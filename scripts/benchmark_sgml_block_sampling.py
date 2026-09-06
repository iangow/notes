#!/usr/bin/env python3
"""Benchmark SGML sampling and persist block classifications in DuckDB."""

import argparse
import gzip
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import zipfile
import zlib
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB, initialize_database

from compare_filing_timestamp_sources import (
    DEFAULT_NEW,
    DEFAULT_NEW_ZIP,
    DEFAULT_OLD,
    DEFAULT_USER_AGENT,
    sql_string,
)

def cik_candidates(old_path: Path, new_path: Path, candidates_per_stratum=100):
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
        diffs AS (
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
        by_cik AS (
          SELECT cik,
                 count(*) AS n,
                 count(*) FILTER (WHERE diff_min = 0) AS n_unchanged,
                 count(*) FILTER (WHERE diff_min IN (240, 300)) AS n_shifted
          FROM diffs
          WHERE diff_min IN (0, 240, 300)
          GROUP BY cik
        ),
        classified AS (
          SELECT *,
                 CASE
                   WHEN n_unchanged > 0 AND n_shifted > 0 THEN 'mixed'
                   WHEN n_unchanged > 0 THEN 'unchanged'
                   ELSE 'utc_converted'
                 END AS stratum
          FROM by_cik
          WHERE n >= 20
        ),
        numbered AS (
          SELECT *,
                 row_number() OVER (
                   PARTITION BY stratum ORDER BY hash(cik)
                 ) AS rn
          FROM classified
        )
        SELECT cik, stratum, n, n_unchanged, n_shifted
        FROM numbered
        WHERE rn <= {candidates_per_stratum}
        ORDER BY stratum, rn
        """
    ).fetchall()
    con.close()
    return rows


def filing_data(data):
    return data.get("filings", {}).get("recent", data)


def block_names(zf: zipfile.ZipFile, names: set[str], cik: int):
    base_name = f"CIK{cik:010d}.json"
    if base_name not in names:
        return []
    base = json.loads(zf.read(base_name))
    result = [base_name]
    result.extend(
        item["name"]
        for item in base.get("filings", {}).get("files", [])
        if item.get("name") in names
    )
    return result


def choose_ciks(zf, names, candidates, per_stratum, max_blocks):
    selected = []
    counts = {"unchanged": 0, "utc_converted": 0, "mixed": 0}
    for cik, stratum, n, n_unchanged, n_shifted in candidates:
        if counts[stratum] >= per_stratum:
            continue
        blocks = block_names(zf, names, cik)
        if not blocks or len(blocks) > max_blocks:
            continue
        if stratum == "mixed" and len(blocks) < 2:
            continue
        selected.append((cik, stratum, blocks, n, n_unchanged, n_shifted))
        counts[stratum] += 1
    missing = [key for key, value in counts.items() if value < per_stratum]
    if missing:
        raise RuntimeError(f"could not select enough CIKs for: {', '.join(missing)}")
    return selected


def block_samples(data, sample_count, since=None):
    records = filing_data(data)
    accessions = records.get("accessionNumber", [])
    acceptances = records.get("acceptanceDateTime", [])
    filing_dates = records.get("filingDate", [])
    usable = [
        (index, accession, acceptances[index])
        for index, accession in enumerate(accessions)
        if index < len(acceptances)
        and accession
        and acceptances[index]
        and (
            since is None
            or (index < len(filing_dates) and filing_dates[index] >= since)
        )
    ]
    if not usable:
        return [], 0
    if len(usable) == 1:
        indices = [0]
    else:
        indices = sorted(
            {
                round(i * (len(usable) - 1) / (sample_count - 1))
                for i in range(sample_count)
            }
        )
    samples = []
    for sample_index in indices:
        _, accession, acceptance = usable[sample_index]
        if sample_index == 0:
            position = "first"
        elif sample_index == len(usable) - 1:
            position = "last"
        else:
            position = f"quantile_{sample_index / (len(usable) - 1):.2f}"
        samples.append((accession, acceptance, position))
    return samples, len(usable)


def decode_response(response):
    content = response.read()
    encoding = response.headers.get("Content-Encoding", "").lower()
    if encoding == "gzip":
        return gzip.decompress(content)
    if encoding == "deflate":
        return zlib.decompress(content)
    return content


def sgml_url(cik, accession):
    compact = accession.replace("-", "")
    return (
        f"https://www.sec.gov/Archives/edgar/data/{cik}/"
        f"{compact}/{accession}.hdr.sgml"
    )


def fetch_sgml(cik, accession, user_agent):
    url = sgml_url(cik, accession)
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
    )
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = decode_response(response)
            status = response.status
        text = content.decode("latin-1")
        match = re.search(r"<ACCEPTANCE-DATETIME>(\d{14})", text)
        if not match:
            raise ValueError("ACCEPTANCE-DATETIME tag not found")
        acceptance = datetime.strptime(match.group(1), "%Y%m%d%H%M%S")
        error = None
        digest = hashlib.sha256(content).hexdigest()
    except Exception as exc:
        text = None
        acceptance = None
        status = exc.code if isinstance(exc, urllib.error.HTTPError) else None
        error = f"{type(exc).__name__}: {exc}"
        digest = None
    elapsed_ms = (time.monotonic() - started) * 1000
    return {
        "acceptance": acceptance,
        "url": url,
        "retrieved_at": datetime.now(timezone.utc),
        "elapsed_ms": elapsed_ms,
        "status": status,
        "digest": digest,
        "text": text,
        "error": error,
    }


def cached_or_fetch(con, cik, accession, user_agent):
    cached = con.execute(
        """
        SELECT acceptance_datetime, elapsed_ms, error
        FROM sgml_observations
        WHERE accession_number = ? AND acceptance_datetime IS NOT NULL
        """,
        [accession],
    ).fetchone()
    if cached:
        return cached[0], "cache", 0.0, cached[2]

    result = fetch_sgml(cik, accession, user_agent)
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
    return result["acceptance"], "network", result["elapsed_ms"], result["error"]


def parse_zip_datetime(value):
    return datetime.fromisoformat(value.removesuffix("Z"))


def interpretation(diff_min):
    if diff_min == 0:
        return "eastern"
    if diff_min in (240, 300):
        return "utc"
    return "anomalous"


def snapshot_id(path: Path):
    stat = path.stat()
    identity = f"{path.resolve()}:{stat.st_size}:{stat.st_mtime_ns}"
    return hashlib.sha256(identity.encode()).hexdigest()[:16]


def classify(labels):
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--old", type=Path, default=DEFAULT_OLD)
    parser.add_argument("--new", type=Path, default=DEFAULT_NEW)
    parser.add_argument("--zip", type=Path, default=DEFAULT_NEW_ZIP)
    parser.add_argument("--database", type=Path, default=DEFAULT_DB)
    parser.add_argument("--ciks-per-stratum", type=int, default=1)
    parser.add_argument("--samples-per-block", type=int, default=3)
    parser.add_argument("--max-blocks-per-cik", type=int, default=4)
    parser.add_argument("--cik", type=int)
    parser.add_argument("--since")
    parser.add_argument("--request-delay", type=float, default=0.12)
    parser.add_argument("--user-agent", default=DEFAULT_USER_AGENT)
    args = parser.parse_args()
    if args.samples_per_block < 2:
        parser.error("--samples-per-block must be at least 2")

    args.database.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(args.database))
    initialize_database(con)
    run_started = time.monotonic()
    snapshot = snapshot_id(args.zip)
    candidates = cik_candidates(args.old, args.new)

    with zipfile.ZipFile(args.zip) as zf:
        names = set(zf.namelist())
        if args.cik is None:
            selected = choose_ciks(
                zf,
                names,
                candidates,
                args.ciks_per_stratum,
                args.max_blocks_per_cik,
            )
        else:
            candidate = next((row for row in candidates if row[0] == args.cik), None)
            if candidate is None:
                raise RuntimeError(f"CIK {args.cik} is not an eligible overlap candidate")
            cik, stratum, n, n0, ns = candidate
            selected = [
                (cik, stratum, block_names(zf, names, cik), n, n0, ns)
            ]
        print(f"database: {args.database}")
        print(f"snapshot: {snapshot}")
        for cik, stratum, blocks, n, n0, ns in selected:
            print(
                f"CIK {cik} [{stratum}]: {len(blocks)} blocks; "
                f"overlap n={n}, unchanged={n0}, shifted={ns}"
            )
            for block_name in blocks:
                block_started = time.monotonic()
                content = zf.read(block_name)
                block_hash = hashlib.sha256(content).hexdigest()
                samples, n_records = block_samples(
                    json.loads(content), args.samples_per_block, args.since
                )
                if not samples:
                    print(f"  {block_name}: no eligible records; skipped")
                    continue
                labels = []
                new_requests = 0
                cached_requests = 0
                for accession, zip_value, position in samples:
                    sgml_value, source, request_ms, error = cached_or_fetch(
                        con, cik, accession, args.user_agent
                    )
                    if source == "network":
                        new_requests += 1
                    else:
                        cached_requests += 1
                    diff_min = None
                    label = "unresolved"
                    if sgml_value is not None:
                        diff_min = int(
                            (parse_zip_datetime(zip_value) - sgml_value).total_seconds()
                            / 60
                        )
                        label = interpretation(diff_min)
                        labels.append(label)
                    con.execute(
                        """
                        INSERT OR REPLACE INTO block_samples VALUES
                          (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        [
                            snapshot,
                            cik,
                            stratum,
                            block_name,
                            block_hash,
                            accession,
                            position,
                            zip_value,
                            sgml_value,
                            diff_min,
                            label if error is None else "unresolved",
                            source,
                            datetime.now(timezone.utc),
                        ],
                    )
                    print(
                        f"  {block_name} {position}: {accession} -> "
                        f"{diff_min} min ({label}), {source}, {request_ms:.0f} ms"
                    )
                    if source == "network":
                        time.sleep(args.request_delay)

                block_elapsed_ms = (time.monotonic() - block_started) * 1000
                block_classification = classify(labels)
                con.execute(
                    """
                    INSERT OR REPLACE INTO block_classifications VALUES
                      (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        snapshot,
                        cik,
                        stratum,
                        block_name,
                        block_hash,
                        n_records,
                        len(samples),
                        block_classification,
                        new_requests,
                        cached_requests,
                        block_elapsed_ms,
                        datetime.now(timezone.utc),
                    ],
                )
                con.commit()
                print(
                    f"  block result: {block_classification}; "
                    f"{block_elapsed_ms / 1000:.2f}s"
                )

    totals = con.execute(
        """
        SELECT count(*) AS blocks,
               sum(n_samples) AS samples,
               sum(new_requests) AS new_requests,
               sum(cached_requests) AS cached_requests,
               round(sum(elapsed_ms) / 1000, 2) AS block_seconds
        FROM block_classifications
        WHERE snapshot_id = ?
        """,
        [snapshot],
    ).fetchone()
    con.close()
    wall_seconds = time.monotonic() - run_started
    print(
        f"Summary: blocks={totals[0]}, samples={totals[1]}, "
        f"new={totals[2]}, cached={totals[3]}, "
        f"block_time={totals[4]}s, wall_time={wall_seconds:.2f}s"
    )


if __name__ == "__main__":
    main()
