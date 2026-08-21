/* PG count and EC/replication calculators (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, C = h.C, T = h.T, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, numIn = h.numIn, stat = h.stat, clamp = h.clamp, range = h.range;
  var SIZES = [[2, 'rep 2'], [3, 'rep 3'], [4, 'rep 4'], ['3e', 'EC 2+1'], ['4e', 'EC 2+2'], ['6e', 'EC 4+2'], ['8e', 'EC 6+2'], ['11e', 'EC 8+3']];

  S.DEFS.pgcalc = {
    icon: 'M4 4h16v16H4zM4 9h16M9 9v11M14 9v11',
    defaults: function () {
      return { osds: 24, target: 200, maxpg: 500, pools: [
        { name: 'rbd', size: '3', ratio: 45, bulk: true, auto: true, pg: 32 },
        { name: 'cephfs.data', size: '6e', ratio: 30, bulk: true, auto: true, pg: 32 },
        { name: 'cephfs.meta', size: '3', ratio: 2, bulk: false, auto: true, pg: 16 },
        { name: '.mgr', size: '3', ratio: 0, bulk: false, auto: true, pg: 1 }] };
    },
    refs: [['src/pybind/mgr/pg_autoscaler/module.py :: _get_pool_status, _calculate_final_pool_pg_target', 'r_as_passes'],
           ['module.py :: PoolGroup, _find_optimal_pg_distribution, _append_result', 'r_as_knap'], ['module.py :: nearest_power_of_two, get_dynamic_threshold', 'r_as_pow2'],
           ['src/osd/OSDMap.cc :: pool_raw_used_rate', 'r_as_raw'], ['src/common/options/mgr.yaml.in :: mon_target_pg_per_osd (200)', 'r_as_opt'],
           ['src/common/options/global.yaml.in :: mon_max_pg_per_osd (500), osd_pool_default_pg_num (32)', 'r_as_opt2']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('pc_osds'), numIn('osds', st.osds, 1, 5000, 1))
        + field('mon_target_pg_per_osd', sel('target', [50, 100, 200, 300], st.target)) + field('mon_max_pg_per_osd', sel('maxpg', [250, 500, 1000], st.maxpg)) + '</div>'
        + '<div class="table-wrap"><table class="sim-t pc-pools"><thead><tr><th>' + esc(T('pc_pool')) + '</th><th>' + esc(T('pc_psize')) + '</th><th>' + esc(T('pc_share')) + '</th><th>bulk</th><th>autoscale</th><th>pg_num</th><th><span class="vh">' + esc(T('pc_rm')) + '</span></th></tr></thead><tbody>'
        + st.pools.map(function (p, i) {
          return '<tr><td><input type="text" dir="ltr" data-k="name" data-p="' + i + '" data-fid="n' + i + '" value="' + esc(p.name) + '" aria-label="' + esc(T('pc_pool')) + '"></td>'
            + '<td>' + sel('size', SIZES, p.size, ' data-p="' + i + '" data-fid="s' + i + '" aria-label="' + esc(T('pc_psize')) + '"') + '</td>'
            + '<td>' + numIn('ratio', p.ratio, 0, 100, 1, ' data-p="' + i + '" data-fid="r' + i + '" aria-label="' + esc(T('pc_share')) + '"') + '</td>'
            + '<td><input type="checkbox" data-k="bulk" data-p="' + i + '" data-fid="b' + i + '"' + (p.bulk ? ' checked' : '') + ' aria-label="bulk"></td>'
            + '<td><input type="checkbox" data-k="auto" data-p="' + i + '" data-fid="a' + i + '"' + (p.auto ? ' checked' : '') + ' aria-label="autoscale"></td>'
            + '<td>' + numIn('pg', p.pg, 1, 65536, 1, ' data-p="' + i + '" data-fid="g' + i + '" aria-label="pg_num"') + '</td>'
            + '<td><button type="button" class="cr-x" data-act="rm" data-p="' + i + '" aria-label="' + esc(T('pc_rm')) + '">×</button></td></tr>';
        }).join('') + '</tbody></table></div><button type="button" class="sim-btn sm" data-act="add">+ ' + esc(T('pc_add')) + '</button>';
    },
    view: function (st) {
      var share = st.pools.reduce(function (a, p) { return a + p.ratio; }, 0) || 1;
      var pools = st.pools.map(function (p, i) { return { name: p.name || 'pool' + i, size: parseInt(p.size, 10), ratio: p.ratio / 100, bulk: p.bulk, autoscale: p.auto, pg_num: p.pg }; });
      var as = C.autoscale(st.osds, st.target, pools), used = 0, usedNow = 0;
      var rows = pools.map(function (p, i) {
        var a = as.pools[i], cl = C.pgcalc(st.target, st.osds, st.pools[i].ratio / share, p.size);
        used += a.pg * p.size; usedNow += p.pg_num * p.size;
        return '<tr><td dir="ltr">' + esc(p.name) + '</td><td>' + L(p.size) + '</td><td>' + L(Math.round(cl.raw)) + ' → <b>' + L(cl.pg) + '</b></td>'
          + '<td>' + L(a.ideal) + '</td><td><b>' + L(a.pg) + '</b> <small>' + esc(T('pc_pass_' + a.pass)) + '</small></td>'
          + '<td>' + (a.adjust ? '<span class="sim-pill hot">' + esc(T('pc_yes', { a: L(p.pg_num), b: L(a.pg) })) + '</span>' : '<span class="sim-pill">' + esc(T('pc_no')) + '</span>') + '</td></tr>';
      }).join('');
      var per = used / st.osds, perNow = usedNow / st.osds;
      return '<div class="sim-stats">' + stat(L(as.pg_target), T('pc_s_budget')) + stat(num(per, 1), T('pc_s_per'), per > st.maxpg ? 'warn' : '') + stat(num(perNow, 1), T('pc_s_now'), perNow > st.maxpg ? 'warn' : '') + '</div>'
        + '<div class="table-wrap"><table class="sim-t"><thead><tr><th>' + esc(T('pc_pool')) + '</th><th>size</th><th>' + esc(T('pc_classic')) + '</th><th>' + esc(T('pc_ideal')) + '</th><th>' + esc(T('pc_final')) + '</th><th>' + esc(T('pc_adjust')) + '</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        + '<div class="sim-formula" dir="ltr">pgcalc: pg = pow2( target × OSDs × share / size ), next power up if the nearest is &gt; 25% below<br>autoscaler: root budget = mon_target_pg_per_osd × OSDs = ' + st.target + ' × ' + st.osds + ' = ' + as.pg_target
        + '; pool = ⌊capacity_ratio × pg_left⌋ / size, rounded down or up to a power of two by a knapsack over the budget; min pg_num_min (32); changes only past the threshold (3×; 1× at 512/1024, 2× at 2048)</div>'
        + '<p class="sim-note">' + tx('pc_note') + '</p>' + (per > st.maxpg ? '<p class="sim-warn">' + tx('pc_warn', { n: L(st.maxpg) }) + '</p>' : '');
    },
    input: function (st, k, v, el) {
      var p = st.pools[+(el && el.getAttribute('data-p') || 0)];
      if (k === 'osds') { st.osds = clamp(parseInt(v, 10) || 1, 1, 5000); return 'out'; }
      if (k === 'target' || k === 'maxpg') { st[k] = +v; return 'out'; }
      if (k === 'name') { p.name = String(v).slice(0, 40); return 'out'; }
      if (k === 'size') { p.size = v; return 'out'; }
      if (k === 'ratio') { p.ratio = clamp(parseFloat(v) || 0, 0, 100); return 'out'; }
      if (k === 'pg') { p.pg = clamp(parseInt(v, 10) || 1, 1, 65536); return 'out'; }
      if (k === 'bulk' || k === 'auto') { p[k] = !!el.checked; return 'out'; }
      return null;
    },
    act: function (st, a, el) {
      if (a === 'add' && st.pools.length < 10) { st.pools.push({ name: 'pool' + (st.pools.length + 1), size: '3', ratio: 5, bulk: false, auto: true, pg: 32 }); return 'all'; }
      if (a === 'rm' && st.pools.length > 1) { st.pools.splice(+el.getAttribute('data-p'), 1); return 'all'; }
      return null;
    }
  };

  S.DEFS.ecprofile = {
    icon: 'M4 6h4v12H4zM10 6h4v12h-4zM16 6h4v12h-4zM4 12h16',
    defaults: function () { return { hosts: 8, per: 6, tb: 16, plugin: 'isa', k: 4, m: 2, l: 3, c: 2, d: 5, fd: 'host', rep: 3 }; },
    refs: [['src/mon/OSDMonitor.cc :: prepare_pool_size', 'r_ec_minsize'], ['src/common/options/global.yaml.in :: osd_pool_default_erasure_code_profile, mon_osd_nearfull_ratio', 'r_ec_def'],
           ['src/erasure-code/lrc/ErasureCodeLrc.cc :: parse_kml', 'r_ec_lrc'], ['src/erasure-code/clay/ErasureCodeClay.cc :: parse', 'r_ec_clay'],
           ['src/erasure-code/shec/ErasureCodeShec.cc :: parse', 'r_ec_shec'], ['src/osd/OSDMap.cc :: pool_raw_used_rate', 'r_as_raw']],
    controls: function (st) {
      var dmin = st.k + 1, dmax = st.k + st.m - 1;
      var ex = st.plugin === 'lrc' ? field('l', sel('l', [2, 3, 4, 6], st.l)) : st.plugin === 'shec' ? field('c', sel('c', [1, 2, 3, 4], st.c))
        : st.plugin === 'clay' && dmax >= dmin ? field('d', sel('d', range(dmin, dmax), clamp(st.d, dmin, dmax))) : '';
      return '<div class="sim-row">' + field(T('ec_hosts'), numIn('hosts', st.hosts, 1, 200)) + field(T('ec_per'), numIn('per', st.per, 1, 60)) + field(T('ec_tb'), numIn('tb', st.tb, 1, 60, 1)) + '</div>'
        + '<div class="sim-row">' + field('plugin', sel('plugin', ['isa', 'jerasure', 'lrc', 'shec', 'clay'].map(function (x) { return [x, x]; }), st.plugin))
        + field('k', sel('k', [2, 3, 4, 5, 6, 8, 10, 12], st.k)) + field('m', sel('m', [1, 2, 3, 4], st.m)) + ex
        + field('crush-failure-domain', sel('fd', [['host', 'host'], ['osd', 'osd']], st.fd)) + field(T('ec_rep'), sel('rep', [2, 3, 4], st.rep)) + '</div>';
    },
    view: function (st) {
      var raw = st.hosts * st.per * st.tb, dd = clamp(st.d, st.k + 1, st.k + st.m - 1), err = [];
      var e = C.ecPool(st.k, st.m, st.plugin, { l: st.l, c: st.c, d: dd }), r = C.repPool(st.rep);
      if (st.plugin === 'lrc') {
        if ((st.k + st.m) % st.l) err.push(T('ec_e_lrc1'));
        else { var g = (st.k + st.m) / st.l; if (st.k % g) err.push(T('ec_e_lrc2')); if (st.m % g) err.push(T('ec_e_lrc3')); }
      }
      if (st.plugin === 'shec' && st.c > st.m) err.push(T('ec_e_shec'));
      if (st.plugin === 'clay' && st.m < 2) err.push(T('ec_e_clay'));
      var domains = st.fd === 'host' ? st.hosts : st.hosts * st.per;
      if (e.chunks > domains) err.push(T('ec_e_fd', { n: L(e.chunks), d: L(domains) }));
      else if (e.chunks === domains) err.push(T('ec_w_fd'));
      function card(title, x, cls) {
        var use = raw * x.eff;
        return '<div class="ec-card ' + cls + '"><h4 dir="auto">' + esc(title) + '</h4><div class="ec-bar" aria-hidden="true"><i style="width:' + (x.eff * 100).toFixed(1) + '%"></i></div><dl>'
          + '<dt>' + esc(T('ec_usable')) + '</dt><dd>' + num(use, 1) + ' TB <small>(' + pct(x.eff) + ')</small></dd>'
          + '<dt>' + esc(T('ec_practical')) + '</dt><dd>' + num(use * 0.85, 1) + ' TB</dd>'
          + '<dt>' + esc(T('ec_overhead')) + '</dt><dd>' + num(x.overhead, 2) + '×</dd>'
          + '<dt>' + esc(T('ec_tol')) + '</dt><dd>' + L(x.tolerate) + '</dd>'
          + '<dt>size / min_size</dt><dd>' + L(x.size) + ' / ' + L(x.minSize) + '</dd>'
          + '<dt>' + esc(T('ec_io')) + '</dt><dd>' + L(x.ioTolerate) + '</dd>'
          + '<dt>' + esc(T('ec_repair')) + '</dt><dd>' + num(x.repairRead, 2) + ' ' + esc(T('ec_chunks')) + '</dd></dl></div>';
      }
      var extra = st.plugin === 'lrc' ? ' l=' + st.l : st.plugin === 'shec' ? ' c=' + st.c : st.plugin === 'clay' ? ' d=' + dd : '';
      var prof = 'ceph osd erasure-code-profile set prof-' + st.k + '-' + st.m + ' plugin=' + st.plugin + ' k=' + st.k + ' m=' + st.m + extra + ' crush-failure-domain=' + st.fd
        + '\nceph osd pool create ecpool erasure prof-' + st.k + '-' + st.m + '\nceph osd pool set ecpool allow_ec_overwrites true   # RBD, CephFS';
      var rf = st.plugin === 'clay' ? 'repair read = d / (d − k + 1)' : st.plugin === 'lrc' ? 'repair read = l (local group)' : st.plugin === 'shec' ? 'repair read ≈ ⌈k × c / m⌉' : 'repair read = k';
      return '<div class="sim-stats">' + stat(num(raw, 0) + ' TB', T('ec_raw')) + stat(L(domains), T('ec_domains')) + '</div>'
        + (err.length ? '<ul class="sim-warn">' + err.map(function (x) { return '<li>' + rich(x) + '</li>'; }).join('') + '</ul>' : '')
        + '<div class="ec-cards">' + card('EC ' + st.plugin + ' k=' + st.k + ' m=' + st.m, e, 'ec') + card(T('ec_repl', { n: L(st.rep) }), r, 'rep') + '</div>'
        + '<div class="sim-formula" dir="ltr">usable = raw × k / (k + m' + (st.plugin === 'lrc' ? ' + (k + m) / l' : '') + ') · EC min_size = k + min(1, m − 1) = ' + e.minSize
        + ' · replicated min_size = size − ⌊size / 2⌋ = ' + r.minSize + ' · ' + rf + '</div>'
        + '<pre class="sim-cmd" dir="ltr"><code>' + esc(prof) + '</code></pre><p class="sim-note">' + tx('ec_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'plugin') {
        st.plugin = v;
        if (v === 'lrc') { st.k = 4; st.m = 2; st.l = 3; }
        if (v === 'shec') { st.k = 4; st.m = 3; st.c = 2; }
        if (v === 'clay') { st.m = Math.max(2, st.m); st.d = st.k + st.m - 1; }
        return 'all';
      }
      if (k === 'k' || k === 'm') { st[k] = +v; st.d = st.k + st.m - 1; return 'all'; }
      if (k === 'hosts' || k === 'per' || k === 'tb') { st[k] = clamp(parseInt(v, 10) || 1, 1, 200); return 'out'; }
      if (k === 'l' || k === 'c' || k === 'd' || k === 'rep') { st[k] = +v; return 'out'; }
      if (k === 'fd') { st.fd = v; return 'out'; }
      return null;
    }
  };
})(typeof self !== 'undefined' ? self : this);
