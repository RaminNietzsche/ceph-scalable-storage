---
chapter: 7
id: ch07
title: Operating and Managing a Ceph Cluster
part: main
lang: en
---

::: {.tldr}

- With cephadm every daemon is a container under systemd and you manage services declaratively with `ceph orch`; configuration lives in the MON database, not in `ceph.conf`.
- Keep each node under about 10–15% of raw capacity and leave enough free space to survive the loss of the largest failure domain without crossing `nearfull`.
- A failed OSD is marked out after `mon_osd_down_out_interval` (10 minutes) and recovery starts; replace disks with `ceph orch osd rm --replace` and use host maintenance mode for planned work.
- Upgrades are staged and automatic with `ceph orch upgrade`; the three full ratios and `MAX AVAIL` in `ceph df` explain why free space is less than it looks.

:::

# Before you start {#sec-07-1}

## What questions does this chapter answer? {#sec-07-1-1}

Building a cluster takes a day; running it takes years. This chapter covers the operator's day-to-day work: managing services, configuration, growing and shrinking the cluster, replacing disks, upgrading releases and controlling recovery load. The 2019 book did these tasks by editing `ceph.conf` by hand, with `ceph-deploy` and with packaged systemd units. In a modern cluster with cephadm most of these tasks have become declarative: you state the desired state and the orchestrator keeps it in place.

- What layers does service management have in cephadm, and where does systemd fit?
- Where is configuration kept today, and why is `ceph.conf` almost empty?
- How do we add or remove nodes, OSDs and MONs?
- What is the safe procedure for replacing a failed disk?
- How do we upgrade without downtime and with controlled risk?
- How do we slow down or speed up recovery and backfill, especially with the mClock scheduler?

# Managing services {#sec-07-2}

## Control layers {#sec-07-2-1}

