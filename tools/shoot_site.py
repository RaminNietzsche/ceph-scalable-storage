#!/usr/bin/env python3
"""Smoke-test the web edition in headless Chrome and take screenshots.

Usage: tools/shoot_site.py [--site build/site] [--out build/site-shots] [--chapter-fa SLUG] [--chapter-en SLUG]

For fa and en, at 1440 px and 390 px: home, a chapter with figures, the figure
lightbox (zoomed), the mobile menu (390 px), dark mode and search. Pages are
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


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path=chrome, args=['--no-sandbox'])
    for lang in ('fa', 'en'):
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
    # gamification: seed a believable history, then shoot the dashboard, heatmap, badges,
    # flashcards, quiz, level-up toast and certificate (fa; dark dashboard too)
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
    browser.close()
json.dump({'screenshots': shots, 'problems': problems, 'notes': notes}, open(os.path.join(OUT, 'report.json'), 'w'), indent=1, ensure_ascii=False)
for p in problems:
    print('shoot_site:', p)
print(f'shoot_site: {len(shots)} screenshots in {OUT}, {len(problems)} problems')
sys.exit(1 if problems else 0)
