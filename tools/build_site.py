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
import concurrent.futures
import subprocess
import tempfile
import time
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
from booklib import seo  # noqa: E402
from booklib import siteconf  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--book')
ap.add_argument('--out')
ap.add_argument('--site-url', default=os.environ.get('SITE_URL', ''), help='public base URL, e.g. https://example.org/ceph; enables canonical links and absolute URLs')
args = ap.parse_args()
U = seo.Urls(args.site_url)
CFG = siteconf.load(args.site_url)   # REPO_URL, FEEDBACK_ENDPOINT, NEWSLETTER_ACTION, ANALYTICS, CF_BEACON_TOKEN, CNAME (env only)
ANALYTICS_TAG = siteconf.analytics_tag(CFG)
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
        ('appF', 'answers'), ('appG', 'bibliography'), ('appH', 'algorithms'), ('appI', 'changes')]
APPSRC = {'appC': os.path.join(C, 'appendices', 'troubleshooting.md'),
          'appD': os.path.join(C, 'appendices', 'versions.md')}

# ---------------------------------------------------------------- helpers
FIGDIR = os.path.join(OUT, 'figures')
WEBFIG = os.path.join(ROOT, 'build', 'webfig')   # tools/render_web_figures.py (optional)
fmt = HtmlFormatter(nowrap=True, classprefix='')
LEX = {'text': None, '': None, 'console': 'console', 'sh': 'bash', 'shell': 'bash'}


def text_of(node):
    if isinstance(node, Tag) and node.select_one('.math[data-plain]'):
        node = BeautifulSoup(str(node), 'html.parser')  # formulas read as their plain form (alt, labels)
        for m in node.select('.math[data-plain]'):
            m.replace_with(m['data-plain'])
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
    found = {}
    for ext in ('.svg', '.avif', '.webp'):
        src = os.path.join(WEBFIG, rel + ext)
        if os.path.exists(src):
            dst = os.path.join(FIGDIR, rel + ext)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if not os.path.exists(dst) or os.path.getmtime(dst) < os.path.getmtime(src):
                shutil.copy2(src, dst)
            found[ext] = '../figures/' + (rel + ext).replace(os.sep, '/')
    if '.svg' in found:
        return found['.svg'], '.svg', found
    if found:
        ext = '.avif' if '.avif' in found else '.webp'
        return found[ext], ext, found
    return None, None, found


AVIF_CACHE = os.path.join(ROOT, 'build', 'avif-cache')
AVIF_SPEED, AVIF_QUALITY = 6, 45  # avifenc: speed 6 is a good size/time trade-off


def avif_cache_path(png):
    rel = os.path.splitext(os.path.relpath(png, os.path.join(ROOT, 'figures')))[0] + '.avif'
    return os.path.join(AVIF_CACHE, rel.replace(os.sep, '/'))


def _avif_fresh(path, src):
    return os.path.exists(path) and os.path.getsize(path) > 0 and os.path.getmtime(path) >= os.path.getmtime(src)


def maybe_avif(src, dst, png=None):
    """Encode dst AVIF from src (PNG/WebP) if avifenc or magick is on PATH.

    ``png`` is the committed figure, used as the cache key under build/avif-cache/
    so CI can restore encodings across runs. Return dst or None.
    """
    cache = avif_cache_path(png) if png else None
    if _avif_fresh(dst, src):
        if cache and not _avif_fresh(cache, src):
            os.makedirs(os.path.dirname(cache), exist_ok=True)
            shutil.copy2(dst, cache)
        return dst
    if cache and _avif_fresh(cache, src):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(cache, dst)
        return dst
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    # avifenc does not read WebP; re-encode non-PNG sources through a temporary PNG.
    raster, tmp_png = src, None
    if not src.lower().endswith('.png'):
        try:
            im = Image.open(src)
            if im.mode not in ('RGB', 'RGBA'):
                im = im.convert('RGBA' if 'A' in im.getbands() else 'RGB')
            fd, tmp_png = tempfile.mkstemp(suffix='.png')
            os.close(fd)
            im.save(tmp_png, 'PNG')
            raster = tmp_png
        except OSError:
            raster = png or src
    fd, tmp = tempfile.mkstemp(suffix='.avif')
    os.close(fd)
    try:
        for argv in (
            ['avifenc', '-s', str(AVIF_SPEED), '-q', str(AVIF_QUALITY), raster, tmp],
            ['magick', raster, '-quality', str(AVIF_QUALITY), tmp],
        ):
            try:
                subprocess.run(argv, check=True, capture_output=True)
                if os.path.exists(tmp) and os.path.getsize(tmp) > 0:
                    if cache:
                        os.makedirs(os.path.dirname(cache), exist_ok=True)
                        shutil.copy2(tmp, cache)
                    shutil.move(tmp, dst)
                    return dst
            except (FileNotFoundError, subprocess.CalledProcessError):
                continue
    finally:
        for path in (tmp, tmp_png):
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except OSError:
                    pass
    return None


def collect_figure_pngs(*soups):
    out = []
    for soup_ in soups:
        if soup_ is None:
            continue
        for img in soup_.select('figure img[src]'):
            src = img['src'].replace('file://', '')
            if src.endswith('.png') and os.path.exists(src):
                out.append(os.path.abspath(src))
    # unique, stable order
    return list(dict.fromkeys(out))


def warm_avif_cache(pngs):
    """Encode unique figure AVIFs in parallel into the site tree and build/avif-cache/."""
    if not pngs:
        return
    if not shutil.which('avifenc') and not shutil.which('magick'):
        return
    jobs = []
    for pth in pngs:
        hi, ext, alts = hires(pth)
        if ext == '.svg':
            continue
        src = pth
        if alts.get('.webp'):
            cand = os.path.join(FIGDIR, alts['.webp'].split('figures/', 1)[-1])
            if os.path.exists(cand):
                src = cand
        dst = os.path.splitext(os.path.join(FIGDIR, os.path.relpath(pth, os.path.join(ROOT, 'figures'))))[0] + '.avif'
        if _avif_fresh(dst, src):
            maybe_avif(src, dst, png=pth)  # keep the cache in sync
            continue
        jobs.append((src, dst, pth))
    if not jobs:
        print(f'avif: {len(pngs)} figure(s) already encoded')
        return
    t0 = time.time()
    workers = max(1, min(8, os.cpu_count() or 4))
    ok = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(maybe_avif, src, dst, pth) for src, dst, pth in jobs]
        for fut in concurrent.futures.as_completed(futs):
            if fut.result():
                ok += 1
    print(f'avif: encoded {ok}/{len(jobs)} figure(s) with {workers} workers in {time.time() - t0:.1f}s '
          f'(cache {os.path.relpath(AVIF_CACHE, ROOT)}, speed={AVIF_SPEED}, q={AVIF_QUALITY})')


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
    since = div.get('data-since', '')
    badge = ''
    if since:   # release label (booklib.cephver); links to the release-changes appendix
        b = div.find('span', class_='since')
        badge = (f'<a class="since s-{esc(since)}" href="changes.html#rel-{esc(since) if since != 'main' else 'labels'}" title="{esc(b.get("title", "") if b else "")}" dir="ltr">'
                 f'{esc(b.get_text() if b else since)}</a>')
    ds = f' data-since="{esc(since)}"' if since else ''
    return frag(f'<div class="code{long_}" data-lang="{esc(lang)}"{ds}><div class="code-head"><span class="ch-l"><span class="lang" dir="ltr">{shown}</span>{badge}</span>'
                f'<button type="button" class="copy" aria-label="{esc(S["copy_label"])}" data-done="{esc(S["copied"])}">{esc(S["copy"])}</button></div>'
                f'<pre dir="ltr" tabindex="0"><code class="hl">{body}</code></pre></div>')


# ---------------------------------------------------------------- simulators
# templates/site/sims: the interactive lab. The chapters carry <div class="sim-slot" data-sim="NAME">
# (from ::: {.sim name="NAME"}); sims.js mounts the live simulator there and the static figure made
# by tools/sim_fallback.js (the same view code, run in node) is what print and no-JS readers see.
SIMDIR = os.path.join(TPL, 'sims')
SIMY = yaml.safe_load(open(os.path.join(SIMDIR, f'strings-{LANG}.yaml'), encoding='utf-8'))
SIM_PARTS = ['crush-ln-table.js', 'sim-core.js', 'sims.js', 'sim-crush.js', 'sim-placement.js', 'sim-calc.js', 'sim-peering.js', 'sim-flow.js', 'sim-striping.js', 'sim-ui.js']
SIM_NAMES = ['crush', 'placement', 'pgcalc', 'ecprofile', 'peering', 'bluestore', 'rgwput', 'striping']
# Labs added later live in their own file, templates/site/sims/lab-NAME.js, with their strings under keys that
# start with "NAME_". They are loaded only on the pages that show them (assets/lab-NAME.js + LANG/sim-data-NAME.js).
SIM_LAZY = [n for n in (yaml.safe_load(open(os.path.join(SIMDIR, 'labs.yaml'), encoding='utf-8')) or [])]
SIM_NAMES += SIM_LAZY
SIM_HOME = ['placement', 'crush', 'ecdecode', 'capacity', 'sigv4', 'quorum', 'peering', 'mdspin']   # the cards on the home page
SIM_WHERE = {n: [] for n in SIM_NAMES}   # name -> [(page, section id, section title)]


