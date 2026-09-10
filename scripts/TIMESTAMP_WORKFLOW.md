# Accession-first timestamp repair

The production Parquet was updated on September 10, 2026 using the frozen
accession evidence. See [the release record](TIMESTAMP_RELEASE_20260910.md)
for validation, the archived previous version and report publication details.
Statements below about an unchanged production file describe earlier stages.

Parquet-first storage and the non-destructive export/restore bridge are
documented in [TIMESTAMP_STORAGE.md](TIMESTAMP_STORAGE.md). The first snapshots
preserve the existing evidence, frozen accepted timestamps and paired audit;
the collection scripts still use their current DuckDB databases during migration.

This is the proposed streamlined workflow and its measured baseline as of
2026-09-08. The older `SEC_TIMESTAMP_FIX.md` describes the exploratory pipeline
that produced the 2026-09-07 reference file. The baseline below does not use
that pipeline's inferred block/CIK rules, live JSON, or SGML.

## Steps 6 and 7: evidence-coverage completion (September 9)

Step 6 selects cached live JSON files lacking a JSON-only timezone rule,
without inspecting differences from Monday. With
`infer_live_file_timezones.py --sgml-anchor-unclassified`, successful cached
SGML observations become file-specific anchors. SGML clocks are interpreted
as America/New_York. The uniform-live-file assumption is unchanged: all
available anchors must agree on UTC or Eastern; mixed or contradictory files
receive no rule. Candidate accession instants must also agree across files
and with existing validation evidence. `sgml_anchor_target_files` and
`sgml_file_anchors` record selection and evidence separately. These anchors
do not become mislabeled direct JSON-pair overrides.

The initial unresolved-row screen covered 4,255 unclassified files; 4,254
already had usable SGML anchors. The implementation checks all unclassified
cached files, including files without unresolved current rows. No SGML was
fetched. The frozen `step6_evaluation.duckdb` has:

| Measure | Rows |
|---|---:|
| Evidence-supported | 14,079,322 |
| Additional evidence-supported versus Step 5 | 103,457 |
| Identical to Monday | 26,380,597 |
| Evidence-backed differences from Monday | 51,639 |
| Monday corrections still unresolved | 5,093 |

There are zero disagreements between accepted evidence sources. Neither the
production Parquet nor the Step 5 candidate was replaced.

Step 7 independently selects rows with no accepted instant, a raw clock on
or after 2024-01-01, and no cached live observation for the accession. There
is no reference-timestamp or outside-hours predicate. Correspondence forms
are eligible. `build_recent_live_targets.py` stores only selection fields,
the cutoff, and a creation-time checkpoint. The current queue contains
674,592 rows, 563,591 accessions, 95,190 blocks, and 95,106 CIKs.

`run_recent_live_followup.py` fetches those blocks with the existing collector,
including linked historical files, then reruns inference with cached SGML
anchors and freezes an updated evaluation. Worker count and request rate are
configurable independently. The initial eight-worker run was restarted with
16 workers, retaining the shared eight requests/second limiter; writes occur
in short bursts after 50-block batches.
A 50-block trial took 12.53 seconds with 33,263 matches, zero missing matches,
and zero errors. The full run resumes past completed blocks in this queue.
The subsequent 16-worker trial completed 200 additional blocks in 41.28
seconds, with 81,380 matches, zero missing matches, and zero errors. This is
only a modest throughput improvement over the observed eight-worker run;
the samples contain different blocks, so it is not a controlled benchmark.
It updates evidence in DuckDB but does not replace production Parquet. The
existing collector still excludes EFFECT rows from comparison, even though
the coverage-selection counts above include all forms.
The background log is `/private/tmp/edgar-recent-live-step7-20260909.log`.

