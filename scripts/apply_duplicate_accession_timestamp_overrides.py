#!/usr/bin/env python3
"""Resolve duplicate accessions whose ZIP clocks disagree by 4 or 5 hours."""

import argparse
import time
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from compare_filing_timestamp_sources import DATA_DIR, sql_string


DEFAULT_RAW = DATA_DIR / "edgar" / "filings_raw.parquet"
EXCLUDED_FORMS = ("EFFECT", "CORRESP", "UPLOAD", "DRSLTR")


def done_filter(include_done: bool) -> str:
    if include_done:
        return ""
    return f"""
      AND NOT EXISTS (
        SELECT 1
        FROM duplicate_accession_timestamp_overrides AS done
        WHERE done.accession_number = grouped.accessionNumber
      )
    """


def limit_clause(limit: int | None) -> str:
    return "" if limit is None else f"LIMIT {limit}"


def create_candidates(
    con: duckdb.DuckDBPyConnection,
    raw: Path,
    include_done: bool,
    limit: int | None,
) -> None:
    excluded_forms = ", ".join("'" + form + "'" for form in EXCLUDED_FORMS)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE duplicate_accession_candidates AS
        WITH raw AS (
          SELECT accessionNumber,
                 cik,
                 form,
                 acceptanceDateTime,
                 TRY_CAST(regexp_replace(acceptanceDateTime, 'Z$', '') AS TIMESTAMP)
                   AS zip_ts
          FROM read_parquet({sql_string(raw)})
          WHERE accessionNumber IS NOT NULL
            AND acceptanceDateTime IS NOT NULL
            AND acceptanceDateTime <> ''
        ),
        grouped AS (
          SELECT accessionNumber,
                 min(cik) AS representative_cik,
                 count(*) AS rows_n,
                 count(DISTINCT cik) AS ciks_n,
                 count(DISTINCT acceptanceDateTime) AS timestamp_variants,
                 count(*) FILTER (
                   WHERE coalesce(form, '') NOT IN ({excluded_forms})
                     AND (hour(zip_ts) >= 22 OR hour(zip_ts) < 6)
                 ) AS outside_rows,
                 min(zip_ts) AS corrected_acceptance_datetime,
                 min(zip_ts) AT TIME ZONE 'America/New_York'
                   AS corrected_acceptance_timestamptz,
                 max(zip_ts) AS later_zip_datetime,
                 date_diff('minute', min(zip_ts), max(zip_ts)) AS diff_min
          FROM raw
          GROUP BY accessionNumber
          HAVING count(*) > 1
             AND count(DISTINCT acceptanceDateTime) > 1
        )
        SELECT *
        FROM grouped
        WHERE timestamp_variants = 2
          AND diff_min IN (240, 300)
          AND corrected_acceptance_timestamptz = later_zip_datetime AT TIME ZONE 'UTC'
          {done_filter(include_done)}
        ORDER BY outside_rows DESC, rows_n DESC, accessionNumber
        {limit_clause(limit)}
        """
    )


def insert_duplicate_overrides(con: duckdb.DuckDBPyConnection) -> int:
    con.execute(
        """
        INSERT INTO duplicate_accession_timestamp_overrides (
          accession_number,
          corrected_acceptance_datetime,
          corrected_acceptance_timestamptz,
          earlier_zip_datetime,
          later_zip_datetime,
          diff_min,
          rows_n,
          ciks_n,
          outside_rows,
          method,
          updated_at
        )
        SELECT accessionNumber,
               corrected_acceptance_datetime,
               corrected_acceptance_timestamptz,
               corrected_acceptance_datetime,
               later_zip_datetime,
               diff_min,
               rows_n,
               ciks_n,
               outside_rows,
               'two_distinct_zip_clocks_240_300_minutes_apart',
               now()
        FROM duplicate_accession_candidates
        ON CONFLICT (accession_number) DO UPDATE SET
          corrected_acceptance_datetime = excluded.corrected_acceptance_datetime,
          corrected_acceptance_timestamptz = excluded.corrected_acceptance_timestamptz,
          earlier_zip_datetime = excluded.earlier_zip_datetime,
          later_zip_datetime = excluded.later_zip_datetime,
          diff_min = excluded.diff_min,
          rows_n = excluded.rows_n,
          ciks_n = excluded.ciks_n,
          outside_rows = excluded.outside_rows,
          method = excluded.method,
          updated_at = excluded.updated_at
        """
    )
    return con.execute("SELECT count(*) FROM duplicate_accession_candidates").fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-accessions", type=int, default=100_000)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all deterministic duplicate-accession conflicts.",
    )
    parser.add_argument("--include-done", action="store_true")
    parser.add_argument(
        "--promote-overrides",
        action="store_true",
        help="Write deterministic accession-level duplicate timestamp overrides.",
    )
    args = parser.parse_args()

    if args.max_accessions is not None and args.max_accessions < 1:
        parser.error("--max-accessions must be positive")

    raw = args.raw.expanduser().resolve()
    database = args.database.expanduser().resolve()
    limit = None if args.all else args.max_accessions
    started = time.monotonic()

    with duckdb.connect(str(database)) as con:
        initialize_database(con)
        create_candidates(con, raw, args.include_done, limit)
        summary = con.execute(
            """
            SELECT count(*) AS accessions,
                   sum(rows_n) AS affected_rows,
                   sum(outside_rows) AS outside_rows,
                   count(*) FILTER (WHERE diff_min = 240) AS daylight_offsets,
                   count(*) FILTER (WHERE diff_min = 300) AS standard_offsets
            FROM duplicate_accession_candidates
            """
        ).fetchone()
        overrides = insert_duplicate_overrides(con) if args.promote_overrides else 0
        con.commit()

    accessions, affected_rows, outside_rows, daylight_offsets, standard_offsets = summary
    print(f"database: {database}")
    print(f"raw: {raw}")
    print(
        "Summary: "
        f"accessions={accessions:,}, "
        f"affected_rows={affected_rows or 0:,}, "
        f"outside_rows={outside_rows or 0:,}, "
        f"overrides={overrides:,}, "
        f"wall_time={time.monotonic() - started:.2f}s"
    )
    print(f"  diff_min=240: {daylight_offsets:,}")
    print(f"  diff_min=300: {standard_offsets:,}")


if __name__ == "__main__":
    main()
