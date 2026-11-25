#!/usr/bin/env python3
"""Reference data for the labs that load on demand (templates/site/sims/lab-*.js): tests/sims/golden-labs.json.

Functions are cut out of an unmodified Ceph tree (CEPH_SRC=/path/to/ceph/src) by their first and last lines,
compiled unchanged with small stand-ins for the surrounding classes, and run on generated cases; option defaults and
profile constants are read from the same tree. The erasure-code lab also needs jerasure, gf-complete and ISA-L
(JERASURE_SRC, GF_COMPLETE_SRC, ISAL_SRC: the ceph/jerasure, ceph/gf-complete and ceph/isa-l trees that Ceph uses as
submodules); the SigV4 lab uses Python's hashlib and hmac as an independent reference. Usage:

  CEPH_SRC=... JERASURE_SRC=... GF_COMPLETE_SRC=... ISAL_SRC=... python3 tools/simref/gen_golden_labs.py [step ...]
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


def scrub():
    """isbetween_modulo (src/osd/scrubber/osd_scrub.cc), the hour and week-day window test of scrub_time_permit."""
    fn = cut('osd/scrubber/osd_scrub.cc', r'^static inline bool isbetween_modulo', r'^}')
    main = r'''
int main() {
  for (int f = 0; f < 24; f++) for (int t = 0; t < 24; t++) for (int p = 0; p < 24; p++) putchar('0' + isbetween_modulo(f, t, p));
  putchar('\n');
  for (int f = 0; f < 7; f++) for (int t = 0; t < 7; t++) for (int p = 0; p < 7; p++) putchar('0' + isbetween_modulo(f, t, p));
  putchar('\n');
}
'''
    out = run_cxx('scrub', '#include <cstdint>\n#include <cstdio>\n' + fn + main).split('\n')
    OUT['scrub_window'] = {'hours': out[0], 'days': out[1]}


def sigv4():
    """AWS Signature Version 4 for S3 from Python's hashlib/hmac (an independent reference for the browser SHA-256),
    plus the signing-key example from the AWS documentation. RGW checks the same values in src/rgw/rgw_auth_s3.cc."""
    import hashlib, hmac
    from urllib.parse import quote
    def hm(k, m): return hmac.new(k, m.encode(), hashlib.sha256).digest()
    rnd = random.Random(4); cases = []
    words = ['photos', 'a b', 'ü', 'x+y', 'report=1', 'deep/path', '~tilde', 'سلام']
    for _ in range(60):
        method = rnd.choice(['GET', 'PUT', 'HEAD', 'DELETE'])
        path = '/' + '/'.join(rnd.choice(words) for _ in range(rnd.randint(1, 3)))
        q = [(name, rnd.choice(['', '2', 'a b', 'ü', '1000']))   # distinct names: RGW's multimap keeps equal names in arrival order
             for name in rnd.sample(['prefix', 'list-type', 'max-keys', 'uploads', 'x-id', 'ünï'], rnd.randint(0, 3))]
        body = rnd.choice(['', 'hello', 'Ceph RGW', '{"a": 1}']) if method == 'PUT' else ''
        unsigned = rnd.random() < 0.3
        region = rnd.choice(['us-east-1', 'default', 'zg1'])
        host = rnd.choice(['s3.example.com', 'bucket.s3.example.com:8080'])
        amz = '2026%02d%02dT%02d%02d%02dZ' % (rnd.randint(1, 12), rnd.randint(1, 28), rnd.randint(0, 23), rnd.randint(0, 59), rnd.randint(0, 59))
        secret = ''.join(rnd.choice('ABCDEFabcdef0123456789/+') for _ in range(40))
        ph = 'UNSIGNED-PAYLOAD' if unsigned else hashlib.sha256(body.encode()).hexdigest()
        cq = '&'.join(k + '=' + v for k, v in sorted((quote(k, safe='-_.~'), quote(v, safe='-_.~')) for k, v in q))   # sorted after encoding
        hdr = 'host:' + host + '\nx-amz-content-sha256:' + ph + '\nx-amz-date:' + amz + '\n'
        sh = 'host;x-amz-content-sha256;x-amz-date'
        creq = '\n'.join([method, quote(path, safe='/-_.~'), cq, hdr, sh, ph])
        scope = amz[:8] + '/' + region + '/s3/aws4_request'
        sts = 'AWS4-HMAC-SHA256\n' + amz + '\n' + scope + '\n' + hashlib.sha256(creq.encode()).hexdigest()
        key = hm(hm(hm(hm(('AWS4' + secret).encode(), amz[:8]), region), 's3'), 'aws4_request')
        cases.append({'method': method, 'path': path, 'query': q, 'body': body, 'unsigned': unsigned, 'region': region, 'host': host,
                      'amz': amz, 'secret': secret, 'creq': creq, 'sts': sts, 'sig': hmac.new(key, sts.encode(), hashlib.sha256).hexdigest()})
    OUT['sigv4'] = {'cases': cases, 'aws_doc_key': ['wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY', '20150830', 'us-east-1', 'iam',
                    'c4afb1cc5771d871763a393e44b703571b55cc28424d1a5e86da6ed3c154a4b9']}


def bluespace():
    """BlueStore allocation and compression defaults (src/common/options/global.yaml.in) and the acceptance test
    cut from BlueStore::_do_alloc_write, compiled with stand-ins for its surroundings."""
    y = read('common/options/global.yaml.in')
    def dflt(o):
        v = re.search(r'^- name: ' + o + r'\n(?:  .*\n)*?  default: (\S+)', y, re.M).group(1)
        return int(v[:-2]) << {'K': 10, 'M': 20}[v[-1]] if v[-2:-1] == '_' else float(v)
    opts = {o: dflt(o) for o in ('bluestore_min_alloc_size_hdd', 'bluestore_min_alloc_size_ssd', 'bluestore_compression_required_ratio',
                                 'bluestore_compression_max_blob_size_hdd', 'bluestore_compression_max_blob_size_ssd')}
    src = read('os/bluestore/BlueStore.cc')
    a = src.index('      uint64_t want_len_raw = wi.blob_length * wctx->crr;')
    b = src.index('      if (r == 0 && result_len <= want_len && result_len < wi.blob_length) {', a)
    head = src[a:b]
    cond = 'result_len <= want_len && result_len < wi.blob_length'
    assert cond in src[b:b + 200]
    main = r'''
#include <cstdint>
#include <cstdio>
template <class T> T p2roundup(T x, T a) { return (x + a - 1) & ~(a - 1); }
struct WI { uint64_t blob_length; }; struct WC { double crr; }; struct BL { uint64_t n; uint64_t length() const { return n; } };
int main() {
  unsigned long long bl, cl, ma; double crr;
  while (scanf("%llu %llu %llu %lf", &bl, &cl, &ma, &crr) == 4) {
    WI wi{bl}; WC wc{crr}; WC* wctx = &wc; BL t{cl}; uint64_t min_alloc_size = ma; int r = 0;
''' + head + r'''
    printf("%d %llu %llu\n", (r == 0 && ''' + cond + r''') ? 1 : 0, (unsigned long long)want_len, (unsigned long long)result_len);
  }
}
'''
    rnd = random.Random(12); cases = []
    for _ in range(400):
        ma = rnd.choice([4096, 16384, 65536]); blob = rnd.choice([8192, 16384, 32768, 65536, 131072, 524288])
        cases.append([blob, rnd.randint(1, blob + 4096), ma, rnd.choice([0.875, 0.9, 0.5, 0.7, 1.0])])
    out = run_cxx('bluespace', main, ''.join('%d %d %d %r\n' % tuple(c) for c in cases)).split('\n')
    OUT['bluespace'] = {'options': opts, 'accept': [c + [int(x) for x in out[i].split()] for i, c in enumerate(cases)]}


# ---------------------------------------------------------------- balancer
def balancer():
    """OSDMap::calc_pg_upmaps and every helper it calls (src/osd/OSDMap.cc), CrushWrapper::try_remap_rule,
    _choose_type_stack and get_rule_weight_osd_map (src/crush/CrushWrapper.cc), cut out unchanged and compiled with
    stand-ins for pg_t, pg_pool_t, the CRUSH structs, the parent lookups and the raw CRUSH output (given per PG).
    Each case runs several balancer rounds on one pool, applying the increment between rounds."""
    osdmap = ['^bool OSDMap::try_pg_upmap\\(', '^int OSDMap::calc_pg_upmaps\\(', '^float OSDMap::get_osds_weight\\(',
              '^float OSDMap::build_pool_pgs_info \\(', '^float OSDMap::calc_deviations \\(', '^void OSDMap::fill_overfull_underfull \\(',
              '^int OSDMap::pack_upmap_results\\(', '^std::default_random_engine OSDMap::get_random_engine\\(',
              '^bool OSDMap::try_drop_remap_overfull\\(', '^bool OSDMap::try_drop_remap_underfull\\(', '^void OSDMap::add_remap_pair\\(',
              '^int OSDMap::find_best_remap \\(', '^OSDMap::candidates_by_osd_t OSDMap::build_candidates_by_osd\\(',
              '^void OSDMap::_apply_upmap\\(', '^void OSDMap::pg_to_raw_upmap\\(']
    crushw = ['^int CrushWrapper::_choose_type_stack\\(', '^int CrushWrapper::try_remap_rule\\(', '^float CrushWrapper::_get_take_weight_osd_map\\(',
              '^void CrushWrapper::_normalize_weight_map\\(', '^int CrushWrapper::get_rule_weight_osd_map\\(']
    body = '\n\n'.join(cut('osd/OSDMap.cc', s, '^}') for s in osdmap) + '\n\n' + '\n\n'.join(cut('crush/CrushWrapper.cc', s, '^}') for s in crushw)
    y = read('common/options/global.yaml.in')
    def dflt(o):
        return re.search(r'^- name: ' + o + r'\n(?:  .*\n)*?  default: (\S+)', y, re.M).group(1)
    opts = {o: dflt(o) for o in ('osd_calc_pg_upmaps_aggressively', 'osd_calc_pg_upmaps_aggressively_fast', 'osd_calc_pg_upmaps_local_fallback_retries')}
    mgr = read('pybind/mgr/balancer/module.py') if os.path.exists(os.path.join(SRC, 'pybind/mgr/balancer/module.py')) else \
        subprocess.run(['git', '-C', SRC, 'show', 'HEAD:src/pybind/mgr/balancer/module.py'], capture_output=True, text=True, check=True).stdout
    for o in ('upmap_max_optimizations', 'upmap_max_deviation', 'crush_compat_max_iterations', 'crush_compat_step', 'min_score', 'mode'):
        m = re.search(r"Option\(name='" + o + r"',(?:.|\n)*?default=([^,\n]+),", mgr)
        opts['mgr_' + o] = m.group(1).strip().strip("'")
    opts['target_max_misplaced_ratio'] = re.search(r'^- name: target_max_misplaced_ratio\n(?:  .*\n)*?  default: (\S+)', read('common/options/global.yaml.in'), re.M).group(1)
    pre = r'''
#include <cstdio>
#include <cstdint>
#include <cmath>
#include <cassert>
#include <cerrno>
#include <string>
#include <set>
#include <map>
#include <list>
#include <vector>
#include <memory>
#include <random>
#include <algorithm>
using namespace std;
#define ceph_assert assert
struct NullS { template <class T> NullS& operator<<(const T&) { return *this; } };
static NullS nulls;
#define ldout(cct, v) while (0) nulls
#define lderr(cct) while (0) nulls
#define dendl ""
namespace mempool { namespace osdmap { template <class T> using vector = std::vector<T>; } }
static const int CRUSH_ITEM_NONE = 0x7fffffff;
enum { CRUSH_RULE_TAKE = 1, CRUSH_RULE_CHOOSE_FIRSTN = 2, CRUSH_RULE_CHOOSE_INDEP = 3, CRUSH_RULE_EMIT = 4,
       CRUSH_RULE_CHOOSELEAF_FIRSTN = 6, CRUSH_RULE_CHOOSELEAF_INDEP = 7 };
struct Conf { bool aggr, fast; uint64_t retries;
  template <class T> T get_val(const string& n) const {
    if (n == "osd_calc_pg_upmaps_aggressively") return (T)aggr;
    if (n == "osd_calc_pg_upmaps_aggressively_fast") return (T)fast;
    return (T)retries; } };
struct CephContext { Conf _conf; };
struct pg_t { uint64_t m_pool; uint32_t m_seed;
  pg_t() : m_pool(0), m_seed(0) {} pg_t(uint32_t s, uint64_t p) : m_pool(p), m_seed(s) {}
  uint64_t pool() const { return m_pool; } uint32_t ps() const { return m_seed; }
  auto operator<=>(const pg_t&) const noexcept = default; };
struct pg_pool_t { unsigned pg_num, size; int rule;
  unsigned get_pg_num() const { return pg_num; } unsigned get_size() const { return size; } int get_crush_rule() const { return rule; }
  pg_t raw_pg_to_pg(pg_t pg) const { return pg; } };
struct crush_rule_step { uint32_t op; int32_t arg1, arg2; };
struct crush_rule { uint32_t len; crush_rule_step steps[4]; };
struct crush_bucket { int32_t id; uint16_t type; uint32_t size; int32_t *items; uint32_t *weights; };
struct crush_map { crush_bucket **buckets; crush_rule **rules; int32_t max_buckets; uint32_t max_rules; int32_t max_devices; };
static uint32_t crush_get_bucket_item_weight(const crush_bucket *b, int p) { return b->weights[p]; }
class CrushWrapper {
public:
  crush_map *crush; map<int, int> parent; map<int, int> type;
  const crush_rule *get_rule(unsigned r) const { return crush->rules[r]; }
  // stand-ins for the name/class aware lookups: walk the parent links of a plain tree
  int get_parent_of_type(int item, int t, int rule = -1) const {
    do { auto p = parent.find(item); if (p == parent.end()) return 0; item = p->second; } while (type.at(item) != t);
    return item; }
  bool subtree_contains(int root, int item) const {
    for (;;) { if (item == root) return true; auto p = parent.find(item); if (p == parent.end()) return false; item = p->second; } }
  int _choose_type_stack(CephContext *cct, const vector<pair<int,int>>& stack, const set<int>& overfull, const vector<int>& underfull,
    const vector<int>& more_underfull, const vector<int>& orig, vector<int>::const_iterator& i, set<int>& used, vector<int> *pw,
    int root_bucket, int rule) const;
  int try_remap_rule(CephContext *cct, int ruleno, int maxout, const set<int>& overfull, const vector<int>& underfull,
    const vector<int>& more_underfull, const vector<int>& orig, vector<int> *out) const;
  float _get_take_weight_osd_map(int root, map<int,float> *pmap) const;
  void _normalize_weight_map(float sum, const map<int,float>& m, map<int,float> *pmap) const;
  int get_rule_weight_osd_map(unsigned ruleno, map<int,float> *pmap) const;
};
class OSDMap {
public:
  struct Incremental { set<pg_t> old_pg_upmap_items; map<pg_t, mempool::osdmap::vector<pair<int32_t,int32_t>>> new_pg_upmap_items; };
  map<int64_t, pg_pool_t> pools; shared_ptr<CrushWrapper> crush; int max_osd = 0; vector<uint32_t> osd_weight;
  map<pg_t, mempool::osdmap::vector<int32_t>> pg_upmap; map<pg_t, mempool::osdmap::vector<pair<int32_t,int32_t>>> pg_upmap_items;
  map<pg_t, int32_t> pg_upmap_primaries; map<pg_t, vector<int>> raw_table;   // stand-in for the CRUSH output of each PG
  typedef std::vector<std::pair<pg_t, mempool::osdmap::vector<std::pair<int, int>>>> candidates_t;
  typedef std::map<int, candidates_t> candidates_by_osd_t;
  const pg_pool_t *get_pg_pool(int64_t p) const { auto i = pools.find(p); return i == pools.end() ? nullptr : &i->second; }
  int get_pg_pool_size(pg_t pg) const { return pools.at(pg.pool()).get_size(); }
  float get_weightf(int o) const { return (float)osd_weight[o] / (float)0x10000; }
  void deepish_copy_from(const OSDMap& o) { *this = o; }
  void _pg_to_raw_osds(const pg_pool_t&, pg_t pg, vector<int> *raw, void *) const { *raw = raw_table.at(pg); }
  // stand-in for _pg_to_raw_osds + _apply_upmap + _raw_to_up_osds (every OSD up, replicated pool)
  void pg_to_up_acting_osds(pg_t pg, vector<int> *up, int *, vector<int> *, int *) const {
    vector<int> raw, orig; pg_to_raw_upmap(pg, &raw, &orig); up->clear();
    for (int o : orig) if (o != CRUSH_ITEM_NONE) up->push_back(o); }
  bool try_pg_upmap(CephContext *cct, pg_t pg, const set<int>& overfull, const vector<int>& underfull, const vector<int>& more_underfull,
    vector<int> *orig, vector<int> *out);
  int calc_pg_upmaps(CephContext *cct, uint32_t max_deviation, int max, const set<int64_t>& only_pools, Incremental *pending_inc,
    std::random_device::result_type *p_seed = nullptr);
  float get_osds_weight(CephContext *cct, const OSDMap& tmp_osd_map, int64_t pid, map<int,float>& osds_weight) const;
  float build_pool_pgs_info(CephContext *cct, const set<int64_t>& pools, const OSDMap& tmp_osd_map, int& total_pgs,
    map<int, set<pg_t>>& pgs_by_osd, map<int,float>& osds_weight);
  float calc_deviations(CephContext *cct, const map<int,set<pg_t>>& pgs_by_osd, const map<int,float>& osd_weight, float pgs_per_weight,
    map<int,float>& osd_deviation, multimap<float,int>& deviation_osd, double& bal_score);
  void fill_overfull_underfull(CephContext *cct, const multimap<float,int>& deviation_osd, int max_deviation, set<int>& overfull,
    set<int>& more_overfull, vector<int>& underfull, vector<int>& more_underfull);
  int pack_upmap_results(CephContext *cct, const set<pg_t>& to_unmap, const map<pg_t, mempool::osdmap::vector<pair<int, int>>>& to_upmap,
    OSDMap& tmp_osd_map, Incremental *pending_inc);
  std::default_random_engine get_random_engine(CephContext *cct, std::random_device::result_type *p_seed);
  bool try_drop_remap_overfull(CephContext *cct, const vector<pg_t>& pgs, const OSDMap& tmp_osd_map, int osd,
    map<int,set<pg_t>>& temp_pgs_by_osd, set<pg_t>& to_unmap, map<pg_t, mempool::osdmap::vector<pair<int32_t,int32_t>>>& to_upmap,
    const map<int,float>& osd_deviation);
  bool try_drop_remap_underfull(CephContext *cct, const candidates_t& candidates, int osd, map<int,set<pg_t>>& temp_pgs_by_osd,
    set<pg_t>& to_unmap, map<pg_t, mempool::osdmap::vector<pair<int32_t,int32_t>>>& to_upmap);
  void add_remap_pair(CephContext *cct, int orig, int out, pg_t pg, size_t pg_pool_size, int osd, set<int>& existing,
    map<int,set<pg_t>>& temp_pgs_by_osd, mempool::osdmap::vector<pair<int32_t,int32_t>> new_upmap_items,
    map<pg_t, mempool::osdmap::vector<pair<int32_t,int32_t>>>& to_upmap);
  int find_best_remap(CephContext *cct, const vector<int>& orig, const vector<int>& out, const set<int>& existing,
    const map<int,float> osd_deviation);
  candidates_by_osd_t build_candidates_by_osd(CephContext *cct, const OSDMap& tmp_osd_map, const set<pg_t> to_skip,
    const set<int64_t>& only_pools, bool aggressive, std::random_device::result_type *p_seed);
  void _apply_upmap(const pg_pool_t& pi, pg_t raw_pg, vector<int> *raw) const;
  void pg_to_raw_upmap(pg_t pg, vector<int> *raw, vector<int> *raw_upmap) const;
};
'''
    main = r'''
int main() {
  int nosd, nhost, size, pgnum, leaf, aggr, fast, retries, rounds, maxdev, maxopt, nex; unsigned seed;
  if (scanf("%d %d %d %d %d %d %d %d %u %d %d %d", &nosd, &nhost, &size, &pgnum, &leaf, &aggr, &fast, &retries, &seed, &maxdev, &maxopt, &rounds) != 12) return 1;
  vector<int> host(nosd); vector<uint32_t> cw(nosd), rw(nosd);
  for (auto& x : host) scanf("%d", &x); for (auto& x : cw) scanf("%u", &x); for (auto& x : rw) scanf("%u", &x);
  CephContext cct{{(bool)aggr, (bool)fast, (uint64_t)retries}};
  auto cr = make_shared<CrushWrapper>();
  crush_map *cm = new crush_map; cm->max_buckets = nhost + 1; cm->max_devices = nosd; cm->max_rules = 1;
  cm->buckets = new crush_bucket*[nhost + 1]; cm->rules = new crush_rule*[1];
  // root -1 (type 11) holds hosts -2 .. -(nhost+1) (type 1), each holds its OSDs; the bucket weight of a host is the sum
  vector<vector<int32_t>> hi(nhost); vector<vector<uint32_t>> hw(nhost);
  for (int o = 0; o < nosd; o++) { hi[host[o]].push_back(o); hw[host[o]].push_back(cw[o]); cr->parent[o] = -2 - host[o]; }
  cr->type[-1] = 11;
  crush_bucket *root = new crush_bucket{-1, 11, (uint32_t)nhost, new int32_t[nhost], new uint32_t[nhost]};
  for (int h = 0; h < nhost; h++) {
    uint32_t s = 0; for (auto w : hw[h]) s += w;
    root->items[h] = -2 - h; root->weights[h] = s; cr->parent[-2 - h] = -1; cr->type[-2 - h] = 1;
    cm->buckets[1 + h] = new crush_bucket{-2 - h, 1, (uint32_t)hi[h].size(), hi[h].data(), hw[h].data()};
  }
  cm->buckets[0] = root;
  crush_rule *r = new crush_rule; r->len = 3;
  r->steps[0] = {CRUSH_RULE_TAKE, -1, 0};
  r->steps[1] = leaf ? crush_rule_step{CRUSH_RULE_CHOOSELEAF_FIRSTN, 0, 1} : crush_rule_step{CRUSH_RULE_CHOOSE_FIRSTN, 0, 0};
  r->steps[2] = {CRUSH_RULE_EMIT, 0, 0};
  cm->rules[0] = r; cr->crush = cm;
  OSDMap m; m.crush = cr; m.max_osd = nosd; m.osd_weight = rw; m.pools[1] = pg_pool_t{(unsigned)pgnum, (unsigned)size, 0};
  for (int ps = 0; ps < pgnum; ps++) { vector<int> v(size); for (auto& x : v) scanf("%d", &x); m.raw_table[pg_t(ps, 1)] = v; }
  scanf("%d", &nex);
  for (int e = 0; e < nex; e++) { int ps, k; scanf("%d %d", &ps, &k); auto& it = m.pg_upmap_items[pg_t(ps, 1)];
    for (int j = 0; j < k; j++) { int a, b; scanf("%d %d", &a, &b); it.push_back({a, b}); } }
  for (int rd = 0; rd < rounds; rd++) {
    OSDMap::Incremental inc;
    int n = m.calc_pg_upmaps(&cct, maxdev, maxopt, {1}, &inc, &seed);
    printf("R %d", n);
    for (auto& pg : inc.old_pg_upmap_items) { printf(" U %u", pg.ps()); m.pg_upmap_items.erase(pg); }
    for (auto& [pg, it] : inc.new_pg_upmap_items) { printf(" N %u %zu", pg.ps(), it.size()); for (auto& [a, b] : it) printf(" %d %d", a, b); m.pg_upmap_items[pg] = it; }
    printf(" C");
    vector<int> cnt(nosd);
    for (int ps = 0; ps < pgnum; ps++) { vector<int> up; m.pg_to_up_acting_osds(pg_t(ps, 1), &up, nullptr, nullptr, nullptr); for (int o : up) cnt[o]++; }
    for (int c : cnt) printf(" %d", c);
    printf("\n");
  }
}
'''
    code = pre + body + main
    rnd = random.Random(31); cases = []
    for ci in range(60):
        nhost = rnd.randint(3, 8); per = rnd.randint(1, 5); leaf = 0 if ci % 6 == 5 else 1
        size = rnd.choice([2, 3, 3]) if leaf else rnd.choice([2, 3])
        if leaf and size > nhost: size = nhost
        host = [h for h in range(nhost) for _ in range(per if ci % 4 else rnd.randint(1, 5))]
        nosd = len(host)
        if not leaf and size > nosd: size = nosd
        kind = ci % 5
        cw = [0x10000 * (1 if kind == 0 else rnd.choice([1, 2, 4])) if kind != 3 else rnd.randint(0x8000, 0x40000) for _ in host]
        rw = [0x10000 if rnd.random() > 0.15 else rnd.randint(0x6000, 0xffff) for _ in host]
        pgnum = rnd.choice([16, 32, 64, 128, 256])
        hosts = sorted(set(host))
        raw = []
        for ps in range(pgnum):   # a valid placement: distinct failure domains, biased by weight and a little noise
            pick = []
            while len(pick) < size:
                cands = [o for o in range(nosd) if o not in pick and (not leaf or host[o] not in [host[p] for p in pick])]
                ws = [cw[o] * rw[o] * (1 + 0.6 * rnd.random()) for o in cands]
                pick.append(rnd.choices(cands, ws)[0])
            raw.append(pick)
        ex = []
        if ci % 3 == 2:   # some existing upmap items, some of them pointing into full OSDs, to reach the drop paths
            for ps in rnd.sample(range(pgnum), min(pgnum, rnd.randint(1, 8))):
                frm = raw[ps][rnd.randrange(size)]
                tos = [o for o in range(nosd) if o not in raw[ps] and (not leaf or host[o] not in [host[p] for p in raw[ps] if p != frm])]
                if tos: ex.append([ps, [[frm, rnd.choice(tos)]]])
        c = {'host': host, 'cw': cw, 'rw': rw, 'size': size, 'pgnum': pgnum, 'leaf': leaf, 'aggr': int(ci % 2 == 0), 'fast': int(ci % 4 != 2),
             'retries': rnd.choice([100, 100, 3]), 'seed': rnd.randint(0, 1 << 20), 'maxdev': rnd.choice([1, 1, 2, 5]), 'maxopt': rnd.choice([10, 10, 3, 50]),
             'rounds': 4, 'raw': raw, 'ex': ex}
        cases.append(c)
    exe = None
    src = os.path.join(TMP, 'balancer.cc'); exe = os.path.join(TMP, 'balancer')
    open(src, 'w').write(code)
    subprocess.run([CXX, '-std=c++20', '-O1', '-w', '-o', exe, src], check=True)
    for c in cases:
        inp = '%d %d %d %d %d %d %d %d %d %d %d %d\n' % (len(c['host']), max(c['host']) + 1, c['size'], c['pgnum'], c['leaf'], c['aggr'], c['fast'],
                                                        c['retries'], c['seed'], c['maxdev'], c['maxopt'], c['rounds'])
        inp += ' '.join(map(str, c['host'])) + '\n' + ' '.join(map(str, c['cw'])) + '\n' + ' '.join(map(str, c['rw'])) + '\n'
        inp += '\n'.join(' '.join(map(str, r)) for r in c['raw']) + '\n%d\n' % len(c['ex'])
        inp += ''.join('%d %d %s\n' % (e[0], len(e[1]), ' '.join('%d %d' % tuple(p) for p in e[1])) for e in c['ex'])
        out = subprocess.run([exe], input=inp, capture_output=True, text=True, check=True).stdout   # one process per case: the seed counter starts at 0
        res = []
        for line in out.strip().split('\n'):
            t = line.split(); n = int(t[1]); i = 2; un = []; nw = []
            while t[i] != 'C':
                if t[i] == 'U': un.append(int(t[i + 1])); i += 2
                else:
                    ps, k = int(t[i + 1]), int(t[i + 2]); nw.append([ps, [[int(t[i + 3 + 2 * j]), int(t[i + 4 + 2 * j])] for j in range(k)]]); i += 3 + 2 * k
            res.append({'n': n, 'unmap': un, 'upmap': nw, 'count': [int(x) for x in t[i + 1:]]})
        c['out'] = res
    OUT['balancer'] = {'options': opts, 'cases': cases}


STEPS = [capacity, reshard, mdspin, ecdecode, mclock, scrub, sigv4, bluespace, balancer]
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
