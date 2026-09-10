#!/usr/bin/env python3
"""Compare three frozen predictions against SGML on the same weighted sample."""

import argparse
from pathlib import Path

import duckdb

from acceptance_timestamp_db import DEFAULT_DB
from compare_filing_timestamp_sources import sql_string
from build_paired_timestamp_audit import STRATA


def summarize(c):
    c.execute(f"""
        CREATE TABLE model_outcomes AS
        SELECT o.* EXCLUDE(monday_instant,last_night_instant,streamlined_instant),
               v.model,v.predicted,
               CASE WHEN NOT verifiable THEN NULL
                    ELSE v.predicted IS DISTINCT FROM sgml_instant END is_error
        FROM outcomes o CROSS JOIN LATERAL (VALUES
            ('monday',o.monday_instant),('last_night',o.last_night_instant),
            ('streamlined',o.streamlined_instant)) v(model,predicted);
        CREATE TABLE stratum_results AS
        SELECT {STRATA},model,count(*) sample_n,count(*) FILTER(WHERE verifiable) verified_n,
               count(*) FILTER(WHERE is_error) errors_n,
               sum(sampling_weight) population_weight,
               sum(CASE WHEN verifiable THEN sampling_weight ELSE 0 END) verified_weight,
               sum(CASE WHEN is_error THEN sampling_weight ELSE 0 END) error_weight
        FROM model_outcomes GROUP BY ALL;
        CREATE TABLE summary AS
        SELECT model,sum(sample_n) sampled_rows,sum(verified_n) verified_rows,sum(errors_n) errors,
            100.0*sum(error_weight)/nullif(sum(verified_weight),0) error_percent_among_verifiable,
            100.0*(sum(population_weight)-sum(verified_weight))/sum(population_weight) unverifiable_percent,
            100.0*sum(error_weight)/sum(population_weight) whole_population_error_lower,
            100.0*(sum(error_weight)+sum(population_weight)-sum(verified_weight))/sum(population_weight)
                whole_population_error_upper
        FROM stratum_results GROUP BY model;
    """)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue',type=Path,required=True)
    p.add_argument('--database',type=Path,default=DEFAULT_DB)
    p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    with duckdb.connect(str(args.output)) as c:
        c.execute("SET TimeZone='UTC'")
        c.execute(f'ATTACH {sql_string(args.queue)} AS q (READ_ONLY)')
        c.execute(f'ATTACH {sql_string(args.database)} AS e (READ_ONLY)')
        c.execute("""
            CREATE TABLE metadata AS SELECT *,now() reported_at FROM q.metadata;
            CREATE TABLE versions AS SELECT * FROM q.versions;
            CREATE TABLE strata AS SELECT * FROM q.strata;
            CREATE TABLE outcomes AS
            SELECT q.*,s.acceptance_datetime AT TIME ZONE 'America/New_York' sgml_instant,
                   coalesce(s.acceptance_datetime IS NOT NULL AND s.error IS NULL,false) verifiable,
                   s.error,s.source_url,s.retrieved_at,
                   s.accession_number IS NULL not_checked
            FROM q.candidate_rows q LEFT JOIN e.sgml_observations s ON s.accession_number=q.accessionNumber;
        """)
        summarize(c)
        print('Columns:',[r[0] for r in c.execute('DESCRIBE summary').fetchall()],flush=True)
        for row in c.execute('SELECT * FROM summary ORDER BY model').fetchall():
            print(row,flush=True)
        print('These are weighted point estimates. Whole-population ranges reflect unverifiable cases, not sampling confidence intervals.',flush=True)
        print('Streamlined predictions are a provisional replay; refer to versions for exact scope.',flush=True)
        print(f'Frozen paired report: {args.output}',flush=True)


if __name__=='__main__':
    main()
