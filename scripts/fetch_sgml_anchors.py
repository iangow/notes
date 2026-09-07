#!/usr/bin/env python3
"""Fetch SGML anchors for unresolved SEC submissions ZIP blocks."""

import argparse
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from benchmark_sgml_block_sampling import (
    DEFAULT_USER_AGENT,
    fetch_sgml,
    interpretation,
    parse_zip_datetime,
)
from build_acceptance_timestamp_rules import initialize_inventory_schema, snapshot_id
from compare_filing_timestamp_sources import DEFAULT_NEW_ZIP


def choose_targets(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
    classifications: tuple[str, ...],
    max_blocks: int | None,
    order: str,
):
    order_sql = {
        "size": "b.n_records DESC, b.cik, b.block_name",
        "hash": "hash(b.block_name), b.block_name",
        "oldest": "b.min_filing_date NULLS LAST, b.cik, b.block_name",
        "newest": "b.max_filing_date DESC NULLS LAST, b.cik, b.block_name",
    }[order]
    limit_sql = "" if max_blocks is None else f"LIMIT {max_blocks}"
    placeholders = ", ".join("?" for _ in classifications)
    return con.execute(
        f"""
        SELECT c.snapshot_id,
               c.cik,
               c.block_name,
               c.block_sha256,
               c.n_records,
               b.min_filing_date,
               b.max_filing_date,
               c.classification
        FROM block_classifications AS c
        INNER JOIN zip_blocks AS b
          ON c.snapshot_id = b.snapshot_id
         AND c.block_name = b.block_name
        WHERE c.snapshot_id = ?
          AND (
            c.classification IN ({placeholders})
            OR (
              c.stratum = 'sgml_anchor'
              AND c.classification IN ('eastern', 'utc')
            )
          )
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
        ORDER BY {order_sql}
        {limit_sql}
        """,
        [snapshot, *classifications],
    ).fetchall()


def block_sample_records(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
    block_name: str,
    sample_count: int,
):
    rows = con.execute(
        """
        SELECT record_index,
               accession_number,
               filing_date,
               zip_acceptance_datetime_text,
               zip_acceptance_datetime
        FROM zip_filing_records
        WHERE snapshot_id = ?
          AND block_name = ?
          AND accession_number IS NOT NULL
          AND zip_acceptance_datetime IS NOT NULL
        ORDER BY filing_date, record_index, accession_number
        """,
        [snapshot, block_name],
    ).fetchall()
    if not rows:
        return []
    if len(rows) == 1:
        indices = [0]
    else:
        indices = sorted(
            {
                round(i * (len(rows) - 1) / (sample_count - 1))
                for i in range(sample_count)
            }
        )

    samples = []
    for index in indices:
        position = sample_position(index, len(rows))
        samples.append((*rows[index], position))
    return samples


def cached_observation(database: Path, accession: str):
    con = duckdb.connect(str(database), read_only=True)
    try:
        return con.execute(
            """
            SELECT acceptance_datetime, error
            FROM sgml_observations
            WHERE accession_number = ?
              AND (
                acceptance_datetime IS NOT NULL
                OR error LIKE '%ACCEPTANCE-DATETIME tag not found%'
              )
            """,
            [accession],
        ).fetchone()
    finally:
        con.close()


def write_sgml_observation(database: Path, cik: int, accession: str, result: dict):
    con = duckdb.connect(str(database))
    try:
        insert_sgml_observation(con, cik, accession, result)
        con.commit()
    finally:
        con.close()


def insert_sgml_observation(
    con: duckdb.DuckDBPyConnection, cik: int, accession: str, result: dict
):
    con.execute(
        """
        INSERT INTO sgml_observations BY NAME
        SELECT ? AS accession_number,
               ? AS cik,
               ? AS acceptance_datetime,
               ? AS source_url,
               ? AS retrieved_at,
               ? AS elapsed_ms,
               ? AS http_status,
               ? AS content_sha256,
               ? AS sgml_header,
               ? AS error
        ON CONFLICT (accession_number) DO UPDATE SET
          acceptance_datetime = excluded.acceptance_datetime,
          source_url = excluded.source_url,
          retrieved_at = excluded.retrieved_at,
          elapsed_ms = excluded.elapsed_ms,
          http_status = excluded.http_status,
          content_sha256 = excluded.content_sha256,
          sgml_header = excluded.sgml_header,
          error = excluded.error
        """,
        [
            accession,
            cik,
            result["acceptance"],
            result["url"],
            result["retrieved_at"],
            result["elapsed_ms"],
            result["status"],
            result["digest"],
            result["text"],
            result["error"],
        ],
    )


