#!/usr/bin/env python3
"""Smoke-test the web edition in headless Chrome and take screenshots.

Usage: tools/shoot_site.py [--site build/site] [--out build/site-shots] [--chapter-fa SLUG] [--chapter-en SLUG]

For fa and en, at 1440 px and 390 px: home, a chapter with figures, the figure
lightbox (zoomed), the mobile menu (390 px), dark mode and search; then each
simulator of the interactive lab is driven once (desktop, one mobile, one dark,
print media and no-JavaScript fallback). Pages are
opened over file://, so the test also proves the site needs no server and no
network. Any console error, page error or failed request makes the run fail.
Needs Python Playwright; Chrome is taken from $CHROME (default google-chrome).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys

from playwright.sync_api import sync_playwright

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
ap = argparse.ArgumentParser()
ap.add_argument('--site', default=os.path.join(ROOT, 'build', 'site'))
ap.add_argument('--out', default=os.path.join(ROOT, 'build', 'site-shots'))
ap.add_argument('--chapter-fa', default='12-bluestore')
ap.add_argument('--chapter-en', default='11-deployment')
ap.add_argument('--sims-only', action='store_true', help='only the interactive lab section')
ap.add_argument('--bookmarks-only', action='store_true', help='only the heading-bookmark section (file:// and http)')
ap.add_argument('--ui-only', action='store_true', help='only the UI consistency section (fonts, equal cards)')
a = ap.parse_args()
SITE = os.path.abspath(a.site)
OUT = os.path.abspath(a.out)
os.makedirs(OUT, exist_ok=True)
chrome = os.environ.get('CHROME') or shutil.which('google-chrome') or shutil.which('chromium')
problems = []
notes = []
shots = []


def url(lang, slug, frag=''):
    return 'file://' + os.path.join(SITE, lang, slug + '.html') + frag


SEED = r"""([lang, name]) => {
    const P0 = JSON.parse(document.getElementById('site-data').textContent).pages;
    const chs = Object.keys(P0).filter(k => P0[k][2] > 0).sort((a, b) => P0[a][2] - P0[b][2]);
    const pad = n => (n < 10 ? '0' : '') + n;
    const key = t => t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate());
    const ago = n => { const t = new Date(); t.setHours(12); t.setDate(t.getDate() - n); return key(t); };
    const read = {};
    chs.forEach((k, i) => { const n = P0[k][2]; if (n <= 13 || n === 17 || n === 18 || n === 20) read[k] = Date.now() - (40 - i) * 864e5; });
    const days = {}, frozen = {};
    for (let i = 160; i >= 1; i--) {
        const r = (i * 7919) % 23;
        let m = i <= 12 ? 12 + (i * 5) % 30 : (r < 9 ? 0 : 6 + (r * 3) % 45);
        if (i === 6) { m = 0; frozen[ago(i)] = 1; }
        if (m) days[ago(i)] = { s: m * 60, x: m * 3, sec: Math.ceil(m / 6), c: (i * 3) % 14, m: 0, nw: 0, k: {}, gm: m >= 10 ? 1 : 0 };
    }
    days[ago(0)] = { s: 420, x: 25, sec: 2, c: 0, m: 0, nw: 0, k: {} };
    const srs = {};
    for (let k = 1; k <= 8; k++) srs['q1-' + k] = { b: 2, d: ago(0), n: 2, l: 0 };
    for (let k = 1; k <= 10; k++) srs['q2-' + k] = { b: 4, d: ago(-6), n: 4, l: 1 };
    const algo = {}; for (let i = 1; i <= 64; i++) algo['alg-x-' + i] = 1;
    const zoom = {}; for (let i = 1; i <= 14; i++) zoom['fig-x-' + i] = 1;
    const secs = {}; chs.slice(0, 13).forEach(k => { for (let i = 1; i <= 9; i++) secs[k + '#s' + i] = 1; });
    const chXP = {}; Object.keys(read).forEach(k => chXP[k] = 50);
    const g = { v: 1, on: true, sound: false, goal: { t: 'min', n: 10 }, restDays: true, xp: 2550, days, fz: 2, fzEarned: 4, frozen,
        settled: ago(1), best: 19, badges: {}, secs, chXP, zoom, algo, srs, glossOn: true, quiz: { ok: 37, n: 45, run: 3, best: 8 },
        wk: null, name, flags: { night: 1 }, lv: 7, seen: ago(0) };
    localStorage.setItem('book-progress:' + lang, JSON.stringify({ v: 2, read, max: {}, last: { s: chs[13], f: 0.3, h: '', t: Date.now() }, marks: [], g }));
}"""

# every lab card must show a drawn icon and a non-empty preview
CARD_VIS = r"""() => [...document.querySelectorAll('.lab-card')].map(c => {
    const ic = c.querySelector('.sim-ic'), path = ic && ic.querySelector('path'), th = c.querySelector('.lab-thumb');
    const st = ic ? getComputedStyle(ic).stroke : 'none', bb = path ? path.getBBox() : {width: 0, height: 0};
    const tr = th ? th.getBoundingClientRect() : {width: 0, height: 0};
    const drawn = th ? [...th.querySelectorAll('svg rect, svg path, svg line, svg text, td, .sim-stat, li, .ec-card, .ps-osd, .st-set')].filter(e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; }).length : 0;
    return { href: c.getAttribute('href'), icon: !!path && st !== 'none' && bb.width > 0 && bb.height > 0, stroke: st,
             thumb: tr.width > 100 && tr.height > 50, drawn };
})"""


def check_cards(page, where):
    cards = page.evaluate(CARD_VIS)
    want = 8 if where.startswith('home') else 23   # the home page shows the first eight; lab.html lists all twenty-three
    if len(cards) != want:
        problems.append(f'[{where}] {len(cards)} lab cards (expected {want})')
    for c in cards:
        if not c['icon']:
            problems.append(f'[{where}] {c["href"]}: icon not drawn (stroke {c["stroke"]})')
        if not c['thumb'] or c['drawn'] < 3:
            problems.append(f'[{where}] {c["href"]}: preview empty ({c})')
    return cards


# UI consistency (fonts of every control, equal badge cards): fa desktop and mobile, light and dark
FONT_CHECK = r"""(want) => {
    const bad = [];
    document.querySelectorAll('button, input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), select, textarea, .btn, .chip, .pill span, .g-chip, .tb-cta, .sim-btn').forEach(el => {
        const r = el.getBoundingClientRect();
        if (!r.width || !r.height || el.closest('.code, .term, .lb, [hidden]')) return;
        const cs = getComputedStyle(el), fam = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim();
        if (fam !== want) bad.push((el.className || el.tagName) + ': ' + fam);
    });
    return bad;
}"""
CARD_CHECK = r"""() => {
    const b = [...document.querySelectorAll('.badge')].map(e => e.getBoundingClientRect()).filter(r => r.width);
    const hs = b.map(r => Math.round(r.height));
    const bars = [...document.querySelectorAll('.badge')].filter(e => e.querySelector('.g-bar')).map(e => {
        const r = e.getBoundingClientRect(), g = e.querySelector('.g-bar').getBoundingClientRect(); return Math.round(r.bottom - g.bottom); });
    const ws = b.map(r => Math.round(r.width));
    return { n: b.length, hmin: Math.min(...hs), hmax: Math.max(...hs), wmin: Math.min(...ws), wmax: Math.max(...ws),
             barmin: bars.length ? Math.min(...bars) : 0, barmax: bars.length ? Math.max(...bars) : 0 };
}"""


def ui_section(browser):
    for scheme in ('light', 'dark'):
        for w, h, tag in ((1440, 900, 'desktop'), (390, 844, 'mobile')):
            ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1 if w > 800 else 2,
                                      has_touch=w < 800, color_scheme=scheme, reduced_motion='reduce')
            ctx.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
            page = ctx.new_page()
            lab = f'ui {tag} {scheme}'
            page.on('console', lambda m, l=lab: m.type == 'error' and problems.append(f'[{l}] console: {m.text}'))
            page.on('pageerror', lambda e, l=lab: problems.append(f'[{l}] pageerror: {e}'))

            def usnap(name, el=None, full=False):
                p = os.path.join(OUT, f'fa-{tag}-{scheme}-{name}.png')
                if el:
                    page.locator(el).first.screenshot(path=p, style='.topbar, .g-toasts, .totop { visibility: hidden !important; }')
                else:
                    page.screenshot(path=p, full_page=full)
                shots.append(p)

            def fonts(where):
                bad = page.evaluate(FONT_CHECK, 'Vazirmatn')
                if bad:
                    problems.append(f'[{lab}] {where}: {len(bad)} control(s) not in Vazirmatn, e.g. {bad[:3]}')

            page.goto(url('fa', 'index'))
            page.evaluate(SEED, ['fa', 'خواننده‌ی نمونه'])
            page.evaluate(f"localStorage.setItem('book-theme', '{scheme}')")
            page.reload()
            page.wait_for_timeout(300)
            fonts('home')
            page.goto(url('fa', 'progress'))
            page.wait_for_timeout(500)
            fonts('dashboard')
            c = page.evaluate(CARD_CHECK)
            if c['hmax'] - c['hmin'] > 1 or c['wmax'] - c['wmin'] > 1:
                problems.append(f'[{lab}] badge cards differ in size: {c}')
            if c['barmax'] - c['barmin'] > 1:
                problems.append(f'[{lab}] badge progress bars not aligned to the bottom: {c}')
            notes.append(f'[{lab}] badges {c}')
            usnap('dashboard', full=True)
            usnap('badges', el='#gm-badges')
            page.goto(url('fa', 'review'))
            page.wait_for_selector('.flash')
            page.keyboard.press(' ')
            page.wait_for_timeout(300)
            fonts('review')
            usnap('review')
            page.goto(url('fa', 'lab-crush'))
            page.wait_for_selector('.sim-slot.sim-on')
            fonts('sim')
            usnap('sim', el='.sim-slot')
            ctx.close()


BM_PROBE = r"""() => [...document.querySelectorAll('article.content h2[id]:not(.qz-h), article.content h3[id]')]
    .filter(h => !h.closest('.page-head')).map(h => {
        const b = h.querySelector(':scope > .hbm');
        if (!b) return {id: h.id, why: 'no button'};
        const cs = getComputedStyle(b), r = b.getBoundingClientRect();
        if (cs.display === 'none' || cs.visibility !== 'visible') return {id: h.id, why: 'hidden'};
        if (+cs.opacity < 0.8) return {id: h.id, why: 'opacity ' + cs.opacity};
        if (r.width < 24 || r.height < 24) return {id: h.id, why: 'too small ' + r.width + 'x' + r.height};
        if (!b.getAttribute('aria-label')) return {id: h.id, why: 'no aria-label'};
        return null;
    }).filter(Boolean)"""


def bookmark_section(browser):
    """Every h2/h3 of every chapter has a visible (not hover-only) bookmark button, in fa and en,
    light and dark, desktop (mouse) and touch; clicking one (mouse and keyboard) adds a bookmark
    that the bookmarks panel lists on another page. Run over file:// and over http."""
    import functools
    import http.server
    import threading
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
    handler = functools.partial(Quiet, directory=SITE)
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    http_base = f'http://127.0.0.1:{srv.server_address[1]}'
    try:
        for scheme in ('file', 'http'):
            def u(lang, slug):
                return url(lang, slug) if scheme == 'file' else f'{http_base}/{lang}/{slug}.html'
            for lang in ('fa', 'en'):
                slugs = sorted(f[:-5] for f in os.listdir(os.path.join(SITE, lang)) if f[:2].isdigit() and f.endswith('.html'))
                for color, touch in (('light', False), ('dark', False), ('light', True)):
                    tag = f'bookmarks {scheme} {lang} {color}{" touch" if touch else ""}'
                    ctx = browser.new_context(viewport={'width': 390, 'height': 844} if touch else {'width': 1440, 'height': 900},
                                              has_touch=touch, is_mobile=touch, color_scheme=color, reduced_motion='reduce')
                    ctx.route('http*://**', lambda r: r.continue_() if r.request.url.startswith(http_base)
                              else (problems.append(f'network request {r.request.url}'), r.abort()))
                    page = ctx.new_page()
                    page.on('console', lambda m, t=tag: m.type == 'error' and problems.append(f'[{t}] console: {m.text}'))
                    page.on('pageerror', lambda e, t=tag: problems.append(f'[{t}] pageerror: {e}'))
                    # every heading of every chapter (once per scheme/lang, in the light desktop pass; one chapter otherwise)
                    for slug in (slugs if (color, touch) == ('light', False) else slugs[:1]):
                        page.goto(u(lang, slug))
                        bad = page.evaluate(BM_PROBE)
                        if bad:
                            problems.append(f'[{tag}] {slug}: {len(bad)} heading(s) without a visible bookmark button, e.g. {bad[:3]}')
                        if page.locator('article.content h2[id] .hbm').count() < 1:
                            problems.append(f'[{tag}] {slug}: no bookmark buttons at all')
                    slug = slugs[0]
                    page.goto(u(lang, slug))
                    page.evaluate(f"localStorage.removeItem('book-progress:{lang}')")
                    page.reload()
                    hb = page.locator('article.content h2[id] .hbm')
                    h = page.locator('article.content h2[id]').nth(1)
                    h.scroll_into_view_if_needed()
                    want = page.evaluate("document.querySelectorAll('article.content h2[id]')[1].id")
                    if touch:
                        hb.nth(1).tap()
                    else:
                        hb.nth(1).click()
                    if hb.nth(1).get_attribute('aria-pressed') != 'true':
                        problems.append(f'[{tag}] clicking the bookmark button did not mark the heading')
                    if not touch and color == 'light':
                        # keyboard: focus the third heading's button and press Enter
                        hb.nth(2).focus()
                        page.keyboard.press('Enter')
                        if hb.nth(2).get_attribute('aria-pressed') != 'true':
                            problems.append(f'[{tag}] Enter on a focused bookmark button did not mark the heading')
                        h.scroll_into_view_if_needed()
                        p = os.path.join(OUT, f'{lang}-{scheme}-bookmark-buttons.png')
                        page.screenshot(path=p); shots.append(p)
                    if color == 'dark' and scheme == 'file':
                        h.scroll_into_view_if_needed()
                        p = os.path.join(OUT, f'{lang}-dark-bookmark-buttons.png')
                        page.screenshot(path=p); shots.append(p)
                    # the bookmarks panel on another page lists it
                    page.goto(u(lang, 'contents'))
                    page.locator('#my-btn').click()
                    page.wait_for_timeout(200)
                    hrefs = page.eval_on_selector_all('#mk-list li a', 'as => as.map(a => a.getAttribute("href"))')
                    if f'{slug}.html#{want}' not in hrefs:
                        problems.append(f'[{tag}] bookmark {slug}#{want} not listed in the bookmarks panel ({hrefs})')
                    if page.locator('.mk-empty').is_visible():
                        problems.append(f'[{tag}] bookmarks panel still says there are no bookmarks')
                    if not touch and color == 'light':
                        p = os.path.join(OUT, f'{lang}-{scheme}-bookmarks-panel.png')
                        page.screenshot(path=p); shots.append(p)
                    ctx.close()
    finally:
        srv.shutdown()


