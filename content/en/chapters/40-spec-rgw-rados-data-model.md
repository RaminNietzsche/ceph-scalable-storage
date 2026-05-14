---
chapter: 40
id: ch40
title: 'بخش تخصصی (۷): RGW — مدل داده روی RADOS: فراداده، bucket index، نسخه‌بندی، manifest و multipart'
part: specialist
lang: en
translation: pending
---

# پیش از شروع {#sec-40-1}

فصل ۴ نشان داد RGW هر شیء S3 را در دو جا نگه می‌دارد (ایندکس bucket و داده) و الگوریتم‌های انتخاب shard، reshard، فهرست‌گیری و نام اشیای head و tail را آورد. این فصل یک لایه پایین‌تر می‌رود: فراداده‌ی کاربر و bucket دقیقاً در کدام pool و namespace است، یک ورودی ایندکس چه فیلدهایی دارد و کلیدهایش در omap چگونه ساخته می‌شوند، به‌روزرسانی دومرحله‌ای ایندکس چگونه با شکست کنار می‌آید، نسخه‌بندی با OLH چگونه پیاده شده، manifest چگونه head و tail را در placement و storage class می‌چیند، و multipart چگونه بدون کپی داده کامل می‌شود. فصل با مرجع `radosgw-admin` تمام می‌شود. نام‌ها و پیش‌فرض‌ها با شاخه‌ی main مخزن ceph/ceph (نوامبر ۲۰۲۶) تطبیق داده شده‌اند.

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-40-1-1}

- اطلاعات کاربر، کلیدها و bucketها در کدام اشیای RADOS است؟
- ورودی ایندکس یک شیء چه فیلدهایی دارد و کلیدهای `0x80` در omap ایندکس چه هستند؟
- اگر RGW بین نوشتن داده و به‌روزرسانی ایندکس از کار بیفتد چه می‌شود؟
- نسخه‌ی «جاری» یک شیء در bucket نسخه‌دار چگونه انتخاب می‌شود؟
- head یک شیء در کدام pool نوشته می‌شود اگر storage class آن COLD باشد؟
- ETag یک شیء چندبخشی چگونه محاسبه می‌شود؟

## پیش‌نیاز {#sec-40-1-2}

فصل ۴ (RGW)، فصل ۱۵ (cls)، فصل ۳۴ (omap و xattr) و فصل ۳۶ (اتمی بودن cls).

# فراداده: poolها و namespaceها {#sec-40-2}

هر zone مجموعه‌ای از pool دارد که بیشترشان با **namespace** درون چند pool مشترک پیاده می‌شوند (`rgw::init_zone_pool_names` در `rgw_zone.cc`). نام کامل با پیشوند zone ساخته می‌شود؛ برای zone ‏`default`:

| کاربرد | pool:namespace |
|---|---|
| bucket entrypoint و bucket instance | `default.rgw.meta:root` |
| کاربر بر اساس uid | `default.rgw.meta:users.uid` |
| نگاشت access key به کاربر | `default.rgw.meta:users.keys` |
| نگاشت email و Swift | `default.rgw.meta:users.email`، `users.swift` |
| نقش‌ها، account و group، OIDC | `default.rgw.meta:roles`، `accounts`، `groups`، `oidc` |
| gc، lc، reshard، usage، notif، logging | `default.rgw.log:gc`، `:lc`، `:reshard`، `:usage`، `:notif`، `:logging` |
| datalog، mdlog و bilog trim | `default.rgw.log` |
| watch/notify میان RGWها | `default.rgw.control` |
| ایندکس bucketها | `default.rgw.buckets.index` (از placement) |
| داده | `default.rgw.buckets.data` (از storage class) |
| فراداده‌ی multipart | `default.rgw.buckets.non-ec` (`data_extra_pool` از placement) |

