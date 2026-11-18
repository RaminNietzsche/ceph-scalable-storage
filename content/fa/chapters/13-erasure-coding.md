---
chapter: 13
id: ch13
title: "کدگذاری پاک‌شونده (Erasure Coding) برای بهره‌وری ذخیره‌سازی"
part: main
lang: fa
---

::: {.tldr}

- erasure coding داده را به k تکه‌ی داده و m تکه‌ی parity می‌شکند؛ هر k تکه برای بازسازی کافی است، پس m خرابی با فضای خام بسیار کمتر از replication تحمل می‌شود.
- در pool از نوع EC هر OSD در acting set یک shard را نگه می‌دارد؛ RBD و CephFS روی EC به `allow_ec_overwrites` نیاز دارند و RBD متادیتا را در pool از نوع replicated نگه می‌دارد.
- در Tentacle افزونه‌ی پیش‌فرض کلاسترهای تازه ISA-L شد و FastEC (خواندن و نوشتن جزئی و parity-delta) پشت `allow_ec_optimizations` آمد.
- عدد `2147483647` در نگاشت PG همان `CRUSH_ITEM_NONE` است: CRUSH برای آن shard هیچ OSDی پیدا نکرده است.

:::

# پیش از شروع {#sec-13-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-13-1-1}

تکثیر سه‌تایی ساده و سریع است، اما برای هر ترابایت داده‌ی کاربر سه ترابایت دیسک مصرف می‌کند. **کدگذاری پاک‌شونده** (Erasure Coding یا EC) با همان یا حتی بیشتر از سطح تحمل خرابی، سربار را به حدود ۱.۵ برابر یا کمتر می‌رساند. بهای آن پیچیدگی بیشتر، مصرف CPU و تأخیر بالاتر در نوشتن‌های کوچک است. از ۲۰۱۹ تا امروز EC در Ceph دو تحول بزرگ داشته: پیش‌فرض شدن ISA-L به جای Jerasure و معرفی **FastEC** در Tentacle.

- EC چیست و پارامترهای k و m چه معنایی دارند؟
- EC درون Ceph چطور پیاده شده است: stripe، shard و chunk؟
- افزونه‌ها (ISA، Jerasure، LRC، SHEC، CLAY) چه تفاوتی دارند؟
- کجا از EC استفاده کنیم و کجا نه؟
- pool EC را چطور بسازیم و overwrite و FastEC را فعال کنیم؟
- خطای معروف «2147483647» از کجا می‌آید؟

# EC چیست؟ {#sec-13-2}

## k+m {#sec-13-2-1}

در EC، داده به **k قطعه‌ی داده** تقسیم می‌شود و از آن‌ها **m قطعه‌ی parity** محاسبه می‌شود. هر k قطعه از k+m قطعه برای بازسازی کامل داده کافی است؛ بنابراین تا m خرابی هم‌زمان قابل تحمل است.

