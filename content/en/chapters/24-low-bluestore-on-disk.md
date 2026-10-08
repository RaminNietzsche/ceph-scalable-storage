---
chapter: 24
id: ch24
title: 'Lower Layers (2): BlueStore and BlueFS On-Disk Format'
part: lower
lang: en
---

# Introduction: what does BlueStore write on disk? {#sec-24-1}

In chapter 23 we saw how bytes get from a bufferlist to `io_submit`. This chapter shows **where** and **in what format** those bytes land on disk: from the device's first 4 kilobytes (the label) to the superblock and the BlueFS log, and from the RocksDB keys that hold the onode and extent map to the freelist bits and the in-memory cache structure. All structures were extracted from the main branch of the Ceph code (`src/os/bluestore/`). Wherever behaviour depends on the version, it is marked.

::: {.summary}

- The first 4K of every BlueStore device is a label, and the second 4K is the BlueFS superblock. New versions also copy the label at 1G, 10G, 100G and 1000G.
- BlueFS is a small append-only file system for RocksDB. Its metadata lives in a log file (ino 1) as transactions of type `bluefs_transaction_t`.
- Compact encoding with `denc_varint_lowz` and `denc_lba` means a 4K-aligned extent usually fits in 5 bytes.
- The onode is under key `O`, and large extent maps are broken into shards with an `x` suffix.
- The default allocator is hybrid (AVL with overflow to Bitmap). The freelist in RocksDB is only used when "allocation from file" mode is off.

:::

# The device label: bluestore_bdev_label_t {#sec-24-2}

