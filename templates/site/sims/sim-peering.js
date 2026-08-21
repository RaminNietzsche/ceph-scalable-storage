/* Peering and recovery stepper (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * The states and their nesting are the boost::statechart states in src/osd/PeeringState.h;
 * each step names the PeeringState / PGLog / PrimaryLogPG function that does the work. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, T = h.T, L = h.L, esc = h.esc, sel = h.sel, field = h.field, code = h.code;
  // parent of each state (PeeringState.h: struct X : boost::statechart::state<X, Parent, ...>)
  var PARENT = { Reset: null, Started: null, Primary: 'Started', Peering: 'Primary', GetInfo: 'Peering', GetLog: 'Peering', GetMissing: 'Peering', WaitUpThru: 'Peering',
    WaitActingChange: 'Primary', Active: 'Primary', Activating: 'Active', Clean: 'Active', Recovered: 'Active', WaitLocalRecoveryReserved: 'Active',
    WaitRemoteRecoveryReserved: 'Active', Recovering: 'Active', WaitLocalBackfillReserved: 'Active', WaitRemoteBackfillReserved: 'Active', Backfilling: 'Active',
    ReplicaActive: 'Started', Stray: 'Started', ToDelete: 'Started' };
  var TREE = [['Reset', 0], ['Started', 0], ['Primary', 1], ['Peering', 2], ['GetInfo', 3], ['GetLog', 3], ['GetMissing', 3], ['WaitUpThru', 3], ['WaitActingChange', 2], ['Active', 2],
    ['Activating', 3], ['WaitLocalRecoveryReserved', 3], ['WaitRemoteRecoveryReserved', 3], ['Recovering', 3], ['WaitLocalBackfillReserved', 3], ['WaitRemoteBackfillReserved', 3],
    ['Backfilling', 3], ['Recovered', 3], ['Clean', 3], ['ReplicaActive', 1], ['Stray', 1], ['ToDelete', 1]];
  function path(s) { var p = []; while (s) { p.push(s); s = PARENT[s]; } return p; }
  var B = [[5, 1, 'A'], [5, 2, 'B'], [5, 3, 'C']];           // the common history: epoch, version, object
  function lg(extra, flags) { return B.map(function (e) { return e.concat(['']); }).concat((extra || []).map(function (e, i) { return e.concat([(flags || '')[i] || '']); })); }
  // each step: state, pg state string, up, acting, primary, logs {osd: entries}, missing {osd: objects}, ref
  var SCEN = {
    downup: [
      { s: 'Clean', pg: 'active+clean', e: 18, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::Clean' },
      { s: 'Reset', pg: 'peering', e: 20, up: [0, 1], act: [0, 1], dead: [2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::should_restart_peering, start_peering_interval' },
      { s: 'GetInfo', pg: 'peering', e: 20, up: [0, 1], act: [0, 1], dead: [2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::build_prior, GetInfo::get_infos' },
      { s: 'GetLog', pg: 'peering', e: 20, up: [0, 1], act: [0, 1], dead: [2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::find_best_info, choose_acting' },
      { s: 'Activating', pg: 'activating+undersized+degraded', e: 20, up: [0, 1], act: [0, 1], dead: [2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::activate' },
      { s: 'Active', pg: 'active+undersized+degraded', e: 20, up: [0, 1], act: [0, 1], dead: [2], logs: { 0: lg([[20, 4, 'D'], [20, 5, 'A']], 'nn'), 1: lg([[20, 4, 'D'], [20, 5, 'A']], 'nn'), 2: lg() }, ref: 'PrimaryLogPG::execute_ctx, PGLog::add' },
      { s: 'GetInfo', pg: 'peering', e: 25, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[20, 4, 'D'], [20, 5, 'A']]), 1: lg([[20, 4, 'D'], [20, 5, 'A']]), 2: lg() }, ref: 'PeeringState::start_peering_interval, proc_replica_notify' },
      { s: 'GetMissing', pg: 'peering', e: 25, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[20, 4, 'D'], [20, 5, 'A']]), 1: lg([[20, 4, 'D'], [20, 5, 'A']]), 2: lg() }, miss: { 2: ['D', 'A'] }, ref: 'PeeringState::proc_replica_log, PGLog::proc_replica_log' },
      { s: 'Recovering', pg: 'active+recovering+degraded', e: 25, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[20, 4, 'D'], [20, 5, 'A']]), 1: lg([[20, 4, 'D'], [20, 5, 'A']]), 2: lg([[20, 4, 'D'], [20, 5, 'A']], 'nn') }, miss: { 2: ['A'] }, ref: 'PrimaryLogPG::start_recovery_ops, recover_replicas' },
      { s: 'Clean', pg: 'active+clean', e: 25, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[20, 4, 'D'], [20, 5, 'A']]), 1: lg([[20, 4, 'D'], [20, 5, 'A']]), 2: lg([[20, 4, 'D'], [20, 5, 'A']]) }, ref: 'PeeringState::Recovered, Clean' }
    ],
    backfill: [
      { s: 'Clean', pg: 'active+clean', e: 30, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg() }, ref: 'PeeringState::Clean' },
      { s: 'WaitActingChange', pg: 'peering', e: 31, up: [0, 1, 3], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg(), 3: [] }, ref: 'PeeringState::choose_acting, calc_replicated_acting, queue_want_pg_temp' },
      { s: 'Activating', pg: 'activating+remapped', e: 32, up: [0, 1, 3], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg(), 3: [] }, ref: 'PeeringState::activate (backfill_targets)' },
      { s: 'WaitLocalBackfillReserved', pg: 'active+remapped+backfill_wait', e: 32, up: [0, 1, 3], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg(), 3: [] }, ref: 'WaitLocalBackfillReserved (osd_max_backfills)' },
      { s: 'WaitRemoteBackfillReserved', pg: 'active+remapped+backfill_wait', e: 32, up: [0, 1, 3], act: [0, 1, 2], logs: { 0: lg(), 1: lg(), 2: lg(), 3: [] }, ref: 'WaitRemoteBackfillReserved, MBackfillReserve' },
      { s: 'Backfilling', pg: 'active+remapped+backfilling', e: 32, up: [0, 1, 3], act: [0, 1, 2], bf: 'B', logs: { 0: lg(), 1: lg(), 2: lg(), 3: [] }, ref: 'PrimaryLogPG::recover_backfill, PrimaryBackfillInterval' },
      { s: 'Recovered', pg: 'active+remapped', e: 32, up: [0, 1, 3], act: [0, 1, 2], bf: 'MAX', logs: { 0: lg(), 1: lg(), 2: lg(), 3: lg() }, ref: 'PeeringState::Recovered, needs_backfill' },
      { s: 'Clean', pg: 'active+clean', e: 33, up: [0, 1, 3], act: [0, 1, 3], stray: [2], logs: { 0: lg(), 1: lg(), 2: lg(), 3: lg() }, ref: 'PeeringState::Clean, Stray, ToDelete' }
    ],
    divergent: [
      { s: 'Active', pg: 'active+clean', e: 40, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[40, 4, 'D']], 'n'), 1: lg(), 2: lg() }, ref: 'PrimaryLogPG::issue_repop' },
      { s: 'GetLog', pg: 'peering', e: 41, up: [1, 2], act: [1, 2], dead: [0], logs: { 0: lg([[40, 4, 'D']]), 1: lg(), 2: lg() }, ref: 'PeeringState::find_best_info' },
      { s: 'Active', pg: 'active+undersized+degraded', e: 41, up: [1, 2], act: [1, 2], dead: [0], logs: { 0: lg([[40, 4, 'D']]), 1: lg([[41, 4, 'E'], [41, 5, 'B']], 'nn'), 2: lg([[41, 4, 'E'], [41, 5, 'B']], 'nn') }, ref: 'PrimaryLogPG::execute_ctx' },
      { s: 'GetInfo', pg: 'peering', e: 45, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[40, 4, 'D']]), 1: lg([[41, 4, 'E'], [41, 5, 'B']]), 2: lg([[41, 4, 'E'], [41, 5, 'B']]) }, ref: 'PeeringState::start_peering_interval, GetInfo' },
      { s: 'GetLog', pg: 'peering', e: 45, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[40, 4, 'D']], 'd'), 1: lg([[41, 4, 'E'], [41, 5, 'B']]), 2: lg([[41, 4, 'E'], [41, 5, 'B']]) }, ref: 'PeeringState::find_best_info, proc_master_log' },
      { s: 'GetMissing', pg: 'peering', e: 45, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[41, 4, 'E'], [41, 5, 'B']], 'mm'), 1: lg([[41, 4, 'E'], [41, 5, 'B']]), 2: lg([[41, 4, 'E'], [41, 5, 'B']]) }, miss: { 0: ['E', 'B'] }, gone: { 0: ['D'] }, ref: 'PGLog::merge_log, rewind_divergent_log, _merge_divergent_entries' },
      { s: 'Recovering', pg: 'active+recovering+degraded', e: 45, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[41, 4, 'E'], [41, 5, 'B']]), 1: lg([[41, 4, 'E'], [41, 5, 'B']]), 2: lg([[41, 4, 'E'], [41, 5, 'B']]) }, miss: { 0: ['B'] }, ref: 'PrimaryLogPG::recover_primary' },
      { s: 'Clean', pg: 'active+clean', e: 45, up: [0, 1, 2], act: [0, 1, 2], logs: { 0: lg([[41, 4, 'E'], [41, 5, 'B']]), 1: lg([[41, 4, 'E'], [41, 5, 'B']]), 2: lg([[41, 4, 'E'], [41, 5, 'B']]) }, ref: 'PeeringState::Recovered, Clean' }
    ]
  };
  function setHTML(lbl, xs, dead) {
    return '<div class="ps-set"><span>' + esc(lbl) + '</span><span dir="ltr">[' + xs.map(function (o, i) { return '<i class="' + (i === 0 ? 'pri' : '') + '">' + o + '</i>'; }).join(',') + ']</span></div>';
  }
  function treeHTML(cur) {
    var on = path(cur);
    return '<ol class="ps-tree" dir="ltr" aria-label="' + esc(T('ps_tree')) + '">' + TREE.map(function (n) {
      var a = on.indexOf(n[0]) >= 0, me = n[0] === cur;
      return '<li class="d' + n[1] + (a ? ' on' : '') + (me ? ' cur' : '') + '"' + (me ? ' aria-current="step"' : '') + '>' + n[0] + '</li>';
    }).join('') + '</ol>';
  }
  S.DEFS.peering = {
    icon: 'M6 6a3 3 0 1 0 0 .1M18 6a3 3 0 1 0 0 .1M12 18a3 3 0 1 0 0 .1M8.5 7.5l2.5 8M15.5 7.5l-2.5 8M9 6h6',
    steps: function (st) { return SCEN[st.sc].length; },
    defaults: function () { return { sc: 'downup', i: 0 }; },
    refs: [['src/osd/PeeringState.h :: struct Started, Primary, Peering, GetInfo, GetLog, GetMissing, Active, …', 'r_ps_states'],
           ['src/osd/PeeringState.cc :: start_peering_interval, should_restart_peering, build_prior', 'r_ps_interval'],
           ['src/osd/PeeringState.cc :: find_best_info, choose_acting, calc_replicated_acting', 'r_ps_choose'],
           ['src/osd/PeeringState.cc :: proc_master_log, proc_replica_log, activate', 'r_ps_log'],
           ['src/osd/PGLog.cc :: merge_log, rewind_divergent_log, _merge_divergent_entries, proc_replica_log', 'r_ps_pglog'],
           ['src/osd/PrimaryLogPG.cc :: start_recovery_ops, recover_primary, recover_replicas, recover_backfill', 'r_ps_rec']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('ps_sc'), sel('sc', [['downup', T('ps_downup')], ['backfill', T('ps_backfill')], ['divergent', T('ps_divergent')]], st.sc)) + '</div>';
    },
    view: function (st) {
      var sc = SCEN[st.sc], cur = sc[st.i], osds = Object.keys(cur.logs).map(Number);
      var cards = osds.map(function (o) {
        var dead = (cur.dead || []).indexOf(o) >= 0, stray = (cur.stray || []).indexOf(o) >= 0, inA = cur.act.indexOf(o) >= 0, inU = cur.up.indexOf(o) >= 0;
        var role = dead ? 'down' : o === cur.act[0] ? 'primary' : inA ? 'replica' : stray ? 'stray' : inU ? 'backfill' : 'stray';
        var miss = (cur.miss || {})[o] || [], gone = (cur.gone || {})[o] || [];
        var lastOf = {};
        cur.logs[o].forEach(function (e, j) { lastOf[e[2]] = j; });
        var ents = cur.logs[o].map(function (e, j) {
          var f = e[3], m = f === 'm' || (miss.indexOf(e[2]) >= 0 && f !== 'n' && lastOf[e[2]] === j);
          return '<li class="' + (f === 'n' ? 'new' : f === 'd' ? 'div' : m ? 'miss' : '') + '"><b>' + e[0] + "'" + e[1] + '</b> ' + e[2]
            + (f === 'n' ? ' <small>' + esc(T('ps_l_new')) + '</small>' : f === 'd' ? ' <small>' + esc(T('ps_l_div')) + '</small>' : m ? ' <small>' + esc(T('ps_l_miss')) + '</small>' : '') + '</li>';
        }).join('');
        var last = cur.logs[o].length ? cur.logs[o][cur.logs[o].length - 1] : null;
        return '<div class="ps-osd r-' + role + '"><h4 dir="ltr">osd.' + o + ' <span class="sim-pill">' + esc(T('ps_r_' + role)) + '</span></h4>'
          + '<div class="ps-lu" dir="ltr">last_update ' + (last ? last[0] + "'" + last[1] : "0'0") + (cur.bf && role === 'backfill' ? ' · last_backfill ' + cur.bf : '') + '</div>'
          + (cur.logs[o].length ? '<ol class="ps-log" dir="ltr">' + ents + '</ol>' : '<p class="ps-empty">' + esc(T('ps_empty')) + '</p>')
          + (miss.length ? '<div class="ps-miss" dir="ltr">missing: {' + miss.join(', ') + '}</div>' : '') + (gone.length ? '<div class="ps-gone">' + esc(T('ps_gone')) + ' <bdi dir="ltr">' + gone.join(', ') + '</bdi></div>' : '') + '</div>';
      }).join('');
      var hist = sc.slice(0, st.i + 1).map(function (x, j) { return '<li' + (j === st.i ? ' class="cur"' : '') + '><span dir="ltr">e' + x.e + '</span> ' + tx('ps_' + st.sc + '_' + j + '_t') + '</li>'; }).join('');
      return '<div class="ps-top"><div class="ps-state"><div class="ps-pg" dir="ltr">pg 1.7 · ' + esc(cur.pg) + ' · epoch ' + cur.e + '</div>'
        + setHTML('up', cur.up) + setHTML('acting', cur.act) + '<h4 class="ps-h">' + L(st.i + 1) + '/' + L(sc.length) + ' · ' + tx('ps_' + st.sc + '_' + st.i + '_t') + '</h4>'
        + '<p class="ps-x">' + tx('ps_' + st.sc + '_' + st.i) + '</p><p class="ps-ref">' + esc(T('follows')) + ' ' + code(cur.ref) + '</p></div>' + treeHTML(cur.s) + '</div>'
        + '<div class="ps-osds">' + cards + '</div><details class="ps-hist" open><summary>' + esc(T('ps_hist')) + '</summary><ol>' + hist + '</ol></details>';
    },
    say: function (st) { return T('ps_' + st.sc + '_' + st.i + '_t'); },
    input: function (st, k, v) { if (k === 'sc') { st.sc = v; st.i = 0; return 'all'; } return null; },
    fallbackState: function (st) { st.sc = 'divergent'; st.i = 5; return st; }
  };
  S.PEERING = { SCEN: SCEN, PARENT: PARENT };
})(typeof self !== 'undefined' ? self : this);
