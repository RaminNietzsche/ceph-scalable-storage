#!/usr/bin/env python3
"""Build the single-file HTML book (input for render_pdf.py) and the Markdown export.

Usage: tools/build_book.py --lang fa|en [--out build/fa]

Reads content/<lang>/ (chapters, front matter, appendices, answers, ui.yaml,
metadata.yaml), the shared glossary/, references/ and figures/, and writes
<out>/book.html, <out>/ix_hits.json, <out>/book.md and <out>/stats.json.
"""
from __future__ import annotations

import argparse
import collections
import glob
import html
import json
import os
import re
import string
import sys

import yaml
from PIL import Image

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.mdlower import lower, split_front_matter  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--out', default=None)
args = ap.parse_args()
LANG = args.lang
OUT = os.path.abspath(args.out or os.path.join(ROOT, 'build', LANG))
os.makedirs(OUT, exist_ok=True)
C = os.path.join(ROOT, 'content', LANG)
UI = yaml.safe_load(open(os.path.join(C, 'ui.yaml'), encoding='utf-8'))
SIMSTR = yaml.safe_load(open(os.path.join(ROOT, 'templates', 'site', 'sims', f'strings-{LANG}.yaml'), encoding='utf-8'))
META = yaml.safe_load(open(os.path.join(C, 'metadata.yaml'), encoding='utf-8'))
RTL = META.get('dir') == 'rtl'

FA = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹') if UI['digits'] == 'fa' else str.maketrans('', '')
EN = str.maketrans('۰۱۲۳۴۵۶۷۸۹', '0123456789')
fa = lambda x: str(x).translate(FA)  # noqa: E731  (localised digits)
BOOK = UI['book']
esc = lambda s: html.escape(s, quote=False)  # noqa: E731
CH = UI['chapter_word']

# ---------- glossary / references / tools ----------
GL = yaml.safe_load(open(os.path.join(ROOT, 'glossary', 'glossary.yaml'), encoding='utf-8'))
GLOSS = [(g['term'], g.get(LANG) or g.get('fa', '')) for g in GL]
REFDATA = json.load(open(os.path.join(ROOT, 'references', 'references.json'), encoding='utf-8'))
REFS = []
for it in REFDATA:
    grp = UI['ref_groups'][it['custom']['group']]
    if not REFS or REFS[-1][0] != grp:
        REFS.append((grp, []))
    REFS[-1][1].append((it['custom'].get('title-' + LANG) or it['title'], it['URL']))
TOOL_DESC = yaml.safe_load(open(os.path.join(C, 'data', 'tools.yaml'), encoding='utf-8')) or {}

# ---------- inline ----------
LATIN = re.compile(r"[A-Za-z][A-Za-z0-9_./:\-+#@&'=~*<>\[\]{}\"]*(?:(?: |\(|\) ?|, )[A-Za-z0-9\"'(][A-Za-z0-9_./:\-+#@&'=~*<>\[\]{}\"]*)*")
TOK = re.compile(r'(\*\*[^*]+\*\*|`[^`]+`)')


def prose(t):
    if not RTL:
        return esc(t)
    out = []
    pos = 0
    for m in LATIN.finditer(t):
        run = m.group(0)
        while run and (run[-1] in '.:,;' or (run[-1] == ')' and run.count('(') < run.count(')')) or (run[-1] in ' (')):
            run = run[:-1]
        if run.count('(') > run.count(')'):
            k = run.rfind('(')
            run = run[:k].rstrip()
        if not run:
            continue
        s = m.start()
        e = s + len(run)
        if s < pos:
            continue
        out.append(esc(t[pos:s]).translate(FA))
        out.append(f'\u200f<span class="en">{esc(run)}</span>\u200f')
        pos = e
    out.append(esc(t[pos:]).translate(FA))
    return ''.join(out)


RLM = '\u200f' if RTL else ''


def inline(t):
    r = []
    for p in TOK.split(t):
        if not p:
            continue
        if p.startswith('**') and p.endswith('**') and len(p) > 4:
            r.append('<strong>' + prose(p[2:-2]) + '</strong>')
        elif p.startswith('`') and p.endswith('`') and len(p) > 2:
            c = p[1:-1]
            cls = ' class="nw"' if len(c) <= 26 else ''
            r.append(RLM + '<code dir="ltr"' + cls + '>' + esc(c) + '</code>' + RLM)
        else:
            q = prose(p)
            q = re.sub(r'(?<![\w*])\*([^*\s][^*]*)\*(?!\w)', r'<em>\1</em>', q)
            r.append(q)
    return ''.join(r)


