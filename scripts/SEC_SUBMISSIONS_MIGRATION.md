# SEC submissions migration plan

This checkpoint preserves the notes workflow and its tests as they stood on
26 October 2026. New operational functionality belongs in
[`sec_submissions`](https://github.com/iangow/sec_submissions). Keep notes for
articles, dated research, and reproduction of earlier releases.

## What this checkpoint means

The notes scripts intentionally retain their historical behavior. In particular,
`bootstrap_timestamp_workflow.py` accepts `live_file_inferred` as supported prior
evidence, and `process_filings.py` includes those inferred values in resolved
accessions. The newer package working tree makes file-wide inference provisional,
preserves raw source clocks, and adds filing-index reference checks. Do not copy
the older notes policy back into the package or treat this commit as validation
of a new data release.

The September 30 audit remains a dated SGML-only assessment of its frozen
candidate. Later index follow-ups, independent audits, diagnostic collections,
and regression checks concern distinct comparisons or candidate bytes. Preserve
their identities instead of replacing historical results in place.

## Implementation ownership

| Notes source | Maintained package location |
| --- | --- |
| `process_filings.py` | `_process.py`, public `workflow.process()` |
| `bootstrap_timestamp_workflow.py` | `_bootstrap.py` |
| `infer_live_file_timezones.py` | `_infer.py` |
| `download_submissions.py` | `download.py` |
| `make_previous_filings.py` | `reference.py` |
| `audit_filings.py`, `retry_timestamp_audit.py` | `audit.py`, including resume/retry |
| `benchmark_recent_live_json.py` | `live_json.py` |
| `publish_filings.py` | `publish_filings.py` |
| SGML fetching in `benchmark_sgml_block_sampling.py` | `http.py`, `sgml.py` |

## First migration batch: behavioral parity tests

`sec_submissions/tests/test_notes_migration.py` ports the missing regression cases
without copying the older correction policy:

- publication rotation, interrupted-write and checksum rollback, truncation,
  empty/invalid candidate rejection, and aliased path rejection;
- SGML parse failures retaining successful response evidence and newline tags;
- conflicting SGML evidence and response-version isolation;
- an interrupted live-JSON collection retaining its frozen selection, retrying
  the failed block on resume, and preserving its inputs.

These tests must pass against both the package's committed baseline and its
current working source. Existing package work on provisional inference and audit
references remains a separate review and commit; do not sweep it into the test
migration commit.

## Remaining useful parity work

1. Add a stable collection diagnostics interface for selected/population blocks,
   matched/missing rows, requests, failures, retries and elapsed time. The notes
   benchmark has richer saved summaries than the package collector. Keep
   collection completion distinct from supported, provisional and unresolved
   timestamp counts; those come from processing diagnostics.
2. Compare and port remaining bootstrap, audit sampling and collector edge cases
   from all six notes test files. Adapt expectations to the package's current
   evidence policy rather than restoring older behavior.
3. Keep `probe_audit_headers.py` as research until a general, tested use case
   warrants a package diagnostic. Filing-index fallback already exists in the
   package; it is not missing functionality.
4. Keep Dropbox release verification as legacy maintenance. Do not add it to the
   main package unless the old delivery route still needs support. GitHub data
   releases and local `publish()` are separate operations.

## Notes and evidence

The datetime and original SEC notes can use package-based download instructions.
`sec_submissions_workflow.qmd` was published on 26 October 2026 as an introduction
to the package, with current provisional-status guidance and separately dated
audit findings. Its original audit sample remains in this checkpoint for
provenance; the article links to the versioned data-release artifacts.

Keep `TIMESTAMP_WORKFLOW.md`, `TIMESTAMP_STORAGE.md`, the release records and
legacy analysis scripts for dated reproduction. Replace operational directions
with package references as migration completes, without deleting the historical
record or breaking its links.

`output/` is ignored, not deleted. Frozen observations, sample predictions and
release manifests require verified archival copies before any cleanup. Separate
unique metadata-pilot scripts/reports and PostgreSQL benchmark work from generated
archives and rebuildable databases. No data publication, reprocessing, deletion,
or change in repository access is part of this checkpoint.
