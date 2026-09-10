#!/usr/bin/env python3
"""Collect a frozen audit sample without promoting corrections, then report."""

import argparse
from pathlib import Path
import subprocess
import sys

from acceptance_timestamp_db import DEFAULT_DB


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--paired',action='store_true',help='Report three frozen predictions on the same sample.')
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    scripts=Path(__file__).resolve().parent
    common=['--queue',str(args.queue),'--database',str(args.database)]
    subprocess.run([sys.executable,'-u',str(scripts/'collect_queued_sgml.py'),*common,
                    '--audit-only','--shuffle-seed','20260910','--workers','8','--rate','8'],check=True)
    reporter='report_paired_timestamp_audit.py' if args.paired else 'report_timestamp_audit.py'
    subprocess.run([sys.executable,'-u',str(scripts/reporter),*common,
                    '--output',str(args.output)],check=True)


if __name__=='__main__':
    main()
