# SEC acceptance timestamp repair

This directory contains exploratory tools for diagnosing and repairing mixed
time-zone semantics in SEC `submissions.zip` acceptance timestamps.

For the proposed accession-first workflow and its independent comparison with
the September 7 output, see [TIMESTAMP_WORKFLOW.md](TIMESTAMP_WORKFLOW.md).
The sections below retain the history and instructions for the existing
exploratory pipeline; its block/CIK inference is not part of that new baseline.

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
$DATA_DIR/edgar/filings_2024_full.parquet
$DATA_DIR/submissions/filings.parquet.bak-20260906-105247
$DATA_DIR/edgar/filings.parquet.bak-20260906-bad-timeline
$DATA_DIR/edgar/acceptance_timestamp_reference.duckdb
```

The 2024 ZIP and `filings_2024_full.parquet` are the trusted May 2024 snapshot.
The older `filings.parquet.bak-20260906-105247` file is also trusted, but it was
created by an older CIK-limited extractor and has fewer rows. The unqualified ZIP
and `bad-timeline` Parquet are from 2026. Allow Dropbox to finish syncing before
opening the DuckDB database, and use only one database writer at a time.

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

## Timestamp Semantics

The SEC `submissions.zip` field `acceptanceDateTime` is treated as a raw text
clock reading. The trailing `Z` in the JSON is not trusted as a reliable UTC
timezone indicator for all rows in the 2026 ZIP. Raw extracted data should
therefore live in `filings_raw.parquet` with `acceptanceDateTime` preserved as
`VARCHAR`.

The DuckDB database stores a parsed raw clock as `zip_acceptance_datetime`,
which is a naive `TIMESTAMP`. Rules describe how to interpret that raw clock:

- `eastern`: the raw clock already represents New York local time. The
  corrected timestamp is the raw clock encoded as `America/New_York`.
- `utc`: the raw clock represents UTC. The corrected timestamp is converted
  from UTC into New York local time, then encoded as `America/New_York`.
- `anomalous`: no block/CIK rule should be inferred. Use an accession-level
  override when a specific corrected timestamp is known.
- `unresolved`: no timestamp rule applies.

In SQL terms, `resolve_acceptance_timestamp(...)` returns a local New York
`corrected_acceptance_datetime` as a naive `TIMESTAMP`, plus provenance. The
Parquet materialization step is responsible for encoding that local corrected
timestamp as `TIMESTAMP WITH TIME ZONE` in `America/New_York`.

The schema is defined in `acceptance_timestamp_db.py`. Resolution precedence is:

1. `submission_overrides`
2. dated segment rule
3. whole-block rule
4. CIK rule
5. unresolved

The database also contains `sgml_observations`, `block_samples`,
`block_classifications`, `timestamp_rules`, `rule_evidence`, and
`duplicate_accession_timestamp_overrides`.

`submission_overrides` are exact accession-level corrections and take
precedence over all inferred rules. Dated segment rules apply only within their
`valid_from_date`/`valid_to_date` bounds. Whole-block rules apply to one
physical JSON block, identified by `snapshot_id`, `block_name`, and
`block_sha256`. CIK rules are a fallback for CIKs whose trusted overlap
evidence is uniform across blocks.

`duplicate_accession_timestamp_overrides` handles accessions that appear in
multiple CIK JSON rows with conflicting raw ZIP timestamps. When an accession
has exactly two distinct raw clocks and interpreting the earlier clock as
`America/New_York` and the later clock as `UTC` produces the same instant, the
earlier clock is stored as the corrected New York local acceptance timestamp.
These overrides apply by accession number across all duplicate rows, after
explicit `submission_overrides` and before inferred segment/block/CIK rules.
Build or refresh them with:

```bash
uv run python scripts/apply_duplicate_accession_timestamp_overrides.py \
  --all \
  --promote-overrides
