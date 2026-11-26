---
id: troubleshooting
lang: fa
---

این پیوست راهنمای فشرده‌ی برخورد با رایج‌ترین وضعیت‌های ناسالم است. هر ردیف از «نشانه» شروع می‌شود و به اولین فرمان‌های تشخیصی و جهت اصلاح می‌رسد. توضیح کامل هر مورد در فصل ذکرشده آمده است. برای مرور سریع دستورها به تفکیک حوزه، [پیوست ب: برگه‌ی تقلب دستورها](#appB) را ببینید.

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
| `OSDMAP_FLAGS` / `OSD_FLAGS` | `ceph health detail`، `ceph osd dump \| grep flags` | برداشتن پرچم‌هایی که از کار نگهداری مانده‌اند: `ceph osd unset <flag>`، یا برای OSD، میزبان یا کلاس `ceph osd unset-group <flags> <who>` | ۷، ۱۹ |
| `POOL_APP_NOT_ENABLED` | `ceph osd pool ls detail` | برچسب زدن pool: برای RBD `rbd pool init <pool>`، یا `ceph osd pool application enable <pool> <app>` | ۲، ۸ |
| `PG_NOT_SCRUBBED` / `PG_NOT_DEEP_SCRUBBED` | `ceph health detail`، `ceph osd dump \| grep flags`، `ceph config get osd osd_deep_scrub_interval` | فقط PGهای clean اسکراب می‌شوند: ابتدا PGهای degraded یا misplaced و پرچم‌های `noscrub`/`nodeep_scrub` را رفع کنید؛ سپس `ceph pg deep-scrub <pgid>` | ۱۹، ۳۲ |
| `POOL_TOO_FEW_PGS` / `POOL_TOO_MANY_PGS` | `ceph osd pool autoscale-status` | فقط در حالت `warn` ظاهر می‌شود: `ceph osd pool set <pool> pg_autoscale_mode on`، یا تنظیم دستی `pg_num` | ۱۹ |
| `POOL_NEAR_FULL` / `POOL_FULL` | `ceph df detail`، `ceph osd pool get-quota <pool>` | افزایش یا حذف سهمیه (`ceph osd pool set-quota <pool> max_bytes <bytes>`؛ مقدار ۰ آن را حذف می‌کند)، یا افزودن ظرفیت | ۷، ۱۹ |
| `PG_BACKFILL_FULL` / `PG_RECOVERY_FULL` | `ceph pg ls backfill_toofull`، `ceph osd df tree` | OSDهای پر جلوی recovery را گرفته‌اند: مانند `OSD_BACKFILLFULL` / `OSD_FULL` در بالا رفتار کنید | ۱۹ |
| `OSD_TOO_MANY_REPAIRS` | `ceph health detail`، `ceph device ls-by-daemon osd.N` | تعداد زیاد تعمیر هنگام خواندن، حتی بدون خطای scrub، نشانه‌ی دیسک رو به خرابی است: آن را بررسی و تعویض کنید، سپس `ceph tell osd.N clear_shards_repaired` | ۱۷، ۱۹ |
| `BLUESTORE_SLOW_OP_ALERT` | `ceph health detail`، لاگ OSD («slow operation observed») | معمولاً درایو رو به خرابی یا پربار: دستگاه را بررسی و در صورت نیاز تعویض کنید | ۱۲، ۱۷ |
| `DEVICE_HEALTH` | `ceph device ls`، `ceph device info <devid>` | OSD را out کنید، بگذارید داده جابه‌جا شود، سپس دیسک را تعویض کنید؛ `mgr/devicehealth/self_heal` می‌تواند out کردن را انجام دهد | ۷، ۱۹ |
| `AUTH_INSECURE_GLOBAL_ID_RECLAIM_ALLOWED` | `ceph health detail` (آیا `AUTH_INSECURE_GLOBAL_ID_RECLAIM` هم فعال است؟) | اگر نه، `ceph config set mon auth_allow_insecure_global_id_reclaim false`؛ وگرنه ابتدا کلاینت‌های قدیمی را به‌روز کنید | ۸ |
| `MDS_ALL_DOWN` / `FS_DEGRADED` | `ceph fs status`، `ceph orch ps --daemon-type mds` | برای هر rank ازکارافتاده یک MDS (یا standby) را بازگردانید؛ علت را در لاگ MDS ببینید | ۶ |

::: {.warn}
فرمان‌هایی مثل `mark_unfound_lost delete`، `osd lost`، `ceph-objectstore-tool --op remove` و `osd force-create-pg` داده را به‌طور دائم حذف می‌کنند. فقط پس از خروج همه‌ی گزینه‌های دیگر، با پشتیبان و با تأیید فرد دوم اجرا شوند.
:::

# گام‌به‌گام: PGی که active نمی‌شود

این روال از صفحه‌ی رسمی «Troubleshooting PGs» و کد peering در `src/osd/PeeringState.cc` پیروی می‌کند. ماشین حالتی که پشت آن است در فصل ۱۷ توضیح داده شده است.

## 1. PGها و نوع «گیرکردن» را پیدا کنید

```bash
ceph health detail | grep -E "PG_AVAILABILITY|stuck|down|incomplete"
ceph pg dump_stuck stale # هیچ OSDی وضعیت PG را گزارش نکرده است: احتمالاً همه‌ی OSDهایش down هستند
ceph pg dump_stuck inactive # مشکل peering
ceph pg dump_stuck unclean # recovery تمام نمی‌شود (اغلب شیء unfound)
ceph osd blocked-by # هر OSD جلوی چند PG را گرفته است
```

`stale` معمولاً یعنی OSDهایی که PG را نگه می‌دارند اجرا نمی‌شوند؛ پیش از هر کاری آن‌ها را راه بیندازید. `inactive` به peering و `unclean` به recovery اشاره دارد.

## 2. علت را از خود PG بپرسید و پیش از هر تغییری یک نسخه از پاسخ نگه دارید

```bash
ceph pg 2.1f query > pg-2.1f.json
jq '.state, .up, .acting' pg-2.1f.json
jq '.recovery_state[] | {name, comment, blocked, down_osds_we_would_probe, peering_blocked_by, peering_blocked_by_detail}' pg-2.1f.json
jq '.info.stats.blocked_by' pg-2.1f.json
```

## 3. پاسخ را بخوانید

رشته‌های ستون اول را حالت‌های peering در `PeeringState.cc` چاپ می‌کنند.

| آنچه `query` نشان می‌دهد | معنا | اقدام |
|---|---|---|
| `Started/Primary/Peering/GetInfo` برای مدت طولانی، `"blocked": "peering is blocked due to down osds"`، `down_osds_we_would_probe` | OSDهایی از یک بازه‌ی قبلی که ممکن است نوشتن پذیرفته باشند down هستند، پس peering نمی‌تواند وجود داده‌ی تازه‌تر روی آن‌ها را رد کند | آن OSDها را راه بیندازید؛ `ceph osd tree down` و لاگ‌هایشان علت down بودن را نشان می‌دهند |
| `peering_blocked_by` با `"starting or marking this osd lost may let us proceed"` | peering منتظر آن OSD است | آن را برگردانید. فقط اگر دیسکش قطعاً از دست رفته است: `ceph osd lost <id> --yes-i-really-mean-it` (هشدار بالا را ببینید) |
| `Started/Primary/Peering/Down` با `"not enough up instances of this PG to go active"` | تعداد نمونه‌های up از PG کم است | OSDها را برگردانید؛ `min_size` و دامنه‌های خرابی را بررسی کنید |
| `Started/Primary/Peering/Incomplete` با `"not enough complete instances of this PG"` | هیچ OSD upی تاریخچه‌ی کامل PG را ندارد | همه‌ی OSDهای ازکارافتاده‌ای را که ممکن است PG را داشته باشند راه بیندازید. برای pool با EC، صفحه‌ی رسمی حالت‌های PG یادآوری می‌کند که کاهش موقت `min_size` ممکن است recovery را ممکن کند؛ بعد آن را برگردانید |
| `Started/Primary/Peering/WaitUpThru` با `"waiting for osdmap to reflect a new up_thru for this osd"` | primary منتظر است MONها `up_thru` آن را ثبت کنند | quorum در MONها و شبکه‌ی میان این OSD و MONها را بررسی کنید |
| `peering_blocked_by_detail` شامل `peering_blocked_by_history_les_bound` | تازه‌ترین لاگ کامل روی OSDهای up از epochی که PG آخرین بار در آن active شد (`history.last_epoch_started`) قدیمی‌تر است؛ پس نوشتن‌هایی که پس از آن تأیید شده‌اند ممکن است گم شده باشند | OSDی را که نسخه‌ی تازه‌تر را داشت پیدا کنید: دیسک‌های قدیمی، OSDهایی که حذف شده‌اند یا هنوز down هستند |

## 4. درباره‌ی `osd_find_best_info_ignore_history_les`

توصیه‌هایی در اینترنت گاهی این گزینه را برای ردیف آخر پیشنهاد می‌کنند. در `PeeringState::find_best_info`، این گزینه باعث می‌شود peering از قید `history.last_epoch_started` بگذرد و یک لاگ قدیمی به‌عنوان مرجع انتخاب شود. سطح این گزینه `dev` است و توضیح خودش در `src/common/options/osd.yaml.in` می‌گوید: «THIS IS AN EXTREMELY DANGEROUS OPTION THAT SHOULD ONLY BE USED AT THE DIRECTION OF A DEVELOPER … typically leading to data loss». این از دست رفتن بی‌صداست: نوشتن‌هایی که به کلاینت گفته شده موفق بوده‌اند، بدون هیچ خطایی ناپدید می‌شوند. پیش از آنکه حتی به آن فکر کنید، همه‌ی OSDهایی را که ممکن است PG را داشته باشند برگردانید، PG را از هر نسخه با `ceph-objectstore-tool` استخراج کنید (فصل ۱۷) و در فهرست `ceph-users` بپرسید. هرگز آن را سراسری تنظیم نکنید و به محض peer شدن PG حذفش کنید.

# گام‌به‌گام: slow ops

این روال از بخش‌های «Blocked Requests or Slow Requests» و «Debugging Slow Requests» در صفحه‌ی رسمی عیب‌یابی OSD پیروی می‌کند. ردیاب op در کد در فصل ۱۷ توضیح داده شده است.

## 1. OSDها را پیدا کنید

```bash
ceph health detail | grep -A5 SLOW_OPS
ceph osd perf | sort -n -k2 | tail # تأخیر commit (میلی‌ثانیه) برای هر OSD
```

## 2. عملیات را از راه admin socket خود OSD ببینید

این فرمان‌ها را روی میزبان OSD اجرا کنید (در cephadm، داخل `cephadm shell --name osd.7`).

```bash
ceph daemon osd.7 dump_blocked_ops
ceph daemon osd.7 dump_ops_in_flight | jq '.ops[] | {age, description, flag: .type_data.flag_point}'
ceph daemon osd.7 dump_historic_slow_ops | jq '.ops[0].type_data.events'
ceph daemon osd.7 dump_historic_ops_by_duration | jq '.ops[0:3][] | {duration, description}'
```

| فرمان | خروجی (مقادیر پیش‌فرض از مستندات) |
|---|---|
| `dump_blocked_ops` | opهای در جریانی که از `osd_op_complaint_time` (۳۰ ثانیه) قدیمی‌ترند؛ همان آستانه‌ی هشدار |
| `dump_ops_in_flight` | همه‌ی opهایی که اکنون پردازش می‌شوند، با `age` و `flag_point` فعلی |
| `dump_historic_slow_ops` | opهای تمام‌شده‌ای که دست‌کم `osd_op_history_slow_op_threshold` (۱۰ ثانیه) طول کشیده‌اند؛ حداکثر `osd_op_history_slow_op_size` (۲۰) مورد نگه داشته می‌شود |
| `dump_historic_ops_by_duration` | opهای تمام‌شده‌ی `osd_op_history_duration` (۶۰۰ ثانیه) اخیر، حداکثر `osd_op_history_size` (۲۰) مورد، به ترتیب طولانی‌ترین |

هر چهار فرمان به `osd_enable_op_tracker` نیاز دارند (به‌طور پیش‌فرض روشن است).

## 3. رویداد با بیشترین مدت را پیدا کنید

در آرایه‌ی `type_data.events` هر op، رویدادی را که بیشترین مدت را دارد پیدا کنید و آن را با این جدول بخوانید:

| طولانی‌ترین رویداد | معنا | گام بعدی |
|---|---|---|
| `queued_for_pg` | صف PG انباشته شده است: بار هم‌زمان زیاد، یا چیدمان shard برای HDD زیر mClock | CPU و بار میزبان؛ نکته‌ی mClock در پایین |
| `waiting for peered`، `waiting for active`، `waiting for readable` | PG فعال نیست | روال بالا |
| `waiting for missing object`، `waiting for degraded object` | شیء منتظر recovery است | وضعیت recovery در PG |
| `waiting for rw locks`، یا تکرار `reached_pg` و `waiting for rw locks` | کلاینت‌های زیادی روی یک شیء می‌نویسند | کاهش نوشتن هم‌زمان روی آن شیء (اغلب یک shard شاخص RGW یا header یک image در RBD) |
| `started` (پیش از `op_commit`) | ورودی/خروجی کند روی دستگاه خود primary | `iostat`، داده‌ی SMART دستگاه، `BLUESTORE_SLOW_OP_ALERT` |
| `waiting for subops from [X,Y]` | رونوشت X یا Y کند است | همین گام‌ها روی OSD X یا Y و شبکه‌ی میان آن‌ها |

مدت رویداد `throttled` را نادیده بگیرید: مستندات توضیح می‌دهد که به دلیل یک تفریق بدون علامت، اغلب حدود ۴٬۲۹۴٬۹۶۷٬۲۹۵ ثانیه نشان داده می‌شود.

## 4. علت‌های رایج را بررسی کنید

صفحه‌ی رسمی این علت‌ها را فهرست کرده است:

- درایو رو به خرابی: `dmesg -T`، `smartctl -a <device>`، یا برای NVMe `nvme smart-log <device>`.
- شبکه: عضو ازکارافتاده‌ی bond، سیاست hash که فقط یک لینک را به کار می‌گیرد، ناهمخوانی MTU، خطای پورت یا لینک اشباع‌شده (فصل ۲۱).
- recovery با تنظیم بیش از حد: افزایش `osd_max_backfills` یا `osd_recovery_max_active`. زیر mClock این‌ها فقط با `osd_mclock_override_recovery_settings=true` اثر دارند، و پروفایل `high_recovery_ops` هم recovery را بر کلاینت‌ها مقدم می‌کند.
- میزبان پربار، مثلاً ماشین‌های مجازی که کنار OSDها اجرا می‌شوند.
- در کلاسترهای HDD با mClock، اگر بیشتر slow opها به `queued_for_pg` ختم می‌شوند: راه‌حل رسمی `osd_op_num_shards_hdd=1` همراه با `osd_op_num_threads_per_shard_hdd=5` است که به راه‌اندازی دوباره‌ی پلکانی OSDها نیاز دارد. این چیدمان از Squid 19.2.1 پیش‌فرض است (پیوست ح).

::: {.tip}
یک slow op روی یک OSD اغلب نشانه‌ی یک رونوشت کند یا یک لینک کند در جای دیگر است. برای «پاک کردن» slow opها چند OSD را هم‌زمان راه‌اندازی دوباره نکنید: ابتدا همان یک OSD یا لینکی را که پشت آن‌هاست پیدا کنید.
:::
