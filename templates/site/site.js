/* Web edition behaviour: theme, sidebar/drawer, scrollspy, copy buttons,
   figure lightbox (wheel/drag/pinch zoom), offline search, keyboard nav.
   No dependencies and no network access; works from file:// too. */
(function () {
  'use strict';
  var d = document, root = d.documentElement;
  var S = {};
  try { S = JSON.parse(d.getElementById('site-data').textContent); } catch (e) { S = {}; }
  var RTL = root.dir === 'rtl';
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
  };
  var $ = function (s, c) { return (c || d).querySelector(s); };
  var $$ = function (s, c) { return Array.prototype.slice.call((c || d).querySelectorAll(s)); };

  /* ---------- theme ---------- */
  var themeBtn = $('#theme-btn');
  function syncTheme() { if (themeBtn) themeBtn.setAttribute('aria-pressed', String(root.dataset.theme === 'dark')); }
  syncTheme();
  if (themeBtn) themeBtn.addEventListener('click', function () {
    root.dataset.theme = root.dataset.theme === 'dark' ? 'light' : 'dark';
    store.set('book-theme', root.dataset.theme);
    syncTheme();
  });

  /* ---------- sidebar: desktop collapse, mobile drawer ---------- */
  var menuBtn = $('#menu-btn'), sidebar = $('#sidebar'), backdrop = $('.backdrop');
  var mobile = window.matchMedia('(max-width: 900px)');
  var lastFocus = null;
  function drawerOpen() { return root.classList.contains('sb-open'); }
  function setDrawer(open) {
    root.classList.toggle('sb-open', open);
    if (backdrop) backdrop.hidden = !open;
    if (menuBtn) menuBtn.setAttribute('aria-expanded', String(open));
    if (open) {
      lastFocus = d.activeElement;
      var cur = $('.sb-link[aria-current="page"]', sidebar) || $('a', sidebar);
      setTimeout(function () { if (cur) cur.focus(); }, 30);
    } else if (lastFocus && lastFocus.focus) { lastFocus.focus(); }
  }
  function syncMenuBtn() {
    if (!menuBtn) return;
    menuBtn.setAttribute('aria-expanded', String(mobile.matches ? drawerOpen() : !root.classList.contains('sb-collapsed')));
  }
  syncMenuBtn();
  if (menuBtn) menuBtn.addEventListener('click', function () {
    if (mobile.matches) { setDrawer(!drawerOpen()); return; }
    var hidden = root.classList.toggle('sb-collapsed');
    store.set('book-sidebar', hidden ? 'hidden' : 'shown');
    syncMenuBtn();
  });
  $$('[data-close-menu]').forEach(function (b) { b.addEventListener('click', function () { setDrawer(false); }); });
  (mobile.addEventListener ? mobile.addEventListener.bind(mobile, 'change') : mobile.addListener.bind(mobile))(function () {
    if (!mobile.matches) setDrawer(false);
    syncMenuBtn();
  });
  if (sidebar) {
    sidebar.addEventListener('keydown', function (e) {
      if (!drawerOpen()) return;
      if (e.key === 'Escape') { setDrawer(false); return; }
      if (e.key === 'Tab') {   // keep focus inside the drawer
        var f = $$('a[href], button:not([disabled])', sidebar).filter(function (x) { return x.offsetParent !== null; });
        if (!f.length) return;
        if (e.shiftKey && d.activeElement === f[0]) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && d.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
      }
    });
    sidebar.addEventListener('click', function (e) {
      var a = e.target.closest('a');
      if (a && drawerOpen() && a.getAttribute('href').indexOf('#') > 0) setDrawer(false);
    });
    $$('.sb-tog', sidebar).forEach(function (b) {
      b.addEventListener('click', function () {
        var open = b.getAttribute('aria-expanded') !== 'true';
        b.setAttribute('aria-expanded', String(open));
        var ul = d.getElementById(b.getAttribute('aria-controls'));
        if (ul) ul.hidden = !open;
        b.closest('li').classList.toggle('open', open);
      });
    });
    var cur = $('.sb-link[aria-current="page"]', sidebar);
    var sc = $('.sb-scroll', sidebar);
    if (cur && sc) {
      var r = cur.getBoundingClientRect(), sr = sc.getBoundingClientRect();
      if (r.top > sr.bottom - 80 || r.top < sr.top) sc.scrollTop += r.top - sr.top - sr.height / 3;
    }
  }

  /* ---------- scrollspy (right toc + sidebar sub-items) ---------- */
  var heads = $$('.content h2[id], .content h3[id]');
  var spyLinks = $$('.toc a[data-sec], .sb-sub[data-sec]');
  if (heads.length && spyLinks.length && 'IntersectionObserver' in window) {
    var visible = {};
    var activate = function (id) {
      spyLinks.forEach(function (a) {
        var on = a.dataset.sec === id;
        a.classList.toggle('active', on);
        if (on && a.closest('.toc')) {
          var box = a.closest('.toc'), ar = a.getBoundingClientRect(), br = box.getBoundingClientRect();
          if (ar.top < br.top + 40 || ar.bottom > br.bottom - 40) box.scrollTop += ar.top - br.top - br.height / 3;
        }
      });
    };
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) { visible[en.target.id] = en.isIntersecting; });
      var best = null;
      for (var i = 0; i < heads.length; i++) {
        if (visible[heads[i].id]) { best = heads[i].id; break; }
      }
      if (!best) {
        for (var j = heads.length - 1; j >= 0; j--) {
          if (heads[j].getBoundingClientRect().top < 120) { best = heads[j].id; break; }
        }
      }
      if (best) {
        var h = d.getElementById(best);
        if (h.tagName === 'H3') {   // highlight the parent h2 in the sidebar too
          var k = heads.indexOf(h);
          while (k >= 0 && heads[k].tagName !== 'H2') k--;
          if (k >= 0) $$('.sb-sub[data-sec]').forEach(function (a) { a.classList.toggle('active', a.dataset.sec === heads[k].id); });
        }
        activate(best);
      }
    }, { rootMargin: '-64px 0px -60% 0px' });
    heads.forEach(function (h) { io.observe(h); });
  }

  /* ---------- copy buttons ---------- */
  function copyText(t) {
    if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(t);
    return new Promise(function (res, rej) {
      var ta = d.createElement('textarea');
      ta.value = t; ta.setAttribute('readonly', ''); ta.style.position = 'fixed'; ta.style.opacity = '0';
      d.body.appendChild(ta); ta.select();
      try { d.execCommand('copy') ? res() : rej(); } catch (e) { rej(e); }
      d.body.removeChild(ta);
    });
  }
  $$('.code .copy').forEach(function (b) {
    b.addEventListener('click', function () {
      var code = b.closest('.code').querySelector('pre').innerText.replace(/\n$/, '');
      copyText(code).then(function () {
        b.textContent = b.dataset.done || S.copied; b.classList.add('done');
        setTimeout(function () { b.textContent = S.copy || 'Copy'; b.classList.remove('done'); }, 1600);
      }, function () { /* ignore */ });
    });
  });

  /* ---------- lightbox ---------- */
  var lb = null, lbImg, lbCap, lbStage, lbZoomv, st = { s: 1, x: 0, y: 0 }, maxS = 6, lbReturn = null;
  var pointers = {}, pinch = null, drag = null;
  function buildLb() {
    lb = d.createElement('div');
    lb.className = 'lb'; lb.hidden = true;
    lb.setAttribute('role', 'dialog'); lb.setAttribute('aria-modal', 'true'); lb.setAttribute('aria-label', S.zoom || 'Zoom');
    lb.innerHTML = '<div class="lb-stage"><img class="lb-img" alt=""></div>' +
      '<div class="lb-bar"><button type="button" data-a="out"></button><button type="button" class="lb-zoomv" data-a="reset"></button>' +
      '<button type="button" data-a="in"></button><button type="button" data-a="close"></button></div><div class="lb-cap"></div>';
    d.body.appendChild(lb);
    lbImg = $('.lb-img', lb); lbCap = $('.lb-cap', lb); lbStage = $('.lb-stage', lb); lbZoomv = $('.lb-zoomv', lb);
    var labels = { out: ['−', S.zoom_out], reset: ['100%', S.zoom_reset], 'in': ['+', S.zoom_in], close: ['✕', S.close] };
    $$('.lb-bar button', lb).forEach(function (b) {
      var l = labels[b.dataset.a]; b.textContent = l[0]; b.setAttribute('aria-label', l[1]); b.title = l[1];
      b.addEventListener('click', function () {
        var a = b.dataset.a;
        if (a === 'close') closeLb();
        else if (a === 'reset') setT(1, 0, 0);
        else zoomAt(a === 'in' ? 1.5 : 1 / 1.5, 0, 0);
      });
    });
    lbStage.addEventListener('wheel', function (e) {
      e.preventDefault();
      var p = stagePoint(e.clientX, e.clientY);
      zoomAt(Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0018)), p.x, p.y);
    }, { passive: false });
    lbStage.addEventListener('dblclick', function (e) {
      var p = stagePoint(e.clientX, e.clientY);
      if (st.s > 1.05) setT(1, 0, 0); else zoomAt(2.5, p.x, p.y);
    });
    lbStage.addEventListener('pointerdown', function (e) {
      lbStage.setPointerCapture(e.pointerId);
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (ids.length === 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        pinch = { dist: Math.hypot(a.x - b.x, a.y - b.y), s: st.s, x: st.x, y: st.y, c: stagePoint((a.x + b.x) / 2, (a.y + b.y) / 2) };
        drag = null;
      } else if (ids.length === 1) {
        drag = { x: e.clientX, y: e.clientY, ox: st.x, oy: st.y, moved: false };
        lbStage.classList.add('dragging');
      }
    });
    lbStage.addEventListener('pointermove', function (e) {
      if (!pointers[e.pointerId]) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (pinch && ids.length >= 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        var ns = clamp(pinch.s * Math.hypot(a.x - b.x, a.y - b.y) / pinch.dist);
        var c = stagePoint((a.x + b.x) / 2, (a.y + b.y) / 2);
        var k = ns / pinch.s;
        setT(ns, c.x - (pinch.c.x - pinch.x) * k, c.y - (pinch.c.y - pinch.y) * k);
      } else if (drag) {
        var dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 3) drag.moved = true;
        setT(st.s, drag.ox + dx, drag.oy + dy);
      }
    });
    var up = function (e) {
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      if (!Object.keys(pointers).length) {
        if (drag && !drag.moved && e.type === 'pointerup' && e.target === lbStage) closeLb();
        drag = null; lbStage.classList.remove('dragging');
      }
    };
    lbStage.addEventListener('pointerup', up);
    lbStage.addEventListener('pointercancel', up);
    lb.addEventListener('keydown', function (e) {
      var step = 60;
      if (e.key === 'Escape') { e.preventDefault(); closeLb(); }
      else if (e.key === '+' || e.key === '=') zoomAt(1.25, 0, 0);
      else if (e.key === '-' || e.key === '_') zoomAt(0.8, 0, 0);
      else if (e.key === '0') setT(1, 0, 0);
      else if (e.key === 'ArrowLeft') setT(st.s, st.x + step, st.y);
      else if (e.key === 'ArrowRight') setT(st.s, st.x - step, st.y);
      else if (e.key === 'ArrowUp') setT(st.s, st.x, st.y + step);
      else if (e.key === 'ArrowDown') setT(st.s, st.x, st.y - step);
      else if (e.key === 'Tab') {
        var f = $$('.lb-bar button', lb);
        var i = f.indexOf(d.activeElement);
        e.preventDefault();
        f[(i + (e.shiftKey ? -1 : 1) + f.length) % f.length].focus();
      } else return;
      e.stopPropagation();
    });
  }
  function clamp(s) { return Math.min(maxS, Math.max(1, s)); }
  function stagePoint(cx, cy) {   // point relative to the stage centre
    var r = lbStage.getBoundingClientRect();
    return { x: cx - (r.left + r.width / 2), y: cy - (r.top + r.height / 2) };
  }
  function setT(s, x, y) {
    st.s = clamp(s);
    if (st.s === 1) { x = 0; y = 0; }
    var w = lbImg.clientWidth * st.s, h = lbImg.clientHeight * st.s, r = lbStage.getBoundingClientRect();
    var mx = Math.max(0, (w - r.width) / 2 + 40), my = Math.max(0, (h - r.height) / 2 + 40);
    st.x = Math.max(-mx, Math.min(mx, x)); st.y = Math.max(-my, Math.min(my, y));
    lbImg.style.transform = 'translate(' + st.x + 'px,' + st.y + 'px) scale(' + st.s + ')';
    lbZoomv.textContent = Math.round(st.s * 100) + '%';
  }
  function zoomAt(f, px, py) {
    var ns = clamp(st.s * f), k = ns / st.s;
    setT(ns, px - (px - st.x) * k, py - (py - st.y) * k);
  }
  function openLb(img) {
    if (!lb) buildLb();
    lbReturn = img;
    var fg = img.closest('figure');
    emit('zoom', { id: (fg && fg.id) || img.getAttribute('src') });
    lbImg.src = img.dataset.zoom || img.currentSrc || img.src;
    lbImg.alt = img.alt;
    var cap = img.closest('figure') && img.closest('figure').querySelector('figcaption');
    lbCap.innerHTML = cap ? cap.innerHTML : '';
    lbCap.dir = root.dir;
    lb.hidden = false;
    d.body.style.overflow = 'hidden';
    var fit = function () {
      var nat = lbImg.naturalWidth || 1;
      maxS = /\.svg$/.test(lbImg.src) ? 10 : Math.max(4, 2 * nat / Math.max(1, lbImg.clientWidth));
      setT(1, 0, 0);
    };
    if (lbImg.complete) fit(); else lbImg.onload = fit;
    $('.lb-bar [data-a="close"]', lb).focus();
  }
  function closeLb() {
    if (!lb || lb.hidden) return;
    lb.hidden = true; d.body.style.overflow = ''; pointers = {}; pinch = drag = null;
    if (lbReturn) lbReturn.focus();
  }
  $$('img.zoomable').forEach(function (img) {
    img.addEventListener('click', function () { openLb(img); });
    img.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openLb(img); }
    });
  });

  /* ---------- search ---------- */
  var dlg = $('#search-dlg'), input = $('#search-input'), list = $('#search-results'), status = $('#search-status');
  var docs = null, normDocs = null, sel = -1, searchReturn = null, timer = null;
  var MAP = { 'ي': 'ی', 'ى': 'ی', 'ئ': 'ی', 'ك': 'ک', 'ة': 'ه', 'ۀ': 'ه', 'أ': 'ا', 'إ': 'ا', 'ٱ': 'ا', 'آ': 'ا', 'ؤ': 'و' };
  var DROP = /[\u064B-\u065F\u0670\u0640\u200B-\u200F\u202A-\u202E\u2066-\u2069]/;
  function normChar(c) {
    if (DROP.test(c)) return '';
    if (MAP[c]) return MAP[c];
    var code = c.charCodeAt(0);
    if (code >= 0x6F0 && code <= 0x6F9) return String(code - 0x6F0);
    if (code >= 0x660 && code <= 0x669) return String(code - 0x660);
    return c.toLowerCase();
  }
  function norm(s) {   // Persian-aware normalisation: ی/ي, ک/ك, ZWNJ, diacritics, digits
    var o = '';
    for (var i = 0; i < s.length; i++) o += normChar(s[i]);
    return o;
  }
  function normMap(s) {   // normalised string + index map back to the original
    var o = '', m = [];
    for (var i = 0; i < s.length; i++) { var n = normChar(s[i]); for (var k = 0; k < n.length; k++) { o += n[k]; m.push(i); } }
    m.push(s.length);
    return { s: o, m: m };
  }
  function loadIndex(cb) {
    if (docs) return cb();
    status.textContent = S.loading || '…';
    var sc = d.createElement('script');
    sc.src = 'search-index.js';
    sc.onload = function () {
      docs = window.__SEARCH_DOCS__ || [];
      normDocs = docs.map(function (x) { return { t: norm(x[1]), x: norm(x[3]) }; });
      cb();
    };
    sc.onerror = function () { status.textContent = S.no_results; };
    d.head.appendChild(sc);
  }
  function esc(s) { return s.replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function mark(text, terms) {
    var nm = normMap(text), spans = [];
    terms.forEach(function (t) {
      var i = 0;
      while ((i = nm.s.indexOf(t, i)) !== -1) { spans.push([nm.m[i], nm.m[i + t.length]]); i += t.length; }
    });
    spans.sort(function (a, b) { return a[0] - b[0]; });
    var out = '', pos = 0;
    spans.forEach(function (sp) {
      if (sp[0] < pos) return;
      out += esc(text.slice(pos, sp[0])) + '<mark>' + esc(text.slice(sp[0], sp[1])) + '</mark>';
      pos = sp[1];
    });
    return out + esc(text.slice(pos));
  }
  function snippet(text, terms) {
    var nm = normMap(text), first = -1;
    terms.forEach(function (t) { var i = nm.s.indexOf(t); if (i >= 0 && (first < 0 || i < first)) first = i; });
    if (first < 0) return mark(text.slice(0, 160), terms);
    var o = nm.m[first], a = Math.max(0, o - 70), b = Math.min(text.length, o + 150);
    while (a > 0 && text[a] !== ' ') a--;
    return (a > 0 ? '… ' : '') + mark(text.slice(a, b).trim(), terms) + (b < text.length ? ' …' : '');
  }
  function count(h, t) { var n = 0, i = 0; while ((i = h.indexOf(t, i)) !== -1 && n < 50) { n++; i += t.length; } return n; }
  function runSearch() {
    var q = norm(input.value.trim());
    var terms = q.split(/[\s،,؛;:.!?()«»"']+/).filter(function (t) { return t.length > 0; });
    list.innerHTML = ''; sel = -1;
    if (q.replace(/\s/g, '').length < 2) { status.textContent = S.search_hint; return; }
    var hits = [];
    for (var i = 0; i < docs.length; i++) {
      var nd = normDocs[i], score = 0, ok = true;
      for (var k = 0; k < terms.length; k++) {
        var ct = count(nd.t, terms[k]), cx = count(nd.x, terms[k]);
        if (!ct && !cx) { ok = false; break; }
        score += ct * 12 + Math.min(cx, 20);
      }
      if (!ok) continue;
      if (terms.length > 1 && (nd.t + ' ' + nd.x).indexOf(q) !== -1) score += 15;
      if (nd.t === q) score += 30;
      hits.push([score, i]);
    }
    hits.sort(function (a, b) { return b[0] - a[0]; });
    status.textContent = hits.length ? (S.results || '{n}').replace('{n}', RTL ? String(hits.length).replace(/\d/g, function (c) { return '۰۱۲۳۴۵۶۷۸۹'[c]; }) : hits.length) : S.no_results;
    hits.slice(0, 40).forEach(function (h, n) {
      var x = docs[h[1]];
      var li = d.createElement('li');
      li.id = 'sr-' + n; li.setAttribute('role', 'option'); li.setAttribute('aria-selected', 'false');
      li.innerHTML = '<a href="' + esc(x[0]) + '" tabindex="-1">' + (x[2] ? '<span class="r-c">' + esc(x[2]) + '</span>' : '') +
        '<span class="r-t">' + mark(x[1], terms) + '</span><span class="r-s">' + snippet(x[3], terms) + '</span></a>';
      list.appendChild(li);
    });
  }
  function select(i) {
    var items = $$('li', list);
    if (!items.length) return;
    sel = (i + items.length) % items.length;
    items.forEach(function (li, k) { li.setAttribute('aria-selected', String(k === sel)); });
    input.setAttribute('aria-activedescendant', items[sel].id);
    items[sel].scrollIntoView({ block: 'nearest' });
  }
  function openSearch() {
    if (!dlg) return;
    searchReturn = d.activeElement;
    dlg.hidden = false; d.body.style.overflow = 'hidden';
    input.focus(); input.select();
    loadIndex(function () { if (input.value) runSearch(); else status.textContent = S.search_hint; });
  }
  function closeSearch() {
    if (!dlg || dlg.hidden) return;
    dlg.hidden = true; d.body.style.overflow = '';
    if (searchReturn && searchReturn.focus) searchReturn.focus();
  }
  if (dlg) {
    $('#search-btn').addEventListener('click', openSearch);
    $('[data-close-search]', dlg).addEventListener('click', closeSearch);
    dlg.addEventListener('click', function (e) { if (e.target === dlg) closeSearch(); });
    input.addEventListener('input', function () { clearTimeout(timer); timer = setTimeout(function () { if (docs) runSearch(); }, 90); });
    /* index.html?q=term opens the search with that term (the WebSite SearchAction in the JSON-LD points here) */
    try { var q0 = new URLSearchParams(location.search).get('q'); if (q0) { input.value = q0; openSearch(); } } catch (e) { /* old browser */ }
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') { e.preventDefault(); select(sel + 1); }
      else if (e.key === 'ArrowUp') { e.preventDefault(); select(sel - 1); }
      else if (e.key === 'Enter') {
        var a = $('li[aria-selected="true"] a', list) || $('li a', list);
        if (a) { e.preventDefault(); closeSearch(); location.href = a.href; }
      } else if (e.key === 'Escape') { e.preventDefault(); closeSearch(); }
    });
    dlg.addEventListener('keydown', function (e) {
      if (e.key === 'Tab') { e.preventDefault(); (d.activeElement === input ? $('[data-close-search]', dlg) : input).focus(); }
      if (e.key === 'Escape') closeSearch();
    });
    list.addEventListener('click', function (e) { if (e.target.closest('a')) closeSearch(); });
  }

  /* ---------- reading progress, bookmarks, motion ----------
     Everything lives in localStorage under one key per language; nothing leaves the browser. */
  var REDUCE = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
  var LANG = S.lang || root.lang, PAGES = S.pages || {};
  var SLUG = root.dataset.slug, KIND = root.dataset.kind;
  var TRACKED = !!PAGES[SLUG];
  var PKEY = 'book-progress:' + LANG;
  var live = $('#live');
  var FA_DIG = '۰۱۲۳۴۵۶۷۸۹';
  function L(x) { x = String(x); return LANG === 'fa' ? x.replace(/\d/g, function (c) { return FA_DIG[+c]; }) : x; }
  function fmt(t, o) { return String(t || '').replace(/\{(\w+)\}/g, function (_, k) { return o[k] != null ? o[k] : ''; }); }
  function pct(n) { return LANG === 'fa' ? L(n) + '٪' : n + '%'; }
  function say(t) { if (live) { live.textContent = ''; setTimeout(function () { live.textContent = t; }, 30); } }
  /* schema: v1 = read/max/last/marks; v2 adds g (gamification state, owned by game.js). migrate() upgrades in place. */
  var SCHEMA = 2;
  function blank() { return { v: SCHEMA, read: {}, max: {}, last: null, marks: [], g: null }; }
  function valid(o) { return o && (o.v === 1 || o.v === 2) && typeof o.read === 'object' && Array.isArray(o.marks); }
  function migrate(o) {
    o.max = o.max || {};
    if (o.v === 1) { o.v = 2; o.g = null; }
    if (!('g' in o)) o.g = null;
    return o;
  }
  function load() {
    try { var o = JSON.parse(store.get(PKEY) || 'null'); if (valid(o)) return migrate(o); } catch (e) { /* corrupt */ }
    return blank();
  }
  function emit(name, detail) { try { d.dispatchEvent(new CustomEvent('book:' + name, { detail: detail || {} })); } catch (e) { /* old browser */ } }
  var P = load();
  function save() { store.set(PKEY, JSON.stringify(P)); }
  /* shared with game.js: always call get() (import/reset replace the object) */
  window.BookStore = {
    get: function () { return P; }, save: function () { save(); }, key: PKEY, lang: LANG, slug: SLUG, tracked: TRACKED,
    pages: PAGES, say: function (t) { say(t); }, refresh: function () { refreshAll(); }
  };
  var chapters = Object.keys(PAGES).filter(function (k) { return PAGES[k][2] > 0; });
  function setRing(svg, f) { if (svg) svg.style.setProperty('--p', String(Math.round(Math.max(0, Math.min(1, f)) * 100))); }
  function bookFrac() {
    var r = chapters.filter(function (k) { return P.read[k]; }).length;
    return { r: r, n: chapters.length, f: chapters.length ? r / chapters.length : 0 };
  }

  /* read state painted on every link that carries data-slug (sidebar, chips, home contents) */
  function paintLinks() {
    $$('[data-slug]').forEach(function (a) {
      if (a === root) return;
      var s = a.dataset.slug, done = !!P.read[s], part = !done && (P.max[s] || 0) > 0.05;
      a.classList.toggle('is-read', done);
      a.classList.toggle('in-prog', part);
      if (a.classList.contains('sb-link')) {
        var st = $('.sb-st', a);
        if (!st) { st = d.createElement('span'); st.className = 'sb-st'; a.appendChild(st); }
        st.innerHTML = done ? '<span class="vh">(' + S.is_read + ')</span>' : part ? '<span class="vh">(' + S.in_progress + ')</span>' : '';
        if (part) st.style.setProperty('--p', String(Math.round(P.max[s] * 100))); else st.style.removeProperty('--p');
      }
    });
    $$('.pc-prog').forEach(function (el) {
      var lo = +el.dataset.lo, hi = +el.dataset.hi, n = 0, r = 0;
      chapters.forEach(function (k) { var c = PAGES[k][2]; if (c >= lo && c <= hi) { n++; if (P.read[k]) r++; } });
      el.hidden = false;
      setRing($('svg', el), n ? r / n : 0);
      $('.pc-pt', el).textContent = fmt(S.part_prog, { r: L(r), n: L(n) });
      el.classList.toggle('done', n > 0 && r === n);
    });
    var c = $('.mk-n');
    if (c) { c.textContent = P.marks.length ? L(P.marks.length) : ''; c.parentNode.classList.toggle('has', P.marks.length > 0); }
  }

  function continueTarget() {
    var l = P.last;
    if (!l || !PAGES[l.s]) return null;
    return { href: l.s + '.html' + (l.h ? '#' + l.h : ''), title: PAGES[l.s][0], f: l.f || 0, s: l.s };
  }
  function wireContinue(a, withTitle) {
    var t = continueTarget();
    if (!a) return;
    if (!t || (P.read[t.s] && t.f > 0.97)) { a.hidden = true; return; }
    a.hidden = false;
    a.href = t.href;
    var lab = $('.rp-ct', a);
    if (lab && withTitle) lab.textContent = S['continue'] + ': ' + t.title + ' · ' + pct(Math.round(Math.max(t.f, P.max[t.s] || 0) * 100));
    a.onclick = function () { try { sessionStorage.setItem('book-resume', JSON.stringify({ s: t.s, f: t.f })); } catch (e) { /* ignore */ } };
  }
  function paintSummary() {
    var b = bookFrac(), p = Math.round(b.f * 100);
    var line = b.r ? fmt(S.progress_line, { r: L(b.r), n: L(b.n) }) : S.progress_empty;
    var rp = $('#rp');
    if (rp) {
      rp.hidden = false;
      setRing($('svg', rp), b.f); $('.rp-pct', rp).textContent = pct(p); $('.rp-line', rp).textContent = line;
      wireContinue($('.rp-cont', rp), true);
    }
    var dl = $('#my-dlg');
    if (dl) {
      setRing($('.my-prog svg', dl), b.f); $('.my-pct', dl).textContent = pct(p); $('.my-line', dl).textContent = line;
      wireContinue($('.my-cont', dl), false);
    }
  }

  /* ---- per-page tracking: top bar, auto-read at 90 %, last position ---- */
  var bar = $('.rbar i'), totop = $('#totop'), art = $('article.content');
  var readBtn = $('#read-tog'), userUnread = false, lastSave = 0;
  function syncReadBtn() {
    if (!readBtn) return;
    var on = !!P.read[SLUG];
    readBtn.hidden = false;
    readBtn.setAttribute('aria-pressed', String(on));
    readBtn.classList.toggle('on', on);
    $('span', readBtn).textContent = on ? S.is_read : S.mark_read;
    readBtn.title = on ? S.unmark_read : S.mark_read;
  }
  function setRead(on, quiet) {
    if (on) P.read[SLUG] = Date.now(); else delete P.read[SLUG];
    save(); syncReadBtn(); paintLinks();
    emit('read', { slug: SLUG, on: on });
    if (!quiet) say(on ? S.marked_read_msg : S.unmarked_read_msg);
    if (on && readBtn && !REDUCE) { readBtn.classList.remove('pop'); void readBtn.offsetWidth; readBtn.classList.add('pop'); }
  }
  if (readBtn && TRACKED) {
    syncReadBtn();
    readBtn.addEventListener('click', function () { var on = !P.read[SLUG]; userUnread = !on; setRead(on); });
  }
  function topHeading() {
    var hs = $$('article.content h2[id]:not(.qz-h), article.content h3[id]'), id = '';
    for (var i = 0; i < hs.length; i++) { if (hs[i].getBoundingClientRect().top < 120) id = hs[i].id; else break; }
    return id;
  }
  function docFrac() {
    var m = d.documentElement.scrollHeight - innerHeight;
    return m > 0 ? Math.min(1, Math.max(0, scrollY / m)) : 1;
  }
  function artFrac() {
    if (!art) return docFrac();
    var r = art.getBoundingClientRect();
    return r.height > 0 ? Math.min(1, Math.max(0, (innerHeight - r.top) / r.height)) : 1;
  }
  function remember(force) {
    if (!TRACKED) return;
    var now = Date.now();
    if (!force && now - lastSave < 800) return;
    lastSave = now;
    var f = docFrac();
    P.last = { s: SLUG, f: Math.round(f * 1000) / 1000, h: topHeading(), t: now };
    save();
  }
  var ticking = false, scrolled = false;
  function onScroll() {
    ticking = false;
    var f = docFrac();
    if (bar) bar.style.transform = 'scaleX(' + f + ')';
    if (totop) { totop.hidden = scrollY < 500; setRing($('svg', totop), f); }
    if (!TRACKED || !scrolled) return;
    var a = artFrac();
    if (a > (P.max[SLUG] || 0) + 0.02) { P.max[SLUG] = Math.round(a * 100) / 100; }
    if (a >= 0.9 && !P.read[SLUG] && !userUnread) setRead(true);
    remember(false);
  }
  addEventListener('scroll', function () { scrolled = true; if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } }, { passive: true });
  addEventListener('resize', function () { if (!ticking) { ticking = true; requestAnimationFrame(onScroll); } });
  if (TRACKED) {
    // a page becomes "where you left off" once you scroll it or stay on it for 15 s
    var opened = Date.now();
    var leave = function () { if (scrolled || Date.now() - opened > 15000) remember(true); };
    addEventListener('pagehide', leave);
    d.addEventListener('visibilitychange', function () { if (d.visibilityState === 'hidden') leave(); });
  }
  if (totop) totop.addEventListener('click', function () {
    window.scrollTo({ top: 0, behavior: REDUCE ? 'auto' : 'smooth' });
    var m = $('#main'); if (m) m.focus({ preventScroll: true });
  });
  /* resume position after "continue reading" */
  try {
    var rs = JSON.parse(sessionStorage.getItem('book-resume') || 'null');
    if (rs && rs.s === SLUG) {
      sessionStorage.removeItem('book-resume');
      var go = function () { var m = d.documentElement.scrollHeight - innerHeight; if (m > 0 && rs.f > 0) window.scrollTo(0, rs.f * m); };
      if (d.readyState === 'complete') go(); else addEventListener('load', go);
    }
  } catch (e) { /* ignore */ }

  /* ---- bookmarks on section headings ---- */
  function headText(h) {
    var c = h.cloneNode(true);
    $$('.hbm, .hanchor, .anchor, .headerlink', c).forEach(function (x) { x.remove(); });
    return c.textContent.replace(/[\u200e\u200f]/g, '').replace(/\s+/g, ' ').trim();
  }
  function markIndex(s, id) { for (var i = 0; i < P.marks.length; i++) if (P.marks[i].s === s && P.marks[i].id === id) return i; return -1; }
  function syncHeadBtn(h, b) {
    var on = markIndex(SLUG, h.id) >= 0, t = headText(h);
    b.setAttribute('aria-pressed', String(on));
    b.setAttribute('aria-label', fmt(on ? S.bookmark_remove : S.bookmark_add, { t: t }));
    b.title = fmt(on ? S.bookmark_remove : S.bookmark_add, { t: '' }).replace(/[:：]\s*$/, '');
    h.classList.toggle('marked', on);
  }
  var headBtns = [];
  if (TRACKED) {
    $$('article.content h2[id]:not(.qz-h), article.content h3[id]').forEach(function (h) {
      if (h.closest('.page-head')) return;
      var b = d.createElement('button');
      b.type = 'button'; b.className = 'hbm';
      b.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 3h12v18l-6-4.5L6 21z"/></svg>';
      h.appendChild(b);
      headBtns.push([h, b]);
      syncHeadBtn(h, b);
      b.addEventListener('click', function (e) {
        e.preventDefault(); e.stopPropagation();
        var i = markIndex(SLUG, h.id);
        if (i >= 0) { P.marks.splice(i, 1); say(S.unbookmarked_msg); }
        else { P.marks.unshift({ s: SLUG, id: h.id, t: headText(h), ts: Date.now() }); say(S.bookmarked_msg); emit('mark', { n: P.marks.length }); }
        save(); syncHeadBtn(h, b); paintLinks(); renderMarks();
      });
    });
  }
  function renderMarks() {
    var ul = $('#mk-list'); if (!ul) return;
    ul.innerHTML = '';
    P.marks.forEach(function (m, i) {
      var pg = PAGES[m.s]; if (!pg) return;
      var li = d.createElement('li');
      li.innerHTML = '<a href="' + esc(m.s) + '.html#' + esc(m.id) + '"><span class="mk-t"></span><span class="mk-p"></span></a>' +
        '<button type="button" class="icon-btn mk-del"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6 6 18"/></svg></button>';
      $('.mk-t', li).textContent = m.t; $('.mk-p', li).textContent = pg[0];
      var del = $('.mk-del', li);
      del.setAttribute('aria-label', fmt(S.bookmark_remove, { t: m.t }));
      del.addEventListener('click', function () {
        P.marks.splice(i, 1); save(); renderMarks(); paintLinks(); say(S.unbookmarked_msg);
        headBtns.forEach(function (x) { syncHeadBtn(x[0], x[1]); });
        var nx = $$('.mk-del', ul)[Math.min(i, P.marks.length - 1)]; (nx || $('[data-close-my]')).focus();
      });
      $('a', li).addEventListener('click', function () { closeMy(); });
      ul.appendChild(li);
    });
    var em = $('.mk-empty'); if (em) em.hidden = P.marks.length > 0;
  }

  /* ---- "my reading" dialog ---- */
  var my = $('#my-dlg'), myReturn = null;
  function openMy() {
    if (!my) return;
    myReturn = d.activeElement; renderMarks(); paintSummary();
    my.hidden = false; d.body.style.overflow = 'hidden';
    var c = $('[data-close-my]', my); if (c) c.focus();
  }
  function closeMy() {
    if (!my || my.hidden) return;
    my.hidden = true; d.body.style.overflow = '';
    if (myReturn && myReturn.focus) myReturn.focus();
  }
  if (my) {
    $$('#my-btn, [data-open-my]').forEach(function (b) { b.addEventListener('click', openMy); });
    $('[data-close-my]', my).addEventListener('click', closeMy);
    my.addEventListener('click', function (e) { if (e.target === my) closeMy(); });
    my.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { e.preventDefault(); closeMy(); return; }
      if (e.key === 'Tab') {
        var f = $$('a[href]:not([hidden]), button:not([disabled]), input', my).filter(function (x) { return x.offsetParent !== null || x.type === 'file'; });
        if (!f.length) return;
        var i = f.indexOf(d.activeElement);
        if (e.shiftKey && i <= 0) { e.preventDefault(); f[f.length - 1].focus(); }
        else if (!e.shiftKey && i === f.length - 1) { e.preventDefault(); f[0].focus(); }
      }
    });
    $('[data-act="export"]', my).addEventListener('click', function () {
      var blob = new Blob([JSON.stringify({ app: 'ceph-book-progress', lang: LANG, exported: new Date().toISOString(), data: P }, null, 1)], { type: 'application/json' });
      var a = d.createElement('a');
      a.href = URL.createObjectURL(blob); a.download = 'ceph-book-progress-' + LANG + '.json';
      d.body.appendChild(a); a.click();
      setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    });
    $('#my-import').addEventListener('change', function () {
      var f = this.files && this.files[0], inp = this;
      if (!f) return;
      var rd = new FileReader();
      rd.onload = function () {
        try {
          var o = JSON.parse(rd.result), data = o && o.app === 'ceph-book-progress' ? o.data : o;
          if (!valid(data)) throw new Error('bad');
          P = migrate(data); save(); refreshAll(); say(S.import_ok); emit('replaced');
        } catch (e) { say(S.import_bad); }
        inp.value = '';
      };
      rd.readAsText(f);
    });
    $('[data-act="reset"]', my).addEventListener('click', function () {
      if (!confirm(S.reset_confirm)) return;
      P = blank(); save(); refreshAll(); say(S.reset_ok); emit('replaced');
    });
  }
  function refreshAll() {
    paintLinks(); paintSummary(); renderMarks(); syncReadBtn();
    headBtns.forEach(function (x) { syncHeadBtn(x[0], x[1]); });
  }
  paintLinks(); paintSummary();
  onScroll();

  /* ---- motion: scroll reveal and hero counters (skipped for reduced motion) ---- */
  if (!REDUCE && 'IntersectionObserver' in window) {
    var targets = $$('.hsec-head, .hcard, .pcard, .home-toc li, .about, .content figure, .content > h2, .pg-card');
    var rio = new IntersectionObserver(function (es) {
      es.forEach(function (en) { if (en.isIntersecting) { en.target.classList.add('in'); rio.unobserve(en.target); } });
    }, { rootMargin: '0px 0px -6% 0px' });
    targets.forEach(function (el) {
      if (el.getBoundingClientRect().top < innerHeight) return;   // already on screen: never hide it
      var sib = el.parentNode ? Array.prototype.indexOf.call(el.parentNode.children, el) : 0;
      el.style.setProperty('--rv-d', (sib % 6) * 60 + 'ms');
      el.classList.add('rv'); rio.observe(el);
    });
    addEventListener('beforeprint', function () { $$('.rv').forEach(function (el) { el.classList.add('in'); }); });
    var nums = $$('.stats b[data-n]');
    if (nums.length) {
      var cio = new IntersectionObserver(function (es) {
        es.forEach(function (en) {
          if (!en.isIntersecting) return;
          cio.unobserve(en.target);
          var el = en.target, n = +el.dataset.n, t0 = null;
          var step = function (ts) {
            if (t0 === null) t0 = ts;
            var k = Math.min(1, (ts - t0) / 1100), e = 1 - Math.pow(1 - k, 3);
            el.textContent = L(Math.round(n * e));
            if (k < 1) requestAnimationFrame(step);
          };
          el.textContent = L(0); requestAnimationFrame(step);
        });
      });
      nums.forEach(function (el) { cio.observe(el); });
    }
  }

  /* ---------- global keys ---------- */
  d.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    if (typing || (lb && !lb.hidden) || (dlg && !dlg.hidden) || (my && !my.hidden)) return;
    if (e.key === '/' || e.key === 's' || e.key === 'S') { e.preventDefault(); openSearch(); return; }
    if (e.key === 'Escape' && drawerOpen()) { setDrawer(false); return; }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      var back = (e.key === 'ArrowLeft') !== RTL;   // in rtl the "previous" page is on the right
      var l = $(back ? 'link[rel="prev"]' : 'link[rel="next"]');
      if (l) location.href = l.getAttribute('href');
    }
  });
})();
