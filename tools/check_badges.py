#!/usr/bin/env python3
"""Validate the badge art (references/badges.yaml) against the game layer.

* schema: version, count, categories (frame shape, field colours, accent), tier metals, shared glyphs;
* exactly `count` badges (52), unique ids, a known category, tier "tiered" or a single metal 1-3,
  tiered badges only in hexagon categories (the tier banner lives there), every glyph parses, stays on
  its 24 x 24 grid and is drawn for one badge only;
* the same badges as templates/site/game.js (BADGES plus one lab_NAME medal per entry of LABS), with
  the same tier kind, single metal and hidden flag, and lab medals exactly in the labs category;
* every badge has a name and a description in both editions of templates/site/game.yaml, every
  category has its cat_ label, the Persian follows the orthography rules and the English has no Persian;
* the asset renders (tools/render_badges.py), the page template loads it before game.js, site.css has
  the BADGE-ART block, and docs/GAMIFICATION.md states the badge count.

Usage: tools/check_badges.py
"""
from __future__ import annotations

import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
import render_badges as rb  # noqa: E402

ERR: list[str] = []
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')
RULES_FA = [
    (re.compile('[\u064A\u0643]'), 'Arabic ي/ك instead of Persian ی/ک'),
    (re.compile(r'(?<![\w\u200c])(ن?می) (?=[\u0600-\u06FF]{2,})'), '"می"/"نمی" prefix should use ZWNJ'),
    (re.compile(r' [،؛؟]'), 'space before Persian punctuation'),
]
RULES_ALL = [(re.compile(r'\S  +\S'), 'double space'), (re.compile(r'^\s|\s$'), 'leading or trailing space')]


def err(msg: str) -> None:
    ERR.append(msg)


def read(*p: str) -> str:
    with open(os.path.join(ROOT, *p), encoding='utf-8') as f:
        return f.read()


def game_js_badges() -> dict:
    """id -> (tier spec, hidden) from the BADGES table and the LABS list of game.js."""
    js = read('templates', 'site', 'game.js')
    m = re.search(r'var BADGES = \[(.*?)\n  \];', js, re.S)
    if not m:
        err('game.js: BADGES table not found')
        return {}
    out = {}
    row = re.compile(r"^\s*\['(\w+)', '(\w+)', (\[[^\]]*\]|\d), function \([^)]*\) \{.*\}(?:, (\d))?\],?$")
    for line in m.group(1).strip().splitlines():
        r = row.match(line)
        if not r:
            err(f'game.js: unparsed BADGES row: {line.strip()[:80]}')
            continue
        out[r.group(1)] = ('tiered' if r.group(3).startswith('[') else int(r.group(3)), r.group(4) == '1')
    labs = re.search(r'var LABS = \[([^\]]*)\]', js)
    lab_tier = re.search(r"BADGES\.push\(\['lab_' \+ n, 'l_' \+ n, (\d),", js)
    if not labs or not lab_tier:
        err('game.js: LABS list or lab medal push not found')
    else:
        for n in re.findall(r"'(\w+)'", labs.group(1)):
            out['lab_' + n] = (int(lab_tier.group(1)), False)
    return out


