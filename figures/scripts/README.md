# Figure scripts

| Script | Migrated from |
|---|---|
| `compute_bloom_false_positive.py` | `r25.py` |
| `compute_crc32c.py` | `crc.py` |
| `compute_gf256_tables.py` | `gf.py` |
| `compute_rbd_striping.py` | `str.py` |
| `compute_varint_encoding.py` | `enc.py` |
| `measure_cls_lua.py` | `sim/lua15.py` |
| `measure_cls_numops.py` | `sim/cls15.py` |
| `measure_mgr_dump.py` | `sim/mgr09c.py` |
| `measure_mgr_lag.py` | `sim/mgr09b.py` |
| `measure_mgr_stats.py` | `sim/mgr09.py` |
| `measure_osd_memory.py` | `sim/mem33.py` |
| `measure_pg_states.py` | `sim/pgstates.py` |
| `measure_rbd_du.py` | `sim/du_real.py` |
| `plot_ch01.py` | `mk01.py` |
| `plot_ch01_copysets.py` | `v14/cs_fig.py` |
| `plot_ch02.py` | `mk02.py` |
| `plot_ch02_rbd_du.py` | `v14/du_fig.py` |
| `plot_ch03.py` | `mk03.py` |
| `plot_ch04.py` | `mk04.py` |
| `plot_ch05.py` | `mk05.py` |
| `plot_ch06.py` | `mk06.py` |
| `plot_ch07.py` | `mk07.py` |
| `plot_ch08_measured.py` | `v14/ch08_fig.py` |
| `plot_ch09.py` | `mk09.py` |
| `plot_ch09_measured.py` | `v14/ch09_fig.py` |
| `plot_ch10.py` | `mk10.py` |
| `plot_ch10_measured.py` | `v14/ch10_fig.py` |
| `plot_ch11.py` | `mk11.py` |
| `plot_ch12.py` | `mk12.py` |
| `plot_ch13.py` | `mk13.py` |
| `plot_ch14.py` | `mk14.py` |
| `plot_ch15.py` | `mk15.py` |
| `plot_ch15_measured.py` | `v14/ch15_fig.py` |
| `plot_ch16.py` | `mk16.py` |
| `plot_ch16_b.py` | `mk16b.py` |
| `plot_ch17.py` | `mk17.py` |
| `plot_ch17_host_failure.py` | `v14/ch17_host.py` |
| `plot_ch17_pg_timeline.py` | `v14/ch17_pg.py` |
| `plot_ch18.py` | `mk18.py` |
| `plot_ch19.py` | `mk19.py` |
| `plot_ch19_measured.py` | `v14/ch19_fig.py` |
| `plot_ch20.py` | `mk20.py` |
| `plot_ch21.py` | `mk21.py` |
| `plot_ch22_measured.py` | `v14/ch22_fig.py` |
| `plot_ch23.py` | `mk23.py` |
| `plot_ch24.py` | `mk24.py` |
| `plot_ch24_allocator.py` | `v14/ch24_alloc.py` |
| `plot_ch24_label.py` | `v14/ch24_label.py` |
| `plot_ch25.py` | `mk25.py` |
| `plot_ch26.py` | `mk26.py` |
| `plot_ch27.py` | `mk27.py` |
| `plot_ch29.py` | `mk29.py` |
| `plot_ch33_measured.py` | `v14/ch33_fig.py` |

`lib/` holds the simulation models imported by the plot scripts. `measure_*` scripts need a running test cluster (`CEPH_CONF`); their output is committed under `figures/data/`.
