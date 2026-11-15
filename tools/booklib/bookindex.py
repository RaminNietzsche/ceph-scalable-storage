"""Book index: which glossary terms occur where.

One matcher serves the print index (build_book.py anchors) and the web index
(build_site.py, by section). A hit is a whole-word occurrence of the English
term in prose: code (fenced and inline), math, URLs, link targets, image paths,
attribute blocks and identifiers such as ``osd_pool_default`` or ``rgw.log``
do not count. Both editions are scanned and their hits united per section, so
the fa and en index pages list the same terms, chapters and targets.
"""
from __future__ import annotations

import glob
import os
import re

from .mdlower import split_front_matter

# qualifiers that are too generic on their own: match only the full form or "Qualifier Term"
NEEDS_QUALIFIER = {'Label', 'Journal', 'Throttle', 'Superblock', 'Envelope mode', 'Error repo', 'Banner'}
LEFT = r'(?<![\w\-./@#:$=<>])'
RIGHT = r'(?:s|es)?(?![\w\-/@#=<>])(?!\.\w)'
HEAD = re.compile(r'^(#{1,6}) .*\{#([\w:.-]+)[^}]*\}\s*$')


def forms(term):
    """Surface forms that count as the term: 'PG (Placement Group)' -> PG, Placement Group."""
    m = re.match(r'^(.*?) \((.*)\)$', term)
    if not m:
        return [term]
    x, y = m.group(1), m.group(2)
    out = [term]
    if x not in NEEDS_QUALIFIER:
        out.append(x)
    if len(y.split()) > 1 or y.islower():   # an expansion: Placement Group, persistent write log, cap
        out.append(y)
    else:                                  # a qualifier: RGW lifecycle, BlueStore label
        out.append(f'{y} {x}')
    return out


def _cs(form):
    """Single words: exact for acronyms, CamelCase and lowercase names (OSD, BlueStore, cephadm);
    multi-word terms and a/b pairs match in any case (PG log = pg log, Watch/Notify = watch/notify)."""
    if ' ' in form or '/' in form:
        return False
    return any(c.isupper() for c in form[1:]) or form[0].islower()


def matchers(terms):
    res = []
    for t in sorted(terms, key=len, reverse=True):
        pats = []
        for f in forms(t):
            body = re.escape(f).replace(r'\ ', r'\s+')
            if _cs(f):
                pats.append(body)
            elif ' ' in f or '/' in f:
                pats.append(f'(?i:{body})')
            else:
                pats.append(f'(?i:{body[0]}){body[1:]}')
        res.append((t, re.compile(LEFT + '(?:' + '|'.join(pats) + ')' + RIGHT)))
    return res


from .mathtext import MATH, tex_plain  # noqa: E402,F401
def clean(text):
    """Prose only: drop code, math, URLs, link targets, attribute blocks."""
    t = re.sub(r'`[^`]*`', ' ', text)
    t = MATH.sub(lambda m: ' ' + tex_plain(m.group(0)[1:-1]) + ' ', t)
    t = re.sub(r'\]\([^)]*\)', '] ', t)
    t = re.sub(r'\{[#.][^}]*\}', ' ', t)
    t = re.sub(r'<?https?://\S+', ' ', t)
    return t


def count(ms, text):
    """{term: n} whole-word occurrences in already-cleaned text; longer terms first, no double counting."""
    out = {}
    for t, rx in ms:
        n = 0

        def sub(m):
            nonlocal n
            n += 1
            return ' ' * len(m.group(0))
        text = rx.sub(sub, text)
        if n:
            out[t] = n
    return out


def scan_chapter(path, ms):
    """[(section_id, {term: n})] for one chapter file (prose lines only)."""
    _, lines = split_front_matter(open(path, encoding='utf-8').read())
    sec = ''
    res = []
    inc = False
    in_sources = False
    for line in lines:
        if line.startswith('```'):
            inc = not inc
            continue
        if inc or line.startswith(':::') or not line.strip():
            continue
        h = HEAD.match(line)
        if h:
            sec = h.group(2)
            in_sources = False
            continue
        if re.match(r'^\s*- .*https?://', line):  # bibliography lines of the "Sources" section
            in_sources = True
        if in_sources:
            continue
        c = count(ms, clean(line))
        if c:
            res.append((sec, c))
    return res


def build(root, terms):
    """{term: {chapter: [(section_id, n), ...]}} united over the fa and en chapters."""
    ms = matchers(terms)
    occ = {}
    for lang in ('fa', 'en'):
        for path in sorted(glob.glob(os.path.join(root, 'content', lang, 'chapters', '[0-9][0-9]-*.md'))):
            ch = int(os.path.basename(path)[:2])
            per = {}
            for sec, c in scan_chapter(path, ms):
                for t, n in c.items():
                    per.setdefault(t, {}).setdefault(sec, 0)
                    per[t][sec] += n
            for t, secs in per.items():
                slot = occ.setdefault(t, {}).setdefault(ch, {})
                for sec, n in secs.items():
                    slot[sec] = max(slot.get(sec, 0), n)
    # keep section order as in the chapter
    out = {}
    for t, chs in occ.items():
        out[t] = {ch: sorted(secs.items(), key=lambda kv: [int(x) if x.isdigit() else 0 for x in re.findall(r'\d+', kv[0])])
                  for ch, secs in sorted(chs.items())}
    return out


FA_ORDER = 'آابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی'
FA_NORM = str.maketrans({'ي': 'ی', 'ك': 'ک', 'أ': 'ا', 'إ': 'ا', 'ۀ': 'ه', 'ة': 'ه', '\u200c': ''})


def fa_key(s):
    s = s.translate(FA_NORM)
    return [FA_ORDER.index(c) if c in FA_ORDER else 100 + ord(c) for c in s if not c.isspace()]


def fa_letter(s):
    c = s.translate(FA_NORM)[0]
    return 'ا' if c == 'آ' else c
