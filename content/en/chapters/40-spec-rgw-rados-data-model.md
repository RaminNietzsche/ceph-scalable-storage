---
chapter: 40
id: ch40
title: 'Specialist Part (7): RGW — The Data Model on RADOS: Metadata, Bucket Index, Versioning, Manifest and Multipart'
part: specialist
lang: en
---

::: {.tldr}

- Each zone's pools are mostly namespaces inside a few shared pools; users, buckets and their metadata live there.
- A bucket index is a set of omap-only `.dir.<marker>.<shard>` objects, with a generation after resharding.
- Versioned buckets add an OLH (object logical head) that points to the current version.
- The manifest maps an object's head and tails to placement pools and storage classes; a multipart ETag is the md5 of the parts' md5s plus a part count.

:::

# Before we begin {#sec-40-1}

Chapter 4 showed that RGW keeps each S3 object in two places (the bucket index and the data) and presented the algorithms for choosing the shard, resharding, listing, and naming the head and tail objects. This chapter goes one layer down: exactly which pool and namespace hold user and bucket metadata, what fields an index entry has and how its omap keys are built, how the two-phase index update copes with failure, how versioning is implemented with the OLH, how the manifest lays out the head and tail across placement and storage classes, and how multipart completes without copying data. The chapter ends with a `radosgw-admin` reference. Names and defaults have been checked against the main branch of the ceph/ceph repository (November 2026).

## What questions does this chapter answer? {#sec-40-1-1}

- In which RADOS objects are the users, keys and buckets?
- What fields does an object's index entry have, and what are the `0x80` keys in the index omap?
- What happens if RGW fails between writing the data and updating the index?
- How is the "current" version of an object chosen in a versioned bucket?
- In which pool is an object's head written if its storage class is COLD?
- How is the ETag of a multipart object computed?

## Prerequisites {#sec-40-1-2}

Chapter 4 (RGW), chapter 15 (cls), chapter 34 (omap and xattrs) and chapter 36 (the atomicity of cls).

# Metadata: pools and namespaces {#sec-40-2}

Each zone has a set of pools, most of which are implemented as **namespaces** inside a few shared pools (`rgw::init_zone_pool_names` in `rgw_zone.cc`). The full name is built with the zone prefix; for the zone `default`:

| Use | pool:namespace |
|---|---|
| bucket entrypoint and bucket instance | `default.rgw.meta:root` |
| users by uid | `default.rgw.meta:users.uid` |
| mapping an access key to a user | `default.rgw.meta:users.keys` |
| email and Swift mappings | `default.rgw.meta:users.email`, `users.swift` |
| roles, accounts and groups, OIDC | `default.rgw.meta:roles`, `accounts`, `groups`, `oidc` |
| gc, lc, reshard, usage, notif, logging | `default.rgw.log:gc`, `:lc`, `:reshard`, `:usage`, `:notif`, `:logging` |
| datalog, mdlog and bilog trim | `default.rgw.log` |
| watch/notify between RGWs | `default.rgw.control` |
| bucket indexes | `default.rgw.buckets.index` (from the placement) |
| data | `default.rgw.buckets.data` (from the storage class) |
| multipart metadata | `default.rgw.buckets.non-ec` (`data_extra_pool` from the placement) |

A **bucket** has two metadata objects. The **entrypoint**, named after the bucket itself (or `<tenant>/<bucket>`) in `root`, only points to the current instance. The **instance**, named `.bucket.meta.<bucket>:<bucket-id>`, has all the properties: placement, the number of shards and the index layout, the owner, the versioning and object lock flags, and xattrs such as policy, lifecycle and CORS. Resharding creates a new instance with a new bucket-id and only moves the entrypoint.

```bash
# example: viewing a bucket's and a user's metadata
radosgw-admin metadata get bucket:photos
radosgw-admin metadata get bucket.instance:photos:a1b2c3d4-0000-4000-8000-1234567890ab.4123.7
rados -p default.rgw.meta -N users.keys ls | head -3
```

```text
example (shortened output):
{ "key": "bucket:photos",
  "data": { "bucket": { "name": "photos", "marker": "a1b2c3d4-...4123.7", "bucket_id": "a1b2c3d4-...4123.7" },
            "owner": "alice", "creation_time": "2026-11-02T08:14:33.120Z" } }
AKIAEXAMPLE7Q2WZ3L
AKIAEXAMPLEM9K1D0B
AKIAEXAMPLEP5T8H4N
```

