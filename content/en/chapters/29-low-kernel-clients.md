---
chapter: 29
id: ch29
title: 'Lower Layers (7): Linux Kernel Clients — libceph, krbd and ceph.ko'
part: lower
lang: en
---

::: {.tldr}

- The Linux kernel clients are libceph (messenger, MON and OSD client), krbd for block devices and ceph.ko for CephFS.
- `ceph_osdc` builds requests, computes the target OSD from the maps and resends after map changes.
- The shared striper maps a device or file offset to an object and an offset within it.
- krbd uses a watch and the exclusive lock on `rbd_header`; ceph.ko exposes client-side latency and file statistics in debugfs.

:::

# Introduction: Ceph inside the kernel {#sec-29-1}

All the clients of the previous chapters, that is librados, librbd, ceph-fuse and RGW, run in user space and use Ceph's shared C++ code (Objecter and AsyncMessenger). The Linux kernel, however, has a **completely independent** implementation in C: the `libceph` module (the `net/ceph/` directory), which implements the messenger, the mon and OSD clients, CRUSH and cephx. Its two consumers are `rbd.ko` (the file `drivers/block/rbd.c`) and `ceph.ko` (the `fs/ceph/` directory). This chapter examines all three. The source is the master branch of the torvalds/linux repository, and the kernel code is GPL-2.0. In this chapter we give only the names of functions and constants and explain the logic in our own words.

::: {.summary}

- `libceph` contains these parts: `messenger.c` together with `messenger_v1.c` and `messenger_v2.c`, `osd_client.c`, `mon_client.c`, `osdmap.c`, `crush/` (the same mapper.c and hash.c as Ceph), `auth_x.c` (cephx) and `striper.c`.
- krbd turns each blk-mq request into an `rbd_img_request` and then into several `rbd_obj_request`s (one per 4M object). Each one is a `ceph_osd_request` with ops such as WRITE, WRITEFULL, ZERO or DELETE.
- The features krbd supports include layering, striping v2, exclusive-lock, object-map, fast-diff, deep-flatten, data-pool and operations. journaling is not supported.
- Since kernel 5.11, msgr2.1 is supported through the `ms_mode` option. secure mode uses `gcm(aes)` from the kernel crypto API.
- ceph.ko keeps its cache coherent with the MDS caps. The caps determine what may be cached, buffered, or read and written directly.

:::

# libceph: structure {#sec-29-2}

| File | Role | User-space equivalent |
|---|---|---|
| `ceph_common.c` | `ceph_client`, option parsing (`mon_addr`, `name`, `secret`, `ms_mode`) | `CephContext` + `librados::Rados` |
| `messenger.c` / `_v1.c` / `_v2.c` | `ceph_connection`, state machine, banner and frames | `AsyncConnection` + `ProtocolV1/V2` |
| `mon_client.c` | map subscriptions, hunting among mons with backoff, authentication | `MonClient` |
| `osd_client.c` | `ceph_osd_request`, `calc_target`, `send_request`, linger (watch/notify), timeout | `Objecter` |
| `osdmap.c` + `crush/` | decoding the OSDMap and running CRUSH in the kernel | `OSDMap` + `CrushWrapper` |
| `auth_x.c` | cephx (ticket, authorizer) | `auth/cephx` |
| `striper.c` | mapping a file or image extent to objects | `Striper` |

::: {.note}
`net/ceph/crush/mapper.c` and `hash.c` in the kernel are essentially the same files as `src/crush/` in Ceph. The `#ifdef __KERNEL__` conditions at the top of `hash.c` in Ceph (chapter 28) exist for this sharing. The result is that the kernel client computes exactly the same PG→OSD as librados. But support for the tunables and new CRUSH features depends on the kernel version. If the cluster requires a feature the kernel does not know, the mount or map fails with a feature-mismatch error, and the message `missing required protocol features` appears in `dmesg`.
:::

## osd_client: the path of a request {#sec-29-2-1}

