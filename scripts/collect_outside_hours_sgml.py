#!/usr/bin/env python3
"""Collect SGML evidence for non-correspondence outside-hours filing clocks."""

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DATA_DIR, DEFAULT_DB, initialize_database
from benchmark_sgml_block_sampling import (
    DEFAULT_USER_AGENT,
    fetch_sgml,
    interpretation,
    parse_zip_datetime,
)
from build_acceptance_timestamp_rules import initialize_inventory_schema, snapshot_id
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP
from fetch_sgml_anchors import (
    NetworkRateLimiter,
    cached_observation,
    insert_sgml_observation,
)


POLICY = "outside-hours-corrected-top-v2"
EXCLUDED_FORMS = ("EFFECT", "CORRESP", "UPLOAD", "DRSLTR")
EXPECTED_STATUSES = {
    "all_checked_utc",
    "prefix_capped_utc",
    "starts_eastern",
    "fully_checked_no_utc",
    "full_scan_all_eastern",
    "full_scan_all_utc",
    "full_scan_clean_boundary",
}


def outside_hours_predicate(alias: str = "z") -> str:
    return f"(hour({alias}.zip_acceptance_datetime) >= 22 OR hour({alias}.zip_acceptance_datetime) < 6)"


def target_blocks_sql(order: str, limit: int | None, include_ruled: bool) -> str:
    order_sql = {
        "outside-count": "outside_rows DESC, b.n_records DESC, b.cik, b.block_name",
        "fewest-rows": "b.n_records, outside_rows DESC, b.cik, b.block_name",
        "fewest-outside": "outside_rows, b.n_records, b.cik, b.block_name",
        "size": "b.n_records DESC, outside_rows DESC, b.cik, b.block_name",
        "hash": "hash(b.block_name), b.block_name",
        "oldest": "first_outside_date NULLS LAST, b.cik, b.block_name",
        "newest": "last_outside_date DESC NULLS LAST, b.cik, b.block_name",
    }[order]
    limit_sql = "" if limit is None else f"LIMIT {limit}"
    rule_filter = (
        ""
        if include_ruled
        else """
          AND NOT EXISTS (
            SELECT 1
            FROM timestamp_rules AS r
            WHERE r.snapshot_id = o.snapshot_id
              AND r.block_name = o.block_name
              AND r.active
              AND r.status <> 'rejected'
          )
        """
    )
    excluded_forms = ", ".join("'" + form + "'" for form in EXCLUDED_FORMS)
    return f"""
        WITH outside AS (
          SELECT z.snapshot_id,
                 z.block_name,
                 count(*) AS outside_rows,
                 min(z.filing_date) AS first_outside_date,
                 max(z.filing_date) AS last_outside_date
          FROM zip_filing_records AS z
          INNER JOIN remaining_outside AS f
            ON f.source_file = z.block_name
           AND f.accessionNumber = z.accession_number
          WHERE z.snapshot_id = ?
            AND z.zip_acceptance_datetime IS NOT NULL
            AND f.local_datetime >= CAST(? AS TIMESTAMP)
            AND coalesce(z.form, '') NOT IN ({excluded_forms})
          GROUP BY z.snapshot_id, z.block_name
        )
        SELECT b.snapshot_id,
               b.cik,
               b.block_name,
               b.block_sha256,
               b.n_records,
               o.outside_rows,
               o.first_outside_date,
               o.last_outside_date
        FROM outside AS o
        INNER JOIN zip_blocks AS b
          ON b.snapshot_id = o.snapshot_id
         AND b.block_name = o.block_name
        WHERE b.n_records > 0
          {rule_filter}
          AND NOT EXISTS (
            SELECT 1
            FROM missing_sgml_timestamp_blocks AS m
            WHERE m.snapshot_id = o.snapshot_id
              AND m.block_name = o.block_name
              AND m.active
          )
          AND NOT EXISTS (
            SELECT 1
            FROM sgml_anchor_excluded_blocks AS e
            WHERE e.snapshot_id = o.snapshot_id
              AND e.block_name = o.block_name
              AND e.active
          )
          AND NOT EXISTS (
            SELECT 1
            FROM outside_hours_scan_results AS done
            WHERE done.snapshot_id = o.snapshot_id
              AND done.block_name = o.block_name
              AND done.policy = '{POLICY}'
              AND done.status IN (
                'all_checked_utc',
                'boundary_supported',
                'prefix_and_last_utc',
                'starts_eastern',
                'fully_checked_no_utc',
                'full_scan_all_eastern',
                'full_scan_all_utc',
                'full_scan_clean_boundary'
              )
          )
        ORDER BY {order_sql}
        {limit_sql}
    """


