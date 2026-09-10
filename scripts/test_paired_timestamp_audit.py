import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import duckdb

from report_paired_timestamp_audit import summarize
from build_paired_timestamp_audit import main as build_sample


class PairedAuditTests(unittest.TestCase):
    def test_sample_freezes_predictions_without_sgml_database(self):
        with TemporaryDirectory() as directory:
            root=Path(directory)
            workflow=root/'workflow.duckdb'
            streamlined=root/'streamlined.duckdb'
            output=root/'sample.duckdb'
            with duckdb.connect(str(workflow)) as c:
                c.execute('''CREATE TABLE comparison AS SELECT i cik,CAST(i AS VARCHAR) accessionNumber,
                    'file' source_file,'10-K' form,
                    make_timestamp(CASE WHEN i<10 THEN 2000 WHEN i<20 THEN 2010
                         WHEN i<30 THEN 2020 ELSE 2025 END,1,1,12,0,0) raw_clock,
                    raw_clock AT TIME ZONE 'America/New_York' reference_instant,
                    reference_instant prospective_instant,NULL::VARCHAR provenance
                    FROM range(40) t(i)''')
            with duckdb.connect(str(streamlined)) as c:
                c.execute('CREATE TABLE resolved(accession_number VARCHAR,instant TIMESTAMPTZ)')
            with patch('build_paired_timestamp_audit.PERIOD_SIZES',{0:5,1:5,2:5,3:5}),patch(
                    'sys.argv',['build','--workflow-database',str(workflow),
                    '--streamlined-database',str(streamlined),'--output',str(output)]):
                build_sample()
            with duckdb.connect(str(output)) as c:
                self.assertEqual(c.execute('SELECT count(*),sum(sampling_weight) FROM candidate_rows').fetchone(),(20,40.0))
                self.assertEqual(c.execute('SELECT count(*) FROM versions').fetchone()[0],3)

    def test_weighted_errors_and_unverifiable_rows(self):
        with duckdb.connect() as c:
            c.execute('''CREATE TABLE outcomes(period INTEGER,midnight BOOLEAN,form_group VARCHAR,
                method VARCHAR,version_disagreement BOOLEAN,sampling_weight DOUBLE,
                monday_instant TIMESTAMPTZ,last_night_instant TIMESTAMPTZ,
                streamlined_instant TIMESTAMPTZ,sgml_instant TIMESTAMPTZ,verifiable BOOLEAN)''')
            c.execute("""INSERT INTO outcomes VALUES
                (3,false,'other','fallback',true,10,'2025-01-01 12:00:00+00','2025-01-01 17:00:00+00',
                 '2025-01-01 17:00:00+00','2025-01-01 17:00:00+00',true),
                (0,true,'other','fallback',false,90,'2000-01-01 05:00:00+00','2000-01-01 05:00:00+00',
                 '2000-01-01 05:00:00+00',NULL,false)""")
            summarize(c)
            self.assertEqual(c.execute("SELECT errors,error_percent_among_verifiable,unverifiable_percent,whole_population_error_lower,whole_population_error_upper FROM summary WHERE model='monday'").fetchone(),(1,100.0,90.0,10.0,100.0))
            self.assertEqual(c.execute("SELECT errors,error_percent_among_verifiable FROM summary WHERE model='last_night'").fetchone(),(0,0.0))


if __name__=='__main__':
    unittest.main()
