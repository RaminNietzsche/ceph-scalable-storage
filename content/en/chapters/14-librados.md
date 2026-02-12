---
chapter: 14
id: ch14
title: Programming with librados
part: main
original_heading: Developing with Librados
lang: en
translation: pending
---

# پیش از شروع {#sec-14-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-14-1-1}

RBD، RGW و CephFS همه در نهایت مشتری‌های **librados** هستند: کتابخانه‌ای که دسترسی مستقیم به اشیای RADOS را فراهم می‌کند. وقتی هیچ‌کدام از رابط‌های آماده با نیاز شما جور نیست (مثلاً یک صف پیام، یک سامانه‌ی قفل توزیع‌شده یا ذخیره‌ی کلید-مقدار با تضمین اتمی)، می‌توانید مستقیماً روی RADOS برنامه بنویسید. این فصل librados را از سه زاویه بررسی می‌کند: API، الگوهای کاربردی (عملیات اتمی، watch/notify) و درون کتابخانه (Objecter).

- librados چیست و در کجای پشته قرار دارد؟
- اتصال، IoCtx، namespace و عملیات پایه چطور انجام می‌شوند؟
- عملیات مرکب و اتمی چه تضمینی دارند؟
- watch/notify چطور کار می‌کند و برای چه مناسب است؟
- Objecter چطور هدف هر درخواست را محاسبه و تغییرات نقشه را مدیریت می‌کند؟
- چه دام‌هایی در برنامه‌نویسی RADOS هست؟

# librados چیست؟ {#sec-14-2}