```bash
uv run --frozen python scripts/infer_live_file_timezones.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --sgml-anchor-unclassified \
  --output output/timestamp_baseline/live_file_inference_step6.duckdb

uv run --frozen python scripts/evaluate_timestamp_workflow.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --live-inference output/timestamp_baseline/live_file_inference_step6.duckdb \
  --sgml-queue output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb \
  --output output/timestamp_baseline/step6_evaluation.duckdb

uv run --frozen python scripts/build_recent_live_targets.py \
  --workflow-database output/timestamp_baseline/step6_evaluation.duckdb \
  --output output/timestamp_baseline/recent_live_targets.duckdb

uv run --frozen python scripts/run_recent_live_followup.py \
  --workers 16 --max-requests-per-second 8 \
  --targets output/timestamp_baseline/recent_live_targets.duckdb \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --sgml-queue output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb \
  --inference-output output/timestamp_baseline/live_file_inference_step7.duckdb \
  --evaluation-output output/timestamp_baseline/step7_evaluation.duckdb
```

Use fresh output paths when rebuilding analyses; retain the target database
when resuming collection. For subsequent ZIP snapshots, keep accepted
accession instants and their evidence, rebuild unresolved coverage against
the new raw data, and apply the same selection rules. Raw clocks alone must
not override previously verified instants. The recent cutoff is explicit and
configurable, not a claim that older unresolved clocks are verified.

The operational target is to complete Steps 1 through 7 within 24 hours.
Current individual-stage timings suggest this is feasible, but a complete
timed run has not established it. More workers can hide network latency;
they do not raise the shared request limit. Preserve caches and completed
batch checkpoints, and avoid overlapping collectors with separate rate
limiters. Historical-file selection and repeated per-batch scans/writes are
further optimization candidates if network throughput is no longer limiting.

## Completed Step 7 and remaining-case classification (September 9)

The restarted 16-worker collection completed its 92,790 blocks in 14,604.06
seconds (4 hours 3 minutes). The frozen `step7_evaluation.duckdb` contains
16,441,506 evidence-supported rows, 9,995,823 unresolved rows, 26,369,087
instants matching Monday, 63,151 evidence-backed differences, and 5,091
Monday corrections still unresolved. Accepted evidence has zero conflicting
instants. Production Parquet remains unchanged.

The diagnostic selection is `corrected_instant IS NULL AND
prospective_instant IS DISTINCT FROM reference_instant` in the frozen
evaluation's `comparison` table. It contains 5,091 rows, 4,961 accessions,
2,657 ZIP blocks, and 2,656 CIKs. All lack cached live observations by
accession; none are cases of unanchored live files or rejected inference.

| Reason | Rows |
|---|---:|
| EFFECT, deliberately excluded by the live collector | 5,089 |
| Other forms, not found by successful live/history searches | 2 |

All selected rows were in the Step 7 target queue, but inclusion in a target
block does not override the collector's EFFECT filter. Successful cached
SGML covers 101 EFFECT rows (87 accessions): 100 agree with Monday, while
one agrees with the current Eastern fallback. The other 4,990 rows have no
cached SGML. Thus disagreement with Monday is not itself proof of an error.

The two non-EFFECT cases are:

| CIK | Accession | Form | ZIP block |
|---|---|---|---|
| 1354457 | 9999999997-25-003336 | 1 | CIK0001354457.json |
| 1146132 | 9999999997-25-002866 | X-17A-5 | CIK0001146132.json |

Their latest live comparison runs have no request error, but each records
one missing match after following historical files. Neither has cached SGML.
Monday classified both raw clocks as UTC using a block rule; that rule is
not independent confirmation of their correct instants.

A further reusable selection should therefore treat EFFECT separately,
and identify other recent unresolved accessions that remain unmatched after
a successful live/history search. Do not use the Monday differences as a
production collection queue. This classification made no network requests
and changed no evidence or Parquet data.

## EFFECT backfill for Steps 5 and 7

The collector previously reused the outside-hours form exclusions when
comparing rows in any selected block. That incorrectly omitted EFFECT from
Steps 5 and 7. `compare_live_json_timestamps.py` now compares all forms in
selected blocks by default. EFFECT remains excluded from outside-hours
target selection, where unusual hours are not useful evidence for that form.
The optional `--only-form EFFECT` restricts a backfill to EFFECT comparisons;
it cannot be combined with outside-hours selection.

