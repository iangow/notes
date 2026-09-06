#!/usr/bin/env python3
"""Compare filing timestamps across Parquet, submissions ZIPs, and EDGAR archives."""

import argparse
import gzip
import json
import os
import re
import time
import urllib.request
import zipfile
import zlib
from pathlib import Path

import duckdb


REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = Path(
    os.environ.get("DATA_DIR", Path.home() / "Dropbox" / "pq_data")
).expanduser()
RAW_DATA_DIR = Path(
    os.environ.get("RAW_DATA_DIR", DATA_DIR.parent / "raw_data")
).expanduser()
DEFAULT_OLD = Path(
    os.environ.get(
        "OLD_FILINGS_PATH",
        DATA_DIR
        / "submissions"
        / "filings.parquet.bak-20260906-105247",
    )
)
DEFAULT_BAD_TIMELINE = DATA_DIR / "edgar" / "filings.parquet.bak-20260906-bad-timeline"
DEFAULT_NEW = Path(
    os.environ.get(
        "NEW_FILINGS_PATH",
        DEFAULT_BAD_TIMELINE
        if DEFAULT_BAD_TIMELINE.exists()
        else DATA_DIR / "edgar" / "filings.parquet",
    )
)
DEFAULT_OLD_ZIP = Path(
    os.environ.get("OLD_SUBMISSIONS_ZIP", REPO_ROOT / "data" / "submissions.zip")
)
DEFAULT_NEW_ZIP = Path(
    os.environ.get(
        "NEW_SUBMISSIONS_ZIP",
        RAW_DATA_DIR / "submissions" / "submissions.zip",
    )
)
DEFAULT_USER_AGENT = os.environ.get(
    "SEC_USER_AGENT", "EDGAR timestamp research ian.gow@unimelb.edu.au"
)


def sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


def stratified_sample(old_path: Path, new_path: Path, per_group: int):
    con = duckdb.connect()
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'America/New_York'")
    rows = con.execute(
        f"""
        WITH old_filings AS (
          SELECT cik, accessionNumber,
                 acceptanceDateTime AS old_acceptanceDateTime
          FROM read_parquet({sql_string(old_path)})
        ),
        new_filings AS (
          SELECT cik, accessionNumber, form,
                 acceptanceDateTime AS new_acceptanceDateTime
          FROM read_parquet({sql_string(new_path)})
        ),
        common AS (
          SELECT n.cik,
                 n.accessionNumber,
                 n.form,
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
        ),
        numbered AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY diff_min
                   ORDER BY old_acceptanceDateTime, cik, accessionNumber
                 ) AS rn,
                 count(*) OVER (PARTITION BY diff_min) AS group_n
          FROM common
          WHERE diff_min IN (0, 240, 300)
        ),
        targets AS (
          SELECT diff_min,
                 i,
                 1 + round(i * (max(group_n) - 1.0) / ({per_group} - 1))::BIGINT
                   AS target_rn
          FROM numbered
          CROSS JOIN range({per_group}) AS sample_points(i)
          GROUP BY diff_min, i
        )
        SELECT n.* EXCLUDE (rn, group_n)
        FROM numbered AS n
        INNER JOIN targets AS t
          ON n.diff_min = t.diff_min AND n.rn = t.target_rn
        ORDER BY n.diff_min, n.old_acceptanceDateTime
        """
    ).fetchall()
    columns = [item[0] for item in con.description]
    con.close()
    return [dict(zip(columns, row)) for row in rows]