# ---------- index anchors ----------
IX_TERMS = sorted([g[0] for g in GLOSS], key=len, reverse=True)
IX_RE = {t: re.compile(r'(?<![A-Za-z\-])' + re.escape(t) + r'(?:s|es)?(?![A-Za-z\-])', re.I if len(t) > 3 else 0) for t in IX_TERMS}
ix_hits = collections.defaultdict(list)
ix_n = [0]


def ix_anchors(text, chap):
    a = ''
    text = re.sub(r'`[^`]*`', '', text)
    for t in IX_TERMS:
        if IX_RE[t].search(text):
            ix_n[0] += 1
            aid = f'ix{ix_n[0]}'
            ix_hits[t].append((chap, aid))
            a += f'<span class="ixa" id="{aid}"></span>'
    return a


ICONS = {'tip': '💡', 'warn': '⚠', 'note': '✎', 'try': '▶', 'deep': '◆', 'debug': '✚'}
CALL = {'!' + k.upper(): (UI['callouts'][k], k, ICONS[k]) for k in ICONS}


def figure_path(p):
    """Resolve figures/chNN/name.png to the language variant if one exists."""
    full = os.path.join(ROOT, p)
    stem, ext = os.path.splitext(full)
    for cand in (f'{stem}.{LANG}{ext}', f'{stem}.{LANG}.svg', full):
        if os.path.exists(cand):
            return cand
    return full


# ---------- block renderer ----------
figs = []
toc = []
cmds = []
APPFIG = [0]
ALGOS = []
ANS = collections.defaultdict(list)
BIB = collections.defaultdict(list)


def cells(row):
    return [c.replace('\\|', '|') for c in re.split(r'(?<!\\)\|', row)]


