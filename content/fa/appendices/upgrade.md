---
id: upgrade
lang: fa
---

::: {.tldr}

- در هر گام فقط یک نسخه‌ی اصلی جلو بروید و همیشه به آخرین نسخه‌ی نقطه‌ای آن: Reef 18.2، سپس Squid 19.2 و بعد Tentacle 20.2. اگر روی Squid 19.2.6 یا بعدتر هستید، فقط به Tentacle 20.2.4 یا بعدتر بروید.
- پیش از هر گام: `HEALTH_OK`، همه‌ی PGها `active+clean`، پشتیبان از keyringها، پیکربندی و نقشه‌ها، و ظرفیت آزاد برای از دست دادن یک failure domain.
- cephadm ترتیب را خودش نگه می‌دارد (mgr، mon، crash، osd، mds، rgw و بعد بقیه) و در پایان `require_osd_release` را بالا می‌برد؛ این پرچم و هر قابلیت تازه‌ی روی دیسک که روشن کنید، یک‌طرفه است.
- Squid 19.2.6 و Tentacle 20.2.4 نوع کلید تازه‌ی `aes256k` را در cephx می‌آورند: cephadm کلید daemonها را عوض می‌کند، ولی چرخش کلید کلاینت‌ها با شماست و نوع قدیمی باید تا وقتی آخرین کلاینت کلید تازه نگرفته، مجاز بماند.

```bash
ceph orch upgrade start --ceph-version 19.2.7
```

