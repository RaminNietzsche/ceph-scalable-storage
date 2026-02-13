---
chapter: 12
id: ch12
title: "BlueStore: موتور ذخیره‌سازی OSD"
part: main
lang: fa
---

# پیش از شروع {#sec-12-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-12-1-1}

هر OSD در نهایت باید اشیای RADOS را روی یک دیسک فیزیکی بنویسد. لایه‌ای که این کار را انجام می‌دهد **object store** نام دارد. در سال ۲۰۱۹ BlueStore تازه پیش‌فرض شده بود و بسیاری از کلاسترها هنوز FileStore داشتند. امروز وضعیت ساده‌تر است: FileStore از Reef به بعد پشتیبانی نمی‌شود و BlueStore تنها object store کلاسیک OSD است. اما فهم درونی BlueStore هنوز برای طراحی سخت‌افزار، تنظیم کارایی و عیب‌یابی ضروری است.

- BlueStore چیست و چرا جایگزین FileStore شد؟
- RocksDB، BlueFS و نوشتن‌های deferred چه نقشی دارند؟
- دستگاه‌های block، block.db و block.wal را چطور اندازه‌گذاری و چیدمان کنیم؟
- فشرده‌سازی، checksum و min_alloc_size چه اثری دارند؟
- چطور OSDها را به BlueStore (یا به چیدمان جدید) مهاجرت دهیم؟
- آینده: crimson و SeaStore کجا هستند؟

# چرا BlueStore؟ {#sec-12-2}

## نیازهای Ceph از لایه‌ی ذخیره‌سازی {#sec-12-2-1}

OSD برای پیاده‌سازی تضمین‌های RADOS به چند قابلیت از لایه‌ی زیرین نیاز دارد:

- **تراکنش اتمی**: یک عملیات RADOS ممکن است داده، ویژگی‌ها (xattr) و omap را هم‌زمان تغییر دهد و همه باید با هم انجام شوند یا هیچ‌کدام.
- **فهرست‌گیری مرتب**: برای scrub و backfill باید اشیای هر PG را به ترتیب پیمایش کرد.
- **فراداده‌ی کلید-مقدار سریع** برای omap (که RGW برای شاخص bucketها و CephFS برای پوشه‌ها به شدت از آن استفاده می‌کنند).
- **checksum** برای تشخیص خرابی خاموش داده.

## محدودیت‌های FileStore {#sec-12-2-2}

FileStore هر شیء را به شکل یک فایل روی XFS ذخیره می‌کرد. چون فایل‌سیستم‌های POSIX تراکنش چندعملیاتی ندارند، FileStore برای اتمی بودن یک **journal** جدا داشت: هر نوشتن ابتدا کامل در journal و سپس در فایل‌سیستم نوشته می‌شد. پیامدها:

- **نوشتن دوباره**: هر بایت دو بار نوشته می‌شد، که توان مؤثر را تقریباً نصف می‌کرد.
- لایه‌های اضافه: cache صفحه‌ی هسته، XFS، xattrها و omap در LevelDB/RocksDB جدا، که رفتار را غیرقابل پیش‌بینی می‌کرد.
- فهرست‌گیری مرتب با پوشه‌های تودرتو و تقسیم آن‌ها، که در PGهای بزرگ کند بود.
- بدون checksum سرتاسری داده.

