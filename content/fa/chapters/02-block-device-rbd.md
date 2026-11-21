---
chapter: 2
id: ch02
title: "کار با Ceph Block Device (RBD)"
part: main
lang: fa
---

::: {.tldr}

- هر image در RBD مجموعه‌ای thin از اشیای ۴ مگابایتی RADOS است که روی همه‌ی OSDهای pool پخش می‌شود؛ به هر کلاینت کاربر جداگانه با `profile rbd` بدهید، نه `client.admin`.
- krbd سریع و بی‌وابستگی است اما در قابلیت‌ها عقب‌تر است؛ librbd (در QEMU و rbd-nbd) کامل‌ترین مسیر است.
- snapshot فوری و copy-on-write است، clone قابل نوشتن و ارزان است و `flatten` وابستگی clone به والد را قطع می‌کند؛ snapshot بدون freeze فقط crash-consistent است.
- mirroring در حالت journal (RPO چند ثانیه، نوشتن دوبرابر) یا snapshot (RPO برابر زمان‌بندی) کار می‌کند؛ promote اجباری بدون fencing خطر split-brain دارد.

:::

# پیش از شروع {#sec-02-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-02-1-1}

RBD (RADOS Block Device) پرکاربردترین رابط Ceph است. بیشتر کلاسترهای Ceph دنیا، دیسک ماشین‌های مجازی OpenStack، Proxmox و CloudStack یا volumeهای پایدار Kubernetes را از همین رابط تأمین می‌کنند. در این فصل یاد می‌گیریم:

- یک image در RBD واقعاً چیست و چطور روی اشیای RADOS نگاشت می‌شود؟
- چطور یک کلاینت را با دسترسی حداقلی پیکربندی کنیم و image را بسازیم، map کنیم و تغییر اندازه دهیم؟
- snapshot و clone چطور کار می‌کنند و چرا اساس «قالب طلایی» ماشین‌های مجازی‌اند؟
- RBD mirroring چیست، دو حالت journal و snapshot چه فرقی دارند و چطور تکثیر یک‌طرفه و دوطرفه را برقرار کنیم؟
- هنگام سانحه چطور سایت پشتیبان را ارتقا دهیم و بعد از بازگشت سایت اصلی، داده را برگردانیم؟

## پیش‌نیاز {#sec-02-1-2}

کلاستر آزمایشی فصل ۱ با یک pool به نام `rbd` و ماشین `client-node1`. برای بخش mirroring به یک کلاستر دوم نیاز دارید؛ ساده‌ترین راه، bootstrap یک کلاستر تک‌نودی دیگر با cephadm است (با `--single-host-defaults`).

# RBD از درون {#sec-02-2}

## image، شیء و striping {#sec-02-2-1}

یک **image** در RBD دیسکی مجازی با اندازه‌ی ثابت است که روی اشیای RADOS پخش می‌شود. به‌طور پیش‌فرض هر شیء ۴ مگابایت است (`--object-size`)، پس یک image صد گیگابایتی حداکثر ۲۵٬۶۰۰ شیء دارد. اما RBD **thin provisioned** است: شیئی که هنوز در آن نوشته نشده اصلاً وجود ندارد و فضایی مصرف نمی‌کند.

