#!/usr/bin/env python3
"""Infer uniform cached live-file timezones from the first three steps."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from compare_filing_timestamp_sources import sql_string


def infer(con, sgml_file_anchors=False):
    extra_evidence = """
        UNION ALL
        SELECT l.source_url,l.accession_number,l.retrieved_at,
               CASE WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC')=s.instant THEN 'utc'
                    WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York')=s.instant THEN 'eastern'
                    ELSE 'contradiction' END
        FROM live l JOIN sgml_file_anchors s USING(source_url,accession_number)
    """ if sgml_file_anchors else ""
    con.execute(f"""
        CREATE TABLE anchors AS
        SELECT accession, min(instant) instant FROM anchor_inputs
        GROUP BY accession HAVING count(DISTINCT instant)=1;
        CREATE TABLE file_evidence AS
        SELECT l.source_url,l.accession_number,l.retrieved_at,
               CASE WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC')=a.instant THEN 'utc'
                    WHEN (try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York')=a.instant THEN 'eastern'
                    ELSE 'contradiction' END interpretation
        FROM live l JOIN anchors a ON a.accession=l.accession_number
        {extra_evidence};
        CREATE TABLE file_rules AS
        SELECT source_url,min(interpretation) interpretation,
               count(DISTINCT accession_number) evidence_count,
               min(retrieved_at) first_observed,max(retrieved_at) last_observed
        FROM file_evidence GROUP BY source_url
        HAVING count(DISTINCT interpretation)=1 AND min(interpretation)<>'contradiction';
        CREATE TABLE file_candidates AS
        SELECT l.source_url,l.accession_number,
               CASE WHEN r.interpretation='utc'
                 THEN try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'UTC'
                 ELSE try_cast(l.acceptance_datetime_text AS TIMESTAMP) AT TIME ZONE 'America/New_York'
               END instant
        FROM live l JOIN file_rules r USING(source_url);
        CREATE TABLE rejected_accessions AS
        SELECT accession_number FROM file_candidates GROUP BY 1
        HAVING count(DISTINCT instant)<>1 OR count(*) FILTER(WHERE instant IS NULL)>0
        UNION
        SELECT c.accession_number FROM file_candidates c JOIN validation v
          ON v.accession=c.accession_number WHERE c.instant IS DISTINCT FROM v.instant;
        CREATE TABLE inferred_overrides AS
        SELECT accession_number,min(instant) instant,min(source_url) source_url
        FROM file_candidates WHERE accession_number NOT IN (SELECT accession_number FROM rejected_accessions)
        GROUP BY accession_number;
    """)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--promote-overrides',action='store_true')
    p.add_argument('--sgml-anchor-unclassified',action='store_true',
                   help='Use cached SGML anchors for live files lacking a JSON-only timezone rule.')
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as con:
        con.execute("SET TimeZone='UTC'; SET memory_limit='4GB'; SET threads=4")
        con.execute(f'ATTACH {sql_string(args.baseline)} AS baseline (READ_ONLY)')
        con.execute(f'ATTACH {sql_string(args.database)} AS production (READ_ONLY)')
        con.execute("""
            CREATE TEMP TABLE live AS SELECT * FROM production.live_json_timestamp_observations;
            CREATE TEMP TABLE anchor_inputs AS
            SELECT accessionNumber accession,corrected_instant instant FROM baseline.accession_timestamp_overrides
            UNION ALL
            SELECT accession_number,corrected_acceptance_datetime AT TIME ZONE 'America/New_York'
            FROM production.live_json_timestamp_overrides
            WHERE accession_number NOT IN (SELECT accession_number FROM production.live_json_timestamp_conflicts);
            CREATE TEMP TABLE validation AS
            SELECT * FROM anchor_inputs
            UNION ALL SELECT accession_number,acceptance_datetime AT TIME ZONE 'America/New_York'
            FROM production.sgml_observations WHERE acceptance_datetime IS NOT NULL AND error IS NULL
            UNION ALL SELECT accession_number,corrected_acceptance_datetime AT TIME ZONE 'America/New_York'
            FROM production.submission_overrides;
        """)
        infer(con)
        if args.sgml_anchor_unclassified:
            con.execute("""
                CREATE TABLE sgml_anchor_target_files AS
                SELECT DISTINCT source_url FROM live
                WHERE source_url NOT IN (SELECT source_url FROM file_rules);
                CREATE TABLE sgml_file_anchors AS
                SELECT l.source_url,l.accession_number,
                       s.acceptance_datetime AT TIME ZONE 'America/New_York' instant
                FROM live l JOIN sgml_anchor_target_files t USING(source_url)
                JOIN production.sgml_observations s USING(accession_number)
                WHERE s.acceptance_datetime IS NOT NULL AND s.error IS NULL;
            """)
            for table in ('anchors','file_evidence','file_rules','file_candidates',
                          'rejected_accessions','inferred_overrides'):
                con.execute(f'DROP TABLE {table}')
            infer(con, sgml_file_anchors=True)
        con.execute("""
            CREATE TABLE incremental AS
            SELECT c.*,i.instant inferred_instant FROM baseline.comparison c
            JOIN inferred_overrides i ON i.accession_number=c.accessionNumber
            WHERE c.corrected_instant IS NULL
              AND NOT EXISTS(SELECT 1 FROM anchors a WHERE a.accession=c.accessionNumber);
        """)
        print('File rules:',con.execute('SELECT interpretation,count(*) FROM file_rules GROUP BY 1').fetchall(),flush=True)
        print('Rejected accessions:',con.execute('SELECT count(*) FROM rejected_accessions').fetchone(),flush=True)
        print('Incremental accessions, rows, shifts, matches reference:',con.execute("""
            SELECT count(DISTINCT accessionNumber),count(*),
              count(*) FILTER(WHERE inferred_instant IS DISTINCT FROM raw_clock AT TIME ZONE 'America/New_York'),
              count(*) FILTER(WHERE inferred_instant=reference_instant) FROM incremental
        """).fetchone(),flush=True)
        print('Disagreements:',con.execute("""SELECT reference_provenance,count(*) FROM incremental
            WHERE inferred_instant IS DISTINCT FROM reference_instant GROUP BY 1""").fetchall(),flush=True)
    if args.promote_overrides:
        with duckdb.connect(str(args.database)) as con:
            initialize_database(con)
            con.execute(f'ATTACH {sql_string(args.output)} AS analysis (READ_ONLY)')
            con.execute("""
                BEGIN TRANSACTION;
                DELETE FROM live_json_file_overrides;
                INSERT INTO live_json_file_overrides
                SELECT accession_number,instant AT TIME ZONE 'America/New_York',
                       'live_file_inferred',source_url,now() FROM analysis.inferred_overrides;
                COMMIT;
            """)
            print('Promoted inferred accession table; Parquet unchanged.')


if __name__=='__main__':
    main()