![مقایسه‌ی پشته‌ی FileStore و BlueStore: BlueStore فایل‌سیستم واسط و journal جدا را حذف می‌کند](figures/ch12/f01_stack.png){#fig-12-f01_stack}

## راه‌حل BlueStore {#sec-12-2-3}

BlueStore داده را **مستقیماً روی دستگاه بلوکی خام** می‌نویسد و فراداده را در RocksDB نگه می‌دارد. با این طراحی:

- برای نوشتن‌های بزرگ، داده یک بار نوشته می‌شود (در فضای تازه، به شیوه‌ی copy-on-write) و فقط فراداده در تراکنش RocksDB ثبت می‌شود.
- هر بلوک داده checksum دارد (پیش‌فرض crc32c) و هر خواندن بررسی می‌شود.
- فشرده‌سازی درون‌خطی (inline) در سطح pool یا OSD ممکن است.
- cache داده و فراداده در حافظه‌ی خود OSD مدیریت می‌شود و با `osd_memory_target` کنترل می‌شود.

# BlueStore چطور کار می‌کند؟ {#sec-12-3}

![اجزای درونی BlueStore: allocator برای داده، RocksDB برای فراداده و BlueFS به‌عنوان فایل‌سیستم کوچک RocksDB](figures/ch12/f02_internals.png){#fig-12-f02_internals}

## RocksDB {#sec-12-3-1}

RocksDB یک پایگاه داده‌ی کلید-مقدار مبتنی بر ساختار LSM است. BlueStore همه‌ی فراداده را در آن نگه می‌دارد: **onode** هر شیء (اندازه، نگاشت extentها، ویژگی‌ها)، omap، نقشه‌ی فضای آزاد (در برخی allocatorها) و log تراکنش‌ها. از Pacific، OSDهای تازه RocksDB را **sharded** می‌سازند: انواع مختلف کلید در column familyهای جدا قرار می‌گیرند تا compaction یک نوع کلید روی بقیه اثر نگذارد. OSDهای قدیمی‌تر را می‌توان با `ceph-bluestore-tool reshard` به چیدمان جدید برد.

::: {.note}
در Squid فشرده‌سازی **LZ4 برای RocksDB** به‌طور پیش‌فرض فعال شد. این کار حجم DB را کم می‌کند و به‌ویژه در کلاسترهای RGW با omap سنگین، احتمال سرریز DB از SSD به HDD را پایین می‌آورد.
:::

## BlueFS {#sec-12-3-2}

RocksDB برای کار به یک فایل‌سیستم نیاز دارد (فایل‌های SST و WAL خود را می‌نویسد). به جای XFS، BlueStore یک فایل‌سیستم بسیار کوچک و مخصوص به نام **BlueFS** دارد که فقط همین چند نوع فایل را پشتیبانی می‌کند. BlueFS می‌تواند روی سه دستگاه پخش شود:

| دستگاه | محتوا | سخت‌افزار مناسب |
|---|---|---|
| block | داده‌ی اشیا (و در صورت نبود دستگاه دیگر، همه‌چیز) | HDD یا SSD اصلی |
| block.db | فایل‌های RocksDB (و WAL اگر دستگاه wal جدا نباشد) | SSD یا NVMe سریع |
| block.wal | فقط WAL RocksDB | سریع‌ترین دستگاه؛ فقط وقتی سریع‌تر از db باشد |

::: {.deep}
اگر block.db پر شود، BlueFS بقیه‌ی فایل‌های RocksDB را روی دستگاه block (معمولاً HDD کند) می‌نویسد. این **سرریز** (spillover) کارایی فراداده را ناگهان پایین می‌آورد و با هشدار `BLUEFS_SPILLOVER` گزارش می‌شود. نکته‌ی ظریف این است که RocksDB فایل‌ها را در سطوح (level) با اندازه‌های تصاعدی نگه می‌دارد و یک سطح کامل یا روی DB می‌رود یا نمی‌رود؛ پس فضای DB بین آستانه‌های سطح‌ها ممکن است بی‌استفاده بماند.
:::

## نوشتن‌های deferred {#sec-12-3-3}

![دو مسیر نوشتن در BlueStore: نوشتن‌های کوچک ابتدا در WAL ثبت و بعداً اعمال می‌شوند؛ نوشتن‌های بزرگ مستقیماً در فضای تازه نوشته می‌شوند](figures/ch12/f03_write.png){#fig-12-f03_write}

برای HDD، نوشتن تصادفی کوچک گران است (هر نوشتن یک seek). BlueStore نوشتن‌های کوچک‌تر از یک آستانه را **deferred** می‌کند: داده همراه فراداده در WAL RocksDB (که معمولاً روی SSD است) ثبت می‌شود، به کلاینت ack داده می‌شود و بعداً در پس‌زمینه روی HDD اعمال می‌شود. نوشتن‌های بزرگ‌تر مستقیماً در فضای آزاد block نوشته می‌شوند و فقط فراداده در RocksDB commit می‌شود. آستانه‌ها با `bluestore_prefer_deferred_size_hdd` و `_ssd` تنظیم می‌شوند و جریان این نوشتن‌ها با `bluestore_throttle_deferred_bytes` محدود می‌شود.

::: {.tip}
همین سازوکار دلیل اصلی ارزش داشتن SSD برای block.db در OSDهای HDD است: نه فقط فراداده، بلکه نوشتن‌های کوچک هم ابتدا روی SSD می‌روند. اما SSD باید **حفاظت در برابر قطع برق** داشته باشد؛ وگرنه نوشتن‌های sync در WAL کند می‌شوند و مزیت از بین می‌رود (فصل ۱۰).
:::

# استفاده از BlueStore {#sec-12-4}

## چیدمان دستگاه‌ها {#sec-12-4-1}

![چیدمان رایج گره ترکیبی: هر NVMe چند LV برای block.db چند OSD HDD فراهم می‌کند](figures/ch12/f04_devices.png){#fig-12-f04_devices}

در cephadm، OSDها با ابزار `ceph-volume` و روی LVM ساخته می‌شوند. چیدمان را در spec OSD تعیین می‌کنید (فصل ۱۱)؛ cephadm فضای دستگاه سریع را به‌طور مساوی بین OSDهای آن گره تقسیم می‌کند. سه الگوی رایج:

| الگو | چیدمان | کاربرد |
|---|---|---|
| همه‌روی‌یک | block، db و wal روی یک SSD یا NVMe | کلاسترهای تمام‌فلش |
| ترکیبی | block روی HDD، db (و wal همراهش) روی SSD/NVMe مشترک | ظرفیت بالا با هزینه‌ی کم؛ RBD و RGW |
| سه‌لایه | block روی HDD، db روی SSD، wal روی NVMe یا Optane | نادر؛ فقط وقتی دستگاه wal واقعاً سریع‌تر است |

::: {.warn}
در الگوی ترکیبی، از دست رفتن دستگاه db یعنی از دست رفتن **همه‌ی OSDهایی** که db آن‌ها روی آن است. اگر یک NVMe پشتیبان db دوازده HDD باشد، خرابی آن هم‌ارز خرابی دوازده OSD است. نسبت OSD به هر دستگاه db را طوری انتخاب کنید که این دامنه‌ی خرابی با طراحی CRUSH و ظرفیت بازیابی سازگار باشد؛ معمولاً حداکثر ۴ تا ۶ HDD به‌ازای هر SSD SATA و بیشتر برای NVMe.
:::

## اندازه‌ی block.db {#sec-12-4-2}

مستندات جاری (پس از فعال شدن فشرده‌سازی RocksDB در Squid) توصیه می‌کند block.db دست‌کم **۲.۵ درصد** اندازه‌ی دستگاه block باشد. برای نسخه‌های قدیمی‌تر و بارهای سنگین omap (RGW) عدد ۴ درصد ذکر شده و برای RBD اغلب ۱ تا ۲ درصد کافی است. مثال: HDD هجده ترابایتی برای RGW به حدود ۴۵۰ تا ۷۲۰ گیگابایت db نیاز دارد.

```bash
ceph osd metadata 3 | jq '{bluefs_dedicated_db, bluefs_db_size, devices}'
ceph tell osd.3 bluefs stats
ceph health detail | grep -i spillover
```

## min_alloc_size {#sec-12-4-3}

`bluestore_min_alloc_size` کوچک‌ترین واحد تخصیص روی دستگاه است و **فقط هنگام ساخت OSD** ثابت می‌شود. پیش‌فرض‌ها در کد جاری (`src/common/options/global.yaml.in`) برای HDD و SSD هر دو `4_K` است. سیر تغییر: تا Mimic، ۶۴ کیلوبایت برای HDD و ۱۶ کیلوبایت برای SSD؛ Octopus SSD را به ۴ و Pacific HDD را به ۴ کیلوبایت رساند. انگیزه، **تقویت فضا** (space amplification) در RGW با اشیای کوچک بود: یک شیء ۱ کیلوبایتی با واحد ۶۴ کیلوبایت، ۶۳ کیلوبایت هدر می‌داد.

::: {.note}
OSDهایی که پیش از Pacific ساخته شده‌اند هنوز مقدار قدیمی دارند، حتی پس از ارتقای نرم‌افزار. با `ceph osd metadata <id> | jq .bluestore_min_alloc_size` بررسی کنید. تنها راه تغییر، ساختن دوباره‌ی OSD است.
:::

## فشرده‌سازی و checksum {#sec-12-4-4}

```bash
ceph osd pool set rgw-data compression_algorithm zstd     # یا lz4، snappy، zlib
ceph osd pool set rgw-data compression_mode aggressive    # none، passive، aggressive، force
ceph osd pool set rgw-data compression_required_ratio 0.875
ceph df detail | grep -E 'POOL|rgw-data'                   # ستون‌های USED COMPR و UNDER COMPR
```

| حالت | رفتار |
|---|---|
| none | هرگز فشرده نکن |
| passive | فقط وقتی کلاینت اشاره‌ی «قابل فشرده‌سازی» بدهد |
| aggressive | فشرده کن مگر کلاینت بگوید «غیرقابل فشرده‌سازی» |
| force | همیشه تلاش کن |

فشرده‌سازی فقط وقتی نگه داشته می‌شود که نسبت اندازه‌ی فشرده به اصلی از `compression_required_ratio` کمتر باشد. checksum پیش‌فرض `crc32c` است؛ گزینه‌های `crc32c_16`، `crc32c_8`، `xxhash32` و `xxhash64` هم وجود دارند. checksumهای کوتاه‌تر حافظه‌ی فراداده را کم می‌کنند اما قدرت تشخیص خطا را هم پایین می‌آورند.

# مهاجرت و نگهداری OSDها {#sec-12-5}

![مهاجرت OSD به OSD به چیدمان جدید: تخلیه یا جایگزینی، پاک‌سازی، ساخت دوباره و backfill](figures/ch12/f05_migrate.png){#fig-12-f05_migrate}

## از FileStore به BlueStore {#sec-12-5-1}

اگر هنوز OSD FileStore دارید، پیش از ارتقا به Reef یا بالاتر باید آن‌ها را تبدیل کنید. تبدیل درجا وجود ندارد؛ روش، **ساختن دوباره‌ی OSD** است. دو راهبرد مستند:

- **جایگزینی OSD به OSD**: هر OSD را با `ceph orch osd rm <id> --replace --zap` حذف کنید تا با همان id و این بار BlueStore ساخته شود. ساده اما هر OSD دو بار جابه‌جایی داده دارد.
- **جایگزینی میزبان به میزبان**: یک میزبان خالی را BlueStore کنید، داده‌ی یک میزبان FileStore را به آن منتقل کنید، و میزبان آزادشده را برای دور بعد استفاده کنید. جابه‌جایی کمتر، اما به یک میزبان اضافه نیاز دارد.

## افزودن یا جابه‌جا کردن DB {#sec-12-5-2}

اگر OSD را بدون db ساخته‌اید و بعداً SSD اضافه کرده‌اید، یا dbها کوچک بوده‌اند، `ceph-volume lvm new-db` و `ceph-volume lvm migrate` بدون ساختن دوباره‌ی OSD این کار را انجام می‌دهند (OSD باید متوقف باشد):

```bash
ceph orch daemon stop osd.7
cephadm shell --name osd.7
ceph-volume lvm new-db --osd-id 7 --osd-fsid <fsid> --target vg_nvme/db_osd7
ceph-volume lvm migrate --osd-id 7 --osd-fsid <fsid> --from data --target vg_nvme/db_osd7
exit
ceph orch daemon start osd.7
```

## ابزار ceph-bluestore-tool {#sec-12-5-3}

```bash
ceph-bluestore-tool show-label --dev /dev/ceph-vg/osd-block-xxxx
ceph-bluestore-tool fsck --path /var/lib/ceph/osd/ceph-7 --deep
ceph-bluestore-tool bluefs-bdev-sizes --path /var/lib/ceph/osd/ceph-7
ceph-bluestore-tool bluefs-bdev-expand --path /var/lib/ceph/osd/ceph-7   # پس از بزرگ کردن LV
ceph-bluestore-tool reshard --path /var/lib/ceph/osd/ceph-7 --sharding "<spec>"
```

::: {.warn}
همه‌ی این دستورها فقط روی OSD **متوقف** اجرا می‌شوند. `repair` و `reshard` فراداده را تغییر می‌دهند؛ ابتدا `fsck` بگیرید و مطمئن شوید PGهای آن OSD نسخه‌ی سالم در جای دیگر دارند (`ceph osd ok-to-stop`).
:::

# BlueStore با عدد: آزمون پذیرش فشرده‌سازی، اثر min_alloc_size و اندازه‌ی سطح‌های RocksDB {#sec-12-6}

سه محاسبه‌ی این بخش، با پیش‌فرض‌های main در نوامبر 2026، به سه پرسش رایج جواب می‌دهند: چرا فشرده‌سازی روی بعضی OSDها هیچ اثری ندارد، چرا اشیای کوچک فضای خام زیادی مصرف می‌کنند، و block.db چقدر باید باشد. مسیر نوشتن deferred و autotune حافظه در فصل 21 و allocator در فصل 24 آمده‌اند.

## آزمون پذیرش فشرده‌سازی {#sec-12-6-1}

::: {.algo #alg-12-1 title="پذیرفتن یا رد کردن blob فشرده" src="src/os/bluestore/BlueStore.cc :: BlueStore::_do_alloc_write (want_len، result_len)" complexity="O(طول blob) برای فشرده‌سازی و O(1) برای آزمون"}
:::

```text
pseudocode
crr = compression_required_ratio در pool یا bluestore_compression_required_ratio (0.875)
want   = p2roundup(blob_length × crr, min_alloc_size)
result = p2roundup(compressed_len, min_alloc_size)
if result ≤ want و result < blob_length:
    سرآیند فشرده‌سازی را اضافه کن و آزمون را تکرار کن ؛ در صورت موفقیت تا min_alloc پر کن
else: ذخیره‌ی بدون فشرده‌سازی (شمارنده‌ی compress_rejected_count)
اندازه‌ی blob فشرده: bluestore_compression_min/max_blob_size_{hdd,ssd} (هر دو 64K در main)
```

**مثال عددی (blob ‏64 KiB).** با min_alloc_size برابر 4K، ‏want = 56 KiB است. اگر فشرده‌ی blob ‏50 KiB شود، result = 52 KiB پذیرفته می‌شود و 12 KiB صرفه‌جویی دارد. 57.5 KiB پذیرفته نمی‌شود، چون به 60 KiB گرد می‌شود. با min_alloc_size برابر 64K، که پیش‌فرض HDD پیش از Pacific بود و پس از ساخت OSD قابل تغییر نیست، ‏want = 64 KiB است و result حتی برای یک blob ‏30 KiB هم 64 KiB می‌شود. شرط «result < blob» هیچ‌وقت برقرار نمی‌شود، پس **روی چنین OSDی با blobهای 64 KiB فشرده‌سازی هرگز صرفه‌جویی نمی‌کند**. نشانه‌اش این است که در `ceph df detail` ستون USED COMPR صفر می‌ماند و شمارنده‌ی compress_rejected بالا می‌رود. علاج آن ساختن دوباره‌ی OSD است، یا بزرگ کردن compression_max_blob_size، که هزینه‌ی خواندن تصادفی را بالا می‌برد.

![فضای تخصیص‌یافته برای یک blob ‏64 KiB برحسب طول فشرده‌ی آن. چپ: با min_alloc_size برابر 4K، پله‌ها تا 56 KiB صرفه‌جویی واقعی می‌دهند و بالاتر از آن blob بدون فشرده‌سازی ذخیره می‌شود. راست: با 64K، همیشه 64 KiB تخصیص می‌یابد و فشرده‌سازی بی‌اثر است. خط‌چین قرمز آستانه‌ی پذیرش است](figures/ch12/f08_compress.png){#fig-12-f08_compress}

![مسیر فشرده‌سازی در نوشتن BlueStore: فشرده‌سازی blob، محاسبه‌ی want، آزمون دومرحله‌ای (پیش و پس از افزودن سرآیند)، پر کردن تا min_alloc و ثبت در statfs که ستون‌های USED COMPR و UNDER COMPR در ceph df از آن ساخته می‌شوند](figures/ch12/f11_compflow.png){#fig-12-f11_compflow}

## min_alloc_size و اشیای کوچک {#sec-12-6-2}

::: {.algo #alg-12-2 title="فضای تخصیص‌یافته برای یک شیء" src="src/os/bluestore/BlueStore.cc (min_alloc_size ثبت‌شده در superblock هنگام mkfs)؛ پیش‌فرض‌های bluestore_min_alloc_size_{hdd,ssd} = 4K در main" complexity="O(1)"}
:::

```text
pseudocode
allocated(size) = p2roundup(size, min_alloc_size)            # برای هر replica یا هر shard
amplification = allocated / size
در EC: هر shard جداگانه گرد می‌شود ← shard = ceil(size / k) گرد به min_alloc
```

**مثال عددی.** شیء 1 KiB با min_alloc 4K، چهار برابر فضا مصرف می‌کند و با 64K شصت‌وچهار برابر. شیء 10 KiB به ترتیب 1.2 و 6.4 برابر مصرف دارد. برای 100 میلیون شیء ده‌کیلوبایتی (مثلاً thumbnailهای RGW)، مصرف هر replica با 4K حدود 1.12 TiB و با 64K حدود 5.96 TiB است. در pool سه‌نسخه‌ای این اختلاف به 14.5 TiB خام می‌رسد. در EC اثر بدتر است: همان شیء 10 KiB در 4+2، شش shard می‌سازد که هر کدام به 4K گرد می‌شوند، یعنی 24 KiB خام برای 10 KiB داده. نسخه‌ی min_alloc_size هر OSD با `ceph osd metadata <id> | grep min_alloc` دیده می‌شود.

![نسبت فضای تخصیص‌یافته به اندازه‌ی منطقی شیء برای سه مقدار min_alloc_size. برای اشیای بزرگ‌تر از چند ده کیلوبایت اختلاف ناچیز است، اما برای اشیای چندکیلوبایتی مصرف چند ده برابر می‌شود](figures/ch12/f09_minalloc.png){#fig-12-f09_minalloc}

## اندازه‌ی سطح‌های RocksDB و block.db {#sec-12-6-3}

::: {.algo #alg-12-3 title="هدف اندازه‌ی سطح‌ها با گزینه‌های پیش‌فرض" src="src/common/options/global.yaml.in :: bluestore_rocksdb_options (max_bytes_for_level_base = 1 GiB، max_bytes_for_level_multiplier = 8)" complexity="O(تعداد سطح‌ها)"}
:::

```text
pseudocode
target(L1) = 1 GiB ؛ target(Ln) = target(Ln−1) × 8
cumulative(Ln) = Σ target(L1..Ln)  ← 1، 9، 73، 585 GiB
یک سطح فقط وقتی کامل روی دستگاه سریع می‌ماند که فضای آن برای همه‌ی سطح‌های پایین‌تر کافی باشد
افزون بر آن: L0 (تا 8 فایل memtable ‏16 MiB پیش از compaction) و WAL (max_total_wal_size = 1 GiB)
```

**نتیجه.** با سطح‌بندی ایستا، block.db حدود 10 GiB فقط تا L2 را نگه می‌دارد و حدود 75 تا 80 GiB تا L3 را. هر چیزی بین این دو مقدار در عمل به همان اندازه‌ی کوچک‌تر کار می‌کند، چون سطح بعدی جا نمی‌شود و به دستگاه کند می‌ریزد (هشدار BLUEFS_SPILLOVER). این اعداد فرض «سطح‌بندی ایستا» دارند. نسخه‌های تازه‌ی RocksDB گزینه‌ی level_compaction_dynamic_level_bytes را به‌طور پیش‌فرض روشن کرده‌اند. ‏BlueFS هم در main با bluestore_volume_selection_policy مقداری فضای اضافه را مدیریت می‌کند. پس این جدول راهنمای نقطه‌ی آغاز است، نه قانون. برای اطمینان، خروجی `ceph daemon osd.N bluefs stats` را روی یک OSD پرکار بررسی کنید.

![اندازه‌ی هدف سطح‌های L1 تا L4 در RocksDB با گزینه‌های پیش‌فرض BlueStore (ستون‌ها) و مجموع تجمعی آن‌ها (خط قرمز) روی محور لگاریتمی. هر پله‌ی تجمعی اندازه‌ای از block.db است که سطح بعدی را کامل جا می‌دهد. L0 و WAL حدود 1 GiB هر کدام اضافه می‌کنند](figures/ch12/f10_levels.png){#fig-12-f10_levels}

# از درون کد: BlueStore {#sec-12-7}

این بخش BlueStore را از روی کد منبع Ceph (شاخه‌ی main، مخزن `ceph/ceph`، نسخه‌ی تاریخ ۲۳ آبان ۱۴۰۵) بررسی می‌کند. نام فایل‌ها و توابع را می‌آوریم تا خودتان بتوانید دنبال کنید. رفتار ممکن است بین نسخه‌ها فرق کند؛ هر جا که مهم است، نسخه را ذکر کرده‌ایم.

## نقشه‌ی فایل‌ها {#sec-12-7-1}

| فایل در src/os/bluestore | مسئولیت |
|---|---|
| BlueStore.cc / .h | پیاده‌سازی ObjectStore: تراکنش‌ها، خواندن و نوشتن، cache، mount/fsck |
| BlueStore_components.h | ساختارهای TransContext، Onode، Blob، ExtentMap و حالت‌های txc |
| Writer.cc | منطق نوشتن جدید (تصمیم deferred یا مستقیم، تقسیم به blobها) |
| BlueFS.cc / bluefs_types.h | فایل‌سیستم کوچک RocksDB و log آن |
| BlueRocksEnv.cc | پل RocksDB به BlueFS (پیاده‌سازی rocksdb::Env) |
| HybridAllocator*, AvlAllocator*, BitmapAllocator*, Btree2Allocator* | تخصیص‌دهنده‌های فضای آزاد |
| BitmapFreelistManager.cc | ذخیره‌ی پایدار نقشه‌ی فضای آزاد در KV |
| bluestore_types.h | ساختارهای روی‌دیسک: bluestore_onode_t، bluestore_blob_t، pextent |
| bluestore_tool.cc | ابزار ceph-bluestore-tool |

## فضای کلید RocksDB {#sec-12-7-2}

![پیشوندهای کلید BlueStore در RocksDB و column familyهای پیش‌فرض. هر نوع فراداده با یک پیشوند تک‌حرفی از بقیه جدا می‌شود؛ تنظیم bluestore_rocksdb_cfs برخی از این پیشوندها را در column familyهای جدا و shardشده قرار می‌دهد](figures/ch12/f07_kv.png){#fig-12-f07_kv}

BlueStore همه‌ی فراداده را در یک پایگاه کلید-مقدار نگه می‌دارد و انواع آن را با یک **پیشوند** از هم جدا می‌کند. تعریف‌ها در ابتدای `BlueStore.cc` آمده‌اند:

```cpp
// from ceph/ceph, LGPL — src/os/bluestore/BlueStore.cc (excerpt)
const std::string PREFIX_SUPER = "S";       // field -> value
const std::string PREFIX_COLL = "C";        // collection name -> cnode_t
const std::string PREFIX_OBJ = "O";         // object name -> onode_t
const std::string PREFIX_OMAP = "M";        // u64 + keyname -> value
const std::string PREFIX_PERPOOL_OMAP = "m"; // s64 + u64 + keyname -> value
const std::string PREFIX_PERPG_OMAP = "p";   // u64(pool) + u32(hash) + u64(id) + keyname -> value
const std::string PREFIX_DEFERRED = "L";    // id -> deferred_transaction_t
const std::string PREFIX_ALLOC = "B";       // u64 offset -> u64 length (freelist)
const std::string PREFIX_SHARED_BLOB = "X"; // u64 SB id -> shared_blob_t
```

سه نسل omap در این فهرست دیده می‌شود: `M` (قدیمی، یک فضای مشترک)، `m` (per-pool، تا آمار omap هر pool دقیق باشد) و `p` (per-PG، تا حذف یا انتقال یک PG با یک بازه‌ی پیوسته از کلیدها انجام شود). OSDهای قدیمی پس از ارتقا هشدار `BLUESTORE_NO_PER_POOL_OMAP` یا `BLUESTORE_NO_PER_PG_OMAP` می‌دهند تا با fsck/repair تبدیل شوند.

پیش‌فرض column familyها در کد جاری:

```text
bluestore_rocksdb_cfs = m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru}
                        L=min_write_buffer_number_to_merge=32 P=min_write_buffer_number_to_merge=32
```

عدد داخل پرانتز تعداد shard است و بازه‌ی بعدی، بایت‌هایی از کلید که برای hash استفاده می‌شوند. مثلاً `O(3,0-13)` یعنی onodeها در سه column family پخش می‌شوند. هدف این است که compaction یک نوع کلید (مثلاً omapهای پرحجم RGW) کل پایگاه را قفل نکند. تنظیمات RocksDB هم در `bluestore_rocksdb_options` است که در کد جاری با `compression=kLZ4Compression` شروع می‌شود (همان تغییر Squid).

## Onode، ExtentMap و Blob {#sec-12-7-3}

![ساختار فراداده‌ی یک شیء: Onode نگاشت منطقی را در ExtentMap نگه می‌دارد؛ هر Extent به یک Blob اشاره می‌کند که checksum و فشرده‌سازی و محل فیزیکی (pextent) را دارد؛ Blobهای مشترک بین cloneها با SharedBlob مدیریت می‌شوند](figures/ch12/f08_onode.png){#fig-12-f08_onode}

- **Onode** نمایش در حافظه‌ی `bluestore_onode_t` است. فیلدهای اصلی آن: `nid` (شناسه‌ی عددی محلی)، `size`، `attrs` (xattrها)، `extent_map_shards` و اشاره‌های تخصیص (`expected_object_size`، `alloc_hint_flags`).
- **ExtentMap** نگاشت offset منطقی شیء به Extentهاست. برای اشیای بزرگ، این نقشه به **shard**هایی تقسیم و هر shard جداگانه در KV ذخیره می‌شود تا تغییر کوچک در یک شیء ۴ مگابایتی نیازمند بازنویسی کل نقشه نباشد.
- **Blob** واحد checksum و فشرده‌سازی است و فهرست pextentها (offset و طول فیزیکی روی block) را دارد.
- **SharedBlob** وقتی ساخته می‌شود که دو شیء (مثلاً یک شیء و clone snapshot آن) یک Blob را به اشتراک بگذارند؛ شمارش ارجاع آن زیر پیشوند `X` ذخیره می‌شود.

**cache**: Onodeها و بافرهای داده در cache جداگانه‌ای نگه داشته می‌شوند که با `bluestore_cache_autotune=true` (پیش‌فرض) و هدف کلی `osd_memory_target` (پیش‌فرض `4_G` در کد) بین onode، داده و cache بلوک RocksDB تقسیم می‌شود.

## چرخه‌ی عمر یک تراکنش {#sec-12-7-4}

![ماشین حالت TransContext در BlueStore. ردیف اول: نوشتن داده با aio؛ ردیف دوم: commit فراداده در RocksDB توسط kv_sync_thread، که در آن OSD تأیید commit را می‌گیرد؛ ردیف سوم: اعمال نوشتن‌های deferred روی دستگاه و پاک کردن رکورد آن‌ها](figures/ch12/f06_txc.png){#fig-12-f06_txc}

هر تراکنش ObjectStore که OSD با `queue_transactions()` می‌فرستد یک **TransContext** (txc) می‌سازد. حالت‌ها در `BlueStore_components.h` تعریف شده‌اند:

```cpp
// from ceph/ceph, LGPL — src/os/bluestore/BlueStore_components.h (excerpt)
typedef enum {
  STATE_PREPARE,
  STATE_AIO_WAIT,
  STATE_IO_DONE,
  STATE_KV_QUEUED,     // queued for kv_sync_thread submission
  STATE_KV_SUBMITTED,  // submitted to kv; not yet synced
  STATE_KV_DONE,
  STATE_DEFERRED_QUEUED,    // in deferred_queue (pending or running)
  STATE_DEFERRED_CLEANUP,   // remove deferred kv record
  STATE_DEFERRED_DONE,
  STATE_FINISHING,
  STATE_DONE,
} state_t;
```

پیشروی بین این حالت‌ها در `BlueStore::_txc_state_proc()` انجام می‌شود؛ یک حلقه‌ی `while(true)` با `switch` روی حالت فعلی. روند به زبان ساده:

1. **PREPARE**: `_txc_add_transaction` عملیات را پردازش می‌کند؛ برای داده‌ی مستقیم، فضای تازه تخصیص و aio ثبت می‌شود؛ برای deferred، داده در یک `bluestore_deferred_transaction_t` قرار می‌گیرد.
2. **AIO_WAIT → IO_DONE**: منتظر پایان نوشتن داده روی block. ترتیب commit در هر collection (PG) حفظ می‌شود.
3. **KV_QUEUED → KV_SUBMITTED → KV_DONE**: thread اختصاصی `_kv_sync_thread()` تراکنش‌های آماده را دسته‌ای (batch) به RocksDB می‌فرستد و یک sync مشترک انجام می‌دهد. پس از sync، callback `on_commit` اجرا و OSD مطلع می‌شود که داده پایدار است. همین‌جا OSD می‌تواند به primary یا کلاینت ack دهد.
4. **DEFERRED_***: اگر txc نوشتن deferred داشت، داده اکنون از WAL به جای واقعی‌اش روی block نوشته می‌شود (`_deferred_queue`، دسته‌ای و مرتب‌شده بر اساس offset تا HDD کمتر seek کند) و سپس کلید `L` حذف می‌شود.

::: {.deep}
چرا ack پس از KV_DONE ایمن است، حتی وقتی داده‌ی deferred هنوز روی block نیامده؟ چون خود داده همراه رکورد `L` در WAL RocksDB پایدار شده است. اگر OSD پیش از اعمال deferred خاموش شود، هنگام mount تابع `_deferred_replay()` همه‌ی کلیدهای `L` را می‌خواند و دوباره اعمال می‌کند. نوشتن مستقیم هم ایمن است چون در فضای **تازه** نوشته می‌شود و تا commit فراداده، هیچ اشاره‌ای به آن نیست؛ اگر خرابی رخ دهد، نسخه‌ی قبلی شیء دست‌نخورده است.
:::

## تصمیم deferred یا مستقیم {#sec-12-7-5}

در مسیر نوشتن جدید (`Writer.cc`)، تابع `BlueStore::Writer::_defer_or_allocate()` تصمیم می‌گیرد:

```cpp
// from ceph/ceph, LGPL — src/os/bluestore/Writer.cc (excerpt)
uint32_t released_size = 0;
for (const auto& r : released) {
  released_size += r.length;
}
uint32_t au_size = bstore->min_alloc_size;
do_deferred = need_size <= released_size && released_size < bstore->prefer_deferred_size;
```

یعنی نوشتن وقتی deferred می‌شود که (۱) بتواند در همان فضایی نوشته شود که با این نوشتن آزاد می‌شود (بازنویسی درجا) و (۲) این فضا کوچک‌تر از `prefer_deferred_size` باشد. پیش‌فرض‌ها در کد جاری: `bluestore_prefer_deferred_size_hdd = 64_K` و `bluestore_prefer_deferred_size_ssd = 0` (روی SSD عملاً deferred استفاده نمی‌شود، چون نوشتن تصادفی ارزان است). کامنت بالای این تابع هم یادآوری می‌کند که اجرای بخشی از یک نوشتن به‌صورت deferred و بخش دیگر مستقیم، در هر حال بهینه نیست؛ پس تصمیم برای کل نوشتن یکجا گرفته می‌شود.

## تخصیص‌دهنده‌ی فضای آزاد {#sec-12-7-6}

![HybridAllocator: بازه‌های آزاد ابتدا در درخت AVL نگه داشته می‌شوند که جست‌وجوی سریع دارد؛ وقتی حافظه‌ی مجاز درخت پر شود، بازه‌های اضافی به BitmapAllocator سرریز می‌شوند که حافظه‌ی ثابت و کمی مصرف می‌کند](figures/ch12/f09_hybrid.png){#fig-12-f09_hybrid}

پیش‌فرض `bluestore_allocator` در کد جاری `hybrid` است. `HybridAllocator` (فایل `HybridAllocator.h`) ترکیبی از `AvlAllocator` و `BitmapAllocator` است: درخت AVL بازه‌های آزاد را بر اساس offset و اندازه نگه می‌دارد و تخصیص بازه‌های پیوسته را سریع می‌کند، اما حافظه‌اش با تعداد بازه‌ها رشد می‌کند. وقتی دیسک تکه‌تکه (fragmented) شود و تعداد بازه‌ها از سقف حافظه بگذرد، `_spillover_range()` بازه‌ها را به بیت‌مپ منتقل می‌کند. پیامد عملی: روی OSDهای بسیار تکه‌تکه، تخصیص کندتر می‌شود. شاخص تکه‌تکگی را ببینید:

```bash
ceph tell osd.3 bluestore allocator score block
ceph tell osd.3 bluestore allocator fragmentation histogram block
```

::: {.note}
نقشه‌ی فضای آزاد روی دیسک (`BitmapFreelistManager` زیر پیشوندهای `B`/`b`) جدا از تخصیص‌دهنده‌ی در حافظه است. در نسخه‌های جدید، BlueStore می‌تواند به جای به‌روزرسانی freelist در هر تراکنش، وضعیت تخصیص را هنگام خاموشی تمیز ذخیره کند و پس از خاموشی ناگهانی آن را از روی onodeها بازسازی کند (`OnodeScan.cc`)؛ این کار بار نوشتن KV را کم می‌کند اما زمان راه‌اندازی پس از crash را بیشتر.
:::

## شبه‌کد خلاصه‌ی مسیر نوشتن {#sec-12-7-7}

```text
queue_transactions(ops):
  txc = new TransContext(state=PREPARE)
  for op in ops:                       # write, setattr, omap_set, remove, clone, ...
    onode = get_onode(op.oid)          # از cache یا کلید O
    if op is write:
      released = extents overwritten by [off, off+len)
      if len <= released and released < prefer_deferred_size:
        txc.deferred.append(data)      # ثبت در کلید L همراه فراداده
      else:
        ext = allocator.allocate(round_up(len, min_alloc_size))
        aio_write(ext, data, csum=crc32c)
      onode.extent_map.update(off, len, blobs)
    txc.kv.set("O"+oid, encode(onode)) # و omap/attr/shared_blob به‌روزشده
  state_proc(txc)                      # AIO_WAIT -> KV_* -> DEFERRED_* -> DONE
```

::: {.summary title="نکات SRE این فصل"}

- FileStore از Reef پشتیبانی نمی‌شود؛ پیش از ارتقا همه‌ی OSDها را BlueStore کنید.
- block.db دست‌کم ۲.۵٪ (RGW سنگین: ۴٪)؛ `BLUEFS_SPILLOVER` را پایش کنید.
- دامنه‌ی خرابی دستگاه db مشترک را در طراحی لحاظ کنید.
- min_alloc_size هنگام ساخت ثابت می‌شود؛ OSDهای پیش از Pacific را بررسی کنید.
- SSD با حفاظت قطع برق برای db/wal.
- ابزارهای bluestore فقط روی OSD متوقف؛ fsck پیش از repair.
- تکه‌تکگی تخصیص‌دهنده را روی OSDهای پر و قدیمی پایش کنید.

:::

# تکمیلی و به‌روز {#sec-12-8}

- **پیش‌فرض‌های کد جاری**: `bluestore_allocator=hybrid`، `bluestore_min_alloc_size_hdd/ssd=4_K`، `bluestore_prefer_deferred_size_hdd=64_K`، `bluestore_csum_type=crc32c`، `osd_memory_target=4_G`.
- **Pacific**: sharding RocksDB برای OSDهای تازه؛ min_alloc_size HDD به ۴ کیلوبایت.
- **Squid**: فشرده‌سازی LZ4 در RocksDB به‌طور پیش‌فرض؛ کاهش توصیه‌ی اندازه‌ی db به ۲.۵٪.
- **Reef**: FileStore پشتیبانی نمی‌شود.
- **crimson/SeaStore**: crimson در Squid و SeaStore در Tentacle پیش‌نمایش فناوری‌اند؛ crimson OSD می‌تواند BlueStore را هم به‌عنوان backend استفاده کند. برای production هنوز BlueStore کلاسیک توصیه می‌شود.

# تمرین عملی {#sec-12-9}

1. با `ceph osd metadata` برای سه OSD، نوع دستگاه‌ها، اندازه‌ی db و min_alloc_size را استخراج کنید.
2. یک pool آزمایشی با فشرده‌سازی zstd در حالت aggressive بسازید، فایل متنی بزرگ و فایل فشرده‌شده بنویسید و ستون‌های فشرده‌سازی `ceph df detail` را مقایسه کنید.
3. با `ceph tell osd.N bluefs stats` مصرف db و slow را ببینید. اگر سرریز دارید، علتش را با اندازه‌ی db تحلیل کنید.
4. در آزمایشگاه، یک OSD را بدون db بسازید، سپس با `ceph-volume lvm new-db` و `migrate` به آن db اضافه کنید.
5. سطح debug BlueStore را موقتاً روی یک OSD به ۱۰ ببرید، یک نوشتن کوچک و یک نوشتن بزرگ انجام دهید و در لاگ کلمات `deferred` و `direct` و حالت‌های txc را پیدا کنید. سپس debug را برگردانید.
6. در کد منبع، تابع `_deferred_replay` را پیدا کنید و توضیح دهید هنگام mount چه کلیدهایی را می‌خواند.

# پرسش‌های مرور {#sec-12-10}

1. سه محدودیت اصلی FileStore کدام بودند؟
2. چرا BlueStore برای نوشتن‌های بزرگ نیازی به journal جدا ندارد؟
3. BlueFS چیست و چرا Ceph از XFS برای RocksDB استفاده نمی‌کند؟
4. سرریز BlueFS چیست و چه اثری دارد؟
5. شرط deferred شدن یک نوشتن در `_defer_or_allocate` چیست؟
6. چرا ack به کلاینت پس از KV_DONE ایمن است؟
7. سه نسل omap در فضای کلید BlueStore کدام‌اند و چرا per-PG بهتر است؟
8. چرا min_alloc_size از ۶۴ کیلوبایت به ۴ کیلوبایت کاهش یافت؟
9. HybridAllocator چه مصالحه‌ای بین AVL و bitmap برقرار می‌کند؟
10. خرابی یک NVMe پشتیبان db چه اثری بر کلاستر دارد؟

# منابع این فصل {#sec-12-11}

- BlueStore configuration reference: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- BlueStore migration: https://docs.ceph.com/en/latest/rados/operations/bluestore-migration/
- ceph-bluestore-tool: https://docs.ceph.com/en/latest/man/8/ceph-bluestore-tool/
- ceph-volume lvm migrate: https://docs.ceph.com/en/latest/ceph-volume/lvm/migrate/
- Health checks: https://docs.ceph.com/en/latest/rados/operations/health-checks/
- Source: src/os/bluestore (BlueStore.cc, BlueStore_components.h, Writer.cc, HybridAllocator.h): https://github.com/ceph/ceph/tree/main/src/os/bluestore
- Source: option definitions: https://github.com/ceph/ceph/blob/main/src/common/options/global.yaml.in
- Aghayev et al., "File Systems Unfit as Distributed Storage Backends: Lessons from 10 Years of Ceph Evolution" (SOSP 2019): https://www.pdl.cmu.edu/PDL-FTP/Storage/ceph-exp-sosp19.pdf
- Squid release notes: https://docs.ceph.com/en/latest/releases/squid/
- Reef release notes: https://docs.ceph.com/en/latest/releases/reef/
