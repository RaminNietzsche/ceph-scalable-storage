---
chapter: 37
id: ch37
title: "بخش تخصصی (۴): RBD — چیدمان روی RADOS، striping، object map و fast-diff، و مرجع rbd"
part: specialist
lang: fa
---

::: {.tldr}

- هر image با قالب ۲ از `rbd_id`، omap شیء `rbd_header.<id>` و اشیای داده‌ی `rbd_data.<id>.<objectno>` تشکیل می‌شود؛ متادیتا فقط از راه کلاس rbd تغییر می‌کند.
- striping پیش‌فرض اشیای پشت‌سرهم ۴ مگابایتی است؛ striping سفارشی نوشتن‌های کوچک ترتیبی را به‌صورت round-robin میان `stripe_count` شیء پخش می‌کند.
- object map برای هر شیء دو بیت نگه می‌دارد تا fast-diff و `rbd du` لازم نباشد تک‌تک اشیا را بپرسند.
- فصل با مرجع فرمان‌های rbd تمام می‌شود.

```bash
rados -p rbd listomapkeys rbd_header.5f3a2b8c1d4e
```

[![چیدمان یک image در RBD با data pool جدا: header، directory، object map و اشیای داده](figures/ch37/f01_layout.png)](#fig-37-f01_layout)

:::

# پیش از شروع {#sec-37-1}

فصل ۲ نشان داد یک image قالب 2 چه اشیایی دارد و شناسه‌ی آن چگونه ساخته می‌شود (الگوریتم ۲-۱). این فصل همان چیدمان را کلید به کلید باز می‌کند: header یک image دقیقاً چه کلیدهای omap دارد، اشیای سطح pool (`rbd_directory`، `rbd_trash`، `rbd_mirroring`، `rbd_namespace` و دیگران) چه چیزی نگه می‌دارند، striping با `stripe_unit` و `stripe_count` آفست را چگونه به شیء می‌برد، object map بیت‌ها را چگونه بسته‌بندی و ذخیره می‌کند، و fast-diff چگونه بدون خواندن داده تغییرات میان دو snapshot را می‌یابد. فصل با مرجع کامل دستور `rbd` و `rbd-nbd` تمام می‌شود. نام‌ها با شاخه‌ی main مخزن ceph/ceph (نوامبر ۲۰۲۶) تطبیق داده شده‌اند.

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-37-1-1}

- header یک image چه کلیدهایی دارد و هر کدام چه کسی آن را می‌نویسد؟
- نام شیء داده با data pool جدا چه فرقی می‌کند؟
- با `stripe_unit=64K` و `stripe_count=4`، آفست 1000000 در کدام شیء است؟
- object map هر شیء را با چند بیت نگه می‌دارد و بایت‌ها روی دیسک چه ترتیبی دارند؟
- `EXISTS_CLEAN` چه معنایی دارد و چه زمانی تنظیم می‌شود؟
- fast-diff از کدام حالت‌ها برای تشخیص تغییر استفاده می‌کند؟
- pool و namespace و trash و گروه‌ها در RADOS چگونه نمایه می‌شوند؟

## پیش‌نیاز {#sec-37-1-2}

فصل ۲ (RBD)، فصل ۱۵ (cls)، فصل ۳۴ و ۳۶ (omap، SnapContext و clone).

# اشیای یک image {#sec-37-2}

## header {#sec-37-2-1}

همه‌ی فراداده‌ی یک image قالب 2 در omap شیء `rbd_header.<id>` است و فقط از طریق متدهای کلاس `rbd` (`src/cls/rbd/cls_rbd.cc`) تغییر می‌کند:

