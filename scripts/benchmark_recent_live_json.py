#!/usr/bin/env python3
"""Time a reproducible live-JSON trial selected independently of audit errors."""

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path
import threading
import time

import duckdb
import pyarrow as pa

from bootstrap_timestamp_workflow import SUPPORTED_PROVENANCE
from compare_filing_timestamp_sources import sql_string
from compare_live_json_timestamps import compare_clocks, fetch_block
from fetch_sgml_anchors import NetworkRateLimiter
from infer_live_file_timezones import infer
from timestamp_parquet_archive import digest


class CountingLimiter:
    def __init__(self, rate):
        self.limiter = NetworkRateLimiter(1 / rate)
        self.local = threading.local()

    def wait(self):
        self.local.requests = getattr(self.local, 'requests', 0) + 1
        self.limiter.wait()


def save(con, relation, path):
    temporary = path.with_suffix('.partial.parquet')
    temporary.unlink(missing_ok=True)
    con.execute(f'COPY {relation} TO ? (FORMAT PARQUET, COMPRESSION ZSTD)', [str(temporary)])
    temporary.rename(path)


def select(con, filings, raw, output, since, sample_blocks, seed):
    con.execute('''CREATE TABLE candidate_rows AS
        SELECT cik,accessionNumber,source_file,form,acceptanceDateTime predicted
        FROM read_parquet(?)
        WHERE timestamp_provenance IN ('unresolved_raw_as_eastern',
                                      'special_form_unresolved_raw_as_eastern')
          AND acceptanceDateTime AT TIME ZONE 'America/New_York' >= ?''',
        [str(filings), since])
    con.execute('''CREATE TABLE target_blocks AS
        SELECT source_file,count(*) unresolved_rows FROM candidate_rows GROUP BY 1''')
    population = con.execute('SELECT count(*) FROM target_blocks').fetchone()[0]
    if not population:
        raise ValueError('No unresolved recent blocks')
    n = min(sample_blocks, population)
    con.execute(f'''CREATE TABLE sampled_blocks AS SELECT * FROM target_blocks
        USING SAMPLE reservoir({n} ROWS) REPEATABLE({seed})''')
    con.execute('''CREATE TABLE comparison_rows AS
        SELECT cik,accessionNumber accession_number,source_file,
               acceptanceDateTime zip_text FROM read_parquet(?)
        WHERE source_file IN (SELECT source_file FROM sampled_blocks)''', [str(raw)])
    con.execute('''CREATE TABLE reference_anchors AS
        SELECT accessionNumber accession,min(acceptanceDateTime) instant
        FROM read_parquet(?)
        WHERE timestamp_provenance IN (SELECT unnest(?))
          AND accessionNumber IN (SELECT accession_number FROM comparison_rows)
        GROUP BY accessionNumber
        HAVING count(DISTINCT acceptanceDateTime)=1
           AND count(*) FILTER(WHERE acceptanceDateTime IS NULL)=0''',
        [str(filings), list(SUPPORTED_PROVENANCE)])
    for name in ('candidate_rows', 'target_blocks', 'sampled_blocks', 'comparison_rows', 'reference_anchors'):
        save(con, name, output / (name + '.parquet'))
    return population, n


def restore_selection(con, output, filings, raw, since, sample_blocks, seed, workers, rate):
    metadata = output / 'metadata.parquet'
    if not metadata.exists():
        raise ValueError('Resume requires a previously frozen selection and metadata')
    saved = con.execute('SELECT * FROM read_parquet(?)', [str(metadata)]).fetchall()
    expected = {
        'candidate': (str(filings), digest(filings)),
        'raw': (str(raw), digest(raw)),
    }
    for role, path, _, _, checksum, cutoff, old_seed, old_workers, old_rate, _ in saved:
        if role not in expected or (path, checksum) != expected[role]:
            raise ValueError('Resume requires the original candidate and raw Parquet inputs')
        if cutoff != since or old_seed != seed or old_workers != workers or old_rate != rate:
            raise ValueError('Resume requires the original cutoff, seed, worker count and request rate')
    for name in ('candidate_rows', 'target_blocks', 'sampled_blocks', 'comparison_rows', 'reference_anchors'):
        con.execute(f'CREATE TABLE {name} AS SELECT * FROM read_parquet(?)',
                    [str(output / (name + '.parquet'))])
    population = con.execute('SELECT count(*) FROM target_blocks').fetchone()[0]
    n = con.execute('SELECT count(*) FROM sampled_blocks').fetchone()[0]
    if n != min(sample_blocks, population):
        raise ValueError('Resume requires the original sampled-block count')
    return population, n


