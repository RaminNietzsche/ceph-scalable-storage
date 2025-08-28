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
    lbImg.src = img.currentSrc || img.src;
    lbImg.alt = img.alt;
    var cap = img.closest('figure') && img.closest('figure').querySelector('figcaption');
    lbCap.innerHTML = cap ? cap.innerHTML : '';
    lbCap.dir = root.dir;
    lb.hidden = false;
    d.body.style.overflow = 'hidden';
    var fit = function () {
      var nat = lbImg.naturalWidth || 1;
      maxS = Math.max(4, 2.5 * nat / Math.max(1, lbImg.clientWidth));
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

  /* ---------- global keys ---------- */
  d.addEventListener('keydown', function (e) {
    if (e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey) return;
    var t = e.target, typing = t && (t.isContentEditable || /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName));
    if (typing || (lb && !lb.hidden) || (dlg && !dlg.hidden)) return;
    if (e.key === '/' || e.key === 's' || e.key === 'S') { e.preventDefault(); openSearch(); return; }
    if (e.key === 'Escape' && drawerOpen()) { setDrawer(false); return; }
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      var back = (e.key === 'ArrowLeft') !== RTL;   // in rtl the "previous" page is on the right
      var l = $(back ? 'link[rel="prev"]' : 'link[rel="next"]');
      if (l) location.href = l.getAttribute('href');
    }
  });
})();
