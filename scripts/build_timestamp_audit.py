#!/usr/bin/env python3
"""Freeze a stratified random row sample of unverified Eastern fallbacks."""

import argparse
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import sql_string


PERIOD_SIZES = {0: 300, 1: 450, 2: 750, 3: 1500}


def allocate(populations, target):
    """Give small cells representation, then allocate remaining places by capacity."""
    if target > sum(populations.values()):
        raise ValueError('Sample exceeds population')
    sizes = {k: min(5, n) for k, n in populations.items()}
    if sum(sizes.values()) > target:
        raise ValueError('Sample too small for minimum cell representation')
    remaining = target - sum(sizes.values())
    capacity = {k: populations[k] - sizes[k] for k in sizes}
    total = sum(capacity.values())
    if remaining:
        quotas = {k: remaining * n / total for k, n in capacity.items()}
        for k, q in quotas.items():
            sizes[k] += int(q)
        extra = target - sum(sizes.values())
        for k in sorted(quotas, key=lambda k: (-(quotas[k] % 1), k))[:extra]:
            sizes[k] += 1
    return sizes


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workflow-database', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seed', type=int, default=20260910)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute('SET threads=4; SET enable_progress_bar=false')
        c.execute(f'ATTACH {sql_string(args.workflow_database)} AS workflow (READ_ONLY)')
        c.execute("""
            CREATE TEMP TABLE population AS
            SELECT cik,accessionNumber,source_file,form,raw_clock,
                CASE WHEN year(raw_clock)<2003 THEN 0 WHEN year(raw_clock)<2014 THEN 1
                     WHEN year(raw_clock)<2024 THEN 2 ELSE 3 END period,
                CAST(raw_clock AS TIME)=TIME '00:00:00' midnight,
                CASE WHEN form IN ('3','3/A','4','4/A','5','5/A') THEN 'ownership'
                     WHEN form IN ('10-K','10-K/A','10-Q','10-Q/A','8-K','8-K/A','6-K','6-K/A') THEN 'periodic_current'
                     WHEN form IN ('CORRESP','UPLOAD','DRSLTR') THEN 'correspondence'
                     WHEN form='EFFECT' THEN 'effect'
                     ELSE 'other' END form_group
            FROM workflow.comparison WHERE corrected_instant IS NULL;
            CREATE TABLE strata AS
            SELECT period,midnight,form_group,count(*) population_n
            FROM population GROUP BY ALL;
            ALTER TABLE strata ADD COLUMN sample_n BIGINT;
        """)
        for period, target in PERIOD_SIZES.items():
            populations = {(m, f): n for m, f, n in c.execute(
                'SELECT midnight,form_group,population_n FROM strata WHERE period=?', [period]).fetchall()}
            for (midnight, form), n in allocate(populations, target).items():
                c.execute('UPDATE strata SET sample_n=? WHERE period=? AND midnight=? AND form_group=?',
                          [n, period, midnight, form])
        c.execute("""
            CREATE TABLE candidate_rows AS
            SELECT p.*,s.population_n,s.sample_n,
                   s.sample_n::DOUBLE/s.population_n inclusion_probability,
                   s.population_n::DOUBLE/s.sample_n sampling_weight
            FROM population p JOIN strata s USING(period,midnight,form_group)
            QUALIFY row_number() OVER(PARTITION BY period,midnight,form_group
                ORDER BY hash(?,cik,accessionNumber,source_file,raw_clock),
                         cik,accessionNumber,source_file,raw_clock)<=s.sample_n;
        """, [args.seed])
        c.execute("""
            CREATE TABLE sgml_queue AS
            SELECT accessionNumber accession_number,min(cik) cik,count(*) selected_rows,
                   max(raw_clock) latest_clock FROM candidate_rows GROUP BY accessionNumber;
            CREATE TABLE metadata AS SELECT now() created_at,? seed,? workflow_database;
        """, [args.seed, str(args.workflow_database.resolve())])
        n = c.execute('SELECT count(*) FROM candidate_rows').fetchone()[0]
        assert n == sum(PERIOD_SIZES.values())
        print('Sample rows / unique accessions:', n, c.execute('SELECT count(*) FROM sgml_queue').fetchone()[0])
        print('Allocation:', c.execute('SELECT period,sum(population_n),sum(sample_n) FROM strata GROUP BY 1 ORDER BY 1').fetchall())


if __name__ == '__main__':
    main()
