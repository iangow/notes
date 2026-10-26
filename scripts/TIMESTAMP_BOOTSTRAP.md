# Updating from a previous corrected release

> Historical workflow checkpoint (26 October 2026). New operational work belongs
> in [`sec_submissions`](https://github.com/iangow/sec_submissions).
> See [the migration plan](SEC_SUBMISSIONS_MIGRATION.md) before using these scripts
> for another release; their preserved inference policy predates newer package fixes.

## Normal Parquet interface

Readers need not create or maintain a database. `process_filings.py` accepts
the raw and preceding corrected Parquet files, uses a temporary DuckDB for
computation, and removes it after writing the candidate and Parquet diagnostics:

```bash
uv run --frozen python scripts/process_filings.py \
  --raw /path/to/new-snapshot/filings_raw.parquet \
  --previous /path/to/filings_previous.parquet \
  --cache-dir /path/to/parquet-observations \
  --output /path/to/new-snapshot/filings.parquet
```

The cache is optional. It contains `live_json_timestamp_observations.parquet`
and/or `sgml_observations.parquet`, not an accepted-instants database. Accepted
instants and their provenance are carried in the main corrected Parquet.
Retain the observation cache, failed attempts and frozen audit files separately.
Those can cover absent accessions and must not be overwritten by a later release.
For a subsequent candidate, add
`--sgml-observations '/path/to/previous-audit/observations-*.parquet'` to reuse
the previous audit's SGML observations. This is explicit, after that audit has
been scored; it never changes the audited candidate or its saved predictions.
Conflicting valid SGML instants are retained as disagreements rather than
silently choosing an observation. No separate accepted-instants file is required.
The processor reuses available observations; missing new coverage still requires
collection. It does not silently claim that a cache completes a new snapshot.

The worked example has two updates. The initial update applies the May 2024
reference to the ZIP downloaded on September 5, 2026. The subsequent update
uses that corrected Parquet as `--previous` with the September 30 ZIP. The May
2024-derived reference's Eastern convention is an explicit historical
assumption. Literal-midnight clocks are marked unverified, not promoted to
anchors. This helper must not be used to treat arbitrary new ZIPs as uniformly
Eastern. Two diagnostic audits of interim second-update candidates informed
additional SGML collection; those observations were used before a new candidate
was frozen. The reader-facing result is from a fresh independent audit of that
final candidate. A later update can replace the report while these dated audit
artifacts remain archived.

```bash
uv run --frozen python scripts/download_submissions.py \
  /path/to/20260905/submissions.zip

uv run --frozen python scripts/extract_filings.py \
  /path/to/20260905/submissions.zip \
  /path/to/20260905/filings_raw.parquet --max-seconds 0

uv run --frozen python scripts/extract_timestamp_clocks.py \
  /path/to/submissions-2024.zip /path/to/2024/filings_raw_clocks.parquet

uv run --frozen python scripts/make_previous_filings.py \
  --raw /path/to/2024/filings_raw_clocks.parquet \
  --output /path/to/2024/filings_previous.parquet

uv run --frozen python scripts/process_filings.py \
  --raw /path/to/20260905/filings_raw.parquet \
  --previous /path/to/2024/filings_previous.parquet \
  --cache-dir /path/to/parquet-observations \
  --live-observations /path/to/20260930/live_json_timestamp_observations.parquet \
  --live-observations /path/to/20260905/supplement_live_json_timestamp_observations.parquet \
  --output /path/to/20260905/filings.parquet

uv run --frozen python scripts/download_submissions.py \
  /path/to/20260930/submissions.zip

uv run --frozen python scripts/extract_filings.py \
  /path/to/20260930/submissions.zip \
  /path/to/20260930/filings_raw.parquet --max-seconds 0

uv run --frozen python scripts/process_filings.py \
  --raw /path/to/20260930/filings_raw.parquet \
  --previous /path/to/20260905/filings.parquet \
  --cache-dir /path/to/parquet-observations \
  --live-observations /path/to/current-json/live_json_timestamp_observations.parquet \
  --live-observations /path/to/20260905/supplement_live_json_timestamp_observations.parquet \
  --sgml-observations '/path/to/diagnostic-audit-1/observations-*.parquet' \
  --sgml-observations '/path/to/diagnostic-audit-2/observations-*.parquet' \
  --sgml-observations /path/to/20260930/recent_unanchored_sgml_observations.parquet \
  --output /path/to/20260930/anchored/filings.parquet

uv run --frozen python scripts/audit_filings.py \
  --filings /path/to/20260930/anchored/filings.parquet \
  --output /path/to/20260930/anchored/audit_10000_seed202609304 \
  --sample-size 10000 --seed 202609304 --workers 16 --rate 7
```

The audit sample and predictions are frozen before reference lookup. For an
independent release audit, omit `--cache` so every sampled accession receives a
fresh SGML request. Errors are not repaired in place, and transient failures
receive a retry on the same sample. All outputs are Parquet; the audit uses only
an in-memory DuckDB. The confidence bound concerns the verifiable
subpopulation, not rows without an obtainable reference timestamp.
`sample_identifiers.csv` contains the selected row identifiers and frozen
predictions for transparency. Keep diagnostic audits separate from the final
independent audit. When a later snapshot is audited, retain this dated audit and
replace only the reader-facing results with the later independent audit; older
paired development audits remain separate artefacts.
After inspecting diagnostics and audit results, use `publish_filings.py` as
described in Step 4 below. These commands never update the shared file implicitly.

## Timing fresh live-JSON coverage

`benchmark_recent_live_json.py` freezes unresolved rows whose raw Eastern-fallback
clock is on or after an explicit cutoff, samples their source blocks, and compares
all raw rows in each selected block with live JSON. Selection does not read audit
errors or SGML availability. Linked historical JSON is searched when necessary;
all forms are eligible. Existing supported candidate instants and exact clock pairs
can anchor the newly retrieved live files. Unchanged clocks alone supply no anchor.

```bash
uv run --frozen python scripts/benchmark_recent_live_json.py \
  --filings output/sec_submissions_workflow/20260930/filings.parquet \
  --raw output/sec_submissions_workflow/20260930/filings_raw.parquet \
  --output output/sec_submissions_workflow/20260930/recent_live_trial_200 \
  --since-date 2024-01-01 --sample-blocks 200 --seed 202609301 \
  --workers 16 --rate 7
```

Use a fresh output directory for another trial. The script saves the population
queue, sampled block identifiers, input SHA-256 fingerprints, observations,
comparisons, file evidence and timing summary as Parquet. It does not alter either
filings input, frozen audit predictions, or the production evidence database.

The September 30 trial on the 2024-derived baseline selected 200 of 112,674
unresolved blocks dated 2024 onward. Queue
preparation took 5.3 seconds; collection including batch writes took 29.1 seconds.
The 200 HTTP requests matched all 15,732 comparison rows, with no failed blocks or
missing matches. Scaling the collection time by the number of blocks gives
4.56 hours for this queue at seven requests per second.

Of the 1,011 unresolved target rows in the trial, 929 gained comparison evidence,
including 910 changed instants. The other 82 rows occupy 54 live files with no
existing anchor. They remain unresolved, not Eastern-confirmed.

The complete collection command uses `--all-unresolved-blocks`:

```bash
uv run --frozen python scripts/benchmark_recent_live_json.py \
  --filings output/sec_submissions_workflow/20260930/filings.parquet \
  --raw output/sec_submissions_workflow/20260930/filings_raw.parquet \
  --output output/sec_submissions_workflow/20260930/recent_live_collection_20260930 \
  --since-date 2024-01-01 --all-unresolved-blocks --seed 202609301 \
  --workers 16 --rate 7
```

The run writes selection metadata, every 50-file observation and request-result
batch, and a final summary as Parquet. If interrupted, rerun the identical
command with `--resume`; it verifies the input hashes and frozen selection,
then continues from completed batches and retries failed files once. Keep the
same cutoff, seed, worker count, rate, candidate, raw file, and output directory
when resuming.

The full live-JSON refresh processed all 112,674 blocks in 4 hours 32 minutes,
matching 8,743,640 filing rows with no failed blocks or missing matches. The
comparisons yielded 25,375 live-UTC and 37,317 ZIP-UTC clock pairs, plus one
unexplained difference; 74,326 response versions were classified UTC and 7,093
Eastern. After two diagnostic audits identified errors in the unanchored
fallback group, a targeted SGML queue covered 21,609 recent unruled response
versions. It fetched one anchor for singleton versions and the first and last
accessions for multi-accession versions: 23,906 requests, with 23,905 timestamp
tags and one 404. These anchors added 27,640 supported rows relative to the
preceding candidate. The one unavailable header was retained as such.

## Low-level reproduction interface

The database-oriented commands below remain available for reproducing historical
stages and inspecting individual queries. They are not required by the normal
Parquet interface above. An existing database path is refused only to avoid
overwriting the results of a low-level run.

The initial worked update starts from the May 2024-derived Parquet reference and
the new snapshot's `filings_raw.parquet`. Subsequent updates start from the
previous corrected `filings.parquet` and do not require the May 2024 ZIP or its
raw Parquet. The original two-archive route remains available in
`analyze_timestamp_pair_baseline.py` for reproducing the historical analysis.

For a later update, download the processed filings file linked from the
dates-and-times note and verify that it is the intended preceding release.
Retain a dated copy of the starting release. Preserve each new ZIP and extract
its raw tables into a separate snapshot directory as described in
[EXTRACT_FILINGS.md](EXTRACT_FILINGS.md).

## 1. Bootstrap accepted instants

```bash
uv run --frozen python scripts/bootstrap_timestamp_workflow.py \
  --prior-filings /path/to/releases/filings.parquet \
  --raw /path/to/new-snapshot/filings_raw.parquet \
  --output output/new-snapshot/bootstrap.duckdb
```

The output database must not already exist. This command reads the two Parquet
files and writes a new working database; it does not fetch data or alter either
input. `--raw` defaults to `DATA_DIR/edgar/filings_raw.parquet`.

The previous timestamp column must be TIMESTAMPTZ, and `timestamp_provenance`
must be present. The new timestamp column must be VARCHAR. Matching is by
accession number, not CIK or file name. The supported prior provenance values
are `snapshot_pair`, `cross_cik_pair`, `live_pair`, `live_file_inferred`,
`sgml`, `submission_override`, and `duplicate_accession_override`.
`trusted_snapshot_eastern` is additionally supported for an explicitly prepared
historical reference. Unknown provenance, legacy block/CIK rules, missing
timestamps, and unresolved raw-as-Eastern defaults do not become accepted
anchors.

For each accession with supported prior evidence, all usable prior rows must
agree on one non-null instant. Every current clock must reproduce that instant
when interpreted either as UTC or America/New_York. An accession failing these
checks is recorded in `bootstrap_rejections` and receives no baseline override.
The existing two-clock, cross-CIK comparison is also run on the new raw data;
conflicts between that evidence and prior supported instants are rejected.
The prior `timestamp_interpretation` also permits reconstruction of its source
clock for an exact cross-snapshot pair test. An unresolved fallback can
contribute that clock as a comparison value, but the fallback instant itself is
never inherited or treated as an anchor. Unsupported prior values do not veto a
valid new pair.

The database retains `prior_release_evidence`, `prior_accession_evidence`,
`prior_clock_checks`, and `bootstrap_rejections`, including inherited
provenance and reference IDs. `resolved_accessions` contains the accepted
instants with their original provenance, not a generic "previous release"
label. `inputs` fingerprints the raw and prior files. `comparison` includes
unresolved and new accessions; absence from the prior release is not an error.

## 2. Extend evidence where needed

Use `bootstrap.duckdb` wherever the existing workflow takes `--baseline`.
The live comparison, file inference, SGML queue and evaluation stages remain
separate; their commands and selection policies are documented in
[TIMESTAMP_WORKFLOW.md](TIMESTAMP_WORKFLOW.md). The bootstrap alone does not
resolve every new filing or conduct a fresh quality audit.

Before using the live collector on a new ZIP, register that snapshot's inventory
in the evidence database. This requires only the **new** ZIP:

```bash
uv run --frozen python scripts/build_acceptance_timestamp_rules.py \
  --zip /path/to/new-snapshot/submissions.zip \
  --database /path/to/evidence.duckdb --inventory-only
```

Retain the observation cache and use the same explicit evidence database for
collection, inference and evaluation. `--inventory-only` does not create the
legacy block/CIK rules. Plan collection from unresolved coverage and the
outside-hours screen; do not rely solely on the latter.

The inference script uses supported prior evidence as validation, including
conflicting prior instants, so file inference cannot silently resolve those
conflicts. The evaluator preserves inherited provenance and copies the prior
evidence and rejection tables into the frozen output. Inspect rejected cases
and any `evidence_disagreements` before release. Independent new evidence can
require investigation of an older accepted value; publication is not an
automatic approval of such a change.

## 3. Materialize and validate a candidate

After the follow-up stages, use their frozen evaluation database. To inspect
bootstrap coverage alone, the bootstrap database is already materializable:

```bash
uv run --frozen python scripts/materialize_corrected_filings.py \
  --workflow-database output/new-snapshot/bootstrap.duckdb \
  --raw /path/to/new-snapshot/filings_raw.parquet \
  --output output/new-snapshot/filings_candidate.parquet \
  --allow-unresolved
```

Use a fresh candidate path, **not the shared current-file path**. The
materializer verifies that the raw input still matches the frozen input,
preserves non-timestamp fields, and checks the output row count. Unresolved
rows require the explicit compatibility option shown above and retain their
fallback labels. They are not made trustworthy by being published repeatedly.

Validate schema, coverage/provenance counts, exact accepted instants,
non-timestamp fields and unexplained changes. Audit a frozen probability sample
before approval. The publisher's structural checks are not a statistical audit
or a substitute for these data-quality checks.

## 4. Roll releases forward without renaming the shared file

Once the candidate is approved:

```bash
uv run --frozen python scripts/publish_filings.py \
  --candidate output/sec_submissions_workflow/20260930/anchored/filings.parquet \
  --current /path/to/current/filings.parquet
```

The publisher requires an explicit path to the current local release and has
no Dropbox dependency. For this worked example, use the local path that maps to
`/pq_data/submissions/filings.parquet`.

By default the publisher:

1. Checks that the candidate is nonempty, has timezone-aware acceptance times,
   and does not drop or change the types of current columns. Extra columns are
   allowed. It computes the candidate's SHA-256 digest.
2. Finishes a backup of the current release before changing any release path.
3. Moves an existing `filings_previous.parquet` into `archive/`, adding a UTC
   timestamp to its name, then installs the backup as `filings_previous.parquet`.
4. Copies the candidate into the **existing** `filings.parquet`, truncates to the
   new length, flushes and fsyncs it, and verifies matching bytes and the
   unchanged local inode. It does not rename, unlink, or replace the current file.

`--previous` and `--archive-dir` override the backup paths. Candidate, current
and previous must be different files; linked aliases and current/previous
symlinks are rejected. The candidate is retained.

The publisher only updates local files; it makes no assumptions about hosted
links. For the Dropbox-hosted worked example, the maintainer can use
`release_filings_dropbox.py` to coordinate the portable publisher with the
Dropbox-specific checks:

```bash
uv run --frozen python scripts/release_filings_dropbox.py \
  --candidate output/sec_submissions_workflow/20260930/anchored/filings.parquet \
  --current "$DATA_DIR/submissions/filings.parquet" \
  --share-url 'https://www.dropbox.com/scl/fi/9osie7ln50z67uzi9zys5/filings.parquet?rlkey=5igrlb23tns4n8trunk3nstlt&dl=0'
```

The wrapper does not pause Dropbox syncing. It asks for confirmation before it
invokes `publish_filings.py`, then waits until Dropbox reports sync is complete
before checking the existing shared link. Because publication updates the
existing file in place and is not atomic, active sync could observe intermediate
bytes and readers may briefly see an incomplete Parquet file. Its default
check follows the link's download response and confirms the Parquet signature
and remote file size match the local candidate. This quick check cannot
distinguish two different releases with the same size. `--verify-sha256`
additionally downloads the entire shared file and compares every byte; this is
stronger but transfers the full file again. `--verify-only` skips local
publication and checks the shared link against the current local release,
which is useful after sync is resumed separately or a previous publication has
already completed.

If the post-sync link check fails, the wrapper offers to restore
`filings_previous.parquet` into the existing current file in place, then verifies
the restored bytes and unchanged inode. Type `RESTORE` only after confirming
Dropbox reported the attempted update as synced. After restoration, wait for
Dropbox to sync again and rerun the wrapper with `--verify-only`. If the link
still fails, pause syncing before further recovery and investigate the Dropbox
file or shared-link state. The wrapper cannot observe Dropbox Desktop's sync
state or confirm its remote revision metadata; do not treat a failed or
incomplete link check as a completed release.

Close readers and writers of these files during publication. In-place
publication is deliberately **not atomic** for concurrent readers. A caught
copy or verification failure restores the current bytes from the backup
without replacing the inode. A force kill or machine failure can leave a
partial current file; retain the backup and restore it in place before
resuming Dropbox sync or rerunning publication. Do not overwrite that backup
with a partial release. Older archived releases are never deleted by this
script.

For the next update, bootstrap from the now-current `filings.parquet`. The
previous and archived releases document earlier published versions; retain
their raw snapshots and evidence separately for full reproducibility.
