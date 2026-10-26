from pathlib import Path
import tempfile
import unittest

import duckdb

from make_previous_filings import make_previous
from process_filings import process
import test_timestamp_bootstrap


class ProcessTests(unittest.TestCase):
    def test_trusted_reference_does_not_promote_midnight(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            raw, previous = root/'raw.parquet',root/'filings_previous.parquet'
            with duckdb.connect() as con:
                con.execute('''CREATE TABLE raw(accessionNumber VARCHAR,acceptanceDateTime VARCHAR);
                    INSERT INTO raw VALUES ('winter','2024-01-01T12:00:00Z'),
                    ('summer','2024-07-01T12:00:00Z'),('midnight','2001-01-01T00:00:00Z'),('missing','bad')''')
                con.execute('COPY raw TO ? (FORMAT PARQUET)',[str(raw)])
            make_previous(raw,previous)
            with duckdb.connect() as con:
                con.execute("SET TimeZone='UTC'")
                rows=con.execute('SELECT accessionNumber,hour(acceptanceDateTime),timestamp_provenance FROM read_parquet(?) ORDER BY 1',[str(previous)]).fetchall()
                self.assertEqual(rows,[('midnight',5,'historical_midnight_unverified'),('missing',None,'raw_missing'),
                                       ('summer',16,'trusted_snapshot_eastern'),('winter',17,'trusted_snapshot_eastern')])

    def test_candidate_is_the_carry_forward_record(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with duckdb.connect() as con:
                raw,prior=test_timestamp_bootstrap.BootstrapTests().fixture(con,root)
            output=root/'filings.parquet'
            process(raw,prior,output)
            self.assertFalse(any(root.glob('*.duckdb')))
            self.assertFalse(any(root.glob('.timestamp-work-*')))
            self.assertTrue((root/'filings_checks'/'bootstrap_rejections.parquet').exists())
            second=root/'next.parquet'
            process(raw,output,second)
            with duckdb.connect() as con:
                self.assertEqual(con.execute("SELECT DISTINCT timestamp_provenance FROM read_parquet(?) WHERE accessionNumber='same'",[str(second)]).fetchall(),[('sgml',)])

    def test_parquet_cache_extends_file_inference(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cache=root/'cache'
            cache.mkdir()
            with duckdb.connect() as con:
                raw,prior=test_timestamp_bootstrap.BootstrapTests().fixture(con,root)
                con.execute('''CREATE TABLE live AS SELECT * FROM (VALUES
                    ('uniform','same','2025-01-01T12:00:00Z',now()),
                    ('uniform','new','2026-01-01T12:00:00Z',now()),
                    ('uniform','conflict','2025-01-01T12:00:00Z',now()))
                    l(source_url,accession_number,acceptance_datetime_text,retrieved_at)''')
                con.execute('COPY live TO ? (FORMAT PARQUET)',[str(cache/'live_json_timestamp_observations.parquet')])
            output=root/'filings.parquet'
            process(raw,prior,output,cache)
            with duckdb.connect() as con:
                rows=con.execute("SELECT accessionNumber,timestamp_provenance FROM read_parquet(?) WHERE accessionNumber IN ('new','conflict') ORDER BY 1",[str(output)]).fetchall()
                self.assertEqual(rows,[('conflict','unresolved_raw_as_eastern'),('new','live_file_inferred')])

    def test_changed_live_file_convention_is_separate_by_response_version(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            cache=root/'cache'
            cache.mkdir()
            with duckdb.connect() as con:
                raw,prior=test_timestamp_bootstrap.BootstrapTests().fixture(con,root)
                con.execute('''CREATE TABLE old_live AS SELECT * FROM (VALUES
                    ('uniform','same','2025-01-01T12:00:00Z','2026-09-01 00:00:00+00'::TIMESTAMPTZ))
                    l(source_url,accession_number,acceptance_datetime_text,retrieved_at);
                    CREATE TABLE fresh_live AS SELECT * FROM (VALUES
                    ('uniform','same','2025-01-01T17:00:00Z','2026-09-30 00:00:00+00'::TIMESTAMPTZ),
                    ('uniform','new','2026-01-01T12:00:00Z','2026-09-30 00:00:00+00'::TIMESTAMPTZ))
                    l(source_url,accession_number,acceptance_datetime_text,retrieved_at);''')
                con.execute('COPY old_live TO ? (FORMAT PARQUET)',[str(cache/'live_json_timestamp_observations.parquet')])
                fresh=root/'fresh.parquet'
                con.execute('COPY fresh_live TO ? (FORMAT PARQUET)',[str(fresh)])
            output=root/'filings.parquet'
            process(raw,prior,output,cache,live_sources=[fresh])
            with duckdb.connect() as con:
                con.execute("SET TimeZone='UTC'")
                self.assertEqual(con.execute("SELECT hour(acceptanceDateTime),timestamp_provenance FROM read_parquet(?) WHERE accessionNumber='new'",
                    [str(output)]).fetchone(),(12,'live_file_inferred'))
                self.assertEqual(con.execute('SELECT interpretation FROM read_parquet(?) ORDER BY observation_version',
                    [str(root/'filings_checks'/'file_rules.parquet')]).fetchall(),[('eastern',),('utc',)])

    def test_conflicting_extra_sgml_is_not_silently_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            with duckdb.connect() as con:
                raw,prior=test_timestamp_bootstrap.BootstrapTests().fixture(con,root)
                sgml=root/'sgml.parquet'
                con.execute('''COPY (SELECT * FROM (VALUES
                    ('new','2026-01-01 12:00:00'::TIMESTAMP,NULL::VARCHAR),
                    ('new','2026-01-01 13:00:00'::TIMESTAMP,NULL::VARCHAR))
                    s(accession_number,acceptance_datetime,error)) TO ? (FORMAT PARQUET)''',[str(sgml)])
            output=root/'filings.parquet'
            process(raw,prior,output,sgml_sources=[sgml])
            with duckdb.connect() as con:
                self.assertEqual(con.execute("SELECT timestamp_provenance FROM read_parquet(?) WHERE accessionNumber='new'",
                    [str(output)]).fetchone(),('unresolved_raw_as_eastern',))
                self.assertEqual(con.execute('SELECT accession_number,instant_count FROM read_parquet(?)',
                    [str(root/'filings_checks'/'evidence_disagreements.parquet')]).fetchall(),[('new',2)])


if __name__=='__main__':
    unittest.main()
