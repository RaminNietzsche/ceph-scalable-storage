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
                                      has_touch=w < 800, color_scheme='light')
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
            page.evaluate('document.fonts.ready')
            snap('home')
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
    browser.close()
json.dump({'screenshots': shots, 'problems': problems, 'notes': notes}, open(os.path.join(OUT, 'report.json'), 'w'), indent=1, ensure_ascii=False)
for p in problems:
    print('shoot_site:', p)
print(f'shoot_site: {len(shots)} screenshots in {OUT}, {len(problems)} problems')
sys.exit(1 if problems else 0)
