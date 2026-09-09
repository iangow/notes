#!/usr/bin/env python3
"""Promote cached SGML evidence for residual outside-hours accessions."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DATA_DIR, DEFAULT_DB, initialize_database
from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT, fetch_sgml
from fetch_sgml_anchors import NetworkRateLimiter, insert_sgml_observation


def residuals(con, filings):
    con.execute("""
        CREATE TEMP TABLE residuals AS
        SELECT *, acceptanceDateTime AT TIME ZONE 'America/New_York' AS local_ts
        FROM read_parquet(?)
        WHERE local_ts >= TIMESTAMP '2003-01-01'
          AND coalesce(form,'') NOT IN ('EFFECT','CORRESP','UPLOAD','DRSLTR')
          AND (CAST(local_ts AS TIME)>TIME '22:00:00'
            OR CAST(local_ts AS TIME)<TIME '06:00:00')
    """, [str(filings)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=DEFAULT_DB)
    parser.add_argument('--filings', type=Path, default=DATA_DIR/'edgar'/'filings.parquet')
    parser.add_argument('--raw', type=Path, default=DATA_DIR/'edgar'/'filings_raw.parquet')
    parser.add_argument('--fetch-identical', type=int, default=0,
                        help='Check this many recent identical ZIP/live cases, one per block.')
    parser.add_argument('--promote-overrides', action='store_true')
    args = parser.parse_args()
    if args.fetch_identical < 0:
        parser.error('--fetch-identical must be nonnegative')
    fetched = []
    if args.fetch_identical:
        with duckdb.connect(str(args.database), read_only=True) as con:
            residuals(con, args.filings)
            targets = con.execute("""
                SELECT f.cik,f.accessionNumber,f.source_file,f.local_ts,
                       try_cast(r.acceptanceDateTime AS TIMESTAMP) raw_ts
                FROM residuals f
                JOIN read_parquet(?) r USING (source_file,accessionNumber)
                JOIN live_json_timestamp_observations l
                  ON l.accession_number=f.accessionNumber
                 AND l.source_url='https://data.sec.gov/submissions/'||f.source_file
                LEFT JOIN sgml_observations s ON s.accession_number=f.accessionNumber
                WHERE try_cast(l.acceptance_datetime_text AS TIMESTAMP)=raw_ts
                  AND s.acceptance_datetime IS NULL
                QUALIFY row_number() OVER (PARTITION BY f.source_file ORDER BY f.local_ts DESC)=1
                ORDER BY f.local_ts DESC,f.source_file LIMIT ?
            """, [str(args.raw),args.fetch_identical]).fetchall()
        limiter = NetworkRateLimiter(0.125)
        for cik,accession,block,local_ts,raw_ts in targets:
            limiter.wait()
            result = fetch_sgml(cik,accession,DEFAULT_USER_AGENT)
            fetched.append((cik,accession,result))
            print(f'{block} {accession}: output={local_ts}; ZIP/live={raw_ts}; SGML={result["acceptance"]}; error={result["error"]}',flush=True)

    with duckdb.connect(str(args.database),read_only=not args.promote_overrides) as con:
        if args.promote_overrides:
            initialize_database(con)
            con.execute('BEGIN TRANSACTION')
            for cik,accession,result in fetched:
                insert_sgml_observation(con,cik,accession,result)
        residuals(con,args.filings)
        con.execute("""
            CREATE TEMP TABLE candidates AS
            SELECT f.accessionNumber accession,first(f.cik) cik,
                   first(try_cast(r.acceptanceDateTime AS TIMESTAMP)) zip_ts,
                   first(s.acceptance_datetime) corrected,first(s.source_url) source_url,
                   count(*) affected_rows
            FROM residuals f
            JOIN read_parquet(?) r USING (source_file,accessionNumber)
            JOIN sgml_observations s ON s.accession_number=f.accessionNumber
            WHERE s.acceptance_datetime IS NOT NULL AND s.error IS NULL
              AND try_cast(r.acceptanceDateTime AS TIMESTAMP) IS NOT NULL
              AND f.local_ts<>s.acceptance_datetime
            GROUP BY f.accessionNumber
        """,[str(args.raw)])
        print('Corrections (accessions, residual rows):',con.execute('SELECT count(*),sum(affected_rows) FROM candidates').fetchone())
        if args.promote_overrides:
            con.execute("""
                INSERT INTO submission_overrides
                  (accession_number,cik,zip_acceptance_datetime,corrected_acceptance_datetime,
                   interpretation,evidence_source,source_url,reason,updated_at)
                SELECT accession,cik,zip_ts,corrected,
                       CASE WHEN zip_ts=corrected THEN 'eastern'
                         WHEN (zip_ts AT TIME ZONE 'UTC')=(corrected AT TIME ZONE 'America/New_York')
                         THEN 'utc' ELSE 'anomalous' END,
                       'sgml',source_url,'Direct SGML evidence for residual outside-hours row.',now()
                FROM candidates
                ON CONFLICT(accession_number) DO UPDATE SET
                  cik=excluded.cik,zip_acceptance_datetime=excluded.zip_acceptance_datetime,
                  corrected_acceptance_datetime=excluded.corrected_acceptance_datetime,
                  interpretation=excluded.interpretation,evidence_source=excluded.evidence_source,
                  source_url=excluded.source_url,reason=excluded.reason,updated_at=excluded.updated_at
            """)
            con.commit()


if __name__ == '__main__':
    main()
