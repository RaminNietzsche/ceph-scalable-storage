/* Reference harness for the erasure-coding data in tests/sims/golden.json.
 *
 * gen_golden.py copies, without changes, out of an unmodified Ceph tree into ec_extract.inc:
 *   src/osd/ECUtil.h    stripe_info_t::object_size_to_shard_size, ro_offset_to_shard_offset,
 *                       shard_offset_to_ro_offset, align_next
 *   src/osd/ECUtil.cc   stripe_info_t::ro_range_to_shards
 *   src/erasure-code/jerasure/ErasureCodeJerasure.cc
 *                       ErasureCodeJerasure::get_chunk_size,
 *                       ErasureCodeJerasureReedSolomonVandermonde::get_alignment
 *   src/osd/OSDMap.cc   OSDMap::_raw_to_up_osds, OSDMap::_pick_primary
 * and compiles this file with g++ against the real src/include/intarith.h. Stood in for:
 * logging, ceph_assert, buffer::list (the bufferlist branch is never taken: bl is nullptr),
 * extent_set (an interval set), the shard id types (plain integers) and the chunk mapping
 * (the identity, as jerasure's empty get_chunk_mapping() completes to).
 *
 * Commands on stdin, one per line:
 *   C k w per_chunk_alignment stripe_width   -> jerasure reed_sol_van get_chunk_size
 *   S k m chunk_size off len                 -> ro_range_to_shards: "shard off len" per extent, then "s off len" superset
 *   Z k m chunk_size size                    -> object_size_to_shard_size of every shard
 *   O k m chunk_size ro_offset               -> ro_offset_to_shard_offset of every data shard
 *   R k m chunk_size shard offset            -> shard_offset_to_ro_offset
 *   U can_shift n raw... d down...           -> _raw_to_up_osds then _pick_primary: "up... | primary"
 * Every answer ends with a line "." CC BY-NC-SA 4.0, Ramin Najarbashi. */
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <map>
#include <set>
#include <sstream>
#include <string>
#include <vector>
#include "include/intarith.h"

#define ceph_assert(x) assert(x)
#define dout(v) if (0) std::cerr
#define dendl std::endl
#define CRUSH_ITEM_NONE 0x7fffffff
using std::min;
using std::vector;

struct raw_shard_id_t { int id; raw_shard_id_t(long long i = 0) : id((int)i) {} operator int() const { return id; } };
struct shard_id_t { int id; shard_id_t(long long i = 0) : id((int)i) {} operator int() const { return id; } };

namespace buffer {
struct list {
  uint64_t length() const { return 0; }
  void substr_of(const list &, uint64_t, uint64_t) {}
  void append(const list &) {}
};
}

namespace ECUtil {
static inline constexpr uint64_t EC_ALIGN_SIZE = 4096;    // src/osd/ECUtil.h
struct extent_set {
  std::map<uint64_t, uint64_t> m;                          // off -> len, merged
  void union_insert(uint64_t off, uint64_t len) {
    uint64_t a = off, b = off + len;
    auto it = m.upper_bound(a);
    if (it != m.begin()) { auto p = std::prev(it); if (p->first + p->second >= a) { a = p->first; b = std::max(b, p->first + p->second); it = m.erase(p); } }
    while (it != m.end() && it->first <= b) { b = std::max(b, it->first + it->second); it = m.erase(it); }
    m[a] = b - a;
  }
};
struct shard_id_less { bool operator()(const shard_id_t &a, const shard_id_t &b) const { return int(a) < int(b); } };
typedef std::map<shard_id_t, extent_set, shard_id_less> shard_extent_set_t;
struct shard_extent_map_t { void insert_in_shard(shard_id_t, uint64_t, buffer::list &, uint64_t, uint64_t) {} };

#include "ec_extract_inline.inc"

class stripe_info_t {
  const uint64_t stripe_width;
  const uint64_t chunk_size;
  const unsigned int k;
  const unsigned int m;
 public:
  stripe_info_t(unsigned int k, unsigned int m, uint64_t stripe_width)
    : stripe_width(stripe_width), chunk_size(stripe_width / k), k(k), m(m) {}
  uint64_t get_stripe_width() const { return stripe_width; }
  uint64_t get_chunk_size() const { return chunk_size; }
  unsigned int get_k() const { return k; }
  shard_id_t get_shard(const raw_shard_id_t raw_shard) const { return shard_id_t(int(raw_shard)); }
  raw_shard_id_t get_raw_shard(shard_id_t shard) const { return raw_shard_id_t(int(shard)); }
#include "ec_extract_methods.inc"
  void ro_range_to_shards(uint64_t ro_offset, uint64_t ro_size, ECUtil::shard_extent_set_t *shard_extent_set,
                          extent_set *extent_superset, buffer::list *bl, shard_extent_map_t *shard_extent_map) const;
};
}  // namespace ECUtil
#include "ec_extract_cc.inc"

