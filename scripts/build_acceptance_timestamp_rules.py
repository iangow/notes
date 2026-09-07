#!/usr/bin/env python3
"""Build block-level SEC acceptance timestamp rules from ZIP overlap evidence."""

import argparse
import csv
import hashlib
import json
import os
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database
from compare_filing_timestamp_sources import (
    DEFAULT_NEW_ZIP,
    DEFAULT_OLD,
    sql_string,
)


def snapshot_id(path: Path) -> str:
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def initialize_inventory_schema(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS zip_snapshots (
          snapshot_id VARCHAR PRIMARY KEY,
          zip_path VARCHAR NOT NULL,
          file_size BIGINT NOT NULL,
          mtime_ns BIGINT NOT NULL,
          inventoried_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
        );

        CREATE TABLE IF NOT EXISTS zip_blocks (
          snapshot_id VARCHAR NOT NULL,
          cik BIGINT NOT NULL,
          block_name VARCHAR NOT NULL,
          block_sha256 VARCHAR NOT NULL,
          n_records BIGINT NOT NULL,
          min_filing_date DATE,
          max_filing_date DATE,
          PRIMARY KEY (snapshot_id, block_name)
        );

        CREATE TABLE IF NOT EXISTS zip_filing_records (
          snapshot_id VARCHAR NOT NULL,
          cik BIGINT NOT NULL,
          block_name VARCHAR NOT NULL,
          block_sha256 VARCHAR NOT NULL,
          record_index BIGINT NOT NULL,
          accession_number VARCHAR NOT NULL,
          filing_date DATE,
          form VARCHAR,
          items VARCHAR,
          zip_acceptance_datetime_text VARCHAR,
          zip_acceptance_datetime TIMESTAMP,
          PRIMARY KEY (snapshot_id, block_name, record_index)
        );
        """
    )


def filing_data(data: dict) -> dict:
    return data.get("filings", {}).get("recent", data)


def row_count(records: dict) -> int:
    fields = [
        "accessionNumber",
        "filingDate",
        "acceptanceDateTime",
        "form",
        "items",
    ]
    return max((len(records.get(field, [])) for field in fields), default=0)


def value_at(records: dict, field: str, index: int):
    values = records.get(field, [])
    return values[index] if index < len(values) else None


def parse_zip_timestamp(value):
    if not value:
        return None
    return datetime.fromisoformat(value.removesuffix("Z"))


def write_inventory_csv(zip_path: Path, snapshot: str, records_csv: Path, blocks_csv: Path) -> None:
    started = time.monotonic()
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        primary = sorted(
            name
            for name in names
            if name.startswith("CIK")
            and name.endswith(".json")
            and "-submissions-" not in name
        )
        total_blocks = 0
        total_rows = 0
        with records_csv.open("w", newline="") as records_fh, blocks_csv.open(
            "w", newline=""
        ) as blocks_fh:
            records_writer = csv.writer(records_fh)
            blocks_writer = csv.writer(blocks_fh)
            records_writer.writerow(
                [
                    "snapshot_id",
                    "cik",
                    "block_name",
                    "block_sha256",
                    "record_index",
                    "accession_number",
                    "filing_date",
                    "form",
                    "items",
                    "zip_acceptance_datetime_text",
                    "zip_acceptance_datetime",
                ]
            )
            blocks_writer.writerow(
                [
                    "snapshot_id",
                    "cik",
                    "block_name",
                    "block_sha256",
                    "n_records",
                    "min_filing_date",
                    "max_filing_date",
                ]
            )

            for primary_index, base_name in enumerate(primary, start=1):
                base_data = json.loads(zf.read(base_name))
                cik = int(base_data.get("cik", 0) or 0)
                block_names = [base_name]
                block_names.extend(
                    ref["name"]
                    for ref in base_data.get("filings", {}).get("files", [])
                    if ref.get("name") in names
                )

                for block_name in block_names:
                    content = zf.read(block_name)
                    block_hash = hashlib.sha256(content).hexdigest()
                    block_data = base_data if block_name == base_name else json.loads(content)
                    records = filing_data(block_data)
                    n_rows = row_count(records)
                    filing_dates = []
                    for index in range(n_rows):
                        accession = value_at(records, "accessionNumber", index)
                        if not accession:
                            continue
                        filing_date = value_at(records, "filingDate", index)
                        if filing_date:
                            filing_dates.append(filing_date)
                        zip_text = value_at(records, "acceptanceDateTime", index)
                        zip_timestamp = parse_zip_timestamp(zip_text)
                        records_writer.writerow(
                            [
                                snapshot,
                                cik,
                                block_name,
                                block_hash,
                                index,
                                accession,
                                filing_date,
                                value_at(records, "form", index),
                                value_at(records, "items", index),
                                zip_text,
                                "" if zip_timestamp is None else zip_timestamp.isoformat(" "),
                            ]
                        )
                    blocks_writer.writerow(
                        [
                            snapshot,
                            cik,
                            block_name,
                            block_hash,
                            n_rows,
                            min(filing_dates) if filing_dates else None,
                            max(filing_dates) if filing_dates else None,
                        ]
                    )
                    total_blocks += 1
                    total_rows += n_rows

                if primary_index % 50_000 == 0:
                    elapsed = time.monotonic() - started
                    print(
                        f"  {primary_index:,} / {len(primary):,} CIK files; "
                        f"{total_blocks:,} blocks; {total_rows:,} rows; {elapsed:.0f}s",
                        flush=True,
                    )

        elapsed = time.monotonic() - started
        print(
            f"Inventory CSV complete: {total_blocks:,} blocks; "
            f"{total_rows:,} rows; {elapsed:.0f}s",
            flush=True,
        )


def load_inventory(
    con: duckdb.DuckDBPyConnection,
    zip_path: Path,
    snapshot: str,
    force: bool,
) -> None:
    existing = con.execute(
        "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
    ).fetchone()[0]
    if existing and not force:
        print(f"Inventory already exists for snapshot {snapshot}: {existing:,} rows")
        return

    con.execute("DELETE FROM zip_filing_records WHERE snapshot_id = ?", [snapshot])
    con.execute("DELETE FROM zip_blocks WHERE snapshot_id = ?", [snapshot])
    con.execute("DELETE FROM zip_snapshots WHERE snapshot_id = ?", [snapshot])

    with tempfile.TemporaryDirectory(prefix="sec-timestamp-inventory-") as tmp_dir:
        records_csv = Path(tmp_dir) / "zip_filing_records.csv"
        blocks_csv = Path(tmp_dir) / "zip_blocks.csv"
        write_inventory_csv(zip_path, snapshot, records_csv, blocks_csv)

        print("Loading inventory CSV into DuckDB ...", flush=True)
        con.execute(
            f"""
            INSERT INTO zip_blocks
            SELECT snapshot_id,
                   TRY_CAST(cik AS BIGINT),
                   block_name,
                   block_sha256,
                   TRY_CAST(n_records AS BIGINT),
                   TRY_CAST(min_filing_date AS DATE),
                   TRY_CAST(max_filing_date AS DATE)
            FROM read_csv({sql_string(blocks_csv)}, header = true, all_varchar = true)
            """
        )
        con.execute(
            f"""
            INSERT INTO zip_filing_records
            SELECT snapshot_id,
                   TRY_CAST(cik AS BIGINT),
                   block_name,
                   block_sha256,
                   TRY_CAST(record_index AS BIGINT),
                   accession_number,
                   TRY_CAST(filing_date AS DATE),
                   form,
                   items,
                   zip_acceptance_datetime_text,
                   TRY_CAST(zip_acceptance_datetime AS TIMESTAMP)
            FROM read_csv({sql_string(records_csv)}, header = true, all_varchar = true)
            """
        )

    stat = zip_path.stat()
    con.execute(
        """
        INSERT INTO zip_snapshots (
          snapshot_id,
          zip_path,
          file_size,
          mtime_ns,
          inventoried_at
        )
        SELECT ?, ?, ?, ?, ?
        ON CONFLICT (snapshot_id) DO UPDATE SET
          zip_path = excluded.zip_path,
          file_size = excluded.file_size,
          mtime_ns = excluded.mtime_ns,
          inventoried_at = excluded.inventoried_at
        """,
        [snapshot, str(zip_path), stat.st_size, stat.st_mtime_ns, datetime.now(timezone.utc)],
    )
    con.commit()
    rows = con.execute(
        "SELECT count(*) FROM zip_filing_records WHERE snapshot_id = ?", [snapshot]
    ).fetchone()[0]
    blocks = con.execute(
        "SELECT count(*) FROM zip_blocks WHERE snapshot_id = ?", [snapshot]
    ).fetchone()[0]
    print(f"Loaded inventory for {snapshot}: {blocks:,} blocks; {rows:,} rows")


def classify_overlap(
    con: duckdb.DuckDBPyConnection,
    old_path: Path,
    snapshot: str,
    min_evidence: int,
    evidence_per_rule: int,
) -> None:
    print("Classifying block overlap against trusted snapshot ...", flush=True)
    old_sql = sql_string(old_path)
    con.execute(
        f"""
        CREATE OR REPLACE TEMP TABLE overlap_evidence AS
        WITH old_rows AS (
          SELECT cik,
                 accessionNumber AS accession_number,
                 acceptanceDateTime AS trusted_acceptance_datetime,
                 row_number() OVER (
                   PARTITION BY cik, accessionNumber
                   ORDER BY filingDate, form, items, acceptanceDateTime
                 ) AS duplicate_index
          FROM read_parquet({old_sql})
          WHERE acceptanceDateTime IS NOT NULL
        ),
        zip_rows AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY cik, accession_number
                   ORDER BY filing_date, form, items, zip_acceptance_datetime
                 ) AS duplicate_index
          FROM zip_filing_records
          WHERE snapshot_id = ?
            AND zip_acceptance_datetime IS NOT NULL
        )
        SELECT z.snapshot_id,
               z.cik,
               z.block_name,
               z.block_sha256,
               z.record_index,
               z.accession_number,
               z.filing_date,
               z.zip_acceptance_datetime,
               o.trusted_acceptance_datetime,
               date_diff(
                 'minute',
                 o.trusted_acceptance_datetime,
                 z.zip_acceptance_datetime
               ) AS diff_min,
               CASE
                 WHEN date_diff('minute', o.trusted_acceptance_datetime,
                                z.zip_acceptance_datetime) = 0
                   THEN 'eastern'
                 WHEN date_diff('minute', o.trusted_acceptance_datetime,
                                z.zip_acceptance_datetime) IN (240, 300)
                   THEN 'utc'
                 ELSE 'anomalous'
               END AS interpretation
        FROM zip_rows AS z
        INNER JOIN old_rows AS o
          ON z.cik = o.cik
         AND z.accession_number = o.accession_number
         AND z.duplicate_index = o.duplicate_index
        """,
        [snapshot],
    )

    con.execute(
        """
        INSERT OR REPLACE INTO block_classifications
        SELECT b.snapshot_id,
               b.cik,
               CASE
                 WHEN count(e.accession_number) = 0 THEN 'no_overlap'
                 WHEN count(*) FILTER (WHERE e.interpretation = 'eastern') > 0
                  AND count(*) FILTER (WHERE e.interpretation = 'utc') > 0
                   THEN 'mixed_overlap'
                 WHEN count(*) FILTER (WHERE e.interpretation = 'eastern') > 0
                   THEN 'eastern_overlap'
                 WHEN count(*) FILTER (WHERE e.interpretation = 'utc') > 0
                   THEN 'utc_overlap'
                 ELSE 'anomalous_overlap'
               END AS stratum,
               b.block_name,
               b.block_sha256,
               b.n_records,
               count(e.accession_number) AS n_samples,
               CASE
                 WHEN count(e.accession_number) = 0 THEN 'unresolved'
                 WHEN count(*) FILTER (WHERE e.interpretation = 'anomalous') > 0
                   THEN 'anomalous'
                 WHEN count(DISTINCT e.interpretation) = 1
                   THEN min(e.interpretation)
                 ELSE 'mixed'
               END AS classification,
               0 AS new_requests,
               count(e.accession_number) AS cached_requests,
               0.0 AS elapsed_ms,
               current_timestamp AS classified_at
        FROM zip_blocks AS b
        LEFT JOIN overlap_evidence AS e
          ON b.snapshot_id = e.snapshot_id
         AND b.block_name = e.block_name
        WHERE b.snapshot_id = ?
        GROUP BY b.snapshot_id, b.cik, b.block_name, b.block_sha256, b.n_records
        """,
        [snapshot],
    )

    methods = ["overlap_block_uniform_v1", "overlap_cik_uniform_v1"]
    con.execute(
        """
        DELETE FROM rule_evidence
        WHERE rule_id IN (
          SELECT rule_id
          FROM timestamp_rules
          WHERE method IN (?, ?)
            AND snapshot_id = ?
        )
        """,
        [*methods, snapshot],
    )
    con.execute(
        """
        DELETE FROM timestamp_rules
        WHERE method IN (?, ?)
          AND snapshot_id = ?
        """,
        [*methods, snapshot],
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
          notes
        )
        SELECT 'block:' || snapshot_id || ':' || substr(block_sha256, 1, 16),
               'block',
               cik,
               snapshot_id,
               block_name,
               block_sha256,
               NULL,
               NULL,
               classification,
               n_samples,
               1.0,
               'verified',
               'overlap_block_uniform_v1',
               'Uniform block rule derived from trusted 2024 overlap.'
        FROM block_classifications
        WHERE snapshot_id = ?
          AND classification IN ('eastern', 'utc')
          AND n_samples >= ?
        """,
        [snapshot, min_evidence],
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
          notes
        )
        SELECT 'cik:' || snapshot_id || ':' || cik,
               'cik',
               cik,
               snapshot_id,
               NULL,
               NULL,
               NULL,
               NULL,
               min(interpretation),
               count(*),
               1.0,
               'verified',
               'overlap_cik_uniform_v1',
               'Uniform CIK rule derived from trusted 2024 overlap.'
        FROM overlap_evidence
        GROUP BY snapshot_id, cik
        HAVING count(*) >= ?
           AND count(*) FILTER (WHERE interpretation = 'anomalous') = 0
           AND count(DISTINCT interpretation) = 1
        """,
        [min_evidence],
    )
    con.execute(
        """
        INSERT INTO rule_evidence (
          rule_id,
          accession_number,
          evidence_role,
          observed_interpretation
        )
        SELECT rule_id,
               accession_number,
               CASE WHEN rn <= ? THEN 'training' ELSE 'validation' END,
               interpretation
        FROM (
          SELECT r.rule_id,
                 e.accession_number,
                 e.interpretation,
                 row_number() OVER (
                   PARTITION BY r.rule_id
                   ORDER BY hash(e.accession_number)
                 ) AS rn
          FROM timestamp_rules AS r
          INNER JOIN overlap_evidence AS e
            ON r.snapshot_id = e.snapshot_id
           AND r.cik = e.cik
           AND (r.block_name IS NULL OR r.block_name = e.block_name)
          WHERE r.method IN ('overlap_block_uniform_v1', 'overlap_cik_uniform_v1')
            AND r.snapshot_id = ?
            AND e.interpretation = r.interpretation
        )
        WHERE rn <= ?
        """,
        [max(1, evidence_per_rule // 2), snapshot, evidence_per_rule],
    )
    con.commit()

    totals = con.execute(
        """
        SELECT classification, count(*) AS blocks, sum(n_samples) AS evidence_rows
        FROM block_classifications
        WHERE snapshot_id = ?
        GROUP BY classification
        ORDER BY classification
        """,
        [snapshot],
    ).fetchall()
    rules = con.execute(
        """
        SELECT count(*) FROM timestamp_rules
        WHERE method IN ('overlap_block_uniform_v1', 'overlap_cik_uniform_v1')
          AND snapshot_id = ?
        """,
        [snapshot],
    ).fetchone()[0]
    rule_methods = con.execute(
        """
        SELECT method, interpretation, count(*)
        FROM timestamp_rules
        WHERE method IN ('overlap_block_uniform_v1', 'overlap_cik_uniform_v1')
          AND snapshot_id = ?
        GROUP BY method, interpretation
        ORDER BY method, interpretation
        """,
        [snapshot],
    ).fetchall()
    print("Block classifications:")
    for classification, blocks, evidence_rows in totals:
        print(f"  {classification}: {blocks:,} blocks; {evidence_rows or 0:,} evidence rows")
    print(f"Created {rules:,} verified rules")
    for method, interpretation, count in rule_methods:
        print(f"  {method} {interpretation}: {count:,}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--force-inventory", action="store_true")
    parser.add_argument("--inventory-only", action="store_true")
    parser.add_argument("--classify-only", action="store_true")
    parser.add_argument("--min-evidence", type=int, default=3)
    parser.add_argument("--evidence-per-rule", type=int, default=20)
    args = parser.parse_args()

    if args.inventory_only and args.classify_only:
        parser.error("--inventory-only and --classify-only are mutually exclusive")

    args.database.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.database))
    initialize_database(con)
    initialize_inventory_schema(con)
    snapshot = snapshot_id(args.zip)
    print(f"database: {args.database}")
    print(f"zip: {args.zip}")
    print(f"snapshot: {snapshot}")

    if not args.classify_only:
        load_inventory(con, args.zip, snapshot, args.force_inventory)
    if not args.inventory_only:
        classify_overlap(
            con,
            args.old,
            snapshot,
            args.min_evidence,
            args.evidence_per_rule,
        )
    con.close()


if __name__ == "__main__":
    main()