1. **Construction:** `ceph_osdc_alloc_request` and the `osd_req_op_*_init` functions (for example extent, cls or watch) build the ops. The data is attached without copying as `ceph_osd_data` (a bio list, a bvec or pages).
2. **Targeting:** `calc_target` uses the current OSDMap to map the object to a PG and then to the primary (with upmap and pg_temp). If the map changes, in-flight requests are re-targeted and resent.
3. **Sending:** `send_request` makes some checks: if the `PAUSEWR` flag is in the map, or the pool is full (`pool_full`) and the request is a write without `CEPH_OSD_FLAG_FULL_TRY`, the request is held until the next map arrives. Then the `MOSDOp` message is queued on the `ceph_connection` of that OSD.
4. **Reply:** `handle_reply` finds the result by tid and calls the callback (for example `rbd_osd_req_callback`).
5. **linger:** RBD watches (for the header and the exclusive lock) are kept as `ceph_osd_linger_request` and re-registered after every map change or reconnection.

::: {.warn}
The kernel client's default behaviour towards a full pool or a paused cluster is to **wait indefinitely**, not to fail. A program writing to `/dev/rbd0` or to kernel CephFS gets stuck in state D (uninterruptible). The `osd_request_timeout` option (in `rbd map -o` or mount) bounds this, but the consequence is an I/O error for the filesystem above. Measure its effect before setting it.
:::

# krbd: from blk-mq to the object {#sec-29-3}

