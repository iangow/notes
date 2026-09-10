#!/usr/bin/env python3
"""Collect and promote exact SGML evidence for a frozen accession queue."""

import argparse
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT, fetch_sgml
from compare_filing_timestamp_sources import sql_string
from fetch_sgml_anchors import NetworkRateLimiter, insert_sgml_observation


def save(args, fetched, accessions):
    deadline=time.monotonic()+300
    while True:
        try:
            c=duckdb.connect(str(args.database))
            break
        except duckdb.IOException:
            if time.monotonic()>=deadline:
                raise
            time.sleep(1)
    with c:
        initialize_database(c)
        c.execute(f'ATTACH {sql_string(args.queue)} AS q (READ_ONLY)')
        c.execute('BEGIN TRANSACTION')
        for cik,accession,result in fetched:
            insert_sgml_observation(c,cik,accession,result)
        if args.audit_only:
            c.commit()
            return
        c.execute("""
            INSERT INTO submission_overrides
              (accession_number,cik,zip_acceptance_datetime,corrected_acceptance_datetime,
               interpretation,evidence_source,source_url,reason,updated_at)
            WITH selected AS (
              SELECT accessionNumber accession,min(cik) cik,min(raw_clock) raw_clock
              FROM q.candidate_rows WHERE accessionNumber IN (SELECT unnest(?))
              GROUP BY accessionNumber
            )
            SELECT r.accession,r.cik,r.raw_clock,s.acceptance_datetime,
                   CASE WHEN r.raw_clock=s.acceptance_datetime THEN 'eastern'
                     WHEN (r.raw_clock AT TIME ZONE 'UTC')=(s.acceptance_datetime AT TIME ZONE 'America/New_York')
                     THEN 'utc' ELSE 'anomalous' END,
                   'sgml',s.source_url,'SGML check selected by frozen JSON-only outside-hours queue.',now()
            FROM selected r JOIN sgml_observations s ON s.accession_number=r.accession
            WHERE s.acceptance_datetime IS NOT NULL AND s.error IS NULL
            ON CONFLICT(accession_number) DO UPDATE SET
              corrected_acceptance_datetime=excluded.corrected_acceptance_datetime,
              zip_acceptance_datetime=excluded.zip_acceptance_datetime,
              interpretation=excluded.interpretation,evidence_source=excluded.evidence_source,
              source_url=excluded.source_url,reason=excluded.reason,updated_at=excluded.updated_at
        """,[accessions])
        c.commit()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--rate',type=float,default=8)
    p.add_argument('--batch-size',type=int,default=50)
    p.add_argument('--max-fetches',type=int)
    p.add_argument('--audit-only',action='store_true',help='Cache SGML observations without promoting exact overrides.')
    p.add_argument('--shuffle-seed',type=int,help='Shuffle the queue reproducibly before applying the fetch limit.')
    p.add_argument('--retry-errors',action='store_true')
    p.add_argument('--retry-transient-only',action='store_true',
                   help='Retry only cached HTTP 503 failures and timeouts; skip missing tags.')
    args=p.parse_args()
    if min(args.workers,args.rate,args.batch_size)<=0 or (args.max_fetches is not None and args.max_fetches<0):
        p.error('Invalid worker count, rate, batch size, or fetch limit')
    with duckdb.connect(str(args.database),read_only=True) as c:
        c.execute(f'ATTACH {sql_string(args.queue)} AS q (READ_ONLY)')
        rows=c.execute("""
            SELECT q.cik,q.accession_number,s.accession_number IS NOT NULL AS cached,
                   s.acceptance_datetime IS NOT NULL AND s.error IS NULL AS valid,s.error
            FROM q.sgml_queue q LEFT JOIN sgml_observations s USING(accession_number)
            ORDER BY q.latest_clock DESC,q.accession_number
        """).fetchall()
    cached=[r[1] for r in rows if r[2] and r[3]]
    pending=[(r[0],r[1]) for r in rows if not r[2] or (args.retry_errors and not r[3])]
    if args.retry_transient_only:
        pending=[(r[0],r[1]) for r in rows if r[4] and
                 ('HTTP Error 503' in r[4] or r[4].startswith('TimeoutError:'))]
    if args.shuffle_seed is not None:
        random.Random(args.shuffle_seed).shuffle(pending)
    if args.max_fetches is not None:
        pending=pending[:args.max_fetches]
    print(f'Queue={len(rows):,}; cached timestamps={len(cached):,}; fetching={len(pending):,}',flush=True)
    for offset in range(0,0 if args.retry_transient_only or args.audit_only else len(cached),500):
        save(args,[],cached[offset:offset+500])
    limiter=NetworkRateLimiter(1/args.rate)
    def fetch(row):
        cik,accession=row
        limiter.wait()
        return cik,accession,fetch_sgml(cik,accession,DEFAULT_USER_AGENT)
    started=time.monotonic()
    errors=0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for offset in range(0,len(pending),args.batch_size):
            batch=pending[offset:offset+args.batch_size]
            fetched=list(pool.map(fetch,batch))
            save(args,fetched,[a for _,a in batch])
            failures=[(a,r['error']) for _,a,r in fetched if r['error']]
            errors+=len(failures)
            print(f'Progress={offset+len(batch):,}/{len(pending):,}; errors={errors}; elapsed={time.monotonic()-started:.1f}s; batch_errors={failures}',flush=True)
    print('Finished; SGML observations cached; Parquet unchanged.' if args.audit_only
          else 'Finished; exact overrides stored; Parquet unchanged.',flush=True)


if __name__=='__main__':
    main()