![The layout of the start of BlueStore devices. On a block device with a co-located DB, block 0 is the label, block 1 the BlueFS superblock, and the rest shared space for data and BlueFS. The label is also repeated at the 1, 10, 100 and 1000 gigabyte positions (only if the device is that large). On a separate block.db device, BlueFS extents start at 8K (SUPER_RESERVED)](figures/ch24/f01_layout.png){#fig-24-f01_layout}

The constants are defined in `bluestore_common.h`: `BDEV_FIRST_LABEL_POSITION = 0`, `BDEV_LABEL_BLOCK_SIZE = 4096`, `BLUEFS_SUPER_POSITION = 4096` and `SUPER_RESERVED = 8192`. The label's content, in order:

| Bytes | Content | Description |
|---|---|---|
| 0–22 | `bluestore block device\n` | 23 ASCII bytes, for anyone looking at the device with `hexdump` |
| 23–58 | the OSD's uuid as text | 36 characters |
| 59 | `\n` | 60 bytes in total; the decoder skips this part with `p += 60` |
| 60… | `ENCODE_START(2,1)` | struct_v=2, compat=1, length (u32) |
| … | osd_uuid (16 bytes), size (u64), btime (utime_t), description (string) | description is for example `main` or `bluefs db` |
| … | meta: `map<string,string>` | keys such as `ceph_fsid`, `whoami`, `osd_key`, `ready`, `kv_backend`, `type=bluestore` |
| end | crc32c (u32) over everything above with seed −1 | then zeros up to 4096 bytes |

```bash
# reading the label (read-only; the OSD can be running)
ceph-bluestore-tool show-label --dev /dev/ceph-xxx/osd-block-yyy
dd if=/dev/ceph-xxx/osd-block-yyy bs=4096 count=1 2>/dev/null | hexdump -C | head -5
```

::: {.warn}
The `osd_key` value in meta is a cephx key. Never put the output of `show-label` in a ticket or chat without removing this field.
:::

::: {.deep}
Why multiple copies? In old versions, corruption of the first 4K (for example by `wipefs` or a partitioning tool writing by mistake) made the OSD unrecoverable. The main branch has the array `bdev_label_positions = {0, 1G, 10G, 100G, 1000G}`. At mount, BlueStore reads a valid label from any healthy position (`_read_multi_bdev_label`) and keeps the valid positions in `bdev_label_valid_locations`. Because old versions may have used those regions for data, a copy is only written where the allocator has reserved it. Check the reservation mechanism and the exact range of versions in your version's release notes before relying on it.
:::

# Compact encodings: varint, lowz and lba {#sec-24-3}

Before going to the structures, you need to know three encodings defined in `include/denc.h` and used everywhere in BlueStore metadata:

| Function | Format | Use |
|---|---|---|
| `denc_varint` | 7 data bits per byte; the high bit means "another byte follows" (little-endian) | counters, blobid |
| `denc_varint_lowz` | the low 2 bits = number of trailing zero nibbles removed (0 to 3), then a varint | lengths (usually multiples of 4K) |
| `denc_lba` | a 32-bit word: the first 1 to 3 bits are the kind of trailing-zero removal (`0`=12 bits, `01`=16, `011`=20, `111`=none), then 28 to 30 data bits, bit 31 = continuation | physical offsets on disk |

| Value | denc_varint | denc_varint_lowz | denc_lba |
|---|---|---|---|
| 0x1000 (4K) | `80 20` | `07` | `02 00 00 00` |
| 0x3000 (12K) | `80 60` | `0f` | — |
| 0x10000 (64K) | `80 80 04` | `43` | — |
| 0x12340000 | — | — | `d1 48 00 00` |
| 0x3a8f05000 | — | — | `0a 1e 75 00` |

**Step-by-step lowz example for 0x10000:** this number has 16 trailing zero bits, that is 4 nibbles, but the cap is 3. So 0x10000 >> 12 = 0x10 and (0x10 << 2) | 3 = 0x43, which fits in one byte.

**lba example for 0x12340000:** this number has 18 trailing zero bits, that is 4 full nibbles. So t = 4 − 3 = 1, and the "remove 16 bits" mode with prefix `01` is chosen: 0x12340000 >> 16 = 0x1234 and word = 0b01 | (0x1234 << 2) = 0x48D1. The output is four little-endian bytes: `d1 48 00 00`. We computed these values with an independent Python implementation based on the logic of `denc.h`.

::: {.note}
The practical result: a `bluestore_pextent_t` (offset with `denc_lba` and length with `denc_varint_lowz`) for a typical 4K-aligned 64K extent is only 5 bytes, while its raw form would be 12 bytes (u64 + u32). When you have billions of extents in RocksDB, this difference has a big effect on DB size and cache hit rate.
:::

# BlueFS: a file system for RocksDB {#sec-24-4}

RocksDB needs a file system (SST, WAL, MANIFEST and CURRENT files). Instead of ext4 or XFS, BlueStore has its own small file system, BlueFS, connected to RocksDB through `BlueRocksEnv`. BlueFS implements only what RocksDB needs: a few flat directories, append-only files, rename, unlink and fsync.

![The structure of BlueFS. The superblock is in block 1 and points to the fnode of the log file (ino 1). The log is a sequence of transactions whose ops (directory creation, link, full or incremental fnode update, removal, seq jump) build the entire metadata. Each fnode has a list of extents {bdev, offset, length}. When the log exceeds 16 megabytes and 5 times the estimated size, compaction starts](figures/ch24/f02_bluefs.png){#fig-24-f02_bluefs}

## Structures {#sec-24-4-1}

| struct | Fields | Note |
|---|---|---|
| `bluefs_super_t` | `_version`, `uuid`, `osd_uuid`, `seq`, `block_size`, `log_fnode`, `memorized_layout` | `_version` is BASELINE=2 or ENVELOPE_MODE_ENABLED=3 |
| `bluefs_fnode_t` | `ino`, `size`, `mtime`, `extents`, `allocated`, `encoding`, `content_size` | `extents_index` is in memory only, for finding an extent with `upper_bound` |
| `bluefs_extent_t` | `offset` (lba), `length` (lowz), `bdev` (u8) | bdev: WAL=0, DB=1, SLOW=2, NEWWAL=3, NEWDB=4 (MAX_BDEV=5) |
| `bluefs_transaction_t` | `uuid`, `seq`, `op_bl` | op_t from OP_NONE to OP_FILE_UPDATE_INC; the ALLOC_ADD/RM ops are obsolete |

```text
pseudocode: BlueFS mount (this book's summary)
  super = decode(read(bdev[DB or SLOW], 0x1000, 4096)); verify crc
  log_reader = open(super.log_fnode)
  pos = 0
  repeat:
      read header at pos; if uuid != super.uuid or seq != expected → end of log
      t = decode(bluefs_transaction_t); verify crc
      for op in t.op_bl:
          INIT        → nothing
          DIR_CREATE  → dir_map[name] = {}
          DIR_LINK    → dir_map[d][f] = ino
          FILE_UPDATE → file_map[ino].fnode = fnode
          FILE_UPDATE_INC → merge extents into file_map[ino].fnode
          FILE_REMOVE → release extents (unless shared)
          JUMP/JUMP_SEQ → pos/seq = ...
      pos = next block-aligned boundary
  # at the end, each bdev's allocator is built from the extents of all fnodes
```

| Option | Default (main) | Effect |
|---|---|---|
| `bluefs_alloc_size` | 1_M | allocation unit on dedicated DB and WAL devices |
| `bluefs_shared_alloc_size` | 64_K | allocation unit on a device shared with data |
| `bluefs_min_log_runway` / `bluefs_max_log_runway` | 1_M / 4_M | pre-allocated space for the log to continue |
| `bluefs_log_compact_min_size` | 16_M | a log smaller than this is never compacted |
| `bluefs_log_compact_min_ratio` | 5 | ratio of actual to estimated size to start compaction |
| `bluefs_buffered_io` | true | BlueFS reads use the kernel page cache |

## Log compaction and envelope mode {#sec-24-4-2}

`_should_start_compact_log_L_N()` compares the current log size with `_estimate_log_size_N()`. If both conditions in the table above hold, `_compact_log_async_LD_LNF_D()` runs: a complete image of the metadata (all directories and fnodes) is written into a new log, the superblock is updated with the new `log_fnode` and a higher `seq`, and the old log's extents are freed. The order of these steps is such that a crash at any moment leaves either the old log intact or the new log complete.

::: {.note}
**Version-dependent:** `bluefs_node_encoding` (PLAIN, ENVELOPE, ENVELOPE_FIN) exists in Tentacle and main but not in Squid. In envelope mode, data appended to a file (for example RocksDB's WAL) is placed in a self-describing envelope. So for each fsync the file size does not need to be updated in the BlueFS log, and an extra synchronous write is eliminated. After a crash, the region between `size` and `allocated` is scanned to find the envelopes.
:::

```bash
ceph-bluestore-tool bluefs-bdev-sizes --path /var/lib/ceph/osd/ceph-4      # OSD stopped
ceph-bluestore-tool bluefs-log-dump --path /var/lib/ceph/osd/ceph-4
ceph daemon osd.4 bluefs stats                         # admin socket on the OSD host
ceph-bluestore-tool bluefs-export --path ... --out-dir /tmp/bluefs   # RocksDB files for ldb
```

# The full map of KV prefixes {#sec-24-5}

All of BlueStore's metadata lives in RocksDB. The first character of each key is its "prefix", defined in `BlueStore.cc`:

| Prefix | Constant name | Key → value |
|---|---|---|
| `S` | PREFIX_SUPER | field name → value (nid_max, blobid_max, min_alloc_size, per_pool_omap, ...) |
| `T` | PREFIX_STAT | pool or whole-store statistics (an int64 array with an `int64_array` merge operator) |
| `C` | PREFIX_COLL | collection (PG) name → `bluestore_cnode_t` (only the `bits` field) |
| `O` | PREFIX_OBJ | object key → `bluestore_onode_t`; extent map shards with an `x` suffix |
| `M` | PREFIX_OMAP | u64 (nid) + key name → value (old, global omap) |
| `P` | PREFIX_PGMETA_OMAP | omap of the pgmeta object (pg log and pg info) |
| `m` | PREFIX_PERPOOL_OMAP | s64 (pool) + u64 (nid) + key name → value |
| `p` | PREFIX_PERPG_OMAP | u64 (pool) + u32 (hash) + u64 (nid) + key name → value (the default in new versions) |
| `L` | PREFIX_DEFERRED | seq → `bluestore_deferred_transaction_t` |
| `B` | PREFIX_ALLOC | freelist metadata (size, blocks_per_key, ...) |
| `b` | PREFIX_ALLOC_BITMAP | offset → bitmap (through BitmapFreelistManager) |
| `X` | PREFIX_SHARED_BLOB | sbid → `bluestore_shared_blob_t` |

::: {.tip}
To see the volume of each prefix on a stopped OSD, use `ceph-kvstore-tool bluestore-kv /var/lib/ceph/osd/ceph-4 stats`, or count the onode keys with `list O | wc -l`. On a healthy RBD OSD, `O` and `p` usually have the most volume. If `L` is large, deferred writes are piling up.
:::

# The onode: from key to extent {#sec-24-6}

![The structure of an onode. The onode key is encoded in an order such that its lexicographic sort matches the ghobject_t order: shard + 0x80, then pool + 2^63, the bit-reversed hash, the namespace and escaped name, snap, generation, and finally the character 'o'. The value is bluestore_onode_t. lextents point to blobs, and blobs to physical pextents. Large extent maps are broken into separate shards with the key "onode + u32 offset + x"](figures/ch24/f03_onode.png){#fig-24-f03_onode}

## The object key {#sec-24-6-1}

The key is built so that a sequential RocksDB scan gives exactly the order of a PG's objects. So `collection_list` (used in scrub and backfill) becomes a simple range scan:

| Component | Encoding | Reason |
|---|---|---|
| shard | `u8(shard.id + 0x80)` | shard = −1 (NO_SHARD) becomes 0x7F and sorts before the EC shards (0x80 and up) |
| pool | `u64(pool + 2^63)` big-endian | negative (temp) pools sort before positive ones |
| hash | bit-reversed `u32`, big-endian | PGs are contiguous ranges of the bit-reversed hash, so a PG's objects fall next to each other |
| namespace and key | escaped string + `!` | characters ≤ `#` become `#xx` and ≥ `~` become `~xx` |
| `<` or `=` or `>` | one character | `=` means the key equals the name and the name is not written again |
| snap, generation | u64 big-endian | snaps and EC generations one after another |
| `o` | suffix | distinguishes the onode from extent shards (`x`) |

## bluestore_onode_t {#sec-24-6-2}

The main fields: `nid` (a local numeric ID for omap keys), `size`, `attrs` (xattrs such as `_` for object_info_t and `snapset`), `extent_map_shards` (a list of `{offset, bytes}`), `expected_object_size`, `expected_write_size`, `alloc_hint_flags`, `segment_size` and `flags` (`FLAG_OMAP=1`, `FLAG_PGMETA_OMAP=2`, `FLAG_PERPOOL_OMAP=4`, `FLAG_PERPG_OMAP=8`). If `extent_map_shards` is empty, the whole extent map is stored inline after the onode in the same value.

## The extent map and its compact encoding {#sec-24-6-3}

Each lextent has four numbers: `logical_offset`, `length`, `blob_offset` and a reference to a blob. `ExtentMap::encode_some` avoids repeating information with four flags in the low bits of the blobid:

| Flag | Value | Meaning |
|---|---|---|
| `BLOBID_FLAG_CONTIGUOUS` | 0x1 | this extent starts exactly after the previous one, so logical_offset is not written |
| `BLOBID_FLAG_ZEROOFFSET` | 0x2 | blob_offset is zero |
| `BLOBID_FLAG_SAMELENGTH` | 0x4 | the length equals the previous extent's |
| `BLOBID_FLAG_SPANNING` | 0x8 | the blob is a spanning blob (shared across several shards) and its ID is written |

The remaining bits (after `BLOBID_SHIFT_BITS = 4`) are the blob ID. If the blob is local and appears for the first time in this shard, zero is written as the ID and the decoder infers it from its own counter.

**Numerical example:** an RBD image with a 4M object that has received two consecutive 64K writes at offsets 0 and 0x10000, each in a new blob:

| extent | blobid before varint | lextent bytes |
|---|---|---|
| 1: lo=0, len=0x10000, boff=0 | CONTIGUOUS + ZEROOFFSET = 0x3 | `03` + lowz(0x10000)=`43` → 2 bytes |
| 2: lo=0x10000, len=0x10000, boff=0 | CONTIGUOUS + ZEROOFFSET + SAMELENGTH = 0x7 | `07` → 1 byte |

After each lextent, if the blob is new, the blob itself is also encoded: flags, pextents (about 5 bytes each) and the checksum array. For a 64K blob with crc32c and a 4K chunk, the checksum array is 16 × 4 = 64 bytes. So **checksums are the dominant part of an onode's size**, not the addresses. With `bluestore_csum_type=crc32c_16` this volume is halved.

| Option | Default | Role |
|---|---|---|
| `bluestore_extent_map_shard_max_size` | 1200 | if a shard grows beyond this size (encoded bytes), it is resharded |
| `bluestore_extent_map_shard_target_size` | 500 | target size when resharding |
| `bluestore_extent_map_shard_min_size` | 150 | shards smaller than this are merged with a neighbour |
| `bluestore_extent_map_inline_shard_prealloc_size` | 256 | buffer pre-allocation for the shard inside the onode |

::: {.deep}
Why sharding? RocksDB rewrites each update in full (an LSM has no read-modify-write at the value level). If an RBD image has many random 4K writes on one 4M object, its extent map gets hundreds of lextents. Without shards, every 4K write would have to rewrite several kilobytes of onode into the WAL and memtable, and metadata write amplification would rise sharply. With shards, only the shard containing the written range (about 500 bytes) becomes dirty.
:::

## Shared blobs and clones {#sec-24-6-4}

When `rbd snap` or `clone_range` shares a blob between two onodes, the `FLAG_SHARED` flag is set on the blob and it gets an `sbid`. The reference counts of its physical extents (`bluestore_extent_ref_map_t`: offset → {length, refs}) are stored under key `X` + sbid. Deleting one of the clones only decrements refs. The physical space is freed when refs reaches zero.

# Deferred writes on disk {#sec-24-7}

For writes smaller than `bluestore_prefer_deferred_size` (64K on HDD), BlueStore first writes the data into RocksDB together with the metadata transaction. Its structure:

| struct | Fields |
|---|---|
| `bluestore_deferred_op_t` | `op` (only OP_WRITE=1), `extents` (the destination PExtentVector), `data` (bufferlist) |
| `bluestore_deferred_transaction_t` | `seq`, `ops` (a list), `released` (an interval_set of space freed after applying) |

```text
pseudocode: the deferred cycle (this book's summary)
  txc: kv.set("L" + seq, encode(deferred_txn)); kv.submit_sync()     # RocksDB's WAL = durability
  ack → client
  deferred_queue: gather until bluestore_deferred_batch_ops or throttle pressure (128M)
  _deferred_submit: aio_write(extents, data) on the main device (no separate fsync)
  _deferred_aio_finish → in the next txc: kv.rmkey("L" + seq)     # after the device flush
  mount after a crash: _deferred_replay() rewrites all L* to disk (idempotent)
```

# The allocator: who knows the free space? {#sec-24-8}

![Allocators and the freelist. The default allocator is hybrid: free space is kept in an AVL (an offset tree and a size tree), and if its memory exceeds bluestore_hybrid_alloc_mem_cap (64M), small pieces overflow into a Bitmap. The persistent freelist, if used, is under prefix b: each key covers 128 allocation units with 128 bits, and changes are applied with a bitwise_xor merge operator. In allocation-from-file mode (the default), the allocator is saved to a BlueFS file on a clean shutdown and rebuilt from the onodes after a crash](figures/ch24/f04_alloc.png){#fig-24-f04_alloc}

| Allocator | Structure | Property |
|---|---|---|
| `bitmap` | a three-level bit tree (`fastbmap_allocator_impl`) | fixed, predictable memory (1 bit per unit), but searching for large pieces is slower |
| `avl` | two AVL trees: by offset and by size | first-fit up to `bluestore_avl_alloc_bf_threshold=128K` or while free space is above `bf_free_pct=4%`, then best-fit |
| `btree` / `hybrid_btree2` | a B-tree instead of AVL | lower memory use per range |
| `hybrid` (default) | AVL + Bitmap for overflow | memory cap with `bluestore_hybrid_alloc_mem_cap=64M` |
| `stupid` | bin trees | testing only |

::: {.note}
`bluestore_allocator_lookup_policy` (present in Squid, Tentacle and main) determines whether the search continues from the last found position (`hdd_optimized`, for sequential writes on HDD and QLC) or starts from the beginning of the device (`ssd_optimized`), or is chosen automatically by device type (`auto`).
:::

## The fragmentation score {#sec-24-8-1}

`Allocator::get_fragmentation_score()` returns a number between 0 (one contiguous piece) and 1 (all free space in single-block pieces). The idea is that a 2X-byte piece is more valuable than two X-byte pieces. For pieces smaller than 1M, each doubling of length gets 1.2 times the weight; this factor falls linearly to 1 by 128M and stays constant above that. The score is computed like this:

```text
score(len) ≈ an increasing convex function (linear interpolation between 2^k and 2^(k+1) with the factors above)
ideal    = score(sum)                          # all free space in one piece
terrible = (sum / block_size) × score(block_size)
actual   = Σ score(len_i)
fragmentation = (ideal − actual) / (ideal − terrible)
```

| Free space state (conceptual example) | Score |
|---|---|
| one contiguous 100G piece | 0 |
| thousands of 4M pieces | middling |
| millions of scattered 4K pieces | close to 1 |

```bash
ceph daemon osd.4 bluestore allocator score block       # {"fragmentation_rating": 0.27...}
ceph daemon osd.4 bluestore allocator fragmentation histogram block
ceph-bluestore-tool free-score --path /var/lib/ceph/osd/ceph-4    # OSD stopped
```

::: {.warn}
A score above 0.8 on HDD usually means new blobs are broken into several pieces and sequential writes turn into random ones. The usual solution is adding capacity or reducing fullness. There is no magic defrag tool for BlueStore. Rebuilding the OSD (removal and backfill) is the last resort.
:::

## The freelist and freelist-less mode {#sec-24-8-2}

In `BitmapFreelistManager`, `bytes_per_block` equals the allocation unit (`min_alloc_size`) and `blocks_per_key = bluestore_freelist_blocks_per_key = 128`. So each `b` key, with a 16-byte value, covers 128 units (with a 4K unit, 512K of disk). Allocation and release are both an XOR with a mask (`XorMergeOperator` named `bitwise_xor`). So without reading the previous value, only one merge is sent to RocksDB.

The `bluestore_allocation_from_file` option has existed since Quincy (it is not in Pacific), and on main its default is `true`. In this mode the freelist update is removed from the write path, and on a clean umount BlueStore writes the allocator map into the file `ALLOCATOR_NCB_DIR/ALLOCATOR_NCB_FILE` inside BlueFS. If the shutdown is not clean, the next mount scans all onodes with `read_allocation_from_onodes` to rebuild the used space. This makes transactions lighter, but after a crash it adds several minutes to the mount time of OSDs full of objects.

# The BlueStore cache {#sec-24-9}

![The BlueStore cache. The buffer cache uses the 2Q algorithm by default: fresh data goes to warm_in. When evicted, only its header remains in warm_out. If the same range is read again, it moves to hot. This prevents a sequential scan from evicting frequently used data. Every 5 seconds autotune splits memory between kv, meta and data based on osd_memory_target](figures/ch24/f05_cache.png){#fig-24-f05_cache}

| Option | Default | Role |
|---|---|---|
| `bluestore_cache_type` | 2q | buffer cache type (`2q` or `lru`); the onode cache is always LRU |
| `bluestore_2q_cache_kin_ratio` / `kout_ratio` | 0.5 / 0.5 | warm_in share and warm_out size |
| `bluestore_cache_autotune` | true | dynamic split with PriorityCache |
| `bluestore_cache_autotune_interval` | 5 | seconds |
| `bluestore_cache_size_hdd` / `ssd` | 1_G / 3_G | only when autotune is off |
| `bluestore_cache_meta_ratio` / `kv_ratio` / `kv_onode_ratio` | 0.45 / 0.45 / 0.04 | initial shares in manual mode |
| `osd_memory_cache_min` | 128_M | floor for the whole cache |

The caches are sharded (each OSD op shard has its own cache) to reduce lock contention. Onodes are pinned with a reference counter. An onode in use by an in-flight transaction is not evicted until the transaction ends, even if the cache is full.

```bash
ceph daemon osd.4 perf dump bluestore | jq '.bluestore | {onodes, onode_hits, onode_misses}'
ceph daemon osd.4 dump_mempools | jq '.mempool.by_pool | {o: .bluestore_cache_onode, d: .bluestore_cache_data}'
```

# Space allocation in numbers {#sec-24-10}

The free space of BlueStore's main device is kept by the allocator. The default is `bluestore_allocator = hybrid`: an AVL allocator that hands part of its ranges to a bitmap allocator when needed. This section follows three of its algorithms with numbers.

## near-fit and best-fit in AVL {#sec-24-10-1}

::: {.algo #alg-24-1 title="Choosing a range in AvlAllocator" src="src/os/bluestore/AvlAllocator.cc :: AvlAllocator::_allocate, _pick_block_after, _pick_block_fits" complexity="near-fit O(log R + c) with a cap of c = 100 steps or 16 MiB scanned; best-fit O(log R) on the size tree"}
:::

```text
pseudocode
max_size = the largest range (the end of the size tree)
if max_size < want: want = p2align(max_size, unit) ; force best-fit   # piecewise allocation
free_pct = num_free × 100 / device_size
if force or max_size < bf_threshold (128K) or free_pct < bf_free_pct (4): best-fit
else near-fit:
    align = want & −want ; cursor = lbas[cbits(align) − 1]   # one cursor per power of two
    walk forward from lower_bound(cursor) in the offset tree until offset + want ≤ end
    (at most ff_max_search_count = 100 ranges or ff_max_search_bytes = 16M; then from the start up to cursor)
best-fit: lower_bound({0, want}) in the size tree ⇒ the smallest sufficient range; on a tie, the lower offset
```

**Numerical example.** Part of the device has four free ranges: 32K at 0x10000, 128K at 0x40000, 32K at 0x100000 and 1M at 0x200000.

- **A 64K request (near-fit):** align = 0x10000, so cbits = 17 and cursor = lbas[16] = 0. The first range is too small and the cursor moves to 0x20000. The second range fits: offset = 0x40000 and cursor = 0x50000. The next 64K request continues from 0x50000 with the same cursor, so same-sized allocations land next to each other.
- **A 32K request (best-fit):** suppose the device is large and free space has dropped below 4%. The size tree has two 32K ranges, and lower_bound with key {0, 32K} returns the one with the lower offset, that is 0x10000. The 1M range stays untouched.

The penalty of near-fit is that it fragments large ranges. best-fit is not slower, but it spreads consecutive allocations apart. That is why it is only enabled when space is low.

![Three views of a 3-megabyte region of the device. Green is a free range and hatching is the allocated part. In the middle view, near-fit with the cursor for the 64K size walks forward from the start of the region, skips the 32K range and takes the start of the 128K range. In the bottom view, best-fit places the 32K request exactly in the smallest sufficient range, so the large ranges remain for large requests](figures/ch24/f07_avl.png){#fig-24-f07_avl}

## The fragmentation score in numbers {#sec-24-10-2}

::: {.algo #alg-24-2 title="Computing fragmentation_rating" src="src/os/bluestore/Allocator.cc :: Allocator::get_fragmentation_score" complexity="O(R) for R free ranges (one pass with foreach_interruptible)"}
:::

```text
pseudocode
scale[0] = 1 ; scale[k+1] = scale[k] × w(k)    # w = 1.2 up to 2^20, linear to 1.0 at 2^27, then 1.0
score(v): sc = floor(log2 v) ; b = 2^sc ; x = (v − b)/b
          return b·scale[sc]·(1 − x) + 2b·scale[sc+1]·x       # linear interpolation
actual = Σ score(len_i) ; ideal = score(Σ len) ; terrible = (Σ len / block_size) × score(block_size)
rating = (ideal − actual) / (ideal − terrible)
```

**Numerical example (block_size = 4K, 1 GiB free).** These numbers were computed with an independent implementation of the same formula:

- One 1G piece, and any piece larger than 128M: score 0.
- 16M pieces: 0.093.
- 1M pieces: 0.498.
- 64K pieces: 0.837.
- 16K pieces: 0.933.
- 4K pieces: 1.
- **An 896-megabyte mix** (two 256M pieces, 256 1M pieces and 2048 64K pieces): 0.262. Most of the space is in large pieces, so the score stays low even though there are many small pieces.

Because the factor above 128M is 1, pieces larger than 128M carry no penalty. A score above 0.8 on HDD usually means a small min_alloc_size and scattered allocations. In that state, large writes are broken into several extents.

![The fragmentation score for one gigabyte of free space divided into equal-sized pieces. The horizontal axis is logarithmic. The curve falls quickly between 1 megabyte and 128 megabytes, because the value factor for each doubling of length decreases from 1.2 to 1 in this range. The dashed blue line is the text's sample mix, which has a score of 0.26 despite thousands of small pieces](figures/ch24/f06_fragscore.png){#fig-24-f06_fragscore}

## Hybrid overflow to bitmap {#sec-24-10-3}

::: {.algo #alg-24-3 title="AVL memory cap and moving ranges to bitmap" src="src/os/bluestore/AvlAllocator.h :: AvlAllocator::_try_insert_range; src/os/bluestore/HybridAllocator_impl.h :: HybridAllocatorBase::allocate, _spillover_range" complexity="insert O(log R); with the cap R ≤ range_count_cap"}
:::

```text
pseudocode
range_count_cap = bluestore_hybrid_alloc_mem_cap (64M) / sizeof(range_seg_t)
insert(start, end):
    if size_tree.size < cap: insert into the AVL
    elif end − start > the smallest AVL range: insert and move the smallest to bitmap
    else: straight to bitmap
allocate(want):
    primary = AVL, unless bitmap has free space and want < the smallest AVL range ⇒ primary = bitmap
    take from primary ; take the shortfall from the other ; nothing ⇒ ENOSPC
```

**Numerical example.** Each range_seg_t has two 64-bit numbers (start and end, 16 bytes together) and two boost::intrusive AVL tree hooks (`offset_hook` and `size_hook`). `MEMPOOL_CLASS_HELPERS()` only defines operator new/delete and adds no data member. Each `avl_set_member_hook<>` with default parameters (no optimize_size) has three pointers, parent, left and right, and a balance field, which with 8-byte alignment comes to 32 bytes. So sizeof(range_seg_t) = 16 + 32 + 32 = **80 bytes**. We checked this number by compiling a small program with the same layout on x86-64 (boost.intrusive headers from the main branch, Clang 22.1 via zig c++ 0.17.1, the C++17 standard): the output was hook = 32, seg = 80, offsetof(size_hook) = 48 and alignof = 8. The 64-megabyte cap (`bluestore_hybrid_alloc_mem_cap` = 64 MiB = 67108864 bytes) therefore keeps ⌊67108864 / 80⌋ = 838860 ranges in the AVL. The real memory is a bit higher, because the heap allocator's overhead is not in this calculation. On 32-bit architectures or with other boost headers the number may differ.

- **A sixteen-terabyte HDD with 30% free space and an average piece of 64K:** there are about 4.8T / 64K, that is nearly 73 million ranges. So more than 98% of the ranges, the smallest ones, stay in the bitmap, and the AVL keeps only the largest.
- **A 4K allocation:** it is smaller than the smallest AVL range, so it is taken directly from the bitmap and the large ranges stay untouched.

![The two paths of the hybrid allocator. The top row is inserting a free range: up to the memory cap the range is inserted into the two AVL trees, and after that the smallest ranges are pushed to the bitmap. The bottom row is allocation: requests smaller than the smallest AVL range are answered from the bitmap first. This keeps the OSD's memory bounded without losing large ranges](figures/ch24/f08_hybrid.png){#fig-24-f08_hybrid}

::: {.tip}
To see the real state, run `ceph daemon osd.N bluestore allocator score block` and `bluestore allocator fragmentation histogram block`. If most ranges are small and the score is high, `ceph-bluestore-tool --command free-dump` gives the full distribution. This command only runs on a stopped OSD.
:::

# On a real disk: the label and the free space map {#sec-24-11}

The two figures in this section were taken from the BlueStore OSDs of a test cluster with Ceph 18.2.7. Each OSD's block device was a ten-gigabyte sparse file.

## The first 588 bytes of the label {#sec-24-11-1}

The bytes were read directly from the block file and compared with the output of `ceph-bluestore-tool show-label`. This cluster had no cephx, so meta had no `osd_key`. On a real cluster, remove this field before showing it to anyone.

::: {.algo #alg-24-4 title="Decoding and verifying the label" src="bluestore_bdev_label_t::encode/decode in src/os/bluestore/bluestore_types.cc; _write_bdev_label with bl.crc32c(-1) in BlueStore.cc" complexity="O(label length)"}
:::

```text
pseudocode
b = the first 4 KiB of the device
skip the 60 text bytes: "bluestore block device\n" (23) + text uuid + "\n" (37)
struct_v = b[60] ; compat = b[61] ; len = u32le(b[62:66])        # ENCODE_START(2, 1)
osd_uuid = b[66:82] ; size = u64le(b[82:90]) ; btime = (u32 sec, u32 nsec)
description = (u32 len, bytes) ; meta = u32 count then count pairs (u32 len, key)(u32 len, value)
end = 60 + 6 + len ; crc = u32le(b[end:end+4])
valid if crc32c(seed = 0xffffffff, no final xor)(b[0:end]) == crc
```

**Real values.**

- **Structure header:** at offset 0x3c the value `02 01`, that is struct_v = 2 and compat = 1, and `06 02 00 00`, that is a length of 518. So the body continues up to offset 584.
- **size:** `00 00 00 80 02 00 00 00` equals 0x280000000, that is 10737418240 bytes.
- **btime:** sec = 1794712746 and nsec = 393184192, that is 2026-11-15 06:49:06.393 Tehran time.
- **description and meta:** the description value is "main", and meta has fourteen pairs, including `bfm_blocks = 2621440`, `bfm_bytes_per_block = 4096`, `kv_backend = rocksdb` and `magic = ceph osd volume v026`.
- **crc:** the four bytes at offset 0x248 are 0xb012c37d. We recomputed this value with an independent crc32c implementation (the Castagnoli polynomial, seed −1, no final xor). The decoder skips the same 60 bytes with `p += 60u`.

![The first 588 bytes of the real label of osd.0 on the Ceph 18.2.7 test cluster, coloured by field: the magic text and text uuid (60 bytes), the ENCODE_START header with version and length, the binary uuid, size, btime, description, the fourteen-pair meta and the final crc32c, which was verified with an independent computation](figures/ch24/f09_labelhex.png){#fig-24-f09_labelhex}

## The allocator's free space map {#sec-24-11-2}

The tool used is `ceph daemon osd.0 bluestore allocator dump block`. This command gives the complete list of free extents. `… allocator score block` returns the fragmentation_rating. Both were taken for this version's default allocator (hybrid) with a min_alloc_size of 4 KiB. Three moments were recorded:

- **A:** after deleting the earlier test pools (the 4 KiB and 4 MiB benchmarks). The score was 0.0163.
- **B:** after writing 6000 64 KiB objects into a single-replica pool. The score was 0.0167.
- **C:** after randomly deleting 51% of those objects. The score was 0.0215.

**What the data shows.**

1. **4 KiB holes:** even in A, the free space was fragmented into 26235 extents, 23218 of which were only 4 KiB. We did not isolate the exact cause of these holes in this experiment. It probably comes from interleaved placement with live data and metadata.
2. **Amount of free space:** about 8.5 GiB of free space is almost all in a few large extents of 256 MiB to 2.4 GiB.
3. **64 KiB writes:** these writes did not fill the 4 KiB holes, because the allocator wants a contiguous extent for a 64 KiB request. The later random deletion created about 330 new holes of 64 to 512 KiB.
4. **Overall score:** fragmentation_rating stayed below 0.03 in all three states. This score is byte-weighted (the fragmentation score algorithm in the previous section), and when most free bytes are in large extents, tens of thousands of small holes do not raise it.

So a low score does not mean "we have no small holes". The number of extents affects the allocator's memory and search time. To see it, count the extent list itself.

![The real free space map of osd.0 at three moments. Left: the number of free extents in each size range (logarithmic axis). Right: the total free bytes in each range. Tens of thousands of 4 KiB holes have almost no share of the bytes, which is why fragmentation_rating stays low](figures/ch24/f10_freemap.png){#fig-24-f10_freemap}

# Supplementary and up to date {#sec-24-12}

- **Label copies** (`bdev_label_positions`) exist in the code of Squid, Tentacle and main. **Envelope mode in BlueFS** is only in Tentacle and main, not in Squid. If you have a mixed cluster, do not count on these features on the older OSDs.
- `hybrid_btree2` and `bluestore_allocator_lookup_policy` exist in Squid and later.
- The main branch also has structures for BlueStore's new write path (such as `segment_size` in the onode and FragMetric in `bluestore_common.h`), which are part of ongoing work on reducing fragmentation and the new EC. Follow the details in the release notes before the final release.

# Hands-on exercise {#sec-24-13}

1. On a test OSD, read the device's first 4K with `dd`. Look at the 60 text bytes, compare the rest with the output of `ceph-bluestore-tool show-label`, and recompute the crc with the Python function from chapter 23.
2. Write a `lowz` and an `lba` function, reproduce the values in this chapter's table, and measure the encoded size for real offsets from the output of `ceph-bluestore-tool fsck --deep` or `dump onode`.
3. Write an RBD image with random 4K fio, and count the `O` keys with an `x` suffix (shards) before and after with `ceph-kvstore-tool`.
4. Record `bluestore allocator score block` daily on several OSDs and compare it with how full they are.
5. Stop an OSD with `kill -9`, start it again, and measure the time of `read_allocation_from_onodes` in the log.

# Review questions {#sec-24-14}

1. What do the label's first 60 bytes contain, and why does the decoder skip them?
2. Why is the BlueFS superblock always at offset 4096?
3. How many bytes does `denc_lba` use for a 4K-aligned offset, and why?
4. What condition starts BlueFS log compaction?
5. Why is the hash in the onode key bit-reversed?
6. What savings do the BLOBID flags in the extent map create?
7. Why is the checksum the largest part of an encoded blob?
8. How does the hybrid allocator limit memory use?
9. Why does the freelist use merge with XOR?
10. What problem of LRU does the 2Q algorithm solve?

# Sources for this chapter {#sec-24-15}

- BlueStore types: https://github.com/ceph/ceph/blob/main/src/os/bluestore/bluestore_types.h
- BlueFS types: https://github.com/ceph/ceph/blob/main/src/os/bluestore/bluefs_types.h
- denc encoding: https://github.com/ceph/ceph/blob/main/src/include/denc.h
- Fragmentation score: https://github.com/ceph/ceph/blob/main/src/os/bluestore/Allocator.cc
- BitmapFreelistManager: https://github.com/ceph/ceph/blob/main/src/os/bluestore/BitmapFreelistManager.cc
- BlueStore configuration: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- ceph-bluestore-tool: https://docs.ceph.com/en/latest/man/8/ceph-bluestore-tool/
- The BlueStore paper (SOSP 2019): https://www.pdl.cmu.edu/PDL-FTP/Storage/ceph-exp-sosp19.pdf
- 2Q (Johnson and Shasha, VLDB 1994): https://www.vldb.org/conf/1994/P439.PDF
