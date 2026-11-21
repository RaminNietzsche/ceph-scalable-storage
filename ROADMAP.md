# Roadmap

This file holds planned work for later editions of the book. After an item is written in the Persian text, it is translated into the English edition with the same identifiers.

## Gaps vs 《Ceph分布式存储实战》 (2016)

A topical comparison of this book's contents with the Chinese book 《Ceph分布式存储实战》 (2016; its examples are mostly based on Hammer and Jewel) showed that most of that book's topics are already covered here, or that their methods are obsolete. The remaining gaps are mostly **practical case studies**, not architectural holes. The list below is ordered by practical value today.

The comparison was only a way to find topics: no prose, command list or figure from that book is copied into this repository, and every new section will be written from official documentation and our own experiments.

| Rank | Topic | Target chapter | Status |
|---:|---|---|---|
| 1 | Cloud drive: Nextcloud on RGW/S3 — external storage, virtual bucket in DNS, CORS and path-style | ch04 | planned |
| 2 | Read/write split in front of RGW — ACLs on HTTP methods in HAProxy next to the ingress service, and consistency pitfalls after PUT | ch04 (beside §4.3.2) | done (§4.3.3) |
| 3 | VOD with HLS/DASH on RGW — lifecycle for stale segments, CDN, CORS and the public-bucket warning | ch04 | planned |
| 4 | Windows access, the modern way — SMB for CephFS, the official Ceph client for Windows, and an NVMe/TCP initiator for Windows and VMware | ch06 and ch02 | planned |
| 5 | RGW Admin Ops REST API — when to use it instead of the CLI, the caps it needs, and a few user, bucket and quota examples | ch04 (with a pointer to the signing material in ch41) | done (§4.12.3) |
| 6 | Primary on SSD, replicas on HDD — a "pattern and pitfall" box with primary-affinity and the CRUSH rule, and why a separate pool is usually better | ch08 or ch16 | done (§8.10.1) |
| 7 | CloudStack with RBD — RBD as primary storage, short, and not given equal weight with OpenStack | ch02 (referenced in ch03) | planned |
| 8 | CephFS for HPC — when to use CephFS and when Lustre or BeeGFS, and metadata pressure with many clients | ch06 | in progress (§6.8.3 covers what the Ceph documentation supports; a comparison with Lustre or BeeGFS needs sources outside Ceph and is not written) |
| 9 | OS and BIOS tuning additions — irqbalance, tuned profiles and a few network sysctl settings | ch21 (§21.8) | in progress (§21.8.1: cephadm-managed sysctl profiles; irqbalance and specific network values still open, since the Ceph documentation gives no values to cite) |

### Not adding (obsolete)

