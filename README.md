# notes

Python dependencies in this repository are managed with `uv`.

## Setup

Create the project environment:

```sh
uv sync
```

If you use RStudio with `reticulate`, the project is configured to use `.venv/bin/python`.

## Common commands

Render or preview Quarto content through the `uv` environment:

```sh
uv run quarto preview published/bb68.qmd --no-browser --no-watch-inputs
```

Check the Python environment seen by `uv`:

```sh
uv run python -c "import sys; print(sys.executable)"
```

## The pandas `.assign()` note

`published/assign_magic.qmd` uses pandas 3.1 and includes an executed R comparison.
It uses Quarto's knitr engine with reticulate, plus the R packages dplyr, readr,
and tibble. Create its separate Python environment and preview it with:

```sh
uv venv .venv-assign --python 3.13
uv pip install --python .venv-assign/bin/python -r published/assign_magic-requirements.txt
RETICULATE_PYTHON="$PWD/.venv-assign/bin/python" \
  quarto preview published/assign_magic.qmd --no-browser
```

The requirements file records the Python packages used to execute the note.

## The chronological portal

`blog.qmd` combines the notes linked in `index.qmd` with short blog posts.
Short posts have `kind: post`, a title, a topic list, and a description in
`_blog-metadata.json`; they do not need to be added to the home-page note collection.
Published short posts live in `posts/`. LinkedIn migration drafts live in
`drafts/linkedin/` until reviewed and approved for publication.
The [Quarto pre-render hook](https://quarto.org/docs/projects/scripts.html#pre-and-post-render)
runs `scripts/build-blog.py`, which refreshes `_blog-listing.qmd`. The generated
include is checked in because Quarto resolves includes before running its hooks.
It reads note titles, links, and topics from the home-page collection, so adding a
note there also adds it to the chronological portal. Short summaries and optional
display-title overrides live in `_blog-metadata.json`.

Dates come from each note's explicit `date: YYYY-MM-DD` front matter. Revisions
(`date-modified`) and filesystem dates do not affect ordering; Git commit dates
are used only when explicitly recorded as a fallback below.
If a future note has no date, a verified LinkedIn post date (or another documented
publication date) can be recorded in its `_blog-metadata.json` entry as `date`,
with the exact source URL in `date-source`. This fallback is used only when the
note has no date, and its source is linked in the archive. A note with no verified
date appears under **Undated**, rather than receiving an inferred date.
When the original publication date is unknown, the first Git commit containing the
note can serve as a documented fallback. Set `date-source-label` to
`First Git commit` so the archive identifies the basis for that date.

Render or preview the portal without executing the research notes:

```sh
quarto render blog.qmd --to html --no-execute
quarto preview blog.qmd --no-browser
```

### Adding a new post

1. Create a note in `published/` with a descriptive, stable filename and front
   matter containing `title`, `author`, `date`, and `categories`. Set `date` to
   the date the post is first published on this site, in `YYYY-MM-DD` form.
   Keep that date for later revisions; use `date-modified` for substantial updates.
2. Add its HTML link and topics to the appropriate table in `index.qmd`.
   This includes the post in both the topic collection and the chronological
   portal. Its permanent URL will be `https://iangow.github.io/notes/published/<filename>.html`.
3. Add a short description under that HTML path in `_blog-metadata.json`.
   The archive still includes a new post if no description has been added yet.
4. Render the post, then `index.qmd` and `blog.qmd`, and review them before
   committing and publishing. Render computational posts with the environment
   their code requires; the two portals do not execute the posts they link to.

New posts do not need a LinkedIn counterpart or a LinkedIn date.

### Migrating LinkedIn posts

The goal is to preserve original posts and articles, including short observations,
updates, and commentary on links. A post introducing an existing note can become
its own dated entry linking to that note. A link to an existing note does not by
itself mean the post's introductory text has been migrated.

`migration/linkedin-inventory.json` tracks the captured feed and articles, related
notes, draft paths, and remaining source checks. It distinguishes Ian's own text
from third-party reposts. Preserve source URLs, exact publication timestamps,
authorship, attachments, and the basis for the displayed date. For the first batch,
dates use the UTC calendar date supplied by LinkedIn's `datePublished` metadata.

Drafts are omitted from the archive by default and are outside the normal website
render/resource paths. To build a local migration preview, first run:

```sh
BLOG_INCLUDE_DRAFTS=1 python3 scripts/build-blog.py
BLOG_INCLUDE_DRAFTS=1 quarto render blog.qmd --profile migration-preview --to html --no-execute
```

Render individual draft files with the same profile and environment flag. Restore
the checked-in listing with `python3 scripts/build-blog.py` after previewing.
The profile writes to `_migration-preview/`, separate from the publication output.
When approved, move a draft and its downloads to `posts/`, update its registered
path and relative asset/filter paths, and remove `draft: true`. Keep its original
publication date. Retain original charts unless a revision is clearly identified;
record unresolved issues for review.

### Republishing existing material

When a LinkedIn post introduces an attached note, combine complementary material
from the post and attachment into one Quarto source, removing duplicated openings.
Use the verified original publication date, record substantial changes with
`date-modified`, and identify the original post and any historical context.
Keep the original PDF available as an archive, and produce HTML and a new Typst PDF
from the combined source. Keep the intermediate Typst source when useful.
Typst documents can use `filters/pdf-links.lua` with `pdf-link-base` to make
relative links absolute in downloaded PDFs while retaining relative HTML links.
For a short post introducing a slide deck, the original PDF deck can accompany the
HTML note without recreating the slides. Keep the editable presentation master
separate from the published PDF.

Keep topic tags consistent between each note's `categories` and its topic list in
`index.qmd`. Apply tool tags such as Polars when the note actually uses the tool.

## Parked drafts

`published/valuation_methods.qmd` remains on `main` as an unfinished draft.
It is marked `draft: true` and excluded from the website render list. Its Typst
source and generated PDF are also excluded from website resources. Keep these
exclusions until publication is explicitly approved.