```

For the `d5ddef93bf6bed0e` inventory, this deterministic rule produced
2,803,396 accession-level overrides covering 6,359,318 raw rows, including
955,384 non-correspondence outside-hours rows. All conflicting duplicate
accessions had exactly two raw timestamp values separated by 240 or 300
minutes, and every retained case resolved to a single timezone-aware instant
under the Eastern-vs-UTC interpretation.

SGML evidence is used only to classify or verify rules. The SGML
`<ACCEPTANCE-DATETIME>` value is treated as authoritative for sampled
accessions. Comparing the raw ZIP clock to the SGML clock gives the
interpretation:

- difference of `0` minutes -> `eastern`
- difference of `240` or `300` minutes -> `utc`, reflecting daylight/standard
  time offsets from New York
- anything else -> `anomalous`

Blocks marked in `missing_sgml_timestamp_blocks` or
`sgml_anchor_excluded_blocks` are skipped by SGML collection so retry loops do
not keep revisiting known finite exception categories. These tables are audit
exclusions, not timestamp rules. Rows covered only by those exclusions remain
unresolved until a manual exception policy or override is applied.

Three correspondence-related form types still need a separate policy:
`CORRESP`, `UPLOAD`, and `DRSLTR`. The SGML boundary pilot excluded these forms
because they can behave differently from ordinary filing records. In the current
ZIP inventory (`d5ddef93bf6bed0e`) they account for 260,271 `CORRESP` rows,
237,217 `UPLOAD` rows, and 5,730 `DRSLTR` rows. Treat these as a known open
category, not as evidence that the ordinary Eastern/UTC classifier failed.

The existing SGML observations do not support a single form-level or global
date-cutoff rule for these forms: observed `CORRESP`, `UPLOAD`, and `DRSLTR`
rows include both Eastern and UTC interpretations, and several filing dates have
both interpretations. However, observed special-form samples are stable within
their physical JSON blocks so far. The working policy is therefore:

1. Apply ordinary `submission_overrides`, segment rules, block rules, and CIK
   rules to these rows when such rules exist.
2. Do not infer an interpretation from the form type alone.
3. Do not apply a global filing-date cutoff unless later evidence supports one.
4. If no rule applies, materialize the row using the raw ZIP clock parsed as
   Eastern and mark it `special_form_unresolved_raw_as_eastern` so it remains
   auditable and separable from ordinary unresolved rows.

## Build persisted rules

Inventory the 2026 ZIP blocks and derive conservative block-level rules from
the trusted 2024 overlap:

```bash
uv run python scripts/build_acceptance_timestamp_rules.py
```

This adds `zip_snapshots`, `zip_blocks`, and `zip_filing_records` tables to the
DuckDB database. It uses `$DATA_DIR/edgar/filings_2024_full.parquet` when
present, falling back to the older smaller trusted backup only if the full file
does not exist. It then populates `block_classifications`,
`timestamp_rules`, and `rule_evidence` for blocks and CIKs whose overlap
observations are uniformly Eastern or UTC. Mixed blocks and CIKs remain
unresolved unless a more specific block rule applies.

To rebuild the ZIP inventory:

```bash
uv run python scripts/build_acceptance_timestamp_rules.py --force-inventory
```

After the inventory and rules exist, materialize a corrected Parquet file from
the raw expanded filings:

```bash
uv run python scripts/materialize_corrected_filings.py
```

The default raw input is `$DATA_DIR/edgar/filings_raw.parquet`; the default
output is `/private/tmp/filings.parquet`. The output preserves the expanded
columns, replaces `acceptanceDateTime` with a timezone-aware timestamp, and
adds `timestamp_provenance`, `timestamp_reference_id`, and
`timestamp_interpretation`.

By default, materialization refuses to write if timestamped raw rows have no
rule. To produce an audit file anyway, parsing unresolved raw ZIP clocks as
Eastern and marking their provenance, use:

```bash
uv run python scripts/materialize_corrected_filings.py --allow-unresolved
```

To collect SGML anchors for unresolved blocks and promote sampled evidence into
verified rules:

```bash
uv run python scripts/fetch_sgml_anchors.py --max-blocks 100
```

The SGML anchor fetcher is resumable through `sgml_observations` and skips
blocks that already have active rules. It creates block rules when all sampled
SGML anchors agree and the valid evidence count reaches `--min-evidence`,
capped by the number of filings in the block. For example, a two-filing block
can be resolved from two agreeing SGML anchors even when `--min-evidence 3` is
used for larger blocks. If older samples lack `<ACCEPTANCE-DATETIME>` but later
usable anchors agree, it creates a dated segment rule starting at the first
usable SGML sample date, leaving the older no-tag records unresolved for a
separate exception pass. Increase `--max-blocks` gradually, and use
`--order size` to prioritize row coverage or `--order hash` for a more
representative deterministic pass. Use `--max-requests-per-second` to tune SEC
network pacing; cache hits are not delayed.

For longer runs, use concurrent SGML fetching with batched DuckDB writes:

```bash
uv run python scripts/fetch_sgml_anchors.py \
  --max-blocks 100000 \
  --samples-per-block 3 \
  --min-evidence 3 \
  --order size \
  --max-requests-per-second 9.5 \
  --workers 8 \
  --write-batch-blocks 50 \
  --write-lock-timeout 300
