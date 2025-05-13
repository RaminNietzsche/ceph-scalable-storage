---
chapter: 25
id: ch25
title: 'Lower Layers (3): RocksDB Inside BlueStore'
part: lower
lang: en
translation: pending
---

# مقدمه: چرا RocksDB؟ {#sec-25-1}

BlueStore داده‌ی اشیا را مستقیم روی دستگاه خام می‌نویسد، ولی همه‌ی فراداده‌اش، از onodeها و omapها تا freelist و deferred writeها، در RocksDB قرار دارد. RocksDB یک پایگاه داده‌ی کلید-مقدار مبتنی بر LSM-tree است: نوشتن‌ها ابتدا در یک لاگ ترتیبی (WAL) و یک ساختار حافظه‌ای (memtable) ثبت می‌شوند و بعدها در پس‌زمینه به فایل‌های مرتب و تغییرناپذیر (SST) تبدیل و ادغام می‌شوند. این ساختار نوشتن کوچک را ارزان و ترتیبی می‌کند، که برای فراداده‌ی پرتکرار BlueStore ایده‌آل است. هزینه‌ی آن در compaction و write amplification پرداخت می‌شود. این فصل لایه‌به‌لایه نشان می‌دهد Ceph چگونه RocksDB را پیکربندی و shard می‌کند و روی BlueFS می‌نشاند.

::: {.summary}

- Ceph نسخه‌ی خودش از RocksDB را به‌صورت submodule (`ceph/rocksdb`) همراه کد دارد. رابط آن `src/kv/RocksDBStore.cc` است که `KeyValueDB` را پیاده می‌کند.
- پیش‌فرض‌های `bluestore_rocksdb_options` شامل این موارد است: memtable ۱۶M، حداکثر ۶۴ memtable، ادغام دست‌کم ۶ memtable پیش از flush، L1 برابر 1G، ضریب ۸ و فشرده‌سازی LZ4.
- column family sharding (`bluestore_rocksdb_cfs`) پیشوندهای `m`، `p` و `O` را به چند CF با hash نوع rjenkins روی بخشی از کلید تقسیم می‌کند.
- BlueFS سطوح RocksDB را بر اساس سیاست `use_some_extra` بین WAL، DB و دستگاه کند پخش می‌کند. سرریز به دستگاه کند هشدار `BLUEFS_SPILLOVER` می‌دهد.

:::

# از تراکنش BlueStore تا WriteBatch {#sec-25-2}

`BlueStore::_txc_finalize_kv` و `_kv_sync_thread` تراکنش‌های آماده را جمع می‌کنند. هر `KeyValueDB::Transaction` در `RocksDBStore` یک `rocksdb::WriteBatch` است و `submit_transaction_sync` آن را با `WriteOptions.sync = true` به RocksDB می‌دهد. چند تراکنش BlueStore در یک دور `_kv_sync_thread` پشت سر هم ثبت می‌شوند، ولی فقط آخرین آن‌ها هم‌گام است. بنابراین چندین txc با یک fsync روی WAL پایدار می‌شوند (group commit).

