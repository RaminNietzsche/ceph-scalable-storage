/* S3 Signature Version 4 signer (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * Everything runs in the page: SHA-256 and HMAC are written out below, nothing is sent anywhere.
 * RGW recomputes the same chain in src/rgw/rgw_auth_s3.cc (get_v4_canonical_qs, get_v4_canonical_headers,
 * get_v4_string_to_sign, get_v4_signing_key, get_v4_signature) and compares it with the client's. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, sel = h.sel, field = h.field, stat = h.stat;

  // ---- SHA-256 (FIPS 180-4) on byte arrays
  var K = [0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5, 0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3,
    0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174, 0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
    0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967, 0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13,
    0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85, 0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
    0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3, 0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208,
    0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2];
  function sha256(bytes) {
    var H = [0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19];
    var m = bytes.slice(), bitLen = bytes.length * 8;
    m.push(0x80); while (m.length % 64 !== 56) m.push(0);
    for (var s = 56; s >= 0; s -= 8) m.push(s >= 32 ? Math.floor(bitLen / Math.pow(2, s)) & 0xff : (bitLen >>> s) & 0xff);
    var W = new Array(64);
    function r(x, n) { return (x >>> n) | (x << (32 - n)); }
    for (var off = 0; off < m.length; off += 64) {
      for (var i = 0; i < 16; i++) W[i] = (m[off + 4 * i] << 24) | (m[off + 4 * i + 1] << 16) | (m[off + 4 * i + 2] << 8) | m[off + 4 * i + 3];
      for (i = 16; i < 64; i++) {
        var s0 = r(W[i - 15], 7) ^ r(W[i - 15], 18) ^ (W[i - 15] >>> 3), s1 = r(W[i - 2], 17) ^ r(W[i - 2], 19) ^ (W[i - 2] >>> 10);
        W[i] = (W[i - 16] + s0 + W[i - 7] + s1) | 0;
      }
      var a = H[0], b = H[1], c = H[2], d = H[3], e = H[4], f = H[5], g = H[6], hh = H[7];
      for (i = 0; i < 64; i++) {
        var t1 = (hh + (r(e, 6) ^ r(e, 11) ^ r(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + W[i]) | 0;
        var t2 = ((r(a, 2) ^ r(a, 13) ^ r(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
        hh = g; g = f; f = e; e = (d + t1) | 0; d = c; c = b; b = a; a = (t1 + t2) | 0;
      }
      H = [H[0] + a, H[1] + b, H[2] + c, H[3] + d, H[4] + e, H[5] + f, H[6] + g, H[7] + hh].map(function (x) { return x | 0; });
    }
    var out = []; H.forEach(function (x) { out.push((x >>> 24) & 0xff, (x >>> 16) & 0xff, (x >>> 8) & 0xff, x & 0xff); });
    return out;
  }
  function utf8(s) { return NODE ? Array.from(Buffer.from(s, 'utf8')) : Array.from(new TextEncoder().encode(s)); }
  function hex(b) { return b.map(function (x) { return (x < 16 ? '0' : '') + x.toString(16); }).join(''); }
  function hmac(key, msg) {
    if (key.length > 64) key = sha256(key);
    var k = key.slice(); while (k.length < 64) k.push(0);
    return sha256(k.map(function (x) { return x ^ 0x5c; }).concat(sha256(k.map(function (x) { return x ^ 0x36; }).concat(utf8(msg)))));
  }
  // RFC 3986 unreserved characters stay; everything else is %XX of its UTF-8 bytes
  function enc(s, keepSlash) {
    return utf8(s).map(function (b) {
      var c = String.fromCharCode(b);
      return /[A-Za-z0-9\-_.~]/.test(c) || (keepSlash && c === '/') ? c : '%' + (b < 16 ? '0' : '') + b.toString(16).toUpperCase();
    }).join('');
  }
  function sign(o) {
    var ph = o.unsigned ? 'UNSIGNED-PAYLOAD' : hex(sha256(utf8(o.body || '')));
    var q = o.query.map(function (p) { return [enc(p[0]), enc(p[1])]; }).sort(function (a, b) { return a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0; });
    var cq = q.map(function (p) { return p[0] + '=' + p[1]; }).join('&');
    var hdr = 'host:' + o.host + '\nx-amz-content-sha256:' + ph + '\nx-amz-date:' + o.amz + '\n', sh = 'host;x-amz-content-sha256;x-amz-date';
    var creq = [o.method, enc(o.path, true), cq, hdr, sh, ph].join('\n');
    var scope = o.amz.slice(0, 8) + '/' + o.region + '/s3/aws4_request';
    var sts = 'AWS4-HMAC-SHA256\n' + o.amz + '\n' + scope + '\n' + hex(sha256(utf8(creq)));
    var kDate = hmac(utf8('AWS4' + o.secret), o.amz.slice(0, 8)), kRegion = hmac(kDate, o.region), kService = hmac(kRegion, 's3'), kSign = hmac(kService, 'aws4_request');
    return { ph: ph, creq: creq, sts: sts, scope: scope, keys: [kDate, kRegion, kService, kSign].map(hex), sig: hex(hmac(kSign, sts)), sh: sh };
  }
  function parseQuery(s) {
    return String(s || '').replace(/^\?/, '').split('&').filter(Boolean).map(function (kv) { var i = kv.indexOf('='); return i < 0 ? [kv, ''] : [kv.slice(0, i), kv.slice(i + 1)]; });
  }

  S.X = S.X || {};
  S.X.sigv4 = {
    sha256: sha256, hmac: hmac, sign: sign, enc: enc,
    test: function (t) {
      t.eq(hex(sha256(utf8(''))), 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'sha256 of the empty string');
      t.eq(hex(sha256(utf8('abc'))), 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', 'sha256("abc") (FIPS 180-4)');
      t.eq(hex(sha256(utf8(new Array(1001).join('a')))).length, 64, 'multi-block input');
      var g = t.G.sigv4; if (!g) return;
      var d = g.aws_doc_key, k = hmac(hmac(hmac(hmac(utf8('AWS4' + d[0]), d[1]), d[2]), d[3]), 'aws4_request');
      t.eq(hex(k), d[4], 'signing key example from the AWS documentation');
      g.cases.forEach(function (c, i) {
        var r = sign(c);
        t.eq(r.creq, c.creq, 'canonical request ' + i); t.eq(r.sts, c.sts, 'string to sign ' + i); t.eq(r.sig, c.sig, 'signature ' + i);
      });
    }
  };

  S.DEFS.sigv4 = {
    icon: 'M7 11V7a5 5 0 0110 0v4M5 11h14v10H5zM12 15v2',
    defaults: function () {
      return { method: 'PUT', host: 's3.example.com', path: '/photos/2026/cat.jpg', query: '', body: 'hello ceph', unsigned: false, region: 'default',
        amz: '20261122T090000Z', access: 'AKIDEXAMPLE', secret: 'wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY', tamper: 'none' };
    },
    refs: [['src/rgw/rgw_auth_s3.cc :: get_v4_canonical_qs, get_v4_canonical_headers, get_v4_string_to_sign', 'sigv4_r1'],
           ['src/rgw/rgw_auth_s3.cc :: get_v4_signing_key, get_v4_signature', 'sigv4_r2'],
           ['AWS documentation :: Signature Version 4 signing process, deriving the signing key', 'sigv4_r3']],
    controls: function (st) {
      function txt(k, w) { return '<input type="text" dir="ltr" data-k="' + k + '" value="' + esc(st[k]) + '"' + (w ? ' style="min-width:' + w + 'ch"' : '') + '>'; }
      return '<div class="sim-row">' + field(T('sigv4_method'), sel('method', ['GET', 'PUT', 'HEAD', 'DELETE'], st.method)) + field('Host', txt('host'))
        + field(T('sigv4_path'), txt('path', 22)) + field(T('sigv4_query'), txt('query')) + '</div>'
        + '<div class="sim-row">' + (st.method === 'PUT' ? field(T('sigv4_body'), txt('body')) : '')
        + '<label class="sim-f sim-chk"><span>UNSIGNED-PAYLOAD</span><input type="checkbox" data-k="unsigned"' + (st.unsigned ? ' checked' : '') + '></label>'
        + field(T('sigv4_region'), txt('region')) + field('x-amz-date', txt('amz')) + '</div>'
        + '<div class="sim-row">' + field('Access key', txt('access')) + field('Secret key', txt('secret', 30), esc(T('sigv4_secret_h')))
        + field(T('sigv4_tamper'), sel('tamper', [['none', T('sigv4_t_none')], ['path', T('sigv4_t_path')], ['body', T('sigv4_t_body')], ['date', T('sigv4_t_date')], ['region', T('sigv4_t_region')]], st.tamper)) + '</div>';
    },
    view: function (st) {
      var req = { method: st.method, host: st.host, path: st.path || '/', query: parseQuery(st.query), body: st.method === 'PUT' ? st.body : '', unsigned: st.unsigned, region: st.region, amz: st.amz, secret: st.secret };
      var good = /^\d{8}T\d{6}Z$/.test(st.amz);
      if (!good) return '<p class="sim-warn">' + tx('sigv4_baddate') + '</p>';
      var c = sign(req);
      // what the server sees after the request was changed on the way (RGW recomputes from what arrived)
      var srv = JSON.parse(JSON.stringify(req));
      if (st.tamper === 'path') srv.path = req.path + 'x';
      if (st.tamper === 'body') srv.body = req.body + '!';
      if (st.tamper === 'date') srv.amz = req.amz.slice(0, 13) + ((+req.amz[13] + 1) % 6) + req.amz.slice(14);
      if (st.tamper === 'region') srv.region = req.region + '2';
      var s = sign(srv), match = s.sig === c.sig;
      var bodyNote = st.tamper === 'body' && st.unsigned;
      var auth = 'AWS4-HMAC-SHA256 Credential=' + st.access + '/' + c.scope + ', SignedHeaders=' + c.sh + ', Signature=' + c.sig;
      function block(title, body, cls) { return '<div class="lx-card ' + (cls || 'on') + '"><h4>' + esc(title) + '</h4><pre class="lx-mono" dir="ltr">' + esc(body) + '</pre></div>'; }
      return '<div class="sim-stats">' + stat(c.sig.slice(0, 12) + '…', T('sigv4_s_sig')) + stat(st.tamper === 'none' ? '—' : s.sig.slice(0, 12) + '…', T('sigv4_s_srv'), st.tamper === 'none' ? '' : match ? '' : 'warn')
        + stat(match ? '200' : '403', match ? T('sigv4_s_ok') : 'SignatureDoesNotMatch', match ? '' : 'warn') + '</div>'
        + '<ol class="lx-steps">'
        + '<li>' + block(T('sigv4_st1'), c.creq) + '</li>'
        + '<li>' + block(T('sigv4_st2'), c.sts) + '</li>'
        + '<li>' + block(T('sigv4_st3'), 'kDate    = HMAC("AWS4" + secret, "' + st.amz.slice(0, 8) + '") = ' + c.keys[0] + '\nkRegion  = HMAC(kDate, "' + st.region + '") = ' + c.keys[1] + '\nkService = HMAC(kRegion, "s3") = ' + c.keys[2] + '\nkSigning = HMAC(kService, "aws4_request") = ' + c.keys[3]) + '</li>'
        + '<li>' + block(T('sigv4_st4'), 'Signature = HMAC(kSigning, StringToSign) = ' + c.sig + '\n\nAuthorization: ' + auth) + '</li>'
        + '<li>' + block(T('sigv4_st5'), st.tamper === 'none' ? T('sigv4_srv_same') : 'server Signature = ' + s.sig + '\n' + (match ? '== client' : '!= client  ->  403 SignatureDoesNotMatch'), match ? 'on' : 'bad') + '</li>'
        + '</ol>'
        + (bodyNote ? '<p class="sim-warn">' + tx('sigv4_unsigned_warn') + '</p>' : '')
        + '<p class="sim-note">' + tx('sigv4_note') + '</p>';
    },
    input: function (st, k, v, el) {
      if (k === 'unsigned') { st.unsigned = !!(el && el.checked !== undefined ? el.checked : v); return 'out'; }
      if (k === 'method') { st.method = v; return 'all'; }
      if (k in st) { st[k] = String(v).slice(0, 200); return 'out'; }
      return null;
    },
    say: function (st) { return T('sigv4_s_sig'); },
    fallbackState: function (st) { st.tamper = 'path'; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
