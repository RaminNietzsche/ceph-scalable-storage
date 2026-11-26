/* Command-line reference (appendix "CLI Reference"): search and filters over
   window.CLIREF, written by tools/build_site.py from references/cli-reference.yaml. */
(function () {
  'use strict';
  var d = document, root = d.getElementById('clr');
  if (!root) return;
  var R = window.CLIREF;
  var list = d.getElementById('clr-list'), qEl = d.getElementById('clr-q'), toolEl = d.getElementById('clr-tool'),
      notesEl = d.getElementById('clr-notes'), countEl = d.getElementById('clr-count'), emptyEl = d.getElementById('clr-empty'),
      moreEl = d.getElementById('clr-more'), tagBox = d.getElementById('clr-tags');
  if (!R || !list) { if (list) list.textContent = ''; return; }
  var S = R.s, TAGS = R.tags, PAGE = 120, GH = 'https://github.com/ceph/ceph/';
  var rows = [], shown = 0, matches = [], sel = {}, NCMD = 0;

  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }
  function fmt(t, o) { return t.replace(/\{(\w+)\}/g, function (_, k) { return o[k] != null ? o[k] : ''; }); }
  function num(n) { return R.lang === 'fa' ? String(n).replace(/\d/g, function (x) { return '۰۱۲۳۴۵۶۷۸۹'[x]; }) : String(n); }
  function badge(i) {
    var t = TAGS[i];
    return '<span class="clr-tag t-' + t + '" title="' + esc(S['tag_' + t]) + '">' + t + '</span>';
  }
  function loc(p) {
    if (!p) return '';
    var m = /^(.*?)(?::(\d+))?$/.exec(p), path = m[1], line = m[2];
    var kind = /\/$|\*/.test(path) ? 'tree/' : 'blob/';
    var url = GH + kind + R.sha + '/' + path.replace(/\*.*$/, '') + (line ? '#L' + line : '');
    return '<a href="' + esc(url) + '" rel="noopener" dir="ltr">' + esc(p) + '</a>';
  }

  // flatten: one row per command, plus a "global options" row per tool
  R.tools.forEach(function (t) {
    if (t.go && t.go.length) rows.push({ tool: t.id, g: true, n: fmt(S.global, { tool: t.id }), t: [], o: t.go });
    t.cmds.forEach(function (c) { c.tool = t.id; rows.push(c); NCMD++; });
  });
  rows.forEach(function (r) {
    var hay = [r.tool, r.n, r.a || '', r.h || '', r.note ? r.note.d + ' ' + r.note.x : ''];
    (r.o || []).forEach(function (o) { hay.push(o[0], o[2] || ''); });
    r.hay = hay.join(' ').toLowerCase();
    var ot = {};
    (r.o || []).forEach(function (o) { o[1].forEach(function (i) { ot[i] = (ot[i] || 0) + 1; }); });
    r.ot = ot;
  });

  // tag chips
  tagBox.innerHTML = TAGS.map(function (t, i) {
    return '<button type="button" class="clr-chip t-' + t + '" data-i="' + i + '" aria-pressed="false" title="' + esc(S['tag_' + t]) + '">' + t + '</button>';
  }).join('');

  function summary(r) {
    var tags = r.t.map(badge).join(''), extra = '';
    var on = Object.keys(sel).filter(function (k) { return sel[k]; });
    on.forEach(function (k) {
      if (r.ot[k] && r.t.indexOf(+k) < 0) extra += '<span class="clr-otag">' + badge(+k) + ' ' + esc(fmt(S.opt_tagged, { n: num(r.ot[k]) })) + '</span>';
    });
    var name = r.g ? '<span class="clr-gname">' + esc(r.n) + '</span>'
      : '<code dir="ltr"><span class="clr-tool">' + esc(r.tool) + '</span> ' + esc(r.n) + '</code>';
    return '<summary>' + name + tags + extra + (r.note ? '<span class="clr-star" title="' + esc(S.note) + '">★</span>' : '') +
      (r.h ? '<span class="clr-help" dir="ltr" lang="en">' + esc(r.h) + '</span>' : '') + '</summary>';
  }
  function body(r) {
    var h = [];
    if (r.note) {
      h.push('<div class="clr-note"><b>' + esc(S.note) + ':</b> ' + esc(r.note.d) +
        '<div class="clr-ex"><span>' + esc(S.example) + ':</span> <code dir="ltr">' + esc(r.note.x) + '</code></div>' +
        (r.note.h ? '<div><span>' + esc(S.section) + ':</span> <a href="' + esc(r.note.h) + '">' + esc(r.note.l) + '</a></div>' : '') + '</div>');
    }
    var meta = [];
    if (r.a) meta.push('<span>' + esc(S.alias) + ': <code dir="ltr">' + esc(r.a) + '</code></span>');
    if (r.f && r.f.length) meta.push('<span>' + esc(S.flags) + ': <code dir="ltr">' + esc(r.f.join(', ')) + '</code></span>');
    if (r.s) meta.push('<span>' + esc(S.src) + ': ' + loc(r.s) + '</span>');
    if (r.d) meta.push('<span>' + esc(S.doc) + ': ' + loc(r.d) + '</span>');
    if (meta.length) h.push('<p class="clr-meta">' + meta.join('') + '</p>');
    if (r.o && r.o.length) {
      h.push('<table class="clr-opts"><caption>' + esc(S.options) + '</caption><tbody>' + r.o.map(function (o) {
        var x = o[3] || {};
        var nm = (x.q ? '[' : '') + esc(o[0]) + (x.q ? ']' : '') + (x.a ? ', ' + esc(x.a) : '') +
          (x.y ? ' <span class="clr-type">' + esc(x.y) + '</span>' : '');
        return '<tr><td class="clr-on"><code dir="ltr">' + nm + '</code></td><td class="clr-ot">' + o[1].map(badge).join('') +
          '</td><td class="clr-oh" dir="ltr" lang="en">' + esc(o[2] || (x.c ? '{' + x.c.join('|') + '}' : '')) + '</td></tr>';
      }).join('') + '</tbody></table>');
    }
    return h.join('');
  }
  function item(r) {
    var li = d.createElement('li');
    li.innerHTML = '<details>' + summary(r) + '<div class="clr-body"></div></details>';
    var det = li.firstChild;
    det.addEventListener('toggle', function () {
      var b = det.querySelector('.clr-body');
      if (det.open && !b.firstChild) b.innerHTML = body(r);
    });
    return li;
  }
  function renderMore() {
    var frag = d.createDocumentFragment(), end = Math.min(matches.length, shown + PAGE);
    for (var i = shown; i < end; i++) frag.appendChild(item(matches[i]));
    list.appendChild(frag);
    shown = end;
    var left = matches.length - shown;
    moreEl.hidden = left <= 0;
    if (left > 0) moreEl.textContent = fmt(S.more, { n: num(Math.min(left, PAGE)) + (left > PAGE ? ' / ' + num(left) : '') });
  }
  function apply(push) {
    var q = (qEl.value || '').toLowerCase().trim().split(/\s+/).filter(Boolean);
    var tool = toolEl.value, onlyN = notesEl.checked;
    var on = Object.keys(sel).filter(function (k) { return sel[k]; }).map(Number);
    var qs = q.join(' ');
    matches = rows.filter(function (r) {
      if (tool && r.tool !== tool) return false;
      if (onlyN && !r.note) return false;
      if (on.length && !on.some(function (k) { return r.t.indexOf(k) >= 0 || r.ot[k]; })) return false;
      for (var i = 0; i < q.length; i++) if (r.hay.indexOf(q[i]) < 0) return false;
      return true;
    });
    if (qs) {
      // names that match the query come first: exact, then prefix, then substring, then the rest
      var rank = function (r) {
        var n = (r.g ? '' : r.n).toLowerCase(), full = r.tool + ' ' + n;
        if (n === qs || full === qs) return 0;
        if (n.indexOf(qs) === 0 || full.indexOf(qs) === 0) return 1;
        if (n.indexOf(qs) >= 0) return 2;
        return 3;
      };
      matches = matches.map(function (r, i) { return [rank(r), i, r]; })
        .sort(function (a, b) { return a[0] - b[0] || a[1] - b[1]; }).map(function (x) { return x[2]; });
    }
    list.textContent = '';
    shown = 0;
    renderMore();
    countEl.textContent = fmt(S.shown, { n: num(matches.filter(function (r) { return !r.g; }).length), t: num(NCMD) });
    emptyEl.hidden = matches.length > 0;
    if (push && history.replaceState) {
      var p = [];
      if (qEl.value) p.push('q=' + encodeURIComponent(qEl.value));
      if (tool) p.push('tool=' + encodeURIComponent(tool));
      if (on.length) p.push('tag=' + on.map(function (k) { return TAGS[k]; }).join(','));
      if (onlyN) p.push('notes=1');
      history.replaceState(null, '', p.length ? '#' + p.join('&') : location.pathname + location.search);
    }
  }
  // initial state from the URL hash: #q=...&tool=rbd&tag=docs-only,usage-only&notes=1
  (location.hash.slice(1) || '').split('&').forEach(function (kv) {
    var i = kv.indexOf('='), k = kv.slice(0, i), v = decodeURIComponent(kv.slice(i + 1));
    if (k === 'q') qEl.value = v;
    else if (k === 'tool') toolEl.value = v;
    else if (k === 'notes') notesEl.checked = v === '1';
    else if (k === 'tag') v.split(',').forEach(function (t) { var j = TAGS.indexOf(t); if (j >= 0) sel[j] = true; });
  });
  Array.prototype.forEach.call(tagBox.querySelectorAll('.clr-chip'), function (b) {
    var i = +b.getAttribute('data-i');
    b.setAttribute('aria-pressed', sel[i] ? 'true' : 'false');
    b.addEventListener('click', function () {
      sel[i] = !sel[i];
      b.setAttribute('aria-pressed', sel[i] ? 'true' : 'false');
      apply(true);
    });
  });
  var tmr;
  qEl.addEventListener('input', function () { clearTimeout(tmr); tmr = setTimeout(function () { apply(true); }, 120); });
  toolEl.addEventListener('change', function () { apply(true); });
  notesEl.addEventListener('change', function () { apply(true); });
  moreEl.addEventListener('click', renderMore);
  var lg = root.querySelector('.clr-legend');
  if (lg && window.matchMedia && window.matchMedia('(max-width: 640px)').matches) lg.open = false;
  root.classList.add('ready');
  apply(false);
})();
