---
chapter: 30
id: ch30
title: 'Lower Layers (8): Crimson and Seastar — Shard-per-Core OSD and SeaStore'
part: lower
lang: en
---

::: {.tldr}

- Crimson is the new OSD built on Seastar: shard-per-core, no locks or blocking calls, futures and continuations instead.
- Each PG is pinned to one core and operations go through ordered pipeline phases instead of the PG lock.
- Backends are BlueStore (through an adaptor), CyanStore (memory) and SeaStore, a log-structured store for NVMe.
- SeaStore needs segment garbage collection; some monitoring commands exist only on main, so check your release.

:::

# Introduction: why a new OSD? {#sec-30-1}

The classic OSD (chapters 12, 21 and 22) was designed in an era when a spinning disk had a latency of several milliseconds and a few tens of microseconds of software cost were negligible against it. On today's NVMe, a 4K read completes in about 10 to 80 microseconds. In that same time, the classic OSD hands the message from a network thread to a shard queue, from there to another thread holding the PG lock, and then to the kv_sync and finisher threads in BlueStore. Every hand-off between threads costs a context switch, lost processor cache and lock contention. **Crimson** is a rewrite of the OSD on the **Seastar** framework to eliminate these costs: each processor core has one reactor, and each PG lives on only one core.

::: {.note}
**Status.** According to the official documentation (`doc/crimson/crimson.rst` in the main branch and `doc/dev/crimson/crimson.rst` in Squid and Tentacle), Crimson is at the **tech preview** stage and is **not suitable for production**. Enabling it requires three flags: the experimental feature `crimson` in `enable_experimental_unrecoverable_data_corrupting_features`, the OSDMap flag via `ceph osd set-allow-crimson --yes-i-really-mean-it`, and creating pools with the crimson flag (`osd_pool_default_crimson`). Crimson only creates PGs of crimson pools. Everything in this chapter is for understanding the architecture, not a deployment recommendation.
:::

