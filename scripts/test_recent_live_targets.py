import unittest
from datetime import date

import duckdb

from build_recent_live_targets import select_targets


class RecentTargetTests(unittest.TestCase):
    def test_selection_needs_no_reference_columns(self):
        with duckdb.connect() as c:
            c.execute("ATTACH ':memory:' AS workflow; ATTACH ':memory:' AS evidence")
            c.execute('''CREATE TABLE workflow.comparison (
                cik BIGINT,accessionNumber VARCHAR,source_file VARCHAR,form VARCHAR,
                raw_clock TIMESTAMP,corrected_instant TIMESTAMPTZ)''')
            c.execute("""INSERT INTO workflow.comparison VALUES
                (1,'new','a','10-K','2024-01-01',NULL),
                (1,'old','a','10-K','2023-12-31',NULL),
                (2,'known','b','10-K','2025-01-01',NULL),
                (3,'fixed','c','10-K','2025-01-01','2025-01-01 05:00:00+00'),
                (4,'letter','d','CORRESP','2025-01-01',NULL)""")
            c.execute('CREATE TABLE evidence.live_json_timestamp_observations(accession_number VARCHAR)')
            c.execute("INSERT INTO evidence.live_json_timestamp_observations VALUES ('known')")
            select_targets(c,date(2024,1,1))
            self.assertEqual(c.execute('SELECT accessionNumber FROM candidate_rows ORDER BY 1').fetchall(),[('letter',),('new',)])


if __name__=='__main__':
    unittest.main()
