/* Reference harness for the RBD striping in tests/sims/golden.json.
 *
 * gen_golden.py copies the upstream bodies of Striper::file_to_extents (the lightweight
 * overload), object_truncate_size, get_num_objects and get_file_offset, and the
 * OrderByObject comparator, out of src/osdc/Striper.cc into striper_extract.inc, and
 * compiles this file with g++ against the real src/osdc/StriperTypes.h. Only the logging,
 * the assert and boost's small_vector are stood in for (see the shim headers gen_golden.py
 * writes). Object names follow src/librbd/ImageCtx.cc (format_string) and
 * src/librbd/image/CreateRequest.cc (object prefix with a separate data pool).
 *
 * Commands on stdin, one per line:
 *   F os su sc off len trunc bufoff -> one line per extent: objno off len trunc be_off,be_len;...
 *   N os su sc size                  -> get_num_objects
 *   O os su sc objno off             -> get_file_offset
 *   T os su sc objno trunc           -> object_truncate_size
 *   D id mdpool objno                -> data object name (mdpool -1: no separate data pool)
 * CC BY-NC-SA 4.0, Ramin Najarbashi. */
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <iostream>
#include <sstream>
#include <string>
#include <algorithm>
#include <vector>
#include "osdc/StriperTypes.h"

struct CephContext {};
#define ldout(cct, v) if (0) std::cerr
#define lderr(cct) if (0) std::cerr
#define dendl std::endl
#define ceph_assert(x) assert(x)
typedef uint32_t __u32;

struct file_layout_t {
  uint32_t stripe_unit = 0, stripe_count = 0, object_size = 0;
  uint64_t get_period() const { return static_cast<uint64_t>(stripe_count) * object_size; }  // include/fs_types.h
};

struct Striper {
  static void file_to_extents(CephContext *cct, const file_layout_t *layout, uint64_t offset,
                              uint64_t len, uint64_t trunc_size, uint64_t buffer_offset,
                              striper::LightweightObjectExtents *object_extents);
  static uint64_t object_truncate_size(CephContext *cct, const file_layout_t *layout,
                                       uint64_t objectno, uint64_t trunc_size);
  static uint64_t get_num_objects(const file_layout_t &layout, uint64_t size);
  static uint64_t get_file_offset(CephContext *cct, const file_layout_t *layout,
                                  uint64_t objectno, uint64_t off);
};

#include "striper_extract.inc"

#define RBD_DATA_PREFIX "rbd_data."   /* include/rbd_types.h */

int main() {
  CephContext cct;
  std::string line;
  while (std::getline(std::cin, line)) {
    std::istringstream in(line);
    char c; in >> c;
    if (c == 'D') {
      std::string id; long long mdpool; unsigned long long objno;
      in >> id >> mdpool >> objno;
      // CreateRequest<I>::create_image: RBD_DATA_PREFIX [+ "<metadata pool id>."] + image id
      std::ostringstream oss; oss << RBD_DATA_PREFIX;
      if (mdpool != -1) oss << mdpool << ".";
      oss << id;
      std::string object_prefix = oss.str();
      // ImageCtx::init_layout (format 2) and format_oid in Striper.cc
      size_t len = object_prefix.length() + 16;
      std::vector<char> format_string(len);
      snprintf(format_string.data(), len, "%s.%%016llx", object_prefix.c_str());
      char buf[256];
      snprintf(buf, sizeof(buf), format_string.data(), (long long unsigned)objno);
      std::cout << buf << "\n";
      continue;
    }
    file_layout_t l; in >> l.object_size >> l.stripe_unit >> l.stripe_count;
    if (c == 'F') {
      uint64_t off, len, trunc, bo; in >> off >> len >> trunc >> bo;
      striper::LightweightObjectExtents ex;
      Striper::file_to_extents(&cct, &l, off, len, trunc, bo, &ex);
      std::cout << ex.size() << "\n";
      for (auto &e : ex) {
        std::cout << e.object_no << " " << e.offset << " " << e.length << " " << e.truncate_size;
        for (auto &b : e.buffer_extents) std::cout << " " << b.first << "," << b.second;
        std::cout << "\n";
      }
    } else if (c == 'N') {
      uint64_t size; in >> size; std::cout << Striper::get_num_objects(l, size) << "\n";
    } else if (c == 'O') {
      uint64_t o, off; in >> o >> off; std::cout << Striper::get_file_offset(&cct, &l, o, off) << "\n";
    } else if (c == 'T') {
      uint64_t o, t; in >> o >> t; std::cout << Striper::object_truncate_size(&cct, &l, o, t) << "\n";
    }
    std::cout.flush();
  }
  return 0;
}
