---
chapter: 4
id: ch04
title: Object Storage with the RADOS Gateway
part: main
original_heading: Working with Ceph Object Storage
lang: en
---

# Before you start {#sec-04-1}

## What questions does this chapter answer? {#sec-04-1-1}

Object storage is the fastest-growing part of the storage world: backups, media archives, logs, machine-learning datasets, CI artifacts and even the "data lake". The de facto standard API in this field is **Amazon S3**, and the **RADOS Gateway** (RGW) is Ceph's implementation of it. In this chapter:

- How does object storage differ from block and file, and how does RGW implement it on RADOS?
- How do we deploy RGW with cephadm and put it behind a load balancer?
- What are users, keys, subusers, tenants and accounts, and which should we use when?
- How do we access RGW with S3 (s3cmd and aws-cli) and Swift, and configure virtual-host bucket DNS?
- How do we integrate RGW with Keystone and Hadoop S3A?
- How do today's features such as versioning, lifecycle, object lock, bucket policy and event notification work?

## Prerequisites {#sec-04-1-2}

The cluster from chapter 1 and the host ceph-node4 with the `rgw` label, plus client-node1 for the client tools.

# Getting to know object storage in Ceph {#sec-04-2}

## Objects, buckets and the API {#sec-04-2-1}

In object storage there is no directory tree and no rewritable block. Data is stored as **objects**: a key (name), binary content and metadata. Objects are grouped in **buckets** (in Swift terms: containers) and accessed over HTTP with verbs such as PUT, GET, HEAD and DELETE. An object is usually written in one go and read in one go; changing part of an object means rewriting the whole of it. This very simplicity is what makes huge scale and access from anywhere on the internet possible.

| Property | Block (RBD) | File (CephFS) | Object (RGW) |
|---|---|---|---|
| Interface | Block device | POSIX | HTTP (S3/Swift) |
| Unit of access | Block | Byte in a file | Whole object (with range reads) |
| Metadata | None | Permissions, times | Arbitrary, plus tags |
| Typical scale | Terabytes per disk | Millions of files | Billions of objects |
| Use | VMs, databases | File shares, HPC | Backup, media, analytics data |

## RGW on RADOS {#sec-04-2-2}

radosgw is a stateless HTTP server (since Nautilus its default frontend is **Beast**, based on Boost.Asio, and the old civetweb frontend has been retired). It translates each S3 or Swift request into a set of RADOS operations. Because no state is kept in RGW itself, any number of instances can be put behind a load balancer.

