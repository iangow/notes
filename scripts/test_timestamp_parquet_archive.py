import tempfile
from pathlib import Path
import unittest

import duckdb

from acceptance_timestamp_db import initialize_database
from timestamp_parquet_archive import export_snapshot, restore_snapshot


class ParquetArchiveTests(unittest.TestCase):
    def test_evidence_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / 'source.duckdb'
            with duckdb.connect(str(database)) as con:
                initialize_database(con)
                con.execute("""INSERT INTO sgml_observations VALUES
                    ('a', 1, '2025-06-02 13:15:00', 'https://example.org/a', now(),
                     10, 200, 'hash', '<ACCEPTANCE-DATETIME>20250602131500', NULL),
                    ('b', 2, NULL, 'https://example.org/b', now(), 20, NULL, NULL,
                     NULL, 'ValueError: ACCEPTANCE-DATETIME tag not found')""")
                con.execute('''CREATE TABLE accepted_timestamps (
                    accession_number VARCHAR PRIMARY KEY, instant TIMESTAMPTZ,
                    filing_date DATE, raw_clock VARCHAR, provenance VARCHAR,
                    tags VARCHAR[], header BLOB)''')
                con.execute("""INSERT INTO accepted_timestamps VALUES
                    ('a', '2025-06-02 13:15:00-04', '2025-06-02',
                     '2025-06-02T13:15:00.000Z', 'sgml', ['one', 'two'], 'abc')""")
                con.execute('CREATE UNIQUE INDEX accession_key ON accepted_timestamps(accession_number)')
                con.execute('CREATE VIEW z_base AS SELECT * FROM accepted_timestamps')
                con.execute('CREATE VIEW a_dependent AS SELECT * FROM z_base')
            archive = export_snapshot(database, root / 'archive')
            with duckdb.connect() as restored:
                restore_snapshot(archive, restored)
                restored.execute(f"ATTACH '{database}' AS original (READ_ONLY)")
                tables = restored.execute("SELECT table_name FROM duckdb_tables() WHERE database_name='original'").fetchall()
                for (name,) in tables:
                    self.assertEqual(restored.execute(f'''SELECT count(*) FROM (
                        (SELECT * FROM main."{name}" EXCEPT ALL SELECT * FROM original."{name}")
                        UNION ALL
                        (SELECT * FROM original."{name}" EXCEPT ALL SELECT * FROM main."{name}"))''').fetchone()[0], 0)
                self.assertEqual(restored.execute('SELECT count(*) FROM a_dependent').fetchone()[0], 1)
                self.assertEqual(restored.execute('SELECT count(*) FROM active_timestamp_rules').fetchone()[0], 0)
                with self.assertRaises(duckdb.ConstraintException):
                    restored.execute('INSERT INTO accepted_timestamps SELECT * FROM accepted_timestamps')
            with self.assertRaises(FileExistsError):
                export_snapshot(database, archive)

    def test_partial_export_and_corruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            database = root / 'source.duckdb'
            with duckdb.connect(str(database)) as con:
                con.execute('CREATE TABLE kept AS SELECT 1 AS n')
                con.execute('CREATE TABLE omitted AS SELECT 2 AS n')
                con.execute("CREATE TABLE metadata AS SELECT '9007199254740993'::HUGEINT AS n")
                con.execute('CREATE VIEW combined AS SELECT * FROM kept, omitted')
            with self.assertRaises(ValueError):
                export_snapshot(database, root / 'invalid', ['unknown'])
            self.assertFalse((root / 'invalid').exists())
            archive = export_snapshot(database, root / 'archive', ['kept', 'metadata'])
            with duckdb.connect() as con:
                restore_snapshot(archive, con)
                self.assertEqual(con.execute('SHOW TABLES').fetchall(), [('kept',), ('metadata',)])
                self.assertEqual(con.execute('SELECT n FROM metadata').fetchone()[0], 9007199254740993)
                with self.assertRaises(ValueError):
                    restore_snapshot(archive, con)
            with (archive / 'kept.parquet').open('ab') as stream:
                stream.write(b'corrupt')
            with duckdb.connect() as con, self.assertRaisesRegex(ValueError, 'Checksum mismatch'):
                restore_snapshot(archive, con)


if __name__ == '__main__':
    unittest.main()
