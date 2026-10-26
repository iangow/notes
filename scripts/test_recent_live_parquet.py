from datetime import date
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import duckdb

from benchmark_recent_live_json import benchmark, select


class RecentLiveParquetTests(unittest.TestCase):
    def fixture(self, con, root):
        con.execute('''CREATE TABLE candidate(cik BIGINT,accessionNumber VARCHAR,
            source_file VARCHAR,form VARCHAR,acceptanceDateTime TIMESTAMPTZ,
            timestamp_provenance VARCHAR);
            INSERT INTO candidate VALUES
            (1,'anchor','CIK0000000001.json','10-K','2024-01-01 17:00:00+00','trusted_snapshot_eastern'),
            (1,'new','CIK0000000001.json','EFFECT','2026-01-01 17:00:00+00','unresolved_raw_as_eastern'),
            (2,'old','CIK0000000002.json','4','2001-01-01 17:00:00+00','unresolved_raw_as_eastern');
            CREATE TABLE raw AS SELECT * EXCLUDE(timestamp_provenance)
                REPLACE('2024-01-01T12:00:00Z' AS acceptanceDateTime)
                FROM candidate WHERE accessionNumber='anchor'
            UNION ALL SELECT * EXCLUDE(timestamp_provenance)
                REPLACE('2026-01-01T12:00:00Z' AS acceptanceDateTime)
                FROM candidate WHERE accessionNumber='new'
            UNION ALL SELECT * EXCLUDE(timestamp_provenance)
                REPLACE('2001-01-01T12:00:00Z' AS acceptanceDateTime)
                FROM candidate WHERE accessionNumber='old';
        ''')
        filings, raw = root/'filings.parquet',root/'raw.parquet'
        con.execute('COPY candidate TO ? (FORMAT PARQUET)', [str(filings)])
        con.execute('COPY raw TO ? (FORMAT PARQUET)', [str(raw)])
        return filings, raw

    def test_queue_is_recent_unresolved_all_forms_and_compares_full_block(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            root = Path(directory)
            filings, raw = self.fixture(con, root)
            output = root/'trial'
            output.mkdir()
            self.assertEqual(select(con,filings,raw,output,date(2024,1,1),200,1),(1,1))
            self.assertEqual(con.execute('SELECT accessionNumber FROM candidate_rows').fetchall(), [('new',)])
            self.assertEqual(con.execute('SELECT accession_number FROM comparison_rows ORDER BY 1').fetchall(),
                             [('anchor',),('new',)])

    def test_trial_saves_observations_and_infers_from_independent_anchor(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with duckdb.connect() as con:
                filings, raw = self.fixture(con, root)
            original = filings.read_bytes(),raw.read_bytes()

            def fake(item, limiter, follow_history):
                self.assertTrue(follow_history)
                limiter.wait()
                block, rows = item
                live = {'anchor':'2024-01-01T17:00:00Z','new':'2026-01-01T12:00:00Z'}
                matches = [(cik,a,clock,live[a],'https://data.sec.gov/submissions/'+block)
                           for cik,a,clock in rows]
                return matches,(block,len(matches),0,None)

            output = root/'trial'
            with patch('benchmark_recent_live_json.fetch_block',side_effect=fake):
                benchmark(filings,raw,output,sample_blocks=1,rate=1000)
            self.assertEqual(original,(filings.read_bytes(),raw.read_bytes()))
            self.assertFalse(any(output.glob('*.duckdb')))
            with duckdb.connect() as con:
                self.assertEqual(con.execute('SELECT requests,failed_blocks,newly_supported_rows FROM read_parquet(?)',
                    [str(output/'summary.parquet')]).fetchone(),(1,0,1))
                self.assertEqual(con.execute('SELECT interpretation FROM read_parquet(?)',
                    [str(output/'file_rules.parquet')]).fetchall(),[('utc',)])
            with self.assertRaises(FileExistsError):
                benchmark(filings,raw,output)

    def test_resume_reuses_frozen_selection_and_retries_one_failed_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with duckdb.connect() as con:
                filings, raw = self.fixture(con, root)
            output = root/'resume'
            calls = {'n': 0}

            def fail_then_succeed(item, limiter, follow_history):
                limiter.wait()
                calls['n'] += 1
                block, rows = item
                if calls['n'] == 1:
                    return [], (block,0,len(rows),'TimeoutError: timed out')
                live = {'anchor':'2024-01-01T17:00:00Z','new':'2026-01-01T12:00:00Z'}
                matches = [(cik,a,clock,live[a],'https://data.sec.gov/submissions/'+block)
                           for cik,a,clock in rows]
                return matches,(block,len(matches),0,None)

            with patch('benchmark_recent_live_json.fetch_block',side_effect=fail_then_succeed):
                benchmark(filings,raw,output,sample_blocks=1,rate=1000)
                first_sample = (output/'sampled_blocks.parquet').read_bytes()
                benchmark(filings,raw,output,sample_blocks=1,rate=1000,resume=True)
            self.assertEqual((output/'sampled_blocks.parquet').read_bytes(),first_sample)
            self.assertEqual(calls['n'],2)
            with duckdb.connect() as con:
                results = con.execute('SELECT count(*),count(*) FILTER(WHERE error IS NULL) FROM read_parquet(?)',
                    [str(output/'fetch_results.parquet')]).fetchone()
                self.assertEqual(results,(2,1))
                self.assertEqual(con.execute('SELECT requests,failed_blocks,newly_supported_rows FROM read_parquet(?)',
                    [str(output/'summary.parquet')]).fetchone(),(2,0,1))


if __name__ == '__main__':
    unittest.main()
