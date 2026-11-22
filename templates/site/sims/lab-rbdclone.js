/* RBD snapshots, clones, copy-up and flatten (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * Follows librbd's object-level behaviour: a child reads an object it does not have from the parent snapshot
 * (src/librbd/io/ObjectRequest.cc ObjectReadRequest::read_parent), a write to such an object first copies the whole
 * parent object up (src/librbd/io/CopyupRequest.cc), rbd_clone_copy_on_read does the same on reads, and flatten copies
 * every remaining object (src/librbd/operation/FlattenRequest.cc). A write to the parent after a snapshot makes RADOS
 * keep a clone of the old object (self-managed snapshots). */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, sel = h.sel, field = h.field, stat = h.stat;
  var N = 16, OBJ = 4;   // objects, MiB per object (rbd default object size 4 MiB, order 22)

  function fresh(cor) {
    var head = [];
    for (var i = 0; i < N; i++) head.push(i % 4 === 3 ? null : 'p' + i);   // some objects never written: sparse
    return { head: head, snap: null, radosClone: new Array(N).fill(false), child: null, cor: !!cor, copied: 0, parentReads: 0, log: [], flat: false };
  }
  function snapshot(m) { m.snap = m.head.slice(); m.radosClone = new Array(N).fill(false); m.log.push(['snap']); }
  function clone(m) { if (!m.snap) snapshot(m); m.child = new Array(N).fill(undefined); m.log.push(['clone']); }
  // what the child sees for object i, and where it comes from
  function childView(m, i) {
    if (!m.child) return { v: null, from: 'none' };
    if (m.child[i] !== undefined) return { v: m.child[i], from: 'child' };
    if (m.flat) return { v: null, from: 'child' };
    return { v: m.snap[i], from: m.snap[i] == null ? 'hole' : 'parent' };
  }
  function copyup(m, i) {
    if (m.snap[i] != null) { m.child[i] = m.snap[i]; m.copied += OBJ; }
    else m.child[i] = null;   // nothing in the parent: no data to copy
  }
  function childWrite(m, i, tag) {
    if (!m.child) return;
    var was = childView(m, i).from;
    if (was === 'parent') { copyup(m, i); m.log.push(['copyup', i]); }
    m.child[i] = tag; m.log.push(['cwrite', i, was]);
  }
  function childRead(m, i) {
    var v = childView(m, i);
    if (v.from === 'parent') { m.parentReads++; if (m.cor) { copyup(m, i); m.log.push(['cor', i]); } else m.log.push(['cread', i]); }
    else m.log.push(['cread_own', i]);
    return v.v;
  }
  function parentWrite(m, i, tag) {
    if (m.snap && !m.radosClone[i] && m.head[i] != null) { m.radosClone[i] = true; m.log.push(['rclone', i]); }
    m.head[i] = tag; m.log.push(['pwrite', i]);
  }
  function flatten(m) {
    if (!m.child) return;
    for (var i = 0; i < N; i++) if (m.child[i] === undefined) { if (m.snap[i] != null) { m.child[i] = m.snap[i]; m.copied += OBJ; } }
    m.flat = true; m.log.push(['flatten']);
  }

  S.X = S.X || {};
  S.X.rbdclone = {
    fresh: fresh, snapshot: snapshot, clone: clone, childView: childView, childWrite: childWrite, childRead: childRead, parentWrite: parentWrite, flatten: flatten,
    test: function (t) {
      var seed = 3; function rnd(n) { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed % n; }
      for (var run = 0; run < 80; run++) {
        var m = fresh(run % 2), model = null;
        snapshot(m); clone(m);
        model = m.snap.slice();      // what a full copy of the snapshot would read
        for (var s = 0; s < 40; s++) {
          var i = rnd(N), op = rnd(5), tag = 'w' + run + '_' + s;
          if (op === 0) { childWrite(m, i, tag); model[i] = tag; }
          else if (op === 1) { t.eq(childRead(m, i), model[i], 'child read = snapshot or own data ' + run + '/' + s); }
          else if (op === 2) { parentWrite(m, i, tag); }
          else if (op === 3 && rnd(10) === 0) { flatten(m); }
          else { for (var j = 0; j < N; j++) t.eq(childView(m, j).v, model[j], 'child view ' + run + '/' + s + '/' + j); }
        }
        if (!m.flat) { var own = m.child.filter(function (x) { return x !== undefined; }).length; flatten(m); t.eq(m.child.filter(function (x) { return x !== undefined; }).length >= own, true, 'flatten only adds objects'); }
        for (var k = 0; k < N; k++) t.eq(childView(m, k).v, model[k], 'after flatten ' + run + '/' + k);
        t.ok(m.copied <= N * OBJ * 1, 'each object is copied up at most once ' + run);
      }
      var a = fresh(false); snapshot(a); clone(a); childWrite(a, 0, 'x'); t.eq(a.copied, OBJ, 'a small write copies the whole 4 MiB object');
      childWrite(a, 3, 'y'); t.eq(a.copied, OBJ, 'no copy-up for an object the parent never wrote');
    }
  };

  function cell(label, cls, act, i, aria) { return '<button type="button" class="rc-c ' + cls + '" data-act="' + act + '" data-p="' + i + '" aria-label="' + esc(aria) + '">' + esc(label) + '</button>'; }
  S.DEFS.rbdclone = {
    icon: 'M6 3v12M6 15a3 3 0 103 3M18 9a3 3 0 10-3-3M18 9c0 5-12 3-12 9',
    defaults: function () { var m = fresh(false); snapshot(m); clone(m); m.log = []; return { m: m, op: 'write', cor: false, n: 0 }; },
    refs: [['src/librbd/io/ObjectRequest.cc :: ObjectReadRequest::read_parent, ObjectReadRequest::copyup', 'rbdclone_r1'],
           ['src/librbd/io/CopyupRequest.cc :: CopyupRequest', 'rbdclone_r2'],
           ['src/librbd/operation/FlattenRequest.cc', 'rbdclone_r3'],
           ['src/common/options/rbd.yaml.in :: rbd_clone_copy_on_read (false), rbd_default_clone_format (auto)', 'rbdclone_r4']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('rbdclone_op'), sel('op', [['write', T('rbdclone_op_w')], ['read', T('rbdclone_op_r')]], st.op))
        + '<label class="sim-f sim-chk"><span>rbd_clone_copy_on_read</span><input type="checkbox" data-k="cor"' + (st.cor ? ' checked' : '') + '></label>'
        + '<div class="lx-btns"><button type="button" class="sim-btn" data-act="flatten"' + (st.m.flat ? ' disabled' : '') + '>rbd flatten</button></div></div>'
        + '<p class="sim-note">' + tx('rbdclone_how') + '</p>';
    },
    view: function (st) {
      var m = st.m, i, p = '', s = '', c = '';
      for (i = 0; i < N; i++) {
        p += cell(m.head[i] == null ? '·' : m.head[i], m.head[i] == null ? 'hole' : m.radosClone[i] ? 'pw' : 'pd', 'pw', i, 'parent object ' + i);
        s += '<span class="rc-c ' + (m.snap[i] == null ? 'hole' : 'pd') + (m.radosClone[i] ? ' rc' : '') + '" title="' + esc(m.radosClone[i] ? T('rbdclone_rc') : '') + '">' + esc(m.snap[i] == null ? '·' : m.snap[i]) + '</span>';
        var v = childView(m, i);
        c += cell(v.v == null ? '·' : v.v, v.from === 'child' ? (v.v == null ? 'own hole' : 'own') : v.from === 'parent' ? 'ref' : 'hole', 'cw', i, 'child object ' + i);
      }
      var own = m.child.filter(function (x) { return x !== undefined; }).length;
      var last = m.log.slice(-6).reverse().map(function (e) { return '<li>' + tx('rbdclone_l_' + e[0], { i: e[1] != null ? L(e[1]) : '', f: e[2] ? T('rbdclone_f_' + e[2]) : '' }) + '</li>'; }).join('');
      return '<div class="sim-stats">' + stat(L(own) + ' / ' + L(N), T('rbdclone_s_own')) + stat(L(m.copied) + ' MiB', T('rbdclone_s_copied'), m.copied ? 'hot' : '')
        + stat(L(m.parentReads), T('rbdclone_s_preads')) + stat(L(m.radosClone.filter(Boolean).length), T('rbdclone_s_rclone')) + '</div>'
        + '<div class="rc-grid" dir="ltr"><h4>' + esc(T('rbdclone_parent')) + '</h4><div class="rc-row">' + p + '</div>'
        + '<h4>' + esc(T('rbdclone_snap')) + '</h4><div class="rc-row">' + s + '</div>'
        + '<h4>' + esc(T(m.flat ? 'rbdclone_child_flat' : 'rbdclone_child')) + '</h4><div class="rc-row">' + c + '</div></div>'
        + '<div class="lx-legend"><span class="rc-k own"></span>' + esc(T('rbdclone_k_own')) + ' <span class="rc-k ref"></span>' + esc(T('rbdclone_k_ref')) + ' <span class="rc-k hole"></span>' + esc(T('rbdclone_k_hole')) + ' <span class="rc-k rc"></span>' + esc(T('rbdclone_k_rc')) + '</div>'
        + (last ? '<ol class="rc-log">' + last + '</ol>' : '')
        + '<p class="sim-note">' + tx('rbdclone_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'op') { st.op = v; return 'out'; }
      if (k === 'cor') { st.cor = !!v; st.m.cor = st.cor; return 'out'; }
      return null;
    },
    act: function (st, a, el) {
      var i = el ? +el.getAttribute('data-p') : 0;
      st.n++;
      if (a === 'cw') { if (st.op === 'write') childWrite(st.m, i, 'c' + st.n); else childRead(st.m, i); return 'out'; }
      if (a === 'pw') { parentWrite(st.m, i, 'P' + st.n); return 'out'; }
      if (a === 'flatten') { flatten(st.m); return 'all'; }
      return null;
    },
    say: function (st) { return T('rbdclone_s_copied') + ': ' + L(st.m.copied) + ' MiB'; },
    fallbackState: function (st) { childWrite(st.m, 0, 'c1'); childWrite(st.m, 5, 'c2'); parentWrite(st.m, 1, 'P3'); return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
