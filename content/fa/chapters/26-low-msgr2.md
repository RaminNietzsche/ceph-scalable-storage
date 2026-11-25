---
chapter: 26
id: ch26
title: "لایه‌های پایینی (۴): msgr2 در سطح بایت، AsyncConnection و EventCenter"
part: lower
lang: fa
---

::: {.tldr}

- msgr2 پروتکل سیمی Ceph است: یک banner و سپس frameهایی با preamble، segmentها و epilogue در حالت crc یا secure (AES-GCM).
- هر پیام چهار segment دارد: header، front، middle و data.
- AsyncConnection ماشین حالت هر اتصال را اجرا می‌کند و EventCenter رویدادهای socket را روی چند thread کارگر پخش می‌کند.
- فصل frameهای واقعی را بایت‌به‌بایت رمزگشایی می‌کند، مثل یک KEEPALIVE2 در حالت crc.

```bash {since=squid}
ceph daemon osd.4 messenger dump
```

[![دست‌دهی کامل msgr2: banner، HELLO، احراز هویت، توافق حالت اتصال و برپایی نشست](figures/ch26/f01_hs.png)](#fig-26-f01_hs)

:::

# مقدمه: سیم بین دو daemon {#sec-26-1}

هر پیامی که در Ceph رد و بدل می‌شود، چه درخواست نوشتن کلاینت به OSD، چه heartbeat بین OSDها و چه نقشه‌ای که mon منتشر می‌کند، از لایه‌ی messenger می‌گذرد. از Nautilus به بعد پروتکل پیش‌فرض msgr2 (پورت 3300 برای mon) است. این فصل آن را در سطح بایت باز می‌کند: banner آغازین، قالب frame با preamble و segmentها، دو حالت crc و secure (AES-GCM)، دست‌دهی احراز هویت، جلسه و بازاتصال، و در پایان ماشین وضعیت `ProtocolV2` و حلقه‌ی رویداد `EventCenter` که همه‌ی این‌ها را با تعداد کمی thread اجرا می‌کند. منبع ساختارها `src/msg/async/frames_v2.h`، `ProtocolV2.cc`، `crypto_onwire.cc` و `src/include/msgr.h` در شاخه‌ی main است.

::: {.summary}

- banner برابر `ceph v2\n` است، به‌همراه طول ۱۶ و دو ویژگی ۶۴ بیتی (supported و required). ویژگی‌های فعلی REVISION_1 (msgr2.1) و COMPRESSION هستند.
- هر frame با یک preamble ۳۲ بایتی آغاز می‌شود: tag، تعداد segment (حداکثر ۴)، طول و هم‌ترازی هر segment، flags و crc32c.
- حالت crc برای هر segment یک crc32c دارد. حالت secure با AES-128-GCM (کلید ۱۶، IV ۱۲ و tag ۱۶ بایتی) هم رمز و هم احراز اصالت می‌کند.
- پیش‌فرض‌ها: `ms_cluster_mode` و `ms_client_mode` برابر `crc secure`، و `ms_mon_*_mode` برابر `secure crc`.
- AsyncMessenger با `ms_async_op_threads=3` worker کار می‌کند. هر worker یک EventCenter مبتنی بر epoll (edge-triggered) دارد.

:::

# banner و مذاکره‌ی ویژگی {#sec-26-2}

نخستین بایت‌هایی که پس از برقراری TCP فرستاده می‌شوند، رمزنگاری نشده‌اند. `ProtocolV2::_banner_exchange` این ساختار را می‌سازد: رشته‌ی ۸ بایتی `CEPH_BANNER_V2_PREFIX = "ceph v2\n"`، یک u16 برای طول payload و سپس payload شامل دو u64، یعنی `CEPH_MSGR2_SUPPORTED_FEATURES` و `CEPH_MSGR2_REQUIRED_FEATURES`.

| بایت‌ها (مثال) | معنی |
|---|---|
| `63 65 70 68 20 76 32 0a` | «ceph v2\n» |
| `10 00` | طول payload = 16 (u16 LE) |
| `03 00 00 00 00 00 00 00` | supported = REVISION_1 (بیت 0) + COMPRESSION (بیت 1) = 3 |
| `00 00 00 00 00 00 00 00` | required = 0 |

::: {.note}
یک کلاینت قدیمی با banner نسخه‌ی ۱ (`ceph v027`) به یک پورت msgr2 وصل نمی‌شود، چون بایت‌های banner فرق دارند. به همین دلیل monها دو آدرس `v2:...:3300` و `v1:...:6789` را در `addrvec` منتشر می‌کنند. اگر `ms_bind_msgr1=false` باشد، کلاینت‌های قدیمی (و نسخه‌های قدیمی krbd پیش از پشتیبانی msgr2 در هسته‌ی ۵٫۱۱) نمی‌توانند وصل شوند.
:::

![دست‌دهی کامل msgr2. پس از banner، هر طرف HELLO (نوع entity و آدرسی که طرف مقابل را با آن می‌بیند) می‌فرستد. سپس احراز هویت cephx با AUTH_REQUEST، رفت و برگشت‌های MORE و AUTH_DONE (که global_id و حالت اتصال crc یا secure را تعیین می‌کند) انجام می‌شود. از این نقطه frameها در حالت انتخاب‌شده‌اند. AUTH_SIGNATURE (HMAC-SHA256 روی بایت‌های پیش از احراز) از دستکاری مرحله‌ی رمزنشده جلوگیری می‌کند. CLIENT_IDENT و SERVER_IDENT جلسه را با cookie و global_seq برقرار می‌کنند](figures/ch26/f01_hs.png){#fig-26-f01_hs}

::: {.deep}
**چرا AUTH_SIGNATURE؟** banner و HELLO و بخشی از مذاکره‌ی auth پیش از وجود کلید جلسه ارسال می‌شوند. مهاجمی در میانه می‌تواند مثلاً فهرست `preferred_modes` را تغییر دهد تا طرفین به‌جای secure روی crc توافق کنند (حمله‌ی downgrade). پس از AUTH_DONE، هر طرف `hmac_sha256` تمام بایت‌هایی را که **دریافت** کرده است (`pre_auth.rxbuf`) با کلید جلسه می‌فرستد و طرف دیگر آن را با بایت‌هایی که خودش **فرستاده** مقایسه می‌کند. هر تغییری در مسیر باعث قطع اتصال می‌شود.
:::

# frame در سطح بایت {#sec-26-3}

![ساختار frame در msgr2.1. preamble_block_t دقیقاً ۳۲ بایت است و طوری طراحی شده که مضرب بلوک AES (۱۶) باشد. در حالت crc، segment اول بلافاصله پس از preamble و همراه crc خودش می‌آید و اگر segment دیگری باشد، epilogue شامل late_status و crc بقیه‌ی segmentهاست. در حالت secure، preamble همراه ۴۸ بایت اول segment صفر یکجا رمز می‌شود و یک tag مربوط به GCM می‌گیرد. پیام‌ها چهار segment دارند: header2، front، middle و data (با هم‌ترازی صفحه برای کپی صفر)](figures/ch26/f02_frame.png){#fig-26-f02_frame}

| offset | اندازه | فیلد | توضیح |
|---|---|---|---|
| 0 | 1 | `tag` | نوع frame (جدول بعد) |
| 1 | 1 | `num_segments` | ۱ تا ۴ |
| 2 | 24 | `segments[4]` | هر کدام `length` (le32) و `alignment` (le16) |
| 26 | 1 | `flags` | مثلاً `FRAME_EARLY_DATA_COMPRESSED=0x1` |
| 27 | 1 | `_reserved` | صفر |
| 28 | 4 | `crc` | `ceph_crc32c(0, preamble, 28)` |

| Tag | مقدار | Tag | مقدار |
|---|---|---|---|
| HELLO | 1 | SESSION_RETRY | 13 |
| AUTH_REQUEST | 2 | SESSION_RETRY_GLOBAL | 14 |
| AUTH_BAD_METHOD | 3 | SESSION_RECONNECT_OK | 15 |
| AUTH_REPLY_MORE | 4 | WAIT | 16 |
| AUTH_REQUEST_MORE | 5 | MESSAGE | 17 |
| AUTH_DONE | 6 | KEEPALIVE2 | 18 |
| AUTH_SIGNATURE | 7 | KEEPALIVE2_ACK | 19 |
| CLIENT_IDENT | 8 | ACK | 20 |
| SERVER_IDENT | 9 | COMPRESSION_REQUEST | 21 |
| IDENT_MISSING_FEATURES | 10 | COMPRESSION_DONE | 22 |
| SESSION_RECONNECT | 11 | SESSION_RESET | 12 |

## مثال کامل: یک KEEPALIVE2 در حالت crc {#sec-26-3-1}

KEEPALIVE2 یک segment دارد که فقط `utime_t` است (sec و nsec، هرکدام u32). برای زمان 1700000000.5 ثانیه، frame کامل ۴۴ بایت است. این مقادیر را با یک کدگذار مستقل محاسبه کرده‌ایم:

| بایت‌ها | بخش |
|---|---|
| `12 01` | tag=18 (KEEPALIVE2)، num_segments=1 |
| `08 00 00 00 08 00` | segment 0: length=8، alignment=8 (`DEFAULT_ALIGNMENT = sizeof(void*)`) |
| `00 × 18` | سه segment خالی |
| `00 00` | flags، reserved |
| `d8 d5 f5 99` | crc preamble = 0x99F5D5D8 (seed 0) |
| `00 f1 53 65 00 65 cd 1d` | sec=1700000000، nsec=500000000 |
| `39 7f 34 4d` | crc segment = 0x4D347F39 (seed 0xFFFFFFFF) |

![همان قاب KEEPALIVE2 بالا، این بار به شکل شبکه‌ی بایت: preamble سی‌ودوبایتی با tag، تعداد segment و جدول چهار segment (سه‌تای آخر صفر)، سپس crc خود preamble، سپس segment هشت‌بایتی utime_t و در پایان crc آن segment. جمع 44 بایت است و چون فقط یک segment هست، epilogue ندارد. این کوچک‌ترین قاب پرتکرار روی یک اتصال بی‌کار است و مثلاً MonClient هر mon_client_ping_interval ثانیه یکی از آن را به mon می‌فرستد (send_keepalive)](figures/ch26/f05_kaframe.png){#fig-26-f05_kaframe}

چون فقط یک segment هست، epilogue ارسال نمی‌شود (در msgr2.1). سرور با KEEPALIVE2_ACK و همان timestamp پاسخ می‌دهد. کلاینت از این پاسخ برای سنجش «آخرین زمان زنده بودن» اتصال استفاده می‌کند (`mon_client_ping_interval` و heartbeatها).

## پیام: چهار segment {#sec-26-3-2}

`MESSAGE` همیشه چهار segment دارد (`SegmentIndex::Msg`): **HEADER (0)** که `ceph_msg_header2` است (seq، tid، type، priority، version، data_pre_padding_len، data_off، ack_seq، flags، compat_version)، **FRONT (1)** که بدنه‌ی اصلی کدگذاری‌شده‌ی پیام است (مثلاً فیلدهای MOSDOp)، **MIDDLE (2)** که به‌ندرت استفاده می‌شود، و **DATA (3)** که داده‌ی خام نوشتن یا خواندن است. هم‌ترازی segment داده `PAGE_SIZE_ALIGNMENT = 4096` است تا گیرنده بتواند بافر هم‌تراز با صفحه تخصیص دهد و داده را بدون کپی تا O_DIRECT در BlueStore ببرد (فصل ۲۳). `sizeof(ceph_msg_header2)` کمتر از ۴۸ است، بنابراین در حالت secure کل header در بخش inline قرار می‌گیرد و گیرنده با یک رمزگشایی می‌تواند طول بقیه را بداند.

# حالت secure: AES-128-GCM روی سیم {#sec-26-4}

وقتی `con_mode` برابر `CEPH_CON_MODE_SECURE` (0x2) باشد، `crypto_onwire.cc` با OpenSSL (`EVP_aes_128_gcm`) کار می‌کند: `AESGCM_KEY_LEN=16`، `AESGCM_IV_LEN=12` و `AESGCM_TAG_LEN=16`. nonce ساختاری ۱۲ بایتی است: یک بخش ثابت ۳۲ بیتی و یک شمارنده‌ی ۶۴ بیتی که برای هر frame افزایش می‌یابد. کلید و nonce اولیه از کلید جلسه‌ی cephx و `connection_secret` که در AUTH_DONE مبادله شده است، برای هر جهت جداگانه به دست می‌آیند.

```text
pseudocode: ارسال یک frame در حالت secure (msgr2.1، خلاصه‌ی این کتاب)
  plain_head = preamble(32) || segment0[0:48] (با صفر پر می‌شود اگر کوتاه‌تر باشد)
  out  = AES_GCM_encrypt(key_tx, nonce_tx, plain_head) || tag(16); nonce_tx.counter++
  if len(segment0) > 48 or num_segments > 1:
      rest = segment0[48:] || segment1 || segment2 || segment3   # هر کدام pad به 16
      out += AES_GCM_encrypt(key_tx, nonce_tx, rest || epilogue) || tag(16); nonce_tx.counter++
  send(out)
```

**سربار:** برای یک پیام کنترلی کوچک، حالت secure حدود ۹۶ بایت (۳۲ + ۴۸ + ۱۶) در برابر ۴۴ بایت حالت crc مصرف می‌کند. برای نوشتن ۴M، سربار ناچیز است، ولی هزینه‌ی CPU مربوط به AES-GCM (با AES-NI حدود چند گیگابایت در ثانیه در هر هسته) روی OSDهای پرترافیک NVMe قابل‌اندازه‌گیری است. به همین دلیل پیش‌فرض ترافیک داده `crc secure` است (crc ترجیح داده می‌شود) و برای mon `secure crc`.

| گزینه | پیش‌فرض | کاربرد |
|---|---|---|
| `ms_cluster_mode` | crc secure | OSD↔OSD |
| `ms_service_mode` | crc secure | حالت‌هایی که سرویس‌دهنده (OSD، MDS) می‌پذیرد |
| `ms_client_mode` | crc secure | ترجیح کلاینت |
| `ms_mon_cluster_mode` / `ms_mon_service_mode` / `ms_mon_client_mode` | secure crc | اتصال به mon |
| `ms_osd_compress_mode` | none | فشرده‌سازی روی سیم برای OSD |
| `ms_crc_data` / `ms_crc_header` | true / true | خاموش کردن crc در حالت crc (توصیه نمی‌شود) |

::: {.warn}
حالت crc **هیچ حفاظتی در برابر مهاجم** ندارد. crc فقط خطای تصادفی را تشخیص می‌دهد. اگر شبکه‌ی عمومی (public network) مشترک یا غیرقابل‌اعتماد است، `ms_client_mode=secure` و `ms_service_mode=secure` را در نظر بگیرید و تأثیر آن را روی CPU بسنجید. cephx در حالت crc فقط هویت را ثابت می‌کند، نه محرمانگی یا یکپارچگی پیام‌ها را.
:::

# جلسه، بازاتصال و reset {#sec-26-5}

اتصال‌های lossless (مثلاً OSD↔OSD یا کلاینت↔mon در برخی policyها) باید پس از قطع TCP **بدون از دست رفتن یا تکرار پیام** ادامه یابند. msgr2 برای این کار این حالت‌ها را نگه می‌دارد:

| متغیر | معنی |
|---|---|
| `client_cookie` / `server_cookie` | شناسه‌ی تصادفی جلسه که در CLIENT_IDENT و SERVER_IDENT تعیین می‌شود |
| `global_seq` | شمارنده‌ی سراسری messenger برای ترتیب‌دهی تلاش‌های اتصال (حل رقابت دو اتصال هم‌زمان) |
| `connect_seq` | تعداد بازاتصال‌های موفق این جلسه |
| `message seq` / `ack_seq` | شماره‌ی آخرین پیام دریافتی؛ پیام‌های تأییدنشده در صف ارسال مجدد می‌مانند |

```text
سناریوی بازاتصال (خلاصه‌ی این کتاب)
  کلاینت: SESSION_RECONNECT(addrs, client_cookie, server_cookie, global_seq, connect_seq, msg_seq)
  سرور:
    cookie ناشناخته (سرور restart شده)       → SESSION_RESET(full=true)  → جلسه‌ی تازه، صف‌ها خالی
    global_seq قدیمی‌تر از آنچه دیده‌ام       → SESSION_RETRY_GLOBAL(gs)  → دوباره با gs بزرگ‌تر
    connect_seq ناسازگار                     → SESSION_RETRY(cs)
    رقابت با اتصالی که خودم در حال برقراری‌ام → WAIT
    همه‌چیز درست                             → SESSION_RECONNECT_OK(msg_seq)
                                               ارسال مجدد پیام‌های بالاتر از msg_seq
```

::: {.deep}
**رقابت اتصال (connection race):** دو OSD ممکن است هم‌زمان به هم وصل شوند. هر طرف یک اتصال خروجی و یک ورودی دارد. ProtocolV2 با مقایسه‌ی آدرس‌ها (و `global_seq`) تصمیم می‌گیرد کدام اتصال بماند. طرف «بازنده» WAIT دریافت می‌کند و اتصال خودش را رها می‌کند، و اتصال برنده (`replacing`) جای آن را می‌گیرد. پیام‌های صف‌شده به اتصال برنده منتقل می‌شوند. باگ‌های قدیمی در همین منطق دلیل بسیاری از گزارش‌های «پیام تکراری» یا «اتصال گیرکرده» بودند.
:::

![ماشین وضعیت ProtocolV2. سمت connect از START_CONNECT با banner، HELLO، auth و فشرده‌سازی به SESSION_CONNECTING (جلسه‌ی تازه) یا SESSION_RECONNECTING (cookie قبلی) و در نهایت READY می‌رسد. سمت accept مسیر مشابهی دارد. در READY دریافت هر پیام از سه throttler (تعداد پیام، بایت‌های policy و صف dispatch) می‌گذرد. خطا در اتصال lossless به STANDBY یا بازاتصال با backoff (0.2 تا 15 ثانیه)، و در اتصال lossy به CLOSED منجر می‌شود](figures/ch26/f03_state.png){#fig-26-f03_state}

| throttle | گزینه یا policy | اثر وقتی پر است |
|---|---|---|
| THROTTLE_MESSAGE | `policy.throttler_messages` (مثلاً `osd_client_message_cap=256`) | خواندن از سوکت متوقف می‌شود، پس TCP backpressure به کلاینت می‌رسد |
| THROTTLE_BYTES | `policy.throttler_bytes` (مثلاً `osd_client_message_size_cap=500M`) | همان |
| THROTTLE_DISPATCH_QUEUE | `ms_dispatch_throttle_bytes=100M` | همان؛ محافظ حافظه‌ی صف dispatch |

# AsyncMessenger، Worker و EventCenter {#sec-26-6}

![مدل threading در AsyncMessenger. NetworkStack (پیش‌فرض Posix) تعداد ms_async_op_threads=3 Worker می‌سازد و هر Worker یک EventCenter دارد. هر اتصال هنگام ساخت به یکی از workerها سپرده می‌شود و تا پایان عمرش همان‌جا می‌ماند. حلقه‌ی هر worker ابتدا زمان‌سنج‌های سررسیده را اجرا می‌کند، سپس در epoll_wait (edge-triggered) منتظر رویدادهای fd می‌ماند و در پایان رویدادهای خارجی‌ای را اجرا می‌کند که threadهای دیگر صف کرده‌اند. threadهای دیگر worker را با نوشتن در یک eventfd (یا pipe در سیستم‌های بدون آن) بیدار می‌کنند](figures/ch26/f04_event.png){#fig-26-f04_event}

`EventCenter::process_events` در هر دور این کارها را انجام می‌کند:

1. زمان رسیدن نزدیک‌ترین رویداد زمانی را حساب می‌کند تا مدت انتظار تعیین شود (حداقل `ms_time_events_min_wait_interval`).
2. اگر poller فعال یا رویداد خارجی در صف نباشد، `event_wait` (یعنی `epoll_wait` در `EventEpoll.cc`) را تا آن زمان بلوک می‌کند.
3. برای هر fd آماده، `read_cb` یا `write_cb` ثبت‌شده را صدا می‌زند. برای اتصال‌ها، این‌ها `AsyncConnection::process` و `handle_write` هستند.
4. زمان‌سنج‌های سررسیده را اجرا می‌کند (مثلاً keepalive، timeout اتصال و backoff بازاتصال).
5. صف `external_events` را خالی و اجرا می‌کند. `AsyncConnection::send_message` از thread دیگری (مثلاً thread مربوط به PG در OSD) پیام را در `out_q` می‌گذارد و با `dispatch_event_external` نوشتن را در worker درست زمان‌بندی می‌کند.

::: {.note}
چون epoll در حالت `EPOLLET` (edge-triggered) ثبت می‌شود، handler باید تا `EAGAIN` بخواند یا بنویسد. در غیر این صورت، داده‌ی باقی‌مانده هیچ رویداد جدیدی ایجاد نمی‌کند. ProtocolV2 برای همین وضعیت خواندن را در continuationها (`CONTINUATION(...)`) نگه می‌دارد و با بازگشت `nullptr` منتظر داده‌ی بیشتر می‌ماند.
:::

**چرا فقط سه thread؟** پردازش پروتکل (رمزنگاری یا crc، تجزیه‌ی frame و throttle) سبک است و کار اصلی در thread pool‌های OSD (`osd_op_num_threads_per_shard`) انجام می‌شود. سه worker معمولاً برای ده‌ها هزار اتصال کافی است، ولی با حالت secure روی OSDهای NVMe پرترافیک، این workerها ممکن است گلوگاه CPU شوند. در این صورت `top -H -p <pid>` threadهایی با نام `msgr-worker-N` را نشان می‌دهد که نزدیک ۱۰۰٪ هستند.

```bash {since=squid}
top -H -p $(pidof -s ceph-osd)            # msgr-worker-0..2
ceph daemon osd.4 perf dump AsyncMessenger::Worker-0 | jq '.[] | {msgr_recv_messages, msgr_send_messages, msgr_running_total_time}'
ceph daemon osd.4 messenger dump        # بدون آرگومان فهرست messengerها؛ با نام یکی، اتصال‌هایش
ss -tinp | grep ceph-osd | head            # cwnd، rtt و retrans برای هر اتصال
tcpdump -i any -s 128 -w /tmp/msgr.pcap port 3300   # banner و preamble در crc mode قابل دیدن است
```

::: {.debug}
Wireshark تجزیه‌گر Ceph دارد، ولی پشتیبانی آن از msgr2 محدود است. در حالت crc می‌توانید با جدول tag این فصل، preamble را دستی بخوانید: بایت ۰ برابر tag و بایت‌های ۲ تا ۵ برابر طول segment اول (LE) است. در حالت secure، بعد از banner و HELLO همه‌چیز رمز است.
:::

# حساب دقیق اندازه‌ی قاب روی سیم {#sec-26-7}

`FrameAssembler` در `frames_v2.h` برای هر بخش قاب تابع جداگانه‌ای دارد: `get_preamble_onwire_len`، `get_segment_onwire_len` و `get_epilogue_onwire_len`. با این سه تابع می‌توان سربار دقیق هر پیام را پیش از ارسال حساب کرد.

::: {.algo #alg-26-1 title="طول قاب msgr2.1 روی سیم" src="src/msg/async/frames_v2.h :: FrameAssembler::get_preamble_onwire_len، get_segment_onwire_len، get_epilogue_onwire_len، get_frame_onwire_len" complexity="O(تعداد segmentها) = O(1) (حداکثر 4)"}
:::

```text
pseudocode
preamble = secure ? 32 + 48 (inline) + 16 (tag) : 32
seg(i):
    if secure:
        p = round_up(len_i, 16)
        if i == 0: return p > 48 ? p + 16 − 48 : 0       # تا 48 بایت درون preamble جا می‌شود
        return p
    return (i == 0 and len_0 > 0) ? len_0 + 4 : len_i        # crc جدا برای segment 0
epilogue = (تنها یک segment) ? 0 : secure ? 16 + 16 : 1 + 3×4
total = preamble + Σ seg(i) + epilogue
```

**مثال عددی.** یک پیام MESSAGE را در نظر بگیرید با segment 0 = ceph_msg_header2 (packed، 41 بایت)، front = 200 بایت، middle = 0 و data = 4096 بایت. داده‌ی منطقی 4337 بایت است.

- **حالت crc:** 32 + (41 + 4) + 200 + 0 + 4096 + 13 = 4386 بایت، یعنی 49 بایت سربار (1.1٪).
- **حالت secure:** 96 + 0 (هدر 41 بایتی به 48 گرد می‌شود و کامل در preamble جا می‌گیرد) + 208 + 0 + 4096 + 32 = 4432 بایت، یعنی 95 بایت سربار (2.2٪).

برای KEEPALIVE2 در حالت crc عدد همان 44 بایت جدول بالاست، چون فقط یک segment دارد و epilogue ندارد. در secure، segment هشت‌بایتی به 16 گرد می‌شود و درون preamble جا می‌گیرد، پس کل قاب 96 بایت است.

![مقایسه‌ی بایت‌های روی سیم برای یک پیام با داده‌ی 4 KiB در دو حالت crc و secure. در crc، segment 0 crc چهاربایتی خودش را دارد و epilogue سیزده‌بایتی crc سه segment دیگر را. در secure، preamble جای 48 بایت inline و تگ GCM شانزده‌بایتی را دارد، پس هدر پیام بدون قاب جداگانه رمز می‌شود. front به مضرب 16 گرد می‌شود و epilogue یک بلوک 16 بایتی به‌اضافه‌ی تگ است. نوار داده برای خوانایی در 1000 بایت بریده شده است](figures/ch26/f07_onwire.png){#fig-26-f07_onwire}

# nonce در AES-GCM و جلوگیری از بازاستفاده {#sec-26-8}

![چیدمان 40 بایت ابتدایی connection_secret که cephx در پایان احراز هویت به هر دو طرف می‌دهد: 16 بایت کلید AES-128 مشترک، سپس nonce دوازده‌بایتی دریافت و nonce دوازده‌بایتی ارسال. هر nonce یک بخش ثابت چهاربایتی و یک شمارنده‌ی هشت‌بایتی دارد. سمت سرور با پرچم crossed نقش rx و tx را جابه‌جا می‌کند تا هر جهت nonce مستقل داشته باشد](figures/ch26/f06_secret.png){#fig-26-f06_secret}

::: {.algo #alg-26-2 title="مدیریت nonce در AES-128-GCM" src="src/msg/async/crypto_onwire.cc :: rxtx_t::create_handler_pair، AES128GCM_OnWireTxHandler::reset_tx_handler، AES128GCM_OnWireRxHandler::reset_rx_handler" complexity="O(1) برای هر قاب؛ رمزگذاری O(L) با AES-NI"}
:::

```text
pseudocode
create_handler_pair(secret, crossed):
    key = secret[0:16] ; rx = secret[16:28] ; tx = secret[28:40]
    Tx = AESGCM(key, crossed ? rx : tx) ; Rx = AESGCM(key, crossed ? tx : rx)
reset_tx_handler(segments):
    if nonce == initial_nonce:
        if used_initial_nonce: throw "nonce reuse"     # چرخه‌ی کامل شمارنده
        used_initial_nonce = true
    EVP_EncryptInit_ex(..., iv = nonce)
    if msgr2.1: nonce.counter += 1  else: nonce.fixed += 1   # msgr2.0: سرریز پس از 2^32
```

**مثال عددی.** یک OSD با 10000 قاب در ثانیه روی یک اتصال، در msgr2.0 پس از $2^{32} / 10^4 \approx 429497$ ثانیه (حدود 5 روز) به nonce اولیه برمی‌گشت و اتصال باید reset می‌شد. در msgr2.1 شمارنده‌ی 64 بیتی $2^{64} / 10^4 \approx 5.8 \times 10^7$ سال دوام می‌آورد. GCM هم برای هر nonce حداکثر حدود 64 GiB داده را مجاز می‌داند ($2^{32}$ بلوک 16 بایتی)، و قاب‌های msgr با سقف segment از این بسیار کوچک‌ترند.

# حلقه‌ی EventCenter و بیدار شدن بین threadها {#sec-26-9}

::: {.algo #alg-26-3 title="حلقه‌ی رویداد Worker" src="src/msg/async/Event.cc :: EventCenter::process_events، dispatch_event_external، wakeup؛ src/msg/async/Stack.cc :: NetworkStack::add_thread" complexity="O(k) برای k fd آماده + O(t) رویداد زمان‌دار سررسیده + O(e) رویداد خارجی در هر دور"}
:::

```text
pseudocode
loop (هر Worker، msgr-worker-N): process_events(30 s)
process_events(timeout):
    if نخستین time event < now + timeout: timeout = max(آن فاصله، 1000 µs) ; trigger_time = true
    if pollers یا external_num_events > 0: timeout = 0
    n = epoll_wait(timeout)
    for each fd آماده: read_cb و/یا write_cb
    if trigger_time: process_time_events()
    if external_num_events: lock ; swap(external_events) ; unlock ; do_request روی همه
dispatch_event_external(e) (از thread دیگر):
    lock ; external_events.push(e) ; external_num_events++ ; unlock
    if thread جاری همان Worker نیست: wakeup() ⇒ write(eventfd, 1)
```

**مثال عددی و تأخیر.** یک thread از op shard در OSD پاسخ یک op را آماده می‌کند و `send_message` را صدا می‌زند. اتصال به msgr-worker-1 تعلق دارد، پس ارسال به شکل رویداد خارجی صف می‌شود و eventfd بیدار می‌شود. هزینه‌ی این مسیر یک write روی eventfd، یک بیدار شدن epoll_wait (معمولاً چند میکروثانیه تا چند ده میکروثانیه، بسته به بار و تنظیمات C-state) و سپس writev روی سوکت است. اگر Worker در آن لحظه مشغول پردازش fdهای دیگر باشد، رویداد تا پایان همان دور منتظر می‌ماند. به همین دلیل یک Worker که هم‌زمان صدها اتصال پرترافیک دارد، تأخیر دنباله‌دار (tail latency) را بالا می‌برد. کف 1000 میکروثانیه‌ای `ms_time_events_min_wait_interval` مانع می‌شود که تایمرهای خیلی نزدیک حلقه را به busy-loop تبدیل کنند.

![ساختار process_events در EventCenter. مهلت انتظار از نزدیک‌ترین رویداد زمان‌دار به دست می‌آید و کف 1 میلی‌ثانیه دارد. اگر رویداد خارجی منتظر باشد، صفر می‌شود. پس از epoll_wait، اول callbackهای fd، سپس تایمرها و در پایان رویدادهای خارجی اجرا می‌شوند. ردیف پایین مسیر بیدار کردن از thread دیگر را نشان می‌دهد: صف زیر قفل، شمارنده‌ی اتمی و یک write هشت‌بایتی روی eventfd](figures/ch26/f08_evloop.png){#fig-26-f08_evloop}

# انتخاب Worker برای هر اتصال {#sec-26-10}

::: {.algo #alg-26-4 title="توزیع اتصال‌ها بین Workerها" src="src/msg/async/Stack.cc :: NetworkStack::get_worker؛ Stack.h :: Worker::release_worker؛ AsyncConnection.cc :: AsyncConnection::_stop" complexity="O(W) با W = ms_async_op_threads (پیش‌فرض 3) زیر یک spinlock"}
:::

```text
pseudocode
get_worker():
    lock(pool_spin)
    best = argmin_w w.references       # تساوی ⇒ نخستین در بردار
    unlock ; best.references++ ; return best
release_worker(): references.fetch_sub(1)    # در AsyncConnection::_stop هنگام بستن اتصال
```

**مثال عددی.** با سه Worker و ده اتصال پیاپی، توزیع به‌صورت چرخشی 0، 1، 2، 0، 1، 2 است. اگر اتصال پنجم (روی Worker 1) بسته شود، شمارنده‌ها [2، 1، 2] می‌شوند و اتصال هفتم به Worker 1 می‌رود. در پایان، شمارنده‌ها [3، 3، 3] هستند. این تعادل فقط بر اساس **تعداد** اتصال است، نه ترافیک آن‌ها. یک OSD که 2 اتصال پرترافیک به دو OSD همسایه و 200 اتصال بی‌کار به کلاینت‌ها دارد، ممکن است هر دو اتصال پرترافیک را روی یک Worker داشته باشد. افزایش `ms_async_op_threads` (نیاز به راه‌اندازی دوباره دارد) احتمال این تصادف را کم می‌کند. شمارنده‌های `msgr_recv_bytes` و `msgr_send_bytes` هر Worker در `ceph daemon osd.N perf dump AsyncMessenger::Worker-N` نشان می‌دهند که تعادل واقعی برقرار است یا نه.

![ردیابی get_worker برای ده اتصال و یک بستن. ستون‌های سمت راست شمارنده‌ی references هر Worker را پس از هر رویداد نشان می‌دهند. انتخاب همیشه کمترین شمارنده است و در تساوی، نخستین Worker برنده می‌شود. بستن اتصال پنجم یک جای خالی در Worker 1 باز می‌کند که بلافاصله اتصال بعدی آن را پر می‌کند](figures/ch26/f10_worker.png){#fig-26-f10_worker}

# بازاتصال: کدام پیام‌ها دوباره فرستاده می‌شوند؟ {#sec-26-11}

::: {.algo #alg-26-5 title="بازفرستادن و دور ریختن پیام‌ها پس از بازاتصال" src="src/msg/async/ProtocolV2.cc :: ProtocolV2::requeue_sent، discard_requeued_up_to، handle_reconnect_ok" complexity="O(s) برای s پیام ارسال‌شده‌ی بی‌ack"}
:::

```text
pseudocode
on fault (اتصال lossless): requeue_sent():
    out_seq −= |sent|
    برای پیام‌های sent از آخر به اول: clear_payload ; push_front در out_queue[HIGHEST]
handle_reconnect_ok(msg_seq از طرف مقابل):
    out_seq = discard_requeued_up_to(out_seq, msg_seq)
discard_requeued_up_to(out_seq, seq):
    count = out_seq
    while صف HIGHEST خالی نیست و front.seq ≠ 0 و front.seq ≤ seq: pop_front ; count++
    return count
```

**مثال عددی.** کلاینت تا seq 120 فرستاده، ولی ack فقط تا 117 رسیده است. پس sent = {118، 119، 120}. با قطع TCP، requeue_sent مقدار out_seq را به 117 برمی‌گرداند و سه پیام را به سر صف می‌برد. OSD پیش از قطع 118 را گرفته بود (in_seq = 118)، پس در SESSION_RECONNECT_OK مقدار msg_seq = 118 برمی‌گرداند. discard_requeued_up_to(117، 118) پیام 118 را دور می‌ریزد و out_seq = 118 می‌شود. فقط 119 و 120 دوباره فرستاده می‌شوند و هیچ پیامی دو بار به dispatch نمی‌رسد. payload هر پیام پاک می‌شود (clear_payload)، چون ممکن است ویژگی‌های اتصال تازه فرق کند و encode دوباره لازم باشد.

![توالی بازاتصال یک اتصال lossless. کلاینت پس از قطع، پیام‌های بی‌ack را به سر صف برمی‌گرداند و پس از احراز هویت دوباره SESSION_RECONNECT می‌فرستد. OSD آخرین seq دریافتی را در RECONNECT_OK اعلام می‌کند و کلاینت هر چیزی تا آن شماره را دور می‌ریزد. اتصال‌های lossy (مثل کلاینت به OSD در Objecter) این مسیر را ندارند و به جای آن reset می‌شوند، و Objecter خودش opها را دوباره می‌فرستد](figures/ch26/f09_reconnect.png){#fig-26-f09_reconnect}

# تکمیلی و به‌روز {#sec-26-12}

- msgr2.1 (بیت REVISION_1) در نسخه‌های Nautilus به بعد وجود دارد. قالب epilogue و inline شدن segment اول در حالت secure را تغییر داد و در frameهای تک‌segment، epilogue را حذف کرد. msgr2.0 فقط برای سازگاری با نسخه‌های اولیه‌ی Nautilus نگه داشته شده است.
- فشرده‌سازی روی سیم (`COMPRESSION_REQUEST` و `COMPRESSION_DONE`، گزینه‌ی `ms_osd_compress_mode`) پس از auth مذاکره می‌شود. پیش‌فرض آن `none` است.
- هسته‌ی لینوکس از نسخه‌ی ۵٫۱۱ msgr2.1 را با گزینه‌ی `ms_mode` (`legacy`، `crc`، `secure`، `prefer-crc`، `prefer-secure`) پشتیبانی می‌کند (فصل ۲۹).
- crimson-osd به‌جای AsyncMessenger از messenger مبتنی بر Seastar استفاده می‌کند ولی همان قالب msgr2 روی سیم را دارد.

# تمرین عملی {#sec-26-13}

1. با `tcpdump` اولین ۲۶ بایت یک اتصال به پورت 3300 را بگیرید و banner و ویژگی‌ها را با جدول این فصل مقایسه کنید.
2. یک کدگذار پایتونی برای KEEPALIVE2 بنویسید و crc preamble را با محاسبه‌ی این فصل (0x99F5D5D8) تطبیق دهید.
3. روی یک خوشه‌ی آزمایشی `ms_client_mode=secure` و `ms_cluster_mode=secure` را تنظیم کنید و با `rados bench` و `top -H`، CPU مصرفی msgr-workerها را مقایسه کنید.
4. در حین `rados bench`، کارت شبکه‌ی یک OSD را برای ۵ ثانیه down کنید و در لاگ (`debug_ms=1`) پیام‌های SESSION_RECONNECT و RECONNECT_OK را پیدا کنید.

# پرسش‌های مرور {#sec-26-14}

1. ساختار banner در msgr2 چیست و ویژگی‌های فعلی کدام‌اند؟
2. چرا preamble دقیقاً ۳۲ بایت است؟
3. crc مربوط به preamble و crc مربوط به segment با چه seedهایی محاسبه می‌شوند؟
4. چرا segment داده هم‌ترازی ۴۰۹۶ دارد؟
5. inline کردن ۴۸ بایت در حالت secure چه سودی دارد؟
6. AUTH_SIGNATURE از چه حمله‌ای جلوگیری می‌کند؟
7. SESSION_RESET و SESSION_RETRY_GLOBAL چه زمانی ارسال می‌شوند؟
8. سه throttler در دریافت پیام کدام‌اند و چگونه backpressure ایجاد می‌کنند؟
9. چرا handlerها در EventCenter باید تا EAGAIN بخوانند؟
10. thread دیگری چگونه یک worker را برای ارسال پیام بیدار می‌کند؟

# منابع این فصل {#sec-26-15}

- مستند طراحی msgr2: https://docs.ceph.com/en/latest/dev/msgr2/
- frames_v2.h: https://github.com/ceph/ceph/blob/main/src/msg/async/frames_v2.h
- ProtocolV2.cc: https://github.com/ceph/ceph/blob/main/src/msg/async/ProtocolV2.cc
- crypto_onwire.cc: https://github.com/ceph/ceph/blob/main/src/msg/async/crypto_onwire.cc
- پیکربندی messenger: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- گزینه‌ی ms_mode در هسته: https://docs.kernel.org/filesystems/ceph.html
- NIST SP 800-38D (GCM): https://csrc.nist.gov/pubs/sp/800/38/d/final
- epoll(7): https://man7.org/linux/man-pages/man7/epoll.7.html
