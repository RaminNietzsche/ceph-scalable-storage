---
chapter: 30
id: ch30
title: "لایه‌های پایینی (۸): Crimson و Seastar، OSD تک‌هسته‌ای و SeaStore"
part: lower
lang: fa
---

# مقدمه: چرا یک OSD تازه؟ {#sec-30-1}

OSD کلاسیک (فصل‌های ۱۲، ۲۱ و ۲۲) در دوره‌ای طراحی شد که دیسک چرخان چند میلی‌ثانیه تأخیر داشت و چند ده میکروثانیه هزینه‌ی نرم‌افزار در برابر آن ناچیز بود. روی NVMe امروزی، یک خواندن 4K در حدود ۱۰ تا ۸۰ میکروثانیه تمام می‌شود. در همین مدت، OSD کلاسیک پیام را از یک thread شبکه به صف شارد، از آنجا به thread دیگری با قفل PG و سپس به threadهای kv_sync و finisher در BlueStore می‌سپارد. هر جابه‌جایی بین threadها هزینه‌ی context switch، از دست رفتن cache پردازنده و رقابت قفل دارد. **Crimson** بازنویسی OSD روی چارچوب **Seastar** است تا این هزینه‌ها حذف شوند: هر هسته‌ی پردازنده یک reactor دارد و هر PG فقط روی یک هسته زندگی می‌کند.

::: {.note}
**وضعیت.** طبق مستند رسمی (`doc/crimson/crimson.rst` در شاخه‌ی main و `doc/dev/crimson/crimson.rst` در Squid و Tentacle)، Crimson در مرحله‌ی **tech preview** است و **برای production مناسب نیست**. فعال کردن آن به سه پرچم نیاز دارد: ویژگی آزمایشی `crimson` در `enable_experimental_unrecoverable_data_corrupting_features`، پرچم OSDMap با `ceph osd set-allow-crimson --yes-i-really-mean-it` و ساخت poolها با پرچم crimson (`osd_pool_default_crimson`). Crimson فقط PGهای poolهای crimson را می‌سازد. همه‌ی مطالب این فصل برای فهم معماری است، نه توصیه‌ی استقرار.
:::