![Comparing the execution models of the classic OSD and Crimson. In the classic OSD each request passes through several thread pools and several locks. In Crimson each core has an independent reactor that runs both the network and its own PGs. Communication between cores happens only through explicit messages (submit_to and invoke_on), and the result returns to the originating core as a future](figures/ch30/f01_threads.png){#fig-30-f01_threads}

This figure shows the fundamental difference between the two models. In the top row, a request moves between threads at least four times, and at each move its data has to be read from another core's cache. In the middle row, the data of a PG (log, object context, cache) lives only in one core's memory and no lock is needed, because no other core touches it. The price of this simplicity is that every interaction between cores must be explicit, such as the message sent to core 0 to find the core that owns a PG.

# Seastar: future, continuation and reactor {#sec-30-2}

In Seastar no function blocks. A function that has asynchronous work (reading from the network, writing to disk, asking another core) immediately returns a `future<T>`. The rest of the work is attached to that future with `.then()`. When the result is ready, the producer makes it ready with `promise.set_value()` and the continuation goes into the task queue of the same reactor. The reactor is an endless loop on each core: it runs ready tasks, polls the I/O backend (io_uring, linux-aio or epoll, chosen with the `crimson_reactor_backend` option) and checks the timers.

![The path of a request on one reactor. No step waits. Every asynchronous operation returns a future, and the continuation is queued on the same core once the result is ready. Because scheduling is cooperative, each task must finish quickly. Crimson sets each task's time slice with crimson_reactor_task_quota_ms (default 0.5 milliseconds in main)](figures/ch30/f02_future.png){#fig-30-f02_future}

::: {.algo #alg-30-1 title="Cooperative scheduling in the Seastar reactor" src="seastar: reactor::run (used in src/crimson/osd/main.cc and the crimson_reactor_* options)" complexity="each round O(number of ready tasks + poll events); lock-free"}
:::

```text
pseudocode: one reactor round (a conceptual model, this book's rewrite)
loop forever:
  t0 = now()
  while ready_tasks not empty and now() - t0 < task_quota:   # 0.5ms
      task = ready_tasks.pop_front(); task.run()             # continuations
  poll(io backend)          # io_uring/aio completion ⇒ promise.set_value ⇒ new task
  poll(network)             # socket data ⇒ new task
  poll(smp queues)          # messages from other cores (submit_to)
  run expired timers
  if nothing to do for idle_poll_time (200us): sleep in kernel (unless poll_mode)
```

**Numerical example.** Suppose each 4K read uses about 15 microseconds of CPU on the reactor (decoding, looking up the object context, building the reply). With a 0.5 millisecond quota, about 33 requests run per round, and then the reactor polls the device and the network again. So the maximum added latency for a new I/O completion is about 0.5 milliseconds. If one bad continuation uses 5 milliseconds of CPU (for example walking a large omap without splitting the work), all the PGs on that core stop for 5 milliseconds. This is the "stall" that Seastar reports in the log. In the cooperative model, long work must be cut into pieces with `seastar::maybe_yield()` or asynchronous loops.

::: {.warn}
`crimson_reactor_idle_poll_time_us=200` means the reactor sleeps in the operating-system kernel after 200 microseconds of idleness. `crimson_poll_mode=true` removes this sleep and polls all the time. In this mode latency is lower, but each reactor keeps one core 100% busy, even with no load. A dashboard showing `osd_reactor_utilization` is always close to 100 in poll mode, and that is no longer a sign of saturation.
:::

## shared-nothing in practice {#sec-30-2-1}

Data shared between cores moves in only three ways: `seastar::smp::submit_to(core, func)` runs a function on another core and returns the result as a future. `sharded<T>` keeps one instance of a service on each core, and `invoke_on` and `invoke_on_all` call it. `foreign_ptr` transfers ownership of an object created on another core so that it is freed on the core that created it. In Crimson, `PGShardMapping` is a `peering_sharded_service`. That is, each core has a local copy of the PG-to-core map, but only core 0 changes it.

# The PG-to-core mapping algorithm {#sec-30-3}

::: {.algo #alg-30-2 title="Choosing the least-loaded core for a new PG" src="src/crimson/osd/pg_map.cc :: PGShardMapping::get_or_create_pg_mapping" complexity="lookup O(log P) with std::map; choice O(C) over C cores; one round trip to core 0"}
:::

![Mapping PGs to cores in Crimson. If a core does not find the PG in its local map, it asks core 0. For a new PG, core 0 chooses the least-loaded core with min_element over the PG count of each core, increments the counter and broadcasts the map to all cores. From then on all the work of that PG runs only on that core](figures/ch30/f03_pgmap.png){#fig-30-f03_pgmap}

```text
pseudocode: get_or_create_pg_mapping (a summary of the code's logic)
on any core:
  if pgid in local.pg_to_core: return local.pg_to_core[pgid]
  return invoke_on(core 0):
     if pgid in primary.pg_to_core: core = that core
     else:
        core = argmin_c primary.core_to_num_pgs[c]    # the least-loaded core
        primary.core_to_num_pgs[core] += 1
        store_index = pick least-loaded store shard on core (if there are several store shards)
        primary.pg_to_core[pgid] = (core, store_index)
     broadcast mapping to all cores; return (core, store_index)
```

**Numerical example.** Consider an OSD with `crimson_cpu_num=4` and cores 0 to 3 holding 30, 29, 31 and 29 PGs respectively. A new PG 2.1f arrives. min_element returns the **first** minimum, so core 1 is chosen (not 3), and the counts become 30, 30, 31 and 29. The next PG goes to core 3. This method balances only the **number** of PGs, not their load. If two hot RBD PGs land on one core, that core saturates while the other cores stay idle, because the shared-nothing model has no work-stealing. This is one of the important practical differences from the classic OSD, where the threads of each shard are shared among that shard's many PGs.

::: {.deep}
The mapping is fixed for the lifetime of the PG on the OSD and can be seen with `ceph tell osd.N dump_store_shards` (the `dump_store_shards` function in the same file). If the number of store shards (for example SeaStore's) is not equal to the number of reactors, the code adds a second layer of least-loaded selection (over `core_alien_to_num_pgs` or `core_shard_to_num_pgs`). The `seastore_require_partition_count_match_reactor_count` option restricts this case.
:::

# The operation pipeline {#sec-30-4}

In the classic OSD, the order of a PG's requests is preserved by the PG lock and the shard queue. Instead of locks, Crimson uses **phases** (`src/crimson/osd/osd_operation.h`). Each phase is either **OrderedExclusive**, meaning only one operation is in it at any moment and the order of arrival is preserved, or **OrderedConcurrent**, meaning several operations are in it at once but they leave in the same order.

![The phases of a ClientRequest in Crimson. The connection level (waiting to become active, getting the map and finding the PG's core), the shard level (creating or waiting for the PG), the PG level (PG ready, OSDMap version gate, PG active and getting the object context) and the object level (processing, waiting for scrub, waiting for replication to the replicas and sending the reply). Exclusive phases guarantee order, and concurrent ones make overlap possible](figures/ch30/f04_pipeline.png){#fig-30-f04_pipeline}

| phase | Type | What it guarantees |
|---|---|---|
| ConnectionPipeline::AwaitActive / AwaitMap / GetPGMapping | exclusive | the order of a connection's messages until they reach the PG's core |
| PerShardPipeline::CreateOrWaitPG | exclusive | the PG is created only once |
| CommonPGPipeline::WaitPGReady | concurrent | waiting for the PG to be ready without breaking order |
| CommonPGPipeline::GetOBC | exclusive | the order of getting the object context (equivalent to an object lock) |
| CommonOBCPipeline::Process | exclusive | running the ops on the object in arrival order |
| CommonOBCPipeline::WaitRepop | concurrent | several concurrent writes waiting for acks from the replicas |
| CommonOBCPipeline::SendReply | exclusive | replies in the order of the requests |

**Latency reasoning.** Because WaitRepop is concurrent, 32 consecutive writes to one object can wait for the replicas at the same time. If the round trip to a replica is 200 microseconds and processing each write is 20 microseconds, the throughput of one object is about 1/20µs=50K writes per second, not 1/220µs. If Process blocks (for example waiting to read the object context from disk), the whole queue of the object waits behind it. That is why `crimson_osd_obc_lru_size=512` (the size of the object-context cache) matters a lot for random load.

# Storage backends in Crimson {#sec-30-5}

Crimson's storage interface is `FuturizedStore` (`src/crimson/os/futurized_store.h`). Each operation returns a future instead of a value. There are three implementations in `src/crimson/os/`:

![Crimson's storage backends. SeaStore and CyanStore are native and run directly on the reactor. AlienStore runs the classic BlueStore or MemStore in "alien" threads (outside Seastar). The request is sent from the reactor to a thread pool, and the result returns to the originating core with seastar::alien::submit_to](figures/ch30/f05_backends.png){#fig-30-f05_backends}

| Backend | Execution | Use | Status (main documentation) |
|---|---|---|---|
| SeaStore | native, on the reactor | a new design for NVMe | "early", not the default |
| CyanStore | native, in memory | measuring the overhead of the OSD itself; **stores no data** | testing only |
| AlienStore + BlueStore | alien thread pool | the default; compatible with HDD and SSD | the default in Crimson |
| AlienStore + MemStore | alien thread pool | testing and development | testing only |

In `alien_store.cc`, the thread pool is built with `crimson_bluestore_num_threads` (default 6 in main). The operations of one collection always go to a specific thread via `ch->get_cid().hash_to_shard(tp->size())`, so that the order of a PG's transactions is preserved. This is the same role the shard queue plays in the classic OSD.

::: {.warn}
**The hidden cost of AlienStore.** Each operation crosses the reactor/thread boundary twice (out to the pool and back with alien::submit_to). On fast NVMe, these two transfers and BlueStore's work in its own threads wipe out a large part of Crimson's gain. That is why the documentation recommends keeping BlueStore's CPU set (`crimson_bluestore_cpu_set`) separate from the reactor cores (`crimson_cpu_set`), so that the alien threads do not compete with the reactors.
:::

# SeaStore: architecture {#sec-30-6}

SeaStore is a **log-structured**, transactional ObjectStore. No data is overwritten in place, except in the random block (RBM) backend. Each transaction becomes a **record** in the journal that contains the deltas (logical changes to blocks) and the new blocks.

![The layers of SeaStore. The logical managers (onode with the FLTree, omap and xattr with a BTree, object data and collections) work on the logical address laddr. The TransactionManager gathers the changes in a Transaction and commits them as one atomic record. The LBAManager keeps the laddr-to-paddr mapping in a B-tree, and the BackrefManager keeps the reverse mapping for GC. The Journal, ExtentPlacementManager, Cache and AsyncCleaner work on segmented, RBM or ZBD devices](figures/ch30/f06_seastore.png){#fig-30-f06_seastore}

SeaStore has two kinds of address. **laddr** is the logical address that onodes and the omap trees point to, and it does not change when GC moves a block. **paddr** is the physical address. The only structure that has to be updated when a block moves is the LBA tree. This design bounds the cost of GC: moving a data block changes only one leaf entry in the LBA tree, not all the pointers to it.

## paddr_t bit by bit {#sec-30-6-1}

![The 64-bit structure of paddr_t in seastore_types.h. The top eight bits are the device_id (DEVICE_ID_BITS = digits(uint8_t) = 8). On a segmented device, the next 24 bits are the segment number within the device and the low 32 bits are the offset within the segment. On RBM, the low 56 bits are an absolute offset. The top seven device_id values are reserved for symbolic addresses such as an offset relative to a record or a delayed address](figures/ch30/f07_paddr.png){#fig-30-f07_paddr}

**Relative** addresses (`DEVICE_ID_RECORD_RELATIVE` and `DEVICE_ID_BLOCK_RELATIVE`) have a subtle point. When a transaction is built, it is not yet known where in the journal its record will be placed. So the new blocks are named with an offset relative to the start of the record, and when the record is written these addresses are converted to absolute paddrs. `DEVICE_ID_DELAYED` is for blocks whose location has not been decided by the ExtentPlacementManager until the moment of commit (out-of-line writes).

## Records and batching in the journal {#sec-30-6-2}

![The structure of a journal segment and a record group. Each record group is committed with one disk write and contains a record_group_header_t (number of records, metadata and data length, segment nonce, committed_to and the data crc), then the header of each record (transaction type, number of deltas and extents, modification time), the deltas and the inline extents. RecordSubmitter gathers up to 16 records in a batch and keeps at most 5 concurrent writes on the journal (the main defaults)](figures/ch30/f09_record.png){#fig-30-f09_record}

::: {.algo #alg-30-3 title="Batching records in RecordSubmitter" src="src/crimson/os/seastore/journal/record_submitter.cc :: RecordSubmitter::submit / flush_current_batch" complexity="each record O(size) to encode; latency at worst one batch"}
:::

```text
pseudocode: journal batching (a conceptual model)
submit(record):
  if current_batch can fit record and batch.size < batch_capacity(16):
      current_batch.add(record)
  else: flush_current_batch(); current_batch.add(record)
  if outstanding_ios < iodepth_limit(5): flush_current_batch()      # the disk is idle: do not wait
  else: wait (the batch grows until one of the writes finishes)
flush_current_batch():
  header = record_group_header_t{records=n, mdlength, dlength, segment_nonce,
                                 committed_to = the last point at which all earlier ones are complete,
                                 data_crc = crc(data)}
  write(header + metadata + data) as ONE aligned I/O
```

**Numerical example.** Suppose 40 small transactions (each a delta on an onode plus 4K of data) arrive at the same time and the disk completes each write in 20 microseconds. The first five records each become a separate write, because the disk queue is empty. Once the limit of 5 concurrent writes is reached, the rest are gathered in batches of up to 16. The remaining 35 records are committed in 3 writes (16+16+3). In total 8 writes are done instead of 40, and the largest added latency for any record is less than twice the time of one write. This is the same group-commit trade-off as `kv_sync_thread` in BlueStore, except that it is implemented without a separate thread, using only futures.

::: {.note}
**Version-dependent.** In Squid, `seastore_max_concurrent_transactions` is 8 and in main it is 128. The option names have also changed: Squid and Tentacle use `crimson_seastar_num_threads` and `crimson_alien_op_num_threads`, and main uses `crimson_cpu_num` and `crimson_bluestore_num_threads`. The cache in Squid was set with `seastore_cache_lru_size=64M`, and in main with `seastore_cachepin_size_pershard=2G` and a choice of LRU or 2Q. Before any experiment, run `ceph config help` on your own version.
:::

## The states of an extent in the cache {#sec-30-6-3}

![The extent state machine in SeaStore's Cache. A new extent is created in INITIAL_WRITE_PENDING and becomes CLEAN after commit. Modifying an existing extent creates a version in MUTATION_PENDING that becomes DIRTY after commit, with the delta recorded in the journal (the in-memory content differs from disk and is pinned in memory). Extents whose metadata has not been committed yet are EXIST_CLEAN and EXIST_MUTATION_PENDING. DIRTY extents become CLEAN again when they are rewritten by the cleaner or by the journal trim](figures/ch30/f08_extstate.png){#fig-30-f08_extstate}

The important point of this state machine is **optimistic concurrency control**. Each transaction keeps the extents it has read in a `read_set`. If another transaction modifies one of them before commit, `Cache::mark_transaction_conflicted` invalidates the first transaction and it has to run again from scratch. The SeaStore documentation notes that this mechanism has a high retry rate under heavy write loads and that its removal is planned. This is one of the reasons for SeaStore's "early" status.

# Segment GC: choosing the victim segment {#sec-30-7}

On a segmented device, every byte written must eventually be paid for by "cleaning" an old segment: the live data of that segment is moved to a new segment and the segment is freed. The key question is which segment to choose.

::: {.algo #alg-30-4 title="Choosing a segment to reclaim (greedy / cost-benefit / benefit)" src="src/crimson/os/seastore/async_cleaner.cc :: SegmentCleaner::calc_gc_benefit_cost, get_next_reclaim_segment" complexity="O(S) over S closed segments per choice"}
:::

```text
pseudocode: get_next_reclaim_segment (summary)
for each closed segment s:
   u = live_bytes(s) / segment_size                      # 0 ≤ u < 1
   score(s) = greedy:       1 - u
              cost_benefit: (1 - u) × age(s) / (2u)        # u=0 ⇒ +∞
              benefit:      a combination of (1-u) with a normalized age factor
pick = argmax score;  greedy_pick = argmin u
if autotune and formula ≠ greedy and (1-u_greedy) ≥ ratio(2.0) × (1-u_pick):
   pick = greedy_pick                                     # the age-based formula got it wrong
```

The cost-benefit formula is the classic formula of log-structured file systems (LFS). The benefit of cleaning a segment is proportional to the space freed (1-u) and its "stability" (age), and its cost is reading u and writing u (that is, 2u). An old segment with little live data is the best choice, because its remaining data is probably "cold" and will not die again soon.

**Numerical example.** We have three closed segments:

| Segment | u (live fraction) | Age (seconds) | greedy = 1-u | cost-benefit = $(1-u) \cdot \mathit{age} / (2u)$ |
|---|---|---|---|---|
| A | 0.2 | 100 | **0.8** | 200 |
| B | 0.5 | 1000 | 0.5 | 500 |
| C | 0.9 | 10000 | 0.1 | **555.6** |

The cost-benefit formula chooses segment C, because it is very old. But cleaning C frees only 10% of the space and 90% of it has to be moved. autotune checks this: greedy's free fraction (0.8) is at least 2 times the free fraction of the formula's choice (0.1), so the choice goes back to A. If C were not there, the formula would choose B with a score of 500. The ratio 0.8/0.5=1.6 is less than 2, so the formula's choice would be kept. These options (`seastore_segment_cleaner_gc_formula=cost_benefit`, `seastore_segment_cleaner_gc_autotune=true` and `ratio=2.0`) are in main and do not appear in the Squid and Tentacle yaml.

**Write-amplification reasoning.** If, in the steady state, the cleaner cleans segments with an average u=0.5, then for every 1 byte freed 1 byte has to be rewritten, and WA is about 2. With u=0.2, 0.2 bytes are moved for every 0.8 bytes freed, and WA is about 1.25. So reserving more free space on the device lowers the u of the victim segments and improves both the NVMe's lifetime and the write latency.

# Measuring and monitoring Crimson {#sec-30-8}

```bash {since=main}
ceph tell osd.0 dump_metrics reactor_utilization     # utilization of each reactor (shard)
ceph tell osd.0 dump_store_shards                    # mapping of PGs and store shards to cores
ceph config set osd crimson_prometheus_port_base 29180   # main: osd.N on 29180+N
curl -s http://HOST:29180/metrics | grep osd_reactor_utilization
ceph osd dump | grep -E 'allow_crimson|crimson'          # map and pool flags
```

::: {.debug}
If one reactor is close to 100% and the rest are lightly loaded, (1) check poll_mode, (2) use `dump_store_shards` to see which PGs are on that core, and (3) compare the load of each PG with `ceph pg dump pgs`. In Crimson the solution is to redistribute the PGs (increase pg_num or use upmap), not to add threads.
:::

# Supplementary and up to date {#sec-30-9}

- In the main branch, the Crimson user documentation has moved from `doc/dev/crimson/` to `doc/crimson/crimson.rst`, and deployment is described with `ceph orch apply osd --osd-type crimson`, and for SeaStore with `--objectstore seastore`. In Squid and Tentacle these commands are not in the documentation.
- `crimson_cpu_num` has no default and cannot be changed after deployment. The documentation recommends setting it below nproc divided by the number of OSDs on the host.
- io_uring is the reactor's default backend, if the kernel allows it (`kernel.io_uring_disabled`). On some conservative distributions it has to be enabled explicitly.
- SeaStore is not suitable for HDD (according to the documentation). For HDD and slow SSDs, Crimson still supports BlueStore through AlienStore.

# Hands-on exercise {#sec-30-10}

1. Build a Crimson cluster with vstart (`MDS=0 MON=1 OSD=1 ../src/vstart.sh -n --crimson --crimson-smp 2`). Compare `dump_metrics reactor_utilization` before and after `rados bench`.
2. Compare CyanStore with AlienStore+BlueStore under a random 4K load. The latency difference is the cost of the store, and CyanStore's latency is the overhead of the OSD itself.
3. With four PGs in a pool and two reactors, look at the mapping with `dump_store_shards` and compare it with this chapter's example.
4. Make up three segments with arbitrary u and age and compute the greedy and cost-benefit scores and the autotune result by hand.

# Review questions {#sec-30-11}

1. Why is the thread-pool model of the classic OSD expensive on NVMe?
2. How do futures and continuations in Seastar replace blocking?
3. What does crimson_reactor_task_quota_ms limit, and what is the effect of a long continuation?
4. How is a new PG assigned to a core, and what is the weakness of this method?
5. Explain the difference between exclusive and concurrent phases with the WaitRepop example.
6. Why is AlienStore needed, and what does it cost?
7. How do laddr and paddr differ in SeaStore, and why does this separation reduce the cost of GC?
8. Describe the 64-bit structure of paddr_t for segments and for RBM.
9. Write the cost-benefit formula and explain autotune with an example.
10. Which three flags are needed to enable Crimson?

# Sources for this chapter {#sec-30-12}

- Crimson in the documentation (main): https://github.com/ceph/ceph/blob/main/doc/crimson/crimson.rst
- Crimson developer guide: https://github.com/ceph/ceph/blob/main/doc/dev/crimson/index.rst
- SeaStore design: https://github.com/ceph/ceph/blob/main/doc/dev/crimson/seastore.rst
- Crimson code: https://github.com/ceph/ceph/tree/main/src/crimson
- Crimson options: https://github.com/ceph/ceph/blob/main/src/common/options/crimson.yaml.in
- Seastar: https://seastar.io/
- Seastar tutorial: https://github.com/scylladb/seastar/blob/master/doc/tutorial.md
- The Crimson project on the Ceph blog: https://ceph.io/en/news/crimson/
- Rosenblum and Ousterhout, The Design and Implementation of a Log-Structured File System (1992): https://people.eecs.berkeley.edu/~brewer/cs262/LFS.pdf
