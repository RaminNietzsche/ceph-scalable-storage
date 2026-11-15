---
chapter: 26
id: ch26
title: 'Lower Layers (4): msgr2 at the Byte Level, AsyncConnection and EventCenter'
part: lower
lang: en
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

# Exact on-wire frame size {#sec-26-7}

`FrameAssembler` in `frames_v2.h` has a separate function for each part of the frame: `get_preamble_onwire_len`, `get_segment_onwire_len` and `get_epilogue_onwire_len`. With these three functions the exact overhead of each message can be computed before it is sent.

::: {.algo #alg-26-1 title="On-wire length of an msgr2.1 frame" src="src/msg/async/frames_v2.h :: FrameAssembler::get_preamble_onwire_len, get_segment_onwire_len, get_epilogue_onwire_len, get_frame_onwire_len" complexity="O(number of segments) = O(1) (at most 4)"}
:::

```text
pseudocode
preamble = secure ? 32 + 48 (inline) + 16 (tag) : 32
seg(i):
    if secure:
        p = round_up(len_i, 16)
        if i == 0: return p > 48 ? p + 16 − 48 : 0       # up to 48 bytes fit inside the preamble
        return p
    return (i == 0 and len_0 > 0) ? len_0 + 4 : len_i        # separate crc for segment 0
epilogue = (only one segment) ? 0 : secure ? 16 + 16 : 1 + 3×4
total = preamble + Σ seg(i) + epilogue
```

**Numerical example.** Take a MESSAGE with segment 0 = ceph_msg_header2 (packed, 41 bytes), front = 200 bytes, middle = 0 and data = 4096 bytes. The logical data is 4337 bytes.

- **crc mode:** 32 + (41 + 4) + 200 + 0 + 4096 + 13 = 4386 bytes, that is 49 bytes of overhead (1.1%).
- **secure mode:** 96 + 0 (the 41-byte header is rounded up to 48 and fits entirely inside the preamble) + 208 + 0 + 4096 + 32 = 4432 bytes, that is 95 bytes of overhead (2.2%).

For KEEPALIVE2 in crc mode the figure is the same 44 bytes as in the table above, because it has only one segment and no epilogue. In secure mode the eight-byte segment is rounded up to 16 and fits inside the preamble, so the whole frame is 96 bytes.

![Comparison of the on-wire bytes for a message with 4 KiB of data in crc and secure modes. In crc mode, segment 0 has its own four-byte crc and the thirteen-byte epilogue holds the crcs of the other three segments. In secure mode the preamble has room for 48 inline bytes and the sixteen-byte GCM tag, so the message header is encrypted without a separate frame. front is rounded up to a multiple of 16 and the epilogue is one 16-byte block plus the tag. The data bar is cut at 1000 bytes for readability](figures/ch26/f07_onwire.png){#fig-26-f07_onwire}

# Nonces in AES-GCM and preventing reuse {#sec-26-8}

![Layout of the first 40 bytes of the connection_secret that cephx gives both sides at the end of authentication: 16 bytes of shared AES-128 key, then a twelve-byte receive nonce and a twelve-byte send nonce. Each nonce has a fixed four-byte part and an eight-byte counter. The server side swaps the rx and tx roles with the crossed flag so that each direction has its own nonce](figures/ch26/f06_secret.png){#fig-26-f06_secret}

::: {.algo #alg-26-2 title="Nonce management in AES-128-GCM" src="src/msg/async/crypto_onwire.cc :: rxtx_t::create_handler_pair, AES128GCM_OnWireTxHandler::reset_tx_handler, AES128GCM_OnWireRxHandler::reset_rx_handler" complexity="O(1) per frame; encryption O(L) with AES-NI"}
:::

```text
pseudocode
create_handler_pair(secret, crossed):
    key = secret[0:16] ; rx = secret[16:28] ; tx = secret[28:40]
    Tx = AESGCM(key, crossed ? rx : tx) ; Rx = AESGCM(key, crossed ? tx : rx)
reset_tx_handler(segments):
    if nonce == initial_nonce:
        if used_initial_nonce: throw "nonce reuse"     # the counter has wrapped around
        used_initial_nonce = true
    EVP_EncryptInit_ex(..., iv = nonce)
    if msgr2.1: nonce.counter += 1  else: nonce.fixed += 1   # msgr2.0: wraps after 2^32
```

**Numerical example.** An OSD sending 10000 frames per second on one connection would, in msgr2.0, return to the initial nonce after $2^{32} / 10^4 \approx 429497$ seconds (about 5 days), and the connection had to be reset. In msgr2.1 the 64-bit counter lasts $2^{64} / 10^4 \approx 5.8 \times 10^7$ years. GCM also allows at most about 64 GiB of data per nonce ($2^{32}$ blocks of 16 bytes), and msgr frames, with their segment limit, are far smaller than that.

# The EventCenter loop and waking up across threads {#sec-26-9}

::: {.algo #alg-26-3 title="The Worker event loop" src="src/msg/async/Event.cc :: EventCenter::process_events, dispatch_event_external, wakeup; src/msg/async/Stack.cc :: NetworkStack::add_thread" complexity="O(k) for k ready fds + O(t) due time events + O(e) external events per round"}
:::

```text
pseudocode
loop (each Worker, msgr-worker-N): process_events(30 s)
process_events(timeout):
    if first time event < now + timeout: timeout = max(that gap, 1000 µs) ; trigger_time = true
    if pollers or external_num_events > 0: timeout = 0
    n = epoll_wait(timeout)
    for each ready fd: read_cb and/or write_cb
    if trigger_time: process_time_events()
    if external_num_events: lock ; swap(external_events) ; unlock ; do_request on all of them
dispatch_event_external(e) (from another thread):
    lock ; external_events.push(e) ; external_num_events++ ; unlock
    if the current thread is not that Worker: wakeup() ⇒ write(eventfd, 1)
```

**Numerical example and latency.** A thread of an OSD op shard prepares the reply to an op and calls `send_message`. The connection belongs to msgr-worker-1, so the send is queued as an external event and the eventfd is woken. The cost of this path is one write on the eventfd, one epoll_wait wake-up (usually a few microseconds to a few tens of microseconds, depending on load and the C-state settings) and then a writev on the socket. If the Worker is busy processing other fds at that moment, the event waits until the end of that round. This is why a Worker that has hundreds of busy connections at once raises tail latency. The 1000-microsecond floor of `ms_time_events_min_wait_interval` keeps very close timers from turning the loop into a busy loop.

![The structure of process_events in EventCenter. The wait timeout comes from the nearest time event and has a floor of 1 millisecond. If an external event is waiting, it becomes zero. After epoll_wait, the fd callbacks run first, then the timers and finally the external events. The bottom row shows the wake-up path from another thread: a queue under a lock, an atomic counter and an eight-byte write on the eventfd](figures/ch26/f08_evloop.png){#fig-26-f08_evloop}

# Choosing a Worker for each connection {#sec-26-10}

::: {.algo #alg-26-4 title="Distributing connections across Workers" src="src/msg/async/Stack.cc :: NetworkStack::get_worker; Stack.h :: Worker::release_worker; AsyncConnection.cc :: AsyncConnection::_stop" complexity="O(W) with W = ms_async_op_threads (default 3) under a spinlock"}
:::

```text
pseudocode
get_worker():
    lock(pool_spin)
    best = argmin_w w.references       # tie ⇒ the first in the vector
    unlock ; best.references++ ; return best
release_worker(): references.fetch_sub(1)    # in AsyncConnection::_stop when the connection closes
```

**Numerical example.** With three Workers and ten connections in a row, the distribution is round-robin: 0, 1, 2, 0, 1, 2. If the fifth connection (on Worker 1) is closed, the counters become [2, 1, 2] and the seventh connection goes to Worker 1. At the end the counters are [3, 3, 3]. This balance is based only on the **number** of connections, not on their traffic. An OSD with 2 busy connections to two neighbouring OSDs and 200 idle connections to clients may end up with both busy connections on one Worker. Raising `ms_async_op_threads` (which needs a restart) makes this coincidence less likely. Each Worker's `msgr_recv_bytes` and `msgr_send_bytes` counters in `ceph daemon osd.N perf dump AsyncMessenger::Worker-N` show whether the real balance holds.

![A trace of get_worker for ten connections and one close. The columns on the right show each Worker's references counter after every event. The choice is always the lowest counter, and on a tie the first Worker wins. Closing the fifth connection opens a slot on Worker 1 that the next connection fills immediately](figures/ch26/f10_worker.png){#fig-26-f10_worker}

# Reconnection: which messages are sent again? {#sec-26-11}

::: {.algo #alg-26-5 title="Resending and discarding messages after a reconnect" src="src/msg/async/ProtocolV2.cc :: ProtocolV2::requeue_sent, discard_requeued_up_to, handle_reconnect_ok" complexity="O(s) for s sent messages without an ack"}
:::

```text
pseudocode
on fault (lossless connection): requeue_sent():
    out_seq −= |sent|
    for the sent messages from last to first: clear_payload ; push_front into out_queue[HIGHEST]
handle_reconnect_ok(msg_seq from the peer):
    out_seq = discard_requeued_up_to(out_seq, msg_seq)
discard_requeued_up_to(out_seq, seq):
    count = out_seq
    while the HIGHEST queue is not empty and front.seq ≠ 0 and front.seq ≤ seq: pop_front ; count++
    return count
```

**Numerical example.** A client has sent up to seq 120, but acks have arrived only up to 117. So sent = {118, 119, 120}. When TCP drops, requeue_sent sets out_seq back to 117 and moves the three messages to the head of the queue. The OSD had received 118 before the drop (in_seq = 118), so it returns msg_seq = 118 in SESSION_RECONNECT_OK. discard_requeued_up_to(117, 118) discards message 118 and out_seq becomes 118. Only 119 and 120 are sent again, and no message reaches dispatch twice. The payload of each message is cleared (clear_payload), because the features of the new connection may differ and a fresh encode may be needed.

![The reconnect sequence of a lossless connection. After the drop the client moves the unacknowledged messages back to the head of the queue and, after authenticating again, sends SESSION_RECONNECT. The OSD announces the last seq it received in RECONNECT_OK, and the client discards everything up to that number. Lossy connections (such as client to OSD in the Objecter) do not take this path; they are reset instead, and the Objecter resends the ops itself](figures/ch26/f09_reconnect.png){#fig-26-f09_reconnect}

# Supplementary and up to date {#sec-26-12}

- msgr2.1 (the REVISION_1 bit) exists in Nautilus and later releases. It changed the epilogue format and the inlining of the first segment in secure mode, and it removed the epilogue from single-segment frames. msgr2.0 is kept only for compatibility with early Nautilus releases.
- On-wire compression (`COMPRESSION_REQUEST` and `COMPRESSION_DONE`, the `ms_osd_compress_mode` option) is negotiated after auth. Its default is `none`.
- The Linux kernel has supported msgr2.1 since 5.11, with the `ms_mode` option (`legacy`, `crc`, `secure`, `prefer-crc`, `prefer-secure`) (chapter 29).
- crimson-osd uses a Seastar-based messenger instead of AsyncMessenger, but it has the same msgr2 format on the wire.

# Hands-on exercise {#sec-26-13}

1. Capture the first 26 bytes of a connection to port 3300 with `tcpdump` and compare the banner and features with this chapter's table.
2. Write a Python encoder for KEEPALIVE2 and check the preamble crc against this chapter's calculation (0x99F5D5D8).
3. On a test cluster set `ms_client_mode=secure` and `ms_cluster_mode=secure`, and compare the CPU used by the msgr-workers with `rados bench` and `top -H`.
4. During a `rados bench`, take one OSD's network card down for 5 seconds and find the SESSION_RECONNECT and RECONNECT_OK messages in the log (`debug_ms=1`).

# Review questions {#sec-26-14}

1. What is the structure of the msgr2 banner, and which features exist today?
2. Why is the preamble exactly 32 bytes?
3. With what seeds are the preamble crc and the segment crc computed?
4. Why does the data segment have an alignment of 4096?
5. What is the benefit of inlining 48 bytes in secure mode?
6. What attack does AUTH_SIGNATURE prevent?
7. When are SESSION_RESET and SESSION_RETRY_GLOBAL sent?
8. What are the three throttlers on message receive, and how do they create backpressure?
9. Why must handlers in EventCenter read until EAGAIN?
10. How does another thread wake a worker to send a message?

# Sources for this chapter {#sec-26-15}

- msgr2 design document: https://docs.ceph.com/en/latest/dev/msgr2/
- frames_v2.h: https://github.com/ceph/ceph/blob/main/src/msg/async/frames_v2.h
- ProtocolV2.cc: https://github.com/ceph/ceph/blob/main/src/msg/async/ProtocolV2.cc
- crypto_onwire.cc: https://github.com/ceph/ceph/blob/main/src/msg/async/crypto_onwire.cc
- Messenger configuration: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- The ms_mode option in the kernel: https://docs.kernel.org/filesystems/ceph.html
- NIST SP 800-38D (GCM): https://csrc.nist.gov/pubs/sp/800/38/d/final
- epoll(7): https://man7.org/linux/man-pages/man7/epoll.7.html
