/* Reading paths (tools/build_site.py, references/reading-paths.yaml).
   On paths.html: "Follow this path" buttons and a count of the steps already read.
   On every other page: if the reader follows a path and this page is a step of it, a note above the
   previous/next cards names the next step. The choice is one localStorage value (book-path);
   nothing leaves the browser, and without a choice or without data this script does nothing. */
(function () {
  'use strict';
  var d = document, root = d.documentElement;
  var D = window.__PATHS__;
  if (!D || !D.paths || !D.paths.length) return;
  var KEY = D.key, LANG = D.lang, S = D.s || {};
  var FA_DIG = '۰۱۲۳۴۵۶۷۸۹';
  function L(x) { x = String(x); return LANG === 'fa' ? x.replace(/\d/g, function (c) { return FA_DIG[+c]; }) : x; }
  function fmt(t, o) { return String(t || '').replace(/\{(\w+)\}/g, function (_, k) { return o[k] != null ? o[k] : ''; }); }
  function get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } }
  function set(v) { try { if (v) localStorage.setItem(KEY, v); else localStorage.removeItem(KEY); } catch (e) { /* private mode */ } }
  function byId(id) { for (var i = 0; i < D.paths.length; i++) if (D.paths[i].id === id) return D.paths[i]; return null; }
  function chosen() { var id = get(); return id ? byId(id) : null; }
  function el(tag, cls, text) { var n = d.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = text; return n; }

  /* ---- the note on a page of the chosen path ---- */
  function hint() {
    var p = chosen(), slug = root.dataset.slug;
    if (!p || !slug) return;
    var last = -1;
    p.steps.forEach(function (s, i) { if (s.slug === slug) last = i; });
    if (last < 0) return;
    var next = null;
    for (var j = last + 1; j < p.steps.length; j++) if (p.steps[j].slug !== slug) { next = p.steps[j]; break; }
    var box = el('aside', 'path-hint');
    box.setAttribute('role', 'note');
    box.setAttribute('aria-label', S.paths_hint_label || '');
    var top = el('div', 'ph-top');
    top.appendChild(el('span', 'ph-t', next
      ? fmt(S.paths_hint_on, { path: p.t, i: L(last + 1), n: L(p.steps.length) })
      : fmt(S.paths_hint_done, { path: p.t })));
    var more = el('a', 'ph-link', next ? S.paths_hint_path : S.paths_hint_all);
    more.href = 'paths.html' + (next ? '#path-' + p.id : '');
    top.appendChild(more);
    var stop = el('button', 'ph-stop', S.paths_hint_stop);
    stop.type = 'button';
    stop.addEventListener('click', function () { set(null); if (box.parentNode) box.parentNode.removeChild(box); });
    top.appendChild(stop);
    box.appendChild(top);
    if (next) {
      var a = el('a', 'ph-next');
      a.href = next.href;
      a.appendChild(el('span', 'ph-dir', S.paths_hint_next));
      a.appendChild(el('span', 'ph-nt', next.t));
      var meta = (next.o ? S.paths_hint_opt + ' · ' : '') + fmt(S.paths_hint_min, { n: L(next.m) });
      a.appendChild(el('span', 'ph-m', meta));
      box.appendChild(a);
    }
    var pager = d.querySelector('nav.pager');
    var host = pager ? pager.parentNode : (d.querySelector('main article.content') || d.querySelector('main'));
    if (!host) return;
    host.insertBefore(box, pager || null);
  }

  /* ---- paths.html: follow buttons and the read count ---- */
  function page() {
    var btns = [].slice.call(d.querySelectorAll('[data-follow]'));
    function paint() {
      var cur = get();
      btns.forEach(function (b) {
        var on = b.dataset.follow === cur;
        b.hidden = false;
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
        b.classList.toggle('is-on', on);
        var sec = b.closest('.rtp');
        if (sec) sec.classList.toggle('is-following', on);
      });
    }
    btns.forEach(function (b) {
      b.addEventListener('click', function () { set(get() === b.dataset.follow ? null : b.dataset.follow); paint(); });
    });
    paint();
    var st = window.BookStore && window.BookStore.get && window.BookStore.get();
    if (!st || !st.read) return;
    [].slice.call(d.querySelectorAll('.rtp')).forEach(function (sec) {
      var tracked = 0, done = 0;
      [].slice.call(sec.querySelectorAll('a.rtp-link[data-slug]')).forEach(function (a) {
        var pg = window.BookStore.pages && window.BookStore.pages[a.dataset.slug];
        if (!pg || !(pg[2] > 0)) return;
        tracked++;
        if (st.read[a.dataset.slug]) done++;
      });
      var out = sec.querySelector('.rtp-prog');
      if (out && tracked && done) {
        out.textContent = fmt(S.paths_read_n, { r: L(done), n: L(tracked) });
        out.hidden = false;
      }
    });
  }

  function init() { if (root.dataset.slug === 'paths') page(); else hint(); }
  if (d.readyState === 'loading') d.addEventListener('DOMContentLoaded', init); else init();
})();
