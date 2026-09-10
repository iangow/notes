#!/usr/bin/env python3
"""Resolve differing ZIP/live JSON clocks by exact timezone conversion."""

import argparse
import json
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import duckdb
import pyarrow as pa

from acceptance_timestamp_db import DATA_DIR, DEFAULT_DB, initialize_database
from fetch_sgml_anchors import NetworkRateLimiter
from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT
from build_acceptance_timestamp_rules import snapshot_id
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP


def compare_clocks(con):
    con.execute("""
        CREATE OR REPLACE TEMP TABLE comparisons AS
        WITH clocks AS (
          SELECT *, try_cast(zip_text AS TIMESTAMP) AS z,
                    try_cast(live_text AS TIMESTAMP) AS l
          FROM input_clocks
        ), paired AS (
          SELECT *, (z AT TIME ZONE 'UTC') =
                    (l AT TIME ZONE 'America/New_York') AS zip_utc,
                    (z AT TIME ZONE 'America/New_York') =
                    (l AT TIME ZONE 'UTC') AS live_utc
          FROM clocks
        )
        SELECT *, CASE
                 WHEN z IS NULL OR l IS NULL THEN 'invalid'
                 WHEN z = l THEN 'unchanged'
                 WHEN zip_utc AND NOT live_utc THEN 'zip_utc'
                 WHEN live_utc AND NOT zip_utc THEN 'live_utc'
                 ELSE 'unexplained' END AS status,
               CASE WHEN zip_utc AND NOT live_utc THEN l
                    WHEN live_utc AND NOT zip_utc THEN z END AS corrected
        FROM paired
    """)


def fetch_block(item, limiter, follow_history=False):
    block, rows = item
    try:
        if Path(block).name != block or not block.startswith('CIK'):
            raise ValueError(f'Invalid block: {block}')
        url = f'https://data.sec.gov/submissions/{block}'
        request = urllib.request.Request(url, headers={'User-Agent': DEFAULT_USER_AGENT})
        limiter.wait()
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.load(response)
        records = data.get('filings', {}).get('recent', data)
        live = dict(zip(records['accessionNumber'], records['acceptanceDateTime'], strict=True))
        locations = {a:url for a in live}
        if follow_history:
            missing={a for _,a,_ in rows if a not in live}
            root=data
            if missing and '-submissions-' in block:
                root_url=f'https://data.sec.gov/submissions/CIK{rows[0][0]:010d}.json'
                limiter.wait()
                with urllib.request.urlopen(urllib.request.Request(root_url,headers={'User-Agent':DEFAULT_USER_AGENT}),timeout=30) as response:
                    root=json.load(response)
                recent=root.get('filings',{}).get('recent',{})
                for a,clock in zip(recent.get('accessionNumber',[]),recent.get('acceptanceDateTime',[]),strict=True):
                    if a in missing:
                        live[a]=clock
                        locations[a]=root_url
                        missing.remove(a)
            for ref in root.get('filings',{}).get('files',[]):
                if not missing:
                    break
                name=ref['name']
                if Path(name).name!=name or not name.startswith('CIK'):
                    raise ValueError(f'Invalid historical filename: {name}')
                history_url=f'https://data.sec.gov/submissions/{name}'
                if history_url==url:
                    continue
                limiter.wait()
                with urllib.request.urlopen(urllib.request.Request(history_url,headers={'User-Agent':DEFAULT_USER_AGENT}),timeout=30) as response:
                    history=json.load(response)
                for a,clock in zip(history['accessionNumber'],history['acceptanceDateTime'],strict=True):
                    if a in missing:
                        live[a]=clock
                        locations[a]=history_url
                        missing.remove(a)
        matched = [(cik, accession, clock, live[accession], locations[accession])
                   for cik, accession, clock in rows if accession in live]
        return matched, (block, len(matched), len(rows)-len(matched), None)
    except Exception as exc:
        partial = [(cik,a,clock,live[a],locations[a]) for cik,a,clock in rows if a in live] if 'locations' in locals() else []
        return partial, (block, len(partial), len(rows)-len(partial), str(exc))


