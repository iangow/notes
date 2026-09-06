#!/usr/bin/env python3
"""Focused checks for acceptance timestamp rule precedence."""

from datetime import date, datetime

import duckdb

from acceptance_timestamp_db import initialize_database


def resolve(con, accession, block, filing_date, zip_datetime, cik=1):
    return con.execute(
        """
        SELECT corrected_acceptance_datetime,
               interpretation,
               provenance,
               reference_id
        FROM resolve_acceptance_timestamp(?, ?, ?, ?, ?, ?, ?)
        """,
        [
            cik,
            accession,
            "snapshot-1",
            block,
            "hash-1",
            filing_date,
            zip_datetime,
        ],
    ).fetchone()


def main():
    con = duckdb.connect()
    initialize_database(con)
    con.executemany(
        """
        INSERT INTO timestamp_rules (
          rule_id, rule_level, cik, block_name,
          valid_from_date, valid_to_date, interpretation,
          evidence_count, confidence, status, method
        ) VALUES (?, ?, 1, ?, ?, ?, ?, 3, 1.0, 'verified', 'test')
        """,
        [
            ["cik-1", "cik", None, None, None, "utc"],
            ["block-1", "block", "block-a", None, None, "eastern"],
            [
                "segment-1",
                "segment",
                "block-a",
                date(2025, 1, 1),
                date(2025, 12, 31),
                "utc",
            ],
        ],
    )
    con.execute(
        """
        INSERT INTO submission_overrides (
          accession_number, cik, zip_acceptance_datetime,
          corrected_acceptance_datetime, interpretation,
          evidence_source, reason
        ) VALUES (
          'override-accession', 1, TIMESTAMP '2025-06-01 20:00:00',
          TIMESTAMP '2025-06-01 12:34:56', 'anomalous', 'sgml',
          'test override'
        )
        """
    )

    assert resolve(
        con,
        "cik-accession",
        "other-block",
        date(2026, 1, 15),
        datetime(2026, 1, 15, 20),
    ) == (datetime(2026, 1, 15, 15), "utc", "cik_rule", "cik-1")
    assert resolve(
        con,
        "block-accession",
        "block-a",
        date(2024, 6, 1),
        datetime(2024, 6, 1, 20),
    ) == (
        datetime(2024, 6, 1, 20),
        "eastern",
        "block_rule",
        "block-1",
    )
    assert resolve(
        con,
        "segment-accession",
        "block-a",
        date(2025, 6, 1),
        datetime(2025, 6, 1, 20),
    ) == (
        datetime(2025, 6, 1, 16),
        "utc",
        "segment_rule",
        "segment-1",
    )
    assert resolve(
        con,
        "override-accession",
        "block-a",
        date(2025, 6, 1),
        datetime(2025, 6, 1, 20),
    ) == (
        datetime(2025, 6, 1, 12, 34, 56),
        "anomalous",
        "submission_override",
        "override-accession",
    )
    assert resolve(
        con,
        "unknown",
        "unknown-block",
        date(2026, 1, 15),
        datetime(2026, 1, 15, 20),
        cik=2,
    ) == (None, "unresolved", "unresolved", None)
    con.close()
    print("acceptance timestamp database tests passed")


if __name__ == "__main__":
    main()
