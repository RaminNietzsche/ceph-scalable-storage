"""Suggested reading paths: the single data source (references/reading-paths.yaml) and what is derived from it.

Used by tools/check_paths.py (validator), tools/build_site.py (paths.html, the on-page "next step" hint
and paths-data.js), tools/build_book.py and tools/export_pandoc.py (the table in the preface), and
tools/booklib/llmstxt.py (the Markdown alternates).

A path is a list of stages; a stage is a list of steps. A step names one thing to read or do by `ref`:

    chN         a whole chapter                 (ch7)
    sec-NN-K    a top-level section             (sec-07-6), or a sub-section (sec-07-10-4)
    appX        an appendix, by its print id    (appJ)
    lab:NAME    an interactive lab of the site  (lab:balancer)

The reading time of a chapter or section is computed from the Markdown source with the formula of the
web edition (words per minute, plus 3 s per line of code and 12 s per figure), so the numbers move with
the text. Labs and the generated appendices have no source to count; their `min` is written in the data.
`hands_on` adds the minutes a step needs for its exercises.
"""
from __future__ import annotations

import glob
import os
import re

import yaml

DATA = os.path.join('references', 'reading-paths.yaml')
WPM = {'fa': 170, 'en': 220}
APPS = {'appA': 'glossary', 'appB': 'cheatsheet', 'appC': 'troubleshooting', 'appD': 'versions', 'appF': 'answers',
        'appG': 'bibliography', 'appH': 'algorithms', 'appI': 'changes', 'appJ': 'upgrade', 'appK': 'security',
        'appL': 'multisite-dr'}
APP_SRC = {'appC': 'appendices/troubleshooting.md', 'appD': 'appendices/versions.md',
           'appJ': 'appendices/upgrade.md', 'appK': 'appendices/security.md',
           'appL': 'appendices/multisite-dr.md'}
# Pandoc heading ids of the appendices that have one (the print book uses the keys)
PANDOC_APP = {'appB': 'appB', 'appI': 'app-changes', 'appJ': 'app-upgrade', 'appK': 'app-security', 'appL': 'app-multisite-dr'}
UI_KEYS = ('paths_nav', 'paths_title', 'paths_intro', 'paths_fig_alt', 'paths_fig_cap', 'paths_pick', 'paths_steps', 'paths_time',
           'paths_prereq', 'paths_after', 'paths_optional', 'paths_lab', 'paths_then', 'paths_follow', 'paths_following',
           'paths_note', 'paths_hint_label', 'paths_hint_on', 'paths_hint_next', 'paths_hint_opt', 'paths_hint_min',
           'paths_hint_done', 'paths_hint_all', 'paths_hint_stop', 'paths_hint_path', 'paths_read_n', 'paths_home_t', 'paths_home_d')
ICONS = {'cluster', 'deploy', 'ops', 'alert', 'code', 'layers', 'cpu', 'book', 'route'}
STORAGE_KEY = 'book-path'

_HEAD = re.compile(r'^(#{1,6}) (.*?)(?:\s+\{#([\w:.-]+)[^}]*\})?\s*$')
_FENCE = re.compile(r'^\s*(```|~~~)')
_CH_FILE = re.compile(r'^(\d\d)-.*\.md$')
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def load(root: str) -> dict:
    with open(os.path.join(root, DATA), encoding='utf-8') as fh:
        return yaml.safe_load(fh) or {}


def ui_strings(root: str, lang: str) -> dict:
    """The texts of the web page, from the `ui` section of the data."""
    return load(root)['ui'][lang]


def loc(n, lang: str) -> str:
    return str(n).translate(FA_DIGITS) if lang == 'fa' else str(n)


# ------------------------------------------------------------------ references
def parse_ref(ref: str) -> tuple[str, str] | None:
    """(kind, value) of a step ref, or None when it is not one of the four shapes."""
    if not isinstance(ref, str):
        return None
    m = re.fullmatch(r'ch(\d+)', ref)
    if m:
        return 'chapter', str(int(m.group(1)))
    if re.fullmatch(r'sec-\d\d-\d+(?:-\d+)*', ref):
        return 'section', ref
    if ref in APPS:
        return 'appendix', ref
    m = re.fullmatch(r'lab:([a-z0-9]+)', ref)
    if m:
        return 'lab', m.group(1)
    return None