def write_batch(args, snapshot, results):
    inputs = [row for matched, _ in results for row in matched]

    deadline = time.monotonic() + args.write_lock_timeout
    while True:
        try:
            con = duckdb.connect(str(args.database), read_only=not args.promote_overrides)
            break
        except duckdb.IOException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    with con:
        if args.promote_overrides:
            initialize_database(con)
        columns = ('cik', 'accession', 'zip_text', 'live_text', 'url')
        arrays = [pa.array([row[i] for row in inputs], type=pa.int64() if i == 0 else pa.string())
                  for i in range(5)]
        con.register('input_clocks', pa.Table.from_arrays(arrays, names=columns))
        compare_clocks(con)
        print(con.execute('SELECT status, count(*) FROM comparisons GROUP BY status ORDER BY status').fetchall())
        if args.promote_overrides:
            con.execute("""
                CREATE TEMP TABLE candidates AS
                SELECT accession, min(cik) cik, min(corrected) corrected,
                       first(z) FILTER (WHERE corrected IS NOT NULL) z,
                       first(l) FILTER (WHERE corrected IS NOT NULL) l,
                       first(url) FILTER (WHERE corrected IS NOT NULL) url,
                       first(CASE WHEN status='zip_utc' THEN 'utc' ELSE 'eastern' END)
                         FILTER (WHERE corrected IS NOT NULL) interpretation
                FROM comparisons
                GROUP BY accession
                HAVING count(DISTINCT corrected) = 1
                   AND count(*) FILTER (WHERE status IN ('invalid','unexplained')) = 0
            """)
            con.execute("""
                CREATE TEMP TABLE conflicts AS
                SELECT DISTINCT c.accession
                FROM candidates c JOIN (
                  SELECT accession_number, corrected_acceptance_datetime FROM submission_overrides
                  UNION ALL
                  SELECT accession_number, corrected_acceptance_datetime FROM duplicate_accession_timestamp_overrides
                  UNION ALL
                  SELECT accession_number, corrected_acceptance_datetime FROM live_json_timestamp_overrides
                ) e ON c.accession=e.accession_number
                WHERE c.corrected <> e.corrected_acceptance_datetime
                UNION
                SELECT accession FROM comparisons GROUP BY accession
                HAVING count(DISTINCT corrected)>1
            """)
            print('Existing correction conflicts:', con.execute('SELECT * FROM conflicts').fetchall())
            con.execute('BEGIN TRANSACTION')
            con.execute("""
                    INSERT INTO live_json_timestamp_conflicts
                    SELECT accession, now() FROM conflicts
                    ON CONFLICT (accession_number) DO NOTHING
            """)
            con.execute("""
                    INSERT INTO live_json_timestamp_observations
                    SELECT DISTINCT url,accession,live_text,now() FROM input_clocks
                    ON CONFLICT (source_url, accession_number) DO UPDATE SET
                    acceptance_datetime_text=excluded.acceptance_datetime_text,
                    retrieved_at=excluded.retrieved_at
            """)
            con.execute("""
                INSERT INTO live_json_timestamp_overrides
                SELECT accession,cik,corrected,interpretation,z,l,url,now()
                FROM candidates WHERE accession NOT IN (SELECT accession FROM conflicts)
                ON CONFLICT (accession_number) DO NOTHING
            """)
            con.executemany("""
                INSERT INTO live_json_comparison_runs VALUES (?,?,?,?,?,now())
                ON CONFLICT (snapshot_id,block_name) DO UPDATE SET
                  matched=excluded.matched,missing=excluded.missing,
                  error=excluded.error,checked_at=excluded.checked_at
            """, [(snapshot, *report) for _, report in results])
            con.commit()
            print('Consistent accession candidates:', con.execute('SELECT count(*) FROM candidates WHERE accession NOT IN (SELECT accession FROM conflicts)').fetchone()[0])


