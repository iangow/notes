# September 10, 2026 timestamp release

The production `edgar/filings.parquet` now uses the frozen accession evidence
from `effect_evaluation.duckdb`, restored from the verified Parquet archive
into `output/timestamp_parquet/20260910/accepted_roundtrip.duckdb`.
It does not incorporate subsequent random-audit observations as corrections.

```bash
uv run --frozen python scripts/materialize_corrected_filings.py \
  --workflow-database output/timestamp_parquet/20260910/accepted_roundtrip.duckdb \
  --output output/timestamp_release/20260910/filings.parquet \
  --allow-unresolved --memory-limit 4GB
```

Validation before installation confirmed:

- 26,437,329 rows; no missing acceptance timestamps; TIMESTAMPTZ acceptance
  instants and DATE filing/report dates.
- 16,463,879 evidence-supported rows and 9,973,450 labelled Eastern fallbacks.
- Non-timestamp row fingerprints unchanged from `filings_raw.parquet`.
- Timestamp/provenance fingerprints match the frozen accession workflow.
- The frozen evaluation records 63,879 timestamp differences from Monday:
  63,877 evidence-supported differences and two remaining unsupported cases.
- All 24 script regression tests pass.

The former `edgar/filings.parquet` and shared `submissions/filings.parquet`
were byte-identical. Their contents are preserved at
`$DATA_DIR/edgar/archived/filings-20260907-before-20260910.parquet`.
The shared file was overwritten in place, retaining its local inode, rather
than moved or recreated. Its Dropbox identity is `id:FdrsnXG58SgAAAAAAAoWhA`;
the existing download URL in `published/datetimes.qmd` is unchanged. Local
replacement alone does not prove cloud publication: verify Dropbox's revision
and size after desktop syncing completes.

Both new copies have 1,138,230,145 bytes and SHA-256
`1bf40e6afe0141e6468bab3a6395b2e37bb0cbdd7ef423ecfa9e246cc82ab672`.
The archived file has SHA-256
`39948989c88fa2fae6bfcf237c97adebf64ad5d3d1fbfb8743fef4b7ccd50dec`.

The HTML and Typst/PDF report were rerun with:

```bash
uv run --frozen quarto render published/datetimes.qmd \
  --to all --execute --cache-refresh --no-clean
```

For 2003 onward, strictly outside 06:00 through 22:00 New York time, the new
data contain 143,047 EFFECT, 1,493 correspondence and 9,186 other rows.
Outside-hours observations are a diagnostic, not automatically errors.
The report now explains mixed raw clock encodings, evidence-based corrections
and the remaining Eastern fallback, rather than claiming all JSON clocks are
Eastern. Site publication updates only this report, its assets and its search
entries on the existing `gh-pages` branch.
