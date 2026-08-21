/*
 * sims.js: the interactive simulators of the web edition (vanilla JS, offline).
 * Each simulator is mounted into <div class="sim-slot" data-sim="NAME">; the arithmetic
 * lives in sim-core.js (tested against Ceph's own code), this file only draws.
 * The same view functions run in node at build time to make the static fallback
 * figure that is shown when printing and without JavaScript (tools/sim_fallback.js).
 * Part of "Ceph: Scalable Storage" by Ramin Najarbashi. CC BY-NC-SA 4.0.
 */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var C = NODE ? require('./sim-core.js') : root.SimCore;
  var D = { s: {}, lang: 'en' };            /* strings; set by init() */
  var FA = false;
  function T(k, v) {
    var s = D.s[k]; if (s == null) s = k;
    if (v) s = s.replace(/\{(\w+)\}/g, function (_, n) { return v[n] != null ? v[n] : ''; });
    return s;
  }
  function L(x) { x = String(x); return FA ? x.replace(/[0-9]/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }).replace(/\./g, '٫') : x; }
  function esc(s) { return String(s).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function num(x, d) { var v = d == null ? Math.round(x) : Math.round(x * Math.pow(10, d)) / Math.pow(10, d); return L(v); }
  function pct(x, d) { return L((Math.round(x * 1000) / 10).toFixed(d == null ? 1 : d)) + (FA ? '٪' : '%'); }
  function bytes(n) {
    var u = ['B', 'KiB', 'MiB', 'GiB', 'TiB'], i = 0;
    while (n >= 1024 && i < u.length - 1 && n % 1024 === 0) { n /= 1024; i++; }
    if (n >= 1024 && i < u.length - 1) { while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; } return L(Math.round(n * 100) / 100) + ' ' + u[i]; }
    return L(n) + ' ' + u[i];
  }
  // prose with Latin tokens (versions like 40'4, function names, [0,1,2]) isolated so the Persian bidi order holds
  var TOK = /[A-Za-z0-9_\[{(<\/.$?][\w.:'\[\]{},+\-\/=&#?…()<>$*^%|]*/g;
  function rich(s) {
    s = String(s);
    if (!FA) return esc(s);
    var out = '', last = 0, m;
    TOK.lastIndex = 0;
    while ((m = TOK.exec(s))) {
      if (!/[A-Za-z0-9]/.test(m[0])) continue;
      var t = m[0], tail = '';
      while (/[.,:;)]$/.test(t) && !/\(\)$/.test(t) && (t.slice(-1) !== ')' || (t.split('(').length < t.split(')').length))) { tail = t.slice(-1) + tail; t = t.slice(0, -1); }
      out += esc(s.slice(last, m.index)) + '<bdi dir="ltr">' + esc(t) + '</bdi>' + esc(tail);
      last = m.index + m[0].length;
    }
    return out + esc(s.slice(last));
  }
  function tx(k, v) { return rich(T(k, v)); }
  function code(s) { return '<code dir="ltr">' + esc(s) + '</code>'; }
  function sel(name, opts, cur, attrs) {
    return '<select data-k="' + name + '"' + (attrs || '') + '>' + opts.map(function (o) {
      var v = Array.isArray(o) ? o[0] : o, t = Array.isArray(o) ? o[1] : L(o);
      return '<option value="' + esc(v) + '"' + (String(v) === String(cur) ? ' selected' : '') + '>' + esc(t) + '</option>';
    }).join('') + '</select>';
  }
  function field(label, ctl, hint) { return '<label class="sim-f"><span>' + esc(label) + '</span>' + ctl + (hint ? '<small>' + hint + '</small>' : '') + '</label>'; }
  function numIn(name, v, min, max, step, extra) { return '<input type="number" inputmode="decimal" data-k="' + name + '" value="' + v + '" min="' + min + '" max="' + max + '" step="' + (step || 1) + '"' + (extra || '') + '>'; }
  function seg(name, opts, cur) {
    return '<div class="sim-seg" role="radiogroup" aria-label="' + esc(T(name + '_l')) + '">' + opts.map(function (o) {
      return '<button type="button" role="radio" data-set="' + name + '" data-v="' + o[0] + '" aria-checked="' + (String(cur) === String(o[0])) + '">' + esc(o[1]) + '</button>';
    }).join('') + '</div>';
  }
  function stat(v, label, cls) { return '<div class="sim-stat ' + (cls || '') + '"><b><bdi dir="ltr">' + v + '</bdi></b><span>' + rich(label) + '</span></div>'; }
  function refList(refs) { return '<ul class="sim-refs">' + refs.map(function (r) { return '<li>' + code(r[0]) + (r[1] ? ' <span>' + tx(r[1]) + '</span>' : '') + '</li>'; }).join('') + '</ul>'; }
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function range(a, b) { var r = []; for (var i = a; i <= b; i++) r.push(i); return r; }

  var DEFS = {};
  root.__SIM_PARTS__ = root.__SIM_PARTS__ || [];
  var API = { DEFS: DEFS, h: { T: T, tx: tx, rich: rich, L: L, esc: esc, num: num, pct: pct, bytes: bytes, code: code, sel: sel, field: field, numIn: numIn, seg: seg, stat: stat, clamp: clamp, range: range,
                               fa: function () { return FA; }, C: C } };
  if (NODE) module.exports = API; else root.Sims = API;
  API.setStrings = function (s, lang) { D = { s: s, lang: lang }; FA = lang === 'fa'; };
  API.refList = refList;
})(typeof self !== 'undefined' ? self : this);
