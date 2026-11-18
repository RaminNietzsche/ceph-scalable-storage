#!/usr/bin/env python3
"""Regenerate the reference data the web simulators are tested against.

Usage: CEPH_SRC=/path/to/ceph/src tools/simref/gen_golden.py [--table]

Needs an unmodified Ceph source tree, gcc and g++ (C++20; set CXX if g++ has another name). Writes tests/sims/golden.json:
  * CRUSH mappings from Ceph's own src/crush C code (compiled with crush_ref.c),
    for replicated (chooseleaf firstn) and erasure (chooseleaf indep) rules over
    several hierarchies, weights, reweights and out OSDs, through the pool
    path pps = crush_hash32_2(ceph_stable_mod(ps, pgp_num, mask), pool);
  * crush_hash32_2/_3, ceph_str_hash_rjenkins, straw2 draws and a checksum of
    all 65536 crush_ln() values;
  * crush_hash32_4, crush_bucket_choose of single uniform, list, tree, straw and
    straw2 buckets (with the bucket weights and straw lengths builder.c computes),
    and crush_do_rule over maps built entirely of each bucket algorithm (and maps
    that mix them), with straw_calc_version 1 as set by the jewel tunables;
  * Striper::file_to_extents, object_truncate_size, get_num_objects and
    get_file_offset, copied verbatim out of src/osdc/Striper.cc and compiled with
    g++ (striper_ref.cc), over random layouts including fancy striping, and RBD
    data object names as librbd builds them (with and without a data pool);
  * erasure coding: ECUtil::stripe_info_t (ro_range_to_shards, object_size_to_shard_size,
    ro_offset_to_shard_offset, shard_offset_to_ro_offset), jerasure reed_sol_van
    get_chunk_size and OSDMap::_raw_to_up_osds/_pick_primary, copied verbatim and
    compiled with g++ (ec_ref.cc), and CRUSH indep rules for k+m shards with out
    OSDs and NONE holes, with down OSDs applied for EC and replicated pools;
  * pg_autoscaler targets from Ceph's own src/pybind/mgr/pg_autoscaler/module.py
    (imported with small stand-ins for the mgr runtime) for several pool sets.
With --table it also rewrites templates/site/sims/crush-ln-table.js from
src/crush/crush_ln_table.h. tests/sims/test_core.js checks the JavaScript port
(templates/site/sims/sim-core.js) against this file; it does not need Ceph.
"""
from __future__ import annotations

import hashlib
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import types

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
SRC = os.environ.get('CEPH_SRC')
if not SRC or not os.path.isfile(os.path.join(SRC, 'crush', 'mapper.c')):
    sys.exit('set CEPH_SRC to the src/ directory of a Ceph checkout')


