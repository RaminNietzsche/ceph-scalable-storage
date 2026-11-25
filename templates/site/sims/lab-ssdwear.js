/* SSD wear and endurance of BlueStore OSDs (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * A model. The parts that come from Ceph: replication and EC fan-out (each replica or shard is one write on its OSD;
 * classic EC writes every shard, chunks padded to the stripe unit, src/osd/ECUtil.h stripe_info_t), allocation padding
 * to bluestore_min_alloc_size_ssd and the deferred-write threshold bluestore_prefer_deferred_size_ssd
 * (src/os/bluestore/BlueStore.cc _do_write_small / _do_write_big), and RocksDB level sizes from bluestore_rocksdb_options
 * (max_bytes_for_level_base, max_bytes_for_level_multiplier; src/common/options/global.yaml.in). The metadata bytes per
 * write, the compaction cost per level and the drive's own write amplification are assumptions the reader sets. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, clamp = h.clamp;
  var KI = 1024, BLOCK = 4096, SU = 4096;
  // Ceph's defaults (checked against the Ceph tree in the test)
  var CEPH = { min_alloc_ssd: 4096, prefer_deferred_ssd: 0, level_base: 1 << 30, level_mult: 8, stripe_unit_classic: SU };
  function up(x, a) { return Math.ceil(x / a) * a; }
  function pool(id) { var m = /^ec(\d+)\+(\d+)$/.exec(id); return m ? { ec: true, k: +m[1], m: +m[2], n: +m[1] + +m[2] } : { ec: false, n: +id.slice(3) }; }
  // the RocksDB levels a DB of `db` bytes needs with leveled compaction, and the bytes written per metadata byte
  function levels(db, base, mult) {
    var n = 0, cum = 0, t = base, tg = [];
    while (cum < db && n < 8) { n++; tg.push(t); cum += t; t *= mult; }
    return { n: Math.max(1, n), targets: tg, cum: cum };
  }
  function rocksWA(dbBytes, compaction, mult) {
    // WAL (1) + memtable flush to L0 (1); with compaction: L0 → L1 (1) and about (multiplier + 1) / 2 per deeper level
    if (!compaction) return 2;
    var lv = levels(dbBytes, CEPH.level_base, mult || CEPH.level_mult);
    return 3 + (lv.n - 1) * ((mult || CEPH.level_mult) + 1) / 2;
  }
  // bytes the OSDs write per client write of `io` bytes, split by cause
  function perWrite(st) {
    var p = pool(st.pool), op = p.ec ? up(Math.ceil(st.io / p.k), SU) : st.io;   // what one OSD receives
    var deferred = up(op, BLOCK) < st.defer;                                     // small writes into the WAL first (prefer_deferred_size)
    var data = deferred ? up(op, BLOCK) : up(op, st.alloc);
    var wa = rocksWA(st.db * Math.pow(2, 30), st.compact, st.mult);
    var r = { client: st.io, p: p, op: op, deferred: deferred, n: p.n, wa: wa };
    r.fan = p.n * op;                          // replicas or shards, as sent
    r.pad = p.n * (data - op);                 // rounding to min_alloc_size (or the block for deferred)
    r.wal = deferred ? p.n * up(op, BLOCK) : 0; // the deferred data in the RocksDB WAL
    r.meta = p.n * st.meta * KI * 2;           // metadata: WAL + flush
    r.comp = p.n * st.meta * KI * (wa - 2);    // metadata: compaction
    r.dataDev = r.fan + r.pad;                 // to the data device
    r.dbDev = r.wal + r.meta + r.comp;         // to block.db (or the same device)
    return r;
  }
  function model(st) {
    var w = perWrite(st), ops = st.mbps * 1e6 / st.io;                          // client writes per second
    var extra = 1 + st.recov / 100, dev = st.waf;
    var perOsdData = ops * w.dataDev * extra * dev / st.osds, perOsdDb = ops * w.dbDev * extra * dev / st.osds;
    var onData = st.dbsep ? perOsdData : perOsdData + perOsdDb;                  // bytes/s on one data SSD
    var tbw = st.spec === 'tbw' ? st.tbw : st.dwpd * st.cap * 365 * st.years;  // TB written over the warranty
    var day = onData * 86400 / 1e12;                                            // TB per day, average OSD
    var hot = day * (1 + st.imb / 100);
    var total = (w.dataDev + w.dbDev) * extra * dev / w.client;
    return { w: w, ops: ops, day: day, hot: hot, tbw: tbw, life: tbw / (day * 365), lifeHot: tbw / (hot * 365), dwpdUsed: day / st.cap,
             db: perOsdDb * 86400 / 1e12, total: total, extra: extra };
  }

  S.X = S.X || {};
  S.X.ssdwear = {
    model: model, perWrite: perWrite, levels: levels, rocksWA: rocksWA, CEPH: CEPH,
    test: function (t) {
      var g = t.G.ssdwear;
      if (g) {
        t.eq([g.options.bluestore_min_alloc_size_ssd, g.options.bluestore_prefer_deferred_size_ssd, g.options.bdev_block_size], [CEPH.min_alloc_ssd, CEPH.prefer_deferred_ssd, BLOCK], 'BlueStore SSD defaults from global.yaml.in');
        t.eq([g.rocksdb.max_bytes_for_level_base, g.rocksdb.max_bytes_for_level_multiplier], [CEPH.level_base, CEPH.level_mult], 'RocksDB level options from bluestore_rocksdb_options');
        t.eq(g.options.osd_pool_erasure_code_stripe_unit, 0, 'osd_pool_erasure_code_stripe_unit 0: 4 KiB for classic EC');
        t.ok(/4KB/.test(g.stripe_unit_desc), 'classic EC picks a 4 KiB stripe unit');
        ['bytes_written_wal', 'bytes_written_sst', 'write_big_bytes', 'write_small_bytes', 'issued_deferred_write_bytes'].forEach(function (c) { t.ok(g.counters.indexOf(c) >= 0, 'perf counter ' + c + ' exists in BlueFS.cc / BlueStore.cc'); });
      }
      // chapter 12: cumulative level sizes 1, 9, 73, 585 GiB
      t.eq(levels(585 * Math.pow(2, 30), CEPH.level_base, 8).targets.reduce(function (a, x) { a.push((a.length ? a[a.length - 1] : 0) + x / Math.pow(2, 30)); return a; }, []), [1, 9, 73, 585], 'chapter 12 level sizes');
      var base = S.DEFS.ssdwear.defaults();
      for (var i = 0; i < 200; i++) {
        var st = {}; for (var k in base) st[k] = base[k];
        st.pool = ['rep2', 'rep3', 'ec4+2', 'ec8+3'][i % 4]; st.io = [4096, 16384, 65536, 1 << 20, 4 << 20][i % 5]; st.alloc = [4096, 16384, 65536][i % 3];
        st.defer = [0, 16384, 65536][(i >> 2) % 3]; st.compact = !!(i % 2); st.dbsep = !!((i >> 1) % 2); st.mbps = 50 + 10 * i; st.meta = 0.5 + (i % 7); st.db = [10, 30, 80, 300][i % 4];
        var m = model(st), w = m.w, raw = w.p.ec ? w.p.n / w.p.k : w.p.n;
        t.ok(w.fan >= raw * st.io - 1e-6, 'nothing is written less than the pool factor ' + i);
        t.ok(w.pad >= 0 && (w.deferred || (w.fan + w.pad) % st.alloc === 0), 'data is padded to min_alloc_size ' + i);
        t.ok(m.total >= raw - 1e-9, 'write amplification is at least the raw factor ' + i);
        var st2 = {}; for (k in st) st2[k] = st[k]; st2.mbps = st.mbps * 2;
        t.near(model(st2).life * 2, m.life, 'twice the writes, half the life ' + i, 1e-6 * m.life);
        st2.mbps = st.mbps; st2.compact = true; st2.dbsep = false;
        var st3 = {}; for (k in st2) st3[k] = st2[k]; st3.compact = false;
        t.ok(model(st2).life <= model(st3).life + 1e-9, 'compaction only shortens the life ' + i);
      }
      // a 4 MiB write on replica 3 costs about three times its size; a 4 KiB write much more
      var big = {}, small = {}; for (k in base) { big[k] = base[k]; small[k] = base[k]; }
      big.io = 4 << 20; big.pool = 'rep3'; small.io = 4096; small.pool = 'rep3';
      t.ok(model(big).total < 3.3 && model(small).total > 6, '4 MiB vs 4 KiB write amplification');
    }
  };

  S.DEFS.ssdwear = {
    icon: 'M4 7h16v10H4zM8 7V4h8v3M8 12h3M13 12h3M7 20l2-3M17 20l-2-3',
    defaults: function () { return { pool: 'rep3', io: 16384, mbps: 400, osds: 24, cap: 3.84, spec: 'dwpd', dwpd: 1, tbw: 7000, years: 5, alloc: 4096, defer: 0, meta: 1, compact: true, mult: 8, db: 30, dbsep: false, waf: 1, recov: 5, imb: 10 }; },
    refs: [['src/os/bluestore/BlueStore.cc :: _do_write_small, _do_write_big (padding to min_alloc_size, deferred below prefer_deferred_size)', 'ssdwear_r1'],
           ['src/common/options/global.yaml.in :: bluestore_min_alloc_size_ssd (4 KiB), bluestore_prefer_deferred_size_ssd (0), bluestore_rocksdb_options', 'ssdwear_r2'],
           ['src/osd/ECUtil.h :: stripe_info_t; src/common/options/mon.yaml.in :: osd_pool_erasure_code_stripe_unit', 'ssdwear_r3'],
           ['src/os/bluestore/BlueFS.cc :: bytes_written_wal, bytes_written_sst; BlueStore.cc :: write_big_bytes, write_small_bytes, issued_deferred_write_bytes', 'ssdwear_r4']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('ssdwear_pool'), sel('pool', [['rep2', T('ssdwear_rep', { n: L(2) })], ['rep3', T('ssdwear_rep', { n: L(3) })], ['ec4+2', 'EC 4+2'], ['ec8+3', 'EC 8+3']], st.pool))
        + field(T('ssdwear_io'), sel('io', [[4096, '4 KiB'], [16384, '16 KiB'], [65536, '64 KiB'], [1048576, '1 MiB'], [4194304, '4 MiB']], st.io))
        + field(T('ssdwear_mbps'), numIn('mbps', st.mbps, 1, 100000, 10)) + field(T('ssdwear_osds'), numIn('osds', st.osds, 3, 2000, 1)) + '</div>'
        + '<div class="sim-row">' + field(T('ssdwear_cap'), sel('cap', [[0.96, '0.96 TB'], [1.92, '1.92 TB'], [3.84, '3.84 TB'], [7.68, '7.68 TB'], [15.36, '15.36 TB']], st.cap))
        + field(T('ssdwear_spec'), sel('spec', [['dwpd', 'DWPD'], ['tbw', 'TBW']], st.spec))
        + (st.spec === 'dwpd' ? field('DWPD', sel('dwpd', [[0.3, '0.3'], [1, '1'], [3, '3'], [10, '10']], st.dwpd)) : field('TBW (TB)', numIn('tbw', st.tbw, 100, 1000000, 100)))
        + field(T('ssdwear_years'), numIn('years', st.years, 1, 10, 1)) + '</div>'
        + '<div class="sim-row">' + field('bluestore_min_alloc_size_ssd', sel('alloc', [[4096, '4 KiB'], [16384, '16 KiB'], [65536, '64 KiB']], st.alloc))
        + field('bluestore_prefer_deferred_size_ssd', sel('defer', [[0, '0'], [16384, '16 KiB'], [65536, '64 KiB']], st.defer))
        + field(T('ssdwear_meta'), numIn('meta', st.meta, 0, 64, 0.5)) + field(T('ssdwear_db'), numIn('db', st.db, 1, 2000, 5)) + '</div>'
        + '<div class="sim-row"><label class="sim-f sim-chk"><span>' + esc(T('ssdwear_compact')) + '</span><input type="checkbox" data-k="compact"' + (st.compact ? ' checked' : '') + '></label>'
        + field('max_bytes_for_level_multiplier', sel('mult', [[8, '8'], [10, '10']], st.mult))
        + '<label class="sim-f sim-chk"><span>' + esc(T('ssdwear_dbsep')) + '</span><input type="checkbox" data-k="dbsep"' + (st.dbsep ? ' checked' : '') + '></label>'
        + field(T('ssdwear_waf'), numIn('waf', st.waf, 1, 10, 0.1)) + field(T('ssdwear_recov'), numIn('recov', st.recov, 0, 100, 1)) + field(T('ssdwear_imb'), numIn('imb', st.imb, 0, 100, 1)) + '</div>';
    },
    view: function (st) {
      var m = model(st), w = m.w, c = w.client, short = m.lifeHot < st.years;
      var rows = [['ssdwear_b_fan', w.fan], ['ssdwear_b_pad', w.pad], ['ssdwear_b_wal', w.wal], ['ssdwear_b_meta', w.meta], ['ssdwear_b_comp', w.comp]];
      var extraB = (w.dataDev + w.dbDev) * (m.extra - 1), wafB = (w.dataDev + w.dbDev) * m.extra * (st.waf - 1);
      rows.push(['ssdwear_b_recov', extraB]); rows.push(['ssdwear_b_waf', wafB]);
      var tot = rows.reduce(function (a, r) { return a + r[1]; }, 0);
      var bars = rows.filter(function (r) { return r[1] > 0; }).map(function (r, i) {
        return '<div class="bsp-row"><span>' + esc(T(r[0])) + '</span><div class="bsp-bar" dir="ltr"><i class="bsp-data" style="width:' + Math.min(100, r[1] / tot * 100) + '%;background:var(--sim-c' + (i % 6) + ')"></i></div><span class="lx-mono" dir="ltr">' + L(Math.round(r[1] / c * 100) / 100) + '×</span></div>';
      }).join('');
      var n = Math.min(st.osds, 48), W = 720, H = 170, bw = (W - 50) / n, top = 10, bot = H - 22;
      var lifeOf = function (i) { var fct = n > 1 ? 1 + st.imb / 100 * (2 * i / (n - 1) - 1) : 1; return m.tbw / (m.day * fct * 365); };
      var ymax = Math.max(st.years * 1.6, lifeOf(0) * 1.05), y = function (v) { return bot - Math.min(v, ymax) / ymax * (bot - top); };
      var osdBars = '';
      for (var i = 0; i < n; i++) {
        var lf = lifeOf(i), x = 40 + i * bw;
        osdBars += '<g><title>osd.' + i + ': ' + (Math.round(lf * 10) / 10) + ' y</title><rect class="lx-b ' + (lf < st.years ? 'f-full' : lf < st.years * 1.3 ? 'f-near' : 'f-ok') + '" x="' + (x + 1) + '" y="' + y(lf) + '" width="' + Math.max(2, bw - 2) + '" height="' + (bot - y(lf)) + '" rx="2"/>'
          + (n <= 24 || i % 4 === 0 ? '<text x="' + (x + bw / 2) + '" y="' + (H - 8) + '" text-anchor="middle">' + i + '</text>' : '') + '</g>';
      }
      var warr = '<line class="lx-now" x1="38" x2="' + (W - 8) + '" y1="' + y(st.years) + '" y2="' + y(st.years) + '"/><text x="34" y="' + (y(st.years) + 4) + '" text-anchor="end">' + st.years + 'y</text>'
        + '<line class="lx-gl" x1="38" x2="' + (W - 8) + '" y1="' + bot + '" y2="' + bot + '"/>';
      var lifeTxt = function (v) { return isFinite(v) ? num(v, 1) : '∞'; };
      return '<div class="sim-stats">' + stat(L(Math.round(m.total * 100) / 100) + '×', T('ssdwear_s_wa'), m.total > 6 ? 'hot' : '')
        + stat(num(m.day * 1000, 0) + ' GB', T('ssdwear_s_day')) + stat(L(Math.round(m.dwpdUsed * 1000) / 1000), T('ssdwear_s_dwpd'), st.spec === 'dwpd' && m.dwpdUsed > st.dwpd ? 'warn' : '')
        + stat(lifeTxt(m.life) + ' / ' + lifeTxt(m.lifeHot), T('ssdwear_s_life'), short ? 'warn' : '') + '</div>'
        + '<h4>' + esc(T('ssdwear_per')) + '</h4><div class="bsp-list">' + bars + '</div>'
        + '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('ssdwear_fig')) + '" dir="ltr">' + warr + osdBars + '</svg><figcaption>' + esc(T('ssdwear_figcap', { n: L(n) })) + '</figcaption></figure>'
        + (st.dbsep ? '<p class="sim-note">' + tx('ssdwear_dbdev', { gb: num(m.db * 1000, 0) }) + '</p>' : '')
        + (w.deferred ? '<p class="sim-warn">' + tx('ssdwear_deferred') + '</p>' : '')
        + (short ? '<p class="sim-warn">' + tx('ssdwear_short', { y: num(m.lifeHot, 1), w: L(st.years) }) + '</p>' : '')
        + '<div class="sim-formula" dir="ltr">per OSD write = ' + (w.p.ec ? 'roundup(io / k, stripe_unit)' : 'io') + ' = ' + w.op + ' B → ' + (w.deferred ? 'deferred: WAL + in place' : 'roundup(·, min_alloc_size)') + ' · RocksDB WA ≈ ' + L(Math.round(w.wa * 10) / 10)
          + '<br>TBW = DWPD × capacity × 365 × years · life = TBW / (TB written per day × 365)</div>'
        + '<pre class="sim-cmd" dir="ltr"><code>ceph daemon osd.0 perf dump bluefs        # bytes_written_wal, bytes_written_sst\nceph daemon osd.0 perf dump bluestore     # write_big_bytes, write_small_bytes, issued_deferred_write_bytes\nsmartctl -a /dev/nvme0n1 | grep -i -e "percentage used" -e "data units written"</code></pre>'
        + '<p class="sim-note">' + tx('ssdwear_note') + '</p>';
    },
    input: function (st, k, v, el) {
      if (k === 'compact' || k === 'dbsep') { st[k] = !!(el ? el.checked : v); return 'out'; }
      if (k === 'pool' || k === 'spec') { st[k] = v; return k === 'spec' ? 'all' : 'out'; }
      var n = parseFloat(v); if (!isFinite(n)) return null;
      var lim = { mbps: [1, 100000], osds: [3, 2000], tbw: [100, 1000000], years: [1, 10], meta: [0, 64], db: [1, 2000], waf: [1, 10], recov: [0, 100], imb: [0, 100] };
      st[k] = lim[k] ? clamp(k === 'osds' ? Math.round(n) : n, lim[k][0], lim[k][1]) : n;
      return 'out';
    },
    say: function (st) { var m = model(st); return T('ssdwear_s_life') + ': ' + num(m.life, 1) + ' / ' + num(m.lifeHot, 1); }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
