---
chapter: 19
id: ch19
title: 'Day-to-Day Operations: Upgrades, Disk Replacement, Autoscaler and Balancer'
part: main
lang: en
---

::: {.tldr}

- cephadm upgrades are rolling: mgrs, then MONs one by one, then OSDs while PGs stay active, then the other daemons.
- Replace a disk with `--replace` so the OSD id and CRUSH position are kept and only its PGs are backfilled.
- Host maintenance mode checks that stopping a host is safe and sets `noout` for that host only.
- pg_autoscaler sets PG counts per pool and the upmap balancer evens out the PG distribution; device health and periodic checks belong in the routine.

```bash
ceph orch upgrade status
```

[![The upgrade procedure in three stages: cluster readiness, staged daemon upgrades with cephadm, and checking require_osd_release](figures/ch19/f01_upgrade.png)](#fig-19-f01_upgrade)

:::

# Before you start {#sec-19-1}

## What questions does this chapter answer? {#sec-19-1-1}

Most of a Ceph cluster's life consists of routine work: upgrading versions, replacing disks, adding and removing hosts, adjusting the number of PGs and balancing data. Each of these tasks is uneventful if done right, and turns into an incident if not. This chapter reviews today's procedures with cephadm and then goes inside two important mgr modules: **pg_autoscaler** and **balancer**.

- In what order does a cephadm upgrade proceed, and what is a staggered upgrade?
- How do we replace a failed disk while keeping the OSD id?
- How do we take a host out for maintenance, or remove it permanently?
- With what formula does pg_autoscaler compute the number of PGs, and what changed in Umbrella?
- In upmap mode, how does the balancer decide which PG to move?
- Which flags and settings are needed for maintenance work?

# Upgrading {#sec-19-2}

![The upgrade procedure in three stages: preparation, including a healthy cluster, reading the release notes and making sure the hosts can reach the image; the cephadm order, from mgr and mon to the OSDs with ok-to-stop checks and then the other daemons; and the end, with identical versions and a check of require_osd_release](figures/ch19/f01_upgrade.png){#fig-19-f01_upgrade}

cephadm performs the upgrade as a **rolling** upgrade: first the mgrs (so that the new cephadm module carries on with the work), then the MONs one by one while keeping quorum, then the OSDs, checking that stopping them does not make PGs inactive, and finally the other services.

```bash
ceph -s
ceph versions
ceph orch upgrade start --ceph-version 20.2.5          # or --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade status
ceph -W cephadm                                        # live follow-up
ceph orch upgrade pause | resume | stop
```

::: {.note}
The version in the example (Tentacle 20.2.5) is the latest Tentacle point release at the time of writing. Before upgrading, check the official release list at docs.ceph.com/en/latest/releases and read the upgrade notes for that version; some releases have prerequisites or manual steps.
:::

## Staggered upgrades {#sec-19-2-1}

cephadm can upgrade a subset of daemons (a staggered upgrade); for example only mgr and mon on a few hosts, or only specific RGW services with a limit on the count:

```bash
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5 --daemon-types mgr,mon --hosts mon1,mon2
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5 --services rgw.s3main --limit 2
```

::: {.deep}
In the Umbrella documentation, OSD upgrades can proceed **by CRUSH bucket**: with `--daemon-types osd --crush_bucket_type rack` (and optionally `--crush_bucket_name`), cephadm calls the MON command `ceph osd ok-to-upgrade` for each bucket, capped by `mgr/cephadm/max_parallel_osd_upgrades`, and upgrades that bucket's OSDs together; if the bucket parameters are not given, it falls back to the default `ok-to-stop` gate. The bucket types supported in the documentation are host, rack and chassis. This feature greatly shortens the upgrade time of large clusters, because a whole failure domain is upgraded at once instead of one OSD at a time.
:::

::: {.warn}
If a host is offline or in maintenance mode, the upgrade stops and waits. Before starting, check `ceph orch host ls`. Do not start an upgrade during heavy backfill or while there are inactive PGs.
:::

::: {.note}
Appendix I turns this section into a runbook for Reef → Squid → Tentacle: a pre-upgrade checklist, the release changes that can break something on the way, the new cephx key type of Squid 19.2.6 and Tentacle 20.2.4, package-based clusters, and an honest table of what can and cannot be rolled back.
:::

# Replacing a disk {#sec-19-3}

![Replacing a failed disk while keeping the OSD id, in two stages: removal with orch osd rm --replace, which drains the PGs and marks the OSD destroyed, and replacement, in which after the physical swap and, if needed, a zap, the OSD service specification picks up the new disk and the OSD is created with the same id and backfilled](figures/ch19/f02_replace.png){#fig-19-f02_replace}

```bash
ceph osd tree | grep -E "down|destroyed"
ceph orch osd rm 17 --replace          # the id is kept and the OSD stays in CRUSH
ceph orch osd rm status
# after replacing the disk
ceph orch device ls stor-b3 --refresh
ceph orch device zap stor-b3 /dev/sdk --force      # only if the disk was used before
ceph orch ps --daemon-type osd | grep osd.17
```

::: {.tip}
`--replace` keeps the OSD in the `destroyed` state rather than removing it entirely; so its CRUSH position and id are kept, and after the new OSD is created only that OSD's PGs are backfilled, not a general redistribution. Without `--replace`, removing the OSD and adding a new one moves the data twice.
:::

::: {.warn}
`ceph orch osd rm` asks for no confirmation and starts immediately; the documentation points this out explicitly. Double-check the id. To stop: `ceph orch osd rm stop <id>`.
:::

# Host maintenance and removal {#sec-19-4}

```bash
ceph orch host maintenance enter stor-b3        # stop all Ceph daemons on the host
# ... kernel update, hardware repair, reboot ...
ceph orch host maintenance exit stor-b3
# permanent removal
ceph orch host drain stor-b3                    # the _no_schedule and _no_conf_keyring labels; daemons leave
ceph orch osd rm status
ceph orch host rm stor-b3
```

::: {.note}
Before stopping anything, `maintenance enter` checks that stopping the host's daemons is safe (for example that the PGs stay active) and refuses if it is unsafe; according to the documentation, `--force` overrides warnings (not alerts), and `--force --yes-i-really-mean-it` bypasses all safety checks and can lead to loss of data access or quorum. In the cephadm code (`pybind/mgr/cephadm/module.py`), entering maintenance sets the noout flag on that host's CRUSH subtree with the `osd set-group` command, so that data is not redistributed needlessly, and exiting removes it.
:::

# Inside the code: pg_autoscaler {#sec-19-5}

## The problem {#sec-19-5-1}

The number of PGs in each pool has two opposing effects: few PGs mean an uneven data distribution and little parallelism; many PGs mean more memory and CPU use in the OSDs and heavier peering. The `pg_autoscaler` module in the mgr (`src/pybind/mgr/pg_autoscaler/module.py`) automates this balance. Its goal is for each OSD to host about `mon_target_pg_per_osd` PG replicas.

![The steps of the pg_autoscaler calculation: first each CRUSH root's PG budget from the number of OSDs times mon_target_pg_per_osd, then each pool's share from actual usage or a target ratio, converted to pg_target taking bias and size into account, and finally rounding to a power of 2 and changing only when the difference exceeds the threshold](figures/ch19/f03_autoscale.png){#fig-19-f03_autoscale}

::: {.warn}
**Version-dependent.** The default value of `mon_target_pg_per_osd` in `src/common/options/mgr.yaml.in` is **100** at tags v19.2.0 and v20.2.0 and **200** at v21.2.0 (Umbrella). That is, after upgrading to Umbrella the autoscaler may recommend more PGs for existing pools, and PG splitting (and data movement) may begin. Before upgrading, save `ceph osd pool autoscale-status` and compare after the upgrade; if necessary, set the previous value explicitly with `ceph config set global mon_target_pg_per_osd 100`.
:::

## The algorithm {#sec-19-5-2}

```text
pseudocode: pg_autoscaler (this book's rewrite)
  for root in crush_roots:
      budget[root] = osds_in(root) * mon_target_pg_per_osd
  for pool:
      root      = root_of(pool.crush_rule)
      ratio     = max(actual_used / root_capacity,
                      target_size_bytes / root_capacity,
                      normalized target_size_ratio)          # ratios are normalized
      pg_target = ratio * budget[root] * pool.bias / pool.size
      if pool.bulk:     start near full share
      else:             start small, grow with usage
      pg_final  = round_to_power_of_two(pg_target)            # Umbrella: optimal (knapsack) rounding
      pg_final  = clamp(pg_final, pg_num_min, pg_num_max)
      threshold = dynamic_threshold(pg_final) if scaling up else threshold   # default 3.0
      if pg_final > pg_num_target * threshold or pg_final < pg_num_target / threshold:
          if pool.mode == 'on':   set pg_num_target = pg_final
          elif pool.mode == 'warn': raise POOL_TOO_FEW_PGS / POOL_TOO_MANY_PGS
```

The **threshold** prevents oscillation: the autoscaler only changes pg_num when the ideal value is at least three times (default `threshold=3.0`) larger or smaller than the current value. The minimum allowed threshold is 1.0 (`ceph osd pool set threshold`).

In current code (and Umbrella), the threshold for **increases** is dynamic at a few common sizes:

```python
# from ceph/ceph, LGPL — src/pybind/mgr/pg_autoscaler/module.py (excerpt)
def get_dynamic_threshold(self, final_pg_num: int, default_threshold: float) -> float:
    if final_pg_num in (512, 1024):
        return 1.0
    elif final_pg_num == 2048:
        return 2.0
    return default_threshold
```

That is, reaching 512 or 1024 PGs does not require a threefold difference (any increase is enough), and for 2048 a twofold difference is enough. For decreases, the default threshold applies. In Umbrella, rounding pg_target to a power of 2 is also no longer done separately for each pool: the function `_find_optimal_pg_distribution` uses **dynamic-programming knapsack** to decide which pools to round up and which down so that the total rounding error is minimized and the root's PG budget is respected (this function does not exist at tag v20.2.0).

```bash
ceph osd pool autoscale-status
ceph osd pool set vm-fast target_size_ratio 0.4       # predict the future share
ceph osd pool set archive bulk true                   # a large pool: full share from the start
ceph osd pool set archive pg_num_min 256
ceph config get mgr mgr/pg_autoscaler/threshold      # the threshold (Tentacle+: ceph osd pool get threshold)
ceph osd pool set noautoscale                          # temporary global stop
ceph osd pool unset noautoscale
```

::: {.tip}
For pools you know will become large (the main RGW or RBD data), enable `bulk` from the start. Otherwise the autoscaler starts with few PGs and, as the pool fills, splits the PGs several times, each time with data movement.
:::

# Inside the code: balancer {#sec-19-6}

## Modes {#sec-19-6-1}

| Mode | Mechanism | Prerequisite |
|---|---|---|
| upmap (default) | Adding pg_upmap_items to move individual PGs | Luminous and later clients |
| crush-compat | Setting alternative weights in a compatible weight-set | Compatible with old clients |
| read and upmap-read | Balancing primaries (pg_upmap_primary) for read load | Reef and later clients |

![How the balancer works in upmap mode: the mgr module runs do_upmap every sleep_interval (default 60 seconds) if the cluster is quiet; OSDMap::calc_pg_upmaps compares each OSD's PG count with the weighted target value and, for OSDs deviating by more than max_deviation, creates pg_upmap_items entries that respect the CRUSH rule; the result is backfill only for the selected PGs](figures/ch19/f04_balancer.png){#fig-19-f04_balancer}

## The upmap algorithm {#sec-19-6-2}

`Module.do_upmap()` in `src/pybind/mgr/balancer/module.py`, with the options `upmap_max_optimizations` (default 10, the maximum number of changes per round) and `upmap_max_deviation` (default 5 PGs), hands the work to `OSDMap::calc_pg_upmaps()` in C++. Its logic:

```text
pseudocode: calc_pg_upmaps (this book's summary of OSDMap.cc)
  for osd: target[osd] = total_pgs * weight[osd] / total_weight      # weighted share
           deviation[osd] = pgs[osd] - target[osd]
  repeat up to max_optimizations:
      over  = OSDs with deviation >  max_deviation (fullest first)
      under = OSDs with deviation < -max_deviation
      if none: break
      for pg on over[0]:
          candidate = an OSD in under that keeps CRUSH rule valid
                      (same failure domain, no repeats in the up set)
          if found: add pg_upmap_items[pg] += (over[0] → candidate); update counts; break
      also: remove existing upmap items that no longer help
  return pending increment
```

::: {.deep}
`pg_upmap_items` does not bypass the CRUSH mapping; it is applied **on top of CRUSH's output**: CRUSH computes the up set and then the (from → to) pairs are substituted. If a later CRUSH change makes an upmap violate the rule (for example two copies on one host), the OSDMap ignores it when applying it and the MON cleans it up (`clean_pg_upmaps`). That is why upmap is safer than changing weights by hand.
:::

```bash
ceph balancer status
ceph balancer mode upmap
ceph balancer on
ceph config set mgr mgr/balancer/upmap_max_deviation 1     # a more precise distribution in a large cluster
ceph balancer eval
ceph osd df tree | sort -nk17 | tail                      # the VAR and PGS columns
```

::: {.note}
The balancer only works when the percentage of misplaced PGs is below `target_max_misplaced_ratio` (default 0.05); so in the middle of heavy backfill it starts no new work. The read balancer modes need Reef and later clients (`ceph osd set-require-min-compat-client reef`).
:::

# Three maintenance algorithms in numbers {#sec-19-7}

The previous sections explained the autoscaler and the balancer at the conceptual level. This section opens both down to the level of loops and numbers. Because the autoscaler's rounding algorithm changed in Umbrella, we give both versions separately.

## Rounding to a power of two and the 3x threshold {#sec-19-7-1}

::: {.algo #alg-19-1 title="Three-pass pg_autoscaler (up to v20.2.0)" src="src/pybind/mgr/pg_autoscaler/module.py :: PgAutoscaler._calc_final_pg_target, nearest_power_of_two (tag v20.2.0)" complexity="O(P) for P pools per CRUSH root; rounding O(1) with bit shifts"}
:::

```text
pseudocode
budget[root] = Σ_osd mon_target_pg_per_osd / (number of roots of that OSD) ; pg_left = budget
pass 1 (non-bulk pools): used = capacity_ratio × pg_left ; pg_left −= used ; target = used / size × bias
pass 2 (bulk with ratio > even = 1/(pools − used_pools)): ratio = max(used, even) ; same calculation
pass 3 (remaining bulk): ratio = 1/(remaining) ; target = ratio × pg_left / size × bias
final = max(pg_num_min=32, nearest_power_of_two(target)) ; final = min(final, pg_num_max)
adjust = (final > current × 3) or (final < current / 3)       # default threshold 3.0
```

**Numerical example.** Ten OSDs in one root with `mon_target_pg_per_osd = 100` (the v20.2.0 default) give a budget of 1000 PG replicas. A non-bulk pool named `rbd` with size 3 and capacity_ratio = 0.3 has used = 300 and target = 300/3 = 100. The function nearest_power_of_two(100) builds the bounds 64 and 128 (by ORing shifts: 99 → 127 → 128). Because 128 − 100 = 28 < 100 − 64 = 36, the result is 128. If the current pg_num is 32, 128 > 96 and the change is applied. If the current pg_num were 64, 128 < 192, and the autoscaler would only warn and change nothing. This hysteresis prevents back-to-back splits and merges. The rounding decision point is 1.5 times each power of two.

![Left: the step function nearest_power_of_two: each pool's target is rounded to the nearest power of two, and the decision boundary (orange dotted line) is 1.5 times the lower power. The red point is the text's example. Right: the threshold rule with threshold = 3 and a current pg_num of 32: only the green values, that is above 96 or below 10.7, cause a real change](figures/ch19/f05_pow2.png){#fig-19-f05_pow2}

## Global rounding with knapsack (Umbrella) {#sec-19-7-2}

::: {.algo #alg-19-2 title="Optimal PG rounding with dynamic programming" src="src/pybind/mgr/pg_autoscaler/module.py :: PgAutoscaler._find_optimal_pg_distribution, _calculate_final_pool_pg_target, get_dynamic_threshold, PoolGroup.update (tag v21.2.0)" complexity="per the code's docstring O(n·log2(budget)); state space = possible sums of extra PGs"}
:::

```text
pseudocode
for each pool group (same target, same size, same bias): down = pow2_down(t)×size , up = pow2_up(t)×size
    cost_down = |down − t×size| , cost_up = |up − t×size| , extra = up − down
base = Σ down ; budget = pg_left − base
parent[0] = {0: (Σ cost_down)}
for group i: for each sum s in parent[i]:
    s' = s + extra_i ; c' = c − cost_down_i + cost_up_i
    if s' ≤ budget and (s' is new or c' is lower): parent[i+1][s'] = (c', s)
opt = lowest cost; on a tie, the most PGs ; then backtrack to find the "up" groups
dynamic threshold for increases: final ∈ {512, 1024} ⇒ 1.0 , final = 2048 ⇒ 2.0 , otherwise threshold
```

**Numerical example.** pg_left = 1000. Pool A has a target of 100 with size 3, and pool B a target of 180 with size 3.

- **A:** down = 64×3 = 192, up = 128×3 = 384, costs 108 and 84, extra = 192.
- **B:** down = 128×3 = 384, up = 256×3 = 768, costs 156 and 228, extra = 384.

base = 576 and budget = 424. There are four options:

- Both down: cost 264.
- Only B up: 336.
- Only A up: **240**.
- Both up: 576 extra PGs, more than the budget.

So A = 128 and B = 128 are chosen. In this example the result is the same as local rounding. The difference appears when local rounding would round both up and break the root's budget. The three-pass version could not see that. The dynamic threshold also allows a change from 256 to 512 without the 3x condition.

![The four possible choices for rounding the two pools in the text's example. The height of each bar is the total distance of the rounded values from the target. The grey option exceeds the budget of 424 extra PG replicas and is excluded. The green option has the lowest cost and is chosen. Instead of trying all 2ⁿ combinations, dynamic programming keeps only the possible sums of extra PGs](figures/ch19/f06_knap.png){#fig-19-f06_knap}

::: {.warn}
**Version-dependent.** This algorithm does not exist at tag v20.2.0 and is present at v21.2.0. In the same version the default `mon_target_pg_per_osd` also went from 100 to 200, so after the upgrade both the budget and the rounding method change. In the main branch, the `pg_num_min` floor is read from `osd_pool_default_pg_num` instead of the constant PG_NUM_MIN = 32. Check your own version before relying on it.
:::

## Deviation and the balance score in upmap {#sec-19-7-3}

::: {.algo #alg-19-3 title="Weighted deviation and bal_score in calc_pg_upmaps" src="src/osd/OSDMap.cc :: OSDMap::calc_pg_upmaps, calc_deviations, fill_overfull_underfull" complexity="each iteration O(OSDs + PGs on the fullest OSD × CRUSH cost); at most upmap_max_optimizations = 10 changes per round"}
:::

```text
pseudocode
pgs_per_weight = total_pg_replicas / Σ weight
for osd: target = weight × pgs_per_weight ; dev = pgs − target
         bal_score += (dev/target)^2 × weight ; max_dev = max(|dev|)
if max_dev ≤ max_deviation (5): return 0
loop (max times): overfull = {dev > 5} , underfull = {dev < −5}
    if both empty: break ; if overfull is empty: use more_overfull (0 < dev ≤ 5)
    from the fullest OSD: find a PG whose move to underfull does not break the CRUSH rule ⇒ pg_upmap_items
    recompute the deviations ; accept only if bal_score improved
```

**Numerical example.** We have six OSDs with weights 1, 1, 1, 1, 2 and 2 (total 8) and 384 PG replicas (128 PGs × size 3), so pgs_per_weight = 48. The weight-1 OSDs have a target of 48 and the weight-2 ones 96. The current counts are 55, 41, 50, 46, 100 and 92, so the deviations are +7, −7, +2, −2, +4 and −4.

- **bal_score** = $2 \times (7/48)^2 + 2 \times (2/48)^2 + 4 \times (4/96)^2 = 0.0530$.
- **First move**, one PG from osd.0 to osd.1: deviation ±6 and score 0.0417.
- **Second move:** ±5 and score 0.0321.

Now no OSD deviates by more than 5, and the loop stops. In practice, the choice of PG is constrained by the CRUSH rule. If osd.0 and osd.1 are on the same host and the rule wants one copy per host, a direct move is impossible and the algorithm turns to another underloaded OSD. The code deliberately accumulates bal_score in a double, because in a float the change from one PG in large clusters fell below the number's precision and the balancer stalled.

![Each OSD's PG count deviation from its weighted target in the text's example, before upmap and after each upmap. The dashed lines are the upmap_max_deviation = 5 boundary. Each upmap takes one unit from the fullest OSD and adds it to the least loaded. The bal_score, the weighted sum of squared relative deviations, decreases with each move. The weight-2 OSDs with deviation ±4 remain untouched, because they are within the boundary](figures/ch19/f07_dev.png){#fig-19-f07_dev}

::: {.tip}
`ceph balancer eval` reports this same score for the whole cluster or a pool. `ceph osd df tree` shows the PGS column, with which you can compute the deviation by hand. For a more uniform distribution than the default, try `ceph config set mgr mgr/balancer/upmap_max_deviation 1`, but this causes more data movement.
:::

# The balancer and splits on a real mapping {#sec-19-8}

The two experiments in this section were run on the same 120-OSD map (10 hosts × 12, straw2, `chooseleaf host`, size = 3) that we built in chapter 1. The tools were crushtool and osdmaptool from Ceph 18.2.7.

## The upmap balancer on 1024 and 8192 PGs {#sec-19-8-1}

::: {.algo #alg-19-4 title="The balancer's path in upmap mode" src="src/osd/OSDMap.cc :: calc_pg_upmaps; src/pybind/mgr/balancer/module.py; the same code in osdmaptool --upmap" complexity="each round O(pg_num × size) for counting and selection"}
:::

```text
pseudocode
for each OSD: target = pg_num × size × (OSD weight / total pool weight)
deviation(o) = PGs on o − target(o)
while max |deviation| > upmap_max_deviation and the number of changes < upmap_max:
    o_over = the largest positive deviation ; o_under = the largest negative deviation, with the same allowed failure domain
    take a PG from o_over that does not violate the CRUSH rule and move it to o_under
    ← a pg-upmap-items entry: pg  o_over  o_under
```

**Measurement.** The command `osdmaptool om --mark-up-in --upmap out.txt --upmap-deviation 1 --upmap-max 10000 --upmap-pool rbd --save` was run on two osdmaps.

With 8192 PGs, CRUSH alone gives each OSD between 172 and 234 PGs (a standard deviation of 13.24 against a mean of 204.8). After 618 `pg-upmap-items` entries (630 OSD pairs, that is 2.6% of the replicas), the range narrowed to 204 to 206 and the standard deviation to 0.54.

With 1024 PGs, the range went from 13 to 42 to 25 to 26. This needed 226 entries and 246 pairs, which is 8.0% of the replicas. That is, the share of movement needed to even things out is larger at a low pg_num.

Because CRUSH is more uniform at a high pg_num, the balancer also has less work. But in both cases removing the deviation moves a few percent of the data, and the balancer spreads it out in instalments under the same 5% cap (target_max_misplaced_ratio).

![Distribution of PG counts over 120 OSDs before upmap (orange, CRUSH only) and after upmap (blue), for 1024 and 8192 PGs, with osdmaptool --upmap and an allowed deviation of 1. Each chart's title shows the number of pg-upmap-items entries and the share of replicas moved](figures/ch19/f08_upmap.png){#fig-19-f08_upmap}

## Doubling pg_num: half the data moves {#sec-19-8-2}

::: {.algo #alg-19-5 title="The pg_num and pgp_num controller in the mgr" src="src/mgr/DaemonServer.cc :: adjust_pgs; the options target_max_misplaced_ratio = 0.05 (global.yaml.in) and mgr_max_pg_num_change = 128 (mgr.yaml.in)" complexity="O(number of pools) per round"}
:::

```text
pseudocode
if all of the pool's PGs are active and pg_num − pgp_num < 128:
    pg_num += min(128 − (pg_num − pgp_num), pg_num_target − pg_num)      # split, still no movement
target = min(pg_num_pending, pgp_num_target)
if inactive or degraded or unknown > 0  or  misplaced > 0.05: wait
if the pool is nearly empty (objects ≤ pgp_num_target): pgp_num = target in one go
otherwise: room = min(0.05 − misplaced, 0.025) ; estmax = max(⌊pg_num × room⌋, 1)
       pgp_num = clamp(target, pgp_num − estmax, pgp_num + estmax)       # the real movement is here
```

**Measurement.** For each doubling, the mapping of child PG `ps + n` was compared with the mapping of parent PG `ps` in the previous osdmap (pgp_num equal to pg_num). In every step from 256 to 512 up to 32768 to 65536, about 92% of the children landed on three new OSDs and the rest almost all on two new OSDs. In total, 48.6 to 49.2 percent of all data moved. No parent PG changed its location.

This number agrees with a simple estimate. Half the data goes to the children. The probability that a child replica happens to land on one of the parent's OSDs is about 3/120. So 0.5 × (1 − 3/120) ≈ 48.75%.

Until pgp_num is raised, the child is mapped with `ceph_stable_mod(ps, pgp_num, mask)` to the same place as the parent, and the split is metadata only. The real movement happens when pgp_num goes up.

The controller model shows that the mgr spreads this movement in steps of about 2.5% of pg_num. A simulation of 1024 to 2048, assuming backfill finishes before each round, gives 27 steps, the first of which is 1024 to 1052. So increasing pg_num on a full pool is equivalent to moving half of the pool's data, and depending on the volume takes from a few hours to a few days.

![Left: after doubling pg_num and pgp_num, what percentage of child PGs land on 0, 1, 2 or 3 new OSDs, and the share of all data moved (about 48.7%), measured with osdmaptool on 120 OSDs. Right: a model of the adjust_pgs controller in the mgr for 1024 to 2048, with a cap of 128 on the gap between pg_num and pgp_num and a pgp step of pg_num × min(0.05 − misplaced, 0.025), assuming backfill finishes before each round](figures/ch19/f09_split.png){#fig-19-f09_split}

# Configuration management {#sec-19-9}

Since Mimic, the central configuration is kept in the MON database, and `ceph.conf` on the hosts is only needed to find the MONs. This means configuration changes are traceable, reversible and identical across all daemons.

```bash
ceph config dump | head
ceph config get osd.12 osd_memory_target
ceph config show osd.12 | grep -E "osd_memory_target|osd_max_backfills"   # the effective value and its source
ceph config set osd/class:hdd osd_memory_target 6G                       # a mask by device class
ceph config set osd.12 debug_osd 10/10                                   # temporary, for troubleshooting
ceph config rm osd.12 debug_osd
ceph config log 20                                                        # change history
ceph config reset 1234                                                    # revert to a specific version
ceph config help osd_op_queue
```

::: {.tip}
`ceph config log` and `ceph config reset <num>` are the tools for quickly reverting a wrong change. Before any broad change, note the number of the last log entry.
:::

::: {.warn}
Settings applied with `ceph tell osd.* injectargs` or `ceph daemon ... config set` are **temporary** and are lost on restart. For persistence, use `ceph config set`; for a temporary change during an incident, use tell deliberately and record it in the incident log.
:::

# Maintenance flags {#sec-19-10}

| Flag | Effect | Use |
|---|---|---|
| noout | Down OSDs are not marked out | Short maintenance (preferably set-group for one host) |
| norebalance | Movement for balancing stops | Consecutive CRUSH changes |
| nobackfill / norecover | Backfill or recovery stops | Reducing load at peak time (temporary and dangerous) |
| noscrub / nodeep-scrub | No new scrubs start | Upgrades or heavy load |
| pause | All reads and writes stop | Only specific emergencies |

```bash
ceph osd set-group noout stor-b3          # only one host's OSDs
ceph osd unset-group noout stor-b3
ceph osd set norebalance && ceph osd unset norebalance
```

# Periodic tasks {#sec-19-11}

| Interval | Task |
|---|---|
| Daily | `ceph -s`, new warnings, `ceph crash ls-new`, fullness (`ceph df`) |
| Weekly | `ceph osd df tree` (VAR and PGS), overdue deep scrubs, mirroring and multisite status |
| Monthly | Check versions and point releases, review disk SMART data (`ceph device ls`), a restore test |
| Quarterly | Failover drill, capacity review and growth forecast, review of caps and keys |

::: {.note}
The devicehealth module in the mgr collects the disks' SMART data: `ceph device ls`, `ceph device get-health-metrics <devid>` and failure prediction with `ceph device predict-life-expectancy <devid>`; prediction is off by default (`device_failure_prediction_mode=none`), and for local mode you must enable the `diskprediction_local` module. With `mgr/devicehealth/mark_out_threshold` you can automatically mark out the OSD of a failing disk before it fails.
:::

::: {.summary title="SRE notes for this chapter"}

- Start an upgrade only on a healthy cluster and after reading the release notes.
- After upgrading to Umbrella, manage the change in the default mon_target_pg_per_osd (100 to 200).
- Always use `--replace` for disk replacement.
- Set noout with set-group for one host, and temporarily.
- Make large pools bulk from the start.
- Make all configuration changes with ceph config, reversibly.

:::

# Supplementary and up to date {#sec-19-12}

- OSD upgrades by CRUSH bucket and the `ceph osd ok-to-upgrade` command appear in the Umbrella documentation.
- In Umbrella, the default `mon_target_pg_per_osd` has reached 200 and PG rounding is done with global optimization.
- `ceph-deploy` has been archived and all procedures are done with cephadm; ceph-ansible is still maintained "for now", and migrating to cephadm is recommended (chapter 11).
- The read balancer has been available since Reef for balancing primaries.

# Hands-on exercise {#sec-19-13}

1. Perform a point upgrade in a test cluster and record the daemon upgrade order from `ceph -W cephadm`.
2. Remove and recreate an OSD with `--replace`; compare the amount of backfilled data with a removal without `--replace`.
3. Put a host into maintenance mode and look at the group noout flag in `ceph osd dump`.
4. Compare the output of `ceph osd pool autoscale-status` before and after setting `bulk` and `target_size_ratio`.
5. Lower `upmap_max_deviation` to 1 and follow the change in the PGS column of `ceph osd df`.
6. In `pg_autoscaler/module.py`, find where `pg_num_min` and `pg_num_max` are applied.

# Review questions {#sec-19-14}

1. What is the daemon upgrade order in cephadm, and why is the mgr first?
2. What is the advantage of upgrading OSDs by CRUSH bucket?
3. Why does `--replace` reduce data movement?
4. What does maintenance enter do with the noout flag?
5. What is the basic pg_target formula in the autoscaler?
6. What problem does the autoscaler threshold solve, and when is the dynamic threshold applied?
7. What are the consequences of the change in the default mon_target_pg_per_osd in Umbrella?
8. How does the upmap balancer choose a PG to move?
9. Why is upmap safer than changing weights by hand?
10. What is the difference between ceph config set and injectargs?

# Sources for this chapter {#sec-19-15}

- cephadm upgrade: https://docs.ceph.com/en/latest/cephadm/upgrade/
- cephadm upgrade (Umbrella): https://docs.ceph.com/en/umbrella/cephadm/upgrade/
- cephadm host management: https://docs.ceph.com/en/latest/cephadm/host-management/
- cephadm OSD service: https://docs.ceph.com/en/latest/cephadm/services/osd/
- Placement groups and autoscaling: https://docs.ceph.com/en/latest/rados/operations/placement-groups/
- Balancer: https://docs.ceph.com/en/latest/rados/operations/balancer/
- Configuring Ceph (central config): https://docs.ceph.com/en/latest/rados/configuration/ceph-conf/
- Source: src/mon/ConfigMonitor.cc (config log / reset): https://github.com/ceph/ceph/blob/main/src/mon/ConfigMonitor.cc
- Device management: https://docs.ceph.com/en/latest/rados/operations/devices/
- Ceph releases: https://docs.ceph.com/en/latest/releases/
- Source: src/pybind/mgr/pg_autoscaler/module.py: https://github.com/ceph/ceph/blob/main/src/pybind/mgr/pg_autoscaler/module.py
- Source: src/pybind/mgr/balancer/module.py: https://github.com/ceph/ceph/blob/main/src/pybind/mgr/balancer/module.py
- Source: src/osd/OSDMap.cc (calc_pg_upmaps): https://github.com/ceph/ceph/blob/main/src/osd/OSDMap.cc