def ensure_scan_schema(con: duckdb.DuckDBPyConnection) -> None:
    initialize_database(con)


def candidate_records(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
    block_name: str,
) -> list[tuple]:
    excluded_forms = ", ".join("'" + form + "'" for form in EXCLUDED_FORMS)
    return con.execute(
        f"""
        SELECT record_index,
               accession_number,
               filing_date,
               form,
               zip_acceptance_datetime_text,
               zip_acceptance_datetime
        FROM zip_filing_records AS z
        WHERE snapshot_id = ?
          AND block_name = ?
          AND accession_number IS NOT NULL
          AND zip_acceptance_datetime IS NOT NULL
          AND coalesce(form, '') NOT IN ({excluded_forms})
        ORDER BY record_index, accession_number
        """,
        [snapshot, block_name],
    ).fetchall()


def cached_or_fetch(
    database: Path,
    cik: int,
    accession: str,
    user_agent: str,
    rate_limiter: NetworkRateLimiter,
):
    cached = cached_observation(database, accession)
    if cached:
        return {
            "acceptance": cached[0],
            "source": "cache",
            "elapsed_ms": 0.0,
            "error": cached[1],
            "result": None,
        }
    rate_limiter.wait()
    result = fetch_sgml(cik, accession, user_agent)
    return {
        "acceptance": result["acceptance"],
        "source": "network",
        "elapsed_ms": result["elapsed_ms"],
        "error": result["error"],
        "result": result,
    }


def classify(zip_text: str, sgml_value, error: str | None):
    diff_min = None
    label = "unresolved"
    if sgml_value is not None and zip_text:
        seconds = (parse_zip_datetime(zip_text) - sgml_value).total_seconds()
        if seconds % 60 == 0:
            diff_min = int(seconds / 60)
            label = interpretation(diff_min)
        else:
            label = "anomalous"
    elif error and "ACCEPTANCE-DATETIME tag not found" in error:
        label = "unresolved"
    return diff_min, label


