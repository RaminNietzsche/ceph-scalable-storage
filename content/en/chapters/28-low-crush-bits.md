---
chapter: 28
id: ch28
title: 'Lower Layers (6): CRUSH at the Bit Level, from rjenkins to upmap'
part: lower
lang: en
---

# Introduction: how does CRUSH "compute"? {#sec-28-1}

In chapters 1 and 8 we saw CRUSH as an algorithm that determines the location of each PG without a central table. This chapter goes down to the bit level: the rjenkins hashes that make every decision deterministic, the straw2 algorithm with its fixed-point logarithm table, the step-by-step execution of `crush_do_rule`, the retries on collisions, and finally how choose_args, weight-set and upmap correct CRUSH's raw result. We follow a complete example from the object name to the choice of host, with numbers computed by compiling Ceph's own C code (`src/crush/hash.c` and `mapper.c`, LGPL) into a small test program.

::: {.summary}

- The object name is hashed with `ceph_str_hash_rjenkins`. `ceph_stable_mod` maps it to a PG, and with `HASHPSPOOL` the CRUSH input is `crush_hash32_2(ps, pool)`.
- straw2 computes a "draw" for each item: draw = ln(u) / w, where u is a sixteen-bit hash and ln comes from a fixed-point table. The largest draw wins. The probability of each item winning is exactly proportional to its weight.
- A collision (a repeated choice) is resolved by increasing r (r = rep + ftotal), up to `choose_total_tries=50`.
- `reweight` works through a probabilistic `is_out`. A weight-set in choose_args is a substitute weight for CRUSH, and upmap explicitly replaces the result after CRUSH.

:::

# From the object name to x {#sec-28-2}

