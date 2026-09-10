import unittest

import duckdb

from build_effect_live_targets import select_targets


class EffectTargetTests(unittest.TestCase):
    def test_union_targets_and_cached_accessions(self):
        with duckdb.connect() as c:
            for alias in ('step5','step7','workflow','evidence'):
                c.execute(f"ATTACH ':memory:' AS {alias}")
            for alias in ('step5','step7'):
                c.execute(f'CREATE TABLE {alias}.target_blocks(source_file VARCHAR)')
            c.execute("INSERT INTO step5.target_blocks VALUES ('a')")
            c.execute("INSERT INTO step7.target_blocks VALUES ('a'),('b')")
            c.execute('''CREATE TABLE workflow.comparison(cik BIGINT,accessionNumber VARCHAR,
                source_file VARCHAR,form VARCHAR,raw_clock TIMESTAMP)''')
            c.execute("""INSERT INTO workflow.comparison VALUES
                (1,'new','a','EFFECT','2025-01-01'),
                (1,'cached','a','EFFECT','2025-01-01'),
                (2,'second','b','EFFECT','2025-01-01'),
                (3,'outside','c','EFFECT','2025-01-01'),
                (1,'regular','a','10-K','2025-01-01')""")
            c.execute('CREATE TABLE evidence.live_json_timestamp_observations(accession_number VARCHAR)')
            c.execute("INSERT INTO evidence.live_json_timestamp_observations VALUES ('cached')")
            select_targets(c)
            self.assertEqual(c.execute('SELECT accessionNumber FROM candidate_rows ORDER BY 1').fetchall(),[('new',),('second',)])
            self.assertEqual(c.execute('SELECT count(*) FROM target_blocks').fetchone()[0],2)


if __name__=='__main__':
    unittest.main()
