#!/usr/bin/env python3
"""SEO and best-practice audit of the built web edition (run by ``make check-site``).

For every page of build/site/{fa,en}/*.html (plus the language chooser and 404.html) it asserts:
a unique <title> and meta description, <html lang/dir>, hreflang fa/en/x-default, canonical when
SITE_URL was set at build time (and none otherwise), Open Graph + Twitter card with an existing
image, valid JSON-LD (Book with author, licence, inLanguage and hasPart chapters plus
WebSite/SearchAction on the edition home; BreadcrumbList elsewhere), exactly one <h1>, descriptive
alt text and width/height on every image, lazy loading below the fold, meaningful link text, a font
preload, fingerprinted CSS/JS, a web manifest and favicons. Site-wide it checks sitemap.xml (both
editions, hreflang alternates), robots.txt, 404.html and the cache-policy files.

Usage: tools/check_seo.py [--site build/site] [--report]
Exit status 1 on any problem. --report prints the per-check pass counts.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
ap.add_argument('--report', action='store_true')
a = ap.parse_args()
SITE = os.path.abspath(a.site)
CFG = json.load(open(os.path.join(SITE, 'seo.json'))) if os.path.exists(os.path.join(SITE, 'seo.json')) else {'site_url': ''}
BASE = CFG.get('site_url', '')
GENERIC = {'here', 'click here', 'more', 'read more', 'link', 'this', 'this page', 'اینجا', 'این‌جا', 'کلیک کنید', 'بیشتر', 'لینک'}
VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'}


class Doc(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.html = {}
        self.title, self.in_title, self.titles = '', False, 0
        self.meta = collections.defaultdict(list)
        self.links = []
        self.ld, self.in_ld, self.buf = [], False, ''
        self.h1 = 0
        self.imgs = []
        self.anchors = []          # [attrs, text, img_alts]
        self.stack = []
        self.in_main = False
        self.hidden_depth = 0
        self.in_head = True

    def handle_starttag(self, tag, attrs):
        d = {k: (v or '') for k, v in attrs}
        if tag not in VOID:
            self.stack.append((tag, d.get('aria-hidden') == 'true'))
            if d.get('aria-hidden') == 'true':
                self.hidden_depth += 1
        if tag == 'html':
            self.html = d
        elif tag == 'title' and self.in_head:
            self.in_title, self.titles = True, self.titles + 1
        elif tag == 'meta':
            k = d.get('name') or d.get('property')
            if k:
                self.meta[k].append(d.get('content', ''))
        elif tag == 'link':
            self.links.append(d)
        elif tag == 'script' and d.get('type') == 'application/ld+json':
            self.in_ld, self.buf = True, ''
        elif tag == 'h1':
            self.h1 += 1
        elif tag in ('main', 'body'):
            self.in_head = False
            self.in_main = self.in_main or tag == 'main'
        elif tag == 'img':
            d['_main'] = self.in_main
            d['_hidden'] = self.hidden_depth > 0
            self.imgs.append(d)
            if self.anchors and self.anchors[-1][3]:
                self.anchors[-1][2].append(d.get('alt', ''))
        elif tag == 'a' and 'href' in d:
            self.anchors.append([d, '', [], True])

    def handle_endtag(self, tag):
        if tag == 'title':
            self.in_title = False
        elif tag == 'script' and self.in_ld:
            self.in_ld = False
            self.ld.append(self.buf)
        elif tag == 'a' and self.anchors:
            self.anchors[-1][3] = False
        if tag not in VOID:
            while self.stack:
                t, h = self.stack.pop()
                if h:
                    self.hidden_depth -= 1
                if t == tag:
                    break

    def handle_data(self, data):
        if self.in_title:
            self.title += data
        if self.in_ld:
            self.buf += data
        if self.anchors and self.anchors[-1][3] and not self.hidden_depth:
            self.anchors[-1][1] += data


errors = []
passed = collections.Counter()


def check(ok, name, rel, msg):
    if ok:
        passed[name] += 1
    else:
        errors.append(f'{rel}: {msg}')


def exists_ref(page, ref):
    u = urlsplit(ref)
    if u.scheme in ('http', 'https'):
        if BASE and ref.startswith(BASE + '/'):
            return os.path.exists(os.path.join(SITE, ref[len(BASE) + 1:].split('?')[0].split('#')[0]))
        return True
    return os.path.exists(os.path.normpath(os.path.join(os.path.dirname(page), u.path)))


def ld_types(objs):
    out = collections.defaultdict(list)
    for o in objs:
        for n in o.get('@graph', [o]):
            out[n.get('@type')].append(n)
    return out


titles = collections.defaultdict(dict)
long_titles = []
descs = collections.defaultdict(dict)
pages = []
for lang in ('fa', 'en'):
    pages += [(lang, f) for f in sorted(glob.glob(os.path.join(SITE, lang, '*.html')))]
pages.append(('root', os.path.join(SITE, 'index.html')))

for lang, f in pages:
    rel = os.path.relpath(f, SITE)
    if not os.path.exists(f):
        errors.append(f'missing {rel}')
        continue
    d = Doc()
    d.feed(open(f, encoding='utf-8').read())
    slug = os.path.basename(f)[:-5]
    edition_home = lang != 'root' and slug == 'index'
    # title and description
    t = re.sub(r'\s+', ' ', d.title).strip()
    check(d.titles == 1 and 10 <= len(t) <= 160, 'title', rel, f'title missing or of odd length ({len(t)}): "{t[:60]}"')
    if t in titles[lang]:
        errors.append(f'{rel}: title duplicates {titles[lang][t]}')
    titles[lang][t] = rel
    if len(t) > 70:
        long_titles.append(rel)
    desc = (d.meta.get('description') or [''])[0]
    check(len(d.meta.get('description', [])) == 1 and 50 <= len(desc) <= 200, 'description', rel, f'meta description missing or {len(desc)} chars')
    if desc in descs[lang]:
        errors.append(f'{rel}: meta description duplicates {descs[lang][desc]}')
    descs[lang][desc] = rel
    # html lang/dir
    want = {'fa': ('fa', 'rtl'), 'en': ('en', 'ltr'), 'root': ('en', 'ltr')}[lang]
    check((d.html.get('lang'), d.html.get('dir')) == want, 'html-lang-dir', rel, f'html lang/dir {d.html.get("lang")}/{d.html.get("dir")}, want {want}')
    check(d.meta.get('google-site-verification') == ['7UxUjcyaTpcjuxAHbfvsIWmIxNHIeQHkkvUZGSHLiLQ'],
          'gsc-verification', rel, 'Google Search Console verification tag missing or unexpected')
    # hreflang + canonical
    alts = {l.get('hreflang'): l.get('href') for l in d.links if l.get('rel') == 'alternate' and l.get('hreflang')}
    check({'fa', 'en', 'x-default'} <= set(alts), 'hreflang', rel, f'hreflang alternates {sorted(alts)}')
    check(all(exists_ref(f, h) for h in alts.values()), 'hreflang-target', rel, 'an hreflang target does not exist')
    canon = [l.get('href') for l in d.links if l.get('rel') == 'canonical']
    if BASE:
        exp = f'{BASE}/{rel}'.replace(os.sep, '/')
        check(canon == [exp], 'canonical', rel, f'canonical {canon}, want {exp}')
    else:
        check(not canon, 'canonical', rel, 'canonical present although SITE_URL was not set')
    # Open Graph / Twitter
    need = ('og:title', 'og:description', 'og:type', 'og:image', 'og:image:alt', 'og:locale', 'og:site_name', 'twitter:card', 'twitter:image')
    miss = [k for k in need if not (d.meta.get(k) or [''])[0]]
    check(not miss, 'opengraph', rel, f'missing {miss}')
    img = (d.meta.get('og:image') or [''])[0]
    check(bool(img) and exists_ref(f, img), 'og-image', rel, f'og:image does not exist: {img}')
    if BASE:
        check(img.startswith(BASE), 'og-image-abs', rel, 'og:image is not absolute although SITE_URL is set')
    # JSON-LD
    objs = []
    for raw in d.ld:
        try:
            objs.append(json.loads(raw))
        except ValueError as e:
            errors.append(f'{rel}: invalid JSON-LD ({e})')
    types = ld_types(objs)
    check(bool(objs) and all(o.get('@context') == 'https://schema.org' for o in objs), 'jsonld', rel, 'no JSON-LD with @context https://schema.org')
    if edition_home:
        hw = ('citation_title', 'citation_author', 'citation_publication_date', 'citation_doi')
        miss_hw = [k for k in hw if not (d.meta.get(k) or [''])[0]]
        check(not miss_hw, 'highwire', rel, f'missing Highwire tags {miss_hw}')
        b = (types.get('Book') or [{}])[0]
        ok = (b.get('author', {}).get('name') == 'Ramin Najarbashi' and 'by-nc-sa/4.0' in b.get('license', '')
              and b.get('inLanguage') == lang and len(b.get('hasPart', [])) >= 40
              and all(p.get('@type') == 'Chapter' and p.get('name') and p.get('url') for p in b.get('hasPart', [])))
        check(ok, 'jsonld-book', rel, 'Book JSON-LD lacks author/licence/inLanguage/hasPart chapters')
        author = b.get('author') or {}
        check(author.get('sameAs') == 'https://orcid.org/0009-0000-7622-8130' or
              author.get('identifier') == 'https://orcid.org/0009-0000-7622-8130',
              'jsonld-orcid', rel, 'Book JSON-LD author lacks ORCID')
        w = (types.get('WebSite') or [{}])[0]
        pa = w.get('potentialAction', {})
        check(pa.get('@type') == 'SearchAction' and '{search_term_string}' in json.dumps(pa), 'jsonld-search', rel, 'WebSite SearchAction missing')
    elif lang != 'root':
        bl = (types.get('BreadcrumbList') or [{}])[0]
        items = bl.get('itemListElement', [])
        check(len(items) >= 2 and all(i.get('name') and i.get('position') == k for k, i in enumerate(items, 1)), 'jsonld-breadcrumb', rel, 'BreadcrumbList missing or malformed')
        kind = (d.html.get('data-kind') or '')
        slug = os.path.splitext(os.path.basename(rel))[0]
        if kind in ('chapter', 'appendix'):
            ch = (types.get('Chapter') or [{}])[0]
            check(ch.get('@type', 'Chapter') == 'Chapter' and ch.get('name') and ch.get('url'),
                  'jsonld-chapter', rel, 'chapter/appendix page lacks Chapter JSON-LD')
            check(slug in img.replace('\\', '/'), 'og-image-page', rel, f'og:image is not the per-page card: {img}')
    else:
        check('WebSite' in types, 'jsonld', rel, 'chooser lacks WebSite JSON-LD')
    # headings
    check(d.h1 == 1, 'one-h1', rel, f'{d.h1} <h1> elements')
    # images
    vis = [i for i in d.imgs if not i['_hidden']]
    for k, i in enumerate(d.imgs):
        check(bool(i.get('width')) and bool(i.get('height')), 'img-size', rel, f'<img src="{i.get("src")}"> lacks width/height')
        if not i['_hidden'] and i.get('role') != 'presentation':
            alt = i.get('alt', '').strip()
            check(len(alt) >= 5 and not re.fullmatch(r'[\w\-]+\.(png|webp|svg|jpe?g)', alt), 'img-alt', rel, f'<img src="{i.get("src")}"> has no descriptive alt')
    main_imgs = [i for i in vis if i['_main']]
    for i in (main_imgs[1:] if lang != 'root' else []):
        check(i.get('loading') == 'lazy', 'img-lazy', rel, f'<img src="{i.get("src")}"> below the fold is not lazy')
    if main_imgs and edition_home:
        check(main_imgs[0].get('loading') != 'lazy', 'img-lcp', rel, 'hero image must not be lazy')
    # link text
    for attrs, text, alts_, _ in d.anchors:
        name = (attrs.get('aria-label') or re.sub(r'\s+', ' ', text).strip() or ' '.join(x for x in alts_ if x)).strip()
        if attrs.get('aria-hidden') == 'true' or attrs.get('tabindex') == '-1':
            continue
        bad = (not name or name.lower() in GENERIC or (re.fullmatch(r'[\W\d_۰-۹]+', name) is not None and not attrs.get('aria-label')))
        check(not bad, 'link-text', rel, f'link to {attrs.get("href")} has no meaningful text ("{name[:30]}")')
    # head resources
    raw_head = open(f, encoding='utf-8').read().split('</head>')[0]
    pre = [l.get('href') for l in d.links if l.get('rel') == 'preload' and l.get('as') == 'font' and 'crossorigin' in l]
    pre += re.findall(r"<script data-preload-font>.*?l\.as='font'.*?l\.href='([^']+)'", raw_head)
    check(bool(pre) and all(exists_ref(f, h) for h in pre), 'font-preload', rel, 'no valid font preload')
    css = [l.get('href', '') for l in d.links if l.get('rel') == 'stylesheet']
    check(bool(css) and all('?v=' in h for h in css if 'assets/' in h), 'fingerprint', rel, f'unversioned stylesheet in {css}')
    man = [l.get('href') for l in d.links if l.get('rel') == 'manifest']
    check(len(man) == 1 and exists_ref(f, man[0]), 'manifest', rel, 'web manifest link missing or broken')
    ic = [l.get('href') for l in d.links if l.get('rel') in ('icon', 'apple-touch-icon')]
    check(len(ic) >= 3 and all(exists_ref(f, h) for h in ic), 'favicons', rel, f'favicons missing or broken: {ic}')
    check(bool(d.meta.get('theme-color')), 'theme-color', rel, 'theme-color missing')

# manifests
for m in [os.path.join(SITE, 'manifest.webmanifest')] + [os.path.join(SITE, l, 'manifest.webmanifest') for l in ('fa', 'en')]:
    rel = os.path.relpath(m, SITE)
    try:
        j = json.load(open(m, encoding='utf-8'))
        ok = all(j.get(k) for k in ('name', 'short_name', 'start_url', 'display', 'theme_color', 'lang')) and \
            {i['sizes'] for i in j['icons']} >= {'192x192', '512x512'} and \
            all(os.path.exists(os.path.normpath(os.path.join(os.path.dirname(m), i['src']))) for i in j['icons'])
        check(ok, 'manifest-file', rel, 'manifest lacks fields or icons')
    except (OSError, ValueError, KeyError) as e:
        errors.append(f'{rel}: {e}')
# sitemap
sm = os.path.join(SITE, 'sitemap.xml')
try:
    tree = ET.parse(sm)
    ns = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9', 'x': 'http://www.w3.org/1999/xhtml'}
    urls = tree.getroot().findall('s:url', ns)
    locs = {u.find('s:loc', ns).text for u in urls}
    expect = set()
    for lang, f in pages:
        if lang != 'root':
            r = os.path.relpath(f, SITE).replace(os.sep, '/')
            expect.add(f'{BASE}/{r}' if BASE else r)
    check(expect <= locs, 'sitemap', 'sitemap.xml', f'{len(expect - locs)} pages missing, e.g. {sorted(expect - locs)[:3]}')
    check(all({x.get('hreflang') for x in u.findall('x:link', ns)} >= {'fa', 'en', 'x-default'} for u in urls), 'sitemap-hreflang', 'sitemap.xml', 'url without hreflang alternates')
    check(all(re.fullmatch(r'\d{4}-\d{2}-\d{2}', (u.find('s:lastmod', ns).text or '') if u.find('s:lastmod', ns) is not None else '') for u in urls), 'sitemap-lastmod', 'sitemap.xml', 'lastmod is missing or is not a full YYYY-MM-DD date')
    if BASE:
        check(all(l.startswith(BASE + '/') for l in locs), 'sitemap-abs', 'sitemap.xml', 'relative <loc> although SITE_URL is set')
except (OSError, ET.ParseError) as e:
    errors.append(f'sitemap.xml: {e}')
rb = os.path.join(SITE, 'robots.txt')
txt = open(rb).read() if os.path.exists(rb) else ''
check('User-agent:' in txt and (not BASE or f'Sitemap: {BASE}/sitemap.xml' in txt), 'robots', 'robots.txt', 'robots.txt missing or lacks Sitemap')
nf = os.path.join(SITE, '404.html')
nft = open(nf, encoding='utf-8').read() if os.path.exists(nf) else ''
check('noindex' in nft and '<h1>' in nft and 'fa/index.html' in nft and 'en/index.html' in nft, '404', '404.html', '404 page missing, indexable or without links home')
check(os.path.exists(os.path.join(SITE, '_headers')) and os.path.exists(os.path.join(SITE, '.htaccess')), 'cache-policy', '_headers', 'cache policy files missing')
# offline: no external scripts/styles (check_site covers src/href; double-check script tags in head)
for lang, f in pages:
    s = open(f, encoding='utf-8').read() if os.path.exists(f) else ''
    check(not re.search(r'<(script|link)[^>]+(src|href)="https?://(?!creativecommons)', s.split('</head>')[0]) or
          all(m.group(0).find('rel="canonical"') >= 0 or 'rel="alternate"' in m.group(0) or (BASE and 'rel="describedby"' in m.group(0) and f'href="{BASE}/' in m.group(0))
              for m in re.finditer(r'<link[^>]+href="https?://[^"]+"[^>]*>', s.split('</head>')[0])),
          'offline', os.path.relpath(f, SITE), 'external script or stylesheet in <head>')

for e in errors[:200]:
    print('check_seo:', e)
if a.report:
    for k, v in sorted(passed.items()):
        print(f'check_seo:   {k:18s} {v} passed')
print(f'check_seo: note: {len(long_titles)} titles are longer than 70 characters (long chapter titles; the book name is dropped from those)')
print(f'check_seo: {len(pages)} pages, {sum(passed.values())} checks passed, {len(errors)} problems'
      + (f' (SITE_URL={BASE})' if BASE else ' (SITE_URL not set: canonical omitted, relative URLs)'))
sys.exit(1 if errors else 0)
