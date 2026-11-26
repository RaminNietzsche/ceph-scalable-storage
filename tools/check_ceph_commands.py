#!/usr/bin/env python3
"""Check the Ceph command lines in the book against the Ceph source code.

Walks the command blocks of content/fa and content/en (the same blocks that get
a release badge, see tools/booklib/cephver.py) and finds every invocation of a
Ceph command-line tool, also inside pipelines, ``$( ... )``, ``watch``,
``sudo`` and ``cephadm shell -- ...``. Each invocation is checked against the
command tables in a checkout of ceph/ceph (default: a shallow sparse clone of
``main``, the branch behind docs.ceph.com/en/latest):

* ``ceph``: the real argument parser (src/pybind/ceph_argparse.py) against the
  monitor and manager command tables (MonCommands.h, MgrCommands.h), every
  manager module's CLI commands, and for ``ceph tell`` / ``ceph daemon`` the
  admin-socket commands. Option names given to ``ceph config ...``,
  ``injectargs`` and ``--<option>`` are checked against src/common/options.
* ``rbd``, ``rados``, ``radosgw-admin``, ``cephadm``, ``ceph-volume``: the
  subcommand tables and the option names those tools accept.
* ``ceph-objectstore-tool``, ``ceph-bluestore-tool``, ``ceph-kvstore-tool``,
  ``crushtool``, ``osdmaptool``, ``monmaptool``: option names (and the
  ``--op`` / command names where the tool has them).

Placeholders (``<pool>``, ``$POOL``, ``osd.$i``, ``...``) match any argument.
Known-good lines the checker cannot model go in
tools/ceph-commands-allowlist.yaml with a reason.

Report-only: exit 0 unless --strict.
"""
from __future__ import annotations

import argparse
import ast
import glob
import importlib.util
import io
import os
import re
import shlex
import subprocess
import sys
import tempfile
import warnings
from collections import defaultdict
from contextlib import redirect_stderr

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver  # noqa: E402

CEPH_GIT = 'https://github.com/ceph/ceph.git'
SPARSE = ['/src/', '!/src/test/', '!/src/rocksdb/', '!/src/seastar/', '!/src/spdk/', '!/src/dpdk/',
          '!/src/boost/', '!/src/arrow/', '!/src/jaegertracing/', '!/src/s3select/']
TOOLS = ('ceph', 'rbd', 'rados', 'radosgw-admin', 'cephadm', 'ceph-volume', 'ceph-objectstore-tool',
         'ceph-bluestore-tool', 'ceph-kvstore-tool', 'crushtool', 'osdmaptool', 'monmaptool')
warnings.filterwarnings('ignore', category=SyntaxWarning)   # old escapes in upstream sources
PH = '\u2063PH:'          # marker for placeholder words (match any argument)


# --------------------------------------------------------------------------- source

def ensure_source(path: str | None, ref: str) -> str:
    if path:
        return os.path.abspath(path)
    dest = os.path.join(tempfile.gettempdir(), f'ceph-src-{ref}')
    if not os.path.isdir(os.path.join(dest, 'src', 'mon')):
        subprocess.run(['git', 'clone', '-q', '--depth', '1', '--filter=blob:none', '--sparse',
                        '--branch', ref, CEPH_GIT, dest], check=True)
        subprocess.run(['git', '-C', dest, 'sparse-checkout', 'set', '--no-cone', *SPARSE], check=True)
    return dest


def src_rev(src: str) -> str:
    try:
        return subprocess.check_output(['git', '-C', src, 'rev-parse', 'HEAD'], text=True).strip()
    except Exception:  # noqa: BLE001
        return 'unknown'


def read(p):
    try:
        return open(p, encoding='utf-8', errors='replace').read()
    except OSError:
        return ''


_CSTR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def strip_c_comments(t: str) -> str:
    t = re.sub(r'/\*.*?\*/', ' ', t, flags=re.S)
    return re.sub(r'(?m)^\s*//.*$', '', t)


def c_macros(t: str):
    """String macros: #define NAME "..." (also chains of other string macros)."""
    macros = {}
    for m in re.finditer(r'(?m)^#define\s+([A-Z_][A-Z0-9_]*)\s+(.+)$', t):
        val, ok = [], True
        for part in re.findall(r'"((?:[^"\\]|\\.)*)"|([A-Z_][A-Z0-9_]*)', m.group(2)):
            if part[0] or not part[1]:
                val.append(part[0])
            elif part[1] in macros:
                val.append(macros[part[1]])
            else:
                ok = False
        if ok and val:
            macros[m.group(1)] = ''.join(val)
    return macros


def c_string_run(t: str, i: int, macros=None):
    """Concatenate adjacent C string literals (and string macros) starting at t[i]."""
    out, n = [], len(t)
    macros = macros or {}
    while True:
        while i < n and (t[i].isspace() or t[i] == '\\'):
            i += 1
        if i < n and t[i] == '"':
            m = _CSTR.match(t, i)
            if not m:
                break
            out.append(m.group(1))
            i = m.end()
            continue
        m = re.compile(r'[A-Z_][A-Z0-9_]*\b').match(t, i)
        if m and m.group(0) in macros and out:
            out.append(macros[m.group(0)])
            i = m.end()
            continue
        break
    return (''.join(out) if out else None), i


def desc_to_sig(desc: str):
    """'osd pool set name=pool,type=CephPoolname ...' -> ['osd', 'pool', 'set', {...}, ...]"""
    sig, positional = [], True
    for tok in desc.split():
        if tok == '--':
            positional = False
            continue
        if '=' not in tok and ',' not in tok:
            sig.append(tok)
            continue
        d = {} if positional else {'positional': 'false', 'req': 'false'}
        for kv in tok.split(','):
            if '=' in kv:
                k, v = kv.split('=', 1)
                d[k] = v
        d.pop('goodchars', None)      # character classes are not needed to match a command
        if 'type' in d:
            sig.append(d)
    return sig


