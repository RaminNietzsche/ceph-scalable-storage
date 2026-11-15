#!/usr/bin/env python3
"""Print the CHANGELOG.md section of one version, for a GitHub Release body.

Usage: tools/release_notes.py v1.7   (or 1.7)
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.siteconf import changelog_releases  # noqa: E402

want = sys.argv[1].lstrip('v') if len(sys.argv) > 1 else ''
for ver, date, body in changelog_releases(os.path.join(ROOT, 'CHANGELOG.md')):
    if ver == want:
        print(f'Version {ver} ({date}) of the Persian and English editions: PDF, EPUB, DOCX and single-file HTML.\n'
              f'Read online at https://book.ceph-s3.ir/ · License CC BY-NC-SA 4.0.\n\n{body}')
        sys.exit(0)
sys.exit(f'release_notes: no "## [{want}] - date" section in CHANGELOG.md')
