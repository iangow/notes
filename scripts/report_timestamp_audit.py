#!/usr/bin/env python3
"""Freeze stratified SGML audit outcomes, including unverifiable observations."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute(f'ATTACH {sql_string(args.queue)} AS q (READ_ONLY)')
        c.execute(f'ATTACH {sql_string(args.database)} AS e (READ_ONLY)')
        c.execute("""
            CREATE TABLE metadata AS SELECT *,now() reported_at FROM q.metadata;
            CREATE TABLE strata AS SELECT * FROM q.strata;
            CREATE TABLE outcomes AS
            SELECT q.*,s.acceptance_datetime sgml_clock,s.error,s.source_url,s.retrieved_at,
                CASE WHEN s.accession_number IS NULL THEN 'not_checked'
                     WHEN s.error IS NOT NULL OR s.acceptance_datetime IS NULL THEN 'unverifiable'
                     WHEN q.raw_clock=s.acceptance_datetime THEN 'eastern_confirmed'
                     WHEN (q.raw_clock AT TIME ZONE 'UTC')=
                          (s.acceptance_datetime AT TIME ZONE 'America/New_York') THEN 'utc_indicated'
                     ELSE 'other_discrepancy' END outcome
            FROM q.candidate_rows q LEFT JOIN e.sgml_observations s ON s.accession_number=q.accessionNumber;
            CREATE TABLE stratum_results AS
            SELECT period,midnight,form_group,outcome,count(*) sampled_rows,
                   sum(sampling_weight) estimated_population_rows
            FROM outcomes GROUP BY ALL;
        """)
        print('OUTCOMES: status, sample rows, population-weighted percent',flush=True)
        for row in c.execute('''SELECT outcome,count(*),
            round(100*sum(sampling_weight)/(SELECT sum(population_n) FROM strata),4)
            FROM outcomes GROUP BY 1 ORDER BY 1''').fetchall():
            print(row,flush=True)
        print('By period:',c.execute('SELECT period,outcome,count(*) FROM outcomes GROUP BY 1,2 ORDER BY 1,2').fetchall(),flush=True)
        print('Unverifiable and not_checked are not confirmations; weighted percentages are estimates, not confidence bounds.',flush=True)
        print(f'Frozen audit report: {args.output}',flush=True)


if __name__=='__main__':
    main()
