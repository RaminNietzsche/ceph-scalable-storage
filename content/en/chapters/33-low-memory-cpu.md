---
chapter: 33
id: ch33
title: 'Lower Layers (11): Memory and CPU Inside the OSD — from mempool to NUMA and Profiling'
part: lower
lang: en
translation: pending
---

# چرا حافظه و CPU؟ {#sec-33-1}

بیشتر شکایت‌های کارایی از یک OSD در نهایت به یکی از این دو بازمی‌گردد: یا OSD بیش از سهم خود حافظه مصرف می‌کند (و OOM killer آن را می‌کشد)، یا یک thread یا یک shard اشباع شده است در حالی که بقیه بی‌کارند. این فصل سازوکارهای درونی هر دو را تابع به تابع بررسی می‌کند: **mempool** برای حساب‌داری حافظه، **tcmalloc** به‌عنوان تخصیص‌دهنده، **PriorityCache** برای تقسیم بودجه‌ی حافظه میان cacheها، **threadهای OSD** و توزیع کار میان آن‌ها، **NUMA**، و ابزارهای اندازه‌گیری (perf، bpftrace و uftrace). همه‌ی ارجاع‌ها به main است.

# threadهای یک OSD کلاسیک {#sec-33-2}

![مهم‌ترین threadهای ceph-osd با نامی که در top -H یا perf دیده می‌شود. msgr-worker-N (از Stack.h) پیام‌ها را می‌خوانند و رمزگشایی می‌کنند. tp_osd_tp (thread pool مربوط به OSD::osd_op_tp) opها را از ShardedOpWQ اجرا می‌کند. bstore_aio تکمیل I/O را از هسته می‌گیرد. bstore_kv_sync تراکنش‌ها را دسته‌ای در RocksDB ثبت می‌کند. bstore_kv_final و cfin callbackها را اجرا می‌کنند. bstore_mempool حافظه را تنظیم می‌کند، rocksdb:low/high فشرده‌سازی و flush انجام می‌دهند و osd_srv_heartbt ضربان را می‌فرستد](figures/ch33/f01_threads.png){#fig-33-f01_threads}

| نام thread | سازنده در کد | تعداد پیش‌فرض | نکته |
|---|---|---|---|
| msgr-worker-N | msg/async/Stack.h | ms_async_op_threads=3 | برای هر messenger (public و cluster) جدا |
| tp_osd_tp | OSD.cc: osd_op_tp | shards × threads_per_shard: SSD 8×2=16، HDD 1×5=5 (از v19.2.1) | timeout 15 ثانیه و suicide 150 ثانیه |
| bstore_aio | blk/kernel/KernelDevice.cc | یکی برای هر دستگاه | در مسیر SPDK نیست (فصل ۳۱) |
| bstore_kv_sync | BlueStore.cc | 1 | گلوگاه رایج در نوشتن‌های کوچک |
| bstore_kv_final | BlueStore.cc | 1 | اجرای on_commit |
| cfin | BlueStore.cc: commit_finisher | 1 | finisher مربوط به commit |
| bstore_mempool | BlueStore.h: MempoolThread | 1 | tune_memory هر 1 ثانیه، balance هر 5 ثانیه |
| osd_srv_heartbt | OSD.cc | 1 | heartbeat هر osd_heartbeat_interval=6 ثانیه |
| safe_timer | common/Timer.cc | چند عدد | tickهای OSD و mgr client |

## توزیع op میان shardها {#sec-33-2-1}

`OSD::enqueue_op` برای هر op شاخص shard را با `pgid.hash_to_shard(num_shards)` محاسبه می‌کند. این تابع در `osd_types.h` به‌سادگی `ps() % num_shards` است. همه‌ی opهای یک PG همیشه در یک shard صف می‌شوند و ترتیب آن‌ها حفظ می‌شود. اما توزیع بار میان shardها به پراکندگی ps مربوط به PGهای همان OSD بستگی دارد.

![نمونه‌ای از هم‌نامی (aliasing) در نگاشت PG به shard. PGهایی که ps آن‌ها در پیمانه‌ی 8 برابر است (3، 11، 19، 27) همگی در shard 3 قرار می‌گیرند. اگر این PGها پربار باشند، دو thread مربوط به shard 3 اشباع می‌شوند در حالی که 14 thread دیگر بی‌کارند](figures/ch33/f05_shards.png){#fig-33-f05_shards}

::: {.algo #alg-33-1 title="نگاشت PG به shard صف op" src="src/osd/osd_types.h :: spg_t::hash_to_shard و src/osd/OSD.cc :: OSD::enqueue_op" complexity="O(1)"}
:::

```text
shard_index = pg.ps mod num_shards                 # num_shards = osd_op_num_shards_ssd (8)
sdata = shards[shard_index]
sdata.shard_lock: enqueue(op) با زمان‌بند mClock یا WPQ
thread t از آن shard: dequeue ⇒ قفل PG ⇒ do_op
فقط thread با thread_index < num_shards صف context (oncommit) را هم خالی می‌کند
```

**مثال عددی.** یک OSD در خوشه‌ای با 100 OSD و pool با pg_num=256 و size=3 حدود 256×3/100 ≈ 7.7 PG دارد که حدود 2.6 تای آن‌ها primary است. با 8 shard، احتمال اینکه دو PG primary به یک shard بیفتند بالاست (مسئله‌ی روز تولد: برای سه PG در 8 خانه، 1 − (8×7×6)/8³ ≈ 34٪). وقتی یک PG بخش عمده‌ی بار را دارد (مثلاً یک تصویر RBD پرکار)، **حداکثر** دو thread روی آن کار می‌کنند، چون قفل PG اجرای موازی opهای یک PG را محدود می‌کند. به همین دلیل، افزایش `osd_op_num_threads_per_shard` برای یک PG داغ کمکی نمی‌کند. افزایش pg_num (و در نتیجه تقسیم داده‌ی داغ) راه‌حل واقعی است.

::: {.note}
**وابسته به نسخه.** پیش‌فرض HDD در v19.2.0 پنج shard با یک thread بود و از v19.2.1 یک shard با پنج thread است (فصل ۲۱). گزینه‌های shard فقط هنگام راه‌اندازی OSD خوانده می‌شوند و تغییر آن‌ها راه‌اندازی دوباره می‌خواهد.
:::

# mempool: حساب‌داری بدون قفل {#sec-33-3}

هر ساختار داده‌ی مهم در Ceph با یک allocator مخصوص mempool ساخته می‌شود (مثلاً `mempool::bluestore_cache_onode::map`). این allocator هنگام تخصیص و آزادسازی، شمارنده‌های items و bytes آن pool را به‌روز می‌کند. چالش این است که این به‌روزرسانی در مسیر داغ و از دهها thread هم‌زمان رخ می‌دهد. یک شمارنده‌ی atomic مشترک، cache line را میان هسته‌ها پاس می‌دهد و صدها نانوثانیه هزینه دارد.

![ساختار یک shard_t در mempool.h. هر shard آرایه‌ای از stats_t برای همه‌ی poolهاست و با aligned(128) شروع می‌شود تا دو shard هرگز یک cache line را به اشتراک نگذارند (توضیح کد، ۱۲۸ بایت را بزرگ‌ترین اندازه‌ی cache line در پردازنده‌های شناخته‌شده می‌داند). مقدار کل یک pool جمع همه‌ی shardهاست](figures/ch33/f02_mempool.png){#fig-33-f02_mempool}

::: {.algo #alg-33-2 title="شمارنده‌ی shardشده‌ی mempool" src="src/common/mempool.cc :: get_num_shards، pick_a_shard_int؛ include/mempool.h :: pool_allocator::allocate" complexity="به‌روزرسانی O(1) بدون رقابت؛ خواندن کل O(num_shards)"}
:::

```text
init: threads = clamp(hardware_concurrency, MIN_SHARDS, 128) − 1
      bits = تعداد بیت‌های threads ; num_shards = 1 << bits
allocate(n, T):
      shid = sched_getcpu() & (num_shards − 1)       # یا round-robin ثابت برای هر thread
      shards[shid].pool[ix].bytes += n × sizeof(T)    # atomic اما محلی برای هسته
      shards[shid].pool[ix].items += n
allocated_bytes(pool) = Σ over shards of bytes       # فقط هنگام dump
```

**مثال عددی.** ماشین با 48 رشته‌ی سخت‌افزاری: threads = 48 − 1 = 47 = 0b101111 (۶ بیت)، پس num_shards = 64. هر shard_t با 30 pool در main 480 بایت است که به 512 گرد می‌شود. کل 64 × 512 = 32 KiB. thread روی هسته‌ی 37 همیشه shard 37 را به‌روز می‌کند. تنها رقابت ممکن وقتی است که thread میان `sched_getcpu()` و به‌روزرسانی جابه‌جا شود، که نادر است. dump کامل 64 × 30 جمع است، که در مقایسه با یک بار در ثانیه هیچ هزینه‌ای ندارد.

::: {.warn}
`ceph tell osd.N dump_mempools` فقط حافظه‌ای را نشان می‌دهد که از allocatorهای mempool گذشته است. حافظه‌ی RocksDB (به‌جز block cache که PriorityCache آن را مدیریت می‌کند)، memtableها، پشته‌ی threadها و تکه‌تکه شدن tcmalloc در آن نیستند. اختلاف میان RSS و جمع mempoolها چند صد مگابایت تا بیش از یک گیگابایت طبیعی است. `osd_memory_base=768M` دقیقاً برای همین بخش «حساب‌نشده» در نظر گرفته شده است.
:::

# tcmalloc و حافظه‌ی «نگاشته‌شده» {#sec-33-4}

ceph-osd به‌طور پیش‌فرض با tcmalloc (از gperftools) لینک می‌شود. tcmalloc حافظه را در سه سطح نگه می‌دارد: cache هر thread، فهرست‌های آزاد مرکزی برای هر کلاس اندازه، و page heap که spanها را از سیستم‌عامل می‌گیرد. حافظه‌ی آزادشده لزوماً به سیستم‌عامل برنمی‌گردد. فقط وقتی span کاملاً آزاد باشد و `ReleaseFreeMemory` یا آزادسازی تدریجی آن را با madvise برگرداند، در `pageheap_unmapped_bytes` حساب می‌شود.

![سطوح tcmalloc. تخصیص کوچک از cache همان thread و بدون قفل انجام می‌شود. کمبود از transfer cache و central free list پر می‌شود و آن‌ها از page heap span می‌گیرند. حافظه‌ی آزاد page heap با madvise به سیستم‌عامل پس داده می‌شود و در شمارنده‌ی pageheap_unmapped_bytes دیده می‌شود. PriorityCache مقدار «mapped» را heap_size منهای همین unmapped حساب می‌کند](figures/ch33/f07_tcmalloc.png){#fig-33-f07_tcmalloc}

فایل محیطی بسته‌ها (`etc/sysconfig/ceph` در مخزن) مقدار `TCMALLOC_MAX_TOTAL_THREAD_CACHE_BYTES=134217728` (128 MiB) را می‌گذارد. این سقف کل cacheهای thread در فرایند است. اگر کمتر باشد، threadهای op بیشتر به central free list (با قفل) مراجعه می‌کنند. اگر بیشتر باشد، حافظه‌ی «پنهان» در cacheهای thread بیشتر می‌شود. استقرار cephadm متغیرهای محیطی کانتینر را جدا تنظیم می‌کند. مقدار واقعی را با `ceph tell osd.N heap stats` بخوانید.

# PriorityCache: تقسیم بودجه‌ی حافظه {#sec-33-5}

## از osd_memory_target به بودجه‌ی cache {#sec-33-5-1}

`BlueStore::MempoolThread::_update_cache_settings` و `_resize_shards` سه عدد را برای `PriorityCache::Manager` (با نام «bluestore-pricache») تعیین می‌کنند:

```text
target  = osd_memory_target                         (4 GiB)
ltarget = (1 − osd_memory_expected_fragmentation) × target = 0.85 × 4096 = 3481.6 MiB
max     = ltarget − osd_memory_base = 3481.6 − 768 = 2713.6 MiB    (اگر ltarget > base + min)
min     = osd_memory_cache_min = 128 MiB
```

::: {.algo #alg-33-3 title="تنظیم بودجه‌ی cache با بازخورد از heap (tune_memory)" src="src/common/PriorityCache.cc :: PriorityCache::Manager::tune_memory" complexity="O(1) در هر دور (هر osd_memory_cache_resize_interval = 1 ثانیه)"}
:::

```text
mapped = heap_size − pageheap_unmapped_bytes        # از tcmalloc
new = clamp(tuned_mem, min, max)
if mapped < target:  new += (1 − mapped/target) × (max − new)      # آرام به max نزدیک شو
else:                new −= (1 − target/mapped) × (new − min)      # سریع عقب بکش
tuned_mem = new
```

![شبیه‌سازی هشت دور tune_memory با پیش‌فرض‌ها و مقادیر ورودی فرضی برای mapped. از 1500 MiB، چون mapped=3000 کمتر از هدف است، بودجه به 1824.7 بالا می‌رود. در دور بعد mapped=4500 از هدف بیشتر است و بودجه به 1672.4 کاهش می‌یابد. بودجه هرگز از max=2713.6 بالاتر و از min=128 پایین‌تر نمی‌رود](figures/ch33/f03_tune.png){#fig-33-f03_tune}

**مثال عددی (دو دور اول شکل).** tuned_mem=1500 و mapped=3000: نسبت = 1 − 3000/4096 = 0.2676، پس new = 1500 + 0.2676 × (2713.6 − 1500) = 1824.7 MiB. دور بعد mapped=4500: نسبت = 1 − 4096/4500 = 0.0898، پس new = 1824.7 − 0.0898 × (1824.7 − 128) = 1672.4 MiB. عبارت «approach slowly, bounce away quickly» در خود کد آمده است. وقتی فاصله‌ی mapped تا target زیاد است، ضریب افزایش بزرگ است، اما هرچه نزدیک‌تر شود کوچک‌تر می‌شود. کاهش متناسب با فاصله تا min است، پس در بودجه‌های بزرگ کاهش مطلق بیشتر است.

::: {.warn}
**چرا OSD گاهی از osd_memory_target بیشتر می‌خورد.** این حلقه‌ی بازخورد فقط **اندازه‌ی cacheها** را کم می‌کند. اگر حافظه‌ی حساب‌نشده (pg log در هنگام recovery، بافرهای messenger زیر فشار، osdmapهای زیاد) خودش از target بیشتر شود، حتی با cache در حداقل 128 MiB، OSD از هدف عبور می‌کند. osd_memory_target **سقف سخت نیست**. در کانتینر، `osd_memory_target_cgroup_limit_ratio=0.8` پیش‌فرض target را 80٪ محدودیت cgroup می‌گذارد تا این حاشیه حفظ شود.
:::

## balance: تقسیم میان cacheها و اولویت‌ها {#sec-33-5-2}

BlueStore چهار cache در Manager ثبت می‌کند: kv (block cache مربوط به RocksDB)، kv_onode، meta (onodeها) و data (بافرها). نسبت‌ها از `bluestore_cache_kv_ratio=0.45`، `bluestore_cache_meta_ratio=0.45` و `bluestore_cache_kv_onode_ratio=0.04` می‌آیند و data باقی‌مانده (حدود 0.06) را می‌گیرد. هر cache داده‌هایش را بر پایه‌ی **سن** در bin قرار می‌دهد. اولویت‌های PRI1 تا PRI10 به بازه‌های سنی نگاشته می‌شوند (تازه‌تر = اولویت بالاتر). PRI0 مخصوص indexها و filterهای RocksDB است.

::: {.algo #alg-33-4 title="تقسیم حافظه میان cacheها به ترتیب اولویت با سهم منصفانه‌ی وزنی" src="src/common/PriorityCache.cc :: Manager::balance و balance_priority؛ BlueStore.h :: MempoolCache::request_cache_bytes" complexity="O(L × R × C) برای L اولویت، R دور و C cache"}
:::

```text
mem_avail = tuned_mem − C × get_chunk(1, tuned_mem)          # ذخیره‌ی یک chunk برای هر cache
for pri in PRI0..PRI11:
    pending = all caches; ratios = Σ ratio
    while pending and mem_avail > |pending|:
        for c in pending:
            want = c.request_cache_bytes(pri)                     # آنچه در binهای این اولویت دارد − اختصاص‌یافته
            share = mem_avail × c.ratio / ratios
            if want > share: c.add(pri, share)                    # می‌ماند برای دور بعد
            else: c.add(pri, want); pending.remove(c)
        mem_avail −= assigned; ratios = Σ ratio of remaining
    PRI11 (LAST): باقی‌مانده فقط بر پایه‌ی نسبت‌ها تقسیم می‌شود
commit: هر cache به مضرب get_chunk گرد می‌شود (usage + 64 MiB، با chunk میان 4 و 64 MiB)
```

**مثال عددی.** tuned_mem=1672 MiB. get_chunk: 1672 به توان دو بعدی یعنی 2048 MiB گرد می‌شود و تقسیم بر 256 می‌دهد 8 MiB (میان 4 و 64). get_chunk(1) برابر 1 بایت + 64 MiB است که به مضرب 8 MiB یعنی 72 MiB گرد می‌شود. چهار cache × 72 = 288 MiB ذخیره، پس mem_avail = 1384 MiB.

- **PRI0:** فقط kv می‌خواهد (فرض: 200 MiB index و filter). سهم آن 0.45 × 1384 = 622.8 است و همه‌ی 200 را می‌گیرد. mem_avail = 1184.
- **PRI1، دور 1** (فرض خواسته‌ها: kv 300، meta 900، data 100، kv_onode 50): سهم‌ها 532.8، 532.8، 71.0 و 47.4 MiB. kv خواسته‌اش (300) را کامل می‌گیرد و خارج می‌شود. بقیه سهم کامل می‌گیرند و می‌مانند. جمع اختصاص 951.2، پس mem_avail = 232.8 و نسبت‌های باقی‌مانده 0.55.
- **PRI1، دور 2:** meta 0.45/0.55 × 232.8 = 190.5 (هنوز 367.2 می‌خواهد)، data 25.4 (هنوز 29 می‌خواهد) و kv_onode فقط 2.6 باقی‌مانده‌اش را می‌گیرد. پس از چند دور دیگر، mem_avail به کمتر از تعداد cacheها می‌رسد و اولویت‌های پایین‌تر چیزی نمی‌گیرند.

![نتیجه‌ی مثال balance پس از PRI0 و دو دور PRI1. kv به 500 MiB، meta به 723.3، data به 96.4 و kv_onode به 50 مگابایت رسیده‌اند. چون cacheهای meta و data هنوز داده‌ی تازه‌ی بیشتری از بودجه دارند، binهای قدیمی‌ترشان (اولویت‌های پایین‌تر) در commit بعدی بیرون رانده می‌شوند](figures/ch33/f04_balance.png){#fig-33-f04_balance}

پیامد عملی این مثال: در OSDی که حافظه‌اش کم است، **داده‌های تازه‌ی همه‌ی cacheها** پیش از داده‌های قدیمی هر cache تأمین می‌شوند. اگر onodeهای پرکاربرد در meta جا نشوند، هر خواندن یک مراجعه‌ی اضافه به RocksDB دارد (فصل ۲۵). شمارنده‌های `bluestore-pricache:meta` و مشابه در `perf dump` (فیلدهای pri0_bytes تا pri11_bytes، committed_bytes و reserved_bytes) نشان می‌دهند بودجه دقیقاً کجا رفته است.

# NUMA {#sec-33-6}

در سرورهای دوسوکتی، دسترسی به حافظه یا دستگاه PCIe سوکت دیگر از راه اتصال میان‌سوکتی می‌گذرد و تأخیر و پهنای باند بدتری دارد. `OSD::set_numa_affinity` این را به‌طور خودکار مدیریت می‌کند.

![تصمیم وابستگی NUMA در OSD::set_numa_affinity. OSD گره NUMA دستگاه ذخیره‌سازی (get_numa_node) و گره رابط‌های شبکه‌ی public و cluster (get_iface_numa_node) را پیدا می‌کند. اگر هر سه یکسان باشند و osd_numa_auto_affinity=true باشد، همه‌ی threadها به CPUهای همان گره محدود می‌شوند. osd_numa_node اگر صریحاً تنظیم شود، بر تصمیم خودکار مقدم است](figures/ch33/f06_numa.png){#fig-33-f06_numa}

::: {.algo #alg-33-5 title="انتخاب گره NUMA برای OSD" src="src/osd/OSD.cc :: OSD::set_numa_affinity" complexity="O(1) هنگام راه‌اندازی"}
:::

```text
store_node = store.get_numa_node()
front = iface_numa(public addr); back = iface_numa(cluster addr)
if front == back == store_node and osd_numa_auto_affinity: node = front
if osd_numa_node ≥ 0: node = osd_numa_node                # اولویت با تنظیم دستی
if node ≥ 0: set_cpu_affinity_all_threads(cpus(node))
```

**مثال.** میزبانی با دو گره: nvme0 و nvme1 و NIC اول روی گره 0، و nvme2 و nvme3 و NIC دوم روی گره 1. برای osd.2 روی nvme2، اگر public و cluster هر دو روی NIC دوم باشند، OSD خودکار به هسته‌های 32 تا 63 بسته می‌شود. اگر شبکه‌ی public روی NIC اول باشد، پیام «public and cluster network numa nodes do not match» در لاگ دیده می‌شود و هیچ وابستگی‌ای تنظیم نمی‌شود. `osd_numa_prefer_iface=true` باعث می‌شود OSD هنگام انتخاب نشانی، IP روی رابط هم‌گره با دستگاه را ترجیح دهد. فرمان `ceph osd numa-status` وضعیت را برای همه‌ی OSDها نشان می‌دهد.

# پروفایل‌گیری {#sec-33-7}

![ابزارها به ترتیب لایه. درون Ceph: dump_mempools، heap stats، perf dump و dump_historic_ops. نمونه‌برداری CPU با perf و flame graph. ردیابی رویداد و زمان off-CPU با bpftrace. ردیابی تابع‌به‌تابع با uftrace. و پشته‌ی همه‌ی threadها با gdb یا eu-stack برای حالت گیرکرده](figures/ch33/f08_tools.png){#fig-33-f08_tools}

```bash
ceph tell osd.3 dump_mempools | jq '.mempool.by_pool | to_entries | sort_by(-.value.bytes) | .[:5]'
ceph tell osd.3 heap stats
ceph tell osd.3 perf dump | jq '."bluestore-pricache:meta"'
ceph osd numa-status
top -H -p $(pidof ceph-osd)                     # نام threadها
perf record -F 99 -g -p PID -- sleep 30 && perf script | stackcollapse-perf.pl | flamegraph.pl > osd.svg
bpftrace -e 'kprobe:finish_task_switch /pid == PID/ { @[kstack, comm] = count(); }'   # off-CPU تقریبی
uftrace record --no-libcall -P 'BlueStore::_txc_.*' -- ceph-osd -f --id 3   # اجرای OSD آزمایشی زیر uftrace (uftrace فرایند را خودش اجرا می‌کند)
eu-stack -p PID > stacks.txt                    # همه‌ی threadها، بدون توقف طولانی
```

**استدلال بودجه‌ی CPU برای هر op (مدل فرضی).** فرض کنید یک OSD روی NVMe با 16 thread مربوط به tp_osd_tp، 30 هزار نوشتن 4 KiB در ثانیه انجام می‌دهد و `perf` نشان می‌دهد ceph-osd حدود 6 هسته‌ی کامل مصرف می‌کند. بودجه = 6 / 30000 = 200 میکروثانیه‌ی CPU برای هر op (شامل replica). اگر flame graph نشان دهد 15٪ در crc32c و رمزگذاری msgr2، 35٪ در PrimaryLogPG و ساخت تراکنش، 30٪ در BlueStore و RocksDB و 20٪ در messenger و تخصیص حافظه است، حذف رمزگذاری (حالت crc به‌جای secure) حداکثر 30 میکروثانیه صرفه‌جویی می‌کند. در مقابل، کم کردن تقویت نوشتن RocksDB (فصل ۲۵) روی بخش بزرگ‌تری اثر دارد. این نوع حساب «سهم × بودجه» پیش از هر تنظیم، جلوی بهینه‌سازی‌های بی‌اثر را می‌گیرد. اعداد واقعی را خودتان اندازه بگیرید.

# mempoolها با داده‌ی واقعی {#sec-33-8}

این بخش عددهای واقعی mempool را از سه OSD ‏BlueStore یک کلاستر آزمایشی با Ceph 18.2.7 نشان می‌دهد. خروجی `ceph daemon osd.N dump_mempools` هر pool را با دو عدد گزارش می‌کند: items و bytes. نسبت این دو یعنی «هزینه‌ی هر آیتم»، و بهترین راه برای برآورد حافظه در مقیاس است.

## طول pg log و بودجه‌ی هر OSD {#sec-33-8-1}

::: {.algo #alg-33-6 title="بودجه‌ی طول pg log برای هر PG" src="OSDService::get_target_pg_log_entries در src/osd/OSD.cc؛ برش در PeeringState::calc_trim_to با osd_pg_log_trim_min = 100" complexity="O(1) برای هر PG"}
:::

```text
pseudocode
num_pgs = تعداد PGهای این OSD (primary و replica)
target = osd_target_pg_log_entries_per_osd        # پیش‌فرض 300000
اگر num_pgs > 0 و target > 0:
    entries = max(min(target / num_pgs, osd_max_pg_log_entries = 10000), osd_min_pg_log_entries = 250)
وگرنه entries = osd_min_pg_log_entries
برش فقط وقتی انجام می‌شود که دست‌کم osd_pg_log_trim_min ورودی برای حذف باشد ← طول تا حدود entries + 100 بالا می‌رود
ورودی‌های حذف‌شده به dups (تا osd_pg_log_dups_tracked = 3000) منتقل می‌شوند؛ هر دو در mempool osd_pglog
```

**آزمایش.** برای اینکه سقف زود دیده شود، `osd_target_pg_log_entries_per_osd` را روی 30000 گذاشتیم. سپس روی pool ‏`m33` (32 PG، size = 1) صد و بیست هزار نوشتن 128 بایتی روی 1000 شیء انجام دادیم (بازنویسی) و بعد شصت هزار نوشتن روی شیءهای تازه. هر ده هزار نوشتن، mempoolها و `log_size` همه‌ی PGها را خواندیم.

**نتیجه.** OSDها 33، 38 و 25 PG داشتند، پس بودجه‌ها 909، 789 و 1200 بود. طول log در حدود 40 هزار نوشتن ثابت شد. میانگین حدود 980 و بیشینه 1300 بود، که همان 1200 به‌علاوه‌ی حداکثر 100 ورودیِ منتظر برش است. پس از رسیدن به سقف، mempool ‏`osd_pglog` باز هم آهسته رشد کرد: روی osd.0 از 79.7 به 86.5 MiB. دلیلش این است که ورودی‌های برش‌خورده به `dups` می‌روند و dups هم در همین mempool است (`mempool::osd_pglog::list<pg_log_dup_t> dups` در osd_types.h). در این دوره هر آیتم تازه به‌طور میانگین حدود 110 بایت هزینه داشت، در برابر حدود 300 بایت در ابتدای پر شدن log.

![چپ: بیشینه و میانگین طول pg log در 32 PG ‏pool ‏m33 برحسب تعداد نوشتن، با خط‌چین بودجه‌ی هر OSD (30000 تقسیم بر تعداد PGها). راست: حجم mempool ‏osd_pglog (خط پر) و bluestore_cache_onode (خط‌چین) برای هر OSD. خط نقطه‌چین مرز بازنویسی 1000 شیء و ساختن شیء تازه است](figures/ch33/f09_pglogmem.png){#fig-33-f09_pglogmem}

## هزینه‌ی هر آیتم {#sec-33-8-2}

از آخرین نمونه‌ی osd.0 (پس از 180 هزار نوشتن) این هزینه‌ها به دست آمد:

| mempool | بایت در هر آیتم | برداشت |
|---|---|---|
| bluestore_cache_onode | 679.4 | هر onode در cache حدود 680 بایت. یک میلیون onode در cache حدود 650 MiB است |
| osd_pglog | 378.6 | میانگین مخلوط ورودی‌های log و dups |
| bluestore_blob و bluestore_shared_blob | 112.0 | برای هر blob |
| bluestore_inline_bl | 88.2 | داده‌ی inline کوچک |
| bluestore_alloc | 80.0 | برابر اندازه‌ی گره‌ی range_seg_t در allocator ‏AVL/hybrid (فصل 24) |
| bluestore_extent | 48.0 | هر extent منطقی |

این عددها را مستقیم برای برآورد به کار ببرید. برای مثال 300000 ورودی pg log در هر OSD با حدود 380 بایت تقریباً 110 MiB است، آن هم بدون dups. اگر dups برای هر PG تا 3000 پر شوند، روی OSD با 200 PG، ‏600000 dup اضافه می‌شود.

این‌ها خارج از بودجه‌ی cache در osd_memory_target نیستند. PriorityCache فقط cacheهای BlueStore و RocksDB را تنظیم می‌کند. pg log حافظه‌ی ثابتی است که از سهم cache کم می‌شود.

::: {.note}
عدد 80 بایت برای bluestore_alloc با اندازه‌ی range_seg_t که در فصل 24 از روی کد به دست آوردیم یکی است. این تطابق وارسی مستقلی برای آن عدد است.
:::

![هزینه‌ی واقعی هر آیتم (بایت تقسیم بر تعداد آیتم) در mempoolهای اصلی osd.0 روی کلاستر آزمایشی Ceph 18.2.7، همراه با تعداد آیتم‌ها و حجم کل هر mempool](figures/ch33/f10_itemcost.png){#fig-33-f10_itemcost}

# تکمیلی و به‌روز {#sec-33-9}

- فهرست poolهای mempool در main شامل `ec_extent_cache` و `bluefs_file_reader` و `bluefs_file_writer` است. در نسخه‌ی خود با `dump_mempools` ببینید کدام poolها وجود دارند.
- در Crimson (فصل ۳۰)، به‌جای thread pool، هر reactor یک هسته دارد و Seastar allocator خودش را برای هر هسته دارد. مدل حافظه و CPU این فصل فقط برای OSD کلاسیک است.
- `osd_memory_target_autotune` (پیش‌فرض false) به cephadm اجازه می‌دهد target را در سطح میزبان و بر پایه‌ی حافظه‌ی کل و تعداد OSDها تنظیم کند. این تنظیم بیرون از OSD انجام می‌شود و ارتباطی با حلقه‌ی tune_memory درون OSD ندارد.
- PriorityCache در monها هم برای cacheهای RocksDB و osdmap استفاده می‌شود (گزینه‌های `mon_memory_target` و `mon_memory_autotune`).

# تمرین عملی {#sec-33-10}

1. روی یک OSD آزمایشی، `osd_memory_target` را به 2 GiB کاهش دهید و هر 5 ثانیه `perf dump` بخش `bluestore-pricache` را ثبت کنید. کاهش تدریجی committed_bytes را با مدل tune_memory مقایسه کنید.
2. برای ماشین خودتان num_shards مربوط به mempool را از روی nproc حساب کنید.
3. PGهای primary یک OSD را با `ceph pg ls-by-primary osd.N` فهرست کنید، ps هر PG را در پیمانه‌ی 8 حساب کنید و بار shardها را تخمین بزنید.
4. با `perf record` یک flame graph از OSD هنگام `rados bench -t 64 write` بسازید و سهم crc32c، RocksDB و tcmalloc را بخوانید.
5. `ceph osd numa-status` را اجرا کنید و برای هر OSD توضیح دهید چرا وابستگی NUMA تنظیم شده یا نشده است.

# پرسش‌های مرور {#sec-33-11}

1. چرا mempool به‌جای یک شمارنده‌ی atomic مشترک از shard استفاده می‌کند و shard چگونه انتخاب می‌شود؟
2. اندازه‌ی shard_t چرا مضرب 128 است؟
3. دو عددی را که از osd_memory_target به‌عنوان max و min بودجه‌ی cache به دست می‌آیند با پیش‌فرض‌ها محاسبه کنید.
4. tune_memory در افزایش و کاهش چه رفتار متفاوتی دارد؟
5. چرا osd_memory_target سقف سخت نیست؟
6. در balance، cacheی که کمتر از سهمش می‌خواهد چه می‌شود و باقی‌مانده به چه کسی می‌رسد؟
7. get_chunk برای tuned_mem برابر 1672 MiB چه مقداری دارد؟
8. چرا افزایش threads_per_shard برای یک PG داغ کمکی نمی‌کند؟
9. OSD در چه شرطی خودکار وابستگی NUMA تنظیم می‌کند؟
10. «بودجه‌ی CPU برای هر op» را چگونه حساب می‌کنید و از آن چه نتیجه‌ای می‌گیرید؟

# منابع این فصل {#sec-33-12}

- پیکربندی حافظه‌ی BlueStore: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- مرجع گزینه‌های OSD: https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/
- mempool: https://github.com/ceph/ceph/blob/main/src/include/mempool.h
- PriorityCache: https://github.com/ceph/ceph/blob/main/src/common/PriorityCache.cc
- BlueStore MempoolThread: https://github.com/ceph/ceph/blob/main/src/os/bluestore/BlueStore.cc
- NUMA در OSD: https://github.com/ceph/ceph/blob/main/src/osd/OSD.cc
- tcmalloc (gperftools): https://github.com/gperftools/gperftools
- perf: https://perfwiki.github.io/main/
- bpftrace: https://github.com/bpftrace/bpftrace
- uftrace: https://github.com/namhyung/uftrace
- Flame graphs: https://www.brendangregg.com/flamegraphs.html