def cached_or_fetch(database: Path, cik: int, accession: str, user_agent: str):
    cached = cached_observation(database, accession)
    if cached:
        return cached[0], "cache", 0.0, cached[1]

    result = fetch_sgml(cik, accession, user_agent)
    write_sgml_observation(database, cik, accession, result)
    return result["acceptance"], "network", result["elapsed_ms"], result["error"]


class NetworkRateLimiter:
    def __init__(self, delay: float):
        self.delay = delay
        self.lock = threading.Lock()
        self.next_request_at = 0.0

    def wait(self):
        if self.delay <= 0:
            return
        with self.lock:
            now = time.monotonic()
            wait_seconds = max(0.0, self.next_request_at - now)
            self.next_request_at = max(now, self.next_request_at) + self.delay
        if wait_seconds > 0:
            time.sleep(wait_seconds)


def cached_or_fetch_without_write(
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


def sample_position(index: int, count: int) -> str:
    if index == 0:
        return "first"
    if index == count - 1:
        return "last"
    return f"quantile_{index / (count - 1):.2f}"


def classify_labels(labels: list[str]) -> str:
    unique = set(labels)
    if not labels:
        return "unresolved"
    if unique == {"eastern"}:
        return "eastern"
    if unique == {"utc"}:
        return "utc"
    if "anomalous" in unique:
        return "anomalous"
    return "mixed"


def write_block_rule(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
    cik: int,
    block_name: str,
    block_sha256: str,
    classification: str,
    evidence_count: int,
    min_evidence: int,
    n_records: int,
):
    required_evidence = min(min_evidence, n_records)
    if classification not in {"eastern", "utc"} or evidence_count < required_evidence:
        return False
    rule_id = f"block:{snapshot}:{block_sha256[:16]}:sgml"
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
          interpretation,
          evidence_count,
          confidence,
          status,
          method,
          notes,
          updated_at
        ) VALUES (?, 'block', ?, ?, ?, ?, NULL, NULL, ?, ?, 1.0,
                  'verified', 'sgml_block_uniform_v1',
                  'Uniform block rule derived from sampled SGML anchors.',
                  ?)
        ON CONFLICT (rule_id) DO UPDATE SET
          interpretation = excluded.interpretation,
          evidence_count = excluded.evidence_count,
          confidence = excluded.confidence,
          status = excluded.status,
          active = true,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        [
            rule_id,
            cik,
            snapshot,
            block_name,
            block_sha256,
            classification,
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
               'training',
               interpretation
        FROM block_samples
        WHERE snapshot_id = ?
          AND block_name = ?
          AND interpretation = ?
        """,
        [rule_id, snapshot, block_name, classification],
    )
    return True


def write_segment_rule(
    con: duckdb.DuckDBPyConnection,
    snapshot: str,
    cik: int,
    block_name: str,
    block_sha256: str,
    classification: str,
    evidence_count: int,
    valid_from_date,
):
    if classification not in {"eastern", "utc"} or evidence_count == 0:
        return False
    rule_id = (
        f"segment:{snapshot}:{block_sha256[:16]}:"
        f"{valid_from_date}:{classification}:sgml"
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
          interpretation,
          evidence_count,
          confidence,
          status,
          method,
          notes,
          updated_at
        ) VALUES (?, 'segment', ?, ?, ?, ?, ?, NULL, ?, ?, 0.95,
                  'verified', 'sgml_segment_from_first_valid_v1',
                  'Dated segment rule derived from agreeing SGML anchors after older missing-tag samples.',
                  ?)
        ON CONFLICT (rule_id) DO UPDATE SET
          interpretation = excluded.interpretation,
          evidence_count = excluded.evidence_count,
          confidence = excluded.confidence,
          status = excluded.status,
          active = true,
          notes = excluded.notes,
          updated_at = excluded.updated_at
        """,
        [
            rule_id,
            cik,
            snapshot,
            block_name,
            block_sha256,
            valid_from_date,
            classification,
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
               'training',
               interpretation
        FROM block_samples
        WHERE snapshot_id = ?
          AND block_name = ?
          AND interpretation = ?
        """,
        [rule_id, snapshot, block_name, classification],
    )
    return True


def collect_block_analysis(
    database: Path,
    target,
    sample_count: int,
    min_evidence: int,
    user_agent: str,
    rate_limiter: NetworkRateLimiter,
    executor: ThreadPoolExecutor,
):
    (
        snapshot,
        cik,
        block_name,
        block_sha256,
        n_records,
        _min_filing_date,
        _max_filing_date,
        prior_classification,
    ) = target
    started = time.monotonic()
    con = duckdb.connect(str(database), read_only=True)
    try:
        samples = block_sample_records(con, snapshot, block_name, sample_count)
    finally:
        con.close()
    labels = []
    valid_sample_dates = []
    missing_sample_dates = []
    missing_acceptance_tags = 0
    new_requests = 0
    cached_requests = 0
    sample_rows = []

    fetched = list(
        executor.map(
            lambda sample: cached_or_fetch_without_write(
                database,
                cik,
                sample[1],
                user_agent,
                rate_limiter,
            ),
            samples,
        )
    )

    for (
        (_record_index, accession, filing_date, zip_text, zip_timestamp, position),
        observation,
    ) in zip(samples, fetched):
        sgml_value = observation["acceptance"]
        source = observation["source"]
        request_ms = observation["elapsed_ms"]
        error = observation["error"]
        if source == "network":
            new_requests += 1
        else:
            cached_requests += 1

        diff_min = None
        label = "unresolved"
        if sgml_value is not None:
            diff_min = int((parse_zip_datetime(zip_text) - sgml_value).total_seconds() / 60)
            label = interpretation(diff_min)
            labels.append(label)
            valid_sample_dates.append(filing_date)
        elif error and "ACCEPTANCE-DATETIME tag not found" in error:
            missing_acceptance_tags += 1
            missing_sample_dates.append(filing_date)

        sample_rows.append(
            [
                snapshot,
                cik,
                prior_classification,
                block_name,
                block_sha256,
                accession,
                position,
                zip_text,
                sgml_value,
                diff_min,
                label if error is None else "unresolved",
                source,
                datetime.now(timezone.utc),
            ]
        )
        print(
            f"  {block_name} {position}: {accession} -> "
            f"{diff_min} min ({label}), {source}, {request_ms:.0f} ms",
            flush=True,
        )
    classification = classify_labels(labels)
    elapsed_ms = (time.monotonic() - started) * 1000
    segment_boundary_date = min(valid_sample_dates) if valid_sample_dates else None
    missing_samples_precede_segment = (
        segment_boundary_date is not None
        and missing_sample_dates
        and max(missing_sample_dates) < segment_boundary_date
    )
    network_observations = [
        (accession, observation["result"])
        for (
            (_record_index, accession, _filing_date, _zip_text, _zip_timestamp, _position),
            observation,
        ) in zip(samples, fetched)
        if observation["source"] == "network"
    ]
    rule_kind = None
    required_evidence = min(min_evidence, n_records)
    if classification in {"eastern", "utc"}:
        if len(labels) >= required_evidence:
            rule_kind = "block"
        elif labels and missing_samples_precede_segment:
            rule_kind = "segment"
    print(
        f"  block result: {classification}; samples={len(samples)}, "
        f"new={new_requests}, cached={cached_requests}, "
        f"rule={rule_kind or 'no'} pending write; {elapsed_ms / 1000:.2f}s",
        flush=True,
    )
    return {
        "snapshot": snapshot,
        "cik": cik,
        "block_name": block_name,
        "block_sha256": block_sha256,
        "n_records": n_records,
        "n_samples": len(samples),
        "classification": classification,
        "labels_count": len(labels),
        "new_requests": new_requests,
        "cached_requests": cached_requests,
        "elapsed_ms": elapsed_ms,
        "sample_rows": sample_rows,
        "network_observations": network_observations,
        "segment_boundary_date": segment_boundary_date,
        "missing_samples_precede_segment": missing_samples_precede_segment,
        "rule_kind": rule_kind,
    }


def write_block_analysis(
    con: duckdb.DuckDBPyConnection,
    analysis: dict,
    min_evidence: int,
):
    for accession, result in analysis["network_observations"]:
        insert_sgml_observation(con, analysis["cik"], accession, result)
    con.executemany(
        """
        INSERT OR REPLACE INTO block_samples VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        analysis["sample_rows"],
    )
    con.execute(
        """
        INSERT OR REPLACE INTO block_classifications VALUES
          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            analysis["snapshot"],
            analysis["cik"],
            "sgml_anchor",
            analysis["block_name"],
            analysis["block_sha256"],
            analysis["n_records"],
            analysis["n_samples"],
            analysis["classification"],
            analysis["new_requests"],
            analysis["cached_requests"],
            analysis["elapsed_ms"],
            datetime.now(timezone.utc),
        ],
    )
    rule_created = write_block_rule(
        con,
        analysis["snapshot"],
        analysis["cik"],
        analysis["block_name"],
        analysis["block_sha256"],
        analysis["classification"],
        analysis["labels_count"],
        min_evidence,
        analysis["n_records"],
    )
    if (
        not rule_created
        and analysis["classification"] in {"eastern", "utc"}
        and analysis["missing_samples_precede_segment"]
        and analysis["labels_count"]
    ):
        rule_created = write_segment_rule(
            con,
            analysis["snapshot"],
            analysis["cik"],
            analysis["block_name"],
            analysis["block_sha256"],
            analysis["classification"],
            analysis["labels_count"],
            analysis["segment_boundary_date"],
        )
    return rule_created


def write_analysis_batch(
    database: Path,
    analyses: list[dict],
    min_evidence: int,
    lock_timeout: float,
):
    if not analyses:
        return 0
    deadline = time.monotonic() + lock_timeout
    attempt = 0
    last_error = None
    while True:
        attempt += 1
        try:
            con = duckdb.connect(str(database))
            try:
                rules = 0
                for analysis in analyses:
                    rules += int(write_block_analysis(con, analysis, min_evidence))
                con.commit()
                return rules
            finally:
                con.close()
        except duckdb.IOException as error:
            last_error = error
            if time.monotonic() >= deadline:
                raise
            sleep_seconds = min(5.0, 0.25 * attempt)
            print(
                f"  DuckDB write lock busy; retrying in {sleep_seconds:.2f}s",
                flush=True,
            )
            time.sleep(sleep_seconds)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--max-blocks", type=int, default=100)
    parser.add_argument(
        "--max-seconds",
        type=float,
        help="Stop after roughly this many wall-clock seconds, after finishing the current block.",
    )
    parser.add_argument("--samples-per-block", type=int, default=3)
    parser.add_argument("--min-evidence", type=int, default=3)
    parser.add_argument(
        "--classification",
        action="append",
        choices=["unresolved", "mixed", "anomalous"],
        help="Block classification to sample. May be passed more than once.",
    )
    parser.add_argument(
        "--order",
        choices=["size", "hash", "oldest", "newest"],
        default="size",
    )
    parser.add_argument("--request-delay", type=float, default=0.12)
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Number of concurrent SGML fetch workers. DuckDB writes remain single-threaded.",
    )
    parser.add_argument(
        "--write-batch-blocks",
        type=int,
        default=25,
        help="Number of processed blocks to accumulate before one DuckDB write burst.",
    )
    parser.add_argument(
        "--write-lock-timeout",
        type=float,
        default=300.0,
        help="Seconds to keep retrying a DuckDB write burst when another process holds the file.",
    )
    parser.add_argument(
        "--max-requests-per-second",
        type=float,
        help=(
            "Maximum SEC network fetch rate. Overrides --request-delay. "
            "Cache hits are not delayed."
        ),
    )
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    if args.samples_per_block < 1:
        parser.error("--samples-per-block must be at least 1")
    if args.max_blocks is not None and args.max_blocks < 1:
        parser.error("--max-blocks must be positive")
    if args.max_seconds is not None and args.max_seconds <= 0:
        parser.error("--max-seconds must be positive")
    if args.workers < 1:
        parser.error("--workers must be positive")
    if args.write_batch_blocks < 1:
        parser.error("--write-batch-blocks must be positive")
    if args.write_lock_timeout <= 0:
        parser.error("--write-lock-timeout must be positive")
    if args.max_requests_per_second is not None and args.max_requests_per_second <= 0:
        parser.error("--max-requests-per-second must be positive")

    network_delay = (
        1.0 / args.max_requests_per_second
        if args.max_requests_per_second is not None
        else args.request_delay
    )

    classifications = tuple(args.classification or ["unresolved"])
    con = duckdb.connect(str(args.database))
    try:
        initialize_database(con)
        initialize_inventory_schema(con)
        con.commit()
    finally:
        con.close()
    snapshot = snapshot_id(args.zip)
    con = duckdb.connect(str(args.database), read_only=True)
    try:
        inventory_rows = con.execute(
            "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
        ).fetchone()[0]
    finally:
        con.close()
    if inventory_rows == 0:
        raise RuntimeError(
            "No ZIP inventory found for this snapshot. Run "
            "scripts/build_acceptance_timestamp_rules.py first."
        )

    print(f"database: {args.database}")
    print(f"snapshot: {snapshot}")
    print(f"classifications: {', '.join(classifications)}")
    if network_delay > 0:
        print(f"network delay: {network_delay:.3f}s ({1 / network_delay:.2f} req/s max)")
    else:
        print("network delay: 0.000s (unlimited)")
    print(f"workers: {args.workers}")
    print(f"write batch: {args.write_batch_blocks} blocks")
    con = duckdb.connect(str(args.database), read_only=True)
    try:
        targets = choose_targets(
            con,
            snapshot,
            classifications,
            args.max_blocks,
            args.order,
        )
    finally:
        con.close()
    print(f"selected blocks: {len(targets):,}")

    total_new = 0
    total_cached = 0
    total_rules = 0
    processed_blocks = 0
    outcomes = {}
    started = time.monotonic()
    rate_limiter = NetworkRateLimiter(network_delay)
    pending_analyses = []
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for index, target in enumerate(targets, start=1):
            if args.max_seconds is not None and time.monotonic() - started >= args.max_seconds:
                print(
                    f"Reached --max-seconds after {index - 1:,} blocks; stopping.",
                    flush=True,
                )
                break
            _snapshot, cik, block_name, _hash, n_records, min_date, max_date, classification = target
            print(
                f"{index:,}/{len(targets):,} CIK {cik} {block_name} "
                f"[{classification}] n={n_records:,} dates={min_date}..{max_date}",
                flush=True,
            )
            analysis = collect_block_analysis(
                args.database,
                target,
                args.samples_per_block,
                args.min_evidence,
                args.user_agent,
                rate_limiter,
                executor,
            )
            processed_blocks += 1
            total_new += analysis["new_requests"]
            total_cached += analysis["cached_requests"]
            outcomes[analysis["classification"]] = outcomes.get(analysis["classification"], 0) + 1
            pending_analyses.append(analysis)
            if len(pending_analyses) >= args.write_batch_blocks:
                print(
                    f"Writing batch of {len(pending_analyses):,} blocks ...",
                    flush=True,
                )
                batch_rules = write_analysis_batch(
                    args.database,
                    pending_analyses,
                    args.min_evidence,
                    args.write_lock_timeout,
                )
                total_rules += batch_rules
                print(f"  wrote batch; rules={batch_rules:,}", flush=True)
                pending_analyses.clear()
        if pending_analyses:
            print(
                f"Writing final batch of {len(pending_analyses):,} blocks ...",
                flush=True,
            )
            batch_rules = write_analysis_batch(
                args.database,
                pending_analyses,
                args.min_evidence,
                args.write_lock_timeout,
            )
            total_rules += batch_rules
            print(f"  wrote final batch; rules={batch_rules:,}", flush=True)
            pending_analyses.clear()

    elapsed = time.monotonic() - started
    print(
        f"Summary: blocks={processed_blocks:,}, selected={len(targets):,}, "
        f"new={total_new:,}, "
        f"cached={total_cached:,}, rules={total_rules:,}, "
        f"wall_time={elapsed:.2f}s"
    )
    for outcome, count in sorted(outcomes.items()):
        print(f"  {outcome}: {count:,}")


if __name__ == "__main__":
    main()
