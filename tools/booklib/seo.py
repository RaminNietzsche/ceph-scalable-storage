"""SEO and web-app metadata for the web edition (used by tools/build_site.py).

Everything here is static and offline: no trackers, no CDNs. Absolute URLs are
written only when SITE_URL is configured (``make site SITE_URL=https://...``);
without it canonical links are omitted and the other URLs stay relative, so the
site still works from file://.
"""
from __future__ import annotations

import hashlib
import html
import json
import os
import re
import subprocess

from PIL import Image, ImageDraw, ImageFont

LICENSE_URL = 'https://creativecommons.org/licenses/by-nc-sa/4.0/'
AUTHOR = 'Ramin Najarbashi'
THEME = '#0e7490'
BG = '#0b1120'
OG_W, OG_H = 1200, 630
LOCALE = {'fa': 'fa_IR', 'en': 'en_US'}
PRELOAD_FONT = {'fa': 'vazirmatn-400.woff2', 'en': 'inter-var.woff2'}

esc = lambda s: html.escape(str(s), quote=True)  # noqa: E731


class Urls:
    """URL helper: ``rel`` is used inside <lang>/ pages, ``root_rel`` at the site root."""

    def __init__(self, site_url):
        self.base = (site_url or '').strip().rstrip('/')

    def abs(self, path):
        return f'{self.base}/{path}' if self.base else None

    def rel(self, path):          # from a page in <lang>/
        return self.abs(path) or '../' + path

    def root(self, path):         # from a page at the site root
        return self.abs(path) or path


