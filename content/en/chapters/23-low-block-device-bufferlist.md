---
chapter: 23
id: ch23
title: 'Lower Layers (1): Block Device, bufferlist, mempool and crc32c'
part: lower
lang: en
---

# Where this part fits {#sec-23-1}

The "lower layers" part starts where the earlier chapters stopped: after BlueStore has decided "write these bytes at this offset", what happens? This chapter follows the path from a `bufferlist` in ceph-osd's memory to the DMA command on the device. The following chapters do the same for BlueStore's on-disk format, RocksDB, msgr2, erasure code mathematics, CRUSH at the bit level and the kernel clients. All names have been checked against the main branch of the ceph/ceph repository.

::: {.summary title="In this chapter"}

- `KernelDevice`: opening the device with O_DIRECT, locking, write hints, discard and flush
- libaio vs io_uring and the path from `aio_submit` to the completion callback
- Alignment and `bdev_block_size`
- The internal structure of `bufferlist`, `ptr` and `raw`, zero copy and mempools
- crc32c: choosing the hardware implementation and a numerical example

:::

# KernelDevice: BlueStore's window onto the disk {#sec-23-2}

`src/blk/BlockDevice.h` defines the abstract `BlockDevice` interface, and `BlockDevice.cc` chooses its type. On the main branch there are only two types: `aio` (the `KernelDevice` class in `src/blk/kernel/`) and `spdk` (the `NVMEDevice` class in `src/blk/spdk/`). The PMEM implementation that existed in older versions is no longer in `block_device_t` on main.

