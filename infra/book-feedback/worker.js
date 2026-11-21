const ALLOWED_ORIGINS = new Set([
  'https://book.ceph-s3.ir',
  'http://book.ceph-s3.ir',
]);

const MAX_BODY = 8192;
const MAX_PAGE = 200;
const MAX_SECTION = 200;
const MAX_LANG = 16;
const MAX_EMAIL = 254;
const SUBSCRIBE_LIMIT = 8;
const VISITS_TTL_MS = 10 * 60 * 1000;
const ACCOUNT_ID_DEFAULT = '53895845b7cfe401510ca1843235f3fc';
const SITE_TAG_DEFAULT = '14352fa705774783a8d5f30ec547978e';
const EMAIL_RE = /^[a-z0-9._%+!-]{1,64}@[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)+$/;

function originAllowed(origin) {
  if (!origin) return false;
  if (ALLOWED_ORIGINS.has(origin)) return true;
  try {
    const u = new URL(origin);
    return (u.protocol === 'http:' || u.protocol === 'https:') &&
      (u.hostname === 'localhost' || u.hostname === '127.0.0.1');
  } catch {
    return false;
  }
}

function cors(origin) {
  const headers = {
    'Cache-Control': 'no-store',
    Vary: 'Origin',
  };
  if (origin && originAllowed(origin)) {
    headers['Access-Control-Allow-Origin'] = origin;
    headers['Access-Control-Allow-Methods'] = 'POST, OPTIONS';
    headers['Access-Control-Allow-Headers'] = 'Content-Type';
  }
  return headers;
}

function jsonResp(status, body, origin, extra) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      ...cors(origin),
      ...extra,
    },
  });
}

function empty(status, origin, extra) {
  return new Response(null, { status, headers: { ...cors(origin), ...extra } });
}

function htmlResp(status, html, extra) {
  return new Response(html, {
    status,
    headers: {
      'Content-Type': 'text/html; charset=utf-8',
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow',
      ...extra,
    },
  });
}

function clampText(value, max) {
  if (typeof value !== 'string') return '';
  const t = value.trim();
  if (!t || t.length > max) return '';
  if (/[\u0000-\u0008\u000B\u000C\u000E-\u001F]/.test(t)) return '';
  return t;
}

function parseHelpful(value) {
  if (value === true || value === 1 || value === '1') return 1;
  if (value === false || value === 0 || value === '0') return 0;
  if (typeof value === 'string') {
    const v = value.trim().toLowerCase();
    if (v === 'yes' || v === 'true' || v === 'bale' || v === 'بله') return 1;
    if (v === 'no' || v === 'false' || v === 'kheir' || v === 'خیر') return 0;
  }
  return null;
}

function normalizeEmail(value) {
  const t = clampText(String(value || ''), MAX_EMAIL).toLowerCase();
  if (!t || t.includes('..') || !EMAIL_RE.test(t)) return '';
  return t;
}

function normalizeLang(value) {
  const t = clampText(String(value || ''), MAX_LANG).toLowerCase();
  if (t === 'en' || t === 'fa') return t;
  return 'fa';
}

async function hmacHex(secret, message) {
  const enc = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    enc.encode(secret || ''),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign'],
  );
  const sig = await crypto.subtle.sign('HMAC', key, enc.encode(message));
  const bytes = new Uint8Array(sig);
  let hex = '';
  for (let i = 0; i < bytes.length; i++) hex += bytes[i].toString(16).padStart(2, '0');
  return hex;
}

async function visitorKey(request, env, day) {
  const ip = request.headers.get('CF-Connecting-IP') || '';
  const ua = request.headers.get('User-Agent') || '';
  return hmacHex(env.HASH_SALT, `${day}\0${ip}\0${ua}`);
}

function timingEqual(a, b) {
  const enc = new TextEncoder();
  const left = enc.encode(a || '');
  const right = enc.encode(b || '');
  const n = Math.max(left.length, right.length);
  let diff = left.length ^ right.length;
  for (let i = 0; i < n; i++) diff |= (left[i] || 0) ^ (right[i] || 0);
  return diff === 0;
}

function cookieValue(header, name) {
  if (!header) return '';
  const parts = header.split(';');
  for (const part of parts) {
    const [k, ...rest] = part.trim().split('=');
    if (k === name) return decodeURIComponent(rest.join('=') || '');
  }
  return '';
}

function authorized(request, env) {
  const expected = env.STATS_KEY || '';
  if (!expected) return false;
  const auth = request.headers.get('Authorization') || '';
  const bearer = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  const headerKey = request.headers.get('X-Stats-Key') || '';
  let queryKey = '';
  try { queryKey = new URL(request.url).searchParams.get('key') || ''; } catch { /* ignore */ }
  const cookieKey = cookieValue(request.headers.get('Cookie') || '', 'book_stats');
  return [bearer, headerKey, queryKey, cookieKey].some((v) => v && timingEqual(v, expected));
}

function esc(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function b64url(str) {
  const bytes = new TextEncoder().encode(str);
  let bin = '';
  for (const b of bytes) bin += String.fromCharCode(b);
  return btoa(bin).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/g, '');
}

function fromB64url(s) {
  try {
    const pad = s.length % 4 === 0 ? '' : '='.repeat(4 - (s.length % 4));
    const bin = atob(s.replace(/-/g, '+').replace(/_/g, '/') + pad);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    return new TextDecoder().decode(bytes);
  } catch {
    return '';
  }
}

async function signedToken(env, purpose, email) {
  const sig = await hmacHex(env.HASH_SALT, `${purpose}\0${email}`);
  return `${b64url(email)}.${sig}`;
}

async function unsubToken(env, email) { return signedToken(env, 'unsub', email); }
async function confirmToken(env, email) { return signedToken(env, 'confirm', email); }

async function parseSignedToken(env, purpose, token) {
  const raw = clampText(String(token || ''), 800);
  const dot = raw.lastIndexOf('.');
  if (dot < 1) return '';
  const email = normalizeEmail(fromB64url(raw.slice(0, dot)));
  const sig = raw.slice(dot + 1).toLowerCase();
  if (!email || !/^[0-9a-f]{64}$/.test(sig)) return '';
  const expected = await hmacHex(env.HASH_SALT, `${purpose}\0${email}`);
  if (!timingEqual(sig, expected)) return '';
  return email;
}

async function parseUnsubToken(env, token) { return parseSignedToken(env, 'unsub', token); }
async function parseConfirmToken(env, token) { return parseSignedToken(env, 'confirm', token); }

const MAIL_FROM = { email: 'book@ceph-s3.ir', name: 'Ceph: Scalable Storage' };
const TEST_MAIL_ALLOWLIST = new Set(['ramin.najarbashi@gmail.com']);

