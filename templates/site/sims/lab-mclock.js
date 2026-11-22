/* mClock QoS profiles (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * Profiles from src/common/mclock_common.h, the conversion of ratios to bytes/s per shard from
 * ClientRegistry::update_from_profile and MclockConfig::set_from_config, the cost of one op from
 * MclockConfig::calc_scaled_cost, and the steady-state share from dmClock (src/dmclock/src/dmclock_server.h:
 * reservation first, then weight; ops served by weight also reduce the reservation tags, so the reservation is a floor). */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, bytes = h.bytes, clamp = h.clamp;
  // Row labels mix Persian and Latin words: give them an RTL base direction in FA so the word order survives inside the LTR chart.
  var rowLabel = function (y, txt) {
    txt = txt.replace(/\s*\(.*\)$/, ''); // the legend keeps the full name; the chart has 100px
    return h.fa() ? '<text x="104" y="' + y + '" class="lx-th" direction="rtl" style="direction:rtl;unicode-bidi:embed">' + esc(txt) + '</text>'
      : '<text x="4" y="' + y + '" class="lx-th">' + esc(txt) + '</text>';
  };
  var MiB = 1 << 20;
  var PROF = {   // [reservation, weight, limit] for client, background_recovery, background_best_effort
    balanced: [[0.5, 1, 0], [0.5, 1, 0], [0.05, 2, 0.9]],
    high_client_ops: [[0.6, 2, 0], [0.4, 1, 0], [0.05, 4, 0.7]],
    high_recovery_ops: [[0.3, 1, 0], [0.7, 2, 0], [0.05, 2, 0]]
  };
  var DEV = { hdd: { iops: 315, bw: 150 * MiB, shards: 1 }, ssd: { iops: 21500, bw: 1200 * MiB, shards: 8 } };
  var CLS = ['client', 'recovery', 'besteffort'];
  function config(dev, iops, shards) {
    var d = DEV[dev], bw = Math.max(1, d.bw), io = Math.max(1, iops || d.iops);
    return { costPerIo: bw / io, capPerShard: bw / (shards || d.shards), bw: bw, iops: io, shards: shards || d.shards };
  }
  function scaledCost(cfg, itemCost) { return Math.max(Math.max(1, itemCost), Math.floor(cfg.costPerIo)); }  // calc_scaled_cost
  function qos(prof, cap) {   // update_from_profile: 0 reservation = minimum, 0 limit = maximum
    return PROF[prof].map(function (p) { return { r: p[0] ? p[0] * cap : 0, w: p[1], l: p[2] ? p[2] * cap : Infinity }; });
  }
  // fluid steady state: each class gets min(demand, limit, max(reservation, weight × λ)), λ chosen to fill the shard
  function allocate(cap, cls) {
    var floor = cls.map(function (c) { return Math.min(c.d, c.l, c.r); }), fs = floor.reduce(function (a, b) { return a + b; }, 0);
    if (fs >= cap) return { a: floor.map(function (f) { return fs ? f * cap / fs : 0; }), lambda: 0, phase: 'res' };
    function f(lm) { return cls.reduce(function (s, c, i) { return s + Math.min(c.d, c.l, Math.max(floor[i], c.w * lm)); }, 0); }
    var hi = 1; while (f(hi) < cap && hi < 1e18) hi *= 2;
    if (f(hi) < cap) return { a: cls.map(function (c) { return Math.min(c.d, c.l); }), lambda: Infinity, phase: 'idle' };
    var lo = 0; for (var it = 0; it < 200; it++) { var mid = (lo + hi) / 2; if (f(mid) < cap) lo = mid; else hi = mid; }
    return { a: cls.map(function (c, i) { return Math.min(c.d, c.l, Math.max(floor[i], c.w * hi)); }), lambda: hi, phase: 'wgt' };
  }
  function model(st) {
    var cfg = config(st.dev, st.iops, st.shards), q = qos(st.prof, cfg.capPerShard);
    var dem = [[st.cOps, st.cSize], [st.rOps, st.rSize], [st.bOps, st.bSize]].map(function (x) { var c = scaledCost(cfg, x[1]); return { ops: x[0], cost: c, perShard: x[0] * c / cfg.shards }; });
    var cls = q.map(function (c, i) { return { r: c.r, w: c.w, l: c.l, d: dem[i].perShard }; });
    var al = allocate(cfg.capPerShard, cls);
    var served = al.a.map(function (a, i) { return dem[i].cost ? a * cfg.shards / dem[i].cost : 0; });
    return { cfg: cfg, q: q, dem: dem, cls: cls, al: al, served: served };
  }

  S.X = S.X || {};
  S.X.mclock = {
    PROF: PROF, DEV: DEV, config: config, allocate: allocate, scaledCost: scaledCost, model: model,
    test: function (t) {
      var g = t.G.mclock;
      if (g) {
        Object.keys(g.profiles).forEach(function (p) { t.eq(PROF[p], g.profiles[p], 'profile ' + p + ' matches mclock_common.h'); });
        var o = g.options;
        t.eq([DEV.hdd.iops, DEV.ssd.iops, DEV.hdd.bw, DEV.ssd.bw, DEV.hdd.shards, DEV.ssd.shards],
             [o.osd_mclock_max_capacity_iops_hdd, o.osd_mclock_max_capacity_iops_ssd, o.osd_mclock_max_sequential_bandwidth_hdd, o.osd_mclock_max_sequential_bandwidth_ssd, o.osd_op_num_shards_hdd, o.osd_op_num_shards_ssd], 'device defaults match osd.yaml.in');
        t.eq(S.DEFS.mclock.defaults().prof, o.osd_mclock_profile, 'default profile');
      }
      var c = config('hdd'); t.eq(Math.round(c.costPerIo), 499322, 'hdd cost per io = 150 MiB / 315');
      t.eq(scaledCost(c, 4096), 499321, '4 KiB op costs cost_per_io (truncated)'); t.eq(scaledCost(c, 4 * MiB), 4 * MiB, '4 MiB op costs its size');
      var cap = 100, r;
      r = allocate(cap, [{ r: 50, w: 1, l: Infinity, d: 1000 }, { r: 50, w: 1, l: Infinity, d: 1000 }, { r: 5, w: 2, l: 90, d: 1000 }]);
      t.ok(Math.abs(r.a[0] + r.a[1] + r.a[2] - cap) < 1e-6, 'saturated: the shard is full');
      t.ok(r.phase === 'res' && Math.abs(r.a[0] - 100 * 50 / 105) < 1e-9, 'reservations over 100% are served in proportion');
      r = allocate(cap, [{ r: 30, w: 1, l: Infinity, d: 1000 }, { r: 0, w: 1, l: Infinity, d: 1000 }, { r: 0, w: 2, l: 10, d: 1000 }]);
      t.ok(Math.abs(r.a[2] - 10) < 1e-6 && Math.abs(r.a[0] - 45) < 1e-6 && Math.abs(r.a[1] - 45) < 1e-6, 'limit caps a class, the rest is split by weight');
      r = allocate(cap, [{ r: 60, w: 2, l: Infinity, d: 20 }, { r: 40, w: 1, l: Infinity, d: 1000 }, { r: 0, w: 4, l: 70, d: 0 }]);
      t.ok(Math.abs(r.a[0] - 20) < 1e-6 && Math.abs(r.a[1] - 80) < 1e-6, 'unused share goes to the busy class');
      r = allocate(cap, [{ r: 50, w: 1, l: Infinity, d: 10 }, { r: 50, w: 1, l: Infinity, d: 10 }, { r: 5, w: 2, l: 90, d: 10 }]);
      t.eq(r.phase, 'idle', 'low demand: everyone is served');
      // properties over random inputs
      var seed = 7; function rnd() { seed = (seed * 1103515245 + 12345) & 0x7fffffff; return seed / 0x7fffffff; }
      for (var i = 0; i < 300; i++) {
        var cl = [0, 1, 2].map(function () { return { r: rnd() < 0.3 ? 0 : rnd() * 60, w: 1 + Math.floor(rnd() * 4), l: rnd() < 0.5 ? Infinity : 10 + rnd() * 90, d: rnd() * 150 }; });
        r = allocate(100, cl); var sum = r.a.reduce(function (a, b) { return a + b; }, 0), totD = cl.reduce(function (a, x) { return a + Math.min(x.d, x.l); }, 0);
        t.ok(sum <= 100 + 1e-6 && Math.abs(sum - Math.min(100, totD)) < 1e-6, 'work conserving ' + i);
        t.ok(r.a.every(function (a, j) { return a <= Math.min(cl[j].d, cl[j].l) + 1e-6; }), 'never above demand or limit ' + i);
        if (r.phase !== 'res') t.ok(r.a.every(function (a, j) { return a >= Math.min(cl[j].d, cl[j].l, cl[j].r) - 1e-6; }), 'reservation floor ' + i);
      }
    }
  };

  var SIZES = [[4096, '4 KiB'], [65536, '64 KiB'], [MiB, '1 MiB'], [4 * MiB, '4 MiB'], [8 * MiB, '8 MiB']];
  S.DEFS.mclock = {
    icon: 'M4 18V6M4 18h16M8 15v-4M12 15V8M16 15v-6',
    defaults: function () { return { dev: 'hdd', prof: 'balanced', iops: 315, shards: 1, cOps: 300, cSize: 4096, rOps: 30, rSize: 4 * MiB, bOps: 10, bSize: 4 * MiB }; },
    refs: [['src/common/mclock_common.h :: HIGH_CLIENT_OPS, HIGH_RECOVERY_OPS, BALANCED', 'mclock_r1'],
           ['src/common/mclock_common.cc :: ClientRegistry::update_from_profile, MclockConfig::set_from_config, calc_scaled_cost', 'mclock_r2'],
           ['src/dmclock/src/dmclock_server.h :: PullPriorityQueue::pull_request, reduce_reservation_tags', 'mclock_r3'],
           ['src/common/options/osd.yaml.in :: osd_mclock_max_capacity_iops_*, osd_mclock_max_sequential_bandwidth_*, osd_op_num_shards_*', 'mclock_r4']],
    controls: function (st) {
      function cls(k, o, s) { return '<div class="sim-row">' + field(T('mclock_' + k), numIn(o, st[o], 0, 100000, 1)) + field(T('mclock_size'), sel(s, SIZES.map(function (x) { return [x[0], x[1]]; }), st[s])) + '</div>'; }
      return '<div class="sim-row">' + field(T('mclock_dev'), sel('dev', [['hdd', 'HDD'], ['ssd', 'SSD']], st.dev)) + field('osd_mclock_profile', sel('prof', [['balanced', 'balanced'], ['high_client_ops', 'high_client_ops'], ['high_recovery_ops', 'high_recovery_ops']], st.prof))
        + field(T('mclock_iops'), numIn('iops', st.iops, 1, 1000000, 1), esc(T('mclock_iops_h'))) + field(T('mclock_shards'), sel('shards', [1, 2, 4, 5, 8, 16], st.shards)) + '</div>'
        + cls('client', 'cOps', 'cSize') + cls('recovery', 'rOps', 'rSize') + cls('besteffort', 'bOps', 'bSize');
    },
    view: function (st) {
      var m = model(st), cap = m.cfg.capPerShard, W = 640, BH = 30, y0 = 8, xs = function (v) { return 110 + (W - 130) * v / cap; };
      var colors = ['c-cl', 'c-rc', 'c-be'], svg = '<svg class="lx-svg" style="direction:ltr" viewBox="0 0 ' + W + ' ' + (y0 + 4 * (BH + 14) + 10) + '" role="img" aria-label="' + esc(T('mclock_fig')) + '" dir="ltr">';
      // stacked bar of one shard
      var x = 110; svg += rowLabel(y0 + BH / 2 + 4, T('mclock_shard'));
      m.al.a.forEach(function (a, i) { var w = (W - 130) * a / cap; svg += '<rect x="' + x + '" y="' + y0 + '" width="' + Math.max(0, w) + '" height="' + BH + '" class="mc-b ' + colors[i] + '"/>'; x += w; });
      svg += '<rect x="110" y="' + y0 + '" width="' + (W - 130) + '" height="' + BH + '" class="lx-bg" fill="none"/>';
      // per class: demand (light), granted (solid), reservation and limit marks
      m.cls.forEach(function (c, i) {
        var y = y0 + (i + 1) * (BH + 14), dem = Math.min(c.d, cap * 1.5), lim = isFinite(c.l) ? c.l : null;
        svg += rowLabel(y + BH / 2 + 4, T('mclock_' + CLS[i]))
          + '<rect x="110" y="' + (y + 6) + '" width="' + Math.max(0, xs(Math.min(dem, cap)) - 110) + '" height="' + (BH - 12) + '" class="mc-d ' + colors[i] + '"/>'
          + '<rect x="110" y="' + y + '" width="' + Math.max(0, xs(m.al.a[i]) - 110) + '" height="' + BH + '" class="mc-b ' + colors[i] + '"/>'
          + (c.r ? '<line x1="' + xs(c.r) + '" x2="' + xs(c.r) + '" y1="' + (y - 3) + '" y2="' + (y + BH + 3) + '" class="mc-res"/>' : '')
          + (lim != null && lim <= cap ? '<line x1="' + xs(lim) + '" x2="' + xs(lim) + '" y1="' + (y - 3) + '" y2="' + (y + BH + 3) + '" class="mc-lim"/>' : '')
          + (c.d > cap ? '<text x="' + (W - 16) + '" y="' + (y + BH / 2 + 4) + '" class="lx-th" text-anchor="end">≫</text>' : '');
      });
      svg += '</svg>';
      var rows = m.cls.map(function (c, i) {
        var ok = m.al.a[i] >= c.d - 1e-6;
        return '<tr' + (ok ? '' : ' class="lx-red"') + '><th>' + esc(T('mclock_' + CLS[i])) + '</th><td>' + pct(c.r / cap) + '</td><td>' + L(c.w) + '</td><td>' + (isFinite(c.l) ? pct(c.l / cap) : '∞') + '</td><td><bdi dir="ltr">' + bytes(m.dem[i].cost) + '</bdi></td>'
          + '<td>' + num(m.dem[i].ops) + '</td><td>' + num(m.served[i]) + '</td><td>' + pct(m.al.a[i] / cap) + '</td></tr>';
      }).join('');
      var used = m.al.a.reduce(function (a, b) { return a + b; }, 0) / cap;
      var cs = m.served[0] / Math.max(1e-9, m.dem[0].ops);
      return '<div class="sim-stats">' + stat(num(m.served[0]) + ' / ' + num(m.dem[0].ops), T('mclock_s_client'), cs < 0.999 ? 'warn' : '') + stat(bytes(m.served[1] * st.rSize) + '/s', T('mclock_s_rec'), 'hot')
        + stat(bytes(m.cfg.costPerIo), T('mclock_s_cost')) + stat(pct(used), T('mclock_s_used'), used > 0.999 ? 'hot' : '') + '</div>'
        + '<div class="sim-fig">' + svg + '<div class="lx-legend"><span class="mc-k c-cl"></span>' + esc(T('mclock_client')) + ' <span class="mc-k c-rc"></span>' + esc(T('mclock_recovery')) + ' <span class="mc-k c-be"></span>' + esc(T('mclock_besteffort')) + ' · ' + esc(T('mclock_leg')) + '</div></div>'
        + '<table class="sim-t"><thead><tr><th></th><th>res</th><th>wgt</th><th>lim</th><th>' + esc(T('mclock_c_cost')) + '</th><th>' + esc(T('mclock_c_want')) + '</th><th>' + esc(T('mclock_c_got')) + '</th><th>' + esc(T('mclock_c_share')) + '</th></tr></thead><tbody>' + rows + '</tbody></table>'
        + '<p class="sim-note">' + tx(m.al.phase === 'res' ? 'mclock_ph_res' : m.al.phase === 'idle' ? 'mclock_ph_idle' : 'mclock_ph_wgt') + '</p>'
        + '<div class="sim-formula" dir="ltr">cost_per_io = ' + Math.round(m.cfg.bw / MiB) + ' MiB / ' + m.cfg.iops + ' IOPS = ' + Math.round(m.cfg.costPerIo) + ' B · capacity_per_shard = ' + Math.round(m.cfg.bw / MiB) + ' MiB / ' + m.cfg.shards + ' shard(s) · op cost = max(size, cost_per_io) · share = min(demand, lim, max(res, wgt × λ))</div>'
        + '<p class="sim-note">' + tx('mclock_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'dev') { st.dev = v; st.iops = DEV[v].iops; st.shards = DEV[v].shards; if (v === 'ssd' && st.cOps === 300) st.cOps = 20000; if (v === 'hdd' && st.cOps === 20000) st.cOps = 300; return 'all'; }
      if (k === 'prof') { st.prof = v; return 'out'; }
      if (/Size$/.test(k) || k === 'shards') { st[k] = +v; return 'out'; }
      if (k === 'iops' || /Ops$/.test(k)) { var n = parseFloat(v); if (!isFinite(n)) return null; st[k] = clamp(n, k === 'iops' ? 1 : 0, 1000000); return 'out'; }
      return null;
    },
    say: function (st) { var m = model(st); return T('mclock_s_client') + ': ' + num(m.served[0]); }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
