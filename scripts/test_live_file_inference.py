import unittest

import duckdb

from infer_live_file_timezones import infer


class FileInferenceTests(unittest.TestCase):
    def test_uniform_file_and_conflicts(self):
        with duckdb.connect() as c:
            c.execute("SET TimeZone='UTC'")
            c.execute('CREATE TABLE anchor_inputs(accession VARCHAR,instant TIMESTAMPTZ)')
            c.execute("INSERT INTO anchor_inputs VALUES ('a','2025-01-01 17:00:00+00'),('b','2025-01-01 18:00:00+00')")
            c.execute('CREATE TABLE validation AS SELECT * FROM anchor_inputs')
            c.execute("INSERT INTO validation VALUES ('conflict','2025-01-01 20:00:00+00')")
            c.execute('CREATE TABLE live(source_url VARCHAR,accession_number VARCHAR,acceptance_datetime_text VARCHAR,retrieved_at TIMESTAMPTZ)')
            c.execute("""INSERT INTO live VALUES
                ('uniform','a','2025-01-01T12:00:00Z',now()),
                ('uniform','new','2025-07-01T12:00:00Z',now()),
                ('uniform','conflict','2025-01-01T12:00:00Z',now()),
                ('mixed','a','2025-01-01T12:00:00Z',now()),
                ('mixed','b','2025-01-01T18:00:00Z',now()),
                ('unknown','unanchored','2025-01-01T12:00:00Z',now())""")
            infer(c)
            self.assertEqual(c.execute('SELECT source_url,interpretation FROM file_rules').fetchall(),[('uniform','eastern')])
            self.assertEqual(c.execute("SELECT hour(instant) FROM inferred_overrides WHERE accession_number='new'").fetchone()[0],16)
            self.assertEqual(c.execute('SELECT * FROM rejected_accessions').fetchall(),[('conflict',)])
            self.assertEqual(c.execute("SELECT count(*) FROM inferred_overrides WHERE accession_number='unanchored'").fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
