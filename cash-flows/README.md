# Cash-flow reporting note

Copy of Ian D. Gow's 11 June 2026 note from https://github.com/iangow/cash-flows.

- `cash-flows.qmd`: complete R/Quarto analysis; original date and results retained.
- `cash-flows.pdf`: existing rendered note.
- `index.qmd`: website landing page linking the PDF and reproducible source.

The Python environment is copied from the original repository, including its
`uv.lock`. Run `uv sync` within this directory to recreate it. It supports
Python work on this topic; the current note itself executes R, not Python.

To rerun the analysis, install Quarto and the R packages tidyverse, DBI, farr,
gt, and duckdb. Configure `DATA_DIR` to point to a local Parquet repository
containing the DERA Notes tables used in the source. DuckDB's ICU extension
must be available. Run `quarto render cash-flows.qmd --to pdf` in this directory.

The site renders only `index.qmd` here, so ordinary website builds do not
rerun the large XBRL analysis or require its data. The source, bibliography,
citation style, and original PDF are copied as downloadable resources.
