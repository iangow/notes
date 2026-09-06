# SEC acceptance timestamp repair

This directory contains exploratory tools for diagnosing and repairing mixed
time-zone semantics in SEC `submissions.zip` acceptance timestamps.

## Data layout

Set these variables in the project `.env` file on each computer:

```text
DATA_DIR="/path/to/Dropbox/pq_data"
RAW_DATA_DIR="/path/to/Dropbox/raw_data"
SEC_USER_AGENT="Your Name your.email@example.com"
```

The scripts expect these Dropbox files:

```text
$RAW_DATA_DIR/submissions/submissions-2024.zip
$RAW_DATA_DIR/submissions/submissions.zip
$DATA_DIR/submissions/filings.parquet.bak-20260906-105247
$DATA_DIR/edgar/filings.parquet.bak-20260906-bad-timeline
$DATA_DIR/edgar/acceptance_timestamp_reference.duckdb
```

The first ZIP and Parquet file are the trusted May 2024 snapshot. The unqualified
ZIP and `bad-timeline` Parquet are from 2026. Allow Dropbox to finish syncing
before opening the DuckDB database, and use only one database writer at a time.

Install dependencies and test the timestamp-rule schema:

```bash
uv sync
uv run python scripts/test_acceptance_timestamp_db.py
```

## Current findings

The archival SGML `<ACCEPTANCE-DATETIME>` is an Eastern clock value. The 2026
ZIP mixes two meanings despite consistently appending `Z`:

- ZIP minus SGML is `0`: the ZIP contains an Eastern clock value.
- ZIP minus SGML is `240` or `300` minutes: the ZIP contains UTC.

The treatment is often constant within a CIK or JSON block, but not always.
CIK 102729 (Valmont Industries) is a useful counterexample: its 2026-02-17 8-K
is UTC-converted, while its 2026-02-23 10-K is unchanged. Mixed regions may
therefore require dated segments or per-submission overrides.

## Diagnostic commands

Compare the 2024 and 2026 Parquet timelines:

```bash
Rscript scripts/analyze_filing_timestamp_diffs.R
```

Compare stratified common observations with both ZIPs and SEC SGML:

```bash
uv run python scripts/compare_filing_timestamp_sources.py --per-group 3
```

Sample filings added after the 2024 snapshot:

```bash
uv run python scripts/sample_new_filing_timestamp_sources.py --per-stratum 2
```

Test repeated filings within historically mixed CIKs:

```bash
uv run python scripts/sample_cik_timestamp_consistency.py \
  --cik-count 6 --per-cik 5
```

## SGML cache and rule database

Run a small stratified benchmark. It stores complete SGML headers, timings,
samples, and provisional block classifications in the DuckDB database:

```bash
uv run python scripts/benchmark_sgml_block_sampling.py \
  --ciks-per-stratum 1 \
  --samples-per-block 3 \
  --max-blocks-per-cik 4
```

Rerunning the same command uses cached SGML observations. To investigate a
specific CIK and date range:

```bash
uv run python scripts/benchmark_sgml_block_sampling.py \
  --cik 102729 \
  --since 2024-05-21 \
  --samples-per-block 9
```

The schema is defined in `acceptance_timestamp_db.py`. Resolution precedence is:

1. `submission_overrides`
2. dated segment rule
3. whole-block rule
4. CIK rule
5. unresolved

The database also contains `sgml_observations`, `block_samples`,
`block_classifications`, `timestamp_rules`, and `rule_evidence`.

## Important limitations

The production-wide classifier is not implemented yet. In particular, the
benchmark does not automatically promote classifications into `timestamp_rules`
or create `submission_overrides`.

`fix_filing_timeline.py` only replaces timestamps for accessions found in the
trusted 2024 Parquet file. It does not fix new-only observations. Likewise,
`extract_filings.py` currently treats every raw ZIP clock as Eastern, which is
known to be incorrect for the mixed 2026 ZIP. Do not overwrite the live Parquet
file with either script without retaining a backup.

The intended production workflow is:

1. Inventory physical blocks in both ZIP snapshots.
2. Reserve a deterministic portion of the 2024 overlap as holdout data.
3. Use the remaining overlap to classify shared submissions and block regions.
4. Fetch and cache SGML anchors for new tails and blocks without old evidence.
5. Subdivide mixed blocks chronologically; use accession overrides when needed.
6. Validate inferred rules against the 2024 holdout.
7. Materialize a corrected Parquet file with provenance for every timestamp.

Commit `09a118c` introduced the timestamp tools. Commit `e5061cb` added the
portable Dropbox paths and the provisional update to `datetimes.qmd`.
