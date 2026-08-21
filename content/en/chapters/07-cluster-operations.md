---
chapter: 7
id: ch07
title: Operating and Managing a Ceph Cluster
part: main
lang: en
translation: pending
---

# پیش از شروع {#sec-07-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-07-1-1}

ساختن کلاستر کار یک روز است؛ راهبری آن کار چند سال. این فصل کارهای روزمره‌ی اپراتور را پوشش می‌دهد: مدیریت سرویس‌ها، پیکربندی، بزرگ و کوچک کردن کلاستر، تعویض دیسک، ارتقای نسخه و کنترل بار بازیابی. کتاب ۲۰۱۹ این کارها را با ویرایش دستی `ceph.conf`، `ceph-deploy` و unitهای systemd بسته‌ای انجام می‌داد. در یک کلاستر امروزی با cephadm، بیشتر این کارها اعلانی (declarative) شده‌اند: شما وضعیت مطلوب را می‌گویید و orchestrator آن را برقرار نگه می‌دارد.

- مدیریت سرویس در cephadm چه لایه‌هایی دارد و systemd کجای آن است؟
- پیکربندی امروز کجا نگه‌داری می‌شود و چرا `ceph.conf` تقریباً خالی است؟
- چطور گره، OSD و MON اضافه یا حذف کنیم؟
- روال امن تعویض دیسک خراب چیست؟
- ارتقای نسخه را چطور بدون قطعی و با کنترل ریسک انجام دهیم؟
- بازیابی و backfill را چطور کند یا تند کنیم، به‌ویژه با زمان‌بند mClock؟

# مدیریت سرویس‌ها {#sec-07-2}

## لایه‌های کنترل {#sec-07-2-1}

