"""Extract the structural skeleton of a chapter file (ids, counts) for checks."""
from __future__ import annotations

import re

from .mdlower import split_front_matter, parse_div

IMG = re.compile(r'^!\[.*\]\((\S+?)\)\{#([\w:.-]+)\}\s*$')
HID = re.compile(r'^(#{1,6}) .*\{#([\w:.-]+)\}\s*$')


def skeleton(path):
    fm_text, lines = split_front_matter(open(path, encoding='utf-8').read())
    import yaml
    fm = yaml.safe_load(fm_text) or {}
    sk = {'fm': fm, 'sections': [], 'figures': [], 'images': [], 'algos': [], 'tables': 0,
          'code_blocks': 0, 'callouts': [], 'headings_without_id': []}
    inc = False
    for k, l in enumerate(lines):
        if l.startswith('```'):
            if not inc:
                sk['code_blocks'] += 1
            inc = not inc
            continue
        if inc:
            continue
        m = HID.match(l)
        if m:
            sk['sections'].append(m.group(2))
            continue
        if re.match(r'^#{1,2} ', l):
            sk['headings_without_id'].append(k + 1)
        m = IMG.match(l)
        if m:
            sk['figures'].append(m.group(2))
            sk['images'].append(m.group(1))
            continue
        d = parse_div(l)
        if d:
            classes, ident, attrs = d
            if classes and classes[0] == 'algo':
                sk['algos'].append(ident)
            elif classes:
                sk['callouts'].append(classes[0])
            continue
        if l.startswith('|') and k + 1 < len(lines) and re.match(r'^\|?\s*:?-{3,}', lines[k + 1]):
            sk['tables'] += 1
    return sk


def canonical_counts(root):
    """Figure and ALGO counts of the canonical (fa) edition.

    The editions are structurally identical (check_parity), so the preface of any
    edition quotes these numbers even while chapters are still pending translation.
    """
    import glob
    import os
    algos = figs = 0
    for p in glob.glob(os.path.join(root, 'content', 'fa', 'chapters', '*.md')):
        sk = skeleton(p)
        algos += len(sk['algos'])
        figs += len(sk['figures'])
    return algos, figs