![جایگاه librados: کتابخانه‌های بالادستی و برنامه‌ی شما از طریق IoCtx با librados کار می‌کنند؛ Objecter هدف هر عملیات را محاسبه می‌کند و MonClient نقشه‌ها و احراز هویت را مدیریت می‌کند](figures/ch14/f01_stack.png){#fig-14-f01_stack}

librados رابط بومی RADOS است و در چند زبان در دسترس است: C (`librados.h`)، C++ (`librados.hpp`)، Python (ماژول `rados`)، و از طریق bindingهای جامعه در Go و Rust. مفاهیم پایه:

| مفهوم | معنی |
|---|---|
| Rados / cluster handle | اتصال به کلاستر با هویت cephx و فایل پیکربندی |
| IoCtx | زمینه‌ی I/O روی یک pool (و اختیاری یک namespace)؛ همه‌ی عملیات شیء از طریق آن |
| شیء | نام (رشته‌ی دلخواه)، داده‌ی بایتی، xattrها و omap (کلید-مقدار مرتب) |
| namespace | زیرفضای نام درون pool برای جداسازی مستأجران بدون pool جدا |
| locator key | کلید جایگزین برای محاسبه‌ی PG، تا اشیای مرتبط در یک PG قرار گیرند |
| snap context | برای snapshotهای self-managed (روشی که RBD استفاده می‌کند) |

::: {.note}
یک شیء RADOS سه بخش مستقل دارد: **داده** (مانند فایل، با offset)، **xattr** (چند ویژگی کوچک) و **omap** (کلید-مقدار مرتب، در RocksDB زیر BlueStore). omap برای شاخص‌ها و فراداده عالی است، اما در pool EC پشتیبانی نمی‌شود و omapهای بسیار بزرگ (میلیون‌ها کلید در یک شیء) مشکلاتی مثل scrub طولانی و هشدار `LARGE_OMAP_OBJECTS` ایجاد می‌کنند.
:::

# شروع کار {#sec-14-3}

## آماده‌سازی {#sec-14-3-1}

```bash
sudo dnf install -y python3-rados librados-devel     # یا apt install python3-rados librados-dev
ceph osd pool create devpool 32
ceph osd pool application enable devpool myapp
ceph auth get-or-create client.devapp mon 'allow r' osd 'allow rwx pool=devpool' \
  -o /etc/ceph/ceph.client.devapp.keyring
```

::: {.tip}
پرچم `x` در capability OSD برای فراخوانی متدهای کلاس RADOS (`exec`) لازم است (فصل ۱۵). اگر برنامه‌ی شما فقط داده می‌خواند و می‌نویسد، `rw` کافی است؛ کمترین دسترسی لازم را بدهید.
:::

## یک برنامه‌ی پایتونی ساده {#sec-14-3-2}

```python
#!/usr/bin/env python3
import rados

with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as cluster:
    print("fsid:", cluster.get_fsid())
    with cluster.open_ioctx('devpool') as io:
        io.set_namespace('tenant-a')
        io.write_full('greeting', b'salam donya')
        io.set_xattr('greeting', 'lang', b'fa')
        print(io.read('greeting'))
        print(dict(io.get_xattrs('greeting')))
        # omap با WriteOp
        with rados.WriteOpCtx() as op:
            io.set_omap(op, ('k1', 'k2'), (b'v1', b'v2'))
            io.operate_write_op(op, 'index')
        with rados.ReadOpCtx() as op:
            it, ret = io.get_omap_vals(op, "", "", 100)
            io.operate_read_op(op, 'index')
            print(dict(it))
        for obj in io.list_objects():
            print(obj.nspace, obj.key)
```

## همان در C++ {#sec-14-3-3}

```cpp
// my_app.cc — نمونه‌ی نوشته‌شده برای این فصل
#include <rados/librados.hpp>
#include <iostream>
int main() {
  librados::Rados cluster;
  cluster.init2("client.devapp", "ceph", 0);
  cluster.conf_read_file("/etc/ceph/ceph.conf");
  if (int r = cluster.connect(); r < 0) { std::cerr << "connect: " << r << "\n"; return 1; }
  librados::IoCtx io;
  cluster.ioctx_create("devpool", io);
  io.set_namespace("tenant-a");
  librados::bufferlist bl;
  bl.append("salam donya");
  io.write_full("greeting", bl);
  librados::bufferlist out;
  io.read("greeting", out, 0, 0);
  std::cout << out.to_str() << "\n";
  cluster.shutdown();
}
```

```bash
g++ -std=c++20 my_app.cc -lrados -o my_app && ./my_app
```

## ناهمگام (aio) {#sec-14-3-4}

برای توان بالا، عملیات را ناهمگام بفرستید تا چند درخواست هم‌زمان در جریان باشد:

```python
import rados, threading
done = threading.Semaphore(0)
def on_complete(completion):
    done.release()
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c, c.open_ioctx('devpool') as io:
    N = 64
    for i in range(N):
        io.aio_write_full(f'obj-{i}', b'x' * 65536, oncomplete=on_complete)
    for _ in range(N):
        done.acquire()
```

::: {.warn}
در حلقه‌های ناهمگام، تعداد درخواست‌های در جریان را محدود کنید (مثلاً با semaphore). فرستادن صدها هزار درخواست هم‌زمان حافظه‌ی کلاینت را پر می‌کند و throttleهای Objecter (`objecter_inflight_ops` و `objecter_inflight_op_bytes`) درخواست‌ها را معطل می‌کنند.
:::

# عملیات اتمی {#sec-14-4}

## عملیات مرکب {#sec-14-4-1}

![ساختار یک عملیات مرکب: guardها، تغییرها و فراخوانی کلاس در یک تراکنش اتمی روی یک شیء اجرا می‌شوند](figures/ch14/f05_compound.png){#fig-14-f05_compound}

RADOS روی **یک شیء** تراکنش اتمی می‌دهد: چند عملیات (نوشتن داده، تغییر xattr، به‌روزرسانی omap، شرط‌ها) را در یک `ObjectWriteOperation` جمع می‌کنید و OSD همه را با هم اجرا می‌کند یا هیچ‌کدام را. اگر یکی از **guard**ها (شرط‌ها) شکست بخورد، هیچ تغییری اعمال نمی‌شود. تراکنش بین چند شیء وجود ندارد؛ این مهم‌ترین محدودیت طراحی روی RADOS است.

## الگوی compare-and-swap با نسخه {#sec-14-4-2}

هر شیء یک **user_version** دارد که با هر تغییر افزایش می‌یابد. با `assert_version` می‌توان «فقط اگر از وقتی خواندم کسی تغییرش نداده» نوشت:

![کنترل هم‌زمانی خوش‌بینانه با assert_version: کلاینت B که نسخه‌ی قدیمی را دیده، خطا می‌گیرد و پس از خواندن دوباره تلاش می‌کند](figures/ch14/f03_atomic.png){#fig-14-f03_atomic}

```python
import rados, errno

def increment(io, oid):
    while True:
        try:
            data = io.read(oid, length=64)   # پیش‌فرض length در binding برابر 8192 است
            ver = io.get_last_version()
        except rados.ObjectNotFound:
            data, ver = b'0', None
        new = str(int(data) + 1).encode()
        with rados.WriteOpCtx() as op:
            if ver is None:
                op.new(rados.LIBRADOS_CREATE_EXCLUSIVE)    # فقط اگر وجود ندارد
            else:
                op.assert_version(ver)
            op.write_full(new)
            try:
                io.operate_write_op(op, oid)
                return int(new)
            except (rados.OSError, rados.ObjectExists) as e:
                continue    # کسی زودتر نوشت؛ دوباره
```

در OSD، این بررسی در `PrimaryLogPG::do_osd_ops` انجام می‌شود:

```cpp
// from ceph/ceph, LGPL — src/osd/PrimaryLogPG.cc (excerpt)
case CEPH_OSD_OP_ASSERT_VER:
  ...
  if (!ver) {
    result = -EINVAL;
  } else if (ver < oi.user_version) {
    result = -ERANGE;
  } else if (ver > oi.user_version) {
    result = -EOVERFLOW;
  }
```

پس نسخه‌ی کهنه `-ERANGE` و نسخه‌ای که هنوز وجود ندارد `-EOVERFLOW` برمی‌گرداند. guardهای دیگر: `cmpxattr` (مقایسه‌ی یک xattr)، `cmpext` (مقایسه‌ی بخشی از داده)، `assert_exists` و `omap_cmp`.

## قفل توزیع‌شده {#sec-14-4-3}

librados قفل‌های مشورتی (advisory) روی اشیا دارد که با کلاس `lock` در OSD پیاده شده‌اند؛ RBD برای exclusive-lock از همین استفاده می‌کند:

```python
io.lock_exclusive('jobs', 'scheduler', cookie='node-a', desc='leader', duration=30)
# ... کار ...
io.unlock('jobs', 'scheduler', 'node-a')
```

::: {.warn}
قفل مشورتی فقط وقتی کار می‌کند که همه‌ی کلاینت‌ها آن را رعایت کنند. با `duration`، قفل کلاینتی که مرده خودبه‌خود منقضی می‌شود؛ اما کلاینتی که فقط کند شده هم ممکن است قفلش را از دست بدهد و بی‌خبر ادامه دهد. برای ایمنی واقعی، قفل را با guard در عملیات نوشتن ترکیب کنید (مثلاً `assert_locked` در کلاس lock) یا مانند RBD، کلاینت قبلی را **blocklist** کنید.
:::

# watch و notify {#sec-14-5}

![watch/notify: watcherها روی یک شیء ثبت‌نام می‌کنند؛ notify به همه می‌رسد و notifier پس از دریافت ackها یا timeout پاسخ تجمیعی می‌گیرد](figures/ch14/f04_watch.png){#fig-14-f04_watch}

watch/notify یک کانال اعلان سبک روی یک شیء است: هر کلاینت روی شیء **watch** ثبت می‌کند و هر کلاینتی می‌تواند **notify** بفرستد که به همه‌ی watcherها می‌رسد. RBD از آن برای اطلاع‌رسانی تغییر header image (مثلاً resize یا snapshot) به همه‌ی کلاینت‌هایی که image را باز کرده‌اند استفاده می‌کند. RGW هم برای همگام‌سازی cache بین نمونه‌ها از آن بهره می‌برد.

```python
# watcher.py
import rados, time
def on_notify(notify_id, notifier_id, watch_id, data):
    print("got:", data)
    return b'ok'           # payload پاسخ (در نسخه‌های جدید binding)
def on_error(err):
    print("watch error:", err)    # باید watch را دوباره ثبت کنید
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c, c.open_ioctx('devpool') as io:
    io.write_full('config', b'v1')
    with io.watch('config', on_notify, on_error):
        time.sleep(600)
```

```python
# notifier.py
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c, c.open_ioctx('devpool') as io:
    io.notify('config', 'reload', timeout_ms=5000)
```

::: {.deep}
watch در کلاینت به شکل یک عملیات **linger** در Objecter پیاده شده است: درخواستی که «تمام نمی‌شود» و Objecter هر بار که نقشه تغییر کند یا اتصال قطع شود، آن را دوباره به primary فعلی شیء می‌فرستد (`Objecter::_recalc_linger_op_target`). در OSD، watch بخشی از وضعیت شیء است و با ping دوره‌ای زنده نگه داشته می‌شود؛ اگر کلاینت در مهلت ping نکند، watch حذف می‌شود و callback خطای کلاینت باید watch را دوباره بسازد. notify اگر همه‌ی watcherها در مهلت ack ندهند، با timeout تمام می‌شود و فهرست watcherهای بی‌پاسخ را برمی‌گرداند؛ مهلت پیش‌فرض سمت OSD `osd_default_notify_timeout` است (در کد جاری ۳۰ ثانیه).
:::

::: {.tip}
watch/notify برای **اعلان** است، نه انتقال داده‌ی حجیم یا صف قابل اتکا: اگر watcher در لحظه‌ی notify قطع باشد، پیام را از دست می‌دهد. الگوی درست: داده‌ی واقعی را در شیء (یا omap) بنویسید و notify فقط بگوید «چیزی تغییر کرد، دوباره بخوان». watcher پس از اتصال دوباره هم باید یک بار وضعیت را بخواند.
:::

# زیر librados: پیام MOSDOp، session و backoff {#sec-14-6}

بخش «از درون کد: Objecter» در ادامه‌ی همین فصل نشان می‌دهد librados چگونه یک op را به Objecter می‌دهد. اینجا یک لایه پایین‌تر می‌رویم: پیامی که روی سیم می‌رود دقیقاً چه چیزی دارد، Objecter چگونه opها را بر اساس OSD در sessionها نگه می‌دارد، و OSD چگونه می‌تواند به کلاینت بگوید «فعلاً نفرست» (backoff). همه‌ی ساختارها از main هستند (`src/osdc/Objecter.cc`، `src/messages/MOSDOp.h` و `src/include/rados.h`).

![ترتیب فیلدها در payload پیام MOSDOp با HEAD_VERSION=9 (COMPAT_VERSION=3). ابتدا pgid و hash شیء، epoch نقشه و flags، شناسه‌ی درخواست (reqid)، client_inc و mtime، سپس object_locator و نام شیء، تعداد و ساختار هر op، و در پایان اطلاعات snapshot، retry_attempt و features می‌آیند. در msgr2 همه‌ی این‌ها در segment از نوع front هستند و داده‌ی ورودی همه‌ی opها پشت سر هم در segment data قرار می‌گیرد](figures/ch14/f06_mosdop.png){#fig-14-f06_mosdop}

## چرا pgid پیش از نام شیء می‌آید؟ {#sec-14-6-1}

OSD پیام را در دو مرحله decode می‌کند (`partial_decode_needed` و `final_decode_needed` در کلاس). در مرحله‌ی اول فقط pgid، hash، epoch و flags خوانده می‌شوند. این کافی است تا پیام بدون decode کامل به shard درست صف عملیاتی (`OSDShard`) فرستاده شود. decode کامل (نام، opها و snapها) بعداً در thread همان shard انجام می‌شود. این طراحی، کار thread مربوط به messenger را کم و موازی‌سازی را بیشتر می‌کند. به همین دلیل MOSDOp از `MOSDFastDispatchOp` ارث می‌برد.

| فیلد | نقش در OSD |
|---|---|
| `osdmap_epoch` | اگر از epoch فعلی OSD جدیدتر باشد، OSD ابتدا نقشه را می‌گیرد. اگر قدیمی‌تر باشد و PG جابه‌جا شده باشد، op دور ریخته می‌شود و کلاینت با نقشه‌ی جدید دوباره می‌فرستد. |
| `reqid` (client.N:tid) | کلید تشخیص تکرار. OSD در pg log آن را جست‌وجو می‌کند و برای op تکراری (پس از resend) پاسخ قبلی را برمی‌گرداند. |
| `flags` | مثلاً `ONDISK`، `READ`، `WRITE`، `BALANCE_READS`، `LOCALIZE_READS`، `FULL_TRY` |
| `retry_attempt` | شمارنده‌ی ارسال مجدد؛ در لاگ OSD و `dump_ops_in_flight` دیده می‌شود |
| `snap_seq`، `snaps` | SnapContext نویسنده برای COW snapshot (فصل ۲) |

## sessionها و op «بی‌خانمان» {#sec-14-6-2}

Objecter برای هر OSD یک `OSDSession` دارد که opهای در جریان آن OSD را با tid نگه می‌دارد. هر op در `_calc_target` به یک OSD نگاشت می‌شود. اگر هدفی وجود نداشته باشد (pool حذف شده، PG بدون primary یا نقشه هنوز نرسیده)، op به `homeless_session` منتقل می‌شود. با هر نقشه‌ی جدید، Objecter همه‌ی opها را دوباره هدف‌یابی می‌کند و آن‌هایی را که هدفشان تغییر کرده، به session تازه منتقل و دوباره ارسال می‌کند.

| گزینه | پیش‌فرض | اثر |
|---|---|---|
| `objecter_inflight_ops` | 1_K | سقف opهای در جریان؛ بیش از آن، `op_submit` بلوک می‌شود (throttle بودجه) |
| `objecter_inflight_op_bytes` | 100_M | سقف بایت‌های در جریان |
| `objecter_tick_interval` | 5 | ثانیه؛ بررسی opهای کند و ارسال keepalive |
| `objecter_timeout` | 10 | ثانیه؛ پس از آن، برای sessionهای بی‌پاسخ درخواست نقشه یا ping |
| `rados_osd_op_timeout` | 0 | ۰ یعنی بدون timeout؛ مقدار مثبت خطای `ETIMEDOUT` می‌دهد |
| `objecter_completion_locks_per_session` | 32 | قفل‌های شاردشده برای ترتیب completionها |

::: {.warn}
`objecter_inflight_ops=1024` برای برنامه‌ای که با `aio_write` هزاران op هم‌زمان می‌فرستد، یک گلوگاه پنهان است: فراخوانی `aio_*` **بلوک** می‌شود تا بودجه آزاد شود. اگر callbackهای completion در همان thread منتظر باشند، بن‌بست ایجاد می‌شود. عمق صف را در برنامه کنترل کنید یا گزینه را آگاهانه افزایش دهید.
:::

# backoff: OSD می‌گوید «صبر کن» {#sec-14-7}

![سازوکار backoff. وقتی PG در حال peering است یا شیء unfound است، OSD به‌جای نگه داشتن op در صف خودش (که حافظه و thread مصرف می‌کند)، یک MOSDBackoff با عمل BLOCK برای یک بازه‌ی hobject به کلاینت می‌فرستد. کلاینت تأیید می‌کند و opهای آن بازه را نزد خودش نگه می‌دارد. پس از فعال شدن PG، OSD با UNBLOCK آزادسازی را اعلام می‌کند و کلاینت opها را دوباره می‌فرستد](figures/ch14/f07_backoff.png){#fig-14-f07_backoff}

عمل‌ها در `rados.h` عبارت‌اند از `CEPH_OSD_BACKOFF_OP_BLOCK=1`، `ACK_BLOCK=2` و `UNBLOCK=3`. پیش‌فرض‌های OSD (در main): `osd_backoff_on_unfound=true`، `osd_backoff_on_degraded=false` و `osd_backoff_on_peering=false`. پس به‌طور پیش‌فرض فقط برای اشیای unfound، backoff فرستاده می‌شود. در حالت‌های دیگر op در OSD صف می‌شود. backoff به ویژگی `RADOS_BACKOFF` در کلاینت نیاز دارد که کلاینت‌های Luminous به بعد آن را دارند.

```bash
ceph daemon osd.4 dump_blocked_ops
ceph daemon client.admin.<pid>.<cookie> objecter_requests     # از admin socket کلاینت
ceph tell osd.4 config get osd_backoff_on_peering
```

# SplitOp (فقط main) {#sec-14-8}

شاخه‌ی main یک کلاس تازه به نام `SplitOp` در `src/osdc/` دارد (مجوز LGPL 2.1، ۲۰۲۵). توضیح خود کد آن را «پایه‌ای برای تقسیم عملیات بین چند OSD برای کارایی بهتر» معرفی می‌کند: در poolهای EC، یک خواندن بزرگ مستقیم به shardهای داده فرستاده می‌شود، و در poolهای replicated، یک خواندن بزرگ بین replicaها تقسیم می‌شود. سپس پاسخ‌ها در کلاینت به هم وصل می‌شوند. شمارنده‌ای با توضیح «Client read ops split by SplitOp» هم به Objecter اضافه شده است. این کلاس در شاخه‌ی Tentacle نیست (فایل آن در آن شاخه وجود ندارد). پس این قابلیت مربوط به انتشار بعدی است و جزئیات، گزینه‌ها و پیش‌فرض‌هایش ممکن است پیش از انتشار تغییر کند.

::: {.deep}
**چرا خواندن مستقیم از shard در EC ممکن شد؟** در EC قدیمی، کلاینت همیشه به primary می‌فرستاد و primary از k shard می‌خواند و decode می‌کرد. با `FLAG_EC_PLUGIN_PARTIAL_READ_OPTIMIZATION` (فصل ۲۷)، داده‌ی یک بازه دقیقاً در یک shard داده قرار دارد. اگر کلاینت چیدمان stripe را بداند (stripe_unit و k از پروفایل pool)، می‌تواند بازه را خودش به shardها نگاشت کند و یک رفت‌وبرگشت شبکه (کلاینت→primary→shard) حذف شود. ترکیب این با `SplitOp`، پایه‌ی خواندن‌های سریع‌تر از EC در نسخه‌های آینده است.
:::

# Objecter با عدد: بودجه‌ی op، سقف در جریان، زنده‌بودن watch و timeout ‏notify {#sec-14-9}

این بخش چهار سازوکار کوچک در کلاینت RADOS را بررسی می‌کند که در برنامه‌های واقعی رفتار غیرمنتظره ایجاد می‌کنند. ارجاع‌ها به main در نوامبر 2026 است. همه‌ی پیش‌فرض‌ها از فایل‌های src/common/options خوانده شده‌اند.

## بودجه‌ی هر op {#sec-14-9-1}

::: {.algo #alg-14-1 title="محاسبه‌ی بودجه و throttle دوگانه" src="src/osdc/Objecter.cc :: Objecter::calc_op_budget، _throttle_op؛ src/common/Throttle.h :: Throttle::_should_wait" complexity="O(تعداد زیرعملیات op)"}
:::

```text
pseudocode
budget = 0
برای هر زیرعملیات:
    if حالت WR: budget += طول indata
    elif حالت RD و از extent استفاده می‌کند (READ، SPARSE_READ، CMPEXT…): budget += extent.length
    elif RD و نوع ATTR: budget += name_len + value_len
    # بقیه (STAT، OMAPGETVALS، CALL با حالت RD|EXEC…) صفر
op_throttle_bytes.get(budget)   # سقف objecter_inflight_op_bytes = 100 MiB
op_throttle_ops.get(1)          # سقف objecter_inflight_ops = 1024
_should_wait(c) = (c ≤ max و cur + c > max) یا (c ≥ max و cur > max)
```

| عملیات | budget بایت | توضیح |
|---|---|---|
| write ‏4 KiB | 4096 | طول داده |
| writefull ‏4 MiB | 4194304 | 25تا از آن کل سقف 100 MiB را پر می‌کند |
| read ‏64 KiB | 65536 | طول extent، نه طول پاسخ واقعی |
| getxattr «user.x» با مقدار 100 بایتی | 106 | طول نام و مقدار |
| omap_get_vals | 0 | فقط یک واحد از سقف 1024 تایی |
| omap_set_vals با 1 MiB کلید و مقدار | 1048576 | حالت WR، پس indata شمرده می‌شود |
| CALL (کلاس) با ورودی 10 MiB | 0 | حالت CALL فقط RD است، پس ورودی شمرده نمی‌شود |

**نتیجه.** سقف بایت برای opهای بزرگ و سقف تعداد برای opهای کوچک تعیین‌کننده است. op بزرگ‌تر از 100 MiB قفل نمی‌شود. اگر cur ≤ max باشد، بی‌درنگ رد می‌شود، اما بعد از آن cur > max است و همه‌ی opهای بعدی صبر می‌کنند تا آن op تمام شود. فراخوانی کلاس با ورودی حجیم عملاً throttle بایتی ندارد. برنامه‌ای که با aio_exec بلاک‌های بزرگ می‌فرستد باید خودش محدودیت بگذارد.

## سقف در جریان و قانون Little {#sec-14-9-2}

::: {.algo #alg-14-2 title="سقف throughput یک نمونه‌ی Objecter" src="src/osdc/Objecter.cc :: _throttle_op (با پیش‌فرض‌های objecter_inflight_ops و objecter_inflight_op_bytes)" complexity="O(1)"}
:::

```text
pseudocode
N(s) = s > 100 MiB ? 1 : min(1024, ⌊104857600 / s⌋)      # op هم‌زمان با اندازه‌ی s
throughput ≤ N(s) × s / latency
IOPS ≤ N(s) / latency
نقطه‌ی تغییر: s = 104857600 / 1024 = 102400 بایت (100 KiB)
```

**مثال عددی.** برای op چهار کیلوبایتی N = 1024 است. با تأخیر 2 میلی‌ثانیه، سقف 512000 IOPS ‏(2 GiB/s) است و با 10 میلی‌ثانیه، 102400 IOPS. برای op ‏128 KiB، ‏N = 800 است. برای 4 MiB ‏N = 25 است: با تأخیر 10 میلی‌ثانیه حدود 9.8 GiB/s و با 50 میلی‌ثانیه (EC روی HDD زیر بار) فقط 1.95 GiB/s برای کل یک نمونه‌ی librados، صرف‌نظر از تعداد threadها. برای 16 MiB، ‏N = 6 است. این سقف برای **هر نمونه‌ی Rados/Objecter** است. پس یا آن را با `objecter_inflight_op_bytes` بالا ببرید، یا چند نمونه‌ی مستقل بسازید. در فرایندهای QEMU یا rbd-nbd، تنظیم معادل در بخش [client] قرار می‌گیرد.

![چپ: تعداد op هم‌زمان مجاز برحسب اندازه‌ی op. تا 100 KiB سقف 1024 حاکم است و بالاتر از آن ⌊100 MiB / s⌋. بالاتر از 100 MiB فقط یک op در جریان است. راست: سقف throughput یک نمونه‌ی Objecter با قانون Little، برای سه تأخیر نمونه. تأخیرها فرضی‌اند و فرمول از کد است](figures/ch14/f08_budget.png){#fig-14-f08_budget}

## زنده‌بودن watch {#sec-14-9-3}

::: {.algo #alg-14-3 title="ping ‏linger و انقضای watch در OSD" src="src/osdc/Objecter.cc :: Objecter::tick، _send_linger_ping؛ src/osd/PrimaryLogPG.cc (CEPH_OSD_WATCH_OP_WATCH)؛ src/osd/Watch.cc" complexity="O(sessionها + linger opها) در هر tick"}
:::

```text
pseudocode
Objecter::tick هر objecter_tick_interval (5 s):
    opهای قدیمی‌تر از objecter_timeout (10 s) ← session «laggy» ← MPing و درخواست osdmap تازه
    برای هر watch ثبت‌شده و بی‌خطا: _send_linger_ping
OSD: watch_info_t(cookie, timeout = op.watch.timeout یا osd_client_watch_timeout (30 s))
    هر ping تایمر را تازه می‌کند ؛ اگر timeout بگذرد: watch حذف می‌شود
کلاینت پس از وصل شدن دوباره: watch_check یا callback خطا ← ENOTCONN ← watch دوباره و خواندن دوباره‌ی وضعیت
```

**مثال عددی.** آخرین ping موفق در ثانیه‌ی 10 به OSD می‌رسد و از ثانیه‌ی 12 شبکه قطع می‌شود. حدود ثانیه‌ی 40، یعنی 30 ثانیه پس از آخرین ping، OSD watch را حذف می‌کند. هر notify که در این فاصله به آن شیء فرستاده شود به این کلاینت نمی‌رسد و در فهرست timeout یا missed ‏notify ثبت می‌شود. برنامه‌ی درست (مانند exclusive-lock در RBD) پس از خطای watch، وضعیت را دوباره از خود شیء می‌خواند و به notifyهای گذشته اعتماد نمی‌کند.

![زمان‌بندی زنده‌بودن watch. pingها هر 5 ثانیه فرستاده می‌شوند. پس از قطع شبکه در ثانیه‌ی 12، دیگر هیچ pingی نمی‌رسد. OSD حدود ثانیه‌ی 40 watch را حذف می‌کند (30 ثانیه پس از آخرین ping). Objecter زودتر، پس از 10 ثانیه، session را laggy می‌داند و نقشه‌ی تازه درخواست می‌کند](figures/ch14/f09_watch.png){#fig-14-f09_watch}

![کار هر tick در Objecter: شمردن opهای laggy، ping برای watchهای ثبت‌شده، و در صورت وجود op بی‌خانمان یا session مشکوک، درخواست osdmap تازه از MON و فرستادن MPing. پاسخ OSD سیاست lossy دارد، پس ping لازم است تا ریست شدن session کشف شود](figures/ch14/f11_tick.png){#fig-14-f11_tick}

## timeout ‏notify: گرد شدن به ثانیه {#sec-14-9-4}

::: {.algo #alg-14-4 title="تعیین timeout مؤثر notify" src="src/librados/IoCtxImpl.cc :: IoCtxImpl::notify، aio_notify؛ src/osd/PrimaryLogPG.cc (CEPH_OSD_OP_NOTIFY)" complexity="O(1)"}
:::

```text
pseudocode
timeout = notify_timeout                         # client_notify_timeout، پیش‌فرض 10 s
if timeout_ms: timeout = timeout_ms / 1000       # تقسیم صحیح
روی سیم: timeout (ثانیه)
OSD: if timeout == 0: timeout = osd_default_notify_timeout   # 30 s
```

**مثال عددی.** timeout_ms برابر 0 یعنی 10 ثانیه. 1500 میلی‌ثانیه به 1 ثانیه تبدیل می‌شود. اما 500 میلی‌ثانیه به 0 تبدیل می‌شود و OSD آن را «پیش‌فرض» تعبیر می‌کند، پس notify تا **30 ثانیه** منتظر ack می‌ماند، یعنی 60 برابر چیزی که برنامه‌نویس خواسته بود. برای timeoutهای کمتر از یک ثانیه، از timeout خود notify استفاده نکنید و در برنامه تایمر جداگانه بگذارید.

![timeout مؤثر notify برحسب timeout_ms ورودی. صفر به client_notify_timeout (10 ثانیه) می‌رسد. 1 تا 999 میلی‌ثانیه پس از تقسیم صحیح صفر می‌شود و OSD پیش‌فرض 30 ثانیه را به کار می‌برد. از 1000 به بعد، ثانیه‌های کامل اعمال می‌شوند](figures/ch14/f10_notify.png){#fig-14-f10_notify}

# از درون کد: Objecter {#sec-14-10}

## نقش Objecter {#sec-14-10-1}

Objecter (`src/osdc/Objecter.cc`) قلب سمت کلاینت librados است: هر عملیات را به یک `Op` تبدیل می‌کند، هدفش (PG و OSD primary) را محاسبه و ارسال می‌کند، پاسخ را به درخواست‌کننده برمی‌گرداند و مهم‌تر از همه، **با هر تغییر نقشه، درخواست‌های در جریان را بازبینی و در صورت نیاز دوباره ارسال می‌کند**. librbd، RGW و ceph-fuse همه از همین کلاس استفاده می‌کنند.

| تابع در Objecter.cc | کار |
|---|---|
| _op_submit() | ثبت Op، محاسبه‌ی هدف، اعمال throttle و ارسال |
| _calc_target() | محاسبه‌ی PG و acting primary بر اساس نقشه‌ی فعلی |
| _send_op() | ساخت پیام MOSDOp و ارسال روی اتصال OSD |
| handle_osd_map() | دریافت نقشه‌ی جدید و بازبینی همه‌ی Opها و lingerها |
| _recalc_linger_op_target() | محاسبه‌ی دوباره‌ی هدف برای watchها |

## محاسبه‌ی هدف {#sec-14-10-2}

![گام‌های _calc_target: وجود pool، نگاشت شیء به PG، محاسبه‌ی up/acting با CRUSH و pg_temp و upmap، و تصمیم به ارسال دوباره در صورت تغییر interval](figures/ch14/f02_calc.png){#fig-14-f02_calc}

خلاصه‌ی منطق `Objecter::_calc_target()`:

1. epoch نقشه‌ی فعلی در هدف ثبت می‌شود.
2. `osdmap->get_pg_pool()`: اگر pool وجود ندارد، نتیجه `RECALC_OP_TARGET_POOL_DNE` است و Op منتظر نقشه‌ی جدیدتر می‌ماند (شاید pool تازه ساخته شده و کلاینت هنوز نقشه‌اش را ندارد).
3. اگر pool خراب یا با پرچم EIO است، `RECALC_OP_TARGET_POOL_EIO`.
4. `osdmap->object_locator_to_pg()`: hash نام شیء (یا locator key) و نگاشت به PG.
5. محاسبه‌ی up و acting و primary (CRUSH، pg_temp، upmap؛ فصل ۸).
6. مقایسه با هدف قبلی: اگر primary، acting، اندازه‌ی pool یا تقسیم PG تغییر کرده باشد (**interval جدید**)، Op باید دوباره ارسال شود.

```text
on new osdmap (handle_osd_map):
  for op in inflight_ops:
     r = calc_target(op.target)
     if r == NEED_RESEND: cancel on old session; send to new primary
     if r == POOL_DNE and map is new enough: fail op with -ENOENT
  for linger in watches: recalc_linger_op_target(linger)   # watch دوباره ثبت می‌شود
```

::: {.deep}
چرا ارسال دوباره ایمن است؟ هر Op یک شناسه‌ی یکتا (`reqid`: شناسه‌ی کلاینت و tid) دارد. OSD در log هر PG شناسه‌ی درخواست‌های اخیر را نگه می‌دارد؛ اگر نوشتنی که قبلاً اعمال شده دوباره برسد (مثلاً چون ack در راه گم شده)، OSD آن را تکراری تشخیص می‌دهد و همان نتیجه را بدون اجرای دوباره برمی‌گرداند. این **idempotency** است که بازارسال پس از تغییر نقشه را بی‌خطر می‌کند.
:::

## throttle و پیکربندی کلاینت {#sec-14-10-3}

```bash
ceph config get client objecter_inflight_ops
ceph config get client objecter_inflight_op_bytes
ceph config set client.devapp rados_osd_op_timeout 30      # بدون این، Op ممکن است بی‌نهایت منتظر بماند
```

::: {.note}
پیش‌فرض‌های کد جاری: `objecter_inflight_ops=1_K`، `objecter_inflight_op_bytes=100_M`، `rados_osd_op_timeout=0` (یعنی بدون timeout) و `osd_max_object_size=128_M`.
:::

::: {.warn}
پیش‌فرض librados این است که Op را **تا ابد** منتظر نگه دارد تا PG دوباره active شود؛ این برای ذخیره‌سازی درست است (داده از دست نمی‌رود) اما برنامه‌ی شما ممکن است بی‌پاسخ بماند. اگر برنامه باید سریع خطا بدهد (مثلاً یک API با SLA)، `rados_osd_op_timeout` و `rados_mon_op_timeout` را تنظیم کنید و خطای `-ETIMEDOUT` را مدیریت کنید.
:::

# دام‌ها و الگوهای طراحی {#sec-14-11}

| دام | پیامد | راه درست |
|---|---|---|
| شیء خیلی بزرگ (گیگابایت‌ها) | بازیابی و scrub کند؛ محدودیت `osd_max_object_size` | شکستن به اشیای چندمگابایتی (مانند striper یا RBD) |
| omap خیلی بزرگ در یک شیء | `LARGE_OMAP_OBJECTS`، تأخیر deep-scrub | shard کردن شاخص روی چند شیء (مانند bucket index در RGW) |
| یک شیء «داغ» | همه‌ی بار روی یک PG و یک OSD | توزیع کلیدها روی چند شیء |
| فهرست‌گیری مکرر pool | پیمایش همه‌ی PGها؛ بسیار کند | نگه داشتن شاخص خودتان در omap |
| فرض تراکنش چندشیئی | ناسازگاری پس از خرابی میانه‌ی کار | طراحی idempotent یا journal در یک شیء |

::: {.tip}
اندازه‌ی بیشینه‌ی شیء با `osd_max_object_size` محدود است. برای داده‌ی بزرگ از **libradosstriper** یا الگوی خودتان برای شکستن به اشیای ۴ مگابایتی استفاده کنید؛ RBD و CephFS دقیقاً همین کار را می‌کنند.
:::

::: {.summary title="نکات SRE این فصل"}

- برای هر برنامه کاربر cephx جدا با دسترسی به pool یا namespace خودش.
- عملیات مرکب فقط روی یک شیء اتمی است.
- برای هم‌زمانی از assert_version، cmpxattr یا قفل همراه blocklist استفاده کنید.
- watch/notify برای اعلان است، نه انتقال قابل اتکای داده.
- timeout کلاینت را برای برنامه‌های تعاملی تنظیم کنید.
- اشیا و omapها را کوچک و توزیع‌شده نگه دارید.

:::

# تکمیلی و به‌روز {#sec-14-12}

- **watch2/notify2** (C++) و `watch3` (C) نسخه‌های جدیدتر با مدیریت خطای بهتر هستند؛ نسخه‌های قدیمی watch در API باقی مانده‌اند.
- در `librados.hpp` کد جاری، شکل نوع‌دار `exec(const ClsMethod<...>&, ...)` برای فراخوانی متدهای کلاس دیده می‌شود (علاوه بر شکل رشته‌ای قدیمی).
- binding پایتون از `aio_*`، WriteOp/ReadOp، omap، watch و قفل پشتیبانی می‌کند.
- **msgr2** با حالت secure ترافیک librados را رمزنگاری می‌کند (فصل ۸).

# تمرین عملی {#sec-14-13}

1. برنامه‌ی پایتونی این فصل را اجرا کنید و با `rados -p devpool --namespace tenant-a ls` اشیا را ببینید.
2. شمارنده‌ی اتمی را با ده فرایند هم‌زمان اجرا کنید و تأیید کنید مقدار نهایی درست است. سپس guard را حذف کنید و نتیجه را مقایسه کنید.
3. یک watcher و یک notifier بنویسید؛ watcher را قطع و وصل کنید و ببینید چه زمانی پیام از دست می‌رود.
4. با `rados_osd_op_timeout` رفتار برنامه را هنگام توقف OSDهای یک PG آزمایش کنید.
5. ده هزار کلید omap در یک شیء بنویسید و زمان `rados listomapkeys` را اندازه بگیرید؛ سپس روی ده شیء shard کنید.
6. در کد Objecter، جایی که `RECALC_OP_TARGET_POOL_DNE` مدیریت می‌شود را پیدا کنید و رفتار را توضیح دهید.

# پرسش‌های مرور {#sec-14-14}

1. سه بخش مستقل یک شیء RADOS کدام‌اند؟
2. namespace چه فرقی با pool دارد و چه زمانی مفید است؟
3. چرا omap در pool EC پشتیبانی نمی‌شود و چه پیامدی برای طراحی دارد؟
4. عملیات مرکب چه تضمینی می‌دهد و چه تضمینی نمی‌دهد؟
5. assert_version در چه حالت‌هایی ERANGE و EOVERFLOW برمی‌گرداند؟
6. چرا قفل مشورتی به تنهایی برای ایمنی کافی نیست؟
7. watch در Objecter چگونه پس از تغییر نقشه حفظ می‌شود؟
8. چرا بازارسال Op پس از تغییر نقشه ایمن است؟
9. چه زمانی باید rados_osd_op_timeout را تنظیم کرد؟
10. برای ذخیره‌ی داده‌ی چندگیگابایتی روی RADOS چه الگویی مناسب است؟

# منابع این فصل {#sec-14-15}

- librados introduction: https://docs.ceph.com/en/latest/rados/api/librados-intro/
- librados C API: https://docs.ceph.com/en/latest/rados/api/librados/
- librados C++ API: https://docs.ceph.com/en/latest/rados/api/libradospp/
- librados Python API: https://docs.ceph.com/en/latest/rados/api/python/
- Objclass and RADOS classes: https://docs.ceph.com/en/latest/rados/api/objclass-sdk/
- Source: src/include/rados/librados.h, librados.hpp: https://github.com/ceph/ceph/tree/main/src/include/rados
- Source: src/osdc/Objecter.cc: https://github.com/ceph/ceph/blob/main/src/osdc/Objecter.cc
- Source: src/pybind/rados/rados.pyx: https://github.com/ceph/ceph/blob/main/src/pybind/rados/rados.pyx
- Source: src/osd/PrimaryLogPG.cc: https://github.com/ceph/ceph/blob/main/src/osd/PrimaryLogPG.cc
- Weil et al., "RADOS: A Scalable, Reliable Storage Service for Petabyte-scale Storage Clusters" (PDSW 2007): https://ceph.io/assets/pdfs/weil-rados-pdsw07.pdf
