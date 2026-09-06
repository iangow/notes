"""Schema and resolver for SEC acceptance timestamp evidence."""

import os
from pathlib import Path

from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(REPO_ROOT / ".env")
DATA_DIR = Path(
    os.environ.get("DATA_DIR", Path.home() / "Dropbox" / "pq_data")
).expanduser()
DEFAULT_DB = Path(
    os.environ.get(
        "ACCEPTANCE_TIMESTAMP_DB",
        DATA_DIR / "edgar" / "acceptance_timestamp_reference.duckdb",
    )
)


def initialize_database(con):
    """Apply the idempotent schema migration to an open DuckDB connection."""
    con.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_versions (
          component VARCHAR PRIMARY KEY,
          version INTEGER NOT NULL,
          applied_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
        );

        CREATE TABLE IF NOT EXISTS sgml_observations (
          accession_number VARCHAR PRIMARY KEY,
          cik BIGINT NOT NULL,
          acceptance_datetime TIMESTAMP,
          source_url VARCHAR NOT NULL,
          retrieved_at TIMESTAMPTZ NOT NULL,
          elapsed_ms DOUBLE NOT NULL,
          http_status INTEGER,
          content_sha256 VARCHAR,
          sgml_header VARCHAR,
          error VARCHAR
        );

        CREATE TABLE IF NOT EXISTS block_samples (
          snapshot_id VARCHAR NOT NULL,
          cik BIGINT NOT NULL,
          stratum VARCHAR NOT NULL,
          block_name VARCHAR NOT NULL,
          block_sha256 VARCHAR NOT NULL,
          accession_number VARCHAR NOT NULL,
          sample_position VARCHAR NOT NULL,
          zip_acceptance_datetime VARCHAR NOT NULL,
          sgml_acceptance_datetime TIMESTAMP,
          diff_min INTEGER,
          interpretation VARCHAR NOT NULL,
          request_source VARCHAR NOT NULL,
          recorded_at TIMESTAMPTZ NOT NULL,
          PRIMARY KEY (snapshot_id, block_name, accession_number)
        );

        CREATE TABLE IF NOT EXISTS block_classifications (
          snapshot_id VARCHAR NOT NULL,
          cik BIGINT NOT NULL,
          stratum VARCHAR NOT NULL,
          block_name VARCHAR NOT NULL,
          block_sha256 VARCHAR NOT NULL,
          n_records BIGINT NOT NULL,
          n_samples BIGINT NOT NULL,
          classification VARCHAR NOT NULL,
          new_requests BIGINT NOT NULL,
          cached_requests BIGINT NOT NULL,
          elapsed_ms DOUBLE NOT NULL,
          classified_at TIMESTAMPTZ NOT NULL,
          PRIMARY KEY (snapshot_id, block_name)
        );

        CREATE TABLE IF NOT EXISTS timestamp_rules (
          rule_id VARCHAR PRIMARY KEY,
          rule_level VARCHAR NOT NULL
            CHECK (rule_level IN ('cik', 'block', 'segment')),
          cik BIGINT NOT NULL,
          snapshot_id VARCHAR,
          block_name VARCHAR,
          block_sha256 VARCHAR,
          valid_from_date DATE,
          valid_to_date DATE,
          interpretation VARCHAR NOT NULL
            CHECK (interpretation IN ('eastern', 'utc')),
          evidence_count BIGINT NOT NULL DEFAULT 0,
          confidence DOUBLE
            CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 1),
          status VARCHAR NOT NULL DEFAULT 'provisional'
            CHECK (status IN ('provisional', 'verified', 'rejected')),
          method VARCHAR NOT NULL,
          active BOOLEAN NOT NULL DEFAULT true,
          notes VARCHAR,
          created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
          CHECK (
            (rule_level = 'cik' AND block_name IS NULL) OR
            (rule_level IN ('block', 'segment') AND block_name IS NOT NULL)
          ),
          CHECK (
            rule_level <> 'segment' OR
            valid_from_date IS NOT NULL OR valid_to_date IS NOT NULL
          ),
          CHECK (
            valid_from_date IS NULL OR valid_to_date IS NULL OR
            valid_from_date <= valid_to_date
          )
        );

        CREATE TABLE IF NOT EXISTS rule_evidence (
          rule_id VARCHAR NOT NULL,
          accession_number VARCHAR NOT NULL,
          evidence_role VARCHAR NOT NULL
            CHECK (evidence_role IN (
              'training', 'validation', 'boundary', 'exception'
            )),
          observed_interpretation VARCHAR NOT NULL
            CHECK (observed_interpretation IN (
              'eastern', 'utc', 'anomalous', 'unresolved'
            )),
          added_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
          PRIMARY KEY (rule_id, accession_number)
        );

        CREATE TABLE IF NOT EXISTS submission_overrides (
          accession_number VARCHAR PRIMARY KEY,
          cik BIGINT NOT NULL,
          zip_acceptance_datetime TIMESTAMP NOT NULL,
          corrected_acceptance_datetime TIMESTAMP NOT NULL,
          interpretation VARCHAR NOT NULL
            CHECK (interpretation IN ('eastern', 'utc', 'anomalous')),
          evidence_source VARCHAR NOT NULL
            CHECK (evidence_source IN ('sgml', 'old_zip', 'manual')),
          source_url VARCHAR,
          reason VARCHAR NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp,
          updated_at TIMESTAMPTZ NOT NULL DEFAULT current_timestamp
        );

        INSERT INTO schema_versions (component, version)
        VALUES ('acceptance_timestamp', 1)
        ON CONFLICT (component) DO UPDATE SET
          version = greatest(schema_versions.version, excluded.version),
          applied_at = now();

        CREATE OR REPLACE VIEW active_timestamp_rules AS
        SELECT *
        FROM timestamp_rules
        WHERE active AND status <> 'rejected';
        """
    )
    _create_resolver(con)


def _create_resolver(con):
    con.execute(
        """
        CREATE OR REPLACE MACRO resolve_acceptance_timestamp(
          p_cik,
          p_accession_number,
          p_snapshot_id,
          p_block_name,
          p_block_sha256,
          p_filing_date,
          p_zip_acceptance_datetime
        ) AS TABLE (
          WITH exact_override AS (
            SELECT corrected_acceptance_datetime,
                   interpretation,
                   'submission_override' AS provenance,
                   accession_number AS reference_id,
                   4 AS precedence
            FROM submission_overrides
            WHERE accession_number = p_accession_number
              AND cik = p_cik
          ),
          matching_rules AS (
            SELECT
              CASE
                WHEN interpretation = 'eastern'
                  THEN p_zip_acceptance_datetime
                WHEN interpretation = 'utc'
                  THEN (p_zip_acceptance_datetime AT TIME ZONE 'UTC')
                       AT TIME ZONE 'America/New_York'
              END AS corrected_acceptance_datetime,
              interpretation,
              rule_level || '_rule' AS provenance,
              rule_id AS reference_id,
              CASE rule_level
                WHEN 'segment' THEN 3
                WHEN 'block' THEN 2
                WHEN 'cik' THEN 1
              END AS precedence,
              updated_at
            FROM active_timestamp_rules
            WHERE cik = p_cik
              AND (snapshot_id IS NULL OR snapshot_id = p_snapshot_id)
              AND (block_name IS NULL OR block_name = p_block_name)
              AND (block_sha256 IS NULL OR block_sha256 = p_block_sha256)
              AND (valid_from_date IS NULL OR p_filing_date >= valid_from_date)
              AND (valid_to_date IS NULL OR p_filing_date <= valid_to_date)
            QUALIFY row_number() OVER (
              ORDER BY precedence DESC, confidence DESC NULLS LAST,
                       evidence_count DESC, updated_at DESC, rule_id
            ) = 1
          ),
          resolved AS (
            SELECT corrected_acceptance_datetime,
                   interpretation,
                   provenance,
                   reference_id,
                   precedence
            FROM exact_override
            UNION ALL
            SELECT corrected_acceptance_datetime,
                   interpretation,
                   provenance,
                   reference_id,
                   precedence
            FROM matching_rules
            WHERE NOT EXISTS (SELECT 1 FROM exact_override)
          )
          SELECT corrected_acceptance_datetime,
                 interpretation,
                 provenance,
                 reference_id,
                 precedence
          FROM resolved
          UNION ALL
          SELECT NULL::TIMESTAMP,
                 'unresolved',
                 'unresolved',
                 NULL::VARCHAR,
                 0
          WHERE NOT EXISTS (SELECT 1 FROM resolved)
        );
        """
    )