| کلید omap | نوع | محتوا |
|---|---|---|
| `size` | u64 | اندازه‌ی image به بایت |
| `order` | u8 | لگاریتم دودویی اندازه‌ی شیء (22 یعنی 4 MiB) |
| `object_prefix` | string | پیشوند اشیای داده، مثلاً `rbd_data.5f3a2b8c1d4e` |
| `features` | u64 | بیت‌های ویژگی (جدول بعد) |
| `flags` | u64 | `OBJECT_MAP_INVALID` ‏(1) و `FAST_DIFF_INVALID` ‏(2) |
| `op_features` | u64 | ویژگی‌های عملیاتی مثل clone-parent، clone-child، group، snap-trash |
| `snap_seq` | u64 | بزرگ‌ترین snap id ساخته‌شده برای این image |
| `snapshot_<id:016x>` | cls_rbd_snap | نام، اندازه، parent، پرچم‌ها و namespace هر snapshot |
| `snap_children_<id:016x>` | set | فرزندان clone قالب 2 روی آن snapshot |
| `parent` | cls_rbd_parent | pool، namespace، image و snap والد و overlap (برای clone) |
| `stripe_unit`، `stripe_count` | u64 | فقط اگر striping سفارشی باشد |
| `data_pool_id` | s64 | فقط اگر data pool جدا باشد |
| `create_timestamp`، `access_timestamp`، `modify_timestamp` | utime | زمان‌ها |
| `snap_limit` | u64 | سقف تعداد snapshot |
| `metadata_<key>` | string | متادیتای image؛ مثلاً `conf_rbd_cache` برای تنظیمات هر image |
| `migration` | cls_rbd_migration | وضعیت مهاجرت زنده |

افزون بر omap، xattr ‏`lock.rbd_lock` (کلاس `lock`) قفل مشورتی را نگه می‌دارد که ManagedLock برای exclusive-lock از آن استفاده می‌کند (فصل ۳۸). همین شیء header هدف watch همه‌ی کلاینت‌های باز آن image است.

| ویژگی | بیت | پیش‌فرض |
|---|---|---|
| `layering` | 1 | بله |
| `striping` | 2 | فقط اگر stripe سفارشی باشد |
| `exclusive-lock` | 4 | بله |
| `object-map` | 8 | بله |
| `fast-diff` | 16 | بله |
| `deep-flatten` | 32 | بله |
| `journaling` | 64 | خیر |
| `data-pool` | 128 | فقط اگر `--data-pool` داده شود |
| `operations` | 256 | داخلی |
| `migrating` | 512 | داخلی |
| `non-primary` | 1024 | داخلی، برای image مقصد mirror |
| `dirty-cache` | 2048 | داخلی، برای cache پایدار PWL |

مجموع پیش‌فرض (`rbd_default_features`) برابر 1+4+8+16+32 = 61 است.

## اشیای داده و object map {#sec-37-2-2}

اشیای داده `<object_prefix>.<objectno:016x>` نام دارند. اگر image با `--data-pool` ساخته شود، header و فراداده در pool اصلی می‌مانند (که باید replicated باشد) و داده در pool دوم (اغلب EC با `allow_ec_overwrites`) نوشته می‌شود. در این حالت پیشوند شامل شناسه‌ی pool اصلی است: `rbd_data.<metadata-pool-id>.<image-id>`، تا اشیای imageهای چند pool مختلف در یک data pool مشترک با هم برخورد نکنند.

object map در شیء `rbd_object_map.<id>` برای head و `rbd_object_map.<id>.<snapid:016x>` برای هر snapshot ذخیره می‌شود.

## اشیای سطح pool {#sec-37-2-3}

| شیء | omap یا داده | کاربرد |
|---|---|---|
| `rbd_id.<name>` | داده: شناسه‌ی image | یافتن id از نام |
| `rbd_directory` | `name_<name>` → id و `id_<id>` → name | فهرست imageهای pool یا namespace |
| `rbd_trash` | `id_<id>` → نام، زمان حذف، زمان مجاز بازگرداندن، منبع | imageهای در سطل زباله |
| `rbd_children` | کلید: parent spec، مقدار: فرزندان | فقط برای clone قالب 1 |
| `rbd_info` | omap ‏`conf_<option>` و نشانگر اعتبارسنجی pool | تنظیمات سطح pool (`rbd config pool set`) و نتیجه‌ی بررسی قابلیت overwrite در data pool |
| `rbd_namespace` | `name_<ns>` | فهرست namespaceهای pool |
| `rbd_mirroring` | `mirror_mode`، `mirror_uuid`، `mirror_peer_<uuid>`، `image_<id>`، `global_<gid>`، `status_global_<gid>`، `instance_<id>`، `image_map_<gid>` | وضعیت mirroring (فصل ۳۹) |
| `rbd_group_directory` و `rbd_group_header.<id>` | omap | گروه‌های consistency |
| `rbd_task` | omap | صف کارهای پس‌زمینه‌ی mgr (‏`rbd task add flatten` و مانند آن) |

**namespace** در RBD همان namespace در RADOS است (فصل ۳۴). همه‌ی اشیای فهرست‌شده در بالا جداگانه در هر namespace ساخته می‌شوند. با cap ‏`profile rbd pool=P namespace=N` می‌توان یک کلاینت را به یک namespace محدود کرد، بی‌آنکه برای هر مستاجر pool جدا ساخت.

