#!/usr/bin/env python3
"""Check that the built web edition exposes AVIF figures ahead of WebP.

Without --require this is informational (exit 0 even when no AVIF files exist,
so a laptop without avifenc can still run make check-site). CI installs
libavif-bin and calls this with --require.
"""
from __future__ import annotations

import argparse
import os
import sys
from html.parser import HTMLParser

ap = argparse.ArgumentParser()
ap.add_argument('--site', default='build/site')
ap.add_argument('--require', action='store_true', help='fail if no AVIF figures or if a <picture> lists WebP before AVIF')
a = ap.parse_args()
SITE = os.path.abspath(a.site)
FIG = os.path.join(SITE, 'figures')


class Pictures(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.pictures = []
        self._cur = None

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag == 'picture':
            self._cur = []
        elif tag == 'source' and self._cur is not None:
            self._cur.append((d.get('type') or '', d.get('srcset') or ''))
        elif tag == 'img' and self._cur is not None:
            self._cur.append(('img', d.get('src') or ''))

    def handle_endtag(self, tag):
        if tag == 'picture' and self._cur is not None:
            self.pictures.append(self._cur)
            self._cur = None


def walk_html():
    for dirpath, _, files in os.walk(SITE):
        for fn in files:
            if fn.endswith('.html'):
                yield os.path.join(dirpath, fn)


avifs = []
if os.path.isdir(FIG):
    for dirpath, _, files in os.walk(FIG):
        for fn in files:
            if fn.endswith('.avif'):
                avifs.append(os.path.join(dirpath, fn))
webp = png = 0
if os.path.isdir(FIG):
    for dirpath, _, files in os.walk(FIG):
        for fn in files:
            if fn.endswith('.webp'):
                webp += 1
            elif fn.endswith('.png'):
                png += 1

avif_bytes = sum(os.path.getsize(p) for p in avifs)
pics = []
order_bad = []
missing_src = []
for f in walk_html():
    p = Pictures()
    try:
        p.feed(open(f, encoding='utf-8').read())
    except (OSError, UnicodeError):
        continue
    for sources in p.pictures:
        types = [t for t, _ in sources]
        pics.append((f, sources))
        if 'image/avif' in types and 'image/webp' in types:
            if types.index('image/avif') > types.index('image/webp'):
                order_bad.append(os.path.relpath(f, SITE))
        if 'image/avif' in types:
            srcset = next(s for t, s in sources if t == 'image/avif')
            # resolve relative to the page
            rel = srcset.split()[0]
            page_dir = os.path.dirname(f)
            path = os.path.normpath(os.path.join(page_dir, rel))
            if not os.path.exists(path):
                missing_src.append((os.path.relpath(f, SITE), rel))

n_with_avif = sum(1 for _, s in pics if any(t == 'image/avif' for t, _ in s))
print(f'check-avif: {len(avifs)} AVIF file(s) ({avif_bytes/1024:.0f} KiB) next to {webp} WebP and {png} PNG; '
      f'{n_with_avif}/{len(pics)} <picture> element(s) expose an AVIF source')
if order_bad:
    print(f'check-avif: {len(order_bad)} page(s) list WebP before AVIF, e.g. {order_bad[:3]}')
if missing_src:
    print(f'check-avif: {len(missing_src)} AVIF srcset path(s) do not exist, e.g. {missing_src[:3]}')

errors = []
if order_bad:
    errors.append('AVIF <source> must come before WebP')
if missing_src:
    errors.append('AVIF srcset points at a missing file')
if a.require:
    if len(avifs) < 50:
        errors.append(f'expected many AVIF figures, found {len(avifs)}')
    if not pics or n_with_avif == 0:
        errors.append('no <picture> on the site exposes an AVIF source')
    # almost every raster picture should have avif when the encoder ran
    raster = [s for _, s in pics if any(t in ('image/webp', 'image/avif', 'img') for t, _ in s)]
    if raster and n_with_avif < max(1, int(0.8 * len(raster))):
        errors.append(f'only {n_with_avif}/{len(raster)} pictures have an AVIF source')

if errors:
    for e in errors:
        print('check-avif: ERROR', e)
    sys.exit(1)
print('check-avif: ok' + (' (required)' if a.require else ''))