![The daemon management layers in cephadm: from the ceph orch command to the container on the host](figures/ch07/f01_layers.png){#fig-07-f01_layers}

In cephadm each daemon is a container run by a systemd unit. The orchestrator (the cephadm module in the MGR) creates, removes or restarts daemons on the hosts over SSH. You normally work only with the top layer:

```bash
ceph orch ls                          # services and the number of desired/running daemons
ceph orch ps                          # all daemons
ceph orch ps --daemon-type osd --hostname ceph-node2
ceph orch ls --export > cluster-specs.yaml   # a backup of the desired state
```

## Start, stop and restart {#sec-07-2-2}

```bash
ceph orch restart rgw.objstore            # all daemons of a service, one by one
ceph orch daemon restart osd.3
ceph orch daemon stop mds.fs01.ceph-node3.xyzabc
ceph orch daemon start mds.fs01.ceph-node3.xyzabc
ceph orch daemon redeploy mgr.ceph-node1.abcdef   # rebuild the container (e.g. after an image change)
```

## systemd behind the scenes {#sec-07-2-3}

On each host the systemd units have a specific naming scheme that includes the cluster fsid. This naming lets several clusters run on one host (for example in a lab) without interfering.

```bash
FSID=$(ceph fsid)
systemctl list-units "ceph-${FSID}*"
systemctl status ceph-${FSID}@osd.3.service
sudo systemctl stop ceph-${FSID}.target      # stop all daemons of this cluster on this host
sudo systemctl start ceph-${FSID}.target
journalctl -u ceph-${FSID}@osd.3 --since "1 hour ago"
cephadm logs --name osd.3                  # the same log through cephadm
```

::: {.warn}
If you stop a daemon directly with systemctl, the orchestrator does not know about it and may restart it or report an error in the next reconciliation cycle. For planned work on a whole host, use **maintenance mode** (below). Keep systemctl for local debugging or for when the MGR is unavailable.
:::

# Configuration {#sec-07-3}

## The centralised configuration database {#sec-07-3-1}

![Configuration sources and their order of precedence; see each daemon's effective value with ceph config show](figures/ch07/f02_config.png){#fig-07-f02_config}

Since Mimic, the cluster configuration has been kept in the **MON configuration database**, and `ceph.conf` on the hosts holds only the minimum information needed to find the MONs (fsid and mon_host). The 2019 book still taught adding `[mon.a]` and `[osd.0]` sections to `ceph.conf`; today this is neither necessary nor recommended.

```bash
cat /etc/ceph/ceph.conf                      # usually a few lines
ceph config dump                              # all non-default settings
ceph config get osd osd_memory_target
ceph config set osd osd_memory_target 6442450944
ceph config set osd.12 osd_memory_target 8589934592    # one OSD only
ceph config set osd/class:ssd osd_memory_target 8589934592   # all SSD OSDs (mask)
ceph config set client.rgw.objstore rgw_max_concurrent_requests 2048
ceph config show osd.3 | grep memory_target   # the effective value in the running daemon
ceph config help osd_memory_target
ceph config log 10                            # the change history
```

::: {.tip}
The `ceph config log` and `ceph config reset <n>` commands let you roll back configuration changes. Before any big change, save the output of `ceph config dump` in version control (Git) so that you can compare the differences later.
:::

## Temporary changes at run time {#sec-07-3-2}

```bash
ceph tell osd.* config set debug_osd 10/10      # temporarily, until restart
ceph tell osd.* config set debug_osd 1/5        # restore
ceph daemon osd.3 config show                    # through the admin socket, on the same host (inside a cephadm shell)
```

::: {.note}
`ceph tell` sends a message to the daemon over the network; `ceph daemon` works through the local admin socket and is available only on that daemon's host (in cephadm, inside `cephadm shell --name osd.3`). When a daemon does not respond because it is stuck on network messages, the admin socket usually still answers.
:::

# Growing and shrinking the cluster {#sec-07-4}

## Scale-up or scale-out? {#sec-07-4-1}

![Two ways to add capacity: more disks in the same nodes, or more nodes](figures/ch07/f05_scale.png){#fig-07-f05_scale}

| Criterion | Scale-up (denser nodes) | Scale-out (more nodes) |
|---|---|---|
| Cost per terabyte | Usually lower | Somewhat higher (CPU, network, rack) |
| Failure domain | Large; losing one node recovers a large part of the data | Smaller; faster recovery with less impact |
| Performance | Each node's CPU and network become the bottleneck | More linear as nodes are added |
| Limitation | Minimum number of nodes for EC and the failure domain | Rack space, switches and power |

::: {.tip}
A practical rule: no node should hold more than about 10 to 15 percent of the cluster's raw capacity. Also, the cluster's free space should be large enough that after losing the largest failure domain (node or rack), the OSDs do not cross the `nearfull` ratio.
:::

## Adding a node and OSDs {#sec-07-4-2}

```bash
# On the new node: install podman, set up time (chrony) and the cluster SSH key
ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph-node5
ceph orch host add ceph-node5 192.168.10.15 --labels osd
ceph orch device ls ceph-node5 --refresh
# If your OSD spec (e.g. all-available-devices or a spec with a filter) is active, OSDs are created automatically
ceph orch ls osd
ceph -s
```

::: {.warn}
Suddenly adding many OSDs causes widespread PG movement. On a busy cluster, set the `norebalance` and `nobackfill` flags before adding, create all the OSDs, and then remove the flags so that data moves once rather than several times. Tools such as the **balancer** module even out the distribution after backfill finishes.
:::

```bash
ceph osd set norebalance && ceph osd set nobackfill
ceph orch apply -i osd-spec.yaml
ceph osd tree
ceph osd unset nobackfill && ceph osd unset norebalance
```

## Adding MONs and MGRs {#sec-07-4-3}

In cephadm the number and placement of MONs are set with the `mon` service spec:

```yaml
service_type: mon
placement:
  count: 5
  label: mon
```

```bash
ceph orch host label add ceph-node5 mon
ceph orch apply -i mon-spec.yaml
ceph mon stat
ceph quorum_status -f json-pretty | jq '.quorum_names'
```

::: {.note}
Keep the number of MONs odd (3 or 5). Five MONs tolerate losing two MONs; more than 5 usually only adds consensus overhead. Place MONs in different failure domains (racks or rooms).
:::

## Removing an OSD {#sec-07-4-4}

```bash
ceph osd safe-to-destroy osd.9        # can it be removed without losing data?
ceph osd ok-to-stop osd.9             # would stopping it temporarily make a PG unavailable?
ceph orch osd rm 9                    # drain and remove
ceph orch osd rm status
```

`ceph orch osd rm` first sets the OSD's weight to zero, waits until all PGs have moved elsewhere, then removes the daemon and deletes the OSD from CRUSH and the map. With `--zap` the disk is also wiped (LVM and partitions) so that it can be used again.

## Removing a whole host {#sec-07-4-5}

```bash
ceph orch host drain ceph-node5       # drains all daemons, including OSDs
ceph orch osd rm status
ceph orch ps ceph-node5               # should become empty
ceph orch host rm ceph-node5
```

::: {.warn}
`--offline --force` in `host rm` is only for a host that is lost for good; this option removes its OSDs without draining and is safe only when their data can be rebuilt from other copies.
:::

# Replacing a failed disk {#sec-07-5}

![The safe disk replacement procedure: recovery first, then the safe-to-destroy check, then removal keeping the id, and the physical replacement](figures/ch07/f03_replace.png){#fig-07-f03_replace}

When a disk fails, its OSD goes down, and after `mon_osd_down_out_interval` (default 10 minutes) it is automatically marked out and recovery starts. The suggested procedure:

```bash
ceph health detail
ceph osd tree down
ceph device ls-by-daemon osd.7                 # device id and host
ceph device light on <devid> ident             # turn on the identification light (if the hardware supports it)
# wait until the data has been recovered
ceph -s
ceph osd safe-to-destroy osd.7
ceph orch osd rm 7 --replace --zap
ceph orch osd rm status
# after physically replacing the disk
ceph orch device ls ceph-node2 --refresh
ceph osd tree | grep osd.7
```

::: {.deep}
The `--replace` option keeps the OSD in the `destroyed` state instead of removing it completely; its id and position in CRUSH are preserved. When the OSD spec sees the new disk on the same host, it creates the new OSD with the same id. The advantage is that the CRUSH map does not change and less data moves.
:::

::: {.tip}
Device health management (`ceph device`) collects the SMART data of the disks and can predict failures. Check it with `ceph device monitoring on` and `ceph device get-health-metrics <devid>`. If `mgr/devicehealth/self_heal` is enabled, the OSDs of disks with a high probability of failure are marked out preemptively.
:::

# Upgrading {#sec-07-6}

![The upgrade order in cephadm: MGR and MON first, then OSD and MDS, and the gateways last](figures/ch07/f04_upgrade.png){#fig-07-f04_upgrade}

cephadm performs upgrades automatically and in stages, and it respects the correct order. Before upgrading:

- Read the release notes of the target release in full, especially the "Upgrading" section and the incompatible changes.
- Check the allowed upgrade path: Ceph usually supports upgrades from at most two major releases back.
- The cluster must be `HEALTH_OK` and every PG `active+clean`.
- For Umbrella, check the host prerequisites: the images are based on el10, and a CPU at the x86-64-v3 level is required.

```bash
ceph versions
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade status
ceph -W cephadm                         # follow the upgrade events
ceph orch upgrade pause                 # in case of trouble
ceph orch upgrade resume
ceph orch upgrade stop
```

## Staged and limited upgrades {#sec-07-6-1}

cephadm lets you limit an upgrade to a specific daemon type, service or host. Umbrella added the ability to upgrade OSDs **bucket by bucket** in CRUSH, which uses the new `ceph osd ok-to-upgrade` command to check which OSDs can be upgraded at the same time:

```bash {since=umbrella}
ceph orch upgrade start --image quay.io/ceph/ceph:v21.2.0 --daemon-types mgr,mon
ceph orch upgrade start --image quay.io/ceph/ceph:v21.2.0 --daemon-types osd --crush_bucket_type rack --crush_bucket_name rack-a
```

::: {.warn}
In a multi-stage upgrade you must respect the order yourself: no daemon may be newer than the MGRs and MONs. After all OSDs have been upgraded, cephadm normally sets `require_osd_release`; confirm with `ceph osd dump | grep require_osd_release`. Until this value is set, new OSD features are not enabled and the related warning remains.
:::

# Capacity and balance {#sec-07-7}

## Fullness ratios {#sec-07-7-1}

Ceph has three thresholds to prevent OSDs from filling up completely. A completely full OSD is very dangerous in Ceph, because BlueStore needs free space even to delete data:

| Threshold | Default | Effect |
|---|---|---|
| nearfull_ratio | 0.85 | OSD_NEARFULL warning |
| backfillfull_ratio | 0.90 | Backfill to this OSD stops |
| full_ratio | 0.95 | Writes to the dependent pools stop (OSD_FULL) |

```bash
ceph osd dump | grep -E 'full_ratio|nearfull'
ceph osd df tree                    # usage percentage and PG count of each OSD
ceph df detail                      # raw and usable space of each pool
```

::: {.warn}
If the cluster reaches `OSD_FULL`, the natural first reaction (deleting data) may not work. The emergency procedure: temporarily `ceph osd set-full-ratio 0.97` (only to make room for deletion), delete or move non-essential data, add capacity, and then set the ratio back to its default. Never raise this ratio permanently.
:::

## The real "usable" capacity {#sec-07-7-2}

The `MAX AVAIL` figure in `ceph df` computes each pool's usable capacity taking into account the redundancy type and the **fullest OSD**. That is, imbalance reduces usable capacity: if one OSD fills up first, the whole pool counts as full. Use these rules for capacity planning:

- Divide raw capacity by the redundancy factor (3 for three-way replication, `(k+m)/k` for EC).
- Subtract the space needed to tolerate the failure of the largest domain.
- Subtract a safety margin up to nearfull (usually aim for normal usage under 70 percent).

::: {.try}
You have a cluster with 8 nodes and 12 disks of 16 TB in each node, and the failure domain is host. Raw capacity is 1536 TB. With three-way replication about 512 TB remains usable. To tolerate losing one node (one eighth of the capacity) and stay under 85 percent after recovery, keep normal usage at about 70 percent, that is around 350 to 360 TB. Repeat the same calculation for EC 4+2.
:::

## The balancer {#sec-07-7-3}

The **balancer** module in the MGR evens out the distribution by setting **upmap** mappings (explicit movement of PGs between OSDs). In current releases it is enabled by default, and `upmap` mode requires clients at least at the Luminous level.

```bash
ceph balancer status
ceph balancer mode upmap
ceph balancer on
ceph config set mgr target_max_misplaced_ratio .03     # at most 3% of data misplaced at any moment
ceph osd df | sort -nk17 | tail                        # the fullest OSDs
```

::: {.deep}
Reef added the new modes `read` and `upmap-read`, which balance **primaries** as well as data distribution so that read load becomes more even (by default reads are served by each PG's primary OSD). These modes use the `pg-upmap-primary` mapping, and all clients must be Reef or newer. On a cluster with heterogeneous disks, this mode can reduce read bottlenecks on a few OSDs.
:::

## Automatic PG scaling {#sec-07-7-4}

The **pg_autoscaler** module adjusts each pool's PG count based on the stored data or a target size you declare:

```bash
ceph osd pool autoscale-status
ceph osd pool set rbd target_size_ratio 0.4          # this pool is expected to take 40% of the cluster
ceph osd pool set cephfs.fs01.meta pg_autoscale_mode on
ceph osd pool set images bulk true                   # a large pool: get enough PGs from the start
```

::: {.note}
In Umbrella the default of `mon_target_pg_per_osd` was raised from 100 to 200 and the cap `mon_max_pg_per_osd` from 250 to 500. After upgrading, the autoscaler may raise the PG count of some pools and data movement may start. Compare the output of `autoscale-status` before and after the upgrade, and schedule the changes if necessary.
:::

::: {.sim name="pgcalc"}
:::

# Inside the code: MON, Paxos and the map services {#sec-07-8}

## The role of Paxos in Ceph {#sec-07-8-1}

All the cluster maps (MonMap, OSDMap, MgrMap, FSMap, the central configuration, cephx keys and so on) are stored on **one shared Paxos instance** in `src/mon/Paxos.cc`. Each "service" (`PaxosService`; such as `OSDMonitor`, `AuthMonitor`, `ConfigMonitor`) proposes its changes to this Paxos, and Paxos writes them one by one, with a contiguous version number (`last_committed`), into the monitor's RocksDB. Ceph's implementation is a form of **Multi-Paxos with a stable leader**: after an election the leader runs the recovery phase (collect/last) once, and from then on each change needs only one round trip (begin/accept) and one commit message.

![The sequence of Paxos messages in the MON: after an election the leader announces a new proposal number with OP_COLLECT and gathers unfinished values with OP_LAST; then, for each change, OP_BEGIN is sent with the next version, OP_ACCEPT is received from every quorum member, OP_COMMIT is announced, and OP_LEASE grants the peons permission to serve reads for mon_lease](figures/ch07/s01_paxos.png){#fig-07-s01_paxos}

| Message (MMonPaxos) | Direction | Meaning |
|---|---|---|
| OP_COLLECT (1) | leader → peon | Start a round with a new proposal number (pn) |
| OP_LAST (2) | peon → leader | Accept the pn and send unfinished accepted values |
| OP_BEGIN (3) | leader → peon | Proposed value for the next version |
| OP_ACCEPT (4) | peon → leader | Accept the value |
| OP_COMMIT (5) | leader → peon | Announce the agreed value |
| OP_LEASE (6) | leader → peon | Extend read permission |
| OP_LEASE_ACK (7) | peon → leader | Acknowledge the lease |

An important difference from classic Paxos: to commit, the leader waits for acceptance from **all members of the current quorum**, not just a majority. In `Paxos::handle_accept()`:

```cpp
// from ceph/ceph, LGPL — src/mon/Paxos.cc, handle_accept() (excerpt)
accepted.insert(from);
...
if (accepted == mon.get_quorum()) {
```

This is possible because the quorum itself came out of a majority election; if one quorum member does not respond, an accept timeout occurs and a new election is held so that a smaller quorum (still a majority) forms. The advantage: all quorum members always have all versions and can serve reads under a lease.

## States and the lease {#sec-07-8-2}

The Paxos states in `Paxos.h`: `STATE_RECOVERING`, `STATE_ACTIVE`, `STATE_UPDATING`, `STATE_UPDATING_PREVIOUS`, `STATE_WRITING`, `STATE_WRITING_PREVIOUS`, `STATE_REFRESH` (and SHUTDOWN). A read from a peon is allowed only when it holds a valid lease. Parameters:

| Option | Default | Role |
|---|---|---|
| mon_lease | 5 seconds | Validity period of the read lease |
| mon_lease_renew_interval_factor | 0.6 | Renew after 60% of the lease period |
| mon_lease_ack_timeout_factor | 2 | If the ack does not arrive within twice the lease, re-elect |
| paxos_propose_interval | 1 second | Batching interval for changes before proposing |
| mon_election_timeout | 5 seconds | Election timeout |

::: {.deep}
The lease is the main reason the MON is sensitive to **clock skew**: the leader tells a peon "you may serve reads until time T". If the peon's clock is behind, it may still hand the old map to a client after the leader has committed a new one. The `MON_CLOCK_SKEW` warning (threshold `mon_clock_drift_allowed`) exists to prevent exactly this situation.
:::

## From command to new map {#sec-07-8-3}

![The path of a command in a Paxos service such as OSDMonitor: read-only commands are answered in preprocess_query from the current map; modifying commands are applied in prepare_update to the pending incremental, batched with a paxos_propose_interval delay and proposed to Paxos with propose_pending; after commit the map is loaded, the incremental is published to subscribers and the issuer gets a reply](figures/ch07/s02_service.png){#fig-07-s02_service}

```text
pseudocode: PaxosService (this book's summary of PaxosService.cc and OSDMonitor.cc)
  dispatch(op):
      if preprocess_query(op): return            # read-only; e.g. osd dump
      if not leader: forward(op to leader); return
      if prepare_update(op):                     # change on pending_inc
          if should_propose(delay):              # batching with paxos_propose_interval
              schedule propose_pending() after delay
  propose_pending():
      t = new transaction
      encode_pending(t)                          # OSDMap::Incremental → bytes
      paxos.begin(t)                             # OP_BEGIN to the quorum
  on commit:
      update_from_paxos()                        # new epoch
      publish incrementals to subscribers        # OSDs and clients
      reply to waiting ops
```

::: {.note}
This is why running several dozen `ceph osd ...` commands at the same time usually produces **one** new epoch with all the changes, not dozens of epochs. And it is also why a modifying command takes about a second even when the cluster is completely quiet.
:::

## Elections {#sec-07-8-4}

`src/mon/ElectionLogic.h` has three election strategies: `CLASSIC` (rank-based; the lowest rank wins), `DISALLOW` (a list of MONs must not become leader) and `CONNECTIVITY` (includes DISALLOW, and prefers the MON with better connectivity based on connectivity scores stored in the store). Stretch mode requires `connectivity` (chapter 18).

```bash
ceph mon dump | grep election_strategy
ceph mon set election_strategy connectivity
ceph mon add disallowed_leader e         # the tiebreaker MON never becomes leader
ceph quorum_status | jq '.quorum_leader_name, .quorum_names'
ceph daemon mon.a sessions | jq length   # on the MON host
```

# Daily operations by the numbers: down, out, grace and MAX AVAIL {#sec-07-9}

The four algorithms in this section run in the MON and answer a few everyday operator questions: why an OSD was or was not marked down at this moment, why it was marked out after ten minutes, and why `ceph df` shows less free space than the raw space. References are to main as of November 2026, and the numbers were computed with a Python reimplementation.

## Marking down: reporters and grace {#sec-07-9-1}

::: {.algo #alg-07-1 title="The MON's decision to mark an OSD down" src="src/mon/OSDMonitor.cc :: OSDMonitor::check_failure, get_grace_time, is_failure_stale" complexity="O(number of reporters)"}
:::

```text
pseudocode
group the reporters by mon_osd_reporter_subtree_level (default host)
if number of groups < mon_osd_min_down_reporters (2): not yet
failed_for = now − failed_since                      # from the first report, backdated
grace = osd_heartbeat_grace (20)
if mon_osd_adjust_heartbeat_grace (true):
    decay = exp(failed_for × ln 0.5 / mon_osd_laggy_halflife (3600))
    grace += decay × laggy_interval × laggy_probability             # the OSD's own history
    grace += the mean of the same term for the reporters (decayed from their down_stamp)
if failed_for ≥ grace: mark the OSD down in the next map
if failed_for ≥ grace + osd_heartbeat_stale (600 s) and still no decision: discard the reports
```

**Numerical example.** A healthy OSD with no laggy history (p = 0) is marked down when its peers on at least two different hosts report it and failed_for reaches 20 seconds. Because OSDs themselves report after 20 seconds without a ping reply, this is usually almost simultaneous with the first reports. If all the reports come from OSDs on one host, the group count is 1 and the OSD is never marked down. This is deliberate, because a network problem on one host should not cause the rest of the cluster to be marked down. In a three-host cluster, if the other two hosts are healthy, the condition is met.

![The timeline of a powered-off OSD with the defaults. After 20 seconds without replies, peers on two hosts report it and the MON marks it down. PGs become degraded, but no data moves. After 600 seconds (plus the laggy term) the OSD is marked out and backfill starts. The purple line shows the exceptions: the noout flag and a whole rack being down (mon_osd_down_out_subtree_limit), which reset the counter](figures/ch07/f09_downout.png){#fig-07-f09_downout}

## Laggy history: an exponential moving average {#sec-07-9-2}

::: {.algo #alg-07-2 title="Updating laggy_probability and laggy_interval" src="src/mon/OSDMonitor.cc :: OSDMonitor::prepare_boot, grace_interval_threshold_exceeded, set_default_laggy_params" complexity="O(1)"}
:::

```text
pseudocode
w = mon_osd_laggy_weight (0.3)
on boot of an OSD that had been marked down:
    if boot_epoch == 0 (the process really started afresh):  p ×= 0.7 ; I ×= 0.7
    else (the process was alive, i.e. the down was wrong):
        gap = min(now − down_stamp, mon_osd_laggy_max_interval 300)
        I = w × gap + (1 − w) × I ;  p = w + (1 − w) × p
if the next down happens more than 48 × laggy_halflife (48 hours) after the previous down_stamp: p = I = 0
```

**Numerical example.** An OSD that is wrongly marked down under heavy load and comes back 40 seconds later each time has p = 0.3 and I = 12 after the first time. After the second time p = 0.51 and I = 20.4, and after the third p = 0.657 and I = 26.28. So the grace for the next failure is about 20 + 0.657 × 26.28 = 37.3 seconds. The decay here is computed on failed_for, i.e. a few tens of seconds, and is about 0.994. The grace series for 1 to 8 wrong downs is: 23.6, 30.4, 37.3, 43.1, 47.7, 51.1, 53.7 and 55.5 seconds. Its upper bound is 20 + 40 = 60 seconds. That is, the MON automatically becomes more patient with "difficult" OSDs. What clears the history is not the passage of time but a real process restart or 48 hours without a down. The same term, with decay based on the down duration, is also added to mon_osd_down_out_interval. For the example above, out happens after about 615 seconds, not 600.

![Left: growth of laggy_probability and laggy_interval with each wrong down (a live OSD that returns 40 seconds later), with weight 0.3. Right: the effective grace of the next failure, i.e. the 20-second base plus p × I. The peer term is assumed to be zero in this example. If the next down is more than 48 hours later, the history is reset](figures/ch07/f08_laggy.png){#fig-07-f08_laggy}

## From down to out {#sec-07-9-3}

::: {.algo #alg-07-3 title="Automatic marking out" src="src/mon/OSDMonitor.cc :: OSDMonitor::tick (down_pending_out), can_mark_out; src/osd/OSDMap.cc :: containing_subtree_is_down" complexity="O(down OSDs × CRUSH depth)"}
:::

```text
pseudocode
every tick, for each OSD in down_pending_out:
    down = now − time it was marked down
    grace = mon_osd_down_out_interval (600) + exp(down × ln 0.5 / 3600) × I × p
    if noout flag (global, or on a CRUSH node or device class) or can_mark_out refuses: continue
    if a whole subtree of type mon_osd_down_out_subtree_limit (rack) is down: down_pending_out[o] = now ; continue
    if down ≥ grace: mark the OSD out (reweight = 0) ← PGs are remapped and backfilled
```

**Numerical example.** An OSD with no history is marked out exactly 600 seconds after going down. If a whole rack with 3 hosts and 36 OSDs is powered off, none of their counters advance and no automatic out happens. This policy is conservative: it assumes that a complete rack outage (power or switch) is transient and should not cause tens of terabytes of data to move. For planned maintenance of a host, use `ceph osd set-group noout <host>` or `ceph orch host maintenance enter` instead of the global flag.

## MAX AVAIL in ceph df {#sec-07-9-4}

::: {.algo #alg-07-4 title="Estimating a pool's usable space" src="src/mon/PGMap.cc :: PGMap::get_rule_avail, dump_object_stat_sum; src/osd/OSDMap.cc :: pool_raw_used_rate" complexity="O(OSDs in the rule)"}
:::

```text
pseudocode
wm = each OSD's weighted share in the rule (get_rule_weight_osd_map, sum = 1)
for each OSD with weight > 0:
    avail = max(0, kb_avail − kb × (1 − full_ratio))      # the 5% reserve before full
    proj  = avail / wm[osd]                                # how much raw data until this OSD fills
raw_avail = min(proj)                                       # the fullest OSD relative to its share
MAX AVAIL = raw_avail / raw_used_rate     # replicated: size ; EC: (k + m) / k
```

**Numerical example.** Consider a cluster with 52 TiB raw: eleven 4 TB OSDs and one 8 TB OSD. Ten of the 4 TB OSDs are 60% full, osd.10 is 80% and osd.11 (8 TB) is 55%. The weighted share of each 4 TB OSD is 4/52. For the 60% OSDs we have proj = (1.6 − 0.2) / (4/52) = 18.2 TiB, but for osd.10 only (0.8 − 0.2) / (4/52) = 7.8 TiB. The MAX AVAIL of a three-replica pool is 7.8 / 3 = 2.6 TiB, and of an EC 4+2 pool 7.8 / 1.5 = 5.2 TiB. If osd.10 were also at 60%, the same three-replica pool would show 6.1 TiB. So one unbalanced OSD eats more than half of the reported "usable" space. This definition is correct, because CRUSH spreads data in proportion to weight and that same OSD fills up first. The remedy is the balancer in upmap mode, not adding disks.

![Left: the usage percentage of twelve OSDs, with one 4 TB OSD 80% full (red). Right: for each OSD, the raw data that can be written before that OSD reaches full_ratio. Their minimum (red line) is the basis of MAX AVAIL and is divided by size or (k + m) / k](figures/ch07/f10_maxavail.png){#fig-07-f10_maxavail}

![The ladder of fullness ratios with the defaults: the NEARFULL warning from 85%, backfill to the OSD stops from 90%, the FULL flag and client writes stop from 95%, and the OSD's own failsafe from 97%. The first three ratios are kept in the OSDMap and changed with set-*-ratio. The failsafe is an OSD configuration option](figures/ch07/f11_ratios.png){#fig-07-f11_ratios}

::: {.sim name="capacity"}
:::

# Day-to-day maintenance {#sec-07-10}

## Host maintenance mode {#sec-07-10-1}

For planned work (kernel updates, part replacement, reboots), use cephadm's maintenance mode. This mode stops all Ceph daemons on the host and sets the `noout` flag for that host only, so that its OSDs are not marked out and no unnecessary recovery starts:

```bash
ceph osd ok-to-stop $(ceph osd ls-tree ceph-node2 | tr '\n' ' ')   # is it safe to stop all OSDs on this host?
ceph orch host maintenance enter ceph-node2
# ... reboot the host or repair it ...
ceph orch host maintenance exit ceph-node2
ceph -s
```

::: {.warn}
`--force` in `maintenance enter` bypasses the safety checks. If the host holds the last healthy MON or the last available copy of some PGs, forcing it into maintenance means an outage. If `ok-to-stop` answers no, fix the cause first.
:::

## Cluster flags {#sec-07-10-2}

| Flag | Effect | Typical use |
|---|---|---|
| noout | Down OSDs are not marked out automatically | Short maintenance |
| norebalance | Rebalancing of healthy data stops | Adding OSDs in bulk |
| nobackfill | Backfill stops | Reducing load at peak hours |
| norecover | Recovery stops | Only in emergencies and briefly |
| noscrub, nodeep-scrub | No new scrub starts | Heavy operations, upgrades |
| pause | All reads and writes stop | Almost never in production |

```bash
ceph osd set noout
ceph osd unset noout
ceph osd set-group noout osd.4    # one OSD only
ceph osd set-group noout ceph-node3   # all OSDs of one host (a CRUSH bucket)
ceph osd unset-group noout ceph-node3
```

::: {.tip}
Forgotten flags are one of the most common causes of strange cluster behaviour (for example, data never recovers because `norecover` was left on). In monitoring, take the `OSDMAP_FLAGS` warning seriously and check `ceph osd dump | grep flags` after every maintenance.
:::

## Controlling recovery and backfill speed {#sec-07-10-3}

To slow recovery down, older guides taught setting `osd_max_backfills`, `osd_recovery_max_active` and `osd_recovery_sleep` directly. Since Quincy the default OSD scheduler is **mClock**, and it manages these settings itself. The right way today is to choose a **profile**:

| Profile | Priority | Use |
|---|---|---|
| balanced (default) | Balance between client and recovery | Normal operation |
| high_client_ops | Clients first; slower recovery | Peak hours, latency-sensitive cluster |
| high_recovery_ops | Recovery first | After a big failure, in off-peak hours |

```bash
ceph config get osd osd_mclock_profile
ceph config set osd osd_mclock_profile high_recovery_ops
# after recovery finishes
ceph config set osd osd_mclock_profile balanced
```

::: {.deep}
In mClock mode the OSD ignores values such as `osd_max_backfills` and `osd_recovery_max_active`, or sets them itself. If you really need to set them by hand, you must first set `osd_mclock_override_recovery_settings` to `true`. mClock relies on each OSD's IOPS capacity, measured at first start-up (`osd_mclock_max_capacity_iops_hdd` and `_ssd`), to allocate shares. If this measurement was taken on a busy disk, the unrealistic value spoils the recovery share. In Squid the shard defaults for HDDs changed (`osd_op_num_shards_hdd` set to 1 with 5 threads) to make mClock's behaviour on HDDs more predictable.
:::

::: {.sim name="mclock"}
:::

## Prioritising specific PGs {#sec-07-10-4}

```bash
ceph pg force-recovery 2.1f
ceph pg force-backfill 2.1f 2.20
ceph pg cancel-force-recovery 2.1f
```

## Scrub {#sec-07-10-5}

Light scrub (daily) compares the replicas' metadata, and deep-scrub (weekly) checks the data with checksums. To reduce scrub's impact on clients, limit it to off-peak hours:

```bash
ceph config set osd osd_scrub_begin_hour 1
ceph config set osd osd_scrub_end_hour 6
ceph pg deep-scrub 2.1f
ceph health detail | grep -i scrub
```

::: {.summary title="SRE notes for this chapter"}

- Keep the desired state in Git with `ceph orch ls --export`.
- Configuration lives in the MON database; do not edit `ceph.conf` by hand.
- Before any removal: `ok-to-stop` and `safe-to-destroy`.
- Replace disks with `--replace` so that the id and CRUSH position are kept.
- Host maintenance only with `maintenance enter/exit`.
- Remove flags after the work; monitor `OSDMAP_FLAGS`.
- Control recovery speed with the mClock profile, not manual tuning.
- Upgrades: release notes, HEALTH_OK, a path of at most two releases, monitoring after the upgrade.

:::

::: {.sim name="scrub"}
:::

# Supplementary and up to date {#sec-07-11}

- **ceph-deploy** is retired, and ceph-ansible is no longer the recommended path either; cephadm and Rook are the two supported methods of deployment and operation.
- **Centralised configuration** (Mimic) replaced editing `ceph.conf`.
- **mClock** (default since Quincy) handed recovery control over to profiles; Squid point release 19.2.1 changed the HDD shard defaults to 1 shard × 5 threads (issue 66289).
- **Umbrella**: OSD upgrades in CRUSH bucket order and the `ceph osd ok-to-upgrade` command; the x86-64-v3 CPU prerequisite and el10 images; and higher defaults of 200 for `mon_target_pg_per_osd` and 500 for `mon_max_pg_per_osd`, which affect PG planning in upgraded clusters.
- **Tentacle**: the restful and zabbix modules were removed from the MGR; if your operational scripts depend on restful, move them to the dashboard API before upgrading.

# Hands-on exercise {#sec-07-12}

1. Save the output of `ceph orch ls --export`, change the number of MGRs and look at the difference with `diff`.
2. Change `osd_memory_target` for the ssd-class OSDs only and check it on one OSD with `ceph config show`.
3. Put a host into maintenance mode, reboot it and exit. Note the output of `ceph -s` and the flags along the way.
4. Simulate a disk failure with `ceph orch daemon stop osd.N`; after it is marked out, run the replacement procedure with `--replace`.
5. Change the mClock profile to `high_recovery_ops` and compare the recovery speed (`ceph -s`) with `balanced`.
6. In a lab, upgrade the cluster to the latest point release of the same line and follow the stages with `ceph -W cephadm`.

# Review questions {#sec-07-13}

1. Why is stopping a daemon with systemctl not recommended in cephadm?
2. What is the precedence order of configuration sources, and how do you see the effective value?
3. What is the difference between `ceph tell` and `ceph daemon`?
4. Compare the advantages and disadvantages of scale-up and scale-out in terms of failure domain.
5. Why are the norebalance and nobackfill flags useful when adding many OSDs?
6. What is the difference between `ok-to-stop` and `safe-to-destroy`?
7. What advantage does the `--replace` option give when removing an OSD?
8. What does cephadm's maintenance mode do?
9. Why does setting `osd_max_backfills` directly have no effect under mClock, and what is the right way?
10. What risk does upgrading OSDs in CRUSH bucket order in Umbrella reduce?

# Sources for this chapter {#sec-07-14}

- cephadm operations: https://docs.ceph.com/en/latest/cephadm/operations/
- Host management: https://docs.ceph.com/en/latest/cephadm/host-management/
- OSD service: https://docs.ceph.com/en/latest/cephadm/services/osd/
- Upgrading Ceph (cephadm): https://docs.ceph.com/en/latest/cephadm/upgrade/
- Configuring Ceph: https://docs.ceph.com/en/latest/rados/configuration/ceph-conf/
- ceph command reference: https://docs.ceph.com/en/latest/man/8/ceph/
- mClock config reference: https://docs.ceph.com/en/latest/rados/configuration/mclock-config-ref/
- Device management: https://docs.ceph.com/en/latest/rados/operations/devices/
- Monitor/OSD interaction: https://docs.ceph.com/en/latest/rados/configuration/mon-osd-interaction/
- Adding/removing monitors: https://docs.ceph.com/en/latest/rados/operations/add-or-rm-mons/
- Release index: https://docs.ceph.com/en/latest/releases/
- Tentacle release notes: https://docs.ceph.com/en/latest/releases/tentacle/
