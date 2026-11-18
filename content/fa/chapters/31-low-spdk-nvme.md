---
chapter: 31
id: ch31
title: "لایه‌های پایینی (۹): SPDK و NVMe، از صف‌های سخت‌افزاری تا درگاه NVMe-oF"
part: lower
lang: fa
---

::: {.tldr}

- NVMe با جفت‌صف‌های submission و completion در حافظه‌ی میزبان با آن حرف می‌زند؛ فصل فرمان‌ها و completionها را بایت‌به‌بایت می‌خواند.
- SPDK درایور NVMe را با polling در فضای کاربر اجرا می‌کند و `NVMEDevice` در BlueStore وقتی مسیر دستگاه با `spdk:` شروع شود از آن استفاده می‌کند.
- gateway از نوع NVMe-oF، imageهای RBD را روی NVMe/TCP صادر می‌کند؛ gatewayهای یک گروه برای failover وضعیت ANA را با هم شریک‌اند.
- اگر I/O میزبان پس از خرابی یک gateway متوقف ماند، `ceph nvme-gw show` و blocklist در OSDها را بررسی کنید.

:::

# چرا این فصل؟ {#sec-31-1}

در فصل‌های قبل، پایین‌ترین لایه‌ای که دیدیم `KernelDevice` در BlueStore بود که با libaio یا io_uring درخواست را به هسته می‌دهد. این فصل یک لایه پایین‌تر می‌رود: خود **صف‌های سخت‌افزاری NVMe**، بایت‌های یک فرمان و یک تکمیل، doorbellها و Phase Tag. سپس دو جایی را بررسی می‌کنیم که Ceph با **SPDK** (Storage Performance Development Kit) هسته را دور می‌زند:

- **NVMEDevice** در BlueStore (`src/blk/spdk/NVMEDevice.cc`): درایور فضای کاربری برای دستگاه محلی یا هدف NVMe-oF.
- **درگاه NVMe-oF** (پروژه‌ی ceph-nvmeof): هدف NVMe/TCP مبتنی بر SPDK که تصاویر RBD را به میزبان‌ها صادر می‌کند. بخش مدیریت آن در mon با `NVMeofGwMon` و `NVMeofGwMap` پیاده شده است.

::: {.note}
**وضعیت.** گزینه‌های `bluestore_spdk_*` در کد سطح `dev` دارند. پشتیبانی SPDK در BlueStore هنوز ابزاری برای آزمایش و پژوهش است و در استقرار cephadm مسیر معمول نیست. اما درگاه NVMe-oF با `ceph orch apply nvmeof` مستند و پشتیبانی می‌شود. همه‌ی ارجاع‌های کد این فصل به شاخه‌ی main در زمان نگارش است.
:::

# NVMe از نگاه درایور {#sec-31-2}

## دو مسیر داده {#sec-31-2-1}

