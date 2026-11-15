---
chapter: 20
id: ch20
title: "پایش Ceph: Prometheus، ceph-exporter، هشدارها و مشاهده‌پذیری"
part: main
lang: fa
---

# پیش از شروع {#sec-20-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-20-1-1}

`ceph -s` برای یک نگاه سریع کافی است، اما برای پاسخ به پرسش‌هایی مانند «تأخیر نوشتن از سه‌شنبه چرا بالا رفته؟» یا «کدام OSD در یک ساعت گذشته کندترین بوده؟» به سری‌های زمانی، قواعد هشدار و داشبورد نیاز داریم. Ceph امروز پشته‌ی پایش استانداردی دارد که cephadm آن را مستقر می‌کند: ماژول prometheus در mgr، daemon **ceph-exporter** روی هر میزبان، node-exporter، Prometheus، Alertmanager و Grafana، و در Tentacle دروازه‌ی **mgmt-gateway**.

- هر مؤلفه‌ی پشته چه داده‌ای تولید می‌کند و چرا شمارنده‌های عملکرد از mgr به ceph-exporter منتقل شدند؟
- کدام متریک‌ها مهم‌ترین سیگنال‌ها هستند؟
- قاعده‌ی هشدار خوب برای Ceph چه ویژگی‌هایی دارد؟
- شمارنده‌های داخلی daemonها (perf counters) چگونه ساخته و خوانده می‌شوند؟
- mgmt-gateway و oauth2-proxy چه مشکلی را حل می‌کنند؟

# معماری پشته‌ی پایش {#sec-20-2}