class SubmissionsZip:
    def __init__(self, path: Path):
        self.zf = zipfile.ZipFile(path)
        self.names = set(self.zf.namelist())
        self.base_cache = {}
        self.recent_accession_cache = {}

    def close(self):
        self.zf.close()

    def recent_accessions(self, cik: int):
        if cik in self.recent_accession_cache:
            return self.recent_accession_cache[cik]
        base_name = f"CIK{cik:010d}.json"
        if base_name not in self.names:
            return set()
        if base_name not in self.base_cache:
            self.base_cache[base_name] = json.loads(self.zf.read(base_name))
        recent = self.base_cache[base_name].get("filings", {}).get("recent", {})
        accessions = set(recent.get("accessionNumber", []))
        self.recent_accession_cache[cik] = accessions
        return accessions

    def acceptance_datetime(self, cik: int, accession_number: str):
        record = self.record(cik, accession_number)
        return None if record is None else record["acceptance_datetime"]

    def record(self, cik: int, accession_number: str):
        base_name = f"CIK{cik:010d}.json"
        if base_name not in self.names:
            return None

        if base_name not in self.base_cache:
            self.base_cache[base_name] = json.loads(self.zf.read(base_name))
        base_data = self.base_cache[base_name]
        filing_files = [base_name] + [
            ref["name"]
            for ref in base_data.get("filings", {}).get("files", [])
            if ref.get("name")
        ]

        for name in filing_files:
            if name not in self.names:
                continue
            data = base_data if name == base_name else json.loads(self.zf.read(name))
            recent = data.get("filings", {}).get("recent", data)
            try:
                index = recent.get("accessionNumber", []).index(accession_number)
            except ValueError:
                continue
            return {
                "acceptance_datetime": recent.get("acceptanceDateTime", [])[index],
                "json_file": name,
                "json_section": "recent" if name == base_name else "historical",
            }
        return None


def archive_acceptance_datetime(cik: int, accession: str, user_agent: str):
    accession_compact = accession.replace("-", "")
    url = (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{accession_compact}/{accession}.hdr.sgml"
    )
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
            encoding = response.headers.get("Content-Encoding", "").lower()
            if encoding == "gzip":
                content = gzip.decompress(content)
            elif encoding == "deflate":
                content = zlib.decompress(content)
            text = content.decode("latin-1")
    except Exception as exc:  # Keep the rest of a sample usable after one failure.
        return None, f"{type(exc).__name__}: {exc}", url

    match = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", text)
    if not match:
        return None, "tag not found", url
    value = match.group(1)
    formatted = (
        f"{value[0:4]}-{value[4:6]}-{value[6:8]}T"
        f"{value[8:10]}:{value[10:12]}:{value[12:14]}"
    )
    return formatted, None, url


def format_parquet_datetime(value):
    return value.strftime("%Y-%m-%dT%H:%M:%S")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--old-zip", type=Path, default=DEFAULT_OLD_ZIP)
    parser.add_argument("--new-zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--per-group", type=int, default=4)
    parser.add_argument(
        "--user-agent",
        default=os.environ.get("SEC_USER_AGENT", DEFAULT_USER_AGENT),
    )
    args = parser.parse_args()
    if args.per_group < 2:
        parser.error("--per-group must be at least 2")

    sample = stratified_sample(args.old, args.new, args.per_group)
    old_zip = SubmissionsZip(args.old_zip)
    new_zip = SubmissionsZip(args.new_zip)

    columns = [
        "diff_min",
        "cik",
        "accession",
        "form",
        "old_parquet",
        "new_parquet",
        "old_zip",
        "new_zip",
        "archive",
        "archive_error",
    ]
    print("\t".join(columns))
    try:
        for row in sample:
            archive_value, error, _ = archive_acceptance_datetime(
                row["cik"], row["accessionNumber"], args.user_agent
            )
            values = [
                row["diff_min"],
                row["cik"],
                row["accessionNumber"],
                row["form"],
                format_parquet_datetime(row["old_acceptanceDateTime"]),
                format_parquet_datetime(row["new_acceptanceDateTime"]),
                old_zip.acceptance_datetime(row["cik"], row["accessionNumber"]),
                new_zip.acceptance_datetime(row["cik"], row["accessionNumber"]),
                archive_value,
                error,
            ]
            print("\t".join("" if value is None else str(value) for value in values))
            time.sleep(0.12)
    finally:
        old_zip.close()
        new_zip.close()


if __name__ == "__main__":
    main()
