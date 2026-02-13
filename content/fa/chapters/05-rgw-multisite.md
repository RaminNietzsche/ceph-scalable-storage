---
chapter: 5
id: ch05
title: "ذخیره‌سازی شیء چندسایتی با RGW Multi-Site"
part: main
lang: fa
---

# پیش از شروع {#sec-05-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-05-1-1}

یک کلاستر Ceph، هر قدر هم بزرگ، در یک مرکز داده قرار دارد. برای بازیابی از سانحه، نزدیک کردن داده به کاربران در مناطق مختلف، یا مهاجرت بین مراکز داده، باید داده‌ی شیء را بین چند کلاستر مستقل تکثیر کنیم. **RGW Multi-Site** پاسخ Ceph به این نیاز است. در این فصل می‌بینیم:

- realm، zonegroup، zone و period چه هستند و چطور با هم یک فضای نام سراسری می‌سازند؟
- multisite امروزی (نسخه‌ی ۲، از Jewel) چه فرقی با پیکربندی federated قدیمی Hammer دارد؟
- پیش‌نیازهای شبکه، زمان و ظرفیت برای یک استقرار چندسایتی چیست؟
- چطور دو zone را، هم به روش دستی با `radosgw-admin` و هم با ماژول خودکار `ceph rgw`، پیکربندی کنیم؟
- چطور وضعیت همگام‌سازی را بخوانیم، مشکلات را پیدا کنیم و هنگام سانحه master را جابه‌جا کنیم؟
- sync policy، archive zone و resharding در multisite چگونه کار می‌کنند؟

## پیش‌نیاز {#sec-05-1-2}

دو کلاستر Ceph (برای آزمایشگاه دو کلاستر تک‌نودی کافی است) که RGWهایشان از طریق HTTP به هم دسترسی دارند. مفاهیم فصل ۴ را باید بدانید.

# مفاهیم multisite {#sec-05-2}

## سلسله‌مراتب {#sec-05-2-1}