def describe(text, limit=158):
    """A meta description: whitespace collapsed, soft hyphens and bidi marks removed, cut at a word."""
    t = re.sub(r'\s+', ' ', re.sub('[\u00ad\u200e\u200f\u2066-\u2069]', '', text or '')).strip()
    if len(t) <= limit:
        return t
    cut = t[:limit - 1]
    if ' ' in cut[limit // 2:]:
        cut = cut[:cut.rfind(' ')]
    return cut.rstrip(' ,،;؛:-—') + '…'


def first_paragraph(body):
    for p in body.find_all('p'):
        if p.find_parent(['figure', 'table', 'aside', 'pre']) or 'ansref' in (p.get('class') or []):
            continue
        t = p.get_text(' ')
        if len(t.split()) >= 8:
            return t
    return ''


# ------------------------------------------------------------------ images
def _font(pattern, size):
    try:
        path = subprocess.run(['fc-match', '-f', '%{file}', pattern], capture_output=True, text=True, check=True).stdout.strip()
        return ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
    except Exception:  # noqa: BLE001 - fall back to PIL's bitmap font
        return ImageFont.load_default()


def _wrap(draw, text, font, width, **kw):
    words, lines, cur = text.split(), [], ''
    for w in words:
        t = (cur + ' ' + w).strip()
        if draw.textlength(t, font=font, **kw) <= width or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def og_image(cover_png, dst, lang, title, subtitle, byline):
    """1200×630 social card: the cover on a dark gradient with the title (Persian shaped with raqm)."""
    im = Image.new('RGB', (OG_W, OG_H), BG)
    px = im.load()
    for x in range(OG_W):   # horizontal gradient #0b1120 → #0e3a4a
        r, g, b = (int(a + (bb - a) * x / OG_W) for a, bb in ((0x0b, 0x0e), (0x11, 0x3a), (0x20, 0x4a)))
        for y in range(OG_H):
            px[x, y] = (r, g, b)
    cov = Image.open(cover_png).convert('RGB')
    cov.thumbnail((380, 540))
    rtl = lang == 'fa'
    cx = 70 if not rtl else OG_W - 70 - cov.width
    im.paste(cov, (cx, (OG_H - cov.height) // 2))
    d = ImageDraw.Draw(im)
    kw = {'direction': 'rtl', 'language': 'fa'} if rtl else {}
    fam = 'Vazirmatn' if rtl else 'Inter'
    f_t, f_s, f_b = _font(f'{fam}:weight=200', 64), _font(f'{fam}:weight=80', 30), _font(f'{fam}:weight=100', 28)
    tx0, tx1 = (cx + cov.width + 60, OG_W - 70) if not rtl else (70, cx - 60)
    width = tx1 - tx0
    y = 120
    try:
        for size_font, text, fill, gap in ((f_t, title, '#ffffff', 14), (f_s, subtitle, '#a5f3fc', 10)):
            for line in _wrap(d, text, size_font, width, **kw)[:4]:
                w = d.textlength(line, font=size_font, **kw)
                d.text((tx1 - w if rtl else tx0, y), line, font=size_font, fill=fill, **kw)
                y += size_font.size + gap
            y += 26
        w = d.textlength(byline, font=f_b, **kw)
        d.text((tx1 - w if rtl else tx0, OG_H - 110), byline, font=f_b, fill='#e2e8f0', **kw)
    except (TypeError, KeyError, OSError):
        pass   # no raqm: the cover alone still makes a valid card
    d.rectangle((0, OG_H - 10, OG_W, OG_H), fill=THEME)
    im.save(dst, optimize=True)
    return OG_W, OG_H


def _icon(size):
    s = 4  # supersample
    n = size * s
    im = Image.new('RGBA', (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, n - 1, n - 1), radius=int(n * 0.22), fill=THEME)
    pts = [(0.5, 0.27), (0.27, 0.70), (0.73, 0.70)]
    pts = [(int(x * n), int(y * n)) for x, y in pts]
    lw = max(2, int(n * 0.06))
    for a, b in ((0, 1), (0, 2), (1, 2)):
        d.line((pts[a], pts[b]), fill='white', width=lw)
    r = int(n * 0.11)
    for x, y in pts:
        d.ellipse((x - r, y - r, x + r, y + r), fill='white')
    return im.resize((size, size), Image.LANCZOS)


ICON_SVG = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="%s"/>'
            '<path d="M32 17.3 17.3 44.8h29.4z" fill="none" stroke="#fff" stroke-width="3.8"/>'
            '<g fill="#fff"><circle cx="32" cy="17.3" r="7"/><circle cx="17.3" cy="44.8" r="7"/><circle cx="46.7" cy="44.8" r="7"/></g></svg>\n') % THEME


def icons(dstdir):
    os.makedirs(dstdir, exist_ok=True)
    for n, name in ((192, 'icon-192.png'), (512, 'icon-512.png'), (180, 'apple-touch-icon.png')):
        _icon(n).save(os.path.join(dstdir, name), optimize=True)
    m = Image.new('RGBA', (512, 512), THEME)   # maskable: full-bleed background, glyph inside the safe zone
    m.alpha_composite(_icon(360), (76, 76))
    m.save(os.path.join(dstdir, 'icon-maskable-512.png'), optimize=True)
    _icon(64).save(os.path.join(dstdir, 'favicon.ico'), sizes=[(16, 16), (32, 32), (48, 48)])
    open(os.path.join(dstdir, 'icon.svg'), 'w').write(ICON_SVG)


def manifest(path, name, short, lang, dirn, desc, icon_prefix, start='index.html'):
    data = {'name': name, 'short_name': short, 'description': desc, 'lang': lang, 'dir': dirn,
            'start_url': start, 'scope': './', 'display': 'standalone', 'background_color': BG, 'theme_color': THEME,
            'icons': [{'src': f'{icon_prefix}icon-192.png', 'sizes': '192x192', 'type': 'image/png'},
                      {'src': f'{icon_prefix}icon-512.png', 'sizes': '512x512', 'type': 'image/png'},
                      {'src': f'{icon_prefix}icon-maskable-512.png', 'sizes': '512x512', 'type': 'image/png', 'purpose': 'maskable'}]}
    open(path, 'w', encoding='utf-8').write(json.dumps(data, ensure_ascii=False, indent=1) + '\n')


# ------------------------------------------------------------------ head
_hash_cache = {}


def fingerprint(doc, assets_dir):
    """Append ?v=<content hash> to ../assets/*.css|js references so long cache lifetimes are safe."""
    def rep(m):
        f = os.path.join(assets_dir, m.group(2))
        if f not in _hash_cache:
            _hash_cache[f] = hashlib.sha256(open(f, 'rb').read()).hexdigest()[:10] if os.path.exists(f) else ''
        return f'{m.group(1)}{m.group(2)}' + (f'?v={_hash_cache[f]}' if _hash_cache[f] else '') + '"'
    return re.sub(r'((?:\.\./)?assets/)([\w./-]+\.(?:css|js))"', rep, doc)


def preload(href):
    """Font preload. Over http(s) it is a normal <link rel=preload>; from file:// Chrome rejects
    crossorigin preloads with console errors, so the link is added by a tiny inline script that skips file://."""
    return ("<script data-preload-font>if(location.protocol!=='file:'){var l=document.createElement('link');"
            f"l.rel='preload';l.as='font';l.type='font/woff2';l.crossOrigin='anonymous';l.href='{href}';document.head.appendChild(l)}}</script>")


def head(u, lang, other, slug, title, desc, og_type, og_alt, book, jsonld, icon_prefix='../assets/icons/',
         manifest_href='manifest.webmanifest', font_href=None, og_img=None):
    me, them = f'{lang}/{slug}.html', f'{other}/{slug}.html'
    rel = u.rel
    out = [f'<meta name="description" content="{esc(desc)}">']
    if u.base:
        out.append(f'<link rel="canonical" href="{u.abs(me)}">')
    out += [f'<link rel="alternate" hreflang="{lang}" href="{rel(me)}">',
            f'<link rel="alternate" hreflang="{other}" href="{rel(them)}">',
            f'<link rel="alternate" hreflang="x-default" href="{rel("index.html")}">',
            f'<meta name="theme-color" content="{THEME}">',
            f'<link rel="icon" href="{icon_prefix}favicon.ico" sizes="48x48">',
            f'<link rel="icon" href="{icon_prefix}icon.svg" type="image/svg+xml">',
            f'<link rel="apple-touch-icon" href="{icon_prefix}apple-touch-icon.png">',
            f'<link rel="manifest" href="{manifest_href}">']
    if font_href:
        out.append(preload(font_href))
    img = og_img or rel(f'assets/og.{lang}.png')
    out += [f'<meta property="og:type" content="{og_type}">', f'<meta property="og:site_name" content="{esc(book)}">',
            f'<meta property="og:title" content="{esc(title)}">', f'<meta property="og:description" content="{esc(desc)}">',
            f'<meta property="og:locale" content="{LOCALE[lang]}">', f'<meta property="og:locale:alternate" content="{LOCALE[other]}">',
            f'<meta property="og:image" content="{img}">', f'<meta property="og:image:width" content="{OG_W}">',
            f'<meta property="og:image:height" content="{OG_H}">', f'<meta property="og:image:alt" content="{esc(og_alt)}">']
    if u.base:
        out.append(f'<meta property="og:url" content="{u.abs(me)}">')
    out += ['<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:title" content="{esc(title)}">',
            f'<meta name="twitter:description" content="{esc(desc)}">', f'<meta name="twitter:image" content="{img}">',
            f'<meta name="twitter:image:alt" content="{esc(og_alt)}">']
    if jsonld:
        out.append('<script type="application/ld+json">' + json.dumps(jsonld, ensure_ascii=False, separators=(',', ':')).replace('</', '<\\/') + '</script>')
    return '\n'.join(out)


def book_ld(u, lang, other, book, other_book, desc, version, date, chapters, image):
    """chapters: [(position, name, slug)]"""
    url = u.rel(f'{lang}/index.html')
    bid = url + '#book'
    b = {'@type': 'Book', '@id': bid, 'name': book, 'url': url, 'description': desc, 'inLanguage': lang,
         'author': {'@type': 'Person', 'name': AUTHOR}, 'creator': {'@type': 'Person', 'name': AUTHOR},
         'license': LICENSE_URL, 'bookFormat': 'https://schema.org/EBook', 'version': version, 'datePublished': date,
         'image': image, 'isAccessibleForFree': True,
         'hasPart': [{'@type': 'Chapter', 'position': n, 'name': t, 'url': u.rel(f'{lang}/{s}.html')} for n, t, s in chapters]}
    rel_key = 'translationOfWork' if lang == 'en' else 'workTranslation'
    b[rel_key] = {'@type': 'Book', 'name': other_book, 'inLanguage': other, 'url': u.rel(f'{other}/index.html')}
    site = {'@type': 'WebSite', '@id': url + '#website', 'name': book, 'url': url, 'inLanguage': lang,
            'publisher': {'@type': 'Person', 'name': AUTHOR},
            'potentialAction': {'@type': 'SearchAction',
                                'target': {'@type': 'EntryPoint', 'urlTemplate': url + '?q={search_term_string}'},
                                'query-input': 'required name=search_term_string'}}
    return {'@context': 'https://schema.org', '@graph': [site, b]}


def crumbs_ld(u, lang, trail, extra=None):
    """trail: [(name, slug-or-None)]; the last item is the page itself."""
    items = []
    for i, (name, slug) in enumerate(trail, 1):
        it = {'@type': 'ListItem', 'position': i, 'name': name}
        if slug:
            it['item'] = u.rel(f'{lang}/{slug}.html')
        items.append(it)
    graph = [{'@type': 'BreadcrumbList', 'itemListElement': items}]
    if extra:
        graph.append(extra)
    return {'@context': 'https://schema.org', '@graph': graph}


# ------------------------------------------------------------------ site-level files
def sitemap(path, u, slugs, date):
    """slugs exist in both editions under the same file names."""
    ns = ('<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n')
    out = [ns]
    for slug in slugs:
        for lang in ('fa', 'en'):
            out.append(f'<url><loc>{esc(u.root(f"{lang}/{slug}.html"))}</loc><lastmod>{date}</lastmod>')
            for l2 in ('fa', 'en'):
                out.append(f'<xhtml:link rel="alternate" hreflang="{l2}" href="{esc(u.root(f"{l2}/{slug}.html"))}"/>')
            out.append(f'<xhtml:link rel="alternate" hreflang="x-default" href="{esc(u.root("index.html"))}"/></url>\n')
    out.append('</urlset>\n')
    open(path, 'w', encoding='utf-8').write(''.join(out))


def robots(path, u):
    txt = 'User-agent: *\nAllow: /\nDisallow: /404.html\n'
    if u.base:
        txt += f'\nSitemap: {u.abs("sitemap.xml")}\n'
    else:
        txt += '\n# Build with SITE_URL=https://example.org/book to add the absolute Sitemap: line.\n'
    open(path, 'w').write(txt)


HEADERS = """# Cache policy for static hosts that read _headers (Netlify, Cloudflare Pages).
# CSS and JS are fingerprinted with ?v=<hash> by tools/build_site.py, so they can be cached for a year.
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/figures/*
  Cache-Control: public, max-age=604800
/*.html
  Cache-Control: public, max-age=0, must-revalidate
/*/*.js
  Cache-Control: public, max-age=3600
"""

HTACCESS = """# Apache: the same cache policy as _headers, plus the 404 page.
ErrorDocument 404 /404.html
<IfModule mod_expires.c>
  ExpiresActive On
  ExpiresByType text/css "access plus 1 year"
  ExpiresByType application/javascript "access plus 1 year"
  ExpiresByType font/woff2 "access plus 1 year"
  ExpiresByType image/png "access plus 1 week"
  ExpiresByType image/webp "access plus 1 week"
  ExpiresByType image/svg+xml "access plus 1 week"
  ExpiresByType text/html "access plus 0 seconds"
</IfModule>
AddType application/manifest+json .webmanifest
AddType font/woff2 .woff2
"""


def host_files(out):
    open(os.path.join(out, '_headers'), 'w').write(HEADERS)
    open(os.path.join(out, '.htaccess'), 'w').write(HTACCESS)
