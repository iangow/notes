# Typst migration

This repo currently builds website pages as HTML and many notes as PDF via LaTeX.
The first Typst pass should target notes that have simple PDF metadata only.

## First-pass criteria

- No `include-in-header`
- No Lua filters
- No LaTeX-specific layout flags such as `classoption: [landscape]`
- No known TeX-only body content

## Notes migrated in this pass

- `published/tax_target.qmd`
- `published/sirca_ma.qmd`
- `published/sirca_eod.qmd`
- `published/bklyz.qmd`

Each of these now uses `format: typst:` and Typst-native `margin:` metadata.
For Typst bibliography output, use `bibliographystyle: harvard-cite-them-right` rather than a CSL file.
Use `linkcolor: "#0000FF"` on the Typst side for blue PDF links.

## Next migration tiers

1. Notes with simple metadata plus minor PDF-only options.
2. Notes that use abstract blocks via `abstract.lua`.
3. Notes that depend on `include-in-header: preamble.tex`.
4. Notes with TeX-oriented table styling or raw LaTeX in the body.

## Known blockers

- Project renders trigger `scripts/render-db2pq-test.sh` via `_quarto.yml` pre-render.
- Some notes need an R graphics device stack that is not available in the current shell.
- `abstract.lua` and `preamble.tex` are LaTeX-specific and need Typst replacements before broader migration.
