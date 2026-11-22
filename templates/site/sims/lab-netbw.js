/* Network traffic of replication and erasure coding (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * The client talks only to the PG primary on the public network; the primary fans the write out to the other
 * replicas or shards on the cluster network (src/osd/ReplicatedBackend.cc issue_op, src/osd/ECBackend.cc / ECCommon);
 * an EC read gathers k chunks; recovery rebuilds a replica by copying it, an EC shard by reading k chunks. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, clamp = h.clamp;
  function pool(id) { var m = /^ec(\d+)\+(\d+)$/.exec(id); return m ? { ec: true, k: +m[1], m: +m[2] } : { ec: false, n: +id.slice(3) }; }
  // traffic per byte of client data
  function factors(p) {
    if (!p.ec) return { wPub: 1, wClu: p.n - 1, wDisk: p.n, rPub: 1, rClu: 0, rec: 1, raw: p.n };
    return { wPub: 1, wClu: (p.k + p.m - 1) / p.k, wDisk: (p.k + p.m) / p.k, rPub: 1, rClu: (p.k - 1) / p.k, rec: p.k, raw: (p.k + p.m) / p.k };
  }
  function model(st) {
    var p = pool(st.pool), f = factors(p), w = st.write, r = st.read;   // MB/s from clients
    var pub = w * f.wPub + r * f.rPub, clu = w * f.wClu + r * f.rClu;
    var nicPub = st.hosts * st.nic * 1000 / 8 * 0.9, nicClu = st.split ? nicPub : 0;     // ~90% of line rate usable
    var pubLoad = st.split ? pub : pub + clu, cluLoad = st.split ? clu : 0;
    var lostTB = st.osdTB * st.fill, recMB = lostTB * 1e6 * f.rec;                          // read across the cluster network to rebuild one OSD
    var recBw = clamp((st.split ? nicClu - clu : nicPub - pub - clu) * st.budget, 1, Infinity);
    // the disks bound it too: rebuild reads recMB and writes the lost data, spread over all hosts' spare disk throughput
    var diskBw = clamp(st.hosts * st.disk * st.budget, 1, Infinity), netH = recMB / recBw / 3600, diskH = (recMB + lostTB * 1e6) / diskBw / 3600;
    return { p: p, f: f, pub: pub, clu: clu, nicPub: nicPub, nicClu: nicClu, uPub: pubLoad / nicPub, uClu: st.split ? cluLoad / nicClu : 0, recMB: recMB, recH: Math.max(netH, diskH), netH: netH, diskH: diskH, bound: diskH > netH ? 'disk' : 'net', recBw: recBw };
  }

  S.X = S.X || {};
  S.X.netbw = {
    factors: factors, pool: pool, model: model,
    test: function (t) {
      var r3 = factors(pool('rep3')), e42 = factors(pool('ec4+2')), e83 = factors(pool('ec8+3'));
      t.eq([r3.wClu, r3.wDisk, r3.rec], [2, 3, 1], 'replica 3: two cluster copies, three disk writes, one copy to rebuild');
      t.eq([e42.wClu, e42.wDisk, e42.rClu, e42.rec], [1.25, 1.5, 0.75, 4], 'EC 4+2: 5/4 out, 6/4 on disk, 3/4 gathered, 4 chunks per rebuilt chunk');
      t.eq(e83.wDisk, 11 / 8, 'EC 8+3 raw factor');
      ['rep2', 'rep3', 'ec2+1', 'ec4+2', 'ec6+3', 'ec8+3'].forEach(function (id) {
        var p = pool(id), f = factors(p), local = p.ec ? 1 / p.k : 1;   // what the primary keeps on its own disk
        t.ok(Math.abs(local + f.wClu - f.wDisk) < 1e-12, id + ': disk writes = the primary own part + what it sent on the cluster network');
        t.ok(f.raw === f.wDisk, id + ': raw space factor = disk write factor');
      });
      for (var i = 0; i < 100; i++) {
        var st = { pool: ['rep3', 'ec4+2', 'ec8+3'][i % 3], write: 50 * i, read: 30 * i, hosts: 3 + i % 10, nic: [10, 25, 100][i % 3], split: !!(i % 2), osdTB: 4 + i % 16, fill: 0.7, budget: 0.5, disk: 200 + 100 * (i % 9) };
        var m = model(st);
        t.ok(m.recH > 0 && isFinite(m.recH) && m.recH >= m.netH && m.recH >= m.diskH, 'recovery time is the slower of network and disks ' + i);
        t.ok(Math.abs(m.recMB - st.osdTB * st.fill * 1e6 * m.f.rec) < 1e-6, 'recovery volume ' + i);
      }
    }
  };

  S.DEFS.netbw = {
    icon: 'M4 6h16M4 12h16M4 18h16M8 3v6M16 9v6M12 15v6',
    defaults: function () { return { pool: 'rep3', write: 1000, read: 2000, hosts: 6, nic: 25, split: true, osdTB: 16, fill: 0.7, budget: 0.5, disk: 1000 }; },
    refs: [['src/osd/ReplicatedBackend.cc :: ReplicatedBackend::issue_op', 'netbw_r1'],
           ['src/osd/ECBackend.cc, src/osd/ECCommon.cc :: write fan-out, read gather, recovery reads', 'netbw_r2'],
           ['doc/rados/configuration/network-config-ref.rst :: public and cluster networks', 'netbw_r3']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('netbw_pool'), sel('pool', [['rep2', T('netbw_rep', { n: L(2) })], ['rep3', T('netbw_rep', { n: L(3) })], ['ec2+1', 'EC 2+1'], ['ec4+2', 'EC 4+2'], ['ec8+3', 'EC 8+3']], st.pool))
        + field(T('netbw_write'), numIn('write', st.write, 0, 1000000, 50)) + field(T('netbw_read'), numIn('read', st.read, 0, 1000000, 50)) + '</div>'
        + '<div class="sim-row">' + field(T('netbw_hosts'), numIn('hosts', st.hosts, 3, 1000, 1)) + field(T('netbw_nic'), sel('nic', [[10, '10 Gb/s'], [25, '25 Gb/s'], [100, '100 Gb/s']], st.nic))
        + '<label class="sim-f sim-chk"><span>' + esc(T('netbw_split')) + '</span><input type="checkbox" data-k="split"' + (st.split ? ' checked' : '') + '></label></div>'
        + '<div class="sim-row">' + field(T('netbw_osd'), sel('osdTB', [[4, '4 TB'], [8, '8 TB'], [16, '16 TB'], [22, '22 TB']], st.osdTB)) + field(T('netbw_fill'), sel('fill', [[0.5, '50%'], [0.7, '70%'], [0.85, '85%']], st.fill))
        + field(T('netbw_disk'), numIn('disk', st.disk, 50, 100000, 50)) + field(T('netbw_budget'), sel('budget', [[0.2, '20%'], [0.5, '50%'], [0.8, '80%']], st.budget)) + '</div>';
    },
    view: function (st) {
      var m = model(st), f = m.f;
      function bar(label, load, cap) {
        var u = cap ? load / cap : 0;
        return '<div class="bsp-row"><span>' + esc(label) + '</span><div class="bsp-bar" dir="ltr"><i class="bsp-data" style="width:' + Math.min(100, u * 100) + '%;background:' + (u > 1 ? 'var(--sim-bad)' : u > 0.7 ? 'var(--sim-hot)' : 'var(--sim-c0)') + '"></i></div><span class="lx-mono" dir="ltr">' + num(load) + ' / ' + num(cap) + ' MB/s</span></div>';
      }
      var bars = st.split ? bar(T('netbw_pub'), m.pub, m.nicPub) + bar(T('netbw_clu'), m.clu, m.nicClu) : bar(T('netbw_one'), m.pub + m.clu, m.nicPub);
      var rows = [['netbw_f_wpub', f.wPub], ['netbw_f_wclu', f.wClu], ['netbw_f_disk', f.wDisk], ['netbw_f_rclu', f.rClu], ['netbw_f_rec', f.rec]].map(function (r) {
        return '<tr><th>' + esc(T(r[0])) + '</th><td><bdi dir="ltr">' + L(Math.round(r[1] * 100) / 100) + '×</bdi></td></tr>';
      }).join('');
      var worst = Math.max(m.uPub, m.uClu);
      return '<div class="sim-stats">' + stat(pct(m.uPub), T(st.split ? 'netbw_s_pub' : 'netbw_s_one'), m.uPub > 1 ? 'warn' : m.uPub > 0.7 ? 'hot' : '')
        + (st.split ? stat(pct(m.uClu), T('netbw_s_clu'), m.uClu > 1 ? 'warn' : m.uClu > 0.7 ? 'hot' : '') : '')
        + stat(num(m.recMB / 1e6, 1) + ' TB', T('netbw_s_recv'), 'hot') + stat(worst >= 1 ? '∞' : num(m.recH, 1) + ' h', T(m.bound === 'disk' ? 'netbw_s_rect_d' : 'netbw_s_rect'), worst >= 1 ? 'warn' : '') + '</div>'
        + '<div class="bsp-list">' + bars + '</div>'
        + '<table class="sim-t"><thead><tr><th>' + esc(T('netbw_per')) + '</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>'
        + (worst >= 1 ? '<p class="sim-warn">' + tx('netbw_over') + '</p>' : '')
        + '<div class="sim-formula" dir="ltr">' + (m.p.ec ? 'write: client → primary 1×, primary → ' + (m.p.k + m.p.m - 1) + ' shards × 1/' + m.p.k + ' · read: gather ' + (m.p.k - 1) + '/' + m.p.k + ' · rebuild one shard: read k = ' + m.p.k + ' chunks' : 'write: client → primary 1×, primary → ' + (m.p.n - 1) + ' replicas × 1 · read: primary only · rebuild: copy 1×') + ' · usable ≈ 90% of line rate</div>'
        + '<p class="sim-note">' + tx('netbw_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'split') { st.split = !!v; return 'out'; }
      if (k === 'pool') { st.pool = v; return 'out'; }
      var n = parseFloat(v); if (!isFinite(n)) return null;
      st[k] = k === 'hosts' ? clamp(Math.round(n), 3, 1000) : Math.max(0, n); return 'out';
    },
    say: function (st) { var m = model(st); return T('netbw_s_rect') + ': ' + num(m.recH, 1); }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