`build_effect_live_targets.py` unions the original Step 5 and Step 7 target
blocks and selects EFFECT rows without any cached live clock for the
accession. It uses neither Monday's instants nor unresolved-status filtering:
even previously resolved EFFECT accessions can supply useful live evidence.
The queue has 31,900 rows, 29,217 accessions, 8,017 blocks, and 8,005 CIKs.
Its fresh metadata checkpoint prevents earlier non-EFFECT fetch records from
being mistaken for completed backfill work. Retain this queue when resuming;
do not reuse an EFFECT-only queue as a checkpoint for an all-form collection.

```bash
uv run --frozen python scripts/build_effect_live_targets.py \
  --step5-targets output/timestamp_baseline/old_rule_live_targets.duckdb \
  --step7-targets output/timestamp_baseline/recent_live_targets.duckdb \
  --workflow-database output/timestamp_baseline/step7_evaluation.duckdb \
  --output output/timestamp_baseline/effect_live_targets.duckdb

uv run --frozen python scripts/run_recent_live_followup.py \
  --targets output/timestamp_baseline/effect_live_targets.duckdb \
  --only-form EFFECT --workers 16 --max-requests-per-second 8 \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --sgml-queue output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb \
  --inference-output output/timestamp_baseline/live_file_inference_effect.duckdb \
  --evaluation-output output/timestamp_baseline/effect_evaluation.duckdb
```

Only live JSON is fetched. Inference then uses the accumulated JSON evidence
and cached SGML, applying the same conflict checks as Step 7. The frozen
evaluation includes all forms; production Parquet is not replaced.
The background log is `/private/tmp/edgar-effect-live-20260909.log`.
The initial 50-block trial completed in 14.05 seconds: 234 matches, no missing
matches or request errors, and 78 consistent timezone-pair candidates. The
remaining 7,967 blocks resume separately; the trial checkpoints are retained.

## Stratified fallback audit (September 10)

`build_timestamp_audit.py` freezes a random row sample from the 9,973,450
unverified Eastern fallback rows in `effect_evaluation.duckdb`, before
consulting SGML availability. Acceptance-clock period allocations are:

| Period | Population rows | Sample rows |
|---|---:|---:|
| Before 2003 | 1,782,771 | 300 |
| 2003-2013 | 5,803,181 | 450 |
| 2014-2023 | 2,332,490 | 750 |
| 2024-2026 | 55,008 | 1,500 |

Each period is subdivided by midnight/non-midnight clock and broad form
group (ownership, periodic/current reports, correspondence, EFFECT, other).
Each nonempty cell gets up to five initial places, with remaining places
allocated proportionally to remaining cell population using largest
remainders. Selection uses a seeded hash ranking within each cell. The
frozen queue retains population counts, sample counts, inclusion
probabilities, and inverse-probability weights. Its 3,000 rows represent
2,990 accessions; SGML is fetched once per accession, but every selected row
retains its own outcome and weight.

The reproducibly shuffled 100-accession pilot took 16.2 seconds with eight
workers and an eight requests/second limiter. Nine fetched headers lacked
ACCEPTANCE-DATETIME; all 91 obtained timestamps agreed with Eastern. Including
preexisting cache entries and sampled row multiplicity, the pilot report has
92 Eastern-confirmed rows, 13 unverifiable rows, and 2,895 not yet checked.
These incomplete pilot outcomes are not a population accuracy conclusion.

The full audit was started after the user authorized proceeding if the
projected runtime was under five hours; the pilot projects roughly eight
minutes for remaining fetches. Missing tags and previously cached errors
are retained, not silently replaced with new sample members. Transient
errors can be retried later without changing sample membership.

