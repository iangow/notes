#!/usr/bin/env python3
"""Encode the trusted 2024 raw clocks as an explicit Eastern reference."""

import argparse
from pathlib import Path

import duckdb


def make_previous(raw, output):
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix('.partial.parquet')
    if temporary.exists():
        raise FileExistsError(temporary)
    with duckdb.connect() as con:
        con.execute("SET TimeZone='UTC'; SET threads=4; SET memory_limit='2GB'")
        schema = dict((r[0],r[1]) for r in con.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(raw)]).fetchall())
        if schema.get('acceptanceDateTime') != 'VARCHAR':
            raise ValueError('Reference input must preserve the original timestamp text')
        con.execute('''CREATE TEMP TABLE previous AS
            SELECT * REPLACE(try_cast(acceptanceDateTime AS TIMESTAMP) AT TIME ZONE 'America/New_York' AS acceptanceDateTime),
                CASE WHEN try_cast(acceptanceDateTime AS TIMESTAMP) IS NULL THEN 'raw_missing'
                     WHEN CAST(try_cast(acceptanceDateTime AS TIMESTAMP) AS TIME)=TIME '00:00:00'
                     THEN 'historical_midnight_unverified' ELSE 'trusted_snapshot_eastern' END timestamp_provenance,
                accessionNumber timestamp_reference_id
            FROM read_parquet(?)''',[str(raw)])
        con.execute('COPY previous TO ? (FORMAT PARQUET,COMPRESSION ZSTD)',[str(temporary)])
        print('2024 reference:',con.execute('SELECT timestamp_provenance,count(*) FROM previous GROUP BY 1').fetchall(),flush=True)
    temporary.rename(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    make_previous(args.raw.expanduser().resolve(),args.output.expanduser().resolve())


if __name__ == '__main__':
    main()
