---
chapter: 18
id: ch18
title: 'Disaster Recovery: rbd-mirror, Stretch Mode and Cluster Rescue'
part: main
lang: en
---

::: {.tldr}

- Replication is not backup: you also need copies out of reach of the same credentials, such as protected snapshots or another cluster.
- rbd-mirror runs on the destination and pulls; snapshot mode is the usual default, journal mode is for RPOs of seconds.
- Stretch mode keeps one cluster across two sites with a tiebreaker MON, for zero RPO when a whole site is lost.
- If all MONs are lost, the monitor store can be rebuilt from the OSDs; `ceph-objectstore-tool` can export and import PGs from a dead OSD's readable disk.

:::

# Before you start {#sec-18-1}

## What questions does this chapter answer? {#sec-18-1-1}

"Disaster recovery" in Ceph is not a single feature but several layers of defence, each protecting against a particular kind of disaster. Three-way replication protects against disk and host failure, but it can do nothing against the accidental deletion of a pool, ransomware or the complete loss of a data centre. This chapter reviews the layers from inside a cluster to an independent backup, and explains the two main mechanisms down to the code level: **rbd-mirror** and **stretch mode**.

- What are the RPO and RTO of each layer, and which layer protects against which disaster?
- How does rbd-mirror work in its two modes, journal and snapshot?
- How do planned and emergency failover differ, and how is split-brain resolved?
- How does stretch mode keep one cluster across two sites with an RPO of zero?
- If all MONs are lost, how do we rebuild the maps from the OSDs?
- What must be backed up separately from Ceph?

# Layers of defence {#sec-18-2}