![The path of a write from BlueStore to the disk. In user space, BlueStore builds a block-aligned bufferlist and collects a list of aio_t (offset, iovec and write hint) through an IOContext. KernelDevice::aio_submit hands them in a batch to the aio queue. At the syscall boundary, libaio uses io_submit and io_uring uses io_uring_prep_writev and io_uring_submit, on an fd opened with O_RDWR and O_DIRECT (a separate fd for each write hint). In the kernel, the bio becomes a request in blk-mq, and the NVMe or SCSI driver transfers the data with DMA directly from user memory pages. Completion reaches _aio_thread through io_getevents or a CQE, and it calls aio_callback](figures/ch23/f01_stack.png){#fig-23-f01_stack}

## Opening the device {#sec-23-2-1}

`KernelDevice::open()` opens two fds for each write hint value from `WRITE_LIFE_NOT_SET` to `WRITE_LIFE_MAX`: one in `fd_directs` with `O_RDWR | O_DIRECT` and another in `fd_buffereds` without O_DIRECT for buffered paths (for example large BlueFS reads). If the kernel supports `F_SET_FILE_RW_HINT`, the corresponding hint is set on each fd with `fcntl`, so that SSDs with streams can keep data with different lifetimes apart. On the buffered fd, `posix_fadvise(..., POSIX_FADV_RANDOM)` is also set.

**Exclusive lock:** `KernelDevice::_lock()` first tries a record lock (`struct flock` with `F_WRLCK`) and, if needed, `flock(fd, LOCK_EX | LOCK_NB)`, with at most `bdev_flock_retry=3` retries. This lock prevents two processes (for example a running OSD and a mistaken `ceph-bluestore-tool`) from writing to the same device at the same time.

```text
pseudocode: KernelDevice::open (this book's summary)
  for hint in WRITE_LIFE_NOT_SET .. WRITE_LIFE_MAX-1:
      fd_directs[hint]   = open(path, O_RDWR | O_DIRECT | O_CLOEXEC)
      fd_buffereds[hint] = open(path, O_RDWR | O_CLOEXEC)
      if F_SET_FILE_RW_HINT: fcntl(fd, F_SET_FILE_RW_HINT, &hint)
  _lock()                                   # flock/F_WRLCK, up to 3 retries
  fstat → size, block_size = bdev_block_size (4K); if st_blksize differs, only a warning
  detect rotational, discard support, NUMA node, device model/serial
  if bdev_aio: io_queue = io_uring (if bdev_ioring=true and supported) or libaio
  start _aio_thread ; start discard threads (bdev_async_discard_threads)
```

## Alignment {#sec-23-2-2}

With O_DIRECT, the kernel DMAs data directly from user pages. So the offset, length and buffer address must be aligned to the device's logical block size. Ceph guarantees this with `bdev_block_size=4_K` and asserts on the write paths. Read buffers are allocated with `bdev_read_buffer_alignment=4_K`. The practical result: BlueStore never writes less than 4K to the device. A 100-byte client write becomes either a read-modify-write on one 4K block or (on HDD) a deferred write in the WAL (chapter 24).

::: {.warn}
Disks that are not "4K native" but report a 4K physical block in 512e format work correctly with `bdev_block_size=4K`. But a device with a logical block larger than 4K (some hardware arrays) is not compatible with the defaults, and the OSD fails at mkfs or open. Before buying, check the value of `cat /sys/block/<dev>/queue/logical_block_size`.
:::

## libaio or io_uring {#sec-23-2-3}

| Option | Default (main) | Role |
|---|---|---|
| bdev_aio | true | use asynchronous I/O |
| bdev_ioring | false | use io_uring instead of libaio (if the kernel and liburing support it) |
| bdev_ioring_hipri / bdev_ioring_sqthread_poll | false / false | hardware polling and a kernel submission thread |
| bdev_aio_max_queue_depth | 1024 | aio queue depth |
| bdev_aio_reap_max | 16 | maximum completions reaped at a time |
| bdev_aio_poll_ms | 250 | timeout when waiting for completions |
| bdev_block_size | 4_K | assumed block size |
| bdev_enable_discard | false | send discard/TRIM after space is freed |
| bdev_async_discard_threads | 0 | asynchronous discard (replaces the old bdev_async_discard option) |
| bdev_flock_retry | 3 | lock retries |

In libaio (`src/blk/aio/aio.cc`), `aio_queue_t::submit_batch` sends an array of `iocb`s with `io_submit`. The `iocb` field must be the **first member** of `aio_t`, so that the pointer returned by the kernel can be cast directly to `aio_t` (the code's own comment in `aio.h`). On `EAGAIN`, submission is retried after a short delay. `get_next_completed` waits for completions with `io_getevents`. In io_uring (`src/blk/kernel/io_uring.cc`) the same interface is implemented with `io_uring_prep_writev`, `io_uring_prep_readv` and `io_uring_submit`.

![The sequence of an I/O batch. The transaction thread only records aio_write in the IOContext, and then aio_submit sends them all in a batch (up to a depth of 1024). The independent _aio_thread, in a loop with a 250-millisecond timeout, reaps at most 16 completions and decrements each IOContext's num_running counter. When this counter reaches zero, aio_callback is called with that transaction's priv, and BlueStore moves it from AIO_WAIT to IO_DONE and then KV_QUEUED](figures/ch23/f02_aio.png){#fig-23-f02_aio}

```cpp
// from ceph/ceph, LGPL — src/blk/kernel/KernelDevice.cc, _aio_thread() (excerpt)
	if (--ioc->num_running == 0) {
	    aio_callback(aio_callback_priv, ioc->priv);
```

## flush and discard {#sec-23-2-4}

`KernelDevice::flush()` finally runs `fdatasync(fd_directs[WRITE_LIFE_NOT_SET])` to drain the device's write cache. In `BlueStore::_kv_sync_thread` there is logic named `force_flush`: if data and DB are on the same device, the BlueFS log commit itself flushes the device and a separate flush is not needed. Otherwise (or when there is nothing to commit in RocksDB), flushing the data device is forced, so that the aio data is durable before the metadata is recorded. discard is only sent when the device supports it and `bdev_enable_discard=true`. With `bdev_async_discard_threads>0`, discard is done in separate threads with a queue cap of `bdev_async_discard_max_pending`, so that it does not raise write latency.

::: {.deep}
Why discard is off by default: on many SATA SSDs, the TRIM command is synchronous and slow and can block the device queue for several milliseconds. Today's NVMe SSDs usually perform well even without discard, because they have internal over-provisioning. If you enable discard, make it asynchronous and measure p99 latency before and after.
:::

## SPDK {#sec-23-2-5}

`NVMEDevice` in `src/blk/spdk/` separates the NVMe device completely from the kernel: SPDK's user-space driver manages the NVMe queues directly with polling, and there are no syscalls or interrupts on the data path. The device path is indicated with the `spdk:` prefix in `bluestore_block_path`. The cost is dedicating a CPU core to polling, needing hugepages and vfio, and losing the usual kernel tools (iostat, blktrace). In practice most deployments prefer KernelDevice, and crimson with SeaStore pursues another path to removing kernel overhead.

::: {.debug}
Seeing the real I/O path:
:::

```bash
ceph osd metadata 4 | jq '{bluestore_bdev_type, bluestore_bdev_rotational, bluestore_bdev_dev_node}'
cat /sys/block/nvme0n1/queue/{logical_block_size,physical_block_size,write_cache}
ceph config get osd.4 bdev_ioring
strace -f -e trace=io_submit,io_getevents,io_uring_enter -p $(pgrep -f 'ceph-osd.*--id 4') 2>&1 | head
blktrace -d /dev/nvme0n1 -o - | blkparse -i - | head -30   # Q/G/D/C for each request
```

# bufferlist: Ceph's core data structure {#sec-23-3}

Almost every byte that moves in Ceph, whether a network message, object data or a RocksDB record, is inside a `ceph::buffer::list` (usually with the short name `bufferlist`). Its design has three goals: **zero copy** (joining pieces without moving bytes), **sharing** (several lists pointing to the same memory) and **memory accounting** (each piece belongs to a mempool).

![The three layers of bufferlist. At the top, list keeps a linked list of ptr_nodes in _buffers, along with _carriage (pointing to the last ptr, on which fast appends are done), _len (total bytes) and _num (number of ptrs). In the middle, each ptr is only a window: a pointer to a raw along with _off and _len. At the bottom, raw owns the actual memory and holds data, len, the atomic reference counter nref, the mempool ID and a cache of the last crc. Several ptrs in several lists can point to one raw; copying a bufferlist only increments nref](figures/ch23/f03_bl.png){#fig-23-f03_bl}

| Type | File | Note |
|---|---|---|
| `buffer::ptr` | `include/buffer.h` | fields `_raw`, `_off`, `_len`; methods `c_str()`, `length()`, `is_aligned()`, `is_page_aligned()` |
| `buffer::list` | `include/buffer.h` | `_buffers`, `_carriage`, `_len`, `_num`; `append`, `claim_append`, `splice`, `rebuild`, `c_str()` |
| `buffer::raw` | `include/buffer_raw.h` | `data`, `len`, `nref`, `mempool`, `last_crc_offset`/`last_crc_val` with `crc_spinlock` |
| raw implementations | `common/buffer.cc` | `create_aligned`, `create_small_page_aligned`, `claim_char`, `claim_malloc`, `claim_buffer` (with a custom deleter), `raw_hack_aligned` |

## The real cost of c_str() {#sec-23-3-1}

`list::c_str()` returns a pointer to a **contiguous** region. If the list consists of several ptrs, `rebuild()` runs first, which creates a new raw and **copies** all the pieces into it. So an apparently harmless call can cause a copy of several megabytes. That is why data path code uses iterators (`begin()`, `copy()`) or `rebuild_aligned_size_and_memory` (for O_DIRECT).

```text
pseudocode: the copy-free path of a write (this book's summary)
  msgr2 receive: the data segment is read into a new raw (with the alignment announced in the preamble)
  MOSDOp::decode: a ptr over the same raw (no copy) → OSDOp.indata
  PrimaryLogPG: t.write(oid, off, len, indata)                          # nref++
  BlueStore::_do_write: if aligned → the same ptrs become an iovec
                         if not → pad with zeros/previous data + rebuild_aligned (one copy)
  KernelDevice::aio_write: iovec[] → io_prep_pwritev (DMA from the same pages)
```

::: {.deep}
The crc cached on the raw: for each ptr, `buffer::list::crc32c()` checks with `raw::get_crc` whether the raw has already computed the crc for the same range and stored the (base seed, crc) pair with `set_crc` (`last_crc_offset` and `last_crc_val`). If the current seed differs from the stored seed, instead of reading the data again, the seed difference is corrected using the linearity of crc and the `ceph_crc32c_zeros` function (the crc of a zero region of the range's length). Any change to the raw (for example `copy_in` or `zero`) invalidates this cache with `invalidate_crc()`. This is a big saving for messages that are sent or checked with crc several times.
:::

# mempool: memory accounting {#sec-23-4}

`src/include/mempool.h` defines a fixed list of pools with the `DEFINE_MEMORY_POOLS_HELPER` macro. Each allocator of type `mempool::<pool>::vector`, `map` and so on records bytes and item counts in that pool in a sharded way (to reduce contention on cache lines). `osd_memory_target` and the BlueStore cache autotune make decisions based on these numbers.

| pool | What |
|---|---|
| bluestore_cache_onode / _meta / _data / _buffer / _other | parts of the BlueStore cache |
| bluestore_alloc | allocator structures |
| bluestore_extent / _blob / _shared_blob / _inline_bl | in-memory onode metadata structures |
| bluestore_txc / _writing / _writing_deferred | transactions and data being written |
| bluefs / bluefs_file_reader / bluefs_file_writer | BlueFS |
| buffer_anon / buffer_meta | buffers without a specific pool and their metadata |
| osd / osd_mapbl / osd_pglog / osdmap / osdmap_mapping / pgmap | OSD structures and maps |

```bash
ceph tell osd.4 dump_mempools | jq '.mempool.by_pool | to_entries | sort_by(-.value.bytes) | .[:6]'
ceph tell osd.4 dump_mempools | jq '.mempool.total'
ceph config get osd.4 osd_memory_target          # default 4_G
```

::: {.warn}
Uncontrolled growth of `buffer_anon` usually means that network data or messages are being held somewhere (for example large op queues on a slow OSD, or clients that do not read replies). Growth of `osd_pglog` points to an excessively long pg log (the `osd_min_pg_log_entries` and `osd_max_pg_log_entries` options).
:::

# crc32c: from a CPU instruction to a block checksum {#sec-23-5}

Ceph uses crc32c (the Castagnoli polynomial, in reversed form 0x82F63B78) both for data checksums in BlueStore and for message integrity in msgr2. `ceph_choose_crc32()` in `common/crc32c.cc` chooses the best implementation for the CPU once, at load time.

![The crc32c implementation selection chain and where it is used. The check order is: on x86 first AVX512 with VPCLMULQDQ, then SSE4.2 (with or without PCLMUL for processing three streams in parallel), on aarch64 the CRC32 instructions, and on ppc, s390x and riscv dedicated versions. If none is available, the software table-driven sctp implementation is used. This function is used in BlueStore for each data chunk, in msgr2 crc mode for each segment and preamble, and in bufferlist with the crc cache on the raw](figures/ch23/f04_crc.png){#fig-23-f04_crc}

## A numerical example {#sec-23-5-1}

`ceph_crc32c(seed, data, len)` works **without** the final inversion, and BlueStore starts with a seed of `-1` (0xFFFFFFFF). For the reference string `"123456789"`:

| Input | seed | ceph_crc32c output | After final XOR with 0xFFFFFFFF |
|---|---|---|---|
| `"123456789"` (9 bytes) | 0xFFFFFFFF | 0x1CF96D7C | 0xE3069283 (the standard CRC-32C reference value) |
| 4096 zero bytes | 0xFFFFFFFF | 0x6706BE76 | — |
| `"ceph"` | 0 | 0x575990D6 | — |

```python
# this guide's own example: bit-by-bit crc32c (slow, only for understanding)
def crc32c(crc, data):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc
assert crc32c(0xFFFFFFFF, b"123456789") == 0x1CF96D7C
```

The hardware version does the same with the `crc32` instruction on x86 (8 bytes per instruction) and with three parallel streams combined with PCLMULQDQ. On today's processors its speed is several tens of gigabytes per second per core, so the checksum is practically free.

## Checksums in BlueStore {#sec-23-5-2}

`Checksummer.h` defines the types `CSUM_XXHASH32=2`, `CSUM_XXHASH64=3`, `CSUM_CRC32C=4`, `CSUM_CRC32C_16=5` (the low 16 bits) and `CSUM_CRC32C_8=6`, and the default is `bluestore_csum_type=crc32c`. Each blob (chapter 24) has the fields `csum_type`, `csum_chunk_order` (chunk size equal to `1 << order` bytes) and `csum_data` (the array of checksums).

**Overhead arithmetic:** with a 4K chunk and crc32c, every 4096 bytes of data have 4 bytes of checksum, that is about 0.1%. For an OSD with 10 TiB of data, this is about 10 GiB of checksums in onodes, part of which sits in the onode cache. If you make the chunk larger (large blobs and sequential reads, as with RGW), this overhead drops, but every small read has to read the whole chunk in order to verify it.

# libaio and io_uring at the level of structures and locks {#sec-23-6}

The KernelDevice section showed the overall path. Here the same path is followed at the level of bytes, locks and threads. In `KernelDevice::KernelDevice`, based on `bdev_ioring` (default false), KernelDevice builds one of two queues: `aio_queue_t` (libaio) or `ioring_queue_t` (io_uring). The queue depth in both cases is `bdev_aio_max_queue_depth` (default 1024).

![The sixty-four-byte iocb structure that aio_t in Ceph fills for each I/O. The example is a pwritev with three iovecs, 12 KiB in total, at offset 0x5A000. aio_data is the pointer to the aio_t itself and comes back in the io_event. With this pointer, the reaping thread knows without searching which IOContext to complete. In vectored commands, aio_nbytes is the number of iovecs, not the byte length](figures/ch23/f05_iocb.png){#fig-23-f05_iocb}

::: {.algo #alg-23-1 title="libaio batch submission with exponential backoff" src="src/blk/aio/aio.cc :: aio_queue_t::submit_batch" complexity="O(N/max_iodepth) io_submit calls normally; in the worst case 16 attempts and about 8.2 seconds of cumulative waiting"}
:::

```text
pseudocode
attempts = bdev_aio_submit_retry_max (16) ; delay = 125 µs
while work remains:
    fill piocb[] from the list up to max_iodepth
    r = io_submit(ctx, pulled − pushed, piocb + pushed)
    if 0 ≤ r < toSubmit: pushed += r ; r = −EAGAIN      # partial acceptance
    if r == −EAGAIN and attempts−− > 0:
        usleep(delay) ; delay ×= 2 ; retries++ ; continue
    if r < 0: return r
    pushed = pulled = 0 ; reset attempts and delay
```

**Numerical example.** With 1024 requests pending in the kernel queue and a batch of 64, io_submit may accept only 10 requests. In that case pushed = 10, r becomes −EAGAIN, and a retry happens after 125 µs. If the queue stays full, the waits are 125, 250, 500 µs and so on, doubling up to 4.1 seconds for the sixteenth attempt. The total is 125 × (2^16 − 1) µs ≈ 8.19 seconds. The retries counter shows up in the log as "aio_submit retries". If this number appears often in the OSD log, the queue depth or device latency has a problem, not the CPU.

![The wait before each retry (bars, logarithmic scale) and the cumulative wait (red line) when io_submit keeps returning EAGAIN. After 8 attempts only 32 milliseconds have passed, but the last 8 attempts take more than 8 seconds. So a short saturation is almost invisible, and only a long saturation turns into a slow op](figures/ch23/f07_aioretry.png){#fig-23-f07_aioretry}

![The io_uring submission queue entry that init_sqe in Ceph builds for the same pwritev. The opcode is IORING_OP_WRITEV (2). The IOSQE_FIXED_FILE flag means the fd is an index into the table of registered files, and the kernel does not pay the fget/fput cost on each I/O. user_data is the same aio_t pointer and comes back in the sixteen-byte CQE](figures/ch23/f06_sqe.png){#fig-23-f06_sqe}

::: {.algo #alg-23-2 title="io_uring submission and reaping with two locks and epoll" src="src/blk/kernel/io_uring.cc :: ioring_queue_t::submit_batch, ioring_queue, ioring_get_cqe, get_next_completed" complexity="submission O(N) SQE writes and one io_uring_submit; reaping O(min(ready, reap_max)) with no system call when a CQE is ready"}
:::

```text
pseudocode
submit_batch(beg, end):
    lock(sq_mutex)
    for io in [beg, end): sqe = io_uring_get_sqe() ; if null: break   # the ring is full
                          init_sqe(sqe, io)   # prep_writev/readv, FIXED_FILE, user_data=io
    rc = io_uring_submit()        # io_uring_enter, or just updating the tail in SQPOLL
    unlock(sq_mutex) ; return rc
get_next_completed(timeout, paio[], max):
    lock(cq_mutex) ; for each cqe up to max: io.rval = cqe.res ; paio[n++] = io
    io_uring_cq_advance(n) ; unlock(cq_mutex)
    if n == 0: epoll_wait(ring_fd, timeout = bdev_aio_poll_ms) ; if ready, go again
```

**Numerical example and the difference from libaio.** With a 1024-entry ring, the SQ is 1024 × 64 = 64 KiB and the CQ (which the kernel makes twice the SQ by default) is 2048 × 16 = 32 KiB. Both are shared between the kernel and Ceph with mmap. In libaio, each batch has at least one io_submit and each reap one io_getevents. In io_uring, when a CQE is ready, reaping is just reading shared memory. With `bdev_ioring_sqthread_poll=true` (the IORING_SETUP_SQPOLL flag), submission also has no system call, but a kernel thread spins on a CPU core. `bdev_ioring_hipri` sets the IORING_SETUP_IOPOLL flag: completion is done by polling the NVMe queue, and this only works for devices that have poll queues and with O_DIRECT.

![The full io_uring path in KernelDevice. Submission is done under sq_mutex, because several threads (transaction, deferred, BlueFS) submit I/O concurrently. Reaping is in the aio_thread under cq_mutex. When no CQE is ready, instead of blocking in io_uring_enter, it waits on ring_fd with epoll, which preserves the same bdev_aio_poll_ms timing pattern as libaio](figures/ch23/f08_uring.png){#fig-23-f08_uring}

::: {.warn}
io_uring is off by default in Ceph and may be disabled or restricted on some kernels and security policies (for example the `kernel.io_uring_disabled` sysctl in newer kernels). `ioring_queue_t::supported()` tests support by building a trial ring of 16 entries. If it fails, the OSD falls back to libaio with a warning.
:::

# Buffer growth in bufferlist::append {#sec-23-7}

::: {.algo #alg-23-3 title="Exponential growth of append space" src="src/common/buffer.cc :: buffer::list::append(const char*, unsigned), refill_append_space" complexity="amortized O(1) per small append; O(log(L/4K)) allocations up to the 256K cap and then L/256K allocations"}
:::

```text
pseudocode
append(data, len):
    first = min(len, free space at the end of _carriage)
    memcpy into the same raw (inline copy for length ≤ 32) ; _carriage.len += first
    if len − first > 0: refill_append_space(len − first).append(the rest)
refill_append_space(len):
    alen = round_up(round_up(len, 8) + S, 4096)          # S = sizeof(raw_combined)
    if _carriage is the last ptr:
        alen = max(alen, min(2 × round_up(_carriage.raw_length, 4096), 256 KiB))
    raw_combined::create(alen − S) ← data and header in one allocation
```

**Numerical example.** If encoding a structure appends 1 MiB of data in small pieces (for example u64s and short strings), the allocations are 4K, 8K, 16K, 32K, 64K, 128K and then 256K. After the first six buffers 252K is filled, and the remaining 772K goes into four more 256K buffers. The result is 10 ptr_nodes, with 1276 KiB allocated in total for 1024 KiB of data, instead of 256 4K buffers. The 256K cap is deliberately below tcmalloc's "small object" threshold. Each raw_combined keeps its control header at the end of the same allocation, so each buffer gets exactly a multiple of 4K of memory from the allocator.

![The sizes of the ten raw_combined buffers that refill_append_space creates when appending one megabyte of data in small pieces. The sizes double from 4K until they reach the 256K cap. S is the size of the raw_combined header, which is subtracted from each allocation. The unused space at the end of the last buffer is the reason for the difference between the 1276 KiB allocated and the 1024 KiB of data](figures/ch23/f09_appendgrow.png){#fig-23-f09_appendgrow}

::: {.tip}
If the final size is known in advance, `bl.reserve(n)` or `bl.push_back(buffer::create(n))` eliminates all these intermediate allocations. Ceph's hot paths use this method, for example encoding messages with `encode(..., features)` and the `bound_encode` pre-estimate in denc.
:::

# crc32c for zeros and seed adjustment {#sec-23-8}

`ceph_crc32c(crc, NULL, len)` in `include/crc32c.h` has a special convention: if data is null and len is greater than 16, the crc of an all-zero region is computed, without reading memory. BlueStore and bufferlist use this for zero regions (`buffer::list::append_zero`, raw_zeros buffers) and for adjusting a stored crc.

::: {.algo #alg-23-4 title="crc32c of zeros with jump matrices" src="src/common/crc32c.cc :: ceph_crc32c_zeros, create_turbo_table (the crc_turbo_table[32][32] table)" complexity="O(log len) 32×32 matrix multiplications over GF(2), each at most 32 XORs; independent of length (instead of O(len))"}
:::

```text
pseudocode
# M[0][bit] = crc(1≪bit, one zero byte) ; M[r] = M[r−1]², that is a jump of 2^r bytes
zeros(crc, len):
    rem = len & 15 ; n = len ≫ 4 ; r = 4                 # start from the 16-byte jump
    while n: if n & 1: crc = Σ_{bit j of crc = 1} M[r][j]   (XOR)
             n ≫= 1 ; r += 1
    if rem: crc = regular_crc(crc, rem zero bytes)
```

**Numerical example.** For 4096 zero bytes with seed = 0xFFFFFFFF: rem = 0 and n = 256 = 2^8, so only one multiplication with M[12] is needed, and the result is 0x6706BE76. Direct byte-by-byte computation (this guide's separate implementation) gives the same number. For 69637 = 65536 + 4096 + 5 bytes: two multiplications (M[16] and M[12]) and then 5 regular bytes, with the result 0xAC433F9D, which again matches the direct computation. The first four values of row M[0] (0xF26B8303, 0xE13B70F7, 0xC79A971F, 0x8AD958CF) are the same values as the crc_turbo_table in Ceph's code.

::: {.algo #alg-23-5 title="Adjusting a cached crc to a new seed" src="src/common/buffer.cc :: buffer::list::crc32c; include/buffer_raw.h :: raw::get_crc, set_crc" complexity="O(log len) instead of O(len) for each raw whose crc is cached"}
:::

```text
pseudocode
for node in _buffers:
    if raw.get_crc((off, off+len)) → (v, c):
        if v == crc: crc = c                                  # cache hit
        else: crc = c ⊕ ceph_crc32c(v ⊕ crc, NULL, len)       # adjust
    else: base = crc ; crc = ceph_crc32c(crc, data, len) ; raw.set_crc(..., (base, crc))
```

**Numerical example.** For a 1000-byte buffer, the crc with seed 0 is 0xACBE2A2C and is cached in the raw. Now the same buffer is requested with seed 0xFFFFFFFF. The adjustment gives 0xACBE2A2C ⊕ zeros(0 ⊕ 0xFFFFFFFF, 1000) = 0x8B0C0F84, which is exactly the direct crc with the new seed. This is where the messenger (msgr) and BlueStore checksum a buffer twice with different seeds, and the second time costs only a few dozen XORs. Its statistics can be seen with `buffer_track_crc` in the `buffer_cached_crc` and `buffer_cached_crc_adjusted` counters.

![Three uses of crc32c jump matrices in Ceph. The top row is the ceph_crc32c_zeros algorithm, which breaks the length into powers of two. The middle row is the example of 4096 zero bytes, solved with one matrix multiplication. The bottom row is the adjustment of a cached crc in bufferlist: because CRC is linear, the difference between two seeds equals the crc of a zero region with a seed equal to the XOR of the two](figures/ch23/f10_crczeros.png){#fig-23-f10_crczeros}

# Supplementary and up to date {#sec-23-9}

- On main, `block_device_t` only has `aio` and `spdk`. PMEM support (DAX devices) has been removed on main, but Tentacle still has `block_device_t::pmem`. If you use PMEM, check the release notes before upgrading.
- The `bdev_async_discard` option has been replaced by `bdev_async_discard_threads`, and for compatibility the code maps the old value to one thread.
- io_uring is still off by default (`bdev_ioring=false`).

# Hands-on exercise {#sec-23-10}

1. On a test OSD, measure the ratio of `io_submit` to `io_getevents` with `strace -c -f -p <pid>` during a `rados bench`. Then set `bdev_ioring=true`, restart the OSD and compare the difference with `ceph osd perf`.
2. Run this chapter's Python crc32c function and compare the result for a random 4K block with Python's `crcmod` or `crc32c` (remember to apply the final XOR).
3. Save the output of `dump_mempools` before and after a large `rados bench` and identify the 5 pools with the most growth.
4. Collect `cat /sys/block/<dev>/queue/write_cache` and `rotational` for all OSD devices and compare them with `ceph osd metadata`.

# Review questions {#sec-23-11}

1. Why does KernelDevice open a separate fd for each write hint?
2. What limit does O_DIRECT alignment place on BlueStore's smallest write?
3. What are the roles of `bdev_aio_max_queue_depth` and `bdev_aio_reap_max`?
4. When does BlueStore force a separate flush of the data device?
5. Why is discard off by default?
6. What is the difference between `buffer::ptr` and `buffer::raw`?
7. Why can `bufferlist::c_str()` be expensive?
8. How does mempool help memory autotuning?
9. Why does Ceph's crc32c of `"123456789"` differ from the standard reference value?
10. What is the checksum overhead with a 4K chunk, and what is the trade-off of making the chunk larger?

# Sources for this chapter {#sec-23-12}

- KernelDevice code: https://github.com/ceph/ceph/blob/main/src/blk/kernel/KernelDevice.cc
- libaio in Ceph: https://github.com/ceph/ceph/blob/main/src/blk/aio/aio.cc
- bufferlist: https://github.com/ceph/ceph/blob/main/src/include/buffer.h
- mempool: https://github.com/ceph/ceph/blob/main/src/include/mempool.h
- crc32c: https://github.com/ceph/ceph/blob/main/src/common/crc32c.cc
- BlueStore configuration (checksum and compression): https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- io_uring: https://kernel.dk/io_uring.pdf
- CRC-32C (RFC 3720, appendix B.4): https://www.rfc-editor.org/rfc/rfc3720
