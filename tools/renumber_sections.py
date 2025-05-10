#!/usr/bin/env python3
"""Rewrite the {#sec-NN-K[-M]} anchors of level-1/2 headings in chapter files.

Run after inserting or removing a section. Anchors must stay identical across
languages, so run it for both editions and then `make check-parity`.

Usage: tools/renumber_sections.py content/fa/chapters/08-under-the-hood.md [...]
"""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
from booklib.mdlower import heading_ids, split_front_matter  # noqa: E402

if len(sys.argv) < 2 or sys.argv[1] in ('-h', '--help'):
    print(__doc__)
    sys.exit(0 if len(sys.argv) > 1 else 2)
for path in sys.argv[1:]:
    text = open(path, encoding='utf-8').read()
    fm, lines = split_front_matter(text)
    n = int(re.search(r'^chapter:\s*(\d+)', fm, re.M).group(1))
    lines = [re.sub(r'(^#{1,2} .*?)\s+\{#sec-[\w-]+\}\s*$', r'\1', x) if x.startswith('#') else x for x in lines]
    for k, _, hid in heading_ids(lines, n):
        lines[k] = f'{lines[k]} {{#{hid}}}'
    open(path, 'w', encoding='utf-8').write('---\n' + fm + '\n---\n' + '\n'.join(lines))
    print('renumbered', path)