function maySendTo(env, email) {
  if (!email) return false;
  if (TEST_MAIL_ALLOWLIST.has(email)) return true;
  return env.MAIL_LIVE === '1';
}

function mailEnabled(env) {
  return !!(env.EMAIL && typeof env.EMAIL.send === 'function');
}

async function sendBookEmail(env, { to, lang, subject, text, html, unsubUrl }) {
  if (!mailEnabled(env)) return { sent: false, reason: 'no_binding' };
  if (!maySendTo(env, to)) return { sent: false, reason: 'not_allowlisted' };
  const headers = {
    'List-Unsubscribe': `<${unsubUrl}>`,
    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
    'List-Id': '<book.ceph-s3.ir>',
    Precedence: 'bulk',
    'Content-Language': lang === 'en' ? 'en' : 'fa',
  };
  try {
    await env.EMAIL.send({
      from: MAIL_FROM,
      to: { email: to },
      subject,
      text,
      html,
      headers,
    });
    return { sent: true };
  } catch (err) {
    const msg = String((err && err.message) || err).slice(0, 240);
    return { sent: false, reason: 'send_failed', error: msg };
  }
}

function confirmEmailCopy(lang, confirmUrl, unsubUrl) {
  const fa = lang !== 'en';
  if (fa) {
    return {
      subject: 'تأیید عضویت در خبرنامهٔ راهنمای جامع Ceph',
      text: `برای تأیید عضویت در خبرنامهٔ کتاب «راهنمای جامع Ceph» این پیوند را باز کنید:\n${confirmUrl}\n\nاگر این درخواست از طرف شما نبوده، این نامه را نادیده بگیرید. لغو عضویت: ${unsubUrl}`,
      html: `<p dir="rtl">برای تأیید عضویت در خبرنامهٔ کتاب «راهنمای جامع Ceph» روی این پیوند بزنید:</p><p dir="ltr"><a href="${esc(confirmUrl)}">${esc(confirmUrl)}</a></p><p dir="rtl">اگر این درخواست از طرف شما نبوده، این نامه را نادیده بگیرید.</p><p dir="rtl"><a href="${esc(unsubUrl)}">لغو عضویت</a></p>`,
    };
  }
  return {
    subject: 'Confirm your subscription to The Comprehensive Ceph Guide',
    text: `Confirm your subscription to the newsletter for The Comprehensive Ceph Guide:\n${confirmUrl}\n\nIf you did not request this, ignore this email. Unsubscribe: ${unsubUrl}`,
    html: `<p>Confirm your subscription to the newsletter for <i>The Comprehensive Ceph Guide</i>:</p><p dir="ltr"><a href="${esc(confirmUrl)}">${esc(confirmUrl)}</a></p><p>If you did not request this, ignore this email.</p><p><a href="${esc(unsubUrl)}">Unsubscribe</a></p>`,
  };
}

function releaseEmailCopy(lang, version, releaseUrl, unsubUrl) {
  const ver = version || '';
  if (lang !== 'en') {
    return {
      subject: `نسخهٔ تازه‌ی راهنمای جامع Ceph منتشر شد${ver ? ' (' + ver + ')' : ''}`,
      text: `نسخهٔ تازه‌ای از کتاب «راهنمای جامع Ceph» منتشر شد${ver ? ' (' + ver + ')' : ''}.\n${releaseUrl}\n\nلغو عضویت: ${unsubUrl}`,
      html: `<p dir="rtl">نسخهٔ تازه‌ای از کتاب «راهنمای جامع Ceph» منتشر شد${ver ? ' (' + esc(ver) + ')' : ''}.</p><p dir="ltr"><a href="${esc(releaseUrl)}">${esc(releaseUrl)}</a></p><p dir="rtl"><a href="${esc(unsubUrl)}">لغو عضویت</a></p>`,
    };
  }
  return {
    subject: `A new edition of The Comprehensive Ceph Guide is out${ver ? ' (' + ver + ')' : ''}`,
    text: `A new edition of The Comprehensive Ceph Guide has been published${ver ? ' (' + ver + ')' : ''}.\n${releaseUrl}\n\nUnsubscribe: ${unsubUrl}`,
    html: `<p>A new edition of <i>The Comprehensive Ceph Guide</i> has been published${ver ? ' (' + esc(ver) + ')' : ''}.</p><p dir="ltr"><a href="${esc(releaseUrl)}">${esc(releaseUrl)}</a></p><p><a href="${esc(unsubUrl)}">Unsubscribe</a></p>`,
  };
}

