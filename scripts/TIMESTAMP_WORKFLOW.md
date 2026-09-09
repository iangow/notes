# Accession-first timestamp repair

This is the proposed streamlined workflow and its measured baseline as of
2026-09-08. The older `SEC_TIMESTAMP_FIX.md` describes the exploratory pipeline
that produced the 2026-09-07 reference file. The baseline below does not use
that pipeline's inferred block/CIK rules, live JSON, or SGML.

## Preserve the raw clocks

Extract both the May 2024 and current `submissions.zip` snapshots with
`acceptanceDateTime` preserved as VARCHAR. Keep the snapshots separate.
Accession number identifies a filing; CIK and physical source file identify
its occurrences. The JSON `Z` suffix is not sufficient evidence of UTC.

The existing `filings_2024_full.parquet` has TIMESTAMPTZ values, so it is not a
raw input for this experiment. `extract_timestamp_clocks.py` reads every CIK
JSON member of the original ZIP and creates a four-column projection:
`cik`, `accessionNumber`, `acceptanceDateTime`, and `source_file`. It preserves
the original timestamp text and includes historical submissions files. It is
an analysis projection, not a replacement for the full `filings_raw.parquet`.
The 2024 projection contains 24,319,342 rows.

## Shared conversion test

For an accession, gather distinct parsed wall clocks. If there are exactly
two clocks, let `earlier` and `later` be their chronological order. Accept
the pair only when:

```sql
(earlier AT TIME ZONE 'America/New_York') =
(later AT TIME ZONE 'UTC')
```

Store the resulting TIMESTAMPTZ instant, both original clocks, and the evidence
source. This tests the complete date/time, including seconds, date rollover,
and the named zone's daylight-saving offset. A four- or five-hour difference
alone is insufficient. Either source can supply the UTC clock.

Identical clocks provide no timezone evidence. Missing/unparseable values,
more than two distinct clocks, and non-equivalent pairs are not resolved by
this conservative baseline. Conflicting inferred instants must not be silently
overwritten. All forms are eligible for these pairwise tests, including EFFECT,
CORRESP, UPLOAD, and DRSLTR: there is no EDGAR-hours premise here.

## Step 1: Compare snapshots

For accessions present in both raw snapshots, combine their distinct clocks
and apply the conversion test. The accepted instant applies to every current
row for that accession, irrespective of its CIK or physical JSON block.

This does not assume all 2024 clocks are Eastern, nor extend evidence from one
accession to other rows in its block. Different CIK coverage in the snapshots
does not prevent a match because the key is the accession number.

## Step 2: Compare current CIK occurrences

Within the current raw snapshot, select accessions appearing under multiple
CIKs and apply the same conversion test to their distinct clocks. Add the
accepted instants not already supplied by step 1. When both steps resolve an
accession, require agreement and retain both evidence sources.

The analysis database stores `snapshot_pair_overrides`,
`current_duplicate_overrides`, their combined `accession_timestamp_overrides`,
and `pair_conflicts`. None of these results depends on production rules.

## Comparison with the September 7 output

Reference: the 26,437,329-row `filings.parquet` installed after the cached-SGML
corrections. Comparison keys are `(source_file, accessionNumber)`. Input paths,
sizes, and modification times are recorded in the analysis database's `inputs`
table. `comparison` preserves each reference instant and its provenance.

| Evidence | Distinct accessions | Current rows resolved |
|---|---:|---:|
| Step 1, including overlap with step 2 | 7,253,120 | 11,544,683 |
| Step 2, including overlap with step 1 | 2,803,396 | 6,359,318 |
| Both steps | 2,603,013 | 5,900,768 |
| Additional from step 2 | 200,383 | 458,550 |
| Combined, without double counting | 7,453,503 | 12,003,233 |

Together the steps resolve **45.40%** of current rows. There are no conflicts
between the steps. Of the resolved rows, 11,996,623 agree with the reference
and 6,610 differ. Every disagreement is a reference row labelled
`unresolved_raw_as_eastern`: the new cross-snapshot evidence resolves cases
that the previous pipeline left at a fallback. None disagrees with a reference
row resolved by an exact override or an inferred rule.

For example, accession `0000002488-23-000129` has current raw clock
`2023-07-20 20:12:08` and a matching 2024 Eastern clock of
`2023-07-20 16:12:08`. The pair resolves to `2023-07-20 20:12:08+00`.
The reference instead interpreted `20:12:08` as Eastern because it lacked
an applicable correction.

The two steps leave **14,434,096 rows** without pair evidence:

