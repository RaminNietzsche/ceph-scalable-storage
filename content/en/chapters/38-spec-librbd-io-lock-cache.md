---
chapter: 38
id: ch38
title: 'بخش تخصصی (۵): RBD — مسیر I/O در librbd، layering و copyup، exclusive-lock، cache و QoS'
part: specialist
lang: en
translation: pending
---

# پیش از شروع {#sec-38-1}

librbd یک کتابخانه‌ی سنگین است: هر درخواست از چند لایه‌ی **dispatch** در سطح image و سپس در سطح شیء عبور می‌کند، و ویژگی‌هایی مثل exclusive-lock، journaling، cache، رمزنگاری و QoS هر کدام یک لایه‌اند. این فصل آن لایه‌ها را به ترتیب واقعی‌شان نشان می‌دهد، سپس سه سازوکار پرکاربرد را در جزئیات باز می‌کند: copyup در clone و flatten، گرفتن و شکستن exclusive-lock با blocklist، و cache پیش‌فرض writearound. در پایان krbd، librbd و rbd-nbd را از نظر ویژگی و کارایی مقایسه می‌کند. نام‌ها و پیش‌فرض‌ها با شاخه‌ی main مخزن ceph/ceph (نوامبر ۲۰۲۶) تطبیق داده شده‌اند.

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-38-1-1}

- یک `rbd_aio_write` از کدام لایه‌ها عبور می‌کند؟
- نوشتن روی شیئی از clone که هنوز وجود ندارد چگونه انجام می‌شود؟
- deep-flatten چه فرقی با flatten معمولی دارد؟
- دو کلاینت که هم‌زمان یک image را باز می‌کنند چگونه قفل را دست‌به‌دست می‌کنند؟
- چه زمانی librbd کلاینت دیگری را blocklist می‌کند؟
- cache پیش‌فرض librbd چه کار می‌کند و چه کار نمی‌کند؟
- QoS در librbd چگونه کار می‌کند و چه محدودیتی دارد؟

## پیش‌نیاز {#sec-38-1-2}

فصل ۲ (RBD)، فصل ۲۹ (krbd)، فصل ۳۶ (SnapContext و clone در RADOS)، فصل ۳۷ (header و object map).

# لایه‌های dispatch {#sec-38-2}

`ImageDispatcher` و `ObjectDispatcher` دو زنجیره از لایه‌ها هستند. هر لایه می‌تواند درخواست را بگیرد و تمام کند، تغییر دهد و به لایه‌ی بعد بسپارد، یا تا رفع شرطی نگه دارد. ترتیب از `librbd/io/Types.h`:

| ترتیب | لایه‌ی image | نقش |
|---|---|---|
| 1 | `QUEUE` | صف ورودی و انتقال به thread pool (‏`rbd_op_threads`) |
| 2 | `QOS` | محدودیت IOPS و پهنای باند (token bucket) |
| 3 | `EXCLUSIVE_LOCK` | نگه داشتن نوشتن‌ها تا گرفتن قفل |
| 4 | `REFRESH` | به‌روزرسانی ImageCtx اگر header تغییر کرده باشد |
| 5 | `MIGRATION` | هدایت به image مبدأ در مهاجرت زنده |
| 6 | `JOURNAL` | ثبت رویداد در journal پیش از نوشتن (فصل ۳۹) |
| 7 | `WRITE_BLOCK` | توقف موقت نوشتن‌ها در عملیاتی مثل snapshot |
| 8 | `WRITEBACK_CACHE` | cache پایدار PWL، اگر فعال باشد |
| 9 | `CORE` | تبدیل extent تصویر به extent شیء با Striper (فصل ۳۷) |

| ترتیب | لایه‌ی شیء | نقش |
|---|---|---|
| 1 | `CACHE` | writearound یا ObjectCacher (writeback و writethrough) |
| 2 | `CRYPTO` | رمزنگاری LUKS در سطح بلوک |
| 3 | `JOURNAL` | تأخیر نوشتن شیء تا commit رویداد journal |
| 4 | `PARENT_CACHE` | cache فقط‌خواندنی والد از طریق ceph-immutable-object-cache |
| 5 | `SCHEDULER` | ادغام نوشتن‌های کوچک پشت‌سرهم (`rbd_io_scheduler`) |
| 6 | `CORE` | ساختن `ObjectRequest` و ارسال op به RADOS |

