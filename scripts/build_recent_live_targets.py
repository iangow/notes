#!/usr/bin/env python3
"""Select unresolved recent filings without cached live clocks, independently of a reference."""

import argparse
from datetime import date
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string


def select_targets(c, since):
    c.execute("""
        CREATE TABLE candidate_rows AS
        SELECT c.cik,c.accessionNumber,c.source_file,c.form,c.raw_clock
        FROM workflow.comparison c
        WHERE c.corrected_instant IS NULL AND c.raw_clock >= ?
          AND NOT EXISTS (
            SELECT 1 FROM evidence.live_json_timestamp_observations l
            WHERE l.accession_number=c.accessionNumber
          );
    """, [since])
    c.execute("""
        CREATE TABLE target_blocks AS
        SELECT source_file,count(*) candidate_rows FROM candidate_rows GROUP BY source_file;
        CREATE TABLE metadata AS SELECT now() AS created_at;
    """)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workflow-database',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--since-date',type=date.fromisoformat,default=date(2024,1,1))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute('SET threads=4; SET enable_progress_bar=false')
        c.execute(f'ATTACH {sql_string(args.workflow_database)} AS workflow (READ_ONLY)')
        c.execute(f'ATTACH {sql_string(args.database)} AS evidence (READ_ONLY)')
        select_targets(c,args.since_date)
        c.execute('ALTER TABLE metadata ADD COLUMN since_date DATE')
        c.execute('UPDATE metadata SET since_date=?',[args.since_date])
        print('Rows, accessions, blocks, CIKs:',c.execute('''
            SELECT count(*),count(DISTINCT accessionNumber),count(DISTINCT source_file),
                   count(DISTINCT cik) FROM candidate_rows
        ''').fetchone())


if __name__=='__main__':
    main()