def sim_fallbacks():
    node = shutil.which('node')
    if not node:
        print('build_site: node not found; simulators get a text-only fallback', file=sys.stderr)
        return {'html': {}, 'icon': {}}
    # plus "name:mode" for every simulator a chapter opens in one of its modes
    modes = set()
    for f in glob.glob(os.path.join(ROOT, 'content', LANG, '**', '*.md'), recursive=True):
        modes.update(f'{n}:{m}' for n, m in re.findall(r'\{\.sim name="(\w+)" mode="(\w+)"\}', open(f, encoding='utf-8').read()))
    r = subprocess.run([node, os.path.join(ROOT, 'tools', 'sim_fallback.js')], input=json.dumps({'lang': LANG, 'strings': SIMY, 'names': SIM_NAMES + sorted(modes)}),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


SIMFB = sim_fallbacks()


def sim_icon(name):
    d = SIMFB['icon'].get(name, 'M4 4h16v16H4z')
    return f'<svg class="sim-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="{d}"/></svg>'


# the parts of each static figure that make a readable preview (first match of each)
THUMB_PARTS = {'crush': ('sim-stats', 'sim-fig'), 'placement': ('pl-flow', 'sim-stats'), 'pgcalc': ('sim-stats', 'table-wrap'), 'ecprofile': ('sim-stats', 'ec-cards'),
               'peering': ('ps-top', 'ps-osds'), 'bluestore': ('sim-stats', 'sim-fig'), 'rgwput': ('sim-stats', 'sim-fig'),
               'striping': ('sim-stats', 'st-sets'), 'capacity': ('sim-stats', 'sim-fig')}


def sim_thumb(name):
    """Preview for a lab card: the visual part (.sim-out) of the static figure, scaled down by CSS.
    Interactive or linking elements are flattened (the card itself is the link) and ids get a
    prefix so they stay unique next to a live simulator. Without node, a large icon stands in."""
    h = SIMFB['html'].get(name)
    out = frag(h).select_one('.sim-out') if h else None
    if out is None:
        return f'<div class="lab-thumb lab-thumb-ph" aria-hidden="true">{sim_icon(name)}</div>'
    keep, seen = THUMB_PARTS.get(name, ()), set()
    for c in list(out.find_all(recursive=False)):
        cls = next((k for k in keep if k in (c.get('class') or [])), None)
        if keep and (cls is None or cls in seen):
            c.decompose()
        elif cls:
            seen.add(cls)
    for t in out.find_all(['a', 'button', 'summary']):
        t.name = 'span'
        for k in ('href', 'type', 'aria-pressed', 'aria-expanded', 'tabindex'):
            t.attrs.pop(k, None)
    for t in out.find_all(['details', 'input', 'select', 'textarea']):
        if t.name == 'details':
            t.name = 'div'
            t.attrs.pop('open', None)
        else:
            t.decompose()
    html_ = str(out)
    for i in re.findall(r'\bid="([^"]+)"', html_):
        html_ = html_.replace(f'id="{i}"', f'id="th-{i}"').replace(f'#{i})', f'#th-{i})').replace(f'href="#{i}"', f'href="#th-{i}"')
    return (f'<div class="lab-thumb" aria-hidden="true"><div class="lab-thumb-in"><div class="sim sim-{name} sim-static">{html_}</div></div></div>')


def lab_card(name, where=''):
    return (f'<a class="lab-card" href="lab-{name}.html">{sim_thumb(name)}<span class="lab-card-h">{sim_icon(name)}<b>{esc(SIMY[name + "_t"])}</b></span>'
            f'<span class="lab-card-d">{esc(SIMY[name + "_d"])}</span>{where}</a>')


def sim_slot_html(name, mode=''):
    inner = SIMFB['html'].get(f'{name}:{mode}' if mode else name) or SIMFB['html'].get(name) or f'<div class="sim-head">{sim_icon(name)}<div class="sim-ttl"><h3>{esc(SIMY[name + "_t"])}</h3></div></div><p class="sim-sub">{esc(SIMY[name + "_d"])}</p>'
    return (f'<div class="sim-slot" data-sim="{name}"' + (f' data-mode="{esc(mode)}"' if mode else '') + f' data-href="lab-{name}.html"><figure class="sim-fallback"><div class="sim sim-{name} sim-static">{inner}</div>'
            f'<figcaption class="sim-cap">{esc(SIMY["static_note"])} <a href="lab-{name}.html">{esc(SIMY["lab_title"])}: {esc(SIMY[name + "_t"])}</a></figcaption></figure></div>')


def decorate_sims(body, page):
    for div in body.select('div.sim-slot'):
        name = div.get('data-sim', '')
        if name not in SIM_WHERE:
            sys.exit(f'build_site: unknown simulator "{name}" in {page.slug}')
        h = div.find_previous(['h2', 'h3'])
        SIM_WHERE[name].append((page, h.get('id', '') if h else '', text_of(frag(heading_inner(h))) if h else page.title_text))
        page.sims = getattr(page, 'sims', []) + [name]
        div.replace_with(frag(sim_slot_html(name, div.get('data-mode', ''))).find('div'))


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
        hi, ext, alts = hires(p)
        # Optionally build an AVIF next to the committed PNG / existing WebP.
        if ext != '.svg':
            src_for_avif = p
            if alts.get('.webp'):
                src_for_avif = os.path.join(FIGDIR, alts['.webp'].split('figures/', 1)[-1])
            avif_dst = os.path.splitext(os.path.join(FIGDIR, os.path.relpath(p, os.path.join(ROOT, 'figures'))))[0] + '.avif'
            if maybe_avif(src_for_avif if os.path.exists(src_for_avif) else p, avif_dst, png=p):
                alts['.avif'] = '../figures/' + os.path.relpath(avif_dst, FIGDIR).replace(os.sep, '/')
        if ext == '.svg':
            img['src'] = hi
            img['data-zoom'] = hi
        elif ext or alts:
            if hi:
                img['srcset'] = f"{img['src']} 1x, {hi} 2x"
                img['data-zoom'] = hi
            sources = []
            if alts.get('.avif'):
                sources.append(f'<source type="image/avif" srcset="{alts[".avif"]}">')
            if alts.get('.webp'):
                sources.append(f'<source type="image/webp" srcset="{alts[".webp"]}">')
            if sources:
                pic = new('picture')
                img.replace_with(pic)
                for s in sources:
                    pic.append(BeautifulSoup(s, 'html.parser'))
                pic.append(img)
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
    for div in body.select('div.tldr'):
        # the chapter-opening TL;DR: collapsible, open by default
        lab = div.select_one('.lab')
        det = new('details', {'class': 'tldr', 'open': ''})
        sm = new('summary')
        for c in list(lab.contents):
            sm.append(c.extract())
        det.append(sm)
        for c in list(div.contents):
            if c is not lab:
                det.append(c.extract())
        div.replace_with(det)
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
    decorate_sims(body, page)


# front matter ---------------------------------------------------------------
pref = soup.select_one('section#preface')
Page('preface', 'front', UI['preface'], UI['preface'], 'front', body_of(pref, ['h1']))
copyright_box = soup.select_one('.fm.copyright .cbox')

# Encode unique figure AVIFs once (parallel, cached) before pages start decorating.
warm_avif_cache(collect_figure_pngs(soup))

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
for _a in lb.select('td.tt a'):  # full chapter caption, not the print short label
    for _x in _a.select('.cap-short'):
        _x.decompose()
    for _x in _a.select('.cap-full'):
        _x.unwrap()
Page('figures', 'list', esc(UI['lof']), esc(UI['lof']), 'lists', lb)
decorate(lb, pages[-1])
ids['lof'] = ('figures', '')

# index ----------------------------------------------------------------------
# Built from the chapter sources of BOTH editions (booklib.bookindex): whole-word prose
# occurrences only, united per section, so fa and en list the same terms and targets.
# Every chapter number links to the first section of that chapter that uses the term.
from booklib import bookindex  # noqa: E402
_GL = yaml.safe_load(open(os.path.join(ROOT, 'glossary', 'glossary.yaml'), encoding='utf-8'))
FA_TERM = {g['term']: g['fa_term'] for g in _GL if re.match('[\u0600-\u06FF]', g.get('fa_term') or '')}  # Persian-initial only
IXOCC = bookindex.build(ROOT, [g['term'] for g in _GL])
chap_slug = {p.chap: p.slug for p in pages if p.chap}
SEP = UI['list_sep']


def ix_links(term):
    out = []
    for ch, secs in IXOCC[term].items():
        if ch not in chap_slug:
            continue
        sec, _ = secs[0]
        n = sum(k for _, k in secs)
        lab = f'{term} — {UI["chapter_word"]} {loc(ch)} ({S["ix_occ"].format(n=loc(n))})'
        out.append(f'<a href="{chap_slug[ch]}.html{"#" + sec if sec else ""}" aria-label="{esc(lab)}" title="{esc(S["ix_occ"].format(n=loc(n)))}">{loc(ch)}</a>')
    return SEP.join(out)


def ix_item(term, label_html):
    return f'<li>{label_html} <span class="chs">{esc(UI["chapter_word"])} {ix_links(term)}</span></li>'


groups = []   # (letter, heading id, [li])
_terms = [t for t in IXOCC if any(ch in chap_slug for ch in IXOCC[t])]
if LANG == 'fa':
    fa_items = sorted([t for t in _terms if FA_TERM.get(t)], key=lambda t: bookindex.fa_key(FA_TERM[t]))
    for t in fa_items:
        L = bookindex.fa_letter(FA_TERM[t])
        if not groups or groups[-1][0] != L:
            groups.append((L, f'ix-{len(groups) + 1}', []))
        groups[-1][2].append(ix_item(t, f'<span class="ixt">{esc(FA_TERM[t])}</span> <span class="ixe" lang="en" dir="ltr">{esc(t)}</span>'))
    latin = sorted([t for t in _terms if not FA_TERM.get(t)], key=lambda t: t.lower())
else:
    latin = sorted(_terms, key=lambda t: t.lower())
n_fa_groups = len(groups)
for t in latin:
    L = t[0].upper()
    if len(groups) == n_fa_groups or groups[-1][0] != L:
        groups.append((L, f'ix-{len(groups) + 1}', []))
    groups[-1][2].append(ix_item(t, f'<span class="ixt" lang="en" dir="ltr">{esc(t)}</span>'))


def _jump(gs):
    return ''.join(f'<a href="#{gid}">{esc(L)}</a>' for L, gid, _ in gs)


_body = [f'<p class="lead">{esc(S["index_intro"])}</p>']
_nav = f'<nav class="ix-jump" aria-label="{esc(S["ix_jump"])}">'
if LANG == 'fa':
    _nav += f'<span class="ix-jump-fa">{_jump(groups[:n_fa_groups])}</span><span class="ix-jump-en" dir="ltr">{_jump(groups[n_fa_groups:])}</span>'
else:
    _nav += f'<span class="ix-jump-en">{_jump(groups)}</span>'
_body.append(_nav + '</nav>')
for k, (L, gid, lis) in enumerate(groups):
    if LANG == 'fa' and k == n_fa_groups:
        _body.append(f'<h2 class="ix-sec" id="ix-latin">{esc(S["ix_latin"])}</h2>')
    _body.append(f'<h3 class="ix-letter" id="{gid}"{" dir=ltr" if k >= n_fa_groups else ""}>{esc(L)}</h3><ul class="ixlist">{"".join(lis)}</ul>')
ib = frag('<div>' + ''.join(_body) + '</div>').find('div')
Page('book-index', 'list', esc(UI['index']), esc(UI['index']), 'lists', ib)
ids['index'] = ('book-index', '')
ids['toc'] = ('contents', '')
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
for f in ('site.css', 'site.js', 'game.js', 'ask.js'):
    shutil.copy2(os.path.join(TPL, f), os.path.join(ASSETS, f))
# KaTeX (MIT) styles + woff2 fonts for the formulas that build_book.py pre-renders; no runtime JS, no CDN
_kx = os.path.join(ROOT, 'templates', 'vendor', 'katex')
shutil.copytree(_kx, os.path.join(ASSETS, 'katex'), dirs_exist_ok=True, ignore=shutil.ignore_patterns('*.js'))  # the JS is for the build only
shutil.copy2(os.path.join(SIMDIR, 'sims.css'), os.path.join(ASSETS, 'sims.css'))
with open(os.path.join(ASSETS, 'sims.js'), 'w', encoding='utf-8') as _f:
    _f.write('/* The interactive lab of "Ceph: Scalable Storage", concatenated from templates/site/sims by tools/build_site.py.\n'
             ' * crush-ln-table.js is LGPL-2.1 data from Ceph (see NOTICE.md); the rest is CC BY-NC-SA 4.0. */\n')
    for _part in SIM_PARTS:
        _f.write(f'\n/* ---- {_part} ---- */\n' + open(os.path.join(SIMDIR, _part), encoding='utf-8').read())
_lazy_keys = {n: {k: v for k, v in SIMY.items() if k.startswith(n + '_')} for n in SIM_LAZY}
for _n in SIM_LAZY:
    shutil.copy2(os.path.join(SIMDIR, f'lab-{_n}.js'), os.path.join(ASSETS, f'lab-{_n}.js'))
    open(os.path.join(LOUT, f'sim-data-{_n}.js'), 'w', encoding='utf-8').write(
        'Object.assign(window.__SIMS__.s,' + json.dumps(_lazy_keys[_n], ensure_ascii=False, separators=(',', ':')) + ');\n')
_lazy_all = {k for d in _lazy_keys.values() for k in d}
open(os.path.join(LOUT, 'sim-data.js'), 'w', encoding='utf-8').write(
    'window.__SIMS__=' + json.dumps({'lang': LANG, 's': {k: v for k, v in SIMY.items() if k not in _lazy_all}}, ensure_ascii=False, separators=(',', ':')) + ';\n')
light = HtmlFormatter(style='friendly').get_style_defs('html:not([data-theme="dark"]) .hl')
dark = HtmlFormatter(style='github-dark').get_style_defs('html[data-theme="dark"] .hl')
drop_bg = lambda css: '\n'.join(l for l in css.split('\n') if not re.match(r'^\S.*\.hl \{ background', l) and 'pre {' not in l and '.hll' not in l and 'linenos' not in l and not l.startswith('td.') and not l.startswith('span.linenos'))  # noqa: E731
PYG_CONTRAST = '''
/* Contrast overrides for the light (friendly) theme: comments, numbers and names
   must meet WCAG AA against --code-bg #f6f8fa. */
html:not([data-theme="dark"]) .hl .c,
html:not([data-theme="dark"]) .hl .c1,
html:not([data-theme="dark"]) .hl .cm,
html:not([data-theme="dark"]) .hl .ch { color: #2c6570; font-style: italic; }
html:not([data-theme="dark"]) .hl .m,
html:not([data-theme="dark"]) .hl .mi,
html:not([data-theme="dark"]) .hl .mf,
html:not([data-theme="dark"]) .hl .mh { color: #0f6a3d; }
html:not([data-theme="dark"]) .hl .nv,
html:not([data-theme="dark"]) .hl .vc,
html:not([data-theme="dark"]) .hl .vg,
html:not([data-theme="dark"]) .hl .vi { color: #7a218d; }
'''
open(os.path.join(ASSETS, 'pygments.css'), 'w').write('/* generated by tools/build_site.py from Pygments styles friendly and github-dark */\n' + drop_bg(light) + '\n' + drop_bg(dark) + '\n' + PYG_CONTRAST)
cover_src = os.path.join(ROOT, 'assets', f'cover.{LANG}.png')
im = Image.open(cover_src).convert('RGB')
im.thumbnail((720, 1100))
im.save(os.path.join(ASSETS, f'cover.{LANG}.webp'), quality=86)
COVER_WH = im.size
seo.og_image(cover_src, os.path.join(ASSETS, f'og.{LANG}.png'), LANG, BOOK, META.get('subtitle', ''), META.get('author', ''))
seo.icons(os.path.join(ASSETS, 'icons'))
seo.manifest(os.path.join(LOUT, 'manifest.webmanifest'), BOOK, 'Ceph', LANG, DIR, seo.describe(META.get('subtitle', '')), '../assets/icons/')

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
    'clock': '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    'check': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12.5 4.5 4.5L19 7.5"/></svg>',
    'bookmark': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg>',
    'up': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 19V5M6 11l6-6 6 6"/></svg>',
    'download': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
    'upload': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 15V4M7 9l5-5 5 5M5 20h14"/></svg>',
    'trash': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
    'trophy': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 4h8v5a4 4 0 0 1-8 0V4zM8 6H5a3 3 0 0 0 3 4M16 6h3a3 3 0 0 1-3 4M12 13v4M8 21h8M9 17h6"/></svg>',
    'cards': '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="7" width="13" height="13" rx="2"/><path d="M8 4h11a2 2 0 0 1 2 2v11"/></svg>',
    'flame': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.2 1.6 1 2.6 2 3 0-3 .3-5.6.8-8.2z"/></svg>',
    'book': '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5z"/><path d="M4 19a2 2 0 0 1 2-2h13"/></svg>',
    'github': '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="currentColor" stroke="none" d="M12 2a10 10 0 0 0-3.16 19.49c.5.09.68-.22.68-.48v-1.7c-2.78.6-3.37-1.34-3.37-1.34-.45-1.16-1.11-1.47-1.11-1.47-.91-.62.07-.61.07-.61 1 .07 1.53 1.03 1.53 1.03.9 1.52 2.34 1.08 2.91.83.09-.66.35-1.08.63-1.33-2.22-.25-4.56-1.11-4.56-4.95 0-1.1.39-1.99 1.03-2.69-.1-.25-.45-1.27.1-2.65 0 0 .84-.27 2.75 1.02A9.56 9.56 0 0 1 12 6.8a9.6 9.6 0 0 1 2.5.34c1.91-1.29 2.75-1.02 2.75-1.02.55 1.38.2 2.4.1 2.65.64.7 1.03 1.6 1.03 2.69 0 3.85-2.34 4.7-4.57 4.95.36.31.68.92.68 1.85v2.74c0 .26.18.58.69.48A10 10 0 0 0 12 2z"/></svg>',
}
ICON['list'] = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 6h11M9 12h11M9 18h11M4 6h.01M4 12h.01M4 18h.01"/></svg>'
ICON['flask'] = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9 3h6M10 3v6l-5.6 9.6A1.6 1.6 0 0 0 5.8 21h12.4a1.6 1.6 0 0 0 1.4-2.4L14 9V3M7.2 15h9.6"/></svg>'
GROUPS = [('front', S['front']), ('chapters', S['chapters']), ('appendices', S['appendices']), ('lists', S['lists'])]
order = [None] + pages  # None = home


