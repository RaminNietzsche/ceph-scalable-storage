---
id: multisite-dr
lang: en
---

::: {.tldr}

- Choose the layer first: stretch mode for an RPO of zero across two close sites, independent clusters with asynchronous replication (RGW multisite, rbd-mirror, cephfs-mirror) for distant sites, and an independent backup against mistakes and ransomware.
- Asynchronous replication means an RPO greater than zero: the replication lag at the moment of failure is the data you can lose, so measure it all the time (`sync status`, `bucket sync status`, `sync error list`, the sync perf counters).
- A planned switchover waits until sync is caught up; an unplanned failover promotes the secondary zone (`zone modify --master --default`, then `period update --commit`) only after the old master is confirmed down and its RGWs are stopped.
- Before a returning site writes anything, it must pull the new realm and period; then it catches up, and only then do you decide whether to move the master back.
- For RBD, demote then promote in a planned switchover, `promote --force` in a disaster, and `resync` the old primary afterwards; rehearse all of it in a drill with recorded times.

```bash
radosgw-admin sync status
```

[![The multisite switchover, failover and failback flow: planned or not, promote the secondary zone, commit the period, move DNS, pull the period on the returning site, catch up, and record the times](figures/app/f04_multisite_failover.png)](#fig-app-multisite-failover)

:::

This appendix is a practical guide for running Ceph across sites and for recovering when a site is lost. Chapter 5 sets up RGW multisite, chapter 42 explains periods and the sync engines in the code, chapter 18 covers rbd-mirror and stretch mode, and chapter 6 covers CephFS snapshot mirroring; this appendix puts them together as an operator's plan: which topology to choose, what RPO and RTO to expect, how to watch replication, and step-by-step runbooks for switchover, failover and failback, ending with a drill checklist. Security of the gateways and of the system user's keys is in [Appendix J: RGW Security](#appK), and the commands are also in [Appendix B: Command Cheat Sheet](#appB).

![The multisite flow for a planned switchover and an unplanned failover: stop writes and wait for caught up, or confirm the failure and stop the old RGWs; promote the secondary zone and commit the period on it; move DNS or GSLB and the endpoints; when the old site returns, pull the realm and the period before any write, catch up with sync status or data sync init, and decide whether to move the master back; finally record the times and the real RPO and RTO](figures/app/f04_multisite_failover.png){#fig-app-multisite-failover}

# Choosing the topology

![The DR options: one cluster across two sites with stretch mode (RPO zero, low latency, a tiebreaker in a third site); independent clusters with asynchronous replication through RGW multisite, rbd-mirror and cephfs-mirror; and an independent backup with Object Lock](figures/app/f05_dr_options.png){#fig-app-dr-options}

| Option | What it protects | RPO | Requirements and limits |
|---|---|---|---|
| Stretch mode (one cluster) | Loss of one of two data sites | Zero (synchronous writes to both sites) | Low latency between sites, a tiebreaker monitor in a third site, double raw capacity; a cluster-wide bug or mistake reaches both sites |
| RGW multisite | Loss of a site or a cluster, for objects | Seconds to minutes, the replication lag | Independent clusters, one realm; metadata changes need the master zone |
| rbd-mirror, journal mode | Loss of a cluster, for block images | Seconds | Every write is written twice; the journaling feature is not supported by krbd |
| rbd-mirror, snapshot mode | Loss of a cluster, for block images | The schedule interval | Low overhead; works with krbd |
| cephfs-mirror | Loss of a cluster, for directories | The snapshot interval | Snapshot-based, one direction per peer |
| Independent backup | Mistakes, ransomware, software bugs | The backup interval | Must be outside the replication path and protected against deletion |

Replication copies a mistake as faithfully as it copies data: a deleted bucket or an overwritten image reaches the other site within seconds. Every DR plan therefore needs a backup layer as well (chapter 18), for example a copy with Object Lock or an archive zone that keeps all versions.

Within RGW multisite, the main topology choices are:

- **Active-active** zones in one zonegroup: clients write to both sites, and each zone pulls the changes of the other. This is the default and gives the shortest RTO, but writing the same object in two sites at once ends with one version winning.
- **Active-passive**: clients use only the master zone, and the secondary zone is kept for failover; set `rgw_enable_apis` or the load balancer so that the passive zone does not take client writes, or mark it with `--read-only`.
- **Several zonegroups**: data is replicated only inside a zonegroup, metadata (users, buckets) across the whole realm. Use them to keep data in a region, not for DR of the same data.
- **Sync policy and archive zone**: replicate only some buckets, or in one direction, and keep every version in an archive zone (see below).

# RPO and RTO with asynchronous replication

**RPO** (how much data can be lost) is the replication lag at the moment of failure. In RGW multisite it is made of the time until the destination zone notices a change (each zone reads the remote data log every `rgw_data_sync_poll_interval` seconds, 20 by default, unless `rgw_data_notify_interval_msec` is set), plus the time to copy the backlog. Under a steady load the lag is seconds; after a link outage or a burst of large uploads it can grow to hours. Metadata changes made on the master zone that were not yet synced (a new user, a bucket, a policy) are also lost when the master is lost.

**RTO** (how long until service returns) is the sum of: detection, the decision to fail over (usually the longest part), promotion and period commit (seconds), restart of the RGWs, and the DNS or GSLB change, whose TTL decides how quickly clients move. With a short DNS TTL (for example 60 seconds) and a written runbook, an RTO of 15 to 30 minutes is realistic; without a runbook it is hours.

::: {.tip}
Write down target values for RPO and RTO per service and check them in every drill. An RPO goal that the measured lag regularly exceeds is not a goal but a hope; add bandwidth, more syncing RGWs or a sync policy that excludes unimportant buckets.
:::

The multisite lab below models the replication lag after a link outage; try a few bandwidth and outage values to see how long catching up takes.

::: {.sim name="multisite"}
:::

# Monitoring sync

## Commands

```bash
radosgw-admin sync status
radosgw-admin bucket sync status --bucket=photos
radosgw-admin sync error list
radosgw-admin metadata sync status
radosgw-admin data sync status --source-zone=eu-1
radosgw-admin sync info
```

`sync status` is the first check (chapter 5, [sync status](#sec-05-6-1)). For metadata it should say "metadata is caught up with master", and for each source zone "data is caught up with source". "behind shards" lists the shards that are not caught up, and "oldest incremental change not applied" shows the time of the oldest change that is still waiting: the difference between that time and now is your current RPO for that source.

`bucket sync status` shows the same for one bucket, which is useful when a client reports a missing object. `sync error list` keeps the objects that failed to sync, with the error code; a growing list means a real problem (permissions of the system user, a missing placement target, a pool that is full). After you fix the cause and the objects have synced, clear old entries with `radosgw-admin sync error trim`.

## Metrics

Each RGW keeps sync perf counters per source zone, in the `data-sync-from-<zone>` set: `fetch_bytes`, `fetch_errors`, `poll_latency` and `poll_errors`. From Tentacle, the `rgw_sync_delta` counters report `sync_delta`, the lag of each data log shard in seconds, which is the most direct RPO metric:

```bash
ceph daemon client.rgw.eu2.host1.abcdef perf dump
```

Alert on: `sync status` not caught up for longer than your RPO target, a growing `sync error list`, `fetch_errors` or `poll_errors` that increase steadily, and an RGW in the destination zone that does not sync at all (for example because `rgw_run_sync_thread` is false on it). The Prometheus exporter of the manager exposes the RGW perf counters, so the same values can be graphed (chapter 20).

# Planned switchover

A switchover moves the master zone while both sites are healthy: before maintenance on the primary site, or as a drill. Because both sites are up, no data has to be lost.

1. Announce a window and stop changes to users, buckets and policies.
2. Move clients to read-only or stop writes to the current master zone, and wait until `radosgw-admin sync status` on the secondary zone says caught up for metadata and data.
3. On the secondary zone, make it the master and commit the period (the commands after this list).
4. Restart the RGWs of both zones, or let them pick up the new period (cephadm: `ceph orch restart rgw.<service>`).
5. Change DNS or the GSLB so that clients reach the new master, then allow writes again.
6. Check `radosgw-admin period get` on both sites: the same period id and epoch, and `master_zone` is eu-2.

```bash
radosgw-admin zone modify --rgw-zone=eu-2 --master --default
radosgw-admin period update --commit
```

If the zone endpoints change at the same time (a new load balancer, a new name), update them in the zone and zonegroup and commit again; other zones use these endpoints for sync:

```bash
radosgw-admin zone modify --rgw-zone=eu-2 --endpoints=https://s3-eu2.example.com
radosgw-admin zonegroup modify --rgw-zonegroup=eu --endpoints=https://s3.example.com
radosgw-admin period update --commit
```

# Unplanned failover

When the master site is lost, the other zones keep serving and accepting object data for existing buckets, but anything that needs the master zone (new users and buckets, policy changes) fails. If the outage will be long, promote the secondary zone (chapter 5, [When the master zone becomes unavailable](#sec-05-10-1)):

1. Confirm the failure through two independent paths, for example monitoring and the site team. A network split looks like a site failure from one side.
2. Make sure the old master cannot take writes: stop its RGWs or cut it off at the load balancer. This is the most important step against split brain.
3. Note the last "oldest incremental change not applied" time on the secondary zone: it is your RPO for this incident.
4. Promote and commit, as in the switchover, then restart the RGWs of the zone.
5. Move DNS or the GSLB to the new master.
6. Tell the service owners which data window may be missing.

# Failback and resync

When the old site returns, it still believes it is the master. Before its RGWs take any client traffic, give it the new period:

```bash
radosgw-admin realm pull --url=https://s3-eu2.example.com --access-key=<AK> --secret=<SK>
radosgw-admin period pull --url=https://s3-eu2.example.com --access-key=<AK> --secret=<SK>
radosgw-admin sync status
```

Then start its RGWs and let it catch up. Objects written to the old master but not yet replicated before the failure are still in its pools; data sync replicates them to the other zone when the logs that recorded them are processed. If the sync state of the returning zone is damaged or it has been away so long that the remote logs were trimmed, start a full sync from the other zone. This is safe but reads the whole data set again, so plan the bandwidth:

```bash
radosgw-admin data sync init --source-zone=eu-2
radosgw-admin metadata sync init
radosgw-admin bucket sync init --bucket=photos --source-zone=eu-2
radosgw-admin bucket sync run --bucket=photos --source-zone=eu-2
```

After an `init`, restart the RGWs of the zone so that the sync threads start from the new state. When `sync status` is caught up in both directions, you can move the master back with a planned switchover.

# Split brain

Split brain in multisite has two forms:

- **Two masters.** If both sites promote themselves during a network split, two period histories exist. The zone that pulls the period of the other loses its own metadata changes made in the meantime. Prevent it with the rule above: only one site may promote, and only after the old master is stopped; after the split ends, the returning site pulls the period before anything else.
- **Conflicting object writes.** In active-active mode both zones accept writes. When the same object is written in both during a split, data sync copies an object only if it is newer than the local copy (`copy_if_newer` in the sync code), so the version with the newer modification time wins and the other write is lost; with versioning both versions are kept. Keep clocks in sync with NTP on all RGW hosts, and give each application one home zone for writes.

Bucket deletion is also replicated: a bucket deleted on one side is deleted on the other. Protect important buckets with versioning, Object Lock, an archive zone or a separate backup.

# Metadata and data sync

| | Metadata sync | Data sync |
|---|---|---|
| What | Users, buckets (entry points and instances), roles, accounts | Objects and their versions |
| Direction | From the master zone of the realm to every other zone | Between the zones of one zonegroup, each zone pulling from the others |
| Log | mdlog (`rgw_md_log_max_shards` shards) | datalog (`rgw_data_log_num_shards` shards) and bucket index logs |
| Status | `metadata sync status` | `data sync status`, `bucket sync status` |
| Full resync | `metadata sync init` | `data sync init`, `bucket sync init` |

Chapter 42 explains both engines in the code ([Metadata sync](#sec-42-6), [The data sync engine](#sec-42-5)), and [Periods and commit](#sec-42-2) explains why a commit on a new master creates a new period.

# Sync policy and the archive zone

A sync policy (chapter 5, [Sync policy](#sec-05-11)) decides which buckets replicate, and in which direction, with groups, flows and pipes. A zonegroup-level policy that allows sync, with a bucket-level policy that enables it only for selected buckets, keeps the replication lag low for the data that matters:

```bash
radosgw-admin sync group create --group-id=group1 --status=allowed
radosgw-admin sync group flow create --group-id=group1 --flow-id=flow1 --flow-type=symmetrical --zones=eu-1,eu-2
radosgw-admin sync group pipe create --group-id=group1 --pipe-id=pipe1 --source-zones='*' --source-bucket='*' --dest-zones='*' --dest-bucket='*'
radosgw-admin period update --commit
radosgw-admin sync group create --bucket=photos --group-id=photos-sync --status=enabled
radosgw-admin sync group pipe create --bucket=photos --group-id=photos-sync --pipe-id=pipe1 --source-zones='*' --dest-zones='*'
```

An **archive zone** (chapter 5, [The archive zone](#sec-05-12)) receives the data of the other zones and keeps every version of every object, even after the object is deleted or overwritten in the other zones. It is a good second line against mistakes, but not a full backup: it is in the same realm and is managed with the same keys.

```bash
radosgw-admin zone create --rgw-zonegroup=eu --rgw-zone=eu-archive --endpoints=https://s3-archive.example.com --tier-type=archive
radosgw-admin period update --commit
```

# RBD mirroring

Chapter 18 sets up rbd-mirror ([rbd-mirror](#sec-18-3)); this is the failover part. Journal mode copies every write and gives an RPO of seconds; snapshot mode copies the difference between mirror snapshots and gives an RPO of the schedule interval.

```bash
rbd mirror pool status vmpool --verbose
rbd mirror image status vmpool/db01
```

**Planned switchover**: stop the application on site A, then demote on A and promote on B; the image stays consistent and nothing is lost:

```bash
rbd mirror image demote vmpool/db01
rbd mirror image promote vmpool/db01
```

Run the first command on site A and the second on site B, after `rbd mirror image status` on B shows the image is in sync. `rbd mirror pool demote vmpool` and `rbd mirror pool promote vmpool` do the same for every mirrored image of a pool.

**Unplanned failover**: site A is gone, so the image cannot be demoted cleanly; force the promotion on B:

```bash
rbd mirror image promote --force vmpool/db01
```

**Failback**: when site A returns, its copy of the image is also primary, so the two have diverged. Demote the old primary on A and resync it from B; resync discards A's copy and copies the image again:

```bash
rbd mirror image demote vmpool/db01
rbd mirror image resync vmpool/db01
```

When A is in sync again, move back with a planned switchover. Never promote on both sites while both are reachable by clients: two primaries with writes on both is split brain at the block level, and one side's writes are discarded by the resync. `rbd_mirroring_replay_delay` can delay the replay on the secondary site, which gives a window to stop a mistake from reaching it.

# CephFS mirroring

CephFS snapshot mirroring (chapter 6, [Snapshot mirroring between clusters](#sec-06-8-1)) copies the snapshots of chosen directories to another cluster with the cephfs-mirror daemon. It is one-way per peer and is meant for DR copies, not for an active-active file system:

```bash
ceph mgr module enable mirroring
ceph orch apply cephfs-mirror
ceph fs snapshot mirror enable cephfs
ceph fs snapshot mirror peer_bootstrap create cephfs client.mirror_remote site-b
ceph fs snapshot mirror add cephfs /projects
ceph fs snapshot mirror daemon status
```

The RPO is the interval of the snapshots (for example with `snap_schedule`). For failover, mount the copy on the other cluster; it is read-only from the mirror's point of view, so after failover disable mirroring for that directory before you write to it, and set up mirroring in the other direction for failback.

# Stretch mode or multisite?

Stretch mode (chapter 18, [stretch mode: one cluster across two sites](#sec-18-7)) keeps one cluster across two data sites with a tiebreaker monitor in a third site: writes go to both sites before they are acknowledged, so the RPO is zero and failover is automatic. It needs low latency between the sites (a few milliseconds), and it protects against the loss of a site, not against a mistake, a bug or an upgrade problem in the cluster, because there is only one cluster. Multisite and mirroring keep independent clusters with an RPO greater than zero and a manual failover, but a problem in one cluster does not reach the other. For large distances use multisite and mirroring; for two close sites that need an RPO of zero use stretch mode, and in both cases keep an independent backup.

# DR drill runbook

Run a drill at least twice a year, and after every big change in the topology. A drill that is not timed and written down did not happen.

**Before the drill**

1. Choose the scope: a planned switchover only, or a simulated loss of a site (stop its RGWs and rbd-mirror, or cut the link).
2. Write down the RPO and RTO targets and who decides on failover.
3. Check that the runbook, the system user's keys (kept as described in [Appendix J](#appK)) and the DNS access are available from the secondary site.
4. Create test data with known content and times: an object per minute in a test bucket, a test RBD image with a running write loop.

**During the drill**

1. Record the time of each step: detection, decision, promotion, period commit, DNS change, first successful client request.
2. Check `period get` on all sites after each commit.
3. Find the last test object and the last RBD write that reached the secondary site; the difference to the failure time is the measured RPO.

**After the drill**

1. Fail back, wait until `sync status` and `rbd mirror pool status` are healthy in both directions, and remove the test data.
2. Compare the measured RPO and RTO with the targets, and record what was slow or unclear.
3. Update the runbook, the alerts and this checklist.

## Checklist

| Check | Command or place | Expected |
|---|---|---|
| Same period everywhere | `radosgw-admin period get` | One period id and epoch, the expected `master_zone` |
| Metadata and data caught up | `radosgw-admin sync status` | "caught up" for metadata and every source |
| No growing sync errors | `radosgw-admin sync error list` | Empty, or only old, understood entries |
| Lag within the RPO target | `sync_delta` (Tentacle+), "oldest incremental change not applied" | Below the RPO target |
| Endpoints correct | `radosgw-admin zonegroup get` | The endpoints reach the RGWs of each zone |
| RBD mirroring healthy | `rbd mirror pool status --verbose` | `health: OK`, every image replaying |
| CephFS mirroring healthy | `ceph fs snapshot mirror daemon status` | Peers connected, no failed directories |
| DNS ready | The DNS or GSLB console | A short TTL, access from the secondary site |
| Keys available | The secret store | The system user's keys and an admin keyring for each site |
| Backup independent | The backup system | Latest backup within its interval, protected against deletion |

# Sources

- RGW multisite: https://docs.ceph.com/en/latest/radosgw/multisite/
- Multisite sync policy: https://docs.ceph.com/en/latest/radosgw/multisite-sync-policy/
- Archive zone: https://docs.ceph.com/en/latest/radosgw/archive-sync-module/
- RBD mirroring: https://docs.ceph.com/en/latest/rbd/rbd-mirroring/
- CephFS snapshot mirroring: https://docs.ceph.com/en/latest/cephfs/cephfs-mirroring/
- Stretch mode: https://docs.ceph.com/en/latest/rados/operations/stretch-mode/
- Sync perf counters (`src/rgw/driver/rados/rgw_sync_counters.cc`): https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_sync_counters.cc