def main() -> None:
    d = rb.load()
    if d.get('version') != 1:
        err('version must be 1')
    cats = d.get('categories') or {}
    for cid, c in cats.items():
        if c.get('shape') not in rb.SHAPES:
            err(f'category {cid}: unknown shape {c.get("shape")!r} (one of {", ".join(rb.SHAPES)})')
        f = c.get('field') or []
        if len(f) != 2 or not all(HEX.match(str(x)) for x in f):
            err(f'category {cid}: field needs two #rrggbb colours')
        if not HEX.match(str(c.get('accent', ''))):
            err(f'category {cid}: accent must be #rrggbb')
    metals = d.get('metals') or {}
    for t in (1, 2, 3):
        if len(metals.get(t) or []) != 3 or not all(HEX.match(str(x)) for x in metals.get(t) or []):
            err(f'metals: tier {t} needs three #rrggbb stops')
    if len(metals.get('holo') or []) < 2:
        err('metals: holo needs at least two stops')
    for k in ('lock', 'secret'):
        if not (d.get('glyphs') or {}).get(k):
            err(f'glyphs: shared glyph {k!r} missing')

    badges = d.get('badges') or []
    if len(badges) != d.get('count'):
        err(f'{len(badges)} badges, but count says {d.get("count")}')
    if d.get('count') != 52:
        err(f'count is {d.get("count")}, the book promises 52 badges')
    seen, art = {}, {}
    used_cats = set()
    for b in badges:
        bid = b.get('id', '?')
        if bid in seen:
            err(f'{bid}: duplicate id')
        seen[bid] = b
        if b.get('cat') not in cats:
            err(f'{bid}: unknown category {b.get("cat")!r}')
            continue
        used_cats.add(b['cat'])
        t = b.get('tier')
        if t not in ('tiered', 1, 2, 3):
            err(f'{bid}: tier must be "tiered" or 1, 2, 3, not {t!r}')
        if t == 'tiered' and cats[b['cat']]['shape'] != 'hex':
            err(f'{bid}: tiered badges need a hex category (the tier banner is drawn there)')
        if 'hidden' in b and not isinstance(b['hidden'], bool):
            err(f'{bid}: hidden must be true or false')
        if b.get('hidden') and b['cat'] != 'secret':
            err(f'{bid}: hidden badges belong in the secret category')
        if b['cat'] == 'secret' and not b.get('hidden'):
            err(f'{bid}: the secret category holds hidden badges only')
        if (b['cat'] == 'labs') != bid.startswith('lab_'):
            err(f'{bid}: lab_NAME medals and only they go in the labs category')
        g = b.get('glyph')
        if not isinstance(g, list) or not g:
            err(f'{bid}: glyph missing')
            continue
        try:
            markup = rb.glyph_svg(g)
        except ValueError as e:
            err(f'{bid}: {e}')
            continue
        box = rb.glyph_bounds(g)
        if box and (box[0] < -0.5 or box[1] < -0.5 or box[2] > 24.5 or box[3] > 24.5):
            err(f'{bid}: glyph leaves the 24 x 24 grid {box}')
        if markup in art:
            err(f'{bid}: same glyph as {art[markup]}')
        art[markup] = bid
    for cid in cats:
        if cid not in used_cats:
            err(f'category {cid}: no badge uses it')

    js = game_js_badges()
    for bid in sorted(set(js) - set(seen)):
        err(f'{bid}: in game.js but has no art in references/badges.yaml')
    for bid in sorted(set(seen) - set(js)):
        err(f'{bid}: has art but game.js does not define it')
    for bid in sorted(set(js) & set(seen)):
        spec, hidden = js[bid]
        if spec != seen[bid].get('tier'):
            err(f'{bid}: tier {seen[bid].get("tier")!r} here, {spec!r} in game.js')
        if hidden != bool(seen[bid].get('hidden')):
            err(f'{bid}: hidden is {bool(seen[bid].get("hidden"))} here, {hidden} in game.js')

    gy = yaml.safe_load(read('templates', 'site', 'game.yaml'))
    for lang in ('fa', 'en'):
        names, s = gy[lang].get('badges') or {}, gy[lang].get('s') or {}
        texts = []
        for bid in seen:
            v = names.get(bid)
            if not (isinstance(v, list) and len(v) == 2 and all(isinstance(x, str) and x.strip() for x in v)):
                err(f'game.yaml {lang}: badge {bid} needs [name, description]')
            else:
                texts += [(f'badge {bid}', x) for x in v]
        for bid in names:
            if bid not in seen:
                err(f'game.yaml {lang}: badge {bid} has a name but no art')
        for cid in cats:
            if not str(s.get(f'cat_{cid}', '')).strip():
                err(f'game.yaml {lang}: category label cat_{cid} missing')
            else:
                texts.append((f'cat_{cid}', s[f'cat_{cid}']))
        for k in ('gal_page', 'gal_intro', 'gal_open', 'gal_cat', 'gal_state', 'gal_all', 'gal_earned', 'gal_locked', 'gal_shown', 'gal_none', 'gal_when', 'gal_new', 'gal_tier_of'):
            if not str(s.get(k, '')).strip():
                err(f'game.yaml {lang}: gallery string {k} missing')
            else:
                texts.append((k, s[k]))
        for where, txt in texts:
            for rx, why in RULES_ALL + (RULES_FA if lang == 'fa' else []):
                if rx.search(txt):
                    err(f'game.yaml {lang} {where}: {why}: {txt!r}')
            if lang == 'en' and re.search('[\u0600-\u06FF]', txt):
                err(f'game.yaml en {where}: Persian text in the English edition')
            if lang == 'fa' and not re.search('[\u0600-\u06FF]', txt):
                err(f'game.yaml fa {where}: no Persian text')

    try:
        asset = rb.asset_js(d)
        for bid in seen:
            if f'id=\\"bdg-g-{bid}\\"' not in asset:
                err(f'asset: no symbol for {bid}')
        if 'window.BadgeArt' not in asset:
            err('asset: renderer missing (templates/site/badges.js)')
    except Exception as e:  # noqa: BLE001
        err(f'asset does not render: {e}')
    page = read('templates', 'site', 'page.html')
    a, g = page.find('assets/badges.js'), page.find('assets/game.js')
    if a < 0 or g < 0 or a > g:
        err('templates/site/page.html must load ../assets/badges.js before ../assets/game.js')
    css = read('templates', 'site', 'site.css')
    if '/* BADGE-ART */' not in css or '/* /BADGE-ART */' not in css:
        err('site.css: BADGE-ART block missing')
    if f'{len(badges)} badges' not in read('docs', 'GAMIFICATION.md'):
        err(f'docs/GAMIFICATION.md does not say "{len(badges)} badges"')

    for e in ERR:
        print('check_badges:', e)
    by = {}
    for b in badges:
        by[b.get('cat')] = by.get(b.get('cat'), 0) + 1
    print(f'check_badges: {len(badges)} badges (' + ', '.join(f'{k} {v}' for k, v in by.items()) +
          f'), {sum(1 for b in badges if b.get("tier") == "tiered")} tiered, {sum(1 for b in badges if b.get("hidden"))} hidden; '
          + ('OK' if not ERR else f'{len(ERR)} problem(s)'))
    sys.exit(1 if ERR else 0)


if __name__ == '__main__':
    main()