# ---------------------------------------------------------------- reading time / progress
WPM = 170 if LANG == 'fa' else 220   # technical prose; Persian words counted by whitespace (ZWNJ keeps a word whole)


def reading_minutes(body):
    words = code = figs = 0
    for el in body.find_all(string=True):
        if el.find_parent(['script', 'style']):
            continue
        if el.find_parent('pre'):
            code += str(el).count('\n')
        else:
            words += len(str(el).split())
    figs = len(body.find_all('figure'))
    return max(1, round(words / WPM + code * 3 / 60 + figs * 12 / 60))


def fmt_min(n, short=False):
    if n < 60:
        return S['min_short' if short else 'read_min'].format(n=loc(n))
    return S['hm_short' if short else 'read_hm'].format(h=loc(n // 60), m=loc(n % 60))


TRACK = {}
for _p in pages:
    if _p.kind in ('chapter', 'appendix', 'front'):
        _p.minutes = reading_minutes(_p.body)
        _t = _p.nav_text if _p.kind != 'chapter' else _p.title_text
        _t = re.sub(r'\(\s+', '(', re.sub(r'\s+\)', ')', re.sub(r'\s+([:؛،])', r'\1', _t))).strip()
        TRACK[_p.slug] = [_t, _p.minutes, _p.chap or 0]
# ---------------------------------------------------------------- learning data (cards, glossary) for review/quizzes
GAMEY = yaml.safe_load(open(os.path.join(TPL, 'game.yaml'), encoding='utf-8'))
GM = GAMEY[LANG]
PG_BY = {_p.slug: _p for _p in pages}
CARDS, GLOSS = [], []


def ltext(node):   # keeps the RLM marks around Latin runs (bidi) and does not add spaces between inline tags
    return re.sub(r'\s+', ' ', node.get_text('')).strip()


if 'answers' in PG_BY:
    for _h in PG_BY['answers'].body.find_all('h2', id=re.compile(r'^answers-\d+$')):
        _ch = int(_h['id'].split('-')[1])
        _ol = _h.find_next_sibling()
        if not (_ol and _ol.name == 'ol'):
            continue
        for _k, _li in enumerate(_ol.find_all('li', recursive=False), 1):
            _li = frag(str(_li))
            for _x in _li.select('.oln, .ixa'):
                _x.decompose()
            _b = _li.find('b')
            if not _b:
                continue
            _q = ltext(_b)
            _b.decompose()
            _a = ltext(_li)
            if _q and _a:
                CARDS.append([f'q{_ch}-{_k}', _ch, _q, _a])
if 'glossary' in PG_BY:
    _seen = set()
    for _tr in PG_BY['glossary'].body.select('table.gloss tbody tr'):
        _td = _tr.find_all('td')
        if len(_td) < 2:
            continue
        _t, _dd = ltext(_td[0]).replace('\u00ad', ''), ltext(_td[1]).replace('\u00ad', '')
        _id = 'g-' + (re.sub(r'[^a-z0-9]+', '-', _t.lower()).strip('-') or str(len(GLOSS)))
        while _id in _seen:
            _id += '-2'
        _seen.add(_id)
        GLOSS.append([_id, _t, _dd])
CARDS_BY_CH = {}
for _c in CARDS:
    CARDS_BY_CH[_c[1]] = CARDS_BY_CH.get(_c[1], 0) + 1
PROG_KEYS = ('read_min', 'min_short', 'mark_read', 'is_read', 'unmark_read', 'marked_read_msg', 'unmarked_read_msg', 'progress_line',
             'progress_empty', 'continue', 'bookmarks', 'bookmark_add', 'bookmark_remove', 'bookmarked_msg', 'unbookmarked_msg',
             'reset_confirm', 'import_ok', 'import_bad', 'reset_ok', 'part_prog', 'in_progress')


def ring(cls=''):
    return (f'<svg class="ring {cls}" viewBox="0 0 36 36" aria-hidden="true"><circle class="trk" cx="18" cy="18" r="15.5"/>'
            f'<circle class="val" cx="18" cy="18" r="15.5" pathLength="100"/></svg>')


SB_PART_LABEL = {1: S['sb_p1'], 22: S['sb_p2']}


class AppPage:
    """A page that is rendered by game.js (dashboard, review, certificate); not part of the reading order."""
    def __init__(self, slug, title):
        self.slug, self.kind, self.title_text, self.nav_text, self.crumb = slug, 'app', title, title, title
        self.sections, self.group, self.chap = [], None, None


APP_PAGES = {'progress': AppPage('progress', GM['s']['my_progress']), 'review': AppPage('review', GM['s']['review_page']),
             'certificate': AppPage('certificate', GM['s']['cert_page'])}


EXTRAS = (f'<div class="my-dlg" id="my-dlg" role="dialog" aria-modal="true" aria-labelledby="my-h" hidden><div class="my-box">'
          f'<div class="my-head"><h2 id="my-h">{ICON["bookmark"]}{esc(S["my_reading"])}</h2><button type="button" class="icon-btn" data-close-my aria-label="{esc(S["close"])}">{ICON["close"]}</button></div>'
          f'<div class="my-prog"><div class="ring-wrap">{ring("big")}<b class="my-pct"></b></div><div><div class="rp-t">{esc(S["progress_title"])}</div><p class="my-line"></p>'
          f'<a class="btn primary my-cont" href="index.html" hidden>{esc(S["continue"])} {ICON["arrow"]}</a></div></div>'
          f'<h3>{esc(S["bookmarks"])}</h3><ul class="mk-list" id="mk-list"></ul><p class="mk-empty">{esc(S["bookmarks_empty"])}</p>'
          f'<div class="my-actions"><button type="button" class="btn" data-act="export">{ICON["download"]}{esc(S["export"])}</button>'
          f'<label class="btn file-btn">{ICON["upload"]}<span>{esc(S["import"])}</span><input type="file" id="my-import" accept="application/json,.json"></label>'
          f'<button type="button" class="btn danger" data-act="reset">{ICON["trash"]}{esc(S["reset"])}</button></div>'
          f'<p class="my-note">{esc(S["store_note"])}</p></div></div>'
          f'<button type="button" class="totop" id="totop" aria-label="{esc(S["to_top"])}" title="{esc(S["to_top"])}" hidden>'
          f'<svg class="ring" viewBox="0 0 48 48" aria-hidden="true"><circle class="trk" cx="24" cy="24" r="21"/><circle class="val" cx="24" cy="24" r="21" pathLength="100"/></svg>{ICON["up"]}</button>'
          f'<p class="vh" id="live" role="status" aria-live="polite"></p>'
          + (f'<button type="button" class="ask-fab" id="ask-fab" aria-haspopup="dialog" title="{esc(S["ask_title"])}" hidden>'
             f'{ICON["spark"]}<span>{esc(S["ask_btn"])}</span></button>' if CFG['ask'] else ''))


def sidebar(cur):
    out = [f'<nav class="sidebar" id="sidebar" aria-label="{esc(S["navigation"])}"><div class="sb-head"><a class="sb-home" href="index.html">{esc(BOOK)}</a>'
           f'<button type="button" class="icon-btn sb-close" data-close-menu aria-label="{esc(S["close_menu"])}">{ICON["close"]}</button></div><div class="sb-scroll">']
    homecur = ' aria-current="page"' if cur is None else ''
    acur = lambda k: ' aria-current="page"' if getattr(cur, 'slug', None) == k else ''  # noqa: E731
    out.append(f'<ul class="sb-list"><li><a class="sb-link" href="index.html"{homecur}>{esc(S["home"])}</a></li>'
               f'<li><a class="sb-link app" href="contents.html"{acur("contents")}>{ICON["list"]}<span>{esc(S["contents"])}</span></a></li>'
               f'<li><a class="sb-link app" href="progress.html"{acur("progress")}>{ICON["trophy"]}<span>{esc(GM["s"]["my_progress"])}</span></a></li>'
               f'<li><a class="sb-link app" href="review.html"{acur("review")}>{ICON["cards"]}<span>{esc(GM["s"]["review_today"])}</span><span class="sb-due" data-due hidden></span></a></li>'
               f'<li><a class="sb-link app" href="lab.html"{acur("lab")}>{ICON["flask"]}<span>{esc(SIMY["lab_title"])}</span></a></li></ul>')
    for g, label in GROUPS:
        out.append(f'<div class="sb-group">{esc(label)}</div><ul class="sb-list">')
        for p in pages:
            if p.group != g:
                continue
            if p.kind == 'chapter' and p.chap in SB_PART_LABEL:
                out.append(f'<li class="sb-part">{esc(SB_PART_LABEL[p.chap])}</li>')
            is_cur = p is cur
            curattr = ' aria-current="page"' if is_cur else ''
            cls = 'sb-link' + (' part' if p.kind == 'part' else '')
            trk = f' data-slug="{p.slug}"' if p.slug in TRACK else ''
            kids = [s for s in p.sections if s[0] == 2]
            if kids and p.kind in ('chapter', 'appendix'):
                sid = f'sb-{p.slug}'
                exp = 'true' if is_cur else 'false'
                sub = ''.join(f'<li><a class="sb-sub" href="{p.slug}.html#{nid}" data-sec="{nid}">{t}</a></li>' for _, nid, t in kids)
                out.append(f'<li class="has-kids{" open" if is_cur else ""}"><div class="sb-row"><a class="{cls}" href="{p.slug}.html"{curattr}{trk}>{p.nav_html}</a>'
                           f'<button type="button" class="sb-tog" aria-expanded="{exp}" aria-controls="{sid}" aria-label="{esc(p.nav_text)}">{ICON["chev"]}</button></div>'
                           f'<ul class="sb-kids" id="{sid}"{"" if is_cur else " hidden"}>{sub}</ul></li>')
            else:
                out.append(f'<li><a class="{cls}" href="{p.slug}.html"{curattr}{trk}>{p.nav_html}</a></li>')
        out.append('</ul>')
    out.append('</div></nav>')
    return ''.join(out)


def header(cur):
    other = f'../{OTHER}/{cur.slug if cur else "index"}.html'
    return (f'<header class="topbar"><div class="tb-start">'
            f'<button type="button" class="icon-btn" id="menu-btn" aria-controls="sidebar" aria-expanded="false" aria-label="{esc(S["toggle_sidebar"])}">{ICON["menu"]}</button>'
            f'<a class="brand" href="index.html"><span class="logo" aria-hidden="true"></span>{esc(BOOK)}</a></div><div class="tb-end">'
            f'<button type="button" class="search-btn" id="search-btn" aria-haspopup="dialog" aria-label="{esc(S["search"])}">{ICON["search"]}<span class="sb-txt">{esc(S["search_placeholder"])}</span><kbd>/</kbd></button>'
            f'<a class="icon-btn toc-btn" href="contents.html" aria-label="{esc(S["contents"])}" title="{esc(S["contents"])}">{ICON["list"]}</a>'
            f'<a class="icon-btn lang-btn" href="{other}" hreflang="{OTHER}" lang="{OTHER}" title="{esc(SO["lang_name"])}">{ICON["globe"]}<span>{esc(SO["lang_name"])}</span></a>'
            f'<a class="g-chip game" id="g-chip" href="progress.html" aria-label="{esc(GM["s"]["my_progress"])}" hidden>{ICON["flame"]}<span class="g-s"></span><span class="g-l"></span></a>'
            f'<button type="button" class="icon-btn mk-btn" id="my-btn" aria-haspopup="dialog" aria-controls="my-dlg" aria-label="{esc(S["my_reading"])}" title="{esc(S["my_reading"])}">{ICON["bookmark"]}<span class="mk-n" aria-hidden="true"></span></button>'
            f'<button type="button" class="icon-btn" id="theme-btn" aria-label="{esc(S["theme"])}" aria-pressed="false">{ICON["sun"]}{ICON["moon"]}</button>'
            f'<a class="tb-cta" href="index.html#get-started">{ICON["spark"]}<span>{esc(S["get_started"])}</span></a>'
            f'</div><div class="rbar" aria-hidden="true"><i></i></div></header>')


def crumbs(cur):
    if cur is None:
        return ''
    if isinstance(cur, AppPage):
        return (f'<nav class="crumbs" aria-label="{esc(S["breadcrumb"])}"><ol><li><a href="index.html">{esc(S["home"])}</a></li>'
                f'<li><a href="{cur.slug}.html" aria-current="page">{esc(cur.title_text)}</a></li></ol></nav>')
    glabel = dict(GROUPS)[cur.group]
    return (f'<nav class="crumbs" aria-label="{esc(S["breadcrumb"])}"><ol><li><a href="index.html">{esc(S["home"])}</a></li>'
            f'<li><span>{esc(glabel)}</span></li><li><a href="{cur.slug}.html" aria-current="page">{esc(cur.crumb)}</a></li></ol></nav>')


def pager(cur):
    if isinstance(cur, AppPage):
        return ''
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
                                           'zoom_in', 'zoom_out', 'zoom_reset', 'close', 'copied', 'copy', 'zoom',
                                           'fb_thanks', 'fb_issue', 'fb_issue_title', 'fb_issue_body') + PROG_KEYS}
                       | {'lang': LANG, 'rtl': RTL, 'pages': TRACK,
                          'fb': {'repo': CFG['repo'], 'endpoint': CFG['feedback'], 'issues': CFG['feedback_issues']}}
                       | ({'ask': {'endpoint': CFG['ask'] + '/v1/ask', 'js': '../assets/ask.js',
                                   's': {k[4:]: S[k] for k in S if k.startswith('ask_')} | {'close': S['close']}}}
                          if CFG['ask'] else {}), ensure_ascii=False)


