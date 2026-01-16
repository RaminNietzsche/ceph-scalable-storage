---
chapter: 26
id: ch26
title: 'Lower Layers (4): msgr2 at the Byte Level, AsyncConnection and EventCenter'
part: lower
lang: en
translation: pending
---

# Introduction: the wire between two daemons {#sec-26-1}

Every message exchanged in Ceph, whether a client's write request to an OSD, a heartbeat between OSDs or a map that the mon publishes, passes through the messenger layer. Since Nautilus the default protocol is msgr2 (port 3300 for the mon). This chapter opens it up at the byte level: the opening banner, the frame format with its preamble and segments, the two modes crc and secure (AES-GCM), the authentication handshake, the session and reconnection, and finally the `ProtocolV2` state machine and the `EventCenter` event loop that runs all of this with a small number of threads. The source of the structures is `src/msg/async/frames_v2.h`, `ProtocolV2.cc`, `crypto_onwire.cc` and `src/include/msgr.h` on the main branch.

::: {.summary}

- The banner is `ceph v2\n`, followed by a length of 16 and two 64-bit feature sets (supported and required). The current features are REVISION_1 (msgr2.1) and COMPRESSION.
- Every frame starts with a 32-byte preamble: the tag, the number of segments (at most 4), the length and alignment of each segment, flags and a crc32c.
- crc mode has one crc32c per segment. secure mode both encrypts and authenticates with AES-128-GCM (16-byte key, 12-byte IV and 16-byte tag).
- Defaults: `ms_cluster_mode` and `ms_client_mode` are `crc secure`, and `ms_mon_*_mode` are `secure crc`.
- AsyncMessenger works with `ms_async_op_threads=3` workers. Each worker has an EventCenter based on epoll (edge-triggered).

:::

# The banner and feature negotiation {#sec-26-2}

The first bytes sent after the TCP connection is established are not encrypted. `ProtocolV2::_banner_exchange` builds this structure: the eight-byte string `CEPH_BANNER_V2_PREFIX = "ceph v2\n"`, a u16 for the payload length, and then the payload of two u64s, namely `CEPH_MSGR2_SUPPORTED_FEATURES` and `CEPH_MSGR2_REQUIRED_FEATURES`.

| Bytes (example) | Meaning |
|---|---|
| `63 65 70 68 20 76 32 0a` | "ceph v2\n" |
| `10 00` | payload length = 16 (u16 LE) |
| `03 00 00 00 00 00 00 00` | supported = REVISION_1 (bit 0) + COMPRESSION (bit 1) = 3 |
| `00 00 00 00 00 00 00 00` | required = 0 |

::: {.note}
An old client with a version 1 banner (`ceph v027`) cannot connect to an msgr2 port, because the banner bytes differ. This is why mons publish two addresses, `v2:...:3300` and `v1:...:6789`, in the `addrvec`. If `ms_bind_msgr1=false`, old clients (and old krbd versions from before msgr2 support in kernel 5.11) cannot connect.
:::