def summarize(con, output, population, n, seconds, preparation, rate):
    con.execute('''CREATE TEMP VIEW input_clocks AS
        SELECT cik,accession_number accession,zip_text,
               acceptance_datetime_text live_text,source_url url FROM live''')
    compare_clocks(con)
    con.execute('''CREATE TABLE anchor_inputs AS
        SELECT * FROM reference_anchors
        UNION ALL SELECT accession,corrected AT TIME ZONE 'America/New_York'
            FROM comparisons WHERE status IN ('zip_utc','live_utc');
        CREATE TABLE validation AS SELECT * FROM anchor_inputs;
    ''')
    infer(con, versioned=True)
    con.execute('''CREATE TABLE trial_resolved AS
        WITH evidence AS (
            SELECT accession,instant FROM anchor_inputs
            UNION ALL SELECT accession_number,instant FROM inferred_overrides
        ) SELECT accession,min(instant) instant FROM evidence
        GROUP BY accession HAVING count(DISTINCT instant)=1;
        CREATE TABLE trial_coverage AS
        SELECT c.*,r.instant newly_supported_instant
        FROM candidate_rows c JOIN sampled_blocks USING(source_file)
        LEFT JOIN trial_resolved r ON r.accession=c.accessionNumber;
    ''')
    requests = con.execute('SELECT sum(requests) FROM fetch_results').fetchone()[0]
    matched, missing, errors = con.execute('''SELECT sum(matched),sum(missing),
        count(*) FILTER(WHERE error IS NOT NULL) FROM (
          SELECT * FROM fetch_results
          QUALIFY row_number() OVER(PARTITION BY source_file ORDER BY retrieved_at DESC)=1
        )''').fetchone()
    targeted, supported = con.execute('''SELECT count(*),
        count(newly_supported_instant) FROM trial_coverage''').fetchone()
    con.execute('''CREATE TABLE summary AS SELECT ?::BIGINT population_blocks,
        ?::BIGINT sampled_blocks,?::BIGINT requests,?::BIGINT matched_rows,
        ?::BIGINT missing_rows,?::BIGINT failed_blocks,?::BIGINT targeted_rows,
        ?::BIGINT newly_supported_rows,?::DOUBLE collection_seconds,
        ?::DOUBLE preparation_seconds,?::DOUBLE requests_per_second_limit,
        ?::DOUBLE projected_collection_hours''',
        [population,n,requests,matched,missing,errors,targeted,supported,seconds,
         preparation,rate,seconds * population / n / 3600])
    for name in ('comparisons','file_evidence','file_rules','rejected_accessions',
                 'trial_coverage','summary'):
        save(con, name, output / (name + '.parquet'))
    label = 'Collection' if n == population else 'Trial'
    print(f'{label} summary:', con.execute('SELECT * FROM summary').fetchone(), flush=True)
    print('Clock comparisons:', con.execute('SELECT status,count(*) FROM comparisons GROUP BY 1').fetchall(), flush=True)
    print('Live-file rules:', con.execute('SELECT interpretation,count(*) FROM file_rules GROUP BY 1').fetchall(), flush=True)
    print('Inputs and frozen audit predictions were not changed. Unchanged clocks alone are not timezone evidence.', flush=True)


