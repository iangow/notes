#!/usr/bin/env python3
"""Freeze a simple random row sample and audit it without changing filings."""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import time

import duckdb
from scipy.stats import beta

from benchmark_sgml_block_sampling import DEFAULT_USER_AGENT, fetch_sgml
from compare_filing_timestamp_sources import sql_string
from fetch_sgml_anchors import NetworkRateLimiter
from retry_timestamp_audit import retryable
from timestamp_parquet_archive import digest


OBS_SCHEMA = '''accession_number VARCHAR,cik BIGINT,acceptance_datetime TIMESTAMP,
    source_url VARCHAR,retrieved_at TIMESTAMPTZ,elapsed_ms DOUBLE,http_status INTEGER,
    content_sha256 VARCHAR,sgml_header VARCHAR,error VARCHAR,origin VARCHAR'''


def save_batch(con, directory, number, results, origin):
    con.execute(f'CREATE OR REPLACE TEMP TABLE batch({OBS_SCHEMA})')
    for cik, accession, r in results:
        con.execute('INSERT INTO batch VALUES (?,?,?,?,?,?,?,?,?,?,?)',
            [accession,cik,r['acceptance'],r['url'],r['retrieved_at'],r['elapsed_ms'],
             r['status'],r['digest'],r['text'],r['error'],origin])
    path=directory/f'observations-{number:05d}.parquet'
    if path.exists():
        raise FileExistsError(path)
    temporary=path.with_suffix('.partial.parquet')
    con.execute('COPY batch TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(temporary)])
    temporary.rename(path)


def freeze(con, filings, output, n, seed):
    population = con.execute('SELECT count(*) FROM read_parquet(?)',[str(filings)]).fetchone()[0]
    if not 0<n<=population:
        raise ValueError('Sample size must be positive and no larger than the population')
    con.execute(f'''CREATE TABLE sample AS
        SELECT file_row_number sample_row,cik,accessionNumber,source_file,form,
            acceptanceDateTime predicted,timestamp_provenance
        FROM read_parquet({sql_string(filings)},file_row_number=true)
        USING SAMPLE reservoir({n} ROWS) REPEATABLE({seed})''')
    con.execute('COPY sample TO ? (FORMAT PARQUET)',[str(output/'sample.parquet')])
    con.execute('COPY sample TO ? (FORMAT CSV,HEADER)',[str(output/'sample_identifiers.csv')])
    stat=filings.stat()
    con.execute('''CREATE TABLE metadata(filings VARCHAR,size_bytes BIGINT,mtime_ns BIGINT,
        sha256 VARCHAR,population_n BIGINT,sample_n BIGINT,seed BIGINT,frozen_at TIMESTAMPTZ,policy VARCHAR)''')
    con.execute('INSERT INTO metadata VALUES (?,?,?,?,?,?,?,?,?)',
        [str(filings),stat.st_size,stat.st_mtime_ns,digest(filings),population,n,seed,datetime.now(timezone.utc),
         'Simple random sample of filing rows; predictions frozen before SGML lookup; no repairs'])
    con.execute('COPY metadata TO ? (FORMAT PARQUET)',[str(output/'metadata.parquet')])


def report(con, output):
    paths=sorted(str(p) for p in output.glob('observations-*.parquet') if '.partial.' not in p.name)
    con.execute('''CREATE OR REPLACE TEMP TABLE observations AS
        SELECT * FROM read_parquet(?)
        QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY retrieved_at DESC)=1''',[paths])
    con.execute('''CREATE OR REPLACE TABLE outcomes AS
        SELECT p.*,o.* EXCLUDE(accession_number,cik),
            o.acceptance_datetime AT TIME ZONE 'America/New_York' sgml_instant,
            coalesce(o.acceptance_datetime IS NOT NULL AND o.error IS NULL,false) verifiable,
            CASE WHEN o.acceptance_datetime IS NOT NULL AND o.error IS NULL
                THEN p.predicted IS DISTINCT FROM o.acceptance_datetime AT TIME ZONE 'America/New_York' END is_error
        FROM sample p LEFT JOIN observations o ON o.accession_number=p.accessionNumber''')
    sampled,verified,errors=con.execute('SELECT count(*),count(*) FILTER(WHERE verifiable),count(*) FILTER(WHERE is_error) FROM outcomes').fetchone()
    upper=None if verified==0 else (1. if errors==verified else float(beta.ppf(.95,errors+1,verified-errors)))
    con.execute('''CREATE OR REPLACE TABLE summary AS SELECT ?::BIGINT sampled_rows,?::BIGINT verified_rows,
        ?::BIGINT errors,?::BIGINT unavailable_rows,?::DOUBLE error_upper_95_among_verifiable''',
        [sampled,verified,errors,sampled-verified,upper])
    for name in ('outcomes','summary'):
        con.execute(f'COPY {name} TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(output/(name+'.parquet'))])
    print('Audit summary:',con.execute('SELECT * FROM summary').fetchone(),flush=True)
    print('Unavailable:',con.execute('SELECT error,count(*) FROM outcomes WHERE NOT verifiable GROUP BY 1').fetchall(),flush=True)
    print('Methods:',con.execute('SELECT timestamp_provenance,count(*),count(*) FILTER(WHERE verifiable),count(*) FILTER(WHERE is_error) FROM outcomes GROUP BY 1').fetchall(),flush=True)
    print('The upper bound concerns verifiable rows only. Predictions and the candidate were not changed.',flush=True)


def audit(filings, output, n=3000, seed=20260930, cache=None, workers=8, rate=7, resume=False):
    existed=output.exists()
    if existed and not resume:
        raise FileExistsError(output)
    output.mkdir(parents=True,exist_ok=True)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=1; SET memory_limit='2GB'")
        if existed:
            meta=con.execute('SELECT sha256,sample_n,seed FROM read_parquet(?)',
                             [str(output/'metadata.parquet')]).fetchone()
            if meta!=(digest(filings),n,seed):
                raise ValueError('Resume requires the original candidate, sample size and seed')
            con.execute('CREATE TABLE sample AS SELECT * FROM read_parquet(?)',[str(output/'sample.parquet')])
        else:
            freeze(con,filings,output,n,seed)
        print(f'Frozen {n:,} rows before reference lookup: {output}',flush=True)
        paths=sorted(p for p in output.glob('observations-*.parquet') if '.partial.' not in p.name)
        number=max((int(p.stem.split('-')[-1]) for p in paths),default=0)
        cached=set()
        attempts={}
        if paths:
            con.execute('CREATE TABLE saved AS SELECT * FROM read_parquet(?)',[[str(p) for p in paths]])
            attempts=dict(con.execute("SELECT accession_number,count(*) FILTER(WHERE origin LIKE 'audit_%') FROM saved GROUP BY 1").fetchall())
            for accession,error in con.execute('''SELECT accession_number,error FROM saved
                    QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY retrieved_at DESC)=1''').fetchall():
                if not retryable(error) or attempts.get(accession,0)>=2:
                    cached.add(accession)
        if cache is not None:
            con.execute(f'''CREATE TEMP TABLE cached AS SELECT s.* FROM read_parquet({sql_string(cache)}) s
                WHERE accession_number IN (SELECT accessionNumber FROM sample)
                  AND ((acceptance_datetime IS NOT NULL AND error IS NULL) OR error LIKE '%ACCEPTANCE-DATETIME tag not found%')''')
            rows=con.execute('SELECT * FROM cached').fetchall()
            names=[r[0] for r in con.execute('DESCRIBE cached').fetchall()]
            results=[]
            for row in rows:
                r=dict(zip(names,row))
                if r['accession_number'] in cached:
                    continue
                cached.add(r['accession_number'])
                results.append((r['cik'],r['accession_number'],dict(acceptance=r['acceptance_datetime'],
                    url=r['source_url'],retrieved_at=r['retrieved_at'],elapsed_ms=r['elapsed_ms'],
                    status=r['http_status'],digest=r['content_sha256'],text=r['sgml_header'],error=r['error'])))
            if results:
                number+=1
                save_batch(con,output,number,results,'existing_cache')
        pending=[r for r in con.execute('SELECT min(cik),accessionNumber FROM sample GROUP BY accessionNumber ORDER BY accessionNumber').fetchall() if r[1] not in cached]
        print(f'Cached accessions={len(cached):,}; fetching={len(pending):,}',flush=True)
        limiter=NetworkRateLimiter(1/rate)
        def fetch(row):
            cik, accession=row
            limiter.wait()
            return cik,accession,fetch_sgml(cik,accession,DEFAULT_USER_AGENT)
        started=time.monotonic()
        retry=[]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for offset in range(0,len(pending),50):
                results=list(pool.map(fetch,pending[offset:offset+50]))
                number+=1
                save_batch(con,output,number,results,'audit_fetch')
                for cik,accession,r in results:
                    attempts[accession]=attempts.get(accession,0)+1
                    if retryable(r['error']) and attempts[accession]<2:
                        retry.append((cik,accession))
                print(f'Audit fetches {offset+len(results):,}/{len(pending):,}; elapsed={time.monotonic()-started:.1f}s',flush=True)
            if retry:
                time.sleep(5)
                print(f'Retrying {len(retry):,} transient failures without changing predictions',flush=True)
                for offset in range(0,len(retry),50):
                    results=list(pool.map(fetch,retry[offset:offset+50]))
                    number+=1
                    save_batch(con,output,number,results,'audit_retry')
        report(con,output)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--filings',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--sample-size',type=int,default=10000)
    parser.add_argument('--seed',type=int,default=20260930)
    parser.add_argument('--cache',type=Path)
    parser.add_argument('--workers',type=int,default=8)
    parser.add_argument('--rate',type=float,default=7)
    parser.add_argument('--resume',action='store_true',help='Resume the same frozen sample without replacing any predictions.')
    args=parser.parse_args()
    if min(args.workers,args.rate,args.sample_size)<=0:
        parser.error('Workers, rate and sample size must be positive')
    audit(args.filings.expanduser().resolve(),args.output.expanduser().resolve(),args.sample_size,args.seed,
          None if args.cache is None else args.cache.expanduser().resolve(),args.workers,args.rate,args.resume)


if __name__=='__main__':
    main()