```bash
# مثال: خواندن مستقیم header (فقط برای بررسی؛ هرگز با rados تغییرش ندهید)
rados -p rbd listomapkeys rbd_header.5f3a2b8c1d4e
rados -p rbd getomapval rbd_header.5f3a2b8c1d4e object_prefix
```

```text
مثال (خروجی):
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

چهار بایت اول (`15 00 00 00` یعنی 21) طول رشته به‌صورت little-endian است؛ همه‌ی رشته‌ها در کدگذاری Ceph همین قالب را دارند.

![چیدمان یک image با data pool جدا. pool فراداده‌ی replicated شامل rbd_id، rbd_directory، header و object mapهاست و pool داده‌ی EC اشیای rbd_data با پیشوند شناسه‌ی pool فراداده را دارد. کلاینت‌ها روی header ‏watch می‌کنند و قفل exclusive روی xattr همان header است](figures/ch37/f01_layout.png){#fig-37-f01_layout}

# striping {#sec-37-3}

به‌طور پیش‌فرض `stripe_unit` برابر اندازه‌ی شیء و `stripe_count` برابر 1 است، پس image به‌سادگی به قطعه‌های پشت‌سرهم 4 MiB تقسیم می‌شود. با striping سفارشی، داده به‌صورت **round-robin** میان `stripe_count` شیء پخش می‌شود تا نوشتن‌های ترتیبی کوچک هم‌زمان به چند OSD بروند.

::: {.algo #alg-37-1 title="نگاشت آفست image به (شیء، آفست درون شیء)" src="src/osdc/Striper.cc :: Striper::file_to_extents" complexity="O(len / stripe_unit) قطعه"}
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

**مثال عددی.** `object_size = 4 MiB`، `stripe_unit = 64 KiB`، `stripe_count = 4`، نوشتن 300000 بایت از آفست 1000000. هر شیء 64 stripe دارد و یک «object set» از ۴ شیء 16 MiB را می‌پوشاند.

| block | stripe | stripepos | شیء | آفست درون شیء | طول |
|---|---|---|---|---|---|
| 15 | 3 | 3 | 3 | 213568 | 48576 |
| 16 | 4 | 0 | 0 | 262144 | 65536 |
| 17 | 4 | 1 | 1 | 262144 | 65536 |
| 18 | 4 | 2 | 2 | 262144 | 65536 |
| 19 | 4 | 3 | 3 | 262144 | 54816 |

نوشتن 300 KB به هر چهار شیء می‌رسد. با striping پیش‌فرض همین نوشتن فقط شیء 0 را (آفست 1000000 تا 1300000) لمس می‌کرد. striping برای بار ترتیبی تک‌جریانی با عمق صف کم سودمند است، ولی برای بار تصادفی 4K فقط تعداد اشیای درگیر را زیاد می‌کند. krbd از نسخه‌ی 4.17 هسته striping سفارشی را پشتیبانی می‌کند (فصل ۲۹).

![striping با stripe_unit=64K و stripe_count=4. هر سطر یک stripe است و چهار ستون چهار شیء یک object set. بلوک‌های 15 تا 19 که نوشتن مثال را می‌سازند رنگی شده‌اند](figures/ch37/f02_striping.png){#fig-37-f02_striping}

::: {.sim name="striping"}
:::

آزمایشگاه زیر همین اشیا را یک گام جلوتر دنبال می‌کند، تا PG و OSDهایشان، همراه با اشیای header، id و object map همان image.

::: {.sim name="placement" mode="rbd"}
:::

# object map {#sec-37-4}

## حالت‌ها و بسته‌بندی بیت {#sec-37-4-1}

object map برای هر شیء ۲ بیت دارد (`BitVector<2>`):

| مقدار | ثابت | معنی |
|---|---|---|
| 0 | `OBJECT_NONEXISTENT` | شیء وجود ندارد؛ خواندن صفر برمی‌گرداند و نیازی به رفتن به OSD نیست |
| 1 | `OBJECT_EXISTS` | شیء وجود دارد و از آخرین snapshot تغییر کرده است |
| 2 | `OBJECT_PENDING` | حذف در جریان است (discard یا resize) |
| 3 | `OBJECT_EXISTS_CLEAN` | شیء وجود دارد و از آخرین snapshot تغییر **نکرده** است |

هر بایت چهار شیء را نگه می‌دارد و **شیء با شماره‌ی کوچک‌تر در بیت‌های بالاتر** است: `shift = (3 − objectno % 4) × 2`. کدگذاری روی دیسک سه بخش دارد: header (طول، نسخه و تعداد عناصر)، داده‌ی خام، و footer شامل crc32c ‏header و یک crc32c برای هر بلوک 4096 بایتی داده. پس به‌روزرسانی یک شیء فقط یک بلوک 4 KiB و crc آن را بازنویسی می‌کند (متد `object_map_update` در cls_rbd).

![کدگذاری object map یک image ده‌گیگابایتی با اشیای 4 MiB (2560 شیء)، بایت به بایت. header هجده‌بایتی شامل طول، struct_v و compat و تعداد عناصر است؛ سپس 640 بایت داده که هر بایت چهار شیء را با دو بیت نگه می‌دارد و در پایان footer با crcها](figures/ch37/f03_objectmap.png){#fig-37-f03_objectmap}

## چه کسی حالت را عوض می‌کند؟ {#sec-37-4-2}

- **نوشتن** روی شیئی که NONEXISTENT یا EXISTS_CLEAN است، **پیش از** ارسال نوشتن، object map را به EXISTS به‌روز می‌کند (اول در حافظه، سپس با `object_map_update` روی RADOS). اگر شیء از قبل EXISTS باشد، هیچ هزینه‌ای ندارد.
- **discard یا حذف** ابتدا حالت را PENDING می‌کند، شیء را حذف می‌کند و سپس NONEXISTENT.
- **گرفتن snapshot** نقشه‌ی head را در `rbd_object_map.<id>.<snapid>` کپی و سپس همه‌ی EXISTSهای head را به EXISTS_CLEAN تبدیل می‌کند (`object_map_snap_add` در cls_rbd).
- **حذف snapshot** بیت‌های EXISTS نقشه‌ی آن snapshot را با نقشه‌ی snapshot بعدی (یا head) ادغام می‌کند تا اطلاعات «تغییر کرده» از دست نرود (`object_map_snap_remove`).

object map فقط با **exclusive-lock** معتبر است، چون فقط مالک قفل حق تغییر آن را دارد. اگر کلاینت در میانه‌ی به‌روزرسانی از کار بیفتد، پرچم `OBJECT_MAP_INVALID` در `flags` می‌نشیند و `rbd object-map rebuild` باید اجرا شود.

## fast-diff {#sec-37-4-3}

::: {.algo #alg-37-2 title="محاسبه‌ی وضعیت تغییر هر شیء میان دو snapshot" src="src/librbd/object_map/DiffRequest.cc :: DiffRequest::handle_load_object_map" complexity="O(N × S) برای N شیء و S نقشه‌ی بارشده؛ بدون هیچ خواندن داده"}
:::

```text
pseudocode
# برای هر snapshot از from_snap تا end_snap (و head)، نقشه‌ی آن بارگذاری و با وضعیت قبلی ترکیب می‌شود
first map (from_snap):  state[o] = HOLE if NONEXISTENT else DATA (PENDING → DATA_UPDATED)
each later map m:
    HOLE:         if m[o] != NONEXISTENT → DATA_UPDATED     (diff-iterate: فقط در نقشه‌ی پایانی)
    DATA:         if m[o] == NONEXISTENT → HOLE_UPDATED
                  elif m[o] != EXISTS_CLEAN → DATA_UPDATED
    HOLE_UPDATED: if m[o] != NONEXISTENT → DATA_UPDATED
    DATA_UPDATED: if m[o] == NONEXISTENT → HOLE_UPDATED
