#!/usr/bin/env python3
"""Export one edition to HTML, EPUB or DOCX with Pandoc.

The Pandoc sources are the chapter files themselves (standard Pandoc Markdown
with fenced divs); this script only concatenates them in book order, adds a
title heading per chapter, shifts chapter headings down one level, resolves
per-language figure variants and runs pandoc with templates/pandoc/book.lua.

Usage: tools/export_pandoc.py --lang fa|en --format html|epub|docx [--out FILE]
Environment: PANDOC (default: pandoc on PATH)
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.mdlower import split_front_matter  # noqa: E402
from booklib.structure import canonical_counts  # noqa: E402
from booklib import cephver  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
ap.add_argument('--format', default='html', choices=['html', 'epub', 'docx'])
ap.add_argument('--out')
a = ap.parse_args()
C = os.path.join(ROOT, 'content', a.lang)
UI = yaml.safe_load(open(os.path.join(C, 'ui.yaml'), encoding='utf-8'))
META = yaml.safe_load(open(os.path.join(C, 'metadata.yaml'), encoding='utf-8'))
B = os.path.join(ROOT, 'build', a.lang)
os.makedirs(B, exist_ok=True)
out = a.out or os.path.join(B, f'ceph-scalable-storage-{a.lang}.{a.format}')
IMG = re.compile(r'^(!\[.*\]\()(\S+?)(\)\{#[\w:.-]+\})\s*$')
TLDR_IMG = re.compile(r'^(\[!\[.*\]\()(\S+?)(\)\]\(#[\w:.-]+\))\s*$')


def variant(p):
    stem, ext = os.path.splitext(p)
    for c in (f'{stem}.{a.lang}{ext}', p):
        if os.path.exists(os.path.join(ROOT, c)):
            return c
    return p


def body_of(path, shift=1, pending_title=None):
    fm_text, lines = split_front_matter(open(path, encoding='utf-8').read())
    fm = yaml.safe_load(fm_text) or {}
    if fm.get('translation') == 'pending':
        return fm, [f'::: {{.note}}', UI['pending_note'], ':::']
    res = []
    inc = False
    for l in lines:
        if l.startswith('```'):
            inc = not inc
        if not inc:
            m = IMG.match(l)
            tm = TLDR_IMG.match(l)
            if m:
                l = m.group(1) + variant(m.group(2)) + m.group(3)
            elif tm:
                l = tm.group(1) + variant(tm.group(2)) + tm.group(3)
            elif shift and re.match(r'^#{1,5} ', l):
                l = '#' * shift + l
        res.append(l)
    return fm, release_fences(res)


def release_fences(lines):
    """Rewrite each command block's fence to Pandoc attribute syntax with its Ceph release label
    (booklib.cephver: an explicit {since=...} or the Reef baseline); book.lua prints the label."""
    out = list(lines)
    for i, lang, attrs, body in cephver.blocks(lines):
        since = cephver.since_of(lang, attrs, body)
        cls = f'.{lang} ' if lang else ''
        if since:
            out[i] = (f'``` {{{cls}since="{since}" since-label="{cephver.label(since, a.lang)}" '
                      f'since-title="{cephver.title(since, a.lang)}"}}')
        elif attrs:
            out[i] = '```' + lang
    return out


N_ALGO, N_FIG = canonical_counts(ROOT)


def num(n):
    return str(n).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')) if a.lang == 'fa' else str(n)


parts = []
fm, pre = body_of(os.path.join(C, 'front', 'preface.md'))
parts += [f'# {UI["preface"]} {{#preface .unnumbered}}', ''] + [x.replace('@NALGO@', num(N_ALGO)).replace('@NFIG@', num(N_FIG)) for x in pre]
for path in sorted(glob.glob(os.path.join(C, 'chapters', '[0-9][0-9]-*.md'))):
    fm, lines = body_of(path)
    n = int(fm['chapter'])
    parts += ['', f'# {UI["chapter_word"]} {n}: {fm["title"]} {{#ch{n:02d} .unnumbered}}', ''] + lines
for key, fn in (('troubleshooting', 'troubleshooting.md'), ('versions', 'versions.md')):
    fm, lines = body_of(os.path.join(C, 'appendices', fn))
    letter, title, _ = UI['app'][key]
    parts += ['', f'# {UI["appendix"]} {letter}: {title} {{.unnumbered}}', ''] + lines
G = yaml.safe_load(open(os.path.join(ROOT, 'glossary', 'glossary.yaml'), encoding='utf-8'))
letter, title, _ = UI['app']['glossary']
parts += ['', f'# {UI["appendix"]} {letter}: {title} {{.unnumbered}}', '', f'| {UI["glossary_cols"][0]} | {UI["glossary_cols"][1]} |', '|---|---|']
parts += [f'| {g["term"]} | {(g.get(a.lang) or g.get("fa", "")).replace("|", "/")} |' for g in sorted(G, key=lambda g: g['term'].lower())]
RC = yaml.safe_load(open(os.path.join(ROOT, 'references', 'ceph-release-changes.yaml'), encoding='utf-8'))
letter, title, _ = UI['app']['changes']
parts += ['', f'# {UI["appendix"]} {letter}: {title} {{#app-changes .unnumbered}}', '', UI['changes_intro'], '']
for rk, ri in RC['releases'].items():
    _, rname, rver = cephver.REL[rk]
    parts += [f'## {rname} ({rver}) {{#rel-{rk} .unnumbered}}', '', UI['changes_release'].format(v=ri['version'], d=ri['date']) + f' <{ri["notes"]}>', '',
              '| ' + ' | '.join(UI['changes_cols']) + ' |', '|---|---|---|---|']
    for c in RC['changes']:
        if c['rel'] == rk:
            st = UI['changes_confirmed'] if c['status'] == 'confirmed' else UI['changes_review']
            parts.append(f'| {c["area"]} | {c[a.lang].replace("|", "/")} | ' + ', '.join(f'[{UI["chapter_word"]} {num(n)}](#ch{n:02d})' for n in c['ch']) + f' | {st} |')
    parts.append('')
src = os.path.join(B, f'pandoc-{a.lang}.md')
SIMSTR = yaml.safe_load(open(os.path.join(ROOT, 'templates', 'site', 'sims', f'strings-{a.lang}.yaml'), encoding='utf-8'))
labels = {'algorithm': UI['algorithm'], 'algo_src': UI['algo_src'], 'algo_complexity': UI['algo_complexity'], **UI['callouts'],
          'sim_print': UI['sim_print'], 'tldr_title': UI['tldr_title'], 'tldr_sub': UI['tldr_sub'], **{k: v for k, v in SIMSTR.items() if k.endswith('_t') and not k.startswith('ps_')}}
meta = {'title': META['title'], 'subtitle': META['subtitle'], 'author': META['author'], 'lang': a.lang, 'dir': META['dir'],
        'date': META['date_display'], 'ui_labels': labels, 'rights': META.get('license', '')}
open(src, 'w', encoding='utf-8').write('---\n' + yaml.safe_dump(meta, allow_unicode=True, sort_keys=False) + '---\n\n' + '\n'.join(parts) + '\n')
pandoc = os.environ.get('PANDOC') or shutil.which('pandoc') or os.path.expanduser('~/.local/bin/pandoc')
cmd = [pandoc, src, '-o', out, '--from', 'markdown+fenced_divs+pipe_tables+yaml_metadata_block', '--toc', '--toc-depth=2',
       '--lua-filter', os.path.join(ROOT, 'templates', 'pandoc', 'book.lua'), '--resource-path', ROOT]
if a.format in ('html', 'epub'):
    cmd += ['--mathml']  # $...$ -> MathML, no JavaScript or CDN (docx gets native OMML equations)
if a.format in ('html', 'epub'):
    cmd += ['--css', os.path.join(ROOT, 'templates', 'pandoc', f'html.{a.lang}.css')]
if a.format == 'html':
    cmd += ['--standalone', '--embed-resources']
if a.format == 'epub':
    cover = os.path.join(ROOT, 'assets', f'cover.{a.lang}.png')
    cmd += ['--epub-cover-image', cover, '--split-level=1']
if a.format == 'docx':
    ref = os.path.join(ROOT, 'templates', 'pandoc', f'reference.{a.lang}.docx')
    if os.path.exists(ref):
        cmd += ['--reference-doc', ref]
subprocess.run(cmd, check=True)
print('export:', os.path.relpath(out, ROOT), os.path.getsize(out), 'bytes')
