from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from publish_filings import build_parser, publish


class PublicationTests(unittest.TestCase):
    def test_current_path_must_be_supplied(self):
        with redirect_stderr(StringIO()):
            with self.assertRaises(SystemExit) as error:
                build_parser().parse_args(['--candidate', 'candidate.parquet'])
        self.assertEqual(error.exception.code, 2)

    def write(self, path, instant):
        with duckdb.connect() as con:
            con.execute('CREATE TABLE release AS SELECT ?::TIMESTAMPTZ acceptanceDateTime', [instant])
            con.execute('COPY release TO ? (FORMAT PARQUET)', [str(path)])

    def test_rotation_preserves_current_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            self.write(candidate,'2025-01-01 13:00:00+00')
            self.write(previous,'2025-01-01 11:00:00+00')
            inode, old, older = current.stat().st_ino,current.read_bytes(),previous.read_bytes()
            rows, archived = publish(candidate,current,previous,root/'archive')
            self.assertEqual(rows,1)
            self.assertEqual(current.stat().st_ino,inode)
            self.assertEqual(current.read_bytes(),candidate.read_bytes())
            self.assertEqual(previous.read_bytes(),old)
            self.assertEqual(archived.read_bytes(),older)

    def test_failed_copy_restores_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            self.write(candidate,'2025-01-01 13:00:00+00')
            original, inode = current.read_bytes(),current.stat().st_ino
            original_copy = shutil.copyfileobj
            calls = 0

            def fail_once(source,destination):
                nonlocal calls
                calls += 1
                if calls == 1:
                    destination.write(b'incomplete')
                    raise OSError('simulated interrupted write')
                return original_copy(source,destination)

            with patch('publish_filings.shutil.copyfileobj',side_effect=fail_once):
                with self.assertRaisesRegex(OSError,'simulated'):
                    publish(candidate,current,previous,root/'archive')
            self.assertEqual(current.read_bytes(),original)
            self.assertEqual(current.stat().st_ino,inode)

    def test_rejects_invalid_candidate_without_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            original = current.read_bytes()
            with duckdb.connect() as con:
                con.execute("COPY (SELECT TIMESTAMP '2025-01-01 12:00:00' acceptanceDateTime) TO ? (FORMAT PARQUET)",[str(candidate)])
            with self.assertRaisesRegex(ValueError,'changes current columns'):
                publish(candidate,current,previous,root/'archive')
            self.assertEqual(current.read_bytes(),original)
            self.assertFalse(previous.exists())

    def test_shorter_candidate_truncates_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            with duckdb.connect() as con:
                con.execute("COPY (SELECT TIMESTAMPTZ '2025-01-01 12:00:00+00' acceptanceDateTime FROM range(10000)) TO ? (FORMAT PARQUET)", [str(current)])
            self.write(candidate,'2025-01-01 13:00:00+00')
            self.assertGreater(current.stat().st_size, candidate.stat().st_size)
            publish(candidate,current,previous,root/'archive')
            self.assertEqual(current.read_bytes(), candidate.read_bytes())

    def test_failed_digest_restores_current(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            self.write(candidate,'2025-01-01 13:00:00+00')
            original = current.read_bytes()
            with patch('publish_filings.digest',side_effect=[b'candidate',b'wrong bytes']):
                with self.assertRaisesRegex(OSError,'do not match'):
                    publish(candidate,current,previous,root/'archive')
            self.assertEqual(current.read_bytes(),original)
            self.assertEqual(previous.read_bytes(),original)

    def test_rejects_empty_candidate_without_rotation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            original = current.read_bytes()
            with duckdb.connect() as con:
                con.execute('COPY (SELECT NULL::TIMESTAMPTZ acceptanceDateTime WHERE false) TO ? (FORMAT PARQUET)', [str(candidate)])
            with self.assertRaisesRegex(ValueError,'empty'):
                publish(candidate,current,previous,root/'archive')
            self.assertEqual(current.read_bytes(), original)
            self.assertFalse(previous.exists())

    def test_rejects_linked_release_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            current, candidate, previous = [root/n for n in ('filings.parquet','candidate.parquet','filings_previous.parquet')]
            self.write(current,'2025-01-01 12:00:00+00')
            candidate.hardlink_to(current)
            with self.assertRaisesRegex(ValueError,'same file'):
                publish(candidate,current,previous,root/'archive')
            self.assertFalse(previous.exists())


if __name__ == '__main__':
    unittest.main()
