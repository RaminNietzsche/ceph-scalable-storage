---
chapter: 16
id: ch16
title: "لایه‌بندی ذخیره‌سازی: از Cache Tiering تا Device Class و Storage Class"
part: main
lang: fa
---

::: {.tldr}

- cache tiering یک pool سریع را جلوی pool پایه می‌گذارد، اما از Reef منسوخ شده است.
- cache tier موجود را با احتیاط بردارید: فضای آزاد pool پایه را بررسی کنید، flush و evict کنید و بعد overlay را حذف کنید.
- جایگزین‌های امروز: device class و قانون CRUSH برای هر pool، جدا کردن داده‌ی داغ و سرد در خود برنامه، و storage class در RGW با انتقال‌های lifecycle.
- داده‌ی RocksDB هم درون BlueStore میان دستگاه سریع و کند تقسیم می‌شود.

:::

# پیش از شروع {#sec-16-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-16-1-1}

هر کلاستر بزرگی دیر یا زود با این پرسش روبه‌رو می‌شود: چطور داده‌ی داغ را روی رسانه‌ی سریع و گران و داده‌ی سرد را روی رسانه‌ی ارزان و پرظرفیت نگه داریم؟ Ceph سال‌ها پاسخ «رسمی» به این پرسش داشت: **Cache Tiering**. امروز وضعیت متفاوت است. مستندات رسمی صریحاً می‌گوید cache tiering در Reef منسوخ (deprecated) شده، مدت‌هاست نگه‌دارنده ندارد و ممکن است در نسخه‌ای آینده بدون اطلاع قبلی حذف شود؛ نباید cache tier جدید ساخت و استقرارهای موجود باید هرچه زودتر مهاجرت کنند. این فصل هر دو روی سکه را پوشش می‌دهد:

- cache tiering چگونه کار می‌کرد و چرا برای بیشتر بارها کارایی را **کاهش** می‌داد؟
- عامل کش (tier agent) درون OSD با چه الگوریتمی flush و evict می‌کرد؟
- اگر هنوز cache tier دارید، چگونه آن را **بی‌خطر حذف** کنید؟
- جایگزین‌های امروزی کدام‌اند: device class و قانون‌های CRUSH، block.db روی NVMe، storage class و lifecycle در RGW؟

# Cache Tiering: معماری {#sec-16-2}

## overlay و pool کش {#sec-16-2-1}

در cache tiering، یک pool سریع (کش) جلوی یک pool پایه (backing) قرار می‌گیرد. با `set-overlay`، OSDMap برای pool پایه فیلدهای `read_tier` و `write_tier` را به pool کش اشاره می‌دهد. Objecter کلاینت این فیلدها را می‌بیند و درخواست‌ها را به‌طور شفاف به pool کش می‌فرستد؛ کلاینت لازم نیست چیزی درباره‌ی کش بداند.

