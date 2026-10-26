from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import duckdb

from bootstrap_timestamp_workflow import bootstrap
from acceptance_timestamp_db import initialize_database
from evaluate_timestamp_workflow import main as evaluate
from infer_live_file_timezones import main as infer_live
from materialize_corrected_filings import materialize_workflow


class BootstrapTests(unittest.TestCase):
    def fixture(self, con, root):
        raw, prior = root / 'raw.parquet', root / 'prior.parquet'
        con.execute("""
            CREATE TABLE raw(cik INTEGER,accessionNumber VARCHAR,source_file VARCHAR,
                             form VARCHAR,acceptanceDateTime VARCHAR);
            INSERT INTO raw VALUES
              (1,'same','new-file.json','4','2025-01-01T12:00:00Z'),
              (2,'same','other-file.json','4','2025-01-01T17:00:00Z'),
              (3,'summer','moved.json','CORRESP','2025-07-01T16:00:00Z'),
              (4,'fallback','a.json','4','2025-07-01T12:00:00Z'),
              (5,'duplicate','b.json','4','2025-07-01T12:00:00Z'),
              (6,'duplicate','c.json','4','2025-07-01T16:00:00Z'),
              (7,'conflict','d.json','4','2025-01-01T12:00:00Z'),
              (8,'wrong_winter','e.json','4','2025-01-01T16:00:00Z'),
              (9,'invalid','f.json','4','bad'),
              (10,'legacy','g.json','4','2025-01-01T12:00:00Z'),
              (11,'new','h.json','4','2026-01-01T12:00:00Z'),
              (12,'invalid_prior','i.json','4','2025-01-01T12:00:00Z');
            CREATE TABLE prior(accessionNumber VARCHAR,acceptanceDateTime TIMESTAMPTZ,
                               timestamp_provenance VARCHAR,timestamp_reference_id VARCHAR,
                               timestamp_interpretation VARCHAR);
            INSERT INTO prior VALUES
              ('same','2025-01-01 17:00:00+00','sgml','same','utc'),
              ('same','2025-01-01 17:00:00+00','live_file_inferred','same','eastern'),
              ('summer','2025-07-01 16:00:00+00','live_pair','summer','utc'),
              ('fallback','2025-07-01 16:00:00+00','unresolved_raw_as_eastern',NULL,'unresolved'),
              ('duplicate','2025-07-01 15:00:00+00','unresolved_raw_as_eastern',NULL,'unresolved'),
              ('conflict','2025-01-01 17:00:00+00','sgml','conflict','utc'),
              ('conflict','2025-01-01 18:00:00+00','live_pair','conflict','utc'),
              ('wrong_winter','2025-01-01 17:00:00+00','snapshot_pair','wrong_winter','eastern'),
              ('invalid','2025-01-01 17:00:00+00','sgml','invalid','utc'),
              ('legacy','2025-01-01 17:00:00+00','block_rule','legacy','utc'),
              ('invalid_prior',NULL,'sgml','invalid_prior','utc');
        """)
        con.execute('COPY raw TO ? (FORMAT PARQUET)', [str(raw)])
        con.execute('COPY prior TO ? (FORMAT PARQUET)', [str(prior)])
        return raw, prior

    def test_inheritance_duplicates_and_quarantine(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            raw, prior = self.fixture(con, Path(directory))
            bootstrap(con, raw, prior)
            self.assertEqual(con.execute('SELECT accessionNumber,evidence,provenance FROM accession_timestamp_overrides ORDER BY 1').fetchall(),
                             [('duplicate','cross_cik_pair','cross_cik_pair'),
                              ('same','prior_and_pair','sgml'),
                              ('summer','prior_only','live_pair')])
            rejected = dict(con.execute('SELECT accessionNumber,reason FROM bootstrap_rejections').fetchall())
            self.assertEqual(set(rejected), {'conflict','wrong_winter','invalid','invalid_prior'})
            self.assertEqual(con.execute("SELECT inherited_provenances FROM inherited_overrides WHERE accessionNumber='same'").fetchone()[0],
                             ['live_file_inferred','sgml'])
            self.assertEqual(con.execute("SELECT reference_found FROM comparison WHERE accessionNumber='new'").fetchone(), (False,))

    def test_prior_fallback_clock_can_form_new_pair_but_not_be_inherited(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            root = Path(directory)
            raw, prior = self.fixture(con, root)
            con.execute("UPDATE raw SET acceptanceDateTime='2025-07-01T16:00:00Z' WHERE accessionNumber='fallback'")
            con.execute('COPY raw TO ? (FORMAT PARQUET)', [str(raw)])
            bootstrap(con, raw, prior)
            row = con.execute("""
                SELECT evidence,provenance,corrected_instant
                FROM accession_timestamp_overrides WHERE accessionNumber='fallback'
            """).fetchone()
            self.assertEqual(row[:2], ('snapshot_pair','snapshot_pair'))
            self.assertEqual(row[2].hour, 16)
            self.assertEqual(row[2].minute, 0)
            self.assertEqual(con.execute("SELECT count(*) FROM inherited_overrides WHERE accessionNumber='fallback'").fetchone()[0], 0)
            self.assertEqual(con.execute("SELECT count(*) FROM old_groups WHERE accessionNumber='legacy'").fetchone()[0], 0)

    def test_materializer_and_next_update(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database, output = root/'workflow.duckdb', root/'result.parquet'
            with duckdb.connect(str(database)) as con:
                raw, prior = self.fixture(con, root)
                bootstrap(con, raw, prior)
            args = SimpleNamespace(workflow_database=database,threads=1,memory_limit='512MB',limit=None,allow_unresolved=True)
            materialize_workflow(args, raw, output)
            with duckdb.connect() as con:
                con.execute("SET TimeZone='UTC'")
                self.assertEqual(con.execute("SELECT DISTINCT acceptanceDateTime FROM read_parquet(?) WHERE accessionNumber='same'",[str(output)]).fetchone()[0].hour, 17)
                bootstrap(con, raw, output)
                self.assertEqual(con.execute("SELECT count(*) FROM inherited_overrides WHERE accessionNumber='fallback'").fetchone()[0], 0)
                self.assertEqual(con.execute('SELECT count(*) FROM resolved_accessions').fetchone()[0], 3)

    def test_requires_timezone_and_provenance(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            root = Path(directory)
            raw, prior = self.fixture(con, root)
            con.execute('COPY (SELECT accessionNumber,acceptanceDateTime::TIMESTAMP acceptanceDateTime,timestamp_provenance FROM prior) TO ? (FORMAT PARQUET)',[str(root/'naive.parquet')])
            with self.assertRaisesRegex(ValueError, 'TIMESTAMP WITH TIME ZONE'):
                bootstrap(con, raw, root/'naive.parquet')
            con.execute('COPY (SELECT accessionNumber,acceptanceDateTime FROM prior) TO ? (FORMAT PARQUET)',[str(root/'no_provenance.parquet')])
            with self.assertRaisesRegex(ValueError, 'timestamp_provenance'):
                bootstrap(con, raw, root/'no_provenance.parquet')

    def test_prior_disagrees_with_current_duplicate_pair(self):
        with tempfile.TemporaryDirectory() as directory, duckdb.connect() as con:
            root = Path(directory)
            raw, prior = self.fixture(con, root)
            con.execute("""DELETE FROM raw; DELETE FROM prior;
                INSERT INTO raw VALUES
                  (1,'pair','a.json','4','2025-01-01T12:00:00Z'),
                  (2,'pair','b.json','4','2025-01-01T17:00:00Z');
                INSERT INTO prior VALUES ('pair','2025-01-01 22:00:00+00','sgml','pair','utc');""")
            con.execute('COPY raw TO ? (FORMAT PARQUET)', [str(raw)])
            con.execute('COPY prior TO ? (FORMAT PARQUET)', [str(prior)])
            bootstrap(con, raw, prior)
            reasons = {r[0] for r in con.execute('SELECT reason FROM bootstrap_rejections').fetchall()}
            self.assertIn('prior_conflicts_with_duplicate_pair', reasons)
            self.assertEqual(con.execute('SELECT count(*) FROM resolved_accessions').fetchone()[0], 0)

    def test_existing_inference_and_freeze_keep_prior_provenance(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline, evidence, inference, queue, workflow = [root / (name+'.duckdb')
                for name in ('baseline','evidence','inference','queue','workflow')]
            with duckdb.connect(str(baseline)) as con:
                raw, prior = self.fixture(con, root)
                bootstrap(con, raw, prior)
            with duckdb.connect(str(evidence)) as con:
                initialize_database(con)
                con.execute("""INSERT INTO live_json_timestamp_observations
                    (source_url,accession_number,acceptance_datetime_text) VALUES
                    ('uniform','same','2025-01-01T12:00:00Z'),
                    ('uniform','new','2026-01-01T12:00:00Z'),
                    ('uniform','conflict','2025-01-01T12:00:00Z')""")
            with duckdb.connect(str(queue)) as con:
                con.execute('CREATE TABLE sgml_queue(accession_number VARCHAR)')
            arguments = ['script','--baseline',str(baseline),'--database',str(evidence)]
            with patch('sys.argv',arguments+['--output',str(inference)]):
                infer_live()
            with patch('sys.argv',arguments+['--live-inference',str(inference),
                        '--sgml-queue',str(queue),'--output',str(workflow)]):
                evaluate()
            with duckdb.connect(str(workflow),read_only=True) as con:
                self.assertEqual(con.execute("SELECT provenance FROM resolved_accessions WHERE accession_number='same'").fetchone(), ('sgml',))
                self.assertEqual(con.execute("SELECT provenance FROM resolved_accessions WHERE accession_number='new'").fetchone(), ('live_file_inferred',))
                self.assertEqual(con.execute("SELECT count(*) FROM resolved_accessions WHERE accession_number='conflict'").fetchone()[0], 0)
                self.assertGreater(con.execute('SELECT count(*) FROM bootstrap_rejections').fetchone()[0], 0)
                self.assertEqual(con.execute('SELECT count(*) FROM prior_release_evidence').fetchone()[0], 11)
            output = root/'updated.parquet'
            args = SimpleNamespace(workflow_database=workflow,threads=1,memory_limit='512MB',limit=None,allow_unresolved=True)
            materialize_workflow(args, raw, output)


if __name__ == '__main__':
    unittest.main()