The `marker` is the prefix from which the names of the data and index objects are built (chapter 4), and it does **not** change after a reshard, whereas `bucket_id` does. The `users.keys` list holds only the access key ids; the secret key is inside the user record and must never appear in a log or report.

# The bucket index {#sec-40-3}

## Objects and keys {#sec-40-3-1}

Each bucket's index is in the objects `.dir.<marker>.<shard>` (or, for generations after a reshard, `.dir.<marker>.<gen>.<shard>`) in the index pool. Each index object has only omap. The omap header keeps the shard's statistics (count, size and actual size per category) and the index version. The omap keys have several **key spaces** (`cls_rgw.cc`):

| Space | Key format | Content |
|---|---|---|
| ordinary entry | `<name>` | the `rgw_bucket_dir_entry` of the current version (or of an unversioned object) |
| bilog (InIndex mode) | `0x80` + `0_` + `<index_ver:%011llu>.<osd ver>.<subop>` | a bilog entry for multisite (chapter 42) |
| instance | `0x80` + `1000_` + `<name>` + `\0i` + `<instance>` | one version of an object in a versioned bucket |
| OLH | `0x80` + `1001_` + `<name>` | `rgw_bucket_olh_entry`: the current version and the change log |
| reshard log | `0x80` + `2001_` + … | changes made during a reshard |

Since in UTF-8 no name starts with the byte `0x80` (that byte is only a continuation byte of a multi-byte character), the `bi_entry_type` function in cls rgw tells ordinary keys from special ones by looking at the first byte. Special keys sort after all ASCII names and before names that start with non-ASCII characters (first byte `0xC2` and up); hence listing (`get_obj_vals`) must explicitly skip the `0x80` range, and "a scan up to 0x80" alone is not enough.