| Reference interpretation of unresolved-by-pairs rows | Rows |
|---|---:|
| Matches raw clock interpreted as Eastern | 13,417,254 |
| Matches raw clock interpreted as UTC | 1,016,842 |

If an unverified Eastern fallback is added, the result agrees with the
reference on **25,413,877 rows (96.13%)**. That is agreement, not verified
coverage. It leaves 1,016,842 rows where the reference uses UTC plus the
6,610 new pair-supported corrections where the reference used its fallback.
The reference itself is not assumed to be ground truth.

## Subsequent evidence and materialization

### Uniform live-file inference

After the three direct-pair stages, `infer_live_file_timezones.py` uses their
resolved instants to classify observed live clocks in each source file. A
file is eligible only if all its classifiable anchor observations agree on
one timezone and none contradicts the anchor instant. Files without anchors
are left unclassified. The working assumption is that other cached clocks in
that same file use the same convention. This is explicitly a file-level
inference, not a direct pair match for every accession.

Every candidate instant is checked against the prior three steps, successful
cached SGML observations, explicit submission overrides, and candidates from
other files for the same accession. Conflicting accessions are rejected.
SGML is validation evidence here, not an input to file classification.
Direct accession evidence takes precedence over inferred file semantics.

On 2026-09-08 the inference classified 22,235 files as UTC and 14,456 as
Eastern using only steps one through three as anchors. No candidate accession
conflicted with the validation evidence. It added 994,426 accessions covering
1,450,584 current rows beyond the three steps; 804,071 rows change from the
unverified Eastern fallback. Of these additional rows, 1,417,805 match the
September 7 reference. The 32,779 disagreements consist of 32,172 ordinary
fallback rows, 145 special-form fallback rows, and 462 block-rule rows.

The resulting prospective pipeline has evidence for 13,875,392 rows. Only
106,573 reference corrections are still absent (101,356 block-rule rows,
3,342 CIK-rule rows, 1,857 segment-rule rows, and 18 exact-override rows),
down from 878,789 before this inference. With an explicit Eastern fallback,
26,282,622 rows agree with the reference. Agreement is not proof of correctness.

```bash
uv run python scripts/infer_live_file_timezones.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --output output/timestamp_baseline/live_file_inference_v2.duckdb \
  --promote-overrides
```

Use a new output path on reruns. The analysis database retains file rules,
anchor counts, source timestamps, candidate instants, and rejections. Promotion
rebuilds `live_json_file_overrides` in the production evidence database.
The materializer reads it through `effective_submission_overrides` after
explicit accession overrides, with interpretation `live_file_inferred`.
No live Parquet was regenerated by this step, and no network requests were
needed. The first attempted analysis output (without the `_v2` suffix) was
aborted before inference and is not a result database.

### Sizing a live-JSON third step

The 1,016,842 unresolved-by-pairs rows whose reference instant interprets the
raw clock as UTC span 71,706 physical blocks, 71,663 CIKs, and 761,898 distinct
accessions. These counts describe a gap against the reference, not independently
known errors in the new baseline.

The existing production database already has 1,892,320 live JSON observation
rows across 11,866 source URLs in `live_json_timestamp_observations`; fetch
completion and missing-row counts are in `live_json_comparison_runs`.
For the 1,016,842-row gap specifically:

| Stored evidence | Current rows covered |
|---|---:|
| Matching source-file/accession live JSON clock | 164,212 |
| Of those: identical to the ZIP clock | 151,193 |
| Of those: exact ZIP-UTC/live-Eastern pair | 13,019 |
| No matching source-file/accession live JSON clock | 852,630 |
| Cached SGML acceptance timestamp | 58,929 |

The live and SGML counts overlap. Existing live-derived accession overrides,
propagated across CIKs, already match the reference instant for 22,191 of these
rows. Thus useful cached evidence is not limited to a same-file live match.
Identical clocks still do not establish a timezone.

For a practical third stage, select blocks containing unresolved raw clocks
after 22:00 or before 06:00, from 2003 onward, excluding only EFFECT (so this
version includes CORRESP, UPLOAD, and DRSLTR). This selects 37,792 blocks and
37,723 CIKs. Of those, 9,174 have a successful previous comparison run and
28,618 do not. The selected blocks contain 865,077 of the 1,016,842 gap rows;
the outside-hours filter will not capture the whole gap.