def c_commands(path: str, macro_re: str):
    """Yield (descriptor, flags) for COMMAND(...)/register_command(...) calls with a literal descriptor."""
    t = strip_c_comments(read(path))
    macros = c_macros(t)
    strvars = dict(re.findall(r'std::string\s+(\w+)\s*(?:=\s*|\(\s*|\{\s*)"([^"]+)"', t))
    for m in re.finditer(macro_re, t):
        k = m.end()
        while k < len(t) and t[k] in ' \t\n({':
            k += 1
        s, j = c_string_run(t, k, macros)
        if s is not None and m.group(0).startswith('AdminSocketHook'):
            # crimson: AdminSocketHook(prefix, argument descriptors, help)
            mm = re.compile(r'\s*,\s*').match(t, j)
            if mm:
                s2, j2 = c_string_run(t, mm.end(), macros)
                if s2 is not None and (not s2 or '=' in s2.split()[0]):
                    s, j = s + ' ' + s2, j2
        if s is None:
            mv = re.compile(r'(\w+)\s*[,)]').match(t, k)
            if mv and mv.group(1) in strvars:
                s, j = strvars[mv.group(1)], mv.end()
        if not s or not re.match(r'[a-z]', s):
            continue
        if re.compile(r'\s*\+\s*\w').match(t, j):      # "bluestore allocator score " + name
            s = s.rstrip() + ' name=dyn_name,type=CephString'
        tail = t[j:j + 400]
        nxt = re.search(r'\bCOMMAND|\bregister_command', tail)
        tail = tail[:nxt.start()] if nxt else tail
        flags = set(re.findall(r'FLAG\((\w+)\)', tail))
        yield s, flags


# ---- manager modules (Python): CLICommand decorators and COMMANDS tables

def _enum_index(mgr_dir: str):
    enums = {}
    for p in glob.glob(os.path.join(mgr_dir, '**', '*.py'), recursive=True):
        if '/tests/' in p or '/test_' in p:
            continue
        try:
            tree = ast.parse(read(p))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                    (isinstance(b, ast.Name) and 'Enum' in b.id) or (isinstance(b, ast.Attribute) and 'Enum' in b.attr)
                    for b in node.bases):
                vals = []
                for st in node.body:
                    if isinstance(st, ast.Assign) and isinstance(st.value, ast.Constant) and isinstance(st.value.value, str):
                        vals.append(st.value.value)
                if vals:
                    enums.setdefault(node.name, vals)
    return enums


def _ann_to_desc(ann, name, has_default, positional, enums):
    d = {'name': name}
    n = None

    def unwrap(a):
        nonlocal n, has_default
        if isinstance(a, ast.Constant) and isinstance(a.value, str):
            try:
                a = ast.parse(a.value, mode='eval').body
            except SyntaxError:
                return 'CephString', None
        if isinstance(a, ast.Subscript):
            base = a.value.attr if isinstance(a.value, ast.Attribute) else getattr(a.value, 'id', '')
            inner = a.slice
            if base == 'Optional':
                has_default = True
                return unwrap(inner)
            if base == 'Union':
                elts = [e for e in getattr(inner, 'elts', [inner]) if not (isinstance(e, ast.Constant) and e.value is None)]
                return unwrap(elts[0]) if elts else ('CephString', None)
            if base in ('List', 'list', 'Sequence'):
                n = 'N'
                return unwrap(inner)
            if base in ('Tuple', 'tuple'):
                elts = getattr(inner, 'elts', [inner])
                n = str(len(elts))
                return unwrap(elts[0])
            return 'CephString', None
        if isinstance(a, ast.BinOp):   # X | None
            return unwrap(a.left)
        nm = a.attr if isinstance(a, ast.Attribute) else getattr(a, 'id', '')
        if nm == 'str':
            return 'CephString', None
        if nm == 'int':
            return 'CephInt', None
        if nm == 'float':
            return 'CephFloat', None
        if nm == 'bool':
            return 'CephBool', None
        if nm in enums:
            return 'CephChoices', '|'.join(enums[nm])
        return 'CephString', None

    t, strings = unwrap(ann) if ann is not None else ('CephString', None)
    d['type'] = t
    if strings:
        d['strings'] = strings
    if n:
        d['n'] = n
    if has_default:
        d['req'] = 'false'
    if not positional:
        d['positional'] = 'false'
        d['req'] = 'false'
    return d


