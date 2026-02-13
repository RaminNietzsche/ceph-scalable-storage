---
chapter: 4
id: ch04
title: "ذخیره‌سازی شیء با RADOS Gateway"
part: main
lang: fa
---

# پیش از شروع {#sec-04-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-04-1-1}

ذخیره‌سازی شیء سریع‌ترین بخش در حال رشد دنیای ذخیره‌سازی است: پشتیبان‌ها، آرشیو رسانه، لاگ‌ها، دیتاست‌های یادگیری ماشین، artifactهای CI و حتی «دریاچه‌ی داده». API عملاً استاندارد این حوزه **Amazon S3** است و **RADOS Gateway** (RGW) پیاده‌سازی Ceph از آن است. در این فصل:

- ذخیره‌سازی شیء چه فرقی با بلوک و فایل دارد و RGW چطور آن را روی RADOS پیاده می‌کند؟
- چطور RGW را با cephadm مستقر و پشت load balancer قرار دهیم؟
- کاربر، کلید، subuser، tenant و account چیست و کدام را کی به کار ببریم؟
- چطور با S3 (s3cmd و aws-cli) و Swift به RGW دسترسی داشته باشیم و DNS مجازی bucket را پیکربندی کنیم؟
- RGW را چطور با Keystone و Hadoop S3A یکپارچه کنیم؟
- قابلیت‌های امروزی مثل نسخه‌بندی، lifecycle، object lock، سیاست bucket و اعلان رویداد چطور کار می‌کنند؟

## پیش‌نیاز {#sec-04-1-2}

کلاستر فصل ۱ و میزبان ceph-node4 با برچسب `rgw`، به‌علاوه‌ی client-node1 برای ابزارهای کلاینت.

# آشنایی با ذخیره‌سازی شیء در Ceph {#sec-04-2}

## شیء، bucket و API {#sec-04-2-1}

در ذخیره‌سازی شیء، هیچ درخت پوشه یا بلوک قابل‌بازنویسی وجود ندارد. داده در قالب **شیء** ذخیره می‌شود: یک کلید (نام)، محتوای باینری و فراداده. اشیاء در **bucket**ها (در اصطلاح Swift: container) دسته‌بندی می‌شوند و از طریق HTTP با فعل‌هایی مثل PUT، GET، HEAD و DELETE دسترسی پیدا می‌کنند. شیء معمولاً یک‌جا نوشته و یک‌جا خوانده می‌شود؛ تغییر بخشی از شیء یعنی بازنویسی کل آن. همین سادگی است که مقیاس عظیم و دسترسی از هر جای اینترنت را ممکن می‌کند.

| ویژگی | بلوک (RBD) | فایل (CephFS) | شیء (RGW) |
|---|---|---|---|
| رابط | دستگاه بلوکی | POSIX | HTTP (S3/Swift) |
| واحد دسترسی | بلوک | بایت در فایل | کل شیء (با range read) |
| فراداده | ندارد | مجوزها، زمان‌ها | دلخواه، به‌همراه برچسب‌ها |
| مقیاس معمول | ترابایت در هر دیسک | میلیون‌ها فایل | میلیاردها شیء |
| کاربرد | VM، پایگاه داده | اشتراک فایل، HPC | پشتیبان، رسانه، داده‌ی تحلیلی |

## RGW روی RADOS {#sec-04-2-2}

radosgw یک سرور HTTP بدون حالت است (frontend پیش‌فرض آن از Nautilus به بعد **Beast** مبتنی بر Boost.Asio است و frontend قدیمی civetweb کنار گذاشته شده). هر درخواست S3 یا Swift را به مجموعه‌ای از عملیات RADOS ترجمه می‌کند. چون حالتی در خود RGW نگه داشته نمی‌شود، هر تعداد نمونه را می‌توان پشت load balancer قرار داد.