def scan_block(
    database: Path,
    target: tuple,
    max_prefix: int,
    tail_checks: int,
    check_last: bool,
    full_scan: bool,
    user_agent: str,
    rate_limiter: NetworkRateLimiter,
    executor: ThreadPoolExecutor,
    since_date: str,
):
    (
        snapshot,
        cik,
        block_name,
        block_sha256,
        n_records,
        outside_rows,
        first_outside_date,
        last_outside_date,
    ) = target
    started = time.monotonic()
    with duckdb.connect(str(database), read_only=True) as con:
        rows = candidate_records(
            con,
            snapshot,
            block_name,
        )

    observed = {}

    def check(index: int):
        if index not in observed:
            record_index, accession, filing_date, form, zip_text, _zip_timestamp = rows[index]
            observation = cached_or_fetch(
                database,
                cik,
                accession,
                user_agent,
                rate_limiter,
            )
            diff_min, label = classify(
                zip_text,
                observation["acceptance"],
                observation["error"],
            )
            observed[index] = {
                "record_index": record_index,
                "accession": accession,
                "filing_date": filing_date,
                "form": form,
                "zip_text": zip_text,
                "acceptance": observation["acceptance"],
                "diff_min": diff_min,
                "label": label,
                "source": observation["source"],
                "elapsed_ms": observation["elapsed_ms"],
                "error": observation["error"],
                "result": observation["result"],
            }
        return observed[index]["label"]

    first_eastern_index = None
    checked_last = False
    last_label = None
    if full_scan:
        for index in range(len(rows)):
            check(index)
    else:
        prefix_count = min(len(rows), max_prefix)
        for index in range(prefix_count):
            label = check(index)
            if label == "eastern":
                first_eastern_index = index
                break
            if label != "utc":
                break

        if (
            first_eastern_index is None
            and check_last
            and len(rows) > prefix_count
            and all(observed[index]["label"] == "utc" for index in range(prefix_count))
        ):
            last_label = check(len(rows) - 1)
            checked_last = True
            if last_label == "eastern":
                first_eastern_index = len(rows) - 1

        if first_eastern_index is not None and tail_checks > 0:
            tail = len(rows) - first_eastern_index - 1
            for step in range(1, tail_checks + 1):
                if tail <= 0:
                    break
                check(first_eastern_index + max(1, round(tail * step / tail_checks)))

    labels = [value["label"] for value in observed.values()]
    if full_scan:
        eastern_indices = [
            index for index, value in observed.items() if value["label"] == "eastern"
        ]
        first_eastern_index = min(eastern_indices) if eastern_indices else None
    checked_after_boundary = [
        value["label"]
        for index, value in observed.items()
        if first_eastern_index is not None and index > first_eastern_index
    ]
    utc_prefix = [
        value
        for index, value in observed.items()
        if first_eastern_index is not None and index < first_eastern_index
    ]
    first_eastern = (
        None
        if first_eastern_index is None
        else observed[first_eastern_index]
    )
    utc_segment_from_date = None
    if utc_prefix and first_eastern is not None:
        min_utc_date = min(value["filing_date"] for value in utc_prefix)
        max_utc_date = max(value["filing_date"] for value in utc_prefix)
        if first_eastern["filing_date"] < min_utc_date:
            utc_segment_from_date = min_utc_date

    if not rows:
        status = "no_eligible_rows"
    elif any(label in {"anomalous", "unresolved"} for label in labels):
        status = "incomplete"
    elif full_scan and set(labels) == {"utc"}:
        status = "full_scan_all_utc"
    elif full_scan and set(labels) == {"eastern"}:
        status = "full_scan_all_eastern"
    elif full_scan and first_eastern_index is not None and "utc" in checked_after_boundary:
        status = "full_scan_mixed_reversal"
    elif full_scan and first_eastern_index is not None:
        status = "full_scan_clean_boundary"
    elif first_eastern_index is None and checked_last and last_label == "utc":
        status = "prefix_and_last_utc"
    elif first_eastern_index is None and len(rows) > max_prefix:
        status = "prefix_capped_utc"
    elif first_eastern_index is None:
        status = "all_checked_utc"
    elif first_eastern_index == 0 and all(label != "utc" for label in labels):
        status = "starts_eastern"
    elif "utc" in checked_after_boundary:
        status = "reversal"
    elif checked_last or utc_segment_from_date is None:
        status = "date_boundary_ambiguous"
    else:
        status = "boundary_supported"

    sample_rows = []
    network_observations = []
    for index, value in sorted(observed.items()):
        sample_rows.append(
            [
                snapshot,
                cik,
                "outside_hours",
                block_name,
                block_sha256,
                value["accession"],
                f"outside_record_{value['record_index']}",
                value["zip_text"],
                value["acceptance"],
                value["diff_min"],
                value["label"] if value["error"] is None else "unresolved",
                value["source"],
                datetime.now(timezone.utc),
            ]
        )
        if value["source"] == "network":
            network_observations.append((value["accession"], value["result"]))
        print(
            f"  {block_name} {value['record_index']}: {value['accession']} "
            f"{value['form']} -> {value['diff_min']} min ({value['label']}), "
            f"{value['source']}, {value['elapsed_ms']:.0f} ms",
            flush=True,
        )

    report = {
        "snapshot": snapshot,
        "cik": cik,
        "block": block_name,
        "digest": block_sha256,
        "n_records": n_records,
        "outside_rows": outside_rows,
        "first_outside_date": str(first_outside_date),
        "last_outside_date": str(last_outside_date),
        "eligible_rows": len(rows),
        "eligible_rows_from_first_outside": None,
        "checked": len(observed),
        "new": sum(1 for value in observed.values() if value["source"] == "network"),
        "cached": sum(1 for value in observed.values() if value["source"] == "cache"),
        "first_eastern_record": None
        if first_eastern_index is None
        else rows[first_eastern_index][0],
        "first_candidate_record": None if not rows else rows[0][0],
        "last_record_checked": checked_last,
        "full_scan": full_scan,
        "utc_segment_from_date": None
        if utc_segment_from_date is None
        else str(utc_segment_from_date),
        "utc_segment_to_record": None
        if first_eastern_index is None
        else rows[first_eastern_index][0] - 1,
        "status": status,
        "labels": {label: labels.count(label) for label in sorted(set(labels))},
        "seconds": round(time.monotonic() - started, 3),
    }
    return report, sample_rows, network_observations