![مسیرهای نوشتن و خواندن در RocksDB. در مسیر نوشتن، WriteBatch ابتدا در WAL (روی دستگاه WAL یا DB از طریق BlueFS) و سپس در memtable فعال هر column family ثبت می‌شود. در پس‌زمینه، memtableهای پر تغییرناپذیر می‌شوند، پس از جمع شدن حداقل ۶ عدد با هم ادغام و به L0 flush می‌شوند و compaction آن‌ها را به سطوح پایین‌تر می‌برد. خواندن به ترتیب memtable، immutableها، همه‌ی فایل‌های L0 و سپس از هر سطح دیگر حداکثر یک فایل (با کمک bloom filter) را بررسی می‌کند](figures/ch25/f01_write.png){#fig-25-f01_write}

| عملیات KeyValueDB | معادل RocksDB | کاربرد در BlueStore |
|---|---|---|
| `set(prefix, key, bl)` | `Put(cf, key, value)` | onode، omap، deferred |
| `rmkey` | `Delete` | حذف onode و omap |
| `rm_single_key` | `SingleDelete` | کلیدهایی که دقیقاً یک بار نوشته شده‌اند (مثل L)؛ tombstone زودتر حذف می‌شود |
| `rm_range_keys` | `DeleteRange` (بالاتر از آستانه) | حذف omap کامل یک شیء؛ زیر `rocksdb_delete_range_threshold=1M` کلیدبه‌کلید حذف می‌شود |
| `merge` | `Merge` با operator ثبت‌شده | `bitwise_xor` برای freelist و `int64_array` برای آمار |

# WAL: قالب رکورد {#sec-25-3}

WAL مربوط به RocksDB (فایل‌های `*.log` در دایرکتوری BlueFS به نام `db.wal`) به بلوک‌های ثابت ۳۲ کیلوبایتی (`kBlockSize = 32768`) تقسیم می‌شود. هر رکورد یک سرآیند ۷ بایتی (`kHeaderSize = 4 + 2 + 1`) دارد: checksum از نوع crc32c ماسک‌شده (۴ بایت)، طول (۲ بایت) و نوع (۱ بایت). نوع یکی از این‌هاست: `kFullType=1` (رکورد کامل در همین بلوک)، `kFirstType=2`، `kMiddleType=3` یا `kLastType=4` (رکوردی که به چند بلوک شکسته شده است). در حالت recyclable، ۴ بایت شماره‌ی لاگ هم اضافه و سرآیند ۱۱ بایتی می‌شود.

```text
WAL record (منطق از RocksDB db/log_format.h، Apache-2.0/GPL-2.0؛ نمایش از این کتاب)
 +--------+--------+------+---------------------------+
 | CRC(4) | Len(2) | T(1) |  payload: WriteBatch بخشی |
 +--------+--------+------+---------------------------+
 WriteBatch = seq(8) | count(4) | {type, [cf id], key, value}*
```

::: {.deep}
**تعامل WAL و BlueFS:** RocksDB برای هر commit هم‌گام `Sync()` را روی فایل WAL صدا می‌زند و BlueRocksEnv آن را به `BlueFS::fsync` تبدیل می‌کند. BlueFS داده را flush می‌کند. اگر فایل بزرگ‌تر شده باشد، باید fnode تازه را هم در لاگ BlueFS ثبت کند، که یعنی یک نوشتن هم‌گام دوم. حالت envelope در Tentacle و بالاتر (فصل ۲۴) دقیقاً برای حذف همین نوشتن دوم طراحی شده است. همچنین `max_total_wal_size=1G` باعث می‌شود اگر WAL بیش از ۱ گیگابایت شود، memtableهای قدیمی‌تر زودتر flush شوند تا WAL بتواند کوتاه شود.
:::

# memtable و flush {#sec-25-4}

memtable به‌طور پیش‌فرض یک skiplist است. با پیش‌فرض‌های Ceph، هر memtable `write_buffer_size=16M` دارد و تا `max_write_buffer_number=64` memtable (یعنی حداکثر ۱ گیگابایت) می‌تواند در حافظه باشد. `min_write_buffer_number_to_merge=6` یعنی flush فقط وقتی انجام می‌شود که دست‌کم شش memtable تغییرناپذیر آماده باشند. سپس هر شش با هم ادغام می‌شوند و کلیدهایی که در این فاصله نوشته و پاک شده‌اند (مثل deferred writeها و رکوردهای موقت pg log) **هرگز به SST نمی‌رسند**. برای CFهای `L` و `P` این عدد در `bluestore_rocksdb_cfs` به ۳۲ رسانده شده است، چون عمر کلیدهای آن‌ها بسیار کوتاه است.

::: {.tip}
این طراحی توضیح می‌دهد چرا حذف یا کوتاه کردن `min_write_buffer_number_to_merge` در تنظیمات دستی معمولاً write amplification را چند برابر می‌کند. اگر `bluestore_rocksdb_options` را تغییر می‌دهید، فقط کلیدهای مورد نظر را در `bluestore_rocksdb_options_annex` اضافه کنید، نه کل رشته را.
:::

# SST: قالب فایل {#sec-25-5}

![ساختار یک فایل SST از نوع block-based. داده در بلوک‌های حدود ۴K (rocksdb_block_size) با فشرده‌سازی پیشوند کلید و نقاط restart ذخیره می‌شود. پس از داده‌ها بلوک filter (bloom با ۲۰ بیت برای هر کلید در Ceph)، index (آخرین کلید هر بلوک و BlockHandle آن)، properties و metaindex قرار می‌گیرند. footer در انتها BlockHandleهای metaindex و index، format_version و عدد جادویی 0x88e241b785f4cff7 را دارد. هر بلوک یک trailer پنج‌بایتی شامل نوع فشرده‌سازی و checksum دارد](figures/ch25/f02_sst.png){#fig-25-f02_sst}

| بخش | محتوا | گزینه‌ی Ceph |
|---|---|---|
| data block | کلیدهای مرتب با پیشوند مشترک حذف‌شده؛ هر ۱۶ کلید یک restart point | `rocksdb_block_size=4_K` |
| filter | bloom filter کل فایل یا پارتیشن‌بندی‌شده | `rocksdb_bloom_bits_per_key=20` (نرخ مثبت کاذب حدود ۰٫۰۱٪) |
| index | آخرین کلید هر بلوک → (offset، size) | `rocksdb_metadata_block_size=4_K` |
| کش | بلوک‌های داده، index و filter در block cache | `rocksdb_cache_size=512_M` (با autotune متغیر)، `rocksdb_cache_type=binned_lru`، `rocksdb_cache_index_and_filter_blocks=true` |
| footer | BlockHandleها، format_version، magic | — |

::: {.note}
نوع checksum بلوک‌ها و `format_version` پیش‌فرض به نسخه‌ی RocksDB همراه Ceph بستگی دارد. در RocksDB اصلی (شاخه‌ی main) پیش‌فرض‌ها `kXXH3` و `format_version=7` هستند. Ceph نسخه‌ی خودش را از مخزن `ceph/rocksdb` می‌سازد، بنابراین برای دیدن مقدار دقیق، خروجی `OPTIONS-*` درون BlueFS را بررسی کنید (با `bluefs-export`).
:::

# compaction و سطوح {#sec-25-6}

![اندازه‌ی هدف سطوح با پیش‌فرض‌های Ceph و جای‌گذاری آن‌ها روی دستگاه‌ها. L1 برابر 1G است و هر سطح ۸ برابر سطح قبلی، پس L2 حدود 8G، L3 حدود 64G و L4 حدود 512G است. سیاست use_some_extra سطوحی را که کامل جا می‌شوند روی block.db قرار می‌دهد، فضای اضافه را برای بخشی از سطح بعدی به کار می‌برد و فقط بقیه را به دستگاه کند می‌فرستد](figures/ch25/f04_levels.png){#fig-25-f04_levels}

با `compaction_style=kCompactionStyleLevel`، هر سطح Ln (n ≥ 1) مجموعه‌ای از SSTهای بدون هم‌پوشانی کلید است. وقتی تعداد فایل‌های L0 به `level0_file_num_compaction_trigger=8` برسد، compaction L0→L1 آغاز می‌شود. وقتی اندازه‌ی یک سطح از هدفش بیشتر شود، بخشی از آن به سطح بعد ادغام می‌شود. پیش‌فرض‌های Ceph عبارت‌اند از `max_bytes_for_level_base=1G`، `max_bytes_for_level_multiplier=8` و `max_background_jobs=4` (flush و compaction با هم).

**مثال عددی اندازه‌ی DB:** OSDی با ۱۰ میلیون شیء ۴M (حدود ۴۰ ترابایت) و onodeهای حدود ۸۰۰ بایتی، فقط برای `O` حدود ۸ گیگابایت داده دارد. با omap و pg log ممکن است به ۲۰ تا ۳۰ گیگابایت برسد. با پیش‌فرض‌ها، L1+L2+L3 = 1 + 8 + 64 = 73G روی DB لازم است تا کل داده‌ی سطح ۳ روی دستگاه سریع بماند. اگر block.db فقط ۳۰G باشد، سیاست `use_some_extra` بخشی از L3 را روی DB و بقیه را روی دستگاه کند قرار می‌دهد و `BLUEFS_SPILLOVER` گزارش می‌شود.

| سیاست `bluestore_volume_selection_policy` | رفتار |
|---|---|
| `rocksdb_original` | فقط سطوحی که کامل جا می‌شوند روی DB قرار می‌گیرند |
| `use_some_extra` (پیش‌فرض) | فضای اضافه‌ی DB برای بخشی از سطح بعدی استفاده می‌شود؛ `bluestore_volume_selection_reserved_factor=2` |
| `use_some_extra_enforced` | مانند قبلی، با اجبار سخت‌گیرانه‌تر |
| `fit_to_fast` | استفاده‌ی ۱۰۰٪ از دستگاه سریع؛ امکان فعال کردن `level_compaction_dynamic_level_bytes` |

::: {.deep}
**چرا ضریب ۸ و نه ۱۰؟** write amplification در compaction سطحی تقریباً با ضریب سطوح متناسب است (هر بایت در هر سطح حدوداً به اندازه‌ی ضریب بار دیگر بازنویسی می‌شود)، و فضای اضافه برابر 1/(multiplier−1) است. ضریب ۸ در برابر ۱۰ کمی فضای بیشتری می‌گیرد ولی write amplification را کاهش می‌دهد و اندازه‌ی سطوح را با اندازه‌های رایج دستگاه‌های DB هم‌خوان‌تر می‌کند. این یک انتخاب طراحی در پیش‌فرض‌های Ceph است. پیش از تغییر آن، تأثیرش را روی اندازه‌ی DB خود محاسبه کنید.
:::

# column family sharding {#sec-25-7}

![column family sharding در BlueStore. پیش‌فرض main این است: «m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L=min_write_buffer_number_to_merge=32 P=min_write_buffer_number_to_merge=32». هر پیشوند فهرست‌شده CF(های) جداگانه‌ی خودش را دارد. برای انتخاب shard، بازه‌ی بایت مشخص‌شده از کلید با ceph_str_hash_rjenkins هش و باقیمانده‌ی آن بر تعداد shard محاسبه می‌شود. پیشوندهای فهرست‌نشده در CF پیش‌فرض می‌مانند](figures/ch25/f03_cf.png){#fig-25-f03_cf}

نحو تعریف به شکل `<prefix>(<shards>[,<l>-<h>])[=<options>]` است که `parse_sharding_def` در `RocksDBStore.cc` آن را تفسیر می‌کند. `get_key_cf` بخش `[hash_l, hash_h)` کلید را با `ceph_str_hash_rjenkins` هش می‌کند و `hash % shards.handles.size()` را برمی‌گرداند. در `p(3,0-12)`، بایت‌های ۰ تا ۱۲ کلید (یعنی pool، hash PG و ابتدای nid) استفاده می‌شوند تا omapهای یک PG در یک shard بمانند و range scan روی یک CF انجام شود.

**چرا shard؟** (۱) هر CF memtable و compaction جداگانه دارد. بنابراین داده‌های پرتغییر (`L` و `P`) با onodeهای پایدار (`O`) در یک SST ادغام نمی‌شوند و write amplification کمتر می‌شود. (۲) compaction روی چند CF موازی می‌شود. (۳) کش جداگانه برای `O` (`block_cache={type=binned_lru}`) از رانده شدن onodeها توسط omap جلوگیری می‌کند.

```bash
# OSD متوقف:
ceph-bluestore-tool show-sharding --path /var/lib/ceph/osd/ceph-4
ceph-bluestore-tool reshard --path /var/lib/ceph/osd/ceph-4 \
    --sharding "m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L P"
ceph-kvstore-tool bluestore-kv /var/lib/ceph/osd/ceph-4 stats
# OSD در حال اجرا:
ceph tell osd.4 compact
ceph daemon osd.4 bluefs stats
```

::: {.warn}
`reshard` روی OSD متوقف اجرا می‌شود و کل DB را بازنویسی می‌کند. پیش از آن OSD را `noout` کنید، فضای آزاد DB را بررسی کنید و ابتدا روی یک OSD آزمایش کنید. طبق مستندات، OSDهایی که پیش از Pacific ساخته شده‌اند پس از ارتقا همچنان بدون shard می‌مانند (همه‌چیز در CF به نام default) و reshard روش رسمی تبدیل آن‌هاست.
:::

# tuning و تشخیص {#sec-25-8}

| نشانه | علت محتمل | اقدام |
|---|---|---|
| تأخیر commit بالا (`ceph daemon osd.N perf dump bluestore` → `kv_sync_lat`) | WAL روی دستگاه کند یا WAL و DB رقیب داده | WAL و DB روی NVMe؛ بررسی `bluefs stats` |
| `BLUEFS_SPILLOVER` | block.db کوچک‌تر از سطوح لازم | بزرگ کردن DB (`bluefs-bdev-expand`) یا مهاجرت (`bluefs-bdev-migrate`) |
| کندی پس از حذف انبوه (مثلاً حذف snapshot) | tombstoneهای زیاد در SSTها | `rocksdb_cf_compact_on_deletion=true` (پیش‌فرض) یا `ceph tell osd.N compact` |
| رشد حافظه‌ی OSD | memtableها (تا ۱G) و block cache | `osd_memory_target`، بررسی `dump_mempools` و `rocksdb` در perf |
| L0 پر و stall نوشتن | compaction عقب افتاده | بررسی `max_background_jobs` و پهنای باند دستگاه DB |

```bash
ceph daemon osd.4 perf dump rocksdb | jq '.rocksdb | {get_latency, submit_latency, submit_sync_latency, compact, compact_running}'
ceph config set osd bluestore_rocksdb_options_annex "max_background_jobs=6"   # فقط کلیدهای تغییرکرده
```

# یک WriteBatch در سطح بایت {#sec-25-9}

برای این‌که ببینیم یک تراکنش BlueStore روی WAL چه شکلی دارد، یک WriteBatch فرضی با دو عمل را دستی کدگذاری می‌کنیم: یک `Put` در CF با شناسه‌ی ۳ (کلید `Ok1o` و مقدار `hello`) و یک `SingleDelete` در CF با شناسه‌ی ۷ (کلید `L42`). شماره‌ی توالی 1234567 است. ثابت‌های نوع از `db/dbformat.h` در RocksDB آمده‌اند: `kTypeColumnFamilyValue=0x5` و `kTypeColumnFamilySingleDeletion=0x8`. کدگذار نوشته‌ی خود ماست.

| بایت‌ها | معنی |
|---|---|
| `87 d6 12 00 00 00 00 00` | sequence = 1234567 (u64 little-endian) |
| `02 00 00 00` | count = 2 (u32) |
| `05` | نوع: Put در CF غیرپیش‌فرض |
| `03` | شناسه‌ی CF (varint) |
| `04 4f 6b 31 6f` | طول کلید ۴ + «Ok1o» |
| `05 68 65 6c 6c 6f` | طول مقدار ۵ + «hello» |
| `08 07` | نوع SingleDelete در CF + شناسه‌ی CF ۷ |
| `03 4c 34 32` | طول کلید ۳ + «L42» |

این ۳۲ بایت سپس به‌عنوان payload یک رکورد WAL، با سرآیند ۷ بایتی (crc + طول + نوع `kFullType`)، در بلوک ۳۲K جاری نوشته می‌شود. اگر payload از انتهای بلوک بگذرد، به رکوردهای First/Middle/Last تقسیم می‌شود. اگر کمتر از ۷ بایت تا انتهای بلوک مانده باشد، آن چند بایت با صفر پر می‌شوند.

::: {.deep}
**کلیدهای واقعی BlueStore:** برای پیشوندهایی که CF جدا دارند، نخستین نویسه‌ی پیشوند در کلید RocksDB تکرار نمی‌شود، چون خود CF پیشوند را مشخص می‌کند. در CF پیش‌فرض، کلید به شکل `prefix + 0x00 + key` ترکیب می‌شود (`combine_strings`). به همین دلیل وقتی با `ldb` مستقیم روی CF پیش‌فرض نگاه می‌کنید، کلیدهایی مثل `S\0nid_max` می‌بینید.
:::

# BlueRocksEnv: RocksDB بدون فایل‌سیستم هسته {#sec-25-10}

`BlueRocksEnv` از `rocksdb::EnvWrapper` ارث می‌برد و فراخوانی‌های فایل RocksDB را به BlueFS می‌فرستد:

| تابع Env در RocksDB | پیاده‌سازی در BlueFS |
|---|---|
| `NewWritableFile` | `BlueFS::open_for_write` → `FileWriter` با بافر و `append` |
| `NewSequentialFile` / `NewRandomAccessFile` | `open_for_read` → `FileReader` با prefetch |
| `Sync` / `Fsync` | `BlueFS::fsync`: flush داده، و در صورت تغییر اندازه، ثبت fnode در لاگ |
| `RenameFile` | op_dir_link + op_dir_unlink در یک تراکنش لاگ (اتمیک) |
| `GetChildren` | فهرست `dir_map` |
| `LockFile` | قفل درون‌فرایندی (BlueFS فقط یک کاربر دارد) |

دایرکتوری‌های BlueFS بیانگر محل فیزیکی‌اند: `db` (دستگاه DB)، `db.wal` (دستگاه WAL) و `db.slow` (دستگاه اصلی). RocksDB از طریق گزینه‌های `db_paths` و `wal_dir` فایل‌ها را در این دایرکتوری‌ها می‌سازد و volume selector مربوط به BlueFS (بخش قبل) تصمیم نهایی را درباره‌ی دستگاه می‌گیرد.

```text
pseudocode: fsync یک فایل WAL (خلاصه‌ی این کتاب)
  BlueFS::fsync(h):
      _flush_F(h)                         # نوشتن بافر به extentها با aio
      if h.file.fnode.size changed (یا allocated changed):
          log.t.op_file_update_inc(h.file.fnode)
          _flush_and_sync_log_LD()        # نوشتن هم‌گام دوم: لاگ BlueFS
      else:
          _flush_bdev(h)                  # فقط flush دستگاه
```

# الگوریتم‌های درون RocksDB در سطح کد {#sec-25-11}

بخش‌های پیشین گفتند RocksDB درون BlueStore چه می‌کند. این بخش هفت الگوریتم کلیدی را با کد RocksDB 9.11 بررسی می‌کند، یعنی همان نسخه‌ای که submodule `src/rocksdb` در شاخه‌ی main به آن اشاره می‌کند (مخزن ceph/rocksdb). نسخه‌های Reef و Squid به commitهای دیگری اشاره می‌کنند. پیش‌فرض‌هایی که در طول نسخه‌ها عوض شده‌اند، جداگانه مشخص شده‌اند.

## skiplist در memtable {#sec-25-11-1}

memtable پیش‌فرض یک `InlineSkipList` است. Ceph کارخانه‌ی memtable را عوض نمی‌کند، پس همین ساختار برای همه‌ی column familyها به‌کار می‌رود. سازنده‌ی آن `max_height = 12` و `branching_factor = 4` دارد.

::: {.algo #alg-25-1 title="درج و جست‌وجو در skiplist" src="rocksdb/memtable/inlineskiplist.h :: InlineSkipList::RandomHeight، FindGreaterOrEqual، Insert" complexity="جست‌وجو و درج با امید O(log_4 n) سطح و حدود 4 مقایسه در هر سطح، یعنی O(log n). حافظه به‌طور میانگین 4/3 اشاره‌گر برای هر گره"}
:::

```text
pseudocode
RandomHeight(): h = 1
    while h < 12 and rnd.Next() < 2^32/4: h++          # احتمال 1/4 برای هر سطح بالاتر
FindGreaterOrEqual(key):
    x = head ; level = max_height − 1
    loop: next = x.next[level]
          cmp = (next == null) ? +1 : compare(next.key, key)
          if cmp == 0 or (cmp > 0 and level == 0): return next
          if cmp < 0: x = next                       # جلو برو
          else: level −= 1                           # پایین برو
Insert(key): ارتفاع h ؛ prev[] و next[] را از بالا تا پایین پیدا کن ؛
             گره را با یک تخصیص از arena بساز (اشاره‌گرها پیش از کلید) ؛
             از سطح 0 به بالا با CAS یا store-release پیوند بزن
```

**مثال عددی.** با write_buffer_size = 16 MiB (پیش‌فرض Ceph) و ورودی‌های حدود 100 بایتی، هر memtable حدود 160000 گره دارد. تعداد امید ریاضی گره‌هایی که ارتفاعشان دست‌کم h است، n·4^-(h−1) است: 160000، 40000، 10000، 2500، 625، 156، 39، 10، 2.4 برای h = 1..9. پس ارتفاع مؤثر حدود 9 است و یک Seek حدود 9 سطح را با 1 تا 3 قدم افقی در هر سطح طی می‌کند، یعنی کمتر از 30 مقایسه‌ی کلید. میانگین ارتفاع 4/3 است، پس هر گره به‌طور میانگین 8 × 4/3 ≈ 10.7 بایت اشاره‌گر دارد. یک شبیه‌سازی جداگانه با 160000 گره میانگین 1.335 را داد.

![skiplist با ده کلید و ارتفاع‌های تصادفی، و مسیر Seek(38) با رنگ قرمز. جست‌وجو از بالاترین سطح head شروع می‌شود، تا وقتی کلید بعدی کوچک‌تر است جلو می‌رود و وقتی بزرگ‌تر یا تهی است یک سطح پایین می‌رود. اگر در هر سطحی کلید برابر پیدا شود، همان‌جا برمی‌گردد. در InlineSkipList اشاره‌گرهای سطوح بالا پیش از خود گره در همان تخصیص arena قرار دارند، پس یک گره با ارتفاع h دقیقاً h اشاره‌گر هشت بایتی و سپس کلید و مقدار را در یک قطعه‌ی پیوسته دارد](figures/ch25/f05_skiplist.png){#fig-25-f05_skiplist}

::: {.note}
درج هم‌زمان (`allow_concurrent_memtable_write = true`، پیش‌فرض RocksDB) از `InsertConcurrently` با CAS در هر سطح استفاده می‌کند. در BlueStore بیشتر نوشتن‌ها از `kv_sync_thread` می‌آیند، پس رقابت روی skiplist کم است و هزینه‌ی اصلی مقایسه‌ی کلید و cache miss است.
:::

## گروه نوشتن (group commit) {#sec-25-11-2}

::: {.algo #alg-25-2 title="تشکیل گروه نوشتن" src="rocksdb/db/write_thread.cc :: WriteThread::JoinBatchGroup، EnterAsBatchGroupLeader، ExitAsBatchGroupLeader" complexity="O(g) برای g نویسنده‌ی گروه؛ یک AddRecord و حداکثر یک fsync برای کل گروه"}
:::

```text
pseudocode
JoinBatchGroup(w): newest_writer_ را با CAS به w تغییر بده
    if صف خالی بود: w رهبر است
    else: روی w.state منتظر بمان (spin کوتاه، سپس futex/condvar)
EnterAsBatchGroupLeader(leader):
    max = max_write_batch_group_size_bytes                # 1 MiB
    if size(leader) ≤ max/8: max = size(leader) + max/8   # 128 KiB
    for w از قدیمی به جدید:
        if (w.sync و not leader.sync) or w.disable_wal ≠ leader.disable_wal
           or w.no_slowdown ≠ … or size + size(w) > max: قطع کن
        else: w را به گروه اضافه کن
```

**مثال عددی.** رهبر یک batch شصت کیلوبایتی دارد. چون 60K ≤ 128K، سقف گروه 60K + 128K = 188K می‌شود. سه نویسنده‌ی بعدی 40K، 50K و 70K دارند. 60 + 40 + 50 = 150K پذیرفته می‌شود، اما با 70K جمع 220K می‌شود و از 188K بیشتر است، پس گروه همان‌جا قطع می‌شود. اگر رهبر sync=false باشد و نویسنده‌ی دوم sync=true، گروه پیش از نویسنده‌ی دوم قطع می‌شود، چون رهبرِ بی‌sync نمی‌تواند برای دیگری fsync را تضمین کند.

![توالی group commit در WriteThread. نخستین نویسنده با CAS روی newest_writer_ رهبر می‌شود. بقیه منتظر می‌مانند. رهبر تا سقف اندازه و تا جایی که پرچم‌ها سازگارند، batchها را در یک رکورد WAL ادغام می‌کند. یک‌بار Sync می‌کند، هر batch را با شماره‌ی توالی پیوسته در memtable درج می‌کند و سپس همه را با STATE_COMPLETED بیدار می‌کند](figures/ch25/f10_wgroup.png){#fig-25-f10_wgroup}

## قالب رکورد WAL و قطعه‌قطعه شدن {#sec-25-11-3}

::: {.algo #alg-25-3 title="تقسیم رکورد WAL به بلوک‌های 32K" src="rocksdb/db/log_writer.cc :: log::Writer::AddRecord، EmitPhysicalRecord؛ db/log_format.h" complexity="O(L/32K) قطعه برای رکورد L بایتی؛ سربار 7 بایت در هر قطعه (11 بایت در قالب recyclable)"}
:::

```text
pseudocode
left = len(record) ; begin = true
do:
    leftover = 32768 − block_offset
    if leftover < 7: صفر بنویس تا پایان بلوک ؛ block_offset = 0
    avail = 32768 − block_offset − 7
    frag = min(left, avail) ; end = (frag == left)
    type = begin&&end ? FULL(1) : begin ? FIRST(2) : end ? LAST(4) : MIDDLE(3)
    EmitPhysicalRecord(type, ptr, frag)      # crc32c(type‖payload) ماسک‌شده، len (2B)، type (1B)
    left −= frag ; begin = false
while left > 0
```

**مثال عددی.** یک WriteBatch هفتادهزار بایتی در block_offset = 30000 شروع می‌شود:

- leftover = 2768 و avail = 2761، پس FIRST با 2761 بایت.
- بلوک بعدی: avail = 32761، پس MIDDLE.
- بلوک سوم: باز MIDDLE با 32761 بایت.
- باقی‌مانده 70000 − 2761 − 2×32761 = 1717 بایت است، پس LAST در ابتدای بلوک چهارم.

block_offset بعدی 7 + 1717 = 1724 است. سربار کل 4 × 7 = 28 بایت است.

![اینکه log::Writer::AddRecord یک batch هفتادهزار بایتی را چگونه در چهار بلوک 32 KiB می‌نویسد. هر قطعه هدر 7 بایتی دارد: crc32c چهاربایتی، طول دوبایتی و نوع یک‌بایتی. بلوک‌ها مستقل‌اند: اگر خواننده در بازیابی به بلوک خراب برسد، می‌تواند از ابتدای بلوک بعدی همگام شود. اگر کمتر از 7 بایت به پایان بلوک مانده باشد، با صفر پر می‌شود](figures/ch25/f08_walfrag.png){#fig-25-f08_walfrag}

## بلوک داده‌ی SST: دلتای کلید و restart {#sec-25-11-4}

::: {.algo #alg-25-4 title="رمزگذاری دلتای کلید و Seek درون بلوک" src="rocksdb/table/block_based/block_builder.cc :: BlockBuilder::AddWithLastKeyImpl، Finish؛ table/block_based/block.cc :: DataBlockIter::SeekImpl (BinarySeek)؛ util/coding.h :: EncodeVarint32" complexity="ساخت O(L)؛ Seek O(log R + I) با R restart و I = block_restart_interval = 16"}
:::

```text
pseudocode
Add(key, value):
    if counter == 16: restarts.push(buffer.size) ; shared = 0 ; counter = 0
    else: shared = طول پیشوند مشترک با کلید قبلی
    PutVarint32 ×3 (shared, len(key)−shared, len(value)) ; append key[shared:] ; append value
Finish(): append restarts[] as u32 ; append Pack(index_type, num_restarts)   # bit31
Seek(target): جست‌وجوی دودویی روی restarts با مقایسه‌ی کلید کامل هر restart
              سپس پیمایش خطی و بازسازی کلید = prev[0:shared] + delta
EncodeVarint32(v): while v ≥ 128: emit (v & 127) | 128 ; v ≫= 7 ; emit v
```

**مثال عددی.** با `rocksdb_block_size = 4K` (پیش‌فرض Ceph) و ورودی‌های حدود 300 بایتی، هر بلوک حدود 13 ورودی دارد، یعنی کمتر از 16، پس فقط یک restart. Seek درون بلوک عملاً خطی است، اما 13 مقایسه روی داده‌ای که در cache است. در بلوک‌های metadata که مقادیر کوچک‌اند (مثلاً 100 کلید 40 بایتی)، 7 restart هست و جست‌وجوی دودویی 3 مقایسه به‌اضافه‌ی حداکثر 15 قدم خطی دارد. رمزگذاری varint عدد 300 دو بایت AC 02 است و عدد 18 یک بایت 12.

![چیدمان بایت‌به‌بایت یک بلوک داده‌ی SST با دو ورودی نمونه. ورودی اول restart است و کلید کامل 18 بایتی را نگه می‌دارد (10 بایت کلید کاربر و 8 بایت trailer شامل seq و type). ورودی دوم فقط 9 بایت غیرمشترک دارد. انتهای بلوک آرایه‌ی آفست restartها و یک u32 پانویس است که بیت 31 آن نوع ایندکس درون‌بلوکی را نشان می‌دهد و بقیه‌ی بیت‌ها تعداد restartها را](figures/ch25/f07_block.png){#fig-25-f07_block}

## فیلتر Bloom محلی در cache line {#sec-25-11-5}

Ceph با `rocksdb_bloom_bits_per_key = 20` تابع `NewBloomFilterPolicy(20)` را صدا می‌زند (`RocksDBStore::load_rocksdb_options`). در RocksDB 9.11 پیش‌فرض `format_version = 6` است، پس پیاده‌سازی فیلتر `FastLocalBloomImpl` است: همه‌ی probeهای یک کلید درون یک cache line پانصد و دوازده بیتی می‌افتند.

::: {.algo #alg-25-5 title="Bloom محلی در cache line" src="rocksdb/util/bloom_impl.h :: FastLocalBloomImpl::ChooseNumProbes، AddHash، HashMayMatchPrepared؛ BloomMath::CacheLocalFpRate" complexity="O(k) بیت‌خوانی در یک cache line (با AVX2 تا 8 probe هم‌زمان)؛ حافظه b بیت برای هر کلید"}
:::

```text
pseudocode
k = ChooseNumProbes(1000·b)            # جدول تجربی: 20000 میلی‌بیت ⇒ 11
AddHash(h1, h2): line = FastRange32(h1, len/64) · 64     # انتخاب cache line
    h = h2
    repeat k: bit = h ≫ 23 (۹ بیت بالا ⇒ 0..511) ; line[bit] = 1 ; h ×= 0x9e3779b9
MayMatch: همان مسیر ؛ اگر هر بیت صفر بود ⇒ «قطعاً نیست»
FP ≈ میانگین Bloom استاندارد برای (کلید در هر خط ± انحراف معیار)
```

**مثال عددی.**

- **b = 20:** k = 11 و هر cache line به‌طور میانگین 512/20 = 25.6 کلید دارد. انحراف معیار √25.6 ≈ 5.06 است، پس دو حالت شلوغ و خلوت 30.66 و 20.54 کلید در خط دارند. FP تخمینی حدود 1.7×10^-4 (0.017٪) است، در برابر 6.8×10^-5 برای Bloom استاندارد با همان حافظه.
- **b = 10:** k = 6 و FP حدود 0.95٪.
- **حافظه:** یک SST با 1 میلیون کلید 20×10^6 بیت، یعنی 2.5 MB فیلتر دارد.

بهای محلی بودن کمی FP بیشتر است. در عوض هر پرس‌وجو به جای 11 cache miss فقط یک cache miss دارد.

![نرخ مثبت کاذب برحسب بیت به ازای هر کلید برای Bloom استاندارد و Bloom محلی در cache line، با تعداد probe که هر پیاده‌سازی انتخاب می‌کند. نقطه‌ی قرمز تنظیم Ceph است (20 بیت، 11 probe، حدود 0.017٪). در 10 بیت تفاوت دو منحنی کم است و در 20 بیت حدود 2.5 برابر. اما Bloom محلی همیشه یک خط 64 بایتی را لمس می‌کند، و این برای Get‌های onode که بیشترشان در L0 تا L2 دنبال کلید نبوده می‌گردند، تعیین‌کننده است](figures/ch25/f06_bloom.png){#fig-25-f06_bloom}

## امتیاز compaction و اندازه‌ی پویای سطوح {#sec-25-11-6}

::: {.algo #alg-25-6 title="محاسبه‌ی هدف سطوح و امتیاز compaction" src="rocksdb/db/version_set.cc :: VersionStorageInfo::CalculateBaseBytes، ComputeCompactionScore، MaxInputLevel" complexity="O(تعداد فایل‌ها) در هر تغییر Version"}
:::

```text
pseudocode
CalculateBaseBytes (dynamic):
    max_level_size = بزرگ‌ترین سطح ؛ cur = max_level_size
    for i = num_levels−2 down to first_non_empty: cur /= multiplier
    base_level = first_non_empty
    while base_level > 1 and cur > base_bytes_max: base_level−− ; cur /= multiplier
    target[base_level] = max(cur, base_bytes_max) ; target[i+1] = target[i]·multiplier (کف base_bytes_max)
ComputeCompactionScore: for level in 0 .. num_levels−2:
    L0: score = max(files/trigger, size/max_bytes_for_level_base …) و ×10 اگر > 1
    L>0: score = bytes_not_compacting / target   (یا / (target + ورودی در راه) ×10 اگر ≥ 1)
بیشترین امتیاز ⇒ نخستین compaction
```

**مثال عددی (پیش‌فرض‌های Ceph: base = 1 GiB، multiplier = 8، هفت سطح).** فرض کنید L6 دویست گیگابایت دارد. از بالا به پایین: L5 = 25، L4 = 3.125 و L3 = 0.39 GiB. چون 0.39 از base_bytes_min = 1/8 GiB بزرگ‌تر است، base_level = L3 و هدف‌ها L3 = max(0.39, 1) = 1 GiB، L4 = 3.125، L5 = 25 و L6 = 200 هستند. با اندازه‌های واقعی 0.31، 3.0 و 24 امتیازها 0.31، 0.96 و 0.96 می‌شوند. هیچ‌کدام به 1 نرسیده است. اگر L0 هشت فایل داشته باشد، امتیاز آن 8/8 = 1 است و پس از ضرب در kScoreScale برابر 10 می‌شود، پس L0→L3 اولویت دارد. L1 و L2 خالی می‌مانند: این همان رفتار dynamic level bytes است که داده را مستقیم به سطح پایه می‌برد.

![اندازه‌ی واقعی و هدف هر سطح با level_compaction_dynamic_level_bytes=true. هدف‌ها از سطح آخر به بالا با تقسیم بر 8 به دست می‌آیند. L1 و L2 زیر سطح پایه‌اند و خالی می‌مانند. امتیاز برای سطح آخر حساب نمی‌شود، چون MaxInputLevel برابر num_levels − 2 است](figures/ch25/f09_dynlevels.png){#fig-25-f09_dynlevels}

::: {.warn}
پیش‌فرض `level_compaction_dynamic_level_bytes` در RocksDB از نسخه‌ی 8.4 به true تغییر کرد. رشته‌ی `bluestore_rocksdb_options` در Ceph این گزینه را صریحاً تنظیم نمی‌کند. پس رفتار سطوح به نسخه‌ی RocksDB داخل هر انتشار Ceph بستگی دارد. برای اطمینان، خروجی `ceph daemon osd.N config get bluestore_rocksdb_options` و فایل OPTIONS-* درون BlueFS را (با `ceph-bluestore-tool bluefs-export`) بررسی کنید.
:::

# تکمیلی و به‌روز {#sec-25-12}

- sharding از Pacific برای OSDهای تازه پیش‌فرض شده است. رشته‌ی پیش‌فرض main، یعنی `m(3) p(3,0-12) O(3,0-13)=block_cache={type=binned_lru} L=min_write_buffer_number_to_merge=32 P=min_write_buffer_number_to_merge=32`، را با `ceph config help bluestore_rocksdb_cfs` روی نسخه‌ی خود مقایسه کنید.
- `bluefs_spillover_cleaner` (در Tentacle و main موجود، پیش‌فرض false) یک thread پس‌زمینه است که فایل‌های سرریزشده به دستگاه کند را، در صورت وجود فضا، به DB برمی‌گرداند.
- طبق مستندات، Pacific پشتیبانی آزمایشی از `level_compaction_dynamic_level_bytes` را آورد (همراه سیاست `fit_to_fast`).

# تمرین عملی {#sec-25-13}

1. با `ceph-bluestore-tool bluefs-export` فایل‌های RocksDB یک OSD آزمایشی را بیرون بکشید، با `ldb --db=... list_column_families` CFها را ببینید و با `sst_dump --file=... --show_properties` اندازه‌ی data، index و filter را بخوانید.
2. ۸ بایت انتهای یک SST را با `tail -c 8 | xxd` بخوانید و عدد جادویی را تأیید کنید (به ترتیب little-endian دقت کنید).
3. برای اندازه‌ی DB خود (مثلاً 60G) با پیش‌فرض‌ها حساب کنید چه سطوحی جا می‌شوند. سپس `bluefs stats` را بخوانید و با پیش‌بینی خود مقایسه کنید.
4. `submit_sync_latency` را پیش و پس از انتقال WAL به NVMe مقایسه کنید.

# پرسش‌های مرور {#sec-25-14}

1. group commit در `_kv_sync_thread` چگونه تعداد fsyncها را کم می‌کند؟
2. سرآیند رکورد WAL چند بایت است و چه فیلدهایی دارد؟
3. چرا `min_write_buffer_number_to_merge=6` برای Ceph مهم است؟
4. چرا برای CFهای `L` و `P` این عدد ۳۲ است؟
5. بلوک filter در SST چه نقشی در مسیر خواندن دارد؟
6. با پیش‌فرض‌ها اندازه‌ی L3 چقدر است؟
7. `use_some_extra` چه تفاوتی با `rocksdb_original` دارد؟
8. چگونه CF یک کلید omap per-pg انتخاب می‌شود؟
9. چرا omap یک PG باید در یک shard بماند؟
10. چرا تغییر کل رشته‌ی `bluestore_rocksdb_options` خطرناک است و جایگزین آن چیست؟

# منابع این فصل {#sec-25-15}

- RocksDBStore: https://github.com/ceph/ceph/blob/main/src/kv/RocksDBStore.cc
- پیکربندی BlueStore و sharding: https://docs.ceph.com/en/latest/rados/configuration/bluestore-config-ref/
- قالب WAL مربوط به RocksDB: https://github.com/facebook/rocksdb/wiki/Write-Ahead-Log-File-Format
- قالب block-based table: https://github.com/facebook/rocksdb/wiki/Rocksdb-BlockBasedTable-Format
- compaction سطحی: https://github.com/facebook/rocksdb/wiki/Leveled-Compaction
- column familyها: https://github.com/facebook/rocksdb/wiki/Column-Families
- log_format.h: https://github.com/facebook/rocksdb/blob/main/db/log_format.h
- LSM-tree (O'Neil و همکاران، 1996): https://www.cs.umb.edu/~poneil/lsmtree.pdf