async function ensureSchema(env) {
  await env.DB.batch([
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS subscribers (
         email TEXT PRIMARY KEY,
         lang TEXT NOT NULL DEFAULT 'fa',
         ts TEXT NOT NULL,
         confirmed INTEGER NOT NULL DEFAULT 0,
         unsubscribed INTEGER NOT NULL DEFAULT 0,
         unsubscribed_ts TEXT
       )`,
    ),
    env.DB.prepare(
      `CREATE TABLE IF NOT EXISTS rate_limits (
         key TEXT PRIMARY KEY,
         count INTEGER NOT NULL,
         reset_at INTEGER NOT NULL
       )`,
    ),
  ]);
}

const PAGE_CSS = `
  :root { color-scheme: light dark; }
  body { font-family: Tahoma, "Shabnam", "Vazirmatn", sans-serif; margin: 0; padding: 1.5rem; line-height: 1.7; }
  main { max-width: 72rem; margin: 0 auto; }
  h1 { font-size: 1.4rem; margin-bottom: .3rem; }
  h2 { font-size: 1.15rem; margin: 2rem 0 .6rem; }
  .meta, .hint { opacity: .8; margin-bottom: 1.2rem; }
  .cards { display: flex; flex-wrap: wrap; gap: .8rem; margin-bottom: 1.2rem; }
  .card { border: 1px solid currentColor; border-radius: .5rem; padding: .7rem 1rem; min-width: 8rem; }
  .card b { display: block; font-size: 1.2rem; }
  table { width: 100%; border-collapse: collapse; margin-bottom: 1rem; }
  th, td { text-align: right; border-bottom: 1px solid color-mix(in srgb, currentColor 25%, transparent); padding: .45rem .4rem; }
  th { font-weight: 700; }
  .logout, .exports { margin-top: 1.5rem; }
  .err { color: #b00020; }
  .sr-only { position: absolute !important; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); }
`;

function pageShell(title, body, extraHead = '') {
  return `<!DOCTYPE html>
<html lang="fa" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${esc(title)}</title>
<style>${PAGE_CSS}
  main.narrow { max-width: 36rem; margin: 8vh auto; }
  input, button { font: inherit; }
  input { width: 100%; box-sizing: border-box; padding: .5rem .6rem; }
  button { margin-top: 1rem; padding: .45rem 1rem; cursor: pointer; }
</style>${extraHead}
</head>
<body>
${body}
</body>
</html>`;
}

function loginPage(error) {
  const msg = error ? `<p class="err">${esc(error)}</p>` : '';
  const html = pageShell('ورود به خلاصه آمار', `<main class="narrow">
  <h1>خلاصه بازخورد، خبرنامه و بازدید</h1>
  <p>برای دیدن آمار، کلید دسترسی را وارد کنید.</p>
  ${msg}
  <form method="post" action="/stats">
    <label for="key">کلید دسترسی</label>
    <input id="key" name="key" type="password" autocomplete="current-password" required>
    <button type="submit">ورود</button>
  </form>
</main>`);
  return htmlResp(error ? 401 : 200, html);
}

function rowsTable(headers, rows, emptyCols, emptyText) {
  const head = `<tr>${headers.map((h) => `<th>${esc(h)}</th>`).join('')}</tr>`;
  const body = rows.length
    ? rows.map((r) => `<tr>${r.map((c) => `<td>${c}</td>`).join('')}</tr>`).join('')
    : `<tr><td colspan="${emptyCols}">${esc(emptyText)}</td></tr>`;
  return `<table><thead>${head}</thead><tbody>${body}</tbody></table>`;
}

function langBucket(path) {
  const p = String(path || '').toLowerCase();
  if (p === '/fa' || p.startsWith('/fa/') || p.startsWith('/fa?')) return 'fa';
  if (p === '/en' || p.startsWith('/en/') || p.startsWith('/en?')) return 'en';
  return 'other';
}

function visitsSection(visits) {
  if (!visits || visits.available === false) {
    const reason = visits && visits.reason;
    let msg = 'آمار بازدید هنوز در دسترس نیست.';
    if (reason === 'no_token') {
      msg = 'آمار بازدید از Cloudflare Web Analytics می‌آید. برای نمایش آن، یک API Token با مجوز Account Analytics: Read در داشبورد Cloudflare (My Profile → API Tokens) بسازید، حساب همین پروژه را انتخاب کنید، و توکن را به‌عنوان secret با نام CF_ANALYTICS_TOKEN روی Worker book-feedback قرار دهید.';
    } else if (visits && visits.error) {
      msg = `خواندن آمار بازدید ناموفق بود: ${visits.error}`;
    }
    return `<section>
      <h2>آمار بازدید سایت</h2>
      <p class="hint">${esc(msg)}</p>
    </section>`;
  }
  const totals = visits.totals || { pageviews: 0, visits: 0 };
  const daily = (visits.daily || []).map((r) => [esc(r.date), r.visits, r.pageviews]);
  const pages = (visits.pages || []).map((r) => [esc(r.path || '/'), r.visits, r.pageviews]);
  const countries = (visits.countries || []).map((r) => [esc(r.country || '—'), r.visits, r.pageviews]);
  const referrers = (visits.referrers || []).map((r) => [esc(r.referrer === '' || r.referrer == null ? 'مستقیم' : r.referrer), r.visits, r.pageviews]);
  const langs = visits.langs || { fa: { visits: 0, pageviews: 0 }, en: { visits: 0, pageviews: 0 }, other: { visits: 0, pageviews: 0 } };
  const cached = visits.cached ? ' · نتایج تا ۱۰ دقیقه کش می‌شوند' : ' · تازه‌خوانی‌شده، تا ۱۰ دقیقه کش می‌شود';
  return `<section>
    <h2>آمار بازدید سایت</h2>
    <p class="meta">۳۰ روز گذشته (روزهای UTC، با امروز) · منبع: Cloudflare Web Analytics (RUM)${esc(cached)}</p>
    <div class="cards">
      <div class="card"><span>بازدیدها</span><b>${totals.visits}</b></div>
      <div class="card"><span>نمایش صفحات</span><b>${totals.pageviews}</b></div>
      <div class="card"><span>فارسی</span><b>${(langs.fa && langs.fa.pageviews) || 0}</b></div>
      <div class="card"><span>انگلیسی</span><b>${(langs.en && langs.en.pageviews) || 0}</b></div>
    </div>
    <h3>بازدید روزانه</h3>
    ${rowsTable(['روز', 'بازدید', 'نمایش'], daily, 3, 'در این بازه داده‌ای نیست.')}
    <h3>صفحات پربازدید</h3>
    ${rowsTable(['صفحه', 'بازدید', 'نمایش'], pages, 3, 'در این بازه داده‌ای نیست.')}
    <h3>کشورها</h3>
    ${rowsTable(['کشور', 'بازدید', 'نمایش'], countries, 3, 'در این بازه داده‌ای نیست.')}
    <h3>ارجاع‌دهنده‌ها</h3>
    ${rowsTable(['منبع', 'بازدید', 'نمایش'], referrers, 3, 'در این بازه داده‌ای نیست.')}
    <h3>فارسی در برابر انگلیسی</h3>
    ${rowsTable(['زبان', 'بازدید', 'نمایش'], [
      ['فارسی (/fa/)', langs.fa.visits || 0, langs.fa.pageviews || 0],
      ['انگلیسی (/en/)', langs.en.visits || 0, langs.en.pageviews || 0],
      ['سایر', langs.other.visits || 0, langs.other.pageviews || 0],
    ], 3, 'در این بازه داده‌ای نیست.')}
  </section>`;
}

function statsHtml(feedback, subs, visits, generatedAt) {
  const totalYes = feedback.reduce((s, r) => s + r.yes, 0);
  const totalNo = feedback.reduce((s, r) => s + r.no, 0);
  const total = totalYes + totalNo;
  const pctAll = total ? Math.round((1000 * totalYes) / total) / 10 : 0;
  const fbRows = feedback.map((r) => {
    const n = r.yes + r.no;
    const pct = n ? Math.round((1000 * r.yes) / n) / 10 : 0;
    return [esc(r.page), esc(r.section), esc(r.lang), r.yes, r.no, `${pct}٪`, n];
  });
  const html = pageShell('خلاصه بازخورد، خبرنامه و بازدید', `<main>
  <h1>خلاصه بازخورد، خبرنامه و بازدید</h1>
  <p class="meta">۳۰ روز گذشته برای رأی‌ها و بازدیدها · به‌روز شده در ${esc(generatedAt)}</p>

  <section>
    <h2>بازخورد بخش‌های کتاب</h2>
    <div class="cards">
      <div class="card"><span>کل رأی‌ها</span><b>${total}</b></div>
      <div class="card"><span>مفید</span><b>${totalYes}</b></div>
      <div class="card"><span>مفید نبود</span><b>${totalNo}</b></div>
      <div class="card"><span>درصد مفید</span><b>${pctAll}٪</b></div>
    </div>
    ${rowsTable(['صفحه', 'بخش', 'زبان', 'مفید', 'مفید نبود', 'درصد مفید', 'تعداد رأی'], fbRows, 7, 'هنوز رأیی در ۳۰ روز گذشته ثبت نشده است.')}
  </section>

  <section>
    <h2>خبرنامه</h2>
    <p class="hint">عضویت با ایمیل تأیید (double opt-in) انجام می‌شود وقتی سرویس نامه فعال باشد؛ تا آن زمان confirmed ممکن است صفر بماند.</p>
    <div class="cards">
      <div class="card"><span>اعضای فعال</span><b>${subs.active}</b></div>
      <div class="card"><span>لغو عضویت</span><b>${subs.unsubscribed}</b></div>
      <div class="card"><span>کل ثبت‌ها</span><b>${subs.total}</b></div>
      <div class="card"><span>تأییدشده</span><b>${subs.confirmed}</b></div>
    </div>
    <p class="exports"><a href="/stats/subscribers.csv">دانلود CSV اعضا</a></p>
  </section>

  ${visitsSection(visits)}

  <p class="logout"><a href="/stats?logout=1">خروج</a></p>
</main>`);
  return htmlResp(200, html);
}

function subscribeResultPage(lang, email, unsubUrl, already, mailed) {
  const fa = lang !== 'en';
  const title = fa ? 'عضویت در خبرنامه' : 'Newsletter subscription';
  const dir = fa ? 'rtl' : 'ltr';
  const heading = already
    ? (fa ? 'این نشانی پیش‌تر ثبت شده بود' : 'This address was already on the list')
    : (fa ? 'نشانی شما ثبت شد' : 'Your address has been saved');
  const savedFa = email
    ? `<p>ایمیل <b dir="ltr">${esc(email)}</b> برای خبر انتشار نسخه‌های تازه‌ی کتاب ذخیره شد.</p>`
    : '<p>درخواست عضویت دریافت شد.</p>';
  const savedEn = email
    ? `<p>The address <b dir="ltr">${esc(email)}</b> has been stored for notices about new editions of the book.</p>`
    : '<p>The subscription request was received.</p>';
  const mailNoteFa = mailed
    ? '<p>یک ایمیل تأیید به این نشانی فرستاده شد. لطفاً پیوند داخل نامه را باز کنید تا عضویت قطعی شود.</p>'
    : '<p>ایمیل تأیید عضویت فعلاً فرستاده نشد (سرویس نامه هنوز برای ارسال عمومی آماده نیست). نشانی شما ذخیره شد و وقتی ارسال فعال شود برای تأیید با شما تماس گرفته می‌شود.</p>';
  const mailNoteEn = mailed
    ? '<p>A confirmation email was sent to this address. Open the link in that message to finish subscribing.</p>'
    : '<p>A confirmation email was not sent yet (the mail service is not enabled for general sending). Your address has been stored, and you will be asked to confirm when sending is turned on.</p>';
  const body = fa
    ? `${savedFa}
       ${mailNoteFa}
       <p>برای لغو عضویت از این پیوند استفاده کنید:</p>
       <p dir="ltr"><a href="${esc(unsubUrl)}">${esc(unsubUrl)}</a></p>`
    : `${savedEn}
       ${mailNoteEn}
       <p>To unsubscribe, use this link:</p>
       <p dir="ltr"><a href="${esc(unsubUrl)}">${esc(unsubUrl)}</a></p>`;
  const html = `<!DOCTYPE html>
<html lang="${fa ? 'fa' : 'en'}" dir="${dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${esc(title)}</title>
<style>${PAGE_CSS}</style>
</head>
<body>
<main class="narrow" style="max-width:36rem;margin:8vh auto">
  <h1>${esc(heading)}</h1>
  ${body}
</main>
</body>
</html>`;
  return htmlResp(200, html);
}

function unsubPage(ok, lang, email) {
  const fa = lang !== 'en';
  const title = fa ? 'لغو عضویت' : 'Unsubscribe';
  const dir = fa ? 'rtl' : 'ltr';
  let body;
  if (!ok) {
    body = fa
      ? '<h1>پیوند نامعتبر است</h1><p>این پیوند لغو عضویت معتبر نیست یا منقضی شده است.</p>'
      : '<h1>Invalid link</h1><p>This unsubscribe link is invalid or has expired.</p>';
  } else {
    body = fa
      ? `<h1>عضویت لغو شد</h1><p>نشانی <b dir="ltr">${esc(email)}</b> از فهرست خبرنامه خارج شد.</p>`
      : `<h1>You have been unsubscribed</h1><p>The address <b dir="ltr">${esc(email)}</b> has been removed from the newsletter list.</p>`;
  }
  const html = `<!DOCTYPE html>
<html lang="${fa ? 'fa' : 'en'}" dir="${dir}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${esc(title)}</title>
<style>${PAGE_CSS}</style>
</head>
<body>
<main class="narrow" style="max-width:36rem;margin:8vh auto">${body}</main>
</body>
</html>`;
  return htmlResp(ok ? 200 : 400, html);
}

async function loadStats(env) {
  const res = await env.DB.prepare(
    `SELECT page, section, lang,
            SUM(CASE WHEN helpful = 1 THEN 1 ELSE 0 END) AS yes,
            SUM(CASE WHEN helpful = 0 THEN 1 ELSE 0 END) AS no
       FROM votes
      WHERE day >= date('now', '-29 days')
      GROUP BY page, section, lang
      ORDER BY CAST(yes AS REAL) / (yes + no) ASC, no DESC, page, section, lang`,
  ).all();
  return (res.results || []).map((r) => ({
    page: r.page,
    section: r.section,
    lang: r.lang,
    yes: Number(r.yes) || 0,
    no: Number(r.no) || 0,
  }));
}

async function loadSubscriberStats(env) {
  await ensureSchema(env);
  const res = await env.DB.prepare(
    `SELECT
        COUNT(*) AS total,
        SUM(CASE WHEN unsubscribed = 0 THEN 1 ELSE 0 END) AS active,
        SUM(CASE WHEN unsubscribed = 1 THEN 1 ELSE 0 END) AS unsubscribed,
        SUM(CASE WHEN confirmed = 1 AND unsubscribed = 0 THEN 1 ELSE 0 END) AS confirmed
       FROM subscribers`,
  ).first();
  return {
    total: Number(res && res.total) || 0,
    active: Number(res && res.active) || 0,
    unsubscribed: Number(res && res.unsubscribed) || 0,
    confirmed: Number(res && res.confirmed) || 0,
  };
}

const WINDOW_DAYS = 30;

// UTC calendar days of the window, oldest first, ending with today (partial).
function windowDays(now) {
  const out = [];
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  for (let i = WINDOW_DAYS - 1; i >= 0; i--) out.push(new Date(today - i * 86400000).toISOString().slice(0, 10));
  return out;
}

// Merge per-day groups into top-N rows keyed by one dimension.
function mergeGroups(dayRows, dim, limit) {
  const m = new Map();
  for (const rows of dayRows) {
    for (const r of rows || []) {
      const key = (r.dimensions && r.dimensions[dim]) || '';
      const cur = m.get(key) || { key, pageviews: 0, visits: 0 };
      cur.pageviews += Number(r.count) || 0;
      cur.visits += Number((r.sum && r.sum.visits)) || 0;
      m.set(key, cur);
    }
  }
  return [...m.values()].sort((x, y) => y.pageviews - x.pageviews || y.visits - x.visits).slice(0, limit);
}

// Cloudflare RUM data is sampled adaptively, and a wide time range is sampled far more
// coarsely (counts come back rounded to tens, and a 30-day query can be off by 3x for a
// quiet day). So ask one query per UTC day, which keeps the sampling fine, and combine
// the days here. Empty days are zero-filled and today is included.
async function fetchVisits(env) {
  const token = env.CF_ANALYTICS_TOKEN || '';
  if (!token) return { available: false, reason: 'no_token' };
  const accountTag = env.CF_ACCOUNT_ID || ACCOUNT_ID_DEFAULT;
  const siteTag = env.CF_SITE_TAG || SITE_TAG_DEFAULT;
  const days = windowDays(new Date());
  const group = (alias, d, dim, orderBy) => {
    const next = new Date(Date.parse(`${d}T00:00:00Z`) + 86400000).toISOString().slice(0, 10);
    return `${alias}: rumPageloadEventsAdaptiveGroups(
          limit: 200
          filter: { siteTag: $siteTag, datetime_geq: "${d}T00:00:00Z", datetime_lt: "${next}T00:00:00Z" }
          orderBy: [${orderBy}]
        ) { count sum { visits } dimensions { ${dim} } }`;
  };
  // Cloudflare caps the nodes per request, so one request per dimension (30 days each).
  const runKind = async (prefix, dim) => {
    const fields = days.map((d, i) => group(`${prefix}${i}`, d, dim, 'count_DESC'));
    const query = `query BookVisits($accountTag: String!, $siteTag: String!) {
    viewer { accounts(filter: { accountTag: $accountTag }) { ${fields.join('\n')} } }
  }`;
    const res = await fetch('https://api.cloudflare.com/client/v4/graphql', {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${token}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ query, variables: { accountTag, siteTag } }),
    });
    const raw = await res.text();
    let data;
    try { data = JSON.parse(raw); } catch {
      return { error: `پاسخ غیرقابل‌خواندن از API (${res.status})` };
    }
    if (!res.ok || data.errors) {
      const msg = (data.errors && data.errors[0] && data.errors[0].message)
        ? String(data.errors[0].message)
        : `HTTP ${res.status}`;
      return { error: msg.slice(0, 240) };
    }
    const acc = data.data && data.data.viewer && data.data.viewer.accounts && data.data.viewer.accounts[0];
    if (!acc) return { error: 'حساب یا داده‌ای برنگشت.' };
    return { rows: days.map((_, i) => acc[`${prefix}${i}`] || []) };
  };
  const [pRes, cRes, rRes] = await Promise.all([
    runKind('p', 'requestPath'),
    runKind('c', 'countryName'),
    runKind('r', 'refererHost'),
  ]);
  const failed = [pRes, cRes, rRes].find((x) => x.error);
  if (failed) return { available: false, error: failed.error };
  const pathRows = pRes.rows;
  const daily = days.map((date, i) => ({
    date,
    pageviews: pathRows[i].reduce((s, r) => s + (Number(r.count) || 0), 0),
    visits: pathRows[i].reduce((s, r) => s + (Number(r.sum && r.sum.visits) || 0), 0),
  }));
  const pages = mergeGroups(pathRows, 'requestPath', 20).map((r) => ({ path: r.key, pageviews: r.pageviews, visits: r.visits }));
  const countries = mergeGroups(cRes.rows, 'countryName', 15).map((r) => ({ country: r.key, pageviews: r.pageviews, visits: r.visits }));
  const referrers = mergeGroups(rRes.rows, 'refererHost', 15).map((r) => ({ referrer: r.key, pageviews: r.pageviews, visits: r.visits }));
  const langs = { fa: { visits: 0, pageviews: 0 }, en: { visits: 0, pageviews: 0 }, other: { visits: 0, pageviews: 0 } };
  for (const rows of pathRows) {
    for (const r of rows) {
      const bucket = langBucket((r.dimensions && r.dimensions.requestPath) || '');
      langs[bucket].pageviews += Number(r.count) || 0;
      langs[bucket].visits += Number(r.sum && r.sum.visits) || 0;
    }
  }
  const totals = daily.reduce((s, r) => ({ pageviews: s.pageviews + r.pageviews, visits: s.visits + r.visits }), { pageviews: 0, visits: 0 });
  return {
    available: true,
    window_days: WINDOW_DAYS,
    timezone: 'UTC',
    source: 'cloudflare-web-analytics',
    totals,
    daily,
    pages,
    countries,
    referrers,
    langs,
  };
}

async function loadVisits(env) {
  const cache = caches.default;
  const cacheReq = new Request('https://feedback.ceph-s3.ir/__cache/visits-v2');
  try {
    const hit = await cache.match(cacheReq);
    if (hit) {
      const data = await hit.json();
      return { ...data, cached: true };
    }
  } catch { /* ignore cache miss */ }
  const fresh = await fetchVisits(env);
  fresh.generated_at = new Date().toISOString();
  try {
    if (fresh.available !== false || fresh.reason === 'no_token') {
      const ttl = fresh.reason === 'no_token' ? 60 : Math.floor(VISITS_TTL_MS / 1000);
      await cache.put(cacheReq, new Response(JSON.stringify(fresh), {
        headers: { 'Content-Type': 'application/json', 'Cache-Control': `max-age=${ttl}` },
      }));
    }
  } catch { /* cache put is best-effort */ }
  return { ...fresh, cached: false };
}

async function handleVote(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    if (!originAllowed(origin)) return empty(403, origin);
    return empty(204, origin);
  }
  if (request.method !== 'POST') return empty(405, origin, { Allow: 'POST, OPTIONS' });
  if (!originAllowed(origin)) return empty(403, origin);

  const length = Number(request.headers.get('Content-Length') || '0');
  if (length > MAX_BODY) return jsonResp(413, { error: 'too large' }, origin);

  const raw = await request.text();
  if (!raw || raw.length > MAX_BODY) return jsonResp(413, { error: 'too large' }, origin);

  let data;
  try { data = JSON.parse(raw); } catch { return jsonResp(400, { error: 'invalid json' }, origin); }
  if (!data || typeof data !== 'object') return jsonResp(400, { error: 'invalid json' }, origin);

  const props = (data.props && typeof data.props === 'object') ? data.props : {};
  const event = clampText(data.event || '', 64);
  if (event && event !== 'section-feedback') return jsonResp(400, { error: 'ignored event' }, origin);

  const page = clampText(props.page || data.page || '', MAX_PAGE);
  const section = clampText(props.section || '', MAX_SECTION);
  const lang = clampText(props.lang || data.lang || '', MAX_LANG).toLowerCase();
  const helpful = parseHelpful(props.helpful);
  if (!page || !section || !lang || !/^[a-z]{2,8}$/.test(lang) || helpful === null) {
    return jsonResp(400, { error: 'invalid fields' }, origin);
  }

  const now = new Date();
  const ts = now.toISOString();
  const day = ts.slice(0, 10);
  const visitor = await visitorKey(request, env, day);

  await env.DB.prepare(
    `INSERT INTO votes (ts, day, lang, page, section, helpful, visitor)
     VALUES (?, ?, ?, ?, ?, ?, ?)
     ON CONFLICT(visitor, page, section, day)
     DO UPDATE SET helpful = excluded.helpful, ts = excluded.ts, lang = excluded.lang`,
  ).bind(ts, day, lang, page, section, helpful, visitor).run();

  return empty(204, origin);
}

async function rateLimited(env, key, limit, windowMs) {
  const now = Date.now();
  const row = await env.DB.prepare('SELECT count, reset_at FROM rate_limits WHERE key = ?').bind(key).first();
  if (!row || Number(row.reset_at) <= now) {
    await env.DB.prepare(
      'INSERT INTO rate_limits (key, count, reset_at) VALUES (?, 1, ?) ON CONFLICT(key) DO UPDATE SET count = 1, reset_at = excluded.reset_at',
    ).bind(key, now + windowMs).run();
    return false;
  }
  if (Number(row.count) >= limit) return true;
  await env.DB.prepare('UPDATE rate_limits SET count = count + 1 WHERE key = ?').bind(key).run();
  return false;
}

async function parseSubscribeBody(request) {
  const contentType = request.headers.get('Content-Type') || '';
  const fields = { email: '', lang: '', website: '' };
  if (contentType.includes('application/json')) {
    const raw = await request.text();
    if (!raw || raw.length > MAX_BODY) return { tooLarge: true };
    let data;
    try { data = JSON.parse(raw); } catch { return { invalid: true }; }
    if (!data || typeof data !== 'object') return { invalid: true };
    fields.email = data.email || '';
    fields.lang = data.lang || '';
    fields.website = data.website || data.url || '';
    return fields;
  }
  if (contentType.includes('application/x-www-form-urlencoded') || contentType.includes('multipart/form-data')) {
    const form = await request.formData();
    fields.email = form.get('email') || '';
    fields.lang = form.get('lang') || '';
    fields.website = form.get('website') || form.get('url') || '';
    return fields;
  }
  const raw = await request.text();
  if (!raw || raw.length > MAX_BODY) return { tooLarge: true };
  const params = new URLSearchParams(raw);
  fields.email = params.get('email') || '';
  fields.lang = params.get('lang') || '';
  fields.website = params.get('website') || params.get('url') || '';
  return fields;
}

async function handleSubscribe(request, env) {
  const origin = request.headers.get('Origin') || '';
  if (request.method === 'OPTIONS') {
    if (!originAllowed(origin)) return empty(403, origin);
    return empty(204, origin);
  }
  if (request.method !== 'POST') return empty(405, origin, { Allow: 'POST, OPTIONS' });
  if (!originAllowed(origin)) return empty(403, origin);

  const length = Number(request.headers.get('Content-Length') || '0');
  if (length > MAX_BODY) return jsonResp(413, { error: 'too large' }, origin);

  await ensureSchema(env);
  const fields = await parseSubscribeBody(request);
  if (fields.tooLarge) return jsonResp(413, { error: 'too large' }, origin);
  if (fields.invalid) return jsonResp(400, { error: 'invalid body' }, origin);

  const lang = normalizeLang(fields.lang);
  // Honeypot: pretend success, store nothing.
  if (clampText(String(fields.website || ''), 200)) {
    const unsubUrl = `${new URL(request.url).origin}/v1/unsubscribe`;
    return subscribeResultPage(lang, '', unsubUrl, false);
  }

  const email = normalizeEmail(fields.email);
  if (!email) return jsonResp(400, { error: 'invalid email' }, origin);

  const hour = new Date().toISOString().slice(0, 13);
  const visitor = await visitorKey(request, env, hour);
  if (await rateLimited(env, `sub:${visitor}`, SUBSCRIBE_LIMIT, 60 * 60 * 1000)) {
    return jsonResp(429, { error: 'too many requests' }, origin, { 'Retry-After': '3600' });
  }

  const ts = new Date().toISOString();
  const existing = await env.DB.prepare('SELECT email, unsubscribed, confirmed FROM subscribers WHERE email = ?').bind(email).first();
  const already = !!(existing && Number(existing.unsubscribed) === 0);
  const alreadyConfirmed = already && Number(existing.confirmed) === 1;

  await env.DB.prepare(
    `INSERT INTO subscribers (email, lang, ts, confirmed, unsubscribed, unsubscribed_ts)
     VALUES (?, ?, ?, 0, 0, NULL)
     ON CONFLICT(email) DO UPDATE SET
       lang = excluded.lang,
       ts = CASE WHEN subscribers.unsubscribed = 1 THEN excluded.ts ELSE subscribers.ts END,
       confirmed = CASE WHEN subscribers.unsubscribed = 1 THEN 0 ELSE subscribers.confirmed END,
       unsubscribed = 0,
       unsubscribed_ts = NULL`,
  ).bind(email, lang, ts).run();

  const siteOrigin = new URL(request.url).origin;
  const unsubUrl = `${siteOrigin}/v1/unsubscribe?t=${encodeURIComponent(await unsubToken(env, email))}`;
  let mailed = false;
  if (!alreadyConfirmed) {
    const confirmUrl = `${siteOrigin}/v1/confirm?t=${encodeURIComponent(await confirmToken(env, email))}`;
    const copy = confirmEmailCopy(lang, confirmUrl, unsubUrl);
    const result = await sendBookEmail(env, { to: email, lang, subject: copy.subject, text: copy.text, html: copy.html, unsubUrl });
    mailed = !!result.sent;
  }
  return subscribeResultPage(lang, email, unsubUrl, already, mailed);
}

function confirmResultPage(lang, email, kind) {
  const fa = lang !== 'en';
  let title, body;
  if (kind === 'ok') {
    title = fa ? 'عضویت تأیید شد' : 'Subscription confirmed';
    body = fa
      ? `<h1>عضویت تأیید شد</h1><p>نشانی <b dir="ltr">${esc(email)}</b> تأیید شد. وقتی نسخهٔ تازه‌ای از کتاب منتشر شود خبرتان می‌کنیم.</p>`
      : `<h1>Subscription confirmed</h1><p>The address <b dir="ltr">${esc(email)}</b> is confirmed. We will write when a new edition of the book is published.</p>`;
  } else if (kind === 'unsubscribed') {
    title = fa ? 'این نشانی لغو عضویت شده است' : 'This address is unsubscribed';
    body = fa
      ? `<h1>این نشانی لغو عضویت شده است</h1><p>نشانی <b dir="ltr">${esc(email)}</b> قبلاً از فهرست خبرنامه خارج شده و تأیید نشد.</p>`
      : `<h1>This address is unsubscribed</h1><p>The address <b dir="ltr">${esc(email)}</b> was already removed from the list and was not confirmed.</p>`;
  } else {
    title = fa ? 'پیوند تأیید نامعتبر است' : 'Invalid confirmation link';
    body = fa
      ? '<h1>پیوند تأیید نامعتبر است</h1><p>این پیوند تأیید عضویت معتبر نیست یا منقضی شده است.</p>'
      : '<h1>Invalid confirmation link</h1><p>This confirmation link is invalid or has expired.</p>';
  }
  const html = `<!DOCTYPE html>
<html lang="${fa ? 'fa' : 'en'}" dir="${fa ? 'rtl' : 'ltr'}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>${esc(title)}</title>
<style>${PAGE_CSS}</style>
</head>
<body>
<main class="narrow" style="max-width:36rem;margin:8vh auto">${body}</main>
</body>
</html>`;
  return htmlResp(kind === 'ok' ? 200 : 400, html);
}

async function handleConfirm(request, env) {
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, HEAD' } });
  }
  const url = new URL(request.url);
  const token = url.searchParams.get('t') || url.searchParams.get('token') || '';
  await ensureSchema(env);
  const email = await parseConfirmToken(env, token);
  if (!email) return confirmResultPage('fa', '', 'invalid');
  const row = await env.DB.prepare('SELECT lang, unsubscribed FROM subscribers WHERE email = ?').bind(email).first();
  const lang = row ? normalizeLang(row.lang) : 'fa';
  if (!row) return confirmResultPage(lang, email, 'invalid');
  if (Number(row.unsubscribed) === 1) return confirmResultPage(lang, email, 'unsubscribed');
  await env.DB.prepare('UPDATE subscribers SET confirmed = 1 WHERE email = ?').bind(email).run();
  return confirmResultPage(lang, email, 'ok');
}

function hookAuthorized(request, env) {
  const expected = env.MAIL_HOOK_KEY || '';
  if (!expected) return false;
  const auth = request.headers.get('Authorization') || '';
  const bearer = auth.toLowerCase().startsWith('bearer ') ? auth.slice(7).trim() : '';
  const headerKey = request.headers.get('X-Mail-Key') || '';
  return [bearer, headerKey].some((v) => v && timingEqual(v, expected));
}

async function handleNotifyRelease(request, env) {
  if (request.method === 'OPTIONS') return empty(204, request.headers.get('Origin') || '');
  if (request.method !== 'POST') return jsonResp(405, { error: 'method not allowed' }, '', { Allow: 'POST, OPTIONS' });
  if (!hookAuthorized(request, env)) return jsonResp(401, { error: 'unauthorized' }, '');
  await ensureSchema(env);
  let data = {};
  try { data = JSON.parse(await request.text() || '{}'); } catch { return jsonResp(400, { error: 'invalid json' }, ''); }
  const version = clampText(String((data && data.version) || ''), 32);
  const releaseUrl = clampText(String((data && (data.url || data.release_url)) || 'https://book.ceph-s3.ir'), 500)
    || 'https://book.ceph-s3.ir';
  if (releaseUrl && !/^https:\/\//i.test(releaseUrl)) return jsonResp(400, { error: 'url must be https' }, '');
  const dryRun = data && data.dry_run === true;
  const siteOrigin = new URL(request.url).origin;
  const rows = await env.DB.prepare(
    `SELECT email, lang FROM subscribers
      WHERE confirmed = 1 AND unsubscribed = 0
      ORDER BY ts, email`,
  ).all();
  const recipients = (rows.results || []).map((r) => ({ email: r.email, lang: normalizeLang(r.lang) }));
  const sent = [];
  const skipped = [];
  const failed = [];
  if (!dryRun) {
    for (const r of recipients) {
      if (!maySendTo(env, r.email)) { skipped.push({ email: r.email, reason: 'not_allowlisted' }); continue; }
      const unsubUrl = `${siteOrigin}/v1/unsubscribe?t=${encodeURIComponent(await unsubToken(env, r.email))}`;
      const copy = releaseEmailCopy(r.lang, version, releaseUrl, unsubUrl);
      const result = await sendBookEmail(env, { to: r.email, lang: r.lang, subject: copy.subject, text: copy.text, html: copy.html, unsubUrl });
      if (result.sent) sent.push(r.email);
      else failed.push({ email: r.email, reason: result.reason || 'send_failed' });
    }
  } else {
    for (const r of recipients) {
      if (!maySendTo(env, r.email)) skipped.push({ email: r.email, reason: 'not_allowlisted' });
      else sent.push(r.email);
    }
  }
  return jsonResp(200, {
    version,
    url: releaseUrl,
    dry_run: dryRun,
    mail_enabled: mailEnabled(env),
    mail_live: env.MAIL_LIVE === '1',
    candidates: recipients.length,
    sent: sent.length,
    skipped: skipped.length,
    failed: failed.length,
  }, '');
}

async function handleAlerts(request, env) {
  const url = new URL(request.url);
  let since = url.searchParams.get('since') || '';
  if (since) {
    const d = new Date(since);
    if (Number.isNaN(d.getTime())) return jsonResp(400, { error: 'invalid since' }, '');
    since = d.toISOString();
  } else {
    since = new Date(Date.now() - 24 * 3600 * 1000).toISOString();
  }
  const until = new Date().toISOString();
  const down = await env.DB.prepare(
    `SELECT page, section, lang, COUNT(*) AS count, MAX(ts) AS last_ts
       FROM votes
      WHERE helpful = 0 AND ts >= ?
      GROUP BY page, section, lang
      ORDER BY count DESC, last_ts DESC, page, section, lang`,
  ).bind(since).all();
  await ensureSchema(env);
  const subs = await env.DB.prepare(
    `SELECT email, lang, ts, confirmed, unsubscribed
       FROM subscribers
      WHERE ts >= ?
      ORDER BY ts DESC, email`,
  ).bind(since).all();
  return new Response(JSON.stringify({
    since,
    until,
    generated_at: until,
    downvotes: (down.results || []).map((r) => ({
      page: r.page,
      section: r.section,
      lang: r.lang,
      count: Number(r.count) || 0,
      last_ts: r.last_ts,
    })),
    new_subscribers: {
      count: (subs.results || []).length,
      rows: (subs.results || []).map((r) => ({
        email: r.email,
        lang: r.lang,
        ts: r.ts,
        confirmed: Number(r.confirmed) || 0,
        unsubscribed: Number(r.unsubscribed) || 0,
      })),
    },
  }), {
    status: 200,
    headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow' },
  });
}

async function handleUnsubscribe(request, env) {
  if (request.method !== 'GET' && request.method !== 'HEAD' && request.method !== 'POST') {
    return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, HEAD, POST' } });
  }
  const url = new URL(request.url);
  let token = url.searchParams.get('t') || url.searchParams.get('token') || '';
  if (!token && request.method === 'POST') {
    try {
      const ct = request.headers.get('Content-Type') || '';
      if (ct.includes('application/x-www-form-urlencoded') || ct.includes('multipart/form-data')) {
        const form = await request.formData();
        token = String(form.get('t') || form.get('token') || '');
      }
    } catch { /* ignore */ }
  }
  await ensureSchema(env);
  const email = await parseUnsubToken(env, token);
  if (!email) return unsubPage(false, 'fa', '');
  const row = await env.DB.prepare('SELECT lang FROM subscribers WHERE email = ?').bind(email).first();
  const lang = row ? normalizeLang(row.lang) : 'fa';
  const ts = new Date().toISOString();
  await env.DB.prepare(
    `UPDATE subscribers SET unsubscribed = 1, unsubscribed_ts = ?
      WHERE email = ? AND unsubscribed = 0`,
  ).bind(ts, email).run();
  return unsubPage(true, lang, email);
}

async function handleStatsLogin(request, env) {
  const contentType = request.headers.get('Content-Type') || '';
  let key = '';
  if (contentType.includes('application/x-www-form-urlencoded') || contentType.includes('multipart/form-data')) {
    const form = await request.formData();
    key = String(form.get('key') || '');
  } else {
    const raw = await request.text();
    try {
      const data = JSON.parse(raw);
      key = String((data && data.key) || '');
    } catch {
      key = new URLSearchParams(raw).get('key') || '';
    }
  }
  if (!timingEqual(key, env.STATS_KEY || '')) return loginPage('کلید نادرست است.');
  const cookie = `book_stats=${encodeURIComponent(key)}; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=2592000`;
  return new Response(null, {
    status: 303,
    headers: {
      Location: '/stats',
      'Set-Cookie': cookie,
      'Cache-Control': 'no-store',
    },
  });
}

function csvEscape(value) {
  const s = String(value ?? '');
  if (/[",\r\n]/.test(s)) return `"${s.replace(/"/g, '""')}"`;
  return s;
}

