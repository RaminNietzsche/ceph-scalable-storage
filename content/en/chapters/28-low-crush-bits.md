---
chapter: 28
id: ch28
title: 'Lower Layers (6): CRUSH at the Bit Level, from rjenkins to upmap'
part: lower
lang: en
translation: pending
---

# مقدمه: CRUSH چگونه «حساب» می‌کند؟ {#sec-28-1}

در فصل‌های ۱ و ۸ CRUSH را به‌عنوان الگوریتمی دیدیم که بدون جدول مرکزی جای هر PG را تعیین می‌کند. این فصل تا سطح بیت پایین می‌رود: hashهای rjenkins که هر تصمیم را تعیین‌پذیر می‌کنند، الگوریتم straw2 با جدول لگاریتم fixed-point، اجرای گام‌به‌گام `crush_do_rule`، تلاش‌های مجدد هنگام تصادم، و در پایان این‌که choose_args، weight-set و upmap نتیجه‌ی خام CRUSH را چگونه اصلاح می‌کنند. یک مثال کامل را از نام شیء تا انتخاب host با اعدادی دنبال می‌کنیم که با کامپایل همان کد C مربوط به Ceph (`src/crush/hash.c` و `mapper.c`، LGPL) در یک برنامه‌ی آزمایشی کوچک محاسبه شده‌اند.

::: {.summary}

- نام شیء با `ceph_str_hash_rjenkins` hash می‌شود. `ceph_stable_mod` آن را به یک PG نگاشت می‌کند و با `HASHPSPOOL`، ورودی CRUSH برابر `crush_hash32_2(ps, pool)` است.
- straw2 برای هر آیتم یک «قرعه» محاسبه می‌کند: draw = ln(u) / w، که u یک hash شانزده‌بیتی است و ln از جدول fixed-point به دست می‌آید. بیشترین draw برنده است. احتمال برنده شدن هر آیتم دقیقاً با وزنش متناسب است.
- تصادم (انتخاب تکراری) با افزایش r حل می‌شود (r = rep + ftotal) تا `choose_total_tries=50`.
- `reweight` با `is_out` احتمالی کار می‌کند. weight-set در choose_args وزن جایگزین برای CRUSH است و upmap نتیجه را پس از CRUSH صریحاً جایگزین می‌کند.

:::

# از نام شیء تا x {#sec-28-2}

