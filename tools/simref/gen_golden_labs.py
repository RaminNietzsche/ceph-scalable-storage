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
open(os.path.join(TMP, 'acconfig.h'), 'w').close()   # the build-time config header the includes expect
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


# ---------------------------------------------------------------- reshard
def reshard():
    primes = cut('rgw/driver/rados/rgw_reshard.cc', r'^const std::initializer_list<uint16_t> RGWBucketReshard::reshard_primes = \{', r'^\};')
    pref = cut('rgw/driver/rados/rgw_reshard.cc', r'^void RGWBucketReshard::calculate_preferred_shards\(', r'^\} // RGWBucketReshard::check_bucket_shards')
    near = cut('rgw/driver/rados/rgw_reshard.cc', r'^uint32_t RGWBucketReshard::nearest_prime\(', r'^\}')
    ge = cut('rgw/driver/rados/rgw_reshard.h', r'static uint32_t get_prime_shards_greater_or_equal\(', r'^  \}')
    per = cut('rgw/driver/rados/rgw_rados.cc', r'^uint32_t RGWRados::calc_ordered_bucket_list_per_shard\(', r'^\}')
    consts = cut('rgw/driver/rados/rgw_reshard.cc', r'^constexpr uint64_t default_min_objs_per_shard', r'^constexpr uint32_t min_dynamic_shards')
    code = r"""
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <algorithm>
#include <initializer_list>
#include <iostream>
using namespace std;
struct DoutPrefixProvider {};
struct DoutS { template<class T> DoutS& operator<<(const T&) { return *this; } };
#define ldpp_dout(a, b) DoutS()
#define dendl ""
""" + consts + r"""
struct RGWBucketReshard {
  static const std::initializer_list<uint16_t> reshard_primes;
""" + ge + r"""
  static uint32_t nearest_prime(uint32_t suggested_shards);
  static void calculate_preferred_shards(const DoutPrefixProvider* dpp, const uint32_t max_dynamic_shards, const uint32_t min_layout_shards,
    const uint64_t max_objs_per_shard, const bool is_multisite, const uint64_t num_objs, const uint32_t current_num_shards,
    bool& need_resharding, uint32_t* suggested_num_shards, bool prefer_prime = true);
};
""" + primes + '\n' + near + '\n' + pref + r"""
struct RGWRados { static uint32_t calc_ordered_bucket_list_per_shard(uint32_t num_entries, uint32_t num_shards); };
""" + per + r"""
int main() {
  char k;
  for (auto p : RGWBucketReshard::reshard_primes) printf("%u ", (unsigned)p);
  printf("\n");
  while (cin >> k) {
    if (k == 'P') {
      unsigned md, ml, ms, cur; unsigned long long mo, n; cin >> md >> ml >> mo >> ms >> n >> cur;
      bool need = false; uint32_t sug = 0;
      RGWBucketReshard::calculate_preferred_shards(nullptr, md, ml, mo, ms, n, cur, need, &sug);
      printf("%d %u\n", need ? 1 : 0, need ? sug : 0);
    } else { unsigned n, s; cin >> n >> s; printf("%u\n", RGWRados::calc_ordered_bucket_list_per_shard(n, s)); }
  }
}
"""
    rnd = random.Random(11)
    pc, lc, lines = [], [], []
    for _ in range(400):
        md = rnd.choice([499, 1999]); ml = rnd.choice([0, 0, 11, 23]); mo = rnd.choice([100000, 33333, 50000, 200000, 1000])
        ms = rnd.choice([0, 1]); cur = rnd.choice([1, 11, 23, 29, 61, 101, 127, 499, 1999]); n = rnd.choice([rnd.randint(0, 3000), rnd.randint(0, 10 ** 6), rnd.randint(0, 10 ** 9), cur * mo + rnd.randint(-2, 2)])
        n = max(0, n); pc.append([md, ml, mo, ms, n, cur]); lines.append(f'P {md} {ml} {mo} {ms} {n} {cur}')
    for _ in range(200):
        n = rnd.choice([1, 10, 100, 1000, rnd.randint(1, 5000)]); s = rnd.randint(1, 2000)
        lc.append([n, s]); lines.append(f'L {n} {s}')
    out = run_cxx('reshard', code, '\n'.join(lines) + '\n').split('\n')
    OUT['reshard_primes'] = [int(x) for x in out[0].split()]
    for i, c in enumerate(pc):
        a, b = out[1 + i].split(); c.append([int(a), int(b)])
    for j, c in enumerate(lc):
        c.append(int(out[1 + len(pc) + j]))
    OUT['reshard_pref'] = pc
    OUT['reshard_list'] = lc



