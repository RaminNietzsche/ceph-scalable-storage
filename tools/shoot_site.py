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