async function handleSubscribersCsv(request, env) {
  await ensureSchema(env);
  const res = await env.DB.prepare(
    `SELECT email, lang, ts, confirmed, unsubscribed, unsubscribed_ts
       FROM subscribers
      ORDER BY ts DESC, email`,
  ).all();
  const lines = ['email,lang,ts,confirmed,unsubscribed,unsubscribed_ts'];
  for (const r of (res.results || [])) {
    lines.push([r.email, r.lang, r.ts, r.confirmed, r.unsubscribed, r.unsubscribed_ts || '']
      .map(csvEscape).join(','));
  }
  const body = lines.join('\r\n') + '\r\n';
  return new Response(body, {
    status: 200,
    headers: {
      'Content-Type': 'text/csv; charset=utf-8',
      'Content-Disposition': 'attachment; filename="subscribers.csv"',
      'Cache-Control': 'no-store',
      'X-Robots-Tag': 'noindex, nofollow',
    },
  });
}

async function handleStats(request, env) {
  const url = new URL(request.url);
  const wantsJson = url.pathname === '/stats.json' || url.pathname === '/stats/alerts.json' || (request.headers.get('Accept') || '').includes('application/json');
  const wantsCsv = url.pathname === '/stats/subscribers.csv';

  if (url.searchParams.get('logout') === '1') {
    return new Response(null, {
      status: 303,
      headers: {
        Location: '/stats',
        'Set-Cookie': 'book_stats=; Path=/; HttpOnly; Secure; SameSite=Strict; Max-Age=0',
        'Cache-Control': 'no-store',
      },
    });
  }

  if (request.method === 'POST' && url.pathname === '/stats') return handleStatsLogin(request, env);
  if (request.method !== 'GET' && request.method !== 'HEAD') {
    return new Response('Method Not Allowed', { status: 405, headers: { Allow: 'GET, HEAD, POST' } });
  }
  if (!authorized(request, env)) {
    if (wantsJson || wantsCsv) {
      return new Response(JSON.stringify({ error: 'unauthorized' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json; charset=utf-8', 'WWW-Authenticate': 'Bearer', 'Cache-Control': 'no-store' },
      });
    }
    return loginPage('');
  }

  if (wantsCsv) return handleSubscribersCsv(request, env);
  if (url.pathname === '/stats/alerts.json') return handleAlerts(request, env);

  const [rows, subs, visits] = await Promise.all([
    loadStats(env),
    loadSubscriberStats(env),
    loadVisits(env),
  ]);
  const generatedAt = new Date().toISOString();
  if (wantsJson && url.pathname === '/stats.json') {
    return new Response(JSON.stringify({
      window_days: 30,
      generated_at: generatedAt,
      totals: {
        yes: rows.reduce((s, r) => s + r.yes, 0),
        no: rows.reduce((s, r) => s + r.no, 0),
      },
      rows,
      subscribers: subs,
      visits,
    }), {
      status: 200,
      headers: { 'Content-Type': 'application/json; charset=utf-8', 'Cache-Control': 'no-store', 'X-Robots-Tag': 'noindex, nofollow' },
    });
  }
  return statsHtml(rows, subs, visits, generatedAt);
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    if (url.pathname === '/v1/vote') return handleVote(request, env);
    if (url.pathname === '/v1/subscribe') return handleSubscribe(request, env);
    if (url.pathname === '/v1/confirm') return handleConfirm(request, env);
    if (url.pathname === '/v1/unsubscribe') return handleUnsubscribe(request, env);
    if (url.pathname === '/v1/notify-release') return handleNotifyRelease(request, env);
    if (url.pathname === '/stats' || url.pathname === '/stats.json' || url.pathname === '/stats/subscribers.csv' || url.pathname === '/stats/alerts.json') {
      return handleStats(request, env);
    }
    return new Response('Not Found', { status: 404 });
  },
};