- **Calamari** (and Romana, Diamond, salt-minion): replaced by the Ceph Dashboard (ch09).
- **ceph-deploy and ceph-disk**: the current tool is cephadm (ch01 and ch11).
- **FileStore and a journal on SSD**, and journal sizing ratios: replaced by BlueStore (ch12).
- **Federated sync with Region in Hammer**: today's multisite uses realm, zonegroup and period (ch05 and ch42).
- **cache tier as a new production design**: ch16 covers only the architecture and how to migrate off it.
- **iSCSI with tgtd**: the NVMe-oF gateway replaces it (§2.10.1 and ch31).
- **Hadoop on CephFS with the old plugin**: the current path is S3A (§4.8).
- **COSBench**: warp is used instead (§10.7.1).
- **Ceph-Dokan with cephx turned off**: not acceptable from a security standpoint.
- **ZStack**, and **Zabbix or Diamond** as the primary monitoring stack (today's stack is Prometheus, in ch20).
- **2016 hardware figures** (1 GbE NICs, MONs with 1 GB of RAM, and the like): the current table is in §1.5.

## Ceph publications to review and integrate

Sources checked on 2026-11-15: the [ceph.io publications page](https://ceph.io/en/news/publications/) and the archived [UCSC SSRC Ultra-Large Scale Storage project page](https://www.ssrc.us/proj/exscale.html). Relevance notes are our own one-line summaries, not abstracts. "In bibliography" means the paper is already cited in a chapter's Sources list. Every row is `to review` until someone reads the paper and either cites it or decides against it.

The books on the ceph.io page are not listed: this book does not draw on other books (the 2016 Chinese book is handled only as a gap list, above).

### ceph.io: papers

| Title | Authors | Year | Venue | Link | Relevance | Target | In bibliography | Status |
|---|---|---|---|---|---|---|---|---|
| TiDedup: A New Distributed Deduplication Architecture for Ceph | M. Oh, S. Lee, S. Just, Y. J. Yu, D.-H. Bae, S. Weil, S. Cho, H. Y. Yeom | 2023 | USENIX ATC '23 | [pdf](https://www.usenix.org/system/files/atc23-oh.pdf) | The design behind today's RADOS dedup tier and its chunk/manifest objects | ch16, ch36 | no | to review |
| Design of Global Data Deduplication for a Scale-out Distributed Storage System | M. Oh, S. Park, J. Yoon, S. Kim, K. Lee, S. Weil, H. Y. Yeom, M. Jung | 2018 | IEEE ICDCS 2018 | [pdf](https://ceph.io/assets/pdfs/ICDCS_2018_mwoh.pdf) | Earlier dedup design (double hashing, self-contained objects); background for the TiDedup row | ch16 | no | to review |
| Performance Optimization for All Flash Scale-Out Storage | M. Oh, J. Eom, J. Yoon, J. Y. Yun, S. Kim | 2016 | IEEE Cluster 2016 | [pdf](https://ceph.io/assets/pdfs/performance_optimization_for_all_flash_scale-out_storage-SK_Telecom.pdf) | Where the OSD write path loses time on flash; useful as history next to Crimson | ch21, ch30 | no | to review |
| Asynchronous Object Storage with QoS for Scientific and Commercial Big Data | M. J. Brim, D. A. Dillow, S. Oral, B. W. Settlemyer, F. Wang | 2013 | PDSW '13 (SC13) | [pdf](https://ceph.io/assets/pdfs/p7-pdsw13-brim.pdf) | QoS-aware asynchronous object API on top of RADOS-like stores; a reference point for mClock | ch14, ch21 | no | to review |
| Ceph: Reliable, Scalable, and High-Performance Distributed Storage (Ph.D. thesis) | S. A. Weil | 2007 | Ph.D. thesis, UC Santa Cruz | [pdf](https://ceph.io/assets/pdfs/weil-thesis.pdf) | The single most complete original description of MDS, RADOS and CRUSH together | ch01, ch06, ch08, ch22 | no (mentioned in ch06 prose only) | to review |
| RADOS: A Fast, Scalable, and Reliable Storage Service for Petabyte-scale Storage Clusters | S. A. Weil, A. W. Leung, S. A. Brandt, C. Maltzahn | 2007 | PDSW '07 (SC07) | [pdf](https://ceph.io/assets/pdfs/weil-rados-pdsw07.pdf) | Original RADOS design: maps, peering, OSD-driven replication and recovery | ch08, ch14, ch35 | yes (ch01, ch14) | to review |
| Ceph: A Scalable, High-Performance Distributed File System | S. Weil, S. A. Brandt, E. L. Miller, D. D. E. Long, C. Maltzahn | 2006 | OSDI '06 | [pdf](https://ceph.io/assets/pdfs/weil-ceph-osdi06.pdf) | The founding paper: decoupled data and metadata, dynamic subtree partitioning | ch01, ch06, ch22 | yes (ch01, ch22) | to review |
| CRUSH: Controlled, Scalable, Decentralized Placement of Replicated Data | S. Weil, S. A. Brandt, E. L. Miller, C. Maltzahn | 2006 | SC '06 | [pdf](https://ceph.io/assets/pdfs/weil-crush-sc06.pdf) | The placement algorithm and bucket types; check our ch28 text against the paper's straw/list/tree analysis | ch08, ch28 | yes (ch01, ch08, ch28) | to review |
| Dynamic Metadata Management for Petabyte-Scale File Systems | S. Weil, K. Pollack, S. A. Brandt, E. L. Miller | 2004 | SC '04 | [pdf](https://ceph.io/assets/pdfs/weil-mds-sc04.pdf) | Origin of dynamic subtree partitioning used by the CephFS MDS balancer | ch06 | no | to review |
| Scalable Security for Large, High Performance Storage Systems | A. Leung, E. L. Miller | 2006 | StorageSS 2006 | [pdf](http://www.ssrc.ucsc.edu/Papers/leung-storagess06.pdf) | Capability-based access for many clients; background for cephx tickets and caps | ch07, ch26 | no | to review |
| The Design and Implementation of AQuA: an Adaptive QoS Aware Object-Based Storage Device | J. C. Wu, S. A. Brandt | 2006 | MSST 2006 | [page](https://www.ssrc.ucsc.edu/pub/wu-msst06.html) | Early per-OSD QoS scheduling; historical context for mClock | ch21 | no | to review |
| Secure Capabilities for a Petabyte-Scale Object-Based Distributed File System | C. Olson, E. L. Miller | 2005 | StorageSS 2005 | [pdf](http://www.cs.ucsc.edu/%7Eelm/Papers/storagess05.pdf) | Capability design that precedes cephx | ch26 | no | to review |
| Disk Infant Mortality in Large Storage Systems | Q. Xin, T. Schwarz, E. L. Miller | 2005 | MASCOTS '05 | [pdf](http://www.ssrc.ucsc.edu/Papers/xin-mascots05.pdf) | Early-life disk failures and burn-in; supports the hardware and failure-rate discussion | ch11, ch18 | no | to review |
| Impact of Failure on Interconnection Networks in Large Storage Systems | Q. Xin, E. L. Miller, T. Schwarz, D. D. E. Long | 2005 | MSST 2005 | [pdf](https://www.cse.scu.edu/~tschwarz/Papers/msst05-net.pdf) | How network failures, not only disks, affect data availability | ch11, ch18 | no | to review |
| OBFS: A File System for Object-Based Storage Devices | F. Wang, S. A. Brandt, E. L. Miller, D. D. E. Long | 2004 | MSST 2004 | [page](https://www.ssrc.ucsc.edu/pub/wang-msst04a.html) | Ancestor of EBOFS, so part of the FileStore → BlueStore story | ch12, ch24 | no | to review |
| File System Workload Analysis for Large Scientific Computing Applications | F. Wang, Q. Xin, B. Hong, S. A. Brandt, E. L. Miller, D. D. E. Long, T. T. McLarty | 2004 | MSST 2004 | [page](https://www.crss.ucsc.edu/pub/wang-msst04b.html) | The HPC workload traces that shaped Ceph's metadata design | ch06, ch10 | no | to review |
| Interconnection Architectures for Petabyte-Scale High-Performance Storage Systems | A. Hospodor, E. L. Miller | 2004 | MSST 2004 | [page](https://www.crss.ucsc.edu/pub/hospodor-msst04.html) | Network topology choices for large OSD clusters | ch11 | no | to review |
| Replication Under Scalable Hashing: A Family of Algorithms for Scalable Decentralized Data Distribution | R. J. Honicky, E. L. Miller | 2004 | IPDPS 2004 | [pdf](http://www.ssrc.ucsc.edu/Papers/honicky-ipdps04.pdf) | RUSH, CRUSH's direct predecessor | ch08, ch28 | no (RUSH named in ch01 prose) | to review |
| A Distributed Key-Value Store using Ceph | E. Cawthon | 2012 | Summer project report | [pdf](https://ceph.io/assets/pdfs/CawthonKeyValueStore.pdf) | A key-value layer built on RADOS objects; a worked librados example | ch14, ch15 | no | to review |

### UCSC SSRC (exscale)

Ceph-, RADOS-, CRUSH-, CephFS- and object-storage-related papers from the project page that are not already in the ceph.io table above. Not listed as out of scope: metadata search (Spyglass, Magellan, Copernicus), provenance, archival power management, the CERN EOS trace study, and pre-2001 work.

| Title | Authors | Year | Venue | Link | Relevance | Target | In bibliography | Status |
|---|---|---|---|---|---|---|---|---|
| Ceph: A Scalable Object-Based Storage System | S. Weil, F. Wang, Q. Xin, S. A. Brandt, E. L. Miller, D. D. E. Long, C. Maltzahn | 2006 | Tech. report UCSC-SSRC-06-01 | [page](https://www.ssrc.us/pub/weil-ssrctr06.html) | Longer pre-OSDI description of the object store side | ch01, ch22 | no | to review |
| Intelligent Metadata Management for a Petabyte-Scale File System | S. Weil, S. A. Brandt, E. L. Miller, K. Pollack | 2004 | 2nd Intelligent Storage Workshop | [page](https://www.ssrc.us/pub/weil-isw04.html) | Early MDS partitioning ideas, before the SC '04 paper | ch06 | no | to review |
| Efficient Metadata Management in Large Distributed File Systems | S. A. Brandt, E. L. Miller, D. D. E. Long, L. Xue | 2003 | MSST 2003 | [page](https://www.ssrc.us/pub/brandt-msst03.html) | Compares metadata distribution schemes that CephFS later chose between | ch06 | no | to review |
| A Fast Algorithm for Online Placement and Reorganization of Replicated Data | R. J. Honicky, E. L. Miller | 2003 | IPDPS 2003 | [page](https://www.ssrc.us/pub/honicky-ipdps03.html) | First RUSH variant: placement that moves little data when the cluster grows | ch08, ch28 | no | to review |
| Reliability Mechanisms for Very Large Storage Systems | Q. Xin, E. L. Miller, T. Schwarz, D. D. E. Long, S. A. Brandt, W. Litwin | 2003 | MSST 2003 | [page](https://www.ssrc.us/pub/xin-msst03.html) | Declustered parallel recovery (FARM), the idea behind PG-wide recovery | ch13, ch32 | no | to review |
| Evaluation of Distributed Recovery in Large-Scale Storage Systems | Q. Xin, E. L. Miller, T. Schwarz | 2004 | HPDC 2004 | [page](https://www.ssrc.us/pub/xin-hpdc04.html) | Recovery speed versus data-loss risk at scale | ch18, ch32 | no | to review |
| Disk Scrubbing in Large Archival Storage Systems | T. Schwarz, Q. Xin, E. L. Miller, D. D. E. Long, A. Hospodor, S. Ng | 2004 | MASCOTS '04 | [page](https://www.ssrc.us/pub/schwarz-mascots04.html) | Why and how often to scrub; a model to set against Ceph's scrub defaults | ch32 | no | to review |
| Using Device Diversity to Protect Data against Batch-Correlated Disk Failures | J.-F. Pâris, D. D. E. Long | 2006 | StorageSS 2006 | [page](https://www.ssrc.us/pub/paris-storagess06.html) | Mixing disk batches inside a failure domain; hardware-planning advice | ch11, ch18 | no | to review |
| Efficient Access Control for Distributed Hierarchical File Systems | K. Pollack, S. A. Brandt | 2005 | MSST 2005 | [page](https://www.ssrc.us/pub/pollack-msst05.html) | Permission checks in a partitioned namespace; context for CephFS caps and path restrictions | ch06 | no | to review |
| Storage Management in Large Distributed Object-Based Storage Systems (Ph.D. thesis) | F. Wang | 2006 | Ph.D. thesis, UC Santa Cruz | [page](https://www.ssrc.us/pub/wang-phdthesis06.html) | OBFS/EBOFS and OSD-local layout; BlueStore history | ch12, ch24 | no | to review |
| Ceph-related security: Scalable Security for High Performance, Petascale Storage; Scalable Security for Petascale Parallel File Systems | A. Leung; A. Leung, E. L. Miller, S. Jones | 2007 | Tech. report UCSC-SSRC-07-07; SC '07 | [TR](https://www.ssrc.us/pub/leung-ssrctr07.html), [SC07](https://www.ssrc.us/pub/leung-sc07.html) | Ticket and capability schemes for many clients; compare with cephx | ch07, ch26 | no | to review |
| Quota Enforcement for High-Performance Distributed Storage Systems | K. Pollack, D. D. E. Long, R. Golding, R. Becker-Szendy, B. C. Reed | 2007 | MSST 2007 | [page](https://www.ssrc.us/pub/pollack-msst07.html) | Distributed quota accounting; compare with CephFS quotas and RGW quotas | ch04, ch06 | no | to review |
| Providing Quality of Service Support in Object-Based File System | J. Wu, S. A. Brandt | 2007 | MSST 2007 | [page](https://www.ssrc.us/pub/wu-msst07.html) | QoS across many OSDs, follow-up to AQuA | ch21 | no | to review |
| Using Comprehensive Analysis for Performance Debugging in Distributed Storage Systems | A. Leung, E. Lalonde, J. Telleen, J. Davis, C. Maltzahn | 2007 | MSST 2007 (earlier as TR UCSC-SSRC-07-05) | [page](https://www.ssrc.us/pub/leung-msst07.html) | Correlating traces across a distributed storage system to find slow paths; method for the troubleshooting chapter | ch17, ch20 | no | to review |
| Understanding and Coping with Failures in Large-Scale Storage Systems | Q. Xin | 2007 | Tech. report UCSC-SSRC-07-06 | [page](https://www.ssrc.us/pub/xin-tr07.html) | Collected failure models and recovery strategies | ch18, ch32 | no | to review |
| The Impact of Failures on Large Distributed Storage Systems | M. Mehech | 2007 | Tech. report UCSC-SSRC-07-10 | [page](https://www.ssrc.us/pub/mehech-ssrctr07.html) | Simulated data loss under correlated failures | ch18 | no | to review |
| Disaster Recovery Codes: Increasing Reliability with Large-Stripe Error Correction Codes | K. Greenan, E. L. Miller, T. Schwarz, D. D. E. Long | 2007 | StorageSS 2007 | [page](https://www.ssrc.us/pub/greenan-storagess07.html) | Wide-stripe codes across sites; relevant to wide EC profiles and stretch layouts | ch13, ch27 | no | to review |
| Design and Evaluation of Oasis: An Active Storage Framework based on T10 OSD Standard | Y. Xie, K.-K. Muniswamy-Reddy, D. Feng, D. D. E. Long, Y. Kang, Z. Niu, Z. Tan | 2011 | MSST 2011 | [page](https://www.ssrc.us/pub/xie-msst11.html) | Running code next to the data on an OSD; a comparison point for RADOS classes | ch15 | no | to review |
| Reliable and Randomized Data Distribution Strategies for Large Scale Storage Systems | A. Miranda, S. Effert, Y. Kang, E. L. Miller, A. Brinkmann, T. Cortes | 2011 | HiPC 2011 | [page](https://www.ssrc.us/pub/miranda-hipc11.html) | Compares CRUSH-like placement strategies for fairness and data movement | ch28 | no | to review |
| Random Slicing: Efficient and Scalable Data Placement for Large-scale Storage Systems | A. Miranda, S. Effert, Y. Kang, E. L. Miller, I. Popov, A. Brinkmann, T. Friedetzky, T. Cortes | 2014 | ACM Transactions on Storage 10(3) | [page](https://www.ssrc.us/pub/miranda-tos14.html) | An alternative to CRUSH with measured balance and memory cost | ch08, ch28 | no | to review |
| Horus: Fine-Grained Encryption-Based Security for Large-Scale Storage (and the PDSW '11 version) | Y. Li, N. Dhotre, Y. Ohara, T. Kroeger, E. L. Miller, D. D. E. Long; R. Rajendran, E. L. Miller, D. D. E. Long | 2013 (2011) | FAST 2013; PDSW '11 | [FAST](https://www.ssrc.us/pub/li-fast13.html), [PDSW](https://www.ssrc.us/pub/rajendran-pdsw11.html) | Per-region keys for large datasets; context for RBD and RGW encryption | ch02, ch04 | no | to review |
| ASCAR: Automating Contention Management for High-Performance Storage Systems | Y. Li, X. Lu, E. L. Miller, D. D. E. Long | 2015 | MSST 2015 | [page](https://www.ssrc.us/pub/li-msst15.html) | Client-side traffic control rules to cut contention | ch21 | no | to review |
| Pilot: A Framework that Understands How to Do Performance Benchmarks The Right Way | Y. Li, Y. Gupta, E. L. Miller, D. D. E. Long | 2016 | MASCOTS 2016 | [page](https://www.ssrc.us/pub/li-mascots16.html) | Statistical rigour for benchmark runs (warm-up, confidence intervals) | ch10 | no | to review |
| RESAR: Reliable Storage at Exabyte Scale | T. Schwarz, A. Amer, T. Kroeger, E. L. Miller, D. D. E. Long, J.-F. Pâris | 2016 | MASCOTS 2016 | [page](https://www.ssrc.us/pub/schwarz-mascots16.html) | Flexible parity layouts at very large scale; compare with LRC/CLAY plugins | ch13, ch27 | no | to review |
| CAPES: Unsupervised Storage Performance Tuning Using Neural Network-Based Deep Reinforcement Learning | Y. Li, O. Bel, K. Chang, E. L. Miller, D. D. E. Long | 2017 | SC '17 | [page](https://www.ssrc.us/pub/li-sc17.html) | Automatic parameter tuning; a research contrast to manual tuning in ch21 | ch21 | no | to review |
| Strong Security for Network-Attached Storage | E. L. Miller, D. D. E. Long, W. E. Freeman, B. C. Reed | 2002 | FAST 2002 | [page](https://www.ssrc.us/pub/miller-fast02.html) | Early encrypted, authenticated network storage; prior work for cephx and msgr2 secure mode | ch26 | no | to review |
