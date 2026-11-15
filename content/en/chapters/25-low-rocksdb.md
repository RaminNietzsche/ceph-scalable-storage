---
chapter: 25
id: ch25
title: 'Lower Layers (3): RocksDB Inside BlueStore'
part: lower
lang: en
---

# Introduction: why RocksDB? {#sec-25-1}

BlueStore writes object data directly to the raw device, but all of its metadata, from onodes and omaps to the freelist and deferred writes, lives in RocksDB. RocksDB is a key-value database based on an LSM-tree: writes are first recorded in a sequential log (the WAL) and an in-memory structure (the memtable), and later, in the background, turned into sorted, immutable files (SSTs) and merged. This structure makes small writes cheap and sequential, which is ideal for BlueStore's frequently changing metadata. The cost is paid in compaction and write amplification. This chapter shows layer by layer how Ceph configures and shards RocksDB and places it on BlueFS.

::: {.summary}

- Ceph carries its own version of RocksDB as a submodule (`ceph/rocksdb`) alongside the code. Its interface is `src/kv/RocksDBStore.cc`, which implements `KeyValueDB`.
- The `bluestore_rocksdb_options` defaults include: a 16M memtable, at most 64 memtables, merging at least 6 memtables before a flush, L1 of 1G, a multiplier of 8 and LZ4 compression.
- Column family sharding (`bluestore_rocksdb_cfs`) splits the `m`, `p` and `O` prefixes into several CFs with an rjenkins hash over part of the key.
- BlueFS spreads RocksDB's levels across the WAL, DB and slow devices according to the `use_some_extra` policy. Overflow to the slow device raises a `BLUEFS_SPILLOVER` warning.

:::

# From a BlueStore transaction to a WriteBatch {#sec-25-2}

`BlueStore::_txc_finalize_kv` and `_kv_sync_thread` gather ready transactions. Each `KeyValueDB::Transaction` in `RocksDBStore` is a `rocksdb::WriteBatch`, and `submit_transaction_sync` hands it to RocksDB with `WriteOptions.sync = true`. Several BlueStore transactions are submitted back to back in one round of `_kv_sync_thread`, but only the last of them is synchronous. So several txcs become durable with one fsync on the WAL (group commit).