![The complete mapping pipeline. The object name is hashed with rjenkins to 0xD1895615. With pg_num=128, ceph_stable_mod gives 0x15, that is PG 3.15. With the HASHPSPOOL flag, the pool number is also mixed into the hash so that the PGs of different pools do not overlap, and x = 0x36D15C32 is the CRUSH input. crush_do_rule returns the raw list of OSDs, then non-existent OSDs are removed and upmaps applied, and finally pg_temp determines the acting set](figures/ch28/f01_pipe.png){#fig-28-f01_pipe}

`ceph_stable_mod(x, b, bmask)` is defined in `include/rados.h`: if `x & bmask` is less than b it returns that, otherwise `x & (bmask >> 1)`. This function is "stable" because when pg_num grows from 128 to 192, only the PGs that have the new bit move (split) and the rest keep their number. This is the mathematical reason a split moves only part of the data.

| Step | Value in the example | Function |
|---|---|---|
| hash of the name | 0xD1895615 | `ceph_str_hash_rjenkins` (`common/ceph_hash.cc`) |
| ps | 0x15 (= 0xD1895615 & 127) | `ceph_stable_mod(h, 128, 127)` |
| PG | 3.15 | `pg_t(ps, pool)` |
| x (pps) | 0x36D15C32 | `crush_hash32_2(RJENKINS1, ps, 3)` in `pg_pool_t::raw_pg_to_pps` |

## The rjenkins hash {#sec-28-2-1}

`crush_hashmix(a, b, c)` is nine rounds of subtraction, XOR and shift on three 32-bit words, taken from Bob Jenkins's mixing function. The three-input version `crush_hash32_rjenkins1_3(a, b, c)` starts with `hash = 1315423911 ^ a ^ b ^ c` (the `crush_hash_seed` constant) and runs mix five times with the constants `x = 231232` and `y = 1232`. Its important property is **complete determinism on all architectures**: it uses only unsigned 32-bit integer operations, no floating point. That is why the Linux kernel client (which has the same file in `net/ceph/crush/`) and librados get exactly the same result.

::: {.warn}
Any change to these functions, to the logarithm table or to the tunables (such as `chooseleaf_stable`) changes the mapping of almost every PG. That is why the tunables have named profiles (`ceph osd crush tunables optimal`), and changing them on a full cluster causes huge data movement.
:::

# straw2: an exponential draw {#sec-28-3}

Suppose each item i with weight w_i draws an exponential random variable with rate w_i. The probability that item i has the **smallest** value is exactly w_i / Σw. straw2 implements exactly this without floating-point numbers:

```text
straw2 (the logic of mapper.c, LGPL; a simplified rendering by this book)
  for each item i in bucket:
      u    = crush_hash32_3(bucket.hash, x, id_i, r) & 0xFFFF       # 16 bits
      ln   = crush_ln(u) − 2^48          # ≈ 2^44 · log2((u+1)/2^16) ≤ 0
      draw = ln / weight_i                # weight in 16.16 fixed point
  return item with max draw              # the smallest −ln/w = exponential with rate w
```

`crush_ln(x)` computes 2^44 · log2(x+1) with two tables, `__RH_LH_tbl` and `__LL_tbl` (in `crush_ln_table.h`), using only integer operations. It first normalizes the input (the exponent), then looks up the top 8 bits of the mantissa in the first table (an approximation of 1/x and log2) and the next 8 bits in the second table (the correction). The results in our test program: `crush_ln(0) = 0`, `crush_ln(0x7FFF) = 0xF00000000000` (that is 15 · 2^44) and `crush_ln(0xFFFF) = 0xFFFFF0000000` (about 16 · 2^44 = 2^48).

![A real straw2 run for x=0x36D15C32 in a root bucket with three hosts: -3 and -4 each with weight 10 and -5 with weight 20. At r=0, host -4 wins with the largest draw (−8.9M). At r=1, host -5 wins. For the third replica, r=2 to r=5 land on repeated hosts and ftotal is increased each time, until r=6 reaches host -3. The retry limit is choose_total_tries=50](figures/ch28/f02_straw2.png){#fig-28-f02_straw2}

| r | draw(-3) | draw(-4) | draw(-5) | Winner |
|---|---|---|---|---|
| 0 | −77,259,388 | **−8,880,361** | −31,248,985 | -4 |
| 1 | −7,177,981 | −14,582,287 | **−3,918,635** | -5 |
| 2 | −11,854,384 | −59,760,693 | **−2,413,629** | -5 (repeat) |
| 3 | −63,878,138 | −125,349,258 | **−14,701,300** | -5 (repeat) |

**Checking the distribution:** in the same program, with three items of weights 1, 1 and 2 and 300,000 values of x, the winner counts were 75,274, 74,753 and 149,973, that is 25%, 25% and 50%, just as the theory predicts.

::: {.deep}
**Why straw2 and not straw?** In the old straw, the "straw length" of each item was computed from the weights relative to, and dependent on, the other items. So changing the weight of one item also changed the draws of the other items, and data moved between items whose weights had not changed. In straw2, the draw of each item depends only on (x, id, r, its own weight). If item A's weight increases, only some x values **move** from the other items to A, and no data moves between B and C. This is the minimal-movement property (optimal reorganization).
:::

# crush_do_rule step by step {#sec-28-4}

![Executing replicated_rule. TAKE puts the root into the working vector w. CHOOSELEAF_FIRSTN with numrep=0 (that is, equal to size) chooses a host for each replica and then, recursively, an OSD inside it. EMIT appends the result to the output. In each choice r = rep + ftotal. If the result is a repeat or the OSD is rejected by is_out, ftotal is increased and the attempt is repeated. For a reweight between 0 and 1, is_out makes a probabilistic decision with another hash of (x, osd)](figures/ch28/f03_rule.png){#fig-28-f03_rule}

A rule is an array of steps (`crush_rule_step` with op, arg1 and arg2). `crush_do_rule` has a working vector `w` and an output vector `o`:

| op | Value | Action |
|---|---|---|
| `TAKE` | 1 | w = [arg1] (for example the root id or a device class in the shadow tree) |
| `CHOOSE_FIRSTN` | 2 | from each bucket in w, choose arg1 items of type arg2 (for replicated) |
| `CHOOSE_INDEP` | 3 | the same, with fixed positions (for EC; a lost shard leaves an empty slot) |
| `EMIT` | 4 | o += w; w is emptied |
| `CHOOSELEAF_FIRSTN` / `_INDEP` | 6 / 7 | choose a bucket of type arg2 and then one leaf (OSD) inside it |
| `SET_CHOOSE_TRIES` and similar | 8–13 | override tunables for this rule |
| `SET_MSR_DESCENTS` / `SET_MSR_COLLISION_TRIES` / `CHOOSE_MSR` | 14 / 15 / 16 | MSR rules (several OSDs per failure domain) — in Squid and later, not in Reef |

**numrep:** if arg1 ≤ 0, numrep = result_max + arg1. So `0` means "as many as size" and `-1` means "size minus one". This is used for rules such as "one in the first DC, the rest in the second DC".

## firstn versus indep {#sec-28-4-1}

In **firstn**, order does not matter. If the second replica becomes unavailable, the third replica takes its place and everything shifts forward by one. For replication this is optimal, because only one new copy is needed. In **indep**, position r is always shard r. If the OSD of one shard is lost, only that position is chosen again with a new r (r + numrep · ftotal), and the other shards do not move. For EC this is vital, because shards are not interchangeable.

| tunable (jewel/optimal profile) | Value | Effect |
|---|---|---|
| `choose_local_tries` | 0 | old local retry off |
| `choose_local_fallback_tries` | 0 | off |
| `choose_total_tries` | 50 | the retry limit; in our example there were 4 failed attempts |
| `chooseleaf_descend_once` | 1 | in chooseleaf, descend once and, if it fails, retry from the top |
| `chooseleaf_vary_r` | 1 | r in the leaf sub-choice depends on the parent's r, so that retries give different results |
| `chooseleaf_stable` | 1 | when one OSD goes out, the other replicas do not move |
| `straw_calc_version` | 1 | fix to the old straw calculation |

::: {.note}
Collisions become frequent when the number of failure domains is close to size. In our example, with three hosts and size=3, the third replica was found after 4 attempts. If one of the hosts has a very small weight, even 50 attempts may not be enough, and the PG stays `undersized` with fewer than size members. `crushtool --test --show-bad-mappings` tests exactly this.
:::

```bash
ceph osd getcrushmap -o cm.bin && crushtool -d cm.bin -o cm.txt
crushtool -i cm.bin --test --rule 0 --num-rep 3 --min-x 0 --max-x 1023 --show-utilization
crushtool -i cm.bin --test --rule 0 --num-rep 3 --x 0x36d15c32 --show-mappings
crushtool -i cm.bin --test --show-bad-mappings --rule 0 --num-rep 3
ceph osd map rbd rbd_data.10ab2c3d4e5f.0000000000000000     # pg and up/acting
```

# choose_args, weight-set and upmap {#sec-28-5}

![The three tools for correcting the distribution and the order in which they apply. reweight works through a probabilistic is_out and causes widespread movement. choose_args (weight-set) provides substitute weights for straw2 that can even differ per position (first replica, second, and so on), and the balancer uses it in crush-compat mode. upmap explicitly replaces the result after CRUSH. In the OSDMap the order of application is: crush_do_rule with choose_args, removal of non-existent OSDs, pg_upmap, pg_upmap_items and pg_upmap_primary](figures/ch28/f04_adjust.png){#fig-28-f04_adjust}

**choose_args:** in `bucket_straw2_choose`, the function `get_choose_arg_weights` uses `weight_set[position]` instead of `item_weights` if a `weight_set` exists. `position` is the number of the replica being chosen. This makes it possible to fix a subtle problem: in straw2 with unequal weights, the second and third replicas deviate slightly from the weight ratio, because the earlier choices have been excluded. The weight-set gives slightly different weights for each position. There are also substitute `ids`, so that the hash can be changed without changing the bucket's real id.

**upmap:** `OSDMap::_apply_upmap` first checks `pg_upmap` (replacing the whole list), then `pg_upmap_items` (from→to pairs) and finally `pg_upmap_primaries` (only setting the primary, for the read balancer). Upmaps that violate the CRUSH rule (for example two replicas on one host) are checked and removed by the mon (`clean_pg_upmaps`).

| Balancer mode | Mechanism | Release |
|---|---|---|
| `crush-compat` | weight-set in choose_args | since Luminous; for old clients |
| `upmap` | `pg_upmap_items` | the default; requires `require-min-compat-client luminous` |
| `read` | `pg_upmap_primaries` (primary only) | Reef and later (according to the documentation) |
| `upmap-read` | both | Reef and later |

```bash
ceph osd pg-upmap-items 3.15 4 11        # replace osd.4 with osd.11 for PG 3.15
ceph osd rm-pg-upmap-items 3.15
ceph osd crush weight-set ls
ceph balancer status && ceph balancer eval
ceph osd dump | grep -E '^pg_upmap(_items|_primary)?' | head
```

# is_out and reweight: a numerical example {#sec-28-6}

`is_out` in `mapper.c` interprets an OSD's reweight value (a 16.16 number between 0 and 0x10000) like this: if the weight is full, the OSD is in. If it is zero, it is out. Otherwise `crush_hash32_2(x, osd) & 0xFFFF` is compared with the weight, and if it is smaller, the OSD is in for this x. So a reweight of 0.5 means roughly half of the PGs CRUSH had given to this OSD are rejected and go elsewhere on retry.

| Example | Value |
|---|---|
| x | 0x36D15C32 (the same PG 3.15) |
| osd | 7 |
| `crush_hash32_2(x, 7) & 0xFFFF` | 0xC425 |
| reweight 0.5 (0x8000) | 0xC425 ≥ 0x8000 → **out** for this PG |
| reweight 0.9 (0xE666) | 0xC425 < 0xE666 → **in** |
| fraction in with reweight 0.5 over 100,000 x | 50,069 (≈ 50%) |

::: {.tip}
The difference between `ceph osd reweight` (this probabilistic is_out, applied after the straw2 choice) and `ceph osd crush reweight` (the straw2 weight in the bucket itself) matters. Reweighting through is_out causes more retries and a subtle skew of the distribution, which is why the upmap-based balancer is a better alternative. Values close to 1 (for example 0.95) cause little movement, but small values (for example 0.3) can push the retries close to the limit of 50.
:::

# Device classes and the shadow tree {#sec-28-7}

When OSDs have classes (`hdd`, `ssd`, `nvme`), CrushWrapper builds for each bucket and each class a "shadow" with a new negative id and a name such as `default~ssd` that contains only the OSDs of that class. A rule such as `step take default class ssd` is in fact a `TAKE` on the shadow id. Because the shadows have their own ids, the straw2 hash (which includes the item id) for the shadows is independent of the main tree. Adding an hdd OSD does not move any PG in the ssd pools.

```bash
ceph osd crush tree --show-shadow
ceph osd crush rule create-replicated fast default host ssd
ceph osd crush class ls-osd ssd
```

::: {.deep}
**Why do the shadow ids stay stable?** The mapping from class to shadow id is stored in the CRUSH map itself (`class_bucket`). So rebuilding the shadows after adding an OSD or changing a weight keeps the same ids. If these ids changed, the x of every PG in the pools that depend on that class would get a different hash and all the data would move. The `crushtool --reclassify` tool, for converting old maps (with separate roots for ssd) to classes, sets exactly these ids so that the mapping does not change.
:::

# Three other bucket types: uniform, list and tree {#sec-28-8}

straw2 is the default today, but CRUSH had five bucket algorithms from the start: uniform, list, tree, straw and straw2. Each is a trade-off between selection speed and the amount of data movement on change. Old mappings and hand-written maps may still contain them. To understand why straw2 won, we ran all three with the real rjenkins hash. All the numbers in this section were computed with a small C program that takes `hash.c` and `crush_ln` from the Ceph code.

## uniform: a pseudo-random permutation {#sec-28-8-1}

::: {.algo #alg-28-1 title="Choosing in a uniform bucket with an incremental permutation" src="src/crush/mapper.c :: bucket_perm_choose, bucket_uniform_choose" complexity="r=0 in O(1); r=k in O(k); shared work in crush_work_bucket.perm"}
:::

```text
pseudocode (taken from bucket_perm_choose)
pr = r mod size
if x changed:
    if pr == 0: return items[hash3(x, bucket_id, 0) mod size]        # common shortcut
    perm = [0..size-1]; perm_n = 0
while perm_n ≤ pr:                         # incremental Fisher–Yates with a hash instead of random
    p = perm_n
    if p < size-1:
        i = hash3(x, bucket_id, p) mod (size − p)
        swap(perm[p], perm[p+i])
    perm_n += 1
return items[perm[pr]]
```

![A real run of bucket_perm_choose for bucket -5 with four items and x=0x1234ABCD. Three Fisher–Yates steps build the permutation \[3 2 0 1\]. So r=0 reaches item 13, r=1 reaches 12, r=2 reaches 10 and r=3 reaches 11. The permutation is kept in crush_work so that later attempts with the same x are not recomputed](figures/ch28/f05_uniform.png){#fig-28-f05_uniform}

uniform only works correctly when all items have equal weight, because the weight is not part of the calculation at all. The bigger problem is that changing `size` changes the modulus of every hash. Our simulation shows that adding a fifth item to four items moves **80%** of the inputs, while the minimum needed is 20%. This bucket was designed for hardware that is always bought and replaced all at once and in identical sizes.

## list: walking from the end {#sec-28-8-2}

::: {.algo #alg-28-2 title="Choosing in a list bucket" src="src/crush/mapper.c :: bucket_list_choose" complexity="O(n) in the worst case; appending at the end is optimal"}
:::

```text
for i = size-1 down to 0:
    h = hash4(x, items[i], r, bucket_id) & 0xFFFF                   # a 16-bit number
    if (h × sum_weights[i]) >> 16 < item_weights[i]: return items[i]
return items[0]
# sum_weights[i] = Σ_{j ≤ i} item_weights[j]  ⇒ probability of choosing i given we reach it = w_i / sum_i
```

![A real run of bucket_list_choose for bucket -6 with weights 1, 1 and 2. For r=0 the scaled value of item 22 is 3.90, which is more than its weight 2, so it is rejected. item 21 is chosen with 0.36 < 1. For r=1 and r=2 both of the last items are rejected and item 20 is chosen](figures/ch28/f06_list.png){#fig-28-f06_list}

Why is this correct? The probability of choosing the last item is w₂/(w₀+w₁+w₂) = 2/4. If it is rejected, the probability of the middle item is w₁/(w₀+w₁) = 1/2. So P(21) = (1 − 1/2) × 1/2 = 1/4 and P(20) = 1/4. A count over 400 thousand inputs gave the same 1:1:2 ratio (100336, 99970, 199694). Adding an item at the **end** moves only the necessary data (20.1%). But removing an item from the middle breaks the order (36% instead of 25% in our simulation).

## tree: a weighted binary tree {#sec-28-8-3}

::: {.algo #alg-28-3 title="Choosing in a tree bucket" src="src/crush/mapper.c :: bucket_tree_choose; src/crush/builder.c :: crush_make_tree_bucket" complexity="O(log n); node numbers stay fixed when items are added"}
:::

```text
node(i) = 2(i+1) − 1   (leaves are odd); height(n) = number of trailing zeros of n
n = num_nodes / 2                          # the root
while n is even:                           # an internal node
    t = (hash4(x, n, r, bucket_id) × node_weights[n]) >> 32     # a uniform number in [0, w)
    n = t < node_weights[left(n)] ? left(n) : right(n)
return items[n >> 1]
```

![A real run of bucket_tree_choose for four items with weights 1, 2, 3 and 4. The root n4 has weight 10. t=4.22 is greater than the weight of the left subtree (3), so the path goes right (n6, weight 7). There t=0.78 < 3, so leaf n5, that is item 32, is chosen. The same path was taken for r=1. The distribution over 400 thousand inputs was about 1:2:3:4](figures/ch28/f07_tree.png){#fig-28-f07_tree}

The elegant trick of tree is its node numbering. Because the hash depends on the **node number**, and the numbers of existing nodes do not change as the tree grows (the old root n4 becomes the left child of n8 in an eight-leaf tree), adding a fifth item moved exactly 20% of the data. But removing from the middle and rebuilding the tree changes the layout of the leaves, and in our simulation it caused 54% movement.

## Comparing movement {#sec-28-8-4}

![The percentage of inputs that got a different destination when the bucket changed, over 200 thousand values of x with the real hash. Blue bar: adding a fifth item to four equal-weight items (theoretical minimum 20%). Orange bar: removing the second item and rebuilding the bucket (theoretical minimum 25%). Only straw2 reaches the theoretical minimum in both cases](figures/ch28/f08_moves.png){#fig-28-f08_moves}

| Bucket type | Selection cost | Adding | Removing or reweighting | Use today |
|---|---|---|---|---|
| uniform | O(1) | bad (80% in the simulation) | bad | almost none |
| list | O(n) | optimal if at the end | bad in the middle | old grow-only clusters |
| tree | O(log n) | optimal | moderate | old, very large buckets |
| straw | O(n) | nearly optimal | nearly optimal, with a known error in the weights | obsolete, replaced by straw2 |
| straw2 | O(n) | optimal | optimal (movement only to/from the changed item) | the default |

::: {.note}
The removal simulation rebuilds the bucket without the removed item. In practice, with `ceph osd crush reweight` to zero or `crush remove`, the behaviour depends on the bucket type and the item's position. For straw2, setting the weight to zero has the same effect as removal, because each item draws its own independent lot.
:::

::: {.sim name="crush"}
:::

# The balancer in upmap mode: calc_pg_upmaps {#sec-28-9}

The mgr balancer in upmap mode (chapter 19) hands the main work to `OSDMap::calc_pg_upmaps` in C++. This function makes a copy of the OSDMap, experiments with `pg_upmap_items` pairs and returns the result in an Incremental.

![The structure of OSDMap::calc_pg_upmaps. After computing the PGs of each OSD and each OSD's deviation from its weight target, the overfull and underfull sets are built in every round. Then, starting from the fullest OSD, first removing earlier upmaps and then adding a new pair is tried. Each change is accepted only if the balance score does not get worse](figures/ch28/f09_upmap.png){#fig-28-f09_upmap}

::: {.algo #alg-28-4 title="Greedy upmap selection with a score test" src="src/osd/OSDMap.cc :: OSDMap::calc_pg_upmaps, calc_deviations, fill_overfull_underfull, try_pg_upmap, find_best_remap" complexity="each round O(OSD × PG) for the scan and one CRUSH computation per candidate; at most max rounds"}
:::

```text
ppw = total_pgs / Σ weight
dev(osd) = pgs(osd) − weight(osd) × ppw
bal_score = Σ weight × (dev / target)²                  # 0 means perfect
repeat up to max times:
    overfull  = {dev > max_deviation};   more_overfull  = {0 < dev ≤ max_deviation}
    underfull = {dev < −max_deviation};  more_underfull = {−max_deviation ≤ dev < 0}
    if overfull and underfull both empty: break
    for osd in OSDs by dev descending (dev > max_deviation):
        if try_drop_remap_overfull(osd): goto test       # first take back old upmaps
        for pg on osd (without a manual pg_upmap):
            out = try_pg_upmap(pg, overfull, underfull)   # rerun CRUSH with zero weight for the overfull ones
            pos = find_best_remap(orig, out)            # the single best replacement
            if pos ≥ 0: add pair (orig[pos] → out[pos]); goto test
    for osd in underfull: try_drop_remap_underfull(osd) → test
    break
test: if new_bal_score > bal_score: reject (skip that PG)  else: apply
```

**Numerical example.** Four equal-weight OSDs, one pool with 64 PGs and size=3, so 192 copies and a target of 48 per OSD. The counts are [56, 50, 44, 42] and the deviations [+8, +2, −4, −6]. With `upmap_max_deviation=5` (the balancer module's default): overfull={osd.0}, underfull={osd.3}. Score = (64 + 4 + 16 + 36)/48² = 0.0521.

| Step | upmap pair | Counts | Deviations | bal_score |
|---|---|---|---|---|
| 0 | — | 56, 50, 44, 42 | +8, +2, −4, −6 | 0.0521 |
| 1 | (0 → 3) | 55, 50, 44, 43 | +7, +2, −4, −5 | 0.0408 |
| 2 | (0 → 3) for another PG | 54, 50, 44, 44 | +6, +2, −4, −4 | 0.0313 |
| 3 | (0 → 2) | 53, 50, 45, 44 | +5, +2, −3, −4 | 0.0234 |

After step 3, no OSD deviates by more than 5, so overfull and underfull are empty and the loop ends. From step 2 on, underfull is empty and the replacements come from more_underfull. Three `pg_upmap_items` entries are recorded in the OSDMap. Each change adds only **one** pair. The code comment says this is deliberately "slow", so that every small step really moves the distribution toward the perfect state. This example assumes the CRUSH rule allows these replacements (for example, the OSDs are on different hosts). If a replacement breaks the failure-domain rule, try_pg_upmap rejects it.

::: {.note}
`osd_calc_pg_upmaps_aggressively` (and its fast variant) shuffles the PG list and searches more exhaustively. In main, `bal_score` is summed as a double. The code comment says that with float, a change of one PG in large clusters could be smaller than the precision of the sum, and the balancer would stall.
:::

# MSR rules: several OSDs per failure domain {#sec-28-10}

In EC with k+m larger than the number of hosts (for example 4+2 on three hosts), the classic rule `choose indep 3 type host` followed by `chooseleaf indep 2 type osd` has a problem. If an OSD goes out, the second step looks for a replacement only in the **same** host. If that host has no other healthy OSD, the shard is left unplaced, because classic CRUSH cannot go back to the previous step. **MSR** (Multi-Step Retry) rules, from Squid, with the types `msr_firstn` and `msr_indep` and the `choosemsr` step, solve this: the whole descent from the root is retried.

![An MSR rule for EC 4+2 on three hosts. The six-slot output is divided into three strides of two, and the hosts of each stride are kept apart from the other strides. When osd.7 is out, index 3 stays empty in this round, and in the next round the descent is repeated from the root with a new try number. The replacement can be in the same host or in a host not used in another stride](figures/ch28/f10_msr.png){#fig-28-f10_msr}

::: {.algo #alg-28-5 title="Multi-step descent with retry (MSR)" src="src/crush/mapper.c :: crush_msr_do_rule, crush_msr_choose, crush_msr_descend, crush_msr_get_retry_value" complexity="O(msr_descents × result_max × depth × bucket size) in the worst case; default msr_descents = msr_collision_tries = 100"}
:::

```text
pseudocode
total = Π(arg1 of choosemsr steps)      # for example 3 × 2 = 6
for descent in 0 .. msr_descents-1 while the output is not complete:
    crush_msr_choose(root, [0, total), step0, tryno = descent)
crush_msr_choose(bucket, [start, end), step):
    num_strides = step.arg1 (or result_max if 0)
    stride_length = (end − start) / num_strides
    for each stride:
        if all indexes of the stride are filled: continue
        for local_try in 0 .. msr_collision_tries-1:
            r = ((descent × result_max + index) << 16) + local_try
            cand = crush_msr_descend(bucket, step.type, r)          # straw2 etc. down to the target type
            if cand is used in another stride (collision): continue
            if last step: if the OSD is out ⇒ leave the index empty (undo after the round)
            else: crush_msr_choose(cand, [stride], step+1) for the next level
```

**Numerical example.** With `choosemsr 3 host` and `choosemsr 2 osd`, total_descendants = 6, num_strides = 3 and stride_length = 2. In the recursive call for each host, total_descendants = 2 and stride_length = 1 (these are the same numbers as in the comment above `crush_msr_choose` in the code). The try value for descent=1, result_max=6, index=3 and local_try=0 is ((1×6+3) ≪ 16) + 0 = 9 × 65536 = 589824. So the hashes are completely different in each round. The guarantee of the `choosemsr 3 host` step is "at least" three hosts, not "exactly" three: one stride may use two hosts after an OSD goes out, provided those hosts are not in other strides.

::: {.warn}
MSR rules need the `CRUSH_MSR` feature (bit 38 in `ceph_features.h`), and only clients and OSDs that know it (Squid and later) can compute the mapping. At the time of writing, `net/ceph/crush/mapper.c` in the Linux kernel mainline has no MSR implementation, so krbd and ceph.ko cannot use a pool with an MSR rule. Check `ceph features` before creating an MSR rule.
:::

# Supplementary and up to date {#sec-28-11}

- MSR rules (`CRUSH_RULE_CHOOSE_MSR` and the types `CRUSH_RULE_TYPE_MSR_FIRSTN` and `MSR_INDEP`) exist in the Squid and main code and are not in Reef. Their goal is placing several shards in one failure domain with precise control (for example EC 8+6 on 4 racks).
- The Linux kernel has the same `mapper.c`, `hash.c` and `crush_ln_table.h` in `net/ceph/crush/`. Its support for new CRUSH features (such as MSR) depends on the kernel version, and the cluster's features must be aligned with `ceph osd set-require-min-compat-client`.

# Hands-on exercise {#sec-28-12}

1. Rebuild this chapter's test program: take `hash.c` and `crush_ln_table.h` from the Ceph code and run `bucket_straw2_choose` for a bucket with five items and arbitrary weights. Measure the distribution for one million x.
2. Map a few objects with `ceph osd map` and match ps against a manual calculation of `ceph_stable_mod`.
3. Increase the weight of one host by 10% in a test map and use `crushtool --compare` to see the number of PGs moved and their destinations (they should move only to that host).
4. Create a manual pg-upmap-items that puts two replicas on one host and see what the mon does with it.

# Review questions {#sec-28-13}

1. How does ceph_stable_mod limit data movement when pg_num is increased?
2. Why is HASHPSPOOL needed?
3. Why does CRUSH use only integer operations?
4. In straw2, how is the draw computed and why does the largest draw win?
5. What does crush_ln return, and with what precision?
6. Why does straw2 have minimal movement, and why did the old straw not?
7. How is a collision resolved in firstn, and what is its limit?
8. What is the difference between firstn and indep for EC?
9. What problem does the weight-set in choose_args solve?
10. What is the order in which upmaps are applied, and what does the mon do with an invalid upmap?

# Sources for this chapter {#sec-28-14}

- The CRUSH paper (Weil et al., SC 2006): https://ceph.io/assets/pdfs/weil-crush-sc06.pdf
- mapper.c: https://github.com/ceph/ceph/blob/main/src/crush/mapper.c
- hash.c: https://github.com/ceph/ceph/blob/main/src/crush/hash.c
- CRUSH maps: https://docs.ceph.com/en/latest/rados/operations/crush-map/
- Editing a CRUSH map: https://docs.ceph.com/en/latest/rados/operations/crush-map-edits/
- upmap: https://docs.ceph.com/en/latest/rados/operations/upmap/
- balancer: https://docs.ceph.com/en/latest/rados/operations/balancer/
- crushtool: https://docs.ceph.com/en/latest/man/8/crushtool/
- Bob Jenkins's hash function: https://burtleburtle.net/bob/hash/doobs.html
