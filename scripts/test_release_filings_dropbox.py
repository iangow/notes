from email.message import Message
from hashlib import sha256
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from release_filings_dropbox import (
    download_url,
    main,
    publish_with_generic_script,
    restore_previous_in_place,
    verify_shared_link,
)


class Response:
    def __init__(self, body, status=206, headers=None):
        self.body = body
        self.status = status
        self.headers = Message()
        for key, value in (headers or {}).items():
            self.headers[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if size < 0:
            size = len(self.body)
        result, self.body = self.body[:size], self.body[size:]
        return result


class DropboxReleaseTests(unittest.TestCase):
    def test_download_url_preserves_shared_link_key(self):
        self.assertEqual(
            download_url('https://www.dropbox.com/s/example/file?rlkey=key&dl=0'),
            'https://www.dropbox.com/s/example/file?rlkey=key&dl=1')

    def test_rejects_non_dropbox_url(self):
        with self.assertRaisesRegex(ValueError, 'HTTPS Dropbox'):
            download_url('https://example.com/file')

    def test_range_check_validates_signature_and_size(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'filings.parquet'
            local.write_bytes(b'PAR1payload')
            response = Response(b'PAR1', headers={'Content-Range': 'bytes 0-3/11'})
            with patch('release_filings_dropbox.urllib.request.urlopen', return_value=response) as get:
                size, checksum = verify_shared_link(
                    'https://www.dropbox.com/s/example/file?dl=0', local)
            self.assertEqual((size, checksum), (11, None))
            self.assertEqual(get.call_args.args[0].get_header('Range'), 'bytes=0-3')

    def test_range_check_rejects_size_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'filings.parquet'
            local.write_bytes(b'PAR1payload')
            response = Response(b'PAR1', headers={'Content-Range': 'bytes 0-3/12'})
            with patch('release_filings_dropbox.urllib.request.urlopen', return_value=response):
                with self.assertRaisesRegex(ValueError, 'serves 12 bytes'):
                    verify_shared_link('https://www.dropbox.com/s/example/file', local)

    def test_full_check_compares_downloaded_hash(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'filings.parquet'
            body = b'PAR1payload'
            local.write_bytes(body)
            response = Response(body, status=200)
            with patch('release_filings_dropbox.urllib.request.urlopen', return_value=response):
                size, checksum = verify_shared_link(
                    'https://www.dropbox.com/s/example/file', local, full_sha256=True)
            self.assertEqual(size, len(body))
            self.assertEqual(checksum, sha256(body).hexdigest())

    def test_full_check_rejects_wrong_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            local = Path(directory) / 'filings.parquet'
            local.write_bytes(b'PAR1expected')
            response = Response(b'PAR1badbytes', status=200)
            with patch('release_filings_dropbox.urllib.request.urlopen', return_value=response):
                with self.assertRaisesRegex(ValueError, 'SHA-256'):
                    verify_shared_link(
                        'https://www.dropbox.com/s/example/file', local, full_sha256=True)

    def test_publish_wrapper_does_not_require_sync_to_be_paused(self):
        from argparse import Namespace

        args = Namespace(candidate=Path('candidate.parquet'), previous=None, archive_dir=None)
        with patch('builtins.input', return_value='PUBLISH'), \
                patch('release_filings_dropbox.subprocess.run') as run:
            publish_with_generic_script(args, Path('current.parquet'))
        self.assertIn('publish_filings.py', run.call_args.args[0][1])

    def test_restore_previous_preserves_current_inode(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, previous = root / 'filings.parquet', root / 'filings_previous.parquet'
            current.write_bytes(b'PAR1candidate')
            previous.write_bytes(b'PAR1original')
            inode = current.stat().st_ino
            restore_previous_in_place(current, previous)
            self.assertEqual(current.read_bytes(), previous.read_bytes())
            self.assertEqual(current.stat().st_ino, inode)

    def test_failed_verify_can_restore_previous_release(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, previous = root / 'filings.parquet', root / 'filings_previous.parquet'
            current.write_bytes(b'PAR1candidate')
            previous.write_bytes(b'PAR1original')
            args = ['release_filings_dropbox.py', '--verify-only', '--current', str(current),
                    '--share-url', 'https://www.dropbox.com/s/example/file']
            with patch.object(sys, 'argv', args), \
                    patch('release_filings_dropbox.verify_shared_link',
                          side_effect=ValueError('shared link unavailable')), \
                    patch('builtins.input', return_value='RESTORE'):
                with self.assertRaisesRegex(SystemExit, 'Previous local release restored'):
                    main()
            self.assertEqual(current.read_bytes(), previous.read_bytes())


if __name__ == '__main__':
    unittest.main()
