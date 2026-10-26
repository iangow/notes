#!/usr/bin/env python3
"""Roll filings releases forward while retaining the current file's identity."""

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

import duckdb


def digest(path):
    with path.open('rb') as source:
        return hashlib.file_digest(source, 'sha256').digest()


def validate(candidate, current):
    with duckdb.connect() as con:
        schemas = [con.execute('DESCRIBE SELECT * FROM read_parquet(?)', [str(p)]).fetchall()
                   for p in (candidate, current)]
        candidate_schema = {r[0]: r[1] for r in schemas[0]}
        if any(candidate_schema.get(r[0]) != r[1] for r in schemas[1]):
            raise ValueError('Candidate drops or changes current columns')
        if dict((r[0],r[1]) for r in schemas[0]).get('acceptanceDateTime') != 'TIMESTAMP WITH TIME ZONE':
            raise ValueError('Candidate acceptanceDateTime must be timezone-aware')
        rows = con.execute('SELECT count(*) FROM read_parquet(?)', [str(candidate)]).fetchone()[0]
        if rows == 0:
            raise ValueError('Candidate is empty')
        return rows


def publish(candidate: Path, current: Path, previous: Path, archive: Path):
    if not candidate.is_file() or not current.is_file():
        raise ValueError('Candidate and current release must both exist')
    paths = (candidate.resolve(),current.resolve(),previous.resolve())
    if len(set(paths)) != 3:
        raise ValueError('Candidate, current, and previous paths must differ')
    if candidate.samefile(current) or (previous.exists() and
        (previous.samefile(current) or previous.samefile(candidate))):
        raise ValueError('Release paths must not be links to the same file')
    if current.is_symlink() or previous.is_symlink():
        raise ValueError('Current and previous paths must not be symbolic links')
    rows = validate(candidate,current)
    candidate_digest = digest(candidate)
    previous.parent.mkdir(parents=True,exist_ok=True)
    archive.mkdir(parents=True,exist_ok=True)
    # Finish the backup before rotating releases or touching the current file.
    handle, temporary = tempfile.mkstemp(prefix=previous.name+'.',suffix='.tmp',dir=previous.parent)
    os.close(handle)
    temporary = Path(temporary)
    archived = None
    try:
        shutil.copyfile(current,temporary)
        with temporary.open('rb') as backup:
            os.fsync(backup.fileno())
        if previous.exists():
            stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            archived = archive/f'{previous.stem}-{stamp}{previous.suffix}'
            if archived.exists():
                raise FileExistsError(archived)
            previous.rename(archived)
        temporary.replace(previous)
        inode = current.stat().st_ino
        try:
            with candidate.open('rb') as source, current.open('r+b') as destination:
                shutil.copyfileobj(source,destination)
                destination.truncate()
                destination.flush()
                os.fsync(destination.fileno())
            if digest(current) != candidate_digest:
                raise OSError('Published bytes do not match the validated candidate')
        except BaseException:
            # Restore interrupted writes without unlinking the shared file.
            with previous.open('rb') as source, current.open('r+b') as destination:
                shutil.copyfileobj(source,destination)
                destination.truncate()
                destination.flush()
                os.fsync(destination.fileno())
            raise
        if current.stat().st_ino != inode:
            raise RuntimeError('Current file identity changed during publication')
    finally:
        temporary.unlink(missing_ok=True)
    return rows, archived


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--current',type=Path,required=True,
                        help='existing current release path')
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--archive-dir',type=Path)
    return parser


def main():
    args = build_parser().parse_args()
    current = args.current.expanduser().absolute()
    previous = args.previous or current.with_name('filings_previous.parquet')
    archive = args.archive_dir or current.parent/'archive'
    rows, archived = publish(args.candidate.expanduser().absolute(),current,
                             previous.expanduser().absolute(),archive.expanduser().absolute())
    print(f'Published {rows:,} rows to {current} in place')
    print(f'Previous release: {previous}')
    if archived:
        print(f'Archived older previous release: {archived}')
    print('Verified candidate SHA-256 and unchanged local inode.')


if __name__ == '__main__':
    main()