objects beyond the previous size (image grew) → HOLE or DATA_UPDATED
```

نکته‌ی کلیدی EXISTS_CLEAN است: اگر شیئی در from_snap وجود داشته و در همه‌ی نقشه‌های بعدی EXISTS_CLEAN مانده، یعنی پس از from_snap نوشتنی نداشته است و در diff نمی‌آید. `rbd diff --whole-object`، `rbd du` و `rbd export-diff` (و حالت snapshot در rbd-mirror) همه از همین محاسبه استفاده می‌کنند. اگر `FAST_DIFF_INVALID` روشن باشد، librbd به `list_snaps` روی تک‌تک اشیا برمی‌گردد که بسیار کندتر است.

**مثال عددی.** image ‏10 GiB با 2560 شیء. پس از snap1، بیست شیء نوشته شده و سه شیء discard شده است. با fast-diff، `rbd export-diff --from-snap snap1` فقط دو نقشه‌ی 640 بایتی (و header و footer) می‌خواند و 23 شیء را پیدا می‌کند. بدون آن، 2560 فراخوانی `list_snaps` لازم بود.

# مرجع rbd {#sec-37-5}

## image و snapshot {#sec-37-5-1}

| دستور | کاربرد |
|---|---|
| `rbd create P/I --size 10G [--object-size 4M] [--stripe-unit 64K --stripe-count 4] [--data-pool DP] [--image-feature F]` | ساخت image |
| `rbd ls [-l] P[/NS]` / `rbd info P/I` / `rbd status P/I` | فهرست، جزئیات، watcherها |
| `rbd resize P/I --size N [--allow-shrink]` | تغییر اندازه |
| `rbd feature {enable,disable} P/I F` | روشن و خاموش کردن ویژگی |
| `rbd object-map {rebuild,check} P/I[@S]` | بازسازی و بررسی object map |
| `rbd du P/I` / `rbd diff [--from-snap S] [--whole-object] P/I` | مصرف و تغییرات |
| `rbd snap {create,ls,rm,purge,rollback,rename,limit set}` | snapshot |
| `rbd snap {protect,unprotect} P/I@S` | فقط برای clone قالب 1 |
| `rbd clone P/I@S P2/C [--rbd-default-clone-format 2]` / `rbd children P/I@S` / `rbd flatten P2/C` | layering (فصل ۳۸) |
| `rbd export P/I FILE` / `import` / `export-diff` / `import-diff` / `merge-diff` | پشتیبان |
| `rbd deep cp P/I P2/I2` / `rbd cp` | کپی (deep با snapshotها) |
| `rbd trash {mv,ls,restore,rm,purge}` | سطل زباله |
| `rbd migration {prepare,execute,commit,abort}` | مهاجرت زنده |
| `rbd image-meta {list,get,set,remove} P/I` | متادیتا و تنظیمات هر image |
| `rbd config {pool,image,global} {get,set,list}` | تنظیمات سطح pool یا image |
| `rbd namespace {create,ls,remove} P/NS` | namespace |
| `rbd group {create,image add,snap create}` | گروه consistency |
| `rbd lock {ls,add,rm}` | قفل مشورتی (نه exclusive-lock) |
| `rbd bench P/I --io-type {read,write,readwrite} --io-size 4K --io-threads 16 --io-pattern rand` | آزمون کارایی |
| `rbd perf image {iostat,iotop}` | آمار زنده از mgr |
| `rbd pool init P` / `rbd pool stats P` | آماده‌سازی و آمار pool |

## map کردن {#sec-37-5-2}

| دستور | کاربرد |
|---|---|
| `rbd device map [-t krbd] P/I [-o OPTS]` / `rbd device unmap` / `rbd device list` | krbd |
| `rbd device map -t nbd P/I` یا `rbd-nbd map P/I [--try-netlink] [--timeout N]` | rbd-nbd (librbd در فضای کاربر) |
| `rbd-nbd list-mapped` / `rbd-nbd unmap /dev/nbdX` | فهرست و قطع |
| `rbd device map -t ubbd P/I` | ubbd، اگر بسته‌ی آن نصب باشد |

```bash
# مثال: ساخت image با striping و data pool، و بررسی آن
rbd create rbd/vm01 --size 10G --stripe-unit 64K --stripe-count 4 --data-pool rbd-ec
rbd info rbd/vm01
```

```text
مثال (خروجی):
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

