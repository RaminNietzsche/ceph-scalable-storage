---
chapter: 35
id: ch35
title: 'Specialist Part (2): RADOS — The PG Log, Intervals, Missing Sets, and How Recovery and Backfill Work'
part: specialist
lang: en
---

# Before we begin {#sec-35-1}

Chapter 17 showed the peering state machine and how the authoritative info is chosen, and chapter 32 showed recovery reservation and scheduling. This chapter opens the middle layer: how a PG works out which OSDs it must ask (past intervals and the prior set), how the logs of two OSDs are merged, what it does with **divergent** entries, how the missing set is built, when and by how much the log is trimmed, and what recovery and backfill actually do object by object. Function names and defaults have been checked against the main branch of the ceph/ceph repository (November 2026).

## What questions does this chapter answer? {#sec-35-1-1}

- What change in the OSDMap creates a new interval, and how is `maybe_went_rw` determined?
- Why does a PG sometimes become `down`, and what does `blocked_by` in `ceph pg query` (the `peering_blocked_by` field) say?
- What does `merge_log` do with a peer's log that is ahead or behind?
- What is a divergent entry, and what are the five ways of handling it?
- How is the length of the pg log determined, and what prevents trimming?
- When is log-based recovery enough, and when is backfill needed?
- How does backfill compare and transfer objects?

## Prerequisites {#sec-35-1-2}

Chapter 17 (peering), chapter 32 (scrub and recovery) and chapter 34 (the pg log on disk and versions).

# The info and history of a PG {#sec-35-2}

Each member of a PG has a `pg_info_t`. The key fields:

| Field | Meaning |
|---|---|
| `last_update` | the last version present in this member's log |
| `last_complete` | up to this version all objects are complete on this member (there is no older missing object) |
| `log_tail` | the oldest log entry |
| `last_backfill` | objects greater than this (in hobject_t order) may not be on this member; `MAX` means no backfill is needed |
| `last_epoch_started` | the last epoch in which the PG became active on this member |
| `purged_snaps` | snaps whose purge has finished (chapter 36) |
| `history` | a `pg_history_t` shared among the members |

`pg_history_t` keeps the PG's history at the epoch level: `epoch_created`, `same_interval_since` (since when up and acting have not changed), `same_up_since`, `same_primary_since`, `last_epoch_started` and `last_interval_started` (the last time the PG became active anywhere), `last_epoch_clean` and `last_interval_clean`, and the scrub times.

::: {.note}
`last_update` and `last_complete` are two separate concepts. A replica may have the log up to `1462'93` (last_update) while object A, written at `1462'80`, is not yet on its disk. In that case `last_complete` is `1462'79` and A is in that member's missing set.
:::

# Past intervals and the prior set {#sec-35-3}

## When does a new interval start? {#sec-35-3-1}

An **interval** is a range of epochs during which the PG's mapping stayed constant. On every new map, `PastIntervals::is_new_interval` checks whether any of the following has changed: the primary or the acting set, the up primary or the up set, the pool's `size` or `min_size`, a split or merge (and their pending states), `sort_bitwise`, `recovery_deletes`, the CRUSH stretch parameters (`crush_count`, `crush_target`, `crush_barrier`, `crush_member`), EC optimizations being turned on, and in the main branch the PG entering or leaving a pool migration. So changing `min_size` alone also triggers peering.

