#!/usr/bin/env python3
"""Content checks of the built web book that link checks cannot see.

* No soft hyphen (U+00AD) in any page: copied text must not contain them.
* Math: no raw $...$ TeX or build placeholders left in prose; every page with
  KaTeX output links the bundled katex.min.css; formulas are LTR-isolated.
* List of figures (fa, en): one entry per figure of the book; each
  entry shows the figure number and the FULL caption of that figure (as on the
  chapter page) and links to the figure.
* Index (fa, en): both editions list the same terms with the same chapters and
  link targets; every target section exists and its text uses the term; no
  space before the Persian comma; fa: Persian-equivalent entries sorted in
  Persian alphabetical order under letter headings, then a Latin section;
  every jump-bar letter points to a heading.

Usage: tools/check_lists.py [--site build/site]
"""
from __future__ import annotations

import argparse
import os
import re
import sys

import yaml
from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import bookindex  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
SITE = os.path.abspath(ap.parse_args().site)
problems = []
summary = []
cache = {}


def page(lang, slug):
    k = (lang, slug)
    if k not in cache:
        p = os.path.join(SITE, lang, slug + '.html')
        cache[k] = BeautifulSoup(open(p, encoding='utf-8').read(), 'html.parser') if os.path.exists(p) else None
    return cache[k]


def norm(s):
    return re.sub(r'\s+', ' ', s.replace('\u200f', '').replace('\u200e', '')).strip()


def text(node):
    node = BeautifulSoup(str(node), 'html.parser')
    for m in node.select('.math[data-plain]'):
        m.replace_with(m['data-plain'])
    return norm(node.get_text(' '))


# ---- whole site: soft hyphens, math leftovers
n_pages = 0
for lang in ('fa', 'en'):
    for fn in sorted(os.listdir(os.path.join(SITE, lang))):
        if not fn.endswith('.html'):
            continue
        n_pages += 1
        raw = open(os.path.join(SITE, lang, fn), encoding='utf-8').read()
        if '\u00ad' in raw or '&shy;' in raw:
            problems.append(f'{lang}/{fn}: contains soft hyphens (U+00AD)')
        if '\ue000' in raw or '\ue001' in raw:
            problems.append(f'{lang}/{fn}: unreplaced math placeholder')
        if 'class="katex"' in raw and 'katex/katex.min.css' not in raw:
            problems.append(f'{lang}/{fn}: KaTeX output without the katex stylesheet')
        soup = BeautifulSoup(raw, 'html.parser')
        main = soup.find('main') or soup
        for el in main.select('.math'):
            if el.get('dir') != 'ltr':
                problems.append(f'{lang}/{fn}: formula without dir=ltr')
        for x in main.select('pre, code, script, .katex, .math, .term'):
            x.decompose()
        t = main.get_text(' ')
        for m in re.finditer(r'\$(?=\S)[^$\n]+?(?<=\S)\$(?!\d)', t):
            problems.append(f'{lang}/{fn}: raw TeX in text: {m.group(0)[:40]}')
        for m in re.finditer(r'\w\)?\^[\w({-]', t):
            problems.append(f'{lang}/{fn}: bare ^ exponent in text: …{t[max(0, m.start() - 15):m.end() + 10]}…')
            break
summary.append(f'{n_pages} pages')

# ---- list of figures
# chapters and the appendices that can hold figures (the upgrade, RGW security and multisite/DR guides)
APPENDIX_PAGES = {'troubleshooting', 'versions', 'upgrade', 'security', 'multisite-dr'}
FIGN = {}
for lang in ('fa', 'en'):
    lof = page(lang, 'figures')
    rows = lof.select('main td.tt a') if lof else []
    nums = lof.select('main td.tn') if lof else []
    figs_seen = 0
    for a, tn in zip(rows, nums):
        href = a['href']
        slug, _, fid = href.partition('.html#')
        tgt = page(lang, slug)
        fig = tgt.find(id=fid) if tgt else None
        if fig is None or fig.name != 'figure':
            problems.append(f'{lang}/figures: {href} does not point to a figure')
            continue
        figs_seen += 1
        cap = fig.find('figcaption')
        b = cap.find('b')
        label = text(b) if b else ''
        cap_txt = BeautifulSoup(str(cap), 'html.parser')
        bb = cap_txt.find('b')
        if bb:
            bb.decompose()
        full = text(cap_txt)
        if text(a) != full:
            problems.append(f'{lang}/figures: {href}: entry is not the figure caption: {text(a)[:50]!r} vs {full[:50]!r}')
        if norm(tn.get_text()) not in label:
            problems.append(f'{lang}/figures: {href}: number {norm(tn.get_text())} does not match {label!r}')
    n_book = sum(len(page(lang, f[:-5]).select('main figure[id^="fig-"]')) for f in os.listdir(os.path.join(SITE, lang))
                 if f.endswith('.html') and (f[:2].isdigit() or f[:-5] in APPENDIX_PAGES))
    FIGN[lang] = figs_seen
    if len(rows) != n_book or figs_seen != n_book:
        problems.append(f'{lang}/figures: {len(rows)} entries, {figs_seen} valid, but the chapters have {n_book} figures')
