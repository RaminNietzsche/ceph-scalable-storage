---
chapter: 32
id: ch32
title: 'Lower Layers (10): Scrub, Recovery, Backfill and Repair at Code Level'
part: lower
lang: en
---

::: {.tldr}

- Scrub lives in `src/osd/scrubber/`: PgScrubber, a statechart ScrubMachine, ScrubBackend for comparisons, and OSD-level scheduling.
- Each PG has shallow and deep scrub targets with times and urgency; operator requests come first.
- After peering, recovery fills missing objects from the log, while backfill copies whole PGs to targets without log overlap.
- Repair reuses recovery with an artificial missing list, so recovery limits (reservations, `osd_max_backfills`) apply to it too.

:::

# Chapter map {#sec-32-1}

We examine three data-correctness mechanisms of the OSD at the code level:

- **scrub**: periodically comparing the copies of a PG on different OSDs. shallow compares only metadata and size, and deep reads all the data and omap and builds digests.
- **recovery and backfill**: restoring missing copies. recovery is based on the pg log, and backfill on a full scan of the content.
- **repair**: a combination of the two. scrub finds the authoritative copy and recovery puts it in place of the damaged copy.

Since Quincy, the scrub code in `src/osd/scrubber/` has been split into several components: `PgScrubber` (the per-PG logic), `ScrubMachine` (a boost::statechart state machine), `ScrubBackend` (comparing the maps), `OsdScrub` and `ScrubQueue` (scheduling at the OSD level) and `ScrubResources` and `ScrubReservations` (reservation). All references are to main. The defaults were read from `osd.yaml.in` in the same branch.

# Scheduling scrub {#sec-32-2}

## Targets and randomization {#sec-32-2-1}

Each PG has a `ScrubJob` with two **targets** (`shallow_target` and `deep_target`). Each target has `scheduled_at` (the desired time), `not_before` (the earliest allowed time) and an **urgency**. The urgencies range from periodic_regular to operator_requested and must_repair. Only periodic targets are randomized (`requires_randomization`).

