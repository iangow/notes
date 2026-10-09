from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from time import perf_counter
from urllib.parse import quote

import psycopg
from psycopg import sql
import pyarrow as pa
import pyarrow.parquet as pq

from db2pq import close_adbc_cached, db_to_pq


MiB = 1024 * 1024
parser = argparse.ArgumentParser(description="Compare local PostgreSQL export engines.")
parser.add_argument("--host", default="localhost")
parser.add_argument("--port", type=int, default=5432)
parser.add_argument("--database", default="igow")
parser.add_argument("--user")
parser.add_argument("--data-dir", type=Path, default=Path("/tmp/db2pq_local_bench"))
parser.add_argument("--include-pg-duckdb", action="store_true")
parser.add_argument("--pg-duckdb-build-info", type=Path)
args = parser.parse_args()
DATA_DIR = args.data_dir.resolve()
DATABASE, HOST, PORT, USER = args.database, args.host, args.port, args.user
ROW_GROUP_SIZE = 250_000

TABLE_CASES = [
    {"schema": "comp", "table_name": "company", "obs": 50_000, "adbc_reps": 2},
    {"schema": "comp", "table_name": "funda", "obs": 1_000_000, "adbc_reps": 1},
    {"schema": "crsp", "table_name": "msf_v2", "obs": 10_000_000, "adbc_reps": 1},
]


RESULTS_PATH = Path(__file__).with_name("local_engine_benchmark_update_results.parquet")


def _emit_result(
    *,
    case: dict,
    run_label: str,
    engine_case: dict,
    elapsed: float,
    rows: int,
    size_mb: float,
    columns: int,
    writer: str,
) -> None:
    result = {
        "schema": case["schema"],
        "table_name": case["table_name"],
        "obs_requested": case["obs"],
        "run_label": run_label,
        "engine": engine_case["engine"],
        "time_seconds": elapsed,
        "rows": rows,
        "size_mb": size_mb,
        "columns": columns,
        "parquet_writer": writer,
        "config_json": json.dumps(engine_case, sort_keys=True),
    }
    RESULT_ROWS.append(result)
    print(
        f"{case['schema']}.{case['table_name']}",
        run_label,
        engine_case,
        f"time={elapsed:.2f}s",
        f"rows={rows}",
        f"size_mb={size_mb:.1f}",
    )


def _db_to_pq_case(case: dict, *, engine_case: dict, run_label: str) -> None:
    start = perf_counter()
    path = db_to_pq(
        table_name=case["table_name"],
        schema=case["schema"],
        user=USER,
        host=quote(HOST, safe="") if HOST.startswith("/") else HOST,
        database=DATABASE,
        port=PORT,
        data_dir=DATA_DIR,
        obs=case["obs"],
        row_group_size=ROW_GROUP_SIZE,
        alt_table_name=f"{case['schema']}_{case['table_name']}_{run_label}",
        **engine_case,
    )
    elapsed = perf_counter() - start
    meta = pq.read_metadata(path)
    size_mb = Path(path).stat().st_size / MiB
    _emit_result(
        case=case,
        run_label=run_label,
        engine_case=engine_case,
        elapsed=elapsed,
        rows=meta.num_rows,
        size_mb=size_mb,
        columns=meta.num_columns,
        writer=meta.created_by,
    )


def _pg_extension_case(case: dict, engine: str) -> None:
    server_path = DATA_DIR / f"{engine}_{case['schema']}_{case['table_name']}.parquet"
    with psycopg.connect(host=HOST, port=PORT, dbname=DATABASE, user=USER) as conn:
        conn.execute("SET pg_parquet.enable_copy_hooks = on")
        if "pg_duckdb" in extensions:
            conn.execute("SET duckdb.force_execution = off")
        identifiers = [case["schema"], case["table_name"]]
        if engine == "pg_duckdb":
            identifiers.insert(0, "pgduckdb")
        query = sql.SQL(
            "COPY (SELECT * FROM {} LIMIT {}) TO {} WITH (FORMAT 'parquet')"
        ).format(
            sql.Identifier(*identifiers), sql.Literal(case["obs"]),
            sql.Literal(str(server_path)),
        )
        start = perf_counter()
        with conn.cursor() as cur:
            if engine == "pg_duckdb":
                # Send SQL directly to DuckDB, avoiding PostgreSQL's deparser.
                cur.execute("SELECT duckdb.raw_query(%s)", (query.as_string(conn),))
            else:
                cur.execute(query)
            cur.execute("SELECT (pg_stat_file(%s)).size", (str(server_path),))
            size_bytes = cur.fetchone()[0]
        elapsed = perf_counter() - start
    meta = pq.read_metadata(server_path)
    expected_writer = "pg_parquet" if engine == "pg_parquet" else "DuckDB version "
    if not meta.created_by.startswith(expected_writer):
        raise RuntimeError(f"Requested {engine}, but Parquet writer was {meta.created_by!r}")

    _emit_result(
        case=case,
        run_label=engine,
        engine_case={"engine": engine, "route": "duckdb.raw_query" if engine == "pg_duckdb" else "COPY"},
        elapsed=elapsed,
        rows=meta.num_rows,
        size_mb=size_bytes / MiB,
        columns=meta.num_columns,
        writer=meta.created_by,
    )