![The special keys in the omap of an index shard. The instance key is built from 0x80, the prefix 1000_, the name, a zero byte, the letter i and the version id; the OLH key has only the prefix 1001_ and the name; the bilog key has an eleven-digit zero-padded index_ver so that lexical order equals numeric order](figures/ch40/f01_index.png){#fig-40-f01_index}

## The index entry {#sec-40-3-2}

`rgw_bucket_dir_entry` has these fields: `key` (name and instance), `ver` (pool and epoch, that is the RADOS version of the head object), `locator`, `exists`, `meta` (category, size, mtime, etag, owner, owner_display_name, content_type, accounted_size, user_data, storage_class, appendable and the restore status), `pending_map` (unfinished operations), `index_ver`, `tag`, `flags` (`VER`, `CURRENT`, `DELETE_MARKER`, `VER_MARKER`) and `versioned_epoch`.

`accounted_size` is the size the user saw (before compression or encryption) and `size` is the actual stored size; quotas and bucket statistics are computed from `accounted_size`.

## The two-phase update {#sec-40-3-3}

Writing the data and updating the index happen in two separate objects (and usually on two separate OSDs), and RADOS has no cross-object transactions. RGW coordinates the two with a two-phase protocol.

::: {.algo #alg-40-1 title="prepare and complete in the bucket index" src="src/cls/rgw/cls_rgw.cc :: rgw_bucket_prepare_op, rgw_bucket_complete_op, rgw_dir_suggest_changes; src/rgw/driver/rados/rgw_rados.cc :: RGWRados::Bucket::UpdateIndex" complexity="two cls calls on the index shard per PUT or DELETE"}
:::

```text
pseudocode
PUT key:
    tag = random op tag
    cls rgw.bucket_prepare_op(shard, key, op=ADD, tag)
        entry = read or init(exists=false) ; entry.pending_map[tag] = {PENDING_MODIFY, now, op}
    write head (and tails) to data pool ; get head RADOS version (epoch)
    cls rgw.bucket_complete_op(shard, key, op=ADD, tag, ver=epoch, meta)
        erase pending_map[tag]
        if ver older than entry.ver: skip (stale completion)
        unaccount old entry stats ; entry.meta = meta ; entry.exists = true ; account new
        append bilog entry (if logging enabled)
    on write failure: complete_op(op=CANCEL) → just erase tag (no bilog)
crash between prepare and complete:
    entry stays with stale pending_map ; listing sees pending older than rgw_pending_bucket_index_op_expiration (120 s)
    → RGW checks head object's real state (check_disk_state)
    → cls rgw.dir_suggest_changes(UPDATE or REMOVE) fixes the entry
```

![The sequence of the two-phase update: prepare puts the operation tag in pending_map, the data is written, and complete removes the tag and updates the entry, the statistics and the bilog. If complete never arrives, the next listing checks the head's state and fixes the entry with dir_suggest_changes](figures/ch40/f03_twophase.png){#fig-40-f03_twophase}

The practical consequence: the index may be inconsistent with the data for a short time (the object is written but not yet listed, or the other way round), but **listing repairs itself**. `radosgw-admin bucket check --fix --check-objects` performs the same check for all entries.

# Versioning and the OLH {#sec-40-4}

In a versioned bucket each version has a separate head object with a random `instance` (for example `3sL4kqtJlcpXroDTDmJ+rmSpXd3dIbrHY`). The current version is identified by an **OLH** (object logical head): a `1001_` entry in the index and a data-less head object with the original name, which points to the current instance in the xattrs `user.rgw.olh.info`, `user.rgw.olh.ver`, `user.rgw.olh.idtag` and `user.rgw.olh.pending.*`.

::: {.algo #alg-40-2 title="link_olh: adding a version and setting the current version" src="src/cls/rgw/cls_rgw.cc :: rgw_bucket_link_olh; src/rgw/driver/rados/rgw_rados.cc :: RGWRados::set_olh, apply_olh_log" complexity="a few omap reads and writes on one shard; then one xattr update on the OLH head"}
:::

```text
pseudocode
PUT on versioned bucket:
    write instance head object <name> with instance id ; index prepare/complete on 1000_<name>\0i<instance>
    cls rgw.bucket_link_olh(key, olh_tag, delete_marker = false, olh_epoch = 0 or remote epoch):
        candidate_epoch = olh_epoch from multisite, else now in ns   # main
        if olh.start_modify(candidate_epoch):
            promote = newer epoch, or same epoch and instance sorts after current
            if promote: old current loses FLAG_CURRENT ; this instance gets FLAG_CURRENT
                        plain entry <name> now mirrors this instance
            olh.update_log(LINK_OLH, op_tag, key, delete_marker)
            olh.update(key, delete_marker)
        bilog entry LINK_OLH (or LINK_OLH_DM for delete marker)
    RGW then reads OLH log and applies it to the OLH head xattrs (apply_olh_log), then trims the log
DELETE without versionId: link_olh with delete_marker = true (new instance, no data)
DELETE with versionId: unlink_instance ; if it was current → promote next newest
```

**Example.** The object `report.pdf` was uploaded three times and then deleted without a versionId. The index has four instance entries (three versions and one delete marker with the flags `DELETE_MARKER|CURRENT`), one OLH entry and one ordinary entry. `GET report.pdf` looks at the OLH, sees that the current version is a delete marker and returns 404. `GET report.pdf?versionId=<v2>` reads the head of the second version directly.

::: {.note}
An object written before versioning was turned on has an empty instance and appears in the API as `versionId=null`. Writing again in the `Suspended` state also overwrites that same null version.
:::

# Manifest, placement and storage classes {#sec-40-5}

## Layout rules {#sec-40-5-1}

Each bucket has a **placement target** (from the zonegroup), which the zone maps to three pools: `index_pool`, `data_extra_pool` and, for each **storage class**, a `data_pool` (with optional compression). The head is always in the pool of the default storage class (`STANDARD`) of the bucket's placement; if the object has a different storage class, the head holds only metadata (the manifest and xattrs) and all the data is in tails in that class's pool.

::: {.algo #alg-40-3 title="Setting the head, chunk and stripe sizes for a PUT" src="src/rgw/driver/rados/rgw_putobj_processor.cc :: AtomicObjectProcessor::prepare; src/rgw/rgw_obj_manifest.cc :: set_trivial_rule" complexity="O(1) to build the rule; O(size / stripe) tail objects"}
:::

```text
pseudocode
head_pool = data pool of (bucket placement, STANDARD)
max_head_chunk = rgw_max_chunk_size (4 MiB), aligned to pool alignment (EC)
if object storage class != STANDARD:
    tail_pool = data pool of that class ; head_max_size = 0 ; chunk = tail pool max chunk
elif placement.inline_data:
    head_max_size = max_head_chunk ; chunk = max_head_chunk
else: head_max_size = 0
stripe = rgw_obj_stripe_size (4 MiB), aligned
manifest.set_trivial_rule(head_max_size, stripe)
data: first head_max_size bytes → head ; rest → tail objects of `stripe` bytes, written in chunks
xattrs on head: user.rgw.manifest, user.rgw.etag, user.rgw.acl, user.rgw.idtag, user.rgw.tail_tag, user.rgw.storage_class, ...
```

**Numerical example.** A 10 MiB PUT in the STANDARD class: the head holds 4 MiB of data and two tails of 4 MiB and 2 MiB are created (three RADOS objects). The same PUT with `x-amz-storage-class: COLD`: a data-less head in the STANDARD pool and three tails of 4, 4 and 2 MiB in the COLD pool. So even for a cold class, the STANDARD pool has one small head per object; this matters when sizing an SSD pool. A lifecycle transition (chapter 41) produces the same pattern: new tails in the destination pool and a new manifest on the same head.

![The layout of a 10 MiB object in two cases. In STANDARD, the head holds the first four megabytes and two tails the rest. In COLD, the head keeps only the manifest and xattrs in the STANDARD pool, and all the data is in three tails in the COLD pool](figures/ch40/f02_manifest.png){#fig-40-f02_manifest}

# Multipart {#sec-40-6}

::: {.algo #alg-40-4 title="Multipart upload: init, part and complete" src="src/rgw/driver/rados/rgw_sal_rados.cc :: RadosMultipartUpload::init, complete; src/rgw/driver/rados/rgw_putobj_processor.cc :: MultipartObjectProcessor::complete; src/rgw/rgw_multi.h" complexity="complete is O(P) for P parts; with no data copy"}
:::

```text
pseudocode
init(key): upload_id = "2~" + random ; create meta object "<key>.<upload_id>.meta"
           (namespace multipart, data_extra_pool) ; index entry in multipart namespace
upload part n (size >= rgw_multipart_min_part_size 5 MiB, except last):
    write part head "<marker>__multipart_<key>.<upload_id>.<n>" + shadow stripes
    omap set on meta object: key "part." + %08d(n) → RGWUploadPartInfo{num, size, etag, manifest}
complete(list of (n, etag)):
    read part infos from meta omap (sorted thanks to %08d) ; verify each etag and order
    manifest = concatenation of part manifests (no data copy)
    etag = hex(md5(concat(binary md5 of each part))) + "-" + P
    write final head <key> with manifest and attrs ; index prepare/complete
    remove meta object and its index entry ; parts not listed → gc
```

**Numerical example.** Three parts of 5, 5 and 2 MiB, filled with `A`, `B` and `C` respectively, have the ETags `b8fc857a25e7958868c2f003d5e0952d`, `ba8c3fac0e224c9b79a8e74bebd54654` and `bf52955b454974e73c3e2694bd7207c4`. The final ETag is the md5 of the concatenation of their 48 binary bytes: `eacd2737fa049d51213f10cdc5732ece-3`. This value is **not** the md5 of the whole file; a tool that compares the ETag with the file's md5 must recognize the `-N` suffix.

The `2~` prefix in the upload_id shows that the part keys are stored sorted with `%08d`. Old uploads (prefix `2/`) stored parts without leading zeros, and complete had to sort them numerically.

# radosgw-admin reference {#sec-40-7}

| Command | Use |
|---|---|
| `radosgw-admin user {create,info,modify,suspend,enable,rm,list}` | users |
| `radosgw-admin key {create,rm}` / `subuser {create,modify,rm}` | keys and subusers |
| `radosgw-admin account {create,get,modify,rm}` | accounts (IAM) |
| `radosgw-admin bucket {list,stats,link,unlink,chown,rm}` | buckets |
| `radosgw-admin bucket check [--fix] [--check-objects]` | checking and repairing the index |
| `radosgw-admin bucket reshard --bucket B --num-shards N` / `reshard {add,list,status,process,cancel}` | resharding |
| `radosgw-admin bucket limit check` | over-full shards |
| `radosgw-admin bi {get,list,put,purge}` | raw index entries (with care) |
| `radosgw-admin object stat --bucket B --object K` | an object's manifest and xattrs |
| `radosgw-admin object {rm,unlink,rewrite}` | operations on one object |
| `radosgw-admin quota {set,enable,disable} --quota-scope {user,bucket}` / `user stats --sync-stats` | quotas |
| `radosgw-admin ratelimit {set,get,enable,disable} --ratelimit-scope {user,bucket,anonymous}` | rate limits |
| `radosgw-admin gc {list,process} [--include-all]` | garbage collection |
| `radosgw-admin lc {list,get,process,reshard fix}` | lifecycle |
| `radosgw-admin usage {show,trim}` | usage reports (if enabled) |
| `radosgw-admin metadata {list,get,put,rm} SECTION[:KEY]` | raw metadata |
| `radosgw-admin zonegroup placement {list,add,modify}` / `zone placement {list,add,modify}` | placement and storage classes |
| `radosgw-admin {realm,zonegroup,zone,period} ...` / `sync status` | multisite (chapter 42) |
| `radosgw-admin orphans` / `rgw-orphan-list` | finding orphaned objects in the data pool |

```bash
# example: the manifest of a 10 MiB object in STANDARD
radosgw-admin object stat --bucket photos --object big.bin | jq '.manifest | {obj_size, head_size, max_head_size, rules}'
```

```text
example (output):
{
  "obj_size": 10485760,
  "head_size": 4194304,
  "max_head_size": 4194304,
  "rules": [ { "key": 0, "val": { "start_part_num": 0, "start_ofs": 4194304, "part_size": 0,
               "stripe_max_size": 4194304, "override_prefix": "" } } ]
}
```

# Tuning and troubleshooting {#sec-40-8}

- **Slow listing and wrong `bucket stats`:** there are many old pending entries. Run `radosgw-admin bucket check --check-objects --fix` at a quiet time.
- **Large omap in the index pool:** a shard has more than `rgw_max_objs_per_shard` (100000) entries, or (in InIndex mode) the bilog has not been trimmed. Look at `bucket limit check` and `bilog list` (chapter 42).
- **The STANDARD pool fills up despite a cold class:** each object has one head in STANDARD; for billions of small objects this alone is a lot of space and objects.
- **Space in the data pool is not freed:** deleted tails are waiting for gc (by default at least 2 hours; chapter 41). Look at `gc list --include-all`.
- **Abandoned multipart uploads:** only lifecycle with `AbortIncompleteMultipartUpload` or `radosgw-admin bucket rm --purge-objects` removes them; `rados ls` on `data_extra_pool` shows how many there are.

# Supplementary and up to date {#sec-40-9}

- In the main branch, the `epoch` of versions in link_olh is taken from the current time in nanoseconds (unless it comes from multisite). Older versions behaved differently, and this matters when versions are compared across zones.
- The `inline_data` option in the placement (on by default) determines whether the head holds data; turning it off helps EC pools that store small heads poorly.
- In the main branch, new buckets keep the bilog by default in a separate FIFO instead of the index omap (`rgw_default_bucket_bilog_type = fifo`); `0_` keys appear only in `inindex` mode and in old buckets.
- The `:accounts`, `:groups` and `:vector` pools and `dedup_pool` have been added in new versions; check your version before relying on them.

# Hands-on exercise {#sec-40-10}

1. Create a bucket and find its entrypoint and instance with `rados -p default.rgw.meta -N root ls`. Look again after `bucket reshard`.
2. With `rados -p default.rgw.buckets.index listomapkeys .dir.<marker>.0 | xxd | head`, look at the `0x80` keys in a versioned bucket.
3. Upload a 10 MiB object once in STANDARD and once in COLD, and compare where the head and tails are with `object stat` and `rados ls`.
4. Do a three-part upload and match the final ETag against a manual calculation (the md5 of the concatenated md5s).

# Review questions {#sec-40-11}

1. How do a bucket's entrypoint and instance differ, and which one does a reshard change?
2. What structure does the key of a bilog entry in the index omap have?
3. Why do the special keys start with the byte 0x80?
4. How do `size` and `accounted_size` in an index entry differ?
5. If RGW fails after prepare and the data write but before complete, how is the entry repaired?
6. What is the OLH, and where is it stored?
7. What does a delete without a versionId do in a versioned bucket?
8. In which pool is the head of a COLD object, and what does it hold?
9. How is the ETag of a three-part upload built?
10. What does the `2~` prefix in the upload_id indicate?

# Sources for this chapter {#sec-40-12}

- cls_rgw.cc and cls_rgw_types.h: https://github.com/ceph/ceph/blob/main/src/cls/rgw/cls_rgw.cc
- rgw_zone.cc (pool names): https://github.com/ceph/ceph/blob/main/src/rgw/rgw_zone.cc
- rgw_putobj_processor.cc: https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_putobj_processor.cc
- rgw_sal_rados.cc (multipart): https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_sal_rados.cc
- Bucket index and layout documentation: https://docs.ceph.com/en/latest/dev/radosgw/bucket_index/
- Placement and storage class documentation: https://docs.ceph.com/en/latest/radosgw/placement/
- radosgw-admin: https://docs.ceph.com/en/latest/man/8/radosgw-admin/
