---
chapter: 41
id: ch41
title: "بخش تخصصی (۸): RGW — مسیر درخواست، SigV4، سهمیه، محدودیت نرخ، gc و lifecycle"
part: specialist
lang: fa
---

::: {.tldr}

- frontend از نوع Beast هر اتصال را در یک coroutine روی thread pool اجرا می‌کند؛ درخواست به یک op با گام‌های ثابت تبدیل می‌شود.
- احراز هویت SigV4 کلید امضا را از secret، تاریخ، region و سرویس می‌سازد؛ فصل یک مثال را گام‌به‌گام محاسبه می‌کند.
- quotaها نرم‌اند (در هر RGW cache می‌شوند) و rate limitها token bucket به ازای کاربر یا bucket هستند.
- tailهای حذف‌شده به صف gc می‌روند و بعداً آزاد می‌شوند؛ lifecycle در پنجره‌ی کاری روزانه اجرا می‌شود و `rgw_lc_debug_interval` آن را برای آزمون سریع می‌کند.

```bash
radosgw-admin ratelimit set --ratelimit-scope=user --uid=alice --max-read-ops=600 --max-write-bytes=104857600
```

[![خط لوله‌ی یک درخواست در RGW: Beast، انتخاب handler، احراز هویت، مجوزها، محدودیت نرخ و اجرا](figures/ch41/f01_pipeline.png)](#fig-41-f01_pipeline)

:::

# پیش از شروع {#sec-41-1}

فصل ۴۰ نشان داد داده‌ی RGW روی RADOS چگونه چیده می‌شود. این فصل همان داده را در حرکت دنبال می‌کند: یک درخواست HTTP از Beast تا اجرای op چه مراحلی را طی می‌کند، امضای SigV4 دقیقاً چگونه بازسازی و بررسی می‌شود، PUT و GET چگونه داده را در پنجره‌های موازی جابه‌جا می‌کنند، سهمیه و محدودیت نرخ در کجای مسیر و با چه حسابی اعمال می‌شوند، و دو کارگر پس‌زمینه یعنی gc و lifecycle کار خود را چگونه تقسیم و زمان‌بندی می‌کنند. پیش‌فرض‌ها از `src/common/options/rgw.yaml.in` در شاخه‌ی main (نوامبر ۲۰۲۶) خوانده شده‌اند.

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-41-1-1}

- چرا یک درخواست با امضای درست ممکن است با `RequestTimeTooSkewed` رد شود؟
- کلید امضای SigV4 از کلید محرمانه با چند HMAC به دست می‌آید؟
- سهمیه‌ی حجم با اندازه‌ی واقعی شیء مقایسه می‌شود یا با مقدار گردشده؟
- محدودیت نرخ در هر RGW جداگانه است یا در کل خوشه؟
- چرا پس از حذف یک bucket بزرگ، فضای pool تا چند ساعت آزاد نمی‌شود؟
- lifecycle کدام bucket را چه زمانی پردازش می‌کند؟

## پیش‌نیاز {#sec-41-1-2}

فصل ۴ (RGW)، فصل ۴۰ (مدل داده) و فصل ۲۱ (تنظیم کارایی).

# از سوکت تا op {#sec-41-2}

frontend پیش‌فرض **Beast** است (`rgw_frontends = "beast port=7480"`) که بر پایه‌ی Boost.Asio هر اتصال را در یک coroutine روی مجموعه‌ای از نخ‌ها (`rgw_thread_pool_size` ‏128) اجرا می‌کند. وقتی `rgw_beast_enable_async` روشن است (پیش‌فرض)، انتظار برای RADOS نخ را مسدود نمی‌کند و یک نخ می‌تواند هزاران درخواست هم‌زمان را جلو ببرد. `rgw_max_concurrent_requests` ‏(1024) سقف درخواست‌های در جریان است.

