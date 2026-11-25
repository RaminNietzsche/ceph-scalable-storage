---
id: versions
lang: en
---

The table below shows the major Ceph releases from 2019 to today. Dates for active releases were taken from the official releases page (docs.ceph.com/en/latest/releases, November 2026).

| Name | Number | Status (November 2026) | Notes relevant to this book |
|---|---|---|---|
| Nautilus | 14.2 | Archived | Current in 2019; msgr2, pg_autoscaler, PG merging |
| Octopus | 15.2 | Archived | Introduced cephadm |
| Pacific | 16.2 | Archived | `bluestore_min_alloc_size_hdd` reduced to 4K; sharded RocksDB in BlueStore |
| Quincy | 17.2 | Archived | mClock as the default OSD scheduler |
| Reef | 18.2 | Archived | Cache tiering deprecated; RGW multisite improvements |
| Squid | 19.2 | Active; started 2024-09-26, estimated end 2026-12-02 | One of the bases of this book; from point release 19.2.1 the HDD default is 1 mClock shard with 5 threads (issue 66289) |
| Tentacle | 20.2 | Active; started 2025-11-18, estimated end 2027-06-01 | FastEC (`allow_ec_optimizations`); ISA-L default plugin for new clusters; SMB manager module |
| Umbrella | 21.2 | Active; started 2026-10-28, estimated end 2028-06-01 | `mon_target_pg_per_osd` set to 200; typed cls API |

::: {.note}
When upgrading, move forward at most two major releases at a time. Read the release notes of the target release in full, and set `require_osd_release` only after every OSD has been upgraded (chapter 19; the step-by-step runbook is appendix I).
:::