def render(lines, chap=None, md=None):
    H = []
    i = 0
    n1 = n2 = 0
    figno = 0

    def mdw(s):
        if md is not None:
            md.append(s)
    while i < len(lines):
        l = lines[i]
        if not l.strip():
            i += 1
            continue
        if l.startswith('!SIGN '):
            H.append(f'<p class="sign">{inline(l[6:])}</p>')
            mdw('\n*' + l[6:] + '*\n')
            i += 1
            continue
        if l.startswith('!Q '):
            j = i
            items = []
            while j < len(lines) and lines[j].startswith('!Q '):
                q = lines[j][3:]
                a = lines[j + 1][3:] if j + 1 < len(lines) and lines[j + 1].startswith('!A ') else ''
                items.append((q, a))
                j += 2 if a else 1
            base = len(ANS[chap])
            ANS[chap] += items
            H.append('<ol class="qs">' + ''.join(f'<li><span class="oln">{fa(base + k + 1)}.</span> {ix_anchors(q, chap) if chap else ""}{inline(q)}</li>' for k, (q, a) in enumerate(items)) + f'</ol><p class="ansref">{UI["answers_ref"]}</p>')
            mdw('\n' + '\n'.join(f'{base + k + 1}. {q}' for k, (q, a) in enumerate(items)) + '\n\n' + UI['answers_ref_md'] + '\n')
            i = j
            continue
        if l.startswith('!SRC '):
            j = i
            items = []
            while j < len(lines) and lines[j].startswith('!SRC '):
                items.append(lines[j][5:].split('|', 1))
                j += 1
            BIB[chap] += items
            H.append('<ul class="refs">' + ''.join(f'<li>{inline(t)}<br/><a class="url" href="{u}">{esc(u)}</a></li>' for t, u in items) + '</ul>')
            mdw('\n' + '\n'.join(f'- {t}: <{u}>' for t, u in items) + '\n')
            i = j
            continue
        if l.startswith('!BOX'):
            j = i + 1
            buf = []
            while not lines[j].startswith('!ENDBOX'):
                buf.append(lines[j])
                j += 1
            H.append('<div class="box">' + ''.join(f'<p>{inline(b)}</p>' for b in buf) + '</div>')
            mdw('\n' + '\n'.join('> ' + b for b in buf) + '\n')
            i = j + 1
            continue
        if l.startswith('!SUM'):
            lab = l[4:].strip() or UI['summary_default']
            j = i + 1
            buf = []
            while not lines[j].startswith('!ENDSUM'):
                buf.append(lines[j])
                j += 1
            items = ''.join(f'<li>{inline(b[2:])}</li>' if b.startswith('- ') else f'<p>{inline(b)}</p>' for b in buf)
            H.append(f'<div class="sum"><div class="lab">{inline(lab)}</div><ul>{items}</ul></div>')
            mdw(f'\n> **{lab}**\n>\n' + '\n'.join('> ' + b for b in buf) + '\n')
            i = j + 1
            continue
        if l.startswith('```'):
            lang = l[3:].strip()
            j = i + 1
            buf = []
            while not lines[j].startswith('```'):
                buf.append(lines[j])
                j += 1
            if chap:
                for b in buf:
                    s = b.strip()
                    if s.startswith('$ '):
                        s = s[2:]
                    m = re.match(r'(ceph-objectstore-tool|ceph-bluestore-tool|ceph-kvstore-tool|ceph-dencoder|ceph-volume|cephfs-journal-tool|radosgw-admin|osdmaptool|crushtool|monmaptool|cephadm|ceph|rados|rbd|kubectl)\s+(\S+)', s)
                    if m and not s.endswith(':'):
                        cmds.append((m.group(1), m.group(2), s.split(' #')[0].rstrip(), chap))
            cls = 'code long' if len(buf) > 28 else 'code'
            lab = f'<span class="lang">{esc(lang)}</span>' if lang else ''
            H.append(f'<div class="{cls}">{lab}<pre>' + esc('\n'.join(buf)) + '</pre></div>')
            mdw('\n```' + lang + '\n' + '\n'.join(buf) + '\n```\n')
            i = j + 1
            continue
        if l.startswith('!TABLE'):
            hdr = cells(l[6:].strip())
            j = i + 1
            rows = []
            while not lines[j].startswith('!ENDTABLE'):
                rows.append(cells(lines[j]))
                j += 1
            t = '<table><thead><tr>' + ''.join(f'<th>{inline(h)}</th>' for h in hdr) + '</tr></thead><tbody>'
            for r in rows:
                t += '<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>'
            H.append(t + '</tbody></table>')
            mdw('\n| ' + ' | '.join(hdr) + ' |\n|' + '---|' * len(hdr) + '\n' + '\n'.join('| ' + ' | '.join(r) + ' |' for r in rows) + '\n')
            i = j + 1
            continue
        if l.startswith('!ALGO '):
            nm, src, cx = (l[6:].split('|') + ['', ''])[:3]
            nm, src, cx = nm.strip(), src.strip(), cx.strip()
            ALGOS.append((chap, f'algo{len(ALGOS) + 1}', nm, src, cx))
            aid = ALGOS[-1][1]
            H.append(f'<div class="call algo" id="{aid}"><div class="lab"><span class="ic">∑</span> {UI["algorithm"]}: {inline(nm)}</div><p>{UI["algo_src"]}: <code>{esc(src)}</code></p><p>{UI["algo_complexity"]}: {inline(cx)}</p></div>')
            mdw(f'\n> **{UI["algorithm"]}: {nm}**  \n> {UI["algo_src"]}: `{src}`  \n> {UI["algo_complexity"]}: {cx}\n')
            i += 1
            continue
        if l.startswith('!SIM '):
            nm = l[5:].strip()
            t = SIMSTR.get(f'{nm}_t', nm)
            # the web edition mounts the simulator here; the print edition keeps a one-line pointer to it
            H.append(f'<div class="sim-slot" data-sim="{esc(nm)}"><p class="sim-print">{inline(UI["sim_print"].format(t=t))}</p></div>')
            mdw(f'\n> {UI["sim_print"].format(t=t)}\n')
            i += 1
            continue
        key = l.split(' ', 1)[0]
        if key in CALL:
            lab, cls, ic = CALL[key]
            body = [l.split(' ', 1)[1]]
            j = i + 1
            while j < len(lines) and lines[j].startswith('+ '):
                body.append(lines[j][2:])
                j += 1
            ix = ix_anchors(' '.join(body), chap) if chap else ''
            H.append(f'<div class="call {cls}">{ix}<div class="lab"><span class="ic">{ic}</span> {lab}</div>' + ''.join(f'<p>{inline(b)}</p>' for b in body) + '</div>')
            mdw(f'\n> **{lab}:** ' + '\n>\n> '.join(body) + '\n')
            i = j
            continue
        if l.startswith('!IMG '):
            path, cap = l[5:].split('|', 1)
            figno += 1
            if chap:
                fid = f'fig-{chap}-{figno}'
            else:
                APPFIG[0] += 1
                fid = f'fig-app-{APPFIG[0]}'
            apath = figure_path(path)
            w, h = Image.open(apath).size
            ar = w / h
            cls = 'wide' if ar > 1.25 else ('mid' if ar > 0.8 else 'tall')
            num = f'{fa(chap)}-{fa(figno)}' if chap else f'{UI["appendix_fig_prefix"]}-{fa(APPFIG[0])}'
            figs.append((fid, num, cap))
            H.append(f'<figure id="{fid}" class="{cls}"><img src="file://{apath}"/><figcaption><b>{UI["figure"]} {num}:</b> {inline(cap)}</figcaption></figure>')
            mdw(f'\n![{UI["figure"]} {num}: {cap}]({os.path.relpath(apath, ROOT)})\n\n*{UI["figure"]} {num}: {cap}*\n')
            i += 1
            continue
        m = re.match(r'^(#{1,4}) (.*)', l)
        if m:
            lvl = len(m.group(1))
            txt = m.group(2)
            if chap:
                if lvl == 1:
                    n1 += 1
                    n2 = 0
                    num = f'{fa(chap)}-{fa(n1)}'
                    hid = f's{chap}-{n1}'
                    toc.append((2, hid, num, txt, chap))
                elif lvl == 2:
                    n2 += 1
                    num = f'{fa(chap)}-{fa(n1)}-{fa(n2)}'
                    hid = f's{chap}-{n1}-{n2}'
                else:
                    num = ''
                    hid = ''
                ix = ix_anchors(txt, chap)
                tag = f'h{lvl + 1}'
                nm = f'<span class="num">{num}</span> ' if num else ''
                H.append(f'<{tag}' + (f' id="{hid}"' if hid else '') + f'>{ix}{nm}{inline(txt)}</{tag}>')
                mdw('\n' + '#' * (lvl + 1) + ' ' + (num.translate(EN).replace('-', '.') + ' ' if num else '') + txt + '\n')
            else:
                H.append(f'<h{lvl + 1}>{inline(txt)}</h{lvl + 1}>')
                mdw('\n' + '#' * (lvl + 1) + ' ' + txt + '\n')
            i += 1
            continue
        if l.startswith('- '):
            j = i
            items = []
            while j < len(lines) and lines[j].startswith('- '):
                items.append(lines[j][2:])
                j += 1
            H.append('<ul>' + ''.join(f'<li>{ix_anchors(x, chap) if chap else ""}{inline(x)}</li>' for x in items) + '</ul>')
            mdw('\n' + '\n'.join('- ' + x for x in items) + '\n')
            i = j
            continue
        if re.match(r'^\d+\. ', l):
            j = i
            items = []
            while j < len(lines) and re.match(r'^\d+\. ', lines[j]):
                items.append(re.match(r'^(\d+)\. (.*)', lines[j]).groups())
                j += 1
            H.append('<ol>' + ''.join(f'<li><span class="oln">{fa(n)}.</span> {ix_anchors(x, chap) if chap else ""}{inline(x)}</li>' for n, x in items) + '</ol>')
            mdw('\n' + '\n'.join(f'{n}. {x}' for n, x in items) + '\n')
            i = j
            continue
        ix = ix_anchors(l, chap) if chap else ''
        H.append(f'<p>{ix}{inline(l)}</p>')
        mdw('\n' + l + '\n')
        i += 1
    return '\n'.join(H)