![The path of a write in krbd. The program writes to /dev/rbd0 or to a filesystem on it. The block layer passes requests to rbd_queue_rq through the blk-mq tag_set (with depth queue_depth, default BLKDEV_DEFAULT_RQ). rbd.c turns each request into an img_request and splits it into obj_requests according to the object size. Each obj_request is a ceph_osd_request that osd_client sends to the primary OSD using in-kernel CRUSH](figures/ch29/f01_krbd.png){#fig-29-f01_krbd}

The queue limits that `rbd.c` sets come directly from the image structure: `io_opt` equals the size of one object set (object_size × stripe_count), `io_min` equals `alloc_size` (default 64K, `RBD_ALLOC_SIZE_DEFAULT`), and `discard_granularity` also equals `alloc_size`. Filesystems such as XFS read these values in `mkfs` to set their alignment.

| I/O type in blk-mq | op on the OSD (in `__rbd_osd_setup_write_ops` and similar) |
|---|---|
| read | `CEPH_OSD_OP_READ` (or sparse-read) |
| a write that covers the whole object | `CEPH_OSD_OP_WRITEFULL` |
| a partial write | `CEPH_OSD_OP_WRITE` (after `SETALLOCHINT` with the object size) |
| discard or write-zeroes at the end of the object | `CEPH_OSD_OP_TRUNCATE` |
| discard or write-zeroes in the middle | `CEPH_OSD_OP_ZERO` |
| discard of a whole object (no parent) | `CEPH_OSD_OP_DELETE` |

![The state machines in rbd.c. If exclusive-lock is enabled, the img_request first acquires the lock, then runs all obj_requests and waits. Each object write first updates the object-map if it is enabled, then writes to the OSD. In a clone, if the object does not exist yet, copyup sends the parent's data along with the write, and at the end the object-map is finalized. A read that meets -ENOENT in a clone goes to the parent](figures/ch29/f02_objsm.png){#fig-29-f02_objsm}

# krbd in practice {#sec-29-4}

```bash
rbd map rbd/img1 -o ms_mode=prefer-crc,queue_depth=256,alloc_size=65536
rbd showmapped
cat /sys/block/rbd0/queue/{optimal_io_size,minimum_io_size,discard_granularity,nr_requests}
cat /sys/bus/rbd/devices/0/{pool,name,image_id,features,current_snap}
# libceph in-flight requests (debugfs):
mount -t debugfs none /sys/kernel/debug 2>/dev/null
cat /sys/kernel/debug/ceph/*/osdc       # tid, osd, pg, object, op
cat /sys/kernel/debug/ceph/*/monc       # maps and the current mon
cat /sys/kernel/debug/ceph/*/client_options
```

::: {.tip}
The `osdc` output is the most important tool for diagnosing a "stuck" kernel client. If a tid stays on one OSD for a long time, follow the story further on that OSD with `ceph daemon osd.N dump_ops_in_flight` (chapter 22). If all requests are on `osd-1` (no target), the client has no valid map. In that case check `monc` and the connection to the mons.
:::

| `rbd map -o` option | Default (per the master code) | Note |
|---|---|---|
| `queue_depth` | `BLKDEV_DEFAULT_RQ` | blk-mq queue depth |
| `alloc_size` | 65536 | io_min and discard_granularity |
| `lock_timeout` | 0 (no timeout) | wait for the exclusive lock |
| `read_only` / `ro` | false | — |
| `ms_mode` | legacy (msgr1) | `crc`, `secure`, `prefer-crc` or `prefer-secure` since 5.11 |
| `exclusive` | off | do not release the lock (for fencing) |
| `notrim` | off | ignore discard (for thick provisioning) |

::: {.note}
Check the default of `ms_mode` in the kernel documentation (`Documentation/filesystems/ceph.rst` for CephFS and the rbd man page for krbd). In the master code of `net/ceph/ceph_common.c`, the initial value of `con_modes` is `CEPH_CON_MODE_UNKNOWN`, which means msgr1 (legacy) is used. So if the mons listen only on v2, you must set `ms_mode` explicitly.
:::

# ceph.ko and caps {#sec-29-5}

![Caps coordination in kernel CephFS. Client A opens a file for writing and, because it is the only writer, gets full caps, including Fc (read cache) and Fb (write buffer). So the writes stay in the page cache. When client B opens the same file, the MDS asks A to give back Fc and Fb. A writes its dirty pages directly to the OSDs and reports the size and mtime to the MDS. Then B gets only Fr and performs every read directly and synchronously from the OSD](figures/ch29/f03_caps.png){#fig-29-f03_caps}

Caps are a bitmask shifted by "subsystem". The generic bits (`include/linux/ceph/ceph_fs.h` and its equivalent in Ceph) are:

| Bit | Name | Meaning for the File subsystem |
|---|---|---|
| 1 | `GSHARED` (s) | read attributes |
| 2 | `GEXCL` (x) | exclusive read and modify |
| 4 | `GCACHE` (c) | cache reads (page cache valid) |
| 8 | `GRD` (r) | read |
| 16 | `GWR` (w) | write |
| 32 | `GBUFFER` (b) | buffer writes (writeback) |
| 64 | `GWREXTEND` (a) | extend EOF |
| 128 | `GLAZYIO` (l) | lazy I/O |

The shifts are `SAUTH=2` (A: owner and mode), `SLINK=4` (L: link count), `SXATTR=6` (X: xattrs) and `SFILE=8` (F: data and size). That is why a string like `pAsLsXsFrwcb` in `ceph tell mds.0 session ls` or debugfs means: pin, Auth shared, Link shared, Xattr shared and File read/write/cache/buffer.

```text
pseudocode: writing in ceph.ko (this book's summary of the logic of fs/ceph/file.c and caps.c)
  ceph_write_iter:
      need = Fw (+ Fb if buffered), want = Fb
      ceph_get_caps(need, want)        # if missing → request to the MDS and wait
      if have Fb:  generic_perform_write → page cache (writeback later)
      else:        ceph_sync_write → osd_client directly (no cache)
      ceph_put_cap_refs
  MDS revoke(Fb):
      writeback all dirty pages → OSD
      ceph_check_caps → cap ack with size and mtime
```

::: {.warn}
If a kernel client does not answer a revoke (for example because the OSDs are slow or the client itself is stuck), the MDS raises a health warning with the code `MDS_HEALTH_CLIENT_LATE_RELEASE` and the message "Client … failing to respond to capability release" (in `mds/Beacon.cc`), and the other clients wait. After `mds_session_blocklist_on_timeout` and the session timeouts, the MDS evicts and blocklists the client. The kernel client then gets I/O errors until a remount, unless `recover_session=clean` is set.
:::

# Kernel versus user space {#sec-29-6}

![Comparing kernel and user-space clients. krbd and ceph.ko are built on libceph, which is an independent implementation in C whose features are limited by the kernel version. librbd and ceph-fuse are built on librados, Objecter and AsyncMessenger, have all the features (journaling, mirroring, QoS, cache) and are upgraded without a reboot](figures/ch29/f04_cmp.png){#fig-29-f04_cmp}

| Aspect | krbd / ceph.ko | librbd (qemu, rbd-nbd) / ceph-fuse |
|---|---|---|
| Performance | lowest overhead; no extra context switch | one more layer (nbd or fuse), but librbd in qemu is very efficient |
| Features | limited to `RBD_FEATURES_SUPPORTED`; no journaling | all features |
| Upgrade | needs a new kernel and a reboot or module reload | a package upgrade |
| Failure | panic or hang in the kernel, processes stuck in state D | only the user process |
| Cache | the kernel page cache (and caps in CephFS) | the librbd cache and `client_oc` in ceph-fuse |

# A lower layer: from file offset to OSD in the kernel {#sec-29-7}

## Mapping an offset to an object (striper) {#sec-29-7-1}

Both kernel clients, krbd and ceph.ko, use a shared function in `net/ceph/striper.c` to turn "an offset in the device or file" into "an object and an offset inside the object": `ceph_calc_file_object_mapping` and its multi-extent version `ceph_file_to_extents`. The input is a layout of three numbers: stripe_unit (su), stripe_count (sc) and object_size (os).

![Striping computation in the kernel. The offset is converted to a block number (su), a stripe number and an object set. In the example, a 3MiB read from offset 10.5MiB with a 1MiB/4/4MiB layout breaks into four pieces in four different objects. The bottom of the figure shows the object-name format in RBD v2, RBD v1 and CephFS](figures/ch29/f05_striping.png){#fig-29-f05_striping}

```text
pseudocode: mapping one offset (this book's rewrite)
  stripes_per_object = os / su
  blockno,  blockoff  = divmod(off, su)
  stripeno, stripepos = divmod(blockno, sc)
  objset,   setpos    = divmod(stripeno, stripes_per_object)
  objno  = objset * sc + stripepos
  objoff = setpos * su + blockoff
  len_in_this_object = min(len, su - blockoff)
```

| Piece | Logical offset | blockno | stripeno / pos | Object | Offset in object | Length |
|---|---|---|---|---|---|---|
| 1 | 10.5 MiB | 10 | 2 / 2 | 2 | 2.5 MiB | 0.5 MiB |
| 2 | 11 MiB | 11 | 2 / 3 | 3 | 2 MiB | 1 MiB |
| 3 | 12 MiB | 12 | 3 / 0 | 0 | 3 MiB | 1 MiB |
| 4 | 13 MiB | 13 | 3 / 1 | 1 | 3 MiB | 0.5 MiB |

We computed this table with an independent implementation of the same formula. For the default RBD layout (su=os=4MiB, sc=1) the formula simplifies to objno = off / 4MiB. For example, offset 10MiB goes to object 2 at offset 2MiB. When su does not equal os (the STRIPINGV2 feature, which is in the kernel's `RBD_FEATURES_ALL`), krbd chooses the copying path `rbd_img_fill_request` instead of the zero-copy path (`rbd_img_fill_request_nocopy`), because the bios have to be cut across several objects. "Fancy" striping works in krbd, but it costs more CPU.

### Object names

| Client | Format | Example |
|---|---|---|
| RBD v2 | `RBD_V2_DATA_FORMAT` = `"%s.%016llx"` on object_prefix | `rbd_data.10ab2c3d4e5f.0000000000000002` |
| RBD v1 (obsolete) | `"%s.%012llx"` | `rb.0.1234.000000000002` |
| CephFS | `"%llx.%08llx"` (inode, object number) | `10000000000.00000002` |

The object name is the input to the next stage. As chapter 28 showed with the name `rbd_data.10ab2c3d4e5f.0000000000000000`, the hash of the name leads to the PG, and CRUSH leads to the OSD. The kernel reimplements this same chain with its own C code (a same-version copy of `crush/` and `ceph_hash.c`). If the result differed from the user-space side by even one bit, the kernel client would go to the wrong OSD. That is why CRUSH features (tunables, straw2, MSR) are usable only after the kernel supports them (chapter 22, `require-min-compat-client`).

## calc_target: choosing the OSD {#sec-29-7-2}

![Choosing the OSD in libceph. calc_target builds the raw seed from the hash of the object name, maps it to pg_num with ceph_stable_mod, builds pps with crush_hash32_2 and the pool id, and applies CRUSH and then upmap and primary_temp. With every new osdmap, scan_requests re-evaluates in-flight requests and resends them if the target changed. A request with no reachable OSD waits in homeless_osd](figures/ch29/f06_target.png){#fig-29-f06_target}

The steps in `net/ceph/osd_client.c` and `net/ceph/osdmap.c` are:

1. `__ceph_object_locator_to_pg`: first `ceph_str_hash(pool->object_hash, name)` (rjenkins) is applied to the object name (and the namespace, if there is one) and the raw seed is built.
2. `raw_pg_to_pg`: the PG number is obtained with `ceph_stable_mod(seed, pg_num, pg_num_mask)`. stable_mod ensures that when pg_num doubles only half of the objects move (chapter 28).
3. `raw_pg_to_pps`: if the HASHPSPOOL flag is on (the default for today's pools), `crush_hash32_2(stable_mod(seed, pgp_num), pool_id)` is computed so that the PGs of different pools do not overlap. In the old mode, the pool id was added to ps and PG 0.5 and 1.4 ended up co-located.
4. `do_crush`, followed by applying `pg_upmap`, `pg_upmap_items` and `primary_temp` in `ceph_pg_to_up_acting_osds`.
5. `link_request` attaches the request to the session of that OSD (`struct ceph_osd`). If the target OSD is down, the request is linked to `homeless_osd` and no message is sent until the next map arrives.

::: {.deep}
**Why do requests get "stuck"?** In `/sys/kernel/debug/ceph/<fsid>.client<id>/osdc`, the first column is the target OSD number. A request with no OSD number there (homeless), or one that has stayed on one OSD for a long time, means either the client has not received the new map (compare the `osdmap` file with the epoch in `ceph osd dump`) or the target PG is not active. In the second case the problem is on the cluster side and you should examine `ceph pg <pgid> query` (chapter 22), not the client.
:::

## watch and exclusive lock in krbd {#sec-29-7-3}

krbd registers a **linger request** (watch) on the `rbd_header.<id>` object. `rbd_watch_cb` receives the notifications: `HEADER_UPDATE` (a size or snapshot change) and the lock messages (`ACQUIRED_LOCK`, `RELEASED_LOCK`, `REQUEST_LOCK`). When exclusive-lock is enabled and another client (for example the librbd of a VM) holds the lock, krbd sends `REQUEST_LOCK` before its first write and waits for the lock to be released. The `exclusive` map option makes this behaviour strict, meaning the lock is acquired and not given back. Linger requests, like ordinary requests, are re-evaluated with every osdmap, and after a disconnection the watch is registered again (reconnect watch). If this fails, the image does not see size changes until the watch is back.

## CephFS numbers in debugfs {#sec-29-7-4}

ceph.ko has a `metrics/` directory in debugfs. The `latency` file gives read, write and metadata latency from the client's point of view, and the `file` file gives statistics on files being opened and closed. The same data is sent to the MDS in a metrics message and appears in `ceph fs top` (the mgr module named stats). The `caps`, `mdsc` and `mds_sessions` files show, respectively, the number of caps, the in-flight MDS requests and the state of the sessions.

```bash
D=/sys/kernel/debug/ceph/*.client*
cat $D/osdc              # in-flight OSD requests (tid, osd, pgid, oid)
cat $D/osdmap | head -3  # the map epoch as the kernel sees it
cat $D/metrics/latency   # ceph.ko only
cat $D/caps | head
rbd showmapped; cat /sys/bus/rbd/devices/0/features
```

::: {.warn}
debugfs shows internal information (object names, inode ids and so on) and is for root only. Do not copy its output into tickets without scrubbing sensitive names.
:::

# Kernel client algorithms at the code level {#sec-29-8}

The previous sections showed the path at the conceptual level. This section examines five key algorithms of `net/ceph`, `drivers/block/rbd.c` and `fs/ceph`, with the code of the Linux kernel mainline and numerical examples. We do not claim here which kernel version each behaviour arrived in. For your distribution's kernel, check the same functions in the source tree of that version.

## Turning a request into object extents {#sec-29-8-1}

::: {.algo #alg-29-1 title="Splitting and merging extents in the striper" src="net/ceph/striper.c :: ceph_file_to_extents, ceph_calc_file_object_mapping, lookup_last" complexity="O(L/su) steps for an L-byte request; lookup_last searches from the end of the sorted list, so it is O(1) for a sequential pattern"}
:::

```text
pseudocode
while len > 0:
    (objno, objoff, xlen) = calc_file_object_mapping(off, len)   # at most up to the end of su
    last = lookup_last(list, objno)                              # the last extent of the same object
    if last and last.off + last.len == objoff: last.len += xlen   # contiguous merge
    else: a new extent at the sorted position
    action_fn(ex, xlen)   # krbd: record this piece's bio_vec for the same extent
    off += xlen ; len −= xlen
final check: the list is sorted by (objno, off) and has no overlaps
```

**Numerical example.** A layout with stripe_unit = 64K, stripe_count = 4 and object_size = 4M. A 256K write at offset 1056K (that is 1 MiB + 32K) breaks into five pieces:

- 32K to object 0 at offset 288K;
- 64K to object 1, 64K to object 2 and 64K to object 3, each at offset 256K;
- the final 32K again to object 0, at offset 320K.

The fifth piece sits exactly after the first piece in object 0 (288K + 32K = 320K), so lookup_last merges it. The result is four OSD requests of 64K each, not five. With the default RBD layout (su = os = 4M, sc = 1), a 4M write at offset 3M gives two extents: object 0 [3M, +1M] and object 1 [0, +3M].

![Mapping a 256 KB write on a krbd device with custom striping. The top row shows the pieces of the request in the image space and the destination object of each. The bottom row shows the same pieces inside the four objects. The two pieces of object 0, which are 224K apart in the image space, fall next to each other inside the object, and ceph_file_to_extents turns them into one extent. So one obj_request with two bio_vecs is built](figures/ch29/f08_extents.png){#fig-29-f08_extents}

## Deciding to resend after a new map {#sec-29-8-2}

::: {.algo #alg-29-2 title="calc_target and the resend decision" src="net/ceph/osd_client.c :: calc_target, target_should_be_paused, ceph_osds_changed; net/ceph/osdmap.c :: ceph_pg_is_split" complexity="O(size of acting + CRUSH cost) per request for each new epoch"}
:::

```text
pseudocode
pi = pool(t.base_oloc) ; if not pi: return POOL_DNE
if t.last_force_resend < pi.last_force_request_resend: force_resend = true
pgid = object_locator_to_pg(t.target_oid) ; (up, acting) = pg_to_up_acting_osds(pgid)
should_pause = PAUSERD/PAUSEWR or a full pool/cluster (for writes)
unpaused = t.paused and not should_pause
legacy_change = pgid changed or osds_changed(t.acting, acting)
split = t.pg_num and pg_is_split(last_pgid, t.pg_num, pi.pg_num)
return (unpaused or legacy_change or force_resend or split) ? NEED_RESEND : NO_ACTION
```

**Numerical example.** A request is waiting in PG 3.1a (pg_num = 64, acting = [7, 2, 11]) and a new epoch arrives:

- **osd.11 died:** acting changes to [7, 2, 5]. ceph_osds_changed is true, so NEED_RESEND. But the primary is still osd.7, and the request is resent to the same session.
- **pg_num from 64 to 128:** the object may go to PG 3.5a. split holds, so the request is re-targeted and resent.
- **Only an unrelated OSD changed:** NO_ACTION, and the request is not touched.

If the `pausewr` flag is set on the cluster, write requests are paused. When the flag is removed, unpaused resends them all. This is the wave of sends seen in debugfs (the osdc file) after `ceph osd unpause`.

![The decision branches of calc_target in libceph. The top row reads the inputs from the new map: the existence of the pool, the force-resend counter and the new PG mapping. The middle row evaluates three kinds of change. The bottom row is the result: every meaningful change detaches the request from the previous session and attaches it to the new OSD's session. Unrelated changes cost nothing](figures/ch29/f09_calctarget.png){#fig-29-f09_calctarget}

## Detecting slowness and maintaining sessions {#sec-29-8-3}

::: {.algo #alg-29-3 title="handle_timeout and handle_osds_timeout" src="net/ceph/osd_client.c :: handle_timeout, handle_osds_timeout, send_linger_ping; include/linux/ceph/libceph.h (defaults)" complexity="O(number of requests and lingers) per five-second round; O(number of sessions in the LRU) per fifteen-second round"}
:::

```text
pseudocode
handle_timeout (every osd_keepalive_timeout = 5 s):
    cutoff = now − 5 s
    for each osd, each req: if req.r_stamp < cutoff: put the osd in slow_osds   # laggy
    for each linger (watch) committed: send_linger_ping
    if osd_request_timeout > 0: requests older than that ⇒ abort with ETIMEDOUT
    for osd in slow_osds: ceph_con_keepalive(osd.o_con)
handle_osds_timeout (every osd_idle_ttl/4 = 15 s):
    for osd in LRU: if now > osd.lru_ttl (= time it went idle + 60 s): close_osd
```

**Numerical example.** Request B was sent to osd.7 at t = 3 s and has not had a reply yet. In the round at t = 10 s, cutoff = 5 s and r_stamp = 3 is smaller. So osd.7 is counted as slow and a KEEPALIVE goes out on its connection. If the connection is really dead, the keepalive failure causes a fault and a reconnection, and the request is resent. With the default `osd_request_timeout = 0`, a request never returns with an error. That is why krbd on an unhealthy cluster gets "stuck" instead of returning an I/O error. The session of osd.3, whose last request finished at 2.2 s, has lru_ttl = 62.2 s and is closed in the first handle_osds_timeout round after that (at most about 15 seconds later).

![The handle_timeout timeline in osd_client. The blue dashed lines are the five-second rounds. Request A finished on time. Request B is counted as slow from the tenth second on, and a keepalive is sent to its OSD. The idle session of osd.3 is kept until lru_ttl passes and is then closed in the next handle_osds_timeout round](figures/ch29/f11_timeout.png){#fig-29-f11_timeout}

::: {.tip}
To make krbd return an error instead of getting stuck (for example on a test cluster, or when a higher layer has failover), pass the `osd_request_timeout=<seconds>` option in `rbd map -o`. Use it with care in production: an I/O error may push the filesystem above it into read-only mode.
:::

## Acquiring the exclusive lock in krbd {#sec-29-8-4}

::: {.algo #alg-29-4 title="Acquiring the exclusive lock and pushing aside a dead owner" src="drivers/block/rbd.c :: rbd_acquire_lock, rbd_try_acquire_lock, rbd_try_lock, find_watcher, rbd_request_lock" complexity="O(number of watchers) per attempt; in the worst case several rounds 2 × RBD_NOTIFY_TIMEOUT = 10 s apart"}
:::

```text
pseudocode
rbd_try_lock:
  again: r = cls_lock(header, EXCLUSIVE, cookie) ; if r != −EBUSY: return r
         owner = get_lock_owner_info() ; if none: goto again
         if find_watcher(owner): return 1                 # the owner is alive ⇒ ask it
         if the owner changed: goto again
         ceph_monc_blocklist_add(owner.addr) ; cls_break_lock(owner) ; goto again
rbd_acquire_lock (work):
  r = rbd_try_acquire_lock ; if r ≤ 0: done
  r = rbd_request_lock (notify REQUEST_LOCK, timeout 5 s)
  ETIMEDOUT ⇒ assume the owner is dead, retry ; EROFS ⇒ the owner will not release
  ack ⇒ retry after 10 s if not released ; other error ⇒ retry after RBD_RETRY_DELAY = 1 s
```

**Numerical example.** Host O, which owned the lock, has shut down without warning. Its watch is removed from the watcher list after the watch timeout (`osd_client_watch_timeout`, default 30 seconds). If host N maps at second 10, find_watcher still sees O's watcher, so it sends REQUEST_LOCK. After 5 seconds it gets ETIMEDOUT and tries again. This cycle continues until about second 30. After that the watcher disappears, N blocklists O's address, breaks the lock and acquires it. The first write on N can wait up to about 30 seconds. `lock_timeout` in `rbd map` (default 0, meaning infinite) sets the upper bound of this wait.

![The two branches of lock acquisition in krbd. If the current owner has a live watcher on rbd_header, krbd asks it with a notify to release the lock and waits. If there is no watcher, the owner is assumed dead: its address is blocklisted in the mon so that it cannot finish a pending write, and then the lock is broken and acquired. The order of blocklist before break_lock is vital to prevent two hosts writing at the same time](figures/ch29/f10_lock.png){#fig-29-f10_lock}

## Cap bits and their string {#sec-29-8-5}

::: {.algo #alg-29-5 title="Encoding and displaying caps" src="fs/ceph/caps.c :: ceph_cap_string, gcap_string; include/linux/ceph/ceph_fs.h (CEPH_CAP_S*, CEPH_CAP_G*)" complexity="O(1): at most 16 bits"}
:::

```text
pseudocode
s = "" ; if caps & PIN: s += "p"
for (letter, shift) in (A,2) (L,4) (X,6):  c = (caps ≫ shift) & 3 ; if c: s += letter + gcap(c)
c = caps ≫ 8 ; if c: s += "F" + gcap(c)
gcap(c): for bits 1,2,4,…,128 the letters s x c r w b a l, in order
revoking = implemented & ~issued                # in __ceph_check_caps and handle_cap_grant
```

**Numerical example.** The value 0x3F55 = 1 + 4 + 16 + 64 + (63 ≪ 8) becomes the string `pAsLsXsFsxcrwb`. If the MDS takes back the Fb bit (new issued = 0x1F55), revoking = 0x3F55 & ~0x1F55 = 0x2000, that is 1 ≪ 13 = FILE b. The client must flush its dirty pages and then send an ack. Until the ack arrives, the MDS keeps another client that asked for Fw waiting. This is the origin of the "client X failing to respond to capability release" messages in `ceph health detail`.

![The layout of the cap bits in an integer, and the example 0x3F55. Bit 0 is PIN. AUTH, LINK and XATTR each have two bits (shared and exclusive). FILE has eight bits from bit 8 on: s, x, c, r, w, b, a and l. The highlighted cells are the active bits of the example. ceph_cap_string turns these bits into the string seen in debugfs and the MDS logs](figures/ch29/f07_capbits.png){#fig-29-f07_capbits}

# Supplementary and up to date {#sec-29-9}

- msgr2.1 support in the kernel client is from version 5.11 (according to `Documentation/filesystems/ceph.rst`).
- `RBD_FEATURES_ALL` in the master rbd.c includes layering, striping v2, exclusive-lock, object-map, fast-diff, deep-flatten, data-pool and operations. journaling (bit 6) is not in it. So images with journaling, for rbd-mirror in journal mode, cannot be mapped with krbd.
- The code quoted or named in this chapter is from the kernel master branch at the time of writing. Enterprise distributions (RHEL, Ubuntu LTS) may have different backports. Always check `modinfo rbd` and `uname -r` against your distribution's changelog.

# Hands-on exercise {#sec-29-10}

1. Attach an image with `rbd map` and test it with `fio --direct=1 --rw=randwrite --bs=4k --iodepth=64`. Meanwhile read `cat /sys/kernel/debug/ceph/*/osdc` several times and compare the number of in-flight requests with the iodepth.
2. Run the same test with `rbd-nbd` and librbd and compare the latency.
3. Open a CephFS file from two kernel clients (one writer and one reader) and watch the caps change in `/sys/kernel/debug/ceph/*/caps`.
4. On a test cluster, run `ceph osd pause`, compare the kernel client's behaviour with and without `osd_request_timeout=30`, and then run `ceph osd unpause`.

# Review questions {#sec-29-11}

1. What parts make up libceph, and why is CRUSH in the kernel too?
2. How is a blk-mq request split into obj_requests?
3. When does krbd use WRITEFULL, ZERO, TRUNCATE or DELETE instead of WRITE?
4. When does copyup happen in krbd?
5. Why does the kernel client get stuck on a full pool, and how can this be bounded?
6. Where do the io_opt and io_min values in krbd come from?
7. Interpret a caps string of the form `pAsLsXsFrwcb`.
8. Why does the second reader of a file being written not get Fc?
9. What does the MDS_HEALTH_CLIENT_LATE_RELEASE warning mean?
10. Name two advantages and two disadvantages of krbd compared with librbd.

# Sources for this chapter {#sec-29-12}

- net/ceph in the kernel: https://github.com/torvalds/linux/tree/master/net/ceph
- drivers/block/rbd.c: https://github.com/torvalds/linux/blob/master/drivers/block/rbd.c
- fs/ceph: https://github.com/torvalds/linux/tree/master/fs/ceph
- Kernel CephFS documentation: https://docs.kernel.org/filesystems/ceph.html
- rbd (man): https://docs.ceph.com/en/latest/man/8/rbd/
- krbd in the Ceph documentation: https://docs.ceph.com/en/latest/rbd/rbd-ko/
- caps in CephFS: https://docs.ceph.com/en/latest/cephfs/capabilities/
- The CephFS kernel client: https://docs.ceph.com/en/latest/cephfs/mount-using-kernel-driver/
