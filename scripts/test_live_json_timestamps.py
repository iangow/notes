import unittest

import duckdb

from acceptance_timestamp_db import initialize_database
from compare_live_json_timestamps import compare_clocks


class LiveClockTests(unittest.TestCase):
    def test_conversion_directions_and_daylight_saving(self):
        with duckdb.connect() as con:
            con.execute('CREATE TABLE input_clocks(zip_text VARCHAR, live_text VARCHAR)')
            con.executemany('INSERT INTO input_clocks VALUES (?,?)', [
                ('2025-12-10T02:30:40Z', '2025-12-09T21:30:40Z'),
                ('2025-07-01T12:00:00Z', '2025-07-01T16:00:00Z'),
                ('2025-12-01T12:00:00Z', '2025-12-01T16:00:00Z'),
                ('2025-07-01T12:00:00Z', '2025-07-01T12:00:00Z'),
                ('bad', '2025-07-01T12:00:00Z'),
            ])
            compare_clocks(con)
            self.assertEqual(con.execute('SELECT status FROM comparisons').fetchall(),
                             [('zip_utc',), ('live_utc',), ('unexplained',),
                              ('unchanged',), ('invalid',)])

    def test_sgml_override_precedes_live(self):
        with duckdb.connect() as con:
            initialize_database(con)
            con.execute("""INSERT INTO live_json_timestamp_overrides VALUES
                ('a',1,TIMESTAMP '2025-01-01 12:00:00','utc',
                 TIMESTAMP '2025-01-01 17:00:00',TIMESTAMP '2025-01-01 12:00:00','url',now())""")
            self.assertEqual(con.execute('SELECT count(*) FROM effective_submission_overrides').fetchone()[0], 1)
            con.execute("""INSERT INTO submission_overrides
                (accession_number,cik,zip_acceptance_datetime,corrected_acceptance_datetime,
                 interpretation,evidence_source,reason) VALUES
                ('a',1,TIMESTAMP '2025-01-01 17:00:00',TIMESTAMP '2025-01-01 13:00:00',
                 'utc','sgml','test')""")
            self.assertEqual(con.execute('SELECT hour(corrected_acceptance_datetime) FROM effective_submission_overrides').fetchall(), [(13,)])


if __name__ == '__main__':
    unittest.main()
