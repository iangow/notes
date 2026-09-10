#!/usr/bin/env python3
"""Collect independently selected recent live JSON and freeze updated evidence."""

import argparse
from pathlib import Path
import subprocess
import sys

from acceptance_timestamp_db import DEFAULT_DB


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--targets',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--sgml-queue',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--inference-output',type=Path,required=True)
    p.add_argument('--evaluation-output',type=Path,required=True)
    p.add_argument('--workers',type=int,default=8)
    p.add_argument('--max-requests-per-second',type=float,default=8)
    p.add_argument('--only-form',help='Restrict collection to this form for a targeted backfill.')
    args=p.parse_args()
    if args.workers<1 or args.max_requests_per_second<=0:
        p.error('Workers and request rate must be positive')
    for path in (args.inference_output,args.evaluation_output):
        if path.exists():
            raise FileExistsError(path)
    scripts=Path(__file__).resolve().parent

    def run(script,*options):
        subprocess.run([sys.executable,'-u',str(scripts/script),
                        '--database',str(args.database),*map(str,options)],check=True)

    run('compare_live_json_timestamps.py','--target-database',args.targets,
        '--include-correspondence','--follow-history','--promote-overrides',
        '--workers',args.workers,'--max-requests-per-second',args.max_requests_per_second,
        *(['--only-form',args.only_form] if args.only_form else []))
    run('infer_live_file_timezones.py','--baseline',args.baseline,
        '--output',args.inference_output,'--sgml-anchor-unclassified')
    run('evaluate_timestamp_workflow.py','--baseline',args.baseline,
        '--live-inference',args.inference_output,'--sgml-queue',args.sgml_queue,
        '--output',args.evaluation_output)
    print('Recent live collection and evaluation finished; production Parquet unchanged.',flush=True)


if __name__=='__main__':
    main()