![The full msgr2 handshake. After the banner, each side sends HELLO (the entity type and the address at which it sees the other side). Then cephx authentication runs with AUTH_REQUEST, MORE round trips and AUTH_DONE (which sets the global_id and the connection mode, crc or secure). From this point on, frames are in the chosen mode. AUTH_SIGNATURE (HMAC-SHA256 over the bytes from before authentication) prevents tampering with the unencrypted phase. CLIENT_IDENT and SERVER_IDENT establish the session with a cookie and global_seq](figures/ch26/f01_hs.png){#fig-26-f01_hs}

::: {.deep}
**Why AUTH_SIGNATURE?** The banner, HELLO and part of the auth negotiation are sent before a session key exists. A man in the middle could, for example, change the `preferred_modes` list so that the two sides agree on crc instead of secure (a downgrade attack). After AUTH_DONE, each side sends the `hmac_sha256`, with the session key, of all the bytes it has **received** (`pre_auth.rxbuf`), and the other side compares it with the bytes it has itself **sent**. Any change along the way drops the connection.
:::

# The frame at the byte level {#sec-26-3}

![The frame structure in msgr2.1. preamble_block_t is exactly 32 bytes and is designed to be a multiple of the AES block (16). In crc mode the first segment comes right after the preamble together with its own crc, and if there are other segments, the epilogue holds late_status and the crc of the remaining segments. In secure mode the preamble is encrypted together with the first 48 bytes of segment zero in one go and gets a GCM tag. Messages have four segments: header2, front, middle and data (page-aligned for zero copy)](figures/ch26/f02_frame.png){#fig-26-f02_frame}

| offset | size | field | description |
|---|---|---|---|
| 0 | 1 | `tag` | frame type (next table) |
| 1 | 1 | `num_segments` | 1 to 4 |
| 2 | 24 | `segments[4]` | each one `length` (le32) and `alignment` (le16) |
| 26 | 1 | `flags` | for example `FRAME_EARLY_DATA_COMPRESSED=0x1` |
| 27 | 1 | `_reserved` | zero |
| 28 | 4 | `crc` | `ceph_crc32c(0, preamble, 28)` |

| Tag | Value | Tag | Value |
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

## A complete example: one KEEPALIVE2 in crc mode {#sec-26-3-1}

KEEPALIVE2 has one segment that is just a `utime_t` (sec and nsec, each a u32). For the time 1700000000.5 seconds, the complete frame is 44 bytes. We computed these values with an independent encoder:

| Bytes | Part |
|---|---|
| `12 01` | tag=18 (KEEPALIVE2), num_segments=1 |
| `08 00 00 00 08 00` | segment 0: length=8, alignment=8 (`DEFAULT_ALIGNMENT = sizeof(void*)`) |
| `00 × 18` | three empty segments |
| `00 00` | flags, reserved |
| `d8 d5 f5 99` | preamble crc = 0x99F5D5D8 (seed 0) |
| `00 f1 53 65 00 65 cd 1d` | sec=1700000000, nsec=500000000 |
| `39 7f 34 4d` | segment crc = 0x4D347F39 (seed 0xFFFFFFFF) |

![The same KEEPALIVE2 frame as above, this time as a byte grid: the thirty-two-byte preamble with the tag, the segment count and the table of four segments (the last three zero), then the preamble's own crc, then the eight-byte utime_t segment and finally that segment's crc. The total is 44 bytes, and since there is only one segment there is no epilogue. This is the smallest frequent frame on an idle connection; for example, MonClient sends one to the mon every mon_client_ping_interval seconds (send_keepalive)](figures/ch26/f05_kaframe.png){#fig-26-f05_kaframe}

Because there is only one segment, no epilogue is sent (in msgr2.1). The server replies with KEEPALIVE2_ACK and the same timestamp. The client uses this reply to measure the connection's "last alive time" (`mon_client_ping_interval` and heartbeats).

## A message: four segments {#sec-26-3-2}

`MESSAGE` always has four segments (`SegmentIndex::Msg`): **HEADER (0)**, which is `ceph_msg_header2` (seq, tid, type, priority, version, data_pre_padding_len, data_off, ack_seq, flags, compat_version); **FRONT (1)**, which is the main encoded body of the message (for example the fields of MOSDOp); **MIDDLE (2)**, which is rarely used; and **DATA (3)**, which is the raw data of a write or read. The data segment's alignment is `PAGE_SIZE_ALIGNMENT = 4096`, so that the receiver can allocate a page-aligned buffer and take the data without copying all the way to O_DIRECT in BlueStore (chapter 23). `sizeof(ceph_msg_header2)` is less than 48, so in secure mode the whole header fits in the inline part and the receiver can learn the length of the rest with one decryption.

# secure mode: AES-128-GCM on the wire {#sec-26-4}

When `con_mode` is `CEPH_CON_MODE_SECURE` (0x2), `crypto_onwire.cc` works with OpenSSL (`EVP_aes_128_gcm`): `AESGCM_KEY_LEN=16`, `AESGCM_IV_LEN=12` and `AESGCM_TAG_LEN=16`. The nonce is a twelve-byte structure: a fixed 32-bit part and a 64-bit counter that is incremented for each frame. The key and the initial nonce are derived, separately for each direction, from the cephx session key and the `connection_secret` exchanged in AUTH_DONE.

```text
pseudocode: sending one frame in secure mode (msgr2.1, this book's summary)
  plain_head = preamble(32) || segment0[0:48] (padded with zeros if shorter)
  out  = AES_GCM_encrypt(key_tx, nonce_tx, plain_head) || tag(16); nonce_tx.counter++
  if len(segment0) > 48 or num_segments > 1:
      rest = segment0[48:] || segment1 || segment2 || segment3   # each padded to 16
      out += AES_GCM_encrypt(key_tx, nonce_tx, rest || epilogue) || tag(16); nonce_tx.counter++
  send(out)
```

**Overhead:** for a small control message, secure mode uses about 96 bytes (32 + 48 + 16) versus 44 bytes in crc mode. For a 4M write the overhead is negligible, but the CPU cost of AES-GCM (with AES-NI, around a few gigabytes per second per core) is measurable on busy NVMe OSDs. This is why the default for data traffic is `crc secure` (crc preferred) and for the mon `secure crc`.

| Option | Default | Use |
|---|---|---|
| `ms_cluster_mode` | crc secure | OSD↔OSD |
| `ms_service_mode` | crc secure | modes the server (OSD, MDS) accepts |
| `ms_client_mode` | crc secure | client preference |
| `ms_mon_cluster_mode` / `ms_mon_service_mode` / `ms_mon_client_mode` | secure crc | connections to the mon |
| `ms_osd_compress_mode` | none | on-wire compression for the OSD |
| `ms_crc_data` / `ms_crc_header` | true / true | turning off the crc in crc mode (not recommended) |

::: {.warn}
crc mode has **no protection against an attacker**. A crc only detects random errors. If the public network is shared or untrusted, consider `ms_client_mode=secure` and `ms_service_mode=secure`, and measure the effect on CPU. In crc mode cephx only proves identity, not the confidentiality or integrity of messages.
:::

# Session, reconnection and reset {#sec-26-5}

Lossless connections (for example OSD↔OSD, or client↔mon under some policies) must continue after a TCP drop **without losing or repeating messages**. For this msgr2 keeps the following state:

| Variable | Meaning |
|---|---|
| `client_cookie` / `server_cookie` | random session identifier set in CLIENT_IDENT and SERVER_IDENT |
| `global_seq` | the messenger's global counter for ordering connection attempts (resolving a race between two simultaneous connections) |
| `connect_seq` | the number of successful reconnections of this session |
| `message seq` / `ack_seq` | the number of the last message received; unacknowledged messages stay in the resend queue |

```text
Reconnection scenario (this book's summary)
  client: SESSION_RECONNECT(addrs, client_cookie, server_cookie, global_seq, connect_seq, msg_seq)
  server:
    unknown cookie (the server restarted)     → SESSION_RESET(full=true)  → new session, queues empty
    global_seq older than what I have seen    → SESSION_RETRY_GLOBAL(gs)  → again with a larger gs
    inconsistent connect_seq                  → SESSION_RETRY(cs)
    race with a connection I am establishing  → WAIT
    everything correct                        → SESSION_RECONNECT_OK(msg_seq)
                                               resend the messages above msg_seq
```

::: {.deep}
**Connection race:** two OSDs may connect to each other at the same time. Each side has one outgoing and one incoming connection. ProtocolV2 decides which connection stays by comparing addresses (and `global_seq`). The "losing" side receives WAIT and drops its own connection, and the winning connection (`replacing`) takes its place. Queued messages are moved to the winning connection. Old bugs in this very logic were the cause of many reports of "duplicate messages" or "stuck connections".
:::

![The ProtocolV2 state machine. The connect side goes from START_CONNECT through banner, HELLO, auth and compression to SESSION_CONNECTING (a new session) or SESSION_RECONNECTING (a previous cookie) and finally READY. The accept side follows a similar path. In READY, receiving each message passes three throttlers (message count, policy bytes and the dispatch queue). An error on a lossless connection leads to STANDBY or reconnection with backoff (0.2 to 15 seconds), and on a lossy connection to CLOSED](figures/ch26/f03_state.png){#fig-26-f03_state}

| Throttle | Option or policy | Effect when full |
|---|---|---|
| THROTTLE_MESSAGE | `policy.throttler_messages` (for example `osd_client_message_cap=256`) | reading from the socket stops, so TCP backpressure reaches the client |
| THROTTLE_BYTES | `policy.throttler_bytes` (for example `osd_client_message_size_cap=500M`) | the same |
| THROTTLE_DISPATCH_QUEUE | `ms_dispatch_throttle_bytes=100M` | the same; protects the dispatch queue's memory |

# AsyncMessenger, Worker and EventCenter {#sec-26-6}

![The threading model in AsyncMessenger. NetworkStack (Posix by default) creates ms_async_op_threads=3 Workers, and each Worker has an EventCenter. Each connection is assigned to one of the workers when it is created and stays there for its whole life. Each worker's loop first runs the expired timers, then waits in epoll_wait (edge-triggered) for fd events, and finally runs the external events that other threads have queued. Other threads wake the worker by writing to an eventfd (or a pipe on systems without it)](figures/ch26/f04_event.png){#fig-26-f04_event}

`EventCenter::process_events` does the following in each round:

1. It computes when the nearest time event is due, to set the wait duration (at least `ms_time_events_min_wait_interval`).
2. If no poller is active and no external event is queued, it blocks in `event_wait` (that is `epoll_wait` in `EventEpoll.cc`) until that time.
3. For each ready fd, it calls the registered `read_cb` or `write_cb`. For connections these are `AsyncConnection::process` and `handle_write`.
4. It runs the expired timers (for example keepalive, connection timeout and reconnection backoff).
5. It empties and runs the `external_events` queue. `AsyncConnection::send_message`, from another thread (for example a PG thread in the OSD), puts the message in `out_q` and schedules the write on the right worker with `dispatch_event_external`.

::: {.note}
Because epoll is registered in `EPOLLET` (edge-triggered) mode, the handler must read or write until `EAGAIN`. Otherwise the remaining data does not generate any new event. This is why ProtocolV2 keeps its reading state in continuations (`CONTINUATION(...)`) and waits for more data by returning `nullptr`.
:::

**Why only three threads?** Protocol processing (encryption or crc, frame parsing and throttling) is light, and the main work happens in the OSD's thread pools (`osd_op_num_threads_per_shard`). Three workers are usually enough for tens of thousands of connections, but with secure mode on busy NVMe OSDs these workers may become a CPU bottleneck. In that case `top -H -p <pid>` shows threads named `msgr-worker-N` near 100%.

```bash
top -H -p $(pidof -s ceph-osd)            # msgr-worker-0..2
ceph daemon osd.4 perf dump AsyncMessenger::Worker-0 | jq '.[] | {msgr_recv_messages, msgr_send_messages, msgr_running_total_time}'
ceph daemon osd.4 messenger dump        # without arguments, the list of messengers; with one's name, its connections
ss -tinp | grep ceph-osd | head            # cwnd, rtt and retrans for each connection
tcpdump -i any -s 128 -w /tmp/msgr.pcap port 3300   # the banner and preamble are visible in crc mode
```

::: {.debug}
Wireshark has a Ceph dissector, but its msgr2 support is limited. In crc mode you can read the preamble by hand with this chapter's tag table: byte 0 is the tag and bytes 2 to 5 are the length of the first segment (LE). In secure mode everything after the banner and HELLO is encrypted.
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

**مثال عددی.** یک OSD با 10000 قاب در ثانیه روی یک اتصال، در msgr2.0 پس از 2^32 / 10^4 ≈ 429497 ثانیه (حدود 5 روز) به nonce اولیه برمی‌گشت و اتصال باید reset می‌شد. در msgr2.1 شمارنده‌ی 64 بیتی 2^64 / 10^4 ≈ 5.8 × 10^7 سال دوام می‌آورد. GCM هم برای هر nonce حداکثر حدود 64 GiB داده را مجاز می‌داند (2^32 بلوک 16 بایتی)، و قاب‌های msgr با سقف segment از این بسیار کوچک‌ترند.

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