summary.append(f'figures list fa/en: {FIGN}')

# ---- index
GL = yaml.safe_load(open(os.path.join(ROOT, 'glossary', 'glossary.yaml'), encoding='utf-8'))
FA_TERM = {g['term']: g.get('fa_term') for g in GL}
MS = dict(bookindex.matchers([g['term'] for g in GL]))
entries = {}
FAN = []
for lang in ('fa', 'en'):
    ix = page(lang, 'book-index')
    main = ix.find('main')
    if re.search(r'\s،', main.get_text()):
        problems.append(f'{lang}/book-index: space before the Persian comma')
    ent = {}
    for li in main.select('ul.ixlist li'):
        term = norm((li.select_one('.ixe') or li.select_one('.ixt')).get_text())
        links = [x['href'] for x in li.select('.chs a')]
        if not links:
            problems.append(f'{lang}/book-index: {term} has no links')
        ent[term] = links
        for h in links:
            slug, _, sec = h.partition('.html#')
            tgt = page(lang, slug.replace('.html', ''))
            if tgt is None:
                problems.append(f'{lang}/book-index: {term}: missing page {h}')
                continue
            if sec and tgt.find(id=sec) is None:
                problems.append(f'{lang}/book-index: {term}: missing anchor {h}')
    entries[lang] = ent
    hs = {x['id'] for x in main.select('h2[id], h3[id]')}
    for a in main.select('nav.ix-jump a'):
        if a['href'][1:] not in hs:
            problems.append(f'{lang}/book-index: jump link {a["href"]} has no heading')
    if lang == 'fa':
        fa_terms = [norm(x.get_text()) for x in main.select('ul.ixlist li .ixt') if x.find_next_sibling(class_='ixe')]
        FAN.append(len(fa_terms))
        if fa_terms != sorted(fa_terms, key=bookindex.fa_key):
            problems.append('fa/book-index: Persian entries are not in Persian alphabetical order')
        lat = main.select_one('#ix-latin')
        for h in main.select('h3.ix-letter'):
            before_latin = lat is not None and h.find_previous('h2', id='ix-latin') is None
            if before_latin and not re.fullmatch('[\u0600-\u06FF]', h.get_text()):
                problems.append(f'fa/book-index: Persian letter group headed {h.get_text()!r}')
        if not lat:
            problems.append('fa/book-index: no Latin section')
        for li in main.select('ul.ixlist li'):
            t = li.select_one('.ixe')
            if t and FA_TERM.get(norm(t.get_text())) != norm(li.select_one('.ixt').get_text()):
                problems.append(f'fa/book-index: {norm(t.get_text())}: Persian label does not match the glossary')
if entries.get('fa') != entries.get('en'):
    d = set(entries['fa']) ^ set(entries['en'])
    diff = [t for t in set(entries['fa']) & set(entries['en']) if entries['fa'][t] != entries['en'][t]]
    problems.append(f'book-index: fa and en differ (terms only in one: {sorted(d)[:5]}, different links: {diff[:5]})')


# every target section uses the term in at least one edition
SEC = {}


def section_text(lang, slug, sec):
    if (lang, slug, sec) not in SEC:
        SEC[lang, slug, sec] = _section_text(page(lang, slug), sec)
    return SEC[lang, slug, sec]


def _section_text(soup, sec):
    h = soup.find(id=sec)
    if h is None:
        return ''
    buf = []
    for el in h.find_all_next():
        if el.name in ('h2', 'h3') and el is not h and el.get('id'):
            break
        if el.name in ('p', 'li', 'td', 'th', 'figcaption', 'blockquote', 'div') and not el.find(['p', 'li', 'td', 'figcaption']):
            c = BeautifulSoup(str(el), 'html.parser')
            for x in c.select('pre, code, a.url'):
                x.decompose()
            buf.append(text(c))
    return ' '.join(buf)


n_links = 0
for term, links in entries.get('en', {}).items():
    rx = MS.get(term)
    for h in links:
        slug, _, sec = h.partition('.html#')
        if not sec:
            continue
        n_links += 1
        if not any(rx.search(section_text(lg, slug, sec)) for lg in ('fa', 'en')):
            problems.append(f'book-index: {term} -> {h}: the section text does not use the term')
summary.append(f'index: {len(entries.get("en", {}))} terms ({FAN[0] if FAN else 0} with a Persian label), {n_links} links checked against section text')

for p in problems[:60]:
    print('check_lists:', p)
if len(problems) > 60:
    print(f'check_lists: ... and {len(problems) - 60} more')
print(f'check_lists: {", ".join(summary)}; {len(problems)} problems')
sys.exit(1 if problems else 0)
