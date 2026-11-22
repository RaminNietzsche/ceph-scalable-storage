#!/usr/bin/env python3
"""Reference data for the labs that load on demand (templates/site/sims/lab-*.js): tests/sims/golden-labs.json.

Functions are cut out of an unmodified Ceph tree (CEPH_SRC=/path/to/ceph/src) by their first and last lines,
compiled unchanged with small stand-ins for the surrounding classes, and run on generated cases. The erasure-code
lab also needs jerasure and gf-complete (JERASURE_SRC, GF_COMPLETE_SRC: the ceph/jerasure and ceph/gf-complete
trees that Ceph uses as submodules). Usage:

  CEPH_SRC=... JERASURE_SRC=... GF_COMPLETE_SRC=... python3 tools/simref/gen_golden_labs.py
"""
import json, os, random, re, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC = os.environ.get('CEPH_SRC')
if not SRC or not os.path.isdir(SRC):
    sys.exit('set CEPH_SRC to the src directory of a Ceph checkout')
CXX = os.environ.get('CXX', 'g++')
CC = os.environ.get('CC', 'gcc')
TMP = tempfile.mkdtemp(prefix='simref-labs-')
OUT = {}


def read(rel):
    return open(os.path.join(SRC, rel), encoding='utf-8').read()


def cut(rel, start, end, inclusive=True):
    """the text of a Ceph source file from the first line matching `start` to the next line matching `end`"""
    lines = read(rel).split('\n')
    a = next(i for i, l in enumerate(lines) if re.search(start, l))
    b = next(i for i in range(a + 1, len(lines)) if re.search(end, lines[i]))
    return '\n'.join(lines[a:b + 1] if inclusive else lines[a + 1:b])


def run_cxx(name, code, stdin='', extra=(), lang='c++'):
    src = os.path.join(TMP, name + ('.cc' if lang == 'c++' else '.c'))
    exe = os.path.join(TMP, name)
    open(src, 'w').write(code)
    cmd = ([CXX, '-std=c++20'] if lang == 'c++' else [CC, '-std=gnu11']) + ['-O1', '-w', '-o', exe, src, *extra]
    subprocess.run(cmd, check=True)
    return subprocess.run([exe], input=stdin, capture_output=True, text=True, check=True).stdout


