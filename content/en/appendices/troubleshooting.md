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

::: {.warn}
Commands such as `mark_unfound_lost delete`, `osd lost`, `ceph-objectstore-tool --op remove` and `osd force-create-pg` remove data permanently. Run them only when every other option has been exhausted, with a backup, and with a second person's approval.
:::
