import unittest
from datetime import datetime, timezone

import duckdb

from replay_timestamp_collections import replay


class ReplayTests(unittest.TestCase):
    def test_selected_blocks_include_effect_and_measure_lost_support(self):
        self.check_plan(None)

    def test_inherited_cache_restores_unselected_block_evidence(self):
        self.check_plan(datetime(2026,9,8,tzinfo=timezone.utc))

    def check_plan(self, inherited_before):
        with duckdb.connect() as c:
            c.execute("SET TimeZone='UTC'")
            for alias in ('b','old','e','q'):
                c.execute(f"ATTACH ':memory:' AS {alias}")
            c.execute('''CREATE TABLE b.comparison(cik BIGINT,accessionNumber VARCHAR,
                source_file VARCHAR,form VARCHAR,raw_clock TIMESTAMP,corrected_instant TIMESTAMPTZ)''')
            c.execute("""INSERT INTO b.comparison VALUES
                (1,'a','CIK0000000001.json','EFFECT','2025-01-01 12:00:00',NULL),
                (2,'b','CIK0000000002.json','10-K','2025-01-01 12:00:00',NULL)""")
            c.execute('CREATE TABLE old.comparison AS SELECT *,raw_clock AT TIME ZONE \'UTC\' prospective_instant FROM b.comparison')
            c.execute("UPDATE old.comparison SET corrected_instant=TIMESTAMPTZ '2025-01-01 12:00:00+00'")
            c.execute('CREATE TABLE b.accession_timestamp_overrides(accessionNumber VARCHAR,corrected_instant TIMESTAMPTZ)')
            c.execute('CREATE TABLE e.live_json_timestamp_observations(source_url VARCHAR,accession_number VARCHAR,acceptance_datetime_text VARCHAR,retrieved_at TIMESTAMPTZ)')
            c.execute("""INSERT INTO e.live_json_timestamp_observations VALUES
                ('https://data.sec.gov/submissions/CIK0000000001.json','a','2025-01-01T07:00:00Z',now()),
                ('https://data.sec.gov/submissions/CIK0000000002.json','b','2025-01-01T07:00:00Z','2026-09-07 20:00:00+00')""")
            c.execute('CREATE TABLE plans(stage VARCHAR,source_file VARCHAR)')
            c.execute("INSERT INTO plans VALUES ('7','CIK0000000001.json'),('5','CIK0000000002.json')")
            c.execute('CREATE TABLE fixed_sgml(accession_number VARCHAR,instant TIMESTAMPTZ)')
            c.execute('CREATE TABLE q.sgml_queue(accession_number VARCHAR)')
            replay(c,['7'],inherited_before)
            expected=(2,2,0,0) if inherited_before else (2,1,1,1)
            self.assertEqual(c.execute('SELECT rows_n,supported_rows,lost_support_rows,lost_shift_rows FROM metrics').fetchone(),expected)
            self.assertEqual(c.execute('SELECT target_blocks,unique_json_urls_lower_bound FROM fetch_metrics').fetchone(),(1,2 if inherited_before else 1))


if __name__=='__main__':
    unittest.main()