```

The worker threads only perform cache reads and network fetches. DuckDB writes
are concentrated into short batch transactions, and write-lock conflicts are
retried for up to `--write-lock-timeout` seconds.

## Outside-Hours SGML Scans

Outside-hours rows are a useful way to find remaining suspicious timestamp
regions. Figure 4 in `published/datetimes.qmd` defines these as rows whose
acceptance clock is after 22:00 or before 06:00 New York time. The exploratory
collector excludes `EFFECT`, `CORRESP`, `UPLOAD`, and `DRSLTR` by default and
starts with recent filings:

```bash
uv run python scripts/collect_outside_hours_sgml.py \
  --max-blocks 100 \
  --since-date 2025-01-01 \
  --max-prefix 100 \
  --workers 8 \
  --max-requests-per-second 8
```

Outside-hours rows are used to select suspicious physical JSON blocks. Once a
block is selected, the scan starts at the first outside-hours row in that block
and then walks through all non-excluded timestamped rows from that point
downward until the first Eastern SGML observation appears, because a filing need
not be outside EDGAR hours to have a UTC-encoded ZIP clock. The working
assumption is that this UTC run followed by Eastern observations marks a modern
UTC segment sitting above an older Eastern region. If sampled rows below the
first Eastern observation are UTC, the scan reports `reversal`; that is evidence
that the simple boundary process needs review.

The collector records direct SGML evidence in `sgml_observations`,
`block_samples`, and `outside_hours_scan_results`. The first outside-hours row
is an anchor showing that at least one row in the block is suspicious; it is not
assumed to be the first UTC row, because in-hours rows can also be UTC. The
collector therefore does not promote `prefix_and_last_utc` evidence into a rule
by itself. A promoted segment rule needs a true boundary search over all
non-excluded rows or another conservative policy such as exact accession-level
overrides for directly observed rows. Use `--no-promote-rules` to collect
evidence without creating segment rules, and use
`--promote-observed-overrides` when directly observed SGML rows should be
written to `submission_overrides`.

The single raw-to-corrected materialization process is
`materialize_corrected_filings.py`. It reads `filings_raw.parquet` and the
DuckDB database, promotes eligible stored outside-hours scan results into
`timestamp_rules`, and writes `filings.parquet`. Use
`--no-promote-collected-rules` when the database should be opened read-only and
no stored evidence should be promoted during materialization.

`prefix_capped_utc` means the checked top-of-block prefix was uniformly UTC
and a larger `--max-prefix` is needed before concluding where the first Eastern
observation occurs. By default the scan also checks the last non-excluded row in
the block when the prefix is all UTC; `prefix_and_last_utc` means both the
prefix and the oldest checked row were UTC.

Use `--full-scan --order fewest-rows` for small exploratory batches where every
eligible row in each selected block should be checked. This is useful for
learning whether blocks are all UTC, all Eastern, cleanly segmented, or mixed in
a way that invalidates the simple boundary model.

A 200-block full scan of small 2025+ outside-hours blocks produced 186
`full_scan_all_utc` blocks and 14 `full_scan_mixed_reversal` blocks. The mixed
cases were concentrated in two-row patterns, especially `4:eastern -> 3:utc`
(11 of 14 mixed blocks). This suggests that some small blocks may need
form/accession-level treatment rather than a simple block chronology rule.

If a pass finds blocks where every sampled SGML response lacks
`<ACCEPTANCE-DATETIME>`, mark those blocks so later SGML collection runs do not
keep revisiting them:

```bash
uv run python scripts/mark_missing_sgml_timestamp_blocks.py
```

Use `--report-only` to inspect candidates without marking them. These blocks
remain unresolved for timestamp materialization until a separate finite
exception policy is applied.

If retry passes leave blocks unresolved because sampled SGML requests return
terminal fetch errors, mark those separately so collection does not keep
retrying them:

```bash
uv run python scripts/mark_sgml_anchor_excluded_blocks.py
```

This writes `terminal_fetch_failure` rows to `sgml_anchor_excluded_blocks`.
Use `--report-only` to inspect candidates first. These are audit exclusions,
not timestamp rules; timestamp materialization still treats the underlying rows
as unresolved until a manual exception policy is applied.

## Important limitations

The implemented classifier is intentionally conservative. It promotes uniform
overlap evidence into verified block and CIK rules, and SGML anchor evidence
into block or first-valid-date segment rules. It does not infer full dated
segments within mixed modern blocks, does not create `submission_overrides`, and
does not yet infer new rules from the special `CORRESP`/`UPLOAD`/`DRSLTR`
category.

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

### Outside-hours follow-up after duplicate corrections (2026-09-07)

`collect_outside_hours_sgml.py` now selects targets from the current corrected
`filings.parquet` (`--filings` overrides the path). It measures times in
`America/New_York`, using strictly after 22:00 or before 06:00 as in
`published/datetimes.qmd`, and excludes EFFECT, CORRESP, UPLOAD, and DRSLTR.
Existing block rules do not exclude targets by default: these are residual
issues despite those rules. `--dry-run` lists targets without fetching or writing.

The date cutoff selects target rows only. Scans start at the top of each
physical JSON block and include all eligible records, including in-hours and
older records. A UTC prefix is followed until the first non-UTC observation;
tail checks test for reversals. Checking a distant last row does not establish
an exact boundary. The scan policy is `outside-hours-corrected-top-v2`, separate
from earlier raw-clock scans.

The corrected input had 8,653 non-excluded outside-hours rows in 2025 and 4,027
in 2026. A five-block trial targeting the largest residual counts took 32.38s:
20 observations (9 fetched, 11 cached), 20 exact accession overrides, and no
inferred rules. All five blocks had an Eastern top record and three sampled
lower UTC records: CIK0001350487, CIK0002056263, CIK0001473845,
CIK0001473606, and CIK0001476530. These samples do not establish a single
transition or prove that every lower record is UTC.

Trial command:

```bash
uv run python scripts/collect_outside_hours_sgml.py \
  --max-blocks 5 --max-prefix 20 --no-check-last --tail-checks 3 \
  --batch-blocks 5 --no-promote-rules --promote-observed-overrides