![Four layers of defence against disaster: inside the cluster with replication and automatic recovery, between two sites with one stretched cluster (stretch mode) and an RPO of zero, between independent clusters with asynchronous replication via rbd-mirror, RGW multisite and cephfs-mirror, and finally an independent backup with object lock and a configuration backup](figures/ch18/f01_layers.png){#fig-18-f01_layers}

| Layer | Protects against | Does not protect against | Approximate RPO |
|---|---|---|---|
| Replication/EC inside the cluster | Disk, host, rack failure | Accidental deletion, software bugs, site loss | Zero |
| stretch mode | Loss of one site | Accidental deletion, simultaneous failure of both sites | Zero |
| rbd-mirror / multisite | Complete loss of a cluster or site | Accidental deletion (it gets replicated!) | Seconds to minutes |
| Independent backup with object lock | Accidental deletion, ransomware, logical corruption | — | The backup interval |

::: {.warn}
Replication is not backup. An `rbd rm` on the primary site, or deleting a bucket, is carried to the second site by asynchronous replication too. For human error and ransomware you need a copy that is **out of reach of the same credentials**: protected snapshots, object lock in COMPLIANCE mode, or a backup in another system.
:::

# rbd-mirror {#sec-18-3}

## Two modes {#sec-18-3-1}

| Feature | journal-based | snapshot-based |
|---|---|---|
| Mechanism | Each write is first recorded in the image's journal (RADOS objects) and then replayed | Periodic mirror snapshots and transfer of the difference between them |
| Consistency | Crash-consistent at every moment; write order is preserved | Crash-consistent at each snapshot boundary |
| Write overhead | Each write twice (once in the journal and once in the image) | Low; only when creating snapshots and transferring differences |
| RPO | Seconds | The schedule interval (for example 5 to 15 minutes) |
| Kernel client (krbd) | The journaling feature is not supported in krbd (check your kernel's feature list) | Usable |
| Prerequisite | The journaling image feature (requires exclusive-lock); since Jewel | Snapshot scheduling in the mgr; since Octopus |

::: {.tip}
For most deployments today, **snapshot mode** is the better default choice: it has little write overhead, works with krbd and behaves more simply. Keep journal mode for workloads that truly need an RPO of a few seconds and accept the cost of doubled writes.
:::

## Setup (snapshot mode) {#sec-18-3-2}

```bash
# on both clusters: the rbd-mirror service (in cephadm)
ceph orch apply rbd-mirror --placement=1
# site A
rbd mirror pool enable --site-name site-a vmpool image
rbd mirror pool peer bootstrap create --site-name site-a vmpool > /tmp/token
# site B (transfer the token securely; it contains a cephx key)
rbd mirror pool enable --site-name site-b vmpool image
rbd mirror pool peer bootstrap import --site-name site-b --direction rx-tx vmpool /tmp/token
# enable for one image, and the schedule
rbd mirror image enable vmpool/db01 snapshot
rbd mirror snapshot schedule add --pool vmpool 15m
rbd mirror snapshot schedule status --pool vmpool
rbd mirror pool status vmpool --verbose
```

::: {.warn}
The token output by `peer bootstrap create` contains a cephx credential for the other site's access. Transfer it like a password and delete it after the import; do not put it in logs or tickets.
:::

# Inside the code: rbd-mirror {#sec-18-4}

## Daemon structure {#sec-18-4-1}

`rbd-mirror` (`src/tools/rbd_mirror/`) is a standalone daemon that runs in the **destination** cluster and **pulls** from the source cluster. It builds one `PoolReplayer` per pool and one `ImageReplayer` per image. Depending on the image's mode, `ImageReplayer` uses one of two implementations: `image_replayer/journal/Replayer` or `image_replayer/snapshot/Replayer`. Several rbd-mirror daemons in a cluster coordinate with each other (through leader election on RADOS objects) and divide the images among themselves.

## Snapshot mode: the algorithm {#sec-18-4-2}

Each mirror snapshot is recorded in the snapshot namespace with the `MirrorSnapshotNamespace` structure (`src/cls/rbd/cls_rbd_types.h`). The key fields:

| Field | Meaning |
|---|---|
| state | PRIMARY, PRIMARY_DEMOTED, NON_PRIMARY or NON_PRIMARY_DEMOTED |
| complete | For a destination snapshot: whether copying the difference has finished |
| mirror_peer_uuids | Peers that still need this snapshot |
| primary_mirror_uuid / primary_snap_id | At the destination: the corresponding snapshot at the source |
| last_copied_object_number | The resume point for an unfinished copy |

![One round of snapshot-based synchronization: site A creates a primary snapshot S2 according to the schedule; rbd-mirror at site B scans both sides' snapshots, creates an incomplete snapshot S2' at the destination, transfers the difference from S1 to S2 with deep-copy, applies the image state and marks the snapshot complete, and finally removes the peer link from S1 so that it can be deleted](figures/ch18/f02_snapmirror.png){#fig-18-f02_snapmirror}

The order of functions in `snapshot/Replayer.cc` follows exactly this path: `load_local_image_meta` → `refresh_remote_image` / `refresh_local_image` → `scan_local_mirror_snapshots` → `scan_remote_mirror_snapshots` → `create_non_primary_snapshot` → `copy_image` → `apply_image_state` → `update_non_primary_snapshot(complete=true)` → `unlink_peer`.

```text
pseudocode: one Replayer round (this book's rewrite)
  local_last  = the last complete NON_PRIMARY snapshot at the destination
  remote_from = the source snapshot matching local_last.primary_snap_id
  remote_to   = the first PRIMARY snapshot after remote_from whose mirror_peer_uuids includes our peer
  if none: wait for remote image update notification; return
  if local has incomplete snapshot for remote_to: resume from last_copied_object_number
  else: create_non_primary_snapshot(remote_to, complete=false)
  deep_copy(remote, local, snap range = (remote_from, remote_to])   # only changed objects
  apply_image_state(size, metadata, snapshot names)
  mark local snapshot complete
  unlink_peer(remote_from)        # the source can prune the old snapshot
```

::: {.deep}
Why does "complete=false" matter? If rbd-mirror stops in the middle of a copy, the destination image is a mix of S1 and part of S2, that is, **inconsistent**. The existence of an incomplete snapshot tells the tools that the last consistent point is the previous complete snapshot. On an emergency promote, librbd rolls the destination image back to the last complete snapshot (the rollback step in `librbd/mirror/snapshot/PromoteRequest.cc`) so that the application sees consistent data. This is the crash-consistency guarantee at the snapshot boundary.
:::

## Journal mode: the algorithm {#sec-18-4-3}

In journal mode, librbd appends each write to the **journal** (the `src/journal/` library, which stores events in RADOS objects of the same pool) before applying it to the image. At the destination, rbd-mirror connects to the source journal with `init_remote_journaler`, reads the events, prepares them with `preprocess_entry` (for example mapping snapshot ids) and replays them on the local image with `process_entry`. The replay position is recorded in the source journal with `flush_commit_position` so that the source can trim the consumed parts.

::: {.warn}
If the destination rbd-mirror is down for a long time, the source journal grows and consumes space. Its limit and behaviour are controlled by options such as `rbd_journal_max_payload_bytes` and `rbd_mirroring_resync_after_disconnect` and the journal settings; monitoring `rbd mirror pool status` and alerting on images in the `unknown` or `error` state is essential.
:::

## Failover and failback {#sec-18-4-4}

![Two failover scenarios: in the planned case the application is stopped, the image is demoted in A, promoted in B after syncing, and the application is started in B, with no data lost; in the emergency case B is activated with promote --force, and after A returns, A's image is demoted and resynchronized from B with resync](figures/ch18/f03_failover.png){#fig-18-f03_failover}

```bash
# planned
rbd --cluster site-a mirror image demote vmpool/db01
rbd --cluster site-b mirror image status vmpool/db01      # wait for up+replaying and sync
rbd --cluster site-b mirror image promote vmpool/db01
# emergency (site A is unavailable)
rbd --cluster site-b mirror image promote --force vmpool/db01
# after A returns: prevent two primaries
rbd --cluster site-a mirror image demote vmpool/db01
rbd --cluster site-a mirror image resync vmpool/db01
```

::: {.note}
After a forced promote, if site A returns and its image is still primary, we have two primaries (split-brain), and rbd-mirror stops synchronizing. `resync` discards the local copy and copies afresh from the current primary; any write made on A after the disconnection is lost. Write this explicitly in the runbook.
:::

# The lower layer: the journal on RADOS and the stretch state machine {#sec-18-5}

## The journal format in journal-based mirroring {#sec-18-5-1}

The `src/journal/` library is a general-purpose journal on RADOS, and librbd is only one of its consumers. Each image has a **header object** named `journal.<image_id>`, whose omap holds the order (object size), splay_width, the active set number, the list of clients (such as each peer's rbd-mirror) and each one's commit position. Data is written to objects named `journal_data.<pool_id>.<image_id>.<n>` (the constants `JOURNAL_HEADER_PREFIX` and `JOURNAL_OBJECT_PREFIX` in `Journaler.cc`).

![The journal layout of an RBD image. The header is in the omap of the journal.<id> object. Data is in sets of splay_width objects, and each entry is appended to one of the active set's objects according to entry_tid % splay_width. When one of the objects reaches $2^{\mathit{order}}$ bytes, the whole set is closed and the next set becomes active. Sets that all clients have passed are deleted](figures/ch18/f06_journal.png){#fig-18-f06_journal}

In `JournalRecorder.cc`, two simple relations determine everything:

```text
splay_offset  = entry_tid % splay_width
object_number = splay_offset + active_set * splay_width
```

With the defaults (`rbd_journal_order=24`, that is 16MiB, and `rbd_journal_splay_width=4`), the entry with tid=10 in active set 3 goes to object number 2+3×4=14. Spreading entries over four objects spreads the appends across four PGs (and usually four primary OSDs) so that one hot object does not become a bottleneck. Each set holds at most 4×16MiB=64MiB of data.

### The bytes of an entry

`Entry::encode` writes a fixed 25-byte header part (preamble, version, entry_tid, tag_tid) and a fixed 8-byte trailer (data length and crc). The preamble is the constant `0x3141592653589793` (the digits of π), which is checked on read-back to find entry boundaries and detect corrupt data. The crc is computed with `crc32c(0)` over everything except the crc itself.

| Offset | Length | Field | Example (tid=10, tag=1, data "ABCD") |
|---|---|---|---|
| 0 | 8 | preamble (LE) | `93 97 58 53 26 59 41 31` |
| 8 | 1 | version | `01` |
| 9 | 8 | entry_tid | `0a 00 00 00 00 00 00 00` |
| 17 | 8 | tag_tid | `01 00 00 00 00 00 00 00` |
| 25 | 4 | data length | `04 00 00 00` |
| 29 | 4 | data | `41 42 43 44` |
| 33 | 4 | crc32c(0) of bytes 0 to 32 | `75 7d a6 34` (=0x34A67D75) |

::: {.note}
We computed this crc value with an independent crc32c implementation (the Castagnoli polynomial, seed=0, no final inversion, like `ceph_crc32c`). The same function reproduces the standard value 0xE3069283 for "123456789" with seed=~0 and a final xor. In librbd, each entry's data is an encoded librbd event (for example AioWrite with offset, length and bytes), and `rbd_journal_max_payload_bytes=16K` limits the largest data piece per entry. A 64K write is split into several entries.
:::

::: {.warn}
**The real cost of the journal:** every client write is written twice, once in journal_data and once in the image. In addition, librbd waits for the write to be safely recorded in the journal before applying it to the image. So write latency roughly doubles and the pool's write bandwidth doubles. This is the main reason for preferring snapshot-based mirroring in most deployments today. If a journal is needed, it can be placed in a faster pool with `rbd_journal_pool`.
:::

```bash
rbd journal info --pool vmpool --image db01        # order, splay_width, object_pool
rbd journal status --pool vmpool --image db01      # active_set, minimum_set, clients' commit positions
rados -p vmpool ls | grep '^journal_data\.' | sort -t. -k4 -n | tail -4
rbd journal inspect --pool vmpool --image db01 --verbose | head   # check entry consistency
```

### Options that matter in rbd-mirror

| Option | Default (main) | Effect |
|---|---|---|
| `rbd_mirror_concurrent_image_syncs` | 5 | Maximum concurrent full syncs (image bootstrap) |
| `rbd_mirroring_max_mirroring_snapshots` | 5 | Cap on mirror snapshots per image; older ones are pruned |
| `rbd_mirroring_replay_delay` | 0 | Deliberate replay delay (seconds) to protect against human error |
| `rbd_mirror_memory_target` | 4G | The daemon's memory target (cache) |
| `rbd_mirror_image_state_check_interval` | 30 | Interval for checking image states (seconds) |
| `rbd_mirror_concurrent_image_deletions` | 1 | Concurrent deletions of images deleted at the source |
| `rbd_journal_commit_age` | 5 | Maximum age of the commit position before a flush (seconds) |

::: {.tip}
`rbd_mirroring_replay_delay` builds a "delayed DR". If someone corrupts the database at the source, the destination still has the healthy copy for N seconds. This makes sense in journal mode. In snapshot mode, the snapshot schedule interval plays the same role.
:::

## The stretch mode state machine in the code {#sec-18-5-2}

![The three stretch mode states and the pg_pool_t values in each (the logic of the functions trigger_degraded_stretch_mode, trigger_recovery_stretch_mode and trigger_healthy_stretch_mode in OSDMonitor.cc in Squid). The min_size values are for the default stretch pool with size=4](figures/ch18/f07_stretchfsm.png){#fig-18-f07_stretchfsm}

In stretch mode the OSDMap has five fields: `stretch_mode_enabled`, `stretch_bucket_count` (the number of sites, currently 2), `degraded_stretch_mode` (0 or the number of live sites), `recovering_stretch_mode` and `stretch_mode_bucket` (the bucket type, for example datacenter). Each stretched pool also has four peering fields: `peering_crush_bucket_count`, `peering_crush_bucket_target`, `peering_crush_bucket_barrier` and `peering_crush_mandatory_member`.

The heart of the matter is the function `pg_pool_t::stretch_set_can_peer`. Before a PG can become active with an acting set, the OSDs' ancestors at the barrier level (datacenter) are counted:

```text
pseudocode: stretch_set_can_peer (summary)
  if pool is not stretch: return true
  sites = { crush.parent_of_type(osd, barrier) for osd in want }
  if |sites| < peering_crush_bucket_count: return false     # all sites are required
  if mandatory_member != NONE and mandatory_member not in sites: return false
  return true
```

That is, in the healthy state **no stretched PG becomes active with OSDs from only one site**, even if it has min_size copies. This is the main barrier against split-brain: if the link between the sites breaks and the MONs have not yet marked the state degraded, the PGs stop rather than accept writes at one site. Only after the MONs decide (with the tiebreaker) and enter DEGRADED does the count drop to 1, and `mandatory_member` is set to the surviving site. Even if the dead site comes back, it cannot activate a PG on its own until recovery ends.

| State | bucket_count | mandatory_member | min_size (size=4) | Tolerance |
|---|---|---|---|---|
| HEALTHY | 2 | NONE | 2 | Loss of 2 OSDs, provided both sites are present |
| DEGRADED | 1 | The surviving site | 1 | Only the surviving site; one copy is enough (high risk) |
| RECOVERY | 1 (until the end) | The surviving site | 1 | Backfill to the returned site |

::: {.warn}
**Take min_size=1 seriously.** In DEGRADED, the default `min_size` of 2 is halved to 1. If during this period one of a PG's two remaining OSDs is also lost, the PG keeps writing with one copy, and the next failure means data loss. During the degraded period, stop disk replacements and planned maintenance at the surviving site.
:::

::: {.note}
**Version-dependent.** The table above was read from Squid's code. In the main branch (after `num_zones` was introduced per pool), `mon_stretch_pool_size=4` and `mon_stretch_pool_min_size=2` appear in the options documentation with the LEGACY tag, and the min_size formula is different for pools with num_zones. On your own version, read `ceph osd pool ls detail` and look for `peering_crush_bucket_count` and `min_size`.
:::

```bash
ceph osd dump | grep -E 'stretch_mode|degraded_stretch|recovering_stretch'
ceph osd pool ls detail | grep -E 'peering_crush|min_size'
ceph mon dump | grep -E 'tiebreaker|stretch|location'
ceph config get mon mon_stretch_cluster_recovery_ratio   # 0.6
```

# Disaster recovery in numbers: MON connection scores, connectivity elections and image distribution in rbd-mirror {#sec-18-6}

The three algorithms in this section determine which MON becomes leader in a two-site cluster, and which rbd-mirror daemon replicates which image. References are to main as of November 2026. The scenarios are hypothetical, but all numbers were computed with a Python reimplementation of the same formulas.

## The connection score of each MON pair {#sec-18-6-1}

::: {.algo #alg-18-1 title="Updating the connection score in ConnectionTracker" src="src/mon/ConnectionTracker.cc :: report_live_connection, report_dead_connection, get_total_connection_score; src/mon/Elector.cc :: ping_check, dead_ping" complexity="O(1) per ping and O(number of MONs) for the total score"}
:::

```text
pseudocode
h = mon_con_tracker_score_halflife (43200 s) ; each peer's initial score 1.0
ping every mon_elector_ping_timeout / divisor = 2 / 2 = 1 s ; after 2 s without a reply, the peer is "dead"
live reply after u seconds:  s = min(1, s × (1 − u/2h) + u/2h)
no reply for u seconds (every 2 s):     s = max(0, s × (1 − u/2h) − u/2h)
score(r) = Σ over the other MONs' reports: history[r], only if current[r] is alive
```

**Numerical example.** With α = u / 86400, a connection that dies from a score of 1 reaches 0.986 after 10 minutes, 0.918 after one hour, 0.558 after six hours, 0.213 after twelve hours, and zero after exactly 59888 seconds (86400 × ln 2, about 16.6 hours). Recovery is equally slow: going from 0 to 0.5 takes about 16.6 hours. This long memory is deliberate: a connection that keeps dropping and reconnecting should not be counted as "healthy" again after a few successful pings.

![A peer's score in ConnectionTracker. Red: a connection that drops from a full score and reaches zero after 16.6 hours. Green: recovery from zero. The slope of both is set by the 43200-second half-life. The points are values computed with 2-second steps](figures/ch18/f08_score.png){#fig-18-f08_score}

## Elections with the connectivity strategy {#sec-18-6-2}

::: {.algo #alg-18-2 title="Comparing proposals in ElectionLogic" src="src/mon/ElectionLogic.cc :: connectivity_election_score, propose_connectivity_handler" complexity="O(number of MONs)"}
:::

```text
pseudocode
score(r) = −1 if r is in disallowed_leaders (e.g. the tiebreaker in stretch mode) ; otherwise get_total_connection_score(r)
on receiving PROPOSE from f:
    if I am the tiebreaker and f is marked down: ignore
    my_win = my ≥ 0 and (my > from or (my == from and my rank < f))
    if my_win: propose myself
    elif from is better than me and than the currently acked leader: ACK f
votes are not changed for an improvement smaller than mon_elector_ignore_propose_margin (0.0005)
```

**Numerical example.** We have five MONs: a and b in DC1, c and d in DC2, and e as the tiebreaker, which is not allowed to become leader. Suppose a's link to c and d has been down for an hour and everything else is healthy. a's score is summed only from the live reports of b and e and is 2.0. b's score is four (1 from each of a, c, d and e). c and d each have 3, because a's report about them is "dead" and is not counted. So b becomes leader. With the classic strategy, a would remain leader merely because of its lower rank, even though it cannot reach half the cluster. After the links reconnect, a's score is 1 + 0.918 + 0.918 + 1 = 3.837, still less than b's (4.0), so leadership does not change. The default mon_election_default_strategy is 1 (classic). stretch mode requires the connectivity strategy, which is set with `ceph mon set election_strategy connectivity`.

![Election scores of five MONs in the scenario where a's link to DC2 is down. Left: during the outage, b wins with a score of 4. Right: after reconnecting, a's score history is still damaged, and b, which has a lower rank than c and d in a tie, remains leader. e, as the tiebreaker, has a score of −1](figures/ch18/f09_election.png){#fig-18-f09_election}

![The proposal handling logic in the connectivity strategy. The first row is the tiebreaker ignoring a proposal from a down MON, and computing three scores. The second row is the decision between proposing oneself and ACKing another. The third row shows two side rules: a score of −1 for disallowed leaders, and a margin of 0.0005 to prevent oscillating votes](figures/ch18/f11_propose.png){#fig-18-f11_propose}

## Distributing images among rbd-mirror daemons {#sec-18-6-3}

::: {.algo #alg-18-3 title="SimplePolicy: mapping and moving images" src="src/tools/rbd_mirror/image_map/SimplePolicy.cc :: calc_images_per_instance, do_shuffle_add_instances, do_map; src/tools/rbd_mirror/image_map/Policy.cc :: can_shuffle_image; src/tools/rbd_mirror/ImageMap.cc :: schedule_rebalance_task" complexity="O(images × instances) per shuffle"}
:::

```text
pseudocode
per = max(1, ⌊number of images / live instances⌋)
when an instance is added:
    for each instance with more than per images: cut = size − per
        walk its images in order: if being moved, cut−− ; elif can_shuffle: cut−− and mark it
can_shuffle = idle and (now − mapped_time ≥ rbd_mirror_image_policy_migration_throttle (300 s))
do_map(img) = the live instance with the fewest images
periodic rebalance only if rbd_mirror_image_policy_rebalance_timeout > 0 (default 0 = off)
```

**Numerical example.** 100 old images are on daemon A. B is added at t = 0: per = 50, so 50 images go to B (50/50). C is added at t = 200 seconds: per = 33. A must give up 17 images and does. B must also give up 17 images, but all of its images were mapped less than 300 seconds ago, so none of them move. The result is 33/50/17. Because periodic rebalancing is off by default, **this imbalance remains until the next membership change**. If `rbd_mirror_image_policy_rebalance_timeout` is, say, 300, the map is spread again once it settles, and the result is 34/33/33. If A dies, its 34 images go one by one to the least loaded instance, and the result is 50/50. Each move means releasing and re-acquiring the image and starting replay from the last snapshot. So bring rbd-mirror instances up together, not minutes apart.

![Distribution of 100 images among rbd-mirror daemons with SimplePolicy across five events. The third column shows the effect of migration_throttle: B's freshly moved images cannot be moved for 300 seconds, and C gets only 17 images. The fourth column happens only when rebalance_timeout is non-zero. Our simulation, based on SimplePolicy.cc](figures/ch18/f10_imagemap.png){#fig-18-f10_imagemap}

# stretch mode: one cluster across two sites {#sec-18-7}

## The model {#sec-18-7-1}

stretch mode is for when you have two data centres with low latency (a few milliseconds) and want to tolerate the complete loss of one of them **without data loss** (RPO of zero) and with continued service. Each site keeps a full copy of the data, and a tiebreaker MON at a third site, which holds no data, decides which site stays active when the two sites lose contact.

![stretch mode topology: two data centres, each with two MONs and OSDs that hold two copies of every PG, and a data-less tiebreaker MON at a third site; every write is recorded at both sites before the ack, and if the link between the two sites breaks, the tiebreaker determines the winning site](figures/ch18/f04_stretch.png){#fig-18-f04_stretch}

## Configuration in released versions (Squid, Tentacle, Umbrella) {#sec-18-7-2}

The general procedure in these versions' documentation:

1. Create `datacenter` buckets in CRUSH and move the hosts into them.
2. Set each MON's location with `ceph mon set_location <mon> datacenter=<site>`.
3. Create a CRUSH rule that places two copies in each datacenter (in the documentation, by editing the CRUSH map).
4. Change the MON election strategy to `connectivity`.
5. Enable with `ceph mon enable_stretch_mode <tiebreaker-mon> <rule> datacenter`.

```bash
ceph osd crush add-bucket site1 datacenter
ceph osd crush add-bucket site2 datacenter
ceph osd crush move site1 root=default
ceph osd crush move site2 root=default
ceph osd crush move stor-a1 datacenter=site1      # and the other hosts
ceph mon set_location a datacenter=site1
ceph mon set_location b datacenter=site1
ceph mon set_location c datacenter=site2
ceph mon set_location d datacenter=site2
ceph mon set_location e datacenter=site3
ceph mon set election_strategy connectivity
ceph mon enable_stretch_mode e stretch_rule datacenter
```

::: {.note}
**Version-dependent.** The rule name in the documentation example is `stretch_rule` in Squid and Tentacle and `stretch_replicated_rule` in Umbrella; the rule name is arbitrary, but it must match the rule you created. The documentation of the latest branch (the version under development) describes a new model in which each pool is stretched with `num_zones`, EC pools can also be spread across two zones, and the commands `ceph osd pool create ... --num_zones 2` and `ceph osd pool default set` are introduced; this does not exist in the umbrella and tentacle pages, and you must check your cluster's version before using it.
:::

## Behaviour on failure {#sec-18-7-3}

When one site is lost, the cluster enters **degraded stretch mode**: the MONs form a quorum with the tiebreaker and, according to the Tentacle documentation, the pools' min_size drops to 1 (size does not change) so that the PGs stay active with the copies at the surviving site; that is, during this period you have only two copies at one site and the safety margin is small. After the site returns, the cluster goes into recovery and, once the PGs have synchronized, returns to normal.

::: {.warn}
stretch mode increases write latency by **the round trip between the two sites**, because every write must be recorded at both sites before the ack. Before deploying, measure the real RTT and test a sample workload with it. The tiebreaker MON must be at an independent third site; placing it at one of the two sites defeats the purpose.
:::

# When all MONs are lost {#sec-18-8}

## Prevention {#sec-18-8-1}

- At least three, and preferably five, MONs on reliable disks with correct flush and write settings.
- **Since Umbrella:** periodic backups of the monitor's RocksDB with `mon_backup_interval`, manual backups with `ceph tell mon.* backup` and restoring with `ceph-mon --restore-backup` (chapter 8). This is the simplest and safest way to recover a MON.
- Separate backups of `ceph config dump`, `ceph auth export` and the service specifications from `ceph orch ls --export` somewhere outside the cluster (encrypted, because they include keys).

## Rebuilding from the OSDs {#sec-18-8-2}

If no backup exists, the official documentation (Troubleshooting Monitors, section Monitor Store Failures) gives a procedure for rebuilding the monitor store from the maps that each OSD keeps. A summary in this book's words:

![The procedure for rebuilding the monitor store from the OSDs in two stages: first, on each OSD host with the OSDs stopped, ceph-objectstore-tool with the update-mon-db operation collects the maps into a shared store directory, and this directory is carried from host to host; then ceph-monstore-tool rebuilds the store with the admin key and the MON ids, and store.db is replaced on the MONs](figures/ch18/f05_monrebuild.png){#fig-18-f05_monrebuild}

1. Stop all OSDs.
2. Create an empty store directory and take it to each OSD host in turn; on each host, for each OSD, run `ceph-objectstore-tool --data-path <osd> --no-mon-config --op update-mon-db --mon-store-path <dir>` to add that OSD's maps to the store; then bring the accumulated store back.
3. Build a keyring containing the `mon.` and `client.admin` keys (and the mgr keys) with the necessary caps.
4. Run `ceph-monstore-tool <dir> rebuild -- --keyring <keyring> --mon-ids <ids>` (the order of the ids matters if they are not sorted by IP).
5. Make a copy of the broken store.db, replace it with the rebuilt store, fix the file ownership and start the MONs.

::: {.warn}
Documented limitations of this procedure: the MDS keyrings and many other keyrings are not recovered and must be added again; pools that were being created may have `unknown` PGs (the documentation mentions `ceph osd force-create-pg` for this case); and other settings that existed only in the MON may be lost. In cephadm, the paths are under `/var/lib/ceph/<fsid>/`, and the commands must run inside `cephadm shell` with the right mounts. Practise this procedure in a lab **before you need it**.
:::

# Rescuing data from an OSD {#sec-18-9}

On a stopped OSD, `ceph-objectstore-tool` can list, export and import PGs (chapter 17). Its DR use is when several OSDs have been lost at once and a PG is stuck incomplete or down, but the disk of one of the dead OSDs is still readable.

```bash
# inside cephadm shell for the stopped OSD
ceph-objectstore-tool --data-path /var/lib/ceph/osd/ceph-12 --op list-pgs
ceph-objectstore-tool --data-path /var/lib/ceph/osd/ceph-12 --pgid 2.5 --op info
ceph-objectstore-tool --data-path /var/lib/ceph/osd/ceph-12 --pgid 2.5 --op export --file /backup/2.5.export
# on the destination OSD (stopped)
ceph-objectstore-tool --data-path /var/lib/ceph/osd/ceph-30 --op import --file /backup/2.5.export
```

# Independent backup {#sec-18-10}

- **RBD**: `rbd export-diff` between snapshots and `rbd import-diff` into another cluster or store; or VM-level backup tools.
- **RGW**: bucket versioning together with **S3 Object Lock** in COMPLIANCE mode, so that even an administrator cannot delete before the period ends (chapter 4); synchronization to external storage.
- **CephFS**: directory snapshots and `cephfs-mirror` to another cluster (since Pacific; chapter 6).
- **Configuration**: the output of `ceph orch ls --export`, `ceph config dump` and the keyrings.

| Disaster | First action |
|---|---|
| Complete failure of one site with stretch mode | Check degraded stretch mode and the quorum with the tiebreaker |
| Loss of the main cluster with rbd-mirror | promote --force at the second site and accept the RPO |
| Accidental deletion of an RBD image | Check the RBD trash with `rbd trash ls` and `rbd trash restore` |
| Loss of all MONs | Restore from a MON backup (Umbrella) or rebuild from the OSDs |
| Incomplete PG after several disk failures | Bring the OSDs back; otherwise export/import with ceph-objectstore-tool |

::: {.summary title="SRE notes for this chapter"}

- Write down the RPO and RTO of each service and choose the appropriate layer.
- Asynchronous replication replicates deletions too; an independent backup with object lock is necessary.
- Practise failover periodically; an unwritten runbook does not work in a crisis.
- Keep tokens and keyrings like passwords.
- Practise rebuilding the MONs from the OSDs in a lab before you need it.

:::

# Supplementary and up to date {#sec-18-11}

- Snapshot-based mirroring has been available since Octopus and has become a suitable replacement for the journal for most uses.
- Umbrella added built-in backups of the monitor store (chapter 8).
- The documentation of the development branch describes the new stretch model with `num_zones`; until it is officially released in a version, use the enable_stretch_mode procedure.
- `ceph-deploy`, which old rebuilding procedures used, has been archived; all procedures today are done with cephadm.

# Hands-on exercise {#sec-18-12}

1. Build two small clusters, enable snapshot mirroring for one image and measure the sync lag with `rbd mirror image status`.
2. Perform a planned failover and confirm that no data was lost (file checksums).
3. Simulate an emergency failover by cutting site A's network; then run the resync procedure.
4. In `snapshot/Replayer.cc`, find where copying resumes from `last_copied_object_number`.
5. In a lab, delete one MON's store and run the full rebuild-from-OSDs procedure.
6. Create a bucket with object lock in COMPLIANCE mode and try to delete from it.

# Review questions {#sec-18-13}

1. Why is replication not a substitute for backup?
2. What is the difference between journal-based and snapshot-based mirroring in overhead and RPO?
3. What role does the complete field in MirrorSnapshotNamespace play?
4. In which cluster does rbd-mirror run, and why does it pull?
5. What must be done after promote --force when the previous site returns?
6. What is the role of the tiebreaker MON in stretch mode?
7. What effect does stretch mode have on write latency?
8. What information is lost when rebuilding the MONs from the OSDs?
9. What tool has Umbrella added for MON backups?
10. What is ceph-objectstore-tool used for in DR, and what is its prerequisite?

# Sources for this chapter {#sec-18-14}

- RBD mirroring: https://docs.ceph.com/en/latest/rbd/rbd-mirroring/
- Stretch mode (Tentacle): https://docs.ceph.com/en/tentacle/rados/operations/stretch-mode/
- Stretch mode (Umbrella): https://docs.ceph.com/en/umbrella/rados/operations/stretch-mode/
- Stretch mode (latest/dev): https://docs.ceph.com/en/latest/rados/operations/stretch-mode/
- Troubleshooting monitors (Monitor Store Failures): https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-mon/
- CephFS mirroring: https://docs.ceph.com/en/latest/cephfs/cephfs-mirroring/
- RGW S3 bucket operations (object lock config): https://docs.ceph.com/en/latest/radosgw/s3/bucketops/
- Source: src/tools/rbd_mirror: https://github.com/ceph/ceph/tree/main/src/tools/rbd_mirror
- Source: src/cls/rbd/cls_rbd_types.h: https://github.com/ceph/ceph/blob/main/src/cls/rbd/cls_rbd_types.h
- Source: src/librbd/mirror/snapshot: https://github.com/ceph/ceph/tree/main/src/librbd/mirror/snapshot
