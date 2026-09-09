#!/usr/bin/env python3
"""Freeze accession evidence and evaluate against the reference."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--live-inference',type=Path,required=True)
    p.add_argument('--sgml-queue',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET TimeZone='UTC'; SET threads=4; SET enable_progress_bar=false; SET memory_limit='4GB'")
        for alias,path in [('b',args.baseline),('l',args.live_inference),('q',args.sgml_queue),('e',args.database)]:
            c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
        c.execute("""
            CREATE TABLE inputs AS SELECT * FROM b.inputs;
            CREATE TABLE workflow_metadata AS SELECT now() AS created_at;
            CREATE TABLE accession_evidence AS
            SELECT accessionNumber accession_number,corrected_instant,
                   CASE WHEN evidence='duplicates_only' THEN 'cross_cik_pair' ELSE 'snapshot_pair' END provenance,
                   30 priority FROM b.accession_timestamp_overrides
            UNION ALL SELECT accession,instant,'live_pair',20 FROM l.anchors
            WHERE accession NOT IN (SELECT accessionNumber FROM b.accession_timestamp_overrides)
            UNION ALL SELECT accession_number,instant,'live_file_inferred',10 FROM l.inferred_overrides
            UNION ALL
            SELECT s.accession_number,s.acceptance_datetime AT TIME ZONE 'America/New_York','sgml',40
            FROM q.sgml_queue q JOIN e.sgml_observations s USING(accession_number)
            WHERE s.acceptance_datetime IS NOT NULL AND s.error IS NULL;
            CREATE TABLE evidence_disagreements AS
            SELECT accession_number,count(DISTINCT corrected_instant) instant_count
            FROM accession_evidence GROUP BY 1 HAVING count(DISTINCT corrected_instant)>1;
            CREATE TABLE resolved_accessions AS
            SELECT accession_number,corrected_instant,provenance FROM accession_evidence
            QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY priority DESC)=1;
            CREATE UNIQUE INDEX resolved_accession_key ON resolved_accessions(accession_number);
            CREATE TABLE comparison AS
            SELECT b.cik,b.accessionNumber,b.source_file,b.form,b.raw_clock,
                   b.reference_instant,b.reference_provenance,r.provenance,
                   r.corrected_instant,
                   coalesce(r.corrected_instant,b.raw_clock AT TIME ZONE 'America/New_York') prospective_instant
            FROM b.comparison b LEFT JOIN resolved_accessions r ON r.accession_number=b.accessionNumber;
            CREATE TABLE summary AS
            SELECT count(*) rows_n,count(corrected_instant) supported_rows,
              count(*) FILTER(WHERE prospective_instant=reference_instant) matching_rows,
              count(*) FILTER(WHERE corrected_instant IS NULL AND prospective_instant IS DISTINCT FROM reference_instant) missing_corrections,
              count(*) FILTER(WHERE corrected_instant IS NOT NULL AND prospective_instant IS DISTINCT FROM reference_instant) evidence_differences
            FROM comparison;
        """)
        print('Summary:',c.execute('SELECT * FROM summary').fetchone())
        print('Evidence disagreements:',c.execute('SELECT count(*) FROM evidence_disagreements').fetchone()[0])
        print('Provenance:',c.execute('SELECT provenance,count(*) FROM comparison GROUP BY 1 ORDER BY 2 DESC').fetchall())
    print(f'Frozen workflow database: {args.output}')


if __name__=='__main__':
    main()