def load_md(path):
    fm, body = split_front_matter(open(path, encoding='utf-8').read())
    return (yaml.safe_load(fm) or {}), lower(body)


def prep(rest, n):
    ap_ = os.path.join(C, 'answers', f'{n:02d}.md')
    ans = [re.sub(r'^\d+\.\s*', '', x) for x in open(ap_, encoding='utf-8').read().strip().split('\n') if x.strip() and not x.startswith('<!--')] if os.path.exists(ap_) else []
    out = []
    mode = None
    qi = 0
    inc = False
    for x in rest:
        if x.startswith('```'):
            inc = not inc
        if not inc and (x.startswith('# ') or x.startswith('## ')):
            h = x.split(' ', 1)[1].strip()
            mode = 'q' if h.startswith(UI['review_questions']) else ('s' if h.startswith(UI['chapter_sources']) else None)
            out.append(x)
            continue
        if mode == 'q' and re.match(r'^\d+\. ', x):
            q = re.sub(r'^\d+\.\s*', '', x)
            a = ans[qi] if qi < len(ans) else ''
            qi += 1
            out.append('!Q ' + q)
            out.append('!A ' + a)
            continue
        if mode == 's' and x.startswith('- ') and 'http' in x:
            u = re.findall(r'https?://\S+', x)[-1].rstrip(').,؛،>')
            t = x[2:].replace(u, '').strip(' :-–—()<>')
            out.append('!SRC ' + (t or u) + '|' + u)
            continue
        out.append(x)
    return out


