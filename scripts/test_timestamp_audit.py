import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

import duckdb

from acceptance_timestamp_db import initialize_database
from build_timestamp_audit import allocate
from collect_queued_sgml import save


class AuditTests(unittest.TestCase):
    def test_allocation(self):
        populations={'a':2,'b':100,'c':1000}
        result=allocate(populations,300)
        self.assertEqual(sum(result.values()),300)
        self.assertEqual(result['a'],2)
        self.assertTrue(all(0<result[k]<=populations[k] for k in result))
        self.assertEqual(result,allocate(populations,300))

    def test_audit_does_not_promote_cached_evidence(self):
        with TemporaryDirectory() as directory:
            database=Path(directory)/'e.duckdb'
            queue=Path(directory)/'q.duckdb'
            with duckdb.connect(str(database)) as c:
                initialize_database(c)
            with duckdb.connect(str(queue)) as c:
                c.execute('CREATE TABLE sentinel(n INTEGER)')
            save(SimpleNamespace(database=database,queue=queue,audit_only=True),[],['a'])
            with duckdb.connect(str(database)) as c:
                self.assertEqual(c.execute('SELECT count(*) FROM submission_overrides').fetchone()[0],0)


if __name__=='__main__':
    unittest.main()