```bash
uv run --frozen python scripts/build_timestamp_audit.py \
  --workflow-database output/timestamp_baseline/effect_evaluation.duckdb \
  --output output/timestamp_baseline/fallback_audit_3000.duckdb

uv run --frozen python scripts/run_timestamp_audit.py \
  --queue output/timestamp_baseline/fallback_audit_3000.duckdb \
  --output output/timestamp_baseline/fallback_audit_3000_report.duckdb
```

`collect_queued_sgml.py --audit-only` stores observations but does not promote
submission overrides. The report distinguishes Eastern confirmed, UTC
indicated, other discrepancy, unverifiable, and not checked. Its weighted
percentages use the entire target population, not only successfully verified
rows, and are estimates rather than confidence bounds. The simple `3/n`
zero-error bound is not directly applicable to this unequal-probability
sample or to a sample with unverifiable observations. Future inference can
read the newly cached SGML, but no inference or Parquet regeneration is
automatically run by the audit.

Log: `/private/tmp/edgar-fallback-audit-20260910.log`.

The audit completed: remaining collection took 439.8 seconds, in addition
to the 16.2-second pilot. Of 3,000 sampled rows, 2,741 were Eastern-confirmed
and 259 unverifiable, all due to missing ACCEPTANCE-DATETIME tags. There were
no observed UTC or other discrepancies among verifiable rows. Weighted
population estimates are 84.1163% confirmed and 15.8837% unverifiable; these
are not confidence bounds or evidence that unverifiable clocks are correct.

### Midnight-clock diagnostic

| Raw ZIP clock | Eastern confirmed | Missing SGML tag |
|---|---:|---:|
| Midnight (00:00:00) | 0 | 255 |
| Non-midnight | 2,741 | 4 |

All 255 sampled midnight clocks lacked a tag. Four non-midnight missing-tag
exceptions occurred on 2002-04-29, 2002-04-30, 2002-05-10, and 2002-05-14;
these were not midnight after a UTC-to-New-York conversion either. The three
post-2002 missing-tag sample rows had midnight clocks dated 2009-03-23.

An additional nonrandom cache check against the same frozen fallback
population found 1,074 midnight rows (731 accessions) with missing tags,
two midnight rows (one accession) with another error, and no midnight rows
with usable SGML timestamps. Non-midnight rows included 8,801 with usable
timestamps, eight with missing tags, and two with other errors. Cache counts
include the audit and must not be treated as an independent random sample.

This supports deprioritizing raw-midnight fallback clocks as likely
unavailable time-of-day values, not marking them as verified instants.
Known missing-tag accessions should not be repeatedly fetched. A future
skip heuristic should retain occasional random midnight checks and keep
non-midnight early-2002 exceptions distinct. No such skip rule has yet been
enabled and no timestamps were changed by this diagnostic.

### Broader midnight check: blanket exclusion is unsafe

The earlier midnight diagnostic was restricted to fallback rows. A later
check across all raw rows linked to cached SGML, including corrected rows,
found eight literal `T00:00:00.000Z` rows representing six accessions with
usable SGML timestamps. Five accessions have genuine UTC-midnight instants:
their SGML clocks are 19:00 or 20:00 Eastern on the previous day. Examples:

| Accession | JSON clock | SGML Eastern clock |
|---|---|---|
| 0000891092-20-002671 | 2020-03-05T00:00:00.000Z | 2020-03-04 19:00:00 |
| 0000950103-24-011643 | 2024-08-03T00:00:00.000Z | 2024-08-02 20:00:00 |
| 0001193125-09-224187 | 2009-11-05T00:00:00.000Z | 2009-11-04 19:50:02 |

The last example is an anomalous clock rather than a pure timezone shift.
The all-row missing-tag check also found non-midnight clocks: many become
midnight in New York when interpreted as UTC, but 186 accessions (271 rows)
were neither kind of midnight, with raw dates from April 26 to May 14, 2002.
Counts are a snapshot of the growing cache, not results from a random sample.