def git_rev():
    try:
        return subprocess.run(['git', '-C', SRC, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return 'unknown'


# ---------------------------------------------------------------- crush_ln table
def ln_tables():
    h = open(os.path.join(SRC, 'crush', 'crush_ln_table.h'), encoding='utf-8').read()
    out = {}
    for name in ('__RH_LH_tbl', '__LL_tbl'):
        m = re.search(re.escape(name) + r'\[[^\]]*\]\s*=\s*\{(.*?)\};', h, re.S)
        out[name] = [int(x, 16) for x in re.findall(r'0x([0-9a-fA-F]+)u?ll', m.group(1))]
    return out


if '--table' in sys.argv:
    t = ln_tables()
    def rows(v):
        return ',\n'.join('  ' + ', '.join(str(x) for x in v[i:i + 6]) for i in range(0, len(v), 6))
    js = ('/*\n * crush_ln() lookup tables, transcribed from ceph/ceph src/crush/crush_ln_table.h\n'
          ' * Copyright (C) 2015 Intel Corporation. Licensed under the GNU Lesser General Public\n'
          ' * License version 2.1 (upstream licence kept; this file is NOT covered by the book\'s\n'
          ' * CC BY-NC-SA 4.0 licence). Regenerate with tools/simref/gen_golden.py --table.\n'
          ' * RH_LH[2k] = 2^48/(1+k/128), RH_LH[2k+1] = 2^48*log2(1+k/128); LL[k] ~ 2^48*log2(1+k/2^15).\n'
          ' * All values are below 2^53, so plain numbers hold them exactly.\n */\n'
          '(function (root) {\n  var T = {\n  RH_LH: [\n' + rows(t['__RH_LH_tbl']) + '],\n  LL: [\n' + rows(t['__LL_tbl']) + ']\n  };\n'
          "  if (typeof module !== 'undefined' && module.exports) module.exports = T; else root.CRUSH_LN_TABLE = T;\n"
          "})(typeof self !== 'undefined' ? self : this);\n")
    open(os.path.join(ROOT, 'templates', 'site', 'sims', 'crush-ln-table.js'), 'w', encoding='utf-8').write(js)
    print('wrote crush-ln-table.js')

# ---------------------------------------------------------------- build harness
tmp = tempfile.mkdtemp(prefix='crushref-')
open(os.path.join(tmp, 'acconfig.h'), 'w').close()
inc = ['-I' + tmp, '-I' + SRC, '-I' + os.path.join(SRC, 'crush')]
objs = []
for f in ('hash', 'crush', 'builder'):
    o = os.path.join(tmp, f + '.o')
    subprocess.run(['gcc', '-O1', '-w', *inc, '-c', os.path.join(SRC, 'crush', f + '.c'), '-o', o], check=True)
    objs.append(o)
exe = os.path.join(tmp, 'crush_ref')
subprocess.run(['gcc', '-O1', '-w', *inc, '-x', 'c', os.path.join(ROOT, 'tools', 'simref', 'crush_ref.c'), '-x', 'none', *objs, '-lm', '-o', exe], check=True)


def run(lines):
    r = subprocess.run([exe], input='\n'.join(lines) + '\n', capture_output=True, text=True, check=True)
    return r.stdout.split('\n')[:-1]


rnd = random.Random(20261115)
gold = {'ceph_rev': git_rev(), 'note': 'generated by tools/simref/gen_golden.py from an unmodified Ceph tree'}

# hashes
h2 = [[rnd.getrandbits(32), rnd.getrandbits(32)] for _ in range(200)] + [[0, 0], [1, 2], [4294967295, 7]]
h3 = [[rnd.getrandbits(32), rnd.getrandbits(32) if i % 3 else (-rnd.randint(1, 40)) & 0xffffffff, rnd.randint(0, 60)] for i in range(200)]
names = ['', 'a', 'foo', 'rbd_data.10226b8b4567.0000000000000000', 'rbd_header.10226b8b4567', 'photo.jpg',
         'the quick brown fox jumps', '12345678901', '123456789012', '1234567890123', 'فارسی', 'obj-%d' % 7, 'photos/2026/11/img_0001.jpg', 'photos/2026/11/img_0002.jpg', 'logs/app.log']
names += ['obj-%d' % rnd.randint(0, 10 ** 6) for _ in range(40)]
draws = [[rnd.getrandbits(31), -rnd.randint(1, 30) if i % 2 else rnd.randint(0, 40), rnd.randint(0, 12),
          rnd.choice([1, 0x8000, 0x10000, 0x1999a, 0x30000, 0x3ccc, 0x100000, 0xfffff])] for i in range(300)]
lines = [f'H2 {a} {b}' for a, b in h2] + [f'H3 {a} {b} {c}' for a, b, c in h3]
lines += [f'STR {n.encode().hex() or "-"}' for n in names]
lines += [f'DRAW {x} {y} {z} {w}' for x, y, z, w in draws] + ['LN']
out = run(lines)
i = 0
gold['hash32_2'] = [[a, b, int(out[i + k])] for k, (a, b) in enumerate(h2)]; i += len(h2)
gold['hash32_3'] = [[a, b, c, int(out[i + k])] for k, (a, b, c) in enumerate(h3)]; i += len(h3)
gold['str_hash'] = [[n, int(out[i + 2 * k])] for k, n in enumerate(names)]
gold['str_hash_linux'] = [[n, int(out[i + 2 * k + 1])] for k, n in enumerate(names)]; i += 2 * len(names)
gold['draw'] = [[x, y, z, w, int(out[i + k])] for k, (x, y, z, w) in enumerate(draws)]; i += len(draws)
lnv = out[i:i + 65536]
gold['ln'] = {'sha256': hashlib.sha256('\n'.join(lnv).encode()).hexdigest(), 'sample': {str(u): int(lnv[u]) for u in (0, 1, 2, 255, 256, 4095, 32767, 32768, 65534, 65535)}}

# CRUSH maps: osd=0 host=1 rack=3 root=11 (default types); rule steps as CrushWrapper::add_simple_rule_at
TAKE, CHOOSE_FIRSTN, CHOOSE_INDEP, EMIT, CL_FIRSTN, CL_INDEP, SET_CT, SET_CLT = 1, 2, 3, 4, 6, 7, 8, 9


def mk_map(hosts, rnd_w):
    """hosts: list of per-host OSD counts. Returns map dict like sim-core's CRUSH model."""
    osd, buckets, hid = 0, [], -2
    host_items = []
    for n in hosts:
        items = []
        for _ in range(n):
            w = rnd_w()
            items.append([osd, w]); osd += 1
        buckets.append({'id': hid, 'type': 1, 'items': items})
        host_items.append([hid, sum(w for _, w in items)])
        hid -= 1
    buckets.append({'id': -1, 'type': 11, 'items': host_items})
    return {'ndev': osd, 'buckets': buckets}


def rules():
    return {
        0: {'type': 1, 'steps': [[TAKE, -1, 0], [CL_FIRSTN, 0, 1], [EMIT, 0, 0]]},
        1: {'type': 3, 'steps': [[SET_CLT, 5, 0], [SET_CT, 100, 0], [TAKE, -1, 0], [CL_INDEP, 0, 1], [EMIT, 0, 0]]},
        2: {'type': 1, 'steps': [[TAKE, -1, 0], [CHOOSE_FIRSTN, 0, 0], [EMIT, 0, 0]]},
        3: {'type': 3, 'steps': [[SET_CLT, 5, 0], [SET_CT, 100, 0], [TAKE, -1, 0], [CHOOSE_INDEP, 0, 0], [EMIT, 0, 0]]},
    }


W1 = 0x10000
cases = []
specs = [
    ('3x3 equal', [3, 3, 3], lambda: W1),
    ('4 hosts mixed', [2, 3, 4, 3], lambda: rnd.choice([W1, 2 * W1, 0x1999a, 0x8000, 0x3ccc0])),
    ('5 hosts for EC', [2, 2, 2, 2, 2], lambda: rnd.choice([W1, W1, 0x20000])),
    ('6 hosts big', [4, 4, 4, 4, 4, 4], lambda: rnd.choice([0x3a333, 0x74666, 0xe8ccc])),
    ('2 hosts tight', [2, 2], lambda: W1),
    ('7 hosts small', [1, 2, 1, 3, 1, 2, 1], lambda: rnd.choice([W1, 0x18000, 0x6000])),
]
for name, hosts, rw in specs:
    m = mk_map(hosts, rw)
    nd = m['ndev']
    for variant in ('all in', 'outs', 'reweight'):
        wv = [0x10000] * nd
        if variant == 'outs':
            for k in rnd.sample(range(nd), max(1, nd // 5)):
                wv[k] = 0
        elif variant == 'reweight':
            for k in rnd.sample(range(nd), max(1, nd // 3)):
                wv[k] = rnd.choice([0x8000, 0xc000, 0x4000, 0xe666])
        for rno, size in ((0, 3), (0, 2), (1, 5), (1, 6), (2, 3), (3, 4)):
            pgp = rnd.choice([32, 64, 100, 128])
            cases.append({'name': f'{name} / {variant} / rule {rno} size {size}', 'map': m, 'weights': wv, 'rule': rno,
                          'size': size, 'pgp_num': pgp, 'pool': rnd.randint(1, 9)})
lines = []
for c in cases:
    m = c['map']
    lines.append('MAP')
    lines.append('TUN 0 0 50 1 1 1')                      # CrushWrapper::set_tunables_jewel/optimal
    for b in m['buckets']:
        lines.append(f'B {b["id"]} {b["type"]} {len(b["items"])} ' + ' '.join(f'{i} {w}' for i, w in b['items']))
    for no, r in rules().items():
        lines.append(f'R {no} {r["type"]} {len(r["steps"])} ' + ' '.join(f'{a} {b} {cc}' for a, b, cc in r['steps']))
    lines.append('FIN')
    lines.append(f'W {m["ndev"]} ' + ' '.join(str(x) for x in c['weights']))
    lines.append(f'Q {c["rule"]} 0 {c["pgp_num"]} {c["size"]} {c["pgp_num"]} {c["pool"]}')
    lines.append('END')
out = run(lines)
k = 0
for c in cases:
    res = []
    for _ in range(c['pgp_num']):
        v = [int(x) for x in out[k].split()]
        res.append(v[1:]); k += 1
    c['expect'] = res
gold['crush_rules'] = rules()
gold['crush'] = cases

# ---------------------------------------------------------------- pg_autoscaler (real module, stubbed runtime)
sys.path.insert(0, os.path.join(SRC, 'pybind', 'mgr'))
for modname in ('mgr_module', 'mgr_util', 'prettytable'):
    mod = types.ModuleType(modname)
    sys.modules[modname] = mod
mm = sys.modules['mgr_module']


class _MgrModule:
    def __init__(self, *a, **k):
        import logging
        self.log = logging.getLogger('pgas')

    def get_module_option(self, *a, **k):
        return None


class _Option:
    def __init__(self, *a, **k):
        pass


mm.MgrModule, mm.Option, mm.CRUSHMap, mm.OSDMap = _MgrModule, _Option, object, object
mm.HealthChecksT = dict
class _CLI:
    def __init__(self, *a, **k):
        pass

    def __call__(self, f):
        return f

    @classmethod
    def make_registry_subtype(cls, name):
        return type(name, (cls,), {})

    @classmethod
    def Read(cls, *a, **k):
        return lambda f: f

    @classmethod
    def Write(cls, *a, **k):
        return lambda f: f


mm.CLICommandBase = mm.CLICommand = _CLI
sys.modules['prettytable'].PrettyTable = object


class _AnyAttr(types.ModuleType):
    def __getattr__(self, n):
        return lambda *a, **k: (lambda f: f)


sys.modules['mgr_util'] = _AnyAttr('mgr_util')
try:
    from pg_autoscaler import module as pgas  # noqa: E402
except Exception as e:  # pragma: no cover
    sys.exit(f'cannot import pg_autoscaler/module.py with stubs: {e}')


class _Root:
    def __init__(self, osds, target_per_osd):
        self.pg_target = target_per_osd * osds
        self.pg_left = self.pg_target
        self.pool_count = 0
        self.pool_used = 0
        self.capacity = 1


def autoscale(osds, target_per_osd, pools, default_pg_num=32, threshold=3.0):
    """pools: list of dicts name,size,ratio,bulk,autoscale,pg_num. Mirrors _get_pool_status() for one root."""
    a = pgas.PgAutoscaler('pg_autoscaler', 0, 0)
    a.osd_pool_default_pg_num = default_pg_num
    root = _Root(osds, target_per_osd)
    root.pool_count = len(pools)
    groups = {}
    ps = {}
    for i, p in enumerate(pools):
        d = {'pool': i, 'pool_name': p['name'], 'size': p['size'], 'pg_num_target': p['pg_num'],
             'pg_autoscale_mode': 'on' if p['autoscale'] else 'off', 'options': {}}
        ps[i] = d
        pg_target = int(p['ratio'] * root.pg_left) if p['autoscale'] else p['pg_num'] * p['size']
        key = pgas.GroupKey(pg_target, p['size'], 1.0, p['bulk'], p['autoscale'])
        if key not in groups:
            groups[key] = pgas.PoolGroup(pg_target, p['size'], 1.0, p['autoscale'])
        groups[key].add(p['name'], d)
    res = {}
    for fp in ('first', 'second', 'third', 'fourth'):
        fr, ppt, finals, outp = a._calculate_final_pool_pg_target({0: root}, 0, fp, groups)
        fail = False
        rows = []
        for r_, t_, fin, p in zip(fr, ppt, finals, outp):
            if r_ is None:
                continue
            root.pg_left -= fin * p['size']
            if root.pg_left < 0:
                fail = True
            if fin > p['pg_num_target']:
                dyn = a.get_dynamic_threshold(fin, threshold)
                adj = fin > p['pg_num_target'] * dyn
            else:
                adj = fin < p['pg_num_target'] / threshold
            adj = bool(adj and 0.0 <= r_ <= 1.0 and p['pg_autoscale_mode'] == 'on')
            rows.append([p['pool_name'], fp, fin, round(r_, 9), adj])
        for row in rows:
            if fail:
                row[4] = False
            res[row[0]] = row
    return [res[p['name']] for p in pools]


ascases = [
    (12, 100, [{'name': 'rbd', 'size': 3, 'ratio': 0.6, 'bulk': False, 'autoscale': True, 'pg_num': 32},
               {'name': 'meta', 'size': 3, 'ratio': 0.01, 'bulk': False, 'autoscale': True, 'pg_num': 32}]),
    (24, 200, [{'name': 'rbd', 'size': 3, 'ratio': 0.45, 'bulk': True, 'autoscale': True, 'pg_num': 128},
               {'name': 'ec', 'size': 6, 'ratio': 0.30, 'bulk': True, 'autoscale': True, 'pg_num': 64},
               {'name': '.mgr', 'size': 3, 'ratio': 0.0, 'bulk': False, 'autoscale': True, 'pg_num': 1},
               {'name': 'rgw.meta', 'size': 3, 'ratio': 0.02, 'bulk': False, 'autoscale': True, 'pg_num': 32}]),
    (6, 200, [{'name': 'a', 'size': 2, 'ratio': 0.2, 'bulk': True, 'autoscale': True, 'pg_num': 32},
              {'name': 'b', 'size': 2, 'ratio': 0.2, 'bulk': True, 'autoscale': True, 'pg_num': 32},
              {'name': 'c', 'size': 3, 'ratio': 0.1, 'bulk': False, 'autoscale': False, 'pg_num': 64}]),
    (100, 100, [{'name': 'data', 'size': 3, 'ratio': 0.8, 'bulk': False, 'autoscale': True, 'pg_num': 256},
                {'name': 'idx', 'size': 3, 'ratio': 0.05, 'bulk': False, 'autoscale': True, 'pg_num': 32},
                {'name': 'old', 'size': 3, 'ratio': 0.1, 'bulk': False, 'autoscale': False, 'pg_num': 512}]),
    (48, 200, [{'name': 'p%d' % i, 'size': 3, 'ratio': r, 'bulk': i % 2 == 0, 'autoscale': True, 'pg_num': 32}
               for i, r in enumerate([0.3, 0.25, 0.15, 0.1, 0.05, 0.0])]),
]
gold['autoscaler'] = [{'osds': o, 'target': t, 'pools': p, 'expect': autoscale(o, t, p)} for o, t, p in ascases]

# ---------------------------------------------------------------- the five bucket algorithms
# Its own random stream, so everything above stays byte-for-byte what it was.
ra = random.Random(20261118)
ALGS = {'uniform': 1, 'list': 2, 'tree': 3, 'straw': 4, 'straw2': 5}
ALGS_LIST = list(ALGS)[::-1]
h4 = [[ra.getrandbits(32), ra.getrandbits(32) if i % 3 else (-ra.randint(1, 40)) & 0xffffffff, ra.randint(0, 60), (-ra.randint(1, 40)) & 0xffffffff] for i in range(150)]
out = run([f'H4 {a} {b} {c} {d}' for a, b, c, d in h4])
gold['hash32_4'] = [[a, b, c, d, int(out[k])] for k, (a, b, c, d) in enumerate(h4)]


def bweight(alg, ws):
    """builder.c: bucket weight (uniform: size * first item weight)."""
    return (len(ws) * ws[0] if ws else 0) if alg == 'uniform' else sum(ws)


# one bucket at a time: crush_bucket_choose for r = 0 .. size+2 in one workspace (uniform keeps its permutation)
bcases = []
for alg in ALGS:
    for size in (1, 2, 3, 4, 5, 7, 8, 12):
        items = ra.sample(range(0, 60), size)
        if alg == 'uniform':
            ws = [ra.choice([W1, 0x20000, 0x3ccc0])] * size
        else:
            ws = [ra.choice([W1, 2 * W1, 0x1999a, 0x8000, 0x3ccc0, 0x74666, 0]) for _ in range(size)]
            if not any(ws):
                ws[0] = W1
        bid = -1 - ra.randint(0, 6)
        bcases.append({'alg': alg, 'id': bid, 'items': items, 'weights': ws,
                       'xs': [ra.getrandbits(32) if k % 4 else ra.randint(0, 1000) for k in range(40)], 'rmax': size + 3})
lines = []
for c in bcases:
    lines += ['MAP', 'TUN 0 0 50 1 1 1', 'SCV 1',
              f'BA {ALGS[c["alg"]]} {c["id"]} 1 {len(c["items"])} ' + ' '.join(f'{i} {w}' for i, w in zip(c['items'], c['weights'])),
              'FIN', f'BW {c["id"]}']
    if c['alg'] == 'straw':
        lines.append(f'BS {c["id"]}')
    lines += [f'BC {c["id"]} {x} {c["rmax"]}' for x in c['xs']]
    lines.append('END')
out = run(lines)
k = 0
for c in bcases:
    c['weight'] = int(out[k]); k += 1
    if c['alg'] == 'straw':
        c['straws'] = [int(v) for v in out[k].split()]; k += 1
    c['expect'] = []
    for _ in c['xs']:
        c['expect'].append([int(v) for v in out[k].split()]); k += 1
gold['bucket_choose'] = bcases

# whole maps: root -> hosts -> osds with every bucket of one algorithm (and some mixed maps), through crush_do_rule
acases = []
aspecs = [
    ('3x3 equal', [3, 3, 3], lambda: W1),
    ('4 hosts mixed', [2, 3, 4, 3], lambda: ra.choice([W1, 2 * W1, 0x1999a, 0x8000, 0x3ccc0])),
    ('5x2', [2, 2, 2, 2, 2], lambda: ra.choice([W1, W1, 0x20000])),
    ('6 hosts uneven', [1, 2, 3, 4, 2, 3], lambda: ra.choice([0x3a333, 0x74666, 0xe8ccc, W1])),
    ('2 hosts tight', [2, 2], lambda: W1),
    ('8x4 equal', [4] * 8, lambda: W1),
]
for alg in list(ALGS) + ['mixed']:
    for name, hosts, rw in aspecs:
        osd, buckets, hitems = 0, [], []
        for hi, n in enumerate(hosts):
            halg = ALGS_LIST[hi % 5] if alg == 'mixed' else alg
            items = []
            for _ in range(n):
                items.append([osd, rw()]); osd += 1
            if halg == 'uniform':
                items = [[i, items[0][1]] for i, _ in items]
            buckets.append({'id': -2 - hi, 'type': 1, 'alg': halg, 'items': items})
            hitems.append([-2 - hi, bweight(halg, [w for _, w in items])])
        ralg = 'straw2' if alg == 'mixed' else alg
        buckets.append({'id': -1, 'type': 11, 'alg': ralg, 'items': hitems})
        m = {'ndev': osd, 'buckets': buckets}
        for variant in ('all in', 'outs', 'reweight'):
            wv = [0x10000] * osd
            if variant == 'outs':
                for kk in ra.sample(range(osd), max(1, osd // 5)):
                    wv[kk] = 0
            elif variant == 'reweight':
                for kk in ra.sample(range(osd), max(1, osd // 3)):
                    wv[kk] = ra.choice([0x8000, 0xc000, 0x4000, 0xe666])
            for rno, size in ((0, 3), (0, 2), (2, 3), (1, 4)):
                pgp = ra.choice([16, 32, 48, 64])
                acases.append({'name': f'{alg} / {name} / {variant} / rule {rno} size {size}', 'map': m, 'weights': wv,
                               'rule': rno, 'size': size, 'pgp_num': pgp, 'pool': ra.randint(1, 9)})
lines = []
for c in acases:
    m = c['map']
    lines += ['MAP', 'TUN 0 0 50 1 1 1', 'SCV 1']
    for b in m['buckets']:
        lines.append(f'BA {ALGS[b["alg"]]} {b["id"]} {b["type"]} {len(b["items"])} ' + ' '.join(f'{i} {w}' for i, w in b['items']))
    for no, r in rules().items():
        lines.append(f'R {no} {r["type"]} {len(r["steps"])} ' + ' '.join(f'{a} {b} {cc}' for a, b, cc in r['steps']))
    lines += ['FIN', f'W {m["ndev"]} ' + ' '.join(str(x) for x in c['weights']),
              f'Q {c["rule"]} 0 {c["pgp_num"]} {c["size"]} {c["pgp_num"]} {c["pool"]}', 'END']
out = run(lines)
k = 0
for c in acases:
    c['expect'] = []
    for _ in range(c['pgp_num']):
        c['expect'].append([int(x) for x in out[k].split()][1:]); k += 1
gold['crush_algs'] = acases

# upstream unit-test vectors for Striper (src/test/test_striper.cc)
gold['striper_upstream'] = 'src/test/test_striper.cc (Stripe1, EmptyPartialResult, GetNumObj, GetFileOffset)'

# ---------------------------------------------------------------- RBD striping and object names
# The upstream Striper code is copied out of src/osdc/Striper.cc verbatim and compiled with g++
# (tools/simref/striper_ref.cc) against the real src/osdc/StriperTypes.h.
def cut(src, start):
    i = src.index(start)
    j = src.index('\n}\n', i)
    return src[i:j + 3]


stc = open(os.path.join(SRC, 'osdc', 'Striper.cc'), encoding='utf-8').read()
order_by = stc[stc.index('struct OrderByObject {'):stc.index('};', stc.index('struct OrderByObject {')) + 2]
fte = re.search(r'void Striper::file_to_extents\(\s*CephContext \*cct, const file_layout_t \*layout, uint64_t offset,', stc)
parts = ['namespace {\n' + order_by + '\n}\n', cut(stc[fte.start():], 'void Striper::file_to_extents(')]
for sig in ('uint64_t Striper::object_truncate_size(', 'uint64_t Striper::get_num_objects(', 'uint64_t Striper::get_file_offset('):
    parts.append(cut(stc, sig))
stmp = tempfile.mkdtemp(prefix='striperref-')
os.makedirs(os.path.join(stmp, 'boost', 'container'))
os.makedirs(os.path.join(stmp, 'include'))
open(os.path.join(stmp, 'boost', 'container', 'small_vector.hpp'), 'w').write(
    '#pragma once\n#include <vector>\n#include <cstddef>\n'
    'namespace boost { namespace container { template <class T, std::size_t N> using small_vector = std::vector<T>; } }\n')
open(os.path.join(stmp, 'include', 'container_ios.h'), 'w').write(
    '#pragma once\n#include <ostream>\n#include <vector>\n#include <utility>\n'
    'namespace striper { template <class A, class B> std::ostream& operator<<(std::ostream& o, const std::vector<std::pair<A, B>>&) { return o; } }\n')
open(os.path.join(stmp, 'striper_extract.inc'), 'w').write('\n'.join(parts))
sexe = os.path.join(stmp, 'striper_ref')
subprocess.run([os.environ.get('CXX', 'g++'), '-O1', '-w', '-std=c++17', '-I' + stmp, '-I' + SRC, os.path.join(ROOT, 'tools', 'simref', 'striper_ref.cc'), '-o', sexe], check=True)
rs = random.Random(1405)                    # its own stream: the data above stays as it was
scases, sq = [], []
for t in range(160):
    order = rs.choice([12, 16, 20, 22, 22, 23, 25])
    os_ = 1 << order
    su = os_ >> rs.randint(0, min(6, order - 9))
    sc = rs.choice([1, 1, 2, 3, 4, 8, 16])
    off = rs.randint(0, 40 * os_ * sc) if t % 4 else rs.randint(0, 2 ** 40)
    ln = rs.randint(1, 5 * os_ * sc) if t % 3 else rs.randint(1, su * 2)
    trunc = 0 if t % 2 else rs.randint(0, off + ln + os_ * sc)
    bo = rs.choice([0, 0, rs.randint(0, 1 << 20)])
    scases.append({'layout': [os_, su, sc], 'off': off, 'len': ln, 'trunc': trunc, 'bo': bo})
    sq.append(f'F {os_} {su} {sc} {off} {ln} {trunc} {bo}')
ncases = []
for t in range(80):
    os_ = 1 << rs.choice([12, 16, 22, 25]); su = os_ >> rs.randint(0, 4); sc = rs.choice([1, 2, 3, 4, 8])
    if sc == 1:
        su = os_                            # librbd and Striper treat a stripe_count of 1 as su = os
    size = rs.choice([rs.randint(1, 3 * os_ * sc), rs.randint(1, 2 ** 42)])
    o, oo = rs.randint(0, 5000), rs.randint(0, os_ - 1)
    ncases.append({'layout': [os_, su, sc], 'size': size, 'objno': o, 'ooff': oo})
    sq += [f'N {os_} {su} {sc} {size}', f'O {os_} {su} {sc} {o} {oo}', f'T {os_} {su} {sc} {o} {size}']
names = [('10226b8b4567', -1, 0), ('10226b8b4567', -1, 255), ('1d6f2a8c4e93', -1, 2559), ('1d6f2a8c4e93', 2, 2559),
         ('5e1a9f3c27b44d', 7, 0xfffffffff), ('ab12', 12, 1)]
sq += [f'D {i} {p} {o}' for i, p, o in names]
r = subprocess.run([sexe], input='\n'.join(sq) + '\n', capture_output=True, text=True, check=True).stdout.split('\n')
k = 0
for c in scases:
    n = int(r[k]); k += 1
    c['expect'] = []
    for _ in range(n):
        f = r[k].split(); k += 1
        c['expect'].append([int(x) for x in f[:4]] + [[int(y) for y in b.split(',')] for b in f[4:]])
for c in ncases:
    c['num_objects'], c['file_offset'], c['trunc'] = int(r[k]), int(r[k + 1]), int(r[k + 2]); k += 3
gold['striper'] = {'file_to_extents': scases, 'layout_fns': ncases,
                   'rbd_data_names': [[i, p, o, r[k + j]] for j, (i, p, o) in enumerate(names)]}

# ---------------------------------------------------------------- erasure coding
# ECUtil stripe_info_t arithmetic, jerasure's chunk size and OSDMap's raw -> up step, copied verbatim
# out of the Ceph tree and compiled with g++ (tools/simref/ec_ref.cc); CRUSH indep rules from crush_ref.c.
def block(src, sig):
    """The text from sig to the brace that closes its body."""
    i = src.index(sig)
    j = src.index('{', i)
    depth = 0
    for q in range(j, len(src)):
        if src[q] == '{':
            depth += 1
        elif src[q] == '}':
            depth -= 1
            if depth == 0:
                return src[i:q + 1] + '\n'
    raise ValueError(sig)


ech = open(os.path.join(SRC, 'osd', 'ECUtil.h'), encoding='utf-8').read()
ecc = open(os.path.join(SRC, 'osd', 'ECUtil.cc'), encoding='utf-8').read()
jer = open(os.path.join(SRC, 'erasure-code', 'jerasure', 'ErasureCodeJerasure.cc'), encoding='utf-8').read()
osm = open(os.path.join(SRC, 'osd', 'OSDMap.cc'), encoding='utf-8').read()
etmp = tempfile.mkdtemp(prefix='ecref-')
open(os.path.join(etmp, 'ec_extract_inline.inc'), 'w').write(block(ech, 'inline uint64_t align_next(uint64_t val)'))
open(os.path.join(etmp, 'ec_extract_methods.inc'), 'w').write(''.join(block(ech, sig) for sig in (
    'uint64_t object_size_to_shard_size(', 'uint64_t ro_offset_to_shard_offset(', 'uint64_t shard_offset_to_ro_offset(')))
open(os.path.join(etmp, 'ec_extract_cc.inc'), 'w').write(block(ecc, 'void ECUtil::stripe_info_t::ro_range_to_shards('))
open(os.path.join(etmp, 'ec_extract_jerasure.inc'), 'w').write(
    block(jer, 'unsigned int ErasureCodeJerasure::get_chunk_size(') + block(jer, 'unsigned ErasureCodeJerasureReedSolomonVandermonde::get_alignment()'))
open(os.path.join(etmp, 'ec_extract_osdmap.inc'), 'w').write(
    block(osm, 'void OSDMap::_raw_to_up_osds(') + block(osm, 'int OSDMap::_pick_primary('))
eexe = os.path.join(etmp, 'ec_ref')
subprocess.run([os.environ.get('CXX', 'g++'), '-O1', '-w', '-std=c++20', '-I' + etmp, '-I' + SRC, os.path.join(ROOT, 'tools', 'simref', 'ec_ref.cc'), '-o', eexe], check=True)


def erun(cmds):
    out = subprocess.run([eexe], input='\n'.join(cmds) + '\n', capture_output=True, text=True, check=True).stdout.split('\n')
    res, cur = [], []
    for ln in out:
        if ln == '.':
            res.append(cur); cur = []
        elif ln:
            cur.append(ln)
    return res


re_ = random.Random(1407)                   # its own stream: the data above stays as it was
# jerasure reed_sol_van chunk sizes: the pool's stripe_width is k * get_chunk_size(stripe_unit * k)
chunk_cases = []
for t in range(60):
    k = re_.choice([2, 3, 4, 5, 6, 8, 10, 12])
    su = re_.choice([4096, 8192, 16384, 65536, 1000, 4000, 512, 12345]) if t % 3 else 4096
    chunk_cases.append([k, re_.choice([8, 8, 16, 32]), re_.choice([0, 0, 1]), su * k])
r = erun([f'C {k} {w} {p} {sw}' for k, w, p, sw in chunk_cases])
chunk_cases = [c + [int(x[0])] for c, x in zip(chunk_cases, r)]
# stripe_info_t: ranges to shard extents, shard sizes, offsets
lay_cases, cmds = [], []
for t in range(120):
    k, m = re_.choice([(2, 1), (2, 2), (3, 2), (4, 2), (4, 3), (6, 3), (8, 3), (8, 4), (10, 4)])
    chunk = re_.choice([4096, 4096, 8192, 16384, 65536])
    sw = k * chunk
    off = re_.choice([0, re_.randint(0, 8 * sw), re_.randint(0, 64) * chunk, re_.randint(0, 2 ** 32)])
    ln = re_.choice([1, re_.randint(1, sw), re_.randint(1, 5 * sw), re_.randint(1, 3) * sw, 4 << 20])
    size = re_.choice([0, 1, re_.randint(1, sw), re_.randint(1, 40 * sw), 4 << 20, re_.randint(1, 2 ** 34)])
    so = re_.randint(0, 50 * chunk)
    sh = re_.randint(0, k - 1)
    lay_cases.append({'k': k, 'm': m, 'chunk': chunk, 'off': off, 'len': ln, 'size': size, 'shard': sh, 'shard_off': so})
    cmds += [f'S {k} {m} {chunk} {off} {ln}', f'Z {k} {m} {chunk} {size}', f'O {k} {m} {chunk} {off}', f'R {k} {m} {chunk} {sh} {so}']
r = erun(cmds)
for i, c in enumerate(lay_cases):
    S, Z, O, R = r[4 * i:4 * i + 4]
    c['extents'] = [[int(a), int(b), int(cc)] for a, b, cc in (x.split() for x in S if not x.startswith('s '))]
    c['superset'] = [[int(a), int(b)] for _, a, b in (x.split() for x in S if x.startswith('s '))]
    c['shard_sizes'] = [int(x) for x in Z[0].split()]
    c['shard_offsets'] = [int(x) for x in O[0].split()]
    c['ro_offset'] = int(R[0])
# CRUSH indep (and firstn for comparison) for k+m shards, with out OSDs and too few hosts (NONE holes),
# then OSDMap::_raw_to_up_osds with down OSDs for an EC pool (no shift) and a replicated one (shift)
ec_cases = []
especs = [('4 hosts x 3 (the lab)', [3, 3, 3, 3], lambda: W1), ('6 hosts', [2, 2, 3, 2, 2, 3], lambda: re_.choice([W1, 2 * W1, 0x18000])),
          ('3 hosts', [4, 4, 4], lambda: W1), ('8 hosts small', [1, 1, 2, 1, 1, 2, 1, 1], lambda: re_.choice([W1, 0x8000]))]
for name, hosts, rw in especs:
    m = mk_map(hosts, rw)
    nd = m['ndev']
    for variant in ('all in', 'outs', 'reweight'):
        wv = [0x10000] * nd
        if variant == 'outs':
            for q in re_.sample(range(nd), max(1, nd // 4)):
                wv[q] = 0
        elif variant == 'reweight':
            for q in re_.sample(range(nd), max(1, nd // 3)):
                wv[q] = re_.choice([0x8000, 0x4000, 0xc000])
        for rno, size in ((1, 3), (1, 6), (1, 7), (1, 11), (3, 6), (3, 9), (0, 6), (2, 6)):
            ec_cases.append({'name': f'{name} / {variant} / rule {rno} size {size}', 'map': m, 'weights': wv, 'rule': rno, 'size': size,
                             'pgp_num': 16, 'pool': re_.randint(1, 9),
                             'down': sorted(re_.sample(range(nd), re_.choice([0, 1, 2])))})
lines = []
for c in ec_cases:
    m = c['map']
    lines += ['MAP', 'TUN 0 0 50 1 1 1']
    for b in m['buckets']:
        lines.append(f'B {b["id"]} {b["type"]} {len(b["items"])} ' + ' '.join(f'{i} {w}' for i, w in b['items']))
    for no, rr in rules().items():
        lines.append(f'R {no} {rr["type"]} {len(rr["steps"])} ' + ' '.join(f'{a} {b} {cc}' for a, b, cc in rr['steps']))
    lines += ['FIN', f'W {m["ndev"]} ' + ' '.join(str(x) for x in c['weights']),
              f'Q {c["rule"]} 0 {c["pgp_num"]} {c["size"]} {c["pgp_num"]} {c["pool"]}', 'END']
out = run(lines)
k, ucmds = 0, []
for c in ec_cases:
    c['raw'] = []
    for _ in range(c['pgp_num']):
        raw = [int(x) for x in out[k].split()][1:]; k += 1
        c['raw'].append(raw)
        for shift in (0, 1):
            ucmds.append(f'U {shift} {len(raw)} ' + ' '.join(map(str, raw)) + ' d ' + ' '.join(map(str, c['down'])))
r = erun(ucmds)
q = 0
for c in ec_cases:
    c['up_ec'], c['up_rep'] = [], []
    for _ in range(c['pgp_num']):
        for key in ('up_ec', 'up_rep'):
            a, b = r[q][0].split('|'); q += 1
            c[key].append([[int(x) for x in a.split()], int(b)])
gold['ec'] = {'chunk_size': chunk_cases, 'stripe_info': lay_cases, 'crush_up': ec_cases,
              'nones': sum(raw.count(0x7fffffff) for c in ec_cases for raw in c['raw'])}

open(os.path.join(ROOT, 'tests', 'sims', 'golden.json'), 'w', encoding='utf-8').write(
    json.dumps(gold, ensure_ascii=False, separators=(',', ':')) + '\n')
print(json.dumps({'crush_cases': len(cases), 'pgs': sum(c['pgp_num'] for c in cases), 'autoscaler_cases': len(ascases),
                  'bucket_choose': len(bcases), 'alg_cases': len(acases), 'alg_pgs': sum(c['pgp_num'] for c in acases),
                  'striper_cases': len(scases), 'striper_layout_cases': len(ncases),
                  'ec_chunk': len(chunk_cases), 'ec_layout': len(lay_cases), 'ec_crush': len(ec_cases), 'ec_nones': gold['ec']['nones']}))