![لایه‌های مدیریت daemon در cephadm: از دستور ceph orch تا کانتینر روی میزبان](figures/ch07/f01_layers.png){#fig-07-f01_layers}

در cephadm، هر daemon یک کانتینر است که با یک unit systemd اجرا می‌شود. orchestrator (ماژول cephadm در MGR) از طریق SSH روی میزبان‌ها daemon می‌سازد، حذف می‌کند یا راه‌اندازی مجدد می‌کند. شما معمولاً فقط با لایه‌ی بالا کار می‌کنید:

```bash
ceph orch ls                          # سرویس‌ها و تعداد daemonهای مطلوب/در حال اجرا
ceph orch ps                          # همه‌ی daemonها
ceph orch ps --daemon-type osd --hostname ceph-node2
ceph orch ls --export > cluster-specs.yaml   # پشتیبان از وضعیت مطلوب
```

## شروع، توقف و راه‌اندازی مجدد {#sec-07-2-2}

```bash
ceph orch restart rgw.objstore            # همه‌ی daemonهای یک سرویس، یکی‌یکی
ceph orch daemon restart osd.3
ceph orch daemon stop mds.fs01.ceph-node3.xyzabc
ceph orch daemon start mds.fs01.ceph-node3.xyzabc
ceph orch daemon redeploy mgr.ceph-node1.abcdef   # ساخت دوباره‌ی کانتینر (مثلاً پس از تغییر image)
```

## systemd در پشت صحنه {#sec-07-2-3}

روی هر میزبان، unitهای systemd نام‌گذاری مشخصی دارند که شامل fsid کلاستر است. این نام‌گذاری اجازه می‌دهد چند کلاستر روی یک میزبان (مثلاً در آزمایشگاه) بدون تداخل اجرا شوند.

```bash
FSID=$(ceph fsid)
systemctl list-units "ceph-${FSID}*"
systemctl status ceph-${FSID}@osd.3.service
sudo systemctl stop ceph-${FSID}.target      # توقف همه‌ی daemonهای این کلاستر روی این میزبان
sudo systemctl start ceph-${FSID}.target
journalctl -u ceph-${FSID}@osd.3 --since "1 hour ago"
cephadm logs --name osd.3                  # همان لاگ از طریق cephadm
```

::: {.warn}
اگر daemon را مستقیم با systemctl متوقف کنید، orchestrator از آن خبر ندارد و ممکن است در چرخه‌ی بعدی تطبیق وضعیت آن را دوباره راه بیندازد یا گزارش خطا بدهد. برای کارهای برنامه‌ریزی‌شده روی کل میزبان، از **حالت نگهداری** استفاده کنید (پایین‌تر). systemctl را برای اشکال‌زدایی محلی یا وقتی MGR در دسترس نیست نگه دارید.
:::

# پیکربندی {#sec-07-3}

## پایگاه پیکربندی متمرکز {#sec-07-3-1}

![منابع پیکربندی و ترتیب اولویت آن‌ها؛ مقدار مؤثر هر daemon را با ceph config show ببینید](figures/ch07/f02_config.png){#fig-07-f02_config}

از Mimic، پیکربندی کلاستر در **پایگاه پیکربندی MON** نگه داشته می‌شود و `ceph.conf` روی میزبان‌ها فقط حداقل اطلاعات لازم برای پیدا کردن MONها را دارد (fsid و mon_host). کتاب ۲۰۱۹ هنوز افزودن بخش‌های `[mon.a]` و `[osd.0]` به `ceph.conf` را آموزش می‌داد؛ این کار امروز نه لازم است و نه توصیه می‌شود.

```bash
cat /etc/ceph/ceph.conf                      # معمولاً چند خط
ceph config dump                              # همه‌ی تنظیمات غیرپیش‌فرض
ceph config get osd osd_memory_target
ceph config set osd osd_memory_target 6442450944
ceph config set osd.12 osd_memory_target 8589934592    # فقط یک OSD
ceph config set osd/class:ssd osd_memory_target 8589934592   # همه‌ی OSDهای SSD (mask)
ceph config set client.rgw.objstore rgw_max_concurrent_requests 2048
ceph config show osd.3 | grep memory_target   # مقدار مؤثر در daemon در حال اجرا
ceph config help osd_memory_target
ceph config log 10                            # تاریخچه‌ی تغییرات
```

::: {.tip}
دستور `ceph config log` و `ceph config reset <n>` امکان برگرداندن تغییرات پیکربندی را می‌دهند. قبل از هر تغییر بزرگ خروجی `ceph config dump` را در کنترل نسخه (Git) ذخیره کنید تا بعداً بتوانید تفاوت‌ها را مقایسه کنید.
:::

## تغییر موقت در زمان اجرا {#sec-07-3-2}

```bash
ceph tell osd.* config set debug_osd 10/10      # موقتاً، تا راه‌اندازی مجدد
ceph tell osd.* config set debug_osd 1/5        # بازگرداندن
ceph daemon osd.3 config show                    # از طریق admin socket، روی همان میزبان (درون shell cephadm)
```

::: {.note}
`ceph tell` از طریق شبکه به daemon پیام می‌فرستد؛ `ceph daemon` از طریق admin socket محلی کار می‌کند و فقط روی میزبان همان daemon (در cephadm، داخل `cephadm shell --name osd.3`) در دسترس است. وقتی daemon به دلیل گیر کردن به پیام‌های شبکه پاسخ نمی‌دهد، admin socket معمولاً هنوز جواب می‌دهد.
:::

# بزرگ و کوچک کردن کلاستر {#sec-07-4}

## scale-up یا scale-out؟ {#sec-07-4-1}

![دو راه افزایش ظرفیت: دیسک بیشتر در همان گره‌ها یا گره‌های بیشتر](figures/ch07/f05_scale.png){#fig-07-f05_scale}

| معیار | scale-up (گره‌های پرتراکم‌تر) | scale-out (گره‌های بیشتر) |
|---|---|---|
| هزینه‌ی هر ترابایت | معمولاً کمتر | کمی بیشتر (CPU، شبکه، رک) |
| دامنه‌ی خرابی | بزرگ؛ از دست رفتن یک گره بخش بزرگی از داده را بازیابی می‌کند | کوچک‌تر؛ بازیابی سریع‌تر و کم‌اثرتر |
| کارایی | CPU و شبکه‌ی هر گره گلوگاه می‌شود | خطی‌تر با افزایش گره‌ها |
| محدودیت | حداقل تعداد گره برای EC و دامنه‌ی خرابی | فضای رک، سوئیچ و برق |

::: {.tip}
یک قاعده‌ی عملی: هیچ گره‌ای نباید بیش از حدود ۱۰ تا ۱۵ درصد ظرفیت خام کلاستر را نگه دارد. همچنین فضای آزاد کلاستر باید آن‌قدر باشد که پس از از دست رفتن بزرگ‌ترین دامنه‌ی خرابی (گره یا رک)، OSDها از نسبت `nearfull` عبور نکنند.
:::

## افزودن گره و OSD {#sec-07-4-2}

```bash
# روی گره تازه: نصب podman، تنظیم زمان (chrony) و کلید SSH کلاستر
ssh-copy-id -f -i /etc/ceph/ceph.pub root@ceph-node5
ceph orch host add ceph-node5 192.168.10.15 --labels osd
ceph orch device ls ceph-node5 --refresh
# اگر spec OSD شما (مثلاً all-available-devices یا یک spec با فیلتر) فعال است، OSDها خودکار ساخته می‌شوند
ceph orch ls osd
ceph -s
```

::: {.warn}
افزودن ناگهانی تعداد زیادی OSD باعث جابه‌جایی گسترده‌ی PGها می‌شود. در کلاستر شلوغ قبل از افزودن، پرچم‌های `norebalance` و `nobackfill` را بگذارید، همه‌ی OSDها را بسازید و بعد پرچم‌ها را بردارید تا داده یک بار و نه چند بار جابه‌جا شود. ابزارهایی مانند ماژول **balancer** پس از اتمام backfill، توزیع را یکنواخت می‌کنند.
:::

```bash
ceph osd set norebalance && ceph osd set nobackfill
ceph orch apply -i osd-spec.yaml
ceph osd tree
ceph osd unset nobackfill && ceph osd unset norebalance
```

## افزودن MON و MGR {#sec-07-4-3}

در cephadm، تعداد و محل MONها با spec سرویس `mon` تعیین می‌شود:

```yaml
service_type: mon
placement:
  count: 5
  label: mon
```

```bash
ceph orch host label add ceph-node5 mon
ceph orch apply -i mon-spec.yaml
ceph mon stat
ceph quorum_status -f json-pretty | jq '.quorum_names'
```

::: {.note}
تعداد MONها را فرد نگه دارید (۳ یا ۵). پنج MON تحمل از دست رفتن دو MON را می‌دهد؛ بیشتر از ۵ معمولاً فقط سربار اجماع را زیاد می‌کند. MONها را در دامنه‌های خرابی مختلف (رک یا اتاق) قرار دهید.
:::

## حذف OSD {#sec-07-4-4}

```bash
ceph osd safe-to-destroy osd.9        # آیا بدون از دست رفتن داده می‌توان حذف کرد؟
ceph osd ok-to-stop osd.9             # آیا توقف موقت باعث از دسترس رفتن PG می‌شود؟
ceph orch osd rm 9                    # تخلیه و حذف
ceph orch osd rm status
```

`ceph orch osd rm` ابتدا وزن OSD را صفر می‌کند، صبر می‌کند تا همه‌ی PGها جای دیگری بروند، سپس daemon را حذف و OSD را از CRUSH و نقشه پاک می‌کند. با `--zap` دیسک هم پاک‌سازی (LVM و partitionها) می‌شود تا دوباره قابل استفاده باشد.

## حذف یک میزبان کامل {#sec-07-4-5}

```bash
ceph orch host drain ceph-node5       # همه‌ی daemonها را تخلیه می‌کند، از جمله OSDها
ceph orch osd rm status
ceph orch ps ceph-node5               # باید خالی شود
ceph orch host rm ceph-node5
```

::: {.warn}
`--offline --force` در `host rm` فقط برای میزبانی است که برای همیشه از دست رفته است؛ این گزینه OSDهای آن را بدون تخلیه حذف می‌کند و تنها وقتی امن است که داده‌ی آن‌ها از روی نسخه‌های دیگر قابل بازسازی باشد.
:::

# تعویض دیسک خراب {#sec-07-5}

![روال امن تعویض دیسک: اول بازیابی، بعد بررسی safe-to-destroy، سپس حذف با حفظ id و تعویض فیزیکی](figures/ch07/f03_replace.png){#fig-07-f03_replace}

وقتی دیسکی خراب می‌شود، OSD آن down می‌شود و پس از `mon_osd_down_out_interval` (پیش‌فرض ۱۰ دقیقه) به‌صورت خودکار out می‌شود و بازیابی شروع می‌شود. روال پیشنهادی:

```bash
ceph health detail
ceph osd tree down
ceph device ls-by-daemon osd.7                 # شناسه‌ی دستگاه و میزبان
ceph device light on <devid> ident             # روشن کردن چراغ شناسایی (اگر سخت‌افزار پشتیبانی کند)
# صبر تا داده بازیابی شود
ceph -s
ceph osd safe-to-destroy osd.7
ceph orch osd rm 7 --replace --zap
ceph orch osd rm status
# پس از تعویض فیزیکی دیسک
ceph orch device ls ceph-node2 --refresh
ceph osd tree | grep osd.7
```

::: {.deep}
گزینه‌ی `--replace` به‌جای حذف کامل، OSD را در وضعیت `destroyed` نگه می‌دارد؛ id و جایگاهش در CRUSH حفظ می‌شود. وقتی spec OSD دیسک تازه‌ی همان میزبان را می‌بیند، OSD جدید را با همان id می‌سازد. مزیتش این است که نقشه‌ی CRUSH تغییر نمی‌کند و داده‌ی کمتری جابه‌جا می‌شود.
:::

::: {.tip}
مدیریت سلامت دستگاه‌ها (`ceph device`) داده‌ی SMART دیسک‌ها را جمع می‌کند و می‌تواند خرابی را پیش‌بینی کند. با `ceph device monitoring on` و `ceph device get-health-metrics <devid>` آن را بررسی کنید. اگر `mgr/devicehealth/self_heal` فعال باشد، OSDهای دیسک‌هایی که احتمال خرابی بالایی دارند پیش‌دستانه out می‌شوند.
:::

# ارتقای نسخه {#sec-07-6}

![ترتیب ارتقا در cephadm: اول MGR و MON، سپس OSD و MDS، در پایان دروازه‌ها](figures/ch07/f04_upgrade.png){#fig-07-f04_upgrade}

cephadm ارتقای نسخه را خودکار و مرحله‌ای انجام می‌دهد و ترتیب درست را رعایت می‌کند. پیش از ارتقا:

- یادداشت‌های انتشار نسخه‌ی مقصد را کامل بخوانید، به‌ویژه بخش «Upgrading» و تغییرات ناسازگار.
- مسیر ارتقای مجاز را بررسی کنید: Ceph معمولاً ارتقا را حداکثر از دو نسخه‌ی اصلی قبل‌تر پشتیبانی می‌کند.
- کلاستر باید `HEALTH_OK` باشد و همه‌ی PGها `active+clean`.
- برای Umbrella، پیش‌نیازهای میزبان را چک کنید: image‌ها مبتنی بر el10 هستند و CPU با سطح x86-64-v3 لازم است.

```bash
ceph versions
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade status
ceph -W cephadm                         # دنبال کردن رویدادهای ارتقا
ceph orch upgrade pause                 # در صورت مشکل
ceph orch upgrade resume
ceph orch upgrade stop
```

## ارتقای مرحله‌ای و محدود {#sec-07-6-1}

cephadm اجازه می‌دهد ارتقا را به نوع daemon، سرویس یا میزبان خاصی محدود کنید. در Umbrella امکان ارتقای OSDها **bucket به bucket** در CRUSH اضافه شده است که با دستور تازه‌ی `ceph osd ok-to-upgrade` بررسی می‌کند کدام OSDها را می‌توان هم‌زمان ارتقا داد:

```bash
ceph orch upgrade start --image quay.io/ceph/ceph:v21.2.0 --daemon-types mgr,mon
ceph orch upgrade start --image quay.io/ceph/ceph:v21.2.0 --daemon-types osd --crush_bucket_type rack --crush_bucket_name rack-a
```

::: {.warn}
در ارتقای چندمرحله‌ای، باید ترتیب را خودتان رعایت کنید: هیچ daemonی نباید جدیدتر از MGRها و MONها باشد. پس از ارتقای همه‌ی OSDها، cephadm به‌طور معمول `require_osd_release` را تنظیم می‌کند؛ با `ceph osd dump | grep require_osd_release` تأیید کنید. تا وقتی این مقدار تنظیم نشده، قابلیت‌های جدید OSD فعال نمی‌شوند و هشدار مربوط باقی می‌ماند.
:::

# ظرفیت و توازن {#sec-07-7}

## نسبت‌های پر شدن {#sec-07-7-1}

Ceph برای جلوگیری از پر شدن کامل OSDها سه آستانه دارد. پر شدن کامل یک OSD در Ceph بسیار خطرناک است، چون BlueStore برای حذف داده هم به فضای آزاد نیاز دارد:

| آستانه | پیش‌فرض | اثر |
|---|---|---|
| nearfull_ratio | ۰.۸۵ | هشدار OSD_NEARFULL |
| backfillfull_ratio | ۰.۹۰ | backfill به این OSD متوقف می‌شود |
| full_ratio | ۰.۹۵ | نوشتن در poolهای وابسته متوقف می‌شود (OSD_FULL) |

```bash
ceph osd dump | grep -E 'full_ratio|nearfull'
ceph osd df tree                    # درصد استفاده و تعداد PG هر OSD
ceph df detail                      # فضای خام و قابل استفاده هر pool
```

::: {.warn}
اگر کلاستر به `OSD_FULL` رسید، اولین واکنش طبیعی (حذف داده) ممکن است کار نکند. روال اضطراری: موقتاً `ceph osd set-full-ratio 0.97` (فقط برای فرصت حذف)، حذف یا انتقال داده‌ی غیرضروری، افزودن ظرفیت، و سپس بازگرداندن نسبت به مقدار پیش‌فرض. هرگز این نسبت را به‌صورت دائمی بالا نبرید.
:::

## ظرفیت «قابل استفاده» واقعی {#sec-07-7-2}

عدد `MAX AVAIL` در `ceph df` ظرفیت قابل استفاده‌ی هر pool را با در نظر گرفتن نوع افزونگی و **پرترین OSD** محاسبه می‌کند. یعنی عدم توازن، ظرفیت قابل استفاده را کم می‌کند: اگر یک OSD زودتر پر شود، کل pool پر به حساب می‌آید. برای برنامه‌ریزی ظرفیت این قاعده‌ها را به کار ببرید:

- ظرفیت خام را بر ضریب افزونگی تقسیم کنید (۳ برای تکثیر سه‌تایی، `(k+m)/k` برای EC).
- فضای لازم برای تحمل خرابی بزرگ‌ترین دامنه را کم کنید.
- حاشیه‌ی امن تا nearfull را کم کنید (معمولاً هدف مصرف عادی زیر ۷۰ درصد).

::: {.try}
کلاستری با ۸ گره و در هر گره ۱۲ دیسک ۱۶ ترابایتی دارید و دامنه‌ی خرابی host است. ظرفیت خام ۱۵۳۶ ترابایت است. با تکثیر سه‌تایی حدود ۵۱۲ ترابایت قابل استفاده می‌ماند. برای تحمل از دست رفتن یک گره (یک‌هشتم ظرفیت) و ماندن زیر ۸۵ درصد پس از بازیابی، مصرف عادی را حدود ۷۰ درصد یعنی نزدیک ۳۵۰ تا ۳۶۰ ترابایت نگه دارید. همین محاسبه را برای EC 4+2 تکرار کنید.
:::

## balancer {#sec-07-7-3}

ماژول **balancer** در MGR با تنظیم نگاشت‌های **upmap** (جابه‌جایی صریح PGها بین OSDها) توزیع را یکنواخت می‌کند. در نسخه‌های جاری به‌صورت پیش‌فرض فعال است و حالت `upmap` به کلاینت‌هایی با حداقل نسخه‌ی Luminous نیاز دارد.

```bash
ceph balancer status
ceph balancer mode upmap
ceph balancer on
ceph config set mgr target_max_misplaced_ratio .03     # حداکثر ۳٪ داده‌ی جابه‌جا‌شده در هر لحظه
ceph osd df | sort -nk17 | tail                        # پرترین OSDها
```

::: {.deep}
در Reef حالت‌های تازه‌ی `read` و `upmap-read` اضافه شدند که علاوه بر توزیع داده، **primary**ها را هم متعادل می‌کنند تا بار خواندن یکنواخت‌تر شود (خواندن به‌طور پیش‌فرض از OSD اصلی هر PG انجام می‌شود). این حالت‌ها از نگاشت `pg-upmap-primary` استفاده می‌کنند و همه‌ی کلاینت‌ها باید Reef یا جدیدتر باشند. در کلاستری که دیسک‌های ناهمگن دارد، این حالت می‌تواند گلوگاه خواندن روی چند OSD را کاهش دهد.
:::

## مقیاس‌دهی خودکار PG {#sec-07-7-4}

ماژول **pg_autoscaler** تعداد PG هر pool را بر اساس داده‌ی ذخیره‌شده یا اندازه‌ی هدفی که اعلام می‌کنید تنظیم می‌کند:

```bash
ceph osd pool autoscale-status
ceph osd pool set rbd target_size_ratio 0.4          # این pool قرار است ۴۰٪ کلاستر را بگیرد
ceph osd pool set cephfs.fs01.meta pg_autoscale_mode on
ceph osd pool set images bulk true                   # pool بزرگ: از ابتدا PG کافی بگیرد
```

::: {.note}
در Umbrella پیش‌فرض `mon_target_pg_per_osd` از ۱۰۰ به ۲۰۰ و سقف `mon_max_pg_per_osd` از ۲۵۰ به ۵۰۰ افزایش یافت. پس از ارتقا، autoscaler ممکن است تعداد PG برخی poolها را بالا ببرد و جابه‌جایی داده شروع شود. خروجی `autoscale-status` را پیش و پس از ارتقا مقایسه کنید و اگر لازم است تغییرات را زمان‌بندی کنید.
:::

::: {.sim name="pgcalc"}
:::

# از درون کد: MON، Paxos و سرویس‌های نقشه {#sec-07-8}

## نقش Paxos در Ceph {#sec-07-8-1}

همه‌ی نقشه‌های کلاستر (MonMap، OSDMap، MgrMap، FSMap، پیکربندی مرکزی، کلیدهای cephx و...) روی **یک نمونه‌ی Paxos مشترک** در `src/mon/Paxos.cc` ذخیره می‌شوند. هر «سرویس» (`PaxosService`؛ مانند `OSDMonitor`، `AuthMonitor`، `ConfigMonitor`) تغییرات خود را به این Paxos پیشنهاد می‌کند و Paxos آن‌ها را یکی‌یکی با شماره‌ی نسخه‌ی پیوسته (`last_committed`) در RocksDB مانیتور می‌نویسد. پیاده‌سازی Ceph نسخه‌ای از **Multi-Paxos با رهبر پایدار** است: پس از انتخابات، رهبر یک بار مرحله‌ی بازیابی (collect/last) را انجام می‌دهد و سپس هر تغییر فقط به یک رفت‌وبرگشت (begin/accept) و یک پیام commit نیاز دارد.

![توالی پیام‌های Paxos در MON: پس از انتخابات، رهبر با OP_COLLECT شماره‌ی پیشنهاد جدید را اعلام و با OP_LAST مقادیر ناتمام را جمع می‌کند؛ سپس برای هر تغییر، OP_BEGIN با نسخه‌ی بعدی ارسال، OP_ACCEPT از همه‌ی اعضای quorum دریافت، OP_COMMIT اعلام و با OP_LEASE اجازه‌ی خواندن تا مدت mon_lease به peonها داده می‌شود](figures/ch07/s01_paxos.png){#fig-07-s01_paxos}

| پیام (MMonPaxos) | جهت | معنا |
|---|---|---|
| OP_COLLECT (۱) | رهبر → peon | شروع دور با شماره‌ی پیشنهاد (pn) جدید |
| OP_LAST (۲) | peon → رهبر | پذیرش pn و ارسال مقادیر پذیرفته‌شده‌ی ناتمام |
| OP_BEGIN (۳) | رهبر → peon | مقدار پیشنهادی برای نسخه‌ی بعد |
| OP_ACCEPT (۴) | peon → رهبر | پذیرش مقدار |
| OP_COMMIT (۵) | رهبر → peon | اعلام مقدار توافق‌شده |
| OP_LEASE (۶) | رهبر → peon | تمدید اجازه‌ی خواندن |
| OP_LEASE_ACK (۷) | peon → رهبر | تأیید lease |

یک تفاوت مهم با Paxos کلاسیک: رهبر برای commit منتظر پذیرش **همه‌ی اعضای quorum فعلی** می‌ماند، نه فقط اکثریت. در `Paxos::handle_accept()`:

```cpp
// from ceph/ceph, LGPL — src/mon/Paxos.cc, handle_accept() (excerpt)
accepted.insert(from);
...
if (accepted == mon.get_quorum()) {
```

این ممکن است چون quorum خودش از انتخابات اکثریتی آمده است؛ اگر یکی از اعضای quorum پاسخ ندهد، accept timeout رخ می‌دهد و انتخابات دوباره برگزار می‌شود تا quorum کوچک‌تری (که هنوز اکثریت است) شکل بگیرد. مزیت: همه‌ی اعضای quorum همیشه همه‌ی نسخه‌ها را دارند و می‌توانند خواندن را با lease سرویس دهند.

## حالت‌ها و lease {#sec-07-8-2}

حالت‌های Paxos در `Paxos.h`: `STATE_RECOVERING`، `STATE_ACTIVE`، `STATE_UPDATING`، `STATE_UPDATING_PREVIOUS`، `STATE_WRITING`، `STATE_WRITING_PREVIOUS`، `STATE_REFRESH` (و SHUTDOWN). خواندن از یک peon فقط وقتی مجاز است که lease معتبر داشته باشد. پارامترها:

| گزینه | پیش‌فرض | نقش |
|---|---|---|
| mon_lease | ۵ ثانیه | مدت اعتبار lease خواندن |
| mon_lease_renew_interval_factor | ۰.۶ | تمدید پس از ۶۰٪ مدت lease |
| mon_lease_ack_timeout_factor | ۲ | اگر ack در دو برابر lease نرسد، انتخابات دوباره |
| paxos_propose_interval | ۱ ثانیه | فاصله‌ی دسته‌بندی تغییرات پیش از پیشنهاد |
| mon_election_timeout | ۵ ثانیه | مهلت انتخابات |

::: {.deep}
lease دلیل اصلی حساسیت MON به **اختلاف ساعت** است: رهبر به peon می‌گوید «تا زمان T می‌توانی خواندن را سرویس دهی». اگر ساعت peon عقب باشد، ممکن است پس از اینکه رهبر نقشه‌ی جدیدی commit کرده، هنوز نقشه‌ی قدیمی را به کلاینت بدهد. هشدار `MON_CLOCK_SKEW` (آستانه‌ی `mon_clock_drift_allowed`) برای جلوگیری از همین وضعیت است.
:::

## از فرمان تا نقشه‌ی جدید {#sec-07-8-3}

![مسیر یک فرمان در یک سرویس Paxos مانند OSDMonitor: فرمان‌های فقط‌خواندنی در preprocess_query از نقشه‌ی فعلی پاسخ داده می‌شوند؛ فرمان‌های تغییردهنده در prepare_update روی pending incremental اعمال، با تأخیر paxos_propose_interval دسته‌بندی و با propose_pending به Paxos پیشنهاد می‌شوند؛ پس از commit، نقشه بارگذاری، incremental به مشترکان منتشر و به فرمان‌دهنده پاسخ داده می‌شود](figures/ch07/s02_service.png){#fig-07-s02_service}

```text
pseudocode: PaxosService (خلاصه‌ی این کتاب از PaxosService.cc و OSDMonitor.cc)
  dispatch(op):
      if preprocess_query(op): return            # فقط‌خواندنی؛ مثلاً osd dump
      if not leader: forward(op to leader); return
      if prepare_update(op):                     # تغییر روی pending_inc
          if should_propose(delay):              # دسته‌بندی با paxos_propose_interval
              schedule propose_pending() after delay
  propose_pending():
      t = new transaction
      encode_pending(t)                          # OSDMap::Incremental → bytes
      paxos.begin(t)                             # OP_BEGIN به quorum
  on commit:
      update_from_paxos()                        # epoch جدید
      publish incrementals to subscribers        # OSDها و کلاینت‌ها
      reply to waiting ops
```

::: {.note}
به همین دلیل اجرای هم‌زمان چند ده فرمان `ceph osd ...` معمولاً **یک** epoch جدید با همه‌ی تغییرات می‌سازد، نه ده‌ها epoch. و به همین دلیل یک فرمان تغییردهنده حدود یک ثانیه طول می‌کشد حتی وقتی کلاستر کاملاً آرام است.
:::

## انتخابات {#sec-07-8-4}

`src/mon/ElectionLogic.h` سه راهبرد انتخابات دارد: `CLASSIC` (بر اساس rank؛ کمترین rank برنده می‌شود)، `DISALLOW` (فهرستی از MONها نباید رهبر شوند) و `CONNECTIVITY` (شامل DISALLOW، و ترجیح MONی با اتصال بهتر بر اساس امتیازهای اتصال که در store ذخیره می‌شوند). stretch mode به `connectivity` نیاز دارد (فصل ۱۸).

```bash
ceph mon dump | grep election_strategy
ceph mon set election_strategy connectivity
ceph mon add disallowed_leader e         # MON داور هرگز رهبر نشود
ceph quorum_status | jq '.quorum_leader_name, .quorum_names'
ceph daemon mon.a sessions | jq length   # روی میزبان MON
```

# عملیات روزمره با عدد: down، out، grace و MAX AVAIL {#sec-07-9}

چهار الگوریتم این بخش در MON اجرا می‌شوند و به چند پرسش روزمره‌ی اپراتور جواب می‌دهند: چرا OSD در این لحظه down شد یا نشد، چرا بعد از ده دقیقه out شد، و چرا `ceph df` فضای آزاد کمتری از فضای خام نشان می‌دهد. ارجاع‌ها به main در نوامبر 2026 است و عددها با بازپیاده‌سازی پایتونی حساب شده‌اند.

## علامت‌گذاری down: گزارش‌دهنده‌ها و grace {#sec-07-9-1}

::: {.algo #alg-07-1 title="تصمیم MON برای down کردن یک OSD" src="src/mon/OSDMonitor.cc :: OSDMonitor::check_failure، get_grace_time، is_failure_stale" complexity="O(تعداد گزارش‌دهنده‌ها)"}
:::

```text
pseudocode
گزارش‌دهنده‌ها را بر حسب mon_osd_reporter_subtree_level (پیش‌فرض host) گروه کن
if تعداد گروه‌ها < mon_osd_min_down_reporters (2): هنوز نه
failed_for = now − failed_since                      # از اولین گزارش، با عقب‌بردن زمان
grace = osd_heartbeat_grace (20)
if mon_osd_adjust_heartbeat_grace (true):
    decay = exp(failed_for × ln 0.5 / mon_osd_laggy_halflife (3600))
    grace += decay × laggy_interval × laggy_probability             # سابقه‌ی خود OSD
    grace += میانگین همان جمله برای گزارش‌دهنده‌ها (با decay از down_stamp آن‌ها)
if failed_for ≥ grace: OSD را در نقشه‌ی بعدی down کن
اگر failed_for ≥ grace + osd_heartbeat_stale (600 s) شد و هنوز تصمیمی نیست: گزارش‌ها را دور بریز
```

**مثال عددی.** OSD سالمی که سابقه‌ی laggy ندارد (p = 0) وقتی down می‌شود که همتایانش روی دست‌کم دو میزبان متفاوت گزارش بدهند و failed_for به 20 ثانیه برسد. چون OSDها خودشان پس از 20 ثانیه بدون پاسخ ping گزارش می‌دهند، این معمولاً تقریباً هم‌زمان با اولین گزارش‌هاست. اگر همه‌ی گزارش‌ها از OSDهای یک میزبان باشند، شمارش گروهی 1 است و OSD هیچ‌وقت down نمی‌شود. این عمدی است، چون مشکل شبکه‌ی یک میزبان نباید باعث down شدن بقیه‌ی کلاستر شود. در کلاستر سه‌میزبانی، اگر دو میزبان دیگر سالم باشند، این شرط برقرار می‌شود.

![زمان‌بندی یک OSD خاموش با پیش‌فرض‌ها. پس از 20 ثانیه بی‌پاسخی، همتایان روی دو میزبان گزارش می‌دهند و MON آن را down می‌کند. PGها degraded می‌شوند، اما داده جابه‌جا نمی‌شود. پس از 600 ثانیه (به‌علاوه‌ی جمله‌ی laggy) OSD ‏out می‌شود و backfill شروع می‌شود. خط بنفش استثناها را نشان می‌دهد: پرچم noout و down بودن کل یک rack (mon_osd_down_out_subtree_limit) که شمارنده را صفر می‌کند](figures/ch07/f09_downout.png){#fig-07-f09_downout}

## سابقه‌ی laggy: میانگین متحرک نمایی {#sec-07-9-2}

::: {.algo #alg-07-2 title="به‌روزرسانی laggy_probability و laggy_interval" src="src/mon/OSDMonitor.cc :: OSDMonitor::prepare_boot، grace_interval_threshold_exceeded، set_default_laggy_params" complexity="O(1)"}
:::

```text
pseudocode
w = mon_osd_laggy_weight (0.3)
هنگام boot یک OSD که down علامت خورده بود:
    if boot_epoch == 0 (پردازه واقعاً از نو شروع شده):  p ×= 0.7 ; I ×= 0.7
    else (پردازه زنده بود، یعنی down اشتباه بود):
        gap = min(now − down_stamp, mon_osd_laggy_max_interval 300)
        I = w × gap + (1 − w) × I ;  p = w + (1 − w) × p
اگر down بعدی بیش از 48 × laggy_halflife (48 ساعت) پس از down_stamp قبلی بیفتد: p = I = 0
```

**مثال عددی.** OSDی که زیر بار سنگین به اشتباه down می‌شود و هر بار 40 ثانیه بعد برمی‌گردد، پس از بار اول p = 0.3 و I = 12 دارد. پس از بار دوم p = 0.51 و I = 20.4 است و پس از بار سوم p = 0.657 و I = 26.28. پس grace شکست بعدی تقریباً 20 + 0.657 × 26.28 = 37.3 ثانیه است. decay در اینجا روی failed_for حساب می‌شود، یعنی چند ده ثانیه، و حدود 0.994 است. سری grace برای 1 تا 8 down اشتباه این است: 23.6، 30.4، 37.3، 43.1، 47.7، 51.1، 53.7 و 55.5 ثانیه. حد بالای آن 20 + 40 = 60 ثانیه است. یعنی MON خود به خود با OSDهای «بدقلق» صبورتر می‌شود. چیزی که سابقه را پاک می‌کند گذشت زمان نیست، بلکه ری‌استارت واقعی پردازه یا 48 ساعت بدون down است. همین جمله، با decay بر اساس مدت down، به mon_osd_down_out_interval هم اضافه می‌شود. برای مثال بالا، out پس از حدود 615 ثانیه انجام می‌شود، نه 600.

![چپ: رشد laggy_probability و laggy_interval با هر down اشتباه (OSD زنده که 40 ثانیه بعد برمی‌گردد)، با وزن 0.3. راست: grace مؤثر شکست بعدی، یعنی 20 ثانیه‌ی پایه به‌علاوه‌ی p × I. جمله‌ی همتایان در این مثال صفر فرض شده است. اگر down بعدی بیش از 48 ساعت بعد باشد، سابقه صفر می‌شود](figures/ch07/f08_laggy.png){#fig-07-f08_laggy}

## از down تا out {#sec-07-9-3}

::: {.algo #alg-07-3 title="علامت‌گذاری خودکار out" src="src/mon/OSDMonitor.cc :: OSDMonitor::tick (down_pending_out)، can_mark_out؛ src/osd/OSDMap.cc :: containing_subtree_is_down" complexity="O(OSDهای down × عمق CRUSH)"}
:::

```text
pseudocode
هر tick برای هر OSD در down_pending_out:
    down = now − زمان down شدن
    grace = mon_osd_down_out_interval (600) + exp(down × ln 0.5 / 3600) × I × p
    if پرچم noout (سراسری یا روی گره CRUSH یا device class) یا can_mark_out رد کند: ادامه
    if کل زیردرختی از نوع mon_osd_down_out_subtree_limit (rack) down است: down_pending_out[o] = now ; ادامه
    if down ≥ grace: OSD را out کن (reweight = 0) ← PGها remap و backfill می‌شوند
```

**مثال عددی.** OSD بی‌سابقه دقیقاً 600 ثانیه پس از down، out می‌شود. اگر یک rack کامل با 3 میزبان و 36 OSD خاموش شود، شمارنده‌ی هیچ‌کدام جلو نمی‌رود و out خودکار انجام نمی‌شود. این سیاست محافظه‌کارانه است: فرض می‌کند خاموشی کامل یک rack (برق یا سوئیچ) گذرا است و نباید باعث جابه‌جایی چند ده ترابایت داده شود. برای نگه‌داری برنامه‌ریزی‌شده‌ی یک میزبان، به جای پرچم سراسری از `ceph osd set-group noout <host>` یا `ceph orch host maintenance enter` استفاده کنید.

## MAX AVAIL در ceph df {#sec-07-9-4}

::: {.algo #alg-07-4 title="برآورد فضای قابل‌استفاده‌ی یک pool" src="src/mon/PGMap.cc :: PGMap::get_rule_avail، dump_object_stat_sum؛ src/osd/OSDMap.cc :: pool_raw_used_rate" complexity="O(OSDهای rule)"}
:::

```text
pseudocode
wm = سهم وزنی هر OSD در rule (get_rule_weight_osd_map، مجموع = 1)
برای هر OSD با وزن > 0:
    avail = max(0, kb_avail − kb × (1 − full_ratio))      # 5٪ ذخیره‌ی پیش از full
    proj  = avail / wm[osd]                                # چقدر داده‌ی خام تا پر شدن همین OSD
raw_avail = min(proj)                                       # پرترین OSD نسبت به سهمش
MAX AVAIL = raw_avail / raw_used_rate     # replicated: size ؛ EC: (k + m) / k
```

**مثال عددی.** کلاستری با 52 TiB خام را در نظر بگیرید: یازده OSD چهار ترابایتی و یک OSD هشت ترابایتی. ده OSD چهار ترابایتی 60٪ پرند، osd.10 ‏80٪ و osd.11 (هشت ترابایتی) ‏55٪. سهم وزنی هر OSD چهار ترابایتی 4/52 است. برای OSDهای 60٪ داریم proj = (1.6 − 0.2) / (4/52) = 18.2 TiB، اما برای osd.10 فقط (0.8 − 0.2) / (4/52) = 7.8 TiB. MAX AVAIL یک pool سه‌نسخه‌ای 7.8 / 3 = 2.6 TiB است و یک pool ‏EC ‏4+2 برابر 7.8 / 1.5 = 5.2 TiB. اگر osd.10 هم 60٪ بود، همین pool سه‌نسخه‌ای 6.1 TiB نشان می‌داد. پس یک OSD نامتوازن بیش از نیمی از فضای «قابل‌استفاده»ی گزارش‌شده را می‌خورد. این تعریف درست است، چون CRUSH داده را به نسبت وزن پخش می‌کند و همان OSD اول پر می‌شود. علاج آن balancer با حالت upmap است، نه افزودن دیسک.

![چپ: درصد استفاده‌ی دوازده OSD، با یک OSD چهار ترابایتی که 80٪ پر است (قرمز). راست: برای هر OSD، داده‌ی خامی که می‌توان نوشت تا همان OSD به full_ratio برسد. کمینه‌ی آن‌ها (خط قرمز) پایه‌ی MAX AVAIL است و بر size یا (k + m) / k تقسیم می‌شود](figures/ch07/f10_maxavail.png){#fig-07-f10_maxavail}

![نردبان نسبت‌های پری با پیش‌فرض‌ها: هشدار NEARFULL از 85٪، توقف backfill به سمت OSD از 90٪، پرچم FULL و توقف نوشتن کلاینت‌ها از 95٪، و failsafe خود OSD از 97٪. سه نسبت اول در OSDMap نگه‌داری می‌شوند و با set-*-ratio تغییر می‌کنند. failsafe یک گزینه‌ی پیکربندی OSD است](figures/ch07/f11_ratios.png){#fig-07-f11_ratios}

# نگهداری روزمره {#sec-07-10}

## حالت نگهداری میزبان {#sec-07-10-1}

برای کارهای برنامه‌ریزی‌شده (به‌روزرسانی هسته، تعویض قطعه، راه‌اندازی مجدد)، از حالت نگهداری cephadm استفاده کنید. این حالت همه‌ی daemonهای Ceph روی میزبان را متوقف می‌کند و پرچم `noout` را فقط برای همان میزبان می‌گذارد تا OSDهایش out نشوند و بازیابی بی‌مورد شروع نشود:

```bash
ceph osd ok-to-stop $(ceph osd ls-tree ceph-node2 | tr '\n' ' ')   # آیا توقف همه‌ی OSDهای این میزبان امن است؟
ceph orch host maintenance enter ceph-node2
# ... راه‌اندازی مجدد میزبان یا تعمیر ...
ceph orch host maintenance exit ceph-node2
ceph -s
```

::: {.warn}
`--force` در `maintenance enter` بررسی‌های ایمنی را دور می‌زند. اگر میزبان آخرین MON سالم یا آخرین نسخه‌ی در دسترس برخی PGها را دارد، ورود اجباری به نگهداری یعنی قطع دسترسی. اگر `ok-to-stop` منفی جواب داد، اول علت را برطرف کنید.
:::

## پرچم‌های کلاستر {#sec-07-10-2}

| پرچم | اثر | کاربرد معمول |
|---|---|---|
| noout | OSDهای down خودکار out نمی‌شوند | نگهداری کوتاه‌مدت |
| norebalance | بازتوزیع داده‌ی سالم متوقف می‌شود | افزودن گروهی OSD |
| nobackfill | backfill متوقف می‌شود | کاهش بار در ساعات اوج |
| norecover | بازیابی متوقف می‌شود | فقط در اضطرار و برای مدت کوتاه |
| noscrub, nodeep-scrub | scrub جدید شروع نمی‌شود | عملیات سنگین، ارتقا |
| pause | همه‌ی خواندن و نوشتن‌ها متوقف می‌شود | تقریباً هرگز در production |

```bash
ceph osd set noout
ceph osd unset noout
ceph osd set-group noout osd.4    # فقط یک OSD
ceph osd set-group noout ceph-node3   # همه‌ی OSDهای یک میزبان (bucket CRUSH)
ceph osd unset-group noout ceph-node3
```

::: {.tip}
پرچم‌های فراموش‌شده یکی از رایج‌ترین علت‌های رفتار عجیب کلاستر هستند (مثلاً داده هرگز بازیابی نمی‌شود چون `norecover` روشن مانده است). در پایش، هشدار `OSDMAP_FLAGS` را جدی بگیرید و بعد از هر نگهداری `ceph osd dump | grep flags` را بررسی کنید.
:::

## کنترل سرعت بازیابی و backfill {#sec-07-10-3}

راهنماهای قدیمی برای کند کردن بازیابی، تنظیم مستقیم `osd_max_backfills`، `osd_recovery_max_active` و `osd_recovery_sleep` را آموزش می‌دادند. از Quincy، زمان‌بند پیش‌فرض OSD **mClock** است و این تنظیمات را خودش مدیریت می‌کند. راه درست امروزی انتخاب **پروفایل** است:

| پروفایل | اولویت | کاربرد |
|---|---|---|
| balanced (پیش‌فرض) | تعادل بین کلاینت و بازیابی | حالت عادی |
| high_client_ops | اولویت با کلاینت؛ بازیابی کندتر | ساعات اوج، کلاستر حساس به تأخیر |
| high_recovery_ops | اولویت با بازیابی | پس از خرابی بزرگ، در ساعات کم‌بار |

```bash
ceph config get osd osd_mclock_profile
ceph config set osd osd_mclock_profile high_recovery_ops
# پس از اتمام بازیابی
ceph config set osd osd_mclock_profile balanced
```

::: {.deep}
در حالت mClock، OSD مقادیری مثل `osd_max_backfills` و `osd_recovery_max_active` را نادیده می‌گیرد یا خودش تنظیم می‌کند. اگر واقعاً لازم است دستی تنظیمشان کنید، اول باید `osd_mclock_override_recovery_settings` را `true` کنید. mClock برای تخصیص سهم‌ها به ظرفیت IOPS هر OSD تکیه دارد که در اولین راه‌اندازی اندازه‌گیری می‌شود (`osd_mclock_max_capacity_iops_hdd` و `_ssd`). اگر این اندازه‌گیری روی دیسک شلوغ انجام شده باشد، مقدار غیرواقعی سهم بازیابی را خراب می‌کند. در Squid برای HDDها پیش‌فرض‌های shard تغییر کرد (`osd_op_num_shards_hdd` برابر ۱ با ۵ thread) تا رفتار mClock روی HDD قابل پیش‌بینی‌تر شود.
:::

## اولویت‌دهی به PGهای خاص {#sec-07-10-4}

```bash
ceph pg force-recovery 2.1f
ceph pg force-backfill 2.1f 2.20
ceph pg cancel-force-recovery 2.1f
```

## scrub {#sec-07-10-5}

scrub سبک (هر روز) فراداده‌ی نسخه‌ها را مقایسه می‌کند و deep-scrub (هر هفته) داده را با checksum بررسی می‌کند. برای کاهش اثر scrub بر کلاینت، آن را به ساعات کم‌بار محدود کنید:

```bash
ceph config set osd osd_scrub_begin_hour 1
ceph config set osd osd_scrub_end_hour 6
ceph pg deep-scrub 2.1f
ceph health detail | grep -i scrub
```

::: {.summary title="نکات SRE این فصل"}

- وضعیت مطلوب را با `ceph orch ls --export` در Git نگه دارید.
- پیکربندی در پایگاه MON است؛ `ceph.conf` را دستی ویرایش نکنید.
- قبل از هر حذف: `ok-to-stop` و `safe-to-destroy`.
- تعویض دیسک با `--replace` تا id و CRUSH حفظ شوند.
- نگهداری میزبان فقط با `maintenance enter/exit`.
- پرچم‌ها را پس از کار بردارید؛ `OSDMAP_FLAGS` را پایش کنید.
- سرعت بازیابی را با پروفایل mClock کنترل کنید، نه تنظیم دستی.
- ارتقا: یادداشت انتشار، HEALTH_OK، مسیر حداکثر دو نسخه، پایش پس از ارتقا.

:::

# تکمیلی و به‌روز {#sec-07-11}

- **ceph-deploy** بازنشسته شده و ceph-ansible هم دیگر مسیر توصیه‌شده نیست؛ cephadm و Rook دو روش پشتیبانی‌شده‌ی استقرار و راهبری هستند.
- **پیکربندی متمرکز** (Mimic) جای ویرایش `ceph.conf` را گرفت.
- **mClock** (پیش‌فرض از Quincy) کنترل بازیابی را به پروفایل‌ها سپرد؛ Squid پیش‌فرض‌های shard HDD را تغییر داد.
- **Umbrella**: ارتقای OSD به ترتیب bucketهای CRUSH و دستور `ceph osd ok-to-upgrade`؛ پیش‌نیاز CPU x86-64-v3 و image‌های el10؛ و افزایش پیش‌فرض‌های `mon_target_pg_per_osd` به ۲۰۰ و `mon_max_pg_per_osd` به ۵۰۰ که بر برنامه‌ریزی PG در کلاسترهای ارتقایافته اثر دارد.
- **Tentacle**: ماژول‌های restful و zabbix از MGR حذف شدند؛ اگر اسکریپت‌های عملیاتی شما به restful وابسته‌اند، پیش از ارتقا آن‌ها را به API داشبورد منتقل کنید.

# تمرین عملی {#sec-07-12}

1. خروجی `ceph orch ls --export` را ذخیره کنید، تعداد MGRها را تغییر دهید و تفاوت را با `diff` ببینید.
2. `osd_memory_target` را فقط برای OSDهای کلاس ssd تغییر دهید و با `ceph config show` در یک OSD بررسی کنید.
3. یک میزبان را وارد حالت نگهداری کنید، آن را راه‌اندازی مجدد کنید و خارج شوید. در حین کار خروجی `ceph -s` و پرچم‌ها را یادداشت کنید.
4. خرابی دیسک را با `ceph orch daemon stop osd.N` شبیه‌سازی کنید، پس از out شدن، روال تعویض با `--replace` را اجرا کنید.
5. پروفایل mClock را به `high_recovery_ops` تغییر دهید و سرعت بازیابی (`ceph -s`) را با `balanced` مقایسه کنید.
6. در آزمایشگاه، کلاستر را به آخرین نسخه‌ی نقطه‌ای همان خط ارتقا دهید و مراحل را با `ceph -W cephadm` دنبال کنید.

# پرسش‌های مرور {#sec-07-13}

1. چرا توقف daemon با systemctl در cephadm توصیه نمی‌شود؟
2. ترتیب اولویت منابع پیکربندی چیست و مقدار مؤثر را چطور می‌بینید؟
3. تفاوت `ceph tell` و `ceph daemon` چیست؟
4. مزایا و معایب scale-up و scale-out را از نظر دامنه‌ی خرابی مقایسه کنید.
5. چرا هنگام افزودن تعداد زیادی OSD، پرچم‌های norebalance و nobackfill مفیدند؟
6. تفاوت `ok-to-stop` و `safe-to-destroy` چیست؟
7. گزینه‌ی `--replace` در حذف OSD چه مزیتی دارد؟
8. حالت نگهداری cephadm چه کاری انجام می‌دهد؟
9. چرا در mClock تنظیم مستقیم `osd_max_backfills` اثر ندارد و راه درست چیست؟
10. ارتقای OSD به ترتیب bucketهای CRUSH در Umbrella چه ریسکی را کاهش می‌دهد؟

# منابع این فصل {#sec-07-14}

- cephadm operations: https://docs.ceph.com/en/latest/cephadm/operations/
- Host management: https://docs.ceph.com/en/latest/cephadm/host-management/
- OSD service: https://docs.ceph.com/en/latest/cephadm/services/osd/
- Upgrading Ceph (cephadm): https://docs.ceph.com/en/latest/cephadm/upgrade/
- Configuring Ceph: https://docs.ceph.com/en/latest/rados/configuration/ceph-conf/
- ceph command reference: https://docs.ceph.com/en/latest/man/8/ceph/
- mClock config reference: https://docs.ceph.com/en/latest/rados/configuration/mclock-config-ref/
- Device management: https://docs.ceph.com/en/latest/rados/operations/devices/
- Monitor/OSD interaction: https://docs.ceph.com/en/latest/rados/configuration/mon-osd-interaction/
- Adding/removing monitors: https://docs.ceph.com/en/latest/rados/operations/add-or-rm-mons/
- Release index: https://docs.ceph.com/en/latest/releases/
- Tentacle release notes: https://docs.ceph.com/en/latest/releases/tentacle/