![کدگذاری 4+2: یک stripe شانزده‌کیلوبایتی به چهار shard داده‌ی چهارکیلوبایتی تقسیم و دو shard parity از آن‌ها محاسبه می‌شود؛ هر shard روی یک OSD در دامنه‌ی خرابی جدا قرار می‌گیرد](figures/ch13/f01_km.png){#fig-13-f01_km}

| طرح | سربار ذخیره‌سازی | تحمل خرابی | حداقل دامنه‌ی خرابی (host) |
|---|---|---|---|
| تکثیر ۳ | ۳.۰× | ۲ | ۳ |
| EC 2+1 | ۱.۵× | ۱ | ۳ |
| EC 4+2 | ۱.۵× | ۲ | ۶ |
| EC 8+3 | ۱.۳۷۵× | ۳ | ۱۱ |
| EC 8+4 | ۱.۵× | ۴ | ۱۲ |

::: {.warn}
«حداقل دامنه‌ی خرابی» شوخی نیست: با EC 8+3 و دامنه‌ی خرابی host به یازده میزبان نیاز دارید و برای اینکه پس از خرابی یک میزبان بتوان shardها را بازسازی کرد، دوازده میزبان یا بیشتر. EC روی کلاستر کوچک یا فشار به جای دامنه‌ی خرابی (مثلاً `crush-failure-domain=osd`) دوام واقعی را از بین می‌برد.
:::

::: {.sim name="ecprofile"}
:::

در آزمایشگاه زیر pool را erasure-coded کنید و k و m را برگزینید تا ببینید CRUSH با `indep` هر shard را روی کدام OSD می‌گذارد، یک OSD از کار افتاده چه جای خالی‌ای باقی می‌گذارد و PG با از دست رفتن چند shard همچنان active می‌ماند.

::: {.sim name="placement" mode="ec"}
:::

## ریاضیات به زبان ساده {#sec-13-2-2}

کدهای Reed-Solomon (که ISA-L و Jerasure پیاده می‌کنند) روی **میدان گالوا** (معمولاً $\mathrm{GF}(2^8)$) کار می‌کنند: هر بایت یک عنصر میدان است و جمع، XOR است. k بایت داده را بردار d در نظر بگیرید؛ shardها حاصل ضرب ماتریس مولد G با ابعاد (k+m)×k در d هستند. k سطر اول G ماتریس همانی است (پس shardهای داده همان داده‌اند) و m سطر بعدی ضرایب parity. برای بازسازی، از هر k shard در دسترس، زیرماتریس k×k متناظر را می‌گیریم و معکوس می‌کنیم. شرط کار این است که **هر** زیرماتریس k×k وارون‌پذیر باشد؛ ماتریس‌های Vandermonde (`reed_sol_van`) و Cauchy (`cauchy`) این ویژگی را دارند.

```text
shard_i = Σ_j  G[i][j] ⊗ d_j      (⊗ ضرب در GF(2^8)، Σ همان XOR)
برای i < k:  G[i] = e_i  →  shard_i = d_i
decode:  d = (G_S)^-1 · shards_S     (S: هر k اندیس در دسترس)
```

# EC درون Ceph {#sec-13-3}

## stripe، shard و chunk {#sec-13-3-1}

![چیدمان stripeها: داده‌ی شیء به stripeهایی به طول k×stripe_unit تقسیم می‌شود؛ قطعه‌ی i هر stripe روی shard i قرار می‌گیرد و parity هر stripe جداگانه محاسبه می‌شود](figures/ch13/f02_stripe.png){#fig-13-f02_stripe}

در pool EC، هر PG به جای «نسخه» **shard** دارد: OSD شماره‌ی i در acting set، shard i است و فقط قطعه‌ی خودش را نگه می‌دارد. شیء به stripeهایی به اندازه‌ی `k × stripe_unit` تقسیم می‌شود (پیش‌فرض stripe_unit چهار کیلوبایت). برای هر stripe، k قطعه‌ی داده و m قطعه‌ی parity ساخته و قطعه‌ی i روی shard i ذخیره می‌شود. پس روی هر OSD، شیء به شکل یک «شیء shard» شامل همه‌ی قطعه‌های i آن شیء دیده می‌شود.

## primary در EC {#sec-13-3-2}

primary در pool EC مسئول encode و decode است: کلاینت فقط با primary صحبت می‌کند، primary داده را encode و قطعه‌ها را به shardها می‌فرستد. در خواندن، primary قطعه‌های لازم را از shardها جمع و در صورت نیاز decode می‌کند. این یعنی بار CPU و شبکه‌ی EC روی primaryها متمرکز است.

![خواندن تخریب‌شده (degraded read): وقتی shard 1 در دسترس نیست، minimum_to_decode مجموعه‌ای از k shard در دسترس را انتخاب و decode داده‌ی گم‌شده را بازسازی می‌کند](figures/ch13/f04_decode.png){#fig-13-f04_decode}

## نوشتن جزئی و overwrite {#sec-13-3-3}

EC در ابتدا (پیش از Luminous) فقط append را پشتیبانی می‌کرد و برای RBD و CephFS قابل استفاده نبود. پرچم `allow_ec_overwrites` (از Luminous، که سرفصل قدیمی آن را با Kraken مرتبط کرده) بازنویسی را ممکن کرد. اما در پیاده‌سازی قدیمی، بازنویسی ۴ کیلوبایت در وسط یک stripe یعنی **read-modify-write کامل**: خواندن بقیه‌ی stripe، encode دوباره و نوشتن همه‌ی shardها.

![مقایسه‌ی نوشتن کوچک در EC قدیمی و FastEC: پیاده‌سازی قدیمی کل stripe را می‌خواند و دوباره می‌نویسد؛ FastEC فقط shard تغییرکرده و parityها را به‌روز می‌کند](figures/ch13/f03_rmw.png){#fig-13-f03_rmw}

# افزونه‌ها و پروفایل‌ها {#sec-13-4}

![افزونه‌های EC در Ceph: همه رابط مشترک ErasureCodeInterface را پیاده می‌کنند و به‌صورت کتابخانه‌ی پویا بارگذاری می‌شوند](figures/ch13/f05_plugins.png){#fig-13-f05_plugins}

| افزونه | ایده | کاربرد |
|---|---|---|
| isa | Reed-Solomon با کتابخانه‌ی Intel ISA-L (ماتریس Vandermonde یا Cauchy)؛ پیش‌فرض کلاسترهای تازه از Tentacle | انتخاب پیش‌فرض؛ پشتیبانی از FastEC |
| jerasure | Reed-Solomon و کدهای دیگر با کتابخانه‌ی Jerasure؛ کتابخانه دیگر نگهداری نمی‌شود | کلاسترهای قدیمی؛ FastEC فقط با reed_sol_van |
| lrc | Locally Repairable Code: گروه‌های محلی با parity محلی | بازیابی با خواندن کمتر؛ کلاسترهای چندرکی |
| shec | Shingled EC: parityهای همپوشان | کاهش هزینه‌ی بازیابی با هزینه‌ی کمی دوام |
| clay | Coupled-layer: تقسیم chunk به sub-chunk | کاهش شدید ترافیک شبکه در بازیابی یک shard |

::: {.note}
طبق یادداشت انتشار Tentacle، افزونه‌ی پیش‌فرض از Jerasure به **ISA-L** تغییر کرد. کلاسترهایی که روی Tentacle یا بعد ساخته شوند از ISA-L استفاده می‌کنند؛ کلاسترهای ارتقایافته پیش‌فرض قبلی را نگه می‌دارند. در کد جاری، `osd_pool_default_erasure_code_profile` برابر `plugin=isa technique=reed_sol_van k=2 m=2` است.
:::

## ساخت پروفایل و pool {#sec-13-4-1}

```bash
ceph osd erasure-code-profile ls
ceph osd erasure-code-profile get default
ceph osd erasure-code-profile set ec42 plugin=isa technique=reed_sol_van k=4 m=2 \
     crush-failure-domain=host crush-device-class=hdd
ceph osd pool create ecpool erasure ec42
ceph osd pool set ecpool allow_ec_overwrites true     # برای RBD و CephFS
ceph osd pool application enable ecpool rgw
```

::: {.warn}
پروفایل یک pool **پس از ساخت قابل تغییر نیست**: k، m، افزونه و stripe_unit ثابت می‌مانند. برای تغییر باید pool تازه ساخت و داده را منتقل کرد. پیش از ساخت، رشد آینده‌ی کلاستر و تعداد دامنه‌های خرابی را در نظر بگیرید.
:::

## LRC و CLAY {#sec-13-4-2}

```bash
# LRC: k=4 داده، m=2 parity سراسری، l=3 → هر ۳ قطعه یک parity محلی
ceph osd erasure-code-profile set lrc42 plugin=lrc k=4 m=2 l=3 crush-failure-domain=host
# CLAY: d تعداد shardهایی که در بازیابی یک shard مشارکت می‌کنند
ceph osd erasure-code-profile set clay42 plugin=clay k=4 m=2 d=5 crush-failure-domain=host
```

::: {.deep}
در Reed-Solomon معمولی، بازسازی **یک** shard گم‌شده نیازمند خواندن k shard کامل است: برای 8+3 یعنی هشت برابر حجم داده‌ی گم‌شده روی شبکه. LRC با parity محلی این را به اندازه‌ی گروه محلی کاهش می‌دهد (با هزینه‌ی فضای بیشتر). CLAY هر chunk را به sub-chunkها تقسیم می‌کند و در بازیابی فقط بخشی از sub-chunkهای هر یک از d کمک‌کننده را می‌خواند؛ با همان سربار فضای RS، ترافیک بازیابی کمتری دارد اما خواندن‌ها پراکنده‌ترند.
:::

# کجا EC و کجا تکثیر؟ {#sec-13-5}

| بار | توصیه |
|---|---|
| اشیای RGW بزرگ (آرشیو، پشتیبان، رسانه) | EC؛ بهترین نسبت هزینه |
| pool شاخص bucket و فراداده‌ی RGW | تکثیری؛ omap در EC پشتیبانی نمی‌شود |
| RBD برای پایگاه داده‌ی حساس به تأخیر | تکثیری |
| RBD برای VMهای عمومی یا پشتیبان | EC با FastEC و stripe_unit=16K (Tentacle+) |
| CephFS داده‌ی آرشیو | pool داده‌ی دوم EC با layout |
| فراداده‌ی CephFS و pool داده‌ی پیش‌فرض | تکثیری |

::: {.tip}
RBD روی EC همیشه دو pool دارد: فراداده‌ی image (header، omap) در pool تکثیری و داده در pool EC با گزینه‌ی `--data-pool`:
:::

```bash
rbd create rbd/vm01 --size 200G --data-pool ecpool
rbd info rbd/vm01 | grep data_pool
```

# FastEC در Tentacle {#sec-13-6}

## چه چیزی تغییر کرد؟ {#sec-13-6-1}

Tentacle پیاده‌سازی تازه‌ای از مسیر I/O در EC اضافه کرد که مجموعاً **FastEC** نامیده می‌شود: خواندن جزئی (فقط shardهای لازم)، نوشتن جزئی، نوشتن **parity delta**، حذف padding صفرها و صرفه‌جویی در فضای اشیای کوچک. با پرچم هر pool فعال می‌شود:

```bash {since=tentacle}
ceph osd pool set ecpool allow_ec_optimizations true
ceph osd pool get ecpool allow_ec_optimizations
# پیش‌فرض برای poolهای تازه
ceph config set global osd_pool_default_flag_ec_optimizations true
```

محدودیت‌ها طبق مستندات:

- همه‌ی MONها و OSDها باید Tentacle یا جدیدتر باشند؛ کلاینت‌ها نیازی به ارتقا ندارند.
- پرچم پس از فعال شدن **خاموش‌شدنی نیست**، چون شیوه‌ی ذخیره‌ی داده‌ی جدید را تغییر می‌دهد.
- فقط با ISA-L یا Jerasure با `reed_sol_van` کار می‌کند؛ CLAY، LRC و SHEC رد می‌شوند.
- stripe_unit باید مضرب ۴ کیلوبایت باشد؛ مستندات برای بیشتر بارها **۱۶ کیلوبایت** را توصیه می‌کند و برای بارهای عمدتاً خواندنی تا ۲۵۶ کیلوبایت.

```bash {since=tentacle}
ceph osd erasure-code-profile set ec42fast plugin=isa technique=reed_sol_van k=4 m=2 \
     stripe_unit=16K crush-failure-domain=host
ceph osd pool create rbd-ec erasure ec42fast
ceph osd pool set rbd-ec allow_ec_overwrites true
ceph osd pool set rbd-ec allow_ec_optimizations true
```

# عیب‌یابی: خطای 2147483647 {#sec-13-7}

در خروجی `ceph pg dump` یا `ceph pg map` برای pool EC گاهی به جای شماره‌ی OSD عدد **2147483647** می‌بینید. این عدد همان ثابت `CRUSH_ITEM_NONE` است:

```c
/* from ceph/ceph, LGPL — src/crush/crush.h */
#define CRUSH_ITEM_NONE   0x7fffffff
```

معنی‌اش این است که CRUSH نتوانسته برای آن جایگاه shard یک OSD پیدا کند. در pool تکثیری، جایگاه خالی ساده حذف می‌شود؛ اما در EC جایگاه هر shard معنی دارد (shard 3 باید shard 3 بماند)، پس به جای حذف، با NONE پر می‌شود. علت‌های رایج:

- تعداد دامنه‌های خرابی کمتر از k+m (مثلاً 4+2 با پنج میزبان).
- OSDهای out یا down که دامنه‌ای را خالی کرده‌اند.
- قانون CRUSH که کلاس دستگاه یا root اشتباهی دارد.
- تعداد تلاش‌های CRUSH کم است و در سلسله‌مراتب نامتوازن نتیجه نمی‌گیرد (`set_choose_tries`).

```bash
ceph pg ls-by-pool ecpool | grep -c 2147483647
ceph osd crush rule dump ecpool
ceph osd getcrushmap -o cm && crushtool -i cm --test --rule <id> --num-rep 6 --show-bad-mappings
```

::: {.debug}
اگر `--show-bad-mappings` خروجی داد ولی تعداد میزبان‌ها کافی است، در قانون EC گام `set_choose_tries 100` را بررسی کنید (قانون‌هایی که با `create-erasure` ساخته می‌شوند معمولاً آن را دارند). اگر میزبان کافی ندارید، راه درست افزودن میزبان یا انتخاب k+m کوچک‌تر است، نه پایین آوردن دامنه‌ی خرابی به osd.
:::

# درون backend مربوط به EC: نوشتن، rollback و recovery {#sec-13-8}

این بخش پلی است به فصل ۲۷ («ریاضیات erasure coding»). در اینجا به‌جای ریاضیات، مکانیک OSD را بررسی می‌کنیم: یک نوشتن EC چگونه میان shardها هماهنگ می‌شود، اگر وسط کار خرابی رخ دهد چه می‌شود، و recovery دقیقاً چه چیزی را می‌خواند و می‌نویسد. کلاس‌های مرتبط در `src/osd/` شاخه‌ی main عبارت‌اند از `ECBackend`، `ECCommon`، `ECTransaction`، `ECUtil` و نسخه‌های «L» (legacy) آن‌ها، که `ECSwitch` بر اساس پرچم pool میانشان انتخاب می‌کند.

![یک نوشتن در pool از نوع EC. primary (که همیشه shard صفر نیست، ولی در این شکل shard 0 فرض شده) تراکنش را به stripeها می‌شکند و تصمیم می‌گیرد آیا RMW لازم است. در صورت نیاز، chunkهای قدیمی را می‌خواند، parity را محاسبه و برای هر shard یک ECSubWrite شامل chunk آن shard و ورودی pg log می‌فرستد. هر ورودی log یک ObjectModDesc دارد که توضیح می‌دهد این تغییر چگونه قابل بازگشت است. کلاینت فقط پس از commit همه‌ی shardهای acting پاسخ می‌گیرد](figures/ch13/f07_ecwrite.png){#fig-13-f07_ecwrite}

## چرا EC به rollback نیاز دارد؟ {#sec-13-8-1}

در replication، هر replica یک کپی کامل است. اگر نوشتنی فقط روی برخی replicaها commit شود، recovery می‌تواند همان نسخه‌ی جدید را از یک replica به بقیه کپی کند. در EC هیچ shardی کل داده را ندارد. اگر نوشتن روی ۳ shard از ۶ shard commit شده باشد و سپس primary بمیرد، نه نسخه‌ی قدیم و نه نسخه‌ی جدید از هیچ k shard سازگاری قابل بازسازی نیست. راه حل Ceph این است که تغییرات «برگشت‌پذیر» باشند: هر ورودی pg log در EC یک `ObjectModDesc` دارد و پس از peering، shardهایی که از نقطه‌ی توافق‌شده جلوترند، تغییرات را **به عقب برمی‌گردانند**.

| op در `ObjectModDesc::ModID` | مقدار | چگونه برمی‌گردد |
|---|---|---|
| APPEND | 1 | بریدن (truncate) به اندازه‌ی قبلی |
| SETATTRS | 2 | بازگرداندن xattrهای قبلی ذخیره‌شده |
| DELETE | 3 | شیء به‌جای حذف، به نسخه‌ی موقت stash منتقل شده و برگردانده می‌شود |
| CREATE | 4 | حذف شیء تازه |
| UPDATE_SNAPS | 5 | بازگرداندن snapset قبلی |
| TRY_DELETE | 6 | حذف اختیاری |
| ROLLBACK_EXTENTS | 7 | برای overwrite: extentهای قبلی در شیء موقت نگه داشته می‌شوند |
| EC_OMAP | 8 | برای omap در EC (در main) |

`pg_log_t` دو مرز دارد: `can_rollback_to` (ورودی‌های جدیدتر از آن قابل بازگشت‌اند) و `rollback_info_trimmed_to` (اطلاعات stash تا آنجا پاک شده است). وقتی primary مطمئن شود یک ورودی روی همه‌ی shardها commit شده، `can_rollback_to` جلو می‌رود و داده‌ی stash (مثلاً extentهای قدیمی ROLLBACK_EXTENTS) می‌تواند پاک شود. این همان دلیلی است که overwrite در EC قدیمی نسبت به replication فضای موقت و نوشتن اضافه دارد.

::: {.deep}
**هزینه‌ی پنهان ROLLBACK_EXTENTS:** برای هر overwrite جزئی، داده‌ی قدیمی همان بازه باید پیش از بازنویسی در یک شیء موقت (generation) کپی شود تا اگر rollback لازم شد، برگردانده شود. در BlueStore این کپی با `clone_range` و blob مشترک انجام می‌شود (فصل ۲۴، shared blob)، پس داده‌ی واقعی دوباره نوشته نمی‌شود، ولی فراداده‌ی اضافه (کلیدهای `X` و extent map) ایجاد می‌شود. EC بهینه در Tentacle بخشی از این کار را با انتخاب دقیق‌تر بازه‌ها کاهش می‌دهد.
:::

## min_size پیش‌فرض و دلیل آن {#sec-13-8-2}

در `OSDMonitor::prepare_pool_size`، برای poolهای EC مقدار پیش‌فرض `min_size = k + min(1, m − 1)` است (و `size = num_zones × (k + m)`). یعنی برای k=4، m=2 مقدار min_size برابر ۵ است: pool تا وقتی دست‌کم ۵ shard در دسترس باشد، نوشتن را می‌پذیرد. بنابراین پس از از دست رفتن یک shard، هنوز یک shard اضافه برای تحمل خرابی بعدی وجود دارد. برای m=1، min_size = k است و هر خرابی دوم در حین recovery یعنی از دست رفتن داده. به همین دلیل m=1 برای داده‌ی مهم توصیه نمی‌شود.

![خواندن و recovery در EC. در خواندن، OSD با minimum_to_decode کمترین مجموعه‌ی shardهای لازم را تعیین می‌کند. با fast_read=false فقط همان‌ها خوانده می‌شوند. با fast_read=true همه‌ی shardها خوانده می‌شوند و با رسیدن اولین k پاسخ decode انجام می‌شود (تأخیر دم کمتر، ترافیک بیشتر). در recovery، primary از pg log فهرست اشیای گم‌شده‌ی هر shard را می‌سازد، از k shard سالم (یا کمتر در LRC و CLAY) می‌خواند، فقط chunk گم‌شده را decode و به OSD جدید push می‌کند. پایین شکل فرمول min_size پیش‌فرض را نشان می‌دهد](figures/ch13/f08_ecrecover.png){#fig-13-f08_ecrecover}

| گزینه‌ی pool | اثر |
|---|---|
| `fast_read` | خواندن موازی همه‌ی shardها؛ کاهش tail latency در ازای ترافیک بیشتر |
| `allow_ec_overwrites` | لازم برای RBD و CephFS روی EC؛ فعال‌سازی RMW و ROLLBACK_EXTENTS |
| `allow_ec_optimizations` (Tentacle به بعد) | backend بهینه؛ برگشت‌ناپذیر (فصل ۲۷) |
| `min_size` | حداقل shardهای در دسترس برای پذیرش I/O |

```bash
ceph osd pool set ecpool fast_read 1
ceph pg 5.1a query | jq '.peer_info[] | {peer, last_update, last_complete, log_tail}'   # بقیه‌ی shardها؛ peer "12(2)" یعنی shard 2 روی osd.12
ceph pg 5.1a list_unfound
ceph daemon osd.4 dump_ops_in_flight | jq '.ops[] | select(.description|test("ECSub"))'
```

::: {.note}
نام PG در EC پسوند shard دارد: `5.1as2` یعنی shard 2 از PG 5.1a. این پسوند در لاگ‌های OSD و در نام collectionها روی OSD (`5.1as2_head`) دیده می‌شود و همان `shard_id` است که در کلید onode با 0x80 جمع می‌شود (فصل ۲۴). فرمان‌هایی مثل `ceph pg ... query` شناسه‌ی PG را بدون پسوند می‌گیرند (`5.1a`)؛ وضعیت هر shard در فهرست `peer_info` خروجی آمده است.
:::

# کدگذاری پاک‌شونده با عدد: ماتریس Reed-Solomon، حد MDS، به‌روزرسانی دلتای parity و هزینه‌ی بازسازی {#sec-13-9}

این بخش ریاضیات پشت افزونه‌ی ISA را روی بایت‌های واقعی اجرا می‌کند. ارجاع‌ها به src/erasure-code/isa در main (نوامبر 2026) و به تابع gf_gen_rs_matrix در کتابخانه‌ی ISA-L (erasure_code/ec_base.c) است. حساب $\mathrm{GF}(2^8)$ با چندجمله‌ای 0x11d در پایتون بازپیاده‌سازی و با جدول gff_base در ISA-L تطبیق داده شده است.

## کدگذاری و بازگشایی یک ستون بایت {#sec-13-9-1}

::: {.algo #alg-13-1 title="Reed-Solomon با ماتریس Vandermonde در ISA (technique=reed_sol_van)" src="src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::prepare، isa_encode، isa_decode؛ ISA-L ec_base.c :: gf_gen_rs_matrix" complexity="کدگذاری O(k × m) ضرب GF برای هر بایت؛ بازگشایی O(k³) برای وارون ماتریس (در cache جدول‌ها نگه‌داری می‌شود)"}
:::

```text
pseudocode
G[0..k−1] = I_k                        # systematic: shardهای داده همان داده‌اند
gen = 1
for i in k .. k+m−1: G[i][j] = gen^j ; gen = gen × 2      (در GF(2^8))
parity_i = ⊕_j G[i][j] ⊗ d_j
بازگشایی: k سطر سالم را انتخاب کن ← B ؛ d = B⁻¹ × (shardهای سالم)
```

**مثال عددی (k = 4، m = 2، بایت‌های «ABCD»).** سطر P0 همه یک است، پس P0 = 0x41 ⊕ 0x42 ⊕ 0x43 ⊕ 0x44 = 0x04. سطر P1 برابر 1، 2، 4 و 8 است: 2 ⊗ 0x42 = 0x84، ‏4 ⊗ 0x43 = 0x11 و 8 ⊗ 0x44 = 0x1a، پس P1 = 0xce. اگر d1 و d3 از دست بروند، سطرهای d0، d2، P0 و P1 یک ماتریس 4×4 می‌سازند که وارون آن 0x42 و 0x44 را دوباره می‌دهد. هر 15 حالت از دست رفتن دو shard در 4+2 قابل بازگشایی است.

![کدگذاری Reed-Solomon روی یک ستون بایت. چپ: ماتریس 6×4 ساخته‌شده با gf_gen_rs_matrix، شامل همانی برای داده و دو سطر parity. راست: محاسبه‌ی P0 و P1 برای «ABCD» و بازگشایی پس از از دست رفتن d1 و d3. ضرب‌ها در GF(2⁸) با چندجمله‌ای 0x11d انجام شده‌اند](figures/ch13/f09_gfencode.png){#fig-13-f09_gfencode}

## چرا ISA گاهی به Cauchy برمی‌گردد؟ {#sec-13-9-2}

::: {.algo #alg-13-2 title="بررسی MDS بودن ماتریس Vandermonde" src="src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::parse (m > 4، یا m = 4 و k > 21 ← cauchy)" complexity="بررسی کامل: Σ C(k,e)·C(m,e) وارون ماتریس"}
:::

```text
pseudocode
برای هر e از 1 تا m، هر زیرمجموعه‌ی L از e shard داده و P از e سطر parity:
    سطرها = (داده‌های سالم) ∪ P
    if det = 0 در GF(2^8): الگوی L قابل بازگشایی نیست
کد MDS است اگر هیچ الگویی شکست نخورد
```

**نتیجه‌ی بررسی کامل ما.** برای 4+2 و 21+4 هیچ الگوی شکستی نیست. برای 22+4 دو الگو وجود دارد، مثلاً از دست رفتن d0، ‏d10، ‏d21 و P2، که با وجود m = 4 داده را برنمی‌گرداند. برای 8+5 شش الگو هست (مثلاً d0، ‏d2، ‏d5، ‏P1 و P2). برای 4+5 مشکلی پیدا نشد. پس قاعده‌ی کد، یعنی تغییر به Cauchy برای m > 4 یا m = 4 با k > 21، دقیقاً همان مرز شکست در m = 4 است و برای m > 4 محافظه‌کارانه عمل می‌کند. پیام هشدار آن هنگام ساخت پروفایل («switching to Cauchy technique») را جدی بگیرید: technique واقعی pool با چیزی که نوشته‌اید فرق می‌کند.

![تعداد الگوهای از دست رفتنِ حداکثر m ‏shard که با ماتریس Vandermonde قابل بازگشایی نیستند. سبز یعنی MDS است و قرمز یعنی شکست دارد. بررسی کامل با اسکریپت ما بر پایه‌ی gf_gen_rs_matrix انجام شده است](figures/ch13/f10_mds.png){#fig-13-f10_mds}

## به‌روزرسانی دلتای parity {#sec-13-9-3}

::: {.algo #alg-13-3 title="نوشتن parity-delta در FastEC" src="src/erasure-code/isa/ErasureCodeIsa.cc :: encode_delta، apply_delta (ec_encode_data_update)؛ src/osd/ECTransaction.cc (do_parity_delta_write)" complexity="O(m) ضرب GF برای هر بایت تغییرکرده"}
:::

```text
pseudocode
delta = old_d ⊕ new_d                       # encode_delta
for هر parity i: P_i ⊕= G[i][j] ⊗ delta      # apply_delta؛ برای m=1 فقط XOR
انتخاب در OSD (ec_pdw_write_mode = 0):
    conv = shardهایی که RMW معمولی باید بخواند ؛ pdw = shard تغییرکرده + parityها
    if |pdw| ≥ k: معمولی
    elif pdw بازسازی لازم دارد: معمولی ؛ elif فقط معمولی بازسازی لازم دارد: pdw
    else: pdw اگر |pdw| ≤ |conv|  (تساوی ← pdw)
```

**مثال عددی.** d2 از 0x43 به 0x5a تغییر می‌کند. delta = 0x19 است، پس P0 = 0x04 ⊕ 0x19 = 0x1d و P1 = 0xce ⊕ (4 ⊗ 0x19 = 0x64) = 0xaa، که همان نتیجه‌ی کدگذاری دوباره‌ی کامل است. برای بازنویسی 4K یک shard: در 4+2، RMW معمولی سه shard داده‌ی دیگر را می‌خواند و PDW شامل d2 قدیمی و دو parity است، یعنی 3 در برابر 3. در تساوی PDW انتخاب می‌شود. در 8+3 مقایسه 7 در برابر 4 و به نفع PDW است. در 2+2 مقایسه 1 در برابر 3 است و مسیر معمولی برنده است. این مسیر فقط در pool با FastEC (allow_ec_optimizations، Tentacle به بعد) و افزونه‌ای که پرچم paritydelta دارد (ISA و Jerasure) فعال است.

![گام‌های به‌روزرسانی دلتای parity برای تغییر یک بایت در d2: XOR قدیم و جدید، ضرب در ضریب ستون همان shard و XOR در هر parity. سطر آخر تطبیق با کدگذاری دوباره‌ی کامل را نشان می‌دهد. خط بنفش شمار shardهای خواندنی در دو مسیر را برای سه پروفایل مقایسه می‌کند](figures/ch13/f11_delta.png){#fig-13-f11_delta}

## هزینه‌ی بازسازی یک shard: RS، ‏LRC و CLAY {#sec-13-9-4}

::: {.algo #alg-13-4 title="حجم خواندن برای بازسازی یک chunk" src="src/erasure-code/clay/ErasureCodeClay.cc :: parse (q = d − k + 1، t = (k+m+nu)/q، sub_chunk_no = qᵗ)؛ src/erasure-code/lrc" complexity="O(1)"}
:::

```text
pseudocode
RS:   read = k chunk
LRC:  read = l chunk (گروه محلی) ؛ سربار خام = (k + m + (k+m)/l) / k
CLAY: q = d − k + 1 ؛ هر یک از d کمک‌کننده 1/q از chunk را می‌فرستد ؛ read = d / q chunk
      شرط: k + 1 ≤ d ≤ k + m − 1 ؛ sub-chunkها = q^t
```

**مثال عددی.** در 4+2، بازسازی RS چهار chunk می‌خواند. LRC با l = 3 سه chunk می‌خواند، اما سربار خامش 2.0 است، نه 1.5. CLAY با d = 5 (q = 2، t = 3 و 8 sub-chunk) فقط 2.5 chunk می‌خواند و سربار 1.5 را حفظ می‌کند. در 8+4، اعداد برای RS، ‏LRC (l = 4، سربار 1.875) و CLAY (d = 11، q = 4، 64 sub-chunk) به ترتیب 8، 4 و 2.75 chunk است. هزینه‌ی CLAY در خواندن‌های تکه‌تکه است: هر کمک‌کننده sub-chunkهای پراکنده می‌فرستد، پس روی HDD تعداد seekها بیشتر می‌شود.

![داده‌ی خوانده‌شده برای بازسازی یک chunk ازدست‌رفته با RS، ‏LRC و CLAY در دو پیکربندی، همراه سربار خام هر طرح. LRC خواندن را با فضای بیشتر کم می‌کند و CLAY با همان فضای RS](figures/ch13/f12_repair.png){#fig-13-f12_repair}

# از درون کد: EC در OSD {#sec-13-10}

## نقشه‌ی فایل‌ها {#sec-13-10-1}

| مسیر | نقش |
|---|---|
| src/erasure-code/ErasureCodeInterface.h | رابط افزونه‌ها: init، encode، decode، minimum_to_decode، پرچم‌های بهینه‌سازی |
| src/erasure-code/isa, jerasure, lrc, shec, clay | پیاده‌سازی افزونه‌ها |
| src/osd/ECSwitch.h | سوییچ بین پیاده‌سازی قدیمی (ECBackendL) و بهینه (ECBackend) |
| src/osd/ECBackend.cc, ECCommon.cc | مسیر خواندن، نوشتن و بازیابی بهینه |
| src/osd/ECTransaction.cc | برنامه‌ریزی نوشتن: تعیین خواندن‌های لازم، RMW یا parity delta |
| src/osd/ECUtil.h | stripe_info_t و نگاشت محدوده‌ی منطقی به shardها |
| src/osd/OSDMap.cc | pgtemp_primaryfirst برای انتخاب primary در poolهای بهینه |

## رابط افزونه {#sec-13-10-2}

هر افزونه کلاسی است که `ErasureCodeInterface` را پیاده می‌کند. توابع کلیدی (امضاها خلاصه شده‌اند):

- `init(profile, ss)`: پارامترهای پروفایل را می‌خواند و ماتریس را می‌سازد.
- `get_chunk_count()` و `get_data_chunk_count()`: k+m و k.
- `minimum_to_decode(want_to_read, available, minimum)`: کمترین مجموعه‌ی shard برای خواندن خواسته‌شده.
- `encode(want_to_encode, in, encoded)` و `decode(want_to_read, chunks, decoded)`.
- `get_supported_optimizations()`: پرچم‌هایی که FastEC بر اساس آن‌ها تصمیم می‌گیرد.

```cpp
// from ceph/ceph, LGPL — src/erasure-code/ErasureCodeInterface.h (excerpt)
FLAG_EC_PLUGIN_PARTIAL_READ_OPTIMIZATION = 1<<0,
FLAG_EC_PLUGIN_PARTIAL_WRITE_OPTIMIZATION = 1<<1,
FLAG_EC_PLUGIN_ZERO_INPUT_ZERO_OUTPUT_OPTIMIZATION = 1<<2,
FLAG_EC_PLUGIN_ZERO_PADDING_OPTIMIZATION = 1<<3,
FLAG_EC_PLUGIN_PARITY_DELTA_OPTIMIZATION = 1<<4,
```

این پرچم‌ها توضیح می‌دهند چرا FastEC فقط با برخی افزونه‌ها کار می‌کند: هر بهینه‌سازی به ویژگی ریاضی خاصی نیاز دارد. مثلاً «zero in, zero out» یعنی encode بلوک تمام‌صفر، parity تمام‌صفر می‌دهد (برای کدهای خطی درست است) تا بتوان از نوشتن padding صفر صرف‌نظر کرد. parity delta به خطی بودن کد تکیه دارد: اگر داده‌ی shard j از d به d' تغییر کند، parity جدید برابر است با parity قدیم به‌علاوه‌ی G[i][j]⊗(d ⊕ d').

## ECSwitch: گذار تدریجی {#sec-13-10-3}

کامنت ابتدای `ECSwitch.h` صریح است: این کلاس «سوییچر موقت» بین پیاده‌سازی legacy و optimized است تا وقتی پیاده‌سازی جدید به اندازه‌ی کافی مورد اعتماد شود. `ECSwitch` هر دو شیء `ECLegacy::ECBackendL legacy` و `ECBackend optimized` را دارد و بر اساس پرچم pool (`allow_ec_optimizations`) درخواست‌ها را به یکی هدایت می‌کند. به همین دلیل پرچم برگشت‌پذیر نیست: پس از نوشتن داده با قالب جدید، پیاده‌سازی قدیمی نمی‌تواند آن را بخواند.

## تصمیم RMW یا parity delta {#sec-13-10-4}

در `ECTransaction.cc` برای هر نوشتن، طرح (plan) ساخته می‌شود. منطق انتخاب، ساده‌شده:

```cpp
// from ceph/ceph, LGPL — src/osd/ECTransaction.cc (excerpt, simplified indentation)
if (sinfo.supports_parity_delta_writes() && !object_in_cache &&
    orig_size == projected_size && !reads.empty() && !op.truncate) {
  ...
  if (pdw_write_mode != 0) {
    do_parity_delta_write = (pdw_write_mode == 2);
  } else if (pdw_read_shards.size() >= sinfo.get_k()) {
    do_parity_delta_write = false;
  } else if (!shard_id_set::difference(pdw_read_shards, readable_shards).empty()) {
    do_parity_delta_write = false;
  } else if (!shard_id_set::difference(read_shards, readable_shards).empty()) {
    do_parity_delta_write = true;
  } else {
    do_parity_delta_write = pdw_read_shards.size() <= read_shards.size();
  }
}
```

خوانش: parity delta فقط وقتی معنا دارد که اندازه‌ی شیء تغییر نکند، truncate نباشد و داده در cache نباشد. اگر parity delta نیازمند k خواندن یا بیشتر باشد، مزیتی ندارد؛ اگر برای parity delta بازسازی لازم باشد، کنار گذاشته می‌شود؛ اگر برای RMW معمولی بازسازی لازم باشد ولی برای parity delta نه، parity delta انتخاب می‌شود؛ در غیر این صورت روشی که خواندن کمتری دارد (با ترجیح parity delta در تساوی). متغیر `pdw_write_mode` اجازه می‌دهد برای آزمایش یکی از دو روش را اجبار کرد.

## چرا shard 0 همیشه primary نیست؟ {#sec-13-10-5}

در poolهای بهینه، برخی shardهای داده در هر I/O به‌روز نمی‌شوند (نوشتن جزئی فقط shard تغییرکرده و parityها را لمس می‌کند). چنین shardی نمی‌تواند primary شود، چون primary باید log کامل PG را داشته باشد. اما منطق انتخاب primary در OSDMap را نمی‌توان تغییر داد بدون اینکه کلاینت‌ها ارتقا یابند. راه‌حل `OSDMap::pgtemp_primaryfirst()`: OSDMonitor هنگام تنظیم pg_temp ترتیب را طوری عوض می‌کند که shardهای مجاز primary اول بیایند.

![مثال کامنت کد برای pool بهینه‌ی 4+2: shard 0 از دست رفته است؛ pg_temp طوری مرتب می‌شود که shardهای parity (که همیشه به‌روزند) جلو بیایند و osd.9 primary شود](figures/ch13/f06_pgtemp.png){#fig-13-f06_pgtemp}

```cpp
// from ceph/ceph, LGPL — src/osd/OSDMap.cc (comment excerpt)
 * Example: Optimized EC pool 4+2
 * acting_set = {NONE, 6, 7, 8, 9, 10}
 * non_primary_shards = {1, 2, 3} # data shards other than shard 0
 * pg_temp = {NONE, 9, 10, 6, 7, 8} # non-primary shards at end
 * primary will be OSD 9(1)
```

## شبه‌کد خواندن تخریب‌شده {#sec-13-10-6}

```text
read(obj, off, len):
  want = shards_covering(off, len)                 # ECUtil: محدوده‌ی منطقی → shard extents
  avail = shards_up_and_not_missing(obj)
  if want ⊆ avail:                                  # خواندن جزئی (FastEC)
     return gather(want)
  need = ec_impl.minimum_to_decode(want, avail)     # k shard
  chunks = gather(need)
  return ec_impl.decode(want, chunks)[off:len]
```

::: {.summary title="نکات SRE این فصل"}

- EC به دامنه‌های خرابی کافی نیاز دارد: دست‌کم k+m، ترجیحاً k+m+1.
- پروفایل تغییرناپذیر است؛ از ابتدا درست انتخاب کنید.
- poolهای تازه: ISA-L؛ در Tentacle+ با FastEC و stripe_unit=16K برای RBD/CephFS.
- فراداده، omap و شاخص bucketها روی pool تکثیری.
- 2147483647 یعنی CRUSH جایگاه shard را پر نکرده؛ `crushtool --test` را اجرا کنید.
- بازیابی EC پرهزینه است؛ LRC یا CLAY را برای کلاسترهای بزرگ بررسی کنید.

:::

# تکمیلی و به‌روز {#sec-13-11}

- **Luminous**: `allow_ec_overwrites` و پشتیبانی RBD و CephFS روی EC.
- **Tentacle**: FastEC با `allow_ec_optimizations`؛ ISA-L پیش‌فرض کلاسترهای تازه؛ رفع اشکال‌های برنامه‌ریزی truncate+write.
- **Squid**: قانون CRUSH نوع MSR برای پیکربندی‌های انعطاف‌پذیرتر EC.
- **کد جاری**: `osd_pool_default_flag_ec_optimizations=false` (FastEC برای poolهای تازه خودکار روشن نیست).

# تمرین عملی {#sec-13-12}

1. پروفایل‌های 2+1، 4+2 و 8+3 را بسازید و با `ceph osd erasure-code-profile get` مقایسه کنید. کدام روی کلاستر شما قابل اجراست؟
2. یک pool 4+2 بسازید، شیئی بنویسید و با `ceph osd map` ببینید هر shard روی کدام OSD است. یک OSD را متوقف کنید و شیء را بخوانید.
3. pool EC را به‌عنوان data-pool یک image RBD استفاده کنید و با fio نوشتن تصادفی ۴ کیلوبایتی را با pool تکثیری مقایسه کنید.
4. در کلاستر Tentacle آزمایشی، همان آزمایش را با `allow_ec_optimizations` و stripe_unit=16K تکرار کنید.
5. pool 4+2 را روی کلاستری با پنج میزبان بسازید و 2147483647 را در `ceph pg dump` مشاهده کنید؛ سپس با `crushtool --test` تأیید کنید.
6. در کد، تابع `pgtemp_primaryfirst` را بخوانید و با مثال خودتان (8+3) خروجی را پیش‌بینی کنید.

# پرسش‌های مرور {#sec-13-13}

1. سربار و تحمل خرابی EC 8+3 در مقایسه با تکثیر سه‌تایی چیست؟
2. چرا هر زیرماتریس k×k ماتریس مولد باید وارون‌پذیر باشد؟
3. تفاوت shard در EC و نسخه در تکثیر چیست؟
4. چرا نوشتن کوچک در EC قدیمی پرهزینه بود؟
5. parity delta بر چه ویژگی ریاضی تکیه دارد؟
6. محدودیت‌های فعال‌سازی FastEC کدام‌اند؟
7. چرا پرچم allow_ec_optimizations برگشت‌پذیر نیست؟
8. CLAY و LRC چطور ترافیک بازیابی را کاهش می‌دهند؟
9. عدد 2147483647 در نگاشت PG چه معنایی دارد و علت‌های رایج آن کدام‌اند؟
10. چرا در pool بهینه، primary همیشه shard 0 نیست؟

# منابع این فصل {#sec-13-14}

- Erasure code: https://docs.ceph.com/en/latest/rados/operations/erasure-code/
- Erasure code profiles: https://docs.ceph.com/en/latest/rados/operations/erasure-code-profile/
- ISA plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-isa/
- LRC plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-lrc/
- CLAY plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-clay/
- SHEC plugin: https://docs.ceph.com/en/latest/rados/operations/erasure-code-shec/
- Tentacle release notes: https://docs.ceph.com/en/latest/releases/tentacle/
- Source: src/erasure-code: https://github.com/ceph/ceph/tree/main/src/erasure-code
- Source: src/osd/ECTransaction.cc, ECSwitch.h, OSDMap.cc: https://github.com/ceph/ceph/tree/main/src/osd
- Intel ISA-L: https://github.com/intel/isa-l
- Plank, "A Tutorial on Reed-Solomon Coding for Fault-Tolerance in RAID-like Systems": https://web.eecs.utk.edu/~jplank/plank/papers/CS-96-332.pdf