def chapter_files(root: str, lang: str) -> dict[int, str]:
    out = {}
    for p in sorted(glob.glob(os.path.join(root, 'content', lang, 'chapters', '[0-9][0-9]-*.md'))):
        out[int(_CH_FILE.match(os.path.basename(p)).group(1))] = p
    return out


def lab_names(root: str) -> list[str]:
    """Slugs of the interactive labs (lab-NAME.html): the built-in simulators and the lazily loaded labs."""
    src = open(os.path.join(root, 'tools', 'build_site.py'), encoding='utf-8').read()
    m = re.search(r"^SIM_NAMES = \[([^\]]*)\]", src, re.M)
    names = re.findall(r"'([a-z0-9]+)'", m.group(1)) if m else []
    labs = yaml.safe_load(open(os.path.join(root, 'templates', 'site', 'sims', 'labs.yaml'), encoding='utf-8')) or []
    return names + [n for n in labs if n not in names]


def split_body(text: str) -> list[str]:
    lines = text.split('\n')
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() == '---':
                return lines[i + 1:]
    return lines


def headings(lines: list[str]) -> list[tuple[int, int, int, str]]:
    """(line index, level, ...) of every heading outside code fences: (index, level, anchor-or-'', title)."""
    out, inc = [], False
    for i, ln in enumerate(lines):
        if _FENCE.match(ln):
            inc = not inc
            continue
        if inc:
            continue
        m = _HEAD.match(ln)
        if m:
            out.append((i, len(m.group(1)), m.group(3) or '', m.group(2).strip()))
    return out


def source_lines(root: str, lang: str, ref: str) -> list[str] | None:
    """The Markdown lines a ref covers, or None for refs without a source (labs, generated appendices)."""
    kind, val = parse_ref(ref) or (None, None)
    if kind == 'chapter':
        p = chapter_files(root, lang).get(int(val))
        return split_body(open(p, encoding='utf-8').read()) if p else None
    if kind == 'appendix':
        rel = APP_SRC.get(val)
        return split_body(open(os.path.join(root, 'content', lang, rel), encoding='utf-8').read()) if rel else None
    if kind == 'section':
        n = int(val.split('-')[1])
        p = chapter_files(root, lang).get(n)
        if not p:
            return None
        lines = split_body(open(p, encoding='utf-8').read())
        hs = headings(lines)
        for k, (i, lvl, anchor, _t) in enumerate(hs):
            if anchor == val:
                end = len(lines)
                for j, lvl2, _a, _t2 in hs[k + 1:]:
                    if lvl2 <= lvl:
                        end = j
                        break
                return lines[i:end]
    return None


def section_title(root: str, lang: str, ref: str) -> str | None:
    kind, val = parse_ref(ref) or (None, None)
    if kind != 'section':
        return None
    p = chapter_files(root, lang).get(int(val.split('-')[1]))
    if not p:
        return None
    for _i, _lvl, anchor, title in headings(split_body(open(p, encoding='utf-8').read())):
        if anchor == val:
            return title
    return None


def reading_minutes(lines: list[str], lang: str) -> int:
    """Reading time of Markdown lines, by the formula of the web edition (build_site.reading_minutes)."""
    words = code = figs = 0
    inc = False
    for ln in lines:
        if _FENCE.match(ln):
            inc = not inc
            continue
        if inc:
            code += 1
            continue
        if re.match(r'^!\[', ln) or re.match(r'^\[!\[', ln):
            figs += 1
            ln = re.sub(r'!\[[^\]]*\]\([^)]*\)(\{#[^}]*\})?', '', ln)
        ln = re.sub(r'^:::.*$', '', ln)
        ln = re.sub(r'\{#[^}]*\}', '', ln)
        ln = re.sub(r'^[#>|\-*\s]+', '', ln)
        ln = re.sub(r'\|[-:\s|]+\|?', ' ', ln) if set(ln) <= set('-:| ') else ln.replace('|', ' ')
        words += len(ln.split())
    return max(1, round(words / WPM[lang] + code * 3 / 60 + figs * 12 / 60))


