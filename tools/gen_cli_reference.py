#!/usr/bin/env python3
"""Generate references/cli-reference.yaml from a Ceph source checkout.

The command-line reference (web appendix "CLI Reference") lists every command
and option of ceph, rados, radosgw-admin, rbd, ceph-volume and
cephfs-journal-tool for one Ceph release, and tags each one by where it is
found:

  both        parsed or registered by the tool's code and present in doc/
  code-only   in the code, not found in doc/ (undocumented)
  docs-only   in doc/ (man page or guide), not in the code (removed or stale)
  usage-only  in the tool's own usage()/help text but not parsed by the code
  no-usage    parsed by the code but missing from the tool's usage()/help text

Code sources (per tool):
  radosgw-admin  src/rgw/radosgw-admin/radosgw-admin.cc: the all_cmds table,
                 the ceph_argparse_* option loop and usage()
  rados          src/tools/rados/rados.cc: strcmp(nargs[0], ...) dispatch,
                 the ceph_argparse_* option loop and usage()
  rbd            src/tools/rbd/action/*.cc Shell::Action registrations; the
                 per-command boost::program_options set is read from
                 src/test/cli/rbd/help.t, the cram test that pins
                 `rbd help <command>` to the code in Ceph's own make check
  ceph           src/mon/MonCommands.h, src/mgr/MgrCommands.h, the mgr
                 modules (COMMANDS tables and CLI*Command decorators, read
                 with the ast module) and the argparse options of src/ceph.in
  ceph-volume    argparse in src/ceph-volume/ceph_volume (mapper tables,
                 add_argument calls, common argument tables)
  cephfs-journal-tool  src/tools/cephfs/JournalTool.cc and JournalFilter.cc

Doc sources: doc/man/8/<tool>.rst (:command: entries, ``.. option::`` and
``Usage::`` blocks) and command lines quoted anywhere under doc/.  Only names
and the short help strings printed by the tools themselves are stored; no
documentation prose is copied.

Usage:
  tools/gen_cli_reference.py --ceph-src /path/to/ceph [--out references/cli-reference.yaml]
  make cli-reference CEPH_SRC=/path/to/ceph     (clones v<tag> when CEPH_SRC is unset)
"""
from __future__ import annotations

import argparse
import ast
import glob
import os
import re
import subprocess
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
OUT_DEFAULT = os.path.join(ROOT, 'references', 'cli-reference.yaml')
TAGS = ('both', 'code-only', 'docs-only', 'usage-only', 'no-usage')

S = None   # ceph source root


def rd(rel):
    with open(os.path.join(S, rel), encoding='utf-8', errors='replace') as f:
        return f.read()


def rel(path):
    return os.path.relpath(path, S).replace(os.sep, '/')


# ----------------------------------------------------------------- C helpers
_CSTR = re.compile(r'"((?:[^"\\\n]|\\.)*)"')


def c_unescape(s):
    return (s.replace('\\n', '\n').replace('\\t', '\t').replace('\\"', '"')
            .replace("\\'", "'").replace('\\\\', '\\'))


def strip_c_comments(text):
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c == '"':
            m = re.compile(r'"(?:[^"\\\n]|\\.)*"').match(text, i)
            if m:
                out.append(m.group(0))
                i = m.end()
                continue
        if text.startswith('//', i):
            j = text.find('\n', i)
            i = n if j < 0 else j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return ''.join(out)


def func_body(text, signature_rx):
    m = re.search(signature_rx, text, re.M)
    if not m:
        raise SystemExit(f'cannot find {signature_rx!r}')
    i = text.index('{', m.end() - 1 if text[m.end() - 1] == '{' else m.end())
    depth, j = 0, i
    while j < len(text):
        if text[j] == '"':
            mm = re.compile(r'"(?:[^"\\\n]|\\.)*"').match(text, j)
            j = mm.end()
            continue
        if text[j] == '{':
            depth += 1
        elif text[j] == '}':
            depth -= 1
            if depth == 0:
                return text[i:j + 1], text[:i].count('\n') + 1
        j += 1
    raise SystemExit('unbalanced body')


def usage_text(body):
    """Concatenate every string literal of a usage() body into the printed text."""
    body = re.sub(r'\b(?:std::)?endl\b', '"\\n"', strip_c_comments(body))
    return ''.join(c_unescape(m.group(1)) for m in _CSTR.finditer(body))


def norm_dash(opt):
    """ceph_argparse accepts --foo-bar and --foo_bar alike."""
    if opt.startswith('--'):
        return '--' + opt[2:].replace('_', '-')
    return opt


def tidy(s, limit=240):
    s = re.sub(r'\s+', ' ', s or '').strip()
    return s if len(s) <= limit else s[:limit - 1].rstrip() + '…'


# ----------------------------------------------------------------- doc helpers
def doc_files(*globs_):
    out = []
    for g in globs_:
        out += glob.glob(os.path.join(S, 'doc', g), recursive=True)
    return sorted(set(p for p in out if p.endswith('.rst')))


def man_commands(path):
    """:command:`a b` entries of a man page -> {name: line}."""
    out = {}
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        for m in re.finditer(r':command:`([^`]+)`', line):
            out.setdefault(re.sub(r'\s+', ' ', m.group(1)).strip(), n)
    return out


def man_options(path):
    """``.. option::`` names of a man page -> {--name: line} (also -x short forms)."""
    out = {}
    for n, line in enumerate(open(path, encoding='utf-8'), 1):
        m = re.match(r'\s*\.\. option::\s*(.+)$', line)
        if not m:
            continue
        for part in re.split(r'[,/]', m.group(1)):
            tok = part.strip().split()[0] if part.strip() else ''
            tok = re.split(r'[=\[]', tok)[0]
            if tok.startswith('-') and len(tok) > 1:
                out.setdefault(tok, n)
    return out


def tool_lines(tool, files):
    """Lines of doc/ quoting a command line of `tool` -> list of (rel, line_no, rest_of_line)."""
    rx = re.compile(r'(?:^|[\s`$#>(])' + re.escape(tool) + r'\s+(.*)$')
    out = []
    for p in files:
        for n, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
            m = rx.search(line)
            if m:
                out.append((rel(p), n, m.group(1)))
    return out


_OPT_IN_TEXT = re.compile(r'(?<![\w-])(--?[A-Za-z][\w-]*)')


def words(rest):
    """Leading command words of a doc line: lower-case tokens before any argument."""
    out = []
    for tok in rest.replace('`', ' ').replace('\\', ' ').split():
        if not re.fullmatch(r'[a-z][a-z0-9_-]*', tok):
            break
        out.append(tok)
    return out


# ----------------------------------------------------------------- items
def item(name, *, code, docs, usage=None, help_=None, **extra):
    d = {'name': name}
    d.update({k: v for k, v in extra.items() if v not in (None, [], '', {})})
    if help_:
        d['help'] = tidy(help_)
    d['in'] = {'code': bool(code), 'docs': bool(docs)}
    if usage is not None:
        d['in']['usage'] = bool(usage)
    d['tags'] = derive_tags(d['in'])
    return d


