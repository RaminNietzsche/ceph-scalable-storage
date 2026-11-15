---
chapter: 31
id: ch31
title: 'Lower Layers (9): SPDK and NVMe — from Hardware Queues to the NVMe-oF Gateway'
part: lower
lang: en
---

# Why this chapter? {#sec-31-1}

In the previous chapters, the lowest layer we saw was `KernelDevice` in BlueStore, which hands requests to the kernel with libaio or io_uring. This chapter goes one layer lower: the **NVMe hardware queues** themselves, the bytes of a command and of a completion, the doorbells and the Phase Tag. Then we examine the two places where Ceph bypasses the kernel with **SPDK** (Storage Performance Development Kit):

- **NVMEDevice** in BlueStore (`src/blk/spdk/NVMEDevice.cc`): a user-space driver for a local device or an NVMe-oF target.
- **The NVMe-oF gateway** (the ceph-nvmeof project): an SPDK-based NVMe/TCP target that exports RBD images to hosts. Its management side in the mon is implemented with `NVMeofGwMon` and `NVMeofGwMap`.

::: {.note}
**Status.** The `bluestore_spdk_*` options are at the `dev` level in the code. SPDK support in BlueStore is still a tool for testing and research and is not the usual path in a cephadm deployment. The NVMe-oF gateway, however, is documented and supported with `ceph orch apply nvmeof`. All code references in this chapter are to the main branch at the time of writing.
:::

# NVMe from the driver's point of view {#sec-31-2}

## Two data paths {#sec-31-2-1}