# ---------- chapters ----------
# Book parts that get a part title page before their first chapter: (first chapter, anchor id, ui.yaml key prefix).
SPEC_START = 34
PARTS = [(23, 'part-low', 'part_low'), (SPEC_START, 'part-spec', 'part_spec')]
PART_IDS = {pid for _, pid, _ in PARTS}
MD = []
body = []
chapters = []
pending = []
for path in sorted(glob.glob(os.path.join(C, 'chapters', '[0-9][0-9]-*.md'))):
    fm, rest = load_md(path)
    n = int(fm['chapter'])
    title = fm['title']
    meta = ''
    if fm.get('translation') == 'pending':
        pending.append(n)
        rest = ['!NOTE ' + UI['pending_note']]
    rest = prep(rest, n)
    chapters.append((n, title))
    toc.append((1, f'ch{n}', fa(n), title, n))
    MD.append(f'\n\n# {CH} {n}: {title}\n\n*{meta}*\n')
    inc = False
    mains = []
    for x in rest:
        if x.startswith('```'):
            inc = not inc
            continue
        if not inc and x.startswith('# '):
            mains.append(x[2:])
    chap_html = render(rest, n, MD)
    word = UI['special_word'] if n == 22 else (UI['spec_word'] if n >= SPEC_START else (UI['lower_word'] if n >= 23 else CH))
    opener = f'''<section class="chapter" id="ch{n}">
<div class="opener"><div class="ch-word">{word}</div><div class="ch-num">{fa(n)}</div><div class="rule"></div>
<h1 class="ch-title">{inline(title)}</h1><div class="ch-meta">{esc(meta)}</div>
<div class="inthis"><div class="lab">{UI["in_this_chapter"]}</div><ol>{''.join(f'<li><span class="oln">{fa(n)}-{fa(k + 1)}</span> {inline(t)}</li>' for k, t in enumerate(mains))}</ol></div></div>
<div class="chbody">{chap_html}</div></section>'''
    for pstart, pid, pkey in PARTS:
        if n == pstart:
            toc.append((1, pid, '', UI[f'{pkey}_toc'], 0))
            body.append(f'<section class="partpg" id="{pid}"><div class="pp-word">{UI[f"{pkey}_word"]}</div><h1 class="pp-title">{UI[f"{pkey}_title"]}</h1><div class="rule"></div><p class="pp-desc">{UI[f"{pkey}_desc"]}</p></section>')
            MD.append(f'\n\n# {UI[f"{pkey}_word"]}: {UI[f"{pkey}_title"]}\n\n{UI[f"{pkey}_md"]}\n')
    body.append(opener)

# ---------- appendices ----------
app = []
MDA = []
A = UI['app']


def letter_sec(aid, key, body_html):
    letter, title, short = A[key]
    app.append(f'<section class="appendix" id="{aid}"><h1 class="ap-title" data-t="{UI["appendix"]} {letter} · {short}"><span class="apn">{UI["appendix"]} {letter}</span>{title}</h1>{body_html}</section>')


