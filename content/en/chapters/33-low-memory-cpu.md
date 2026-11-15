---
chapter: 33
id: ch33
title: 'Lower Layers (11): Memory and CPU Inside the OSD — from mempool to NUMA and Profiling'
part: lower
lang: en
---

::: {.tldr}

- Most OSD performance complaints come down to memory (OOM kills) or one saturated thread or shard.
- Each PG's ops go to shard `ps % num_shards`, so a hot PG can saturate one shard while others idle.
- mempools count bytes and items per subsystem without locks; tcmalloc may keep freed memory, so RSS and the mempool total differ.
- PriorityCache splits `osd_memory_target` between onode, data and RocksDB caches; NUMA affinity and profiling (perf, flame graphs) find CPU hot spots.

:::

# Why memory and CPU? {#sec-33-1}

Most performance complaints about an OSD eventually come back to one of these two: either the OSD uses more than its share of memory (and the OOM killer kills it), or one thread or one shard is saturated while the rest are idle. This chapter examines the internal mechanisms of both, function by function: **mempool** for memory accounting, **tcmalloc** as the allocator, **PriorityCache** for dividing the memory budget among caches, **the OSD's threads** and how work is distributed among them, **NUMA**, and the measurement tools (perf, bpftrace and uftrace). All references are to main.

# The threads of a classic OSD {#sec-33-2}