![معماری پشته‌ی پایش در سه ردیف: روی هر میزبان ceph-exporter شمارنده‌های عملکرد daemonها را از admin socket می‌خواند و node-exporter متریک‌های سیستم‌عامل را منتشر می‌کند؛ mgr فعال با ماژول prometheus متریک‌های سطح کلاستر و نقطه‌ی service discovery را ارائه می‌دهد؛ Prometheus همه را scrape و قواعد هشدار را ارزیابی می‌کند، Alertmanager هشدارها را مسیریابی و Grafana داشبوردها را نمایش می‌دهد](figures/ch20/f01_stack.png){#fig-20-f01_stack}

```bash
ceph mgr module enable prometheus
ceph orch apply node-exporter
ceph orch apply ceph-exporter
ceph orch apply alertmanager
ceph orch apply prometheus
ceph orch apply grafana
ceph orch ls --service-type prometheus
ceph dashboard get-prometheus-api-host
```

| مؤلفه | داده | نکته |
|---|---|---|
| ماژول prometheus در mgr | سلامت، کدهای health، وضعیت OSD و PG، مصرف pool، فراداده‌ی daemonها، متریک‌های تصویر RBD (اختیاری) | پورت پیش‌فرض 9283؛ فقط mgr فعال داده می‌دهد |
| ceph-exporter | شمارنده‌های عملکرد هر daemon محلی (از admin socket) | روی هر میزبان؛ بار mgr را کم می‌کند |
| node-exporter | CPU، حافظه، دیسک، شبکه‌ی میزبان | برای همبستگی کندی Ceph با سخت‌افزار |
| Prometheus | ذخیره‌ی سری زمانی و ارزیابی قواعد | قواعد ceph-mixin همراه cephadm |
| Alertmanager | گروه‌بندی، سکوت و ارسال هشدار | Dashboard هشدارها را نمایش می‌دهد |
| Grafana | داشبوردهای آماده | درون Dashboard جاسازی می‌شود |

::: {.note}
**تغییر نسبت به نسخه‌های قدیمی.** طبق مستندات ماژول prometheus، شمارنده‌های عملکرد daemonها دیگر به‌صورت پیش‌فرض از این ماژول منتشر نمی‌شوند و این کار به ceph-exporter سپرده شده است؛ گزینه‌ی `mgr/prometheus/exclude_perf_counters` فقط وقتی باید غیرفعال شود که هیچ ceph-exporterی مستقر نیست. دلیل: جمع‌آوری همه‌ی شمارنده‌ها از یک نقطه در کلاسترهای بزرگ کارایی mgr را پایین می‌آورد.
:::

::: {.warn}
فقط mgr **فعال** متریک‌های کلاستر را منتشر می‌کند. اگر Prometheus بیرونی دارید، همه‌ی mgrها را به‌عنوان هدف تعریف کنید (یا از service discovery در `http(s)://<mgr>:8765/sd/prometheus/sd-config?service=...` استفاده کنید) تا پس از failover، scrape قطع نشود. رفتار mgrهای standby با `standby_behaviour` و کد پاسخ آن‌ها با `standby_error_status_code` تنظیم می‌شود.
:::

## Prometheus بیرونی {#sec-20-2-1}

```yaml
# prometheus.yml — نمونه‌ی این کتاب برای Prometheus بیرونی
scrape_configs:
  - job_name: ceph
    honor_labels: true
    http_sd_configs:
      - url: http://mgr1.example.internal:8765/sd/prometheus/sd-config?service=mgr-prometheus
  - job_name: ceph-exporter
    honor_labels: true
    http_sd_configs:
      - url: http://mgr1.example.internal:8765/sd/prometheus/sd-config?service=ceph-exporter
  - job_name: node
    http_sd_configs:
      - url: http://mgr1.example.internal:8765/sd/prometheus/sd-config?service=node-exporter
```

::: {.tip}
`honor_labels: true` لازم است تا برچسب‌هایی مانند `ceph_daemon` و `instance` که Ceph تنظیم می‌کند، با برچسب‌های Prometheus بازنویسی نشوند. نام دقیق سرویس‌ها در service discovery را با مستندات نسخه‌ی خود تطبیق دهید. طبق مستندات cephadm، اگر `mgr/cephadm/secure_monitoring_stack` فعال باشد یا mgmt-gateway مستقر شده باشد، این endpoint روی https و با basic auth سرویس می‌دهد و تعریف job باید `basic_auth` و `tls_config` داشته باشد.
:::

# از درون کد: perf counters {#sec-20-3}

## ساخت شمارنده‌ها {#sec-20-3-1}

هر daemon Ceph شمارنده‌های خود را با `PerfCountersBuilder` (`src/common/perf_counters.h`) تعریف می‌کند. هر شمارنده یک کلید عددی، یک نام، یک نوع و یک **اولویت** دارد. انواع اصلی:

| تابع سازنده | نوع | مثال |
|---|---|---|
| add_u64 | مقدار لحظه‌ای (gauge) | تعداد عملیات در جریان |
| add_u64_counter | شمارنده‌ی افزایشی | تعداد کل عملیات نوشتن |
| add_time_avg | مجموع زمان و تعداد (برای میانگین) | op_w_latency |
| add_u64_counter_histogram | هیستوگرام دوبعدی (مثلاً اندازه × تأخیر) | توزیع تأخیر بر حسب اندازه |

اولویت‌ها از `PRIO_CRITICAL=10` تا `PRIO_DEBUGONLY=0` هستند (`PRIO_INTERESTING=8`، `PRIO_USEFUL=5`). این اولویت نقش عملی دارد: ceph-exporter فقط شمارنده‌هایی با اولویت دست‌کم `exporter_prio_limit` را منتشر می‌کند که در `src/common/options/ceph-exporter.yaml.in` پیش‌فرضش **۵** است. بنابراین شمارنده‌های DEBUGONLY به Prometheus نمی‌رسند مگر این حد را کاهش دهید (که حجم متریک‌ها را بسیار زیاد می‌کند).

![مسیر یک شمارنده‌ی عملکرد از تولید تا مصرف: OSD شمارنده‌ای مثل op_w_latency را با PerfCountersBuilder ثبت می‌کند، admin socket آن را با فرمان‌های counter dump و counter schema عرضه می‌کند، ceph-exporter آن را با برچسب ceph_daemon به فرمت Prometheus تبدیل می‌کند و Prometheus آن را ذخیره و با PromQL در قواعد هشدار و پنل‌ها به کار می‌برد](figures/ch20/f02_metric.png){#fig-20-f02_metric}

```bash
# خواندن مستقیم شمارنده‌ها روی میزبان
ceph daemon osd.3 counter schema | jq 'keys' | head
ceph daemon osd.3 counter dump | jq '.osd[0].counters | {op_w, op_r}'
ceph daemon osd.3 perf dump osd | jq '.osd.op_w_latency'       # شکل قدیمی‌تر: avgcount و sum
ceph config get client.ceph-exporter exporter_prio_limit
```

::: {.note}
فرمان‌های `counter dump` و `counter schema` در `src/common/ceph_context.cc` ثبت شده‌اند و شکل برچسب‌دار (labeled) شمارنده‌ها را برمی‌گردانند؛ `perf dump` شکل قدیمی‌تر است. ceph-exporter با فاصله‌ی `exporter_stats_period` (پیش‌فرض ۵ ثانیه) از socketهای پوشه‌ی `exporter_sock_dir` می‌خواند و روی پورت `exporter_http_port` (پیش‌فرض 9926) منتشر می‌کند.
:::

## از time_avg به تأخیر {#sec-20-3-2}

شمارنده‌ی `add_time_avg` دو مقدار دارد: `sum` (مجموع ثانیه‌ها) و `avgcount` (تعداد). میانگین تأخیر در یک بازه، نسبت **افزایش** این دو است، نه نسبت مقادیر خام (که میانگین کل عمر daemon است):

```text
avg_latency(window) = Δsum / Δavgcount
PromQL:  rate(ceph_osd_op_w_latency_sum[5m]) / rate(ceph_osd_op_w_latency_count[5m])
```

::: {.tip}
نام دقیق متریک‌ها را از خود endpoint بخوانید (`curl -s http://host:9926/metrics | grep op_w_latency`)؛ پسوندها (`_sum`، `_count`) و برچسب‌ها ممکن است بین نسخه‌ها و بین ماژول mgr و ceph-exporter متفاوت باشند.
:::

# سیگنال‌های کلیدی {#sec-20-4}

| سیگنال | متریک یا PromQL نمونه | چرا |
|---|---|---|
| سلامت کلی | `ceph_health_status` (۰ سالم، ۱ هشدار، ۲ خطا) | خلاصه‌ی وضعیت |
| کد سلامت مشخص | `ceph_health_detail{name="MON_DOWN"} == 1`؛ برای SLOW_OPS متریک جداگانه‌ی `ceph_healthcheck_slow_ops > 0` (فهرست HEALTH_CHECKS در module.py) | هشدار دقیق بر اساس کدهای فصل ۱۷ |
| OSDهای down | `count(ceph_osd_up == 0)` | از دست رفتن ظرفیت و افزونگی |
| PGهای غیرفعال | `ceph_pool_metadata * on(cluster,pool_id,instance) group_left() (ceph_pg_total - ceph_pg_active) > 0` (عین قاعده‌ی CephPGsInactive) | توقف I/O، به تفکیک pool |
| پری pool | `ceph_pool_percent_used` (کسری بین 0 و 1، نه درصد) | پیشگیری از OSD_FULL |
| quorum | `ceph_mon_quorum_status` | سلامت لایه‌ی کنترل |
| تأخیر نوشتن OSD | `rate(ceph_osd_op_w_latency_sum[5m]) / rate(ceph_osd_op_w_latency_count[5m])` به تفکیک ceph_daemon | کندی کاربر |
| mirroring | `topk by (cluster,ceph_daemon,image,namespace,pool) (1, ceph_rbd_mirror_snapshot_image_local_timestamp) - topk by (…) (1, ceph_rbd_mirror_snapshot_image_remote_timestamp) != 0` (قاعده‌ی CephRBDMirrorImagesNotInSync) | تأخیر RPO |

::: {.note}
همه‌ی نام‌های متریک و عبارت‌های جدول بالا در نوامبر 2026 با src/pybind/mgr/prometheus/module.py و قواعد هشدار رسمی `monitoring/ceph-mixin/prometheus_alerts.yml` شاخه‌ی main تطبیق داده شده‌اند. فایل قواعد ceph-mixin در شاخه‌ی main (هنگام نگارش) ۱۰۹ قاعده دارد؛ از جمله CephHealthError، CephMonDownQuorumAtRisk، CephOSDDown، CephOSDNearFull، CephPGsInactive، CephPGUnavailableBlockingIO، CephSlowOps، CephPoolGrowthWarning و قواعد سخت‌افزاری (مانند PowerSupplyFailed) و NVMe-oF.
:::

# طراحی قواعد هشدار {#sec-20-5}

![چرخه‌ی هشدار در سه مرحله: سیگنال‌ها از ceph_health_detail و متریک‌های وضعیت و تأخیر؛ قاعده در Prometheus با expr و مدت پایداری for، برچسب severity و توضیح همراه لینک runbook؛ و تحویل در Alertmanager با گروه‌بندی بر اساس alertname و cluster، inhibit برای خاموش کردن هشدارهای فرعی و ارسال به on-call](figures/ch20/f03_alertflow.png){#fig-20-f03_alertflow}

قواعد زیر نمونه‌ی خود این کتاب‌اند و جایگزین ceph-mixin نیستند، بلکه الگوی افزودن قواعد محلی را نشان می‌دهند:

```yaml
groups:
- name: ceph-local
  rules:
  - alert: CephWriteLatencyHigh
    expr: |
      ( rate(ceph_osd_op_w_latency_sum[5m]) / rate(ceph_osd_op_w_latency_count[5m]) ) > 0.05
    for: 15m
    labels: { severity: warning }
    annotations:
      summary: "تأخیر نوشتن {{ $labels.ceph_daemon }} بیش از ۵۰ میلی‌ثانیه"
      runbook: "https://wiki.example.internal/runbooks/ceph-slow-osd"
  - alert: CephPoolFillingFast
    expr: predict_linear(ceph_pool_percent_used[6h], 3 * 24 * 3600) > 0.85
    for: 1h
    labels: { severity: warning }
    annotations:
      summary: "pool {{ $labels.pool_id }} در سه روز آینده از ۸۵٪ می‌گذرد"
```

```yaml
# Alertmanager: خاموش کردن هشدار OSD منفرد وقتی کل میزبان down است
inhibit_rules:
- source_matchers: [ alertname = "CephOSDHostDown" ]
  target_matchers: [ alertname = "CephOSDDown" ]
  equal: [ cluster ]
```

::: {.warn}
مقادیر آستانه‌ی بالا (۵۰ میلی‌ثانیه، ۸۵٪) نمونه‌اند. آستانه‌ی واقعی را از پایه‌ی رفتار کلاستر خودتان (مثلاً صدک ۹۵ هفته‌ی گذشته) و SLOهای سرویس استخراج کنید. هشداری که هر روز بی‌دلیل به صدا درآید، به‌سرعت نادیده گرفته می‌شود.
:::

::: {.tip}
در cephadm، قواعد سفارشی کنار قواعد پیش‌فرض قرار می‌گیرند: فایل را با `ceph config-key set mgr/cephadm/services/prometheus/alerting/custom_alerts.yml -i custom_alerts.yml` ثبت و سپس `ceph orch reconfig prometheus` را اجرا کنید (مستندات monitoring در cephadm). طبق همان مستندات، قواعد سفارشی با Jinja پردازش نمی‌شوند.
:::

# لایه‌ی پایین‌تر: از متغیر atomic تا سطر /metrics {#sec-20-6}

هر عدد روی داشبورد از یک متغیر `std::atomic<uint64_t>` در حافظه‌ی یک daemon شروع می‌شود. این بخش مسیر آن را تا Prometheus در سطح بایت و کد دنبال می‌کند تا بدانید هر عدد دقیقاً چه چیزی را اندازه می‌گیرد و کجا ممکن است دروغ بگوید.

## ساختار یک شمارنده {#sec-20-6-1}

`perf_counter_data_any_d` در `src/common/perf_counters.h` برای هر شمارنده یک بایت نوع (bitmask)، یک اولویت و یک واحد نگه می‌دارد:

| بیت نوع | مقدار | معنا |
|---|---|---|
| `PERFCOUNTER_TIME` | 0x1 | مقدار زمانی؛ به نانوثانیه در u64 ذخیره می‌شود (`to_nsec`) |
| `PERFCOUNTER_U64` | 0x2 | عدد صحیح (یکی از TIME یا U64 باید روشن باشد) |
| `PERFCOUNTER_LONGRUNAVG` | 0x4 | جفت «مجموع + تعداد» برای میانگین بلندمدت |
| `PERFCOUNTER_COUNTER` | 0x8 | شمارنده‌ی صعودی (در برابر gauge) |
| `PERFCOUNTER_HISTOGRAM` | 0x10 | هیستوگرام (مثلاً دوبعدی اندازه × تأخیر) |

اولویت‌ها `PRIO_CRITICAL=10`، `PRIO_INTERESTING=8`، `PRIO_USEFUL=5`، `PRIO_UNINTERESTING=2` و `PRIO_DEBUGONLY=0` هستند. این عدد تعیین می‌کند شمارنده اصلاً از daemon بیرون برود یا نه: MgrClient فقط شمارنده‌هایی را گزارش می‌کند که اولویت تنظیم‌شده‌شان `>= mgr_stats_threshold` (پیش‌فرض 5) باشد. ceph-exporter هم همین کار را با `exporter_prio_limit=5` انجام می‌دهد. پس شمارنده‌ای که در `ceph daemon osd.3 perf dump` می‌بینید ولی در Prometheus نیست، احتمالاً اولویتی کمتر از 5 دارد.

## میانگین بدون قفل {#sec-20-6-2}

`tinc` برای یک شمارنده‌ی LONGRUNAVG سه کار را به این ترتیب انجام می‌دهد: `avgcount++`، سپس `u64 += nsec` و در پایان `avgcount2++`. خواننده (`read_avg`) برعکس عمل می‌کند:

```text
pseudocode: read_avg (الگوی seqlock-مانند)
  repeat:
    c   = avgcount2        # شمارنده‌ی «پایان نوشتن»
    sum = u64
  until avgcount == c      # در این فاصله نوشتنی شروع نشده است
  return (sum, c)
```

اگر وسط خواندن یک `tinc` انجام شود، `avgcount` از `avgcount2` جلو می‌افتد و حلقه تکرار می‌شود. بنابراین جفت (sum, count) همیشه با هم سازگار است، بدون mutex در مسیر داغ I/O. چون نویسنده‌های چندتایی (threadهای شارد) هم‌زمان هستند، این تضمین «تقریباً» سازگار است و برای آمار کافی است، نه برای حسابداری دقیق.

::: {.deep}
**عدد خامی که می‌بینید میانگین از لحظه‌ی شروع daemon است.** `perf dump` برای `op_r_latency` مقادیر `avgcount` و `sum` (به ثانیه) و `avgtime=sum/avgcount` را می‌دهد. avgtime میانگین **از زمان شروع daemon** است و یک کندی ۵ دقیقه‌ای را پس از یک ماه کار عملاً نشان نمی‌دهد. همیشه از تفاضل دو نمونه استفاده کنید.
:::

### مثال عددی

فرض کنید دو نمونه به فاصله‌ی ۶۰ ثانیه از `osd.3` گرفته‌ایم:

| نمونه | op_r_latency.avgcount | op_r_latency.sum (s) | avgtime گزارش‌شده |
|---|---|---|---|
| t=0 | 50,000 | 120.5 | 2.41 ms |
| t=60s | 53,000 | 123.5 | 2.33 ms |
| تفاضل | 3,000 | 3.0 | **1.00 ms** (تأخیر واقعی این دقیقه) |

IOPS خواندن در این دقیقه 3000/60=50 است. avgtime از 2.41 به 2.33 رسیده و ظاهراً بهبود کمی نشان می‌دهد، در حالی که تأخیر واقعی این دقیقه 1ms بوده است. برعکسش هم ممکن است: یک دقیقه با تأخیر 50ms، avgtime را فقط کمی بالا می‌برد. در PromQL معادل همین تفاضل این است:

```text
rate(ceph_osd_op_r_latency_sum[1m]) / rate(ceph_osd_op_r_latency_count[1m])
```

## پروتکل admin socket {#sec-20-6-3}

![پروتکل admin socket. یک اتصال UNIX برای هر فرمان باز می‌شود. درخواست رشته‌ی JSON است که با 0x00 یا 0x0A تمام می‌شود. پاسخ با یک طول ۴ بایتی big-endian و سپس payload می‌آید. اگر اولین بایت درخواست 0x00 باشد، پروتکل قدیمی ۴ بایتی فرض می‌شود (کد ۱ یعنی perfcounters_dump و کد ۲ یعنی perfcounters_schema)](figures/ch20/f05_asok.png){#fig-20-f05_asok}

در `AdminSocket::do_accept` کد خطا روی سیم ارسال نمی‌شود. اگر فرمان شکست بخورد، پاسخ با رشته‌ی `ERROR: ` شروع می‌شود، پس ابزار خودکار باید همین پیشوند را بررسی کند. یک کلاینت حداقلی (نوشته‌ی این کتاب، فقط برای فهم پروتکل):

```python
import socket, struct, json, sys
def asok(path, prefix):
    s = socket.socket(socket.AF_UNIX); s.connect(path)
    s.sendall(json.dumps({"prefix": prefix}).encode() + b"\0")
    n = struct.unpack(">I", s.recv(4, socket.MSG_WAITALL))[0]
    buf = b""
    while len(buf) < n: buf += s.recv(n - len(buf))
    s.close()
    if buf.startswith(b"ERROR: "): raise RuntimeError(buf[:200].decode())
    return json.loads(buf)
d = asok(sys.argv[1], "perf dump")
lat = d["osd"]["op_r_latency"]; print(lat["avgcount"], lat["sum"])
```

::: {.warn}
admin socket دسترسی کامل به daemon می‌دهد (از جمله `config set` و فرمان‌های مخرب). فقط root یا کاربر ceph باید به فایل `.asok` دسترسی داشته باشد. هرگز دایرکتوری `/var/run/ceph` را در یک کانتینر پایش با دسترسی نوشتن mount نکنید، مگر آنکه همان ceph-exporter رسمی باشد.
:::

## دو مسیر رسیدن به Prometheus {#sec-20-6-4}

![دو مسیر رسیدن یک شمارنده به Prometheus. مسیر mgr از MgrClient و پیام MMgrReport (هر mgr_stats_period=5 ثانیه) استفاده می‌کند و ماژول prometheus روی پورت 9283 آن را منتشر می‌کند. مسیر ceph-exporter روی هر میزبان مستقیماً از admin socket هر daemon می‌خواند (counter schema و counter dump هر exporter_stats_period=5 ثانیه) و روی پورت 9926 منتشر می‌کند. شمارنده‌های LONGRUNAVG به دو سری _sum و _count تبدیل می‌شوند](figures/ch20/f06_pcpath.png){#fig-20-f06_pcpath}

| گزینه | پیش‌فرض (main) | مسیر |
|---|---|---|
| `mgr_stats_period` | 5 s | MgrClient → mgr |
| `mgr_stats_period_autotune` | true | افزایش خودکار period وقتی صف پیام mgr پر شود (در yaml نسخه‌های Squid و Tentacle هم هست) |
| `mgr_stats_threshold` | 5 | کمترین اولویت ارسالی به mgr |
| `exporter_stats_period` | 5 s | ceph-exporter |
| `exporter_http_port` | 9926 | ceph-exporter |
| `exporter_prio_limit` | 5 | کمترین اولویت منتشرشده در exporter |
| `exporter_sock_dir` | `/var/run/ceph/` | محل جست‌وجوی asokها |

::: {.tip}
**چرا ceph-exporter؟** در خوشه‌ی بزرگ، مسیر mgr همه‌ی شمارنده‌های همه‌ی daemonها را از یک فرایند Python عبور می‌دهد و mgr گلوگاه می‌شود. ceph-exporter این بار را بین میزبان‌ها پخش می‌کند. وقتی هر دو فعال‌اند، شمارنده‌های per-daemon را فقط از یکی scrape کنید تا سری‌های تکراری نداشته باشید (در cephadm، ceph-exporter سرویس جداگانه‌ای با نام `ceph-exporter` است؛ وضعیت آن را با `ceph orch ls ceph-exporter` ببینید).
:::

### دقت زمانی

عدد Prometheus در بدترین حالت قدیمی‌تر از scrape_interval به‌علاوه‌ی دوره‌ی جمع‌آوری (۵ ثانیه) است. با scrape هر 15 ثانیه، یک spike سه‌ثانیه‌ای ممکن است فقط به‌صورت افزایش کوچکی در `rate()` دیده شود. برای عیب‌یابی لحظه‌ای، مستقیم از `ceph daemon osd.N perf dump` یا `ceph tell osd.N dump_historic_ops` (فصل ۲۲) استفاده کنید، نه از داشبورد.

```bash
ceph daemon osd.3 perf schema | jq '.osd.op_r_latency'      # type، priority، units
ceph daemon osd.3 perf dump   | jq '.osd.op_r_latency'      # avgcount، sum، avgtime
ceph daemon osd.3 counter dump | jq 'keys' | head            # شمارنده‌های برچسب‌دار (نسخه‌های جدیدتر)
curl -s localhost:9926/metrics | grep -m3 ceph_osd_op_r_latency
ceph config get mgr mgr_stats_period
```

# پایش با عدد: هیستوگرام، cache و سه قاعده‌ی هشدار {#sec-20-7}

این بخش پنج الگوریتم کوچک پشته‌ی پایش را با عدد بررسی می‌کند. دو الگوریتم درون خود Ceph هستند: هیستوگرام دوبعدی perf counterها و cache ماژول prometheus در mgr. سه الگوریتم دیگر قواعد هشدار پیش‌فرض بسته‌ی `monitoring/ceph-mixin` هستند که cephadm همراه Prometheus مستقر می‌کند. همه‌ی ارجاع‌ها به شاخه‌ی main در نوامبر 2026 است. متن قواعد هشدار در نسخه‌های مختلف بارها تغییر کرده است، پس فایل `prometheus_alerts.yml` نسخه‌ی خودتان را با این متن مقایسه کنید. عددهای مثال با بازپیاده‌سازی پایتونی همین منطق حساب شده‌اند. در مورد `rate()` و `predict_linear()` در Prometheus، پیاده‌سازی ما یک تقریب از منطق Prometheus است.

## هیستوگرام دوبعدی تأخیر و اندازه {#sec-20-7-1}

::: {.algo #alg-20-1 title="نگاشت مقدار به bucket در PerfHistogram" src="src/common/perf_histogram.cc :: PerfHistogramCommon::get_bucket_for_axis، get_axis_bucket_ranges؛ src/osd/osd_perf_counters.cc :: op_hist_x_axis_config، op_hist_y_axis_config" complexity="O(B) برای B bucket در هر محور (B = 32)؛ حافظه B_x × B_y شمارنده"}
:::

```text
pseudocode
bucket(v, axis):
    if v < min: return 0                       # bucket صفر: کمتر از min
    q = (v − min) / quant
    LINEAR: return min(q + 1, buckets − 1)
    LOG2:   for i in 1 .. buckets−1: if q < 2^(i−1): return i
            return buckets − 1                 # bucket آخر: هر چیز بزرگ‌تر
محدوده‌ی bucket i در LOG2: [min + 2^(i−2)·quant ، min + 2^(i−1)·quant − 1]   (i ≥ 2)
hinc(latency_ns, bytes): counts[bucket_x(latency)][bucket_y(bytes)] += 1
```

OSD دو هیستوگرام از این نوع دارد: `op_w_latency_in_bytes_histogram` و `op_r_latency_out_bytes_histogram`. محور x تأخیر است. برچسب آن در کد «Latency (usec)» است، اما مقدار ورودی `latency.to_nsec()` است و quant برابر 100000 نانوثانیه، یعنی 100 میکروثانیه. محور y اندازه‌ی درخواست است با quant ‏512 بایت. هر دو محور LOG2 و 32 bucket دارند.

**مثال عددی.** نوشتنی با تأخیر 1.5 ms: q = 1500000 / 100000 = 15. کوچک‌ترین i با $15 < 2^{i-1}$ عدد 5 است، پس bucket 5 با محدوده‌ی 800 تا 1600 میکروثانیه. اندازه‌ی 4 KiB: q = 4096 / 512 = 8 و i = 5، یعنی محدوده‌ی 4096 تا 8191 بایت. نوشتن 4 MiB به bucket 15 می‌رود. نوشتن 64 KiB به bucket 9 می‌رود. تأخیر 150 µs در bucket 2 (100 تا 200 µs) و 30 ms در bucket 10 (25.6 تا 51.2 ms) است. bucket آخر (31) از $2^{29} \times 100\,\mu\mathrm{s} \approx 53687$ ثانیه شروع می‌شود و در عمل هرگز پر نمی‌شود. کل هیستوگرام 32 × 32 = 1024 شمارنده‌ی 64 بیتی، یعنی 8 KiB برای هر OSD و هر جهت است.

![سمت چپ: نمای هیستوگرام دوبعدی نوشتن برای یک بار مصنوعی با سه اندازه‌ی درخواست (4 KiB، 64 KiB و 4 MiB) و توزیع لگ‌نرمال تأخیر. رنگ لگاریتم تعداد است. هر سطر یک اندازه‌ی درخواست و هر ستون یک بازه‌ی تأخیر است. سمت راست: محدوده‌ی bucketهای محور تأخیر روی محور لگاریتمی. هر bucket دو برابر قبلی است و سه مقدار نمونه (150 µs، 1.5 ms و 30 ms) روی آن نشان داده شده‌اند. عددهای سمت چپ از اندازه‌گیری نیامده‌اند و فقط شکل داده را نشان می‌دهند](figures/ch20/f07_hist.png){#fig-20-f07_hist}

ارزش این هیستوگرام در مقایسه با `op_w_latency` (که فقط میانگین است) این است که دُم توزیع را نشان می‌دهد. اگر میانگین تأخیر 2 ms باشد، نمی‌دانیم همه‌ی درخواست‌ها 2 ms هستند یا 95 درصد 1 ms و 5 درصد 20 ms. هیستوگرام این را جدا می‌کند و سطر به سطر نشان می‌دهد کدام اندازه‌ی درخواست کند است. هیستوگرام از راه admin socket با `ceph daemon osd.N perf histogram dump` خوانده می‌شود. در کد main، ماژول prometheus شمارنده‌های نوع histogram را صریحاً رد می‌کند (توضیح کد: «they are represented by long running avgs»). ceph-exporter هم شمارنده‌ها را از خروجی counter dump و counter schema می‌خواند که محل این هیستوگرام‌ها نیست. پس برای p99 در Prometheus باید از ابزار جانبی یا از اسکریپتی استفاده کرد که dump را می‌خواند.

## cache ماژول prometheus {#sec-20-7-2}

::: {.algo #alg-20-2 title="cache متریک‌ها و سیاست stale" src="src/pybind/mgr/prometheus/module.py :: MetricCollectionThread.collect، Module.config_notify، Root.metrics" complexity="O(1) برای هر scrape (پاسخ از cache)؛ جمع‌آوری O(OSD + PG + pool) در thread جدا"}
:::

```text
pseudocode
thread جمع‌آوری (اگر cache = true):
    loop: start = now ; data = collect() ; d = now − start
          collect_cache = data ; collect_time = d
          sleep(max(0, scrape_interval − d))            # اگر d > interval: هشدار در لاگ و بدون خواب
config: اگر stale_cache_strategy ∉ {fail, return}: strategy = fail   # پیش‌فرض گزینه «log» است
GET /metrics:
    if collect_cache خالی: 503
    if collect_time < scrape_interval: 200 با cache
    if strategy == return: 200 با cache کهنه (و پیام در لاگ)
    if strategy == fail: 503
```

دو نکته‌ی کمتر شناخته‌شده در این کد هست. اول، «کهنه بودن» بر اساس **مدت آخرین جمع‌آوری** سنجیده می‌شود، نه بر اساس سن cache. اگر آخرین `collect()` 17 ثانیه طول کشیده باشد و scrape_interval برابر 15 ثانیه باشد، cache کهنه حساب می‌شود، حتی اگر همین یک ثانیه پیش به‌روز شده باشد. دوم، مقدار پیش‌فرض گزینه‌ی `stale_cache_strategy` در تعریف گزینه «log» است. این مقدار در فهرست مقادیر معتبر نیست و هنگام بارگذاری پیکربندی به fail تبدیل می‌شود. مستندات هم می‌گوید رفتار پیش‌فرض پاسخ 503 است. پس عملاً پیش‌فرض fail است.

**مثال عددی.** با scrape_interval = 15 ثانیه، فرض کنید مدت جمع‌آوری‌ها 5، 5، 6، 17، 18، 6 و 5 ثانیه باشد (مثلاً هنگام peering گسترده). جمع‌آوری‌های 17 و 18 ثانیه‌ای بدون خواب پشت هم اجرا می‌شوند. scrapeهای Prometheus که پس از پایان این دو جمع‌آوری و پیش از پایان جمع‌آوری 6 ثانیه‌ای بعدی می‌رسند، در حالت fail پاسخ 503 می‌گیرند. در شبیه‌سازی ما، دو scrape متوالی (در ثانیه‌ی 70 و 85) 503 می‌شوند. Prometheus هشدار `up == 0` یا «target down» را برای mgr می‌بیند، در حالی که mgr سالم است و فقط کند است. در حالت return همان دو scrape داده‌ی کهنه می‌گیرند و هیچ شکافی در نمودارها دیده نمی‌شود. برای کلاسترهای بزرگ (مستندات عدد بیش از 1000 OSD را ذکر می‌کند)، یا scrape_interval ماژول را بالا ببرید و با Prometheus هماهنگ کنید، یا strategy را return بگذارید.

![خط زمانی cache ماژول prometheus با scrape_interval ‏15 ثانیه. ردیف بالا مدت هر collect() است. جمع‌آوری‌های نارنجی بیش از 15 ثانیه طول کشیده‌اند. دو ردیف پایین پاسخ scrapeهای Prometheus را در دو سیاست نشان می‌دهند. در fail (که مقدار پیش‌فرض log هم به آن تبدیل می‌شود)، scrapeهایی که آخرین جمع‌آوری کامل‌شده‌شان کند بوده است 503 می‌گیرند. در return همان scrapeها داده‌ی کهنه با کد 200 می‌گیرند. مدت‌ها فرضی هستند و برای نشان دادن منطق انتخاب شده‌اند](figures/ch20/f08_cache.png){#fig-20-f08_cache}

## قاعده‌ی CephOSDFlapping {#sec-20-7-3}

::: {.algo #alg-20-3 title="تشخیص flapping با rate روی یک gauge" src="monitoring/ceph-mixin/prometheus_alerts.yml :: CephOSDFlapping" complexity="O(n) برای n نمونه در پنجره‌ی 5 دقیقه برای هر OSD"}
:::

```text
pseudocode
expr: (rate(ceph_osd_up[5m]) × on(cluster, ceph_daemon) group_left(hostname) ceph_osd_metadata) × 60 > 1
rate روی نمونه‌ها: increase = Σ (v_i − v_{i−1} اگر v_i ≥ v_{i−1} ، وگرنه v_i)     # افت 1→0 «reset» است و 0 اضافه می‌کند
                   هر گذار 0→1 یک واحد افزایش است
                   increase برون‌یابی به لبه‌های پنجره ؛ تقسیم بر 300 ثانیه
×60 ⇒ تعداد «بالا آمدن» در دقیقه ؛ هشدار اگر بیش از 1 (بدون for:)
```

`ceph_osd_up` یک gauge با مقدار 0 یا 1 است، اما قاعده `rate()` را روی آن به کار می‌برد که برای counter ساخته شده است. نتیجه کار می‌کند، چون `rate()` هر افت را reset تلقی می‌کند و هر صعود از 0 به 1 را یک واحد افزایش حساب می‌کند. پس rate × 60 تقریباً تعداد دفعاتی است که OSD در هر دقیقه دوباره up شده است.

**مثال عددی.** Prometheus هر 15 ثانیه نمونه می‌گیرد. OSD در فاصله‌ی ثانیه‌ی 330 تا 585 هفت بار down و دوباره up دیده می‌شود (هر بار در یک نمونه 0 است). در ارزیابی ثانیه‌ی 585، پنجره‌ی [285، 585] بیست نمونه و هفت افزایش دارد. برون‌یابی Prometheus آن را حدود 7 × 300 / 285 ≈ 7.4 می‌کند، و rate × 60 ≈ 1.26 > 1 است. هشدار فوراً فعال می‌شود. دو محدودیت مهم دارد. اول، OSDی که بین دو نمونه down و up شود (کمتر از 15 ثانیه) **دیده نمی‌شود**. دوم، شش flap در پنج دقیقه هنوز ممکن است زیر آستانه بماند. برای دید دقیق‌تر، `ceph osd stat` و لاگ mon (پیام‌های «wrongly marked me down») قابل اعتمادترند.

![بالا: نمونه‌های ceph_osd_up هر 15 ثانیه برای یک OSD که در پنج دقیقه‌ی آخر هفت بار down و up می‌شود. ناحیه‌ی زرد پنجره‌ی 5 دقیقه‌ای ارزیابی در ثانیه‌ی 585 است. پایین: مقدار rate(ceph_osd_up\[5m\]) × 60 در هر ارزیابی، با پیاده‌سازی تقریبی برون‌یابی Prometheus. منحنی با هر flap یک پله بالا می‌رود و پس از هفتمین flap از خط‌چین آستانه‌ی 1 می‌گذرد](figures/ch20/f09_flap.png){#fig-20-f09_flap}

## قاعده‌ی CephPGImbalance {#sec-20-7-4}

::: {.algo #alg-20-4 title="انحراف تعداد PG هر OSD از میانگین کلاس دستگاه" src="monitoring/ceph-mixin/prometheus_alerts.yml :: CephPGImbalance" complexity="O(N) برای N OSD در هر ارزیابی"}
:::

```text
pseudocode
x_o = ceph_osd_numpg{o} (فقط اگر > 0) با برچسب device_class از ceph_osd_metadata
avg_c = میانگین x_o روی OSDهای همان (cluster, job, device_class)
هشدار اگر |x_o − avg_c| / avg_c > 0.30  به مدت 5 دقیقه (for: 5m)
```

**مثال عددی.** ده OSD در کلاس hdd به ترتیب 92، 95، 98، 100، 101، 103، 104، 106، 110 و 141 PG دارند. میانگین 105 است و باند مجاز 73.5 تا 136.5. osd.9 با 141 PG حدود 34.3 درصد بالاتر از میانگین است و پس از پنج دقیقه هشدار می‌گیرد. osd.0 با 12.4 درصد کمتر از میانگین در باند است. دو نکته: OSD با صفر PG (مثلاً تازه اضافه‌شده یا out) با فیلتر `> 0` از محاسبه کنار می‌رود و خودش هشدار نمی‌گیرد. همچنین آستانه‌ی 30 درصد بسیار گشاده‌تر از هدف balancer است. balancer در حالت upmap تلاش می‌کند انحراف هر OSD از هدف به حدود چند PG برسد (فصل ۱۹). پس اگر این هشدار فعال شد، معمولاً balancer خاموش است یا نمی‌تواند کار کند، مثلاً به دلیل وزن‌های نادرست CRUSH یا OSDهای تقریباً پر.

![تعداد PG ده OSD در یک کلاس دستگاه، با میانگین 105 (خط سیاه) و باند ±30٪ (سبز). درصد بالای هر ستون انحراف آن OSD از میانگین است. فقط osd.9 با 34.3٪ بیرون از باند است (قرمز) و اگر پنج دقیقه همین‌طور بماند هشدار CephPGImbalance فعال می‌شود. عددها مثال هستند](figures/ch20/f10_imbalance.png){#fig-20-f10_imbalance}

## قاعده‌ی CephPoolGrowthWarning {#sec-20-7-5}

::: {.algo #alg-20-5 title="پیش‌بینی پر شدن pool با رگرسیون خطی" src="monitoring/ceph-mixin/prometheus_alerts.yml :: CephPoolGrowthWarning؛ Prometheus :: predict_linear" complexity="O(n) برای n نمونه در پنجره‌ی 2 روزه"}
:::

```text
pseudocode
expr: (predict_linear(ceph_pool_percent_used[2d], 3600 × 24 × 5) × on(cluster, pool_id, instance) group_right() ceph_pool_metadata) ≥ 0.95
predict_linear: (a, b) = کمترین مربعات روی نمونه‌های 48 ساعت گذشته ، با t نسبت به زمان ارزیابی
                خروجی a + b × 432000                       # مقدار پیش‌بینی‌شده 5 روز بعد
هشدار اگر خروجی ≥ 0.95 (بدون for:)
```

**مثال عددی.** pool در دو روز گذشته از 70 درصد به 78 درصد رسیده است، یعنی شیب 0.04 در روز. نمونه‌ها هر 10 دقیقه گرفته شده‌اند. بدون نویز، پیش‌بینی 5 روز بعد 0.78 + 5 × 0.04 = 0.98 است که از 0.95 بیشتر است و هشدار فعال می‌شود. با نویز مصنوعی (انحراف معیار 0.004) خروجی 0.987 شد. هشدار یعنی «با این روند، پنج روز دیگر pool پر است»، نه این‌که الان پر است. برعکس، اگر رشد ناگهانی در دو ساعت آخر رخ داده باشد، رگرسیون روی 48 ساعت آن را رقیق می‌کند و هشدار دیر می‌آید. توجه کنید که `ceph_pool_percent_used` به `max_avail` وابسته است. max_avail با پرترین OSD زیر CRUSH rule آن pool محاسبه می‌شود. بنابراین عدم توازن داده، percent_used را بالا می‌برد و این هشدار را زودتر فعال می‌کند.

![نمونه‌های مصنوعی ceph_pool_percent_used در 48 ساعت (نقطه‌های آبی)، با رشد خطی از 0.70 به 0.78 و کمی نویز. خط‌چین قرمز خط کمترین مربعات روی همین پنجره است که 5 روز به جلو امتداد یافته. پیش‌بینی در آن نقطه 0.987 است که از خط 0.95 می‌گذرد، پس هشدار فعال می‌شود. خط عمودی نقطه‌ی ارزیابی را نشان می‌دهد](figures/ch20/f11_growth.png){#fig-20-f11_growth}

# mgmt-gateway: یک درِ ورودی {#sec-20-8}

در استقرارهای پیش از Tentacle، Dashboard، Grafana، Prometheus و Alertmanager هر کدام پورت و گواهی جدا داشتند و کاربر باید به چند نشانی دسترسی داشت. **mgmt-gateway** (سرویس cephadm مبتنی بر nginx) همه را پشت یک نقطه‌ی ورود با TLS قرار می‌دهد و با **oauth2-proxy** می‌تواند احراز هویت را به یک IdP بیرونی (OIDC) بسپارد.

![mgmt-gateway به‌عنوان ورودی واحد: مرورگر کاربر به gateway مبتنی بر nginx با TLS و نشانی مجازی وصل می‌شود که در صورت فعال بودن احراز هویت، کاربر را از oauth2-proxy و IdP بیرونی عبور می‌دهد؛ پشت gateway، Dashboard، Grafana، Prometheus و Alertmanager قرار دارند و دیگر مستقیماً در معرض شبکه نیستند](figures/ch20/f04_gateway.png){#fig-20-f04_gateway}

```bash {since=tentacle}
ceph orch apply mgmt-gateway --placement="label:mgmt"
# با نشانی مجازی و احراز هویت (طبق مستندات mgmt-gateway)
ceph orch apply mgmt-gateway --virtual_ip 192.0.2.50 --enable-auth=true --placement="label:mgmt"
ceph orch apply oauth2-proxy -i oauth2-proxy.yaml
ceph orch ls | grep -E "mgmt-gateway|oauth2"
```

::: {.note}
طبق مستندات، نشانی `virtual_ip` در mgmt-gateway باید IP ساده باشد و برای دسترسی‌پذیری بالا همراه سرویس ingress با همان IP (با پیشوند شبکه) به کار می‌رود؛ oauth2-proxy بی‌حالت است و می‌تواند چند نمونه داشته باشد. پس از استقرار gateway، endpointهای پشته‌ی پایش (از جمله service discovery) امن (https) می‌شوند.
:::

::: {.warn}
Prometheus و Alertmanager را مستقیماً در معرض شبکه‌ی کاربران قرار ندهید: مستندات monitoring یادآوری می‌کند که مدل امنیتی Prometheus فرض می‌کند کاربران نامطمئن به endpoint و داده‌ها دسترسی دارند و API فقط‌خواندنی آن همه‌ی (فرا)داده‌های جمع‌آوری‌شده را آشکار می‌کند. gateway یا فایروال لازم است.
:::

# log و رویدادها {#sec-20-9}

- **log کلاستر** در MON: `ceph log last 200`، و پیگیری زنده با `ceph -w`؛ کانال cephadm با `ceph -W cephadm`.
- **log daemonها** در cephadm به journald می‌روند: `cephadm logs --name osd.3` یا `journalctl -u ceph-<fsid>@osd.3`؛ برای نوشتن در فایل `ceph config set global log_to_file true`.
- **crashها** با ماژول crash جمع می‌شوند و در هشدار RECENT_CRASH ظاهر می‌شوند؛ `ceph crash ls`، `ceph crash info <id>`، `ceph crash archive-all`.
- **telemetry** (اختیاری و با رضایت): ارسال آمار ناشناس به پروژه؛ پیش‌نمایش با `ceph telemetry preview` (فصل ۹).

::: {.tip}
برای جمع‌آوری متمرکز log، journald میزبان‌ها را با ابزار انتخابی سازمان (مثلاً یک عامل جمع‌آوری log) به سامانه‌ی مرکزی بفرستید و برچسب fsid و نام daemon را حفظ کنید تا بتوانید log را با متریک‌ها و هشدارها هم‌زمان کنید.
:::

# داشبوردها و SLO {#sec-20-10}

داشبوردهای ceph-mixin (کلاستر، میزبان، OSD، pool، RGW، RBD، CephFS) همراه Grafana مستقر می‌شوند. برای راهبری سرویس، علاوه بر آن‌ها چند نمای سطح سرویس بسازید:

| SLI | تعریف نمونه | منبع |
|---|---|---|
| دسترس‌پذیری RBD | درصد زمانی که همه‌ی PGهای pool فعال‌اند | ceph_pg_active / ceph_pg_total برای pool |
| تأخیر نوشتن | صدک ۹۹ تأخیر نوشتن OSD یا کلاینت | ceph-exporter (و شمارنده‌های librbd در صورت فعال بودن) |
| دسترس‌پذیری S3 | نسبت پاسخ‌های غیر ۵xx در RGW | log دسترسی RGW یا شمارنده‌های rgw |
| RPO mirroring | اختلاف timestamp محلی و راه دور تصاویر | متریک‌های ceph_rbd_mirror_snapshot_* |

::: {.summary title="نکات SRE این فصل"}

- پشته‌ی پایش را با cephadm مستقر و ceph-exporter را روی همه‌ی میزبان‌ها فعال کنید.
- همه‌ی mgrها یا service discovery را برای scrape تعریف کنید تا failover نقطه‌ی کور نسازد.
- میانگین تأخیر را از نسبت rate شمارنده‌ها حساب کنید، نه از مقدار خام.
- قواعد محلی را با runbook همراه کنید و آستانه را از رفتار واقعی بگیرید.
- Prometheus و Alertmanager را پشت mgmt-gateway یا فایروال نگه دارید.

:::

# تکمیلی و به‌روز {#sec-20-11}

- انتقال perf counters از ماژول prometheus به ceph-exporter (پیش‌فرض `exclude_perf_counters`) مهم‌ترین تغییر معماری پایش از ۲۰۱۹ است؛ در آن سال‌ها پایش بیشتر بر Calamari و ابزارهای جانبی تکیه داشت که امروز جای خود را به Dashboard و پشته‌ی Prometheus داده‌اند.
- mgmt-gateway و oauth2-proxy در Tentacle آمده‌اند.
- قواعد سخت‌افزاری (منبع تغذیه، خنک‌کننده، NVMe) و NVMe-oF به ceph-mixin افزوده شده‌اند.

# تمرین عملی {#sec-20-12}

1. پشته‌ی پایش را با cephadm مستقر کنید و همه‌ی هدف‌ها را در صفحه‌ی Targets پرومتئوس سالم ببینید.
2. با `ceph daemon osd.N counter dump` و `curl` روی پورت ceph-exporter، یک شمارنده را در هر دو شکل مقایسه کنید.
3. قاعده‌ی CephWriteLatencyHigh را اضافه کنید و با `tc netem` روی شبکه‌ی cluster آن را فعال کنید.
4. یک قاعده‌ی inhibit برای CephOSDHostDown و CephOSDDown بنویسید و با خاموش کردن یک میزبان آزمایش کنید.
5. mgr فعال را با `ceph mgr fail` جابه‌جا کنید و پیوستگی سری‌های زمانی را بررسی کنید.
6. mgmt-gateway را مستقر کنید و دسترسی مستقیم به پورت Prometheus را با فایروال ببندید.

# پرسش‌های مرور {#sec-20-13}

1. چرا perf counters از ماژول prometheus به ceph-exporter منتقل شدند؟
2. چرا باید همه‌ی mgrها یا service discovery را برای scrape تعریف کرد؟
3. اولویت شمارنده و exporter_prio_limit چه رابطه‌ای دارند؟
4. میانگین تأخیر یک بازه از شمارنده‌ی time_avg چگونه محاسبه می‌شود؟
5. متریک ceph_health_detail چه کاربردی دارد؟
6. نقش for در قاعده‌ی هشدار چیست؟
7. inhibit در Alertmanager چه مشکلی را حل می‌کند؟
8. mgmt-gateway چه مزایایی دارد؟
9. چرا Prometheus نباید مستقیماً در معرض کاربران باشد؟
10. چند SLI مناسب برای سرویس RBD نام ببرید.

# منابع این فصل {#sec-20-14}

- Monitoring overview: https://docs.ceph.com/en/latest/monitoring/
- cephadm monitoring services: https://docs.ceph.com/en/latest/cephadm/services/monitoring/
- Prometheus manager module: https://docs.ceph.com/en/latest/mgr/prometheus/
- mgmt-gateway: https://docs.ceph.com/en/latest/cephadm/services/mgmt-gateway/
- oauth2-proxy: https://docs.ceph.com/en/latest/cephadm/services/oauth2-proxy/
- Ceph Dashboard: https://docs.ceph.com/en/latest/mgr/dashboard/
- Crash module: https://docs.ceph.com/en/latest/mgr/crash/
- ceph-mixin alerts: https://github.com/ceph/ceph/blob/main/monitoring/ceph-mixin/prometheus_alerts.yml
- Source: src/common/perf_counters.h: https://github.com/ceph/ceph/blob/main/src/common/perf_counters.h
- Source: src/common/options/ceph-exporter.yaml.in: https://github.com/ceph/ceph/blob/main/src/common/options/ceph-exporter.yaml.in
- Prometheus security model: https://prometheus.io/docs/operating/security/