letter, gtitle, gshort = A['glossary']
rows = ''.join(f'<tr><td class="ltr">{esc(e)}</td><td>{inline(p)}</td></tr>' for e, p in sorted(GLOSS, key=lambda x: x[0].lower()))
app.append(f'<section class="appendix" id="appA"><h1 class="ap-title" data-t="{UI["appendix"]} {letter} · {gshort}"><span class="apn">{UI["appendix"]} {letter}</span>{gtitle}</h1><p>{UI["glossary_intro"]}</p><table class="gloss"><thead><tr><th>{UI["glossary_cols"][0]}</th><th>{UI["glossary_cols"][1]}</th></tr></thead><tbody>{rows}</tbody></table></section>')
MDA.append(f'\n\n# {UI["appendix"]} {letter}: {gtitle}\n\n| {UI["glossary_cols"][0]} | {UI["glossary_cols"][1]} |\n|---|---|\n' + '\n'.join(f'| {e} | {p} |' for e, p in sorted(GLOSS, key=lambda x: x[0].lower())))
by = collections.OrderedDict()
seen = set()
order = ['ceph', 'rados', 'rbd', 'radosgw-admin', 'cephadm', 'ceph-volume', 'ceph-bluestore-tool', 'ceph-objectstore-tool', 'ceph-kvstore-tool', 'osdmaptool', 'crushtool', 'monmaptool', 'ceph-dencoder', 'cephfs-journal-tool', 'kubectl']
for tool, sub, line, ch in cmds:
    key = re.sub(r'\s+', ' ', line)
    if key in seen or len(key) > 110:
        continue
    seen.add(key)
    by.setdefault(tool, collections.OrderedDict()).setdefault(sub, []).append((key, ch))
letter, ctitle, cshort = A['cheatsheet']
bh = [f'<section class="appendix" id="appB"><h1 class="ap-title" data-t="{UI["appendix"]} {letter} · {cshort}"><span class="apn">{UI["appendix"]} {letter}</span>{ctitle}</h1><p>{UI["cheatsheet_intro"]}</p>']
MDA.append(f'\n\n# {UI["appendix"]} {letter}: {ctitle}\n')
for tool in sorted(by, key=lambda t: order.index(t) if t in order else 99):
    bh.append(f'<h2 class="cmdtool"><span class="en">{tool}</span> · {TOOL_DESC.get(tool, "")}</h2><table class="cmds"><tbody>')
    MDA.append(f'\n## {tool} — {TOOL_DESC.get(tool, "")}\n')
    subs = by[tool]
    for sub in sorted(subs, key=lambda s: -len(subs[s])):
        bh.append(f'<tr class="subh"><td colspan="2"><span class="en">{esc(tool)} {esc(sub)}</span></td></tr>')
        MDA.append(f'\n**{tool} {sub}**\n')
        for line, ch in subs[sub]:
            bh.append(f'<tr><td class="cmd"><code>{esc(line)}</code></td><td class="chref">{UI["chapter_ref"].format(n=fa(ch))}</td></tr>')
            MDA.append(f'- `{line}` ({UI["chapter_ref"].format(n=ch)})')
    bh.append('</tbody></table>')
bh.append('</section>')
app.append('\n'.join(bh))
for aid, key, fn in [('appC', 'troubleshooting', 'troubleshooting.md'), ('appD', 'versions', 'versions.md')]:
    afm, L = load_md(os.path.join(C, 'appendices', fn))
    if afm.get('translation') == 'pending':
        L = ['!NOTE ' + UI['pending_note']]
    m = []
    h = render(L, None, m)
    letter_sec(aid, key, h)
    MDA.append(f'\n\n# {UI["appendix"]} {A[key][0]}: {A[key][1]}\n' + '\n'.join(m))
ah = [f'<p>{UI["answers_intro"]}</p>']
MDA.append(f'\n\n# {UI["appendix"]} {A["answers"][0]}: {A["answers"][2]}\n')
for n, t in chapters:
    if not ANS[n]:
        continue
    ah.append(f'<h2>{CH} {fa(n)}: {inline(t)}</h2><ol class="ans">')
    MDA.append(f'\n## {CH} {n}: {t}\n')
    for k, (q, a) in enumerate(ANS[n]):
        ah.append(f'<li><span class="oln">{fa(k + 1)}.</span> <b>{inline(q)}</b><br/>{inline(a)}</li>')
        MDA.append(f'{k + 1}. **{q}**  \n   {a}')
    ah.append('</ol>')