**bucket** دو شیء فراداده دارد. **entrypoint** با نام خود bucket (یا `<tenant>/<bucket>`) در `root` فقط به instance فعلی اشاره می‌کند. **instance** با نام `.bucket.meta.<bucket>:<bucket-id>` همه‌ی ویژگی‌ها را دارد: placement، تعداد shard و layout ایندکس، مالک، پرچم versioning و object lock، و xattrهایی مثل policy، lifecycle و CORS. reshard یک instance تازه با bucket-id جدید می‌سازد و فقط entrypoint را جابه‌جا می‌کند.

```bash
# مثال: دیدن فراداده‌ی یک bucket و کاربر
radosgw-admin metadata get bucket:photos
radosgw-admin metadata get bucket.instance:photos:a1b2c3d4-0000-4000-8000-1234567890ab.4123.7
rados -p default.rgw.meta -N users.keys ls | head -3
```

```text
مثال (خروجی کوتاه‌شده):
{ "key": "bucket:photos",
  "data": { "bucket": { "name": "photos", "marker": "a1b2c3d4-...4123.7", "bucket_id": "a1b2c3d4-...4123.7" },
            "owner": "alice", "creation_time": "2026-11-02T08:14:33.120Z" } }
AKIAEXAMPLE7Q2WZ3L
AKIAEXAMPLEM9K1D0B
AKIAEXAMPLEP5T8H4N
```

`marker` همان پیشوندی است که نام اشیای داده و ایندکس از آن ساخته می‌شود (فصل ۴) و پس از reshard تغییر **نمی‌کند**، درحالی‌که `bucket_id` تغییر می‌کند. فهرست `users.keys` فقط شناسه‌ی access key است؛ کلید محرمانه درون رکورد کاربر است و هرگز نباید در لاگ یا گزارش آورده شود.

# bucket index {#sec-40-3}

## اشیا و کلیدها {#sec-40-3-1}

ایندکس هر bucket در اشیای `.dir.<marker>.<shard>` (یا برای نسل‌های پس از reshard ‏`.dir.<marker>.<gen>.<shard>`) در pool ایندکس است. هر شیء ایندکس فقط omap دارد. header ‏omap آمار shard (تعداد، حجم، حجم واقعی هر category) و نسخه‌ی ایندکس را نگه می‌دارد. کلیدهای omap چند **فضای کلید** دارند (`cls_rgw.cc`):

| فضا | قالب کلید | محتوا |
|---|---|---|
| ورودی معمولی | `<name>` | `rgw_bucket_dir_entry` نسخه‌ی جاری (یا شیء نسخه‌نشده) |
| bilog (حالت InIndex) | `0x80` + `0_` + `<index_ver:%011llu>.<osd ver>.<subop>` | ورودی bilog برای multisite (فصل ۴۲) |
| instance | `0x80` + `1000_` + `<name>` + `\0i` + `<instance>` | یک نسخه از شیء در bucket نسخه‌دار |
| OLH | `0x80` + `1001_` + `<name>` | `rgw_bucket_olh_entry`: نسخه‌ی جاری و log تغییرات |
| reshard log | `0x80` + `2001_` + … | تغییرهای حین reshard |

چون در UTF-8 هیچ نامی با بایت `0x80` شروع نمی‌شود (این بایت فقط بایت ادامه‌ی یک نویسه‌ی چندبایتی است)، تابع `bi_entry_type` در cls ‏rgw با نگاه به بایت اول کلید معمولی را از ویژه جدا می‌کند. کلیدهای ویژه پس از همه‌ی نام‌های ASCII و پیش از نام‌هایی که با نویسه‌های غیر ASCII (بایت اول `0xC2` به بعد) شروع می‌شوند مرتب می‌شوند؛ ازاین‌رو فهرست‌گیری (`get_obj_vals`) باید بازه‌ی `0x80`ها را صریحاً رد کند و فقط «یک اسکن تا 0x80» کافی نیست.

