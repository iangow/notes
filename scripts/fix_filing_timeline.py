#!/usr/bin/env python3
"""
Repair filing acceptance timestamps using the trusted backup timeline.

The output keeps the current file's coverage and non-timestamp columns, but for
rows that also appear in the backup it uses the backup acceptanceDateTime.
"""

import argparse
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import DATA_DIR, DEFAULT_OLD

DEFAULT_BACKUP = DEFAULT_OLD
DEFAULT_CURRENT = DATA_DIR / "edgar" / "filings.parquet"
DEFAULT_OUTPUT = Path("/private/tmp/filings_timeline_fixed.parquet")


def sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--backup", type=Path, default=DEFAULT_BACKUP)
    parser.add_argument("--current", type=Path, default=DEFAULT_CURRENT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = args.output.with_suffix(".tmp.parquet")
    tmp_output.unlink(missing_ok=True)

    con = duckdb.connect()
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'America/New_York'")

    con.execute(
        f"""
        COPY (
          WITH backup AS (
            SELECT *,
                   row_number() OVER (
                     PARTITION BY cik, accessionNumber
                     ORDER BY filingDate, form, items, acceptanceDateTime
                   ) AS key_row
            FROM read_parquet({sql_string(args.backup)})
          ),
          current AS (
            SELECT *,
                   row_number() OVER (
                     PARTITION BY cik, accessionNumber
                     ORDER BY filingDate, form, items, acceptanceDateTime
                   ) AS key_row
            FROM read_parquet({sql_string(args.current)})
          )
          SELECT c.cik,
                 c.accessionNumber,
                 c.filingDate,
                 coalesce(b.acceptanceDateTime, c.acceptanceDateTime)
                   AS acceptanceDateTime,
                 c.form,
                 c.items
          FROM current AS c
          LEFT JOIN backup AS b
            ON c.cik = b.cik
           AND c.accessionNumber = b.accessionNumber
           AND c.key_row = b.key_row
        )
        TO {sql_string(tmp_output)}
        (FORMAT PARQUET, COMPRESSION SNAPPY)
        """
    )
    tmp_output.replace(args.output)

    rows = con.execute(
        f"SELECT count(*) FROM read_parquet({sql_string(args.output)})"
    ).fetchone()[0]
    print(f"wrote {args.output} ({rows:,} rows)")
    con.close()


if __name__ == "__main__":
    main()
