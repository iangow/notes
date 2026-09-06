#!/usr/bin/env python3
"""
Extract cik, accessionNumber, acceptanceDateTime from SEC EDGAR submissions.zip.
Checkpoints progress so it can be run in multiple short sessions.

Usage:
    python3 extract_filings.py [submissions.zip] [output.parquet]
Defaults: ~/Downloads/submissions.zip -> ~/Downloads/filings_slim.parquet

Each run resumes automatically from where it left off (via .ckpt file).
When finished, converts the accumulated CSV to parquet and removes the CSV.
"""
import sys, zipfile, json, csv, time
from pathlib import Path

REPORT_EVERY = 50_000
MAX_SECONDS  = 150      # stop and checkpoint before device_bash kills us

def extract(zip_path: Path, out_path: Path) -> None:
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
                w.writerow(["cik", "accessionNumber", "acceptanceDateTime"])

            for i, name in enumerate(primary[start_idx:], start=start_idx):
                if i % REPORT_EVERY == 0:
                    elapsed = time.monotonic() - t0
                    print(f"  {i:,} / {total:,}  ({rows:,} new rows, {elapsed:.0f}s)", flush=True)

                data   = json.loads(zf.read(name))
                cik    = str(data.get("cik", ""))
                recent = data.get("filings", {}).get("recent", {})

                for acc, adt in zip(
                    recent.get("accessionNumber",    []),
                    recent.get("acceptanceDateTime", []),
                ):
                    w.writerow([cik, acc, adt])
                    rows += 1

                for ref in data.get("filings", {}).get("files", []):
                    comp = ref.get("name", "")
                    if comp and comp in name_set and comp not in companion_seen:
                        companion_seen.add(comp)
                        cd = json.loads(zf.read(comp))
                        cr = cd.get("filings", {}).get("recent", {})
                        for acc, adt in zip(
                            cr.get("accessionNumber",    []),
                            cr.get("acceptanceDateTime", []),
                        ):
                            w.writerow([cik, acc, adt])
                            rows += 1

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


def _csv_to_parquet(csv_path, out_path, ckpt_path):
    import pandas as pd
    print("Converting CSV → parquet …", flush=True)
    df = pd.read_csv(csv_path, dtype=str)
    df.to_parquet(out_path, index=False, compression="snappy")
    csv_path.unlink()
    ckpt_path.unlink(missing_ok=True)
    print(f"Done → {out_path}  ({len(df):,} rows, {out_path.stat().st_size/1e6:.1f} MB)", flush=True)


if __name__ == "__main__":
    zip_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads" / "submissions.zip"
    out_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home() / "Downloads" / "filings_slim.parquet"
    extract(zip_path, out_path)
