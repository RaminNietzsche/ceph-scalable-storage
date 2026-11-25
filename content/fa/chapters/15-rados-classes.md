---
chapter: 15
id: ch15
title: "کلاس‌های RADOS: محاسبه در کنار داده"
part: main
lang: fa
---

::: {.tldr}

- کلاس‌های RADOS متدهای شما را درون OSD و کنار شیء اجرا می‌کنند؛ رفت‌وبرگشت شبکه کم و خطر رقابت حذف می‌شود.
- کلاینت آن‌ها را با `exec` صدا می‌زند و capability مربوط به OSD باید `x` داشته باشد.
- می‌توانید کلاس خودتان را با C++ بنویسید (فصل کلاس `tally` را می‌سازد) یا اسکریپت Lua را با cls_lua اجرا کنید.
- پرچم‌های متد (RD و WR) باید با کار واقعی متد بخوانند؛ درستی و هزینه را روی کلاستر واقعی بسنجید.

```bash
ceph config get osd osd_class_dir
```

[![مقایسه‌ی دو روش افزایش شمارنده: در روش کلاس numops.add، OSD درخواست‌ها را به‌صورت سریال درون PG اجرا می‌کند](figures/ch15/f03_rmw.png)](#fig-15-f03_rmw)

:::

# پیش از شروع {#sec-15-1}

## این فصل به چه سؤال‌هایی جواب می‌دهد؟ {#sec-15-1-1}

در معماری‌های معمول، داده از ذخیره‌ساز به سرور برنامه منتقل می‌شود، آنجا پردازش می‌شود و نتیجه برمی‌گردد. Ceph راه دیگری هم دارد: **کلاس‌های شیء** (Object Classes یا cls) که کتابخانه‌های مشترکی هستند و درون خود OSD، کنار داده، اجرا می‌شوند. librbd، RGW و CephFS همه بر این سازوکار تکیه دارند. در این فصل یاد می‌گیریم:

- کلاس RADOS چیست و چرا محاسبه در کنار داده سودمند است؟
- OSD یک متد کلاس را چگونه بارگذاری، اجرا و کنترل می‌کند؟
- چگونه کلاس خودمان را بنویسیم، بسازیم و مستقر کنیم؟
- چه کلاس‌هایی در Ceph وجود دارد و کدام برای ما مفیدند؟
- cls_lua چیست و چرا به‌صورت پیش‌فرض بارگذاری نمی‌شود؟
- مرزهای امنیتی و عملیاتی این قدرت کجاست؟

# مفهوم: محاسبه در کنار داده {#sec-15-2}

## چرا کلاس؟ {#sec-15-2-1}

فرض کنید شمارنده‌ای در omap یک شیء دارید که چندین کلاینت هم‌زمان آن را افزایش می‌دهند. بدون کلاس، هر کلاینت باید مقدار را بخواند، یکی اضافه کند و بنویسد؛ دو رفت‌وبرگشت شبکه و خطر رقابت که باید با assert_version (فصل ۱۴) مدیریت شود. با کلاس، کلاینت فقط می‌گوید «به کلید X یک واحد اضافه کن» و OSD عملیات خواندن-تغییر-نوشتن را **زیر قفل PG و درون یک تراکنش** انجام می‌دهد.

![مقایسه‌ی دو روش افزایش شمارنده: در روش سمت کلاینت، دو کلاینت مقدار ۱۰ را می‌خوانند و هر دو ۱۱ می‌نویسند و یک به‌روزرسانی گم می‌شود؛ در روش کلاس numops.add، OSD درخواست‌ها را به‌صورت سریال درون PG اجرا می‌کند و مقدار نهایی ۱۳ است](figures/ch15/f03_rmw.png){#fig-15-f03_rmw}

مزایای کلاس‌ها:

- **کاهش رفت‌وبرگشت**: یک درخواست به جای چند درخواست.
- **اتمی بودن**: همه‌ی تغییرات متد در تراکنش همان شیء ثبت و به replicaها تکثیر می‌شود.
- **کاهش انتقال داده**: فیلتر یا خلاصه‌سازی کنار داده انجام می‌شود و فقط نتیجه برمی‌گردد.
- **منطق سازگار**: قواعد ساختار داده (مثل سرآیند تصویر RBD) در یک جا پیاده می‌شود و همه‌ی کلاینت‌ها از آن پیروی می‌کنند.

::: {.warn}
متد کلاس فقط به **همان یک شیء** دسترسی دارد. نمی‌توان از درون متد شیء دیگری را خواند یا نوشت (چون آن شیء ممکن است در PG و OSD دیگری باشد). هر منطق چندشیئی باید سمت کلاینت هماهنگ شود.
:::

## کلاس‌های موجود {#sec-15-2-2}

![نقشه‌ی مصرف‌کنندگان کلاس‌های داخلی: librbd برای سرآیند تصویر و object map به cls_rbd، RGW برای شاخص bucket به cls_rgw و برای GC و صف به cls_rgw_gc و cls_2pc_queue و cls_fifo تکیه دارد؛ cls_lock و cls_version و cls_refcount عمومی‌اند](figures/ch15/f04_users.png){#fig-15-f04_users}

| کلاس | کاربرد |
|---|---|
| cls_rbd | سرآیند و فراداده‌ی تصویرهای RBD، snapshotها، object map |
| cls_rgw | شاخص bucket و log شاخص (bilog) |
| cls_rgw_gc، cls_2pc_queue، cls_fifo، cls_queue | جمع‌آوری زباله، صف اعلان‌ها و logهای FIFO در RGW |
| cls_lock | قفل مشترک و انحصاری مشورتی روی اشیا |
| cls_version، cls_refcount | نسخه‌گذاری و شمارش ارجاع |
| cls_log، cls_timeindex | logهای زمان‌دار در omap |
| cls_numops | عملیات عددی add و mul روی مقادیر omap |
| cls_hello | کلاس نمونه برای آموزش و آزمون |
| cls_lua | اجرای اسکریپت Lua درون OSD |

::: {.note}
در کد جاری، مقدار پیش‌فرض `osd_class_load_list` و `osd_class_default_list` هر دو برابر «cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex» است. پس **lua** به‌صورت پیش‌فرض بارگذاری نمی‌شود و باید صریحاً به فهرست اضافه شود.
:::

# فراخوانی کلاس از کلاینت {#sec-15-3}

## پایتون {#sec-15-3-1}

```python
import rados, json
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c:
    with c.open_ioctx('devpool') as io:
        io.write_full('stats', b'')
        # cls_numops ورودی را به‌صورت دو رشته‌ی encode‌شده‌ی Ceph می‌خواهد؛
        # ساده‌ترین راه آزمایش در پایتون، کلاس hello است:
        ret, out = io.execute('greeting', 'hello', 'say_hello', b'Ramin')
        print(ret, out)          # خروجی: b'Hello, Ramin!' (ورودی بیش از ۱۰۰ بایت: -EINVAL)
```

امضای `Ioctx.execute(key, cls, method, data, length=8192)` در binding پایتون یک تاپل (کد برگشتی، خروجی) برمی‌گرداند. `length` سقف اندازه‌ی خروجی است.

## C++ و عملیات مرکب {#sec-15-3-2}

```cpp
librados::ObjectWriteOperation op;
op.create(false);
bufferlist in;
encode(std::string("hits"), in);   // کلید
encode(std::string("1"), in);      // مقدار افزایش
op.exec("numops", "add", in);      // فراخوانی کلاس درون عملیات مرکب
int r = io.operate("stats", &op);
```

این نمونه‌ی خودمان است و الگوی ورودی همان است که `cls_numops.cc` انتظار دارد: دو رشته‌ی encode‌شده (کلید و مقدار). کتابخانه‌ی کمکی `cls_numops_client.h` هم تابع‌های `add` و `mul` را مستقیماً فراهم می‌کند.

::: {.tip}
متد کلاس را می‌توان با عملیات دیگر در یک `ObjectWriteOperation` ترکیب کرد؛ مثلاً `assert_exists` + `exec` + `setxattr` که همگی اتمی اجرا می‌شوند.
:::

## دسترسی cephx {#sec-15-3-3}

اجرای متد کلاس به cap مناسب نیاز دارد. `allow rwx` همه‌ی کلاس‌ها را مجاز می‌کند؛ برای محدودسازی:

```bash
ceph auth caps client.devapp mon 'allow r' \
  osd 'allow rw class-read class-write pool=devpool'
ceph auth caps client.counter mon 'allow r' \
  osd 'allow rw pool=devpool, allow class numops add pool=devpool'
```

::: {.note}
`class-read` و `class-write` اجازه‌ی متدهایی را می‌دهند که پرچم RD یا WR دارند، اما فقط برای کلاس‌های «allowed» (یعنی موجود در `osd_class_default_list`). کلاس خارج از این فهرست cap صریح `class <name> [<method>]` لازم دارد (طبق دستور زبان capspec در `src/osd/OSDCap.cc`: `class <name> [<method name>]`؛ در نمونه‌ی دوم فقط متد add از numops مجاز است).
:::

# نوشتن کلاس خودمان {#sec-15-4}

## طراحی: cls_tally {#sec-15-4-1}

برای تمرین، کلاسی به نام **tally** می‌سازیم که دو متد دارد: `bump` (افزایش اتمی یک شمارنده در omap و برگرداندن مقدار جدید) و `top` (خواندن شمارنده‌ها و برگرداندن بیشترین n مورد، تا لازم نباشد همه‌ی کلیدها به کلاینت منتقل شوند). این کد را خودمان نوشته‌ایم و فقط از رابط عمومی `objclass.h` استفاده می‌کند.

```cpp
// cls_tally.cc — نمونه‌ی آموزشی این کتاب (نه بخشی از Ceph)
#include "objclass/objclass.h"
#include <string>
#include <map>
#include <vector>
#include <algorithm>

CLS_VER(1, 0)
CLS_NAME(tally)

// ورودی: نام کلید؛ خروجی: مقدار جدید به صورت رشته
static int bump(cls_method_context_t hctx, ceph::bufferlist *in, ceph::bufferlist *out)
{
  std::string key(in->c_str(), in->length());
  if (key.empty() || key.size() > 256)
    return -EINVAL;
  ceph::bufferlist cur;
  uint64_t v = 0;
  int r = cls_cxx_map_get_val(hctx, key, &cur);
  if (r == 0)
    v = std::stoull(std::string(cur.c_str(), cur.length()));
  else if (r != -ENOENT && r != -ENODATA)
    return r;
  ++v;
  ceph::bufferlist nv;
  nv.append(std::to_string(v));
  r = cls_cxx_map_set_val(hctx, key, &nv);
  if (r < 0)
    return r;
  out->append(std::to_string(v));
  return 0;
}

// ورودی: n؛ خروجی: n کلید پرتکرار به صورت "key=value\n"
static int top(cls_method_context_t hctx, ceph::bufferlist *in, ceph::bufferlist *out)
{
  int n = in->length() ? std::stoi(std::string(in->c_str(), in->length())) : 10;
  std::vector<std::pair<uint64_t, std::string>> all;
  std::string start;
  bool more = true;
  while (more) {
    std::map<std::string, ceph::bufferlist> vals;
    int r = cls_cxx_map_get_vals(hctx, start, "", 1000, &vals, &more);
    if (r < 0)
      return r;
    for (auto& [k, bl] : vals) {
      all.emplace_back(std::stoull(std::string(bl.c_str(), bl.length())), k);
      start = k;
    }
    if (vals.empty()) break;
  }
  std::partial_sort(all.begin(), all.begin() + std::min<size_t>(n, all.size()),
                    all.end(), std::greater<>());
  for (int i = 0; i < n && i < (int)all.size(); ++i)
    out->append(all[i].second + "=" + std::to_string(all[i].first) + "\n");
  return 0;
}

CLS_INIT(tally)
{
  cls_handle_t h_class;
  cls_method_handle_t h_bump, h_top;
  cls_register("tally", &h_class);
  cls_register_cxx_method(h_class, "bump", CLS_METHOD_RD | CLS_METHOD_WR, bump, &h_bump);
  cls_register_cxx_method(h_class, "top",  CLS_METHOD_RD, top, &h_top);
}
```

::: {.warn}
`std::stoull` روی داده‌ی خراب استثنا پرتاب می‌کند. استثنای مدیریت‌نشده در متد کلاس **فرایند OSD را از کار می‌اندازد**. در کد تولیدی، همه‌ی تبدیل‌ها را در try/catch بگذارید و `-EBADMSG` برگردانید. این دقیقاً دلیل احتیاط Ceph در بارگذاری کلاس‌هاست: کلاس با همان امتیازات OSD اجرا می‌شود.
:::

::: {.note}
**وابسته به نسخه.** شکل ثبت بالا (`cls_register_cxx_method` با پرچم صریح) رابط Tentacle (20.2.x) و نسخه‌های پیش از آن است؛ این تابع در `src/include/rados/objclass.h` برچسب v20.2.0 وجود دارد. در Umbrella (21.2.0) و شاخه‌ی main، این تابع به `detail::cls_register_cxx_method_impl` منتقل شده و ثبت از راه قالب نوع‌دار `ClassRegistrar<ClassDef>` انجام می‌شود؛ پرچم‌های RD/WR/PROMOTE در نوع متد (`RdTag`، `RdWrTag` و...، تعریف‌شده در `src/include/rados/cls_traits.hpp`) رمزگذاری می‌شوند تا کلاینت و سرور نتوانند درباره‌ی پرچم‌ها ناسازگار باشند. نسخه‌ی Umbrella همان کلاس ما:
:::

```cpp
// cls_tally_ops.h — نمونه‌ی آموزشی این کتاب، سبک Umbrella
#include "include/rados/cls_traits.hpp"
namespace cls::tally {
struct ClassId { static constexpr auto name = "tally"; };
namespace method {
constexpr auto bump = ClsMethod<RdWrTag, ClassId>("bump");
constexpr auto top  = ClsMethod<RdTag,   ClassId>("top");
}}
// cls_tally.cc (بخش ثبت)
CLS_INIT(tally)
{
  using namespace cls::tally;
  cls_handle_t h_class;
  cls_method_handle_t h_bump, h_top;
  cls_register(ClassId::name, &h_class);
  ClassRegistrar<ClassId> cls(h_class);
  cls.register_cxx_method(method::bump, bump, &h_bump);
  cls.register_cxx_method(method::top,  top,  &h_top);
}
```

## ساخت و استقرار {#sec-15-4-2}

دو راه برای ساخت هست: درون درخت منبع Ceph (افزودن پوشه به `src/cls` و `CMakeLists.txt`) یا با **SDK کلاس‌های شیء** که مستندات رسمی آن را برای ساخت خارج از درخت معرفی می‌کند (نمونه‌ی مرجع: `src/cls/sdk/cls_sdk.cc`).

```bash
# روی ماشین ساخت با سرآیندهای توسعه‌ی Ceph هم‌نسخه با کلاستر
g++ -std=c++17 -fPIC -shared -O2 -o libcls_tally.so cls_tally.cc \
    $(pkg-config --cflags librados) -lrados
# مسیر کلاس‌ها روی OSD
ceph config get osd osd_class_dir
```

::: {.warn}
کلاس باید با **همان نسخه‌ی Ceph و همان کامپایلر/ABI** ساخته شود که روی OSDها اجرا می‌شود. در استقرار cephadm، OSD درون کانتینر اجرا می‌شود و `osd_class_dir` به مسیری درون image اشاره دارد؛ کپی فایل روی میزبان کافی نیست. راه پایدار ساختن یک **image سفارشی** بر پایه‌ی image رسمی هم‌نسخه و افزودن `libcls_tally.so` به همان پوشه، سپس `ceph orch upgrade start --image <image>` یا تنظیم `container_image` است.
:::

```bash
ceph config set osd osd_class_load_list "cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex tally"
ceph config set osd osd_class_default_list "cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex tally"
ceph orch restart osd.<service>     # بارگذاری کلاس در نخستین فراخوانی پس از راه‌اندازی
```

::: {.tip}
هنگام تغییر این دو فهرست، **مقادیر پیش‌فرض را حفظ کنید**. اگر فقط `tally` بنویسید، OSD دیگر cls_rbd یا cls_rgw را بارگذاری نمی‌کند و RBD و RGW از کار می‌افتند. پیش از تغییر، مقدار فعلی را با `ceph config get osd osd_class_load_list` بخوانید.
:::

## فراخوانی و آزمون {#sec-15-4-3}

```python
with rados.Rados(conffile='/etc/ceph/ceph.conf', name='client.devapp') as c:
    with c.open_ioctx('devpool') as io:
        for w in ['ceph', 'rados', 'ceph', 'osd', 'ceph']:
            ret, out = io.execute('words', 'tally', 'bump', w.encode())
        ret, out = io.execute('words', 'tally', 'top', b'2')
        print(out.decode())       # ceph=3 و پس از آن یکی از دیگران
```

::: {.debug}
اگر فراخوانی `-EOPNOTSUPP` (Operation not supported) برگرداند، یا کلاس بارگذاری نشده یا متد وجود ندارد؛ در log OSD primary پیام «not permitted to load» یا «does not exist» را جست‌وجو کنید. `-EPERM` معمولاً مشکل cap است.
:::

# cls_lua: اسکریپت درون OSD {#sec-15-5}

کلاس `lua` یک مفسر Lua درون OSD اجرا می‌کند. کلاینت متد `eval_json` (یا `eval_bufferlist`) را با یک ورودی شامل `script`، `handler` و `input` (اختیاری) صدا می‌زند. اسکریپت ابتدا اجرا می‌شود و تابع handler باید با `cls.register` ثبت شده باشد؛ سپس OSD آن را با دو آرگومان input و output (هر دو bufferlist) فراخوانی می‌کند. توابعی مثل `read`، `write_full`، `map_get_val`، `map_set_val`، `setxattr`، `stat` و `log` در دسترس‌اند (جدول `clslua_lib` در `src/cls/lua/cls_lua.cc`). این توابع در جدول سراسری **`objclass`** قرار دارند، نه `cls`: تابع `clslua_setup_env` آن‌ها را با `luaL_requiref(L, "objclass", luaopen_objclass, 1)` ثبت می‌کند. برای همین در اسکریپت باید `objclass.read(…)` و `objclass.register(…)` نوشت. ما این را روی Ceph 18.2.7 آزمودیم. با `cls.register` خطای `attempt to index a nil value (global 'cls')` گرفتیم، و همین نمونه با `objclass` درست کار کرد.

```lua
-- نمونه‌ی خودمان: شمارش خطوط شیء کنار داده
function count_lines(input, output)
  local size = objclass.stat()
  local data = objclass.read(0, size)
  local s = data:str()
  local _, n = s:gsub("\n", "")
  output:append(tostring(n))
end
objclass.register(count_lines)
```

::: {.warn}
cls_lua در فهرست پیش‌فرض کلاس‌ها **نیست**. فعال کردن آن یعنی هر کلاینت دارای cap مناسب می‌تواند کد دلخواه درون OSD اجرا کند؛ یک حلقه‌ی بی‌پایان یا خواندن شیء چندصدمگابایتی، thread OSD و PG را مسدود می‌کند و slow ops می‌سازد. فقط در محیط کنترل‌شده و با cap محدود (`allow class lua eval_json pool=...`) فعال کنید.
:::

# سه الگوریتم از مسیر کلاس‌ها {#sec-15-6}

## اعتبارسنجی یک فراخوانی CALL {#sec-15-6-1}

::: {.algo #alg-15-1 title="بررسی پرچم RD/WR پیش و پس از اجرای متد کلاس" src="src/osd/osd_op_util.cc :: OpInfo::set_from_op (شاخه‌ی CEPH_OSD_OP_CALL)؛ src/osd/ClassHandler.cc :: ClassHandler::open_class، _get_class، in_class_list؛ src/osd/PrimaryLogPG.cc :: PrimaryLogPG::do_osd_ops" complexity="O(طول فهرست کلاس‌ها) فقط در نخستین بارگذاری؛ سپس O(log M) برای یافتن متد در map"}
:::

```text
pseudocode
set_from_op:
    cls = open_class(cname)            # در load_list نیست ⇒ EPERM ، فایل نیست ⇒ EOPNOTSUPP
    flags = cls.get_method_flags(mname)   # نیست ⇒ EOPNOTSUPP
    RD ⇒ CLASS_READ (+ CLASS_READ_DATA در EC) ؛ WR ⇒ CLASS_WRITE ؛ PROMOTE ⇒ promote
    add_class(cname, mname, rd, wr, cls.allowed)  # برای OSDCap::is_capable
do_osd_ops:
    if WR: user_modify = true
    r0, w0 = num_read, num_write ; r = exec(ctx, in, out)
    if num_read > r0 and !RD: EIO ; if num_write > w0 and !WR: EIO
```

**مثال عددی.** کلاسی به نام `tally` (کلاس نمونه‌ی این فصل) متد `inc` را با پرچم فقط `CLS_METHOD_WR` ثبت کرده است، اما درون متد `cls_cxx_map_get_val` را صدا می‌زند تا مقدار قبلی را بخواند.

1. **پیش از اجرا:** op به‌عنوان فقط-نوشتن برچسب می‌خورد و cap `allow class-write` کافی است.
2. **حین اجرا:** هر فراخوانی خواندن درون کلاس num_read را از 0 به 1 می‌برد.
3. **پس از exec:** بررسی num_read > r0 بدون RD برقرار است و OSD خطای EIO برمی‌گرداند. در لاگ هم پیام «tried to read object but is not marked RD» دیده می‌شود.

راه‌حل ثبت متد با `CLS_METHOD_RD | CLS_METHOD_WR` است. در آن صورت cap کاربر هم باید `class-read` داشته باشد. اگر `tally` در `osd_class_load_list` نباشد، پیش از همه‌ی این مراحل خطای EPERM برمی‌گردد. فهرست پیش‌فرض در v20.2.0 و main، 20 کلاس داخلی را شامل می‌شود: cephfs، hello، journal، lock، log، numops، otp، rbd، refcount، rgw، rgw_gc، timeindex، user، version، cas، cmpomap، queue، 2pc_queue، fifo و sem_set. lua و sdk در این فهرست نیستند.

![سه مرحله‌ی اعتبارسنجی یک CALL. ردیف اول هنگام رسیدن پیام اجرا می‌شود و کلاس و متد را می‌یابد. ردیف دوم پرچم‌های ثبت‌شده‌ی متد را به پرچم‌های op تبدیل می‌کند تا OSDCap بتواند مجوز را بسنجد و PG بداند op خواندنی است یا نوشتنی. ردیف سوم پس از اجرای متد شمارنده‌های خواندن و نوشتن را مقایسه می‌کند. متدی که برخلاف پرچمش رفتار کند، با EIO رد می‌شود](figures/ch15/f05_callcheck.png){#fig-15-f05_callcheck}

## قفل مشورتی cls_lock {#sec-15-6-2}

::: {.algo #alg-15-2 title="گرفتن، تمدید و انقضای قفل در cls_lock" src="src/cls/lock/cls_lock.cc :: lock_obj، read_lock؛ src/cls/lock/cls_lock_types.h :: LOCK_FLAG_MAY_RENEW، LOCK_FLAG_MUST_RENEW" complexity="O(L log L) برای L دارنده‌ی قفل (decode و پیمایش map)؛ یک xattr برای هر نام قفل"}
:::

```text
pseudocode
linfo = decode(xattr "lock." + name) ; حذف دارندگانی که expiration < now   # انقضای تنبل
if MAY_RENEW و MUST_RENEW هر دو: EINVAL
if lockers ≠ ∅ and tag ≠ linfo.tag: EBUSY
id = (entity_name مبدأ، cookie)
if id ∈ lockers: اگر MAY_RENEW نیست ⇒ EEXIST ، وگرنه حذف ورودی قدیمی
elif MUST_RENEW: ENOENT
if lockers ≠ ∅: exclusive ⇒ EBUSY ؛ نوع متفاوت ⇒ EBUSY
lockers[id] = (now + duration یا 0 = بی‌انقضا، addr، description) ; write xattr
```

**مثال عددی.** قفلی انحصاری با duration = 30 s:

- **t = 0:** کلاینت A با cookie c1 قفل را می‌گیرد (انقضا 30).
- **t = 10:** B تلاش می‌کند و EBUSY می‌گیرد.
- **t = 20:** A بدون پرچم دوباره تلاش می‌کند و EEXIST می‌گیرد.
- **t = 25:** A با MAY_RENEW تمدید می‌کند (انقضا 55).
- **t = 60:** B دوباره تلاش می‌کند. read_lock ورودی A را حذف می‌کند، چون 55 < 60، و B قفل را می‌گیرد (انقضا 90).
- **t = 70:** A با MUST_RENEW تمدید می‌خواهد و ENOENT می‌گیرد، چون دیگر دارنده نیست.

انقضا فقط هنگام دسترسی بعدی اعمال می‌شود. یعنی هیچ تایمری در OSD نیست. ساعت مقایسه هم ساعت OSD primary است، نه ساعت کلاینت. هر کسی می‌تواند با `rados lock break` یا `rbd lock remove` قفل دیگری را بشکند. قفل cls_lock مشورتی است. RBD برای جلوگیری از نوشتن کلاینت قدیمی، شکستن قفل را با blocklist همراه می‌کند (فصل ۲۹).

![خط زمانی شش درخواست قفل از دو کلاینت روی یک شیء. نقطه‌های سبز موفق و قرمز ناموفق‌اند. نوارهای سایه‌دار بازه‌ی نگه‌داشتن قفل هستند. تمدید A در ثانیه‌ی 25 انقضا را به 55 می‌برد. چون هیچ‌کس پیش از ثانیه‌ی 60 به قفل دست نمی‌زند، ورودی A تا آن لحظه در xattr می‌ماند و تنها در درخواست B پاک می‌شود](figures/ch15/f06_lock.png){#fig-15-f06_lock}

## خواندن صفحه‌ای omap درون کلاس {#sec-15-6-3}

::: {.algo #alg-15-3 title="صفحه‌بندی cls_cxx_map_get_vals" src="src/osd/objclass.cc :: cls_cxx_map_get_vals؛ src/osd/PrimaryLogPG.cc :: do_osd_ops (CEPH_OSD_OP_OMAPGETVALS)" complexity="O(log K + n) برای K کلید omap و n کلید برگشتی (یک seek و پیمایش)"}
:::

```text
pseudocode
max_return = min(max_to_get, osd_max_omap_entries_per_request = 1024)
seek = max(start_after, filter_prefix) ; نوع = (prefix > start_after) ? LOWER_BOUND : UPPER_BOUND
iterate (key, value):
    if key پیشوند filter_prefix را ندارد: STOP
    if num ≥ max_return or bytes ≥ osd_max_omap_bytes_per_request (1 GiB): truncated = true ; STOP
    encode(key, value) ; num++
return (vals, more = truncated)
```

**مثال عددی.** شیئی 2500 کلید `u_0000` تا `u_2499` و چند کلید با پیشوند دیگر دارد. کلاس با filter_prefix = "u_" و max_to_get = 1000 در حلقه می‌خواند.

- **فراخوانی 1:** start_after خالی، 1000 کلید، more = true.
- **فراخوانی 2:** start_after = "u_0999"، 1000 کلید، more = true.
- **فراخوانی 3:** start_after = "u_1999"، 500 کلید. کلید بعدی پیشوند دیگری دارد، پس STOP بدون truncated و more = false.

more فقط وقتی true است که یک کلید مطابق دیگر واقعاً دیده شده باشد. پس اگر دقیقاً 1000 کلید وجود داشت، فراخوانی اول more = false برمی‌گرداند. اگر کلاس max_to_get = 5000 بخواهد، OSD آن را بی‌صدا به 1024 می‌برد. کدی که فرض کند «کمتر از درخواستم گرفتم، پس تمام شد» اشتباه است. فقط به more تکیه کنید.

![سه فراخوانی پیاپی cls_cxx_map_get_vals روی 2500 کلید با پیشوند u_. هر فراخوانی از آخرین کلید فراخوانی قبلی ادامه می‌دهد (UPPER_BOUND، یعنی کلید بعد از start_after). خط قرمز سقف 1024 کلید در هر درخواست است که روی max_to_get اعمال می‌شود. پرچم more فقط در صفحه‌ی آخر false است](figures/ch15/f07_omap.png){#fig-15-f07_omap}

::: {.debug}
اگر متد کلاس شما EIO برمی‌گرداند، اول `debug_osd = 10` را روی OSD primary فعال کنید و دنبال «tried to read object but is not marked RD» یا «tried to update object but is not marked WR» بگردید. اگر EPERM می‌گیرید، `ceph config get osd osd_class_load_list` را بررسی کنید.
:::

# کلاس‌ها روی کلاستر واقعی: درستی و هزینه {#sec-15-7}

دو آزمایش این بخش روی کلاستر آزمایشی سه‌OSDی BlueStore با Ceph 18.2.7 اجرا شدند. کلاینت python-rados بود و از `Ioctx.execute` استفاده کرد.

## شمارنده: cls_numops در برابر خواندن و نوشتن از کلاینت {#sec-15-7-1}

::: {.algo #alg-15-4 title="افزایش اتمی با یک متد کلاس" src="src/cls/numops/cls_numops.cc :: add (cls_cxx_map_get_val، سپس cls_cxx_map_set_val)؛ سریال‌سازی با قفل PG در PrimaryLogPG" complexity="O(1) برای هر افزایش"}
:::

```text
pseudocode
ورودی: encode(string key) ‖ encode(string diff)           # هر string = u32 طول + بایت‌ها
cls: v = map_get_val(key) یا 0 ؛ v += diff ؛ map_set_val(key, str(v))   # یک op، زیر قفل PG
کلاینت (روش ناامن): v = read omap(key) ؛ write omap(key, v+1)          # دو op جدا، بدون قفل
N رشته × K افزایش روی یک شیء ← مقدار نهایی را با N×K مقایسه کن
```

**نتیجه (هر رشته 300 افزایش).** با cls_numops مقدار نهایی در هر پنج حالت (1، 2، 4، 8 و 16 رشته) دقیقاً N × 300 شد. روش خواندن و نوشتن از سمت کلاینت با یک رشته درست بود، ولی با 2 رشته 297 افزایش از 600 گم شد (50٪)، با 4 رشته 64٪، با 8 رشته 79٪ و با 16 رشته 89٪.

دلیل این است که OSD هر op روی یک شیء را زیر قفل PG اجرا می‌کند، پس `add` بین خواندن و نوشتن قطع نمی‌شود. دو op جدای کلاینت چنین ضمانتی ندارند. هزینه‌ی زمانی در این ماشین مجازی مشترک پرنوسان بود: میانه‌ی 0.25 تا 6 میلی‌ثانیه و جهش‌هایی حدود 0.2 ثانیه در صدک 99 که علتشان را بررسی نکردیم. پس از عدد latency نتیجه نگیرید.

اگر کلاس مناسبی ندارید، راه درستِ سمت کلاینت، تراکنش شرطی است: `cmpxattr` یا `assert_version` را در همان op نوشتن بگذارید و اگر شرط برقرار نبود، دوباره تلاش کنید. اگر مقایسه‌ی `cmpxattr` شکست بخورد، خطا `ECANCELED` است. اگر نسخه‌ی `assert_version` کوچک‌تر یا بزرگ‌تر از نسخه‌ی فعلی شیء باشد، خطا به ترتیب `ERANGE` یا `EOVERFLOW` است (`PrimaryLogPG::do_osd_ops`).

![چپ: مقدار نهایی شمارنده پس از 300 افزایش در هر رشته، با cls_numops (سبز) و با خواندن omap، افزودن یک و نوشتن از سمت کلاینت (قرمز). خط سیاه مقدار مورد انتظار است. راست: میانه‌ی زمان هر افزایش روی کلاستر آزمایشی Ceph 18.2.7](figures/ch15/f08_numops.png){#fig-15-f08_numops}

## فیلتر کنار داده با cls_lua: کی می‌ارزد؟ {#sec-15-7-2}

در Ceph 18.2.7 کلاس lua در فهرست پیش‌فرض `osd_class_load_list` نیست. برای این آزمایش، `lua` را به هر دو فهرست افزودیم و OSDها را دوباره راه‌اندازی کردیم. سپس همان اسکریپت `count_lines` بخش قبل را روی شیءهایی از 64 KiB تا 16 MiB اجرا کردیم و با «خواندن کل شیء و شمردن در کلاینت» مقایسه کردیم. هر نقطه میانه‌ی 15 اجرا بود.

::: {.algo #alg-15-5 title="نقطه‌ی سربه‌سر پردازش کنار داده" src="اندازه‌گیری؛ clslua_read، clslua_stat و eval_json در src/cls/lua/cls_lua.cc" complexity="O(اندازه‌ی شیء) در هر دو روش"}
:::

```text
pseudocode
t_lua(S)    = زمان eval_json روی شیء S بایتی          # پاسخ چند بایت
t_client(S) = زمان read(S) روی loopback + شمردن        # بدون هزینه‌ی شبکه
روی شبکه‌ی واقعی: t_client(S, B) ≈ t_client(S) + S / B
سربه‌سر: B* = S / (t_lua(S) − t_client(S))      ← اگر پهنای باند مؤثر کمتر از B* است، Lua زودتر تمام می‌کند
```

**نتیجه.** روی loopback، Lua چهار تا پنج برابر کندتر بود. برای 16 MiB، زمان Lua برابر 111.6 میلی‌ثانیه بود و زمان کلاینت 29.4 میلی‌ثانیه. دلیلش این است که هر درخواست یک وضعیت تازه‌ی Lua می‌سازد، اسکریپت را ترجمه می‌کند و `gsub` را در مفسر اجرا می‌کند. پاسخ Lua فقط 4 تا 6 بایت بود، در برابر کل شیء.

پهنای باند سربه‌سر از این اندازه‌گیری‌ها برای 64 KiB حدود 0.58 Gb/s و برای 16 MiB حدود 1.63 Gb/s است. پس روی شبکه‌ی 10 گیگابیتی، خواندن به کلاینت سریع‌تر است. Lua فقط وقتی می‌ارزد که لینک کند یا پرترافیک است، یا وقتی فیلتر تعداد زیادی شیء را رد می‌کند و داده‌ی کمی برمی‌گرداند.

هزینه‌ی پنهان مهم‌تر این است که اجرای 111 میلی‌ثانیه‌ای Lua تمام آن مدت قفل PG را نگه می‌دارد. همه‌ی opهای دیگرِ آن PG پشت آن صف می‌کشند.

![چپ: میانه‌ی زمان شمردن خط‌ها در شیءهای 64 KiB تا 16 MiB، با cls_lua درون OSD (بنفش) و با خواندن کل شیء در کلاینت (آبی) روی loopback. خط‌چین‌ها همان زمان کلاینت را به‌علاوه‌ی زمان انتقال روی 10 و 1 گیگابیت نشان می‌دهند (محاسبه‌شده). راست: پهنای باند سربه‌سر که زیر آن اجرای Lua زودتر تمام می‌شود](figures/ch15/f09_lua.png){#fig-15-f09_lua}

# از درون کد: مسیر یک فراخوانی کلاس {#sec-15-8}

## از MOSDOp تا method->exec {#sec-15-8-1}

![مسیر کامل یک فراخوانی کلاس در سه ردیف: کلاینت با Objecter درخواست CEPH_OSD_OP_CALL را به primary می‌فرستد؛ PrimaryLogPG::do_osd_ops نام کلاس و متد را decode و با ClassHandler کلاس را باز می‌کند؛ سپس متد اجرا و تعداد خواندن و نوشتن با پرچم‌های اعلام‌شده مقایسه می‌شود و تغییرات در تراکنش PG ثبت می‌شود](figures/ch15/f01_flow.png){#fig-15-f01_flow}

در سمت کلاینت، `exec` یک زیرعملیات `CEPH_OSD_OP_CALL` به عملیات مرکب اضافه می‌کند که شامل طول نام کلاس، طول نام متد و داده‌ی ورودی است. در OSD، `PrimaryLogPG::do_osd_ops()` در شاخه‌ی `case CEPH_OSD_OP_CALL` این سه را از payload جدا می‌کند. بخش کلیدی این شاخه، کنترل صداقت متد است:

```cpp
// from ceph/ceph, LGPL — src/osd/PrimaryLogPG.cc, do_osd_ops(), case CEPH_OSD_OP_CALL (excerpt)
int prev_rd = ctx->num_read;
int prev_wr = ctx->num_write;
result = method->exec((cls_method_context_t)&ctx, indata, outdata);

if (ctx->num_read > prev_rd && !(flags & CLS_METHOD_RD)) {
  derr << "method " << cname << "." << mname << " tried to read object but is not marked RD" << dendl;
  result = -EIO;
  break;
}
if (ctx->num_write > prev_wr && !(flags & CLS_METHOD_WR)) {
  derr << "method " << cname << "." << mname << " tried to update object but is not marked WR" << dendl;
  result = -EIO;
  break;
}
```

چرا این کنترل مهم است؟ پرچم‌ها پیش از اجرا در `init_op_flags()` برای تعیین نوع عملیات (خواندنی یا نوشتنی) به کار می‌روند: عملیات نوشتنی باید به primary برود، در log PG ثبت و به replicaها تکثیر شود، و در pool با snapshot، cloning را فعال کند. اگر متدی بدون پرچم WR بنویسد، OSD ممکن است آن را مانند خواندن پردازش کند و تغییر بدون تکثیر بماند. بنابراین Ceph پس از اجرا بررسی می‌کند و در صورت نقض، `-EIO` برمی‌گرداند. پرچم سوم، `CLS_METHOD_PROMOTE`، برای تیرینگ کش (فصل ۱۶) بود و به OSD می‌گفت شیء پیش از اجرا باید به لایه‌ی کش آورده شود.

```text
pseudocode: CALL در do_osd_ops (خلاصه‌ی این کتاب)
  decode(class_name, method_name, indata)  else -EINVAL
  cls    = ClassHandler.open_class(class_name)      # در init_op_flags تأیید شده
  method = cls.get_method(method_name)               else -EOPNOTSUPP
  if method.flags & WR: ctx.user_modify = true
  snapshot(num_read, num_write)
  r = method.exec(ctx, indata, &outdata)             # cls_cxx_* داخل ctx.ops کار می‌کنند
  verify RD/WR honesty                               else -EIO
  if r >= 0: append outdata to reply                 # تغییرات در ctx->op_t
```

## بارگذاری کلاس: ClassHandler {#sec-15-8-2}

![دو مرحله‌ی بارگذاری کلاس در ClassHandler: بالا، نخستین فراخوانی با بررسی osd_class_load_list و dlopen فایل libcls_X.so از osd_class_dir و اجرای __cls_init؛ پایین، ثبت متدها با نام و پرچم و تعیین وضعیت allowed بر اساس osd_class_default_list که روی تفسیر capهای class-read و class-write اثر دارد](figures/ch15/f02_load.png){#fig-15-f02_load}

`ClassHandler::_get_class()` در `src/osd/ClassHandler.cc` اگر کلاس در `osd_class_load_list` نباشد، پیام «not permitted to load» در log می‌نویسد و NULL برمی‌گرداند. سپس `allowed` را بر اساس `osd_class_default_list` تعیین می‌کند. `_load_class()` فایل `libcls_<name>.so` را از `osd_class_dir` با `dlopen` باز و تابع `__cls_init` (که ماکروی `CLS_INIT(name)` تعریف می‌کند) را اجرا می‌کند؛ این تابع با `cls_register` و ثبت متدها، جدول متدهای کلاس را پر می‌کند. کلاس می‌تواند با نماد اختیاری `class_deps` وابستگی‌هایش را اعلام کند تا پیش از آن بارگذاری شوند (`dlsym(cls->handle, "class_deps")`).

| پیکربندی | نقش | پیش‌فرض در کد جاری |
|---|---|---|
| osd_class_dir | مسیر فایل‌های libcls_*.so | مسیر rados-classes زیر libdir نصب |
| osd_class_load_list | کلاس‌های مجاز به بارگذاری | cephfs hello journal lock log numops otp rbd refcount rgw rgw_gc timeindex |
| osd_class_default_list | کلاس‌های مجاز برای capهای عمومی | همان فهرست |
| osd_open_classes_on_start | باز کردن کلاس‌ها هنگام شروع OSD | true |

::: {.deep}
مدل خطا: کلاس در فضای آدرس OSD اجرا می‌شود. هیچ sandbox، محدودیت حافظه یا timeout مستقلی برای متد وجود ندارد؛ متد درون همان thread پردازش PG اجرا می‌شود که قفل PG را در دست دارد. بنابراین متد کند، **همه‌ی عملیات دیگر روی آن PG** را پشت سر خود نگه می‌دارد و در `ceph health detail` به شکل slow ops ظاهر می‌شود. این همان دلیلی است که کلاس‌های خوب (مثل cls_rgw) حجم کار هر فراخوانی را محدود می‌کنند (مثلاً خواندن omap در دسته‌های محدود با `max_return`) و ادامه‌ی کار را به فراخوانی بعدی کلاینت می‌سپارند.
:::

## بافت اجرا: cls_method_context_t {#sec-15-8-3}

`cls_method_context_t` در واقع اشاره‌گری به `OpContext` همان عملیات است. توابع `cls_cxx_read`، `cls_cxx_write_full`، `cls_cxx_map_get_val` و `cls_cxx_map_set_val` (در `src/osd/objclass.cc`) هرکدام یک زیرعملیات OSD می‌سازند و از همان مسیر `do_osd_ops` اجرا می‌کنند؛ یعنی کلاس در واقع **عملیات مرکب پویا** می‌سازد که درون تراکنش جاری اعمال می‌شود. به همین دلیل شمارنده‌های `num_read` و `num_write` با هر فراخوانی این توابع بالا می‌روند و بررسی صداقت پرچم ممکن است.

```text
cls_cxx_map_set_val(hctx, key, bl):
    op = OSDOp(CEPH_OSD_OP_OMAPSETVALS, encode({key: bl}))
    return do_osd_ops(ctx, [op])     # نوشتن به ctx->op_t اضافه می‌شود؛ num_write++
```

# دام‌ها و الگوهای طراحی {#sec-15-9}

| دام | پیامد | راه درست |
|---|---|---|
| تغییر osd_class_load_list بدون حفظ پیش‌فرض‌ها | از کار افتادن RBD، RGW، CephFS | همیشه مقدار فعلی را بخوانید و الحاق کنید |
| متد بدون محدودیت کار | slow ops، مسدود شدن PG | صفحه‌بندی با max_return و ادامه از سمت کلاینت |
| استثنای مدیریت‌نشده در C++ | crash OSD در همه‌ی replicaها | try/catch و برگرداندن کد خطا |
| ناهماهنگی نسخه‌ی کلاس و OSD | خطای dlopen یا رفتار نامعین | ساخت در image هم‌نسخه، آزمون در staging |
| پرچم غلط RD/WR | خطای -EIO | پرچم دقیق؛ در Umbrella از Tagها استفاده کنید |

::: {.summary title="نکات SRE این فصل"}

- کلاس با امتیاز کامل OSD اجرا می‌شود؛ کد آن را مانند کد هسته بازبینی کنید.
- هر تغییر در فهرست کلاس‌ها را با مقدار پیش‌فرض مقایسه کنید.
- کار هر فراخوانی را محدود نگه دارید.
- cls_lua را فقط آگاهانه و با cap محدود فعال کنید.
- در cephadm، کلاس سفارشی یعنی image سفارشی؛ ارتقا را با آن برنامه‌ریزی کنید.

:::

# تکمیلی و به‌روز {#sec-15-10}

- در Umbrella (21.2.0) ثبت متدها نوع‌دار شده است (`ClassRegistrar` و `ClsMethod<Tag, ClassDef>`)؛ کلاس‌های خارج از درخت که با Tentacle ساخته شده‌اند هنگام ارتقا به بازنویسی بخش ثبت نیاز دارند.
- کلاس‌های تازه‌تر درخت، مانند `cls_fifo`، `cls_2pc_queue` و `cls_cmpomap`، الگوهای صف و مقایسه‌ی اتمی omap را برای RGW فراهم می‌کنند.
- تیرینگ کش که پرچم PROMOTE برای آن بود، در Reef منسوخ اعلام شد (فصل ۱۶).

# تمرین عملی {#sec-15-11}

1. با `io.execute(..., 'hello', 'say_hello', ...)` ورودی‌های خالی، کوتاه و بیش از ۱۰۰ بایت را آزمایش کنید.
2. cap کاربر را به `allow class hello say_hello` محدود کنید و ببینید `record_hello` چه خطایی می‌دهد.
3. شمارنده را یک بار با read-modify-write سمت کلاینت و یک بار با numops.add از ده فرایند هم‌زمان افزایش دهید و مقایسه کنید.
4. کلاس tally را بسازید، در یک کلاستر آزمایشی مستقر کنید و top را روی ده هزار کلید بسنجید.
5. در `src/osd/ClassHandler.cc` مسیر بارگذاری وابستگی‌ها را دنبال کنید.
6. کلاس lua را در کلاستر آزمایشی فعال کنید و اسکریپت شمارش خطوط را اجرا کنید؛ سپس یک حلقه‌ی طولانی بنویسید و اثرش را روی slow ops ببینید.

# پرسش‌های مرور {#sec-15-12}

1. سه مزیت اصلی اجرای منطق در کلاس به جای کلاینت چیست؟
2. چرا متد کلاس نمی‌تواند شیء دیگری را تغییر دهد؟
3. تفاوت osd_class_load_list و osd_class_default_list چیست؟
4. اگر متدی بدون پرچم WR بنویسد چه رخ می‌دهد و چرا؟
5. cap «allow class numops add» دقیقاً چه چیزی را مجاز می‌کند؟
6. چرا cls_lua به‌صورت پیش‌فرض بارگذاری نمی‌شود؟
7. در cephadm چگونه کلاس سفارشی را مستقر می‌کنید؟
8. چه تغییری در رابط ثبت متدها در Umbrella رخ داد؟
9. متد کند چه اثری بر سایر عملیات PG دارد؟
10. librbd و RGW از کدام کلاس‌ها استفاده می‌کنند؟

# منابع این فصل {#sec-15-13}

- SDK for Ceph Object Classes: https://docs.ceph.com/en/latest/rados/api/objclass-sdk/
- OSD config reference (classes): https://docs.ceph.com/en/latest/rados/configuration/osd-config-ref/
- User management and capabilities: https://docs.ceph.com/en/latest/rados/operations/user-management/
- Source: src/cls: https://github.com/ceph/ceph/tree/main/src/cls
- Source: src/osd/ClassHandler.cc: https://github.com/ceph/ceph/blob/main/src/osd/ClassHandler.cc
- Source: src/osd/OSDCap.cc: https://github.com/ceph/ceph/blob/main/src/osd/OSDCap.cc
- Source: src/include/rados/objclass.h (v20.2.0): https://github.com/ceph/ceph/blob/v20.2.0/src/include/rados/objclass.h
- Source: src/include/rados/cls_traits.hpp: https://github.com/ceph/ceph/blob/main/src/include/rados/cls_traits.hpp
- Source: src/cls/lua/cls_lua.cc: https://github.com/ceph/ceph/blob/main/src/cls/lua/cls_lua.cc
