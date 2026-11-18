/*
 * sim-core.js: the arithmetic behind the web edition's interactive simulators.
 * No DOM, no network; runs in the browser (window.SimCore) and in node (tests).
 *
 * Every function is a port of a named Ceph function (main branch, November 2026);
 * the name is given above each one. tests/sims/test_core.js checks the ports
 * against data produced by Ceph's own code (tools/simref/gen_golden.py) and
 * against the vectors of Ceph's unit tests.
 * Part of "Ceph: Scalable Storage" by Ramin Najarbashi. CC BY-NC-SA 4.0.
 */
(function (root) {
  'use strict';
  var LNT = (typeof module !== 'undefined' && module.exports) ? require('./crush-ln-table.js') : root.CRUSH_LN_TABLE;

  /* ------------------------------------------------------------ hashes */
  // src/crush/hash.c :: crush_hashmix (Robert Jenkins' 96-bit mix), on unsigned 32-bit values
  function mix(s) {
    var a = s[0], b = s[1], c = s[2];
    a = (a - b) >>> 0; a = (a - c) >>> 0; a = (a ^ (c >>> 13)) >>> 0;
    b = (b - c) >>> 0; b = (b - a) >>> 0; b = (b ^ (a << 8)) >>> 0;
    c = (c - a) >>> 0; c = (c - b) >>> 0; c = (c ^ (b >>> 13)) >>> 0;
    a = (a - b) >>> 0; a = (a - c) >>> 0; a = (a ^ (c >>> 12)) >>> 0;
    b = (b - c) >>> 0; b = (b - a) >>> 0; b = (b ^ (a << 16)) >>> 0;
    c = (c - a) >>> 0; c = (c - b) >>> 0; c = (c ^ (b >>> 5)) >>> 0;
    a = (a - b) >>> 0; a = (a - c) >>> 0; a = (a ^ (c >>> 3)) >>> 0;
    b = (b - c) >>> 0; b = (b - a) >>> 0; b = (b ^ (a << 10)) >>> 0;
    c = (c - a) >>> 0; c = (c - b) >>> 0; c = (c ^ (b >>> 15)) >>> 0;
    s[0] = a; s[1] = b; s[2] = c;
  }
  var SEED = 1315423911;
  // src/crush/hash.c :: crush_hash32_rjenkins1_2
  function hash2(a, b) {
    a >>>= 0; b >>>= 0;
    var hash = (SEED ^ a ^ b) >>> 0, x = 231232, y = 1232, s;
    s = [a, b, hash]; mix(s); a = s[0]; b = s[1]; hash = s[2];
    s = [x, a, hash]; mix(s); x = s[0]; a = s[1]; hash = s[2];
    s = [b, y, hash]; mix(s); b = s[0]; y = s[1]; hash = s[2];
    return hash;
  }
  // src/crush/hash.c :: crush_hash32_rjenkins1_3
  function hash3(a, b, c) {
    a >>>= 0; b >>>= 0; c >>>= 0;
    var hash = (SEED ^ a ^ b ^ c) >>> 0, x = 231232, y = 1232, s;
    s = [a, b, hash]; mix(s); a = s[0]; b = s[1]; hash = s[2];
    s = [c, x, hash]; mix(s); c = s[0]; x = s[1]; hash = s[2];
    s = [y, a, hash]; mix(s); y = s[0]; a = s[1]; hash = s[2];
    s = [b, x, hash]; mix(s); b = s[0]; x = s[1]; hash = s[2];
    s = [y, c, hash]; mix(s); y = s[0]; c = s[1]; hash = s[2];
    return hash;
  }
  // src/crush/hash.c :: crush_hash32_rjenkins1_4 (list and tree buckets)
  function hash4(a, b, c, d) {
    a >>>= 0; b >>>= 0; c >>>= 0; d >>>= 0;
    var hash = (SEED ^ a ^ b ^ c ^ d) >>> 0, x = 231232, y = 1232, s;
    s = [a, b, hash]; mix(s); a = s[0]; b = s[1]; hash = s[2];
    s = [c, d, hash]; mix(s); c = s[0]; d = s[1]; hash = s[2];
    s = [a, x, hash]; mix(s); a = s[0]; x = s[1]; hash = s[2];
    s = [y, b, hash]; mix(s); y = s[0]; b = s[1]; hash = s[2];
    s = [c, x, hash]; mix(s); c = s[0]; x = s[1]; hash = s[2];
    s = [y, d, hash]; mix(s); y = s[0]; d = s[1]; hash = s[2];
    return hash;
  }
  function utf8(str) {
    if (typeof TextEncoder !== 'undefined') return new TextEncoder().encode(str);
    return Buffer.from(str, 'utf8');
  }
  // src/common/ceph_hash.cc :: ceph_str_hash_rjenkins (the pool's object_hash)
  function strHash(str) {
    var k = typeof str === 'string' ? utf8(str) : str, length = k.length, len = length, p = 0;
    var s = [0x9e3779b9, 0x9e3779b9, 0];
    function w(i) { return (k[i] | (k[i + 1] << 8) | (k[i + 2] << 16) | (k[i + 3] << 24)) >>> 0; }
    while (len >= 12) {
      s[0] = (s[0] + w(p)) >>> 0; s[1] = (s[1] + w(p + 4)) >>> 0; s[2] = (s[2] + w(p + 8)) >>> 0;
      mix(s); p += 12; len -= 12;
    }
    s[2] = (s[2] + length) >>> 0;
    /* the last 11 bytes; the C switch falls through */
    if (len >= 11) s[2] = (s[2] + ((k[p + 10] << 24) >>> 0)) >>> 0;
    if (len >= 10) s[2] = (s[2] + (k[p + 9] << 16)) >>> 0;
    if (len >= 9) s[2] = (s[2] + (k[p + 8] << 8)) >>> 0;
    if (len >= 8) s[1] = (s[1] + ((k[p + 7] << 24) >>> 0)) >>> 0;
    if (len >= 7) s[1] = (s[1] + (k[p + 6] << 16)) >>> 0;
    if (len >= 6) s[1] = (s[1] + (k[p + 5] << 8)) >>> 0;
    if (len >= 5) s[1] = (s[1] + k[p + 4]) >>> 0;
    if (len >= 4) s[0] = (s[0] + ((k[p + 3] << 24) >>> 0)) >>> 0;
    if (len >= 3) s[0] = (s[0] + (k[p + 2] << 16)) >>> 0;
    if (len >= 2) s[0] = (s[0] + (k[p + 1] << 8)) >>> 0;
    if (len >= 1) s[0] = (s[0] + k[p]) >>> 0;
    mix(s);
    return s[2];
  }
  // src/include/rados.h :: ceph_stable_mod
  function stableMod(x, b, bmask) { return (x & bmask) < b ? (x & bmask) : (x & (bmask >> 1)); }
  // src/osd/osd_types.cc :: pg_pool_t::calc_pg_masks (pg_num_mask = (1 << cbits(pg_num - 1)) - 1)
  function pgMask(n) { var v = n - 1, bits = v ? 32 - Math.clz32(v) : 0; return (bits >= 31 ? 0x7fffffff : (1 << bits) - 1); }

  /* ------------------------------------------------------------ crush_ln and straw2 */
  var LN = null;
  // src/crush/mapper.c :: crush_ln: 2^44 * log2(input + 1), fixed point, via two lookup tables
  function crushLn(xin) {
    var x = (xin + 1) >>> 0, iexpon = 15;
    if (!(x & 0x18000)) { var bits = Math.clz32(x & 0x1FFFF) - 16; x = x << bits; iexpon = 15 - bits; }
    var index1 = (x >>> 8) << 1;
    var RH = LNT.RH_LH[index1 - 256], LH = LNT.RH_LH[index1 + 1 - 256];
    // xl64 = ((s64)x * RH) >> 48: the product can exceed 2^53, so this one step uses BigInt
    var xl64 = Number((BigInt(x) * BigInt(RH)) >> 48n);
    var index2 = xl64 & 0xff;
    LH = LH + LNT.LL[index2];
    return iexpon * 17592186044416 + Math.floor(LH / 16);   /* (iexpon << 44) + (LH >> 4) */
  }
  function lnOf(u) {
    if (!LN) { LN = new Float64Array(65536); for (var i = 0; i < 65536; i++) LN[i] = crushLn(i); }
    return LN[u];
  }
  // src/crush/mapper.c :: generate_exponential_distribution
  // ln < 2^49 and the weight is an integer, so the double quotient truncates exactly like div64_s64
  function expDraw(x, y, z, weight) {
    var u = hash3(x, y, z) & 0xffff;
    var ln = lnOf(u) - 281474976710656;     /* - 0x1000000000000 */
    return Math.trunc(ln / weight);
  }
  // src/crush/mapper.c :: bucket_straw2_choose (no choose_args)
  // info (optional) receives every candidate's draw, for the step-by-step lab
  function straw2(b, x, r, info) {
    var high = 0, highDraw = 0, draw;
    for (var i = 0; i < b.items.length; i++) {
      draw = b.weights[i] ? expDraw(x, b.items[i], r, b.weights[i]) : -Infinity;   /* S64_MIN */
      if (info) info.push({ item: b.items[i], w: b.weights[i], u: hash3(x, b.items[i], r) & 0xffff, draw: draw });
      if (i === 0 || draw > highDraw) { high = i; highDraw = draw; }
    }
    return b.items[high];
  }

  /* ------------------------------------------------------------ the four older bucket algorithms */
  // src/crush/mapper.c :: bucket_straw_choose: the longest scaled straw (hash & 0xffff) * straws[i] wins
  function straw(b, x, r, info) {
    var high = 0, highDraw = 0, draw, u;
    for (var i = 0; i < b.items.length; i++) {
      u = hash3(x, b.items[i], r) & 0xffff;
      draw = u * b.straws[i];                          /* < 2^48: exact */
      if (info) info.push({ item: b.items[i], w: b.weights[i], u: u, straw: b.straws[i], draw: draw });
      if (i === 0 || draw > highDraw) { high = i; highDraw = draw; }
    }
    return b.items[high];
  }
  // src/crush/builder.c :: crush_calc_straw (straw_calc_version 1, set by the jewel and later tunables)
  function calcStraws(weights, version) {
    var size = weights.length, rev = [], i, j, k, straws = new Array(size);
    if (size) rev[0] = 0;
    for (i = 1; i < size; i++) {                        /* reverse sort by weight (insertion sort) */
      for (j = 0; j < i; j++) {
        if (weights[i] < weights[rev[j]]) { for (k = i; k > j; k--) rev[k] = rev[k - 1]; rev[j] = i; break; }
      }
      if (j === i) rev[i] = i;
    }
    var numleft = size, st = 1.0, wbelow = 0, lastw = 0, wnext, pbelow;
    i = 0;
    while (i < size) {
      if (version === 0) {
        if (weights[rev[i]] === 0) { straws[rev[i]] = 0; i++; continue; }
        straws[rev[i]] = Math.trunc(st * 0x10000) >>> 0;
        i++;
        if (i === size) break;
        if (weights[rev[i]] === weights[rev[i - 1]]) continue;
        wbelow += (weights[rev[i - 1]] - lastw) * numleft;
        for (j = i; j < size; j++) { if (weights[rev[j]] === weights[rev[i]]) numleft--; else break; }
        wnext = numleft * (weights[rev[i]] - weights[rev[i - 1]]);
      } else {
        if (weights[rev[i]] === 0) { straws[rev[i]] = 0; i++; numleft--; continue; }
        straws[rev[i]] = Math.trunc(st * 0x10000) >>> 0;
        i++;
        if (i === size) break;
        wbelow += (weights[rev[i - 1]] - lastw) * numleft;
        numleft--;
        wnext = numleft * (weights[rev[i]] - weights[rev[i - 1]]);
      }
      pbelow = wbelow / (wbelow + wnext);
      st *= Math.pow(1.0 / pbelow, 1.0 / numleft);
      lastw = weights[rev[i - 1]];
    }
    return straws;
  }
  // src/crush/mapper.c :: bucket_list_choose: walk from the tail; item i keeps the draw with probability w_i / sum_i
  function list(b, x, r, info) {
    for (var i = b.items.length - 1; i >= 0; i--) {
      var u = hash4(x, b.items[i], r, b.id) & 0xffff;
      var sc = Math.floor(u * b.sum[i] / 65536);       /* (u * sum_weights[i]) >> 16, < 2^48 */
      var ok = sc < b.weights[i];
      if (info) info.push({ item: b.items[i], w: b.weights[i], u: u, sum: b.sum[i], scaled: sc, ok: ok });
      if (ok) return b.items[i];
    }
    return b.items[0];
  }
  // src/crush/mapper.c :: height, left, right, terminal (node numbers of the tree bucket)
  function theight(n) { var h = 0; while ((n & 1) === 0) { h++; n >>= 1; } return h; }
  function tleft(n) { return n - (1 << (theight(n) - 1)); }
  function tright(n) { return n + (1 << (theight(n) - 1)); }
  // ((u64)hash * w) >> 32 without losing bits: split w into 16-bit halves (every partial product < 2^48)
  function mulHi32(h, w) {
    var a = h * (w >>> 16), bb = h * (w & 0xffff), aq = Math.floor(a / 65536), ar = a - aq * 65536;
    return aq + Math.floor((ar * 65536 + bb) / 4294967296);
  }
  // src/crush/mapper.c :: bucket_tree_choose: descend a weighted binary tree from the root node
  function tree(b, x, r, info) {
    var n = b.numNodes >> 1;
    while (!(n & 1)) {
      var w = b.nodes[n], t = mulHi32(hash4(x, n, r, b.id), w), l = tleft(n), goLeft = t < b.nodes[l];
      if (info) info.push({ node: n, w: w, t: t, left: l, lw: b.nodes[l], right: tright(n), dir: goLeft ? 'L' : 'R' });
      n = goLeft ? l : tright(n);
    }
    return b.items[n >> 1];
  }
  // src/crush/builder.c :: calc_depth, crush_make_tree_bucket (crush.h :: crush_calc_tree_node)
  function treeNodes(weights) {
    var size = weights.length, depth = 0;
    if (size) { depth = 1; for (var t = size - 1; t; t >>= 1) depth++; }
    var num = 1 << depth, nodes = new Array(num).fill(0);
    function parent(n) { var h = theight(n); return (n & (1 << (h + 1))) ? n - (1 << h) : n + (1 << h); }
    for (var i = 0; i < size; i++) {
      var node = ((i + 1) << 1) - 1;
      nodes[node] = weights[i];
      for (var j = 1; j < depth; j++) { node = parent(node); nodes[node] += weights[i]; }
    }
    return { numNodes: size ? num : 0, nodes: nodes };
  }
  // src/crush/mapper.c :: bucket_perm_choose (uniform buckets): a Fisher-Yates permutation driven by the hash,
  // kept in the per-call workspace (crush_work_bucket) so that r = 1, 2, ... extend it instead of redoing it
  function permChoose(b, wk, x, r, info) {
    var size = b.items.length, pr = r % size, i, s;
    x >>>= 0;
    if (wk.permX !== x || wk.permN === 0) {
      wk.permX = x;
      if (pr === 0) {
        s = hash3(x, b.id, 0) % size;
        wk.perm[0] = s; wk.permN = 0xffff;
        if (info) info.push({ p: 0, h: hash3(x, b.id, 0), mod: size, swap: s, fast: true, perm: [s] });
        return b.items[s];
      }
      for (i = 0; i < size; i++) wk.perm[i] = i;
      wk.permN = 0;
    } else if (wk.permN === 0xffff) {
      for (i = 1; i < size; i++) wk.perm[i] = i;
      wk.perm[wk.perm[0]] = 0;
      wk.permN = 1;
    }
    while (wk.permN <= pr) {
      var p = wk.permN;
      if (p < size - 1) {
        var hh = hash3(x, b.id, p);
        i = hh % (size - p);
        if (i) { var t = wk.perm[p + i]; wk.perm[p + i] = wk.perm[p]; wk.perm[p] = t; }
        if (info) info.push({ p: p, h: hh, mod: size - p, swap: p + i, perm: wk.perm.slice(0, size) });
      }
      wk.permN++;
    }
    s = wk.perm[pr];
    if (info) info.push({ pr: pr, pick: s });
    return b.items[s];
  }
  var ALG = { uniform: 1, list: 2, tree: 3, straw: 4, straw2: 5 };
  // src/crush/mapper.c :: crush_bucket_choose
  function bucketChoose(m, b, x, r, info) {
    switch (b.alg) {
      case 'uniform': return permChoose(b, work(m, b), x, r, info);
      case 'list': return list(b, x, r, info);
      case 'tree': return tree(b, x, r, info);
      case 'straw': return straw(b, x, r, info);
      default: return straw2(b, x, r, info);
    }
  }
  // src/crush/mapper.c :: crush_init_workspace (perm_x = perm_n = 0 for every bucket, once per crush_do_rule)
  function work(m, b) {
    var w = m.work[b.id];
    if (!w) w = m.work[b.id] = { permX: 0, permN: 0, perm: new Array(b.items.length).fill(0) };
    return w;
  }

  /* ------------------------------------------------------------ CRUSH map and rules */
  var NONE = 0x7fffffff, UNDEF = 0x7ffffffe;
  var OP = { TAKE: 1, CHOOSE_FIRSTN: 2, CHOOSE_INDEP: 3, EMIT: 4, CHOOSELEAF_FIRSTN: 6, CHOOSELEAF_INDEP: 7,
             SET_CHOOSE_TRIES: 8, SET_CHOOSELEAF_TRIES: 9, SET_CHOOSE_LOCAL_TRIES: 10, SET_CHOOSE_LOCAL_FALLBACK_TRIES: 11,
             SET_CHOOSELEAF_VARY_R: 12, SET_CHOOSELEAF_STABLE: 13 };
  // src/crush/CrushWrapper.h :: set_tunables_jewel (also the "optimal" and "default" profiles)
  var JEWEL = { local: 0, fallback: 0, total: 50, descendOnce: 1, varyR: 1, stable: 1, strawCalc: 1 };

  // buckets: [{id (<0), type, alg ('straw2' when absent), items:[id], weights:[16.16]}]
  // src/crush/builder.c :: crush_make_bucket: the bucket weight is the sum of the item weights, except
  // uniform (size * the first item's weight; the other weights are ignored); list keeps running sums,
  // tree the node weights and straw the scaled straw lengths
  function bucketWeight(alg, ws) { return alg === 'uniform' ? (ws.length ? ws.length * ws[0] : 0) : ws.reduce(function (s, w) { return s + w; }, 0); }
  function makeMap(buckets, rules, tun) {
    var m = { buckets: {}, rules: rules || {}, tun: tun || JEWEL, maxDevices: 0, maxBuckets: 0, work: {} };
    buckets.forEach(function (b) {
      var alg = b.alg || 'straw2', ws = b.weights.slice();
      var nb = m.buckets[b.id] = { id: b.id, type: b.type, alg: alg, items: b.items.slice(), weights: ws, weight: bucketWeight(alg, ws) };
      if (alg === 'uniform') nb.weights = ws.map(function () { return ws[0]; });
      if (alg === 'list') { var acc = 0; nb.sum = ws.map(function (w) { acc += w; return acc; }); }
      if (alg === 'tree') { var tn = treeNodes(ws); nb.numNodes = tn.numNodes; nb.nodes = tn.nodes; }
      if (alg === 'straw') nb.straws = calcStraws(ws, m.tun.strawCalc == null ? 1 : m.tun.strawCalc);
      m.maxBuckets = Math.max(m.maxBuckets, -b.id);
      b.items.forEach(function (it) { if (it >= m.maxDevices) m.maxDevices = it + 1; });   /* crush_finalize */
    });
    return m;
  }
  function bucket(m, id) { return m.buckets[id]; }
  // src/crush/mapper.c :: is_out (reweight is a probability in 16.16)
  function isOut(weight, item, x) {
    if (item >= weight.length) return true;
    if (weight[item] >= 0x10000) return false;
    if (weight[item] === 0) return true;
    return !((hash2(x, item) & 0xffff) < weight[item]);
  }
  function itemType(m, item) { return item < 0 ? m.buckets[item].type : 0; }

  // src/crush/mapper.c :: crush_choose_firstn (local retries and the permutation fallback are 0 with jewel tunables)
  function chooseFirstn(m, bkt, weight, x, numrep, type, out, ob, outpos, outSize, tries, recurseTries,
                        localRetries, localFallback, recurseToLeaf, varyR, stable, out2, o2b, parentR, trace) {
    var rep, ftotal, flocal, retryDescent, retryBucket, skipRep, inb, r, item = 0, itype, collide, reject, count = outSize;
    for (rep = stable ? 0 : outpos; rep < numrep && count > 0; rep++) {
      ftotal = 0; skipRep = 0;
      do {
        retryDescent = 0; inb = bkt; flocal = 0;
        do {
          collide = 0; retryBucket = 0;
          r = rep + parentR + ftotal;
          var why = '';
          if (inb.items.length === 0) { reject = 1; why = 'empty'; }
          else {
            var info = trace ? [] : null;
            if (localFallback > 0 && flocal >= (inb.items.length >> 1) && flocal > localFallback)
              item = permChoose(inb, work(m, inb), x, r, info);
            else item = bucketChoose(m, inb, x, r, info);
            if (trace) trace.push({ k: 'pick', b: inb.id, alg: inb.alg, r: r, rep: rep, item: item, info: info, inner: out2 === null });
            if (item >= m.maxDevices) { skipRep = 1; break; }
            itype = itemType(m, item);
            if (itype !== type) {
              if (item >= 0 || (-1 - item) >= m.maxBuckets) { skipRep = 1; break; }
              inb = bucket(m, item); retryBucket = 1; continue;
            }
            for (var i = 0; i < outpos; i++) if (out[ob + i] === item) { collide = 1; break; }
            reject = 0;
            if (!collide && recurseToLeaf) {
              if (item < 0) {
                var subR = varyR ? r >> (varyR - 1) : 0;
                if (chooseFirstn(m, bucket(m, item), weight, x, stable ? 1 : outpos + 1, 0, out2, o2b, outpos, count,
                                 recurseTries, 0, localRetries, localFallback, 0, varyR, stable, null, 0, subR, trace) <= outpos)
                  reject = 1;
              } else out2[o2b + outpos] = item;
            }
            if (reject) why = 'leaf';
            if (!reject && !collide && itype === 0) { reject = isOut(weight, item, x) ? 1 : 0; if (reject) why = 'out'; }
          }
          if (reject || collide) {
            ftotal++; flocal++;
            if (trace) trace.push({ k: collide ? 'collide' : 'reject', why: collide ? '' : why, item: item, r: r, ftotal: ftotal });
            if (collide && flocal <= localRetries) retryBucket = 1;
            else if (localFallback > 0 && flocal <= inb.items.length + localFallback) retryBucket = 1;
            else if (ftotal < tries) retryDescent = 1;
            else skipRep = 1;
          }
        } while (retryBucket);
      } while (retryDescent);
      if (skipRep) continue;
      out[ob + outpos] = item; outpos++; count--;
    }
    return outpos;
  }

  // src/crush/mapper.c :: crush_choose_indep (breadth-first, positionally stable; used by erasure-coded pools)
  function chooseIndep(m, bkt, weight, x, left, numrep, type, out, ob, outpos, tries, recurseTries,
                       recurseToLeaf, out2, o2b, parentR, trace) {
    var endpos = outpos + left, rep, ftotal, r, item = 0, itype, collide, inb, i;
    for (rep = outpos; rep < endpos; rep++) { out[ob + rep] = UNDEF; if (out2) out2[o2b + rep] = UNDEF; }
    for (ftotal = 0; left > 0 && ftotal < tries; ftotal++) {
      for (rep = outpos; rep < endpos; rep++) {
        if (out[ob + rep] !== UNDEF) continue;
        inb = bkt;
        for (;;) {
          r = rep + parentR;
          if (inb.alg === 'uniform' && inb.items.length % numrep === 0) r += (numrep + 1) * ftotal;   /* r' = r + (n+1) * f_total */
          else r += numrep * ftotal;                                                              /* r' = r + n * f_total */
          if (inb.items.length === 0) break;
          var info = trace ? [] : null;
          item = bucketChoose(m, inb, x, r, info);
          if (trace) trace.push({ k: 'pick', b: inb.id, alg: inb.alg, r: r, rep: rep, item: item, info: info });
          if (item >= m.maxDevices) { out[ob + rep] = NONE; if (out2) out2[o2b + rep] = NONE; left--; break; }
          itype = itemType(m, item);
          if (itype !== type) {
            if (item >= 0 || (-1 - item) >= m.maxBuckets) { out[ob + rep] = NONE; if (out2) out2[o2b + rep] = NONE; left--; break; }
            inb = bucket(m, item); continue;
          }
          collide = 0;
          for (i = outpos; i < endpos; i++) if (out[ob + i] === item) { collide = 1; break; }
          if (collide) { if (trace) trace.push({ k: 'collide', item: item, r: r }); break; }
          if (recurseToLeaf) {
            if (item < 0) {
              chooseIndep(m, bucket(m, item), weight, x, 1, numrep, 0, out2, o2b, rep, recurseTries, 0, 0, null, 0, r, trace);
              if (out2 && out2[o2b + rep] === NONE) break;
            } else if (out2) out2[o2b + rep] = item;
          }
          if (itype === 0 && isOut(weight, item, x)) { if (trace) trace.push({ k: 'reject', item: item, r: r }); break; }
          out[ob + rep] = item; left--; break;
        }
      }
    }
    for (rep = outpos; rep < endpos; rep++) {
      if (out[ob + rep] === UNDEF) out[ob + rep] = NONE;
      if (out2 && out2[o2b + rep] === UNDEF) out2[o2b + rep] = NONE;
    }
  }

  // src/crush/mapper.c :: crush_do_rule / crush_do_rule_no_retry (non-MSR rules)
  function doRule(m, ruleno, x, resultMax, weight, trace) {
    var rule = m.rules[ruleno]; if (!rule) return [];
    m.work = {};                                    /* crush_init_workspace */
    var t = m.tun, result = [], a = new Array(resultMax), b = new Array(resultMax), c = new Array(resultMax);
    var w = a, o = b, wsize = 0, osize, tmp;
    var chooseTries = t.total + 1, chooseLeafTries = 0, localR = t.local, fallbackR = t.fallback, varyR = t.varyR, stable = t.stable;
    rule.steps.forEach(function (st) {
      var op = st[0], a1 = st[1], a2 = st[2], firstn = 0;
      switch (op) {
        case OP.TAKE: if ((a1 >= 0 && a1 < m.maxDevices) || (a1 < 0 && m.buckets[a1])) { w[0] = a1; wsize = 1; } break;
        case OP.SET_CHOOSE_TRIES: if (a1 > 0) chooseTries = a1; break;
        case OP.SET_CHOOSELEAF_TRIES: if (a1 > 0) chooseLeafTries = a1; break;
        case OP.SET_CHOOSE_LOCAL_TRIES: if (a1 >= 0) localR = a1; break;
        case OP.SET_CHOOSE_LOCAL_FALLBACK_TRIES: if (a1 >= 0) fallbackR = a1; break;
        case OP.SET_CHOOSELEAF_VARY_R: if (a1 >= 0) varyR = a1; break;
        case OP.SET_CHOOSELEAF_STABLE: if (a1 >= 0) stable = a1; break;
        case OP.CHOOSELEAF_FIRSTN: case OP.CHOOSE_FIRSTN: firstn = 1; /* falls through */
        case OP.CHOOSELEAF_INDEP: case OP.CHOOSE_INDEP:
          if (wsize === 0) break;
          var leaf = op === OP.CHOOSELEAF_FIRSTN || op === OP.CHOOSELEAF_INDEP;
          osize = 0;
          for (var i = 0; i < wsize; i++) {
            var numrep = a1;
            if (numrep <= 0) { numrep += resultMax; if (numrep <= 0) continue; }
            if (w[i] >= 0 || !m.buckets[w[i]]) continue;
            if (firstn) {
              var recurseTries = chooseLeafTries ? chooseLeafTries : (t.descendOnce ? 1 : chooseTries);
              osize += chooseFirstn(m, m.buckets[w[i]], weight, x, numrep, a2, o, osize, 0, resultMax - osize,
                                    chooseTries, recurseTries, localR, fallbackR, leaf, varyR, stable, c, osize, 0, trace);
            } else {
              var outSize = numrep < resultMax - osize ? numrep : resultMax - osize;
              chooseIndep(m, m.buckets[w[i]], weight, x, outSize, numrep, a2, o, osize, 0, chooseTries,
                          chooseLeafTries ? chooseLeafTries : 1, leaf, c, osize, 0, trace);
              osize += outSize;
            }
          }
          if (leaf) for (var j = 0; j < osize; j++) o[j] = c[j];
          tmp = o; o = w; w = tmp; wsize = osize;
          break;
        case OP.EMIT:
          for (var k = 0; k < wsize && result.length < resultMax; k++) result.push(w[k]);
          wsize = 0; break;
      }
    });
    return result;
  }

  // src/crush/CrushWrapper.cc :: add_simple_rule_at (firstn: take, chooseleaf/choose, emit; indep adds two tries steps)
  function simpleRule(rootId, typeId, indep) {
    var leaf = typeId !== 0, steps = [];
    if (indep) { steps.push([OP.SET_CHOOSELEAF_TRIES, 5, 0]); steps.push([OP.SET_CHOOSE_TRIES, 100, 0]); }
    steps.push([OP.TAKE, rootId, 0]);
    steps.push([indep ? (leaf ? OP.CHOOSELEAF_INDEP : OP.CHOOSE_INDEP) : (leaf ? OP.CHOOSELEAF_FIRSTN : OP.CHOOSE_FIRSTN), 0, typeId]);
    steps.push([OP.EMIT, 0, 0]);
    return { type: indep ? 3 : 1, steps: steps };
  }
  // src/crush/CrushWrapper.cc :: insert_item: iweight = (int)(weight * (float)0x10000)
  function iweight(w) { return Math.trunc(Math.fround(Math.fround(w) * 65536)); }

  // src/osd/osd_types.cc :: pg_pool_t::raw_pg_to_pps (FLAG_HASHPSPOOL, the default)
  function pps(ps, pgpNum, pool) { return hash2(stableMod(ps, pgpNum, pgMask(pgpNum)), pool); }
  // src/osd/OSDMap.cc :: _pg_to_raw_osds + _raw_to_up_osds + _pick_primary (no pg_temp / primary affinity)
  function pgToUp(m, ruleno, ps, pool, pgpNum, size, weight, down, ec, trace) {
    var x = pps(ps, pgpNum, pool), raw = doRule(m, ruleno, x, size, weight, trace), up;
    if (!ec) up = raw.filter(function (o) { return o !== NONE && !down[o]; });
    else up = raw.map(function (o) { return o === NONE || down[o] ? NONE : o; });
    var primary = -1;
    for (var i = 0; i < up.length; i++) if (up[i] !== NONE) { primary = up[i]; break; }
    return { pps: x, raw: raw, up: up, primary: primary };
  }
  // src/osd/OSDMap.cc :: object_locator_to_pg + pg_pool_t::raw_pg_to_pg (object name -> pg; no namespace)
  function objectToPg(name, pgNum) { var h = strHash(name); return { hash: h, ps: stableMod(h, pgNum, pgMask(pgNum)) }; }

  /* ------------------------------------------------------------ RBD striping */
  // src/osdc/Striper.cc :: Striper::file_to_extents (the lightweight overload); numbers stay below 2^53
  function fileToExtents(layout, offset, len, truncSize, bufferOffset) {
    var os = layout.object_size, su = layout.stripe_unit, sc = layout.stripe_count;
    if (!(len > 0)) throw new Error('len > 0');
    if (os < su) throw new Error('object_size >= stripe_unit');
    if (sc === 1) su = os;
    var spo = Math.floor(os / su), cur = offset, left = len, ex = [];
    bufferOffset = bufferOffset || 0;
    while (left > 0) {
      var blockno = Math.floor(cur / su), stripeno = Math.floor(blockno / sc), stripepos = blockno % sc;
      var objectsetno = Math.floor(stripeno / spo), objectno = objectsetno * sc + stripepos;
      var blockStart = (stripeno % spo) * su, blockOff = cur % su, max = su - blockOff;
      var xOff = blockStart + blockOff, xLen = left > max ? max : left;
      // keep one extent per object, sorted by object number (upper_bound + reverse iterator in the C++)
      var it = 0; while (it < ex.length && ex[it].object_no <= objectno) it++;
      var prev = it > 0 ? ex[it - 1] : null, e;
      if (!prev || prev.object_no !== objectno || prev.offset + prev.length !== xOff) {
        e = { object_no: objectno, offset: xOff, length: xLen, truncate_size: objectTruncateSize(layout, objectno, truncSize || 0), buffer_extents: [] };
        ex.splice(it, 0, e);
      } else { e = prev; e.length += xLen; }
      e.buffer_extents.push([cur - offset + bufferOffset, xLen]);
      left -= xLen; cur += xLen;
    }
    return ex;
  }
  // src/osdc/Striper.cc :: Striper::object_truncate_size
  function objectTruncateSize(l, objectno, trunc) {
    if (trunc === 0 || trunc === -1) return trunc;
    var os = l.object_size, su = l.stripe_unit, sc = l.stripe_count, spo = Math.floor(os / su);
    var objectsetno = Math.floor(objectno / sc), tset = Math.floor(Math.floor(trunc / os) / sc);
    if (objectsetno > tset) return 0;
    if (objectsetno < tset) return os;
    var tblock = Math.floor(trunc / su), tstripe = Math.floor(tblock / sc), tpos = tblock % sc, tobj = tset * sc + tpos;
    if (objectno < tobj) return ((tstripe % spo) + 1) * su;
    if (objectno > tobj) return (tstripe % spo) * su;
    return (tstripe % spo) * su + (trunc % su);
  }
  // src/osdc/Striper.cc :: Striper::get_num_objects (period = object_size * stripe_count)
  function numObjects(l, size) {
    var su = l.stripe_unit, sc = l.stripe_count, period = l.object_size * sc;
    var nper = Math.floor((size + period - 1) / period), rem = size % period, remObjs = 0;
    if (rem > 0 && rem < sc * su) remObjs = sc - Math.floor((rem + su - 1) / su);
    return nper * sc - remObjs;
  }
  // src/osdc/Striper.cc :: Striper::get_file_offset
  function fileOffset(l, objectno, off) {
    var su = l.stripe_unit, sc = l.stripe_count, spo = Math.floor(l.object_size / su);
    var stripepos = objectno % sc, objectsetno = Math.floor(objectno / sc);
    var stripeno = Math.floor(off / su) + objectsetno * spo, blockno = stripeno * sc + stripepos;
    return blockno * su + off % su;
  }
  // src/librbd/ImageCtx.cc :: format_string "%s.%016llx" (format 2) with the object prefix of
  // src/librbd/image/CreateRequest.cc :: create_image, "rbd_data." [+ "<metadata pool id>." with --data-pool] + id
  function rbdDataName(imageId, objectno, mdPool) {
    var h = objectno.toString(16);
    return 'rbd_data.' + (mdPool != null && mdPool !== -1 ? mdPool + '.' : '') + imageId + '.' + '0000000000000000'.slice(h.length) + h;
  }
  // the image's metadata objects (include/rbd_types.h; librbd/Utils.cc :: id_obj_name, header_name;
  // librbd/ObjectMap.cc :: object_map_name for the head, CEPH_NOSNAP); all live in the metadata pool
  function rbdMetaNames(name, imageId) {
    return { directory: 'rbd_directory', id: 'rbd_id.' + name, header: 'rbd_header.' + imageId, objectMap: 'rbd_object_map.' + imageId };
  }
  // src/librbd/Utils.cc :: generate_image_id: hex(client instance id) + hex(32-bit random), no padding,
  // keeping the last RBD_MAX_IMAGE_ID_LENGTH (14) characters
  function rbdImageId(instanceId, extra) {
    var id = instanceId.toString(16) + (extra >>> 0).toString(16);
    return id.length > 14 ? id.slice(id.length - 14) : id;
  }

  /* ------------------------------------------------------------ pg_autoscaler */
  // src/pybind/mgr/pg_autoscaler/module.py :: is_power_of_two / nearest_power_of_two
  function isPow2(v) { return v >= 0 && (v & (v - 1)) === 0; }
  function nearestPow2(n, dir) {
    var v = Math.trunc(n);
    if (isPow2(v)) { if (dir === 'down') return v >= 1 ? v >> 1 : 0; return v; }
    v -= 1; v |= v >> 1; v |= v >> 2; v |= v >> 4; v |= v >> 8; v |= v >> 16; v += 1;
    var x = v >> 1;
    if (dir === 'up') return v;
    if (dir === 'down') return x;
    return (v - n) > (n - x) ? x : v;
  }
  // module.py :: PoolGroup (pools with the same GroupKey are rounded in the same direction)
  function PoolGroup(pgTarget, size, bias, autoscale) { this.pools = []; this.update(pgTarget, size, bias, autoscale); }
  PoolGroup.prototype.update = function (pgTarget, size, bias, autoscale) {
    this.pg_target = Math.trunc(pgTarget * bias);
    var per = this.pg_target / size;
    this.rd_down_val = nearestPow2(per, 'down') * size; this.rd_up_val = nearestPow2(per, 'up') * size;
    this.cost_down_val = Math.abs(this.rd_down_val - this.pg_target); this.cost_up_val = Math.abs(this.rd_up_val - this.pg_target);
    if (!autoscale) { this.rd_down_val = this.rd_up_val = this.pg_target; this.cost_down_val = this.cost_up_val = 0; }
    this.refresh();
  };
  PoolGroup.prototype.refresh = function () {
    var n = this.pools.length;
    this.pg_target_total = this.pg_target * n; this.rd_down_total = this.rd_down_val * n; this.rd_up_total = this.rd_up_val * n;
    this.dev_down_total = this.cost_down_val * n; this.dev_up_total = this.cost_up_val * n;
  };
  PoolGroup.prototype.add = function (p) { this.pools.push(p); this.refresh(); };
  // module.py :: _find_optimal_pg_distribution (knapsack over "round this group up?"); Maps keep Python dict order
  function findOptimal(root, base, cost, groups, backtrack) {
    var budget = root.pg_left - base, parent = [new Map([[0, [cost, 0]]])];
    groups.forEach(function (g, idx) {
      var upCost = g.rd_up_total - g.rd_down_total, prev = parent[idx], next = new Map();
      prev.forEach(function (v, k) { next.set(k, [v[0], k]); });
      prev.forEach(function (v, cur) {
        var nc = cur + upCost, nw = v[0] - g.dev_down_total + g.dev_up_total;
        if (nc <= budget && (!next.has(nc) || nw < next.get(nc)[0])) next.set(nc, [nw, cur]);
      });
      parent.push(next);
    });
    var opt = null;
    parent[parent.length - 1].forEach(function (v, cur) {
      if (!opt || v[0] < opt[1] || (v[0] === opt[1] && cur > opt[0])) opt = [cur, v[0], v[1]];
    });
    var bt = [opt];
    for (var i = parent.length - 2; i > 0; i--) { var last = bt[bt.length - 1], pv = parent[i].get(last[2]); bt.push([last[2], pv[0], pv[1]]); }
    bt.reverse();
    bt.forEach(function (x) { backtrack.push(x); });
  }
  // module.py :: _append_result
  function appendResult(groups, backtrack, out, pgTotal, defaultPgNum) {
    groups.forEach(function (g, i) {
      g.pools.forEach(function (p) {
        var minPg = p.pg_num_min != null ? p.pg_num_min : defaultPgNum, maxPg = p.pg_num_max;
        var poolTarget = Math.trunc(g.pg_target_total / g.pools.length);
        var finTotal = backtrack[i][0] - backtrack[i][2] + g.rd_down_total;
        var fin = finTotal / g.pools.length, perRep = Math.trunc(fin / p.size);
        if (minPg > perRep) { perRep = minPg; fin = minPg * p.size; }
        if (maxPg && maxPg < perRep) { perRep = maxPg; fin = maxPg * p.size; }
        out.push({ p: p, ratio: pgTotal ? fin / pgTotal : 0, ideal: poolTarget, fin: perRep });
      });
    });
  }
  // module.py :: _calculate_final_pool_pg_target (four passes: unmanaged, non-bulk, big bulk, even bulk)
  function finalTargets(root, pass, groupMap, defaultPgNum) {
    var out = [], base = 0, cost = 0, victims = [], bt = [], sel = [];
    if (!groupMap.size) return out;
    groupMap.forEach(function (g, key) {
      var k = JSON.parse(key);
      var take = pass === 'first' ? !k[4] : pass === 'second' ? !k[3] :
                 pass === 'third' ? (g.pg_target_total / g.pools.length / root.pg_left > 1 / (root.pool_count - root.pool_used) && k[3]) : true;
      if (pass === 'third' && root.pg_left === 0) take = false;
      if (!take) return;
      if (pass === 'first') g.pools.forEach(function (p) { g.update(p.pg_num_target * k[1], k[1], k[2], k[4]); });
      sel.push([key, g]);
    });
    if (pass === 'third' && root.pg_left === 0) return out;
    if (pass === 'fourth') {
      var fr = 1 / (root.pool_count - root.pool_used);
      sel.forEach(function (kg) { var k = JSON.parse(kg[0]); kg[1].update(Math.trunc(fr * root.pg_left), k[1], k[2], k[4]); });
    }
    sel.forEach(function (kg) { base += kg[1].rd_down_total; cost += kg[1].dev_down_total; root.pool_used += kg[1].pools.length; victims.push(kg[0]); });
    var groups = sel.map(function (kg) { return kg[1]; });
    findOptimal(root, base, cost, groups, bt);
    appendResult(groups, bt, out, root.pg_target, defaultPgNum);
    victims.forEach(function (k) { groupMap.delete(k); });
    return out;
  }
  // module.py :: get_dynamic_threshold
  function dynThreshold(fin, def) { return fin === 512 || fin === 1024 ? 1.0 : fin === 2048 ? 2.0 : def; }
  // module.py :: _get_pool_status for one CRUSH root: pools [{name,size,ratio,bulk,autoscale,pg_num}]
  function autoscale(osds, targetPerOsd, pools, opts) {
    opts = opts || {};
    var thr = opts.threshold || 3.0, defPg = opts.defaultPgNum || 32;
    var root = { pg_target: targetPerOsd * osds, pg_left: targetPerOsd * osds, pool_count: pools.length, pool_used: 0 };
    var groups = new Map(), res = {};
    pools.forEach(function (q, i) {
      var p = { pool: i, pool_name: q.name, size: q.size, pg_num_target: q.pg_num, autoscale: q.autoscale !== false };
      var pgt = p.autoscale ? Math.trunc(q.ratio * root.pg_left) : q.pg_num * q.size;
      var key = JSON.stringify([pgt, q.size, 1.0, !!q.bulk, p.autoscale]);
      if (!groups.has(key)) groups.set(key, new PoolGroup(pgt, q.size, 1.0, p.autoscale));
      groups.get(key).add(p);
    });
    ['first', 'second', 'third', 'fourth'].forEach(function (pass) {
      var rows = finalTargets(root, pass, groups, defPg), fail = false, recs = [];
      rows.forEach(function (r) {
        root.pg_left -= r.fin * r.p.size;
        if (root.pg_left < 0) fail = true;
        var adj = r.fin > r.p.pg_num_target ? r.fin > r.p.pg_num_target * dynThreshold(r.fin, thr) : r.fin < r.p.pg_num_target / thr;
        adj = !!(adj && r.ratio >= 0 && r.ratio <= 1 && r.p.autoscale);
        recs.push({ name: r.p.pool_name, pass: pass, pg: r.fin, ratio: r.ratio, ideal: r.ideal, adjust: adj });
      });
      recs.forEach(function (x) { if (fail) x.adjust = false; res[x.name] = x; });
    });
    return { pg_target: root.pg_target, pg_left: root.pg_left, pools: pools.map(function (q) { return res[q.name]; }) };
  }
  // the classic pgcalc rule (docs: "PG calculator"): (target per OSD * OSDs * %data) / size, nearest power of two,
  // but the next power up if the nearest is more than 25% below the raw value; never below OSDs / size
  function pgcalc(targetPerOsd, osds, share, size) {
    var raw = targetPerOsd * osds * share / size;
    if (raw < osds / size) raw = osds / size;
    var p = nearestPow2(raw, 'nearest');
    if (p < raw * 0.75) p = nearestPow2(raw, 'up');
    return { raw: raw, pg: Math.max(1, p) };
  }

  /* ------------------------------------------------------------ erasure coding and replication */
  // src/mon/OSDMonitor.cc :: prepare_pool_size (EC: size = k + m, min_size = k + min(1, m - 1));
  // replicated min_size = size - size / 2 when osd_pool_default_min_size = 0 (pg_pool_t / OSDMonitor)
  function ecPool(k, m, plugin, extra) {
    var size = k + m, chunks = size;
    if (plugin === 'lrc') { var l = extra.l; chunks = k + m + Math.ceil((k + m) / l); size = chunks; }
    var minSize = k + Math.min(1, m - 1);
    var repair, helpers;
    if (plugin === 'lrc') { repair = extra.l; helpers = extra.l; }
    else if (plugin === 'clay') { var d = extra.d; helpers = d; repair = d / (d - k + 1); }
    else if (plugin === 'shec') { helpers = Math.ceil(k * extra.c / m); repair = helpers; }
    else { helpers = k; repair = k; }
    return { size: size, chunks: chunks, minSize: minSize, eff: k / chunks, overhead: chunks / k, tolerate: plugin === 'shec' ? extra.c : m,
             ioTolerate: Math.max(0, size - minSize), repairRead: repair, helpers: helpers };
  }
  function repPool(size) { var minSize = size - Math.floor(size / 2); return { size: size, minSize: minSize, eff: 1 / size, overhead: size, tolerate: size - 1, ioTolerate: size - minSize, repairRead: 1, helpers: 1 }; }

  /* ------------------------------------------------------------ RGW object layout */
  // the book's reading of src/rgw/rgw_obj_manifest.cc :: RGWObjManifest::get_implicit_location (chapter 4)
  function rgwLayout(key, size, opts) {
    opts = opts || {};
    var head = opts.head == null ? 4 << 20 : opts.head, stripe = opts.stripe || (4 << 20), marker = opts.marker || 'MARKER';
    var objs = [], ofs;
    if (!opts.parts) {
      var prefix = '.' + (opts.rand || 'RAND32') + '_';
      objs.push({ ns: 'head', name: marker + '_' + key, len: Math.min(size, head), meta: true });
      for (ofs = head, opts.n = 1; ofs < size; ofs += stripe, opts.n++)
        objs.push({ ns: 'shadow', name: marker + '__shadow_' + prefix + opts.n, len: Math.min(stripe, size - ofs) });
      return objs;
    }
    objs.push({ ns: 'head', name: marker + '_' + key, len: 0, meta: true });
    var upload = opts.upload || 'UPLOADID';
    opts.parts.forEach(function (plen, i) {
      var part = i + 1, pfx = key + '.' + upload;
      objs.push({ ns: 'multipart', name: marker + '__multipart_' + pfx + '.' + part, len: Math.min(plen, stripe), part: part });
      for (var o = stripe, n = 1; o < plen; o += stripe, n++)
        objs.push({ ns: 'shadow', name: marker + '__shadow_' + pfx + '.' + part + '_' + n, len: Math.min(stripe, plen - o), part: part });
    });
    return objs;
  }

  /* ------------------------------------------------------------ RGW bucket index shard */
  // src/common/ceph_hash.cc :: ceph_str_hash_linux (32-bit unsigned arithmetic)
  function strHashLinux(str) {
    var b = utf8(str), hsh = 0;
    for (var i = 0; i < b.length; i++) { var c = b[i]; hsh = Math.imul((hsh + (c << 4) + (c >> 4)) >>> 0, 11) >>> 0; }
    return hsh >>> 0;
  }
  // src/rgw/services/svc_bi_rados.h :: RGWSI_BucketIndex_RADOS::bucket_shard_index + rgw_tools.h :: rgw_shards_mod
  function bucketShardIndex(key, n) {
    if (n <= 0) return -1;
    var sid = strHashLinux(key), sid2 = (sid ^ ((sid & 0xff) << 24)) >>> 0;
    return n <= 7877 ? sid2 % 7877 % n : sid2 % 65521 % n;
  }

  /* ------------------------------------------------------------ BlueStore write decisions */
  // src/os/bluestore/BlueStore.cc (classic path; bluestore_write_v2 defaults to false):
  //   _do_write_data cuts a write at min_alloc_size into an unaligned head, an aligned middle and an unaligned tail;
  //   _do_write_small: an overwrite of allocated space in a mutable blob becomes a deferred overwrite (reading the
  //     rest of the disk block first if the write is not block aligned); new data goes to a new blob;
  //   _do_write_big: an overwrite of up to 2 * prefer_deferred_size that fits existing blobs is deferred, otherwise
  //     the middle goes to new blobs;
  //   _do_alloc_write: one decision for all new blobs of the write: deferred if data_size < prefer_deferred_size,
  //     otherwise allocate (min_alloc_size units) and write directly with aio before the KV commit.
  function bluestoreWrite(off, len, o) {
    var mas = o.minAlloc, pds = o.preferDeferred, blk = o.block || 4096, end = off + len, pieces = [];
    function add(kind, a, l) { if (l) pieces.push({ kind: kind, off: a, len: l }); }
    if (Math.floor(off / mas) === Math.floor((end - 1) / mas) && len !== mas) add('small', off, len);
    else {
      var headLen = (mas - off % mas) % mas, tailOff = Math.floor(end / mas) * mas, tailLen = end % mas;
      add('small', off, headLen); add('big', off + headLen, len - headLen - tailLen); add('small', tailOff, tailLen);
    }
    var newData = 0;
    pieces.forEach(function (p) {
      p.readPenalty = 0;
      if (o.overwrite && p.kind === 'small') {
        p.path = 'over'; p.deferred = true;
        var hr = p.off % blk, tr = (blk - (p.off + p.len) % blk) % blk;
        p.readPenalty = hr + tr; p.disk = p.len + hr + tr;
      } else if (o.overwrite && p.kind === 'big' && pds && p.len <= 2 * pds) {
        p.path = 'bigover'; p.deferred = true; p.disk = p.len;
      } else {
        p.path = 'new';
        p.disk = Math.ceil((p.off + p.len) / blk) * blk - Math.floor(p.off / blk) * blk;   /* padded to the disk block */
        newData += p.disk;
      }
    });
    var deferNew = newData > 0 && newData < pds;
    pieces.forEach(function (p) {
      if (p.path === 'new') { p.deferred = deferNew; p.alloc = Math.ceil(p.disk / mas) * mas; } else p.alloc = 0;
    });
    return { pieces: pieces, newData: newData, deferNew: deferNew };
  }

  var API = {
    hash2: hash2, hash3: hash3, hash4: hash4, ALG: ALG, calcStraws: calcStraws, treeNodes: treeNodes, bucketChoose: bucketChoose, strHash: strHash, stableMod: stableMod, pgMask: pgMask, crushLn: crushLn, expDraw: expDraw,
    NONE: NONE, OP: OP, JEWEL: JEWEL, makeMap: makeMap, doRule: doRule, simpleRule: simpleRule, iweight: iweight,
    pps: pps, pgToUp: pgToUp, objectToPg: objectToPg,
    fileToExtents: fileToExtents, objectTruncateSize: objectTruncateSize, numObjects: numObjects, fileOffset: fileOffset, rbdDataName: rbdDataName, rbdMetaNames: rbdMetaNames, rbdImageId: rbdImageId,
    nearestPow2: nearestPow2, autoscale: autoscale, pgcalc: pgcalc, ecPool: ecPool, repPool: repPool, rgwLayout: rgwLayout, strHashLinux: strHashLinux, bucketShardIndex: bucketShardIndex,
    bluestoreWrite: bluestoreWrite
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = API; else root.SimCore = API;
})(typeof self !== 'undefined' ? self : this);
