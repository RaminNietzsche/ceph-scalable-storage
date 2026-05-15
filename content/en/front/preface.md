---
id: preface
lang: en
---

## Why this book? {#sec-00-0-1}

Ceph is one of the few open-source storage systems that provides block, object and file storage on a single platform, with no central point of failure, at the scale of hundreds of petabytes. That breadth is also what makes it hard to learn. An operator who has only memorised commands will not know what is happening inside the system at the first serious incident: a stuck PG, a full OSD, a lost quorum. Coherent, in-depth material about Ceph in Persian is very scarce, and this book is an attempt to fill part of that gap.

This book is an original work. The text, examples, commands, diagrams, exercises and "From the code" sections were all written for this book, and they are based on current Ceph releases: Squid (19.2), Tentacle (20.2) and Umbrella (21.2). Many older resources still teach FileStore, ceph-deploy and other deprecated tools. Wherever that matters, this book uses their modern replacements (BlueStore, cephadm, mClock and so on) and explains how they differ from the old way.

## Structure of the book {#sec-00-0-2}

Chapters 1–21 cover the main topics of working with Ceph: architecture and the first cluster, RBD, OpenStack, RGW and multisite, CephFS, cluster operations, CRUSH and RADOS internals, the dashboard, performance benchmarking, deployment, BlueStore, erasure coding, librados, RADOS classes, tiering, troubleshooting, disaster recovery, day-to-day operations, monitoring and performance tuning. **Special Part 22** is for readers who want to see the structure of the Ceph code and the complete path of requests, function by function. **Part III, "Lower Layers" (chapters 23–33)**, goes one layer deeper. Chapters 23–29 were added in version 1.1 and chapters 30–33 in version 1.2. The topics of this part: the block device, bufferlist, mempool and crc32c; the BlueStore and BlueFS on-disk format, byte by byte; RocksDB inside BlueStore; msgr2 frames; GF(2^8) and Reed-Solomon mathematics; CRUSH at the bit level; the Linux kernel clients; Crimson and SeaStore; SPDK and NVMe; scrub and recovery at the code level; and memory and CPU inside the OSD. **Part IV, "Specialist Part" (chapters 34–42)**, added in version 1.6, checks the three main subsystems against the main branch: in RADOS, the object model and the op path, the pg log, peering and recovery, and snapshots, watch/notify and cls; in RBD, the image layout and object map, the librbd I/O path, exclusive lock and caches, and rbd-mirror internals; and in RGW, the data model, bucket index, versioning and multipart, the request path, SigV4, quotas, gc and lifecycle, and multisite internals.

## What's new in version 1.6 {#sec-00-0-3}

- **Part IV, "Specialist Part", with nine new chapters (34–42)** on RADOS, RBD and RGW, with algorithm boxes from the source code, byte-level figures, complete command references with sample output, tuning and troubleshooting, exercises and answers.
- **@NALGO@ "Algorithm" boxes and @NFIG@ figures** across the book, up from 143 and 350 in version 1.5.
- The glossary (OLH, bilog, period, SigV4, SnapSet, PastIntervals and more) and the bibliography were updated.

## What's new in version 1.4 {#sec-00-0-4}

- **143 "Algorithm" boxes and 350 figures** across the book, up from 129 and 332 in version 1.3. The new boxes and figures are in chapters 8, 9, 10, 15, 17, 19, 22, 24 and 33.
- **Numbers from a real cluster, not a model.** Most of the new numbers were measured on a small test cluster running Ceph 18.2.7 (Reef), with one mon, one mgr and three OSDs on BlueStore. The cluster ran on a single virtual machine, so only the trends and ratios are meaningful, not the absolute values. Other figures were computed exactly from real CRUSH maps with crushtool and osdmaptool. The measurements are: the real output of rbd du, with and without `--exact`; copysets and rebuild time, with the exact number of triples and the fan-out; data movement when adding a host and when changing weights; the effect of the upmap balancer and of doubling pg_num; a timeline of PG states, and the loss of one to three hosts; Little's law and a block-size sweep; OpTracker events and commit ordering; the real BlueStore label, byte by byte, and the free-space map; pglog growth and the cost per item in the mempool; the cls_numops counter compared with reads and writes from the client; the cost of cls_lua; and mgr statistics staleness and the cost of pg dump.
- **More accurate PromQL:** the metric names and alert expressions in chapter 20 now match `module.py` in the prometheus module and `prometheus_alerts.yml` in ceph-mixin.
- **New findings:** doubling pg_num moves about 49% of the data. With three replicas and `min_size=2`, losing two hosts out of ten stalls almost every client of an image. pglog memory keeps growing through dups even after the log length has levelled off. The cost of one bluestore_alloc item was measured at 80 bytes. In our environment, Lua inside the OSD was faster than reading the whole object only on links slower than about 0.6–1.6 Gb/s.
- **Corrections:** in cls_lua the global table is called `objclass`, not `cls`. The chapter 15 example was corrected and tested on the cluster. The version header in every chapter was updated to 1.4.

## What's new in version 1.3 {#sec-00-0-5}

