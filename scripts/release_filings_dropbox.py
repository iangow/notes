#!/usr/bin/env python3
"""Publish filings.parquet locally, then verify its Dropbox shared link."""

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request


def file_digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').digest()


def download_url(shared_url):
    parsed = urllib.parse.urlsplit(shared_url)
    if parsed.scheme != 'https' or not parsed.hostname or not (
        parsed.hostname == 'dropbox.com' or parsed.hostname.endswith('.dropbox.com')
    ):
        raise ValueError('Share URL must be an HTTPS Dropbox link')
    query = [(key, value) for key, value in urllib.parse.parse_qsl(parsed.query)
             if key != 'dl']
    query.append(('dl', '1'))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


def verify_shared_link(shared_url, expected_file, full_sha256=False):
    expected_file = Path(expected_file)
    if not expected_file.is_file():
        raise ValueError(f'Expected local release does not exist: {expected_file}')
    expected_size = expected_file.stat().st_size
    url = download_url(shared_url)
    headers = {'User-Agent': 'SEC-submissions-workflow/1.0'}
    if not full_sha256:
        headers['Range'] = 'bytes=0-3'
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=60) as response:
        status = response.status
        if status not in (200, 206):
            raise ValueError(f'Dropbox link returned HTTP {status}')
        magic = response.read(4)
        if magic != b'PAR1':
            raise ValueError('Dropbox link did not return a Parquet file (missing PAR1 signature)')

        if full_sha256:
            hasher = hashlib.sha256()
            hasher.update(magic)
            size = len(magic)
            while chunk := response.read(1024 * 1024):
                hasher.update(chunk)
                size += len(chunk)
            if size != expected_size:
                raise ValueError(f'Downloaded {size:,} bytes; expected {expected_size:,}')
            with expected_file.open('rb') as source:
                expected_hash = hashlib.file_digest(source, 'sha256').hexdigest()
            actual_hash = hasher.hexdigest()
            if actual_hash != expected_hash:
                raise ValueError('Dropbox download SHA-256 does not match the local release')
            return size, actual_hash

        content_range = response.headers.get('Content-Range')
        if content_range:
            try:
                total = int(content_range.rsplit('/', 1)[1])
            except (IndexError, ValueError) as exc:
                raise ValueError(f'Unrecognized Dropbox Content-Range: {content_range}') from exc
        else:
            content_length = response.headers.get('Content-Length')
            if not content_length:
                raise ValueError('Dropbox response did not report the file size')
            total = int(content_length)
        if total != expected_size:
            raise ValueError(f'Dropbox link serves {total:,} bytes; local release has {expected_size:,}')
        return total, None


def restore_previous_in_place(current, previous):
    current, previous = Path(current), Path(previous)
    if not current.is_file() or not previous.is_file():
        raise ValueError('Current release and previous backup must both exist')
    if current.is_symlink() or previous.is_symlink() or current.samefile(previous):
        raise ValueError('Current release and previous backup must be separate, regular files')

    expected_digest = file_digest(previous)
    inode = current.stat().st_ino
    with previous.open('rb') as source, current.open('r+b') as destination:
        shutil.copyfileobj(source, destination)
        destination.truncate()
        destination.flush()
        os.fsync(destination.fileno())
    if file_digest(current) != expected_digest:
        raise OSError('Restored bytes do not match the previous-release backup')
    if current.stat().st_ino != inode:
        raise RuntimeError('Current file identity changed during restoration')


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path,
                        help='approved Parquet candidate; required unless --verify-only')
    parser.add_argument('--current', type=Path, required=True,
                        help='existing local release path synced to Dropbox')
    parser.add_argument('--share-url', required=True,
                        help='existing public Dropbox shared link')
    parser.add_argument('--previous', type=Path)
    parser.add_argument('--archive-dir', type=Path)
    parser.add_argument('--verify-only', action='store_true',
                        help='skip publication and verify the current local file against Dropbox')
    parser.add_argument('--verify-sha256', action='store_true',
                        help='download the entire shared file and compare its SHA-256')
    return parser


def publish_with_generic_script(args, current):
    if not args.candidate:
        raise ValueError('--candidate is required unless --verify-only is used')
    print('This wrapper will not pause Dropbox syncing. If sync is active, it may observe intermediate bytes during the in-place copy.')
    print('Close other readers and writers of the release files before continuing.')
    if input('Type PUBLISH to continue: ').strip() != 'PUBLISH':
        raise SystemExit('Publication cancelled.')

    publisher = Path(__file__).with_name('publish_filings.py')
    command = [sys.executable, str(publisher), '--candidate',
               str(args.candidate.expanduser().absolute()), '--current', str(current)]
    if args.previous:
        command.extend(['--previous', str(args.previous.expanduser().absolute())])
    if args.archive_dir:
        command.extend(['--archive-dir', str(args.archive_dir.expanduser().absolute())])
    subprocess.run(command, check=True)

    print('Publication is complete locally. If Dropbox syncing is paused, resume it now; otherwise wait for it to finish.')
    input('When Dropbox reports sync is complete, press Enter to test the shared link: ')


def main():
    args = build_parser().parse_args()
    current = args.current.expanduser().absolute()
    previous = (args.previous or current.with_name('filings_previous.parquet')).expanduser().absolute()
    try:
        if not args.verify_only:
            publish_with_generic_script(args, current)
            expected_file = args.candidate.expanduser().absolute()
        else:
            expected_file = current
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.returncode) from exc
    except (OSError, ValueError) as exc:
        raise SystemExit(f'Local publication failed: {exc}') from exc

    try:
        size, sha256 = verify_shared_link(args.share_url, expected_file, args.verify_sha256)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f'Dropbox release check failed: {exc}')
        if previous.is_file() and current.is_file():
            confirmation = input(
                'If the Dropbox check failed after sync completed, type RESTORE to restore the previous local release in place: '
            ).strip()
            if confirmation == 'RESTORE':
                try:
                    restore_previous_in_place(current, previous)
                except (OSError, ValueError, RuntimeError) as restore_error:
                    raise SystemExit(f'Previous release restoration failed: {restore_error}') from restore_error
                raise SystemExit(
                    'Previous local release restored in place. Wait for Dropbox to sync it, then rerun with --verify-only.'
                )
        raise SystemExit(1) from exc

    print(f'Dropbox shared link is available and serves a Parquet file ({size:,} bytes).')
    if sha256:
        print(f'Remote SHA-256 matches local release: {sha256}')
    else:
        print('Size and Parquet signature match; use --verify-sha256 to compare every byte.')


if __name__ == '__main__':
    main()
