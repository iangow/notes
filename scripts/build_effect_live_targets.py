#!/usr/bin/env python3
"""Backfill missing EFFECT observations from previously selected live JSON blocks."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string


def select_targets(c):
    c.execute("""
        CREATE TABLE selected_blocks AS
        SELECT source_file FROM step5.target_blocks
        UNION SELECT source_file FROM step7.target_blocks;
        CREATE TABLE candidate_rows AS
        SELECT c.cik,c.accessionNumber,c.source_file,c.form,c.raw_clock
        FROM workflow.comparison c JOIN selected_blocks b USING(source_file)
        WHERE c.form='EFFECT' AND NOT EXISTS (
            SELECT 1 FROM evidence.live_json_timestamp_observations o
            WHERE o.accession_number=c.accessionNumber
        );
        CREATE TABLE target_blocks AS
        SELECT source_file,count(*) candidate_rows FROM candidate_rows GROUP BY 1;
        CREATE TABLE metadata AS SELECT now() AS created_at,'EFFECT' AS only_form;
    """)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--step5-targets',type=Path,required=True)
    p.add_argument('--step7-targets',type=Path,required=True)
    p.add_argument('--workflow-database',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute('SET threads=4; SET enable_progress_bar=false')
        for alias,path in [('step5',args.step5_targets),('step7',args.step7_targets),
                           ('workflow',args.workflow_database),('evidence',args.database)]:
            c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
        select_targets(c)
        print('Rows, accessions, blocks, CIKs:',c.execute('''
            SELECT count(*),count(DISTINCT accessionNumber),count(DISTINCT source_file),
                   count(DISTINCT cik) FROM candidate_rows
        ''').fetchone())


if __name__=='__main__':
    main()