```

Observations and exact overrides are stored in DuckDB. The existing
`materialize_corrected_filings.py` consumes these accession overrides; the
trial did not regenerate `filings.parquet`. Further scans should retain
`--no-promote-rules` while the reversed/mixed ordering is investigated.

The subsequent full scan of CIK0002056263.json checked all 154 eligible
filings in 176.33s (128 network requests, 26 cached). Record 0,
0001076809-26-000019 (SCHEDULE 13G/A), is Eastern in the ZIP; all 153
remaining eligible records are UTC. There were no unresolved observations.
All 154 exact accession overrides were persisted, without an inferred rule
or Parquet regeneration. Five excluded-form records were not SGML-checked.

The live https://data.sec.gov/submissions/CIK0002056263.json was also compared
on 2026-09-07. It contained 159 matching accessions. Only record 0 had the
same timestamp clock as the ZIP; 124 live clocks were four hours earlier and
34 were five hours earlier. All 154 live clocks with SGML evidence matched
the Eastern SGML clock exactly, despite the live JSON strings ending in `Z`.
Thus this live file is consistently Eastern for the checked records, whereas
the archived ZIP block is mixed. Do not interpret its `Z` suffix literally
or generalize this result to every live JSON file without further checks.

### Comparing Live JSON With ZIP Clocks

`compare_live_json_timestamps.py` compares each matched accession's two clocks
using both assignments of UTC and America/New_York. It accepts a correction
only when exactly one assignment produces the same instant, including the
date and daylight-saving offset. Equal clocks supply no new timezone evidence.
Unexplained differences and disagreements with existing accession corrections
are not promoted. This does not assume uniform timezone interpretation across
a whole block or infer unchanged rows from changed neighbors.

Live source clocks are retained in `live_json_timestamp_observations` and
inferred Eastern clocks in `live_json_timestamp_overrides`. The latter joins
the materializer through `effective_submission_overrides`, behind explicit
SGML/submission overrides. Conflicting live corrections are excluded via
`live_json_timestamp_conflicts`. The corrected output continues to use
`submission_override` provenance, with the accession as its reference ID.

```bash
uv run python scripts/compare_live_json_timestamps.py \
  --all-outside-hours --promote-overrides