def derive_tags(src):
    code, docs, usage = src['code'], src['docs'], src.get('usage')
    if code and docs:
        tags = ['both']
    elif code:
        tags = ['code-only']
    elif docs:
        tags = ['docs-only']
    else:
        tags = []
    if usage is True and not code:
        tags.append('usage-only')
    if usage is False and code:
        tags.append('no-usage')
    return tags


def finish(items):
    return sorted(items, key=lambda d: d['name'].lower())


# ================================================================ radosgw-admin / rados
def parse_usage_block(text, cmd_indent, opt_indent_max):
    """Split a usage() text into commands {name: help} and options {opt: (help, display)}."""
    cmds, opts = {}, {}
    last = None
    for line in text.split('\n'):
        if not line.strip():
            last = None
            continue
        lead = len(line) - len(line.lstrip(' '))
        body = line.strip()
        if body.startswith('-') and lead <= opt_indent_max:
            m = re.match(r'(\S+(?:, ?-\S+)?)(?:\s{2,}(.*))?$', body)
            disp = m.group(1) if m else body.split()[0]
            hlp = (m.group(2) or '') if m else ''
            names = []
            for part in re.split(r'[/,]\s*', disp):
                part = part.strip()
                base = re.split(r'[=\[<]', part)[0]
                if base.startswith('-') and len(base) > 1:
                    names.append(base)
                    if '[-2]' in part:
                        names.append(base + '-2')
            for nm in names:
                opts.setdefault(norm_dash(nm), [hlp, disp])
            last = ('o', names)
            continue
        if lead == cmd_indent and re.match(r'[a-z]', body):
            m = re.match(r'(.+?)(?:\s{2,}(.*))?$', body)
            sig, hlp = m.group(1), m.group(2) or ''
            cmds.setdefault(sig, hlp)
            last = ('c', sig)
            continue
        if last and lead > cmd_indent + 4:
            if last[0] == 'c' and not cmds[last[1]]:
                cmds[last[1]] = body
            elif last[0] == 'o':
                for nm in last[1]:
                    o = opts[norm_dash(nm)]
                    if not o[0]:
                        o[0] = body
    return cmds, opts


def argparse_groups(text):
    """Every ceph_argparse_* call of a C++ source -> [(names, line)] (names as normalized, first long one first)."""
    out = []
    clean = strip_c_comments(text)
    for m in re.finditer(r'ceph_argparse_(?:witharg|flag|binary_flag)\s*\(', clean):
        depth, end = 1, m.end()
        while depth and end < len(clean):
            if clean[end] == '"':
                end = re.compile(r'"(?:[^"\\\n]|\\.)*"').match(clean, end).end()
                continue
            depth += {'(': 1, ')': -1}.get(clean[end], 0)
            end += 1
        seg = clean[m.end():end - 1]
        names = [norm_dash(x) for x in _CSTR.findall(seg) if x.startswith('-')]
        if not names:
            continue
        names = sorted(dict.fromkeys(names), key=lambda x: (not x.startswith('--'),))
        out.append((names, clean[:m.start()].count('\n') + 1))
    return out


def argparse_opts(text):
    return {n: ln for names, ln in argparse_groups(text) for n in names}


def global_parsed():
    """Options parsed for every C++ tool by ceph_argparse_early_args() and md_config_t::parse_argv()."""
    out = {}
    for f in ('src/common/ceph_argparse.cc', 'src/common/config.cc'):
        for names, ln in argparse_groups(rd(f)):
            out.setdefault(names[0], (names[1:], f'{f}:{ln}'))
    return out


def cxx_options(tool, path, src, uopts, dopts, doc_hits, cfg_names, gp, gen_help):
    """Options of a C++ tool with a ceph_argparse loop: merge code, usage(), man page and doc hits."""
    groups = argparse_groups(src)
    entries = []          # [names, src, kind]
    by_name = {}
    for names, ln in groups:
        hit = next((by_name[n] for n in names if n in by_name), None)
        if hit is not None:
            for n in names:
                if n not in hit[0]:
                    hit[0].append(n)
                by_name[n] = hit
            continue
        e = [list(names), f'{path}:{ln}', None]
        entries.append(e)
        for n in names:
            by_name[n] = e
    for main_, (al, where) in gp.items():
        names = [main_] + al
        if any(n in by_name for n in names):
            continue
        e = [names, where, 'global']
        entries.append(e)
        for n in names:
            by_name[n] = e
    extra = set(uopts) | {norm_dash(k) for k in dopts}
    for n in sorted(extra):
        if n in by_name:
            continue
        kind = None
        if n.startswith('--') and n[2:].replace('-', '_') in cfg_names:
            kind = 'config'
        e = [[n], None, kind]
        entries.append(e)
        by_name[n] = e
    man = f'doc/man/8/{tool}.rst'
    opts = []
    for names, where, kind in entries:
        code = where is not None or kind == 'config'
        un = next((n for n in names if n in uopts), None)
        hlp = uopts[un][0] if un else next((gen_help[n] for n in names if n in gen_help), None)
        dn = next((n for n in names if n in dopts), None)
        dref = f'{man}:{dopts[dn]}' if dn else next((doc_hits[n] for n in names if n in doc_hits), None)
        usage = bool(un) or any(n in gen_help for n in names)
        if kind == 'global' and not dref and not usage:
            continue  # shared early options that this tool neither prints nor documents
        main_ = names[0]
        opts.append(item(main_, code=code, docs=bool(dref), usage=usage, help_=hlp, kind=kind,
                         alias=', '.join(names[1:]) or None, doc=dref, src=where if kind != 'global' else None))
    return finish(opts)


def config_option_names():
    names = set()
    for p in glob.glob(os.path.join(S, 'src', 'common', 'options', '*.yaml.in')):
        for m in re.finditer(r'^- name: (\S+)', open(p, encoding='utf-8').read(), re.M):
            names.add(m.group(1))
    return names


def generic_options():
    """Options printed by generic_usage() and parsed by global_init (shared by the C++ tools)."""
    body, _ = func_body(rd('src/common/ceph_argparse.cc'), r'^static void generic_usage\(bool is_server\)\s*\{')
    txt = usage_text(body)
    _, opts = parse_usage_block(txt, 99, 8)
    return {k: v[0] for k, v in opts.items()}


