/* The balancer: upmap and crush-compat (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * upmap mode is a port of OSDMap::calc_pg_upmaps and the helpers it calls (src/osd/OSDMap.cc: build_pool_pgs_info,
 * get_osds_weight, calc_deviations, fill_overfull_underfull, try_drop_remap_overfull, try_drop_remap_underfull,
 * try_pg_upmap, find_best_remap, add_remap_pair, build_candidates_by_osd, pack_upmap_results, get_random_engine,
 * _apply_upmap) and of CrushWrapper::try_remap_rule, _choose_type_stack and get_rule_weight_osd_map
 * (src/crush/CrushWrapper.cc), with the float arithmetic, the container orders and libstdc++'s std::shuffle over
 * std::default_random_engine kept, so the same input gives the same pg-upmap-items as Ceph (tests/sims/golden-labs.json).
 * crush-compat mode follows do_crush_compat and calc_eval of src/pybind/mgr/balancer/module.py with the pgs metric. */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, C = h.C, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, pct = h.pct, sel = h.sel, field = h.field, stat = h.stat, numIn = h.numIn, clamp = h.clamp;
  var f = Math.fround, NONE = 0x7fffffff, IN = 0x10000;

  /* ---------------- libstdc++: std::default_random_engine (minstd_rand0), uniform_int_distribution, std::shuffle */
  function engine(seed) {
    var x = (seed >>> 0) % 2147483647; if (x === 0) x = 1;
    return function () { x = (16807 * x) % 2147483647; return x; };
  }
  function uniform(g, a, b) {                       // urng range 2147483645 > b - a: the downscaling branch
    var uer = b - a + 1, scaling = Math.floor(2147483645 / uer), past = uer * scaling, r;
    do { r = g() - 1; } while (r >= past);
    return Math.floor(r / scaling) + a;
  }
  function shuffle(v, g) {                          // bits/stl_algo.h: two swaps per draw while the range allows it
    var n = v.length, i, t;
    if (!n) return;
    function sw(p, q) { t = v[p]; v[p] = v[q]; v[q] = t; }
    if (Math.floor(2147483645 / n) >= n) {
      i = 1;
      if (n % 2 === 0) { sw(i, uniform(g, 0, 1)); i++; }
      while (i !== n) {
        var r = i + 1, x = uniform(g, 0, r * (r + 1) - 1);
        sw(i, Math.floor(x / (r + 1))); i++;
        sw(i, x % (r + 1)); i++;
      }
      return;
    }
    for (i = 1; i < n; i++) sw(i, uniform(g, 0, i));
  }

  /* ---------------- the OSD map: root -1 > hosts -2-h > OSDs; raw CRUSH output per PG; pg_upmap_items */
  // M = { host: [h per osd], cw: [16.16 crush weight], rw: [16.16 reweight], size, pgnum, leaf (failure domain host), raw: [[osd]], items: {ps: [[from, to]]} }
  function parentOf(M, item) { return item >= 0 && item < M.host.length ? -2 - M.host[item] : item <= -2 ? -1 : null; }
  function typeOf(item) { return item >= 0 ? 0 : item === -1 ? 11 : 1; }
  function parentOfType(M, item, type) {            // stand-in for get_parent_of_type on a plain tree; 0 when there is none
    do { item = parentOf(M, item); if (item == null) return 0; } while (typeOf(item) !== type);
    return item;
  }
  function subtreeContains(M, rootId, item) { for (;;) { if (item === rootId) return true; item = parentOf(M, item); if (item == null) return false; } }
  function sortNum(a) { return a.sort(function (x, y) { return x - y; }); }
  function keys(o) { return sortNum(Object.keys(o).map(Number)); }
  // OSDMap::_apply_upmap (pg_upmap_items part; no pg_upmap or primaries here)
  function applyUpmap(M, items, ps) {
    var raw = M.raw[ps].slice(), q = items[ps];
    if (q) q.forEach(function (p) {
      var exists = false, pos = -1;
      for (var i = 0; i < raw.length; i++) {
        if (raw[i] === p[1]) { exists = true; break; }
        if (raw[i] === p[0] && pos < 0 && !(p[1] !== NONE && p[1] < M.host.length && p[1] >= 0 && M.rw[p[1]] === 0)) pos = i;
      }
      if (!exists && pos >= 0) raw[pos] = p[1];
    });
    return raw;
  }
  function upOf(M, items, ps) { return applyUpmap(M, items, ps).filter(function (o) { return o !== NONE; }); }
  function counts(M, items) {
    var c = M.host.map(function () { return 0; });
    for (var ps = 0; ps < M.pgnum; ps++) upOf(M, items, ps).forEach(function (o) { c[o]++; });
    return c;
  }
  // CrushWrapper::_get_take_weight_osd_map (breadth first from the root) + _normalize_weight_map, then get_osds_weight
  function osdWeights(M) {
    var m = {}, sum = 0, nh = Math.max.apply(null, M.host) + 1;
    for (var hh = 0; hh < nh; hh++) for (var o = 0; o < M.host.length; o++) if (M.host[o] === hh) { m[o] = f(M.cw[o]); sum = f(sum + m[o]); }
    var w = {}, total = 0;
    keys(m).forEach(function (o) {
      var nw = sum > 0 ? f(m[o] / sum) : 0, adj = f(f(f(M.rw[o]) / f(IN)) * nw);
      if (adj !== 0) { w[o] = f((w[o] || 0) + adj); total = f(total + adj); }
    });
    return { w: w, total: total };
  }
  function cloneSets(p) { var o = {}; for (var k in p) o[k] = new Set(p[k]); return o; }
  function at(p, k) { return p[k] || (p[k] = new Set()); }
  // OSDMap::calc_deviations: deviation_osd is a multimap<float,int> filled in OSD order (ties keep that order)
  function calcDeviations(pgsByOsd, w, ppw) {
    var cur = 0, score = 0, dev = {}, order = [];
    keys(pgsByOsd).forEach(function (o) {
      var weight = w[o], pgs = f(pgsByOsd[o].size), target = f(weight * ppw), d = f(pgs - target);
      dev[o] = d; order.push([d, o]);
      var rel = d / target; score += rel * rel * weight;
      if (Math.abs(d) > cur) cur = Math.abs(d);
    });
    order.sort(function (a, b) { return a[0] - b[0]; });
    return { dev: dev, order: order, score: score, max: cur };
  }
  function fillOverUnder(order, maxDev) {
    var r = { over: new Set(), moreOver: new Set(), under: [], moreUnder: [] }, i;
    for (i = order.length - 1; i >= 0; i--) { if (order[i][0] <= 0) break; (order[i][0] > maxDev ? r.over : r.moreOver).add(order[i][1]); }
    for (i = 0; i < order.length; i++) { if (order[i][0] >= 0) break; if (order[i][0] < -maxDev) r.under.push(order[i][1]); else r.moreUnder.push(order[i][1]); }
    return r;
  }
  // CrushWrapper::_choose_type_stack
  function chooseTypeStack(M, stack, over, under, moreUnder, orig, it, used, w0, rootBucket) {
    var w = w0.slice(), cum = [], fo = 1, j, k;
    for (j = stack.length - 1; j >= 0; --j) { cum[j] = fo; fo *= stack[j][1]; }
    var ub = []; for (j = 0; j < stack.length - 1; j++) ub.push(new Set());
    under.forEach(function (osd) {
      var item = osd;
      for (var jj = stack.length - 2; jj >= 0; --jj) {
        item = parentOfType(M, item, stack[jj][0]);
        if (!subtreeContains(M, rootBucket, item)) continue;
        ub[jj].add(item);
      }
    });
    for (j = 0; j < stack.length; ++j) {
      var type = stack[j][0], fanout = stack[j][1], cf = cum[j], o = [], tmpi = it.i;
      if (it.i === orig.length) break;
      for (var wi = 0; wi < w.length; wi++) {
        var from = w[wi], leaves = [];
        for (k = 0; k < fanout; k++) leaves.push(new Set());
        for (var pos = 0; pos < fanout; ++pos) {
          if (type > 0) {
            o.push(parentOfType(M, orig[tmpi], type));
            var n = cf;
            while (n-- && tmpi !== orig.length) leaves[pos].add(orig[tmpi++]);
          } else {
            var replaced = false;
            if (over.has(orig[it.i])) {
              [under, moreUnder].forEach(function (list) {
                if (replaced) return;
                for (var u = 0; u < list.length; u++) {
                  var item = list[u];
                  if (used.has(item) || !subtreeContains(M, from, item) || orig.indexOf(item) >= 0) continue;
                  o.push(item); used.add(item); replaced = true; it.i++; break;
                }
              });
            }
            if (!replaced) { o.push(orig[it.i]); it.i++; }
            if (it.i === orig.length) break;
          }
        }
        if (j + 1 < stack.length) {
          for (pos = 0; pos < fanout; ++pos) {
            if (ub[j].has(o[pos])) continue;
            var anyOver = false;
            leaves[pos].forEach(function (x) { if (over.has(x)) anyOver = true; });
            if (!anyOver) continue;
            var alts = sortNum(Array.from(ub[j]));
            for (k = 0; k < alts.length; k++) {
              if (o.indexOf(alts[k]) >= 0) continue;
              if (j === 0 || parentOfType(M, o[pos], stack[j - 1][0]) === parentOfType(M, alts[k], stack[j - 1][0])) { o[pos] = alts[k]; break; }
            }
          }
        }
        if (it.i === orig.length) break;
      }
      w = o;
    }
    return w;
  }
  // CrushWrapper::try_remap_rule for "take root; chooseleaf firstn 0 type host | choose firstn 0 type osd; emit"
  function tryRemapRule(M, over, under, moreUnder, orig) {
    var it = { i: 0 }, used = new Set(), out = [], w = [-1];
    var stack = M.leaf ? [[1, M.size], [0, 1]] : [[0, M.size]];
    w = chooseTypeStack(M, stack, over, under, moreUnder, orig, it, used, w, -1);
    return out.concat(w);
  }
  function tryPgUpmap(M, over, under, moreUnder, orig) {
    if (!orig.some(function (o) { return over.has(o); })) return null;
    var out = tryRemapRule(M, over, under, moreUnder, orig);
    if (out.length === orig.length && out.every(function (o, i) { return o === orig[i]; })) return null;
    return out;
  }
  function findBestRemap(orig, out, existing, dev) {
    var best = -1, max = 0;
    for (var i = 0; i < out.length; i++) {
      if (orig[i] === out[i] || existing.has(orig[i]) || existing.has(out[i])) continue;
      if (dev[orig[i]] > max) { max = dev[orig[i]]; best = i; }
    }
    return best;
  }
  function tryDropOverfull(items, pgs, osd, temp, toUnmap, toUpmap, dev) {
    var od = dev[osd];
    for (var a = 0; a < pgs.length; a++) {
      var pg = pgs[a], p = items[pg]; if (!p) continue;
      var nu = [];
      p.forEach(function (pr) { if (pr[1] === osd && f(dev[pr[0]] + 1) < od) { at(temp, pr[1]).delete(pg); at(temp, pr[0]).add(pg); } else nu.push(pr); });
      if (!nu.length) { toUnmap.add(pg); return true; }
      if (nu.length !== p.length) { toUpmap[pg] = nu; return true; }
    }
    return false;
  }
  function tryDropUnderfull(cands, osd, temp, toUnmap, toUpmap) {
    for (var a = 0; a < cands.length; a++) {
      var pg = cands[a][0], p = cands[a][1], nu = [];
      p.forEach(function (pr) { if (pr[0] === osd) { at(temp, pr[1]).delete(pg); at(temp, pr[0]).add(pg); } else nu.push(pr); });
      if (!nu.length) { toUnmap.add(pg); return true; }
      if (nu.length !== p.length) { toUpmap[pg] = nu; return true; }
    }
    return false;
  }
  // OSDMap::calc_pg_upmaps for one pool. opt: {aggr, fast, retries}; rng: {seed, n} (get_random_engine's counter)
  function calcPgUpmaps(M, items0, maxDeviation, max, opt, rng) {
    var inc = { unmap: new Set(), upmap: {} }, items = {}, k;
    for (k in items0) items[k] = items0[k];
    if (maxDeviation < 1) maxDeviation = 1;
    var numChanged = 0;
    if (max <= 0) return { n: 0, inc: inc };
    var pgsByOsd = {}, ps, totalPgs = 0;
    for (ps = 0; ps < M.pgnum; ps++) upOf(M, items, ps).forEach(function (o) { at(pgsByOsd, o).add(ps); });
    totalPgs += M.size * M.pgnum;
    var ow = osdWeights(M), wTotal = f(0 + ow.total), w = ow.w;
    keys(w).forEach(function (o) { at(pgsByOsd, o); });
    if (wTotal === 0) return { n: 0, inc: inc };
    var ppw = f(totalPgs / wTotal);
    var cd = calcDeviations(pgsByOsd, w, ppw), score = cd.score, dev = cd.dev, order = cd.order;
    if (cd.max <= maxDeviation) return { n: 0, inc: inc, perfect: true };
    var skipOver = false, aggr = !!opt.aggr, fast = aggr && !!opt.fast, retries = opt.retries;
    var rand = function () { return engine((rng.seed + rng.n++) >>> 0); };
    var done = false;
    while (!done && max--) {
      var fo = fillOverUnder(order, maxDeviation), over = fo.over, under = fo.under, moreUnder = fo.moreUnder, usingMore = false;
      if (!under.length && !over.size) break;
      if (!over.size && under.length) { over = new Set(fo.moreOver); usingMore = true; }
      var toSkip = new Set(), retried = 0, nChanges = 0, prevN = 0, osdToSkip = new Set();
      for (;;) {   // retry:
        var toUnmap = new Set(), toUpmap = {}, temp = cloneSets(pgsByOsd), found = false, j;
        outer:
        for (j = order.length - 1; j >= 0; j--) {
          if (skipOver && under.length) break;
          var osd = order[j][1], deviation = order[j][0];
          if (fast && osdToSkip.has(osd)) continue;
          if (deviation < 0) break;
          if (!usingMore && deviation <= maxDeviation) break;
          var pgs = sortNum(Array.from(at(pgsByOsd, osd))).filter(function (pg) { return !toSkip.has(pg); });
          if (aggr) shuffle(pgs, rand());
          if (tryDropOverfull(items, pgs, osd, temp, toUnmap, toUpmap, dev)) { found = true; break; }
          for (var a = 0; a < pgs.length; a++) {
            var pg = pgs[a], nu = [], existing = new Set(), cur = items[pg];
            if (cur) {
              if (cur.length >= M.size) continue;
              nu = cur.slice(); cur.forEach(function (pr) { existing.add(pr[0]); existing.add(pr[1]); });
            }
            var orig = applyUpmap(M, items, pg), out = tryPgUpmap(M, over, under, moreUnder, orig);
            if (!out || orig.length !== out.length) continue;
            var pos = findBestRemap(orig, out, existing, dev);
            if (pos !== -1) {   // add_remap_pair
              existing.add(orig[pos]); existing.add(out[pos]);
              at(temp, orig[pos]).delete(pg); at(temp, out[pos]).add(pg);
              nu.push([orig[pos], out[pos]]); toUpmap[pg] = nu;
              found = true; break outer;
            }
          }
          if (fast) { if (prevN === nChanges) osdToSkip.add(osd); else prevN = nChanges; }
        }
        if (!found) {
          var cands = [], byOsd = {};
          keys(items).forEach(function (pg) { if (!toSkip.has(pg)) cands.push([pg, items[pg]]); });
          if (aggr) shuffle(cands, rand());
          cands.forEach(function (c) { c[1].forEach(function (pr) { (byOsd[pr[0]] = byOsd[pr[0]] || []).push(c); }); });
          for (j = 0; j < order.length; j++) {
            if (under.indexOf(order[j][1]) < 0) break;
            if (Math.abs(order[j][0]) < maxDeviation) break;
            var cs = byOsd[order[j][1]];
            if (cs && tryDropUnderfull(cs, order[j][1], temp, toUnmap, toUpmap)) { found = true; break; }
          }
        }
        if (!found) {
          if (!aggr || !skipOver) { done = true; break; }
          skipOver = false; break;
        }
        // test_change
        var nd = calcDeviations(temp, w, ppw);
        if (nd.score > score) {
          if (!aggr) { done = true; break; }
          retried++;
          if (retried >= retries) { skipOver = !skipOver; break; }
          toUnmap.forEach(function (x) { toSkip.add(x); });
          keys(toUpmap).forEach(function (x) { toSkip.add(x); });
          continue;   // goto retry
        }
        score = nd.score; pgsByOsd = temp; dev = nd.dev; order = nd.order; nChanges++;
        sortNum(Array.from(toUnmap)).forEach(function (x) { delete items[x]; inc.unmap.add(x); numChanged++; });
        keys(toUpmap).forEach(function (x) { items[x] = toUpmap[x]; inc.upmap[x] = toUpmap[x]; numChanged++; });
        if (nd.max <= maxDeviation) done = true;
        break;
      }
    }
    return { n: numChanged, inc: inc };
  }
  function applyInc(items, inc) {
    inc.unmap.forEach(function (x) { delete items[x]; });
    for (var x in inc.upmap) items[x] = inc.upmap[x];
  }

  /* ---------------- crush-compat: do_crush_compat / calc_eval of the mgr balancer module (pgs metric) */
  function erf(x) {   // Abramowitz and Stegun 7.1.26 (|error| < 1.5e-7); the module calls math.erf
    var s = x < 0 ? -1 : 1; x = Math.abs(x);
    var t = 1 / (1 + 0.3275911 * x);
    return s * (1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x));
  }
  function evalScore(cnt, target) {   // Eval.calc_stats for one metric; every PG carries the same data, so pgs, objects and bytes agree
    var ids = keys(target), num = Math.max(ids.length, 1), total = 0;
    ids.forEach(function (o) { total += cnt[o] || 0; });
    if (!total) return 0;
    var avg = total / num, score = 0, sw = 0;
    ids.forEach(function (o) {
      var adj = target[o] ? (cnt[o] || 0) / target[o] / num : 0;
      if (adj > avg) { score += target[o] * erf(((adj - avg) / avg) / Math.SQRT2); sw += target[o]; }
    });
    return score / Math.max(sw, 1);
  }
  function targets(M) {
    var t = {}, s = 0;
    M.cw.forEach(function (w, o) { if (M.rw[o] > 0 && w > 0) { t[o] = w / IN * M.rw[o] / IN; s += t[o]; } });
    for (var o in t) t[o] /= s;
    return t;
  }

  /* ---------------- the lab's cluster: CRUSH places the PGs (sim-core.js, tested against mapper.c) */
  var SIZES = { same: function () { return 4; }, newhost: function (h, i, H) { return h === H - 1 ? 8 : 4; }, mixed: function (h, i) { return [4, 8, 4, 12][(h + i) % 4]; } };
  function tib(tb) { return tb * 1e12 / Math.pow(2, 40); }
  function cluster(st) {
    var host = [], tbs = [];
    for (var hh = 0; hh < st.hosts; hh++) for (var i = 0; i < st.per; i++) { host.push(hh); tbs.push(SIZES[st.sizes](hh, i, st.hosts)); }
    var cw = tbs.map(function (tb) { return C.iweight(tib(tb)); });
    return { host: host, tbs: tbs, cw: cw, rw: host.map(function () { return IN; }), size: Math.min(st.size, st.fd === 'host' ? st.hosts : host.length), pgnum: st.pgnum, leaf: st.fd === 'host' };
  }
  function place(M, ws) {   // ws: the compat weight-set (TiB per OSD) or null for the crush weights
    var nh = Math.max.apply(null, M.host) + 1, buckets = [], hw = [];
    for (var hh = 0; hh < nh; hh++) {
      var items = [], wts = [];
      M.host.forEach(function (x, o) { if (x === hh) { items.push(o); wts.push(ws ? C.iweight(ws[o]) : M.cw[o]); } });
      buckets.push({ id: -2 - hh, type: 1, items: items, weights: wts });
      hw.push(wts.reduce(function (a, b) { return a + b; }, 0));
    }
    buckets.unshift({ id: -1, type: 11, items: buckets.map(function (b) { return b.id; }), weights: hw });
    var m = C.makeMap(buckets, { 0: C.simpleRule(-1, M.leaf ? 1 : 0, false) }), raw = [];
    for (var ps = 0; ps < M.pgnum; ps++) raw.push(C.doRule(m, 0, C.pps(ps, M.pgnum, 1), M.size, M.rw));
    return raw;
  }
  function pgid(ps) { return '1.' + ps.toString(16); }
  // one mgr round of crush-compat: up to crush_compat_max_iterations steps, keep the best weight-set
  function crushCompat(M, ws0, rnd) {
    var target = targets(M), base = counts(M, {}), basePlace = M.raw, step = 0.5, left = 25, bad = 0, maxMis = 0.05;
    var pe = evalScore(base, target), best = { ws: ws0.slice(), score: pe, raw: M.raw }, next = ws0.slice();
    if (pe === 0) return null;
    var rootW = M.cw.reduce(function (a, b) { return a + b; }, 0) / IN;
    while (left > 0) {
      var act = counts({ host: M.host, raw: best.raw, pgnum: M.pgnum, rw: M.rw }, {}), tot = act.reduce(function (a, b) { return a + b; }, 0);
      var actual = act.map(function (c) { return c / Math.max(tot, 1); });
      keys(target).sort(function (a, b) { return Math.abs(target[b] - actual[b]) - Math.abs(target[a] - actual[a]); }).some(function (o) {
        var d = target[o] - actual[o];
        if (d === 0) return true;
        var calc = actual[o] > 0 ? target[o] / actual[o] * best.ws[o] * 1 : target[o];
        next[o] = best.ws[o] * (1 - step) + calc * step;
        return false;
      });
      var sum = next.reduce(function (a, b) { return a + b; }, 0);
      if (sum > 0 && rootW > 0) next = next.map(function (x) { return x / (sum / rootW); });
      var raw = place(M, next), mis = 0;
      raw.forEach(function (r, ps) { if (r.join() !== basePlace[ps].join()) mis++; });
      var sc = evalScore(counts({ host: M.host, raw: raw, pgnum: M.pgnum, rw: M.rw }, {}), target);
      if (mis / M.pgnum > maxMis) {
        if (best.score < pe) break;
        step /= 2; next = best.ws.slice();
      } else if (sc > best.score * 1.0001) {
        bad++;
        if (!(bad < 5 && rnd() * 101 < 70)) { step /= 2; next = best.ws.slice(); }
      } else {
        bad = 0; best = { ws: next.slice(), score: sc, raw: raw };
        if (sc === 0) break;
      }
      left--;
    }
    return best.score < pe ? best : null;
  }
  function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }

  function fresh(st) {
    var M = cluster(st);
    M.raw = place(M, null);
    st.M = M; st.items = {}; st.ws = M.cw.map(function (w) { return w / IN; }); st.rng = { seed: 42, n: 0 }; st.round = 0; st.cmds = []; st.moved = 0; st.total = 0; st.note = '';
    st.start = stats(M, {});
    return st;
  }
  function stats(M, items) {
    var c = counts(M, items), ow = osdWeights(M), ppw = f(M.size * M.pgnum / ow.total), max = 0, sq = 0;
    var tg = c.map(function (x, o) { return ow.w[o] ? f(ow.w[o] * ppw) : 0; });
    c.forEach(function (x, o) { var d = x - tg[o]; if (Math.abs(d) > max) max = Math.abs(d); sq += d * d; });
    return { c: c, tg: tg, max: max, sd: Math.sqrt(sq / c.length), min: Math.min.apply(null, c), hi: Math.max.apply(null, c) };
  }
  function round(st) {
    var M = st.M, before = st.items, cmds = [];
    st.round++;
    if (st.mode === 'upmap') {
      var r = calcPgUpmaps(M, before, st.maxdev, st.maxopt, { aggr: st.aggr, fast: true, retries: 100 }, st.rng);
      var it = {}; for (var k in before) it[k] = before[k];
      var oldUp = []; for (var ps = 0; ps < M.pgnum; ps++) oldUp.push(upOf(M, it, ps).join());
      applyInc(it, r.inc);
      sortNum(Array.from(r.inc.unmap)).forEach(function (x) { if (!r.inc.upmap[x]) cmds.push('ceph osd rm-pg-upmap-items ' + pgid(x)); });
      keys(r.inc.upmap).forEach(function (x) { cmds.push('ceph osd pg-upmap-items ' + pgid(x) + ' ' + r.inc.upmap[x].map(function (p) { return p[0] + ' ' + p[1]; }).join(' ')); });
      st.items = it; st.moved = 0;
      for (ps = 0; ps < M.pgnum; ps++) if (upOf(M, it, ps).join() !== oldUp[ps]) st.moved++;
      st.note = r.n ? '' : r.perfect ? 'balancer_perfect' : 'balancer_none';
    } else {
      var b = crushCompat(M, st.ws, mulberry(st.round * 7919));
      if (!b) { st.note = 'balancer_none'; st.moved = 0; }
      else {
        var mv = 0; b.raw.forEach(function (r2, ps2) { if (r2.join() !== M.raw[ps2].join()) mv++; });
        if (!st.cmds.length && st.total === 0) cmds.push('ceph osd crush weight-set create-compat');
        b.ws.forEach(function (w, o) { if (Math.abs(w - st.ws[o]) > 5e-7) cmds.push('ceph osd crush weight-set reweight-compat osd.' + o + ' ' + w.toFixed(6)); });
        st.ws = b.ws; M.raw = b.raw; st.moved = mv; st.note = '';
      }
    }
    st.total += st.moved;
    st.cmds = cmds;
  }

  S.X = S.X || {};
  S.X.balancer = {
    calcPgUpmaps: calcPgUpmaps, applyInc: applyInc, counts: counts, shuffle: shuffle, engine: engine, uniform: uniform, evalScore: evalScore, erf: erf,
    test: function (t) {
      // libstdc++ minstd_rand0: the 10000th value from the default seed is 1043618065 (C++ standard, [rand.predef])
      var g = engine(1), v; for (var i = 0; i < 10000; i++) v = g();
      t.eq(v, 1043618065, 'minstd_rand0 10000th value');
      var gb = t.G.balancer;
      if (gb) {
        var o = gb.options;
        t.eq([o.mgr_upmap_max_deviation, o.mgr_upmap_max_optimizations, o.mgr_mode, o.osd_calc_pg_upmaps_aggressively, o.osd_calc_pg_upmaps_aggressively_fast, o.osd_calc_pg_upmaps_local_fallback_retries, o.mgr_crush_compat_max_iterations, o.mgr_crush_compat_step, o.target_max_misplaced_ratio],
          [String(DEF.maxdev), String(DEF.maxopt), 'upmap', 'true', 'true', '100', '25', '.5', '0.05'], 'balancer defaults as in Ceph (module.py, global.yaml.in)');
        gb.cases.forEach(function (c, ci) {
          var M = { host: c.host, cw: c.cw, rw: c.rw, size: c.size, pgnum: c.pgnum, leaf: !!c.leaf, raw: c.raw }, items = {}, rng = { seed: c.seed, n: 0 };
          c.ex.forEach(function (e) { items[e[0]] = e[1]; });
          c.out.forEach(function (want, rd) {
            var r = calcPgUpmaps(M, items, c.maxdev, c.maxopt, { aggr: !!c.aggr, fast: !!c.fast, retries: c.retries }, rng);
            applyInc(items, r.inc);
            var got = { count: counts(M, items), n: r.n, unmap: sortNum(Array.from(r.inc.unmap)), upmap: keys(r.inc.upmap).map(function (x) { return [x, r.inc.upmap[x]]; }) };
            t.eq(got, want, 'calc_pg_upmaps case ' + ci + ' round ' + rd);
          });
        });
      }
      // invariants on CRUSH-placed clusters: failure domains hold, and a round never makes the score worse
      [['same', 4, 3, 64, 'host'], ['newhost', 5, 4, 256, 'host'], ['mixed', 6, 2, 128, 'osd'], ['same', 3, 6, 512, 'host']].forEach(function (p) {
        var st = fresh({ sizes: p[0], hosts: p[1], per: p[2], pgnum: p[3], fd: p[4], size: 3, mode: 'upmap', maxdev: 1, maxopt: 10, aggr: true });
        var s0 = stats(st.M, st.items).max;
        for (var r = 0; r < 6; r++) round(st);
        var s1 = stats(st.M, st.items);
        t.ok(s1.max <= s0, 'upmap rounds do not raise the max deviation ' + p.join(','));
        for (var ps = 0; ps < st.M.pgnum; ps++) {
          var up = upOf(st.M, st.items, ps), hs = up.map(function (o) { return st.M.host[o]; });
          t.ok(new Set(up).size === up.length && (p[4] !== 'host' || new Set(hs).size === hs.length), 'PG keeps distinct ' + p[4] + 's ' + p.join(',') + ' ' + ps);
        }
        var cc = fresh({ sizes: p[0], hosts: p[1], per: p[2], pgnum: p[3], fd: p[4], size: 3, mode: 'crush-compat', maxdev: 5, maxopt: 10, aggr: true });
        var e0 = evalScore(counts(cc.M, {}), targets(cc.M));
        round(cc);
        t.ok(evalScore(counts(cc.M, {}), targets(cc.M)) <= e0 + 1e-12, 'crush-compat keeps the best score ' + p.join(','));
        t.ok(cc.moved <= 0.05 * cc.M.pgnum + 1e-9, 'crush-compat respects target_max_misplaced_ratio ' + p.join(','));
      });
      t.near(erf(0.5), 0.5204998778, 'erf(0.5)', 2e-7);
    }
  };

  var DEF = { maxdev: 5, maxopt: 10 };
  S.DEFS.balancer = {
    icon: 'M12 3v18M5 7h14M5 7l-3 6a3 3 0 0 0 6 0zM19 7l-3 6a3 3 0 0 0 6 0zM8 21h8',
    defaults: function () { return fresh({ hosts: 4, per: 3, sizes: 'newhost', size: 3, pgnum: 128, fd: 'host', mode: 'upmap', maxdev: DEF.maxdev, maxopt: DEF.maxopt, aggr: true }); },
    refs: [['src/osd/OSDMap.cc :: OSDMap::calc_pg_upmaps, calc_deviations, fill_overfull_underfull, try_drop_remap_overfull, try_drop_remap_underfull, try_pg_upmap, find_best_remap, _apply_upmap', 'balancer_r1'],
           ['src/crush/CrushWrapper.cc :: try_remap_rule, _choose_type_stack, get_rule_weight_osd_map', 'balancer_r2'],
           ['src/pybind/mgr/balancer/module.py :: do_upmap, do_crush_compat, calc_eval, calc_stats; upmap_max_deviation (5), upmap_max_optimizations (10)', 'balancer_r3'],
           ['src/common/options/global.yaml.in :: osd_calc_pg_upmaps_aggressively (true), osd_calc_pg_upmaps_local_fallback_retries (100), target_max_misplaced_ratio (0.05)', 'balancer_r4']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('balancer_hosts'), numIn('hosts', st.hosts, 3, 12, 1)) + field(T('balancer_per'), numIn('per', st.per, 1, 8, 1))
        + field(T('balancer_sizes'), sel('sizes', [['same', T('balancer_sz_same')], ['newhost', T('balancer_sz_new')], ['mixed', T('balancer_sz_mixed')]], st.sizes))
        + field(T('balancer_pgnum'), sel('pgnum', [32, 64, 128, 256, 512, 1024], st.pgnum)) + field(T('balancer_fd'), sel('fd', [['host', 'host'], ['osd', 'osd']], st.fd)) + '</div>'
        + '<div class="sim-row">' + field(T('balancer_mode'), sel('mode', [['upmap', 'upmap'], ['crush-compat', 'crush-compat']], st.mode))
        + (st.mode === 'upmap' ? field('upmap_max_deviation', numIn('maxdev', st.maxdev, 1, 20, 1)) + field('upmap_max_optimizations', numIn('maxopt', st.maxopt, 1, 100, 1))
          + '<label class="sim-f sim-chk"><span>osd_calc_pg_upmaps_aggressively</span><input type="checkbox" data-k="aggr"' + (st.aggr ? ' checked' : '') + '></label>' : '')
        + '<div class="lx-btns"><button type="button" class="sim-btn pri" data-act="round">' + esc(T('balancer_round')) + '</button>'
        + '<button type="button" class="sim-btn" data-act="all">' + esc(T('balancer_all')) + '</button></div></div>';
    },
    view: function (st) {
      var M = st.M, s = stats(M, st.items), W = 720, H = 210, n = s.c.length, bw = (W - 50) / n, top = 12, bot = H - 26;
      var ymax = Math.max(s.hi, Math.max.apply(null, s.tg)) * 1.1 || 1, y = function (v) { return bot - v / ymax * (bot - top); };
      var bars = s.c.map(function (c, o) {
        var x = 40 + o * bw, d = c - s.tg[o], cls = d > st.maxdev ? 'f-full' : d < -st.maxdev ? 'f-near' : 'f-ok';
        return '<g><title>osd.' + o + ' (host' + (M.host[o] + 1) + ', ' + M.tbs[o] + ' TB): ' + c + ' PGs, target ' + (Math.round(s.tg[o] * 10) / 10) + '</title>'
          + '<rect class="lx-b ' + cls + '" x="' + (x + 1) + '" y="' + y(c) + '" width="' + Math.max(2, bw - 2) + '" height="' + (bot - y(c)) + '" rx="2"/>'
          + '<line class="lx-now" x1="' + x + '" x2="' + (x + bw) + '" y1="' + y(s.tg[o]) + '" y2="' + y(s.tg[o]) + '"/>'
          + (n <= 40 || o % 2 === 0 ? '<text class="lx-x" x="' + (x + bw / 2) + '" y="' + (H - 12) + '" text-anchor="middle">' + o + '</text>' : '') + '</g>';
      }).join('');
      var hosts = [], nh = Math.max.apply(null, M.host) + 1;
      for (var hh = 0; hh < nh; hh++) { var first = M.host.indexOf(hh), last = M.host.lastIndexOf(hh); hosts.push('<text x="' + (40 + (first + last + 1) / 2 * bw) + '" y="' + (H - 1) + '" text-anchor="middle">host' + (hh + 1) + '</text>'); }
      var axis = '<line class="lx-gl" x1="38" x2="' + (W - 8) + '" y1="' + bot + '" y2="' + bot + '"/><text x="34" y="' + (y(ymax / 1.1) + 4) + '" text-anchor="end">' + Math.round(ymax / 1.1) + '</text><text x="34" y="' + (bot + 4) + '" text-anchor="end">0</text>';
      var nItems = Object.keys(st.items).length;
      var cmds = st.cmds.length ? st.cmds.slice(0, 12).join('\n') + (st.cmds.length > 12 ? '\n# … ' + (st.cmds.length - 12) + ' more' : '') : null;
      var setup = st.mode === 'upmap'
        ? 'ceph osd set-require-min-compat-client luminous\nceph balancer mode upmap\nceph config set mgr mgr/balancer/upmap_max_deviation ' + st.maxdev + '\nceph balancer on\nceph balancer eval'
        : 'ceph balancer mode crush-compat\nceph balancer on\nceph balancer eval';
      return '<div class="sim-stats">' + stat(num(st.start.max, 1) + ' → ' + num(s.max, 1), T('balancer_s_dev'), s.max > st.maxdev ? 'warn' : '')
        + stat(L(s.min) + '–' + L(s.hi), T('balancer_s_range')) + stat(st.mode === 'upmap' ? L(nItems) : L(st.round), T(st.mode === 'upmap' ? 'balancer_s_items' : 'balancer_s_rounds'))
        + stat(L(st.moved) + ' / ' + L(st.total), T('balancer_s_moved'), st.moved ? 'hot' : '') + '</div>'
        + '<figure class="sim-fig"><svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('balancer_fig')) + '" dir="ltr">' + axis + bars + hosts + '</svg><figcaption>' + esc(T('balancer_cap')) + '</figcaption></figure>'
        + (st.note ? '<p class="sim-note">' + tx(st.note) + '</p>' : '')
        + (cmds ? '<h4>' + esc(T('balancer_cmds', { n: L(st.round) })) + '</h4><pre class="sim-cmd" dir="ltr"><code>' + esc(cmds) + '</code></pre>' : '')
        + '<h4>' + esc(T('balancer_setup')) + '</h4><pre class="sim-cmd" dir="ltr"><code>' + esc(setup) + '</code></pre>'
        + '<div class="sim-formula" dir="ltr">target<sub>i</sub> = w<sub>i</sub> × size × pg_num / Σw · deviation<sub>i</sub> = PGs<sub>i</sub> − target<sub>i</sub> · overfull: deviation &gt; max_deviation · underfull: deviation &lt; −max_deviation</div>'
        + '<p class="sim-note">' + tx(st.mode === 'upmap' ? 'balancer_note_up' : 'balancer_note_cc') + '</p>';
    },
    input: function (st, k, v, el) {
      var topo = { hosts: [3, 12], per: [1, 8] };
      if (topo[k]) { st[k] = clamp(parseInt(v, 10) || topo[k][0], topo[k][0], topo[k][1]); fresh(st); return 'out'; }
      if (k === 'sizes' || k === 'fd') { st[k] = v; fresh(st); return 'out'; }
      if (k === 'pgnum') { st.pgnum = +v; fresh(st); return 'out'; }
      if (k === 'mode') { st.mode = v; fresh(st); return 'all'; }
      if (k === 'maxdev') { st.maxdev = clamp(parseInt(v, 10) || 1, 1, 20); return 'out'; }
      if (k === 'maxopt') { st.maxopt = clamp(parseInt(v, 10) || 1, 1, 100); return 'out'; }
      if (k === 'aggr') { st.aggr = !!(el ? el.checked : v); return 'out'; }
      return null;
    },
    act: function (st, a) {
      if (a === 'round') { round(st); return 'out'; }
      if (a === 'all') { var all = []; for (var i = 0; i < 40; i++) { round(st); all = all.concat(st.cmds); if (!st.moved && st.note) break; } st.cmds = all; return 'out'; }
      return null;
    },
    say: function (st) { return T('balancer_s_dev') + ': ' + num(stats(st.M, st.items).max, 1); },
    fallbackState: function (st) { round(st); round(st); return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
