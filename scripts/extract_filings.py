#!/usr/bin/env python3
"""Extract submissions.zip into a separate, resumable set of Parquet tables.

Usage: python scripts/extract_filings.py [submissions.zip] [output.parquet]
See EXTRACT_FILINGS.md for schemas, timestamp semantics, and resume behavior.
"""
import argparse
from contextlib import ExitStack
import json
import os
import resource
import sys
from pathlib import Path
import time
import zipfile

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
RAW_DATA_DIR = Path(os.environ.get("RAW_DATA_DIR", Path.home() / "Dropbox/raw_data")).expanduser()
DATA_DIR = Path(os.environ.get("DATA_DIR", Path.home() / "Dropbox/pq_data")).expanduser()
DEFAULT_ZIP = RAW_DATA_DIR / "submissions/submissions.zip"
DEFAULT_OUT = DATA_DIR / "edgar/filings_expanded.parquet"
MAX_SECONDS = 150
VERSION = 2
FIELDS = [
    "accessionNumber", "filingDate", "reportDate", "acceptanceDateTime",
    "act", "form", "fileNumber", "filmNumber", "items", "core_type", "size",
    "isXBRL", "isInlineXBRL", "primaryDocument", "primaryDocDescription",
]
# Seed schemas also make empty tables usable. Additional keys are discovered
# across ALL records, not just DuckDB's initial inference sample.
TABLE_FIELDS = {
    "filings": ["cik", *FIELDS, "source_file"],
    "companies": ["cik", "source_file"],
    "addresses": ["cik", "address_type", "source_file"],
    "tickers": ["cik", "ticker", "exchange", "source_file"],
    "former_names": ["cik", "name", "from", "to", "source_file"],
    "files": ["cik", "name", "filingCount", "filingFrom", "filingTo", "source_file", "available"],
}


def _sql_string(value):
    return "'" + str(value).replace("'", "''") + "'"


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def output_paths(out_path):
    return {table: out_path if table == "filings" else
            out_path.with_name(f"{out_path.stem}_{table}.parquet")
            for table in TABLE_FIELDS}


def _recent_filings(data):
    return data.get("filings", {}).get("recent", data)


def filing_rows(cik, recent, source_file):
    if any(not isinstance(values, list) for values in recent.values()):
        raise ValueError(f"Non-array filing field in {source_file}")
    for i in range(max((len(v) for v in recent.values()), default=0)):
        row = {key: values[i] if i < len(values) else None
               for key, values in recent.items()}
        row.update(cik=cik, source_file=source_file)
        yield row


def company_rows(data, source_file, names):
    cik = data["cik"]
    common = {"cik": cik, "source_file": source_file}
    excluded = {"filings", "addresses", "tickers", "exchanges", "formerNames"}
    yield "companies", {**{k: v for k, v in data.items() if k not in excluded}, **common}
    for kind, address in (data.get("addresses") or {}).items():
        yield "addresses", {**(address or {}), **common, "address_type": kind}
    tickers, exchanges = data.get("tickers") or [], data.get("exchanges") or []
    for i in range(max(len(tickers), len(exchanges))):
        yield "tickers", {**common, "ticker": tickers[i] if i < len(tickers) else None,
                          "exchange": exchanges[i] if i < len(exchanges) else None}
    for former in data.get("formerNames") or []:
        yield "former_names", {**former, **common}
    for ref in data.get("filings", {}).get("files") or []:
        yield "files", {**ref, **common, "available": ref.get("name") in names}


def _expression(table, key):
    col = _identifier(key)
    kind = None
    if key == "cik" or (table == "companies" and key == "sic"):
        kind = "INTEGER"
    elif (table == "filings" and key == "size") or (table == "files" and key == "filingCount"):
        kind = "BIGINT"
    elif (table == "filings" and key in {"isXBRL", "isInlineXBRL"}) or (
        table == "companies" and key.endswith("Exists")
    ) or (table == "addresses" and key == "isForeignLocation") or (table == "files" and key == "available"):
        kind = "BOOLEAN"
    elif (table == "filings" and key in {"filingDate", "reportDate"}) or (
        table == "files" and key in {"filingFrom", "filingTo"}
    ):
        kind = "DATE"
    return f"TRY_CAST({col} AS {kind}) AS {col}" if kind else col


def _peak_rss_mib():
    """Process lifetime peak RSS; macOS reports bytes, Linux reports KiB."""
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return rss / (1024 ** 2 if sys.platform == "darwin" else 1024)