Use cached live comparisons and accession evidence first, then fetch the
missing live files and compare all eligible rows within selected blocks.
The earlier run's targets came from a different, more heavily corrected
Parquet and excluded correspondence forms, so its completion list alone does
not prove coverage under this expanded policy. Missing accessions may also
have moved into different live historical files. Fetch status, accession
coverage, and resolved timezone must remain separate concepts.

The baseline-driven collection was started on 2026-09-08 with:

```bash
uv run python scripts/compare_live_json_timestamps.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --include-correspondence --promote-overrides \
  --workers 8 --max-requests-per-second 8 --batch-blocks 50
```

It selected exactly 28,618 previously uncollected blocks. Selection uses the
baseline only; comparisons cover every non-EFFECT inventory row in each
selected block, not just outside-hours rows. Rerunning the command skips
successful checkpoints. `--list-only` prints the pending block count without
fetching or writing. The running process logs to
`/private/tmp/edgar-live-json-baseline-20260908.log` and does not rematerialize
`filings.parquet` automatically.

The run finished in 4,519.49 seconds (75.3 minutes). It attempted all 28,618
blocks, matched 4,424,843 rows, reported 162,768 missing rows, and recorded
eight failed blocks for retry. There were no accession-correction conflicts.

Beyond the two pairwise baseline steps, this run newly resolves 100,611
accessions covering 173,155 current rows. Of those rows, 108,913 change from
the unverified Eastern fallback; the remaining 64,242 gain evidence confirming
that interpretation. Including earlier cached live JSON, step three resolves
272,033 additional accessions covering 421,575 rows, of which 131,104 change
from the Eastern fallback. Together with steps one and two, this yields
12,424,808 rows with accession-level pair evidence.

Among the additional 421,575 rows, 412,830 agree with the September 7 reference
and 8,745 differ: 7,827 previously used block rules, 20 CIK rules, 876 the
ordinary unresolved fallback, and 22 the special-form fallback. These are
differences from the reference, not conflicts between accepted accession
corrections. Exact live-pair evidence reproduces the reference's UTC instant
for 130,206 of the previously identified 1,016,842-row gap. No Parquet was
rematerialized as part of collection.

Start with the two pairwise steps above. Then compare live JSON for unresolved
accessions, using the same exact conversion test. Use cached SGML, then new
SGML checks, where pair evidence is absent or contradictory. Successful direct
SGML evidence remains an accession-level correction. Differences with pair
evidence should be retained and investigated.

Outside-hours rows can prioritize investigation, but outside-hours status is
neither required to resolve a pair nor proof that a corrected timestamp is
wrong. Identical ZIP/live clocks still leave the interpretation unknown.
Do not promote an accession's evidence to a uniform block rule without an
independently justified model and validation.

For a streamlined materializer, join the combined accession table to raw rows
by accession number and use its stored TIMESTAMPTZ directly. Mark remaining
rows unresolved; if a compatibility fallback is desired, label it explicitly.
Later evidence should feed the same materialization path rather than editing
Parquet timestamps through separate repair scripts.

This experiment has **not** replaced the production database, integrated the
new snapshot-pair table into the production materializer, or changed the live
Parquet. Its results make that migration reviewable before changing the
existing fallback and precedence behavior.

## Reproduce

### Step 5: Old rules as a targeting diagnostic

After the transient SGML retry, 104,098 rows still lacked the old inferred
block/CIK/segment correction. `build_old_rule_live_targets.py` freezes their
29,001 physical blocks (28,973 CIKs) as targets. The old rule's timestamp is
used only to identify and later evaluate the targets, never to establish a
new corrected instant. Of these rows, 102,072 lacked a same-file live match;
2,985 target blocks had already had a successful live comparison.

`compare_live_json_timestamps.py --target-database ... --follow-history`
fetches the target files and searches linked historical JSON when accessions
have moved. Observations retain their actual live source URL for subsequent
file-timezone inference. Partial successful matches survive historical-fetch
failures, and checkpoints newer than the target set's creation time allow
resuming this follow-up separately from earlier collections.

The initial 50-block trial compared 26,788 rows and found 3,203 consistent
accession candidates in 12.42s, with no errors, missing matches, or conflicts.
The remaining blocks were launched with `run_old_rule_live_followup.py`, which
automatically runs file-timezone inference after collection and reports how
many original target rows now have evidence, including agreement/disagreement
with the old rules. It does not replace the production Parquet.

```bash
uv run python scripts/run_old_rule_live_followup.py \
  --targets output/timestamp_baseline/old_rule_live_targets.duckdb \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --output output/timestamp_baseline/live_file_inference_step5.duckdb
```

The background log is `/private/tmp/edgar-old-rule-live-step5-20260908.log`.

