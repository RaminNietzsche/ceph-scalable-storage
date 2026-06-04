#!/usr/bin/env python3
"""Build the multi-page web edition of one language (``make html``).

Usage: tools/build_site.py --lang fa|en [--book build/fa] [--out build/site]

Input is the print HTML that tools/build_book.py writes (<book>/book.html and
<book>/ix_hits.json), so the web edition renders exactly the same text, figures
and ALGO boxes as the PDF. The book is split into one page per chapter,
appendix and list, ids are mapped back to the stable source anchors
(``sec-NN-K``, ``fig-NN-name``, ``alg-NN-K``), code is highlighted with Pygments
at build time and fonts, figures, scripts and the search index are written next
to the pages, so the site works offline (also from file://) with no network.

Layout of <out>:
  index.html                 language chooser
  assets/                    site.css, site.js, pygments.css, fonts/, covers
  figures/chNN/*.png         figures used by either edition
  <lang>/*.html              pages; same file names in fa/ and en/
  <lang>/search-index.js     offline search documents
"""
from __future__ import annotations

import argparse
import glob
import html
import json
import os
import re
import shutil
import string
import subprocess
import sys

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag
from PIL import Image
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.mdlower import split_front_matter, parse_div  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--book')
ap.add_argument('--out')
args = ap.parse_args()
LANG = args.lang
OTHER = 'en' if LANG == 'fa' else 'fa'
BOOKDIR = os.path.abspath(args.book or os.path.join(ROOT, 'build', LANG))
OUT = os.path.abspath(args.out or os.path.join(ROOT, 'build', 'site'))
LOUT = os.path.join(OUT, LANG)
TPL = os.path.join(ROOT, 'templates', 'site')
C = os.path.join(ROOT, 'content', LANG)
UI = yaml.safe_load(open(os.path.join(C, 'ui.yaml'), encoding='utf-8'))
META = yaml.safe_load(open(os.path.join(C, 'metadata.yaml'), encoding='utf-8'))
STR = yaml.safe_load(open(os.path.join(TPL, 'strings.yaml'), encoding='utf-8'))
S = STR[LANG]
SO = STR[OTHER]
RTL = META.get('dir') == 'rtl'
DIR = 'rtl' if RTL else 'ltr'
FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹') if UI['digits'] == 'fa' else str.maketrans('', '')
EN = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
loc = lambda x: str(x).translate(FA)  # noqa: E731
esc = html.escape
BOOK = UI['book']

os.makedirs(LOUT, exist_ok=True)
for old in glob.glob(os.path.join(LOUT, '*.html')):
    os.remove(old)

src = open(os.path.join(BOOKDIR, 'book.html'), encoding='utf-8').read()
soup = BeautifulSoup(src, 'lxml')
IX = json.load(open(os.path.join(BOOKDIR, 'ix_hits.json'), encoding='utf-8'))

# ---------------------------------------------------------------- sources
IMG = re.compile(r'^!\[.*\]\((\S+?)\)\{#([\w:.-]+)\}\s*$')


def source_ids(path):
    """Figure and ALGO ids of one source file, in document order."""
    _, lines = split_front_matter(open(path, encoding='utf-8').read())
    figs, algos, inc = [], [], False
    for line in lines:
        if line.startswith('```'):
            inc = not inc
            continue
        if inc:
            continue
        m = IMG.match(line)
        if m:
            figs.append(m.group(2))
        d = parse_div(line)
        if d and d[0] and d[0][0] == 'algo' and d[1]:
            algos.append(d[1])
    return figs, algos


CHFILES = {}
for p in sorted(glob.glob(os.path.join(C, 'chapters', '[0-9][0-9]-*.md'))):
    fm = yaml.safe_load(split_front_matter(open(p, encoding='utf-8').read())[0]) or {}
    CHFILES[int(fm['chapter'])] = p

APPS = [('appA', 'glossary'), ('appB', 'cheatsheet'), ('appC', 'troubleshooting'), ('appD', 'versions'),
        ('appF', 'answers'), ('appG', 'bibliography'), ('appH', 'algorithms')]
APPSRC = {'appC': os.path.join(C, 'appendices', 'troubleshooting.md'),
          'appD': os.path.join(C, 'appendices', 'versions.md')}

# ---------------------------------------------------------------- helpers
FIGDIR = os.path.join(OUT, 'figures')
WEBFIG = os.path.join(ROOT, 'build', 'webfig')   # tools/render_web_figures.py (optional)
fmt = HtmlFormatter(nowrap=True, classprefix='')
LEX = {'text': None, '': None, 'console': 'console', 'sh': 'bash', 'shell': 'bash'}


def text_of(node):
    t = node.get_text(' ') if isinstance(node, Tag) else str(node)
    return re.sub(r'\s+', ' ', t.replace('\u200f', '').replace('\u200e', '')).strip()


def frag(markup):
    return BeautifulSoup(markup, 'html.parser')


def new(tag, attrs=None, text=None):
    t = soup.new_tag(tag)
    for k, v in (attrs or {}).items():
        t[k] = v
    if text is not None:
        t.string = text
    return t


def heading_inner(h):
    """Heading HTML without index anchors or the permalink."""
    h = BeautifulSoup(str(h), 'html.parser').find()
    for x in h.select('.ixa, .hanchor'):
        x.decompose()
    return ''.join(str(c) for c in h.contents).strip()


