#!/usr/bin/env python3
"""Measure two accession-level clock-pair steps without production rules."""

import argparse
from pathlib import Path
import time

import duckdb


def build_overrides(con):
    con.execute("""
        CREATE OR REPLACE TABLE snapshot_pair_overrides AS
        WITH pairs AS (
          SELECT c.accessionNumber,
                 list_sort(list_distinct(list_concat(c.clocks,o.clocks))) clocks,
                 c.invalid+o.invalid invalid
          FROM current_groups c JOIN old_groups o USING(accessionNumber)
        )
        SELECT accessionNumber,clocks[1] AS eastern_clock,clocks[2] AS utc_clock,
               clocks[1] AT TIME ZONE 'America/New_York' AS corrected_instant
        FROM pairs WHERE len(clocks)=2 AND invalid=0
          AND (clocks[1] AT TIME ZONE 'America/New_York')=(clocks[2] AT TIME ZONE 'UTC');

        CREATE OR REPLACE TABLE current_duplicate_overrides AS
        SELECT accessionNumber,clocks[1] AS eastern_clock,clocks[2] AS utc_clock,
               clocks[1] AT TIME ZONE 'America/New_York' AS corrected_instant
        FROM current_groups WHERE len(clocks)=2 AND invalid=0 AND ciks>1
          AND (clocks[1] AT TIME ZONE 'America/New_York')=(clocks[2] AT TIME ZONE 'UTC');

        CREATE OR REPLACE TABLE pair_conflicts AS
        SELECT accessionNumber FROM (
          SELECT accessionNumber,corrected_instant FROM snapshot_pair_overrides
          UNION ALL
          SELECT accessionNumber,corrected_instant FROM current_duplicate_overrides
        ) GROUP BY accessionNumber HAVING count(DISTINCT corrected_instant)>1;

        CREATE OR REPLACE TABLE accession_timestamp_overrides AS
        SELECT coalesce(s.accessionNumber,d.accessionNumber) accessionNumber,
               coalesce(s.corrected_instant,d.corrected_instant) corrected_instant,
               CASE WHEN s.accessionNumber IS NOT NULL AND d.accessionNumber IS NOT NULL THEN 'both'
                    WHEN s.accessionNumber IS NOT NULL THEN 'snapshot_only'
                    ELSE 'duplicates_only' END evidence
        FROM snapshot_pair_overrides s FULL JOIN current_duplicate_overrides d USING(accessionNumber)
        WHERE coalesce(s.accessionNumber,d.accessionNumber) NOT IN (SELECT accessionNumber FROM pair_conflicts);
    """)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--old-raw',type=Path,required=True)
    parser.add_argument('--raw',type=Path,required=True)
    parser.add_argument('--reference',type=Path,required=True)
    parser.add_argument('--database',type=Path,required=True,
                        help='Separate analysis database, not the production evidence database.')
    args=parser.parse_args()
    if args.database.exists():
        raise FileExistsError('Use a new analysis database to preserve previous results')
    args.database.parent.mkdir(parents=True,exist_ok=True)
    started=time.monotonic()
    with duckdb.connect(str(args.database)) as con:
        con.execute("SET TimeZone='UTC'; SET memory_limit='4GB'; SET threads=4")
        con.execute('CREATE TABLE inputs(role VARCHAR,path VARCHAR,size_bytes BIGINT,mtime_ns BIGINT)')
        for role,path in [('old',args.old_raw),('current',args.raw),('reference',args.reference)]:
            stat=path.stat()
            con.execute('INSERT INTO inputs VALUES (?,?,?,?)',[role,str(path.resolve()),stat.st_size,stat.st_mtime_ns])
        for role,path in [('old',args.old_raw),('current',args.raw)]:
            dtype=con.execute('DESCRIBE SELECT acceptanceDateTime FROM read_parquet(?)',[str(path)]).fetchone()[1]
            if dtype!='VARCHAR':
                raise ValueError(f'{role} must preserve timestamp text, got {dtype}')
            if role=='current':
                con.execute("""CREATE TEMP TABLE current_rows AS
                    SELECT cik,accessionNumber,source_file,form,
                           try_cast(acceptanceDateTime AS TIMESTAMP) AS raw_clock
                    FROM read_parquet(?)""",[str(path)])
            con.execute(f"""
                CREATE TABLE {role}_groups AS
                SELECT accessionNumber,
                       list_sort(list(DISTINCT try_cast(acceptanceDateTime AS TIMESTAMP))
                         FILTER (WHERE try_cast(acceptanceDateTime AS TIMESTAMP) IS NOT NULL)) clocks,
                       count(*) FILTER (WHERE try_cast(acceptanceDateTime AS TIMESTAMP) IS NULL) invalid,
                       count(DISTINCT cik) ciks,count(*) rows_n
                FROM read_parquet(?) WHERE accessionNumber IS NOT NULL GROUP BY accessionNumber
            """,[str(path)])
            print(f'Grouped {role}: {time.monotonic()-started:.1f}s',flush=True)
        build_overrides(con)
        print('Pair overrides built',flush=True)
        con.execute('''CREATE TEMP TABLE reference AS
            SELECT source_file,accessionNumber,acceptanceDateTime,
                   timestamp_provenance,timestamp_interpretation
            FROM read_parquet(?)''',[str(args.reference)])
        duplicates=con.execute('SELECT count(*) FROM (SELECT source_file,accessionNumber FROM reference GROUP BY ALL HAVING count(*)>1)').fetchone()[0]
        if duplicates:
            raise ValueError(f'Reference has {duplicates} duplicate row keys')
        con.execute("""
            CREATE TABLE comparison AS
            SELECT r.cik,r.accessionNumber,r.source_file,r.form,r.raw_clock,
                   o.evidence,o.corrected_instant,
                   f.acceptanceDateTime AS reference_instant,
                   f.timestamp_provenance AS reference_provenance,
                   f.timestamp_interpretation AS reference_interpretation,
                   f.accessionNumber IS NOT NULL AS reference_found
            FROM current_rows r
            LEFT JOIN accession_timestamp_overrides o USING(accessionNumber)
            LEFT JOIN reference f ON f.source_file=r.source_file AND f.accessionNumber=r.accessionNumber
        """)
        assert con.execute('SELECT count(*) FROM comparison WHERE NOT reference_found').fetchone()[0]==0
        for title,sql in [
            ('Coverage by evidence',"""SELECT coalesce(evidence,'unresolved'),count(DISTINCT accessionNumber),count(*),
               count(*) FILTER(WHERE corrected_instant=reference_instant),
               count(*) FILTER(WHERE corrected_instant IS NOT NULL AND corrected_instant IS DISTINCT FROM reference_instant)
               FROM comparison GROUP BY 1 ORDER BY 1"""),
            ('Step counts',"""SELECT 'snapshot',count(*),sum(g.rows_n) FROM snapshot_pair_overrides s JOIN current_groups g USING(accessionNumber)
               UNION ALL SELECT 'duplicates',count(*),sum(g.rows_n) FROM current_duplicate_overrides s JOIN current_groups g USING(accessionNumber)"""),
            ('Unresolved clocks vs reference',"""SELECT reference_provenance,count(*),
               count(*) FILTER(WHERE (raw_clock AT TIME ZONE 'America/New_York')=reference_instant) eastern_matches,
               count(*) FILTER(WHERE (raw_clock AT TIME ZONE 'UTC')=reference_instant) utc_matches
               FROM comparison WHERE corrected_instant IS NULL GROUP BY 1 ORDER BY 2 DESC"""),
            ('Inferred disagreements',"""SELECT reference_provenance,form,count(*) FROM comparison
               WHERE corrected_instant IS NOT NULL AND corrected_instant IS DISTINCT FROM reference_instant
               GROUP BY 1,2 ORDER BY 3 DESC LIMIT 20"""),
            ('With unverified Eastern fallback',"""SELECT count(*),count(*) FILTER(WHERE
               coalesce(corrected_instant,raw_clock AT TIME ZONE 'America/New_York')=reference_instant)
               FROM comparison"""),
        ]:
            print(title,con.execute(sql).fetchall(),flush=True)
        print('Conflicts:',con.execute('SELECT count(*) FROM pair_conflicts').fetchone()[0])
    print(f'Database: {args.database}; elapsed={time.monotonic()-started:.1f}s')


if __name__=='__main__':
    main()
