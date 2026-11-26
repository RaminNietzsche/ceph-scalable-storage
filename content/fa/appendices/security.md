---
id: security
lang: fa
---

::: {.tldr}

- هر درخواست S3 از لایه‌های یکسانی می‌گذرد: TLS، احراز هویت (SigV4، SigV2، URL پیش‌امضا یا توکن STS)، مجوزدهی (اول Deny صریح، بعد سیاست‌های هویت و bucket، بعد ACLها)، محدودیت نرخ و سهمیه، و رمزنگاری در حالت سکون؛ ترافیک خود gateway تا RADOS را cephx و msgr2 محافظت می‌کنند.
- SigV4، URLهای پیش‌امضای کوتاه‌عمر (SigV4 حداکثر هفت روز؛ URL با SigV2 سقفی ندارد) و اعتبارنامه‌های موقت STS را به کلیدهای بلندمدت ترجیح دهید؛ کلید را با افزودن کلید تازه پیش از حذف کلید قدیمی بچرخانید.
- سیاست bucket و از Squid سیاست‌های IAM مبتنی بر حساب بنویسید؛ ACLها را خصوصی نگه دارید و Block Public Access را روشن کنید. `Deny` صریح همیشه برنده است.
- از SSE-KMS یا SSE-S3 با KMS بیرونی (Vault، KMIP یا Barbican)، TLS روی frontend یا یک load balancer مورد اعتماد، حالت `secure` در msgr2 برای ترافیک RGW به OSD، و Object Lock برای داده‌ای که نباید پاک شود استفاده کنید.
- Admin Ops API را روی اینترنت باز نکنید، برای رد ممیزی ops log یا bucket logging را روشن کنید، و اطلاعیه‌های امنیتی Ceph و نسخه‌های نقطه‌ای را دنبال کنید.

```bash
radosgw-admin ratelimit set --ratelimit-scope=user --uid=app1 --max-read-ops=1000 --max-write-ops=200
```

