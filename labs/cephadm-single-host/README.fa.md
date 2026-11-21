# آزمایشگاه: کلاستر Ceph تک‌میزبانه با cephadm

[English](README.md)

این آزمایشگاه با cephadm یک کلاستر کوچک Ceph روی یک ماشین مجازی می‌سازد: سه OSD، یک pool و
image در RBD، یک volume در CephFS، و یک سرویس RGW با یک کاربر S3. از مستندات رسمی cephadm
پیروی می‌کند و همراه فصل‌های ۱ و ۱۱ کتاب است.

> **هشدار.** فقط برای آزمایشگاه. `--single-host-defaults` اجازه می‌دهد replicaها روی یک میزبان
> باشند، پس این کلاستر از دست رفتن میزبان را تاب نمی‌آورد و الگویی برای production نیست.

## پیش‌نیازها

- یک ماشین مجازی دورریختنی (نه container) که **systemd** در آن PID 1 است، با یک توزیع Linux
  امروزی. حافظه‌ی کافی برای یک MON، یک MGR، پشته‌ی پایش و سه OSD به آن بدهید؛ هر OSD می‌کوشد
  به اندازه‌ی `osd_memory_target` (به‌طور پیش‌فرض 4 GiB) حافظه به کار ببرد که در آزمایشگاه
  می‌توانید آن را پایین بیاورید.
- الزام‌های میزبان در مستندات cephadm: **Podman** (یا Docker)، **Python 3** (برای cephadm در
  Umbrella، نسخه‌ی 3.9 یا بالاتر)، **LVM2** و همگام‌سازی زمان مانند chrony.
- **سه دیسک خالی و اضافه** (برای نمونه `/dev/vdb`، `/dev/vdc`، `/dev/vdd`). همه‌ی محتوای آن‌ها
  پاک می‌شود.
- یک نشانی IP ثابت روی ماشین مجازی و دسترسی اینترنت به `download.ceph.com` و `quay.io` برای
  فایل cephadm و imageهای container.
- دسترسی root. کلاینت‌های kernel (krbd، کلاینت kernel در CephFS) را روی همین میزبان mount
  نکنید: مستندات Ceph هشدار می‌دهد که ممکن است به بن‌بست (deadlock) برسد؛ از ماشین مجازی
  دیگری به‌عنوان کلاینت استفاده کنید.

## گام‌ها

```bash
cp lab.env.example lab.env          # then set MON_IP and LAB_DISKS
sudo ./00-preflight.sh              # read-only checks; fix every FAIL first
sudo ./01-install-cephadm.sh        # cephadm for CEPH_RELEASE into /usr/local/sbin
sudo ./02-bootstrap.sh              # cephadm bootstrap --single-host-defaults
sudo ./03-osds.sh                   # one OSD per disk in LAB_DISKS
sudo ./04-services.sh               # RBD pool and image, CephFS volume, RGW and a user
sudo ./05-verify.sh                 # wait for HEALTH_OK, print state, short rbd bench
sudo ./99-teardown.sh --yes-really-destroy   # remove the cluster and zap its disks
```

هر اسکریپت:

- از `set -euo pipefail` استفاده می‌کند و تنظیم‌هایش را از `lab.env` می‌خواند؛
- **idempotent** است: ابتدا بررسی می‌کند و آنچه از پیش وجود دارد را رد می‌کند، پس اجرای دوباره‌اش بی‌خطر است؛
- `--help` و `--dry-run` (یا `DRY_RUN=1`) را می‌پذیرد که فرمان‌هایی را که اجرا می‌کرد، بدون پرس‌وجو
  یا تغییر چیزی، چاپ می‌کند.

## تمرین‌ها

پس از آنکه `05-verify.sh` وضعیت HEALTH_OK را نشان داد، این‌ها را امتحان کنید که هر کدام به فصلی گره خورده است:

1. `ceph -s`، `ceph osd tree` و `ceph df` را بخوانید و هر سطر را توضیح دهید (فصل ۱).
2. `lab-rbd/img1` را از یک ماشین مجازی دوم map کنید و از آنجا `rbd bench` اجرا کنید (فصل ۲).
3. کلیدهای S3 کاربر `lab` را با `radosgw-admin user info --uid lab` بخوانید و با `aws s3` روی
   endpoint در RGW که `ceph orch ps` نشان می‌دهد به کار ببرید (فصل ۴).
4. با `ceph fs authorize` یک کلاینت CephFS محدود به یک دایرکتوری بسازید و از ماشین مجازی دوم
   mount کنید (فصل ۶).
5. یک OSD را با `ceph orch daemon stop osd.0` متوقف کنید، وضعیت PGها را دنبال کنید و سپس دوباره
   راه بیندازید (فصل‌های ۷ و ۱۷).
6. یک OSD را مانند جایگزینی دیسک دوباره مستقر کنید (فصل ۱۹).

## آزموده‌شده روی

محدوده‌ی صادقانه‌ی آنچه در این مخزن تأیید شده است:

- همه‌ی اسکریپت‌ها از `shellcheck` می‌گذرند (که در CI روی هر push هم اجرا می‌شود).
- `--help` و `--dry-run` برای همه‌ی اسکریپت‌ها اجرا شد و مسیرهای امتناع بررسی شد: نبود `lab.env`،
  نبود دسترسی root، `99-teardown.sh` بدون `--yes-really-destroy`، و شکست `00-preflight.sh` روی
  دیسک‌هایی که در حال استفاده‌اند.
- **هنوز هیچ اجرای کامل روی یک ماشین مجازی واقعی ثبت نشده است.** فرمان‌ها از مستندات cephadm
  گرفته شده‌اند، ولی تا وقتی چنین اجرایی گزارش نشده، آزمایشگاه را آزموده‌نشده به‌طور کامل بدانید.
  گزارش‌ها و اصلاح‌ها از راه issue و pull request پذیرفته می‌شوند.

## منابع

- نصب cephadm (الزام‌ها، نصب با curl، تک‌میزبان):
  <https://docs.ceph.com/en/latest/cephadm/install/>
- سرویس OSD (`ceph orch device ls`، `ceph orch daemon add osd`):
  <https://docs.ceph.com/en/latest/cephadm/services/osd/>
- پاک کردن کلاستر (`cephadm rm-cluster`):
  <https://docs.ceph.com/en/latest/cephadm/operations/>
- کلاستر تک‌گره و هشدار کلاینت kernel:
  <https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/>