# ---------------------------------------------------------------- mdspin
def mdspin():
    rj = cut('include/hash.h', r'^inline uint64_t rjhash64\(uint64_t key\) \{', r'^\}')
    hb = cut('mds/MDCache.cc', r'^mds_rank_t MDCache::hash_into_rank_bucket\(inodeno_t ino, frag_t fg\)', r'^\}', inclusive=False)
    hb = hb.replace('  const mds_rank_t max_mds = mds->mdsmap->get_max_mds();', '')
    bits = cut('mds/MDCache.cc', r'^    double want = g_conf\(\).get_val<double>\("mds_export_ephemeral_distributed_factor"\);', r'^    export_ephemeral_dist_frag_bits = n;')
    bits = bits.replace('g_conf().get_val<double>("mds_export_ephemeral_distributed_factor")', 'factor')
    code = r"""
#include <cstdio>
#include <cstdint>
#include <cassert>
#include <string>
#include <iostream>
#include "include/ceph_hash.h"
typedef uint32_t __u32;
#include "include/ceph_frag.h"
#define ceph_assert assert
typedef int32_t mds_rank_t;
typedef uint64_t inodeno_t;
const mds_rank_t MDS_RANK_NONE = -1;
struct frag_t { uint32_t _enc; unsigned value() const { return ceph_frag_value(_enc); } operator uint32_t() const { return _enc; } };
""" + rj + r"""
static mds_rank_t hash_into_rank_bucket(inodeno_t ino, frag_t fg, mds_rank_t max_mds)
""" + hb + '\n}' + r"""
static unsigned frag_bits(int max_mds, double factor) {
  unsigned export_ephemeral_dist_frag_bits = 0;
  if (max_mds > 1) {
""" + bits + r"""
  }
  return export_ephemeral_dist_frag_bits;
}
int main() {
  char k;
  while (std::cin >> k) {
    if (k == 'J') { unsigned long long x; std::cin >> x; printf("%llu\n", (unsigned long long)rjhash64(x)); }
    else if (k == 'B') { int m; double f; std::cin >> m >> f; printf("%u\n", frag_bits(m, f)); }
    else {
      unsigned long long ino; std::string name; unsigned bits; int m; std::cin >> ino >> name >> bits >> m;
      unsigned h = ceph_str_hash_rjenkins(name.c_str(), name.size());
      // an evenly split fragtree of 2^bits leaves: the leaf containing h (frag_t::contains / ceph_frag_contains_value)
      frag_t fg{0};
      for (unsigned v = 0; v < (1u << bits) && bits; v++) { uint32_t f = ceph_frag_make(bits, v << (24 - bits)); if (ceph_frag_contains_value(f, h)) { fg._enc = f; break; } }
      printf("%u %d\n", fg._enc, hash_into_rank_bucket(ino, fg, m));
    }
  }
}
"""
    rnd = random.Random(5)
    lines, rjc, rc, bc = [], [], [], []
    for _ in range(100):
        x = rnd.choice([rnd.getrandbits(64), 0x10000000000 + rnd.randint(0, 10 ** 6), rnd.randint(0, 100)])
        rjc.append([str(x)]); lines.append(f'J {x}')
    for _ in range(60):
        m = rnd.randint(1, 16); f = rnd.choice([1.0, 2.0, 2.5, 4.0, 100.0]); bc.append([m, f]); lines.append(f'B {m} {f}')
    for _ in range(400):
        ino = rnd.choice([0x10000000000, 0x10000000000 + rnd.randint(1, 5000), 1, rnd.getrandbits(40)])
        name = rnd.choice(['user', 'job', 'proj', 'home', 'u']) + str(rnd.randint(0, 9999))
        m = rnd.randint(1, 16); bits = rnd.choice([0, 1, 2, 3, 4, 5, 6])
        rc.append([ino, name, bits, m]); lines.append(f'R {ino} {name} {bits} {m}')
    out = run_cxx('mdspin', code, '\n'.join(lines) + '\n', extra=[f'-I{TMP}', f'-I{SRC}', os.path.join(SRC, 'common', 'ceph_hash.cc')]).split('\n')
    i = 0
    for c in rjc: c.append(out[i]); i += 1
    for c in bc: c.append(int(out[i])); i += 1
    for c in rc: a, b = out[i].split(); c += [int(a), int(b)]; i += 1
    OUT['mdspin_rj'] = rjc; OUT['mdspin_bits'] = bc; OUT['mdspin_rank'] = rc



