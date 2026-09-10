#!/usr/bin/env python3
"""Compare live collection plans against frozen evidence, without SEC requests.

This is a cache-backed coverage replay, not an HTTP trace replay. Historical
file observations are reachable only through an accession and CIK belonging
to a selected ZIP block. SGML evidence is held constant across plans.
"""

import argparse
from datetime import datetime
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string
from compare_live_json_timestamps import compare_clocks
from infer_live_file_timezones import infer


def replay(c, stages, inherited_before=None):
    c.execute('CREATE TABLE targets AS SELECT DISTINCT source_file FROM plans WHERE stage IN (SELECT unnest(?))',[stages])
    c.execute('''CREATE TABLE inherited_live AS SELECT * FROM e.live_json_timestamp_observations
        WHERE retrieved_at<CAST(? AS TIMESTAMPTZ)''',[inherited_before])
    c.execute("""
        CREATE TEMP TABLE selected_rows AS
        SELECT b.* FROM b.comparison b JOIN targets t USING(source_file);
        CREATE TABLE live AS
        SELECT DISTINCT o.* FROM e.live_json_timestamp_observations o
        JOIN selected_rows r ON r.accessionNumber=o.accession_number
          AND try_cast(regexp_extract(o.source_url,'CIK([0-9]+)',1) AS BIGINT)=r.cik
        UNION SELECT * FROM inherited_live;
        CREATE TEMP TABLE input_clocks AS
        SELECT DISTINCT r.cik,r.accessionNumber accession,
               CAST(r.raw_clock AS VARCHAR) zip_text,l.acceptance_datetime_text live_text,l.source_url url
        FROM b.comparison r JOIN live l ON l.accession_number=r.accessionNumber
          AND try_cast(regexp_extract(l.source_url,'CIK([0-9]+)',1) AS BIGINT)=r.cik
        WHERE r.source_file IN (SELECT source_file FROM targets)
           OR EXISTS(SELECT 1 FROM inherited_live i WHERE i.source_url=l.source_url
                     AND i.accession_number=l.accession_number);
    """)
    compare_clocks(c)
    c.execute("""
        CREATE TABLE direct_pairs AS
        SELECT accession,min(corrected) AT TIME ZONE 'America/New_York' instant
        FROM comparisons GROUP BY accession
        HAVING count(DISTINCT corrected)=1
          AND count(*) FILTER(WHERE status IN ('invalid','unexplained'))=0;
        CREATE TEMP TABLE anchor_inputs AS
        SELECT accessionNumber accession,corrected_instant instant FROM b.accession_timestamp_overrides
        UNION ALL SELECT * FROM direct_pairs;
        CREATE TEMP TABLE validation AS
        SELECT * FROM anchor_inputs
        UNION ALL SELECT accession_number,instant FROM fixed_sgml;
    """)
    infer(c)
    c.execute("""
        CREATE TABLE sgml_file_anchors AS
        SELECT l.source_url,l.accession_number,s.instant
        FROM live l JOIN fixed_sgml s USING(accession_number)
        WHERE l.source_url NOT IN (SELECT source_url FROM file_rules);
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
        UNION ALL SELECT s.accession_number,s.instant,40 FROM fixed_sgml s
        JOIN q.sgml_queue q USING(accession_number);
        CREATE TABLE disagreements AS
        SELECT accession_number FROM evidence GROUP BY 1 HAVING count(DISTINCT instant)>1;
        CREATE TABLE resolved AS
        SELECT accession_number,instant FROM evidence
        QUALIFY row_number() OVER(PARTITION BY accession_number ORDER BY priority DESC)=1;
        CREATE TABLE metrics AS
        SELECT count(*) rows_n,count(r.instant) supported_rows,
          count(*) FILTER(WHERE r.instant IS NOT NULL AND
             r.instant IS DISTINCT FROM c.raw_clock AT TIME ZONE 'America/New_York') shifted_rows,
          count(*) FILTER(WHERE r.instant IS NULL AND c.corrected_instant IS NOT NULL) lost_support_rows,
          count(*) FILTER(WHERE coalesce(r.instant,c.raw_clock AT TIME ZONE 'America/New_York')
             IS DISTINCT FROM c.prospective_instant) changed_vs_frozen,
          count(*) FILTER(WHERE r.instant IS NULL AND c.corrected_instant IS NOT NULL AND
             c.prospective_instant IS DISTINCT FROM c.raw_clock AT TIME ZONE 'America/New_York') lost_shift_rows
        FROM old.comparison c LEFT JOIN resolved r ON r.accession_number=c.accessionNumber;
        CREATE TABLE fetch_metrics AS
        WITH urls AS (
          SELECT 'https://data.sec.gov/submissions/'||source_file url FROM targets
          UNION SELECT source_url FROM live
        )
        SELECT (SELECT count(*) FROM targets) target_blocks,
               (SELECT count(*) FROM urls) unique_json_urls_lower_bound,
               (SELECT count(*) FROM live) cached_live_observations,
               (SELECT count(DISTINCT accession_number) FROM sgml_file_anchors) sgml_anchor_accessions,
               (SELECT count(*) FROM disagreements) conflicting_accessions;
        CREATE TABLE inherited_cache_metrics AS
        SELECT count(*) observations,count(DISTINCT source_url) source_files,
               count(DISTINCT accession_number) accessions FROM inherited_live;
    """)
    print('Fetch metrics:',c.execute('SELECT * FROM fetch_metrics').fetchone(),flush=True)
    print('Correction metrics:',c.execute('SELECT * FROM metrics').fetchone(),flush=True)
    print('Inherited cache:',c.execute('SELECT * FROM inherited_cache_metrics').fetchone(),flush=True)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('output/timestamp_baseline'))
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--inherited-before',type=datetime.fromisoformat,
                   help='Reuse all cached live observations retrieved before this timezone-aware timestamp.')
    p.add_argument('--union-only',action='store_true')
    p.add_argument('--fixed-sgml-from',type=Path,
                   help='Reuse fixed_sgml from an earlier replay for an identical SGML starting point.')
    args=p.parse_args()
    if args.inherited_before and args.inherited_before.tzinfo is None:
        p.error('--inherited-before must include a timezone offset')
    args.output.mkdir(parents=True,exist_ok=False)
    # The audit's new SGML must not leak into this comparison of earlier plans.
    scenarios=[('step7_only',['7']),('steps3_7',['3','7']),('steps3_5_7',['3','5','7'])]
    for name,stages in scenarios[-1:] if args.union_only else scenarios:
        print('PLAN:',name,flush=True)
        with duckdb.connect(str(args.output/f'{name}.duckdb')) as c:
            c.execute("SET threads=4; SET memory_limit='4GB'; SET TimeZone='UTC'; SET enable_progress_bar=false")
            for alias,path in [('b',args.root/'pair_baseline.duckdb'),
                               ('old',args.root/'effect_evaluation.duckdb'),
                               ('f',args.root/'live_file_inference_effect.duckdb'),
                               ('q',args.root/'outside_hours_sgml_queue_v2.duckdb'),
                               ('s5',args.root/'old_rule_live_targets.duckdb'),
                               ('s7',args.root/'recent_live_targets.duckdb'),
                               ('e',args.database)]:
                c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
            c.execute("""
                CREATE TABLE plans AS
                SELECT '3' stage,source_file FROM b.comparison
                WHERE corrected_instant IS NULL AND raw_clock>=TIMESTAMP '2003-01-01'
                  AND coalesce(form,'')<>'EFFECT'
                  AND (CAST(raw_clock AS TIME)>TIME '22:00:00' OR CAST(raw_clock AS TIME)<TIME '06:00:00')
                GROUP BY source_file
                UNION ALL SELECT '5',source_file FROM s5.target_blocks
                UNION ALL SELECT '7',source_file FROM s7.target_blocks;
                CREATE TABLE fixed_sgml AS
                SELECT accession_number,min(instant) instant FROM (
                  SELECT accession_number,instant FROM f.sgml_file_anchors
                  UNION ALL SELECT accession_number,acceptance_datetime AT TIME ZONE 'America/New_York'
                  FROM e.sgml_observations WHERE acceptance_datetime IS NOT NULL AND error IS NULL
                    AND retrieved_at<=(SELECT created_at FROM old.workflow_metadata)
                  UNION ALL SELECT accession_number,corrected_instant
                  FROM old.accession_evidence WHERE provenance='sgml'
                ) GROUP BY 1 HAVING count(DISTINCT instant)=1;
                CREATE TABLE metadata AS SELECT now() created_at,
                  'Frozen Step 5/7 targets; reconstructed Step 3 targets; current cached JSON; fixed pre-audit SGML; URL counts are lower bounds' assumptions;
            """)
            print('Original queues:',c.execute('SELECT stage,count(*) FROM plans GROUP BY 1 ORDER BY 1').fetchall(),flush=True)
            if args.fixed_sgml_from:
                c.execute(f'ATTACH {sql_string(args.fixed_sgml_from)} AS original_replay (READ_ONLY)')
                c.execute('DROP TABLE fixed_sgml; CREATE TABLE fixed_sgml AS SELECT * FROM original_replay.fixed_sgml')
            c.execute('ALTER TABLE metadata ADD COLUMN inherited_before TIMESTAMPTZ')
            c.execute('UPDATE metadata SET inherited_before=?',[args.inherited_before])
            replay(c,stages,args.inherited_before)


if __name__=='__main__':
    main()
