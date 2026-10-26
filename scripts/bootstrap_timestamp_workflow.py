#!/usr/bin/env python3
"""Start timestamp correction from a previous corrected Parquet release."""

import argparse
from pathlib import Path
import time

import duckdb

from acceptance_timestamp_db import DATA_DIR
from analyze_timestamp_pair_baseline import build_overrides


# Legacy block/CIK rules and unresolved defaults are deliberately not anchors.
SUPPORTED_PROVENANCE = (
    "snapshot_pair", "cross_cik_pair", "live_pair", "live_file_inferred",
    "sgml", "submission_override", "duplicate_accession_override",
    "trusted_snapshot_eastern",
)


def bootstrap(con, raw: Path, prior: Path):
    con.execute("SET TimeZone='UTC'")
    for role, path in (("current", raw), ("prior", prior)):
        schema = {row[0]: row[1] for row in con.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()}
        required = {"accessionNumber", "acceptanceDateTime"}
        required |= {"cik", "source_file", "form"} if role == "current" else {"timestamp_provenance"}
        if missing := required - schema.keys():
            raise ValueError(f"{role} is missing columns: {sorted(missing)}")
        expected = "VARCHAR" if role == "current" else "TIMESTAMP WITH TIME ZONE"
        if schema["acceptanceDateTime"] != expected:
            raise ValueError(f"{role} acceptanceDateTime must be {expected}")

    con.execute("CREATE TABLE inputs(role VARCHAR,path VARCHAR,size_bytes BIGINT,mtime_ns BIGINT)")
    for role, path in (("current", raw), ("prior", prior)):
        stat = path.stat()
        con.execute("INSERT INTO inputs VALUES (?,?,?,?)",
                    [role, str(path.resolve()), stat.st_size, stat.st_mtime_ns])
    con.execute("""
        CREATE TEMP TABLE current_rows AS
        SELECT cik,accessionNumber,source_file,form,
               try_cast(acceptanceDateTime AS TIMESTAMP) raw_clock
        FROM read_parquet(?);
    """, [str(raw)])
    con.execute("""
        CREATE TABLE current_groups AS
        SELECT accessionNumber,
               list_sort(list(DISTINCT raw_clock) FILTER (WHERE raw_clock IS NOT NULL)) clocks,
               count(*) FILTER (WHERE raw_clock IS NULL) invalid,
               count(DISTINCT cik) ciks,count(*) rows_n
        FROM current_rows WHERE accessionNumber IS NOT NULL GROUP BY accessionNumber;
        CREATE TABLE old_groups AS SELECT * FROM current_groups WHERE false;
    """)
    prior_schema = {r[0] for r in con.execute(
        "DESCRIBE SELECT * FROM read_parquet(?)", [str(prior)]).fetchall()}
    if "timestamp_interpretation" in prior_schema:
        con.execute("""
            CREATE OR REPLACE TABLE old_groups AS
            WITH prior_clocks AS (
              SELECT accessionNumber,
                     CASE
                       WHEN timestamp_interpretation='utc'
                         THEN acceptanceDateTime AT TIME ZONE 'UTC'
                       WHEN timestamp_interpretation='eastern'
                         THEN acceptanceDateTime AT TIME ZONE 'America/New_York'
                       WHEN timestamp_provenance IN
                         ('unresolved_raw_as_eastern','special_form_unresolved_raw_as_eastern')
                         AND timestamp_interpretation='unresolved'
                         THEN acceptanceDateTime AT TIME ZONE 'America/New_York'
                     END source_clock,
                     timestamp_provenance,timestamp_interpretation
              FROM read_parquet(?)
              WHERE accessionNumber IN (SELECT accessionNumber FROM current_groups)
                AND ((timestamp_provenance IN (SELECT unnest(?))
                      AND timestamp_interpretation IN ('utc','eastern'))
                  OR (timestamp_provenance IN
                        ('unresolved_raw_as_eastern','special_form_unresolved_raw_as_eastern')
                      AND timestamp_interpretation='unresolved'))
            )
            SELECT accessionNumber,
                   list_sort(list(DISTINCT source_clock)
                     FILTER (WHERE source_clock IS NOT NULL)) clocks,
                   count(*) FILTER (WHERE source_clock IS NULL) invalid
            FROM prior_clocks GROUP BY accessionNumber;
        """, [str(prior), list(SUPPORTED_PROVENANCE)])
    build_overrides(con)

    reference = "timestamp_reference_id" if "timestamp_reference_id" in prior_schema else "NULL::VARCHAR"
    con.execute(f"""
        CREATE TABLE prior_release_evidence AS
        SELECT accessionNumber,acceptanceDateTime corrected_instant,
               timestamp_provenance provenance,{reference} reference_id,
               timestamp_provenance IN (SELECT unnest(?)) supported
        FROM read_parquet(?) WHERE accessionNumber IN (SELECT accessionNumber FROM current_groups);
    """, [list(SUPPORTED_PROVENANCE), str(prior)])
    con.execute("""
        CREATE TABLE prior_accession_evidence AS
        SELECT accessionNumber,min(corrected_instant) corrected_instant,
               list_sort(list(DISTINCT provenance)) inherited_provenances,
               list_sort(list(DISTINCT reference_id)) inherited_reference_ids,
               count(DISTINCT corrected_instant) instant_count,
               count(*) FILTER (WHERE corrected_instant IS NULL) invalid,
               first(provenance ORDER BY CASE provenance
                 WHEN 'sgml' THEN 1 WHEN 'submission_override' THEN 2
                 WHEN 'snapshot_pair' THEN 3 WHEN 'cross_cik_pair' THEN 4
                 WHEN 'duplicate_accession_override' THEN 5 WHEN 'live_pair' THEN 6
                 WHEN 'trusted_snapshot_eastern' THEN 8 ELSE 7 END,provenance) provenance
        FROM prior_release_evidence WHERE supported GROUP BY accessionNumber;

        CREATE TABLE prior_clock_checks AS
        SELECT c.*,p.corrected_instant prior_instant,
               coalesce((raw_clock AT TIME ZONE 'UTC')=p.corrected_instant,false) utc_matches,
               coalesce((raw_clock AT TIME ZONE 'America/New_York')=p.corrected_instant,false) eastern_matches
        FROM current_rows c JOIN prior_accession_evidence p USING(accessionNumber)
        WHERE p.instant_count=1 AND p.invalid=0;

        CREATE TABLE bootstrap_rejections AS
        SELECT p.accessionNumber,'conflicting_prior_instants' reason
        FROM prior_accession_evidence p JOIN current_groups c USING(accessionNumber)
        WHERE p.instant_count<>1 OR p.invalid>0
        UNION
        SELECT accessionNumber,'current_clock_matches_neither_timezone' FROM prior_clock_checks
        WHERE NOT utc_matches AND NOT eastern_matches
        UNION
        SELECT accessionNumber,'conflicting_current_pair_proposals' FROM pair_conflicts
        UNION
        SELECT s.accessionNumber,'prior_conflicts_with_snapshot_pair'
        FROM snapshot_pair_overrides s JOIN prior_accession_evidence p USING(accessionNumber)
        WHERE p.instant_count=1 AND p.invalid=0 AND s.corrected_instant<>p.corrected_instant
        UNION
        SELECT d.accessionNumber,'prior_conflicts_with_duplicate_pair'
        FROM current_duplicate_overrides d JOIN prior_accession_evidence p USING(accessionNumber)
        WHERE p.instant_count=1 AND p.invalid=0 AND d.corrected_instant<>p.corrected_instant;

        CREATE TABLE inherited_overrides AS
        SELECT p.* FROM prior_accession_evidence p JOIN current_groups c USING(accessionNumber)
        WHERE p.instant_count=1 AND p.invalid=0
          AND p.accessionNumber NOT IN (SELECT accessionNumber FROM bootstrap_rejections);

        CREATE OR REPLACE TABLE accession_timestamp_overrides AS
        WITH pair_proposals AS (
          SELECT accessionNumber,corrected_instant,'snapshot_pair' pair_source
          FROM snapshot_pair_overrides
          UNION ALL
          SELECT accessionNumber,corrected_instant,'cross_cik_pair' pair_source
          FROM current_duplicate_overrides
        ), pairs AS (
          SELECT accessionNumber,min(corrected_instant) corrected_instant,
                 string_agg(DISTINCT pair_source,',' ORDER BY pair_source) pair_source
          FROM pair_proposals GROUP BY accessionNumber
        )
        SELECT coalesce(p.accessionNumber,d.accessionNumber) accessionNumber,
               coalesce(p.corrected_instant,d.corrected_instant) corrected_instant,
               CASE WHEN p.accessionNumber IS NULL THEN
                         CASE WHEN d.pair_source='cross_cik_pair,snapshot_pair'
                              THEN 'snapshot_and_cross_cik_pair' ELSE d.pair_source END
                    WHEN d.accessionNumber IS NULL THEN 'prior_only'
                    ELSE 'prior_and_pair' END evidence,
               coalesce(p.provenance,CASE WHEN contains(d.pair_source,'snapshot_pair')
                                           THEN 'snapshot_pair' ELSE 'cross_cik_pair' END) provenance
        FROM inherited_overrides p FULL JOIN pairs d USING(accessionNumber)
        WHERE coalesce(p.accessionNumber,d.accessionNumber) NOT IN
              (SELECT accessionNumber FROM bootstrap_rejections);

        CREATE OR REPLACE TABLE pair_conflicts AS
        SELECT DISTINCT accessionNumber FROM bootstrap_rejections;

        CREATE TABLE resolved_accessions AS
        SELECT accessionNumber accession_number,corrected_instant,provenance
        FROM accession_timestamp_overrides;
        CREATE UNIQUE INDEX resolved_accession_key ON resolved_accessions(accession_number);

        CREATE TABLE prior_reference AS
        SELECT accessionNumber,
               CASE WHEN count(DISTINCT corrected_instant)=1
                     AND count(*) FILTER (WHERE corrected_instant IS NULL)=0
                    THEN min(corrected_instant) END reference_instant,
               string_agg(DISTINCT provenance,', ' ORDER BY provenance) reference_provenance
        FROM prior_release_evidence GROUP BY accessionNumber;

        CREATE TABLE comparison AS
        SELECT c.*,a.evidence,a.corrected_instant,p.reference_instant,p.reference_provenance,
               p.accessionNumber IS NOT NULL reference_found,a.provenance,
               coalesce(a.corrected_instant,c.raw_clock AT TIME ZONE 'America/New_York') prospective_instant
        FROM current_rows c LEFT JOIN accession_timestamp_overrides a USING(accessionNumber)
        LEFT JOIN prior_reference p USING(accessionNumber);

        CREATE TABLE summary AS
        SELECT count(*) rows_n,count(corrected_instant) supported_rows,
               count(*) FILTER (WHERE corrected_instant IS NULL) unresolved_rows
        FROM comparison;
        CREATE TABLE workflow_metadata AS
        SELECT now() created_at,'prior_corrected_parquet' AS policy,
               'Supported prior instants require unanimous evidence and agreement with every current clock; legacy block/CIK rules and fallbacks excluded.' assumptions;
    """)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-filings", type=Path, required=True)
    parser.add_argument("--raw", type=Path, default=DATA_DIR / "edgar" / "filings_raw.parquet")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Use a new output database to preserve earlier results")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    with duckdb.connect(str(args.output)) as con:
        con.execute("SET threads=4; SET memory_limit='4GB'; SET enable_progress_bar=false")
        con.execute("BEGIN TRANSACTION")
        bootstrap(con, args.raw.expanduser().resolve(), args.prior_filings.expanduser().resolve())
        con.commit()
        print("Coverage:", con.execute("SELECT * FROM summary").fetchone())
        print("Sources:", con.execute("SELECT evidence,count(*) FROM accession_timestamp_overrides GROUP BY 1").fetchall())
        print("Rejections:", con.execute("SELECT reason,count(*) FROM bootstrap_rejections GROUP BY 1").fetchall())
        print("Prior provenance:", con.execute("SELECT provenance,supported,count(*) FROM prior_release_evidence GROUP BY 1,2").fetchall())
    print(f"Workflow: {args.output}; elapsed={time.monotonic()-started:.1f}s")


if __name__ == "__main__":
    main()
