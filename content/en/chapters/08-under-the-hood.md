---
chapter: 8
id: ch08
title: 'Ceph Under the Hood: CRUSH, Maps, Authentication and PGs'
part: main
lang: en
---

::: {.tldr}

- CRUSH replaces a central lookup table: a hierarchy of buckets plus rules computes the OSDs of each PG, so clients find data themselves.
- An object hashes to a PG and the PG maps to OSDs in different failure domains; every change of the maps is versioned by an epoch.
- Tunables fix old CRUSH behaviours but change mappings, so enabling them moves data.
- cephx gives Kerberos-like mutual authentication with time-limited tickets; device classes put a pool on chosen OSDs.

```bash
ceph osd map rbd rbd_data.12ab.0000000000000004
```

[![The two placement stages: the object name is mapped to a PG by a hash, and CRUSH maps that PG to a set of OSDs](figures/ch08/f01_place.png)](#fig-08-f01_place)

:::

# Before you start {#sec-08-1}

## What questions does this chapter answer? {#sec-08-1-1}

So far we have seen Ceph from the outside: commands, services and interfaces. This chapter goes inside. Every important decision in designing and troubleshooting Ceph (why the data is where it is, why a PG is stuck, why a CRUSH rule does not work) comes back to a few basic mechanisms, which we examine in this chapter:

- How does data find its place without a central table?
- What structure does the CRUSH map have, and how do we write rules?
- What are tunables, and why does the "non-optimal tunables" warning appear?
- Which cluster maps are there, and how do the MONs stay available?
- How does cephx work, and how do we restrict capabilities?
- What is the path of a write from the client to the disk, and what states do PGs have?
- How do we place a pool on specific OSDs?

# Scaling without a central table {#sec-08-2}

## The placement problem {#sec-08-2-1}

Most older distributed storage systems had a metadata server or lookup table that said where each block was. At large scale this table has three problems: it becomes a performance bottleneck, it is a single point of failure, and it must be updated with every hardware change. Ceph has removed this table: **every client and every OSD computes the location of the data itself**. The inputs to this computation are only the object name, the pool id and the cluster map, which everyone has.

![The two placement stages: the object name is mapped to a PG by a hash, and CRUSH maps that PG to a set of OSDs](figures/ch08/f01_place.png){#fig-08-f01_place}

## The two mapping stages {#sec-08-2-2}

1. **Object to PG**: the object name is hashed, and its remainder modulo the pool's PG count (more precisely, with the stable mod algorithm) gives the PG number. A PG id combines the pool number and the PG number, such as `3.1f`.
2. **PG to OSD**: the CRUSH algorithm, given the PG id, the CRUSH map and the pool's rule, returns an ordered list of OSDs. The first active OSD is the **primary**.

```bash
ceph osd map rbd rbd_data.12ab.0000000000000004
# osdmap e1234 pool 'rbd' (3) object '...' -> pg 3.8c7e1b1f (3.1f) -> up ([12,4,27], p12) acting ([12,4,27], p12)
ceph pg map 3.1f
```

::: {.deep}
Why the intermediate PG layer? If we ran CRUSH directly on each object, the cluster would have to track replication, recovery and scrub state separately for each object; for billions of objects that is impossible. PGs divide objects into a few thousand groups, and all the data protection mechanisms (peering, log, recovery, scrub) work at the PG level. The PG count is a trade-off: too few and the distribution becomes uneven; too many and OSD memory and CPU and the peering load go up.
:::

## up and acting {#sec-08-2-3}

The `up set` is CRUSH's pure output. The `acting set` is the set that actually serves requests. The two are usually identical; a difference means Ceph is temporarily using other OSDs (for example **pg_temp** during backfill until the new OSD has all the data) or an explicit **upmap** has changed CRUSH's result for that PG.

# The CRUSH mechanism {#sec-08-3}

## The hierarchy {#sec-08-3-1}

![A sample CRUSH hierarchy: root, datacenter, rack, host and OSDs with device classes](figures/ch08/f02_hier.png){#fig-08-f02_hier}

The CRUSH map consists of two parts: the **hierarchy** (a tree of buckets showing the physical location of each OSD) and the **rules**, which say how to spread replicas across this tree. The default bucket types, from bottom to top, are osd, host, chassis, rack, row, pdu, pod, room, datacenter, zone, region and root. You do not need to use all of them; define only the levels that really are independent failure domains.

```bash
ceph osd crush tree --show-shadow
ceph osd crush add-bucket rack1 rack
ceph osd crush move rack1 root=default
ceph osd crush move ceph-node1 rack=rack1
ceph osd crush set-device-class nvme osd.20
ceph osd crush class ls
```

::: {.tip}
With cephadm you can set the host's CRUSH location in the host spec (`location: {rack: rack1}`) so that new OSDs land directly under the right rack. Otherwise every OSD goes under its host, directly under `root=default`, and after you move it by hand the data moves once more.
:::

## Weight {#sec-08-3-2}

Each OSD has a **CRUSH weight** (by default equal to its capacity in terabytes), and each bucket's weight is the sum of its children's weights. CRUSH spreads data in proportion to weight. There is also another weight called **reweight** (between 0 and 1) that used to be used to correct the distribution temporarily; today the balancer does this more precisely with upmap.

```bash
ceph osd crush reweight osd.20 3.49309     # permanent CRUSH weight
ceph osd reweight 20 0.9                   # temporary correction (prefer the balancer)
```

## The bucket algorithm {#sec-08-3-3}

CRUSH has an algorithm for choosing a child in each bucket. Today in practice only **straw2** is used (since Hammer, the default for new buckets). The key advantage of straw2 is that changing one item's weight moves data only between that item and the rest, not among the other items; that is, the minimum necessary movement.

## Rules {#sec-08-3-4}

A CRUSH rule defines the selection steps. Most of the time you do not need to write a rule by hand; the helper commands are enough:

```bash
# Replicated: replicas on different hosts, SSD only
ceph osd crush rule create-replicated rep-ssd-host default host ssd
# Replicated with a rack failure domain
ceph osd crush rule create-replicated rep-rack default rack
# EC from a profile
ceph osd erasure-code-profile set ec42-rack k=4 m=2 crush-failure-domain=rack crush-device-class=hdd
ceph osd crush rule create-erasure ec42-rack ec42-rack
ceph osd crush rule ls
ceph osd crush rule dump rep-ssd-host
```

For more complex cases, extract the map, edit it and test it before applying:

```bash
ceph osd getcrushmap -o crush.bin
crushtool -d crush.bin -o crush.txt
# edit crush.txt
crushtool -c crush.txt -o crush.new
crushtool -i crush.new --test --rule 1 --num-rep 3 --show-statistics --show-bad-mappings
ceph osd setcrushmap -i crush.new
```

An example of a hand-written rule that puts two replicas in one datacenter and the third in another datacenter:

```text
rule rep-2dc {
    id 5
    type replicated
    step take default
    step choose firstn 2 type datacenter
    step chooseleaf firstn 2 type host
    step emit
}
```

::: {.warn}
With `size=3` the rule above puts two replicas in the first datacenter and one in the second, but **which datacenter gets two replicas** differs for each PG. If you want both sites to be certain to hold a replica and writes to continue when one site is cut off, use **stretch mode** (chapter 18) instead of a hand-written rule; it also manages the quorum and min_size logic.
:::

::: {.note}
Squid added a new rule type called **MSR** (Multi-Step Retry) which, according to the release notes, enables more flexible EC configurations; its common use is controlled placement of several shards in one failure domain when the number of domains is less than `k+m`. Because this rule type is recorded in the CRUSH map, `require_min_compat_client` also applies to it; check your clients' versions before using it.
:::

## Device classes and the shadow tree {#sec-08-3-5}

Since Luminous each OSD has a **device class** (hdd, ssd, nvme or any name you like). CRUSH builds a shadow tree for each class, for example `default~ssd`, containing only the OSDs of that class. A rule with a class runs on that shadow tree. This feature replaces the old trick from the 2019 book of building two separate roots to separate SSDs and HDDs.

# Tunables {#sec-08-4}

## Why tunables? {#sec-08-4-1}

CRUSH was not perfect from the start. In some hierarchies (for example small trees, or when many OSDs are out) it could not find enough replicas for every PG, or it moved a lot of data for small changes. Fixing these behaviours changes the mapping result, so they could not be applied silently: every client must compute the same result the OSDs compute. Ceph's solution is **tunables**: flags in the CRUSH map that determine the algorithm's behaviour, grouped into **profiles** named after releases.

| Profile | Main feature | Minimum client kernel (per the documentation) |
|---|---|---|
| argonaut (legacy) | Original behaviour | All |
| bobtail (CRUSH_TUNABLES2) | Fewer failures to find a mapping and fixed retries | 3.9 |
| firefly (CRUSH_TUNABLES3) | Fixed chooseleaf behaviour with re-descent | 3.15 |
| hammer (CRUSH_V4) | straw2 bucket type | 4.1 |
| jewel (CRUSH_TUNABLES5) | chooseleaf_stable: less movement when an OSD goes out | 4.5 |

```bash
ceph osd crush show-tunables
ceph osd crush tunables optimal       # causes data movement!
ceph features                         # version and features of connected clients
ceph osd get-require-min-compat-client
```

::: {.warn}
Changing the tunable profile on a cluster full of data moves a large part of the data. Do it in off-peak hours, with a suitable mClock profile, and after making sure all clients are compatible (especially old kernel RBD and CephFS clients). Clusters built with recent releases have optimal tunables from the start, and this section matters mostly for old upgraded clusters.
:::

## The non-optimal warning {#sec-08-4-2}

If the cluster's tunables lag behind the optimal profile of the current release, the `OLD_CRUSH_TUNABLES` warning is shown. You can fix it by updating the tunables or, if you have old clients you cannot upgrade, silence it temporarily with `mon_warn_on_legacy_crush_tunables=false`. A similar warning, `OLD_CRUSH_STRAW_CALC_VERSION`, appears when the map still uses the old, buggy version of the weight calculation in straw buckets.

```bash
# convert straw buckets to straw2 with minimal movement
ceph osd crush set-all-straw-buckets-to-straw2
```

# Cluster maps and MONs {#sec-08-5}

![Cluster maps are kept in the MONs and versioned by epoch; clients and OSDs get the new map from the MON or from each other](figures/ch08/f03_maps.png){#fig-08-f03_maps}

## The maps {#sec-08-5-1}

The cluster state is kept in several maps, all versioned with an **epoch** (an increasing version number):

| Map | Contents | Command to view |
|---|---|---|
| MonMap | fsid, the list of MONs and their addresses | `ceph mon dump` |
| OSDMap | pools, OSDs and their up/in state, pg_temp and upmaps, flags and the CRUSH map | `ceph osd dump` |
| MgrMap | active MGR, standbys and modules | `ceph mgr dump` |
| FSMap | file systems and MDSs | `ceph fs dump` |
| PGMap | PG statistics (in the MGR, not the MON) | `ceph pg dump` |

::: {.deep}
OSDs do not necessarily get the new map from the MON: every message between OSDs and clients carries the sender's epoch, and the side with the newer map sends the changes (incrementals) to the other. This "gossip" reduces the load on the MONs. The practical consequence: an OSD that has been off for a while must process all the missed epochs when it comes up, and if the MONs keep old epochs (for example because the cluster has been unhealthy for a long time) the MON database grows.
:::

## MON availability {#sec-08-5-2}

MONs reach consensus with the **Paxos** algorithm: a map change is valid only when a majority of MONs (a quorum) accepts it. One MON is the **leader** and the rest are peons.

```bash
ceph mon stat
ceph quorum_status -f json-pretty
ceph mon dump
ceph tell mon.ceph-node1 mon_status
```

| Number of MONs | Majority needed | Failures tolerated |
|---|---|---|
| 1 | 1 | 0 |
| 3 | 2 | 1 |
| 5 | 3 | 2 |
| 7 | 4 | 3 |

::: {.warn}
An even number of MONs does not increase fault tolerance: four MONs also tolerate only one failure. MONs are sensitive to accurate time (the `MON_CLOCK_SKEW` warning); configure and monitor chrony or NTP on all nodes. Put the MON database (RocksDB) on SSD and monitor its disk space; when free space runs low, the `MON_DISK_LOW` warning and eventually a MON shutdown follow.
:::

::: {.note}
Umbrella added an optional **MON RocksDB backup and restore** mechanism (the `mon_backup_interval` setting, the `ceph tell mon.* backup` command and offline restore with `ceph-mon --restore-backup`). Before any risky operation on the MONs (removal, rebuild or a major upgrade), be aware of this option or of the documented methods for rebuilding the MON database; losing all MONs without a backup is Ceph's worst scenario.
:::

# Inside the code: placement, authentication and messaging {#sec-08-6}

## From object name to OSD {#sec-08-6-1}

![The three stages of mapping an object to an OSD: in the client the object name is hashed with ceph_str_hash and turned into a PG number with ceph_stable_mod; then the PG number is combined with the pool id and given to crush_do_rule as input x; finally the OSDMap removes non-existent OSDs and applies upmap and pg_temp to obtain the acting set and the primary](figures/ch08/s01_obj2osd.png){#fig-08-s01_obj2osd}

The first stage happens in `pg_pool_t::hash_key()` (`src/osd/osd_types.cc`): the object name, together with the namespace if there is one, is turned into a 32-bit number with the pool's hash function (rjenkins by default). This number is then mapped to the PG range with `ceph_stable_mod()`. This small function is one of the cleverest pieces of Ceph:

```c
/* from ceph/ceph, LGPL — src/include/rados.h (excerpt) */
static inline int ceph_stable_mod(int x, int b, int bmask)
{
	if ((x & bmask) < b)
		return x & bmask;
	else
		return x & (bmask >> 1);
}
```

`b` is the number of PGs and `bmask` is the smallest power of 2 minus one that is at least `b`. If pg_num is not a power of 2 (for example 12 with bmask=15), the values 12 to 15, which have no corresponding PG, are "folded" into the lower half (4 to 7). The important result: when pg_num grows from 12 to 13, only the objects that went to PG 5 and whose hash falls on 13 move; that is, PG splitting is **local** and the data is not all reshuffled. This property is what made gradual pg_num increases (since Nautilus) possible.

::: {.note}
For this reason, when pg_num is not a power of 2, PG sizes are unequal: the "folded" PGs have roughly twice as much data. This is one of the reasons for the power-of-2 recommendation and for the autoscaler's behaviour (chapter 19).
:::

In the lab below you can follow these three stages for any object name, down to every CRUSH draw in every bucket.

::: {.sim name="placement"}
:::

## straw2: choosing by drawing exponential lots {#sec-08-6-2}

![The straw2 algorithm in three stages: for each bucket item a sixteen-bit pseudo-random number is built from the input hash, the item id and the attempt number, and its natural logarithm is computed with a table and divided by the weight; the item with the largest value is chosen, which is mathematically equivalent to picking the minimum of exponential variables with rate equal to the weight and makes each item's selection probability exactly proportional to its weight; the consequence is minimal data movement when weights change](figures/ch08/s02_straw2.png){#fig-08-s02_straw2}

`bucket_straw2_choose()` in `src/crush/mapper.c` computes a "draw" for each bucket item and chooses the largest. The core of the computation:

```c
/* from ceph/ceph, LGPL — src/crush/mapper.c, generate_exponential_distribution() (excerpt) */
unsigned int u = crush_hash32_3(type, x, y, z);
u &= 0xffff;
__s64 ln = crush_ln(u) - 0x1000000000000ll;
return div64_s64(ln, weight);
```

The mathematics behind it (in this book's words): suppose U is uniform on (0, 1]. Then `−ln(U) / w` is an exponential variable with rate w. The minimum of several independent exponential variables with rates w₁ to wₙ belongs to item i with probability `wᵢ / Σw`. Because ln(U) is negative, `ln(U)/w` is largest for the same item for which `−ln(U)/w` is smallest. Therefore:

```text
draw_i = ln(u_i / 65536) / w_i          (u_i = hash(x, id_i, r) mod 2^16)
choose argmax_i draw_i   ⇒   P(i) = w_i / Σ_j w_j
```

`crush_ln()` approximates the logarithm with fixed-point tables (no floating point, because the same code also runs in the Linux kernel); its output is in the range [0, 2⁴⁸), and subtracting 2⁴⁸ turns it into the negative value equivalent to ln(u/65536). Weights are in 16.16 fixed-point format (0x10000 means 1.0).

::: {.deep}
Why does straw2 minimise movement? Each item's draw depends only on its own hash and **its own weight**. If item A's weight increases, only its draw grows; PGs that had already chosen A still choose A and some other PGs move to A, but no PG moves between two other items (B and C). In the old straw algorithm the length of the "straws" depended on the weights of all items and this property did not hold; that is why straw2 was introduced in Hammer and later became the default.
:::

::: {.sim name="crush"}
:::

## Retrying: collision and reject {#sec-08-6-3}

`crush_choose_firstn()` descends through a bucket for each replica (rep) until it reaches the desired type. If the chosen item has already been chosen (**collide**) or the OSD is out or overfull (**reject**), the `ftotal` counter is incremented and the choice is repeated with `r' = r + ftotal`, up to the `choose_total_tries` limit (a tunable, default 50 in the newer profiles).

```text
pseudocode: crush_choose_firstn (this book's summary)
  for rep in 0..numrep-1:
      ftotal = 0
      loop:
          r = rep + ftotal
          item = descend(bucket, x, r) until type matches     # straw2 at each level
          collide = item in out[0..rep-1]
          reject  = is_out(item, x) or (chooseleaf and leaf selection failed)
          if not collide and not reject: out[rep] = item; break
          ftotal += 1
          if ftotal >= choose_total_tries: give up on this rep
```

The `is_out()` function is interesting: an OSD with a reweight between 0 and 1 is rejected **probabilistically**; `hash(x, item) & 0xffff` is compared with the reweight value (16.16). So `ceph osd reweight 12 0.8` means that about 20% of the PGs CRUSH gave to osd.12 go to another OSD after a retry. This is why reweight differs from the CRUSH weight (which changes the share in straw2).

::: {.tip}
`crushtool --test` runs the same code outside the cluster. To see the effect of a change before applying it: `ceph osd getcrushmap -o cm`, edit, then `crushtool -i cm --test --show-statistics --rule 0 --num-rep 3 --min-x 0 --max-x 100000`, and compare `--show-mappings` before and after.
:::

## cephx: tickets and rotating keys {#sec-08-6-4}

![The cephx authentication flow: by proving knowledge of the shared key, the client gets a session key and an auth ticket from the MON, then obtains a service ticket for the OSD service encrypted with that service's rotating key; the OSD, which has received the rotating keys from the MON, decrypts the ticket, checks its expiry and caps, and replies so that mutual authentication is complete](figures/ch08/s03_cephx.png){#fig-08-s03_cephx}

The main structures are defined in `src/auth/cephx/CephxProtocol.h`: `CephXServerChallenge`, `CephXAuthenticate`, `CephXTicketBlob`, `CephXServiceTicket`, `CephXServiceTicketInfo` and `CephXAuthorizer`. The three main request types are identified by the constants `CEPHX_GET_AUTH_SESSION_KEY` (0x0100), `CEPHX_GET_PRINCIPAL_SESSION_KEY` (0x0200) and `CEPHX_GET_ROTATING_KEY` (0x0400).

- The client's shared key is never sent over the network; the client only proves that it has it (by answering a challenge).
- The service ticket is encrypted with the service's **rotating key**, which the MON changes periodically and the OSDs fetch; so the OSD does not need to contact the MON to check a ticket.
- Ticket lifetimes are controlled by `auth_mon_ticket_ttl` (default 72 hours) and `auth_service_ticket_ttl` (default 1 hour); the client renews before expiry.

::: {.warn}
Because tickets expire, **clock skew** between the client, MON and OSD can break authentication. Messages such as "could not get service secret", or authentication errors after rebooting a host with a wrong clock, are often caused by this. NTP/chrony on all hosts and clients is mandatory.
:::

::: {.sim name="cephx"}
:::

## msgr2: frames and secure mode {#sec-08-6-5}

![The frame structure in the msgr2 protocol: a fixed-size preamble containing the frame type tag, the number of segments up to four, the length and alignment of each segment and a separate CRC; then up to four segments containing the header, front, middle and data; and finally the epilogue, which in crc mode holds each segment's CRC and in secure mode the AES-GCM encryption and authentication of the whole frame](figures/ch08/s04_msgr2.png){#fig-08-s04_msgr2}

In `src/msg/async/frames_v2.h`, each frame starts with a `preamble_block_t` holding the tag (`enum class Tag`: HELLO, AUTH_REQUEST, AUTH_REQUEST_MORE, ..., SESSION_RECONNECT, MESSAGE, KEEPALIVE2, COMPRESSION_REQUEST and so on), the number of segments (at most `MAX_NUM_SEGMENTS = 4`) and the length and alignment of each segment. Separating the data segment with a specific alignment lets the data buffer reach BlueStore directly without copying (zero-copy).

```bash
ceph config get mon ms_cluster_mode          # crc or secure (and the order of preference)
ceph config get mon ms_service_mode
ceph config get mon ms_client_mode
ceph config set global ms_cluster_mode "secure"   # encrypt traffic between OSDs
ceph mon dump | grep -E "v2:|v1:"                 # the addresses of the two protocols
```

::: {.note}
`secure` mode costs CPU, but on processors with AES-NI it is usually tolerable. Before enabling it on a busy cluster network, measure the effect in a lab. The default msgr2 port on the MON is 3300 and msgr1 is 6789.
:::

# Data movement by the numbers: adding a host and changing a weight {#sec-08-7}

This section answers two practical questions with real CRUSH mappings: "how much data moves when a host is added?" and "what moves when an OSD's weight changes?". The map was built with `crushtool --build --num_osds 132 … host straw2 12 root straw2 0`. The ten-host version of the same map was obtained with `--remove-item` so that the ids of all buckets and OSDs stay fixed, because straw2 uses the item id in the hash. A three-replica pool with 8192 PGs was defined with `osdmaptool --createsimple 256 --pg-bits 5 --pgp-bits 5`, and the mapping of each case was taken with `--test-map-pgs-dump`. The tools were from Ceph 18.2.7 and the tunables were the defaults: `chooseleaf_vary_r 1`, `chooseleaf_stable 1` and `choose_total_tries 50`.

::: {.note}
A trap in osdmaptool: the `--mark-up-in` option gives a weight of 1.0 to every OSD with a CRUSH weight of zero (src/tools/osdmaptool.cc, the `if (mark_up_in)` block with `adjust_item_weightf(…, 1.0)`). So to simulate "the host has not been added yet" you cannot set the OSDs' weight to zero; you must remove them from the map. We made exactly this mistake at first and saw no movement at all.
:::

## Adding a host {#sec-08-7-1}

::: {.algo #alg-08-1 title="Counting movement by comparing two mappings" src="osdmaptool --test-map-pgs-dump before and after the change; bucket_straw2_choose and crush_choose_firstn in src/crush/mapper.c" complexity="O(pg_num × size)"}
:::

```text
pseudocode
A = up(pg) with the old map ; B = up(pg) with the new map          # for each pg in [0, pg_num)
moved = Σ_pg |set(B[pg]) − set(A[pg])|                         # new placements, ignoring order
to_new = Σ_pg |{o ∈ B[pg] − A[pg] : o on the new host}|
ideal = pg_num × size × (new host weight / total weight)               # 24576 × 12/132
```

**Result.** Of 24576 replica placements, 2184 (8.89%) went to the new host. The ideal is 2234 (9.09%). This is exactly the behaviour straw2 guarantees: each item has an independent "draw" `ln(u)/w` (the `generate_exponential_distribution` function), and adding an item changes the winner only where the new item's draw is higher.

But another 328 placements (1.33%) moved between old OSDs. A real example from this mapping: PG `1.58` went from `[76, 113, 46]` to `[76, 125, 116]`. The new host took the second position and host 9 was pushed to the third. In `crush_choose_firstn` the leaf within a host is chosen with `sub_r = r >> (vary_r − 1)`, i.e. it depends on the position's r. So within the same host 9, osd.116 was chosen instead of osd.113. The practical consequence is that adding capacity causes about 15% more movement than the ideal (2512 versus 2234). Take this into account when estimating backfill time.

![Adding an eleventh host (12 OSDs) to a 10 × 12 cluster with straw2, a three-replica pool and 8192 PGs, measured with osdmaptool. Grey is the ideal share, green the replicas that went to the new host, and orange the movement between old OSDs caused by the position's r changing in chooseleaf](figures/ch08/f07_addhost.png){#fig-08-f07_addhost}

## Changing an OSD's weight {#sec-08-7-2}

::: {.algo #alg-08-2 title="Classifying movements after a reweight" src="crushtool --reweight-item (also updates the parents' weights); the same A and B comparison" complexity="O(pg_num × size)"}
:::

```text
pseudocode
for each new placement y ∈ B[pg] − A[pg]:
    if osd.5 is the incoming or outgoing OSD of this PG      → "osd.5 itself"
    else if the incoming or outgoing OSD is on host0       → "other OSDs of host0"   (host0's weight in root changed)
    else                                          → "unrelated hosts"   (position/r shift)
```

**Result.** When osd.5's weight goes from 1.0 to 2.0, 411 placements change: 214 are osd.5 itself, 169 are other OSDs of host0 and 28 are unrelated hosts. When the weight drops to 0.8, 84 placements change: 42, 40 and 2.

The large "other OSDs of host0" share is not a flaw of straw2. `crushtool --reweight-item` also raises host0's weight in the root from 12 to 13, and host0 gets a larger share of the PGs. straw2 spreads this share within host0 in the ratio 2/13 for osd.5 and 1/13 for each other OSD.

In this experiment the old straw algorithm gave almost the same result (400 versus 411 for weight 2.0), because all items but one had equal weights. The documented flaw of old straw (movement between the other items of the same bucket when one item's weight changes) shows up in buckets with unequal weights. Even so, straw2 is the only algorithm that guarantees this property for any weight distribution.

::: {.tip}
Before any weight change or host addition on a real cluster, do the same comparison offline: `ceph osd getmap -o om`, then `osdmaptool om --export-crush cm`, change cm with crushtool, `osdmaptool om --import-crush cm2` on a copy, and compare the two `--test-map-pgs-dump` outputs. In this case `--mark-up-in` is not needed, because the real osdmap has the up and in state.
:::

![Changing the CRUSH weight of one OSD (osd.5 on host0) from 1.0 to five values and classifying the moved placements: blue is osd.5 itself, yellow the other OSDs of host0, which gain or lose share as the host's weight changes, and red unrelated hosts. Left straw2 and right old straw, with 8192 PGs, measured with osdmaptool](figures/ch08/f08_reweight.png){#fig-08-f08_reweight}

# Authentication and authorisation {#sec-08-8}

## cephx {#sec-08-8-1}

Ceph uses the **cephx** protocol for mutual authentication between clients and daemons. Its idea is similar to Kerberos: the secret key is never sent over the network, and the MON, as the authority, issues time-limited **tickets** with which the client talks directly to OSDs and MDSs.

![The cephx flow: the client proves its identity to the MON, gets a ticket and uses it to work directly with the OSD](figures/ch08/f04_cephx.png){#fig-08-f04_cephx}

::: {.deep}
If every I/O request went to the MON for an authorisation check, the MONs would become a bottleneck. With tickets, the OSD checks a ticket's validity using only its own service key (obtained from the MON and rotated periodically). This is also why clock skew between nodes can lead to authentication errors: tickets expire.
:::

## Users and capabilities {#sec-08-8-2}

Every identity in Ceph has the form `type.id` (for example `client.backup` or `osd.3`) and has a key and a set of capabilities. Capabilities are defined separately for each daemon type:

```bash
ceph auth ls
ceph auth get client.admin
# a user for RBD in one pool only
ceph auth get-or-create client.vmhost mon 'profile rbd' osd 'profile rbd pool=vms' mgr 'profile rbd pool=vms'
# a read-only user for monitoring
ceph auth get-or-create client.monitor mon 'allow r' mgr 'allow r'
# a user restricted to one namespace
ceph auth get-or-create client.tenant1 mon 'allow r' osd 'allow rw pool=shared namespace=tenant1'
ceph auth caps client.vmhost mon 'profile rbd' osd 'profile rbd pool=vms, profile rbd-read-only pool=images'
ceph auth rm client.old-app
```

::: {.tip}
Always use **profiles** (`profile rbd`, `profile rbd-read-only`, `profile crash`, `profile bootstrap-osd`) instead of writing low-level capabilities by hand. Profiles also include the capabilities needed for operations such as blocklisting the previous client (for the exclusive-lock in RBD), which are usually forgotten in hand-written capabilities.
:::

## Key rotation and encryption {#sec-08-8-3}

- A user's key can be rotated with `ceph auth rotate` (in recent releases) or by creating a new key and replacing it gradually.
- Umbrella hardened cephx: the new **AES256KRB5** cipher became the default in place of older key types, and online key rotation was added. Before upgrading, check the compatibility of old clients (especially kernel clients).
- To encrypt network traffic, enable `secure` mode in **msgr2** (`ms_cluster_mode`, `ms_service_mode`, `ms_client_mode`). This mode has CPU overhead; measure it on real hardware.

```bash
ceph config set global ms_client_mode secure
ceph config set global ms_service_mode secure
ceph config get mon ms_cluster_mode
```

# The I/O path and PGs {#sec-08-9}

## The path of a write {#sec-08-9-1}

![A write to a replicated pool: the client talks only to the primary; the primary replicates to the secondaries in parallel and acks after all replicas have committed](figures/ch08/f05_write.png){#fig-08-f05_write}

1. The client (librados) computes the PG and the primary with the map it has.
2. It sends the request only to the **primary**.
3. The primary records the operation in that PG's log and sends it to the secondaries in parallel.
4. Each OSD commits the transaction in BlueStore.
5. The primary acks the client after receiving confirmation from **all** OSDs in the acting set.

So write latency equals the slowest OSD in the acting set plus two network round trips. This is why one slow disk slows down the whole cluster (chapter 17). In an EC pool the primary splits the data into k data chunks and m parity chunks and sends each chunk to one OSD (chapter 13).

::: {.note}
By default reads are served by the primary. RBD and RGW clients can, under certain conditions, read from the nearest replica (for example the `rbd_read_from_replica_policy` option with the values balance and localize), which is useful in clusters stretched across sites.
:::

## PG states {#sec-08-9-2}

![The main PG states and the common transitions between them](figures/ch08/f06_pgstates.png){#fig-08-f06_pgstates}

| State | Meaning | Worrying? |
|---|---|---|
| active+clean | All replicas present and in sync | No; the desired state |
| peering | OSDs agreeing on the PG's state | Only if it takes long |
| degraded | Some objects lack enough replicas | Higher risk until recovery completes |
| recovering | Synchronising from the log | Normal after a short failure |
| backfilling, backfill_wait | Full copy of the PG to a new OSD | Normal after a map change |
| remapped | The acting set temporarily differs from the up set | Normal during backfill |
| undersized | Fewer OSDs than size | Should be checked |
| inconsistent | Scrub found an inconsistency | Yes; must be investigated and repaired |
| incomplete, down | Not enough valid copies to become active | Yes; I/O to this PG is stopped |
| stale | The primary has not sent stats for a while | Yes; check the OSDs |

```bash
ceph pg stat
ceph pg dump_stuck inactive
ceph pg dump_stuck unclean
ceph pg ls degraded
ceph pg 3.1f query | jq '.recovery_state'
```

::: {.debug}
For a PG stuck in peering or incomplete, read the output of `ceph pg <id> query` from the bottom up. The `recovery_state` section usually says which OSD it is waiting for (`blocked_by` or `down_osds_we_would_probe`). If that OSD is lost for good, decisions such as `ceph osd lost` or marking objects as lost risk data loss; read chapter 17 before running them.
:::

## min_size and size {#sec-08-9-3}

`size` is the number of replicas and `min_size` is the minimum number of healthy replicas a PG needs to accept I/O. For a three-way replicated pool, `min_size=2` is standard. Lowering it to 1 keeps the cluster "available" during a failure but sharply raises the risk of data loss, because a write might exist on only one disk.

# A pool on specific OSDs {#sec-08-10}

The modern way to place a pool on a specific group of OSDs is the **device class**. If the default classes are not enough (for example you want to set aside the NVMe disks of a particular model for one tenant), define a custom class:

```bash
for id in 30 31 32 33 34 35; do
  ceph osd crush rm-device-class osd.$id
  ceph osd crush set-device-class fastnvme osd.$id
done
ceph osd crush rule create-replicated fast-host default host fastnvme
ceph osd pool create tenant-a-db 64 64 replicated fast-host
ceph osd pool application enable tenant-a-db rbd
ceph pg ls-by-pool tenant-a-db | head
```

::: {.tip}
In the cephadm OSD spec you can also set `crush_device_class` so that new OSDs get the right class from the start and you do not need to rerun the commands above.
:::

## Primary on SSD, replicas on HDD: pattern and pitfall {#sec-08-10-1}

Some clusters put SSD and HDD OSDs in one replicated pool so that reads come from SSD and capacity comes from HDD. The official CRUSH documentation describes two ways to do this.

- **Primary affinity.** Every OSD has a primary affinity between 0 and 1, and the default is 1. With `ceph osd primary-affinity <osd> 0` on the HDD OSDs, CRUSH avoids them as primaries. In the code (`OSDMap::_apply_primary_affinity`), the up set is walked in order, and an OSD with a lowered affinity is skipped as primary for a share of its PGs that depends on a hash of the PG seed and the OSD id. If every OSD in the set is skipped, the first skipped one becomes the primary anyway, so a PG with no SSD in its set still gets an HDD primary.
- **A rule that takes an SSD first.** The rule first takes one host from class `ssd` and then the remaining copies from class `hdd`.

```text
rule mixed_replicated_rule {
    id 11
    type replicated
    step take default class ssd
    step chooseleaf firstn 1 type host
    step emit
    step take default class hdd
    step chooseleaf firstn 0 type host
    step emit
}
```

```bash
ceph osd primary-affinity osd.12 0     # an HDD OSD: avoid it as primary
ceph osd tree                          # the PRI-AFF column shows the value
ceph pg ls-by-primary osd.12 | head    # should now be (almost) empty
```

The pitfalls of this pattern:

1. **Writes do not get faster.** The primary acknowledges a write only after every replica has committed it (the write path earlier in this chapter), so write latency still follows the slowest HDD replica. Only reads, which the primary serves, gain.
2. **Hosts can be shared.** In the rule above, the SSD and one of the HDDs can sit on the same host. The documentation notes that for an N-times replicated pool the rule selects N+1 OSDs for this reason. The alternative is separate SSD and HDD hosts under separate roots, with `firstn -1` in the second step; then every client request lands on the SSD hosts, which need the faster CPUs.
3. **When the SSD fails, reads move to an HDD.** Until the replacement SSD has the PG's data, its requests are served by a slower HDD OSD.
4. **The read balancer respects the value.** In Reef and later, the read balancer weighs each OSD's target share of primaries by its primary affinity (`OSDMap::calc_desired_primary_distribution`), so it does not undo the setting.

::: {.tip}
A separate pool for each device class is usually the better design: a `ssd` rule for hot data (a database RBD image, the RGW index pool) and an `hdd` rule for bulk data. Both reads and writes then have predictable latency, a failure stays inside one class, and capacity is reported per pool. Keep the mixed pattern for a read-heavy pool when the SSDs cannot hold a full copy of the data.
:::

::: {.summary title="SRE notes for this chapter"}

- Data location is computed, not looked up; `ceph osd map` is your first tool.
- Define only real failure domains in CRUSH, and give the host location in the spec.
- Run `crushtool --test` before applying any hand-edited map.
- Use device classes for SSD/HDD, not separate roots.
- A tunable change means a large movement; check client compatibility with `ceph features`.
- An odd number of MONs (3 or 5), on SSD, with accurate clocks.
- Capabilities with profiles and least privilege; do not lower min_size.

:::

# Supplementary and up to date {#sec-08-11}

- **Device classes and the shadow tree** (Luminous) replaced the separate SSD/HDD roots seen in older sources.
- **upmap and the balancer** have replaced manual reweighting (chapter 7).
- **The MSR rule** (Squid) gives more flexibility for EC.
- **cephx in Umbrella**: the AES256KRB5 cipher as the default and online key rotation.
- **MON RocksDB backup** (Umbrella).
- **The read balancer** (Reef) for distributing primaries.

# Hands-on exercise {#sec-08-12}

1. Run `ceph osd map` for three different objects and compare the PG and OSD paths with `ceph pg map`.
2. Build a two-rack hierarchy, move the hosts, and apply the `rep-rack` rule to a test pool. Observe the amount of movement.
3. Extract the CRUSH map, add the two-datacenter rule, and check the distribution with `crushtool --test` before applying it.
4. Create a user with `profile rbd` for one pool only and prove that it has no access to another pool.
5. Stop an OSD and record the PG states over time with `ceph pg stat`.
6. Using a custom device class, create a pool on three specific OSDs and check the PG distribution.

# Review questions {#sec-08-13}

1. What are the two stages of mapping an object to an OSD, and why is the PG needed?
2. What is the difference between the up set and the acting set?
3. What is the advantage of straw2 over the earlier algorithms?
4. Why does changing tunables cause data movement, and what must be checked beforehand?
5. Why do four MONs not tolerate more failures than three?
6. Where do OSDs receive the new map from?
7. Why does cephx use tickets?
8. Why does write latency depend on the slowest OSD in the acting set?
9. How do the incomplete and inconsistent states differ?
10. What is the recommended way to place a pool on specific OSDs?

# Sources for this chapter {#sec-08-14}

- CRUSH maps: https://docs.ceph.com/en/latest/rados/operations/crush-map/
- CRUSH map edits: https://docs.ceph.com/en/latest/rados/operations/crush-map-edits/
- Placement groups: https://docs.ceph.com/en/latest/rados/operations/placement-groups/
- PG states: https://docs.ceph.com/en/latest/rados/operations/pg-states/
- Monitoring OSDs and PGs: https://docs.ceph.com/en/latest/rados/operations/monitoring-osd-pg/
- User management: https://docs.ceph.com/en/latest/rados/operations/user-management/
- Cephx config: https://docs.ceph.com/en/latest/rados/configuration/auth-config-ref/
- Messenger v2: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- Architecture: https://docs.ceph.com/en/latest/architecture/
- Health checks: https://docs.ceph.com/en/latest/rados/operations/health-checks/
- Read balancer: https://docs.ceph.com/en/latest/rados/operations/read-balancer/
- Source: src/osd/OSDMap.cc: https://github.com/ceph/ceph/blob/main/src/osd/OSDMap.cc
- Squid release notes: https://docs.ceph.com/en/latest/releases/squid/
- Umbrella release notes: https://docs.ceph.com/en/latest/releases/umbrella/
- Weil et al., CRUSH (SC 2006): https://ceph.io/assets/pdfs/weil-crush-sc06.pdf
