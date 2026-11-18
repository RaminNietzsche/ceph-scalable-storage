/* Mounting, events and the static fallback for the simulators (sims.js part, loaded last).
 * CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc;
  function icon(d) { return '<svg class="sim-ic" viewBox="0 0 24 24" aria-hidden="true"><path d="' + d + '"/></svg>'; }
  function info(name, def) {
    return '<div class="sim-info" id="sim-info-' + name + '" hidden><p>' + tx(name + '_what') + '</p><h4>' + esc(T('follows')) + '</h4>' + S.refList(def.refs)
      + '<p class="sim-limit">' + tx(name + '_limit') + '</p></div>';
  }
  function stepper(st, def) {
    var n = def.steps(st), i = Math.min(st.i, n - 1);
    return '<div class="sim-stepper" role="group" aria-label="' + esc(T('seq_label')) + '">'
      + '<button type="button" class="sim-btn" data-act="prev"' + (i <= 0 ? ' disabled' : '') + '>' + esc(T('prev')) + '</button>'
      + '<button type="button" class="sim-btn pri" data-act="play" aria-pressed="' + !!st.playing + '">' + esc(T(st.playing ? 'pause' : 'play')) + '</button>'
      + '<button type="button" class="sim-btn" data-act="next"' + (i >= n - 1 ? ' disabled' : '') + '>' + esc(T('next')) + '</button>'
      + '<input type="range" min="0" max="' + (n - 1) + '" value="' + i + '" data-k="__i" aria-label="' + esc(T('seq_label')) + '" aria-valuetext="' + L(i + 1) + '/' + L(n) + '"></div>';
  }
  function frame(name, def, lab, href) {
    return '<div class="sim-head">' + icon(def.icon) + '<div class="sim-ttl"><span class="sim-tag">' + esc(T('lab_tag')) + '</span><h3>' + esc(T(name + '_t')) + '</h3></div>'
      + '<div class="sim-tools"><button type="button" class="sim-btn sm" data-act="__info" aria-expanded="false" aria-controls="sim-info-' + name + '">' + esc(T('info')) + '</button>'
      + '<button type="button" class="sim-btn sm" data-act="__reset">' + esc(T('reset')) + '</button>'
      + (lab || !href ? '' : '<a class="sim-btn sm" href="' + esc(href) + '">' + esc(T('open_lab')) + '</a>') + '</div></div>'
      + '<p class="sim-sub">' + tx(name + '_d') + '</p>' + info(name, def)
      + '<div class="sim-ctl"></div><div class="sim-out"></div><div class="vh" aria-live="polite"></div>';
  }
  // the figure for print and no-JS readers: the same view, of a fixed state, with every step shown
  S.staticHTML = function (name, strings, lang) {
    S.setStrings(strings, lang);
    var def = S.DEFS[name], st = def.defaults();
    if (def.fallbackState) st = def.fallbackState(st);
    return '<div class="sim-head">' + icon(def.icon) + '<div class="sim-ttl"><span class="sim-tag">' + esc(T('lab_tag')) + '</span><h3>' + esc(T(name + '_t')) + '</h3></div></div>'
      + '<p class="sim-sub">' + tx(name + '_d') + '</p><div class="sim-out">' + def.view(st, true) + '</div>'
      + '<div class="sim-info"><h4>' + esc(T('follows')) + '</h4>' + S.refList(def.refs) + '</div>';
  };
  if (NODE) return;

  var reduce = root.matchMedia && root.matchMedia('(prefers-reduced-motion: reduce)').matches;
  function mount(slot, lab) {
    var name = slot.getAttribute('data-sim'), def = S.DEFS[name];
    if (!def || slot.__sim) return;
    var st = def.defaults(), used = false, timer = null, deb = null;
    slot.__sim = true;
    var box = document.createElement('section');
    box.className = 'sim sim-' + name; box.setAttribute('aria-label', T(name + '_t'));
    box.innerHTML = frame(name, def, lab, slot.getAttribute('data-href'));
    slot.insertBefore(box, slot.firstChild);
    slot.classList.add('sim-on');
    var ctl = box.querySelector('.sim-ctl'), out = box.querySelector('.sim-out'), live = box.querySelector('.vh');
    function drawCtl() {
      var f = document.activeElement && box.contains(document.activeElement) ? document.activeElement.getAttribute('data-fid') || document.activeElement.getAttribute('data-k') : null;
      ctl.innerHTML = def.controls(st) + (def.steps ? stepper(st, def) : '');
      if (f) { var el = ctl.querySelector('[data-fid="' + f + '"]') || ctl.querySelector('[data-k="' + f + '"]'); if (el) el.focus(); }
    }
    function drawOut() {
      if (def.steps) st.i = Math.max(0, Math.min(st.i, def.steps(st) - 1));
      // controls that live in the output (e.g. the placement lab's comparison) keep keyboard focus too
      var a = document.activeElement, f = a && out.contains(a) ? a.getAttribute('data-fid') || a.getAttribute('data-k') : null;
      try { out.innerHTML = def.view(st, false); } catch (e) { out.innerHTML = '<p class="sim-warn">' + esc(T('error')) + '</p>'; }
      if (f) { var el = out.querySelector('[data-fid="' + f + '"]') || out.querySelector('[data-k="' + f + '"]'); if (el) el.focus(); }
      if (def.say) live.textContent = def.say(st);
    }
    function apply(r) {
      if (!r) return;
      if (r === 'all' || r === 'ctl' || r === 'outctl') drawCtl();
      if (r !== 'ctl') drawOut();
    }
    function touch() { if (!used) { used = true; document.dispatchEvent(new CustomEvent('sim:use', { detail: { sim: name } })); } }
    function stop() { if (timer) { clearInterval(timer); timer = null; } st.playing = false; }
    function step(d) {
      var n = def.steps(st);
      st.i = Math.max(0, Math.min(n - 1, st.i + d));
      if (st.i >= n - 1) stop();
      apply('outctl');
    }
    function act(a, el) {
      touch();
      if (a === '__info') {
        var p = box.querySelector('.sim-info'), open = el.getAttribute('aria-expanded') === 'true';
        el.setAttribute('aria-expanded', String(!open)); p.hidden = open; return;
      }
      if (a === '__reset') { stop(); st = def.defaults(); apply('all'); live.textContent = T('reset_done'); return; }
      if (a === 'prev') { stop(); step(-1); return; }
      if (a === 'next') { stop(); step(1); return; }
      if (a === 'play') {
        if (st.playing) { stop(); apply('ctl'); return; }
        if (st.i >= def.steps(st) - 1) st.i = 0;
        st.playing = true; apply('outctl');
        timer = setInterval(function () { if (!document.body.contains(box)) return stop(); step(1); }, reduce ? 3200 : 1700);
        return;
      }
      apply(def.act ? def.act(st, a, el) : null);
    }
    function input(el, immediate) {
      var k = el.getAttribute('data-k');
      if (!k) return;
      touch();
      var v = el.type === 'checkbox' ? el.checked : el.value;
      var run = function () {
        if (k === '__i') { stop(); st.i = +v; apply('outctl'); return; }
        apply(def.input(st, k, v, el));
      };
      clearTimeout(deb);
      if (immediate) run(); else deb = setTimeout(run, 250);
    }
    box.addEventListener('click', function (e) {
      var b = e.target.closest('[data-act],[data-set]');
      if (!b || !box.contains(b)) return;
      if (b.hasAttribute('data-set')) { touch(); apply(def.input(st, b.getAttribute('data-set'), b.getAttribute('data-v'), b)); var f = ctl.querySelector('[data-set="' + b.getAttribute('data-set') + '"][aria-checked="true"]'); if (f) f.focus(); return; }
      act(b.getAttribute('data-act'), b);
    });
    box.addEventListener('change', function (e) { if (e.target.matches('select,input[type=checkbox],input[type=range]')) input(e.target, true); else if (e.target.matches('input')) input(e.target, true); });
    box.addEventListener('input', function (e) { if (e.target.matches('input[type=number],input[type=text]')) input(e.target, false); else if (e.target.matches('input[type=range]')) input(e.target, true); });
    box.addEventListener('keydown', function (e) {
      var b = e.target.closest('[role=radio]');
      if (!b || (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight')) return;
      var all = Array.prototype.slice.call(b.parentNode.children), i = all.indexOf(b), rtl = getComputedStyle(b).direction === 'rtl';
      var d = (e.key === 'ArrowRight') !== rtl ? 1 : -1, nb = all[(i + d + all.length) % all.length];
      e.preventDefault(); nb.click();
    });
    apply('all');
  }
  function boot() {
    var cfg = root.__SIMS__;
    if (!cfg) return;
    S.setStrings(cfg.s, cfg.lang);
    var lab = (document.documentElement.getAttribute('data-slug') || '').indexOf('lab-') === 0;
    Array.prototype.forEach.call(document.querySelectorAll('.sim-slot[data-sim]'), function (s) { mount(s, lab); });
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot); else boot();
})(typeof self !== 'undefined' ? self : this);
