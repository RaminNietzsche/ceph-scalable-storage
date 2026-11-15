# نقشه‌ی راه (Roadmap)

این فایل کارهای برنامه‌ریزی‌شده برای نسخه‌های بعدی کتاب را نگه می‌دارد. هر مورد پس از نوشته شدن در متن فارسی، با همان شناسه‌ها به نسخه‌ی انگلیسی هم ترجمه می‌شود.

## Gaps vs 《Ceph分布式存储实战》 (2016)

### شکاف‌ها در برابر یک کتاب Ceph سال ۲۰۱۶

یک مقایسه‌ی موضوعی میان فهرست این کتاب و کتاب چینی 《Ceph分布式存储实战》 (۲۰۱۶، مثال‌ها بیشتر بر پایه‌ی Hammer و Jewel) نشان داد بیشتر موضوع‌های آن کتاب در این کتاب پوشش داده شده‌اند یا روش‌شان منسوخ شده است. شکاف‌های باقی‌مانده بیشتر **مطالعه‌ی موردی کاربردی** هستند، نه خلأ معماری. فهرست زیر به ترتیب ارزش عملی امروز مرتب شده است.

این مقایسه فقط برای پیدا کردن موضوع بود: هیچ متن، فهرست دستور یا شکلی از آن کتاب به این مخزن منتقل نمی‌شود و هر بخش تازه از روی مستندات رسمی و آزمایش خود ما نوشته خواهد شد.

| رتبه | موضوع (Topic) | فصل هدف | وضعیت |
|---:|---|---|---|
| 1 | درایو ابری روی RGW با Nextcloud و S3 سازگار (Cloud drive: Nextcloud on RGW/S3) — external storage، bucket مجازی در DNS، CORS و path-style | فصل ۴ | planned |
| 2 | تفکیک خواندن و نوشتن در جلوی RGW (Read/write split in front of RGW) — ACL روی متد HTTP در HAProxy کنار سرویس ingress، و دام‌های سازگاری پس از PUT | فصل ۴ (کنار §۴.۳.۲) | planned |
| 3 | پخش ویدئوی درخواستی با HLS و DASH روی RGW (VOD with HLS/DASH on RGW) — lifecycle برای قطعه‌های قدیمی، CDN، CORS و هشدار bucket عمومی | فصل ۴ | planned |
| 4 | دسترسی از ویندوز به روش امروزی (Windows access, the modern way) — SMB برای CephFS، کلاینت رسمی Ceph برای Windows، و initiator ‏NVMe/TCP برای ویندوز و VMware | فصل ۶ و فصل ۲ | planned |
| 5 | رابط REST ‏Admin Ops در RGW (RGW Admin Ops REST API) — چه زمانی به‌جای CLI، caps لازم، و چند مثال کاربر، bucket و سهمیه | فصل ۴ (ارجاع به امضای فصل ۴۱) | planned |
| 6 | الگوی «primary روی SSD، نسخه‌ها روی HDD» (Primary on SSD, replicas on HDD) — جعبه‌ی «الگو و دام» با primary-affinity و قاعده‌ی CRUSH، و چرا pool جدا معمولاً بهتر است | فصل ۸ یا ۱۶ | planned |
| 7 | CloudStack با RBD (CloudStack with RBD) — primary storage از نوع RBD، کوتاه و بدون هم‌وزنی با OpenStack | فصل ۲ (ارجاع در فصل ۳) | planned |
| 8 | CephFS برای HPC (CephFS for HPC) — کی CephFS و کی Lustre یا BeeGFS، و فشار فراداده با کلاینت‌های زیاد | فصل ۶ | planned |
| 9 | تکمیل تنظیم سیستم‌عامل و BIOS (OS and BIOS tuning additions) — irqbalance، پروفایل‌های tuned و چند sysctl شبکه | فصل ۲۱ (§۲۱.۸) | planned |

### Not adding (obsolete)

### موارد منسوخ که اضافه نمی‌شوند

- **Calamari** (و Romana، Diamond، salt-minion): جای آن را Ceph Dashboard گرفته است (فصل ۹).
- **ceph-deploy و ceph-disk**: ابزار امروزی cephadm است (فصل‌های ۱ و ۱۱).
- **FileStore و journal روی SSD** و نسبت‌های اندازه‌ی journal: جای آن را BlueStore گرفته است (فصل ۱۲).
- **همگام‌سازی federated با Region در Hammer**: multisite امروزی با realm، zonegroup و period (فصل‌های ۵ و ۴۲).
- **cache tier به‌عنوان راه‌حل تولیدی تازه**: فصل ۱۶ فقط معماری و مهاجرت به بیرون را می‌آورد.
- **iSCSI با tgtd**: دروازه‌ی NVMe-oF جایگزین است (§۲.۱۰.۱ و فصل ۳۱).
- **Hadoop روی CephFS با پلاگین قدیمی**: مسیر امروزی S3A است (§۴.۸).
- **COSBench**: از warp استفاده می‌شود (§۱۰.۷.۱).
- **Ceph-Dokan با خاموش کردن cephx**: از نظر امنیتی پذیرفتنی نیست.
- **ZStack**، و **Zabbix یا Diamond** به‌عنوان پایش اصلی (پشته‌ی امروزی Prometheus در فصل ۲۰ است).
- **اعداد سخت‌افزاری ۲۰۱۶** (NIC یک‌گیگابیتی، MON با ۱ گیگابایت RAM و مانند آن): جدول به‌روز در §۱.۵ است.
