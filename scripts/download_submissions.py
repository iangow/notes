#!/usr/bin/env python3
"""Download an immutable SEC submissions ZIP with a source manifest."""

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import time
import urllib.request
import zipfile

import duckdb

from compare_filing_timestamp_sources import DEFAULT_USER_AGENT

URL = 'https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip'


def download(output):
    manifest = output.with_suffix('.manifest.parquet')
    partial = output.with_suffix('.partial.zip')
    if any(p.exists() for p in (output, manifest, partial)):
        raise FileExistsError('Use a fresh snapshot path; existing downloads are never overwritten')
    output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    retrieved = datetime.now(timezone.utc)
    request = urllib.request.Request(URL, headers={'User-Agent': DEFAULT_USER_AGENT,
                                                 'Accept-Encoding': 'identity'})
    digest = hashlib.sha256()
    total = 0
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open('xb') as destination:
            length = response.headers.get('Content-Length')
            expected = int(length) if length is not None else None
            modified, etag = response.headers.get('Last-Modified'), response.headers.get('ETag')
            print(f'Downloading {URL}; expected bytes={expected}; Last-Modified={modified}', flush=True)
            while chunk := response.read(1024 * 1024):
                destination.write(chunk)
                digest.update(chunk)
                total += len(chunk)
                if total % (64 * 1024 * 1024) == 0:
                    print(f'{total / 1024**2:,.0f} MiB; {time.monotonic()-started:.1f}s', flush=True)
        if expected is not None and total != expected:
            raise ValueError(f'Incomplete download: {total} bytes; expected {expected}')
        with zipfile.ZipFile(partial) as archive:
            members = len(archive.infolist())
            if not any(n.startswith('CIK') and n.endswith('.json') for n in archive.namelist()):
                raise ValueError('Downloaded ZIP has no CIK JSON files')
        with duckdb.connect() as con:
            con.execute('CREATE TABLE source(url VARCHAR,retrieved_at TIMESTAMPTZ,last_modified VARCHAR,etag VARCHAR,size_bytes BIGINT,sha256 VARCHAR,members BIGINT)')
            con.execute('INSERT INTO source VALUES (?,?,?,?,?,?,?)',
                        [URL,retrieved,modified,etag,total,digest.hexdigest(),members])
            con.execute('COPY source TO ? (FORMAT PARQUET)', [str(manifest)])
        partial.rename(output)
        print(f'Saved {output}: {total:,} bytes; {members:,} members; SHA-256={digest.hexdigest()}', flush=True)
    except BaseException:
        partial.unlink(missing_ok=True)
        manifest.unlink(missing_ok=True)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    download(args.output.expanduser().resolve())


if __name__ == '__main__':
    main()