![کلیدهای ویژه در omap یک shard ایندکس. کلید instance از 0x80، پیشوند ‏1000_، نام، بایت صفر، حرف i و شناسه‌ی نسخه ساخته می‌شود؛ OLH فقط پیشوند ‏1001_ و نام دارد؛ bilog شماره‌ی ‏index_ver صفرپرشده‌ی یازده‌رقمی دارد تا ترتیب واژگانی همان ترتیب عددی باشد](figures/ch40/f01_index.png){#fig-40-f01_index}

## ورودی ایندکس {#sec-40-3-2}

`rgw_bucket_dir_entry` این فیلدها را دارد: `key` (name و instance)، `ver` (pool و epoch، یعنی نسخه‌ی RADOS شیء head)، `locator`، `exists`، `meta` (category، size، mtime، etag، owner، owner_display_name، content_type، accounted_size، user_data، storage_class، appendable و وضعیت restore)، `pending_map` (عملیات نیمه‌تمام)، `index_ver`، `tag`، `flags` (`VER`، `CURRENT`، `DELETE_MARKER`، `VER_MARKER`) و `versioned_epoch`.

`accounted_size` اندازه‌ای است که کاربر دیده (پیش از فشرده‌سازی یا رمزنگاری) و `size` اندازه‌ی واقعی ذخیره‌شده؛ سهمیه و آمار bucket بر پایه‌ی `accounted_size` حساب می‌شوند.

## به‌روزرسانی دومرحله‌ای {#sec-40-3-3}

نوشتن داده و به‌روزرسانی ایندکس در دو شیء جدا (و معمولاً دو OSD جدا) است و RADOS تراکنش میان‌شیئی ندارد. RGW این دو را با یک پروتکل دومرحله‌ای هماهنگ می‌کند.

::: {.algo #alg-40-1 title="prepare و complete در bucket index" src="src/cls/rgw/cls_rgw.cc :: rgw_bucket_prepare_op، rgw_bucket_complete_op، rgw_dir_suggest_changes؛ src/rgw/driver/rados/rgw_rados.cc :: RGWRados::Bucket::UpdateIndex" complexity="دو فراخوانی cls روی shard ایندکس به‌ازای هر PUT یا DELETE"}
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

![توالی به‌روزرسانی دومرحله‌ای: prepare برچسب عملیات را در ‏pending_map می‌گذارد، داده نوشته می‌شود، complete برچسب را برمی‌دارد و ورودی، آمار و bilog را به‌روز می‌کند. اگر complete نرسد، فهرست‌گیری بعدی وضعیت head را بررسی و با dir_suggest_changes ورودی را اصلاح می‌کند](figures/ch40/f03_twophase.png){#fig-40-f03_twophase}

پیامد عملی: ایندکس ممکن است برای مدتی کوتاه با داده ناسازگار باشد (شیء نوشته شده ولی هنوز در فهرست نیست، یا برعکس)، ولی **فهرست‌گیری خودش را ترمیم می‌کند**. `radosgw-admin bucket check --fix --check-objects` همین بررسی را برای همه‌ی ورودی‌ها انجام می‌دهد.

# نسخه‌بندی و OLH {#sec-40-4}

در bucket نسخه‌دار هر نسخه یک شیء head جدا با `instance` تصادفی (مثلاً `3sL4kqtJlcpXroDTDmJ+rmSpXd3dIbrHY`) دارد. نسخه‌ی جاری با یک **OLH** ‏(object logical head) مشخص می‌شود: یک ورودی `1001_` در ایندکس و یک شیء head بدون داده با نام اصلی، که در xattrهای `user.rgw.olh.info`، `user.rgw.olh.ver`، `user.rgw.olh.idtag` و `user.rgw.olh.pending.*` به instance جاری اشاره می‌کند.

::: {.algo #alg-40-2 title="link_olh: افزودن نسخه و تعیین نسخه‌ی جاری" src="src/cls/rgw/cls_rgw.cc :: rgw_bucket_link_olh؛ src/rgw/driver/rados/rgw_rados.cc :: RGWRados::set_olh، apply_olh_log" complexity="چند خواندن و نوشتن omap روی یک shard؛ سپس یک به‌روزرسانی xattr روی head ‏OLH"}
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

**مثال.** شیء `report.pdf` سه بار آپلود و سپس بدون versionId حذف شده است. ایندکس چهار ورودی instance (سه نسخه و یک delete marker با پرچم `DELETE_MARKER|CURRENT`)، یک ورودی OLH و یک ورودی معمولی دارد. `GET report.pdf` به OLH نگاه می‌کند، می‌بیند نسخه‌ی جاری delete marker است و 404 برمی‌گرداند. `GET report.pdf?versionId=<v2>` مستقیم head نسخه‌ی دوم را می‌خواند.

::: {.note}
شیئی که پیش از روشن کردن versioning نوشته شده، instance خالی دارد و در API به‌صورت `versionId=null` دیده می‌شود. نوشتن دوباره در حالت `Suspended` هم همان null را بازنویسی می‌کند.
:::

# manifest، placement و storage class {#sec-40-5}

## قواعد چیدمان {#sec-40-5-1}

هر bucket یک **placement target** دارد (از zonegroup) که در zone به سه pool نگاشت می‌شود: `index_pool`، `data_extra_pool` و برای هر **storage class** یک `data_pool` (با فشرده‌سازی اختیاری). head همیشه در pool ‏storage class پیش‌فرض (`STANDARD`) placement ‏bucket است؛ اگر شیء storage class دیگری داشته باشد، head فقط فراداده (manifest و xattrها) دارد و همه‌ی داده در tail در pool همان class است.

::: {.algo #alg-40-3 title="تعیین اندازه‌ی head، chunk و stripe برای یک PUT" src="src/rgw/driver/rados/rgw_putobj_processor.cc :: AtomicObjectProcessor::prepare؛ src/rgw/rgw_obj_manifest.cc :: set_trivial_rule" complexity="O(1) برای ساخت قاعده؛ O(size / stripe) شیء tail"}
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

**مثال عددی.** یک PUT ‏10 MiB در کلاس STANDARD: head ‏4 MiB داده دارد و دو tail ‏4 MiB و 2 MiB ساخته می‌شوند (سه شیء RADOS). همان PUT با `x-amz-storage-class: COLD`: head بدون داده در pool ‏STANDARD و سه tail ‏4، 4 و 2 MiB در pool ‏COLD. پس حتی برای کلاس سرد، pool ‏STANDARD به ازای هر شیء یک head کوچک دارد؛ این نکته در طراحی ظرفیت pool ‏SSD اهمیت دارد. انتقال lifecycle (فصل ۴۱) هم همین الگو را می‌سازد: tail جدید در pool مقصد و manifest تازه روی همان head.

![چیدمان یک شیء 10 MiB در دو حالت. در STANDARD، head چهار مگابایت اول را دارد و دو tail بقیه را. در COLD، head فقط manifest و xattrها را در pool ‏STANDARD نگه می‌دارد و همه‌ی داده در سه tail در pool ‏COLD است](figures/ch40/f02_manifest.png){#fig-40-f02_manifest}

# multipart {#sec-40-6}

::: {.algo #alg-40-4 title="آپلود چندبخشی: init، part و complete" src="src/rgw/driver/rados/rgw_sal_rados.cc :: RadosMultipartUpload::init، complete؛ src/rgw/driver/rados/rgw_putobj_processor.cc :: MultipartObjectProcessor::complete؛ src/rgw/rgw_multi.h" complexity="complete ‏O(P) برای P بخش؛ بدون کپی داده"}
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

**مثال عددی.** سه بخش 5، 5 و 2 MiB که به‌ترتیب با `A`، `B` و `C` پر شده‌اند ETagهای `b8fc857a25e7958868c2f003d5e0952d`، `ba8c3fac0e224c9b79a8e74bebd54654` و `bf52955b454974e73c3e2694bd7207c4` دارند. ETag نهایی md5 الحاق ۴۸ بایت دودویی آن‌هاست: `eacd2737fa049d51213f10cdc5732ece-3`. این مقدار با md5 کل فایل یکی **نیست**؛ ابزاری که ETag را با md5 فایل مقایسه می‌کند باید پسوند `-N` را بشناسد.

پیشوند `2~` در upload_id نشان می‌دهد کلیدهای بخش‌ها با `%08d` و مرتب ذخیره شده‌اند. uploadهای قدیمی (پیشوند `2/`) بخش‌ها را بدون صفر ابتدایی ذخیره می‌کردند و complete باید آن‌ها را عددی مرتب می‌کرد.

# مرجع radosgw-admin {#sec-40-7}

| دستور | کاربرد |
|---|---|
| `radosgw-admin user {create,info,modify,suspend,enable,rm,list}` | کاربران |
| `radosgw-admin key {create,rm}` / `subuser {create,modify,rm}` | کلیدها و subuserها |
| `radosgw-admin account {create,get,modify,rm}` | accountها (IAM) |
| `radosgw-admin bucket {list,stats,link,unlink,chown,rm}` | bucketها |
| `radosgw-admin bucket check [--fix] [--check-objects]` | بررسی و ترمیم ایندکس |
| `radosgw-admin bucket reshard --bucket B --num-shards N` / `reshard {add,list,status,process,cancel}` | reshard |
| `radosgw-admin bucket limit check` | shardهای پرشده |
| `radosgw-admin bi {get,list,put,purge}` | ورودی‌های خام ایندکس (با احتیاط) |
| `radosgw-admin object stat --bucket B --object K` | manifest و xattrهای یک شیء |
| `radosgw-admin object {rm,unlink,rewrite}` | عملیات روی یک شیء |
| `radosgw-admin quota {set,enable,disable} --quota-scope {user,bucket}` / `user stats --sync-stats` | سهمیه |
| `radosgw-admin ratelimit {set,get,enable,disable} --ratelimit-scope {user,bucket,anonymous}` | محدودیت نرخ |
| `radosgw-admin gc {list,process} [--include-all]` | garbage collection |
| `radosgw-admin lc {list,get,process,reshard fix}` | lifecycle |
| `radosgw-admin usage {show,trim}` | گزارش مصرف (اگر روشن باشد) |
| `radosgw-admin metadata {list,get,put,rm} SECTION[:KEY]` | فراداده‌ی خام |
| `radosgw-admin zonegroup placement {list,add,modify}` / `zone placement {list,add,modify}` | placement و storage class |
| `radosgw-admin {realm,zonegroup,zone,period} ...` / `sync status` | multisite (فصل ۴۲) |
| `radosgw-admin orphans` / `rgw-orphan-list` | یافتن اشیای یتیم در pool داده |

```bash
# مثال: manifest یک شیء 10 MiB در STANDARD
radosgw-admin object stat --bucket photos --object big.bin | jq '.manifest | {obj_size, head_size, max_head_size, rules}'
```

```text
مثال (خروجی):
{
  "obj_size": 10485760,
  "head_size": 4194304,
  "max_head_size": 4194304,
  "rules": [ { "key": 0, "val": { "start_part_num": 0, "start_ofs": 4194304, "part_size": 0,
               "stripe_max_size": 4194304, "override_prefix": "" } } ]
}
```

# تنظیم و عیب‌یابی {#sec-40-8}

- **فهرست‌گیری کند و `bucket stats` نادرست:** ورودی‌های pending قدیمی زیادند. `radosgw-admin bucket check --check-objects --fix` را در زمان خلوت اجرا کنید.
- **large omap در pool ایندکس:** shard بیش از `rgw_max_objs_per_shard` ‏(100000) ورودی دارد یا (در حالت InIndex) bilog trim نشده است. `bucket limit check` و `bilog list` را ببینید (فصل ۴۲).
- **pool ‏STANDARD با وجود کلاس سرد پر می‌شود:** هر شیء یک head در STANDARD دارد؛ برای میلیاردها شیء کوچک این خودش حجم و تعداد شیء زیادی است.
- **فضای pool داده آزاد نمی‌شود:** tailهای حذف‌شده منتظر gc هستند (پیش‌فرض دست‌کم 2 ساعت؛ فصل ۴۱). `gc list --include-all` را ببینید.
- **multipartهای رهاشده:** فقط lifecycle با `AbortIncompleteMultipartUpload` یا `radosgw-admin bucket rm --purge-objects` آن‌ها را پاک می‌کند؛ `rados ls` روی `data_extra_pool` تعدادشان را نشان می‌دهد.

# تکمیلی و به‌روز {#sec-40-9}

- در شاخه‌ی main، `epoch` نسخه‌ها در link_olh از زمان جاری به نانوثانیه گرفته می‌شود (مگر از multisite بیاید). نسخه‌های قدیمی‌تر رفتار دیگری داشتند و همین در مقایسه‌ی نسخه‌ها میان zoneها اهمیت دارد.
- گزینه‌ی `inline_data` در placement (پیش‌فرض روشن) تعیین می‌کند head داده داشته باشد یا نه؛ خاموش کردن آن برای poolهای EC که head کوچک را بد نگه می‌دارند سودمند است.
- در شاخه‌ی main، bucketهای جدید به‌طور پیش‌فرض bilog را به‌جای omap ایندکس در FIFO جدا نگه می‌دارند (`rgw_default_bucket_bilog_type = fifo`)؛ کلیدهای `0_` فقط در حالت `inindex` و bucketهای قدیمی دیده می‌شوند.
- poolهای `:accounts`، `:groups` و `:vector` و `dedup_pool` در نسخه‌های جدید اضافه شده‌اند؛ پیش از تکیه بر آن‌ها نسخه‌ی خود را بررسی کنید.

# تمرین عملی {#sec-40-10}

1. یک bucket بسازید و با `rados -p default.rgw.meta -N root ls` entrypoint و instance آن را پیدا کنید. پس از `bucket reshard` دوباره نگاه کنید.
2. با `rados -p default.rgw.buckets.index listomapkeys .dir.<marker>.0 | xxd | head` کلیدهای `0x80` را در یک bucket نسخه‌دار ببینید.
3. یک شیء 10 MiB را یک بار در STANDARD و یک بار در COLD آپلود کنید و با `object stat` و `rados ls` جای head و tailها را مقایسه کنید.
4. یک آپلود سه‌بخشی انجام دهید، ETag نهایی را با محاسبه‌ی دستی (md5 الحاق md5ها) تطبیق دهید.

# پرسش‌های مرور {#sec-40-11}

1. entrypoint و instance یک bucket چه فرقی دارند و reshard کدام را عوض می‌کند؟
2. کلید ورودی bilog در omap ایندکس چه ساختاری دارد؟
3. چرا کلیدهای ویژه با بایت 0x80 شروع می‌شوند؟
4. `size` و `accounted_size` در ورودی ایندکس چه فرقی دارند؟
5. اگر RGW پس از prepare و نوشتن داده ولی پیش از complete از کار بیفتد، ورودی چگونه ترمیم می‌شود؟
6. OLH چیست و در کجا ذخیره می‌شود؟
7. حذف بدون versionId در bucket نسخه‌دار چه می‌کند؟
8. head یک شیء COLD در کدام pool است و چه دارد؟
9. ETag آپلود سه‌بخشی چگونه ساخته می‌شود؟
10. پیشوند `2~` در upload_id چه چیزی را نشان می‌دهد؟

# منابع این فصل {#sec-40-12}

- cls_rgw.cc و cls_rgw_types.h: https://github.com/ceph/ceph/blob/main/src/cls/rgw/cls_rgw.cc
- rgw_zone.cc (نام poolها): https://github.com/ceph/ceph/blob/main/src/rgw/rgw_zone.cc
- rgw_putobj_processor.cc: https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_putobj_processor.cc
- rgw_sal_rados.cc (multipart): https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_sal_rados.cc
- مستند bucket index و layout: https://docs.ceph.com/en/latest/dev/radosgw/bucket_index/
- مستند placement و storage class: https://docs.ceph.com/en/latest/radosgw/placement/
- radosgw-admin: https://docs.ceph.com/en/latest/man/8/radosgw-admin/
