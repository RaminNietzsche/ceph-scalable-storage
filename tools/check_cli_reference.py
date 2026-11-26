#!/usr/bin/env python3
"""Validate references/cli-reference.yaml (the web appendix "CLI Reference").

Cheap and offline, so it runs in `make check` and CI; regenerating the file
needs a Ceph checkout (make cli-reference). Checks:

  - meta: a Tentacle release tag (v20.2.N), a full commit SHA, the generator
    path, the tag list and a per-tool summary that matches the entries
  - tools: the expected tools in order, each with commands and options
  - every entry: a name, unique and sorted within its list, an in: record of
    booleans and tags equal to the ones derived from it (tools/booklib/clirefs.py)
  - help strings: one line, at most 240 characters, no Markdown or HTML
  - doc:/src: locations: paths inside doc/ or src/ with an optional :line
  - the cheat-sheet commands of these tools resolve to reference entries
  - the print pointer (content/<lang>/appendices/cli-reference.md) states the
    release and the command and option counts of the data
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver, clirefs  # noqa: E402

LOC = re.compile(r'^(doc|src)/[\w./+@-]*(?:/|\*?)?(?::\d+)?$')
SHA = re.compile(r'^[0-9a-f]{40}$')
NAME = re.compile(r'^(?:-{1,2}[A-Za-z0-9][\w.-]*|[A-Za-z_][\w.-]*(?: [\w.-]+)*)$')
MIN_CS_LINKS = 150


def tentacle_tag() -> re.Pattern:
    n = cephver.REL['tentacle'][0]
    return re.compile(r'^v%d\.2\.\d+$' % n)


def check_entry(e, where, errs, kind):
    if not isinstance(e, dict) or not isinstance(e.get('name'), str) or not e['name'].strip():
        errs.append(f'{where}: entry without a name')
        return
    nm = e['name']
    w = f'{where} {nm!r}'
    if not NAME.match(nm):
        errs.append(f'{w}: unexpected characters in name')
    src = e.get('in')
    if not isinstance(src, dict) or not isinstance(src.get('code'), bool) or not isinstance(src.get('docs'), bool):
        errs.append(f'{w}: in: needs boolean code and docs')
        return
    if 'usage' in src and not isinstance(src['usage'], bool):
        errs.append(f'{w}: in.usage must be boolean')
    if set(src) - {'code', 'docs', 'usage'}:
        errs.append(f'{w}: unknown keys in in: {sorted(set(src) - {"code", "docs", "usage"})}')
    if not (src['code'] or src['docs'] or src.get('usage')):
        errs.append(f'{w}: found nowhere (code, docs and usage all false)')
    tags = e.get('tags')
    if tags != clirefs.derive_tags(src):
        errs.append(f'{w}: tags {tags} do not match in: {src} (expected {clirefs.derive_tags(src)})')
    for t in tags or []:
        if t not in clirefs.TAGS:
            errs.append(f'{w}: unknown tag {t!r}')
    h = e.get('help')
    if h is not None:
        if not isinstance(h, str) or '\n' in h or len(h) > 240:
            errs.append(f'{w}: help must be one line of at most 240 characters')
        elif re.search(r'</?(?:a|b|i|em|strong|script|code|br|p|div|span|img)(?:\s[^>]*)?>|\]\(', h):
            errs.append(f'{w}: help contains markup')
    for k in ('doc', 'src'):
        v = e.get(k)
        if v is not None and (not isinstance(v, str) or not LOC.match(v)):
            errs.append(f'{w}: {k}: {v!r} is not a doc/ or src/ location')
    if e.get('doc') and not src['docs']:
        errs.append(f'{w}: doc: location given but in.docs is false')
    if kind == 'command':
        opts = e.get('options', [])
        if not isinstance(opts, list):
            errs.append(f'{w}: options must be a list')
            return
        seen = set()
        for o in opts:
            check_entry(o, f'{w} option', errs, 'option')
            if isinstance(o, dict):
                if o.get('name') in seen:
                    errs.append(f'{w}: duplicate option {o.get("name")!r}')
                seen.add(o.get('name'))


def check_list(lst, where, errs, kind):
    if not isinstance(lst, list):
        errs.append(f'{where}: must be a list')
        return
    names = [e.get('name') for e in lst if isinstance(e, dict)]
    dup = sorted({n for n in names if names.count(n) > 1})
    if dup:
        errs.append(f'{where}: duplicate names {dup[:10]}')
    if names != sorted(names, key=lambda s: (s or '').lower()):
        errs.append(f'{where}: not sorted by name')
    for e in lst:
        check_entry(e, where, errs, kind)


def recount(tool):
    c = {t: 0 for t in clirefs.TAGS}
    o = {t: 0 for t in clirefs.TAGS}
    for cm in tool['commands']:
        for t in cm['tags']:
            c[t] += 1
        for op in cm.get('options', []):
            for t in op['tags']:
                o[t] += 1
    for op in tool['options']:
        for t in op['tags']:
            o[t] += 1
    return {'commands': len(tool['commands']),
            'options': sum(len(cm.get('options', [])) for cm in tool['commands']) + len(tool['options']),
            'command_tags': c, 'option_tags': o}


def main() -> int:
    errs: list[str] = []
    try:
        data = clirefs.load()
    except Exception as e:  # noqa: BLE001
        print(f'check_cli_reference: cannot read {clirefs.DATA}: {e}')
        return 1
    meta = data.get('meta') or {}
    if not tentacle_tag().match(str(meta.get('ceph_tag', ''))):
        errs.append(f'meta.ceph_tag {meta.get("ceph_tag")!r} is not a Tentacle release tag')
    if not SHA.match(str(meta.get('ceph_commit', ''))):
        errs.append('meta.ceph_commit must be a full 40-character SHA')
    if not re.match(r'^\d{4}-\d{2}-\d{2}$', str(meta.get('ceph_commit_date', ''))):
        errs.append('meta.ceph_commit_date must be YYYY-MM-DD')
    gen = meta.get('generator')
    if not gen or not os.path.exists(os.path.join(ROOT, gen)):
        errs.append(f'meta.generator {gen!r} does not exist')
    if list(meta.get('tags') or []) != list(clirefs.TAGS):
        errs.append(f'meta.tags must be {list(clirefs.TAGS)}')
    tools = data.get('tools') or []
    ids = [t.get('id') for t in tools]
    if tuple(ids) != clirefs.TOOL_ORDER:
        errs.append(f'tools must be {list(clirefs.TOOL_ORDER)} in this order (got {ids})')
    summ = meta.get('summary') or {}
    for t in tools:
        tid = t.get('id')
        if not isinstance(t.get('sources'), dict) or not t['sources'].get('code') or not t['sources'].get('docs'):
            errs.append(f'{tid}: sources.code and sources.docs are required')
        check_list(t.get('commands'), f'{tid} commands', errs, 'command')
        check_list(t.get('options'), f'{tid} options', errs, 'option')
        if not t.get('commands'):
            errs.append(f'{tid}: no commands')
        if not errs and summ.get(tid) != recount(t):
            errs.append(f'{tid}: meta.summary does not match the entries (regenerate)')
    if not errs:
        links = clirefs.cheatsheet_links(data)
        n = sum(len(v) for v in links.values())
        if n < MIN_CS_LINKS:
            errs.append(f'only {n} cheat-sheet commands resolve to reference entries (expected at least {MIN_CS_LINKS})')
    if not errs:
        nc, no = clirefs.counts(data)
        ver = meta['ceph_tag'][1:]
        fa = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')
        for lang, want in (('en', (f'Ceph {ver}', f'{nc} commands and {no} options')),
                           ('fa', (f'Ceph {ver}', f'{str(nc).translate(fa)} دستور و {str(no).translate(fa)} گزینه'))):
            p = os.path.join(ROOT, 'content', lang, 'appendices', 'cli-reference.md')
            txt = open(p, encoding='utf-8').read() if os.path.exists(p) else ''
            for w in want:
                if w not in txt:
                    errs.append(f'{os.path.relpath(p, ROOT)}: must say {w!r} (from the data)')
    if errs:
        for e in errs[:60]:
            print(f'check_cli_reference: {e}')
        if len(errs) > 60:
            print(f'check_cli_reference: ... and {len(errs) - 60} more')
        return 1
    print(f'cli reference: OK ({meta["ceph_tag"]} {meta["ceph_commit"][:12]}, {len(tools)} tools, '
          f'{nc} commands, {no} options, {n} cheat-sheet links)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