### Independently selecting outside-hours SGML checks

`build_outside_hours_sgml_queue.py` selects the first SGML investigation group
without attaching the production SGML database or using the reference
timestamps. It reconstructs file consensus from JSON-only `file_candidates`
before SGML validation and combines it with the first three steps. Unresolved
rows receive an explicitly labelled Eastern fallback for this screening only.
The selection is strictly outside 06:00 through 22:00 New York time, from 2003
onward, excluding only EFFECT. It preserves rows and deduplicates the fetch
queue by accession number.

The frozen queue in `output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb`
contains 13,696 rows, 11,106 accessions, 7,849 blocks and 7,697 CIKs. Only after
freezing it did we inspect SGML: 456 accessions already had timestamps, covering
469 selected rows; 403 of those rows disagreed with the prospective timestamp.
The remaining 10,650 accessions needed fetching. A 50-accession trial finished
in 8.8 seconds without errors; the remaining 10,600 were started as a resumable
background run on 2026-09-08.

```bash
uv run python scripts/build_outside_hours_sgml_queue.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --live-inference output/timestamp_baseline/live_file_inference_v2.duckdb \
  --output output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb

uv run python scripts/collect_queued_sgml.py \
  --queue output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb
```

The collector consults cached SGML first, promotes successful exact timestamps
to `submission_overrides`, and fetches only uncached accessions with eight
workers at up to eight requests per second. Writes occur after 50 requests;
no database connection is held during network fetches. Failures are cached;
use `--retry-errors` to retry them. The background log is
`/private/tmp/edgar-outside-hours-sgml-20260908.log`. It does not regenerate
the live Parquet. The queue without the `_v2` suffix was an aborted metadata
write, not a completed queue.

The background collection completed in 3,345.3 seconds (55.8 minutes), after
the initial trial. Of 11,106 queued accessions, 10,924 yielded successful
timestamps (13,506 selected rows). The remaining 182 accessions cover 190
rows: 88 HTTP 503 responses, 35 timeouts, and 59 headers without an
ACCEPTANCE-DATETIME tag. The 123 request failures are retry candidates;
missing tags should be tracked separately rather than repeatedly fetched.

The targeted retry (`collect_queued_sgml.py --retry-transient-only`) recovered
121 of those 123 request failures in 31.3 seconds. Two accessions still
returned HTTP 503: `9999999994-25-000194` and `0001481057-24-014665`.
The 59 missing-tag cases were not retried. Successful timestamps and exact
overrides were saved; the live Parquet remained unchanged. Counts below
describe the initial Step 4 run, before this retry.

Step 4 changes 3,000 rows (2,942 accessions) compared with the pre-SGML
prospective output and supplies evidence for another 5,680 previously
unresolved rows. The prospective pipeline now has evidence for 13,881,072
of 26,437,329 rows. Non-EFFECT outside-hours rows fall from 13,696 to 10,709:
10,519 have SGML-confirmed outside-hours clocks and 190 lack a successful
SGML timestamp. Outside-hours status alone does not justify another shift.

Against the frozen September 7 reference, 26,284,524 prospective timestamps
agree. There are 104,122 reference corrections still lacking evidence in the
new process: 99,163 block-rule rows, 3,100 CIK-rule rows, 1,857 segment-rule
rows, and only two exact-override rows. A separate 48,683 rows have evidence
that disagrees with the reference; those must not be described as missing
corrections. These are prospective results; no live Parquet has been replaced.

The shell commands below assume DATA_DIR and RAW_DATA_DIR are exported; shell
expansion does not read the project's `.env` automatically. Use a new analysis
database filename on reruns. Existing outputs are deliberately not overwritten.

```bash
uv run python scripts/extract_timestamp_clocks.py \
  "$RAW_DATA_DIR/submissions/submissions-2024.zip" \
  output/timestamp_baseline/2024/filings_raw_clocks.parquet

uv run python scripts/analyze_timestamp_pair_baseline.py \
  --old-raw output/timestamp_baseline/2024/filings_raw_clocks.parquet \
  --raw "$DATA_DIR/edgar/filings_raw.parquet" \
  --reference "$DATA_DIR/edgar/filings.parquet" \
  --database output/timestamp_baseline/pair_baseline.duckdb
```

The extraction took 51 seconds and the analysis took 66 seconds on the current
machine. No network requests were needed. Regression tests cover cross-snapshot
pairs, current cross-CIK pairs, equal clocks, invalid clocks, and an incorrect
winter four-hour offset.
