/* Bucket index sharding and dynamic reshard (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * calculatePreferred is a port of RGWBucketReshard::calculate_preferred_shards with the prime list and
 * nearest_prime of src/rgw/driver/rados/rgw_reshard.cc and the wrapper RGWRados::calculate_preferred_shards
 * (versioned buckets divide the threshold by 3); perShard is RGWRados::calc_ordered_bucket_list_per_shard;
 * the shard of a key is rgw_bucket_shard_index (sim-core.js, checked against ceph_str_hash_linux). */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, numIn = h.numIn, stat = h.stat, clamp = h.clamp, C = h.C;
  var PRIMES = [1, 2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37, 41, 43, 47, 53, 59, 61, 67, 71, 73, 79, 83, 89, 97, 101, 103, 107, 109, 113, 127, 131, 137,
    139, 149, 151, 157, 163, 167, 173, 179, 181, 191, 193, 197, 199, 211, 223, 227, 229, 233, 239, 241, 251, 257, 263, 269, 271, 277, 281, 283,
    293, 307, 311, 313, 317, 331, 337, 347, 349, 353, 359, 367, 373, 379, 383, 389, 397, 401, 409, 419, 421, 431, 433, 439, 443, 449, 457, 461,
    463, 467, 479, 487, 491, 499, 503, 509, 521, 523, 541, 547, 557, 563, 569, 571, 577, 587, 593, 599, 601, 607, 613, 617, 619, 631, 641, 643,
    647, 653, 659, 661, 673, 677, 683, 691, 701, 709, 719, 727, 733, 739, 743, 751, 757, 761, 769, 773, 787, 797, 809, 811, 821, 823, 827, 829,
    839, 853, 857, 859, 863, 877, 881, 883, 887, 907, 911, 919, 929, 937, 941, 947, 953, 967, 971, 977, 983, 991, 997, 1009, 1013, 1019, 1021,
    1031, 1033, 1039, 1049, 1051, 1061, 1063, 1069, 1087, 1091, 1093, 1097, 1103, 1109, 1117, 1123, 1129, 1151, 1153, 1163, 1171, 1181,
    1187, 1193, 1201, 1213, 1217, 1223, 1229, 1231, 1237, 1249, 1259, 1277, 1279, 1283, 1289, 1291, 1297, 1301, 1303, 1307, 1319, 1321,
    1327, 1361, 1367, 1373, 1381, 1399, 1409, 1423, 1427, 1429, 1433, 1439, 1447, 1451, 1453, 1459, 1471, 1481, 1483, 1487, 1489, 1493,
    1499, 1511, 1523, 1531, 1543, 1549, 1553, 1559, 1567, 1571, 1579, 1583, 1597, 1601, 1607, 1609, 1613, 1619, 1621, 1627, 1637, 1657,
    1663, 1667, 1669, 1693, 1697, 1699, 1709, 1721, 1723, 1733, 1741, 1747, 1753, 1759, 1777, 1783, 1787, 1789, 1801, 1811, 1823, 1831,
    1847, 1861, 1867, 1871, 1873, 1877, 1879, 1889, 1901, 1907, 1913, 1931, 1933, 1949, 1951, 1973, 1979, 1987, 1993, 1997, 1999];
  var MIN_DYN = 11, DEF_MIN_OBJS = 10000;
  function primeGE(n) { for (var i = 0; i < PRIMES.length; i++) if (PRIMES[i] >= n) return PRIMES[i]; return 0; }
  function nearestPrime(n) { var p = primeGE(n); return p ? p : n; }
  // RGWBucketReshard::calculate_preferred_shards (uint32 arithmetic as in C++)
  function preferred(maxDyn, minLayout, maxObjs, multisite, objs, cur) {
    var minObjs = Math.min(DEF_MIN_OBJS, Math.ceil(maxObjs / 100.0)), verb;
    if (cur < maxDyn && objs > cur * maxObjs) verb = 'expansion';
    else if (cur > MIN_DYN && objs < cur * minObjs) verb = 'reduction';
    else return { need: false };
    var mult = multisite ? 8 : 2;
    var calc = Math.max(MIN_DYN, Math.min(maxDyn, Math.floor(objs * mult / maxObjs) >>> 0));
    if (calc === cur) return { need: false };
    calc = nearestPrime(calc);
    calc = Math.min(maxDyn, Math.max(calc, MIN_DYN, minLayout));
    return { need: true, verb: verb, shards: calc };
  }
  // RGWRados::calculate_preferred_shards
  function check(o, objs, cur) {
    var maxObjs = o.maxObjs; if (o.versioned) maxObjs = Math.floor(maxObjs / 3); maxObjs = Math.max(1, maxObjs);
    return preferred(o.maxDyn, o.minLayout || 0, maxObjs, o.multisite, objs, cur);
  }
  function perShard(n, s) {
    if (!s) return 0;
    var calc = 1 + Math.trunc(Math.floor(n / s) + Math.sqrt((2 * n) * Math.log(s) / s));
    return Math.max(8, calc >>> 0);
  }
  // the growth path: the bucket is checked when its stats are synced, taken here as once every `every` new objects
  function path(o, target, start, every) {
    every = every || 1;
    var cur = start, steps = [], maxObjs = Math.max(1, o.versioned ? Math.floor(o.maxObjs / 3) : o.maxObjs);
    for (var guard = 0; guard < 64; guard++) {
      var at = (Math.floor(cur * maxObjs / every) + 1) * every;
      if (at > target) break;
      var r = check(o, at, cur);
      if (!r.need || r.shards <= cur) break;
      steps.push({ at: at, from: cur, to: r.shards, verb: r.verb }); cur = r.shards;
    }
    return { steps: steps, shards: cur };
  }

  S.X = S.X || {};
  S.X.reshard = {
    preferred: preferred, check: check, perShard: perShard, path: path, PRIMES: PRIMES,
    test: function (t) {
      (t.G.reshard_pref || []).forEach(function (c) {
        var r = preferred(c[0], c[1], c[2], !!c[3], c[4], c[5]);
        t.eq(r.need ? [1, r.shards] : [0, 0], c[6], 'calculate_preferred_shards ' + JSON.stringify(c.slice(0, 6)));
      });
      (t.G.reshard_list || []).forEach(function (c) { t.eq(perShard(c[0], c[1]), c[2], 'calc_ordered_bucket_list_per_shard ' + c[0] + ',' + c[1]); });
      t.eq(t.G.reshard_primes, PRIMES, 'the reshard_primes list');
      // the book's chapter 4 example: 11 → 29 → 61 → 127 → 257 → 521 → 1049 → 1999, multisite 11 → 97 → 787 → 1999
      var o = { maxObjs: 100000, maxDyn: 1999, versioned: false, multisite: false };
      t.eq(path(o, 2e8, 11, 100000).steps.map(function (s) { return s.to; }), [29, 61, 127, 257, 521, 1049, 1999], 'growth path, one zone');
      o.multisite = true;
      t.eq(path(o, 2e8, 11, 100000).steps.map(function (s) { return s.to; }), [97, 787, 1999], 'growth path, multisite');
      t.eq(check({ maxObjs: 100000, maxDyn: 1999 }, 90000, 101), { need: true, verb: 'reduction', shards: 11 }, 'reduction example');
      t.eq([perShard(1000, 11), perShard(1000, 101), perShard(1000, 1999)], [111, 19, 8], 'listing examples');
      [['photos/2026/11/img_0001.jpg', 11, 5], ['photos/2026/11/img_0001.jpg', 23, 18]].forEach(function (c) { t.eq(C.bucketShardIndex(c[0], c[1]), c[2], 'shard of ' + c[0]); });
    }
  };

  function fmtN(n) {
    if (n >= 1e6) return L(Math.round(n / 1e5) / 10) + (h.fa() ? ' میلیون' : 'M');
    if (n >= 1e3) return L(Math.round(n / 100) / 10) + (h.fa() ? ' هزار' : 'k');
    return L(n);
  }
  S.DEFS.reshard = {
    icon: 'M4 5h16M4 10h16M4 15h16M4 20h16M9 3v19M15 3v19',
    defaults: function () { return { objs: 30, every: 100000, start: 11, maxObjs: 100000, maxDyn: 1999, versioned: false, multisite: false, after: 0, keys: 1000 }; },
    refs: [['src/rgw/driver/rados/rgw_reshard.cc :: RGWBucketReshard::calculate_preferred_shards, nearest_prime, reshard_primes', 'reshard_r1'],
           ['src/rgw/driver/rados/rgw_rados.cc :: RGWRados::calculate_preferred_shards, check_bucket_shards; src/rgw/rgw_quota.cc :: RGWOwnerStatsCache::sync_bucket', 'reshard_r2'],
           ['src/rgw/driver/rados/rgw_rados.cc :: RGWRados::calc_ordered_bucket_list_per_shard', 'reshard_r3'],
           ['src/rgw/services/svc_bi_rados.h :: RGWSI_BucketIndex_RADOS::bucket_shard_index; src/common/ceph_hash.cc :: ceph_str_hash_linux', 'reshard_r4'],
           ['src/common/options/rgw.yaml.in :: rgw_max_objs_per_shard (100000), rgw_max_dynamic_shards (1999), rgw_dynamic_resharding_reduction_wait (120)', 'reshard_r5']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('reshard_objs'), numIn('objs', st.objs, 0.001, 1000, 'any')) + field(T('reshard_start'), sel('start', [1, 11, 23, 101, 211], st.start))
        + field('rgw_max_objs_per_shard', sel('maxObjs', [50000, 100000, 200000], st.maxObjs)) + field('rgw_max_dynamic_shards', sel('maxDyn', [499, 1999], st.maxDyn))
        + field(T('reshard_keys'), sel('keys', [100, 1000], st.keys)) + field(T('reshard_every'), sel('every', [[1, '1'], [10000, '10k'], [100000, '100k'], [1000000, '1M']], st.every)) + '</div>'
        + '<div class="sim-row"><label class="sim-f sim-chk"><span>' + esc(T('reshard_ver')) + '</span><input type="checkbox" data-k="versioned"' + (st.versioned ? ' checked' : '') + '></label>'
        + '<label class="sim-f sim-chk"><span>' + esc(T('reshard_ms')) + '</span><input type="checkbox" data-k="multisite"' + (st.multisite ? ' checked' : '') + '></label>'
        + field(T('reshard_after'), numIn('after', st.after, 0, 1000, 'any'), esc(T('reshard_after_h'))) + '</div>';
    },
    view: function (st) {
      var o = { maxObjs: st.maxObjs, maxDyn: st.maxDyn, versioned: st.versioned, multisite: st.multisite }, target = Math.round(st.objs * 1e6);
      var p = path(o, target, st.start, st.every), cur = p.shards, red = null;
      if (st.after > 0 && st.after * 1e6 < target) { var r = check(o, Math.round(st.after * 1e6), cur); if (r.need && r.verb === 'reduction') red = r.shards; }
      var fin = red || cur, finObjs = red ? Math.round(st.after * 1e6) : target, k = perShard(st.keys, fin);
      // step chart, log-log
      var W = 720, H = 210, x0 = 54, x1 = W - 14, y0 = H - 26, y1 = 12, lx = function (v) { return x0 + (Math.log10(Math.max(v, 1e3)) - 3) / 6 * (x1 - x0); }, ly = function (v) { return y0 - Math.log10(Math.max(v, 1)) / Math.log10(2000) * (y0 - y1); };
      var pts = [[1e3, st.start]], prev = st.start;
      p.steps.forEach(function (s) { pts.push([s.at, prev]); pts.push([s.at, s.to]); prev = s.to; });
      pts.push([Math.max(target, 1e3), prev]);
      var poly = pts.map(function (q) { return lx(q[0]).toFixed(1) + ',' + ly(q[1]).toFixed(1); }).join(' ');
      var labels = p.steps.map(function (s) { return '<circle class="lx-dot" cx="' + lx(s.at).toFixed(1) + '" cy="' + ly(s.to).toFixed(1) + '" r="3"/><text x="' + (lx(s.at) + 4).toFixed(1) + '" y="' + (ly(s.to) - 5).toFixed(1) + '">' + s.to + '</text>'; }).join('');
      var axes = [1e3, 1e4, 1e5, 1e6, 1e7, 1e8, 1e9].map(function (v) { return '<line class="lx-gl" x1="' + lx(v) + '" x2="' + lx(v) + '" y1="' + y1 + '" y2="' + y0 + '"/><text x="' + lx(v) + '" y="' + (H - 10) + '" text-anchor="middle">' + (v >= 1e9 ? '1G' : v >= 1e6 ? (v / 1e6) + 'M' : (v / 1e3) + 'k') + '</text>'; }).join('')
        + [1, 11, 101, 1999].map(function (v) { return '<line class="lx-gl" x1="' + x0 + '" x2="' + x1 + '" y1="' + ly(v) + '" y2="' + ly(v) + '"/><text x="' + (x0 - 4) + '" y="' + (ly(v) + 4) + '" text-anchor="end">' + v + '</text>'; }).join('');
      var now = '<line class="lx-now" x1="' + lx(target) + '" x2="' + lx(target) + '" y1="' + y1 + '" y2="' + y0 + '"/>';
      var fig = '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('reshard_fig')) + '" dir="ltr">' + axes + now + '<polyline class="lx-line" points="' + poly + '"/>' + labels + '</svg><figcaption>' + esc(T('reshard_cap')) + '</figcaption></figure>';
      var rows = p.steps.map(function (s, i) { return '<tr><td>' + L(i + 1) + '</td><td>' + fmtN(s.at) + '</td><td dir="ltr">' + s.from + ' → <b>' + s.to + '</b></td><td>' + esc(T('reshard_v_' + s.verb)) + '</td></tr>'; }).join('')
        + (red ? '<tr class="lx-red"><td>' + L(p.steps.length + 1) + '</td><td>' + fmtN(Math.round(st.after * 1e6)) + '</td><td dir="ltr">' + cur + ' → <b>' + red + '</b></td><td>' + esc(T('reshard_v_reduction')) + '</td></tr>' : '');
      // keys per shard for 2000 sample keys (the chapter 4 naming pattern)
      var cnt = new Array(fin).fill(0), N = 2000;
      for (var i = 0; i < N; i++) cnt[C.bucketShardIndex('photos/2026/11/img_' + String(i).padStart(6, '0') + '.jpg', fin)]++;
      var mn = Math.min.apply(null, cnt), mx = Math.max.apply(null, cnt);
      var dist = '';
      if (fin <= 128) {
        var bw = (W - 20) / fin, top = Math.max(mx, 1);
        dist = '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' 90" role="img" aria-label="' + esc(T('reshard_dist')) + '" dir="ltr">' + cnt.map(function (c, j) {
          var hh = c / top * 60; return '<rect class="lx-b f-ok" x="' + (10 + j * bw).toFixed(1) + '" y="' + (70 - hh).toFixed(1) + '" width="' + Math.max(1, bw - 1).toFixed(1) + '" height="' + hh.toFixed(1) + '"><title>.dir.&lt;marker&gt;.' + j + ': ' + c + '</title></rect>';
        }).join('') + '<text x="10" y="86">0</text><text x="' + (W - 10) + '" y="86" text-anchor="end">' + (fin - 1) + '</text></svg><figcaption>' + esc(T('reshard_dist_cap', { n: L(N), s: L(fin), a: L(mn), b: L(mx) })) + '</figcaption></figure>';
      } else dist = '<p class="sim-note">' + tx('reshard_dist_cap', { n: L(N), s: L(fin), a: L(mn), b: L(mx) }) + '</p>';
      var maxEff = st.versioned ? Math.floor(st.maxObjs / 3) : st.maxObjs;
      return '<div class="sim-stats">' + stat(L(fin), T('reshard_s_shards')) + stat(L(p.steps.length + (red ? 1 : 0)), T('reshard_s_count'), p.steps.length > 4 ? 'hot' : '')
        + stat(fmtN(Math.round(finObjs / fin)), T('reshard_s_per')) + stat(L(k) + ' × ' + L(fin), T('reshard_s_list', { n: L(st.keys) }), k * fin > 4 * st.keys ? 'warn' : '') + '</div>'
        + fig + '<div class="table-wrap"><table class="sim-t"><thead><tr><th>#</th><th>' + esc(T('reshard_h_at')) + '</th><th>' + esc(T('reshard_h_sh')) + '</th><th>' + esc(T('reshard_h_v')) + '</th></tr></thead><tbody>'
        + (rows || '<tr><td colspan="4">' + esc(T('reshard_none')) + '</td></tr>') + '</tbody></table></div>' + dist
        + '<div class="sim-formula" dir="ltr">expand if objects &gt; shards × ' + maxEff + (st.versioned ? ' (rgw_max_objs_per_shard / 3, versioned)' : '') + ' · reduce if shards &gt; 11 and objects &lt; shards × ' + Math.min(10000, Math.ceil(maxEff / 100))
        + '<br>new = clamp(⌊objects × ' + (st.multisite ? 8 : 2) + ' / ' + maxEff + '⌋, 11, ' + st.maxDyn + ') → next prime in reshard_primes · ordered listing reads max(8, 1 + ⌊n/s⌋ + √(2n·ln s / s)) = ' + k + ' entries from each of ' + fin + ' shards</div>'
        + (red ? '<p class="sim-note">' + tx('reshard_wait') + '</p>' : '') + '<p class="sim-note">' + tx('reshard_note') + '</p>';
    },
    input: function (st, k, v, el) {
      if (k === 'objs' || k === 'after') { st[k] = clamp(parseFloat(v) || 0, 0, 1000); return 'out'; }
      if (k === 'start' || k === 'maxObjs' || k === 'maxDyn' || k === 'keys' || k === 'every') { st[k] = +v; return 'out'; }
      if (k === 'versioned' || k === 'multisite') { st[k] = !!el.checked; return 'out'; }
      return null;
    },
    say: function (st) { var p = path({ maxObjs: st.maxObjs, maxDyn: st.maxDyn, versioned: st.versioned, multisite: st.multisite }, Math.round(st.objs * 1e6), st.start, st.every); return T('reshard_s_shards') + ': ' + L(p.shards); },
    fallbackState: function (st) { st.objs = 30; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
