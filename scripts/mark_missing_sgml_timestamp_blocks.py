#!/usr/bin/env python3
"""Mark SEC ZIP blocks whose sampled SGML headers have no acceptance timestamp."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from build_acceptance_timestamp_rules import initialize_inventory_schema, snapshot_id
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP


MISSING_TAG_ERROR = "%ACCEPTANCE-DATETIME tag not found%"


def candidate_sql(limit: int | None) -> str:
    limit_sql = "" if limit is None else f"LIMIT {limit}"
    return f"""
        WITH sample_status AS (
          SELECT bs.snapshot_id,
                 bs.cik,
                 bs.block_name,
                 bs.block_sha256,
                 b.n_records,
                 count(*) AS n_samples,
                 count(*) FILTER (
                   WHERE o.error LIKE '{MISSING_TAG_ERROR}'
                 ) AS n_missing_tags,
                 count(*) FILTER (
                   WHERE o.acceptance_datetime IS NOT NULL
                 ) AS n_valid_sgml,
                 min(z.filing_date) AS min_sample_filing_date,
                 max(z.filing_date) AS max_sample_filing_date,
                 string_agg(
                   bs.accession_number,
                   ', '
                   ORDER BY z.filing_date, bs.accession_number
                 ) AS evidence_accessions
          FROM block_samples AS bs
          INNER JOIN sgml_observations AS o
            ON bs.accession_number = o.accession_number
          INNER JOIN zip_blocks AS b
            ON bs.snapshot_id = b.snapshot_id
           AND bs.block_name = b.block_name
          LEFT JOIN zip_filing_records AS z
            ON bs.snapshot_id = z.snapshot_id
           AND bs.block_name = z.block_name
           AND bs.accession_number = z.accession_number
          WHERE bs.snapshot_id = ?
          GROUP BY bs.snapshot_id,
                   bs.cik,
                   bs.block_name,
                   bs.block_sha256,
                   b.n_records
        )
        SELECT snapshot_id,
               cik,
               block_name,
               block_sha256,
               n_records,
               n_samples,
               min_sample_filing_date,
               max_sample_filing_date,
               evidence_accessions
        FROM sample_status
        WHERE n_samples >= ?
          AND n_missing_tags = n_samples
          AND n_valid_sgml = 0
        ORDER BY n_records DESC, cik, block_name
        {limit_sql}
    """


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--min-samples", type=int, default=3)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if args.min_samples < 1:
        parser.error("--min-samples must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    snapshot = snapshot_id(args.zip)
    con = duckdb.connect(str(args.database), read_only=args.report_only)
    if not args.report_only:
        initialize_database(con)
        initialize_inventory_schema(con)

    rows = con.execute(candidate_sql(args.limit), [snapshot, args.min_samples]).fetchall()
    print(f"database: {args.database}")
    print(f"snapshot: {snapshot}")
    print(f"all-missing sampled blocks: {len(rows):,}")

    total_rows = sum(row[4] for row in rows)
    print(f"covered ZIP rows in those blocks: {total_rows:,}")

    for row in rows[:20]:
        _snapshot, cik, block_name, _sha, n_records, n_samples, min_date, max_date, accessions = row
        print(
            f"  CIK {cik} {block_name}: n={n_records:,}, "
            f"samples={n_samples}, dates={min_date}..{max_date}, "
            f"evidence={accessions}"
        )
    if len(rows) > 20:
        print(f"  ... {len(rows) - 20:,} more")

    if args.report_only:
        con.close()
        return

    now = datetime.now(timezone.utc)
    reason = (
        "All sampled SGML headers lack <ACCEPTANCE-DATETIME>; "
        "skip in anchor collection pending finite exception handling."
    )
    con.executemany(
        """
        INSERT INTO missing_sgml_timestamp_blocks (
          snapshot_id,
          cik,
          block_name,
          block_sha256,
          n_records,
          n_samples,
          min_sample_filing_date,
          max_sample_filing_date,
          evidence_accessions,
          reason,
          active,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, true, ?)
        ON CONFLICT (snapshot_id, block_name) DO UPDATE SET
          block_sha256 = excluded.block_sha256,
          n_records = excluded.n_records,
          n_samples = excluded.n_samples,
          min_sample_filing_date = excluded.min_sample_filing_date,
          max_sample_filing_date = excluded.max_sample_filing_date,
          evidence_accessions = excluded.evidence_accessions,
          reason = excluded.reason,
          active = true,
          updated_at = excluded.updated_at
        """,
        [(*row, reason, now) for row in rows],
    )
    con.commit()

    active_total = con.execute(
        """
        SELECT count(*), coalesce(sum(n_records), 0)
        FROM missing_sgml_timestamp_blocks
        WHERE snapshot_id = ?
          AND active
        """,
        [snapshot],
    ).fetchone()
    con.close()
    print(
        f"marked active all-missing blocks: {active_total[0]:,}; "
        f"rows: {active_total[1]:,}"
    )


if __name__ == "__main__":
    main()
