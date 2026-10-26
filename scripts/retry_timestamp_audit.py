#!/usr/bin/env python3
"""Recheck unavailable frozen audit references, preserving predictions and attempts."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import duckdb

from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT, fetch_sgml
from compare_filing_timestamp_sources import sql_string
from fetch_sgml_anchors import NetworkRateLimiter
from report_paired_timestamp_audit import summarize


def retryable(error):
    return bool(error and ('HTTP Error 503' in error or 'HTTP Error 502' in error
                          or error.startswith(('TimeoutError:', 'IncompleteRead:'))))


def finish(con):
    con.execute('''
        CREATE OR REPLACE TABLE latest AS SELECT * FROM attempts
        QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY attempt DESC)=1;
        CREATE OR REPLACE TABLE outcomes AS
        SELECT o.* REPLACE (
            CASE WHEN o.verifiable THEN o.sgml_instant ELSE l.acceptance_datetime AT TIME ZONE 'America/New_York' END AS sgml_instant,
            o.verifiable OR coalesce(l.acceptance_datetime IS NOT NULL AND l.error IS NULL,false) AS verifiable,
            CASE WHEN o.verifiable THEN o.error ELSE l.error END AS error,
            coalesce(l.source_url,o.source_url) AS source_url,
            coalesce(l.retrieved_at,o.retrieved_at) AS retrieved_at,
            false AS not_checked),
            o.verifiable original_verifiable,o.error original_error
        FROM original_outcomes o LEFT JOIN latest l ON l.accession_number=o.accessionNumber;
        CREATE OR REPLACE TABLE missing_summary AS SELECT outcomes.error,l.http_status,count(*) sample_rows,
            count(DISTINCT accessionNumber) accessions,min(raw_clock) earliest,max(raw_clock) latest
        FROM outcomes LEFT JOIN latest l ON l.accession_number=outcomes.accessionNumber
        WHERE NOT verifiable GROUP BY outcomes.error,l.http_status;
    ''')
    for table in ('model_outcomes','stratum_results','summary'):
        con.execute(f'DROP TABLE IF EXISTS {table}')
    summarize(con)
    print('Follow-up summary:', con.execute('SELECT * FROM summary').fetchall(), flush=True)
    print('Still unavailable:', con.execute('SELECT * FROM missing_summary').fetchall(), flush=True)


def run(report, output, workers=8, rate=7, rounds=2):
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(output)) as con:
        con.execute("SET TimeZone='UTC'")
        con.execute(f'ATTACH {sql_string(report)} AS original (READ_ONLY)')
        con.execute('CREATE TABLE original_outcomes AS SELECT * FROM original.outcomes')
        for table in ('metadata','versions','strata'):
            con.execute(f'CREATE TABLE {table} AS SELECT * FROM original.{table}')
        con.execute('''CREATE TABLE attempts(accession_number VARCHAR,cik BIGINT,attempt INTEGER,
            acceptance_datetime TIMESTAMP,source_url VARCHAR,retrieved_at TIMESTAMPTZ,
            elapsed_ms DOUBLE,http_status INTEGER,content_sha256 VARCHAR,sgml_header VARCHAR,error VARCHAR)''')
        pending = con.execute('''SELECT min(cik),accessionNumber FROM original_outcomes
            WHERE NOT verifiable GROUP BY accessionNumber ORDER BY min(raw_clock) DESC,accessionNumber''').fetchall()
        limiter = NetworkRateLimiter(1/rate)
        started = time.monotonic()
        def fetch(row):
            cik, accession = row
            limiter.wait()
            return cik, accession, fetch_sgml(cik, accession, DEFAULT_USER_AGENT)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for attempt in range(1, rounds+1):
                print(f'Round {attempt}: fetching {len(pending):,} accessions', flush=True)
                retry = []
                for offset in range(0, len(pending), 50):
                    fetched = list(pool.map(fetch, pending[offset:offset+50]))
                    for cik, accession, result in fetched:
                        con.execute('INSERT INTO attempts VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                            [accession,cik,attempt,result['acceptance'],result['url'],result['retrieved_at'],
                             result['elapsed_ms'],result['status'],result['digest'],result['text'],result['error']])
                        if retryable(result['error']):
                            retry.append((cik, accession))
                    con.commit()
                    print(f'Round {attempt}: {offset+len(fetched):,}/{len(pending):,}; retryable={len(retry):,}; elapsed={time.monotonic()-started:.1f}s', flush=True)
                pending = retry
                if not pending:
                    break
                if attempt < rounds:
                    time.sleep(5)
        finish(con)
    print(f'Preserved original predictions; follow-up report: {output}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--rate', type=float, default=7)
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--report-only', action='store_true', help='Rebuild the report from saved attempts without requests.')
    args = parser.parse_args()
    if min(args.workers,args.rate,args.rounds) <= 0:
        parser.error('Workers, rate and rounds must be positive')
    if args.report_only:
        with duckdb.connect(str(args.output)) as con:
            con.execute("SET TimeZone='UTC'")
            finish(con)
    else:
        run(args.report,args.output,args.workers,args.rate,args.rounds)


if __name__ == '__main__':
    main()