def rgw_admin(cfg_names, gen_opts, gp):
    path = 'src/rgw/radosgw-admin/radosgw-admin.cc'
    src = rd(path)
    m = re.search(r'static SimpleCmd::Commands all_cmds = \{(.*?)\n\};', src, re.S)
    table = re.findall(r'\{\s*"([^"]+)"\s*,\s*OPT::(\w+)\s*\}', m.group(1))
    groups = {}   # OPT:: value -> [names]; the first name is the primary one
    for name, opt in table:
        name = name.replace(' [*]', '').strip()
        if name not in groups.setdefault(opt, []):
            groups[opt].append(name)
    alias = dict(re.findall(r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\}',
                            re.search(r'cmd_aliases = \{(.*?)\};', src, re.S).group(1)))
    trailing = {n.replace(' [*]', '') for n, _ in table if n.endswith('[*]')}
    body, _ = func_body(src, r'^void usage\(\)\s*\{')
    utxt = usage_text(body)
    ucmds_raw, uopts = parse_usage_block(utxt, 2, 6)
    for o in re.findall(r'(?<![\w-])(--[A-Za-z][\w-]*)', utxt):
        uopts.setdefault(norm_dash(o), ['', o])
    ucmds = {}
    for sig, hlp in ucmds_raw.items():
        w = ' '.join(words(sig))
        if w:
            ucmds.setdefault(w, hlp)

    man = os.path.join(S, 'doc', 'man', '8', 'radosgw-admin.rst')
    dcmds = {' '.join(words(k)): v for k, v in man_commands(man).items()}
    dopts = man_options(man)
    files = doc_files('radosgw/**/*.rst', 'man/8/radosgw-admin.rst', 'rados/**/*.rst', 'cephadm/**/*.rst', 'mgr/**/*.rst')
    lines = tool_lines('radosgw-admin', files)
    doc_words, doc_opt_hits = [], {}
    for f, n, rest in lines:
        doc_words.append(words(rest))
        for o in _OPT_IN_TEXT.findall(rest):
            doc_opt_hits.setdefault(norm_dash(re.split(r'=', o)[0]), f'{f}:{n}')

    def canon(name):
        return ' '.join(alias.get(t, t) for t in name.split())

    canon_to_opt = {canon(n): opt for opt, ns in groups.items() for n in ns}
    # each doc line is attributed to the longest code command that prefixes it
    doc_first = {}
    for (f, n, rest), w in zip(lines, doc_words):
        cw = [canon(t) for t in w]
        for k in range(len(cw), 0, -1):
            c = ' '.join(cw[:k])
            if c in canon_to_opt:
                doc_first.setdefault(canon_to_opt[c], f'{f}:{n}')
                break
    ucanon = {canon(k): k for k in ucmds}
    dcanon = {canon(k): k for k in dcmds}
    cmds = []
    seen = set()
    for opt, names in groups.items():
        cn = [canon(n) for n in names]
        un = next((ucanon[c] for c in cn if c in ucanon), None)
        dn = next((dcanon[c] for c in cn if c in dcanon), None)
        r = f'doc/man/8/radosgw-admin.rst:{dcmds[dn]}' if dn else doc_first.get(opt)
        primary = un if un in names else names[0]
        others = [n for n in names if n != primary]
        cmds.append(item(primary, code=True, docs=bool(r), usage=bool(un), help_=ucmds.get(un) if un else None,
                         alias=', '.join(others) or None, args='trailing' if primary in trailing else None, doc=r))
        seen.update(cn)
    for name, hlp in ucmds.items():
        if canon(name) in seen:
            continue
        r = f'doc/man/8/radosgw-admin.rst:{dcmds[name]}' if name in dcmds else None
        cmds.append(item(name, code=False, docs=bool(r), usage=True, help_=hlp, doc=r))
        seen.add(canon(name))
    for name, ln in dcmds.items():
        if not name or canon(name) in seen:
            continue
        cmds.append(item(name, code=False, docs=True, usage=False, doc=f'doc/man/8/radosgw-admin.rst:{ln}'))
        seen.add(canon(name))

    opts = cxx_options('radosgw-admin', path, src, uopts, dopts, doc_opt_hits, cfg_names, gp, gen_opts)
    return {
        'id': 'radosgw-admin',
        'sources': {'code': [path, 'src/common/ceph_argparse.cc', 'src/common/options/*.yaml.in'],
                    'docs': ['doc/man/8/radosgw-admin.rst', 'doc/radosgw/'],
                    'usage': f'{path} usage()'},
        'commands': finish(cmds), 'options': opts,
    }


def rados_tool(cfg_names, gen_opts, gp):
    path = 'src/tools/rados/rados.cc'
    src = rd(path)
    clean = strip_c_comments(src)
    code_cmds = {}
    for m in re.finditer(r'strcmp\(nargs\[0\],\s*"([^"]+)"\)\s*==\s*0', clean):
        code_cmds.setdefault(m.group(1), clean[:m.start()].count('\n') + 1)
    body, _ = func_body(src, r'^void usage\(ostream& out\)\s*\{')
    utxt = usage_text(body)
    # commands are indented by three spaces, options by three or four
    ucmds, uopts = {}, {}
    last = None
    for line in utxt.split('\n'):
        if not line.strip():
            last = None
            continue
        lead = len(line) - len(line.lstrip(' '))
        b = line.strip()
        if b.startswith('-') and lead <= 6:
            m = re.match(r'(\S+(?:,? ?-\S+)*)(?:\s+\S+)?(?:\s{2,}(.*))?$', b)
            disp = b.split('  ')[0]
            hlp = b[len(disp):].strip()
            for part in re.split(r'[,/]\s*|\s+', disp):
                base = re.split(r'[=\[<]', part)[0]
                if base.startswith('-') and len(base) > 1 and re.match(r'--?[A-Za-z]', base):
                    uopts.setdefault(norm_dash(base), [hlp])
            last = None
            continue
        if lead == 3 and re.match(r'[a-z][\w-]*(\s|$)', b):
            sig = b.split('  ')[0]
            name = sig.split()[0]
            ucmds.setdefault(name, b[len(sig):].strip())
            last = name
            continue
        if last and lead > 10 and not ucmds[last]:
            ucmds[last] = b
    for o in re.findall(r'(?<![\w-])(--[A-Za-z][\w-]*)', utxt):
        uopts.setdefault(norm_dash(o), [''])
    man = os.path.join(S, 'doc', 'man', '8', 'rados.rst')
    dcmds = {k.split()[0]: v for k, v in man_commands(man).items()}
    dopts = man_options(man)
    files = doc_files('rados/**/*.rst', 'man/8/rados.rst', 'radosgw/**/*.rst', 'dev/**/*.rst', 'cephfs/**/*.rst')
    lines = tool_lines('rados', files)
    doc_cmd_hits, doc_opt_hits = {}, {}
    for f, n, rest in lines:
        # skip "-p pool" style values: take the first word that is a known command
        for t in rest.replace('`', ' ').split():
            if t in code_cmds or t in ucmds:
                doc_cmd_hits.setdefault(t, f'{f}:{n}')
                break
        for o in _OPT_IN_TEXT.findall(rest):
            doc_opt_hits.setdefault(norm_dash(o.split('=')[0]), f'{f}:{n}')
    cmds = []
    for name in sorted(set(code_cmds) | set(ucmds) | set(dcmds)):
        code = name in code_cmds
        dref = f'doc/man/8/rados.rst:{dcmds[name]}' if name in dcmds else doc_cmd_hits.get(name)
        cmds.append(item(name, code=code, docs=bool(dref), usage=name in ucmds, help_=ucmds.get(name), doc=dref,
                         src=f'{path}:{code_cmds[name]}' if code else None))
    opts = cxx_options('rados', path, src, uopts, dopts, doc_opt_hits, cfg_names, gp, gen_opts)
    return {
        'id': 'rados',
        'sources': {'code': [path, 'src/common/ceph_argparse.cc'], 'docs': ['doc/man/8/rados.rst', 'doc/rados/'],
                    'usage': f'{path} usage()'},
        'commands': finish(cmds), 'options': opts,
    }


