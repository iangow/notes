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

## The chronological portal

`blog.qmd` offers a blog-style view of the same notes linked in `index.qmd`.
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

### Republishing existing material

When a LinkedIn post introduces an attached note, combine complementary material
from the post and attachment into one Quarto source, removing duplicated openings.
Use the verified original publication date, record substantial changes with
`date-modified`, and identify the original post and any historical context.
Keep the original PDF available as an archive, and produce HTML and a new Typst PDF
from the combined source. Keep the intermediate Typst source when useful.
Typst documents can use `filters/pdf-links.lua` with `pdf-link-base` to make
relative links absolute in downloaded PDFs while retaining relative HTML links.

Keep topic tags consistent between each note's `categories` and its topic list in
`index.qmd`. Apply tool tags such as Polars when the note actually uses the tool.
