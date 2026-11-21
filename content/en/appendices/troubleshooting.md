---
id: troubleshooting
lang: en
---

This appendix is a compact guide to handling the most common unhealthy states. Each row starts from a "symptom" and leads to the first diagnostic commands and the direction of the fix. The full explanation of each case is in the chapter listed.

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
