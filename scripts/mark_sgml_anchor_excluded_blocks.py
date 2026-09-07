#!/usr/bin/env python3
"""Mark SGML anchor blocks that should be skipped by future fetch passes."""

import argparse
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from build_acceptance_timestamp_rules import initialize_inventory_schema, snapshot_id
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP


TERMINAL_ERRORS = (
    "%HTTP Error 404%",
    "%read operation timed out%",
)


def terminal_fetch_failure_sql(limit: int | None) -> str:
    limit_sql = "" if limit is None else f"LIMIT {limit}"
    error_predicate = " OR ".join(f"o.error LIKE '{pattern}'" for pattern in TERMINAL_ERRORS)
    return f"""
        WITH remaining AS (
          SELECT c.snapshot_id,
                 c.cik,
                 c.block_name,
                 c.block_sha256,
                 c.n_records
          FROM block_classifications AS c
          INNER JOIN zip_blocks AS b
            ON c.snapshot_id = b.snapshot_id
           AND c.block_name = b.block_name
          WHERE c.snapshot_id = ?
            AND c.classification = 'unresolved'
            AND c.n_records > 0
            AND NOT EXISTS (
              SELECT 1
              FROM timestamp_rules AS r
              WHERE r.snapshot_id = c.snapshot_id
                AND r.block_name = c.block_name
                AND r.active
                AND r.status <> 'rejected'
            )
            AND NOT EXISTS (
              SELECT 1
              FROM missing_sgml_timestamp_blocks AS m
              WHERE m.snapshot_id = c.snapshot_id
                AND m.block_name = c.block_name
                AND m.active
            )
            AND NOT EXISTS (
              SELECT 1
              FROM sgml_anchor_excluded_blocks AS e
              WHERE e.snapshot_id = c.snapshot_id
                AND e.block_name = c.block_name
                AND e.active
            )
        ),
        sample_status AS (
          SELECT r.snapshot_id,
                 r.cik,
                 r.block_name,
                 r.block_sha256,
                 r.n_records,
                 count(*) AS n_samples,
                 count(*) FILTER (
                   WHERE o.acceptance_datetime IS NOT NULL
                 ) AS n_valid_sgml,
                 count(*) FILTER (
                   WHERE o.error IS NOT NULL AND ({error_predicate})
                 ) AS n_terminal_errors,
                 string_agg(
                   bs.accession_number,
                   ', '
                   ORDER BY bs.accession_number
                 ) AS evidence_accessions,
                 string_agg(
                   coalesce(o.error, 'no observation error'),
                   '; '
                   ORDER BY bs.accession_number
                 ) AS error_summary
          FROM remaining AS r
          INNER JOIN block_samples AS bs
            ON bs.snapshot_id = r.snapshot_id
           AND bs.block_name = r.block_name
          LEFT JOIN sgml_observations AS o
            ON o.accession_number = bs.accession_number
          GROUP BY r.snapshot_id,
                   r.cik,
                   r.block_name,
                   r.block_sha256,
                   r.n_records
        )
        SELECT snapshot_id,
               cik,
               block_name,
               block_sha256,
               n_records,
               evidence_accessions,
               error_summary
        FROM sample_status
        WHERE n_samples > 0
          AND n_valid_sgml = 0
          AND n_terminal_errors = n_samples
        ORDER BY n_records DESC, cik, block_name
        {limit_sql}
    """


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()

    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    snapshot = snapshot_id(args.zip)
    con = duckdb.connect(str(args.database))
    initialize_database(con)
    initialize_inventory_schema(con)
    con.commit()
    if args.report_only:
        con.close()
        con = duckdb.connect(str(args.database), read_only=True)

    rows = con.execute(terminal_fetch_failure_sql(args.limit), [snapshot]).fetchall()
    print(f"database: {args.database}")
    print(f"snapshot: {snapshot}")
    print(f"terminal SGML fetch failure blocks: {len(rows):,}")

    total_rows = sum(row[4] for row in rows)
    print(f"covered ZIP rows in those blocks: {total_rows:,}")

    for row in rows[:20]:
        _snapshot, cik, block_name, _sha, n_records, accessions, error_summary = row
        print(
            f"  CIK {cik} {block_name}: n={n_records:,}, "
            f"evidence={accessions}, errors={error_summary}"
        )
    if len(rows) > 20:
        print(f"  ... {len(rows) - 20:,} more")

    if args.report_only:
        con.close()
        return

    now = datetime.now(timezone.utc)
    reason = (
        "Sampled SGML anchors failed with terminal fetch errors after retry; "
        "skip in anchor collection pending manual exception handling."
    )
    con.executemany(
        """
        INSERT INTO sgml_anchor_excluded_blocks (
          snapshot_id,
          cik,
          block_name,
          block_sha256,
          n_records,
          category,
          evidence_accessions,
          error_summary,
          reason,
          active,
          updated_at
        ) VALUES (?, ?, ?, ?, ?, 'terminal_fetch_failure', ?, ?, ?, true, ?)
        ON CONFLICT (snapshot_id, block_name) DO UPDATE SET
          block_sha256 = excluded.block_sha256,
          n_records = excluded.n_records,
          category = excluded.category,
          evidence_accessions = excluded.evidence_accessions,
          error_summary = excluded.error_summary,
          reason = excluded.reason,
          active = true,
          updated_at = excluded.updated_at
        """,
        [(*row, reason, now) for row in rows],
    )
    con.commit()

    active_total = con.execute(
        """
        SELECT category, count(*), coalesce(sum(n_records), 0)
        FROM sgml_anchor_excluded_blocks
        WHERE snapshot_id = ?
          AND active
        GROUP BY category
        ORDER BY category
        """,
        [snapshot],
    ).fetchall()
    con.close()

    print("active SGML anchor exclusions:")
    for category, count, n_records in active_total:
        print(f"  {category}: {count:,} blocks; {n_records:,} rows")


if __name__ == "__main__":
    main()