EMITTED, DESC_SEEN = [], set()
OG_ALT = f'{BOOK} — {META.get("author", "")}'


def page_desc(cur, title_text):
    body = getattr(cur, 'body', None)
    d = seo.describe(seo.first_paragraph(body)) if body is not None else ''
    if not d:
        d = seo.describe(f'{title_text} — {META.get("subtitle", "")}')
    if len(d) < 70:
        d = seo.describe(f'{d} — {title_text} · {BOOK}' if title_text not in d else f'{d} — {BOOK}: {META.get("subtitle", "")}')
    if d in DESC_SEEN:
        d = seo.describe(f'{title_text}: {d}')
    return d


def page_ld(cur, title_text):
    home = (S['home'], 'index')
    if isinstance(cur, AppPage):
        if cur.slug.startswith('lab-'):
            trail = [home, (SIMY['lab_title'], 'lab'), (cur.title_text, cur.slug)]
        else:
            trail = [home, (cur.title_text, cur.slug)]
        return seo.crumbs_ld(U, LANG, trail)
    extra = None
    if cur.kind in ('chapter', 'appendix'):
        extra = {'@type': 'Chapter', 'name': cur.title_text, 'inLanguage': LANG,
                 'url': U.rel(f'{LANG}/{cur.slug}.html'), 'author': {'@type': 'Person', 'name': seo.AUTHOR},
                 'license': seo.LICENSE_URL, 'description': page_desc(cur, title_text),
                 'image': page_og_url(cur.slug),
                 'isPartOf': {'@type': 'Book', '@id': U.rel(f'{LANG}/index.html') + '#book', 'name': BOOK}}
        if cur.kind == 'chapter':
            extra['position'] = cur.chap
    return seo.crumbs_ld(U, LANG, [home, (S['contents'], 'contents'), (cur.crumb, cur.slug)], extra)