def round5(n: int) -> int:
    return max(5, int(5 * round(n / 5)))


def step_minutes(root: str, lang: str, step: dict) -> int:
    """Minutes shown for a step: the `min` of the data, else the reading time of its source rounded to 5,
    plus the `hands_on` minutes of a step that has exercises."""
    if step.get('min'):
        base = int(step['min'])
    else:
        lines = source_lines(root, lang, step['ref'])
        base = round5(reading_minutes(lines, lang)) if lines else 5
    return base + int(step.get('hands_on') or 0)


def all_steps(path: dict):
    for st in path.get('stages', []):
        for s in st.get('steps', []):
            yield s


def totals(root: str, lang: str, path: dict) -> tuple[int, int]:
    """(required minutes, optional minutes) of a path."""
    req = opt = 0
    for s in all_steps(path):
        m = step_minutes(root, lang, s)
        if s.get('optional'):
            opt += m
        else:
            req += m
    return req, opt


def fmt_dur(mins: int, lang: str) -> str:
    """'45 min', '6 h', '6 h 30 min' / '۴۵ دقیقه'، '۶ ساعت'، '۶ ساعت و ۳۰ دقیقه' (rounded to 5 minutes)."""
    mins = round5(mins)
    h, m = divmod(mins, 60)
    if lang == 'fa':
        if h and m:
            return f'{loc(h, lang)} ساعت و {loc(m, lang)} دقیقه'
        return f'{loc(h, lang)} ساعت' if h else f'{loc(m, lang)} دقیقه'
    if h and m:
        return f'{h} h {m} min'
    return f'{h} h' if h else f'{m} min'


def fmt_total(req: int, opt: int, lang: str) -> str:
    base = fmt_dur(req, lang)
    if opt >= 5:
        return f'{base} (+ {fmt_dur(opt, lang)} ' + ('اختیاری' if lang == 'fa' else 'optional') + ')'
    return base


# ------------------------------------------------------------------ the print book
def chapters_of(path: dict) -> list[tuple[str, str]]:
    """The reading order of a path as ('ch', 7) / ('app', 'appJ') items, each chapter or appendix once."""
    out, seen = [], set()
    for s in all_steps(path):
        kind, val = parse_ref(s['ref'])
        if kind == 'chapter':
            item = ('ch', int(val))
        elif kind == 'section':
            item = ('ch', int(val.split('-')[1]))
        elif kind == 'appendix':
            item = ('app', val)
        else:
            continue
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def preface_markdown(root: str, lang: str, flavor: str, ui: dict) -> list[str]:
    """Markdown lines for the preface's reading-path table.

    flavor 'print' links chapters as #chN and appendices by their print ids; 'pandoc' uses the heading ids of the
    Pandoc export (#chNN, and only the appendices that have one); 'text' has no links (the Markdown alternates
    for readers that are not the book). Appendices without a target are plain text."""
    data = load(root)
    head = ['| ' + ' | '.join(data['preface_cols'][lang]) + ' |', '|---|---|---|']
    rows = []
    for p in data['paths']:
        items = []
        for kind, val in chapters_of(p):
            if kind == 'ch':
                tgt = None if flavor == 'text' else (f'ch{val}' if flavor == 'print' else f'ch{val:02d}')
                lab = f'{ui["chapter_word"]}\u00a0{loc(val, lang)}'
                items.append(f'[{lab}](#{tgt})' if tgt else lab)
            else:
                letter = ui['app'][APPS[val]][0]
                label = f'{ui["appendix"]} {letter}'
                tgt = None if flavor == 'text' else (val if flavor == 'print' else PANDOC_APP.get(val))
                items.append(f'[{label}](#{tgt})' if tgt else label)
        req, opt = totals(root, lang, p)
        sep = ' ← ' if lang == 'fa' else ' → '
        rows.append(f'| **{p["short"][lang]}**: {p["who"][lang]} | ' + sep.join(items)
                    + f' | {fmt_total(req, opt, lang)} |')
    return head + rows


PLACEHOLDER = '@READING_PATHS@'


