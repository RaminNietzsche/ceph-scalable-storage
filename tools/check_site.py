#!/usr/bin/env python3
"""Check the built web edition: every local link, image, script and #anchor
resolves, ids are unique per page, and nothing is loaded from the network.

Usage: tools/check_site.py [--site build/site] [--lang fa|en|all]
Exit status 1 on any problem.
"""
from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import sys
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
ap.add_argument('--lang', default='all', choices=['fa', 'en', 'all'])
a = ap.parse_args()
SITE = os.path.abspath(a.site)
_cfg = os.path.join(SITE, 'seo.json')
BASE = (json.load(open(_cfg)).get('site_url') or '') if os.path.exists(_cfg) else ''
_feat = os.path.join(SITE, 'features.json')
# hosts the build was told to load analytics from (ANALYTICS / CF_BEACON_TOKEN); nothing else may load from the network
ALLOWED = set(json.load(open(_feat)).get('analytics_hosts') or []) if os.path.exists(_feat) else set()


class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.ids = collections.Counter()
        self.refs = []  # (attr, value, tag)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get('id'):
            self.ids[d['id']] += 1
        for k in ('href', 'src'):
            if d.get(k) is not None:
                self.refs.append((k, d[k], tag, d.get('rel', '')))


parsed = {}


def parse(path):
    if path not in parsed:
        p = P()
        p.feed(open(path, encoding='utf-8').read())
        parsed[path] = p
    return parsed[path]


files = [os.path.join(SITE, 'index.html')]
langs = ['fa', 'en'] if a.lang == 'all' else [a.lang]
for lang in langs:
    files += sorted(glob.glob(os.path.join(SITE, lang, '*.html')))
errors = []
nlinks = 0
other_lang_missing = 0
for f in files:
    if not os.path.exists(f):
        errors.append(f'missing page {os.path.relpath(f, SITE)}')
        continue
    p = parse(f)
    rel = os.path.relpath(f, SITE)
    for i, n in p.ids.items():
        if n > 1:
            errors.append(f'{rel}: duplicate id "{i}" ({n}x)')
    for attr, val, tag, relattr in p.refs:
        u = urlsplit(val)
        if u.scheme in ('http', 'https') and tag == 'link' and relattr in ('canonical', 'alternate'):
            # page URLs (not resources); with SITE_URL they must map onto a built page
            if BASE and val.startswith(BASE + '/') and not os.path.exists(os.path.join(SITE, val[len(BASE) + 1:])):
                errors.append(f'{rel}: {relattr} link to a page that was not built: {val}')
            continue
        if u.scheme in ('http', 'https'):
            if tag == 'script' and u.hostname in ALLOWED:
                continue
            if tag != 'a':
                errors.append(f'{rel}: external resource <{tag} {attr}="{val}"> (site must work offline)')
            continue
        if u.scheme in ('mailto',):
            continue
        if u.scheme:
            errors.append(f'{rel}: unexpected URL scheme in {val}')
            continue
        nlinks += 1
        target = f if not u.path else os.path.normpath(os.path.join(os.path.dirname(f), unquote(u.path)))
        if not os.path.exists(target):
            top = os.path.relpath(target, SITE).split(os.sep)[0]
            if tag in ('a', 'link') and top in ('fa', 'en') and top not in langs:
                other_lang_missing += 1
                continue
            errors.append(f'{rel}: broken {attr} "{val}"')
            continue
        if u.fragment and target.endswith('.html') and u.fragment != 'top':
            if u.fragment not in parse(target).ids:
                errors.append(f'{rel}: missing anchor "{val}"')
for e in errors[:200]:
    print('check_site:', e)
print(f'check_site: {len(files)} pages, {nlinks} local links/resources checked, {len(errors)} problems'
      + (f', {other_lang_missing} links into an edition that was not built' if other_lang_missing else ''))
sys.exit(1 if errors else 0)
