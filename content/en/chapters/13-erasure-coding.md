---
chapter: 13
id: ch13
title: Erasure Coding for Storage Efficiency
part: main
lang: en
---

# Before you start {#sec-13-1}

## What questions does this chapter answer? {#sec-13-1-1}

Three-way replication is simple and fast, but it consumes three terabytes of disk for every terabyte of user data. **Erasure coding** (EC) brings the overhead down to about 1.5 times or less, with the same or even a higher level of fault tolerance. The price is more complexity, CPU usage and higher latency for small writes. From 2019 to today, EC in Ceph has gone through two major changes: ISA-L became the default instead of Jerasure, and **FastEC** arrived in Tentacle.

- What is EC, and what do the parameters k and m mean?
- How is EC implemented inside Ceph: stripe, shard and chunk?
- How do the plugins (ISA, Jerasure, LRC, SHEC, CLAY) differ?
- Where should we use EC, and where not?
- How do we create an EC pool and enable overwrites and FastEC?
- Where does the famous "2147483647" error come from?

# What is EC? {#sec-13-2}

## k+m {#sec-13-2-1}

In EC, data is split into **k data chunks**, and **m parity chunks** are computed from them. Any k of the k+m chunks are enough to rebuild the data completely; so up to m simultaneous failures can be tolerated.

