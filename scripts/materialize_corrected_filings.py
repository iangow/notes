#!/usr/bin/env python3
"""Materialize timezone-correct SEC filings from raw expanded filings."""

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from compare_filing_timestamp_sources import DATA_DIR, DEFAULT_NEW_ZIP, sql_string


DEFAULT_RAW = DATA_DIR / "edgar" / "filings_raw.parquet"
DEFAULT_OUTPUT = Path("/private/tmp/filings.parquet")
OUTSIDE_HOURS_POLICY = "outside-hours-noncorrespondence-v1"


def table_exists(con: duckdb.DuckDBPyConnection, table_name: str) -> bool:
    return bool(
        con.execute(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_name = ?
            """,
            [table_name],
        ).fetchone()[0]
    )


def snapshot_id(path: Path) -> str:
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def promote_outside_hours_rules(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
) -> int:
    if not table_exists(con, "outside_hours_scan_results"):
        return 0
    rows = con.execute(
        """
        SELECT report_json
        FROM outside_hours_scan_results
        WHERE snapshot_id = ?
          AND policy = ?
          AND status = 'boundary_supported'
        """,
        [snapshot, OUTSIDE_HOURS_POLICY],
    ).fetchall()
    promoted = 0
    for (report_json,) in rows:
        report = json.loads(report_json)
        valid_from_date = report.get("utc_segment_from_date")
        valid_from_record = report.get("first_candidate_record")
        valid_to_record = report.get("utc_segment_to_record")
        if valid_from_record is None:
            continue
        rule_id = (
            f"segment:{snapshot}:{report['digest'][:16]}:"
            f"record-{valid_from_record}-"
            f"{'end' if valid_to_record is None else valid_to_record}:utc:outside-hours"
        )
        evidence_count = int((report.get("labels") or {}).get("utc", 0))
        if evidence_count <= 0:
            continue
        con.execute(
            """
            INSERT INTO timestamp_rules (
              rule_id,
              rule_level,
              cik,
              snapshot_id,
              block_name,
              block_sha256,
              valid_from_date,
              valid_to_date,
              valid_from_record_index,
              valid_to_record_index,
              interpretation,
              evidence_count,
              confidence,
              status,
              method,
              notes,
              updated_at
            ) VALUES (?, 'segment', ?, ?, ?, ?, ?, NULL, ?, ?, 'utc', ?, 0.95,
                      'verified', 'outside_hours_utc_prefix_boundary_v1',
                      'UTC segment inferred from stored outside-hours SGML boundary scan using record-index bounds inside a physical JSON block.',
                      ?)
            ON CONFLICT (rule_id) DO UPDATE SET
              valid_from_date = excluded.valid_from_date,
              valid_to_date = excluded.valid_to_date,
              valid_from_record_index = excluded.valid_from_record_index,
              valid_to_record_index = excluded.valid_to_record_index,
              evidence_count = excluded.evidence_count,
              confidence = excluded.confidence,
              status = excluded.status,
              active = true,
              notes = excluded.notes,
              updated_at = excluded.updated_at
            """,
            [
                rule_id,
                report["cik"],
                snapshot,
                report["block"],
                report["digest"],
                valid_from_date,
                valid_from_record,
                valid_to_record,
                evidence_count,
                datetime.now(timezone.utc),
            ],
        )
        con.execute(
            """
            INSERT OR REPLACE INTO rule_evidence (
              rule_id,
              accession_number,
              evidence_role,
              observed_interpretation
            )
            SELECT ?,
                   accession_number,
                   CASE WHEN interpretation = 'utc' THEN 'training' ELSE 'boundary' END,
                   interpretation
            FROM block_samples
            WHERE snapshot_id = ?
              AND block_name = ?
              AND stratum = 'outside_hours'
              AND interpretation IN ('eastern', 'utc')
            """,
            [rule_id, snapshot, report["block"]],
        )
        promoted += 1
    return promoted


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--allow-unresolved", action="store_true")
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Allow replacing an existing output file.",
    )
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--memory-limit", default="12GB")
    parser.add_argument(
        "--limit",
        type=int,
        help="Materialize only the first N raw rows for a quick validation run.",
    )
    parser.add_argument(
        "--no-promote-collected-rules",
        action="store_true",
        help="Do not promote eligible collected SGML scan results before materializing.",
    )
    args = parser.parse_args()

    if args.threads < 1:
        parser.error("--threads must be positive")
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be positive")

    raw = args.raw.expanduser().resolve()
    output = args.output.expanduser().resolve()
    database = args.database.expanduser().resolve()
    if raw == output:
        parser.error("--raw and --output must be different files")
    if output.exists() and not args.replace:
        parser.error(f"{output} exists; pass --replace to overwrite it")

    snapshot = snapshot_id(args.zip.expanduser().resolve())
    output.parent.mkdir(parents=True, exist_ok=True)
    tmp_output = output.with_suffix(".tmp.parquet")
    tmp_output.unlink(missing_ok=True)

    con = duckdb.connect(str(database), read_only=args.no_promote_collected_rules)
    if not args.no_promote_collected_rules:
        initialize_database(con)
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'America/New_York'")
    con.execute(f"SET threads = {args.threads}")
    con.execute("SET preserve_insertion_order = false")
    con.execute(f"SET memory_limit = {sql_string(args.memory_limit)}")

    inventory_rows = con.execute(
        "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
    ).fetchone()[0]
    if inventory_rows == 0:
        raise RuntimeError(
            "No ZIP inventory found for this snapshot. Run "
            "scripts/build_acceptance_timestamp_rules.py first."
        )

    promoted_rules = 0
    if not args.no_promote_collected_rules:
        promoted_rules = promote_outside_hours_rules(con, snapshot)
        con.commit()

    con.execute(
        """
        CREATE TEMP TABLE active_block_rules_materialize AS
        SELECT cik,
               snapshot_id,
               block_name,
               block_sha256,
               interpretation,
               rule_id
        FROM active_timestamp_rules
        WHERE rule_level = 'block'
        QUALIFY row_number() OVER (
          PARTITION BY cik, snapshot_id, block_name, block_sha256
          ORDER BY confidence DESC NULLS LAST,
                   evidence_count DESC,
                   updated_at DESC,
                   rule_id
        ) = 1
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE active_cik_rules_materialize AS
        SELECT cik,
               interpretation,
               rule_id
        FROM active_timestamp_rules
        WHERE rule_level = 'cik'
        QUALIFY row_number() OVER (
          PARTITION BY cik
          ORDER BY confidence DESC NULLS LAST,
                   evidence_count DESC,
                   updated_at DESC,
                   rule_id
        ) = 1
        """
    )
    con.execute(
        """
        CREATE TEMP TABLE active_segment_rules_materialize AS
        SELECT cik,
               snapshot_id,
               block_name,
               block_sha256,
               valid_from_date,
               valid_to_date,
               valid_from_record_index,
               valid_to_record_index,
               interpretation,
               rule_id
        FROM active_timestamp_rules
        WHERE rule_level = 'segment'
        QUALIFY row_number() OVER (
          PARTITION BY cik,
                       snapshot_id,
                       block_name,
                       block_sha256,
                       valid_from_date,
                       valid_to_date,
                       valid_from_record_index,
                       valid_to_record_index
          ORDER BY confidence DESC NULLS LAST,
                   evidence_count DESC,
                   updated_at DESC,
                   rule_id
        ) = 1
        """
    )

    raw_sql = sql_string(raw)
    raw_relation = (
        f"(SELECT * FROM read_parquet({raw_sql}) LIMIT {args.limit})"
        if args.limit is not None
        else f"read_parquet({raw_sql})"
    )
    unresolved = con.execute(
        f"""
        WITH joined AS (
          SELECT raw.cik,
                 raw.accessionNumber,
                 raw.source_file,
                 raw.acceptanceDateTime,
                 z.snapshot_id,
                 z.block_name,
                 CASE
                   WHEN o.accession_number IS NOT NULL THEN 'submission_override'
                   WHEN d.accession_number IS NOT NULL THEN 'duplicate_accession_override'
                   WHEN sr.rule_id IS NOT NULL THEN 'segment_rule'
                   WHEN br.rule_id IS NOT NULL THEN 'block_rule'
                   WHEN cr.rule_id IS NOT NULL THEN 'cik_rule'
                   ELSE 'unresolved'
                 END AS provenance
          FROM {raw_relation} AS raw
          LEFT JOIN zip_filing_records AS z
            ON z.snapshot_id = ?
           AND z.block_name = raw.source_file
           AND z.accession_number = raw.accessionNumber
          LEFT JOIN effective_submission_overrides AS o
            ON o.accession_number = z.accession_number
          LEFT JOIN duplicate_accession_timestamp_overrides AS d
            ON d.accession_number = z.accession_number
          LEFT JOIN active_segment_rules_materialize AS sr
            ON sr.cik = z.cik
           AND sr.snapshot_id = z.snapshot_id
           AND sr.block_name = z.block_name
           AND sr.block_sha256 = z.block_sha256
           AND (sr.valid_from_date IS NULL OR z.filing_date >= sr.valid_from_date)
           AND (sr.valid_to_date IS NULL OR z.filing_date <= sr.valid_to_date)
           AND (sr.valid_from_record_index IS NULL OR z.record_index >= sr.valid_from_record_index)
           AND (sr.valid_to_record_index IS NULL OR z.record_index <= sr.valid_to_record_index)
          LEFT JOIN active_block_rules_materialize AS br
            ON br.cik = z.cik
           AND br.snapshot_id = z.snapshot_id
           AND br.block_name = z.block_name
           AND br.block_sha256 = z.block_sha256
          LEFT JOIN active_cik_rules_materialize AS cr
            ON cr.cik = z.cik
          WHERE raw.acceptanceDateTime IS NOT NULL
            AND raw.acceptanceDateTime <> ''
        )
        SELECT
          count(*) FILTER (WHERE snapshot_id IS NULL) AS missing_inventory_rows,
          count(*) FILTER (WHERE coalesce(provenance, 'unresolved') = 'unresolved')
            AS unresolved_timestamp_rows
        FROM joined
        """,
        [snapshot],
    ).fetchone()
    missing_inventory_rows, unresolved_timestamp_rows = unresolved
    if missing_inventory_rows:
        raise RuntimeError(
            f"{missing_inventory_rows:,} raw rows did not match ZIP inventory by "
            "source_file/accessionNumber."
        )
    if unresolved_timestamp_rows and not args.allow_unresolved:
        raise RuntimeError(
            f"{unresolved_timestamp_rows:,} rows have no timestamp rule. "
            "Pass --allow-unresolved to materialize them with the raw ZIP clock "
            "parsed as Eastern and provenance marked unresolved_raw_as_eastern "
            "or special_form_unresolved_raw_as_eastern."
        )

    out_sql = sql_string(tmp_output)
    con.execute(
        f"""
        COPY (
          WITH joined AS (
            SELECT raw.*,
                   z.zip_acceptance_datetime,
                   o.corrected_acceptance_datetime AS override_acceptance_datetime,
                   d.corrected_acceptance_datetime AS duplicate_acceptance_datetime,
                   coalesce(
                     o.interpretation,
                     CASE WHEN d.accession_number IS NOT NULL THEN 'duplicate_conflict' END,
                     sr.interpretation,
                     br.interpretation,
                     cr.interpretation
                   )
                     AS resolved_interpretation,
                   coalesce(o.accession_number, d.accession_number, sr.rule_id, br.rule_id, cr.rule_id)
                     AS reference_id,
                   CASE
                     WHEN o.accession_number IS NOT NULL THEN 'submission_override'
                     WHEN d.accession_number IS NOT NULL THEN 'duplicate_accession_override'
                     WHEN sr.rule_id IS NOT NULL THEN 'segment_rule'
                     WHEN br.rule_id IS NOT NULL THEN 'block_rule'
                     WHEN cr.rule_id IS NOT NULL THEN 'cik_rule'
                     ELSE 'unresolved'
                   END AS resolved_provenance
            FROM {raw_relation} AS raw
            LEFT JOIN zip_filing_records AS z
              ON z.snapshot_id = '{snapshot}'
             AND z.block_name = raw.source_file
             AND z.accession_number = raw.accessionNumber
            LEFT JOIN effective_submission_overrides AS o
              ON o.accession_number = z.accession_number
            LEFT JOIN duplicate_accession_timestamp_overrides AS d
              ON d.accession_number = z.accession_number
            LEFT JOIN active_segment_rules_materialize AS sr
              ON sr.cik = z.cik
             AND sr.snapshot_id = z.snapshot_id
             AND sr.block_name = z.block_name
             AND sr.block_sha256 = z.block_sha256
             AND (sr.valid_from_date IS NULL OR z.filing_date >= sr.valid_from_date)
             AND (sr.valid_to_date IS NULL OR z.filing_date <= sr.valid_to_date)
             AND (sr.valid_from_record_index IS NULL OR z.record_index >= sr.valid_from_record_index)
             AND (sr.valid_to_record_index IS NULL OR z.record_index <= sr.valid_to_record_index)
            LEFT JOIN active_block_rules_materialize AS br
              ON br.cik = z.cik
             AND br.snapshot_id = z.snapshot_id
             AND br.block_name = z.block_name
             AND br.block_sha256 = z.block_sha256
            LEFT JOIN active_cik_rules_materialize AS cr
              ON cr.cik = z.cik
          )
          SELECT * EXCLUDE (
                   zip_acceptance_datetime,
                   override_acceptance_datetime,
                   duplicate_acceptance_datetime,
                   resolved_interpretation,
                   reference_id,
                   resolved_provenance
                 ) REPLACE (
                   CASE
                     WHEN acceptanceDateTime IS NULL
                       OR acceptanceDateTime = ''
                       THEN NULL::TIMESTAMPTZ
                     WHEN resolved_provenance = 'submission_override'
                       THEN override_acceptance_datetime
                            AT TIME ZONE 'America/New_York'
                     WHEN resolved_provenance = 'duplicate_accession_override'
                       THEN duplicate_acceptance_datetime
                            AT TIME ZONE 'America/New_York'
                     WHEN resolved_interpretation = 'eastern'
                       THEN zip_acceptance_datetime AT TIME ZONE 'America/New_York'
                     WHEN resolved_interpretation = 'utc'
                       THEN zip_acceptance_datetime AT TIME ZONE 'UTC'
                     ELSE
                       TRY_CAST(
                         regexp_replace(acceptanceDateTime, 'Z$', '')
                         AS TIMESTAMP
                       ) AT TIME ZONE 'America/New_York'
                   END AS acceptanceDateTime
                 ),
                 CASE
                   WHEN acceptanceDateTime IS NULL
                     OR acceptanceDateTime = ''
                     THEN 'raw_missing'
                   WHEN resolved_provenance <> 'unresolved'
                     THEN resolved_provenance
                   WHEN form IN ('CORRESP', 'UPLOAD', 'DRSLTR')
                     THEN 'special_form_unresolved_raw_as_eastern'
                   ELSE 'unresolved_raw_as_eastern'
                 END AS timestamp_provenance,
                 reference_id AS timestamp_reference_id,
                 CASE
                   WHEN acceptanceDateTime IS NULL
                     OR acceptanceDateTime = ''
                     THEN 'missing'
                   ELSE coalesce(resolved_interpretation, 'unresolved')
                 END AS timestamp_interpretation
          FROM joined
        )
        TO {out_sql}
        (FORMAT PARQUET, COMPRESSION SNAPPY)
        """
    )
    tmp_output.replace(output)

    summary = con.execute(
        f"""
        SELECT timestamp_provenance,
               timestamp_interpretation,
               count(*) AS n
        FROM read_parquet({sql_string(output)})
        GROUP BY timestamp_provenance, timestamp_interpretation
        ORDER BY n DESC, timestamp_provenance, timestamp_interpretation
        """
    ).fetchall()
    rows = con.execute(
        f"SELECT count(*) FROM read_parquet({sql_string(output)})"
    ).fetchone()[0]
    schema = con.execute(
        f"""
        SELECT column_type
        FROM (DESCRIBE SELECT * FROM read_parquet({sql_string(output)}))
        WHERE column_name = 'acceptanceDateTime'
        """
    ).fetchone()[0]
    con.close()

    print(f"wrote {output} ({rows:,} rows)")
    print(f"acceptanceDateTime: {schema}")
    if not args.no_promote_collected_rules:
        print(f"promoted collected rules: {promoted_rules:,}")
    for provenance, interpretation, count in summary:
        print(f"  {provenance}\t{interpretation}\t{count:,}")


if __name__ == "__main__":
    main()