`block_name_prefix` همان `object_prefix` است و عدد 3 در آن شناسه‌ی pool ‏`rbd` است، چون data pool جدا داریم.

# تنظیم و عیب‌یابی {#sec-37-6}

- **کندی نخستین نوشتن روی image تازه:** هر نخستین نوشتن روی یک شیء یک `object_map_update` هم دارد. پس از پر شدن image این هزینه از بین می‌رود. برای آزمون کارایی، image را اول پر کنید.
- **`rbd du` یا export-diff کند است:** `rbd info` را ببینید؛ اگر `flags: object map invalid, fast diff invalid` است، `rbd object-map rebuild` اجرا کنید (روی snapshotها هم جداگانه).
- **image با `--data-pool` روی EC ساخته نمی‌شود:** `allow_ec_overwrites` روی pool ‏EC و اجرای `rbd pool init` روی هر دو pool را بررسی کنید.
- **حذف image بزرگ کند است:** حذف به تعداد اشیای **موجود** وابسته است؛ با object map فقط اشیای موجود حذف می‌شوند. برای کارهای بلند از `rbd trash mv` و سپس `rbd trash rm` یا `ceph rbd task add remove` استفاده کنید.
- **هرگز header را با `rados setomapval` تغییر ندهید:** cls_rbd ناسازگاری‌ها را بررسی می‌کند ولی کلاینت‌های باز از تغییر خبر نمی‌گیرند (هیچ notify فرستاده نمی‌شود).

