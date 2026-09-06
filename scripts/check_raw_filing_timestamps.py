#!/usr/bin/env python3
"""
Compare affected filing timestamps with raw SEC submissions.zip records.

The focus is on rows where the current Parquet timestamp differs from the
backup Parquet timestamp by 240 or 300 minutes.
"""

import argparse
import json
import zipfile
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import (
    DEFAULT_NEW,
    DEFAULT_OLD,
    DEFAULT_OLD_ZIP,
)

DEFAULT_ZIP = DEFAULT_OLD_ZIP


def sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def affected_sample(old_path: Path, new_path: Path, limit: int):
    con = duckdb.connect()
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'America/New_York'")
    rows = con.execute(
        f"""
        WITH old_filings AS (
          SELECT cik, accessionNumber, filingDate, form,
                 acceptanceDateTime AS old_acceptanceDateTime
          FROM read_parquet({sql_string(old_path)})
        ),
        new_filings AS (
          SELECT cik, accessionNumber, filingDate, form,
                 acceptanceDateTime AS new_acceptanceDateTime
          FROM read_parquet({sql_string(new_path)})
        ),
        common AS (
          SELECT n.cik,
                 n.accessionNumber,
                 coalesce(n.filingDate, o.filingDate) AS filingDate,
                 coalesce(n.form, o.form) AS form,
                 o.old_acceptanceDateTime,
                 n.new_acceptanceDateTime,
                 date_diff(
                   'minute',
                   o.old_acceptanceDateTime,
                   n.new_acceptanceDateTime
                 ) AS diff_min
          FROM new_filings AS n
          INNER JOIN old_filings AS o USING (cik, accessionNumber)
          WHERE year(o.old_acceptanceDateTime) >= 2003
        )
        SELECT *
        FROM common
        WHERE diff_min IN (240, 300)
        ORDER BY diff_min, old_acceptanceDateTime
        LIMIT {limit}
        """
    ).fetchall()
    cols = [desc[0] for desc in con.description]
    con.close()
    return [dict(zip(cols, row)) for row in rows]


def raw_record(zf: zipfile.ZipFile, cik: int, accession_number: str):
    names = set(zf.namelist())
    base = f"CIK{cik:010d}.json"
    if base not in names:
        return None

    base_data = json.loads(zf.read(base))
    filing_files = [base]
    filing_files.extend(
        ref["name"]
        for ref in base_data.get("filings", {}).get("files", [])
        if ref.get("name")
    )

    for name in filing_files:
        if name not in names:
            continue
        data = json.loads(zf.read(name))
        recent = data.get("filings", {}).get("recent", data)
        accessions = recent.get("accessionNumber", [])
        try:
            idx = accessions.index(accession_number)
        except ValueError:
            continue

        return {
            "json_file": name,
            "raw_acceptanceDateTime": recent.get("acceptanceDateTime", [])[idx],
            "raw_filingDate": recent.get("filingDate", [])[idx],
            "raw_form": recent.get("form", [])[idx],
            "raw_items": recent.get("items", [""])[idx],
        }

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--zip", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()

    sample = affected_sample(args.old, args.new, args.limit)

    print(f"old: {args.old}")
    print(f"new: {args.new}")
    print(f"zip: {args.zip}")
    print()

    with zipfile.ZipFile(args.zip) as zf:
        for row in sample:
            raw = raw_record(zf, row["cik"], row["accessionNumber"]) or {}
            print(
                "\t".join(
                    str(x)
                    for x in [
                        row["diff_min"],
                        row["cik"],
                        row["accessionNumber"],
                        row["form"],
                        row["old_acceptanceDateTime"],
                        row["new_acceptanceDateTime"],
                        raw.get("raw_acceptanceDateTime", "<not found>"),
                        raw.get("json_file", ""),
                    ]
                )
            )


if __name__ == "__main__":
    main()
