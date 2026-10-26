from datetime import datetime,timezone
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import duckdb

from audit_filings import OBS_SCHEMA,audit,freeze
from benchmark_sgml_block_sampling import fetch_sgml
from download_submissions import download
from process_filings import process
import test_timestamp_bootstrap


class Response(io.BytesIO):
    status=200
    def __init__(self,body):
        super().__init__(body)
        self.headers={'Content-Length':str(len(body))}


class RunTests(unittest.TestCase):
    def test_download_manifest_and_refusal(self):
        body=io.BytesIO()
        with zipfile.ZipFile(body,'w') as archive:
            archive.writestr('CIK0000000001.json','{}')
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'submissions.zip'
            with patch('download_submissions.urllib.request.urlopen',return_value=Response(body.getvalue())):
                download(output)
            self.assertEqual(output.read_bytes(),body.getvalue())
            self.assertTrue(output.with_suffix('.manifest.parquet').exists())
            with self.assertRaises(FileExistsError):
                download(output)

    def test_missing_sgml_retains_successful_response(self):
        body=b'<SEC-HEADER>\n<ACCEPTANCE-DATETIME>\n<FILING-DATE>20090518\n</SEC-HEADER>'
        with patch('benchmark_sgml_block_sampling.urllib.request.urlopen',return_value=Response(body)):
            result=fetch_sgml(1,'a','test agent')
        self.assertEqual(result['status'],200)
        self.assertEqual(result['text'],body.decode('latin-1'))
        self.assertIsNotNone(result['digest'])
        self.assertIsNone(result['acceptance'])

    def test_sgml_timestamp_can_follow_newline(self):
        body=b'<SEC-HEADER>\n<ACCEPTANCE-DATETIME>\n20260930123456\n</SEC-HEADER>'
        with patch('benchmark_sgml_block_sampling.urllib.request.urlopen',return_value=Response(body)):
            self.assertEqual(fetch_sgml(1,'a','test agent')['acceptance'],datetime(2026,9,30,12,34,56))

    def test_random_sample_is_reproducible_and_audit_does_not_repair(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with duckdb.connect() as con:
                raw,prior=test_timestamp_bootstrap.BootstrapTests().fixture(con,root)
            candidate=root/'filings.parquet'
            process(raw,prior,candidate)
            original=candidate.read_bytes()
            samples=[]
            for number in (1,2):
                output=root/f'sample-{number}'
                output.mkdir()
                with duckdb.connect() as con:
                    con.execute('SET threads=1')
                    freeze(con,candidate,output,6,42)
                    samples.append(con.execute('SELECT sample_row FROM sample ORDER BY sample_row').fetchall())
            self.assertEqual(samples[0],samples[1])
            cache=root/'sgml.parquet'
            with duckdb.connect() as con:
                con.execute(f'CREATE TABLE cache({OBS_SCHEMA})')
                con.execute("""INSERT INTO cache VALUES
                    ('same',1,'2025-01-01 12:00:00','url',now(),0,200,'hash','header',NULL,'cache'),
                    ('summer',3,'2025-07-01 12:00:00','url',now(),0,200,'hash','header',NULL,'cache')""")
                con.execute('COPY cache TO ? (FORMAT PARQUET)',[str(cache)])
            failed=dict(acceptance=None,url='url',retrieved_at=datetime.now(timezone.utc),elapsed_ms=0,
                        status=200,digest='hash',text='<SEC-HEADER>',error='ValueError: ACCEPTANCE-DATETIME tag not found')
            with patch('audit_filings.fetch_sgml',return_value=failed):
                audit(candidate,root/'audit',n=12,seed=7,cache=cache,rate=1000)
            with duckdb.connect() as con:
                self.assertEqual(con.execute('SELECT sampled_rows,verified_rows,errors,unavailable_rows FROM read_parquet(?)',[str(root/'audit'/'summary.parquet')]).fetchone(),(12,3,0,9))
            self.assertEqual(original,candidate.read_bytes())


if __name__=='__main__':
    unittest.main()
