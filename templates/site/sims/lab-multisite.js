/* RGW multisite: realm, zonegroups, zones, the period and the sync direction (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * From Ceph: what 'radosgw-admin period update --commit' does to the period (src/rgw/rgw_zone.cc fork_period, commit_period:
 * same master zone → same period id, epoch + 1; a new master zone → a new period id, epoch FIRST_EPOCH and realm_epoch + 1;
 * the commit must run on the master zone), the sync options in src/common/options/rgw.yaml.in, and the flow types and
 * options radosgw-admin accepts for sync groups and zone sync-from lists (src/rgw/radosgw-admin/radosgw-admin.cc).
 * Who pulls from whom follows the RGW docs (data within a zonegroup, metadata from the master zone of the realm).
 * The replication-lag numbers are a queue model with assumptions spelled out in the lab text. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, clamp = h.clamp;
  var FIRST_EPOCH = 1, REALM = 'gold';
  var OPT = { poll: 20, spawn: 20, dshards: 128, mshards: 64 };   // rgw_data_sync_poll_interval, rgw_data_sync_spawn_window, rgw_data_log_num_shards, rgw_md_log_max_shards
  var ZG = [{ name: 'europe', pre: 'eu' }, { name: 'asia', pre: 'as' }];
  function url(z) { return 'http://rgw-' + z + '.example.com:80'; }

  // the configuration the controls describe (what would be committed)
  function snap(st) {
    var zgs = [];
    for (var g = 0; g < st.zg; g++) {
      var n = g ? st.zb : st.za, zones = [];
      for (var i = 1; i <= n; i++) zones.push(ZG[g].pre + '-' + i);
      zgs.push({ name: ZG[g].name, zones: zones, master: zones[Math.min(st.mz[g], n - 1)] });
    }
    var mg = Math.min(st.mzg, st.zg - 1);
    return { zgs: zgs, mzg: mg, master: zgs[mg].master, sync: st.sync, flow: st.flow };
  }
  function same(a, b) { return JSON.stringify(a) === JSON.stringify(b); }
  // radosgw-admin period update --commit, as rgw_zone.cc fork_period + commit_period do it
  function commit(period, live, staged, onZone) {
    if (onZone !== staged.master) return { err: 'must_run_on_master', period: period };
    if (staged.master !== live.master) return { period: { id: period.id + 1, epoch: FIRST_EPOCH, re: period.re + 1 }, fresh: true };
    return { period: { id: period.id, epoch: period.epoch + 1, re: period.re }, fresh: false };
  }
  // who pulls from whom: data within a zonegroup, metadata from the realm's master zone
  function edges(c) {
    var data = [], meta = [];
    c.zgs.forEach(function (g) {
      g.zones.forEach(function (dst) {
        g.zones.forEach(function (src) {
          if (src === dst) return;
          var one = c.sync === 'directional' || (c.sync === 'policy' && c.flow === 'directional');
          if (!one || src === g.master) data.push([src, dst]);
        });
      });
    });
    c.zgs.forEach(function (g) { g.zones.forEach(function (z) { if (z !== c.master) meta.push([c.master, z]); }); });
    return { data: data, meta: meta };
  }
  function zgOf(c, z) { return c.zgs.filter(function (g) { return g.zones.indexOf(z) >= 0; })[0]; }
  function syncCmds(c) {
    var out = [];
    if (c.sync === 'directional') c.zgs.forEach(function (g) {
      if (g.zones.length < 2) return;
      g.zones.forEach(function (z) {
        out.push('radosgw-admin zone modify --rgw-zone=' + z + ' --sync-from-all=false' + (z === g.master ? '' : ' --sync-from=' + g.master));
      });
    });
    if (c.sync === 'policy') c.zgs.forEach(function (g) {
      if (g.zones.length < 2) return;
      var zg = ' --rgw-zonegroup=' + g.name;
      out.push('radosgw-admin sync group create' + zg + ' --group-id=group1 --status=allowed');
      if (c.flow === 'symmetrical') out.push('radosgw-admin sync group flow create' + zg + ' --group-id=group1 --flow-id=mesh --flow-type=symmetrical --zones=' + g.zones.join(','));
      else g.zones.forEach(function (z) { if (z !== g.master) out.push('radosgw-admin sync group flow create' + zg + ' --group-id=group1 --flow-id=to-' + z + ' --flow-type=directional --source-zone=' + g.master + ' --dest-zone=' + z); });
      out.push("radosgw-admin sync group pipe create" + zg + " --group-id=group1 --pipe-id=all --source-zones='*' --source-bucket='*' --dest-zones='*' --dest-bucket='*'");
      out.push('radosgw-admin sync group modify' + zg + ' --group-id=group1 --status=enabled');
    });
    return out;
  }
  function undoSync(c) {
    var out = [];
    if (c.sync === 'directional') c.zgs.forEach(function (g) { if (g.zones.length > 1) g.zones.forEach(function (z) { out.push('radosgw-admin zone modify --rgw-zone=' + z + ' --sync-from-all=true'); }); });
    if (c.sync === 'policy') c.zgs.forEach(function (g) { if (g.zones.length > 1) out.push('radosgw-admin sync group remove --rgw-zonegroup=' + g.name + ' --group-id=group1'); });
    return out;
  }
  var KEYS = ' --access-key=<AK> --secret=<SK>';
  function pullCmds(c) {
    return ['radosgw-admin realm pull --url=' + url(c.master) + KEYS, 'radosgw-admin realm default --rgw-realm=' + REALM,
            'radosgw-admin period pull --url=' + url(c.master) + KEYS];
  }
  function addZone(c, g, z) {
    return 'radosgw-admin zone create --rgw-zonegroup=' + g.name + ' --rgw-zone=' + z + ' --endpoints=' + url(z) + KEYS + (z === g.master ? ' --master' : '');
  }
  // the whole setup for a configuration, cluster by cluster (chapter 5, §5.4)
  function setup(c) {
    var blocks = [], M = c.master, mg = c.zgs[c.mzg], commitL = 'radosgw-admin period update --commit';
    blocks.push({ zone: M, cmds: ['radosgw-admin realm create --rgw-realm=' + REALM + ' --default',
      'radosgw-admin zonegroup create --rgw-zonegroup=' + mg.name + ' --endpoints=' + url(M) + ' --rgw-realm=' + REALM + ' --master --default',
      'radosgw-admin zone create --rgw-zonegroup=' + mg.name + ' --rgw-zone=' + M + ' --endpoints=' + url(M) + ' --master --default',
      'radosgw-admin user create --uid=sync-user --display-name="Multisite sync" --system',
      'radosgw-admin zone modify --rgw-zone=' + M + KEYS, commitL] });
    c.zgs.forEach(function (g, gi) {
      if (gi !== c.mzg) blocks.push({ zone: g.master, cmds: pullCmds(c).concat(['radosgw-admin zonegroup create --rgw-zonegroup=' + g.name + ' --endpoints=' + url(g.master) + ' --rgw-realm=' + REALM,
        addZone(c, g, g.master), commitL]) });
      g.zones.forEach(function (z) { if (z !== g.master) blocks.push({ zone: z, cmds: pullCmds(c).concat([addZone(c, g, z), commitL]) }); });
    });
    var sc = syncCmds(c);
    if (sc.length) blocks.push({ zone: M, cmds: sc.concat([commitL]) });
    c.zgs.forEach(function (g) { g.zones.forEach(function (z) {
      blocks.push({ zone: z, cmds: ['ceph orch apply rgw ' + REALM + '-' + z + ' --realm=' + REALM + ' --zone=' + z + ' --placement="label:rgw count-per-host:1" --port=80'], orch: true });
    }); });
    return blocks;
  }
  // what to run to go from the committed configuration to the staged one
  function changes(live, c) {
    var out = [], all = function (x) { return [].concat.apply([], x.zgs.map(function (g) { return g.zones; })); };
    var was = all(live), now = all(c);
    c.zgs.forEach(function (g, gi) {
      if (!live.zgs[gi]) out.push({ k: 'zg', zone: g.master, cmds: pullCmds(live).concat(['radosgw-admin zonegroup create --rgw-zonegroup=' + g.name + ' --endpoints=' + url(g.master) + ' --rgw-realm=' + REALM]) });
      g.zones.forEach(function (z) { if (was.indexOf(z) < 0) out.push({ k: 'add', zone: z, cmds: (live.zgs[gi] || z !== g.master ? pullCmds(live) : []).concat([addZone(c, g, z)]) }); });
    });
    was.forEach(function (z) {
      if (now.indexOf(z) >= 0) return;
      var g = zgOf(live, z);
      out.push({ k: 'rm', zone: z, cmds: ['radosgw-admin zonegroup remove --rgw-zonegroup=' + g.name + ' --rgw-zone=' + z, 'radosgw-admin zone delete --rgw-zone=' + z] });
    });
    live.zgs.forEach(function (g, gi) { if (!c.zgs[gi]) out.push({ k: 'rmzg', zone: c.master, cmds: ['radosgw-admin zonegroup delete --rgw-zonegroup=' + g.name] }); });
    if (live.mzg !== c.mzg) out.push({ k: 'mzg', zone: c.master, cmds: ['radosgw-admin zonegroup modify --rgw-zonegroup=' + c.zgs[c.mzg].name + ' --master --default'] });
    c.zgs.forEach(function (g, gi) {
      var lg = live.zgs[gi];
      if (lg && lg.master !== g.master && was.indexOf(g.master) >= 0) out.push({ k: 'master', zone: g.master, cmds: ['radosgw-admin zone modify --rgw-zone=' + g.master + ' --master --default'] });
    });
    var zonesMoved = !same(live.zgs.map(function (g) { return g.zones; }), c.zgs.map(function (g) { return g.zones; })) || !same(live.zgs.map(function (g) { return g.master; }), c.zgs.map(function (g) { return g.master; }));
    if (live.sync !== c.sync || live.flow !== c.flow || (zonesMoved && c.sync !== 'mesh')) {
      var u = undoSync(live), s = syncCmds(c);
      if (u.length || s.length) out.push({ k: 'sync', zone: c.master, cmds: u.concat(s) });
    }
    return out;
  }
  // replication lag between a source and a destination zone: a queue fed at lam objects/s, served at mu
  function lag(st) {
    var size = st.size, bwObj = st.bw / size, conc = OPT.spawn * st.rgws, rttS = st.rtt / 1000;
    var mu = Math.min(bwObj, conc / (2 * rttS + size / st.bw * conc));   // in-flight fetches, each one round trip + its share of the link
    var lam = st.lam, xfer = 2 * rttS + size / st.bw;
    var steady = OPT.poll / 2 + xfer, worst = OPT.poll + xfer;
    var backlog = lam * st.out * 60, catchup = mu > lam ? backlog / (mu - lam) : Infinity;
    return { mu: mu, lam: lam, util: lam / mu, steady: steady, worst: worst, backlog: backlog, catchup: catchup, risk: backlog * size / 1000, conc: conc };
  }

  S.X = S.X || {};
  S.X.multisite = {
    snap: snap, commit: commit, edges: edges, setup: setup, changes: changes, syncCmds: syncCmds, lag: lag, OPT: OPT,
    test: function (t) {
      var g = t.G.multisite, base = S.DEFS.multisite.defaults();
      function cl(o) { return JSON.parse(JSON.stringify(o)); }
      if (g) {
        t.eq(g.first_epoch, FIRST_EPOCH, 'FIRST_EPOCH in rgw_zone.cc');
        t.eq(g.commit_checks[0], 'must_run_on_master', 'commit_period first refuses a zone that is not the master');
        t.ok(g.commit_checks.indexOf('master_changed') < g.commit_checks.indexOf('epoch'), 'a new master is handled before the epoch check');
        t.ok(g.master_change.new_id && g.master_change.epoch_first && g.fork_realm_epoch_plus_one, 'new master: new period id, FIRST_EPOCH, realm_epoch + 1');
        t.ok(g.same_master.keeps_id && g.same_master.epoch_plus_one && g.same_master.keeps_realm_epoch, 'same master: same period, epoch + 1');
        t.eq([g.options.rgw_data_sync_poll_interval, g.options.rgw_data_sync_spawn_window, g.options.rgw_data_log_num_shards, g.options.rgw_md_log_max_shards],
             [OPT.poll, OPT.spawn, OPT.dshards, OPT.mshards], 'sync options from rgw.yaml.in');
        t.eq(g.options.rgw_data_notify_interval_msec, 0, 'data change notifications are off by default, so peers poll');
      }
      var p0 = { id: 1, epoch: 2, re: 2 };
      for (var i = 0; i < 300; i++) {
        var st = cl(base);
        st.zg = 1 + (i % 2); st.za = 1 + (i % 3); st.zb = 1 + ((i >> 1) % 3); st.mzg = (i >> 2) % 2; st.mz = [(i >> 3) % 3, (i >> 4) % 3];
        st.sync = ['mesh', 'directional', 'policy'][i % 3]; st.flow = ['symmetrical', 'directional'][(i >> 1) % 2];
        var c = snap(st), e = edges(c), zones = [].concat.apply([], c.zgs.map(function (x) { return x.zones; }));
        t.eq(e.meta.length, zones.length - 1, 'every zone but the realm master pulls metadata from it ' + i);
        t.ok(e.data.every(function (d) { return zgOf(c, d[0]) === zgOf(c, d[1]); }), 'data never syncs across zonegroups ' + i);
        var one = c.sync === 'directional' || (c.sync === 'policy' && c.flow === 'directional');
        c.zgs.forEach(function (zg) {
          var n = zg.zones.length, cnt = e.data.filter(function (d) { return zg.zones.indexOf(d[1]) >= 0; }).length;
          t.eq(cnt, one ? n - 1 : n * (n - 1), 'data pulls in ' + zg.name + ' ' + i);
          if (one) t.ok(!e.data.some(function (d) { return d[1] === zg.master; }), 'one-way: the master pulls nothing ' + i);
        });
        var b = setup(c), lines = [].concat.apply([], b.map(function (x) { return x.cmds; }));
        t.eq(lines.filter(function (l) { return / zonegroup create .*--master/.test(l); }).length, 1, 'exactly one master zonegroup ' + i);
        zones.forEach(function (z) { t.ok(lines.some(function (l) { return l.indexOf(' zone create ') >= 0 && l.indexOf('--rgw-zone=' + z + ' ') >= 0; }), 'zone ' + z + ' is created ' + i); });
        t.ok(b.every(function (x) { return x.cmds[x.cmds.length - 1] === 'radosgw-admin period update --commit' || x.orch; }), 'every radosgw-admin block ends with a commit ' + i);
        if (g) lines.forEach(function (l) {
          (l.match(/--[a-z-]+/g) || []).forEach(function (o) { if (!/^--rgw-/.test(o) && /sync|group|flow|pipe|zones|bucket|status|source|dest/.test(o)) t.ok(g.admin_opts.indexOf(o) >= 0, 'radosgw-admin knows ' + o + ' ' + i); });
          var ft = /--flow-type=(\w+)/.exec(l); if (ft) t.ok(g.flow_types[ft[1]] && g.flow_types[ft[1]].indexOf(ft[1]) >= 0, 'flow type ' + ft[1] + ' ' + i);
        });
        // the commit, against the rules in commit_period
        var st2 = cl(st); st2.mz = [(st.mz[0] + 1) % 3, st.mz[1]];
        var c2 = snap(st2), r = commit(p0, c, c2, c2.master);
        if (c2.master === c.master) t.eq(r.period, { id: 1, epoch: 3, re: 2 }, 'same master, epoch + 1 ' + i);
        else t.eq(r.period, { id: 2, epoch: FIRST_EPOCH, re: 3 }, 'new master, new period ' + i);
        t.eq(commit(p0, c, c2, c2.master + 'x').err, 'must_run_on_master', 'commit only on the master zone ' + i);
        t.eq(changes(c, c).length, 0, 'nothing staged, nothing to run ' + i);
      }
      // the queue: backlog after an outage drains at mu - lam
      for (i = 0; i < 100; i++) {
        var q = cl(base); q.lam = 5 + i * 3; q.size = [0.064, 1, 4, 16][i % 4]; q.bw = [50, 125, 1250][i % 3]; q.rtt = [1, 20, 80][(i >> 1) % 3]; q.out = 5 + i % 60; q.rgws = 1 + i % 3;
        var m = lag(q);
        t.ok(m.mu <= q.bw / q.size + 1e-9, 'never faster than the link ' + i);
        t.near(m.backlog, q.lam * q.out * 60, 'backlog = writes during the outage ' + i, 1e-6);
        if (m.mu > m.lam) t.near(m.catchup * (m.mu - m.lam), m.backlog, 'catch-up time ' + i, 1e-6 * m.backlog);
        else t.ok(m.catchup === Infinity, 'never catches up when writes outrun sync ' + i);
        t.ok(m.worst >= m.steady && m.steady >= OPT.poll / 2, 'lag is at least half a poll interval ' + i);
      }
    }
  };

  S.DEFS.multisite = {
    icon: 'M3 6h7v5H3zM14 6h7v5h-7zM8.5 18h7v4h-7zM10 8.5h4M6.5 11v3.5h11V11M12 14.5V18',
    defaults: function () {
      var st = { zg: 1, za: 2, zb: 2, mzg: 0, mz: [0, 0], sync: 'mesh', flow: 'directional', on: 'eu-1',
                 lam: 50, size: 1, bw: 125, rtt: 30, out: 30, rgws: 1, period: { id: 1, epoch: 2, re: 2 }, msg: '' };
      st.live = snap(st); return st;
    },
    refs: [['src/rgw/rgw_zone.cc :: fork_period, commit_period (FIRST_EPOCH, the master-zone check, epoch + 1)', 'multisite_r1'],
           ['src/rgw/radosgw-admin/radosgw-admin.cc :: zone modify --sync-from-all / --sync-from, sync group flow / pipe', 'multisite_r2'],
           ['src/common/options/rgw.yaml.in :: rgw_data_sync_poll_interval, rgw_data_sync_spawn_window, rgw_data_log_num_shards, rgw_data_notify_interval_msec', 'multisite_r3'],
           ['doc/radosgw/multisite.rst, doc/radosgw/multisite-sync-policy.rst', 'multisite_r4']],
    controls: function (st) {
      var c = snap(st), zones = [].concat.apply([], c.zgs.map(function (g) { return g.zones; }));
      var zsel = function (g) { var n = g ? st.zb : st.za, o = []; for (var i = 0; i < n; i++) o.push([i, ZG[g].pre + '-' + (i + 1)]); return field(T('multisite_mz', { g: ZG[g].name }), sel('mz' + g, o, Math.min(st.mz[g], n - 1))); };
      return '<div class="sim-row">' + field(T('multisite_zg'), sel('zg', [[1, '1'], [2, '2']], st.zg))
        + field(T('multisite_zones', { g: 'europe' }), sel('za', [1, 2, 3], st.za)) + (st.zg > 1 ? field(T('multisite_zones', { g: 'asia' }), sel('zb', [1, 2, 3], st.zb)) : '')
        + (st.zg > 1 ? field(T('multisite_mzg'), sel('mzg', [[0, 'europe'], [1, 'asia']], st.mzg)) : '') + '</div>'
        + '<div class="sim-row">' + zsel(0) + (st.zg > 1 ? zsel(1) : '')
        + field(T('multisite_sync'), sel('sync', [['mesh', T('multisite_mesh')], ['directional', T('multisite_dir')], ['policy', T('multisite_policy')]], st.sync))
        + (st.sync === 'policy' ? field('--flow-type', sel('flow', [['symmetrical', 'symmetrical'], ['directional', 'directional']], st.flow)) : '') + '</div>'
        + '<div class="sim-row">' + field(T('multisite_on'), sel('on', zones.map(function (z) { return [z, z]; }), zones.indexOf(st.on) >= 0 ? st.on : c.master))
        + '<div class="lx-btns"><button type="button" class="sim-btn pri" data-act="commit">period update --commit</button></div></div>'
        + '<div class="sim-row">' + field(T('multisite_lam'), numIn('lam', st.lam, 0.1, 100000, 10)) + field(T('multisite_size'), numIn('size', st.size, 0.001, 5000, 0.5))
        + field(T('multisite_bw'), numIn('bw', st.bw, 1, 100000, 25)) + field('RTT (ms)', numIn('rtt', st.rtt, 0.1, 1000, 5))
        + field(T('multisite_out'), numIn('out', st.out, 0, 1440, 5)) + field(T('multisite_rgws'), numIn('rgws', st.rgws, 1, 16, 1)) + '</div>';
    },
    view: function (st) {
      var c = snap(st), live = st.live, e = edges(live), ch = changes(live, c), staged = ch.length > 0;
      var liveZ = [].concat.apply([], live.zgs.map(function (g) { return g.zones; }));
      // topology: zonegroup boxes, zones inside, data and metadata arrows of the committed period
      var W = 720, H = 250, ng = c.zgs.length, gw = (W - 30 - (ng - 1) * 20) / ng, pos = {};
      var svg = '<defs><marker id="ms-ad" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--sim-c0)"/></marker>'
        + '<marker id="ms-am" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L10 5L0 10z" fill="var(--sim-c1)"/></marker></defs>'
        + '<rect x="4" y="4" width="' + (W - 8) + '" height="' + (H - 8) + '" rx="12" fill="none" stroke="var(--line)"/><text x="14" y="22">realm ' + REALM + '</text>';
      c.zgs.forEach(function (g, gi) {
        var x0 = 15 + gi * (gw + 20), n = g.zones.length;
        svg += '<rect class="lx-bg" x="' + x0 + '" y="34" width="' + gw + '" height="' + (H - 48) + '" rx="10"' + (gi === c.mzg ? ' stroke="var(--sim-a)"' : ' stroke="var(--line)"') + '/>'
          + '<text x="' + (x0 + 10) + '" y="52">zonegroup ' + g.name + (gi === c.mzg ? ' ★' : '') + '</text>';
        g.zones.forEach(function (z, i) { pos[z] = { x: x0 + gw * (i + 0.5) / n, y: n === 3 && i === 1 ? 190 : 125 }; });
      });
      var arrow = function (a, b, cls, bend) {
        var p = pos[a], q = pos[b]; if (!p || !q) return '';
        var dx = q.x - p.x, dy = q.y - p.y, d = Math.sqrt(dx * dx + dy * dy) || 1, ux = dx / d, uy = dy / d, r = 34;
        var sx = p.x + ux * r, sy = p.y + uy * r * 0.7, ex = q.x - ux * r, ey = q.y - uy * r * 0.7, mx = (sx + ex) / 2 - uy * bend, my = (sy + ey) / 2 + ux * bend;
        return '<path d="M' + sx + ' ' + sy + 'Q' + mx + ' ' + my + ' ' + ex + ' ' + ey + '" fill="none" stroke="' + (cls === 'm' ? 'var(--sim-c1)' : 'var(--sim-c0)') + '" stroke-width="2"'
          + (cls === 'm' ? ' stroke-dasharray="5 4"' : '') + ' marker-end="url(#ms-a' + (cls === 'm' ? 'm' : 'd') + ')"/>';
      };
      e.data.forEach(function (d) { svg += arrow(d[0], d[1], 'd', 22); });
      e.meta.forEach(function (d) { if (zgOf(live, d[0]) !== zgOf(live, d[1])) svg += arrow(d[0], d[1], 'm', -40); });
      Object.keys(pos).forEach(function (z) {
        var p = pos[z], isM = z === c.master, gm = zgOf(c, z).master === z, isNew = liveZ.indexOf(z) < 0;
        svg += '<g><rect x="' + (p.x - 40) + '" y="' + (p.y - 20) + '" width="80" height="40" rx="8" fill="var(--bg)" stroke="' + (isM ? 'var(--sim-ok)' : gm ? 'var(--sim-c4)' : 'var(--line)') + '" stroke-width="' + (gm ? 2.5 : 1.5) + '"'
          + (isNew ? ' stroke-dasharray="4 3"' : '') + '/><text x="' + p.x + '" y="' + (p.y - 2) + '" text-anchor="middle">' + z + '</text><text x="' + p.x + '" y="' + (p.y + 13) + '" text-anchor="middle" font-size="10">'
          + (isNew ? 'staged' : isM ? 'realm master' : gm ? 'zg master' : 'zone') + '</text></g>';
      });
      // replication lag on the first pair that syncs data in the committed period
      var pair = e.data.filter(function (d) { return d[0] === live.master; })[0] || e.data[0], m = lag(st);
      var lagHtml = '';
      if (pair) {
        var Wc = 720, Hc = 150, T0 = st.out * 60, Tend = isFinite(m.catchup) ? T0 + m.catchup : T0 * 3, span = Math.max(Tend * 1.15, 60);
        var ymax = Math.max(m.backlog, 1) * (isFinite(m.catchup) ? 1.1 : 3), X = function (s) { return 40 + s / span * (Wc - 60); }, Y = function (v) { return Hc - 22 - Math.min(v, ymax) / ymax * (Hc - 40); };
        var pts = [[0, 0], [T0, m.backlog]].concat(isFinite(m.catchup) ? [[Tend, 0], [span, 0]] : [[span, m.backlog + (m.lam - m.mu) * (span - T0)]]);
        lagHtml = '<h4>' + esc(T('multisite_lagh', { a: pair[0], b: pair[1] })) + '</h4>'
          + '<div class="sim-stats">' + stat(num(m.steady, 1) + ' s', T('multisite_s_lag')) + stat(num(m.mu, 0) + ' / ' + num(m.lam, 0), T('multisite_s_rate'), m.util >= 1 ? 'warn' : m.util > 0.8 ? 'hot' : '')
          + stat(num(m.backlog, 0), T('multisite_s_back')) + stat(isFinite(m.catchup) ? num(m.catchup / 60, 1) + ' min' : '∞', T('multisite_s_catch'), isFinite(m.catchup) ? '' : 'warn') + '</div>'
          + '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + Wc + ' ' + Hc + '" role="img" aria-label="' + esc(T('multisite_fig2')) + '" dir="ltr" style="direction:ltr">'
          + '<line class="lx-gl" x1="38" x2="' + (Wc - 10) + '" y1="' + Y(0) + '" y2="' + Y(0) + '"/>'
          + (st.out > 0 ? '<rect x="' + X(0) + '" y="12" width="' + (X(T0) - X(0)) + '" height="' + (Y(0) - 12) + '" fill="var(--sim-bad)" opacity=".08"/><text x="' + (X(T0 / 2)) + '" y="26" text-anchor="middle">link down</text>' : '')
          + '<polyline fill="none" stroke="var(--sim-c0)" stroke-width="2.5" points="' + pts.map(function (p) { return X(p[0]) + ',' + Y(p[1]); }).join(' ') + '"/>'
          + '<text x="' + X(0) + '" y="' + (Hc - 6) + '">0</text><text x="' + (Wc - 12) + '" y="' + (Hc - 6) + '" text-anchor="end">' + Math.round(span / 60) + ' min</text>'
          + '<text x="36" y="' + (Y(m.backlog) + 4) + '" text-anchor="end">' + Math.round(m.backlog) + '</text></svg>'
          + '<figcaption>' + esc(T('multisite_fig2c')) + '</figcaption></figure>'
          + (m.util >= 1 ? '<p class="sim-warn">' + tx('multisite_slow') + '</p>' : '')
          + (m.backlog > 0 ? '<p class="sim-note">' + tx('multisite_risk', { n: num(m.backlog, 0), gb: num(m.risk, 1) }) + '</p>' : '');
      } else lagHtml = '<p class="sim-note">' + tx('multisite_nosync') + '</p>';
      var pre = function (lines) { return '<pre class="sim-cmd" dir="ltr"><code>' + esc(lines.join('\n')) + '</code></pre>'; };
      var chHtml = staged ? '<h4>' + esc(T('multisite_staged')) + '</h4>' + ch.map(function (x) { return '<p class="sim-note">' + tx('multisite_on_zone', { z: x.zone }) + '</p>' + pre(x.cmds); }).join('')
          + pre(['radosgw-admin period update --commit   # on ' + c.master]) : '';
      var blocks = setup(c), setupHtml = '<details class="ms-setup"><summary>' + esc(T('multisite_setup')) + '</summary>'
          + blocks.filter(function (b) { return !b.orch; }).map(function (b) { return '<p class="sim-note">' + tx('multisite_on_zone', { z: b.zone }) + '</p>' + pre(b.cmds); }).join('')
          + pre(blocks.filter(function (b) { return b.orch; }).map(function (b) { return b.cmds[0]; })) + '</details>';
      return '<div class="sim-stats">' + stat('p' + st.period.id + ' · ' + L(st.period.epoch), T('multisite_s_period')) + stat(L(st.period.re), 'realm_epoch')
          + stat(live.master, T('multisite_s_master')) + stat(staged ? T('multisite_yes') : T('multisite_no'), T('multisite_s_staged'), staged ? 'hot' : '') + '</div>'
        + (st.msg ? '<p class="' + (/^err/.test(st.msg) ? 'sim-warn' : 'sim-note') + '">' + tx('multisite_' + st.msg, { z: st.on, m: c.master, p: 'p' + st.period.id, e: L(st.period.epoch) }) + '</p>' : '')
        + (staged ? '<p class="sim-warn">' + tx('multisite_notyet', { e: L(st.period.epoch) }) + '</p>' : '')
        + '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('multisite_fig')) + '" dir="ltr" style="direction:ltr">' + svg + '</svg>'
        + '<figcaption>' + esc(T('multisite_figc')) + '</figcaption></figure>'
        + chHtml + lagHtml
        + '<div class="sim-formula" dir="ltr">lag ≈ poll/2 + 2·RTT + size/bw (poll = rgw_data_sync_poll_interval = ' + OPT.poll + ' s) · μ = min(bw / size, in-flight / (2·RTT + in-flight · size / bw)) · in-flight = rgw_data_sync_spawn_window × RGWs = ' + m.conc
        + '<br>backlog = writes/s × outage · catch-up = backlog / (μ − writes/s)</div>'
        + pre(['radosgw-admin sync status', 'radosgw-admin period get', 'radosgw-admin data sync status --source-zone=' + (pair ? pair[0] : c.master), 'radosgw-admin sync error list'])
        + setupHtml + '<p class="sim-note">' + tx('multisite_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'sync' || k === 'flow' || k === 'on') { st[k] = v; st.msg = ''; return 'all'; }
      if (k === 'mz0' || k === 'mz1') { st.mz[+k.slice(2)] = +v; st.msg = ''; return 'all'; }
      var n = parseFloat(v); if (!isFinite(n)) return null;
      if (k === 'zg' || k === 'za' || k === 'zb' || k === 'mzg') { st[k] = n; st.msg = ''; return 'all'; }
      var lim = { lam: [0.1, 100000], size: [0.001, 5000], bw: [1, 100000], rtt: [0.1, 1000], out: [0, 1440], rgws: [1, 16] };
      if (!lim[k]) return null;
      st[k] = clamp(k === 'rgws' ? Math.round(n) : n, lim[k][0], lim[k][1]);
      return 'out';
    },
    act: function (st, a) {
      if (a !== 'commit') return null;
      var c = snap(st), zones = [].concat.apply([], c.zgs.map(function (g) { return g.zones; }));
      if (zones.indexOf(st.on) < 0) st.on = c.master;
      var r = commit(st.period, st.live, c, st.on);
      if (r.err) { st.msg = 'err_master'; return 'out'; }
      st.period = r.period; st.live = c; st.msg = r.fresh ? 'fresh' : 'epoch';
      return 'out';
    },
    say: function (st) { return T('multisite_s_period') + ': p' + st.period.id + ' ' + st.period.epoch; },
    fallbackState: function (st) { st.za = 3; st.sync = 'directional'; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
