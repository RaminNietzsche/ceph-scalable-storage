/* CRUSH playground (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, C = h.C, T = h.T, L = h.L, esc = h.esc, pct = h.pct, sel = h.sel, field = h.field, seg = h.seg, stat = h.stat;
  var PRESETS = {
    p3: [[4, 4, 4], [4, 4, 4], [4, 4, 4]],
    pmix: [[4, 4], [8, 8, 8], [4, 4, 4], [2, 2, 2, 2]],
    p6: [[4, 4], [4, 4], [4, 4], [4, 4], [4, 4], [4, 4]]
  };
  function fromPreset(p) {
    var id = 0;
    return PRESETS[p].map(function (ws, i) { return { name: 'host' + (i + 1), osds: ws.map(function (w) { return { id: id++, w: w, out: false, down: false }; }) }; });
  }
  // builds the same map as `ceph osd crush add-bucket` + `osd crush add` + `osd pool create`:
  // root (type 11) -> hosts (type 1) -> osds, straw2 buckets, rule from add_simple_rule_at
  function model(st) {
    var buckets = [], hostItems = [], hostW = [], all = [];
    st.hosts.forEach(function (ho, i) {
      var items = ho.osds.map(function (o) { return o.id; }), ws = ho.osds.map(function (o) { return C.iweight(o.w); });
      buckets.push({ id: -2 - i, type: 1, items: items, weights: ws });
      hostItems.push(-2 - i); hostW.push(ws.reduce(function (a, b) { return a + b; }, 0));
      ho.osds.forEach(function (o) { all.push(o); });
    });
    buckets.push({ id: -1, type: 11, items: hostItems, weights: hostW });
    var ec = st.type === 'ec', size = ec ? st.k + st.m : st.size;
    var m = C.makeMap(buckets, { 0: C.simpleRule(-1, st.fd === 'host' ? 1 : 0, ec) });
    var maxId = all.reduce(function (a, o) { return Math.max(a, o.id); }, -1), dev = [], down = {};
    for (var i = 0; i <= maxId; i++) dev[i] = 0;
    all.forEach(function (o) { dev[o.id] = o.out ? 0 : 0x10000; if (o.down) down[o.id] = 1; });
    var pgs = [];
    for (var ps = 0; ps < st.pgs; ps++) pgs.push(C.pgToUp(m, 0, ps, st.pool, st.pgs, size, dev, down, ec));
    return { pgs: pgs, size: size, ec: ec, osds: all };
  }
  function moved(prev, cur, ec) {
    if (!prev || prev.length !== cur.length) return null;
    var n = 0, tot = 0, pgs = 0, changed = {};
    cur.forEach(function (p, i) {
      var a = prev[i].raw, b = p.raw, d = 0;
      if (ec) { for (var j = 0; j < b.length; j++) { tot++; if (a[j] !== b[j] && b[j] !== C.NONE) d++; } }
      else b.forEach(function (o) { tot++; if (a.indexOf(o) < 0) d++; });
      n += d;
      if (d || JSON.stringify(prev[i].up) !== JSON.stringify(p.up)) { pgs++; changed[i] = 1; }
    });
    return { frac: tot ? n / tot : 0, pgs: pgs, changed: changed };
  }
  function osdRow(o, p) {
    return '<div class="cr-osd' + (o.out ? ' is-out' : '') + (o.down ? ' is-down' : '') + '"><span class="cr-id">osd.' + o.id + '</span>'
      + '<input type="number" step="0.5" min="0" max="64" value="' + o.w + '" data-k="w" data-p="' + p + '" data-fid="w' + o.id + '" aria-label="' + esc(T('cr_weight', { o: 'osd.' + o.id })) + '">'
      + '<button type="button" class="cr-tg" data-act="out" data-p="' + p + '" data-fid="o' + o.id + '" aria-pressed="' + o.out + '" aria-label="' + esc(T('cr_tg_out', { o: 'osd.' + o.id })) + '">' + (o.out ? 'out' : 'in') + '</button>'
      + '<button type="button" class="cr-tg" data-act="down" data-p="' + p + '" data-fid="d' + o.id + '" aria-pressed="' + o.down + '" aria-label="' + esc(T('cr_tg_down', { o: 'osd.' + o.id })) + '">' + (o.down ? 'down' : 'up') + '</button>'
      + '<button type="button" class="cr-x" data-act="rm" data-p="' + p + '" aria-label="' + esc(T('cr_rm', { o: 'osd.' + o.id })) + '">×</button></div>';
  }
  S.DEFS.crush = {
    icon: 'M10 2h4v4h-4zM12 6v3M12 9l-6 4M12 9l6 4M4 13h4v4H4zM16 13h4v4h-4zM6 17v2M18 17v2',
    defaults: function () { return { preset: 'p3', hosts: fromPreset('p3'), type: 'rep', size: 3, k: 4, m: 2, fd: 'host', pgs: 64, pool: 1, obj: 'rbd_data.10226b8b4567.0000000000000000', prev: null, last: '' }; },
    refs: [['src/crush/mapper.c :: crush_do_rule', 'r_do_rule'], ['src/crush/mapper.c :: crush_choose_firstn, crush_choose_indep', 'r_choose'],
           ['src/crush/mapper.c :: bucket_straw2_choose, generate_exponential_distribution, crush_ln', 'r_straw2'],
           ['src/crush/mapper.c :: is_out', 'r_isout'], ['src/crush/hash.c :: crush_hash32_rjenkins1_2, _3', 'r_hash'],
           ['src/osd/osd_types.cc :: pg_pool_t::raw_pg_to_pps, hash_key', 'r_pps'], ['src/include/rados.h :: ceph_stable_mod', 'r_stable'],
           ['src/common/ceph_hash.cc :: ceph_str_hash_rjenkins', 'r_strhash'], ['src/osd/OSDMap.cc :: _pg_to_raw_osds, _raw_to_up_osds', 'r_up'],
           ['src/crush/CrushWrapper.cc :: add_simple_rule_at, insert_item; CrushWrapper.h :: set_tunables_jewel', 'r_rule']],
    controls: function (st) {
      var out = '<div class="sim-row">' + field(T('cr_preset'), sel('preset', [['p3', T('cr_p3')], ['pmix', T('cr_pmix')], ['p6', T('cr_p6')]], st.preset))
        + '<div class="sim-f"><span>' + esc(T('cr_type')) + '</span>' + seg('type', [['rep', T('cr_rep')], ['ec', T('cr_ec')]], st.type) + '</div>'
        + (st.type === 'rep' ? field('size', sel('size', [2, 3, 4], st.size)) : field('k', sel('k', [2, 3, 4, 5, 6, 8], st.k)) + field('m', sel('m', [1, 2, 3, 4], st.m)))
        + field(T('cr_fd'), sel('fd', [['host', 'host'], ['osd', 'osd']], st.fd)) + field('pg_num', sel('pgs', [32, 64, 128, 256], st.pgs)) + '</div>';
      out += '<div class="cr-hosts" dir="ltr">' + st.hosts.map(function (ho, hi) {
        var tw = Math.round(ho.osds.reduce(function (a, o) { return a + (o.w || 0); }, 0) * 100) / 100;
        return '<fieldset class="cr-host"><legend>' + esc(ho.name) + ' <small>' + tw + ' TiB</small></legend>'
          + ho.osds.map(function (o, oi) { return osdRow(o, hi + '.' + oi); }).join('')
          + '<button type="button" class="sim-btn sm" data-act="addosd" data-p="' + hi + '">+ OSD</button></fieldset>';
      }).join('') + '<button type="button" class="sim-btn sm cr-addh" data-act="addhost">+ host</button></div>';
      return out + '<div class="sim-row">' + field(T('cr_obj'), '<input type="text" dir="ltr" spellcheck="false" data-k="obj" value="' + esc(st.obj) + '">') + '</div>';
    },
    view: function (st) {
      var r = model(st), mv = moved(st.prev, r.pgs, r.ec), counts = {}, exp = {}, totalW = 0, none = 0, degraded = 0;
      r.osds.forEach(function (o) { counts[o.id] = 0; if (!o.out) totalW += o.w; });
      r.pgs.forEach(function (p) {
        p.raw.forEach(function (o) { if (o !== C.NONE) counts[o]++; else none++; });
        if (p.up.filter(function (o) { return o !== C.NONE; }).length < r.size) degraded++;
      });
      var shards = st.pgs * r.size;
      r.osds.forEach(function (o) { exp[o.id] = !o.out && totalW ? shards * o.w / totalW : 0; });
      var maxc = Math.max.apply(null, r.osds.map(function (o) { return Math.max(counts[o.id], exp[o.id]); }).concat([1]));
      var W = 720, H = 190, bw = (W - 40) / r.osds.length;
      var bars = r.osds.map(function (o, i) {
        var x = 30 + i * bw, hh = (counts[o.id] / maxc) * (H - 44), ey = H - 22 - (exp[o.id] / maxc) * (H - 44);
        return '<g><title>osd.' + o.id + ': ' + counts[o.id] + ' (≈' + Math.round(exp[o.id]) + ')</title><rect class="' + (o.out ? 'b-out' : o.down ? 'b-down' : 'b-in') + '" x="' + (x + 2) + '" y="' + (H - 22 - hh) + '" width="' + Math.max(2, bw - 4) + '" height="' + hh + '" rx="2"/>'
          + '<line class="b-exp" x1="' + (x + 1) + '" x2="' + (x + bw - 1) + '" y1="' + ey + '" y2="' + ey + '"/>'
          + '<text x="' + (x + bw / 2) + '" y="' + (H - 8) + '" text-anchor="middle">' + o.id + '</text>'
          + '<text class="b-n" x="' + (x + bw / 2) + '" y="' + (H - 26 - hh) + '" text-anchor="middle">' + counts[o.id] + '</text></g>';
      }).join('');
      var hist = '<figure class="sim-fig"><svg class="cr-hist" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('cr_hist')) + '" dir="ltr">'
        + '<line class="ax" x1="28" x2="' + (W - 6) + '" y1="' + (H - 22) + '" y2="' + (H - 22) + '"/>' + bars + '</svg><figcaption>' + esc(T('cr_hist_cap')) + '</figcaption></figure>';
      var stats = '<div class="sim-stats">' + stat(L(st.pgs) + ' × ' + L(r.size), T('cr_s_pgs')) + stat(mv ? pct(mv.frac) : '–', T('cr_s_moved'), mv && mv.frac ? 'hot' : '')
        + stat(mv ? L(mv.pgs) : '–', T('cr_s_remap')) + stat(L(degraded), T('cr_s_degraded'), degraded ? 'warn' : '') + stat(L(none), T('cr_s_none'), none ? 'warn' : '') + '</div>';
      var note = '<p class="sim-note">' + rich(mv ? T('cr_moved_note', { what: st.last }) : T('cr_hint')) + '</p>';
      var rows = r.pgs.map(function (p, i) {
        var ch = mv && mv.changed[i], old = ch ? st.prev[i].up : null;
        return '<li class="' + (ch ? 'chg' : '') + '"><span class="pgid">' + st.pool + '.' + i.toString(16) + '</span><span class="set">[' + p.up.map(function (o, j) {
          var nw = old && (r.ec ? old[j] !== o : old.indexOf(o) < 0);
          return '<i class="' + (o === p.primary ? 'pri ' : '') + (nw ? 'new' : '') + '">' + (o === C.NONE ? '∅' : o) + '</i>';
        }).join(',') + ']</span></li>';
      }).join('');
      var table = '<details class="cr-pgs" open><summary>' + esc(T('cr_map', { n: L(st.pgs) })) + '</summary><ol dir="ltr">' + rows + '</ol></details>';
      var o = C.objectToPg(st.obj || '', st.pgs), pg = r.pgs[o.ps];
      var look = '<div class="cr-look" dir="ltr"><span class="cmd">$ ceph osd map pool' + st.pool + ' ' + esc(st.obj || '') + '</span>'
        + 'ceph_str_hash_rjenkins → 0x' + o.hash.toString(16) + ' · ceph_stable_mod(·, ' + st.pgs + ', ' + C.pgMask(st.pgs) + ') → pg <b>' + st.pool + '.' + o.ps.toString(16) + '</b>'
        + ' · pps 0x' + pg.pps.toString(16) + ' · up [' + pg.up.map(function (x) { return x === C.NONE ? 'NONE' : x; }).join(',') + '] p' + pg.primary + '</div>';
      return stats + note + hist + look + table;
    },
    input: function (st, k, v, el) {
      var snap = function (what) { st.prev = model(st).pgs; st.last = what; };
      if (k === 'preset') { st.preset = v; st.hosts = fromPreset(v); st.prev = null; return 'all'; }
      if (k === 'type') { st.type = v; st.prev = null; return 'all'; }
      if (k === 'size' || k === 'k' || k === 'm') { st[k] = +v; st.prev = null; return 'all'; }
      if (k === 'fd' || k === 'pgs') { st[k] = k === 'pgs' ? +v : v; st.prev = null; return 'out'; }
      if (k === 'obj') { st.obj = String(v).slice(0, 200); return 'out'; }
      if (k === 'w') {
        var p = el.getAttribute('data-p').split('.'), o = st.hosts[+p[0]].osds[+p[1]], nv = Math.max(0, Math.min(64, parseFloat(v) || 0));
        if (nv === o.w) return null;
        snap(T('cr_ch_w', { o: 'osd.' + o.id, w: L(nv) })); o.w = nv; return 'out';
      }
      return null;
    },
    act: function (st, a, el) {
      var p = (el.getAttribute('data-p') || '').split('.'), ho = st.hosts[+p[0]], o = ho && p.length > 1 ? ho.osds[+p[1]] : null;
      var snap = function (what) { st.prev = model(st).pgs; st.last = what; };
      var maxId = function () { var m = -1; st.hosts.forEach(function (x) { x.osds.forEach(function (y) { m = Math.max(m, y.id); }); }); return m; };
      if (a === 'out') { snap(T(o.out ? 'cr_ch_in' : 'cr_ch_out', { o: 'osd.' + o.id })); o.out = !o.out; return 'all'; }
      if (a === 'down') { snap(T(o.down ? 'cr_ch_up' : 'cr_ch_down', { o: 'osd.' + o.id })); o.down = !o.down; return 'all'; }
      if (a === 'rm') {
        if (st.hosts.reduce(function (n, x) { return n + x.osds.length; }, 0) <= 1) return null;
        snap(T('cr_ch_rm', { o: 'osd.' + o.id })); ho.osds.splice(+p[1], 1); if (!ho.osds.length) st.hosts.splice(+p[0], 1); return 'all';
      }
      if (a === 'addosd') { var id = maxId() + 1; snap(T('cr_ch_add', { o: 'osd.' + id })); ho.osds.push({ id: id, w: 4, out: false, down: false }); return 'all'; }
      if (a === 'addhost') {
        if (st.hosts.length >= 12) return null;
        var b = maxId() + 1, nm = 'host' + (st.hosts.length + 1); snap(T('cr_ch_host', { h: nm }));
        st.hosts.push({ name: nm, osds: [0, 1, 2].map(function (i) { return { id: b + i, w: 4, out: false, down: false }; }) }); return 'all';
      }
      return null;
    },
    // the print figure: the default map, then osd.4 marked out, so the movement is visible
    fallbackState: function (st) { st.prev = model(st).pgs; st.last = T('cr_ch_out', { o: 'osd.4' }); st.hosts[1].osds[0].out = true; return st; }
  };
})(typeof self !== 'undefined' ? self : this);
