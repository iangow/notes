# Expanded SEC submissions extraction

Run from the repository root:

```sh
.venv/bin/python scripts/extract_filings.py --max-seconds 0
```

Input defaults to `$RAW_DATA_DIR/submissions/submissions.zip`; output defaults to
`$DATA_DIR/edgar/filings_raw.parquet`. The repository `.env` supplies those
variables when they are not already set. Without them, the corresponding roots
are `~/Dropbox/raw_data` and `~/Dropbox/pq_data`.

You can supply a ZIP and a separate output path as positional arguments:

```sh
.venv/bin/python scripts/extract_filings.py /path/submissions.zip /path/filings_raw.parquet --max-seconds 0
```

The script refuses an output named `filings.parquet`, and refuses to replace
existing outputs unless resuming its own checkpoint. It does not modify the
existing timestamp-investigation scripts or apply their conversion rules.

## Outputs

For the default output name:

| File | Contents |
| --- | --- |
| `filings_raw.parquet` | All fields from recent and referenced historical filing arrays, plus `cik` and `source_file` |
| `companies.parquet` | One row per primary company JSON, with company-level fields including `ownerOrg` |
| `addresses.parquet` | Addresses by `cik` and `address_type` |
| `tickers.parquet` | Ticker/exchange pairs by array position, padding unequal arrays with nulls |
| `former_names.parquet` | Former names and their original `from`/`to` dates |
| `files.parquet` | Historical-file references, counts, date ranges, and an `available` flag indicating ZIP membership |

Every table includes `cik` and `source_file`. Company metadata describes the ZIP
snapshot; it is not historical company information as of each filing date.
Missing companion files are recorded with `available = false`; their filing rows
cannot be extracted. Duplicate references within a company's file list are
retained in the files table, but their filing rows are read only once.

`acceptanceDateTime` stays **text exactly as supplied** (including suffixes,
fractional seconds, and empty strings). No time-zone interpretation is applied.
Filing and report dates and companion-file date ranges are dates; CIK and SIC
are integers; sizes and counts are big integers; former-name `from`/`to` values
are dates; indicator fields are Booleans.
Invalid or empty values in these typed columns become null through `TRY_CAST`.
Other fields are text, preserving leading zeros in identifiers such as EIN,
file numbers, ZIP codes, and fiscal-year ends. Unknown nested values are retained
as JSON text. Extra fields are discovered across the entire archive, including
fields that first appear late in extraction. Empty tables still have schemas.

## Checkpoints and validation

Without `--max-seconds 0`, extraction checkpoints and returns after about 150
seconds. Repeating the same command resumes. Conversion itself has no time limit.
A sibling `filings_raw.staging` directory holds JSON Lines files and a
checkpoint containing the input identity, field lists, counts, and byte offsets.
Progress is checkpointed every 1,000 companies and at timed exits. On resume,
uncheckpointed trailing bytes are discarded before extraction continues.
Changing the input ZIP while a checkpoint exists requires a new output name.
Do not run multiple instances against the same output path.

All six temporary Parquet files are prepared and their row counts checked before
publication. Each file is replaced atomically, but the six-file set is not a
single atomic transaction. If conversion or publication fails, repeat the same
command to retry using the retained staging data. Staging is removed on success.

Run the synthetic regression tests with:

```sh
.venv/bin/python -m unittest discover -s scripts -p test_extract_filings.py
```

Conversion logs elapsed seconds per table and process-lifetime peak resident
memory (RSS) before conversion and after each table. The peak includes extraction
and earlier tables; it is not an isolated per-table memory measurement.
