---
chapter: 27
id: ch27
title: "لایه‌های پایینی (۵): ریاضیات erasure coding، از GF(2⁸) تا FastEC"
part: lower
lang: fa
---

# مقدمه: از XOR تا Reed-Solomon {#sec-27-1}

در فصل ۱۳ دیدیم یک pool با erasure coding چگونه ساخته می‌شود و پروفایل‌ها چه معنایی دارند. این فصل یک لایه پایین‌تر می‌رود: ریاضیات میدان متناهی $\mathrm{GF}(2^8)$، ساخت ماتریس تولید Reed-Solomon (به روش Vandermonde و Cauchy)، پیاده‌سازی SIMD در ISA-L، و این‌که Ceph چگونه شیء را به stripe و chunk تقسیم می‌کند، نوشتن جزئی را با read-modify-write انجام می‌دهد و در Tentacle با EC بهینه‌شده (که معمولاً FastEC نامیده می‌شود) چه چیزی تغییر کرده است. یک مثال عددی کامل encode و decode هم با دست حل می‌کنیم.

::: {.summary}

- همه‌ی پلاگین‌های اصلی (isa، jerasure و پایه‌ی clay) در $\mathrm{GF}(2^8)$ کار می‌کنند. در این میدان جمع برابر XOR است و ضرب با جدول log/exp یا SIMD انجام می‌شود.
- پروفایل پیش‌فرض در Tentacle و main `plugin=isa technique=reed_sol_van k=2 m=2` است. در Squid پیش‌فرض `plugin=jerasure` بود.
- در ISA-L، Vandermonde فقط برای m ≤ 4 (و برای m=4 تنها با k ≤ 21) MDS تضمین‌شده است. در غیر این صورت Ceph خودکار به `cauchy` تغییر می‌دهد.
- `stripe_unit` پیش‌فرض 4K است و برای poolهای با `allow_ec_optimizations` برابر 16K می‌شود.
- EC بهینه در Tentacle (`ECSwitch` بین backend قدیمی و جدید) خواندن جزئی مستقیم و به‌روزرسانی parity با delta را ممکن می‌کند. پس از فعال شدن، غیرفعال‌کردنی نیست.

:::

# GF(2⁸): حساب بایت‌ها {#sec-27-2}

erasure coding باید روی بایت‌ها «ضرب و تقسیم» کند، به‌طوری که هر عدد غیرصفر معکوس داشته باشد و نتیجه همیشه یک بایت بماند. میدان گالوا $\mathrm{GF}(2^8)$ دقیقاً همین را فراهم می‌کند. عناصر آن ۲۵۶ بایت‌اند که به‌صورت چندجمله‌ای‌هایی از درجه‌ی کمتر از ۸ با ضرایب ۰ و ۱ دیده می‌شوند.

- **جمع و تفریق:** هر دو XOR هستند، پس a + a = 0.
- **ضرب:** ضرب چندجمله‌ای‌ها و سپس باقیمانده بر یک چندجمله‌ای تحویل‌ناپذیر درجه ۸ گرفته می‌شود. ISA-L از 0x11D (x⁸ + x⁴ + x³ + x² + 1) استفاده می‌کند: در هر شیفت به چپ، اگر بیت ۸ روشن شد، با 0x1D XOR می‌شود (در `ec_base.c` همین الگو برای ضرب در ۲ دیده می‌شود).
- **جدول log/exp:** چون عدد ۲ مولد گروه ضربی است، هر بایت غیرصفر برابر $2^i$ است. پس $a \cdot b = \exp[(\log a + \log b) \bmod 255]$ و $a^{-1} = \exp[255 - \log a]$.

| ضرب نمونه در $\mathrm{GF}(2^8)$ با 0x11D | نتیجه | شرح |
|---|---|---|
| 0x02 × 0x04 | 0x08 | بدون سرریز؛ فقط شیفت |
| 0x34 × 0x02 | 0x68 | 0x34 << 1 = 0x68 |
| 0x56 × 0x04 | 0x45 | 0x56 << 2 = 0x158 → بیت ۸ روشن → 0x58 ⊕ 0x1D = 0x45 |
| 0x78 × 0x08 | 0xE7 | سه شیفت با دو سرریز |