def copy_figure(abspath):
    rel = os.path.relpath(abspath, os.path.join(ROOT, 'figures'))
    if rel.startswith('..'):
        rel = os.path.join('misc', os.path.basename(abspath))
    dst = os.path.join(FIGDIR, rel)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(abspath):
        shutil.copy2(abspath, dst)
    return '../figures/' + rel.replace(os.sep, '/')


def hires(abspath):
    """Site URL of the high-resolution variant of a committed PNG, or None."""
    rel = os.path.relpath(abspath, os.path.join(ROOT, 'figures'))[:-4]
    for ext in ('.svg', '.webp'):
        src = os.path.join(WEBFIG, rel + ext)
        if os.path.exists(src):
            dst = os.path.join(FIGDIR, rel + ext)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
            return '../figures/' + (rel + ext).replace(os.sep, '/'), ext
    return None, None


def code_block(div):
    lab = div.find('span', class_='lang')
    lang = lab.get_text().strip() if lab else ''
    pre = div.find('pre')
    code = pre.get_text()
    name = LEX.get(lang, lang)
    body = esc(code, quote=False)
    if name and not (lang == 'text'):
        try:
            body = highlight(code, get_lexer_by_name(name), fmt).rstrip('\n')
        except ClassNotFound:
            pass
    long_ = ' long' if 'long' in div.get('class', []) else ''
    shown = esc(lang or 'code')
    return frag(f'<div class="code{long_}" data-lang="{esc(lang)}"><div class="code-head"><span class="lang" dir="ltr">{shown}</span>'
                f'<button type="button" class="copy" aria-label="{esc(S["copy_label"])}" data-done="{esc(S["copied"])}">{esc(S["copy"])}</button></div>'
                f'<pre dir="ltr" tabindex="0"><code class="hl">{body}</code></pre></div>')


# ---------------------------------------------------------------- pages
pages = []          # ordered
ids = {}            # any id (old or new) -> (slug, new id)


class Page:
    def __init__(self, slug, kind, title_html, nav_html, group, body, eyebrow='', chap=None):
        self.slug, self.kind, self.title_html, self.nav_html = slug, kind, title_html, nav_html
        self.group, self.body, self.eyebrow, self.chap = group, body, eyebrow, chap
        self.title_text = text_of(frag(title_html))
        self.nav_text = text_of(frag(nav_html))
        self.crumb = (f'{eyebrow}: {self.title_text}' if kind == 'appendix' else self.nav_text)
        self.sections = []
        pages.append(self)
        ids[slug] = (slug, '')


def body_of(section, drop):
    """Move the children of section into a new div, skipping tags named in drop."""
    wrap = soup.new_tag('div')
    for c in list(section.contents):
        if isinstance(c, Tag) and c.name in drop:
            continue
        wrap.append(c.extract())
    return wrap


def map_ids(body, page, figs=None, algos=None):
    figs, algos = list(figs or []), list(algos or [])
    chap = page.chap
    last = {2: page.slug, 3: page.slug}
    counters = {}
    for el in body.find_all(['h2', 'h3', 'h4', 'h5', 'figure', 'div', 'span']):
        old = el.get('id')
        if el.name == 'span':
            if old:
                ids[old] = (page.slug, old)
            continue
        if el.name == 'figure':
            nid = figs.pop(0) if figs else old
            el['id'] = nid
            ids[old] = (page.slug, nid)
            continue
        if el.name == 'div':
            if 'algo' in el.get('class', []):
                nid = algos.pop(0) if algos else old
                el['id'] = nid
                ids[old] = (page.slug, nid)
            elif old:
                ids[old] = (page.slug, old)
            continue
        lvl = int(el.name[1])
        if old and chap and re.match(r'^s\d+-', old):
            nid = 'sec-%02d-%s' % (chap, old.split('-', 1)[1])
        elif old:
            nid = old
        else:
            parent = last.get(lvl - 1, page.slug) if lvl > 2 else page.slug
            counters[parent] = counters.get(parent, 0) + 1
            nid = f'{parent}-{counters[parent]}' if parent != page.slug else f'{page.slug}-{counters[parent]}'
        el['id'] = nid
        if old:
            ids[old] = (page.slug, nid)
        ids[nid] = (page.slug, nid)
        last[lvl] = nid
        if lvl in (2, 3):
            page.sections.append((lvl, nid, heading_inner(el)))
        a = new('a', {'class': 'hanchor', 'href': '#' + nid, 'aria-label': S['section_link']}, '#')
        el.append(a)


def decorate(body, page):
    for div in body.select('div.code'):
        div.replace_with(code_block(div))
    for fig in body.find_all('figure'):
        img = fig.find('img')
        p = img['src'].replace('file://', '')
        img['src'] = copy_figure(p)
        hi, ext = hires(p)
        if ext == '.svg':
            img['src'] = hi
            img['data-zoom'] = hi
        elif ext:
            img['srcset'] = f"{img['src']} 1x, {hi} 2x"
            img['data-zoom'] = hi
        w, h = Image.open(p).size
        img['width'], img['height'] = str(w), str(h)
        img['loading'] = 'lazy'
        img['decoding'] = 'async'
        cap = fig.find('figcaption')
        img['alt'] = text_of(cap) if cap else ''
        img['tabindex'] = '0'
        img['role'] = 'button'
        img['aria-label'] = S['zoom'] + ': ' + (text_of(cap)[:140] if cap else '')
        img['class'] = 'zoomable'
    for t in body.find_all('table'):
        if t.parent and 'table-wrap' in (t.parent.get('class') or []):
            continue
        w = new('div', {'class': 'table-wrap', 'tabindex': '0', 'role': 'region', 'aria-label': text_of(t.find('th'))[:60] if t.find('th') else 'table'})
        t.wrap(w)
    for div in body.select('div.call, div.sum, div.box'):
        div['role'] = 'note'
    for a in body.select('a.url'):
        a['rel'] = 'noopener'
    for td in body.select('td.pg'):
        td.decompose()
    for x in body.select('.en'):
        x['lang'] = 'en'
    if page.chap:
        for p_ in body.select('p.ansref'):
            p_.append(' ')
            p_.append(frag(f'<a class="anslink" href="answers.html#answers-{page.chap:02d}">{esc(S["answers_link"])} →</a>'))


