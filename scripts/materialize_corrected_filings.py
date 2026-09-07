#!/usr/bin/env python3
"""Materialize SEC filing timestamps from persisted ZIP inventory and rules."""

import argparse
import hashlib
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP, DEFAULT_OLD, sql_string


DEFAULT_OUTPUT = Path("/private/tmp/filings_timestamp_corrected.parquet")


def snapshot_id(path: Path) -> str:
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-unresolved", action="store_true")
    args = parser.parse_args()

    snapshot = snapshot_id(args.zip)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = args.output.with_suffix(".tmp.parquet")
    tmp_output.unlink(missing_ok=True)

    con = duckdb.connect(str(args.database), read_only=True)
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'America/New_York'")

    inventory_rows = con.execute(
        "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
    ).fetchone()[0]
    if inventory_rows == 0:
        raise RuntimeError(
            "No ZIP inventory found for this snapshot. Run "
            "scripts/build_acceptance_timestamp_rules.py first."
        )

    unresolved_new_rows = con.execute(
        """
        WITH old_keys AS (
          SELECT cik,
                 accessionNumber AS accession_number,
                 row_number() OVER (
                   PARTITION BY cik, accessionNumber
                   ORDER BY filingDate, form, items, acceptanceDateTime
                 ) AS duplicate_index
          FROM read_parquet(?)
        ),
        zip_rows AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY cik, accession_number
                   ORDER BY filing_date, form, items, zip_acceptance_datetime
                 ) AS duplicate_index
          FROM zip_filing_records
          WHERE snapshot_id = ?
        ),
        resolved AS (
          SELECT z.accession_number,
                 o.accession_number IS NOT NULL AS has_trusted_overlap,
                 rr.provenance
          FROM zip_rows AS z
          LEFT JOIN old_keys AS o
            ON z.cik = o.cik
           AND z.accession_number = o.accession_number
           AND z.duplicate_index = o.duplicate_index
          LEFT JOIN LATERAL (
            SELECT provenance
            FROM resolve_acceptance_timestamp(
              z.cik,
              z.accession_number,
              z.snapshot_id,
              z.block_name,
              z.block_sha256,
              z.filing_date,
              z.zip_acceptance_datetime
            )
          ) AS rr ON true
        )
        SELECT count(*)
        FROM resolved
        WHERE NOT has_trusted_overlap
          AND provenance = 'unresolved'
        """,
        [str(args.old), snapshot],
    ).fetchone()[0]

    if unresolved_new_rows and not args.allow_unresolved:
        raise RuntimeError(
            f"{unresolved_new_rows:,} new-only rows have no timestamp rule. "
            "Pass --allow-unresolved to materialize them with their ZIP clock "
            "left unchanged and provenance marked unresolved_zip_as_eastern."
        )

    old_sql = sql_string(args.old)
    out_sql = sql_string(tmp_output)
    con.execute(
        f"""
        COPY (
          WITH old_rows AS (
            SELECT cik,
                   accessionNumber AS accession_number,
                   acceptanceDateTime AS trusted_acceptance_datetime,
                   row_number() OVER (
                     PARTITION BY cik, accessionNumber
                     ORDER BY filingDate, form, items, acceptanceDateTime
                   ) AS duplicate_index
            FROM read_parquet({old_sql})
          ),
          zip_rows AS (
            SELECT *,
                   row_number() OVER (
                     PARTITION BY cik, accession_number
                     ORDER BY filing_date, form, items, zip_acceptance_datetime
                   ) AS duplicate_index
            FROM zip_filing_records
            WHERE snapshot_id = '{snapshot}'
          ),
          corrected AS (
            SELECT z.cik,
                   z.accession_number AS accessionNumber,
                   z.filing_date AS filingDate,
                   CASE
                     WHEN o.trusted_acceptance_datetime IS NOT NULL
                       THEN o.trusted_acceptance_datetime
                     WHEN rr.provenance <> 'unresolved'
                       THEN rr.corrected_acceptance_datetime
                     ELSE z.zip_acceptance_datetime
                   END AS acceptanceDateTime,
                   z.form,
                   z.items,
                   z.block_name,
                   z.block_sha256,
                   CASE
                     WHEN o.trusted_acceptance_datetime IS NOT NULL
                       THEN 'trusted_2024_overlap'
                     WHEN rr.provenance <> 'unresolved'
                       THEN rr.provenance
                     ELSE 'unresolved_zip_as_eastern'
                   END AS timestamp_provenance,
                   CASE
                     WHEN o.trusted_acceptance_datetime IS NOT NULL
                       THEN 'trusted_2024_parquet'
                     ELSE rr.reference_id
                   END AS timestamp_reference_id,
                   CASE
                     WHEN o.trusted_acceptance_datetime IS NOT NULL
                       THEN 'eastern'
                     ELSE rr.interpretation
                   END AS timestamp_interpretation
            FROM zip_rows AS z
            LEFT JOIN old_rows AS o
              ON z.cik = o.cik
             AND z.accession_number = o.accession_number
             AND z.duplicate_index = o.duplicate_index
            LEFT JOIN LATERAL (
              SELECT corrected_acceptance_datetime,
                     interpretation,
                     provenance,
                     reference_id
              FROM resolve_acceptance_timestamp(
                z.cik,
                z.accession_number,
                z.snapshot_id,
                z.block_name,
                z.block_sha256,
                z.filing_date,
                z.zip_acceptance_datetime
              )
            ) AS rr ON true
          )
          SELECT *
          FROM corrected
        )
        TO {out_sql}
        (FORMAT PARQUET, COMPRESSION SNAPPY)
        """
    )
    tmp_output.replace(args.output)

    summary = con.execute(
        f"""
        SELECT timestamp_provenance,
               timestamp_interpretation,
               count(*) AS n
        FROM read_parquet({sql_string(args.output)})
        GROUP BY timestamp_provenance, timestamp_interpretation
        ORDER BY n DESC, timestamp_provenance, timestamp_interpretation
        """
    ).fetchall()
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet({sql_string(args.output)})"
    ).fetchone()[0]
    con.close()

    print(f"wrote {args.output} ({rows:,} rows)")
    for provenance, interpretation, count in summary:
        print(f"  {provenance}\t{interpretation}\t{count:,}")


if __name__ == "__main__":
    main()
