---
id: troubleshooting
lang: en
---

This appendix is a compact guide to handling the most common unhealthy states. Each row starts from a "symptom" and leads to the first diagnostic commands and the direction of the fix. The full explanation of each case is in the chapter listed. For quick syntax lookup across all subsystems, see [Appendix B: Command Cheat Sheet](#appB).

# General principles

1. Before any action, record the state: `ceph -s`, `ceph health detail` and `ceph osd tree`.
2. Know the protective flags: `noout` for short maintenance work, and `norebalance` and `nobackfill` only for a clear reason. Remove them when the work is done.
3. Never make several changes at the same time. Note each change together with the command that reverts it.

# Symptom → action table

| Symptom (health warning) | First commands | Direction of the fix | Chapter |
|---|---|---|---|
| `OSD_DOWN` / `OSD_HOST_DOWN` | `ceph osd tree down`, `journalctl -u ceph-*@osd.N`, `ceph orch ps --daemon-type osd` | Check the disk, network and memory; restart; if the disk has failed, `ceph orch osd rm N --replace` | 17, 19 |
| `PG_AVAILABILITY` (inactive, stuck peering) | `ceph pg dump_stuck inactive`, `ceph pg <pgid> query \| jq .recovery_state` | Find the blocking OSD (`blocked_by`, `down_osds_we_would_probe`) and bring it back | 8, 17 |
| `PG_DEGRADED` / `undersized` | `ceph pg ls degraded`, `ceph osd df tree` | Wait for recovery; check that there are enough failure domains for size | 8 |
| `OBJECT_UNFOUND` | `ceph pg <pgid> list_unfound` | First bring up every previous OSD; use `mark_unfound_lost revert` only as the last resort | 17 |
| `OSD_SCRUB_ERRORS` / `PG_DAMAGED` (inconsistent) | `rados list-inconsistent-obj <pgid> --format=json-pretty` | Find the damaged copy (disk read error, checksum); then `ceph pg repair <pgid>` | 17 |
| `OSD_NEARFULL` / `OSD_BACKFILLFULL` / `OSD_FULL` | `ceph osd df`, `ceph df detail` | Add capacity, delete data, use the balancer; raise `full_ratio` temporarily only for an emergency exit | 19, 21 |
| `SLOW_OPS` | `ceph daemon osd.N dump_ops_in_flight`, `dump_historic_ops`, `ceph osd perf` | Find the event where the op is stuck (queued_for_pg, waiting for subops, commit); look for a slow disk or network | 17, 21 |
| `MON_DOWN` / lost quorum | `ceph quorum_status` (if it answers), `ceph daemon mon.X mon_status` on the host | Restore the majority; in the worst case, extract and inject the monmap | 7, 18 |
| `MON_CLOCK_SKEW` | `chronyc tracking`, `ceph time-sync-status` | Fix NTP/chrony on all MON hosts | 7 |
| `MON_DISK_LOW` / store growth | `du -sh /var/lib/ceph/*/mon.*` | Fix the reason trimming is not happening (a long-unhealthy PG); `ceph tell mon.X compact` | 7 |
| `LARGE_OMAP_OBJECTS` | `ceph health detail`, the cluster log for the object name | RGW: reshard, or trim the multisite logs; CephFS: look for a very large directory | 4, 5 |
| `BLUEFS_SPILLOVER` | `ceph daemon osd.N bluefs stats`, `ceph osd metadata N` | Enlarge the DB or move it to a faster device; compaction | 12 |
| `MDS_SLOW_REQUEST` / `MDS_CLIENT_LATE_RELEASE` | `ceph tell mds.X dump_ops_in_flight`, `session ls` | Find the client that does not release its cap; evict it in a controlled way | 6 |
| `MDS_TRIM_BEHIND` / `MDS_CACHE_OVERSIZED` | `ceph tell mds.X cache status`, `perf dump mds_log` | Raise `mds_cache_memory_limit` or reduce the load; pinning | 6 |
| `RECENT_CRASH` | `ceph crash ls-new`, `ceph crash info <id>` | Analyse the backtrace; then `ceph crash archive <id>` | 17 |
| `MGR_MODULE_ERROR` | `ceph mgr module ls`, the mgr log | Disable and re-enable the module; `ceph mgr fail` | 9 |
| `CEPHADM_*` (e.g. HOST_CHECK_FAILED) | `ceph orch host ls`, `ceph cephadm check-host <host>` | SSH, time, packages and podman/docker on the host | 11 |
| `OSDMAP_FLAGS` / `OSD_FLAGS` | `ceph health detail`, `ceph osd dump \| grep flags` | Remove flags left over from maintenance: `ceph osd unset <flag>`, or `ceph osd unset-group <flags> <who>` for OSDs, hosts or classes | 7, 19 |
| `POOL_APP_NOT_ENABLED` | `ceph osd pool ls detail` | Tag the pool: `rbd pool init <pool>` for RBD, or `ceph osd pool application enable <pool> <app>` | 2, 8 |
| `PG_NOT_SCRUBBED` / `PG_NOT_DEEP_SCRUBBED` | `ceph health detail`, `ceph osd dump \| grep flags`, `ceph config get osd osd_deep_scrub_interval` | Only clean PGs are scrubbed: fix degraded or misplaced PGs and `noscrub`/`nodeep_scrub` first; then `ceph pg deep-scrub <pgid>` | 19, 32 |
| `POOL_TOO_FEW_PGS` / `POOL_TOO_MANY_PGS` | `ceph osd pool autoscale-status` | Raised only in `warn` mode: `ceph osd pool set <pool> pg_autoscale_mode on`, or set `pg_num` by hand | 19 |
| `POOL_NEAR_FULL` / `POOL_FULL` | `ceph df detail`, `ceph osd pool get-quota <pool>` | Raise or remove the quota (`ceph osd pool set-quota <pool> max_bytes <bytes>`, 0 removes it), or add capacity | 7, 19 |
| `PG_BACKFILL_FULL` / `PG_RECOVERY_FULL` | `ceph pg ls backfill_toofull`, `ceph osd df tree` | Recovery is blocked by full OSDs: handle as `OSD_BACKFILLFULL` / `OSD_FULL` above | 19 |
| `OSD_TOO_MANY_REPAIRS` | `ceph health detail`, `ceph device ls-by-daemon osd.N` | Many read repairs point to a failing disk even without scrub errors: check and replace it, then `ceph tell osd.N clear_shards_repaired` | 17, 19 |
| `BLUESTORE_SLOW_OP_ALERT` | `ceph health detail`, the OSD log ("slow operation observed") | Usually a failing or overloaded drive: check the device and replace it if needed | 12, 17 |
| `DEVICE_HEALTH` | `ceph device ls`, `ceph device info <devid>` | Mark the OSD out, let the data move, then replace the disk; `mgr/devicehealth/self_heal` can do the mark-out | 7, 19 |
| `AUTH_INSECURE_GLOBAL_ID_RECLAIM_ALLOWED` | `ceph health detail` (is `AUTH_INSECURE_GLOBAL_ID_RECLAIM` also raised?) | If not, `ceph config set mon auth_allow_insecure_global_id_reclaim false`; otherwise upgrade the old clients first | 8 |
| `MDS_ALL_DOWN` / `FS_DEGRADED` | `ceph fs status`, `ceph orch ps --daemon-type mds` | Bring an MDS (or a standby) back for every failed rank; look at the MDS log for the reason | 6 |

::: {.warn}
Commands such as `mark_unfound_lost delete`, `osd lost`, `ceph-objectstore-tool --op remove` and `osd force-create-pg` remove data permanently. Run them only when every other option has been exhausted, with a backup, and with a second person's approval.
:::

# Step by step: a PG that does not become active

This procedure follows the official "Troubleshooting PGs" page and the peering code in `src/osd/PeeringState.cc`. Chapter 17 explains the state machine behind it.

## 1. Find the PGs and the kind of "stuck"

```bash
ceph health detail | grep -E "PG_AVAILABILITY|stuck|down|incomplete"
ceph pg dump_stuck stale # no OSD has reported the PG: its OSDs are probably all down
ceph pg dump_stuck inactive # a peering problem
ceph pg dump_stuck unclean # recovery cannot finish (often unfound objects)
ceph osd blocked-by # how many PGs each OSD is blocking
```

`stale` usually means that the OSDs holding the PG are not running, so start them before anything else. `inactive` points to peering and `unclean` to recovery.

## 2. Ask the PG why, and keep a copy of the answer before you change anything

```bash
ceph pg 2.1f query > pg-2.1f.json
jq '.state, .up, .acting' pg-2.1f.json
jq '.recovery_state[] | {name, comment, blocked, down_osds_we_would_probe, peering_blocked_by, peering_blocked_by_detail}' pg-2.1f.json
jq '.info.stats.blocked_by' pg-2.1f.json
```

## 3. Read the answer

The strings in the first column are printed by the peering states in `PeeringState.cc`.

| What `query` shows | Meaning | What to do |
|---|---|---|
| `Started/Primary/Peering/GetInfo` for a long time, `"blocked": "peering is blocked due to down osds"`, `down_osds_we_would_probe` | OSDs of an earlier interval that may have accepted writes are down, so peering cannot rule out newer data on them | Start those OSDs; `ceph osd tree down` and their logs show why they are down |
| `peering_blocked_by` with `"starting or marking this osd lost may let us proceed"` | Peering is waiting for that OSD | Bring it back. Only if its disk is certainly gone: `ceph osd lost <id> --yes-i-really-mean-it` (see the warning above) |
| `Started/Primary/Peering/Down` with `"not enough up instances of this PG to go active"` | Too few instances of the PG are up | Bring the OSDs back; check `min_size` and the failure domains |
| `Started/Primary/Peering/Incomplete` with `"not enough complete instances of this PG"` | No up OSD has a complete history of the PG | Start every failed OSD that may hold the PG. For an EC pool, the official PG-states page notes that temporarily lowering `min_size` may allow recovery; set it back afterwards |
| `Started/Primary/Peering/WaitUpThru` with `"waiting for osdmap to reflect a new up_thru for this osd"` | The primary is waiting for the MONs to record its `up_thru` | Check MON quorum and the network between this OSD and the MONs |
| `peering_blocked_by_detail` containing `peering_blocked_by_history_les_bound` | The newest complete log on the up OSDs is older than the epoch at which the PG last went active (`history.last_epoch_started`), so writes acknowledged after it may be missing | Find the OSD that held the newer copy: old disks, OSDs that were removed or are still down |

## 4. About `osd_find_best_info_ignore_history_les`

Advice on the internet sometimes suggests this option for the last row. In `PeeringState::find_best_info`, it makes peering skip the `history.last_epoch_started` bound, so an old log can be chosen as authoritative. The option has level `dev`, and its own description in `src/common/options/osd.yaml.in` reads: "THIS IS AN EXTREMELY DANGEROUS OPTION THAT SHOULD ONLY BE USED AT THE DIRECTION OF A DEVELOPER … typically leading to data loss". The loss is silent: writes that clients were told had succeeded can disappear without an error. Before you even consider it, bring back every OSD that might hold the PG, export the PG from each copy with `ceph-objectstore-tool` (chapter 17), and ask on the `ceph-users` list. Never set it globally, and remove it as soon as the PG has peered.

# Step by step: slow ops

This procedure follows the "Blocked Requests or Slow Requests" and "Debugging Slow Requests" sections of the official OSD troubleshooting page. Chapter 17 describes the op tracker in the code.

## 1. Find the OSDs

```bash
ceph health detail | grep -A5 SLOW_OPS
ceph osd perf | sort -n -k2 | tail # commit latency (ms) per OSD
```

## 2. Look at the operations through the OSD's admin socket

Run these on the OSD host (with cephadm, inside `cephadm shell --name osd.7`).

```bash
ceph daemon osd.7 dump_blocked_ops
ceph daemon osd.7 dump_ops_in_flight | jq '.ops[] | {age, description, flag: .type_data.flag_point}'
ceph daemon osd.7 dump_historic_slow_ops | jq '.ops[0].type_data.events'
ceph daemon osd.7 dump_historic_ops_by_duration | jq '.ops[0:3][] | {duration, description}'
```

| Command | What it returns (defaults from the documentation) |
|---|---|
| `dump_blocked_ops` | In-flight ops older than `osd_op_complaint_time` (30 s), the same threshold as the warning |
| `dump_ops_in_flight` | Every op being processed now, with `age` and the current `flag_point` |
| `dump_historic_slow_ops` | Completed ops that took at least `osd_op_history_slow_op_threshold` (10 s); up to `osd_op_history_slow_op_size` (20) are kept |
| `dump_historic_ops_by_duration` | Completed ops of the last `osd_op_history_duration` (600 s), at most `osd_op_history_size` (20), longest first |

All four need `osd_enable_op_tracker` (on by default).

## 3. Find the event with the longest duration

In the `type_data.events` array of each op, find the event with the largest duration and read it from this table:

| Longest event | Meaning | Next step |
|---|---|---|
| `queued_for_pg` | Backlog in the PG queue: high concurrent load, or the HDD shard layout under mClock | CPU and load on the host; the mClock note below |
| `waiting for peered`, `waiting for active`, `waiting for readable` | The PG is not active | The procedure above |
| `waiting for missing object`, `waiting for degraded object` | The object is waiting for recovery | Recovery state of the PG |
| `waiting for rw locks`, or `reached_pg` and `waiting for rw locks` repeating | Many clients writing to the same object | Reduce concurrent writes to that object (often an RGW index shard or an RBD header) |
| `started` (before `op_commit`) | Slow I/O on the primary's own device | `iostat`, the device's SMART data, `BLUESTORE_SLOW_OP_ALERT` |
| `waiting for subops from [X,Y]` | Replica X or Y is slow | The same steps on OSD X or Y, and the network between them |

Ignore the duration of the `throttled` event: the documentation explains that it often shows about 4,294,967,295 seconds because of an unsigned subtraction.

## 4. Check the common causes

The official page lists these causes:

- A failing drive: `dmesg -T`, `smartctl -a <device>`, or `nvme smart-log <device>` for NVMe.
- The network: a failed bond member, a hash policy that uses one link, an MTU mismatch, port errors or a saturated link (chapter 21).
- Recovery set too high: raised `osd_max_backfills` or `osd_recovery_max_active`. Under mClock these take effect only with `osd_mclock_override_recovery_settings=true`, and the `high_recovery_ops` profile also favours recovery over clients.
- An overloaded host, for example virtual machines running next to the OSDs.
- On HDD clusters with mClock, if most slow ops end in `queued_for_pg`: the official resolution is `osd_op_num_shards_hdd=1` with `osd_op_num_threads_per_shard_hdd=5`, which needs a staggered OSD restart. This layout is the default from Squid 19.2.1 (appendix H).

::: {.tip}
A slow op on one OSD is often the symptom of a slow replica or a slow link elsewhere. Do not restart many OSDs at once to "clear" slow ops: find the one OSD or link behind them first.
:::