::: {.algo #alg-41-1 title="خط لوله‌ی پردازش یک درخواست" src="src/rgw/rgw_process.cc :: process_request، rgw_process_authenticated؛ src/rgw/rgw_asio_frontend.cc" complexity="هزینه‌ی ثابت هر درخواست: احراز هویت، خواندن ACL و policy از cache، سپس op->execute"}
:::

```text
pseudocode
process_request(req):
    s = req_state ; rest handler by dialect (S3, Swift, admin, STS ...) from URL and headers
    op = handler.get_op()                       # e.g. RGWPutObj_ObjStore_S3
    handler.authorize()                         # SigV4/V2, STS, anonymous ...
    normalize buckets and tenants
    rgw_process_authenticated(handler, op):
        init permissions                        # bucket and user policy, ACL (cached)
        reading permissions ; init op ; verifying op mask
        verifying CORS origin matches ; verifying op permissions (IAM + ACL)
        verifying op params ; pre-executing
        check rate limiting → 503 SlowDown + Retry-After when delayed
        executing: op->execute()                # RADOS I/O, quota check inside
        completing: op->complete() → response, ops log, usage log, bucket notification
```

هر مرحله با `debug_rgw = 2` در لاگ دیده می‌شود (مثلاً `req 123 0.000s s3:put_obj verifying op permissions`) و زمان نسبی کنار هر خط آمده است؛ همین ساده‌ترین راه برای یافتن مرحله‌ی کند است.

![خط لوله‌ی یک درخواست در RGW: Beast، انتخاب handler و op، احراز هویت، خواندن مجوزها، بررسی‌ها، محدودیت نرخ، اجرا و تکمیل. خطای هر مرحله مستقیم به پاسخ HTTP می‌رود](figures/ch41/f01_pipeline.png){#fig-41-f01_pipeline}

# امضای SigV4 {#sec-41-3}

::: {.algo #alg-41-2 title="بررسی امضای AWS SigV4" src="src/rgw/rgw_auth_s3.cc :: get_v4_canonical_headers، get_v4_string_to_sign، get_v4_signing_key، get_v4_signature؛ src/rgw/rgw_auth_s3.h :: RGW_AUTH_GRACE" complexity="پنج HMAC-SHA256 و یک SHA256 روی canonical request؛ کلید امضا قابل cache است"}
:::

```text
pseudocode
parse Authorization: AWS4-HMAC-SHA256 Credential=AK/YYYYMMDD/region/s3/aws4_request,
                     SignedHeaders=h1;h2;..., Signature=hex
reject if |now - x-amz-date| > RGW_AUTH_GRACE (15 min)      # RequestTimeTooSkewed
canonical = METHOD \n URI \n sorted query \n "name:value\n" for each signed header \n
            SignedHeaders \n payload hash (or UNSIGNED-PAYLOAD / STREAMING-...)
sts = "AWS4-HMAC-SHA256" \n x-amz-date \n "YYYYMMDD/region/s3/aws4_request" \n hex(sha256(canonical))
kDate = HMAC("AWS4" + secret, YYYYMMDD) ; kRegion = HMAC(kDate, region)
kService = HMAC(kRegion, "s3") ; kSigning = HMAC(kService, "aws4_request")
ok if hex(HMAC(kSigning, sts)) == Signature (constant-time compare)
streaming upload: every chunk carries its own signature chained from the previous one
```

**مثال عددی.** با یک کلید محرمانه‌ی ساختگی (`EXAMPLE/secret/NOT+A+REAL+KEY0000000000`)، region ‏`default`، تاریخ `20261115T071500Z` و درخواست `GET /photos/cat.jpg` با سه سرآیند امضاشده و `UNSIGNED-PAYLOAD`:

```text
مثال:
sha256(canonical request) = 36f24a8179a5bc758bde32b4a6932f313216b6c9f7d84e04e33bd7a2086b87f5
kSigning                  = 38793786cc844d69350de848f15fe23b8f7887e3bcbb48d552b2e0a2c1d9746d
Signature                 = 5e63a875b9d9e0ec540db8784929f6d4c5799c453bd5442804a9a7bc7f57aff8
```

تغییر یک بایت در هر کدام از ورودی‌ها امضا را کاملاً عوض می‌کند. دو خطای رایج: region امضا با `api_name` zonegroup یکی نیست (`SignatureDoesNotMatch`)، و یک proxy سرآیند `Host` را بازنویسی کرده است. با `debug_rgw = 20` ‏RGW متن canonical request و string to sign را چاپ می‌کند و می‌شود آن را با خروجی کلاینت مقایسه کرد.

![مشتق‌گیری کلید SigV4: چهار HMAC زنجیره‌ای از کلید محرمانه با تاریخ، region، سرویس و aws4_request، و HMAC پنجم روی string to sign که خودش هش canonical request را دارد](figures/ch41/f02_sigv4.png){#fig-41-f02_sigv4}

::: {.warn}
هیچ‌گاه لاگ `debug_rgw = 20` یک محیط واقعی را بدون پاک کردن سرآیندها به اشتراک نگذارید؛ مقدار Authorization، توکن‌های STS و گاهی بدنه‌ی درخواست در آن است.
:::

# PUT و GET در حرکت {#sec-41-4}

::: {.algo #alg-41-3 title="جریان داده در PUT و GET" src="src/rgw/driver/rados/rgw_putobj_processor.cc؛ src/rgw/rgw_op.cc :: RGWPutObj::execute، RGWGetObj::execute؛ src/rgw/driver/rados/rgw_rados.cc :: get_obj_iterate" complexity="PUT: O(size) با حداکثر rgw_put_obj_min_window_size بایت در پرواز؛ GET: پنجره‌ی rgw_get_obj_window_size"}
:::

```text
pseudocode
PUT:
    check quota (estimated size = Content-Length)            # before any data write
    processor = Atomic (or Multipart part / Append)
    loop body chunks: filter chain (compression, encryption, etag md5) → StripeProcessor → ChunkProcessor
        aio write chunk ; keep up to rgw_put_obj_min_window_size (16 MiB) in flight
    complete: wait aio ; index prepare → write head attrs + manifest → index complete (alg-40-1)
    old object's tail (if overwritten) → gc chain with tail_tag
GET:
    read head (attrs + up to first chunk of data) ; check conditions (If-Match, Range ...)
    walk manifest from range start: each RADOS read ≤ rgw_get_obj_max_req_size (4 MiB)
    keep up to rgw_get_obj_window_size (16 MiB) outstanding ; stream to client in order
    filters in reverse (decrypt, decompress)
```

بنابراین توان یک جریان واحد PUT یا GET تقریباً «پنجره تقسیم بر تأخیر یک نوشتن یا خواندن RADOS» است. برای شیء بزرگ روی یک اتصال پرتأخیر، بزرگ کردن پنجره‌ها کمک می‌کند ولی مصرف حافظه را به‌ازای هر درخواست بالا می‌برد. کلاینت‌های S3 معمولاً با multipart موازی همین محدودیت را دور می‌زنند.

# سهمیه {#sec-41-5}

::: {.algo #alg-41-4 title="بررسی سهمیه‌ی bucket و کاربر" src="src/rgw/rgw_quota.cc :: RGWQuotaHandlerImpl::check_quota، RGWQuotaInfoDefApplier، RGWQuotaInfoRawApplier؛ src/rgw/rgw_common.h :: rgw_rounded_objsize" complexity="O(1) با cache؛ بازخوانی آمار هر rgw_bucket_quota_ttl"}
:::

```text
pseudocode
check_quota(bucket, owner, num_objs = 1, size):
    for scope in (bucket quota, user quota) if enabled:
        stats = quota cache (refreshed after rgw_bucket_quota_ttl = 10 min, or on async update)
        if max_objects >= 0 and stats.num_objects + num_objs > max_objects → QuotaExceeded
        if max_size >= 0:
            if check_on_raw: exceeded = stats.size + size > max_size
            else:            exceeded = stats.size_rounded + round_up(size, 4096) > max_size
        → 403 QuotaExceeded
```

دو پیامد: سهمیه به‌ازای هر RGW از cache خوانده می‌شود، پس چند RGW هم‌زمان می‌توانند کمی از سقف عبور کنند (سهمیه «نرم» است)؛ و در حالت پیش‌فرض هر شیء دست‌کم 4 KiB حساب می‌شود، پس میلیون‌ها شیء 100 بایتی سهمیه را بسیار زودتر از حجم واقعی پر می‌کنند. آمار سهمیه‌ی کاربر با `radosgw-admin user stats --uid U --sync-stats` بازسازی می‌شود.

# محدودیت نرخ {#sec-41-6}

::: {.algo #alg-41-5 title="سطل توکن در هر RGW" src="src/rgw/rgw_ratelimit.h :: RateLimiterEntry؛ src/rgw/rgw_process.cc" complexity="O(1) به‌ازای هر درخواست؛ یک ورودی برای هر account، کاربر و bucket در حافظه‌ی هر RGW"}
:::

```text
pseudocode
tokens kept ×1000 (fixed point) ; interval = rgw_ratelimit_interval (60 s)
on request, levels checked in order: account, user, bucket (each with its own bucket of tokens):
    elapsed = now - ts ; refill = limit × elapsed / interval  (capped at limit)
    op type ∈ {read, write, list, delete}            # list/delete classes: main branch
    if ops tokens < 1 or bytes tokens < 0:
        delay = ceil(needed × interval / limit) seconds → 503 SlowDown, Retry-After: delay
    else take 1 op token
after response: subtract transferred bytes from read or write bytes bucket (may go negative)
if a lower level blocks, op tokens already taken at higher levels are given back
```

**مثال.** با `max-read-ops = 600` در بازه‌ی 60 ثانیه، سطل هر ثانیه 10 توکن پر می‌شود و حداکثر 600 توکن جمع می‌کند. کاربری که پس از یک دقیقه سکوت 700 GET پشت‌سرهم بفرستد، 600 درخواست اول پذیرفته و بقیه با 503 رد می‌شوند تا سطل پر شود. چون سطل در حافظه‌ی هر RGW است، پشت یک load balancer با چهار RGW سقف مؤثر تا چهار برابر می‌شود؛ مقدار را بر تعداد RGWها تقسیم کنید.

```bash
# مثال: تنظیم محدودیت برای یک کاربر
radosgw-admin ratelimit set --ratelimit-scope=user --uid=alice --max-read-ops=600 --max-write-bytes=104857600
radosgw-admin ratelimit enable --ratelimit-scope=user --uid=alice
radosgw-admin ratelimit get --ratelimit-scope=user --uid=alice
```

```text
مثال (خروجی):
{ "user_ratelimit": { "max_read_ops": 600, "max_write_ops": 0, "max_list_ops": 0, "max_delete_ops": 0,
                      "max_read_bytes": 0, "max_write_bytes": 104857600, "enabled": true } }
```

مقدار 0 یعنی نامحدود. فیلدهای list و delete فقط در نسخه‌هایی هستند که این دسته‌ها را دارند.

# garbage collection {#sec-41-7}

حذف یا بازنویسی یک شیء فقط head و ایندکس را فوراً عوض می‌کند. tailها در یک **زنجیره** (`cls_rgw_obj_chain`) با برچسب `tail_tag` به صف gc سپرده می‌شوند تا درخواست‌های GET در جریان که هنوز manifest قدیمی را دارند، tail را از دست ندهند.

::: {.algo #alg-41-6 title="صف gc و پردازش آن" src="src/rgw/driver/rados/rgw_gc.cc :: RGWGC::tag_index، send_chain، process؛ src/cls/rgw_gc" complexity="enqueue ‏O(1)؛ process ‏O(تعداد اشیای منقضی) با rgw_gc_max_concurrent_io حذف موازی"}
:::

```text
pseudocode
enqueue(chain, tag):
    shard = XXH64(tag, seed 8675309) mod rgw_gc_max_objs (32) → object gc.<shard> in <zone>.rgw.log:gc
    cls rgw_gc.queue_enqueue(entry{tag, chain, time = now + rgw_gc_obj_min_wait (2 h)})
    (split into several entries if chain too large for one queue entry)
gc thread every rgw_gc_processor_period (1 h), for up to rgw_gc_processor_max_time (1 h):
    for each shard in random start order:
        try lock "gc_process" on gc.<shard> ; skip if held by another RGW
        list expired entries ; delete each tail object (≤ rgw_gc_max_concurrent_io = 10 in flight)
        remove processed entries from queue (trim in chunks of rgw_gc_max_trim_chunk)
```

**مثال.** حذف bucket‌ای با یک میلیون شیء 64 MiB تقریباً ۱۵ میلیون tail ‏4 MiB به صف می‌فرستد. با پیش‌فرض‌ها هیچ‌کدام زودتر از ۲ ساعت حذف نمی‌شوند و هر RGW در هر چرخه‌ی ساعتی با ۱۰ حذف هم‌زمان کار می‌کند؛ اگر هر حذف ۵ میلی‌ثانیه طول بکشد، یک RGW در ساعت حدود ۷ میلیون tail پاک می‌کند. افزایش `rgw_gc_max_concurrent_io` یا اجرای دستی `radosgw-admin gc process --include-all` سرعت را بالا می‌برد ولی بار OSD را هم.

![زمان‌بندی gc و lifecycle. حذف شیء زنجیره‌ی tail را در صف یک شیء gc.N با زمان انقضای دوساعته می‌گذارد و نخ gc پس از قفل کردن shard آن را پاک می‌کند. نخ lifecycle در پنجره‌ی کاری روزانه shardهای lc.N را قفل می‌کند و برای هر bucket قواعد را اجرا می‌کند](figures/ch41/f03_gc_lc.png){#fig-41-f03_gc_lc}

# lifecycle {#sec-41-8}

::: {.algo #alg-41-7 title="زمان‌بندی و اجرای lifecycle" src="src/rgw/rgw_lc.cc :: get_lc_index، RGWLC::process، bucket_lc_process، LCOpAction_*؛ src/rgw/rgw_lc.h" complexity="هر bucket روزی یک بار؛ O(تعداد اشیای منطبق با prefixها) فهرست‌گیری"}
:::

```text
pseudocode
PutBucketLifecycle: store rules in bucket attr ; add entry "<tenant>:<bucket>:<marker>" to shard
    lc.<ceph_str_hash_linux(key) mod 7877 mod rgw_lc_max_objs (32)> in <zone>.rgw.log:lc
rgw_lc_max_worker (3) worker threads, active only inside rgw_lifecycle_work_time (00:00-06:00):
    pick shard ; lock "lc_process" (rgw_lc_lock_max_time 90 s, renewed) ; take next entry not done today
    bucket_lc_process(entry):
        skip if bucket marker != entry marker (bucket was recreated)
        group rules by prefix ; list objects (and versions) per prefix
        for each object, run matching actions with up to rgw_lc_max_wp_worker (128) parallel ops:
            CurrentExpiration, NonCurrentExpiration, DMExpiration (expired delete markers),
            CurrentTransition, NonCurrentTransition (copy tail to class pool, new manifest)
        abort incomplete multipart uploads older than N days
    mark entry complete with start time
```

نکته‌های عملیاتی: تاریخ انقضا بر پایه‌ی روز است و اجرا در پنجره‌ی کاری انجام می‌شود، پس «Expiration: 1 day» یعنی «در نخستین پنجره پس از گذشت یک روز». برای آزمایش، `rgw_lc_debug_interval` (پیش‌فرض ‎-1، خاموش) یک «روز» را به چند ثانیه کوتاه می‌کند و هرگز نباید در تولید روشن بماند. `radosgw-admin lc list` وضعیت هر bucket را نشان می‌دهد:

```text
مثال (خروجی lc list):
[ { "bucket": ":logs:a1b2c3d4-...4123.9", "shard": "lc.17", "started": "Sun, 15 Nov 2026 00:00:04 GMT", "status": "COMPLETE" },
  { "bucket": ":photos:a1b2c3d4-...4123.7", "shard": "lc.4",  "started": "Sun, 15 Nov 2026 00:00:06 GMT", "status": "PROCESSING" } ]
```

# دستورها با کلاینت‌های S3 {#sec-41-9}

| کار | aws cli | mc |
|---|---|---|
| تعریف endpoint | `aws --endpoint-url https://s3.example.test s3 ls` | `mc alias set c1 https://s3.example.test AK SK` |
| آپلود چندبخشی موازی | `aws configure set s3.multipart_chunksize 64MB` سپس `aws s3 cp f s3://b/` | `mc cp f c1/b/` |
| نسخه‌بندی | `aws s3api put-bucket-versioning --bucket b --versioning-configuration Status=Enabled` | `mc version enable c1/b` |
| فهرست نسخه‌ها | `aws s3api list-object-versions --bucket b` | `mc ls --versions c1/b` |
| lifecycle | `aws s3api put-bucket-lifecycle-configuration --bucket b --lifecycle-configuration file://lc.json` | `mc ilm rule add --expire-days 30 c1/b` |
| storage class | `aws s3 cp f s3://b/ --storage-class COLD` | `mc cp --storage-class COLD f c1/b/` |
| URL امضاشده | `aws s3 presign s3://b/k --expires-in 3600` | `mc share download --expire 1h c1/b/k` |

```bash
# مثال: یک lifecycle ساده با انتقال و انقضا
cat > lc.json <<'J'
{ "Rules": [ { "ID": "logs", "Status": "Enabled", "Filter": { "Prefix": "logs/" },
  "Transitions": [ { "Days": 30, "StorageClass": "COLD" } ],
  "Expiration": { "Days": 365 },
  "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 7 } } ] }
J
aws --endpoint-url https://s3.example.test s3api put-bucket-lifecycle-configuration --bucket logs --lifecycle-configuration file://lc.json
```

# تنظیم و عیب‌یابی {#sec-41-10}

| نشانه | علت محتمل | اقدام |
|---|---|---|
| `RequestTimeTooSkewed` | ساعت کلاینت یا RGW بیش از ۱۵ دقیقه اختلاف دارد | NTP/chrony |
| `SignatureDoesNotMatch` فقط پشت proxy | بازنویسی Host یا مسیر | ارسال Host اصلی، بررسی `rgw_dns_name` |
| 503 SlowDown با Retry-After | محدودیت نرخ | `ratelimit get`، تقسیم سقف بر تعداد RGW |
| 503 بدون Retry-After | `rgw_max_concurrent_requests` یا صف پر | افزایش RGW یا سقف، بررسی تأخیر OSD |
| QuotaExceeded زودتر از انتظار | گردکردن 4 KiB یا آمار کهنه | `user stats --sync-stats`، بررسی `check_on_raw` |
| فضای pool پس از حذف آزاد نمی‌شود | صف gc | شمردن ورودی‌های `gc list --include-all`، سپس `gc process` |
| lifecycle اجرا نمی‌شود | خارج از پنجره، قفل گیرکرده، marker کهنه | `lc list`، `lc process --bucket B` |

# تکمیلی و به‌روز {#sec-41-11}

- دسته‌های list و delete در محدودیت نرخ و سرآیند `Retry-After` در شاخه‌ی main دیده می‌شوند؛ در نسخه‌های قدیمی‌تر فقط read و write وجود داشت.
- صف gc بر پایه‌ی cls ‏`rgw_gc` (صف دو مرحله‌ای روی یک شیء) است؛ نسخه‌های قدیمی از omap استفاده می‌کردند و مسیر مهاجرت در `RGWGC::list` هنوز هر دو را می‌خواند.
- `rgw_lc_max_rules` ‏(1000) سقف قواعد یک bucket است.

# تمرین عملی {#sec-41-12}

1. یک درخواست GET را با یک اسکریپت پایتون (فقط hashlib و hmac) امضا کنید و با `curl` بفرستید. سپس یک سرآیند را عوض کنید و `SignatureDoesNotMatch` را ببینید.
2. برای یک کاربر سقف 60 read op در دقیقه بگذارید و با یک حلقه‌ی curl زمان اولین 503 و مقدار Retry-After را بیابید.
3. یک bucket با ۱۰۰ شیء ۱۰ MiB را حذف کنید و تعداد ورودی‌های `gc list --include-all` را پیش و پس از `gc process --include-all` بشمارید.
4. با `rgw_lc_debug_interval = 10` روی یک خوشه‌ی آزمایشی، یک قاعده‌ی Expiration یک‌روزه را ظرف چند ثانیه ببینید.

# پرسش‌های مرور {#sec-41-13}

1. مراحل اصلی `rgw_process_authenticated` به ترتیب کدام‌اند؟
2. RGW اختلاف زمان مجاز درخواست SigV4 را چقدر می‌گیرد و چه خطایی می‌دهد؟
3. کلید امضای SigV4 چگونه از کلید محرمانه مشتق می‌شود؟
4. چه چیزی توان یک جریان PUT را محدود می‌کند و کدام گزینه آن را تنظیم می‌کند؟
5. در حالت پیش‌فرض، سهمیه‌ی حجم شیء ۱۰۰ بایتی را چقدر حساب می‌کند؟
6. چرا سهمیه در RGW «نرم» است؟
7. محدودیت نرخ ۶۰۰ read op در دقیقه پشت سه RGW در عمل چقدر است؟
8. shard ‏gc یک زنجیره چگونه انتخاب می‌شود و چرا tail فوراً حذف نمی‌شود؟
9. lifecycle چگونه bucket را به shard می‌برد و در چه بازه‌ای کار می‌کند؟
10. چرا bucket_lc_process مقدار marker را بررسی می‌کند؟

# منابع این فصل {#sec-41-14}

- rgw_process.cc: https://github.com/ceph/ceph/blob/main/src/rgw/rgw_process.cc
- rgw_auth_s3.cc: https://github.com/ceph/ceph/blob/main/src/rgw/rgw_auth_s3.cc
- rgw_ratelimit.h: https://github.com/ceph/ceph/blob/main/src/rgw/rgw_ratelimit.h
- rgw_quota.cc: https://github.com/ceph/ceph/blob/main/src/rgw/rgw_quota.cc
- rgw_gc.cc: https://github.com/ceph/ceph/blob/main/src/rgw/driver/rados/rgw_gc.cc
- rgw_lc.cc: https://github.com/ceph/ceph/blob/main/src/rgw/rgw_lc.cc
- AWS Signature Version 4: https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_sigv-create-signed-request.html
- مستند gc و lifecycle در Ceph: https://docs.ceph.com/en/latest/radosgw/config-ref/