def page_og_path(slug):
    return os.path.join(ASSETS, 'og', LANG, f'{slug}.png')


def page_og_url(slug):
    rel = f'assets/og/{LANG}/{slug}.png'
    return U.abs(rel) if U.base else U.rel(rel)


def write_page_og(slug, title_text):
    dst = page_og_path(slug)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    seo.og_image(cover_src, dst, LANG, title_text, BOOK, META.get('author', ''))
    return page_og_url(slug)


def emit(cur, main_html, title_text, desc=None, ld=None, og_img=None):
    side, inline = page_toc(cur)
    i = order.index(cur) if not isinstance(cur, AppPage) else -1
    links = []
    if i > 0:
        links.append(f'<link rel="prev" href="{order[i - 1].slug if order[i - 1] else "index"}.html">')
    if 0 <= i and i + 1 < len(order):
        links.append(f'<link rel="next" href="{order[i + 1].slug}.html">')
    slug = cur.slug if cur else 'index'
    has_sims = bool(getattr(cur, 'sims', None))
    head_extra = '<link rel="stylesheet" href="../assets/sims.css">' if has_sims or cur is None or slug == 'lab' else ''
    if 'class="katex"' in main_html:
        head_extra += '<link rel="stylesheet" href="../assets/katex/katex.min.css">'
    scripts_extra = '<script src="sim-data.js" defer></script>\n<script src="../assets/sims.js" defer></script>' if has_sims else ''
    for _n in dict.fromkeys(n for n in (getattr(cur, 'sims', None) or []) if n in SIM_LAZY):
        scripts_extra += f'\n<script src="sim-data-{_n}.js" defer></script>\n<script src="../assets/lab-{_n}.js" defer></script>'
    if cur is None:
        head_extra += f'<link rel="alternate" type="application/atom+xml" title="{esc(S["nl_feed"])}" href="../releases.xml">'
    if ANALYTICS_TAG:
        scripts_extra += '\n' + ANALYTICS_TAG
    desc = desc or page_desc(cur, title_text)
    DESC_SEEN.add(desc)
    og_type = 'book' if cur is None else ('article' if getattr(cur, 'kind', '') in ('chapter', 'appendix') else 'website')
    if og_img is None and cur is not None and getattr(cur, 'kind', '') in ('chapter', 'appendix'):
        og_img = write_page_og(slug, title_text)
        og_alt = f'{title_text} — {BOOK}'
    else:
        og_alt = OG_ALT
    seo_head = seo.head(U, LANG, OTHER, slug, title_text, desc, og_type, og_alt, BOOK, ld or page_ld(cur, title_text),
                        font_href='../assets/fonts/' + seo.PRELOAD_FONT[LANG], og_img=og_img)
    doc = PAGE_TPL.substitute(head_extra=head_extra, scripts_extra=scripts_extra, seo=seo_head,
        lang=LANG, dir=DIR, other=OTHER, slug=slug, title=esc(title_text), book=esc(BOOK),
        links='\n'.join(links), site_data=SITE_DATA.replace('</', '<\\/'),
        skip=esc(S['skip']), header=header(cur), sidebar=sidebar(cur), crumbs=crumbs(cur),
        toc_inline=inline, main=main_html, pager=pager(cur), toc=side,
        has_toc='has-toc' if side else 'no-toc', kind=cur.kind if cur else 'home', extras=EXTRAS,
        search_title=esc(S['search']), search_placeholder=esc(S['search_placeholder']), close=esc(S['close']),
        search_hint=esc(S['search_hint']), lic=esc('© 2026 Ramin Najarbashi · CC BY-NC-SA 4.0'), privacy=PRIVACY, version=esc(META['version_display']),
        date=esc(META['date_display']))
    open(os.path.join(LOUT, f'{slug}.html'), 'w', encoding='utf-8').write(seo.fingerprint(doc, ASSETS))
    EMITTED.append(slug)


# ---------------------------------------------------------------- hyphenation
# No soft hyphens are inserted: they ended up in copied text ("cal\u00adcu\u00adla\u00adtion").
# The English pages rely on CSS `hyphens: auto` with lang="en" (site.css).
HYPH = None

# ---------------------------------------------------------------- write pages
docs = []
PRIVACY = esc(S['privacy_analytics'].format(svc=siteconf.analytics_name(CFG)) if CFG['analytics'] else S['privacy_none'])
if CFG['ask']:
    PRIVACY += ' ' + esc(S['privacy_ask'])


def edit_url(path):
    return f'{CFG["repo"]}/edit/{CFG["branch"]}/{os.path.relpath(path, ROOT).replace(os.sep, "/")}'


FB_SKIP = (UI['review_questions'], UI['chapter_sources'])


def add_feedback(p):
    """A small "Was this section helpful?" row at the end of every h2 section of a chapter.

    Votes go through bookEvent() in site.js: FEEDBACK_ENDPOINT (if set), any analytics
    with custom events, and a 'book:event' DOM event; a "No" also offers a prefilled
    GitHub issue naming the section anchor. Hidden until site.js runs.
    """
    hs = [h for h in p.body.find_all('h2') if h.get('id')]
    for k, h in enumerate(hs):
        title = text_of(frag(heading_inner(h)))
        if title.startswith(FB_SKIP):
            continue
        row = frag(f'<div class="fb" data-sec="{esc(h["id"])}" data-sec-t="{esc(title)}" hidden><span class="fb-q">{esc(S["fb_q"])}</span>'
                   f'<button type="button" class="fb-b" data-v="yes">👍 {esc(S["fb_yes"])}</button>'
                   f'<button type="button" class="fb-b" data-v="no">👎 {esc(S["fb_no"])}</button>'
                   f'<span class="fb-t" role="status" aria-live="polite"></span></div>')
        if k + 1 < len(hs):
            hs[k + 1].insert_before(row)
        else:
            p.body.append(row)


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
        if el.find_parent(class_='katex-html') or el.find_parent('annotation'):
            continue  # math: index the MathML text once, not the glyph layout or the TeX source
        if el.find_parent(['h2', 'h3']) or el.find_parent(class_='fb') or el.find_parent(class_='hanchor') or el.find_parent(class_='code-head') or el.find_parent(class_='sim-slot') or el.find_parent(class_='lab-thumb'):
            continue
        state['buf'].append(str(el).replace('\u200f', ''))
    flush()


for p in pages:
    if p.kind not in ('list',):
        index_docs(p)
    if p.kind == 'chapter':
        add_feedback(p)
    meta = ''
    if p.slug in TRACK:
        edit = ''
        if p.kind == 'chapter' and p.chap in CHFILES:
            edit = (f'<a class="edit-link" href="{esc(edit_url(CHFILES[p.chap]))}" title="{esc(S["edit_page_t"])}" rel="noopener">'
                    f'<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 20h9M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/></svg>'
                    f'<span>{esc(S["edit_page"])}</span></a>')
        meta = (f'<div class="ph-meta"><span class="rt">{ICON["clock"]}{esc(fmt_min(p.minutes))}</span>'
                f'<button type="button" class="read-tog" id="read-tog" aria-pressed="false" hidden>{ICON["check"]}<span>{esc(S["mark_read"])}</span></button>{edit}</div>')
    if HYPH:
        HYPH(p.body)
    eyebrow = f'<div class="eyebrow">{esc(p.eyebrow)}</div>' if p.eyebrow else ''
    extra = ''
    if p.kind == 'part':
        lo, hi = PART_RANGE.get(p.slug, (23, 10 ** 6))
        lis = ''.join(f'<li><a href="{q.slug}.html">{q.nav_html}</a></li>' for q in pages if q.chap and lo <= q.chap < hi)
        extra = f'<ol class="part-list">{lis}</ol>'
    if p.kind == 'chapter' and CARDS_BY_CH.get(p.chap):
        extra += (f'<aside class="quiz-cta" aria-labelledby="qz-{p.chap}"><span class="hc-ic">{ICON["cards"]}</span><div><h2 id="qz-{p.chap}" class="qz-h">{esc(GM["s"]["ch_quiz"])}</h2>'
                  f'<p>{esc(GM["s"]["ch_quiz_sub"].format(n=loc(CARDS_BY_CH[p.chap])))}</p></div>'
                  f'<a class="btn primary" href="review.html?ch={p.chap}">{esc(GM["s"]["rv_start"])} {ICON["arrow"]}</a></aside>')
    main = f'<article class="content" id="top"><header class="page-head">{eyebrow}<h1>{p.title_html}</h1>{meta}</header>{"".join(str(c) for c in p.body.contents)}{extra}</article>'
    tt = (f'{p.eyebrow}: ' if p.kind in ('chapter', 'appendix') else '') + p.title_text
    tt = tt if len(tt) + len(BOOK) > 67 else f'{tt} · {BOOK}'   # keep titles short; long chapter titles stand alone
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
        trk = f' data-slug="{p.slug}"' if p.slug in TRACK else ''
        rt = f'<span class="rt-s">{ICON["clock"]}{esc(fmt_min(p.minutes, True))}</span>' if p.slug in TRACK else ''
        lis.append(f'<li{cls}><a href="{p.slug}.html"{trk}><span class="ct">{p.nav_html}</span>{secs}{rt}</a></li>')
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


