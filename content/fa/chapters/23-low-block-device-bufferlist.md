---
chapter: 23
id: ch23
title: "لایه‌های پایینی (۱): دستگاه بلوکی، bufferlist، mempool و crc32c"
part: lower
lang: fa
---

# جایگاه این بخش {#sec-23-1}

بخش «لایه‌های پایینی» در کتاب اصلی وجود ندارد. این بخش از جایی شروع می‌شود که فصل‌های قبل متوقف شدند: پس از اینکه BlueStore تصمیم گرفت «این بایت‌ها را در این offset بنویس»، چه اتفاقی می‌افتد؟ این فصل مسیر را از `bufferlist` در حافظه‌ی ceph-osd تا فرمان DMA روی دستگاه دنبال می‌کند. فصل‌های بعدی همین کار را برای قالب روی دیسک BlueStore، RocksDB، msgr2، ریاضیات erasure code، CRUSH در سطح بیت و کلاینت‌های هسته انجام می‌دهند. همه‌ی نام‌ها با شاخه‌ی main مخزن ceph/ceph تطبیق داده شده‌اند.

::: {.summary title="در این فصل"}

- `KernelDevice`: باز کردن دستگاه با O_DIRECT، قفل، write hint، discard و flush
- libaio در برابر io_uring و مسیر `aio_submit` تا callback تکمیل
- هم‌ترازی و `bdev_block_size`
- ساختار درونی `bufferlist`، `ptr` و `raw`، کپی صفر و mempool
- crc32c: انتخاب پیاده‌سازی سخت‌افزاری و یک مثال عددی

:::

# KernelDevice: پنجره‌ی BlueStore به دیسک {#sec-23-2}

`src/blk/BlockDevice.h` رابط انتزاعی `BlockDevice` را تعریف می‌کند و `BlockDevice.cc` نوع آن را انتخاب می‌کند. در شاخه‌ی main فقط دو نوع وجود دارد: `aio` (کلاس `KernelDevice` در `src/blk/kernel/`) و `spdk` (کلاس `NVMEDevice` در `src/blk/spdk/`). پیاده‌سازی PMEM که در نسخه‌های قدیمی‌تر وجود داشت، در main دیگر در `block_device_t` نیست.