def comparison_rows(con, snapshot, blocks, only_form=None):
    return con.execute("""
        SELECT block_name,cik,accession_number,zip_acceptance_datetime_text
        FROM zip_filing_records WHERE snapshot_id=?
          AND block_name IN (SELECT unnest(?))
          AND (? IS NULL OR form=?)
    """,[snapshot,blocks,only_form,only_form]).fetchall()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--block-name', action='append')
    selection.add_argument('--all-outside-hours', action='store_true')
    selection.add_argument('--baseline', type=Path,
                           help='Select unresolved outside-hours blocks from a pair-baseline database.')
    selection.add_argument('--target-database',type=Path,
                           help='Read source_file values from target_blocks in an analysis database.')
    parser.add_argument('--follow-history',action='store_true',help='Search linked historical JSON files for missing accessions.')
    parser.add_argument('--include-correspondence', action='store_true',
                        help='Allow correspondence forms in outside-hours targeting; comparison includes all forms.')
    parser.add_argument('--only-form',help='Compare only this form in explicitly selected blocks (for backfills).')
    parser.add_argument('--list-only', action='store_true', help='Count targets without fetching or writing.')
    parser.add_argument('--filings', type=Path, default=DATA_DIR/'edgar'/'filings.parquet')
    parser.add_argument('--since-date', default='2003-01-01')
    parser.add_argument('--database', type=Path, default=DEFAULT_DB)
    parser.add_argument('--zip', type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument('--promote-overrides', action='store_true')
    parser.add_argument('--include-done', action='store_true')
    parser.add_argument('--max-blocks', type=int)
    parser.add_argument('--batch-blocks', type=int, default=50)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--max-requests-per-second', type=float, default=8)
    parser.add_argument('--write-lock-timeout', type=float, default=300)
    args = parser.parse_args()
    if args.only_form and (args.baseline or args.all_outside_hours):
        parser.error('--only-form requires explicit blocks or a target database')
    if min(args.batch_blocks,args.workers,args.max_requests_per_second,args.write_lock_timeout)<=0:
        parser.error('Batch size, workers, rate, and timeout must be positive')
    if args.max_blocks is not None and args.max_blocks<1:
        parser.error('--max-blocks must be positive')
    snapshot = snapshot_id(args.zip.expanduser().resolve())
    started = time.monotonic()
    excluded_forms = "'EFFECT'" if args.include_correspondence else "'EFFECT','CORRESP','UPLOAD','DRSLTR'"
    if args.promote_overrides and not args.list_only:
        with duckdb.connect(str(args.database)) as con:
            initialize_database(con)
    with duckdb.connect(str(args.database), read_only=True) as con:
        target_since=None
        if args.target_database:
            with duckdb.connect(str(args.target_database),read_only=True) as target_db:
                targets=[r[0] for r in target_db.execute('SELECT source_file FROM target_blocks ORDER BY source_file').fetchall()]
                target_since=target_db.execute('SELECT created_at FROM metadata').fetchone()[0]
        elif args.baseline:
            with duckdb.connect(str(args.baseline), read_only=True) as baseline:
                targets = [r[0] for r in baseline.execute(f"""
                    SELECT source_file FROM comparison
                    WHERE corrected_instant IS NULL AND raw_clock>=CAST(? AS TIMESTAMP)
                      AND coalesce(form,'') NOT IN ({excluded_forms})
                      AND (CAST(raw_clock AS TIME)>TIME '22:00:00'
                        OR CAST(raw_clock AS TIME)<TIME '06:00:00')
                    GROUP BY source_file ORDER BY max(raw_clock) DESC,source_file
                """, [args.since_date]).fetchall()]
        elif args.all_outside_hours:
            targets = [r[0] for r in con.execute(f"""
                WITH f AS (
                  SELECT *,acceptanceDateTime AT TIME ZONE 'America/New_York' AS local_time
                  FROM read_parquet(?)
                )
                SELECT source_file FROM f
                WHERE local_time>=CAST(? AS TIMESTAMP)
                  AND coalesce(form,'') NOT IN ({excluded_forms})
                  AND (CAST(local_time AS TIME)>TIME '22:00:00'
                    OR CAST(local_time AS TIME)<TIME '06:00:00')
                GROUP BY source_file ORDER BY max(local_time) DESC,source_file
            """, [str(args.filings),args.since_date]).fetchall()]
        else:
            targets = list(dict.fromkeys(args.block_name))
        if (args.baseline or args.all_outside_hours or args.target_database) and not args.include_done and con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='live_json_comparison_runs'").fetchone()[0]:
            done = {r[0] for r in con.execute('SELECT block_name FROM live_json_comparison_runs WHERE snapshot_id=? AND error IS NULL AND (? IS NULL OR checked_at>=?)',[snapshot,target_since,target_since]).fetchall()}
            targets = [b for b in targets if b not in done]
    if args.max_blocks:
        targets = targets[:args.max_blocks]
    print(f'Target blocks: {len(targets):,}; workers={args.workers}; rate={args.max_requests_per_second}/s',flush=True)
    if args.list_only:
        return
    limiter = NetworkRateLimiter(1/args.max_requests_per_second)
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for offset in range(0,len(targets),args.batch_blocks):
            batch = targets[offset:offset+args.batch_blocks]
            inventory = {b: [] for b in batch}
            with duckdb.connect(str(args.database),read_only=True) as con:
                rows = comparison_rows(con,snapshot,batch,args.only_form)
            for block,*row in rows:
                inventory[block].append(row)
            results = list(executor.map(lambda item: fetch_block(item,limiter,args.follow_history),inventory.items()))
            write_batch(args,snapshot,results)
            failures = [(r[0],r[3]) for _,r in results if r[3]]
            print(f'Progress: {offset+len(batch):,}/{len(targets):,}; matched={sum(r[1] for _,r in results):,}; missing={sum(r[2] for _,r in results):,}; errors={failures}; elapsed={time.monotonic()-started:.1f}s',flush=True)
    print(f'wall_time={time.monotonic()-started:.2f}s')


if __name__ == '__main__':
    main()
