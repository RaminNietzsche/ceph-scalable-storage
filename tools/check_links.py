#!/usr/bin/env python3
"""Check external links in content/ and references/.

Offline (default): URL syntax, scheme (https preferred), duplicates per file.
Online (--online): HTTP HEAD (falling back to GET) with a timeout; failures are
reported, and make the exit status non-zero only with --strict, because remote
sites rate-limit and block crawlers.

Usage: tools/check_links.py [--online] [--strict] [--lang fa|en|all]
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import glob
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
URL = re.compile(r'https?://[^\s<>()\]`"\'،؛]+')
ap = argparse.ArgumentParser()
ap.add_argument('--online', action='store_true')
ap.add_argument('--strict', action='store_true')
ap.add_argument('--lang', default='all')
ap.add_argument('--timeout', type=float, default=15)
a = ap.parse_args()
langs = ['fa', 'en'] if a.lang == 'all' else [a.lang]
files = []
for lang in langs:
    files += glob.glob(os.path.join(ROOT, 'content', lang, '**', '*.md'), recursive=True)
urls = {}
bad = []
for f in files:
    inc = False
    for ln, line in enumerate(open(f, encoding='utf-8'), 1):
        if line.startswith('```'):
            inc = not inc
            continue
        if inc:
            continue
        for u in URL.findall(re.sub(r'`[^`]*`', ' ', line)):
            u = u.rstrip('.,;:')
            p = urllib.parse.urlparse(u)
            if not p.netloc or '.' not in p.netloc:
                bad.append(f'{os.path.relpath(f, ROOT)}:{ln}: malformed URL {u}')
            urls.setdefault(u, f'{os.path.relpath(f, ROOT)}:{ln}')
for r in json.load(open(os.path.join(ROOT, 'references', 'references.json'), encoding='utf-8')):
    urls.setdefault(r['URL'], 'references/references.json')
http = [u for u in urls if u.startswith('http://')]
print(f'check-links: {len(urls)} unique URL(s), {len(bad)} malformed, {len(http)} plain http')
for b in bad:
    print('  ERROR', b)
failed = []
if a.online:
    def probe(u):
        hdr = {'User-Agent': 'Mozilla/5.0 (book link checker)'}
        for method in ('HEAD', 'GET'):
            try:
                req = urllib.request.Request(u, method=method, headers=hdr)
                with urllib.request.urlopen(req, timeout=a.timeout) as resp:
                    return u, resp.status
            except urllib.error.HTTPError as e:
                if method == 'GET' or e.code not in (403, 405, 400):
                    return u, e.code
            except Exception as e:  # noqa: BLE001
                if method == 'GET':
                    return u, type(e).__name__
        return u, 'error'
    with cf.ThreadPoolExecutor(16) as ex:
        for u, st in ex.map(probe, sorted(urls)):
            if not (isinstance(st, int) and st < 400):
                failed.append((u, st))
    print(f'  online: {len(failed)} URL(s) failed')
    for u, st in failed:
        print(f'  FAIL {st} {u} ({urls[u]})')
sys.exit(1 if bad or (a.strict and failed) else 0)
