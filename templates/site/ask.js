/* "Ask the book" panel of the web edition, loaded by site.js on the first click of the
   button. It POSTs {q} to ASK_ENDPOINT (the book-ask Worker, infra/book-ask) and shows the
   answer with links to the book sections it was written from. No cookies, no storage,
   no third-party code. */
(function () {
  'use strict';
  var d = document, S = {};
  try { S = JSON.parse(d.getElementById('site-data').textContent); } catch (e) { S = {}; }
  var A = S.ask || {}, T = A.s || {};
  var panel, form, input, out, sendBtn, opener, busy = false;

  function el(tag, cls, text) {
    var e = d.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  // inline **bold**, `code` and [n] citations; everything else stays text
  function inline(parent, text, sources) {
    var re = /(\*\*[^*]+\*\*|`[^`]+`|\[\d+\])/g, last = 0, m;
    while ((m = re.exec(text))) {
      if (m.index > last) parent.appendChild(d.createTextNode(text.slice(last, m.index)));
      var t = m[0];
      if (t[0] === '*') parent.appendChild(el('strong', null, t.slice(2, -2)));
      else if (t[0] === '`') { var c = el('code', null, t.slice(1, -1)); c.dir = 'ltr'; parent.appendChild(c); }
      else {
        var n = Number(t.slice(1, -1)), src = sources[n - 1];
        if (src) {
          var a = el('a', 'ask-cite', String(n));
          a.href = src.url; a.title = src.title + (src.section ? ' — ' + src.section : '');
          parent.appendChild(a);
        } else parent.appendChild(d.createTextNode(t));
      }
      last = m.index + t.length;
    }
    if (last < text.length) parent.appendChild(d.createTextNode(text.slice(last)));
  }

  function render(answer, sources) {
    var box = el('div', 'ask-answer');
    String(answer || '').split(/\n{2,}/).forEach(function (para) {
      var lines = para.split('\n');
      var items = lines.filter(function (l) { return /^\s*([-*•]|\d+\.)\s+/.test(l); });
      if (items.length && items.length === lines.filter(function (l) { return l.trim(); }).length) {
        var ul = el('ul');
        items.forEach(function (l) { var li = el('li'); inline(li, l.replace(/^\s*([-*•]|\d+\.)\s+/, ''), sources); ul.appendChild(li); });
        box.appendChild(ul);
      } else {
        lines.forEach(function (l, i) {
          if (/^\s*([-*•])\s+/.test(l)) { var p0 = el('p', 'ask-li'); inline(p0, '• ' + l.replace(/^\s*[-*•]\s+/, ''), sources); box.appendChild(p0); return; }
          if (!l.trim()) return;
          var p = el('p'); inline(p, l, sources); box.appendChild(p);
        });
      }
    });
    var shown = sources.filter(function (s) { return s.cited; });
    if (!shown.length) shown = sources.slice(0, 3);
    if (shown.length) {
      box.appendChild(el('h3', 'ask-src-h', T.sources || 'Sources'));
      var ol = el('ol', 'ask-src');
      shown.forEach(function (s) {
        var li = el('li'), a = el('a', null, s.title + (s.section ? ' — ' + s.section : ''));
        a.href = s.url;
        li.value = s.n;
        li.appendChild(a);
        ol.appendChild(li);
      });
      box.appendChild(ol);
    }
    return box;
  }

  function show(node) {
    out.textContent = '';
    out.appendChild(node);
  }

  function ask(q) {
    if (busy) return;
    busy = true;
    sendBtn.disabled = true;
    out.setAttribute('aria-busy', 'true');
    show(el('p', 'ask-wait', T.thinking || '…'));
    fetch(A.endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ q: q }),
      credentials: 'omit',
      referrerPolicy: 'no-referrer',
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; });
    }).then(function (res) {
      if (res.j && res.j.answer) {
        var box = render(res.j.answer, res.ok ? (res.j.sources || []) : []);
        if (res.j.lang) box.lang = res.j.lang;
        if (res.j.lang) box.dir = res.j.lang === 'fa' ? 'rtl' : 'ltr';
        show(box);
      } else show(el('p', 'ask-err', T.error || 'Error'));
    }).catch(function () {
      show(el('p', 'ask-err', T.error || 'Error'));
    }).then(function () {
      busy = false;
      sendBtn.disabled = false;
      out.removeAttribute('aria-busy');
    });
  }

  function build() {
    panel = el('div', 'ask-panel');
    panel.id = 'ask-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-labelledby', 'ask-h');
    var head = el('div', 'ask-head');
    var h = el('h2', null, T.title || 'Ask the book');
    h.id = 'ask-h';
    var x = el('button', 'icon-btn', '✕');
    x.type = 'button';
    x.setAttribute('aria-label', T.close || 'Close');
    x.addEventListener('click', close);
    head.appendChild(h);
    head.appendChild(x);
    panel.appendChild(head);
    panel.appendChild(el('p', 'ask-intro', T.intro || ''));
    form = el('form', 'ask-form');
    input = el('textarea');
    input.rows = 2;
    input.maxLength = 500;
    input.required = true;
    input.placeholder = T.placeholder || '';
    input.setAttribute('aria-label', T.title || 'Question');
    input.dir = 'auto';
    sendBtn = el('button', 'btn primary', T.send || 'Ask');
    sendBtn.type = 'submit';
    form.appendChild(input);
    form.appendChild(sendBtn);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      var q = input.value.replace(/\s+/g, ' ').trim();
      if (q.length >= 3) ask(q);
    });
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit ? form.requestSubmit() : form.dispatchEvent(new Event('submit')); }
    });
    panel.appendChild(form);
    out = el('div', 'ask-out');
    out.setAttribute('aria-live', 'polite');
    panel.appendChild(out);
    panel.appendChild(el('p', 'ask-note', T.note || ''));
    panel.addEventListener('keydown', function (e) { if (e.key === 'Escape') close(); });
    d.body.appendChild(panel);
  }

  function open(from) {
    opener = from || null;
    if (!panel) build();
    panel.hidden = false;
    if (opener) opener.setAttribute('aria-expanded', 'true');
    input.focus();
  }

  function close() {
    if (!panel) return;
    panel.hidden = true;
    if (opener) { opener.setAttribute('aria-expanded', 'false'); opener.focus(); }
  }

  window.bookAsk = { open: open, close: close };
})();
