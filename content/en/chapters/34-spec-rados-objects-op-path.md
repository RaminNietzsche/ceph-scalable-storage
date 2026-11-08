---
chapter: 34
id: ch34
title: 'Specialist Part (1): RADOS — Object Identity, Metadata and the Op Path Inside the OSD'
part: specialist
lang: en
---

# Before we start {#sec-34-1}

Chapter 8 showed how an object reaches an OSD through CRUSH, and chapter 22 followed the path of a write from librados to the ack at a glance. This chapter opens up that same path inside the OSD in detail: exactly what key a RADOS object is identified and sorted by, where its metadata (object_info_t and SnapSet) lives, which shard the op is queued in, which gates it passes through before it runs, how versions are numbered and what the pg log looks like on disk. All names have been checked against the main branch of the ceph/ceph repository (November 2026).

## What questions does this chapter answer? {#sec-34-1-1}

- What fields identify a RADOS object, and why does its sort order reverse the bits of the hash?
- What fields do `object_info_t` and `SnapSet` have, and in which xattr are they stored?
- In which shard and thread does a client op run?
- What does `do_op` check, in order, and in which wait queue does it put the op?
- How is a duplicate request (for example after a reconnection) detected?
- How do `version` and `user_version` differ, and how are they incremented?
- In which object, and with what keys, are the pg log and pg info stored?

## Prerequisites {#sec-34-1-2}

Chapter 8 (CRUSH and PGs), chapter 14 (librados and MOSDOp), chapter 22 (code architecture) and chapter 24 (BlueStore keys). Familiarity with reading C++ helps but is not required.

# The identity of a RADOS object {#sec-34-2}

## From name to hobject_t {#sec-34-2-1}

The client knows an object by its name, but the OSD works with `hobject_t` (`src/common/hobject.h`). The main fields:

| Field | Meaning |
|---|---|
| `oid` | the object name the client gave |
| `key` | the locator key; if it is not empty, the hash is computed from this key instead of the name |
| `nspace` | the namespace within the pool; objects with the same name in two namespaces are two separate objects |
| `pool` | the pool id |
| `hash` | the hash of the name (or key) with the pool's default hash function, that is rjenkins |
| `snap` | the snapshot number; for the current version it is the special value `CEPH_NOSNAP` (head) |
| `max` | the "largest possible object" flag, used as an end sentinel in traversals |

`ghobject_t` is a layer on top of it and adds `shard_id` (for EC) and `generation`. It is this ghobject_t that became the `O` key in RocksDB in chapter 24.

::: {.note}
`key` (the locator) is rarely used but important: objects with the same key get the same hash and always stay in one PG. A program that wants several related objects always to be co-located (for example so that one class call can see both on the same OSD) can give them all the same key; the price is an uneven distribution of data.
:::

## Sort order: the reversed hash {#sec-34-2-2}

Object traversals (listing, scrub, backfill) all rely on `hobject_t` order. The function `cmp(const hobject_t&, const hobject_t&)` in `hobject.cc` compares in this order: `max`, then `pool`, then the **bitwise key** (`get_bitwise_key`, that is the hash with its bits reversed), then `nspace`, then the effective key, then `oid` and finally `snap`.

