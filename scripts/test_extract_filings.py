"""Synthetic archive tests; no SEC downloads or production data writes."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import duckdb
import extract_filings as e


class ExtractionTests(unittest.TestCase):
    def test_tables_and_interrupted_resume(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.zip', root / 'expanded.parquet'
            with zipfile.ZipFile(source, 'w') as z:
                z.writestr('CIK0000000001.json', json.dumps({
                    'cik': '0000000001', 'sic': '0123', 'ein': '001234567',
                    'ownerOrg': {'unexpected': 'retained'},
                    'tickers': ['AAA', 'BBB'], 'exchanges': ['NYSE'],
                    'addresses': {'business': {'zipCode': '00123'}, 'mailing': None},
                    'formerNames': [{'name': 'Old', 'from': '2000-01-01T00:00:00Z'}],
                    'filings': {'recent': {'accessionNumber': ['a'],
                        'filingDate': ['2024-07-01'], 'reportDate': [''],
                        'acceptanceDateTime': ['2024-07-01T12:34:56.123Z'],
                        'size': [123], 'isXBRL': [1]},
                        'files': [{'name': 'CIK0000000001-submissions-001.json'},
                                  {'name': 'missing.json'}]}}))
                z.writestr('CIK0000000001-submissions-001.json', json.dumps({
                    'accessionNumber': ['b'], 'newField': ['001'], 'form': []}))
                z.writestr('CIK0000000002.json', json.dumps({
                    'cik': 2, 'laterField': '0004', 'filings': {'recent': {}}}))
            self.assertFalse(e.extract(source, output, max_seconds=1e-12))
            # Simulate uncheckpointed writes left by an interruption.
            stage = output.with_suffix('.staging')
            with (stage / 'filings.jsonl').open('ab') as f:
                f.write(b'bad trailing bytes\n')
            self.assertTrue(e.extract(source, output, max_seconds=0))
            with duckdb.connect() as con:
                rows = con.execute('SELECT cik, accessionNumber, newField FROM read_parquet(?) ORDER BY accessionNumber', [str(output)]).fetchall()
                self.assertEqual(rows, [(1, 'a', None), (1, 'b', '001')])
                raw, report, flag = con.execute("SELECT acceptanceDateTime, reportDate, isXBRL FROM read_parquet(?) WHERE accessionNumber='a'", [str(output)]).fetchone()
                self.assertEqual(raw, '2024-07-01T12:34:56.123Z')
                self.assertIsNone(report)
                self.assertTrue(flag)
                paths = e.output_paths(output)
                self.assertEqual(con.execute('SELECT ticker, exchange FROM read_parquet(?)', [str(paths['tickers'])]).fetchall(), [('AAA', 'NYSE'), ('BBB', None)])
                self.assertEqual(con.execute('SELECT available FROM read_parquet(?)', [str(paths['files'])]).fetchall(), [(True,), (False,)])
                self.assertEqual(con.execute('SELECT laterField FROM read_parquet(?) WHERE cik=2', [str(paths['companies'])]).fetchone(), ('0004',))
            self.assertFalse(stage.exists())
            with self.assertRaises(FileExistsError):
                e.extract(source, output)
            with self.assertRaises(ValueError):
                e.extract(source, root / 'filings.parquet')

    def test_changed_archive_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'source.zip', root / 'expanded.parquet'
            with zipfile.ZipFile(source, 'w') as z:
                for cik in (1, 2):
                    z.writestr(f'CIK{cik:010d}.json', json.dumps({
                        'cik': cik, 'filings': {'recent': {}}}))
            self.assertFalse(e.extract(source, output, 1e-12))
            with zipfile.ZipFile(source, 'a') as z:
                z.writestr('extra.txt', 'different archive')
            with self.assertRaisesRegex(ValueError, 'different ZIP/schema'):
                e.extract(source, output, 0)

    def test_empty_tables_and_conversion_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, output = root / 'empty.zip', root / 'expanded.parquet'
            with zipfile.ZipFile(source, 'w'):
                pass
            with patch.object(e, '_to_parquet', side_effect=RuntimeError('conversion failed')):
                with self.assertRaises(RuntimeError):
                    e.extract(source, output, 0)
            self.assertTrue(e.extract(source, output, 0))
            for path in e.output_paths(output).values():
                with duckdb.connect() as con:
                    self.assertEqual(con.execute('SELECT count(*) FROM read_parquet(?)', [str(path)]).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
