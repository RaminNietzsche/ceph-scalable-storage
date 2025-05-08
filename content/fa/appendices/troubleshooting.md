---
id: troubleshooting
lang: fa
---

این پیوست راهنمای فشرده‌ی برخورد با رایج‌ترین وضعیت‌های ناسالم است. هر ردیف از «نشانه» شروع می‌شود و به اولین فرمان‌های تشخیصی و جهت اصلاح می‌رسد. توضیح کامل هر مورد در فصل ذکرشده آمده است.

# اصل کلی

1. پیش از هر اقدام، وضعیت را ثبت کنید: `ceph -s`، `ceph health detail` و `ceph osd tree`.
2. پرچم‌های پیشگیری را بشناسید: `noout` برای کارهای کوتاه نگهداری، و `norebalance` و `nobackfill` فقط با دلیل روشن. پس از پایان کار آن‌ها را بردارید.
3. هرگز چند تغییر را هم‌زمان انجام ندهید. هر تغییر را با یک فرمان بازگشت یادداشت کنید.

# جدول نشانه → اقدام

| نشانه (هشدار) | اولین فرمان‌ها | جهت اصلاح | فصل |
|---|---|---|---|
| `OSD_DOWN` / `OSD_HOST_DOWN` | `ceph osd tree down`، `journalctl -u ceph-*@osd.N`، `ceph orch ps --daemon-type osd` | بررسی دیسک، شبکه و حافظه؛ راه‌اندازی دوباره؛ اگر دیسک خراب است، `ceph orch osd rm N --replace` | ۱۷، ۱۹ |
| `PG_AVAILABILITY` (inactive، peering گیرکرده) | `ceph pg dump_stuck inactive`، `ceph pg <pgid> query \| jq .recovery_state` | یافتن OSD مسدودکننده (`blocked_by`، `down_osds_we_would_probe`) و بازگرداندن آن | ۸، ۱۷ |
| `PG_DEGRADED` / `undersized` | `ceph pg ls degraded`، `ceph osd df tree` | صبر برای recovery؛ بررسی کافی بودن دامنه‌ی خرابی برای size | ۸ |
| `OBJECT_UNFOUND` | `ceph pg <pgid> list_unfound` | ابتدا همه‌ی OSDهای قبلی را بالا بیاورید؛ فقط در آخر `mark_unfound_lost revert` | ۱۷ |
| `OSD_SCRUB_ERRORS` / `PG_DAMAGED` (inconsistent) | `rados list-inconsistent-obj <pgid> --format=json-pretty` | یافتن نسخه‌ی خراب (خطای خواندن دیسک، checksum)؛ سپس `ceph pg repair <pgid>` | ۱۷ |
| `OSD_NEARFULL` / `OSD_BACKFILLFULL` / `OSD_FULL` | `ceph osd df`، `ceph df detail` | افزودن ظرفیت، حذف داده، balancer؛ افزایش موقت `full_ratio` فقط برای خروج اضطراری | ۱۹، ۲۱ |
| `SLOW_OPS` | `ceph daemon osd.N dump_ops_in_flight`، `dump_historic_ops`، `ceph osd perf` | پیدا کردن رویدادی که op در آن مانده است (queued_for_pg، waiting for subops، commit)؛ بررسی دیسک کند یا شبکه | ۱۷، ۲۱ |
| `MON_DOWN` / quorum ازدست‌رفته | `ceph quorum_status` (اگر پاسخ دهد)، `ceph daemon mon.X mon_status` روی میزبان | بازگرداندن اکثریت؛ در بدترین حالت استخراج و تزریق monmap | ۷، ۱۸ |
| `MON_CLOCK_SKEW` | `chronyc tracking`، `ceph time-sync-status` | اصلاح NTP/chrony روی همه‌ی میزبان‌های MON | ۷ |
| `MON_DISK_LOW` / رشد store | `du -sh /var/lib/ceph/*/mon.*` | رفع علت عدم trim (PG ناسالم طولانی)؛ `ceph tell mon.X compact` | ۷ |
| `LARGE_OMAP_OBJECTS` | `ceph health detail`، لاگ cluster برای نام شیء | RGW: resharding یا trim لاگ‌های multisite؛ CephFS: بررسی دایرکتوری بسیار بزرگ | ۴، ۵ |
| `BLUEFS_SPILLOVER` | `ceph daemon osd.N bluefs stats`، `ceph osd metadata N` | افزایش اندازه‌ی DB یا انتقال آن به دستگاه سریع‌تر؛ compaction | ۱۲ |
| `MDS_SLOW_REQUEST` / `MDS_CLIENT_LATE_RELEASE` | `ceph tell mds.X dump_ops_in_flight`، `session ls` | یافتن کلاینتی که cap را پس نمی‌دهد؛ evict کنترل‌شده | ۶ |
| `MDS_TRIM_BEHIND` / `MDS_CACHE_OVERSIZED` | `ceph tell mds.X cache status`، `perf dump mds_log` | افزایش `mds_cache_memory_limit` یا کاهش بار؛ pinning | ۶ |
| `RECENT_CRASH` | `ceph crash ls-new`، `ceph crash info <id>` | تحلیل backtrace؛ سپس `ceph crash archive <id>` | ۱۷ |
| `MGR_MODULE_ERROR` | `ceph mgr module ls`، لاگ mgr | غیرفعال و فعال کردن دوباره‌ی ماژول؛ `ceph mgr fail` | ۹ |
| `CEPHADM_*` (مثلاً HOST_CHECK_FAILED) | `ceph orch host ls`، `ceph cephadm check-host <host>` | SSH، زمان، پکیج‌ها و podman/docker روی میزبان | ۱۱ |

::: {.warn}
فرمان‌هایی مثل `mark_unfound_lost delete`، `osd lost`، `ceph-objectstore-tool --op remove` و `osd force-create-pg` داده را به‌طور دائم حذف می‌کنند. فقط پس از خروج همه‌ی گزینه‌های دیگر، با پشتیبان و با تأیید فرد دوم اجرا شوند.
:::