# ================================================================ rbd
def rbd_tool():
    actions = {}
    for p in sorted(glob.glob(os.path.join(S, 'src', 'tools', 'rbd', 'action', '*.cc'))):
        txt = strip_c_comments(open(p, encoding='utf-8').read())
        for m in re.finditer(r'Shell::Action\s+\w+\s*\(\s*\{([^}]*)\}\s*,\s*\{([^}]*)\}\s*,\s*((?:"(?:[^"\\]|\\.)*"\s*)+)', txt):
            name = ' '.join(_CSTR.findall(m.group(1)))
            tail = txt[m.end():txt.find(');', m.end())]
            hidden = bool(re.search(r',\s*false\s*$', tail))
            al = ' '.join(_CSTR.findall(m.group(2)))
            desc = ''.join(c_unescape(s) for s in _CSTR.findall(m.group(3)))
            actions[name] = {'alias': al or None, 'help': desc,
                             'src': f'{rel(p)}:{txt[:m.start()].count(chr(10)) + 1}', 'hidden': hidden}
    # per-command options from the cram test of `rbd help <command>`
    help_t = rd('src/test/cli/rbd/help.t')
    blocks = re.split(r'\n  (?:\$ )?rbd help ', help_t)
    per = {}
    for blk in blocks[1:]:
        name = blk.split('\n', 1)[0].strip()
        text = '\n'.join(l[2:] if l.startswith('  ') else l for l in blk.split('\n')[1:])
        usage = text.split('\n\n')[0]
        listed, cur = {}, None
        section = None
        for line in text.split('\n'):
            if line.startswith('Optional arguments'):
                section = 'o'
                continue
            if line.startswith('Positional arguments'):
                section = 'p'
                continue
            if section == 'o':
                m = re.match(r'  (-\w \[ (--[\w-]+) \]|(--[\w-]+))( arg)?\s*(.*)$', line)
                if m:
                    nm = m.group(2) or m.group(3)
                    short = re.match(r'  (-\w) \[', line)
                    listed[nm] = {'help': m.group(5), 'short': short.group(1) if short else None,
                                  'arg': bool(m.group(4))}
                    cur = nm
                elif line.startswith('     ') and cur:
                    listed[cur]['help'] = (listed[cur]['help'] + ' ' + line.strip()).strip()
                elif not line.strip():
                    section, cur = None, None
        in_usage = set(re.findall(r'(--[\w-]+)', usage))
        per[name] = {'listed': listed, 'usage': in_usage}
    man = os.path.join(S, 'doc', 'man', '8', 'rbd.rst')
    mtext = open(man, encoding='utf-8').read().split('\n')
    dcmds, dsyn = {}, {}
    for n, line in enumerate(mtext, 1):
        m = re.match(r':command:`([^`]+)`(.*)$', line)
        if m:
            nm = m.group(1).strip()
            dcmds.setdefault(nm, n)
            # the synopsis continues on indented lines up to the blank line
            syn = m.group(2)
            k = n
            while k < len(mtext) and mtext[k].strip() and not mtext[k].startswith(':command:'):
                if mtext[k].startswith('  '):
                    break
                syn += ' ' + mtext[k]
                k += 1
            dsyn[nm] = set(re.findall(r'(--[\w-]+)', syn))
    dopts = man_options(man)
    files = doc_files('rbd/**/*.rst', 'man/8/rbd.rst', 'rados/**/*.rst')
    lines = tool_lines('rbd', files)
    doc_cmd_hits = {}
    names_by_len = sorted(set(actions) | {a['alias'] for a in actions.values() if a['alias']}, key=lambda s: -len(s.split()))
    for f, n, rest in lines:
        w = words(rest)
        for nm in names_by_len:
            if w[:len(nm.split())] == nm.split():
                doc_cmd_hits.setdefault(nm, f'{f}:{n}')
                break
    alias_of = {a['alias']: k for k, a in actions.items() if a['alias']}
    cmds = []
    seen = set()
    for name, a in sorted(actions.items()):
        dname = name if name in dcmds else (a['alias'] if a['alias'] in dcmds else None)
        dref = f'doc/man/8/rbd.rst:{dcmds[dname]}' if dname else (doc_cmd_hits.get(name) or doc_cmd_hits.get(a['alias']))
        h = per.get(name) or per.get(a['alias'] or '') or {'listed': {}, 'usage': set()}
        syn = dsyn.get(dname, set()) if dname else set()
        opts = []
        for on in sorted(set(h['listed']) | h['usage'] | syn):
            code = on in h['listed'] or on in h['usage']
            odoc = on in syn or on in dopts
            opts.append(item(on, code=code, docs=odoc, usage=on in h['listed'] if code else None,
                             help_=h['listed'].get(on, {}).get('help'),
                             short=h['listed'].get(on, {}).get('short')))
        cmds.append(item(name, code=True, docs=bool(dref), help_=a['help'], alias=a['alias'], doc=dref,
                         src=a['src'], options=opts, flags=['hidden'] if a['hidden'] else None))
        seen.add(name)
        if a['alias']:
            seen.add(a['alias'])
    for nm, ln in dcmds.items():
        if nm in seen or nm in alias_of:
            continue
        syn = dsyn.get(nm, set())
        opts = [item(o, code=False, docs=True) for o in sorted(syn)]
        cmds.append(item(nm, code=False, docs=True, doc=f'doc/man/8/rbd.rst:{ln}', options=opts))
    # global options (Shell.cc)
    sh = strip_c_comments(rd('src/tools/rbd/Shell.cc')) + strip_c_comments(rd('src/tools/rbd/ArgumentTypes.cc'))
    gopts = {}
    for m in re.finditer(r'\(\s*"([\w-]+)(?:,(\w))?"\s*,\s*(?:po::value<[^>]*>\(\)(?:->[^,]*)?\s*,\s*)?"([^"]*)"', sh):
        if m.group(1) in ('conf', 'cluster', 'id', 'name', 'mon_host', 'keyring', 'keyfile'):
            gopts['--' + m.group(1).replace('_', '-')] = m.group(3)
    gl = []
    for on in sorted(set(gopts) | set(dopts)):
        gl.append(item(on, code=on in gopts or on in ('-c', '-m', '-p', '--pool', '--namespace', '--no-progress', '--image-feature', '--image-format', '--object-size', '--image-shared', '--stripe-unit', '--stripe-count', '--snap', '--id', '--keyring', '--name', '--cluster') or any(on in h['listed'] for h in per.values()),
                       docs=on in dopts, help_=gopts.get(on), doc=f'doc/man/8/rbd.rst:{dopts[on]}' if on in dopts else None))
    return {
        'id': 'rbd',
        'sources': {'code': ['src/tools/rbd/action/*.cc', 'src/tools/rbd/Shell.cc', 'src/test/cli/rbd/help.t'],
                    'docs': ['doc/man/8/rbd.rst', 'doc/rbd/'], 'usage': 'src/test/cli/rbd/help.t (rbd help <command>)'},
        'commands': finish(cmds), 'options': finish(gl),
    }


# ================================================================ ceph
def parse_argdesc(sig):
    """'osd pool create name=pool,type=CephPoolname name=pg_num,...' -> (prefix, [args])."""
    prefix, args = [], []
    for tok in sig.split():
        if '=' in tok and ',' in tok or tok.startswith('name='):
            kv = dict(p.split('=', 1) for p in tok.split(',') if '=' in p)
            a = {'name': kv.get('name', '?'), 'type': kv.get('type', '')}
            if kv.get('req') == 'false':
                a['optional'] = True
            if kv.get('strings'):
                a['choices'] = kv['strings'].split('|')
            if kv.get('positional') == 'false' or a['type'] == 'CephBool':
                a['flag'] = True
            args.append(a)
        elif not args:
            prefix.append(tok)
    return ' '.join(prefix), args