[![مسیر ارتقا: بررسی‌های پیش از ارتقا، از Reef به Squid، نوع کلیدهای cephx و سپس از Squid به Tentacle؛ require-osd-release در هر نسخه گام یک‌طرفه است](figures/app/f01_upgrade_path.png)](#fig-app-upgrade-path)

:::

این پیوست دستورالعملی است برای بردن یک کلاستر عملیاتی از Reef (18.2) از راه Squid (19.2) به Tentacle (20.2). فصل ۱۹ سازوکار ارتقا با cephadm را توضیح می‌دهد؛ این‌جا همان سازوکار به شکل یک روال درآمده است: بررسی‌هایی که پیش از هر گام باید انجام شوند، تغییرهای هر نسخه که ممکن است در میانه‌ی راه چیزی را بشکنند، و روایتی صادقانه از این‌که چه چیزی برگشت‌پذیر است. نسخه‌های نقطه‌ای این پیوست (Squid 19.2.7 و Tentacle 20.2.5) در زمان نگارش آخرین نسخه‌ها هستند؛ پیش از شروع، فهرست docs.ceph.com/en/latest/releases را ببینید و آخرین نسخه‌ی نقطه‌ای سری مقصد را به کار ببرید.

![مسیر ارتقا در چهار مرحله: بررسی‌های پیش از ارتقا؛ از Reef به آخرین نسخه‌ی نقطه‌ای Squid به ترتیب cephadm و در پایان require-osd-release squid؛ بردن کلیدهای cephx به aes256k؛ و از Squid به Tentacle 20.2.4 یا بعدتر و در پایان require-osd-release tentacle. هر دو گام require-osd-release یک‌طرفه‌اند](figures/app/f01_upgrade_path.png){#fig-app-upgrade-path}

# مسیرهای پشتیبانی‌شده

Ceph ارتقا را حداکثر از روی دو نسخه‌ی اصلی پشتیبانی می‌کند، و فقط به آخرین نسخه‌ی نقطه‌ای سری مقصد: هر نسخه فقط در برابر نسخه‌هایی آزموده می‌شود که هنگام انتشارش وجود داشته‌اند.

| از | به | پشتیبانی می‌شود؟ | توضیح |
|---|---|---|---|
| Quincy 17.2 | Squid 19.2 | بله | یادداشت‌های Squid، Quincy یا Reef را نقطه‌ی شروع مجاز می‌دانند |
| Reef 18.2 | Squid 19.2 | بله | گام اول این پیوست |
| Reef 18.2 | Tentacle 20.2 | بله | یادداشت‌های Tentacle آن را مجاز می‌دانند؛ مسیر دوگامی از راه Squid را آسان‌تر می‌توان متوقف و بررسی کرد |
| Squid 19.2 | Tentacle 20.2 | بله | گام دوم این پیوست |
| Squid 19.2.6 یا بعدتر | Tentacle پیش از 20.2.4 | خیر | daemonهای Tentacle پیش از 20.2.4 نوع کلیدهای تازه را نمی‌شناسند و بالا نمی‌آیند |
| Quincy یا قدیمی‌تر | Tentacle 20.2 | خیر | اول به Reef یا Squid ارتقا دهید |
| هر نسخه | یک نسخه‌ی اصلی قدیمی‌تر | خیر | بازگشت به نسخه‌ی قبلی وجود ندارد؛ بخش «توقف موقت، لغو و بازگشت» را ببینید |

::: {.note}
دو گام از یک گام بیشتر طول می‌کشد، ولی هر گام با یک کلاستر پایدار و کاملاً پشتیبانی‌شده تمام می‌شود که می‌توانید چند روز رویش کار کنید، و در هر گام تغییرهای هم‌زمانِ کمتری برای اشکال‌یابی وجود دارد.
:::

# فهرست بررسی پیش از ارتقا

کل فهرست را پیش از هر گام اجرا کنید، نه فقط پیش از گام اول. هیچ موردی از این فهرست، جز پرچم‌های پایان آن، چیزی را در کلاستر تغییر نمی‌دهد.

| بررسی | دستور | انتظار / چرا |
|---|---|---|
| سلامت کلی | `ceph health detail` | `HEALTH_OK`، یا فقط هشدارهایی که علتشان را می‌دانید و با زمان انقضا mute کرده‌اید |
| وضعیت PGها | `ceph pg stat` | همه‌ی PGها `active+clean`؛ هیچ PG در حالت `down`، `recovering`، `incomplete`، `undersized` یا `backfilling` نباشد |
| نسخه‌ی daemonها | `ceph versions` | برای هر نوع daemon یک نسخه؛ اگر ارتقای قبلی نیمه‌کاره است، اول آن را تمام کنید |
| میزبان‌ها | `ceph orch host ls` | همه‌ی میزبان‌ها online و هیچ‌کدام در حالت maintenance نباشند؛ وگرنه cephadm ارتقا را شروع نمی‌کند |
| quorum مانیتورها | `ceph quorum_status --format json-pretty` | همه‌ی مانیتورها در quorum باشند تا بتوان هر بار یکی را بازراه‌اندازی کرد |
| mgr آماده‌به‌کار | `ceph mgr stat` | دست‌کم یک mgr آماده‌به‌کار؛ بدون آن cephadm هشدار `UPGRADE_NO_STANDBY_MGR` می‌دهد |
| `require_osd_release` | `ceph osd dump \| grep require_osd_release` | پیش از Squid دست‌کم `quincy` و پیش از Tentacle دست‌کم `reef` |
| سازگاری کلاینت‌ها | `ceph features` و `ceph osd get-require-min-compat-client` | قدیمی‌ترین نسخه‌ی کلاینتِ وصل را بشناسید؛ ارتقا `min_compat_client` را بالا نمی‌برد |
| کلاینت‌های کرنلی | `ceph features` (ستون `release` هر گروه) | کرنل‌هایی را که RBD یا CephFS را mount کرده‌اند یادداشت کنید: بعداً همین‌ها نوع کلید cephx را تعیین می‌کنند |
| ظرفیت آزاد | `ceph osd df tree` و `ceph df` | جای کافی برای از دست دادن یک failure domain بدون رسیدن به `nearfull` |
| CephFS | `ceph fs status` | `max_mds` و standby-replay هر فایل‌سیستم را یادداشت کنید؛ cephadm در مرحله‌ی MDS مقدار `max_mds` را ۱ می‌کند |
| RGW multisite | `radosgw-admin sync status` | پیش از شروع، همگام‌سازی فراداده و داده در همه‌ی zoneها به‌روز باشد |
| release notes | docs.ceph.com/en/latest/releases | یادداشت‌های نسخه‌ی مقصد و همه‌ی نسخه‌های نقطه‌ای میان راه را بخوانید، از جمله بخش «Critical Upgrade Steps» |

## پیش از شروع پشتیبان بگیرید

ارتقا داده‌ای را پاک نمی‌کند، ولی یک اشتباه در کلیدها یا پیکربندی می‌تواند دسترسی شما را به یک کلاستر سالم ببندد. این موارد را روی میزبان مدیریت ذخیره کنید و نسخه‌ای از آن‌ها را بیرون از کلاستر نگه دارید:

```bash
mkdir -p /root/ceph-pre-upgrade && cd /root/ceph-pre-upgrade
ceph config dump --format json > config-dump.json
ceph config generate-minimal-conf > ceph.conf.minimal
ceph mon getmap -o monmap.bin
ceph osd getmap -o osdmap.bin
ceph osd getcrushmap -o crushmap.bin
ceph fs dump --format json > fsmap.json
ceph orch ls --export > service-specs.yaml
radosgw-admin period get > period.json
ceph auth export -o auth-export.keyring
chmod 600 auth-export.keyring
```

::: {.warn}
فایل `auth-export.keyring` همه‌ی کلیدهای کلاستر، از جمله `client.admin`، را در خود دارد. آن را رمزگذاری‌شده، بیرون از کلاستر و بیرون از هر مخزن کد نگه دارید و وقتی ارتقا تمام شد، نسخه‌ی کاری را پاک کنید. محتوای آن را هرگز در تیکت یا گفت‌وگو نچسبانید.
:::

## پرچم‌ها و autoscaler

در طول ارتقا autoscaler مربوط به PGها را متوقف کنید: تقسیم یا ادغام PG در میانه‌ی ارتقا آن را کند می‌کند، و یک نسخه‌ی تازه ممکن است مقدار پیش‌فرض `mon_target_pg_per_osd` را عوض کند. نسخه‌های تازه‌ی cephadm خودشان autoscaler را متوقف می‌کنند، ولی گذاشتن پرچم به دست خودتان کلاسترهای مبتنی بر بسته را هم پوشش می‌دهد.

```bash
ceph osd pool set noautoscale
ceph osd set noout
```

با cephadm، گذاشتن `noout` اختیاری است، چون بازراه‌اندازی هر OSD با `ok-to-stop` کنترل می‌شود. با بسته‌ها آن را بگذارید و در پایان بردارید. هر دو پرچم را فقط وقتی بردارید که گام کامل شده و کلاستر دوباره سالم است.

# تغییرهای نسخه‌ها که در ارتقا مهم‌اند

این جدول‌ها فقط تغییرهایی را فهرست می‌کنند که ممکن است در حین ارتقا یا بلافاصله پس از آن چیزی را بشکنند. دیگر تغییرهای مهم هر نسخه در پیوست ح آمده است.

## از Reef به Squid

| حوزه | تغییر | چه باید کرد |
|---|---|---|
| نسخه‌ی نقطه‌ای | 19.2.0 هنگام ارتقا با ماژول balancer مشکل داشت که در 19.2.1 رفع شد | مستقیم به آخرین نسخه‌ی نقطه‌ای Squid بروید |
| RADOS | هشدار `POOL_APP_NOT_ENABLED` برای هر pool بدون برچسب application داده می‌شود | پیش از ارتقا هر pool را با `ceph osd pool application enable` برچسب بزنید |
| RADOS | در حین ارتقا ممکن است یک PG میان دو acting set جابه‌جا شود (باگ 62338) | ارتقا را تمام کنید؛ در صورت نیاز تا پایان آن `osd_async_recovery_min_cost` را بالا ببرید |
| مانیتور | گزینه‌های `mon_cluster_log_file_level` و `mon_cluster_log_to_syslog_level` حذف شدند | تنظیم را به `mon_cluster_log_level` منتقل کنید |
| CephFS | balancer خودکار فراداده به‌طور پیش‌فرض خاموش است (`balance_automate`) | فقط اگر به آن تکیه داشتید، دوباره روشنش کنید |
| CephFS | `root_squash` در capهای `mds` به قابلیت کلاینتیِ `client_mds_auth_caps` نیاز دارد | آن کلاینت‌ها را ارتقا دهید، وگرنه MDS هشدار `MDS_CLIENTS_BROKEN_ROOTSQUASH` می‌دهد |
| RGW | radosgw هنگام راه‌اندازی `rgw_realm` را اعتبارسنجی می‌کند | مقدار نادرست `rgw_realm` را اصلاح یا حذف کنید، وگرنه راه‌اندازی با «failed to load realm» شکست می‌خورد |
| RGW | قالب `notification_v2` برای topicها در ارتقا روشن نمی‌شود | این zone feature را فقط وقتی روشن کنید که همه‌ی RGWهای همه‌ی zoneها روی Squid باشند |
| cephx | دستور `ceph auth rotate` اضافه شد | کلیدها را درجا بچرخانید، به‌جای پاک کردن و ساختن دوباره‌ی آن‌ها |

## از Squid به Tentacle

| حوزه | تغییر | چه باید کرد |
|---|---|---|
| نسخه‌ی نقطه‌ای | از Squid 19.2.6 یا بعدتر، Tentacle پیش از 20.2.4 بالا نمی‌آید | به Tentacle 20.2.4 یا بعدتر بروید |
| MGR | ماژول‌های `restful` و `zabbix` حذف شدند | پیش از ارتقا به API ماژول `dashboard` و به `prometheus` مهاجرت کنید |
| RADOS | افزونه‌ی پیش‌فرض EC در کلاسترهای تازه ISA-L است؛ کلاسترهای ارتقایافته پیش‌فرض خود را نگه می‌دارند | برای poolهای موجود چیزی عوض نمی‌شود؛ در profileهای تازه افزونه را صریح انتخاب کنید |
| RADOS | FastEC (`allow_ec_optimizations`) به Tentacle بودن همه‌ی monها و OSDها نیاز دارد | آن را برای هر pool فقط پس از پایان گام روشن کنید؛ خاموش‌شدنی نیست |
| RADOS | قاعده‌ی CRUSH کشیده (stretch) با چند گام `take` ممکن است پس از ارتقا داده را جابه‌جا کند | قاعده‌های stretch را پیش از ارتقا بررسی کنید |
| RADOS | گزینه‌ی `osd_repair_during_recovery` حذف شد | آن را از پیکربندی بردارید |
| CephFS | تغییر `max_mds` روی کلاستر ناسالم به `--yes-i-really-mean-it` نیاز دارد | `max_mds` را فقط پس از سالم شدن کلاستر برگردانید |
| RBD | `rbd device map` به‌طور پیش‌فرض msgr2 به کار می‌برد | `-o ms_mode=legacy` را فقط برای میزبان‌هایی بدهید که msgr1 لازم دارند |
| RGW | `LastModified` تا ثانیه کوتاه می‌شود، پس ممکن است در حین ارتقا به عقب برگشته به نظر برسد | به برنامه‌هایی که زمان‌ها را مقایسه می‌کنند هشدار دهید |
| RGW | APIهای IAM در سطح tenant به نفع accountها منسوخ شدند | مهاجرت به accountها را برنامه‌ریزی کنید؛ فعلاً چیزی نمی‌شکند |

## نسخه‌های نقطه‌ای امنیتی: نوع کلید تازه‌ی cephx

Squid 19.2.6 و Tentacle 20.2.4 آسیب‌پذیری CVE-2025-30156 را رفع می‌کنند؛ یک دورزدن احراز هویت که از رمزگذاری بدون احراز اصالت AES-128-CBC در نوع کلید قدیمی `aes` می‌آید. این نسخه‌ها نوع کلید تازه‌ی `aes256k` (AES256-CTS-HMAC-SHA384-192) و شش بررسی سلامت اضافه می‌کنند که نشان می‌دهند چه چیزهایی هنوز نوع قدیمی را به کار می‌برند. در کلاستر ارتقایافته هر دو نوع مجاز می‌مانند و هیچ چیزی خودبه‌خود از کار نمی‌افتد؛ کار اصلی بردن همه‌ی کلیدها به `aes256k` با ترتیب درست است. کلاینت کرنل لینوکس از Linux 7.0 (و در backportهای توزیع‌ها) از `aes256k` پشتیبانی می‌کند؛ کرنل‌های قدیمی‌تر باید کلید `aes` نگه دارند.

# گام‌به‌گام با cephadm

## گام ۱: از Reef به Squid

بررسی کنید که همه‌ی میزبان‌ها image را دریافت می‌کنند، سپس ارتقا را شروع کنید و دنبالش کنید:

```bash
ceph orch upgrade check --image quay.io/ceph/ceph:v19.2.7
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7
ceph orch upgrade status
ceph -W cephadm
```

cephadm daemonها را به ترتیبی ثابت ارتقا می‌دهد: `mgr`، `mon`، `crash`، `osd`، `mds`، `rgw`، `rbd-mirror`، `cephfs-mirror`، `ceph-exporter`، gatewayها (`iscsi`، `nfs`، `nvmeof`، `smb`) و در پایان پشته‌ی پایش. هر مانیتور را فقط وقتی بازراه‌اندازی می‌کند که بقیه quorum را نگه دارند، و هر OSD را فقط پس از آن‌که `ok-to-stop` بگوید هیچ PG غیرفعال نمی‌شود. برای CephFS مقدار `max_mds` را ۱ می‌کند و پس از کار برمی‌گرداند. وقتی همه‌ی OSDها روی Squid رفتند، خودش `require_osd_release squid` را می‌گذارد.

## ارتقای مرحله‌ای

در یک کلاستر بزرگ، مرحله‌به‌مرحله ارتقا دهید تا بتوانید میان مرحله‌ها بایستید و وضعیت را ببینید. ترتیب همچنان برقرار است: cephadm مرحله‌ای را که بخواهد یک نوع daemon را پیش از انواع جلوتر ارتقا دهد، رد می‌کند.

```bash
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types mgr,mon
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types crash,osd --hosts <host1>,<host2>
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types mds
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --services <rgw-service> --limit 1
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7
```

دستور آخر هر چه را مانده ارتقا می‌دهد. در استقرار multisite برای RGW، هر بار یک zone (یک کلاستر) را ارتقا دهید و پیش از سراغ بعدی رفتن، صبر کنید تا `radosgw-admin sync status` به‌روز شود؛ zone featureهای تازه را فقط وقتی روشن کنید که همه‌ی zoneها روی نسخه‌ی تازه باشند.

## پس از هر گام

```bash
ceph versions
ceph osd dump | grep require_osd_release
ceph mon dump | grep min_mon_release
ceph health detail
ceph crash ls-new
```

`ceph versions` باید برای هر نوع daemon فقط یک نسخه نشان دهد و `require_osd_release` و `min_mon_release` نسخه‌ی تازه را. پس از آن، پیش از گام بعد چند روز روی نسخه‌ی تازه کار کنید و فقط پس از آن قابلیت‌هایی را که از آن نسخه می‌خواهید روشن کنید (جدول بخش آخر را ببینید).

## گام ۲: بردن کلیدهای cephx به aes256k

این گام به Squid 19.2.6 یا بعدتر (یا Tentacle 20.2.4 یا بعدتر) نیاز دارد. بررسی کنید که مانیتورها هر دو نوع کلید را مجاز می‌دانند، و نوع کلیدهای تازه را انتخاب کنید:

```bash {since=squid}
ceph --format=json mon dump | jq -r '.auth_allowed_ciphers | map(.name) | join(",")'
ceph mon set auth_allowed_ciphers aes,aes256k
ceph mon set auth_preferred_cipher aes256k
ceph health detail | grep AUTH_INSECURE
```

cephadm کلید daemonهایی را که مدیریت می‌کند، خودش می‌چرخاند. کلیدهای کلاینت با شماست: هر کدام را فقط وقتی بچرخانید که همه‌ی میزبان‌هایی که آن را به کار می‌برند، کلاینتی با پشتیبانی از `aes256k` داشته باشند، و keyring تازه را بی‌درنگ پخش کنید. `ceph auth rotate` capهای entity را نگه می‌دارد؛ هرگز کلیدی را فقط برای عوض کردن نوعش پاک نکنید و از نو نسازید، چون این کار capهایش را هم از نو می‌کند.

```bash {since=squid}
ceph auth get-or-create client.admin-backup mon 'allow *' -o client.admin-backup.keyring
ceph --name client.admin-backup --keyring client.admin-backup.keyring auth ls
ceph auth rotate --key-type=aes256k client.app -o client.app.keyring
ceph-authtool --import-keyring client.app.keyring /etc/ceph/ceph.client.app.keyring
ceph --name client.app --keyring /etc/ceph/ceph.client.app.keyring health
ceph health mute AUTH_INSECURE_CLIENT_KEY_TYPE 8w
```

`client.admin` را آخر از همه بچرخانید، پس از آن‌که مطمئن شدید کلید پشتیبان بالا کار می‌کند، و وقتی کار تمام شد `client.admin-backup` را حذف کنید. هشدار کلاینت‌ها را فقط برای کلیدهایی mute کنید که هنوز نمی‌توانید بچرخانید، مثل کلید کلاینت‌های کرنلی قدیمی. وقتی `AUTH_INSECURE_SERVICE_KEY_TYPE` و `AUTH_INSECURE_CLIENT_KEY_TYPE` هر دو پاک شدند، کلیدهای چرخان سرویس‌ها را به نوع تازه ببرید و نوع قدیمی را ممنوع کنید:

```bash {since=squid}
ceph mon set auth_service_cipher aes256k
ceph config set mon mon_auth_allow_insecure_key false
ceph mon set auth_allowed_ciphers aes256k
```

::: {.warn}
`aes` را فقط وقتی از `auth_allowed_ciphers` بردارید که هیچ کلیدی از نوع قدیمی نمانده باشد. اگر `client.admin` یا کلید یک daemon هنوز `aes` باشد، کلاستر دسترسی شما را می‌بندد و به روال اضطراری مستندات cephx در upstream نیاز پیدا می‌کنید. کلاینت‌هایی که کرنلشان قدیمی‌تر از 7.0 است، به مجاز ماندن `aes` و کلید `aes` مخصوص خودشان نیاز دارند.
:::

## گام ۳: از Squid به Tentacle

فهرست بررسی را تکرار کنید و سپس به آخرین نسخه‌ی نقطه‌ای Tentacle ارتقا دهید، هرگز به نسخه‌ای پیش از 20.2.4:

```bash
ceph orch upgrade check --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade status
```

ترتیب، بررسی‌ها و وضعیت پایانی همان گام ۱ است و در پایان `require_osd_release tentacle` گذاشته می‌شود. وقتی کلاستر سالم شد، پرچم‌ها را بردارید:

```bash
ceph osd pool unset noautoscale
ceph osd unset noout
```

# کلاسترهای مبتنی بر بسته

بدون cephadm ترتیب را خودتان نگه می‌دارید. در Reef و بعد از آن، نام unitهای systemd شامل fsid کلاستر است؛ آن‌ها را با `systemctl -l | grep ceph` پیدا کنید. روی هر میزبان اول بسته‌های تازه را نصب کنید و سپس فقط نوع daemon مرحله‌ی جاری را بازراه‌اندازی کنید. این قطعه Squid را مقصد گرفته است؛ برای گام دوم، در خط یکی مانده به آخر `tentacle` بنویسید:

```bash {since=squid}
ceph osd set noout
systemctl restart ceph-mon.target
ceph mon dump | grep min_mon_release
systemctl restart ceph-mgr.target
ceph osd ok-to-stop <osd-id>
systemctl restart ceph-osd.target
ceph fs set <fs_name> allow_standby_replay false
ceph fs set <fs_name> max_mds 1
systemctl restart ceph-mds.target
ceph fs set <fs_name> max_mds <original_max_mds>
systemctl restart ceph-radosgw.target
ceph osd require-osd-release squid
ceph osd unset noout
```

مانیتورها را هر بار روی یک میزبان بازراه‌اندازی کنید و پس از هر کدام quorum را بررسی کنید، سپس mgrها، سپس OSDها را هر بار روی یک میزبان (یا یک failure domain)، و پیش از میزبان بعدی صبر کنید تا PGها `active+clean` شوند. برای CephFS، هر فایل‌سیستم را به یک MDS فعال برسانید، standbyها را متوقف کنید، آخرین MDS فعال را ارتقا دهید، سپس standbyها را راه بیندازید و `max_mds` را برگردانید. RGW آخر از همه می‌آید. فقط وقتی `ceph versions` همه‌ی OSDها را روی نسخه‌ی تازه نشان داد، `require-osd-release` را اجرا کنید. در کلاسترهای مبتنی بر بسته، چرخش کلید daemonها در گام ۲ هم دستی است؛ روال upstream برای ارتقای cephx را دنبال کنید که برچسب `osd_key` هر OSD را هم به‌روز می‌کند.

# پایش در طول ارتقا

```bash
ceph orch upgrade status
ceph -W cephadm
ceph versions
ceph orch ps --daemon-type osd
ceph progress
ceph health detail
```

`ceph -s` برای ارتقا نوار پیشرفت نشان می‌دهد و `ceph versions` نشان می‌دهد چند daemon از هر نوع روی نسخه‌ی تازه رفته‌اند. مراقب این هشدارها باشید: `UPGRADE_FAILED_PULL` (یک میزبان نمی‌تواند image را دریافت کند؛ ارتقا را متوقف کنید و با image درست دوباره شروع کنید)، `UPGRADE_NO_STANDBY_MGR`، `UPGRADE_OFFLINE_HOST` (ارتقا تا وقتی خودتان ادامه‌اش ندهید متوقف می‌ماند)، و `SLOW_OPS` یا PGهای غیرفعالِ تازه، که یعنی پیش از ادامه باید مکث کنید و علت را ببینید. داشبوردهای فصل ۲۰، به‌ویژه تأخیر کلاینت‌ها، را باز نگه دارید.

# توقف موقت، لغو و بازگشت

```bash
ceph orch upgrade pause
ceph orch upgrade resume
ceph orch upgrade stop
```

`pause` مقصد را نگه می‌دارد و از همان‌جا ادامه می‌دهد؛ `stop` ارتقا را لغو می‌کند و کلاستر را در وضعیتی آمیخته رها می‌کند که Ceph فقط به‌طور موقت پشتیبانی‌اش می‌کند. هیچ‌کدام چیزی را به نسخه‌ی قبلی برنمی‌گرداند: بازگشت به نسخه‌ی اصلی قبلی وجود ندارد. اگر صادق باشیم، «بازگشت» در Ceph فقط چند حالت محدود است:

| وضعیت | برگشت‌پذیر؟ | چه می‌توان کرد |
|---|---|---|
| فقط mgrها ارتقا یافته‌اند | تا حدی | mgrها را با image قبلی دوباره مستقر کنید (`ceph orch daemon redeploy mgr.<id> --image <old-image>`)؛ این همان راه مستند خروج از ارتقای ناموفق Squid 19.2.6 به Tentacle قدیمی است |
| بعضی مانیتورها ارتقا یافته‌اند | در عمل خیر | رو به جلو بروید: علت را رفع کنید و ارتقا را تمام کنید؛ وقتی همه‌ی مانیتورها روی نسخه‌ی تازه رفتند، `min_mon_release` بالا می‌رود و مانیتورهای قدیمی‌تر دیگر نمی‌توانند بپیوندند |
| بعضی OSDها ارتقا یافته‌اند | خیر | رو به جلو بروید؛ OSD ممکن است هنگام راه‌اندازی با نسخه‌ی تازه، فراداده‌ی روی دیسک را تبدیل کند |
| `require_osd_release` بالا رفته است | خیر | این پرچم پایین‌آوردنی نیست و OSDهای نسخه‌ی قبلی دیگر بالا نمی‌آیند |
| قابلیتی پس از ارتقا روشن شده است (FastEC، `notification_v2`، accountهای RGW) | خیر | تا وقتی نسخه مدتی خوب کار نکرده، چنین قابلیت‌هایی را روشن نکنید |
| نسخه‌ی نقطه‌ای قدیمی‌تر از همان نسخه‌ی اصلی | پشتیبانی نمی‌شود | ممکن است کار کند یا نکند؛ یک راه‌حل پیکربندی یا یک نسخه‌ی نقطه‌ای بعدتر را ترجیح دهید |
| کلیدی در cephx چرخانده شده است | بله، با احتیاط | کلید تازه به‌تنهایی کار می‌کند؛ نوع قدیمی را فقط از راه روال اضطراری مستند برگردانید، و کلید مدیر پشتیبان برای همین است |
| برگشت به نسخه‌ی اصلی قدیمی‌تر | فقط با یک کلاستر تازه | یک کلاستر تازه با نسخه‌ی قدیمی بسازید و داده را به آن مهاجرت دهید یا بازیابی کنید |

::: {.tip}
بهترین برنامه‌ی بازگشت، برنامه‌ای کوتاه است: اول یک کلاستر آزمایشی با همان نسخه، همان قابلیت‌ها و همان نسخه‌های کلاینت را ارتقا دهید، و گام‌ها را کوچک نگه دارید تا «رو به جلو رفتن» همیشه گامی کوچک و شناخته‌شده باشد.
:::

# درس‌هایی از یک ارتقای واقعی: وقتی مشکل کلیدها بود

در یکی از ارتقاهای عملیاتی که نویسنده در آن حضور داشت (جزئیاتی که کلاستر یا صاحبش را شناسایی‌پذیر می‌کند حذف شده است)، daemonها بی‌دردسر ارتقا یافتند. مشکل کلیدهای cephx و capهای آن‌ها بود، نه خود daemonها. علت پیدا شد، مستند شد و رفع شد. درس‌هایش به آن کلاستر محدود نیست:

1. پیش از دست زدن به هر کلید، بررسی‌های سلامت را بخوانید. پس از ارتقا هشدارهای `AUTH_INSECURE_*` طبیعی‌اند؛ هر کدام نام entityهایی را می‌آورد که هنوز نوع کلید قدیمی دارند، و همین فهرست برنامه‌ی کار است.
2. هرگز پیش از آن‌که آخرین کلاینت کلید تازه گرفته باشد، `auth_allowed_ciphers` را تنگ نکنید. کلاینت‌های کرنلی قدیمی و میزبان‌های خودکارسازیِ فراموش‌شده معمولاً همان‌هایی‌اند که هنوز روی `aes` مانده‌اند.
3. بچرخانید، از نو نسازید. `ceph auth rotate` capها را نگه می‌دارد؛ `auth del` و پس از آن `get-or-create` بی‌صدا capهایی را حذف می‌کند که کسی سال‌ها پیش دستی اضافه کرده بود، و آن‌وقت کلاینت به‌جای خطای احراز هویت با «permission denied» شکست می‌خورد.
4. هر کلید جاهایی بیش از مانیتورها زندگی می‌کند: فایل‌های keyring روی هر میزبان کلاینت، secretها در سامانه‌های هماهنگ‌سازی مثل Kubernetes، و برای OSDهایی که با ceph-volume ساخته شده‌اند، برچسب `osd_key` روی خود دستگاه که keyring هنگام activate از روی آن دوباره نوشته می‌شود. کلیدی که فقط در یک جا به‌روز شده، نه همان لحظه، بلکه در بازراه‌اندازی بعدی شکست می‌خورد.
5. یک کلید مدیر اضطراری کارا نگه دارید که پیش از تغییر آزموده شده باشد، و پس از کار حذفش کنید.
6. کلیدها را در گروه‌های کوچک بچرخانید، هر گروه را با یک عملیات واقعی کلاینت بیازمایید، و ترتیبی را که به کار بردید بنویسید؛ همان فهرست بعداً سابقه‌ی تغییر هم می‌شود.

# منابع

- یادداشت‌های انتشار Ceph، بخش‌های ارتقای Squid و Tentacle: https://docs.ceph.com/en/latest/releases/
- ارتقای Ceph با cephadm: https://docs.ceph.com/en/latest/cephadm/upgrade/
- ارتقا و چرخش کلیدهای cephx: https://docs.ceph.com/en/latest/rados/configuration/auth-config-ref/
- CVE-2025-30156: https://docs.ceph.com/en/latest/security/CVE-2025-30156/
- zone featureهای RGW: https://docs.ceph.com/en/latest/radosgw/zone-features/
- FastEC (`allow_ec_optimizations`): https://docs.ceph.com/en/latest/rados/operations/erasure-code/