# front matter ---------------------------------------------------------------
pref = soup.select_one('section#preface')
Page('preface', 'front', UI['preface'], UI['preface'], 'front', body_of(pref, ['h1']))
copyright_box = soup.select_one('.fm.copyright .cbox')

# chapters -------------------------------------------------------------------
SITE_PARTS = [(23, 34, 'part-low', 'part_low', 'part-3'), (34, 10 ** 6, 'part-spec', 'part_spec', 'part-4')]
PART_RANGE = {}
for sec in soup.select('section.chapter'):
    n = int(sec['id'][2:])
    for pstart, pend, pid, pkey, pslug in SITE_PARTS:
        part = soup.select_one(f'section#{pid}')
        if n == pstart and part is not None:
            desc = part.select_one('.pp-desc')
            pb = soup.new_tag('div')
            pb.append(frag(str(desc)))
            pg = Page(pslug, 'part', esc(UI[f'{pkey}_title']), esc(UI[f'{pkey}_toc']), 'chapters', pb, eyebrow=UI[f'{pkey}_word'])
            ids[pid] = (pslug, '')
            PART_RANGE[pslug] = (pstart, pend)
    word = text_of(sec.select_one('.ch-word'))
    title = ''.join(str(c) for c in sec.select_one('h1.ch-title').contents)
    slug = os.path.splitext(os.path.basename(CHFILES[n]))[0]
    body = sec.select_one('div.chbody')
    body.name = 'div'
    del body['class']
    pg = Page(slug, 'chapter', title, f'<span class="n">{loc(n)}</span><span class="t">{title}</span>', 'chapters', body.extract(),
              eyebrow=f'{word} {loc(n)}', chap=n)
    ids[f'ch{n}'] = (slug, '')
    figs, algos = source_ids(CHFILES[n])
    map_ids(pg.body, pg, figs, algos)
    decorate(pg.body, pg)

# appendices -----------------------------------------------------------------
afigs = []
for aid, key in APPS:
    sec = soup.select_one(f'section#{aid}')
    letter, title, short = UI['app'][key]
    body = body_of(sec, ['h1'])
    pg = Page(key, 'appendix', esc(title), f'<span class="n">{esc(letter)}</span><span class="t">{esc(short)}</span>', 'appendices', body,
              eyebrow=f'{UI["appendix"]} {letter}')
    ids[aid] = (key, '')
    figs, algos = source_ids(APPSRC[aid]) if aid in APPSRC else ([], [])
    if key == 'answers':
        for h in body.find_all('h2'):
            m = re.search(r'(\d+)', text_of(h).translate(EN))
            if m:
                h['id'] = 'answers-%02d' % int(m.group(1))
    map_ids(body, pg, figs, algos)
    decorate(body, pg)

# list of figures ------------------------------------------------------------
lof = soup.select_one('section#lof')
lb = body_of(lof, ['h1'])
pre_p = frag(f'<p class="lead">{esc(S["figures_intro"])}</p>')
lb.insert(0, pre_p)
Page('figures', 'list', esc(UI['lof']), esc(UI['lof']), 'lists', lb)
decorate(lb, pages[-1])
ids['lof'] = ('figures', '')

# index ----------------------------------------------------------------------
chap_slug = {p.chap: p.slug for p in pages if p.chap}
items = []
for term in sorted(IX, key=lambda t: t.lower()):
    first = {}
    for ch, aid in IX[term]:
        if ch and ch not in first:
            first[ch] = aid
    if not first:
        continue
    links = UI['list_sep'].join(f'<a href="{chap_slug[ch]}.html#{aid}">{loc(ch)}</a>' for ch, aid in sorted(first.items()))
    items.append(f'<li><span class="term" lang="en" dir="ltr">{esc(term)}</span> <span class="chs">{esc(UI["chapter_word"])} {links}</span></li>')
ib = frag(f'<div><p class="lead">{esc(S["index_intro"])}</p><ul class="ixlist">{"".join(items)}</ul></div>').find('div')
Page('book-index', 'list', esc(UI['index']), esc(UI['index']), 'lists', ib)
ids['index'] = ('book-index', '')
ids['toc'] = ('index', 'contents')
ids['preface'] = ('preface', '')

# ---------------------------------------------------------------- links
SLUGS = {p.slug for p in pages} | {'index'}
for p in pages:
    for a in p.body.find_all('a', href=True):
        h = a['href']
        if h.startswith('#') and not a.get('class') == ['hanchor']:
            tgt = h[1:]
            if tgt in ids:
                slug, nid = ids[tgt]
                if slug == p.slug:
                    a['href'] = '#' + nid if nid else '#top'
                else:
                    a['href'] = f'{slug}.html' + (f'#{nid}' if nid else '')

