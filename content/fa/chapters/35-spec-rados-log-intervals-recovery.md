---
chapter: 35
id: ch35
title: "بخش تخصصی (۲): RADOS — pg log، intervalها، missing و سازوکار recovery و backfill"
part: specialist
lang: fa
---

# پیش از شروع {#sec-35-1}

فصل ۱۷ ماشین حالت peering و انتخاب info معتبر را نشان داد و فصل ۳۲ رزرو و زمان‌بندی recovery را. این فصل لایه‌ی میانی را باز می‌کند: PG چگونه می‌فهمد کدام OSDها را باید بپرسد (past intervals و prior set)، log دو OSD چگونه ادغام می‌شود، با ورودی‌های **divergent** چه می‌کند، missing set چگونه ساخته می‌شود، log چه زمانی و چقدر trim می‌شود، و recovery و backfill در عمل شیء به شیء چه کار می‌کنند. نام توابع و پیش‌فرض‌ها با شاخه‌ی main مخزن ceph/ceph (نوامبر ۲۰۲۶) تطبیق داده شده است.

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-35-1-1}

- چه تغییری در OSDMap یک interval تازه می‌سازد و `maybe_went_rw` چگونه تعیین می‌شود؟
- PG چرا گاهی `down` می‌شود و `blocked_by` در `ceph pg query` (فیلد `peering_blocked_by`) چه می‌گوید؟
- `merge_log` با log جلوتر یا عقب‌تر یک peer چه می‌کند؟
- ورودی divergent چیست و پنج حالت رسیدگی به آن کدام‌اند؟
- طول pg log چگونه تعیین می‌شود و چه چیزی جلوی trim را می‌گیرد؟
- چه زمانی recovery بر پایه‌ی log کافی است و چه زمانی backfill لازم می‌شود؟
- backfill اشیا را چگونه مقایسه و منتقل می‌کند؟

## پیش‌نیاز {#sec-35-1-2}

فصل ۱۷ (peering)، فصل ۳۲ (scrub و recovery) و فصل ۳۴ (pg log روی دیسک و نسخه‌ها).

# info و history یک PG {#sec-35-2}

هر عضو PG یک `pg_info_t` دارد. فیلدهای کلیدی:

| فیلد | معنی |
|---|---|
| `last_update` | آخرین نسخه‌ای که در log این عضو هست |
| `last_complete` | تا این نسخه همه‌ی اشیا روی همین عضو کامل‌اند (هیچ missing قدیمی‌تری نیست) |
| `log_tail` | قدیمی‌ترین ورودی log |
| `last_backfill` | اشیای بزرگ‌تر از این (در ترتیب hobject_t) ممکن است روی این عضو نباشند؛ `MAX` یعنی backfill لازم نیست |
| `last_epoch_started` | آخرین epochی که PG روی این عضو active شد |
| `purged_snaps` | snapهایی که پاک‌سازی آن‌ها تمام شده است (فصل ۳۶) |
| `history` | یک `pg_history_t` مشترک میان اعضا |

`pg_history_t` تاریخچه‌ی PG را در سطح epoch نگه می‌دارد: `epoch_created`، `same_interval_since` (از کی up و acting تغییر نکرده)، `same_up_since`، `same_primary_since`، `last_epoch_started` و `last_interval_started` (آخرین باری که PG در هر جایی active شد)، `last_epoch_clean` و `last_interval_clean`، و زمان‌های scrub.

::: {.note}
`last_update` و `last_complete` دو مفهوم جدا هستند. یک replica ممکن است log را تا `1462'93` داشته باشد (last_update) ولی شیء A که در `1462'80` نوشته شده هنوز روی دیسکش نباشد. در این حالت `last_complete` ‏`1462'79` است و A در missing set آن عضو است.
:::

# past intervals و prior set {#sec-35-3}

## interval تازه چه زمانی شروع می‌شود؟ {#sec-35-3-1}