Therefore neither direction is an equivalence: missing tags do not imply
literal midnight, and literal midnight does not imply a missing tag. Do not
enable a global literal-midnight exclusion. Known missing-tag outcomes are
already persisted in `sgml_observations.error` and skipped by default; keep
them distinct from HTTP errors/timeouts and from verified timestamps. Any
additional date- and evidence-dependent fetch heuristic needs validation.

## Offline collection replay and logged costs (September 10)

Historical logs provide the measured collection baseline below. JSON units
are completed ZIP-block jobs, not individual HTTP requests: a job may follow
historical files. SGML units are accession fetch attempts. These are separate
background-log segments and exclude separately run pilots and retries.

| Collection | Logged completed units | Collection seconds |
|---|---:|---:|
| Step 3 live JSON | 28,618 blocks | 4,519.49 |
| Step 5 live JSON continuation | 28,951 blocks | 4,582.03 |
| Step 7 before restart | 2,150 blocks | 461.8 |
| Step 7 after restart | 92,790 blocks | 14,604.06 |
| EFFECT backfill continuation | 7,967 blocks | 1,264.98 |
| Outside-hours SGML continuation | 10,600 fetches | 3,345.3 |
| Random audit continuation | 2,885 fetches | 439.8 |

Totals: 160,476 JSON block jobs in 25,432.36 seconds and 13,485 SGML fetches
in 3,785.1 seconds, or 8.116 hours combined. This is elapsed collection work,
including parsing and batch writes, not a pure network-time measurement.
Logs live in `/private/tmp/edgar-*.log`; the Step 7 log contains both runs.
Retry/pilot costs and earlier exploratory fetching are additional. Counting
attempted HTTP requests and unique URLs explicitly would improve future
instrumentation, but these logs already support empirical cost estimates.

`replay_timestamp_collections.py` compares cached coverage under three target
plans. It reconstructs Step 3's 37,792 blocks and uses the frozen Step 5
(29,001) and Step 7 (95,190) targets. It recomputes exact live clock pairs and
file inference, holding pre-audit SGML evidence constant. EFFECT is included
in comparison. It never fetches data or changes production outputs.

| Plan | Unique target blocks | Supported rows | Timezone-shifted rows | Frozen shifts lost |
|---|---:|---:|---:|---:|
| Step 7 only | 95,190 | 14,837,287 | 9,020,892 | 723,278 |
| Steps 3 + 7 | 130,036 | 16,315,825 | 9,652,416 | 91,754 |
| Steps 3 + 5 + 7 | 155,816 | 16,396,471 | 9,731,490 | 12,680 |
| Frozen EFFECT evaluation | not a collection plan | 16,463,879 | 9,744,170 | 0 |

Shift means an evidence-backed instant different from the raw-Eastern
fallback, not a change actually written to production Parquet. No accepted
evidence conflicts appeared in these replays. Unique JSON URL lower bounds
(requested block URLs plus reachable cached observation URLs) are 96,168,
131,057, and 156,990 respectively; retries and unsuccessful history lookups
are not represented. Historical cached observations are associated with a
selected block by matching accession and CIK, not a retained fetch trace.

The combined plan still loses support for 67,408 rows, including 12,680
shifts. It is therefore NOT yet a validated replacement. Earlier exploratory
cache coverage, globally recomputed pair decisions versus historical batch
decisions, and cache reachability assumptions need reconciliation. Also,
Step 5 targets depend on legacy rules and Step 7 targets were selected after
earlier stages: these frozen-plan comparisons are not a from-scratch replay
of target generation. Do not infer that later selectors subsume earlier
ones. A merged fetch pass can deduplicate known targets, but dropping
selectors or deploying the consolidated workflow requires further checks.

Outputs: `output/timestamp_baseline/collection_replay/`, one DuckDB per plan,
with targets, reachable observations, evidence, metrics, and assumptions.
The replay regression test checks target filtering, EFFECT inclusion, and
lost-support/lost-shift accounting.

## JSON-first ordering replay (September 10)