```

This selects blocks with residual outside-hours observations in the current
`filings.parquet`, from 2003 onward by default, in New York time. EFFECT,
CORRESP, UPLOAD, and DRSLTR are excluded both from target selection and row
comparison. It compares all other matching rows in each selected block, not
only outside-hours rows. Defaults: eight workers, eight requests per second,
and writes after each 50-block batch. Successful blocks are checkpointed in
`live_json_comparison_runs`; rerunning resumes, while `--include-done` revisits
completed blocks. Missing accessions (e.g., moved to a different live file)
and HTTP errors are counted separately. A successful comparison does not
mean every accession was found or that every clock was resolved.

Use repeatable `--block-name CIK0002056263.json` for explicit blocks, or
`--max-blocks 50` for a bounded trial. Without `--promote-overrides`, results
are printed without persistent writes. Rematerialize through the existing
`materialize_corrected_filings.py` process afterward.

The initial 50-block batch compared 27,192 rows in 10.34s: 104 live-UTC
pairs, seven ZIP-UTC pairs, and 27,081 unchanged clocks. It yielded 110
distinct consistent accession candidates, no conflicts, and 906 missing
accessions. There were 11,952 target blocks in the corrected input.

An exploratory check of excluded forms in the first five fetched live files
found three CORRESP and one UPLOAD pairs resolving as ZIP-UTC/live-Eastern,
plus five unchanged CORRESP clocks; there were no DRSLTR examples. This
supports testing the same pairwise method for these forms, but they remain
excluded from the broad run pending a separate decision.

### Promoting Cached SGML For Residual Cases

`apply_cached_sgml_overrides.py` finds non-excluded outside-hours rows in the
current corrected Parquet (2003 onward) that disagree with successful cached
SGML observations. `--promote-overrides` writes exact `submission_overrides`
with SGML source URLs. These take precedence over inferred block rules and
JSON-pair corrections. It does not change the Parquet itself.

```bash
uv run python scripts/apply_cached_sgml_overrides.py \
  --fetch-identical 12 --promote-overrides
```

The optional fetch count checks recent residual rows with identical ZIP/live
clocks and no cached timestamp, one per physical block, before promoting the
evidence. On 2026-09-07 all 12 checked clocks were Eastern according to SGML,
but the existing inferred UTC block rules had shifted them five hours early.
Together with cached evidence, this run created 2,283 accession corrections
covering 2,522 residual rows. No uniform replacement block rule was inferred.
After rematerialization, non-excluded outside-hours rows fell from 18,168 to
15,662 (2025: 6,283 to 4,631; 2026: 1,293 to 766). The full output retained
26,437,329 rows and matched every stored exact SGML override. The preceding
Parquet was archived before installing the replacement.

Separately, all 1,626 residual rows with explainable ZIP/live differences
already matched their inferred instants in the Parquet. An explainable
conversion does not guarantee that the resulting time is within EDGAR hours.

Commit `09a118c` introduced the timestamp tools. Commit `e5061cb` added the
portable Dropbox paths and the provisional update to `datetimes.qmd`.
