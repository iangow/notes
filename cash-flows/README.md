# Cash-flow reporting note

Ian D. Gow's note, originally dated 11 June 2026, from https://github.com/iangow/cash-flows.

- `cash-flows.qmd`: complete R/Quarto analysis, rendered as `cash-flows/index.html` on the website.
- `cash-flows.pdf`: the original PDF dated 11 June 2026, linked from the HTML note.
- `cash-flows.css`: readable HTML table sizes.
- `../_freeze/cash-flows/cash-flows/`: saved HTML computations and figures for ordinary website builds.

The HTML retains the original publication date and records the date of its latest update.
Its analysis was refreshed on 23 October 2026 using the available local data.
The linked PDF retains the original results.

To rerun the analysis, install Quarto and the R packages tidyverse, DBI, farr,
gt, duckdb, ragg, igraph, ggraph, and tidygraph.
Configure `DATA_DIR` to point to a local Parquet repository
containing the DERA Notes tables used in the source. DuckDB's ICU extension
must be available.
From the notes repository root, run:

```sh
quarto render cash-flows/cash-flows.qmd --to html
```

Commit the updated source together with the saved computations and figures after checking the results against the surrounding text.
The note uses `freeze: true`, so ordinary project builds reuse the saved computations.
To render only this note from the saved results, run:

```sh
quarto render cash-flows/cash-flows.qmd --to html --use-freezer
```

The source, bibliography, citation style, and original PDF remain downloadable resources.