![4+2 coding: a sixteen-kilobyte stripe is split into four four-kilobyte data shards, and two parity shards are computed from them; each shard is placed on an OSD in a separate failure domain](figures/ch13/f01_km.png){#fig-13-f01_km}

| Scheme | Storage overhead | Fault tolerance | Minimum failure domains (host) |
|---|---|---|---|
| Replication 3 | 3.0× | 2 | 3 |
| EC 2+1 | 1.5× | 1 | 3 |
| EC 4+2 | 1.5× | 2 | 6 |
| EC 8+3 | 1.375× | 3 | 11 |
| EC 8+4 | 1.5× | 4 | 12 |

::: {.warn}
"Minimum failure domains" is no joke: with EC 8+3 and a host failure domain you need eleven hosts, and twelve or more so that shards can be rebuilt after one host fails. EC on a small cluster, or squeezing the failure domain (for example `crush-failure-domain=osd`), destroys real durability.
:::

::: {.sim name="ecprofile"}
:::

## The mathematics in plain terms {#sec-13-2-2}

Reed-Solomon codes (which ISA-L and Jerasure implement) work over a **Galois field** (usually GF(2^8)): each byte is a field element, and addition is XOR. Treat k data bytes as a vector d; the shards are the product of a (k+m)×k generator matrix G and d. The first k rows of G are the identity matrix (so the data shards are the data itself), and the next m rows are the parity coefficients. To rebuild, we take the k×k submatrix that corresponds to any k available shards and invert it. The condition for this to work is that **every** k×k submatrix is invertible; Vandermonde (`reed_sol_van`) and Cauchy (`cauchy`) matrices have this property.

```text
shard_i = Σ_j  G[i][j] ⊗ d_j      (⊗ multiplication in GF(2^8), Σ is XOR)
for i < k:  G[i] = e_i  →  shard_i = d_i
decode:  d = (G_S)^-1 · shards_S     (S: any k available indices)
```

# EC inside Ceph {#sec-13-3}

## Stripe, shard and chunk {#sec-13-3-1}

![Stripe layout: the object's data is split into stripes of length k×stripe_unit; chunk i of each stripe goes to shard i, and each stripe's parity is computed separately](figures/ch13/f02_stripe.png){#fig-13-f02_stripe}

In an EC pool, each PG has **shards** instead of "replicas": OSD number i in the acting set is shard i and keeps only its own chunk. The object is split into stripes of size `k × stripe_unit` (stripe_unit defaults to four kilobytes). For each stripe, k data chunks and m parity chunks are built, and chunk i is stored on shard i. So on each OSD the object appears as a "shard object" that contains all the i-th chunks of that object.

## The primary in EC {#sec-13-3-2}

In an EC pool the primary is responsible for encoding and decoding: the client talks only to the primary, and the primary encodes the data and sends the chunks to the shards. On reads, the primary gathers the needed chunks from the shards and decodes if necessary. This means EC's CPU and network load is concentrated on the primaries.

![A degraded read: when shard 1 is unavailable, minimum_to_decode chooses a set of k available shards, and decode rebuilds the missing data](figures/ch13/f04_decode.png){#fig-13-f04_decode}

## Partial writes and overwrites {#sec-13-3-3}

EC originally (before Luminous) supported only appends and could not be used for RBD and CephFS. The `allow_ec_overwrites` flag (from Luminous; the old outline tied it to Kraken) made overwrites possible. But in the old implementation, overwriting 4 kilobytes in the middle of a stripe meant a **full read-modify-write**: reading the rest of the stripe, encoding again and writing all the shards.

![Comparing a small write in old EC and FastEC: the old implementation reads and rewrites the whole stripe; FastEC updates only the changed shard and the parities](figures/ch13/f03_rmw.png){#fig-13-f03_rmw}

# Plugins and profiles {#sec-13-4}

![EC plugins in Ceph: all implement the common ErasureCodeInterface and are loaded as dynamic libraries](figures/ch13/f05_plugins.png){#fig-13-f05_plugins}

| Plugin | Idea | Use |
|---|---|---|
| isa | Reed-Solomon with the Intel ISA-L library (Vandermonde or Cauchy matrix); the default for new clusters from Tentacle | The default choice; supports FastEC |
| jerasure | Reed-Solomon and other codes with the Jerasure library; the library is no longer maintained | Older clusters; FastEC only with reed_sol_van |
| lrc | Locally Repairable Code: local groups with local parity | Recovery with fewer reads; multi-rack clusters |
| shec | Shingled EC: overlapping parities | Lower recovery cost at a small cost in durability |
| clay | Coupled-layer: splitting a chunk into sub-chunks | A sharp reduction in network traffic when recovering one shard |

::: {.note}
According to the Tentacle release notes, the default plugin changed from Jerasure to **ISA-L**. Clusters created on Tentacle or later use ISA-L; upgraded clusters keep the previous default. In the current code, `osd_pool_default_erasure_code_profile` is `plugin=isa technique=reed_sol_van k=2 m=2`.
:::

## Creating a profile and a pool {#sec-13-4-1}

```bash
ceph osd erasure-code-profile ls
ceph osd erasure-code-profile get default
ceph osd erasure-code-profile set ec42 plugin=isa technique=reed_sol_van k=4 m=2 \
     crush-failure-domain=host crush-device-class=hdd
ceph osd pool create ecpool erasure ec42
ceph osd pool set ecpool allow_ec_overwrites true     # for RBD and CephFS
ceph osd pool application enable ecpool rgw
```

::: {.warn}
A pool's profile **cannot be changed after creation**: k, m, the plugin and stripe_unit stay fixed. To change them you must create a new pool and move the data. Before creating it, consider the cluster's future growth and the number of failure domains.
:::

## LRC and CLAY {#sec-13-4-2}

```bash
# LRC: k=4 data, m=2 global parity, l=3 → one local parity for every 3 chunks
ceph osd erasure-code-profile set lrc42 plugin=lrc k=4 m=2 l=3 crush-failure-domain=host
# CLAY: d is the number of shards that take part in recovering one shard
ceph osd erasure-code-profile set clay42 plugin=clay k=4 m=2 d=5 crush-failure-domain=host
```

::: {.deep}
In ordinary Reed-Solomon, rebuilding **one** lost shard requires reading k whole shards: for 8+3, that is eight times the lost data on the network. LRC reduces this to the size of the local group with local parity (at the cost of more space). CLAY splits each chunk into sub-chunks and, during recovery, reads only part of the sub-chunks from each of the d helpers; with the same space overhead as RS, it has less recovery traffic, but the reads are more scattered.
:::

# Where EC and where replication? {#sec-13-5}

| Workload | Recommendation |
|---|---|
| Large RGW objects (archive, backup, media) | EC; the best cost ratio |
| The RGW bucket index pool and metadata | Replicated; omap is not supported on EC |
| RBD for latency-sensitive databases | Replicated |
| RBD for general-purpose VMs or backups | EC with FastEC and stripe_unit=16K (Tentacle+) |
| CephFS archive data | A second EC data pool with a layout |
| CephFS metadata and the default data pool | Replicated |

::: {.tip}
RBD on EC always has two pools: the image metadata (header, omap) in a replicated pool, and the data in an EC pool with the `--data-pool` option:
:::

```bash
rbd create rbd/vm01 --size 200G --data-pool ecpool
rbd info rbd/vm01 | grep data_pool
```

# FastEC in Tentacle {#sec-13-6}

## What changed? {#sec-13-6-1}

Tentacle added a new implementation of the EC I/O path, collectively called **FastEC**: partial reads (only the needed shards), partial writes, **parity delta** writes, removal of zero padding and space savings for small objects. It is enabled with a per-pool flag:

```bash
ceph osd pool set ecpool allow_ec_optimizations true
ceph osd pool get ecpool allow_ec_optimizations
# the default for new pools
ceph config set global osd_pool_default_flag_ec_optimizations true
```

The limitations, according to the documentation:

- All MONs and OSDs must be Tentacle or newer; clients do not need upgrading.
- Once enabled, the flag **cannot be turned off**, because it changes how data is stored.
- It works only with ISA-L, or Jerasure with `reed_sol_van`; CLAY, LRC and SHEC are rejected.
- stripe_unit must be a multiple of 4 kilobytes; the documentation recommends **16 kilobytes** for most workloads and up to 256 kilobytes for mostly-read workloads.

```bash
ceph osd erasure-code-profile set ec42fast plugin=isa technique=reed_sol_van k=4 m=2 \
     stripe_unit=16K crush-failure-domain=host
ceph osd pool create rbd-ec erasure ec42fast
ceph osd pool set rbd-ec allow_ec_overwrites true
ceph osd pool set rbd-ec allow_ec_optimizations true
```

# Troubleshooting: the 2147483647 error {#sec-13-7}

In the output of `ceph pg dump` or `ceph pg map` for an EC pool you sometimes see the number **2147483647** instead of an OSD number. This number is the constant `CRUSH_ITEM_NONE`:

```c
/* from ceph/ceph, LGPL — src/crush/crush.h */
#define CRUSH_ITEM_NONE   0x7fffffff
```

It means CRUSH could not find an OSD for that shard position. In a replicated pool an empty position is simply dropped; but in EC each shard's position has meaning (shard 3 must stay shard 3), so instead of being dropped it is filled with NONE. Common causes:

- Fewer failure domains than k+m (for example 4+2 with five hosts).
- OSDs that are out or down and have emptied a domain.
- A CRUSH rule with the wrong device class or root.
- Too few CRUSH tries, which give no result in an unbalanced hierarchy (`set_choose_tries`).

```bash
ceph pg ls-by-pool ecpool | grep -c 2147483647
ceph osd crush rule dump ecpool
ceph osd getcrushmap -o cm && crushtool -i cm --test --rule <id> --num-rep 6 --show-bad-mappings
```

::: {.debug}
If `--show-bad-mappings` prints output but there are enough hosts, check the `set_choose_tries 100` step in the EC rule (rules created with `create-erasure` usually have it). If you do not have enough hosts, the right fix is adding hosts or choosing a smaller k+m, not lowering the failure domain to osd.
:::

# Inside the EC backend: writes, rollback and recovery {#sec-13-8}

This section is a bridge to chapter 27 ("The mathematics of erasure coding"). Here, instead of the mathematics, we examine the OSD mechanics: how an EC write is coordinated between shards, what happens if a failure occurs halfway, and exactly what recovery reads and writes. The related classes in `src/osd/` on the main branch are `ECBackend`, `ECCommon`, `ECTransaction`, `ECUtil` and their "L" (legacy) versions, between which `ECSwitch` chooses based on a pool flag.

![A write in an EC pool. The primary (which is not always shard zero, but is assumed to be shard 0 in this figure) breaks the transaction into stripes and decides whether an RMW is needed. If needed, it reads the old chunks, computes the parity, and sends each shard an ECSubWrite containing that shard's chunk and the pg log entry. Each log entry has an ObjectModDesc that describes how this change can be undone. The client gets a reply only after all acting shards have committed](figures/ch13/f07_ecwrite.png){#fig-13-f07_ecwrite}

## Why does EC need rollback? {#sec-13-8-1}

In replication, each replica is a full copy. If a write commits on only some replicas, recovery can copy the new version from one replica to the others. In EC, no shard has all the data. If a write has committed on 3 of 6 shards and then the primary dies, neither the old nor the new version can be rebuilt from any consistent set of k shards. Ceph's solution is to make changes "reversible": each EC pg log entry has an `ObjectModDesc`, and after peering, shards that are ahead of the agreed point **roll back** their changes.

| op in `ObjectModDesc::ModID` | Value | How it is undone |
|---|---|---|
| APPEND | 1 | Truncate to the previous size |
| SETATTRS | 2 | Restore the previous xattrs that were saved |
| DELETE | 3 | Instead of being deleted, the object was stashed as a temporary version and is restored |
| CREATE | 4 | Delete the new object |
| UPDATE_SNAPS | 5 | Restore the previous snapset |
| TRY_DELETE | 6 | Optional delete |
| ROLLBACK_EXTENTS | 7 | For overwrites: the previous extents are kept in a temporary object |
| EC_OMAP | 8 | For omap on EC (in main) |

`pg_log_t` has two boundaries: `can_rollback_to` (entries newer than it can be rolled back) and `rollback_info_trimmed_to` (stash information has been deleted up to there). When the primary is sure an entry has committed on all shards, `can_rollback_to` moves forward, and the stashed data (for example the old ROLLBACK_EXTENTS extents) can be deleted. This is why overwrites in old EC need temporary space and extra writes compared with replication.

::: {.deep}
**The hidden cost of ROLLBACK_EXTENTS:** for every partial overwrite, the old data of that range must be copied into a temporary object (a generation) before it is overwritten, so that it can be restored if a rollback is needed. In BlueStore this copy is done with `clone_range` and a shared blob (chapter 24, shared blob), so the actual data is not written again, but extra metadata (`X` keys and the extent map) is created. Optimized EC in Tentacle reduces part of this work by choosing ranges more precisely.
:::

## The default min_size and the reason for it {#sec-13-8-2}

In `OSDMonitor::prepare_pool_size`, the default for EC pools is `min_size = k + min(1, m − 1)` (and `size = num_zones × (k + m)`). So for k=4, m=2, min_size is 5: the pool accepts writes as long as at least 5 shards are available. Therefore, after one shard is lost, there is still a spare shard to tolerate the next failure. For m=1, min_size = k, and any second failure during recovery means data loss. That is why m=1 is not recommended for important data.

![Reads and recovery in EC. On reads, the OSD uses minimum_to_decode to determine the smallest set of needed shards. With fast_read=false only those are read. With fast_read=true all shards are read, and decoding happens when the first k replies arrive (lower tail latency, more traffic). In recovery, the primary builds the list of missing objects for each shard from the pg log, reads from k healthy shards (or fewer with LRC and CLAY), decodes only the missing chunk and pushes it to the new OSD. The bottom of the figure shows the default min_size formula](figures/ch13/f08_ecrecover.png){#fig-13-f08_ecrecover}

| Pool option | Effect |
|---|---|
| `fast_read` | Read all shards in parallel; lower tail latency at the cost of more traffic |
| `allow_ec_overwrites` | Required for RBD and CephFS on EC; enables RMW and ROLLBACK_EXTENTS |
| `allow_ec_optimizations` (Tentacle onwards) | The optimized backend; irreversible (chapter 27) |
| `min_size` | The minimum available shards for accepting I/O |

```bash
ceph osd pool set ecpool fast_read 1
ceph pg 5.1as2 query | jq '.info | {last_update, last_complete, log_tail}'   # shard 2 of PG 5.1a
ceph pg 5.1a list_unfound
ceph daemon osd.4 dump_ops_in_flight | jq '.ops[] | select(.description|test("ECSub"))'
```

::: {.note}
PG names in EC have a shard suffix: `5.1as2` means shard 2 of PG 5.1a. This suffix appears in `ceph pg dump` and in collection names on the OSD (`5.1as2_head`), and it is the same `shard_id` that is added to 0x80 in the onode key (chapter 24).
:::

# Erasure coding by the numbers: the Reed-Solomon matrix, the MDS limit, parity-delta updates and the cost of rebuilding {#sec-13-9}

This section runs the mathematics behind the ISA plugin on real bytes. References are to src/erasure-code/isa in main (November 2026) and to the gf_gen_rs_matrix function in the ISA-L library (erasure_code/ec_base.c). GF(2^8) arithmetic with the polynomial 0x11d was reimplemented in Python and checked against the gff_base table in ISA-L.

## Encoding and decoding one byte column {#sec-13-9-1}

::: {.algo #alg-13-1 title="Reed-Solomon with a Vandermonde matrix in ISA (technique=reed_sol_van)" src="src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::prepare, isa_encode, isa_decode; ISA-L ec_base.c :: gf_gen_rs_matrix" complexity="encoding O(k × m) GF multiplications per byte; decoding O(k³) for the matrix inverse (the tables are kept in a cache)"}
:::

```text
pseudocode
G[0..k−1] = I_k                        # systematic: the data shards are the data itself
gen = 1
for i in k .. k+m−1: G[i][j] = gen^j ; gen = gen × 2      (in GF(2^8))
parity_i = ⊕_j G[i][j] ⊗ d_j
decoding: choose k healthy rows ← B ; d = B⁻¹ × (healthy shards)
```

**Numerical example (k = 4, m = 2, the bytes "ABCD").** Row P0 is all ones, so P0 = 0x41 ⊕ 0x42 ⊕ 0x43 ⊕ 0x44 = 0x04. Row P1 is 1, 2, 4 and 8: 2 ⊗ 0x42 = 0x84, 4 ⊗ 0x43 = 0x11 and 8 ⊗ 0x44 = 0x1a, so P1 = 0xce. If d1 and d3 are lost, the rows d0, d2, P0 and P1 form a 4×4 matrix whose inverse gives back 0x42 and 0x44. All 15 cases of losing two shards in 4+2 can be decoded.

![Reed-Solomon encoding of one byte column. Left: the 6×4 matrix built with gf_gen_rs_matrix, containing the identity for the data and two parity rows. Right: computing P0 and P1 for "ABCD" and decoding after losing d1 and d3. The multiplications are in GF(2^8) with the polynomial 0x11d](figures/ch13/f09_gfencode.png){#fig-13-f09_gfencode}

## Why does ISA sometimes fall back to Cauchy? {#sec-13-9-2}

::: {.algo #alg-13-2 title="Checking whether the Vandermonde matrix is MDS" src="src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::parse (m > 4, or m = 4 and k > 21 ← cauchy)" complexity="full check: Σ C(k,e)·C(m,e) matrix inversions"}
:::

```text
pseudocode
for each e from 1 to m, each subset L of e data shards and P of e parity rows:
    rows = (healthy data) ∪ P
    if det = 0 in GF(2^8): pattern L cannot be decoded
the code is MDS if no pattern fails
```

**The result of our full check.** For 4+2 and 21+4 there is no failing pattern. For 22+4 there are two patterns, for example losing d0, d10, d21 and P2, which do not give the data back despite m = 4. For 8+5 there are six patterns (for example d0, d2, d5, P1 and P2). For 4+5 no problem was found. So the code's rule, switching to Cauchy for m > 4 or m = 4 with k > 21, is exactly the failure boundary at m = 4 and is conservative for m > 4. Take its warning message when a profile is created ("switching to Cauchy technique") seriously: the pool's real technique differs from what you wrote.

![The number of patterns of losing up to m shards that cannot be decoded with the Vandermonde matrix. Green means MDS and red means it has failures. The full check was done with our script based on gf_gen_rs_matrix](figures/ch13/f10_mds.png){#fig-13-f10_mds}

## Parity-delta updates {#sec-13-9-3}

::: {.algo #alg-13-3 title="Parity-delta writes in FastEC" src="src/erasure-code/isa/ErasureCodeIsa.cc :: encode_delta, apply_delta (ec_encode_data_update); src/osd/ECTransaction.cc (do_parity_delta_write)" complexity="O(m) GF multiplications per changed byte"}
:::

```text
pseudocode
delta = old_d ⊕ new_d                       # encode_delta
for each parity i: P_i ⊕= G[i][j] ⊗ delta    # apply_delta; for m=1 only XOR
choice in the OSD (ec_pdw_write_mode = 0):
    conv = shards a conventional RMW must read ; pdw = changed shard + the parities
    if |pdw| ≥ k: conventional
    elif pdw needs a rebuild: conventional ; elif only conventional needs a rebuild: pdw
    else: pdw if |pdw| ≤ |conv|  (tie ← pdw)
```

**Numerical example.** d2 changes from 0x43 to 0x5a. delta = 0x19, so P0 = 0x04 ⊕ 0x19 = 0x1d and P1 = 0xce ⊕ (4 ⊗ 0x19 = 0x64) = 0xaa, which is the same result as a full re-encode. For overwriting 4K of one shard: in 4+2, a conventional RMW reads the three other data shards, and PDW reads the old d2 and two parities, i.e. 3 against 3. On a tie PDW is chosen. In 8+3 the comparison is 7 against 4, in favour of PDW. In 2+2 the comparison is 1 against 3, and the conventional path wins. This path is active only in a pool with FastEC (allow_ec_optimizations, Tentacle onwards) and a plugin that has the paritydelta flag (ISA and Jerasure).

![The steps of a parity-delta update for changing one byte in d2: XOR of old and new, multiplication by that shard's column coefficient, and XOR into each parity. The last row shows the match with a full re-encode. The purple line compares the number of shards read on the two paths for three profiles](figures/ch13/f11_delta.png){#fig-13-f11_delta}

## The cost of rebuilding one shard: RS, LRC and CLAY {#sec-13-9-4}

::: {.algo #alg-13-4 title="The read volume for rebuilding one chunk" src="src/erasure-code/clay/ErasureCodeClay.cc :: parse (q = d − k + 1, t = (k+m+nu)/q, sub_chunk_no = q^t); src/erasure-code/lrc" complexity="O(1)"}
:::

```text
pseudocode
RS:   read = k chunks
LRC:  read = l chunks (local group) ; raw overhead = (k + m + (k+m)/l) / k
CLAY: q = d − k + 1 ; each of the d helpers sends 1/q of a chunk ; read = d / q chunks
      condition: k + 1 ≤ d ≤ k + m − 1 ; sub-chunks = q^t
```

**Numerical example.** In 4+2, an RS rebuild reads four chunks. LRC with l = 3 reads three chunks, but its raw overhead is 2.0, not 1.5. CLAY with d = 5 (q = 2, t = 3 and 8 sub-chunks) reads only 2.5 chunks and keeps the 1.5 overhead. In 8+4, the numbers for RS, LRC (l = 4, overhead 1.875) and CLAY (d = 11, q = 4, 64 sub-chunks) are 8, 4 and 2.75 chunks respectively. CLAY's cost is in fragmented reads: each helper sends scattered sub-chunks, so on HDDs the number of seeks goes up.

![The data read to rebuild one lost chunk with RS, LRC and CLAY in two configurations, together with each scheme's raw overhead. LRC reduces reads with more space, and CLAY with the same space as RS](figures/ch13/f12_repair.png){#fig-13-f12_repair}

# Inside the code: EC in the OSD {#sec-13-10}

## File map {#sec-13-10-1}

| Path | Role |
|---|---|
| src/erasure-code/ErasureCodeInterface.h | The plugin interface: init, encode, decode, minimum_to_decode, optimization flags |
| src/erasure-code/isa, jerasure, lrc, shec, clay | Plugin implementations |
| src/osd/ECSwitch.h | The switch between the old (ECBackendL) and optimized (ECBackend) implementations |
| src/osd/ECBackend.cc, ECCommon.cc | The optimized read, write and recovery path |
| src/osd/ECTransaction.cc | Write planning: the reads needed, RMW or parity delta |
| src/osd/ECUtil.h | stripe_info_t and the mapping of a logical range to shards |
| src/osd/OSDMap.cc | pgtemp_primaryfirst for choosing the primary in optimized pools |

## The plugin interface {#sec-13-10-2}

Each plugin is a class that implements `ErasureCodeInterface`. The key functions (signatures abbreviated):

- `init(profile, ss)`: reads the profile parameters and builds the matrix.
- `get_chunk_count()` and `get_data_chunk_count()`: k+m and k.
- `minimum_to_decode(want_to_read, available, minimum)`: the smallest set of shards for the requested read.
- `encode(want_to_encode, in, encoded)` and `decode(want_to_read, chunks, decoded)`.
- `get_supported_optimizations()`: the flags FastEC bases its decisions on.

```cpp
// from ceph/ceph, LGPL — src/erasure-code/ErasureCodeInterface.h (excerpt)
FLAG_EC_PLUGIN_PARTIAL_READ_OPTIMIZATION = 1<<0,
FLAG_EC_PLUGIN_PARTIAL_WRITE_OPTIMIZATION = 1<<1,
FLAG_EC_PLUGIN_ZERO_INPUT_ZERO_OUTPUT_OPTIMIZATION = 1<<2,
FLAG_EC_PLUGIN_ZERO_PADDING_OPTIMIZATION = 1<<3,
FLAG_EC_PLUGIN_PARITY_DELTA_OPTIMIZATION = 1<<4,
```

These flags explain why FastEC works only with some plugins: each optimization needs a particular mathematical property. For example, "zero in, zero out" means that encoding an all-zero block gives all-zero parity (true for linear codes), so writing zero padding can be skipped. Parity delta relies on the code being linear: if the data of shard j changes from d to d', the new parity equals the old parity plus G[i][j]⊗(d ⊕ d').

## ECSwitch: a gradual transition {#sec-13-10-3}

The comment at the top of `ECSwitch.h` is explicit: this class is a "temporary switcher" between the legacy and optimized implementations until the new implementation is trusted enough. `ECSwitch` holds both objects, `ECLegacy::ECBackendL legacy` and `ECBackend optimized`, and routes requests to one of them based on the pool flag (`allow_ec_optimizations`). This is why the flag is irreversible: once data is written in the new format, the old implementation cannot read it.

## The RMW or parity-delta decision {#sec-13-10-4}

In `ECTransaction.cc` a plan is built for each write. The selection logic, simplified:

```cpp
// from ceph/ceph, LGPL — src/osd/ECTransaction.cc (excerpt, simplified indentation)
if (sinfo.supports_parity_delta_writes() && !object_in_cache &&
    orig_size == projected_size && !reads.empty() && !op.truncate) {
  ...
  if (pdw_write_mode != 0) {
    do_parity_delta_write = (pdw_write_mode == 2);
  } else if (pdw_read_shards.size() >= sinfo.get_k()) {
    do_parity_delta_write = false;
  } else if (!shard_id_set::difference(pdw_read_shards, readable_shards).empty()) {
    do_parity_delta_write = false;
  } else if (!shard_id_set::difference(read_shards, readable_shards).empty()) {
    do_parity_delta_write = true;
  } else {
    do_parity_delta_write = pdw_read_shards.size() <= read_shards.size();
  }
}
```

Reading it: parity delta only makes sense when the object size does not change, there is no truncate and the data is not in the cache. If parity delta needs k reads or more, it has no advantage; if parity delta needs a rebuild, it is set aside; if the conventional RMW needs a rebuild but parity delta does not, parity delta is chosen; otherwise the method with fewer reads wins (preferring parity delta on a tie). The `pdw_write_mode` variable makes it possible to force one of the two methods for testing.

## Why is shard 0 not always the primary? {#sec-13-10-5}

In optimized pools, some data shards are not updated on every I/O (a partial write touches only the changed shard and the parities). Such a shard cannot become the primary, because the primary must have the PG's complete log. But the primary selection logic in the OSDMap cannot be changed without upgrading clients. The solution is `OSDMap::pgtemp_primaryfirst()`: when setting pg_temp, the OSDMonitor reorders it so that the shards allowed to be primary come first.

![The code comment's example for an optimized 4+2 pool: shard 0 is lost; pg_temp is ordered so that the parity shards (which are always up to date) come first and osd.9 becomes the primary](figures/ch13/f06_pgtemp.png){#fig-13-f06_pgtemp}

```cpp
// from ceph/ceph, LGPL — src/osd/OSDMap.cc (comment excerpt)
 * Example: Optimized EC pool 4+2
 * acting_set = {NONE, 6, 7, 8, 9, 10}
 * non_primary_shards = {1, 2, 3} # data shards other than shard 0
 * pg_temp = {NONE, 9, 10, 6, 7, 8} # non-primary shards at end
 * primary will be OSD 9(1)
```

## Pseudocode of a degraded read {#sec-13-10-6}

```text
read(obj, off, len):
  want = shards_covering(off, len)                 # ECUtil: logical range → shard extents
  avail = shards_up_and_not_missing(obj)
  if want ⊆ avail:                                  # partial read (FastEC)
     return gather(want)
  need = ec_impl.minimum_to_decode(want, avail)     # k shards
  chunks = gather(need)
  return ec_impl.decode(want, chunks)[off:len]
```

::: {.summary title="SRE notes for this chapter"}

- EC needs enough failure domains: at least k+m, preferably k+m+1.
- The profile is immutable; choose it correctly from the start.
- New pools: ISA-L; on Tentacle+ with FastEC and stripe_unit=16K for RBD/CephFS.
- Metadata, omap and bucket indexes on a replicated pool.
- 2147483647 means CRUSH did not fill a shard position; run `crushtool --test`.
- EC recovery is expensive; consider LRC or CLAY for large clusters.

:::

# Supplementary and up to date {#sec-13-11}

- **Luminous**: `allow_ec_overwrites` and RBD and CephFS support on EC.
- **Tentacle**: FastEC with `allow_ec_optimizations`; ISA-L the default for new clusters; fixes to truncate+write planning.
- **Squid**: the MSR CRUSH rule type for more flexible EC configurations.
- **Current code**: `osd_pool_default_flag_ec_optimizations=false` (FastEC is not turned on automatically for new pools).

# Hands-on exercise {#sec-13-12}

1. Create 2+1, 4+2 and 8+3 profiles and compare them with `ceph osd erasure-code-profile get`. Which can run on your cluster?
2. Create a 4+2 pool, write an object and use `ceph osd map` to see which OSD each shard is on. Stop one OSD and read the object.
3. Use an EC pool as the data-pool of an RBD image, and compare 4-kilobyte random writes with fio against a replicated pool.
4. On a test Tentacle cluster, repeat the same test with `allow_ec_optimizations` and stripe_unit=16K.
5. Create a 4+2 pool on a cluster with five hosts and observe 2147483647 in `ceph pg dump`; then confirm with `crushtool --test`.
6. In the code, read the `pgtemp_primaryfirst` function and predict its output with your own example (8+3).

# Review questions {#sec-13-13}

1. What are the overhead and fault tolerance of EC 8+3 compared with three-way replication?
2. Why must every k×k submatrix of the generator matrix be invertible?
3. What is the difference between a shard in EC and a replica in replication?
4. Why were small writes expensive in old EC?
5. What mathematical property does parity delta rely on?
6. What are the limitations on enabling FastEC?
7. Why is the allow_ec_optimizations flag irreversible?
8. How do CLAY and LRC reduce recovery traffic?
9. What does the number 2147483647 in a PG mapping mean, and what are its common causes?
10. Why is the primary not always shard 0 in an optimized pool?

# Sources for this chapter {#sec-13-14}

- Erasure code: https://docs.ceph.com/en/latest/rados/operations/erasure-code/
- Erasure code profiles: https://docs.ceph.com/en/latest/rados/operations/erasure-code-profile/
- ISA plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-isa/
- LRC plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-lrc/
- CLAY plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-clay/
- SHEC plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-shec/
- Tentacle release notes: https://docs.ceph.com/en/latest/releases/tentacle/
- Source: src/erasure-code: https://github.com/ceph/ceph/tree/main/src/erasure-code
- Source: src/osd/ECTransaction.cc, ECSwitch.h, OSDMap.cc: https://github.com/ceph/ceph/tree/main/src/osd
- Intel ISA-L: https://github.com/intel/isa-l
- Plank, "A Tutorial on Reed-Solomon Coding for Fault-Tolerance in RAID-like Systems": https://web.eecs.utk.edu/~jplank/plank/papers/CS-96-332.pdf