def c_commands(path):
    """COMMAND(...) / COMMAND_WITH_FLAG(...) entries of MonCommands.h / MgrCommands.h."""
    txt = strip_c_comments(rd(path))
    out = []
    for m in re.finditer(r'^\s*(COMMAND(?:_WITH_FLAG)?)\(', txt, re.M):
        i, depth = m.end(), 1
        j = i
        while depth and j < len(txt):
            if txt[j] == '"':
                j = re.compile(r'"(?:[^"\\\n]|\\.)*"').match(txt, j).end()
                continue
            depth += {'(': 1, ')': -1}.get(txt[j], 0)
            j += 1
        inner = txt[i:j - 1]
        # split top-level by commas outside quotes/parens
        parts, cur, d, k = [], '', 0, 0
        while k < len(inner):
            c = inner[k]
            if c == '"':
                e = re.compile(r'"(?:[^"\\\n]|\\.)*"').match(inner, k).end()
                cur += inner[k:e]
                k = e
                continue
            if c == '(':
                d += 1
            elif c == ')':
                d -= 1
            if c == ',' and d == 0:
                parts.append(cur)
                cur = ''
            else:
                cur += c
            k += 1
        parts.append(cur)
        strs = [''.join(c_unescape(s) for s in _CSTR.findall(p)) for p in parts]
        flags = re.findall(r'FLAG\(([A-Z_|]+)\)', inner)
        flags = [f.lower() for fl in flags for f in fl.split('|') if f not in ('NONE',)]
        out.append({'sig': strs[0], 'help': strs[1] if len(strs) > 1 else '', 'module': strs[2] if len(strs) > 2 else '',
                    'perm': strs[3] if len(strs) > 3 else '', 'flags': flags,
                    'line': txt[:m.start()].count('\n') + 1})
    return out


def _class_consts(tree):
    """Upper-case string constants assigned anywhere in a module (class attributes such as NAME = 'motd')."""
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out.setdefault(t.id, node.value.value)
    return out