def _to_parquet(stage, paths, state):
    import duckdb

    print(f"Before conversion: process peak RSS {_peak_rss_mib():,.0f} MiB", flush=True)
    with duckdb.connect() as con:
        for table, output in paths.items():
            started = time.monotonic()
            fields = state["fields"][table]
            columns = ", ".join(f"{_sql_string(k)}: 'VARCHAR'" for k in fields)
            select = ", ".join(_expression(table, k) for k in fields)
            if state["counts"][table]:
                source = f"read_json({_sql_string(stage / (table + '.jsonl'))}, format='newline_delimited', columns={{{columns}}})"
            else:
                source = "(SELECT " + ", ".join(f"NULL::VARCHAR AS {_identifier(k)}" for k in fields) + " WHERE false)"
            temporary = output.with_suffix(".tmp.parquet")
            con.execute(f"COPY (SELECT {select} FROM {source}) TO {_sql_string(temporary)} (FORMAT PARQUET, COMPRESSION SNAPPY)")
            count = con.execute(f"SELECT count(*) FROM read_parquet({_sql_string(temporary)})").fetchone()[0]
            if count != state["counts"][table]:
                raise RuntimeError(f"Row count mismatch for {table}")
            print(f"Prepared {output}: {count:,} rows; "
                  f"{time.monotonic() - started:.1f}s; "
                  f"process peak RSS {_peak_rss_mib():,.0f} MiB", flush=True)
        # Prepare every table before publishing any of them. Staging remains
        # available for retry if conversion or publication is interrupted.
        for output in paths.values():
            output.with_suffix(".tmp.parquet").replace(output)


def extract(zip_path: Path, out_path: Path, max_seconds=MAX_SECONDS):
    zip_path, out_path = zip_path.expanduser().resolve(), out_path.expanduser().resolve()
    if out_path.name == "filings.parquet":
        raise ValueError("Use a separate output name; filings.parquet is protected.")
    paths = output_paths(out_path)
    if zip_path in paths.values():
        raise ValueError("Output must not replace the source ZIP.")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    stage = out_path.with_suffix(".staging")
    stage.mkdir(exist_ok=True)
    ckpt = stage / "checkpoint.json"
    stat = zip_path.stat()
    identity = [str(zip_path), stat.st_size, stat.st_mtime_ns]
    state = {"version": VERSION, "zip": identity, "next_index": 0,
             "fields": {t: list(f) for t, f in TABLE_FIELDS.items()},
             "counts": dict.fromkeys(TABLE_FIELDS, 0),
             "offsets": dict.fromkeys(TABLE_FIELDS, 0)}
    if ckpt.exists():
        state = json.loads(ckpt.read_text())
        if state["version"] != VERSION or state["zip"] != identity:
            raise ValueError("Checkpoint belongs to a different ZIP/schema; use a new output name.")
    elif any(p.exists() for p in paths.values()):
        raise FileExistsError("An output already exists; use a new output name.")

    with zipfile.ZipFile(zip_path) as zf, ExitStack() as stack:
        names = set(zf.namelist())
        primary = sorted(n for n in names if n.startswith("CIK") and "-submissions-" not in n and n.endswith(".json"))
        handles = {}
        for table in TABLE_FIELDS:
            path = stage / f"{table}.jsonl"
            if state["offsets"][table] and (not path.exists() or path.stat().st_size < state["offsets"][table]):
                raise ValueError(f"Missing or truncated staging data: {path}")
            fh = stack.enter_context(open(path, "r+b" if path.exists() else "w+b"))
            fh.truncate(state["offsets"][table])
            fh.seek(state["offsets"][table])
            handles[table] = fh

        def checkpoint(index):
            for table, fh in handles.items():
                fh.flush()
                os.fsync(fh.fileno())
                state["offsets"][table] = fh.tell()
            state["next_index"] = index
            temporary = ckpt.with_suffix(".tmp")
            temporary.write_text(json.dumps(state))
            temporary.replace(ckpt)

        def write(table, row):
            for key in row:
                if key not in state["fields"][table]:
                    state["fields"][table].append(key)
            # Unknown nested fields are retained as JSON strings, avoiding
            # lossy inference and heterogeneous struct schemas.
            row = {k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v
                   for k, v in row.items()}
            handles[table].write((json.dumps(row, ensure_ascii=False) + "\n").encode())
            state["counts"][table] += 1

        checkpoint(state["next_index"])
        print(f"Resuming {state['next_index']:,} / {len(primary):,}: {zip_path}", flush=True)
        started = time.monotonic()
        for i in range(state["next_index"], len(primary)):
            name = primary[i]
            data = json.loads(zf.read(name))
            for table, row in company_rows(data, name, names):
                write(table, row)
            for row in filing_rows(data["cik"], _recent_filings(data), name):
                write("filings", row)
            seen = set()
            for ref in data.get("filings", {}).get("files") or []:
                companion = ref.get("name")
                if companion in names and companion not in seen:
                    seen.add(companion)
                    for row in filing_rows(data["cik"], _recent_filings(json.loads(zf.read(companion))), companion):
                        write("filings", row)
            expired = max_seconds > 0 and time.monotonic() - started >= max_seconds
            if (i + 1) % 1000 == 0 or expired:
                checkpoint(i + 1)
                print(f"Processed {i + 1:,} / {len(primary):,}; {state['counts']['filings']:,} filings", flush=True)
            if expired and i + 1 < len(primary):
                print("Checkpoint saved; run the same command to continue.", flush=True)
                return False
        checkpoint(len(primary))
    _to_parquet(stage, paths, state)
    for table in TABLE_FIELDS:
        (stage / f"{table}.jsonl").unlink()
    ckpt.unlink()
    stage.rmdir()
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", nargs="?", type=Path, default=DEFAULT_ZIP)
    parser.add_argument("output", nargs="?", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-seconds", type=float, default=MAX_SECONDS,
                        help="Checkpoint and return after this many extraction seconds; 0 runs to completion.")
    args = parser.parse_args()
    extract(args.zip, args.output, args.max_seconds)
