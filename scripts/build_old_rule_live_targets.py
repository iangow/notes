#!/usr/bin/env python3
"""Use unreproduced old-rule corrections to select live JSON blocks."""

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
        c.execute('SET enable_progress_bar=false; SET threads=4')
        for alias,path in [('b',args.baseline),('l',args.live_inference),('q',args.sgml_queue),('e',args.database)]:
            c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
        c.execute("""
            CREATE TABLE candidate_rows AS
            WITH sgml AS (
              SELECT s.accession_number,s.acceptance_datetime AT TIME ZONE 'America/New_York' instant
              FROM q.sgml_queue q JOIN e.sgml_observations s USING(accession_number)
              WHERE s.acceptance_datetime IS NOT NULL AND s.error IS NULL
            )
            SELECT c.* FROM b.comparison c
            LEFT JOIN l.anchors a ON a.accession=c.accessionNumber
            LEFT JOIN l.inferred_overrides i ON i.accession_number=c.accessionNumber
            LEFT JOIN sgml s ON s.accession_number=c.accessionNumber
            WHERE c.reference_provenance IN ('block_rule','cik_rule','segment_rule')
              AND coalesce(s.instant,c.corrected_instant,a.instant,i.instant) IS NULL
              AND (c.raw_clock AT TIME ZONE 'America/New_York') IS DISTINCT FROM c.reference_instant;
            CREATE TABLE target_blocks AS
            SELECT source_file,count(*) candidate_rows FROM candidate_rows GROUP BY source_file;
            CREATE TABLE metadata AS SELECT now() AS created_at;
        """)
        print(c.execute('SELECT count(*),count(DISTINCT source_file),count(DISTINCT cik) FROM candidate_rows').fetchone())


if __name__=='__main__':
    main()