def str_of(node, consts):
    """Best-effort static value of a string expression (literals, f-strings, +, str.format)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                parts.append(str(v.value))
            else:
                inner = v.value
                key = inner.attr if isinstance(inner, ast.Attribute) else getattr(inner, 'id', None)
                parts.append(consts.get(key, '{%s}' % (key or '?')))
        return ''.join(parts)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        l, r = str_of(node.left, consts), str_of(node.right, consts)
        return l + r if l is not None and r is not None else None
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format'):
        base = str_of(node.func.value, consts)
        if base is None:
            return None
        kw = {}
        for k in node.keywords:
            v = k.value
            key = v.attr if isinstance(v, ast.Attribute) else getattr(v, 'id', None)
            kw[k.arg] = str_of(v, consts) if isinstance(v, (ast.Constant, ast.JoinedStr)) else consts.get(key, '{%s}' % k.arg)
        try:
            return base.format(**kw) if kw else base
        except (KeyError, IndexError):
            return base
    return None


def dashboard_settings():
    """dashboard get-/set-/reset-<option> commands generated from class Options in dashboard/settings.py."""
    r = 'src/pybind/mgr/dashboard/settings.py'
    tree = ast.parse(rd(r))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == 'Options':
            for st in node.body:
                if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name) and not st.targets[0].id.startswith('_'):
                    opt = st.targets[0].id
                    key = opt.lower().replace('_', '-')
                    for verb, desc, perm, args in (('get', 'Get the {} option value', 'r', []),
                                                   ('set', 'Set the {} option value', 'w', [{'name': 'value', 'type': 'CephString'}]),
                                                   ('reset', 'Reset the {} option to its default value', 'w', [])):
                        out.append({'prefix': f'dashboard {verb}-{key}', 'args': args, 'help': desc.format(opt),
                                    'module': 'dashboard', 'src': f'{r}:{st.lineno}', 'perm': perm})
    return out


_KNOWN_ARGS = {'self', 'mgr', 'inbuf', 'return', '_end_positional_'}


def _ann_type(a):
    if a is None:
        return ''
    try:
        return ast.unparse(a)
    except Exception:  # pragma: no cover
        return ''


def mgr_commands():
    base = os.path.join(S, 'src', 'pybind', 'mgr')
    out = []
    for p in sorted(glob.glob(os.path.join(base, '**', '*.py'), recursive=True)):
        r = rel(p)
        if '/tests/' in r or '/test_' in r or r.split('/')[-1].startswith('test_') or '/mgr/test_orchestrator/' in r:
            continue
        mod = r.split('/')[3] if r.count('/') > 3 else os.path.splitext(r.split('/')[-1])[0]
        try:
            tree = ast.parse(open(p, encoding='utf-8').read())
        except SyntaxError:
            continue
        consts = _class_consts(tree)
        for node in ast.walk(tree):
            # COMMANDS = [ {'cmd': '...', 'desc': '...'}, ... ]  (also SSO_COMMANDS and the like)
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id.endswith('COMMANDS') for t in tgts) and isinstance(node.value, ast.List):
                    for el in node.value.elts:
                        if isinstance(el, ast.Dict):
                            d = {}
                            for k, v in zip(el.keys, el.values):
                                if isinstance(k, ast.Constant):
                                    d[k.value] = str_of(v, consts)
                            if d.get('cmd'):
                                prefix, args = parse_argdesc(d['cmd'])
                                out.append({'prefix': prefix, 'args': args, 'help': d.get('desc') or '',
                                            'module': mod, 'src': f'{r}:{el.lineno}', 'perm': d.get('perm') or ''})
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'Command'
                    and any(k.arg == 'prefix' for k in node.keywords)):
                pv = str_of(next(k.value for k in node.keywords if k.arg == 'prefix'), consts)
                if pv and '{' not in pv:
                    out.append({'prefix': pv, 'args': [], 'help': '', 'module': mod, 'src': f'{r}:{node.lineno}', 'perm': ''})
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for dec in node.decorator_list:
                    if not isinstance(dec, ast.Call):
                        continue
                    fn = _ann_type(dec.func)
                    if not re.search(r'CLI\w*Command|_cli_(read|write)_command|CLICommand', fn):
                        continue
                    prefix = str_of(dec.args[0], consts) if dec.args else None
                    for kw in dec.keywords:
                        if kw.arg == 'prefix':
                            prefix = str_of(kw.value, consts)
                    if not prefix or '{' in prefix:
                        continue
                    perm = 'r' if 'Read' in fn or 'read' in fn else ('rw' if 'Write' in fn or 'write' in fn else '')
                    for kw in dec.keywords:
                        if kw.arg == 'perm' and isinstance(kw.value, ast.Constant):
                            perm = kw.value.value
                    args = []
                    a = node.args
                    pos = a.posonlyargs + a.args
                    ndef = len(a.defaults)
                    positional = True
                    for i, arg in enumerate(pos):
                        if arg.arg in _KNOWN_ARGS:
                            if arg.arg == '_end_positional_':
                                positional = False
                            continue
                        t = _ann_type(arg.annotation)
                        if arg.arg == 'format' or t in ('bool', 'Optional[bool]'):
                            positional = False
                        d = {'name': arg.arg, 'type': t}
                        if i >= len(pos) - ndef:
                            d['optional'] = True
                        if not positional:
                            d['flag'] = True
                        args.append(d)
                    for arg in a.kwonlyargs:
                        d = {'name': arg.arg, 'type': _ann_type(arg.annotation), 'optional': True, 'flag': True}
                        args.append(d)
                    doc = ast.get_docstring(node) or ''
                    out.append({'prefix': prefix, 'args': args, 'help': doc.strip().split('\n\n')[0],
                                'module': mod, 'src': f'{r}:{node.lineno}', 'perm': perm})
    out += dashboard_settings()
    if os.path.exists(os.path.join(base, 'cli_api', 'module.py')):
        # cli_api registers "mgr cli <api-function>" for each MgrModule API method at run time
        out.append({'prefix': 'mgr cli', 'args': [{'name': 'function', 'type': 'str'}], 'help': '',
                    'module': 'cli_api', 'src': 'src/pybind/mgr/cli_api/module.py', 'perm': 'r'})
    return out


def ceph_tool():
    mon = c_commands('src/mon/MonCommands.h')
    mgrc = c_commands('src/mgr/MgrCommands.h')
    py = mgr_commands()
    code = {}
    for where, lst in (('src/mon/MonCommands.h', mon), ('src/mgr/MgrCommands.h', mgrc)):
        for c in lst:
            prefix, args = parse_argdesc(c['sig'])
            if not prefix:
                continue
            code.setdefault(prefix, {'args': args, 'help': c['help'], 'module': c['module'],
                                     'perm': c['perm'], 'flags': c['flags'],
                                     'src': f'{where}:{c["line"]}',
                                     'daemon': 'mon' if 'Mon' in where else 'mgr'})
    for c in py:
        code.setdefault(c['prefix'], {'args': c['args'], 'help': c['help'], 'module': c['module'], 'perm': c['perm'],
                                      'flags': [], 'src': c['src'], 'daemon': 'mgr'})
    # client-side commands of the ceph CLI itself (src/ceph.in)
    cin = rd('src/ceph.in')
    for nm, h in (('tell', 'send a command to a specific daemon'), ('daemon', 'talk to a local daemon admin socket'),
                  ('daemonperf', 'watch performance counters of a local daemon')):
        if re.search(r"""['"]%s['"]""" % nm, cin):
            code.setdefault(nm, {'args': [], 'help': h, 'module': 'cli', 'perm': '', 'flags': [], 'src': 'src/ceph.in',
                                 'daemon': 'client'})
    # documentation: every quoted ceph command line under doc/, and the man page Usage:: blocks
    files = doc_files('**/*.rst')
    lines = tool_lines('ceph', files)
    by_len = sorted(code, key=lambda s: -len(s.split()))
    first_words = {k.split()[0] for k in code}
    hits, arg_hits = {}, {}
    for f, n, rest in lines:
        if f.startswith('doc/dev/') or f.startswith('doc/releases/') or f.startswith('doc/changelog/'):
            continue
        w = words(rest)
        if not w:
            continue
        for k in by_len:
            kw = k.split()
            if w[:len(kw)] == kw:
                hits.setdefault(k, f'{f}:{n}')
                arg_hits.setdefault(k, set()).update(re.findall(r'[\w-]+', rest))
                break
    man = os.path.join(S, 'doc', 'man', '8', 'ceph.rst')
    mlines = open(man, encoding='utf-8').read().split('\n')
    man_cmds = {}
    for n, line in enumerate(mlines, 1):
        m = re.match(r'\s+ceph (.+)$', line)
        if m and n > 1 and any(mlines[k].rstrip().endswith('::') for k in range(max(0, n - 4), n - 1)):
            w = words(m.group(1))
            if w and w[0] in first_words | {'tell', 'daemon'}:
                man_cmds.setdefault(' '.join(w), (n, set(re.findall(r'--[\w-]+', m.group(1)))))
    cmds = []
    for k in sorted(code):
        c = code[k]
        dref = hits.get(k)
        ah = arg_hits.get(k, set())
        opts = []
        for a in c['args']:
            nm = a['name']
            disp = ('--' + nm.replace('_', '-')) if a.get('flag') else nm
            docs = bool(dref) and (nm in ah or nm.replace('_', '-') in ah)
            extra = {k2: v for k2, v in a.items() if k2 not in ('name',)}
            opts.append(item(disp, code=True, docs=docs, **{'type': extra.get('type') or None,
                                                             'optional': extra.get('optional'),
                                                             'choices': extra.get('choices')}))
        cmds.append(item(k, code=True, docs=bool(dref), help_=c['help'], doc=dref, src=c['src'],
                         daemon=c['daemon'], module=c['module'] if c['daemon'] == 'mgr' else None,
                         perm=c['perm'] or None, flags=c['flags'] or None, options=opts))
    covered = set(code)
    prefixes = {' '.join(k.split()[:i]) for k in code for i in range(1, len(k.split()))}

    def known(toks):
        return any(' '.join(toks[:i]) in covered for i in range(len(toks), 0, -1)) or ' '.join(toks) in prefixes
    for k, (ln, fl) in sorted(man_cmds.items()):
        if known(k.split()):
            continue
        cmds.append(item(k, code=False, docs=True, doc=f'doc/man/8/ceph.rst:{ln}',
                         options=[item(o, code=False, docs=True) for o in sorted(fl)]))
        covered.add(k)
    # command lines in literal blocks of the guides (indented or prompted), not prose
    stop = {'a', 'an', 'and', 'are', 'as', 'be', 'by', 'command', 'for', 'in', 'is', 'it', 'of', 'on', 'or',
            'that', 'the', 'this', 'to', 'tool', 'with', 'missing', 'subcommands', 'provides'}
    lit = {}
    for p in files:
        rp = rel(p)
        if rp.startswith(('doc/dev/', 'doc/releases/', 'doc/changelog/', 'doc/man/')):
            continue
        for n, line in enumerate(open(p, encoding='utf-8', errors='replace'), 1):
            cands = [m.group(1) for m in re.finditer(r'``ceph ([^`]+)``', line)]
            m = re.match(r'^(?:\s{2,}|\t)(?:\[[^\]]*\]\s*)?(?:[$#]\s+)?(?:sudo\s+)?(?:cephadm shell\s+(?:\S+\s+)*?--\s+)?ceph\s+(.+)$', line)
            if m:
                cands.append(m.group(1))
            for c in cands:
                w = []
                for t in words(c):
                    if '_' in t:
                        break
                    w.append(t)
                if len(w) < 2 or w[0] not in first_words or stop & set(w) or known(w):
                    continue
                lit.setdefault(' '.join(w), f'{rp}:{n}')
    for k, ref in sorted(lit.items()):
        cmds.append(item(k, code=False, docs=True, doc=ref))
        covered.add(k)
    cmds = finish(cmds)
    # global options of the ceph CLI (argparse in src/ceph.in)
    gl = []
    tree = ast.parse(cin.split('\n', 1)[1] if cin.startswith('#!') else cin)
    copts = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'add_argument':
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('-')]
            h = next((kw.value.value for kw in node.keywords if kw.arg == 'help' and isinstance(kw.value, ast.Constant)), '')
            if names:
                main = next((x for x in names if x.startswith('--')), names[0])
                copts[main] = (h, [x for x in names if x != main], node.lineno)
    mopts = man_options(man)
    alias_to_main = {a: m for m, (_, al, _) in copts.items() for a in al}
    for on in sorted(set(copts) | {o for o in mopts if o not in alias_to_main}):
        h, al, ln = copts.get(on, ('', [], None))
        gl.append(item(on, code=on in copts, docs=on in mopts or any(a in mopts for a in al), help_=h,
                       alias=', '.join(al) or None, src=f'src/ceph.in:{ln}' if ln else None,
                       doc=f'doc/man/8/ceph.rst:{mopts[on]}' if on in mopts else None))
    return {
        'id': 'ceph',
        'sources': {'code': ['src/mon/MonCommands.h', 'src/mgr/MgrCommands.h', 'src/pybind/mgr/', 'src/ceph.in'],
                    'docs': ['doc/man/8/ceph.rst', 'doc/'], 'usage': None},
        'commands': finish(cmds), 'options': finish(gl),
    }


