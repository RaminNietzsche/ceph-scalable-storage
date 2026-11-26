#!/usr/bin/env python3
"""Validate references/reading-paths.yaml, the data of the suggested reading paths.

* schema: ids, icons, fa and en text for every field, outcome lists of the same length, `next` ids that exist;
* every step's ref exists in BOTH editions: chapter file, section anchor (inside the chapter it names),
  appendix id, lab (built-in or lazy, with a title string in both languages);
* no ref twice in a path, every path has required steps, `min` is set where the time cannot be counted;
* the text follows the prose rules (Persian orthography, double spaces, codespell on the English), has no
  Persian in en or Latin-only text in fa, and none of the words the book never uses;
* the preface of both editions has the @READING_PATHS@ placeholder once;
* the paths figure (figures/app/f10_reading_paths) names every path, in fa and en.

Usage: tools/check_paths.py
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import readingpaths as rp  # noqa: E402

LANGS = ('fa', 'en')
RULES_FA = [
    (re.compile('[\u064A\u0643]'), 'Arabic ي/ك instead of Persian ی/ک'),
    (re.compile(r'(?<![\w\u200c])(ن?می) (?=[\u0600-\u06FF]{2,})'), '"می"/"نمی" prefix should use ZWNJ'),
    (re.compile(r' [،؛؟]'), 'space before Persian punctuation'),
]
RULES_ALL = [
    (re.compile(r'\w\)?\^[\w({-]'), 'bare ^ exponent outside math'),
    (re.compile(r'\S  +\S'), 'double space'),
    (re.compile(r'[ \t]+$'), 'trailing whitespace'),
]
PERSIAN = re.compile('[\u0600-\u06FF]')
FIG = 'figures/app/f10_reading_paths'
errs: list[str] = []
en_text: list[str] = []


def err(where: str, msg: str) -> None:
    errs.append(f'{where}: {msg}')


def text_ok(val, lang: str, where: str, collect: bool = True) -> None:
    if not isinstance(val, str) or not val.strip():
        err(where, f'empty {lang} text')
        return
    for rx, msg in RULES_ALL + (RULES_FA if lang == 'fa' else []):
        if rx.search(val):
            err(where, f'{lang}: {msg} -> {val!r}')
    if lang == 'en':
        if PERSIAN.search(val):
            err(where, f'en text contains Persian: {val!r}')
        if collect:
            en_text.append(val)
    elif not PERSIAN.search(val):
        err(where, f'fa text has no Persian letters: {val!r}')


def pair(obj, where: str) -> None:
    if not isinstance(obj, dict) or set(obj) != set(LANGS):
        err(where, f'expected exactly the keys fa and en, got {obj!r}')
        return
    for lang in LANGS:
        text_ok(obj[lang], lang, where)


def int_field(step: dict, key: str, where: str) -> None:
    v = step.get(key)
    if v is not None and (not isinstance(v, int) or isinstance(v, bool) or not 1 <= v <= 240):
        err(where, f'{key} must be an integer between 1 and 240, got {v!r}')


def main() -> int:
    data = rp.load(ROOT)
    paths = data.get('paths')
    if not isinstance(paths, list) or not paths:
        print('check-paths: paths must be a non-empty list', file=sys.stderr)
        return 1
    cols = data.get('preface_cols') or {}
    for lang in LANGS:
        if not isinstance(cols.get(lang), list) or len(cols[lang]) != 3:
            err('preface_cols', f'{lang}: expected three column titles')
        else:
            for c in cols[lang]:
                text_ok(c, lang, 'preface_cols')

    ui_data = data.get('ui') or {}
    for lang in LANGS:
        got = ui_data.get(lang) or {}
        for k in rp.UI_KEYS:
            if k not in got:
                err('ui', f'{lang}: missing key {k}')
            else:
                text_ok(got[k], lang, f'ui.{k}')
        for k in got:
            if k not in rp.UI_KEYS:
                err('ui', f'{lang}: unknown key {k}')
        for k in ('paths_steps', 'paths_hint_min'):
            if '{n}' not in got.get(k, ''):
                err('ui', f'{lang}: {k} needs {{n}}')
        if '{path}' not in got.get('paths_hint_on', '') or '{i}' not in got.get('paths_hint_on', ''):
            err('ui', f'{lang}: paths_hint_on needs {{path}}, {{i}} and {{n}}')
        if '{path}' not in got.get('paths_hint_done', ''):
            err('ui', f'{lang}: paths_hint_done needs {{path}}')
        if '{r}' not in got.get('paths_read_n', '') or '{n}' not in got.get('paths_read_n', ''):
            err('ui', f'{lang}: paths_read_n needs {{r}} and {{n}}')

    chapters = {lang: rp.chapter_files(ROOT, lang) for lang in LANGS}
    labs = set(rp.lab_names(ROOT))
    ui = {lang: yaml.safe_load(open(os.path.join(ROOT, 'content', lang, 'ui.yaml'), encoding='utf-8')) for lang in LANGS}
    simstr = {lang: yaml.safe_load(open(os.path.join(ROOT, 'templates', 'site', 'sims', f'strings-{lang}.yaml'), encoding='utf-8'))
              for lang in LANGS}
    anchors = {lang: {} for lang in LANGS}  # chapter number -> anchors of that chapter's headings
    for lang in LANGS:
        for n, p in chapters[lang].items():
            lines = rp.split_body(open(p, encoding='utf-8').read())
            anchors[lang][n] = {a for _i, _l, a, _t in rp.headings(lines) if a}

    ids = [p.get('id') for p in paths]
    n_steps = 0
    covered: set[int] = set()
    for p in paths:
        pid = p.get('id')
        w = f'path:{pid}'
        if not isinstance(pid, str) or not re.fullmatch(r'[a-z0-9]+', pid):
            err(w, f'bad id {pid!r}')
            continue
        if ids.count(pid) > 1:
            err(w, 'duplicate id')
        if p.get('icon') not in rp.ICONS:
            err(w, f'icon must be one of {sorted(rp.ICONS)}, got {p.get("icon")!r}')
        for key in ('short', 'title', 'who', 'prereq'):
            pair(p.get(key), f'{w}.{key}')
        for lang in LANGS:
            if len(p.get('short', {}).get(lang, '')) > 40:
                err(w, f'short.{lang} is longer than 40 characters (it is used in the figure and in the hint)')
        oc = p.get('outcomes') or {}
        if set(oc) != set(LANGS) or not all(isinstance(oc[x], list) for x in LANGS):
            err(w, 'outcomes needs fa and en lists')
        else:
            if len(oc['fa']) != len(oc['en']):
                err(w, f'outcomes: fa has {len(oc["fa"])} items, en has {len(oc["en"])}')
            if not 3 <= len(oc['fa']) <= 6:
                err(w, 'outcomes: expected 3 to 6 items')
            for lang in LANGS:
                for i, t in enumerate(oc[lang]):
                    text_ok(t, lang, f'{w}.outcomes[{i}]')
        for nid in p.get('next') or []:
            if nid not in ids or nid == pid:
                err(w, f'next: unknown or self id {nid!r}')
        seen: set[str] = set()
        required = 0
        stages = p.get('stages') or []
        if not stages:
            err(w, 'no stages')
        for si, st in enumerate(stages):
            sw = f'{w}.stages[{si}]'
            pair(st.get('title'), f'{sw}.title')
            if not st.get('steps'):
                err(sw, 'no steps')
            for ti, s in enumerate(st.get('steps') or []):
                n_steps += 1
                ww = f'{sw}.steps[{ti}]'
                ref = s.get('ref')
                pr = rp.parse_ref(ref)
                if not pr:
                    err(ww, f'bad ref {ref!r}')
                    continue
                ww += f'({ref})'
                if ref in seen:
                    err(ww, 'ref appears twice in this path')
                seen.add(ref)
                kind, val = pr
                if kind == 'chapter':
                    for lang in LANGS:
                        if int(val) not in chapters[lang]:
                            err(ww, f'chapter {val} not found in content/{lang}')
                    covered.add(int(val))
                elif kind == 'section':
                    n = int(val.split('-')[1])
                    covered.add(n)
                    for lang in LANGS:
                        if val not in anchors[lang].get(n, set()):
                            err(ww, f'anchor {val} is not a heading of chapter {n} in content/{lang}')
                elif kind == 'appendix':
                    for lang in LANGS:
                        if rp.APPS[val] not in ui[lang].get('app', {}):
                            err(ww, f'appendix {val} missing from content/{lang}/ui.yaml')
                        if val in rp.APP_SRC and not os.path.exists(os.path.join(ROOT, 'content', lang, rp.APP_SRC[val])):
                            err(ww, f'appendix source {rp.APP_SRC[val]} missing in {lang}')
                else:
                    if val not in labs:
                        err(ww, f'unknown lab {val!r}')
                    for lang in LANGS:
                        if not simstr[lang].get(f'{val}_t'):
                            err(ww, f'lab {val} has no title string in sims/strings-{lang}.yaml')
                pair(s.get('why'), f'{ww}.why')
                if s.get('optional') is not None and not isinstance(s['optional'], bool):
                    err(ww, 'optional must be true or false')
                if not s.get('optional'):
                    required += 1
                int_field(s, 'min', ww)
                int_field(s, 'hands_on', ww)
                has_source = kind in ('chapter', 'section') or ref in rp.APP_SRC
                if not has_source and not s.get('min'):
                    err(ww, 'a lab or an appendix without a Markdown source needs `min`')
                if has_source and s.get('min'):
                    err(ww, '`min` is only for steps without a source; use hands_on for exercises')
                if kind == 'lab' and s.get('hands_on'):
                    err(ww, 'a lab has `min`, not hands_on')
        if required < 3:
            err(w, f'only {required} required step(s)')
        for lang in LANGS:
            req, opt = rp.totals(ROOT, lang, p)
            if not 30 <= req <= 600:
                err(w, f'{lang}: required time {req} min is outside 30..600')

    # preface placeholder
    for lang in LANGS:
        txt = open(os.path.join(ROOT, 'content', lang, 'front', 'preface.md'), encoding='utf-8').read()
        if txt.count('@READING_PATHS@') != 1:
            err('preface', f'content/{lang}/front/preface.md must contain @READING_PATHS@ exactly once')

    # figure: every path is named, fa and en
    fig_fa = os.path.join(ROOT, FIG + '.mmd')
    fig_en = os.path.join(ROOT, FIG + '.en.mmd')
    if os.path.exists(fig_fa):
        txt_fa = open(fig_fa, encoding='utf-8').read()
        txt_en = open(fig_en, encoding='utf-8').read() if os.path.exists(fig_en) else ''
        if not txt_en:
            err('figure', f'{FIG}.en.mmd is missing (run make figures)')
        for p in paths:
            sh = p.get('short', {})
            if sh.get('fa') and sh['fa'] not in txt_fa:
                err('figure', f'{FIG}.mmd does not name the path {p["id"]} ({sh["fa"]!r})')
            if txt_en and sh.get('en') and sh['en'] not in txt_en:
                err('figure', f'{FIG}.en.mmd does not name the path {p["id"]} ({sh["en"]!r})')
    else:
        err('figure', f'{FIG}.mmd is missing')

    cs = shutil.which('codespell') or os.path.expanduser('~/.local/bin/codespell')
    if cs and os.path.exists(cs) and en_text:
        with tempfile.NamedTemporaryFile('w', suffix='.txt', encoding='utf-8', delete=False) as tf:
            tf.write('\n'.join(en_text) + '\n')
            tmp = tf.name
        try:
            r = subprocess.run([cs, '--ignore-words', os.path.join(ROOT, '.codespell-ignore'), tmp], capture_output=True, text=True)
            for line in r.stdout.splitlines():
                if line.strip():
                    err('codespell', line.replace(tmp, rp.DATA))
        finally:
            os.unlink(tmp)

    missing = sorted(set(range(1, 43)) - covered)
    print(f'check-paths: {len(paths)} paths, {n_steps} steps, {len(covered)} of 42 chapters used, {len(errs)} error(s)')
    if missing and not errs:
        print('  chapters on no path (information): ' + ', '.join(str(n) for n in missing))
    for e in errs[:60]:
        print(' ', e)
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
