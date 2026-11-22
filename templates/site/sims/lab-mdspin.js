/* CephFS subtree pinning across MDS ranks (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * rankBucket is a port of MDCache::hash_into_rank_bucket (rjhash64 of src/include/hash.h, then a jump consistent
 * hash), the dirfrag of a child is ceph_frag_make / ceph_frag_contains_value (src/include/ceph_frag.h) of
 * ceph_str_hash_rjenkins (the default dir hash), the frag bits are MDCache::handle_mdsmap and the pin that applies
 * is CInode::get_export_pin, as MDBalancer::handle_export_pins resolves it. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, sel = h.sel, field = h.field, stat = h.stat, seg = h.seg, C = h.C;
  var M64 = (1n << 64n) - 1n;
  function rjhash64(key) {                      // src/include/hash.h
    key = BigInt.asUintN(64, key);
    key = (~key & M64) + ((key << 21n) & M64) & M64;
    key = key ^ (key >> 24n);
    key = (key + ((key << 3n) & M64) + ((key << 8n) & M64)) & M64;
    key = key ^ (key >> 14n);
    key = (key + ((key << 2n) & M64) + ((key << 4n) & M64)) & M64;
    key = key ^ (key >> 28n);
    key = (key + ((key << 31n) & M64)) & M64;
    return key;
  }
  // MDCache::hash_into_rank_bucket(ino, fg); fgValue is frag_t::value(), fgEnc the whole frag_t (0 for the root frag)
  function rankBucket(ino, maxMds, fgEnc, fgValue) {
    if (maxMds === 0) return -1;
    var hash = rjhash64(BigInt(ino));
    if (fgEnc) hash = rjhash64((hash + rjhash64(BigInt(fgValue))) & M64);
    var b = -1, j = 0;
    while (j < maxMds) {
      b = j;
      hash = (hash * 2862933555777941757n + 1n) & M64;
      j = Math.trunc((b + 1) * (2147483648 / (Number(hash >> 33n) + 1)));
    }
    return b;
  }
  // MDCache::handle_mdsmap: the split floor for a distributed-pinned directory
  function fragBits(maxMds, factor) {
    if (maxMds <= 1) return 0;
    var want = Math.fround(factor) * maxMds, n = 0;
    while (Math.pow(2, n) < (want >>> 0)) n++;
    return n;
  }
  // the leaf dirfrag holding a dentry when the directory is split evenly into 2^bits frags
  function fragOf(name, bits) {
    var hsh = C.strHash(name) >>> 0, mask = bits ? ((0xffffff << (24 - bits)) & 0xffffff) >>> 0 : 0, v = (hsh & mask) >>> 0;
    return { enc: bits ? (((bits << 24) | v) >>> 0) : 0, value: v, bits: bits, hash: hsh };
  }
  function fragStr(f) { return f.bits ? (f.value >>> (24 - f.bits)).toString(2).padStart(f.bits, '0') + '*' : '*'; }

  // the tree: inode numbers start at 0x10000000000, the first one CephFS hands out
  var BASE = 0x10000000000;
  function tree(st) {
    var n = [], ino = BASE;
    function add(path, parent, pol) { var d = { path: path, parent: parent, ino: ino++, pin: -1, dist: false, rand: 0 }; for (var k in pol) d[k] = pol[k]; n.push(d); return d; }
    var rootd = { path: '/', parent: null, ino: 1, pin: -1, dist: false, rand: 0, system: true }; n.push(rootd);
    var home = add('/home', rootd, { dist: st.dist });
    for (var i = 1; i <= 24; i++) add('/home/user' + String(i).padStart(2, '0'), home, {});
    var proj = add('/projects', rootd, { pin: st.ppin });
    add('/projects/alpha', proj, { pin: st.apin }); add('/projects/beta', proj, {}); add('/projects/gamma', proj, {});
    var scr = add('/scratch', rootd, { rand: st.rand });
    for (var j = 1; j <= 12; j++) add('/scratch/job' + String(j).padStart(3, '0'), scr, {});
    return n;
  }
  function name(d) { return d.path.slice(d.path.lastIndexOf('/') + 1); }
  // CInode::get_ephemeral_rand: the closest random policy, capped by mds_export_ephemeral_random_max
  function ephRand(d, max) {
    for (var x = d; x && !x.system; x = x.parent) {
      if (x.rand > 0) return Math.min(x.rand, max);
      if (x.pin >= 0 || x.dist) return 0;
    }
    return 0;
  }
  // a fixed draw per directory in [0, 1) stands in for the random number Ceph draws when the inode is loaded
  function draw(d) { return Number(rjhash64(BigInt(d.ino) ^ 0x5bd1e995n) >> 11n) / 9007199254740992; }
  // CInode::get_export_pin(inherit=true) resolved to a rank as MDBalancer does; -2 means no pin applies
  function exportPin(d, st, bits) {
    var rTarget = null, fromFrag = null;
    for (var x = d; x && !x.system; x = x.parent) {
      if (x.pin >= 0) return { rank: x.pin, why: x === d ? 'pin' : 'pin_in', via: x };
      if (x.dist && st.edist) {
        if (x !== d) { var f = fragOf(name(fromFrag), bits); return { rank: rankBucket(x.ino, st.max, f.enc, f.value), why: 'dist', via: x, frag: f }; }
        return { rank: -3, why: 'distroot', via: x };
      }
      if (rTarget !== null && x.rand > 0) return { rank: rTarget, why: 'rand', via: d };
      if (rTarget === null && x.chosen) rTarget = rankBucket(x.ino, st.max, 0, 0);
      fromFrag = x;
    }
    return { rank: -2, why: 'none' };
  }
  function resolve(st) {
    var n = tree(st), bits = fragBits(st.max, st.factor);
    n.forEach(function (d) { d.chosen = !d.system && d.parent && !d.parent.system && ephRand(d, st.rmax) > 0 && draw(d) <= ephRand(d, st.rmax); });
    n.forEach(function (d) {
      if (d.system) { d.rank = 0; d.why = 'root'; return; }
      var e = exportPin(d, st, bits);
      d.e = e; d.why = e.why;
      // a pin to a rank that does not exist (>= max_mds) is not acted on: the directory stays with its parent's subtree
      d.rank = e.rank >= 0 && e.rank < st.max ? e.rank : d.parent.rank;
      if (e.rank >= st.max) d.why = 'pin_big';
    });
    return { nodes: n, bits: bits };
  }

  S.X = S.X || {};
  S.X.mdspin = {
    rjhash64: rjhash64, rankBucket: rankBucket, fragBits: fragBits, fragOf: fragOf, resolve: resolve,
    test: function (t) {
      (t.G.mdspin_rj || []).forEach(function (c) { t.eq(rjhash64(BigInt(c[0])).toString(), c[1], 'rjhash64(' + c[0] + ')'); });
      (t.G.mdspin_rank || []).forEach(function (c) {
        var f = fragOf(c[1], c[2]);
        t.eq([f.enc, rankBucket(c[0], c[3], f.enc, f.value)], [c[4], c[5]], 'frag and hash_into_rank_bucket ' + JSON.stringify(c.slice(0, 4)));
      });
      (t.G.mdspin_bits || []).forEach(function (c) { t.eq(fragBits(c[0], c[1]), c[2], 'frag bits ' + c[0] + ' × ' + c[1]); });
      // consistent hashing: growing max_mds from 4 to 5 moves only the children that land on the new rank
      var st = S.DEFS.mdspin.defaults(); st.factor = 2;
      var a = {}, moved = 0, toNew = 0;
      for (var i = 0; i < 4000; i++) a[i] = rankBucket(BASE + i, 4, 0, 0);
      for (var j = 0; j < 4000; j++) { var r = rankBucket(BASE + j, 5, 0, 0); if (r !== a[j]) { moved++; if (r === 4) toNew++; } }
      t.eq(moved, toNew, 'jump hash moves only to the new rank');
    }
  };

  var WHY = { root: 'mdspin_w_root', pin: 'mdspin_w_pin', pin_in: 'mdspin_w_pinin', pin_big: 'mdspin_w_pinbig', dist: 'mdspin_w_dist', distroot: 'mdspin_w_distroot', rand: 'mdspin_w_rand', none: 'mdspin_w_none' };
  S.DEFS.mdspin = {
    icon: 'M12 3v6M12 9l-6 5M12 9l6 5M6 14v5M18 14v5M4 19h4M16 19h4M10 19h4M12 14v5',
    defaults: function () { return { max: 3, factor: 2, edist: true, dist: true, ppin: 1, apin: -1, rand: 0.5, rmax: 0.01, prev: null }; },
    refs: [['src/mds/MDCache.cc :: MDCache::hash_into_rank_bucket; src/include/hash.h :: rjhash64', 'mdspin_r1'],
           ['src/mds/CInode.cc :: CInode::get_export_pin, get_ephemeral_rand, maybe_ephemeral_rand', 'mdspin_r2'],
           ['src/mds/MDBalancer.cc :: handle_export_pins; src/mds/MDCache.cc :: handle_mdsmap (export_ephemeral_dist_frag_bits)', 'mdspin_r3'],
           ['src/include/ceph_frag.h :: ceph_frag_make, ceph_frag_contains_value; src/mds/CInode.cc :: hash_dentry_name', 'mdspin_r4'],
           ['src/common/options/mds.yaml.in :: mds_export_ephemeral_distributed (true), mds_export_ephemeral_distributed_factor (2), mds_export_ephemeral_random (true), mds_export_ephemeral_random_max (0.01)', 'mdspin_r5']],
    controls: function (st) {
      var ranks = [[-1, T('mdspin_nopin')]].concat([0, 1, 2, 3, 4, 5, 6, 7].map(function (r) { return [r, 'rank ' + r]; }));
      return '<div class="sim-row"><div class="sim-f"><span>max_mds</span>' + seg('max', [1, 2, 3, 4, 5, 6, 8].map(function (x) { return [x, L(x)]; }), st.max) + '</div>'
        + field('…distributed_factor', sel('factor', [1, 2, 4], st.factor)) + field('…random_max', sel('rmax', [0.01, 0.1, 0.5, 1], st.rmax))
        + '<label class="sim-f sim-chk"><span>mds_export_ephemeral_distributed</span><input type="checkbox" data-k="edist"' + (st.edist ? ' checked' : '') + '></label></div>'
        + '<div class="sim-row"><label class="sim-f sim-chk"><span dir="ltr">/home: ceph.dir.pin.distributed</span><input type="checkbox" data-k="dist"' + (st.dist ? ' checked' : '') + '></label>'
        + field('/projects: ceph.dir.pin', sel('ppin', ranks, st.ppin)) + field('/projects/alpha: ceph.dir.pin', sel('apin', ranks, st.apin))
        + field('/scratch: ceph.dir.pin.random', sel('rand', [0, 0.01, 0.1, 0.5, 1], st.rand)) + '</div>';
    },
    view: function (st) {
      var r = resolve(st), nodes = r.nodes, per = []; for (var i = 0; i < st.max; i++) per.push(0);
      nodes.forEach(function (d) { if (!d.system) per[d.rank]++; });
      var moved = 0;
      if (st.prev) nodes.forEach(function (d) { if (st.prev[d.path] != null && st.prev[d.path] !== d.rank) moved++; });
      function row(d) {
        var depth = d.path === '/' ? 0 : d.path.split('/').length - 1, extra = '';
        if (d.e && d.e.why === 'dist') extra = ' <small dir="ltr">frag ' + fragStr(d.e.frag) + '</small>';
        if (d.e && d.e.why === 'rand') extra = ' <small dir="ltr">draw ' + draw(d).toFixed(3) + ' ≤ ' + ephRand(d, st.rmax) + '</small>';
        var mv = st.prev && st.prev[d.path] != null && st.prev[d.path] !== d.rank;
        return '<li class="md-d d' + depth + (mv ? ' mv' : '') + '"><span class="md-r r' + d.rank + '" dir="ltr">' + d.rank + '</span><code dir="ltr">' + esc(d.path) + '</code> <span class="md-why">' + tx(WHY[d.why]) + '</span>' + extra + '</li>';
      }
      var groups = [nodes.filter(function (d) { return d.path === '/' || d.path === '/home'; }), nodes.filter(function (d) { return d.path.indexOf('/home/') === 0; }),
        nodes.filter(function (d) { return d.path.indexOf('/projects') === 0; }), nodes.filter(function (d) { return d.path.indexOf('/scratch') === 0; })];
      var W = 720, bw = (W - 20) / st.max, top = Math.max.apply(null, per.concat([1]));
      var bars = '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' 110" role="img" aria-label="' + esc(T('mdspin_fig')) + '" dir="ltr">' + per.map(function (c, k) {
        var hh = c / top * 70; return '<rect class="md-bar r' + k + '" x="' + (12 + k * bw) + '" y="' + (84 - hh) + '" width="' + (bw - 8) + '" height="' + hh + '" rx="3"/><text x="' + (12 + k * bw + (bw - 8) / 2) + '" y="' + (80 - hh) + '" text-anchor="middle">' + c + '</text><text x="' + (12 + k * bw + (bw - 8) / 2) + '" y="102" text-anchor="middle">rank ' + k + '</text>';
      }).join('') + '</svg><figcaption>' + esc(T('mdspin_cap')) + '</figcaption></figure>';
      var cmds = ['ceph fs set cephfs max_mds ' + st.max];
      if (st.dist) cmds.push('setfattr -n ceph.dir.pin.distributed -v 1 /mnt/cephfs/home');
      if (st.ppin >= 0) cmds.push('setfattr -n ceph.dir.pin -v ' + st.ppin + ' /mnt/cephfs/projects');
      if (st.apin >= 0) cmds.push('setfattr -n ceph.dir.pin -v ' + st.apin + ' /mnt/cephfs/projects/alpha');
      if (st.rand > 0) cmds.push('setfattr -n ceph.dir.pin.random -v ' + st.rand + ' /mnt/cephfs/scratch');
      if (st.rmax !== 0.01) cmds.push('ceph config set mds mds_export_ephemeral_random_max ' + st.rmax);
      return '<div class="sim-stats">' + stat(L(st.max), T('mdspin_s_ranks')) + stat(L(Math.pow(2, r.bits)), T('mdspin_s_frags')) + stat(L(Math.max.apply(null, per)) + ' / ' + L(Math.min.apply(null, per)), T('mdspin_s_spread'))
        + stat(st.prev ? L(moved) : '–', T('mdspin_s_moved'), moved ? 'hot' : '') + '</div>' + bars
        + '<div class="md-cols">' + groups.map(function (g, gi) {
          if (gi === 1) return '<div class="md-chips" dir="ltr">' + g.map(function (d) {
            var mv = st.prev && st.prev[d.path] != null && st.prev[d.path] !== d.rank;
            return '<span class="md-chip r' + d.rank + (mv ? ' mv' : '') + '" title="' + esc(d.path + ' → rank ' + d.rank + (d.e && d.e.frag ? ' (frag ' + fragStr(d.e.frag) + ')' : '')) + '">' + esc(name(d)) + (d.e && d.e.frag ? '<small>' + fragStr(d.e.frag) + '</small>' : '') + '</span>';
          }).join('') + '</div>';
          return '<ul class="md-tree">' + g.map(row).join('') + '</ul>';
        }).join('') + '</div>'
        + '<pre class="sim-cmd" dir="ltr"><code>' + esc(cmds.join('\n')) + '</code></pre>'
        + '<div class="sim-formula" dir="ltr">frag bits = ⌈log2(factor × max_mds)⌉ = ' + r.bits + ' · child → frag by ceph_str_hash_rjenkins(name) · rank = hash_into_rank_bucket(ino(/home), frag) = jump_hash(rjhash64(rjhash64(ino) + rjhash64(frag)), max_mds)</div>'
        + '<p class="sim-note">' + tx('mdspin_note') + '</p>';
    },
    input: function (st, k, v, el) {
      var snap = function () { var o = {}; resolve(st).nodes.forEach(function (d) { o[d.path] = d.rank; }); st.prev = o; };
      if (k === 'max' || k === 'factor' || k === 'rmax' || k === 'ppin' || k === 'apin' || k === 'rand') { snap(); st[k] = +v; return k === 'max' ? 'all' : 'out'; }
      if (k === 'edist' || k === 'dist') { snap(); st[k] = !!el.checked; return 'out'; }
      return null;
    },
    say: function (st) { return 'max_mds ' + st.max; },
    fallbackState: function (st) { return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
