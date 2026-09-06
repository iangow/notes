#!/usr/bin/env python3
"""Test whether post-snapshot timestamp treatment is constant within CIK."""

import argparse
import time
from collections import Counter
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import (
    DEFAULT_NEW,
    DEFAULT_NEW_ZIP,
    DEFAULT_OLD,
    DEFAULT_USER_AGENT,
    SubmissionsZip,
    archive_acceptance_datetime,
    sql_string,
)
from sample_new_filing_timestamp_sources import (
    parse_archive_datetime,
    parse_zip_datetime,
)


def sample_mixed_ciks(
    old_path: Path,
    new_path: Path,
    cik_count: int,
    per_cik: int,
):
    con = duckdb.connect()
    rows = con.execute(
        f"""
        WITH old_filings AS (
          SELECT cik, accessionNumber, filingDate,
                 acceptanceDateTime AS old_acceptanceDateTime
          FROM read_parquet({sql_string(old_path)})
        ),
        new_filings AS (
          SELECT cik, accessionNumber, filingDate, form,
                 acceptanceDateTime AS new_acceptanceDateTime
          FROM read_parquet({sql_string(new_path)})
        ),
        cutoff AS (
          SELECT max(filingDate) AS cutoff_date FROM old_filings
        ),
        common AS (
          SELECT n.cik,
                 date_diff(
                   'minute',
                   o.old_acceptanceDateTime,
                   n.new_acceptanceDateTime
                 ) AS diff_min
          FROM new_filings AS n
          INNER JOIN old_filings AS o USING (cik, accessionNumber)
          WHERE year(o.old_acceptanceDateTime) >= 2003
        ),
        historically_mixed AS (
          SELECT cik
          FROM common
          WHERE diff_min IN (0, 240, 300)
          GROUP BY cik
          HAVING count(DISTINCT diff_min = 0) = 2
        ),
        post_snapshot AS (
          SELECT n.*
          FROM new_filings AS n
          INNER JOIN historically_mixed USING (cik)
          CROSS JOIN cutoff
          WHERE n.filingDate > cutoff.cutoff_date
            AND n.new_acceptanceDateTime IS NOT NULL
        ),
        selected_ciks AS (
          SELECT cik, count(*) AS post_snapshot_n
          FROM post_snapshot
          GROUP BY cik
          ORDER BY post_snapshot_n DESC, cik
          LIMIT {cik_count}
        ),
        numbered AS (
          SELECT p.*,
                 s.post_snapshot_n,
                 row_number() OVER (
                   PARTITION BY p.cik
                   ORDER BY p.filingDate, p.accessionNumber
                 ) AS rn
          FROM post_snapshot AS p
          INNER JOIN selected_ciks AS s USING (cik)
        ),
        targets AS (
          SELECT cik,
                 i,
                 1 + round(i * (max(post_snapshot_n) - 1.0) /
                           ({per_cik} - 1))::BIGINT AS target_rn
          FROM numbered
          CROSS JOIN range({per_cik}) AS sample_points(i)
          GROUP BY cik, i
        )
        SELECT n.* EXCLUDE (post_snapshot_n, rn)
        FROM numbered AS n
        INNER JOIN targets AS t
          ON n.cik = t.cik AND n.rn = t.target_rn
        ORDER BY n.cik, n.filingDate, n.accessionNumber
        """
    ).fetchall()
    columns = [item[0] for item in con.description]
    con.close()
    return [dict(zip(columns, row)) for row in rows]