::: {.algo #alg-35-1 title="Recording a past interval and determining maybe_went_rw" src="src/osd/osd_types.cc :: PastIntervals::is_new_interval, PastIntervals::check_new_interval" complexity="O(n) for n acting members on each new map"}
:::

```text
pseudocode
check_new_interval(old, new, same_interval_since, last_epoch_clean):
    if not is_new_interval(old, new): return false
    i = interval(first = same_interval_since, last = new_epoch - 1,
                 acting = old_acting, up = old_up, primary = old_primary)
    if acting non-empty and primary != -1 and acting_set_writeable(old pool, old acting)
       and could_have_gone_active(acting shards):
        if up_thru[primary] >= i.first and up_from[primary] <= i.first:
            i.maybe_went_rw = true                    # the primary had reported up_thru to the mon
        elif i.first <= last_epoch_clean <= i.last:
            i.maybe_went_rw = true                    # the PG went clean in this range, so it had writes
        else: i.maybe_went_rw = false
    else: i.maybe_went_rw = false                     # acting smaller than min_size
    past_intervals.add_interval(i)
```

The role of `up_thru` is vital. Before going active, the primary asks the mon with `MOSDAlive` to raise its `up_thru` to at least the current epoch. If an interval did not last even long enough for up_thru to be recorded, the primary could not have gone active and no write happened in it. So the next peering does not need to wait for the members of that interval.

## The prior set and the down state {#sec-35-3-2}

`PastIntervals::PriorSet` is the list of OSDs from which the primary must get info and logs. All current up and acting members, and all members of past intervals that are up now, go into `probe`. Then, for each interval with `maybe_went_rw` from `last_epoch_started` onward:

::: {.algo #alg-35-2 title="Building the prior set and detecting a down PG" src="src/osd/osd_types.h :: PastIntervals::PriorSet::PriorSet; src/osd/osd_types.cc :: PastIntervals::iterate_mayberw_back_to" complexity="O(I × n) for I intervals and n members"}
:::

```text
pseudocode
for interval in past_intervals where maybe_went_rw, newest → last_epoch_started:
    up_now = {osd in interval.acting | osd is UP now or marked LOST}
    candidate_blocked_by = {osd in interval.acting | osd is DOWN now}
    if not recoverable(up_now) and candidate_blocked_by not empty:
        pg_down = true                               # some data may exist only on them
        blocked_by += candidate_blocked_by
# recoverable: replicated → at least one member ; EC → at least k distinct shards
```

**Numerical example.** PG 3.1f with size=3 and min_size=2 was on [12,4,27] in the interval [1400, 1449]. At epoch 1450 both OSD 4 and OSD 27 failed and acting dropped to [12]. Since one member is less than min_size, the interval [1450, 1460] had no writes (`maybe_went_rw=false`). Now at epoch 1461 osd.12 itself went down and 4 and 27 came back. The interval [1400, 1449] had writes and its up members are 4 and 27; for replicated, one member is enough, so the PG does not go down. But if only osd.12 had survived from that interval and it were now down, we would get `pg_down=true` and `blocked_by: [12]`. The way out is either to bring osd.12 back or to declare `ceph osd lost 12`, which means accepting the possible loss of data.

```text
example (part of ceph pg 3.1f query):
"recovery_state": [ { "name": "Started/Primary/Peering/Down",
    "comment": "not enough up instances of this PG to go active" },
  { "name": "Started/Primary/Peering",
    "probing_osds": [ "4", "27" ],
    "blocked": "peering is blocked due to down osds",
    "down_osds_we_would_probe": [ 12 ],
    "peering_blocked_by": [ { "osd": 12, "current_lost_at": 0,
        "comment": "starting or marking this osd lost may let us proceed" } ] } ]
```

![The timeline of a PG's intervals. Every change in up, acting or min_size creates a new interval. Only intervals in which the primary obtained up_thru or the PG went clean are maybe_went_rw and count in the prior set. An interval whose acting set was smaller than min_size is ignored](figures/ch35/f01_intervals.png){#fig-35-f01_intervals}

# Merging logs {#sec-35-4}

After the primary has chosen, with `find_best_info` (chapter 17), the member with the most authoritative log, it gets that log and merges it into its own with `PGLog::merge_log`. For the replicas, `proc_replica_log` runs the same logic on a copy of their logs to compute each replica's missing set.

::: {.algo #alg-35-3 title="merge_log: merging the authoritative log into the local log" src="src/osd/PGLog.cc :: PGLog::merge_log, PGLog::rewind_divergent_log" complexity="O(E) for E new or divergent entries; a missing-set update per object"}
:::

```text
pseudocode
merge_log(olog from authoritative peer):
    assert overlap: log.head >= olog.tail and olog.head >= log.tail
    if olog.tail < log.tail:                      # extend the tail
        splice older entries of olog before log; log.tail = olog.tail
    if olog.head < log.head:                      # we were ahead: the extra entries are divergent
        rewind_divergent_log(olog.head)
    if olog.head > log.head:                      # extend the head
        lower_bound = newest olog entry <= log.head
        divergent = log.rewind_from_head(lower_bound)   # entries that olog does not have
        append olog entries after lower_bound; for each: missing.add_next_event(entry)
        _merge_divergent_entries(divergent)
        info.last_update = log.head = olog.head
        info.last_user_version = oinfo.last_user_version ; info.purged_snaps = oinfo.purged_snaps
```

Adding each new entry to the missing set is simple: if the object was not missing before, `have` becomes the entry's `prior_version` and `need` the entry's version. If it was, only `need` moves forward. For a `DELETE` entry, the `FLAG_DELETE` flag is set so that recovery deletes instead of copying.

## Divergent entries {#sec-35-4-1}

A **divergent** entry is one that is in a member's log but not in the authoritative log; for example, the previous primary recorded a write locally and failed before it reached the others. Since the client never received a reply for that write (the reply is sent only after all of acting has committed), it must be **rolled back**. `_merge_object_divergent_entries` groups the entries by object and applies one of five cases to each object:

::: {.algo #alg-35-4 title="The five cases for handling an object's divergent entries" src="src/osd/PGLog.h :: PGLog::_merge_object_divergent_entries" complexity="O(e) for e divergent entries of that object"}
:::

```text
pseudocode
for each object hoid with divergent entries (sorted by version):
    if hoid > info.last_backfill: ignore                 # not backfilled yet
    prior = prior_version of first divergent entry
    1) if log (authoritative) has a newer entry for hoid:
           nothing to do — merge_log already set missing to that newer version
    2) elif prior == eversion_t() or first entry is a clone:
           object should not exist: remove it from store, drop from missing
    3) elif hoid is already missing:
           if missing.have == prior: drop from missing ; else missing.need = prior
    4) elif every entry can_rollback() and version > olog.can_rollback_to:
           rollback each entry (EC: from the rollback stashes)   # the object does not become missing
    5) else:
           remove object from store ; missing.add(hoid, need=prior, have=none)
```

Case 4 happens mostly in EC, because the EC backend keeps rollback information for each write (for example the previous version of the xattrs or the previous length of the object). In replicated pools most writes have no rollback and case 5 applies: the object is removed and recovered from another member at version `prior`.

![Merging logs with a divergent entry. Member A wrote up to 1462'95, but the authoritative log of member B goes up to 1462'93 and then has 1470'94 and 1470'95 in the new epoch. The entries 1462'94 and 1462'95 on A are divergent; they are rolled back or removed, and the corresponding object goes into the missing set at the prior version](figures/ch35/f02_divergent.png){#fig-35-f02_divergent}

# Log length and trimming {#sec-35-5}

The longer the log, the longer an OSD can be down and still come back with the log (without backfill), but more memory and omap space are used.

::: {.algo #alg-35-5 title="The target log length and computing trim_to" src="src/osd/OSD.cc :: OSDService::get_target_pg_log_entries; src/osd/PeeringState.cc :: PeeringState::calc_trim_to" complexity="O(t) for t entries being trimmed"}
:::

```text
pseudocode
target = clamp(osd_target_pg_log_entries_per_osd / num_pgs_on_osd,
               min = osd_min_pg_log_entries, max = osd_max_pg_log_entries)
limit = min(min_last_complete_ondisk, can_rollback_to)
if log.size > target:
    n = min(log.size - target, osd_pg_log_trim_max)
    if n < osd_pg_log_trim_min: return                 # trim in larger batches
    trim_to = version of the n-th oldest entry, but never beyond limit
```

| Option | Default in main |
|---|---|
| `osd_target_pg_log_entries_per_osd` | 300000 |
| `osd_min_pg_log_entries` | 250 |
| `osd_max_pg_log_entries` | 10000 |
| `osd_pg_log_trim_min` | 100 |
| `osd_pg_log_trim_max` | 10000 |
| `osd_pg_log_dups_tracked` | 3000 |

**Numerical example.** An OSD with 200 PGs: 300000/200 = 1500, which lies between 250 and 10000; so the target is 1500 entries per PG. With 1500 PGs on the same OSD (assumption: a large pool with a high pg_num) the target drops to 200 and is rounded up to the minimum of 250. The practical consequence: the more PGs an OSD has, the shorter each PG's log, and an OSD that was down for a few minutes falls back to backfill sooner.

**What prevents trimming?** `min_last_complete_ondisk`, that is, the lowest `last_complete` among all acting members. If a replica has an object missing, the log is not trimmed past that point, because that member's missing set depends on those entries. A PG that stays degraded for a long time has a longer log, and this shows up in the `osd_pglog` mempool.

# Recovery and backfill in practice {#sec-35-6}

## Is the log enough, or backfill? {#sec-35-6-1}

In `PeeringState::activate` a decision is made for each acting or backfill member. If `pg_log.get_tail() > peer.last_update`, meaning our log no longer has the entries after the peer's last version, or if `peer.last_backfill` is empty (a new member), that member is **backfilled**: its `last_backfill` is reset to the beginning (`hobject_t()`) and it is filled object by object from the start. Otherwise the entries after `peer.last_update` are sent to it and its missing set is built from those entries.

::: {.sim name="peering"}
:::

## The order of work in start_recovery_ops {#sec-35-6-2}

::: {.algo #alg-35-6 title="The recovery order in one round of start_recovery_ops" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::start_recovery_ops, recover_primary, recover_replicas, recover_backfill" complexity="at most max operations per round (based on osd_recovery_max_active and mClock)"}
:::

```text
pseudocode
start_recovery_ops(max):
    if primary has no missing or all its missing are unfound:
        started = recover_replicas(max)                  # push to the replicas that have missing objects
    if started == 0:
        started += recover_primary(max)                  # pull for the primary's own missing objects
    if started == 0 and new unfound objects appeared:
        started = recover_replicas(max)
    if backfill targets exist and started < max and primary missing is empty
       and backfill reservation granted:
        started += recover_backfill(max - started)
    # main: then recover_pool_migration for pool migration
```

recover_primary picks, for each missing object, a source from `missing_loc` (a member that has that version) and **pulls** it. recover_replicas **pushes** the object from the primary to the replica. Each push carries at most `osd_recovery_max_chunk` (default 8 MiB) of data, and larger objects are transferred over several rounds. If no up member has the needed version, the object is **unfound** (chapter 17 and `ceph pg <pgid> list_unfound`).

## Backfill: comparing two ordered scans {#sec-35-6-3}

Backfill does not use the log. The primary and each backfill target scan the PG's contents in hobject_t order (chapter 34) in small **intervals** (`BackfillInterval`, with a minimum of `osd_backfill_scan_min` = 64 and a maximum of `osd_backfill_scan_max` = 512 objects per scan) and compare them like merging two sorted lists.

::: {.algo #alg-35-7 title="Comparing backfill intervals" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::recover_backfill, scan_range_primary, scan_range_replica" complexity="O(N) for N objects in the PG; each scan at most osd_backfill_scan_max objects"}
:::

```text
pseudocode
loop while ops < max:
    refill backfill_info (primary) and peer_backfill_info[t] when exhausted (MOSDPGScan)
    check = min(begin of all intervals)
    for each target t:
        if t's next object < check: t has extra object → send remove to t
    if primary has check:
        for targets whose version != primary version (and t.last_backfill < check):
            push check to them
    advance all intervals past check
    new_last_backfill = largest object fully handled on all targets
send MOSDPGBackfill PROGRESS(last_backfill) ; at end FINISH (last_backfill = MAX)
```

Client writes continue during backfill. If the object being written is **before** the target's `last_backfill`, it is replicated to that target as usual. If it is after it, it is only recorded in the log, and backfill itself later transfers the new version. An object that is being backfilled at that very moment is locked for writes, and the op waits in `waiting_for_degraded_object` (chapter 34).

![Backfill as the merge of two ordered scans. The primary's interval and the target's interval advance together. An object present only on the target is removed, an object present only on the primary or with a different version is pushed, and last_backfill advances after each round](figures/ch35/f03_backfill.png){#fig-35-f03_backfill}

# Commands and troubleshooting {#sec-35-7}

| Command | Use |
|---|---|
| `ceph pg <pgid> query` | the info of all members, past_intervals, probing_osds, peering_blocked_by and recovery_progress |
| `ceph pg ls recovering` / `backfilling` / `down` / `incomplete` | listing PGs by state |
| `ceph pg <pgid> list_unfound` | unfound objects and the OSDs that have been checked |
| `ceph pg <pgid> mark_unfound_lost revert` or `delete` | the last resort for unfound objects; data is lost |
| `ceph osd lost <id> --yes-i-really-mean-it` | declaring an OSD lost so peering does not wait for it |
| `ceph-objectstore-tool --op log --pgid <pgid>` | a PG's log, dups and missing set on a stopped OSD |
| `ceph-objectstore-tool --op export` / `import` | rescuing a PG from a faulty OSD |
| `ceph daemon osd.N dump_recovery_reservations` | reservations (chapter 32) |

```text
example (part of ceph pg 3.1f query during backfill):
"info": { "last_update": "1470'2210", "last_complete": "1470'2210",
          "log_tail": "1468'710", "last_backfill": "MAX" },
"peer_info": [ { "peer": "31", "last_update": "1470'2210",
                 "last_backfill": "3:fa21c9e8:::rbd_data.5f3a2b8c1d4e.0000000000000c1a:head" } ],
"recovery_state": [ { "name": "Started/Primary/Active",
    "recovery_progress": { "backfill_targets": [ "31" ],
        "waiting_on_backfill": [], "last_backfill_started": "3:fa21c9e8:::rbd_data...0c1a:head",
        "backfill_info": { "begin": "3:fa21c9e8:::rbd_data...0c1a:head", "end": "3:fa2a...", "objects": [ "..." ] } } } ]
```

The `last_backfill` of target 31 is an hobject_t with the bitwise key `fa21c9e8`. Since this PG's range at pg_num=32 runs from `f8000000` to `ffffffff`, a simple division gives the approximate progress: (0xfa21c9e8 − 0xf8000000) / 0x08000000 ≈ 27%.

## Symptoms and remedies {#sec-35-7-1}

- **The PG stays in `peering` and has `peering_blocked_by`:** an OSD that was a member in an interval with writes is down. Bring it back first; `ceph osd lost` is the last option.
- **The PG is `incomplete`:** no live member has a complete log up to `last_epoch_started`. Before using `osd_find_best_info_ignore_history_les` or `export` and `import` with ceph-objectstore-tool, back up the OSDs.
- **An OSD fell back to backfill after a few minutes of downtime:** the log was short. Check the number of PGs per OSD, or keep the downtime shorter during planned maintenance.
- **A long log and high memory use:** long-degraded PGs are preventing trimming. Finish the recovery.

# Supplementary and up to date {#sec-35-8}

- In the main branch, support for EC partial writes (`written_shards` in pg_log_entry_t and `partial_writes_last_complete`) has made the divergent and backfill logic more complex for EC; some entries were never applied on some shards and must not be considered missing.
- `recover_pool_migration` and `migrating_pgs` have been added in the main branch for migrating data between pools. Before using them, check whether they exist in your version.
- Crimson shares the PeeringState logic directly, but implements backfill with a separate state machine (`crimson/osd/backfill_state.cc`).

# Hands-on exercise {#sec-35-9}

1. On a test pool, change `min_size` and watch `same_interval_since` change in `ceph pg <pgid> query`.
2. Set `noout` and stop one OSD, perform a few thousand writes and, with a small `osd_max_pg_log_entries`, test whether the OSD comes back with the log or is backfilled after it returns.
3. With `ceph-objectstore-tool --op log` on a stopped OSD, find the `pg_missing` fields and match `need` and `have` against the log entries.
4. During backfill, read the target's `last_backfill` a few times and estimate the percentage of progress with the bitwise-key method.

# Review questions {#sec-35-10}

1. What changes in the OSDMap create a new interval? Name three other than up and acting.
2. Under what conditions is `maybe_went_rw` true?
3. Why is up_thru necessary for the safety of peering?
4. When does a PG go down, and whom does `blocked_by` point to?
5. What does merge_log do when the authoritative log is ahead?
6. What is a divergent entry, and why is rolling it back safe?
7. How do cases 4 and 5 of divergent handling differ?
8. What is the target log length for an OSD with 600 PGs under the defaults?
9. What condition determines that a member is backfilled?
10. How does backfill determine that an object must be removed from the target?

# Sources for this chapter {#sec-35-11}

- osd_types.cc and osd_types.h (PastIntervals, PriorSet, pg_info_t, pg_missing_item): https://github.com/ceph/ceph/blob/main/src/osd/osd_types.cc
- PGLog.cc and PGLog.h (merge_log, divergent): https://github.com/ceph/ceph/blob/main/src/osd/PGLog.h
- PeeringState.cc (activate, calc_trim_to): https://github.com/ceph/ceph/blob/main/src/osd/PeeringState.cc
- PrimaryLogPG.cc (start_recovery_ops, recover_backfill): https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- Developer documentation on peering: https://docs.ceph.com/en/latest/dev/peering/
- Developer documentation on the log-based PG: https://docs.ceph.com/en/latest/dev/osd_internals/log_based_pg/
- PG troubleshooting: https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/
