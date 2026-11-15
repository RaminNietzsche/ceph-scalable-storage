---
chapter: 15
id: ch15
title: 'RADOS Classes: Computing Next to the Data'
part: main
lang: en
---

::: {.tldr}

- RADOS classes run your methods inside the OSD, next to the object, saving round trips and avoiding races.
- Clients call them with `exec`; the OSD capability needs `x`.
- You can write your own class in C++ (the chapter builds `tally`) or run Lua scripts with cls_lua.
- Method flags (RD, WR) must match what the method really does; measure cost and correctness on a real cluster.

:::

# Before you start {#sec-15-1}

## What questions does this chapter answer? {#sec-15-1-1}

In typical architectures, data moves from storage to the application server, is processed there, and the result comes back. Ceph has another way too: **object classes** (Object Classes, or cls), shared libraries that run inside the OSD itself, next to the data. librbd, RGW and CephFS all rely on this mechanism. In this chapter we learn:

- What is a RADOS class, and why is computing next to the data beneficial?
- How does an OSD load, execute and control a class method?
- How do we write, build and deploy our own class?
- Which classes exist in Ceph, and which are useful to us?
- What is cls_lua, and why is it not loaded by default?
- Where are the security and operational boundaries of this power?

# Concept: computing next to the data {#sec-15-2}

## Why classes? {#sec-15-2-1}

Suppose you have a counter in an object's omap that several clients increment concurrently. Without a class, each client must read the value, add one and write it back; two network round trips and a race risk that must be handled with assert_version (chapter 14). With a class, the client just says "add one to key X", and the OSD performs the read-modify-write **under the PG lock and inside a single transaction**.