![مسیر یک نوشتن از BlueStore تا دیسک. در فضای کاربر، BlueStore یک bufferlist هم‌تراز با بلوک می‌سازد و از طریق IOContext فهرستی از aio_t (offset، iovec و write hint) جمع می‌کند. KernelDevice::aio_submit آن‌ها را دسته‌ای به صف aio می‌دهد. در مرز syscall، libaio از io_submit و io_uring از io_uring_prep_writev و io_uring_submit استفاده می‌کند، روی fdی که با O_RDWR و O_DIRECT باز شده است (برای هر write hint یک fd جدا). در هسته، bio به request در blk-mq تبدیل و درایور NVMe یا SCSI داده را با DMA مستقیم از صفحه‌های حافظه‌ی کاربر منتقل می‌کند. تکمیل از طریق io_getevents یا CQE به _aio_thread می‌رسد و او aio_callback را صدا می‌زند](figures/ch23/f01_stack.png){#fig-23-f01_stack}

## باز کردن دستگاه {#sec-23-2-1}

`KernelDevice::open()` برای هر مقدار write hint از `WRITE_LIFE_NOT_SET` تا `WRITE_LIFE_MAX` دو fd باز می‌کند: یکی در `fd_directs` با `O_RDWR | O_DIRECT` و دیگری در `fd_buffereds` بدون O_DIRECT برای مسیرهای buffered (مثلاً خواندن‌های بزرگ BlueFS). اگر هسته از `F_SET_FILE_RW_HINT` پشتیبانی کند، روی هر fd hint مربوطه با `fcntl` تنظیم می‌شود تا SSDهای دارای streams بتوانند داده‌های با طول عمر متفاوت را جدا نگه دارند. روی fd buffered هم `posix_fadvise(..., POSIX_FADV_RANDOM)` تنظیم می‌شود.

**قفل انحصاری:** `KernelDevice::_lock()` ابتدا قفل رکورد (`struct flock` با `F_WRLCK`) و در صورت نیاز `flock(fd, LOCK_EX | LOCK_NB)` را امتحان می‌کند، با حداکثر `bdev_flock_retry=3` بار تلاش دوباره. این قفل مانع می‌شود که دو فرایند (مثلاً OSD در حال اجرا و یک `ceph-bluestore-tool` اشتباهی) هم‌زمان روی یک دستگاه بنویسند.

```text
pseudocode: KernelDevice::open (خلاصه‌ی این کتاب)
  for hint in WRITE_LIFE_NOT_SET .. WRITE_LIFE_MAX-1:
      fd_directs[hint]   = open(path, O_RDWR | O_DIRECT | O_CLOEXEC)
      fd_buffereds[hint] = open(path, O_RDWR | O_CLOEXEC)
      if F_SET_FILE_RW_HINT: fcntl(fd, F_SET_FILE_RW_HINT, &hint)
  _lock()                                   # flock/F_WRLCK، تا 3 بار retry
  fstat → size، block_size = bdev_block_size (4K)؛ اگر st_blksize فرق کند فقط هشدار
  detect rotational، discard support، NUMA node، device model/serial
  if bdev_aio: io_queue = io_uring (اگر bdev_ioring=true و پشتیبانی شود) یا libaio
  start _aio_thread ؛ start discard threads (bdev_async_discard_threads)
```

## هم‌ترازی {#sec-23-2-2}

با O_DIRECT، هسته داده را مستقیم از صفحه‌های کاربر DMA می‌کند. بنابراین offset، طول و آدرس بافر باید با اندازه‌ی بلوک منطقی دستگاه هم‌تراز باشند. Ceph این را با `bdev_block_size=4_K` و assert در مسیرهای نوشتن تضمین می‌کند. بافرهای خواندن با `bdev_read_buffer_alignment=4_K` تخصیص می‌یابند. نتیجه‌ی عملی: BlueStore هرگز کمتر از ۴K روی دستگاه نمی‌نویسد. نوشتن ۱۰۰ بایتی کلاینت یا به یک read-modify-write روی یک بلوک ۴K تبدیل می‌شود یا (روی HDD) به نوشتن deferred در WAL (فصل ۲۴).

::: {.warn}
دیسک‌هایی که «۴K native» نیستند ولی بلوک فیزیکی ۴K را در قالب ۵۱۲e گزارش می‌کنند، با `bdev_block_size=4K` درست کار می‌کنند. اما دستگاهی با بلوک منطقی بزرگ‌تر از ۴K (برخی آرایه‌های سخت‌افزاری) با پیش‌فرض‌ها سازگار نیست و OSD هنگام mkfs یا open خطا می‌دهد. پیش از خرید، مقدار `cat /sys/block/<dev>/queue/logical_block_size` را بررسی کنید.
:::

## libaio یا io_uring {#sec-23-2-3}

| گزینه | پیش‌فرض (main) | نقش |
|---|---|---|
| bdev_aio | true | استفاده از I/O ناهمگام |
| bdev_ioring | false | استفاده از io_uring به‌جای libaio (اگر هسته و liburing پشتیبانی کنند) |
| bdev_ioring_hipri / bdev_ioring_sqthread_poll | false / false | poll سخت‌افزاری و thread ارسال هسته |
| bdev_aio_max_queue_depth | 1024 | عمق صف aio |
| bdev_aio_reap_max | 16 | حداکثر تکمیل‌های برداشته‌شده در هر بار |
| bdev_aio_poll_ms | 250 | مهلت انتظار برای تکمیل |
| bdev_block_size | 4_K | اندازه‌ی بلوک فرضی |
| bdev_enable_discard | false | ارسال discard/TRIM پس از آزادسازی فضا |
| bdev_async_discard_threads | 0 | discard ناهمگام (جایگزین گزینه‌ی قدیمی bdev_async_discard) |
| bdev_flock_retry | 3 | تلاش دوباره برای قفل |

در libaio (`src/blk/aio/aio.cc`)، `aio_queue_t::submit_batch` آرایه‌ای از `iocb`ها را با `io_submit` ارسال می‌کند. فیلد `iocb` باید **نخستین عضو** `aio_t` باشد تا اشاره‌گر برگشتی از هسته مستقیم به `aio_t` cast شود (توضیح خود کد در `aio.h`). در صورت `EAGAIN`، ارسال با تأخیر کوتاه تکرار می‌شود. `get_next_completed` با `io_getevents` منتظر تکمیل می‌ماند. در io_uring (`src/blk/kernel/io_uring.cc`) همان رابط با `io_uring_prep_writev`، `io_uring_prep_readv` و `io_uring_submit` پیاده شده است.

![توالی یک دسته I/O. thread تراکنش فقط aio_write را در IOContext ثبت می‌کند و سپس aio_submit همه را دسته‌ای (تا عمق 1024) ارسال می‌کند. thread مستقل _aio_thread در حلقه‌ای با مهلت 250 میلی‌ثانیه حداکثر 16 تکمیل را برمی‌دارد و شمارنده‌ی num_running هر IOContext را کم می‌کند. وقتی این شمارنده به صفر برسد، aio_callback با priv همان تراکنش فراخوانی می‌شود و BlueStore آن را از AIO_WAIT به IO_DONE و سپس KV_QUEUED می‌برد](figures/ch23/f02_aio.png){#fig-23-f02_aio}

```cpp
// from ceph/ceph, LGPL — src/blk/kernel/KernelDevice.cc, _aio_thread() (excerpt)
	if (--ioc->num_running == 0) {
	    aio_callback(aio_callback_priv, ioc->priv);
```

## flush و discard {#sec-23-2-4}

`KernelDevice::flush()` در انتها `fdatasync(fd_directs[WRITE_LIFE_NOT_SET])` را اجرا می‌کند تا کش نوشتن دستگاه تخلیه شود. در `BlueStore::_kv_sync_thread` منطقی به نام `force_flush` وجود دارد: اگر داده و DB روی یک دستگاه باشند، commit لاگ BlueFS خودش دستگاه را flush می‌کند و flush جداگانه لازم نیست. در غیر این صورت (یا وقتی چیزی برای commit در RocksDB نیست)، flush دستگاه داده اجباری می‌شود تا داده‌ی aio پیش از ثبت فراداده پایدار باشد. discard فقط وقتی ارسال می‌شود که دستگاه آن را پشتیبانی کند و `bdev_enable_discard=true` باشد. با `bdev_async_discard_threads>0`، discard در threadهای جدا و با سقف صف `bdev_async_discard_max_pending` انجام می‌شود تا تأخیر نوشتن را بالا نبرد.

::: {.deep}
چرا discard پیش‌فرض خاموش است: روی بسیاری از SSDهای SATA، فرمان TRIM هم‌گام و کند است و می‌تواند صف دستگاه را چند میلی‌ثانیه مسدود کند. SSDهای امروزی NVMe معمولاً بدون discard هم عملکرد خوبی دارند، چون over-provisioning داخلی دارند. اگر discard را فعال می‌کنید، آن را ناهمگام کنید و تأخیر p99 را قبل و بعد بسنجید.
:::

## SPDK {#sec-23-2-5}

`NVMEDevice` در `src/blk/spdk/` دستگاه NVMe را کاملاً از هسته جدا می‌کند: درایور فضای کاربر SPDK صف‌های NVMe را مستقیم با polling مدیریت می‌کند و هیچ syscall و وقفه‌ای در مسیر داده نیست. مسیر دستگاه با پیشوند `spdk:` در `bluestore_block_path` مشخص می‌شود. هزینه‌ی آن، اختصاص هسته‌ی CPU به polling، نیاز به hugepage و vfio، و از دست رفتن ابزارهای معمول هسته (iostat، blktrace) است. در عمل بیشتر استقرارها همان KernelDevice را ترجیح می‌دهند و crimson با SeaStore مسیر دیگری برای حذف سربار هسته دنبال می‌کند.

::: {.debug}
دیدن مسیر واقعی I/O:
:::

```bash
ceph osd metadata 4 | jq '{bluestore_bdev_type, bluestore_bdev_rotational, bluestore_bdev_dev_node}'
cat /sys/block/nvme0n1/queue/{logical_block_size,physical_block_size,write_cache}
ceph config get osd.4 bdev_ioring
strace -f -e trace=io_submit,io_getevents,io_uring_enter -p $(pgrep -f 'ceph-osd.*--id 4') 2>&1 | head
blktrace -d /dev/nvme0n1 -o - | blkparse -i - | head -30   # Q/G/D/C برای هر request
```

# bufferlist: ساختار داده‌ی اصلی Ceph {#sec-23-3}

تقریباً هر بایتی که در Ceph جابه‌جا می‌شود، چه پیام شبکه، چه داده‌ی شیء، چه رکورد RocksDB، داخل یک `ceph::buffer::list` (معمولاً با نام کوتاه `bufferlist`) است. طراحی آن سه هدف دارد: **کپی صفر** (اتصال تکه‌ها بدون جابه‌جایی بایت‌ها)، **اشتراک** (چند لیست به یک حافظه اشاره کنند) و **حسابداری حافظه** (هر تکه به یک mempool تعلق دارد).

![سه لایه‌ی bufferlist. در بالا، list یک فهرست پیوندی از ptr_nodeها در _buffers نگه می‌دارد، به‌همراه _carriage (اشاره به آخرین ptr که append سریع روی آن انجام می‌شود)، _len (کل بایت‌ها) و _num (تعداد ptrها). در میانه، هر ptr فقط یک پنجره است: اشاره‌گر به یک raw همراه _off و _len. در پایین، raw مالک حافظه‌ی واقعی است و data، len، شمارنده‌ی ارجاع اتمیک nref، شناسه‌ی mempool و کش آخرین crc را نگه می‌دارد. چند ptr در چند list می‌توانند به یک raw اشاره کنند؛ کپی یک bufferlist فقط nref را افزایش می‌دهد](figures/ch23/f03_bl.png){#fig-23-f03_bl}

| نوع | فایل | نکته |
|---|---|---|
| `buffer::ptr` | `include/buffer.h` | فیلدهای `_raw`، `_off`، `_len`؛ متدهای `c_str()`، `length()`، `is_aligned()`، `is_page_aligned()` |
| `buffer::list` | `include/buffer.h` | `_buffers`، `_carriage`، `_len`، `_num`؛ `append`، `claim_append`، `splice`، `rebuild`، `c_str()` |
| `buffer::raw` | `include/buffer_raw.h` | `data`، `len`، `nref`، `mempool`، `last_crc_offset`/`last_crc_val` با `crc_spinlock` |
| پیاده‌سازی‌های raw | `common/buffer.cc` | `create_aligned`، `create_small_page_aligned`، `claim_char`، `claim_malloc`، `claim_buffer` (با deleter دلخواه)، `raw_hack_aligned` |

## هزینه‌ی واقعی c_str() {#sec-23-3-1}

`list::c_str()` اشاره‌گری به یک ناحیه‌ی **پیوسته** برمی‌گرداند. اگر لیست از چند ptr تشکیل شده باشد، ابتدا `rebuild()` اجرا می‌شود که یک raw تازه می‌سازد و همه‌ی تکه‌ها را در آن **کپی** می‌کند. بنابراین یک فراخوانی ظاهراً بی‌خطر می‌تواند یک کپی چند مگابایتی ایجاد کند. کد مسیر داده برای همین از iteratorها (`begin()`، `copy()`) یا از `rebuild_aligned_size_and_memory` (برای O_DIRECT) استفاده می‌کند.

```text
pseudocode: مسیر بدون کپی یک نوشتن (خلاصه‌ی این کتاب)
  msgr2 دریافت: segment داده در یک raw تازه (با هم‌ترازی اعلام‌شده در preamble) خوانده می‌شود
  MOSDOp::decode: ptr روی همان raw (بدون کپی) → OSDOp.indata
  PrimaryLogPG: t.write(oid, off, len, indata)                          # nref++
  BlueStore::_do_write: اگر هم‌تراز → همان ptrها به iovec تبدیل می‌شوند
                         اگر نه → pad با صفر/داده‌ی قبلی + rebuild_aligned (یک کپی)
  KernelDevice::aio_write: iovec[] → io_prep_pwritev (DMA از همان صفحه‌ها)
```

::: {.deep}
crc کش‌شده روی raw: `buffer::list::crc32c()` برای هر ptr با `raw::get_crc` بررسی می‌کند آیا raw برای همان بازه قبلاً crc را محاسبه و با `set_crc` جفت (seed پایه، crc) را ذخیره کرده است (`last_crc_offset` و `last_crc_val`). اگر seed فعلی با seed ذخیره‌شده فرق کند، به‌جای خواندن دوباره‌ی داده، اختلاف seed با کمک خطی بودن crc و تابع `ceph_crc32c_zeros` (crc یک ناحیه‌ی صفر به طول بازه) اصلاح می‌شود. هر تغییری در raw (مثلاً `copy_in` یا `zero`) این کش را با `invalidate_crc()` باطل می‌کند. این کار برای پیام‌هایی که چند بار با crc ارسال یا بررسی می‌شوند صرفه‌جویی بزرگی است.
:::

# mempool: حسابداری حافظه {#sec-23-4}

`src/include/mempool.h` با ماکرو `DEFINE_MEMORY_POOLS_HELPER` فهرست ثابتی از poolها تعریف می‌کند. هر allocator از نوع `mempool::<pool>::vector`، `map` و... تعداد بایت‌ها و آیتم‌ها را به‌صورت شاردشده (برای کاهش رقابت روی cache line) در همان pool ثبت می‌کند. `osd_memory_target` و autotune کش BlueStore بر اساس همین اعداد تصمیم می‌گیرند.

| pool | چه چیزی |
|---|---|
| bluestore_cache_onode / _meta / _data / _buffer / _other | اجزای کش BlueStore |
| bluestore_alloc | ساختارهای allocator |
| bluestore_extent / _blob / _shared_blob / _inline_bl | ساختارهای فراداده‌ی onode در حافظه |
| bluestore_txc / _writing / _writing_deferred | تراکنش‌ها و داده‌های در حال نوشتن |
| bluefs / bluefs_file_reader / bluefs_file_writer | BlueFS |
| buffer_anon / buffer_meta | bufferهای بدون pool مشخص و فراداده‌ی آن‌ها |
| osd / osd_mapbl / osd_pglog / osdmap / osdmap_mapping / pgmap | ساختارهای OSD و نقشه‌ها |

```bash
ceph tell osd.4 dump_mempools | jq '.mempool.by_pool | to_entries | sort_by(-.value.bytes) | .[:6]'
ceph tell osd.4 dump_mempools | jq '.mempool.total'
ceph config get osd.4 osd_memory_target          # پیش‌فرض 4_G
```

::: {.warn}
رشد بی‌رویه‌ی `buffer_anon` معمولاً به این معنی است که داده‌ی شبکه یا پیام‌ها در جایی نگه داشته شده‌اند (مثلاً صف‌های بزرگ op در یک OSD کند، یا کلاینت‌هایی که پاسخ نمی‌خوانند). رشد `osd_pglog` به طول بیش از حد pg log اشاره دارد (گزینه‌های `osd_min_pg_log_entries` و `osd_max_pg_log_entries`).
:::

# crc32c: از دستور CPU تا checksum بلوک {#sec-23-5}

Ceph از crc32c (چندجمله‌ای Castagnoli، به شکل معکوس 0x82F63B78) هم برای checksum داده در BlueStore و هم برای سلامت پیام در msgr2 استفاده می‌کند. `ceph_choose_crc32()` در `common/crc32c.cc` یک بار هنگام بارگذاری بهترین پیاده‌سازی را برای CPU انتخاب می‌کند.

![زنجیره‌ی انتخاب پیاده‌سازی crc32c و محل‌های استفاده. ترتیب بررسی چنین است: روی x86 ابتدا AVX512 همراه VPCLMULQDQ، سپس SSE4.2 (با یا بدون PCLMUL برای پردازش موازی سه جریان)، روی aarch64 دستورهای CRC32 و روی ppc، s390x و riscv نسخه‌های مخصوص. اگر هیچ‌کدام در دسترس نباشد، پیاده‌سازی جدولی نرم‌افزاری sctp استفاده می‌شود. این تابع در BlueStore برای هر chunk داده، در msgr2 حالت crc برای هر segment و preamble، و در bufferlist با کش crc روی raw به کار می‌رود](figures/ch23/f04_crc.png){#fig-23-f04_crc}

## یک مثال عددی {#sec-23-5-1}

`ceph_crc32c(seed, data, len)` **بدون** معکوس کردن نهایی کار می‌کند و BlueStore با seed برابر `-1` (0xFFFFFFFF) شروع می‌کند. برای رشته‌ی مرجع `"123456789"`:

| ورودی | seed | خروجی ceph_crc32c | پس از XOR نهایی با 0xFFFFFFFF |
|---|---|---|---|
| `"123456789"` (۹ بایت) | 0xFFFFFFFF | 0x1CF96D7C | 0xE3069283 (مقدار مرجع استاندارد CRC-32C) |
| ۴۰۹۶ بایت صفر | 0xFFFFFFFF | 0x6706BE76 | — |
| `"ceph"` | 0 | 0x575990D6 | — |

```python
# مثال خود این راهنما: crc32c بیت‌به‌بیت (کند، فقط برای فهم)
def crc32c(crc, data):
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ (0x82F63B78 if crc & 1 else 0)
    return crc
assert crc32c(0xFFFFFFFF, b"123456789") == 0x1CF96D7C
```

نسخه‌ی سخت‌افزاری همین کار را با دستور `crc32` در x86 (۸ بایت در هر دستور) و با سه جریان موازی ترکیب‌شده با PCLMULQDQ انجام می‌دهد. روی پردازنده‌های امروزی سرعت آن چند ده گیگابایت در ثانیه در هر هسته است، بنابراین checksum در عمل تقریباً رایگان است.

## checksum در BlueStore {#sec-23-5-2}

`Checksummer.h` انواع `CSUM_XXHASH32=2`، `CSUM_XXHASH64=3`، `CSUM_CRC32C=4`، `CSUM_CRC32C_16=5` (۱۶ بیت پایین) و `CSUM_CRC32C_8=6` را تعریف می‌کند و پیش‌فرض `bluestore_csum_type=crc32c` است. هر blob (فصل ۲۴) فیلدهای `csum_type`، `csum_chunk_order` (اندازه‌ی chunk برابر `1 << order` بایت) و `csum_data` (آرایه‌ی checksumها) دارد.

**حساب سربار:** با chunk ۴K و crc32c، هر ۴۰۹۶ بایت داده ۴ بایت checksum دارد، یعنی حدود ۰.۱٪. برای یک OSD با ۱۰ TiB داده، این حدود ۱۰ GiB checksum در onodeها است که بخشی از آن در کش onode قرار می‌گیرد. اگر chunk را بزرگ‌تر کنید (blobهای بزرگ و خواندن‌های ترتیبی، مثل RGW)، این سربار کم می‌شود ولی هر خواندن کوچک مجبور است کل chunk را بخواند تا آن را بررسی کند.

# libaio و io_uring در سطح ساختار و قفل {#sec-23-6}

بخش KernelDevice مسیر کلی را نشان داد. اینجا همان مسیر در سطح بایت‌ها، قفل‌ها و threadها دنبال می‌شود. KernelDevice در `KernelDevice::KernelDevice` بر اساس `bdev_ioring` (پیش‌فرض false) یکی از دو صف را می‌سازد: `aio_queue_t` (libaio) یا `ioring_queue_t` (io_uring). عمق صف در هر دو حالت `bdev_aio_max_queue_depth` (پیش‌فرض 1024) است.

![ساختار iocb شصت و چهار بایتی که aio_t در Ceph برای هر I/O پر می‌کند. نمونه یک pwritev با سه iovec و در مجموع 12 KiB در آفست 0x5A000 است. aio_data اشاره‌گر خود aio_t است و در io_event برمی‌گردد. با این اشاره‌گر، thread برداشت بدون جست‌وجو می‌فهمد کدام IOContext را باید کامل کند. در فرمان‌های برداری، aio_nbytes تعداد iovecهاست، نه طول بایتی](figures/ch23/f05_iocb.png){#fig-23-f05_iocb}

::: {.algo #alg-23-1 title="ارسال دسته‌ای libaio با عقب‌نشینی نمایی" src="src/blk/aio/aio.cc :: aio_queue_t::submit_batch" complexity="O(N/max_iodepth) فراخوانی io_submit در حالت عادی؛ در بدترین حالت 16 تلاش و حدود 8.2 ثانیه انتظار تجمعی"}
:::

```text
pseudocode
attempts = bdev_aio_submit_retry_max (16) ; delay = 125 µs
while کار باقی است:
    piocb[] را تا max_iodepth از فهرست پر کن
    r = io_submit(ctx, pulled − pushed, piocb + pushed)
    if 0 ≤ r < toSubmit: pushed += r ; r = −EAGAIN      # پذیرش جزئی
    if r == −EAGAIN and attempts−− > 0:
        usleep(delay) ; delay ×= 2 ; retries++ ; continue
    if r < 0: return r
    pushed = pulled = 0 ; attempts و delay را بازنشانی کن
```

**مثال عددی.** با 1024 درخواست معلق در صف هسته و یک دسته‌ی 64 تایی، io_submit ممکن است فقط 10 درخواست را بپذیرد. در این حالت pushed = 10، r به −EAGAIN تبدیل می‌شود و پس از 125 µs تلاش دوباره انجام می‌شود. اگر صف همچنان پر بماند، انتظارها 125، 250، 500 µs و همین‌طور دوبرابر می‌شوند تا 4.1 ثانیه برای تلاش شانزدهم. جمع کل 125 × (2^16 − 1) µs ≈ 8.19 ثانیه است. شمارنده‌ی retries در لاگ «aio_submit retries» دیده می‌شود. اگر این عدد در لاگ OSD زیاد دیده شود، عمق صف یا تأخیر دستگاه مشکل دارد، نه CPU.

![انتظار پیش از هر تلاش دوباره (میله‌ها، مقیاس لگاریتمی) و انتظار تجمعی (خط قرمز) وقتی io_submit پیوسته EAGAIN برمی‌گرداند. پس از 8 تلاش فقط 32 میلی‌ثانیه گذشته است، اما 8 تلاش آخر بیش از 8 ثانیه طول می‌کشند. پس یک اشباع کوتاه تقریباً نامرئی است و فقط اشباع طولانی به slow op تبدیل می‌شود](figures/ch23/f07_aioretry.png){#fig-23-f07_aioretry}

![ورودی صف ارسال io_uring که init_sqe در Ceph برای همان pwritev می‌سازد. opcode برابر IORING_OP_WRITEV (2) است. پرچم IOSQE_FIXED_FILE یعنی fd اندیسی در جدول فایل‌های ثبت‌شده است و هسته هزینه‌ی fget/fput را در هر I/O نمی‌پردازد. user_data همان اشاره‌گر aio_t است و در CQE شانزده بایتی برمی‌گردد](figures/ch23/f06_sqe.png){#fig-23-f06_sqe}

::: {.algo #alg-23-2 title="ارسال و برداشت io_uring با دو قفل و epoll" src="src/blk/kernel/io_uring.cc :: ioring_queue_t::submit_batch، ioring_queue، ioring_get_cqe، get_next_completed" complexity="ارسال O(N) نوشتن SQE و یک io_uring_submit؛ برداشت O(min(ready, reap_max)) بدون فراخوانی سیستمی وقتی CQE آماده است"}
:::

```text
pseudocode
submit_batch(beg, end):
    lock(sq_mutex)
    for io in [beg, end): sqe = io_uring_get_sqe() ; if null: break   # حلقه پر است
                          init_sqe(sqe, io)   # prep_writev/readv، FIXED_FILE، user_data=io
    rc = io_uring_submit()        # io_uring_enter، یا فقط به‌روزرسانی tail در SQPOLL
    unlock(sq_mutex) ; return rc
get_next_completed(timeout, paio[], max):
    lock(cq_mutex) ; for each cqe تا max: io.rval = cqe.res ; paio[n++] = io
    io_uring_cq_advance(n) ; unlock(cq_mutex)
    if n == 0: epoll_wait(ring_fd, timeout = bdev_aio_poll_ms) ؛ اگر آماده بود، دوباره برو
```

**مثال عددی و تفاوت با libaio.** با حلقه‌ی 1024 خانه‌ای، SQ برابر 1024 × 64 = 64 KiB و CQ (که هسته به‌طور پیش‌فرض دو برابر SQ می‌سازد) 2048 × 16 = 32 KiB است. هر دو با mmap بین هسته و Ceph مشترک‌اند. در libaio هر دسته دست‌کم یک io_submit و هر برداشت یک io_getevents دارد. در io_uring، وقتی CQE آماده است، برداشت فقط خواندن حافظه‌ی مشترک است. با `bdev_ioring_sqthread_poll=true` (پرچم IORING_SETUP_SQPOLL) ارسال هم فراخوانی سیستمی ندارد، اما یک thread هسته روی یک هسته‌ی CPU می‌چرخد. `bdev_ioring_hipri` پرچم IORING_SETUP_IOPOLL را می‌گذارد: کامل شدن با polling روی صف NVMe انجام می‌شود، و این فقط برای دستگاه‌هایی که poll queue دارند و با O_DIRECT کار می‌کند.

![مسیر کامل io_uring در KernelDevice. ارسال زیر sq_mutex انجام می‌شود، چون چند thread (تراکنش، deferred، BlueFS) هم‌زمان I/O می‌فرستند. برداشت در thread aio_thread زیر cq_mutex است. وقتی CQE آماده نیست، به جای مسدود شدن در io_uring_enter، روی ring_fd با epoll منتظر می‌ماند، و این همان الگوی زمان‌بندی bdev_aio_poll_ms در libaio را حفظ می‌کند](figures/ch23/f08_uring.png){#fig-23-f08_uring}

::: {.warn}
io_uring در Ceph به‌طور پیش‌فرض خاموش است و روی بعضی هسته‌ها و سیاست‌های امنیتی ممکن است غیرفعال یا محدود باشد (مثلاً sysctl `kernel.io_uring_disabled` در هسته‌های جدیدتر). `ioring_queue_t::supported()` با ساختن یک حلقه‌ی 16 تایی آزمایشی پشتیبانی را می‌سنجد. اگر شکست بخورد، OSD با هشدار به libaio برمی‌گردد.
:::

# رشد بافر در bufferlist::append {#sec-23-7}

::: {.algo #alg-23-3 title="رشد نمایی فضای الحاق" src="src/common/buffer.cc :: buffer::list::append(const char*, unsigned)، refill_append_space" complexity="O(1) سرشکن برای هر append کوچک؛ O(log(L/4K)) تخصیص تا سقف 256K و سپس L/256K تخصیص"}
:::

```text
pseudocode
append(data, len):
    first = min(len, فضای خالی انتهای _carriage)
    memcpy درون همان raw (برای طول ≤ 32 با کپی inline) ; _carriage.len += first
    if len − first > 0: refill_append_space(len − first).append(بقیه)
refill_append_space(len):
    alen = round_up(round_up(len, 8) + S, 4096)          # S = sizeof(raw_combined)
    if _carriage آخرین ptr است:
        alen = max(alen, min(2 × round_up(_carriage.raw_length, 4096), 256 KiB))
    raw_combined::create(alen − S) ← داده و سرآیند در یک تخصیص
```

**مثال عددی.** اگر encode یک ساختار 1 MiB داده را در قطعه‌های کوچک (مثلاً u64 و رشته‌های کوتاه) append کند، تخصیص‌ها 4K، 8K، 16K، 32K، 64K، 128K و سپس 256K هستند. پس از شش بافر اول 252K پر شده است و 772K باقی‌مانده به چهار بافر 256K دیگر می‌رود. نتیجه 10 ptr_node است، با جمع 1276 KiB تخصیص برای 1024 KiB داده، به جای 256 بافر 4K. سقف 256K عمداً زیر آستانه‌ی «شیء کوچک» tcmalloc است. هر raw_combined سرآیند کنترلی خود را در انتهای همان تخصیص دارد، پس هر بافر دقیقاً مضربی از 4K حافظه از allocator می‌گیرد.

![اندازه‌ی ده بافر raw_combined که refill_append_space هنگام append کردن یک مگابایت داده در قطعه‌های کوچک می‌سازد. اندازه‌ها از 4K دوبرابر می‌شوند تا به سقف 256K برسند. S اندازه‌ی سرآیند raw_combined است که از هر تخصیص کم می‌شود. فضای بلااستفاده‌ی انتهای بافر آخر دلیل اختلاف 1276 KiB تخصیص و 1024 KiB داده است](figures/ch23/f09_appendgrow.png){#fig-23-f09_appendgrow}

::: {.tip}
اگر اندازه‌ی نهایی از پیش معلوم است، `bl.reserve(n)` یا `bl.push_back(buffer::create(n))` همه‌ی این تخصیص‌های میانی را حذف می‌کند. در مسیرهای داغ Ceph، مثلاً encode پیام‌ها با `encode(..., features)` و پیش‌برآورد `bound_encode` در denc، از همین روش استفاده می‌شود.
:::

# crc32c برای صفرها و تطبیق seed {#sec-23-8}

`ceph_crc32c(crc, NULL, len)` در `include/crc32c.h` قرارداد ویژه‌ای دارد: اگر data تهی و len بزرگ‌تر از 16 باشد، crc یک ناحیه‌ی تماماً صفر حساب می‌شود، آن هم بدون خواندن حافظه. BlueStore و bufferlist از این برای ناحیه‌های صفر (`buffer::list::append_zero`، بافرهای raw_zeros) و برای تطبیق crc ذخیره‌شده استفاده می‌کنند.

::: {.algo #alg-23-4 title="crc32c صفرها با ماتریس‌های جهش" src="src/common/crc32c.cc :: ceph_crc32c_zeros، create_turbo_table (جدول crc_turbo_table[32][32])" complexity="O(log len) ضرب ماتریس 32×32 روی GF(2)، هر ضرب حداکثر 32 XOR؛ مستقل از طول (به جای O(len))"}
:::

```text
pseudocode
# M[0][bit] = crc(1≪bit، یک بایت صفر) ؛ M[r] = M[r−1]², یعنی جهش 2^r بایت
zeros(crc, len):
    rem = len & 15 ; n = len ≫ 4 ; r = 4                 # از جهش 16 بایتی شروع کن
    while n: if n & 1: crc = Σ_{bit j of crc = 1} M[r][j]   (XOR)
             n ≫= 1 ; r += 1
    if rem: crc = crc_معمولی(crc، rem بایت صفر)
```

**مثال عددی.** برای 4096 بایت صفر با seed = 0xFFFFFFFF: rem = 0 و n = 256 = 2^8، پس فقط یک ضرب با M[12] لازم است و نتیجه 0x6706BE76 است. محاسبه‌ی مستقیم بایت‌به‌بایت (پیاده‌سازی جداگانه‌ی این راهنما) همین عدد را می‌دهد. برای 69637 = 65536 + 4096 + 5 بایت: دو ضرب (M[16] و M[12]) و سپس 5 بایت معمولی، با نتیجه‌ی 0xAC433F9D که باز با محاسبه‌ی مستقیم یکی است. چهار مقدار اول ردیف M[0] (0xF26B8303، 0xE13B70F7، 0xC79A971F، 0x8AD958CF) همان مقادیر جدول crc_turbo_table در کد Ceph هستند.

::: {.algo #alg-23-5 title="تطبیق crc کش‌شده با seed تازه" src="src/common/buffer.cc :: buffer::list::crc32c؛ include/buffer_raw.h :: raw::get_crc، set_crc" complexity="O(log len) به جای O(len) برای هر raw که crc آن کش شده است"}
:::

```text
pseudocode
for node in _buffers:
    if raw.get_crc((off, off+len)) → (v, c):
        if v == crc: crc = c                                  # cache hit
        else: crc = c ⊕ ceph_crc32c(v ⊕ crc, NULL, len)       # adjust
    else: base = crc ; crc = ceph_crc32c(crc, data, len) ; raw.set_crc(..., (base, crc))
```

**مثال عددی.** برای یک بافر 1000 بایتی، crc با seed 0 برابر 0xACBE2A2C است و در raw کش می‌شود. اکنون همان بافر با seed 0xFFFFFFFF خواسته می‌شود. تطبیق 0xACBE2A2C ⊕ zeros(0 ⊕ 0xFFFFFFFF, 1000) = 0x8B0C0F84 می‌دهد، که دقیقاً crc مستقیم با seed جدید است. این همان جایی است که پیام‌رسان (msgr) و BlueStore یک بافر را دو بار با seedهای متفاوت checksum می‌کنند و بار دوم فقط چند ده XOR هزینه دارد. آمار آن با `buffer_track_crc` در شمارنده‌های `buffer_cached_crc` و `buffer_cached_crc_adjusted` دیده می‌شود.

![سه کاربرد ماتریس‌های جهش crc32c در Ceph. ردیف بالا الگوریتم ceph_crc32c_zeros است که طول را به توان‌های دو می‌شکند. ردیف میانی مثال 4096 بایت صفر است که با یک ضرب ماتریس حل می‌شود. ردیف پایین تطبیق crc کش‌شده در bufferlist است: به دلیل خطی بودن CRC، تفاوت دو seed معادل crc یک ناحیه‌ی صفر با seed برابر XOR آن دو است](figures/ch23/f10_crczeros.png){#fig-23-f10_crczeros}

# تکمیلی و به‌روز {#sec-23-9}

- در main، `block_device_t` فقط `aio` و `spdk` را دارد. پشتیبانی PMEM (دستگاه‌های DAX) در main حذف شده است، ولی Tentacle هنوز `block_device_t::pmem` را دارد. پیش از ارتقا، اگر از PMEM استفاده می‌کنید، یادداشت‌های انتشار را بررسی کنید.
- گزینه‌ی `bdev_async_discard` با `bdev_async_discard_threads` جایگزین شده است و کد برای سازگاری، مقدار قدیمی را به یک thread نگاشت می‌کند.
- io_uring همچنان به‌طور پیش‌فرض خاموش است (`bdev_ioring=false`).

# تمرین عملی {#sec-23-10}

1. روی یک OSD آزمایشی با `strace -c -f -p <pid>` در حین `rados bench` نسبت `io_submit` به `io_getevents` را بسنجید. سپس `bdev_ioring=true` را تنظیم کنید، OSD را راه‌اندازی دوباره کنید و تفاوت را با `ceph osd perf` مقایسه کنید.
2. تابع پایتون crc32c این فصل را اجرا کنید و نتیجه را برای یک بلوک ۴K تصادفی با `crcmod` یا `crc32c` پایتون مقایسه کنید (یادتان باشد XOR نهایی را اعمال کنید).
3. خروجی `dump_mempools` را قبل و بعد از یک `rados bench` بزرگ ذخیره و ۵ pool با بیشترین رشد را شناسایی کنید.
4. `cat /sys/block/<dev>/queue/write_cache` و `rotational` را برای همه‌ی دستگاه‌های OSD جمع کنید و با `ceph osd metadata` مقایسه کنید.

# پرسش‌های مرور {#sec-23-11}

1. چرا KernelDevice برای هر write hint یک fd جدا باز می‌کند؟
2. هم‌ترازی O_DIRECT چه محدودیتی بر کوچک‌ترین نوشتن BlueStore می‌گذارد؟
3. نقش `bdev_aio_max_queue_depth` و `bdev_aio_reap_max` چیست؟
4. چه زمانی BlueStore flush جداگانه‌ی دستگاه داده را اجباری می‌کند؟
5. چرا discard به‌طور پیش‌فرض خاموش است؟
6. تفاوت `buffer::ptr` و `buffer::raw` چیست؟
7. چرا `bufferlist::c_str()` می‌تواند گران باشد؟
8. mempool چگونه به autotune حافظه کمک می‌کند؟
9. چرا crc32c مقدار `"123456789"` در Ceph با مقدار مرجع استاندارد فرق دارد؟
10. سربار checksum با chunk ۴K چقدر است و بزرگ کردن chunk چه بده‌بستانی دارد؟

# منابع این فصل {#sec-23-12}

- کد KernelDevice: https://github.com/ceph/ceph/blob/main/src/blk/kernel/KernelDevice.cc
- libaio در Ceph: https://github.com/ceph/ceph/blob/main/src/blk/aio/aio.cc
- bufferlist: https://github.com/ceph/ceph/blob/main/src/include/buffer.h
- mempool: https://github.com/ceph/ceph/blob/main/src/include/mempool.h
- crc32c: https://github.com/ceph/ceph/blob/main/src/common/crc32c.cc
- پیکربندی BlueStore (checksum و فشرده‌سازی): https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- io_uring: https://kernel.dk/io_uring.pdf
- CRC-32C (RFC 3720، پیوست B.4): https://www.rfc-editor.org/rfc/rfc3720
