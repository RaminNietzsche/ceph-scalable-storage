---
id: multisite-dr
lang: fa
---

::: {.tldr}

- اول لایه را انتخاب کنید: stretch mode برای RPO صفر میان دو site نزدیک، کلاسترهای مستقل با تکثیر ناهمگام (RGW multisite، rbd-mirror، cephfs-mirror) برای siteهای دور، و یک پشتیبان مستقل در برابر اشتباه و باج‌افزار.
- تکثیر ناهمگام یعنی RPO بزرگ‌تر از صفر: تأخیر تکثیر در لحظه‌ی خرابی همان داده‌ای است که ممکن است از دست برود؛ پس آن را همیشه بسنجید (`sync status`، `bucket sync status`، `sync error list` و شمارنده‌های sync).
- جابه‌جایی برنامه‌ریزی‌شده صبر می‌کند تا sync به caught up برسد؛ failover برنامه‌ریزی‌نشده zone ثانویه را (`zone modify --master --default` و سپس `period update --commit`) فقط وقتی ارتقا می‌دهد که از کار افتادن master قدیمی تأیید و RGWهای آن متوقف شده باشند.
- site بازگشته پیش از هر نوشتنی باید realm و period تازه را pull کند؛ سپس عقب‌ماندگی را جبران کند و تنها پس از آن درباره‌ی بازگرداندن master تصمیم بگیرید.
- برای RBD در جابه‌جایی برنامه‌ریزی‌شده اول demote و بعد promote کنید، در فاجعه `promote --force` و پس از آن primary قدیمی را `resync` کنید؛ همه‌ی این‌ها را در یک تمرین با زمان‌های ثبت‌شده امتحان کنید.

```bash
radosgw-admin sync status
```