`replay_json_first.py` uses the same frozen union of Step 3/5/7 blocks and
reachable cached JSON as the combined-target replay, but applies JSON-only
pair and file inference before selecting SGML. It then rebuilds the
non-EFFECT outside-hours queue and adds unmatched Step 5/7 accessions.
Step 6 uses pre-audit cached SGML to anchor otherwise unclassified files.
Known SGML evidence is also retained for validation. This isolates ordering
from target coverage and makes no network requests or Parquet changes.

| Measure | Result |
|---|---:|
| Outside-hours rows after JSON-only inference | 11,239 |
| Outside-hours accessions | 8,699 |
| Additional unmatched accessions | 4 |
| Combined exact-SGML follow-up queue | 8,703 |
| Usable cached SGML in frozen evidence | 8,639 |
| Known missing-tag cases | 59 |
| Cached request errors | 2 |
| Uncached at the frozen cutoff | 3 |

The old outside-hours queue held 11,106 accessions. All 8,699 newly selected
outside-hours accessions are in that old queue: 2,407 outside-hours checks
are removed, with four unmatched cases added. Final support (16,396,471
rows), timezone shifts (9,731,490 rows), and every prospective row instant
are identical to the previous combined-target replay. There are no accepted
evidence conflicts. This is a 21.6% smaller follow-up queue, not a measured
21.6% runtime improvement or a reduction in the separate cached-anchor work.

The earlier combined replay's 67,408-row support gap and 12,680 lost shifts
relative to the frozen historical workflow remain. This experiment supports
JSON-before-SGML ordering conditional on identical target coverage; it does
not yet establish a complete replacement for the historical process.

Step 6 is cache-only by design, not proof that no useful new SGML anchors
exist. After cached anchoring, 31,990 reachable live files remain unclassified;
31,989 have no anchor evidence and one has conflicting evidence. Of the
unclassified files, 30,590 contain unresolved accessions, including 30,586
with at least one non-midnight live clock. These are potential anchor targets,
not an authorized fetch queue; missing-time conventions and expected yield
still need consideration.

A production design can allow a bounded feedback pass: new SGML evidence
may anchor cached live files, or select an affected live file for collection
when no cached match exists. Recompute file consistency after adding such
evidence, quarantine contradictions, and fetch only new required URLs or
accessions. Do not repeatedly rerun all live collection or treat known
missing SGML tags as a reason to fetch indefinitely.

Output: `output/timestamp_baseline/json_first_replay.duckdb`.

## Paired three-version audit (September 10)

The broader audit samples all 26,437,329 current rows, not just unverified
fallbacks. `build_paired_timestamp_audit.py` freezes 10,000 selected rows
(9,973 accessions) and three predictions before reading SGML availability:

1. Monday: frozen September 7 reference instants in `effect_evaluation`.
2. Last night: `effect_evaluation` prospective instants, including EFFECT
   backfill but not the still-unapplied four-case Step 8.
3. Streamlined candidate: `json_first_replay` resolved instants plus Eastern
   fallbacks. This is the provisional frozen-target ordering replay, not a
   validated end-to-end iterative pipeline. Its known coverage gap remains.

Acceptance-clock period allocations are 1,000 before 2003, 1,500 for
2003-2013, 2,500 for 2014-2023, and 5,000 for 2024-2026. Within periods,
strata also distinguish midnight, form group, last-night correction method,
and whether predictions differ across versions. Each nonempty cell gets up
to five initial places, with remaining capacity-proportional allocation.
Population counts and inclusion probabilities are retained. The sample has
3,913 raw-pair rows, 1,792 live-pair rows, 2,124 live-file-inferred rows,
2,081 fallbacks, and 90 direct-SGML rows.

`report_paired_timestamp_audit.py` evaluates all three predictions against
the same SGML reference instants, assumed America/New_York. It reports
weighted error rates among verifiable rows and weighted unavailable-reference
rates. Whole-population lower/upper estimates treat all unverifiable rows
as correct/incorrect respectively; those ranges are not sampling confidence
intervals. Sampling uncertainty needs separate analysis before drawing
statistical conclusions, especially for rare or zero observed errors.
The frozen predictions are never repaired using the audit before scoring.