#define LARGEST_VECTOR_WORDSIZE 16                        // src/erasure-code/jerasure/ErasureCodeJerasure.h
struct ErasureCodeJerasure {
  int k = 2, w = 8; bool per_chunk_alignment = false;
  virtual unsigned get_alignment() const = 0;
  unsigned int get_chunk_size(unsigned int stripe_width) const;
  virtual ~ErasureCodeJerasure() {}
};
struct ErasureCodeJerasureReedSolomonVandermonde : ErasureCodeJerasure { unsigned get_alignment() const override; };
#include "ec_extract_jerasure.inc"

struct pg_pool_t { bool shift; bool can_shift_osds() const { return shift; } };
struct OSDMap {
  std::set<int> down; int max_osd = 0;
  bool exists(int osd) const { return osd >= 0 && osd < max_osd; }
  bool is_down(int osd) const { return down.count(osd) > 0; }
  void _raw_to_up_osds(const pg_pool_t &pool, const vector<int> &raw, vector<int> *up) const;
  int _pick_primary(const vector<int> &osds) const;
};
#include "ec_extract_osdmap.inc"

int main() {
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    char c; in >> c;
    if (c == 'C') {
      ErasureCodeJerasureReedSolomonVandermonde e; int pca; unsigned sw;
      in >> e.k >> e.w >> pca >> sw; e.per_chunk_alignment = pca;
      std::cout << e.get_chunk_size(sw) << "\n";
    } else if (c == 'U') {
      int shift, n; in >> shift >> n; vector<int> raw(n);
      for (auto &x : raw) in >> x;
      OSDMap om; om.max_osd = 1 << 20; std::string d; in >> d; int x;
      while (in >> x) om.down.insert(x);
      pg_pool_t p{shift != 0}; vector<int> up;
      om._raw_to_up_osds(p, raw, &up);
      for (int o : up) std::cout << o << " ";
      std::cout << "| " << om._pick_primary(up) << "\n";
    } else {
      unsigned k, m; uint64_t chunk; in >> k >> m >> chunk;
      ECUtil::stripe_info_t si(k, m, chunk * k);
      if (c == 'S') {
        uint64_t off, len; in >> off >> len;
        ECUtil::shard_extent_set_t ses; ECUtil::extent_set sup;
        si.ro_range_to_shards(off, len, &ses, &sup, nullptr, nullptr);
        for (auto &p : ses) for (auto &e : p.second.m) std::cout << int(p.first) << " " << e.first << " " << e.second << "\n";
        for (auto &e : sup.m) std::cout << "s " << e.first << " " << e.second << "\n";
      } else if (c == 'Z') {
        uint64_t size; in >> size;
        for (unsigned s = 0; s < k + m; s++) std::cout << si.object_size_to_shard_size(size, shard_id_t(s)) << (s + 1 < k + m ? " " : "\n");
      } else if (c == 'O') {
        uint64_t off; in >> off;
        for (unsigned s = 0; s < k; s++) std::cout << si.ro_offset_to_shard_offset(off, raw_shard_id_t(s)) << (s + 1 < k ? " " : "\n");
      } else if (c == 'R') {
        int shard; uint64_t off; in >> shard >> off;
        std::cout << si.shard_offset_to_ro_offset(shard_id_t(shard), off) << "\n";
      }
    }
    std::cout << ".\n" << std::flush;
  }
  return 0;
}