![خط لوله‌ی کامل نگاشت. نام شیء با rjenkins به 0xD1895615 hash می‌شود. با pg_num=128، ceph_stable_mod نتیجه‌ی 0x15 را می‌دهد، یعنی PG 3.15. با پرچم HASHPSPOOL، شماره‌ی pool هم در hash دخیل می‌شود تا PGهای poolهای مختلف روی هم نیفتند، و x = 0x36D15C32 ورودی CRUSH است. crush_do_rule فهرست خام OSDها را برمی‌گرداند، سپس OSDهای ناموجود حذف و upmapها اعمال می‌شوند و در پایان pg_temp مجموعه‌ی acting را تعیین می‌کند](figures/ch28/f01_pipe.png){#fig-28-f01_pipe}

`ceph_stable_mod(x, b, bmask)` در `include/rados.h` تعریف شده است: اگر `x & bmask` کمتر از b باشد، همان را برمی‌گرداند، وگرنه `x & (bmask >> 1)`. این تابع «پایدار» است، چون وقتی pg_num از ۱۲۸ به ۱۹۲ افزایش می‌یابد، فقط PGهایی که بیت جدید را دارند جابه‌جا می‌شوند (split) و بقیه همان شماره را نگه می‌دارند. این دلیل ریاضی آن است که split فقط بخشی از داده را حرکت می‌دهد.

| گام | مقدار در مثال | تابع |
|---|---|---|
| hash نام | 0xD1895615 | `ceph_str_hash_rjenkins` (`common/ceph_hash.cc`) |
| ps | 0x15 (= 0xD1895615 & 127) | `ceph_stable_mod(h, 128, 127)` |
| PG | 3.15 | `pg_t(ps, pool)` |
| x (pps) | 0x36D15C32 | `crush_hash32_2(RJENKINS1, ps, 3)` در `pg_pool_t::raw_pg_to_pps` |

## hash مربوط به rjenkins {#sec-28-2-1}

`crush_hashmix(a, b, c)` نُه دور تفریق، XOR و شیفت روی سه کلمه‌ی ۳۲ بیتی است، برگرفته از تابع ترکیب Bob Jenkins. نسخه‌ی سه‌ورودی `crush_hash32_rjenkins1_3(a, b, c)` با `hash = 1315423911 ^ a ^ b ^ c` (ثابت `crush_hash_seed`) شروع می‌کند و پنج بار mix را با ثابت‌های `x = 231232` و `y = 1232` اجرا می‌کند. ویژگی مهم آن **تعیین‌پذیری کامل روی همه‌ی معماری‌ها** است: فقط عملیات صحیح بدون علامت ۳۲ بیتی دارد، بدون اعشار. به همین دلیل کلاینت هسته‌ی لینوکس (که همین فایل را در `net/ceph/crush/` دارد) و librados دقیقاً همان نتیجه را می‌گیرند.

::: {.warn}
هر تغییری در این توابع، در جدول لگاریتم یا در tunableها (مثل `chooseleaf_stable`) نگاشت تقریباً همه‌ی PGها را عوض می‌کند. به همین دلیل tunableها پروفایل‌های نام‌دار دارند (`ceph osd crush tunables optimal`) و تغییر آن‌ها روی خوشه‌ی پر، حرکت داده‌ی عظیمی ایجاد می‌کند.
:::

# straw2: قرعه‌کشی نمایی {#sec-28-3}

فرض کنید هر آیتم i با وزن w_i یک متغیر تصادفی نمایی با نرخ w_i بکشد. احتمال این‌که آیتم i **کمترین** مقدار را داشته باشد، دقیقاً w_i / Σw است. straw2 همین را بدون عدد اعشاری پیاده می‌کند:

```text
straw2 (منطق mapper.c، LGPL؛ نمایش ساده‌شده از این کتاب)
  for each item i in bucket:
      u    = crush_hash32_3(bucket.hash, x, id_i, r) & 0xFFFF       # 16 بیت
      ln   = crush_ln(u) − 2^48          # ≈ 2^44 · log2((u+1)/2^16) ≤ 0
      draw = ln / weight_i                # weight در 16.16 fixed-point
  return item with max draw              # کمترین −ln/w = نمایی با نرخ w
```

`crush_ln(x)` مقدار 2^44 · log2(x+1) را با دو جدول `__RH_LH_tbl` و `__LL_tbl` (در `crush_ln_table.h`) و فقط با عملیات صحیح محاسبه می‌کند. ابتدا ورودی را نرمال می‌کند (توان)، سپس با ۸ بیت بالای mantissa در جدول اول (تقریب 1/x و log2) و با ۸ بیت بعدی در جدول دوم (تصحیح) جست‌وجو می‌کند. نتیجه‌ها در برنامه‌ی آزمایشی ما: `crush_ln(0) = 0`، `crush_ln(0x7FFF) = 0xF00000000000` (یعنی 15 · 2^44) و `crush_ln(0xFFFF) = 0xFFFFF0000000` (تقریباً 16 · 2^44 = 2^48).

![اجرای واقعی straw2 برای x=0x36D15C32 در یک bucket ریشه با سه host: -3 و -4 هرکدام با وزن ۱۰ و -5 با وزن ۲۰. در r=0، host -4 با بیشترین draw (−8.9M) برنده است. در r=1، host -5 برنده است. برای replica سوم، r=2 تا r=5 به hostهای تکراری می‌رسند و هر بار ftotal افزایش می‌یابد، تا این‌که r=6 به host -3 می‌رسد. سقف تلاش choose_total_tries=50 است](figures/ch28/f02_straw2.png){#fig-28-f02_straw2}

| r | draw(-3) | draw(-4) | draw(-5) | برنده |
|---|---|---|---|---|
| 0 | −77,259,388 | **−8,880,361** | −31,248,985 | -4 |
| 1 | −7,177,981 | −14,582,287 | **−3,918,635** | -5 |
| 2 | −11,854,384 | −59,760,693 | **−2,413,629** | -5 (تکراری) |
| 3 | −63,878,138 | −125,349,258 | **−14,701,300** | -5 (تکراری) |

**بررسی توزیع:** در همان برنامه، با سه آیتم با وزن‌های 1، 1 و 2 و ۳۰۰٬۰۰۰ مقدار x، شمارش برنده‌ها 75,274، 74,753 و 149,973 بود، یعنی ۲۵٪، ۲۵٪ و ۵۰٪، همان‌طور که نظریه پیش‌بینی می‌کند.

::: {.deep}
**چرا straw2 و نه straw؟** در straw قدیمی، «طول نی» هر آیتم از روی وزن‌ها به‌صورت نسبی و وابسته به سایر آیتم‌ها محاسبه می‌شد. بنابراین تغییر وزن یک آیتم، draw آیتم‌های دیگر را هم تغییر می‌داد و داده بین آیتم‌هایی جابه‌جا می‌شد که وزنشان تغییر نکرده بود. در straw2، draw هر آیتم فقط به (x، id، r، وزن خودش) بستگی دارد. اگر وزن آیتم A زیاد شود، فقط برخی x‌ها از سایر آیتم‌ها به A **منتقل** می‌شوند و هیچ داده‌ای بین B و C جابه‌جا نمی‌شود. این خاصیت حداقل حرکت (optimal reorganization) است.
:::

# crush_do_rule گام‌به‌گام {#sec-28-4}

![اجرای replicated_rule. TAKE ریشه را در بردار کاری w می‌گذارد. CHOOSELEAF_FIRSTN با numrep=0 (یعنی برابر size) برای هر replica یک host انتخاب می‌کند و سپس به‌صورت بازگشتی یک OSD درون آن. EMIT نتیجه را به خروجی می‌افزاید. در هر انتخاب، r = rep + ftotal است. اگر نتیجه تکراری باشد یا OSD با is_out رد شود، ftotal افزایش می‌یابد و تلاش تکرار می‌شود. is_out برای وزن reweight بین ۰ و ۱، با hash دیگری از (x، osd) تصمیم احتمالی می‌گیرد](figures/ch28/f03_rule.png){#fig-28-f03_rule}

یک قاعده آرایه‌ای از گام‌هاست (`crush_rule_step` با op، arg1 و arg2). `crush_do_rule` یک بردار کاری `w` و یک بردار خروجی `o` دارد:

| op | مقدار | عمل |
|---|---|---|
| `TAKE` | 1 | w = [arg1] (مثلاً id ریشه یا یک device class در shadow tree) |
| `CHOOSE_FIRSTN` | 2 | از هر bucket در w، arg1 آیتم از نوع arg2 انتخاب کن (برای replicated) |
| `CHOOSE_INDEP` | 3 | همان، با جایگاه‌های ثابت (برای EC؛ shard گم‌شده جای خالی می‌ماند) |
| `EMIT` | 4 | o += w؛ w خالی می‌شود |
| `CHOOSELEAF_FIRSTN` / `_INDEP` | 6 / 7 | انتخاب bucket از نوع arg2 و سپس یک leaf (OSD) در آن |
| `SET_CHOOSE_TRIES` و موارد مشابه | 8–13 | override کردن tunableها برای همین قاعده |
| `SET_MSR_DESCENTS` / `SET_MSR_COLLISION_TRIES` / `CHOOSE_MSR` | 14 / 15 / 16 | قواعد MSR (چند OSD در هر failure domain) — در Squid و بالاتر، نه در Reef |

**numrep:** اگر arg1 ≤ 0 باشد، numrep = result_max + arg1. پس `0` یعنی «به تعداد size» و `-1` یعنی «size منهای یک». این برای قواعدی مثل «یکی در DC اول، بقیه در DC دوم» استفاده می‌شود.

## firstn در برابر indep {#sec-28-4-1}

در **firstn**، ترتیب مهم نیست. اگر replica دوم ناموجود شود، replica سوم جایش را می‌گیرد و همه‌چیز یک خانه به جلو می‌رود. برای replication این بهینه است، چون فقط یک کپی تازه لازم است. در **indep**، جایگاه r ام همیشه shard r ام است. اگر OSD یک shard از دست برود، فقط همان جایگاه با r تازه (r + numrep · ftotal) دوباره انتخاب می‌شود و بقیه‌ی shardها جابه‌جا نمی‌شوند. برای EC این حیاتی است، چون shardها قابل‌جابه‌جایی نیستند.

| tunable (پروفایل jewel/optimal) | مقدار | اثر |
|---|---|---|
| `choose_local_tries` | 0 | تلاش محلی قدیمی خاموش |
| `choose_local_fallback_tries` | 0 | خاموش |
| `choose_total_tries` | 50 | سقف تلاش‌ها؛ در مثال ما ۴ تلاش ناموفق داشتیم |
| `chooseleaf_descend_once` | 1 | در chooseleaf، یک بار پایین برو و اگر شکست خورد از بالا تلاش کن |
| `chooseleaf_vary_r` | 1 | r در زیرانتخاب leaf به r والد وابسته است تا تلاش‌های مجدد نتیجه‌ی متفاوت بدهند |
| `chooseleaf_stable` | 1 | با out شدن یک OSD، replicaهای دیگر جابه‌جا نمی‌شوند |
| `straw_calc_version` | 1 | اصلاح محاسبه‌ی straw قدیمی |

::: {.note}
تصادم‌ها وقتی تعداد failure domainها به size نزدیک است زیاد می‌شوند. در مثال ما با سه host و size=3، replica سوم پس از ۴ تلاش پیدا شد. اگر یکی از hostها وزن بسیار کمی داشته باشد، ممکن است ۵۰ تلاش هم کافی نباشد و PG با کمتر از size عضو در وضعیت `undersized` بماند. `crushtool --test --show-bad-mappings` همین را آزمایش می‌کند.
:::

```bash
ceph osd getcrushmap -o cm.bin && crushtool -d cm.bin -o cm.txt
crushtool -i cm.bin --test --rule 0 --num-rep 3 --min-x 0 --max-x 1023 --show-utilization
crushtool -i cm.bin --test --rule 0 --num-rep 3 --x 0x36d15c32 --show-mappings
crushtool -i cm.bin --test --show-bad-mappings --rule 0 --num-rep 3
ceph osd map rbd rbd_data.10ab2c3d4e5f.0000000000000000     # pg و up/acting
```

# choose_args، weight-set و upmap {#sec-28-5}

![سه ابزار اصلاح توزیع و ترتیب اعمال آن‌ها. reweight با is_out احتمالی کار می‌کند و جابه‌جایی گسترده ایجاد می‌کند. choose_args (weight-set) وزن‌های جایگزینی برای straw2 فراهم می‌کند که حتی می‌تواند برای هر position (replica اول، دوم و ...) متفاوت باشد و balancer در حالت crush-compat از آن استفاده می‌کند. upmap پس از CRUSH نتیجه را صریحاً جایگزین می‌کند. در OSDMap ترتیب اعمال این است: crush_do_rule با choose_args، حذف OSDهای ناموجود، pg_upmap، pg_upmap_items و pg_upmap_primary](figures/ch28/f04_adjust.png){#fig-28-f04_adjust}

**choose_args:** در `bucket_straw2_choose`، تابع `get_choose_arg_weights` اگر `weight_set` موجود باشد، به‌جای `item_weights` از `weight_set[position]` استفاده می‌کند. `position` شماره‌ی replica در حال انتخاب است. این امکان اصلاح یک مشکل ظریف را می‌دهد: در straw2 با وزن‌های نابرابر، replica دوم و سوم کمی از نسبت وزن منحرف می‌شوند، چون انتخاب‌های قبلی کنار گذاشته شده‌اند. weight-set برای هر position وزن کمی متفاوتی می‌دهد. `ids` جایگزین هم وجود دارد، تا بتوان hash را بدون تغییر شناسه‌ی واقعی bucket عوض کرد.

**upmap:** `OSDMap::_apply_upmap` ابتدا `pg_upmap` (جایگزینی کل فهرست) را بررسی می‌کند، سپس `pg_upmap_items` (جفت‌های from→to) و در پایان `pg_upmap_primaries` (فقط تعیین primary، برای read balancer). upmapهایی که قاعده‌ی CRUSH را نقض کنند (مثلاً دو replica در یک host) توسط mon بررسی و حذف می‌شوند (`clean_pg_upmaps`).

| حالت balancer | مکانیزم | نسخه |
|---|---|---|
| `crush-compat` | weight-set در choose_args | از Luminous؛ برای کلاینت‌های قدیمی |
| `upmap` | `pg_upmap_items` | پیش‌فرض؛ نیازمند `require-min-compat-client luminous` |
| `read` | `pg_upmap_primaries` (فقط primary) | Reef و بالاتر (طبق مستندات) |
| `upmap-read` | هر دو | Reef و بالاتر |

```bash
ceph osd pg-upmap-items 3.15 4 11        # جایگزینی osd.4 با osd.11 برای PG 3.15
ceph osd rm-pg-upmap-items 3.15
ceph osd crush weight-set ls
ceph balancer status && ceph balancer eval
ceph osd dump | grep -E '^pg_upmap(_items|_primary)?' | head
```

# is_out و reweight: یک مثال عددی {#sec-28-6}

`is_out` در `mapper.c` وزن reweight یک OSD (عددی 16.16 بین 0 و 0x10000) را این‌طور تفسیر می‌کند: اگر وزن کامل باشد، OSD داخل است. اگر صفر باشد، بیرون است. در غیر این صورت، `crush_hash32_2(x, osd) & 0xFFFF` با وزن مقایسه می‌شود و اگر کمتر باشد، OSD برای این x داخل است. پس reweight برابر 0.5 یعنی تقریباً نیمی از PGهایی که CRUSH به این OSD داده بود، رد می‌شوند و با تلاش مجدد به جای دیگری می‌روند.

| مثال | مقدار |
|---|---|
| x | 0x36D15C32 (همان PG 3.15) |
| osd | 7 |
| `crush_hash32_2(x, 7) & 0xFFFF` | 0xC425 |
| reweight 0.5 (0x8000) | 0xC425 ≥ 0x8000 → **out** برای این PG |
| reweight 0.9 (0xE666) | 0xC425 < 0xE666 → **in** |
| نسبت in با reweight 0.5 در ۱۰۰٬۰۰۰ x | 50,069 (≈ ۵۰٪) |

::: {.tip}
تفاوت `ceph osd reweight` (همین is_out احتمالی، که پس از انتخاب straw2 اعمال می‌شود) با `ceph osd crush reweight` (وزن straw2 در خود bucket) مهم است. reweight کردن با is_out باعث تلاش‌های مجدد بیشتر و انحراف ظریف توزیع می‌شود، به همین دلیل balancer مبتنی بر upmap جایگزین بهتری است. مقادیر نزدیک ۱ (مثلاً 0.95) جابه‌جایی کمی ایجاد می‌کنند، ولی مقادیر کوچک (مثلاً 0.3) می‌توانند تلاش‌ها را به سقف ۵۰ نزدیک کنند.
:::

# device class و shadow tree {#sec-28-7}

وقتی OSDها کلاس دارند (`hdd`، `ssd`، `nvme`)، CrushWrapper برای هر bucket و هر کلاس یک «سایه» با id منفی جدید و نامی مثل `default~ssd` می‌سازد که فقط OSDهای آن کلاس را دارد. قاعده‌ای مثل `step take default class ssd` در واقع `TAKE` روی id سایه است. چون سایه‌ها idهای خودشان را دارند، hash مربوط به straw2 (که id آیتم در آن دخیل است) برای سایه‌ها مستقل از درخت اصلی است. افزودن یک OSD از نوع hdd هیچ PGی را در poolهای ssd جابه‌جا نمی‌کند.

```bash
ceph osd crush tree --show-shadow
ceph osd crush rule create-replicated fast default host ssd
ceph osd crush class ls-osd ssd
```

::: {.deep}
**چرا idهای سایه پایدار می‌مانند؟** نگاشت کلاس به id سایه در خود CRUSH map ذخیره می‌شود (`class_bucket`). بنابراین بازسازی سایه‌ها پس از افزودن OSD یا تغییر وزن، همان idها را نگه می‌دارد. اگر این idها تغییر می‌کردند، x مربوط به همه‌ی PGهای poolهای وابسته به آن کلاس hash متفاوتی می‌گرفت و کل داده جابه‌جا می‌شد. ابزار `crushtool --reclassify` برای تبدیل نقشه‌های قدیمی (با ریشه‌های جداگانه برای ssd) به کلاس‌ها، دقیقاً همین idها را طوری تنظیم می‌کند که نگاشت تغییر نکند.
:::

# سه نوع bucket دیگر: uniform، list و tree {#sec-28-8}

straw2 امروز پیش‌فرض است، اما CRUSH از ابتدا پنج الگوریتم bucket داشت: uniform، list، tree، straw و straw2. هرکدام مصالحه‌ای میان سرعت انتخاب و میزان جابه‌جایی داده هنگام تغییر است. نگاشت‌های قدیمی و نقشه‌های دست‌ساز هنوز ممکن است آن‌ها را داشته باشند. برای فهم اینکه چرا straw2 برنده شد، هر سه را با hash واقعی rjenkins اجرا کرده‌ایم. همه‌ی اعداد این بخش با یک برنامه‌ی کوچک C که `hash.c` و `crush_ln` را از کد Ceph می‌گیرد محاسبه شده‌اند.

## uniform: جایگشت شبه‌تصادفی {#sec-28-8-1}

::: {.algo #alg-28-1 title="انتخاب در bucket از نوع uniform با جایگشت تدریجی" src="src/crush/mapper.c :: bucket_perm_choose و bucket_uniform_choose" complexity="r=0 در O(1)؛ r=k در O(k)؛ کار مشترک در crush_work_bucket.perm"}
:::

```text
pseudocode (برگرفته از bucket_perm_choose)
pr = r mod size
if x changed:
    if pr == 0: return items[hash3(x, bucket_id, 0) mod size]        # میان‌بر رایج
    perm = [0..size-1]; perm_n = 0
while perm_n ≤ pr:                         # Fisher–Yates تدریجی با hash به‌جای random
    p = perm_n
    if p < size-1:
        i = hash3(x, bucket_id, p) mod (size − p)
        swap(perm[p], perm[p+i])
    perm_n += 1
return items[perm[pr]]
```

![اجرای واقعی bucket_perm_choose برای bucket با شماره‌ی -5 و چهار item با x=0x1234ABCD. سه گام Fisher–Yates جایگشت \[3 2 0 1\] را می‌سازند. پس r=0 به item 13، r=1 به 12، r=2 به 10 و r=3 به 11 می‌رسد. جایگشت در crush_work نگه داشته می‌شود تا تلاش‌های بعدی با همان x از نو محاسبه نشوند](figures/ch28/f05_uniform.png){#fig-28-f05_uniform}

uniform فقط وقتی درست کار می‌کند که همه‌ی itemها وزن برابر داشته باشند، چون وزن اصلاً در محاسبه نیست. مشکل بزرگ‌تر این است که تغییر `size` پیمانه‌ی همه‌ی hashها را عوض می‌کند. شبیه‌سازی ما نشان می‌دهد افزودن item پنجم به چهار item، **۸۰٪** ورودی‌ها را جابه‌جا می‌کند، در حالی که حداقل لازم ۲۰٪ است. این bucket برای سخت‌افزاری طراحی شد که همیشه یک‌جا و هم‌اندازه خریده و جایگزین می‌شود.

## list: پیمایش از آخر {#sec-28-8-2}

::: {.algo #alg-28-2 title="انتخاب در bucket از نوع list" src="src/crush/mapper.c :: bucket_list_choose" complexity="O(n) در بدترین حالت؛ افزودن به انتها بهینه است"}
:::

```text
for i = size-1 down to 0:
    h = hash4(x, items[i], r, bucket_id) & 0xFFFF                   # عدد 16 بیتی
    if (h × sum_weights[i]) >> 16 < item_weights[i]: return items[i]
return items[0]
# sum_weights[i] = Σ_{j ≤ i} item_weights[j]  ⇒ احتمال انتخاب i به شرط رسیدن به آن = w_i / sum_i
```

![اجرای واقعی bucket_list_choose برای bucket با شماره‌ی -6 با وزن‌های 1، 1 و 2. برای r=0 مقدار مقیاس‌شده‌ی item 22 برابر 3.90 است که از وزن 2 بیشتر است، پس رد می‌شود. item 21 با 0.36 < 1 انتخاب می‌شود. برای r=1 و r=2 هر دو item آخر رد می‌شوند و item 20 انتخاب می‌شود](figures/ch28/f06_list.png){#fig-28-f06_list}

چرا درست است؟ احتمال انتخاب item آخر w₂/(w₀+w₁+w₂) = 2/4 است. اگر رد شود، احتمال item میانی w₁/(w₀+w₁) = 1/2 است. پس P(21) = (1 − 1/2) × 1/2 = 1/4 و P(20) = 1/4. شمارش روی ۴۰۰ هزار ورودی همین نسبت ۱:۱:۲ را داد (100336، 99970، 199694). افزودن item به **انتها** فقط داده‌ی لازم را جابه‌جا می‌کند (۲۰٫۱٪). اما حذف یک item از میانه ترتیب را می‌شکند (در شبیه‌سازی ما ۳۶٪ به‌جای ۲۵٪).

## tree: درخت دودویی وزن‌دار {#sec-28-8-3}

::: {.algo #alg-28-3 title="انتخاب در bucket از نوع tree" src="src/crush/mapper.c :: bucket_tree_choose؛ src/crush/builder.c :: crush_make_tree_bucket" complexity="O(log n)؛ شماره‌ی گره‌ها با افزودن item ثابت می‌ماند"}
:::

```text
node(i) = 2(i+1) − 1   (برگ‌ها فرد)؛ height(n) = تعداد صفرهای انتهایی n
n = num_nodes / 2                          # ریشه
while n is even:                           # گره داخلی
    t = (hash4(x, n, r, bucket_id) × node_weights[n]) >> 32     # عدد یکنواخت در [0, w)
    n = t < node_weights[left(n)] ? left(n) : right(n)
return items[n >> 1]
```

![اجرای واقعی bucket_tree_choose برای چهار item با وزن‌های 1، 2، 3 و 4. ریشه n4 وزن 10 دارد. t=4.22 از وزن زیردرخت چپ (3) بیشتر است، پس مسیر به راست (n6، وزن 7) می‌رود. آنجا t=0.78 < 3، پس برگ n5 یعنی item 32 انتخاب می‌شود. برای r=1 هم همین مسیر طی شد. توزیع روی ۴۰۰ هزار ورودی تقریباً 1:2:3:4 بود](figures/ch28/f07_tree.png){#fig-28-f07_tree}

ترفند زیبای tree شماره‌گذاری گره‌هاست. چون hash به **شماره‌ی گره** وابسته است و شماره‌ی گره‌های موجود با بزرگ شدن درخت تغییر نمی‌کند (ریشه‌ی قدیم n4 در درخت هشت‌برگی فرزند چپ n8 می‌شود)، افزودن item پنجم دقیقاً ۲۰٪ داده را جابه‌جا کرد. اما حذف از میانه و بازسازی درخت، چیدمان برگ‌ها را عوض می‌کند و در شبیه‌سازی ما ۵۴٪ جابه‌جایی داشت.

## مقایسه‌ی جابه‌جایی {#sec-28-8-4}

![درصد ورودی‌هایی که با تغییر bucket مقصد دیگری گرفتند، روی ۲۰۰ هزار مقدار x با hash واقعی. ستون آبی: افزودن item پنجم به چهار item هم‌وزن (حداقل نظری ۲۰٪). ستون نارنجی: حذف item دوم و ساخت دوباره‌ی bucket (حداقل نظری ۲۵٪). فقط straw2 در هر دو حالت به حداقل نظری می‌رسد](figures/ch28/f08_moves.png){#fig-28-f08_moves}

| نوع bucket | هزینه‌ی انتخاب | افزودن | حذف یا تغییر وزن | کاربرد امروز |
|---|---|---|---|---|
| uniform | O(1) | بد (۸۰٪ در شبیه‌سازی) | بد | تقریباً هیچ |
| list | O(n) | بهینه اگر در انتها | بد در میانه | خوشه‌های فقط‌رشدی قدیمی |
| tree | O(log n) | بهینه | متوسط | bucketهای خیلی بزرگ قدیمی |
| straw | O(n) | تقریباً بهینه | تقریباً بهینه، با خطای شناخته‌شده در وزن‌ها | منسوخ، جایگزینش straw2 |
| straw2 | O(n) | بهینه | بهینه (فقط جابه‌جایی به/از item تغییرکرده) | پیش‌فرض |

::: {.note}
شبیه‌سازی حذف، bucket را بدون item حذف‌شده از نو می‌سازد. در عمل، با `ceph osd crush reweight` به صفر یا `crush remove`، رفتار به نوع bucket و جای item بستگی دارد. برای straw2، صفر کردن وزن همان اثر حذف را دارد، چون هر item قرعه‌ی مستقل خودش را می‌کشد.
:::

# balancer در حالت upmap: calc_pg_upmaps {#sec-28-9}

balancer مربوط به mgr در حالت upmap (فصل ۱۹) کار اصلی را به `OSDMap::calc_pg_upmaps` در C++ می‌سپارد. این تابع یک کپی از OSDMap می‌سازد، با جفت‌های `pg_upmap_items` آزمایش می‌کند و نتیجه را در یک Incremental برمی‌گرداند.

![ساختار OSDMap::calc_pg_upmaps. پس از محاسبه‌ی PGهای هر OSD و انحراف هر OSD از هدف وزنی، در هر دور مجموعه‌های overfull و underfull ساخته می‌شوند. سپس از پرترین OSD، نخست حذف upmapهای قبلی و بعد افزودن یک جفت تازه آزموده می‌شود. هر تغییر فقط وقتی پذیرفته می‌شود که امتیاز توازن بدتر نشود](figures/ch28/f09_upmap.png){#fig-28-f09_upmap}

::: {.algo #alg-28-4 title="انتخاب upmap حریصانه با آزمون امتیاز" src="src/osd/OSDMap.cc :: OSDMap::calc_pg_upmaps، calc_deviations، fill_overfull_underfull، try_pg_upmap، find_best_remap" complexity="هر دور O(OSD × PG) برای پیمایش و یک محاسبه‌ی CRUSH برای هر نامزد؛ حداکثر max دور"}
:::

```text
ppw = total_pgs / Σ weight
dev(osd) = pgs(osd) − weight(osd) × ppw
bal_score = Σ weight × (dev / target)²                  # 0 یعنی کامل
repeat up to max times:
    overfull  = {dev > max_deviation};   more_overfull  = {0 < dev ≤ max_deviation}
    underfull = {dev < −max_deviation};  more_underfull = {−max_deviation ≤ dev < 0}
    if overfull and underfull both empty: break
    for osd in OSDs by dev descending (dev > max_deviation):
        if try_drop_remap_overfull(osd): goto test       # اول upmapهای قدیمی را پس بگیر
        for pg on osd (بدون pg_upmap دستی):
            out = try_pg_upmap(pg, overfull, underfull)   # CRUSH را با وزن صفر برای overfullها دوباره اجرا کن
            pos = find_best_remap(orig, out)            # بهترین یک جایگزینی
            if pos ≥ 0: add pair (orig[pos] → out[pos]); goto test
    for osd in underfull: try_drop_remap_underfull(osd) → test
    break
test: if new_bal_score > bal_score: reject (پرش از آن PG)  else: apply
```

**مثال عددی.** چهار OSD هم‌وزن، یک pool با 64 PG و size=3، پس 192 نسخه و هدف 48 برای هر OSD. شمارش‌ها [56، 50، 44، 42] و انحراف‌ها [+8، +2، −4، −6] است. با `upmap_max_deviation=5` (پیش‌فرض ماژول balancer): overfull={osd.0}، underfull={osd.3}. امتیاز = (64 + 4 + 16 + 36)/48² = 0.0521.

| گام | جفت upmap | شمارش‌ها | انحراف‌ها | bal_score |
|---|---|---|---|---|
| 0 | — | 56، 50، 44، 42 | +8، +2، −4، −6 | 0.0521 |
| 1 | (0 → 3) | 55، 50، 44، 43 | +7، +2، −4، −5 | 0.0408 |
| 2 | (0 → 3) برای PG دیگر | 54، 50، 44، 44 | +6، +2، −4، −4 | 0.0313 |
| 3 | (0 → 2) | 53، 50، 45، 44 | +5، +2، −3، −4 | 0.0234 |

پس از گام 3، هیچ OSDی بیش از 5 انحراف ندارد، پس overfull و underfull خالی‌اند و حلقه پایان می‌یابد. از گام 2 به بعد underfull خالی است و جایگزین‌ها از more_underfull می‌آیند. سه ورودی `pg_upmap_items` در OSDMap ثبت می‌شوند. هر تغییر فقط **یک** جفت اضافه می‌کند. توضیح کد می‌گوید این کار عمداً «آرام» است تا هر گام کوچک توزیع را واقعاً به سمت حالت کامل ببرد. فرض این مثال آن است که قانون CRUSH اجازه‌ی این جایگزینی‌ها را بدهد (مثلاً OSDها در hostهای متفاوت باشند). اگر جایگزینی قانون failure domain را بشکند، try_pg_upmap آن را رد می‌کند.

::: {.note}
`osd_calc_pg_upmaps_aggressively` (و نسخه‌ی fast آن) فهرست PGها را مخلوط و جست‌وجوی جامع‌تری می‌کند. در main، `bal_score` با double جمع می‌شود. توضیح کد می‌گوید در float، تغییر یک PG در خوشه‌های بزرگ ممکن بود کمتر از دقت مجموع باشد و balancer متوقف شود.
:::

# قانون‌های MSR: چند OSD در هر failure domain {#sec-28-10}

در EC با k+m بزرگ‌تر از تعداد hostها (مثلاً 4+2 روی سه host)، قانون کلاسیک `choose indep 3 type host` و سپس `chooseleaf indep 2 type osd` یک مشکل دارد. اگر یک OSD out شود، مرحله‌ی دوم فقط در **همان** host دنبال جایگزین می‌گردد. اگر آن host OSD سالم دیگری نداشته باشد، shard بی‌جا می‌ماند، چون CRUSH کلاسیک نمی‌تواند به مرحله‌ی قبل برگردد. قانون‌های **MSR** (Multi-Step Retry) از Squid با نوع‌های `msr_firstn` و `msr_indep` و گام `choosemsr` این را حل می‌کنند: کل نزول از ریشه دوباره تلاش می‌شود.

![قانون MSR برای EC 4+2 روی سه host. خروجی شش‌خانه‌ای به سه stride دوتایی تقسیم می‌شود و hostهای هر stride از strideهای دیگر جدا نگه داشته می‌شوند. وقتی osd.7 out است، شاخص 3 در این دور خالی می‌ماند و در دور بعدی نزول با شماره‌ی تلاش تازه از ریشه تکرار می‌شود. جایگزین می‌تواند در همان host یا در hostی باشد که در stride دیگری استفاده نشده است](figures/ch28/f10_msr.png){#fig-28-f10_msr}

::: {.algo #alg-28-5 title="نزول چندمرحله‌ای با تلاش دوباره (MSR)" src="src/crush/mapper.c :: crush_msr_do_rule، crush_msr_choose، crush_msr_descend، crush_msr_get_retry_value" complexity="O(msr_descents × result_max × عمق × اندازه‌ی bucket) در بدترین حالت؛ پیش‌فرض msr_descents = msr_collision_tries = 100"}
:::

```text
pseudocode
total = Π(arg1 of choosemsr steps)      # مثلاً 3 × 2 = 6
for descent in 0 .. msr_descents-1 while خروجی کامل نیست:
    crush_msr_choose(root, [0, total), step0, tryno = descent)
crush_msr_choose(bucket, [start, end), step):
    num_strides = step.arg1 (یا result_max اگر 0)
    stride_length = (end − start) / num_strides
    for each stride:
        if همه‌ی شاخص‌های stride پر شده‌اند: continue
        for local_try in 0 .. msr_collision_tries-1:
            r = ((descent × result_max + index) << 16) + local_try
            cand = crush_msr_descend(bucket, step.type, r)          # straw2 و ... تا نوع هدف
            if cand در stride دیگری استفاده شده (collision): continue
            if آخرین گام: اگر OSD out است ⇒ شاخص خالی بماند (undo پس از دور)
            else: crush_msr_choose(cand, [stride], step+1) برای سطح بعد
```

**مثال عددی.** با `choosemsr 3 host` و `choosemsr 2 osd`، total_descendants = 6، num_strides = 3 و stride_length = 2. در فراخوانی بازگشتی برای هر host، total_descendants = 2 و stride_length = 1 است (این‌ها همان اعداد توضیح بالای `crush_msr_choose` در کد هستند). مقدار تلاش برای descent=1، result_max=6، index=3 و local_try=0 برابر ((1×6+3) ≪ 16) + 0 = 9 × 65536 = 589824 است. پس hashها در هر دور کاملاً متفاوت‌اند. تضمین گام `choosemsr 3 host` «دست‌کم» سه host است، نه «دقیقاً» سه: یک stride ممکن است پس از out شدن یک OSD از دو host استفاده کند، به شرط آنکه آن hostها در strideهای دیگر نباشند.

::: {.warn}
قانون‌های MSR به ویژگی `CRUSH_MSR` (بیت 38 در `ceph_features.h`) نیاز دارند و فقط کلاینت‌ها و OSDهایی که آن را می‌شناسند (Squid و بالاتر) می‌توانند نگاشت را حساب کنند. در زمان نگارش، `net/ceph/crush/mapper.c` در شاخه‌ی اصلی هسته‌ی لینوکس هیچ پیاده‌سازی MSR ندارد، پس krbd و ceph.ko نمی‌توانند از poolی با قانون MSR استفاده کنند. پیش از ساختن قانون MSR، `ceph features` را بررسی کنید.
:::

# تکمیلی و به‌روز {#sec-28-11}

- قواعد MSR (`CRUSH_RULE_CHOOSE_MSR` و انواع `CRUSH_RULE_TYPE_MSR_FIRSTN` و `MSR_INDEP`) در کد Squid و main وجود دارند و در Reef نیستند. هدف آن‌ها قرار دادن چند shard در یک failure domain با کنترل دقیق است (مثلاً EC 8+6 روی ۴ rack).
- هسته‌ی لینوکس همین `mapper.c`، `hash.c` و `crush_ln_table.h` را در `net/ceph/crush/` دارد. پشتیبانی آن از قابلیت‌های جدید CRUSH (مثل MSR) به نسخه‌ی هسته بستگی دارد و قابلیت‌های خوشه باید با `ceph osd set-require-min-compat-client` هماهنگ شود.

# تمرین عملی {#sec-28-12}

1. برنامه‌ی آزمایشی این فصل را بازسازی کنید: فایل‌های `hash.c` و `crush_ln_table.h` را از کد Ceph بردارید و `bucket_straw2_choose` را برای bucketی با پنج آیتم و وزن‌های دلخواه اجرا کنید. توزیع را برای یک میلیون x بسنجید.
2. با `ceph osd map` چند شیء را نگاشت کنید و ps را با محاسبه‌ی دستی `ceph_stable_mod` تطبیق دهید.
3. وزن یک host را در یک نقشه‌ی آزمایشی ۱۰٪ زیاد کنید و با `crushtool --compare` تعداد PGهای جابه‌جاشده و مقصد آن‌ها را ببینید (باید فقط به همان host منتقل شوند).
4. یک pg-upmap-items دستی بسازید که دو replica را در یک host قرار دهد و ببینید mon با آن چه می‌کند.

# پرسش‌های مرور {#sec-28-13}

1. ceph_stable_mod چگونه حرکت داده را هنگام افزایش pg_num محدود می‌کند؟
2. چرا HASHPSPOOL لازم است؟
3. چرا CRUSH فقط از عملیات صحیح استفاده می‌کند؟
4. در straw2، draw چگونه محاسبه می‌شود و چرا بیشترین draw برنده است؟
5. crush_ln چه چیزی را با چه دقتی برمی‌گرداند؟
6. چرا straw2 حرکت حداقلی دارد و straw قدیمی نداشت؟
7. تصادم در firstn چگونه حل می‌شود و سقف آن چیست؟
8. تفاوت firstn و indep برای EC چیست؟
9. weight-set در choose_args چه مشکلی را حل می‌کند؟
10. ترتیب اعمال upmapها چیست و mon با upmap نامعتبر چه می‌کند؟

# منابع این فصل {#sec-28-14}

- مقاله‌ی CRUSH (Weil و همکاران، SC 2006): https://ceph.io/assets/pdfs/weil-crush-sc06.pdf
- mapper.c: https://github.com/ceph/ceph/blob/main/src/crush/mapper.c
- hash.c: https://github.com/ceph/ceph/blob/main/src/crush/hash.c
- CRUSH maps: https://docs.ceph.com/en/latest/rados/operations/crush-map/
- ویرایش CRUSH map: https://docs.ceph.com/en/latest/rados/operations/crush-map-edits/
- upmap: https://docs.ceph.com/en/latest/rados/operations/upmap/
- balancer: https://docs.ceph.com/en/latest/rados/operations/balancer/
- crushtool: https://docs.ceph.com/en/latest/man/8/crushtool/
- تابع hash مربوط به Bob Jenkins: https://burtleburtle.net/bob/hash/doobs.html
