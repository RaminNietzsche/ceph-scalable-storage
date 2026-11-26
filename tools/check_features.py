#!/usr/bin/env python3
"""Check the reader features of the built web edition, in both languages.

* every chapter page opens with one «حوصله ندارم» / TL;DR box (<details open>, 3-5 items);
* every Ceph command block has a release badge linking into changes.html, and
  changes.html has a section for every release used;
* every chapter has an "Edit this page" link to REPO_URL/edit/<branch>/<source path>,
  and the source file exists;
* every chapter has "Was this section helpful?" rows, each naming an h2 that exists;
* the home pages have the newsletter section: a form posting to NEWSLETTER_ACTION
  when it was set, otherwise "Watch releases on GitHub" and the Atom feed; and a privacy note;
* paths.html has one section per path of references/reading-paths.yaml with all of its steps, paths-data.js
  carries the same paths for the on-page hint, and the home page, the sidebar and every chapter page
  link or load them;
* releases.xml is a well-formed Atom feed with one entry per released CHANGELOG version;
* CNAME holds the configured custom domain (or is absent), and the analytics beacon is on
  every page exactly when analytics was configured.

Usage: tools/check_features.py [--site build/site]
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import sys
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import readingpaths  # noqa: E402
from booklib import siteconf  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
a = ap.parse_args()
SITE = os.path.abspath(a.site)
F = json.load(open(os.path.join(SITE, 'features.json')))
errors: list[str] = []
stats = {'chapters': 0, 'badges': 0, 'fb_rows': 0, 'pages': 0}


def err(m):
    errors.append(m)


def soup(path):
    return BeautifulSoup(open(path, encoding='utf-8').read(), 'html.parser')


beacon_host = (F.get('analytics_hosts') or [None])[0]
for lang in ('fa', 'en'):
    changes = os.path.join(SITE, lang, 'changes.html')
    rel_ids = set()
    if not os.path.exists(changes):
        err(f'{lang}/changes.html missing')
    else:
        rel_ids = {x['id'] for x in soup(changes).select('[id^=rel-]')}
        for r in ('rel-reef', 'rel-squid', 'rel-tentacle'):
            if r not in rel_ids:
                err(f'{lang}/changes.html: no section #{r}')
    for path in sorted(glob.glob(os.path.join(SITE, lang, '*.html'))):
        s = soup(path)
        rel = os.path.relpath(path, SITE)
        stats['pages'] += 1
        scripts = [x for x in s.find_all('script', src=True) if re.match(r'https?://', x['src'])]
        if beacon_host:
            if len([x for x in scripts if beacon_host in x['src']]) != 1:
                err(f'{rel}: expected one analytics script from {beacon_host}')
        elif scripts:
            err(f'{rel}: external script {scripts[0]["src"]} but no analytics was configured')
        for code in s.select('div.code[data-since]'):
            stats['badges'] += 1
            b = code.select_one('a.since')
            if not b:
                err(f'{rel}: command block with data-since={code["data-since"]} has no badge')
                continue
            frag = b['href'].partition('#')[2]
            if not b['href'].startswith('changes.html#') or frag not in rel_ids:
                err(f'{rel}: badge links to {b["href"]}, not to a section of changes.html')
        html_el = s.find('html')
        if html_el.get('data-kind') != 'chapter':
            continue
        stats['chapters'] += 1
        t = s.select('details.tldr')
        if len(t) != 1 or not t[0].has_attr('open') or not 3 <= len(t[0].select('li')) <= 5:
            err(f'{rel}: expected one open TL;DR box with 3-5 items')
        elif t[0].find_previous(['h2']) is not None:
            err(f'{rel}: the TL;DR box is not at the top of the chapter')
        else:
            tf = t[0].select_one('div.tldr-fig a[href^="#fig-"]')
            ti = t[0].select_one('div.tldr-fig img[src]')
            if not tf or not ti:
                err(f'{rel}: TL;DR box missing figure thumbnail link')
            else:
                tgt_id = tf['href'][1:]
                if s.find(id=tgt_id) is None:
                    err(f'{rel}: TL;DR figure link #{tgt_id} does not match an id on the page')
        e = s.select_one('.ph-meta a.edit-link')
        want = f'{F["repo"]}/edit/{F["branch"]}/content/{lang}/chapters/{os.path.basename(path)[:-5]}.md'
        if not e:
            err(f'{rel}: no "Edit this page" link')
        elif e['href'] != want:
            err(f'{rel}: edit link {e["href"]} != {want}')
        elif not os.path.exists(os.path.join(ROOT, 'content', lang, 'chapters', os.path.basename(path)[:-5] + '.md')):
            err(f'{rel}: edit link points at a source file that does not exist')
        rows = s.select('div.fb[data-sec]')
        stats['fb_rows'] += len(rows)
        h2 = {x['id'] for x in s.select('h2[id]')}
        if not rows:
            err(f'{rel}: no "Was this section helpful?" rows')
        for r in rows:
            if r['data-sec'] not in h2:
                err(f'{rel}: feedback row names #{r["data-sec"]}, which is not an h2 of the page')
            if len(r.select('button.fb-b')) != 2:
                err(f'{rel}: feedback row #{r["data-sec"]} needs a yes and a no button')
    home = os.path.join(SITE, lang, 'index.html')
    hs = soup(home)
    nl = hs.select_one('section#newsletter')
    if not nl:
        err(f'{lang}/index.html: no newsletter section')
    else:
        form = nl.select_one('form.nl-form')
        if F.get('newsletter'):
            if not form or form.get('action') != F['newsletter'] or not form.select_one('input[type=email][name=email]'):
                err(f'{lang}/index.html: newsletter form missing or not posting to NEWSLETTER_ACTION')
        else:
            if form:
                err(f'{lang}/index.html: newsletter form present but NEWSLETTER_ACTION was not set')
            if not nl.select_one(f'a[href="{F["repo"]}/releases"]') or not nl.select_one('a[href="../releases.xml"]'):
                err(f'{lang}/index.html: no "Watch releases on GitHub" / Atom feed fallback')
        if not nl.select_one('.nl-privacy') or not nl.select_one('.nl-privacy').get_text(strip=True):
            err(f'{lang}/index.html: newsletter section has no privacy note')
    if not hs.select_one('link[rel=alternate][type="application/atom+xml"][href="../releases.xml"]'):
        err(f'{lang}/index.html: no <link rel=alternate> to the Atom feed')

feed = os.path.join(SITE, 'releases.xml')
try:
    root = ET.parse(feed).getroot()
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entries = root.findall('a:entry', ns)
    want = siteconf.changelog_releases(os.path.join(ROOT, 'CHANGELOG.md'))
    if root.tag != '{http://www.w3.org/2005/Atom}feed' or len(entries) != len(want) or not entries:
        err(f'releases.xml: {len(entries)} entries, CHANGELOG has {len(want)} released versions')
    for en in entries:
        for f in ('title', 'id', 'updated', 'content'):
            if en.find(f'a:{f}', ns) is None:
                err(f'releases.xml: entry without <{f}>')
except (OSError, ET.ParseError) as e:
    err(f'releases.xml: {e}')
# suggested reading paths: the page, the hint data and the entry points
_rp = readingpaths.load(ROOT)
for lang in ('fa', 'en'):
    pp = os.path.join(SITE, lang, 'paths.html')
    if not os.path.exists(pp):
        err(f'{lang}/paths.html missing')
        continue
    ps = soup(pp)
    for p in _rp['paths']:
        sec = ps.select_one(f'section.rtp[data-path="{p["id"]}"]')
        if sec is None:
            err(f'{lang}/paths.html: no section for path {p["id"]}')
            continue
        want_n = sum(len(st['steps']) for st in p['stages'])
        have_n = len(sec.select('li.rtp-step'))
        if have_n != want_n:
            err(f'{lang}/paths.html: path {p["id"]} shows {have_n} steps, the data has {want_n}')
        if not sec.select_one('button.rtp-follow[data-follow]'):
            err(f'{lang}/paths.html: path {p["id"]} has no follow button')
    for fn in ('paths-data.js',):
        pd = os.path.join(SITE, lang, fn)
        m = re.match(r'window\.__PATHS__=(.*);\s*$', open(pd, encoding='utf-8').read(), re.S) if os.path.exists(pd) else None
        try:
            dj = json.loads(m.group(1)) if m else None
        except ValueError:
            dj = None
        if not dj or [x['id'] for x in dj['paths']] != [p['id'] for p in _rp['paths']]:
            err(f'{lang}/{fn}: missing, malformed, or its paths differ from the data')
    for page_name in ('index.html', 'contents.html', '01-introduction-and-first-cluster.html'):
        pg = os.path.join(SITE, lang, page_name)
        if not os.path.exists(pg):
            continue
        html_ = open(pg, encoding='utf-8').read()
        if 'href="paths.html"' not in html_:
            err(f'{lang}/{page_name}: no link to paths.html')
        if 'paths-data.js' not in html_ or 'assets/paths.js' not in html_:
            err(f'{lang}/{page_name}: the reading-path scripts are not loaded')
    if not os.path.exists(os.path.join(SITE, 'assets', 'paths.js')):
        err('assets/paths.js missing')
cn = os.path.join(SITE, 'CNAME')
have = open(cn).read().strip() if os.path.exists(cn) else ''
if have != (F.get('cname') or ''):
    err(f'CNAME is {have!r}, expected {F.get("cname")!r}')
for e in errors[:200]:
    print('check_features:', e)
print(f'check_features: {stats["pages"]} pages, {stats["chapters"]} chapter pages, {stats["badges"]} release badges, '
      f'{stats["fb_rows"]} feedback rows, analytics={F.get("analytics") or "none"}, newsletter={"form" if F.get("newsletter") else "GitHub+feed"}, '
      f'CNAME={F.get("cname") or "-"}; {len(errors)} problems')
sys.exit(1 if errors else 0)
