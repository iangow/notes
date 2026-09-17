#!/usr/bin/env python3
"""Add the homepage's native Quarto theme switch to existing rendered pages.

Run after rendering index.qmd with the site's light/dark theme configuration:
    python3 scripts/apply-rendered-site-theme.py

This migration does not render documents or execute their code. It preserves
each page's existing light stylesheet, content, outputs, and page-specific
scripts, and copies Quarto's theme scaffolding from the rendered homepage.
It also includes the shared site-palette stylesheet. Existing theme
controls are not duplicated. Future normal renders inherit the configuration
from _quarto.yml.
"""

import argparse
import hashlib
import os
from pathlib import Path
import re
import shutil
import tempfile


def exactly_one(pattern, text, label):
    matches = list(re.finditer(pattern, text, re.DOTALL))
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {label}; found {len(matches)}")
    return matches[0]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-dir', type=Path, default=Path('_site'))
    args = parser.parse_args()
    site = args.site_dir.resolve()
    template = (site / 'index.html').read_text()
    theme_script = exactly_one(
        r'<script id="quarto-html-before-body"[^>]*>.*?</script>',
        template, 'native Quarto theme script',
    )[0]
    toggle = exactly_one(
        r'<a\b[^>]*class="quarto-color-scheme-toggle[^\"]*"[^>]*>.*?</a>',
        template, 'navbar theme toggle',
    )[0]
    if 'queryPrefersDark' not in theme_script:
        raise ValueError('Template must respect the user color preference')

    custom_style = 'assets/notes-theme.css'
    style_source = Path(__file__).resolve().parent.parent / custom_style
    style_target = site / custom_style
    style_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(style_source, style_target)
    replacements = []
    for path in sorted(site.rglob('*.html')):
        original = path.read_text()
        if '<main ' not in original:
            continue
        updated = original
        if 'notes-theme.css' not in updated:
            relative_style = Path(os.path.relpath(style_target, path.parent)).as_posix()
            updated = updated.replace('</head>', f'<link rel="stylesheet" href="{relative_style}">\n</head>', 1)
        if 'quarto-color-scheme-toggle' in original:
            if updated != original:
                replacements.append((path, original, updated))
            continue
        for style_id in ('quarto-text-highlighting-styles', 'quarto-bootstrap'):
            original_tag = exactly_one(
                rf'<link\b[^>]*id="{style_id}"[^>]*>', updated, style_id,
            )[0]
            if 'class=' in original_tag:
                raise ValueError(f'Unexpected stylesheet classes in {path}')
            light = original_tag.replace('>', ' class="quarto-color-scheme">')
            extra = original_tag.replace('>', ' class="quarto-color-scheme-extra">')
            dark = exactly_one(
                rf'<link\b(?=[^>]*id="{style_id}")'
                r'(?=[^>]*class="quarto-color-scheme quarto-color-alternate")[^>]*>',
                template, f'dark {style_id}',
            )[0]
            href = exactly_one(r'href="([^"]+)"', dark, 'stylesheet URL')
            target = site / href[1]
            if not target.is_file():
                raise ValueError(f'Missing theme asset: {target}')
            relative = Path(os.path.relpath(target, path.parent)).as_posix()
            dark = dark.replace(href[0], f'href="{relative}"')
            updated = updated.replace(original_tag, '\n'.join((light, dark, extra)), 1)

        body = exactly_one(r'<body\b[^>]*>', updated, 'body opening tag')[0]
        updated = updated.replace(body, body + theme_script, 1)
        tools = exactly_one(r'<div class="quarto-navbar-tools">', updated, 'navbar tools')[0]
        updated = updated.replace(tools, tools + '\n' + toggle, 1)
        listener = 'window.document.addEventListener("DOMContentLoaded", function (event) {'
        exactly_one(re.escape(listener), updated, 'DOMContentLoaded listener')
        updated = updated.replace(listener, listener + '\n    setColorSchemeToggle(hasAlternateSentinel());', 1)

        # Everything in the content container, including the TOC, article,
        # tables, figures and footnotes, must remain byte-for-byte identical.
        content_pattern = r'<!-- content -->.*?(?=<script id="quarto-html-after-body")'
        before = exactly_one(content_pattern, original, 'content container')[0]
        after = exactly_one(content_pattern, updated, 'content container')[0]
        if before != after:
            raise ValueError(f'Content changed unexpectedly: {path}')
        replacements.append((path, original, updated))

    # Validate the entire batch before modifying any generated page.
    backup = Path(tempfile.mkdtemp(prefix='notes-before-theme-'))
    for path, original, updated in replacements:
        saved = backup / path.relative_to(site)
        saved.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, saved)
        path.write_text(updated)
        assert hashlib.sha256(saved.read_bytes()).digest() == hashlib.sha256(original.encode()).digest()
    print(f'Updated {len(replacements)} pages; all content containers are unchanged.')
    print(f'Original HTML preserved in {backup}')


if __name__ == '__main__':
    main()
