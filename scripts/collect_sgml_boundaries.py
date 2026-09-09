#!/usr/bin/env python3
"""Concurrent boundary scans; persist direct evidence, never inferred rules."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import time
from zoneinfo import ZoneInfo

import duckdb
from fetch_sgml_anchors import (
    DEFAULT_DB, DEFAULT_NEW_ZIP, DEFAULT_USER_AGENT, NetworkRateLimiter,
    fetch_sgml, insert_sgml_observation, interpretation, parse_zip_datetime, snapshot_id,
)

POLICY = 'noncorrespondence-midnight-skip-v1'


def is_midnight(raw):
    if not raw:
        return False
    value = parse_zip_datetime(raw)
    eastern = value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo('America/New_York'))
    return any((v.hour, v.minute, v.second, v.microsecond) == (0, 0, 0, 0)
               for v in (value, eastern))


def scan(target, records, prior, cache, limiter, max_prefix, fetcher=fetch_sgml):
    cik, block, digest = target
    rows = [r for r in records if not is_midnight(r[2])]
    observed = {}

    def check(i):
        if i not in observed:
            index, accession, raw = rows[i]
            cached = cache.get(accession)
            result = None
            if cached and (cached[0] is not None or 'ACCEPTANCE-DATETIME tag not found' in (cached[1] or '')):
                acceptance, error = cached
            else:
                limiter.wait()
                result = fetcher(cik, accession, DEFAULT_USER_AGENT)
                acceptance, error = result['acceptance'], result['error']
            diff, label = None, 'unresolved'
            if acceptance is not None and raw and not error:
                seconds = (parse_zip_datetime(raw) - acceptance).total_seconds()
                if seconds % 60 == 0:
                    diff = int(seconds / 60)
                    label = interpretation(diff)
                else:
                    label = 'anomalous'
            observed[i] = (acceptance, diff, label, result)
        return observed[i][2]

    boundary = None
    for i in range(min(len(rows), max_prefix)):
        if check(i) == 'utc':
            boundary = i
            break
    if boundary is not None and boundary < len(rows) - 1:
        for step in (1, 2, 3):
            check(boundary + max(1, round((len(rows) - 1 - boundary) * step / 3)))
    eligible = {r[0] for r in rows}
    reversal = boundary is not None and (
        any(i > boundary and v[2] == 'eastern' for i, v in observed.items()) or
        any(index in eligible and index > rows[boundary][0] and label == 'eastern'
            for index, label in prior))
    unresolved = sum(v[2] not in ('eastern', 'utc') for v in observed.values())
    status = ('reversal' if reversal else 'incomplete' if unresolved else
              'boundary_supported' if boundary is not None else
              'prefix_capped' if len(rows) > max_prefix else 'fully_checked_no_utc')
    report = dict(cik=cik, block=block, digest=digest, eligible=len(rows),
                  midnight_skipped=len(records)-len(rows), checked=len(observed),
                  new=sum(v[3] is not None for v in observed.values()),
                  boundary_record=None if boundary is None else rows[boundary][0],
                  status=status, unresolved=unresolved)
    return report, rows, observed


def save(snapshot, analyses):
    deadline = time.monotonic() + 300
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
        con.execute('''CREATE TABLE IF NOT EXISTS boundary_scan_results (
            snapshot_id VARCHAR, block_name VARCHAR, policy VARCHAR, block_sha256 VARCHAR,
            status VARCHAR, report_json VARCHAR, recorded_at TIMESTAMPTZ,
            PRIMARY KEY (snapshot_id, block_name, policy))''')
        for report, rows, observed in analyses:
            for i, (acceptance, diff, label, result) in observed.items():
                index, accession, raw = rows[i]
                if result is not None:
                    insert_sgml_observation(con, report['cik'], accession, result)
                con.execute('INSERT OR REPLACE INTO block_samples VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)',
                            [snapshot, report['cik'], 'boundary_pilot', report['block'],
                             report['digest'], accession, f'record_{index}', raw, acceptance,
                             diff, label, 'network' if result is not None else 'cache', datetime.now(timezone.utc)])
            con.execute('INSERT OR REPLACE INTO boundary_scan_results VALUES (?, ?, ?, ?, ?, ?, ?)',
                        [snapshot, report['block'], POLICY, report['digest'], report['status'],
                         json.dumps(report), datetime.now(timezone.utc)])
        con.commit()
    finally:
        con.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workers', type=int, default=15)
    p.add_argument('--files', type=int, default=100000)
    p.add_argument('--batch-files', type=int, default=75)
    p.add_argument('--rate', type=float, default=8)
    p.add_argument('--max-prefix', type=int, default=100)
    a = p.parse_args()
    if min(a.workers, a.files, a.batch_files, a.rate, a.max_prefix) <= 0:
        p.error('Counts and rate must be positive')
    snapshot = snapshot_id(DEFAULT_NEW_ZIP)
    with duckdb.connect(str(DEFAULT_DB), read_only=True) as c:
        targets = c.execute("""WITH m AS (
            SELECT s.snapshot_id,s.block_name FROM block_samples s JOIN zip_filing_records r
            USING(snapshot_id,block_name,accession_number)
            WHERE s.snapshot_id=? AND s.interpretation IN ('eastern','utc')
            AND coalesce(r.form,'') NOT IN ('CORRESP','UPLOAD','DRSLTR')
            GROUP BY 1,2 HAVING count(DISTINCT s.interpretation)=2)
            SELECT b.cik,b.block_name,b.block_sha256 FROM zip_blocks b JOIN m
            USING(snapshot_id,block_name) ORDER BY hash(b.block_name),b.block_name""", [snapshot]).fetchall()
        done = set()
        if c.execute("SELECT count(*) FROM information_schema.tables WHERE table_name='boundary_scan_results'").fetchone()[0]:
            done = set(c.execute("SELECT block_name,block_sha256 FROM boundary_scan_results WHERE snapshot_id=? AND policy=? AND status IN ('boundary_supported','fully_checked_no_utc')", [snapshot, POLICY]).fetchall())
    targets = [t for t in targets if (t[1], t[2]) not in done][:a.files]
    print(json.dumps(dict(selected=len(targets), workers=a.workers, rate=a.rate)), flush=True)
    limiter = NetworkRateLimiter(1 / a.rate)
    started = time.monotonic()
    outcomes, checked, new, skipped = {}, 0, 0, 0
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        for offset in range(0, len(targets), a.batch_files):
            batch = targets[offset:offset+a.batch_files]
            records, prior = {t[1]: [] for t in batch}, {t[1]: [] for t in batch}
            marks = ','.join('?' for _ in batch)
            with duckdb.connect(str(DEFAULT_DB), read_only=True) as c:
                for block, index, accession, raw in c.execute(f"SELECT block_name,record_index,accession_number,zip_acceptance_datetime_text FROM zip_filing_records WHERE snapshot_id=? AND block_name IN ({marks}) AND coalesce(form,'') NOT IN ('CORRESP','UPLOAD','DRSLTR') ORDER BY block_name,record_index", [snapshot, *records]).fetchall():
                    records[block].append((index, accession, raw))
                for block, index, label in c.execute(f"SELECT r.block_name,r.record_index,s.interpretation FROM block_samples s JOIN zip_filing_records r USING(snapshot_id,block_name,accession_number) WHERE s.snapshot_id=? AND s.block_name IN ({marks})", [snapshot, *records]).fetchall():
                    prior[block].append((index, label))
                cache = {acc: (value, error) for acc, value, error in c.execute('SELECT accession_number,acceptance_datetime,error FROM sgml_observations').fetchall()}
            futures = [executor.submit(scan, t, records[t[1]], prior[t[1]], cache, limiter, a.max_prefix) for t in batch]
            analyses = [f.result() for f in futures]
            save(snapshot, analyses)
            for report, _, _ in analyses:
                status = report['status']
                outcomes[status] = outcomes.get(status, 0) + 1
                checked += report['checked']
                new += report['new']
                skipped += report['midnight_skipped']
                if status not in ('boundary_supported', 'fully_checked_no_utc'):
                    print('EXCEPTION ' + json.dumps(report), flush=True)
            print(json.dumps(dict(completed=offset+len(batch),total=len(targets),checked=checked,
                                  new=new,midnight_skipped=skipped,outcomes=outcomes,
                                  seconds=round(time.monotonic()-started,1))), flush=True)


if __name__ == '__main__':
    main()