def expand_placeholder(lines: list[str], root: str, lang: str, flavor: str, ui: dict) -> list[str]:
    """Replace the placeholder line of the preface by the reading-path table."""
    out: list[str] = []
    for ln in lines:
        if ln.strip() == PLACEHOLDER:
            out += preface_markdown(root, lang, flavor, ui)
        else:
            out.append(ln)
    return out


def expand_text(text: str, root: str, lang: str, flavor: str) -> str:
    """The same for a whole file's text (the Markdown alternates of the web edition)."""
    if PLACEHOLDER not in text:
        return text
    ui = yaml.safe_load(open(os.path.join(root, 'content', lang, 'ui.yaml'), encoding='utf-8'))
    return '\n'.join(expand_placeholder(text.split('\n'), root, lang, flavor, ui))


# ------------------------------------------------------------------ the web edition
def _esc(s) -> str:
    import html
    return html.escape(str(s), quote=True)


def site_model(root: str, lang: str, ui: dict, S: dict, simy: dict, ids: dict, pages: dict, text_of) -> list[dict]:
    """The paths with every step resolved to a page of the built site.

    ids      source anchor -> (slug, id on the page), as build_site.py collects them
    pages    slug -> Page (title_text, nav_text, sections)
    text_of  HTML fragment -> plain text
    Raises SystemExit naming the ref when one cannot be resolved (check_paths.py catches this earlier)."""
    data = load(root)
    out = []
    for p in data['paths']:
        stages, n = [], 0
        for st in p['stages']:
            steps = []
            for s in st['steps']:
                n += 1
                kind, val = parse_ref(s['ref'])
                if kind == 'lab':
                    slug, href, label = f'lab-{val}', f'lab-{val}.html', S['paths_lab']
                    title = simy[f'{val}_t']
                elif ref_missing(s['ref'], ids):
                    raise SystemExit(f'reading paths: {s["ref"]} (path {p["id"]}) has no page in the web edition')
                else:
                    key = f'ch{val}' if kind == 'chapter' else s['ref']
                    slug, nid = ids[key]
                    href = f'{slug}.html' + (f'#{nid}' if nid else '')
                    pg = pages[slug]
                    if kind == 'chapter':
                        label = f'{ui["chapter_word"]} {loc(val, lang)}'
                        title = pg.title_text
                    elif kind == 'appendix':
                        label = f'{ui["appendix"]} {ui["app"][APPS[val]][0]}'
                        title = pg.title_text.split(': ', 1)[-1] if ': ' in pg.title_text and pg.title_text.startswith(ui['appendix']) else pg.title_text
                    else:
                        ch, rest = val.split('-')[1], '.'.join(str(int(x)) for x in val.split('-')[2:])
                        label = (f'§{int(ch)}.{rest}' if lang == 'en' else f'بخش {loc(int(ch), lang)}.{loc(rest, lang)}')
                        title = next((text_of(h) for lvl, sid, h in pg.sections if sid == nid), '') or section_title(root, lang, val) or val
                steps.append({'n': n, 'ref': s['ref'], 'kind': kind, 'slug': slug, 'href': href, 'label': label, 'title': title.strip(),
                              'min': step_minutes(root, lang, s), 'optional': bool(s.get('optional')), 'why': s['why'][lang]})
            stages.append({'title': st['title'][lang], 'steps': steps})
        req, opt = totals(root, lang, p)
        out.append({'id': p['id'], 'icon': p['icon'], 'short': p['short'][lang], 'title': p['title'][lang], 'who': p['who'][lang],
                    'prereq': p['prereq'][lang], 'outcomes': p['outcomes'][lang], 'next': p.get('next') or [], 'stages': stages,
                    'req': req, 'opt': opt, 'n': n})
    return out


def ref_missing(ref: str, ids: dict) -> bool:
    kind, val = parse_ref(ref)
    key = f'ch{val}' if kind == 'chapter' else ref
    return key not in ids