def home_picture(rel, alt, cls='learn-img'):
    """Committed figure under figures/, preferring a LANG-specific .en.png."""
    base = os.path.join(ROOT, 'figures')
    pth = os.path.join(base, rel)
    if LANG == 'en':
        en = os.path.join(base, rel[:-4] + '.en.png')
        if os.path.exists(en):
            pth = en
    if not os.path.exists(pth):
        return ''
    src = copy_figure(pth)
    hi, ext, alts = hires(pth)
    if ext != '.svg':
        src_for_avif = pth
        if alts.get('.webp'):
            src_for_avif = os.path.join(FIGDIR, alts['.webp'].split('figures/', 1)[-1])
        avif_dst = os.path.splitext(os.path.join(FIGDIR, os.path.relpath(pth, os.path.join(ROOT, 'figures'))))[0] + '.avif'
        if maybe_avif(src_for_avif if os.path.exists(src_for_avif) else pth, avif_dst, png=pth):
            alts['.avif'] = '../figures/' + os.path.relpath(avif_dst, FIGDIR).replace(os.sep, '/')
    w, h = Image.open(pth).size
    sources = []
    if alts.get('.avif'):
        sources.append(f'<source type="image/avif" srcset="{alts[".avif"]}">')
    if alts.get('.webp'):
        sources.append(f'<source type="image/webp" srcset="{alts[".webp"]}">')
    img = f'<img class="{cls}" src="{src}" width="{w}" height="{h}" loading="lazy" alt="{esc(alt)}">'
    return ('<picture>' + ''.join(sources) + img + '</picture>') if sources else img


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
    chips = ''.join(f'<a class="chip" href="{ch_href(n)}" data-slug="{CH[n].slug}" title="{esc(text_of(frag(CH[n].title_html)))}" aria-label="{esc(UI["chapter_word"])} {loc(n)}: {esc(text_of(frag(CH[n].title_html)))}">{loc(n)}</a>' for n in range(lo, hi + 1) if n in CH)
    badge = f'<span class="hc-new">{esc(S["new"])}</span>' if new_ else ''
    part_cards.append(f'<div class="pcard p{i}"><div class="pc-top"><span class="hc-ic">{ICON[icon]}</span><span class="hc-tag">{esc(word)} · {esc(rng)}</span>{badge}'
                      f'<span class="pc-prog" data-lo="{lo}" data-hi="{hi}" hidden>{ring()}<span class="pc-pt"></span></span></div>'
                      f'<h3><a href="{href}">{esc(title)}</a></h3><p>{esc(desc)}</p>'
                      f'<p class="pc-time">{ICON["clock"]}{esc(fmt_min(sum(CH[n].minutes for n in range(lo, hi + 1) if n in CH), True))}</p><div class="chips">{chips}</div></div>')
CONCEPT_DOI, VERSION_DOI = '10.5281/zenodo.24253822', '10.5281/zenodo.24253823'
nparts = len(PARTS_HOME)
stats = ('<div class="stats" role="list">' + ''.join(
    f'<div role="listitem"><b data-n="{n}">{loc(n)}</b><span>{esc(S[k])}</span></div>'
    for n, k in ((len(CH), 'stat_ch'), (N_FIG, 'stat_fig'), (N_ALGO, 'stat_algo'), (nparts, 'stat_parts'))) + '</div>')
VERSIONS = ('Reef', 'Squid', 'Tentacle', 'Umbrella')
versions = (f'<p class="versions"><span class="ver-label">{esc(S["versions_label"])}</span>'
            f'<span class="ver-list" dir="ltr">' +
            ''.join(f'<span class="vpill">{v}</span>' for v in VERSIONS) + '</span></p>')
ver_tag = str(META['version'])
rel_base = f"{CFG['repo']}/releases/download/v{ver_tag}/ceph-scalable-storage-{LANG}"
pdf_url, epub_url = rel_base + '.pdf', rel_base + '.epub'
LEARN_FIGS = (
    (1, 'ch01/f01_stack.png', 1),
    (2, 'ch08/f02_hier.png', 8),
    (3, 'ch12/f01_stack.png', 12),
    (4, 'ch34/f01_oppath.png', 34),
)
learn_cards = []
for k, rel, chap_n in LEARN_FIGS:
    href = ch_href(chap_n)
    pic = home_picture(rel, S[f'learn{k}_alt'])
    tag = f'{esc(UI["chapter_word"])} {loc(chap_n)}'
    learn_cards.append(
        f'<a class="lcard l{k}" href="{href}"><span class="lfig">{pic}</span>'
        f'<span class="hc-tag">{tag}</span><span class="hc-t">{esc(S[f"learn{k}_t"])}</span>'
        f'<span class="hc-d">{esc(S[f"learn{k}_d"])}</span>'
        f'<span class="hc-go">{esc(S["gs_go"])} {ICON["arrow"]}</span></a>')
learn = (f'<section class="hsec" id="learn" aria-labelledby="learn-h"><div class="hsec-head">'
         f'<h2 id="learn-h">{esc(S["learn_title"])}</h2><p>{esc(S["learn_sub"])}</p></div>'
         f'<div class="hgrid learn">{"".join(learn_cards)}</div></section>')
cite = (f'<section class="hsec cite" id="cite" aria-labelledby="cite-h"><div class="hsec-head">'
        f'<h2 id="cite-h">{esc(S["cite_title"])}</h2><p>{esc(S["cite_sub"])}</p></div>'
        f'<div class="cite-grid">'
        f'<a class="cite-card" href="https://doi.org/{CONCEPT_DOI}" rel="noopener">'
        f'<span class="cite-k">{esc(S["cite_concept"])}</span>'
        f'<span class="cite-v en" lang="en" dir="ltr">{esc(CONCEPT_DOI)}</span></a>'
        f'<a class="cite-card" href="https://doi.org/{VERSION_DOI}" rel="noopener">'
        f'<span class="cite-k">{esc(S["cite_version"].format(v=loc(META["version_display"])))}</span>'
        f'<span class="cite-v en" lang="en" dir="ltr">{esc(VERSION_DOI)}</span></a>'
        f'<a class="cite-card" href="https://creativecommons.org/licenses/by-nc-sa/4.0/" rel="noopener">'
        f'<span class="cite-k">{esc(S["cite_license"])}</span>'
        f'<span class="cite-v en" lang="en" dir="ltr">CC BY-NC-SA 4.0</span></a></div></section>')
feedback = (f'<section class="hsec feedback" id="feedback" aria-labelledby="fb-h"><div class="hsec-head">'
            f'<h2 id="fb-h">{esc(S["fb_title"])}</h2><p>{esc(S["fb_lead"])}</p></div>'
            f'<p class="fb-acts"><a class="btn" href="{esc(CFG["repo"])}/issues/new" rel="noopener">{ICON["github"]}{esc(S["fb_issue"])}</a></p></section>')
rp = (f'<div class="rp" id="rp" hidden><div class="ring-wrap">{ring("big")}<b class="rp-pct"></b></div><div class="rp-body"><div class="rp-t">{esc(S["progress_title"])}</div>'
      f'<p class="rp-line"></p><div class="rp-acts"><a class="btn primary rp-cont" href="{first.slug}.html" hidden>{ICON["book"]}<span class="rp-ct">{esc(S["continue"])}</span> {ICON["arrow"]}</a>'
      f'<button type="button" class="btn" data-open-my>{ICON["bookmark"]}{esc(S["my_reading"])}</button></div>'
      f'<a class="rp-game game" href="progress.html" aria-label="{esc(GM["s"]["my_progress"])}" hidden></a></div></div>')
term = ('<div class="term" dir="ltr" aria-hidden="true"><div class="term-bar"><i></i><i></i><i></i><span>' + esc(S['term_label']) + '</span></div>'
        '<pre><span class="tp">$</span> ceph -s\n  cluster:\n    health: <span class="tok">HEALTH_OK</span>\n  services:\n    mon: 3 daemons, quorum a,b,c\n'
        '    osd: 36 osds: 36 up, 36 in\n    rgw: 3 daemons active\n  data:\n    pgs: <span class="tok">1024 active+clean</span></pre></div>')
LAB_CARDS = ''.join(lab_card(n) for n in SIM_HOME if n in SIM_NAMES)
if CFG['newsletter']:
    nl_body = (f'<form class="nl-form" action="{esc(CFG["newsletter"])}" method="post" target="_blank">'
               f'<input type="hidden" name="lang" value="{esc(LANG)}">'
               f'<label class="sr-only" for="nl-website">Leave this field empty</label>'
               f'<input type="text" id="nl-website" name="website" value="" class="sr-only" tabindex="-1" autocomplete="off" aria-hidden="true">'
               f'<label class="sr-only" for="nl-email">{esc(S["nl_email"])}</label>'
               f'<input type="email" id="nl-email" name="email" required autocomplete="email" placeholder="{esc(S["nl_email"])}" dir="ltr">'
               f'<button type="submit" class="btn primary">{esc(S["nl_submit"])}</button></form>'
               f'<p class="nl-alt"><a href="{esc(CFG["repo"])}/releases" rel="noopener" title="{esc(S["nl_watch_t"])}">{esc(S["nl_watch"])}</a> · '
               f'<a href="../releases.xml" type="application/atom+xml">{esc(S["nl_feed"])}</a></p>'
               f'<p class="nl-privacy">{esc(S["nl_privacy_form"])} {PRIVACY}</p>')
else:
    nl_body = (f'<p class="nl-acts"><a class="btn primary nl-watch" href="{esc(CFG["repo"])}/releases" rel="noopener">{ICON["arrow"]}{esc(S["nl_watch"])}</a>'
               f'<a class="btn nl-feed" href="../releases.xml" type="application/atom+xml">'
               f'<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path fill="currentColor" d="M6.2 15.6a2.2 2.2 0 1 1 0 4.4 2.2 2.2 0 0 1 0-4.4zM4 9.5a10.5 10.5 0 0 1 10.5 10.5h-3A7.5 7.5 0 0 0 4 12.5v-3zm0-5.5A16 16 0 0 1 20 20h-3A13 13 0 0 0 4 7V4z"/></svg>'
               f'{esc(S["nl_feed"])}</a></p><p class="nl-hint">{esc(S["nl_watch_t"])}</p>'
               f'<p class="nl-privacy">{esc(S["nl_privacy_none"])} {PRIVACY}</p>')
newsletter = (f'<section class="hsec newsletter" id="newsletter" aria-labelledby="nl-h"><div class="hsec-head"><h2 id="nl-h">{esc(S["nl_title"])}</h2>'
              f'<p>{esc(S["nl_sub"])}</p></div>{nl_body}</section>')