letter_sec('appF', 'answers', ''.join(ah))
allu = set()
bh = [f'<p>{UI["bib_intro"]}</p>']
MDA.append(f'\n\n# {UI["appendix"]} {A["bibliography"][0]}: {A["bibliography"][1]}\n')
bh.append(f'<h2>{UI["bib_general"]}</h2>')
for g, items in REFS:
    bh.append(f'<h3>{inline(g)}</h3><ul class="refs">' + ''.join(f'<li>{inline(t)}<br/><a class="url" href="{u}">{esc(u)}</a></li>' for t, u in items) + '</ul>')
    MDA.append(f'\n### {g}\n' + '\n'.join(f'- {t}: <{u}>' for t, u in items))
    allu |= {u for t, u in items}
bh.append(f'<h2>{UI["bib_chapters"]}</h2>')
for n, t in chapters:
    if not BIB[n]:
        continue
    bh.append(f'<h3>{CH} {fa(n)}: {inline(t)}</h3><ul class="refs">' + ''.join(f'<li>{inline(a)}<br/><a class="url" href="{u}">{esc(u)}</a></li>' for a, u in BIB[n]) + '</ul>')
    MDA.append(f'\n### {CH} {n}: {t}\n' + '\n'.join(f'- {a}: <{u}>' for a, u in BIB[n]))
    allu |= {u for a, u in BIB[n]}
letter_sec('appG', 'bibliography', ''.join(bh))
c = UI['algo_cols']
alh = [f'<p>{UI["algo_list_intro"].format(n=fa(len(ALGOS)))}</p><table class="algol"><thead><tr>' + ''.join(f'<th>{x}</th>' for x in c) + '</tr></thead><tbody>']
MDA.append(f'\n\n# {UI["appendix"]} {A["algorithms"][0]}: {A["algorithms"][1]}\n\n| {c[0]} | {c[1]} | {c[2]} | {c[3]} |\n|---|---|---|---|')
for k, (ch, aid, nm, src, cx) in enumerate(ALGOS):
    alh.append(f'<tr><td class="tn">{fa(k + 1)}</td><td><a href="#{aid}">{inline(nm)}</a></td><td class="src"><code>{esc(src)}</code></td><td class="chref">{fa(ch)}</td><td class="pg"><a class="pgn" href="#{aid}"></a></td></tr>')
    MDA.append(f'| {k + 1} | {nm} | `{src}` | {ch} |')
alh.append('</tbody></table>')
letter_sec('appH', 'algorithms', ''.join(alh))
json.dump({t: [(ch, a) for ch, a in v] for t, v in ix_hits.items()}, open(os.path.join(OUT, 'ix_hits.json'), 'w'))
app.append(f'<section class="appendix index" id="index"><h1 class="ap-title" data-t="{UI["index"]}"><span class="apn">&nbsp;</span>{UI["index"]}</h1><p class="ixnote">{UI["index_note"]}</p><div class="ixcols"><!--INDEX--></div></section>')
MDA.append(f'\n\n# {UI["index"]}\n\n{UI["index_md_note"]}\n')
for t in sorted(ix_hits, key=lambda x: x.lower()):
    MDA.append(f'- {t}: {CH} ' + UI['list_sep'].join(str(ch) for ch in sorted({ch for ch, a in ix_hits[t]})))

# ---------- front matter ----------
pref_md = []
pfm, PREF = load_md(os.path.join(C, 'front', 'preface.md'))
if pfm.get('translation') == 'pending':
    PREF = ['!NOTE ' + UI['pending_note']]
from booklib.structure import canonical_counts  # noqa: E402
N_ALGO, N_FIG = (len(ALGOS), len(figs)) if LANG == 'fa' else canonical_counts(ROOT)
pref = render([x.replace('@NALGO@', fa(N_ALGO)).replace('@NFIG@', fa(N_FIG)) for x in PREF], md=pref_md)
toc_html = []
for lvl, hid, num, txt, ch in toc:
    if lvl == 1 and hid in PART_IDS:
        toc_html.append(f'<tr class="t1 tpart"><td class="tt" colspan="2"><a href="#{hid}">{inline(txt)}</a></td><td class="pg"><a class="pgn" href="#{hid}"></a></td></tr>')
        continue
    if lvl == 1:
        toc_html.append(f'<tr class="t1"><td class="tn">{CH} {num}</td><td class="tt"><a href="#{hid}">{inline(txt)}</a></td><td class="pg"><a class="pgn" href="#{hid}"></a></td></tr>')
    else:
        toc_html.append(f'<tr class="t2"><td class="tn">{num}</td><td class="tt"><a href="#{hid}">{inline(txt)}</a></td><td class="pg"><a class="pgn" href="#{hid}"></a></td></tr>')