![ساختار یک image در RADOS: شیء header برای فراداده و اشیای داده‌ی ۴ مگابایتی که فقط پس از نوشتن ساخته می‌شوند](figures/ch02/f01_rbd_objects.png){#fig-02-f01_rbd_objects}

برای هر image (در قالب ۲ که از سال‌ها پیش پیش‌فرض است) این اشیاء در pool وجود دارند:

| شیء | محتوا |
|---|---|
| `rbd_directory` | نگاشت نام imageها به شناسه‌شان در pool |
| `rbd_id.<name>` | شناسه‌ی یکتای image |
| `rbd_header.<id>` | فراداده: اندازه، ترتیب شیء، ویژگی‌ها، فهرست snapshotها، والد (برای clone) |
| `rbd_data.<id>.<offset>` | داده‌ی واقعی؛ شماره‌ی hex نشان‌دهنده‌ی جای شیء در image |
| `rbd_object_map.<id>` | نقشه‌ی وجود اشیاء (اگر ویژگی object-map فعال باشد) |

::: {.deep}
چون هر شیء ۴ مگابایتی با CRUSH مستقلاً روی OSDها جای‌گذاری می‌شود، یک image بزرگ عملاً روی همه‌ی OSDهای pool پخش است. این همان دلیلی است که RBD در I/O موازی (مثلاً عمق صف بالا) خیلی خوب مقیاس می‌گیرد، اما در I/O تک‌رشته‌ای با عمق صف ۱ تأخیر یک رفت‌وبرگشت شبکه و تکثیر را تمام و کمال می‌پردازد. striping سفارشی (`--stripe-unit` و `--stripe-count`) می‌تواند برای بارهای ترتیبی بزرگ مفید باشد، اما krbd فقط برخی ترکیب‌ها را پشتیبانی می‌کند؛ پیش‌فرض را بی‌دلیل تغییر ندهید.
:::

در آزمایشگاه زیر می‌توانید برای یک image نام، اندازه و چیدمان striping تعیین کنید، بازه‌ای از بایت‌ها را برگزینید و ببینید در کدام اشیای `rbd_data` می‌افتد و هر کدام از آن‌ها، همراه با اشیای فراداده‌ی image، روی کدام OSDها قرار می‌گیرند.

::: {.sim name="placement" mode="rbd"}
:::

## ویژگی‌های image {#sec-02-2-2}

هر image مجموعه‌ای از **ویژگی‌ها** (features) دارد که هنگام ساخت تعیین می‌شود و برخی بعداً قابل روشن یا خاموش کردن است:

| ویژگی | کاربرد | وابستگی |
|---|---|---|
| layering | پشتیبانی از clone | — |
| exclusive-lock | تنها یک کلاینت در هر لحظه می‌تواند بنویسد؛ پیش‌نیاز ویژگی‌های پیشرفته | — |
| object-map | ردیابی اشیای موجود؛ سرعت دادن به du، diff، export و حذف | exclusive-lock |
| fast-diff | محاسبه‌ی سریع تفاضل بین snapshotها | object-map |
| deep-flatten | امکان flatten کردن clone همراه با snapshotهایش | — |
| journaling | ثبت همه‌ی تغییرات در journal برای mirroring حالت journal | exclusive-lock |

پیش‌فرض نسخه‌های جدید `layering, exclusive-lock, object-map, fast-diff, deep-flatten` است. ماژول هسته (krbd) در نسخه‌های جدید لینوکس همه‌ی این‌ها به‌جز journaling را پشتیبانی می‌کند؛ روی هسته‌های قدیمی ممکن است هنگام map خطای «image uses unsupported features» بگیرید.

## مسیرهای دسترسی کلاینت {#sec-02-2-3}

![راه‌های دسترسی به RBD: librbd در فضای کاربر (QEMU، rbd-nbd، دروازه‌ی NVMe-oF) و krbd در هسته](figures/ch02/f02_clients.png){#fig-02-f02_clients}

- **librbd:** کتابخانه‌ی فضای کاربر. QEMU/KVM، libvirt، OpenStack و بسیاری از ابزارها از آن استفاده می‌کنند. همه‌ی ویژگی‌ها، از جمله journaling و cache سمت کلاینت، را پشتیبانی می‌کند.
- **krbd:** راه‌انداز هسته‌ی لینوکس که image را به‌صورت `/dev/rbdX` نشان می‌دهد. سریع و بدون وابستگی به بسته‌های فضای کاربر برای مسیر داده، اما مجموعه‌ی ویژگی‌هایش به نسخه‌ی هسته بستگی دارد. Ceph CSI در Kubernetes به‌طور پیش‌فرض از آن استفاده می‌کند.
- **rbd-nbd:** پلی بین librbd و دستگاه NBD هسته؛ وقتی ویژگی‌ای لازم است که krbd ندارد.
- **دروازه‌ی NVMe-oF:** برای میزبان‌هایی که Ceph بومی ندارند (مثلاً VMware ESXi یا ویندوز). image از طریق پروتکل NVMe/TCP صادر می‌شود. این دروازه جانشین عملی دروازه‌ی iSCSI است؛ طبق مستندات رسمی، دروازه‌ی iSCSI از نوامبر ۲۰۲۲ در حالت «فقط نگه‌داری» است و قابلیت تازه‌ای نمی‌گیرد.

# پیکربندی کلاینت Ceph {#sec-02-3}

## ساختن کاربر با دسترسی حداقلی {#sec-02-3-1}

برای کلاینت هرگز از `client.admin` استفاده نکنید. Ceph **profileهای** آماده‌ای برای RBD دارد که دقیقاً همان مجوزهای لازم را می‌دهند:

```bash
ceph auth get-or-create client.rbd-lab \
  mon 'profile rbd' \
  osd 'profile rbd pool=rbd' \
  mgr 'profile rbd pool=rbd' \
  -o /etc/ceph/ceph.client.rbd-lab.keyring
ceph auth get client.rbd-lab
```

::: {.tip}
برای کلاینتی که فقط باید بخواند (مثلاً سرور پشتیبان‌گیری که از snapshotها export می‌گیرد) از `profile rbd-read-only` استفاده کنید. برای جداسازی مستاجرها در یک pool هم می‌توانید از **namespace** استفاده کنید: `rbd namespace create rbd/tenant-a` و سپس `osd 'profile rbd pool=rbd namespace=tenant-a'`.
:::

## انتقال پیکربندی به کلاینت {#sec-02-3-2}

کلاینت به دو چیز نیاز دارد: فایل پیکربندی حداقلی (برای یافتن MONها) و keyring کاربر خودش.

```bash
# روی یک میزبان مدیریتی
ceph config generate-minimal-conf > /tmp/ceph.conf
scp /tmp/ceph.conf client-node1:/etc/ceph/ceph.conf
scp /etc/ceph/ceph.client.rbd-lab.keyring client-node1:/etc/ceph/
# روی client-node1
sudo dnf install -y ceph-common     # یا apt install ceph-common
rbd --id rbd-lab ls rbd
ceph --id rbd-lab -s                # profile rbd اجازه‌ی خواندن وضعیت را می‌دهد
```

::: {.warn}
نسخه‌ی بسته‌های `ceph-common` کلاینت را با نسخه‌ی کلاستر نزدیک نگه دارید. کلاینت‌های خیلی قدیمی ممکن است ویژگی‌های جدید (مثلاً قالب clone نسخه‌ی ۲ یا msgr2) را نشناسند. با `ceph features` می‌توانید نسخه‌ی کلاینت‌های متصل را ببینید و پیش از روشن کردن ویژگی‌هایی که `set-require-min-compat-client` لازم دارند، مطمئن شوید هیچ کلاینت قدیمی‌ای وصل نیست.
:::

# ساختن، map کردن و تغییر اندازه {#sec-02-4}

## ساختن image {#sec-02-4-1}

```bash
rbd --id rbd-lab create rbd/disk01 --size 10G
rbd --id rbd-lab ls -l rbd
rbd --id rbd-lab info rbd/disk01
```

خروجی `rbd info` شامل اندازه، تعداد اشیاء، `order 22` (یعنی اشیای $2^{22}$ بایتی = ۴ مگابایت)، پیشوند نام اشیای داده (`block_name_prefix`) و فهرست ویژگی‌هاست.

## map کردن با krbd {#sec-02-4-2}

```bash
sudo rbd --id rbd-lab device map rbd/disk01      # /dev/rbd0
rbd device list
sudo mkfs.xfs /dev/rbd0
sudo mkdir -p /mnt/disk01 && sudo mount /dev/rbd0 /mnt/disk01
df -h /mnt/disk01
```

برای map خودکار پس از راه‌اندازی مجدد، سرویس `rbdmap` را به کار ببرید:

```bash
echo "rbd/disk01 id=rbd-lab,keyring=/etc/ceph/ceph.client.rbd-lab.keyring" | sudo tee -a /etc/ceph/rbdmap
echo "/dev/rbd/rbd/disk01 /mnt/disk01 xfs noauto,_netdev 0 0" | sudo tee -a /etc/fstab
sudo systemctl enable --now rbdmap
```

::: {.warn}
گزینه‌ی `_netdev` در fstab را فراموش نکنید. بدون آن، سیستم ممکن است در زمان بوت پیش از بالا آمدن شبکه سعی کند فایل‌سیستم را mount کند و بوت متوقف شود. در خاموش کردن هم ترتیب اهمیت دارد: اول umount، بعد unmap، بعد قطع شبکه.
:::

::: {.debug}
اگر `rbd map` با خطای `RBD image feature set mismatch` یا `unsupported features` شکست خورد، پیام `dmesg` را ببینید. ویژگی ناسازگار را خاموش کنید (`rbd feature disable rbd/disk01 journaling`) یا از `rbd-nbd` استفاده کنید. اگر map معطل ماند، دسترسی کلاینت به پورت‌های MON (۳۳۰۰ و ۶۷۸۹) و بازه‌ی پورت OSDها (۶۸۰۰ تا ۷۳۰۰) را با فایروال بررسی کنید.
:::

## تغییر اندازه {#sec-02-4-3}

بزرگ کردن یک image در Ceph فوری است، چون فقط فراداده تغییر می‌کند. بعد باید فایل‌سیستم را هم بزرگ کرد:

```bash
rbd --id rbd-lab resize rbd/disk01 --size 20G
sudo xfs_growfs /mnt/disk01          # برای ext4: sudo resize2fs /dev/rbd0
lsblk /dev/rbd0
```

کوچک کردن خطرناک است و Ceph بدون پرچم صریح اجازه نمی‌دهد:

```bash
rbd resize rbd/disk01 --size 5G --allow-shrink
```

::: {.warn}
پیش از کوچک کردن image، **اول** فایل‌سیستم را کوچک کنید (XFS اصلاً کوچک شدن را پشتیبانی نمی‌کند). کوچک کردن image زیر اندازه‌ی فایل‌سیستم یعنی بریدن انتهای فایل‌سیستم و از دست رفتن داده. در عمل، برای کاهش فضا ساختن image جدید و کپی داده امن‌تر است.
:::

## فضای واقعی و آزادسازی {#sec-02-4-4}

چون RBD thin است، `rbd du` فضای واقعاً مصرف‌شده را نشان می‌دهد. وقتی فایل‌ها را در فایل‌سیستم حذف می‌کنید، فضا تنها وقتی به Ceph برمی‌گردد که فایل‌سیستم دستور **discard** بفرستد:

```bash
rbd du rbd/disk01
sudo fstrim -v /mnt/disk01        # یا فعال کردن fstrim.timer
```

در ماشین‌های مجازی QEMU هم برای رسیدن discard به Ceph باید دیسک با `discard=unmap` و کنترلر virtio-scsi (یا virtio-blk در نسخه‌های جدید) تعریف شده باشد.

# snapshot و clone {#sec-02-5}

## snapshot: تصویر لحظه‌ای فقط‌خواندنی {#sec-02-5-1}

**snapshot** در RBD نسخه‌ی فقط‌خواندنی image در یک لحظه‌ی مشخص است. ساختنش تقریباً آنی است، چون Ceph داده را کپی نمی‌کند. از آن لحظه به بعد، هر شیئی که تغییر کند، OSD نسخه‌ی قبلی‌اش را به‌عنوان «clone شیء» نگه می‌دارد (copy-on-write در سطح شیء RADOS).

```bash
rbd snap create rbd/disk01@before-upgrade
rbd snap ls rbd/disk01
rbd du rbd/disk01                     # سهم هر snapshot از فضا
# بازگرداندن کل image به snapshot (image باید map نشده یا بی‌استفاده باشد)
rbd snap rollback rbd/disk01@before-upgrade
rbd snap rm rbd/disk01@before-upgrade
rbd snap purge rbd/disk01             # حذف همه‌ی snapshotها
```

::: {.warn}
snapshot RBD در سطح بلوک گرفته می‌شود و از فایل‌سیستم داخل image خبر ندارد. اگر روی image در حال استفاده snapshot بگیرید، نتیجه فقط **crash-consistent** است، یعنی مثل قطع ناگهانی برق. برای سازگاری بهتر پیش از snapshot فایل‌سیستم را با `fsfreeze -f /mnt/disk01` منجمد و بعد با `fsfreeze -u` آزاد کنید. در ماشین‌های مجازی QEMU guest agent همین کار را انجام می‌دهد. برای پایگاه داده‌ها از سازوکار خود پایگاه داده (مثلاً حالت backup) استفاده کنید.
:::

::: {.note}
`rbd snap rollback` کل داده‌ی image را بازنویسی می‌کند و برای imageهای بزرگ کند است. اگر فقط چند فایل لازم است، بهتر است از snapshot یک clone بسازید، آن را map کنید و فایل‌ها را کپی کنید.
:::

## زمان‌بندی snapshot {#sec-02-5-2}

از نسخه‌ی Octopus، ماژول MGR به نام `rbd_support` امکان زمان‌بندی snapshot را برای mirroring فراهم می‌کند. برای snapshotهای پشتیبان‌گیری عمومی معمولاً از ابزار بیرونی (cron، Velero، Backy2/Benji یا ابزار پلتفرم مجازی‌سازی) استفاده می‌شود.

## clone: نوشتنی و ارزان {#sec-02-5-3}

**clone** imageی نوشتنی است که بر پایه‌ی یک snapshot ساخته می‌شود. تا وقتی clone در شیئی ننوشته، خواندن آن شیء از والد انجام می‌شود. این همان سازوکاری است که ساختن صدها ماشین مجازی از یک «image طلایی» را در چند ثانیه ممکن می‌کند.

![زنجیره‌ی image والد، snapshot و clone؛ flatten وابستگی clone به والد را قطع می‌کند](figures/ch02/f03_snapclone.png){#fig-02-f03_snapclone}

```bash
rbd create rbd/golden-os --size 20G
# ... نصب سیستم‌عامل روی golden-os ...
rbd snap create rbd/golden-os@v1
# در قالب clone نسخه‌ی ۱ لازم بود snapshot محافظت شود:
rbd snap protect rbd/golden-os@v1
rbd clone rbd/golden-os@v1 rbd/vm01
rbd clone rbd/golden-os@v1 rbd/vm02
rbd children rbd/golden-os@v1
rbd info rbd/vm01 | grep parent
```

::: {.deep}
از Mimic به بعد **قالب clone نسخه‌ی ۲** وجود دارد که دیگر نیازی به `snap protect` ندارد. در این قالب، اگر snapshot والدی را که هنوز فرزند دارد حذف کنید، Ceph آن را به «سطل زباله‌ی snapshot» منتقل می‌کند و وقتی آخرین فرزند flatten یا حذف شد، واقعاً پاکش می‌کند. شرط استفاده این است که کلاستر حداقل نسخه‌ی کلاینت سازگار را دست‌کم Mimic اعلام کرده باشد (`ceph osd set-require-min-compat-client mimic`). گزینه‌ی `rbd_default_clone_format` (با مقدار پیش‌فرض `auto`) تعیین می‌کند کدام قالب استفاده شود.
:::

## flatten: بریدن بند ناف {#sec-02-5-4}

clone تا وقتی والدش وجود دارد به آن وابسته است. اگر بخواهید image طلایی را حذف کنید یا clone را به pool دیگری مهاجرت دهید، باید آن را **flatten** کنید: همه‌ی اشیایی که clone هنوز از والد می‌خواند، در خود clone کپی می‌شوند.

```bash
rbd flatten rbd/vm02
rbd info rbd/vm02 | grep parent      # دیگر parent ندارد
rbd snap unprotect rbd/golden-os@v1  # فقط اگر قالب ۱ و دیگر فرزندی نمانده باشد
```

::: {.tip}
زنجیره‌های clone عمیق (clone از clone از clone) کارایی خواندن را کم می‌کنند، چون خواندن شیء نانوشته باید از چند سطح والد عبور کند. OpenStack و پلتفرم‌های مشابه معمولاً فقط یک سطح clone می‌سازند. اگر زنجیره عمیق شد، flatten کنید.
:::

## سطل زباله و حذف امن {#sec-02-5-5}

RBD یک **trash** دارد. به‌جای حذف فوری، image را به آن منتقل کنید تا در صورت اشتباه قابل بازیابی باشد:

```bash
rbd trash mv rbd/vm01 --expires-at "2026-12-01"
rbd trash ls rbd
rbd trash restore rbd/<image-id>
rbd trash purge rbd                  # حذف همه‌ی imageهای منقضی‌شده
```

## مهاجرت زنده {#sec-02-5-6}

`rbd migration` امکان انتقال image به pool دیگر (مثلاً از HDD به NVMe یا از تکثیری به EC) را با کمترین قطعی فراهم می‌کند. کلاینت فقط در لحظه‌ی prepare باید image را رها کند و بعد می‌تواند روی image مقصد کارش را ادامه دهد، در حالی که داده در پس‌زمینه کپی می‌شود:

```bash
rbd migration prepare rbd/disk01 fast-nvme/disk01
# کلاینت حالا می‌تواند fast-nvme/disk01 را باز کند
rbd migration execute fast-nvme/disk01
rbd migration commit fast-nvme/disk01
```

در Tentacle امکان وارد کردن آنی image از یک کلاستر Ceph دیگر یا از منابع و قالب‌های بیرونی هم به مهاجرت زنده اضافه شده است.

# بازیابی از سانحه با RBD mirroring {#sec-02-6}

## مفهوم و دو حالت آن {#sec-02-6-1}

**RBD mirroring** تکثیر ناهمگام imageها بین دو (یا چند) کلاستر Ceph مستقل است. یک daemon به نام **rbd-mirror** در کلاستر مقصد اجرا می‌شود، تغییرات را از کلاستر مبدأ می‌خواند و روی نسخه‌ی محلی اعمال می‌کند. هر image در هر لحظه فقط در یک کلاستر **primary** (نوشتنی) است و در بقیه **non-primary** (فقط‌خواندنی).

![دو حالت mirroring: در حالت journal همه‌ی نوشتن‌ها ثبت و بازپخش می‌شوند؛ در حالت snapshot تفاضل snapshotهای دوره‌ای منتقل می‌شود](figures/ch02/f04_mirror_modes.png){#fig-02-f04_mirror_modes}

| جنبه | حالت journal | حالت snapshot |
|---|---|---|
| سازوکار | هر نوشتن اول در journal درون RADOS ثبت و سپس روی image اعمال می‌شود | snapshotهای mirror به‌صورت دوره‌ای ساخته و تفاضل آن‌ها منتقل می‌شود |
| RPO | ثانیه‌ها (وابسته به تأخیر بازپخش) | برابر فاصله‌ی زمان‌بندی (مثلاً ۵ دقیقه یا ۱ ساعت) |
| سربار نوشتن | تقریباً دو برابر (journal + داده) | کم؛ فقط در زمان snapshot |
| پشتیبانی krbd | ندارد (journaling پشتیبانی نمی‌شود) | دارد |
| ترتیب نوشتن | حفظ می‌شود (point-in-time consistent) | crash-consistent در لحظه‌ی snapshot |
| توصیه‌ی امروز | برای RPO بسیار کم و کلاینت librbd | انتخاب پیش‌فرض برای بیشتر کاربردها |

## حالت‌های pool {#sec-02-6-2}

mirroring در سطح pool با یکی از این حالت‌ها فعال می‌شود:

- **image:** هر image باید جداگانه و صریحاً برای mirroring فعال شود. انعطاف بیشتر و تنها حالت ممکن برای mirroring نوع snapshot.
- **pool:** همه‌ی imageهایی که ویژگی journaling دارند خودکار mirror می‌شوند (فقط حالت journal).
- **init-only:** pool برای mirroring آماده می‌شود اما خود pool mirror نمی‌شود؛ برای حالتی که فقط namespaceها mirror شوند.

## استقرار rbd-mirror {#sec-02-6-3}

```bash
# روی کلاستر مقصد (و برای دوطرفه، روی هر دو کلاستر)
ceph orch apply rbd-mirror --placement="2 ceph-node2 ceph-node3"
ceph orch ps --daemon-type rbd-mirror
```

::: {.tip}
دو نمونه‌ی rbd-mirror در هر کلاستر اجرا کنید. نمونه‌ها کار را بین خودشان تقسیم می‌کنند و خرابی یکی، تکثیر را متوقف نمی‌کند. rbd-mirror پهنای باند و CPU قابل‌توجهی مصرف می‌کند؛ آن را روی میزبانی بگذارید که هم به شبکه‌ی عمومی محلی و هم به کلاستر راه دور دسترسی خوب دارد.
:::

## پیکربندی تکثیر یک‌طرفه {#sec-02-6-4}

فرض کنید دو کلاستر `site-a` (اصلی) و `site-b` (پشتیبان) داریم و pool به نام `vms` در هر دو با همین نام ساخته شده است.

![توپولوژی mirroring: rbd-mirror در site-b تغییرات را از site-a می‌خواند؛ برای failback به rbd-mirror در site-a هم نیاز است](figures/ch02/f05_mirror_topo.png){#fig-02-f05_mirror_topo}

```bash
# روی هر دو کلاستر
ceph osd pool create vms && rbd pool init vms
# site-a
rbd mirror pool enable --site-name site-a vms image
# site-b
rbd mirror pool enable --site-name site-b vms image
# site-a: ساختن توکن bootstrap (شامل fsid، کاربر و نشانی MONها)
rbd mirror pool peer bootstrap create --site-name site-a vms > /root/vms-token
# انتقال امن توکن به site-b و وارد کردن آن
rbd mirror pool peer bootstrap import --site-name site-b --direction rx-only vms /root/vms-token
rbd mirror pool info vms
```

::: {.warn}
توکن bootstrap حاوی کلید یک کاربر Ceph با دسترسی به pool است. آن را مثل رمز عبور منتقل کنید (scp از کانال امن)، در تیکت یا چت قرار ندهید و پس از import پاکش کنید.
:::

## فعال کردن mirroring برای imageها {#sec-02-6-5}

```bash
# حالت snapshot (پیشنهادی)
rbd create vms/db01 --size 50G
rbd mirror image enable vms/db01 snapshot
# زمان‌بندی snapshotهای mirror برای کل pool یا یک image
rbd mirror snapshot schedule add --pool vms 15m
rbd mirror snapshot schedule ls --pool vms --recursive
# حالت journal (فقط برای کلاینت librbd)
rbd create vms/app01 --size 20G --image-feature exclusive-lock,journaling
rbd mirror image enable vms/app01 journal
```

## بررسی وضعیت همگام‌سازی {#sec-02-6-6}

```bash
rbd mirror pool status vms --verbose
rbd mirror image status vms/db01
```

وضعیت سالم برای یک image non-primary در حالت snapshot معمولاً `up+replaying` است و توضیح آن نشان می‌دهد آخرین snapshot همگام‌شده کدام است و چقدر از آن گذشته. در حالت journal، فاصله‌ی ورودی‌های journal (`entries_behind_primary`) معیار عقب‌ماندگی است.

::: {.debug}
وضعیت `down+unknown` یعنی rbd-mirror در کلاستر مقصد اجرا نمی‌شود یا نمی‌تواند به کلاستر راه دور برسد. `ceph orch ps --daemon-type rbd-mirror`، لاگ daemon و دسترسی شبکه به MONها و OSDهای راه دور را بررسی کنید. وضعیت `up+error` همراه با `split-brain` یعنی image در هر دو طرف primary شده است (بخش بعد را ببینید).
:::

## تکثیر دوطرفه {#sec-02-6-7}

در حالت دوطرفه هر کلاستر هم مبدأ برخی imageها و هم مقصد برخی دیگر است. کافی است rbd-mirror را روی هر دو کلاستر مستقر کنید و توکن را با جهت `rx-tx` (پیش‌فرض) وارد کنید:

```bash
rbd mirror pool peer bootstrap import --site-name site-b --direction rx-tx vms /root/vms-token
```

دوطرفه بودن به این معنی **نیست** که یک image در هر دو طرف هم‌زمان نوشتنی است. معنایش این است که imageهای primary در site-a به site-b و imageهای primary در site-b به site-a تکثیر می‌شوند، و پس از failover جهت تکثیر بدون پیکربندی دوباره برعکس می‌شود.

# از درون کد: چیدمان اشیای RBD، object map و exclusive lock {#sec-02-7}

## یک تصویر RBD روی RADOS چگونه ذخیره می‌شود {#sec-02-7-1}

تصویر RBD در RADOS هیچ «فایل» یکپارچه‌ای نیست. librbd آن را به مجموعه‌ای از اشیای جدا تبدیل می‌کند. پیشوندها در `src/include/rbd_types.h` تعریف شده‌اند: `rbd_id.`، `rbd_header.`، `rbd_object_map.`، `rbd_data.` و اشیای سطح pool یعنی `rbd_directory` و `rbd_trash`.

![چیدمان یک تصویر فرمت ۲ در RADOS. ردیف بالا فهرست‌های سطح pool را نشان می‌دهد: در omap شیء rbd_directory کلیدهای name_ و id_ نام و شناسه را به هم نگاشت می‌کنند. ردیف میانی اشیای فراداده‌ی هر تصویر است: rbd_id.<name> شناسه را نگه می‌دارد، و rbd_header.<id> اندازه، order، features، object_prefix، snapshotها و والد را در omap ذخیره می‌کند و watcherها روی همین شیء ثبت می‌شوند. object map برای هر شیء داده دو بیت حالت دارد. ردیف پایین اشیای داده است که نامشان از object_prefix و یک عدد hex شانزده‌رقمی ساخته می‌شود؛ فقط اشیایی ساخته می‌شوند که واقعاً نوشته شده باشند (thin provisioning)](figures/ch02/s01_layout.png){#fig-02-s01_layout}

فرمول یافتن شیء برای یک offset، بدون striping سفارشی (stripe_unit = اندازه‌ی شیء):

```text
pseudocode (خلاصه‌ی این کتاب از ImageCtx/Striper)
  object_size = 1 << order                 # order=22 → 4 MiB
  objno       = offset // object_size
  obj_off     = offset %  object_size
  oid = sprintf("%s.%016llx", object_prefix, objno)   # object_prefix = "rbd_data.<id>"
```

```bash
rbd info rbd/vm1 | grep -E 'block_name_prefix|order|features'
rados -p rbd listomapvals rbd_directory | head
rados -p rbd listomapkeys rbd_header.$(rados -p rbd get rbd_id.vm1 - | strings)
rados -p rbd ls | grep -c "^rbd_data.<id>"    # تعداد اشیای واقعاً تخصیص‌یافته
rbd du rbd/vm1                                  # با fast-diff سریع است
```

::: {.tip}
اگر `rbd du` روی تصویری بزرگ ثانیه‌ها یا دقیقه‌ها طول می‌کشد، احتمالاً object map/fast-diff غیرفعال یا نامعتبر است. `rbd info` را برای flags نگاه کنید (`object map invalid`) و با `rbd object-map rebuild` بازسازی کنید.
:::

## object map: دو بیت که I/O را سریع می‌کنند {#sec-02-7-2}

ثابت‌های `src/include/rbd/object_map_types.h`:

| مقدار | نام | معنا |
|---|---|---|
| 0 | OBJECT_NONEXISTENT | شیء وجود ندارد؛ خواندن صفر برمی‌گرداند و نیازی به رفتن به OSD نیست |
| 1 | OBJECT_EXISTS | شیء وجود دارد و پس از آخرین snapshot تغییر کرده است |
| 2 | OBJECT_PENDING | حذف/discard در جریان است |
| 3 | OBJECT_EXISTS_CLEAN | شیء وجود دارد ولی از آخرین snapshot تغییر نکرده است (پایه‌ی fast-diff) |

object map فقط زمانی قابل اعتماد است که **یک** نویسنده داشته باشد. به همین دلیل feature `object-map` به `exclusive-lock` وابسته است. سقف تعداد اشیای پوشش‌داده‌شده در `cls_rbd_types.h` برابر `MAX_OBJECT_MAP_OBJECT_COUNT = 256000000` است؛ با اشیای 4MiB، این حدود 976 TiB می‌شود.

```text
pseudocode: نوشتن با object map (خلاصه‌ی این کتاب)
  write(objno, data):
     if objmap[objno] in {NONEXISTENT, EXISTS_CLEAN}:
         objmap_update(objno, EXISTS)        # ابتدا به‌روزرسانی شیء rbd_object_map (cls_rbd)
     send write to rbd_data.<id>.<objno>
  discard(objno):
     objmap_update(objno, PENDING) → remove object → objmap_update(objno, NONEXISTENT)
```

## exclusive lock و ManagedLock {#sec-02-7-3}

پیش‌فرض `rbd_default_features` در `rbd.yaml.in` برابر `layering,exclusive-lock,object-map,fast-diff,deep-flatten` است. قفل با کلاس `cls_lock` و نام `rbd_lock` (`RBD_LOCK_NAME`) روی شیء header گرفته می‌شود. ماشین حالت `librbd/managed_lock/AcquireRequest` سه گام اصلی دارد: `GET_LOCKER`، `LOCK_IMAGE` و در صورت مرده بودن مالک، `BREAK_LOCK`.

![انتقال exclusive lock بین دو کلاینت. B ابتدا مالک فعلی را می‌خواند و اگر قفل گرفته شده باشد، از طریق watch/notify روی header درخواست قفل می‌فرستد. اگر A سالم باشد، طبق policy (پیش‌فرض: آزادسازی خودکار) کش را flush و قفل را رها می‌کند. اگر A دیگر watch نداشته باشد، B قفل را می‌شکند و با rbd_blocklist_on_break_lock=true (پیش‌فرض) آدرس A را blocklist می‌کند تا نوشتن‌های دیررسیده‌ی A پذیرفته نشوند. سپس B قفل را می‌گیرد و در PostAcquire، object map و journal را باز می‌کند](figures/ch02/s02_lock.png){#fig-02-s02_lock}

::: {.warn}
exclusive lock **سازوکار حفاظت از چند نویسنده‌ی هم‌زمان نیست**. این قفل به‌صورت همکارانه بین کلاینت‌ها دست‌به‌دست می‌شود. اگر یک تصویر را روی دو VM هم‌زمان mount کنید (مثلاً با ext4)، داده خراب می‌شود. برای جلوگیری سخت، `rbd map --exclusive` (krbd) یا قفل‌های سطح orchestrator لازم است.
:::

::: {.debug}
دستورهای عیب‌یابی قفل و watcher:
:::

```bash
rbd status rbd/vm1                  # watcherها
rbd lock ls rbd/vm1                 # قفل‌های مشورتی و مالک
ceph osd blocklist ls               # آیا کلاینت قبلی blocklist شده است؟
rbd feature disable rbd/vm1 fast-diff object-map   # ترتیب: وابسته‌ها اول
```

# RBD با عدد: شناسه‌ی image، discard و rbd du {#sec-02-8}

این بخش سه الگوریتم کوچک librbd را بررسی می‌کند که در کار روزمره زیاد دیده می‌شوند: نام‌گذاری شیءهای یک image، تبدیل discard به عملیات شیء، و چگونگی شمارش فضای مصرفی در `rbd du`. ارجاع‌ها به main در نوامبر 2026 است. striping و object map در فصل 3 آمده‌اند.

## شناسه و شیءهای یک image {#sec-02-8-1}

::: {.algo #alg-02-1 title="ساخت شناسه‌ی image و نام شیءهای آن (قالب 2)" src="src/librbd/Utils.cc :: generate_image_id؛ src/include/rbd_types.h (پیشوندها)؛ src/cls/rbd/cls_rbd.cc :: dir_add_image" complexity="O(1)"}
:::

```text
pseudocode
bid   = rados.get_instance_id()          # شناسه‌ی سراسری این اتصال به کلاستر
extra = عدد تصادفی 32 بیتی
id    = hex(bid) + hex(extra)            # بدون صفر پیشرو؛ اگر > 14 نویسه: 14 نویسه‌ی آخر
rbd_id.<name>           ← id
rbd_directory (omap)    ← name_<name> = id ، id_<id> = name
rbd_header.<id>         ← size، order، features، snapshotها، parent (omap)
rbd_object_map.<id>     ← 2 بیت برای هر شیء (اگر object-map فعال باشد)
rbd_data.<id>.%016x     ← شیء داده با شماره‌ی hex شانزده‌رقمی، فقط پس از اولین نوشتن
```

**مثال نمادین.** اگر instance id برابر 4235 (0x108b) و عدد تصادفی 0x1d6e2f3a باشد، id برابر `108b1d6e2f3a` (12 نویسه) است و شیء سوم داده `rbd_data.108b1d6e2f3a.0000000000000002` نام دارد. سقف 14 نویسه (RBD_MAX_IMAGE_ID_LENGTH) از RBD_MAX_BLOCK_NAME_SIZE برابر 24 می‌آید: «rbd_data.» (9 نویسه)، 14 نویسه‌ی id و نویسه‌ی پایان. چون شیءهای داده فقط پس از اولین نوشتن ساخته می‌شوند، `rbd create --size 10T` در کسری از ثانیه تمام می‌شود و هیچ فضایی مصرف نمی‌کند. برای دیدن شیءهای موجود، `rados -p <pool> ls | grep 108b1d6e2f3a` را اجرا کنید.

![زنجیره‌ی شیءهای یک image با قالب 2. ردیف اول ساختن id از instance id و یک عدد تصادفی است. ردیف دوم نگاشت نام به id در rbd_id و rbd_directory، و سرآیند image است. ردیف سوم object map، شیءهای داده‌ای که با اولین نوشتن ساخته می‌شوند، و ورودی trash هنگام حذف است. id نمونه نمادین است](figures/ch02/f08_names.png){#fig-02-f08_names}

## discard: از محدوده‌ی image تا remove، truncate یا zero {#sec-02-8-2}

::: {.algo #alg-02-2 title="هرس و انتخاب عمل discard" src="src/librbd/io/ImageRequest.cc :: ImageDiscardRequest::prune_object_extents؛ src/librbd/io/ObjectRequest.h :: ObjectDiscardRequest؛ src/librbd/ImageCtx.cc (skip_partial_discard)" complexity="O(تعداد شیءهای درگیر)"}
:::

```text
pseudocode
g = rbd_skip_partial_discard (true) و بدون dirty cache ? rbd_discard_granularity_bytes (64K) : 0
g = min(g, object_size)
برای هر extent شیء (off, len):
    if g > 0: off = roundup(off, g) ; end = align(off + len, g) ; if off ≥ end: حذف extent
    if کل شیء: REMOVE    (clone با parent: TRUNCATE یا create+truncate تا parent پنهان شود)
    elif به انتهای شیء می‌رسد: TRUNCATE
    else: ZERO
```

**مثال عددی (شیء 4 MiB).** discard ‏10 KiB در offset ‏100 KiB به بازه‌ی [128K, 64K) گرد می‌شود که خالی است، پس کاری انجام نمی‌شود. discard ‏200 KiB در offset ‏100 KiB به zero در بازه‌ی 128K تا 256K تبدیل می‌شود. discard ‏1 MiB در offset ‏3.5 MiB دو عمل می‌سازد: truncate شیء 0 در 3584K و zero بازه‌ی 0 تا 512K در شیء 1. discard ‏4 MiB در offset ‏2 MiB، شیء 0 را از 2 MiB به بعد truncate و نیمه‌ی اول شیء 1 را zero می‌کند. discard ‏8 MiB در offset ‏4 MiB شیءهای 1 و 2 را کامل حذف می‌کند. پس `fstrim` روی فایل‌سیستمی که بلوک‌های کوچک پراکنده آزاد می‌کند، تقریباً هیچ فضایی پس نمی‌دهد. چیزی که فضا را واقعاً آزاد می‌کند truncate یا remove شیء است، یا zero در BlueStore که اگر هم‌تراز با min_alloc_size باشد، آن بلوک‌ها را آزاد می‌کند.

![پنج درخواست discard روی سه شیء چهارمگابایتی. نوار خاکستری بالای هر ردیف بازه‌ی درخواستی است. قرمز remove، نارنجی truncate، آبی zero و هاشور «رد شده» است. گرد شدن به 64 KiB باعث می‌شود discardهای کوچک‌تر از یک واحد کامل حذف شوند](figures/ch02/f09_discard.png){#fig-02-f09_discard}

![مسیر تصمیم discard در librbd: تبدیل به extentهای شیء، هرس با واحد 64 KiB (مگر اینکه skip_partial_discard خاموش باشد یا cache کثیف وجود داشته باشد) و انتخاب remove، truncate یا zero. برای clone با parent، حذف کامل به truncate تبدیل می‌شود تا داده‌ی parent دوباره پیدا نشود](figures/ch02/f11_discardflow.png){#fig-02-f11_discardflow}

## rbd du: کل شیء یا extent دقیق؟ {#sec-02-8-3}

::: {.algo #alg-02-3 title="شمارش فضای مصرفی در rbd du" src="src/tools/rbd/action/DiskUsage.cc :: get_image_disk_usage (diff_iterate2 با whole_object = !exact)؛ src/librbd/api/DiffIterate.cc" complexity="با fast-diff: O(تعداد شیء) از object map؛ با --exact: O(تعداد شیء) فراخوانی list-snaps"}
:::

```text
pseudocode
whole_object = not --exact
diff_iterate2(from_snap, 0, size, include_parent=false, whole_object, cb)
    if whole_object و fast-diff معتبر: از object map، هر شیء EXISTS یا EXISTS_CLEAN = یک بازه‌ی کامل
    else: برای هر شیء list-snaps ← calc_snap_set_diff
          # بدون snapshot: بازه‌ی [0, size شیء)، نه extentهای پراکنده‌ی نوشته‌شده
USED = Σ طول بازه‌ها                      # PROVISIONED = اندازه‌ی image
اگر fast-diff نامعتبر یا غیرفعال باشد: هشدار و کندی (پیمایش همه‌ی شیءها)
```

**اندازه‌گیری واقعی.** این چهار بار کاری را روی یک کلاستر آزمایشی سه‌OSDی با Ceph 18.2.7 (Reef، بسته‌های Debian) و imageهای ده گیگابایتی با شیء 4 MiB و featureهای پیش‌فرض (61، یعنی layering، exclusive-lock، object-map، fast-diff و deep-flatten) اجرا کردیم:

| بار کاری | بایت نوشته‌شده | rbd du --exact | rbd du پیش‌فرض |
|---|---|---|---|
| A: صد نوشتن 1 KiB در آفست 0 صد شیء | 100 KiB | 100 KiB | 400 MiB |
| B: هزار نوشتن 1 KiB در آفست 0 هزار شیء | 1000 KiB | 1000 KiB | 4000 MiB |
| C: 256 MiB ترتیبی | 256 MiB | 256 MiB | 256 MiB |
| D: دوهزار نوشتن 4 KiB تصادفی در 2 GiB نخست (503 شیء) | 7.8 MiB | 1.51 GiB | 1.96 GiB |

سطر D نکته‌ای را نشان می‌دهد که از نام `--exact` برنمی‌آید. در `calc_snap_set_diff` (فایل src/librados/snap_set_diff.cc) اگر شیء در snapshot آغاز وجود نداشته باشد، diff برابر کل بازه‌ی `[0, size)` شیء گذاشته می‌شود. اندازه‌ی یک شیء RADOS بالاترین بایت نوشته‌شده در آن است. پس `--exact` تا آخرین بایت هر شیء را می‌شمارد، نه extentهای پراکنده را. نوشتن 4 KiB در انتهای یک شیء آن را 4 MiB حساب می‌کند. در D هر شیء به‌طور میانگین حدود چهار نوشتن تصادفی دارد. امید بیشینه‌ی چهار نقطه‌ی یکنواخت 4/5 طول است و همین 503 × 4 MiB × 0.8 ≈ 1.57 GiB را پیش‌بینی می‌کند که به 1.51 GiB اندازه‌گیری‌شده نزدیک است. `--exact` فقط وقتی به داده‌ی واقعاً نوشته‌شده نزدیک است که نوشتن‌ها از ابتدای شیء پیوسته باشند (A، B و C). هیچ‌کدام از دو عدد مصرف خام را نشان نمی‌دهد. مصرف خام به size یا k+m و به min_alloc_size ‏BlueStore (4 KiB در نسخه‌های اخیر) هم بستگی دارد و BlueStore بخش‌های نانوشته را تخصیص نمی‌دهد. برای ظرفیت‌سنجی از `ceph df detail` استفاده کنید و rbd du را فقط برای مقایسه‌ی imageها به کار ببرید.

![USED اندازه‌گیری‌شده روی کلاستر آزمایشی Ceph 18.2.7 برای چهار بار کاری. خاکستری بایت‌های واقعاً نوشته‌شده است، آبی `rbd du --exact` و نارنجی `rbd du` پیش‌فرض (شمارش کل شیء از object map). محور عمودی لگاریتمی است. در بار تصادفی D، ‏`--exact` هم حدود دویست برابر داده‌ی نوشته‌شده را نشان می‌دهد، چون هر شیء را از بایت 0 تا بالاترین بایت نوشته‌شده می‌شمارد](figures/ch02/f10_du.png){#fig-02-f10_du}

# بازگشت از سانحه {#sec-02-9}

## سه سناریو {#sec-02-9-1}

در عمل با سه موقعیت متفاوت روبه‌رو می‌شویم و روش هر کدام فرق دارد:

| سناریو | وضعیت site-a | اقدام | از دست رفتن داده |
|---|---|---|---|
| جابه‌جایی برنامه‌ریزی‌شده (switchover) | سالم | demote در A، صبر تا همگام شدن، promote در B | صفر |
| سانحه (failover) | در دسترس نیست | promote --force در B | به اندازه‌ی RPO |
| بازگشت (failback) | دوباره سالم شده | demote و resync در A، سپس switchover معکوس | صفر (پس از resync) |

![ترتیب گام‌های switchover، failover اجباری و failback](figures/ch02/f06_failover.png){#fig-02-f06_failover}

## جابه‌جایی برنامه‌ریزی‌شده {#sec-02-9-2}

```bash
# ۱. توقف برنامه‌ها و umount در site-a
# ۲. تنزل image در site-a
rbd --cluster site-a mirror image demote vms/db01
# ۳. صبر تا site-b آخرین snapshot را دریافت کند
rbd --cluster site-b mirror image status vms/db01
# ۴. ارتقا در site-b و راه‌اندازی برنامه‌ها آن‌جا
rbd --cluster site-b mirror image promote vms/db01
```

برای کل pool هم دستورهای `rbd mirror pool demote vms` و `rbd mirror pool promote vms` وجود دارند.

## failover اجباری {#sec-02-9-3}

وقتی site-a در دسترس نیست، demote ممکن نیست. image را در site-b به‌اجبار ارتقا می‌دهیم:

```bash
rbd --cluster site-b mirror image promote --force vms/db01
```

::: {.warn}
promote اجباری یعنی پذیرفتن از دست رفتن تغییراتی که هنوز به site-b نرسیده بودند. پیش از آن مطمئن شوید site-a واقعاً از کار افتاده یا کاملاً ایزوله شده است. اگر site-a فقط از دید شما قطع است اما برنامه‌هایش هنوز روی image می‌نویسند، با promote اجباری **split-brain** ساخته‌اید: دو نسخه‌ی primary با تاریخچه‌های متفاوت. Fencing (قطع دسترسی کلاینت‌های قدیمی) بخشی جدایی‌ناپذیر از هر runbook بازیابی از سانحه است.
:::

## failback {#sec-02-9-4}

وقتی site-a برگشت، image آن‌جا هنوز خودش را primary می‌داند. باید آن را تنزل دهیم و دوباره همگامش کنیم:

```bash
rbd --cluster site-a mirror image demote vms/db01
rbd --cluster site-a mirror image resync vms/db01
rbd --cluster site-a mirror image status vms/db01   # تا up+replaying
# پس از همگام شدن، switchover معکوس:
rbd --cluster site-b mirror image demote vms/db01
rbd --cluster site-a mirror image promote vms/db01
```

`resync` نسخه‌ی محلی را دور می‌ریزد و از نسخه‌ی primary فعلی دوباره می‌سازد. برای imageهای بزرگ این یعنی انتقال کامل داده؛ پهنای باند و زمان لازم را در برنامه‌ریزی RTO در نظر بگیرید.

::: {.try}
در آزمایشگاه، یک image را با حالت snapshot و زمان‌بندی یک دقیقه‌ای mirror کنید، داخلش فایلی بنویسید، دو دقیقه صبر کنید، سپس rbd-mirror کلاستر مقصد را متوقف کنید و فایل دیگری بنویسید. حالا با promote اجباری در مقصد ببینید کدام فایل‌ها آن‌جا هستند. این آزمایش ساده مفهوم RPO را ملموس می‌کند.
:::

## ملاحظات طراحی DR {#sec-02-9-5}

- **نام poolها** در دو طرف باید یکسان باشد (یا از remap namespace در نسخه‌های جدید استفاده کنید).
- **ظرفیت مقصد** باید برای همه‌ی imageهای mirror‌شده به‌علاوه‌ی snapshotهای mirror کافی باشد.
- **پهنای باند بین‌سایتی:** نرخ تغییر روزانه‌ی داده (نه اندازه‌ی کل) تعیین‌کننده است. با `rbd mirror image status` و آمار rbd-mirror در Prometheus، عقب‌ماندگی را پایش کنید.
- **پایش و هشدار:** هشدار برای imageهایی که بیش از دو برابر فاصله‌ی زمان‌بندی از آخرین همگام‌سازی‌شان گذشته است.
- **آزمون دوره‌ای:** runbook بازیابی از سانحه‌ای که آزموده نشده، فقط یک سند امیدوارکننده است. دست‌کم هر فصل یک‌بار switchover واقعی انجام دهید.

# تکمیلی و به‌روز {#sec-02-10}

## دروازه‌ی NVMe-oF {#sec-02-10-1}

از Squid به بعد دروازه‌ی **NVMe over Fabrics** (روی TCP) راه رسمی ارائه‌ی RBD به میزبان‌هایی است که کلاینت Ceph ندارند. این دروازه بر پایه‌ی SPDK ساخته شده و با cephadm مستقر می‌شود. دروازه‌ها در **gateway group** سازمان می‌یابند. طبق مستندات، هر گروه در حال حاضر تا هشت دروازه را پشتیبانی می‌کند و دسترس‌پذیری بالا به‌صورت فعال/آماده‌به‌کار برای هر namespace کار می‌کند: هر namespace به یک load-balancing group تعلق دارد و با خرابی یک دروازه، دروازه‌ی دیگری مسئولیتش را بر عهده می‌گیرد. برای HA دست‌کم دو دروازه لازم است. داشبورد Ceph از Tentacle مدیریت گروه‌ها و namespaceهای متعدد NVMe-oF را پشتیبانی می‌کند و در Umbrella امکاناتی مثل TLS/mTLS، احراز هویت DHCHAP و KMIP به آن افزوده شده است.

```bash {since=squid}
ceph osd pool create nvmeof-pool && rbd pool init nvmeof-pool
ceph orch apply nvmeof --pool nvmeof-pool --group group1 --placement="ceph-node2,ceph-node3"
```

## رمزنگاری سطح image {#sec-02-10-2}

RBD از نسخه‌ی Pacific می‌تواند image را با قالب LUKS1 یا LUKS2 در خود librbd رمزنگاری کند (`rbd encryption format`). کلید رمزنگاری با passphrase کاربر محافظت می‌شود و هیچ‌گاه ذخیره نمی‌شود. این قابلیت با librbd و rbd-nbd کار می‌کند. برای krbd، رمزنگاری معمول با dm-crypt روی دستگاه `/dev/rbdX` انجام می‌شود (روشی که Ceph CSI هم برای volumeهای رمزنگاری‌شده به کار می‌برد).

```bash
rbd encryption format rbd/secure01 luks2 /root/passphrase.bin
rbd-nbd map rbd/secure01 -o encryption-format=luks2,encryption-passphrase-file=/root/passphrase.bin
```

## کیفیت سرویس (QoS) {#sec-02-10-3}

librbd محدودیت‌های QoS سمت کلاینت دارد که می‌توان آن‌ها را در سطح pool یا image تعیین کرد، مثل `rbd_qos_iops_limit` و `rbd_qos_bps_limit`:

```bash
rbd config image set rbd/vm01 rbd_qos_iops_limit 2000
rbd config pool set rbd rbd_qos_bps_limit 209715200   # 200 MiB/s
rbd config image ls rbd/vm01 | grep qos
```

این محدودیت‌ها فقط روی librbd اعمال می‌شوند، نه krbd. برای کلاینت‌های krbd، کنترل باید در لایه‌ی cgroup میزبان انجام شود.

## تغییرات دیگر از زمان کتاب {#sec-02-10-4}

- **snapshot گروهی:** `rbd group` امکان گرفتن snapshot سازگار از چند image هم‌زمان را می‌دهد؛ برای برنامه‌هایی که داده‌شان روی چند دیسک است (مثلاً داده و لاگ پایگاه داده). در Tentacle دستورهای مربوط به اطلاعات گروه و snapshot گروهی گسترش یافته‌اند.
- **remap namespace در mirroring:** در Tentacle امکان mirror کردن یک namespace به namespace با نام دیگر در کلاستر مقابل اضافه شده است.
- **پیش‌فرض msgr2 برای krbd:** از Tentacle، `rbd device map` به‌طور پیش‌فرض از پروتکل msgr2 استفاده می‌کند.
- **diff-iterate محلی:** در Squid، `diff-iterate` می‌تواند محلی اجرا شود که کارایی همگام‌سازی زنده‌ی دیسک در QEMU و ابزارهای پشتیبان‌گیری مبتنی بر تفاضل را به‌شدت بهتر کرده است.
- **دروازه‌ی iSCSI:** در حالت نگه‌داری است؛ برای استقرار تازه NVMe-oF را انتخاب کنید.

## میزبان‌های Windows و VMware {#sec-02-10-5}

میزبان‌های Windows می‌توانند بدون دروازه‌ی iSCSI و به‌صورت بومی از RBD استفاده کنند. نصب‌کننده‌ی MSI در Ceph برای Windows ابزار `rbd`، `librbd.dll` و درایور WNBD (Windows Network Block Device) را دارد که یک image را به شکل دیسک محلی نشان می‌دهد. صفحه‌ی رسمی نصب، Windows Server 2019 و 2022 را پشتیبانی‌شده و Windows 10 LTSC و Windows 11 را فقط برای توسعه و آزمون فهرست می‌کند. درایور WNBD امضای Microsoft را ندارد، پس Secure Boot باید خاموش باشد؛ همان صفحه هشدار می‌دهد که تغییر Secure Boot روی میزبانی با BitLocker ممکن است بازیابی BitLocker را آغاز کند، پس ابتدا BitLocker را معلق کنید و کلید بازیابی را در دسترس نگه دارید.

```powershell
rbd device map vms/win-data --id windows      # شماره‌ی دیسک را Windows انتخاب می‌کند
rbd device list                               # در Windows ستون status هم دارد
rbd device show vms/win-data                  # فقط در Windows: مسیر دیسک یک نگاشت
rbd device unmap vms/win-data
```

نگاشت‌ها به‌طور پیش‌فرض ماندگارند: سرویس Windows با نام `ceph-rbd`، که MSI آن را می‌سازد، آن‌ها را هنگام راه‌اندازی دوباره می‌سازد و ترتیب شروع آن را می‌توان طوری تنظیم کرد که imageها پیش از سرویس‌هایی مانند VMMS در Hyper-V نگاشته شوند. image نگاشته‌شده را میزبان می‌تواند به کار ببرد یا مانند یک دیسک iSCSI به یک ماشین مجازی Hyper-V وصل کند. به‌جای `client.admin` از کاربری با کمترین دسترسی (`profile rbd`، مانند بخش «ساختن کاربر با دسترسی حداقلی») استفاده کنید.

VMware ESXi نمی‌تواند librbd را اجرا کند، پس از راه دروازه‌ی NVMe-oF به Ceph می‌رسد (بخش «دروازه‌ی NVMe-oF» در بالا و فصل ۳۱). مستندات Ceph نسخه‌ی ESXi 7.0U3 یا بالاتر را لازم می‌داند. سمت میزبان، با نحو `esxcli` از مستندات Broadcom:

```text
esxcli nvme fabrics enable --protocol TCP --device vmnic2                 # یک آداپتور vmhba می‌سازد
esxcli network ip interface tag add --interface-name vmk1 --tagname NVMeTCP
esxcli nvme adapter list
esxcli nvme fabrics discover -a vmhba65 -i 10.0.5.21 -p 8009 -c          # کشف و اتصال
esxcli nvme namespace list
```

برای مسیر دوم، دو خط اول را برای کارت شبکه‌ی دوم تکرار کنید. راهنمای Broadcom یک آداپتور VMkernel برای هر کارت شبکه‌ی فیزیکی است، بدون LACP یا teaming، چون NVMe/TCP به multipathing خود VMware تکیه دارد. مستندات Ceph آغازگر NVMe/TCP برای Windows را شرح نمی‌دهد؛ برای میزبان‌های Windows از کلاینت بومی RBD در بالا استفاده کنید.

# جمع‌بندی و مرور {#sec-02-11}

## خلاصه‌ی فصل {#sec-02-11-1}

::: {.summary title="نکته‌های کلیدی"}

- image در RBD روی اشیای ۴ مگابایتی RADOS نگاشت می‌شود، thin است و روی همه‌ی OSDهای pool پخش می‌شود.
- کلاینت باید کاربر اختصاصی با `profile rbd` داشته باشد، نه `client.admin`.
- krbd سریع و بدون وابستگی است اما همه‌ی ویژگی‌ها را ندارد؛ librbd کامل‌ترین مسیر است.
- snapshot فوری و COW است؛ clone نوشتنی و ارزان است و flatten وابستگی آن را قطع می‌کند. snapshot بدون freeze فقط crash-consistent است.
- RBD mirroring در دو حالت journal (RPO ثانیه‌ای، سربار بالا) و snapshot (RPO برابر زمان‌بندی، سربار کم) کار می‌کند و با promote و demote جهت آن عوض می‌شود.
- promote اجباری بدون fencing یعنی خطر split-brain.

:::

## اشتباهات رایج {#sec-02-11-2}

- استفاده از `client.admin` روی همه‌ی hypervisorها.
- فراموش کردن `_netdev` و ترتیب خاموش شدن، و گیر کردن بوت یا خاموش شدن میزبان.
- کوچک کردن image بدون کوچک کردن فایل‌سیستم.
- فعال نکردن discard و پر شدن تدریجی کلاستر با فضای حذف‌شده‌ی داخل ماشین‌های مجازی.
- نگه داشتن صدها snapshot قدیمی که هر نوشتن را گران‌تر و scrub را سنگین‌تر می‌کنند.
- فعال کردن journaling روی imageهایی که با krbd map می‌شوند.
- نداشتن runbook آزموده‌شده برای failover و failback.

## تمرین عملی {#sec-02-11-3}

1. یک کاربر با `profile rbd` محدود به namespace بسازید و نشان دهید نمی‌تواند imageهای namespace دیگر را ببیند.
2. یک image بسازید، map و فرمت کنید، ۱ گیگابایت داده بنویسید و `rbd du` را ببینید. سپس فایل‌ها را حذف کنید، `fstrim` بزنید و دوباره `rbd du` را مقایسه کنید.
3. یک image طلایی با snapshot بسازید، ده clone از آن ایجاد کنید و زمان ساخت را اندازه بگیرید. یکی از clone‌ها را flatten کنید و فضای مصرفی را مقایسه کنید.
4. دو کلاستر تک‌نودی بسازید و mirroring حالت snapshot با زمان‌بندی ۵ دقیقه‌ای برقرار کنید. یک switchover کامل و یک failover اجباری با failback انجام دهید و همه‌ی گام‌ها را به شکل runbook بنویسید.
5. با `rbd bench --io-type write --io-size 4K --io-threads 16 rbd/disk01` و سپس با `--io-size 4M` کارایی را بسنجید و تفاوت IOPS و توان را توضیح دهید.

## پرسش‌های مرور {#sec-02-11-4}

1. یک image صد گیگابایتی تازه‌ساخته‌شده که هنوز در آن نوشته نشده، چند شیء در RADOS دارد؟ چرا؟
2. تفاوت krbd، librbd و rbd-nbd چیست و هر کدام کجا مناسب است؟
3. چرا ویژگی object-map به exclusive-lock وابسته است؟
4. snapshot crash-consistent با application-consistent چه فرقی دارد و چطور دومی را به دست می‌آوریم؟
5. در قالب clone نسخه‌ی ۲ چه چیزی نسبت به نسخه‌ی ۱ عوض شده است؟
6. حالت‌های journal و snapshot در mirroring را از نظر RPO، سربار و سازگاری با krbd مقایسه کنید.
7. تفاوت `--direction rx-only` و `rx-tx` در bootstrap import چیست؟
8. چرا promote اجباری بدون fencing خطرناک است؟
9. گام‌های failback پس از بازگشت سایت اصلی کدام‌اند؟
10. برای میزبان VMware که کلاینت Ceph ندارد، امروز کدام راه برای استفاده از RBD توصیه می‌شود؟

## منابع این فصل {#sec-02-11-5}

- مستندات Ceph — Ceph Block Device: https://docs.ceph.com/en/latest/rbd/
- مستندات Ceph — دستورهای پایه‌ی RBD: https://docs.ceph.com/en/latest/rbd/rados-rbd-cmds/
- مستندات Ceph — snapshotهای RBD و clone: https://docs.ceph.com/en/latest/rbd/rbd-snapshot/
- مستندات Ceph — RBD mirroring: https://docs.ceph.com/en/latest/rbd/rbd-mirroring/
- مستندات Ceph — مهاجرت زنده‌ی image: https://docs.ceph.com/en/latest/rbd/rbd-live-migration/
- مستندات Ceph — رمزنگاری image: https://docs.ceph.com/en/latest/rbd/rbd-encryption/
- مستندات Ceph — مرجع پیکربندی librbd و QoS: https://docs.ceph.com/en/latest/rbd/rbd-config-ref/
- مستندات Ceph — دروازه‌ی NVMe-oF: https://docs.ceph.com/en/latest/rbd/nvmeof-overview/
- مستندات Ceph — دروازه‌ی iSCSI (وضعیت نگه‌داری): https://docs.ceph.com/en/latest/rbd/iscsi-overview/
- مستندات Ceph — krbd: https://docs.ceph.com/en/latest/rbd/rbd-ko/
- مستندات cephadm — استقرار rbd-mirror: https://docs.ceph.com/en/latest/rbd/rbd-mirroring/
- یادداشت‌های انتشار Squid: https://docs.ceph.com/en/latest/releases/squid/
- Ceph documentation — RBD on Windows: https://docs.ceph.com/en/latest/rbd/rbd-windows/
- Ceph documentation — Installing the Ceph client on Windows: https://docs.ceph.com/en/latest/install/windows-install/
- Ceph documentation — NVMe/TCP initiator for VMware ESX: https://docs.ceph.com/en/latest/rbd/nvmeof-initiator-esx/
- Broadcom KB 405925 — enabling NVMe over TCP with esxcli: https://knowledge.broadcom.com/external/article/405925/nvme-over-tcp-adapter-option-not-availab.html
