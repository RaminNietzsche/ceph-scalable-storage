/* Web edition gamification: XP and levels, daily goal and streak (with freezes and rest days),
   badges, weekly challenges, learning paths with certificates, and spaced-repetition review
   (Leitner boxes) built from the book's own review questions and glossary.
   Design and sources: docs/GAMIFICATION.md. Offline, no network; state lives in the
   book-progress localStorage record (P.g) shared with site.js through window.BookStore. */
(function () {
  'use strict';
  var G = window.__GAME__, B = window.BookStore;
  if (!G || !B) return;
  var d = document, root = d.documentElement, S = G.s, LANG = G.lang;
  var REDUCE = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var KIND = root.dataset.kind, SLUG = root.dataset.slug;
  var $ = function (s, c) { return (c || d).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || d).querySelectorAll(s)); };
  var FA = '۰۱۲۳۴۵۶۷۸۹';
  function L(x) { x = String(x); return LANG === 'fa' ? x.replace(/\d/g, function (c) { return FA[+c]; }) : x; }
  function T(k, o) { return String(S[k] || k).replace(/\{(\w+)\}/g, function (_, n) { return o && o[n] != null ? o[n] : ''; }); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function pct(n) { return LANG === 'fa' ? L(n) + '٪' : n + '%'; }
  function h(tag, attrs, html) {
    var e = d.createElement(tag);
    if (attrs) Object.keys(attrs).forEach(function (k) { if (attrs[k] != null) e.setAttribute(k, attrs[k]); });
    if (html != null) e.innerHTML = html;
    return e;
  }
  var ICON = {
    book: 'M4 5a2 2 0 0 1 2-2h13v16H6a2 2 0 0 0-2 2V5zM4 19a2 2 0 0 1 2-2h13',
    layers: 'M12 3 2 8l10 5 10-5-10-5zM2 13l10 5 10-5M2 17.5l10 5 10-5',
    clock: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7v5l3 2',
    flame: 'M12 3c1 3.5 5 5.5 5 10a5 5 0 0 1-10 0c0-2.2 1-3.6 2.2-4.8.2 1.6 1 2.6 2 3 0-3 .3-5.6.8-8.2z',
    sigma: 'M18 5H6l6 7-6 7h12',
    zoom: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4M11 8v6M8 11h6',
    cards: 'M3 7h13v13H3zM8 4h11a2 2 0 0 1 2 2v11',
    target: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z',
    lang: 'M4 5h8M8 3v2M5 9c1.5 3 4 5 7 6M11 5c-1 4-3.5 7-7 9M13 21l4-9 4 9M14.5 18h5',
    mark: 'M6 3h12v18l-6-4.5L6 21z',
    star: 'M12 3l2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z',
    check: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM8 12.5l2.7 2.7L16 9.5',
    cpu: 'M7 7h10v10H7zM10 2v3M14 2v3M10 19v3M14 19v3M2 10h3M2 14h3M19 10h3M19 14h3',
    code: 'M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16',
    map: 'M3 6l6-3 6 3 6-3v15l-6 3-6-3-6 3zM9 3v15M15 6v15',
    crown: 'M3 8l4 4 5-7 5 7 4-4-2 11H5z',
    inbox: 'M3 13l3-8h12l3 8v6H3zM3 13h5l1 3h6l1-3h5',
    moon: 'M20 14.5A8 8 0 1 1 9.5 4a6.5 6.5 0 0 0 10.5 10.5z',
    sun: 'M12 7a5 5 0 1 0 0 10 5 5 0 0 0 0-10zM12 1v3M12 20v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M1 12h3M20 12h3',
    sofa: 'M4 11V8a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v3M2 12a2 2 0 0 1 4 0v2h12v-2a2 2 0 0 1 4 0v6H2zM5 18v2M19 18v2',
    back: 'M9 14l-5-5 5-5M4 9h11a5 5 0 0 1 0 10h-3',
    dive: 'M12 3v14M6 11l6 6 6-6M4 21h16',
    bolt: 'M13 2 4 14h7l-1 8 9-12h-7z',
    globe: 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z',
    snow: 'M12 2v20M4 6.5l16 11M4 17.5l16-11M9 4l3 2 3-2M9 20l3-2 3 2',
    q: 'M9 9a3 3 0 1 1 4.5 2.6c-.9.5-1.5 1.2-1.5 2.4M12 18h.01',
    flask: 'M9 3h6M10 3v6l-5.6 9.6A1.6 1.6 0 0 0 5.8 21h12.4a1.6 1.6 0 0 0 1.4-2.4L14 9V3M7.2 15h9.6'
  };
  function svg(name, cls) { return '<svg class="' + (cls || 'gi') + '" viewBox="0 0 24 24" aria-hidden="true"><path d="' + ICON[name] + '"/></svg>'; }

  /* ---------------- dates (local time) ---------------- */
  function pad(n) { return (n < 10 ? '0' : '') + n; }
  function dkey(t) { return t.getFullYear() + '-' + pad(t.getMonth() + 1) + '-' + pad(t.getDate()); }
  function parse(k) { var a = k.split('-'); return new Date(+a[0], +a[1] - 1, +a[2], 12); }
  function addDays(k, n) { var t = parse(k); t.setDate(t.getDate() + n); return dkey(t); }
  function now() { return new Date(); }
  function today() { return dkey(now()); }
  function weekStartKey(k) { var t = parse(k), back = (t.getDay() - G.weekStart + 7) % 7; t.setDate(t.getDate() - back); return dkey(t); }
  function isRest(k) { return G.rest.indexOf(parse(k).getDay()) >= 0; }
  function daysBetween(a, b) { return Math.round((parse(b) - parse(a)) / 864e5); }
  var fmtDate = (function () {
    try { var f = new Intl.DateTimeFormat(LANG === 'fa' ? 'fa-IR' : 'en-GB', { year: 'numeric', month: 'long', day: 'numeric' }); return function (k) { return f.format(parse(k)); }; }
    catch (e) { return function (k) { return L(k); }; }
  })();

  /* ---------------- state ---------------- */
  var GV = 1;
  function defaults() {
    return { v: GV, on: true, sound: false, goal: { t: 'min', n: 10 }, restDays: true, xp: 0, days: {}, fz: 0, fzEarned: 0, frozen: {},
             settled: null, best: 0, badges: {}, secs: {}, chXP: {}, zoom: {}, algo: {}, sims: {}, srs: {}, glossOn: false,
             quiz: { ok: 0, n: 0, run: 0, best: 0 }, wk: null, name: '', flags: {}, lv: 1, seen: null };
  }
  function gs() {
    var P = B.get();
    if (!P.g || typeof P.g !== 'object') P.g = defaults();
    else if (P.g.v !== GV) {   // future migrations go here; unknown keys are kept
      var x = defaults(); Object.keys(x).forEach(function (k) { if (P.g[k] === undefined) P.g[k] = x[k]; }); P.g.v = GV;
    }
    var df = defaults();
    Object.keys(df).forEach(function (k) { if (P.g[k] === undefined) P.g[k] = df[k]; });
    return P.g;
  }
  function save() { B.save(); }
  function day(k) { var g = gs(); k = k || today(); if (!g.days[k]) g.days[k] = { s: 0, x: 0, sec: 0, c: 0, m: 0, nw: 0, k: {} }; return g.days[k]; }
  function trimDays() {
    var g = gs(), keys = Object.keys(g.days).sort();
    if (keys.length > 420) keys.slice(0, keys.length - 420).forEach(function (k) { delete g.days[k]; });
  }

  /* ---------------- levels ---------------- */
  function levelOf(xp) {
    var lv = G.levels, i = 0;
    while (i + 1 < lv.length && xp >= lv[i + 1][0]) i++;
    var cur = lv[i][0], nxt = i + 1 < lv.length ? lv[i + 1][0] : null;
    return { n: i + 1, t: lv[i][1], cur: cur, next: nxt, f: nxt ? (xp - cur) / (nxt - cur) : 1, need: nxt ? nxt - xp : 0 };
  }

  /* ---------------- feedback: toasts, confetti, sound ---------------- */
  var toastBox = null, xpToast = null, xpPend = 0, xpTimer = null;
  function on() { return gs().on; }
  function toasts() {
    if (!toastBox) { toastBox = h('div', { class: 'g-toasts game', role: 'status', 'aria-live': 'polite' }); d.body.appendChild(toastBox); }
    return toastBox;
  }
  function toast(html, cls, ms) {
    if (!on()) return null;
    var t = h('div', { class: 'g-toast ' + (cls || '') }, html);
    var box = toasts();
    while (box.children.length >= 3) box.removeChild(box.firstChild);
    box.appendChild(t);
    setTimeout(function () { t.classList.add('out'); setTimeout(function () { t.remove(); }, 400); }, ms || 3600);
    return t;
  }
  function xpFeedback(n) {
    if (!on() || n <= 0) return;
    xpPend += n;
    if (xpToast && xpToast.isConnected) xpToast.querySelector('b').textContent = T('xp_plus', { n: L(xpPend) });
    else { xpToast = toast(svg('bolt') + '<b>' + esc(T('xp_plus', { n: L(xpPend) })) + '</b>', 'xp', 2600); }
    clearTimeout(xpTimer); xpTimer = setTimeout(function () { xpPend = 0; xpToast = null; }, 2400);
    beep('xp');
  }
  var actx = null;
  function beep(kind) {
    var g = gs(); if (!g.sound || !g.on) return;
    try {
      actx = actx || new (window.AudioContext || window.webkitAudioContext)();
      var notes = kind === 'level' ? [523, 659, 784, 1047] : kind === 'badge' ? [660, 880] : [880];
      notes.forEach(function (f, i) {
        var o = actx.createOscillator(), v = actx.createGain(), t0 = actx.currentTime + i * 0.09;
        o.type = 'sine'; o.frequency.value = f; v.gain.setValueAtTime(0.0001, t0);
        v.gain.exponentialRampToValueAtTime(0.06, t0 + 0.01); v.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.16);
        o.connect(v); v.connect(actx.destination); o.start(t0); o.stop(t0 + 0.18);
      });
    } catch (e) { /* no audio */ }
  }
  function confetti() {
    if (REDUCE || !on()) return;
    var box = h('div', { class: 'g-confetti game', 'aria-hidden': 'true' });
    var cols = ['#22d3ee', '#34d399', '#818cf8', '#f59e0b', '#f472b6'];
    for (var i = 0; i < 36; i++) {
      var c = h('i');
      c.style.setProperty('--x', (Math.random() * 100).toFixed(1) + 'vw');
      c.style.setProperty('--dx', ((Math.random() - 0.5) * 30).toFixed(1) + 'vw');
      c.style.setProperty('--r', Math.round(Math.random() * 720 - 360) + 'deg');
      c.style.setProperty('--t', (1.1 + Math.random() * 0.9).toFixed(2) + 's');
      c.style.background = cols[i % cols.length];
      box.appendChild(c);
    }
    d.body.appendChild(box);
    setTimeout(function () { box.remove(); }, 2300);
  }

  /* ---------------- XP ---------------- */
  var CAPS = { sec: 300, card: 150, mc: 120, algo: 60, sim: 40 };
  var badgeLock = false;
  function award(n, kind, quiet) {
    var g = gs(), dd = day();
    if (CAPS[kind] != null) {
      var used = dd.k[kind] || 0, room = Math.max(0, CAPS[kind] - used);
      n = Math.min(n, room);
      dd.k[kind] = used + n;
    }
    if (n <= 0) return 0;
    var before = levelOf(g.xp).n;
    g.xp += n; dd.x += n;
    var earned = Math.floor(g.xp / 500);
    if (earned > g.fzEarned) { g.fz = Math.min(3, g.fz + (earned - g.fzEarned)); g.fzEarned = earned; }
    save();
    if (!quiet) xpFeedback(n);
    var after = levelOf(g.xp);
    if (after.n > before) {
      g.lv = after.n; save();
      var t = toast(svg('crown') + '<div><b>' + esc(T('level_up', { n: L(after.n), t: after.t })) + '</b><span>' + esc(S.level_up_sub) + '</span></div>', 'level', 5200);
      if (t) { confetti(); beep('level'); }
    }
    if (!badgeLock) checkBadges();
    paintChrome();
    return n;
  }

  /* ---------------- weekly challenges ---------------- */
  var QPOOL = [['sec', 15], ['ch', 2], ['cards', 20], ['gd', 4], ['mc', 15], ['min', 90], ['algo', 10]];
  var QXP = 40;
  function hashStr(s) { var x = 2166136261; for (var i = 0; i < s.length; i++) { x ^= s.charCodeAt(i); x = Math.imul(x, 16777619); } return x >>> 0; }
  function week() {
    var g = gs(), id = weekStartKey(today());
    if (!g.wk || g.wk.id !== id) {
      var idx = QPOOL.map(function (_, i) { return i; }), r = hashStr(id + G.lang), pick = [];
      while (pick.length < 3) { var j = r % idx.length; pick.push(QPOOL[idx.splice(j, 1)[0]]); r = Math.imul(r ^ (r >>> 13), 2654435761) >>> 0; }
      g.wk = { id: id, q: pick, c: {}, done: {} };
    }
    return g.wk;
  }
  function bump(kind, n) {
    var w = week();
    w.c[kind] = (w.c[kind] || 0) + n;
    w.q.forEach(function (q) {
      if (q[0] === kind && !w.done[kind] && w.c[kind] >= q[1]) {
        w.done[kind] = Date.now();
        toast(svg('target') + '<b>' + esc(T('quest_done', { t: T('q_' + kind, { n: L(q[1]) }) })) + '</b>', 'quest');
        award(QXP, 'quest', true);
      }
    });
    save();
  }

  /* ---------------- daily goal and streak ---------------- */
  function goalFrac(k) {
    var g = gs(), dd = gs().days[k || today()];
    if (!dd) return 0;
    return g.goal.t === 'sec' ? Math.min(1, dd.sec / g.goal.n) : Math.min(1, dd.s / 60 / g.goal.n);
  }
  function checkGoal() {
    var dd = day();
    if (!dd.gm && goalFrac() >= 1) {
      dd.gm = 1; save();
      award(20, 'goal', true);
      bump('gd', 1);
      var st = streak();
      if (st.cur > gs().best) { gs().best = st.cur; save(); }
      toast(svg('flame') + '<div><b>' + esc(S.goal_done) + '</b><span>' + esc(T('streak', { n: L(st.cur) })) + '</span></div>', 'goal', 4200);
      checkBadges(); paintChrome();
    }
  }
  function restOK(k) { return gs().restDays && isRest(k); }
  function settle() {
    // walk the days between the last settled day and yesterday; a run of missed days is covered by
    // freezes only when the freezes cover the whole run (so freezes are never wasted on a lost streak)
    var g = gs(), y = addDays(today(), -1);
    var from = g.settled ? addDays(g.settled, 1) : null;
    if (!from) { g.settled = y; save(); return; }
    if (from > y) return;
    var k = from, run = [];
    var activeBefore = streakAt(addDays(from, -1)) > 0;
    while (k <= y) {
      var dd = g.days[k];
      if (dd && dd.gm) { flush(); activeBefore = true; }
      else if (restOK(k)) { /* neutral */ }
      else run.push(k);
      k = addDays(k, 1);
    }
    flush();
    g.settled = y; save();
    function flush() {
      if (!run.length) return;
      if (activeBefore && run.length <= g.fz) {
        run.forEach(function (x) { g.frozen[x] = 1; });
        g.fz -= run.length; g.flags.freeze = 1;
        toast(svg('snow') + '<b>' + esc(T('freeze_used', { n: L(run.length) })) + '</b>', 'freeze', 5000);
      } else if (activeBefore) {
        activeBefore = false;
      }
      if (run.length >= 7) g.flags.comeback = 1;
      run = [];
    }
  }
  function streakAt(k) {
    var g = gs(), n = 0, i = 0;
    while (i++ < 800) {
      var dd = g.days[k];
      if (dd && dd.gm) n++;
      else if (!(g.frozen[k] || restOK(k))) break;
      k = addDays(k, -1);
      if (!Object.keys(g.days).length) break;
    }
    return n;
  }
  function streak() {
    var t = today(), dd = gs().days[t];
    var cur = dd && dd.gm ? streakAt(t) : streakAt(addDays(t, -1));
    return { cur: cur, today: !!(dd && dd.gm) };
  }

  /* ---------------- stats & badges ---------------- */
  function stats() {
    var P = B.get(), g = gs(), chs = Object.keys(G.chs), st = { sec: 0, cards: 0, goals: 0 };
    Object.keys(g.days).forEach(function (k) { var x = g.days[k]; st.sec += x.s || 0; st.cards += x.c || 0; if (x.gm) st.goals++; });
    st.chapters = chs.filter(function (s) { return P.read[s]; }).length;
    st.sections = Object.keys(g.secs).length;
    st.algo = Object.keys(g.algo).length;
    st.figs = Object.keys(g.zoom).length;
    st.sims = Object.keys(g.sims).length;
    st.marks = P.marks.length;
    st.qok = g.quiz.ok; st.qn = g.quiz.n; st.qbest = g.quiz.best;
    st.gloss = Object.keys(g.srs).filter(function (k) { return k.charAt(0) === 'g' && g.srs[k].b >= 4; }).length;
    st.xp = g.xp;
    st.best = Math.max(g.best, streak().cur);
    st.parts = {};
    Object.keys(G.parts).forEach(function (k) { var a = G.parts[k]; st.parts[k] = a.length > 0 && a.every(function (s) { return P.read[s]; }); });
    st.paths = G.paths.filter(function (p) { return p.ch.length && p.ch.every(function (s) { return P.read[s]; }); }).length;
    return st;
  }
  var TIER_XP = [0, 10, 25, 50];
  var BADGES = [
    ['reader', 'book', [1, 10, 42], function (s) { return s.chapters; }],
    ['sections', 'layers', [10, 100, 500], function (s) { return s.sections; }],
    ['hours', 'clock', [1, 10, 30], function (s) { return Math.floor(s.sec / 3600); }],
    ['streak', 'flame', [3, 7, 30], function (s) { return s.best; }],
    ['algo', 'sigma', [20, 80, G.nAlgo], function (s) { return s.algo; }],
    ['figs', 'zoom', [5, 25, 100], function (s) { return s.figs; }],
    ['lab', 'flask', [1, 4, 7], function (s) { return s.sims; }],
    ['cards', 'cards', [20, 200, 1000], function (s) { return s.cards; }],
    ['quiz', 'target', [10, 50, 200], function (s) { return s.qok; }],
    ['gloss', 'lang', [10, 50, Math.max(51, G.gids.length)], function (s) { return s.gloss; }],
    ['marks', 'mark', [1, 10, 30], function (s) { return s.marks; }],
    ['xp', 'star', [500, 2500, 6500], function (s) { return s.xp; }],
    ['goals', 'check', [1, 14, 60], function (s) { return s.goals; }],
    ['part1', 'book', 2, function (s) { return s.parts['1']; }],
    ['part2', 'code', 2, function (s) { return s.parts['2']; }],
    ['part3', 'cpu', 3, function (s) { return s.parts['3']; }],
    ['part4', 'layers', 3, function (s) { return s.parts['4']; }],
    ['path1', 'map', 2, function (s) { return s.paths >= 1; }],
    ['pathall', 'crown', 3, function (s) { return s.paths >= G.paths.length; }],
    ['reviewclear', 'inbox', 2, function () { return !!gs().flags.clear; }],
    ['night', 'moon', 1, function () { return !!gs().flags.night; }, 1],
    ['early', 'sun', 1, function () { return !!gs().flags.early; }, 1],
    ['weekend', 'sofa', 1, function () { return !!gs().flags.weekend; }, 1],
    ['comeback', 'back', 1, function () { return !!gs().flags.comeback; }, 1],
    ['deep', 'dive', 2, function () { return !!gs().flags.deep; }, 1],
    ['perfect', 'bolt', 2, function (s) { return s.qbest >= 10; }, 1],
    ['polyglot', 'globe', 1, function () { return !!gs().flags.poly; }, 1],
    ['freeze', 'snow', 1, function () { return !!gs().flags.freeze; }, 1]
  ];
  function badgeState(b, st) {
    var v = b[3](st);
    if (Array.isArray(b[2])) {
      var t = 0; b[2].forEach(function (x, i) { if (v >= x) t = i + 1; });
      return { tier: t, v: v, target: t < 3 ? b[2][t] : b[2][2], tiered: true };
    }
    return { tier: v ? b[2] : 0, v: v ? 1 : 0, target: 1, tiered: false };
  }
  function checkBadges() {
    if (badgeLock) return;
    badgeLock = true;
    try {
      var g = gs(), st = stats();
      BADGES.forEach(function (b) {
        var s = badgeState(b, st), have = g.badges[b[0]] ? g.badges[b[0]].t : 0;
        if (s.tier > have) {
          var newTier = s.tiered ? s.tier : s.tier;
          g.badges[b[0]] = { t: newTier, ts: Date.now() };
          save();
          var tierName = S['tier' + newTier];
          toast('<span class="g-medal t' + newTier + '">' + svg(b[1]) + '</span><div><b>' + esc(T('badge_new', { t: G.badges[b[0]][0], tier: tierName })) + '</b><span>' + esc(G.badges[b[0]][1]) + '</span></div>', 'badge', 4800);
          beep('badge');
          award(TIER_XP[newTier] || 10, 'badge', true);
        }
      });
    } finally { badgeLock = false; }
  }

  /* ---------------- spaced repetition (Leitner, 6 boxes) ---------------- */
  var BOX_DAYS = [0, 1, 2, 4, 8, 16, 32];
  var NEW_PER_DAY = 10;
  function cardIdsForChapter(n) { var c = +G.cardsByCh[n] || 0, a = []; for (var k = 1; k <= c; k++) a.push('q' + n + '-' + k); return a; }
  function dueIds() { var g = gs(), t = today(); return Object.keys(g.srs).filter(function (k) { return g.srs[k].d <= t; }); }
  function newCandidates() {
    var g = gs(), P = B.get(), out = [];
    Object.keys(G.chs).sort(function (a, b) { return G.chs[a] - G.chs[b]; }).forEach(function (s) {
      if (P.read[s]) cardIdsForChapter(G.chs[s]).forEach(function (id) { if (!g.srs[id]) out.push(id); });
    });
    if (g.glossOn) G.gids.forEach(function (id) { if (!g.srs[id]) out.push(id); });
    return out;
  }
  function newRoom() { return Math.max(0, NEW_PER_DAY - (day().nw || 0)); }
  function todayCount() { return dueIds().length + Math.min(newRoom(), newCandidates().length); }
  function rate(id, r) {   // r: 0 again, 1 hard, 2 good
    var g = gs(), c = g.srs[id], t = today(), dd = day();
    if (!c) { c = g.srs[id] = { b: 1, d: t, n: 0, l: 0 }; dd.nw = (dd.nw || 0) + 1; }
    c.n++;
    if (r === 0) { c.b = 1; c.l++; c.d = addDays(t, 1); }
    else if (r === 1) { c.b = Math.max(1, c.b); c.d = addDays(t, Math.max(1, Math.ceil(BOX_DAYS[c.b] / 2))); }
    else { c.b = Math.min(6, c.b + 1); c.d = addDays(t, BOX_DAYS[c.b]); }
    dd.c = (dd.c || 0) + 1;
    save();
    award(2, 'card');
    bump('cards', 1);
    return c;
  }

  /* ---------------- reading time, sections, algorithm boxes ---------------- */
  var lastAct = Date.now();
  ['scroll', 'keydown', 'pointerdown', 'pointermove', 'wheel', 'touchstart'].forEach(function (ev) {
    addEventListener(ev, function () { lastAct = Date.now(); }, { passive: true });
  });
  function active() { return d.visibilityState === 'visible' && Date.now() - lastAct < 90000; }
  var art = $('article.content');
  var SECS = [];
  if (B.tracked && art && KIND === 'chapter') {
    var heads = $$('h2[id]:not(.qz-h), h3[id]', art).filter(function (x) { return !x.closest('.page-head'); });
    var cur = null, words = {};
    Array.prototype.forEach.call(art.children, function (el) {
      if (heads.indexOf(el) >= 0) { cur = el.id; words[cur] = 0; return; }
      if (cur) words[cur] += (el.textContent || '').split(/\s+/).length;
    });
    SECS = heads.map(function (x, i) {
      var need = Math.max(6, Math.min(120, Math.round((words[x.id] || 0) / (G.wpm / 60) * 0.35)));
      return { el: x, id: x.id, need: need, dwell: 0, next: heads[i + 1] || null };
    });
  }
  function secKey(id) { return SLUG + '#' + id; }
  function tickSections() {
    if (!SECS.length) return;
    var g = gs(), line = innerHeight * 0.4, curS = null;
    for (var i = 0; i < SECS.length; i++) { if (SECS[i].el.getBoundingClientRect().top < line) curS = SECS[i]; else break; }
    if (!curS || g.secs[secKey(curS.id)]) return;
    curS.dwell++;
    if (curS.dwell < curS.need) return;
    var endVisible = curS.next ? curS.next.getBoundingClientRect().top < innerHeight : art.getBoundingClientRect().bottom < innerHeight * 1.2;
    if (!endVisible) return;
    g.secs[secKey(curS.id)] = Date.now();
    var dd = day(); dd.sec = (dd.sec || 0) + 1;
    save();
    award(5, 'sec');
    bump('sec', 1);
    checkGoal();
  }
  var secTick = 0;
  if (B.tracked) {
    setInterval(function () {
      if (!active()) return;
      tickSections();
      if (++secTick % 5) return;
      var g = gs(), dd = day(), hr = now().getHours();
      dd.s = (dd.s || 0) + 5;
      if (hr < 4) g.flags.night = 1;
      if (hr >= 5 && hr < 7) g.flags.early = 1;
      if (isRest(today()) && dd.s >= 600) g.flags.weekend = 1;
      if (dd.s >= 3600) g.flags.deep = 1;
      save();
      if (dd.s % 60 === 0) bump('min', 1);
      checkGoal();
      if (dd.s % 60 === 0) checkBadges();
      paintChrome();
    }, 1000);
  }
  if (B.tracked && 'IntersectionObserver' in window) {
    var seenT = {};
    var aio = new IntersectionObserver(function (es) {
      es.forEach(function (en) {
        var id = en.target.id;
        if (en.isIntersecting) seenT[id] = setTimeout(function () {
          var g = gs(); if (g.algo[id]) return;
          g.algo[id] = 1; save(); award(1, 'algo', true); bump('algo', 1);
        }, 1500);
        else clearTimeout(seenT[id]);
      });
    }, { threshold: 0.5 });
    $$('.call.algo[id]').forEach(function (el) { aio.observe(el); });
  }
  d.addEventListener('book:read', function (e) {
    var g = gs(), s = e.detail.slug;
    if (!e.detail.on || !G.chs[s] || g.chXP[s]) return;
    var mine = SECS.filter(function (x) { return g.secs[secKey(x.id)]; }).length;
    var xp = SECS.length && mine / SECS.length >= 0.5 ? 50 : 10;   // a chapter "read" by a click alone earns little
    g.chXP[s] = xp; save();
    award(xp, 'ch');
    bump('ch', 1);
  });
  // the interactive lab (sims.js): a little XP for the first use of each simulator per day, capped per day
  d.addEventListener('sim:use', function (e) {
    var n = e.detail && e.detail.sim, g = gs(), dd = day();
    if (!n) return;
    dd.sm = dd.sm || {};
    if (dd.sm[n]) return;
    dd.sm[n] = 1; g.sims[n] = (g.sims[n] || 0) + 1; save();
    award(5, 'sim');
    checkBadges();
  });
  d.addEventListener('book:zoom', function (e) { var g = gs(); if (!g.zoom[e.detail.id]) { g.zoom[e.detail.id] = 1; save(); checkBadges(); } });
  d.addEventListener('book:mark', function () { checkBadges(); });
  d.addEventListener('book:replaced', function () { gs(); paintChrome(); renderApp(); });

  /* ---------------- chrome: header chip, sidebar due count, home strip ---------------- */
  function paintChrome() {
    var g = gs();
    root.classList.toggle('no-game', !g.on);
    var lv = levelOf(g.xp), st = streak(), due = todayCount();
    var chip = $('#g-chip');
    if (chip) {
      chip.hidden = !g.on;
      $('.g-s', chip).textContent = L(st.cur);
      $('.g-l', chip).textContent = T('level', { n: L(lv.n) });
      chip.classList.toggle('lit', st.today);
      chip.setAttribute('aria-label', T('chip_label', { s: L(st.cur), l: L(lv.n), t: lv.t }));
      chip.title = chip.getAttribute('aria-label');
    }
    $$('[data-due]').forEach(function (b) { b.hidden = !due; b.textContent = L(due); });
    var strip = $('.rp-game');
    if (strip) {
      strip.hidden = !g.on;
      strip.innerHTML = svg('crown') + '<span>' + esc(T('level', { n: L(lv.n) })) + ' · ' + esc(lv.t) + '</span>' +
        '<span class="sep"></span>' + svg('flame') + '<span>' + esc(T('streak', { n: L(st.cur) })) + '</span>' +
        (due ? '<span class="sep"></span>' + svg('cards') + '<span>' + esc(T('rv_due', { n: L(due) })) + '</span>' : '');
    }
  }

  /* ---------------- pages rendered here ---------------- */
  function loadLearn(cb) {
    if (window.__LEARN__) return cb(window.__LEARN__);
    var sc = d.createElement('script'); sc.src = 'learn-data.js';
    sc.onload = function () { cb(window.__LEARN__ || { cards: [], gloss: [] }); };
    sc.onerror = function () { cb({ cards: [], gloss: [] }); };
    d.head.appendChild(sc);
  }
  function ringSVG(f, cls) {
    return '<svg class="ring ' + (cls || '') + '" viewBox="0 0 36 36" aria-hidden="true" style="--p:' + Math.round(Math.max(0, Math.min(1, f)) * 100) + '"><circle class="trk" cx="18" cy="18" r="15.5"/><circle class="val" cx="18" cy="18" r="15.5" pathLength="100"/></svg>';
  }
  function bar(f, label) {
    return '<div class="g-bar" role="progressbar" aria-valuemin="0" aria-valuemax="100" aria-valuenow="' + Math.round(f * 100) + '"' + (label ? ' aria-label="' + esc(label) + '"' : '') + '><i style="width:' + (Math.max(0, Math.min(1, f)) * 100).toFixed(1) + '%"></i></div>';
  }
  function fmtTime(sec) { var m = Math.round(sec / 60); return m >= 60 ? T('hm', { h: L(Math.floor(m / 60)), m: L(m % 60) }) : T('m_only', { m: L(m) }); }
  function sw(id, label, onState, help) {
    return '<div class="g-set"><button type="button" class="g-switch" role="switch" id="' + id + '" aria-checked="' + (onState ? 'true' : 'false') + '"><span class="knob"></span></button>' +
      '<label for="' + id + '">' + esc(label) + (help ? '<small>' + esc(help) + '</small>' : '') + '</label></div>';
  }
  function chTitle(slug) { return (B.pages[slug] && B.pages[slug][0]) || slug; }

  function nextChapter() {
    var P = B.get(), order = Object.keys(G.chs).sort(function (a, b) { return G.chs[a] - G.chs[b]; });
    // continue the active path first, then the chapter after the last one read, then the first unread
    for (var i = 0; i < G.paths.length; i++) {
      var p = G.paths[i], r = p.ch.filter(function (s) { return P.read[s]; }).length;
      if (r > 0 && r < p.ch.length) { for (var j = 0; j < p.ch.length; j++) if (!P.read[p.ch[j]]) return p.ch[j]; }
    }
    if (P.last && G.chs[P.last.s] && !P.read[P.last.s]) return P.last.s;
    for (var k = 0; k < order.length; k++) if (!P.read[order[k]]) return order[k];
    return null;
  }

  function heatmap(weeks) {
    var g = gs(), t = today(), start = addDays(weekStartKey(t), -7 * (weeks - 1)), cells = [], active = 0;
    for (var i = 0; i < weeks * 7; i++) {
      var k = addDays(start, i);
      if (k > t) { cells.push('<i class="h-x"></i>'); continue; }
      var x = g.days[k], m = x ? Math.round((x.s || 0) / 60) : 0;
      var lv = m === 0 ? 0 : m < 10 ? 1 : m < 20 ? 2 : m < 40 ? 3 : 4;
      if (m > 0) active++;
      var fz = g.frozen[k] && !m;
      var tip = fz ? T('heat_frozen', { d: fmtDate(k) }) : T('heat_day', { d: fmtDate(k), m: L(m) });
      cells.push('<i class="h' + lv + (fz ? ' h-fz' : '') + (k === t ? ' h-today' : '') + (x && x.gm ? ' h-gm' : '') + '" title="' + esc(tip) + '"></i>');
    }
    return '<div class="heat-wrap"><div class="heat" role="img" aria-label="' + esc(T('heat_label', { n: L(active), w: L(weeks) })) + '" style="--weeks:' + weeks + '">' + cells.join('') + '</div>' +
      '<div class="heat-legend" aria-hidden="true"><span>' + esc(S.heat_less) + '</span><i class="h0"></i><i class="h1"></i><i class="h2"></i><i class="h3"></i><i class="h4"></i><span>' + esc(S.heat_more) + '</span><i class="h0 h-fz"></i><span>❄</span></div></div>';
  }

  function badgeGallery() {
    var g = gs(), st = stats(), got = 0, out = [];
    BADGES.forEach(function (b) {
      var s = badgeState(b, st), have = g.badges[b[0]] ? g.badges[b[0]].t : 0, hidden = b[4] && !have;
      if (have) got++;
      var name = hidden ? S.hidden : G.badges[b[0]][0], desc = hidden ? S.hidden_hint : G.badges[b[0]][1];
      var tierCls = have ? 't' + have : 't0';
      var prog = '';
      if (!hidden && s.tiered && have < 3) prog = bar(Math.min(1, s.v / s.target), name) + '<span class="b-p">' + esc(L(Math.min(s.v, s.target)) + ' / ' + L(s.target)) + '</span>';
      var tierTxt = have ? S['tier' + have] : (hidden ? '' : S.locked);
      out.push('<li class="badge ' + tierCls + (hidden ? ' hid' : '') + '"' + ' aria-label="' + esc(name + ' — ' + (tierTxt || S.locked) + '. ' + desc) + '">' +
        '<span class="g-medal ' + tierCls + '">' + svg(hidden ? 'q' : b[1]) + '</span><b>' + esc(name) + '</b><small>' + esc(desc) + '</small>' +
        (tierTxt ? '<span class="b-tier">' + esc(tierTxt) + '</span>' : '') + prog + '</li>');
    });
    return { html: '<ul class="badges">' + out.join('') + '</ul>', got: got, n: BADGES.length };
  }

  function renderDashboard(el) {
    var g = gs(), P = B.get(), lv = levelOf(g.xp), st = streak(), sts = stats(), due = todayCount();
    var gf = goalFrac(), goalTxt = g.goal.t === 'sec' ? T('goal_sec', { n: L(g.goal.n) }) : T('goal_min', { n: L(g.goal.n) });
    var dd = g.days[today()] || {}, gNow = g.goal.t === 'sec' ? L(dd.sec || 0) : L(Math.floor((dd.s || 0) / 60)), gTot = L(g.goal.n);
    var nx = nextChapter(), w = week(), bg = badgeGallery();
    var html = '';
    html += '<p class="g-offnote">' + esc(S.game_off) + '</p>';
    html += '<section class="g-top game" aria-label="' + esc(S.my_progress) + '">' +
      '<div class="g-card g-level"><span class="g-medal t3 big">' + svg('crown') + '</span><div><div class="g-k">' + esc(T('level', { n: L(lv.n) })) + '</div><div class="g-v">' + esc(lv.t) + '</div>' +
      bar(lv.f, T('level', { n: L(lv.n) })) + '<small>' + esc(T('xp', { n: L(g.xp) })) + ' · ' + esc(lv.next ? T('to_next', { n: L(lv.need) }) : S.max_level) + '</small></div></div>' +
      '<div class="g-card g-streak' + (st.today ? ' lit' : '') + '"><span class="g-flame">' + svg('flame') + '</span><div><div class="g-k">' + esc(S.streak_title) + '</div><div class="g-v">' + esc(T('streak', { n: L(st.cur) })) + '</div>' +
      '<small>' + esc(T('best_streak', { n: L(Math.max(g.best, st.cur)) })) + ' · <span title="' + esc(S.freeze_help) + '">❄ ' + esc(T('freezes', { n: L(g.fz) })) + '</span></small></div></div>' +
      '<div class="g-card g-goal"><div class="ring-wrap">' + ringSVG(gf, 'big') + '<b>' + pct(Math.round(gf * 100)) + '</b></div><div><div class="g-k">' + esc(S.goal_title) + '</div><div class="g-v">' + esc(goalTxt) + '</div>' +
      '<small>' + esc(gf >= 1 ? S.goal_done : T('goal_prog', { a: gNow, b: gTot })) + '</small></div></div>' +
      '<a class="g-card g-due" href="review.html"><span class="g-medal t0 big">' + svg('cards') + '</span><div><div class="g-k">' + esc(S.review_today) + '</div><div class="g-v">' + esc(T('rv_due', { n: L(due) })) + '</div><small>' + esc(S.go) + ' →</small></div></a>' +
      '</section>';
    html += '<section class="g-sec g-next"><h2>' + esc(S.next_title) + '</h2><div class="g-nudges">' +
      (nx ? '<a class="g-nudge" href="' + nx + '.html">' + svg('book') + '<span><small>' + esc(S.next_ch) + '</small><b>' + esc(chTitle(nx)) + '</b></span></a>' : '<p>' + esc(S.next_none) + '</p>') +
      (due ? '<a class="g-nudge" href="review.html">' + svg('cards') + '<span><b>' + esc(T('next_review', { n: L(due) })) + '</b></span></a>' : '') + '</div></section>';
    html += '<section class="g-sec game"><h2>' + esc(S.heat_title) + '</h2>' + heatmap(innerWidth < 700 ? 17 : 26) + '</section>';
    html += '<section class="g-sec"><h2>' + esc(S.stats_title) + '</h2><div class="g-stats">' +
      [[fmtTime(sts.sec), S.st_time], [L(sts.chapters) + ' / ' + L(Object.keys(G.chs).length), S.st_chapters], [L(sts.sections), S.st_sections],
       [L(sts.cards), S.st_cards], [sts.qn ? pct(Math.round(sts.qok / sts.qn * 100)) : '—', S.st_acc], [L(sts.algo) + ' / ' + L(G.nAlgo), S.st_algo],
       [L(sts.figs), S.st_figs], [L(sts.sims), S.st_sims], [L(sts.marks), S.st_marks]].map(function (x) { return '<div><b>' + esc(x[0]) + '</b><span>' + esc(x[1]) + '</span></div>'; }).join('') + '</div></section>';
    html += '<section class="g-sec game" id="gm-quests"><h2>' + esc(S.quests_title) + '</h2><p class="g-sub">' + esc(T('quests_sub', { n: L(QXP) })) + '</p><ul class="quests">' +
      w.q.map(function (q) {
        var c = Math.min(q[1], Math.floor(w.c[q[0]] || 0)), done = !!w.done[q[0]], name = T('q_' + q[0], { n: L(q[1]) });
        return '<li class="' + (done ? 'done' : '') + '"><span class="q-ic">' + svg(done ? 'check' : 'target') + '</span><div><b>' + esc(name) + '</b>' + bar(c / q[1], name) + '</div><span class="q-n">' + esc(L(c) + ' / ' + L(q[1])) + '</span></li>';
      }).join('') + '</ul></section>';
    html += '<section class="g-sec" id="gm-paths"><h2>' + esc(S.paths_title) + '</h2><p class="g-sub">' + esc(S.paths_sub) + '</p><ul class="paths">' +
      G.paths.map(function (p) {
        var r = p.ch.filter(function (s) { return P.read[s]; }).length, n = p.ch.length, done = n && r === n;
        return '<li class="' + (done ? 'done' : '') + '"><div class="ring-wrap">' + ringSVG(n ? r / n : 0) + '</div><div><b>' + esc(p.t) + '</b><small>' + esc(T('path_prog', { r: L(r), n: L(n) })) + '</small>' +
          '<span class="p-chips">' + p.ch.map(function (s) { return '<a class="chip' + (P.read[s] ? ' is-read' : '') + '" href="' + s + '.html" title="' + esc(chTitle(s)) + '">' + L(G.chs[s]) + '</a>'; }).join('') + '</span></div>' +
          (done ? '<a class="btn" href="certificate.html?p=' + p.k + '">' + svg('crown') + esc(S.cert_get) + '</a>' : '') + '</li>';
      }).join('') + '</ul></section>';
    html += '<section class="g-sec game" id="gm-badges"><h2>' + esc(S.badges_title) + '</h2><p class="g-sub">' + esc(T('badges_sub', { a: L(bg.got), b: L(bg.n) })) + '</p>' + bg.html + '</section>';
    html += '<section class="g-sec g-settings" id="gm-settings"><h2>' + esc(S.settings_title) + '</h2>' +
      sw('gs-on', S.set_game, g.on, S.set_game_help) + sw('gs-sound', S.set_sound, g.sound) + sw('gs-rest', S.rest_label, g.restDays, S.rest_help) +
      '<fieldset class="g-goalpick"><legend>' + esc(S.goal_pick) + '</legend>' +
      [['min', 10], ['min', 20], ['min', 30], ['sec', 1]].map(function (o) {
        var id = 'gp-' + o[0] + o[1], chk = g.goal.t === o[0] && g.goal.n === o[1];
        return '<label class="pill"><input type="radio" name="gp" id="' + id + '" value="' + o[0] + ':' + o[1] + '"' + (chk ? ' checked' : '') + '><span>' + esc(o[0] === 'sec' ? T('goal_sec', { n: L(o[1]) }) : T('goal_min', { n: L(o[1]) })) + '</span></label>';
      }).join('') + '</fieldset>' +
      '<div class="g-acts"><button type="button" class="btn" data-open-my>' + svg('mark') + '</button>' +
      '<button type="button" class="btn danger" id="gs-reset">' + esc(S.set_reset) + '</button></div><p class="g-sub">' + esc(S.set_note) + '</p></section>';
    el.innerHTML = html;
    var myBtn = $('[data-open-my]', el), headMy = $('#my-btn');
    if (myBtn && headMy) { myBtn.innerHTML = svg('mark') + esc(headMy.getAttribute('aria-label')); myBtn.addEventListener('click', function () { headMy.click(); }); }
    else if (myBtn) myBtn.remove();
    $('#gs-on', el).addEventListener('click', function () { var g2 = gs(); g2.on = !g2.on; save(); paintChrome(); renderApp(); $('#gs-on').focus(); });
    $('#gs-sound', el).addEventListener('click', function () { var g2 = gs(); g2.sound = !g2.sound; save(); this.setAttribute('aria-checked', String(g2.sound)); if (g2.sound) beep('badge'); });
    $('#gs-rest', el).addEventListener('click', function () { var g2 = gs(); g2.restDays = !g2.restDays; save(); this.setAttribute('aria-checked', String(g2.restDays)); });
    $$('input[name="gp"]', el).forEach(function (r) {
      r.addEventListener('change', function () { var a = r.value.split(':'); gs().goal = { t: a[0], n: +a[1] }; save(); checkGoal(); renderApp(); var x = $('#' + r.id); if (x) x.focus(); });
    });
    $('#gs-reset', el).addEventListener('click', function () {
      if (!confirm(S.set_reset_confirm)) return;
      var keep = gs(), fresh = defaults(); fresh.on = keep.on; fresh.sound = keep.sound; fresh.goal = keep.goal; fresh.restDays = keep.restDays; fresh.settled = today();
      B.get().g = fresh; save(); B.say(S.set_reset_ok); paintChrome(); renderApp();
    });
  }

  /* ---- review: flashcards (self-rated) and glossary multiple choice ---- */
  var RV = { mode: null, queue: [], i: 0, shown: false, done: 0, xp0: 0, ch: null, qz: null };
  function renderReview(el) {
    loadLearn(function (data) {
      var cards = {}, byCh = {};
      data.cards.forEach(function (c) { cards[c[0]] = { id: c[0], ch: c[1], q: c[2], a: c[3] }; (byCh[c[1]] = byCh[c[1]] || []).push(c[0]); });
      data.gloss.forEach(function (x) { cards[x[0]] = { id: x[0], g: 1, q: x[1], a: x[2] }; });
      var qs = new URLSearchParams(location.search);
      if (!RV.mode) { RV.mode = qs.get('ch') ? 'ch' : qs.get('mode') === 'quiz' ? 'quiz' : 'today'; RV.ch = +qs.get('ch') || null; }
      var due = todayCount();
      var tabs = [['today', T('rv_tab_today') + (due ? ' (' + L(due) + ')' : '')], ['ch', S.rv_tab_ch], ['quiz', S.rv_tab_quiz]];
      el.innerHTML = '<div class="rv-tabs" role="tablist">' + tabs.map(function (t) {
        return '<button type="button" role="tab" id="tab-' + t[0] + '" aria-controls="rv-panel" aria-selected="' + (RV.mode === t[0]) + '" tabindex="' + (RV.mode === t[0] ? 0 : -1) + '">' + esc(t[1]) + '</button>';
      }).join('') + '</div><div id="rv-panel" role="tabpanel" aria-labelledby="tab-' + RV.mode + '"></div>';
      var tl = $('.rv-tabs', el);
      $$('[role="tab"]', tl).forEach(function (b, i, all) {
        b.addEventListener('click', function () { RV.mode = b.id.slice(4); RV.queue = []; RV.qz = null; renderReview(el); setTimeout(function () { var x = $('#tab-' + RV.mode); if (x) x.focus(); }, 0); });
        b.addEventListener('keydown', function (e) {
          var k = e.key, dir = (k === 'ArrowLeft') !== (root.dir === 'rtl') ? -1 : 1;
          if (k === 'ArrowLeft' || k === 'ArrowRight') { e.preventDefault(); all[(i + dir + all.length) % all.length].click(); }
        });
      });
      var panel = $('#rv-panel', el);
      if (RV.mode === 'quiz') return quiz(panel, data.gloss);
      if (RV.mode === 'ch') {
        var chs = Object.keys(byCh).map(Number).sort(function (a, b) { return a - b; });
        if (!RV.ch || !byCh[RV.ch]) RV.ch = chs[0] || null;
        panel.innerHTML = '<div class="rv-pick"><label for="rv-ch">' + esc(S.rv_pick_ch) + '</label><select id="rv-ch">' + chs.map(function (n) {
          return '<option value="' + n + '"' + (n === RV.ch ? ' selected' : '') + '>' + esc(L(n) + ' — ' + (G.chTitle[n] || '')) + '</option>';
        }).join('') + '</select></div><div class="rv-stage"></div>';
        var sel = $('#rv-ch', panel);
        if (!chs.length) { $('.rv-stage', panel).innerHTML = '<p class="rv-empty">' + esc(S.rv_no_cards) + '</p>'; sel.disabled = true; return; }
        sel.addEventListener('change', function () { RV.ch = +sel.value; RV.queue = []; renderReview(el); setTimeout(function () { $('#rv-ch').focus(); }, 0); });
        if (!RV.queue.length || RV.queueFor !== 'ch' + RV.ch) { RV.queue = byCh[RV.ch].slice(); RV.i = 0; RV.done = 0; RV.queueFor = 'ch' + RV.ch; RV.xp0 = gs().xp; }
        return flash($('.rv-stage', panel), cards, el);
      }
      // today
      var g = gs();
      panel.innerHTML = '<label class="rv-gloss"><input type="checkbox" id="rv-gl"' + (g.glossOn ? ' checked' : '') + '> ' + esc(S.rv_gloss) + '</label><div class="rv-stage"></div>';
      $('#rv-gl', panel).addEventListener('change', function () { gs().glossOn = this.checked; save(); RV.queue = []; paintChrome(); renderReview(el); setTimeout(function () { $('#rv-gl').focus(); }, 0); });
      if (!RV.queue.length || RV.queueFor !== 'today') {
        var q = dueIds().filter(function (id) { return cards[id]; });
        q = q.concat(newCandidates().filter(function (id) { return cards[id]; }).slice(0, newRoom()));
        RV.queue = q; RV.i = 0; RV.done = 0; RV.queueFor = 'today'; RV.xp0 = gs().xp;
      }
      if (!RV.queue.length) { $('.rv-stage', panel).innerHTML = '<p class="rv-empty">' + svg('inbox') + esc(S.rv_empty) + '</p>'; return; }
      flash($('.rv-stage', panel), cards, el);
    });
  }
  function flash(stage, cards, el) {
    if (RV.i >= RV.queue.length) {
      if (RV.queueFor === 'today' && RV.done >= 10 && !dueIds().length) { gs().flags.clear = 1; save(); checkBadges(); }
      stage.innerHTML = '<div class="rv-done"><span class="g-medal t2 big">' + svg('check') + '</span><p>' + esc(T('rv_done', { n: L(RV.done) })) +
        (on() ? ' ' + esc(T('xp_plus', { n: L(gs().xp - RV.xp0) })) : '') + '</p><button type="button" class="btn primary" id="rv-more">' + esc(S.rv_again_round) + '</button></div>';
      $('#rv-more', stage).addEventListener('click', function () { RV.queue = []; renderReview(el); });
      $('#rv-more', stage).focus();
      paintChrome();
      return;
    }
    var c = cards[RV.queue[RV.i]], s = gs().srs[c.id];
    RV.shown = false;
    var src = c.g ? '<a href="glossary.html">' + esc(S.rv_src_g) + '</a>' : '<a href="answers.html#answers-' + pad(c.ch) + '">' + esc(T('rv_src', { n: L(c.ch) })) + '</a>';
    stage.innerHTML = '<div class="rv-meta"><span>' + esc(T('rv_count', { i: L(RV.i + 1), n: L(RV.queue.length) })) + '</span>' + (s ? '<span>' + esc(T('rv_box', { n: L(s.b) })) + '</span>' : '') + '</div>' +
      bar(RV.i / RV.queue.length) +
      '<div class="flash" tabindex="-1"><div class="f-q"' + (c.g ? ' dir="ltr" lang="en"' : '') + '>' + esc(c.q) + '</div><div class="f-a" hidden>' + esc(c.a) + '<div class="f-src">' + src + '</div></div></div>' +
      '<div class="rv-acts"><button type="button" class="btn primary" id="rv-show">' + esc(S.rv_show) + ' <kbd>␣</kbd></button>' +
      '<div class="rv-rate" hidden><button type="button" class="btn r0" data-r="0">' + esc(S.rv_again) + ' <kbd>' + L(1) + '</kbd></button><button type="button" class="btn r1" data-r="1">' + esc(S.rv_hard) + ' <kbd>' + L(2) + '</kbd></button><button type="button" class="btn r2" data-r="2">' + esc(S.rv_good) + ' <kbd>' + L(3) + '</kbd></button></div></div>' +
      '<p class="g-sub rv-keys">' + esc(S.rv_keys) + '</p>';
    var show = function () {
      if (RV.shown) return; RV.shown = true;
      $('.f-a', stage).hidden = false; $('#rv-show', stage).hidden = true; $('.rv-rate', stage).hidden = false;
      $('.flash', stage).classList.add('flip');
      $('.rv-rate .r2', stage).focus();
    };
    var doRate = function (r) {
      if (!RV.shown) return;
      rate(c.id, r); RV.done++;
      if (r === 0 && RV.queueFor === 'today') RV.queue.push(c.id);   // see it again in this round
      RV.i++; flash(stage, cards, el);
    };
    $('#rv-show', stage).addEventListener('click', show);
    $$('.rv-rate button', stage).forEach(function (b) { b.addEventListener('click', function () { doRate(+b.dataset.r); }); });
    $('#rv-show', stage).focus({ preventScroll: true });
    RV.key = function (e) {
      if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
      if ((e.key === ' ' || e.key === 'Enter') && !RV.shown) { e.preventDefault(); show(); }
      else if (RV.shown && /^[123۱۲۳]$/.test(e.key)) { e.preventDefault(); doRate('123'.indexOf(e.key) >= 0 ? +e.key - 1 : '۱۲۳'.indexOf(e.key)); }
    };
  }
  function shuffle(a) { for (var i = a.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)), t = a[i]; a[i] = a[j]; a[j] = t; } return a; }
  function quiz(panel, gloss) {
    if (gloss.length < 4) { panel.innerHTML = '<p class="rv-empty">' + esc(S.qz_need) + '</p>'; return; }
    if (!RV.qz) {
      var pool = shuffle(gloss.slice()).slice(0, 10);
      RV.qz = { items: pool.map(function (x, i) {
        var dist = shuffle(gloss.filter(function (y) { return y[0] !== x[0]; })).slice(0, 3);
        return { x: x, dir: i % 2 ? 'term' : 'def', opts: shuffle([x].concat(dist)) };
      }), i: 0, ok: 0, answered: false, xp0: gs().xp };
    }
    var Q = RV.qz;
    if (Q.i >= Q.items.length) {
      panel.innerHTML = '<div class="rv-done"><span class="g-medal t3 big">' + svg('target') + '</span><p>' + esc(T('qz_done', { a: L(Q.ok), n: L(Q.items.length) })) +
        (on() ? ' ' + esc(T('xp_plus', { n: L(gs().xp - Q.xp0) })) : '') + '</p><button type="button" class="btn primary" id="qz-more">' + esc(S.rv_again_round) + '</button></div>';
      $('#qz-more', panel).addEventListener('click', function () { RV.qz = null; quiz(panel, gloss); });
      $('#qz-more', panel).focus();
      return;
    }
    var it = Q.items[Q.i]; Q.answered = false;
    var prompt = it.dir === 'def' ? T('qz_q_def', { t: it.x[1] }) : S.qz_q_term;
    panel.innerHTML = '<div class="rv-meta"><span>' + esc(T('qz_count', { i: L(Q.i + 1), n: L(Q.items.length) })) + '</span></div>' + bar(Q.i / Q.items.length) +
      '<div class="qz"><p class="qz-p" id="qz-p">' + esc(prompt) + '</p>' + (it.dir === 'term' ? '<blockquote class="qz-def">' + esc(it.x[2]) + '</blockquote>' : '') +
      '<div class="qz-opts" role="group" aria-labelledby="qz-p">' + it.opts.map(function (o, i) {
        var txt = it.dir === 'def' ? o[2] : o[1];
        return '<button type="button" class="qz-o" data-i="' + i + '"' + (it.dir === 'term' ? ' dir="ltr" lang="en"' : '') + '><kbd>' + L(i + 1) + '</kbd><span>' + esc(txt) + '</span></button>';
      }).join('') + '</div><p class="qz-fb" role="status" aria-live="polite"></p>' +
      '<button type="button" class="btn primary" id="qz-next" hidden>' + esc(S.qz_next) + '</button><p class="g-sub rv-keys">' + esc(S.qz_keys) + '</p></div>';
    var choose = function (i) {
      if (Q.answered) return; Q.answered = true;
      var ok = it.opts[i][0] === it.x[0], g = gs();
      g.quiz.n++;
      if (ok) { g.quiz.ok++; g.quiz.run++; g.quiz.best = Math.max(g.quiz.best, g.quiz.run); Q.ok++; } else g.quiz.run = 0;
      var dd = day(); if (ok) dd.m = (dd.m || 0) + 1;
      save();
      $$('.qz-o', panel).forEach(function (b, k) {
        b.disabled = true;
        if (it.opts[k][0] === it.x[0]) b.classList.add('right');
        else if (k === i) b.classList.add('wrong');
      });
      $('.qz-fb', panel).textContent = ok ? S.qz_ok : S.qz_bad;
      $('.qz-fb', panel).className = 'qz-fb ' + (ok ? 'ok' : 'bad');
      award(ok ? 3 : 1, 'mc');
      if (ok) bump('mc', 1);
      checkBadges();
      var nb = $('#qz-next', panel); nb.hidden = false; nb.focus();
    };
    $$('.qz-o', panel).forEach(function (b) { b.addEventListener('click', function () { choose(+b.dataset.i); }); });
    $('#qz-next', panel).addEventListener('click', function () { Q.i++; quiz(panel, gloss); });
    var first = $('.qz-o', panel); if (first) first.focus({ preventScroll: true });
    RV.key = function (e) {
      var k = '1234'.indexOf(e.key) >= 0 ? +e.key - 1 : '۱۲۳۴'.indexOf(e.key);
      if (!Q.answered && k >= 0 && e.key.length === 1) { e.preventDefault(); choose(k); }
      else if (Q.answered && e.key === 'Enter' && d.activeElement !== $('#qz-next', panel)) { e.preventDefault(); $('#qz-next', panel).click(); }
    };
  }
  d.addEventListener('keydown', function (e) {
    if (KIND !== 'app' || SLUG !== 'review' || !RV.key || e.altKey || e.ctrlKey || e.metaKey) return;
    var dlg = $('#my-dlg'), sd = $('#search-dlg');
    if ((dlg && !dlg.hidden) || (sd && !sd.hidden)) return;
    RV.key(e);
  });

  /* ---- certificate ---- */
  function renderCert(el) {
    var P = B.get(), g = gs(), k = +new URLSearchParams(location.search).get('p');
    var p = G.paths.filter(function (x) { return x.k === k; })[0];
    if (!p) {
      el.innerHTML = '<p>' + esc(S.cert_pick) + '</p><ul class="paths">' + G.paths.map(function (x) {
        return '<li><a href="certificate.html?p=' + x.k + '">' + esc(x.t) + '</a></li>'; }).join('') + '</ul>';
      return;
    }
    var left = p.ch.filter(function (s) { return !P.read[s]; });
    if (left.length) {
      el.innerHTML = '<h2>' + esc(p.t) + '</h2><p>' + esc(S.cert_incomplete) + '</p><ul>' + left.map(function (s) {
        return '<li><a href="' + s + '.html">' + esc(L(G.chs[s]) + ' — ' + chTitle(s)) + '</a></li>'; }).join('') + '</ul>';
      return;
    }
    var lastRead = p.ch.map(function (s) { return P.read[s]; }).sort().pop() || Date.now();
    var lv = levelOf(g.xp);
    el.innerHTML = '<div class="cert-form"><label for="cert-name">' + esc(S.cert_name) + '</label><input id="cert-name" type="text" autocomplete="name" maxlength="80" value="' + esc(g.name || '') + '"><small>' + esc(S.cert_name_help) + '</small>' +
      '<button type="button" class="btn primary" id="cert-print">' + esc(S.cert_print) + '</button></div>' +
      '<div class="cert" id="cert"><div class="cert-in"><span class="g-medal t3 big">' + svg('crown') + '</span><div class="cert-k">' + esc(S.cert_head) + '</div>' +
      '<h2 class="cert-path">' + esc(p.t) + '</h2><p class="cert-body"></p><ol class="cert-chs">' + p.ch.map(function (s) { return '<li>' + esc(L(G.chs[s]) + ' — ' + chTitle(s)) + '</li>'; }).join('') + '</ol>' +
      '<div class="cert-foot"><span>' + esc(T('cert_date', { d: fmtDate(dkey(new Date(lastRead))) })) + '</span><span>' + esc(T('cert_level', { l: L(lv.n) + ' · ' + lv.t })) + '</span></div><p class="cert-note">' + esc(S.cert_note) + '</p></div></div>';
    var body = $('.cert-body', el), inp = $('#cert-name', el);
    var paint = function () { body.textContent = T('cert_body', { name: (inp.value.trim() || S.someone), path: p.t, book: G.book, n: L(p.ch.length) }); };
    paint();
    inp.addEventListener('input', function () { gs().name = inp.value.slice(0, 80); save(); paint(); });
    $('#cert-print', el).addEventListener('click', function () { window.print(); });
  }

  function renderApp() {
    if (KIND !== 'app') return;
    var el = $('#gm-' + SLUG);
    if (!el) return;
    if (SLUG === 'progress') renderDashboard(el);
    else if (SLUG === 'review') renderReview(el);
    else if (SLUG === 'certificate') renderCert(el);
    el.removeAttribute('aria-busy');
  }

  /* ---------------- boot ---------------- */
  var g0 = gs();
  var lastSeen = g0.seen;
  if (lastSeen && daysBetween(lastSeen, today()) >= 7) { g0.flags.comeback = 1; setTimeout(function () { toast(svg('back') + '<b>' + esc(S.welcome_back) + '</b>', 'info', 4200); }, 600); }
  g0.seen = today();
  try { var other = JSON.parse(localStorage.getItem('book-progress:' + G.other) || 'null'); if (other && other.g && Object.keys(other.g.days || {}).length && Object.keys(g0.days).length) g0.flags.poly = 1; } catch (e) { /* ignore */ }
  trimDays();
  settle();
  week();
  save();
  checkBadges();
  paintChrome();
  renderApp();
  window.Game = { award: award, state: gs, level: levelOf, streak: streak, todayCount: todayCount };   // for tests and the curious
})();
