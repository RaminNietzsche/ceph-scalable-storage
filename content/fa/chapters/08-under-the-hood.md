---
chapter: 8
id: ch08
title: "Ceph از درون: CRUSH، نقشه‌ها، احراز هویت و PGها"
part: main
lang: fa
---

# پیش از شروع {#sec-08-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-08-1-1}

تا اینجا Ceph را از بیرون دیدیم: دستورها، سرویس‌ها و رابط‌ها. این فصل به درون می‌رود. هر تصمیم مهم در طراحی و عیب‌یابی Ceph (چرا داده آنجاست، چرا PG گیر کرده، چرا یک قانون CRUSH جواب نمی‌دهد) به چند سازوکار پایه برمی‌گردد که در این فصل بررسی می‌کنیم:

- داده چطور بدون جدول مرکزی جای خودش را پیدا می‌کند؟
- نقشه‌ی CRUSH چه ساختاری دارد و قانون‌ها را چطور بنویسیم؟
- tunableها چه هستند و چرا هشدار «non-optimal tunables» می‌آید؟
- نقشه‌های کلاستر کدام‌اند و MONها چطور دسترس‌پذیر می‌مانند؟
- cephx چطور کار می‌کند و capabilityها را چطور محدود کنیم؟
- مسیر یک نوشتن از کلاینت تا دیسک چیست و PGها چه حالت‌هایی دارند؟
- چطور یک pool را روی OSDهای خاص قرار دهیم؟

# مقیاس‌پذیری بدون جدول مرکزی {#sec-08-2}

## مسئله‌ی جاشناسی {#sec-08-2-1}

بیشتر سامانه‌های ذخیره‌سازی توزیع‌شده‌ی قدیمی یک سرور فراداده یا جدول جست‌وجو داشتند که می‌گفت هر بلوک کجاست. این جدول در مقیاس بزرگ سه مشکل دارد: گلوگاه کارایی می‌شود، نقطه‌ی شکست واحد است و با هر تغییر سخت‌افزار باید به‌روز شود. Ceph این جدول را حذف کرده است: **هر کلاینت و هر OSD خودش محل داده را محاسبه می‌کند**. ورودی‌های این محاسبه فقط نام شیء، شناسه‌ی pool و نقشه‌ی کلاستر هستند که همه آن را دارند.