def write_outside_hours_segment_rule(
    con: duckdb.DuckDBPyConnection,
    report: dict,
    sample_rows: list[list],
) -> bool:
    if report["status"] != "boundary_supported":
        return False
    valid_from_record = report.get("first_candidate_record")
    if valid_from_record is None:
        return False
    valid_to_record = report.get("utc_segment_to_record")
    valid_from_date = report.get("utc_segment_from_date")
    rule_id = (
        f"segment:{report['snapshot']}:{report['digest'][:16]}:"
        f"record-{valid_from_record}-"
        f"{'end' if valid_to_record is None else valid_to_record}:utc:outside-hours"
    )
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
                  'UTC segment inferred from outside-hours SGML scan using record-index bounds inside a physical JSON block.',
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
            report["snapshot"],
            report["block"],
            report["digest"],
            valid_from_date,
            valid_from_record,
            valid_to_record,
            report["labels"].get("utc", 0),
            datetime.now(timezone.utc),
        ],
    )
    for row in sample_rows:
        accession = row[5]
        observed_interpretation = row[10]
        if observed_interpretation not in {"eastern", "utc"}:
            continue
        role = "training" if observed_interpretation == "utc" else "boundary"
        con.execute(
            """
            INSERT OR REPLACE INTO rule_evidence (
              rule_id,
              accession_number,
              evidence_role,
              observed_interpretation
            ) VALUES (?, ?, ?, ?)
            """,
            [rule_id, accession, role, observed_interpretation],
        )
    return True


def write_observed_accession_overrides(
    con: duckdb.DuckDBPyConnection,
    report: dict,
    sample_rows: list[list],
) -> int:
    written = 0
    for row in sample_rows:
        (
            _snapshot,
            cik,
            _stratum,
            _block_name,
            _block_sha256,
            accession,
            _sample_position,
            zip_text,
            sgml_value,
            _diff_min,
            observed_interpretation,
            _request_source,
            _recorded_at,
        ) = row
        if observed_interpretation not in {"eastern", "utc"} or sgml_value is None:
            continue
        con.execute(
            """
            INSERT INTO submission_overrides (
              accession_number,
              cik,
              zip_acceptance_datetime,
              corrected_acceptance_datetime,
              interpretation,
              evidence_source,
              source_url,
              reason,
              updated_at
            ) VALUES (
              ?,
              ?,
              TRY_CAST(regexp_replace(?, 'Z$', '') AS TIMESTAMP),
              ?,
              ?,
              'sgml',
              NULL,
              'Direct SGML observation from outside-hours scan.',
              ?
            )
            ON CONFLICT (accession_number) DO UPDATE SET
              cik = excluded.cik,
              zip_acceptance_datetime = excluded.zip_acceptance_datetime,
              corrected_acceptance_datetime = excluded.corrected_acceptance_datetime,
              interpretation = excluded.interpretation,
              evidence_source = excluded.evidence_source,
              reason = excluded.reason,
              updated_at = excluded.updated_at
            """,
            [
                accession,
                cik,
                zip_text,
                sgml_value,
                observed_interpretation,
                datetime.now(timezone.utc),
            ],
        )
        written += 1
    return written