![مقایسه‌ی مدل اجرای OSD کلاسیک و Crimson. در OSD کلاسیک هر درخواست از چند thread pool و چند قفل عبور می‌کند. در Crimson هر هسته یک reactor مستقل دارد که هم شبکه و هم PGهای خودش را اجرا می‌کند. ارتباط بین هسته‌ها فقط با پیام صریح (submit_to و invoke_on) است و نتیجه به‌صورت future به هسته‌ی مبدأ برمی‌گردد](figures/ch30/f01_threads.png){#fig-30-f01_threads}

این شکل تفاوت بنیادی دو مدل را نشان می‌دهد. در ردیف بالا، یک درخواست دست‌کم چهار بار بین threadها جابه‌جا می‌شود و در هر جابه‌جایی داده‌ی آن باید از cache هسته‌ی دیگری خوانده شود. در ردیف میانی، داده‌ی یک PG (log، object context، cache) فقط در حافظه‌ی یک هسته است و هیچ قفلی لازم نیست، چون هیچ هسته‌ی دیگری به آن دست نمی‌زند. بهای این سادگی آن است که هر تعامل بین هسته‌ها باید صریح باشد، مثل پیامی که به هسته‌ی 0 برای پیدا کردن هسته‌ی صاحب PG فرستاده می‌شود.

# Seastar: future، continuation و reactor {#sec-30-2}

در Seastar هیچ تابعی بلوکه نمی‌شود. تابعی که کار ناهم‌گام دارد (خواندن از شبکه، نوشتن روی دیسک، پرسش از هسته‌ی دیگر) بی‌درنگ یک `future<T>` برمی‌گرداند. ادامه‌ی کار با `.then()` به آن future وصل می‌شود. وقتی نتیجه آماده شد، تولیدکننده با `promise.set_value()` آن را آماده می‌کند و continuation به صف task همان reactor می‌رود. reactor یک حلقه‌ی بی‌پایان روی هر هسته است: taskهای آماده را اجرا می‌کند، backend ورودی و خروجی (io_uring، linux-aio یا epoll، با گزینه‌ی `crimson_reactor_backend`) را poll می‌کند و تایمرها را بررسی می‌کند.

![مسیر یک درخواست روی یک reactor. هیچ مرحله‌ای منتظر نمی‌ماند. هر عمل ناهم‌گام future برمی‌گرداند و continuation پس از آماده شدن نتیجه در صف همان هسته قرار می‌گیرد. چون زمان‌بندی تعاونی است، هر task باید زود تمام شود. Crimson سهم زمانی هر task را با crimson_reactor_task_quota_ms (پیش‌فرض 0.5 میلی‌ثانیه در main) تنظیم می‌کند](figures/ch30/f02_future.png){#fig-30-f02_future}

::: {.algo #alg-30-1 title="زمان‌بندی تعاونی reactor در Seastar" src="seastar: reactor::run (به‌کارگیری در src/crimson/osd/main.cc و گزینه‌های crimson_reactor_*)" complexity="هر دور O(تعداد task آماده + رویدادهای poll)؛ بدون قفل"}
:::

```text
pseudocode: یک دور reactor (مدل مفهومی، بازنویسی این کتاب)
loop forever:
  t0 = now()
  while ready_tasks not empty and now() - t0 < task_quota:   # 0.5ms
      task = ready_tasks.pop_front(); task.run()             # continuation‌ها
  poll(io backend)          # تکمیل io_uring/aio ⇒ promise.set_value ⇒ task جدید
  poll(network)             # داده‌ی socket ⇒ task جدید
  poll(smp queues)          # پیام از هسته‌های دیگر (submit_to)
  run expired timers
  if nothing to do for idle_poll_time (200us): sleep in kernel (مگر poll_mode)
```

**مثال عددی.** فرض کنید هر خواندن 4K روی reactor حدود ۱۵ میکروثانیه CPU مصرف کند (decode، جست‌وجوی object context، ساخت پاسخ). با سهم 0.5 میلی‌ثانیه، در هر دور حدود ۳۳ درخواست اجرا می‌شود و سپس reactor دوباره دستگاه و شبکه را poll می‌کند. پس بیشینه‌ی تأخیر اضافه برای یک تکمیل ورودی و خروجی تازه حدود ۰٫۵ میلی‌ثانیه است. اگر یک continuation بد ۵ میلی‌ثانیه CPU مصرف کند (مثلاً پیمایش یک omap بزرگ بدون تقسیم کار)، همه‌ی PGهای آن هسته ۵ میلی‌ثانیه متوقف می‌شوند. این همان «stall» است که Seastar در log گزارش می‌کند. در مدل تعاونی، کار طولانی باید با `seastar::maybe_yield()` یا حلقه‌های ناهم‌گام تکه‌تکه شود.

::: {.warn}
`crimson_reactor_idle_poll_time_us=200` یعنی reactor پس از ۲۰۰ میکروثانیه بی‌کاری در هسته‌ی سیستم‌عامل می‌خوابد. `crimson_poll_mode=true` این خواب را حذف می‌کند و همیشه polling انجام می‌دهد. در این حالت تأخیر کمتر می‌شود، اما هر reactor یک هسته را صددرصد مشغول نگه می‌دارد، حتی بدون بار. داشبوردی که `osd_reactor_utilization` را نشان می‌دهد در حالت poll همیشه نزدیک ۱۰۰ است و دیگر نشانه‌ی اشباع نیست.
:::

## shared-nothing در عمل {#sec-30-2-1}

داده‌ای که بین هسته‌ها مشترک است فقط از سه راه جابه‌جا می‌شود: `seastar::smp::submit_to(core, func)` یک تابع را روی هسته‌ی دیگر اجرا می‌کند و future نتیجه را برمی‌گرداند. `sharded<T>` یک نمونه از سرویس را روی هر هسته نگه می‌دارد و `invoke_on` و `invoke_on_all` آن را فرا می‌خوانند. `foreign_ptr` هم مالکیت شیئی را که روی هسته‌ی دیگر ساخته شده است منتقل می‌کند تا آزادسازی آن روی همان هسته‌ی سازنده انجام شود. در Crimson، `PGShardMapping` یک `peering_sharded_service` است. یعنی هر هسته یک کپی محلی از نقشه‌ی PG به هسته دارد، ولی فقط هسته‌ی 0 آن را تغییر می‌دهد.

# الگوریتم نگاشت PG به هسته {#sec-30-3}

::: {.algo #alg-30-2 title="انتخاب کم‌بارترین هسته برای PG تازه" src="src/crimson/osd/pg_map.cc :: PGShardMapping::get_or_create_pg_mapping" complexity="جست‌وجو O(log P) با std::map؛ انتخاب O(C) روی C هسته؛ یک رفت‌وبرگشت به هسته‌ی 0"}
:::

![نگاشت PG به هسته در Crimson. اگر هسته‌ای PG را در نقشه‌ی محلی نیابد، از هسته‌ی 0 می‌پرسد. هسته‌ی 0 برای PG تازه کم‌بارترین هسته را با min_element روی شمار PGهای هر هسته انتخاب، شمارنده را افزایش و نقشه را به همه‌ی هسته‌ها پخش می‌کند. از آن پس همه‌ی کارهای آن PG فقط روی همان هسته اجرا می‌شود](figures/ch30/f03_pgmap.png){#fig-30-f03_pgmap}

```text
pseudocode: get_or_create_pg_mapping (خلاصه‌ی منطق کد)
on any core:
  if pgid in local.pg_to_core: return local.pg_to_core[pgid]
  return invoke_on(core 0):
     if pgid in primary.pg_to_core: core = that core
     else:
        core = argmin_c primary.core_to_num_pgs[c]    # کم‌بارترین هسته
        primary.core_to_num_pgs[core] += 1
        store_index = pick least-loaded store shard on core (اگر چند shard ذخیره‌ساز)
        primary.pg_to_core[pgid] = (core, store_index)
     broadcast mapping to all cores; return (core, store_index)
```

**مثال عددی.** OSD با `crimson_cpu_num=4` و هسته‌های 0 تا 3 را در نظر بگیرید که به‌ترتیب 30، 29، 31 و 29 PG دارند. PG تازه‌ی 2.1f وارد می‌شود. min_element **اولین** کمینه را برمی‌گرداند، پس هسته‌ی 1 انتخاب می‌شود (نه 3) و شمارش‌ها 30، 30، 31 و 29 می‌شوند. PG بعدی به هسته‌ی 3 می‌رود. این روش فقط **تعداد** PG را متوازن می‌کند، نه بار آن‌ها را. اگر دو PG داغ RBD روی یک هسته بیفتند، آن هسته اشباع می‌شود و هسته‌های دیگر بی‌کار می‌مانند، چون در مدل shared-nothing هیچ work-stealing وجود ندارد. این یکی از تفاوت‌های عملی مهم با OSD کلاسیک است که threadهای هر شارد بین PGهای متعدد آن شارد مشترک‌اند.

::: {.deep}
نگاشت تا پایان عمر PG روی OSD ثابت است و با `ceph tell osd.N dump_store_shards` قابل مشاهده است (تابع `dump_store_shards` در همان فایل). اگر تعداد shardهای ذخیره‌ساز (مثلاً SeaStore) با تعداد reactorها برابر نباشد، کد یک لایه‌ی دوم از انتخاب کم‌بارترین (روی `core_alien_to_num_pgs` یا `core_shard_to_num_pgs`) اضافه می‌کند. گزینه‌ی `seastore_require_partition_count_match_reactor_count` این حالت را محدود می‌کند.
:::

# pipeline عملیات {#sec-30-4}

در OSD کلاسیک، ترتیب درخواست‌های یک PG با قفل PG و صف شارد حفظ می‌شود. Crimson به‌جای قفل از **phaseها** استفاده می‌کند (`src/crimson/osd/osd_operation.h`). هر phase یا **OrderedExclusive** است، یعنی در هر لحظه فقط یک عملیات در آن است و ترتیب ورود حفظ می‌شود، یا **OrderedConcurrent**، یعنی چند عملیات هم‌زمان در آن هستند ولی به همان ترتیب خارج می‌شوند.

![phaseهای یک ClientRequest در Crimson. سطح اتصال (منتظر فعال شدن، دریافت نقشه و یافتن هسته‌ی PG)، سطح شارد (ساختن یا انتظار برای PG)، سطح PG (آماده بودن PG، gate نسخه‌ی OSDMap، فعال بودن PG و گرفتن object context) و سطح شیء (پردازش، انتظار برای scrub، انتظار برای تکرار در replicaها و ارسال پاسخ). phaseهای exclusive ترتیب را تضمین می‌کنند و concurrentها هم‌پوشانی را ممکن می‌کنند](figures/ch30/f04_pipeline.png){#fig-30-f04_pipeline}

| phase | نوع | چه چیزی را تضمین می‌کند |
|---|---|---|
| ConnectionPipeline::AwaitActive / AwaitMap / GetPGMapping | exclusive | ترتیب پیام‌های یک اتصال تا رسیدن به هسته‌ی PG |
| PerShardPipeline::CreateOrWaitPG | exclusive | ساخت PG فقط یک بار |
| CommonPGPipeline::WaitPGReady | concurrent | انتظار برای آماده شدن PG بدون ترتیب‌شکنی |
| CommonPGPipeline::GetOBC | exclusive | ترتیب گرفتن object context (معادل قفل شیء) |
| CommonOBCPipeline::Process | exclusive | اجرای opها روی شیء به ترتیب ورود |
| CommonOBCPipeline::WaitRepop | concurrent | چند نوشتن هم‌زمان منتظر ack از replicaها |
| CommonOBCPipeline::SendReply | exclusive | پاسخ‌ها به ترتیب درخواست‌ها |

**استدلال تأخیر.** چون WaitRepop هم‌زمان است، ۳۲ نوشتن متوالی روی یک شیء می‌توانند هم‌زمان منتظر replicaها باشند. اگر رفت‌وبرگشت تا replica 200 میکروثانیه و پردازش هر نوشتن 20 میکروثانیه باشد، گذردهی یک شیء حدود 1/20µs=50K نوشتن در ثانیه است، نه 1/220µs. اگر Process بلوکه شود (مثلاً منتظر خواندن object context از دیسک)، کل صف شیء پشت آن می‌ماند. به همین دلیل `crimson_osd_obc_lru_size=512` (اندازه‌ی cache مربوط به object context) برای بار تصادفی اهمیت زیادی دارد.

# پشتیبان‌های ذخیره‌سازی در Crimson {#sec-30-5}

رابط ذخیره‌سازی Crimson `FuturizedStore` است (`src/crimson/os/futurized_store.h`). هر عمل به‌جای مقدار، future برمی‌گرداند. سه پیاده‌سازی در `src/crimson/os/` وجود دارد:

![پشتیبان‌های ذخیره‌سازی Crimson. SeaStore و CyanStore بومی‌اند و مستقیماً روی reactor اجرا می‌شوند. AlienStore، BlueStore یا MemStore کلاسیک را در threadهای «بیگانه» (خارج از Seastar) اجرا می‌کند. درخواست از reactor به thread pool فرستاده می‌شود و نتیجه با seastar::alien::submit_to به هسته‌ی مبدأ برمی‌گردد](figures/ch30/f05_backends.png){#fig-30-f05_backends}

| پشتیبان | اجرا | کاربرد | وضعیت (مستند main) |
|---|---|---|---|
| SeaStore | بومی، روی reactor | طراحی تازه برای NVMe | «اولیه»، پیش‌فرض نیست |
| CyanStore | بومی، در حافظه | سنجش سربار خود OSD؛ **داده ذخیره نمی‌کند** | فقط آزمایش |
| AlienStore + BlueStore | thread pool بیگانه | پیش‌فرض؛ سازگار با HDD و SSD | پیش‌فرض در Crimson |
| AlienStore + MemStore | thread pool بیگانه | آزمایش و توسعه | فقط آزمایش |

در `alien_store.cc`، thread pool با `crimson_bluestore_num_threads` (پیش‌فرض 6 در main) ساخته می‌شود. عملیات یک collection با `ch->get_cid().hash_to_shard(tp->size())` همیشه به یک thread مشخص می‌رود تا ترتیب تراکنش‌های یک PG حفظ شود. این همان نقشی است که در OSD کلاسیک صف شارد ایفا می‌کند.

::: {.warn}
**هزینه‌ی پنهان AlienStore.** هر عمل دو بار مرز reactor و thread را می‌گذراند (رفت به pool و برگشت با alien::submit_to). روی NVMe سریع، این دو انتقال و کار BlueStore در threadهای خودش بخش بزرگی از سود Crimson را از بین می‌برند. به همین دلیل مستند توصیه می‌کند مجموعه‌ی CPU مربوط به BlueStore (`crimson_bluestore_cpu_set`) از هسته‌های reactor (`crimson_cpu_set`) جدا باشد تا threadهای بیگانه با reactorها رقابت نکنند.
:::

# SeaStore: معماری {#sec-30-6}

SeaStore یک ObjectStore **log-structured** و تراکنشی است. هیچ داده‌ای در جای قبلی بازنویسی نمی‌شود، مگر در backend مربوط به random block (RBM). هر تراکنش به یک **record** در journal تبدیل می‌شود که deltaها (تغییرات منطقی روی بلوک‌ها) و بلوک‌های تازه را در بر دارد.

![لایه‌های SeaStore. مدیرهای منطقی (onode با درخت FLTree، omap و xattr با BTree، داده‌ی شیء و collectionها) روی آدرس منطقی laddr کار می‌کنند. TransactionManager تغییرات را در یک Transaction جمع و به‌صورت یک record اتمیک ثبت می‌کند. LBAManager نگاشت laddr به paddr را در یک B-tree نگه می‌دارد و BackrefManager نگاشت معکوس را برای GC. Journal، ExtentPlacementManager، Cache و AsyncCleaner روی دستگاه‌های segmented، RBM یا ZBD کار می‌کنند](figures/ch30/f06_seastore.png){#fig-30-f06_seastore}

دو نوع آدرس در SeaStore وجود دارد. **laddr** آدرس منطقی است که onodeها و درخت‌های omap به آن اشاره می‌کنند و با جابه‌جایی بلوک در GC تغییر نمی‌کند. **paddr** آدرس فیزیکی است. تنها ساختاری که باید با جابه‌جایی بلوک به‌روز شود LBA tree است. این طراحی هزینه‌ی GC را محدود می‌کند: جابه‌جا کردن یک بلوک داده فقط یک ورودی برگ در LBA tree را عوض می‌کند، نه همه‌ی اشاره‌گرهای به آن.

## paddr_t بیت به بیت {#sec-30-6-1}

![ساختار ۶۴ بیتی paddr_t در seastore_types.h. هشت بیت بالایی device_id است (DEVICE_ID_BITS = digits(uint8_t) = 8). در دستگاه segmented، ۲۴ بیت بعدی شماره‌ی segment درون دستگاه و ۳۲ بیت پایینی آفست درون segment است. در RBM، ۵۶ بیت پایینی آفست مطلق است. هفت مقدار بالای device_id برای آدرس‌های نمادین مثل آفست نسبی درون record یا آدرس تأخیری رزرو شده‌اند](figures/ch30/f07_paddr.png){#fig-30-f07_paddr}

آدرس‌های **نسبی** (`DEVICE_ID_RECORD_RELATIVE` و `DEVICE_ID_BLOCK_RELATIVE`) نکته‌ی ظریفی دارند. وقتی تراکنشی ساخته می‌شود، هنوز معلوم نیست record آن در کجای journal قرار می‌گیرد. پس بلوک‌های تازه با آفست نسبی به ابتدای record نام‌گذاری می‌شوند و هنگام نوشتن record، این آدرس‌ها به paddr مطلق تبدیل می‌شوند. `DEVICE_ID_DELAYED` برای بلوک‌هایی است که جای آن‌ها تا لحظه‌ی ثبت با ExtentPlacementManager تعیین نشده است (نوشتن out-of-line).

## record و دسته‌بندی در journal {#sec-30-6-2}

![ساختار سگمنت journal و record group. هر record group با یک نوشتن روی دیسک ثبت می‌شود و شامل record_group_header_t (تعداد recordها، طول فراداده و داده، nonce سگمنت، committed_to و crc داده)، سپس header هر record (نوع تراکنش، شمار delta و extent، زمان تغییر)، deltaها و extentهای inline است. RecordSubmitter تا 16 record را در یک batch جمع و حداکثر 5 نوشتن هم‌زمان روی journal نگه می‌دارد (پیش‌فرض‌های main)](figures/ch30/f09_record.png){#fig-30-f09_record}

::: {.algo #alg-30-3 title="دسته‌بندی recordها در RecordSubmitter" src="src/crimson/os/seastore/journal/record_submitter.cc :: RecordSubmitter::submit / flush_current_batch" complexity="هر record O(اندازه) برای کدگذاری؛ تأخیر در بدترین حالت یک batch"}
:::

```text
pseudocode: دسته‌بندی journal (مدل مفهومی)
submit(record):
  if current_batch can fit record and batch.size < batch_capacity(16):
      current_batch.add(record)
  else: flush_current_batch(); current_batch.add(record)
  if outstanding_ios < iodepth_limit(5): flush_current_batch()      # دیسک بی‌کار است: صبر نکن
  else: wait (batch بزرگ‌تر می‌شود تا یکی از نوشتن‌ها تمام شود)
flush_current_batch():
  header = record_group_header_t{records=n, mdlength, dlength, segment_nonce,
                                 committed_to = آخرین نقطه‌ای که همه‌ی قبلی‌ها کامل‌اند,
                                 data_crc = crc(data)}
  write(header + metadata + data) as ONE aligned I/O
```

**مثال عددی.** فرض کنید ۴۰ تراکنش کوچک (هرکدام یک delta روی onode و 4K داده) هم‌زمان می‌رسند و دیسک هر نوشتن را در ۲۰ میکروثانیه کامل می‌کند. پنج record اول هرکدام به یک نوشتن جدا تبدیل می‌شوند، چون صف دیسک خالی است. پس از رسیدن به سقف ۵ نوشتن هم‌زمان، بقیه تا ۱۶ عدد در یک batch جمع می‌شوند. ۳۵ record باقی‌مانده در ۳ نوشتن (16+16+3) ثبت می‌شوند. در مجموع ۸ نوشتن به‌جای ۴۰ انجام می‌شود و بیشترین تأخیر اضافه‌ی هر record کمتر از دو بار زمان یک نوشتن است. این همان مصالحه‌ی group commit در `kv_sync_thread` در BlueStore است، با این تفاوت که بدون thread جداگانه و فقط با futureها پیاده شده است.

::: {.note}
**وابسته به نسخه.** در Squid، `seastore_max_concurrent_transactions` برابر 8 و در main برابر 128 است. نام گزینه‌ها هم تغییر کرده است: Squid و Tentacle از `crimson_seastar_num_threads` و `crimson_alien_op_num_threads` استفاده می‌کنند و main از `crimson_cpu_num` و `crimson_bluestore_num_threads`. cache در Squid با `seastore_cache_lru_size=64M` تنظیم می‌شد و در main با `seastore_cachepin_size_pershard=2G` و انتخاب LRU یا 2Q. پیش از هر آزمایش، `ceph config help` را روی نسخه‌ی خود اجرا کنید.
:::

## حالت‌های یک extent در cache {#sec-30-6-3}

![ماشین حالت extentها در Cache مربوط به SeaStore. extent تازه در INITIAL_WRITE_PENDING ساخته و پس از commit تمیز (CLEAN) می‌شود. تغییر یک extent موجود نسخه‌ای در MUTATION_PENDING می‌سازد که پس از commit با ثبت delta در journal، DIRTY می‌شود (محتوای حافظه با دیسک متفاوت و pinned در حافظه). extentهایی که فراداده‌شان هنوز ثبت نشده EXIST_CLEAN و EXIST_MUTATION_PENDING هستند. DIRTYها با بازنویسی توسط cleaner یا trim مربوط به journal دوباره CLEAN می‌شوند](figures/ch30/f08_extstate.png){#fig-30-f08_extstate}

نکته‌ی مهم این ماشین حالت **کنترل هم‌روندی خوش‌بینانه** است. هر تراکنش extentهایی را که خوانده در `read_set` نگه می‌دارد. اگر تراکنش دیگری پیش از commit یکی از آن‌ها را تغییر دهد، `Cache::mark_transaction_conflicted` تراکنش اول را نامعتبر می‌کند و تراکنش باید از نو اجرا شود. مستند SeaStore یادآوری می‌کند که این سازوکار در بارهای نوشتن سنگین نرخ تکرار بالایی دارد و برای حذف آن برنامه‌ریزی شده است. این یکی از دلایل وضعیت «اولیه»ی SeaStore است.

# GC سگمنت‌ها: انتخاب سگمنت قربانی {#sec-30-7}

در دستگاه segmented، هر بایتی که نوشته می‌شود در نهایت باید با «تمیز کردن» یک سگمنت قدیمی جبران شود: داده‌ی زنده‌ی آن سگمنت به سگمنت تازه منتقل و سگمنت آزاد می‌شود. پرسش کلیدی این است که کدام سگمنت انتخاب شود.

::: {.algo #alg-30-4 title="انتخاب سگمنت برای بازیابی (greedy / cost-benefit / benefit)" src="src/crimson/os/seastore/async_cleaner.cc :: SegmentCleaner::calc_gc_benefit_cost و get_next_reclaim_segment" complexity="O(S) روی S سگمنت بسته در هر انتخاب"}
:::

```text
pseudocode: get_next_reclaim_segment (خلاصه)
for each closed segment s:
   u = live_bytes(s) / segment_size                      # 0 ≤ u < 1
   score(s) = greedy:       1 - u
              cost_benefit: (1 - u) × age(s) / (2u)        # u=0 ⇒ +∞
              benefit:      ترکیب (1-u) با عامل سن نرمال‌شده
pick = argmax score;  greedy_pick = argmin u
if autotune and formula ≠ greedy and (1-u_greedy) ≥ ratio(2.0) × (1-u_pick):
   pick = greedy_pick                                     # فرمول سن‌محور اشتباه کرده است
```

فرمول cost-benefit همان فرمول کلاسیک سامانه‌های فایل log-structured (LFS) است. سود پاک کردن سگمنت متناسب با فضای آزادشده (1-u) و «پایداری» آن (سن) است و هزینه‌اش خواندن u و نوشتن u (یعنی 2u). سگمنت قدیمی با داده‌ی کم‌زنده بهترین گزینه است، چون داده‌ی باقی‌مانده‌اش احتمالاً «سرد» است و دوباره به این زودی نمی‌میرد.

**مثال عددی.** سه سگمنت بسته داریم:

| سگمنت | u (سهم زنده) | سن (ثانیه) | greedy = 1-u | cost-benefit = $(1-u) \cdot \mathit{age} / (2u)$ |
|---|---|---|---|---|
| A | 0.2 | 100 | **0.8** | 200 |
| B | 0.5 | 1000 | 0.5 | 500 |
| C | 0.9 | 10000 | 0.1 | **555.6** |

فرمول cost-benefit سگمنت C را انتخاب می‌کند، چون بسیار قدیمی است. اما پاک کردن C فقط 10٪ فضای آزاد به دست می‌دهد و باید 90٪ آن را جابه‌جا کرد. autotune این را بررسی می‌کند: سهم آزاد greedy (0.8) دست‌کم 2 برابر سهم آزاد انتخاب فرمول (0.1) است، پس انتخاب به A برمی‌گردد. اگر C در کار نبود، فرمول B را با امتیاز 500 انتخاب می‌کرد. نسبت 0.8/0.5=1.6 کمتر از 2 است، پس انتخاب فرمول حفظ می‌شد. این گزینه‌ها (`seastore_segment_cleaner_gc_formula=cost_benefit`، `seastore_segment_cleaner_gc_autotune=true` و `ratio=2.0`) در main هستند و در yaml مربوط به Squid و Tentacle دیده نمی‌شوند.

**استدلال write amplification.** اگر cleaner در حالت پایدار سگمنت‌هایی با میانگین u=0.5 را پاک کند، برای هر ۱ بایت آزادشده ۱ بایت بازنویسی لازم است و WA حدود 2 است. با u=0.2، برای هر 0.8 بایت آزاد 0.2 بایت جابه‌جا می‌شود و WA حدود 1.25 است. پس رزرو فضای آزاد بیشتر روی دستگاه، u سگمنت‌های قربانی را پایین می‌آورد و هم عمر NVMe و هم تأخیر نوشتن را بهتر می‌کند.

# سنجش و پایش Crimson {#sec-30-8}

```bash {since=main}
ceph tell osd.0 dump_metrics reactor_utilization     # بهره‌وری هر reactor (shard)
ceph tell osd.0 dump_store_shards                    # نگاشت PGها و store shardها به هسته‌ها
ceph config set osd crimson_prometheus_port_base 29180   # main: osd.N روی 29180+N
curl -s http://HOST:29180/metrics | grep osd_reactor_utilization
ceph osd dump | grep -E 'allow_crimson|crimson'          # پرچم‌های نقشه و pool
```

::: {.debug}
اگر یک reactor نزدیک ۱۰۰٪ و بقیه کم‌کار باشند، (۱) poll_mode را بررسی کنید، (۲) با `dump_store_shards` ببینید کدام PGها روی آن هسته‌اند و (۳) بار هر PG را با `ceph pg dump pgs` مقایسه کنید. در Crimson راه‌حل، توزیع PGها (افزایش pg_num یا upmap) است، نه افزایش thread.
:::

# تکمیلی و به‌روز {#sec-30-9}

- در شاخه‌ی main، مستند کاربری Crimson از `doc/dev/crimson/` به `doc/crimson/crimson.rst` منتقل شده و استقرار با `ceph orch apply osd --osd-type crimson` و برای SeaStore با `--objectstore seastore` شرح داده شده است. در Squid و Tentacle این فرمان‌ها در مستند نیستند.
- `crimson_cpu_num` پیش‌فرض ندارد و پس از استقرار تغییرپذیر نیست. مستند توصیه می‌کند آن را کمتر از nproc تقسیم بر تعداد OSDهای میزبان بگذارید.
- io_uring backend پیش‌فرض reactor است، اگر هسته اجازه دهد (`kernel.io_uring_disabled`). در برخی توزیع‌های محافظه‌کار باید آن را صریحاً فعال کرد.
- SeaStore برای HDD مناسب نیست (طبق مستند). Crimson برای HDD و SSDهای کند همچنان BlueStore را از راه AlienStore پشتیبانی می‌کند.

# تمرین عملی {#sec-30-10}

1. با vstart (`MDS=0 MON=1 OSD=1 ../src/vstart.sh -n --crimson --crimson-smp 2`) یک خوشه‌ی Crimson بسازید. `dump_metrics reactor_utilization` را پیش و پس از `rados bench` مقایسه کنید.
2. CyanStore را با AlienStore+BlueStore با یک بار 4K تصادفی مقایسه کنید. تفاوت تأخیر، هزینه‌ی ذخیره‌ساز است و تأخیر CyanStore سربار خود OSD.
3. با چهار PG در pool و دو reactor، با `dump_store_shards` نگاشت را ببینید و آن را با مثال این فصل مقایسه کنید.
4. سه سگمنت فرضی با u و سن دلخواه بسازید و امتیاز greedy و cost-benefit و نتیجه‌ی autotune را دستی حساب کنید.

# پرسش‌های مرور {#sec-30-11}

1. چرا مدل thread pool در OSD کلاسیک روی NVMe هزینه‌بر است؟
2. future و continuation در Seastar چگونه جایگزین بلوکه شدن می‌شوند؟
3. crimson_reactor_task_quota_ms چه چیزی را محدود می‌کند و یک continuation طولانی چه اثری دارد؟
4. PG تازه چگونه به یک هسته نسبت داده می‌شود و این روش چه ضعفی دارد؟
5. تفاوت phaseهای exclusive و concurrent را با مثال WaitRepop توضیح دهید.
6. AlienStore چرا لازم است و چه هزینه‌ای دارد؟
7. laddr و paddr در SeaStore چه تفاوتی دارند و چرا این جداسازی هزینه‌ی GC را کم می‌کند؟
8. ساختار ۶۴ بیتی paddr_t را برای segment و RBM شرح دهید.
9. فرمول cost-benefit را بنویسید و autotune را با مثال توضیح دهید.
10. سه پرچمی که برای فعال کردن Crimson لازم‌اند کدام‌اند؟

# منابع این فصل {#sec-30-12}

- Crimson در مستندات (main): https://github.com/ceph/ceph/blob/main/doc/crimson/crimson.rst
- راهنمای توسعه‌دهنده‌ی Crimson: https://github.com/ceph/ceph/blob/main/doc/dev/crimson/index.rst
- طراحی SeaStore: https://github.com/ceph/ceph/blob/main/doc/dev/crimson/seastore.rst
- کد Crimson: https://github.com/ceph/ceph/tree/main/src/crimson
- گزینه‌های Crimson: https://github.com/ceph/ceph/blob/main/src/common/options/crimson.yaml.in
- Seastar: https://seastar.io/
- آموزش Seastar: https://github.com/scylladb/seastar/blob/master/doc/tutorial.md
- پروژه‌ی Crimson در وبلاگ Ceph: https://ceph.io/en/news/crimson/
- Rosenblum و Ousterhout، The Design and Implementation of a Log-Structured File System (1992): https://people.eecs.berkeley.edu/~brewer/cs262/LFS.pdf