![The write and read paths in RocksDB. On the write path, the WriteBatch is first recorded in the WAL (on the WAL or DB device through BlueFS) and then in each column family's active memtable. In the background, full memtables become immutable, once at least 6 have accumulated they are merged and flushed to L0, and compaction moves them to lower levels. A read checks, in order, the memtable, the immutables, all L0 files, and then at most one file from each other level (with the help of the bloom filter)](figures/ch25/f01_write.png){#fig-25-f01_write}

| KeyValueDB operation | RocksDB equivalent | Use in BlueStore |
|---|---|---|
| `set(prefix, key, bl)` | `Put(cf, key, value)` | onode, omap, deferred |
| `rmkey` | `Delete` | removing onodes and omaps |
| `rm_single_key` | `SingleDelete` | keys written exactly once (such as L); the tombstone is removed sooner |
| `rm_range_keys` | `DeleteRange` (above a threshold) | removing an object's whole omap; below `rocksdb_delete_range_threshold=1M` it deletes key by key |
| `merge` | `Merge` with a registered operator | `bitwise_xor` for the freelist and `int64_array` for statistics |

# The WAL: record format {#sec-25-3}

RocksDB's WAL (the `*.log` files in the BlueFS directory named `db.wal`) is divided into fixed 32-kilobyte blocks (`kBlockSize = 32768`). Each record has a 7-byte header (`kHeaderSize = 4 + 2 + 1`): a masked crc32c checksum (4 bytes), the length (2 bytes) and the type (1 byte). The type is one of: `kFullType=1` (the whole record in this block), `kFirstType=2`, `kMiddleType=3` or `kLastType=4` (a record broken across several blocks). In recyclable mode, a 4-byte log number is added and the header becomes 11 bytes.

```text
WAL record (logic from RocksDB db/log_format.h, Apache-2.0/GPL-2.0; drawing from this book)
 +--------+--------+------+---------------------------+
 | CRC(4) | Len(2) | T(1) |  payload: WriteBatch part  |
 +--------+--------+------+---------------------------+
 WriteBatch = seq(8) | count(4) | {type, [cf id], key, value}*
```

::: {.deep}
**How the WAL and BlueFS interact:** for each synchronous commit, RocksDB calls `Sync()` on the WAL file, and BlueRocksEnv turns it into `BlueFS::fsync`. BlueFS flushes the data. If the file has grown, it must also record the new fnode in the BlueFS log, which means a second synchronous write. Envelope mode in Tentacle and later (chapter 24) is designed precisely to eliminate this second write. Also, `max_total_wal_size=1G` means that if the WAL exceeds 1 gigabyte, older memtables are flushed sooner so the WAL can be truncated.
:::

# memtable and flush {#sec-25-4}

The memtable is a skiplist by default. With Ceph's defaults, each memtable has `write_buffer_size=16M`, and up to `max_write_buffer_number=64` memtables (that is at most 1 gigabyte) can be in memory. `min_write_buffer_number_to_merge=6` means a flush only happens when at least six immutable memtables are ready. Then all six are merged together, and keys that were written and deleted in the meantime (such as deferred writes and temporary pg log records) **never reach an SST**. For the `L` and `P` CFs this number is raised to 32 in `bluestore_rocksdb_cfs`, because their keys are very short-lived.

::: {.tip}
This design explains why removing or lowering `min_write_buffer_number_to_merge` in manual tuning usually multiplies write amplification. If you change `bluestore_rocksdb_options`, add only the keys you want in `bluestore_rocksdb_options_annex`, not the whole string.
:::

# SST: file format {#sec-25-5}

![The structure of a block-based SST file. Data is stored in blocks of about 4K (rocksdb_block_size) with key prefix compression and restart points. After the data come the filter block (bloom with 20 bits per key in Ceph), the index (the last key of each block and its BlockHandle), properties and the metaindex. The footer at the end has the BlockHandles of the metaindex and index, the format_version and the magic number 0x88e241b785f4cff7. Each block has a five-byte trailer containing the compression type and the checksum](figures/ch25/f02_sst.png){#fig-25-f02_sst}

| Part | Content | Ceph option |
|---|---|---|
| data block | sorted keys with the shared prefix removed; a restart point every 16 keys | `rocksdb_block_size=4_K` |
| filter | a whole-file or partitioned bloom filter | `rocksdb_bloom_bits_per_key=20` (false positive rate about 0.01%) |
| index | the last key of each block → (offset, size) | `rocksdb_metadata_block_size=4_K` |
| cache | data, index and filter blocks in the block cache | `rocksdb_cache_size=512_M` (varies with autotune), `rocksdb_cache_type=binned_lru`, `rocksdb_cache_index_and_filter_blocks=true` |
| footer | BlockHandles, format_version, magic | — |

::: {.note}
The block checksum type and the default `format_version` depend on the RocksDB version bundled with Ceph. In upstream RocksDB (the main branch) the defaults are `kXXH3` and `format_version=7`. Ceph builds its own version from the `ceph/rocksdb` repository, so to see the exact value, check the `OPTIONS-*` output inside BlueFS (with `bluefs-export`).
:::

# Compaction and levels {#sec-25-6}

![The target size of the levels with Ceph's defaults and their placement on devices. L1 is 1G and each level is 8 times the previous one, so L2 is about 8G, L3 about 64G and L4 about 512G. The use_some_extra policy places the levels that fit completely on block.db, uses the extra space for part of the next level, and sends only the rest to the slow device](figures/ch25/f04_levels.png){#fig-25-f04_levels}

With `compaction_style=kCompactionStyleLevel`, each level Ln (n ≥ 1) is a set of SSTs with no key overlap. When the number of L0 files reaches `level0_file_num_compaction_trigger=8`, an L0→L1 compaction starts. When a level's size exceeds its target, part of it is merged into the next level. Ceph's defaults are `max_bytes_for_level_base=1G`, `max_bytes_for_level_multiplier=8` and `max_background_jobs=4` (flush and compaction together).

**Numerical example of DB size:** an OSD with 10 million 4M objects (about 40 terabytes) and onodes of about 800 bytes has about 8 gigabytes of data just for `O`. With omap and the pg log it may reach 20 to 30 gigabytes. With the defaults, L1+L2+L3 = 1 + 8 + 64 = 73G is needed on the DB to keep all level 3 data on the fast device. If block.db is only 30G, the `use_some_extra` policy puts part of L3 on the DB and the rest on the slow device, and `BLUEFS_SPILLOVER` is reported.

| `bluestore_volume_selection_policy` policy | Behaviour |
|---|---|
| `rocksdb_original` | only levels that fit completely go on the DB |
| `use_some_extra` (default) | the DB's extra space is used for part of the next level; `bluestore_volume_selection_reserved_factor=2` |
| `use_some_extra_enforced` | like the previous one, with stricter enforcement |
| `fit_to_fast` | 100% use of the fast device; allows enabling `level_compaction_dynamic_level_bytes` |

::: {.deep}
**Why a multiplier of 8 and not 10?** Write amplification in leveled compaction is roughly proportional to the level multiplier (each byte at each level is rewritten about multiplier times more), and the extra space is 1/(multiplier−1). A multiplier of 8 versus 10 takes a little more space but reduces write amplification and makes level sizes fit common DB device sizes better. This is a design choice in Ceph's defaults. Before changing it, compute its effect on your DB size.
:::

# Column family sharding {#sec-25-7}

![Column family sharding in BlueStore. The default on main is: "m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L=min_write_buffer_number_to_merge=32 P=min_write_buffer_number_to_merge=32". Each listed prefix has its own separate CF(s). To choose the shard, the specified byte range of the key is hashed with ceph_str_hash_rjenkins and the remainder modulo the number of shards is taken. Unlisted prefixes stay in the default CF](figures/ch25/f03_cf.png){#fig-25-f03_cf}

The definition syntax is `<prefix>(<shards>[,<l>-<h>])[=<options>]`, which `parse_sharding_def` in `RocksDBStore.cc` interprets. `get_key_cf` hashes the `[hash_l, hash_h)` part of the key with `ceph_str_hash_rjenkins` and returns `hash % shards.handles.size()`. In `p(3,0-12)`, bytes 0 to 12 of the key (that is the pool, the PG hash and the start of the nid) are used, so that a PG's omaps stay in one shard and a range scan runs on one CF.

**Why shard?** (1) Each CF has its own memtable and compaction. So frequently changing data (`L` and `P`) is not merged into the same SST as stable onodes (`O`), and write amplification drops. (2) Compaction runs in parallel across several CFs. (3) A separate cache for `O` (`block_cache={type=binned_lru}`) prevents onodes from being evicted by omap.

```bash
# OSD stopped:
ceph-bluestore-tool show-sharding --path /var/lib/ceph/osd/ceph-4
ceph-bluestore-tool reshard --path /var/lib/ceph/osd/ceph-4 \
    --sharding "m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L P"
ceph-kvstore-tool bluestore-kv /var/lib/ceph/osd/ceph-4 stats
# OSD running:
ceph tell osd.4 compact
ceph daemon osd.4 bluefs stats
```

::: {.warn}
`reshard` runs on a stopped OSD and rewrites the whole DB. Before it, set `noout` for the OSD, check the DB's free space, and test on one OSD first. According to the documentation, OSDs created before Pacific remain unsharded after the upgrade (everything in the CF named default), and reshard is the official way to convert them.
:::

# Tuning and diagnosis {#sec-25-8}

| Symptom | Probable cause | Action |
|---|---|---|
| high commit latency (`ceph daemon osd.N perf dump bluestore` → `kv_sync_lat`) | WAL on a slow device, or WAL and DB competing with data | WAL and DB on NVMe; check `bluefs stats` |
| `BLUEFS_SPILLOVER` | block.db smaller than the needed levels | grow the DB (`bluefs-bdev-expand`) or migrate (`bluefs-bdev-migrate`) |
| slowness after mass deletion (for example removing a snapshot) | many tombstones in SSTs | `rocksdb_cf_compact_on_deletion=true` (default) or `ceph tell osd.N compact` |
| OSD memory growth | memtables (up to 1G) and the block cache | `osd_memory_target`, check `dump_mempools` and `rocksdb` in perf |
| L0 full and write stalls | compaction falling behind | check `max_background_jobs` and the DB device's bandwidth |

```bash
ceph daemon osd.4 perf dump rocksdb | jq '.rocksdb | {get_latency, submit_latency, submit_sync_latency, compact, compact_running}'
ceph config set osd bluestore_rocksdb_options_annex "max_background_jobs=6"   # only the changed keys
```

# A WriteBatch at the byte level {#sec-25-9}

To see what a BlueStore transaction looks like on the WAL, we hand-encode a hypothetical WriteBatch with two operations: a `Put` in the CF with ID 3 (key `Ok1o` and value `hello`) and a `SingleDelete` in the CF with ID 7 (key `L42`). The sequence number is 1234567. The type constants come from `db/dbformat.h` in RocksDB: `kTypeColumnFamilyValue=0x5` and `kTypeColumnFamilySingleDeletion=0x8`. The encoder is our own.

| Bytes | Meaning |
|---|---|
| `87 d6 12 00 00 00 00 00` | sequence = 1234567 (u64 little-endian) |
| `02 00 00 00` | count = 2 (u32) |
| `05` | type: Put in a non-default CF |
| `03` | CF ID (varint) |
| `04 4f 6b 31 6f` | key length 4 + "Ok1o" |
| `05 68 65 6c 6c 6f` | value length 5 + "hello" |
| `08 07` | SingleDelete-in-CF type + CF ID 7 |
| `03 4c 34 32` | key length 3 + "L42" |

These 32 bytes are then written as the payload of a WAL record, with a 7-byte header (crc + length + type `kFullType`), into the current 32K block. If the payload crosses the end of the block, it is split into First/Middle/Last records. If fewer than 7 bytes remain to the end of the block, those few bytes are filled with zeros.

::: {.deep}
**Real BlueStore keys:** for prefixes that have their own CF, the prefix's first character is not repeated in the RocksDB key, because the CF itself identifies the prefix. In the default CF, the key is combined as `prefix + 0x00 + key` (`combine_strings`). That is why, when you look directly at the default CF with `ldb`, you see keys like `S\0nid_max`.
:::

# BlueRocksEnv: RocksDB without the kernel file system {#sec-25-10}

`BlueRocksEnv` inherits from `rocksdb::EnvWrapper` and sends RocksDB's file calls to BlueFS:

| Env function in RocksDB | Implementation in BlueFS |
|---|---|
| `NewWritableFile` | `BlueFS::open_for_write` → a `FileWriter` with a buffer and `append` |
| `NewSequentialFile` / `NewRandomAccessFile` | `open_for_read` → a `FileReader` with prefetch |
| `Sync` / `Fsync` | `BlueFS::fsync`: flush the data, and if the size changed, record the fnode in the log |
| `RenameFile` | op_dir_link + op_dir_unlink in one log transaction (atomic) |
| `GetChildren` | the `dir_map` listing |
| `LockFile` | an in-process lock (BlueFS has only one user) |

BlueFS directories express the physical location: `db` (the DB device), `db.wal` (the WAL device) and `db.slow` (the main device). RocksDB creates files in these directories through the `db_paths` and `wal_dir` options, and the BlueFS volume selector (previous section) makes the final decision about the device.

```text
pseudocode: fsync of a WAL file (this book's summary)
  BlueFS::fsync(h):
      _flush_F(h)                         # write the buffer to extents with aio
      if h.file.fnode.size changed (or allocated changed):
          log.t.op_file_update_inc(h.file.fnode)
          _flush_and_sync_log_LD()        # the second synchronous write: the BlueFS log
      else:
          _flush_bdev(h)                  # only flush the device
```

# Algorithms inside RocksDB at the code level {#sec-25-11}

The previous sections described what RocksDB does inside BlueStore. This section examines seven key algorithms with the code of RocksDB 9.11, that is the version the `src/rocksdb` submodule on the main branch points to (the ceph/rocksdb repository). The Reef and Squid versions point to other commits. Defaults that changed across versions are marked separately.

## The skiplist in the memtable {#sec-25-11-1}

The default memtable is an `InlineSkipList`. Ceph does not change the memtable factory, so this same structure is used for all column families. Its constructor has `max_height = 12` and `branching_factor = 4`.

::: {.algo #alg-25-1 title="Insert and search in a skiplist" src="rocksdb/memtable/inlineskiplist.h :: InlineSkipList::RandomHeight, FindGreaterOrEqual, Insert" complexity="search and insert with an expected O(log_4 n) levels and about 4 comparisons per level, that is O(log n). Memory averages 4/3 pointers per node"}
:::

```text
pseudocode
RandomHeight(): h = 1
    while h < 12 and rnd.Next() < 2^32/4: h++          # probability 1/4 for each higher level
FindGreaterOrEqual(key):
    x = head ; level = max_height − 1
    loop: next = x.next[level]
          cmp = (next == null) ? +1 : compare(next.key, key)
          if cmp == 0 or (cmp > 0 and level == 0): return next
          if cmp < 0: x = next                       # move forward
          else: level −= 1                           # move down
Insert(key): height h ; find prev[] and next[] from top to bottom ;
             build the node with one allocation from the arena (pointers before the key) ;
             link from level 0 upward with CAS or store-release
```

**Numerical example.** With write_buffer_size = 16 MiB (Ceph's default) and entries of about 100 bytes, each memtable has about 160000 nodes. The expected number of nodes whose height is at least h is $n \cdot 4^{-(h-1)}$: 160000, 40000, 10000, 2500, 625, 156, 39, 10, 2.4 for h = 1..9. So the effective height is about 9, and a Seek walks about 9 levels with 1 to 3 horizontal steps per level, that is fewer than 30 key comparisons. The average height is 4/3, so each node has on average 8 × 4/3 ≈ 10.7 bytes of pointers. A separate simulation with 160000 nodes gave an average of 1.335.

![A skiplist with ten keys and random heights, and the path of Seek(38) in red. The search starts at head's highest level, moves forward while the next key is smaller, and moves down a level when it is larger or null. If an equal key is found at any level, it returns there. In InlineSkipList the upper-level pointers sit before the node itself in the same arena allocation, so a node of height h has exactly h eight-byte pointers followed by the key and value in one contiguous chunk](figures/ch25/f05_skiplist.png){#fig-25-f05_skiplist}

::: {.note}
Concurrent insertion (`allow_concurrent_memtable_write = true`, RocksDB's default) uses `InsertConcurrently` with CAS at each level. In BlueStore most writes come from `kv_sync_thread`, so contention on the skiplist is low and the main cost is key comparison and cache misses.
:::

## The write group (group commit) {#sec-25-11-2}

::: {.algo #alg-25-2 title="Forming a write group" src="rocksdb/db/write_thread.cc :: WriteThread::JoinBatchGroup, EnterAsBatchGroupLeader, ExitAsBatchGroupLeader" complexity="O(g) for g writers in the group; one AddRecord and at most one fsync for the whole group"}
:::

```text
pseudocode
JoinBatchGroup(w): change newest_writer_ to w with CAS
    if the queue was empty: w is the leader
    else: wait on w.state (short spin, then futex/condvar)
EnterAsBatchGroupLeader(leader):
    max = max_write_batch_group_size_bytes                # 1 MiB
    if size(leader) ≤ max/8: max = size(leader) + max/8   # 128 KiB
    for w from oldest to newest:
        if (w.sync and not leader.sync) or w.disable_wal ≠ leader.disable_wal
           or w.no_slowdown ≠ … or size + size(w) > max: cut
        else: add w to the group
```

**Numerical example.** The leader has a sixty-kilobyte batch. Because 60K ≤ 128K, the group cap becomes 60K + 128K = 188K. The next three writers have 40K, 50K and 70K. 60 + 40 + 50 = 150K is accepted, but with 70K the sum becomes 220K, which exceeds 188K, so the group is cut there. If the leader has sync=false and the second writer sync=true, the group is cut before the second writer, because a leader without sync cannot guarantee an fsync for another writer.

![The group commit sequence in WriteThread. The first writer becomes the leader with a CAS on newest_writer_. The others wait. The leader merges batches into one WAL record up to the size cap and as long as the flags are compatible. It Syncs once, inserts each batch into the memtable with consecutive sequence numbers, and then wakes everyone with STATE_COMPLETED](figures/ch25/f10_wgroup.png){#fig-25-f10_wgroup}

## WAL record format and fragmentation {#sec-25-11-3}

::: {.algo #alg-25-3 title="Splitting a WAL record into 32K blocks" src="rocksdb/db/log_writer.cc :: log::Writer::AddRecord, EmitPhysicalRecord; db/log_format.h" complexity="O(L/32K) fragments for an L-byte record; overhead of 7 bytes per fragment (11 bytes in the recyclable format)"}
:::

```text
pseudocode
left = len(record) ; begin = true
do:
    leftover = 32768 − block_offset
    if leftover < 7: write zeros to the end of the block ; block_offset = 0
    avail = 32768 − block_offset − 7
    frag = min(left, avail) ; end = (frag == left)
    type = begin&&end ? FULL(1) : begin ? FIRST(2) : end ? LAST(4) : MIDDLE(3)
    EmitPhysicalRecord(type, ptr, frag)      # masked crc32c(type‖payload), len (2B), type (1B)
    left −= frag ; begin = false
while left > 0
```

**Numerical example.** A seventy-thousand-byte WriteBatch starts at block_offset = 30000:

- leftover = 2768 and avail = 2761, so FIRST with 2761 bytes.
- Next block: avail = 32761, so MIDDLE.
- Third block: MIDDLE again with 32761 bytes.
- The remainder is 70000 − 2761 − 2×32761 = 1717 bytes, so LAST at the start of the fourth block.

The next block_offset is 7 + 1717 = 1724. The total overhead is 4 × 7 = 28 bytes.

![How log::Writer::AddRecord writes a seventy-thousand-byte batch into four 32 KiB blocks. Each fragment has a 7-byte header: a four-byte crc32c, a two-byte length and a one-byte type. Blocks are independent: if a reader hits a corrupt block during recovery, it can resynchronize from the start of the next block. If fewer than 7 bytes remain to the end of a block, they are filled with zeros](figures/ch25/f08_walfrag.png){#fig-25-f08_walfrag}

## The SST data block: key deltas and restarts {#sec-25-11-4}

::: {.algo #alg-25-4 title="Key delta encoding and Seek within a block" src="rocksdb/table/block_based/block_builder.cc :: BlockBuilder::AddWithLastKeyImpl, Finish; table/block_based/block.cc :: DataBlockIter::SeekImpl (BinarySeek); util/coding.h :: EncodeVarint32" complexity="build O(L); Seek O(log R + I) with R restarts and I = block_restart_interval = 16"}
:::

```text
pseudocode
Add(key, value):
    if counter == 16: restarts.push(buffer.size) ; shared = 0 ; counter = 0
    else: shared = length of the prefix shared with the previous key
    PutVarint32 ×3 (shared, len(key)−shared, len(value)) ; append key[shared:] ; append value
Finish(): append restarts[] as u32 ; append Pack(index_type, num_restarts)   # bit31
Seek(target): binary search over restarts comparing each restart's full key
              then a linear walk, rebuilding key = prev[0:shared] + delta
EncodeVarint32(v): while v ≥ 128: emit (v & 127) | 128 ; v ≫= 7 ; emit v
```

**Numerical example.** With `rocksdb_block_size = 4K` (Ceph's default) and entries of about 300 bytes, each block has about 13 entries, that is fewer than 16, so only one restart. Seek within the block is effectively linear, but 13 comparisons on data that is in cache. In metadata blocks where values are small (for example 100 keys of 40 bytes), there are 7 restarts and the binary search takes 3 comparisons plus at most 15 linear steps. The varint encoding of 300 is the two bytes AC 02, and of 18 the single byte 12.

![Byte-by-byte layout of an SST data block with two sample entries. The first entry is a restart and holds the full 18-byte key (10 bytes of user key and 8 bytes of trailer containing seq and type). The second entry has only 9 non-shared bytes. The end of the block is the array of restart offsets and a u32 footer whose bit 31 indicates the in-block index type and whose remaining bits give the number of restarts](figures/ch25/f07_block.png){#fig-25-f07_block}

## The cache-line-local Bloom filter {#sec-25-11-5}

With `rocksdb_bloom_bits_per_key = 20`, Ceph calls `NewBloomFilterPolicy(20)` (`RocksDBStore::load_rocksdb_options`). In RocksDB 9.11 the default is `format_version = 6`, so the filter implementation is `FastLocalBloomImpl`: all probes of a key fall within one five-hundred-and-twelve-bit cache line.

::: {.algo #alg-25-5 title="Cache-line-local Bloom" src="rocksdb/util/bloom_impl.h :: FastLocalBloomImpl::ChooseNumProbes, AddHash, HashMayMatchPrepared; BloomMath::CacheLocalFpRate" complexity="O(k) bit reads in one cache line (up to 8 probes at once with AVX2); memory b bits per key"}
:::

```text
pseudocode
k = ChooseNumProbes(1000·b)            # empirical table: 20000 millibits ⇒ 11
AddHash(h1, h2): line = FastRange32(h1, len/64) · 64     # choose the cache line
    h = h2
    repeat k: bit = h ≫ 23 (top 9 bits ⇒ 0..511) ; line[bit] = 1 ; h ×= 0x9e3779b9
MayMatch: the same path ; if any bit is zero ⇒ "definitely not present"
FP ≈ the average of a standard Bloom for (keys per line ± standard deviation)
```

**Numerical example.**

- **b = 20:** k = 11, and each cache line has on average 512/20 = 25.6 keys. The standard deviation is $\sqrt{25.6} \approx 5.06$, so the crowded and sparse cases have 30.66 and 20.54 keys per line. The estimated FP is about $1.7 \times 10^{-4}$ (0.017%), versus $6.8 \times 10^{-5}$ for a standard Bloom with the same memory.
- **b = 10:** k = 6 and FP about 0.95%.
- **Memory:** an SST with 1 million keys has $20 \times 10^6$ bits, that is 2.5 MB of filter.

The price of locality is a slightly higher FP. In return, each query has only one cache miss instead of 11.

![False positive rate versus bits per key for a standard Bloom and a cache-line-local Bloom, with the number of probes each implementation chooses. The red point is Ceph's setting (20 bits, 11 probes, about 0.017%). At 10 bits the two curves differ little, and at 20 bits by about 2.5 times. But the local Bloom always touches one 64-byte line, and this is decisive for onode Gets, most of which look in L0 to L2 for a key that is not there](figures/ch25/f06_bloom.png){#fig-25-f06_bloom}

## The compaction score and dynamic level sizes {#sec-25-11-6}

::: {.algo #alg-25-6 title="Computing level targets and the compaction score" src="rocksdb/db/version_set.cc :: VersionStorageInfo::CalculateBaseBytes, ComputeCompactionScore, MaxInputLevel" complexity="O(number of files) on each Version change"}
:::

```text
pseudocode
CalculateBaseBytes (dynamic):
    max_level_size = the largest level ; cur = max_level_size
    for i = num_levels−2 down to first_non_empty: cur /= multiplier
    base_level = first_non_empty
    while base_level > 1 and cur > base_bytes_max: base_level−− ; cur /= multiplier
    target[base_level] = max(cur, base_bytes_max) ; target[i+1] = target[i]·multiplier (floor base_bytes_max)
ComputeCompactionScore: for level in 0 .. num_levels−2:
    L0: score = max(files/trigger, size/max_bytes_for_level_base …) and ×10 if > 1
    L>0: score = bytes_not_compacting / target   (or / (target + incoming) ×10 if ≥ 1)
highest score ⇒ first compaction
```

**Numerical example (Ceph's defaults: base = 1 GiB, multiplier = 8, seven levels).** Suppose L6 has two hundred gigabytes. From the bottom up: L5 = 25, L4 = 3.125 and L3 = 0.39 GiB. Because 0.39 is larger than base_bytes_min = 1/8 GiB, base_level = L3 and the targets are L3 = max(0.39, 1) = 1 GiB, L4 = 3.125, L5 = 25 and L6 = 200. With actual sizes of 0.31, 3.0 and 24, the scores are 0.31, 0.96 and 0.96. None has reached 1. If L0 has eight files, its score is 8/8 = 1, which becomes 10 after multiplying by kScoreScale, so L0→L3 has priority. L1 and L2 stay empty: this is exactly the dynamic level bytes behaviour, which takes data straight to the base level.

![The actual and target size of each level with level_compaction_dynamic_level_bytes=true. The targets are obtained from the last level upward by dividing by 8. L1 and L2 are below the base level and stay empty. No score is computed for the last level, because MaxInputLevel is num_levels − 2](figures/ch25/f09_dynlevels.png){#fig-25-f09_dynlevels}

::: {.warn}
The default of `level_compaction_dynamic_level_bytes` in RocksDB changed to true in version 8.4. Ceph's `bluestore_rocksdb_options` string does not set this option explicitly. So the level behaviour depends on the RocksDB version inside each Ceph release. To be sure, check the output of `ceph daemon osd.N config get bluestore_rocksdb_options` and the OPTIONS-* file inside BlueFS (with `ceph-bluestore-tool bluefs-export`).
:::

# Supplementary and up to date {#sec-25-12}

- Sharding has been the default for new OSDs since Pacific. Compare main's default string, `m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L=min_write_buffer_number_to_merge=32 P=min_write_buffer_number_to_merge=32`, with `ceph config help bluestore_rocksdb_cfs` on your version.
- `bluefs_spillover_cleaner` (present in Tentacle and main, default false) is a background thread that moves files that spilled over to the slow device back to the DB, if there is space.
- According to the documentation, Pacific brought experimental support for `level_compaction_dynamic_level_bytes` (together with the `fit_to_fast` policy).

# Hands-on exercise {#sec-25-13}

1. Extract a test OSD's RocksDB files with `ceph-bluestore-tool bluefs-export`, see the CFs with `ldb --db=... list_column_families`, and read the sizes of data, index and filter with `sst_dump --file=... --show_properties`.
2. Read the last 8 bytes of an SST with `tail -c 8 | xxd` and confirm the magic number (mind the little-endian order).
3. For your DB size (for example 60G), compute which levels fit with the defaults. Then read `bluefs stats` and compare it with your prediction.
4. Compare `submit_sync_latency` before and after moving the WAL to NVMe.

# Review questions {#sec-25-14}

1. How does group commit in `_kv_sync_thread` reduce the number of fsyncs?
2. How many bytes is a WAL record header, and what fields does it have?
3. Why is `min_write_buffer_number_to_merge=6` important for Ceph?
4. Why is this number 32 for the `L` and `P` CFs?
5. What role does an SST's filter block play on the read path?
6. With the defaults, how large is L3?
7. How does `use_some_extra` differ from `rocksdb_original`?
8. How is the CF of a per-pg omap key chosen?
9. Why should a PG's omap stay in one shard?
10. Why is changing the whole `bluestore_rocksdb_options` string dangerous, and what is the alternative?

# Sources for this chapter {#sec-25-15}

- RocksDBStore: https://github.com/ceph/ceph/blob/main/src/kv/RocksDBStore.cc
- BlueStore configuration and sharding: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- RocksDB WAL format: https://github.com/facebook/rocksdb/wiki/Write-Ahead-Log-File-Format
- Block-based table format: https://github.com/facebook/rocksdb/wiki/Rocksdb-BlockBasedTable-Format
- Leveled compaction: https://github.com/facebook/rocksdb/wiki/Leveled-Compaction
- Column families: https://github.com/facebook/rocksdb/wiki/Column-Families
- log_format.h: https://github.com/facebook/rocksdb/blob/main/db/log_format.h
- LSM-tree (O'Neil et al., 1996): https://www.cs.umb.edu/~poneil/lsmtree.pdf
