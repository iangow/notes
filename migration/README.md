# LinkedIn migration

The inventory is a work queue, not an assertion that every LinkedIn publication
has been captured or that every related note contains the original post's text.
It records 133 captured feed entries and 22 article entries; article announcements
can also appear in the feed, so these counts overlap.

The first batch contains the three posts Ian supplied on 26 October 2026. Their
full post text was checked in the authenticated browser; exact publication times
were verified against LinkedIn's public `datePublished` metadata. Original
short links were expanded. The Mixtape link was updated after its old chapter
URL returned 404. The Boeing chart has been rebuilt with Matplotlib from the reported figures in
Boeing's Q2 2026 Form 10-Q, Note 2. Ian's original image remains as a source
asset; the published entry uses the corrected vector chart, omits y-axis tick labels,
and omits the quoted follow-up comment. The original LinkedIn post and comment
have not been changed.

The three reviewed entries were approved for publication on 26 October 2026
and now live under `posts/`, retaining their original LinkedIn dates.

The second batch was approved for publication on 26 October 2026:

- **What's the most important financial statement?** (12 May 2026)
- **Why include code in teaching?** (20 May 2026)

`linkedin-batch-02.json` retains the original post text, independently checked
LinkedIn `datePublished` timestamps, expanded chapter links and editorial changes.
The two posts now live under `posts/`; their notes-owned solution documents live
under `published/` and are included in the topic collection and archive.

The posts now link to notes-owned `bb68-solutions-polars.qmd` and
`panel-data-solutions-polars.qmd`, with PDF and HTML editions. These bounded
documents adapt the current Python Polars solutions and applicable R corrections.
They were freshly executed on 26 October 2026 with freeze and cache disabled.
The existing `published/bb68.qmd` replication note is unchanged.

The original attachments were 13 and 15 pages. The new PDFs are updated editions,
not facsimiles or certified archives of those files. No LinkedIn download is needed
to review or maintain the new notes versions.

`linkedin-solutions-provenance.json` records source revisions and hashes, historical
comparison baselines, corrections versus other substantive changes, package/data
verification limits, code comparisons, numerical checks and rendering receipts.
Before updating these notes, manually compare changes since those recorded
revisions in `era_pl_sols` and the corresponding R files in `far_sols`. Review and
carry across relevant fixes without overwriting notes-specific corrections or
presentation helpers. No scheduled task or shared-source synchronization is set up.

The build was isolated to avoid repository hooks changing unrelated generated
listings or caches. Publication outputs are under `_site/posts/` and `_site/published/`.
The source directory also contains the checked PDFs, retained Typst sources, a
bounded bibliography, citation style and recorded Python requirements. Only the two posts and two solution documents are approved for publication; private
full instructor guides and sharing settings remain unchanged.

Inventory statuses:

- `published`: the approved migration has been published; `site_url` records its location.

- `draft_prepared`: a verified source has a review draft; not yet published.
- `represented_by_existing_note`: an earlier reviewed adaptation exists.
- `linked_note_exists_review_post_text`: a note is linked or attached, but the
  original post text still needs comparison.
- `needs_review`: check the full post, authorship boundaries, dates, links,
  attachments, and thematic overlap before preparing an entry.
- `third_party_repost`: no original text is attributed to Ian; do not republish
  another author's post as his writing.
- `needs_article_review`: inspect the full article and compare it with existing
  notes; title matches are only leads.

Inferred dates and unverified post URLs are explicitly marked. Do not promote
them to verified original publication dates without checking the source. Short
opening excerpts identify items; they are not the full texts to be republished.
Preserve Ian's own follow-up comments only where they add relevant context, and
keep them distinct from the original post and from editorial additions.

## Rebuilding the Spirit chart

Run `python3 scripts/plot_spirit_goodwill.py` with Matplotlib installed. The
script reads `migration/data/boeing-spirit-purchase-price-allocation.csv` and
writes SVG and PNG files to `posts/images/`. Use `--output-dir` to change the
destination.

The CSV contains the individual reported amounts in US$ millions. Liabilities
are positive magnitudes that the chart subtracts; the positive `Other` line
is included with identifiable assets. The script computes the totals and
requires net identifiable assets plus goodwill to equal consideration in each
period. Chart labels use two decimal places in billions, with rounding half up;
the bar geometry uses the unrounded amounts. Both dates are preliminary
purchase-price allocations as reported at those dates, rather than subsequent
balance-sheet carrying values of the acquired business.

## Third batch: published

Four short introductions were approved and published on 27 October 2026 under
`posts/`, with HTML and individual PDFs:

- Consolidation mini-textbook (22 April 2026).
- Learning Python Polars (15 April 2026).
- The R version of db2pq on CRAN (2 June 2026).
- farr: reusable code and teaching data (4 September 2025).

Full original bodies and verified LinkedIn timestamps are preserved in
`linkedin-batch-03.json`; displayed dates retain their original UTC calendar
dates. Links point to maintained public resources; original short-link redirect
chains remain unverified. Polars and farr have explicitly dated updates. The
obsolete farr release-timing parenthetical is omitted from the published post
and preserved in its archived original. Package, function and dataset names
use inline-code formatting where appropriate. No third-party comments or
private solution guides are included.

Publication versions were built in an isolated snapshot. Existing deployed
notes and assets were retained, and valuation remains excluded.

## Fourth batch: published

Two short introductions were approved and published on 27 October 2026 under
`posts/`, with HTML and individual PDFs:

- Direct-method cash flow statements (11 June 2026).
- Moving notes to Typst (3 April 2026 UTC; 2 April in New York).

Full originals and verified LinkedIn timestamps are retained in
`linkedin-batch-04.json`. Original dates and the Typst post's New York/UTC
calendar-date distinction are preserved. The cash-flow introduction dates its
0.2% finding and links the existing HTML analysis and dated PDF; no analysis is
duplicated or rerun. Current Typst collection/archive links are identified in a
dated update; original short-link redirect chains remain unverified. Inline-code
formatting is retained. No third-party comments or private material is included.

Publication versions were built in an isolated snapshot. Existing deployed notes,
assets and the CTE correction were retained; valuation remains unpublished.