home = f'''<article class="content home" id="top">
<section class="hero"><div class="hero-text">
<div class="hbadge"><span class="pulse" aria-hidden="true"></span>{esc(S["badge"].format(v=loc(META["version_display"])))}</div>
<div class="eyebrow">{esc(S["study_guide"])}</div><h1>{esc(BOOK).replace("Ceph", '<span class="grad">Ceph</span>')}</h1>
<p class="subtitle">{esc(META.get("subtitle", ""))}</p><p class="lead">{esc(S["hero_lead"])}</p>
<p class="cta">
<a class="btn primary" href="{first.slug}.html">{ICON["book"]}{esc(S["cta_read"])} {ICON["arrow"]}</a>
<a class="btn" href="{esc(pdf_url)}" rel="noopener">{ICON["download"]}{esc(S["cta_pdf"])}</a>
<a class="btn" href="{esc(epub_url)}" rel="noopener">{ICON["download"]}{esc(S["cta_epub"])}</a>
<a class="btn ghost" href="{esc(CFG["repo"])}" rel="noopener">{ICON["github"]}{esc(S["cta_github"])}</a>
</p>
<p class="cta-more"><a href="#get-started">{esc(S["get_started"])}</a>
<span aria-hidden="true">·</span>
<a href="../{OTHER}/index.html" hreflang="{OTHER}" lang="{OTHER}">{esc(S["read_in_other"])}</a></p>
{stats}{versions}
{rp}
<p class="byline">{esc(S["written_by"])}</p><p class="meta">{esc(S["version"])} {esc(loc(META["version_display"]))} · {esc(META["date_display"])}<br>{esc(S["basis"])}: <span dir="auto">{esc(META["technical_basis"])}</span></p></div>
<div class="hero-art"><div class="glow" aria-hidden="true"></div><img class="cover" src="../assets/cover.{LANG}.webp" width="{COVER_WH[0]}" height="{COVER_WH[1]}" fetchpriority="high" alt="{esc(S['cover_alt'].format(book=BOOK))}">{term}</div></section>
{learn}
<section class="hsec" id="get-started" aria-labelledby="gs-h"><div class="hsec-head"><h2 id="gs-h">{esc(S["gs_title"])}</h2><p>{esc(S["gs_sub"])}</p></div><div class="hgrid roles">{"".join(gs_cards)}</div></section>
<section class="hsec" id="lab" aria-labelledby="lab-h"><div class="hsec-head"><h2 id="lab-h">{esc(SIMY["lab_title"])}</h2><p>{esc(SIMY["lab_intro"])}</p></div><div class="lab-grid">{LAB_CARDS}</div><p><a class="btn" href="lab.html">{ICON["flask"]}{esc(SIMY["lab_all"].replace("{n}", str(loc(len(SIM_NAMES)))))} {ICON["arrow"]}</a></p></section>
<section class="hsec" id="parts" aria-labelledby="parts-h"><div class="hsec-head"><h2 id="parts-h">{esc(S["parts_title"])}</h2><p>{esc(S["parts_sub"])}</p></div><div class="hgrid parts">{"".join(part_cards)}</div></section>
<section class="hsec" id="contents" aria-labelledby="contents-h"><div class="hsec-head"><h2 id="contents-h">{esc(S["contents"])}</h2><p>{esc(S["contents_home"])}</p></div><p><a class="btn primary" href="contents.html">{ICON["list"]}{esc(S["contents_cta"])} {ICON["arrow"]}</a></p></section>
{cite}
<div class="cta-band">{newsletter}{feedback}</div>
<section class="about" aria-labelledby="about-h"><h2 id="about-h">{esc(S["about"])}</h2>{about}</section></article>'''
HOME_DESC = seo.describe(f'{META.get("subtitle", "")}. {S["hero_lead"]}')
HOME_LD = seo.book_ld(U, LANG, OTHER, BOOK, yaml.safe_load(open(os.path.join(ROOT, 'content', OTHER, 'ui.yaml'), encoding='utf-8'))['book'],
                      HOME_DESC, str(META['version']), str(META['date']),
                      [(n, CH[n].title_text, CH[n].slug) for n in sorted(CH)], U.rel(f'assets/og.{LANG}.png'),
                      doi=CONCEPT_DOI, version_doi=VERSION_DOI)
emit(None, home, f'{BOOK} — {S["study_guide"]} · {META.get("author", "")}', HOME_DESC, HOME_LD)
CONTENTS = AppPage('contents', S['contents'])
emit(CONTENTS, f'<article class="content toc-page" id="top"><header class="page-head"><h1>{esc(S["contents"])}</h1></header>'
               f'<p class="lead">{esc(S["contents_intro"])}</p>{"".join(grp)}</article>', f'{S["contents"]} · {BOOK}',
     seo.describe(f'{S["contents"]} — {BOOK}: {S["contents_intro"]}'))

# gamification: app pages and data ---------------------------------------------
GS = GM['s']
NOSCRIPT = f'<noscript><p class="call note">{esc(GS["noscript"])}</p></noscript>'
for _slug, _ap in APP_PAGES.items():
    _main = (f'<article class="content app app-{_slug}" id="top"><header class="page-head"><h1>{esc(_ap.title_text)}</h1></header>{NOSCRIPT}'
             f'<div id="gm-{_slug}" class="gm-root" aria-busy="true"><p class="gm-loading">{esc(GS["loading"])}</p></div></article>')
    emit(_ap, _main, f'{_ap.title_text} · {BOOK}')
# the interactive lab: an index page and one full page per simulator ---------------
# an edition whose chapters are still pending has no slots; its lab pages then point at the chapters from the source
for _n, _l in [(n, l) for n in SIM_WHERE if not SIM_WHERE[n] for l in [None]]:
    for _ch, _f in sorted(CHFILES.items()):
        if f'.sim name="{_n}"' in open(_f, encoding='utf-8').read() and _ch in CH:
            SIM_WHERE[_n].append((CH[_ch], '', CH[_ch].title_text))


def lab_where(name):
    return SIMY['lab_in'] + ' ' + UI['list_sep'].join(f'<a href="{pg.slug}.html' + (f'#{sid}' if sid else '') + f'">{esc(pg.nav_text if not pg.chap else f"{UI["chapter_word"]} {loc(pg.chap)}")}</a>'
                                                      for pg, sid, _ in SIM_WHERE[name])


LAB = AppPage('lab', SIMY['lab_title'])
_cards = ''.join(lab_card(n, f'<small>{esc(SIMY["lab_in"])} {esc(UI["list_sep"].join((f"{UI["chapter_word"]} {loc(pg.chap)}" if pg.chap else pg.nav_text) for pg, _, _ in SIM_WHERE[n]))}</small>')
                 for n in SIM_NAMES)
emit(LAB, f'<article class="content app app-lab" id="top"><header class="page-head"><h1>{esc(LAB.title_text)}</h1></header>'
          f'<p class="lead">{esc(SIMY["lab_intro"])}</p><div class="lab-grid">{_cards}</div></article>', f'{LAB.title_text} · {BOOK}',
     seo.describe(SIMY['lab_intro']))
for n in SIM_NAMES:
    _ap = AppPage(f'lab-{n}', SIMY[n + '_t'])
    _ap.sims = [n]
    _ap.crumb = _ap.title_text
    emit(_ap, f'<article class="content app app-sim" id="top"><header class="page-head"><div class="eyebrow"><a href="lab.html">{esc(SIMY["lab_title"])}</a></div>'
              f'<h1>{esc(_ap.title_text)}</h1></header><p class="lab-in">{lab_where(n)}</p>{sim_slot_html(n)}'
              f'<noscript><p class="call note">{esc(SIMY["noscript"])}</p></noscript></article>', f'{_ap.title_text} · {SIMY["lab_title"]} · {BOOK}',
         seo.describe(f'{_ap.title_text}: {SIMY[n + "_d"]}'))
PATHS = [(1, [1, 2, 4, 6, 7, 8]), (2, [1, 11, 12, 13, 20]), (3, [7, 19, 20, 17, 18, 21]), (4, [17, 8, 32, 18, 20]),
         (5, [22, 14, 15, 23, 26]), (6, list(range(34, 43)))]
PARTS_G = {1: range(1, 22), 2: range(22, 23), 3: range(23, 34), 4: range(34, 43)}
game_data = {
    'lang': LANG, 'other': OTHER, 'book': BOOK, 's': GS, 'levels': GM['levels'], 'badges': GM['badges'],
    'paths': [{'k': k, 't': S[f'role{k}_t'], 'd': S[f'role{k}_d'], 'ch': [CH[n].slug for n in chs if n in CH]} for k, chs in PATHS],
    'parts': {str(k): [CH[n].slug for n in r if n in CH] for k, r in PARTS_G.items()},
    'chs': {CH[n].slug: n for n in CH}, 'chTitle': {str(n): TRACK[CH[n].slug][0] for n in CH},
    'nAlgo': N_ALGO, 'nFig': N_FIG, 'gids': [g[0] for g in GLOSS], 'cardsByCh': {str(k): v for k, v in CARDS_BY_CH.items()},
    'weekStart': 6 if LANG == 'fa' else 1, 'rest': [5] if LANG == 'fa' else [6, 0], 'wpm': WPM,
}
open(os.path.join(LOUT, 'game-data.js'), 'w', encoding='utf-8').write(
    'window.__GAME__=' + json.dumps(game_data, ensure_ascii=False, separators=(',', ':')) + ';\n')
open(os.path.join(LOUT, 'learn-data.js'), 'w', encoding='utf-8').write(
    'window.__LEARN__=' + json.dumps({'cards': CARDS, 'gloss': GLOSS}, ensure_ascii=False, separators=(',', ':')) + ';\n')
docs.insert(0, ['index.html', BOOK, '', text_of(frag(about))])
docs.insert(1, ['contents.html', S['contents'], '', S['contents_intro'] + ' ' + ' · '.join(p.nav_text for p in pages)])
open(os.path.join(LOUT, 'search-index.js'), 'w', encoding='utf-8').write(
    'window.__SEARCH_DOCS__=' + json.dumps(docs, ensure_ascii=False, separators=(',', ':')) + ';\n')

# language chooser ----------------------------------------------------------
STR_FA, STR_EN = STR['fa'], STR['en']
ui_other = yaml.safe_load(open(os.path.join(ROOT, 'content', OTHER, 'ui.yaml'), encoding='utf-8'))
books = {LANG: BOOK, OTHER: ui_other['book']}
CH_DESC = 'Choose an edition of the bilingual book on Ceph storage by Ramin Najarbashi: the original Persian text or the English translation. · ' + STR_FA['choose']
_alt = {l: (STR[l]['cover_alt'].format(book=books[l])) for l in ('fa', 'en')}
_cw = Image.open(os.path.join(ASSETS, f'cover.{LANG}.webp')).size
_ch = round(240 * _cw[1] / _cw[0])
_ld = {'@context': 'https://schema.org', '@type': 'WebSite', 'name': f'{books["en"]} · {books["fa"]}', 'url': U.root('index.html'),
       'inLanguage': ['fa', 'en'], 'author': {'@type': 'Person', 'name': seo.AUTHOR}, 'license': seo.LICENSE_URL}