def benchmark(filings, raw, output, since=date(2024, 1, 1), sample_blocks=200,
              seed=202609301, workers=16, rate=7, resume=False):
    filings, raw, output = filings.resolve(), raw.resolve(), output.resolve()
    if min(sample_blocks, workers, rate) <= 0:
        raise ValueError('Sample size, workers and rate must be positive')
    existed = output.exists()
    if existed and not resume:
        raise FileExistsError(output)
    if resume and not existed:
        raise FileNotFoundError(output)
    output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with duckdb.connect() as con:
        con.execute("SET threads=1; SET memory_limit='2GB'; SET TimeZone='UTC'")
        if resume:
            population, n = restore_selection(con, output, filings, raw, since,
                                               sample_blocks, seed, workers, rate)
        else:
            population, n = select(con, filings, raw, output, since, sample_blocks, seed)
            con.execute('''CREATE TABLE metadata(role VARCHAR,path VARCHAR,size_bytes BIGINT,
                mtime_ns BIGINT,sha256 VARCHAR,since_date DATE,seed BIGINT,
                workers INTEGER,rate DOUBLE,created_at TIMESTAMPTZ)''')
            for role, path in (('candidate', filings), ('raw', raw)):
                stat = path.stat()
                con.execute('INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?,?)',
                    [role,str(path.resolve()),stat.st_size,stat.st_mtime_ns,digest(path),
                     since,seed,workers,rate,datetime.now(timezone.utc)])
            save(con, 'metadata', output / 'metadata.parquet')
        preparation = time.monotonic() - started
        rows = defaultdict(list)
        for cik, accession, block, clock in con.execute('SELECT * FROM comparison_rows ORDER BY source_file,accession_number').fetchall():
            rows[block].append((cik, accession, clock))
        items = [(block, rows[block]) for (block,) in con.execute('SELECT source_file FROM sampled_blocks ORDER BY source_file').fetchall()]
        print(f'Frozen {n:,}/{population:,} blocks; {sum(map(len,rows.values())):,} comparison rows; preparation={preparation:.1f}s', flush=True)
        limiter = CountingLimiter(rate)

        def fetch(item):
            limiter.local.requests = 0
            before = time.monotonic()
            matches, result = fetch_block(item, limiter, follow_history=True)
            return matches, (*result,limiter.local.requests,time.monotonic()-before,datetime.now(timezone.utc))

        con.execute('''CREATE TABLE live(source_url VARCHAR,accession_number VARCHAR,
            acceptance_datetime_text VARCHAR,retrieved_at TIMESTAMPTZ,cik BIGINT,
            zip_text VARCHAR,source_file VARCHAR);
            CREATE TABLE fetch_results(source_file VARCHAR,matched BIGINT,missing BIGINT,
                error VARCHAR,requests BIGINT,elapsed_seconds DOUBLE,retrieved_at TIMESTAMPTZ)''')
        if resume:
            observation_parts = sorted(output.glob('observations-*.parquet'))
            result_parts = sorted(output.glob('fetch_results-*.parquet'))
            if observation_parts:
                con.execute('INSERT INTO live SELECT * FROM read_parquet(?)',
                            [[str(p) for p in observation_parts]])
            if result_parts:
                con.execute('INSERT INTO fetch_results SELECT * FROM read_parquet(?)',
                            [[str(p) for p in result_parts]])
        attempts = {}
        if con.execute('SELECT count(*) FROM fetch_results').fetchone()[0]:
            attempts = {row[0]: (row[1], row[2]) for row in con.execute('''
                SELECT source_file,count(*),arg_max(error,retrieved_at)
                FROM fetch_results GROUP BY source_file
            ''').fetchall()}
        pending = [(block, block_rows) for block, block_rows in items
                   if block not in attempts or
                   (attempts[block][1] is not None and attempts[block][0] < 2)]
        print(f'Previously attempted={len(attempts):,}; queued this run={len(pending):,}', flush=True)
        collection_started = time.monotonic()
        with ThreadPoolExecutor(max_workers=workers) as pool:
            existing_parts = list(output.glob('observations-*.parquet')) + list(output.glob('fetch_results-*.parquet'))
            number = max((int(p.stem.split('-')[-1]) for p in existing_parts),default=0)
            for offset in range(0,len(pending),50):
                results = list(pool.map(fetch, pending[offset:offset+50]))
                con.execute('CREATE OR REPLACE TEMP TABLE batch AS SELECT * FROM live WHERE false')
                con.execute('''CREATE OR REPLACE TEMP TABLE batch_results AS
                    SELECT * FROM fetch_results WHERE false''')
                observations = []
                for matches, result in results:
                    block, *_, retrieved = result
                    con.execute('INSERT INTO batch_results VALUES (?,?,?,?,?,?,?)', result)
                    observations.extend((url,accession,clock,retrieved,cik,zip_text,block)
                                        for cik,accession,zip_text,clock,url in matches)
                if observations:
                    names = ['source_url','accession_number','acceptance_datetime_text',
                             'retrieved_at','cik','zip_text','source_file']
                    types = [pa.string(),pa.string(),pa.string(),pa.timestamp('us',tz='UTC'),
                             pa.int64(),pa.string(),pa.string()]
                    table = pa.Table.from_arrays([
                        pa.array([row[i] for row in observations],type=kind)
                        for i,kind in enumerate(types)],names=names)
                    con.register('incoming_live',table)
                    con.execute('INSERT INTO batch SELECT * FROM incoming_live')
                    con.unregister('incoming_live')
                number += 1
                save(con, 'batch', output / f'observations-{number:05d}.parquet')
                save(con, 'batch_results', output / f'fetch_results-{number:05d}.parquet')
                con.execute('INSERT INTO live SELECT * FROM batch')
                con.execute('INSERT INTO fetch_results SELECT * FROM batch_results')
                completed = min(len(attempts) + offset + len(results), n)
                print(f'Blocks {completed:,}/{n:,}; collection elapsed={time.monotonic()-collection_started:.1f}s', flush=True)
        seconds = time.monotonic() - collection_started
        save(con, 'live', output / 'live_json_timestamp_observations.parquet')
        save(con, 'fetch_results', output / 'fetch_results.parquet')
        summarize(con, output, population, n, seconds, preparation, rate)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filings', type=Path, required=True)
    parser.add_argument('--raw', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--since-date', type=date.fromisoformat, default=date(2024,1,1))
    parser.add_argument('--sample-blocks', type=int, default=200)
    parser.add_argument('--all-unresolved-blocks', action='store_true',
                        help='Collect every unresolved CIK file on or after the cutoff date')
    parser.add_argument('--seed', type=int, default=202609301)
    parser.add_argument('--workers', type=int, default=16)
    parser.add_argument('--rate', type=float, default=7)
    parser.add_argument('--resume', action='store_true', help='Resume the same frozen block sample from saved Parquet checkpoints')
    args = parser.parse_args()
    sample_blocks = args.sample_blocks
    if args.all_unresolved_blocks:
        with duckdb.connect() as con:
            sample_blocks = con.execute('''SELECT count(DISTINCT source_file)
                FROM read_parquet(?)
                WHERE timestamp_provenance IN ('unresolved_raw_as_eastern',
                    'special_form_unresolved_raw_as_eastern')
                  AND acceptanceDateTime AT TIME ZONE 'America/New_York' >= ?''',
                [str(args.filings.resolve()),args.since_date]).fetchone()[0]
        if sample_blocks == 0:
            parser.error('No unresolved CIK files meet the requested cutoff')
        print(f'Full unresolved-block queue: {sample_blocks:,}', flush=True)
    benchmark(args.filings.resolve(),args.raw.resolve(),args.output.resolve(),
              args.since_date,sample_blocks,args.seed,args.workers,args.rate,args.resume)


if __name__ == '__main__':
    main()