# ---------------------------------------------------------------- ecdecode
def ecdecode():
    J = os.environ.get('JERASURE_SRC'); GF = os.environ.get('GF_COMPLETE_SRC'); ISA = os.environ.get('ISAL_SRC')
    if not (J and GF and ISA):
        sys.exit('ecdecode needs JERASURE_SRC, GF_COMPLETE_SRC and ISAL_SRC (ceph/jerasure, ceph/gf-complete, ceph/isa-l)')
    code = r"""
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "jerasure.h"
#include "reed_sol.h"
void gf_gen_rs_matrix(unsigned char *a, int m, int k);
void ec_init_tables_base(int k, int rows, unsigned char *a, unsigned char *gftbls);
void ec_encode_data_base(int len, int srcs, int dests, unsigned char *v, unsigned char **src, unsigned char **dest);
int main(void) {
  char plug[16]; int k, m, cs;
  while (scanf("%15s %d %d %d", plug, &k, &m, &cs) == 4) {
    unsigned char *d[40], *c[40];
    for (int i = 0; i < k; i++) { d[i] = calloc(cs, 1); for (int b = 0; b < cs; b++) { unsigned x; scanf("%2x", &x); d[i][b] = x; } }
    for (int i = 0; i < m; i++) c[i] = calloc(cs, 1);
    if (plug[0] == 'j') {
      int *mat = reed_sol_vandermonde_coding_matrix(k, m, 8);
      jerasure_matrix_encode(k, m, 8, mat, (char **)d, (char **)c, cs);
      for (int i = 0; i < m * k; i++) printf("%d%c", mat[i], i + 1 < m * k ? ',' : ' ');
    } else {
      unsigned char a[64 * 32], g[32 * 64 * 32];
      gf_gen_rs_matrix(a, k + m, k);
      ec_init_tables_base(k, m, &a[k * k], g);
      ec_encode_data_base(cs, k, m, g, d, c);
      for (int i = 0; i < m * k; i++) printf("%d%c", a[k * k + i], i + 1 < m * k ? ',' : ' ');
    }
    for (int i = 0; i < m; i++) { for (int b = 0; b < cs; b++) printf("%02x", c[i][b]); printf(i + 1 < m ? "," : "\n"); }
  }
  return 0;
}
"""
    gfsrc = [os.path.join(GF, 'src', f) for f in ('gf.c', 'gf_w4.c', 'gf_w8.c', 'gf_w16.c', 'gf_w32.c', 'gf_w64.c', 'gf_w128.c', 'gf_wgen.c', 'gf_general.c', 'gf_rand.c', 'gf_method.c', 'gf_cpu.c')]
    jsrc = [os.path.join(J, 'src', f) for f in ('galois.c', 'jerasure.c', 'reed_sol.c')]
    isrc = [os.path.join(ISA, 'erasure_code', 'ec_base.c')]
    rnd = random.Random(3)
    cases, lines = [], []
    for _ in range(120):
        plug = rnd.choice(['jerasure', 'isa']); k = rnd.randint(2, 8); m = rnd.randint(1, 4); cs = rnd.randint(1, 24)
        data = [bytes(rnd.getrandbits(8) for _ in range(cs)).hex() for _ in range(k)]
        cases.append([plug, k, m, data]); lines.append(f'{plug} {k} {m} {cs} ' + ' '.join(data))
    out = run_cxx('ecdecode', code, '\n'.join(lines) + '\n', lang='c',
                  extra=[f'-I{J}/include', f'-I{GF}/include', f'-I{ISA}/include', f'-I{ISA}/erasure_code', *gfsrc, *jsrc, *isrc]).split('\n')
    for i, c in enumerate(cases):
        mat, par = out[i].split(' ')
        c.append([int(x) for x in mat.split(',')]); c.append(par.split(','))
    OUT['ec_encode'] = cases


def mclock():
    """mClock profiles (src/common/mclock_common.h) and the capacity options (src/common/options/osd.yaml.in)."""
    h = read('common/mclock_common.h')
    prof = {}
    for name in ('HIGH_CLIENT_OPS', 'HIGH_RECOVERY_OPS', 'BALANCED'):
        body = re.search(r'constexpr profile_t ' + name + r'\{(.*?)\};', h, re.S).group(1)
        prof[name.lower()] = [[float(x) for x in t.split(',')] for t in re.findall(r'\{([^{}]*)\}', body)]
    y = read('common/options/osd.yaml.in')
    def dflt(o):
        v = re.search(r'^- name: ' + o + r'\n(?:  .*\n)*?  default: (\S+)', y, re.M).group(1)
        mul = {'K': 1 << 10, 'M': 1 << 20, 'G': 1 << 30}
        return float(v[:-2]) * mul[v[-1]] if v[-2:-1] == '_' else (float(v) if re.match(r'^[0-9.]+$', v) else v)
    opts = {o: dflt(o) for o in ('osd_mclock_max_capacity_iops_hdd', 'osd_mclock_max_capacity_iops_ssd',
                                 'osd_mclock_max_sequential_bandwidth_hdd', 'osd_mclock_max_sequential_bandwidth_ssd',
                                 'osd_op_num_shards_hdd', 'osd_op_num_shards_ssd', 'osd_mclock_profile')}
    OUT['mclock'] = {'profiles': prof, 'options': opts}


STEPS = [capacity, reshard, mdspin, ecdecode, mclock]
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