```bash
uv run --frozen python scripts/build_paired_timestamp_audit.py \
  --workflow-database output/timestamp_baseline/effect_evaluation.duckdb \
  --streamlined-database output/timestamp_baseline/json_first_replay.duckdb \
  --output output/timestamp_baseline/paired_audit_10000.duckdb

uv run --frozen python scripts/run_timestamp_audit.py --paired \
  --queue output/timestamp_baseline/paired_audit_10000.duckdb \
  --output output/timestamp_baseline/paired_audit_10000_report.duckdb
```

Collection is audit-only, reuses cached SGML, and makes no Parquet or
submission-override changes. It does not enable the proposed midnight skip:
that would introduce selective nonverification into this audit. Cached
missing-tag failures are still retained rather than repeatedly fetched.
Log: `/private/tmp/edgar-paired-audit-20260910.log`.
The 100-fetch timing pilot took 35.4 seconds (15 missing tags and four HTTP
503 errors). With 431 valid cached timestamps before the pilot, the projected
remaining collection is about 55-60 minutes, below the user's two-hour
threshold. The remaining collection was started in the background. No
automatic retries or replacement sample members are added to this run.

## Equal-cache replay correction (September 10)

The first collection replay was not an equal-starting-cache comparison.
Last night's workflow reused earlier exploratory live JSON evidence, but
the replay admitted observations only through reconstructed Step 3/5/7
target blocks. The 27 sampled streamlined errors came from 25 blocks whose
live collection records date to September 7, 16:09-16:29 Eastern. Their
evidence was already present in the pre-Step-5 live-file inference snapshot.

The corrected replay restores all cached live observations retrieved before
`2026-09-08T00:00:00-04:00`, independent of audit outcomes. That inherited
set has 1,369,902 observations, 10,254 source files, and 1,309,696 accessions.
Observations also reachable from current targets are deduplicated. Both
orderings use the same frozen pre-audit SGML table from the original replay;
the new audit SGML does not leak into correction inference.

| Measure | Combined targets with inherited cache | JSON-first with same cache |
|---|---:|---:|
| Current rows | 26,437,329 | 26,437,329 |
| Evidence-supported rows | 16,463,879 | 16,463,879 |
| Evidence-backed shifts versus Eastern fallback | 9,744,170 | 9,744,170 |
| Instants differing from last night's frozen output | 0 | 0 |
| Lost evidence support versus last night | 0 | 0 |
| Exact-SGML follow-up queue | 11,106 | 8,703 |

This eliminates all 67,408 previously missing support rows and all 12,680
lost shifts. Neither adjusted ordering has accepted-evidence conflicts.
The smaller queue removes 2,407 outside-hours accessions and adds four
unmatched accessions. It has 8,639 usable cached SGML timestamps, with the
same remaining missing-tag/request-error/uncached cases as before.

The separate `equal_cache_audit_rescore.duckdb` retains the original sample
and SGML outcomes but scores adjusted predictions: 10,000 rows, 8,995
verifiable, zero errors. Twenty-nine predictions change versus the original
streamlined sample, including all 27 errors and two unverifiable cases.
This is a post-audit descriptive rescore, not a fresh independent audit.
The original audit databases were not modified.

```bash
uv run --frozen python scripts/replay_timestamp_collections.py \
  --output output/timestamp_baseline/equal_cache_replay --union-only \
  --inherited-before 2026-09-08T00:00:00-04:00 \
  --fixed-sgml-from output/timestamp_baseline/collection_replay/steps3_5_7.duckdb

uv run --frozen python scripts/replay_json_first.py \
  --union-replay output/timestamp_baseline/equal_cache_replay/steps3_5_7.duckdb \
  --output output/timestamp_baseline/json_first_equal_cache.duckdb
```

