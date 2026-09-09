import unittest

import duckdb

from analyze_timestamp_pair_baseline import build_overrides


class PairBaselineTests(unittest.TestCase):
    def test_snapshot_duplicates_and_non_evidence(self):
        with duckdb.connect() as con:
            for role in ('old','current'):
                con.execute(f'CREATE TABLE {role}_groups(accessionNumber VARCHAR,clocks TIMESTAMP[],invalid BIGINT,ciks BIGINT)')
            con.execute("""INSERT INTO old_groups VALUES
                ('cross',[TIMESTAMP '2024-01-01 12:00:00'],0,1),
                ('equal',[TIMESTAMP '2024-01-01 12:00:00'],0,1),
                ('wrong',[TIMESTAMP '2024-01-01 12:00:00'],0,1)""")
            con.execute("""INSERT INTO current_groups VALUES
                ('cross',[TIMESTAMP '2024-01-01 17:00:00'],0,1),
                ('equal',[TIMESTAMP '2024-01-01 12:00:00'],0,1),
                ('wrong',[TIMESTAMP '2024-01-01 16:00:00'],0,1),
                ('dup',[TIMESTAMP '2025-07-01 12:00:00',TIMESTAMP '2025-07-01 16:00:00'],0,2),
                ('same_cik',[TIMESTAMP '2025-07-01 12:00:00',TIMESTAMP '2025-07-01 16:00:00'],0,1),
                ('invalid',[TIMESTAMP '2025-07-01 12:00:00',TIMESTAMP '2025-07-01 16:00:00'],1,2)""")
            build_overrides(con)
            self.assertEqual(con.execute('SELECT accessionNumber,evidence FROM accession_timestamp_overrides ORDER BY 1').fetchall(),
                             [('cross','snapshot_only'),('dup','duplicates_only')])


if __name__=='__main__':
    unittest.main()
