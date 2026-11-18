/* From object name to OSD: the placement pipeline step by step, with the five CRUSH bucket algorithms,
 * for one object or for the objects of an RBD image (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, C = h.C, T = h.T, L = h.L, esc = h.esc, pct = h.pct, sel = h.sel, field = h.field, numIn = h.numIn, seg = h.seg, stat = h.stat, clamp = h.clamp, bytes = h.bytes;
  var K = 1024, G = K * K * K;
  var ALGS = ['straw2', 'straw', 'list', 'tree', 'uniform'];
  var W16 = 65536, P44 = 17592186044416;
  function hx(n) { return '0x' + (n >>> 0).toString(16); }
  function w2(v) { return (Math.round(v / W16 * 100) / 100).toString(); }        /* 16.16 fixed point, two decimals */
  function hosts0() {
    var id = 0;
    return [[4, 4, 4], [4, 4, 4], [4, 4, 4], [4, 4, 4]].map(function (ws, i) {
      return { name: 'host' + (i + 1), bid: -2 - i, osds: ws.map(function (w) { return { id: id++, w: w, out: false, down: false }; }) };
    });
  }
  // bucket ids stay with their host (as in Ceph): the draws hash the ids, so renumbering would move data
  function nextBid(hs) { return hs.reduce(function (m, ho) { return Math.min(m, ho.bid); }, -1) - 1; }
  function clone(hs) { return hs.map(function (ho) { return { name: ho.name, bid: ho.bid, osds: ho.osds.map(function (o) { return { id: o.id, w: o.w, out: o.out, down: o.down }; }) }; }); }
  function osds(hs) { var a = []; hs.forEach(function (ho) { ho.osds.forEach(function (o) { a.push(o); }); }); return a; }
  function maxId(hs) { return osds(hs).reduce(function (m, o) { return Math.max(m, o.id); }, -1); }
  // root (type 11) -> hosts (type 1) -> osds, every bucket of one algorithm; the bucket weight a parent
  // sees is the one builder.c computes (uniform: size x the first item's weight); rule from add_simple_rule_at
  function model(hs, alg, fd) {
    var buckets = [], hitems = [], hw = [], names = { '-1': 'default' };
    hs.forEach(function (ho, i) {
      var ws = ho.osds.map(function (o) { return C.iweight(o.w); });
      buckets.push({ id: ho.bid, type: 1, alg: alg, items: ho.osds.map(function (o) { return o.id; }), weights: ws });
      hitems.push(ho.bid); hw.push(alg === 'uniform' ? ws.length * ws[0] : ws.reduce(function (a, b) { return a + b; }, 0));
      names[ho.bid] = ho.name;
    });
    buckets.push({ id: -1, type: 11, alg: alg, items: hitems, weights: hw });
    var m = C.makeMap(buckets, { 0: C.simpleRule(-1, fd === 'host' ? 1 : 0, false) }), dev = [], down = {}, all = osds(hs);
    for (var i = 0; i <= maxId(hs); i++) dev[i] = 0;
    all.forEach(function (o) { dev[o.id] = o.out ? 0 : 0x10000; if (o.down) down[o.id] = 1; });
    return { m: m, dev: dev, down: down, names: names };
  }
  function nm(md, id) { return id === C.NONE ? 'NONE' : id < 0 ? md.names[id] : 'osd.' + id; }
  function place(st, md, ps, trace) { return C.pgToUp(md.m, 0, ps, st.pool, st.pgp, st.size, md.dev, md.down, false, trace); }
  function setStr(a) { return '[' + a.map(function (o) { return o === C.NONE ? 'NONE' : o; }).join(',') + ']'; }

  /* ---------------------------------------------------------- the change to compare */
  function changed(st, hs) {
    var n = clone(hs), all = osds(n), o = all.filter(function (x) { return x.id === st.co; })[0] || all[0];
    if (st.chg === 'add') { n[n.length - 1].osds.push({ id: maxId(n) + 1, w: st.cw, out: false, down: false }); }
    else if (st.chg === 'host') { var b = maxId(n) + 1; n.push({ name: 'host' + (n.length + 1), bid: nextBid(n), osds: [0, 1, 2].map(function (i) { return { id: b + i, w: 4, out: false, down: false }; }) }); }
    else if (st.chg === 'w') o.w = st.cw;
    else if (st.chg === 'out') o.out = true;
    else if (st.chg === 'rmhost') { if (n.length > 1) n.splice(1, 1); }
    else if (st.chg === 'rm') {
      n.forEach(function (ho) { ho.osds = ho.osds.filter(function (x) { return x !== o; }); });
      n = n.filter(function (ho) { return ho.osds.length; });
    }
    return n;
  }
  var CACHE = { key: '', pss: null };
  function samples(st) {                    /* PG seed -> number of sample objects obj-0 .. obj-(N-1) in it */
    var key = st.pgn + ':' + st.n;
    if (CACHE.key !== key) {
      var cnt = {}, mask = C.pgMask(st.pgn);
      for (var i = 0; i < st.n; i++) { var ps = C.stableMod(C.strHash('obj-' + i), st.pgn, mask); cnt[ps] = (cnt[ps] || 0) + 1; }
      CACHE = { key: key, pss: Object.keys(cnt).map(function (k) { return [+k, cnt[k]]; }) };
    }
    return CACHE.pss;
  }
  // replicas moved (an OSD in the new raw set that was not in the old one), the least movement that gives
  // the new per-OSD counts (the sum of every OSD's gain), and the objects whose raw set changed
  function movement(st, mA, mB) {
    var moved = 0, total = 0, objs = 0, ca = {}, cb = {}, n = 0;
    samples(st).forEach(function (pc) {
      var a = place(st, mA, pc[0]).raw, b = place(st, mB, pc[0]).raw, d = 0, c = pc[1];
      n += c; total += c * st.size;
      a.forEach(function (o) { if (o !== C.NONE) ca[o] = (ca[o] || 0) + c; });
      b.forEach(function (o) { if (o !== C.NONE) { cb[o] = (cb[o] || 0) + c; if (a.indexOf(o) < 0) d++; } });
      moved += c * d; if (d || a.length !== b.length) objs += c;
    });
    var gain = 0;
    Object.keys(cb).forEach(function (o) { gain += Math.max(0, cb[o] - (ca[o] || 0)); });
    return { moved: total ? moved / total : 0, min: total ? gain / total : 0, objs: n ? objs / n : 0 };
  }

  /* ---------------------------------------------------------- one bucket choice, drawn as a table */
  function bar(f) { return '<span class="pl-bar" style="--f:' + Math.max(0, Math.min(1, f)).toFixed(3) + '"></span>'; }
  function pickTable(md, ev) {
    var head, rows, win = ev.item, I = ev.info || [];
    var tr = function (cells, cls) { return '<tr' + (cls ? ' class="' + cls + '"' : '') + '>' + cells.map(function (c) { return '<td dir="ltr">' + c + '</td>'; }).join('') + '</tr>'; };
    if (ev.alg === 'straw2') {
      head = [T('pl_c_item'), T('pl_c_w'), 'u = hash₃(x, id, r) & 0xffff', 'draw ≈ log₂((u+1)/2¹⁶) / w'];
      rows = I.map(function (c) {
        return tr([esc(nm(md, c.item)), w2(c.w), hx(c.u), c.draw === -Infinity ? '−∞' : (c.draw * W16 / P44).toFixed(4)], c.item === win ? 'win' : '');
      });
    } else if (ev.alg === 'straw') {
      head = [T('pl_c_item'), T('pl_c_w'), 'u = hash₃(x, id, r) & 0xffff', 'straw', 'u × straw'];
      rows = I.map(function (c) { return tr([esc(nm(md, c.item)), w2(c.w), hx(c.u), (c.straw / W16).toFixed(3), Math.round(c.draw / W16)], c.item === win ? 'win' : ''); });
    } else if (ev.alg === 'list') {
      head = [T('pl_c_item'), T('pl_c_w'), 'sum_weights', 'u = hash₄(x, id, r, b) & 0xffff', '(u × sum) ≫ 16', T('pl_c_ok')];
      rows = I.map(function (c) { return tr([esc(nm(md, c.item)), w2(c.w), w2(c.sum), hx(c.u), w2(c.scaled), c.ok ? '&lt; w ✔' : '≥ w ✗'], c.ok ? 'win' : ''); });
    } else if (ev.alg === 'tree') {
      head = [T('pl_c_node'), T('pl_c_w'), 't = (hash₄(x, n, r, b) × w) ≫ 32', T('pl_c_lw'), T('pl_c_dir')];
      rows = I.map(function (c) { return tr(['n' + c.node, w2(c.w), w2(c.t), w2(c.lw), (c.dir === 'L' ? '← n' + c.left : '→ n' + c.right)]); });
      rows.push(tr(['n' + (I.length ? (I[I.length - 1].dir === 'L' ? I[I.length - 1].left : I[I.length - 1].right) : 1), '', '', '', '= ' + esc(nm(md, win))], 'win'));
    } else {
      head = ['p', 'hash₃(x, b, p)', 'mod', 'perm'];
      rows = I.filter(function (c) { return c.pick == null; }).map(function (c) { return tr([String(c.p), hx(c.h), c.fast ? '% ' + c.mod + ' = ' + c.swap + ' (r = 0)' : '% ' + c.mod + ' → swap ' + c.p + '↔' + c.swap, '[' + c.perm.join(' ') + ']']); });
      var pk = I.filter(function (c) { return c.pick != null; })[0];
      rows.push(tr(['', '', pk ? 'pr = r % size = ' + pk.pr : 'pr = 0', '= ' + esc(nm(md, win))], 'win'));
    }
    return '<div class="table-wrap"><table class="sim-t pl-t" dir="ltr"><thead><tr>' + head.map(function (x) { return '<th scope="col">' + esc(x) + '</th>'; }).join('') + '</tr></thead><tbody>' + rows.join('') + '</tbody></table></div>';
  }
  function traceHTML(st, md, trace, raw) {
    var groups = [], cur = null;
    trace.forEach(function (ev) {
      if (ev.k === 'pick' && !ev.inner && (!cur || ev.rep !== cur.rep)) { cur = { rep: ev.rep, evs: [] }; groups.push(cur); }
      if (cur) cur.evs.push(ev);
    });
    return groups.map(function (g, gi) {
      var got = raw[gi], body = g.evs.map(function (ev) {
        if (ev.k === 'pick') {
          return '<div class="pl-pick' + (ev.inner ? ' inner' : '') + '"><p class="pl-ph"><bdi dir="ltr">bucket ' + esc(nm(md, ev.b)) + ' (' + ev.alg + '), r = ' + ev.r + '</bdi> <span class="sim-pill">' + tx('pl_win', { o: nm(md, ev.item) }) + '</span></p>' + pickTable(md, ev) + '</div>';
        }
        var key = ev.k === 'collide' ? 'pl_rej_coll' : ev.why === 'out' ? 'pl_rej_out' : ev.why === 'leaf' ? 'pl_rej_leaf' : 'pl_rej_empty';
        return '<p class="pl-rej' + (ev.inner ? ' inner' : '') + '">✗ ' + tx(key, { o: nm(md, ev.item), r: 'r=' + (ev.r + 1) }) + '</p>';
      }).join('');
      var title = got != null && got !== C.NONE ? T('pl_rep', { n: L(gi), o: nm(md, got) }) : T('pl_rep_none', { n: L(gi) });
      return '<details class="pl-rep" open><summary>' + rich(title) + '</summary>' + body + '</details>';
    }).join('');
  }

  /* ---------------------------------------------------------- one object, all five steps */
  function mdPool(st) { return { pool: st.pool, pgn: st.pgn, pgp: st.pgp, name: st.mode === 'rbd' ? 'rbd' : 'pool' + st.pool }; }
  function dataPool(st) { return st.dp ? { pool: st.dpool, pgn: st.dpgn, pgp: st.dpgn, name: 'rbd-data' } : mdPool(st); }
  function objPath(st, md, name, P, full) {
    var hash = C.strHash(name), mask = C.pgMask(P.pgn), ps = C.stableMod(hash, P.pgn, mask), trace = full ? [] : undefined;
    var r = C.pgToUp(md.m, 0, ps, P.pool, P.pgp, st.size, md.dev, md.down, false, trace);
    return { hash: hash, mask: mask, ps: ps, pgid: P.pool + '.' + ps.toString(16), r: r, trace: trace };
  }
  function mapWarns(st) {
    var warn = [];
    if (st.alg === 'uniform' && st.hosts.some(function (ho) { return ho.osds.some(function (o) { return o.w !== ho.osds[0].w; }); })) warn.push(tx('pl_w_uniform'));
    if (st.alg === 'uniform' && st.hosts.some(function (ho) { return ho.osds.reduce(function (a, o) { return a + o.w; }, 0) !== st.hosts[0].osds.reduce(function (a, o) { return a + o.w; }, 0); })) warn.push(tx('pl_w_uniform_root'));
    if (st.alg === 'tree') warn.push(tx('pl_w_tree'));
    return warn;
  }
  function warnList(w) { return w.length ? '<ul class="sim-warn">' + w.map(function (x) { return '<li>' + x + '</li>'; }).join('') + '</ul>' : ''; }
  function stepsHTML(st, md, name, P, o) {
    var hash = o.hash, mask = o.mask, ps = o.ps, r = o.r, pgid = o.pgid, low = hash & mask;
    var pgpMask = C.pgMask(P.pgp), ps2 = C.stableMod(ps, P.pgp, pgpMask);
    var nbytes = (typeof TextEncoder !== 'undefined' ? new TextEncoder().encode(name) : Buffer.from(name, 'utf8')).length;
    var s1 = '<div class="sim-formula" dir="ltr">ceph_str_hash_rjenkins("' + esc(name) + '") <span class="pl-dim">(' + nbytes + ' B, UTF-8)</span> = <b>' + hx(hash) + '</b> = ' + hash + '</div><p class="sim-note">' + tx('pl_s1_n') + '</p>';
    var s2 = '<div class="sim-formula" dir="ltr">pg_num = ' + P.pgn + ' · pg_num_mask = ' + hx(mask) + '<br>' + hx(hash) + ' &amp; ' + hx(mask) + ' = ' + low
      + (low < P.pgn ? ' &lt; ' + P.pgn + ' ⇒ ps = <b>' + ps + '</b>' : ' ≥ ' + P.pgn + ' ⇒ ' + hx(hash) + ' &amp; ' + hx(mask >> 1) + ' = <b>' + ps + '</b>')
      + '<br>pgid = ' + pgid + '</div><p class="sim-note">' + tx(low < P.pgn ? 'pl_s2_ok' : 'pl_s2_fold', { v: L(low) }) + ' ' + tx('pl_s2_n', { raw: P.pool + '.' + hash.toString(16), pgid: pgid }) + '</p>';
    var s3 = '<div class="sim-formula" dir="ltr">ceph_stable_mod(' + ps + ', pgp_num ' + P.pgp + ', ' + hx(pgpMask) + ') = ' + ps2 + '<br>x = crush_hash32_rjenkins1_2(' + ps2 + ', pool ' + P.pool + ') = <b>' + hx(r.pps) + '</b> = ' + r.pps + '</div>'
      + '<p class="sim-note">' + tx('pl_s3_n') + '</p>';
    var rule = st.fd === 'host' ? 'step chooseleaf firstn 0 type host' : 'step choose firstn 0 type osd';
    var s4 = '<pre class="sim-cmd" dir="ltr"><code>rule replicated_rule { step take default; ' + rule + '; step emit }   # ' + st.alg + ', tunables jewel, size ' + st.size + '</code></pre>'
      + '<p class="sim-note">' + tx('pl_s4_n', { fd: st.fd }) + '</p>' + traceHTML(st, md, o.trace, r.raw);
    var downs = r.raw.filter(function (x) { return md.down[x]; });
    var s5 = '<div class="sim-formula" dir="ltr">raw (CRUSH) = ' + setStr(r.raw) + (downs.length ? ' · down: ' + downs.map(function (x) { return 'osd.' + x; }).join(', ') : '')
      + '<br>up = ' + setStr(r.up) + ' · acting = ' + setStr(r.up) + ' · primary = ' + (r.primary >= 0 ? 'osd.' + r.primary : '–') + '</div>'
      + '<p class="sim-note">' + tx('pl_s5_n') + '</p>'
      + '<pre class="sim-cmd" dir="ltr"><code>$ ceph osd map ' + P.name + ' ' + esc(name) + '\nosdmap e1 pool \'' + P.name + '\' (' + P.pool + ') object \'' + esc(name) + '\' -> pg ' + P.pool + '.' + hash.toString(16) + ' (' + pgid + ') -> up (' + setStr(r.up) + ', p' + r.primary + ') acting (' + setStr(r.up) + ', p' + r.primary + ')</code></pre>';
    var steps = [['pl_s1_t', s1], ['pl_s2_t', s2], ['pl_s3_t', s3], ['pl_s4_t', s4], ['pl_s5_t', s5]];
    return '<ol class="pl-steps">' + steps.map(function (x, i) { return '<li class="pl-step"><h4><span class="pl-n">' + L(i + 1) + '</span>' + tx(x[0]) + '</h4>' + x[1] + '</li>'; }).join('') + '</ol>';
  }

  /* ---------------------------------------------------------- RBD: image bytes -> objects -> PGs -> OSDs */
  var ROWS = 32, MAXBLOCKS = 4096, MAXOBJ = 65536;
  // librbd's layout: object_size = 2^order; the Striper treats stripe_count 1 as stripe_unit = object size
  function lay(st) { var os = Math.pow(2, st.order), su = Math.min(st.su, os); return { object_size: os, stripe_unit: st.sc === 1 ? os : su, stripe_count: st.sc }; }
  function newId() { return C.rbdImageId(4096 + Math.floor(Math.random() * 60000), Math.floor(Math.random() * 4294967296)); }
  var ICACHE = { key: '', cnt: null };
  // every object of the image (as if all were written), counted per PG of the data pool
  function imagePgs(st, l, P) {
    var n = Math.min(C.numObjects(l, st.gib * G), MAXOBJ), mdp = st.dp ? st.pool : -1, key = [st.iid, mdp, P.pgn, n].join(':');
    if (ICACHE.key !== key) {
      var cnt = {}, mask = C.pgMask(P.pgn);
      for (var i = 0; i < n; i++) { var ps = C.stableMod(C.strHash(C.rbdDataName(st.iid, i, mdp)), P.pgn, mask); cnt[ps] = (cnt[ps] || 0) + 1; }
      ICACHE = { key: key, cnt: Object.keys(cnt).map(function (k) { return [+k, cnt[k]]; }) };
    }
    return ICACHE.cnt;
  }
  function xBtn(st, name, fid) {
    var on = st.open === name;
    return '<button type="button" class="sim-btn sm" data-act="plx" data-o="' + esc(name) + '" data-fid="' + fid + '" aria-expanded="' + on + '" aria-label="' + esc(T('pl_steps_for', { o: name })) + '">' + esc(T(on ? 'pl_steps_hide' : 'pl_steps')) + '</button>';
  }
  // the open object's five steps go in a panel under its table (a row inside it would widen every column)
  function objRow(st, md, name, P, fid, cells, panel) {
    var o = objPath(st, md, name, P, st.open === name), r = o.r;
    var html = '<tr' + (st.open === name ? ' class="open"' : '') + '><td dir="ltr"><code>' + esc(name) + '</code></td>' + cells + '<td dir="ltr">' + o.pgid + '</td><td dir="ltr">' + setStr(r.up) + '</td><td dir="ltr">'
      + (r.primary >= 0 ? 'osd.' + r.primary : '–') + '</td><td>' + xBtn(st, name, fid) + '</td></tr>';
    if (st.open === name) panel.push('<div class="pl-xp"><h5><bdi dir="ltr">' + esc(name) + '</bdi></h5>' + stepsHTML(st, md, name, P, o) + '</div>');
    return { html: html, o: o };
  }
  function rbdView(st, md) {
    var l = lay(st), size = st.gib * G, off = clamp(st.off, 0, size - 1), len = clamp(st.len, 1, size - off), warn = mapWarns(st);
    var cap = l.stripe_unit * MAXBLOCKS;
    if (len > cap) { len = cap; warn.push(tx('pl_rbd_lencap', { n: bytes(cap) })); }
    if (st.dp && st.dpool === st.pool) warn.push(tx('pl_rbd_samepool'));
    var MP = mdPool(st), DP = dataPool(st), mdp = st.dp ? st.pool : -1, meta = C.rbdMetaNames(st.img, st.iid);
    var ex = C.fileToExtents(l, off, len, 0), pgs = {}, osdsT = {};
    ex.forEach(function (e) { pgs[C.stableMod(C.strHash(C.rbdDataName(st.iid, e.object_no, mdp)), DP.pgn, C.pgMask(DP.pgn))] = 1; });
    Object.keys(pgs).forEach(function (ps) { C.pgToUp(md.m, 0, +ps, DP.pool, DP.pgp, st.size, md.dev, md.down, false).up.forEach(function (x) { if (x !== C.NONE) osdsT[x] = 1; }); });
    var npg = Object.keys(pgs).length, nosd = Object.keys(osdsT).length;
    var flow = '<ol class="pl-flow" dir="ltr"><li><b>' + esc(st.img) + '</b><small>image · id ' + esc(st.iid) + '</small></li><li><b>' + off + '~' + len + '</b><small>bytes</small></li>'
      + '<li><b>' + ex.length + ' objects</b><small>Striper</small></li><li><b>' + npg + ' PGs</b><small>pool ' + DP.pool + '</small></li><li class="pl-to"><b>' + nosd + ' OSDs</b><small>CRUSH · ' + st.alg + '</small></li></ol>';
    var stats = '<div class="sim-stats">' + stat(L(ex.length), T('pl_st_objs')) + stat(L(npg), T('pl_st_pgs')) + stat(L(nosd), T('pl_st_osds')) + stat(bytes(l.object_size), 'object_size')
      + stat(l.stripe_count > 1 ? bytes(l.stripe_unit) + ' × ' + l.stripe_count : '–', 'stripe_unit × stripe_count') + '</div>';
    // step 1: the Striper
    var pd = [], pm = [], rows = ex.slice(0, ROWS).map(function (e, i) {
      var be = e.buffer_extents.slice(0, 3).map(function (b) { return '[' + (off + b[0]) + ', ' + (off + b[0] + b[1]) + ')'; }).join(' ') + (e.buffer_extents.length > 3 ? ' … (' + e.buffer_extents.length + ')' : '');
      return objRow(st, md, C.rbdDataName(st.iid, e.object_no, mdp), DP, 'xd' + i, '<td dir="ltr">' + e.offset + '~' + e.length + '</td><td dir="ltr">' + be + '</td>', pd).html;
    }).join('');
    var head = function (cols) { return '<thead><tr>' + cols.map(function (c) { return '<th scope="col">' + esc(c) + '</th>'; }).join('') + '<th scope="col"><span class="vh">' + esc(T('pl_steps')) + '</span></th></tr></thead>'; };
    var spo = l.object_size / l.stripe_unit;
    var s1 = '<div class="sim-formula" dir="ltr">os = 1 &lt;&lt; ' + st.order + ' = ' + l.object_size + ' · su = ' + l.stripe_unit + ' · sc = ' + l.stripe_count + (st.sc === 1 && st.su < l.object_size ? ' <span class="pl-dim">(sc = 1 ⇒ su = os)</span>' : '')
      + '<br>blockno = ⌊off / su⌋ · stripeno = ⌊blockno / sc⌋ · stripepos = blockno % sc<br>objectno = ⌊stripeno / ' + spo + '⌋ × sc + stripepos · offset in object = (stripeno % ' + spo + ') × su + off % su'
      + '<br>name = "' + esc(C.rbdDataName(st.iid, 0, mdp).replace(/0+$/, '')) + '" + %016llx(objectno)</div><p class="sim-note">' + tx('pl_rbd_s1_n') + '</p>';
    var s2 = '<p class="sim-note">' + tx(st.dp ? 'pl_rbd_s2_dp' : 'pl_rbd_s2_n', { pool: DP.pool, md: MP.pool }) + '</p><div class="table-wrap"><table class="sim-t pl-ot">'
      + head([T('pl_c_obj'), T('pl_c_inobj'), T('pl_c_img'), 'PG', T('pl_st_up'), 'primary']) + '<tbody>' + rows + '</tbody></table></div>' + pd.join('')
      + (ex.length > ROWS ? '<p class="sim-note">' + tx('pl_rbd_more', { n: L(ex.length - ROWS) }) + '</p>' : '');
    // step 3: metadata objects, always in the metadata pool
    var mrows = [['directory', 'pl_r_dir'], ['id', 'pl_r_id'], ['header', 'pl_r_hdr'], ['objectMap', 'pl_r_om']].map(function (m, i) {
      return objRow(st, md, meta[m[0]], MP, 'xm' + i, '<td>' + tx(m[1]) + '</td>', pm).html;
    }).join('');
    var s3 = '<p class="sim-note">' + tx('pl_rbd_s3_n', { md: MP.pool }) + '</p><div class="table-wrap"><table class="sim-t pl-ot">' + head([T('pl_c_obj'), T('pl_c_role'), 'PG', T('pl_st_up'), 'primary']) + '<tbody>' + mrows + '</tbody></table></div>' + pm.join('');
    // step 4: the whole image
    var nobj = C.numObjects(l, size), cnt = imagePgs(st, l, DP), per = {}, prim = {}, tot = 0, osdsAll = {};
    cnt.forEach(function (pc) {
      var r = C.pgToUp(md.m, 0, pc[0], DP.pool, DP.pgp, st.size, md.dev, md.down, false);
      r.up.forEach(function (x) { if (x !== C.NONE) { per[x] = (per[x] || 0) + pc[1]; osdsAll[x] = 1; } });
      if (r.primary >= 0) prim[r.primary] = (prim[r.primary] || 0) + pc[1];
      tot += pc[1];
    });
    var ids = Object.keys(per).map(Number).sort(function (a, b) { return a - b; }), mx = Math.max.apply(null, ids.map(function (i) { return per[i]; }).concat([1]));
    var otab = '<div class="table-wrap pl-osdw"><table class="sim-t pl-osd"><thead><tr><th scope="col">OSD</th><th scope="col">' + esc(T('pl_c_reps')) + '</th><th scope="col">primary</th></tr></thead><tbody>'
      + ids.map(function (i) { return '<tr><th scope="row" dir="ltr">osd.' + i + '</th><td><span class="pl-mv">' + bar(per[i] / mx) + '<b>' + L(per[i]) + '</b></span></td><td>' + L(prim[i] || 0) + '</td></tr>'; }).join('') + '</tbody></table></div>';
    var s4 = '<div class="sim-stats">' + stat(L(nobj), T('pl_st_imgobjs')) + stat(L(cnt.length) + ' / ' + L(DP.pgn), T('pl_st_pgs')) + stat(L(Object.keys(osdsAll).length) + ' / ' + L(osds(st.hosts).length), T('pl_st_osds')) + '</div>'
      + '<p class="sim-note">' + tx('pl_rbd_s4_n') + (nobj > MAXOBJ ? ' ' + tx('pl_rbd_cap', { n: L(MAXOBJ) }) : '') + '</p>' + otab;
    var steps = [['pl_rbd_s1_t', s1], ['pl_rbd_s2_t', s2], ['pl_rbd_s3_t', s3], ['pl_rbd_s4_t', s4]];
    var cmd = '<pre class="sim-cmd" dir="ltr"><code>$ rbd create ' + (st.dp ? '--data-pool rbd-data ' : '') + '--size ' + st.gib + 'G --object-size ' + bytes(l.object_size).replace(' ', '').replace('iB', '')
      + (l.stripe_count > 1 ? ' --stripe-unit ' + bytes(l.stripe_unit).replace(' ', '').replace('iB', '') + ' --stripe-count ' + l.stripe_count : '') + ' rbd/' + esc(st.img) + '\n$ rbd info rbd/' + esc(st.img) + '\n\tsize ' + st.gib + ' GiB in ' + nobj + ' objects\n\torder ' + st.order + ' (' + bytes(l.object_size) + ' objects)\n'
      + (l.stripe_count > 1 ? '\tstripe unit: ' + bytes(l.stripe_unit) + '\n\tstripe count: ' + l.stripe_count + '\n' : '') + '\tid: ' + esc(st.iid) + '\n' + (st.dp ? '\tdata_pool: rbd-data\n' : '') + '\tblock_name_prefix: ' + esc(C.rbdDataName(st.iid, 0, mdp).replace(/\.0+$/, '')) + '\n\tformat: 2</code></pre>';
    return flow + stats + warnList(warn) + cmd + '<ol class="pl-steps">' + steps.map(function (x, i) { return '<li class="pl-step"><h4><span class="pl-n">' + L(i + 1) + '</span>' + tx(x[0]) + '</h4>' + x[1] + '</li>'; }).join('') + '</ol>';
  }

  S.DEFS.placement = {
    icon: 'M3 5h6v4H3zM9 7h3M12 7v10M12 12h3M12 17h3M15 10h6v4h-6zM15 15h6v4h-6zM15 5h6v4h-6z',
    defaults: function () {
      return { obj: 'photos/2026/11/img_0001.jpg', pool: 1, pgn: 64, pgp: 64, size: 3, fd: 'host', alg: 'straw2', hosts: hosts0(),
               chg: 'rmhost', co: 4, cw: 4, to: 'straw', n: 1000,
               mode: 'obj', img: 'vm-disk-1', iid: '1d6f2a8c4e93', gib: 10, order: 22, su: 4 << 20, sc: 1, off: 9 << 20, len: 8 << 20,
               dp: false, dpool: 2, dpgn: 128, open: '' };
    },
    refs: [['src/common/ceph_hash.cc :: ceph_str_hash_rjenkins', 'r_strhash'], ['src/include/rados.h :: ceph_stable_mod; src/osd/osd_types.cc :: pg_pool_t::calc_pg_masks', 'r_stable'],
           ['src/osd/osd_types.cc :: pg_pool_t::raw_pg_to_pps (FLAG_HASHPSPOOL)', 'r_pps'], ['src/crush/hash.c :: crush_hash32_rjenkins1_2, _3, _4', 'r_hash'],
           ['src/crush/mapper.c :: crush_do_rule, crush_choose_firstn, is_out', 'r_choose'],
           ['src/crush/mapper.c :: bucket_straw2_choose, generate_exponential_distribution, crush_ln', 'r_straw2'],
           ['src/crush/mapper.c :: bucket_straw_choose; builder.c :: crush_calc_straw (straw_calc_version 1)', 'r_pl_straw'],
           ['src/crush/mapper.c :: bucket_list_choose, bucket_tree_choose, bucket_perm_choose; builder.c :: crush_make_bucket', 'r_pl_old'],
           ['src/osd/OSDMap.cc :: _pg_to_raw_osds, _raw_to_up_osds, _pick_primary', 'r_up'],
           ['src/crush/CrushWrapper.cc :: add_simple_rule_at; CrushWrapper.h :: set_tunables_jewel', 'r_rule'],
           ['src/osdc/Striper.cc :: Striper::file_to_extents, get_num_objects', 'r_st_fte'],
           ['src/librbd/ImageCtx.cc :: init_layout (format_string "%s.%016llx"); librbd/image/CreateRequest.cc :: create_image, validate_striping', 'r_pl_rbdname'],
           ['src/include/rbd_types.h; librbd/Utils.cc :: generate_image_id, id_obj_name, header_name; librbd/ObjectMap.cc :: object_map_name', 'r_pl_rbdmeta']],
    controls: function (st) {
      var rbd = st.mode === 'rbd', os = Math.pow(2, st.order);
      var out = '<div class="sim-row"><div class="sim-f"><span>' + esc(T('pl_mode_l')) + '</span>' + seg('pl_mode', [['obj', T('pl_mode_obj')], ['rbd', T('pl_mode_rbd')]], st.mode) + '</div></div>';
      if (!rbd) out += '<div class="sim-row">' + field(T('pl_obj'), '<input type="text" dir="ltr" spellcheck="false" autocomplete="off" data-k="obj" value="' + esc(st.obj) + '">') + '</div>';
      else {
        var sus = []; for (var su = 4096; su <= os; su *= 2) sus.push([su, bytes(su) + (su === os ? ' (= object_size)' : '')]);
        out += '<div class="sim-row">' + field(T('pl_img'), '<input type="text" dir="ltr" spellcheck="false" autocomplete="off" data-k="img" value="' + esc(st.img) + '">')
          + '<div class="sim-f"><span>' + esc(T('pl_iid')) + '</span><span class="pl-iid"><input type="text" dir="ltr" spellcheck="false" autocomplete="off" data-k="iid" maxlength="14" aria-label="' + esc(T('pl_iid')) + '" value="' + esc(st.iid) + '">'
          + '<button type="button" class="sim-btn sm" data-act="newid">' + esc(T('pl_newid')) + '</button></span></div>'
          + field(T('pl_gib'), numIn('gib', st.gib, 1, 65536, 1)) + '</div>'
          + '<div class="sim-row">' + field('order', sel('order', [12, 16, 20, 21, 22, 23, 24, 25].map(function (o) { return [o, o + ' (' + bytes(Math.pow(2, o)) + ')']; }), st.order))
          + field('stripe_unit', sel('su', sus, Math.min(st.su, os))) + field('stripe_count', sel('sc', [1, 2, 3, 4, 8, 16], st.sc))
          + field(T('pl_off'), numIn('off', st.off, 0, 1e15, 1), bytes(st.off)) + field(T('pl_len'), numIn('len', st.len, 1, 1e15, 1), bytes(st.len)) + '</div>'
          + '<div class="sim-row"><label class="sim-f sim-chk"><input type="checkbox" data-k="dp"' + (st.dp ? ' checked' : '') + '><span>' + tx('pl_dp') + '</span></label>'
          + (st.dp ? field(T('pl_dpool'), numIn('dpool', st.dpool, 0, 9999, 1)) + field(T('pl_dpgn'), numIn('dpgn', st.dpgn, 1, 4096, 1)) : '') + '</div>';
      }
      out += '<div class="sim-row">' + field(T(rbd ? 'pl_mdpool' : 'pl_pool'), numIn('pool', st.pool, 0, 9999, 1)) + field('pg_num', numIn('pgn', st.pgn, 1, 4096, 1)) + field('pgp_num', numIn('pgp', st.pgp, 1, 4096, 1))
        + field(T('pl_size'), sel('size', [1, 2, 3, 4, 5], st.size)) + field('Failure domain', sel('fd', [['host', 'host'], ['osd', 'osd']], st.fd)) + '</div>'
        + '<div class="sim-row"><div class="sim-f"><span>' + esc(T('pl_alg')) + '</span>' + seg('pl_alg', ALGS.map(function (a) { return [a, a]; }), st.alg) + '<small>' + tx('pl_alg_all') + '</small></div></div>';
      out += '<div class="cr-hosts" dir="ltr">' + st.hosts.map(function (ho, hi) {
        var tw = Math.round(ho.osds.reduce(function (a, o) { return a + (o.w || 0); }, 0) * 100) / 100;
        return '<fieldset class="cr-host"><legend>' + esc(ho.name) + ' <small>' + tw + ' TiB</small></legend>' + ho.osds.map(function (o, oi) {
          var p = hi + '.' + oi;
          return '<div class="cr-osd' + (o.out ? ' is-out' : '') + (o.down ? ' is-down' : '') + '"><span class="cr-id">osd.' + o.id + '</span>'
            + '<input type="number" step="0.5" min="0" max="64" value="' + o.w + '" data-k="w" data-p="' + p + '" data-fid="w' + o.id + '" aria-label="' + esc(T('cr_weight', { o: 'osd.' + o.id })) + '">'
            + '<button type="button" class="cr-tg" data-act="out" data-p="' + p + '" data-fid="o' + o.id + '" aria-pressed="' + o.out + '" aria-label="' + esc(T('cr_tg_out', { o: 'osd.' + o.id })) + '">' + (o.out ? 'out' : 'in') + '</button>'
            + '<button type="button" class="cr-tg" data-act="down" data-p="' + p + '" data-fid="d' + o.id + '" aria-pressed="' + o.down + '" aria-label="' + esc(T('cr_tg_down', { o: 'osd.' + o.id })) + '">' + (o.down ? 'down' : 'up') + '</button>'
            + '<button type="button" class="cr-x" data-act="rm" data-p="' + p + '" aria-label="' + esc(T('cr_rm', { o: 'osd.' + o.id })) + '">×</button></div>';
        }).join('') + '<button type="button" class="sim-btn sm" data-act="addosd" data-p="' + hi + '">+ OSD</button></fieldset>';
      }).join('') + '<button type="button" class="sim-btn sm cr-addh" data-act="addhost">+ host</button></div>';
      return out;
    },
    view: function (st) {
      var md = model(st.hosts, st.alg, st.fd);
      if (st.mode === 'rbd') return rbdView(st, md);
      var P = mdPool(st), o = objPath(st, md, st.obj, P, true), r = o.r;
      var flow = '<ol class="pl-flow" dir="ltr"><li><b>' + esc(st.obj.length > 28 ? st.obj.slice(0, 27) + '…' : st.obj) + '</b><small>name</small></li><li><b>' + hx(o.hash) + '</b><small>rjenkins</small></li>'
        + '<li><b>pg ' + o.pgid + '</b><small>stable_mod</small></li><li><b>x ' + hx(r.pps) + '</b><small>pps</small></li><li class="pl-to"><b>' + setStr(r.up) + '</b><small>up · ' + st.alg + '</small></li></ol>';
      var stats = '<div class="sim-stats">' + stat(o.pgid, T('pl_st_pg')) + stat(hx(r.pps), 'x (pps)') + stat(setStr(r.up), T('pl_st_up')) + stat(r.primary >= 0 ? 'osd.' + r.primary : '–', 'primary', r.primary < 0 ? 'warn' : '') + '</div>';
      var upN = r.up.filter(function (x) { return x !== C.NONE; }), warn = mapWarns(st);
      if (upN.length < st.size) warn.push(tx('pl_w_short', { n: L(upN.length), size: L(st.size) }));
      return flow + stats + warnList(warn) + stepsHTML(st, md, st.obj, P, o) + compare(st, md);
    },
    preset: function (st, mode) { if (mode === 'rbd') st.mode = 'rbd'; return st; },
    say: function (st) {
      if (st.mode === 'rbd') {
        var l = lay(st), off = clamp(st.off, 0, st.gib * G - 1);
        return st.img + ': ' + C.fileToExtents(l, off, clamp(Math.min(st.len, l.stripe_unit * MAXBLOCKS), 1, st.gib * G - off), 0).length + ' objects';
      }
      var md = model(st.hosts, st.alg, st.fd), hash = C.strHash(st.obj), ps = C.stableMod(hash, st.pgn, C.pgMask(st.pgn)), r = place(st, md, ps);
      return st.obj + ' → pg ' + st.pool + '.' + ps.toString(16) + ' → ' + setStr(r.up);
    },
    input: function (st, k, v, el) {
      if (k === 'obj') { st.obj = String(v).slice(0, 200); return 'out'; }
      if (k === 'pl_mode') { st.mode = v; st.open = ''; return 'all'; }
      if (k === 'img') { st.img = String(v).replace(/[\s\/@]/g, '').slice(0, 64) || 'img'; return 'out'; }
      if (k === 'iid') { st.iid = String(v).toLowerCase().replace(/[^0-9a-f]/g, '').slice(0, 14) || '0'; return 'out'; }
      if (k === 'gib') { st.gib = clamp(parseInt(v, 10) || 1, 1, 65536); return 'out'; }
      if (k === 'order') { st.order = +v; st.su = Math.min(st.su, Math.pow(2, st.order)); return 'all'; }
      if (k === 'su' || k === 'sc') { st[k] = +v; return 'out'; }
      if (k === 'off') { st.off = Math.max(0, Math.floor(+v || 0)); return 'out'; }
      if (k === 'len') { st.len = Math.max(1, Math.floor(+v || 1)); return 'out'; }
      if (k === 'dp') { st.dp = !!v; return 'all'; }
      if (k === 'dpool') { st.dpool = clamp(parseInt(v, 10) || 0, 0, 9999); return 'out'; }
      if (k === 'dpgn') { st.dpgn = clamp(parseInt(v, 10) || 1, 1, 4096); return 'out'; }
      if (k === 'pool') { st.pool = clamp(parseInt(v, 10) || 0, 0, 9999); return 'out'; }
      if (k === 'pgn') { var n = clamp(parseInt(v, 10) || 1, 1, 4096), follow = st.pgp === st.pgn; st.pgn = n; st.pgp = follow ? n : Math.min(st.pgp, n); return follow ? 'all' : 'out'; }
      if (k === 'pgp') { st.pgp = clamp(parseInt(v, 10) || 1, 1, st.pgn); return 'out'; }
      if (k === 'size') { st.size = +v; return 'out'; }
      if (k === 'fd') { st.fd = v; return 'out'; }
      if (k === 'pl_alg') { st.alg = v; if (st.to === v) st.to = ALGS.filter(function (a) { return a !== v; })[0]; return 'all'; }
      if (k === 'chg') { st.chg = v; return 'out'; }
      if (k === 'co') { st.co = +v; var o = osds(st.hosts).filter(function (x) { return x.id === st.co; })[0]; if (o && st.chg === 'w') st.cw = o.w / 2; return 'out'; }
      if (k === 'cw') { st.cw = clamp(parseFloat(v) || 0, 0, 64); return 'out'; }
      if (k === 'to') { st.to = v; return 'out'; }
      if (k === 'n') { st.n = +v; return 'out'; }
      if (k === 'w') {
        var p = el.getAttribute('data-p').split('.'), od = st.hosts[+p[0]].osds[+p[1]];
        od.w = clamp(parseFloat(v) || 0, 0, 64); return 'out';
      }
      return null;
    },
    act: function (st, a, el) {
      if (a === 'plx') { var nmx = el.getAttribute('data-o'); st.open = st.open === nmx ? '' : nmx; return 'out'; }
      if (a === 'newid') { st.iid = newId(); return 'all'; }
      var p = (el.getAttribute('data-p') || '').split('.'), ho = st.hosts[+p[0]], o = ho && p.length > 1 ? ho.osds[+p[1]] : null;
      if (a === 'out') { o.out = !o.out; return 'all'; }
      if (a === 'down') { o.down = !o.down; return 'all'; }
      if (a === 'rm') {
        if (osds(st.hosts).length <= 1) return null;
        ho.osds.splice(+p[1], 1); if (!ho.osds.length) st.hosts.splice(+p[0], 1);
        if (!osds(st.hosts).some(function (x) { return x.id === st.co; })) st.co = osds(st.hosts)[0].id;
        return 'all';
      }
      if (a === 'addosd') { ho.osds.push({ id: maxId(st.hosts) + 1, w: 4, out: false, down: false }); return 'all'; }
      if (a === 'addhost') {
        if (st.hosts.length >= 12) return null;
        var b = maxId(st.hosts) + 1;
        st.hosts.push({ name: 'host' + (st.hosts.length + 1), bid: nextBid(st.hosts), osds: [0, 1, 2].map(function (i) { return { id: b + i, w: 4, out: false, down: false }; }) });
        return 'all';
      }
      return null;
    }
  };

  /* ---------------------------------------------------------- compare: what moves, per algorithm */
  function compare(st, md) {
    var all = osds(st.hosts), chg = st.chg;
    var ctl = '<div class="sim-row">' + field(T('pl_chg'), sel('chg', [['add', T('pl_chg_add')], ['host', T('pl_chg_host')], ['w', T('pl_chg_w')], ['out', T('pl_chg_out')], ['rm', T('pl_chg_rm')], ['rmhost', T('pl_chg_rmhost')], ['alg', T('pl_chg_alg')]], chg))
      + (chg === 'w' || chg === 'out' || chg === 'rm' ? field('OSD', sel('co', all.map(function (o) { return [o.id, 'osd.' + o.id]; }), st.co)) : '')
      + (chg === 'add' || chg === 'w' ? field(T('pl_chg_wv'), numIn('cw', st.cw, 0, 64, 0.5)) : '')
      + (chg === 'alg' ? field(T('pl_chg_to'), sel('to', ALGS.filter(function (a) { return a !== st.alg; }).map(function (a) { return [a, a]; }), st.to)) : '')
      + field(T('pl_samples'), sel('n', [[1000, L(1000)], [10000, L(10000)]], st.n)) + '</div>';
    var after = chg === 'alg' ? st.hosts : changed(st, st.hosts), rows = [], cur = null;
    var list = chg === 'alg' ? ALGS.filter(function (a) { return a !== st.alg; }) : ALGS;
    list.forEach(function (a) {
      var mA = chg === 'alg' ? md : model(st.hosts, a, st.fd), mB = model(after, a, st.fd), mv = movement(st, mA, mB);
      rows.push({ a: a, mv: mv });
      if (a === st.alg) cur = mv;
    });
    var maxF = Math.max.apply(null, rows.map(function (x) { return x.mv.moved; }).concat([0.0001]));
    var tbl = '<div class="table-wrap"><table class="sim-t pl-cmp"><thead><tr><th scope="col">' + esc(chg === 'alg' ? T('pl_t_from', { a: st.alg }) : T('pl_t_alg')) + '</th><th scope="col">' + esc(T('pl_t_moved')) + '</th><th scope="col">'
      + esc(T('pl_t_min')) + '</th><th scope="col">' + esc(T('pl_t_objs')) + '</th></tr></thead><tbody>' + rows.map(function (x) {
        var extra = x.mv.moved - x.mv.min;
        return '<tr class="' + (x.a === st.alg && chg !== 'alg' ? 'cur' : '') + '"><th scope="row" dir="ltr">' + x.a + (x.a === st.alg && chg !== 'alg' ? ' <span class="sim-pill">' + esc(T('pl_cur')) + '</span>' : '') + '</th>'
          + '<td><span class="pl-mv">' + bar(x.mv.moved / maxF) + '<b>' + pct(x.mv.moved) + '</b></span>' + (chg !== 'alg' && extra > 0.005 ? ' <span class="sim-pill hot"><bdi dir="ltr">+' + pct(extra) + '</bdi></span>' : '') + '</td>'
          + '<td>' + (chg === 'alg' ? '–' : pct(x.mv.min)) + '</td><td>' + pct(x.mv.objs) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    // the typed object before and after the change, with the current algorithm
    var hash = C.strHash(st.obj), ps = C.stableMod(hash, st.pgn, C.pgMask(st.pgn));
    var bA = place(st, md, ps).raw, bB = place(st, model(after, chg === 'alg' ? st.to : st.alg, st.fd), ps).raw;
    var same = JSON.stringify(bA) === JSON.stringify(bB);
    var objLine = '<p class="sim-note">' + rich(T('pl_cmp_obj', { o: st.obj, a: setStr(bA), b: setStr(bB) })) + (same ? ' ' + esc(T('pl_cmp_same')) : '') + '</p>';
    return '<section class="pl-cmp-box"><h4>' + tx('pl_cmp_t') + '</h4><p class="sim-note">' + tx('pl_cmp_d', { n: L(st.n) }) + '</p>' + ctl + tbl + objLine
      + '<p class="sim-note">' + tx(chg === 'alg' ? 'pl_cmp_note_alg' : 'pl_cmp_note') + '</p></section>';
  }
})(typeof self !== 'undefined' ? self : this);
