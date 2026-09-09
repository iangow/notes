#!/usr/bin/env python3
"""Collect old-rule candidate JSON, infer live file zones, and report gains."""

import argparse
from pathlib import Path
import subprocess
import sys

import duckdb

from compare_filing_timestamp_sources import sql_string


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--targets',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    scripts=Path(__file__).resolve().parent
    subprocess.run([sys.executable,'-u',str(scripts/'compare_live_json_timestamps.py'),
                    '--target-database',str(args.targets),'--include-correspondence',
                    '--follow-history','--promote-overrides'],check=True)
    subprocess.run([sys.executable,'-u',str(scripts/'infer_live_file_timezones.py'),
                    '--baseline',str(args.baseline),'--output',str(args.output),
                    '--promote-overrides'],check=True)
    with duckdb.connect(str(args.output),read_only=True) as c:
        c.execute(f'ATTACH {sql_string(args.targets)} AS targets (READ_ONLY)')
        print('OLD-RULE TARGET RESULT: rows, now resolved, matching old result, differing from old result',flush=True)
        print(c.execute("""
            WITH resolved AS (
              SELECT t.*,coalesce(a.instant,i.instant) new_instant FROM targets.candidate_rows t
              LEFT JOIN anchors a ON a.accession=t.accessionNumber
              LEFT JOIN inferred_overrides i ON i.accession_number=t.accessionNumber
            )
            SELECT count(*),count(new_instant),
                   count(*) FILTER(WHERE new_instant=reference_instant),
                   count(*) FILTER(WHERE new_instant IS NOT NULL AND new_instant IS DISTINCT FROM reference_instant)
            FROM resolved
        """).fetchone(),flush=True)
    print('Step 5 collection and inference finished; production Parquet unchanged.',flush=True)


if __name__=='__main__':
    main()