# ---------------------------------------------------------------- shared assets
ASSETS = os.path.join(OUT, 'assets')
os.makedirs(os.path.join(ASSETS, 'fonts'), exist_ok=True)


def fc(pattern):
    try:
        return subprocess.run(['fc-match', '-f', '%{file}', pattern], capture_output=True, text=True, check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ''


def fc_variable(need):
    try:
        out = subprocess.run(['fc-list', '-f', '%{file}\n', ':variable=true'], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return ''
    key = need.split()[0].lower()
    def ok(x):
        base = os.path.basename(x).lower().replace(' ', '')
        rest = base[len(key):]
        return (base.startswith(key) and 'italic' not in base
                and (rest[:1] in ('-', '_', '.', 'v') or rest.startswith('mono')))  # not Inter Tight/Display
    cands = sorted(filter(ok, out.splitlines()))
    return cands[0] if cands else ''


FONTS = [  # family, weight css, fc pattern, required family substring, unicode ranges, file
    ('Vazirmatn', '400', 'Vazirmatn:weight=80', 'Vazirmatn', 'U+0000-00FF,U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200B-206F,U+2190-21FF,U+2212', 'vazirmatn-400.woff2'),
    ('Vazirmatn', '500', 'Vazirmatn:weight=100', 'Vazirmatn', 'U+0000-00FF,U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200B-206F,U+2190-21FF,U+2212', 'vazirmatn-500.woff2'),
    ('Vazirmatn', '700', 'Vazirmatn:weight=200', 'Vazirmatn', 'U+0000-00FF,U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF,U+200B-206F,U+2190-21FF,U+2212', 'vazirmatn-700.woff2'),
    ('Inter', '100 900', 'Inter', 'Inter', 'U+0000-024F,U+0370-03FF,U+1E00-1EFF,U+2000-22FF,U+2500-25FF', 'inter-var.woff2'),
    ('JetBrains Mono', '100 800', 'JetBrains Mono', 'JetBrains', 'U+0000-024F,U+0370-03FF,U+2000-23FF,U+2500-259F,U+25A0-25FF', 'jetbrains-mono-var.woff2'),
]
faces = []
for fam, wt, pat, need, uni, fn in FONTS:
    dst = os.path.join(ASSETS, 'fonts', fn)
    if not os.path.exists(dst):
        f = fc(pat)
        if 'var' in fn:  # prefer an installed variable font (e.g. InterVariable.ttf) for weight ranges
            f = fc_variable(need) or f
        if need.split()[0].lower() not in os.path.basename(f).lower().replace(' ', ''):
            sys.exit(f'build_site: font {fam} not found by fontconfig; run tools/install_fonts.sh')
        from fontTools import subset
        opts = subset.Options()
        opts.flavor = 'woff2'
        opts.layout_features = ['*']
        opts.name_IDs = ['*']
        opts.notdef_outline = True
        font = subset.load_font(f, opts)
        sub = subset.Subsetter(opts)
        sub.populate(unicodes=subset.parse_unicodes(uni))
        sub.subset(font)
        subset.save_font(font, dst, opts)
    faces.append(f"@font-face{{font-family:'{fam}';font-style:normal;font-weight:{wt};font-display:swap;src:url(fonts/{fn}) format('woff2');unicode-range:{uni};}}")
open(os.path.join(ASSETS, 'fonts.css'), 'w', encoding='utf-8').write('\n'.join(faces) + '\n')
open(os.path.join(ASSETS, 'fonts', 'README.txt'), 'w', encoding='utf-8').write(
    'Vazirmatn (github.com/rastikerdar/vazirmatn), Inter (github.com/rsms/inter) and JetBrains Mono\n'
    '(github.com/JetBrains/JetBrainsMono) are subset copies licensed under the SIL Open Font License 1.1\n'
    '(openfontlicense.org). They are not covered by the book\'s CC BY-NC-SA 4.0 licence.\n')
for f in ('site.css', 'site.js'):
    shutil.copy2(os.path.join(TPL, f), os.path.join(ASSETS, f))
light = HtmlFormatter(style='friendly').get_style_defs('html:not([data-theme="dark"]) .hl')
dark = HtmlFormatter(style='github-dark').get_style_defs('html[data-theme="dark"] .hl')
drop_bg = lambda css: '\n'.join(l for l in css.split('\n') if not re.match(r'^\S.*\.hl \{ background', l) and 'pre {' not in l and '.hll' not in l and 'linenos' not in l and not l.startswith('td.') and not l.startswith('span.linenos'))  # noqa: E731
open(os.path.join(ASSETS, 'pygments.css'), 'w').write('/* generated by tools/build_site.py from Pygments styles friendly and github-dark */\n' + drop_bg(light) + '\n' + drop_bg(dark) + '\n')
cover_src = os.path.join(ROOT, 'assets', f'cover.{LANG}.png')
im = Image.open(cover_src).convert('RGB')
im.thumbnail((720, 1100))
im.save(os.path.join(ASSETS, f'cover.{LANG}.webp'), quality=86)
COVER_WH = im.size

# ---------------------------------------------------------------- chrome
ICON = {
    'menu': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M3 12h18M3 18h18"/></svg>',
    'search': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
    'sun': '<svg class="i-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4.5"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>',
    'moon': '<svg class="i-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20 14.5A8 8 0 0 1 9.5 4a8 8 0 1 0 10.5 10.5z"/></svg>',
    'globe': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z"/></svg>',
    'chev': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m9 6 6 6-6 6"/></svg>',
    'close': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    'panel': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>',
    'arrow': '<svg class="i-arrow" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
    'spark': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6 6l2.5 2.5M15.5 15.5 18 18M6 18l2.5-2.5M15.5 8.5 18 6"/></svg>',
    'cluster': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="5" r="2.2"/><circle cx="5" cy="18" r="2.2"/><circle cx="19" cy="18" r="2.2"/><path d="M11 7 6 16M13 7l5 9M7.2 18h9.6"/></svg>',
    'deploy': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="4" width="18" height="6" rx="1.5"/><rect x="3" y="14" width="18" height="6" rx="1.5"/><path d="M7 7h.01M7 17h.01M11 7h6M11 17h6"/></svg>',
    'ops': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/></svg>',
    'alert': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3 2 20h20L12 3z"/><path d="M12 10v4M12 17h.01"/></svg>',
    'code': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m8 7-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/></svg>',
    'layers': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 9 5-9 5-9-5 9-5z"/><path d="m3 13 9 5 9-5"/></svg>',
    'cpu': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="6" y="6" width="12" height="12" rx="2"/><path d="M9 2v4M15 2v4M9 18v4M15 18v4M2 9h4M2 15h4M18 9h4M18 15h4"/></svg>',
    'book': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5z"/><path d="M4 19a2 2 0 0 1 2-2h13"/></svg>',
}
GROUPS = [('front', S['front']), ('chapters', S['chapters']), ('appendices', S['appendices']), ('lists', S['lists'])]
order = [None] + pages  # None = home


SB_PART_LABEL = {1: S['sb_p1'], 22: S['sb_p2']}


def sidebar(cur):
    out = [f'<nav class="sidebar" id="sidebar" aria-label="{esc(S["navigation"])}"><div class="sb-head"><a class="sb-home" href="index.html">{esc(BOOK)}</a>'
           f'<button type="button" class="icon-btn sb-close" data-close-menu aria-label="{esc(S["close_menu"])}">{ICON["close"]}</button></div><div class="sb-scroll">']
    homecur = ' aria-current="page"' if cur is None else ''
    out.append(f'<ul class="sb-list"><li><a class="sb-link" href="index.html"{homecur}>{esc(S["home"])}</a></li></ul>')
    for g, label in GROUPS:
        out.append(f'<div class="sb-group">{esc(label)}</div><ul class="sb-list">')
        for p in pages:
            if p.group != g:
                continue
            if p.kind == 'chapter' and p.chap in SB_PART_LABEL:
                out.append(f'<li class="sb-part" role="presentation">{esc(SB_PART_LABEL[p.chap])}</li>')
            is_cur = p is cur
            curattr = ' aria-current="page"' if is_cur else ''
            cls = 'sb-link' + (' part' if p.kind == 'part' else '')
            kids = [s for s in p.sections if s[0] == 2]
            if kids and p.kind in ('chapter', 'appendix'):
                sid = f'sb-{p.slug}'
                exp = 'true' if is_cur else 'false'
                sub = ''.join(f'<li><a class="sb-sub" href="{p.slug}.html#{nid}" data-sec="{nid}">{t}</a></li>' for _, nid, t in kids)
                out.append(f'<li class="has-kids{" open" if is_cur else ""}"><div class="sb-row"><a class="{cls}" href="{p.slug}.html"{curattr}>{p.nav_html}</a>'
                           f'<button type="button" class="sb-tog" aria-expanded="{exp}" aria-controls="{sid}" aria-label="{esc(p.nav_text)}">{ICON["chev"]}</button></div>'
                           f'<ul class="sb-kids" id="{sid}"{"" if is_cur else " hidden"}>{sub}</ul></li>')
            else:
                out.append(f'<li><a class="{cls}" href="{p.slug}.html"{curattr}>{p.nav_html}</a></li>')
        out.append('</ul>')
    out.append('</div></nav>')
    return ''.join(out)


def header(cur):
    other = f'../{OTHER}/{cur.slug if cur else "index"}.html'
    return (f'<header class="topbar"><div class="tb-start">'
            f'<button type="button" class="icon-btn" id="menu-btn" aria-controls="sidebar" aria-expanded="false" aria-label="{esc(S["toggle_sidebar"])}">{ICON["menu"]}</button>'
            f'<a class="brand" href="index.html"><span class="logo" aria-hidden="true"></span>{esc(BOOK)}</a></div><div class="tb-end">'
            f'<button type="button" class="search-btn" id="search-btn" aria-haspopup="dialog" aria-label="{esc(S["search"])}">{ICON["search"]}<span class="sb-txt">{esc(S["search_placeholder"])}</span><kbd>/</kbd></button>'
            f'<a class="icon-btn lang-btn" href="{other}" hreflang="{OTHER}" lang="{OTHER}" title="{esc(SO["lang_name"])}">{ICON["globe"]}<span>{esc(SO["lang_name"])}</span></a>'
            f'<button type="button" class="icon-btn" id="theme-btn" aria-label="{esc(S["theme"])}" aria-pressed="false">{ICON["sun"]}{ICON["moon"]}</button>'
            f'<a class="tb-cta" href="index.html#get-started">{ICON["spark"]}<span>{esc(S["get_started"])}</span></a>'
            f'</div></header>')


def crumbs(cur):
    if cur is None:
        return ''
    glabel = dict(GROUPS)[cur.group]
    return (f'<nav class="crumbs" aria-label="{esc(S["breadcrumb"])}"><ol><li><a href="index.html">{esc(S["home"])}</a></li>'
            f'<li><span>{esc(glabel)}</span></li><li><a href="{cur.slug}.html" aria-current="page">{esc(cur.crumb)}</a></li></ol></nav>')


def pager(cur):
    i = order.index(cur)
    prv = order[i - 1] if i > 0 else None
    nxt = order[i + 1] if i + 1 < len(order) else None
    if i == 0:
        prv = None

    def card(p, rel, label):
        if p is None and rel == 'prev' and i == 1:
            return f'<a class="pg-card prev" rel="prev" href="index.html"><span class="pg-dir">{esc(label)}</span><span class="pg-t">{esc(S["home"])}</span></a>'
        if p is None:
            return '<span></span>'
        return f'<a class="pg-card {rel}" rel="{rel}" href="{p.slug}.html"><span class="pg-dir">{esc(label)}</span><span class="pg-t">{esc(p.nav_text)}</span></a>'
    return f'<nav class="pager" aria-label="{esc(S["prev"])} / {esc(S["next"])}">{card(prv, "prev", S["prev"])}{card(nxt, "next", S["next"])}</nav>'


def page_toc(cur):
    if cur is None or not cur.sections:
        return '', ''
    lis = []
    for lvl, nid, t in cur.sections:
        lis.append(f'<li class="l{lvl}"><a href="#{nid}" data-sec="{nid}">{t}</a></li>')
    ul = '<ul>' + ''.join(lis) + '</ul>'
    side = f'<aside class="toc" aria-label="{esc(S["on_this_page"])}"><div class="toc-title">{esc(S["on_this_page"])}</div>{ul}</aside>'
    inline = f'<details class="toc-inline"><summary>{esc(S["on_this_page"])}</summary>{ul}</details>'
    return side, inline


PAGE_TPL = string.Template(open(os.path.join(TPL, 'page.html'), encoding='utf-8').read())
SITE_DATA = json.dumps({k: S[k] for k in ('search', 'search_placeholder', 'search_hint', 'no_results', 'results', 'loading',
                                           'zoom_in', 'zoom_out', 'zoom_reset', 'close', 'copied', 'copy', 'zoom')} | {'lang': LANG, 'rtl': RTL}, ensure_ascii=False)


def emit(cur, main_html, title_text):
    side, inline = page_toc(cur)
    i = order.index(cur)
    links = []
    if i > 0:
        links.append(f'<link rel="prev" href="{order[i - 1].slug if order[i - 1] else "index"}.html">')
    if i + 1 < len(order):
        links.append(f'<link rel="next" href="{order[i + 1].slug}.html">')
    slug = cur.slug if cur else 'index'
    doc = PAGE_TPL.substitute(
        lang=LANG, dir=DIR, other=OTHER, slug=slug, title=esc(title_text), book=esc(BOOK),
        links='\n'.join(links), site_data=SITE_DATA.replace('</', '<\\/'),
        skip=esc(S['skip']), header=header(cur), sidebar=sidebar(cur), crumbs=crumbs(cur),
        toc_inline=inline, main=main_html, pager=pager(cur), toc=side,
        has_toc='has-toc' if side else 'no-toc', kind=cur.kind if cur else 'home',
        search_title=esc(S['search']), search_placeholder=esc(S['search_placeholder']), close=esc(S['close']),
        search_hint=esc(S['search_hint']), lic=esc('© 2026 Ramin Najarbashi · CC BY-NC-SA 4.0'), version=esc(META['version_display']),
        date=esc(META['date_display']))
    open(os.path.join(LOUT, f'{slug}.html'), 'w', encoding='utf-8').write(doc)


# ---------------------------------------------------------------- hyphenation
HYPH = None
if LANG == 'en':
    import pyphen
    _dic = pyphen.Pyphen(lang='en_US', left=3, right=3)
    _word = re.compile(r'[A-Za-z]{7,}')
    SKIP = ('pre', 'code', 'kbd', 'h1', 'h2', 'h3', 'h4', 'h5', 'script', 'style', 'th')

    def HYPH(body):
        """Insert soft hyphens (U+00AD) into long English words of justified prose,
        so justified text does not gap in browsers without hyphenation dictionaries."""
        for t in list(body.find_all(string=True)):
            if type(t) is not NavigableString or not t.strip():
                continue
            if t.find_parent(SKIP) or t.find_parent(class_=['url', 'code', 'hanchor', 'term', 'cmd', 'src']):
                continue
            new_t = _word.sub(lambda m: m.group(0) if any(c.isupper() for c in m.group(0)[1:]) else _dic.inserted(m.group(0), hyphen='\u00ad'), str(t))
            if new_t != str(t):
                t.replace_with(NavigableString(new_t))

# ---------------------------------------------------------------- write pages
docs = []


def index_docs(p):
    """One search document per h2/h3 section (plus the page head)."""
    state = {'id': '', 't': p.title_text, 'buf': []}

    def flush():
        txt = re.sub(r'\s+', ' ', ' '.join(state['buf'])).strip()
        if txt or not state['id']:
            url = f'{p.slug}.html' + (f'#{state["id"]}' if state['id'] else '')
            docs.append([url, state['t'], p.nav_text if state['id'] else (p.eyebrow or ''), txt[:6000]])
    for el in p.body.descendants:
        if isinstance(el, Tag):
            if el.name in ('h2', 'h3') and el.get('id'):
                flush()
                state.update(id=el['id'], t=text_of(frag(heading_inner(el))), buf=[])
            continue
        if type(el) is not NavigableString:
            continue
        if el.find_parent(['h2', 'h3']) or el.find_parent(class_='hanchor') or el.find_parent(class_='code-head'):
            continue
        state['buf'].append(str(el).replace('\u200f', ''))
    flush()


for p in pages:
    if p.kind not in ('list',):
        index_docs(p)
    if HYPH:
        HYPH(p.body)
    eyebrow = f'<div class="eyebrow">{esc(p.eyebrow)}</div>' if p.eyebrow else ''
    extra = ''
    if p.kind == 'part':
        lo, hi = PART_RANGE.get(p.slug, (23, 10 ** 6))
        lis = ''.join(f'<li><a href="{q.slug}.html">{q.nav_html}</a></li>' for q in pages if q.chap and lo <= q.chap < hi)
        extra = f'<ol class="part-list">{lis}</ol>'
    main = f'<article class="content" id="top"><header class="page-head">{eyebrow}<h1>{p.title_html}</h1></header>{"".join(str(c) for c in p.body.contents)}{extra}</article>'
    tt = (f'{p.eyebrow}: ' if p.kind in ('chapter', 'appendix') else '') + p.title_text + ' · ' + BOOK
    emit(p, main, tt)

# home ----------------------------------------------------------------------
grp = []
for g, label in GROUPS:
    lis = []
    for p in pages:
        if p.group != g:
            continue
        secs = ''
        if p.kind == 'chapter':
            secs = '<span class="secs">' + ' · '.join(t for lvl, _, t in p.sections if lvl == 2)[:0] + '</span>'
            secs = '<span class="secs">' + ' · '.join(text_of(frag(t)) for lvl, _, t in p.sections if lvl == 2 and not text_of(frag(t)).startswith((UI['review_questions'], UI['chapter_sources'])))[:220] + '</span>'
        cls = ' class="part"' if p.kind == 'part' else ''
        lis.append(f'<li{cls}><a href="{p.slug}.html"><span class="ct">{p.nav_html}</span>{secs}</a></li>')
    grp.append(f'<h3>{esc(label)}</h3><ol class="home-toc g-{g}">{"".join(lis)}</ol>')
about = ''.join(str(c) for c in copyright_box.contents) if copyright_box else ''
for x in ('<span class="en">',):
    about = about.replace(x, '<span class="en" lang="en">')
first = pages[0]
CH = {p.chap: p for p in pages if p.kind == 'chapter'}
PG = {p.slug: p for p in pages}
from booklib.structure import canonical_counts  # noqa: E402
N_ALGO, N_FIG = canonical_counts(ROOT)


def ch_href(n):
    return f'{CH[n].slug}.html' if n in CH else f'{first.slug}.html'


ROLES = [('cluster', 1, 1), ('deploy', 2, 11), ('ops', 3, 7), ('alert', 4, 17), ('code', 5, 22), ('layers', 6, 'part-4')]
gs_cards = []
for icon, k, tgt in ROLES:
    href = f'{tgt}.html' if isinstance(tgt, str) and tgt in PG else ch_href(tgt if isinstance(tgt, int) else 34)
    tag = esc(UI['part_spec_word']) if isinstance(tgt, str) else f'{esc(UI["chapter_word"])} {loc(tgt)}'
    gs_cards.append(f'<a class="hcard role r{k}" href="{href}"><span class="hc-ic">{ICON[icon]}</span><span class="hc-tag">{tag}</span>'
                    f'<span class="hc-t">{esc(S[f"role{k}_t"])}</span><span class="hc-d">{esc(S[f"role{k}_d"])}</span>'
                    f'<span class="hc-go">{esc(S["gs_go"])} {ICON["arrow"]}</span></a>')
PARTS_HOME = [('book', S['p1_word'], S['p1_title'], S['p1_range'], S['p1_desc'], 1, 21, ch_href(1), False),
              ('code', S['p2_word'], S['p2_title'], S['p2_range'], S['p2_desc'], 22, 22, ch_href(22), False),
              ('cpu', UI['part_low_word'], UI['part_low_title'], S['p3_range'], UI['part_low_md'], 23, 33, 'part-3.html' if 'part-3' in PG else ch_href(23), False),
              ('layers', UI['part_spec_word'], UI['part_spec_title'], S['p4_range'], UI['part_spec_md'], 34, 42, 'part-4.html' if 'part-4' in PG else ch_href(34), True)]
part_cards = []
for i, (icon, word, title, rng, desc, lo, hi, href, new_) in enumerate(PARTS_HOME, 1):
    chips = ''.join(f'<a class="chip" href="{ch_href(n)}" title="{esc(text_of(frag(CH[n].title_html)))}">{loc(n)}</a>' for n in range(lo, hi + 1) if n in CH)
    badge = f'<span class="hc-new">{esc(S["new"])}</span>' if new_ else ''
    part_cards.append(f'<div class="pcard p{i}"><div class="pc-top"><span class="hc-ic">{ICON[icon]}</span><span class="hc-tag">{esc(word)} · {esc(rng)}</span>{badge}</div>'
                      f'<h3><a href="{href}">{esc(title)}</a></h3><p>{esc(desc)}</p><div class="chips">{chips}</div></div>')
nparts = len(PARTS_HOME)
stats = (f'<div class="stats"><div><b>{loc(len(CH))}</b><span>{esc(S["stat_ch"])}</span></div><div><b>{loc(N_FIG)}</b><span>{esc(S["stat_fig"])}</span></div>'
         f'<div><b>{loc(N_ALGO)}</b><span>{esc(S["stat_algo"])}</span></div><div><b>{loc(nparts)}</b><span>{esc(S["stat_parts"])}</span></div></div>')
term = ('<div class="term" dir="ltr" aria-hidden="true"><div class="term-bar"><i></i><i></i><i></i><span>' + esc(S['term_label']) + '</span></div>'
        '<pre><span class="tp">$</span> ceph -s\n  cluster:\n    health: <span class="tok">HEALTH_OK</span>\n  services:\n    mon: 3 daemons, quorum a,b,c\n'
        '    osd: 36 osds: 36 up, 36 in\n    rgw: 3 daemons active\n  data:\n    pgs: <span class="tok">1024 active+clean</span></pre></div>')
home = f'''<article class="content home" id="top">
<section class="hero"><div class="hero-text">
<div class="hbadge"><span class="pulse" aria-hidden="true"></span>{esc(S["badge"].format(v=loc(META["version_display"])))}</div>
<div class="eyebrow">{esc(S["study_guide"])}</div><h1>{esc(BOOK).replace("Ceph", '<span class="grad">Ceph</span>')}</h1>
<p class="subtitle">{esc(META.get("subtitle", ""))}</p><p class="lead">{esc(S["hero_lead"])}</p>
<p class="cta"><a class="btn primary" href="{first.slug}.html">{esc(S["start"])} {ICON["arrow"]}</a> <a class="btn" href="#get-started">{esc(S["get_started"])}</a> <a class="btn ghost" href="../{OTHER}/index.html" hreflang="{OTHER}" lang="{OTHER}">{esc(S["read_in_other"])}</a></p>
{stats}
<p class="byline">{esc(S["written_by"])}</p><p class="meta">{esc(S["version"])} {esc(loc(META["version_display"]))} · {esc(META["date_display"])}<br>{esc(S["basis"])}: <span dir="auto">{esc(META["technical_basis"])}</span></p></div>
<div class="hero-art"><div class="glow" aria-hidden="true"></div><img class="cover" src="../assets/cover.{LANG}.webp" width="{COVER_WH[0]}" height="{COVER_WH[1]}" alt="{esc(BOOK)}">{term}</div></section>
<section class="hsec" id="get-started" aria-labelledby="gs-h"><div class="hsec-head"><h2 id="gs-h">{esc(S["gs_title"])}</h2><p>{esc(S["gs_sub"])}</p></div><div class="hgrid roles">{"".join(gs_cards)}</div></section>
<section class="hsec" id="parts" aria-labelledby="parts-h"><div class="hsec-head"><h2 id="parts-h">{esc(S["parts_title"])}</h2><p>{esc(S["parts_sub"])}</p></div><div class="hgrid parts">{"".join(part_cards)}</div></section>
<section class="hsec" aria-labelledby="contents"><div class="hsec-head"><h2 id="contents">{esc(S["contents"])}</h2></div>{"".join(grp)}</section>
<section class="about" aria-labelledby="about-h"><h2 id="about-h">{esc(S["about"])}</h2>{about}</section></article>'''
emit(None, home, BOOK)
docs.insert(0, ['index.html', BOOK, '', text_of(frag(about))])
open(os.path.join(LOUT, 'search-index.js'), 'w', encoding='utf-8').write(
    'window.__SEARCH_DOCS__=' + json.dumps(docs, ensure_ascii=False, separators=(',', ':')) + ';\n')

# language chooser ----------------------------------------------------------
STR_FA, STR_EN = STR['fa'], STR['en']
ui_other = yaml.safe_load(open(os.path.join(ROOT, 'content', OTHER, 'ui.yaml'), encoding='utf-8'))
books = {LANG: BOOK, OTHER: ui_other['book']}
chooser = f'''<!doctype html>
<html lang="en" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(books["en"])} · {esc(books["fa"])}</title><link rel="stylesheet" href="assets/fonts.css"><link rel="stylesheet" href="assets/site.css">
<script>try{{var t=localStorage.getItem('book-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=t}}catch(e){{}}</script></head>
<body class="chooser"><main><h1><span lang="fa" dir="rtl">{esc(STR_FA["choose"])}</span> · {esc(STR_EN["choose"])}</h1><div class="choose-grid">
<a class="choose-card" href="fa/index.html" lang="fa" dir="rtl"><img src="assets/cover.fa.webp" alt="" width="240"><span>{esc(books["fa"])}</span><small>فارسی (متن اصلی)</small></a>
<a class="choose-card" href="en/index.html" lang="en"><img src="assets/cover.en.webp" alt="" width="240"><span>{esc(books["en"])}</span><small>English (translation)</small></a>
</div><p class="lic">© 2026 Ramin Najarbashi · CC BY-NC-SA 4.0</p></main></body></html>
'''
open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(chooser)
if not os.path.exists(os.path.join(ASSETS, f'cover.{OTHER}.webp')):
    im = Image.open(os.path.join(ROOT, 'assets', f'cover.{OTHER}.png')).convert('RGB')
    im.thumbnail((720, 1100))
    im.save(os.path.join(ASSETS, f'cover.{OTHER}.webp'), quality=86)
print(json.dumps({'lang': LANG, 'pages': len(pages) + 1, 'search_docs': len(docs), 'out': os.path.relpath(LOUT, ROOT)}))
