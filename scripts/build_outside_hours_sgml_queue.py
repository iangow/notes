#!/usr/bin/env python3
"""Freeze an outside-hours SGML queue using JSON evidence only."""

import argparse
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import sql_string


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--live-inference',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--since-date',default='2003-01-01')
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET TimeZone='UTC'; SET threads=4; SET memory_limit='4GB'")
        c.execute(f'ATTACH {sql_string(args.baseline)} AS b (READ_ONLY)')
        c.execute(f'ATTACH {sql_string(args.live_inference)} AS l (READ_ONLY)')
        # Rebuild consensus before SGML validation, so SGML cannot affect selection.
        c.execute("""
            CREATE TEMP TABLE json_file_instants AS
            SELECT accession_number,min(instant) instant FROM l.file_candidates
            GROUP BY accession_number
            HAVING count(DISTINCT instant)=1 AND count(*) FILTER(WHERE instant IS NULL)=0;
        """)
        c.execute("""
            CREATE TABLE candidate_rows AS
            WITH prospective AS (
              SELECT c.cik,c.accessionNumber,c.source_file,c.form,c.raw_clock,
                     coalesce(c.corrected_instant,a.instant,i.instant,
                       c.raw_clock AT TIME ZONE 'America/New_York') prospective_instant,
                     CASE WHEN c.corrected_instant IS NOT NULL THEN 'raw_pair'
                          WHEN a.instant IS NOT NULL THEN 'live_pair'
                          WHEN i.instant IS NOT NULL THEN 'live_file'
                          ELSE 'unresolved_eastern_fallback' END evidence
              FROM b.comparison c LEFT JOIN l.anchors a ON a.accession=c.accessionNumber
              LEFT JOIN json_file_instants i ON i.accession_number=c.accessionNumber
            )
            SELECT *,prospective_instant AT TIME ZONE 'America/New_York' AS local_clock
            FROM prospective WHERE coalesce(form,'')<>'EFFECT'
              AND local_clock>=CAST(? AS TIMESTAMP)
              AND (CAST(local_clock AS TIME)>TIME '22:00:00'
                OR CAST(local_clock AS TIME)<TIME '06:00:00')
        """,[args.since_date])
        c.execute("""
            CREATE TABLE sgml_queue AS
            SELECT accessionNumber accession_number,min(cik) cik,
                   count(*) selected_rows,max(local_clock) latest_clock
            FROM candidate_rows GROUP BY accessionNumber;
            CREATE TABLE selection_metadata AS
            SELECT now() AS created_at,'JSON-only; exclude EFFECT; strictly outside 06:00..22:00 America/New_York' AS policy_description;
        """)
        print('Rows, accessions, blocks, CIKs:',c.execute('SELECT count(*),count(DISTINCT accessionNumber),count(DISTINCT source_file),count(DISTINCT cik) FROM candidate_rows').fetchone())
        print('Evidence:',c.execute('SELECT evidence,count(*) FROM candidate_rows GROUP BY 1').fetchall())


if __name__=='__main__':
    main()
