#!/usr/bin/env python3
"""Create corrected filings using Parquet inputs and a disposable working database."""

import argparse
import glob
from pathlib import Path
import tempfile
from types import SimpleNamespace

import duckdb

from bootstrap_timestamp_workflow import bootstrap
from compare_filing_timestamp_sources import sql_string
from infer_live_file_timezones import infer
from materialize_corrected_filings import materialize_workflow
from timestamp_parquet_archive import export_snapshot


def extend_from_cache(con, cache, sgml_sources=(), live_sources=()):
    for name, empty in (
        ('live', 'source_url VARCHAR,accession_number VARCHAR,acceptance_datetime_text VARCHAR,retrieved_at TIMESTAMPTZ'),
        ('sgml', 'accession_number VARCHAR,acceptance_datetime TIMESTAMP,error VARCHAR')):
        filename = 'live_json_timestamp_observations.parquet' if name == 'live' else 'sgml_observations.parquet'
        path = None if cache is None else cache / filename
        extra = sgml_sources if name == 'sgml' else live_sources
        if extra or (path is not None and path.exists()):
            paths=([path] if path is not None and path.exists() else [])+list(extra)
            projection = ('accession_number,acceptance_datetime,error' if name == 'sgml'
                          else 'source_url,accession_number,acceptance_datetime_text,retrieved_at')
            con.execute(f'''CREATE TEMP TABLE {name} AS SELECT {projection}
                FROM read_parquet(?,union_by_name=true)''',[[str(p) for p in paths]])
        else:
            con.execute(f'CREATE TEMP TABLE {name}({empty})')
    con.execute('''
        CREATE TABLE live_pairs AS
        WITH clocks AS (
            SELECT accessionNumber accession,raw_clock FROM current_rows
            UNION ALL SELECT accession_number,try_cast(acceptance_datetime_text AS TIMESTAMP) FROM live
            WHERE accession_number IN (SELECT accessionNumber FROM current_groups)
        ), grouped AS (
            SELECT accession,list_sort(list(DISTINCT raw_clock) FILTER(WHERE raw_clock IS NOT NULL)) clocks,
                count(*) FILTER(WHERE raw_clock IS NULL) invalid FROM clocks GROUP BY accession
        ) SELECT accession,clocks[2] AT TIME ZONE 'UTC' instant FROM grouped
        WHERE len(clocks)=2 AND invalid=0
          AND accession IN (SELECT accession_number FROM live)
          AND (clocks[1] AT TIME ZONE 'America/New_York')=(clocks[2] AT TIME ZONE 'UTC');
        CREATE TEMP TABLE anchor_inputs AS
        SELECT accessionNumber accession,corrected_instant instant FROM accession_timestamp_overrides
        UNION ALL SELECT * FROM live_pairs;
        CREATE TEMP TABLE validation AS SELECT * FROM anchor_inputs
        UNION ALL SELECT accession_number,acceptance_datetime AT TIME ZONE 'America/New_York'
            FROM sgml WHERE acceptance_datetime IS NOT NULL AND error IS NULL
        UNION ALL SELECT accessionNumber,corrected_instant FROM prior_release_evidence
            WHERE supported AND corrected_instant IS NOT NULL;
    ''')
    infer(con, versioned=True)
    con.execute('''CREATE TABLE sgml_file_anchors AS
        SELECT l.source_url,l.accession_number,l.retrieved_at,
               s.acceptance_datetime AT TIME ZONE 'America/New_York' instant
        FROM live l JOIN sgml s USING(accession_number)
        WHERE NOT EXISTS (SELECT 1 FROM file_rules r WHERE r.source_url=l.source_url
            AND r.observation_version IS NOT DISTINCT FROM l.retrieved_at)
          AND s.acceptance_datetime IS NOT NULL AND s.error IS NULL''')
    for table in ('anchors','file_evidence','file_rules','file_candidates','rejected_accessions','inferred_overrides'):
        con.execute(f'DROP TABLE {table}')
    infer(con,sgml_file_anchors=True,versioned=True)
    con.execute('''
        CREATE TABLE accession_evidence AS
        SELECT accession_number,corrected_instant,provenance,
            CASE WHEN provenance='sgml' THEN 40 ELSE 30 END priority FROM resolved_accessions
        UNION ALL SELECT accession,instant,'live_pair',30 FROM live_pairs
        UNION ALL SELECT accession_number,instant,'live_file_inferred',10 FROM inferred_overrides
        UNION ALL SELECT accession_number,acceptance_datetime AT TIME ZONE 'America/New_York','sgml',40
            FROM sgml WHERE acceptance_datetime IS NOT NULL AND error IS NULL;
        CREATE TABLE evidence_disagreements AS
        SELECT accession_number,count(DISTINCT corrected_instant) instant_count
        FROM accession_evidence GROUP BY 1 HAVING count(DISTINCT corrected_instant)>1;
        CREATE OR REPLACE TABLE resolved_accessions AS
        WITH strongest AS (
            SELECT * FROM accession_evidence
            QUALIFY priority=max(priority) OVER(PARTITION BY accession_number)
        ) SELECT accession_number,min(corrected_instant) corrected_instant,min(provenance) provenance
        FROM strongest GROUP BY accession_number HAVING count(DISTINCT corrected_instant)=1;
        CREATE OR REPLACE TABLE summary AS
        SELECT count(*) rows_n,count(a.corrected_instant) supported_rows,
            count(*) FILTER(WHERE a.corrected_instant IS NULL) unresolved_rows
        FROM current_rows c LEFT JOIN resolved_accessions a ON a.accession_number=c.accessionNumber;
    ''')