::: {.algo #alg-32-1 title="Randomized scrub scheduling (uniform for shallow, truncated normal for deep)" src="src/osd/scrubber/scrub_job.cc :: ScrubJob::adjust_shallow_schedule, adjust_deep_schedule" complexity="O(1) per PG; the OSD queue is sorted in O(log n)"}
:::

```text
pseudocode
shallow: target = last_scrub + I_s + I_s × ratio × U(0,1)          # I_s = osd_scrub_min_interval
         not_before = max(last_scrub, target)
deep:    sd = I_d × cv                                              # cv = osd_deep_scrub_interval_cv
         delay = clamp(Normal(I_d, sd), I_d − 2sd, I_d + 2sd)
         target = not_before = last_deep + delay
initiate_scrub (on every OSD tick):
   if random() < osd_scrub_backoff_ratio: skip           # coin toss: 0.66
   if loadavg/ncpu ≥ osd_scrub_load_threshold: only mandatory scrubs
   take the earliest eligible target (not_before ≤ now) from the queue and reserve resources
```

![The distribution of the next scrub time with the main defaults. Left: shallow with osd_scrub_min_interval=1 day and ratio=0.5, uniform between 24 and 36 hours after the previous scrub. Right: deep with osd_deep_scrub_interval=7 days and cv=0.2, normal with a mean of 7 days and a deviation of 1.4 days, truncated to \[4.2, 9.8\] days. The truncation creates two small peaks at the edges, each with a probability of about 2.3%. The dashed line is the PG_NOT_DEEP_SCRUBBED warning threshold](figures/ch32/f03_sched.png){#fig-32-f03_sched}

**Numerical example.** A PG's last deep scrub was on Monday at 10:00. sd = 7×0.2 = 1.4 days. With a probability of about 68% the next one is between 5.6 and 8.4 days later, that is from about 22:00 on Saturday to about 20:00 on the following Tuesday. It is never earlier than 4.2 days (about 15:00 on Friday) or later than 9.8 days, unless the OSD queue is behind. The mon raises the `PG_NOT_DEEP_SCRUBBED` warning when more than `I_d × (1 + mon_warn_pg_not_deep_scrubbed_ratio)` = 7 × 1.75 = 12.25 days have passed since the last deep scrub (`PGMap.cc`). So the gap from 9.8 to 12.25 days is the margin for a lagging queue. The similar warning for shallow is computed with `osd_scrub_max_interval × 1.5` = 10.5 days.

::: {.note}
**Version-dependent.** `osd_deep_scrub_interval_cv` exists in the squid, tentacle and main branches, and `osd_deep_scrub_randomize_ratio` is marked in its description as "deprecated, has no effect". In older versions, a deep scrub happened randomly with probability randomize_ratio during a shallow scrub. This behaviour has been removed.
:::

**The coin toss and load.** `OsdScrub::scrub_random_backoff` cancels the whole attempt of that tick with probability `osd_scrub_backoff_ratio=0.66`. If the tick is every second, the OSD tries on average once every 3 seconds (1/(1−0.66) ≈ 2.9). This reduces the cost of walking the queue and staggers the start of scrubs across OSDs. `osd_scrub_load_threshold=10.0` is compared with loadavg divided by the number of CPUs. On a machine with 32 cores, loadavg must exceed 320 for normal scrubs to stop. That is why this option rarely has an effect in practice.

## Reserving resources {#sec-32-2-2}

Before starting, `PgScrubber` reserves one slot of `osd_max_scrubs` (default 3) on its own OSD (`inc_scrubs_local`) and then on each replica (the ReservingReplicas state). If one replica refuses, the whole reservation is released and the PG is requeued with a delay of `osd_scrub_retry_delay` (30 seconds). Since Squid, replicas queue reservation requests instead of refusing them immediately. `osd_scrub_disable_reservation_queuing=true` restores the pre-Squid behaviour (an immediate grant or refusal). According to the option's description, it is only for mixed-version clusters and debugging and will be removed in the next release.

# The scrub state machine {#sec-32-3}

![The ScrubMachine state machine in scrub_machine.h. The primary side goes from NotActive to PrimaryActive, takes the replica reservations in Session and runs the chunk cycle in ActiveScrubbing: PendingTimer (sleep between chunks), NewChunk (choosing the range), WaitPushes and WaitLastUpdate (waiting for pushes and in-flight writes), BuildMap, WaitReplicas and the comparison. The PG finishes with WaitDigestUpdate. The replica side has the states ReplicaIdle, ReplicaWaitUpdates and ReplicaBuildingMap](figures/ch32/f01_scrubfsm.png){#fig-32-f01_scrubfsm}

**Why WaitPushes and WaitLastUpdate?** Before building its own map, the primary must be sure that in-flight recovery pushes have finished (WaitPushes) and that all writes accepted within the chunk's range have been applied to its own disk (WaitLastUpdate, until last_update_applied catches up). The replica likewise stays in ReplicaWaitUpdates before building its map, until its in-flight pushes drop to zero. The `scrub_to` field in `MOSDRepScrub` is, according to the code's own comment, no longer used. Because the range is locked before sending, no new write is accepted in it. Without these waits, the replica and the primary would compare different pictures of one moment, and false inconsistencies would be reported.

## Choosing the chunk and preemption {#sec-32-3-1}

![The sequence of one chunk. The primary gets the list of objects in the range from the PGBackend, adjusts the boundary so that a head and its clones stay in one chunk, locks the range and sends MOSDRepScrub to the replicas. Each side builds its own map (in deep, reading the data in 4 MiB steps). Then the primary compares the maps. A client write in the locked range preempts the chunk](figures/ch32/f02_chunkseq.png){#fig-32-f02_chunkseq}

::: {.algo #alg-32-2 title="Choosing the chunk range, shrinking after preemption" src="src/osd/scrubber/pg_scrubber.cc :: PgScrubber::select_range; preemption_data_t::adjust_left in pg_scrubber.h" complexity="O(chunk) for listing; the whole PG in O(N/chunk) rounds"}
:::

```text
pseudocode
min_sz = max(3, deep ? osd_scrub_chunk_min : osd_shallow_scrub_chunk_min)
max_sz = max(min_sz, (deep ? osd_scrub_chunk_max : osd_shallow_scrub_chunk_max) / divisor)
objects, end = objects_list_partial(start, min_sz, max_sz)
while end.is_head() and end == objects.back().get_head():   # do not separate a head and its clones
    end = objects.pop_back()
if end.is_head(): end = end.get_object_boundary()
if not range_available_for_scrub(start, end): return blocked   # RangeBlocked
on preemption (a client write in the range): if left > 0: left -= 1; divisor *= 2
```

**Numerical example.** A deep scrub with the defaults: min=max(3,5)=5 and max=15. After each preemption, the divisor doubles: the maximum chunk is 15, 7, 5, 5, ... in turn (because 15/4=3 is less than 5). After `osd_scrub_max_preemptions=5` times, no further preemption is allowed and client writes in that range **wait** until the end of the chunk. For shallow: min=50 and max=100, and after the first preemption all chunks are 50 objects. A PG with 3000 objects in a deep scrub without preemption has at least 3000/15 = 200 chunks. If `osd_scrub_sleep=0.1`, at least 20 seconds are just sleep between chunks.

::: {.warn}
**Why a head and its clones together?** A clone is always created "immediately to the left" of its head in hobject order. If the chunk boundary fell exactly on the head, a clone could be scrubbed in the previous chunk and then a new clone be created that no chunk ever sees. The comment above `select_range` says exactly this, and the while loop prevents it.
:::

## Comparing and choosing the authoritative copy {#sec-32-3-2}

When the maps have arrived, `ScrubBackend::scrub_compare_maps` calls `select_auth_object` for each object in the union of the maps and then compares each shard with the authoritative copy (`compare_obj_in_maps` and `compare_obj_details`): size, object_info, snapset, attrs, data_digest and omap_digest.

![The logic for choosing the authoritative copy in ScrubBackend::select_auth_object. The candidates start with the primary itself. Any shard with a read error, a stat error, an EC hash or size mismatch, or a damaged object_info or snapset is rejected. Among the usable shards, the larger object_info version wins. On a tie, the shard that recorded more digests wins, and on a complete tie, the first one (the primary)](figures/ch32/f04_auth.png){#fig-32-f04_auth}

::: {.algo #alg-32-3 title="Choosing the authoritative copy in scrub" src="src/osd/scrubber/scrub_backend.cc :: ScrubBackend::select_auth_object, possible_auth_shard" complexity="O(S) for S shards per object; the whole chunk O(S × objects)"}
:::

```text
pseudocode
shards = [primary] + others
for s in shards:
    r = possible_auth_shard(obj, s)          # read/stat/ec/oi/snapset errors
    if r.unusable: record error; continue
    if auth is none or r.oi.version > auth.version
       or (r.oi.version == auth.version and dcount(r.oi) > dcount(auth.oi)):
         auth = s
    if digests of s and auth differ: digest_match = false
dcount(oi) = [data_digest present] + [omap_digest present]
```

**Numerical example.** The object `rbd_data.abc.0000000000000012` on three shards. The primary (osd.4): oi.version = 812'5530 and both digests recorded. osd.9: the same version, only data_digest recorded. osd.11: a read error (EIO from BlueStore because of a checksum mismatch). The result: osd.11 is excluded and marked with `read_error` in `shard_info`. Between osd.4 and osd.9 the version is equal, but dcount(osd.4)=2 > dcount(osd.9)=1, so osd.4 is authoritative. If osd.9's data digest differs from osd.4's, a `data_digest_mismatch` inconsistency is also recorded for osd.9. The output of `rados list-inconsistent-obj` shows this same structure.

::: {.deep}
**Digests in deep scrub.** In a deep scrub, each object is read in steps of `osd_deep_scrub_stride` (4 MiB) and its crc32c is computed incrementally. The omap is walked in batches of `osd_deep_scrub_keys` (1024 keys) and its digest is built. If the object has a digest stored in its object_info, the computed value is also compared with it. Otherwise, if the object is older than `osd_deep_scrub_update_digest_min_age`, the digest is recorded in WaitDigestUpdate. In EC, each shard has its own hash, and the inconsistency check is done at the stripe level in `check_ec_stripe_digests` (for the mathematical details of EC see chapter 27).
:::

# recovery and backfill {#sec-32-4}

## From peering to reservation {#sec-32-4-1}

After peering (chapter 17), the primary knows which shards have missing objects (`peer_missing`) and which shards need the whole content (`backfill_targets`, because their log does not overlap the authoritative log). In Active, the PG enters the sub-machine shown in the figure below.

![The recovery and backfill states inside Active in PeeringState.h. Both paths first take a local reservation (on the primary) and then a remote reservation (on each target). If the reservation is refused or revoked, the PG goes to NotRecovering or NotBackfilling. If the target is full, it gets the toofull state and retries after osd_recovery_retry_interval or osd_backfill_retry_interval (both 30 seconds)](figures/ch32/f08_recstates.png){#fig-32-f08_recstates}

## Reservation priority {#sec-32-4-2}

![The priority ranges in osd_types.h. Each base has a ceiling (get_max_prio_for_base) so that a pool's priority cannot lift a PG into a higher class: normal backfill 100 to 139, backfill with missing replicas 140 to 179, recovery 180 to 219, and an inactive PG (below min_size) 220 to 253. The values 254 and 255 are for force-backfill and force-recovery. The PG-deletion priorities (179, 219, 255) also compete in this same queue](figures/ch32/f05_prio.png){#fig-32-f05_prio}

::: {.algo #alg-32-4 title="Computing the recovery and backfill priority" src="src/osd/PeeringState.cc :: get_recovery_priority, get_backfill_priority, clamp_recovery_priority" complexity="O(n) for counting acting against min_size"}
:::

```text
pseudocode
backfill:
  if FORCED_BACKFILL: return 254
  below = num_acting_below_min_size(pool, acting)
  if below:            base = 220; p = 220 + below
  elif undersized:     base = 140; p = 140 + (size − |actingset|)
  elif degraded:       base = p = 140
  else:                base = p = 100
recovery:
  if FORCED_RECOVERY: return 255
  base = p = 180;  if degraded and below(avail_no_missing): base = 220; p = 220 + below
clamp(p, pool_prio, max_for_base):
  pool_prio = clamp(pool_prio, −10, +10) + 10      # shifted to 0..20
  return clamp(p + pool_prio, 0, max_for_base)
```

**Numerical example.** Consider a replicated pool with size=3, min_size=2 and the default `recovery_priority` of zero:

| PG state | Base | Calculation | Final priority |
|---|---|---|---|
| normal backfill (movement after adding an OSD) | 100 | 100 + (0+10) | 110 |
| backfill while undersized: 2 of 3 in acting | 140 | 140 + 1 + 10 | 151 |
| ordinary recovery | 180 | 180 + 10 | 190 |
| recovery with only 1 healthy shard (below min_size) | 220 | 220 + 1 + 10 | 231 |
| the same with recovery_priority=10 for the pool | 220 | 220 + 1 + 20 | 241 |
| normal backfill with recovery_priority=10 but the base ceiling | 100 | 100 + 20 = 120 ≤ 139 | 120 |

The subtle point is that even with `recovery_priority=0`, the +10 shift is always applied, because the range −10 to +10 is moved to 0 to 20. The ceilings of each base guarantee that even the highest pool priority cannot push a normal backfill (at most 139) ahead of a backfill with missing replicas (at least 140).

::: {.note}
**Version-dependent.** The base `OSD_POOL_MIGRATION_PRIORITY_BASE=60` and the MigratingSource and MigratingTarget states exist in main for the pool-migration feature, but they do not appear in the squid and tentacle branches.
:::

## AsyncReserver: reservation with preemption {#sec-32-4-3}

Each OSD has two reservers: `local_reserver` (for PGs whose primary is this OSD) and `remote_reserver` (for PGs for which this OSD is a target). The limit of both is `osd_max_backfills` (default 1). With the mClock scheduler, changing this option only has an effect when `osd_mclock_override_recovery_settings=true` (`OSD::maybe_override_options_for_qos`). Otherwise the change is removed from the configuration database.

::: {.algo #alg-32-5 title="Priority-based reservation grants with preemption" src="src/common/AsyncReserver.h :: AsyncReserver::do_queues, preempt_one" complexity="O(log P) for P priority levels per grant"}
:::

```text
pseudocode
queues: map<prio, list<Reservation>>; in_progress; preempt_by_prio: set<(prio, item)>
do_queues():
  while preempt_by_prio not empty and (|in_progress| > max_allowed or min(preempt_by_prio).prio < min_priority):
      preempt_one()                                   # the lowest-priority preemptible one
  while queues not empty:
      (prio, list) = highest
      if prio < min_priority: break
      if |in_progress| ≥ max_allowed and preempt_by_prio not empty and prio > min(preempt_by_prio).prio:
          preempt_one()
      if |in_progress| ≥ max_allowed: break
      grant(list.pop_front()); if preemptible: preempt_by_prio.insert(prio, item)
```

![The backfill reservation sequence. The primary first takes a slot of its own local_reserver and then, with MBackfillReserve REQUEST, a slot of the target's remote_reserver. Both are limited to osd_max_backfills. A higher-priority request on the target takes back a lower-priority preemptible reservation, and the primary receives a REVOKE message](figures/ch32/f06_reserve.png){#fig-32-f06_reserve}

**Numerical example.** osd.7 is the backfill target for a PG with priority 151 and has taken the only slot of `remote_reserver` (max=1). Another PG that has only one healthy shard (priority 231) asks osd.7 for a reservation. In `do_queues`, the highest queue is 231, in_progress is full and 231 > 151, so `preempt_one` takes back the 151 reservation. The primary of that PG receives a REVOKE message and goes back to WaitLocalBackfillReserved. The 231 reservation is granted immediately. This is the mechanism that lets inactive PGs recover without waiting for long backfills.

## Log-based recovery and async recovery {#sec-32-4-4}

In recovery, the primary has each shard's `missing` list and recovers the objects in version order: first it pulls its own missing objects (`recover_primary`), then it pushes to the replicas (`recover_replicas`). The number of concurrent operations is limited by `osd_recovery_max_active_hdd=3` and `osd_recovery_max_active_ssd=10`. Each push carries at most `osd_recovery_max_chunk=8M` of data. In **async recovery**, a shard that is far behind is left out of acting so that writes do not wait for it, and it is recovered in the background.

::: {.algo #alg-32-6 title="Choosing async recovery targets by cost" src="src/osd/PeeringState.cc :: PeeringState::choose_async_recovery_replicated" complexity="O(n log n) for n members of want"}
:::

```text
pseudocode
for osd in want (up and not stray):
    cost = |auth.last_update.version − osd.last_update.version| + osd.stats.num_objects_missing
    if cost > osd_async_recovery_min_cost (100): candidates.add(cost, osd)
for (cost, osd) in candidates from the highest cost:
    w = want − {osd}
    if acting_set_writeable(pool, w): want = w; async_recovery.add(osd)
```

**Numerical example.** want=[1, 2, 3], size=3, min_size=2. The authoritative last_update.version is 5000. osd.2 is at version 4990 and has no missing objects, so its cost is 10 and it is not a candidate. osd.3 is at version 4800 with 30 historically missing objects, so its cost is 230 > 100. [1, 2] is still writeable, so osd.3 becomes an async recovery target and acting is [1, 2]. Client writes are acknowledged with two copies, and after recovery finishes osd.3 returns to acting. If osd.2 also had a cost above 100, removing the second one would give [1], which is below min_size, so it would not be done.

## backfill: merging two sorted lists {#sec-32-4-5}

![The merge logic in recover_backfill. The primary keeps one interval of its own objects (backfill_info) and one interval from each target (peer_backfill_info), scanned 64 to 512 objects at a time (osd_backfill_scan_min/max). Both are sorted in hobject order. An object that is only on the target is deleted. An object whose version differs is pushed. An object whose version is equal is kept. Objects after the target's last_backfill are pushed as missing](figures/ch32/f07_backfill.png){#fig-32-f07_backfill}

::: {.algo #alg-32-7 title="backfill as a merge-join over sorted hobjects" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::recover_backfill, scan_range, prep_backfill_object_push" complexity="O(N + M) comparisons for N primary objects and M target objects; O(scan_max) memory"}
:::

```text
pseudocode
while ops < max:
    refill backfill_info / peer intervals if exhausted (MOSDPGScan for replicas)   # one op
    check = min(backfill_info.begin, min over targets of pbi.begin)
    if check < backfill_info.begin:                 # only on the target(s)
        for t with pbi.begin == check: to_remove.add(check, t); pbi.pop_front()
    else:                                           # a primary object
        for t in targets:
            if pbi.begin == check: (version differs ? need_ver : keep_ver).add(t)
            elif check > peer_info[t].last_backfill: missing.add(t)
        if need_ver or missing: prep_backfill_object_push(check, need_ver ∪ missing); ops++
        pop check from backfill_info and matching pbi
    last_backfill_started = check
send MOSDPGBackfill(progress, last_backfill) periodically
```

**Time estimate.** Consider a PG with 50 GiB of data in 4 MiB objects (12800 objects) on an HDD target that writes each object push at about 100 MB/s. Each object takes about 42 milliseconds. With one concurrent PG (`osd_max_backfills=1`), the whole backfill takes about 12800 × 0.042 ≈ 537 seconds, that is about 9 minutes. If `osd_recovery_sleep_hdd=0.1` is applied between ops (with the wpq scheduler; with mClock, the scheduler controls the cost), another 12800 × 0.1 = 1280 seconds are added. The total is about 30 minutes. This shows why, with HDDs, backfilling a full OSD with hundreds of PGs takes hours.

# repair {#sec-32-5}

![The flow of ceph pg repair. The scrub target's urgency goes to must_repair and a full deep scrub runs. For each inconsistent object, ScrubBackend::repair_object uses force_object_missing to add the damaged shards to the missing list and makes only the healthy shards the source in missing_loc. Then the normal recovery mechanism pushes the authoritative copy](figures/ch32/f09_repair.png){#fig-32-f09_repair}

The key point is that repair **has no separate mechanism for copying data**. It is the same recovery, fed with an artificial missing list. So all the limits of recovery (reservation, max_active and priority) also apply to repair. If there is no usable shard (for example all have read errors), repair can do nothing and the object stays "unfound". You have to decide with `ceph pg PGID mark_unfound_lost revert|delete`.

| Option | Default (main) | Effect |
|---|---|---|
| osd_scrub_auto_repair | false | if true, periodic scrub repairs errors automatically |
| osd_scrub_auto_repair_num_errors | 5 | if there are more errors, auto repair is not done |
| osd_max_scrubs | 3 | concurrent scrubs on one OSD |
| osd_scrub_during_recovery | false | allow scrub while the OSD's PGs are in recovery |
| osd_scrub_retry_delay | 30 | delay before retrying after a failure |
| osd_recovery_max_active_hdd / _ssd | 3 / 10 | concurrent recovery operations per OSD |
| osd_backfill_scan_min / max | 64 / 512 | backfill scan size |
| osd_async_recovery_min_cost | 100 | cost threshold for async recovery |

::: {.warn}
**A common mistake.** Do not run `ceph pg repair` without first examining `rados list-inconsistent-obj PGID --format=json-pretty`. If the inconsistency is an `omap_digest_mismatch` on the primary and the primary is wrongly chosen as authoritative, repair spreads the damaged copy to the replicas. The authoritative-copy selection logic favours the primary on equal versions. In doubtful cases, first take the damaged OSD out, or examine the copy by hand with `ceph-objectstore-tool`.
:::

# Commands and debugging {#sec-32-6}

```bash {since=squid}
ceph pg deep-scrub 2.1f                    # an operator request (urgency operator_requested)
ceph tell osd.4 dump_scrubs                # this OSD's scrub queue: targets, not_before and urgency
ceph tell osd.4 dump_scrub_reservations    # local and remote reservations
rados list-inconsistent-obj 2.1f --format=json-pretty
ceph pg 2.1f query | jq '.recovery_state'  # the current state of the peering/recovery machine
ceph tell osd.4 dump_recovery_reservations # local_reserver and remote_reserver
ceph config set osd debug_osd 20/20        # temporary; select_range and do_queues messages
```

::: {.debug}
If a PG has been in `backfill_wait` for a long time: (1) look at `dump_recovery_reservations` on the primary and the target. Usually another PG has taken the single slot of `osd_max_backfills`. (2) Check the priority with `ceph pg PGID query`. (3) For urgency, `ceph pg force-backfill PGID` raises the priority to 254. But if you do this for many PGs, prioritization becomes meaningless.
:::

# Supplementary and up to date {#sec-32-7}

- In Squid the scrub code was reworked: a replica reservation queue, two separate targets for shallow and deep in ScrubJob, and the cv option for deep. The `dump_scrubs` commands had a different output structure in older versions.
- In main, `ScrubBackend` has extended the EC stripe check with `ec_stripe_mismatches` and `find_corrupt_zone_copies`, which relates to FastEC (chapter 27). Check your own version before relying on the details of the EC inconsistency output.
- Crimson (chapter 30) implements backfill with a separate state machine (`BackfillState` in `src/crimson/osd/backfill_state.cc`). The merge logic is the same.

# Hands-on exercise {#sec-32-8}

1. With vstart, create a pool with size=3, write an object and damage it on one replica with `ceph-objectstore-tool`. Look at the deep scrub and the `list-inconsistent-obj` output and explain why that shard was not chosen.
2. Set `osd_scrub_sleep=0.5` and predict and then measure the deep-scrub time of a PG with a thousand objects.
3. With `ceph osd out` on one OSD, read the backfill priority of the undersized PGs from `pg query` and compare it with this chapter's table.
4. With `debug_osd=20`, find the `do_queues` and `preempt_one` messages while an inactive PG and a normal backfill run at the same time.

# Review questions {#sec-32-9}

1. In what range is the next shallow and deep scrub time with the defaults, and why does the deep distribution have peaks at the edges?
2. After exactly how long is the PG_NOT_DEEP_SCRUBBED warning raised?
3. Why must a scrub chunk not separate a head from its clones?
4. After three preemptions in a deep scrub, what is the maximum chunk size?
5. In select_auth_object, if the versions are equal, what criterion decides the winner?
6. What is the backfill priority of an undersized PG with size=3 and two acting members?
7. Why does the priority rise by 10 units even with recovery_priority=0?
8. Under what condition does AsyncReserver take back an in-progress reservation?
9. Which target does async recovery leave out of acting, and what condition limits it?
10. Why does repair have the same limits as recovery?

# Sources for this chapter {#sec-32-10}

- scrub in the Ceph documentation: https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/#scrubbing
- scrub developer documentation: https://docs.ceph.com/en/latest/dev/osd_internals/scrub/
- backfill reservation and priority: https://docs.ceph.com/en/latest/dev/osd_internals/backfill_reservation/
- recovery in the developer documentation: https://docs.ceph.com/en/latest/dev/osd_internals/recovery_reservation/
- scrubber code: https://github.com/ceph/ceph/tree/main/src/osd/scrubber
- PeeringState: https://github.com/ceph/ceph/blob/main/src/osd/PeeringState.cc
- AsyncReserver: https://github.com/ceph/ceph/blob/main/src/common/AsyncReserver.h
- PrimaryLogPG: https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- OSD options: https://github.com/ceph/ceph/blob/main/src/common/options/osd.yaml.in
- Troubleshooting PGs and repairing inconsistencies: https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/