![معماری RGW: نمونه‌های بدون حالت پشت load balancer و poolهای جداگانه برای index، داده و فراداده](figures/ch04/f01_arch.png){#fig-04-f01_arch}

## poolهای RGW {#sec-04-2-3}

RGW در یک استقرار ساده (zone پیش‌فرض) این poolها را می‌سازد:

| pool | محتوا | توصیه |
|---|---|---|
| `.rgw.root` | تعریف realm، zonegroup و zone | کوچک؛ تکثیری |
| `default.rgw.control` | اشیای watch/notify برای هماهنگی cache بین نمونه‌ها | کوچک |
| `default.rgw.meta` | فراداده‌ی کاربران و bucketها | روی SSD در صورت امکان |
| `default.rgw.log` | لاگ‌های همگام‌سازی، lifecycle، usage | کوچک تا متوسط |
| `default.rgw.buckets.index` | index هر bucket در omap | **حتماً روی SSD/NVMe و تکثیری** |
| `default.rgw.buckets.data` | داده‌ی اشیاء | تکثیری یا EC؛ بزرگ‌ترین pool |
| `default.rgw.buckets.non-ec` | فراداده‌ی بارگذاری چندبخشی | تکثیری |

::: {.warn}
pool index را هرگز erasure-coded نکنید (EC از omap پشتیبانی نمی‌کند) و آن را روی HDD نگذارید. هر PUT و DELETE یک به‌روزرسانی omap در index است و index کند یعنی کل RGW کند. یک قاعده‌ی CRUSH مبتنی بر device class برای index روی NVMe یکی از مؤثرترین بهینه‌سازی‌های RGW است.
:::

## شیء S3 در RADOS {#sec-04-2-4}

![یک شیء S3 بیست‌مگابایتی در RADOS: شیء head با فراداده و manifest، اشیای tail برای بقیه‌ی داده، و یک ورودی در shard مربوط به index](figures/ch04/f02_object.png){#fig-04-f02_object}

- **head object:** نخستین بخش داده (به‌طور پیش‌فرض تا ۴ مگابایت؛ `rgw_max_chunk_size`) به‌همراه فراداده‌ی شیء در xattr و یک **manifest** که فهرست بقیه‌ی قطعات را دارد.
- **tail objects:** بقیه‌ی داده در اشیای جداگانه (نام‌هایی با پیشوند `__shadow_` یا در بارگذاری چندبخشی `__multipart_`).
- **ورودی index:** یک کلید در omap یکی از shardهای index bucket؛ برای فهرست‌گیری (ListObjects) استفاده می‌شود.

::: {.deep}
چون index هر bucket در omap اشیای RADOS است، یک bucket با صدها میلیون شیء اگر shard نشود، یک شیء omap غول‌پیکر می‌سازد که scrub، بازیابی و حتی عملیات عادی را کند می‌کند و هشدار `LARGE_OMAP_OBJECTS` می‌دهد. **resharding پویا** (پیش‌فرض از Luminous) با رسیدن تعداد اشیاء هر shard به آستانه‌ی `rgw_max_objs_per_shard` (پیش‌فرض ۱۰۰٬۰۰۰) تعداد shardها را خودکار افزایش می‌دهد. در Tentacle بیشتر پردازش reshard پیش از قفل کردن نوشتن‌ها انجام می‌شود تا اثرش بر کلاینت‌ها کمتر شود.
:::

# استقرار و پیکربندی RADOS Gateway {#sec-04-3}

## استقرار با cephadm {#sec-04-3-1}

در گذشته RGW را دستی با بسته‌ها و ceph-deploy روی یک node جداگانه نصب می‌کردند. با cephadm یک دستور کافی است:

```bash
ceph orch host label add ceph-node4 rgw
ceph orch host label add ceph-node3 rgw
ceph orch apply rgw objstore --placement="label:rgw count-per-host:1" --port=8080
ceph orch ls rgw
ceph orch ps --daemon-type rgw
curl http://ceph-node4:8080
```

پاسخ خالی `ListAllMyBucketsResult` با کاربر anonymous یعنی RGW بالاست. برای کنترل بیشتر، از spec به زبان YAML استفاده کنید:

```yaml
service_type: rgw
service_id: objstore
placement:
  label: rgw
  count_per_host: 2
networks:
  - 192.168.56.0/24
spec:
  rgw_frontend_port: 8080
  rgw_frontend_type: beast
```

## load balancer با سرویس ingress {#sec-04-3-2}

cephadm یک سرویس `ingress` دارد که HAProxy و keepalived را مستقر می‌کند و یک IP مجازی جلوی نمونه‌های RGW قرار می‌دهد:

```yaml
service_type: ingress
service_id: rgw.objstore
placement:
  hosts: [ceph-node3, ceph-node4]
spec:
  backend_service: rgw.objstore
  virtual_ip: 192.168.56.100/24
  frontend_port: 443
  monitor_port: 1967
  ssl: true
```

```bash
ceph orch apply -i ingress.yaml
ceph orch ls ingress
```

در نسخه‌های جدید (Tentacle و Umbrella) زیرسیستم **certmgr** در cephadm گواهی‌های امضاشده توسط cephadm را برای چنین سرویس‌هایی خودکار تولید و تمدید می‌کند، یا گواهی شما را می‌پذیرد و برای گواهی‌های در آستانه‌ی انقضا هشدار سلامت می‌دهد.

::: {.tip}
در production، TLS را یا در load balancer پایان دهید یا در خود Beast (با `rgw_frontend_ssl_certificate`). اگر در HAProxy پایان می‌دهید، مطمئن شوید RGW نشانی واقعی کلاینت را از هدر `X-Forwarded-For` می‌خواند (`rgw_remote_addr_param = http_x_forwarded_for`)؛ وگرنه سیاست‌های مبتنی بر IP و لاگ‌ها نشانی load balancer را می‌بینند.
:::

::: {.debug}
اگر پس از apply نمونه‌ای از RGW بالا نیامد، `ceph orch ps --daemon-type rgw` و `ceph health detail` را ببینید. شایع‌ترین دلیل در کلاسترهای کوچک، هشدار `TOO_MANY_PGS` یا خطای ساخت pool به دلیل رسیدن به `mon_max_pg_per_osd` است، چون RGW چند pool تازه می‌سازد. راه دیگر بررسی، `cephadm logs --name rgw.objstore.ceph-node4.xxxx` روی میزبان است.
:::

# کاربران، کلیدها و مستاجرها {#sec-04-4}

## ساختن کاربر radosgw {#sec-04-4-1}

کاربران RGW مستقل از کاربران cephx هستند و در pool فراداده‌ی RGW نگه داشته می‌شوند. ابزار مدیریت آن‌ها `radosgw-admin` است:

```bash
radosgw-admin user create --uid=alice --display-name="Alice" --email=alice@example.com
radosgw-admin user info --uid=alice
radosgw-admin user list
radosgw-admin key create --uid=alice --key-type=s3 --gen-access-key --gen-secret
radosgw-admin user suspend --uid=alice
radosgw-admin user enable --uid=alice
```

خروجی `user create` یک جفت `access_key` و `secret_key` دارد که کلاینت S3 برای امضای درخواست‌ها (AWS Signature v4) استفاده می‌کند.

::: {.warn}
خروجی `radosgw-admin user info` کلید محرمانه را به‌صورت متن ساده نشان می‌دهد. آن را در تیکت، چت یا لاگ CI کپی نکنید. برای تحویل کلید به تیم‌ها از یک سامانه‌ی مدیریت رمز (مثلاً Vault) استفاده کنید و کلیدهای قدیمی را دوره‌ای چرخش دهید (`key create` و سپس `key rm`).
:::

## سهمیه و محدودیت نرخ {#sec-04-4-2}

```bash
radosgw-admin quota set --quota-scope=user --uid=alice --max-size=500G --max-objects=10000000
radosgw-admin quota enable --quota-scope=user --uid=alice
radosgw-admin quota set --quota-scope=bucket --uid=alice --max-objects=5000000
radosgw-admin quota enable --quota-scope=bucket --uid=alice
radosgw-admin ratelimit set --ratelimit-scope=user --uid=alice --max-read-ops=1000 --max-write-ops=200
radosgw-admin ratelimit enable --ratelimit-scope=user --uid=alice
```

محدودیت نرخ از Quincy اضافه شده است و در Umbrella پاسخ محدودیت نرخ هدر `Retry-After` هم دارد که کلاینت‌های خوش‌رفتار برای عقب‌نشینی از آن استفاده می‌کنند.

## subuser و کلید Swift {#sec-04-4-3}

API Swift از مفهوم subuser استفاده می‌کند: هویتی زیرمجموعه‌ی یک کاربر با سطح دسترسی مشخص و کلید مخصوص Swift.

```bash
radosgw-admin subuser create --uid=alice --subuser=alice:swift --access=full
radosgw-admin key create --subuser=alice:swift --key-type=swift --gen-secret
```

## tenant و account {#sec-04-4-4}

![دو سازوکار چندمستاجری: tenant برای جداسازی فضای نام bucketها و account (از Squid) برای مدیریت سلف‌سرویس کاربران و سیاست‌ها به سبک IAM](figures/ch04/f03_tenancy.png){#fig-04-f03_tenancy}

در RGW نام bucketها به‌طور پیش‌فرض در کل کلاستر یکتاست. **tenant** یک فضای نام جداگانه می‌سازد تا دو مشتری بتوانند bucket هم‌نام داشته باشند:

```bash
radosgw-admin user create --tenant=acme --uid=bob --display-name="Bob at ACME"
# نام کامل کاربر: acme$bob ، و bucketها در فضای acme
```

از Squid، **account** مفهومی شبیه حساب AWS اضافه کرده است: یک account مالک کاربران، گروه‌ها، نقش‌ها و سیاست‌هاست و «کاربر ریشه»ی آن می‌تواند از طریق APIهای سازگار با IAM، بدون دخالت مدیر کلاستر، کاربران و کلیدها را مدیریت کند.

```bash
radosgw-admin account create --account-name=acme --email=ops@acme.example
radosgw-admin user create --uid=acme-root --display-name="ACME root" \
  --account-id=<account-id> --account-root --gen-secret --gen-access-key
radosgw-admin quota set --quota-scope=account --account-id=<account-id> --max-size=10T
radosgw-admin quota enable --quota-scope=account --account-id=<account-id>
```

::: {.note}
یادداشت‌های انتشار Tentacle اعلام می‌کنند که قابلیت‌های IAM مبتنی بر tenant (مانند CreateRole و PutUserPolicy در سطح tenant و STS Lite) به نفع account منسوخ شده‌اند و زودتر از نسخه‌ی V حذف نخواهند شد. خود tenant برای جداسازی فضای نام باقی می‌ماند. برای طراحی تازه‌ی چندمستاجری، از account شروع کنید.
:::

# دسترسی با API سازگار با S3 {#sec-04-5}

## DNS و دسترسی virtual-host {#sec-04-5-1}

S3 دو سبک نشانی‌دهی دارد: **path-style** (`https://s3.example.com/bucket/key`) و **virtual-hosted-style** (`https://bucket.s3.example.com/key`). بسیاری از SDKهای جدید پیش‌فرض را سبک دوم گذاشته‌اند. برای پشتیبانی از آن:

1. یک رکورد wildcard در DNS بسازید: `*.s3.example.com` به IP مجازی load balancer.
2. به RGW بگویید نام دامنه‌اش چیست:

```bash
ceph config set client.rgw rgw_dns_name s3.example.com
ceph orch restart rgw.objstore
```

در استقرار چند zonegroup، نام‌های میزبان در فیلد `hostnames` تعریف zonegroup قرار می‌گیرند (فصل ۵). گواهی TLS هم باید wildcard (`*.s3.example.com`) باشد.

## s3cmd {#sec-04-5-2}

```bash
sudo dnf install -y s3cmd      # یا pip install s3cmd
s3cmd --configure              # access key، secret key و endpoint
# یا مستقیم در ~/.s3cfg:
cat > ~/.s3cfg <<'C'
[default]
access_key = <ACCESS>
secret_key = <SECRET>
host_base = s3.example.com
host_bucket = %(bucket)s.s3.example.com
use_https = True
C
s3cmd mb s3://photos
s3cmd put cat.jpg s3://photos/
s3cmd ls s3://photos
s3cmd get s3://photos/cat.jpg /tmp/cat.jpg
s3cmd info s3://photos/cat.jpg
```

## aws-cli و SDKها {#sec-04-5-3}

```bash
aws configure --profile ceph                      # کلیدها
aws --profile ceph --endpoint-url https://s3.example.com s3 mb s3://backups
aws --profile ceph --endpoint-url https://s3.example.com s3 cp ./db.dump s3://backups/
aws --profile ceph --endpoint-url https://s3.example.com s3api list-objects-v2 --bucket backups
aws --profile ceph --endpoint-url https://s3.example.com s3 presign s3://backups/db.dump --expires-in 3600
```

::: {.warn}
برخی نسخه‌های جدید SDKهای AWS به‌طور پیش‌فرض checksumهای جدید یکپارچگی داده (مثل CRC32 در هدرهای `x-amz-checksum-*`) را برای هر PUT می‌فرستند. پشتیبانی RGW از این قابلیت‌ها در نسخه‌های مختلف متفاوت است؛ اگر پس از ارتقای SDK خطای امضا یا «InvalidArgument» دیدید، یادداشت‌های انتشار نسخه‌ی RGW خود را بررسی کنید و در صورت لزوم در پیکربندی کلاینت، ارسال checksum را به حالت «فقط وقتی لازم است» برگردانید. یادداشت‌های Umbrella هم یک رگرسیون SigV4 در نسخه‌های 19.2.6 و 20.2.4 را گزارش می‌کنند که بارگذاری‌های presigned PUT با Content-Type امضانشده را رد می‌کرد و اصلاح شده است.
:::

## بارگذاری چندبخشی {#sec-04-5-4}

برای اشیای بزرگ (معمولاً بالای ۱۰۰ مگابایت) از **multipart upload** استفاده کنید؛ aws-cli و s3cmd خودکار این کار را انجام می‌دهند. بارگذاری‌های نیمه‌کاره فضا اشغال می‌کنند و در فهرست اشیاء دیده نمی‌شوند. یک قاعده‌ی lifecycle برای پاک کردنشان اضافه کنید (`AbortIncompleteMultipartUpload`) و گاهی با `radosgw-admin bucket list --bucket=<b>` یا `aws s3api list-multipart-uploads` بررسی‌شان کنید.

# دسترسی با API Swift {#sec-04-6}

```bash
pip install python-swiftclient
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' stat
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' post container01
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' upload container01 report.pdf
swift -A http://s3.example.com:8080/auth/1.0 -U alice:swift -K '<SWIFT_SECRET>' list container01
```

bucketها در S3 و containerها در Swift یک چیزند: فایلی که با Swift بارگذاری شده با S3 هم دیده می‌شود (به شرطی که کاربر یکی باشد).

# یکپارچه‌سازی با OpenStack Keystone {#sec-04-7}

در ابرهای OpenStack معمولاً می‌خواهیم کاربران با همان هویت Keystone به ذخیره‌سازی شیء دسترسی داشته باشند و RGW در catalog به‌عنوان سرویس `object-store` ثبت شود.

![جریان احراز هویت Swift با Keystone: RGW توکن را نزد Keystone اعتبارسنجی می‌کند و برای هر پروژه خودکار کاربر می‌سازد](figures/ch04/f04_keystone.png){#fig-04-f04_keystone}

```bash
# در Keystone
openstack service create --name swift --description "Ceph RGW" object-store
openstack endpoint create --region RegionOne object-store public \
  "https://s3.example.com/swift/v1/AUTH_%(project_id)s"
# در Ceph
ceph config set client.rgw rgw_keystone_url https://keystone.example.com:5000
ceph config set client.rgw rgw_keystone_api_version 3
ceph config set client.rgw rgw_keystone_admin_user rgw
ceph config set client.rgw rgw_keystone_admin_password_path /etc/ceph/keystone.pass
ceph config set client.rgw rgw_keystone_admin_domain Default
ceph config set client.rgw rgw_keystone_admin_project service
ceph config set client.rgw rgw_keystone_accepted_roles "member,admin"
ceph config set client.rgw rgw_keystone_implicit_tenants true
ceph config set client.rgw rgw_swift_account_in_url true
ceph config set client.rgw rgw_s3_auth_use_keystone true
```

::: {.tip}
مستندات RGW گزینه‌ی `rgw_keystone_admin_password_path` را به گذاشتن رمز به‌صورت متن ساده در پیکربندی ترجیح می‌دهند. با cephadm می‌توانید فایل را از طریق `extra_container_args`/mount یا `ceph config-key` در اختیار کانتینر بگذارید. `rgw_s3_auth_use_keystone` امکان استفاده از اعتبارنامه‌های EC2 در Keystone (`openstack ec2 credentials create`) برای S3 را فراهم می‌کند. در Umbrella، الزام قدیمی admin token برای Keystone حذف شده و نقش‌های Keystone به محیط ارزیابی سیاست IAM تزریق می‌شوند.
:::

# یکپارچه‌سازی با Hadoop و Spark از طریق S3A {#sec-04-8}

اکوسیستم Hadoop از طریق کانکتور **S3A** به هر سرویس سازگار با S3 وصل می‌شود. این یعنی می‌توانید HDFS را برای ذخیره‌سازی سرد یا حتی اصلی با RGW جایگزین کنید و محاسبه و ذخیره‌سازی را از هم جدا مقیاس دهید.

```xml
<!-- core-site.xml -->
<property><name>fs.s3a.endpoint</name><value>https://s3.example.com</value></property>
<property><name>fs.s3a.path.style.access</name><value>true</value></property>
<property><name>fs.s3a.access.key</name><value>ACCESS</value></property>
<property><name>fs.s3a.secret.key</name><value>SECRET</value></property>
<property><name>fs.s3a.connection.ssl.enabled</name><value>true</value></property>
<property><name>fs.s3a.committer.name</name><value>magic</value></property>
```

```bash
hadoop fs -mkdir s3a://analytics/raw
hadoop fs -put events.parquet s3a://analytics/raw/
spark-submit --conf spark.hadoop.fs.s3a.endpoint=https://s3.example.com job.py
```

::: {.deep}
نوشتن خروجی کارهای Spark روی ذخیره‌سازی شیء چالش «rename» دارد: commit سنتی Hadoop پوشه‌ی موقت را rename می‌کند که در S3 یعنی کپی و حذف همه‌ی اشیاء. **S3A committers** (مثل directory و magic) این مشکل را با بارگذاری چندبخشی که فقط در لحظه‌ی commit نهایی می‌شود حل می‌کنند. برای بارهای سنگین تحلیلی روی RGW حتماً یکی از این committerها را فعال کنید. اسناد خود Hadoop درباره‌ی پیش‌نیازهای سازگاری (مثلاً پشتیبانی از multipart و فهرست‌گیری سازگار) راهنمای خوبی است؛ RGW سازگاری قوی read-after-write دارد.
:::

# از درون کد: bucket index، manifest و مسیر PUT در RGW {#sec-04-9}

## دو جای جدا برای یک شیء S3 {#sec-04-9-1}

RGW هر شیء S3 را در دو مکان مستقل ثبت می‌کند. یکی **ورودی bucket index** است که در omap اشیای شارد در pool index قرار دارد و برای List و آمار bucket استفاده می‌شود. دیگری **خود داده** است که در pool داده به شکل یک head و صفر یا چند tail ذخیره می‌شود. هماهنگ نگه داشتن این دو، بدون تراکنش توزیع‌شده، با یک پروتکل دومرحله‌ای سبک روی کلاس `cls_rgw` انجام می‌شود.

![مسیر PUT یک شیء. radosgw شماره‌ی شارد را از hash نام شیء محاسبه می‌کند. ابتدا متد cls به نام bucket_prepare_op یک ورودی با حالت PENDING_MODIFY و یک tag یکتا در شارد ثبت می‌کند. سپس head (شامل حداکثر ۴MiB اول داده و xattrهای manifest، ACL و etag) و stripeهای tail نوشته می‌شوند. در پایان bucket_complete_op ورودی را با اندازه، etag و mtime به حالت COMPLETE می‌برد و یک رکورد bilog برای همگام‌سازی multisite می‌سازد. اگر RGW بین این دو مرحله از کار بیفتد، ورودی pending باقی می‌ماند و بعداً با dir_suggest_changes (هنگام list) یا radosgw-admin bucket check اصلاح می‌شود](figures/ch04/s01_put.png){#fig-04-s01_put}

| ثابت/گزینه | مقدار (main) | منبع |
|---|---|---|
| پیشوند شیء شارد index | `.dir.` | `rgw/services/svc_bi_rados.cc` |
| تعداد شارد پیش‌فرض bucket جدید | 11 | `default_bucket_index_max_shards` در `rgw_zone_types.h` |
| rgw_override_bucket_index_max_shards | 0 (یعنی مقدار zonegroup) | `rgw.yaml.in` |
| rgw_dynamic_resharding | true | `rgw.yaml.in` |
| rgw_max_objs_per_shard | 100000 | آستانه‌ی resharding پویا |
| rgw_safe_max_objects_per_shard | 102400 | آستانه‌ی هشدار `bucket limit check` |
| rgw_max_chunk_size | 4_M | بیشینه‌ی داده در head |
| rgw_obj_stripe_size | 4_M | اندازه‌ی هر stripe در tail |
| rgw_bucket_index_max_aio | 128 | موازی‌سازی عملیات روی شاردها |

حالت‌های ورودی index در `cls_rgw_types.h`: `CLS_RGW_STATE_PENDING_MODIFY = 0`، `CLS_RGW_STATE_COMPLETE = 1`، `CLS_RGW_STATE_UNKNOWN = 2`.

![چیدمان فیزیکی. در pool index، هر bucket به N شیء .dir.<marker>.<shard> تقسیم می‌شود و ورودی‌ها در omap آن‌ها نگهداری می‌شوند. در pool داده، head با نام <marker>_<key> و tailها با پیشوند __shadow_ ذخیره می‌شوند. در multipart هر part یک شیء __multipart_ جداست و CompleteMultipartUpload فقط manifest را می‌سازد و داده را کپی نمی‌کند. tail اشیای حذف‌شده یا بازنویسی‌شده به‌صورت ناهمگام در صف GC (کلاس rgw_gc) پاک می‌شوند](figures/ch04/s02_layout.png){#fig-04-s02_layout}

```text
pseudocode: put_obj (خلاصه‌ی این کتاب از rgw_rados.cc و cls_rgw.cc)
  shard = hash(key) % num_shards
  tag   = unique_op_tag()
  cls_call(index[shard], "rgw.bucket_prepare_op", {key, tag, op=ADD})
  write head  oid="<marker>_<key>"   data[0:4MiB], xattrs{manifest, acl, etag}
  for i, chunk in stripes(data[4MiB:], 4MiB):
      write tail oid="<marker>__shadow_<prefix>_<i>"
  cls_call(index[shard], "rgw.bucket_complete_op", {key, tag, size, etag, mtime})
      # درون OSD: ورودی COMPLETE + به‌روزرسانی header آمار + bilog entry
  if old version existed: enqueue old tail to GC
```

::: {.deep}
چرا bucketهای بسیار بزرگ کند می‌شوند: List با ترتیب الفبایی باید از **همه‌ی** شاردها بخواند و نتایج را merge کند؛ هزینه‌ی آن با تعداد شارد رشد می‌کند. از طرف دیگر، شارد بیش از حد بزرگ (میلیون‌ها کلید omap) باعث کندی compaction در RocksDB، scrub طولانی و هشدار `LARGE_OMAP_OBJECTS` می‌شود. dynamic resharding تعادل این دو را خودکار برقرار می‌کند، ولی در multisite فقط وقتی کار می‌کند که zone feature به نام `resharding` در zonegroup فعال باشد (ثابت آن در `rgw/rgw_zone_features.h` تعریف شده است؛ بررسی: `radosgw-admin zonegroup get | jq .enabled_features`).
:::

::: {.debug}
فرمان‌های بررسی:
:::

```bash
radosgw-admin bucket stats --bucket=photos | jq '.num_shards, .usage'
radosgw-admin bucket limit check | jq '.[].buckets[] | select(.fill_status!="OK")'
radosgw-admin reshard list ; radosgw-admin reshard status --bucket=photos
radosgw-admin object stat --bucket=photos --object=a.jpg | jq '.manifest'
radosgw-admin bucket check --bucket=photos --check-objects   # بدون --fix فقط گزارش
radosgw-admin gc list --include-all | jq length
ceph health detail | grep -A3 LARGE_OMAP
```

# RGW با عدد: shard ایندکس، reshard، فهرست‌گیری و manifest {#sec-04-10}

چهار الگوریتم این بخش تعیین می‌کنند یک شیء S3 در کدام شیء ایندکس ثبت شود، bucket کی و به چند shard تقسیم شود، فهرست‌گیری مرتب از bucket چقدر داده از OSDها می‌خواند و بایت‌های خود شیء در چه شیءهای RADOS با چه نامی ذخیره شوند. همه‌ی ارجاع‌ها به main در نوامبر 2026 است و عددها با بازپیاده‌سازی پایتونی همان توابع حساب شده‌اند. منطق کاهش shard در reshard پویا و جزئیات چند ضریب در نسخه‌های اخیر اضافه یا عوض شده‌اند. پیش از تکیه بر آن‌ها، کد نسخه‌ی خود را بررسی کنید.

## انتخاب shard ایندکس {#sec-04-10-1}

::: {.algo #alg-04-1 title="نگاشت کلید شیء به shard ایندکس bucket" src="src/rgw/services/svc_bi_rados.h :: RGWSI_BucketIndex_RADOS::bucket_shard_index؛ src/rgw/driver/rados/rgw_tools.h :: rgw_shards_mod؛ src/common/ceph_hash.cc :: ceph_str_hash_linux" complexity="O(طول کلید)"}
:::

```text
pseudocode
key = نام شیء   (برای قطعه‌های multipart: کلید شیء نهایی، تا همه‌ی قطعه‌ها در یک shard باشند)
sid  = ceph_str_hash_linux(key)                         # hash = (hash + (c<<4) + (c>>4)) × 11 برای هر بایت
sid2 = sid XOR ((sid AND 0xFF) << 24)                    # بیت‌های کم‌ارزش را به بالا می‌برد
shard = n ≤ 7877 ? sid2 mod 7877 mod n : sid2 mod 65521 mod n
oid ایندکس = ".dir." + bucket_marker + "." + shard   (با نسل لایه، ".dir.<marker>.<gen>.<shard>")
```

**مثال عددی.** برای کلید `photos/2026/11/img_0001.jpg`، مقدار ceph_str_hash_linux عدد 2668161921 است. بایت پایین آن 0x81 است و پس از XOR با 0x81000000 عدد 503901057 به دست می‌آید. 503901057 mod 7877 mod 11 = 5، پس با 11 shard (پیش‌فرض zonegroup برای bucket تازه) ورودی در `.dir.<marker>.5` می‌نشیند. کلید بعدی، `img_0002.jpg`، به shard ‏10 می‌رود و `logs/app.log` به shard ‏9. اگر bucket به 23 shard برود، همین سه کلید به shardهای 18، 21 و 2 جابه‌جا می‌شوند. به همین دلیل reshard باید **همه‌ی** ورودی‌ها را بازنویسی کند. برای 100000 کلید پشت‌سرهم با الگوی `img_NNNNNN.jpg`، کمترین shard ‏9031 و بیشترین 9162 ورودی گرفت، یعنی ±1 درصد حول میانگین 9091. این hash ضعیف است، اما برای نام‌های معمولی پخش خوبی می‌دهد.

![سمت چپ: پخش 100000 کلید پشت‌سرهم میان 11 shard ایندکس. خط‌چین میانگین است و همه‌ی shardها در حدود یک درصد آن هستند. سمت راست: سه کلید نمونه گام‌به‌گام از hash تا شماره‌ی shard، هم برای 11 و هم برای 23 shard. مرحله‌ی XOR بایت پایین hash را به بایت بالا می‌برد، چون باقی‌مانده‌ی تقسیم بر عدد اول کوچک بیشتر به بیت‌های پایین حساس است](figures/ch04/f08_bishard.png){#fig-04-f08_bishard}

## reshard پویا: کی و به چند shard؟ {#sec-04-10-2}

::: {.algo #alg-04-2 title="محاسبه‌ی تعداد shard پیشنهادی" src="src/rgw/driver/rados/rgw_reshard.cc :: RGWBucketReshard::calculate_preferred_shards، nearest_prime" complexity="O(log P) برای جست‌وجو در فهرست 304 عدد اول تا 1999"}
:::

```text
pseudocode
max_objs = rgw_max_objs_per_shard (100000) ; max_dyn = rgw_max_dynamic_shards (1999) ; min_dyn = 11
min_objs = min(10000, ceil(max_objs / 100))           # آستانه‌ی کاهش: 1000
if cur < max_dyn and objs > cur × max_objs: افزایش
elif cur > min_dyn and objs < cur × min_objs: کاهش   (اگر rgw_dynamic_resharding_may_reduce، با تأخیر)
else: کاری نکن
m = multisite ? 8 : 2
new = clamp(objs × m / max_objs, min_dyn, max_dyn) ; new = کوچک‌ترین عدد اول ≥ new در فهرست
new = min(max_dyn, max(new, min_dyn, min_layout_shards))
```

**مثال عددی.** bucket با 11 shard شروع می‌کند. فرض کنید هر 100000 شیء یک بار بررسی شود. در 1.2 میلیون شیء، شرط 1200000 > 11 × 100000 برقرار است. new = 1200000 × 2 / 100000 = 24 و نزدیک‌ترین عدد اول بزرگ‌تر یا مساوی 29 است. مسیر رشد در یک zone این است: 11 → 29 (1.2 میلیون) → 61 (3 میلیون) → 127 (6.2 میلیون) → 257 (12.8 میلیون) → 521 (25.8 میلیون) → 1049 (52.2 میلیون) → 1999 (105 میلیون). در multisite با ضریب 8 فقط سه reshard لازم است: 11 → 97 → 787 → 1999. هدف ضریب بزرگ‌تر کاهش تعداد reshardها است، چون هر reshard در multisite یک نسل تازه‌ی bilog می‌سازد و همگام‌سازی باید از آن عبور کند. کاهش هم ممکن است. اگر bucketی با 101 shard به 90000 شیء برسد، 90000 < 101 × 1000 است و پیشنهاد 11 shard داده می‌شود. پیش‌فرض `rgw_dynamic_resharding_reduction_wait` در main ‏120 ساعت است، تا bucketی که موقتاً خالی شده بلافاصله کوچک نشود.

![تعداد shard ایندکس برحسب تعداد شیء در bucket، روی محورهای لگاریتمی. آبی مسیر یک zone با ضریب 2 است و قرمز مسیر multisite با ضریب 8. هر پله یک reshard است و عدد کنار آن تعداد shard تازه (عدد اول) است. خط نقطه‌چین سقف 100000 شیء در هر shard است. هر بار که bucket از آن عبور کند، reshard صف می‌شود. سقف 1999 در هر دو مسیر به تعداد شیء متفاوتی می‌رسد](figures/ch04/f09_reshard.png){#fig-04-f09_reshard}

## فهرست‌گیری مرتب: چند ورودی از هر shard؟ {#sec-04-10-3}

::: {.algo #alg-04-3 title="تعداد ورودی درخواستی از هر shard در ListObjects مرتب" src="src/rgw/driver/rados/rgw_rados.cc :: RGWRados::calc_ordered_bucket_list_per_shard، cls_bucket_list_ordered" complexity="هر صفحه O(s × k) ورودی از s shard و ادغام O(n log s)"}
:::

```text
pseudocode
per_shard(n, s) = max(8, 1 + ⌊n / s⌋ + sqrt(2 n ln s / s))     # تحلیل «توپ در سطل» Raab و Steger
k = per_shard(max_keys, shards)
از هر shard تا k ورودی بعد از marker بخوان (به‌صورت موازی)
ادغام مرتب ؛ اگر یک shard زودتر تمام شد و n ورودی نرسید: تلاش دوباره با k × 2^(expansion − 1) (حداکثر 1024 برابر)
```

**مثال عددی.** صفحه‌ی پیش‌فرض S3 هزار کلید است (max-keys = 1000). با 11 shard: ⌊1000 / 11⌋ = 90 و sqrt(2000 × ln 11 / 11) ≈ 20.9، پس k = 111 و کل ورودی‌های خوانده‌شده 1221 است، یعنی 22 درصد اضافه. با 101 shard: k = 1 + 9 + 9.6 ≈ 19 و کل 1919. با 1999 shard، ⌊1000 / 1999⌋ = 0 و ریشه حدود 2.8 است، اما حداقل 8 اعمال می‌شود و کل 15992 ورودی، یعنی 16 برابر نیاز، از 1999 شیء ایندکس خوانده می‌شود. هر shard هم یک فراخوانی cls جداگانه است. پس bucket با 1999 shard برای هر صفحه‌ی 1000 کلیدی 1999 عملیات cls به OSDها می‌فرستد. اگر برنامه فقط به فهرست نامرتب نیاز دارد (مثلاً پاک‌سازی یا پشتیبان‌گیری)، `allow-unordered=true` در API یا `--allow-unordered` در radosgw-admin این هزینه را حذف می‌کند.

![تعداد کل ورودی‌های ایندکسی که برای ساختن یک صفحه‌ی فهرست مرتب درخواست می‌شود، برحسب تعداد shard، برای max-keys برابر 1000 و 100. خط نقطه‌چین هم‌رنگ تعداد واقعی کلیدهای صفحه است. با shard کم، اضافه‌خوانی کم است. از جایی که n / s زیر 8 می‌رود، حداقل 8 غالب می‌شود، دو منحنی بر هم منطبق می‌شوند و هزینه با تعداد shard خطی بالا می‌رود. عددها فقط تلاش اول را نشان می‌دهند، پیش از گسترش ضریب](figures/ch04/f10_listing.png){#fig-04-f10_listing}

## نام شیءهای RADOS: head، tail و multipart {#sec-04-10-4}

::: {.algo #alg-04-4 title="چیدمان یک شیء S3 در RADOS" src="src/rgw/rgw_obj_manifest.cc :: RGWObjManifest::get_implicit_location؛ src/rgw/driver/rados/rgw_putobj_processor.cc :: AtomicObjectProcessor::prepare؛ src/rgw/driver/rados/rgw_obj_manifest.cc :: RGWObjManifest::generator::create_begin" complexity="O(size / stripe) شیء برای هر PUT"}
:::

```text
pseudocode
head_max = rgw_max_chunk_size (4 MiB)   # اگر placement داده‌ی inline دارد و tail در همان pool است، وگرنه 0
stripe   = rgw_obj_stripe_size (4 MiB، هم‌تراز با alignment pool)
prefix   = "." + rand_alnum(32) + "_"    (PUT عادی) ؛ name + "." + upload_id   (multipart)
location(part, stripe_no, ofs):
    part == 0 and ofs < head_max: شیء head = "<marker>_<name>"
    part == 0:                     ns shadow    "<marker>__shadow_" + prefix + stripe_no
    part > 0 and stripe_no == 0:   ns multipart "<marker>__multipart_" + prefix + "." + part
    part > 0:                      ns shadow    "<marker>__shadow_" + prefix + "." + part + "_" + stripe_no
```

**مثال عددی.** PUT یک فایل 10 MiB به نام `photo.jpg` در pool پیش‌فرض سه شیء RADOS می‌سازد. head با نام `<marker>_photo.jpg` چهار مگابایت اول داده را همراه xattrهای manifest، ACL و ETag نگه می‌دارد. دو شیء tail با نام‌های `<marker>__shadow_.<rand32>_1` (4 MiB) و `..._2` (2 MiB) بقیه را دارند. یک آپلود multipart با دو قطعه‌ی 10 مگابایتی برای `big.iso` این‌ها را می‌سازد: head بدون داده با manifest، و برای هر قطعه یک شیء `__multipart_big.iso.<upload>.N` با 4 MiB اول آن قطعه و دو stripe در ns shadow با نام‌های `big.iso.<upload>.N_1` و `.N_2`. کل یک شیء S3 بیست مگابایتی هفت شیء RADOS است. ETag چنین شیئی md5 الحاق md5 دودویی قطعه‌ها و پسوند «‎-2» است، نه md5 کل فایل. حذف شیء فوری فقط head را پاک می‌کند. tailها به صف GC (`radosgw-admin gc list`) می‌روند و بعد از `rgw_gc_obj_min_wait` پاک می‌شوند. به همین دلیل فضای pool پس از حذف انبوه بلافاصله آزاد نمی‌شود.

![بالا: یک PUT ساده‌ی 10 مگابایتی. head (زرد) چهار مگابایت اول و فراداده را دارد و دو stripe در namespace ‏shadow (آبی) با پیشوند تصادفی 32 نویسه‌ای بقیه را دارند. پایین: آپلود multipart با دو قطعه‌ی 10 مگابایتی. head بدون داده است و فقط manifest را دارد. هر قطعه یک شیء در namespace ‏multipart (قرمز) برای 4 مگابایت اول خود و دو stripe در namespace ‏shadow دارد. نام‌ها از get_implicit_location گرفته شده‌اند. marker و upload id نمادین هستند](figures/ch04/f11_manifest.png){#fig-04-f11_manifest}

# قابلیت‌های پیشرفته‌ی S3 در RGW {#sec-04-11}

## نسخه‌بندی و object lock {#sec-04-11-1}

با فعال کردن **versioning** روی bucket، هر بازنویسی یا حذف یک نسخه‌ی تازه می‌سازد و نسخه‌های قبلی قابل بازیابی‌اند. **object lock** یک گام جلوتر می‌رود: نسخه‌ها را برای مدت مشخص غیرقابل‌حذف و غیرقابل‌تغییر (WORM) می‌کند؛ قابلیتی کلیدی برای حفاظت پشتیبان‌ها در برابر باج‌افزار و الزامات قانونی نگه‌داری داده.

```bash
EP="--endpoint-url https://s3.example.com --profile ceph"
aws $EP s3api create-bucket --bucket vault --object-lock-enabled-for-bucket
aws $EP s3api put-object-lock-configuration --bucket vault \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":30}}}'
aws $EP s3 cp backup-2026-11-15.tar s3://vault/
aws $EP s3api list-object-versions --bucket vault
aws $EP s3api get-object-retention --bucket vault --key backup-2026-11-15.tar
```

| حالت | رفتار | چه کسی می‌تواند زودتر حذف کند؟ |
|---|---|---|
| GOVERNANCE | نسخه تا پایان مهلت قفل است | کاربری با مجوز `s3:BypassGovernanceRetention` |
| COMPLIANCE | نسخه تا پایان مهلت قفل است | هیچ کاربر S3ای، حتی مالک |
| Legal Hold | قفل بدون تاریخ پایان | تا وقتی برداشته نشود |

::: {.warn}
object lock در حالت COMPLIANCE از دید API S3 قطعی است، اما مدیر کلاستر با دسترسی `radosgw-admin` یا RADOS هنوز از نظر فنی می‌تواند داده را حذف کند. حفاظت واقعی در برابر مهاجمی که به اعتبارنامه‌ی مدیر کلاستر رسیده، نیازمند جداسازی دسترسی‌ها، پایش و نسخه‌ی خارج از سایت است. همچنین bucketی که با object lock ساخته شده را نمی‌توان بعداً بدون آن کرد؛ مدت پیش‌فرض را با دقت انتخاب کنید.
:::

## lifecycle، storage class و placement {#sec-04-11-2}

**placement target** تعیین می‌کند داده و index یک bucket در کدام poolها باشند. هر placement می‌تواند چند **storage class** داشته باشد که هر کدام به pool داده‌ی متفاوتی اشاره می‌کند. قاعده‌های **lifecycle** اشیاء را پس از مدتی به کلاس دیگر منتقل یا حذف می‌کنند.

![placement و storage class: داده‌ی تازه در کلاس STANDARD و پس از مدتی با lifecycle به کلاس سرد EC یا ذخیره‌سازی ابری بیرونی منتقل می‌شود](figures/ch04/f05_placement.png){#fig-04-f05_placement}

```bash
# تعریف کلاس COLD در zonegroup و zone پیش‌فرض
radosgw-admin zonegroup placement add --rgw-zonegroup default \
  --placement-id default-placement --storage-class COLD
radosgw-admin zone placement add --rgw-zone default \
  --placement-id default-placement --storage-class COLD \
  --data-pool default.rgw.cold.data --compression lz4
radosgw-admin period update --commit     # فقط اگر realm تعریف شده باشد
```

```json
{"Rules":[{"ID":"tiering","Status":"Enabled","Filter":{"Prefix":"logs/"},
  "Transitions":[{"Days":30,"StorageClass":"COLD"}],
  "Expiration":{"Days":365},
  "AbortIncompleteMultipartUpload":{"DaysAfterInitiation":7}}]}
```

```bash
aws $EP s3api put-bucket-lifecycle-configuration --bucket logs-bucket --lifecycle-configuration file://lc.json
radosgw-admin lc list
radosgw-admin lc process --bucket logs-bucket    # اجرای دستی برای آزمایش
```

::: {.tip}
در آزمایشگاه برای دیدن اثر lifecycle بدون صبر چندروزه، `rgw_lc_debug_interval` را مثلاً ۶۰ بگذارید تا هر «روز» lifecycle شصت ثانیه حساب شود. این گزینه را هرگز در production روشن نگذارید.
:::

در نسخه‌های جدید، lifecycle می‌تواند اشیاء را به یک ذخیره‌سازی ابری سازگار با S3 هم منتقل کند (**cloud transition**) و در Umbrella بازگرداندن از Glacier یا نوار (cloud restore) با ابزارهای مدیریتی و اعلان رویداد کامل‌تر شده است.

## سیاست bucket و IAM {#sec-04-11-3}

RGW زبان سیاست AWS را پشتیبانی می‌کند. نمونه‌ی زیر به کاربر `ci-bot` اجازه می‌دهد فقط در پیشوند `artifacts/` بنویسد:

```json
{"Version":"2012-10-17","Statement":[{
  "Effect":"Allow",
  "Principal":{"AWS":["arn:aws:iam:::user/ci-bot"]},
  "Action":["s3:PutObject","s3:GetObject"],
  "Resource":["arn:aws:s3:::builds/artifacts/*"]}]}
```

```bash
aws $EP s3api put-bucket-policy --bucket builds --policy file://policy.json
```

با account (از Squid) می‌توان همین سیاست‌ها را روی کاربران و گروه‌ها هم با APIهای IAM گذاشت و از STS برای اعتبارنامه‌ی موقت و AssumeRoleWithWebIdentity (OIDC) استفاده کرد.

## رمزنگاری سمت سرور {#sec-04-11-4}

RGW از SSE-C (کلید از کلاینت)، SSE-KMS (کلید از Vault یا KMIP یا Barbican) و SSE-S3 پشتیبانی می‌کند. در Umbrella رمزنگاری AES-256-GCM اضافه شده و CopyObject برای اشیای رمزشده هم کار می‌کند.

::: {.warn}
SSE-C و SSE-KMS فقط روی اتصال HTTPS مجازند. اگر TLS را در load balancer پایان می‌دهید، به RGW بگویید درخواست‌ها امن رسیده‌اند (`rgw_trust_forwarded_https = true`) و فقط وقتی این را روشن کنید که مطمئنید load balancer همیشه این هدر را خودش تنظیم یا پاک می‌کند.
:::

## اعلان رویداد و لاگ bucket {#sec-04-11-5}

RGW می‌تواند رویدادهایی مثل ساخت یا حذف شیء را به Kafka، AMQP (RabbitMQ) یا HTTP بفرستد؛ پایه‌ای برای پردازش رویدادمحور (مثلاً تولید thumbnail پس از آپلود عکس):

```bash
aws $EP sns create-topic --name uploads \
  --attributes '{"push-endpoint":"kafka://kafka.example.com:9092","persistent":"true"}'
aws $EP s3api put-bucket-notification-configuration --bucket photos \
  --notification-configuration '{"TopicConfigurations":[{"Id":"n1","TopicArn":"arn:aws:sns:default::uploads","Events":["s3:ObjectCreated:*"]}]}'
```

**Bucket logging** (ثبت درخواست‌های هر bucket در bucket دیگر) طبق مستندات از Tentacle اضافه شده و در Umbrella حالت journal، پشتیبانی از pool EC و دستورهای مدیریتی گرفته است.

# عملیات روزمره‌ی RGW {#sec-04-12}

## دستورهای پرکاربرد {#sec-04-12-1}

```bash
radosgw-admin bucket list
radosgw-admin bucket stats --bucket=photos
radosgw-admin bucket limit check            # shardهای نزدیک آستانه
radosgw-admin reshard list
radosgw-admin reshard add --bucket=photos --num-shards=101
radosgw-admin gc list --include-all | head
radosgw-admin gc process
radosgw-admin usage show --uid=alice --start-date=2026-11-01
radosgw-admin bucket check --bucket=photos --check-objects --fix
```

::: {.deep}
حذف شیء در RGW فوری فضا آزاد نمی‌کند. head object حذف می‌شود اما اشیای tail به **garbage collector** سپرده می‌شوند و پس از `rgw_gc_obj_min_wait` (پیش‌فرض دو ساعت) پاک می‌شوند. اگر حذف انبوه انجام دادید و `ceph df` تغییری نکرد، صف gc را ببینید. در کلاسترهای پرتراکنش ممکن است نیاز باشد پارامترهای `rgw_gc_max_concurrent_io` و `rgw_gc_processor_period` را تنظیم کنید.
:::

## عیب‌یابی {#sec-04-12-2}

::: {.debug}
نشانه‌ها و راه بررسی:

خطای `SignatureDoesNotMatch`: اختلاف ساعت کلاینت و سرور بیش از ۱۵ دقیقه، یا load balancer که هدر Host را تغییر می‌دهد، یا path-style در برابر virtual-host اشتباه.

خطای `NoSuchBucket` با وجود bucket: کلاینت virtual-host استفاده می‌کند ولی `rgw_dns_name` یا hostnames در zonegroup تنظیم نشده و RGW نام bucket را از Host تشخیص نمی‌دهد.

فهرست‌گیری بسیار کند: index روی HDD، bucket بدون shard کافی، یا میلیون‌ها نسخه‌ی حذف‌شده در bucket نسخه‌بندی‌شده.

هشدار `LARGE_OMAP_OBJECTS`: shardهای index بزرگ؛ با `radosgw-admin bucket limit check` bucket مقصر را پیدا کنید.

برای دیدن جزئیات یک درخواست، موقتاً `debug_rgw` را بالا ببرید: `ceph config set client.rgw debug_rgw 20` و پس از بازتولید مشکل، برگردانید.
:::

# تکمیلی و به‌روز {#sec-04-13}

- **ingress و certmgr در cephadm:** load balancer و گواهی‌ها حالا بخشی از ارکستراتورند.
- **account و IAM (Squid به بعد):** مدیریت سلف‌سرویس کاربران، گروه‌ها، نقش‌ها و سیاست‌ها؛ در Umbrella GetAccountSummary، PublicAccessBlock در سطح account، APIهای مدیریتی سهمیه‌ی account و S3 Object Ownership (غیرفعال‌سازی ACL) اضافه شده‌اند.
- **S3 GetObjectAttributes** در Tentacle اضافه شده و برای سازگاری با AWS، زمان LastModified به ثانیه گرد می‌شود.
- **dedup کامل اشیاء** در Umbrella به‌صورت پیش‌نمایش فنی آمده است.
- **cache D4N مبتنی بر Redis** در حال توسعه است.
- **اسکریپت Lua:** RGW اجازه می‌دهد در مراحل مختلف پردازش درخواست، اسکریپت Lua اجرا شود (مثلاً برای لاگ سفارشی یا تغییر رفتار)؛ Umbrella hook جدید `postAuth` را اضافه کرده است.

# جمع‌بندی و مرور {#sec-04-14}

## خلاصه‌ی فصل {#sec-04-14-1}

::: {.summary title="نکته‌های کلیدی"}

- RGW سرور HTTP بدون حالت است که S3 و Swift را روی RADOS پیاده می‌کند؛ با cephadm و سرویس ingress به‌سادگی مقیاس افقی می‌گیرد.
- هر شیء S3 یک head object، تعدادی tail و یک ورودی در index bucket دارد؛ index باید روی SSD و تکثیری باشد.
- کاربر، subuser، tenant و account سطوح مختلف هویت و چندمستاجری‌اند؛ برای طراحی تازه account را در نظر بگیرید.
- virtual-host نیازمند DNS wildcard، `rgw_dns_name` و گواهی wildcard است.
- Keystone و S3A اتصال RGW به OpenStack و اکوسیستم داده را ممکن می‌کنند.
- versioning، object lock، lifecycle، storage class، سیاست‌ها، SSE و اعلان رویداد RGW را به یک سرویس S3 کامل تبدیل کرده‌اند.

:::

## اشتباهات رایج {#sec-04-14-2}

- pool index روی HDD یا EC.
- اجرای یک نمونه‌ی RGW بدون load balancer.
- فراموش کردن lifecycle برای بارگذاری‌های چندبخشی نیمه‌کاره.
- انتظار آزاد شدن فوری فضا پس از حذف (بی‌اطلاعی از gc).
- ساخت bucket با object lock در حالت COMPLIANCE با مدت طولانی برای آزمایش.
- اختلاف ساعت بین کلاینت‌ها و RGW.

## تمرین عملی {#sec-04-14-3}

1. RGW را با دو نمونه و یک سرویس ingress مستقر کنید و با متوقف کردن یک نمونه نشان دهید سرویس قطع نمی‌شود.
2. یک کاربر با سهمیه‌ی ۱ گیگابایت بسازید و رفتار RGW را هنگام عبور از سهمیه ببینید.
3. یک bucket با versioning بسازید، فایلی را سه بار بازنویسی و سپس حذف کنید و با `list-object-versions` همه‌ی نسخه‌ها و delete marker را ببینید. نسخه‌ی دوم را بازیابی کنید.
4. یک storage class سرد روی pool EC بسازید و با lifecycle و `rgw_lc_debug_interval` انتقال اشیاء را در آزمایشگاه مشاهده کنید.
5. ۱۰۰٬۰۰۰ شیء کوچک در یک bucket بنویسید (مثلاً با `s3-benchmark` یا یک اسکریپت موازی) و با `bucket limit check` و `reshard list` رفتار resharding پویا را ببینید.

## پرسش‌های مرور {#sec-04-14-4}

1. چرا RGW را «بدون حالت» می‌نامیم و این چه اثری بر طراحی دسترس‌پذیری بالا دارد؟
2. یک شیء S3 بیست‌مگابایتی در RADOS به چه اشیایی تبدیل می‌شود؟
3. چرا pool index نباید EC یا روی HDD باشد؟
4. resharding پویا چه مشکلی را حل می‌کند و آستانه‌ی پیش‌فرض آن چیست؟
5. تفاوت tenant و account چیست؟
6. برای دسترسی virtual-hosted-style چه پیکربندی‌هایی لازم است؟
7. دو حالت GOVERNANCE و COMPLIANCE در object lock چه فرقی دارند؟
8. چرا پس از حذف انبوه اشیاء، فضای کلاستر فوراً آزاد نمی‌شود؟
9. گزینه‌ی `rgw_s3_auth_use_keystone` چه امکانی فراهم می‌کند؟
10. چرا S3A committers برای Spark روی RGW مهم‌اند؟

## منابع این فصل {#sec-04-14-5}

- مستندات Ceph — Ceph Object Gateway: https://docs.ceph.com/en/latest/radosgw/
- مستندات cephadm — سرویس RGW و ingress: https://docs.ceph.com/en/latest/cephadm/services/rgw/
- مستندات Ceph — مدیریت RGW با radosgw-admin: https://docs.ceph.com/en/latest/radosgw/admin/
- مستندات Ceph — User Accounts: https://docs.ceph.com/en/latest/radosgw/account/
- مستندات Ceph — یکپارچه‌سازی Keystone: https://docs.ceph.com/en/latest/radosgw/keystone/
- مستندات Ceph — placement و storage class: https://docs.ceph.com/en/latest/radosgw/placement/
- مستندات Ceph — resharding پویا: https://docs.ceph.com/en/latest/radosgw/dynamicresharding/
- مستندات Ceph — اعلان رویداد bucket: https://docs.ceph.com/en/latest/radosgw/notifications/
- مستندات Ceph — رمزنگاری سمت سرور: https://docs.ceph.com/en/latest/radosgw/encryption/
- مستندات Ceph — سازگاری API S3: https://docs.ceph.com/en/latest/radosgw/s3/
- مستندات Apache Hadoop — کانکتور S3A: https://hadoop.apache.org/docs/stable/hadoop-aws/tools/hadoop-aws/index.html
- مستندات AWS — S3 Object Lock: https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lock.html