::: {.algo #alg-34-1 title="Comparing two hobject_t values and the bitwise key" src="src/common/hobject.cc :: cmp(const hobject_t&, const hobject_t&); src/common/hobject.h :: hobject_t::_reverse_bits, get_bitwise_key_u32" complexity="O(1) for the numeric fields and O(L) for comparing strings"}
:::

```text
pseudocode
cmp(l, r):
    compare l.max, r.max
    compare l.pool, r.pool
    compare reverse_bits(l.hash), reverse_bits(r.hash)     # hash_reverse_bits is precomputed
    compare l.nspace, r.nspace
    if l.key or r.key: compare effective_key(l), effective_key(r)
    compare l.oid, r.oid
    compare l.snap, r.snap                                  # head (NOSNAP) is the largest snap
```

**Why reversed?** The PG number comes from the **low bits** of the hash (`ceph_stable_mod`). If the hash is reversed, those same low bits move to the top of the number, and all the objects of a PG fall in one **contiguous range** of the bitwise key. So each PG is a range, and traversing it is a range scan in RocksDB.

**Numerical example.** Consider an object with hash `0x8c7e1b1f` in a pool with pg_num=32. The PG number is `0x8c7e1b1f & 31 = 0x1f`. Its bitwise key is `0xf8d87e31`. All the objects of PG `0x1f` have the low five bits `11111`, so their bitwise key starts with `11111` and lies in the range `[0xf8000000, 0xffffffff]`. If pg_num becomes 64, this PG splits into `0x1f` and `0x3f`. The sixth bit of the hash is the sixth bit from the top in the bitwise key, so the two new PGs are two **contiguous halves** of the same range: `[0xf8000000, 0xfbffffff]` and `[0xfc000000, 0xffffffff]`. That is why a split only moves the range boundary and does not need any keys to be rewritten.

![The bitwise key and the PG ranges. The low five bits of the hash determine the PG number at pg_num=32. After reversing the bits, those five bits move to the top of the key, and each PG becomes a contiguous range in hobject_t order. When pg_num doubles, each range is split exactly in half](figures/ch34/f02_bitwise.png){#fig-34-f02_bitwise}

# Per-object metadata {#sec-34-3}

## Three places to store: data, xattrs and omap {#sec-34-3-1}

Each RADOS object has three parts: **data** (contiguous bytes), **xattrs** (small key-value pairs) and **omap** (a sorted key-to-value map that can have millions of keys). In BlueStore the xattrs are stored inside the onode itself, and the omap in separate RocksDB keys with the prefixes `M`, `m`, `p` and `P` (chapter 24). The OSD keeps two special xattrs for itself:

| xattr | Constant in the code | Content |
|---|---|---|
| `_` | `OI_ATTR` | the encoded `object_info_t` |
| `snapset` | `SS_ATTR` | the `SnapSet`, only on the head (chapter 36) |
| `_<name>` | — | a user xattr; when storing, the OSD prepends `_` to the name so that it does not clash with the internal xattrs |

## object_info_t {#sec-34-3-2}

The important fields of `object_info_t` in `src/osd/osd_types.h`:

| Field | Meaning |
|---|---|
| `soid` | the same hobject_t |
| `version`, `prior_version` | the version of the last change and the one before it (of type `eversion_t`, that is epoch and number) |
| `user_version` | the version the client sees (`rados stat` and `ver` in librados) |
| `last_reqid` | the id of the last modifying request |
| `size`, `mtime`, `local_mtime` | size, modification time as the client sees it, and the OSD's local time |
| `flags` | flags, including `whiteout`, `dirty`, `omap`, `data_digest`, `omap_digest`, `manifest` |
| `data_digest`, `omap_digest` | crc32c of the data and the omap, if valid (for scrub) |
| `watchers` | the list of active watches (chapter 14) |
| `truncate_seq`, `truncate_size` | for truncate ordering in CephFS |
| `manifest` | for redirect or chunked (dedup) objects |

```bash
# example: reading an object's object_info_t and decoding it
rados -p rbd getxattr rbd_header.5f3a2b8c1d4e _ > /tmp/oi.bin
ceph-dencoder type object_info_t import /tmp/oi.bin decode dump_json
```

```text
example (abbreviated output):
{
    "oid": { "oid": "rbd_header.5f3a2b8c1d4e", "key": "", "snapid": -2,
             "hash": 2356083487, "max": 0, "pool": 3, "namespace": "" },
    "version": "1462'93",
    "prior_version": "1462'92",
    "last_reqid": "client.24183.0:118",
    "user_version": 93,
    "size": 0,
    "flags": [ "dirty", "omap", "data_digest" ],
    "data_digest": "0xffffffff",
    "watchers": { "client.24183": { "cookie": 94823571521536 } }
}
```

`snapid: -2` is `CEPH_NOSNAP`, that is head. The version `1462'93` means epoch 1462 and number 93 in the pg log.

# Op queueing: shard and thread {#sec-34-4}

`OSD::ms_fast_dispatch` takes the `MOSDOp` message directly from the messenger thread, builds an `OpRequest` and with `enqueue_op` puts it into the sharded queue `op_shardedwq`. Each shard is an `OSDShard` with a lock, a scheduler (mClock by default, chapter 21) and several threads.

::: {.algo #alg-34-2 title="Choosing the shard for an op" src="src/osd/OSD.cc :: OSD::enqueue_op, OSD::ShardedOpWQ::_enqueue; src/osd/osd_types.h :: spg_t::hash_to_shard" complexity="O(1); the real cost is in that shard's mClock scheduler"}
:::

```text
pseudocode
num_shards = osd_op_num_shards  or  (rotational ? osd_op_num_shards_hdd : osd_op_num_shards_ssd)
threads    = osd_op_num_threads_per_shard or (rotational ? _hdd : _ssd)
shard_index = pgid.ps() % num_shards                 # spg_t::hash_to_shard
shards[shard_index].scheduler.enqueue(OpSchedulerItem(pg, op, cost, priority, owner))
worker thread t of that shard: dequeue → lock PG → PG::do_request → PrimaryLogPG::do_op
```

| Option | main default | Description |
|---|---|---|
| `osd_op_num_shards_ssd` | 8 | number of shards on SSD/NVMe |
| `osd_op_num_threads_per_shard_ssd` | 2 | threads per shard on SSD |
| `osd_op_num_shards_hdd` | 1 | one shard on HDD |
| `osd_op_num_threads_per_shard_hdd` | 5 | with five threads |

**Numerical example.** On an OSD with NVMe we have 8 shards and two threads in each shard, that is 16 op threads. PGs 3.0 to 3.1f with ps=0..31 go to shards 0 to 7 in turn, and each shard gets four PGs of this pool. Because each PG is always in one shard, the order of a PG's ops is preserved. But if one PG is very hot (for example a frequently used `rbd_header` object or an RGW index shard), it keeps only the two threads of that shard busy, and adding shards does not help.

# The gates of do_op {#sec-34-5}

Before an op runs, `PrimaryLogPG::do_op` and `do_op_impl` pass it through several gates. If a condition does not hold, the op sits in one of the PG's wait queues and is requeued once the condition is cleared. `op->mark_delayed("...")` shows that text in `dump_ops_in_flight`.

::: {.algo #alg-34-3 title="The op admission gates on the primary" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::do_request, do_op_impl" complexity="O(1) per gate, except find_object_context, which may need to read the onode from disk"}
:::

```text
pseudocode (the order matters)
do_request: if not peered → waiting_for_peered ; if flushes pending → waiting_for_flush
            if not active (and the op needs it) → waiting_for_active
do_op_impl(op):
    check_laggy(op)                       # lease/readable_until; otherwise wait
    op_has_sufficient_caps(op)            # cephx caps; otherwise EPERM
    write_ordered = op.rwordered()
    if write_ordered and failsafe full → reply ENOSPC (or drop)
    if is_unreadable_object(head)       → wait_for_unreadable_object   # missing on the primary
    if write_ordered:
        if is_degraded_or_backfilling_object(head) → wait_for_degraded_object
        if scrub write_blocked(head)               → waiting_for_scrub
    if write_ordered and check_in_progress_op(reqid) → duplicate: the earlier reply or waiting_for_ondisk
    if maybe_await_blocked_head(oid)     → wait_for_blocked_object   # for example promote or flush
    find_object_context(oid)            → if the snap version is missing: wait_for_unreadable_object
    get_rw_locks(ctx)                    # RWState: read, write, excl
    execute_ctx(ctx)
```

| Text in dump_ops_in_flight | Queue | Practical meaning |
|---|---|---|
| `waiting for peered` / `waiting for active` | `waiting_for_peered` / `waiting_for_active` | the PG has not finished peering yet (chapter 35) |
| `waiting for missing object` | `waiting_for_unreadable_object` | the object is missing on the primary and must be recovered first |
| `waiting for degraded object` | `waiting_for_degraded_object` | a write to an object that one of the replicas lacks; recovery first |
| `waiting for scrub` | `waiting_for_scrub` | the chunk being scrubbed includes this object |
| `waiting for ondisk` | `waiting_for_ondisk` | the request is a duplicate and the original has not committed yet |
| `waiting for rw locks` | `ObjectContext::rwstate.waiters` | another op holds an incompatible lock on the same object |

::: {.debug}
When a client "hangs", take `ceph daemon osd.N dump_ops_in_flight` on the primary of that PG and read the `flag_point` field and the `events`. If most ops are `waiting for degraded object`, the problem is not I/O; recovery is slow or has stopped (chapter 32). If it is `waiting for rw locks`, usually a long op (for example a heavy class call) is sitting on the same object.
:::

![The op path inside the OSD from the messenger to commit. ms_fast_dispatch hands the message to the shard without a global lock; the shard's thread takes the PG lock and do_op checks the gates. If a condition does not hold, the op stays in the corresponding wait queue. Otherwise execute_ctx builds the transaction, issue_repop sends it to the replicas, and the reply is sent after all members of acting have committed](figures/ch34/f01_oppath.png){#fig-34-f01_oppath}

## Object locks: RWState {#sec-34-5-1}

Each `ObjectContext` (the PG's in-memory cache of an object's metadata) has an `RWState` with the states `none`, `read`, `write` and `excl` and a counter. Several readers or several writers can hold the lock at once (writers because the pg log itself guarantees their order), but read and write are incompatible with each other and `excl` is incompatible with everything. Ops that both read and write depending on the result (such as a class call with `CLASS_WRITE`) take a write lock. A waiting op stays in `waiters` and is requeued when the lock is released.

## Duplicate requests {#sec-34-5-2}

If the client does not receive the reply to a write (for example the connection drops or the primary changes), it resends the same op with the same `reqid` (consisting of entity, incarnation and tid). The OSD must not execute it twice, because operations such as append or incrementing a counter are not idempotent.

::: {.algo #alg-34-4 title="Detecting duplicate requests with the pg log and dups" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::check_in_progress_op; src/osd/PGLog.h :: IndexedLog::get_request" complexity="O(1) with hash tables on the reqids (caller_ops, extra_caller_ops and dup_index)"}
:::

```text
pseudocode
check_in_progress_op(reqid):
    if reqid in pg_log.caller_ops or extra_caller_ops:   # the current log entries
        found (version, user_version, return_code)
    elif reqid in pg_log.dup_index:                       # trimmed entries of which only a dup remains
        found (version, user_version, return_code)
    else: return not found
if found:
    if already_complete(version): reply with saved user_version and return_code
    else: waiting_for_ondisk[version] += op           # reply after the original version commits
```

dups are lightweight entries (`pg_log_dup_t`: reqid, version, user_version, return_code) kept after the main log entries are trimmed. Their number is limited by `osd_pg_log_dups_tracked`, and in chapter 33 we saw how these dups grow the pglog memory.

# Executing the op and numbering versions {#sec-34-6}

`execute_ctx` builds an empty `PGTransaction` and calls `prepare_transaction`. This function first runs `do_osd_ops`, which turns each op inside the message (for example `CEPH_OSD_OP_WRITE`, `SETXATTR`, `OMAPSETVALS` or `CALL`) into operations on the transaction. Then come the pool-full check, `make_writeable` (for snapshots, chapter 36) and finally `finish_ctx`.

::: {.algo #alg-34-5 title="Setting version and user_version and building the log entry" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::execute_ctx, prepare_transaction, finish_ctx" complexity="O(1) per modified object; encoding object_info_t and SnapSet in proportion to their size"}
:::

```text
pseudocode
execute_ctx: ctx.at_version = get_next_version()   # (current epoch, info.last_update.version + 1)
finish_ctx(ctx, log_op_type):
    ctx.user_at_version = max(info.last_user_version, new_oi.user_version) + 1
    if ctx.at_version.version > ctx.user_at_version: ctx.user_at_version = at_version.version
    new_oi.version = at_version ; new_oi.prior_version = old_oi.version
    new_oi.user_version = user_at_version ; new_oi.last_reqid = reqid ; mtime ...
    attrs["_"] = encode(new_oi) ; if head: attrs["snapset"] = encode(new_snapset)
    op_t.setattrs(soid, attrs)
    log_entries.push(pg_log_entry_t(type, soid, at_version, prior_version,
                                    user_at_version, reqid, mtime, return_code))
```

**Numerical example.** PG 3.1f is at epoch 1462 with `last_update = 1462'92` and `last_user_version = 93`. A write to object A (whose `user_version` is 40) arrives. at_version becomes `1462'93`. user_at_version is max(93, 40) + 1 = 94, and since 93 is not greater than 94 it stays 94. So after the write, A has `version = 1462'93` and `user_version = 94`. Note: user_version is monotonic at the **PG** level, not at the object level; so an object can jump from 40 to 94 between two of its own changes. A program that builds a compare-and-swap pattern with `assert_version` (chapter 14) relies only on it being unique and increasing, not on it being contiguous.

## Replication and commit {#sec-34-6-1}

`issue_repop` builds a `RepGather` and calls `pgbackend->submit_transaction`. In `ReplicatedBackend` the transaction is sent to each replica in an `MOSDRepOp` and at the same time handed to the ObjectStore on the primary. Each replica returns an `MOSDRepOpReply` with the ONDISK flag after its local commit. When all members of acting (not just min_size) have committed, `all_committed` becomes true, the `on_committed` callbacks run and the reply is sent to the client. In EC, the EC backend plays the same role, with chunks and separate transactions for each shard (chapter 27).

![The sequence of a three-copy replicated write. The primary commits the transaction locally and at the same time sends it to the two replicas. Each member replies ONDISK after committing to the BlueStore WAL. The reply to the client is sent only after all replies have arrived; min_size only determines with how many members the PG accepts writes at all](figures/ch34/f03_repop.png){#fig-34-f03_repop}

# The pg log and pg info on disk {#sec-34-7}

Each PG has a special object called **pgmeta** (`spg_t::make_pgmeta_oid`) that has no data; everything is in its omap. The log entries, dups and info are stored as omap keys of this object and, in BlueStore, go under the `P` prefix (the pgmeta-specific omap).

| omap key in pgmeta | Content |
|---|---|
| `_infover`, `_epoch` | format version and epoch |
| `_info` | the full `pg_info_t` (old form) |
| `_biginfo` | past_intervals and purged_snaps, which change rarely |
| `_fastinfo` | `pg_fast_info_t`: only last_update and a few statistics; for back-to-back writes |
| `0000001462.00000000000000000093` | one `pg_log_entry_t` |
| `dup_0000001200.00000000000000000003` | one `pg_log_dup_t` |

::: {.algo #alg-34-6 title="The key names of log and dup entries" src="src/osd/osd_types.cc :: eversion_t::get_key_name, pg_log_dup_t::get_key_name; src/osd/osd_types.h :: infover_key, fastinfo_key" complexity="O(1); a fixed 31-byte (or 35-byte) key"}
:::

```text
pseudocode
eversion_t::get_key_name():   sprintf("%010u.%020llu", epoch, version)       # 31 characters
pg_log_dup_t::get_key_name(): "dup_" + eversion.get_key_name()               # 35 characters
# info keys start with "_" so that read_log_and_missing can skip them
```

Because epoch and version are written with leading zeros and a fixed length, the **string** order of the keys is the **numeric** order of the versions, and reading the log is a simple ordered scan of the omap. Trimming the log is deleting a contiguous range from the start of these same keys.

![The key layout of a pg log entry in the omap of the pgmeta object, byte by byte. Ten digits of epoch with leading zeros, a dot and twenty digits of version. The dup key has the same format with the four-byte prefix dup_ (the note below the figure). The fixed length makes string order the same as numeric order](figures/ch34/f04_logkey.png){#fig-34-f04_logkey}

`_fastinfo` is an optimization: in most writes only `last_update`, `last_complete` and a few statistics change. The function `prepare_info_keymap` (in `osd_types.cc`) writes only this small key, without touching the full `_info`, if it can fit the change into `pg_fast_info_t` (the `osd_pg_fastinfo` and `osd_pg_biginfo` counters in perf dump show how often each case happens).

# Commands and tools {#sec-34-8}

## Reference of this chapter's commands {#sec-34-8-1}

| Command | Use |
|---|---|
| `ceph osd map <pool> <obj> [<nspace>]` | computing an object's PG and up/acting without accessing it |
| `rados -p <pool> stat <obj>` | size and mtime (from object_info_t) |
| `rados -p <pool> listxattr <obj>` / `getxattr <obj> <name>` | user xattrs (without the internal `_` prefix) |
| `rados -p <pool> listomapkeys <obj>` / `listomapvals` | omap keys and values |
| `ceph-dencoder type object_info_t import <file> decode dump_json` | decoding the `_` xattr |
| `ceph pg <pgid> query` | info, peer_info and peering state |
| `ceph pg <pgid> list_unfound` | unfound objects |
| `ceph daemon osd.N dump_ops_in_flight` / `dump_historic_ops` / `dump_blocked_ops` | current, slow and blocked ops |
| `ceph daemon osd.N dump_op_pq_state` | the state of the shard queues |
| `ceph-objectstore-tool --data-path <path> --pgid <pgid> --op log` | a PG's pg log and missing set on a stopped OSD |
| `ceph-objectstore-tool --data-path <path> --op list <obj>` | the list of ghobject_t values of an object (head and clones) |

```bash
# example: one object from start to finish
ceph osd map rbd rbd_header.5f3a2b8c1d4e
rados -p rbd stat rbd_header.5f3a2b8c1d4e
ceph daemon osd.12 dump_ops_in_flight | jq '.ops[] | {description, age, flag_point}'
```

```text
example (output):
osdmap e1462 pool 'rbd' (3) object 'rbd_header.5f3a2b8c1d4e' -> pg 3.8c7e1b1f (3.1f) -> up ([12,4,27], p12) acting ([12,4,27], p12)
rbd/rbd_header.5f3a2b8c1d4e mtime 2026-11-15T09:41:07.000000+0330, size 0
{ "description": "osd_op(client.24183.0:131 3.1f 3:f8d87e31:::rbd_header.5f3a2b8c1d4e:head [watch ping cookie 94823571521536] snapc 0=[] ondisk+write+known_if_redirected e1462)",
  "age": 0.0021, "flag_point": "waiting for sub ops" }
```

In the op description, the string `3:f8d87e31:::rbd_header...:head` is the hobject_t: pool 3, the **bitwise key** `f8d87e31` (not the raw hash), then the empty namespace and key, the name and the snap.

## Tuning and troubleshooting {#sec-34-8-2}

- **A hot PG:** if `dump_historic_ops` shows that most slow ops are on one PG, adding shards or threads does not help. Find the hot object (for example an `rbd_header` with many watches or an RGW index shard) and spread it out (more shards for the index, a larger pg_num for the pool).
- **Slow ops in `waiting for sub ops`:** one of the replicas is slow. Find the cause with `ceph osd perf` and `dump_historic_ops` on that replica.
- **Growth of `osd_pglog` in the mempool:** check the log length (`osd_min_pg_log_entries`, `osd_max_pg_log_entries`) and the dups (chapter 33).
- **`osd_op_num_shards`:** on NVMe with many cores, adding shards only helps when many PGs are active at the same time. Before changing it, look at the distribution of PGs over shards with `dump_op_pq_state`. Changing it requires restarting the OSD.

# Supplementary and up to date {#sec-34-9}

- In Crimson (chapter 30) the op path runs on Seastar without a thread pool, but the same gates (peered, active, missing, degraded) are reimplemented in `crimson/osd/pg.cc` and `ops_executer.cc`.
- In the main branch, the flags `CEPH_OSD_RMW_FLAG_EC_DIRECT_READ` and `EC_SYNC_READ` exist for the optimized EC path (chapter 27); check your version before relying on them.
- The default shard values for HDD in recent versions are one shard with five threads, so that mClock ordering is more precise. Older versions had a different value; check on your own version with `ceph config help osd_op_num_shards_hdd`.

# Hands-on exercise {#sec-34-10}

1. Run `ceph osd map` for three objects of your choice and compute the bitwise key from the hash by hand. Then confirm it with `dump_ops_in_flight` or the log (`debug_osd=20`).
2. Read an object's `_` xattr with `ceph-objectstore-tool ... get-attr _` (on a stopped test OSD) or with `rados getxattr`, and decode it with `ceph-dencoder`. After a write, compare the change in `version` and `user_version`.
3. Look at a few log entries of a PG with `ceph-objectstore-tool --op log` and match their keys against the `%010u.%020llu` format.
4. On a test pool, set `noout` and stop one OSD, write to a few objects, bring the OSD back, and during recovery find an example of `waiting for degraded object` in `dump_ops_in_flight`.

# Review questions {#sec-34-11}

1. In what order is hobject_t compared?
2. Why does the bitwise key reverse the hash?
3. After pg_num doubles, how is the bitwise-key range of PG `0x1f` split?
4. What do the `_` and `snapset` xattrs hold?
5. How is the shard of an op chosen, and what are the defaults on SSD?
6. If the object is missing on the primary, in which queue does the op wait?
7. How is a duplicate request detected, and what role do dups play?
8. How is user_version computed, and why may it not be contiguous for one object?
9. When is the reply to a replicated write sent to the client?
10. What format does the key of a pg log entry have, and why is its length fixed?

# Sources for this chapter {#sec-34-12}

- hobject.h and hobject.cc: https://github.com/ceph/ceph/blob/main/src/common/hobject.h
- osd_types.h (object_info_t, pg_log_entry_t, pgmeta keys): https://github.com/ceph/ceph/blob/main/src/osd/osd_types.h
- PrimaryLogPG.cc (do_op, execute_ctx, finish_ctx): https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- OSD.cc (enqueue_op and the sharded queue): https://github.com/ceph/ceph/blob/main/src/osd/OSD.cc
- Developer documentation on op execution: https://docs.ceph.com/en/latest/dev/osd_internals/
- OSD options: https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/