No SEC requests or production Parquet changes were made. This validates the
ordering change conditional on the frozen targets and inherited evidence;
it does not yet implement iterative target generation for a fresh ZIP or
reconstruct a full historical HTTP trace. The inherited file acquisition
cost is a shared starting cost, not zero-cost evidence in a cold-start run.
The earlier cold-coverage replay results remain recorded for transparency
but must not be interpreted as evidence that streamlining loses accuracy.

## Completed Step 5 and candidate output (September 9)

Step 5 completed successfully: all 29,001 target blocks have successful fetch
records, with 2,123,058 matched rows and two missing matches. The continuation
after the initial 50-block trial took 4,582 seconds (76.4 minutes). New live
evidence resolves 93,215 of the 104,098 target rows: 90,633 match the old rule
and 2,582 differ. Inference classified 28,191 live files as UTC and 32,998 as
Eastern. One accession (`0001193125-09-224187`) was excluded from file-level
inference because the inferred midnight clock disagreed with its cached SGML
clock; it was not silently promoted.

`evaluate_timestamp_workflow.py` freezes the entire workflow, including only
queue-selected successful SGML observations from Step 4, in
`output/timestamp_baseline/step5_evaluation.duckdb`. It stores all accepted
accession evidence, its precedence, the selected `resolved_accessions`, and
the per-row comparison with Monday's frozen reference. There are no conflicts
between accepted evidence sources in this snapshot. Old block/CIK/segment
rules supply neither corrections nor fallbacks in the new workflow.

| Comparison with Monday | Rows |
|---|---:|
| Total current rows | 26,437,329 |
| Identical instants | 26,374,849 (99.7637%) |
| New evidence gives a different instant | 51,595 |
| Old correction not reproduced; new workflow unresolved | 10,885 |

The 51,595 evidence-backed differences comprise 40,703 rows where Monday used
a fallback and 10,892 where it used a rule or override. The 10,885 missing
corrections comprise 10,861 block-rule rows, 14 segment-rule rows, eight CIK-rule
rows, and two exact-override rows. Agreement is not accuracy: Monday's output
included known overgeneralized rules.

Evidence coverage is 13,975,865 rows (52.8641%). The other 12,461,464 retain
an explicitly labelled, unverified Eastern fallback. Most of those agree with
Monday, but should not be described as verified by this workflow. The candidate
has 10,679 non-EFFECT outside-hours rows from 2003 onward.

The existing `materialize_corrected_filings.py` now accepts
`--workflow-database` to use this frozen accession-only table. Its original
mode remains available for the historical production pipeline. The new mode
checks the raw input's recorded size and modification time, propagates the
stored instant by accession, and requires `--allow-unresolved` to permit the
labelled fallback. Provenance distinguishes `snapshot_pair`, `cross_cik_pair`,
`live_pair`, `live_file_inferred`, `sgml`, and unresolved clocks.

```bash
uv run python scripts/evaluate_timestamp_workflow.py \
  --baseline output/timestamp_baseline/pair_baseline.duckdb \
  --live-inference output/timestamp_baseline/live_file_inference_step5.duckdb \
  --sgml-queue output/timestamp_baseline/outside_hours_sgml_queue_v2.duckdb \
  --output output/timestamp_baseline/step5_evaluation.duckdb

uv run python scripts/materialize_corrected_filings.py \
  --workflow-database output/timestamp_baseline/step5_evaluation.duckdb \
  --allow-unresolved \
  --output output/timestamp_baseline/filings_step5.parquet
```

These outputs now exist; use new output paths when repeating the evaluation.
The separate candidate `filings_step5.parquet` retains all 26,437,329 rows and
TIMESTAMPTZ acceptance times. Every written instant was checked against the
frozen evaluation. Monday's live `filings.parquet` has not been replaced.
The candidate is ready for review before deciding whether to promote it.

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

The original two-step experiment did not change production data. The completed
Step 5 section above describes the subsequently added accession-only
materialization mode and its separate candidate file; the live Parquet remains
unchanged pending review.

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
