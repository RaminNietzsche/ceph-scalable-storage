/* BlueStore space: min_alloc_size, EC padding and the compression acceptance test (lab, loaded on demand).
 * CC BY-NC-SA 4.0, Ramin Najarbashi.
 * Allocation rounds every stored extent up to min_alloc_size (fixed when the OSD is created,
 * bluestore_min_alloc_size_{hdd,ssd}); the compression test is the first check in BlueStore::_do_alloc_write. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, bytes = h.bytes, clamp = h.clamp;
  var K = 1024;
  function up(x, a) { return Math.ceil(x / a) * a; }
  // bytes each shard (or replica) holds for one object of `size`
  function shards(size, pool) {
    if (pool.type === 'rep') { var r = []; for (var i = 0; i < pool.size; i++) r.push(size); return r; }
    var k = pool.k, m = pool.m, su = pool.su, out = [];
    if (!pool.fast) {           // classic EC: the last stripe is padded, every shard gets the same length
      var per = up(size, k * su) / k; for (var j = 0; j < k + m; j++) out.push(size ? per : 0); return out;
    }
    // FastEC (allow_ec_optimizations): no zero padding, a shard holds only the stripe units that land in it
    var full = Math.floor(size / (k * su)), rest = size - full * k * su, data = [];
    for (var d = 0; d < k; d++) { var extra = clamp(rest - d * su, 0, su); data.push(full * su + extra); }
    var par = Math.max.apply(null, data);
    return data.concat(new Array(m).fill(par));
  }
  function usage(size, pool, minAlloc) {
    var s = shards(size, pool), stored = s.reduce(function (a, b) { return a + b; }, 0), alloc = s.reduce(function (a, b) { return a + up(b, minAlloc); }, 0);
    return { shards: s, stored: stored, alloc: alloc };
  }
  // BlueStore::_do_alloc_write, first (header-less) estimate
  function accept(blob, compressed, minAlloc, crr) {
    var want = up(Math.floor(blob * crr), minAlloc), result = up(compressed, minAlloc);
    return { ok: result <= want && result < blob, want: want, result: result };
  }

  S.X = S.X || {};
  S.X.bluespace = {
    shards: shards, usage: usage, accept: accept,
    test: function (t) {
      var g = t.G.bluespace;
      if (g) {
        var d = S.DEFS.bluespace.defaults();
        t.eq([d.minAlloc, d.crr, d.blob], [g.options.bluestore_min_alloc_size_hdd, g.options.bluestore_compression_required_ratio, g.options.bluestore_compression_max_blob_size_hdd], 'defaults match global.yaml.in');
        t.eq(g.options.bluestore_min_alloc_size_ssd, 4096, 'ssd min_alloc 4K too');
        g.accept.forEach(function (c, i) { var r = accept(c[0], c[1], c[2], c[3]); t.eq([r.ok ? 1 : 0, r.want, r.result], [c[4], c[5], c[6]], 'acceptance test vs BlueStore.cc ' + i); });
      }
      // the chapter 12 examples
      t.eq(accept(64 * K, 50 * K, 4 * K, 0.875).want, 56 * K, 'want = 56 KiB');
      t.ok(accept(64 * K, 50 * K, 4 * K, 0.875).ok, '50 KiB -> 52 KiB accepted');
      t.ok(!accept(64 * K, 57.5 * K, 4 * K, 0.875).ok, '57.5 KiB rejected');
      t.ok(!accept(64 * K, 30 * K, 64 * K, 0.875).ok, 'min_alloc 64K: never accepted for 64 KiB blobs');
      t.eq(usage(1024, { type: 'rep', size: 3 }, 64 * K).alloc, 3 * 64 * K, '1 KiB x3 at 64K');
      t.eq(usage(1024, { type: 'ec', k: 4, m: 2, su: 4 * K, fast: false }, 64 * K).alloc, 6 * 64 * K, '1 KiB EC 4+2 at 64K');
      t.eq(usage(1024, { type: 'ec', k: 4, m: 2, su: 4 * K, fast: false }, 4 * K).stored, 6 * 4 * K, 'classic EC pads to a full stripe');
      t.eq(usage(1024, { type: 'ec', k: 4, m: 2, su: 16 * K, fast: true }, 4 * K).alloc, 3 * 4 * K, 'FastEC: one data shard and two parity');
      for (var s = 0; s < 300; s++) {
        var size = (s * 7919) % (9 * 1048576), p = { type: 'ec', k: 2 + s % 7, m: 1 + s % 3, su: [4 * K, 16 * K, 64 * K][s % 3], fast: !!(s % 2) };
        var u = usage(size, p, 4 * K), dataSum = u.shards.slice(0, p.k).reduce(function (a, b) { return a + b; }, 0);
        t.ok(p.fast ? dataSum === size : dataSum >= size && dataSum - size < p.k * p.su, 'data shards hold the object ' + s);
      }
    }
  };

  S.DEFS.bluespace = {
    icon: 'M4 4h16v16H4zM4 9h16M9 9v11M14 9v11',
    defaults: function () { return { size: 1024, count: 1000000, minAlloc: 4096, pool: 'ec42', fast: false, blob: 65536, comp: 50 * K, crr: 0.875 }; },
    refs: [['src/common/options/global.yaml.in :: bluestore_min_alloc_size_hdd, bluestore_min_alloc_size_ssd, bluestore_compression_required_ratio', 'bluespace_r1'],
           ['src/os/bluestore/BlueStore.cc :: BlueStore::_do_alloc_write (want_len, result_len)', 'bluespace_r2'],
           ['src/common/options/mon.yaml.in :: osd_pool_erasure_code_stripe_unit (4K, or 16K with allow_ec_optimizations)', 'bluespace_r3']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('bluespace_size'), sel('size', [[512, '512 B'], [1024, '1 KiB'], [4096, '4 KiB'], [16384, '16 KiB'], [102400, '100 KiB'], [1048576, '1 MiB'], [4194304, '4 MiB']], st.size))
        + field(T('bluespace_count'), sel('count', [[1000, '1,000'], [1000000, '1,000,000'], [100000000, '100,000,000']], st.count))
        + field('min_alloc_size', sel('minAlloc', [[4096, '4K'], [16384, '16K'], [65536, '64K']], st.minAlloc))
        + field(T('bluespace_pool'), sel('pool', [['rep3', T('bluespace_rep3')], ['ec42', 'EC 4+2'], ['ec83', 'EC 8+3']], st.pool))
        + (st.pool === 'rep3' ? '' : '<label class="sim-f sim-chk"><span>allow_ec_optimizations</span><input type="checkbox" data-k="fast"' + (st.fast ? ' checked' : '') + '></label>') + '</div>'
        + '<div class="sim-row">' + field(T('bluespace_blob'), sel('blob', [[16384, '16 KiB'], [65536, '64 KiB'], [131072, '128 KiB'], [524288, '512 KiB']], st.blob))
        + field(T('bluespace_comp'), '<input type="range" data-k="comp" min="1" max="' + st.blob + '" step="512" value="' + Math.min(st.comp, st.blob) + '" aria-valuetext="' + esc(bytes(st.comp)) + '">', '<bdi dir="ltr">' + bytes(st.comp) + '</bdi>')
        + field('compression_required_ratio', numIn('crr', st.crr, 0.1, 1, 0.025)) + '</div>';
    },
    pool: function (st) { return st.pool === 'rep3' ? { type: 'rep', size: 3 } : { type: 'ec', k: st.pool === 'ec42' ? 4 : 8, m: st.pool === 'ec42' ? 2 : 3, su: st.fast ? 16 * K : 4 * K, fast: st.fast }; },
    view: function (st) {
      var p = S.DEFS.bluespace.pool(st), u = usage(st.size, p, st.minAlloc), ideal = p.type === 'rep' ? 3 : (p.k + p.m) / p.k, amp = u.alloc / st.size;
      var maxS = Math.max.apply(null, u.shards.map(function (x) { return up(x, st.minAlloc); }).concat([1]));
      var bars = u.shards.map(function (s, i) {
        var a = up(s, st.minAlloc), isP = p.type === 'ec' && i >= p.k;
        return '<div class="bsp-row"><span class="lx-mono" dir="ltr">' + (p.type === 'rep' ? 'replica ' + i : (isP ? 'P' : 'D') + i) + '</span><div class="bsp-bar" dir="ltr"><i class="bsp-alloc" style="width:' + (100 * a / maxS) + '%"></i><i class="bsp-data' + (isP ? ' par' : '') + '" style="width:' + (100 * Math.min(s, st.size) / maxS) + '%"></i></div><span class="lx-mono" dir="ltr">' + bytes(s) + ' → ' + bytes(a) + '</span></div>';
      }).join('');
      var c = accept(st.blob, Math.min(st.comp, st.blob), st.minAlloc, st.crr);
      return '<div class="sim-stats">' + stat(L(Math.round(amp * 10) / 10) + '×', T('bluespace_s_amp'), amp > ideal * 1.5 ? 'warn' : '') + stat(L(Math.round(ideal * 100) / 100) + '×', T('bluespace_s_ideal'))
        + stat(bytes(u.alloc * st.count), T('bluespace_s_raw', { n: L(st.count.toLocaleString('en')) }), 'hot') + stat(bytes(st.size * st.count), T('bluespace_s_logical')) + '</div>'
        + '<h4>' + esc(T('bluespace_h1')) + '</h4><div class="bsp-list">' + bars + '</div>'
        + '<p class="sim-note">' + tx('bluespace_legend') + '</p>'
        + '<h4>' + esc(T('bluespace_h2')) + '</h4>'
        + '<div class="lx-card ' + (c.ok ? 'on' : 'bad') + '"><h4>' + esc(T(c.ok ? 'bluespace_acc' : 'bluespace_rej')) + '</h4><p class="lx-mono" dir="ltr">want = roundup(' + bytes(st.blob) + ' × ' + st.crr + ', ' + bytes(st.minAlloc) + ') = ' + bytes(c.want) + '<br>result = roundup(' + bytes(Math.min(st.comp, st.blob)) + ', ' + bytes(st.minAlloc) + ') = ' + bytes(c.result) + '<br>' + (c.ok ? 'result ≤ want && result < blob → ' + bytes(c.result) + ' allocated, ' + bytes(st.blob - c.result) + ' saved' : 'stored uncompressed: ' + bytes(st.blob) + ' (compress_rejected_count++)') + '</p></div>'
        + '<p class="sim-note">' + tx('bluespace_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'fast') { st.fast = !!v; return 'out'; }
      if (k === 'pool') { st.pool = v; return 'all'; }
      if (k === 'blob') { st.blob = +v; st.comp = Math.min(st.comp, st.blob); return 'all'; }
      if (k === 'crr') { var n = parseFloat(v); if (!isFinite(n)) return null; st.crr = clamp(n, 0.1, 1); return 'out'; }
      if (k in st) { st[k] = +v; return k === 'comp' ? 'all' : 'out'; }
      return null;
    },
    say: function (st) { var u = usage(st.size, S.DEFS.bluespace.pool(st), st.minAlloc); return T('bluespace_s_amp') + ': ' + L(Math.round(u.alloc / st.size * 10) / 10); },
    fallbackState: function (st) { st.minAlloc = 65536; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
