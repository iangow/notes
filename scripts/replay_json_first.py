#!/usr/bin/env python3
"""Replay JSON-first ordering on the frozen union of Step 3/5/7 targets."""

import argparse
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import sql_string
from infer_live_file_timezones import infer


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('output/timestamp_baseline'))
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--union-replay',type=Path,help='Combined-target replay supplying the common live and SGML cache.')
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET threads=4; SET memory_limit='4GB'; SET TimeZone='UTC'; SET enable_progress_bar=false")
        for alias,path in [('u',args.union_replay or args.root/'collection_replay/steps3_5_7.duckdb'),
                           ('b',args.root/'pair_baseline.duckdb'),
                           ('old',args.root/'effect_evaluation.duckdb'),
                           ('q',args.root/'outside_hours_sgml_queue_v2.duckdb')]:
            c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
        c.execute("""
            CREATE TEMP VIEW live AS SELECT * FROM u.live;
            CREATE TEMP TABLE anchor_inputs AS
            SELECT accessionNumber accession,corrected_instant instant FROM b.accession_timestamp_overrides
            UNION ALL SELECT * FROM u.direct_pairs;
            CREATE TEMP TABLE validation AS SELECT * FROM anchor_inputs;
        """)
        infer(c)
        c.execute("""
            CREATE TABLE json_rules AS SELECT * FROM file_rules;
            CREATE TABLE json_prospective AS
            SELECT c.cik,c.accessionNumber,c.source_file,c.form,c.raw_clock,
                   coalesce(a.instant,i.instant) supported_instant,
                   coalesce(a.instant,i.instant,c.raw_clock AT TIME ZONE 'America/New_York') instant
            FROM b.comparison c LEFT JOIN anchors a ON a.accession=c.accessionNumber
            LEFT JOIN inferred_overrides i ON i.accession_number=c.accessionNumber;
            CREATE TABLE outside_hours_rows AS
            SELECT * FROM json_prospective WHERE coalesce(form,'')<>'EFFECT'
              AND (instant AT TIME ZONE 'America/New_York')>=TIMESTAMP '2003-01-01'
              AND (CAST(instant AT TIME ZONE 'America/New_York' AS TIME)<TIME '06:00:00'
                OR CAST(instant AT TIME ZONE 'America/New_York' AS TIME)>TIME '22:00:00');
            CREATE TABLE unmatched_rows AS
            SELECT * FROM json_prospective c WHERE source_file IN (
                SELECT source_file FROM u.plans WHERE stage IN ('5','7'))
              AND NOT EXISTS(SELECT 1 FROM live l WHERE l.accession_number=c.accessionNumber);
            CREATE TABLE sgml_queue AS
            SELECT accessionNumber accession_number FROM outside_hours_rows
            UNION SELECT accessionNumber FROM unmatched_rows;
            CREATE TABLE sgml_file_anchors AS
            SELECT l.source_url,l.accession_number,s.instant FROM live l
            JOIN u.fixed_sgml s USING(accession_number)
            WHERE l.source_url NOT IN (SELECT source_url FROM json_rules);
            INSERT INTO validation SELECT accession_number,instant FROM u.fixed_sgml;
        """)
        for table in ('anchors','file_evidence','file_rules','file_candidates','rejected_accessions','inferred_overrides'):
            c.execute(f'DROP TABLE {table}')
        infer(c,sgml_file_anchors=True)
        c.execute("""
            CREATE TABLE evidence AS
            SELECT accessionNumber accession_number,corrected_instant instant,30 priority
            FROM b.accession_timestamp_overrides
            UNION ALL SELECT accession,instant,20 FROM anchors
            WHERE accession NOT IN (SELECT accessionNumber FROM b.accession_timestamp_overrides)
            UNION ALL SELECT accession_number,instant,10 FROM inferred_overrides
            UNION ALL SELECT s.accession_number,s.instant,40 FROM u.fixed_sgml s
            JOIN sgml_queue q USING(accession_number);
            CREATE TABLE resolved AS SELECT accession_number,instant FROM evidence
            QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY priority DESC)=1;
            CREATE TABLE metrics AS
            SELECT count(*) rows_n,count(r.instant) supported_rows,
              count(*) FILTER(WHERE r.instant IS NOT NULL AND
                r.instant IS DISTINCT FROM c.raw_clock AT TIME ZONE 'America/New_York') shifted_rows,
              count(*) FILTER(WHERE r.instant IS NULL AND c.corrected_instant IS NOT NULL) lost_support_rows,
              count(*) FILTER(WHERE coalesce(r.instant,c.raw_clock AT TIME ZONE 'America/New_York')
                IS DISTINCT FROM c.prospective_instant) changed_vs_frozen,
              count(*) FILTER(WHERE coalesce(r.instant,c.raw_clock AT TIME ZONE 'America/New_York')
                IS DISTINCT FROM coalesce(u.instant,c.raw_clock AT TIME ZONE 'America/New_York')) changed_vs_union
            FROM old.comparison c LEFT JOIN resolved r ON r.accession_number=c.accessionNumber
            LEFT JOIN u.resolved u ON u.accession_number=c.accessionNumber;
            CREATE TABLE unclassified_files AS
            SELECT DISTINCT source_url FROM live WHERE source_url NOT IN (SELECT source_url FROM file_rules);
            CREATE TABLE metadata AS SELECT now() created_at,
              'Frozen union targets and pre-audit SGML availability. SGML selection rebuilt after JSON-only inference. No fetches.' assumptions;
            CREATE TABLE starting_cache_metadata AS SELECT * FROM u.metadata;
        """)
        print('Metrics:',c.execute('SELECT * FROM metrics').fetchone(),flush=True)
        print('Outside-hours rows/accessions:',c.execute('SELECT count(*),count(DISTINCT accessionNumber) FROM outside_hours_rows').fetchone(),flush=True)
        print('Unmatched rows/accessions:',c.execute('SELECT count(*),count(DISTINCT accessionNumber) FROM unmatched_rows').fetchone(),flush=True)
        print('SGML accession queue / cached usable:',c.execute('SELECT count(*),count(s.accession_number) FROM sgml_queue q LEFT JOIN u.fixed_sgml s USING(accession_number)').fetchone(),flush=True)
        print('Queue overlap old/new:',c.execute('''SELECT
            (SELECT count(*) FROM q.sgml_queue),
            (SELECT count(*) FROM sgml_queue),
            (SELECT count(*) FROM q.sgml_queue q JOIN sgml_queue n USING(accession_number))''').fetchone(),flush=True)
        print('Remaining unclassified files / without any anchor evidence:',c.execute('''SELECT count(*),
            count(*) FILTER(WHERE NOT EXISTS(SELECT 1 FROM file_evidence e WHERE e.source_url=f.source_url))
            FROM unclassified_files f''').fetchone(),flush=True)
        print('Evidence conflicts:',c.execute('SELECT count(*) FROM (SELECT accession_number FROM evidence GROUP BY 1 HAVING count(DISTINCT instant)>1)').fetchone(),flush=True)


if __name__=='__main__':
    main()
