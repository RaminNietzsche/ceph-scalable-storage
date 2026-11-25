---
chapter: 37
id: ch37
title: 'Specialist Part (4): RBD — Layout on RADOS, Striping, Object Map and Fast-Diff, and the rbd Reference'
part: specialist
lang: en
---

::: {.tldr}

- A format 2 image is `rbd_id`, an `rbd_header.<id>` omap and data objects `rbd_data.<id>.<objectno>`; metadata changes only through the rbd class.
- Default striping is consecutive 4 MiB objects; custom striping spreads small sequential writes round-robin over `stripe_count` objects.
- The object map keeps two bits per object, so fast-diff and `rbd du` need not query every object.
- The chapter ends with an rbd command reference.

```bash
rados -p rbd listomapkeys rbd_header.5f3a2b8c1d4e
```

[![The layout of an RBD image with a separate data pool: header, directory, object map and data objects](figures/ch37/f01_layout.png)](#fig-37-f01_layout)

:::

# Before we begin {#sec-37-1}

Chapter 2 showed which objects a format 2 image has and how its id is generated (algorithm 2-1). This chapter opens that same layout key by key: exactly which omap keys an image header has, what the pool-level objects (`rbd_directory`, `rbd_trash`, `rbd_mirroring`, `rbd_namespace` and others) hold, how striping with `stripe_unit` and `stripe_count` maps an offset to an object, how the object map packs and stores its bits, and how fast-diff finds the changes between two snapshots without reading data. The chapter ends with a complete reference for the `rbd` command and `rbd-nbd`. Names have been checked against the main branch of the ceph/ceph repository (November 2026).

## What questions does this chapter answer? {#sec-37-1-1}

- What keys does an image header have, and who writes each of them?
- How does the data object name differ with a separate data pool?
- With `stripe_unit=64K` and `stripe_count=4`, which object holds offset 1000000?
- How many bits does the object map keep per object, and in what order are the bytes on disk?
- What does `EXISTS_CLEAN` mean, and when is it set?
- Which states does fast-diff use to detect a change?
- How are pools, namespaces, the trash and groups indexed in RADOS?

## Prerequisites {#sec-37-1-2}

Chapter 2 (RBD), chapter 15 (cls), chapters 34 and 36 (omap, SnapContext and clones).

# The objects of an image {#sec-37-2}

## The header {#sec-37-2-1}

All the metadata of a format 2 image is in the omap of the object `rbd_header.<id>` and changes only through the methods of the `rbd` class (`src/cls/rbd/cls_rbd.cc`):

| omap key | Type | Content |
|---|---|---|
| `size` | u64 | the image size in bytes |
| `order` | u8 | the binary logarithm of the object size (22 means 4 MiB) |
| `object_prefix` | string | the prefix of the data objects, for example `rbd_data.5f3a2b8c1d4e` |
| `features` | u64 | the feature bits (next table) |
| `flags` | u64 | `OBJECT_MAP_INVALID` (1) and `FAST_DIFF_INVALID` (2) |
| `op_features` | u64 | operational features such as clone-parent, clone-child, group, snap-trash |
| `snap_seq` | u64 | the largest snap id created for this image |
| `snapshot_<id:016x>` | cls_rbd_snap | the name, size, parent, flags and namespace of each snapshot |
| `snap_children_<id:016x>` | set | the format 2 clone children on that snapshot |
| `parent` | cls_rbd_parent | the parent's pool, namespace, image and snap, and the overlap (for a clone) |
| `stripe_unit`, `stripe_count` | u64 | only if striping is custom |
| `data_pool_id` | s64 | only if there is a separate data pool |
| `create_timestamp`, `access_timestamp`, `modify_timestamp` | utime | timestamps |
| `snap_limit` | u64 | the cap on the number of snapshots |
| `metadata_<key>` | string | image metadata; for example `conf_rbd_cache` for per-image settings |
| `migration` | cls_rbd_migration | the live-migration state |

Besides the omap, the xattr `lock.rbd_lock` (the `lock` class) holds the advisory lock that ManagedLock uses for exclusive-lock (chapter 38). This same header object is the watch target of all clients that have the image open.

| Feature | Bit | Default |
|---|---|---|
| `layering` | 1 | yes |
| `striping` | 2 | only if the stripe is custom |
| `exclusive-lock` | 4 | yes |
| `object-map` | 8 | yes |
| `fast-diff` | 16 | yes |
| `deep-flatten` | 32 | yes |
| `journaling` | 64 | no |
| `data-pool` | 128 | only if `--data-pool` is given |
| `operations` | 256 | internal |
| `migrating` | 512 | internal |
| `non-primary` | 1024 | internal, for a mirror destination image |
| `dirty-cache` | 2048 | internal, for the PWL persistent cache |

The default sum (`rbd_default_features`) is 1+4+8+16+32 = 61.

## Data objects and the object map {#sec-37-2-2}

Data objects are named `<object_prefix>.<objectno:016x>`. If the image is created with `--data-pool`, the header and metadata stay in the main pool (which must be replicated) and the data is written to the second pool (often EC with `allow_ec_overwrites`). In this case the prefix includes the main pool's id: `rbd_data.<metadata-pool-id>.<image-id>`, so that objects of images from several different pools do not collide in a shared data pool.

The object map is stored in the object `rbd_object_map.<id>` for the head and `rbd_object_map.<id>.<snapid:016x>` for each snapshot.

## Pool-level objects {#sec-37-2-3}

| Object | omap or data | Use |
|---|---|---|
| `rbd_id.<name>` | data: the image id | finding the id from the name |
| `rbd_directory` | `name_<name>` → id and `id_<id>` → name | the list of images in the pool or namespace |
| `rbd_trash` | `id_<id>` → name, deletion time, earliest restore time, source | images in the trash |
| `rbd_children` | key: parent spec, value: children | only for format 1 clones |
| `rbd_info` | the omap `conf_<option>` and a pool validation marker | pool-level settings (`rbd config pool set`) and the result of checking overwrite support in the data pool |
| `rbd_namespace` | `name_<ns>` | the list of the pool's namespaces |
| `rbd_mirroring` | `mirror_mode`, `mirror_uuid`, `mirror_peer_<uuid>`, `image_<id>`, `global_<gid>`, `status_global_<gid>`, `instance_<id>`, `image_map_<gid>` | the mirroring state (chapter 39) |
| `rbd_group_directory` and `rbd_group_header.<id>` | omap | consistency groups |
| `rbd_task` | omap | the mgr's background task queue (`rbd task add flatten` and the like) |

A **namespace** in RBD is the same as a namespace in RADOS (chapter 34). All the objects listed above are created separately in each namespace. With the cap `profile rbd pool=P namespace=N` a client can be restricted to one namespace without creating a separate pool for each tenant.

```bash
# example: reading the header directly (for inspection only; never change it with rados)
rados -p rbd listomapkeys rbd_header.5f3a2b8c1d4e
rados -p rbd getomapval rbd_header.5f3a2b8c1d4e object_prefix
```

```text
example (output):
access_timestamp
create_timestamp
features
flags
modify_timestamp
object_prefix
order
size
snap_seq
snapshot_0000000000000004
value (25 bytes) :
00000000  15 00 00 00 72 62 64 5f  64 61 74 61 2e 35 66 33  |....rbd_data.5f3|
00000010  61 32 62 38 63 31 64 34  65                       |a2b8c1d4e|
```

The first four bytes (`15 00 00 00`, that is 21) are the string length in little-endian; all strings in Ceph's encoding have this format.

![The layout of an image with a separate data pool. The replicated metadata pool holds rbd_id, rbd_directory, the header and the object maps, and the EC data pool holds the rbd_data objects prefixed with the metadata pool's id. Clients watch the header, and the exclusive lock is on an xattr of that same header](figures/ch37/f01_layout.png){#fig-37-f01_layout}

# Striping {#sec-37-3}

By default `stripe_unit` equals the object size and `stripe_count` is 1, so the image is simply divided into consecutive 4 MiB pieces. With custom striping, data is spread **round-robin** across `stripe_count` objects, so that small sequential writes go to several OSDs at once.

::: {.algo #alg-37-1 title="Mapping an image offset to (object, offset within the object)" src="src/osdc/Striper.cc :: Striper::file_to_extents" complexity="O(len / stripe_unit) pieces"}
:::

```text
pseudocode
su = stripe_unit ; sc = stripe_count ; os = object_size
if sc == 1: su = os
stripes_per_object = os / su
while left > 0:
    blockno     = cur / su
    stripeno    = blockno / sc
    stripepos   = blockno % sc
    objectsetno = stripeno / stripes_per_object
    objectno    = objectsetno * sc + stripepos
    x_offset    = (stripeno % stripes_per_object) * su + cur % su
    x_len       = min(su - cur % su, left)
    emit (objectno, x_offset, x_len) ; cur += x_len ; left -= x_len
```

**Numerical example.** `object_size = 4 MiB`, `stripe_unit = 64 KiB`, `stripe_count = 4`, a write of 300000 bytes from offset 1000000. Each object has 64 stripes and one "object set" of 4 objects covers 16 MiB.

| block | stripe | stripepos | object | offset within object | length |
|---|---|---|---|---|---|
| 15 | 3 | 3 | 3 | 213568 | 48576 |
| 16 | 4 | 0 | 0 | 262144 | 65536 |
| 17 | 4 | 1 | 1 | 262144 | 65536 |
| 18 | 4 | 2 | 2 | 262144 | 65536 |
| 19 | 4 | 3 | 3 | 262144 | 54816 |

The 300 KB write reaches all four objects. With default striping, the same write would touch only object 0 (offsets 1000000 to 1300000). Striping helps a single-stream sequential load with a low queue depth, but for a random 4K load it only increases the number of objects involved. krbd supports custom striping from kernel 4.17 (chapter 29).

![Striping with stripe_unit=64K and stripe_count=4. Each row is a stripe and the four columns are the four objects of an object set. Blocks 15 to 19, which make up the example write, are colored](figures/ch37/f02_striping.png){#fig-37-f02_striping}

::: {.sim name="striping"}
:::

The lab below follows the same objects one step further, to their PGs and OSDs, together with the image's header, id and object-map objects.

::: {.sim name="placement" mode="rbd"}
:::

# The object map {#sec-37-4}

## States and bit packing {#sec-37-4-1}

The object map has 2 bits per object (`BitVector<2>`):

| Value | Constant | Meaning |
|---|---|---|
| 0 | `OBJECT_NONEXISTENT` | the object does not exist; a read returns zeros and there is no need to go to the OSD |
| 1 | `OBJECT_EXISTS` | the object exists and has changed since the last snapshot |
| 2 | `OBJECT_PENDING` | a deletion is in progress (discard or resize) |
| 3 | `OBJECT_EXISTS_CLEAN` | the object exists and has **not** changed since the last snapshot |

Each byte holds four objects, and **the object with the lower number is in the higher bits**: `shift = (3 − objectno % 4) × 2`. The on-disk encoding has three parts: a header (length, version and element count), the raw data, and a footer containing the crc32c of the header and one crc32c for each 4096-byte block of data. So updating one object rewrites only one 4 KiB block and its crc (the `object_map_update` method in cls_rbd).

![The object map encoding of a ten-gigabyte image with 4 MiB objects (2560 objects), byte by byte. The eighteen-byte header contains the length, struct_v and compat, and the element count; then 640 bytes of data, each byte holding four objects with two bits each, and finally the footer with the crcs](figures/ch37/f03_objectmap.png){#fig-37-f03_objectmap}

## Who changes the state? {#sec-37-4-2}

- **A write** to an object that is NONEXISTENT or EXISTS_CLEAN updates the object map to EXISTS **before** the write is sent (first in memory, then with `object_map_update` on RADOS). If the object is already EXISTS, it costs nothing.
- **A discard or deletion** first sets the state to PENDING, deletes the object, and then sets NONEXISTENT.
- **Taking a snapshot** copies the head map to `rbd_object_map.<id>.<snapid>` and then turns all EXISTS entries of the head into EXISTS_CLEAN (`object_map_snap_add` in cls_rbd).
- **Deleting a snapshot** merges the EXISTS bits of that snapshot's map into the map of the next snapshot (or the head), so the "changed" information is not lost (`object_map_snap_remove`).

The object map is valid only with **exclusive-lock**, because only the lock owner may change it. If the client fails in the middle of an update, the `OBJECT_MAP_INVALID` flag is set in `flags` and `rbd object-map rebuild` must be run.

## fast-diff {#sec-37-4-3}

::: {.algo #alg-37-2 title="Computing each object's change state between two snapshots" src="src/librbd/object_map/DiffRequest.cc :: DiffRequest::handle_load_object_map" complexity="O(N × S) for N objects and S loaded maps; with no data reads at all"}
:::

```text
pseudocode
# for each snapshot from from_snap to end_snap (and head), its map is loaded and combined with the previous state
first map (from_snap):  state[o] = HOLE if NONEXISTENT else DATA (PENDING → DATA_UPDATED)
each later map m:
    HOLE:         if m[o] != NONEXISTENT → DATA_UPDATED     (diff-iterate: only in the final map)
    DATA:         if m[o] == NONEXISTENT → HOLE_UPDATED
                  elif m[o] != EXISTS_CLEAN → DATA_UPDATED
    HOLE_UPDATED: if m[o] != NONEXISTENT → DATA_UPDATED
    DATA_UPDATED: if m[o] == NONEXISTENT → HOLE_UPDATED
objects beyond the previous size (image grew) → HOLE or DATA_UPDATED
```

The key point is EXISTS_CLEAN: if an object existed at from_snap and stayed EXISTS_CLEAN in all later maps, it had no writes after from_snap and does not appear in the diff. `rbd diff --whole-object`, `rbd du` and `rbd export-diff` (and snapshot mode in rbd-mirror) all use this calculation. If `FAST_DIFF_INVALID` is set, librbd falls back to `list_snaps` on each individual object, which is much slower.

**Numerical example.** A 10 GiB image with 2560 objects. After snap1, twenty objects have been written and three have been discarded. With fast-diff, `rbd export-diff --from-snap snap1` reads only two 640-byte maps (plus header and footer) and finds the 23 objects. Without it, 2560 `list_snaps` calls would be needed.

# rbd reference {#sec-37-5}

## Images and snapshots {#sec-37-5-1}

| Command | Use |
|---|---|
| `rbd create P/I --size 10G [--object-size 4M] [--stripe-unit 64K --stripe-count 4] [--data-pool DP] [--image-feature F]` | creating an image |
| `rbd ls [-l] P[/NS]` / `rbd info P/I` / `rbd status P/I` | listing, details, watchers |
| `rbd resize P/I --size N [--allow-shrink]` | resizing |
| `rbd feature {enable,disable} P/I F` | turning a feature on and off |
| `rbd object-map {rebuild,check} P/I[@S]` | rebuilding and checking the object map |
| `rbd du P/I` / `rbd diff [--from-snap S] [--whole-object] P/I` | usage and changes |
| `rbd snap {create,ls,rm,purge,rollback,rename,limit set}` | snapshots |
| `rbd snap {protect,unprotect} P/I@S` | only for format 1 clones |
| `rbd clone P/I@S P2/C [--rbd-default-clone-format 2]` / `rbd children P/I@S` / `rbd flatten P2/C` | layering (chapter 38) |
| `rbd export P/I FILE` / `import` / `export-diff` / `import-diff` / `merge-diff` | backup |
| `rbd deep cp P/I P2/I2` / `rbd cp` | copying (deep, with snapshots) |
| `rbd trash {mv,ls,restore,rm,purge}` | the trash |
| `rbd migration {prepare,execute,commit,abort}` | live migration |
| `rbd image-meta {list,get,set,remove} P/I` | per-image metadata and settings |
| `rbd config {pool,image,global} {get,set,list}` | pool-level or image-level settings |
| `rbd namespace {create,ls,remove} P/NS` | namespaces |
| `rbd group {create,image add,snap create}` | consistency groups |
| `rbd lock {ls,add,rm}` | advisory locks (not exclusive-lock) |
| `rbd bench P/I --io-type {read,write,readwrite} --io-size 4K --io-threads 16 --io-pattern rand` | performance testing |
| `rbd perf image {iostat,iotop}` | live statistics from the mgr |
| `rbd pool init P` / `rbd pool stats P` | preparing a pool and its statistics |

## Mapping {#sec-37-5-2}

| Command | Use |
|---|---|
| `rbd device map [-t krbd] P/I [-o OPTS]` / `rbd device unmap` / `rbd device list` | krbd |
| `rbd device map -t nbd P/I` or `rbd-nbd map P/I [--try-netlink] [--timeout N]` | rbd-nbd (librbd in user space) |
| `rbd-nbd list-mapped` / `rbd-nbd unmap /dev/nbdX` | listing and unmapping |
| `rbd device map -t ubbd P/I` | ubbd, if its package is installed |

```bash
# example: creating an image with striping and a data pool, and inspecting it
rbd create rbd/vm01 --size 10G --stripe-unit 64K --stripe-count 4 --data-pool rbd-ec
rbd info rbd/vm01
```

```text
example (output):
rbd image 'vm01':
	size 10 GiB in 2560 objects
	order 22 (4 MiB objects)
	snapshot_count: 0
	id: 5f3a2b8c1d4e
	data_pool: rbd-ec
	block_name_prefix: rbd_data.3.5f3a2b8c1d4e
	format: 2
	features: layering, striping, exclusive-lock, object-map, fast-diff, deep-flatten, data-pool
	op_features:
	flags:
	create_timestamp: Sun Nov 15 09:41:07 2026
	access_timestamp: Sun Nov 15 09:41:07 2026
	modify_timestamp: Sun Nov 15 09:41:07 2026
	stripe unit: 64 KiB
	stripe count: 4
```

`block_name_prefix` is the `object_prefix`, and the number 3 in it is the id of the `rbd` pool, because we have a separate data pool.

# Tuning and troubleshooting {#sec-37-6}

- **Slow first writes on a new image:** each first write to an object also involves an `object_map_update`. Once the image is filled, this cost disappears. For performance testing, fill the image first.
- **`rbd du` or export-diff is slow:** look at `rbd info`; if it shows `flags: object map invalid, fast diff invalid`, run `rbd object-map rebuild` (separately on the snapshots too).
- **An image with `--data-pool` on EC cannot be created:** check `allow_ec_overwrites` on the EC pool and that `rbd pool init` has been run on both pools.
- **Deleting a large image is slow:** deletion depends on the number of **existing** objects; with the object map only existing objects are deleted. For long jobs use `rbd trash mv` followed by `rbd trash rm` or `ceph rbd task add remove`.
- **Never change the header with `rados setomapval`:** cls_rbd checks for inconsistencies, but open clients are not told about the change (no notify is sent).

# Supplementary and up to date {#sec-37-7}

- Format 2 clones (the default `rbd_default_clone_format: auto` chooses format 2 if all clients are Mimic or newer) do not need protect and keep the children in `snap_children_*` of the parent's own header.
- The `op_features` value in new versions has bits for snapshots in the trash and for groups; an old client that sees an unknown op_feature does not open the image.
- In the main branch, `rbd-nbd` with netlink and `--try-netlink` is more stable than the ioctl method; ubbd support depends on the distribution's packaging.

# Hands-on exercise {#sec-37-8}

1. Create an image and read all the header keys with `rados listomapkeys` and `getomapval`. Then take a snapshot and find the new key.
2. Create an image with `--stripe-unit 64K --stripe-count 4`, write 300000 bytes at offset 1000000 (`rbd bench` or `dd` on rbd-nbd) and see with `rados ls | grep` which objects were created. Compare with the example table.
3. Take `rados get rbd_object_map.<id> /tmp/om` and with `xxd` match the first four data bytes (after the eighteen-byte header) against the states of objects 0 to 15.
4. After a snapshot, write a few objects and time `rbd diff --from-snap` with and without fast-diff (after `rbd feature disable ... fast-diff`).

# Review questions {#sec-37-9}

1. Which header keys are needed to build the names of the data objects?
2. With a separate data pool, how do the data object names change, and why?
3. What two kinds of key does `rbd_directory` have?
4. In the striping example, which object and which offset hold the byte at offset 1100000?
5. How many bits does the object map keep per object, and in which bits of the first byte is object 0?
6. Why does the object map footer have a separate crc for each 4 KiB block?
7. When is EXISTS_CLEAN set and when is it cleared?
8. In fast-diff, if an object is DATA at from_snap and EXISTS in the head, what is the result?
9. Why does the object map depend on exclusive-lock?
10. How is a namespace implemented in RBD, and what advantage does it have?

# Sources for this chapter {#sec-37-10}

- cls_rbd.cc: https://github.com/ceph/ceph/blob/main/src/cls/rbd/cls_rbd.cc
- rbd_types.h and features.h: https://github.com/ceph/ceph/blob/main/src/include/rbd/features.h
- Striper.cc: https://github.com/ceph/ceph/blob/main/src/osdc/Striper.cc
- bit_vector.hpp: https://github.com/ceph/ceph/blob/main/src/common/bit_vector.hpp
- librbd/object_map/DiffRequest.cc: https://github.com/ceph/ceph/blob/main/src/librbd/object_map/DiffRequest.cc
- RBD layering and striping documentation: https://docs.ceph.com/en/latest/dev/rbd-layering/
- rbd command reference: https://docs.ceph.com/en/latest/man/8/rbd/
- rbd-nbd reference: https://docs.ceph.com/en/latest/man/8/rbd-nbd/