![سلسله‌مراتب multisite: realm شامل zonegroupها و هر zonegroup شامل zoneهایی است که هر کدام در یک کلاستر Ceph جداگانه قرار دارند](figures/ch05/f01_hier.png){#fig-05-f01_hier}

| مفهوم | تعریف | نکته |
|---|---|---|
| zone | مجموعه‌ای از poolها و نمونه‌های RGW در یک کلاستر Ceph | هر zone در یک کلاستر است؛ یک کلاستر می‌تواند چند zone داشته باشد |
| zonegroup | گروهی از zoneها که داده‌ی bucketها بین آن‌ها تکثیر می‌شود | قبلاً «region» نامیده می‌شد؛ یک zone آن master است |
| realm | ظرف سراسری شامل zonegroupها؛ فضای نام یکتای کاربران و bucketها | یک zonegroup آن master است |
| period | نسخه‌ای از پیکربندی realm با شناسه و epoch | هر تغییر ساختاری با `period update --commit` منتشر می‌شود |
| master zone | zoneی که فراداده (کاربران، bucketها) را می‌پذیرد و به بقیه پخش می‌کند | ساخت کاربر و bucket فقط از طریق آن |

## چه چیزی و چطور تکثیر می‌شود؟ {#sec-05-2-2}

- **فراداده** (کاربران، bucketها، سیاست‌ها) در سطح realm تکثیر می‌شود و همیشه از master zone در master zonegroup منشأ می‌گیرد. درخواست ساخت bucket به zone غیر master به‌طور خودکار به master **forward** می‌شود.
- **داده‌ی اشیاء** فقط بین zoneهای یک zonegroup تکثیر می‌شود. zonegroupهای مختلف فضای نام مشترک دارند (نام bucket یکتاست) اما داده‌ی هر bucket فقط در zonegroup خودش است.
- همگام‌سازی **ناهمگام** و **active-active** است: کلاینت‌ها می‌توانند در هر zone بنویسند و تغییرات با تأخیری کوتاه به zoneهای دیگر می‌رسند. در تعارض نوشتن هم‌زمان روی یک شیء، آخرین نوشتن (بر اساس زمان) برنده است.

::: {.warn}
چون همگام‌سازی ناهمگام است، multisite جایگزین سازگاری قوی بین سایت‌ها نیست. اگر برنامه‌ای در سایت A می‌نویسد و بلافاصله در سایت B می‌خواند، ممکن است نسخه‌ی قدیمی یا هیچ نسخه‌ای نبیند. برنامه‌ها را طوری طراحی کنید که هر کلاینت «سایت خانگی» داشته باشد، یا وابستگی به خواندن فوری بین‌سایتی نداشته باشند.
:::

## تغییرات از پیکربندی federated در Hammer {#sec-05-2-3}

![از federated در Hammer به multisite نسخه‌ی ۲: همگام‌سازی از یک agent بیرونی به درون خود radosgw منتقل شد و همه‌ی zoneها نوشتنی شدند](figures/ch05/f02_evolution.png){#fig-05-f02_evolution}

در Hammer و پیش از آن، تکثیر با یک فرایند Python بیرونی به نام **radosgw-agent** انجام می‌شد، zone ثانوی فقط‌خواندنی بود و مفهوم realm و period وجود نداشت. از Jewel، multisite بازطراحی شد:

- همگام‌سازی درون خود radosgw انجام می‌شود (نیازی به agent نیست).
- همه‌ی zoneها می‌توانند داده بپذیرند (active-active).
- realm و period امکان تغییر پیکربندی سازگار و نسخه‌دار را فراهم کرده‌اند.
- failover با جابه‌جایی master zone و commit یک period جدید انجام می‌شود.

از آن زمان قابلیت‌های بسیاری اضافه شده است: sync policy با کنترل در سطح bucket (Octopus)، archive zone، resharding بدون توقف همگام‌سازی (از Reef با zone feature به نام `resharding`) و در Umbrella اصلاح‌های متعدد در درستی همگام‌سازی.

# پیش‌نیازهای multisite {#sec-05-3}

## شبکه و زمان {#sec-05-3-1}

- **دسترسی HTTP(S) بین RGWها:** RGWهای هر zone باید endpointهای zoneهای دیگر را ببینند. معمولاً endpoint هر zone نشانی load balancer آن است.
- **پهنای باند:** نرخ تغییر داده (نه حجم کل) تعیین‌کننده است. همگام‌سازی اولیه (full sync) کل داده‌ی موجود را منتقل می‌کند؛ برای داده‌ی چندصد ترابایتی، روزها طول می‌کشد.
- **تأخیر:** multisite برای WAN طراحی شده و تأخیر بالا را تحمل می‌کند، اما تأخیر زیاد، عقب‌ماندگی را بالا می‌برد.
- **همگامی ساعت:** حل تعارض و امضای درخواست‌ها به زمان وابسته است. همه‌ی nodeها باید با NTP همگام باشند.

## کاربر system و endpointها {#sec-05-3-2}

zoneها برای خواندن لاگ‌ها و اشیای یکدیگر از یک **کاربر system** با کلید مشترک استفاده می‌کنند. این کاربر در master zone ساخته می‌شود و کلیدش در پیکربندی همه‌ی zoneها قرار می‌گیرد.

::: {.warn}
کاربر system به همه‌ی داده‌ها و فراداده‌ی realm دسترسی کامل دارد. کلیدش را مثل کلید مدیر کلاستر حفاظت کنید، endpointهای همگام‌سازی را فقط روی شبکه‌ی خصوصی یا VPN بین سایت‌ها باز کنید و از TLS استفاده کنید.
:::

## ظرفیت و poolها {#sec-05-3-3}

هر zone poolهای خودش را دارد که نامشان با نام zone شروع می‌شود (مثلاً `eu-1.rgw.buckets.data`). اگر poolها را پیش از راه‌اندازی بسازید، می‌توانید قاعده‌ی CRUSH، EC و target_size_ratio را از ابتدا درست تعیین کنید؛ وگرنه RGW آن‌ها را با پیش‌فرض‌ها می‌سازد. علاوه بر داده، pool لاگ (`<zone>.rgw.log`) در multisite پرکارتر است و باید روی رسانه‌ی سریع باشد.

::: {.tip}
هر دو سایت را از نظر ظرفیت متقارن طراحی کنید. zone ثانوی که زودتر پر شود، همگام‌سازی را متوقف می‌کند و بعد از آزاد کردن فضا باید عقب‌ماندگی زیادی را جبران کند.
:::

# پیکربندی multisite به روش دستی {#sec-05-4}

![گام‌های راه‌اندازی: ساخت realm، zonegroup و master zone در کلاستر اصلی، سپس pull کردن realm و ساخت zone ثانوی در کلاستر دوم](figures/ch05/f04_setup.png){#fig-05-f04_setup}

فرض‌ها: کلاستر اصلی با RGW در دسترس روی `http://rgw-eu1.example.com:80` و کلاستر ثانوی روی `http://rgw-eu2.example.com:80`. realm به نام `gold`، zonegroup به نام `europe`، zoneها `eu-1` و `eu-2`.

## گام ۱: ساختار در کلاستر اصلی {#sec-05-4-1}

```bash
radosgw-admin realm create --rgw-realm=gold --default
radosgw-admin zonegroup create --rgw-zonegroup=europe \
  --endpoints=http://rgw-eu1.example.com:80 --rgw-realm=gold --master --default
radosgw-admin zone create --rgw-zonegroup=europe --rgw-zone=eu-1 \
  --endpoints=http://rgw-eu1.example.com:80 --master --default
```

اگر پیش‌تر RGW تک‌سایتی با zone و zonegroup پیش‌فرض (`default`) داشته‌اید و داده دارد، به‌جای ساختن zone جدید، zone و zonegroup پیش‌فرض را **تغییر نام** دهید و به realm اضافه کنید (مستندات «Migrating a Single-Site Deployment to Multi-Site»). در غیر این صورت داده‌ی موجود در zone قدیمی بی‌صاحب می‌ماند.

## گام ۲: کاربر system {#sec-05-4-2}

```bash
radosgw-admin user create --uid=sync-user --display-name="Multisite sync" --system
# access_key و secret_key را از خروجی بردارید
radosgw-admin zone modify --rgw-zone=eu-1 --access-key=<AK> --secret=<SK>
radosgw-admin period update --commit
```

## گام ۳: RGW برای zone اصلی {#sec-05-4-3}

با cephadm، سرویس RGW را با realm و zone مشخص مستقر کنید:

```bash
ceph orch apply rgw gold-eu1 --realm=gold --zone=eu-1 \
  --placement="label:rgw count-per-host:1" --port=80
```

## گام ۴: کلاستر ثانوی {#sec-05-4-4}

```bash
radosgw-admin realm pull --url=http://rgw-eu1.example.com:80 \
  --access-key=<AK> --secret=<SK>
radosgw-admin realm default --rgw-realm=gold
radosgw-admin period pull --url=http://rgw-eu1.example.com:80 --access-key=<AK> --secret=<SK>
radosgw-admin zone create --rgw-zonegroup=europe --rgw-zone=eu-2 \
  --endpoints=http://rgw-eu2.example.com:80 --access-key=<AK> --secret=<SK>
radosgw-admin period update --commit
ceph orch apply rgw gold-eu2 --realm=gold --zone=eu-2 \
  --placement="label:rgw count-per-host:1" --port=80
```

::: {.debug}
اگر `period update --commit` در کلاستر ثانوی با خطای «failed to commit period» یا «connection refused» شکست خورد، از کلاستر ثانوی با `curl http://rgw-eu1.example.com:80` دسترسی را بسنجید و مطمئن شوید کلیدهای system در `zone modify` درست قرار گرفته‌اند (`radosgw-admin zone get --rgw-zone=eu-1`). یک خطای رایج، نام میزبانی است که فقط در یکی از سایت‌ها قابل‌حل است.
:::

# پیکربندی خودکار با ماژول rgw {#sec-05-5}

از Reef به بعد، ماژول MGR به نام `rgw` (فرمان `ceph rgw`) همه‌ی گام‌های بالا را در دو دستور خلاصه می‌کند و با ارکستراتور هماهنگ است:

```yaml
# primary.yaml روی کلاستر اصلی
rgw_realm: gold
rgw_zonegroup: europe
rgw_zone: eu-1
placement:
  label: rgw
  count_per_host: 1
spec:
  rgw_frontend_port: 80
```

```bash
ceph mgr module enable rgw
ceph rgw realm bootstrap -i primary.yaml
ceph rgw realm tokens            # توکن base64 شامل realm، endpoint و کلیدها
```

```yaml
# secondary.yaml روی کلاستر ثانوی
rgw_zone: eu-2
rgw_realm_token: <token>
placement:
  label: rgw
spec:
  rgw_frontend_port: 80
```

```bash
ceph mgr module enable rgw
ceph rgw zone create -i secondary.yaml
```

::: {.tip}
روش خودکار برای ساختارهای ساده (یک zonegroup و دو یا چند zone) بسیار سریع‌تر و کم‌خطاتر است. برای ساختارهای پیچیده (چند zonegroup، placementهای سفارشی، مهاجرت از تک‌سایتی) روش دستی کنترل بیشتری می‌دهد. داشبورد Ceph هم از Tentacle یک wizard برای خودکارسازی multisite دارد.
:::

::: {.warn}
توکن realm حاوی کلید کاربر system است. همان مراقبتی که برای توکن bootstrap در RBD mirroring گفتیم، این‌جا هم لازم است.
:::

# بررسی وضعیت همگام‌سازی {#sec-05-6}

## sync status {#sec-05-6-1}

```bash
radosgw-admin sync status
```

خروجی نمونه در zone ثانوی:

```text
          realm 1c2d... (gold)
      zonegroup 7a8b... (europe)
           zone 9e0f... (eu-2)
   current time 2026-11-15T08:12:44Z
zonegroup features enabled: resharding
  metadata sync syncing
                full sync: 0/64 shards
                incremental sync: 64/64 shards
                metadata is caught up with master
      data sync source: 3d4e... (eu-1)
                        syncing
                        full sync: 0/128 shards
                        incremental sync: 128/128 shards
                        data is caught up with source
```

![سازوکار همگام‌سازی: zone مقصد datalog و bilog مبدأ را می‌خواند و اشیای تغییرکرده را با GET از endpoint مبدأ می‌کشد؛ فراداده از metadata log در master zone می‌آید](figures/ch05/f03_sync.png){#fig-05-f03_sync}

| عبارت در خروجی | معنا | اقدام |
|---|---|---|
| metadata is caught up with master | فراداده همگام است | — |
| data is caught up with source | داده‌ی همه‌ی shardها همگام است | — |
| behind shards: [..] | برخی shardهای داده عقب‌اند | اگر ماندگار است، `sync error list` و پهنای باند را بررسی کنید |
| oldest incremental change not applied | قدیمی‌ترین تغییر اعمال‌نشده | اختلاف زمانی را با now مقایسه کنید (RPO واقعی) |
| full sync: N/M shards | همگام‌سازی کامل در جریان است | طبیعی پس از راه‌اندازی یا resync |

## دستورهای تکمیلی {#sec-05-6-2}

```bash
radosgw-admin sync status --rgw-zone=eu-2
radosgw-admin metadata sync status
radosgw-admin data sync status --source-zone=eu-1
radosgw-admin bucket sync status --bucket=photos
radosgw-admin sync error list | head -50
radosgw-admin sync error trim
radosgw-admin period get | jq '.period_map.zonegroups[].zones[].name'
```

::: {.debug}
سه مشکل پرتکرار:

عقب‌ماندگی ماندگار در چند shard: معمولاً یک bucket خیلی پرتغییر یا شیء خراب. `bucket sync status` روی bucketهای پرترافیک و `sync error list` را ببینید.

خطاهای ۴۰۳ در لاگ همگام‌سازی: کلید system در یکی از zoneها با کاربر واقعی یکی نیست یا کاربر system حذف یا تعلیق شده است.

همگام‌سازی شروع نمی‌شود: endpointهای zone (`zone get`) به نشانی‌ای اشاره می‌کنند که از سایت دیگر در دسترس نیست (مثلاً `localhost` یا نام داخلی).
:::

# آزمون همگام‌سازی کاربر، bucket و شیء {#sec-05-7}

```bash
# روی کلاستر اصلی (master zone)
radosgw-admin user create --uid=tester --display-name="Multisite tester"
# روی کلاستر ثانوی، پس از چند ثانیه:
radosgw-admin user info --uid=tester        # کاربر همگام شده است
# با s3cmd یا aws-cli
aws --endpoint-url http://rgw-eu1.example.com s3 mb s3://ms-test
aws --endpoint-url http://rgw-eu1.example.com s3 cp ./report.pdf s3://ms-test/
aws --endpoint-url http://rgw-eu2.example.com s3 ls s3://ms-test/
# نوشتن در zone ثانوی و دیدن در اصلی (active-active)
aws --endpoint-url http://rgw-eu2.example.com s3 cp ./notes.txt s3://ms-test/
aws --endpoint-url http://rgw-eu1.example.com s3 ls s3://ms-test/
radosgw-admin bucket sync status --bucket=ms-test
```

::: {.try}
زمان رسیدن شیء به zone دیگر را اندازه بگیرید: در یک حلقه هر ثانیه یک شیء کوچک با زمان فعلی در نام در eu-1 بنویسید و در eu-2 فهرست بگیرید. سپس با ابزار `tc` روی میزبان RGW ثانوی ۲۰۰ میلی‌ثانیه تأخیر شبیه‌سازی کنید (`tc qdisc add dev eth0 root netem delay 200ms`) و اثرش را ببینید. یادتان نرود در پایان `tc qdisc del dev eth0 root` اجرا کنید.
:::

# از درون کد: لاگ‌ها و coroutineهای همگام‌سازی multisite {#sec-05-8}

## سه لاگ، سه لایه {#sec-05-8-1}

همگام‌سازی multisite در RGW **کششی (pull)** است. هر zone مقصد با REST، لاگ‌های zone مبدأ را می‌خواند و تغییرات را خودش اعمال می‌کند. سه نوع لاگ در این کار نقش دارند:

| لاگ | کجا ذخیره می‌شود | چه چیزی را ثبت می‌کند | پیش‌فرض‌ها (main) |
|---|---|---|---|
| bilog | کنار هر شارد bucket index (cls_rgw) | هر تغییر شیء در آن شارد | همراه complete_op |
| datalog | pool log zone | «این bucket shard تغییر کرده است» (نه خود شیء) | rgw_data_log_num_shards=128، rgw_data_log_window=30 |
| mdlog | اشیای `meta.log.*` (`rgw_mdlog.h`) | تغییر فراداده: کاربر، bucket، bucket instance | rgw_md_log_max_shards=64 |

![جریان کامل multisite. در zone مبدأ، هر PUT یا DELETE یک ورودی bilog در شارد index می‌سازد و یک ورودی datalog اعلام می‌کند که «آن شارد bucket تغییر کرده است». پنجره‌ی ۳۰ ثانیه‌ای datalog تغییرات پیاپی روی یک شارد را ادغام می‌کند تا لاگ منفجر نشود. ساخت bucket یا کاربر در mdlog ثبت می‌شود که فقط master zone آن را تولید می‌کند. در zone مقصد سه لایه coroutine کار می‌کنند: meta sync، data sync برای هر شارد datalog، و bucket sync برای هر شارد bucket که bilog را می‌خواند. لایه‌ی پایانی شیء را با fetch_remote_obj از مبدأ می‌کشد، محلی می‌نویسد و marker را در شیء وضعیت ذخیره می‌کند](figures/ch05/s01_logs.png){#fig-05-s01_logs}

## ماشین حالت data sync {#sec-05-8-2}

`rgw_data_sync_info` در `src/rgw/driver/rados/rgw_data_sync.h` سه حالت دارد: `StateInit = 0`، `StateBuildingFullSyncMaps = 1` و `StateSync = 2`. پیاده‌سازی بر پایه‌ی چارچوب coroutine خود RGW (`RGWCoroutine`) است. کلاس‌های اصلی در `rgw_data_sync.cc` این‌ها هستند: `RGWDataSyncShardCR` (حلقه‌ی هر شارد)، `RGWDataFullSyncShardCR`، `RGWDataIncSyncShardCR`، `RGWListRemoteDataLogShardCR` و برای لایه‌ی bucket، `RGWBucketShardIncrementalSyncCR`.

![ماشین حالت همگام‌سازی داده. ابتدا اشیای وضعیت ساخته می‌شوند (Init)، سپس همه‌ی bucketهای مبدأ در full-sync map فهرست می‌شوند (BuildingFullSyncMaps)، و پس از آن هر شارد datalog مستقل از بقیه ابتدا full sync و بعد incremental sync را با poll بیست‌ثانیه‌ای اجرا می‌کند. خطاها در error repo ثبت و بعداً دوباره تلاش می‌شوند. اگر چند RGW در zone مقصد باشند، هر شارد با یک lease دودقیقه‌ای فقط به یکی از آن‌ها سپرده می‌شود. trim لاگ‌های مبدأ هر ۲۰ دقیقه و فقط تا کمترین markerی انجام می‌شود که همه‌ی peerها به آن رسیده‌اند](figures/ch05/s02_states.png){#fig-05-s02_states}

```text
pseudocode: یک شارد datalog در zone مقصد (خلاصه‌ی این کتاب از rgw_data_sync.cc)
  loop:
    acquire lease(shard, rgw_sync_lease_period)          # 2min؛ فقط یک RGW
    if shard.state == full_sync:
        for bucket_shard in full_sync_map[shard] from marker:
            run bucket sync (full) ; persist marker
        shard.state = incremental
    else:
        entries = remote.list_datalog(shard, after=marker)
        for e in entries (dedup by bucket_shard):
            spawn bucket_incremental_sync(e.bucket_shard)  # حداکثر rgw_bucket_sync_spawn_window=20 هم‌زمان
              → read remote bilog after bucket marker
              → for op in bilog: fetch_remote_obj / remove
        persist marker ; if no entries: sleep rgw_data_sync_poll_interval (20s)
    on error: add to error repo for retry
```

| گزینه | پیش‌فرض | نکته‌ی SRE |
|---|---|---|
| rgw_run_sync_thread | true | روی RGWهای سمت کاربر می‌توان false کرد تا sync فقط روی RGWهای مخصوص اجرا شود |
| rgw_data_sync_poll_interval | 20 | حداقل تأخیر حالت آرام |
| rgw_meta_sync_poll_interval | 20 | برای فراداده |
| rgw_bucket_sync_spawn_window | 20 | موازی‌سازی bucket sync در هر شارد |
| rgw_sync_lease_period | 2_min | اگر RGW بمیرد، شارد پس از انقضا به RGW دیگری می‌رسد |
| rgw_sync_log_trim_interval | 20_min | peer عقب‌مانده جلوی trim را می‌گیرد و log pool رشد می‌کند |

::: {.warn}
یک zone مقصد خاموش یا عقب‌مانده جلوی trim لاگ‌های مبدأ را می‌گیرد، چون trim فقط تا کمترین marker پیش می‌رود. نتیجه رشد omap در pool log و هشدار `LARGE_OMAP_OBJECTS` است. zone حذف‌شده را حتماً از zonegroup هم حذف و period را commit کنید.
:::

::: {.debug}
فرمان‌های بررسی:
:::

```bash
radosgw-admin sync status
radosgw-admin data sync status --source-zone=us-east --shard-id=7
radosgw-admin bucket sync status --bucket=photos
radosgw-admin sync error list | jq '.[0].entries[:5]'
radosgw-admin datalog status ; radosgw-admin mdlog status
radosgw-admin bilog list --bucket=photos --max-entries=5
```

# multisite با عدد: shardهای datalog و mdlog، پنجره‌ی ادغام و trim {#sec-05-9}

این بخش چهار تابع کوچک را بررسی می‌کند که بار و تأخیر همگام‌سازی multisite را تعیین می‌کنند. ارجاع‌ها به کد main در نوامبر 2026 است. عددها با بازپیاده‌سازی پایتونی ceph_str_hash_linux (از src/common/ceph_hash.cc) حساب شده‌اند. نکته‌ی «بیت‌های پایین hash» در زیر نتیجه‌ی تحلیل و شبیه‌سازی خود ما است، نه گزاره‌ای از مستندات Ceph.

## کدام shard از datalog؟ {#sec-05-9-1}

::: {.algo #alg-05-1 title="انتخاب shard ‏datalog برای یک bucket shard" src="src/rgw/driver/rados/rgw_datalog.cc :: RGWDataChangesLog::choose_oid" complexity="O(طول نام bucket)"}
:::

```text
pseudocode
shift = max(bucket_shard_id, 0)
index = (ceph_str_hash_linux(bucket.name) + shift) mod rgw_data_log_num_shards     # پیش‌فرض 128
# بدون XOR و بدون عدد اول؛ shardهای یک bucket روی shardهای پشت‌سرهم datalog می‌افتند
```

**مثال عددی.** hash نام `photos` برابر 3484799263 است و 3484799263 mod 128 = 31. اگر bucket ‏11 shard ایندکس داشته باشد، تغییرات آن در shardهای 31 تا 41 از datalog ثبت می‌شوند. این پخش عمدی است و Casey Bodley در طراحی reshard چندسایتی آن را «خاصیت مهم مقیاس‌پذیری» نامیده است، چون چند RGW مقصد می‌توانند بار یک bucket پرتغییر را بین خود تقسیم کنند (هر shard ‏datalog با lease دودقیقه‌ای فقط در اختیار یک RGW است).

**نکته‌ی بیت‌های پایین.** در هر گام hash، مقدار `c<<4` مضرب 16 است. پس hash mod 16 فقط به نیبل بالای نویسه‌ها بستگی دارد (برای همه‌ی رقم‌های ASCII برابر 3، برای a تا o برابر 6 و برای p تا z برابر 7). بنابراین همه‌ی نام‌های هم‌طولی که فقط در رقم‌ها با هم فرق دارند، hash mod 16 یکسانی دارند. برای 1000 bucket با نام‌های `bucket-0000` تا `bucket-0999`، hash mod 16 همیشه 8 است و فقط 8 مقدار پایه (8، 24، …، 120) از 128 ممکن است. با 11 shard برای هر bucket، فقط 88 shard از 128 shard ‏datalog کار دارند و 40 shard همیشه خالی می‌مانند. همین تعداد bucket با نام تصادفی 12 نویسه‌ای هر 128 shard را پر می‌کند. ایندکس bucket این مشکل را ندارد، چون پیش از mod، بایت پایین را با XOR به بالا می‌برد و بر عدد اول 7877 تقسیم می‌کند. این نکته روی درستی همگام‌سازی اثری ندارد. فقط موازی‌سازی و پخش بار بین RGWهای مقصد را کم می‌کند.

![بالا: سهم shardهای datalog از 11000 bucket shard (1000 bucket با نام شماره‌دار و 11 shard برای هر کدام). فقط 88 shard از 128 shard کار دارند، در دسته‌هایی 11تایی که از 8، 24، …، 120 شروع می‌شوند. پایین: همین تعداد bucket با نام تصادفی که همه‌ی 128 shard را می‌پوشاند. خط‌چین میانگین ایده‌آل، یعنی حدود 86 bucket shard برای هر shard ‏datalog است. شبیه‌سازی ما، بر پایه‌ی بازپیاده‌سازی choose_oid](figures/ch05/f06_dlshard.png){#fig-05-f06_dlshard}

## پنجره‌ی ادغام datalog {#sec-05-9-2}

::: {.algo #alg-05-2 title="افزودن ورودی datalog با پنجره و renew" src="src/rgw/driver/rados/rgw_datalog.cc :: RGWDataChangesLog::add_entry، renew_entries، renew_run" complexity="O(1) برای هر نوشتن و O(تعداد bucket shard فعال) برای هر renew"}
:::

```text
pseudocode
add_entry(bs):
    if watch روی sem-set سالم نیست: push(entry) ; return        # مسیر ایمن، بدون بهینه‌سازی
    status = change_status[bs]
    if now < status.cur_expiration:                       # در 30 ثانیه‌ی اخیر ثبت شده
        cur_cycle.add(bs) ; sem_set[index] += key ; return
    if status.pending: منتظر push جاری بمان ; return
    status.pending = true ; sent = now
    push(entry{key=bs, gen, timestamp=now})
    status.cur_expiration = sent + rgw_data_log_window      # از زمان شروع، نه پایان
renew_run: هر window × 3/4 ثانیه (با 30 → 22 ثانیه، تقسیم صحیح)
    برای هر bs در cur_cycle: push(entry) ; cur_expiration = now + window ; sem_set −= key
```

**مثال عددی.** فرض کنید از ثانیه‌ی 0 تا 120 هر 10 میلی‌ثانیه یک PUT روی یک bucket shard انجام شود (12000 نوشتن). ورودی‌های datalog فقط در ثانیه‌های 0، 22، 44، 66، 88 و 110 ثبت می‌شوند: شش ورودی به جای 12000. اگر نوشتن‌ها پراکنده باشند (ثانیه‌های 0، 5، 40، 41 و 100)، ورودی‌ها در 0، 22 (renew برای نوشتن ثانیه‌ی 5)، 44 (renew برای 40 و 41) و 100 ثبت می‌شوند. چون بین 44 و 100 نوشتنی نیست، چیزی برای renew در 66 و 88 نمانده است. هر ورودی datalog فقط یعنی «این bucket shard را دوباره نگاه کن». جزئیات تغییر در bilog هست و مقصد آن را می‌خواند. پس ادغام چیزی را گم نمی‌کند، فقط حداکثر حدود یک پنجره به تأخیر کشف تغییر اضافه می‌کند. مجموعه‌ی شمارنده‌ی sem-set و مسیر «watch سالم نیست» در کد main وجود دارند و هدفشان این است که اگر RGW پیش از renew بمیرد، کلیدهای در انتظار گم نشوند. نسخه‌های قدیمی‌تر این سازوکار را نداشتند. پیش از تکیه بر آن، کد نسخه‌ی خود را بررسی کنید.

![بالا: یک bucket shard پرکار با 12000 نوشتن در 120 ثانیه فقط شش ورودی datalog تولید می‌کند. اولی در لحظه‌ی نخستین نوشتن ثبت می‌شود و بقیه در تیک‌های 22 ثانیه‌ای renew. پایین: با نوشتن پراکنده، renew فقط وقتی انجام می‌شود که در پنجره‌ی قبل نوشتنی مانده باشد. نوشتن ثانیه‌ی 100 پس از انقضای پنجره بلافاصله ورودی می‌سازد](figures/ch05/f07_window.png){#fig-05-f07_window}

![درخت تصمیم add_entry در main. ردیف اول مسیر ایمن را نشان می‌دهد: اگر watch روی sem-set قطع باشد، ورودی بی‌درنگ نوشته می‌شود. ردیف دوم ادغام در پنجره و انتظار برای push در جریان است. ردیف سوم push واقعی و چرخه‌ی renew است که پنجره را تمدید می‌کند و شمارنده‌ها را کم می‌کند](figures/ch05/f09_addentry.png){#fig-05-f09_addentry}

## کدام shard از mdlog؟ {#sec-05-9-3}

::: {.algo #alg-05-3 title="انتخاب shard ‏mdlog برای تغییر فراداده" src="src/rgw/driver/rados/rgw_sal_rados.cc (hash_key = section + \":\" + key)؛ src/rgw/driver/rados/rgw_metadata.cc :: rgw_shard_name، RGWMetadataLog::add_entry" complexity="O(طول کلید)"}
:::

```text
pseudocode
hash_key = section + ":" + key            # مثلاً "user:alice" یا "bucket:photos"
shard = ceph_str_hash_linux(hash_key) mod rgw_md_log_max_shards     # پیش‌فرض 64
oid = "meta.log." + period_id + "." + shard
```

**مثال عددی.** `user:alice` به shard ‏52 می‌رود، `bucket:photos` به 50 و `bucket.instance:photos:a1b2c3d4.4567.1` به 28. mdlog را فقط master zone تولید می‌کند و هر period لاگ خودش را دارد. همان نکته‌ی بیت‌های پایین اینجا شدیدتر است، چون 64 هم توان 2 است و جابه‌جایی shard هم وجود ندارد. 1000 کلید `bucket:bucket-0000` تا `bucket:bucket-0999` فقط در 4 shard (9، 25، 41 و 57) می‌نشینند، هر کدام حدود 250 کلید. در عمل نتیجه این است که meta sync اولیه‌ی چنین نام‌هایی روی 4 shard متمرکز می‌شود، به جای اینکه بین 64 shard پخش شود.

![چپ: shard ‏mdlog برای 1000 کلید bucket با نام شماره‌دار که فقط چهار shard را اشغال می‌کنند. راست: 1000 نام تصادفی که هر 64 shard را می‌پوشانند، با 7 تا 31 کلید در هر shard. محاسبه با بازپیاده‌سازی rgw_shard_name](figures/ch05/f08_mdlog.png){#fig-05-f08_mdlog}

## trim لاگ‌ها: کمینه‌ی markerها روی همه‌ی peerها {#sec-05-9-4}

::: {.algo #alg-05-4 title="trim ‏datalog بر پایه‌ی کمترین marker پایدار" src="src/rgw/driver/rados/rgw_trim_datalog.cc :: DataLogTrimCR، take_min_markers، get_stable_marker" complexity="O(peers × shards)"}
:::

```text
pseudocode
هر rgw_sync_log_trim_interval (20 دقیقه):
    status[p] = REST GET /admin/log/?type=data&status از هر peer
    اگر حتی یک peer پاسخ ندهد: این دور trim نکن
    for shard i:
        stable(p) = state == FullSync ? next_step_marker : marker
        min_i = min_p stable(p)
        if min_i > last_trim[i]: trim(shard i, up to min_i) ; last_trim[i] = min_i
```

**مثال نمادین.** فرض کنید در shard ‏5، peer ‏A تا marker ‏m120 و peer ‏B (که هنوز در full sync است) تا next_step_marker برابر m087 جلو رفته‌اند و trim قبلی تا m050 بوده است. پس shard ‏5 تا m087 کوتاه می‌شود. ورودی‌های m088 تا m120 می‌مانند تا B هم به آن‌ها برسد. markerهای واقعی به نوع backend ‏(cls_log یا FIFO) بستگی دارند و m120 فقط نماد است. پیامد عملی این است که «همه‌ی peerها باید پاسخ دهند». اگر یک zone مدت طولانی از دسترس خارج باشد، datalog و bilogهای zone مبدأ کوتاه نمی‌شوند و pool لاگ رشد می‌کند. پیش از حذف دائمی یک zone، آن را از zonegroup بیرون بیاورید و period را commit کنید.

![چرخه‌ی trim ‏datalog. هر 20 دقیقه وضعیت همگام‌سازی از همه‌ی peerها گرفته می‌شود. اگر یکی پاسخ ندهد، آن دور trim انجام نمی‌شود. برای هر shard کمترین marker پایدار حساب می‌شود (در full sync، ‏next_step_marker) و فقط وقتی trim انجام می‌شود که از trim قبلی جلوتر باشد. ردیف پایین یک مثال نمادین است](figures/ch05/f10_trim.png){#fig-05-f10_trim}

# failover و failback {#sec-05-10}

![تصمیم‌گیری هنگام از دست رفتن master zone: در خرابی کوتاه صبر کنید؛ در خرابی طولانی zone دیگری را master کنید](figures/ch05/f05_failover.png){#fig-05-f05_failover}

## وقتی master zone از دسترس خارج می‌شود {#sec-05-10-1}

در خرابی master zone، zoneهای دیگر همچنان **داده** را می‌پذیرند و سرویس S3 برای bucketهای موجود ادامه دارد. اما عملیات فراداده‌ای که به master نیاز دارند (ساخت کاربر یا bucket، تغییر سیاست) با خطا مواجه می‌شوند. اگر خرابی طولانی است، zone ثانوی را master کنید:

```bash
# روی کلاستر eu-2
radosgw-admin zone modify --rgw-zone=eu-2 --master --default
radosgw-admin period update --commit
ceph orch restart rgw.gold-eu2
```

## بازگشت master قدیمی {#sec-05-10-2}

وقتی eu-1 برگشت، باید period جدید را از master فعلی بگیرد تا بفهمد دیگر master نیست:

```bash
# روی کلاستر eu-1
radosgw-admin realm pull --url=http://rgw-eu2.example.com:80 --access-key=<AK> --secret=<SK>
radosgw-admin period pull --url=http://rgw-eu2.example.com:80 --access-key=<AK> --secret=<SK>
ceph orch restart rgw.gold-eu1
radosgw-admin sync status
# اگر می‌خواهید master را برگردانید، پس از همگام شدن:
radosgw-admin zone modify --rgw-zone=eu-1 --master --default
radosgw-admin period update --commit
```

::: {.warn}
اگر هر دو zone هم‌زمان خودشان را master بدانند (مثلاً به دلیل قطع شبکه بین سایت‌ها و ارتقای عجولانه)، دو تاریخچه‌ی period متفاوت ساخته می‌شود. پیش از ارتقای zone ثانوی، مطمئن شوید master قدیمی واقعاً از دسترس خارج است یا RGWهایش متوقف شده‌اند، و پس از بازگشت آن **قبل از** هر تغییری period را pull کنید.
:::

## یک runbook حداقلی {#sec-05-10-3}

1. تأیید خرابی master از دو مسیر مستقل (پایش و تماس با تیم سایت).
2. اعلام وضعیت و توقف تغییرات فراداده‌ای غیرضروری.
3. ارتقای zone ثانوی به master و commit period.
4. به‌روزرسانی DNS یا GSLB تا کلاینت‌ها به endpoint سالم بروند.
5. پس از بازگشت سایت اصلی: pull period، بررسی `sync status` تا caught up، و تصمیم درباره‌ی بازگرداندن master.
6. ثبت زمان‌ها و درس‌ها در لاگ حادثه.

# sync policy: کنترل دقیق همگام‌سازی {#sec-05-11}

از Octopus، **sync policy** امکان می‌دهد به‌جای «همه‌ی bucketها در همه‌ی zoneها»، تعیین کنید چه چیزی از کجا به کجا برود. سیاست‌ها در قالب گروه، flow (جریان بین zoneها) و pipe (کدام bucketها) تعریف می‌شوند و در سطح zonegroup یا bucket اعمال می‌شوند.

```bash
# همه‌ی bucketها به‌طور پیش‌فرض «مجاز» اما غیرفعال
radosgw-admin sync group create --group-id=global --status=allowed
radosgw-admin sync group flow create --group-id=global --flow-id=eu-mesh \
  --flow-type=symmetrical --zones=eu-1,eu-2
radosgw-admin sync group pipe create --group-id=global --pipe-id=all \
  --source-zones='*' --source-bucket='*' --dest-zones='*' --dest-bucket='*'
radosgw-admin period update --commit
# فعال کردن همگام‌سازی فقط برای یک bucket
radosgw-admin sync group create --bucket=critical-data --group-id=critical --status=enabled
radosgw-admin sync group pipe create --bucket=critical-data --group-id=critical \
  --pipe-id=p1 --source-zones='*' --dest-zones='*'
radosgw-admin sync info --bucket=critical-data
```

| وضعیت گروه | معنا |
|---|---|
| enabled | همگام‌سازی انجام می‌شود |
| allowed | مجاز است اما فقط اگر سیاست سطح پایین‌تر (bucket) فعالش کند |
| forbidden | ممنوع؛ سیاست‌های سطح bucket هم نمی‌توانند فعالش کنند |

::: {.tip}
یک الگوی رایج: در سطح zonegroup وضعیت `allowed` و در سطح bucket فقط برای bucketهای حساس `enabled`. این کار پهنای باند بین‌سایتی را برای bucketهای موقت یا قابل بازتولید هدر نمی‌دهد.
:::

# archive zone {#sec-05-12}

**archive zone** یک zone ویژه است که همه‌ی نسخه‌های همه‌ی اشیاء را نگه می‌دارد، حتی اگر در zoneهای دیگر حذف یا بازنویسی شوند. bucketها در archive zone خودکار versioning دارند. این راهی برای حفاظت در برابر حذف تصادفی یا مخرب بدون تحمیل versioning به کاربران است.

```bash
radosgw-admin zone create --rgw-zonegroup=europe --rgw-zone=eu-archive \
  --endpoints=http://rgw-arc.example.com:80 --tier-type=archive \
  --access-key=<AK> --secret=<SK>
radosgw-admin period update --commit
```

# resharding در multisite {#sec-05-13}

پیش از Reef، resharding پویا در multisite پشتیبانی نمی‌شد و reshard دستی هم همگام‌سازی bucket را مختل می‌کرد. از Reef، zonegroup feature به نام `resharding` این امکان را می‌دهد که هر zone مستقل bucketهایش را reshard کند بدون قطع تکثیر. طبق مستندات zone features، این قابلیت فقط وقتی باید فعال شود که همه‌ی zoneها به نسخه‌ی پشتیبان ارتقا یافته باشند:

```bash
radosgw-admin zonegroup modify --rgw-zonegroup=europe --enable-feature=resharding
radosgw-admin period update --commit
radosgw-admin sync status | grep features
```

# کارایی و طراحی {#sec-05-14}

- **RGW اختصاصی همگام‌سازی:** با گزینه‌ی `rgw_run_sync_thread` می‌توانید همگام‌سازی را روی نمونه‌های خاصی اجرا کنید و نمونه‌های رو به کاربر را از بار آن آزاد کنید. endpointهای zone را روی نمونه‌های همگام‌ساز (یا load balancer آن‌ها) تنظیم کنید.
- **pool لاگ سریع:** datalog و bilog در pool لاگ نوشته می‌شوند؛ این pool را روی SSD بگذارید.
- **تعداد shardهای datalog:** پیش‌فرض ۱۲۸ است و موازی‌سازی همگام‌سازی داده را تعیین می‌کند.
- **پایش عقب‌ماندگی:** صادرکننده‌ی Prometheus در MGR و آمار perf کلاینت RGW معیارهای همگام‌سازی دارند. یک هشدار بر اساس «قدیمی‌ترین تغییر اعمال‌نشده» تعریف کنید.
- **ظرفیت لاگ:** اگر یک zone مدتی طولانی قطع باشد، لاگ‌های تغییرات در zone دیگر انباشته می‌شوند. trim خودکار لاگ‌ها فقط وقتی انجام می‌شود که همه‌ی zoneها آن تغییرات را دریافت کرده باشند.

::: {.deep}
RPO در multisite ثابت نیست؛ به نرخ تغییر، پهنای باند، تأخیر و تعداد اشیای کوچک بستگی دارد. اشیای کوچک بسیار زیاد (مثلاً میلیون‌ها فایل چندکیلوبایتی) گلوگاه CPU و درخواست‌اند، نه پهنای باند. برای برآورد واقعی، با بار نمونه‌ی خودتان آزمون کنید و «oldest incremental change not applied» را در اوج بار بسنجید.
:::

# تکمیلی و به‌روز {#sec-05-15}

- **خودکارسازی با `ceph rgw`** و wizard داشبورد (Tentacle) راه‌اندازی را به چند دقیقه رسانده است.
- **zone features:** علاوه بر `resharding`، قابلیت‌هایی مثل `compress-encrypted` (Reef) و `notification_v2` (Squid) با سازوکار zone feature به‌صورت هماهنگ در همه‌ی zoneها فعال می‌شوند.
- **OIDC در multisite:** در Umbrella پشتیبانی از OIDC در محیط چندسایتی اضافه شده است.
- **اصلاح‌های درستی همگام‌سازی:** یادداشت‌های Umbrella اصلاح‌های متعددی را فهرست می‌کنند، از جمله حلقه‌ی بی‌پایان full sync، خطای segfault هنگام راه‌اندازی، درخواست‌های forward‌شده با UNSIGNED-PAYLOAD، قفل‌گذاری full sync در سطح bucket و تغییر نام zonegroup. اگر روی نسخه‌های قدیمی‌تر مشکلات همگام‌سازی دارید، ارتقا را جدی بگیرید.
- **cloud sync module:** یک zone با `--tier-type=cloud` می‌تواند داده را به یک سرویس S3 بیرونی تکثیر کند.

# جمع‌بندی و مرور {#sec-05-16}

## خلاصه‌ی فصل {#sec-05-16-1}

::: {.summary title="نکته‌های کلیدی"}

- realm فضای نام سراسری است؛ zonegroup واحد تکثیر داده؛ zone یک کلاستر؛ period نسخه‌ی پیکربندی.
- فراداده از master zone پخش می‌شود؛ داده بین zoneهای یک zonegroup به‌صورت ناهمگام و active-active تکثیر می‌شود.
- multisite نسخه‌ی ۲ همگام‌سازی را درون radosgw برده و agent قدیمی Hammer را حذف کرده است.
- راه‌اندازی دستی با `radosgw-admin` یا خودکار با `ceph rgw realm bootstrap` و `ceph rgw zone create`.
- `sync status`، `bucket sync status` و `sync error list` ابزارهای اصلی پایش‌اند.
- failover یعنی master کردن zone دیگر و commit period؛ پس از بازگشت، period را pull کنید.
- sync policy، archive zone و zone feature `resharding` multisite را منعطف‌تر کرده‌اند.

:::

## اشتباهات رایج {#sec-05-16-2}

- endpointهایی که فقط از یک سایت قابل‌دسترسی‌اند.
- ساختن zone جدید به‌جای تغییر نام zone پیش‌فرض دارای داده.
- نگه داشتن کلید کاربر system در اسکریپت‌ها و مخازن.
- ارتقای عجولانه‌ی zone ثانوی به master در قطع شبکه‌ی موقت.
- فعال کردن zone feature پیش از ارتقای همه‌ی zoneها.
- نادیده گرفتن عقب‌ماندگی تا وقتی کاربران گزارش دهند.

## تمرین عملی {#sec-05-16-3}

1. دو کلاستر تک‌نودی بسازید و multisite را یک‌بار دستی و یک‌بار با `ceph rgw realm bootstrap` راه بیندازید. زمان و تعداد گام‌ها را مقایسه کنید.
2. هزار شیء در zone اصلی بنویسید و با `sync status` و `bucket sync status` روند همگام‌سازی را ثبت کنید.
3. RGWهای zone اصلی را متوقف کنید، در zone ثانوی شیء بنویسید و ساخت bucket را امتحان کنید. پیام خطا را توضیح دهید. سپس failover کامل انجام دهید.
4. یک sync policy بسازید که فقط bucketی با نام `critical-*` همگام شود و نشان دهید bucketهای دیگر همگام نمی‌شوند.
5. یک archive zone اضافه کنید، شیئی را در zone اصلی حذف کنید و نسخه‌ی آن را در archive zone پیدا کنید.

## پرسش‌های مرور {#sec-05-16-4}

1. تفاوت نقش zonegroup و realm در تکثیر داده و فراداده چیست؟
2. period چیست و چرا پس از تغییرات ساختاری باید commit شود؟
3. سه تفاوت اصلی multisite نسخه‌ی ۲ با پیکربندی federated در Hammer کدام‌اند؟
4. چرا ساخت bucket در zone غیر master هنگام از دست رفتن master شکست می‌خورد اما نوشتن شیء نه؟
5. کاربر system چه نقشی دارد و چرا باید به‌شدت حفاظت شود؟
6. در خروجی `sync status` عبارت «oldest incremental change not applied» چه اطلاعاتی می‌دهد؟
7. گام‌های failover و بازگرداندن master قدیمی را بنویسید.
8. تفاوت وضعیت‌های enabled، allowed و forbidden در sync policy چیست؟
9. archive zone چه مشکلی را حل می‌کند؟
10. چرا resharding پیش از Reef در multisite مشکل‌ساز بود و امروز چطور حل شده است؟

## منابع این فصل {#sec-05-16-5}

- مستندات Ceph — Multi-Site: https://docs.ceph.com/en/latest/radosgw/multisite/
- مستندات Ceph — Multisite Sync Policy: https://docs.ceph.com/en/latest/radosgw/multisite-sync-policy/
- مستندات Ceph — Zone Features: https://docs.ceph.com/en/latest/radosgw/zone-features/
- مستندات Ceph — ماژول rgw در MGR: https://docs.ceph.com/en/latest/mgr/rgw/
- مستندات Ceph — Archive Sync Module: https://docs.ceph.com/en/latest/radosgw/archive-sync-module/
- مستندات Ceph — Cloud Sync Module: https://docs.ceph.com/en/latest/radosgw/cloud-sync-module/
- مستندات cephadm — سرویس RGW در multisite: https://docs.ceph.com/en/latest/cephadm/services/rgw/
- یادداشت‌های انتشار Umbrella (بخش Multisite): https://docs.ceph.com/en/latest/releases/umbrella/