![The most important ceph-osd threads, with the names seen in top -H or perf. msgr-worker-N (from Stack.h) read and decode messages. tp_osd_tp (the OSD::osd_op_tp thread pool) runs ops from ShardedOpWQ. bstore_aio receives I/O completions from the kernel. bstore_kv_sync commits transactions to RocksDB in batches. bstore_kv_final and cfin run callbacks. bstore_mempool tunes memory, rocksdb:low/high do compaction and flush, and osd_srv_heartbt sends heartbeats](figures/ch33/f01_threads.png){#fig-33-f01_threads}

| Thread name | Created in the code | Default count | Note |
|---|---|---|---|
| msgr-worker-N | msg/async/Stack.h | ms_async_op_threads=3 | separate for each messenger (public and cluster) |
| tp_osd_tp | OSD.cc: osd_op_tp | shards × threads_per_shard: SSD 8×2=16, HDD 1×5=5 (since v19.2.1) | timeout 15 seconds and suicide 150 seconds |
| bstore_aio | blk/kernel/KernelDevice.cc | one per device | not in the SPDK path (chapter 31) |
| bstore_kv_sync | BlueStore.cc | 1 | a common bottleneck for small writes |
| bstore_kv_final | BlueStore.cc | 1 | runs on_commit |
| cfin | BlueStore.cc: commit_finisher | 1 | the commit finisher |
| bstore_mempool | BlueStore.h: MempoolThread | 1 | tune_memory every 1 second, balance every 5 seconds |
| osd_srv_heartbt | OSD.cc | 1 | a heartbeat every osd_heartbeat_interval=6 seconds |
| safe_timer | common/Timer.cc | several | OSD and mgr-client ticks |

## Distributing ops among shards {#sec-33-2-1}

For each op, `OSD::enqueue_op` computes the shard index with `pgid.hash_to_shard(num_shards)`. In `osd_types.h` this function is simply `ps() % num_shards`. All the ops of one PG are always queued in one shard and their order is preserved. But the distribution of load among shards depends on how the ps values of that OSD's PGs are spread.

![An example of aliasing in the PG-to-shard mapping. PGs whose ps values are equal modulo 8 (3, 11, 19, 27) all land in shard 3. If these PGs are busy, the two threads of shard 3 saturate while the other 14 threads are idle](figures/ch33/f05_shards.png){#fig-33-f05_shards}

::: {.algo #alg-33-1 title="Mapping a PG to an op-queue shard" src="src/osd/osd_types.h :: spg_t::hash_to_shard; src/osd/OSD.cc :: OSD::enqueue_op" complexity="O(1)"}
:::

```text
shard_index = pg.ps mod num_shards                 # num_shards = osd_op_num_shards_ssd (8)
sdata = shards[shard_index]
sdata.shard_lock: enqueue(op) with the mClock or WPQ scheduler
thread t of that shard: dequeue ⇒ PG lock ⇒ do_op
only a thread with thread_index < num_shards also drains the context (oncommit) queue
```

**Numerical example.** An OSD in a cluster with 100 OSDs and a pool with pg_num=256 and size=3 has about 256×3/100 ≈ 7.7 PGs, of which about 2.6 are primary. With 8 shards, the probability that two primary PGs land in one shard is high (the birthday problem: for three PGs in 8 slots, $1 - (8 \times 7 \times 6)/8^3 \approx 34\%$). When one PG carries most of the load (for example a busy RBD image), **at most** two threads work on it, because the PG lock limits parallel execution of one PG's ops. That is why increasing `osd_op_num_threads_per_shard` does not help a hot PG. Increasing pg_num (and so splitting the hot data) is the real solution.

::: {.note}
**Version-dependent.** The HDD default in v19.2.0 was five shards with one thread, and since v19.2.1 it is one shard with five threads (chapter 21). The shard options are read only when the OSD starts, and changing them requires a restart.
:::

# mempool: lock-free accounting {#sec-33-3}

Every important data structure in Ceph is built with a mempool-specific allocator (for example `mempool::bluestore_cache_onode::map`). On allocation and free, this allocator updates the items and bytes counters of that pool. The challenge is that this update happens on the hot path, from dozens of concurrent threads. A shared atomic counter bounces its cache line between cores and costs hundreds of nanoseconds.

![The structure of a shard_t in mempool.h. Each shard is an array of stats_t for all pools and starts with aligned(128) so that two shards never share a cache line (the code comment takes 128 bytes as the largest cache-line size on known processors). The total of a pool is the sum over all shards](figures/ch33/f02_mempool.png){#fig-33-f02_mempool}

::: {.algo #alg-33-2 title="The sharded mempool counter" src="src/common/mempool.cc :: get_num_shards, pick_a_shard_int; include/mempool.h :: pool_allocator::allocate" complexity="O(1) contention-free update; reading the total O(num_shards)"}
:::

```text
init: threads = clamp(hardware_concurrency, MIN_SHARDS, 128) − 1
      bits = number of bits in threads ; num_shards = 1 << bits
allocate(n, T):
      shid = sched_getcpu() & (num_shards − 1)       # or a fixed round-robin per thread
      shards[shid].pool[ix].bytes += n × sizeof(T)    # atomic, but local to the core
      shards[shid].pool[ix].items += n
allocated_bytes(pool) = Σ over shards of bytes       # only when dumping
```

**Numerical example.** A machine with 48 hardware threads: threads = 48 − 1 = 47 = 0b101111 (6 bits), so num_shards = 64. Each shard_t, with 30 pools in main, is 480 bytes, rounded up to 512. The total is 64 × 512 = 32 KiB. A thread on core 37 always updates shard 37. The only possible contention is when a thread migrates between `sched_getcpu()` and the update, which is rare. A full dump is 64 × 30 additions, which costs nothing at once per second.

::: {.warn}
`ceph tell osd.N dump_mempools` shows only memory that went through the mempool allocators. RocksDB memory (except the block cache, which PriorityCache manages), memtables, thread stacks and tcmalloc fragmentation are not in it. A gap of a few hundred megabytes to over a gigabyte between RSS and the sum of the mempools is normal. `osd_memory_base=768M` is set aside exactly for this "unaccounted" part.
:::

# tcmalloc and "mapped" memory {#sec-33-4}

ceph-osd is linked with tcmalloc (from gperftools) by default. tcmalloc keeps memory at three levels: a per-thread cache, central free lists for each size class, and the page heap, which gets spans from the operating system. Freed memory does not necessarily go back to the operating system. Only when a span is completely free and `ReleaseFreeMemory` or gradual release returns it with madvise is it counted in `pageheap_unmapped_bytes`.

![The levels of tcmalloc. A small allocation is served from the same thread's cache without a lock. A shortfall is refilled from the transfer cache and the central free list, and these get spans from the page heap. Free page-heap memory is given back to the operating system with madvise and shows up in the pageheap_unmapped_bytes counter. PriorityCache computes "mapped" as heap_size minus this unmapped amount](figures/ch33/f07_tcmalloc.png){#fig-33-f07_tcmalloc}

The packages' environment file (`etc/sysconfig/ceph` in the repository) sets `TCMALLOC_MAX_TOTAL_THREAD_CACHE_BYTES=134217728` (128 MiB). This is the limit for all thread caches in the process. If it is lower, the op threads go to the central free list (with a lock) more often. If it is higher, more memory is "hidden" in thread caches. A cephadm deployment sets the container's environment variables separately. Read the real value with `ceph tell osd.N heap stats`.

# PriorityCache: dividing the memory budget {#sec-33-5}

## From osd_memory_target to the cache budget {#sec-33-5-1}

`BlueStore::MempoolThread::_update_cache_settings` and `_resize_shards` set three numbers for the `PriorityCache::Manager` (named "bluestore-pricache"):

```text
target  = osd_memory_target                         (4 GiB)
ltarget = (1 − osd_memory_expected_fragmentation) × target = 0.85 × 4096 = 3481.6 MiB
max     = ltarget − osd_memory_base = 3481.6 − 768 = 2713.6 MiB    (if ltarget > base + min)
min     = osd_memory_cache_min = 128 MiB
```

::: {.algo #alg-33-3 title="Tuning the cache budget with feedback from the heap (tune_memory)" src="src/common/PriorityCache.cc :: PriorityCache::Manager::tune_memory" complexity="O(1) per round (every osd_memory_cache_resize_interval = 1 second)"}
:::

```text
mapped = heap_size − pageheap_unmapped_bytes        # from tcmalloc
new = clamp(tuned_mem, min, max)
if mapped < target:  new += (1 − mapped/target) × (max − new)      # approach max slowly
else:                new −= (1 − target/mapped) × (new − min)      # pull back quickly
tuned_mem = new
```

![A simulation of eight tune_memory rounds with the defaults and hypothetical input values for mapped. From 1500 MiB, because mapped=3000 is below the target, the budget rises to 1824.7. In the next round mapped=4500 is above the target and the budget drops to 1672.4. The budget never goes above max=2713.6 or below min=128](figures/ch33/f03_tune.png){#fig-33-f03_tune}

**Numerical example (the first two rounds of the figure).** tuned_mem=1500 and mapped=3000: ratio = 1 − 3000/4096 = 0.2676, so new = 1500 + 0.2676 × (2713.6 − 1500) = 1824.7 MiB. Next round, mapped=4500: ratio = 1 − 4096/4500 = 0.0898, so new = 1824.7 − 0.0898 × (1824.7 − 128) = 1672.4 MiB. The phrase "approach slowly, bounce away quickly" appears in the code itself. When the gap between mapped and target is large, the increase factor is large, but it shrinks as they get closer. The decrease is proportional to the distance to min, so with large budgets the absolute decrease is larger.

::: {.warn}
**Why an OSD sometimes uses more than osd_memory_target.** This feedback loop only shrinks **the size of the caches**. If unaccounted memory (the pg log during recovery, messenger buffers under pressure, many osdmaps) by itself exceeds the target, the OSD goes over the target even with the cache at its minimum of 128 MiB. osd_memory_target **is not a hard limit**. In a container, the default `osd_memory_target_cgroup_limit_ratio=0.8` sets the target to 80% of the cgroup limit to keep this margin.
:::

## balance: dividing among caches and priorities {#sec-33-5-2}

BlueStore registers four caches in the Manager: kv (the RocksDB block cache), kv_onode, meta (onodes) and data (buffers). The ratios come from `bluestore_cache_kv_ratio=0.45`, `bluestore_cache_meta_ratio=0.45` and `bluestore_cache_kv_onode_ratio=0.04`, and data gets the remainder (about 0.06). Each cache places its data in bins by **age**. Priorities PRI1 to PRI10 map to age ranges (newer = higher priority). PRI0 is reserved for RocksDB indexes and filters.

::: {.algo #alg-33-4 title="Dividing memory among caches in priority order with a weighted fair share" src="src/common/PriorityCache.cc :: Manager::balance, balance_priority; BlueStore.h :: MempoolCache::request_cache_bytes" complexity="O(L × R × C) for L priorities, R rounds and C caches"}
:::

```text
mem_avail = tuned_mem − C × get_chunk(1, tuned_mem)          # reserve one chunk per cache
for pri in PRI0..PRI11:
    pending = all caches; ratios = Σ ratio
    while pending and mem_avail > |pending|:
        for c in pending:
            want = c.request_cache_bytes(pri)                     # what it has in this priority's bins − already assigned
            share = mem_avail × c.ratio / ratios
            if want > share: c.add(pri, share)                    # stays for the next round
            else: c.add(pri, want); pending.remove(c)
        mem_avail −= assigned; ratios = Σ ratio of remaining
    PRI11 (LAST): the remainder is divided by the ratios alone
commit: each cache is rounded to a multiple of get_chunk (usage + 64 MiB, with a chunk between 4 and 64 MiB)
```

**Numerical example.** tuned_mem=1672 MiB. get_chunk: 1672 is rounded up to the next power of two, 2048 MiB, and divided by 256 gives 8 MiB (between 4 and 64). get_chunk(1) is 1 byte + 64 MiB, rounded to a multiple of 8 MiB, that is 72 MiB. Four caches × 72 = 288 MiB reserved, so mem_avail = 1384 MiB.

- **PRI0:** only kv asks (assume 200 MiB of indexes and filters). Its share is 0.45 × 1384 = 622.8, and it gets all 200. mem_avail = 1184.
- **PRI1, round 1** (assumed requests: kv 300, meta 900, data 100, kv_onode 50): the shares are 532.8, 532.8, 71.0 and 47.4 MiB. kv gets its full request (300) and leaves. The rest get their full shares and stay. The total assigned is 951.2, so mem_avail = 232.8 and the remaining ratios sum to 0.55.
- **PRI1, round 2:** meta 0.45/0.55 × 232.8 = 190.5 (it still wants 367.2), data 25.4 (it still wants 29) and kv_onode takes only its remaining 2.6. After a few more rounds, mem_avail falls below the number of caches and the lower priorities get nothing.

![The result of the balance example after PRI0 and two rounds of PRI1. kv has reached 500 MiB, meta 723.3, data 96.4 and kv_onode 50 MB. Because the meta and data caches still have more fresh data than their budget, their older bins (the lower priorities) are evicted at the next commit](figures/ch33/f04_balance.png){#fig-33-f04_balance}

The practical consequence of this example: on an OSD that is short of memory, **the fresh data of all caches** is provided for before the old data of any cache. If the frequently used onodes do not fit in meta, every read has an extra trip to RocksDB (chapter 25). The `bluestore-pricache:meta` counters and similar ones in `perf dump` (the fields pri0_bytes to pri11_bytes, committed_bytes and reserved_bytes) show exactly where the budget went.

# NUMA {#sec-33-6}

On dual-socket servers, access to the memory or a PCIe device of the other socket goes through the inter-socket link and has worse latency and bandwidth. `OSD::set_numa_affinity` handles this automatically.

![The NUMA affinity decision in OSD::set_numa_affinity. The OSD finds the NUMA node of the storage device (get_numa_node) and the node of the public and cluster network interfaces (get_iface_numa_node). If all three are the same and osd_numa_auto_affinity=true, all threads are restricted to the CPUs of that node. osd_numa_node, if set explicitly, takes precedence over the automatic decision](figures/ch33/f06_numa.png){#fig-33-f06_numa}

::: {.algo #alg-33-5 title="Choosing the NUMA node for the OSD" src="src/osd/OSD.cc :: OSD::set_numa_affinity" complexity="O(1) at startup"}
:::

```text
store_node = store.get_numa_node()
front = iface_numa(public addr); back = iface_numa(cluster addr)
if front == back == store_node and osd_numa_auto_affinity: node = front
if osd_numa_node ≥ 0: node = osd_numa_node                # the manual setting takes priority
if node ≥ 0: set_cpu_affinity_all_threads(cpus(node))
```

**Example.** A host with two nodes: nvme0, nvme1 and the first NIC on node 0, and nvme2, nvme3 and the second NIC on node 1. For osd.2 on nvme2, if public and cluster are both on the second NIC, the OSD is automatically bound to cores 32 to 63. If the public network is on the first NIC, the message "public and cluster network numa nodes do not match" appears in the log and no affinity is set. `osd_numa_prefer_iface=true` makes the OSD prefer, when choosing an address, the IP on the interface on the same node as the device. The `ceph osd numa-status` command shows the state for all OSDs.

# Profiling {#sec-33-7}

![The tools by layer. Inside Ceph: dump_mempools, heap stats, perf dump and dump_historic_ops. CPU sampling with perf and flame graphs. Event tracing and off-CPU time with bpftrace. Function-by-function tracing with uftrace. And the stacks of all threads with gdb or eu-stack for a stuck state](figures/ch33/f08_tools.png){#fig-33-f08_tools}

```bash
ceph tell osd.3 dump_mempools | jq '.mempool.by_pool | to_entries | sort_by(-.value.bytes) | .[:5]'
ceph tell osd.3 heap stats
ceph tell osd.3 perf dump | jq '."bluestore-pricache:meta"'
ceph osd numa-status
top -H -p $(pidof ceph-osd)                     # thread names
perf record -F 99 -g -p PID -- sleep 30 && perf script | stackcollapse-perf.pl | flamegraph.pl > osd.svg
bpftrace -e 'kprobe:finish_task_switch /pid == PID/ { @[kstack, comm] = count(); }'   # approximate off-CPU
uftrace record --no-libcall -P 'BlueStore::_txc_.*' -- ceph-osd -f --id 3   # run a test OSD under uftrace (uftrace launches the process itself)
eu-stack -p PID > stacks.txt                    # all threads, without a long pause
```

**Reasoning about the CPU budget per op (a hypothetical model).** Suppose an OSD on NVMe with 16 tp_osd_tp threads does 30 thousand 4 KiB writes per second, and `perf` shows ceph-osd using about 6 full cores. The budget = 6 / 30000 = 200 microseconds of CPU per op (including the replica). If the flame graph shows 15% in crc32c and msgr2 encryption, 35% in PrimaryLogPG and building the transaction, 30% in BlueStore and RocksDB and 20% in the messenger and memory allocation, removing encryption (crc mode instead of secure) saves at most 30 microseconds. By contrast, reducing RocksDB write amplification (chapter 25) affects a larger share. This kind of "share × budget" calculation before any tuning prevents ineffective optimizations. Measure the real numbers yourself.

# mempools with real data {#sec-33-8}

This section shows real mempool numbers from three BlueStore OSDs of a test cluster running Ceph 18.2.7. The output of `ceph daemon osd.N dump_mempools` reports each pool with two numbers: items and bytes. The ratio of the two is the "cost per item", and it is the best way to estimate memory at scale.

## pg log length and the per-OSD budget {#sec-33-8-1}

::: {.algo #alg-33-6 title="The pg log length budget per PG" src="OSDService::get_target_pg_log_entries in src/osd/OSD.cc; trimming in PeeringState::calc_trim_to with osd_pg_log_trim_min = 100" complexity="O(1) per PG"}
:::

```text
pseudocode
num_pgs = number of PGs on this OSD (primary and replica)
target = osd_target_pg_log_entries_per_osd        # default 300000
if num_pgs > 0 and target > 0:
    entries = max(min(target / num_pgs, osd_max_pg_log_entries = 10000), osd_min_pg_log_entries = 250)
else entries = osd_min_pg_log_entries
trimming happens only when at least osd_pg_log_trim_min entries can be removed ← the length rises to about entries + 100
trimmed entries move to dups (up to osd_pg_log_dups_tracked = 3000); both are in the osd_pglog mempool
```

**The experiment.** To see the limit early, we set `osd_target_pg_log_entries_per_osd` to 30000. Then on the pool `m33` (32 PGs, size = 1) we did one hundred and twenty thousand 128-byte writes to 1000 objects (overwrites), followed by sixty thousand writes to new objects. Every ten thousand writes we read the mempools and the `log_size` of all PGs.

**The result.** The OSDs had 33, 38 and 25 PGs, so the budgets were 909, 789 and 1200. The log length levelled off at around 40 thousand writes. The average was about 980 and the maximum 1300, which is that 1200 plus at most 100 entries waiting to be trimmed. After reaching the limit, the `osd_pglog` mempool still grew slowly: on osd.0 from 79.7 to 86.5 MiB. The reason is that trimmed entries go to `dups`, and dups are in the same mempool (`mempool::osd_pglog::list<pg_log_dup_t> dups` in osd_types.h). In this period each new item cost about 110 bytes on average, compared with about 300 bytes when the log was first filling up.

![Left: the maximum and average pg log length over the 32 PGs of pool m33 against the number of writes, with each OSD's budget as a dashed line (30000 divided by the number of PGs). Right: the size of the osd_pglog mempool (solid line) and bluestore_cache_onode (dashed line) for each OSD. The dotted line marks the boundary between overwriting 1000 objects and creating new objects](figures/ch33/f09_pglogmem.png){#fig-33-f09_pglogmem}

## Cost per item {#sec-33-8-2}

From the last sample of osd.0 (after 180 thousand writes) these costs were obtained:

| mempool | Bytes per item | Takeaway |
|---|---|---|
| bluestore_cache_onode | 679.4 | each onode in the cache is about 680 bytes. One million onodes in the cache is about 650 MiB |
| osd_pglog | 378.6 | the mixed average of log entries and dups |
| bluestore_blob and bluestore_shared_blob | 112.0 | per blob |
| bluestore_inline_bl | 88.2 | small inline data |
| bluestore_alloc | 80.0 | equal to the size of a range_seg_t node in the AVL/hybrid allocator (chapter 24) |
| bluestore_extent | 48.0 | per logical extent |

Use these numbers directly for estimates. For example, 300000 pg log entries per OSD at about 380 bytes is roughly 110 MiB, and that is without dups. If the dups fill up to 3000 per PG, on an OSD with 200 PGs another 600000 dups are added.

These are not outside the cache budget in osd_memory_target. PriorityCache tunes only the BlueStore and RocksDB caches. The pg log is fixed memory that is subtracted from the cache's share.

::: {.note}
The 80 bytes for bluestore_alloc is the same as the size of range_seg_t that we derived from the code in chapter 24. This match is an independent check of that number.
:::

![The real cost per item (bytes divided by the number of items) in the main mempools of osd.0 on the Ceph 18.2.7 test cluster, together with the number of items and the total size of each mempool](figures/ch33/f10_itemcost.png){#fig-33-f10_itemcost}

# Supplementary and up to date {#sec-33-9}

- The list of mempool pools in main includes `ec_extent_cache`, `bluefs_file_reader` and `bluefs_file_writer`. Check which pools exist in your version with `dump_mempools`.
- In Crimson (chapter 30), instead of a thread pool, each reactor has one core and Seastar has its own per-core allocator. The memory and CPU model of this chapter applies only to the classic OSD.
- `osd_memory_target_autotune` (default false) lets cephadm set the target at the host level, based on the total memory and the number of OSDs. This setting is made outside the OSD and has nothing to do with the tune_memory loop inside the OSD.
- PriorityCache is also used in the mons for the RocksDB and osdmap caches (the `mon_memory_target` and `mon_memory_autotune` options).

# Hands-on exercise {#sec-33-10}

1. On a test OSD, reduce `osd_memory_target` to 2 GiB and record the `bluestore-pricache` section of `perf dump` every 5 seconds. Compare the gradual decrease of committed_bytes with the tune_memory model.
2. Compute the mempool num_shards for your own machine from nproc.
3. List an OSD's primary PGs with `ceph pg ls-by-primary osd.N`, compute each PG's ps modulo 8 and estimate the load of the shards.
4. Build a flame graph of the OSD with `perf record` during `rados bench -t 64 write` and read the shares of crc32c, RocksDB and tcmalloc.
5. Run `ceph osd numa-status` and explain for each OSD why NUMA affinity was or was not set.

# Review questions {#sec-33-11}

1. Why does mempool use shards instead of one shared atomic counter, and how is the shard chosen?
2. Why is the size of shard_t a multiple of 128?
3. Compute, with the defaults, the two numbers derived from osd_memory_target as the max and min of the cache budget.
4. How does tune_memory behave differently when increasing and when decreasing?
5. Why is osd_memory_target not a hard limit?
6. In balance, what happens to a cache that asks for less than its share, and who gets the remainder?
7. What is get_chunk for a tuned_mem of 1672 MiB?
8. Why does increasing threads_per_shard not help a hot PG?
9. Under what condition does the OSD set NUMA affinity automatically?
10. How do you compute the "CPU budget per op", and what do you conclude from it?

# Sources for this chapter {#sec-33-12}

- BlueStore memory configuration: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- OSD option reference: https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/
- mempool: https://github.com/ceph/ceph/blob/main/src/include/mempool.h
- PriorityCache: https://github.com/ceph/ceph/blob/main/src/common/PriorityCache.cc
- BlueStore MempoolThread: https://github.com/ceph/ceph/blob/main/src/os/bluestore/BlueStore.cc
- NUMA in the OSD: https://github.com/ceph/ceph/blob/main/src/osd/OSD.cc
- tcmalloc (gperftools): https://github.com/gperftools/gperftools
- perf: https://perfwiki.github.io/main/
- bpftrace: https://github.com/bpftrace/bpftrace
- uftrace: https://github.com/namhyung/uftrace
- Flame graphs: https://www.brendangregg.com/flamegraphs.html