# ================================================================ ceph-volume
def ceph_volume_tool():
    base = os.path.join(S, 'src', 'ceph-volume', 'ceph_volume')

    def dict_keys(path, varname):
        tree = ast.parse(open(path, encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(isinstance(t, ast.Name) and t.id == varname for t in tgts) and isinstance(node.value, ast.Dict):
                    out = {}
                    for k, v in zip(node.value.keys, node.value.values):
                        if isinstance(k, ast.Constant):
                            h = ''
                            if isinstance(v, ast.Dict):
                                for kk, vv in zip(v.keys, v.values):
                                    if isinstance(kk, ast.Constant) and kk.value == 'help' and isinstance(vv, ast.Constant):
                                        h = vv.value
                            out[k.value] = h
                    return out
        return {}

    def class_opts(path, clsname, common_dir):
        tree = ast.parse(open(path, encoding='utf-8').read())
        opts = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == clsname:
                src_names = set()
                for sub in ast.walk(node):
                    if isinstance(sub, ast.Call) and getattr(sub.func, 'attr', '') == 'add_argument':
                        names = [a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('-')]
                        h = next((kw.value.value for kw in sub.keywords if kw.arg == 'help' and isinstance(kw.value, ast.Constant)), '')
                        pos = [a.value for a in sub.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and not a.value.startswith('-')]
                        for nm in names or pos[:1]:
                            opts.setdefault(nm, h)
                    if isinstance(sub, ast.Name):
                        src_names.add(sub.id)
                    if isinstance(sub, ast.Attribute):
                        src_names.add(sub.attr)
                cpath = os.path.join(common_dir, 'common.py')
                if os.path.exists(cpath):
                    if 'common_parser' in src_names:
                        src_names |= {'common_args', 'bluestore_args'}
                    for var in ('common_args', 'bluestore_args'):
                        if var in src_names:
                            for k, h in dict_keys(cpath, var).items():
                                opts.setdefault(k, h)
        return opts

    def mapper(path):
        tree = ast.parse(open(path, encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)) and isinstance(node.value, ast.Dict):
                tgts = node.targets if isinstance(node, ast.Assign) else [node.target]
                if any(_ann_type(t).endswith('mapper') for t in tgts):
                    return {k.value: _ann_type(v) for k, v in zip(node.value.keys, node.value.values)}
        return {}

    def docstr(path, clsname):
        tree = ast.parse(open(path, encoding='utf-8').read())
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name == clsname:
                for st in node.body:
                    if isinstance(st, ast.Assign) and any(getattr(t, 'id', '') == 'help' for t in st.targets) and isinstance(st.value, ast.Constant):
                        return st.value.value
                return (ast.get_docstring(node) or '').split('\n')[0]
        return ''

    code = {}
    top = mapper(os.path.join(base, 'main.py'))
    for sub, target in top.items():
        modpath = target.rsplit('.', 1)[0].replace('.', '/')
        cls = target.rsplit('.', 1)[1]
        d = os.path.join(base, modpath)
        mainpy = os.path.join(d, 'main.py') if os.path.isdir(d) else os.path.join(base, modpath + '.py')
        if not os.path.exists(mainpy):
            mainpy = os.path.join(base, modpath, '__init__.py')
        m2 = mapper(mainpy) if os.path.exists(mainpy) else {}
        if m2:
            for name, t2 in m2.items():
                f2 = os.path.join(os.path.dirname(mainpy), t2.split('.')[0] + '.py')
                c2 = t2.split('.')[-1]
                if os.path.exists(f2):
                    code[f'{sub} {name}'] = {'opts': class_opts(f2, c2, os.path.dirname(mainpy)),
                                             'help': docstr(f2, c2), 'src': rel(f2)}
        else:
            code[sub] = {'opts': class_opts(mainpy, cls, os.path.dirname(mainpy)), 'help': docstr(mainpy, cls),
                         'src': rel(mainpy)}
    files = doc_files('ceph-volume/**/*.rst', 'man/8/ceph-volume.rst', 'cephadm/**/*.rst', 'rados/**/*.rst')
    lines = tool_lines('ceph-volume', files)
    hits, opt_hits = {}, {}
    by_len = sorted(code, key=lambda s: -len(s.split()))
    for f, n, rest in lines:
        w = words(rest)
        k = next((k for k in by_len if w[:len(k.split())] == k.split()), None)
        if k:
            hits.setdefault(k, f'{f}:{n}')
            for o in _OPT_IN_TEXT.findall(rest):
                opt_hits.setdefault((k, o.split('=')[0]), f'{f}:{n}')
    # man page sections: "prepare" under "lvm" etc. are documented with ``--option`` lists
    man = open(os.path.join(S, 'doc', 'man', '8', 'ceph-volume.rst'), encoding='utf-8').read()
    man_opts = set(re.findall(r'\* \[(--?[\w-]+)', man)) | set(re.findall(r'``(--[\w-]+)``', man)) | set(re.findall(r'\[(--[\w-]+)', man))
    all_doc_opts = man_opts | {o for (_, o) in opt_hits}
    for p in files:
        all_doc_opts |= set(re.findall(r'(?<![\w-])(--[a-z][\w-]+)', open(p, encoding='utf-8').read()))
    cmds = []
    for k in sorted(code):
        c = code[k]
        opts = [item(o, code=True, docs=o in all_doc_opts or not o.startswith('-'), help_=h) for o, h in sorted(c['opts'].items())]
        dref = hits.get(k) or ('doc/man/8/ceph-volume.rst' if re.search(r'\*\*%s\*\*' % re.escape(k.split()[-1]), man) else None)
        cmds.append(item(k, code=True, docs=bool(dref), help_=c['help'], src=c['src'], doc=dref, options=opts))
    gl = []
    tree = ast.parse(open(os.path.join(base, 'main.py'), encoding='utf-8').read())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'attr', '') == 'add_argument':
            names = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str) and a.value.startswith('-')]
            h = next((kw.value.value for kw in node.keywords if kw.arg == 'help' and isinstance(kw.value, ast.Constant)), '')
            if names:
                main = next((x for x in names if x.startswith('--')), names[0])
                gl.append(item(main, code=True, docs=main in all_doc_opts, help_=h,
                               alias=', '.join(x for x in names if x != main) or None))
    return {
        'id': 'ceph-volume',
        'sources': {'code': ['src/ceph-volume/ceph_volume/'], 'docs': ['doc/man/8/ceph-volume.rst', 'doc/ceph-volume/'],
                    'usage': None},
        'commands': finish(cmds), 'options': finish(gl),
    }


