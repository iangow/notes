from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import duckdb

from materialize_corrected_filings import materialize_workflow


class WorkflowMaterializationTests(unittest.TestCase):
    def test_exact_instants_and_explicit_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            raw=root/'raw.parquet'
            db=root/'workflow.duckdb'
            output=root/'result.parquet'
            with duckdb.connect(str(db)) as c:
                c.execute("""CREATE TABLE raw AS SELECT * FROM (VALUES
                    (1,'a','2025-07-01T12:00:00Z'),
                    (2,'a','2025-07-01T16:00:00Z'),
                    (3,'b','2025-07-01T08:00:00Z'),
                    (4,'c',NULL)) r(cik,accessionNumber,acceptanceDateTime)""")
                c.execute('COPY raw TO ? (FORMAT PARQUET)',[str(raw)])
                c.execute('CREATE TABLE inputs(role VARCHAR,size_bytes BIGINT,mtime_ns BIGINT)')
                c.execute("INSERT INTO inputs VALUES ('current',?,?)",[raw.stat().st_size,raw.stat().st_mtime_ns])
                c.execute('CREATE TABLE resolved_accessions(accession_number VARCHAR PRIMARY KEY,corrected_instant TIMESTAMPTZ,provenance VARCHAR)')
                c.execute("INSERT INTO resolved_accessions VALUES ('a','2025-07-01 16:00:00+00','snapshot_pair')")
            args=SimpleNamespace(workflow_database=db,threads=1,memory_limit='512MB',limit=None,allow_unresolved=False)
            with self.assertRaisesRegex(ValueError,'unresolved rows'):
                materialize_workflow(args,raw,output)
            args.allow_unresolved=True
            materialize_workflow(args,raw,output)
            with duckdb.connect() as c:
                c.execute("SET TimeZone='UTC'")
                result=c.execute('SELECT accessionNumber,hour(acceptanceDateTime),timestamp_provenance FROM read_parquet(?) ORDER BY cik',[str(output)]).fetchall()
                self.assertEqual(result,[('a',16,'snapshot_pair'),('a',16,'snapshot_pair'),('b',12,'unresolved_raw_as_eastern'),('c',None,'raw_missing')])


if __name__=='__main__':
    unittest.main()