def page_html(model: list[dict], S: dict, lang: str, ICON: dict, figure_html: str = '') -> str:
    """The article of paths.html."""
    e = _esc
    short = {m['id']: m['short'] for m in model}
    cards = []
    for m in model:
        cards.append(
            f'<a class="hcard role rtp-card" href="#path-{m["id"]}"><span class="hc-ic">{ICON[m["icon"]]}</span>'
            f'<span class="hc-tag">{e(fmt_dur(m["req"], lang))}</span>'
            f'<span class="hc-t">{e(m["short"])}</span><span class="hc-d">{e(m["who"])}</span>'
            f'<span class="hc-go">{e(S["paths_steps"].format(n=loc(m["n"], lang)))} {ICON["arrow"]}</span></a>')
    secs = []
    for m in model:
        tot = fmt_total(m['req'], m['opt'], lang)
        out = [f'<section class="rtp" aria-labelledby="path-{m["id"]}" data-path="{m["id"]}">'
               f'<header class="rtp-head"><span class="rtp-ic">{ICON[m["icon"]]}</span><div><h2 id="path-{m["id"]}">{e(m["title"])}</h2>'
               f'<p class="rtp-who">{e(m["who"])}</p></div></header>'
               f'<div class="rtp-meta"><span class="rtp-tm">{ICON["clock"]}{e(S["paths_time"])}: {e(tot)}</span>'
               f'<span class="rtp-cnt">{e(S["paths_steps"].format(n=loc(m["n"], lang)))}</span>'
               f'<span class="rtp-prog" data-total="{m["n"]}" hidden></span>'
               f'<button type="button" class="btn rtp-follow" data-follow="{m["id"]}" aria-pressed="false" hidden>'
               f'{ICON["route"]}<span class="rtp-f-off">{e(S["paths_follow"])}</span><span class="rtp-f-on">{e(S["paths_following"])}</span></button></div>'
               f'<div class="rtp-cols"><div class="rtp-box"><h3>{e(S["paths_prereq"])}</h3><p>{e(m["prereq"])}</p></div>'
               f'<div class="rtp-box"><h3>{e(S["paths_after"])}</h3><ul>' + ''.join(f'<li>{e(o)}</li>' for o in m['outcomes']) + '</ul></div></div>']
        for st in m['stages']:
            out.append(f'<div class="rtp-stage"><h3>{e(st["title"])}</h3><ol class="rtp-steps">')
            for s in st['steps']:
                opt = f'<span class="rtp-opt">{e(S["paths_optional"])}</span>' if s['optional'] else ''
                out.append(
                    f'<li class="rtp-step{" is-opt" if s["optional"] else ""}"><span class="rtp-n" aria-hidden="true">{loc(s["n"], lang)}</span>'
                    f'<div class="rtp-line"><span class="rtp-kind">{e(s["label"])}</span>'
                    f'<a class="rtp-link" href="{e(s["href"])}" data-slug="{e(s["slug"])}">{e(s["title"])}</a>{opt}'
                    f'<span class="rtp-min">{ICON["clock"]}{e(fmt_dur(s["min"], lang))}</span></div>'
                    f'<p class="rtp-why">{e(s["why"])}</p></li>')
            out.append('</ol></div>')
        if m['next']:
            links = ' · '.join(f'<a href="#path-{x}">{e(short[x])}</a>' for x in m['next'] if x in short)
            out.append(f'<p class="rtp-next"><b>{e(S["paths_then"])}</b> {links}</p>')
        out.append('</section>')
        secs.append(''.join(out))
    return (f'<article class="content app app-paths" id="top"><header class="page-head"><h1>{e(S["paths_title"])}</h1></header>'
            f'<p class="lead">{e(S["paths_intro"])}</p>{figure_html}'
            f'<h2 class="rtp-pick-h" id="pick">{e(S["paths_pick"])}</h2><div class="hgrid roles rtp-pick">{"".join(cards)}</div>'
            f'{"".join(secs)}<p class="rtp-note">{e(S["paths_note"])}</p></article>')


def hint_data(model: list[dict], S: dict, lang: str) -> dict:
    """What paths.js needs on every page: the steps of every path, in order, with page URLs and titles."""
    return {
        'lang': lang, 'key': STORAGE_KEY,
        's': {k: S[k] for k in UI_KEYS if k.startswith('paths_hint_') or k == 'paths_read_n'},
        'paths': [{'id': m['id'], 't': m['short'],
                   'steps': [{'slug': s['slug'], 'href': s['href'], 't': s['title'], 'm': s['min'], 'o': int(s['optional'])}
                             for st in m['stages'] for s in st['steps']]} for m in model],
    }