::: {.algo #alg-38-1 title="عبور یک نوشتن از زنجیره‌ی dispatch" src="src/librbd/io/ImageDispatcher.cc؛ src/librbd/io/ObjectDispatcher.cc؛ src/librbd/io/ImageRequest.cc :: ImageWriteRequest؛ src/librbd/io/ObjectRequest.cc :: ObjectWriteRequest" complexity="O(L) لایه برای هر درخواست، به‌علاوه‌ی O(k) شیء پس از striping"}
:::

```text
pseudocode
ImageDispatcher.send(write(extents, data)):
    for layer in [QUEUE, QOS, EXCLUSIVE_LOCK, REFRESH, MIGRATION, JOURNAL, WRITE_BLOCK, WRITEBACK_CACHE, CORE]:
        result = layer.write(...)          # true = layer took it
        if result == CONTINUE: next layer
        if result == COMPLETE: done
        if layer is holding it: it resumes later from the next layer
CORE: Striper.file_to_extents → for each object extent:
    ObjectDispatcher.send(write(objectno, off, data, snapc = image snapc))
        CACHE → CRYPTO → JOURNAL → PARENT_CACHE → SCHEDULER → CORE
CORE: ObjectWriteRequest:
    if object_map says may not exist and has parent overlap → copyup (الگوریتم ۳۸-۲)
    else object_map_update(EXISTS) if needed → RADOS write op with snapc
```

![لایه‌های dispatch در librbd. درخواست تصویر از نُه لایه‌ی image عبور و در CORE با Striper به extentهای شیء شکسته می‌شود؛ هر extent سپس از شش لایه‌ی شیء عبور می‌کند تا به‌صورت op به RADOS برسد. لایه‌های غیرفعال (مثلاً journal یا crypto) در زنجیره نیستند](figures/ch38/f01_dispatch.png){#fig-38-f01_dispatch}

# layering: clone، copyup و flatten {#sec-38-3}

clone یک image است که در header خود کلید `parent` (pool، namespace، image و snap والد و **overlap**) دارد. overlap بخشی از فضای آدرس است که هنوز می‌تواند از والد خوانده شود؛ اگر clone کوچک شود، overlap هم کم می‌شود و دیگر بزرگ نمی‌شود.

- **خواندن:** اگر شیء در clone وجود نداشته باشد (ENOENT یا object map ‏NONEXISTENT) و extent در overlap باشد، همان extent از والد خوانده می‌شود. با `rbd_clone_copy_on_read` همان داده بلافاصله در clone هم نوشته می‌شود.
- **نوشتن:** نوشتن جزئی روی شیئی که هنوز در clone نیست ابتدا باید بقیه‌ی شیء را از والد بیاورد، وگرنه بخش‌های نخوانده صفر خواهند شد. این کار **copyup** است.

::: {.algo #alg-38-2 title="copyup: پر کردن شیء clone از والد پیش از نخستین نوشتن" src="src/librbd/io/ObjectRequest.cc :: AbstractObjectWriteRequest::compute_parent_info، send_write، handle_write_object؛ src/librbd/io/CopyupRequest.cc؛ src/cls/rbd/cls_rbd.cc :: copyup" complexity="یک خواندن از والد (تا اندازه‌ی شیء) و یک op مرکب روی شیء clone"}
:::

```text
pseudocode
write to child object o:
    copyup_enabled = has_parent and extent of o within overlap
    if object map says o does not exist and copyup_enabled: goto copyup     # بهینه‌سازی
    send write with assert_exists guard
    on -ENOENT and copyup_enabled: goto copyup
copyup (one CopyupRequest per object; later writes append to it):
    read parent extents of o (sparse read)
    if snapshots exist on child (deep_copyup): first send copyup alone with EMPTY snapc
        # تا cloneهای RADOS برای snapshotهای child هم داده‌ی والد را ببینند
    op = cls rbd.copyup(data) or rbd.sparse_copyup(extent_map, data)
    append all pending writes of this object to the same op (if not deep_copyup)
    update object maps (head, and snapshots if deep-flatten) → EXISTS
    send op with child snapc
cls rbd.copyup on OSD: if object exists → return 0 ; else write data at offset 0
```

نکته‌ی ظریف در cls: اگر دو کلاینت هم‌زمان copyup کنند، دومی می‌بیند شیء وجود دارد و داده‌ی والد را **نمی‌نویسد**، ولی نوشتن خودش (که در همان op است) اعمال می‌شود. چون copyup و نوشتن در یک op اتمی‌اند، هیچ‌کس نیمه‌ی پر شیء را نمی‌بیند.

![copyup برای نخستین نوشتن روی شیء 1280 یک clone. librbd از object map می‌فهمد شیء وجود ندارد، شیء والد را با خواندن پراکنده می‌آورد، object map را به EXISTS می‌برد و copyup و نوشتن کاربر را در یک op اتمی به شیء clone می‌فرستد](figures/ch38/f02_copyup.png){#fig-38-f02_copyup}

**flatten** همه‌ی اشیای درون overlap را با یک copyup بدون داده‌ی کاربر پر می‌کند (`FlattenRequest` برای هر شیء یک نوشتن خالی می‌فرستد که copyup را برمی‌انگیزد) و سپس پیوند والد را حذف می‌کند (`child_detach` در header والد و حذف کلید `parent`). **deep-flatten** یعنی copyup به snapshotهای clone هم برسد؛ بدون آن، snapshotهای clone هنوز به والد وابسته می‌مانند و والد را نمی‌توان حذف کرد.

**مثال عددی.** یک clone از تصویر سیستم‌عامل 20 GiB با 5120 شیء. VM ‏4 KiB در آفست 5 GiB + 8 KiB می‌نویسد. شیء 1280 در clone وجود ندارد. librbd شیء 1280 والد را (فرض: کاملاً پر، 4 MiB) می‌خواند و op مرکب `[rbd.copyup(4 MiB), write(8 KiB, 4 KiB)]` را می‌فرستد. پس نخستین نوشتن 4 KiB روی هر شیء clone در واقع 4 MiB خواندن و 4 MiB نوشتن است. به همین دلیل VMهای تازه‌ی clone در دقایق اول کندترند و `rbd du` روی clone به‌سرعت بالا می‌رود.

# exclusive-lock {#sec-38-4}

exclusive-lock تضمین می‌کند در هر لحظه فقط یک کلاینت روی image می‌نویسد، تا object map، journal و cache سازگار بمانند. این قفل **همکارانه** است: اگر کلاینت دیگری بخواهد بنویسد، از مالک می‌خواهد قفل را رها کند.

قفل یک قفل `cls_lock` با نام `rbd_lock`، نوع exclusive، tag ‏`internal` و cookie ‏`auto <watch handle>` روی شیء header است. cookie شامل handle همان watch است، پس دیگران می‌توانند با `list_watchers` بفهمند صاحب قفل هنوز زنده است یا نه.

::: {.algo #alg-38-3 title="گرفتن exclusive-lock و شکستن قفل مالک مرده" src="src/librbd/ManagedLock.cc؛ src/librbd/managed_lock/AcquireRequest.cc، BreakRequest.cc، Utils.cc :: encode_lock_cookie؛ src/librbd/ExclusiveLock.cc" complexity="چند رفت‌وبرگشت RADOS؛ در بدترین حالت به‌علاوه‌ی یک به‌روزرسانی OSDMap برای blocklist"}
:::

```text
pseudocode
acquire():
    get_locker(header)                          # cls_lock get_info
    try lock(header, "rbd_lock", EXCLUSIVE, cookie = "auto " + watch_handle, tag = "internal")
    if ok: post_acquire (open object map, journal, ...) ; done
    if EBUSY:
        if locker has a live watch on header (same address and cookie handle):
            notify RequestLock to owner ; wait (owner releases if it allows)
            retry acquire later
        else:                                   # مالک مرده یا جدا شده
            if rbd_blocklist_on_break_lock:     # پیش‌فرض true
                mon: osd blocklist add <locker addr> expire = rbd_blocklist_expire_seconds (0 → پیش‌فرض mon)
                wait until our OSDMap epoch >= blocklist epoch
            break_lock(locker) ; retry lock
```

**چرا blocklist؟** مالکی که «مرده» به نظر می‌رسد ممکن است فقط از شبکه جدا شده و هنوز نوشتن‌هایی در مسیر داشته باشد. اگر قفل بدون blocklist شکسته شود، آن نوشتن‌ها بعداً روی داده‌ی مالک جدید فرود می‌آیند. blocklist در OSDMap تضمین می‌کند همه‌ی OSDها opهای آن آدرس را رد کنند. این همان مکانیزم fencing در کلاستر است.

![گرفتن exclusive-lock. اگر قفل گرفته شده باشد، کلاینت B بررسی می‌کند مالک هنوز watch زنده دارد یا نه. در حالت زنده، با notify درخواست رها کردن می‌فرستد؛ در غیر این صورت ابتدا مالک را blocklist و سپس قفل را می‌شکند](figures/ch38/f03_lock.png){#fig-38-f03_lock}

```bash
# مثال: دیدن قفل و watcherهای یک image
rbd lock ls rbd/vm01
rbd status rbd/vm01
ceph osd blocklist ls
```

```text
مثال (خروجی):
There is 1 exclusive lock on this image.
Locker         ID                     Address
client.24183   auto 94823571521536    10.20.0.31:0/2846217731

Watchers:
	watcher=10.20.0.31:0/2846217731 client.24183 cookie=94823571521536

10.20.0.44:0/1739920384 2026-11-15T10:41:07.512038+0330
listed 1 entries
```

cookie قفل (`auto 94823571521536`) با cookie ‏watcher برابر است، پس مالک زنده است. خط blocklist نشان می‌دهد کلاینت دیگری (آدرس ‏…44) پیش‌تر fence شده است.

::: {.warn}
اگر دو VM ‏یک image را با exclusive-lock باز کنند، هیچ خطایی نمی‌بینند: قفل مدام میان آن‌ها دست‌به‌دست می‌شود و هر دو می‌نویسند (با کارایی بسیار بد). exclusive-lock جلوی **دسترسی هم‌زمان** را نمی‌گیرد. برای جلوگیری واقعی، image را با `rbd device map -o exclusive` (krbd) یا گزینه‌ی `RBD_LOCK_MODE_EXCLUSIVE` در `rbd_lock_acquire` باز کنید تا قفل به درخواست دیگران رها نشود.
:::

# cache {#sec-38-5}

## writearound (پیش‌فرض) {#sec-38-5-1}

در شاخه‌ی main ‏`rbd_cache = true` و `rbd_cache_policy = writearound` است. این cache **داده را نگه نمی‌دارد**؛ فقط نوشتن را پیش از رسیدن به OSD تأیید می‌کند تا تأخیر از دید برنامه کم شود.

::: {.algo #alg-38-4 title="لایه‌ی writearound" src="src/librbd/cache/WriteAroundObjectDispatch.cc :: dispatch_io، block_overlapping_io، flush" complexity="O(log n) برای بررسی هم‌پوشانی در extentهای در جریان"}
:::

```text
pseudocode
write(object, extent):
    if max_dirty == 0 or FUA flag: pass through (writethrough)
    if extent overlaps an in-flight write on same object: block until it completes
    elif in_flight_bytes + len <= rbd_cache_max_dirty:
        complete to caller NOW ; send to RADOS in background
    else: queue until in-flight bytes drop
flush(): wait for all in-flight writes ; then complete
read: not cached → straight to RADOS
rbd_cache_writethrough_until_flush: until the guest sends its first flush, behave as writethrough
```

`rbd_cache_writethrough_until_flush = true` از سیستم‌عامل‌های قدیمی که flush نمی‌فرستند محافظت می‌کند: تا نخستین flush دیده نشود، همه‌ی نوشتن‌ها همگام‌اند.

## writeback و writethrough (ObjectCacher) {#sec-38-5-2}

با `rbd_cache_policy = writeback` لایه‌ی CACHE همان ObjectCacher قدیمی است: داده‌ی خوانده‌شده و نوشته‌شده را تا `rbd_cache_size` (پیش‌فرض 32 MiB) نگه می‌دارد و dirty را تا `rbd_cache_max_dirty` (‏24 MiB) جمع می‌کند. این cache **فرّار** است و فقط با flush مهمان پایدار می‌شود.

## cache پایدار (PWL) {#sec-38-5-3}

`rbd_persistent_cache_mode` (پیش‌فرض `disabled`) با مقدار `ssd` یا `rwl` یک log پایدار روی SSD محلی یا PMEM می‌سازد. نوشتن پس از ثبت در log محلی تأیید می‌شود و بعداً به RADOS می‌رود. بیت `dirty-cache` در features نشان می‌دهد image داده‌ی ننوشته در یک میزبان دارد؛ باز کردن آن در میزبان دیگر تا flush شدن cache مجاز نیست. این cache تأخیر نوشتن را بسیار کم می‌کند، ولی میزبان را به **نقطه‌ی شکست** داده تبدیل می‌کند.

# QoS {#sec-38-6}

لایه‌ی QOS برای هر نوع محدودیت (`iops`، `bps`، `read_iops`، `write_iops`، `read_bps`، `write_bps`) یک `TokenBucketThrottle` دارد. تایمر هر `rbd_qos_schedule_tick_min` میلی‌ثانیه (پیش‌فرض 50) توکن اضافه می‌کند.

::: {.algo #alg-38-5 title="token bucket در QoS ‏librbd" src="src/common/Throttle.cc :: TokenBucketThrottle::add_tokens، get؛ src/librbd/io/QosImageDispatch.cc" complexity="O(b) برای b درخواست منتظر در هر tick"}
:::

```text
pseudocode
every tick (>= rbd_qos_schedule_tick_min ms):
    bucket.put(avg * tick / 1000, burst_ratio = max(burst, avg) / avg)   # سقف سطل = burst × burst_seconds
    while blockers not empty:
        b = front ; got = bucket.get(b.tokens)
        if got == b.tokens: release b
        else: b.tokens -= got ; break
request(tokens = 1 for iops, bytes for bps):
    if bucket has tokens: proceed ; else enqueue as blocker
```

**مثال عددی.** `rbd_qos_iops_limit = 500` و burst خاموش. در هر tick ‏50 ms، ‏25 توکن اضافه می‌شود. VM با عمق صف 32 درخواست 4K می‌فرستد؛ 25 درخواست در هر tick آزاد و بقیه منتظر می‌مانند، پس تأخیر میانگین از دید VM حدود 32/500 = 64 ms است. QoS در librbd **برای هر image و هر کلاینت** جداست. دو کلاینتی که یک image را باز کنند هر کدام 500 IOPS می‌گیرند و هیچ هماهنگی سراسری وجود ندارد. برای سقف سطح کلاستر باید از mClock در OSD (فصل ۲۱) کمک گرفت.

# krbd، librbd و rbd-nbd {#sec-38-7}

| | krbd | librbd (QEMU) | rbd-nbd |
|---|---|---|---|
| محل اجرا | هسته | فرایند QEMU | فرایند rbd-nbd + nbd هسته |
| journaling و mirroring حالت journal | خیر | بله | بله |
| object-map و fast-diff | از هسته‌ی 5.3 | بله | بله |
| cache ‏librbd و PWL | خیر (page cache هسته) | بله | بله |
| QoS در librbd | خیر | بله | بله |
| رمزنگاری LUKS ‏librbd | خیر (dm-crypt جدا) | بله | بله |
| کپی‌های اضافه‌ی داده | کمترین | کم | بیشتر (هسته ↔ فضای کاربر) |
| ارتقا | با هسته | با بسته‌ی Ceph | با بسته‌ی Ceph |

پشتیبانی ویژگی‌ها در krbd به نسخه‌ی هسته وابسته است (striping سفارشی از 4.17، deep-flatten از 5.1، object-map و fast-diff از 5.3، طبق مستند rbd(8)). اگر image ویژگی ناشناخته‌ای برای هسته داشته باشد، `rbd device map` با «image uses unsupported features» شکست می‌خورد و باید آن ویژگی را خاموش کرد یا rbd-nbd را به کار برد.

# تنظیم و عیب‌یابی {#sec-38-8}

- **کندی شدید با دو کلاینت:** `rbd status` را ببینید؛ اگر دو watcher دارد و قفل مدام جابه‌جا می‌شود (در لاگ librbd پیام‌های request lock)، یکی از کلاینت‌ها نباید image را باز کرده باشد.
- **VM پس از failover میزبان «read-only» می‌شود:** میزبان قبلی blocklist شده و نوشتن‌های آن رد می‌شوند. این رفتار درست است؛ پس از بازگشت، فرایند QEMU قدیمی را متوقف کنید و `ceph osd blocklist rm` فقط پس از اطمینان از توقف آن.
- **کندی clone تازه:** هزینه‌ی copyup است. `rbd flatten` را در زمان خلوت اجرا کنید یا parent cache (‏`rbd_parent_cache_enabled` با ceph-immutable-object-cache) را برای خواندن‌ها روشن کنید.
- **`rbd_op_threads`:** پیش‌فرض 1 است. برای یک فرایند با تعداد زیادی image یا IOPS بسیار بالا، افزایش آن تا 2 یا 4 می‌تواند کمک کند، ولی ترتیب callbackها را تضمین نمی‌کند.
- **مهلت درخواست:** `rbd_request_timed_out_seconds` (‏30) فقط برای پیام‌های notify میان کلاینت‌هاست، نه برای I/O.

# تکمیلی و به‌روز {#sec-38-9}

- در نسخه‌های قدیمی‌تر پیش‌فرض `rbd_cache_policy` همان writeback بود. هنگام ارتقای clusterهای قدیمی، تنظیمات صریح در `ceph.conf` میزبان‌های QEMU را بررسی کنید.
- لایه‌ی `SCHEDULER` (‏`rbd_io_scheduler = simple`) نوشتن‌های کوچک پشت‌سرهم روی یک شیء را ادغام می‌کند. اثر آن روی بارهای ترتیبی کوچک مثبت و روی بارهای تصادفی ناچیز است.
- `rbd_read_from_replica_policy` با مقدار `balance` یا `localize` خواندن را به replicaها هم می‌فرستد؛ این کار فقط روی clusterهایی با `require_osd_release` جدید و برای imageهایی که نوشتن هم‌زمان ندارند ایمن است.

# تمرین عملی {#sec-38-10}

1. با `debug_rbd=20` یک نوشتن 4K بفرستید و نام لایه‌هایی را که در لاگ دیده می‌شوند به ترتیب یادداشت کنید.
2. یک clone بسازید، روی یک شیء خالی آن 4 KiB بنویسید و با `rados stat` اندازه‌ی شیء clone را ببینید. سپس `rbd du` را پیش و پس مقایسه کنید.
3. image را در دو فرایند `rbd bench` هم‌زمان باز کنید و IOPS هر کدام را با حالت تک‌فرایندی مقایسه کنید.
4. `rbd config image set rbd/vm01 rbd_qos_iops_limit 500` را تنظیم و با `rbd bench --io-threads 32` تأخیر را اندازه بگیرید. با محاسبه‌ی مثال فصل مقایسه کنید.

# پرسش‌های مرور {#sec-38-11}

1. لایه‌ی EXCLUSIVE_LOCK پیش از کدام لایه‌ها اجرا می‌شود و چرا؟
2. چه زمانی copyup بدون فرستادن نخستین نوشتن انجام می‌شود؟
3. چرا متد cls ‏`copyup` اگر شیء وجود داشته باشد کاری نمی‌کند؟
4. deep-flatten چه چیزی را اضافه می‌کند؟
5. cookie قفل `rbd_lock` چه ساختاری دارد و به چه کاری می‌آید؟
6. چرا شکستن قفل بدون blocklist خطرناک است؟
7. writearound چه زمانی نوشتن را بلافاصله تأیید نمی‌کند؟
8. `rbd_cache_writethrough_until_flush` از چه چیزی محافظت می‌کند؟
9. با `rbd_qos_iops_limit = 1000` و tick ‏50 ms، در هر tick چند توکن اضافه می‌شود؟
10. دو دلیل برای استفاده از rbd-nbd به‌جای krbd نام ببرید.

# منابع این فصل {#sec-38-12}

- librbd/io (Types.h، ImageDispatcher، ObjectRequest، CopyupRequest): https://github.com/ceph/ceph/tree/main/src/librbd/io
- librbd/managed_lock و ExclusiveLock.cc: https://github.com/ceph/ceph/tree/main/src/librbd/managed_lock
- WriteAroundObjectDispatch.cc: https://github.com/ceph/ceph/blob/main/src/librbd/cache/WriteAroundObjectDispatch.cc
- Throttle.cc (TokenBucketThrottle): https://github.com/ceph/ceph/blob/main/src/common/Throttle.cc
- گزینه‌های RBD: https://docs.ceph.com/en/latest/rbd/rbd-config-ref/
- cache پایدار: https://docs.ceph.com/en/latest/rbd/rbd-persistent-write-log-cache/
- مستند exclusive lock: https://docs.ceph.com/en/latest/rbd/rbd-exclusive-locks/
- rbd(8) و ویژگی‌های krbd: https://docs.ceph.com/en/latest/man/8/rbd/