![RGW architecture: stateless instances behind a load balancer, and separate pools for the index, data and metadata](figures/ch04/f01_arch.png){#fig-04-f01_arch}

## RGW pools {#sec-04-2-3}

In a simple deployment (the default zone), RGW creates these pools:

| Pool | Content | Recommendation |
|---|---|---|
| `.rgw.root` | Definitions of the realm, zonegroup and zone | Small; replicated |
| `default.rgw.control` | watch/notify objects for cache coordination between instances | Small |
| `default.rgw.meta` | User and bucket metadata | On SSD if possible |
| `default.rgw.log` | Sync, lifecycle and usage logs | Small to medium |
| `default.rgw.buckets.index` | Each bucket's index in omap | **Always on SSD/NVMe and replicated** |
| `default.rgw.buckets.data` | Object data | Replicated or EC; the largest pool |
| `default.rgw.buckets.non-ec` | Multipart upload metadata | Replicated |

::: {.warn}
Never make the index pool erasure-coded (EC does not support omap), and do not put it on HDD. Every PUT and DELETE is an omap update in the index, and a slow index means a slow RGW overall. A CRUSH rule based on device class that puts the index on NVMe is one of the most effective RGW optimisations.
:::

## An S3 object in RADOS {#sec-04-2-4}

![A 20 MB S3 object in RADOS: a head object with metadata and the manifest, tail objects for the rest of the data, and an entry in the relevant index shard](figures/ch04/f02_object.png){#fig-04-f02_object}

- **head object:** the first part of the data (by default up to 4 MB; `rgw_max_chunk_size`) together with the object's metadata in xattrs and a **manifest** that lists the remaining pieces.
- **tail objects:** the rest of the data in separate objects (names with the prefix `__shadow_`, or `__multipart_` for multipart uploads).
- **index entry:** a key in the omap of one of the bucket's index shards; used for listing (ListObjects).

::: {.deep}
Because each bucket's index lives in the omap of RADOS objects, a bucket with hundreds of millions of objects, if not sharded, creates a giant omap object that slows down scrubbing, recovery and even normal operations, and raises the `LARGE_OMAP_OBJECTS` warning. **Dynamic resharding** (the default since Luminous) automatically increases the number of shards when the number of objects per shard reaches the threshold `rgw_max_objs_per_shard` (default 100,000). In Tentacle most of the reshard processing happens before writes are locked, to reduce its effect on clients.
:::

# Deploying and configuring the RADOS Gateway {#sec-04-3}

## Deploying with cephadm {#sec-04-3-1}

The original book installed RGW by hand with packages and ceph-deploy on a separate node. With cephadm one command is enough:

```bash
ceph orch host label add ceph-node4 rgw
ceph orch host label add ceph-node3 rgw
ceph orch apply rgw objstore --placement="label:rgw count-per-host:1" --port=8080
ceph orch ls rgw
ceph orch ps --daemon-type rgw
curl http://ceph-node4:8080
```

An empty `ListAllMyBucketsResult` response for the anonymous user means RGW is up. For more control, use a YAML spec:

```yaml
service_type: rgw
service_id: objstore
placement:
  label: rgw
  count_per_host: 2
networks:
  - 192.168.56.0/24
spec:
  rgw_frontend_port: 8080
  rgw_frontend_type: beast
```

## A load balancer with the ingress service {#sec-04-3-2}

cephadm has an `ingress` service that deploys HAProxy and keepalived and puts a virtual IP in front of the RGW instances:

```yaml
service_type: ingress
service_id: rgw.objstore
placement:
  hosts: [ceph-node3, ceph-node4]
spec:
  backend_service: rgw.objstore
  virtual_ip: 192.168.56.100/24
  frontend_port: 443
  monitor_port: 1967
  ssl: true
```

```bash
ceph orch apply -i ingress.yaml
ceph orch ls ingress
```

In recent releases (Tentacle and Umbrella) the **certmgr** subsystem in cephadm automatically generates and renews cephadm-signed certificates for such services, or accepts your certificate and raises a health warning for certificates that are about to expire.

::: {.tip}
In production, terminate TLS either at the load balancer or in Beast itself (with `rgw_frontend_ssl_certificate`). If you terminate it in HAProxy, make sure RGW reads the client's real address from the `X-Forwarded-For` header (`rgw_remote_addr_param = http_x_forwarded_for`); otherwise IP-based policies and the logs see the load balancer's address.
:::

::: {.debug}
If an RGW instance does not come up after apply, look at `ceph orch ps --daemon-type rgw` and `ceph health detail`. The most common reason on small clusters is a `TOO_MANY_PGS` warning or a pool creation error because `mon_max_pg_per_osd` has been reached, since RGW creates several new pools. Another way to investigate is `cephadm logs --name rgw.objstore.ceph-node4.xxxx` on the host.
:::

# Users, keys and tenants {#sec-04-4}

## Creating a radosgw user {#sec-04-4-1}

RGW users are independent of cephx users and are kept in the RGW metadata pool. The tool for managing them is `radosgw-admin`:

```bash
radosgw-admin user create --uid=alice --display-name="Alice" --email=alice@example.com
radosgw-admin user info --uid=alice
radosgw-admin user list
radosgw-admin key create --uid=alice --key-type=s3 --gen-access-key --gen-secret
radosgw-admin user suspend --uid=alice
radosgw-admin user enable --uid=alice
```

The output of `user create` contains an `access_key` and `secret_key` pair that the S3 client uses to sign requests (AWS Signature v4).

::: {.warn}
The output of `radosgw-admin user info` shows the secret key in plain text. Do not copy it into a ticket, a chat or a CI log. Use a secrets management system (for example Vault) to hand keys to teams, and rotate old keys periodically (`key create` and then `key rm`).
:::

## Quotas and rate limits {#sec-04-4-2}

```bash
radosgw-admin quota set --quota-scope=user --uid=alice --max-size=500G --max-objects=10000000
radosgw-admin quota enable --quota-scope=user --uid=alice
radosgw-admin quota set --quota-scope=bucket --uid=alice --max-objects=5000000
radosgw-admin quota enable --quota-scope=bucket --uid=alice
radosgw-admin ratelimit set --ratelimit-scope=user --uid=alice --max-read-ops=1000 --max-write-ops=200
radosgw-admin ratelimit enable --ratelimit-scope=user --uid=alice
```

Rate limiting was added in Quincy, and in Umbrella the rate-limit response also carries a `Retry-After` header, which well-behaved clients use to back off.

## Subusers and Swift keys {#sec-04-4-3}

The Swift API uses the concept of a subuser: an identity under a user with a specific access level and a Swift-specific key.

```bash
radosgw-admin subuser create --uid=alice --subuser=alice:swift --access=full
radosgw-admin key create --subuser=alice:swift --key-type=swift --gen-secret
```

## Tenants and accounts {#sec-04-4-4}

![Two multi-tenancy mechanisms: the tenant for separating bucket namespaces, and the account (since Squid) for IAM-style self-service management of users and policies](figures/ch04/f03_tenancy.png){#fig-04-f03_tenancy}

In RGW bucket names are unique across the whole cluster by default. A **tenant** creates a separate namespace so that two customers can have buckets with the same name:

```bash
radosgw-admin user create --tenant=acme --uid=bob --display-name="Bob at ACME"
# Full user name: acme$bob , and the buckets are in the acme namespace
```

Since Squid, the **account** adds a concept similar to an AWS account: an account owns users, groups, roles and policies, and its "root user" can manage users and keys through IAM-compatible APIs without the cluster administrator's involvement.

```bash
radosgw-admin account create --account-name=acme --email=ops@acme.example
radosgw-admin user create --uid=acme-root --display-name="ACME root" \
  --account-id=<account-id> --account-root --gen-secret --gen-access-key
radosgw-admin quota set --quota-scope=account --account-id=<account-id> --max-size=10T
radosgw-admin quota enable --quota-scope=account --account-id=<account-id>
```

::: {.note}
The Tentacle release notes announce that tenant-based IAM features (such as tenant-level CreateRole and PutUserPolicy, and STS Lite) are deprecated in favour of accounts and will not be removed before release V. The tenant itself remains for namespace separation. For a new multi-tenancy design, start with accounts.
:::

# Access with the S3-compatible API {#sec-04-5}

## DNS and virtual-host access {#sec-04-5-1}

S3 has two addressing styles: **path-style** (`https://s3.example.com/bucket/key`) and **virtual-hosted-style** (`https://bucket.s3.example.com/key`). Many recent SDKs default to the second style. To support it:

1. Create a wildcard DNS record: `*.s3.example.com` pointing at the load balancer's virtual IP.
2. Tell RGW what its domain name is:

```bash
ceph config set client.rgw rgw_dns_name s3.example.com
ceph orch restart rgw.objstore
```

In a multi-zonegroup deployment the host names go into the `hostnames` field of the zonegroup definition (chapter 5). The TLS certificate must also be a wildcard (`*.s3.example.com`).

## s3cmd {#sec-04-5-2}

```bash
sudo dnf install -y s3cmd      # or pip install s3cmd
s3cmd --configure              # access key, secret key and endpoint
# or directly in ~/.s3cfg:
cat > ~/.s3cfg <<'C'
[default]
access_key = <ACCESS>
secret_key = <SECRET>
host_base = s3.example.com
host_bucket = %(bucket)s.s3.example.com
use_https = True
C
s3cmd mb s3://photos
s3cmd put cat.jpg s3://photos/
s3cmd ls s3://photos
s3cmd get s3://photos/cat.jpg /tmp/cat.jpg
s3cmd info s3://photos/cat.jpg
```

## aws-cli and the SDKs {#sec-04-5-3}

```bash
aws configure --profile ceph                      # the keys
aws --profile ceph --endpoint-url https://s3.example.com s3 mb s3://backups
aws --profile ceph --endpoint-url https://s3.example.com s3 cp ./db.dump s3://backups/
aws --profile ceph --endpoint-url https://s3.example.com s3api list-objects-v2 --bucket backups
aws --profile ceph --endpoint-url https://s3.example.com s3 presign s3://backups/db.dump --expires-in 3600
```

::: {.warn}
Some recent releases of the AWS SDKs send the new data integrity checksums (such as CRC32 in the `x-amz-checksum-*` headers) with every PUT by default. RGW's support for these features differs between releases; if you see signature errors or "InvalidArgument" after an SDK upgrade, check the release notes of your RGW version and, if necessary, set checksum sending back to "only when required" in the client configuration. The Umbrella notes also report a SigV4 regression in 19.2.6 and 20.2.4 that rejected presigned PUT uploads with an unsigned Content-Type, which has been fixed.
:::

## Multipart upload {#sec-04-5-4}

For large objects (usually above 100 MB) use **multipart upload**; aws-cli and s3cmd do this automatically. Incomplete uploads take up space and are not visible in the object listing. Add a lifecycle rule to clean them up (`AbortIncompleteMultipartUpload`), and check them now and then with `radosgw-admin bucket list --bucket=<b>` or `aws s3api list-multipart-uploads`.

# Access with the Swift API {#sec-04-6}

```bash
pip install python-swiftclient
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' stat
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' post container01
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' upload container01 report.pdf
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' list container01
```

Buckets in S3 and containers in Swift are the same thing: a file uploaded with Swift is also visible through S3 (provided the user is the same).

# Integrating with OpenStack Keystone {#sec-04-7}

In OpenStack clouds we usually want users to access object storage with the same Keystone identity, and RGW to be registered in the catalog as the `object-store` service.

![The Swift authentication flow with Keystone: RGW validates the token with Keystone and automatically creates a user for each project](figures/ch04/f04_keystone.png){#fig-04-f04_keystone}

```bash
# In Keystone
openstack service create --name swift --description "Ceph RGW" object-store
openstack endpoint create --region RegionOne object-store public \
  "https://s3.example.com/swift/v1/AUTH_%(project_id)s"
# In Ceph
ceph config set client.rgw rgw_keystone_url https://keystone.example.com:5000
ceph config set client.rgw rgw_keystone_api_version 3
ceph config set client.rgw rgw_keystone_admin_user rgw
ceph config set client.rgw rgw_keystone_admin_password_path /etc/ceph/keystone.pass
ceph config set client.rgw rgw_keystone_admin_domain Default
ceph config set client.rgw rgw_keystone_admin_project service
ceph config set client.rgw rgw_keystone_accepted_roles "member,admin"
ceph config set client.rgw rgw_keystone_implicit_tenants true
ceph config set client.rgw rgw_swift_account_in_url true
ceph config set client.rgw rgw_s3_auth_use_keystone true
```

::: {.tip}
The RGW documentation prefers the `rgw_keystone_admin_password_path` option to putting the password in plain text in the configuration. With cephadm you can make the file available to the container through `extra_container_args`/a mount or `ceph config-key`. `rgw_s3_auth_use_keystone` makes it possible to use EC2 credentials in Keystone (`openstack ec2 credentials create`) for S3. In Umbrella the old admin-token requirement for Keystone has been removed, and Keystone roles are injected into the IAM policy evaluation environment.
:::

# Integrating with Hadoop and Spark through S3A {#sec-04-8}

The Hadoop ecosystem connects to any S3-compatible service through the **S3A** connector. This means you can replace HDFS with RGW for cold or even primary storage and scale compute and storage separately.

```xml
<!-- core-site.xml -->
<property><name>fs.s3a.endpoint</name><value>https://s3.example.com</value></property>
<property><name>fs.s3a.path.style.access</name><value>true</value></property>
<property><name>fs.s3a.access.key</name><value>ACCESS</value></property>
<property><name>fs.s3a.secret.key</name><value>SECRET</value></property>
<property><name>fs.s3a.connection.ssl.enabled</name><value>true</value></property>
<property><name>fs.s3a.committer.name</name><value>magic</value></property>
```

```bash
hadoop fs -mkdir s3a://analytics/raw
hadoop fs -put events.parquet s3a://analytics/raw/
spark-submit --conf spark.hadoop.fs.s3a.endpoint=https://s3.example.com job.py
```

::: {.deep}
Writing the output of Spark jobs to object storage has the "rename" challenge: Hadoop's traditional commit renames a temporary directory, which in S3 means copying and deleting every object. **S3A committers** (such as directory and magic) solve this with multipart uploads that are completed only at commit time. For heavy analytics workloads on RGW, always enable one of these committers. Hadoop's own documentation on compatibility prerequisites (for example multipart support and consistent listing) is a good guide; RGW has strong read-after-write consistency.
:::

# From the code: bucket index, manifest and the PUT path in RGW {#sec-04-9}

## Two separate places for one S3 object {#sec-04-9-1}

RGW records each S3 object in two independent places. One is the **bucket index entry**, which lives in the omap of the shard objects in the index pool and is used for List and bucket statistics. The other is **the data itself**, stored in the data pool as one head and zero or more tails. Keeping these two consistent, without a distributed transaction, is done with a lightweight two-phase protocol on the `cls_rgw` class.

![The PUT path of an object. radosgw computes the shard number from the hash of the object name. First the cls method bucket_prepare_op records an entry with state PENDING_MODIFY and a unique tag in the shard. Then the head (containing at most the first 4MiB of data and the manifest, ACL and etag xattrs) and the tail stripes are written. Finally bucket_complete_op moves the entry to the COMPLETE state with the size, etag and mtime and creates a bilog record for multisite sync. If RGW fails between these two phases, the pending entry stays behind and is later fixed by dir_suggest_changes (during list) or radosgw-admin bucket check](figures/ch04/s01_put.png){#fig-04-s01_put}

| Constant/option | Value (main) | Source |
|---|---|---|
| Index shard object prefix | `.dir.` | `rgw/services/svc_bi_rados.cc` |
| Default shard count for a new bucket | 11 | `default_bucket_index_max_shards` in `rgw_zone_types.h` |
| rgw_override_bucket_index_max_shards | 0 (meaning the zonegroup value) | `rgw.yaml.in` |
| rgw_dynamic_resharding | true | `rgw.yaml.in` |
| rgw_max_objs_per_shard | 100000 | Dynamic resharding threshold |
| rgw_safe_max_objects_per_shard | 102400 | Warning threshold of `bucket limit check` |
| rgw_max_chunk_size | 4_M | Maximum data in the head |
| rgw_obj_stripe_size | 4_M | Size of each tail stripe |
| rgw_bucket_index_max_aio | 128 | Parallelism of operations on shards |

Index entry states in `cls_rgw_types.h`: `CLS_RGW_STATE_PENDING_MODIFY = 0`, `CLS_RGW_STATE_COMPLETE = 1`, `CLS_RGW_STATE_UNKNOWN = 2`.

![The physical layout. In the index pool each bucket is divided into N .dir.<marker>.<shard> objects, and the entries are kept in their omap. In the data pool the head is stored with the name <marker>_<key> and the tails with the __shadow_ prefix. In multipart each part is a separate __multipart_ object, and CompleteMultipartUpload only builds the manifest and does not copy data. The tails of deleted or overwritten objects are removed asynchronously from the GC queue (the rgw_gc class)](figures/ch04/s02_layout.png){#fig-04-s02_layout}

```text
pseudocode: put_obj (this book's summary of rgw_rados.cc and cls_rgw.cc)
  shard = hash(key) % num_shards
  tag   = unique_op_tag()
  cls_call(index[shard], "rgw.bucket_prepare_op", {key, tag, op=ADD})
  write head  oid="<marker>_<key>"   data[0:4MiB], xattrs{manifest, acl, etag}
  for i, chunk in stripes(data[4MiB:], 4MiB):
      write tail oid="<marker>__shadow_<prefix>_<i>"
  cls_call(index[shard], "rgw.bucket_complete_op", {key, tag, size, etag, mtime})
      # inside the OSD: COMPLETE entry + update of the stats header + bilog entry
  if old version existed: enqueue old tail to GC
```

::: {.deep}
Why very large buckets get slow: an alphabetically ordered List must read from **all** shards and merge the results; its cost grows with the number of shards. On the other hand, an oversized shard (millions of omap keys) causes slow compaction in RocksDB, long scrubs and the `LARGE_OMAP_OBJECTS` warning. Dynamic resharding balances these two automatically, but in multisite it only works when the zone feature named `resharding` is enabled in the zonegroup (its constant is defined in `rgw/rgw_zone_features.h`; to check: `radosgw-admin zonegroup get | jq .enabled_features`).
:::

::: {.debug}
Inspection commands:
:::

```bash
radosgw-admin bucket stats --bucket=photos | jq '.num_shards, .usage'
radosgw-admin bucket limit check | jq '.[].buckets[] | select(.fill_status!="OK")'
radosgw-admin reshard list ; radosgw-admin reshard status --bucket=photos
radosgw-admin object stat --bucket=photos --object=a.jpg | jq '.manifest'
radosgw-admin bucket check --bucket=photos --check-objects   # without --fix it only reports
radosgw-admin gc list --include-all | jq length
ceph health detail | grep -A3 LARGE_OMAP
```

# RGW by the numbers: index shards, reshard, listing and the manifest {#sec-04-10}

The four algorithms in this section decide in which index object an S3 object is recorded, when and into how many shards a bucket is split, how much data an ordered bucket listing reads from the OSDs, and in which RADOS objects, with which names, the object's own bytes are stored. All references are to main in November 2026, and the numbers were computed with Python re-implementations of the same functions. The shard-reduction logic of dynamic reshard and the details of some factors were added or changed in recent releases. Check the code of your own release before relying on them.

## Choosing the index shard {#sec-04-10-1}

::: {.algo #alg-04-1 title="Mapping an object key to a bucket index shard" src="src/rgw/services/svc_bi_rados.h :: RGWSI_BucketIndex_RADOS::bucket_shard_index; src/rgw/driver/rados/rgw_tools.h :: rgw_shards_mod; src/common/ceph_hash.cc :: ceph_str_hash_linux" complexity="O(key length)"}
:::

```text
pseudocode
key = object name   (for multipart parts: the key of the final object, so that all parts are in one shard)
sid  = ceph_str_hash_linux(key)                         # hash = (hash + (c<<4) + (c>>4)) × 11 for each byte
sid2 = sid XOR ((sid AND 0xFF) << 24)                    # moves the low-order bits to the top
shard = n ≤ 7877 ? sid2 mod 7877 mod n : sid2 mod 65521 mod n
index oid = ".dir." + bucket_marker + "." + shard   (with a layout generation, ".dir.<marker>.<gen>.<shard>")
```

**Numeric example.** For the key `photos/2026/11/img_0001.jpg`, ceph_str_hash_linux is 2668161921. Its low byte is 0x81, and after XOR with 0x81000000 we get 503901057. 503901057 mod 7877 mod 11 = 5, so with 11 shards (the zonegroup default for a new bucket) the entry lands in `.dir.<marker>.5`. The next key, `img_0002.jpg`, goes to shard 10 and `logs/app.log` to shard 9. If the bucket moves to 23 shards, these same three keys move to shards 18, 21 and 2. That is why a reshard must rewrite **every** entry. For 100000 consecutive keys with the pattern `img_NNNNNN.jpg`, the smallest shard got 9031 entries and the largest 9162, that is ±1 percent around the mean of 9091. This hash is weak, but it spreads ordinary names well.

![Left: the spread of 100000 consecutive keys across 11 index shards. The dashed line is the mean, and every shard is within about one percent of it. Right: three sample keys step by step from hash to shard number, for both 11 and 23 shards. The XOR step moves the hash's low byte to the high byte, because the remainder modulo a small prime is more sensitive to the low bits](figures/ch04/f08_bishard.png){#fig-04-f08_bishard}

## Dynamic reshard: when, and to how many shards? {#sec-04-10-2}

::: {.algo #alg-04-2 title="Computing the preferred number of shards" src="src/rgw/driver/rados/rgw_reshard.cc :: RGWBucketReshard::calculate_preferred_shards, nearest_prime" complexity="O(log P) to search the list of 304 primes up to 1999"}
:::

```text
pseudocode
max_objs = rgw_max_objs_per_shard (100000) ; max_dyn = rgw_max_dynamic_shards (1999) ; min_dyn = 11
min_objs = min(10000, ceil(max_objs / 100))           # reduction threshold: 1000
if cur < max_dyn and objs > cur × max_objs: increase
elif cur > min_dyn and objs < cur × min_objs: reduce   (if rgw_dynamic_resharding_may_reduce, with a delay)
else: do nothing
m = multisite ? 8 : 2
new = clamp(objs × m / max_objs, min_dyn, max_dyn) ; new = the smallest prime ≥ new in the list
new = min(max_dyn, max(new, min_dyn, min_layout_shards))
```

**Numeric example.** A bucket starts with 11 shards. Suppose it is checked once every 100000 objects. At 1.2 million objects the condition 1200000 > 11 × 100000 holds. new = 1200000 × 2 / 100000 = 24, and the nearest prime greater than or equal to it is 29. The growth path in one zone is: 11 → 29 (1.2 million) → 61 (3 million) → 127 (6.2 million) → 257 (12.8 million) → 521 (25.8 million) → 1049 (52.2 million) → 1999 (105 million). In multisite, with a factor of 8, only three reshards are needed: 11 → 97 → 787 → 1999. The purpose of the larger factor is to reduce the number of reshards, because each reshard in multisite creates a new bilog generation that sync has to pass through. Reduction is also possible. If a bucket with 101 shards drops to 90000 objects, 90000 < 101 × 1000, and 11 shards are proposed. The default of `rgw_dynamic_resharding_reduction_wait` in main is 120 hours, so that a bucket that is temporarily empty is not shrunk immediately.

![Number of index shards as a function of the number of objects in the bucket, on logarithmic axes. Blue is the path of one zone with factor 2, and red is the multisite path with factor 8. Each step is a reshard, and the number next to it is the new shard count (a prime). The dotted line is the cap of 100000 objects per shard. Each time the bucket crosses it, a reshard is queued. The cap of 1999 is reached at different object counts on the two paths](figures/ch04/f09_reshard.png){#fig-04-f09_reshard}

## Ordered listing: how many entries from each shard? {#sec-04-10-3}

::: {.algo #alg-04-3 title="Number of entries requested from each shard in an ordered ListObjects" src="src/rgw/driver/rados/rgw_rados.cc :: RGWRados::calc_ordered_bucket_list_per_shard, cls_bucket_list_ordered" complexity="Each page O(s × k) entries from s shards and an O(n log s) merge"}
:::

```text
pseudocode
per_shard(n, s) = max(8, 1 + ⌊n / s⌋ + sqrt(2 n ln s / s))     # the Raab and Steger "balls into bins" analysis
k = per_shard(max_keys, shards)
read up to k entries after the marker from each shard (in parallel)
ordered merge ; if one shard ran out early and n entries were not reached: retry with k × 2^(expansion − 1) (at most 1024 times)
```

**Numeric example.** The default S3 page is a thousand keys (max-keys = 1000). With 11 shards: ⌊1000 / 11⌋ = 90 and sqrt(2000 × ln 11 / 11) ≈ 20.9, so k = 111 and the total number of entries read is 1221, that is 22 percent extra. With 101 shards: k = 1 + 9 + 9.6 ≈ 19 and the total is 1919. With 1999 shards, ⌊1000 / 1999⌋ = 0 and the root is about 2.8, but the minimum of 8 applies and a total of 15992 entries, 16 times what is needed, is read from 1999 index objects. Each shard is also a separate cls call. So a bucket with 1999 shards sends 1999 cls operations to the OSDs for every 1000-key page. If the application only needs an unordered listing (for example cleanup or backup), `allow-unordered=true` in the API or `--allow-unordered` in radosgw-admin removes this cost.

![The total number of index entries requested to build one page of an ordered listing, as a function of the number of shards, for max-keys of 1000 and 100. The dotted line of the same colour is the actual number of keys on the page. With few shards the over-read is small. From the point where n / s drops below 8, the minimum of 8 dominates, the two curves coincide, and the cost rises linearly with the number of shards. The numbers show only the first attempt, before the factor expands](figures/ch04/f10_listing.png){#fig-04-f10_listing}

## RADOS object names: head, tail and multipart {#sec-04-10-4}

::: {.algo #alg-04-4 title="The layout of an S3 object in RADOS" src="src/rgw/rgw_obj_manifest.cc :: RGWObjManifest::get_implicit_location; src/rgw/driver/rados/rgw_putobj_processor.cc :: AtomicObjectProcessor::prepare; src/rgw/driver/rados/rgw_obj_manifest.cc :: RGWObjManifest::generator::create_begin" complexity="O(size / stripe) objects per PUT"}
:::

```text
pseudocode
head_max = rgw_max_chunk_size (4 MiB)   # if the placement has inline data and the tail is in the same pool, otherwise 0
stripe   = rgw_obj_stripe_size (4 MiB, aligned with the pool alignment)
prefix   = "." + rand_alnum(32) + "_"    (normal PUT) ; name + "." + upload_id   (multipart)
location(part, stripe_no, ofs):
    part == 0 and ofs < head_max: head object = "<marker>_<name>"
    part == 0:                     ns shadow    "<marker>__shadow_" + prefix + stripe_no
    part > 0 and stripe_no == 0:   ns multipart "<marker>__multipart_" + prefix + "." + part
    part > 0:                      ns shadow    "<marker>__shadow_" + prefix + "." + part + "_" + stripe_no
```

**Numeric example.** A PUT of a 10 MiB file named `photo.jpg` in the default pool creates three RADOS objects. The head, named `<marker>_photo.jpg`, holds the first four megabytes of data along with the manifest, ACL and ETag xattrs. Two tail objects named `<marker>__shadow_.<rand32>_1` (4 MiB) and `..._2` (2 MiB) hold the rest. A multipart upload with two 10 MB parts for `big.iso` creates these: a head with no data and the manifest, and for each part an object `__multipart_big.iso.<upload>.N` with the first 4 MiB of that part and two stripes in the shadow ns named `big.iso.<upload>.N_1` and `.N_2`. In total one 20 MB S3 object is seven RADOS objects. The ETag of such an object is the md5 of the concatenated binary md5s of the parts with the suffix "-2", not the md5 of the whole file. Deleting the object immediately removes only the head. The tails go to the GC queue (`radosgw-admin gc list`) and are removed after `rgw_gc_obj_min_wait`. That is why pool space is not freed immediately after a mass deletion.

![Top: a simple 10 MB PUT. The head (yellow) holds the first four megabytes and the metadata, and two stripes in the shadow namespace (blue) with a 32-character random prefix hold the rest. Bottom: a multipart upload with two 10 MB parts. The head has no data and holds only the manifest. Each part has one object in the multipart namespace (red) for its first 4 megabytes and two stripes in the shadow namespace. The names are taken from get_implicit_location. The marker and upload id are symbolic](figures/ch04/f11_manifest.png){#fig-04-f11_manifest}

# Advanced S3 features in RGW {#sec-04-11}

## Versioning and object lock {#sec-04-11-1}

With **versioning** enabled on a bucket, every overwrite or deletion creates a new version, and earlier versions can be recovered. **Object lock** goes one step further: it makes versions undeletable and unchangeable for a set period (WORM); a key feature for protecting backups against ransomware and for legal data retention requirements.

```bash
EP="--endpoint-url https://s3.example.com --profile ceph"
aws $EP s3api create-bucket --bucket vault --object-lock-enabled-for-bucket
aws $EP s3api put-object-lock-configuration --bucket vault \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":30}}}'
aws $EP s3 cp backup-2026-11-15.tar s3://vault/
aws $EP s3api list-object-versions --bucket vault
aws $EP s3api get-object-retention --bucket vault --key backup-2026-11-15.tar
```

| Mode | Behaviour | Who can delete earlier? |
|---|---|---|
| GOVERNANCE | The version is locked until the period ends | A user with the `s3:BypassGovernanceRetention` permission |
| COMPLIANCE | The version is locked until the period ends | No S3 user, not even the owner |
| Legal Hold | A lock with no end date | Until it is removed |

::: {.warn}
Object lock in COMPLIANCE mode is final from the S3 API's point of view, but a cluster administrator with `radosgw-admin` or RADOS access can still technically delete the data. Real protection against an attacker who has reached the cluster administrator's credentials requires separation of access, monitoring and an off-site copy. Also, a bucket created with object lock cannot later be made without it; choose the default period carefully.
:::

## Lifecycle, storage classes and placement {#sec-04-11-2}

The **placement target** determines in which pools a bucket's data and index live. Each placement can have several **storage classes**, each pointing to a different data pool. **Lifecycle** rules move objects to another class or delete them after a while.

![Placement and storage classes: new data lands in the STANDARD class and, after a while, lifecycle moves it to a cold EC class or to external cloud storage](figures/ch04/f05_placement.png){#fig-04-f05_placement}

```bash
# Define the COLD class in the default zonegroup and zone
radosgw-admin zonegroup placement add --rgw-zonegroup default \
  --placement-id default-placement --storage-class COLD
radosgw-admin zone placement add --rgw-zone default \
  --placement-id default-placement --storage-class COLD \
  --data-pool default.rgw.cold.data --compression lz4
radosgw-admin period update --commit     # only if a realm is defined
```

```json
{"Rules":[{"ID":"tiering","Status":"Enabled","Filter":{"Prefix":"logs/"},
  "Transitions":[{"Days":30,"StorageClass":"COLD"}],
  "Expiration":{"Days":365},
  "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}
```

```bash
aws $EP s3api put-bucket-lifecycle-configuration --bucket logs-bucket --lifecycle-configuration file://lc.json
radosgw-admin lc list
radosgw-admin lc process --bucket logs-bucket    # run by hand for testing
```

::: {.tip}
In the lab, to see the effect of lifecycle without waiting several days, set `rgw_lc_debug_interval` to, for example, 60 so that each lifecycle "day" counts as sixty seconds. Never leave this option on in production.
:::

In recent releases lifecycle can also move objects to S3-compatible cloud storage (**cloud transition**), and in Umbrella restoring from Glacier or tape (cloud restore) has become more complete with management tools and event notifications.

## Bucket policy and IAM {#sec-04-11-3}

RGW supports the AWS policy language. The example below allows the user `ci-bot` to write only under the `artifacts/` prefix:

```json
{"Version":"2012-10-17","Statement":[{
  "Effect":"Allow",
  "Principal":{"AWS":["arn:aws:iam:::user/ci-bot"]},
  "Action":["s3:PutObject","s3:GetObject"],
  "Resource":["arn:aws:s3:::builds/artifacts/*"]}]}
```

```bash
aws $EP s3api put-bucket-policy --bucket builds --policy file://policy.json
```

With accounts (since Squid), the same policies can also be attached to users and groups with the IAM APIs, and STS can be used for temporary credentials and AssumeRoleWithWebIdentity (OIDC).

## Server-side encryption {#sec-04-11-4}

RGW supports SSE-C (key from the client), SSE-KMS (key from Vault, KMIP or Barbican) and SSE-S3. Umbrella added AES-256-GCM encryption, and CopyObject also works for encrypted objects.

::: {.warn}
SSE-C and SSE-KMS are only allowed over an HTTPS connection. If you terminate TLS at the load balancer, tell RGW that requests arrived securely (`rgw_trust_forwarded_https = true`), and turn this on only when you are sure the load balancer always sets or strips this header itself.
:::

## Event notification and bucket logging {#sec-04-11-5}

RGW can send events such as object creation or deletion to Kafka, AMQP (RabbitMQ) or HTTP; a basis for event-driven processing (for example generating a thumbnail after a photo upload):

```bash
aws $EP sns create-topic --name uploads \
  --attributes '{"push-endpoint":"kafka://kafka.example.com:9092","persistent":"true"}'
aws $EP s3api put-bucket-notification-configuration --bucket photos \
  --notification-configuration '{"TopicConfigurations":[{"Id":"n1","TopicArn":"arn:aws:sns:default::uploads","Events":["s3:ObjectCreated:*"]}]}'
```

**Bucket logging** (recording each bucket's requests in another bucket) was added in Tentacle according to the documentation, and in Umbrella it gained a journal mode, support for EC pools and management commands.

# Day-to-day RGW operations {#sec-04-12}

## Frequently used commands {#sec-04-12-1}

```bash
radosgw-admin bucket list
radosgw-admin bucket stats --bucket=photos
radosgw-admin bucket limit check            # shards near the threshold
radosgw-admin reshard list
radosgw-admin reshard add --bucket=photos --num-shards=101
radosgw-admin gc list --include-all | head
radosgw-admin gc process
radosgw-admin usage show --uid=alice --start-date=2026-11-01
radosgw-admin bucket check --bucket=photos --check-objects --fix
```

::: {.deep}
Deleting an object in RGW does not free space immediately. The head object is removed, but the tail objects are handed to the **garbage collector** and removed after `rgw_gc_obj_min_wait` (default two hours). If you did a mass deletion and `ceph df` did not change, look at the gc queue. On busy clusters you may need to tune the `rgw_gc_max_concurrent_io` and `rgw_gc_processor_period` parameters.
:::

## Troubleshooting {#sec-04-12-2}

::: {.debug}
Symptoms and how to investigate:

The `SignatureDoesNotMatch` error: a clock difference of more than 15 minutes between client and server, or a load balancer that changes the Host header, or path-style versus virtual-host confusion.

The `NoSuchBucket` error even though the bucket exists: the client uses virtual-host, but `rgw_dns_name` or the zonegroup hostnames are not set, so RGW cannot tell the bucket name from Host.

Very slow listing: the index on HDD, a bucket without enough shards, or millions of deleted versions in a versioned bucket.

The `LARGE_OMAP_OBJECTS` warning: large index shards; find the guilty bucket with `radosgw-admin bucket limit check`.

To see the details of a request, temporarily raise `debug_rgw`: `ceph config set client.rgw debug_rgw 20`, and put it back after reproducing the problem.
:::

# Supplementary and up to date {#sec-04-13}

- **ingress and certmgr in cephadm:** the load balancer and certificates are now part of the orchestrator.
- **Accounts and IAM (Squid onwards):** self-service management of users, groups, roles and policies; Umbrella added GetAccountSummary, account-level PublicAccessBlock, account quota management APIs and S3 Object Ownership (disabling ACLs).
- **S3 GetObjectAttributes** was added in Tentacle, and for AWS compatibility the LastModified time is rounded to the second.
- **Full object dedup** arrived in Umbrella as a technical preview.
- **The Redis-based D4N cache** is under development.
- **Lua scripting:** RGW allows Lua scripts to run at various stages of request processing (for example for custom logging or changing behaviour); Umbrella added the new `postAuth` hook.

# Summary and review {#sec-04-14}

## Chapter summary {#sec-04-14-1}

::: {.summary title="Key points"}

- RGW is a stateless HTTP server that implements S3 and Swift on RADOS; with cephadm and the ingress service it scales horizontally with ease.
- Each S3 object has a head object, a number of tails and an entry in the bucket index; the index must be on SSD and replicated.
- Users, subusers, tenants and accounts are different levels of identity and multi-tenancy; consider accounts for a new design.
- Virtual-host access requires wildcard DNS, `rgw_dns_name` and a wildcard certificate.
- Keystone and S3A connect RGW to OpenStack and the data ecosystem.
- Versioning, object lock, lifecycle, storage classes, policies, SSE and event notification have turned RGW into a complete S3 service.

:::

## Common mistakes {#sec-04-14-2}

- The index pool on HDD or EC.
- Running a single RGW instance without a load balancer.
- Forgetting lifecycle for incomplete multipart uploads.
- Expecting space to be freed immediately after deletion (not knowing about gc).
- Creating a bucket with object lock in COMPLIANCE mode with a long period for testing.
- Clock differences between clients and RGW.

## Hands-on exercise {#sec-04-14-3}

1. Deploy RGW with two instances and an ingress service, and show that the service does not stop when you stop one instance.
2. Create a user with a 1 GB quota and observe RGW's behaviour when the quota is exceeded.
3. Create a bucket with versioning, overwrite a file three times and then delete it, and use `list-object-versions` to see all the versions and the delete marker. Restore the second version.
4. Create a cold storage class on an EC pool and watch objects being transitioned in the lab with lifecycle and `rgw_lc_debug_interval`.
5. Write 100,000 small objects to one bucket (for example with `s3-benchmark` or a parallel script) and observe dynamic resharding with `bucket limit check` and `reshard list`.

## Review questions {#sec-04-14-4}

1. Why do we call RGW "stateless", and what effect does this have on high-availability design?
2. Which objects does a 20 MB S3 object become in RADOS?
3. Why should the index pool not be EC or on HDD?
4. What problem does dynamic resharding solve, and what is its default threshold?
5. What is the difference between a tenant and an account?
6. Which configuration is needed for virtual-hosted-style access?
7. How do the GOVERNANCE and COMPLIANCE modes of object lock differ?
8. Why is cluster space not freed immediately after a mass deletion of objects?
9. What does the `rgw_s3_auth_use_keystone` option make possible?
10. Why do S3A committers matter for Spark on RGW?

## Sources for this chapter {#sec-04-14-5}

- Ceph documentation — Ceph Object Gateway: https://docs.ceph.com/en/latest/radosgw/
- cephadm documentation — The RGW and ingress services: https://docs.ceph.com/en/latest/cephadm/services/rgw/
- Ceph documentation — Managing RGW with radosgw-admin: https://docs.ceph.com/en/latest/radosgw/admin/
- Ceph documentation — User Accounts: https://docs.ceph.com/en/latest/radosgw/account/
- Ceph documentation — Keystone integration: https://docs.ceph.com/en/latest/radosgw/keystone/
- Ceph documentation — Placement and storage classes: https://docs.ceph.com/en/latest/radosgw/placement/
- Ceph documentation — Dynamic resharding: https://docs.ceph.com/en/latest/radosgw/dynamicresharding/
- Ceph documentation — Bucket event notification: https://docs.ceph.com/en/latest/radosgw/notifications/
- Ceph documentation — Server-side encryption: https://docs.ceph.com/en/latest/radosgw/encryption/
- Ceph documentation — S3 API compatibility: https://docs.ceph.com/en/latest/radosgw/s3/
- Apache Hadoop documentation — The S3A connector: https://hadoop.apache.org/docs/stable/hadoop-aws/tools/hadoop-aws/index.html
- AWS documentation — S3 Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
