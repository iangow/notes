#!/usr/bin/env python3
"""Build the blog from indexed notes and registered short posts.

Uses only the Python standard library. Run by Quarto before rendering; never
executes a note or changes its source. Dates come from each note's explicit
ISO date, not date-modified, Git history, or filesystem timestamps.
"""

from collections import Counter
from datetime import date
from html import escape
import json
import os
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
ROWS = re.compile(r"^\| \[(.*?)\]\((.*?)\) \| (.*?) \|$", re.MULTILINE)


def inline(text):
    """Preserve the inline code used in the collection's titles."""
    return re.sub(r"`([^`]+)`", r"<code>\1</code>", escape(text))


def source_path(href):
    if href == "cash-flows/index.html":
        return ROOT / "cash-flows/cash-flows.qmd"
    path = (ROOT / href).with_suffix(".qmd")
    if not path.resolve().is_relative_to(ROOT):
        raise ValueError(f"Note must be within the project: {href}")
    return path


def front_matter(path):
    text = path.read_text(encoding="utf-8")
    front = re.match(r"\A---\s*\n(.*?)\n---(?:\s*\n|$)", text, re.DOTALL)
    if not front:
        raise ValueError(f"Missing front matter: {path}")
    return front[1]


def is_draft(path):
    return bool(re.search(r"^draft:[ \t]*true[ \t]*(?:#.*)?$",
                          front_matter(path), re.MULTILINE | re.IGNORECASE))


def note_date(path, metadata):
    match = re.search(r"^date:[ \t]*([^\n]+)", front_matter(path), re.MULTILINE)
    if match:
        # Require a fixed ISO date; never silently substitute the render date.
        value = match[1].split(" #", 1)[0].strip().strip("\"'")
        return date.fromisoformat(value), None
    if metadata.get("date"):
        source = metadata.get("date-source", "")
        if not source.startswith("https://"):
            raise ValueError(f"A fallback date needs a source URL: {path}")
        return date.fromisoformat(metadata["date"]), source
    return None, None


def collect_posts(include_drafts=False):
    extras = json.loads((ROOT / "_blog-metadata.json").read_text(encoding="utf-8"))
    rows = ROWS.findall((ROOT / "index.qmd").read_text(encoding="utf-8"))
    if not rows:
        raise ValueError("No collection entries found in index.qmd")
    for href, metadata in extras.items():
        if metadata.get("kind") != "post":
            continue
        if not (href.startswith(("posts/", "drafts/linkedin/"))
                and href.endswith(".html")):
            raise ValueError(f"Unexpected blog post path: {href}")
        if not metadata.get("title") or not isinstance(metadata.get("topics"), list):
            raise ValueError(f"Blog post needs a title and topic list: {href}")
        rows.append((metadata["title"], href, metadata["topics"]))
    posts = []
    seen = set()
    for title, href, topics in rows:
        if href in seen:
            raise ValueError(f"Duplicate collection entry: {href}")
        seen.add(href)
        metadata = extras.get(href, {})
        path = source_path(href)
        if is_draft(path) and not include_drafts:
            continue
        published, provenance = note_date(path, metadata)
        posts.append({
            "title": metadata.get("title", title),
            "href": href,
            "topics": (topics if isinstance(topics, list)
                       else [topic.strip() for topic in topics.split(",")]),
            "description": metadata.get("description", ""),
            "date": published,
            "date-source": provenance,
            "date-source-label": metadata.get("date-source-label", "Source for date"),
            "year": str(published.year) if published else "Undated",
        })
    # Alphabetical order makes ties stable. Undated posts follow every dated one.
    posts.sort(key=lambda post: post["title"].casefold())
    posts.sort(key=lambda post: post["date"] or date.min, reverse=True)
    return posts


def render(posts):
    years = Counter(post["year"] for post in posts)
    out = [
        "```{=html}",
        '<div class="blog-layout">',
        '<nav class="blog-archive" aria-label="Browse posts and notes by year">',
        '<p class="blog-eyebrow">THE ARCHIVE</p>',
        f'<p class="blog-count">{len(posts)} entries</p>',
        '<ul>',
    ]
    for year, count in years.items():
        out.append(f'<li><a href="#year-{year.lower()}">{year}'
                   f'<span class="year-count">{count}</span></a></li>')
    out.extend([
        '</ul>',
        '<p class="blog-archive-note">Posts and notes, from newest to oldest.</p>',
        '</nav>',
        '<div class="blog-posts">',
    ])
    previous_year = None
    for post in posts:
        year = post["year"]
        if year != previous_year:
            if previous_year is not None:
                out.append('</section>')
            out.append(f'<section class="blog-year" id="year-{year.lower()}" '
                       f'aria-labelledby="heading-{year.lower()}">')
            out.append(f'<h2 id="heading-{year.lower()}">{year}</h2>')
            previous_year = year
        out.append('<article class="blog-entry">')
        published = post["date"]
        if published:
            label = f'{published.day} {published:%B %Y}'
            out.append(f'<time class="blog-date" datetime="{published.isoformat()}">{label}</time>')
        else:
            out.append('<p class="blog-date">Date not yet established</p>')
        if post["date-source"]:
            out.append(f'<p class="blog-date-source"><a href="{escape(post["date-source"])}">'
                       f'{escape(post["date-source-label"])}</a></p>')
        out.append(f'<h3><a href="{escape(post["href"])}">{inline(post["title"])}</a></h3>')
        if post["description"]:
            out.append(f'<p class="blog-summary">{escape(post["description"])}</p>')
        out.append('<ul class="blog-tags" aria-label="Topics">')
        out.extend(f'<li>{escape(topic)}</li>' for topic in post["topics"])
        out.extend(['</ul>', '</article>'])
    out.extend(['</section>', '</div>', '</div>', '```', ''])
    return "\n".join(out)


def main():
    posts = collect_posts(include_drafts=os.environ.get("BLOG_INCLUDE_DRAFTS") == "1")
    output = render(posts)
    destination = ROOT / "_blog-listing.qmd"
    if not destination.exists() or destination.read_text(encoding="utf-8") != output:
        destination.write_text(output, encoding="utf-8")
    undated = sum(post["date"] is None for post in posts)
    print(f"Blog archive: {len(posts)} entries, {undated} undated.")


if __name__ == "__main__":
    main()
