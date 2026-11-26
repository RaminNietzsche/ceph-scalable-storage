---
chapter: 42
id: ch42
title: 'Specialist Part (9): RGW — Inside Multisite: Periods, Log Formats, Bucket Generations and the Sync Engine'
part: specialist
lang: en
---

::: {.tldr}

- A period records the multisite configuration; changes are staged and committed, which raises the epoch.
- Metadata logs, data logs and bucket index logs record changes; zones_trace prevents changes being sent back.
- Sync status objects live in the destination zone's log pool, named after the source zone.
- Data sync advances shard markers despite failures and retries them from an error repo; metadata writes need the master zone.

```bash
radosgw-admin bucket sync status --bucket logs --source-zone zone-a
```

[![The chain of three logs for a PUT in the source zone: bilog, datalog and destination fetch_remote_obj](figures/ch42/f01_logs.png)](#fig-42-f01_logs)

:::

# Before we begin {#sec-42-1}

Chapter 5 covered multisite from the point of view of setup and operation: the realm, zonegroup and zone hierarchy, the three logs, the data sync state machine, choosing the datalog and mdlog shard, the coalescing window and trim. This last chapter of the specialist part opens up the inside of that same engine: exactly what checks committing a period involves and when it creates a new period, what fields the bilog, datalog and mdlog records have, which RADOS objects hold the sync status, how reshard copes with sync through log "generations", where errors are queued, and how a conflict from concurrent writes in two zones is resolved. Names have been matched against the main branch (November 2026).

## What questions does this chapter answer? {#sec-42-1-1}

- Why does `period update --commit` sometimes raise the epoch and sometimes change the period id?
- What information do a bilog entry and a datalog entry carry?
- In which object, and under what name, is the sync status of a bucket shard stored?
- After a reshard in the source zone, how does the destination zone continue without losing changes?
- If syncing a bucket fails, where is it recorded and when is it retried?
- If an object is written in two zones at the same time, which version stays?

## Prerequisites {#sec-42-1-2}

Chapter 5 (multisite), chapter 40 (the bucket index and bilog) and chapter 41 (the request path).

# Periods and commit {#sec-42-2}

The multisite configuration is recorded in a **period**: an id, `epoch`, `realm_epoch`, `predecessor_uuid`, the master zonegroup and master zone, and the full map of zonegroups. Changes are first collected in the "staging" period (id `<realm-id>:staging`), and `radosgw-admin period update --commit` builds it on top of the current period.

::: {.algo #alg-42-1 title="Committing a period" src="src/rgw/rgw_zone.cc :: commit_period; src/rgw/rgw_period.cc" complexity="O(size of the period map); then propagation to all zones"}
:::

```text
pseudocode
commit_period(staging, current):
    require staging.master_zone == this zone                     # only the master zone commits
    require staging.predecessor_uuid == current.id
    require staging.realm_epoch == current.realm_epoch + 1
    if staging.master_zone != current.master_zone:               # failover / master change
        store current metadata sync status into the new period
        new period id ; epoch = FIRST_EPOCH ; realm_epoch advances
        set as realm's current period ; new mdlog prefix meta.log.<new-period>.
    else:
        require staging.epoch == current.epoch (else "period pull")
        keep current.id ; epoch = current.epoch + 1                # same period, newer epoch
    store period ; notify all zones (push to their /admin/realm/period)
```

The result: ordinary changes (adding a zone, an endpoint, a placement) only raise the epoch, and the mdlog continues. But changing the master zone creates a new period and therefore a **new mdlog**; the metadata sync status is stored in the previous period so that the zones can first read the old period's log to its end and then move to the new period. The message "does not come directly after current realm epoch. Use 'realm pull'" means this zone does not have the current period.

```bash
# example: viewing the current period
radosgw-admin period get-current
radosgw-admin period get | jq '{id, epoch, realm_epoch, predecessor_uuid, master_zone}'
```

```text
example (output):
{ "current_period": "7c1f2b9e-5d1a-4c2e-9a0f-3b8d6e4f1a20" }
{ "id": "7c1f2b9e-5d1a-4c2e-9a0f-3b8d6e4f1a20", "epoch": 4, "realm_epoch": 2,
  "predecessor_uuid": "0e9a4d33-1b6c-4f7e-8a25-c5d2f8b7e911", "master_zone": "b3a9e1c4-...-zone-a" }
```

# The format of log records {#sec-42-3}

| Log | Location | Record | Main fields |
|---|---|---|---|
| bilog | in InIndex mode, in the omap of each index shard with the key `0x80 0_<index_ver>…` (chapter 40); in FIFO mode, in separate FIFO objects | `rgw_bi_log_entry` | id, object, instance, timestamp, ver, op, state, index_ver, tag, bilog_flags, owner (for a delete marker), zones_trace |
| datalog | `data_log.<N>` in the log pool (FIFO or omap) | `rgw_data_change` | entity_type, key (`bucket:instance:shard`), timestamp, gen |
| mdlog | `meta.log.<period>.<N>` in the log pool | a cls_log entry with a section and name (for example `bucket` and `photos`) and `RGWMetadataLogData` data | read_version, write_version, status |

**zones_trace** is the list of zones a change has passed through; when the destination zone fetches an object from the source and writes a bilog entry of its own, the source zone is in the trace, and the change is not sent back during reverse sync. Without it, in an active-active topology every write would bounce back and forth in an endless loop.

The **gen** field in the datalog (and the generation suffix in the names of status objects) only has meaning after reshards that have created a new generation; the encoding of `rgw_data_change` has compat 1 when gen is zero and 2 otherwise, so old RGWs can still read entries without a generation.

![The chain of three logs for a PUT in the source zone. complete in the index writes a bilog entry, RGW records the bucket shard key in the datalog, and the destination zone reads the datalog, fetches the bilog of that shard from its marker onward and copies the object with fetch_remote_obj. Metadata changes are read separately from the mdlog of the current period](figures/ch42/f01_logs.png){#fig-42-f01_logs}

# Sync status on RADOS {#sec-42-4}

All status objects are in the log pool of the **destination** zone (`<zone>.rgw.log`) and are named after the source zone's id (`rgw_data_sync.cc` and `rgw_sync.cc`):

| Object | Content |
|---|---|
| `datalog.sync-status.<src-zone>` | `rgw_data_sync_info`: the overall state (Init, BuildingFullSyncMaps, Sync) and the number of shards |
| `datalog.sync-status.shard.<src-zone>.<N>` | `rgw_data_sync_marker`: the shard state, marker, next_step_marker, total_entries, pos, timestamp |
| `datalog.sync-status.shard.<src-zone>.<N>.retry` | **error repo**: the keys of failed bucket shards in omap |
| `data.full-sync.index.<src-zone>.<N>` | the list of this shard's buckets for full sync |
| `bucket.full-sync-status.<src-zone>:<bucket>` | `rgw_bucket_sync_status`: state, full, incremental_gen, shards_done_with_gen |
| `bucket.sync-status.<src-zone>:<bucket>:<shard>[:<gen>]` | `rgw_bucket_shard_sync_info`: the state (Init, FullSync, IncrementalSync, Stopped) and inc_marker |
| `mdlog.sync-status` and `mdlog.sync-status.shard.<N>` | metadata sync status |
| `data-sync-bids` and `meta-sync-bids` | the RGWs' bids for owning shards |

Each datalog shard is processed by only one RGW in the destination zone at any moment. This is done with a **lease** (a cls lock with `rgw_sync_lease_period` of 2 minutes that is renewed) and, in new versions, with a **bid** mechanism that spreads the shards among the available RGWs; an RGW that loses a bid releases the shard.

# The data sync engine {#sec-42-5}

::: {.algo #alg-42-2 title="Incremental sync of a datalog shard" src="src/rgw/driver/rados/rgw_data_sync.cc :: RGWDataSyncShardCR, RGWDataIncSyncShardCR, RGWDataSyncSingleEntryCR, RGWDataFullSyncShardCR" complexity="O(new datalog entries); at most rgw_data_sync_spawn_window (20) concurrent bucket shards"}
:::

```text
pseudocode
for each datalog shard N owned by this RGW (lease or bid):
    state Init → BuildingFullSyncMaps: list all buckets of source into data.full-sync.index.*
    full sync: for each bucket shard in index → sync bucket shard (full) ; advance marker
    incremental: loop
        also wake on out-of-band notify from source (modified shards)
        entries = remote datalog list(N, after marker)
        for each entry key = bucket:instance:shard (gen):
            spawn RGWDataSyncSingleEntryCR (≤ 20 in flight, same key coalesced)
                ok   → advance marker when all earlier entries done (marker tracker)
                fail → write key to <status>.retry (error repo) ; marker still advances
        every pass: retry keys from error repo with backoff ; remove on success
```

The essential point is that **the shard marker advances despite failures**; otherwise one broken bucket would stall the whole shard. Failures stay in the error repo and are retried separately. `radosgw-admin sync error list` shows the recorded permanent failures, and `data sync status --shard-id N --source-zone Z` the details of one shard.

::: {.algo #alg-42-3 title="Syncing a bucket shard and an object" src="src/rgw/driver/rados/rgw_data_sync.cc :: RGWSyncBucketCR, RGWBucketFullSyncCR, RGWBucketShardIncrementalSyncCR, RGWObjFetchCR; src/rgw/driver/rados/rgw_rados.cc :: fetch_remote_obj, obj_time_weight" complexity="full: O(objects in the bucket); incremental: O(bilog entries after the marker)"}
:::

```text
pseudocode
sync bucket (source bucket, dest bucket, gen):
    status = bucket.full-sync-status ; if Init → Full: list source bucket (versions) and fetch each
    init: incremental_gen = source latest_gen (full listing already covers older generations)
    Full done → Incremental
    incremental shard: bilog list(shard, gen, after inc_marker) from source
        squash entries of same object/instance ; skip entries whose zones_trace has this zone
        for each: ADD / LINK_OLH → fetch_remote_obj ; DEL / UNLINK_INSTANCE → remove locally
        advance inc_marker via marker tracker
    when every shard of gen is done (shards_done_with_gen) and remote has gen+1:
        incremental_gen = gen+1 (shard count may differ after reshard)
fetch_remote_obj(copy_if_newer):
    GET object from source zone (with sync manifest, attrs, versioned_epoch)
    compare obj_time_weight: mtime (seconds unless high precision), then zone_short_id, then pg_ver
    if destination copy is not older → skip ; else write locally, zones_trace += source
```

**Generations and reshard.** In the old model, a reshard in one zone destroyed the bilogs of the old shards, and the destination zone had to full sync that bucket from scratch. With the generational layout, a reshard creates generation `gen+1` with the new number of shards and **keeps the previous generation's bilogs until** all peers have completed `shards_done_with_gen` for that generation. The destination reads the old generation to its end, then moves to the new generation; each shard's status is stored separately with the `:<gen>` suffix. Automatic trimming of the old generation's log (`rgw_sync_log_trim_interval` 20 minutes) happens after that.

![The transition between bilog generations after a reshard: generation 0 with 11 shards and generation 1 with 23 shards. The destination zone syncs all shards of generation 0 to their end and marks them in shards_done_with_gen, then moves incremental_gen to 1; the generation 0 log is trimmed only after all peers have finished](figures/ch42/f02_gens.png){#fig-42-f02_gens}

**A conflict example.** Object `k` is written in zone A at 07:15:00.400 and in zone B at 07:15:00.900 (the same second). At one-second precision the mtimes are equal and the decision is made by `zone_short_id`: the version from the zone with the larger short id wins, and both zones end up with that same version. That is, multisite does not guarantee **last writer wins** in the strict temporal sense; applications that are sensitive to write order should write each key in only one zone or use versioning.

# Metadata sync {#sec-42-6}

::: {.algo #alg-42-4 title="metadata sync from the master zone" src="src/rgw/driver/rados/rgw_sync.cc :: RGWMetaSyncCR, RGWMetaSyncShardCR, RGWMetaSyncSingleEntryCR" complexity="O(new mdlog entries); rgw_meta_sync_spawn_window (20) concurrent"}
:::

```text
pseudocode
non-master zone, for each mdlog shard N of the current period (lease or bid):
    full sync: list all metadata keys on master (meta.full-sync.index.*) ; fetch each
    incremental: read meta.log.<period>.<N> after marker ; for each entry (section:key):
        GET /admin/metadata/<section>?key=K from master ; put locally (versioned with read/write version)
    on period change: finish old period's log to its end, then switch to new period's log
writes of metadata (create user, bucket) on non-master: forwarded to master zone first
```

That is why creating a bucket or a user in a non-master zone fails when the master is unavailable, while writing objects to existing buckets continues. (Failover and promoting the master are covered in chapter 5.)

# Multisite command reference {#sec-42-7}

| Command | Use |
|---|---|
| `radosgw-admin sync status` | a summary of metadata and data sync against each source |
| `radosgw-admin data sync status --source-zone Z [--shard-id N]` | the status of the data sync shards |
| `radosgw-admin metadata sync status` / `metadata sync run` | the status and manual run of metadata sync |
| `radosgw-admin bucket sync status --bucket B [--source-zone Z]` | the status of one bucket and its generations |
| `radosgw-admin bucket sync markers --bucket B --source-zone Z` | the markers of the bucket's shards |
| `radosgw-admin bucket sync run --bucket B --source-zone Z` | manually syncing one bucket |
| `radosgw-admin bucket sync {disable,enable} --bucket B` | stopping and resuming for one bucket |
| `radosgw-admin bilog {list,status,trim,autotrim} --bucket B` | a bucket's bilog |
| `radosgw-admin datalog {list,status,trim} [--shard-id N]` | datalog |
| `radosgw-admin mdlog {list,status,trim} [--period P]` | mdlog |
| `radosgw-admin sync error {list,trim}` | sync errors |
| `radosgw-admin data sync init --source-zone Z` | returning data sync to full sync (expensive) |
| `radosgw-admin period {get,get-current,pull,update --commit}` | period |
| `radosgw-admin sync group ...` (with the flow and pipe subcommands) | sync policy (chapter 5) |

```bash
# example: a bucket that is in generation 1 after a reshard
radosgw-admin bucket sync status --bucket logs --source-zone zone-a
```

```text
example (output):
          realm 2f61a0c4-... (prod)
      zonegroup 9b07d2e1-... (eu)
           zone 5c3e8a77-... (zone-b)
         bucket :logs[a1b2c3d4-...4123.9])
   current time 2026-11-15T07:20:11Z

    source zone b3a9e1c4-... (zone-a)
  source bucket :logs[a1b2c3d4-...4123.9])
                incremental sync on 23 shards
                bucket is behind on 2 shards
                behind shards: [4,17]
```

::: {.sim name="multisite"}
:::

# Tuning and troubleshooting {#sec-42-8}

- **Lagging shards that do not advance:** look at `sync error list` and `data sync status --shard-id N`; if one bucket keeps failing, `bucket sync run` for that bucket isolates the problem and makes it visible.
- **Unbounded growth of the datalog or bilog:** an old or removed peer is still defined in the zonegroup and trim is waiting for its marker (chapter 5); remove the dead zone from the zonegroup and commit the period.
- **Slow sync with many small buckets:** carefully increase `rgw_data_sync_spawn_window` and `rgw_bucket_sync_spawn_window` (both 20), and raise the number of syncing RGWs so the bids spread out. RGWs that serve users can be separated from sync with `rgw_run_sync_thread = false`.
- **After a master change:** if zones are stuck on the old period, `period pull` and an RGW restart are needed.
- **Content differences despite "caught up":** temporarily turn on `rgw_sync_obj_etag_verify` (default false) so that the ETag of each copied object is checked.

The operator's side of the same machinery (monitoring the lag, failover, failback and resync, and a DR drill) is in [Appendix K: Multisite and Disaster Recovery](#appL).

# Supplementary and up to date {#sec-42-9}

- The generational bilog layout and sync after a reshard in multisite are supported in recent versions, and they require the zonegroup feature `resharding`; before resharding in multisite, check `radosgw-admin zonegroup get` and the `enabled_features` list.
- The bid mechanism for spreading shards is in the main branch; older versions had only the lease, and one RGW could take most of the shards.
- In the main branch the option `rgw_default_bucket_bilog_type` (default `fifo`) determines whether new buckets keep their bilog in the index (`inindex`) or in a separate FIFO; existing InIndex buckets migrate at their next reshard. This behavior does not exist in older released versions; check your version before relying on it.

# Hands-on exercise {#sec-42-10}

1. In a two-zone environment, add an endpoint to the zonegroup, commit, and see the epoch change. Then change the master and see the id and realm_epoch change.
2. Do a PUT and follow its entry in `bilog list`, `datalog list` and then in `bucket sync markers` in the destination zone.
3. Write one object in the same second in both zones and see which version wins; compare the result with the two zones' `zone_short_id` (in `zonegroup get`).
4. Reshard a bucket in the source zone and follow the destination's `bucket sync status` until it moves to the new generation.

## Capstone project for Part IV: trace one object through RGW and RADOS {#sec-42-10-1}

**Goal.** For one S3 object in a two-zone setup, show every RADOS object and index entry that represents it, and how they change through upload, overwrite, sync and deletion.

**Requirements.**

1. A lab with two zones in one zonegroup and a versioned bucket.
2. One multipart upload of a file larger than the part size, then an overwrite of the same key.
3. The RADOS objects (head, tail and multipart parts), the bucket index entries, and the bilog and datalog entries for that key, each found with the tools of this part.
4. The object followed to the second zone through the sync markers.
5. A deletion, then the garbage collector or lifecycle followed until the tail objects are gone.

**Acceptance criteria.**

- A table lists each RADOS object and omap key you found, its pool, and its role, and each row was verified with a command whose output you kept.
- You can show the point at which the second zone had the object, using the sync status and markers rather than only listing the bucket there.
- After deletion you show which objects were removed at once and which waited for gc, and why.
- Anything you expected but did not observe is listed, with your explanation.

**Hints.** The RGW data model and bucket index: chapter 40. The request path, gc and lifecycle: chapter 41. Multisite internals and sync status: this chapter. Basic RGW and multisite setup: chapters 4 and 5. How the OSD applies the operations underneath: chapter 34.

# Review questions {#sec-42-11}

1. What three conditions does committing a period check before anything else?
2. When does a commit change the period id, and what is the consequence for the mdlog?
3. What problem does zones_trace in the bilog solve?
4. What does the key of a datalog entry identify?
5. In which object and which pool is the sync status of a bucket shard?
6. Why does the datalog shard marker advance despite a bucket's failure, and where is the failure recorded?
7. What roles do the lease and the bid play in sync?
8. After a reshard in the source zone, how does the destination zone continue without a full sync?
9. In what order of criteria is a concurrent-write conflict resolved?
10. Why does creating a bucket in a non-master zone depend on the master being available?

# Sources for this chapter {#sec-42-12}

- rgw_zone.cc (commit_period): https://github.com/ceph/ceph/blob/main/src/rgw/rgw_zone.cc
- rgw_data_sync.cc and rgw_data_sync.h: https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_data_sync.cc
- rgw_sync.cc (metadata sync): https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_sync.cc
- rgw_datalog.h: https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_datalog.h
- cls_rgw_types.h (rgw_bi_log_entry): https://github.com/ceph/ceph/blob/main/src/cls/rgw/cls_rgw_types.h
- Multisite documentation: https://docs.ceph.com/en/latest/radosgw/multisite/
- Dynamic resharding documentation (including multisite): https://docs.ceph.com/en/latest/radosgw/dynamicresharding/