for aid, key in [('appA', 'glossary'), ('appB', 'cheatsheet'), ('appC', 'troubleshooting'), ('appD', 'versions'), ('appF', 'answers'), ('appG', 'bibliography'), ('appH', 'algorithms'), ('index', None)]:
    t = UI['toc_app'][key] if key else UI['index']
    toc_html.append(f'<tr class="t1"><td class="tt" colspan="2"><a href="#{aid}">{inline(t)}</a></td><td class="pg"><a class="pgn" href="#{aid}"></a></td></tr>')


def short(c, n=78):
    c = re.sub(r'\*\*|`', '', c)
    c = c.split(':')[0] if len(c) > n and ':' in c[:n] else c
    return c if len(c) <= n else c[:n].rsplit(' ', 1)[0] + '…'


lof = ''.join(f'<tr><td class="tn">{num}</td><td class="tt"><a href="#{fid}">{inline(short(cap))}</a></td><td class="pg"><a class="pgn" href="#{fid}"></a></td></tr>' for fid, num, cap in figs)
ASSETS = os.path.join(ROOT, 'assets')
cover = os.path.join(OUT, f'cover.png') if os.path.exists(os.path.join(OUT, 'cover.png')) else os.path.join(ASSETS, f'cover.{LANG}.png')
backimg = os.path.join(OUT, f'back.png') if os.path.exists(os.path.join(OUT, 'back.png')) else os.path.join(ASSETS, f'back.{LANG}.png')
tmpl = string.Template(open(os.path.join(ROOT, 'templates', 'html', f'front.{LANG}.html'), encoding='utf-8').read())
front = tmpl.substitute(cover='file://' + cover, book=BOOK, preface=pref, toc=''.join(toc_html), lof=lof,
                        version_display=META['version_display'], date_display=META['date_display'],
                        technical_basis=META['technical_basis'])
back = f'<div class="backpg"><img src="file://{backimg}"/></div>'
css = open(os.path.join(ROOT, 'templates', 'css', f'book.{LANG}.css'), encoding='utf-8').read()
doc = f'<!doctype html><html lang="{LANG}" dir="{META["dir"]}"><head><meta charset="utf-8"><title>{BOOK}</title><style>{css}</style></head><body>\n{front}\n<div id="mainstart"></div>{"".join(body)}{"".join(app)}{back}</body></html>'
open(os.path.join(OUT, 'book.html'), 'w', encoding='utf-8').write(doc)

# ---------- markdown export ----------
md = [f'# {BOOK}\n\n{UI["md_title_line"]}\n\n{UI["md_byline"].format(version=META["version_display"], date=META["date_display"])}\n',
      f'\n## {UI["md_about_title"]}\n\n{UI["md_about"]}\n',
      f'\n# {UI["preface"]}\n' + ''.join(x + '\n' for x in pref_md).replace('\n### ', '\n## '),
      f'\n# {UI["toc"]}\n']
for lvl, hid, num, txt, ch in toc:
    if hid in PART_IDS:
        md.append(f'- **{txt}**')
        continue
    md.append(f'- {CH} {ch}: {txt}' if lvl == 1 else f'  - {num.translate(EN).replace("-", ".")} {txt}')
md.append(UI['md_toc_apps'])
md.append(f'\n# {UI["lof"]}\n')
md += [f'- {UI["figure"]} {num.translate(EN)}: {short(cap)}' for fid, num, cap in figs]
open(os.path.join(OUT, 'book.md'), 'w', encoding='utf-8').write('\n'.join(md) + '\n'.join(MD) + '\n'.join(MDA) + '\n')
stats = dict(lang=LANG, chapters=len(chapters), figures=len(figs), algorithms=len(ALGOS), references=len(allu),
             answers=sum(len(v) for v in ANS.values()), toc=len(toc), commands=len(seen), index_terms=len(ix_hits),
             pending_chapters=pending)
json.dump(stats, open(os.path.join(OUT, 'stats.json'), 'w'), indent=1)
print(json.dumps(stats))
