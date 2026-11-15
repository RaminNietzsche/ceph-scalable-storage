---
chapter: 38
id: ch38
title: 'Specialist Part (5): RBD — The librbd I/O Path, Layering and Copyup, Exclusive Lock, Caches and QoS'
part: specialist
lang: en
---

::: {.tldr}

- librbd sends each request through layered ImageDispatcher and ObjectDispatcher chains (QoS, cache, journal and others).
- Clones read through to the parent within the overlap; the first write copies the parent's data up (copyup), and flatten copies everything.
- exclusive-lock is cooperative and keeps the object map, journal and cache consistent with one writer at a time.
- The default cache is writearound; QoS uses token buckets per limit; krbd, librbd and rbd-nbd differ in feature support.

:::

# Before we begin {#sec-38-1}

librbd is a heavy library: each request passes through several **dispatch** layers at the image level and then at the object level, and features such as exclusive-lock, journaling, caching, encryption and QoS are each a layer. This chapter shows those layers in their real order, then opens three widely used mechanisms in detail: copyup in clones and flatten, acquiring and breaking the exclusive-lock with blocklisting, and the default writearound cache. Finally it compares krbd, librbd and rbd-nbd in terms of features and performance. Names and defaults have been checked against the main branch of the ceph/ceph repository (November 2026).

## What questions does this chapter answer? {#sec-38-1-1}

- Which layers does an `rbd_aio_write` pass through?
- How is a write to an object of a clone that does not exist yet carried out?
- How does deep-flatten differ from ordinary flatten?
- How do two clients that open an image at the same time pass the lock back and forth?
- When does librbd blocklist another client?
- What does the default librbd cache do, and what does it not do?
- How does QoS in librbd work, and what are its limits?

## Prerequisites {#sec-38-1-2}

Chapter 2 (RBD), chapter 29 (krbd), chapter 36 (SnapContext and clones in RADOS), chapter 37 (the header and the object map).

# The dispatch layers {#sec-38-2}

`ImageDispatcher` and `ObjectDispatcher` are two chains of layers. Each layer can take the request and finish it, modify it and pass it to the next layer, or hold it until a condition is cleared. The order, from `librbd/io/Types.h`:

| Order | Image layer | Role |
|---|---|---|
| 1 | `QUEUE` | the input queue and hand-off to the thread pool (`rbd_op_threads`) |
| 2 | `QOS` | IOPS and bandwidth limits (token bucket) |
| 3 | `EXCLUSIVE_LOCK` | holding writes until the lock is acquired |
| 4 | `REFRESH` | refreshing the ImageCtx if the header has changed |
| 5 | `MIGRATION` | redirecting to the source image during live migration |
| 6 | `JOURNAL` | recording the event in the journal before the write (chapter 39) |
| 7 | `WRITE_BLOCK` | temporarily stopping writes during operations such as a snapshot |
| 8 | `WRITEBACK_CACHE` | the PWL persistent cache, if enabled |
| 9 | `CORE` | turning image extents into object extents with the Striper (chapter 37) |

| Order | Object layer | Role |
|---|---|---|
| 1 | `CACHE` | writearound or ObjectCacher (writeback and writethrough) |
| 2 | `CRYPTO` | LUKS encryption at the block level |
| 3 | `JOURNAL` | delaying the object write until the journal event commits |
| 4 | `PARENT_CACHE` | a read-only cache of the parent through ceph-immutable-object-cache |
| 5 | `SCHEDULER` | merging small back-to-back writes (`rbd_io_scheduler`) |
| 6 | `CORE` | building the `ObjectRequest` and sending the op to RADOS |

