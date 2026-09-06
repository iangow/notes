#!/usr/bin/env python3
"""
Extract filing-level data from SEC EDGAR submissions.zip.
Checkpoints progress so it can be run in multiple short sessions.

Usage:
    python3 extract_filings.py [submissions.zip] [output.parquet]
Defaults: $RAW_DATA_DIR/submissions/submissions.zip -> $DATA_DIR/edgar/filings.parquet.
If these variables are not set, uses the corresponding directories under
~/Dropbox.

Each run resumes automatically from where it left off (via .ckpt file).
When finished, converts the accumulated CSV to parquet and removes the CSV.
"""
import sys, zipfile, json, csv, time
import os
from pathlib import Path

from dotenv import load_dotenv

REPORT_EVERY = 50_000
MAX_SECONDS  = 150      # stop and checkpoint before device_bash kills us
TIMEZONE = "America/New_York"
REPO_ROOT = Path(__file__).resolve().parents[1]

load_dotenv(REPO_ROOT / ".env")

RAW_SCHEMA = "submissions"
OUT_SCHEMA = "edgar"
RAW_DATA_DIR = Path(
    os.environ.get("RAW_DATA_DIR", Path.home() / "Dropbox" / "raw_data")
).expanduser()
DATA_DIR = Path(
    os.environ.get("DATA_DIR", Path.home() / "Dropbox" / "pq_data")
).expanduser()
DEFAULT_ZIP = RAW_DATA_DIR / RAW_SCHEMA / "submissions.zip"
DEFAULT_OUT = DATA_DIR / OUT_SCHEMA / "filings.parquet"
FIELDS = [
    "accessionNumber",
    "filingDate",
    "acceptanceDateTime",
    "form",
    "items",
]

def extract(zip_path: Path, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path  = out_path.with_suffix(".csv")
    ckpt_path = out_path.with_suffix(".ckpt")

    print(f"zip:  {zip_path}  ({zip_path.stat().st_size/1e6:.0f} MB)", flush=True)
    print(f"out:  {out_path}", flush=True)

    with zipfile.ZipFile(zip_path) as zf:
        name_set = set(zf.namelist())
        primary  = sorted(
            n for n in name_set
            if n.startswith("CIK") and "-submissions-" not in n and n.endswith(".json")
        )
        total = len(primary)

        # Load checkpoint
        start_idx = 0
        if ckpt_path.exists():
            start_idx = int(ckpt_path.read_text().strip())
        print(f"Resuming from index {start_idx:,} / {total:,}", flush=True)

        if start_idx >= total:
            print("All files already processed — converting CSV to parquet.", flush=True)
            _csv_to_parquet(csv_path, out_path, ckpt_path)
            return

        companion_seen = set()
        rows = 0
        t0   = time.monotonic()

        append = start_idx > 0
        with open(csv_path, "a" if append else "w", newline="") as fh:
            w = csv.writer(fh)
            if not append:
                w.writerow(["cik", *FIELDS])

            for i, name in enumerate(primary[start_idx:], start=start_idx):
                if i % REPORT_EVERY == 0:
                    elapsed = time.monotonic() - t0
                    print(f"  {i:,} / {total:,}  ({rows:,} new rows, {elapsed:.0f}s)", flush=True)

                data   = json.loads(zf.read(name))
                cik    = str(data.get("cik", ""))
                recent = _recent_filings(data)
                rows += _write_recent_rows(w, cik, recent)

                for ref in data.get("filings", {}).get("files", []):
                    comp = ref.get("name", "")
                    if comp and comp in name_set and comp not in companion_seen:
                        companion_seen.add(comp)
                        cd = json.loads(zf.read(comp))
                        cr = _recent_filings(cd)
                        rows += _write_recent_rows(w, cik, cr)

                # Save checkpoint and exit before timeout
                if time.monotonic() - t0 >= MAX_SECONDS:
                    next_idx = i + 1
                    ckpt_path.write_text(str(next_idx))
                    print(f"Checkpoint saved at {next_idx:,} — run again to continue.", flush=True)
                    return

        # Reached the end
        ckpt_path.write_text(str(total))
        print(f"All {total:,} files done. CSV size: {csv_path.stat().st_size/1e6:.0f} MB", flush=True)
        _csv_to_parquet(csv_path, out_path, ckpt_path)


def _recent_filings(data):
    return data.get("filings", {}).get("recent", data)


def _write_recent_rows(writer, cik, recent):
    lengths = [len(recent.get(field, [])) for field in FIELDS]
    n_rows = max(lengths, default=0)

    for idx in range(n_rows):
        row = [cik]
        for field in FIELDS:
            values = recent.get(field, [])
            row.append(values[idx] if idx < len(values) else "")
        writer.writerow(row)

    return n_rows


def _csv_to_parquet(csv_path, out_path, ckpt_path):
    import duckdb

    print("Converting CSV to parquet ...", flush=True)
    tmp_out_path = out_path.with_suffix(".tmp.parquet")
    tmp_out_path.unlink(missing_ok=True)

    con = duckdb.connect()
    con.execute("LOAD icu")
    con.execute("SET TimeZone = 'UTC'")
    csv = _sql_string(csv_path)
    out = _sql_string(tmp_out_path)
    con.execute(f"""
        COPY (
          SELECT
            TRY_CAST(cik AS INTEGER) AS cik,
            accessionNumber,
            TRY_CAST(filingDate AS DATE) AS filingDate,
            COALESCE(
              TRY_STRPTIME(
                REGEXP_REPLACE(REPLACE(acceptanceDateTime, 'T', ' '), 'Z$', ''),
                '%Y-%m-%d %H:%M:%S.%g'
              ),
              TRY_STRPTIME(
                REGEXP_REPLACE(REPLACE(acceptanceDateTime, 'T', ' '), 'Z$', ''),
                '%Y-%m-%d %H:%M:%S'
              )
            ) AT TIME ZONE '{TIMEZONE}' AS acceptanceDateTime,
            form,
            items
          FROM read_csv(
            {csv},
            all_varchar = true,
            header = true,
            null_padding = true
          )
        )
        TO {out}
        (FORMAT PARQUET, COMPRESSION SNAPPY)
    """)
    total_rows = con.execute(
        f"SELECT COUNT(*) FROM read_parquet({out})"
    ).fetchone()[0]
    con.close()
    tmp_out_path.replace(out_path)
    csv_path.unlink()
    ckpt_path.unlink(missing_ok=True)
    print(f"Done -> {out_path}  ({total_rows:,} rows, {out_path.stat().st_size/1e6:.1f} MB)", flush=True)


def _sql_string(path: Path) -> str:
    return "'" + str(path).replace("'", "''") + "'"


if __name__ == "__main__":
    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_ZIP
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_OUT
    extract(zip_path, out_path)
