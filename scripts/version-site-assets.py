#!/usr/bin/env python3
"""Version custom CSS/JS URLs so browsers fetch changed assets after publishing.

Quarto runs this after rendering. Also run it before a --no-render publication
when editing CSS/JS directly. It changes references only, never note content.
"""

import hashlib
from pathlib import Path
import re


def main():
    site = Path('_site')
    versions = {}
    for name in ('notes-theme.css', 'notes-home.css', 'notes-home.js'):
        asset = site / 'assets' / name
        if asset.is_file():
            versions[name] = hashlib.sha256(asset.read_bytes()).hexdigest()[:12]
    pattern = re.compile(
        r'(<(?:link|script)\b[^>]*\b(?:href|src)=")'
        r'([^"?]*assets/(notes-theme\.css|notes-home\.css|notes-home\.js))'
        r'(?:\?[^\"]*)?("[^>]*>)'
    )
    changed = 0
    for path in site.rglob('*.html'):
        original = path.read_text()

        def version(match):
            name = match[3]
            if name not in versions:
                raise ValueError(f'Missing asset: {name}')
            return f'{match[1]}{match[2]}?v={versions[name]}{match[4]}'

        updated = pattern.sub(version, original)
        if updated != original:
            path.write_text(updated)
            changed += 1
    print(f'Versioned custom asset references in {changed} HTML pages.')


if __name__ == '__main__':
    main()
