# Parquet evidence storage

## Migration status (September 10, 2026)

`timestamp_parquet_archive.py` provides a non-destructive bridge: export an
existing DuckDB to an immutable directory of Parquet tables, then reconstruct
a working DuckDB when needed. Collection and inference scripts still use their
existing databases. This is not yet a Parquet-native collection pipeline.

Initial snapshots are under `output/timestamp_parquet/20260910/`:

| Directory | Source and purpose |
|---|---|
| `evidence/` | All 20 tables in `acceptance_timestamp_reference.duckdb`, plus definitions of its two resolver views. Includes observations, errors, fetch/comparison checkpoints, legacy rules and rebuildable ZIP inventories. |
| `accepted/` | Selected tables from frozen `effect_evaluation.duckdb`: `resolved_accessions`, `accession_evidence`, `evidence_disagreements`, `inputs`, `workflow_metadata`, and `summary`. |
| `paired_audit/` | All seven tables of the frozen 10,000-row paired-audit report, including predictions, observations, strata, weights and source-version metadata. |

`accepted/resolved_accessions.parquet` is the accepted-timestamp dataset:
10,714,350 distinct accessions, with `corrected_instant` as TIMESTAMPTZ and
`provenance`. It covers 16,463,879 current filing rows. Raw-as-Eastern fallbacks
are deliberately absent. `accession_evidence.parquet` retains the candidate
evidence and priority used to select accepted values. Neither repeated
publication nor agreement with a fallback makes that fallback verified.

The observational cache is newer than this frozen accepted set and includes
the subsequent audit collection. Exporting observations does not promote
audit evidence into corrections or recompute the frozen audit predictions.
The historical audit report retains its original streamlined predictions;
the later equal-cache replay is a separate analysis.

The existing production `filings.parquet`, raw Parquet files, source databases,
ZIP files and analysis artifacts are unchanged. The snapshot does not embed
external input Parquet/ZIP files: `inputs` records their original paths and
fingerprints. Preserve those files separately. These snapshots are currently
in the repository's generated `output/` directory, not Dropbox or Git.

## Export and restore

```bash
uv run --frozen python scripts/timestamp_parquet_archive.py export \
  --database /path/to/evidence.duckdb \
  --output /path/to/new-snapshot/evidence

uv run --frozen python scripts/timestamp_parquet_archive.py restore \
  --snapshot /path/to/new-snapshot/evidence \
  --output /path/to/new-working.duckdb --memory-limit 8GB
```

Existing destinations are refused. The exporter reads a consistent transaction
through a read-only connection. It verifies each table before publishing the
directory by rename. Failed exports/restores leave no published destination.
The restore CLI also stages its database before publication.
Its default memory cap is 2GB; reconstructing the full legacy database's
primary-key indexes exceeds that cap. Use the larger cap shown above for it.

Each directory has ordinary table Parquet files and three Parquet manifests:

- `manifest.parquet`: table names, filenames, original table DDL, column names
  and types, row counts, order-independent row hashes, and SHA-256 file digests.
- `metadata.parquet`: archive format version, source database path and file
  metadata, export time, DuckDB version, and whether this is a partial export.
- `objects.parquet`: view and explicit index definitions for full exports.

Source tables named `metadata`, `manifest`, or `objects` receive disambiguated
filenames recorded in the manifest. Restores execute the stored schema SQL:
only restore trusted archives. This bridge supports these main-schema evidence
databases, not arbitrary DuckDB extensions, macros, sequences or foreign-key
dependency graphs. Partial exports (`--tables ...`) omit views and explicit
indexes; table-declared constraints remain in their DDL. Working analytical
indexes can be rebuilt as needed.

Checks preserve column types, nulls, raw clock strings, DATEs, SGML wall clocks
(TIMESTAMP), accepted instants (TIMESTAMPTZ), errors and provenance. HUGEINT
totals use DECIMAL(38,0) in Parquet and restore as HUGEINT; values beyond that
decimal range fail instead of silently losing precision. Other unsupported
type changes also fail. Row hashes are supplementary checks, not proofs of
equality; they are compared on restore only with the same DuckDB version.
SHA-256 checks are version-independent. Exact bidirectional row comparisons
and constraint/view checks are covered by the small round-trip tests.

Ordinary tools can read each Parquet directly without a persistent DuckDB.
The reconstructed `accepted` database has the `resolved_accessions` and
`inputs` tables required by the materializer's `--workflow-database` mode;
normal raw-input fingerprint checks still apply.

The initial Parquet snapshots occupy approximately 1.1GB (evidence), 334MB
(accepted) and 1.3MB (audit). All three snapshots were successfully rebuilt
as DuckDB databases, including the full evidence database with its constraints
and views using the 8GB memory cap. Validation found 10,714,350 unique, non-null
accepted accession/instant/provenance records and zero exact differences from
the frozen source across all accepted instants and provenance values. The
scripts' regression suite passes all 24 tests. Reconstructed verification
databases are named `*_roundtrip.duckdb` alongside the snapshot directories;
these are derived artifacts, not additional sources of truth.

## Target steady-state layout

The next migration stage should separate durable evidence from disposable
working tables, rather than repeatedly copying the whole legacy database:

- Versioned raw filings and the previous published `filings.parquet`.
- Append-only live-JSON observation batches, keyed by source URL, accession,
  and retrieval version. The current cache retains only the latest observation
  per URL/accession; exporting it cannot recover already overwritten history.
- SGML observations and attempts, including known missing tags separately from
  retryable network failures. Preserve URLs, retrieval times and available
  headers/digests. Existing failed parses may not retain a response body.
- Accepted accession instants with evidence provenance, status and conflicts;
  retain learning even when an accession disappears from a later snapshot.
- Derived rules with their evidence, scope, snapshot and inference version.
  Legacy block rules are not interchangeable with accepted exact instants.
- Run/input manifests and request-attempt logs. Existing comparison checkpoints
  are not complete HTTP request logs; the exporter cannot manufacture these.
- Independently frozen audit samples, predictions, weights and results.

Future collectors should publish immutable batch files plus a committed batch
manifest, and never amend a Parquet in place. Consumers should read only batches
listed in published manifests, not indiscriminately glob old full snapshots
(which would double-count evidence). Compaction must preserve retrieval history,
keys and conflicts. DuckDB becomes a rebuildable query engine and working cache.

The previous corrected Parquet can replace the 2024 bootstrap reference after
validation, but only alongside provenance identifying evidence-supported values
versus defaults. Keep the 2024 bootstrap and current databases until that
transition has been demonstrated. No deletion is part of this migration.