![دو مرحله‌ی جاشناسی: نام شیء با hash به یک PG نگاشت می‌شود و CRUSH آن PG را به مجموعه‌ای از OSDها نگاشت می‌کند](figures/ch08/f01_place.png){#fig-08-f01_place}

## دو مرحله‌ی نگاشت {#sec-08-2-2}

1. **شیء به PG**: نام شیء hash می‌شود و باقیمانده‌ی آن بر تعداد PGهای pool (به‌صورت دقیق‌تر با الگوریتم stable mod) شماره‌ی PG را می‌دهد. شناسه‌ی PG ترکیب شماره‌ی pool و شماره‌ی PG است، مثل `3.1f`.
2. **PG به OSD**: الگوریتم CRUSH با ورودی شناسه‌ی PG، نقشه‌ی CRUSH و قانون pool، فهرست مرتبی از OSDها را برمی‌گرداند. اولین OSD فعال، **primary** است.

```bash
ceph osd map rbd rbd_data.12ab.0000000000000004
# osdmap e1234 pool 'rbd' (3) object '...' -> pg 3.8c7e1b1f (3.1f) -> up ([12,4,27], p12) acting ([12,4,27], p12)
ceph pg map 3.1f
```

::: {.deep}
چرا لایه‌ی میانی PG؟ اگر CRUSH را مستقیماً روی هر شیء اجرا می‌کردیم، کلاستر برای هر شیء باید وضعیت تکثیر، بازیابی و scrub را جداگانه پیگیری می‌کرد؛ برای میلیاردها شیء غیرممکن است. PGها اشیا را به چند هزار گروه تقسیم می‌کنند و همه‌ی سازوکارهای حفاظت داده (peering، log، بازیابی، scrub) در سطح PG کار می‌کنند. تعداد PG یک مصالحه است: کم باشد، توزیع ناهموار می‌شود؛ زیاد باشد، حافظه و CPU OSDها و بار peering بالا می‌رود.
:::

## up و acting {#sec-08-2-3}

`up set` خروجی خالص CRUSH است. `acting set` مجموعه‌ای است که واقعاً به درخواست‌ها پاسخ می‌دهد. این دو معمولاً یکسان‌اند؛ تفاوتشان یعنی Ceph موقتاً از OSDهای دیگری استفاده می‌کند (مثلاً **pg_temp** در حین backfill تا OSD جدید داده را کامل بگیرد) یا یک **upmap** صریح، نتیجه‌ی CRUSH را برای آن PG تغییر داده است.

# سازوکار CRUSH {#sec-08-3}

## سلسله‌مراتب {#sec-08-3-1}

![یک سلسله‌مراتب CRUSH نمونه: root، datacenter، rack، host و OSDها با کلاس دستگاه](figures/ch08/f02_hier.png){#fig-08-f02_hier}

نقشه‌ی CRUSH از دو بخش تشکیل شده است: **سلسله‌مراتب** (درختی از bucketها که مکان فیزیکی هر OSD را نشان می‌دهد) و **قانون‌ها** (rules) که می‌گویند نسخه‌ها را چطور در این درخت پخش کنیم. انواع پیش‌فرض bucket از پایین به بالا عبارت‌اند از osd، host، chassis، rack، row، pdu، pod، room، datacenter، zone، region و root. لازم نیست از همه استفاده کنید؛ فقط سطوحی را تعریف کنید که واقعاً دامنه‌ی خرابی مستقل‌اند.

```bash
ceph osd crush tree --show-shadow
ceph osd crush add-bucket rack1 rack
ceph osd crush move rack1 root=default
ceph osd crush move ceph-node1 rack=rack1
ceph osd crush set-device-class nvme osd.20
ceph osd crush class ls
```

::: {.tip}
با cephadm می‌توانید مکان CRUSH میزبان را در spec میزبان (`location: {rack: rack1}`) تعیین کنید تا OSDهای تازه مستقیماً زیر rack درست قرار بگیرند. در غیر این صورت هر OSD زیر host و مستقیماً زیر `root=default` می‌رود و پس از جابه‌جایی دستی، داده یک بار دیگر حرکت می‌کند.
:::

## وزن {#sec-08-3-2}

هر OSD یک **وزن CRUSH** دارد (به‌طور پیش‌فرض برابر ظرفیت به ترابایت) و وزن هر bucket مجموع وزن فرزندان آن است. CRUSH داده را به نسبت وزن پخش می‌کند. وزن دیگری به نام **reweight** (بین ۰ و ۱) هم وجود دارد که برای اصلاح موقت توزیع به کار می‌رفت؛ امروز balancer با upmap این کار را دقیق‌تر انجام می‌دهد.

```bash
ceph osd crush reweight osd.20 3.49309     # وزن دائمی CRUSH
ceph osd reweight 20 0.9                   # اصلاح موقت (ترجیحاً از balancer استفاده کنید)
```

## الگوریتم bucket {#sec-08-3-3}

CRUSH برای انتخاب فرزند در هر bucket الگوریتمی دارد. امروز عملاً فقط **straw2** استفاده می‌شود (از Hammer، پیش‌فرض bucketهای تازه). مزیت کلیدی straw2 این است که تغییر وزن یک آیتم فقط داده را بین آن آیتم و بقیه جابه‌جا می‌کند، نه بین آیتم‌های دیگر؛ یعنی حداقل جابه‌جایی لازم.

## قانون‌ها {#sec-08-3-4}

قانون CRUSH مراحل انتخاب را تعریف می‌کند. بیشتر وقت‌ها لازم نیست قانون را دستی بنویسید؛ دستورهای کمکی کافی‌اند:

```bash
# تکثیری: نسخه‌ها در hostهای مختلف، فقط روی SSD
ceph osd crush rule create-replicated rep-ssd-host default host ssd
# تکثیری با دامنه‌ی خرابی rack
ceph osd crush rule create-replicated rep-rack default rack
# EC از روی پروفایل
ceph osd erasure-code-profile set ec42-rack k=4 m=2 crush-failure-domain=rack crush-device-class=hdd
ceph osd crush rule create-erasure ec42-rack ec42-rack
ceph osd crush rule ls
ceph osd crush rule dump rep-ssd-host
```

برای حالت‌های پیچیده‌تر، نقشه را استخراج، ویرایش و پیش از اعمال آزمایش کنید:

```bash
ceph osd getcrushmap -o crush.bin
crushtool -d crush.bin -o crush.txt
# ویرایش crush.txt
crushtool -c crush.txt -o crush.new
crushtool -i crush.new --test --rule 1 --num-rep 3 --show-statistics --show-bad-mappings
ceph osd setcrushmap -i crush.new
```

نمونه‌ی یک قانون دستی که دو نسخه را در یک datacenter و نسخه‌ی سوم را در datacenter دیگر می‌گذارد:

```text
rule rep-2dc {
    id 5
    type replicated
    step take default
    step choose firstn 2 type datacenter
    step chooseleaf firstn 2 type host
    step emit
}
```

::: {.warn}
قانون بالا با `size=3` دو نسخه در datacenter اول و یک نسخه در دومی می‌گذارد، اما **کدام datacenter دو نسخه می‌گیرد** برای هر PG متفاوت است. اگر می‌خواهید هر دو سایت قطعاً نسخه داشته باشند و نوشتن هنگام قطع یک سایت ادامه یابد، به جای قانون دستی از **stretch mode** (فصل ۱۸) استفاده کنید که منطق quorum و min_size را هم مدیریت می‌کند.
:::

::: {.note}
Squid نوع تازه‌ای از قانون به نام **MSR** (Multi-Step Retry) اضافه کرد که به گفته‌ی یادداشت‌های انتشار، پیکربندی‌های انعطاف‌پذیرتری برای EC ممکن می‌کند؛ کاربرد رایج آن قرار دادن کنترل‌شده‌ی چند shard در یک دامنه‌ی خرابی است وقتی تعداد دامنه‌ها کمتر از `k+m` است. چون این نوع قانون در نقشه‌ی CRUSH ثبت می‌شود، `require_min_compat_client` هم روی آن اثر دارد؛ پیش از استفاده نسخه‌ی کلاینت‌ها را بررسی کنید.
:::

## کلاس دستگاه و shadow tree {#sec-08-3-5}

از Luminous هر OSD یک **کلاس دستگاه** (hdd، ssd، nvme یا هر نام دلخواه) دارد. CRUSH برای هر کلاس یک درخت سایه (shadow) می‌سازد، مثلاً `default~ssd`، که فقط OSDهای آن کلاس را دارد. قانونی که کلاس دارد روی همین درخت سایه اجرا می‌شود. این قابلیت جایگزین ترفند قدیمی کتاب ۲۰۱۹ است که برای جدا کردن SSD و HDD دو root جدا می‌ساخت.

# tunableها {#sec-08-4}

## چرا tunable؟ {#sec-08-4-1}

CRUSH از ابتدا کامل نبود. در برخی سلسله‌مراتب‌ها (مثلاً درخت‌های کوچک یا وقتی OSDهای زیادی out هستند) نمی‌توانست برای همه‌ی PGها نسخه‌ی کافی پیدا کند، یا با تغییرات کوچک داده‌ی زیادی را جابه‌جا می‌کرد. اصلاح این رفتارها نتیجه‌ی نگاشت را تغییر می‌دهد، پس نمی‌شد آن‌ها را بی‌صدا اعمال کرد: هر کلاینت باید همان نتیجه‌ای را محاسبه کند که OSDها محاسبه می‌کنند. راه‌حل Ceph، **tunable**هاست: پرچم‌هایی در نقشه‌ی CRUSH که رفتار الگوریتم را تعیین می‌کنند و به‌صورت **پروفایل**هایی به نام نسخه‌ها گروه‌بندی شده‌اند.

| پروفایل | ویژگی اصلی | حداقل هسته‌ی کلاینت (طبق مستندات) |
|---|---|---|
| argonaut (legacy) | رفتار اولیه | همه |
| bobtail (CRUSH_TUNABLES2) | کاهش شکست در یافتن نگاشت و اصلاح retryها | ۳.۹ |
| firefly (CRUSH_TUNABLES3) | اصلاح رفتار chooseleaf با پیمایش دوباره | ۳.۱۵ |
| hammer (CRUSH_V4) | bucket نوع straw2 | ۴.۱ |
| jewel (CRUSH_TUNABLES5) | chooseleaf_stable: جابه‌جایی کمتر هنگام out شدن OSD | ۴.۵ |

```bash
ceph osd crush show-tunables
ceph osd crush tunables optimal       # جابه‌جایی داده دارد!
ceph features                         # نسخه و قابلیت‌های کلاینت‌های متصل
ceph osd get-require-min-compat-client
```

::: {.warn}
تغییر پروفایل tunable روی کلاستر پرداده، بخش بزرگی از داده را جابه‌جا می‌کند. این کار را در ساعات کم‌بار، با پروفایل mClock مناسب و پس از اطمینان از سازگاری همه‌ی کلاینت‌ها (به‌ویژه کلاینت‌های هسته‌ی قدیمی RBD و CephFS) انجام دهید. کلاسترهایی که با نسخه‌های جدید ساخته شده‌اند از ابتدا tunableهای بهینه دارند و این بخش بیشتر برای کلاسترهای قدیمیِ ارتقایافته اهمیت دارد.
:::

## هشدار non-optimal {#sec-08-4-2}

اگر tunableهای کلاستر از پروفایل بهینه‌ی نسخه‌ی فعلی عقب باشند، هشدار `OLD_CRUSH_TUNABLES` نمایش داده می‌شود. می‌توانید آن را با به‌روزرسانی tunableها رفع کنید یا، اگر کلاینت قدیمی دارید که نمی‌توانید ارتقا دهید، با `mon_warn_on_legacy_crush_tunables=false` موقتاً خاموش کنید. هشدار مشابه `OLD_CRUSH_STRAW_CALC_VERSION` هم وقتی ظاهر می‌شود که نقشه هنوز از نسخه‌ی قدیمی و معیوب محاسبه‌ی وزن در bucketهای straw استفاده کند.

```bash
# تبدیل bucketهای straw به straw2 با حداقل جابه‌جایی
ceph osd crush set-all-straw-buckets-to-straw2
```

# نقشه‌های کلاستر و MONها {#sec-08-5}

![نقشه‌های کلاستر در MONها نگهداری و با epoch نسخه‌گذاری می‌شوند؛ کلاینت‌ها و OSDها نقشه‌ی جدید را از MON یا از یکدیگر می‌گیرند](figures/ch08/f03_maps.png){#fig-08-f03_maps}

## نقشه‌ها {#sec-08-5-1}

وضعیت کلاستر در چند نقشه نگهداری می‌شود که همه با یک **epoch** (شماره‌ی نسخه‌ی صعودی) نسخه‌گذاری شده‌اند:

| نقشه | محتوا | دستور مشاهده |
|---|---|---|
| MonMap | fsid، فهرست MONها و آدرس‌هایشان | `ceph mon dump` |
| OSDMap | poolها، OSDها و وضعیت up/in، pg_temp و upmapها، پرچم‌ها و نقشه‌ی CRUSH | `ceph osd dump` |
| MgrMap | MGR فعال، آماده‌به‌کارها و ماژول‌ها | `ceph mgr dump` |
| FSMap | فایل‌سیستم‌ها و MDSها | `ceph fs dump` |
| PGMap | آمار PGها (در MGR، نه MON) | `ceph pg dump` |

::: {.deep}
OSDها نقشه‌ی جدید را لزوماً از MON نمی‌گیرند: هر پیام بین OSDها و کلاینت‌ها epoch فرستنده را دارد و طرفی که نقشه‌ی جدیدتری دارد، تغییرات (incremental) را برای دیگری می‌فرستد. این «شایعه‌پراکنی» (gossip) بار MONها را کم می‌کند. پیامد عملی: OSDی که مدتی خاموش بوده باید هنگام بالا آمدن همه‌ی epochهای از دست رفته را پردازش کند، و اگر MONها epochهای قدیمی را نگه داشته باشند (مثلاً چون کلاستر مدت‌ها ناسالم بوده) پایگاه داده‌ی MON بزرگ می‌شود.
:::

## دسترس‌پذیری MONها {#sec-08-5-2}

MONها با الگوریتم **Paxos** اجماع می‌کنند: هر تغییر نقشه فقط وقتی معتبر است که اکثریت MONها (quorum) آن را بپذیرند. یکی از MONها **leader** است و بقیه peon.

```bash
ceph mon stat
ceph quorum_status -f json-pretty
ceph mon dump
ceph tell mon.ceph-node1 mon_status
```

| تعداد MON | اکثریت لازم | تحمل خرابی |
|---|---|---|
| ۱ | ۱ | ۰ |
| ۳ | ۲ | ۱ |
| ۵ | ۳ | ۲ |
| ۷ | ۴ | ۳ |

::: {.warn}
تعداد زوج MON تحمل خرابی را افزایش نمی‌دهد: چهار MON هم فقط یک خرابی را تحمل می‌کنند. MONها به ساعت دقیق حساس‌اند (هشدار `MON_CLOCK_SKEW`)؛ chrony یا NTP را روی همه‌ی گره‌ها پیکربندی و پایش کنید. پایگاه داده‌ی MON (RocksDB) را روی SSD قرار دهید و فضای دیسک آن را پایش کنید؛ وقتی فضای آزاد کم شود، هشدار `MON_DISK_LOW` و در نهایت توقف MON پیش می‌آید.
:::

::: {.note}
Umbrella سازوکار اختیاری **پشتیبان‌گیری و بازیابی RocksDB MON** را اضافه کرده است (تنظیم `mon_backup_interval`، دستور `ceph tell mon.* backup` و بازیابی آفلاین با `ceph-mon --restore-backup`). پیش از هر عملیات پرخطر روی MONها (حذف، بازسازی یا ارتقای اصلی) از این امکان یا از روش‌های مستند بازسازی پایگاه MON آگاه باشید؛ از دست رفتن همه‌ی MONها بدون پشتیبان، بدترین سناریوی Ceph است.
:::

# از درون کد: جای‌گذاری، احراز هویت و پیام‌رسانی {#sec-08-6}

## از نام شیء تا OSD {#sec-08-6-1}

![سه مرحله‌ی نگاشت شیء به OSD: در کلاینت، نام شیء با ceph_str_hash درهم‌سازی و با ceph_stable_mod به شماره‌ی PG تبدیل می‌شود؛ سپس شماره‌ی PG با شناسه‌ی pool ترکیب و به‌عنوان ورودی x به crush_do_rule داده می‌شود؛ در پایان OSDMap OSDهای ناموجود را حذف و upmap و pg_temp را اعمال می‌کند تا acting set و primary به دست آید](figures/ch08/s01_obj2osd.png){#fig-08-s01_obj2osd}

مرحله‌ی اول در `pg_pool_t::hash_key()` (`src/osd/osd_types.cc`) انجام می‌شود: نام شیء، و در صورت وجود namespace، با تابع درهم‌سازی pool (پیش‌فرض rjenkins) به یک عدد ۳۲بیتی تبدیل می‌شود. سپس این عدد با `ceph_stable_mod()` به بازه‌ی PGها نگاشت می‌شود. این تابع کوچک یکی از هوشمندانه‌ترین قطعه‌های Ceph است:

```c
/* from ceph/ceph, LGPL — src/include/rados.h (excerpt) */
static inline int ceph_stable_mod(int x, int b, int bmask)
{
	if ((x & bmask) < b)
		return x & bmask;
	else
		return x & (bmask >> 1);
}
```

`b` تعداد PGها و `bmask` کوچک‌ترین توان ۲ منهای یک است که دست‌کم `b` باشد. اگر pg_num توان ۲ نباشد (مثلاً ۱۲ با bmask=15)، مقادیر ۱۲ تا ۱۵ که PG متناظر ندارند به نیمه‌ی پایین (۴ تا ۷) «تا» می‌شوند. نتیجه‌ی مهم: وقتی pg_num از ۱۲ به ۱۳ افزایش می‌یابد، فقط اشیایی که به PG ۵ می‌رفتند و hash آن‌ها در ۱۳ می‌افتد جابه‌جا می‌شوند؛ یعنی تقسیم PG **محلی** است و همه‌ی داده بازچینی نمی‌شود. همین ویژگی است که افزایش تدریجی pg_num (از Nautilus) را ممکن کرده است.

::: {.note}
به همین دلیل، وقتی pg_num توان ۲ نیست، اندازه‌ی PGها نابرابر است: PGهای «تاشده» تقریباً دو برابر داده دارند. این یکی از دلایل توصیه‌ی توان ۲ و رفتار autoscaler است (فصل ۱۹).
:::

## straw2: انتخاب با کشیدن قرعه‌ی نمایی {#sec-08-6-2}

![الگوریتم straw2 در سه مرحله: برای هر آیتم bucket یک عدد شبه‌تصادفی شانزده‌بیتی از hash ورودی، شناسه‌ی آیتم و شماره‌ی تلاش ساخته و لگاریتم طبیعی آن با جدول محاسبه و بر وزن تقسیم می‌شود؛ آیتمی با بیشترین مقدار انتخاب می‌شود که از نظر ریاضی معادل انتخاب کمینه از متغیرهای نمایی با نرخ برابر وزن است و احتمال انتخاب هر آیتم را دقیقاً متناسب با وزن آن می‌کند؛ پیامد آن حداقل جابه‌جایی داده هنگام تغییر وزن است](figures/ch08/s02_straw2.png){#fig-08-s02_straw2}

`bucket_straw2_choose()` در `src/crush/mapper.c` برای هر آیتم bucket یک «قرعه» (draw) محاسبه و بزرگ‌ترین را انتخاب می‌کند. هسته‌ی محاسبه:

```c
/* from ceph/ceph, LGPL — src/crush/mapper.c, generate_exponential_distribution() (excerpt) */
unsigned int u = crush_hash32_3(type, x, y, z);
u &= 0xffff;
__s64 ln = crush_ln(u) - 0x1000000000000ll;
return div64_s64(ln, weight);
```

ریاضیات پشت آن (به بیان این کتاب): فرض کنید U یکنواخت در (۰، ۱] باشد. آنگاه `−ln(U) / w` متغیری نمایی با نرخ w است. کمینه‌ی چند متغیر نمایی مستقل با نرخ‌های w₁ تا wₙ، با احتمال `wᵢ / Σw` متعلق به آیتم i است. چون ln(U) منفی است، `ln(U)/w` بزرگ‌ترین مقدار را برای همان آیتمی دارد که `−ln(U)/w` کمینه است. بنابراین:

```text
draw_i = ln(u_i / 65536) / w_i          (u_i = hash(x, id_i, r) mod 2^16)
choose argmax_i draw_i   ⇒   P(i) = w_i / Σ_j w_j
```

`crush_ln()` لگاریتم را با جدول‌های ممیز ثابت (بدون ممیز شناور، چون همین کد در هسته‌ی لینوکس هم اجرا می‌شود) تقریب می‌زند؛ خروجی آن در بازه‌ی [0, 2⁴⁸) است و تفریق 2⁴⁸ آن را به مقدار منفی معادل ln(u/65536) تبدیل می‌کند. وزن‌ها در قالب 16.16 ممیز ثابت‌اند (۰x10000 یعنی ۱.۰).

::: {.deep}
چرا straw2 جابه‌جایی را کمینه می‌کند؟ draw هر آیتم فقط به hash خودش و **وزن خودش** بستگی دارد. اگر وزن آیتم A افزایش یابد، فقط draw آن بزرگ‌تر می‌شود؛ PGهایی که قبلاً A را انتخاب کرده بودند همچنان A را انتخاب می‌کنند و برخی PGهای دیگر به A منتقل می‌شوند، اما هیچ PGی بین دو آیتم دیگر (B و C) جابه‌جا نمی‌شود. در الگوریتم قدیمی straw، طول «نی»ها به وزن همه‌ی آیتم‌ها وابسته بود و این ویژگی برقرار نبود؛ به همین دلیل straw2 از Hammer معرفی و بعدها پیش‌فرض شد.
:::

::: {.sim name="crush"}
:::

## تلاش دوباره: collision و reject {#sec-08-6-3}

`crush_choose_firstn()` برای هر نسخه (rep) یک bucket را پایین می‌رود تا به نوع مورد نظر برسد. اگر آیتم انتخاب‌شده قبلاً انتخاب شده باشد (**collide**) یا OSD خارج یا بیش‌ازحد پر باشد (**reject**)، شمارنده‌ی `ftotal` افزایش می‌یابد و انتخاب با `r' = r + ftotal` تکرار می‌شود؛ تا سقف `choose_total_tries` (tunable، پیش‌فرض ۵۰ در پروفایل‌های جدید).

```text
pseudocode: crush_choose_firstn (خلاصه‌ی این کتاب)
  for rep in 0..numrep-1:
      ftotal = 0
      loop:
          r = rep + ftotal
          item = descend(bucket, x, r) until type matches     # straw2 در هر سطح
          collide = item in out[0..rep-1]
          reject  = is_out(item, x) or (chooseleaf and leaf selection failed)
          if not collide and not reject: out[rep] = item; break
          ftotal += 1
          if ftotal >= choose_total_tries: give up on this rep
```

تابع `is_out()` جالب است: OSDی با reweight بین ۰ و ۱ به‌صورت **احتمالاتی** رد می‌شود؛ `hash(x, item) & 0xffff` با وزن reweight (16.16) مقایسه می‌شود. پس `ceph osd reweight 12 0.8` یعنی حدود ۲۰٪ از PGهایی که CRUSH به osd.12 می‌داد، با تلاش دوباره به OSD دیگری می‌روند. reweight به همین دلیل با وزن CRUSH (که سهم را در straw2 تغییر می‌دهد) فرق دارد.

::: {.tip}
`crushtool --test` همین کد را خارج از کلاستر اجرا می‌کند. برای دیدن اثر یک تغییر پیش از اعمال: `ceph osd getcrushmap -o cm`، ویرایش، سپس `crushtool -i cm --test --show-statistics --rule 0 --num-rep 3 --min-x 0 --max-x 100000` و مقایسه‌ی `--show-mappings` قبل و بعد.
:::

## cephx: بلیت‌ها و کلیدهای چرخشی {#sec-08-6-4}

![جریان احراز هویت cephx: کلاینت با اثبات دانستن کلید مشترک از MON کلید جلسه و بلیت احراز می‌گیرد، سپس برای سرویس OSD بلیت سرویس رمزشده با کلید چرخشی آن سرویس دریافت می‌کند؛ OSD که کلیدهای چرخشی را از MON گرفته است، بلیت را رمزگشایی و انقضا و capها را بررسی می‌کند و پاسخ می‌دهد تا احراز دوطرفه کامل شود](figures/ch08/s03_cephx.png){#fig-08-s03_cephx}

ساختارهای اصلی در `src/auth/cephx/CephxProtocol.h` تعریف شده‌اند: `CephXServerChallenge`، `CephXAuthenticate`، `CephXTicketBlob`، `CephXServiceTicket`، `CephXServiceTicketInfo` و `CephXAuthorizer`. سه نوع درخواست اصلی با ثابت‌های `CEPHX_GET_AUTH_SESSION_KEY` (۰x0100)، `CEPHX_GET_PRINCIPAL_SESSION_KEY` (۰x0200) و `CEPHX_GET_ROTATING_KEY` (۰x0400) مشخص می‌شوند.

- کلید مشترک کلاینت هرگز روی شبکه منتقل نمی‌شود؛ کلاینت فقط ثابت می‌کند آن را دارد (پاسخ به challenge).
- بلیت سرویس با **کلید چرخشی** سرویس رمز می‌شود که MON دوره‌ای عوض می‌کند و OSDها می‌گیرند؛ بنابراین OSD برای بررسی بلیت نیازی به تماس با MON ندارد.
- عمر بلیت‌ها با `auth_mon_ticket_ttl` (پیش‌فرض ۷۲ ساعت) و `auth_service_ticket_ttl` (پیش‌فرض ۱ ساعت) کنترل می‌شود؛ کلاینت پیش از انقضا تمدید می‌کند.

::: {.warn}
چون بلیت‌ها زمان انقضا دارند، **اختلاف ساعت** بین کلاینت، MON و OSD می‌تواند احراز را بشکند. پیام‌هایی مانند «could not get service secret» یا خطای احراز پس از راه‌اندازی دوباره‌ی میزبانی با ساعت نادرست، اغلب از همین است. NTP/chrony روی همه‌ی میزبان‌ها و کلاینت‌ها الزامی است.
:::

## msgr2: قاب‌ها و حالت امن {#sec-08-6-5}

![ساختار قاب در پروتکل msgr2: preamble با اندازه‌ی ثابت شامل برچسب نوع قاب، تعداد segmentها تا چهار و طول و هم‌ترازی هر segment و CRC جداگانه؛ سپس حداکثر چهار segment شامل سرآیند، front، middle و data؛ و در پایان epilogue که در حالت crc شامل CRC هر segment و در حالت secure رمز و احراز صحت AES-GCM کل قاب است](figures/ch08/s04_msgr2.png){#fig-08-s04_msgr2}

در `src/msg/async/frames_v2.h`، هر قاب با یک `preamble_block_t` شروع می‌شود که برچسب (`enum class Tag`: HELLO، AUTH_REQUEST، AUTH_REQUEST_MORE، ...، SESSION_RECONNECT، MESSAGE، KEEPALIVE2، COMPRESSION_REQUEST و...)، تعداد segmentها (حداکثر `MAX_NUM_SEGMENTS = 4`) و طول و هم‌ترازی هر segment را دارد. جدا کردن segment داده با هم‌ترازی مشخص اجازه می‌دهد بافر داده بدون کپی (zero-copy) مستقیم به BlueStore برسد.

```bash
ceph config get mon ms_cluster_mode          # crc یا secure (و ترتیب ترجیح)
ceph config get mon ms_service_mode
ceph config get mon ms_client_mode
ceph config set global ms_cluster_mode "secure"   # رمزنگاری ترافیک بین OSDها
ceph mon dump | grep -E "v2:|v1:"                 # نشانی‌های دو پروتکل
```

::: {.note}
حالت `secure` هزینه‌ی CPU دارد، اما روی پردازنده‌های دارای AES-NI معمولاً قابل‌تحمل است. پیش از فعال‌سازی روی شبکه‌ی cluster پرترافیک، اثر را در آزمایشگاه بسنجید. پورت پیش‌فرض msgr2 روی MON ۳۳۰۰ و msgr1 ۶۷۸۹ است.
:::

# جابه‌جایی داده با عدد: افزودن میزبان و تغییر وزن {#sec-08-7}

این بخش دو پرسش عملی را با نگاشت واقعی CRUSH پاسخ می‌دهد: «با افزودن یک میزبان چه مقدار داده جابه‌جا می‌شود؟» و «با تغییر وزن یک OSD چه چیزی جابه‌جا می‌شود؟». نقشه با `crushtool --build --num_osds 132 … host straw2 12 root straw2 0` ساخته شد. نسخه‌ی ده‌میزبانی همان نقشه با `--remove-item` به دست آمد تا شناسه‌ی همه‌ی bucketها و OSDها ثابت بماند، چون straw2 شناسه‌ی آیتم را در hash به کار می‌برد. pool سه‌نسخه‌ای با 8192 PG در `osdmaptool --createsimple 256 --pg-bits 5 --pgp-bits 5` تعریف شد و نگاشت هر حالت با `--test-map-pgs-dump` گرفته شد. ابزارها از Ceph 18.2.7 بودند و tunableها پیش‌فرض: `chooseleaf_vary_r 1`، `chooseleaf_stable 1` و `choose_total_tries 50`.

::: {.note}
یک دام در osdmaptool: گزینه‌ی `--mark-up-in` به هر OSD با وزن CRUSH صفر وزن 1.0 می‌دهد (src/tools/osdmaptool.cc، بلوک `if (mark_up_in)` با `adjust_item_weightf(…, 1.0)`). پس برای شبیه‌سازی «میزبان هنوز اضافه نشده» نمی‌توان وزن OSDها را صفر کرد و باید آن‌ها را از نقشه حذف کرد. ما اول همین اشتباه را کردیم و هیچ جابه‌جایی‌ای ندیدیم.
:::

## افزودن یک میزبان {#sec-08-7-1}

::: {.algo #alg-08-1 title="شمارش جابه‌جایی با مقایسه‌ی دو نگاشت" src="osdmaptool --test-map-pgs-dump پیش و پس از تغییر؛ bucket_straw2_choose و crush_choose_firstn در src/crush/mapper.c" complexity="O(pg_num × size)"}
:::

```text
pseudocode
A = up(pg) با نقشه‌ی قدیم ؛ B = up(pg) با نقشه‌ی جدید          # برای هر pg در [0, pg_num)
moved = Σ_pg |set(B[pg]) − set(A[pg])|                         # جای‌گذاری‌های تازه، بی‌توجه به ترتیب
to_new = Σ_pg |{o ∈ B[pg] − A[pg] : o روی میزبان جدید}|
ideal = pg_num × size × (وزن میزبان جدید / وزن کل)               # 24576 × 12/132
```

**نتیجه.** از 24576 جای‌گذاری replica، 2184 مورد (8.89٪) به میزبان جدید رفت. حد ایده‌آل 2234 (9.09٪) است. این همان رفتاری است که straw2 تضمین می‌کند: هر آیتم یک «قرعه»ی مستقل `ln(u)/w` دارد (تابع `generate_exponential_distribution`) و افزودن یک آیتم فقط در جاهایی برنده را عوض می‌کند که قرعه‌ی آیتم تازه بالاتر باشد.

اما 328 جای‌گذاری دیگر (1.33٪) بین OSDهای قدیمی جابه‌جا شد. نمونه‌ای واقعی از همین نگاشت: PG ‏`1.58` از `[76, 113, 46]` به `[76, 125, 116]` رفت. میزبان جدید در جایگاه دوم نشست و میزبان 9 به جایگاه سوم رانده شد. در `crush_choose_firstn` برگ درون میزبان با `sub_r = r >> (vary_r − 1)` انتخاب می‌شود، یعنی به r جایگاه بستگی دارد. پس در همان میزبان 9 به‌جای osd.113، ‏osd.116 انتخاب شد. نتیجه‌ی عملی این است که افزودن ظرفیت حدود 15٪ بیشتر از حد ایده‌آل جابه‌جایی ایجاد می‌کند (2512 در برابر 2234). این را در برآورد زمان backfill لحاظ کنید.

![افزودن میزبان یازدهم (12 OSD) به کلاستر 10 × 12 با straw2، ‏pool سه‌نسخه‌ای و 8192 PG، اندازه‌گیری‌شده با osdmaptool. خاکستری سهم ایده‌آل است، سبز replicaهایی که به میزبان جدید رفتند و نارنجی جابه‌جایی بین OSDهای قدیمی که از عوض شدن r جایگاه در chooseleaf ناشی می‌شود](figures/ch08/f07_addhost.png){#fig-08-f07_addhost}

## تغییر وزن یک OSD {#sec-08-7-2}

::: {.algo #alg-08-2 title="دسته‌بندی جابه‌جایی‌ها پس از reweight" src="crushtool --reweight-item (وزن والدها را هم به‌روز می‌کند)؛ همان مقایسه‌ی A و B" complexity="O(pg_num × size)"}
:::

```text
pseudocode
برای هر جای‌گذاری تازه y ∈ B[pg] − A[pg]:
    اگر osd.5 در ورودی یا خروجی این PG باشد      → «خود osd.5»
    وگرنه اگر ورودی یا خروجی روی host0 باشد       → «دیگر OSDهای host0»   (وزن host0 در root عوض شده)
    وگرنه                                          → «میزبان‌های نامربوط»   (جابه‌جایی جایگاه/r)
```

**نتیجه.** وقتی وزن osd.5 از 1.0 به 2.0 می‌رسد، 411 جای‌گذاری عوض می‌شود: 214 مورد خود osd.5، ‏169 مورد دیگر OSDهای host0 و 28 مورد میزبان‌های نامربوط. وقتی وزن به 0.8 کم می‌شود، 84 جای‌گذاری عوض می‌شود: 42، 40 و 2.

بخش بزرگ «دیگر OSDهای host0» اشکال straw2 نیست. `crushtool --reweight-item` وزن host0 را در root هم از 12 به 13 می‌برد و host0 سهم بیشتری از PGها می‌گیرد. straw2 این سهم را درون host0 به نسبت 2/13 برای osd.5 و 1/13 برای هر OSD دیگر پخش می‌کند.

در این آزمایش الگوریتم قدیمی straw نتیجه‌ی تقریباً یکسانی داد (400 در برابر 411 برای وزن 2.0)، چون همه‌ی آیتم‌ها جز یکی هم‌وزن بودند. ایراد مستند straw قدیمی (جابه‌جایی بین آیتم‌های دیگرِ همان bucket هنگام تغییر وزن یکی) در bucketهای با وزن‌های نابرابر بروز می‌کند. با این حال، straw2 تنها الگوریتمی است که این ویژگی را برای هر توزیع وزنی تضمین می‌کند.

::: {.tip}
پیش از هر تغییر وزن یا افزودن میزبان روی کلاستر واقعی، همین مقایسه را آفلاین انجام دهید: `ceph osd getmap -o om`، سپس `osdmaptool om --export-crush cm`، تغییر روی cm با crushtool، `osdmaptool om --import-crush cm2` روی یک کپی، و مقایسه‌ی دو خروجی `--test-map-pgs-dump`. در این حالت `--mark-up-in` لازم نیست، چون osdmap واقعی وضعیت up و in را دارد.
:::

![تغییر وزن CRUSH یک OSD (osd.5 روی host0) از 1.0 به پنج مقدار و دسته‌بندی جای‌گذاری‌های جابه‌جاشده: آبی خود osd.5، زرد دیگر OSDهای host0 که با تغییر وزن میزبان سهم تازه می‌گیرند یا از دست می‌دهند، قرمز میزبان‌های نامربوط. چپ straw2 و راست straw قدیمی، با 8192 PG و اندازه‌گیری osdmaptool](figures/ch08/f08_reweight.png){#fig-08-f08_reweight}

# احراز هویت و مجوزها {#sec-08-8}

## cephx {#sec-08-8-1}

Ceph از پروتکل **cephx** برای احراز هویت دوطرفه بین کلاینت‌ها و daemonها استفاده می‌کند. ایده‌ی آن شبیه Kerberos است: کلید مخفی هرگز روی شبکه ارسال نمی‌شود و MON به‌عنوان مرجع، **ticket**های زمان‌دار صادر می‌کند که کلاینت با آن‌ها مستقیماً با OSDها و MDSها صحبت می‌کند.

![جریان cephx: کلاینت هویتش را به MON ثابت می‌کند، ticket می‌گیرد و با آن مستقیماً با OSD کار می‌کند](figures/ch08/f04_cephx.png){#fig-08-f04_cephx}

::: {.deep}
اگر هر درخواست I/O برای بررسی مجوز به MON می‌رفت، MONها گلوگاه می‌شدند. با ticket، OSD فقط با کلید سرویس خودش (که از MON گرفته و دوره‌ای چرخانده می‌شود) اعتبار ticket را بررسی می‌کند. به همین دلیل اختلاف ساعت بین گره‌ها می‌تواند به خطاهای احراز هویت منجر شود: ticketها زمان انقضا دارند.
:::

## کاربران و capabilityها {#sec-08-8-2}

هر هویت در Ceph به شکل `type.id` است (مثلاً `client.backup` یا `osd.3`) و یک کلید و مجموعه‌ای capability دارد. capabilityها برای هر نوع daemon جداگانه تعریف می‌شوند:

```bash
ceph auth ls
ceph auth get client.admin
# کاربر فقط برای RBD در یک pool
ceph auth get-or-create client.vmhost mon 'profile rbd' osd 'profile rbd pool=vms' mgr 'profile rbd pool=vms'
# کاربر فقط‌خواندنی برای پایش
ceph auth get-or-create client.monitor mon 'allow r' mgr 'allow r'
# کاربر محدود به یک namespace
ceph auth get-or-create client.tenant1 mon 'allow r' osd 'allow rw pool=shared namespace=tenant1'
ceph auth caps client.vmhost mon 'profile rbd' osd 'profile rbd pool=vms, profile rbd-read-only pool=images'
ceph auth rm client.old-app
```

::: {.tip}
همیشه از **profile**ها (`profile rbd`، `profile rbd-read-only`، `profile crash`، `profile bootstrap-osd`) به جای نوشتن دستی capabilityهای سطح پایین استفاده کنید. profileها capabilityهای لازم برای عملیاتی مثل blocklist کردن کلاینت قبلی (برای قفل exclusive-lock در RBD) را هم دارند که در capabilityهای دستی معمولاً فراموش می‌شوند.
:::

## چرخش کلید و رمزنگاری {#sec-08-8-3}

- کلید یک کاربر را می‌توان با `ceph auth rotate` (در نسخه‌های جدید) یا ساختن کلید تازه و جایگزینی تدریجی چرخاند.
- Umbrella cephx را سخت‌تر کرد: رمز تازه‌ی **AES256KRB5** به جای انواع کلید قدیمی‌تر پیش‌فرض شد و چرخش آنلاین کلیدها اضافه شد. پیش از ارتقا، سازگاری کلاینت‌های قدیمی (به‌ویژه کلاینت‌های هسته) را بررسی کنید.
- برای رمزنگاری ترافیک شبکه، حالت `secure` در **msgr2** را فعال کنید (`ms_cluster_mode`، `ms_service_mode`، `ms_client_mode`). این حالت سربار CPU دارد؛ آن را روی سخت‌افزار واقعی اندازه بگیرید.

```bash
ceph config set global ms_client_mode secure
ceph config set global ms_service_mode secure
ceph config get mon ms_cluster_mode
```

# مسیر I/O و PGها {#sec-08-9}

## مسیر یک نوشتن {#sec-08-9-1}

![نوشتن در pool تکثیری: کلاینت فقط با primary صحبت می‌کند؛ primary به‌طور موازی به ثانویه‌ها تکثیر می‌کند و پس از commit همه‌ی نسخه‌ها ack می‌دهد](figures/ch08/f05_write.png){#fig-08-f05_write}

1. کلاینت (librados) با نقشه‌ای که دارد، PG و primary را محاسبه می‌کند.
2. درخواست را فقط به **primary** می‌فرستد.
3. primary عملیات را در log آن PG ثبت و به‌طور موازی به ثانویه‌ها می‌فرستد.
4. هر OSD تراکنش را در BlueStore commit می‌کند.
5. primary پس از دریافت تأیید از **همه‌ی** OSDهای acting set به کلاینت ack می‌دهد.

بنابراین تأخیر نوشتن برابر کندترین OSD در acting set به‌علاوه‌ی دو رفت‌وبرگشت شبکه است. همین دلیل است که یک دیسک کند کل کلاستر را کند می‌کند (فصل ۱۷). در pool EC، primary داده را به k قطعه‌ی داده و m قطعه‌ی parity تقسیم و هر قطعه را به یک OSD می‌فرستد (فصل ۱۳).

::: {.note}
خواندن به‌طور پیش‌فرض از primary انجام می‌شود. کلاینت‌های RBD و RGW می‌توانند در شرایط خاص از نزدیک‌ترین نسخه بخوانند (مثلاً گزینه‌ی `rbd_read_from_replica_policy` با مقادیر balance و localize)، که در کلاسترهای گسترده بین سایت‌ها مفید است.
:::

## حالت‌های PG {#sec-08-9-2}

![حالت‌های اصلی PG و گذارهای رایج بین آن‌ها](figures/ch08/f06_pgstates.png){#fig-08-f06_pgstates}

| حالت | معنی | نگران‌کننده؟ |
|---|---|---|
| active+clean | همه‌ی نسخه‌ها موجود و همگام | خیر؛ حالت مطلوب |
| peering | OSDها در حال توافق بر وضعیت PG | فقط اگر طول بکشد |
| degraded | برخی اشیا نسخه‌ی کافی ندارند | تا بازیابی کامل، ریسک بالاتر |
| recovering | همگام‌سازی از روی log | طبیعی پس از خرابی کوتاه |
| backfilling, backfill_wait | کپی کامل PG به OSD جدید | طبیعی پس از تغییر نقشه |
| remapped | acting set موقتاً با up set فرق دارد | طبیعی در حین backfill |
| undersized | تعداد OSDها کمتر از size | بررسی شود |
| inconsistent | scrub ناسازگاری پیدا کرده | بله؛ باید بررسی و repair شود |
| incomplete, down | نسخه‌ی معتبر کافی برای فعال شدن نیست | بله؛ I/O این PG متوقف است |
| stale | primary مدتی آمار نفرستاده | بله؛ OSDها را بررسی کنید |

```bash
ceph pg stat
ceph pg dump_stuck inactive
ceph pg dump_stuck unclean
ceph pg ls degraded
ceph pg 3.1f query | jq '.recovery_state'
```

::: {.debug}
برای PGی که در peering یا incomplete گیر کرده، خروجی `ceph pg <id> query` را از پایین به بالا بخوانید. بخش `recovery_state` معمولاً می‌گوید منتظر کدام OSD است (`blocked_by` یا `down_osds_we_would_probe`). اگر آن OSD برای همیشه از دست رفته است، تصمیم‌هایی مثل `ceph osd lost` یا علامت‌گذاری اشیای گم‌شده ریسک از دست رفتن داده دارند؛ قبل از اجرا فصل ۱۷ را بخوانید.
:::

## min_size و size {#sec-08-9-3}

`size` تعداد نسخه‌هاست و `min_size` حداقل نسخه‌ی سالمی که PG برای پذیرش I/O لازم دارد. برای pool تکثیری سه‌تایی، `min_size=2` استاندارد است. کاهش آن به ۱ کلاستر را در حین خرابی «در دسترس» نگه می‌دارد اما ریسک از دست رفتن داده را به‌شدت بالا می‌برد، چون یک نوشتن ممکن است فقط روی یک دیسک وجود داشته باشد.

# pool روی OSDهای مشخص {#sec-08-10}

راه امروزی قرار دادن یک pool روی گروه خاصی از OSDها، **کلاس دستگاه** است. اگر کلاس‌های پیش‌فرض کافی نیستند (مثلاً می‌خواهید دیسک‌های NVMe یک مدل خاص را برای یک مستأجر کنار بگذارید)، کلاس دلخواه تعریف کنید:

```bash
for id in 30 31 32 33 34 35; do
  ceph osd crush rm-device-class osd.$id
  ceph osd crush set-device-class fastnvme osd.$id
done
ceph osd crush rule create-replicated fast-host default host fastnvme
ceph osd pool create tenant-a-db 64 64 replicated fast-host
ceph osd pool application enable tenant-a-db rbd
ceph pg ls-by-pool tenant-a-db | head
```

::: {.tip}
در spec OSD در cephadm هم می‌توانید `crush_device_class` را تعیین کنید تا OSDهای تازه از ابتدا کلاس درست را بگیرند و نیازی به اجرای دوباره‌ی دستورهای بالا نباشد.
:::

::: {.summary title="نکات SRE این فصل"}

- محل داده محاسبه می‌شود، نه جست‌وجو؛ `ceph osd map` ابزار اول شماست.
- فقط دامنه‌های خرابی واقعی را در CRUSH تعریف کنید و مکان میزبان را در spec بدهید.
- قبل از اعمال هر نقشه‌ی دستی، `crushtool --test` اجرا کنید.
- برای SSD/HDD از کلاس دستگاه استفاده کنید، نه rootهای جدا.
- تغییر tunable یعنی جابه‌جایی بزرگ؛ سازگاری کلاینت‌ها را با `ceph features` بررسی کنید.
- MON فرد (۳ یا ۵)، روی SSD، با ساعت دقیق.
- capability با profile و حداقل دسترسی؛ min_size را پایین نیاورید.

:::

# تکمیلی و به‌روز {#sec-08-11}

- **کلاس دستگاه و shadow tree** (Luminous) جایگزین rootهای جداگانه‌ی SSD/HDD شد که در منابع قدیمی دیده می‌شود.
- **upmap و balancer**: جای reweight دستی را گرفته‌اند (فصل ۷).
- **قانون MSR** (Squid) برای EC انعطاف بیشتری می‌دهد.
- **cephx در Umbrella**: رمز AES256KRB5 به‌عنوان پیش‌فرض و چرخش آنلاین کلید.
- **پشتیبان RocksDB MON** (Umbrella).
- **read balancer** (Reef) برای توزیع primaryها.

# تمرین عملی {#sec-08-12}

1. برای سه شیء مختلف `ceph osd map` بگیرید و مسیر PG و OSDها را با `ceph pg map` مقایسه کنید.
2. یک سلسله‌مراتب دو rackی بسازید، میزبان‌ها را جابه‌جا کنید و قانون `rep-rack` را روی یک pool آزمایشی اعمال کنید. حجم جابه‌جایی را مشاهده کنید.
3. نقشه‌ی CRUSH را استخراج کنید، قانون دو datacenterی را اضافه کنید و پیش از اعمال، با `crushtool --test` توزیع را بررسی کنید.
4. کاربری با `profile rbd` فقط برای یک pool بسازید و ثابت کنید به pool دیگر دسترسی ندارد.
5. یک OSD را متوقف کنید و حالت‌های PG را در طول زمان با `ceph pg stat` ثبت کنید.
6. با کلاس دستگاه دلخواه یک pool روی سه OSD خاص بسازید و توزیع PGها را بررسی کنید.

# پرسش‌های مرور {#sec-08-13}

1. دو مرحله‌ی نگاشت شیء به OSD کدام‌اند و چرا PG لازم است؟
2. تفاوت up set و acting set چیست؟
3. مزیت straw2 نسبت به الگوریتم‌های قبلی چیست؟
4. چرا تغییر tunableها باعث جابه‌جایی داده می‌شود و پیش از آن چه چیزی را باید بررسی کرد؟
5. چرا چهار MON از سه MON تحمل خرابی بیشتری ندارد؟
6. OSDها نقشه‌ی جدید را از کجا دریافت می‌کنند؟
7. چرا cephx از ticket استفاده می‌کند؟
8. چرا تأخیر نوشتن به کندترین OSD acting set بستگی دارد؟
9. حالت‌های incomplete و inconsistent چه تفاوتی دارند؟
10. راه توصیه‌شده برای قرار دادن یک pool روی OSDهای خاص چیست؟

# منابع این فصل {#sec-08-14}

- CRUSH maps: https://docs.ceph.com/en/latest/rados/operations/crush-map/
- CRUSH map edits: https://docs.ceph.com/en/latest/rados/operations/crush-map-edits/
- Placement groups: https://docs.ceph.com/en/latest/rados/operations/placement-groups/
- PG states: https://docs.ceph.com/en/latest/rados/operations/pg-states/
- Monitoring OSDs and PGs: https://docs.ceph.com/en/latest/rados/operations/monitoring-osd-pg/
- User management: https://docs.ceph.com/en/latest/rados/operations/user-management/
- Cephx config: https://docs.ceph.com/en/latest/rados/configuration/auth-config-ref/
- Messenger v2: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- Architecture: https://docs.ceph.com/en/latest/architecture/
- Health checks: https://docs.ceph.com/en/latest/rados/operations/health-checks/
- Read balancer: https://docs.ceph.com/en/latest/rados/operations/read-balancer/
- Squid release notes: https://docs.ceph.com/en/latest/releases/squid/
- Umbrella release notes: https://docs.ceph.com/en/latest/releases/umbrella/
- Weil et al., CRUSH (SC 2006): https://ceph.io/assets/pdfs/weil-crush-sc06.pdf