chooser = f"""<!doctype html>
<html lang="en" dir="ltr" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(books["en"])} · {esc(books["fa"])}</title>
<meta name="description" content="{esc(seo.describe(CH_DESC))}">
{f'<link rel="canonical" href="{U.abs("index.html")}">' if U.base else ''}
<link rel="alternate" hreflang="fa" href="{U.root('fa/index.html')}"><link rel="alternate" hreflang="en" href="{U.root('en/index.html')}"><link rel="alternate" hreflang="x-default" href="{U.root('index.html')}">
<meta name="theme-color" content="{seo.THEME}"><link rel="icon" href="assets/icons/favicon.ico" sizes="48x48"><link rel="icon" href="assets/icons/icon.svg" type="image/svg+xml"><link rel="apple-touch-icon" href="assets/icons/apple-touch-icon.png"><link rel="manifest" href="manifest.webmanifest">
{seo.preload('assets/fonts/inter-var.woff2')}{seo.preload('assets/fonts/vazirmatn-400.woff2')}
<meta property="og:type" content="website"><meta property="og:site_name" content="{esc(books["en"])}"><meta property="og:title" content="{esc(books["en"])} · {esc(books["fa"])}"><meta property="og:description" content="{esc(seo.describe(CH_DESC))}">
<meta property="og:locale" content="en_US"><meta property="og:locale:alternate" content="fa_IR"><meta property="og:image" content="{U.root('assets/og.en.png')}"><meta property="og:image:width" content="{seo.OG_W}"><meta property="og:image:height" content="{seo.OG_H}"><meta property="og:image:alt" content="{esc(_alt['en'])}">{f'<meta property="og:url" content="{U.abs("index.html")}">' if U.base else ''}
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(books["en"])} · {esc(books["fa"])}"><meta name="twitter:description" content="{esc(seo.describe(CH_DESC))}"><meta name="twitter:image" content="{U.root('assets/og.en.png')}"><meta name="twitter:image:alt" content="{esc(_alt['en'])}">
<script type="application/ld+json">{json.dumps(_ld, ensure_ascii=False)}</script>
<link rel="stylesheet" href="assets/fonts.css"><link rel="stylesheet" href="assets/site.css">
<script>try{{var t=localStorage.getItem('book-theme')||(matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.dataset.theme=t}}catch(e){{}}</script></head>
<body class="chooser"><button type="button" class="icon-btn choose-theme" id="theme-btn" aria-label="{esc(STR_EN['choose_theme'])} · {esc(STR_FA['choose_theme'])}">{ICON['sun']}{ICON['moon']}</button>
<main>
<p class="choose-kicker" dir="ltr">Ceph · Reef · Squid · Tentacle · Umbrella</p>
<h1><span lang="fa" dir="rtl">{esc(STR_FA["choose"])}</span> · {esc(STR_EN["choose"])}</h1>
<p class="choose-lead"><span lang="fa" dir="rtl">{esc(STR_FA["choose_lead"])}</span> · <span lang="en">{esc(STR_EN["choose_lead"])}</span></p>
<div class="choose-stats" role="list">
<div role="listitem"><b dir="ltr">{len(CH)}</b><span lang="en">{esc(STR_EN["stat_ch"])}</span></div>
<div role="listitem"><b dir="ltr">{N_FIG}</b><span lang="en">{esc(STR_EN["stat_fig"])}</span></div>
<div role="listitem"><b dir="ltr">{N_ALGO}</b><span lang="en">{esc(STR_EN["stat_algo"])}</span></div>
<div role="listitem"><b dir="ltr">{nparts}</b><span lang="en">{esc(STR_EN["stat_parts"])}</span></div>
</div>
<div class="choose-grid">
<a class="choose-card" href="fa/index.html" lang="fa" dir="rtl"><img src="assets/cover.fa.webp" alt="{esc(_alt['fa'])}" width="240" height="{_ch}"><span>{esc(books["fa"])}</span><small>فارسی (متن اصلی)</small></a>
<a class="choose-card" href="en/index.html" lang="en"><img src="assets/cover.en.webp" alt="{esc(_alt['en'])}" width="240" height="{_ch}"><span>{esc(books["en"])}</span><small>English (translation)</small></a>
</div>
<p class="lic">© 2026 Ramin Najarbashi · <a href="https://creativecommons.org/licenses/by-nc-sa/4.0/" rel="noopener">CC BY-NC-SA 4.0</a><br>
<span class="en" lang="en" dir="ltr"><a href="https://doi.org/{CONCEPT_DOI}">{CONCEPT_DOI}</a></span></p>
</main>
<script>document.getElementById('theme-btn').addEventListener('click',function(){{var t=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=t;try{{localStorage.setItem('book-theme',t)}}catch(e){{}}}});</script>
</body></html>
"""
if ANALYTICS_TAG:
    chooser = chooser.replace('</body>', ANALYTICS_TAG + '\n</body>', 1)
open(os.path.join(OUT, 'index.html'), 'w', encoding='utf-8').write(seo.fingerprint(chooser, ASSETS))
seo.manifest(os.path.join(OUT, 'manifest.webmanifest'), f'{books["en"]} · {books["fa"]}', 'Ceph', 'en', 'ltr', seo.describe(CH_DESC), 'assets/icons/')
# 404 page (served from the site root by most static hosts; <base> keeps its links working at any depth when SITE_URL is set)
nf = f"""<!doctype html>
<html lang="fa" dir="rtl" data-theme="light"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
{f'<base href="{U.base}/">' if U.base else ''}<title>{esc(STR_FA["nf_title"])} · {esc(STR_EN["nf_title"])} — {esc(books["fa"])}</title>
<meta name="description" content="{esc(STR_FA["nf_text"])} {esc(STR_EN["nf_text"])}"><meta name="robots" content="noindex">
<link rel="icon" href="assets/icons/favicon.ico" sizes="48x48"><link rel="icon" href="assets/icons/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="assets/fonts.css"><link rel="stylesheet" href="assets/site.css"></head>
<body class="chooser"><main><h1>{esc(STR_FA["nf_title"])} · <span lang="en" dir="ltr">{esc(STR_EN["nf_title"])}</span></h1>
<p>{esc(STR_FA["nf_text"])}</p><p lang="en" dir="ltr">{esc(STR_EN["nf_text"])}</p>
<p><a class="btn primary" href="fa/index.html">{esc(STR_FA["home"])}: {esc(books["fa"])}</a> <a class="btn" href="fa/contents.html">{esc(STR_FA["contents"])}</a></p>
<p lang="en" dir="ltr"><a class="btn primary" href="en/index.html">{esc(STR_EN["home"])}: {esc(books["en"])}</a> <a class="btn" href="en/contents.html">{esc(STR_EN["contents"])}</a></p>
</main></body></html>
"""
open(os.path.join(OUT, '404.html'), 'w', encoding='utf-8').write(seo.fingerprint(nf, ASSETS))
seo.sitemap(os.path.join(OUT, 'sitemap.xml'), U, EMITTED, str(META['date']))
seo.robots(os.path.join(OUT, 'robots.txt'), U)
# LLM-facing catalogue, full-text dumps and per-page Markdown alternates (llmstxt.org)
from booklib import llmstxt  # noqa: E402
_home_lead = (f'{META.get("subtitle") or ""}\n\n{S["hero_lead"]}\n\n'
              f'Author: {seo.AUTHOR}. Version {META.get("version")}. '
              f'Licence: CC BY-NC-SA 4.0. Concept DOI: https://doi.org/{llmstxt.CONCEPT_DOI}.')
llmstxt.write_edition_markdowns(OUT, U, ROOT, LANG, pages, home_lead=_home_lead)
# App / generated pages that were emitted but are not in the book ``pages`` list
for _slug in EMITTED:
    _md = os.path.join(LOUT, f'{_slug}.md')
    if os.path.exists(_md):
        continue
    _html = os.path.join(LOUT, f'{_slug}.html')
    if not os.path.exists(_html):
        continue
    _soup = BeautifulSoup(open(_html, encoding='utf-8').read(), 'html.parser')
    _title = (_soup.select_one('h1') or _soup.title)
    _title = text_of(_title) if _title else _slug
    _main = _soup.select_one('article') or _soup.select_one('main') or _soup.body
    llmstxt.write_page_markdown(LOUT, _slug, _title, LANG, U, html=_main)
llmstxt.write_llms_txt(OUT, U, ROOT, version=str(META.get('version') or '1.6'))
llmstxt.write_llms_full(OUT, U, ROOT, 'en', version=str(META.get('version') or '1.6'))
llmstxt.write_llms_full(OUT, U, ROOT, 'fa', version=str(META.get('version') or '1.6'))
seo.host_files(OUT)
json.dump({'site_url': U.base, 'pages': EMITTED}, open(os.path.join(OUT, 'seo.json'), 'w'))
# releases feed (from CHANGELOG.md), custom domain for GitHub Pages, and what was configured
# (for tools/check_features.py; no secrets: the analytics token is not recorded here)
with open(os.path.join(OUT, 'releases.xml'), 'w', encoding='utf-8') as fh:
    fh.write(siteconf.atom_feed(os.path.join(ROOT, 'CHANGELOG.md'), CFG, U.base, yaml.safe_load(open(os.path.join(ROOT, 'content', 'en', 'ui.yaml'), encoding='utf-8'))['book'], seo.AUTHOR))
_cn = os.path.join(OUT, 'CNAME')
if CFG['cname']:
    open(_cn, 'w').write(CFG['cname'] + '\n')
elif os.path.exists(_cn):
    os.remove(_cn)
json.dump({'repo': CFG['repo'], 'branch': CFG['branch'], 'feedback': bool(CFG['feedback']), 'feedback_issues': CFG['feedback_issues'],
           'ask': CFG['ask'],
           'newsletter': CFG['newsletter'], 'analytics': CFG['analytics'],
           'analytics_hosts': [siteconf.ANALYTICS_HOSTS[CFG['analytics']]] if CFG['analytics'] else [], 'cname': CFG['cname']},
          open(os.path.join(OUT, 'features.json'), 'w'), indent=1)
if not os.path.exists(os.path.join(ASSETS, f'cover.{OTHER}.webp')):
    im = Image.open(os.path.join(ROOT, 'assets', f'cover.{OTHER}.png')).convert('RGB')
    im.thumbnail((720, 1100))
    im.save(os.path.join(ASSETS, f'cover.{OTHER}.webp'), quality=86)
print(json.dumps({'lang': LANG, 'pages': len(pages) + 1, 'search_docs': len(docs), 'out': os.path.relpath(LOUT, ROOT)}))
