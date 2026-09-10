#!/usr/bin/env python3
"""Diagnose frozen paired-audit errors and quantify stratified uncertainty."""

import argparse
import math
from pathlib import Path

import duckdb

from compare_filing_timestamp_sources import sql_string


def zero_error_upper(strata, verified_fraction, alpha=.05):
    """Conservative joint bound for E/V under fixed verification status.

    With no sampled errors, P(no hit | K errors) <= exp(-f_min*K).
    A weighted Hoeffding lower bound for V/N supplies the denominator.
    Split alpha between the two statements; this is deliberately not 3/n.
    """
    total=sum(N for N,n in strata)
    noncensus=[(N,n) for N,n in strata if n<N]
    if not noncensus:
        return 0.,verified_fraction,0.
    logtail=math.log(2/alpha)
    numerator=min(1.,logtail/min(n/N for N,n in noncensus)/total)
    denominator=max(0.,verified_fraction-math.sqrt(
        .5*logtail*sum((N/total)**2/n for N,n in noncensus)))
    return numerator,denominator,min(1.,numerator/denominator) if denominator else 1.


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=Path('output/timestamp_baseline'))
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET threads=4; SET TimeZone='UTC'; SET enable_progress_bar=false")
        for alias,path in [('a',args.root/'paired_audit_10000_report.duckdb'),
                           ('j',args.root/'json_first_replay.duckdb'),
                           ('u',args.root/'collection_replay/steps3_5_7.duckdb'),
                           ('f',args.root/'live_file_inference_effect.duckdb')]:
            c.execute(f'ATTACH {sql_string(path)} AS {alias} (READ_ONLY)')
        c.execute("""
            CREATE TABLE error_diagnostics AS
            SELECT b.*,i.source_url original_live_url,
              EXISTS(SELECT 1 FROM u.targets t WHERE t.source_file=b.source_file) selected_block,
              EXISTS(SELECT 1 FROM u.live l WHERE l.accession_number=b.accessionNumber) replay_live_present,
              r.accession_number IS NOT NULL replay_resolved,
              CASE WHEN r.accession_number IS NULL AND NOT EXISTS(
                SELECT 1 FROM u.live l WHERE l.accession_number=b.accessionNumber)
                THEN 'missing live coverage' WHEN r.accession_number IS NULL THEN 'unresolved inference'
                ELSE 'different accepted instant' END AS diagnosis
            FROM a.model_outcomes b LEFT JOIN j.resolved r ON r.accession_number=b.accessionNumber
            LEFT JOIN f.inferred_overrides i ON i.accession_number=b.accessionNumber
            WHERE b.model='streamlined' AND b.is_error;
            CREATE TABLE unavailable AS
            SELECT *,CASE WHEN error LIKE '%ACCEPTANCE-DATETIME tag not found%' THEN 'missing_tag'
                WHEN error LIKE '%503%' OR error LIKE 'Timeout%' OR error LIKE 'IncompleteRead%'
                  THEN 'retryable_request_failure'
                WHEN error LIKE '%404%' THEN 'http_404' ELSE 'other' END AS failure_kind,
              CASE WHEN midnight THEN 'raw_midnight'
                   WHEN CAST(raw_clock AT TIME ZONE 'UTC' AT TIME ZONE 'America/New_York' AS TIME)=TIME '00:00:00'
                     THEN 'eastern_midnight_if_raw_utc' ELSE 'neither_midnight' END AS clock_kind
            FROM a.outcomes WHERE NOT verifiable;
            CREATE TABLE unavailable_summary AS
            SELECT failure_kind,clock_kind,count(*) sampled_rows,count(DISTINCT accessionNumber) accessions,
              min(raw_clock) earliest,max(raw_clock) latest,
              100*sum(sampling_weight)/(SELECT sum(population_n) FROM a.strata) population_percent
            FROM unavailable GROUP BY 1,2;
            CREATE TABLE uncertainty(model VARCHAR,estimate_percent DOUBLE,se_percentage_points DOUBLE,
                lower_percent DOUBLE,upper_percent DOUBLE,interval_method VARCHAR);
            CREATE TABLE zero_bound_inputs(error_fraction_upper DOUBLE,verified_fraction_lower DOUBLE,
                alpha DOUBLE,assumption VARCHAR);
            CREATE TABLE metadata AS SELECT now() created_at,
                'Frozen audit: no new SGML, no repaired predictions. Treat strata as SRS without replacement and verifiability as fixed under the audit protocol.' assumptions;
        """)
        strata=c.execute('SELECT population_n,sample_n FROM a.strata').fetchall()
        total=sum(N for N,n in strata)
        verified=c.execute('''SELECT sum(CASE WHEN verifiable THEN sampling_weight ELSE 0 END)
            /sum(sampling_weight) FROM a.outcomes''').fetchone()[0]
        for model in ('monday','last_night','streamlined'):
            errors,ratio=c.execute('''SELECT count(*) FILTER(WHERE is_error),
                sum(CASE WHEN is_error THEN sampling_weight ELSE 0 END)
                /sum(CASE WHEN verifiable THEN sampling_weight ELSE 0 END)
                FROM a.model_outcomes WHERE model=?''',[model]).fetchone()
            if errors==0:
                numerator,denominator,upper=zero_error_upper(strata,verified)
                c.execute('INSERT INTO zero_bound_inputs VALUES (?,?,?,?)',
                          [numerator,denominator,.05,'Fixed verifiability; union bound of two 97.5% statements'])
                c.execute('INSERT INTO uncertainty VALUES (?,?,?,?,?,?)',
                          [model,0.,None,0.,100*upper,'Conservative one-sided 95% zero-error bound'])
                continue
            moments=c.execute('''SELECT population_n,sample_n,
                var_samp(CASE WHEN is_error THEN 1 ELSE 0 END - ?*CAST(verifiable AS INTEGER))
                FROM a.model_outcomes WHERE model=? GROUP BY period,midnight,form_group,
                method,version_disagreement,population_n,sample_n''',[ratio,model]).fetchall()
            if any(v is None and n<N for N,n,v in moments):
                raise ValueError('Cannot estimate a noncensus singleton stratum variance')
            variance=sum((N/total)**2*(1-n/N)*(v or 0)/n for N,n,v in moments)/verified**2
            se=math.sqrt(variance)
            c.execute('INSERT INTO uncertainty VALUES (?,?,?,?,?,?)',
                      [model,ratio*100,se*100,max(0,ratio-1.95996398454*se)*100,
                       min(1,ratio+1.95996398454*se)*100,'Approximate 95% stratified ratio-linearization interval'])
        print('Discrepancies:',c.execute('SELECT diagnosis,selected_block,replay_live_present,replay_resolved,count(*) FROM error_diagnostics GROUP BY ALL').fetchall())
        print('Unverifiable:',c.execute('SELECT failure_kind,sum(sampled_rows),sum(population_percent) FROM unavailable_summary GROUP BY 1').fetchall())
        print('Uncertainty:',c.execute('SELECT * FROM uncertainty').fetchall())
        print('No interval validates the unavailable-reference population. Retryable failures warrant follow-up before final inference.')


if __name__=='__main__':
    main()