![معماری cache tiering در سه ردیف: کلاینت درخواست pool پایه را به دلیل overlay به pool کش می‌فرستد؛ OSD کش در maybe_handle_cache_detail بررسی می‌کند شیء موجود است یا با توجه به HitSet باید promote شود؛ عامل کش در پس‌زمینه اشیای dirty را flush و اشیای clean سرد را evict می‌کند](figures/ch16/f01_tier.png){#fig-16-f01_tier}

```bash
# فقط برای درک یا آزمایشگاه؛ در کلاستر تولیدی cache tier جدید نسازید
ceph osd tier add cold-storage hot-storage
ceph osd tier cache-mode hot-storage writeback
ceph osd tier set-overlay cold-storage hot-storage
ceph osd pool set hot-storage hit_set_type bloom
ceph osd pool set hot-storage hit_set_count 12
ceph osd pool set hot-storage hit_set_period 14400
ceph osd pool set hot-storage target_max_bytes 1099511627776
```

| حالت کش | رفتار |
|---|---|
| writeback | نوشتن در کش و ack فوری؛ عامل بعداً flush می‌کند؛ خواندن‌ها promote می‌شوند |
| readproxy | اشیای موجود در کش استفاده می‌شوند؛ اشیای غایب بدون promote از پایه proxy می‌شوند |
| readonly | promote فقط روی خواندن؛ نوشتن مستقیم به پایه؛ داده‌ی کش ممکن است کهنه باشد |
| proxy | همه‌ی عملیات به پایه proxy می‌شود؛ برای تخلیه‌ی کش writeback |
| none | کش کاملاً غیرفعال |

::: {.warn}
حالت **readonly** سازگاری را تضمین نمی‌کند: پس از نوشتن در pool پایه، نسخه‌ی قدیمی در کش ممکن است همچنان خوانده شود. فقط برای داده‌ی تغییرناپذیر مناسب بود.
:::

## HitSet: کدام شیء داغ است؟ {#sec-16-2-2}

OSD کش برای تصمیم promote باید بداند شیء اخیراً دسترسی داشته یا نه. هر PG در هر بازه‌ی `hit_set_period` ثانیه یک **HitSet** می‌سازد: مجموعه‌ای از اشیایی که در آن بازه دسترسی داشته‌اند. نوع پیشنهادی `bloom` است (`src/osd/BloomHitSet.h`): فیلتر Bloom با حافظه‌ی کم و احتمال خطای مثبت کنترل‌شده. انواع دیگر `explicit_hash` و `explicit_object` حافظه‌ی بیشتری مصرف می‌کنند. `hit_set_count` تعداد HitSetهای نگه‌داشته‌شده و `min_read_recency_for_promote` تعداد HitSetهای اخیری است که شیء باید در آن‌ها دیده شده باشد تا روی خواندن promote شود؛ مقدار ۰ یعنی همیشه promote.

```text
pseudocode: تصمیم promote (خلاصه‌ی این کتاب از maybe_handle_cache_detail)
  if object in cache pool:            serve locally
  elif mode == writeback/readproxy:
      recent = count(h in last min_read_recency HitSets if obj in h)
      if recent >= min_read_recency_for_promote:  promote_object(obj)  # کپی از پایه
      else:                                        proxy_read(obj)     # خواندن مستقیم از پایه
```

::: {.deep}
HitSetها خودشان به صورت اشیای مخفی در همان PG کش ذخیره می‌شوند (`hit_set_persist()` در `PrimaryLogPG.cc`) و با `hit_set_trim()` کوتاه می‌شوند. این یعنی کش برای ردیابی داغی هم I/O اضافه دارد. هر promote هم یک خواندن از pool پایه و یک نوشتن در کش است؛ اگر الگوی دسترسی پراکنده باشد (بیشتر بارهای RBD)، کش دائماً در حال promote و evict است و کارایی از pool بدون کش هم بدتر می‌شود. مستندات رسمی همین را صریحاً می‌گوید: cache tiering برای بیشتر بارها کارایی را کاهش می‌دهد و فقط وقتی مؤثر است که دسترسی‌ها به مجموعه‌ی کوچکی از اشیا متمرکز باشد (مثلاً RGW با خواندن عمدتاً اشیای تازه‌نوشته).
:::

# از درون کد: عامل کش {#sec-16-3}

## agent_choose_mode: سنجش پری و کثیفی {#sec-16-3-1}

عامل کش در هر PG کش با `agent_setup()` فعال می‌شود و OSD در یک thread جدا، `agent_work()` را روی PGهای فعال اجرا می‌کند (حداکثر عملیات هم‌زمان با `osd_agent_max_ops` کنترل می‌شود که در کد جاری پیش‌فرضش ۴ است). تصمیم اصلی در `PrimaryLogPG::agent_choose_mode()` گرفته می‌شود. نکته‌ی جالب این است که اهداف **کل pool** (مثلاً `target_max_bytes`) با یک «مقسوم‌علیه» به سهم هر PG تبدیل می‌شوند: `pg_pool_t::get_pg_num_divisor()` تعداد PGها را با در نظر گرفتن تقسیم ناتمام (وقتی pg_num توان ۲ نیست) برمی‌گرداند. همه‌ی نسبت‌ها با واحد **میکرو** (یک‌میلیونیم) و عدد صحیح محاسبه می‌شوند تا از ممیز شناور پرهیز شود.

```text
pseudocode: agent_choose_mode (بازنویسی این کتاب از PrimaryLogPG.cc)
  divisor   = pool.get_pg_num_divisor(pgid)         # سهم این PG از هدف pool
  avg_size  = user_bytes / user_objects
  dirty_µ   = dirty_objs * avg_size * 1e6 / (target_max_bytes / divisor)
  full_µ    = user_objs  * avg_size * 1e6 / (target_max_bytes / divisor)
  if target_max_objects:                            # هر کدام بزرگ‌تر باشد
      dirty_µ = max(dirty_µ, dirty_objs * 1e6 / (target_max_objects / divisor))
      full_µ  = max(full_µ,  user_objs  * 1e6 / (target_max_objects / divisor))

  slop = target * osd_agent_slop                    # هیسترزیس (پیش‌فرض 0.02)
  target' = target + slop  if currently IDLE  else target - slop

  flush_mode = HIGH if dirty_µ > dirty_high' else LOW if dirty_µ > dirty' else IDLE
  if   full_µ > 1e6:        evict_mode = FULL; effort = 1e6     # هر شیء clean را بیرون کن
  elif full_µ > full':      evict_mode = SOME
      effort = max((full_µ - full') * 1e6 / (1e6 - full'), osd_agent_min_evict_effort)
      effort = quantize(effort, osd_agent_quantize_effort)   # کاهش جابه‌جایی در صف عامل
  else:                     evict_mode = IDLE
```

![ماشین حالت عامل کش: سه حالت flush (IDLE، LOW، HIGH) بر اساس نسبت اشیای dirty به هدف و سه حالت evict (IDLE، SOME، FULL) بر اساس پری؛ هیسترزیس با osd_agent_slop از نوسان سریع بین حالت‌ها جلوگیری می‌کند چون آستانه‌ی ورود کمی بالاتر و آستانه‌ی خروج کمی پایین‌تر از هدف است](figures/ch16/f02_modes.png){#fig-16-f02_modes}

## انتخاب قربانی: دمای شیء {#sec-16-3-2}

در حالت SOME، `agent_maybe_evict()` برای هر شیء clean «دما»ی آن را با `agent_estimate_temp()` از روی HitSetهای اخیر تخمین می‌زند (برای هر HitSet که شیء در آن هست، وزن `pool.info.get_grade(i)` جمع می‌شود؛ وزن‌ها با `hit_set_grade_decay_rate` برای HitSetهای قدیمی‌تر کاهش می‌یابند و شیئی که در HitSet جاری باشد دمای بیشینه می‌گیرد) و آن را در یک هیستوگرام (`temp_hist`) قرار می‌دهد. سپس جایگاه شیء در توزیع دما (`get_position_micro`) را با `evict_effort` مقایسه می‌کند: نیت طراحی این است که شیء داغ نگه داشته شود، اما شرط واقعی کد main وارونه است (بخش «دما با عدد» را ببینید). بنابراین evict یک LRU دقیق نیست، بلکه **نمونه‌گیری آماری** روی دما است که هزینه‌ی حافظه‌ی کم دارد.

```text
pseudocode: agent_maybe_evict (خلاصه)
  if obj dirty or in use or age < cache_min_evict_age: skip
  if evict_mode != FULL:
      temp = estimate_temp(obj, hitsets)             # مجموع وزن‌دار حضور در HitSetها
      hist.add(temp); (lower, upper) = hist.position_µ(temp)
      if 1e6 - upper >= evict_effort: keep           # شرط لفظی کد؛ معنایش در بخش «دما با عدد» بررسی شده است
  evict(obj)                                         # حذف از کش؛ نسخه‌ی معتبر در pool پایه است
```

::: {.deep}
flush در `agent_maybe_flush()` و `start_flush()` انجام می‌شود: شیء dirty (همراه snapshotهایش) با عملیات copy-from به pool پایه نوشته می‌شود و پس از تأیید، پرچم dirty پاک می‌شود. `cache_min_flush_age` جلوی flush شیئی را که تازه نوشته شده می‌گیرد. اگر کش به `target_max_bytes` یا `target_max_objects` برسد و عامل نتواند به اندازه‌ی کافی flush و evict کند، OSD **درخواست‌های کلاینت را مسدود می‌کند**؛ این یکی از رایج‌ترین علت‌های قطع سرویس در کلاسترهای دارای کش بود.
:::

::: {.warn}
اگر هیچ‌کدام از `target_max_bytes` و `target_max_objects` تنظیم نشده باشد، نسبت‌های پری صفر محاسبه می‌شوند و عامل هرگز بر اساس پری evict نمی‌کند؛ کش تا پر شدن OSDها رشد می‌کند. در شبه‌کد بالا هم دیدید که پری فقط وقتی محاسبه می‌شود که این اهداف تنظیم شده باشند.
:::

# مهاجرت: حذف بی‌خطر cache tier {#sec-16-4}

![روال حذف cache tier حالت writeback: تغییر به proxy برای توقف promote، تخلیه با cache-flush-evict-all و تکرار تا خالی شدن pool کش، سپس حذف overlay و جدا کردن tier](figures/ch16/f03_remove.png){#fig-16-f03_remove}

```bash
# ۱. وضعیت فعلی
ceph osd pool ls detail | grep -E "tier|cache_mode|read_tier|write_tier"
ceph df detail
# ۲. توقف promote و نوشتن در کش
ceph osd tier cache-mode hot-storage proxy
# ۳. تخلیه (ممکن است ساعت‌ها طول بکشد؛ پیشرفت را پایش کنید)
rados -p hot-storage cache-flush-evict-all
rados -p hot-storage ls | head
# ۴. حذف overlay و tier
ceph osd tier remove-overlay cold-storage
ceph osd tier remove cold-storage hot-storage
```

::: {.tip}
پیش از شروع، ظرفیت آزاد pool پایه را بررسی کنید: همه‌ی اشیای dirty باید آنجا نوشته شوند. اگر pool پایه EC روی HDD است، flush انبوه بار سنگینی می‌سازد؛ در ساعات کم‌بار انجام دهید و `ceph -s` و تأخیر کلاینت را پایش کنید.
:::

::: {.note}
مستندات رسمی برای ارتقاهای قدیمی (۱۴.۲.۶ به ۱۴.۲.۷) موردی از **اشیای unfound** پس از راه‌اندازی دوباره‌ی OSDها در pool کش را ثبت کرده است. اگر پس از ارتقا یا راه‌اندازی دوباره چنین چیزی دیدید، پیش از هر اقدام `ceph pg <pgid> list_unfound` را بررسی کنید و راهنمای همان صفحه را دنبال کنید.
:::

## اگر pool پایه EC است {#sec-16-4-1}

دلیل تاریخی بسیاری از cache tierها این بود که پیش از Luminous، pool EC از overwrite پشتیبانی نمی‌کرد و RBD یا CephFS نمی‌توانستند مستقیم روی آن کار کنند. امروز با `allow_ec_overwrites` (و در Tentacle، بهینه‌سازی‌های FastEC؛ فصل ۱۳) این محدودیت برطرف شده است: فراداده در pool تکثیری و داده در pool EC قرار می‌گیرد (`rbd create --data-pool`، یا افزودن data pool EC به CephFS).

# لایه‌بندی در سطح بایت: storage class در RGW و lifecycle {#sec-16-5}

در بخش‌های قبل دیدیم cache tiering از Reef منسوخ اعلام شده است (هشدار ابتدای مستند `cache-tiering.rst`) و جایگزین‌های امروزی، یعنی device class، pool جدا برای داده و فراداده و storage class در RGW، چیست. این بخش نشان می‌دهد یک شیء S3 هنگام «جابه‌جایی بین لایه‌ها» واقعاً در RADOS چه تغییری می‌کند.

## چیدمان یک شیء RGW {#sec-16-5-1}

![شیء S3 ده‌مگابایتی در RADOS. شیء HEAD فراداده (manifest، ACL، etag و سایر xattrها) و در storage class پیش‌فرض، اولین تکه‌ی داده (تا rgw_max_chunk_size=4M) را به‌صورت inline نگه می‌دارد. بقیه‌ی داده در اشیای tail با اندازه‌ی rgw_obj_stripe_size=4M قرار دارد. پس از transition به یک storage class دیگر، HEAD در pool پیش‌فرض می‌ماند ولی manifest آن به tailهای تازه در data_pool کلاس جدید اشاره می‌کند و داده‌ی قدیمی به garbage collection سپرده می‌شود. پایین شکل poolهای یک placement target را نشان می‌دهد](figures/ch16/f05_rgwlayout.png){#fig-16-f05_rgwlayout}

**manifest** (در xattr با نام `user.rgw.manifest`) نقشه‌ی شیء منطقی به اشیای RADOS است: اندازه‌ی head، اندازه‌ی stripe، prefix اشیای tail و قواعد نام‌گذاری آن‌ها. این توضیح می‌دهد چرا transition «ارزان» به نظر می‌رسد ولی در واقع **کپی کامل داده** است: RGW داده را از tailهای قدیمی می‌خواند، در pool کلاس جدید می‌نویسد، manifest را به‌روز می‌کند و اشیای قدیمی را برای حذف به GC می‌دهد. پهنای باند lifecycle همان پهنای باند خوشه است.

| گزینه / ویژگی | مقدار (main) | اثر |
|---|---|---|
| `rgw_max_chunk_size` | 4_M | اندازه‌ی تکه‌ی head و واحد خواندن و نوشتن RGW |
| `rgw_obj_stripe_size` | 4_M | اندازه‌ی اشیای tail |
| `--placement-inline-data` | true (پیش‌فرض) | داده‌ی اول در head؛ طبق مستندات، inline فقط در کلاس پیش‌فرض انجام می‌شود |
| `data_extra_pool` | مثلاً `default.rgw.buckets.non-ec` | فراداده‌ی multipart ناتمام؛ باید replicated باشد (omap) |
| `index_pool` | مثلاً `default.rgw.buckets.index` | bucket index (فقط omap)؛ بهترین جا برای SSD یا NVMe |

::: {.tip}
طبق مستند `placement.rst`، اگر DB مربوط به BlueStore روی دستگاه سریع‌تر از داده‌ی bucket باشد، خاموش کردن inline (`--placement-inline-data=false`) می‌تواند حذف‌های کلاینت را سریع‌تر کند، چون RGW هنگام DELETE دیگر لازم نیست هم‌گام به دستگاه کند دست بزند و داده بعداً توسط GC حذف می‌شود. بده‌بستان آن یک رفت‌وبرگشت اضافه برای خواندن و نوشتن اشیای کوچک است.
:::

## lifecycle چگونه اجرا می‌شود؟ {#sec-16-5-2}

![اجرای lifecycle در RGW. فهرست bucketهای دارای قاعده در rgw_lc_max_objs=32 شیء RADOS (shardهای lc) نگه داشته می‌شود. فقط در پنجره‌ی rgw_lifecycle_work_time (پیش‌فرض 00:00 تا 06:00 به وقت محلی) کار انجام می‌شود. هر shard با قفلی با عمر rgw_lc_lock_max_time=90 ثانیه برداشته می‌شود. rgw_lc_max_worker=3 worker موازی، هرکدام با ۱۲۸ coroutine (rgw_lc_max_wp_worker)، bucket index را پیمایش و expire، transition یا abort multipart را اجرا می‌کنند](figures/ch16/f06_lc.png){#fig-16-f06_lc}

```bash
radosgw-admin lc list                          # وضعیت هر bucket: UNINITIAL / PROCESSING / COMPLETE
radosgw-admin lc get --bucket photos
radosgw-admin lc process --bucket photos       # اجرای دستی (خارج از پنجره)
radosgw-admin gc list --include-all | head
ceph config set client.rgw rgw_lifecycle_work_time "00:00-23:59"   # فقط برای آزمایش
```

::: {.warn}
**محاسبه‌ی ظرفیت:** با ۳ worker و ۱۲۸ coroutine، در هر لحظه تا حدود ۳۸۴ شیء هم‌زمان پردازش می‌شود. اگر هر شب ۵۰ ترابایت باید از STANDARD به COLD برود و پنجره‌ی کار ۶ ساعت باشد، خوشه باید حدود 50 TB / 21600 s ≈ 2.3 GB/s خواندن و همان اندازه نوشتن (به‌علاوه‌ی سربار EC یا replication) را **علاوه بر** بار عادی تحمل کند. در غیر این صورت lifecycle هر شب عقب می‌افتد و صف آن رشد می‌کند. پیش از تعریف قواعد transition، این عدد را حساب کنید.
:::

## لایه‌بندی داخل یک OSD {#sec-16-5-3}

لایه‌بندی فقط بین poolها نیست. یک OSD با دستگاه‌های block.db و block.wal سه لایه دارد. فصل ۲۵ نشان داد BlueFS سطوح RocksDB را با سیاست `use_some_extra` بین WAL، DB و دستگاه کند پخش می‌کند. فصل ۲۴ نشان داد deferred writeهای کوچک‌تر از `bluestore_prefer_deferred_size` (در HDD برابر 64K) ابتدا در WAL مربوط به RocksDB (یعنی روی دستگاه سریع) نوشته و بعداً به HDD منتقل می‌شوند. این عملاً یک **write-back cache کوچک** برای نوشتن‌های کوچک روی HDD است، بدون پیچیدگی‌های cache tiering. فصل ۲۸ هم نشان داد device classها با shadow treeهای جداگانه تضمین می‌کنند افزودن دستگاه به یک کلاس هیچ داده‌ای را در poolهای کلاس دیگر جابه‌جا نکند.

| لایه | سازوکار | فصل |
|---|---|---|
| PG→دستگاه | device class + قاعده‌ی CRUSH | ۸ و ۲۸ |
| فراداده‌ی RGW | index_pool و data_extra_pool روی SSD | ۴ و همین فصل |
| داده‌ی سرد | storage class و lifecycle transition | همین فصل |
| فراداده‌ی OSD | block.db و block.wal (BlueFS) | ۱۲، ۲۴ و ۲۵ |
| نوشتن کوچک روی HDD | deferred write | ۱۲ و ۲۴ |
| فراداده‌ی RBD | pool داده‌ی جدا (`--data-pool`) روی EC | ۲ و ۱۳ |

# لایه‌بندی با عدد: شش الگوریتم از کد {#sec-16-6}

این بخش سازوکارهای لایه‌بندی را که بالاتر توصیف شدند، با کد و عدد بررسی می‌کند. سه الگوریتم مربوط به cache tiering است (منسوخ، اما هنوز در کد main)، دو الگوریتم به lifecycle در RGW، و یکی به جای‌گذاری داده‌ی RocksDB میان دستگاه سریع و کند درون OSD.

## اندازه‌ی HitSet {#sec-16-6-1}

::: {.algo #alg-16-1 title="اندازه‌ی فیلتر Bloom در HitSet" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::hit_set_create؛ src/osd/BloomHitSet.h :: BloomHitSet" complexity="O(1) برای تعیین اندازه؛ حافظه −n·ln(p)/(ln 2)² بیت"}
:::

```text
pseudocode
p = fpp_pool / hit_set_count ; if p ≤ 0: p = 0.01
if target_size == 0 and hit_set قبلی هست:
    target_size = unique_inserts(قبلی) × hit_set_period / مدت واقعی قبلی
target_size = clamp(target_size, osd_hit_set_min_size = 1000, osd_hit_set_max_size = 100000)
seed = now.sec ; BloomHitSet(target_size, p, seed)
```

**مثال عددی.** با پیش‌فرض‌های `osd_tier_default_cache_*` که `ceph osd tier add-cache` اعمال می‌کند (bloom، hit_set_count = 4، hit_set_period = 1200 s) و `osd_pool_default_hit_set_bloom_fpp = 0.05`، نرخ مثبت کاذب هر مجموعه 0.05/4 = 0.0125 است. اگر HitSet قبلی در 1200 ثانیه 30000 شیء یکتا دیده باشد، target_size = 30000 و فیلتر حدود $2.7 \times 10^5$ بیت (حدود 33 KiB) با 6 تابع hash است. سقف 100000 شیء فیلتری حدود 111 KiB می‌دهد و کف 1000 حدود 1.1 KiB. دلیل تقسیم fpp بر تعداد مجموعه‌ها این است که دما از جمع حضور در چند مجموعه به دست می‌آید و خطای هر مجموعه جمع می‌شود.

![اندازه‌ی فیلتر Bloom یک HitSet برحسب تعداد اشیای یکتای مجموعه‌ی قبلی، برای دو مقدار hit_set_period. اندازه‌ی هدف به نسبت دوره‌ی تازه به مدت واقعی مجموعه‌ی قبلی مقیاس می‌شود و میان کف و سقف OSD بریده می‌شود. خط‌چین‌ها همین دو حد هستند. هر PG کش در هر دوره یک فیلتر می‌سازد و آن را به‌صورت شیء در namespace جداگانه‌ی همان pool بایگانی می‌کند](figures/ch16/f12_hitset.png){#fig-16-f12_hitset}

## دما با عدد {#sec-16-6-2}

::: {.algo #alg-16-2 title="جدول درجه و دمای شیء" src="src/osd/osd_types.h :: pg_pool_t::calc_grade_table، get_grade؛ src/osd/PrimaryLogPG.cc :: agent_estimate_temp، agent_maybe_evict؛ src/common/histogram.h :: pow2_hist_t::get_position_micro" complexity="O(hit_set_count) برای هر شیء؛ هیستوگرام توانی O(log temp)"}
:::

```text
pseudocode
calc_grade_table: v = 10^6 ; for i < count: v = v × (1 − decay/100) ; grade[i] = v
estimate_temp(o): t = (o ∈ current) ? 10^6 : 0
    for i, set in archived (جدید به قدیم) while last_n > 0: if o ∈ set: t += grade[i] ; last_n−−
agent_maybe_evict (حالت SOME):
    hist.add(t) ; (lower, upper) = hist.position_µ(t)   # upper = سهم اشیای با bin ≤ bin(t)
    if 10^6 − upper ≥ evict_effort: نگه دار  else: evict   # شرط لفظی main؛ نسبت به نیت «سرد را بیرون کن» وارونه است
```

**مثال عددی.** با پیش‌فرض‌های `osd_tier_default_cache_*` (decay_rate = 20، search_last_n = 1)، جدول درجه 800000، 640000، 512000 و 409600 است. چهار شیء نمونه:

- A فقط در مجموعه‌ی جاری است: دما 1000000.
- B در جاری و در مجموعه‌ی 0 است: 1800000.
- C فقط در مجموعه‌ی 1 است: 640000.
- D در هیچ مجموعه‌ای نیست: 0.

اکنون معنای شرط کد: get_position_micro مقدار upper را برابر سهم اشیایی می‌گذارد که bin توانی دمایشان (`cbits(temp)`، یعنی شماره‌ی بالاترین بیت یک) کوچک‌تر یا مساوی bin این شیء است، و lower را سهم اشیای bin کوچک‌تر. یک هیستوگرام ده‌نمونه‌ای بسازیم: پنج نمونه با دمای 0 (bin 0)، دو نمونه 640000 و دو نمونه 1000000 (هر دو bin 20) و یک نمونه 1800000 (bin 21). با evict_effort = 400000 نتیجه این است:

| شیء | دما | bin | lower | upper | $10^6 - \text{upper}$ | تصمیم کد main | تصمیم با اصلاح پیشنهادی (lower ≥ effort ⇒ نگه دار) |
|---|---|---|---|---|---|---|---|
| D | 0 | 0 | 0 | 500000 | 500000 | نگه می‌دارد | بیرون می‌کند |
| C | 640000 | 20 | 500000 | 900000 | 100000 | بیرون می‌کند | نگه می‌دارد |
| A | 1000000 | 20 | 500000 | 900000 | 100000 | بیرون می‌کند | نگه می‌دارد |
| B | 1800000 | 21 | 900000 | 1000000 | 0 | بیرون می‌کند | نگه می‌دارد |

این عددها با یک بازپیاده‌سازی پایتونی از `pow2_hist_t::get_position_micro` به دست آمده‌اند. پس شرط کد main واقعاً **وارونه** است: سردترین شیء (D) می‌ماند و داغ‌ها بیرون می‌روند. این وارونگی سابقه‌ی مستند دارد. پیش از Jewel، عامل به‌جای دما از «فاصله از آخرین دسترسی» (atime) استفاده می‌کرد که برای داده‌ی سرد **بزرگ‌تر** است، و شرط `1000000 − atime_upper ≥ evict_effort ⇒ نگه دار` با آن معنا درست بود. PR شماره‌ی 4737 (شاخه‌ی wip-temp-based-object-eviction) معیار را به دما تغییر داد، که برای داده‌ی سرد **کوچک‌تر** است، اما فقط نام متغیر را در شرط عوض کرد. در نوامبر 2017 در فهرست ceph-devel (رشته‌ی «About the "temperature histogram" of tier-agent») همین مسئله گزارش شد و Sage Weil آن را برای بررسی به نویسندگان آن PR ارجاع داد. پیشنهاد شد شرط به `temp_upper ≥ evict_effort` یا `temp_lower ≥ evict_effort` تغییر کند، اما در کد main امروز (بررسی‌شده در نوامبر 2026) شرط همچنان همان شکل قدیمی را دارد. در حالت EVICT_MODE_FULL این شرط اصلاً اجرا نمی‌شود و هر شیء clean و واجد شرایط بیرون می‌رود؛ پس اثر وارونگی فقط در حالت SOME دیده می‌شود. این یکی دیگر از دلیل‌هایی است که cache tiering (که از Reef منسوخ اعلام شده است) نباید برای کارهای تازه انتخاب شود.

![شرط evict در حالت SOME برای هیستوگرام ده‌نمونه‌ای مثال. محور افقی bin توانی دما و ستون‌ها تعداد نمونه‌ها در هر bin هستند. سمت چپ تصمیم کد main است، با شرط 10⁶ − upper ≥ effort برای نگه داشتن: فقط bin سرد صفر می‌ماند (سبز) و همه‌ی binهای داغ بیرون می‌روند (قرمز). سمت راست تصمیم با اصلاح پیشنهادی ceph-devel در 2017 است، با شرط lower ≥ effort برای نگه داشتن: سردها بیرون می‌روند و داغ‌ها می‌مانند. خط‌چین در هر دو نیمه مرز تصمیم روی محور سهم تجمعی است: در کد main مرز upper = 0.6 (یعنی 1 − 0.4) و در اصلاح پیشنهادی مرز lower = 0.4 است](figures/ch16/f13_evictinv.png){#fig-16-f13_evictinv}

![سمت چپ جدول درجه‌ی HitSetهای بایگانی‌شده برای دو نرخ کاهش است: با decay 20 وزن قدیمی‌ترین مجموعه هنوز 41٪ است و با decay 50 فقط 6٪. سمت راست دمای چهار شیء نمونه است: حضور در مجموعه‌ی جاری همیشه یک میلیون واحد می‌گیرد و با search_last_n = 1 فقط نخستین مجموعه‌ی بایگانی که شیء در آن پیدا شود، سهمش را اضافه می‌کند](figures/ch16/f07_grade.png){#fig-16-f07_grade}

## evict_effort با عدد {#sec-16-6-3}

::: {.algo #alg-16-3 title="محاسبه‌ی evict_effort" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::agent_choose_mode" complexity="O(1) برای هر PG در هر اجرای عامل"}
:::

```text
pseudocode
target = cache_target_full_ratio × 10^6 ; slop = target × osd_agent_slop (0.02)
target = (IDLE یا restart) ? target + slop : target − slop        # هیسترزیس
if full_µ > 10^6: FULL ; effort = 10^6
elif full_µ > target: SOME
    effort = max((full_µ − target) × 10^6 / (10^6 − target), 0.1 × 10^6)
    effort −= effort % (0.1 × 10^6) ; effort = max(effort, 0.1 × 10^6)
```

**مثال عددی.** cache_target_full_ratio = 0.8 (پیش‌فرض)، پس target = 800000 و slop = 16000. عامل از IDLE شروع می‌کند، پس آستانه 816000 است. با full = 0.90: over = 84000، span = 184000 و effort خام 456521 است که به 400000 گرد می‌شود. وقتی پری به 0.80 برمی‌گردد، آستانه‌ی خروج 784000 است. پس عامل تا full ≤ 0.784 در SOME می‌ماند. فاصله‌ی 3.2 درصدی میان ورود و خروج از رفت‌وبرگشت سریع جلوگیری می‌کند. گرد کردن به گام‌های 0.1 هم ترتیب صف عامل در OSD را پایدار نگه می‌دارد.

![evict_effort برحسب نسبت پری برای دو حالت هیسترزیس. منحنی آبی وقتی است که عامل بی‌کار بوده و آستانه‌ی ورود 0.816 است. منحنی قرمز وقتی است که عامل در حال بیرون کردن است و آستانه به 0.784 پایین می‌آید. پله‌ها ناشی از کوانتش 0.1 هستند و بالای پری 100٪ تلاش یکباره به 1.0 می‌پرد](figures/ch16/f08_effort.png){#fig-16-f08_effort}

## شارد lifecycle و انتخاب شیء lc.N {#sec-16-6-4}

::: {.algo #alg-16-4 title="نگاشت bucket به شارد lifecycle و پیمایش کارگرها" src="src/rgw/rgw_lc.cc :: get_lc_index، get_bucket_lc_key، random_sequence، RGWLC::process؛ src/common/ceph_hash.cc :: ceph_str_hash_linux" complexity="hash O(طول کلید)؛ هر کارگر O(rgw_lc_max_objs) شارد در هر دور"}
:::

```text
pseudocode
key = tenant + ":" + bucket + ":" + marker
h = 0 ; for c in key: h = (h + (c ≪ 4) + (c ≫ 4)) × 11   (mod 2^32)
index = h % 7877 % min(rgw_lc_max_objs, 7877)    # پیش‌فرض 32 ⇒ lc.0 .. lc.31
RGWLC::process(worker): for shard in shuffle(0..31):
    lock lc.shard (حداکثر rgw_lc_lock_max_time = 90 s) ; ورودی بعدی را PROCESSING کن ; unlock
    bucket_lc_process(bucket) با استخر rgw_lc_max_wp_worker coroutine
```

**مثال عددی.** marker یک bucket در RADOS هنگام ساخت با `RGWRados::create_bucket_id` ساخته می‌شود و قالب آن `<zone id>.<instance id>.<شمارنده>` است: شناسه‌ی zone (یک UUID)، شناسه‌ی نمونه‌ی کلاینت RADOS آن radosgw و یک شمارنده‌ی افزایشی. marker زیر قالب واقعی را دارد، اما UUID و دو عدد آن **مثال** هستند و از کلاستر واقعی نیامده‌اند. برای bucket با نام `photos`، tenant خالی و marker `3f6e1c2a-77b1-4e0b-9d2c-1a2b3c4d5e6f.4137.1`، کلید (که `get_bucket_lc_key` با جداکننده‌ی «:» می‌سازد) `:photos:3f6e…4137.1` است. ceph_str_hash_linux عدد 2997460109 را می‌دهد. 2997460109 mod 7877 = 1668 و 1668 mod 32 = 4، پس ورودی این bucket در شیء `lc.4` نوشته می‌شود. سه کارگر (rgw_lc_max_worker) شاردها را به ترتیب تصادفی می‌گردند تا همه هم‌زمان سراغ lc.0 نروند. چون hash ضعیف است و فقط 32 شارد وجود دارد، چند bucket بزرگ ممکن است در یک شارد بیفتند و پشت هم پردازش شوند. `radosgw-admin lc list` وضعیت هر bucket را نشان می‌دهد.

![مسیر یک قانون lifecycle از ثبت تا اجرا. کلید bucket با hash ساده‌ی لینوکسی به یکی از 32 شیء lc.N نگاشت می‌شود. در پنجره‌ی کاری (پیش‌فرض 00:00 تا 06:00 به وقت محلی سرور)، هر کارگر شاردها را به ترتیب تصادفی قفل می‌کند و bucket بعدی را برمی‌دارد. سپس اشیای bucket را با استخری از coroutineها بررسی می‌کند و برای هر نسخه انقضا یا انتقال را اعمال می‌کند](figures/ch16/f10_lcshard.png){#fig-16-f10_lcshard}

## چه روزی یک شیء منقضی می‌شود؟ {#sec-16-6-5}

::: {.algo #alg-16-5 title="محاسبه‌ی انقضا با گرد کردن به نیمه‌شب" src="src/rgw/rgw_lc.cc :: obj_has_expired؛ src/include/utime.h :: utime_t::round_to_day" complexity="O(1) برای هر نسخه‌ی شیء"}
:::

```text
pseudocode
if rgw_lc_debug_interval ≤ 0:
    cmp = days × 86400 ; base = round_to_day(now)        # نیمه‌شب محلی امروز (localtime_r/mktime)
else: cmp = days × rgw_lc_debug_interval ; base = now     # حالت آزمایشی: هر «روز» چند ثانیه
expired = (base − mtime) ≥ cmp ; expire_time = mtime + cmp
```

**مثال عددی.** شیئی در روز 0 ساعت 14:24 نوشته شده و قانون Expiration با Days = 30 دارد. اجرای روز 30: base = نیمه‌شب روز 30، فاصله 29.4 روز است و کمتر از 30، پس می‌ماند. اجرای روز 31: فاصله 30.4 روز است، پس حذف می‌شود. پس شیء عملاً بین 30.4 تا 31.25 روز (بسته به زمان اجرای کارگر در پنجره) زنده می‌ماند. چون base از ساعت محلی سرور RGW می‌آید، دو RGW با منطقه‌ی زمانی متفاوت ممکن است یک روز با هم اختلاف داشته باشند. با `rgw_lc_debug_interval = 10` هر روز قانون 10 ثانیه است و Days = 30 یعنی 300 ثانیه، که برای آزمودن قانون‌ها در آزمایشگاه کاربرد دارد.

![خط زمانی انقضای شیئی با Days = 30. شیء در میانه‌ی روز 0 نوشته شده است. obj_has_expired زمان مبنا را به نیمه‌شب گرد می‌کند، پس اجرای روز 30 فاصله‌ی 29.4 روز می‌بیند و شیء را نگه می‌دارد. نخستین اجرایی که حذف می‌کند، در پنجره‌ی روز 31 است](figures/ch16/f11_lcexpire.png){#fig-16-f11_lcexpire}

## جای‌گذاری سطوح RocksDB میان DB و دستگاه کند {#sec-16-6-6}

::: {.algo #alg-16-6 title="ظرفیت اضافه‌ی DB در use_some_extra" src="src/os/bluestore/BlueFS.h :: RocksDBBlueFSVolumeSelector (سازنده، get_extra_level، get_hint_by_dir)؛ src/os/bluestore/BlueStore.cc :: BlueStore::_open_bluefs (ساخت vselector)" complexity="O(log_multiplier(DB/base)) برای حلقه‌ی سطوح، یک‌بار هنگام mount"}
:::

```text
pseudocode
db_total = 0.95 × اندازه‌ی DB ; L0 = write_buffer_size × max_write_buffer_number
if bluestore_volume_selection_reserved == 0:
    prev = L0 ; cur = base ; extra_level = 1
    loop: next = cur × mult ; extra_level++
          if db_total ≤ prev + cur + next:
              db_avail4slow = max(0, db_total − (prev + cur × reserved_factor)) ; break
          prev += cur ; cur = next
else: db_avail4slow = max(0, db_total − reserved) ; extra_level = 0
```

**مثال عددی (پیش‌فرض‌های Ceph: L0 = 16 MiB × 64 = 1 GiB، base = 1 GiB، mult = 8، reserved_factor = 2).**

- **DB سی گیگابایتی (28.5 GiB قابل استفاده):** حلقه در آستانه‌ی 2 + 8 + 64 متوقف می‌شود و cur_threshold = 2 + 8×2 = 18، پس 10.5 GiB برای داده‌ی سطح کند روی DB می‌ماند.
- **DB شصت گیگابایتی:** 57 − 18 = 39 GiB.
- **DB صد و بیست گیگابایتی (114 GiB):** حلقه یک سطح جلوتر می‌رود (آستانه 10 + 64 + 512). cur_threshold = 10 + 64×2 = 138 از 114 بزرگ‌تر است، پس db_avail4slow = 0.
- **DB سیصد گیگابایتی:** 285 − 138 = 147 GiB.

پس DB بزرگ‌تر همیشه فضای اضافه‌ی بیشتری نمی‌دهد. اندازه‌هایی که درست پس از یک مرز سطح قرار می‌گیرند، کمترین بهره را دارند. این همان دلیل توصیه‌های قدیمی «DB را 30، 300 یا 3000 گیگابایت بگیرید» است. سیاست `fit_to_fast` این محاسبه را کنار می‌گذارد و تا 95٪ دستگاه سریع را پر می‌کند.

![فضای DB که سیاست پیش‌فرض use_some_extra برای فایل‌های سطح‌های بالاتر RocksDB مجاز می‌داند، برحسب اندازه‌ی دستگاه DB. منحنی دندانه‌ای است: پس از هر مرز سطح، فرمول دو برابر اندازه‌ی سطح جاری را رزرو می‌کند و فضای اضافه به صفر می‌افتد. نقطه‌های قرمز چهار اندازه‌ی مثال متن‌اند. خط‌چین سقف 95 درصدی دستگاه است](figures/ch16/f09_vsel.png){#fig-16-f09_vsel}

::: {.note}
این محاسبه فقط تعیین می‌کند BlueFS فایل‌های سطح‌های بالا را **ترجیحاً** کجا بگذارد. اگر DB پر شود، BlueFS باز هم به دستگاه کند می‌ریزد (spillover) و هشدار `BLUEFS_SPILLOVER` در `ceph health` ظاهر می‌شود. `ceph daemon osd.N bluefs stats` توزیع واقعی هر سطح را میان WAL، DB و SLOW نشان می‌دهد.
:::

# جایگزین‌های امروزی {#sec-16-7}

![سه سطح لایه‌بندی امروزی در Ceph: در سطح pool با device class و قانون‌های CRUSH جدا برای nvme و hdd، درون OSD با قرار دادن block.db و WAL روی NVMe کنار داده‌ی HDD، و در سطح شیء با storage class و قانون lifecycle در RGW که اشیا را پس از مدتی به pool ظرفیتی یا فضای ابری منتقل می‌کند](figures/ch16/f04_alt.png){#fig-16-f04_alt}

## ۱. device class و pool جدا برای هر لایه {#sec-16-7-1}

ساده‌ترین و قابل‌پیش‌بینی‌ترین روش: داده‌ی داغ و سرد را **در سطح برنامه** جدا کنید و هر کدام را در pool مناسب بگذارید. از Luminous، هر OSD یک device class (hdd، ssd، nvme یا نام دلخواه) دارد و قانون CRUSH می‌تواند فقط OSDهای یک کلاس را انتخاب کند.

```bash
ceph osd crush class ls
ceph osd crush rule create-replicated fast-rule default host nvme
ceph osd erasure-code-profile set cold-ec k=4 m=2 crush-failure-domain=host crush-device-class=hdd
ceph osd pool create vm-fast 128 128 replicated fast-rule
ceph osd pool create archive 256 256 erasure cold-ec
ceph osd pool set archive allow_ec_overwrites true
# RBD با فراداده روی pool سریع و داده روی EC
rbd create --size 1T --data-pool archive vm-fast/backup01
```

::: {.tip}
**انتقال یک pool به لایه‌ی دیگر** فقط با تغییر قانون CRUSH ممکن است: `ceph osd pool set <pool> crush_rule fast-rule`. Ceph داده را با backfill جابه‌جا می‌کند؛ با `osd_max_backfills` و برنامه‌ریز mclock (فصل ۲۱) اثرش را روی کلاینت محدود کنید.
:::

## ۲. لایه‌بندی درون OSD با BlueStore {#sec-16-7-2}

برای OSDهای HDD، قرار دادن `block.db` (RocksDB) و WAL روی NVMe بیشترین اثر را در ازای کمترین پیچیدگی دارد: فراداده، omap و نوشتن‌های کوچک deferred (فصل ۱۲؛ `bluestore_prefer_deferred_size_hdd=64K`) روی رسانه‌ی سریع انجام می‌شوند و HDD فقط نوشتن‌های بزرگ و ترتیبی را می‌بیند. در cephadm با مشخصات سرویس OSD:

```yaml
service_type: osd
service_id: hdd-with-nvme-db
placement:
  host_pattern: 'stor-*'
spec:
  data_devices:
    rotational: 1
  db_devices:
    rotational: 0
```

## ۳. storage class و lifecycle در RGW {#sec-16-7-3}

برای ذخیره‌سازی شیء، الگوی S3 یعنی **storage class** و انتقال با lifecycle، نزدیک‌ترین جایگزین «کش» است با این تفاوت مهم که تصمیم‌ها قطعی و قابل حسابرسی‌اند، نه آماری.

```bash
radosgw-admin zonegroup placement add --rgw-zonegroup default \
    --placement-id default-placement --storage-class COLD
radosgw-admin zone placement add --rgw-zone default \
    --placement-id default-placement --storage-class COLD \
    --data-pool default.rgw.cold.data --compression lz4
```

```json
{ "Rules": [ { "ID": "to-cold-after-30d", "Status": "Enabled",
    "Filter": { "Prefix": "logs/" },
    "Transitions": [ { "Days": 30, "StorageClass": "COLD" } ] } ] }
```

```bash
aws --endpoint-url https://s3.example.internal s3api put-bucket-lifecycle-configuration \
    --bucket app-logs --lifecycle-configuration file://lc.json
radosgw-admin lc list
```

::: {.note}
RGW از **cloud transition** هم پشتیبانی می‌کند: storage class از نوع `cloud-s3` که اشیا را به یک endpoint S3 بیرونی منتقل می‌کند (صفحه‌ی Cloud Transition در مستندات). این برای بایگانی بلندمدت در فضای دیگر مناسب است.
:::

## ۴. سایر ابزارها {#sec-16-7-4}

- **primary affinity**: با `ceph osd primary-affinity <osd> <weight>` می‌توان احتمال primary شدن OSDهای کند را کم کرد تا خواندن‌ها بیشتر از OSDهای سریع سرویس شوند (در pool تکثیری با OSDهای ترکیبی).
- **read balancer** (از Reef): توزیع primaryها برای متوازن کردن بار خواندن؛ صفحه‌ی Read Balancer در مستندات.
- **کش سمت کلاینت**: کش librbd، کش persistent write-back در librbd (PWL) و fscache برای CephFS هسته.

| نیاز | راه پیشنهادی امروز |
|---|---|
| VMهای حساس به تأخیر | pool تکثیری روی nvme با device class |
| بایگانی و پشتیبان | pool EC روی hdd، RBD با --data-pool |
| OSD HDD با بار ترکیبی | block.db/WAL روی NVMe |
| داده‌ی شیء با عمر مشخص | storage class و lifecycle در RGW |
| بایگانی خارج از کلاستر | cloud transition در RGW |

::: {.summary title="نکات SRE این فصل"}

- cache tier جدید نسازید؛ از Reef منسوخ است و ممکن است بدون اطلاع حذف شود.
- پیش از ارتقای کلاستر دارای cache tier، مهاجرت را کامل کنید.
- برای حذف tier writeback: proxy، flush-evict-all، remove-overlay، remove.
- لایه‌بندی را در سطح pool و برنامه انجام دهید؛ رفتار قابل پیش‌بینی است.
- برای OSDهای HDD، block.db روی NVMe بزرگ‌ترین بهبود ارزان است.

:::

# تکمیلی و به‌روز {#sec-16-8}

- از ۲۰۱۹ تاکنون، مهم‌ترین تغییر این حوزه منسوخ شدن cache tiering در Reef است؛ مستندات latest همچنان این هشدار را دارد.
- overwrite در pool EC از Luminous و FastEC در Tentacle، دلیل اصلی تاریخی cache tier جلوی pool EC را از میان برده است.
- RGW storage class، lifecycle و cloud transition مسیر رسمی لایه‌بندی شیء هستند.
- کد عامل کش (`agent_*` در `PrimaryLogPG.cc` و `TierAgentState.h`) هنوز در شاخه‌ی main وجود دارد، اما بدون نگه‌دارنده است.

# تمرین عملی {#sec-16-9}

1. در کلاستر آزمایشی یک cache tier writeback بسازید، با `rados bench` بار تصادفی بدهید و تأخیر را با pool بدون کش مقایسه کنید.
2. `target_max_bytes` را کوچک بگذارید و انتقال حالت flush و evict را در log OSD (سطح ۲۰) دنبال کنید.
3. روال حذف tier را کامل اجرا کنید و تأیید کنید هیچ شیئی از دست نرفته است.
4. دو قانون CRUSH با device class بسازید و یک pool را با تغییر crush_rule بین لایه‌ها جابه‌جا کنید.
5. یک storage class COLD در RGW بسازید و با lifecycle یک روزه انتقال را آزمایش کنید (برای آزمایش، `rgw_lc_debug_interval` را در محیط آزمایشی تنظیم کنید).
6. `agent_choose_mode` را در کد بخوانید و برای یک pool با ۱۲۸ PG و target_max_bytes یک ترابایت، سهم هر PG را حساب کنید.

# پرسش‌های مرور {#sec-16-10}

1. وضعیت رسمی cache tiering در نسخه‌های جاری چیست؟
2. overlay چگونه درخواست کلاینت را به pool کش می‌برد؟
3. HitSet نوع bloom چه مزیتی دارد و min_read_recency_for_promote چه می‌کند؟
4. چرا cache tiering برای بیشتر بارهای RBD کارایی را کاهش می‌داد؟
5. عامل کش چگونه هدف کل pool را به سهم هر PG تبدیل می‌کند؟
6. نقش osd_agent_slop چیست؟
7. evict در حالت SOME چگونه قربانی را انتخاب می‌کند؟
8. مراحل حذف یک cache tier writeback را بنویسید.
9. چه چیزی دلیل تاریخی cache tier جلوی pool EC را از بین برد؟
10. برای داده‌ی شیء با عمر مشخص چه جایگزینی پیشنهاد می‌شود؟

# منابع این فصل {#sec-16-11}

- Cache Tiering (deprecation notice): https://docs.ceph.com/en/latest/rados/operations/cache-tiering/
- CRUSH maps and device classes: https://docs.ceph.com/en/latest/rados/operations/crush-map/
- Read balancer: https://docs.ceph.com/en/latest/rados/operations/read-balancer/
- RGW placement and storage classes: https://docs.ceph.com/en/latest/radosgw/placement/
- RGW cloud transition: https://docs.ceph.com/en/latest/radosgw/cloud-transition/
- Erasure code (overwrites): https://docs.ceph.com/en/latest/rados/operations/erasure-code/
- Source: src/osd/PrimaryLogPG.cc (agent_*, hit_set_*): https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- Source: src/osd/TierAgentState.h: https://github.com/ceph/ceph/blob/main/src/osd/TierAgentState.h
- Source: src/osd/HitSet.h: https://github.com/ceph/ceph/blob/main/src/osd/HitSet.h
- ceph-devel (2017-11), «About the "temperature histogram" of tier-agent»: https://www.spinics.net/lists/ceph-devel/msg39274.html