![سه لایه‌ی محاسبه. در بالا، حساب GF(2⁸): جمع برابر XOR است و ضرب با شیفت و XOR با 0x1D هنگام سرریز، یا با جدول log/exp انجام می‌شود. در وسط، ماتریس تولید سیستماتیک ISA-L برای k=4 و m=2 به روش Vandermonde: چهار سطر اول همانی‌اند (داده دست‌نخورده می‌ماند)، سطر P0 همه ۱ است (همان XOR ساده) و سطر P1 توان‌های ۲ است. در پایین، پیاده‌سازی SIMD: ec_init_tables برای هر ضریب دو جدول ۱۶ خانه‌ای (nibble پایین و بالا) می‌سازد و دستور PSHUFB با این جدول‌ها ۳۲ یا ۶۴ بایت را در یک دستور ضرب می‌کند](figures/ch27/f02_gf.png){#fig-27-f02_gf}

# Reed-Solomon سیستماتیک {#sec-27-3}

در یک کد سیستماتیک (k، m)، k chunk داده بدون تغییر ذخیره و m chunk parity از آن‌ها محاسبه می‌شود. اگر D بردار داده باشد، chunkها از ضرب ماتریس تولید G با اندازه‌ی (k+m)×k در D به دست می‌آیند: C = G · D. چهار سطر اول G همانی‌اند. کد **MDS** است، یعنی هر k chunk از k+m chunk برای بازسازی کافی است، به شرط این‌که هر زیرماتریس k×k از G معکوس‌پذیر باشد.

`gf_gen_rs_matrix` در ISA-L سطر i ام parity را با توان‌های $\mathit{gen} = 2^{i-k}$ می‌سازد. این یک ماتریس «Vandermonde» ساده است که برای همه‌ی (k، m)ها MDS نیست. به همین دلیل `ErasureCodeIsa.cc` اگر m > 4 باشد یا m = 4 و k > 21، با پیامی در لاگ به `gf_gen_cauchy1_matrix` تغییر می‌دهد که درایه‌هایش 1/(i ⊕ j) هستند و همیشه MDS‌اند. سقف k هم `MAX_K = 32` است.

| ماتریس parity برای k=4، m=2 | سطر P0 | سطر P1 |
|---|---|---|
| ISA-L reed_sol_van | 1 1 1 1 | 1 2 4 8 |
| ISA-L cauchy | 0x47 0xA7 0x7A 0xBA | 0xA7 0x47 0xBA 0x7A |

## مثال کامل: encode یک stripe کوچک {#sec-27-3-1}

فرض کنید هر chunk فقط یک بایت دارد و داده D = (0x12, 0x34, 0x56, 0x78) است (در واقع همین محاسبه برای هر بایت از chunkهای ۴K تکرار می‌شود):

```text
P0 = 1·12 ⊕ 1·34 ⊕ 1·56 ⊕ 1·78 = 12 ⊕ 34 ⊕ 56 ⊕ 78           = 0x08
P1 = 1·12 ⊕ 2·34 ⊕ 4·56 ⊕ 8·78 = 12 ⊕ 68 ⊕ 45 ⊕ E7           = 0xD8
chunks = [12, 34, 56, 78 | 08, D8]   (shard 0..5)
```

## decode: از دست رفتن دو shard {#sec-27-3-2}

فرض کنید OSDهای حاوی D1 و D3 از دست رفته‌اند و shardهای سالم {D0، D2، P0، P1} هستند. سطرهای متناظر از G یک ماتریس ۴×۴ می‌سازند. معکوس آن در $\mathrm{GF}(2^8)$ حساب می‌شود (ISA-L از `gf_invert_matrix` استفاده می‌کند) و سطرهای مربوط به داده‌های گم‌شده با بایت‌های سالم ضرب می‌شوند:

```text
D1 = 7B·D0 ⊕ F5·D2 ⊕ A6·P0 ⊕ DD·P1 = 0x34   ✓
D3 = 7A·D0 ⊕ F4·D2 ⊕ A7·P0 ⊕ DD·P1 = 0x78   ✓
```

همه‌ی اعداد این دو بخش با یک پیاده‌سازی پایتونی مستقل از $\mathrm{GF}(2^8)$ با 0x11D و همان الگوریتم ساخت ماتریس ISA-L محاسبه و بررسی شده‌اند. ضرایب decode فقط یک بار برای هر الگوی خرابی حساب می‌شوند و پلاگین isa آن‌ها را در `ErasureCodeIsaTableCache` نگه می‌دارد، چون معکوس کردن ماتریس از encode گران‌تر است.

::: {.deep}
**چرا SIMD این‌قدر سریع است؟** ضرب یک بایت x در ثابت c را می‌توان به دو nibble شکست: c·x = c·(x_hi << 4) ⊕ c·x_lo. هر کدام فقط ۱۶ حالت دارد، پس دو جدول ۱۶ بایتی کافی است. دستور `PSHUFB` (یا `VPSHUFB` در AVX2/AVX-512) می‌تواند ۱۶، ۳۲ یا ۶۴ جست‌وجوی هم‌زمان در یک جدول ۱۶ بایتی انجام دهد. ISA-L این جدول‌ها را با `ec_init_tables` برای همه‌ی ضرایب می‌سازد و `ec_encode_data` برای هر بلوک ورودی، ضرب و XOR انباشتی را با این دستورها اجرا می‌کند. نتیجه، سرعت encode در حد چند گیگابایت در ثانیه در هر هسته است. jerasure (با gf-complete) از روش مشابهی استفاده می‌کند، ولی ISA-L روی x86 معمولاً سریع‌تر است. پلاگین isa روی Arm هم با کدهای NEON و SVE مربوط به ISA-L کار می‌کند.
:::

# stripe، chunk و چیدمان روی OSD {#sec-27-4}

![تقسیم یک شیء ۶۴K در pool با k=4، m=2 و stripe_unit=4K. stripe_width برابر 16K است، پس شیء چهار stripe دارد. در هر stripe، چهار ناحیه‌ی ۴K پشت‌سرهم به shardهای داده ۰ تا ۳ می‌روند و دو parity محاسبه و در shardهای ۴ و ۵ نوشته می‌شوند. هر OSD یک «شیء shard» با shard_id خودش و اندازه‌ی ۱۶K نگه می‌دارد](figures/ch27/f01_stripe.png){#fig-27-f01_stripe}

| مفهوم | تعریف | پیش‌فرض |
|---|---|---|
| `stripe_unit` (chunk size) | بایت‌های داده‌ی یک shard در یک stripe | 0 در `osd_pool_erasure_code_stripe_unit` یعنی 4K، یا 16K اگر pool بهینه باشد و پلاگین پشتیبانی کند |
| `stripe_width` | k × stripe_unit | برای k=4: 16K یا 64K |
| شیء shard | `ghobject_t` با `shard_id` برابر 0..k+m−1 | روی OSD با کلید onode دارای shard + 0x80 (فصل ۲۴) |

::: {.note}
`ceph osd pool create` اگر `stripe_unit` مضرب 4K نباشد، بدون `--yes-i-really-mean-it` پروفایل را رد می‌کند. انتخاب stripe_unit بزرگ‌تر یعنی نوشتن‌های کوچک‌تر از یک stripe بیشتر، ولی خواندن ترتیبی کارآمدتر. با EC بهینه این بده‌بستان به سمت 16K رفته است، چون نوشتن جزئی دیگر کل stripe را نمی‌خواند.
:::

# read-modify-write در EC قدیمی {#sec-27-5}

تا Squid، و در poolهای بدون بهینه‌سازی در نسخه‌های بعدی، backend مربوط به EC برای هر نوشتنی که کل stripe را نپوشاند و روی داده‌ی موجود باشد (`allow_ec_overwrites=true`، لازم برای RBD و CephFS) این کارها را انجام می‌دهد:

```text
pseudocode: overwrite جزئی در ECBackend قدیمی (خلاصه‌ی این کتاب)
  extent = round_out(write, stripe_width)              # گسترش به مرز stripe
  if cache miss: read k chunks of extent from shards   # چند رفت‌وبرگشت شبکه
  merge new bytes into stripe buffer
  encode → m parity chunks for whole stripe
  send sub-writes to all k+m shards (هر shard، تراکنش خودش)
  wait all commits → reply
```

![نوشتن جزئی ۴K در مقایسه‌ی دو backend. در EC قدیمی، primary کل stripe را از k shard می‌خواند، داده‌ی جدید را ادغام، دوباره encode و همه‌ی shardها را بازنویسی می‌کند. در EC بهینه (Tentacle با allow_ec_optimizations)، فقط همان ۴K قدیمی و parityها خوانده می‌شوند، delta برابر قدیم ⊕ جدید محاسبه و هر parity با ضریب مربوط در delta به‌روز می‌شود. خواندن کوچک هم به‌جای decode از k shard، مستقیم از یک shard داده انجام می‌شود](figures/ch27/f03_rmw.png){#fig-27-f03_rmw}

**چرا parity delta درست است؟** چون کد خطی است: $P_i = \sum_j g_{ij} \cdot D_j$. اگر فقط $D_j$ به $D_j'$ تغییر کند، $P_i' = P_i \oplus g_{ij} \cdot (D_j \oplus D_j')$. با مثال بخش قبل، اگر D1 از 0x34 به 0x35 تغییر کند، delta برابر 0x01 است، پس P0′ = 0x08 ⊕ 1·0x01 = 0x09 و P1′ = 0xD8 ⊕ 2·0x01 = 0xDA. نیازی به خواندن D0، D2 و D3 نیست.

| پرچم پلاگین (`ErasureCodeInterface.h`) | معنی |
|---|---|
| `FLAG_EC_PLUGIN_PARTIAL_READ_OPTIMIZATION` | کد سیستماتیک است؛ خواندن کوچک مستقیم از shard داده |
| `FLAG_EC_PLUGIN_PARTIAL_WRITE_OPTIMIZATION` | نوشتن کوچک‌تر از یک chunk فقط همان قطعه را از هر shard داده لازم دارد |
| `FLAG_EC_PLUGIN_ZERO_INPUT_ZERO_OUTPUT_OPTIMIZATION` | داده‌ی تماماً صفر parity صفر می‌دهد (برای ناحیه‌های خالی) |
| `FLAG_EC_PLUGIN_ZERO_PADDING_OPTIMIZATION` | بافرهای با طول صفر مجازند |
| `FLAG_EC_PLUGIN_PARITY_DELTA_OPTIMIZATION` | به‌روزرسانی parity با delta |
| `FLAG_EC_PLUGIN_REQUIRE_SUB_CHUNKS` | پلاگین sub-chunk لازم دارد (CLAY) |
| `FLAG_EC_PLUGIN_OPTIMIZED_SUPPORTED` | می‌تواند در pool بهینه استفاده شود: isa، و jerasure فقط با `reed_sol_van` |

```bash {since=tentacle}
# Tentacle و بالاتر:
ceph osd erasure-code-profile set ec42 plugin=isa technique=reed_sol_van k=4 m=2 crush-failure-domain=host
ceph osd pool create ecdata erasure ec42
ceph osd pool set ecdata allow_ec_overwrites true
ceph osd pool set ecdata allow_ec_optimizations true     # برگشت‌ناپذیر
ceph osd pool get ecdata all | grep -E 'ec_optim|stripe'
```

::: {.warn}
`FLAG_EC_OPTIMIZATIONS` در `osd_types.h` با این توضیح تعریف شده است: «once enabled, cannot be disabled». پیش از فعال کردن آن روی pool تولیدی، مطمئن شوید همه‌ی OSDها به نسخه‌ای ارتقا یافته‌اند که آن را پشتیبانی می‌کند. آن را ابتدا روی یک pool آزمایشی امتحان کنید. `osd_pool_default_flag_ec_optimizations` (پیش‌فرض false) فعال شدن خودکار آن را برای poolهای جدید کنترل می‌کند.
:::

# کدهای با پهنای باند ترمیم کمتر {#sec-27-6}

در RS، بازسازی یک shard گم‌شده به خواندن k chunk کامل نیاز دارد. برای k=8، این یعنی ۸ برابر داده‌ی از دست رفته از شبکه می‌گذرد. سه پلاگین Ceph این هزینه را به روش‌های متفاوت کم می‌کنند:

![ترافیک بازسازی یک shard به اندازه‌ی S. RS با k=4 به 4S نیاز دارد. LRC با l=3 فقط از گروه محلی (۳ chunk) می‌خواند. CLAY با d=5 از ۵ helper، هرکدام کسر 1/(d−k+1) = 1/2 از chunk را می‌خواند، یعنی 2.5S. SHEC parityها را روی زیرمجموعه‌های هم‌پوشان داده می‌سازد تا خرابی تکی با خواندن کمتر از k ترمیم شود](figures/ch27/f04_repair.png){#fig-27-f04_repair}

| پلاگین | پارامترها (پیش‌فرض) | ایده | بده‌بستان |
|---|---|---|---|
| `lrc` | k، m، l | افزودن parity محلی برای هر l chunk؛ معمولاً هر گروه در یک rack | سربار فضای بیشتر: (k+m)/k + (k+m)/(l·k) |
| `clay` | k=4، m=2، d=k+m−1 (پیش‌فرض) | کد coupled-layer با sub-chunk: ترمیم با خواندن کسری از d helper | ترمیم کمینه (MSR)؛ تعداد sub-chunk برابر $q^t$ است که با k+m به‌سرعت بزرگ می‌شود و خواندن‌ها ریز می‌شوند |
| `shec` | k=4، m=3، c=2 | هر parity فقط بخشی از داده را می‌پوشاند؛ c = تعداد خرابی تحمل‌پذیر تضمینی | کارایی فضا بین RS و replication؛ ترمیم تکی ارزان‌تر |

**مثال عددی CLAY:** پهنای باند ترمیم برای یک shard به اندازه‌ی S برابر $d \cdot S / (d - k + 1)$ است. با k=8، m=4 و d=11، این مقدار 11S/4 = 2.75S است، در حالی که RS معادل ۸S می‌خواند (حدود ۶۶٪ صرفه‌جویی). ولی q = d − k + 1 = 4 و t = (k+m)/q = 3، پس هر chunk به $4^3 = 64$ sub-chunk تقسیم می‌شود. با stripe_unit برابر 4K، sub-chunkها ۶۴ بایتی می‌شوند و خواندن ترمیمی به ده‌ها خواندن کوچک و پراکنده تبدیل می‌شود. برای همین CLAY با stripe_unit بزرگ‌تر معنا پیدا می‌کند.

# crc و یکپارچگی در EC {#sec-27-7}

در EC قدیمی، برای poolهای append-only (بدون overwrite)، hash هر shard (`hinfo_key` در xattr) نگه داشته می‌شد و scrub عمیق آن را بررسی می‌کرد. با `allow_ec_overwrites`، این hash دیگر به‌روز نمی‌شود و یکپارچگی بر checksumهای BlueStore در هر shard (فصل ۲۳) تکیه دارد. scrub عمیق در EC هر shard را می‌خواند و سازگاری parity را با encode دوباره بررسی می‌کند. پرچم `FLAG_EC_PLUGIN_CRC_ENCODE_DECODE_SUPPORT` در main نشان می‌دهد پلاگین می‌تواند crc را از روی crc داده‌ها محاسبه کند، یعنی خاصیت خطی بودن crc را با کد ترکیب کند. این بخشی از کارهای در جریان روی scrub سریع‌تر است. پیش از تکیه بر آن، نسخه‌ی خود را بررسی کنید.

```bash
ceph osd erasure-code-profile get default
ceph osd pool ls detail | grep -E 'erasure|stripe_width'
ceph pg <pgid> query | jq '.info.stats.stat_sum.num_objects_degraded'
ceph tell osd.4 config get osd_recovery_max_active_hdd
```

# حساب GF(2⁸) در سطح دستور: جدول‌های log/exp و ترفند نیم‌بایت {#sec-27-8}

بخش‌های پیشین ضرب در $\mathrm{GF}(2^8)$ را تعریف کردند. این بخش نشان می‌دهد ISA-L، که پلاگین `isa` در Ceph بر آن تکیه دارد، این ضرب را در حلقه‌ی داغ چگونه انجام می‌دهد. چندجمله‌ی کاهش در ISA-L همان 0x11D (یعنی $x^8+x^4+x^3+x^2+1$) است. در کد این عدد به شکل `0x1d` دیده می‌شود: هر بار که بیت ۷ پیش از شیفت روشن باشد، حاصل با 0x1d XOR می‌شود.

::: {.algo #alg-27-1 title="ضرب با جدول log/exp" src="isa-l/erasure_code/ec_base.c :: gf_mul، gf_inv" complexity="O(1): دو جست‌وجو، یک جمع و یک مقایسه؛ جدول‌ها 256 + 256 بایت"}
:::

```text
pseudocode
# ساخت یک‌باره: exp[i] = 2^i و log[2^i] = i برای i در 0..254
x = 1
for i in 0..254: exp[i] = x; log[x] = i; x = x·2 (یعنی x≪1 و اگر سرریز شد ⊕ 0x11D)
gf_mul(a, b): if a == 0 or b == 0: return 0
              i = log[a] + log[b]; if i > 254: i −= 255
              return exp[i]
gf_inv(a):   return exp[255 − log[a]]
```

**مثال عددی.** exp[0..15] = 01 02 04 08 10 20 40 80 1D 3A 74 E8 CD 87 13 26. پس $2^8 = \mathtt{0x1D}$ است، یعنی همان سرریز اول. برای 0x53 × 0xCA داریم log[0x53] = 206 و log[0xCA] = 73. جمع آن‌ها 279 است و چون از 254 بزرگ‌تر است، 279 − 255 = 24 و exp[24] = 0x8F. وارون 0x02 برابر exp[255 − 1] = 0x8E است. آزمون: 0x8E × 2 = 0x11C و 0x11C ⊕ 0x11D = 0x01.

این روش برای هر بایت دو دسترسی تصادفی به جدول و یک شاخه دارد و در حلقه‌ی داغ کند است. برای همین ISA-L جدول دیگری می‌سازد که با دستورهای SIMD سازگار است.

![جدول ۳۲ بایتی که gf_vect_mul_init_base برای ضریب c=0x02 می‌سازد. ۱۶ خانه‌ی اول حاصل‌ضرب c در نیم‌بایت پایین (0 تا F) هستند و ۱۶ خانه‌ی دوم حاصل‌ضرب c در نیم‌بایت بالا (0x00 تا 0xF0). ضرب هر بایت با دو جست‌وجو و یک XOR انجام می‌شود، چون ضرب در GF(2⁸) نسبت به XOR خطی است: c·(hi ⊕ lo) = c·hi ⊕ c·lo. خانه‌های زرد همان دو خانه‌ای‌اند که برای بایت 0xB7 خوانده می‌شوند](figures/ch27/f05_gftbl.png){#fig-27-f05_gftbl}

دلیل درستی ترفند این است که هر بایت d برابر (d AND 0xF0) ⊕ (d AND 0x0F) است و ضرب در c روی ⊕ پخش می‌شود. پس به جای جدول 256 خانه‌ای برای هر c، دو جدول ۱۶ خانه‌ای کافی است. ۱۶ خانه دقیقاً اندازه‌ی یک ثبات XMM است و دستور PSHUFB با همین اندازه کار می‌کند: هر بایت از ثبات دوم را شاخصی در ثبات اول می‌گیرد.

::: {.algo #alg-27-2 title="ضرب برداری با جدول نیم‌بایت (split-table)" src="isa-l/erasure_code/ec_base.c :: gf_vect_mul_init_base، ec_init_tables_base و نسخه‌های اسمبلی gf_*vect_dot_prod_avx2.asm" complexity="ساخت جدول O(32) برای هر ضریب، یعنی 32·k·m بایت برای کل ماتریس. کدگذاری O(k·m·L/W) دستور برای L بایت با پهنای ثبات W (16/32/64)"}
:::

```text
pseudocode
init(c): for n in 0..15: tbl[n] = c·n ; tbl[16+n] = c·(n≪4)
encode_row(row r, data D0..Dk-1, length L):
    for off in 0, W, 2W, … < L:                 # W = 32 در AVX2
        acc = 0
        for j in 0..k-1:
            v  = load(Dj + off)
            lo = v AND 0x0F ; hi = (v ≫ 4) AND 0x0F
            acc ^= PSHUFB(tbl[r][j].lo, lo) ^ PSHUFB(tbl[r][j].hi, hi)
        store(P_r + off, acc)
```

**مثال عددی.** برای d = 0xB7 و c = 2: نیم‌بایت پایین 7 به tbl[7] = 0x0E می‌رسد و نیم‌بایت بالا B به tbl[27] = 0x7D. 0x0E ⊕ 0x7D = 0x73، که با 2·0xB7 مستقیم (0x16E ⊕ 0x11D = 0x73) یکی است. برای k=4، m=2، یعنی شش ضریب، ec_init_tables 6 × 32 = 192 بایت جدول می‌سازد. Ceph در `ErasureCodeIsaDefault::prepare` آرایه‌ای به اندازه‌ی k·(m+k)·32 بایت می‌گیرد و جدول‌ها را در `ErasureCodeIsaTableCache` نگه می‌دارد تا برای هر (k, m) فقط یک‌بار ساخته شوند. جدول‌های decode هم در یک LRU به طول `decoding_tables_lru_length` نگه داشته می‌شوند، چون برای هر الگوی خرابی ماتریس متفاوتی لازم است.

![مسیر ضرب ۳۲ بایت داده در ثابت c=2 با AVX2. داده به دو نیم‌بایت شکسته می‌شود. هر نیم‌بایت با VPSHUFB از جدول ۱۶ خانه‌ای مربوطش جست‌وجو می‌شود و دو نتیجه XOR می‌شوند. ردیف پایین نشان می‌دهد این ضرب برای هر ستون داده تکرار می‌شود و در parity انباشته می‌شود. نسخه‌های gf_Nvect_dot_prod چند parity را در یک گذر روی داده می‌سازند تا داده فقط یک‌بار از حافظه خوانده شود](figures/ch27/f07_pshufb.png){#fig-27-f07_pshufb}

::: {.deep}
در پردازنده‌هایی که GFNI دارند، ISA-L نسخه‌های `*_gfni.asm` را انتخاب می‌کند. دستور `GF2P8AFFINEQB` ضرب در یک ثابت $\mathrm{GF}(2^8)$ را به شکل یک تبدیل affine روی هر بایت انجام می‌دهد و جدول نیم‌بایت را حذف می‌کند. انتخاب نسخه در زمان اجرا با dispatcher چندنسخه‌ای (`ec_multibinary.asm`) و بر اساس CPUID انجام می‌شود، نه در زمان کامپایل Ceph.
:::

# ماتریس‌های تولید: Vandermonde در برابر Cauchy {#sec-27-9}

پلاگین isa دو ماتریس می‌شناسد: `technique=reed_sol_van` (پیش‌فرض) که `gf_gen_rs_matrix` را صدا می‌زند و `technique=cauchy` که `gf_gen_cauchy1_matrix` را. هر دو ماتریس (k+m)×k با یک ماتریس همانی k×k در بالا می‌سازند، پس کد سیستماتیک است.

::: {.algo #alg-27-3 title="تولید ماتریس کدگذاری ISA-L" src="isa-l/erasure_code/ec_base.c :: gf_gen_rs_matrix، gf_gen_cauchy1_matrix؛ src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::parse، prepare" complexity="O(k·m) ضرب GF برای هر دو"}
:::

```text
pseudocode
gf_gen_rs_matrix(a, rows=k+m, k):
    a = 0 ; for i < k: a[i][i] = 1
    gen = 1
    for i in k .. rows-1:
        p = 1
        for j < k: a[i][j] = p ; p = p·gen      # سطر i: توان‌های gen
        gen = gen·2
gf_gen_cauchy1_matrix(a, rows, k):
    همانی در بالا ; for i in k..rows-1, j < k: a[i][j] = gf_inv(i ⊕ j)
```

**مثال عددی (k=4، m=2).** Vandermonde: سطر P برابر [1 1 1 1] است (gen = 1) و سطر Q برابر [1 2 4 8] (gen = 2). پس P همان XOR ساده است. Cauchy: سطر 4 برابر [inv(4) inv(5) inv(6) inv(7)] = [47 A7 7A BA] و سطر 5 برابر [inv(5) inv(4) inv(7) inv(6)] = [A7 47 BA 7A]. برای داده‌ی D = [37 5C A1 0F]، با Vandermonde P = 0xC5 و Q = 0x49، و با Cauchy P = 0xD1 و Q = 0x09.

![دو ماتریس کدگذاری ISA-L برای k=4، m=2 و برچسب parity حاصل برای بایت نمونه‌ی D = \[0x37، 0x5C، 0xA1، 0x0F\]. چهار سطر بالا همانی‌اند و داده را بی‌تغییر به shardهای 0 تا 3 می‌برند. دو سطر پایین ضرایب parity هستند. در Vandermonde، سطر P تماماً 1 است، پس P همان XOR است و مسیر سریع xor_gen برای m=1 به‌کار می‌رود. در Cauchy همه‌ی ضرایب parity غیر بدیهی‌اند](figures/ch27/f06_matrices.png){#fig-27-f06_matrices}

**چرا Ceph محدودیت می‌گذارد.** ماتریس `gf_gen_rs_matrix` یک Vandermonde «واقعی» نیست: سطرهای همانی روی آن گذاشته شده‌اند و MDS بودنش برای همه‌ی (k, m) تضمین نمی‌شود. خود ISA-L ابزار `gen_rs_matrix_limits.c` را برای یافتن حدها دارد. Ceph در `ErasureCodeIsaDefault::parse` این حدها را اعمال می‌کند: k ≤ 32 و m ≤ 32 (MAX_K و MAX_M). برای Vandermonde اگر m > 4 باشد، یا m = 4 و k > 21، پیام هشدار می‌دهد و technique را خودکار به `cauchy` تغییر می‌دهد. یعنی پروفایل ذخیره‌شده عوض می‌شود. با شبیه‌سازی جداگانه (حذف همه‌ی ترکیب‌های m سطری و آزمون وارون‌پذیری k×k باقی‌مانده) برای 4+2، 6+3، 8+3، 8+4، 10+4 و 12+4 هیچ زیرماتریس منفردی پیدا نشد (مثلاً 1001 ترکیب برای 10+4)، که با این حدها سازگار است.

# decode با وارون ماتریس: یک مثال کامل بایت‌به‌بایت {#sec-27-10}

::: {.algo #alg-27-4 title="decode با حذف گاوس-جردن در GF(2⁸)" src="isa-l/erasure_code/ec_base.c :: gf_invert_matrix؛ src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::isa_decode" complexity="وارون O(k³) ضرب GF برای هر الگوی خرابی (کش در LRU)، سپس O(k·e·L) برای e shard گم‌شده"}
:::

```text
pseudocode
B = سطرهای ماتریس تولید برای k shard سالم انتخاب‌شده
Binv = gf_invert_matrix(B)            # گاوس-جردن: محور، ضرب سطر در gf_inv، حذف با ⊕
for each lost data shard i: c_i = سطر i از Binv
for each lost parity shard p: c_p = (سطر p از ماتریس تولید) × Binv
ec_init_tables(k, e, c, decode_tbls) ; ec_encode_data(L, k, e, decode_tbls, survivors, outputs)
```

**مثال عددی.** داده‌ی [37 5C A1 0F] و parityهای Vandermonde P = C5 و Q = 49 را داریم. D1 و D3 گم شده‌اند و D0، D2، P و Q باقی مانده‌اند. ابتدا سهم داده‌های معلوم را کم می‌کنیم:

- P' = P ⊕ D0 ⊕ D2 = C5 ⊕ 37 ⊕ A1 = 0x53، که برابر D1 ⊕ D3 است.
- Q' = Q ⊕ D0 ⊕ 4·D2 = 49 ⊕ 37 ⊕ BE = 0xC0، که برابر 2·D1 ⊕ 8·D3 است.

با حذف D1: Q' ⊕ 2·P' = (8 ⊕ 2)·D3 = 0x0A·D3. داریم 2·P' = 0xA6 و Q' ⊕ 0xA6 = 0x66. پس D3 = 0x66 · inv(0x0A) = 0x66 · 0xDD = 0x0F و D1 = P' ⊕ D3 = 0x5C. ماتریس وارونی که gf_invert_matrix برای سطرهای {0, 2, P, Q} می‌سازد، برای D3 سطر [7A F4 A7 DD] و برای D1 سطر [7B F5 A6 DD] دارد. ضرب آن‌ها در [37 A1 C5 49] همین دو عدد را می‌دهد.

# به‌روزرسانی parity با دلتا (Tentacle) {#sec-27-11}

در EC قدیمی، نوشتن جزئی کل stripe را می‌خواند (بخش read-modify-write). مسیر EC بهینه در Tentacle، برای پلاگین‌هایی که پرچم `FLAG_EC_PLUGIN_PARITY_DELTA_OPTIMIZATION` را اعلام می‌کنند، از خطی بودن کد استفاده می‌کند. تغییر یک shard داده فقط parityها را به اندازه‌ی ضریبِ همان ستون ضرب در دلتا تغییر می‌دهد.

::: {.algo #alg-27-5 title="به‌روزرسانی parity با دلتا" src="src/erasure-code/isa/ErasureCodeIsa.cc :: ErasureCodeIsaDefault::encode_delta، apply_delta؛ isa-l :: ec_encode_data_update" complexity="O(m·L) به جای O(k·m·L)؛ خواندن 1 + m بازه به جای k بازه"}
:::

```text
pseudocode
encode_delta(old, new):  Δ = old ⊕ new                    # isa_xor با دو بردار
apply_delta(in = {i: Δ_i, p: P_p}, out):
    for each data shard i با دلتا:
        for each parity p:
            if m == 1:  P_p ^= Δ_i                          # ستون همه 1
            else: ec_encode_data_update(L, k, 1, i, tbls + 32·k·(p−k), Δ_i, &P_p)
                  # P_p ^= a[p][i]·Δ_i
```

**مثال عددی.** D1 از 0x5C به 0xA5 تغییر می‌کند، پس Δ = 0x5C ⊕ 0xA5 = 0xF9. در Vandermonde ضرایب ستون 1 برای P و Q برابر 1 و 2 هستند: P_new = C5 ⊕ F9 = 0x3C و Q_new = 49 ⊕ 2·F9 = 49 ⊕ EF = 0xA6. محاسبه‌ی کامل از صفر با داده‌ی جدید هم دقیقاً 3C و A6 می‌دهد. در Cauchy ضرایب ستون 1 برابر A7 و 47 هستند و نتیجه 0x17 و 0x70 می‌شود، که آن هم با محاسبه‌ی کامل یکی است. برای نوشتن 4K در 8+3، مسیر قدیمی 8 خواندن 4K (یا کل stripe) لازم داشت، اما مسیر دلتا 1 + 3 = 4 خواندن و 4 نوشتن دارد.

![نوشتن 4K درون shard D1 در pool با k=4، m=2 و مسیر parity delta. primary فقط همان بازه را از D1 و دو parity می‌خواند. Δ را با encode_delta حساب می‌کند و با apply_delta ضریب ستون 1 ضرب در Δ را به هر parity XOR می‌کند. سپس سه نوشتن را در یک تراکنش توزیع‌شده می‌فرستد. shardهای D0، D2 و D3 درگیر نمی‌شوند](figures/ch27/f08_delta.png){#fig-27-f08_delta}

::: {.warn}
دلتا فقط وقتی درست است که مقدار قدیمی خوانده‌شده دقیقاً همان مقداری باشد که parity فعلی با آن ساخته شده است. اگر shard ناسازگار باشد (مثلاً پس از خطای نیمه‌کاره)، دلتا خطا را منتشر می‌کند. به همین دلیل scrub عمیق در poolهای EC (فصل ۳۲) و crc هر shard (بخش crc در همین فصل) اهمیت بیشتری پیدا می‌کنند.
:::

# LRC: از k، m و l تا رشته‌ی لایه‌ها {#sec-27-12}

::: {.algo #alg-27-6 title="تولید mapping و layers در LRC" src="src/erasure-code/lrc/ErasureCodeLrc.cc :: ErasureCodeLrc::parse_kml" complexity="O(k+m) برای ساخت رشته‌ها؛ ترمیم محلی l خواندن به جای k"}
:::

```text
pseudocode
require (k+m) % l == 0 ; g = (k+m)/l ; require k % g == 0 and m % g == 0
mapping = repeat g: 'D'×(k/g) + '_'×(m/g) + '_'
global  = repeat g: 'D'×(k/g) + 'c'×(m/g) + '_'
local_i = for j < g: (i==j) ? 'D'×l + 'c' : '_'×(l+1)
if crush-locality: steps = [choose g type locality, chooseleaf (l+1) type failure-domain]
```

**مثال عددی.** با k=4، m=2 و l=3: g = 6/3 = 2 و هر گروه 2 داده، 1 parity سراسری و 1 parity محلی دارد. کل chunkها 4 + 2 + 2 = 8 است. نتیجه: mapping = `DD__DD__`، لایه‌ی سراسری `DDc_DDc_` و لایه‌های محلی `DDDc____` و `____DDDc`. سربار فضا 8/4 = 2 برابر است (در برابر 1.5 برای 4+2 ساده). در مقابل، ترمیم یک chunk به جای 4 خواندن فقط 3 خواندن از همان گروه لازم دارد.

![اینکه parse_kml سه پارامتر k=4، m=2 و l=3 را چگونه به رشته‌های mapping و layers تبدیل می‌کند. در mapping، حرف D جای داده و خط زیر جای chunk کدشده است. در هر لایه، c یعنی chunkی که آن لایه تولید می‌کند. لایه‌ی سراسری parityهای 2 و 6 را با RS می‌سازد و هر لایه‌ی محلی یک parity XOR مانند برای سه chunk گروه خود. با crush-locality=rack، قانون CRUSH دو rack و در هر rack چهار host انتخاب می‌کند تا ترمیم محلی از rack بیرون نرود](figures/ch27/f09_lrc.png){#fig-27-f09_lrc}

# Clay: کدام sub-chunkها برای ترمیم خوانده می‌شوند {#sec-27-13}

::: {.algo #alg-27-7 title="انتخاب sub-chunkهای ترمیم در Clay" src="src/erasure-code/clay/ErasureCodeClay.cc :: ErasureCodeClay::parse، get_repair_subchunks، get_repair_sub_chunk_count" complexity="O(qʸ) بازه برای گره گم‌شده در سطر y؛ ترافیک d·(sub_chunk_no/q) sub-chunk"}
:::

```text
pseudocode
q = d − k + 1 ; nu = (k+m) % q ? q − (k+m) % q : 0
t = (k+m+nu)/q ; sub_chunk_no = q^t
get_repair_subchunks(lost):
    y = lost / q ; x = lost % q
    seq = q^(t−1−y) ; num = q^y ; idx = x·seq
    repeat num times: emit [idx, idx+seq) ; idx += q·seq
```

**مثال عددی.** k=4، m=2، d=5 ⇒ q = 2، nu = 0، t = 3 و sub_chunk_no = 8. برای گره 0 (x=0، y=0): seq = 4 و num = 1، پس sub-chunkهای 0 تا 3. برای گره 2 (x=0، y=1): seq = 2 و num = 2، پس {0، 1، 4، 5}. برای گره 5 (x=1، y=2): seq = 1 و num = 4، پس {1، 3، 5، 7}. هر یک از 5 helper نصف chunk خود را می‌فرستد، یعنی 2.5 chunk در برابر 4 chunk در RS. یک chunk چهار مگابایتی با 2.5 × 4 = 10 MiB به جای 16 MiB ترمیم می‌شود.

![شبکه‌ی sub-chunk در Clay با k=4، m=2 و d=5 برای سه گره گم‌شده‌ی متفاوت. سطرها گره‌ها با مختصات (x, y) در شبکه‌ی q×t هستند و ستون‌ها شاخص sub-chunk. سطر قرمز گره گم‌شده است و خانه‌های آبی sub-chunkهایی‌اند که هر helper می‌فرستد. الگو از get_repair_subchunks می‌آید: هرچه y بزرگ‌تر باشد، بازه‌ها کوتاه‌تر و پراکنده‌ترند. پس خواندن روی دیسک تکه‌تکه‌تر می‌شود، و این هزینه‌ی پنهان Clay روی HDD است](figures/ch27/f10_clay.png){#fig-27-f10_clay}

::: {.tip}
در Clay، چون خواندن‌ها به بازه‌های کوچک (sub_chunk_no برابر) شکسته می‌شوند، اندازه‌ی stripe_unit باید آن‌قدر بزرگ باشد که هر sub-chunk دست‌کم چند کیلوبایت شود. اگر chunk فقط 4K باشد و sub_chunk_no = 8، هر sub-chunk فقط 512 بایت می‌شود (اندازه‌ی واقعی chunk را get_chunk_size با هم‌ترازی sub_chunk_no·k گرد می‌کند).
:::

# تکمیلی و به‌روز {#sec-27-14}

- **پیش‌فرض پلاگین:** در Squid `plugin=jerasure`، و در Tentacle و main `plugin=isa` (هر دو با `technique=reed_sol_van k=2 m=2`). این تغییر را در کد `global.yaml.in` هر دو شاخه بررسی کرده‌ایم.
- **EC بهینه:** کد main کلاس `ECSwitch` را دارد که به‌عنوان «سوئیچ موقت» میان backend قدیمی (`ECBackendL`) و جدید (`ECBackend`) توصیف شده است. طبق توضیح خود کد، پس از اطمینان کامل، backend قدیمی حذف خواهد شد.
- **EC و stretch cluster:** کارهای پشتیبانی EC در stretch mode در شاخه‌ی main ادامه دارد. پیش از استفاده، یادداشت‌های انتشار نسخه‌ی هدف را بخوانید.

# تمرین عملی {#sec-27-15}

1. ضرب $\mathrm{GF}(2^8)$ با 0x11D را در پایتون پیاده کنید و جدول ضرب‌های این فصل را بازتولید کنید. سپس decode با دو خرابی را برای الگوی دیگری (مثلاً D0 و P1) حل کنید.
2. با `ceph_erasure_code_benchmark` (در بسته‌ی تست‌ها) سرعت encode پلاگین‌های isa و jerasure را برای k=8 و m=3 روی سرور خود مقایسه کنید.
3. روی یک pool آزمایشی EC با و بدون `allow_ec_optimizations`، fio با نوشتن تصادفی 4K اجرا و IOPS و تأخیر را مقایسه کنید.
4. پهنای باند ترمیم CLAY را برای (k=6، m=3، d=8) محاسبه و با RS مقایسه کنید.

# پرسش‌های مرور {#sec-27-16}

1. چرا جمع و تفریق در $\mathrm{GF}(2^8)$ هر دو XOR هستند؟
2. 0x56 × 0x04 در $\mathrm{GF}(2^8)$ با 0x11D چگونه محاسبه می‌شود؟
3. کد MDS چیست و چرا Vandermonde ساده‌ی ISA-L همیشه MDS نیست؟
4. Ceph در چه شرایطی خودکار به cauchy تغییر می‌دهد؟
5. در مثال این فصل، P0 و P1 چگونه به دست آمدند؟
6. چرا ضرایب decode کش می‌شوند؟
7. PSHUFB چگونه ضرب در ثابت را سریع می‌کند؟
8. parity delta چیست و چرا درست است؟
9. stripe_unit پیش‌فرض در pool بهینه چقدر است و چرا؟
10. پهنای باند ترمیم CLAY با k=8، m=4 و d=11 چقدر است و هزینه‌ی آن چیست؟

# منابع این فصل {#sec-27-17}

- مستندات erasure code: https://docs.ceph.com/en/latest/rados/operations/erasure-code/
- پروفایل‌ها: https://docs.ceph.com/en/latest/rados/operations/erasure-code-profile/
- پلاگین CLAY: https://docs.ceph.com/en/latest/rados/operations/erasure-code-clay/
- پلاگین LRC: https://docs.ceph.com/en/latest/rados/operations/erasure-code-lrc/
- پلاگین SHEC: https://docs.ceph.com/en/latest/rados/operations/erasure-code-shec/
- ErasureCodeIsa.cc: https://github.com/ceph/ceph/blob/main/src/erasure-code/isa/ErasureCodeIsa.cc
- ISA-L ec_base.c: https://github.com/intel/isa-l/blob/master/erasure_code/ec_base.c
- مقاله‌ی Clay codes (FAST 2018): https://www.usenix.org/conference/fast18/presentation/vajha
- آموزش Reed-Solomon (Plank): https://web.eecs.utk.edu/~jplank/plank/papers/CS-96-332.html