def rev():
    try:
        return subprocess.run(['git', '-C', SRC, 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip()
    except Exception:
        return 'unknown'


# ---------------------------------------------------------------- capacity
def capacity():
    body = cut('osd/OSD.cc', r'^  float nearfull_ratio = osdmap->get_nearfull_ratio\(\);', r'^   return NONE;')
    code = r'''
#include <cstdio>
#include <algorithm>
#include <string>
#include <map>
#include <cstdint>
#include <iostream>
using namespace std;
enum class ceph_release_t { luminous = 12, squid = 19 };
enum s_names { INVALID = -1, NONE, NEARFULL, BACKFILLFULL, FULL, FAILSAFE };
struct OM { float nf, bf, f; ceph_release_t require_osd_release = ceph_release_t::squid;
  float get_nearfull_ratio() const { return nf; } float get_backfillfull_ratio() const { return bf; } float get_full_ratio() const { return f; } };
static float g_failsafe;
static float get_failsafe_full_ratio() { return g_failsafe; }
struct DerrS { template<class T> DerrS& operator<<(const T&) { return *this; } } derr;
#define dendl ""
static s_names recalc(OM* osdmap, float ratio, float pratio, string& inject) {
  s_names injectfull_state = NONE; bool injectfull = false;
''' + body + r'''
}
// PGMap::get_rule_avail, the loop cut out of src/mon/PGMap.cc with stand-ins for osd_stat and the weight map
struct statfs_t { uint64_t total, available; uint64_t kb() const { return total >> 10; } uint64_t kb_avail() const { return available >> 10; } };
struct osd_stat_t { statfs_t statfs; };
struct OSDMapS { float fr; float get_full_ratio() const { return fr; } bool is_up(int) const { return true; } };
struct DoutS { template<class T> DoutS& operator<<(const T&) { return *this; } };
#define dout(x) DoutS()
static int64_t rule_avail(const OSDMapS& osdmap, const map<int,float>& wm, const map<int, osd_stat_t>& osd_stat) {
''' + cut('mon/PGMap.cc', r'^  float fratio = osdmap.get_full_ratio\(\);', r'^  return min;') + r'''
}
int main() {
  const char* N[] = {"none", "nearfull", "backfillfull", "full", "failsafe"};
  string kind;
  while (cin >> kind) {
    if (kind == "F") {
      float r, p, nf, bf, f, fs; cin >> r >> p >> nf >> bf >> f >> fs;
      OM om{nf, bf, f}; g_failsafe = fs; string inj;
      printf("%s\n", N[recalc(&om, r, p, inj)]);
    } else {
      int n; float fr; cin >> n >> fr;
      // CrushWrapper::get_rule_weight_osd_map: float sum of the crush weights, then w / sum (float)
      map<int,float> m, wm; map<int, osd_stat_t> st; float sum = 0;
      for (int i = 0; i < n; i++) { float w; uint64_t t, a; cin >> w >> t >> a; m[i] = w; sum += w; st[i] = osd_stat_t{statfs_t{t, a}}; }
      for (auto& p : m) wm[p.first] = (sum > 0) ? p.second / sum : 0.0f;
      printf("%lld\n", (long long)rule_avail(OSDMapS{fr}, wm, st));
    }
  }
}
'''
    rnd = random.Random(7)
    fcases, lines = [], []
    for _ in range(300):
        nf = rnd.choice([0.75, 0.8, 0.85, 0.9]); bf = rnd.choice([0.8, 0.85, 0.9, 0.92]); f = rnd.choice([0.85, 0.9, 0.95, 0.97]); fs = rnd.choice([0.95, 0.97])
        r = round(rnd.uniform(0.5, 1.0), 4); p = r if rnd.random() < 0.7 else round(rnd.uniform(0.5, 1.0), 4)
        fcases.append([r, p, nf, bf, f, fs]); lines.append(f'F {r} {p} {nf} {bf} {f} {fs}')
    acases = []
    for c in range(60):
        n = rnd.randint(2, 16); fr = rnd.choice([0.9, 0.95, 0.97])
        osds = []
        for i in range(n):
            w = rnd.choice([1.0, 2.0, 3.638, 7.277, 14.553, 0.0])
            t = 0 if rnd.random() < 0.08 else int(w * 2 ** 40) if w else int(4 * 2 ** 40)
            a = int(t * rnd.uniform(0.0, 1.0))
            osds.append([w, t, a])
        acases.append({'name': f'c{c}', 'full': fr, 'osds': osds})
        lines.append(f'A {n} {fr} ' + ' '.join(f'{w} {t} {a}' for w, t, a in osds))
    out = run_cxx('capacity', code, '\n'.join(lines) + '\n').split('\n')
    for i, c in enumerate(fcases):
        c.append(out[i])
    for j, c in enumerate(acases):
        c['want'] = int(out[len(fcases) + j])
    OUT['capacity_full'] = fcases
    OUT['capacity_avail'] = acases


STEPS = [capacity]
if __name__ == '__main__':
    only = sys.argv[1:]
    for f in STEPS:
        if not only or f.__name__ in only:
            f()
    path = os.path.join(ROOT, 'tests', 'sims', 'golden-labs.json')
    old = json.load(open(path)) if os.path.exists(path) else {}
    old.update(OUT)
    old['ceph_rev'] = rev()
    old['note'] = 'Generated by tools/simref/gen_golden_labs.py from an unmodified Ceph tree; do not edit.'
    json.dump(old, open(path, 'w'), separators=(',', ':'), sort_keys=True)
    print('wrote', path, ', '.join(sorted(OUT)))