[![روند جابه‌جایی، failover و failback در multisite: برنامه‌ریزی‌شده یا نه، ارتقای zone ثانویه، commit کردن period، تغییر DNS، pull کردن period در site بازگشته، جبران عقب‌ماندگی و ثبت زمان‌ها](figures/app/f04_multisite_failover.png)](#fig-app-multisite-failover)

:::

این پیوست راهنمایی عملی برای اجرای Ceph در چند site و بازیابی هنگام از دست رفتن یک site است. فصل ۵ RGW multisite را راه‌اندازی می‌کند، فصل ۴۲ periodها و موتورهای sync را در کد توضیح می‌دهد، فصل ۱۸ به rbd-mirror و stretch mode می‌پردازد و فصل ۶ mirroring اسنپ‌شات CephFS را پوشش می‌دهد؛ این پیوست آن‌ها را در قالب برنامه‌ی یک اپراتور کنار هم می‌گذارد: کدام توپولوژی، چه RPO و RTO‌ای، چگونه تکثیر را پایش کنیم، و runbookهای گام‌به‌گام برای جابه‌جایی، failover و failback، و در پایان یک فهرست بررسی تمرین. امنیت gatewayها و کلیدهای کاربر سیستمی در [پیوست ی: امنیت RGW](#appK) آمده و دستورها در [پیوست ب: برگه‌ی تقلب دستورها](#appB) هم هستند.

![روند multisite برای جابه‌جایی برنامه‌ریزی‌شده و failover برنامه‌ریزی‌نشده: توقف نوشتن و صبر تا caught up، یا تأیید خرابی و توقف RGWهای قدیمی؛ ارتقای zone ثانویه و commit کردن period روی آن؛ تغییر DNS یا GSLB و endpointها؛ هنگام بازگشت site قدیمی، pull کردن realm و period پیش از هر نوشتن، جبران عقب‌ماندگی با sync status یا data sync init و تصمیم درباره‌ی بازگرداندن master؛ و در پایان ثبت زمان‌ها و RPO و RTO واقعی](figures/app/f04_multisite_failover.png){#fig-app-multisite-failover}

# انتخاب توپولوژی

![گزینه‌های DR: یک کلاستر در دو site با stretch mode (RPO صفر، تأخیر کم، tiebreaker در site سوم)؛ کلاسترهای مستقل با تکثیر ناهمگام از راه RGW multisite، rbd-mirror و cephfs-mirror؛ و یک پشتیبان مستقل با Object Lock](figures/app/f05_dr_options.png){#fig-app-dr-options}

| گزینه | از چه چیزی محافظت می‌کند | RPO | پیش‌نیازها و محدودیت‌ها |
|---|---|---|---|
| Stretch mode (یک کلاستر) | از دست رفتن یکی از دو site داده | صفر (نوشتن همگام در هر دو site) | تأخیر کم میان siteها، یک monitor به‌عنوان tiebreaker در site سوم، ظرفیت خام دوبرابر؛ یک باگ یا اشتباه در سطح کلاستر به هر دو site می‌رسد |
| RGW multisite | از دست رفتن یک site یا کلاستر، برای شیءها | ثانیه تا دقیقه، به اندازه‌ی تأخیر تکثیر | کلاسترهای مستقل، یک realm؛ تغییرات فراداده به zone اصلی نیاز دارند |
| rbd-mirror، حالت journal | از دست رفتن کلاستر، برای imageهای بلاکی | ثانیه | هر نوشتن دو بار انجام می‌شود؛ قابلیت journaling در krbd پشتیبانی نمی‌شود |
| rbd-mirror، حالت snapshot | از دست رفتن کلاستر، برای imageهای بلاکی | بازه‌ی زمان‌بندی | سربار کم؛ با krbd کار می‌کند |
| cephfs-mirror | از دست رفتن کلاستر، برای دایرکتوری‌ها | بازه‌ی snapshot | مبتنی بر snapshot، برای هر peer یک‌طرفه |
| پشتیبان مستقل | اشتباه، باج‌افزار، باگ نرم‌افزار | بازه‌ی پشتیبان | باید بیرون از مسیر تکثیر و در برابر حذف محافظت‌شده باشد |

تکثیر یک اشتباه را همان‌قدر وفادارانه کپی می‌کند که داده را: bucket حذف‌شده یا image بازنویسی‌شده در چند ثانیه به site دیگر می‌رسد. پس هر برنامه‌ی DR یک لایه‌ی پشتیبان هم لازم دارد (فصل ۱۸)، برای نمونه یک نسخه با Object Lock یا یک archive zone که همه‌ی نسخه‌ها را نگه می‌دارد.

در RGW multisite انتخاب‌های اصلی توپولوژی این‌هاست:

- zoneهای **active-active** در یک zonegroup: کلاینت‌ها در هر دو site می‌نویسند و هر zone تغییرات دیگری را pull می‌کند. این حالت پیش‌فرض است و کوتاه‌ترین RTO را می‌دهد، ولی نوشتن هم‌زمان یک شیء در دو site به برنده شدن یکی از نسخه‌ها ختم می‌شود.
- **active-passive**: کلاینت‌ها فقط از zone اصلی استفاده می‌کنند و zone ثانویه برای failover نگه داشته می‌شود؛ `rgw_enable_apis` یا load balancer را طوری تنظیم کنید که zone غیرفعال نوشتن کلاینت را نپذیرد، یا آن را با `--read-only` علامت بزنید.
- **چند zonegroup**: داده فقط درون یک zonegroup تکثیر می‌شود و فراداده (کاربران، bucketها) در کل realm. از آن‌ها برای نگه داشتن داده در یک منطقه استفاده کنید، نه برای DR همان داده.
- **sync policy و archive zone**: فقط برخی bucketها یا فقط در یک جهت تکثیر شوند، و همه‌ی نسخه‌ها در یک archive zone نگه داشته شوند (پایین‌تر را ببینید).

# RPO و RTO با تکثیر ناهمگام

**RPO** (چه مقدار داده ممکن است از دست برود) همان تأخیر تکثیر در لحظه‌ی خرابی است. در RGW multisite این تأخیر از دو بخش ساخته می‌شود: زمانی که طول می‌کشد تا zone مقصد متوجه تغییر شود (هر zone هر `rgw_data_sync_poll_interval` ثانیه، به‌طور پیش‌فرض ۲۰، data log راه دور را می‌خواند، مگر اینکه `rgw_data_notify_interval_msec` تنظیم شده باشد)، به‌علاوه‌ی زمان کپی کارهای عقب‌مانده. زیر بار پایدار این تأخیر چند ثانیه است؛ پس از قطعی پیوند یا موجی از بارگذاری‌های بزرگ می‌تواند به چند ساعت برسد. تغییرات فراداده‌ای که روی zone اصلی انجام شده ولی هنوز sync نشده‌اند (یک کاربر تازه، یک bucket، یک سیاست) هم با از دست رفتن master از دست می‌روند.

**RTO** (چقدر طول می‌کشد تا سرویس برگردد) جمع این‌هاست: تشخیص، تصمیم به failover (معمولاً طولانی‌ترین بخش)، ارتقا و commit کردن period (چند ثانیه)، راه‌اندازی دوباره‌ی RGWها، و تغییر DNS یا GSLB که TTL آن تعیین می‌کند کلاینت‌ها با چه سرعتی جابه‌جا شوند. با TTL کوتاه برای DNS (مثلاً ۶۰ ثانیه) و یک runbook نوشته‌شده، RTO پانزده تا سی دقیقه واقع‌بینانه است؛ بدون runbook چند ساعت است.

::: {.tip}
برای هر سرویس مقدار هدف RPO و RTO را بنویسید و در هر تمرین آن‌ها را بسنجید. هدف RPOای که تأخیر اندازه‌گیری‌شده مرتب از آن بیشتر می‌شود هدف نیست، امید است؛ پهنای باند، RGWهای sync بیشتر یا یک sync policy که bucketهای کم‌اهمیت را کنار بگذارد اضافه کنید.
:::

آزمایشگاه multisite زیر تأخیر تکثیر پس از قطعی پیوند را مدل می‌کند؛ چند مقدار پهنای باند و مدت قطعی را امتحان کنید تا ببینید جبران عقب‌ماندگی چقدر طول می‌کشد.

::: {.sim name="multisite"}
:::

# پایش sync

## دستورها

```bash
radosgw-admin sync status
radosgw-admin bucket sync status --bucket=photos
radosgw-admin sync error list
radosgw-admin metadata sync status
radosgw-admin data sync status --source-zone=eu-1
radosgw-admin sync info
```

`sync status` نخستین بررسی است (فصل ۵، [sync status](#sec-05-6-1)). برای فراداده باید «metadata is caught up with master» و برای هر zone مبدأ «data is caught up with source» بگوید. «behind shards» شاردهایی را فهرست می‌کند که عقب‌اند و «oldest incremental change not applied» زمان قدیمی‌ترین تغییری را نشان می‌دهد که هنوز منتظر است: فاصله‌ی آن زمان تا اکنون RPO فعلی شما برای آن مبدأ است.

`bucket sync status` همین را برای یک bucket نشان می‌دهد که وقتی کلاینتی از نبود یک شیء خبر می‌دهد مفید است. `sync error list` شیءهایی را که sync آن‌ها شکست خورده همراه با کد خطا نگه می‌دارد؛ فهرستی که بزرگ‌تر می‌شود یعنی مشکلی واقعی (مجوزهای کاربر سیستمی، placement target ناموجود، poolی که پر شده است). پس از رفع علت و sync شدن شیءها، ورودی‌های قدیمی را با `radosgw-admin sync error trim` پاک کنید.

## سنجه‌ها

هر RGW برای هر zone مبدأ شمارنده‌های sync را در مجموعه‌ی `data-sync-from-<zone>` نگه می‌دارد: `fetch_bytes`، `fetch_errors`، `poll_latency` و `poll_errors`. از Tentacle شمارنده‌های `rgw_sync_delta` مقدار `sync_delta` را گزارش می‌کنند، یعنی تأخیر هر شارد data log به ثانیه، که مستقیم‌ترین سنجه‌ی RPO است:

```bash
ceph daemon client.rgw.eu2.host1.abcdef perf dump
```

برای این‌ها هشدار بگذارید: `sync status` که بیش از هدف RPO شما caught up نیست، `sync error list` که بزرگ‌تر می‌شود، `fetch_errors` یا `poll_errors` که پیوسته زیاد می‌شوند، و zone مقصدی که هیچ RGWی در آن sync نمی‌کند (مثلاً چون `rgw_run_sync_thread` روی همه‌ی RGWهای آن zone false است، نه فقط روی آن‌هایی که به کلاینت سرویس می‌دهند). خروجی Prometheus در manager شمارنده‌های RGW را ارائه می‌دهد، پس همین مقدارها را می‌توان نمودار کرد (فصل ۲۰).

# جابه‌جایی برنامه‌ریزی‌شده

جابه‌جایی (switchover) zone اصلی را در حالی جابه‌جا می‌کند که هر دو site سالم‌اند: پیش از نگهداری site اصلی یا به‌عنوان تمرین. چون هر دو site بالا هستند، لازم نیست داده‌ای از دست برود.

1. یک بازه‌ی زمانی اعلام کنید و تغییر کاربران، bucketها و سیاست‌ها را متوقف کنید.
2. کلاینت‌ها را فقط‌خواندنی کنید یا نوشتن روی zone اصلی فعلی را متوقف کنید و صبر کنید تا `radosgw-admin sync status` روی zone ثانویه برای فراداده و داده caught up بگوید.
3. روی zone ثانویه آن را master کنید و period را commit کنید (دستورهای پس از این فهرست).
4. RGWهای هر دو zone را دوباره راه بیندازید یا بگذارید period تازه را بردارند (در cephadm: `ceph orch restart rgw.<service>`).
5. DNS یا GSLB را طوری تغییر دهید که کلاینت‌ها به master تازه برسند و سپس دوباره اجازه‌ی نوشتن بدهید.
6. `radosgw-admin period get` را در هر دو site بررسی کنید: همان شناسه و epoch برای period، و `master_zone` برابر eu-2.

```bash
radosgw-admin zone modify --rgw-zone=eu-2 --master --default
radosgw-admin period update --commit
```

اگر هم‌زمان endpointهای zone هم تغییر می‌کنند (load balancer تازه، نام تازه)، آن‌ها را در zone و zonegroup به‌روز کنید و دوباره commit کنید؛ zoneهای دیگر برای sync از همین endpointها استفاده می‌کنند:

```bash
radosgw-admin zone modify --rgw-zone=eu-2 --endpoints=https://s3-eu2.example.com
radosgw-admin zonegroup modify --rgw-zonegroup=eu --endpoints=https://s3.example.com
radosgw-admin period update --commit
```

# Failover برنامه‌ریزی‌نشده

وقتی site اصلی از دست می‌رود، zoneهای دیگر همچنان سرویس می‌دهند و داده‌ی شیء را برای bucketهای موجود می‌پذیرند، ولی هر چیزی که به zone اصلی نیاز دارد (کاربران و bucketهای تازه، تغییر سیاست‌ها) شکست می‌خورد. اگر قطعی طولانی خواهد بود، zone ثانویه را ارتقا دهید (فصل ۵، [وقتی zone اصلی از دسترس خارج می‌شود](#sec-05-10-1)):

1. از کار افتادن را از دو مسیر مستقل تأیید کنید، مثلاً پایش و تیم site. یک تقسیم شبکه از یک سو درست مانند از کار افتادن site دیده می‌شود.
2. مطمئن شوید master قدیمی نمی‌تواند نوشتن بپذیرد: RGWهای آن را متوقف کنید یا آن را در load balancer جدا کنید. این مهم‌ترین گام در برابر split brain است.
3. آخرین زمان «oldest incremental change not applied» را روی zone ثانویه یادداشت کنید: این RPO شما در این حادثه است.
4. مانند جابه‌جایی برنامه‌ریزی‌شده ارتقا دهید و commit کنید و سپس RGWهای آن zone را دوباره راه بیندازید.
5. DNS یا GSLB را به master تازه بفرستید.
6. به صاحبان سرویس بگویید کدام بازه‌ی داده ممکن است کم باشد.

# Failback و همگام‌سازی دوباره

وقتی site قدیمی برمی‌گردد، هنوز خودش را master می‌داند. پیش از آنکه RGWهای آن ترافیک کلاینت بگیرند، period تازه را به آن بدهید:

```bash
radosgw-admin realm pull --url=https://s3-eu2.example.com --access-key=<AK> --secret=<SK>
radosgw-admin period pull --url=https://s3-eu2.example.com --access-key=<AK> --secret=<SK>
radosgw-admin sync status
```

سپس RGWهای آن را راه بیندازید و بگذارید عقب‌ماندگی را جبران کند. شیءهایی که پیش از خرابی روی master قدیمی نوشته شده ولی هنوز تکثیر نشده بودند همچنان در poolهای آن هستند؛ data sync آن‌ها را وقتی لاگ‌های ثبت‌کننده‌شان پردازش شوند به zone دیگر تکثیر می‌کند. اگر وضعیت sync در zone بازگشته آسیب دیده باشد یا آن‌قدر دور بوده که لاگ‌های راه دور trim شده‌اند، یک sync کامل از zone دیگر شروع کنید. این کار امن است ولی کل داده را دوباره می‌خواند، پس پهنای باند را برنامه‌ریزی کنید:

```bash
radosgw-admin data sync init --source-zone=eu-2
radosgw-admin metadata sync init
radosgw-admin bucket sync init --bucket=photos --source-zone=eu-2
radosgw-admin bucket sync run --bucket=photos --source-zone=eu-2
```

پس از `init`، RGWهای آن zone را دوباره راه بیندازید تا threadهای sync از وضعیت تازه شروع کنند. وقتی `sync status` در هر دو جهت caught up شد، می‌توانید master را با یک جابه‌جایی برنامه‌ریزی‌شده برگردانید.

# Split brain

split brain در multisite دو شکل دارد:

- **دو master.** اگر هنگام تقسیم شبکه هر دو site خودشان را ارتقا دهند، دو تاریخچه‌ی period پدید می‌آید. zoneی که period دیگری را pull کند تغییرات فراداده‌ی خودش در این فاصله را از دست می‌دهد. با همان قاعده‌ی بالا جلویش را بگیرید: فقط یک site اجازه‌ی ارتقا دارد، و فقط پس از توقف master قدیمی؛ پس از پایان تقسیم، site بازگشته پیش از هر کار دیگری period را pull می‌کند.
- **نوشتن‌های متعارض روی شیء.** در حالت active-active هر دو zone نوشتن می‌پذیرند. وقتی یک شیء هنگام تقسیم در هر دو نوشته شود، data sync شیء را فقط وقتی کپی می‌کند که از نسخه‌ی محلی تازه‌تر باشد (`copy_if_newer` در کد sync)، پس نسخه‌ای با زمان تغییر تازه‌تر برنده می‌شود و نوشتن دیگر از دست می‌رود؛ با نسخه‌بندی هر دو نسخه نگه داشته می‌شوند. ساعت همه‌ی میزبان‌های RGW را با NTP هماهنگ نگه دارید و برای هر برنامه یک zone اصلی برای نوشتن تعیین کنید.

حذف bucket هم تکثیر می‌شود: bucketی که در یک سو حذف شود در سوی دیگر هم حذف می‌شود. از bucketهای مهم با نسخه‌بندی، Object Lock، یک archive zone یا یک پشتیبان جدا محافظت کنید.

# sync فراداده و sync داده

| | sync فراداده | sync داده |
|---|---|---|
| چه چیزی | کاربران، bucketها (entry point و instance)، نقش‌ها، حساب‌ها | شیءها و نسخه‌هایشان |
| جهت | از zone اصلی realm به همه‌ی zoneهای دیگر | میان zoneهای یک zonegroup، هر zone از دیگران pull می‌کند |
| لاگ | mdlog (به تعداد `rgw_md_log_max_shards` شارد) | datalog (به تعداد `rgw_data_log_num_shards` شارد) و لاگ‌های شاخص bucket |
| وضعیت | `metadata sync status` | `data sync status`، `bucket sync status` |
| sync کامل دوباره | `metadata sync init` | `data sync init`، `bucket sync init` |

فصل ۴۲ هر دو موتور را در کد توضیح می‌دهد ([sync فراداده](#sec-42-6)، [موتور sync داده](#sec-42-5)) و [periodها و commit](#sec-42-2) توضیح می‌دهد چرا commit روی یک master تازه period تازه‌ای می‌سازد.

# sync policy و archive zone

sync policy (فصل ۵، [sync policy](#sec-05-11)) با groupها، flowها و pipeها تعیین می‌کند کدام bucketها و در کدام جهت تکثیر شوند. یک سیاست در سطح zonegroup که sync را مجاز می‌کند، همراه با یک سیاست در سطح bucket که آن را فقط برای bucketهای انتخابی روشن می‌کند، تأخیر تکثیر را برای داده‌ی مهم پایین نگه می‌دارد:

```bash
radosgw-admin sync group create --group-id=group1 --status=allowed
radosgw-admin sync group flow create --group-id=group1 --flow-id=flow1 --flow-type=symmetrical --zones=eu-1,eu-2
radosgw-admin sync group pipe create --group-id=group1 --pipe-id=pipe1 --source-zones='*' --source-bucket='*' --dest-zones='*' --dest-bucket='*'
radosgw-admin period update --commit
radosgw-admin sync group create --bucket=photos --group-id=photos-sync --status=enabled
radosgw-admin sync group pipe create --bucket=photos --group-id=photos-sync --pipe-id=pipe1 --source-zones='*' --dest-zones='*'
```

یک **archive zone** (فصل ۵، [archive zone](#sec-05-12)) داده‌ی zoneهای دیگر را می‌گیرد و همه‌ی نسخه‌های هر شیء را نگه می‌دارد، حتی پس از اینکه شیء در zoneهای دیگر حذف یا بازنویسی شود. خط دوم خوبی در برابر اشتباه است، ولی پشتیبان کامل نیست: در همان realm است و با همان کلیدها مدیریت می‌شود.

```bash
radosgw-admin zone create --rgw-zonegroup=eu --rgw-zone=eu-archive --endpoints=https://s3-archive.example.com --tier-type=archive
radosgw-admin period update --commit
```

# mirroring در RBD

فصل ۱۸ rbd-mirror را راه‌اندازی می‌کند ([rbd-mirror](#sec-18-3))؛ اینجا بخش failover آن است. حالت journal هر نوشتن را کپی می‌کند و RPO چندثانیه‌ای می‌دهد؛ حالت snapshot اختلاف میان snapshotهای mirror را کپی می‌کند و RPO آن به اندازه‌ی بازه‌ی زمان‌بندی است.

```bash
rbd mirror pool status vmpool --verbose
rbd mirror image status vmpool/db01
```

**جابه‌جایی برنامه‌ریزی‌شده**: برنامه را در site A متوقف کنید، سپس در A demote و در B promote کنید؛ image سازگار می‌ماند و چیزی از دست نمی‌رود:

```bash
rbd mirror image demote vmpool/db01
rbd mirror image promote vmpool/db01
```

دستور اول را در site A و دستور دوم را در site B اجرا کنید، پس از آنکه `rbd mirror image status` در B نشان داد image همگام است. `rbd mirror pool demote vmpool` و `rbd mirror pool promote vmpool` همین کار را برای همه‌ی imageهای mirrorشده‌ی یک pool انجام می‌دهند.

**failover برنامه‌ریزی‌نشده**: site A از دست رفته است، پس image را نمی‌توان به‌طور تمیز demote کرد؛ ارتقا را در B اجباری کنید:

```bash
rbd mirror image promote --force vmpool/db01
```

**Failback**: وقتی site A برمی‌گردد، نسخه‌ی image آن هم primary است، پس دو نسخه از هم جدا شده‌اند. primary قدیمی را در A demote کنید و آن را از B دوباره همگام کنید؛ resync نسخه‌ی A را کنار می‌گذارد و image را دوباره کپی می‌کند:

```bash
rbd mirror image demote vmpool/db01
rbd mirror image resync vmpool/db01
```

وقتی A دوباره همگام شد، با یک جابه‌جایی برنامه‌ریزی‌شده برگردید. هرگز در حالی که هر دو site در دسترس کلاینت‌ها هستند در هر دو promote نکنید: دو primary با نوشتن در هر دو، split brain در سطح بلاک است و نوشتن‌های یک سو با resync کنار گذاشته می‌شوند. `rbd_mirroring_replay_delay` می‌تواند replay را در site ثانویه به تأخیر بیندازد و فرصتی بدهد تا جلوی رسیدن یک اشتباه به آن گرفته شود.

# mirroring در CephFS

mirroring اسنپ‌شات CephFS (فصل ۶، [mirroring اسنپ‌شات میان کلاسترها](#sec-06-8-1)) snapshotهای دایرکتوری‌های انتخابی را با daemon به نام cephfs-mirror به کلاستری دیگر کپی می‌کند. برای هر peer یک‌طرفه است و برای نسخه‌های DR ساخته شده، نه برای یک فایل‌سیستم active-active:

```bash
ceph mgr module enable mirroring
ceph orch apply cephfs-mirror
ceph fs snapshot mirror enable cephfs
ceph fs snapshot mirror peer_bootstrap create cephfs client.mirror_remote site-b
ceph fs snapshot mirror add cephfs /projects
ceph fs snapshot mirror daemon status
```

از Umbrella ماژول mirroring سنجه‌های sync هر دایرکتوری (آخرین snapshot همگام‌شده، مدت sync و شکست‌ها) را بدون دسترسی به daemon به نام cephfs-mirror هم گزارش می‌کند؛ ساده‌ترین راه برای اندازه‌گیری RPO در CephFS هنگام تمرین:

```bash {since=umbrella}
ceph fs snapshot mirror status cephfs /projects
```

RPO برابر بازه‌ی snapshotهاست (مثلاً با `snap_schedule`). برای failover نسخه را در کلاستر دیگر mount کنید؛ از دید mirror این نسخه فقط‌خواندنی است، پس پس از failover پیش از نوشتن در آن mirroring را برای آن دایرکتوری خاموش کنید و برای failback، mirroring را در جهت مخالف راه بیندازید.

# stretch mode یا multisite؟

stretch mode (فصل ۱۸، [stretch mode: یک کلاستر در دو site](#sec-18-7)) یک کلاستر را در دو site داده با یک monitor به‌عنوان tiebreaker در site سوم نگه می‌دارد: نوشتن‌ها پیش از تأیید به هر دو site می‌روند، پس RPO صفر است و failover خودکار. به تأخیر کم میان siteها (چند میلی‌ثانیه) نیاز دارد و در برابر از دست رفتن یک site محافظت می‌کند، نه در برابر اشتباه، باگ یا مشکل ارتقا در کلاستر، چون فقط یک کلاستر هست. multisite و mirroring کلاسترهای مستقل را با RPO بزرگ‌تر از صفر و failover دستی نگه می‌دارند، ولی مشکلی در یک کلاستر به دیگری نمی‌رسد. برای فاصله‌های زیاد از multisite و mirroring استفاده کنید؛ برای دو site نزدیک که RPO صفر لازم دارند stretch mode را، و در هر دو حالت یک پشتیبان مستقل نگه دارید.

# runbook تمرین DR

دست‌کم سالی دو بار و پس از هر تغییر بزرگ در توپولوژی یک تمرین اجرا کنید. تمرینی که زمان‌سنجی و ثبت نشود انجام نشده است.

**پیش از تمرین**

1. دامنه را انتخاب کنید: فقط یک جابه‌جایی برنامه‌ریزی‌شده، یا شبیه‌سازی از دست رفتن یک site (توقف RGWها و rbd-mirror آن یا قطع پیوند).
2. هدف‌های RPO و RTO و اینکه چه کسی درباره‌ی failover تصمیم می‌گیرد را بنویسید.
3. بررسی کنید که runbook، کلیدهای کاربر سیستمی (نگه‌داری‌شده به شیوه‌ی [پیوست ی](#appK)) و دسترسی به DNS از site ثانویه در دسترس باشند.
4. داده‌ی آزمایشی با محتوا و زمان معلوم بسازید: هر دقیقه یک شیء در یک bucket آزمایشی، و یک image آزمایشی RBD با یک حلقه‌ی نوشتن در حال اجرا.

**در طول تمرین**

1. زمان هر گام را ثبت کنید: تشخیص، تصمیم، ارتقا، commit کردن period، تغییر DNS، نخستین درخواست موفق کلاینت.
2. پس از هر commit، `period get` را در همه‌ی siteها بررسی کنید.
3. آخرین شیء آزمایشی و آخرین نوشتن RBD را که به site ثانویه رسیده پیدا کنید؛ فاصله‌ی آن تا زمان خرابی RPO اندازه‌گیری‌شده است.

**پس از تمرین**

1. failback کنید، صبر کنید تا `sync status` و `rbd mirror pool status` در هر دو جهت سالم باشند و داده‌ی آزمایشی را پاک کنید.
2. RPO و RTO اندازه‌گیری‌شده را با هدف‌ها مقایسه کنید و آنچه کند یا نامشخص بود ثبت کنید.
3. runbook، هشدارها و این فهرست بررسی را به‌روز کنید.

## فهرست بررسی

| بررسی | دستور یا جا | مقدار مورد انتظار |
|---|---|---|
| period یکسان در همه‌جا | `radosgw-admin period get` | یک شناسه و epoch برای period، و `master_zone` مورد انتظار |
| فراداده و داده caught up | `radosgw-admin sync status` | «caught up» برای فراداده و هر مبدأ |
| خطاهای sync رو به افزایش نیستند | `radosgw-admin sync error list` | خالی، یا فقط ورودی‌های قدیمی و شناخته‌شده |
| تأخیر در حد هدف RPO | `sync_delta` (از Tentacle)، «oldest incremental change not applied» | کمتر از هدف RPO |
| endpointها درست‌اند | `radosgw-admin zonegroup get` | endpointها به RGWهای هر zone می‌رسند |
| mirroring در RBD سالم است | `rbd mirror pool status --verbose` | `health: OK` و همه‌ی imageها در حال replay |
| mirroring در CephFS سالم است | `ceph fs snapshot mirror daemon status` | peerها وصل‌اند و دایرکتوری شکست‌خورده‌ای نیست |
| DNS آماده است | کنسول DNS یا GSLB | TTL کوتاه، دسترسی از site ثانویه |
| کلیدها در دسترس‌اند | انبار اسرار | کلیدهای کاربر سیستمی و یک keyring مدیر برای هر site |
| پشتیبان مستقل است | سامانه‌ی پشتیبان | آخرین پشتیبان در بازه‌ی خودش، محافظت‌شده در برابر حذف |

# منابع

- RGW multisite: https://docs.ceph.com/en/latest/radosgw/multisite/
- sync policy در multisite: https://docs.ceph.com/en/latest/radosgw/multisite-sync-policy/
- archive zone: https://docs.ceph.com/en/latest/radosgw/archive-sync-module/
- mirroring در RBD: https://docs.ceph.com/en/latest/rbd/rbd-mirroring/
- mirroring اسنپ‌شات CephFS: https://docs.ceph.com/en/latest/cephfs/cephfs-mirroring/
- stretch mode: https://docs.ceph.com/en/latest/rados/operations/stretch-mode/
- شمارنده‌های sync (`src/rgw/driver/rados/rgw_sync_counters.cc`): https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_sync_counters.cc