::: {.algo #alg-38-1 title="A write passing through the dispatch chain" src="src/librbd/io/ImageDispatcher.cc; src/librbd/io/ObjectDispatcher.cc; src/librbd/io/ImageRequest.cc :: ImageWriteRequest; src/librbd/io/ObjectRequest.cc :: ObjectWriteRequest" complexity="O(L) layers per request, plus O(k) objects after striping"}
:::

```text
pseudocode
ImageDispatcher.send(write(extents, data)):
    for layer in [QUEUE, QOS, EXCLUSIVE_LOCK, REFRESH, MIGRATION, JOURNAL, WRITE_BLOCK, WRITEBACK_CACHE, CORE]:
        result = layer.write(...)          # true = layer took it
        if result == CONTINUE: next layer
        if result == COMPLETE: done
        if layer is holding it: it resumes later from the next layer
CORE: Striper.file_to_extents → for each object extent:
    ObjectDispatcher.send(write(objectno, off, data, snapc = image snapc))
        CACHE → CRYPTO → JOURNAL → PARENT_CACHE → SCHEDULER → CORE
CORE: ObjectWriteRequest:
    if object_map says may not exist and has parent overlap → copyup (algorithm 38-2)
    else object_map_update(EXISTS) if needed → RADOS write op with snapc
```

![The dispatch layers in librbd. An image request passes through nine image layers and is split into object extents by the Striper in CORE; each extent then passes through six object layers until it reaches RADOS as an op. Inactive layers (for example journal or crypto) are not in the chain](figures/ch38/f01_dispatch.png){#fig-38-f01_dispatch}

# Layering: clone, copyup and flatten {#sec-38-3}

A clone is an image whose header has a `parent` key (the parent's pool, namespace, image and snap, and the **overlap**). The overlap is the part of the address space that can still be read from the parent; if the clone shrinks, the overlap shrinks too and never grows again.

- **Read:** if the object does not exist in the clone (ENOENT or object map NONEXISTENT) and the extent is within the overlap, that extent is read from the parent. With `rbd_clone_copy_on_read` the same data is immediately written into the clone too.
- **Write:** a partial write to an object that is not yet in the clone must first bring the rest of the object from the parent, otherwise the unread parts would be zeros. This is **copyup**.

::: {.algo #alg-38-2 title="copyup: filling a clone object from the parent before the first write" src="src/librbd/io/ObjectRequest.cc :: AbstractObjectWriteRequest::compute_parent_info, send_write, handle_write_object; src/librbd/io/CopyupRequest.cc; src/cls/rbd/cls_rbd.cc :: copyup" complexity="one read from the parent (up to the object size) and one compound op on the clone object"}
:::

```text
pseudocode
write to child object o:
    copyup_enabled = has_parent and extent of o within overlap
    if object map says o does not exist and copyup_enabled: goto copyup     # an optimization
    send write with assert_exists guard
    on -ENOENT and copyup_enabled: goto copyup
copyup (one CopyupRequest per object; later writes append to it):
    read parent extents of o (sparse read)
    if snapshots exist on child (deep_copyup): first send copyup alone with EMPTY snapc
        # so that the RADOS clones for the child's snapshots also see the parent's data
    op = cls rbd.copyup(data) or rbd.sparse_copyup(extent_map, data)
    append all pending writes of this object to the same op (if not deep_copyup)
    update object maps (head, and snapshots if deep-flatten) → EXISTS
    send op with child snapc
cls rbd.copyup on OSD: if object exists → return 0 ; else write data at offset 0
```

A subtle point in the cls: if two clients copy up at the same time, the second sees that the object exists and does **not** write the parent's data, but its own write (which is in the same op) is applied. Because copyup and the write are in one atomic op, nobody ever sees a half-filled object.

![Copyup for the first write to object 1280 of a clone. librbd learns from the object map that the object does not exist, fetches the parent object with a sparse read, moves the object map to EXISTS, and sends the copyup and the user's write to the clone object in one atomic op](figures/ch38/f02_copyup.png){#fig-38-f02_copyup}

**flatten** fills all objects within the overlap with a copyup carrying no user data (`FlattenRequest` sends an empty write for each object, which triggers copyup) and then removes the parent link (`child_detach` in the parent's header and removal of the `parent` key). **deep-flatten** means copyup also reaches the clone's snapshots; without it, the clone's snapshots still depend on the parent and the parent cannot be deleted.

**Numerical example.** A clone of a 20 GiB operating-system image with 5120 objects. The VM writes 4 KiB at offset 5 GiB + 8 KiB. Object 1280 does not exist in the clone. librbd reads object 1280 of the parent (assumption: completely full, 4 MiB) and sends the compound op `[rbd.copyup(4 MiB), write(8 KiB, 4 KiB)]`. So the first 4 KiB write to each clone object is really a 4 MiB read and a 4 MiB write. That is why freshly cloned VMs are slower in their first minutes and `rbd du` on the clone climbs quickly.

# exclusive-lock {#sec-38-4}

exclusive-lock guarantees that only one client writes to the image at any moment, so that the object map, journal and cache stay consistent. This lock is **cooperative**: if another client wants to write, it asks the owner to release the lock.

The lock is a `cls_lock` lock named `rbd_lock`, of exclusive type, with the tag `internal` and the cookie `auto <watch handle>`, on the header object. The cookie contains the handle of that same watch, so others can use `list_watchers` to find out whether the lock owner is still alive.

::: {.algo #alg-38-3 title="Acquiring exclusive-lock and breaking a dead owner's lock" src="src/librbd/ManagedLock.cc; src/librbd/managed_lock/AcquireRequest.cc, BreakRequest.cc, Utils.cc :: encode_lock_cookie; src/librbd/ExclusiveLock.cc" complexity="a few RADOS round trips; in the worst case plus one OSDMap update for the blocklist"}
:::

```text
pseudocode
acquire():
    get_locker(header)                          # cls_lock get_info
    try lock(header, "rbd_lock", EXCLUSIVE, cookie = "auto " + watch_handle, tag = "internal")
    if ok: post_acquire (open object map, journal, ...) ; done
    if EBUSY:
        if locker has a live watch on header (same address and cookie handle):
            notify RequestLock to owner ; wait (owner releases if it allows)
            retry acquire later
        else:                                   # the owner is dead or detached
            if rbd_blocklist_on_break_lock:     # default true
                mon: osd blocklist add <locker addr> expire = rbd_blocklist_expire_seconds (0 → the mon default)
                wait until our OSDMap epoch >= blocklist epoch
            break_lock(locker) ; retry lock
```

**Why blocklist?** An owner that seems "dead" may only be cut off from the network and still have writes in flight. If the lock is broken without a blocklist, those writes later land on the new owner's data. A blocklist in the OSDMap guarantees that all OSDs reject ops from that address. This is the fencing mechanism of the cluster.

![Acquiring exclusive-lock. If the lock is held, client B checks whether the owner still has a live watch. If it is alive, B sends a release request with notify; otherwise it first blocklists the owner and then breaks the lock](figures/ch38/f03_lock.png){#fig-38-f03_lock}

```bash
# example: viewing an image's lock and watchers
rbd lock ls rbd/vm01
rbd status rbd/vm01
ceph osd blocklist ls
```

```text
example (output):
There is 1 exclusive lock on this image.
Locker         ID                     Address
client.24183   auto 94823571521536    10.20.0.31:0/2846217731

Watchers:
	watcher=10.20.0.31:0/2846217731 client.24183 cookie=94823571521536

10.20.0.44:0/1739920384 2026-11-15T10:41:07.512038+0330
listed 1 entries
```

The lock cookie (`auto 94823571521536`) equals the watcher cookie, so the owner is alive. The blocklist line shows that another client (address …44) was fenced earlier.

::: {.warn}
If two VMs open one image with exclusive-lock, they see no error: the lock keeps passing between them and both write (with very bad performance). exclusive-lock does not prevent **concurrent access**. To really prevent it, open the image with `rbd device map -o exclusive` (krbd) or the `RBD_LOCK_MODE_EXCLUSIVE` option in `rbd_lock_acquire`, so the lock is not released at others' request.
:::

# Caches {#sec-38-5}

## writearound (default) {#sec-38-5-1}

In the main branch `rbd_cache = true` and `rbd_cache_policy = writearound`. This cache **does not keep data**; it only acknowledges the write before it reaches the OSD, so that latency is lower from the application's point of view.

::: {.algo #alg-38-4 title="The writearound layer" src="src/librbd/cache/WriteAroundObjectDispatch.cc :: dispatch_io, block_overlapping_io, flush" complexity="O(log n) for checking overlap among in-flight extents"}
:::

```text
pseudocode
write(object, extent):
    if max_dirty == 0 or FUA flag: pass through (writethrough)
    if extent overlaps an in-flight write on same object: block until it completes
    elif in_flight_bytes + len <= rbd_cache_max_dirty:
        complete to caller NOW ; send to RADOS in background
    else: queue until in-flight bytes drop
flush(): wait for all in-flight writes ; then complete
read: not cached → straight to RADOS
rbd_cache_writethrough_until_flush: until the guest sends its first flush, behave as writethrough
```

`rbd_cache_writethrough_until_flush = true` protects old operating systems that do not send flushes: until the first flush is seen, all writes are synchronous.

## writeback and writethrough (ObjectCacher) {#sec-38-5-2}

With `rbd_cache_policy = writeback`, the CACHE layer is the old ObjectCacher: it keeps read and written data up to `rbd_cache_size` (default 32 MiB) and accumulates dirty data up to `rbd_cache_max_dirty` (24 MiB). This cache is **volatile** and becomes durable only with a guest flush.

## The persistent cache (PWL) {#sec-38-5-3}

`rbd_persistent_cache_mode` (default `disabled`) with the value `ssd` or `rwl` builds a persistent log on a local SSD or PMEM. A write is acknowledged after it is recorded in the local log and goes to RADOS later. The `dirty-cache` bit in features shows that the image has unwritten data on one host; opening it on another host is not allowed until the cache is flushed. This cache greatly reduces write latency, but turns the host into a data **point of failure**.

# QoS {#sec-38-6}

The QOS layer has a `TokenBucketThrottle` for each kind of limit (`iops`, `bps`, `read_iops`, `write_iops`, `read_bps`, `write_bps`). A timer adds tokens every `rbd_qos_schedule_tick_min` milliseconds (default 50).

::: {.algo #alg-38-5 title="The token bucket in librbd QoS" src="src/common/Throttle.cc :: TokenBucketThrottle::add_tokens, get; src/librbd/io/QosImageDispatch.cc" complexity="O(b) for b waiting requests per tick"}
:::

```text
pseudocode
every tick (>= rbd_qos_schedule_tick_min ms):
    bucket.put(avg * tick / 1000, burst_ratio = max(burst, avg) / avg)   # bucket cap = burst × burst_seconds
    while blockers not empty:
        b = front ; got = bucket.get(b.tokens)
        if got == b.tokens: release b
        else: b.tokens -= got ; break
request(tokens = 1 for iops, bytes for bps):
    if bucket has tokens: proceed ; else enqueue as blocker
```

**Numerical example.** `rbd_qos_iops_limit = 500` with burst off. Every 50 ms tick adds 25 tokens. A VM sends 4K requests with a queue depth of 32; 25 requests are released per tick and the rest wait, so the average latency seen by the VM is about 32/500 = 64 ms. QoS in librbd is separate **for each image and each client**. Two clients that open one image each get 500 IOPS, and there is no global coordination. For a cluster-level cap you need mClock in the OSD (chapter 21).

# krbd, librbd and rbd-nbd {#sec-38-7}

| | krbd | librbd (QEMU) | rbd-nbd |
|---|---|---|---|
| Runs in | the kernel | the QEMU process | the rbd-nbd process + the kernel nbd |
| journaling and journal-mode mirroring | no | yes | yes |
| object-map and fast-diff | from kernel 5.3 | yes | yes |
| librbd cache and PWL | no (the kernel page cache) | yes | yes |
| QoS in librbd | no | yes | yes |
| librbd LUKS encryption | no (separate dm-crypt) | yes | yes |
| Extra data copies | fewest | few | more (kernel ↔ user space) |
| Upgrades | with the kernel | with the Ceph package | with the Ceph package |

Feature support in krbd depends on the kernel version (custom striping from 4.17, deep-flatten from 5.1, object-map and fast-diff from 5.3, according to the rbd(8) documentation). If the image has a feature unknown to the kernel, `rbd device map` fails with "image uses unsupported features", and you must turn that feature off or use rbd-nbd.

# Tuning and troubleshooting {#sec-38-8}

- **Severe slowness with two clients:** look at `rbd status`; if it has two watchers and the lock keeps moving (request lock messages in the librbd log), one of the clients should not have the image open.
- **A VM becomes "read-only" after a host failover:** the previous host was blocklisted and its writes are rejected. This behavior is correct; after it comes back, stop the old QEMU process, and run `ceph osd blocklist rm` only after you are sure it has stopped.
- **A slow new clone:** this is the cost of copyup. Run `rbd flatten` at a quiet time, or turn on the parent cache (`rbd_parent_cache_enabled` with ceph-immutable-object-cache) for reads.
- **`rbd_op_threads`:** the default is 1. For a process with many images or very high IOPS, raising it to 2 or 4 can help, but it does not guarantee the order of callbacks.
- **Request timeout:** `rbd_request_timed_out_seconds` (30) applies only to notify messages between clients, not to I/O.

# Supplementary and up to date {#sec-38-9}

- In older versions the default `rbd_cache_policy` was writeback. When upgrading old clusters, check for explicit settings in the `ceph.conf` of the QEMU hosts.
- The `SCHEDULER` layer (`rbd_io_scheduler = simple`) merges small back-to-back writes to one object. Its effect is positive on small sequential loads and negligible on random loads.
- `rbd_read_from_replica_policy` with the value `balance` or `localize` also sends reads to the replicas; this is safe only on clusters with a recent `require_osd_release` and for images that have no concurrent writes.

# Hands-on exercise {#sec-38-10}

1. Send a 4K write with `debug_rbd=20` and note, in order, the names of the layers that appear in the log.
2. Create a clone, write 4 KiB to one of its empty objects and look at the clone object's size with `rados stat`. Then compare `rbd du` before and after.
3. Open the image in two `rbd bench` processes at the same time and compare each one's IOPS with the single-process case.
4. Set `rbd config image set rbd/vm01 rbd_qos_iops_limit 500` and measure the latency with `rbd bench --io-threads 32`. Compare with the calculation in the chapter's example.

# Review questions {#sec-38-11}

1. Which layers does the EXCLUSIVE_LOCK layer run before, and why?
2. When is copyup done without sending the first write?
3. Why does the cls `copyup` method do nothing if the object exists?
4. What does deep-flatten add?
5. What structure does the cookie of the `rbd_lock` lock have, and what is it used for?
6. Why is breaking the lock without a blocklist dangerous?
7. When does writearound not acknowledge a write immediately?
8. What does `rbd_cache_writethrough_until_flush` protect against?
9. With `rbd_qos_iops_limit = 1000` and a 50 ms tick, how many tokens are added per tick?
10. Name two reasons to use rbd-nbd instead of krbd.

# Sources for this chapter {#sec-38-12}

- librbd/io (Types.h, ImageDispatcher, ObjectRequest, CopyupRequest): https://github.com/ceph/ceph/tree/main/src/librbd/io
- librbd/managed_lock and ExclusiveLock.cc: https://github.com/ceph/ceph/tree/main/src/librbd/managed_lock
- WriteAroundObjectDispatch.cc: https://github.com/ceph/ceph/blob/main/src/librbd/cache/WriteAroundObjectDispatch.cc
- Throttle.cc (TokenBucketThrottle): https://github.com/ceph/ceph/blob/main/src/common/Throttle.cc
- RBD options: https://docs.ceph.com/en/latest/rbd/rbd-config-ref/
- Persistent cache: https://docs.ceph.com/en/latest/rbd/rbd-persistent-write-log-cache/
- Exclusive lock documentation: https://docs.ceph.com/en/latest/rbd/rbd-exclusive-locks/
- rbd(8) and krbd features: https://docs.ceph.com/en/latest/man/8/rbd/
