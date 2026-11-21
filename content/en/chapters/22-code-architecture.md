---
chapter: 22
id: ch22
title: Ceph Code Architecture and the Request Path from the Inside
part: special
lang: en
---

::: {.tldr}

- The ceph/ceph repository is a large C++ monorepo with Python parts and submodules; build it with `do_cmake.sh`, CMake and Ninja and test with vstart.
- The OSD talks to storage only through `ObjectStore::Transaction`; BlueStore is one implementation.
- No blocking work may run in a messenger thread or while holding a PG lock; structures are versioned with encode/decode for compatibility.
- The chapter follows a RADOS write and an RGW PUT function by function and times the write path with OpTracker.

:::

# Repository map {#sec-22-1}

The `github.com/ceph/ceph` repository is a large C++ monorepo with Python parts. On the main branch, the `src/` directory contains, in addition to Ceph's own code, several submodules and external libraries (rocksdb, seastar, spdk, isa-l, fmt, googletest, s3select, arrow, zstd and so on). Knowing this boundary is the first step in reading the code: whatever is inside these submodules is not Ceph code.

![Map of the main src/ directories on the main branch. The first row is the shared base code: basic types and encoding in include, the config, log, perf counter and thread infrastructure in common, the network layer in msg/async, cephx authentication in auth and the CRUSH algorithm in crush. The second row is the client libraries: Objecter and Striper in osdc, librados, librbd, the CephFS client in client and OSD-side classes in cls and objclass. The third row is the daemons: mon, osd, os (ObjectStore and BlueStore), mds and mgr. The fourth row is the rest: rgw, crimson (the next-generation OSD on Seastar), the erasure-code plugins, command-line tools in tools and Python code in pybind and python-common](figures/ch22/f01_repo.png){#fig-22-f01_repo}

| Directory | Where to start reading | Why |
|---|---|---|
| `src/osd/` | `OSD.cc` (dispatch and shards), `PrimaryLogPG.cc` (op execution), `PeeringState.cc` | the data path and PG convergence |
| `src/os/bluestore/` | `BlueStore.cc` (`queue_transactions`, `_do_write`), `bluestore_types.h` | the on-disk format |
| `src/osdc/` | `Objecter.cc` (`op_submit`, `_calc_target`) | the client path and retry |
| `src/mon/` | `Monitor.cc`, `Paxos.cc`, `PaxosService.cc`, `OSDMonitor.cc` | maps and consensus |
| `src/msg/async/` | `AsyncMessenger.cc`, `AsyncConnection.cc`, `ProtocolV2.cc`, `Event.h` | networking and msgr2 |
| `src/common/options/` | `global.yaml.in`, `osd.yaml.in`, `rgw.yaml.in`, `mds.yaml.in`, `rbd.yaml.in` | the authoritative source of defaults |
| `src/crimson/` | `osd/osd.cc` | the rewrite of the OSD based on Seastar (shared-nothing, one reactor per core) |

::: {.tip}
To find the real default of any option, instead of searching blogs go straight to the `src/common/options/*.yaml.in` file at that version's tag (for example `v20.2.0`). All of this book's default tables were extracted from these files.
:::

# Build and development environment {#sec-22-2}

The build is done with CMake and Ninja. The `do_cmake.sh` script at the repository root creates the `build` directory (its name can be changed with the `BUILD_DIR` variable) and runs CMake with `-GNinja`. Extra flags can be passed with the `ARGS` variable. The target named `vstart` in `src/CMakeLists.txt` builds only what is needed for a local development cluster.

```bash
git clone https://github.com/ceph/ceph.git && cd ceph
git submodule update --init --recursive
./install-deps.sh
ARGS="-DCMAKE_BUILD_TYPE=Debug -DWITH_MGR_DASHBOARD_FRONTEND=OFF" ./do_cmake.sh
cd build && ninja vstart            # only the components needed for vstart
# local cluster: 1 MON, 3 OSDs, no MDS
MON=1 OSD=3 MDS=0 MGR=1 ../src/vstart.sh -n -d -x --bluestore
./bin/ceph -s
../src/stop.sh
```

The `vstart.sh` options, from the script's own help text: `-n` (new cluster), `-d` (debug), `-x`/`-X` (enable/disable cephx), `-l` (localhost) and `-b` (BlueStore, which is the default). The number of daemons is set with the environment variables `MON`, `OSD`, `MDS`, `MGR`, `RGW` and so on.

::: {.note}
A full Ceph build needs tens of gigabytes of space and a lot of memory. To read the code, it is enough to clone the repository with `--filter=blob:none` and sparse-checkout only the directories you need. The author of this guide also used this method to check names.
:::

# Main classes and relationships {#sec-22-3}

![Relationships of the main classes on the data path. On the client side, RadosClient owns an Objecter. Objecter keeps an OSDSession for each OSD and establishes connections (AsyncConnection with ProtocolV2) through AsyncMessenger. On the OSD side, the OSD class, which is the message Dispatcher, has N OSDShard objects, each with its own scheduler (default mClockScheduler). Each PG is mapped to a shard by hash. PrimaryLogPG extends PG and has PeeringState and PGLog, and performs replication through PGBackend (the ReplicatedBackend or ECBackend implementations). In the storage layer, each change is an ObjectStore::Transaction that BlueStore executes with Collection, Onode and TransContext on top of RocksDB, BlueFS and the Allocator](figures/ch22/f02_classes.png){#fig-22-f02_classes}

## The ObjectStore interface {#sec-22-3-1}

`src/os/ObjectStore.h` is the boundary between PG logic and storage. The OSD never writes directly to disk. The OSD builds an `ObjectStore::Transaction` (defined in `src/os/Transaction.h`) containing a list of operations such as `write`, `zero`, `truncate`, `remove`, `setattrs`, `omap_setkeys` and `omap_rmkeys` on collections, and hands it to the backend with `queue_transactions`. The backend guarantees that the whole transaction is **atomic**. This property is why the data object and the pg log entry become durable at the same time. The existing implementations are BlueStore (the default), MemStore (testing) and, in crimson, SeaStore and CyanStore.

# Thread model {#sec-22-4}

![The thread model in the classic OSD. The first row is networking: there are ms_async_op_threads (default 3) Workers, each running an epoll-based EventCenter. Data messages are delivered in the same network thread through ms_fast_dispatch to reduce queue and context switch cost. The second row is op processing: an op is queued in the scheduler of one of the OSDShards based on the hash of the PG ID, and the ShardedThreadPool has threads_per_shard threads per shard that pick up the op, take the PG lock and run do_request. The third row is helpers: Finisher for running callbacks in a separate thread, SafeTimer for timed events such as tick and heartbeat, and BlueStore's two main threads, kv_sync_thread and kv_finalize_thread](figures/ch22/f03_threads.png){#fig-22-f03_threads}

| Class | File | Role |
|---|---|---|
| `ShardedThreadPool`, `OSD::ShardedOpWQ` | `common/WorkQueue.h`, `osd/OSD.h` | the sharded op queue; op order within each PG is preserved |
| `OSDShard` | `osd/OSD.h` | holds the scheduler, the shard's PGs and its lock |
| `Finisher` | `common/Finisher.h` | a callback queue with a dedicated thread |
| `SafeTimer` (= `CommonSafeTimer<ceph::mutex>`) | `common/Timer.h` | event scheduling |
| `Worker`, `NetworkStack`, `EventCenter` | `msg/async/Stack.h`, `msg/async/Event.h` | the network event loop |

::: {.warn}
The golden rule in OSD code is that no blocking work (synchronous I/O, a long lock) may be done in a network thread or while holding a PG lock. Many strange "slow requests" in the past came from violating this rule. A heartbeat_map warning with the message `had timed out after` in the OSD log is a sign of a thread stuck in ShardedOpWQ.
:::

# Encoding and version compatibility {#sec-22-5}

Every structure that goes over the network or to disk is serialized with the `include/encoding.h` infrastructure or its faster version `include/denc.h`. The main pattern is **versioning each struct** with two numbers: `struct_v` (the current version) and `compat` (the lowest version whose decoder can read this data). The block length is also stored so that an old decoder can skip new trailing fields. The macros are `ENCODE_START(v, compat, bl)`, `ENCODE_FINISH(bl)`, `DECODE_START(v, bl)`, `DECODE_FINISH(bl)` and `WRITE_CLASS_ENCODER(cl)`. In denc, the equivalents are `DENC_START(v, compat, p)` and `WRITE_CLASS_DENC(T)`.

```cpp
// this guide's own example (not from Ceph code): adding a field while keeping compatibility
struct demo_info_t {
  uint64_t size = 0;
  std::string owner;          // added in version 2
  void encode(ceph::buffer::list& bl) const {
    ENCODE_START(2, 1, bl);   // v=2, a version 1 decoder can also read it
    encode(size, bl);
    encode(owner, bl);
    ENCODE_FINISH(bl);
  }
  void decode(ceph::buffer::list::const_iterator& p) {
    DECODE_START(2, p);
    decode(size, p);
    if (struct_v >= 2) decode(owner, p);
    DECODE_FINISH(p);         // unknown fields from later versions are skipped
  }
};
WRITE_CLASS_ENCODER(demo_info_t)
```

::: {.deep}
This mechanism is the basis of **rolling upgrades**. A new-version OSD encodes OSDMap or MOSDOp with more fields, and an old OSD reads it by skipping the end of the block. If a change is truly incompatible, `compat` goes up, and the upgrade is then tied to flags such as `require_osd_release`. The `ceph-dencoder` tool in `src/tools/ceph-dencoder/` exposes these same encoders for compatibility testing and inspecting real data.
:::

# Reading and debugging the code in practice {#sec-22-6}

| Tool | Example | Use |
|---|---|---|
| debug level | `ceph config set osd.3 debug_osd 20/20` | the first number is the written log level and the second the in-memory level kept for dumping on a crash |
| admin socket | `ceph daemon osd.3 help`, `config show`, `dump_ops_in_flight` | direct commands to the daemon on the same host (`common/admin_socket.cc`) |
| OpTracker | `ceph daemon osd.3 dump_historic_ops` | timestamped events of each op; `osd_op_history_size=20` and `osd_op_history_duration=600` |
| ceph-dencoder | `ceph-dencoder type OSDMap import om decode dump_json` | decoding and displaying binary structures |
| ceph-objectstore-tool | `--op list`, `--op log`, `dump` | offline inspection of BlueStore and PGs |
| gdb | `gdb -p $(pidof ceph-osd)` then `thread apply all bt` | analysing hangs; `-dbg` packages or `debuginfod` are needed |
| tracing | `jaeger_tracing_enable` (default false), `osd_blkin_trace_all` | distributed request tracing; requires a build with Jaeger/OpenTelemetry support |

```bash
# reading an op's path in the log: follow the tid and reqid
ceph config set osd.3 debug_osd 20 ; ceph config set osd.3 debug_bluestore 20
rados -p test put obj1 /etc/hosts
grep -E 'do_op|execute_ctx|issue_repop|_txc_state_proc' /var/log/ceph/ceph-osd.3.log | tail
ceph config rm osd.3 debug_osd ; ceph config rm osd.3 debug_bluestore
ceph-dencoder list_types | grep -i -E 'osdmap|pg_log'
```

# The full path of a RADOS write, function by function {#sec-22-7}

![Sequence diagram of a replicated write from librados to the ack. Objecter computes the target and sends MOSDOp over msgr2 to the primary. On the primary, the message is received in ms_fast_dispatch and queued in the PG's shard. A worker thread picks it up and brings it through do_request and do_op to execute_ctx, where prepare_transaction with do_osd_ops turns the operations into an ObjectStore::Transaction. issue_repop sends the transaction to the replicas through the backend and at the same time hands the local transaction to BlueStore. When all acting members have committed, eval_repop sends the reply to the client](figures/ch22/f04_write.png){#fig-22-f04_write}

| Step | Function (file) | What it does |
|---|---|---|
| 1 | `Objecter::op_submit` → `_op_submit` (`osdc/Objecter.cc`) | inflight budget (`objecter_inflight_ops`), tid, choosing the session |
| 2 | `Objecter::_calc_target` | name hash, pg, CRUSH and upmap, acting and primary; detecting the need to resend after a map change |
| 3 | `Objecter::_send_op` | builds MOSDOp with the map epoch; sends through `ProtocolV2::send_message` |
| 4 | `OSD::ms_fast_dispatch` (`osd/OSD.cc`) | converts to an OpRequest; rejects ops with an older epoch; `enqueue_op` |
| 5 | `OSD::ShardedOpWQ::_process` → `OSD::dequeue_op` | takes it from the shard's scheduler; PG lock |
| 6 | `PrimaryLogPG::do_request` → `do_op` → `do_op_impl` | checks peering/active, caps, object existence, blocklist, degraded state |
| 7 | `PrimaryLogPG::execute_ctx` → `prepare_transaction` → `do_osd_ops` | executes each OSDOp (write, omap, cls class call) and builds the Transaction and the pg log entry |
| 8 | `PrimaryLogPG::issue_repop` → `ReplicatedBackend::submit_transaction` → `issue_op` | sends MOSDRepOp to the replicas and the local queue_transactions |
| 9 | `ReplicatedBackend::do_repop` (on the replica) | applies the same transaction and replies commit |
| 10 | `PrimaryLogPG::eval_repop` | when all have committed: the MOSDOpReply |

For EC, step 8 becomes `ECBackend::submit_transaction` and the read-modify-write pipeline in `ECCommon::RMWPipeline::start_rmw`. On this path, for a partial write the existing shards are read first, parity is computed, and then all shards are written.

```text
pseudocode: do_op on the primary (this book's summary of PrimaryLogPG.cc)
  do_op(op):
     if pg not active or op.epoch > osdmap: wait / requeue
     if client blocklisted or cap denies: reply -EPERM/-EBLOCKLISTED
     obc = get_object_context(oid)            # may wait for recovery of this object
     if object degraded/missing: wait_for_degraded_object
     ctx = OpContext(op, obc) ; execute_ctx(ctx)
  execute_ctx(ctx):
     r = prepare_transaction(ctx)             # do_osd_ops: each OSDOp → Transaction operations
     if read-only: reply now
     ctx.log += pg_log_entry_t(version = ++last_update, reqid, prior_version)
     repop = new RepGather(ctx) ; issue_repop(repop, ctx)
```

# Inside BlueStore: a TransContext {#sec-22-8}

![The life cycle of a TransContext in BlueStore. queue_transactions builds a TransContext for each transaction, and _txc_add_transaction executes each operation; writes go from _write to _do_write. Depending on alignment and size, either _do_write_small or _do_write_big is chosen, and _do_alloc_write gets space from the Allocator and applies checksums and compression. The data is either written directly with aio (AIO_WAIT then IO_DONE), or, if smaller than prefer_deferred_size (64K on HDD, and zero, meaning never, on SSD), stored in the WAL together with the metadata. Then kv_sync_thread commits several transactions in one RocksDB batch with one fsync, and on_commit is called. On the deferred path, the actual write to the device happens later in the background](figures/ch22/f05_txc.png){#fig-22-f05_txc}

| State (BlueStore_components.h) | Meaning |
|---|---|
| STATE_PREPARE | building and allocation |
| STATE_AIO_WAIT / STATE_IO_DONE | waiting for the direct data aio to finish |
| STATE_KV_QUEUED / STATE_KV_SUBMITTED / STATE_KV_DONE | queued, submitted and durable in RocksDB |
| STATE_DEFERRED_QUEUED / STATE_DEFERRED_CLEANUP / STATE_DEFERRED_DONE | executing deferred writes |
| STATE_FINISHING / STATE_DONE | release |

::: {.deep}
Why deferred helps on HDD: a random 4K write on an HDD needs a full seek. With deferred, the data is written to the RocksDB WAL (which is usually on NVMe) and acked immediately, and the actual write is done later in batches. On SSD, this double write only adds write amplification, which is why the SSD default is zero.
:::

# The RBD write path {#sec-22-9}

![The RBD write path in librbd/io. The request enters from api::Io into the ImageDispatcher, which runs layers such as QoS, exclusive lock, journal and cache in order. AbstractImageWriteRequest::send_request splits the image range into RADOS objects with Striper. Each object passes through ObjectDispatcher::send_dispatch and ObjectDispatch::write, and AbstractObjectWriteRequest in turn updates the object map, writes the object, and runs copyup if the object does not exist in a clone (chapter 3)](figures/ch22/f06_rbd.png){#fig-22-f06_rbd}

# The PUT path in RGW {#sec-22-10}

![The PUT path in RGW. The beast-based frontend hands the HTTP request to process_request, and after authentication rgw_process_authenticated runs verify_permission, pre_exec and execute for the op in order. RGWPutObj::execute hands the data through the Writer in the rgw::sal abstraction layer to the AtomicObjectProcessor in the rados driver, which writes the head and the tail stripes with RadosWriter::process. Finally _do_write_meta writes the metadata and updates the bucket index with UpdateIndex::prepare and complete (cls_rgw methods, chapter 4)](figures/ch22/f07_rgw.png){#fig-22-f07_rgw}

::: {.note}
The `rgw::sal` layer (Storage Abstraction Layer, in `rgw_sal.h`) has separated RGW from RADOS in recent versions, so that other drivers such as posix, dbstore or d4n can sit under the same frontend and ops.
:::

# The open and write path in CephFS {#sec-22-11}

![The CephFS path. In the first row, open is a metadata request: Client::_open sends an MClientRequest, the MDS in Server::handle_client_open takes the needed locks with Locker::acquire_locks and issues suitable caps with the reply. In the second row, write is the data path: Client::_write with get_caps needs at least Fw and prefers Fb. If it has Fb, the data is buffered in the ObjectCacher; otherwise it is written synchronously. The data goes directly to the OSDs with Striper and Objecter, and the MDS is not on the data path](figures/ch22/f08_cephfs.png){#fig-22-f08_cephfs}

| Layer | Function (file) |
|---|---|
| Client | `Client::_open`, `Client::_write`, `Client::get_caps`, `Client::handle_caps` (`client/Client.cc`) |
| MDS | `Server::handle_client_open`, `Server::handle_client_openc` (`mds/Server.cc`) |
| Locks and caps | `Locker::acquire_locks`, `Locker::handle_client_caps` (`mds/Locker.cc`) |

# The write path with real OpTracker timings {#sec-22-12}

The function-by-function path of the previous section can be timed with the OSD's own tool. Each `OpRequest` records timestamped points in OpTracker. Some are fixed flags: `mark_queued_for_pg`, `mark_reached_pg`, `mark_started` and `mark_commit_sent` in src/osd/OpRequest.h. Some are text events: `"op_commit"`, `"sub_op_commit_rec"` and `"waiting for subops from …"` in src/osd/ReplicatedBackend.cc.

On a three-OSD BlueStore test cluster with Ceph 18.2.7, we set `osd_op_history_size` to 1000. Then we wrote 300 4 KiB objects one after another into pool `p22` with size = 2 and read `ceph daemon osd.N dump_historic_ops` from all three OSDs.

::: {.algo #alg-22-1 title="Extracting each stage's time from dump_historic_ops" src="TrackedOp::mark_event and OpRequest::mark_flag_point (src/common/TrackedOp.cc, src/osd/OpRequest.h); ReplicatedBackend::submit_transaction and do_repop_reply" complexity="O(number of ops × number of events)"}
:::

```text
pseudocode
for each op in ops (all three OSDs):
    if description starts with "osd_op(" and pool = 4 ← primary ; if "osd_repop(" ← replica
    ev = [(event, time)] in recorded order
    for each consecutive pair (a, b): stage["a → b"].append(t_b − t_a)
median and 90th percentile of each stage ; count the order of op_commit and sub_op_commit_rec
```

**Result (median / 90th percentile, microseconds).** The whole write on the primary took about 1637 microseconds. Most of this time was spent waiting for commits. In 268 of the 300 ops, the local commit (`op_commit`) arrived before the replica's confirmation. The interval from `waiting for subops` to `op_commit` had a median of 1006 and a 90th percentile of 1407 microseconds. After that, it took another 356 microseconds until `sub_op_commit_rec`. In the remaining 32 ops the order was reversed.

The path before the PG is cheap. Its largest share was the sharded op queue: `queued_for_pg` to `reached_pg` with a median of 54 and a 90th percentile of 233. After that comes `reached_pg` to `started` at 86 microseconds, which is the time for the PG lock and preparing the op context.

On the replica, the `started` to `commit_sent` part (the BlueStore transaction and kv sync), with a median of 809 microseconds, is the main part. When the two paths are put on one axis, the replica finishes its work about 1170 microseconds after the start. But the primary sees the confirmation at about 1600 microseconds. This gap of several hundred microseconds is the cost of the return messenger path and the reply being queued, and it grows on a real network.

Practical lesson: when analysing a slow op (chapter 17), first see which two events have the largest gap. A large gap before `reached_pg` means the queue or the PG lock. A large gap between `waiting for subops` and `sub_op_commit_rec` means the replica or the network. A large gap up to `op_commit` means the local device or BlueStore.

![Median (dark blue) and 90th percentile (light blue) of the time between consecutive OpTracker events for 300 4 KiB writes on a Ceph 18.2.7 test cluster, on a symlog axis. Left: osd_op on the primary, dominant order only. Right: osd_repop on the replica](figures/ch22/f09_optracker.png){#fig-22-f09_optracker}

![Median timeline of a four-kilobyte replicated write. The top is the op on the primary, and the bottom is the op on the replica, shifted to the moment the subop was sent on the primary. The replica finishes its work about 1170 microseconds after the start, but the primary sees its confirmation at about 1600 microseconds. The difference is the cost of the return path in the messenger and queue](figures/ch22/f10_opgantt.png){#fig-22-f10_opgantt}

# Supplementary and up to date {#sec-22-13}

- **crimson** is still maturing in Tentacle and Umbrella. The classic OSD (`src/osd/`) and crimson (`src/crimson/osd/`) have separate op path code but share encoding, OSDMap and CRUSH. Before operational use, check the release notes of that version.
- The cls class method registration API on main has changed to a typed form (`ClassRegistrar`) (chapter 15). Build out-of-tree class code against the target version's tag.
- `neorados` (in `src/neorados/`) is a modern, asynchronous asio-based C++ interface, and RGW and librbd are gradually adopting it.

# Hands-on exercise {#sec-22-14}

1. Bring up a vstart cluster with `MON=1 OSD=3 MDS=0`, enable `debug_osd=20` on one of the OSDs and run a `rados put`. Find the ten functions of the "full path of a write" table in the log and note their order.
2. Decode the map with `ceph osd getmap -o om` and `ceph-dencoder type OSDMap import om decode dump_json | jq '.epoch, .pools[0]'`.
3. Compile the `demo_info_t` structure in a small unit test. Encode data with version 2 and decode it with a decoder that only knows the size field.
4. On a stopped OSD, find the last pg log entry with `ceph-objectstore-tool --op log` and compare the `version`, `prior_version` and `reqid` fields with the table in chapter 1.
5. During a `rados bench` test, run `thread apply all bt` on an OSD with `gdb -p` and identify the `tp_osd_tp`, `msgr-worker` and `bstore_kv_sync` threads.

## Capstone project for the Special Part: follow one write through the code {#sec-22-14-1}

**Goal.** Connect one real write, as Ceph recorded it, to the functions in the source that handled it, so that the "full path of a write" in this chapter becomes something you have seen rather than read.

**Requirements.**

1. A vstart cluster built from a Ceph commit that you record (the hash, not a branch name).
2. One write, either `rados put` or a write to an RBD image, with `debug_osd` raised on the primary OSD for that write only.
3. The OpTracker record of that operation (`dump_historic_ops`) and the matching part of the OSD log.
4. A diagram or table of the path from the client to the BlueStore commit, built from what you collected.

**Acceptance criteria.**

- Every event in the OpTracker record is tied to a function, with its file and line at the recorded commit.
- The order of the functions in your table matches the order in the log.
- You can point to the longest gap between two events and explain which part of the path it covers.
- Someone else can repeat the exercise from your notes and get the same table.

**Hints.** This chapter's sections on the write path and on OpTracker timings; librados (chapter 14); BlueStore and its transaction (chapter 12); for the messenger part of the path, chapter 26.

# Review questions {#sec-22-15}

1. Why does the OSD not write directly to disk, and why does it use ObjectStore::Transaction?
2. What inputs does `_calc_target` in Objecter have, and when is an op resent?
3. Why does each PG's op always go to one OSDShard?
4. What is the role of `ms_fast_dispatch`, and what must not be done in it?
5. How does `ENCODE_START(v, compat, bl)` make rolling upgrades possible?
6. What is the difference between the direct and deferred paths in BlueStore, and why is the SSD default zero?
7. When does the primary reply to the client in replication?
8. In RGW, which function moves an index entry from pending to complete?
9. In CephFS, why is the MDS not on the data path, and what is the effect of not having the Fb cap?
10. Where do you look to find the real default of an option in a specific version?

# Sources for this chapter {#sec-22-16}

- The Ceph repository: https://github.com/ceph/ceph
- Developer guide: https://docs.ceph.com/en/latest/dev/developer_guide/
- Running vstart: https://docs.ceph.com/en/latest/dev/dev_cluster_deployment/
- OSD internals documentation: https://docs.ceph.com/en/latest/dev/osd_internals/
- encoding: https://docs.ceph.com/en/latest/dev/encoding/
- BlueStore: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- crimson: https://docs.ceph.com/en/latest/dev/crimson/
- Weil et al., "Ceph: A Scalable, High-Performance Distributed File System", OSDI 2006: https://www.usenix.org/legacy/event/osdi06/tech/full_papers/weil/weil.pdf