![Comparing two ways of incrementing a counter: in the client-side method, two clients read the value 10 and both write 11, and one update is lost; with the class method numops.add, the OSD runs the requests serially inside the PG and the final value is 13](figures/ch15/f03_rmw.png){#fig-15-f03_rmw}

Benefits of classes:

- **Fewer round trips**: one request instead of several.
- **Atomicity**: all of a method's changes are recorded in that object's transaction and replicated to the replicas.
- **Less data transfer**: filtering or summarizing happens next to the data, and only the result comes back.
- **Consistent logic**: the rules of a data structure (such as the RBD image header) are implemented in one place, and every client follows them.

::: {.warn}
A class method has access only to **that one object**. From inside a method you cannot read or write another object (because that object may be in a different PG and OSD). Any multi-object logic must be coordinated on the client side.
:::

## Existing classes {#sec-15-2-2}

![Map of the consumers of the built-in classes: librbd relies on cls_rbd for the image header and object map, RGW on cls_rgw for the bucket index and on cls_rgw_gc, cls_2pc_queue and cls_fifo for GC and queues; cls_lock, cls_version and cls_refcount are general purpose](figures/ch15/f04_users.png){#fig-15-f04_users}

| Class | Use |
|---|---|
| cls_rbd | Header and metadata of RBD images, snapshots, object map |
| cls_rgw | Bucket index and the index log (bilog) |
| cls_rgw_gc, cls_2pc_queue, cls_fifo, cls_queue | Garbage collection, notification queues and FIFO logs in RGW |
| cls_lock | Advisory shared and exclusive locks on objects |
| cls_version, cls_refcount | Versioning and reference counting |
| cls_log, cls_timeindex | Timestamped logs in the omap |
| cls_numops | Numeric add and mul operations on omap values |
| cls_hello | A sample class for teaching and testing |
| cls_lua | Running Lua scripts inside the OSD |

::: {.note}
In current code, the default values of `osd_class_load_list` and `osd_class_default_list` are both "cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex". So **lua** is not loaded by default and must be added to the list explicitly.
:::

# Calling a class from the client {#sec-15-3}

## Python {#sec-15-3-1}

```python
import rados, json
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c:
    with c.open_ioctx('devpool') as io:
        io.write_full('stats', b'')
        # cls_numops wants its input as two Ceph-encoded strings;
        # the simplest thing to try in Python is the hello class:
        ret, out = io.execute('greeting', 'hello', 'say_hello', b'Ramin')
        print(ret, out)          # output: b'Hello, Ramin!' (input over 100 bytes: -EINVAL)
```

The signature `Ioctx.execute(key, cls, method, data, length=8192)` in the Python binding returns a tuple (return code, output). `length` is the cap on the output size.

## C++ and compound operations {#sec-15-3-2}

```cpp
librados::ObjectWriteOperation op;
op.create(false);
bufferlist in;
encode(std::string("hits"), in);   // key
encode(std::string("1"), in);      // increment value
op.exec("numops", "add", in);      // class call inside a compound operation
int r = io.operate("stats", &op);
```

This is our own example, and the input pattern is the one `cls_numops.cc` expects: two encoded strings (key and value). The helper library `cls_numops_client.h` also provides the `add` and `mul` functions directly.

::: {.tip}
A class method can be combined with other operations in one `ObjectWriteOperation`; for example `assert_exists` + `exec` + `setxattr`, all executed atomically.
:::

## cephx access {#sec-15-3-3}

Executing a class method needs a suitable cap. `allow rwx` permits all classes; to restrict:

```bash
ceph auth caps client.devapp mon 'allow r' \
  osd 'allow rw class-read class-write pool=devpool'
ceph auth caps client.counter mon 'allow r' \
  osd 'allow rw pool=devpool, allow class numops add pool=devpool'
```

::: {.note}
`class-read` and `class-write` permit methods that have the RD or WR flag, but only for "allowed" classes (that is, those in `osd_class_default_list`). A class outside this list needs an explicit cap `class <name> [<method>]` (according to the capspec grammar in `src/osd/OSDCap.cc`: `class <name> [<method name>]`; in the second example only the add method of numops is permitted).
:::

# Writing our own class {#sec-15-4}

## Design: cls_tally {#sec-15-4-1}

For practice, we build a class called **tally** with two methods: `bump` (atomically increment a counter in the omap and return the new value) and `top` (read the counters and return the top n, so that not all keys have to be transferred to the client). We wrote this code ourselves, and it uses only the public `objclass.h` interface.

```cpp
// cls_tally.cc — teaching example for this book (not part of Ceph)
#include "objclass/objclass.h"
#include <string>
#include <map>
#include <vector>
#include <algorithm>

CLS_VER(1, 0)
CLS_NAME(tally)

// input: key name; output: the new value as a string
static int bump(cls_method_context_t hctx, ceph::bufferlist *in, ceph::bufferlist *out)
{
  std::string key(in->c_str(), in->length());
  if (key.empty() || key.size() > 256)
    return -EINVAL;
  ceph::bufferlist cur;
  uint64_t v = 0;
  int r = cls_cxx_map_get_val(hctx, key, &cur);
  if (r == 0)
    v = std::stoull(std::string(cur.c_str(), cur.length()));
  else if (r != -ENOENT && r != -ENODATA)
    return r;
  ++v;
  ceph::bufferlist nv;
  nv.append(std::to_string(v));
  r = cls_cxx_map_set_val(hctx, key, &nv);
  if (r < 0)
    return r;
  out->append(std::to_string(v));
  return 0;
}

// input: n; output: the n most frequent keys as "key=value\n"
static int top(cls_method_context_t hctx, ceph::bufferlist *in, ceph::bufferlist *out)
{
  int n = in->length() ? std::stoi(std::string(in->c_str(), in->length())) : 10;
  std::vector<std::pair<uint64_t, std::string>> all;
  std::string start;
  bool more = true;
  while (more) {
    std::map<std::string, ceph::bufferlist> vals;
    int r = cls_cxx_map_get_vals(hctx, start, "", 1000, &vals, &more);
    if (r < 0)
      return r;
    for (auto& [k, bl] : vals) {
      all.emplace_back(std::stoull(std::string(bl.c_str(), bl.length())), k);
      start = k;
    }
    if (vals.empty()) break;
  }
  std::partial_sort(all.begin(), all.begin() + std::min<size_t>(n, all.size()),
                    all.end(), std::greater<>());
  for (int i = 0; i < n && i < (int)all.size(); ++i)
    out->append(all[i].second + "=" + std::to_string(all[i].first) + "\n");
  return 0;
}

CLS_INIT(tally)
{
  cls_handle_t h_class;
  cls_method_handle_t h_bump, h_top;
  cls_register("tally", &h_class);
  cls_register_cxx_method(h_class, "bump", CLS_METHOD_RD | CLS_METHOD_WR, bump, &h_bump);
  cls_register_cxx_method(h_class, "top",  CLS_METHOD_RD, top, &h_top);
}
```

::: {.warn}
`std::stoull` throws an exception on corrupt data. An unhandled exception in a class method **crashes the OSD process**. In production code, wrap all conversions in try/catch and return `-EBADMSG`. This is exactly why Ceph is cautious about loading classes: a class runs with the OSD's own privileges.
:::

::: {.note}
**Version-dependent.** The registration form above (`cls_register_cxx_method` with explicit flags) is the interface of Tentacle (20.2.x) and earlier releases; this function exists in `src/include/rados/objclass.h` at tag v20.2.0. In Umbrella (21.2.0) and the main branch, this function has moved to `detail::cls_register_cxx_method_impl`, and registration happens through the typed template `ClassRegistrar<ClassDef>`; the RD/WR/PROMOTE flags are encoded in the method type (`RdTag`, `RdWrTag` and so on, defined in `src/include/rados/cls_traits.hpp`) so that client and server cannot disagree about the flags. The Umbrella version of the same class of ours:
:::

```cpp
// cls_tally_ops.h — teaching example for this book, Umbrella style
#include "include/rados/cls_traits.hpp"
namespace cls::tally {
struct ClassId { static constexpr auto name = "tally"; };
namespace method {
constexpr auto bump = ClsMethod<RdWrTag, ClassId>("bump");
constexpr auto top  = ClsMethod<RdTag,   ClassId>("top");
}}
// cls_tally.cc (registration part)
CLS_INIT(tally)
{
  using namespace cls::tally;
  cls_handle_t h_class;
  cls_method_handle_t h_bump, h_top;
  cls_register(ClassId::name, &h_class);
  ClassRegistrar<ClassId> cls(h_class);
  cls.register_cxx_method(method::bump, bump, &h_bump);
  cls.register_cxx_method(method::top,  top,  &h_top);
}
```

## Building and deploying {#sec-15-4-2}

There are two ways to build: inside the Ceph source tree (adding a directory to `src/cls` and `CMakeLists.txt`) or with the **object class SDK**, which the official documentation introduces for out-of-tree builds (reference example: `src/cls/sdk/cls_sdk.cc`).

```bash
# on a build machine with Ceph development headers of the same version as the cluster
g++ -std=c++17 -fPIC -shared -O2 -o libcls_tally.so cls_tally.cc \
    $(pkg-config --cflags librados) -lrados
# the class path on the OSD
ceph config get osd osd_class_dir
```

::: {.warn}
The class must be built with **the same Ceph version and the same compiler/ABI** that runs on the OSDs. In a cephadm deployment, the OSD runs inside a container and `osd_class_dir` points to a path inside the image; copying the file onto the host is not enough. The durable way is to build a **custom image** on top of the official image of the same version, adding `libcls_tally.so` to that directory, then `ceph orch upgrade start --image <image>` or setting `container_image`.
:::

```bash
ceph config set osd osd_class_load_list "cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex tally"
ceph config set osd osd_class_default_list "cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex tally"
ceph orch restart osd.<service>     # the class is loaded on first call after startup
```

::: {.tip}
When changing these two lists, **keep the default values**. If you write only `tally`, the OSD no longer loads cls_rbd or cls_rgw, and RBD and RGW stop working. Before changing, read the current value with `ceph config get osd osd_class_load_list`.
:::

## Calling and testing {#sec-15-4-3}

```python
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c:
    with c.open_ioctx('devpool') as io:
        for w in ['ceph', 'rados', 'ceph', 'osd', 'ceph']:
            ret, out = io.execute('words', 'tally', 'bump', w.encode())
        ret, out = io.execute('words', 'tally', 'top', b'2')
        print(out.decode())       # ceph=3 and then one of the others
```

::: {.debug}
If the call returns `-EOPNOTSUPP` (Operation not supported), either the class was not loaded or the method does not exist; search the primary OSD's log for the message "not permitted to load" or "does not exist". `-EPERM` is usually a cap problem.
:::

# cls_lua: scripts inside the OSD {#sec-15-5}

The `lua` class runs a Lua interpreter inside the OSD. The client calls the `eval_json` (or `eval_bufferlist`) method with an input containing `script`, `handler` and (optionally) `input`. The script runs first, and the handler function must have been registered with `cls.register`; the OSD then calls it with two arguments, input and output (both bufferlists). Functions such as `read`, `write_full`, `map_get_val`, `map_set_val`, `setxattr`, `stat` and `log` are available (the `clslua_lib` table in `src/cls/lua/cls_lua.cc`). These functions live in the global table **`objclass`**, not `cls`: the function `clslua_setup_env` registers them with `luaL_requiref(L, "objclass", luaopen_objclass, 1)`. That is why the script must say `objclass.read(…)` and `objclass.register(…)`. We tested this on Ceph 18.2.7. With `cls.register` we got the error `attempt to index a nil value (global 'cls')`, and the same example worked correctly with `objclass`.

```lua
-- our own example: count an object's lines next to the data
function count_lines(input, output)
  local size = objclass.stat()
  local data = objclass.read(0, size)
  local s = data:str()
  local _, n = s:gsub("\n", "")
  output:append(tostring(n))
end
objclass.register(count_lines)
```

::: {.warn}
cls_lua is **not** in the default class list. Enabling it means that any client with a suitable cap can run arbitrary code inside the OSD; an infinite loop or reading a multi-hundred-megabyte object blocks the OSD thread and the PG and creates slow ops. Enable it only in a controlled environment and with a restricted cap (`allow class lua eval_json pool=...`).
:::

# Three algorithms from the class path {#sec-15-6}

## Validating a CALL {#sec-15-6-1}

::: {.algo #alg-15-1 title="Checking the RD/WR flags before and after running a class method" src="src/osd/osd_op_util.cc :: OpInfo::set_from_op (the CEPH_OSD_OP_CALL branch); src/osd/ClassHandler.cc :: ClassHandler::open_class, _get_class, in_class_list; src/osd/PrimaryLogPG.cc :: PrimaryLogPG::do_osd_ops" complexity="O(length of the class list) only on first load; then O(log M) to find the method in the map"}
:::

```text
pseudocode
set_from_op:
    cls = open_class(cname)            # not in load_list ⇒ EPERM , no file ⇒ EOPNOTSUPP
    flags = cls.get_method_flags(mname)   # missing ⇒ EOPNOTSUPP
    RD ⇒ CLASS_READ (+ CLASS_READ_DATA in EC) ; WR ⇒ CLASS_WRITE ; PROMOTE ⇒ promote
    add_class(cname, mname, rd, wr, cls.allowed)  # for OSDCap::is_capable
do_osd_ops:
    if WR: user_modify = true
    r0, w0 = num_read, num_write ; r = exec(ctx, in, out)
    if num_read > r0 and !RD: EIO ; if num_write > w0 and !WR: EIO
```

**Numerical example.** A class called `tally` (this chapter's sample class) has registered the method `inc` with only the `CLS_METHOD_WR` flag, but inside the method it calls `cls_cxx_map_get_val` to read the previous value.

1. **Before execution:** the op is labelled write-only, and the cap `allow class-write` is enough.
2. **During execution:** every read call inside the class takes num_read from 0 to 1.
3. **After exec:** the check num_read > r0 without RD holds, and the OSD returns EIO. The log also shows the message "tried to read object but is not marked RD".

The fix is to register the method with `CLS_METHOD_RD | CLS_METHOD_WR`. In that case the user's cap must also include `class-read`. If `tally` is not in `osd_class_load_list`, EPERM is returned before all of these steps. The default list in v20.2.0 and main includes 20 built-in classes: cephfs, hello, journal, lock, log, numops, otp, rbd, refcount, rgw, rgw_gc, timeindex, user, version, cas, cmpomap, queue, 2pc_queue, fifo and sem_set. lua and sdk are not in this list.

![The three stages of validating a CALL. The first row runs when the message arrives and finds the class and method. The second row converts the method's registered flags into op flags so that OSDCap can check permission and the PG knows whether the op reads or writes. The third row compares the read and write counters after the method runs. A method that behaves contrary to its flags is rejected with EIO](figures/ch15/f05_callcheck.png){#fig-15-f05_callcheck}

## The cls_lock advisory lock {#sec-15-6-2}

::: {.algo #alg-15-2 title="Acquiring, renewing and expiring a lock in cls_lock" src="src/cls/lock/cls_lock.cc :: lock_obj, read_lock; src/cls/lock/cls_lock_types.h :: LOCK_FLAG_MAY_RENEW, LOCK_FLAG_MUST_RENEW" complexity="O(L log L) for L lock holders (decoding and walking the map); one xattr per lock name"}
:::

```text
pseudocode
linfo = decode(xattr "lock." + name) ; drop holders whose expiration < now   # lazy expiry
if both MAY_RENEW and MUST_RENEW: EINVAL
if lockers ≠ ∅ and tag ≠ linfo.tag: EBUSY
id = (source entity_name, cookie)
if id ∈ lockers: if not MAY_RENEW ⇒ EEXIST , otherwise remove the old entry
elif MUST_RENEW: ENOENT
if lockers ≠ ∅: exclusive ⇒ EBUSY ; different type ⇒ EBUSY
lockers[id] = (now + duration, or 0 = no expiry, addr, description) ; write xattr
```

**Numerical example.** An exclusive lock with duration = 30 s:

- **t = 0:** client A takes the lock with cookie c1 (expires at 30).
- **t = 10:** B tries and gets EBUSY.
- **t = 20:** A tries again without a flag and gets EEXIST.
- **t = 25:** A renews with MAY_RENEW (expires at 55).
- **t = 60:** B tries again. read_lock removes A's entry, because 55 < 60, and B gets the lock (expires at 90).
- **t = 70:** A asks to renew with MUST_RENEW and gets ENOENT, because it is no longer a holder.

Expiry is applied only on the next access; that is, there is no timer in the OSD. The comparison clock is also the primary OSD's clock, not the client's. Anyone can break another's lock with `rados lock break` or `rbd lock remove`. The cls_lock lock is advisory. To stop an old client from writing, RBD pairs breaking the lock with blocklisting (chapter 29).

![Timeline of six lock requests from two clients on one object. Green points succeed and red ones fail. Shaded bars are the lock holding intervals. A's renewal at second 25 moves the expiry to 55. Because nobody touches the lock before second 60, A's entry stays in the xattr until then and is only cleared by B's request](figures/ch15/f06_lock.png){#fig-15-f06_lock}

## Paged omap reads inside a class {#sec-15-6-3}

::: {.algo #alg-15-3 title="Paging in cls_cxx_map_get_vals" src="src/osd/objclass.cc :: cls_cxx_map_get_vals; src/osd/PrimaryLogPG.cc :: do_osd_ops (CEPH_OSD_OP_OMAPGETVALS)" complexity="O(log K + n) for K omap keys and n returned keys (one seek and a scan)"}
:::

```text
pseudocode
max_return = min(max_to_get, osd_max_omap_entries_per_request = 1024)
seek = max(start_after, filter_prefix) ; kind = (prefix > start_after) ? LOWER_BOUND : UPPER_BOUND
iterate (key, value):
    if key does not have the filter_prefix: STOP
    if num ≥ max_return or bytes ≥ osd_max_omap_bytes_per_request (1 GiB): truncated = true ; STOP
    encode(key, value) ; num++
return (vals, more = truncated)
```

**Numerical example.** An object has 2500 keys `u_0000` to `u_2499` and a few keys with a different prefix. The class reads in a loop with filter_prefix = "u_" and max_to_get = 1000.

- **Call 1:** empty start_after, 1000 keys, more = true.
- **Call 2:** start_after = "u_0999", 1000 keys, more = true.
- **Call 3:** start_after = "u_1999", 500 keys. The next key has a different prefix, so STOP without truncated, and more = false.

more is true only if another matching key was actually seen. So if there were exactly 1000 keys, the first call returns more = false. If the class asks for max_to_get = 5000, the OSD silently lowers it to 1024. Code that assumes "I got fewer than I asked for, so it is finished" is wrong. Rely only on more.

![Three consecutive cls_cxx_map_get_vals calls over 2500 keys with the prefix u_. Each call continues from the last key of the previous call (UPPER_BOUND, that is, the key after start_after). The red line is the cap of 1024 keys per request, applied to max_to_get. The more flag is false only on the last page](figures/ch15/f07_omap.png){#fig-15-f07_omap}

::: {.debug}
If your class method returns EIO, first enable `debug_osd = 10` on the primary OSD and look for "tried to read object but is not marked RD" or "tried to update object but is not marked WR". If you get EPERM, check `ceph config get osd osd_class_load_list`.
:::

# Classes on a real cluster: correctness and cost {#sec-15-7}

The two experiments in this section ran on a three-OSD BlueStore test cluster with Ceph 18.2.7. The client was python-rados and used `Ioctx.execute`.

## A counter: cls_numops versus client-side read and write {#sec-15-7-1}

::: {.algo #alg-15-4 title="Atomic increment with a class method" src="src/cls/numops/cls_numops.cc :: add (cls_cxx_map_get_val, then cls_cxx_map_set_val); serialization by the PG lock in PrimaryLogPG" complexity="O(1) per increment"}
:::

```text
pseudocode
input: encode(string key) ‖ encode(string diff)           # each string = u32 length + bytes
cls: v = map_get_val(key) or 0 ; v += diff ; map_set_val(key, str(v))   # one op, under the PG lock
client (unsafe method): v = read omap(key) ; write omap(key, v+1)          # two separate ops, no lock
N threads × K increments on one object ← compare the final value with N×K
```

**Result (300 increments per thread).** With cls_numops the final value was exactly N × 300 in all five cases (1, 2, 4, 8 and 16 threads). The client-side read-and-write method was correct with one thread, but with 2 threads 297 of 600 increments were lost (50%), with 4 threads 64%, with 8 threads 79% and with 16 threads 89%.

The reason is that the OSD executes each op on an object under the PG lock, so `add` is not interrupted between the read and the write. Two separate client ops have no such guarantee. The time cost on this shared virtual machine fluctuated widely: medians of 0.25 to 6 milliseconds and spikes of about 0.2 seconds at the 99th percentile, whose cause we did not investigate. So draw no conclusions from the latency numbers.

If you have no suitable class, the right client-side approach is a conditional transaction: put `cmpxattr` or `assert_version` in the same write op, and retry if the condition does not hold. If the `cmpxattr` comparison fails, the error is `ECANCELED`. If the `assert_version` version is lower or higher than the object's current version, the error is `ERANGE` or `EOVERFLOW` respectively (`PrimaryLogPG::do_osd_ops`).

![Left: the counter's final value after 300 increments per thread, with cls_numops (green) and with reading the omap, adding one and writing from the client side (red). The black line is the expected value. Right: the median time per increment on the Ceph 18.2.7 test cluster](figures/ch15/f08_numops.png){#fig-15-f08_numops}

## Filtering next to the data with cls_lua: when is it worth it? {#sec-15-7-2}

In Ceph 18.2.7 the lua class is not in the default `osd_class_load_list`. For this experiment we added `lua` to both lists and restarted the OSDs. We then ran the same `count_lines` script from the previous section on objects from 64 KiB to 16 MiB and compared it with "read the whole object and count on the client". Each point was the median of 15 runs.

::: {.algo #alg-15-5 title="The break-even point of processing next to the data" src="measurement; clslua_read, clslua_stat and eval_json in src/cls/lua/cls_lua.cc" complexity="O(object size) in both methods"}
:::

```text
pseudocode
t_lua(S)    = eval_json time on an object of S bytes          # a reply of a few bytes
t_client(S) = read(S) time over loopback + counting        # no network cost
on a real network: t_client(S, B) ≈ t_client(S) + S / B
break-even: B* = S / (t_lua(S) − t_client(S))      ← if the effective bandwidth is below B*, Lua finishes first
```

**Result.** Over loopback, Lua was four to five times slower. For 16 MiB, the Lua time was 111.6 milliseconds and the client time 29.4 milliseconds. The reason is that each request creates a fresh Lua state, compiles the script and runs `gsub` in the interpreter. The Lua reply was only 4 to 6 bytes, against the whole object.

The break-even bandwidth from these measurements is about 0.58 Gb/s for 64 KiB and about 1.63 Gb/s for 16 MiB. So on a 10-gigabit network, reading to the client is faster. Lua is only worth it when the link is slow or congested, or when the filter rejects many objects and returns little data.

The more important hidden cost is that a 111-millisecond Lua run holds the PG lock the whole time. Every other op on that PG queues behind it.

![Left: median time to count lines in objects of 64 KiB to 16 MiB, with cls_lua inside the OSD (purple) and with reading the whole object on the client (blue) over loopback. The dashed lines show the same client time plus the transfer time over 10 and 1 gigabit (computed). Right: the break-even bandwidth below which the Lua run finishes first](figures/ch15/f09_lua.png){#fig-15-f09_lua}

# Inside the code: the path of a class call {#sec-15-8}

## From MOSDOp to method->exec {#sec-15-8-1}

![The full path of a class call in three rows: the client sends a CEPH_OSD_OP_CALL request to the primary through the Objecter; PrimaryLogPG::do_osd_ops decodes the class and method names and opens the class with ClassHandler; then the method runs, the read and write counts are compared with the declared flags, and the changes are recorded in the PG transaction](figures/ch15/f01_flow.png){#fig-15-f01_flow}

On the client side, `exec` adds a `CEPH_OSD_OP_CALL` sub-operation to the compound operation, containing the length of the class name, the length of the method name and the input data. In the OSD, `PrimaryLogPG::do_osd_ops()` separates these three from the payload in the `case CEPH_OSD_OP_CALL` branch. The key part of this branch is the check of the method's honesty:

```cpp
// from ceph/ceph, LGPL — src/osd/PrimaryLogPG.cc, do_osd_ops(), case CEPH_OSD_OP_CALL (excerpt)
int prev_rd = ctx->num_read;
int prev_wr = ctx->num_write;
result = method->exec((cls_method_context_t)&ctx, indata, outdata);

if (ctx->num_read > prev_rd && !(flags & CLS_METHOD_RD)) {
  derr << "method " << cname << "." << mname << " tried to read object but is not marked RD" << dendl;
  result = -EIO;
  break;
}
if (ctx->num_write > prev_wr && !(flags & CLS_METHOD_WR)) {
  derr << "method " << cname << "." << mname << " tried to update object but is not marked WR" << dendl;
  result = -EIO;
  break;
}
```

Why does this check matter? Before execution, the flags are used in `init_op_flags()` to determine the type of operation (read or write): a write operation must go to the primary, be recorded in the PG log and replicated to the replicas, and, in a pool with snapshots, trigger cloning. If a method writes without the WR flag, the OSD might process it like a read, and the change would stay unreplicated. So Ceph checks after execution and returns `-EIO` on a violation. The third flag, `CLS_METHOD_PROMOTE`, was for cache tiering (chapter 16) and told the OSD that the object had to be brought into the cache tier before execution.

```text
pseudocode: CALL in do_osd_ops (this book's summary)
  decode(class_name, method_name, indata)  else -EINVAL
  cls    = ClassHandler.open_class(class_name)      # confirmed in init_op_flags
  method = cls.get_method(method_name)               else -EOPNOTSUPP
  if method.flags & WR: ctx.user_modify = true
  snapshot(num_read, num_write)
  r = method.exec(ctx, indata, &outdata)             # cls_cxx_* work inside ctx.ops
  verify RD/WR honesty                               else -EIO
  if r >= 0: append outdata to reply                 # changes in ctx->op_t
```

## Loading a class: ClassHandler {#sec-15-8-2}

![The two stages of loading a class in ClassHandler: top, the first call, with the osd_class_load_list check, dlopen of libcls_X.so from osd_class_dir and running __cls_init; bottom, registering methods with names and flags and setting the allowed state from osd_class_default_list, which affects how the class-read and class-write caps are interpreted](figures/ch15/f02_load.png){#fig-15-f02_load}

`ClassHandler::_get_class()` in `src/osd/ClassHandler.cc` writes "not permitted to load" to the log and returns NULL if the class is not in `osd_class_load_list`. It then sets `allowed` from `osd_class_default_list`. `_load_class()` opens the file `libcls_<name>.so` from `osd_class_dir` with `dlopen` and runs the function `__cls_init` (which the `CLS_INIT(name)` macro defines); that function fills the class's method table with `cls_register` and method registrations. A class can declare its dependencies with the optional symbol `class_deps` so that they are loaded first (`dlsym(cls->handle, "class_deps")`).

| Setting | Role | Default in current code |
|---|---|---|
| osd_class_dir | Path of the libcls_*.so files | The rados-classes path under the install libdir |
| osd_class_load_list | Classes allowed to load | cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex |
| osd_class_default_list | Classes allowed for generic caps | The same list |
| osd_open_classes_on_start | Open classes when the OSD starts | true |

::: {.deep}
The failure model: a class runs in the OSD's address space. There is no sandbox, memory limit or independent timeout for a method; the method runs in the same PG processing thread that holds the PG lock. So a slow method holds **every other operation on that PG** behind it, and shows up in `ceph health detail` as slow ops. This is why good classes (like cls_rgw) limit the amount of work per call (for example reading the omap in bounded batches with `max_return`) and leave the rest of the work to the client's next call.
:::

## The execution context: cls_method_context_t {#sec-15-8-3}

`cls_method_context_t` is really a pointer to that operation's `OpContext`. The functions `cls_cxx_read`, `cls_cxx_write_full`, `cls_cxx_map_get_val` and `cls_cxx_map_set_val` (in `src/osd/objclass.cc`) each build an OSD sub-operation and run it through the same `do_osd_ops` path; that is, a class actually builds a **dynamic compound operation** that is applied inside the current transaction. That is why the `num_read` and `num_write` counters go up with each call of these functions, and why checking flag honesty is possible.

```text
cls_cxx_map_set_val(hctx, key, bl):
    op = OSDOp(CEPH_OSD_OP_OMAPSETVALS, encode({key: bl}))
    return do_osd_ops(ctx, [op])     # the write is added to ctx->op_t; num_write++
```

# Pitfalls and design patterns {#sec-15-9}

| Pitfall | Consequence | The right way |
|---|---|---|
| Changing osd_class_load_list without keeping the defaults | RBD, RGW and CephFS stop working | Always read the current value and append to it |
| A method with unbounded work | Slow ops, a blocked PG | Paging with max_return and continuing from the client side |
| An unhandled C++ exception | OSD crash on all replicas | try/catch and returning an error code |
| Mismatched class and OSD versions | dlopen errors or undefined behaviour | Build in a same-version image, test in staging |
| Wrong RD/WR flags | -EIO errors | Exact flags; in Umbrella use the Tags |

::: {.summary title="SRE notes for this chapter"}

- A class runs with full OSD privileges; review its code like kernel code.
- Compare every change to the class lists with the default value.
- Keep the work per call bounded.
- Enable cls_lua only deliberately and with a restricted cap.
- In cephadm, a custom class means a custom image; plan upgrades around it.

:::

# Supplementary and up to date {#sec-15-10}

- In Umbrella (21.2.0), method registration has become typed (`ClassRegistrar` and `ClsMethod<Tag, ClassDef>`); out-of-tree classes built for Tentacle need their registration part rewritten when upgrading.
- Newer classes in the tree, such as `cls_fifo`, `cls_2pc_queue` and `cls_cmpomap`, provide queue patterns and atomic omap comparison for RGW.
- Cache tiering, which the PROMOTE flag was for, was declared deprecated in Reef (chapter 16).

# Hands-on exercise {#sec-15-11}

1. With `io.execute(..., 'hello', 'say_hello', ...)`, try empty inputs, short inputs and inputs over 100 bytes.
2. Restrict the user's cap to `allow class hello say_hello` and see what error `record_hello` gives.
3. Increment a counter from ten concurrent processes, once with client-side read-modify-write and once with numops.add, and compare.
4. Build the tally class, deploy it in a test cluster and measure top on ten thousand keys.
5. In `src/osd/ClassHandler.cc`, follow the dependency loading path.
6. Enable the lua class in a test cluster and run the line-counting script; then write a long loop and see its effect on slow ops.

# Review questions {#sec-15-12}

1. What are the three main benefits of running logic in a class instead of the client?
2. Why can a class method not modify another object?
3. What is the difference between osd_class_load_list and osd_class_default_list?
4. What happens if a method writes without the WR flag, and why?
5. What exactly does the cap "allow class numops add" permit?
6. Why is cls_lua not loaded by default?
7. How do you deploy a custom class in cephadm?
8. What changed in the method registration interface in Umbrella?
9. What effect does a slow method have on the PG's other operations?
10. Which classes do librbd and RGW use?

# Sources for this chapter {#sec-15-13}

- SDK for Ceph Object Classes: https://docs.ceph.com/en/latest/rados/api/objclass-sdk/
- OSD config reference (classes): https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/
- User management and capabilities: https://docs.ceph.com/en/latest/rados/operations/user-management/
- Source: src/cls: https://github.com/ceph/ceph/tree/main/src/cls
- Source: src/osd/ClassHandler.cc: https://github.com/ceph/ceph/blob/main/src/osd/ClassHandler.cc
- Source: src/osd/OSDCap.cc: https://github.com/ceph/ceph/blob/main/src/osd/OSDCap.cc
- Source: src/include/rados/objclass.h (v20.2.0): https://github.com/ceph/ceph/blob/v20.2.0/src/include/rados/objclass.h
- Source: src/include/rados/cls_traits.hpp: https://github.com/ceph/ceph/blob/main/src/include/rados/cls_traits.hpp
- Source: src/cls/lua/cls_lua.cc: https://github.com/ceph/ceph/blob/main/src/cls/lua/cls_lua.cc
