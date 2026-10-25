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
asset; the draft uses the corrected vector chart, omits y-axis tick labels,
and omits the quoted follow-up comment. The original LinkedIn post and comment
have not been changed.

Inventory statuses:

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
writes SVG and PNG files to `drafts/linkedin/images/`. Use `--output-dir` to
change the destination when the post is moved for publication.

The CSV contains the individual reported amounts in US$ millions. Liabilities
are positive magnitudes that the chart subtracts; the positive `Other` line
is included with identifiable assets. The script computes the totals and
requires net identifiable assets plus goodwill to equal consideration in each
period. Chart labels use two decimal places in billions, with rounding half up;
the bar geometry uses the unrounded amounts. Both dates are preliminary
purchase-price allocations as reported at those dates, rather than subsequent
balance-sheet carrying values of the acquired business.