def write_batch(
    database: Path,
    analyses: list[tuple],
    lock_timeout: float,
    promote_rules: bool,
    promote_overrides: bool,
) -> int:
    deadline = time.monotonic() + lock_timeout
    while True:
        try:
            con = duckdb.connect(str(database))
            break
        except duckdb.IOException:
            if time.monotonic() >= deadline:
                raise
            time.sleep(1)
    try:
        ensure_scan_schema(con)
        con.execute("BEGIN TRANSACTION")
        rules = 0
        overrides = 0
        for report, sample_rows, network_observations in analyses:
            for accession, result in network_observations:
                insert_sgml_observation(con, report["cik"], accession, result)
            if sample_rows:
                con.executemany(
                    """
                    INSERT OR REPLACE INTO block_samples VALUES
                      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    sample_rows,
                )
            con.execute(
                """
                INSERT OR REPLACE INTO outside_hours_scan_results VALUES
                  (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    report["snapshot"],
                    report["block"],
                    POLICY,
                    report["digest"],
                    report["status"],
                    json.dumps(report),
                    datetime.now(timezone.utc),
                ],
            )
            if promote_rules:
                rules += int(write_outside_hours_segment_rule(con, report, sample_rows))
            if promote_overrides:
                overrides += write_observed_accession_overrides(con, report, sample_rows)
        con.commit()
        return rules, overrides
    finally:
        con.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--filings", type=Path, default=DATA_DIR / "edgar" / "filings.parquet")
    parser.add_argument("--dry-run", action="store_true", help="List targets without fetching or writing.")
    parser.add_argument("--max-blocks", type=int, default=100)
    parser.add_argument(
        "--block-name",
        help="Scan one specific physical JSON block, such as CIK0002012383.json.",
    )
    parser.add_argument("--max-seconds", type=float)
    parser.add_argument("--max-prefix", type=int, default=100)
    parser.add_argument("--tail-checks", type=int, default=3)
    parser.add_argument(
        "--no-check-last",
        action="store_true",
        help="Do not check the last eligible record when the prefix is all UTC.",
    )
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--batch-blocks", type=int, default=50)
    parser.add_argument("--write-lock-timeout", type=float, default=300.0)
    parser.add_argument("--max-requests-per-second", type=float, default=8.0)
    parser.add_argument(
        "--order",
        choices=[
            "outside-count",
            "fewest-rows",
            "fewest-outside",
            "size",
            "hash",
            "oldest",
            "newest",
        ],
        default="outside-count",
    )
    parser.add_argument(
        "--since-date",
        default="2025-01-01",
        help="Only consider outside-hours filings on or after this date.",
    )
    parser.add_argument("--include-ruled", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument(
        "--no-promote-rules",
        action="store_true",
        help="Persist observations and scan reports without creating timestamp_rules.",
    )
    parser.add_argument(
        "--full-scan",
        action="store_true",
        help="Check every eligible row in each selected block.",
    )
    parser.add_argument(
        "--promote-observed-overrides",
        action="store_true",
        help="Create exact submission_overrides for directly observed SGML rows.",
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    if args.max_blocks is not None and args.max_blocks < 1:
        parser.error("--max-blocks must be positive")
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("--max-seconds must be positive")
    if args.max_prefix < 1:
        parser.error("--max-prefix must be positive")
    if args.tail_checks < 0:
        parser.error("--tail-checks must be non-negative")
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.batch_blocks < 1:
        parser.error("--batch-blocks must be positive")
    if args.write_lock_timeout <= 0:
        parser.error("--write-lock-timeout must be positive")
    if args.max_requests_per_second <= 0:
        parser.error("--max-requests-per-second must be positive")

    database = args.database.expanduser().resolve()
    snapshot = snapshot_id(args.zip.expanduser().resolve())
    if not args.dry_run:
        with duckdb.connect(str(database)) as con:
            initialize_database(con)
            initialize_inventory_schema(con)
            ensure_scan_schema(con)
            con.commit()

    with duckdb.connect(str(database), read_only=True) as con:
        con.execute("""
            CREATE TEMP TABLE remaining_outside AS
            SELECT DISTINCT source_file, accessionNumber,
                   acceptanceDateTime AT TIME ZONE 'America/New_York' AS local_datetime
            FROM read_parquet(?)
            WHERE coalesce(form, '') NOT IN ('EFFECT', 'CORRESP', 'UPLOAD', 'DRSLTR')
              AND (CAST(local_datetime AS TIME) > TIME '22:00:00'
                   OR CAST(local_datetime AS TIME) < TIME '06:00:00')
        """, [str(args.filings.expanduser().resolve())])
        inventory_rows = con.execute(
            "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
        ).fetchone()[0]
        if inventory_rows == 0:
            raise RuntimeError(
                "No ZIP inventory found for this snapshot. Run "
                "scripts/build_acceptance_timestamp_rules.py first."
            )
        if args.block_name:
            con.execute("DELETE FROM remaining_outside WHERE source_file <> ?", [args.block_name])
        targets = con.execute(
            target_blocks_sql(args.order, args.max_blocks, args.include_ruled),
            [snapshot, args.since_date],
        ).fetchall()

    print(f"database: {database}")
    print(f"snapshot: {snapshot}")
    print(f"selected blocks: {len(targets):,}")
    if args.dry_run:
        for target in targets:
            print(target)
        return
    print(
        f"outside-hours forms: excluding {', '.join(EXCLUDED_FORMS)}; "
        f"since {args.since_date}"
    )
    print(
        f"workers: {args.workers}; max network rate: "
        f"{args.max_requests_per_second:.2f} req/s; write batch: {args.batch_blocks}"
    )

    outcomes = {}
    checked = 0
    new = 0
    cached = 0
    rules = 0
    overrides = 0
    started = time.monotonic()
    limiter = NetworkRateLimiter(1 / args.max_requests_per_second)
    pending = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for offset, target in enumerate(targets, start=1):
            if args.max_seconds is not None and time.monotonic() - started >= args.max_seconds:
                print(
                    f"Reached --max-seconds after {offset - 1:,} blocks; stopping.",
                    flush=True,
                )
                break
            (
                _snapshot,
                cik,
                block_name,
                _digest,
                n_records,
                outside_rows,
                first_date,
                last_date,
            ) = target
            print(
                f"{offset:,}/{len(targets):,} CIK {cik} {block_name} "
                f"n={n_records:,}; outside={outside_rows:,}; "
                f"dates={first_date}..{last_date}",
                flush=True,
            )
            analysis = scan_block(
                database,
                target,
                args.max_prefix,
                args.tail_checks,
                not args.no_check_last,
                args.full_scan,
                args.user_agent,
                limiter,
                executor,
                args.since_date,
            )
            report = analysis[0]
            outcomes[report["status"]] = outcomes.get(report["status"], 0) + 1
            checked += report["checked"]
            new += report["new"]
            cached += report["cached"]
            pending.append(analysis)
            if len(pending) >= args.batch_blocks:
                print(f"Writing batch of {len(pending):,} blocks ...", flush=True)
                batch_rules, batch_overrides = write_batch(
                    database,
                    pending,
                    args.write_lock_timeout,
                    not args.no_promote_rules,
                    args.promote_observed_overrides,
                )
                rules += batch_rules
                overrides += batch_overrides
                pending.clear()
            if report["status"] not in EXPECTED_STATUSES:
                print("EXCEPTION " + json.dumps(report), flush=True)
        if pending:
            print(f"Writing final batch of {len(pending):,} blocks ...", flush=True)
            batch_rules, batch_overrides = write_batch(
                database,
                pending,
                args.write_lock_timeout,
                not args.no_promote_rules,
                args.promote_observed_overrides,
            )
            rules += batch_rules
            overrides += batch_overrides

    print(
        "Summary: "
        f"blocks={sum(outcomes.values()):,}, checked={checked:,}, "
        f"new={new:,}, cached={cached:,}, rules={rules:,}, "
        f"overrides={overrides:,}, "
        f"wall_time={time.monotonic() - started:.2f}s",
        flush=True,
    )
    for status, count in sorted(outcomes.items()):
        print(f"  {status}: {count:,}", flush=True)


if __name__ == "__main__":
    main()
