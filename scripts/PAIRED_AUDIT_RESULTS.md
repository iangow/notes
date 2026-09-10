# Paired timestamp audit: diagnostic results

Analysis of the frozen 10,000-row audit, September 10, 2026. No new SEC
requests, repairs to sampled predictions, or production Parquet changes
were made. SGML acceptance clocks are assumed to represent America/New_York.

## Streamlined discrepancies

**Update: equal-cache replay.** Restoring all inherited live observations
retrieved before September 8 (not just the sampled discrepancies) eliminates
the coverage gap. Both adjusted orderings reproduce all 26,437,329 frozen
last-night timestamps. The JSON-first follow-up queue remains 8,703 rather
than 11,106 accessions. A separate descriptive audit rescore has zero errors
among 8,995 verifiable rows; 29 sample predictions change, including all 27
previous errors and two unverifiable rows. Original predictions and audit
results below remain untouched. This rescore is a methodological correction
after reviewing the audit, not a fresh independent validation sample.

All 27 discrepancies are missing-coverage cases: their source blocks were
not selected in the combined-target replay, their original live observations
were omitted, and the replay fell back to Eastern. They are not failures
of the retained timezone evidence or consequences of JSON-first ordering.
Last night's methods were live-file inference for 23 rows and direct live
pairs for four. Twenty-six filings are from 2024-2026; one is from 2023.

In the paired sample, Monday alone is wrong for 226 rows and the provisional
streamlined replay alone is wrong for 27. Neither is wrong for 8,742 rows.
Last night's output agrees with SGML for all 8,995 verifiable sample rows.
The omitted coverage needs a general solution, not accession-specific fixes
selected from this audit. Preserve these frozen audit outcomes when revising
the streamlined process.

## Unverifiable cases

| Cause | Sample rows | Estimated population share |
|---|---:|---:|
| Missing ACCEPTANCE-DATETIME tag | 847 | 7.9572% |
| HTTP 503, timeout, or incomplete read | 156 | 1.9804% |
| HTTP 404 | 2 | 0.0000076% |

The 156 potentially retryable rows comprise 128 HTTP 503 responses, 26
timeouts, and two incomplete-read rows. The two 404 cases are the previously
unmatched forms 1 and X-17A-5. No sampled accession is simply unchecked.

Of the 847 missing-tag rows:

| Raw-clock interpretation | Rows |
|---|---:|
| Literal midnight | 705 |
| Midnight Eastern when raw clock is interpreted as UTC | 128 |
| Neither kind of midnight | 14 |

The 14 non-midnight exceptions are distinct accessions dated May 1-14, 2002.
Midnight missing-tag cases extend through May 18, 2009. These are unavailable
reference timestamps, not confirmed errors or confirmed date-only records.

## Sampling uncertainty

Rates below concern the verifiable subset, not the unavailable-reference
population. All calculations use the 141 frozen strata and their population
weights; census strata have zero sampling variance.

| Version | Weighted error estimate | Interval or upper bound |
|---|---:|---:|
| Monday | 0.26294% | approximately 0.24479%-0.28110% (95%) |
| Last night | 0% observed | conservative one-sided 95% upper bound: 0.12796% |
| Provisional streamlined | 0.05108% | approximately 0.03369%-0.06847% (95%) |

The nonzero-error intervals use stratified ratio linearization with
finite-population corrections. They are normal approximations, not exact
intervals; zero-event strata can conceal additional uncertainty. See
[stratified sampling variance](https://online.stat.psu.edu/stat506/Lesson06).

For last night, a zero-width Wald/bootstrap interval would be misleading.
Instead, with K verifiable errors in the population and f_min the smallest
stratum sampling fraction, the probability of observing none is at most
exp(-f_min*K). A 97.5% upper bound on K/N is combined with a weighted Hoeffding
97.5% lower bound on the verifiable population fraction. The union bound
gives a conservative 95% upper bound on their ratio. Here f_min is
0.0001236953, K/N is bounded by 0.001128038, and the verifiable fraction is
bounded below by 0.8815389. The resulting error-rate upper bound is 0.12796%.
For concentration bounds without replacement, see
[Bardenet and Maillard](https://arxiv.org/abs/1309.4029).

These statements assume the seeded within-stratum sample behaves as simple
random sampling without replacement and treat verification status as a
fixed property under the audit protocol. Transient network failures make
the latter qualification important: retry them on the same sample before
final inference. No sampling interval removes the uncertainty about rows
whose reference timestamp cannot be obtained. The previously reported
whole-population ranges describe missing-reference uncertainty, not 95%
confidence intervals.

Reproduce with `scripts/analyze_paired_timestamp_audit.py --output PATH`.
Detailed tables are in
`output/timestamp_baseline/paired_audit_diagnostics.duckdb`.