- **129 "Algorithm" boxes and 332 figures** across the book, up from 77 boxes and 271 figures in version 1.2. The new boxes and figures are in chapters 1–7, 11–14, 18, 20 and 21, and Appendix G was updated.
- **New numeric examples, recomputed from the formulas in the code.** For example: the ceph_str_hash_linux hash for bucket-index shards and resharding; choose_oid in the datalog and mdlog; inode numbering and dirfrag selection with rjenkins in CephFS; split and merge thresholds and the DecayCounter; check_failure and the grace period in OSDMonitor; the operation budget and watch/notify in librados; the ConnectionTracker score and connectivity elections; the RS matrix in ISA-L over GF(2^8); the PDW decision rule; the compression acceptance test and the effect of min_alloc_size in BlueStore; and the copyset model for the probability of data loss.
- **New findings:** the target hash of the datalog and mdlog depends only on the high bits of the characters, so names that share a pattern do not fill every shard. This analysis is this guide's own and is not an official claim of the project. Other findings: the CephFS root directory is never fragmented; a notify timeout shorter than one second falls back to the default; the Vandermonde matrix in ISA-L does not satisfy the MDS condition for some k and m, which is why Cauchy is recommended; and with a min_alloc_size of 64K, a 64K blob is never compressed.
- **Corrections:** the inverted evict logic in cache tiering was rechecked against the code, and its table was fixed. The size of range_seg_t was corrected to 80 bytes. The rbd du function name, the can_fragment conditions and the command for viewing BlueFS statistics (ceph daemon) were also fixed. A document build error was fixed as well: unclosed tables had been swallowing the text that followed them.

## What's new in version 1.2 {#sec-00-0-6}

- **Four new chapters (30–33):** Crimson, Seastar and SeaStore; SPDK, NVMe queues and the NVMe-oF gateway; scrub, recovery, backfill and repair at the code level; and memory and CPU inside the OSD, from mempool and PriorityCache to NUMA and profiling.
- **77 "Algorithm" boxes** throughout the book. Each box has an explanation, pseudocode, complexity, a worked numeric example and at least one figure, and it points to a specific file and function in the code. The new "List of Algorithms" appendix (Appendix G) lists them all with page numbers. Examples: the Galois-field log/exp tables and PSHUFB multiplication in ISA-L; the skiplist, write groups, Bloom filters and dynamic levels of RocksDB; the on-wire length and nonce in msgr2; MSR in CRUSH; scrub scheduling with a normal distribution; knapsack PG rounding in Umbrella; and choosing the authoritative info during peering.
- **271 figures** across the book, all designed for this guide, with long captions and an explanatory paragraph. They include byte diagrams of on-disk and on-wire formats, numeric plots for formulas, and timelines for protocols.
- **Expanded chapters with "By the numbers" sections.** Chapters 9, 10, 15, 16, 17, 19 and 23–29 have new sections that open the mechanisms up to the level of loops and constants in the code. Examples: io_uring and libaio; submit retries; lifecycle expiration days; evict_effort in cache tiering; the volume selector in BlueFS; the cls_lock lock; the slow request warning; the BlueStore allocator; mClock capacity and profiles; and the password policy and account lockout in the Dashboard.
- **Corrections:** several version-dependent behaviours are now marked more explicitly, including that MSR exists only from Squid and is missing from the kernel client, and that the autoscaler knapsack exists only in v21.2.0. Where the code and the documentation disagree, the disagreement is stated explicitly.

## What's new in version 1.1 {#sec-00-0-7}

- Seven new chapters, 23–29, with worked numeric examples (crc, lba and varint encoding, the KEEPALIVE2 frame, RS encoding with k=4 and m=2, straw2 selection for a real object, and striping). All of these examples were computed with independent code or with compiled Ceph code.
- Chapters 13, 14, 16, 18, 20 and 21 were expanded with "One layer down" sections and new diagrams: the EC backend and rollback; the MOSDOp message, Objecter and backoff; the RGW object layout and lifecycle; the RBD journal format and the stretch-mode state machine; perf counters and the admin socket protocol; and the BlueStore memory control loop and throttles.
- Version-dependent details were corrected (including the default number of HDD shards from v19.2.1), the glossary and index were expanded, and the troubleshooting table is easier to read.
- Scope of quoted code: function names and string formats from the Linux kernel (GPL-2.0) and RocksDB (Apache-2.0/GPL-2.0) appear only briefly, with their paths. Algorithms are rewritten in the book's own pseudocode.

Every chapter comes with the same fixed elements: "Tip", "Warning", "Deeper" and "Troubleshooting" boxes; a "From the code" section with structures, algorithms, pseudocode and detailed diagrams; a "Supplementary and up to date" section on changes in recent releases; a "Hands-on exercise"; "Review questions" (answers in the appendix); and "Sources for this chapter".

## Conventions {#sec-00-0-8}

- File, class and function names were checked against the main branch of the official ceph/ceph repository and against the release tags. Short code excerpts are marked "from ceph/ceph, LGPL" with the file path. All other code is pseudocode or examples written for this guide.
- Option defaults were taken from the `src/common/options/*.yaml.in` files. Wherever behaviour differs between releases, the release is stated explicitly.
- Examples, host names and incident scenarios are fictitious or anonymised.

## Who is this book for? {#sec-00-0-9}

SRE and operations engineers, infrastructure architects, and developers who run Ceph or build software on top of it. The book assumes familiarity with Linux, networking and basic storage concepts.

::: {.signature}
Ramin Najarbashi · November 2026
:::