def _pystr(node, env):
    """Best-effort static value of a str expression (constants, implicit/f-string concatenation, .format, names)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(str(v.value))
            else:
                r = _pystr(v.value, env)
                out.append('' if r is None else r)
        return ''.join(out)
    if isinstance(node, ast.Name):
        return env.get(node.id)
    if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ('self', 'cls'):
        return env.get(node.attr)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        a, b = _pystr(node.left, env), _pystr(node.right, env)
        return a + b if a is not None and b is not None else None
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'format':
        base = _pystr(node.func.value, env)
        if base is None:
            return None
        kw = {k.arg: _pystr(k.value, env) for k in node.keywords if k.arg}
        pos = [_pystr(x, env) for x in node.args]
        try:
            return base.format(*pos, **kw)
        except Exception:  # noqa: BLE001
            return None
    return None


def _str_env(body):
    env = {}
    for st in body:
        if isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name):
            v = _pystr(st.value, env)
            if v is not None:
                env[st.targets[0].id] = v
    return env


def mgr_commands(mgr_dir: str):
    enums = _enum_index(mgr_dir)
    out = []

    def visit(node, env, origin):
        for child in ast.iter_child_nodes(node):
            cenv = env
            if isinstance(child, ast.ClassDef):
                cenv = dict(env)
                cenv.update(_str_env(child.body))
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cli_function(child, env, origin)
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                tg = child.targets if isinstance(child, ast.Assign) else [child.target]
                if any(getattr(t, 'id', getattr(t, 'attr', '')).endswith('COMMANDS') for t in tg) and \
                        isinstance(child.value, ast.List):
                    for el in child.value.elts:
                        if isinstance(el, ast.Dict):
                            for k, v in zip(el.keys, el.values):
                                if isinstance(k, ast.Constant) and k.value == 'cmd':
                                    cmd = _pystr(v, env)
                                    if cmd:
                                        out.append((desc_to_sig(cmd), set(), origin))
            visit(child, cenv, origin)

    def cli_function(node, env, origin):
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            fname = f.attr if isinstance(f, ast.Attribute) else getattr(f, 'id', '')
            owner = f.value.id if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) else ''
            if not (('command' in fname.lower() and 'error' not in fname.lower() and fname != 'command') or
                    (fname in ('Read', 'Write') and 'Command' in owner)):
                continue
            pnode = dec.args[0] if dec.args else next((k.value for k in dec.keywords if k.arg == 'prefix'), None)
            prefix = _pystr(pnode, env) if pnode is not None else None
            if not prefix:
                continue
            if (owner or fname).startswith('SMB') and not prefix.startswith('smb '):
                prefix = 'smb ' + prefix
            sig = prefix.split()
            a = node.args
            names = [x.arg for x in a.posonlyargs + a.args]
            anns = {x.arg: x.annotation for x in a.posonlyargs + a.args}
            first_default = len(names) - len(a.defaults)
            positional = True
            for i, nm in enumerate(names):
                if nm in ('_', 'self', 'mgr', 'inbuf', 'return'):
                    continue
                if nm == '_end_positional_':
                    positional = False
                    continue
                ann = anns.get(nm)
                if nm == 'format' or (ann is not None and ast.unparse(ann) in ('bool', 'Optional[bool]')):
                    positional = False
                sig.append(_ann_to_desc(ann, nm, i >= first_default, positional, enums))
            out.append((sig, set(), origin))

    for p in sorted(glob.glob(os.path.join(mgr_dir, '**', '*.py'), recursive=True)):
        if '/tests/' in p or os.path.basename(p).startswith('test_'):
            continue
        try:
            tree = ast.parse(read(p))
        except SyntaxError:
            continue
        visit(tree, _str_env(tree.body), os.path.relpath(p, mgr_dir))
    # dashboard get-/set-/reset- settings, generated at run time from Options
    st = read(os.path.join(mgr_dir, 'dashboard', 'settings.py'))
    for opt in re.findall(r'(?m)^    ([A-Z][A-Z0-9_]+) = Setting\(', st):
        k = opt.lower().replace('_', '-')
        out.append((['dashboard', f'get-{k}'], set(), 'dashboard/settings.py'))
        out.append((['dashboard', f'set-{k}', {'name': 'value', 'type': 'CephString'}], set(), 'dashboard/settings.py'))
        out.append((['dashboard', f'reset-{k}'], set(), 'dashboard/settings.py'))
    return out


def config_options(src: str):
    names = set()
    for p in glob.glob(os.path.join(src, 'src', 'common', 'options', '*.yaml.in')):
        names.update(re.findall(r'(?m)^- name: ([A-Za-z0-9_.]+)', read(p)))
    for sub in re.findall(r'SUBSYS\((\w+)', read(os.path.join(src, 'src', 'common', 'subsys.h'))):
        names.add(f'debug_{sub}')
    return names


def literals(paths, pat=r'[A-Za-z0-9][\w.-]*'):
    out = set()
    for p in paths:
        for s in _CSTR.findall(read(p)):
            if re.fullmatch(pat, s):
                out.add(s)
    return out


def dash_literals(paths):
    """Option names from C/C++ sources: "--foo"/"-f" literals and boost::program_options "foo,f" names."""
    flags = set()
    for p in paths:
        t = read(p)
        for s in _CSTR.findall(t):
            if re.fullmatch(r'--?[A-Za-z][\w-]*', s):
                flags.add(s)
        for m in re.finditer(r'\(\s*"([a-z][\w-]*)(?:,([A-Za-z0-9]))?"\s*,\s*(?:po::|boost::program_options::|"|[a-z_]+::value)', t):
            flags.add('--' + m.group(1))
            if m.group(2):
                flags.add('-' + m.group(2))
    return {norm_flag(f) for f in flags}


def norm_flag(f: str) -> str:
    f = f.split('=', 1)[0]
    if f.startswith('--'):
        return '--' + f[2:].replace('_', '-')
    return f


class PyArgs(ast.NodeVisitor):
    """Collect argparse add_argument option strings (and whether they take a value) and add_parser names."""

    def __init__(self):
        self.flags, self.boolflags, self.parsers = set(), set(), set()

    def visit_Call(self, node):
        fn = node.func.attr if isinstance(node.func, ast.Attribute) else ''
        strs = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        if fn == 'add_argument':
            opts = [s for s in strs if s.startswith('-')]
            action = next((k.value.value for k in node.keywords if k.arg == 'action' and isinstance(k.value, ast.Constant)), None)
            nargs = next((k.value.value for k in node.keywords if k.arg == 'nargs' and isinstance(k.value, ast.Constant)), None)
            for o in opts:
                self.flags.add(norm_flag(o))
                if action in ('store_true', 'store_false', 'count', 'help', 'version', 'store_const') or nargs in (0, '?'):
                    self.boolflags.add(norm_flag(o))
        elif fn == 'add_parser' and strs:
            self.parsers.add(strs[0])
            for k in node.keywords:
                if k.arg == 'aliases' and isinstance(k.value, (ast.List, ast.Tuple)):
                    self.parsers.update(e.value for e in k.value.elts if isinstance(e, ast.Constant))
        self.generic_visit(node)


def py_args(paths):
    v = PyArgs()
    for p in paths:
        try:
            v.visit(ast.parse(read(p)))
        except SyntaxError:
            pass
    return v


# --------------------------------------------------------------------------- vocabulary

class SigTable(dict):
    """A ceph_argparse sigdict, with a first-word index so validate_command only sees candidates."""

    def __init__(self, sd):
        super().__init__(sd)
        self.by_first = defaultdict(dict)
        for k, cmd in sd.items():
            first = cmd['raw'][0] if cmd['raw'] and isinstance(cmd['raw'][0], str) else ''
            self.by_first[first][k] = cmd

    def candidates(self, args):
        if args and PH not in args[0]:
            return self.by_first.get(args[0], {})
        return self


class Vocab:
    def __init__(self, src: str):
        S = lambda *a: os.path.join(src, 'src', *a)  # noqa: E731
        self.src = src
        spec = importlib.util.spec_from_file_location('ceph_argparse_src', S('pybind', 'ceph_argparse.py'))
        self.ap = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.ap)
        self._patch_placeholders()
        self.options = config_options(src)
        # generic Ceph options every librados tool accepts (common/ceph_argparse.cc + global_init)
        common = [S('common', 'ceph_argparse.cc'), S('global', 'global_init.cc'), S('common', 'config.cc')]
        self.common_flags = dash_literals(common) | {'--cluster', '--id', '--user', '-i', '--name', '-n', '-c',
                                                    '--conf', '--keyring', '-k', '-m', '--mon-host', '--admin-socket',
                                                    '--setuser', '--setgroup', '-h', '--help', '--version', '-v'}
        # ---- ceph
        mon = [(desc_to_sig(d), f, 'MonCommands.h') for d, f in c_commands(S('mon', 'MonCommands.h'), r'\bCOMMAND(?:_WITH_FLAG)?\(')]
        mgr = [(desc_to_sig(d), f, 'MgrCommands.h') for d, f in c_commands(S('mgr', 'MgrCommands.h'), r'\bCOMMAND(?:_WITH_FLAG)?\(')]
        mods = mgr_commands(S('pybind', 'mgr'))
        self.cluster = self._sigdict(mon + mgr + mods)
        asok = []
        for p in glob.glob(S('**', '*.cc'), recursive=True) + glob.glob(S('**', '*.h'), recursive=True):
            if '/test/' in p or 'MonCommands.h' in p or 'MgrCommands.h' in p:
                continue
            txt = read(p)
            if not re.search(r'register_command\(|COMMAND\(|AdminSocketHook[({]|string_view\s+COMMAND', txt):
                continue
            for d, f in c_commands(p, r'\bregister_command\(|\bCOMMAND(?:_WITH_FLAG)?\(|\bAdminSocketHook\s*[({]|std::string_view\s+COMMAND\s*='):
                asok.append((desc_to_sig(d), f, os.path.relpath(p, S())))
        self.asok = self._sigdict(asok)
        self.daemon_mon = self._sigdict(asok + mon)
        self.daemon_mgr = self._sigdict(asok + mgr + mods)
        ast_in = py_args([S('ceph.in')])
        self.ceph_flags = ast_in.flags
        self.ceph_boolflags = ast_in.boolflags
        # ---- rbd
        rbd_src = glob.glob(S('tools', 'rbd', '**', '*.cc'), recursive=True) + glob.glob(S('tools', 'rbd', '*.h'))
        self.rbd_actions = set()
        for p in rbd_src:
            for m in re.finditer(r'Shell::Action\s+\w+\s*\(\s*\{([^}]*)\}\s*,\s*\{([^}]*)\}', read(p)):
                for grp in m.groups():
                    w = tuple(_CSTR.findall(grp))
                    if w:
                        self.rbd_actions.add(w)
        rbd_flags = dash_literals(rbd_src)
        consts = set()
        for p in rbd_src:
            consts.update(re.findall(r'const std::string\s+\w+\s*\(\s*"([a-z][\w-]*)"\s*\)', read(p)))
        for c in consts:
            for pre in ('', 'source-', 'dest-'):
                rbd_flags.add('--' + pre + c)
        for p in rbd_src:
            rbd_flags.update('-' + c for c in re.findall(r'\+\s*",([A-Za-z])"', read(p)))
        self.rbd_flags = rbd_flags | self.common_flags
        # ---- rados
        rados_src = [S('tools', 'rados', 'rados.cc')]
        rt = read(rados_src[0])
        self.rados_cmds = set(re.findall(r'strcmp\(nargs\[0\],\s*"([^"]+)"\)', rt))
        self.rados_cmds |= set(re.findall(r'nargs\[0\]\s*==\s*"([^"]+)"', rt))
        self.rados_flags = dash_literals(rados_src) | self.common_flags | dash_literals(
            [S('common', 'obj_bencher.cc')])
        # ---- radosgw-admin
        rgw_src = glob.glob(S('rgw', 'radosgw-admin', '*.cc')) or [S('rgw', 'rgw_admin.cc')]
        gt = ''.join(read(p) for p in rgw_src)
        self.rgw_cmds = {tuple(w for w in c.split() if w not in ('[*]', '*')) for c in re.findall(r'\{\s*"([a-z][a-z0-9 _*\[\]-]*)",\s*OPT::', gt)}
        self.rgw_flags = dash_literals(rgw_src) | self.common_flags
        # ---- cephadm
        cad = [S('cephadm', 'cephadm.py')] + glob.glob(S('cephadm', 'cephadmlib', '**', '*.py'), recursive=True)
        a = py_args(cad)
        self.cephadm_cmds, self.cephadm_flags, self.cephadm_bool = a.parsers, a.flags | {'-h', '--help'}, a.boolflags
        # ---- ceph-volume
        cv = glob.glob(S('ceph-volume', 'ceph_volume', '**', '*.py'), recursive=True)
        cv = [p for p in cv if '/tests/' not in p]
        a = py_args(cv)
        words = set()
        for p in cv:
            for m in re.finditer(r'mapper\s*=\s*\{([^}]*)\}', read(p)):
                words.update(re.findall(r"'([a-z][\w-]*)'\s*:", m.group(1)))
        self.cv_words, self.cv_flags = words, a.flags | self.common_flags | {'-h', '--help'}
        # ---- offline tools: option names, and the values of a command-selecting option
        def tool(paths, valued=()):
            return dash_literals(paths) | self.common_flags, literals(paths), valued
        self.offline = {
            'ceph-objectstore-tool': tool([S('tools', 'ceph_objectstore_tool.cc')], ('--op',)),
            'ceph-bluestore-tool': tool([S('os', 'bluestore', 'bluestore_tool.cc')], ('--command',)),
            'ceph-kvstore-tool': tool([S('tools', 'ceph_kvstore_tool.cc'), S('tools', 'kvstore_tool.cc')]),
            'crushtool': tool([S('tools', 'crushtool.cc'), S('crush', 'CrushTester.cc')]),
            'osdmaptool': tool([S('tools', 'osdmaptool.cc')]),
            'monmaptool': tool([S('tools', 'monmaptool.cc')]),
        }
        self.bluestore_cmds = self.offline['ceph-bluestore-tool'][1]

    def _sigdict(self, entries):
        sd = {}
        for i, (sig, flags, origin) in enumerate(entries):
            try:
                parsed = self.ap.parse_funcsig(sig)
            except Exception:  # noqa: BLE001
                continue
            fl = 0
            for f in flags:
                fl |= getattr(self.ap.Flag, f, 0) or 0
            sd[f'cmd{i:05d}'] = {'sig': parsed, 'flags': fl, 'help': '', 'origin': origin, 'raw': sig}
        return SigTable(sd)

    def _patch_placeholders(self):
        ap = self.ap
        for name in dir(ap):
            cls = getattr(ap, name)
            if isinstance(cls, type) and issubclass(cls, ap.CephArgtype):
                orig = cls.valid

                def valid(self, s, partial=False, _orig=orig):
                    if isinstance(s, str) and PH in s:
                        self.val = s
                        return
                    return _orig(self, s, partial)
                cls.valid = valid

    def option_ok(self, name: str) -> bool:
        if PH in name:
            return True
        n = name.replace('-', '_')
        return n in self.options or name.startswith('mgr/') or n.startswith('mgr/')


# --------------------------------------------------------------------------- book side

_SKIP_LANG = {'cpp', 'c', 'python', 'yaml', 'ini', 'json', 'xml', 'ruby', 'lua', 'go', 'rust', 'java', 'js',
              'javascript', 'toml', 'diff', 'promql', 'conf', 'hcl', 'dockerfile', 'make'}


def command_lines(path):
    """Yield (line_no, text, lang, release) for shell command lines in the file's command blocks.

    release is the block's badge (tools/booklib/cephver.py): the oldest release the
    block claims to work on, or 'main'.
    """
    lines = open(path, encoding='utf-8').read().split('\n')
    for start, lang, attrs, body in cephver.blocks(lines):
        if attrs.get('since') == 'none' or lang in _SKIP_LANG:
            continue
        if lang not in cephver.SHELL_LANGS and lang != 'text':
            continue
        rel = cephver.since_of(lang, attrs, body) or cephver.BASELINE
        buf, first = '', None
        for k, raw in enumerate(body):
            ln = start + 2 + k
            if lang == 'text' and not buf and not cephver.PROMPTED.match(raw):
                continue
            s = raw.rstrip()
            if first is None:
                first = ln
            if s.endswith('\\'):
                buf += s[:-1] + ' '
                continue
            yield first, buf + s, lang, rel
            buf, first = '', None
        if buf:
            yield first, buf, lang, rel


_PROMPT_RE = re.compile(r'^\s*(?:\[[^\]]*\]\s*)?[$#]\s+')
_SEPS = {';', '&&', '||', '|', '&', '(', ')', '$(', '`', '{', '}', '!', 'do', 'then', 'else', 'elif', '|&'}
_WRAPPERS = {'sudo', 'time', 'nohup', 'exec', 'env', 'command', 'nice', 'ionice', 'stdbuf'}


def is_placeholder(w: str) -> bool:
    return bool(re.search(r'<[^<>]*>|\$\{?[A-Za-z_]|\$\(|\{[^{}]*\}|\.\.\.|…|^\[.*\]$|^X{3,}$', w))


def shell_words(line: str):
    lex = shlex.shlex(line, posix=True, punctuation_chars=';&|()')
    lex.whitespace_split = True
    lex.commenters = '#'
    return list(lex)


def simple_commands(line: str, lang: str):
    """Split a shell line into simple commands (lists of words) at command positions."""
    text = _PROMPT_RE.sub('', line, count=1) if (lang == 'text' or _PROMPT_RE.match(line)) else line
    if lang != 'text' and line.lstrip().startswith('#') and not re.match(r'^\s*#\s+(?:sudo\s+)?(?:ceph|rbd|rados)', line):
        return []
    if lang != 'text' and line.lstrip().startswith('#'):
        text = line.lstrip()[1:]
    # command substitutions: check the inner command separately, and give the outer
    # command a placeholder word in its place
    inner = []
    while '$(' in text:
        k = text.index('$(')
        depth, j = 0, k + 1
        while j < len(text):
            if text[j] == '(':
                depth += 1
            elif text[j] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        inner.append(text[k + 2:j])
        text = text[:k] + '$SUBST' + text[j + 1:]
    text = text.replace('`', ' ; ')
    try:
        words = shell_words(text)
    except ValueError:
        words = text.split()
    cmds, cur = [], []
    for w in words:
        if w in _SEPS or re.fullmatch(r'[;&|()]+', w):
            if cur:
                cmds.append(cur)
            cur = []
            continue
        cur.append(w)
    if cur:
        cmds.append(cur)
    out = []
    for c in cmds:
        out.extend(unwrap(c))
    for t in inner:
        out.extend(simple_commands(t, 'bash'))
    return out


def unwrap(words):
    """Strip env assignments, sudo/watch/timeout/xargs wrappers; descend into 'cephadm shell -- ...'."""
    i, n = 0, len(words)
    while i < n:
        w = words[i]
        if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*=.*', w):
            i += 1
        elif w in _WRAPPERS:
            i += 1
            while i < n and words[i].startswith('-'):
                i += 2 if words[i] in ('-u', '-g', '-n') else 1
        elif w in ('watch', 'timeout', 'xargs'):
            i += 1
            while i < n and words[i].startswith('-'):
                i += 2 if words[i] in ('-n', '-I', '-s', '-k', '-P', '-d') and i + 1 < n else 1
            if w == 'timeout' and i < n and re.fullmatch(r'\d+[smhd]?', words[i]):
                i += 1
        elif w in ('for', 'while', 'until', 'if', 'case'):
            return []
        else:
            break
    words = words[i:]
    if not words:
        return []
    tool = os.path.basename(words[0])
    words = [tool] + words[1:]
    # redirections end the argument list
    for k, w in enumerate(words):
        if re.fullmatch(r'\d?[<>]{1,2}&?\d?.*', w) and not re.fullmatch(r'<[^<>]+>.*', w):
            words = words[:k]
            break
    res = []
    if tool in ('cephadm', 'kubectl', 'docker', 'podman', 'ssh') and '--' in words:
        k = words.index('--')
        res.extend(unwrap(words[k + 1:]))
        words = words[:k]
    if tool in TOOLS:
        res.insert(0, words)
    return res


def mark(words):
    return [PH + w if is_placeholder(w) else w for w in words]


# --------------------------------------------------------------------------- checkers

def check_ceph(v: Vocab, argv):
    args = mark(argv[1:])
    if any(a in ('-h', '--help') for a in args) or args[:1] == ['help']:
        return None
    rest, i = [], 0
    while i < len(args):
        a = args[i]
        if a.startswith('-') and a not in ('--', '-'):
            name = norm_flag(a)
            if name in v.ceph_flags:
                if '=' not in a and name not in v.ceph_boolflags:
                    i += 1
                i += 1
                continue
            opt = name[2:] if name.startswith('--') else ''
            if opt and v.option_ok(opt) and not opt.startswith('yes'):
                i += 1 if '=' in a else 2
                continue
        rest.append(a)
        i += 1
    if not rest:
        return None                                  # ceph -s, ceph -w, ceph --version
    if rest[0] == 'daemonperf':
        return None
    if rest[0] in ('daemon',) or argv[1:2] == ['--admin-daemon']:
        if rest[0] == 'daemon':
            rest = rest[2:]
        tgt = argv[2] if argv[1:2] == ['daemon'] and len(argv) > 2 else ''
        return validate(v, v.daemon_mon if tgt.startswith('mon') else v.daemon_mgr if tgt.startswith('mgr') else v.asok,
                        rest, 'admin-socket')
    if rest[0] == 'tell' and len(rest) > 1:
        tgt = rest[1]
        if PH not in tgt:
            try:
                v.ap.CephName().valid(tgt)
            except Exception:  # noqa: BLE001
                try:
                    v.ap.CephPgid().valid(tgt)
                except Exception as e:  # noqa: BLE001
                    return f'bad tell target {tgt!r}: {e}'
        table = v.daemon_mon if tgt.startswith('mon') else v.daemon_mgr if tgt.startswith('mgr') else v.asok
        return validate(v, table, rest[2:], 'tell')
    if rest[0] == 'pg' and len(rest) > 2:
        try:
            v.ap.CephPgid().valid(rest[1])
            return validate(v, v.asok, rest[2:], 'pg')
        except Exception:  # noqa: BLE001
            pass
    return validate(v, v.cluster, rest, 'cluster')


def validate(v: Vocab, sigdict, args, where):
    if not args:
        return f'no command after the {where} target'
    buf = io.StringIO()
    with redirect_stderr(buf):
        try:
            d = v.ap.validate_command(sigdict.candidates(args), list(args))
        except Exception as e:  # noqa: BLE001
            d = {}
            print(f'{type(e).__name__}: {e}', file=buf)
    if not d:
        msg = buf.getvalue().strip().splitlines()
        msg = [m for m in msg if m.strip()]
        head = msg[0] if msg else 'no matching command'
        if head.startswith('no valid command found'):
            head = f'unknown {where} command'
            near = [m for m in msg[1:4]]
            if near:
                head += ' (closest: ' + '; '.join(f'`{x[:60]}`' for x in near) + ')'
        else:
            head = '; '.join(msg[:2])
        return head[:300]
    prefix = d.get('prefix', '')
    for cmd in sigdict.values():
        if cmd['flags'] & getattr(v.ap.Flag, 'DEPRECATED', 0) and ' '.join(
                w for w in cmd['raw'] if isinstance(w, str)) == prefix:
            return f'`{prefix}` is deprecated upstream'
    if prefix.startswith('config ') or prefix.startswith('config-'):
        for key in ('name', 'key', 'var'):
            val = d.get(key)
            if isinstance(val, str) and prefix != 'config-key set' and not prefix.startswith('config-key') \
                    and not (prefix == 'config set' and key == 'who'):
                if key == 'name' and prefix in ('config generate-minimal-conf',):
                    continue
                if not v.option_ok(val):
                    return f'unknown config option `{val}`'
    if prefix == 'injectargs':
        for arg in d.get('injected_args', []) or []:
            for tok in str(arg).split():
                if tok.startswith('--') and not v.option_ok(tok[2:].split('=', 1)[0]):
                    return f'unknown config option `{tok[2:]}` in injectargs'
    return None


def split_flags(args, flags_with_values=None, flagset=None):
    """Return (positionals, flags, positionals_if_flags_take_no_values)."""
    pos, pos_nov, fl = [], [], []
    i = 0
    while i < len(args):
        a = args[i]
        if a.startswith('-') and a not in ('-', '--') and not re.fullmatch(r'-\d.*', a):
            fl.append(a)
            if '=' not in a and i + 1 < len(args) and not args[i + 1].startswith('-'):
                pos_nov.append(args[i + 1])
                i += 2
                continue
        else:
            pos.append(a)
            pos_nov.append(a)
        i += 1
    return pos, fl, pos_nov


def bad_flags(flags, vocab, v: Vocab):
    bad = []
    for f in flags:
        if PH in f or is_placeholder(f):
            continue
        n = norm_flag(f)
        if n in vocab:
            continue
        if n.startswith('--') and v.option_ok(n[2:]):     # --<config option> overrides
            continue
        if re.fullmatch(r'-[A-Za-z]{2,}', n) and all(('-' + c) in vocab for c in n[1:]):  # -fv bundles
            continue
        bad.append(f)
    return bad


def match_words(pos_lists, table):
    """Longest command (tuple of words) in table that prefixes one of the positional lists."""
    best = None
    for pos in pos_lists:
        for k in range(min(5, len(pos)), 0, -1):
            if tuple(pos[:k]) in table:
                if not best or k > len(best):
                    best = tuple(pos[:k])
                break
    return best


def check_simple(v: Vocab, tool, argv):
    args = argv[1:]
    if any(a in ('-h', '--help', 'help') for a in args) or not args:
        return None
    pos, flags, pos2 = split_flags(args)
    plist = [mark(pos), mark(pos2)]
    if tool == 'rbd':
        cmd = match_words(plist, v.rbd_actions)
        if not cmd and not any(PH in (p[0] if p else '') for p in plist):
            return f'unknown rbd command `{" ".join(pos2[:3] or pos[:3])}`'
        bad = bad_flags(flags, v.rbd_flags, v)
    elif tool == 'radosgw-admin':
        cmd = match_words(plist, v.rgw_cmds)
        if not cmd and not any(PH in (p[0] if p else '') for p in plist):
            return f'unknown radosgw-admin command `{" ".join(pos2[:3] or pos[:3])}`'
        bad = bad_flags(flags, v.rgw_flags, v)
    elif tool == 'rados':
        firsts = {p[0] for p in plist if p}
        if firsts and not (firsts & v.rados_cmds) and not any(PH in f for f in firsts):
            return f'unknown rados command `{sorted(firsts)[0]}`'
        bad = bad_flags(flags, v.rados_flags, v)
    elif tool == 'cephadm':
        firsts = {p[0] for p in plist if p}
        if firsts and not (firsts & v.cephadm_cmds) and not any(PH in f for f in firsts):
            return f'unknown cephadm command `{sorted(firsts)[0]}`'
        bad = bad_flags(flags, v.cephadm_flags | v.common_flags, v)
    elif tool == 'ceph-volume':
        for p in plist:
            if p and all(w in v.cv_words or PH in w for w in p[:2] if not re.search(r'[/.]', w)):
                break
        else:
            return f'unknown ceph-volume command `{" ".join(pos[:2])}`'
        bad = bad_flags(flags, v.cv_flags, v)
    else:
        fl, known_words, valued = v.offline[tool]
        bad = bad_flags(flags, fl, v)
        for k, a in enumerate(args[:-1]):
            if norm_flag(a) in valued and '=' not in a:
                val = args[k + 1]
                if not is_placeholder(val) and val not in known_words:
                    return f'unknown value `{val}` for `{a}`'
        if tool == 'ceph-bluestore-tool' and pos2 and '--command' not in args:
            firsts = {p[0] for p in (pos, pos2) if p}
            if not (firsts & known_words) and not any(is_placeholder(f) for f in firsts):
                return f'unknown ceph-bluestore-tool command `{pos2[0]}`'
    if bad:
        return 'unknown option(s) ' + ', '.join(f'`{b}`' for b in bad)
    return None


# --------------------------------------------------------------------------- allowlist, report

def load_allowlist(path):
    import yaml
    if not os.path.exists(path):
        return []
    data = yaml.safe_load(open(path, encoding='utf-8')) or []
    out = []
    for e in data:
        out.append((e.get('tool'), re.compile(e['match']), e.get('reason', '')))
    return out


def md_files():
    out = []
    for lang in ('fa', 'en'):
        out += sorted(glob.glob(os.path.join(ROOT, 'content', lang, '**', '*.md'), recursive=True))
    return out


def cheatsheet_items():
    import yaml
    cs_path = os.path.join(ROOT, 'references', 'cheatsheet.yaml')
    if not os.path.exists(cs_path):
        return []
    rel = os.path.relpath(cs_path, ROOT)
    data = yaml.safe_load(open(cs_path, encoding='utf-8')) or {}
    out = []
    idx = 0
    for cat in data.get('categories', []):
        for entry in cat.get('commands', []):
            idx += 1
            cmd = entry.get('cmd', '')
            since = entry.get('since') or cephver.BASELINE
            argvs = simple_commands(cmd, 'bash')
            if not argvs:
                raise ValueError(f'{rel}: command #{idx} ({cmd!r}) produced no recognized Ceph invocation')
            for argv in argvs:
                out.append((f'{rel}:{cat.get("id", "?")}', idx, since, argv))
    return out


def check(v: Vocab, argv):
    try:
        return check_ceph(v, argv) if argv[0] == 'ceph' else check_simple(v, argv[0], argv)
    except Exception as e:  # noqa: BLE001
        return f'checker error: {type(e).__name__}: {e}'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    ap.add_argument('--ceph-src', default=os.environ.get('CEPH_SRC'),
                    help='checkout of ceph/ceph main (default: shallow sparse clone into $TMPDIR)')
    ap.add_argument('--ref', default='main', help='branch or tag to clone when --ceph-src is not given')
    ap.add_argument('--releases', default='labels',
                    help="also check each block against the release its badge names and every later one: "
                         "'labels' (default: the releases used in the book), a comma list, or 'none'")
    ap.add_argument('--release-src', action='append', default=[], metavar='KEY=PATH',
                    help='use a local checkout for a release branch, e.g. reef=/src/ceph-reef')
    ap.add_argument('--allowlist', default=os.path.join(ROOT, 'tools', 'ceph-commands-allowlist.yaml'))
    ap.add_argument('--out', help='write the Markdown report to this path (also printed)')
    ap.add_argument('--strict', action='store_true', help='exit 1 when something is flagged')
    ap.add_argument('--show-allowlisted', action='store_true')
    a = ap.parse_args()

    # every command line, with its block's release badge
    items = []
    for path in md_files():
        rel = os.path.relpath(path, ROOT)
        for ln, line, lang, since in command_lines(path):
            for argv in simple_commands(line, lang):
                items.append((rel, ln, since, argv))
    items.extend(cheatsheet_items())

    order = [k for k, *_ in cephver.RELEASES]
    if a.releases == 'none':
        wanted = []
    elif a.releases == 'labels':
        used = {it[2] for it in items if it[2] in cephver.REL}
        lo = min((order.index(r) for r in used), default=len(order))
        wanted = order[lo:]
    else:
        wanted = [r.strip() for r in a.releases.split(',') if r.strip()]
    local = dict(x.split('=', 1) for x in a.release_src)

    vocabs, notes = {}, []
    src = ensure_source(a.ceph_src, a.ref)
    vocabs['main'] = Vocab(src)
    revs = {'main': src_rev(src)}
    for r in wanted:
        try:
            rs = ensure_source(local.get(r), r)
            vocabs[r] = Vocab(rs)
            revs[r] = src_rev(rs)
        except Exception as e:  # noqa: BLE001
            notes.append(f'- could not load the `{r}` branch ({type(e).__name__}); blocks labelled {r} were checked against main only')

    allow = load_allowlist(a.allowlist)
    used_allow = set()
    stats = defaultdict(lambda: {'n': 0, 'ok': 0, 'allow': 0, 'bad': 0})
    problems = defaultdict(lambda: {'msg': '', 'where': []})
    allowed_rows = defaultdict(list)
    cache = {}
    for rel, ln, since, argv in items:
        tool = argv[0]
        st = stats[tool]
        st['n'] += 1
        inv = ' '.join(shlex.quote(w) if re.search(r'\s', w) else w for w in argv)
        targets = ['main'] + ([r for r in order[order.index(since):] if r in vocabs] if since in order else [])
        fails = []
        for r in targets:
            key = (r, tuple(argv))
            if key not in cache:
                cache[key] = check(vocabs[r], argv)
            if cache[key]:
                fails.append((r, cache[key]))
        if not fails:
            st['ok'] += 1
            continue
        if fails[0][0] == 'main':
            msg = fails[0][1]
        else:
            rels = ', '.join(cephver.REL[r][1] for r, _ in fails)
            label = cephver.label(since) if since in cephver.REL else since
            msg = f'not accepted by {rels} (block badge: {label}): {fails[0][1]}'
        hit = next((k for k, (t, rx, _) in enumerate(allow) if (t in (None, tool)) and rx.search(inv)), None)
        if hit is not None:
            st['allow'] += 1
            used_allow.add(hit)
            allowed_rows[hit].append(f'{rel}:{ln}')
            continue
        st['bad'] += 1
        p = problems[(tool, inv)]
        p['msg'] = msg
        p['where'].append(f'{rel}:{ln}')

    checked = ', '.join(f'[`{r}`@{revs[r][:10]}](https://github.com/ceph/ceph/tree/{revs[r]})' for r in vocabs)
    lines = [
        f'Checked against ceph/ceph {checked}. `ceph` lines go through the real argument parser '
        '(src/pybind/ceph_argparse.py) with the monitor, manager-module and admin-socket command tables '
        'and the config option schema; the other tools are checked against their command and option tables. '
        'Every line is checked against main, and against the release its block badge names and every later '
        'release branch.',
        '',
        '| Tool | Invocations | OK | Allowlisted | Flagged |',
        '|---|---:|---:|---:|---:|',
    ]
    for tool in TOOLS:
        s_ = stats.get(tool)
        if s_:
            lines.append(f'| `{tool}` | {s_["n"]} | {s_["ok"]} | {s_["allow"]} | {s_["bad"]} |')
    tot = {k: sum(x[k] for x in stats.values()) for k in ('n', 'ok', 'allow', 'bad')}
    lines.append(f'| **total** | {tot["n"]} | {tot["ok"]} | {tot["allow"]} | {tot["bad"]} |')
    lines.append('')
    lines += notes + ([''] if notes else [])
    if problems:
        lines += ['### Flagged', '',
                  'Each row is a command line that Ceph does not accept as written (on main, or on a release '
                  'its badge claims). Fix the book in both fa and en (or the `since=` badge), or add a reasoned '
                  'entry to `tools/ceph-commands-allowlist.yaml` if the line is right.', '',
                  '| Invocation | Problem | Where |', '|---|---|---|']
        for (tool, inv), p in sorted(problems.items(), key=lambda kv: (kv[0][0], kv[1]['where'][0])):
            w = ', '.join(f'`{x}`' for x in p['where'][:4]) + (f' (+{len(p["where"]) - 4})' if len(p['where']) > 4 else '')
            cell = inv.replace('|', '\\|')[:160]
            lines.append(f'| `{cell}` | {p["msg"].replace("|", "\\|")} | {w} |')
        lines.append('')
    else:
        lines += ['No command line in the book was flagged.', '']
    stale = [k for k in range(len(allow)) if k not in used_allow]
    if stale:
        lines += ['### Unused allowlist entries', '', 'These entries no longer match a flagged line and can be removed:', '']
        lines += [f'- `{allow[k][1].pattern}`' for k in stale]
        lines.append('')
    if a.show_allowlisted:
        lines += ['### Allowlisted', '']
        for k, where in allowed_rows.items():
            lines.append(f'- `{allow[k][1].pattern}` ({allow[k][2]}): {len(where)} line(s), e.g. `{where[0]}`')
    body = '\n'.join(lines) + '\n'
    print(body)
    if a.out:
        open(a.out, 'w', encoding='utf-8').write(body)
    print(f'check-ceph-commands: {tot["n"]} invocation(s), {tot["bad"]} flagged, {tot["allow"]} allowlisted '
          f'({", ".join(vocabs)})', file=sys.stderr)
    return 1 if a.strict and problems else 0


if __name__ == '__main__':
    sys.exit(main())
