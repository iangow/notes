#!/usr/bin/env python3
"""Compare post-2024-snapshot submissions timestamps with archival SGML."""

import argparse
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import (
    DEFAULT_NEW,
    DEFAULT_NEW_ZIP,
    DEFAULT_OLD,
    DEFAULT_OLD_ZIP,
    DEFAULT_USER_AGENT,
    SubmissionsZip,
    archive_acceptance_datetime,
    sql_string,
)


def sample_after_snapshot(old_path: Path, new_path: Path, per_stratum: int):
    con = duckdb.connect()
    rows = con.execute(
        f"""
        WITH cutoff AS (
          SELECT max(filingDate) AS cutoff_date
          FROM read_parquet({sql_string(old_path)})
        ),
        candidates AS (
          SELECT n.cik,
                 n.accessionNumber,
                 n.form,
                 n.filingDate,
                 date_trunc('quarter', n.filingDate)::DATE AS quarter,
                 CASE
                   WHEN n.form IN ('3', '3/A', '4', '4/A', '5', '5/A')
                     THEN 'ownership'
                   ELSE 'other'
                 END AS form_group
          FROM read_parquet({sql_string(new_path)}) AS n
          CROSS JOIN cutoff
          WHERE n.filingDate > cutoff.cutoff_date
            AND n.acceptanceDateTime IS NOT NULL
        ),
        numbered AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY quarter, form_group
                   ORDER BY hash(cik, accessionNumber)
                 ) AS rn
          FROM candidates
        )
        SELECT * EXCLUDE rn
        FROM numbered
        WHERE rn <= {per_stratum}
        ORDER BY quarter, form_group, accessionNumber
        """
    ).fetchall()
    columns = [item[0] for item in con.description]
    cutoff = con.execute(
        f"SELECT max(filingDate) FROM read_parquet({sql_string(old_path)})"
    ).fetchone()[0]
    con.close()
    return cutoff, [dict(zip(columns, row)) for row in rows]


def parse_zip_datetime(value):
    if value is None:
        return None
    return datetime.fromisoformat(value.removesuffix("Z"))


def parse_archive_datetime(value):
    if value is None:
        return None
    return datetime.fromisoformat(value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--old-zip", type=Path, default=DEFAULT_OLD_ZIP)
    parser.add_argument("--new-zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--per-stratum", type=int, default=2)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()

    cutoff, sample = sample_after_snapshot(args.old, args.new, args.per_stratum)
    old_zip = SubmissionsZip(args.old_zip)
    new_zip = SubmissionsZip(args.new_zip)
    total_diffs = Counter()
    quarter_diffs = Counter()
    form_group_diffs = Counter()
    json_section_diffs = Counter()

    print(f"2024 snapshot final filing date: {cutoff}")
    print(
        "\t".join(
            [
                "quarter",
                "form_group",
                "form",
                "cik",
                "accession",
                "in_2024_zip",
                "2026_zip",
                "2026_json_section",
                "2026_json_file",
                "archive_sgml",
                "zip_minus_sgml_min",
                "archive_error",
            ]
        )
    )
    try:
        for row in sample:
            accession = row["accessionNumber"]
            old_value = old_zip.acceptance_datetime(row["cik"], accession)
            new_record = new_zip.record(row["cik"], accession)
            new_value = (
                None if new_record is None else new_record["acceptance_datetime"]
            )
            archive_value, error, _ = archive_acceptance_datetime(
                row["cik"], accession, args.user_agent
            )
            zip_datetime = parse_zip_datetime(new_value)
            archive_datetime = parse_archive_datetime(archive_value)
            diff_min = None
            if zip_datetime is not None and archive_datetime is not None:
                diff_min = int(
                    (zip_datetime - archive_datetime).total_seconds() / 60
                )
                quarter = str(row["quarter"])
                total_diffs[diff_min] += 1
                quarter_diffs[(quarter, diff_min)] += 1
                form_group_diffs[(row["form_group"], diff_min)] += 1
                json_section_diffs[(new_record["json_section"], diff_min)] += 1

            values = [
                row["quarter"],
                row["form_group"],
                row["form"],
                row["cik"],
                accession,
                old_value is not None,
                new_value,
                None if new_record is None else new_record["json_section"],
                None if new_record is None else new_record["json_file"],
                archive_value,
                diff_min,
                error,
            ]
            print("\t".join("" if value is None else str(value) for value in values))
            time.sleep(0.12)
    finally:
        old_zip.close()
        new_zip.close()

    print("\nOverall")
    for diff_min, count in sorted(total_diffs.items()):
        print(f"{diff_min:>5} minutes: {count}")

    print("\nBy quarter")
    for (quarter, diff_min), count in sorted(quarter_diffs.items()):
        print(f"{quarter}\t{diff_min:>5}\t{count}")

    print("\nBy form group")
    for (form_group, diff_min), count in sorted(form_group_diffs.items()):
        print(f"{form_group}\t{diff_min:>5}\t{count}")

    print("\nBy JSON section")
    for (json_section, diff_min), count in sorted(json_section_diffs.items()):
        print(f"{json_section}\t{diff_min:>5}\t{count}")


if __name__ == "__main__":
    main()
