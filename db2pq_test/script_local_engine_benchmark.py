from __future__ import annotations

import json
from pathlib import Path
from time import perf_counter

import psycopg
import pyarrow as pa
import pyarrow.parquet as pq

from db2pq import close_adbc_cached, db_to_pq


MiB = 1024 * 1024
DATA_DIR = Path("/tmp/db2pq_local_bench")
DATABASE = "igow"
HOST = "localhost"
PORT = 5432
USER = None
ROW_GROUP_SIZE = 250_000

TABLE_CASES = [
    {"schema": "comp", "table_name": "company", "obs": 50_000, "adbc_reps": 2},
    {"schema": "comp", "table_name": "funda", "obs": 1_000_000, "adbc_reps": 1},
    {"schema": "crsp", "table_name": "msf_v2", "obs": 10_000_000, "adbc_reps": 1},
]


PG_PARQUET_EXCLUDED_COLUMNS = {
    ("comp", "funda"): ("at",),
}
RESULTS_PATH = Path(__file__).with_name("local_engine_benchmark_results.parquet")


def _emit_result(
    *,
    case: dict,
    run_label: str,
    engine_case: dict,
    elapsed: float,
    rows: int,
    size_mb: float,
    excluded_columns: tuple[str, ...] = (),
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
        "config_json": json.dumps(engine_case, sort_keys=True),
        "excluded_columns_json": json.dumps(excluded_columns),
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
        host=HOST,
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
    )


def _pg_parquet_case(case: dict) -> None:
    server_path = f"/tmp/db2pq_pg_parquet_{case['schema']}_{case['table_name']}_{case['obs']}.parquet"
    excluded_columns = PG_PARQUET_EXCLUDED_COLUMNS.get(
        (case["schema"], case["table_name"]),
        (),
    )
    run_label = "pg_parquet"
    uri = (
        f"postgresql://{HOST}:{PORT}/{DATABASE}"
        if USER is None
        else f"postgresql://{USER}@{HOST}:{PORT}/{DATABASE}"
    )
    with psycopg.connect(uri) as conn:
        select_list = "*"
        if excluded_columns:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = %s AND table_name = %s
                    ORDER BY ordinal_position
                    """,
                    (case["schema"], case["table_name"]),
                )
                select_list = ", ".join(
                    f'"{column_name}"'
                    for (column_name,) in cur.fetchall()
                    if column_name not in excluded_columns
                )
            run_label = f"pg_parquet_minus_{'_'.join(excluded_columns)}"
        sql = (
            f"COPY (SELECT {select_list} FROM {case['schema']}.{case['table_name']} "
            f"LIMIT {int(case['obs'])}) "
            f"TO '{server_path}' WITH (FORMAT 'parquet')"
        )
        start = perf_counter()
        with conn.cursor() as cur:
            cur.execute(sql)
            cur.execute("SELECT (pg_stat_file(%s)).size", (server_path,))
            size_bytes = cur.fetchone()[0]
        elapsed = perf_counter() - start
    rows = pq.read_metadata(server_path).num_rows

    _emit_result(
        case=case,
        run_label=run_label,
        engine_case={"engine": "pg_parquet"},
        elapsed=elapsed,
        rows=rows,
        size_mb=size_bytes / MiB,
        excluded_columns=excluded_columns,
    )


close_adbc_cached()
DATA_DIR.mkdir(parents=True, exist_ok=True)
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
    _pg_parquet_case(case)
    print()

pq.write_table(pa.Table.from_pylist(RESULT_ROWS), RESULTS_PATH)
print(f"results_parquet={RESULTS_PATH}")