[![لایه‌های یک درخواست S3 در RGW: TLS، احراز هویت، مجوزدهی، محدودیت نرخ و سهمیه، رمزنگاری در حالت سکون، و پیوند cephx و msgr2 تا RADOS، همراه با ops log](figures/app/f02_rgw_security_layers.png)](#fig-app-rgw-security-layers)

:::

این پیوست امنیت RADOS Gateway را یک‌جا گرد می‌آورد: مهاجم در برابر یک endpoint از نوع S3 چه می‌تواند بکند، RGW چگونه درخواست را احراز هویت و مجوزدهی می‌کند، داده در مسیر و در حالت سکون چگونه رمز می‌شود، جلوی حذف و سوءاستفاده را چگونه می‌گیریم، و یک فهرست مقاوم‌سازی با گزینه‌های پیکربندی مهم. فصل ۴ کاربران، سیاست‌ها و رمزنگاری را معرفی می‌کند؛ فصل ۴۱ مسیر یک درخواست را در کد gateway دنبال می‌کند؛ این پیوست نگاه اپراتور به همان مسیر است. نام همه‌ی گزینه‌های زیر از `src/common/options/rgw.yaml.in` گرفته شده و دستورهای کلیدی در [پیوست ب: برگه‌ی تقلب دستورها](#appB) هم آمده‌اند.

![لایه‌های یک درخواست S3 در RGW، از کلاینت تا RADOS: TLS روی frontend به نام beast یا روی load balancer؛ احراز هویت با SigV4، SigV2، URL پیش‌امضا یا توکن STS؛ مجوزدهی با Deny صریح، سیاست‌های هویت و bucket و ACLها؛ محدودیت نرخ و سهمیه؛ رمزنگاری در حالت سکون با SSE-S3، SSE-KMS یا SSE-C؛ و پیوند با OSDها با cephx و حالت secure در msgr2. ops log و bucket logging هر درخواست را ثبت می‌کنند](figures/app/f02_rgw_security_layers.png){#fig-app-rgw-security-layers}

# مدل تهدید

از این شروع کنید که از چه چیزی و در برابر چه کسی محافظت می‌کنید. برای یک gateway معمولی S3 فهرست مفید کوتاه است:

| تهدید | نمونه | دفاع اصلی |
|---|---|---|
| اعتبارنامه‌ی دزدیده‌شده یا نشت‌کرده | یک access key در مخزن عمومی Git، یک URL پیش‌امضا در یک گفتگو | اعتبارنامه‌ی کوتاه‌عمر STS، URL پیش‌امضای کوتاه، چرخش کلید، سیاست‌های کمترین دسترسی |
| داده‌ی عمومی از سر اشتباه | سیاست bucket با `"Principal": "*"`، ACL از نوع `public-read` | Block Public Access، بازبینی سیاست‌ها، کنار گذاشتن ACLها |
| دسترسی یک مستأجر به داده‌ی مستأجر دیگر | فضای نام مشترک، سیاستی بیش از حد باز | حساب یا tenant، سیاست‌های محدود به ARN، placement جدا برای داده‌ی حساس |
| شنود یا دست‌کاری روی شبکه | HTTP ساده روی شبکه‌ی مشترک، حالت `crc` در msgr2 | TLS تا کلاینت، حالت `secure` در msgr2 تا OSDها |
| افشای داده در حالت سکون | دیسک دزدیده‌شده، میزبانی که از رده خارج شده | SSE با KMS بیرونی، OSDهای رمزشده (فصل ۱۱) |
| حذف یا باج‌افزار | یک کلید لورفته شیءها را پاک یا بازنویسی می‌کند | نسخه‌بندی، Object Lock، MFA delete، یک رونوشت جدا (فصل ۵) |
| سوءاستفاده و از کار انداختن سرویس | کلاینتی gateway را با درخواست پر می‌کند یا خوشه را پر می‌کند | محدودیت نرخ، سهمیه، load balancer با محدودیت اتصال |
| سوءاستفاده از صفحه‌ی مدیریت | Admin Ops API از اینترنت در دسترس است، کاربری با caps مدیریتی | endpoint مدیریتی جدا، `rgw_enable_apis`، کمترین caps |
| نبود رد ممیزی | هیچ سابقه‌ای از اینکه چه کسی شیئی را پاک کرد | ops log، bucket logging، usage log، گردآوری متمرکز لاگ |

gateway خودش هم کلاینت خوشه است: یک کلید cephx با دسترسی گسترده روی poolهای RGW دارد. هر چیزی که روی میزبان RGW اجرا شود می‌تواند از این کلید استفاده کند؛ پس میزبان‌های RGW را بخشی از خوشه‌ی ذخیره‌سازی بدانید، نه وب‌سرورهایی معمولی.

# احراز هویت: کاربران، کلیدها و امضاها

## کاربران، subuserها و کلیدها

هر کاربر RGW (فصل ۴، [ساخت کاربر radosgw](#sec-04-4-1)) یک یا چند جفت کلید S3 دارد؛ subuser کلید Swift خودش و سطح دسترسی محدودی دارد. کاربرهای سرویس را با کمترین دسترسی لازم بسازید و هنگام بررسی یک حادثه به‌جای حذف کاربر آن را معلق کنید:

```bash
radosgw-admin user create --uid=app1 --display-name="Application 1"
radosgw-admin subuser create --uid=app1 --subuser=app1:swift --access=read --key-type=swift --gen-secret
radosgw-admin user suspend --uid=app1
radosgw-admin user enable --uid=app1
```

`radosgw-admin user info --uid=app1` کلیدها، caps و سهمیه‌های یک کاربر را نشان می‌دهد؛ کلیدهای مخفی را هم چاپ می‌کند، پس خروجی آن را در تیکت نچسبانید.

## SigV4 و SigV2

RGW نسخه‌ی ۴ امضای AWS و نسخه‌ی قدیمی‌تر ۲ را می‌پذیرد. SigV4 درخواست را با کلیدی امضا می‌کند که از secret، تاریخ، region و سرویس مشتق شده است؛ بنابراین امضای شنودشده فقط برای همان درخواست و مدتی کوتاه معتبر است. SigV2 با خود secret امضا می‌کند و ضعیف‌تر است. فصل ۴۱ ([امضای SigV4](#sec-41-3)) این بررسی را گام‌به‌گام در کد دنبال می‌کند. کلاینت‌ها و SDKها را روی SigV4 تنظیم کنید؛ بیشتر SDKهای امروزی به‌طور پیش‌فرض همین کار را می‌کنند. اختلاف ساعت برای هر دو مهم است: NTP را روی میزبان‌های gateway روشن نگه دارید.

با Keystone (فصل ۴، [یکپارچه‌سازی با OpenStack Keystone](#sec-04-7)) یا LDAP، گزینه‌ی `rgw_s3_auth_order` ترتیب امتحان موتورهای احراز هویت را تعیین می‌کند و `rgw_s3_auth_use_keystone` موتور Keystone را روشن می‌کند. فقط موتورهایی را روشن کنید که به کار می‌برید.

## URLهای پیش‌امضا و محدودیت‌هایشان

URL پیش‌امضا امضا را در query string با خود دارد؛ پس هر کسی که URL را داشته باشد تا پایان اعتبارش می‌تواند همان یک عملیات را انجام دهد. RGW همان محدودیت‌هایی را بررسی می‌کند که AWS مستند کرده است: برای SigV4 مقدار `X-Amz-Expires` باید بین ۱ ثانیه و ۶۰۴۸۰۰ ثانیه (هفت روز) باشد. URL پیش‌امضا با SigV2 یک زمان مطلق `Expires` دارد و RGW فقط بررسی می‌کند که این زمان نگذشته باشد؛ پس یک URL با SigV2 می‌تواند سال‌ها معتبر بماند. کوتاه‌ترین عمر کارآمد را به URLها بدهید، آن‌ها را با SigV4 بسازید، و به یاد داشته باشید که URL تا پایان اعتبارش معتبر می‌ماند حتی اگر کاربر دیگر به آن نیاز نداشته باشد؛ تنها راه باطل کردن زودهنگامش حذف کلیدی است که آن را امضا کرده است.

اگر هیچ برنامه‌ای به URL پیش‌امضا نیاز ندارد، آن را کاملاً خاموش کنید؛ این گزینه از Squid وجود دارد:

```bash {since=squid}
ceph config set client.rgw rgw_s3_auth_disable_signature_url true
```

## چرخش کلیدها

کلید را بدون قطعی بچرخانید: اول کلید تازه را اضافه کنید، کلاینت‌ها را جابه‌جا کنید و فقط پس از آن کلید قدیمی را حذف کنید. از Squid می‌توان کلید را پیش از حذف غیرفعال کرد که راه بازگشتی سریع است:

```bash
radosgw-admin key create --uid=app1 --key-type=s3 --gen-access-key --gen-secret
radosgw-admin key rm --uid=app1 --key-type=s3 --access-key=OLDACCESSKEY
```

```bash {since=squid}
radosgw-admin key create --uid=app1 --key-type=s3 --access-key=OLDACCESSKEY --key-active=false
```

کلید cephx خود gateway مانند کلید هر daemon دیگری چرخانده می‌شود؛ [گام ۲ راهنمای ارتقا: انتقال کلیدهای cephx به aes256k](#appJ) را ببینید.

# مجوزدهی: سیاست‌ها و ACLها

## ترتیب ارزیابی

RGW درخواست را به ترتیب مدل سیاست AWS ارزیابی می‌کند؛ منطق آن در `evaluate_iam_policies()` در `rgw_common.cc` است:

1. یک `Deny` صریح در سیاست هویت، سیاست bucket یا سیاست نشست درخواست را رد می‌کند.
2. در غیر این صورت یک `Allow` از سیاست bucket یا از یک سیاست هویت اجازه می‌دهد. در نشست STS سیاست نشست هم باید آن عمل را مجاز کند.
3. برای درخواستی میان دو حساب (از Squid)، هم سیاست هویت فراخواننده و هم سیاست bucket مالک باید اجازه دهند.
4. اگر هیچ سیاستی تصمیم نگیرد، RGW به ACLهای bucket و شیء برمی‌گردد.

![ارزیابی سیاست در RGW: یک Deny صریح در هر سیاستی درخواست را رد می‌کند؛ در غیر این صورت Allow از سیاست هویت یا bucket (و برای STS از سیاست نشست) اجازه می‌دهد؛ درخواست میان دو حساب به Allow از هر دو سو نیاز دارد؛ بدون تصمیم، RGW به ACLها برمی‌گردد و اگر اجازه‌ای نباشد درخواست رد می‌شود](figures/app/f03_rgw_policy_eval.png){#fig-app-rgw-policy-eval}

## سیاست‌های bucket

سیاست bucket (فصل ۴، [سیاست bucket و IAM](#sec-04-11-3)) ابزار اصلی برای دسترسی میان کاربران است. دو شرط ارزش دارند که تقریباً به هر سیاستی اضافه شوند: رد درخواست‌هایی که از راه TLS نرسیده‌اند، و محدود کردن bucketهای حساس به شبکه‌های شناخته‌شده.

```json
{"Version":"2012-10-17","Statement":[
  {"Sid":"DenyPlainHTTP","Effect":"Deny","Principal":"*","Action":"s3:*",
   "Resource":["arn:aws:s3:::reports","arn:aws:s3:::reports/*"],
   "Condition":{"Bool":{"aws:SecureTransport":"false"}}},
  {"Sid":"OfficeOnly","Effect":"Deny","Principal":"*","Action":"s3:*",
   "Resource":["arn:aws:s3:::reports","arn:aws:s3:::reports/*"],
   "Condition":{"NotIpAddress":{"aws:SourceIp":["10.20.0.0/16"]}}}]}
```

`aws:SecureTransport` فقط وقتی true است که خود RGW اتصال TLS را پایان دهد، یا پشت load balancerی که `X-Forwarded-Proto` را تنظیم می‌کند گزینه‌ی `rgw_trust_forwarded_https` روشن باشد. `aws:SourceIp` نشانی‌ای است که RGW می‌بیند: پشت load balancer گزینه‌ی `rgw_remote_addr_param` را روی سرآیندی بگذارید که نشانی کلاینت را می‌آورد (مثلاً `HTTP_X_FORWARDED_FOR`)، و مطمئن شوید load balancer این سرآیند را بازنویسی می‌کند و مقدار فرستاده‌شده از کلاینت را عبور نمی‌دهد.

به‌طور پیش‌فرض `rgw_policy_reject_invalid_principals` برابر true است، پس RGW سیاستی را که principal آن وجود ندارد رد می‌کند؛ همین را نگه دارید، چون در غیر این صورت یک غلط تایپی در principal سیاستی می‌سازد که بی‌صدا هیچ کاری نمی‌کند.

## ACLها و دام‌هایشان

ACLها از سیاست‌ها قدیمی‌تر و درشت‌دانه‌اند: `READ` روی bucket یعنی فهرست کردن، `WRITE` یعنی ساختن و بازنویسی هر شیء، و ACLهای آماده‌ی `public-read` و `public-read-write` یک bucket را به روی کل اینترنت باز می‌کنند. ACLی که به گروه `AuthenticatedUsers` داده شود به همه‌ی کاربران خوشه دسترسی می‌دهد، نه فقط به کاربران سازمان شما. ACLها را خصوصی نگه دارید، دسترسی را با سیاست‌ها بدهید، و Block Public Access را برای هر bucketی که قرار نیست عمومی باشد روشن کنید:

```bash
aws $EP s3api put-public-access-block --bucket reports \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

با `RestrictPublicBuckets`، اگر درخواست‌کننده در حساب مالک bucket نباشد، RGW درخواستی را که یک سیاست bucket عمومی اجازه می‌داد رد می‌کند.

## حساب‌ها، کاربران، گروه‌ها و نقش‌های IAM

از Squid، هر حساب ([tenant و حساب](#sec-04-4-4)) مالک کاربران، گروه‌ها، نقش‌ها و سیاست‌هایشان است و کاربر root حساب آن‌ها را با IAM API مدیریت می‌کند. مدیر خوشه حساب و کاربر root آن را یک بار می‌سازد؛ از آن پس حساب خودش را مدیریت می‌کند:

```bash {since=squid}
radosgw-admin account create --account-name=acme --email=ops@acme.example
radosgw-admin user create --uid=acme-root --display-name="ACME root" --account-id=<account-id> --account-root --gen-access-key --gen-secret
radosgw-admin user policy attach --uid=app1 --policy-arn=arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
```

```bash {since=squid}
aws $EP iam create-user --user-name app2
aws $EP iam put-user-policy --user-name app2 --policy-name rw-builds --policy-document file://rw-builds.json
```

از کاربر root حساب فقط برای ساختن کاربران و نقش‌های IAM استفاده کنید، مانند کاربر root یک حساب AWS. یادداشت‌های انتشار Tentacle قابلیت‌های قدیمی‌تر IAM در سطح tenant را به نفع حساب‌ها منسوخ اعلام کرده‌اند؛ برای طراحی تازه از حساب‌ها استفاده کنید.

# STS: اعتبارنامه‌های موقت

STS برای یک نقش اعتبارنامه‌ی موقت (access key، secret و توکن نشست) صادر می‌کند. آن را روی همه‌ی gatewayها با کلیدی یکسان روشن کنید؛ در Reef این کلید ۱۶ نویسه‌ی شانزده‌شانزدهی است و از Squid توضیح گزینه کلیدی base64 از `ceph-authtool --gen-print-key` می‌خواهد؛ پس از توضیح نسخه‌ی خودتان پیروی کنید:

```bash
ceph config set client.rgw rgw_s3_auth_use_sts true
ceph config set client.rgw rgw_sts_key <key>
ceph config set client.rgw rgw_sts_max_session_duration 3600
```

## AssumeRole

هر نقش یک سیاست اعتماد (چه کسی می‌تواند آن را بپذیرد) و سیاست‌های مجوز (چه کاری می‌تواند بکند) دارد:

```bash
radosgw-admin role create --role-name=Reports --assume-role-policy-doc=file://trust.json
radosgw-admin role-policy put --role-name=Reports --policy-name=read-reports --policy-doc=file://read-reports.json
```

```bash
aws $EP sts assume-role --role-arn arn:aws:iam:::role/Reports --role-session-name nightly --duration-seconds 900
```

سپس کلاینت درخواست‌هایش را با کلیدهای موقت و توکن نشست امضا می‌کند. کلید موقتِ لورفته فقط تا پایان نشست به کار می‌آید؛ به همین دلیل STS بهترین جایگزین کلیدهای بلندمدت در jobها و pipelineهاست.

## AssumeRoleWithWebIdentity و OIDC

با AssumeRoleWithWebIdentity کلاینتی که از یک ارائه‌دهنده‌ی OpenID Connect (Keycloak، Dex یا صادرکننده‌ی service account در Kubernetes) توکن دارد، بی‌آنکه هیچ کلید RGW داشته باشد اعتبارنامه‌ی موقت می‌گیرد. ارائه‌دهنده را ثبت کنید و سپس claimهای آن را در سیاست اعتماد نقش به کار ببرید:

```bash
aws $EP iam create-open-id-connect-provider --url https://sso.example.com/realms/ceph \
  --client-id-list ceph-s3 --thumbprint-list <thumbprint>
aws $EP sts assume-role-with-web-identity --role-arn arn:aws:iam:::role/Reports \
  --role-session-name alice --web-identity-token "$TOKEN"
```

سیاست اعتماد را به `aud` (شناسه‌ی کلاینت) و در صورت امکان به `sub` یا claim گروه محدود کنید؛ سیاست اعتمادی که هر توکنی از ارائه‌دهنده را بپذیرد به همه‌ی کاربران ارائه‌دهنده‌ی هویت اجازه می‌دهد نقش را بپذیرند.

# رمزنگاری

## در مسیر: TLS

TLS را یا روی frontend به نام beast در RGW پایان دهید یا روی یک load balancer مانند سرویس ingress در cephadm (فصل ۴، [load balancer با سرویس ingress](#sec-04-3-2)). beast گزینه‌های `ssl_port`، `ssl_certificate`، `ssl_private_key`، `ssl_options` و `ssl_ciphers` را در `rgw_frontends` می‌پذیرد:

```bash
ceph config set client.rgw rgw_frontends "beast ssl_port=443 ssl_certificate=config://rgw/cert/rgw.pem ssl_options=no_sslv2:no_sslv3:no_tlsv1:no_tlsv1_1"
```

اگر TLS روی load balancer پایان یابد، پیوند load balancer تا RGW یک HTTP ساده است؛ آن را روی شبکه‌ی خصوصی نگه دارید و فقط در این حالت `rgw_trust_forwarded_https = true` را تنظیم کنید. چون `rgw_crypt_require_ssl` به‌طور پیش‌فرض true است، RGW درخواست‌هایی را که سرآیند کلید رمزنگاری دارند ولی از راه TLS (یا یک اتصال HTTPS فرستاده‌شده‌ی مورد اعتماد) نرسیده‌اند رد می‌کند.

## در حالت سکون: SSE-S3، SSE-KMS و SSE-C

| حالت | کلید نزد کیست | گزینه‌های RGW | نکته |
|---|---|---|---|
| SSE-C | کلاینت کلید را با هر درخواست می‌فرستد | هیچ | RGW هرگز کلید را نگه نمی‌دارد؛ کلید گم شود، شیء هم از دست رفته است |
| SSE-KMS | یک KMS بیرونی: Vault، KMIP یا Barbican | `rgw_crypt_s3_kms_backend`، `rgw_crypt_vault_*`، `rgw_crypt_kmip_*`، `rgw_barbican_url` | کلاینت شناسه‌ی کلید را می‌دهد؛ برای کلید جدا برای هر مستأجر مناسب است |
| SSE-S3 | RGW، با کلیدهایی که در Vault نگه داشته می‌شوند | `rgw_crypt_sse_s3_backend` (فقط `vault`)، `rgw_crypt_sse_s3_vault_*` | با put-bucket-encryption می‌تواند پیش‌فرض bucket باشد |

پیکربندی Vault برای SSE-KMS با موتور transit و یک فایل توکن:

```bash
ceph config set client.rgw rgw_crypt_s3_kms_backend vault
ceph config set client.rgw rgw_crypt_vault_addr https://vault.example.com:8200
ceph config set client.rgw rgw_crypt_vault_auth token
ceph config set client.rgw rgw_crypt_vault_token_file /etc/ceph/vault.token
ceph config set client.rgw rgw_crypt_vault_secret_engine transit
ceph config set client.rgw rgw_crypt_vault_prefix /v1/transit
```

برای KMIP، `rgw_crypt_s3_kms_backend = kmip` را همراه با `rgw_crypt_kmip_addr`، `rgw_crypt_kmip_ca_path`، `rgw_crypt_kmip_client_cert` و `rgw_crypt_kmip_client_key` تنظیم کنید. در محیط عملیاتی از `rgw_crypt_s3_kms_encryption_keys` یا `rgw_crypt_default_encryption_key` استفاده نکنید: این‌ها کلیدها را در پیکربندی Ceph نگه می‌دارند و برای آزمایش‌اند. `rgw_crypt_suppress_logs` را روی پیش‌فرض `true` نگه دارید تا کلیدها هرگز به لاگ نرسند (درس CVE-2018-16889).

رمزنگاری را پیش‌فرض bucket کنید تا کلاینت‌ها فراموشش نکنند، و بارگذاری رمزنشده را در سیاست bucket با کلید شرط `s3:x-amz-server-side-encryption` رد کنید:

```bash
aws $EP s3api put-bucket-encryption --bucket reports \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

## درون خوشه: حالت secure در msgr2

gateway با monitorها و OSDها از راه msgr2 حرف می‌زند. در حالت پیش‌فرض `crc` داده با cephx احراز می‌شود ولی روی شبکه رمز نمی‌شود؛ در حالت `secure` هر frame با AES-GCM رمز می‌شود (فصل ۲۶، [حالت secure: AES-128-GCM روی سیم](#sec-26-4)). روی شبکه‌ای که کاملاً در اختیارتان نیست، حالت secure را برای کلاینت‌های RGW و اگر OSDها و monitorها از پس هزینه‌ی CPU برمی‌آیند برای کل خوشه الزامی کنید:

```bash
ceph config set client.rgw ms_client_mode secure
ceph config set global ms_service_mode secure
ceph config set global ms_cluster_mode secure
```

رمزنگاری سمت سرور داده‌ی شیء را در حالت سکون و روی شبکه‌ی OSD محافظت می‌کند؛ حالت secure فراداده، شاخص bucket و ترافیک omap را هم محافظت می‌کند. CVE-2020-1759 (استفاده‌ی دوباره از nonce در حالت secure) یادآوری است که نسخه‌ی نقطه‌ای دارای اصلاحات منتشرشده را اجرا کنید.

# Object Lock، نسخه‌بندی و MFA delete

نسخه‌بندی نسخه‌های قبلی یک شیء را هنگام بازنویسی یا حذف نگه می‌دارد؛ Object Lock (فصل ۴، [نسخه‌بندی و قفل شیء](#sec-04-11-1)) تا تاریخ نگهداری جلوی حذف یا بازنویسی یک نسخه را می‌گیرد، که هسته‌ی یک bucket از نوع WORM یا مقاوم در برابر باج‌افزار است. Object Lock باید هنگام ساخت bucket روشن شود و نسخه‌بندی را هم روشن می‌کند:

```bash
aws $EP s3api create-bucket --bucket audit --object-lock-enabled-for-bucket
aws $EP s3api put-object-lock-configuration --bucket audit \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":365}}}'
```

در حالت `GOVERNANCE` کاربری با `s3:BypassGovernanceRetention` هنوز می‌تواند با فرستادن `x-amz-bypass-governance-retention` یک نسخه را پاک کند؛ در حالت `COMPLIANCE` هیچ‌کس نمی‌تواند، حتی مدیر از راه S3. مجوز bypass را به‌طور پیش‌فرض به هیچ‌کس ندهید و نگهداری compliance را اول روی یک bucket آزمایشی امتحان کنید، چون کوتاه‌کردنی نیست.

RGW از MFA delete با توکن‌های TOTP هم پشتیبانی می‌کند: برای کاربر یک دستگاه TOTP بسازید و سپس MFA delete را با شماره‌ی سریال دستگاه و یک کد جاری روی نسخه‌بندی bucket روشن کنید. پس از آن، حذف یک نسخه یا تغییر وضعیت نسخه‌بندی به کد معتبری در سرآیند `x-amz-mfa` نیاز دارد:

```bash
radosgw-admin mfa create --uid=admin1 --totp-serial=admin1-totp --totp-seed=<base32-seed>
aws $EP s3api put-bucket-versioning --bucket audit \
  --versioning-configuration Status=Enabled,MFADelete=Enabled --mfa "admin1-totp 123456"
```

MFA delete در عمل کم به کار می‌رود: در برابر کلید دزدیده‌شده محافظت می‌کند، ولی نه در برابر کلید دزدیده‌شده به‌همراه seed آن TOTP، و خودکارسازی را سخت‌تر می‌کند. Object Lock در حالت compliance همراه با یک رونوشت در zone دیگر محافظت قوی‌تری است. تکثیر به site دیگر و failover در [پیوست ک: multisite و بازیابی از فاجعه](#appL) آمده‌اند.

# جداسازی مستأجرها

RGW دو سطح جداسازی دارد (فصل ۴، [tenant و حساب](#sec-04-4-4)): tenant فضای نام bucket را جدا می‌کند (`tenant:bucket`، با ARN به شکل `arn:aws:s3::tenant:bucket`) و حساب (از Squid) کاربران، نقش‌ها و سیاست‌ها را هم جدا می‌کند. هیچ‌کدام داده را روی دیسک جدا نمی‌کند: شیءهای همه‌ی مستأجرها در همان poolهای RGW می‌مانند، مگر اینکه به یک مستأجر placement target و storage class خودش با poolهای جدا بدهید (فصل ۴، [چرخه‌ی عمر، کلاس ذخیره‌سازی و placement](#sec-04-11-2)). برای جداسازی سخت‌گیرانه، با کلیدهای رمزنگاری جدا، failure domainهای جدا یا مدیران جدا، از placement جدا با poolهای جدا و کلیدهای KMS جدا برای هر مستأجر، یا از یک zone جدا استفاده کنید. هر سیاستی با `"Principal":"*"` را با دقت بررسی کنید: در میان مستأجرها ممکن است به کاربرانی برسد که به آن‌ها فکر نکرده بودید.

# محدودیت نرخ و سهمیه

محدودیت نرخ (از سمت درخواست) و سهمیه (از سمت ظرفیت) دفاع اصلی در برابر کلاینتی است که بد رفتار می‌کند، چه از سر اشتباه و چه عمدی ([سهمیه و محدودیت نرخ](#sec-04-4-2)). RGW عملیات و بایت‌ها را برای هر کاربر، هر bucket و برای درخواست‌های ناشناس در یک بازه‌ی زمانی می‌شمارد و وقتی به حد برسد با `503 SlowDown` پاسخ می‌دهد؛ فصل ۴۱ ([محدودیت نرخ](#sec-41-6)) سازوکار شمارنده‌ها را نشان می‌دهد:

```bash
radosgw-admin ratelimit set --ratelimit-scope=user --uid=app1 --max-read-ops=1000 --max-write-ops=200 --max-write-bytes=104857600
radosgw-admin ratelimit enable --ratelimit-scope=user --uid=app1
radosgw-admin global ratelimit set --ratelimit-scope=anonymous --max-read-ops=100
radosgw-admin global ratelimit enable --ratelimit-scope=anonymous
radosgw-admin quota set --quota-scope=bucket --uid=app1 --max-objects=10000000 --max-size=5T
radosgw-admin quota enable --quota-scope=bucket --uid=app1
```

این حدها در هر نمونه‌ی RGW جداگانه شمرده می‌شوند؛ پس با چهار gateway پشت یک load balancer، کلاینت می‌تواند تا چهار برابر مقدار تنظیم‌شده برسد؛ به همین نسبت تقسیم کنید. سهمیه‌ی پیش‌فرض کاربران تازه را با `rgw_user_default_quota_max_size` و `rgw_bucket_default_quota_max_objects` تنظیم کنید و تعداد bucketهای هر کاربر را با `rgw_user_max_buckets` محدود کنید. یک load balancer با محدودیت اتصال و مهلت درخواست همچنان لازم است: محدودیت نرخ پس از آن اعمال می‌شود که RGW درخواست را پذیرفته و تجزیه کرده است.

# فهرست مقاوم‌سازی

| حوزه | بررسی | گزینه یا دستور |
|---|---|---|
| Frontend | فقط TLS 1.2 یا بالاتر، رمزهای قوی، گواهی از config store | `rgw_frontends` با `ssl_options` و `ssl_ciphers` |
| Frontend | محدود کردن سرآیندهای درخواست و اتصال‌های بی‌کار | `max_header_size` و `request_timeout_ms` در `rgw_frontends` |
| Frontend | پشت load balancer: به سرآیندهایش فقط وقتی اعتماد کنید که خودش آن‌ها را بگذارد | `rgw_trust_forwarded_https`، `rgw_remote_addr_param` |
| APIها | فقط APIهایی را که به کار می‌برید روشن کنید؛ `admin` را از gatewayهای عمومی بردارید | `rgw_enable_apis` |
| Admin API | Admin Ops API را روی یک نمونه‌ی داخلی و جدای RGW ارائه کنید | `rgw_admin_entry`، `rgw_enable_apis` |
| کاربران مدیر | caps مدیریتی را فقط به کاربرانی بدهید که نیاز دارند، و هر جا ممکن است فقط‌خواندنی | `radosgw-admin caps add --uid=monitor --caps="buckets=read;users=read;usage=read"` |
| احراز هویت | URL پیش‌امضا را هر جا کسی لازمش ندارد خاموش کنید | `rgw_s3_auth_disable_signature_url` (از Squid) |
| احراز هویت | فقط موتورهای احراز هویتی را که به کار می‌برید روشن کنید | `rgw_s3_auth_order`، `rgw_s3_auth_use_keystone`، `rgw_s3_auth_use_sts` |
| سیاست‌ها | رد سیاست‌هایی با principal ناشناخته | `rgw_policy_reject_invalid_principals` (پیش‌فرض true) |
| داده‌ی عمومی | Block Public Access روی همه‌ی bucketهای خصوصی | `put-public-access-block` |
| CORS | فقط originها و سرآیندهایی را که برنامه‌ی وب لازم دارد مجاز کنید؛ هرگز `*` همراه با credentials | `put-bucket-cors`، `rgw_cors_rules_max_num` |
| وب‌سایت ایستا | API به نام s3website را فقط روی gatewayهایی روشن کنید که سایت ارائه می‌دهند | `rgw_enable_static_website`، `rgw_enable_apis` |
| رمزنگاری | KMS بیرونی، رمزنگاری پیش‌فرض bucket، بدون کلید در پیکربندی | `rgw_crypt_s3_kms_backend`، `rgw_crypt_suppress_logs` |
| پیوند خوشه | حالت secure در msgr2 برای RGW | `ms_client_mode` |
| لاگ | ops log در فایل یا socket با گردآوری متمرکز | `rgw_enable_ops_log`، `rgw_ops_log_file_path` |
| به‌روزرسانی | اجرای آخرین نسخه‌ی نقطه‌ای نسخه‌ی اصلی خودتان | [پیوست ط](#appJ) |

Admin Ops API (فصل ۴، [Admin Ops REST API](#sec-04-12-3)) می‌تواند کاربر بسازد، کلیدها را بخواند و bucketها را حذف کند. آن را از اینترنت دور نگه دارید: gatewayهای عمومی را با مقداری از `rgw_enable_apis` اجرا کنید که `admin` نداشته باشد و یک gateway داخلی جدا داشته باشید که داشته باشد. قواعد CORS منبع رایج اشتباه‌اند: origin مجاز `*` همراه با credentials یا سرآیندهای بازتابیده به هر صفحه‌ی وبی اجازه می‌دهد از نشست بازدیدکننده استفاده کند. CVE-2020-10753 و CVE-2021-3524 باگ‌های تزریق سرآیند در پردازش CORS در RGW بودند که در نسخه‌های نقطه‌ای خودشان اصلاح شدند؛ نسخه‌ای با این اصلاحات اجرا کنید و قواعد CORS را حداقلی نگه دارید.

# لاگ و ممیزی

RGW سه نوع سابقه‌ی درخواست دارد که هرکدام هدف جدایی دارند:

| سابقه | چه چیزی نگه می‌دارد | چگونه روشن می‌شود |
|---|---|---|
| Ops log | یک ورودی برای هر درخواست: زمان، کاربر، bucket، شیء، عملیات، وضعیت، بایت‌ها | `rgw_enable_ops_log` همراه با `rgw_ops_log_file_path` یا `rgw_ops_log_socket_path`؛ `rgw_ops_log_rados` آن را در RADOS می‌نویسد |
| Bucket logging (از Tentacle) | لاگ دسترسی سرور S3 برای یک bucket که به‌صورت شیء در bucket دیگری نوشته می‌شود | `put-bucket-logging` روی bucket مبدأ |
| Usage log | جمع عملیات و بایت‌ها برای هر کاربر و bucket، برای صورت‌حساب | `rgw_enable_usage_log`، سپس `radosgw-admin usage show` |

```bash
ceph config set client.rgw rgw_enable_ops_log true
ceph config set client.rgw rgw_ops_log_file_path /var/log/ceph/rgw-ops.log
ceph config set client.rgw rgw_log_http_headers http_x_forwarded_for,http_user_agent
```

```bash {since=tentacle}
radosgw-admin bucket logging info --bucket=reports
radosgw-admin bucket logging flush --bucket=reports
```

برای رد ممیزی، ops log را به یک سامانه‌ی لاگ متمرکز بفرستید که مدیران ذخیره‌سازی نتوانند تغییرش دهند، bucket مقصد bucket logging را در حسابی جدا و با Object Lock نگه دارید، و دستورهای `radosgw-admin` اجراشده روی میزبان‌های مدیریتی را ثبت کنید. Usage log رد ممیزی نیست: جمع‌ها را نگه می‌دارد، نه تک‌تک درخواست‌ها را.

پرسش‌هایی که لاگ‌ها باید پس از یک حادثه پاسخ دهند: کدام access key درخواست‌ها را فرستاد، از کدام نشانی، کدام شیءها خوانده یا حذف شدند، و از کی. پیش از آنکه لازم شود امتحانش کنید: یک شیء آزمایشی را پاک کنید و ورودی آن را پیدا کنید.

# به‌روزرسانی‌های امنیتی و اطلاعیه‌ها

Ceph اطلاعیه‌های امنیتی‌اش را در سه جا منتشر می‌کند: صفحه‌ی امنیت مستندات (docs.ceph.com/en/latest/security/) که CVEهای گذشته را با نسخه‌های اصلاح‌شده فهرست می‌کند؛ security advisoryهای GitHub در مخزن ceph/ceph؛ و فهرست پستی ceph-announce که نسخه‌های نقطه‌ای را اعلام می‌کند. اصلاحات امنیتی به‌صورت نسخه‌های نقطه‌ای نسخه‌های اصلی پشتیبانی‌شده منتشر می‌شوند؛ پس «به‌روزرسانی» معمولاً یعنی رفتن به آخرین نسخه‌ی نقطه‌ای نسخه‌ی خودتان با یک ارتقای غلتان معمولی (فصل ۱۹ و [پیوست ط](#appJ)).

یک روال عملی:

1. در ceph-announce عضو شوید، advisoryهای مخزن ceph/ceph را دنبال کنید، و اگر از بسته‌های آماده استفاده می‌کنید خوراک امنیتی توزیع یا فروشنده‌تان را هم دنبال کنید.
2. برای هر اطلاعیه تصمیم بگیرید که آیا بر شما اثر دارد: مؤلفه (RGW، cephx، dashboard)، API یا قابلیت، و نسخه‌ها.
3. اول یک خوشه‌ی آزمایشی را ارتقا دهید و بعد محیط عملیاتی را؛ اگر اصلاح فقط در RGW است، اول gatewayها را.
4. اگر ارتقا باید صبر کند، راهکار موقتی را که اطلاعیه نام برده اعمال کنید؛ مثلاً خاموش کردن یک API در `rgw_enable_apis` یا بستن یک الگوی درخواست روی load balancer.
5. آسیب‌پذیری تازه را خصوصی به security@ceph.io گزارش کنید، نه در یک tracker عمومی، و پیش از بحث درباره‌ی جزئیات منتظر انتشار هماهنگ بمانید.

نمونه‌هایی از فهرست عمومی که به RGW مربوط‌اند: CVE-2018-16889 (کلیدهای رمزنگاری در لاگ)، CVE-2019-3821 (تمام شدن file descriptorها)، CVE-2020-1760 (XSS از راه شکستن سرآیند)، CVE-2020-10753 و CVE-2021-3524 (تزریق سرآیند از راه CORS) و CVE-2023-46159 (از کار انداختن سرویس). هرکدام در یک نسخه‌ی نقطه‌ای اصلاح شد؛ درس هر بار یکی است: نسخه‌ای پشتیبانی‌شده که در آخرین نسخه‌ی نقطه‌ای‌اش نگه داشته شود.

# منابع

- مرجع پیکربندی RGW (`src/common/options/rgw.yaml.in`): https://docs.ceph.com/en/latest/radosgw/config-ref/
- احراز هویت، STS و OIDC در RGW: https://docs.ceph.com/en/latest/radosgw/STS/
- حساب‌ها و IAM API: https://docs.ceph.com/en/latest/radosgw/account/
- سیاست‌های bucket: https://docs.ceph.com/en/latest/radosgw/bucketpolicy/
- رمزنگاری سمت سرور: https://docs.ceph.com/en/latest/radosgw/encryption/
- محدودیت نرخ و سهمیه: https://docs.ceph.com/en/latest/radosgw/admin/
- Bucket logging: https://docs.ceph.com/en/latest/radosgw/bucket_logging/
- msgr2 و حالت secure: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- امنیت Ceph و CVEهای گذشته: https://docs.ceph.com/en/latest/security/
- امضای نسخه‌ی ۴ در AWS و URLهای پیش‌امضا: https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
