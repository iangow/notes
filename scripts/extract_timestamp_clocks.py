#!/usr/bin/env python3
"""Extract an unconverted four-column projection of every filing in a ZIP."""

import argparse
import json
from pathlib import Path
import time
import zipfile

import pyarrow as pa
import pyarrow.parquet as pq

from extract_filings import _recent_filings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('zip', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    temporary = args.output.with_suffix('.partial.parquet')
    schema = pa.schema([('cik',pa.int64()),('accessionNumber',pa.string()),
                        ('acceptanceDateTime',pa.string()),('source_file',pa.string())])
    batches = []
    buffered = total = 0
    started = time.monotonic()
    with zipfile.ZipFile(args.zip) as archive, pq.ParquetWriter(temporary,schema,compression='zstd') as writer:
        names = sorted(n for n in archive.namelist() if n.startswith('CIK') and n.endswith('.json'))
        for index,name in enumerate(names,1):
            data = json.loads(archive.read(name))
            cik = int(data.get('cik') or name[3:13])
            rows = _recent_filings(data)
            count = max((len(v) for v in rows.values()),default=0)
            if count:
                arrays = []
                for values,field in zip(([cik]*count,rows.get('accessionNumber',[]),
                                         rows.get('acceptanceDateTime',[]),[name]*count),schema):
                    arrays.append(pa.array(values+[None]*(count-len(values)),type=field.type))
                batches.append(pa.RecordBatch.from_arrays(arrays,schema=schema))
                buffered += count
                total += count
            if buffered>=100_000:
                writer.write_table(pa.Table.from_batches(batches,schema=schema))
                batches=[]
                buffered=0
            if index%100_000==0:
                print(f'{index:,}/{len(names):,} files; {total:,} rows; {time.monotonic()-started:.1f}s',flush=True)
        if batches:
            writer.write_table(pa.Table.from_batches(batches,schema=schema))
    temporary.rename(args.output)
    print(f'Wrote {args.output}: {total:,} rows in {time.monotonic()-started:.1f}s')


if __name__=='__main__':
    main()