یک **interval** بازه‌ای از epochهاست که در آن نقشه‌ی PG ثابت بوده است. `PastIntervals::is_new_interval` در هر نقشه‌ی جدید بررسی می‌کند که آیا یکی از این‌ها تغییر کرده است یا نه: primary یا مجموعه‌ی acting، primary یا مجموعه‌ی up، `size` یا `min_size` pool، split یا merge (و حالت‌های pending آن‌ها)، `sort_bitwise`، `recovery_deletes`، پارامترهای stretch در CRUSH (`crush_count`، `crush_target`، `crush_barrier`، `crush_member`)، روشن شدن بهینه‌سازی‌های EC و در شاخه‌ی main ورود یا خروج PG از مهاجرت pool. پس عوض شدن `min_size` به‌تنهایی هم peering می‌آورد.

::: {.algo #alg-35-1 title="ثبت interval گذشته و تعیین maybe_went_rw" src="src/osd/osd_types.cc :: PastIntervals::is_new_interval، PastIntervals::check_new_interval" complexity="O(n) برای n عضو acting در هر نقشه‌ی جدید"}
:::

```text
pseudocode
check_new_interval(old, new, same_interval_since, last_epoch_clean):
    if not is_new_interval(old, new): return false
    i = interval(first = same_interval_since, last = new_epoch - 1,
                 acting = old_acting, up = old_up, primary = old_primary)
    if acting non-empty and primary != -1 and acting_set_writeable(old pool, old acting)
       and could_have_gone_active(acting shards):
        if up_thru[primary] >= i.first and up_from[primary] <= i.first:
            i.maybe_went_rw = true                    # primary خبر up_thru را به mon رسانده بود
        elif i.first <= last_epoch_clean <= i.last:
            i.maybe_went_rw = true                    # PG در این بازه clean شده، پس نوشتن داشته
        else: i.maybe_went_rw = false
    else: i.maybe_went_rw = false                     # acting کوچک‌تر از min_size
    past_intervals.add_interval(i)
```

نقش `up_thru` حیاتی است. primary پیش از active شدن با `MOSDAlive` از mon می‌خواهد `up_thru` او را دست‌کم تا epoch جاری بالا ببرد. اگر یک interval حتی آن‌قدر طول نکشیده باشد که up_thru ثبت شود، primary نمی‌توانسته active شود و هیچ نوشتنی در آن رخ نداده است. پس peering بعدی لازم نیست منتظر اعضای آن interval بماند.

## prior set و حالت down {#sec-35-3-2}

`PastIntervals::PriorSet` فهرست OSDهایی است که primary باید از آن‌ها info و log بگیرد. همه‌ی اعضای up و acting فعلی و همه‌ی اعضای intervalهای گذشته که اکنون up هستند در `probe` قرار می‌گیرند. سپس برای هر interval با `maybe_went_rw` از `last_epoch_started` به این سو:

::: {.algo #alg-35-2 title="ساخت prior set و تشخیص pg down" src="src/osd/osd_types.h :: PastIntervals::PriorSet::PriorSet؛ src/osd/osd_types.cc :: PastIntervals::iterate_mayberw_back_to" complexity="O(I × n) برای I interval و n عضو"}
:::

```text
pseudocode
for interval in past_intervals where maybe_went_rw, newest → last_epoch_started:
    up_now = {osd in interval.acting | osd is UP now or marked LOST}
    candidate_blocked_by = {osd in interval.acting | osd is DOWN now}
    if not recoverable(up_now) and candidate_blocked_by not empty:
        pg_down = true                               # ممکن است داده‌ای فقط روی آن‌ها باشد
        blocked_by += candidate_blocked_by
# recoverable: replicated → دست‌کم یک عضو ; EC → دست‌کم k shard متمایز
```

**مثال عددی.** PG ‏3.1f با size=3 و min_size=2 در interval ‏[1400, 1449] روی [12,4,27] بوده است. در epoch ‏1450 هر دو OSD 4 و 27 از کار افتاده‌اند و acting به [12] رسید. چون یک عضو کمتر از min_size است، interval ‏[1450, 1460] نوشتنی نداشته است (`maybe_went_rw=false`). حالا در epoch ‏1461 خود osd.12 هم down شد و 4 و 27 برگشتند. interval ‏[1400, 1449] نوشتنی بوده و اعضای up آن 4 و 27 هستند؛ برای replicated یک عضو کافی است، پس PG down نمی‌شود. اما اگر فقط osd.12 از این interval زنده مانده بود و آن هم اکنون down بود، `pg_down=true` و `blocked_by: [12]` می‌شد. راه برون‌رفت یا برگرداندن osd.12 است یا اعلام `ceph osd lost 12` که پذیرش از دست رفتن داده‌های احتمالی است.

```text
مثال (بخشی از ceph pg 3.1f query):
"recovery_state": [ { "name": "Started/Primary/Peering/Down",
    "comment": "not enough up instances of this PG to go active" },
  { "name": "Started/Primary/Peering",
    "probing_osds": [ "4", "27" ],
    "blocked": "peering is blocked due to down osds",
    "down_osds_we_would_probe": [ 12 ],
    "peering_blocked_by": [ { "osd": 12, "current_lost_at": 0,
        "comment": "starting or marking this osd lost may let us proceed" } ] } ]
```

![زمان‌خط intervalهای یک PG. هر تغییر در up یا acting یا min_size یک interval تازه می‌سازد. فقط intervalهایی که primary در آن up_thru گرفته یا PG در آن clean شده maybe_went_rw هستند و در prior set حساب می‌شوند. intervalی که acting آن از min_size کوچک‌تر بوده نادیده گرفته می‌شود](figures/ch35/f01_intervals.png){#fig-35-f01_intervals}

# ادغام log {#sec-35-4}

پس از اینکه primary با `find_best_info` (فصل ۱۷) عضوی را که معتبرترین log را دارد انتخاب کرد، log او را می‌گیرد و با `PGLog::merge_log` در log خودش ادغام می‌کند. برای replicaها هم `proc_replica_log` همین منطق را روی کپی log آن‌ها اجرا می‌کند تا missing هر replica محاسبه شود.

::: {.algo #alg-35-3 title="merge_log: ادغام log معتبر در log محلی" src="src/osd/PGLog.cc :: PGLog::merge_log، PGLog::rewind_divergent_log" complexity="O(E) برای E ورودی جدید یا divergent؛ به‌روزرسانی missing برای هر شیء"}
:::

```text
pseudocode
merge_log(olog from authoritative peer):
    assert overlap: log.head >= olog.tail and olog.head >= log.tail
    if olog.tail < log.tail:                      # گسترش دم
        splice older entries of olog before log; log.tail = olog.tail
    if olog.head < log.head:                      # ما جلوتر بودیم: ورودی‌های اضافه divergent هستند
        rewind_divergent_log(olog.head)
    if olog.head > log.head:                      # گسترش سر
        lower_bound = newest olog entry <= log.head
        divergent = log.rewind_from_head(lower_bound)   # ورودی‌هایی که olog آن‌ها را ندارد
        append olog entries after lower_bound; for each: missing.add_next_event(entry)
        _merge_divergent_entries(divergent)
        info.last_update = log.head = olog.head
        info.last_user_version = oinfo.last_user_version ; info.purged_snaps = oinfo.purged_snaps
```

افزودن هر ورودی جدید به missing ساده است: اگر شیء قبلاً missing نبوده، `have` همان `prior_version` ورودی و `need` نسخه‌ی ورودی می‌شود. اگر بوده، فقط `need` جلو می‌رود. برای ورودی `DELETE`، پرچم `FLAG_DELETE` گذاشته می‌شود تا recovery به‌جای کپی، حذف کند.

## ورودی‌های divergent {#sec-35-4-1}

ورودی **divergent** ورودی‌ای است که در log یک عضو هست ولی در log معتبر نیست؛ مثلاً primary قبلی نوشتنی را محلی ثبت کرد و پیش از رسیدن آن به بقیه از کار افتاد. چون کلاینت برای آن نوشتن هرگز پاسخ نگرفته (پاسخ فقط پس از commit همه‌ی acting داده می‌شود)، باید آن را **برگرداند**. `_merge_object_divergent_entries` ورودی‌ها را بر اساس شیء گروه می‌کند و برای هر شیء یکی از پنج حالت را اجرا می‌کند:

::: {.algo #alg-35-4 title="پنج حالت رسیدگی به ورودی‌های divergent یک شیء" src="src/osd/PGLog.h :: PGLog::_merge_object_divergent_entries" complexity="O(e) برای e ورودی divergent آن شیء"}
:::

```text
pseudocode
for each object hoid with divergent entries (sorted by version):
    if hoid > info.last_backfill: ignore                 # هنوز backfill نشده
    prior = prior_version of first divergent entry
    1) if log (authoritative) has a newer entry for hoid:
           nothing to do — merge_log already set missing to that newer version
    2) elif prior == eversion_t() or first entry is a clone:
           object should not exist: remove it from store, drop from missing
    3) elif hoid is already missing:
           if missing.have == prior: drop from missing ; else missing.need = prior
    4) elif every entry can_rollback() and version > olog.can_rollback_to:
           rollback each entry (EC: از stashهای rollback)   # شیء missing نمی‌شود
    5) else:
           remove object from store ; missing.add(hoid, need=prior, have=none)
```

حالت ۴ بیشتر در EC رخ می‌دهد، چون backend مربوط به EC برای هر نوشتن اطلاعات rollback (مثلاً نسخه‌ی قبلی xattrها یا طول قبلی شیء) نگه می‌دارد. در replicated بیشتر نوشتن‌ها rollback ندارند و حالت ۵ اجرا می‌شود: شیء حذف و از عضو دیگری با نسخه‌ی `prior` بازیابی می‌شود.

![ادغام log با ورودی divergent. عضو A تا 1462'95 نوشته ولی log معتبر عضو B تا 1462'93 است و سپس در epoch جدید 1470'94 و 1470'95 دارد. ورودی‌های 1462'94 و 1462'95 روی A divergent هستند، برگردانده یا حذف می‌شوند و شیء مربوط با نسخه‌ی prior در missing می‌نشیند](figures/ch35/f02_divergent.png){#fig-35-f02_divergent}

# طول log و trim {#sec-35-5}

هر چه log طولانی‌تر باشد، OSDی که مدت بیشتری خاموش بوده باز هم می‌تواند با log برگردد (بدون backfill)، ولی حافظه و فضای omap بیشتری مصرف می‌شود.

::: {.algo #alg-35-5 title="هدف طول log و محاسبه‌ی trim_to" src="src/osd/OSD.cc :: OSDService::get_target_pg_log_entries؛ src/osd/PeeringState.cc :: PeeringState::calc_trim_to" complexity="O(t) برای t ورودی‌ای که trim می‌شود"}
:::

```text
pseudocode
target = clamp(osd_target_pg_log_entries_per_osd / num_pgs_on_osd,
               min = osd_min_pg_log_entries, max = osd_max_pg_log_entries)
limit = min(min_last_complete_ondisk, can_rollback_to)
if log.size > target:
    n = min(log.size - target, osd_pg_log_trim_max)
    if n < osd_pg_log_trim_min: return                 # trim در دسته‌های بزرگ‌تر
    trim_to = version of the n-th oldest entry, but never beyond limit
```

| گزینه | پیش‌فرض main |
|---|---|
| `osd_target_pg_log_entries_per_osd` | 300000 |
| `osd_min_pg_log_entries` | 250 |
| `osd_max_pg_log_entries` | 10000 |
| `osd_pg_log_trim_min` | 100 |
| `osd_pg_log_trim_max` | 10000 |
| `osd_pg_log_dups_tracked` | 3000 |

**مثال عددی.** OSDی با ۲۰۰ PG: ‏300000/200 = 1500، که بین 250 و 10000 است؛ پس هدف 1500 ورودی برای هر PG است. با ۱۵۰۰ PG روی همان OSD ‏(فرض: pool بزرگ با pg_num زیاد) هدف به 200 می‌رسد و به حداقل 250 گرد می‌شود. پیامد عملی: هر چه PG بیشتری روی یک OSD باشد، log هر PG کوتاه‌تر است و OSDی که چند دقیقه خاموش بوده زودتر به backfill می‌افتد.

**چه چیزی جلوی trim را می‌گیرد؟** `min_last_complete_ondisk`، یعنی کمترین `last_complete` میان همه‌ی اعضای acting. اگر یک replica شیئی را missing داشته باشد، log از آن نقطه trim نمی‌شود، چون missing همان عضو به آن ورودی‌ها وابسته است. PGای که مدت طولانی degraded می‌ماند log بلندتری دارد و این در mempool ‏`osd_pglog` دیده می‌شود.

# recovery و backfill در عمل {#sec-35-6}

## log کافی است یا backfill؟ {#sec-35-6-1}

در `PeeringState::activate` برای هر عضو acting یا backfill تصمیم گرفته می‌شود. اگر `pg_log.get_tail() > peer.last_update` باشد، یعنی log ما دیگر ورودی‌های بعد از آخرین نسخه‌ی peer را ندارد، یا اگر `peer.last_backfill` خالی باشد (عضو تازه)، آن عضو **backfill** می‌شود: `last_backfill` او به ابتدا (`hobject_t()`) برمی‌گردد و از اول شیء به شیء پر می‌شود. در غیر این صورت ورودی‌های بعد از `peer.last_update` برایش فرستاده می‌شوند و missing او از روی همین ورودی‌ها ساخته می‌شود.

::: {.sim name="peering"}
:::

## ترتیب کار در start_recovery_ops {#sec-35-6-2}

::: {.algo #alg-35-6 title="ترتیب recovery در یک دور start_recovery_ops" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::start_recovery_ops، recover_primary، recover_replicas، recover_backfill" complexity="هر دور حداکثر max عملیات (بر پایه‌ی osd_recovery_max_active و mClock)"}
:::

```text
pseudocode
start_recovery_ops(max):
    if primary has no missing or all its missing are unfound:
        started = recover_replicas(max)                  # push به replicaهایی که missing دارند
    if started == 0:
        started += recover_primary(max)                  # pull برای missingهای خود primary
    if started == 0 and new unfound objects appeared:
        started = recover_replicas(max)
    if backfill targets exist and started < max and primary missing is empty
       and backfill reservation granted:
        started += recover_backfill(max - started)
    # main: سپس recover_pool_migration برای مهاجرت pool
```

recover_primary برای هر شیء missing منبعی از `missing_loc` (عضوی که آن نسخه را دارد) انتخاب و آن را **pull** می‌کند. recover_replicas شیء را از primary به replica **push** می‌کند. هر push حداکثر `osd_recovery_max_chunk` (پیش‌فرض 8 MiB) داده دارد و اشیای بزرگ‌تر در چند دور منتقل می‌شوند. اگر هیچ عضو up نسخه‌ی لازم را نداشته باشد، شیء **unfound** است (فصل ۱۷ و `ceph pg <pgid> list_unfound`).

## backfill: مقایسه‌ی دو پیمایش مرتب {#sec-35-6-3}

backfill از log استفاده نمی‌کند. primary و هر backfill target محتوای PG را به ترتیب hobject_t (فصل ۳۴) در **بازه‌های** کوچک پیمایش می‌کنند (`BackfillInterval`، با حداقل `osd_backfill_scan_min` ‏= 64 و حداکثر `osd_backfill_scan_max` ‏= 512 شیء در هر scan) و مثل ادغام دو فهرست مرتب، آن‌ها را مقایسه می‌کنند.

::: {.algo #alg-35-7 title="مقایسه‌ی بازه‌های backfill" src="src/osd/PrimaryLogPG.cc :: PrimaryLogPG::recover_backfill، scan_range_primary، scan_range_replica" complexity="O(N) برای N شیء PG؛ هر scan حداکثر osd_backfill_scan_max شیء"}
:::

```text
pseudocode
loop while ops < max:
    refill backfill_info (primary) and peer_backfill_info[t] when exhausted (MOSDPGScan)
    check = min(begin of all intervals)
    for each target t:
        if t's next object < check: t has extra object → send remove to t
    if primary has check:
        for targets whose version != primary version (and t.last_backfill < check):
            push check to them
    advance all intervals past check
    new_last_backfill = largest object fully handled on all targets
send MOSDPGBackfill PROGRESS(last_backfill) ; at end FINISH (last_backfill = MAX)
```

نوشتن‌های کلاینت در حین backfill هم ادامه دارند. اگر شیئی که نوشته می‌شود **پیش از** `last_backfill` هدف باشد، به‌طور عادی برای آن هدف تکثیر می‌شود. اگر بعد از آن باشد، فقط در log ثبت می‌شود و خود backfill بعداً نسخه‌ی تازه را منتقل می‌کند. شیئی که دقیقاً در حال backfill است برای نوشتن قفل می‌شود و op در `waiting_for_degraded_object` می‌ماند (فصل ۳۴).

![backfill به‌صورت ادغام دو پیمایش مرتب. بازه‌ی primary و بازه‌ی هدف هم‌زمان جلو می‌روند. شیء موجود فقط در هدف حذف می‌شود، شیء فقط در primary یا با نسخه‌ی متفاوت push می‌شود، و last_backfill پس از هر دور جلو می‌رود](figures/ch35/f03_backfill.png){#fig-35-f03_backfill}

# دستورها و عیب‌یابی {#sec-35-7}

| دستور | کاربرد |
|---|---|
| `ceph pg <pgid> query` | info همه‌ی اعضا، past_intervals، probing_osds، peering_blocked_by و recovery_progress |
| `ceph pg ls recovering` / `backfilling` / `down` / `incomplete` | فهرست PGها بر اساس حالت |
| `ceph pg <pgid> list_unfound` | اشیای unfound و OSDهایی که بررسی شده‌اند |
| `ceph pg <pgid> mark_unfound_lost revert` یا `delete` | آخرین راه برای unfound؛ داده از دست می‌رود |
| `ceph osd lost <id> --yes-i-really-mean-it` | اعلام از دست رفتن یک OSD تا peering منتظرش نماند |
| `ceph-objectstore-tool --op log --pgid <pgid>` | log، dups و missing یک PG روی OSD خاموش |
| `ceph-objectstore-tool --op export` / `import` | نجات یک PG از OSD معیوب |
| `ceph daemon osd.N dump_recovery_reservations` | رزروها (فصل ۳۲) |

```text
مثال (بخشی از ceph pg 3.1f query در حین backfill):
"info": { "last_update": "1470'2210", "last_complete": "1470'2210",
          "log_tail": "1468'710", "last_backfill": "MAX" },
"peer_info": [ { "peer": "31", "last_update": "1470'2210",
                 "last_backfill": "3:fa21c9e8:::rbd_data.5f3a2b8c1d4e.0000000000000c1a:head" } ],
"recovery_state": [ { "name": "Started/Primary/Active",
    "recovery_progress": { "backfill_targets": [ "31" ],
        "waiting_on_backfill": [], "last_backfill_started": "3:fa21c9e8:::rbd_data...0c1a:head",
        "backfill_info": { "begin": "3:fa21c9e8:::rbd_data...0c1a:head", "end": "3:fa2a...", "objects": [ "..." ] } } } ]
```

`last_backfill` هدف 31 یک hobject_t با کلید بیتی `fa21c9e8` است. چون بازه‌ی این PG در pg_num=32 از `f8000000` تا `ffffffff` است، با یک تقسیم ساده پیشرفت تقریبی به دست می‌آید: (0xfa21c9e8 − 0xf8000000) / 0x08000000 ≈ ٪۲۷.

## نشانه‌ها و راه‌حل‌ها {#sec-35-7-1}

- **PG در `peering` می‌ماند و `peering_blocked_by` دارد:** یک OSD که در interval نوشتنی عضو بوده down است. اول آن را برگردانید؛ `ceph osd lost` آخرین گزینه است.
- **PG ‏`incomplete`:** هیچ عضو زنده‌ای log کامل تا `last_epoch_started` ندارد. پیش از `osd_find_best_info_ignore_history_les` یا `export` و `import` با ceph-objectstore-tool، از OSDها پشتیبان بگیرید.
- **OSD پس از چند دقیقه خاموشی به backfill افتاد:** log کوتاه بوده است. تعداد PG هر OSD را بررسی کنید یا در تعمیرات برنامه‌ریزی‌شده زمان خاموشی را کوتاه‌تر کنید.
- **log بلند و حافظه‌ی زیاد:** PGهای degraded طولانی جلوی trim را گرفته‌اند. recovery را تمام کنید.

# تکمیلی و به‌روز {#sec-35-8}

- در شاخه‌ی main، پشتیبانی از نوشتن‌های جزئی EC (`written_shards` در pg_log_entry_t و `partial_writes_last_complete`) منطق divergent و backfill را برای EC پیچیده‌تر کرده است؛ برخی ورودی‌ها روی بعضی shardها اصلاً اعمال نشده‌اند و نباید آن‌ها را missing دانست.
- `recover_pool_migration` و `migrating_pgs` در شاخه‌ی main برای مهاجرت داده میان poolها اضافه شده‌اند. پیش از استفاده بررسی کنید در نسخه‌ی شما وجود دارند یا نه.
- Crimson منطق PeeringState را مستقیم به اشتراک می‌گذارد، ولی backfill را با یک ماشین حالت جدا (`crimson/osd/backfill_state.cc`) پیاده کرده است.

# تمرین عملی {#sec-35-9}

1. روی یک pool آزمایشی `min_size` را عوض کنید و در `ceph pg <pgid> query` تغییر `same_interval_since` را ببینید.
2. یک OSD را `noout` و خاموش کنید، چند هزار نوشتن انجام دهید و با `osd_max_pg_log_entries` کوچک آزمایش کنید که پس از بازگشت، OSD با log برمی‌گردد یا backfill می‌شود.
3. با `ceph-objectstore-tool --op log` روی یک OSD خاموش، فیلدهای `pg_missing` را پیدا کنید و `need` و `have` را با ورودی‌های log تطبیق دهید.
4. در حین backfill، `last_backfill` هدف را چند بار بخوانید و درصد پیشرفت را با روش کلید بیتی تخمین بزنید.

# پرسش‌های مرور {#sec-35-10}

1. چه تغییرهایی در OSDMap یک interval تازه می‌سازند؟ سه مورد غیر از up و acting نام ببرید.
2. `maybe_went_rw` در چه شرایطی true است؟
3. چرا up_thru برای ایمنی peering لازم است؟
4. چه زمانی PG ‏down می‌شود و `blocked_by` چه کسی را نشان می‌دهد؟
5. merge_log وقتی log معتبر جلوتر است چه کار می‌کند؟
6. ورودی divergent چیست و چرا برگرداندن آن ایمن است؟
7. حالت‌های ۴ و ۵ رسیدگی به divergent چه فرقی دارند؟
8. هدف طول log برای OSDی با ۶۰۰ PG با پیش‌فرض‌ها چقدر است؟
9. چه شرطی تعیین می‌کند یک عضو backfill شود؟
10. backfill چگونه تشخیص می‌دهد شیئی باید از هدف حذف شود؟

# منابع این فصل {#sec-35-11}

- osd_types.cc و osd_types.h (PastIntervals، PriorSet، pg_info_t، pg_missing_item): https://github.com/ceph/ceph/blob/main/src/osd/osd_types.cc
- PGLog.cc و PGLog.h (merge_log، divergent): https://github.com/ceph/ceph/blob/main/src/osd/PGLog.h
- PeeringState.cc (activate، calc_trim_to): https://github.com/ceph/ceph/blob/main/src/osd/PeeringState.cc
- PrimaryLogPG.cc (start_recovery_ops، recover_backfill): https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- مستند توسعه‌دهنده درباره‌ی peering: https://docs.ceph.com/en/latest/dev/peering/
- مستند توسعه‌دهنده درباره‌ی log-based PG: https://docs.ceph.com/en/latest/dev/osd_internals/log_based_pg/
- عیب‌یابی PG: https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/
