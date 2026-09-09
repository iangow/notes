#!/usr/bin/env python3
"""Measure boundary sampling costs without promoting timestamp rules."""

import argparse
import json
import time
from datetime import datetime, timezone

import duckdb

from fetch_sgml_anchors import (
    DEFAULT_DB, DEFAULT_NEW_ZIP, DEFAULT_USER_AGENT, NetworkRateLimiter,
    cached_or_fetch_without_write, insert_sgml_observation,
    interpretation, parse_zip_datetime, snapshot_id,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--files', type=int, default=40)
    parser.add_argument('--max-prefix', type=int, default=100)
    parser.add_argument('--seed', default='boundary-pilot-20260907')
    args = parser.parse_args()
    if args.files < 1 or args.max_prefix < 1:
        parser.error('Counts must be positive')
    snapshot = snapshot_id(DEFAULT_NEW_ZIP)
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as con:
        targets = con.execute("""
            WITH mixed AS (
                SELECT s.snapshot_id, s.block_name
                FROM block_samples s JOIN zip_filing_records r
                  USING (snapshot_id, block_name, accession_number)
                WHERE s.snapshot_id = ? AND s.interpretation IN ('eastern', 'utc')
                  AND coalesce(r.form, '') NOT IN ('CORRESP', 'UPLOAD', 'DRSLTR')
                GROUP BY 1, 2 HAVING count(DISTINCT s.interpretation) = 2
            )
            SELECT b.cik, b.block_name, b.block_sha256, b.n_records
            FROM zip_blocks b JOIN mixed USING (snapshot_id, block_name)
            ORDER BY hash(b.block_name || ?), b.block_name
        """, [snapshot, args.seed]).fetchall()
    print(json.dumps({'population_files': len(targets), 'sample_files': min(args.files, len(targets)),
                      'seed': args.seed}), flush=True)
    limiter = NetworkRateLimiter(1 / 8)
    reports = []
    for cik, block, digest, n_records in targets[:args.files]:
        started = time.monotonic()
        with duckdb.connect(str(DEFAULT_DB), read_only=True) as con:
            rows = con.execute("""
                SELECT record_index, accession_number, zip_acceptance_datetime_text
                FROM zip_filing_records
                WHERE snapshot_id = ? AND block_name = ?
                  AND coalesce(form, '') NOT IN ('CORRESP', 'UPLOAD', 'DRSLTR')
                ORDER BY record_index
            """, [snapshot, block]).fetchall()
            prior = con.execute("""
                SELECT r.record_index, s.interpretation
                FROM block_samples s JOIN zip_filing_records r
                  USING (snapshot_id, block_name, accession_number)
                WHERE s.snapshot_id = ? AND s.block_name = ?
                  AND coalesce(r.form, '') NOT IN ('CORRESP', 'UPLOAD', 'DRSLTR')
            """, [snapshot, block]).fetchall()
        observed = {}

        def fetch(i):
            if i not in observed:
                index, accession, raw = rows[i]
                result = cached_or_fetch_without_write(DEFAULT_DB, cik, accession,
                                                       DEFAULT_USER_AGENT, limiter)
                diff = None
                label = 'unresolved'
                if result['acceptance'] is not None and raw:
                    seconds = (parse_zip_datetime(raw) - result['acceptance']).total_seconds()
                    if seconds % 60 == 0:
                        diff = int(seconds / 60)
                        label = interpretation(diff)
                    else:
                        label = 'anomalous'
                observed[i] = (result, diff, label)
            return observed[i][2]

        boundary = None
        for i in range(min(len(rows), args.max_prefix)):
            if fetch(i) == 'utc':
                boundary = i
                break
        if boundary is not None:
            tail = len(rows) - boundary - 1
            if tail:
                for step in (1, 2, 3):
                    fetch(boundary + max(1, round(tail * step / 3)))
        unresolved = sum(v[2] not in ('eastern', 'utc') for v in observed.values())
        reversal = boundary is not None and (
            any(i > boundary and v[2] == 'eastern' for i, v in observed.items())
            or any(index > rows[boundary][0] and label == 'eastern' for index, label in prior)
        )
        status = ('reversal' if reversal else 'incomplete' if unresolved else
                  'boundary_supported' if boundary is not None else
                  'prefix_capped' if len(rows) > args.max_prefix else 'fully_checked_no_utc')
        # Persist only direct observations, in a short atomic write burst.
        deadline = time.monotonic() + 60
        while True:
            try:
                con = duckdb.connect(str(DEFAULT_DB))
                break
            except duckdb.IOException:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        try:
            con.execute('BEGIN TRANSACTION')
            for i, (result, diff, label) in observed.items():
                index, accession, raw = rows[i]
                if result['source'] == 'network':
                    insert_sgml_observation(con, cik, accession, result['result'])
                con.execute('INSERT OR REPLACE INTO block_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            [snapshot, cik, 'boundary_pilot', block, digest, accession,
                             f'record_{index}', raw, result['acceptance'], diff, label,
                             result['source'], datetime.now(timezone.utc)])
            con.commit()
        finally:
            con.close()
        report = dict(cik=cik, block=block, total_rows=n_records, eligible=len(rows),
                      checked=len(observed), new=sum(v[0]['source'] == 'network' for v in observed.values()),
                      boundary_record=None if boundary is None else rows[boundary][0],
                      prefix_checks=None if boundary is None else boundary + 1,
                      status=status, unresolved=unresolved,
                      seconds=round(time.monotonic() - started, 3))
        reports.append(report)
        print(json.dumps(report), flush=True)
    print('SUMMARY ' + json.dumps(dict(population=len(targets), reports=reports)), flush=True)


if __name__ == '__main__':
    main()