![مقایسه‌ی دو مسیر از BlueStore تا کنترلر NVMe. در مسیر هسته، درخواست از syscall، لایه‌ی blk-mq و درایور nvme-pci می‌گذرد و تکمیل با وقفه‌ی MSI-X گزارش می‌شود. در مسیر SPDK، همه‌ی این کارها در فضای کاربر انجام می‌شود: درایور SPDK خود SQE را در صف می‌نویسد، doorbell را از راه BAR نگاشته‌شده‌ی دستگاه به‌روز می‌کند و تکمیل را با polling پیدا می‌کند. هر دو مسیر روی همان ساختار سخت‌افزاری (SQ و CQ در حافظه‌ی میزبان) به هم می‌رسند](figures/ch31/f01_paths.png){#fig-31-f01_paths}

کنترلر NVMe با میزبان از راه **جفت صف** (queue pair) گفت‌وگو می‌کند: یک **Submission Queue** (SQ) که میزبان فرمان‌ها را در آن می‌نویسد و یک **Completion Queue** (CQ) که کنترلر نتیجه‌ها را در آن می‌گذارد. هر دو، آرایه‌های حلقوی در حافظه‌ی میزبان‌اند. درایور هسته‌ی لینوکس معمولاً برای هر CPU یک جفت صف می‌سازد. به همین دلیل، دو هسته‌ی CPU برای ارسال فرمان روی یک صف رقابت نمی‌کنند.

## بایت‌های یک فرمان {#sec-31-2-2}

![ساختار ۶۴ بایتی فرمان Read/Write در صف ارسال، با مقادیر یک خواندن 4 KiB از آفست 1 GiB. opcode=0x02 یعنی Read (0x01 Write است). command_id شناسه‌ای است که درایور انتخاب می‌کند و کنترلر در CQE برمی‌گرداند. slba آدرس منطقی آغاز بر حسب بلوک است و length تعداد بلوک‌ها به‌صورت صفرمبنا. prp1 و prp2 آدرس‌های فیزیکی (یا IOVA پشت IOMMU) صفحه‌های داده‌اند](figures/ch31/f02_sqe.png){#fig-31-f02_sqe}

دو نکته‌ی سطح پایین در این ساختار مهم است:

1. **طول صفرمبنا.** مقدار 0 در `length` یعنی یک بلوک. خطای off-by-one در درایورهای آزمایشی رایج است.
2. **PRP و صفحه‌ها.** PRP1 به اولین صفحه اشاره می‌کند (می‌تواند آفست درون صفحه داشته باشد). اگر داده بیش از دو صفحه باشد، PRP2 به **فهرست PRP** اشاره می‌کند. هر ورودی ۸ بایت است، پس یک صفحه‌ی 4 KiB فهرستی از 512 صفحه را نگه می‌دارد. برای یک I/O هشت کیلوبایتی هم‌تراز، PRP1 صفحه‌ی اول و PRP2 صفحه‌ی دوم است و فهرستی لازم نیست. برای 128 KiB (32 صفحه)، PRP2 به فهرستی با 31 ورودی اشاره می‌کند.

## بایت‌های یک تکمیل {#sec-31-2-3}

![ساختار ۱۶ بایتی ورودی صف تکمیل. sq_head به میزبان می‌گوید کنترلر تا کجای SQ را خوانده است. sq_id و command_id با هم فرمان را یکتا مشخص می‌کنند. بیت صفر فیلد status همان Phase Tag است: کنترلر در دور اول صف آن را 1 می‌نویسد، در دور دوم 0، و همین‌طور تا آخر](figures/ch31/f03_cqe.png){#fig-31-f03_cqe}

::: {.algo #alg-31-1 title="تشخیص تکمیل با Phase Tag (پیمایش CQ)" src="linux: drivers/nvme/host/pci.c :: nvme_poll_cq، nvme_cqe_pending، nvme_update_cq_head" complexity="O(k) برای k تکمیل تازه؛ یک نوشتن MMIO در پایان"}
:::

```text
pseudocode (برگرفته از منطق nvme_poll_cq، بازنویسی‌شده)
found = false
while (cqes[cq_head].status & 1) == cq_phase:     # ورودی تازه؟
    found = true
    dma_rmb()                                      # بقیه‌ی CQE را پس از phase بخوان
    handle(cqes[cq_head])                          # command_id ⇒ request ⇒ تکمیل
    cq_head += 1
    if cq_head == q_depth: cq_head = 0; cq_phase ^= 1
if found: writel(cq_head, CQ_HEAD_DOORBELL)        # یک بار برای کل دسته
```

**چرا Phase Tag؟** CQ پیش از شروع با صفر پر شده است و `cq_phase` میزبان از 1 شروع می‌شود. کنترلر در دور اول CQEها را با P=1 می‌نویسد، پس هر خانه‌ای که P آن 1 است تازه است. وقتی صف یک دور کامل می‌چرخد، خانه‌های قدیمی P=1 دارند و کنترلر این بار P=0 می‌نویسد. میزبان هم با وارونه کردن `cq_phase` معیار «تازه» را عوض می‌کند. بنابراین میزبان بدون خواندن هیچ ثبات (register) از دستگاه و فقط با خواندن حافظه‌ی خودش می‌فهمد چه چیزی رسیده است. همین ویژگی است که polling را ارزان می‌کند: پیمایش خالی فقط یک خواندن از cache است.

**مثال عددی.** q_depth=4، cq_head=2، cq_phase=1. کنترلر سه فرمان را کامل می‌کند و در خانه‌های 2 و 3 با P=1 و در خانه‌ی 0 با P=0 (دور تازه) می‌نویسد. میزبان خانه‌ی 2 (P=1، تازه)، خانه‌ی 3 (تازه) را پردازش می‌کند و به انتهای صف می‌رسد: cq_head=0 و cq_phase=0. خانه‌ی 0 با P=0 تازه است و پردازش می‌شود. خانه‌ی 1 هنوز P=1 قدیمی دارد، پس حلقه می‌ایستد و یک doorbell با مقدار 1 نوشته می‌شود. سه تکمیل با یک نوشتن MMIO گزارش شدند.

## doorbellها و هزینه‌ی MMIO {#sec-31-2-4}

![توالی کامل یک فرمان: نوشتن SQE در خانه‌ی sq_tail، به‌روزرسانی SQ Tail Doorbell، واکشی و اجرای فرمان توسط کنترلر، نوشتن CQE، وقفه (یا polling)، پیمایش CQ و به‌روزرسانی CQ Head Doorbell. آفست doorbellها از ثبات CAP.DSTRD به دست می‌آید](figures/ch31/f04_rings.png){#fig-31-f04_rings}

آفست doorbellها در فضای ثبات کنترلر (BAR0) از فرمول استاندارد NVMe به دست می‌آید: `SQyTDBL = 0x1000 + (2y) × (4 << CAP.DSTRD)` و `CQyHDBL = 0x1000 + (2y+1) × (4 << CAP.DSTRD)`. برای صف 3 با DSTRD=0، doorbell مربوط به SQ در 0x1018 و doorbell مربوط به CQ در 0x101C است. هر doorbell یک نوشتن MMIO غیرقابل‌cache است که از PCIe عبور می‌کند. به همین دلیل، هسته در `nvme_write_sq_db` نوشتن doorbell را تا آخرین درخواست یک دسته به تعویق می‌اندازد (پارامتر `write_sq` و `last_sq_tail`) و `nvme_commit_rqs` در پایان دسته آن را می‌نویسد. ویژگی **Doorbell Buffer Config** (در هسته `nvme_dbbuf_update_and_check_event`) در کنترلرهای مجازی حتی همین نوشتن را حذف می‌کند، اگر دستگاه اعلام کند که لازم نیست.

::: {.deep}
**قفل‌ها در مسیر هسته.** `nvme_sq_copy_cmd` و `nvme_write_sq_db` با `__must_hold(&nvmeq->sq_lock)` علامت خورده‌اند: کپی ۶۴ بایت و جلو بردن sq_tail زیر یک spinlock مخصوص همان صف انجام می‌شود. چون معمولاً هر CPU صف خودش را دارد، این قفل تقریباً هیچ‌وقت رقابتی نیست. مسیر تکمیل هم در زمینه‌ی وقفه‌ی همان صف اجرا می‌شود و قفلی روی CQ نمی‌گیرد.
:::

# NVMEDevice: SPDK در BlueStore، تابع به تابع {#sec-31-3}

## پیکربندی و باز کردن {#sec-31-3-1}

BlueStore وقتی نام فایل دستگاه با `spdk:` شروع شود (`SPDK_PREFIX` در `BlockDevice.h`)، به‌جای `KernelDevice` از `NVMEDevice` استفاده می‌کند. مستند BlueStore دو شکل را نشان می‌دهد:

```ini
bluestore_block_path = "spdk:trtype:PCIe traddr:0000:01:00.0"
bluestore_block_path = "spdk:trtype:TCP adrfam:IPv4 traddr:10.0.0.7 trsvcid:4420 subnqn:nqn.2019-02.io.spdk:cnode1"
# برای اینکه DB و WAL هم از SPDK بروند (هم‌مکانی):
bluestore_block_db_path = ""
bluestore_block_wal_path = ""
```

![مسیر کد NVMEDevice در سه مرحله. در باز کردن، رشته‌ی transport ID از فایل خوانده و با spdk_nvme_transport_id_parse تجزیه می‌شود. NVMEManager یک thread جدا برای محیط DPDK و probe می‌سازد. در نوشتن، داده به تکه‌های 128 KiB تقسیم و در یک فهرست پیوندی Task در IOContext جمع می‌شود. aio_submit روی یک qpair مخصوص همان thread (thread_local) فرمان‌ها را می‌فرستد. تکمیل در همان thread با polling پیدا می‌شود و بافرهای DMA به مخزن برمی‌گردند](figures/ch31/f05_nvmedev.png){#fig-31-f05_nvmedev}

| تابع | کار | thread و قفل |
|---|---|---|
| NVMEDevice::open | خواندن خط trid، spdk_nvme_transport_id_parse، manager.try_get | thread بازکننده؛ قفل NVMEManager::lock |
| NVMEManager::try_get | اولین بار: ساخت dpdk_thread با spdk_env_init (coremask، mem_size)، صف probe | probe_queue_lock و probe_queue_cond |
| probe_cb / attach_cb | تطبیق trid، register_ctrlr | thread مربوط به DPDK |
| register_ctrlr | فقط namespace شماره‌ی 1؛ «فعلاً فقط یک دستگاه برای هر OSD» (ceph_assert) | زیر NVMEManager::lock |
| SharedDriverData | برای transport غیر PCIe یک admin_thread که هر 1 ثانیه admin completionها را پردازش می‌کند (keep-alive) | thread جدا |
| aio_write ⇒ write_split | تکه‌های 131072 بایتی، bl.splice به Task | thread فراخواننده |
| aio_submit | num_pending ⇒ num_running؛ thread_local SharedDriverQueueData | بدون قفل: qpair مخصوص همان thread |
| _aio_handle | ارسال Taskها و polling تا num_running صفر شود | همان thread، busy-poll |
| io_complete | کاهش عمق صف، release_segs، aio_callback | همان thread (داخل process_completions) |

## مخزن بافر DMA و تقسیم درخواست {#sec-31-3-2}

SPDK نمی‌تواند مستقیماً از حافظه‌ی معمولی bufferlist استفاده کند. کنترلر با DMA به حافظه‌ای نیاز دارد که pinned باشد و آدرس فیزیکی یا IOVA آن معلوم باشد (hugepageهای DPDK). بنابراین `SharedDriverQueueData` در سازنده‌اش ۱۰۲۴ بافر ۸ کیلوبایتی با `spdk_dma_zmalloc` می‌سازد (`data_buffer_default_num` و `data_buffer_size`). داده‌ی هر نوشتن در این بافرها **کپی** می‌شود. توضیح کد (TODO) خود می‌گوید اگر لایه‌ی بالا حافظه با آدرس فیزیکی معلوم بدهد، این کپی حذف‌شدنی است.

::: {.algo #alg-31-2 title="تقسیم I/O و تخصیص بافر DMA در NVMEDevice" src="src/blk/spdk/NVMEDevice.cc :: write_split، make_read_tasks، SharedDriverQueueData::alloc_buf_from_pool" complexity="O(len/8K) برای کپی و تخصیص؛ فضای ثابت 8 MiB برای هر thread"}
:::

```text
pseudocode
write_split(off, bl):
    while remaining > 0:
        n = min(remaining, 128 KiB)
        task = Task(WRITE, off+begin, n); bl.splice(0, n, task.bl); append(ioc, task)
alloc_buf_from_pool(task):
    count = ceil(task.len / 8 KiB)
    if count > free_buffers: return -ENOMEM        # _aio_handle دوباره poll می‌کند (goto again)
    segs = count ≤ 32 ? task.inline_segs : new void*[count]
    pop count buffers; copy task.bl into them (write)
submit: spdk_nvme_ns_cmd_writev(ns, qpair, off/bs, len/bs, io_complete, task,
                                reset_sgl=data_buf_reset_sgl, next_sge=data_buf_next_sge)
```

**مثال عددی.** نوشتن 300 KiB (307200 بایت) با بلوک 4096 بایتی:

| Task | آفست نسبی | طول | lba_count | بافرهای 8 KiB |
|---|---|---|---|---|
| 1 | 0 | 131072 | 32 | 16 |
| 2 | 131072 | 131072 | 32 | 16 |
| 3 | 262144 | 45056 | 11 | 6 (پنج کامل + یکی با 4096 بایت) |

در مجموع ۳ فرمان NVMe و ۳۸ بافر از ۱۰۲۴ بافر. چون هر Task حداکثر 128 KiB است، شمار بافرها هیچ‌وقت از 16 بیشتر نمی‌شود و همیشه در 32 خانه‌ی `inline_segs` جا می‌گیرد. شاخه‌ی `extra_segs` عملاً برای این اندازه‌ی تقسیم استفاده نمی‌شود. SPDK فهرست scatter-gather را با دو callback از Task می‌گیرد: `data_buf_next_sge` بافر بعدی را با طول 8192 (یا باقی‌مانده‌ی آخر، اینجا 4096) برمی‌گرداند و `data_buf_reset_sgl` برای بازپخش از یک آفست است. مخزن ۱۰۲۴ بافری یعنی حداکثر 8 MiB داده‌ی در پرواز برای هر thread. یک batch بزرگ‌تر از این، با `-ENOMEM` به حلقه‌ی polling برمی‌گردد تا بافرها آزاد شوند.

## polling هم‌زمان در thread فراخواننده {#sec-31-3-3}

مهم‌ترین نکته‌ی رفتاری این درایور در `_aio_handle` است: حلقه‌ی بیرونی `while (ioc->num_running)` تا وقتی **همه‌ی** I/Oهای این IOContext کامل نشده‌اند ادامه دارد. پس `aio_submit` در NVMEDevice برخلاف KernelDevice فقط ارسال نمی‌کند، بلکه thread را تا تکمیل نگه می‌دارد. اگر `process_completions` چیزی پیدا نکند، thread به اندازه‌ی `bluestore_spdk_io_sleep` (پیش‌فرض 5 میکروثانیه) با usleep می‌خوابد. `bluestore_spdk_max_io_completion` (پیش‌فرض 0 یعنی تصمیم با SPDK) تعداد تکمیل‌های هر بار poll را محدود می‌کند.

::: {.warn}
**پیامد برای BlueStore.** در KernelDevice، thread مربوط به aio جداگانه تکمیل‌ها را جمع می‌کند و kv_sync_thread یا thread مربوط به op فقط ارسال می‌کند. در NVMEDevice، هر threadی که `aio_submit` را صدا می‌زند تا پایان I/O خودش منتظر می‌ماند. با `thread_local`، هر thread یک qpair مخصوص دارد که رقابت را حذف می‌کند، اما هر thread تازه‌ای که I/O می‌فرستد ۱۰۲۴ بافر DMA (8 MiB) و یک qpair مصرف می‌کند. مجموع قابل‌محاسبه است: اگر ۱۶ thread مختلف (shardهای op، kv_sync، BlueFS) I/O بفرستند، 128 MiB از حافظه‌ی DPDK، که با `bluestore_spdk_mem=512` (MB) محدود است، فقط به این بافرها می‌رسد.
:::

**استدلال تأخیر.** خواندن تصادفی 4 KiB روی یک SSD نمونه با تأخیر داخلی 80 میکروثانیه را در نظر بگیرید. در مسیر هسته، فرض کنید ۲ تا ۵ میکروثانیه هزینه‌ی syscall، blk-mq، وقفه و بیدار کردن thread اضافه می‌شود. در SPDK بخش بزرگی از این حذف می‌شود، اما ۰ تا ۵ میکروثانیه usleep در هنگام بی‌کاری و کپی به بافر DMA اضافه می‌شود (برای 4 KiB ناچیز، برای 128 KiB چند میکروثانیه). سود SPDK بیشتر در **CPU به‌ازای هر I/O** است تا تأخیر. وقتی تأخیر دستگاه در حد ده‌ها میکروثانیه است، چند میکروثانیه‌ی نرم‌افزار در لایه‌ی BlueStore در برابر هزینه‌ی OSD (فصل‌های ۲۲ و ۳۰) کوچک است.

::: {.algo #alg-31-3 title="قانون Little برای عمق صف لازم" src="نتیجه‌ی صف‌نگاری؛ در کد: max_queue_depth = io_queue_size − 1 در SharedDriverQueueData" complexity="O(1)"}
:::

```text
QD_needed = target_IOPS × latency
```

برای 500K IOPS با تأخیر 80 میکروثانیه: `QD = 500000 × 0.00008 = 40` درخواست هم‌زمان. اگر فقط یک thread با یک IOContext که همه را در یک دسته می‌فرستد I/O بدهد و منتظر تکمیل همه بماند، QD مؤثر به اندازه‌ی همان دسته است. برای رسیدن به ۴۰، یا دسته‌ها باید بزرگ باشند، یا چند thread هم‌زمان کار کنند. همین محاسبه نشان می‌دهد چرا اجرای چند OSD روی یک NVMe سریع، یا shardهای بیشتر، گاهی بیش از تغییر درایور اثر دارد.

# درگاه NVMe-oF {#sec-31-4}

## معماری {#sec-31-4-1}

![اجزای درگاه NVMe-oF. هدف SPDK (nvmf_tgt) فرمان‌های NVMe/TCP را از میزبان می‌گیرد و هر namespace را به یک bdev از نوع rbd می‌دهد. این bdev با librbd ناهم‌گام (rbd_aio_readv و rbd_aio_writev) کار می‌کند. سرویس gRPC درگاه پیکربندی را در یک شیء omap در RADOS نگه می‌دارد. NVMeofGwMonitorClient با mon در ارتباط است و وضعیت ANA هر گروه را از NVMeofGwMap می‌گیرد](figures/ch31/f07_gw.png){#fig-31-f07_gw}

مستند Ceph درگاه را یک هدف NVMe/TCP توصیف می‌کند که تصاویر RBD را صادر می‌کند. هر درگاه همچنین یک Discovery Controller اجرا می‌کند. اعدادی که مستند main برای مقیاس اعلام می‌کند: تا ۴ گروه درگاه، ۸ درگاه در هر گروه، ۱۲۸ subsystem در هر گروه، ۳۲ میزبان در هر subsystem و ۱۰۲۴ namespace در هر گروه. حداقل منابع پیشنهادی ۸ GB حافظه و چهار thread پردازنده برای هر نمونه‌ی درگاه است.

::: {.note}
**وابسته به نسخه.** این سقف‌ها از مستند main گرفته شده‌اند. پیکربندی نمونه‌ی شاخه‌ی devel پروژه‌ی ceph-nvmeof گزینه‌هایی مثل `max_subsystems = 128`، `max_namespaces = 4096` و `max_gws_in_grp = 16` را نشان می‌دهد. پیش از برنامه‌ریزی ظرفیت، مستند همان نسخه‌ای را که نصب می‌کنید ببینید.
:::

## مسیر یک نوشتن از میزبان تا OSD {#sec-31-4-2}

![بایت‌های NVMe/TCP. هر PDU با هدر مشترک ۸ بایتی (type، flags، hlen، pdo، plen) شروع می‌شود. Command Capsule همان SQE ۶۴ بایتی را حمل می‌کند و اگر داده از in_capsule_data_size کوچک‌تر باشد، داده هم درون کپسول می‌آید. برای داده‌ی بزرگ‌تر، هدف با یک R2T اجازه‌ی ارسال می‌دهد و میزبان داده را در H2CData می‌فرستد](figures/ch31/f06_tcppdu.png){#fig-31-f06_tcppdu}

1. میزبان (`nvme_tcp` در هسته) یک Command Capsule با opcode Write می‌فرستد. پیکربندی نمونه‌ی درگاه `in_capsule_data_size` را 8192 گذاشته است، پس نوشتن 4 KiB در یک PDU با plen=4168 جا می‌گیرد.
2. reactor مربوط به SPDK روی socket آن qpair poll می‌کند، PDU را تجزیه و فرمان را به bdev می‌دهد.
3. `bdev_rbd` با `rbd_aio_create_completion` و `rbd_aio_writev` درخواست را به librbd می‌دهد. از اینجا مسیر همان مسیر librbd است (فصل‌های ۲ و ۲۲): ObjectRequest، Objecter و MOSDOp.
4. callback مربوط به librbd در threadهای خود librbd اجرا می‌شود، نه در reactor مربوط به SPDK. `bdev_rbd_io_complete` با `spdk_thread_send_msg` تکمیل را به thread ارسال‌کننده (`submit_td`) برمی‌گرداند تا مدل تک‌threadی SPDK حفظ شود.
5. reactor یک Response Capsule برمی‌گرداند.

**بودجه‌ی تأخیر (نمونه‌ی فرضی، 4 KiB، شبکه‌ی 25 گیگابیتی).** رفت و برگشت میزبان تا درگاه حدود 20 تا 40 میکروثانیه، پردازش SPDK چند میکروثانیه، دو گذر از مرز thread (librbd به reactor و برعکس) چند میکروثانیه، و مسیر librbd تا OSD و replicaها (که در خوشه‌های NVMe معمولاً ۰٫۵ تا ۲ میلی‌ثانیه است). بنابراین درگاه NVMe-oF معمولاً **یک رفت و برگشت شبکه‌ی اضافه** به مسیر krbd یا librbd مستقیم می‌افزاید. سود آن سازگاری با میزبان‌های بدون کلاینت Ceph (مثلاً VMware) و multipath استاندارد است، نه کاهش تأخیر.

## ANA و failover در mon {#sec-31-4-3}

NVMe-oF برای HA از **ANA** (Asymmetric Namespace Access) استفاده می‌کند. هر namespace به یک **گروه ANA** (گروه توازن بار) تعلق دارد. در هر لحظه فقط یک درگاه برای آن گروه «optimized» است و بقیه «inaccessible» گزارش می‌شوند. multipath میزبان I/O را فقط به مسیر optimized می‌فرستد. شمار گروه‌های توازن بار برابر شمار درگاه‌های گروه است.

![ماشین حالت هر درگاه برای هر گروه ANA در gw_states_per_group_t (NVMeofGwTypes.h): IDLE، STANDBY، ACTIVE، OWNER_WAIT_FAILBACK_PREPARED، WAIT_FAILBACK_PREPARED و WAIT_BLOCKLIST_CMPL. حالت صادرشده به میزبان فقط دو مقدار دارد: OPTIMIZED برای ACTIVE و WAIT_BLOCKLIST_CMPL، و INACCESSIBLE برای بقیه](figures/ch31/f08_anafsm.png){#fig-31-f08_anafsm}

**چرا WAIT_BLOCKLIST_CMPL؟** پیش از اینکه درگاه B گروه درگاه خراب A را بپذیرد، باید مطمئن شد A (اگر فقط از mon جدا شده و هنوز زنده است) دیگر نمی‌تواند روی تصاویر RBD بنویسد. وگرنه دو درگاه هم‌زمان روی یک namespace می‌نویسند. `set_failover_gw_for_ANA_group` نشانی‌های A را با `blocklist_gw` در OSDMap blocklist می‌کند و epoch آن را در `blocklist_data[grp].osd_epoch` نگه می‌دارد. B فقط وقتی ACTIVE می‌شود که beacon آن نشان دهد OSDMap با epoch مساوی یا بزرگ‌تر را دیده است (`fsm_handle_gw_alive`). این همان الگوی fencing با blocklist است که در exclusive lock مربوط به RBD و rbd-mirror (فصل‌های ۲ و ۱۸) دیدیم.

![توالی failover. پس از mon_nvmeofgw_beacon_grace (پیش‌فرض 7 ثانیه) بدون beacon، درگاه A ناموجود اعلام می‌شود. find_failover_candidate کم‌بارترین درگاه را پیدا می‌کند، A blocklist می‌شود و B در WAIT_BLOCKLIST_CMPL با تایمر 30 ثانیه قرار می‌گیرد. با رسیدن OSDMap تازه به B، گروه برای B فعال و ANA میزبان به‌روز می‌شود](figures/ch31/f09_failover.png){#fig-31-f09_failover}

::: {.algo #alg-31-4 title="انتخاب درگاه جایگزین (کم‌بارترین، با اولویت location)" src="src/mon/NVMeofGwMap.cc :: NVMeofGwMap::find_failover_candidate و find_failover_gw_logic" complexity="O(G × A) برای G درگاه و A گروه ANA"}
:::

```text
pseudocode
find_failover_gw_logic(gws, location, ignore_locations):
    best = none; best_load = 0xFFF; busy = 0
    for gw in gws (به ترتیب شناسه):
        if not AVAILABLE or (not ignore_locations and gw.location ≠ location): continue
        if location(gw) in disaster: continue
        load = 0
        for grp in gw.sm_state:
            if state in {OWNER_WAIT_FAILBACK_PREPARED, WAIT_FAILBACK_PREPARED, WAIT_BLOCKLIST_CMPL}:
                load = 0xFFFF; busy += 1; break           # در حال گذار: کنار گذاشته می‌شود
            if state == ACTIVE: load += 1
        if load < best_load: best, best_load = gw, load
    return best ? 0 : (busy ? -EBUSY : -ENOENT)
find_failover_candidate: اول با location همان گروه؛ اگر -ENOENT، با ignore_locations=true
```

**مثال عددی.** گروه درگاهی با چهار درگاه در دو location داریم: A و B در L1، و C و D در L2. گروه‌های ANA فعال: A={1}، B={2، 5}، C={3}، D={4}. A از دست می‌رود و گروه 1 در L1 است. در دور اول فقط B در L1 در دسترس است، با بار 2، پس B انتخاب می‌شود، اگرچه C و D بار کمتری دارند. این تصمیم عمدی است: ترافیک در همان location می‌ماند. اگر B در آن لحظه در WAIT_FAILBACK_PREPARED برای گروه دیگری بود، بار آن 0xFFFF می‌شد و نتیجه‌ی دور اول -EBUSY بود. چون -EBUSY با -ENOENT فرق دارد، دور دوم اجرا نمی‌شود و failover تا پایان گذار B به تعویق می‌افتد. اگر B هم خراب بود (-ENOENT)، دور دوم میان C و D (هر دو با بار 1) اولی را به ترتیب شناسه، یعنی C، انتخاب می‌کرد، چون مقایسه اکید (`>`) است.

| گزینه (mon.yaml.in، main) | پیش‌فرض | معنا |
|---|---|---|
| mon_nvmeofgw_beacon_grace | 7 ثانیه | بی‌خبری پس از آن درگاه خراب اعلام می‌شود |
| mon_nvmeofgw_skip_failovers_interval | 16 ثانیه | دوره‌ای که در آن هیچ failover در آن pool و گروه انجام نمی‌شود |
| mon_nvmeofgw_beacons_till_ack | 15 | تعداد beacon از MonClient پیش از اینکه NVMeofGwMon نقشه‌ی ack بفرستد |
| mon_nvmeofgw_max_down_gws | 1 | فرمان ok-to-stop بررسی می‌کند بیش از این تعداد درگاه down نباشد (جلوگیری از توقف همه هنگام ارتقا) |
| mon_nvmeofgw_delete_grace | 15 دقیقه | پس از این مدت، هشدار سلامت NVMEOF_GATEWAY_DELETING داده می‌شود |
| mon_nvmeofgw_failback_delay | 0 | تأخیر failback پس از برگشت مالک |

**محاسبه‌ی زمان قطع I/O در failover.** در بدترین حالت: 7 ثانیه تا اعلام خرابی، به اضافه‌ی زمان یک proposal مربوط به Paxos برای blocklist (معمولاً کمتر از یک ثانیه)، به اضافه‌ی رسیدن OSDMap به B و beacon بعدی آن. پس میزبان باید چند ثانیه تا ده و چند ثانیه I/O معلق را تحمل کند. مستند توصیه می‌کند در `nvme connect-all` گزینه‌ی `-l 1800` (ctrl-loss-tmo برابر 1800 ثانیه) را بدهید تا میزبان در این فاصله مسیر را رها نکند.

# فرمان‌های عملی {#sec-31-5}

```bash {since=tentacle}
# درگاه (pool و group را باید با نام گزینه داد)
ceph orch apply nvmeof --pool POOL --group GROUP --placement="host01, host02"
ceph nvmeof subsystem add --nqn nqn.2016-06.io.spdk:cnode1
ceph nvmeof listener add --nqn nqn.2016-06.io.spdk:cnode1 --host-name host01 --traddr 10.0.0.11 --trsvcid 4420
ceph nvmeof namespace add --nqn nqn.2016-06.io.spdk:cnode1 --rbd-pool rbd --rbd-image-name vol1
ceph nvme-gw show POOL GROUP          # وضعیت ANA هر درگاه از دید mon
# میزبان
nvme discover -t tcp -a 10.0.0.11 -s 8009
nvme connect-all --traddr 10.0.0.11 --transport tcp -l 1800 -s 8009
nvme list-subsys                       # مسیرها و وضعیت ANA (optimized/inaccessible)
# دیدن فرمان‌های NVMe در هسته
bpftrace -e 'tracepoint:nvme:nvme_setup_cmd { @op[args->opcode] = count(); }'
```

::: {.debug}
اگر پس از خرابی یک درگاه، I/O میزبان بیش از چند ده ثانیه معلق ماند: (۱) با `ceph nvme-gw show` ببینید گروه ANA در WAIT_BLOCKLIST_CMPL مانده است یا نه؛ (۲) `ceph osd blocklist ls` را بررسی کنید که نشانی درگاه قدیمی blocklist شده باشد؛ (۳) مطمئن شوید OSDMonitor قابل نوشتن است. `CMonRequestProposal` تا writeable شدن OSDMonitor صبر می‌کند، پس مشکل quorum مستقیماً failover را متوقف می‌کند.
:::

::: {.warn}
مستند هشدار می‌دهد `ceph nvme-gw create` و `delete` را روی خوشه‌ی مدیریت‌شده با cephadm دستی اجرا نکنید: حذف درگاه بی‌درنگ گروه‌های ANA آن را failover می‌کند. `disable` کردن همه‌ی درگاه‌های یک گروه دسترسی NVMe-oF به namespaceها را قطع می‌کند.
:::

# تکمیلی و به‌روز {#sec-31-6}

- فرمان `ceph nvme-gw listeners` طبق مستند در Tentacle افزوده شده است.
- در main، NVMeofGwMap مفهوم **location** و حالت **disaster** برای یک location دارد (`cfg_set_location`، `cfg_location_disaster_set`). انتخاب جایگزین اول در همان location انجام می‌شود. این قابلیت را پیش از استفاده در نسخه‌ی خود بررسی کنید.
- `NVMeofGwBeaconConstants.h` دو نسخه‌ی beacon تعریف می‌کند: 1 (قدیمی، بدون diff) و 2 (با diff). گزینه‌ی `cfg_enable_disable_beacon_diff` در mon آن را کنترل می‌کند.
- در NVMEDevice، `register_ctrlr` فقط namespace شماره‌ی ۱ را استفاده می‌کند و `ceph_assert(shared_driver_datas.empty())` یعنی فقط یک دستگاه SPDK برای هر فرایند OSD.

# تمرین عملی {#sec-31-7}

1. برای q_depth=8 و DSTRD=2، آفست doorbellهای SQ و CQ صف 5 را حساب کنید. (پاسخ: 0x1000 + 10×16 = 0x10A0 و 0x10B0)
2. SQE یک نوشتن 64 KiB در آفست 3 GiB با LBA پانصد و دوازده بایتی را بنویسید: slba، NLB و تعداد ورودی‌های فهرست PRP.
3. نوشتن 1 MiB در NVMEDevice: تعداد Taskها، فرمان‌ها و بافرهای DMA را حساب کنید.
4. با bpftrace روی tracepointهای nvme_setup_cmd و nvme_complete_rq، توزیع تأخیر دستگاه را برای یک OSD در حین `rados bench` بسازید.
5. در یک گروه سه‌درگاهی، یکی را با `ceph orch daemon stop` متوقف و تغییر حالت ANA را در `nvme list-subsys` و `ceph nvme-gw show` دنبال کنید.

# پرسش‌های مرور {#sec-31-8}

1. SQ و CQ کجا قرار دارند و چه کسی در هرکدام می‌نویسد؟
2. Phase Tag چگونه بدون خواندن ثبات دستگاه، CQE تازه را مشخص می‌کند؟
3. چرا هسته نوشتن doorbell را تا پایان دسته به تعویق می‌اندازد؟
4. فیلد length در فرمان Read چرا صفرمبناست و برای 8 بلوک چه مقداری دارد؟
5. چرا NVMEDevice داده را در بافرهای DMA کپی می‌کند؟
6. thread_local SharedDriverQueueData چه سودی و چه هزینه‌ای دارد؟
7. aio_submit در NVMEDevice از نظر بلوکه شدن با KernelDevice چه تفاوتی دارد؟
8. مسیر یک نوشتن از nvme_tcp میزبان تا OSD را با نام توابع bdev_rbd شرح دهید.
9. چرا درگاه جایگزین پیش از ACTIVE شدن باید منتظر blocklist باشد؟
10. الگوریتم انتخاب درگاه جایگزین چه زمانی -EBUSY و چه زمانی -ENOENT برمی‌گرداند؟

# منابع این فصل {#sec-31-9}

- درگاه NVMe-oF در مستند Ceph: https://docs.ceph.com/en/latest/rbd/nvmeof-overview/
- پیکربندی هدف NVMe-oF: https://docs.ceph.com/en/latest/rbd/nvmeof-target-configure/
- پیش‌نیازهای درگاه: https://docs.ceph.com/en/latest/rbd/nvmeof-requirements/
- استفاده از SPDK در BlueStore: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- کد NVMEDevice: https://github.com/ceph/ceph/blob/main/src/blk/spdk/NVMEDevice.cc
- کد NVMeofGwMap: https://github.com/ceph/ceph/blob/main/src/mon/NVMeofGwMap.cc
- پروژه‌ی ceph-nvmeof: https://github.com/ceph/ceph-nvmeof
- درایور NVMe هسته‌ی لینوکس: https://github.com/torvalds/linux/blob/master/drivers/nvme/host/pci.c
- ساختارهای NVMe و NVMe/TCP: https://github.com/torvalds/linux/blob/master/include/linux/nvme.h
- ماژول bdev_rbd در SPDK: https://github.com/spdk/spdk/blob/master/module/bdev/rbd/bdev_rbd.c
- مستند SPDK: https://spdk.io/doc/
- مشخصات NVMe: https://nvmexpress.org/specifications/