def historically_mixed_rows(old_path: Path, new_path: Path):
    con = duckdb.connect()
    rows = con.execute(
        f"""
        WITH old_filings AS (
          SELECT cik, accessionNumber,
                 acceptanceDateTime AS old_acceptanceDateTime
          FROM read_parquet({sql_string(old_path)})
        ),
        new_filings AS (
          SELECT cik, accessionNumber,
                 acceptanceDateTime AS new_acceptanceDateTime
          FROM read_parquet({sql_string(new_path)})
        ),
        common AS (
          SELECT n.cik,
                 n.accessionNumber,
                 date_diff(
                   'minute',
                   o.old_acceptanceDateTime,
                   n.new_acceptanceDateTime
                 ) AS diff_min
          FROM new_filings AS n
          INNER JOIN old_filings AS o USING (cik, accessionNumber)
          WHERE year(o.old_acceptanceDateTime) >= 2003
        ),
        mixed_ciks AS (
          SELECT cik
          FROM common
          WHERE diff_min IN (0, 240, 300)
          GROUP BY cik
          HAVING count(DISTINCT diff_min = 0) = 2
        )
        SELECT c.cik, c.accessionNumber, c.diff_min
        FROM common AS c
        INNER JOIN mixed_ciks USING (cik)
        WHERE c.diff_min IN (0, 240, 300)
        """
    ).fetchall()
    con.close()
    return rows


def summarize_current_recent(rows, new_zip: SubmissionsZip):
    by_cik = {}
    for cik, accession, diff_min in rows:
        if cik not in by_cik:
            by_cik[cik] = Counter()
        if accession in new_zip.recent_accessions(cik):
            state = "unchanged" if diff_min == 0 else "utc_converted"
            by_cik[cik][state] += 1

    comparable = {
        cik: counts for cik, counts in by_cik.items() if sum(counts.values()) >= 2
    }
    mixed = {
        cik: counts
        for cik, counts in comparable.items()
        if len(counts) == 2
    }
    return comparable, mixed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--new-zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--cik-count", type=int, default=6)
    parser.add_argument("--per-cik", type=int, default=5)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()
    if args.per_cik < 2:
        parser.error("--per-cik must be at least 2")

    sample = sample_mixed_ciks(
        args.old, args.new, args.cik_count, args.per_cik
    )
    new_zip = SubmissionsZip(args.new_zip)
    cik_diffs = Counter()

    mixed_rows = historically_mixed_rows(args.old, args.new)
    comparable_recent, mixed_recent = summarize_current_recent(
        mixed_rows, new_zip
    )
    print("Overlap evidence for historically mixed CIKs")
    print(f"CIKs with comparable rows in current recent block: {len(comparable_recent)}")
    print(f"CIKs still mixed inside current recent block: {len(mixed_recent)}")
    for cik, counts in sorted(
        mixed_recent.items(), key=lambda item: -sum(item[1].values())
    )[:10]:
        print(
            f"  {cik}: unchanged={counts['unchanged']}, "
            f"utc_converted={counts['utc_converted']}"
        )
    print()

    print(
        "\t".join(
            [
                "cik",
                "filing_date",
                "form",
                "accession",
                "json_section",
                "2026_zip",
                "archive_sgml",
                "zip_minus_sgml_min",
                "archive_error",
            ]
        )
    )
    try:
        for row in sample:
            accession = row["accessionNumber"]
            record = new_zip.record(row["cik"], accession)
            zip_value = None if record is None else record["acceptance_datetime"]
            archive_value, error, _ = archive_acceptance_datetime(
                row["cik"], accession, args.user_agent
            )
            zip_datetime = parse_zip_datetime(zip_value)
            archive_datetime = parse_archive_datetime(archive_value)
            diff_min = None
            if zip_datetime is not None and archive_datetime is not None:
                diff_min = int(
                    (zip_datetime - archive_datetime).total_seconds() / 60
                )
                cik_diffs[(row["cik"], diff_min)] += 1

            values = [
                row["cik"],
                row["filingDate"],
                row["form"],
                accession,
                None if record is None else record["json_section"],
                zip_value,
                archive_value,
                diff_min,
                error,
            ]
            print("\t".join("" if value is None else str(value) for value in values))
            time.sleep(0.12)
    finally:
        new_zip.close()

    print("\nBy CIK")
    ciks = sorted({cik for cik, _ in cik_diffs})
    for cik in ciks:
        counts = sorted(
            (diff_min, cik_diffs[(cik, diff_min)])
            for candidate_cik, diff_min in cik_diffs
            if candidate_cik == cik
        )
        summary = ", ".join(f"{diff}: {count}" for diff, count in counts)
        print(f"{cik}\t{summary}")


if __name__ == "__main__":
    main()