![Comparing the two paths from BlueStore to the NVMe controller. In the kernel path, the request passes through a syscall, the blk-mq layer and the nvme-pci driver, and completion is reported with an MSI-X interrupt. In the SPDK path all this work is done in user space: the SPDK driver writes the SQE into the queue itself, updates the doorbell through the device's mapped BAR and finds the completion by polling. Both paths meet at the same hardware structure (SQ and CQ in host memory)](figures/ch31/f01_paths.png){#fig-31-f01_paths}

The NVMe controller talks to the host through **queue pairs**: a **Submission Queue** (SQ) into which the host writes commands and a **Completion Queue** (CQ) into which the controller puts the results. Both are ring arrays in host memory. The Linux kernel driver usually creates one queue pair per CPU. That is why two CPU cores do not compete to submit commands on one queue.

## The bytes of a command {#sec-31-2-2}

![The 64-byte structure of a Read/Write command in the submission queue, with the values of a 4 KiB read from offset 1 GiB. opcode=0x02 means Read (0x01 is Write). command_id is an identifier the driver chooses and the controller returns in the CQE. slba is the starting logical address in blocks, and length is the number of blocks, zero-based. prp1 and prp2 are the physical addresses (or IOVAs behind the IOMMU) of the data pages](figures/ch31/f02_sqe.png){#fig-31-f02_sqe}

Two low-level points in this structure matter:

1. **Zero-based length.** A value of 0 in `length` means one block. Off-by-one errors are common in experimental drivers.
2. **PRPs and pages.** PRP1 points to the first page (it may have an offset within the page). If the data spans more than two pages, PRP2 points to a **PRP list**. Each entry is 8 bytes, so one 4 KiB page holds a list of 512 pages. For an aligned 8 KB I/O, PRP1 is the first page and PRP2 the second, and no list is needed. For 128 KiB (32 pages), PRP2 points to a list with 31 entries.

## The bytes of a completion {#sec-31-2-3}

![The 16-byte structure of a completion queue entry. sq_head tells the host how far into the SQ the controller has read. sq_id and command_id together identify the command uniquely. Bit zero of the status field is the Phase Tag: the controller writes it as 1 on the first pass through the queue, 0 on the second, and so on](figures/ch31/f03_cqe.png){#fig-31-f03_cqe}

::: {.algo #alg-31-1 title="Detecting completion with the Phase Tag (walking the CQ)" src="linux: drivers/nvme/host/pci.c :: nvme_poll_cq, nvme_cqe_pending, nvme_update_cq_head" complexity="O(k) for k new completions; one MMIO write at the end"}
:::

```text
pseudocode (taken from the logic of nvme_poll_cq, rewritten)
found = false
while (cqes[cq_head].status & 1) == cq_phase:     # a new entry?
    found = true
    dma_rmb()                                      # read the rest of the CQE after the phase
    handle(cqes[cq_head])                          # command_id ⇒ request ⇒ completion
    cq_head += 1
    if cq_head == q_depth: cq_head = 0; cq_phase ^= 1
if found: writel(cq_head, CQ_HEAD_DOORBELL)        # once for the whole batch
```

**Why a Phase Tag?** The CQ is filled with zeros before starting, and the host's `cq_phase` starts at 1. On the first pass the controller writes CQEs with P=1, so any slot whose P is 1 is new. When the queue wraps around a full cycle, the old slots have P=1 and this time the controller writes P=0. The host likewise flips `cq_phase` to change its criterion for "new". So the host knows what has arrived without reading any register from the device, just by reading its own memory. This property is what makes polling cheap: an empty poll is just one read from cache.

**Numerical example.** q_depth=4, cq_head=2, cq_phase=1. The controller completes three commands and writes them in slots 2 and 3 with P=1 and in slot 0 with P=0 (a new pass). The host processes slot 2 (P=1, new) and slot 3 (new) and reaches the end of the queue: cq_head=0 and cq_phase=0. Slot 0 with P=0 is new and is processed. Slot 1 still has the old P=1, so the loop stops and one doorbell with value 1 is written. Three completions were reported with one MMIO write.

## Doorbells and the cost of MMIO {#sec-31-2-4}

![The full sequence of a command: writing the SQE into slot sq_tail, updating the SQ Tail Doorbell, the controller fetching and executing the command, writing the CQE, an interrupt (or polling), walking the CQ and updating the CQ Head Doorbell. The doorbell offsets are derived from the CAP.DSTRD register](figures/ch31/f04_rings.png){#fig-31-f04_rings}

The doorbell offsets in the controller's register space (BAR0) come from the standard NVMe formula: `SQyTDBL = 0x1000 + (2y) × (4 << CAP.DSTRD)` and `CQyHDBL = 0x1000 + (2y+1) × (4 << CAP.DSTRD)`. For queue 3 with DSTRD=0, the SQ doorbell is at 0x1018 and the CQ doorbell at 0x101C. Each doorbell is an uncacheable MMIO write that crosses PCIe. That is why the kernel, in `nvme_write_sq_db`, defers the doorbell write until the last request of a batch (the `write_sq` parameter and `last_sq_tail`), and `nvme_commit_rqs` writes it at the end of the batch. The **Doorbell Buffer Config** feature (in the kernel, `nvme_dbbuf_update_and_check_event`) eliminates even this write on virtual controllers, if the device declares it unnecessary.

::: {.deep}
**Locks in the kernel path.** `nvme_sq_copy_cmd` and `nvme_write_sq_db` are annotated with `__must_hold(&nvmeq->sq_lock)`: copying the 64 bytes and advancing sq_tail happen under a spinlock specific to that queue. Because each CPU usually has its own queue, this lock is almost never contended. The completion path also runs in the interrupt context of the same queue and takes no lock on the CQ.
:::

# NVMEDevice: SPDK in BlueStore, function by function {#sec-31-3}

## Configuration and opening {#sec-31-3-1}

When the device file name starts with `spdk:` (`SPDK_PREFIX` in `BlockDevice.h`), BlueStore uses `NVMEDevice` instead of `KernelDevice`. The BlueStore documentation shows two forms:

```ini
bluestore_block_path = "spdk:trtype:PCIe traddr:0000:01:00.0"
bluestore_block_path = "spdk:trtype:TCP adrfam:IPv4 traddr:10.0.0.7 trsvcid:4420 subnqn:nqn.2019-02.io.spdk:cnode1"
# so that DB and WAL also go through SPDK (co-located):
bluestore_block_db_path = ""
bluestore_block_wal_path = ""
```

![The NVMEDevice code path in three stages. On open, the transport ID string is read from the file and parsed with spdk_nvme_transport_id_parse. NVMEManager creates a separate thread for the DPDK environment and the probe. On write, the data is split into 128 KiB pieces and collected in a linked list of Tasks in the IOContext. aio_submit sends the commands on a qpair dedicated to that thread (thread_local). The completion is found by polling on the same thread, and the DMA buffers return to the pool](figures/ch31/f05_nvmedev.png){#fig-31-f05_nvmedev}

| Function | Work | Thread and lock |
|---|---|---|
| NVMEDevice::open | read the trid line, spdk_nvme_transport_id_parse, manager.try_get | the opening thread; NVMEManager::lock |
| NVMEManager::try_get | first time: create dpdk_thread with spdk_env_init (coremask, mem_size), the probe queue | probe_queue_lock and probe_queue_cond |
| probe_cb / attach_cb | match the trid, register_ctrlr | the DPDK thread |
| register_ctrlr | only namespace number 1; "only one device per OSD for now" (ceph_assert) | under NVMEManager::lock |
| SharedDriverData | for a non-PCIe transport, an admin_thread that processes admin completions every 1 second (keep-alive) | a separate thread |
| aio_write ⇒ write_split | 131072-byte pieces, bl.splice into the Task | the calling thread |
| aio_submit | num_pending ⇒ num_running; thread_local SharedDriverQueueData | lock-free: a qpair dedicated to that thread |
| _aio_handle | submit the Tasks and poll until num_running is zero | the same thread, busy-poll |
| io_complete | decrement the queue depth, release_segs, aio_callback | the same thread (inside process_completions) |

## The DMA buffer pool and request splitting {#sec-31-3-2}

SPDK cannot use the ordinary memory of a bufferlist directly. For DMA, the controller needs memory that is pinned and whose physical address or IOVA is known (DPDK hugepages). So `SharedDriverQueueData` creates, in its constructor, 1024 buffers of 8 KB with `spdk_dma_zmalloc` (`data_buffer_default_num` and `data_buffer_size`). The data of each write is **copied** into these buffers. The code comment (a TODO) itself says this copy could be removed if the upper layer provided memory with a known physical address.

::: {.algo #alg-31-2 title="I/O splitting and DMA buffer allocation in NVMEDevice" src="src/blk/spdk/NVMEDevice.cc :: write_split, make_read_tasks, SharedDriverQueueData::alloc_buf_from_pool" complexity="O(len/8K) for copying and allocation; a fixed 8 MiB of space per thread"}
:::

```text
pseudocode
write_split(off, bl):
    while remaining > 0:
        n = min(remaining, 128 KiB)
        task = Task(WRITE, off+begin, n); bl.splice(0, n, task.bl); append(ioc, task)
alloc_buf_from_pool(task):
    count = ceil(task.len / 8 KiB)
    if count > free_buffers: return -ENOMEM        # _aio_handle polls again (goto again)
    segs = count ≤ 32 ? task.inline_segs : new void*[count]
    pop count buffers; copy task.bl into them (write)
submit: spdk_nvme_ns_cmd_writev(ns, qpair, off/bs, len/bs, io_complete, task,
                                reset_sgl=data_buf_reset_sgl, next_sge=data_buf_next_sge)
```

**Numerical example.** A 300 KiB (307200-byte) write with a 4096-byte block:

| Task | Relative offset | Length | lba_count | 8 KiB buffers |
|---|---|---|---|---|
| 1 | 0 | 131072 | 32 | 16 |
| 2 | 131072 | 131072 | 32 | 16 |
| 3 | 262144 | 45056 | 11 | 6 (five full + one with 4096 bytes) |

In total, 3 NVMe commands and 38 of the 1024 buffers. Because each Task is at most 128 KiB, the number of buffers never exceeds 16 and always fits in the 32 slots of `inline_segs`. The `extra_segs` branch is effectively unused for this split size. SPDK gets the scatter-gather list from the Task through two callbacks: `data_buf_next_sge` returns the next buffer with length 8192 (or the final remainder, here 4096), and `data_buf_reset_sgl` is for replaying from an offset. A pool of 1024 buffers means at most 8 MiB of data in flight per thread. A batch larger than this returns to the polling loop with `-ENOMEM` until buffers are freed.

## Synchronous polling in the calling thread {#sec-31-3-3}

The most important behavioural point of this driver is in `_aio_handle`: the outer loop `while (ioc->num_running)` continues until **all** the I/Os of this IOContext have completed. So, unlike KernelDevice, `aio_submit` in NVMEDevice does not just submit; it holds the thread until completion. If `process_completions` finds nothing, the thread sleeps with usleep for `bluestore_spdk_io_sleep` (default 5 microseconds). `bluestore_spdk_max_io_completion` (default 0, meaning SPDK decides) limits the number of completions per poll.

::: {.warn}
**The consequence for BlueStore.** In KernelDevice, a separate aio thread collects the completions, and kv_sync_thread or the op thread only submits. In NVMEDevice, every thread that calls `aio_submit` waits until its own I/O finishes. With `thread_local`, each thread has a dedicated qpair, which removes contention, but every new thread that submits I/O consumes 1024 DMA buffers (8 MiB) and one qpair. The total can be calculated: if 16 different threads (op shards, kv_sync, BlueFS) submit I/O, 128 MiB of DPDK memory, which is limited by `bluestore_spdk_mem=512` (MB), goes to these buffers alone.
:::

**Latency reasoning.** Consider a random 4 KiB read on a sample SSD with an internal latency of 80 microseconds. In the kernel path, suppose 2 to 5 microseconds are added for the syscall, blk-mq, the interrupt and waking the thread. SPDK removes a large part of this, but adds 0 to 5 microseconds of usleep when idle and the copy into the DMA buffer (negligible for 4 KiB, a few microseconds for 128 KiB). SPDK's gain is more in **CPU per I/O** than in latency. When the device latency is in the tens of microseconds, a few microseconds of software in the BlueStore layer are small compared with the cost of the OSD (chapters 22 and 30).

::: {.algo #alg-31-3 title="Little's law for the required queue depth" src="a queueing-theory result; in the code: max_queue_depth = io_queue_size − 1 in SharedDriverQueueData" complexity="O(1)"}
:::

```text
QD_needed = target_IOPS × latency
```

For 500K IOPS with a latency of 80 microseconds: `QD = 500000 × 0.00008 = 40` concurrent requests. If I/O comes from only one thread with one IOContext that submits everything in one batch and waits for all of it to complete, the effective QD is just the size of that batch. To reach 40, either the batches must be large or several threads must work concurrently. The same calculation shows why running several OSDs on one fast NVMe, or more shards, sometimes has more effect than changing the driver.

# The NVMe-oF gateway {#sec-31-4}

## Architecture {#sec-31-4-1}

![The components of the NVMe-oF gateway. The SPDK target (nvmf_tgt) receives NVMe/TCP commands from the host and hands each namespace to a bdev of type rbd. This bdev works with asynchronous librbd (rbd_aio_readv and rbd_aio_writev). The gateway's gRPC service keeps its configuration in an omap object in RADOS. NVMeofGwMonitorClient talks to the mon and gets the ANA state of each group from NVMeofGwMap](figures/ch31/f07_gw.png){#fig-31-f07_gw}

The Ceph documentation describes the gateway as an NVMe/TCP target that exports RBD images. Each gateway also runs a Discovery Controller. The scale figures the main documentation gives are: up to 4 gateway groups, 8 gateways per group, 128 subsystems per group, 32 hosts per subsystem and 1024 namespaces per group. The suggested minimum resources are 8 GB of memory and four processor threads per gateway instance.

::: {.note}
**Version-dependent.** These limits are taken from the main documentation. The sample configuration of the ceph-nvmeof project's devel branch shows options such as `max_subsystems = 128`, `max_namespaces = 4096` and `max_gws_in_grp = 16`. Before capacity planning, read the documentation of the version you are installing.
:::

## The path of a write from the host to the OSD {#sec-31-4-2}

![The bytes of NVMe/TCP. Each PDU starts with an 8-byte common header (type, flags, hlen, pdo, plen). The Command Capsule carries the same 64-byte SQE, and if the data is smaller than in_capsule_data_size, the data also comes inside the capsule. For larger data, the target grants permission to send with an R2T and the host sends the data in H2CData](figures/ch31/f06_tcppdu.png){#fig-31-f06_tcppdu}

1. The host (`nvme_tcp` in the kernel) sends a Command Capsule with the Write opcode. The gateway's sample configuration sets `in_capsule_data_size` to 8192, so a 4 KiB write fits in one PDU with plen=4168.
2. The SPDK reactor polls the socket of that qpair, parses the PDU and hands the command to the bdev.
3. `bdev_rbd` hands the request to librbd with `rbd_aio_create_completion` and `rbd_aio_writev`. From here the path is the librbd path (chapters 2 and 22): ObjectRequest, Objecter and MOSDOp.
4. The librbd callback runs in librbd's own threads, not in the SPDK reactor. `bdev_rbd_io_complete` uses `spdk_thread_send_msg` to return the completion to the submitting thread (`submit_td`), so that SPDK's single-threaded model is preserved.
5. The reactor returns a Response Capsule.

**Latency budget (a hypothetical example, 4 KiB, 25-gigabit network).** The host-to-gateway round trip is about 20 to 40 microseconds, SPDK processing a few microseconds, two thread-boundary crossings (librbd to the reactor and back) a few microseconds, and the librbd path to the OSD and the replicas (usually 0.5 to 2 milliseconds in NVMe clusters). So the NVMe-oF gateway usually adds **one extra network round trip** to the direct krbd or librbd path. Its benefit is compatibility with hosts that have no Ceph client (for example VMware) and standard multipath, not lower latency.

## ANA and failover in the mon {#sec-31-4-3}

For HA, NVMe-oF uses **ANA** (Asymmetric Namespace Access). Each namespace belongs to an **ANA group** (a load-balancing group). At any moment only one gateway is "optimized" for that group, and the rest are reported as "inaccessible". The host's multipath sends I/O only to the optimized path. The number of load-balancing groups equals the number of gateways in the group.

![The state machine of each gateway for each ANA group in gw_states_per_group_t (NVMeofGwTypes.h): IDLE, STANDBY, ACTIVE, OWNER_WAIT_FAILBACK_PREPARED, WAIT_FAILBACK_PREPARED and WAIT_BLOCKLIST_CMPL. The state exported to the host has only two values: OPTIMIZED for ACTIVE and WAIT_BLOCKLIST_CMPL, and INACCESSIBLE for the rest](figures/ch31/f08_anafsm.png){#fig-31-f08_anafsm}

**Why WAIT_BLOCKLIST_CMPL?** Before gateway B takes over the group of failed gateway A, we must be sure that A (if it is only cut off from the mon and still alive) can no longer write to the RBD images. Otherwise two gateways would write to one namespace at the same time. `set_failover_gw_for_ANA_group` blocklists A's addresses in the OSDMap with `blocklist_gw` and keeps its epoch in `blocklist_data[grp].osd_epoch`. B becomes ACTIVE only when its beacon shows it has seen an OSDMap with an equal or larger epoch (`fsm_handle_gw_alive`). This is the same blocklist-fencing pattern we saw in RBD's exclusive lock and in rbd-mirror (chapters 2 and 18).

![The failover sequence. After mon_nvmeofgw_beacon_grace (default 7 seconds) without a beacon, gateway A is declared unavailable. find_failover_candidate finds the least-loaded gateway, A is blocklisted and B is put in WAIT_BLOCKLIST_CMPL with a 30-second timer. When the new OSDMap reaches B, the group becomes active for B and the host's ANA is updated](figures/ch31/f09_failover.png){#fig-31-f09_failover}

::: {.algo #alg-31-4 title="Choosing the replacement gateway (least loaded, with location priority)" src="src/mon/NVMeofGwMap.cc :: NVMeofGwMap::find_failover_candidate, find_failover_gw_logic" complexity="O(G × A) for G gateways and A ANA groups"}
:::

```text
pseudocode
find_failover_gw_logic(gws, location, ignore_locations):
    best = none; best_load = 0xFFF; busy = 0
    for gw in gws (in id order):
        if not AVAILABLE or (not ignore_locations and gw.location ≠ location): continue
        if location(gw) in disaster: continue
        load = 0
        for grp in gw.sm_state:
            if state in {OWNER_WAIT_FAILBACK_PREPARED, WAIT_FAILBACK_PREPARED, WAIT_BLOCKLIST_CMPL}:
                load = 0xFFFF; busy += 1; break           # in transition: excluded
            if state == ACTIVE: load += 1
        if load < best_load: best, best_load = gw, load
    return best ? 0 : (busy ? -EBUSY : -ENOENT)
find_failover_candidate: first with the group's own location; if -ENOENT, with ignore_locations=true
```

**Numerical example.** We have a gateway group with four gateways in two locations: A and B in L1, and C and D in L2. The active ANA groups are: A={1}, B={2, 5}, C={3}, D={4}. A is lost, and group 1 is in L1. In the first round only B in L1 is available, with load 2, so B is chosen, even though C and D have less load. This decision is deliberate: the traffic stays in the same location. If B had been in WAIT_FAILBACK_PREPARED for another group at that moment, its load would have been 0xFFFF and the result of the first round -EBUSY. Because -EBUSY is different from -ENOENT, the second round does not run, and the failover is postponed until B's transition ends. If B had also failed (-ENOENT), the second round, between C and D (both with load 1), would choose the first in id order, that is C, because the comparison is strict (`>`).

| Option (mon.yaml.in, main) | Default | Meaning |
|---|---|---|
| mon_nvmeofgw_beacon_grace | 7 seconds | silence after which the gateway is declared failed |
| mon_nvmeofgw_skip_failovers_interval | 16 seconds | a period during which no failover is done in that pool and group |
| mon_nvmeofgw_beacons_till_ack | 15 | the number of beacons from MonClient before NVMeofGwMon sends an ack map |
| mon_nvmeofgw_max_down_gws | 1 | the ok-to-stop command checks that no more than this many gateways are down (preventing all of them from stopping during an upgrade) |
| mon_nvmeofgw_delete_grace | 15 minutes | after this time, the NVMEOF_GATEWAY_DELETING health warning is raised |
| mon_nvmeofgw_failback_delay | 0 | the failback delay after the owner comes back |

**Calculating the I/O interruption during failover.** In the worst case: 7 seconds until the failure is declared, plus the time of one Paxos proposal for the blocklist (usually under a second), plus the OSDMap reaching B and its next beacon. So the host must tolerate a few seconds, up to ten-odd seconds, of suspended I/O. The documentation recommends passing `-l 1800` (ctrl-loss-tmo of 1800 seconds) to `nvme connect-all` so that the host does not give up the path in the meantime.

# Practical commands {#sec-31-5}

```bash {since=tentacle}
# the gateway (main documentation)
ceph orch apply nvmeof POOL GROUP --placement="host01, host02"
ceph nvmeof subsystem add --nqn nqn.2016-06.io.spdk:cnode1
ceph nvmeof listener add --nqn nqn.2016-06.io.spdk:cnode1 --host-name host01 --traddr 10.0.0.11 --trsvcid 4420
ceph nvmeof namespace add --nqn nqn.2016-06.io.spdk:cnode1 --rbd-pool rbd --rbd-image-name vol1
ceph nvme-gw show POOL GROUP          # the ANA state of each gateway as the mon sees it
# the host
nvme discover -t tcp -a 10.0.0.11 -s 8009
nvme connect-all --traddr 10.0.0.11 --transport tcp -l 1800 -s 8009
nvme list-subsys                       # paths and ANA state (optimized/inaccessible)
# seeing NVMe commands in the kernel
bpftrace -e 'tracepoint:nvme:nvme_setup_cmd { @op[args->opcode] = count(); }'
```

::: {.debug}
If host I/O stays suspended for more than a few tens of seconds after a gateway fails: (1) use `ceph nvme-gw show` to see whether the ANA group is stuck in WAIT_BLOCKLIST_CMPL; (2) check `ceph osd blocklist ls` to confirm the old gateway's address has been blocklisted; (3) make sure the OSDMonitor is writeable. `CMonRequestProposal` waits until the OSDMonitor becomes writeable, so a quorum problem directly stops the failover.
:::

::: {.warn}
The documentation warns not to run `ceph nvme-gw create` and `delete` by hand on a cephadm-managed cluster: deleting a gateway immediately fails over its ANA groups. `disable`-ing all the gateways of a group cuts off NVMe-oF access to the namespaces.
:::

# Supplementary and up to date {#sec-31-6}

- The `ceph nvme-gw listeners` command was added in Tentacle, according to the documentation.
- In main, NVMeofGwMap has the concept of a **location** and a **disaster** state for a location (`cfg_set_location`, `cfg_location_disaster_set`). The replacement is chosen first within the same location. Check this feature in your own version before using it.
- `NVMeofGwBeaconConstants.h` defines two beacon versions: 1 (old, without diff) and 2 (with diff). The mon option `cfg_enable_disable_beacon_diff` controls it.
- In NVMEDevice, `register_ctrlr` uses only namespace number 1, and `ceph_assert(shared_driver_datas.empty())` means only one SPDK device per OSD process.

# Hands-on exercise {#sec-31-7}

1. For q_depth=8 and DSTRD=2, compute the offsets of the SQ and CQ doorbells of queue 5. (Answer: 0x1000 + 10×16 = 0x10A0 and 0x10B0)
2. Write the SQE of a 64 KiB write at offset 3 GiB with a 512-byte LBA: slba, NLB and the number of PRP list entries.
3. A 1 MiB write in NVMEDevice: compute the number of Tasks, commands and DMA buffers.
4. With bpftrace on the nvme_setup_cmd and nvme_complete_rq tracepoints, build the device latency distribution for an OSD during `rados bench`.
5. In a three-gateway group, stop one with `ceph orch daemon stop` and follow the ANA state change in `nvme list-subsys` and `ceph nvme-gw show`.

# Review questions {#sec-31-8}

1. Where are the SQ and CQ located, and who writes into each?
2. How does the Phase Tag identify a new CQE without reading a device register?
3. Why does the kernel defer the doorbell write until the end of a batch?
4. Why is the length field of a Read command zero-based, and what is its value for 8 blocks?
5. Why does NVMEDevice copy data into DMA buffers?
6. What are the benefit and the cost of the thread_local SharedDriverQueueData?
7. How does aio_submit in NVMEDevice differ from KernelDevice in terms of blocking?
8. Describe the path of a write from the host's nvme_tcp to the OSD, using the names of the bdev_rbd functions.
9. Why must the replacement gateway wait for the blocklist before becoming ACTIVE?
10. When does the replacement-gateway algorithm return -EBUSY, and when -ENOENT?

# Sources for this chapter {#sec-31-9}

- The NVMe-oF gateway in the Ceph documentation: https://docs.ceph.com/en/latest/rbd/nvmeof-overview/
- Configuring the NVMe-oF target: https://docs.ceph.com/en/latest/rbd/nvmeof-target-configure/
- Gateway requirements: https://docs.ceph.com/en/latest/rbd/nvmeof-requirements/
- Using SPDK in BlueStore: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- NVMEDevice code: https://github.com/ceph/ceph/blob/main/src/blk/spdk/NVMEDevice.cc
- NVMeofGwMap code: https://github.com/ceph/ceph/blob/main/src/mon/NVMeofGwMap.cc
- The ceph-nvmeof project: https://github.com/ceph/ceph-nvmeof
- The Linux kernel NVMe driver: https://github.com/torvalds/linux/blob/master/drivers/nvme/host/pci.c
- NVMe and NVMe/TCP structures: https://github.com/torvalds/linux/blob/master/include/linux/nvme.h
- The bdev_rbd module in SPDK: https://github.com/spdk/spdk/blob/master/module/bdev/rbd/bdev_rbd.c
- SPDK documentation: https://spdk.io/doc/
- The NVMe specifications: https://nvmexpress.org/specifications/