# ================================================================ cephfs-journal-tool
def cephfs_journal_tool(gen_opts):
    path = 'src/tools/cephfs/JournalTool.cc'
    src = rd(path)
    body, _ = func_body(src, r'^void JournalTool::usage\(\)\s*\{')
    utxt = usage_text(body)
    clean = strip_c_comments(src)
    # modes and their sub-commands, as dispatched in JournalTool::main_*()
    code_cmds = {}
    for mode, fn in (('journal', 'main_journal'), ('header', 'main_header'), ('event', 'main_event')):
        b, ln = func_body(clean, r'^int JournalTool::%s\(' % fn + r'[^)]*\)\s*\{')
        for m in re.finditer(r'command == (?:std::string\()?"([\w-]+)"', b):
            code_cmds.setdefault(f'{mode} {m.group(1)}', f'{path}:{ln + b[:m.start()].count(chr(10))}')
    filt = strip_c_comments(rd('src/tools/cephfs/JournalFilter.cc'))
    copts = {}
    for m in re.finditer(r'ceph_argparse_witharg\([^;]*?"(--[\w-]+)"', filt + clean):
        copts.setdefault(norm_dash(m.group(1)), True)
    for m in re.finditer(r'"(--[\w-]+)"', clean + filt):
        copts.setdefault(norm_dash(m.group(1)), True)
    for m in re.finditer(r'arg == "(--?[\w-]+)"|== "(--[\w-]+)"', clean + filt):
        copts.setdefault(norm_dash(m.group(1) or m.group(2)), True)
    ucmds, uopts = {}, {}
    for line in utxt.split('\n'):
        b = line.strip()
        m = re.match(r'cephfs-journal-tool \[options\] (\w+) (.*)$', b)
        if m and m.group(1) != 'journal':
            ucmds.setdefault(m.group(1), b)
        for o in re.findall(r'(?<![\w-])(--[\w-]+)', b):
            uopts.setdefault(norm_dash(o), b)
    for sub in ('inspect', 'import', 'export', 'reset'):
        if re.search(r'^\s+%s\b' % sub, utxt, re.M):
            ucmds.setdefault(f'journal {sub}', '')
    for eff in re.findall(r'<effect>: \[([^\]]+)\]', utxt):
        for e in eff.split('|'):
            ucmds.setdefault(f'event {e}', '')
    for hs in ('get', 'set'):
        ucmds.setdefault(f'header {hs}', '')
    ucmds.pop('header', None)
    ucmds.pop('event', None)
    docf = os.path.join(S, 'doc', 'cephfs', 'cephfs-journal-tool.rst')
    files = doc_files('cephfs/**/*.rst')
    lines = tool_lines('cephfs-journal-tool', files)
    dhits, dopts = {}, {}
    for f, n, rest in lines:
        w = [t for t in rest.replace('`', ' ').split() if not t.startswith('-')]
        if len(w) >= 2:
            dhits.setdefault(f'{w[0]} {w[1]}', f'{f}:{n}')
        for o in _OPT_IN_TEXT.findall(rest):
            dopts.setdefault(norm_dash(o.split('=')[0]), f'{f}:{n}')
    dtext = open(docf, encoding='utf-8').read()
    cmds = []
    for k in sorted(set(code_cmds) | set(ucmds)):
        code = k in code_cmds
        d = dhits.get(k) or (rel(docf) if re.search(r'\b%s\b' % re.escape(k.split()[1]), dtext) else None)
        cmds.append(item(k, code=code, docs=bool(d), usage=k in ucmds, doc=d, src=code_cmds.get(k)))
    opts = []
    for o in sorted(set(copts) | set(uopts)):
        if o in ('--yes-i-really-really-mean-it',) or o.startswith('--'):
            code = o in copts
            opts.append(item(o, code=code, docs=o in dopts or o in dtext, usage=o in uopts,
                             doc=dopts.get(o)))
    return {
        'id': 'cephfs-journal-tool',
        'sources': {'code': [path, 'src/tools/cephfs/JournalFilter.cc'], 'docs': ['doc/cephfs/cephfs-journal-tool.rst'],
                    'usage': f'{path} JournalTool::usage()'},
        'commands': finish(cmds), 'options': finish(opts),
    }


# ================================================================ main
def count(tool):
    c = {t: 0 for t in TAGS}
    o = {t: 0 for t in TAGS}
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


def main():
    global S
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ceph-src', required=True, help='Ceph checkout at the release tag')
    ap.add_argument('--tag', help='release tag (default: git describe --exact-match of --ceph-src)')
    ap.add_argument('--out', default=OUT_DEFAULT)
    a = ap.parse_args()
    S = os.path.abspath(a.ceph_src)
    sha = subprocess.run(['git', '-C', S, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    tag = a.tag or subprocess.run(['git', '-C', S, 'describe', '--tags', '--exact-match'], capture_output=True,
                                  text=True).stdout.strip()
    if not re.fullmatch(r'v\d+\.\d+\.\d+', tag or ''):
        raise SystemExit(f'--ceph-src must be checked out at a release tag (got {tag!r}); pass --tag')
    cfg = config_option_names()
    gen = generic_options()
    gp = global_parsed()
    tools = [ceph_tool(), rados_tool(cfg, gen, gp), rgw_admin(cfg, gen, gp), rbd_tool(), ceph_volume_tool(),
             cephfs_journal_tool(gen)]
    date = subprocess.run(['git', '-C', S, 'log', '-1', '--format=%cs'], capture_output=True, text=True).stdout.strip()
    data = {
        'meta': {
            'ceph_tag': tag, 'ceph_commit': sha, 'ceph_commit_date': date,
            'generator': 'tools/gen_cli_reference.py',
            'tags': list(TAGS),
            'summary': {t['id']: count(t) for t in tools},
        },
        'tools': tools,
    }
    hdr = ('# Generated by tools/gen_cli_reference.py from the Ceph source tree; do not edit by hand.\n'
           '# Regenerate: make cli-reference (clones ceph/ceph at meta.ceph_tag) or\n'
           '#   tools/gen_cli_reference.py --ceph-src /path/to/ceph\n'
           '# Validated by tools/check_cli_reference.py (make check-cli-reference).\n')
    with open(a.out, 'w', encoding='utf-8') as f:
        f.write(hdr)
        yaml.safe_dump(data, f, allow_unicode=True, sort_keys=False, width=1000, default_flow_style=None)
    for t in tools:
        s = data['meta']['summary'][t['id']]
        print(f"{t['id']:>20}: {s['commands']} commands {s['command_tags']}, {s['options']} options {s['option_tags']}")
    print(f'wrote {os.path.relpath(a.out)} ({tag} {sha[:12]})')
    return 0


if __name__ == '__main__':
    sys.exit(main())
