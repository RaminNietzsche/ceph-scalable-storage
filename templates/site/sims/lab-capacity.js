/* Capacity and full-ratio planner (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * MAX AVAIL is a port of PGMap::get_rule_avail with CrushWrapper::get_rule_weight_osd_map (float weights),
 * each OSD's state is a port of OSDService::recalc_full_state, and the health check names are those of
 * OSDMap::check_health. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, rich = h.rich, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, numIn = h.numIn, stat = h.stat, clamp = h.clamp, seg = h.seg;
  var f32 = Math.fround, TIB = Math.pow(2, 40);

  // OSDService::recalc_full_state (luminous and later, no injection; ratio == physical ratio here)
  function fullState(ratio, pratio, r) {
    var nearfull = f32(r.nearfull), backfillfull = Math.max(f32(r.backfillfull), nearfull), full = Math.max(f32(r.full), backfillfull), failsafe = Math.max(f32(r.failsafe), full);
    if (full <= 0 || backfillfull <= 0 || nearfull <= 0) { full = backfillfull = nearfull = failsafe; }
    if (pratio > failsafe) return 'failsafe';
    if (ratio > full) return 'full';
    if (ratio > backfillfull) return 'backfillfull';
    if (pratio > nearfull) return 'nearfull';
    return 'none';
  }
  // PGMap::get_rule_avail: osds = [{w: crush weight, total: bytes, avail: bytes}] under the rule's one take
  function ruleAvail(osds, fullRatio) {
    var sum = f32(0);
    osds.forEach(function (o) { sum = f32(sum + f32(o.w)); });                  // _get_take_weight_osd_map
    var fratio = f32(fullRatio), min = -1, at = -1;
    osds.forEach(function (o, i) {
      var w = sum > 0 ? f32(f32(o.w) / sum) : 0;                                 // _normalize_weight_map
      if (o.total === 0 || w === 0) return;                                      // an out OSD reports zeroed stats
      var kb = Math.floor(o.total / 1024), kbAvail = Math.floor(o.avail / 1024);
      var unusable = kb * (1.0 - fratio);
      var avail = Math.max(0.0, kbAvail - unusable) * 1024.0;
      var proj = Math.trunc(avail / w);
      if (min < 0 || proj < min) { min = proj; at = i; }
    });
    return { avail: min, at: at };
  }
  function rawRate(t) { return t.indexOf('ec') === 0 ? (+t.split('-')[1] + +t.split('-')[2]) / +t.split('-')[1] : +t.slice(3); }
  function needDomains(t) { return t.indexOf('ec') === 0 ? +t.split('-')[1] + +t.split('-')[2] : +t.slice(3); }
  // the cluster: hosts × OSDs; stored data spread by weight with a linear imbalance; a lost host's share moves to the rest
  function model(st) {
    var osds = [], n = st.hosts * st.per, rate = rawRate(st.pool), raw = st.stored * TIB * rate;
    for (var hI = 0; hI < st.hosts; hI++) for (var j = 0; j < st.per; j++) {
      var id = hI * st.per + j, size = (st.big && id === n - 1 ? 2 : 1) * st.tib * TIB;
      osds.push({ id: id, host: hI, size: size, w: size / TIB, lost: st.lose && hI === 0 });
    }
    var alive = osds.filter(function (o) { return !o.lost; }), canHeal = !st.lose || st.hosts - 1 >= needDomains(st.pool);
    var pool = st.lose && !canHeal ? osds : alive;                              // without enough hosts the copies cannot move
    var tw = pool.reduce(function (a, o) { return a + o.w; }, 0), m = pool.length;
    pool.forEach(function (o, i) {
      var tilt = m > 1 ? (st.imb / 100) * (2 * i / (m - 1) - 1) : 0;
      o.used = raw * (o.w / tw) * (1 + tilt);
    });
    osds.forEach(function (o) {
      if (o.used == null) o.used = 0;
      if (o.lost) { o.total = 0; o.avail = 0; o.ratio = 0; o.state = 'lost'; return; }
      o.used = Math.min(o.used, o.size); o.total = o.size; o.avail = o.size - o.used; o.ratio = o.used / o.size;
      o.state = fullState(o.ratio, o.ratio, st);
    });
    var ra = ruleAvail(osds, st.full);
    return { osds: osds, rate: rate, raw: raw, maxAvail: ra.avail < 0 ? 0 : ra.avail / rate, at: ra.at, canHeal: canHeal };
  }

  S.X = S.X || {};
  S.X.capacity = {
    fullState: fullState, ruleAvail: ruleAvail, model: model,
    test: function (t) {
      (t.G.capacity_full || []).forEach(function (c) { t.eq(fullState(c[0], c[1], { nearfull: c[2], backfillfull: c[3], full: c[4], failsafe: c[5] }), c[6], 'recalc_full_state ' + JSON.stringify(c)); });
      (t.G.capacity_avail || []).forEach(function (c) {
        var r = ruleAvail(c.osds.map(function (o) { return { w: o[0], total: o[1], avail: o[2] }; }), c.full);
        t.eq(r.avail, c.want, 'get_rule_avail case ' + c.name);
      });
      // a balanced cluster: MAX AVAIL = (full_ratio × raw − used) / raw_used_rate, within float rounding
      var st = S.DEFS.capacity.defaults(); st.imb = 0; st.big = false; st.lose = false;
      var r = model(st), raw = st.hosts * st.per * st.tib * TIB, want = (raw * st.full - r.raw) / r.rate;
      t.near(r.maxAvail / want, 1, 'balanced MAX AVAIL', 1e-5);
    }
  };

  var STATE_C = { none: 'ok', nearfull: 'near', backfillfull: 'bfull', full: 'full', failsafe: 'full', lost: 'off' };
  S.DEFS.capacity = {
    icon: 'M4 20V10M9 20V6M14 20v-8M19 20V4M3 8h18',
    defaults: function () { return { hosts: 4, per: 3, tib: 8, pool: 'rep3', stored: 20, imb: 10, big: false, lose: false, nearfull: 0.85, backfillfull: 0.9, full: 0.95, failsafe: 0.97 }; },
    refs: [['src/mon/PGMap.cc :: get_rule_avail, dump_object_stat_sum (max_avail = avail / raw_used_rate)', 'capacity_r1'],
           ['src/crush/CrushWrapper.cc :: get_rule_weight_osd_map, _get_take_weight_osd_map, _normalize_weight_map', 'capacity_r2'],
           ['src/osd/OSD.cc :: OSDService::recalc_full_state', 'capacity_r3'],
           ['src/osd/OSDMap.cc :: check_health (OSD_NEARFULL, OSD_BACKFILLFULL, OSD_FULL), pool_raw_used_rate', 'capacity_r4'],
           ['src/common/options/global.yaml.in :: mon_osd_nearfull_ratio (0.85), mon_osd_backfillfull_ratio (0.90), mon_osd_full_ratio (0.95), osd_failsafe_full_ratio (0.97)', 'capacity_r5']],
    controls: function (st) {
      var pools = [['rep2', 'rep 2'], ['rep3', 'rep 3'], ['ec-2-1', 'EC 2+1'], ['ec-4-2', 'EC 4+2'], ['ec-8-3', 'EC 8+3']];
      return '<div class="sim-row">' + field(T('capacity_hosts'), numIn('hosts', st.hosts, 2, 12)) + field(T('capacity_per'), numIn('per', st.per, 1, 12)) + field(T('capacity_tib'), numIn('tib', st.tib, 1, 30))
        + field(T('capacity_pool'), sel('pool', pools, st.pool)) + field(T('capacity_stored'), numIn('stored', st.stored, 0, 5000, 1)) + field(T('capacity_imb'), numIn('imb', st.imb, 0, 60, 1)) + '</div>'
        + '<div class="sim-row">' + field('nearfull_ratio', sel('nearfull', [0.75, 0.8, 0.85, 0.9], st.nearfull)) + field('backfillfull_ratio', sel('backfillfull', [0.85, 0.9, 0.92], st.backfillfull))
        + field('full_ratio', sel('full', [0.9, 0.95, 0.97], st.full))
        + '<label class="sim-f sim-chk"><span>' + esc(T('capacity_big')) + '</span><input type="checkbox" data-k="big"' + (st.big ? ' checked' : '') + '></label>'
        + '<label class="sim-f sim-chk"><span>' + esc(T('capacity_lose')) + '</span><input type="checkbox" data-k="lose"' + (st.lose ? ' checked' : '') + '></label></div>';
    },
    view: function (st) {
      var r = model(st), W = 720, H = 220, n = r.osds.length, bw = (W - 90) / n, top = 14, bot = H - 24, y = function (v) { return bot - v * (bot - top); };
      var lines = [['nearfull', st.nearfull, 0], ['backfillfull', st.backfillfull, 1], ['full', st.full, 0]].map(function (x) {
        return '<line class="lx-th th-' + x[0] + '" x1="40" x2="' + (W - 44) + '" y1="' + y(x[1]) + '" y2="' + y(x[1]) + '"/><text class="lx-tl" x="' + (x[2] ? W - 40 : 38) + '" y="' + (y(x[1]) + 4) + '" text-anchor="' + (x[2] ? 'start' : 'end') + '">' + Math.round(x[1] * 100) + '%</text>';
      }).join('');
      var bars = r.osds.map(function (o, i) {
        var x = 44 + i * bw, hh = (bot - y(o.ratio));
        return '<g><title>osd.' + o.id + ' (host' + (o.host + 1) + '): ' + (o.state === 'lost' ? 'down/out' : Math.round(o.ratio * 1000) / 10 + '% · ' + o.state) + '</title>'
          + '<rect class="lx-bg" x="' + (x + 1) + '" y="' + top + '" width="' + Math.max(2, bw - 2) + '" height="' + (bot - top) + '" rx="2"/>'
          + '<rect class="lx-b f-' + STATE_C[o.state] + '" x="' + (x + 1) + '" y="' + (bot - hh) + '" width="' + Math.max(2, bw - 2) + '" height="' + hh + '" rx="2"/>'
          + (i === r.at ? '<text class="lx-star" x="' + (x + bw / 2) + '" y="' + (bot - hh - 3) + '" text-anchor="middle">▼</text>' : '')
          + '<text class="lx-x" x="' + (x + bw / 2) + '" y="' + (H - 8) + '" text-anchor="middle">' + o.id + '</text></g>';
      }).join('');
      var counts = { nearfull: 0, backfillfull: 0, full: 0, failsafe: 0 };
      r.osds.forEach(function (o) { if (counts[o.state] != null) counts[o.state]++; });
      var checks = [];
      if (counts.full + counts.failsafe) checks.push(['HEALTH_ERR', 'OSD_FULL', T('capacity_c_full', { n: L(counts.full + counts.failsafe) })]);
      if (counts.backfillfull) checks.push(['HEALTH_WARN', 'OSD_BACKFILLFULL', T('capacity_c_bfull', { n: L(counts.backfillfull) })]);
      if (counts.nearfull) checks.push(['HEALTH_WARN', 'OSD_NEARFULL', T('capacity_c_near', { n: L(counts.nearfull) })]);
      var rawT = r.osds.reduce(function (a, o) { return a + (o.state === 'lost' ? 0 : o.size); }, 0);
      var usedT = r.osds.reduce(function (a, o) { return a + o.used; }, 0);
      var worst = r.osds.reduce(function (a, o) { return o.ratio > a ? o.ratio : a; }, 0);
      return '<div class="sim-stats">' + stat(num(rawT / TIB, 1) + ' TiB', T('capacity_s_raw')) + stat(num(usedT / TIB, 1) + ' TiB', T('capacity_s_used'))
        + stat(num(r.maxAvail / TIB, 1) + ' TiB', T('capacity_s_avail'), r.maxAvail <= 0 ? 'warn' : '') + stat(pct(worst), T('capacity_s_worst'), worst > st.nearfull ? 'warn' : '') + '</div>'
        + '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('capacity_fig')) + '" dir="ltr">' + bars + lines + '</svg><figcaption>' + esc(T('capacity_cap')) + '</figcaption></figure>'
        + (checks.length ? '<ul class="lx-health" dir="ltr">' + checks.map(function (c) { return '<li class="' + (c[0] === 'HEALTH_ERR' ? 'err' : 'warn') + '"><b>' + c[0] + '</b> ' + c[1] + ': <bdi dir="auto">' + esc(c[2]) + '</bdi></li>'; }).join('') + '</ul>'
          : '<p class="lx-healthy" dir="ltr"><b>HEALTH_OK</b></p>')
        + (st.lose && !r.canHeal ? '<p class="sim-warn">' + tx('capacity_noheal', { n: L(needDomains(st.pool)) }) + '</p>' : '')
        + (st.lose && r.canHeal && counts.backfillfull + counts.full ? '<p class="sim-warn">' + tx('capacity_toofull') + '</p>' : '')
        + '<div class="sim-formula" dir="ltr">MAX AVAIL = min over OSDs ( (kb_avail − kb × (1 − full_ratio)) × 1024 / w<sub>i</sub> ) / raw_used_rate, w<sub>i</sub> = crush_weight<sub>i</sub> / Σ crush_weight · raw_used_rate = ' + (Math.round(r.rate * 1000) / 1000)
        + '<br>OSD state: ratio &gt; failsafe → FAILSAFE · &gt; full → FULL · &gt; backfillfull → BACKFILLFULL · &gt; nearfull → NEARFULL</div>'
        + '<p class="sim-note">' + tx('capacity_note') + '</p>';
    },
    input: function (st, k, v, el) {
      if (k === 'hosts') { st.hosts = clamp(parseInt(v, 10) || 2, 2, 12); return 'out'; }
      if (k === 'per') { st.per = clamp(parseInt(v, 10) || 1, 1, 12); return 'out'; }
      if (k === 'tib') { st.tib = clamp(parseFloat(v) || 1, 1, 30); return 'out'; }
      if (k === 'stored') { st.stored = clamp(parseFloat(v) || 0, 0, 5000); return 'out'; }
      if (k === 'imb') { st.imb = clamp(parseFloat(v) || 0, 0, 60); return 'out'; }
      if (k === 'pool') { st.pool = v; return 'out'; }
      if (k === 'nearfull' || k === 'backfillfull' || k === 'full') { st[k] = +v; return 'out'; }
      if (k === 'big' || k === 'lose') { st[k] = !!el.checked; return 'out'; }
      return null;
    },
    say: function (st) { var r = model(st); return T('capacity_s_avail') + ': ' + num(r.maxAvail / TIB, 1) + ' TiB'; },
    fallbackState: function (st) { st.stored = 30; st.lose = true; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
