#!/usr/bin/env python3
"""Freeze a common stratified sample and three timestamp predictions before SGML lookup."""

import argparse
from pathlib import Path

import duckdb

from build_timestamp_audit import allocate
from compare_filing_timestamp_sources import sql_string


PERIOD_SIZES = {0: 1000, 1: 1500, 2: 2500, 3: 5000}
STRATA = 'period,midnight,form_group,method,version_disagreement'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workflow-database',type=Path,required=True)
    p.add_argument('--streamlined-database',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--seed',type=int,default=202609101)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET threads=4; SET memory_limit='4GB'; SET enable_progress_bar=false; SET TimeZone='UTC'")
        c.execute(f'ATTACH {sql_string(args.workflow_database)} AS w (READ_ONLY)')
        c.execute(f'ATTACH {sql_string(args.streamlined_database)} AS s (READ_ONLY)')
        c.execute("""
            CREATE TEMP TABLE population AS
            SELECT c.cik,c.accessionNumber,c.source_file,c.form,c.raw_clock,
                c.reference_instant monday_instant,c.prospective_instant last_night_instant,
                coalesce(s.instant,c.raw_clock AT TIME ZONE 'America/New_York') streamlined_instant,
                CASE WHEN year(raw_clock)<2003 THEN 0 WHEN year(raw_clock)<2014 THEN 1
                     WHEN year(raw_clock)<2024 THEN 2 ELSE 3 END period,
                coalesce(CAST(raw_clock AS TIME)=TIME '00:00:00',false) midnight,
                CASE WHEN form IN ('3','3/A','4','4/A','5','5/A') THEN 'ownership'
                     WHEN form IN ('10-K','10-K/A','10-Q','10-Q/A','8-K','8-K/A','6-K','6-K/A') THEN 'periodic_current'
                     WHEN form IN ('CORRESP','UPLOAD','DRSLTR') THEN 'correspondence'
                     WHEN form='EFFECT' THEN 'effect' ELSE 'other' END form_group,
                CASE WHEN c.provenance IN ('snapshot_pair','cross_cik_pair') THEN 'raw_pair'
                     WHEN c.provenance IS NULL THEN 'fallback' ELSE c.provenance END AS method,
                (monday_instant IS DISTINCT FROM last_night_instant OR
                 last_night_instant IS DISTINCT FROM streamlined_instant) version_disagreement
            FROM w.comparison c LEFT JOIN s.resolved s ON s.accession_number=c.accessionNumber;
        """)
        c.execute(f'CREATE TABLE strata AS SELECT {STRATA},count(*) population_n FROM population GROUP BY ALL')
        c.execute('ALTER TABLE strata ADD COLUMN sample_n BIGINT')
        for period,target in PERIOD_SIZES.items():
            populations={tuple(r[:-1]):r[-1] for r in c.execute('''SELECT midnight,form_group,
                method,version_disagreement,population_n FROM strata WHERE period=?''',[period]).fetchall()}
            for (midnight,form,method,disagreement),n in allocate(populations,target).items():
                c.execute('''UPDATE strata SET sample_n=? WHERE period=? AND midnight=?
                    AND form_group=? AND method=? AND version_disagreement=?''',
                    [n,period,midnight,form,method,disagreement])
        c.execute(f"""
            CREATE TABLE candidate_rows AS
            SELECT p.*,s.population_n,s.sample_n,
                   s.sample_n::DOUBLE/s.population_n inclusion_probability,
                   s.population_n::DOUBLE/s.sample_n sampling_weight
            FROM population p JOIN strata s USING({STRATA})
            QUALIFY row_number() OVER(PARTITION BY {STRATA}
                ORDER BY hash(?,cik,accessionNumber,source_file,raw_clock),
                         cik,accessionNumber,source_file,raw_clock)<=s.sample_n;
        """,[args.seed])
        c.execute("""
            CREATE TABLE sgml_queue AS SELECT accessionNumber accession_number,min(cik) cik,
                count(*) selected_rows,max(raw_clock) latest_clock FROM candidate_rows GROUP BY 1;
            CREATE TABLE versions(name VARCHAR,description VARCHAR,path VARCHAR,size_bytes BIGINT,mtime_ns BIGINT);
            CREATE TABLE metadata AS SELECT now() created_at,? seed,
                'All current rows; sample and predictions frozen before SGML lookup' AS policy;
        """,[args.seed])
        for name,description,path in [
            ('monday','Frozen September 7 reference instants',args.workflow_database),
            ('last_night','EFFECT backfill evaluation; four-case Step 8 not yet applied',args.workflow_database),
            ('streamlined','Provisional JSON-first frozen-target replay, not the final iterative pipeline',args.streamlined_database)]:
            stat=path.stat()
            c.execute('INSERT INTO versions VALUES (?,?,?,?,?)',[name,description,str(path.resolve()),stat.st_size,stat.st_mtime_ns])
        assert c.execute('SELECT count(*) FROM candidate_rows').fetchone()[0]==sum(PERIOD_SIZES.values())
        assert c.execute('SELECT count(*) FROM population').fetchone()[0]==c.execute('SELECT sum(population_n) FROM strata').fetchone()[0]
        print('Sample rows/accessions:',c.execute('SELECT count(*),count(DISTINCT accessionNumber) FROM candidate_rows').fetchone(),flush=True)
        print('Period allocation:',c.execute('SELECT period,sum(population_n),sum(sample_n) FROM strata GROUP BY 1 ORDER BY 1').fetchall(),flush=True)
        print('Methods:',c.execute('SELECT method,count(*) FROM candidate_rows GROUP BY 1 ORDER BY 1').fetchall(),flush=True)


if __name__=='__main__':
    main()