close_adbc_cached()
DATA_DIR.mkdir(parents=True, exist_ok=True)
with psycopg.connect(host=HOST, port=PORT, dbname=DATABASE, user=USER) as conn:
    extensions = dict(conn.execute("SELECT extname, extversion FROM pg_extension").fetchall())
    if "pg_parquet" not in extensions:
        raise RuntimeError("pg_parquet must be installed in the benchmark database")
    if args.include_pg_duckdb and "pg_duckdb" not in extensions:
        raise RuntimeError("--include-pg-duckdb requires pg_duckdb in the benchmark database")
    preload = conn.execute("SHOW shared_preload_libraries").fetchone()[0]
    libraries = [Path(x.strip().strip('"')).stem for x in preload.split(",")]
    if "pg_duckdb" in libraries and (
        "pg_parquet" not in libraries
        or libraries.index("pg_duckdb") > libraries.index("pg_parquet")
    ):
        raise RuntimeError("Load pg_duckdb before pg_parquet in shared_preload_libraries")
RESULT_ROWS: list[dict] = []
first_adbc_run = True

for case in TABLE_CASES:
    print(f"=== {case['schema']}.{case['table_name']} obs={case['obs']} ===")
    adbc_case = {
        "engine": "adbc",
        "numeric_mode": "decimal",
        "adbc_batch_size_hint_bytes": 16 * MiB,
        "adbc_use_copy": True,
    }
    for rep in range(1, case["adbc_reps"] + 1):
        run_label = "adbc_init" if first_adbc_run else "adbc"
        _db_to_pq_case(case, engine_case=adbc_case, run_label=run_label)
        first_adbc_run = False
    _db_to_pq_case(
        case,
        engine_case={"engine": "duckdb", "batched": True},
        run_label="duckdb",
    )
    _pg_extension_case(case, "pg_parquet")
    if args.include_pg_duckdb:
        _pg_extension_case(case, "pg_duckdb")
    print()

with psycopg.connect(host=HOST, port=PORT, dbname=DATABASE, user=USER) as conn:
    server_version = conn.execute("SHOW server_version").fetchone()[0]
    pg_parquet_version = conn.execute(
        "SELECT extversion FROM pg_extension WHERE extname = 'pg_parquet'"
    ).fetchone()[0]

environment = {
    "run_at": datetime.now(timezone.utc).isoformat(),
    "versions": {
        package: version(package)
        for package in (
            "db2pq", "duckdb", "adbc-driver-postgresql", "adbc-driver-manager",
            "pyarrow", "pandas", "polars", "psycopg", "matplotlib", "seaborn",
        )
    },
}
environment["versions"].update(
    {"PostgreSQL": server_version, "pg_parquet": pg_parquet_version}
)
environment["database"] = DATABASE
environment["shared_preload_libraries"] = preload
if args.include_pg_duckdb:
    environment["versions"]["pg_duckdb (SQL version)"] = extensions["pg_duckdb"]
    writers = {r["parquet_writer"] for r in RESULT_ROWS if r["engine"] == "pg_duckdb"}
    environment["versions"]["DuckDB (inside pg_duckdb)"] = ", ".join(sorted(writers))
if args.pg_duckdb_build_info:
    environment["pg_duckdb_build"] = json.loads(args.pg_duckdb_build_info.read_text())
    environment["versions"]["pg_duckdb (source commit)"] = environment["pg_duckdb_build"]["source_commit"][:12]
results = pa.Table.from_pylist(RESULT_ROWS).replace_schema_metadata(
    {"benchmark_environment": json.dumps(environment)}
)
pq.write_table(results, RESULTS_PATH)
print(f"results_parquet={RESULTS_PATH}")