def process(raw, previous, output, cache=None, memory_limit='8GB', sgml_sources=(), live_sources=()):
    checks = output.with_name(output.stem+'_checks')
    if output.exists() or checks.exists():
        raise FileExistsError('Use a fresh output path; published results are never overwritten')
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.timestamp-work-',dir=output.parent) as temporary:
        database = Path(temporary)/'working.duckdb'
        with duckdb.connect(str(database)) as con:
            con.execute("SET threads=1; SET preserve_insertion_order=false; SET enable_progress_bar=false")
            con.execute(f'SET memory_limit={sql_string(memory_limit)}')
            print('Bootstrapping from the previous Parquet ...',flush=True)
            bootstrap(con,raw,previous)
            print('Baseline rows, supported, unresolved:',con.execute('SELECT * FROM summary').fetchone(),flush=True)
            print('Applying cached JSON and SGML observations ...',flush=True)
            extend_from_cache(con,cache,sgml_sources,live_sources)
            if cache is not None:
                for name in ('live_json_timestamp_observations.parquet','sgml_observations.parquet'):
                    path = cache/name
                    if path.exists():
                        stat = path.stat()
                        con.execute('INSERT INTO inputs VALUES (?,?,?,?)',[name,str(path.resolve()),stat.st_size,stat.st_mtime_ns])
            for path in sgml_sources:
                stat=path.stat()
                con.execute('INSERT INTO inputs VALUES (?,?,?,?)',
                    ['sgml:'+path.name,str(path.resolve()),stat.st_size,stat.st_mtime_ns])
            for path in live_sources:
                stat=path.stat()
                con.execute('INSERT INTO inputs VALUES (?,?,?,?)',
                    ['live:'+path.name,str(path.resolve()),stat.st_size,stat.st_mtime_ns])
            print('Final rows, supported, unresolved:',con.execute('SELECT * FROM summary').fetchone(),flush=True)
            print('Conflicting evidence accessions:',con.execute('SELECT count(*) FROM evidence_disagreements').fetchone()[0],flush=True)
            con.execute('''CREATE TABLE rejected_prior_evidence AS
                SELECT p.* FROM prior_accession_evidence p
                WHERE accessionNumber IN (SELECT accessionNumber FROM bootstrap_rejections)''')
        args = SimpleNamespace(workflow_database=database,threads=1,memory_limit=memory_limit,limit=None,allow_unresolved=True)
        candidate = Path(temporary)/'candidate.parquet'
        materialize_workflow(args,raw,candidate)
        export_snapshot(database,checks,tables=['inputs','workflow_metadata','summary',
            'bootstrap_rejections','evidence_disagreements','rejected_prior_evidence',
            'file_rules','file_evidence','rejected_accessions'])
        candidate.rename(output)
    print(f'Candidate: {output}; diagnostics: {checks}; working database removed.',flush=True)
    print('This run reuses available observations; unresolved new coverage still requires collection and an independent audit.',flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--previous',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache-dir',type=Path,help='Parquet directory of live JSON and SGML observations.')
    parser.add_argument('--memory-limit',default='8GB')
    parser.add_argument('--sgml-observations',action='append',default=[],
                        help='Additional Parquet files or quoted globs, including a preceding audit\'s observation batches.')
    parser.add_argument('--live-observations',action='append',default=[],
                        help='Additional live-JSON Parquet files or quoted globs; retrieval versions remain separate.')
    args = parser.parse_args()
    sources=[]
    for pattern in args.sgml_observations:
        matches=glob.glob(str(Path(pattern).expanduser()))
        if not matches:
            raise FileNotFoundError(pattern)
        sources.extend(Path(p).resolve() for p in matches)
    live_sources=[]
    for pattern in args.live_observations:
        matches=glob.glob(str(Path(pattern).expanduser()))
        if not matches:
            raise FileNotFoundError(pattern)
        live_sources.extend(Path(p).resolve() for p in matches)
    process(args.raw.expanduser().resolve(),args.previous.expanduser().resolve(),
            args.output.expanduser().resolve(),None if args.cache_dir is None else args.cache_dir.expanduser().resolve(),
            args.memory_limit,sorted(set(sources)),sorted(set(live_sources)))


if __name__ == '__main__':
    main()