def finish():
    json.dump({'screenshots': shots, 'problems': problems, 'notes': notes}, open(os.path.join(OUT, 'report.json'), 'w'), indent=1, ensure_ascii=False)
    for p in problems:
        print('shoot_site:', p)
    print(f'shoot_site: {len(shots)} screenshots in {OUT}, {len(problems)} problems')
    sys.exit(1 if problems else 0)



with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=chrome, args=['--no-sandbox'])
    if a.bookmarks_only:
        bookmark_section(browser)
        browser.close()
        finish()
    if not (a.ui_only or a.sims_only):
        bookmark_section(browser)
    if a.ui_only:
        ui_section(browser)
        browser.close()
        finish()
    for lang in (() if a.sims_only or a.ui_only else ('fa', 'en')):
        chap = a.chapter_fa if lang == 'fa' else a.chapter_en
        for w, h, tag in ((1440, 900, 'desktop'), (390, 844, 'mobile')):
            ctx = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1 if w > 800 else 2,
                                      has_touch=w < 800, color_scheme='light', reduced_motion='reduce')
            ctx.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
            page = ctx.new_page()
            page.on('console', lambda m, l=lang, t=tag: m.type == 'error' and problems.append(f'[{l} {t}] console: {m.text}'))
            page.on('pageerror', lambda e, l=lang, t=tag: problems.append(f'[{l} {t}] pageerror: {e}'))
            page.on('requestfailed', lambda r, l=lang, t=tag: problems.append(f'[{l} {t}] failed: {r.url}'))

            def snap(name, full=False):
                p = os.path.join(OUT, f'{lang}-{tag}-{name}.png')
                page.screenshot(path=p, full_page=full)
                shots.append(p)

            page.goto(url(lang, 'index'))
            # seed a reading history: chapters 1-11 read, the test chapter 46 % in
            page.evaluate('''([lang, chap]) => {
                const P = JSON.parse(document.getElementById('site-data').textContent).pages;
                const chs = Object.keys(P).filter(k => P[k][2] > 0).sort((a, b) => P[a][2] - P[b][2]);
                const read = {}; chs.slice(0, 11).forEach((k, i) => read[k] = 1794700000000 + i);
                localStorage.setItem('book-progress:' + lang, JSON.stringify({v: 1, read, max: {[chap]: 0.46},
                    last: {s: chap, f: 0.46, h: '', t: 1794740000000}, marks: []}));
            }''', [lang, chap])
            page.reload()
            page.evaluate('document.fonts.ready')
            snap('home')
            if not page.locator('#rp').is_visible() or not page.locator('.rp-cont').is_visible():
                problems.append(f'[{lang} {tag}] home progress panel / continue button not shown')
            if page.locator('.sb-link.is-read').count() != 11:
                problems.append(f'[{lang} {tag}] sidebar shows {page.locator(".sb-link.is-read").count()} read chapters, expected 11')
            if w < 800:
                page.locator('#rp').scroll_into_view_if_needed()
                page.evaluate('window.scrollBy(0, -140)')
                snap('home-progress')
            # "continue reading" lands on the chapter
            page.locator('.rp-cont').click()
            page.wait_for_load_state('load')
            if not page.url.split('#')[0].endswith(f'/{chap}.html'):
                problems.append(f'[{lang} {tag}] continue button went to {page.url}')
            page.evaluate('document.fonts.ready')
            page.evaluate('window.scrollTo(0, 0)')
            if not page.locator('#read-tog').is_visible() or page.locator('.ph-meta .rt').count() != 1:
                problems.append(f'[{lang} {tag}] chapter read time / read toggle missing')
            hb = page.locator('article.content h2[id] .hbm')
            if hb.count() < 2:
                (notes if lang == 'en' else problems).append(f'[{lang} {tag}] fewer than two bookmarkable headings on {chap}')
            else:
                h2 = page.locator('article.content h2[id]').nth(1)
                h2.scroll_into_view_if_needed()
                hb.nth(1).click()
                n = page.evaluate(f"JSON.parse(localStorage.getItem('book-progress:{lang}')).marks.length")
                if n != 1 or hb.nth(1).get_attribute('aria-pressed') != 'true':
                    problems.append(f'[{lang} {tag}] bookmarking a heading did not stick')
                page.evaluate("document.querySelectorAll('article.content h2[id]')[1].scrollIntoView({block: 'start'}); window.scrollBy(0, -200)")
                page.wait_for_timeout(250)
                if 'scaleX(0)' == page.evaluate("document.querySelector('.rbar i').style.transform"):
                    problems.append(f'[{lang} {tag}] reading progress bar did not move')
                snap('chapter-progress')
                page.evaluate('window.scrollTo(0, 0)')
                page.wait_for_timeout(150)
                snap('chapter-head')
                page.locator('#my-btn').click()
                page.wait_for_timeout(200)
                if page.locator('#mk-list li').count() != 1:
                    problems.append(f'[{lang} {tag}] bookmark not listed in the panel')
                snap('my-reading')
                page.keyboard.press('Escape')
                page.wait_for_timeout(100)
                if not page.locator('#my-dlg').is_hidden():
                    problems.append(f'[{lang} {tag}] my-reading panel did not close on Escape')
            page.goto(url(lang, chap))
            page.evaluate('document.fonts.ready')
            figs = page.locator('figure img.zoomable')
            if figs.count() == 0:
                # e.g. a translation still pending: no figures to zoom
                notes.append(f'[{lang} {tag}] {chap} has no figures; lightbox step skipped')
                snap('chapter-figure')
            else:
                fig = figs.first
                fig.scroll_into_view_if_needed()
                page.evaluate('window.scrollBy(0, -120)')
                page.wait_for_timeout(300)
                snap('chapter-figure')
                fig.click()
                page.wait_for_selector('.lb:not([hidden])')
                page.wait_for_timeout(250)
                snap('zoom-open')
                if w > 800:
                    box = page.locator('.lb-stage').bounding_box()
                    page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
                    for _ in range(4):
                        page.mouse.wheel(0, -240)
                    page.wait_for_timeout(150)
                else:
                    page.locator('.lb-bar [data-a="in"]').click()
                    page.locator('.lb-bar [data-a="in"]').click()
                page.wait_for_timeout(150)
                zoom = page.locator('.lb-zoomv').inner_text()
                if zoom.strip() == '100%':
                    problems.append(f'[{lang} {tag}] lightbox did not zoom')
                snap('zoom-zoomed')
                page.keyboard.press('Escape')
                page.wait_for_selector('.lb', state='hidden')
            if w < 800:
                page.locator('#menu-btn').click()
                page.wait_for_timeout(350)
                snap('menu-open')
                page.keyboard.press('Escape')
                page.wait_for_timeout(300)
            else:
                page.locator('#menu-btn').click()
                page.wait_for_timeout(200)
                snap('sidebar-collapsed')
                page.locator('#menu-btn').click()
            page.locator('#theme-btn').click()
            page.wait_for_timeout(200)
            page.evaluate('window.scrollTo(0, 0)')
            snap('dark-chapter')
            page.goto(url(lang, 'index'))
            if page.evaluate('document.documentElement.dataset.theme') != 'dark':
                problems.append(f'[{lang} {tag}] dark theme not persisted')
            snap('dark-home')
            page.keyboard.press('/')
            page.wait_for_selector('#search-dlg:not([hidden])')
            page.keyboard.type('BlueStore' if lang == 'en' else 'نوشتن deferred')
            page.wait_for_timeout(600)
            n = page.locator('#search-results li').count()
            if n == 0:
                problems.append(f'[{lang} {tag}] search returned nothing')
            snap('search')
            page.keyboard.press('Escape')
            page.evaluate("localStorage.setItem('book-theme','light')")
            # code copy button and language switch exist on the chapter page
            page.goto(url(lang, chap))
            if page.locator('.code').count() and page.locator('.code .copy').count() == 0:
                problems.append(f'[{lang}] no copy buttons on {chap}')
            other = page.locator('.lang-btn').get_attribute('href')
            if not other.endswith(f'/{chap}.html'):
                problems.append(f'[{lang}] language switch points to {other}')
            ctx.close()
    if not (a.sims_only or a.ui_only):
        # gamification: seed a believable history, then shoot the dashboard, heatmap, badges,
        # flashcards, quiz, level-up toast and certificate (fa; dark dashboard too)
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, color_scheme='light', reduced_motion='no-preference')
        ctx.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
        page = ctx.new_page()
        page.on('console', lambda m: m.type == 'error' and problems.append(f'[game] console: {m.text}'))
        page.on('pageerror', lambda e: problems.append(f'[game] pageerror: {e}'))

        def gsnap(name, full=False, el=None):
            p = os.path.join(OUT, f'fa-{name}.png')
            (page.locator(el).screenshot(path=p, style='.topbar, .g-toasts { visibility: hidden !important; }') if el else page.screenshot(path=p, full_page=full))
            shots.append(p)
        page.goto(url('fa', 'index'))
        page.evaluate(SEED, ['fa', 'خواننده‌ی نمونه'])
        page.reload()   # first load awards the badges this history has earned
        page.wait_for_timeout(300)
        # park XP two points below level 8 so one reviewed card shows the level-up celebration
        page.evaluate("(() => { const P = JSON.parse(localStorage.getItem('book-progress:fa')); P.g.xp = 2698; const w = P.g.wk; if (w) { w.c = {sec: 9, ch: 1, cards: 12, gd: 3, mc: 7, min: 55, algo: 4}; } localStorage.setItem('book-progress:fa', JSON.stringify(P)); })()")
        page.goto(url('fa', 'progress'))
        page.wait_for_timeout(700)
        gsnap('desktop-progress', full=True)
        n_badges, n_cells = page.locator('.badge').count(), page.locator('.heat i').count()
        if n_badges < 25:
            problems.append(f'[game] badge gallery shows {n_badges} badges')
        if n_cells < 7 * 17:
            problems.append(f'[game] heatmap has {n_cells} cells')
        if page.locator('.badge:not(.t0)').count() < 5:
            problems.append('[game] seeded history unlocked fewer than 5 badges')
        if 'نگهبان' in page.inner_text('.g-level') or 'RGW' not in page.inner_text('.g-level'):
            problems.append('[game] level card does not show level 7 (RGW)')
        if page.locator('.paths li.done .btn').count() < 1:
            problems.append('[game] completed path has no certificate button')
        gsnap('desktop-heatmap', el='.g-sec:has(.heat)')
        gsnap('desktop-badges', el='#gm-badges')
        # lab medals: 23 in the gallery, locked until that lab is used; the lab page shows its own
        page.evaluate("(() => { const P = JSON.parse(localStorage.getItem('book-progress:fa')); P.g.sims = { crush: 2, mclock: 1, cephx: 1 }; localStorage.setItem('book-progress:fa', JSON.stringify(P)); })()")
        page.reload()
        page.wait_for_timeout(500)
        n_lm, n_lm_on = page.locator('#gm-labmedals .badge').count(), page.locator('#gm-labmedals .badge:not(.t0)').count()
        if n_lm != 23 or n_lm_on != 3:
            problems.append(f'[game] lab medals: {n_lm} shown, {n_lm_on} earned (expected 23 and 3)')
        if page.locator('#gm-labmedals .badge:not(.t0)').first.locator('b').inner_text() == '':
            problems.append('[game] lab medal has no name')
        gsnap('desktop-lab-medals', el='#gm-labmedals')
        page.goto(url('fa', 'lab-mclock'))
        page.wait_for_timeout(400)
        if page.locator('#lab-medal.on').count() != 1:
            problems.append('[game] lab page does not show its earned medal')
        gsnap('lab-mclock-medal', el='#lab-medal')
        page.goto(url('fa', 'lab-scrub'))
        page.wait_for_timeout(400)
        if page.locator('#lab-medal.off').count() != 1:
            problems.append('[game] lab page does not show its locked medal')
        page.evaluate("(() => { const P = JSON.parse(localStorage.getItem('book-progress:fa')); P.g.xp = 2698; localStorage.setItem('book-progress:fa', JSON.stringify(P)); })()")
        page.goto(url('fa', 'progress'))
        page.wait_for_timeout(300)
        # opt-out hides every game element
        page.locator('#gs-on').click()
        if not page.locator('#g-chip').is_hidden() or page.locator('#gm-badges').is_visible():
            problems.append('[game] switching gamification off left game UI visible')
        page.locator('#gs-on').click()
        # flashcards: reveal, rate (crosses into level 8)
        page.goto(url('fa', 'review'))
        page.wait_for_selector('.flash')
        gsnap('desktop-review-card')
        page.keyboard.press(' ')
        page.wait_for_timeout(500)
        if not page.locator('.f-a').is_visible():
            problems.append('[game] flashcard answer did not reveal')
        gsnap('desktop-review-answer')
        page.keyboard.press('3')
        page.wait_for_timeout(700)
        if page.locator('.g-toast.level').count() != 1:
            problems.append('[game] no level-up toast after crossing the threshold')
        gsnap('desktop-levelup')
        if page.evaluate("JSON.parse(localStorage.getItem('book-progress:fa')).g.srs['q1-1'].b") != 3:
            problems.append('[game] rating a card did not move it to the next Leitner box')
        # glossary quiz
        page.locator('#tab-quiz').click()
        page.wait_for_selector('.qz-o')
        page.locator('.qz-o').first.click()
        page.wait_for_timeout(300)
        if page.locator('.qz-o.right').count() != 1:
            problems.append('[game] quiz did not mark the right answer')
        gsnap('desktop-quiz')
        # chapter-end quiz card and certificate
        page.goto(url('fa', a.chapter_fa))
        page.locator('.quiz-cta').scroll_into_view_if_needed()
        page.evaluate('window.scrollBy(0, -200)')
        page.wait_for_timeout(300)
        gsnap('desktop-chapter-quiz')
        page.goto(url('fa', 'certificate') + '?p=2')
        page.wait_for_timeout(300)
        if page.locator('#cert').count() != 1 or 'خواننده‌ی نمونه' not in page.inner_text('#cert'):
            problems.append('[game] certificate for a completed path did not render the stored name')
        gsnap('desktop-certificate', full=True)
        page.locator('#theme-btn').click()
        page.goto(url('fa', 'progress'))
        page.wait_for_timeout(500)
        gsnap('desktop-dark-progress')
        page.evaluate("localStorage.setItem('book-theme','light')")
        ctx.close()
        ctx = browser.new_context(viewport={'width': 390, 'height': 844}, device_scale_factor=2, has_touch=True, color_scheme='light', reduced_motion='reduce')
        ctx.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
        page = ctx.new_page()
        page.on('console', lambda m: m.type == 'error' and problems.append(f'[game mobile] console: {m.text}'))
        page.on('pageerror', lambda e: problems.append(f'[game mobile] pageerror: {e}'))
        page.goto(url('fa', 'index'))
        page.evaluate(SEED, ['fa', 'خواننده‌ی نمونه'])
        page.reload()
        page.wait_for_timeout(300)
        page.goto(url('fa', 'progress'))
        page.wait_for_timeout(500)
        gsnap('mobile-progress')
        page.goto(url('fa', 'review'))
        page.wait_for_selector('.flash')
        page.keyboard.press(' ')
        page.wait_for_timeout(200)
        gsnap('mobile-review')
        ctx.close()
        # full motion once: entrance animations, scroll reveal and hero counters must settle without errors
        ctx = browser.new_context(viewport={'width': 1440, 'height': 900}, color_scheme='dark', reduced_motion='no-preference')
        ctx.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
        page = ctx.new_page()
        page.on('console', lambda m: m.type == 'error' and problems.append(f'[motion] console: {m.text}'))
        page.on('pageerror', lambda e: problems.append(f'[motion] pageerror: {e}'))
        page.goto(url('fa', 'index'))
        page.wait_for_timeout(1800)
        got = page.evaluate("[...document.querySelectorAll('.stats b[data-n]')].map(b => b.textContent.replace(/[۰-۹]/g, c => '۰۱۲۳۴۵۶۷۸۹'.indexOf(c)) === b.dataset.n)")
        if not got or not all(got):
            problems.append('[motion] hero counters did not settle on their final values')
        p = os.path.join(OUT, 'fa-desktop-motion-home.png')
        page.screenshot(path=p)
        shots.append(p)
        page.evaluate('window.scrollTo(0, document.documentElement.scrollHeight)')
        page.wait_for_timeout(900)
        if page.locator('.rv').count() and not page.locator('.rv.in').count():
            problems.append('[motion] scroll reveal never revealed anything')
        ctx.close()
    # interactive lab: drive every simulator once; desktop fa, one mobile, one dark, en, print media and no-JS fallback
    SIMS = ['crush', 'placement', 'pgcalc', 'ecprofile', 'peering', 'bluestore', 'rgwput', 'striping']
    HIDE = '.topbar, .g-toasts, .totop { visibility: hidden !important; }'

    def sim_ctx(w=1440, h=900, scheme='light', js=True, tag='sim'):
        c = browser.new_context(viewport={'width': w, 'height': h}, device_scale_factor=1 if w > 800 else 2, has_touch=w < 800,
                                color_scheme=scheme, reduced_motion='reduce', java_script_enabled=js)
        c.route('http*://**', lambda r: (problems.append(f'network request {r.request.url}'), r.abort()))
        pg = c.new_page()
        pg.on('console', lambda m: m.type == 'error' and problems.append(f'[{tag}] console: {m.text}'))
        pg.on('pageerror', lambda e: problems.append(f'[{tag}] pageerror: {e}'))
        return c, pg

    def ssnap(pg, name, el='.sim-slot'):
        p = os.path.join(OUT, f'{name}.png')
        pg.locator(el).first.screenshot(path=p, style=HIDE)
        shots.append(p)

    def mounted(pg, name):
        try:
            pg.wait_for_selector(f'.sim-slot.sim-on[data-sim="{name}"] > .sim .sim-out > *', timeout=5000)
            return True
        except Exception:  # noqa: BLE001
            problems.append(f'[sim {name}] simulator did not mount')
            return False

    def drive(pg, name):
        """One meaningful interaction per simulator, with a check that the output reacted."""
        box = pg.locator(f'.sim-slot[data-sim="{name}"] > .sim')
        if name == 'crush':
            box.locator('.cr-tg[data-act="out"]').nth(4).click()
            pg.wait_for_timeout(150)
            if box.locator('.cr-pgs li.chg').count() == 0 or box.locator('.sim-stat.hot').count() == 0:
                problems.append('[sim crush] marking an OSD out moved no PG')
        elif name == 'placement':
            box.locator('[data-set="pl_alg"][data-v="list"]').click()
            pg.wait_for_timeout(150)
            if 'bucket default (list)' not in box.locator('.pl-steps').inner_text() or box.locator('.pl-cmp tr.cur').count() != 1:
                problems.append('[sim placement] choosing list did not redraw the CRUSH draws and the comparison')
            box.locator('select[data-k="chg"]').select_option('out')
            pg.wait_for_timeout(300)
            if box.locator('.pl-cmp tbody tr').count() != 5:
                problems.append('[sim placement] marking an OSD out did not compare the five algorithms')
            box.locator('[data-set="pl_mode"][data-v="rbd"]').click()
            pg.wait_for_timeout(150)
            box.locator('select[data-k="sc"]').select_option('4')
            box.locator('select[data-k="su"]').select_option(str(64 << 10))
            pg.wait_for_timeout(300)
            txt = box.locator('.sim-out').inner_text()
            if box.locator('.pl-ot').count() != 2 or 'rbd_header.' not in txt or 'rbd_data.' not in txt or box.locator('.pl-ot').first.locator('tbody tr').count() < 2:
                problems.append('[sim placement] RBD mode did not list the striped data objects and the metadata objects')
            box.locator('.pl-ot [data-act="plx"]').first.click()
            pg.wait_for_timeout(200)
            if box.locator('.pl-xp .pl-step').count() != 5:
                problems.append('[sim placement] the Steps button of an RBD object did not open its five steps')
            box.locator('[data-set="pl_ptype"][data-v="ec"]').click()
            pg.wait_for_timeout(200)
            if 'allow_ec_overwrites' not in box.locator('.sim-out').inner_text():
                problems.append('[sim placement] an erasure-coded RBD data pool did not show allow_ec_overwrites')
            box.locator('.pl-ot [data-act="plx"]').first.click()
            pg.wait_for_timeout(200)
            if box.locator('.pl-xp .pl-step').count() != 6 or box.locator('.pl-xp .pl-grid').count() != 1:
                problems.append('[sim placement] an RBD object in an erasure-coded pool did not show its shards and stripes')
            box.locator('[data-set="pl_mode"][data-v="obj"]').click()
            pg.wait_for_timeout(200)
            for i in (3, 4, 5):
                box.locator(f'.cr-tg[data-act="down"][data-fid="d{i}"]').click()
                pg.wait_for_timeout(120)
            txt = box.locator('.sim-out').inner_text()
            if box.locator('.pl-sh td.none').count() == 0 or '2147483647' not in txt or box.locator('.pl-cmp').count() != 2:
                problems.append('[sim placement] down OSDs in an erasure-coded pool did not leave NONE holes or compare EC with replicated')
        elif name == 'pgcalc':
            box.locator('input[data-k="osds"]').fill('120')
            pg.wait_for_timeout(450)
            if '۲۴۰۰۰' not in box.locator('.sim-out').inner_text() and '24000' not in box.locator('.sim-out').inner_text():
                problems.append('[sim pgcalc] the PG budget did not follow the OSD count')
        elif name == 'ecprofile':
            box.locator('select[data-k="plugin"]').select_option('clay')
            pg.wait_for_timeout(150)
            if 'd / (d − k + 1)' not in box.locator('.sim-formula').inner_text():
                problems.append('[sim ecprofile] choosing CLAY did not change the repair formula')
        elif name == 'peering':
            box.locator('select[data-k="sc"]').select_option('divergent')
            for _ in range(5):
                box.locator('[data-act="next"]').click()
            pg.wait_for_timeout(150)
            if box.locator('.ps-gone').count() != 1 or box.locator('.ps-tree li.cur').inner_text() != 'GetMissing':
                problems.append('[sim peering] the divergent scenario did not reach merge_log')
        elif name == 'bluestore':
            box.locator('select[data-k="preset"]').select_option('s6u')
            box.locator('[data-act="next"]').click()
            box.locator('[data-act="next"]').click()
            pg.wait_for_timeout(150)
            if box.locator('.sim-seq .st.cur').count() != 1 or 'head_read' not in box.locator('.sim-step').inner_text():
                problems.append('[sim bluestore] the unaligned overwrite did not show the read of head/tail')
        elif name == 'rgwput':
            box.locator('[data-set="mode"][data-v="multipart"]').click()
            pg.wait_for_timeout(150)
            if box.locator('.rg-objs li.ns-multipart').count() != 2:
                problems.append('[sim rgwput] 10 MiB in 5 MiB parts did not give two __multipart_ objects')
        elif name == 'striping':
            rows = box.locator('.sim-t tbody tr').count()
            if rows != 4 or 'rbd_data.10226b8b4567.0000000000000003' not in box.locator('.sim-t').inner_text():
                problems.append('[sim striping] the book example (4 MiB, 64 KiB × 4, 300000 at 1000000) did not touch objects 0-3')
        # the information panel opens from the keyboard
        info = box.locator('[data-act="__info"]')
        info.focus()
        pg.keyboard.press('Enter')
        if info.get_attribute('aria-expanded') != 'true' or not box.locator('.sim-info').is_visible():
            problems.append(f'[sim {name}] info toggle does not open from the keyboard')
        pg.keyboard.press('Enter')

    ctx, page = sim_ctx(tag='sim')
    page.goto(url('fa', 'index'))
    page.evaluate("localStorage.removeItem('book-progress:fa')")
    page.goto(url('fa', 'lab'))
    for _th in page.locator('.lab-thumb').all():
        _th.scroll_into_view_if_needed()
    page.evaluate('window.scrollTo(0, 0)')
    notes.append(f'[lab cards] {check_cards(page, "lab fa")}')
    p = os.path.join(OUT, 'fa-desktop-lab.png'); page.screenshot(path=p, full_page=True); shots.append(p)
    page.goto(url('en', 'lab'))
    for _th in page.locator('.lab-thumb').all():
        _th.scroll_into_view_if_needed()
    check_cards(page, 'lab en')
    p = os.path.join(OUT, 'en-desktop-lab.png'); page.screenshot(path=p, full_page=True); shots.append(p)
    page.goto(url('fa', 'lab'))
    for n in SIMS:
        page.goto(url('fa', f'lab-{n}'))
        if not mounted(page, n):
            continue
        if page.locator('.sim-tools a.sim-btn').count():
            problems.append(f'[sim {n}] the lab page links to itself')
        drive(page, n)
        page.wait_for_timeout(100)
        ssnap(page, f'fa-desktop-sim-{n}')
    got = page.evaluate("(() => { const P = JSON.parse(localStorage.getItem('book-progress:fa') || '{}'); return P.g ? [Object.keys(P.g.sims || {}).length, P.g.xp, (P.g.badges || {}).lab || 0] : [0, 0, 0]; })()")
    notes.append(f'lab gamification after one visit each: sims={got[0]} xp={got[1]} lab badge tier={got[2]}')
    if got[0] != len(SIMS) or got[1] < 5 * len(SIMS) or not got[2]:
        problems.append(f'[sim] using every simulator did not record sims/XP/badge: {got}')
    # a simulator embedded in a chapter, and the same page as printed
    page.goto(url('fa', a.chapter_fa))
    page.locator('.sim-slot').first.scroll_into_view_if_needed()
    if not mounted(page, 'bluestore'):
        pass
    elif page.locator('.sim-slot .sim-fallback').first.is_visible():
        problems.append('[sim] the static fallback stays visible next to the live simulator')
    ssnap(page, 'fa-desktop-chapter-sim-bluestore')
    page.emulate_media(media='print')
    if not page.locator('.sim-slot .sim-fallback').first.is_visible() or page.locator('.sim-slot > .sim').first.is_visible():
        problems.append('[sim] print media does not swap the live simulator for the static figure')
    ssnap(page, 'fa-print-sim-bluestore')
    page.emulate_media(media='screen')
    page.goto(url('fa', 'index'))
    page.locator('#lab').scroll_into_view_if_needed()
    page.wait_for_timeout(200)
    check_cards(page, 'home fa')
    ssnap(page, 'fa-desktop-home-lab', el='#lab')
    page.goto(url('en', 'lab-crush'))
    if mounted(page, 'crush'):
        drive(page, 'crush')
        ssnap(page, 'en-desktop-sim-crush')
    ctx.close()
    # one mobile, one dark
    ctx, page = sim_ctx(390, 844, tag='sim mobile')
    page.goto(url('fa', 'lab-crush'))
    if mounted(page, 'crush'):
        if page.evaluate('document.documentElement.scrollWidth') > 392:
            problems.append('[sim mobile] the CRUSH playground overflows a 390 px screen')
        drive(page, 'crush')
        p = os.path.join(OUT, 'fa-mobile-sim-crush.png'); page.screenshot(path=p, full_page=True); shots.append(p)
    ctx.close()
    ctx, page = sim_ctx(scheme='dark', tag='sim dark')
    page.goto(url('fa', 'lab'))
    for _th in page.locator('.lab-thumb').all():
        _th.scroll_into_view_if_needed()
    page.evaluate('window.scrollTo(0, 0)')
    check_cards(page, 'lab fa dark')
    p = os.path.join(OUT, 'fa-dark-lab.png'); page.screenshot(path=p, full_page=True); shots.append(p)
    page.goto(url('fa', 'lab-peering'))
    if mounted(page, 'peering'):
        drive(page, 'peering')
        ssnap(page, 'fa-dark-sim-peering')
    page.goto(url('fa', 'lab-bluestore'))
    if mounted(page, 'bluestore'):
        drive(page, 'bluestore')
        ssnap(page, 'fa-dark-sim-bluestore')
    ctx.close()
    # without JavaScript the static figure is the content
    ctx, page = sim_ctx(js=False, tag='sim nojs')
    page.goto(url('fa', 'lab-rgwput'))
    if not page.locator('.sim-fallback .sim-seq').count():
        problems.append('[sim nojs] the static RGW figure has no sequence diagram')
    ssnap(page, 'fa-nojs-sim-rgwput')
    ctx.close()
    browser.close()
finish()