# تکمیلی و به‌روز {#sec-37-7}

- clone قالب 2 (پیش‌فرض `rbd_default_clone_format: auto`، که اگر همه‌ی کلاینت‌ها Mimic یا جدیدتر باشند قالب 2 را برمی‌گزیند) به protect نیازی ندارد و فرزندان را در `snap_children_*` همان header والد نگه می‌دارد.
- مقدار `op_features` در نسخه‌های جدید بیت‌هایی برای snapshot در trash و گروه‌ها دارد؛ کلاینت قدیمی که op_feature ناشناخته ببیند، image را باز نمی‌کند.
- در شاخه‌ی main، `rbd-nbd` با netlink و `--try-netlink` پایدارتر از روش ioctl است؛ پشتیبانی از ubbd به بسته‌بندی توزیع وابسته است.

# تمرین عملی {#sec-37-8}

1. یک image بسازید و با `rados listomapkeys` و `getomapval` همه‌ی کلیدهای header را بخوانید. سپس یک snapshot بگیرید و کلید تازه را پیدا کنید.
2. یک image با `--stripe-unit 64K --stripe-count 4` بسازید، 300000 بایت در آفست 1000000 بنویسید (`rbd bench` یا `dd` روی rbd-nbd) و با `rados ls | grep` ببینید کدام اشیا ساخته شدند. با جدول مثال مقایسه کنید.
3. `rados get rbd_object_map.<id> /tmp/om` بگیرید و با `xxd` چهار بایت اول داده (پس از header هجده‌بایتی) را با حالت اشیای 0 تا 15 تطبیق دهید.
4. پس از یک snapshot، چند شیء بنویسید و `rbd diff --from-snap` را با و بدون fast-diff (پس از `rbd feature disable ... fast-diff`) زمان‌گیری کنید.

# پرسش‌های مرور {#sec-37-9}

1. کدام کلیدهای header برای ساختن نام اشیای داده لازم‌اند؟
2. با data pool جدا، نام اشیای داده چه تغییری می‌کند و چرا؟
3. `rbd_directory` چه دو نوع کلیدی دارد؟
4. در مثال striping، بایت آفست 1100000 در کدام شیء و کدام آفست است؟
5. object map هر شیء را با چند بیت نگه می‌دارد و شیء 0 در کدام بیت‌های بایت اول است؟
6. چرا footer object map برای هر بلوک 4 KiB یک crc جدا دارد؟
7. EXISTS_CLEAN چه زمانی تنظیم و چه زمانی پاک می‌شود؟
8. در fast-diff اگر شیء در from_snap ‏DATA و در head ‏EXISTS باشد، نتیجه چیست؟
9. چرا object map به exclusive-lock وابسته است؟
10. namespace در RBD چگونه پیاده شده و چه مزیتی دارد؟

# منابع این فصل {#sec-37-10}

- cls_rbd.cc: https://github.com/ceph/ceph/blob/main/src/cls/rbd/cls_rbd.cc
- rbd_types.h و features.h: https://github.com/ceph/ceph/blob/main/src/include/rbd/features.h
- Striper.cc: https://github.com/ceph/ceph/blob/main/src/osdc/Striper.cc
- bit_vector.hpp: https://github.com/ceph/ceph/blob/main/src/common/bit_vector.hpp
- librbd/object_map/DiffRequest.cc: https://github.com/ceph/ceph/blob/main/src/librbd/object_map/DiffRequest.cc
- مستند RBD layering و striping: https://docs.ceph.com/en/latest/dev/rbd-layering/
- مرجع دستور rbd: https://docs.ceph.com/en/latest/man/8/rbd/
- مرجع rbd-nbd: https://docs.ceph.com/en/latest/man/8/rbd-nbd/
