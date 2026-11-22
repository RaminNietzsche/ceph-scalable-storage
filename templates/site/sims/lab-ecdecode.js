/* Erasure code encode, failure and decode (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * GF(2⁸) with the polynomial 0x11d (gf-complete's default for w=8, and ISA-L's); the coding matrices are
 * jerasure's reed_sol_vandermonde_coding_matrix (src/reed_sol.c) and ISA-L's gf_gen_rs_matrix (erasure_code/ec_base.c),
 * the two reed_sol_van techniques of Ceph's jerasure and isa plugins; which chunks are read follows
 * ErasureCode::_minimum_to_decode (src/erasure-code/ErasureCode.cc). */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, num = h.num, sel = h.sel, field = h.field, stat = h.stat, seg = h.seg, bytes = h.bytes;
  var EXP = new Array(512), LOG = new Array(256);
  (function () { var x = 1; for (var i = 0; i < 255; i++) { EXP[i] = x; LOG[x] = i; x <<= 1; if (x & 0x100) x ^= 0x11d; } for (var j = 255; j < 512; j++) EXP[j] = EXP[j - 255]; LOG[0] = -1; })();
  function mul(a, b) { return a && b ? EXP[LOG[a] + LOG[b]] : 0; }
  function div(a, b) { if (!b) throw new Error('div0'); return a ? EXP[LOG[a] - LOG[b] + 255] : 0; }
  // jerasure: reed_sol_extended_vandermonde_matrix + reed_sol_big_vandermonde_distribution_matrix, rows k..k+m-1
  function jerasureMatrix(k, m) {
    var rows = k + m, cols = k, d = new Array(rows * cols).fill(0), i, j, t;
    d[0] = 1;
    d[(rows - 1) * cols + cols - 1] = 1;
    for (i = 1; i < rows - 1; i++) { t = 1; for (j = 0; j < cols; j++) { d[i * cols + j] = t; t = mul(t, i); } }
    var sindex = 0;
    for (i = 1; i < cols; i++) {
      sindex += cols;
      var srindex = sindex + i;
      for (j = i; j < rows && d[srindex] === 0; j++) srindex += cols;
      if (j !== i) { srindex -= i; for (var q = 0; q < cols; q++) { t = d[srindex + q]; d[srindex + q] = d[sindex + q]; d[sindex + q] = t; } }
      if (d[sindex + i] !== 1) { t = div(1, d[sindex + i]); srindex = i; for (j = 0; j < rows; j++) { d[srindex] = mul(t, d[srindex]); srindex += cols; } }
      for (j = 0; j < cols; j++) {
        t = d[sindex + j];
        if (j !== i && t !== 0) { var a = j, b = i; for (var r = 0; r < rows; r++) { d[a] ^= mul(t, d[b]); a += cols; b += cols; } }
      }
    }
    sindex = cols * cols;
    for (j = 0; j < cols; j++) {
      t = d[sindex];
      if (t !== 1) { t = div(1, t); var s2 = sindex; for (i = cols; i < rows; i++) { d[s2] = mul(t, d[s2]); s2 += cols; } }
      sindex++;
    }
    sindex = cols * (cols + 1);
    for (i = cols + 1; i < rows; i++) {
      t = d[sindex];
      if (t !== 1) { t = div(1, t); for (j = 0; j < cols; j++) d[sindex + j] = mul(d[sindex + j], t); }
      sindex += cols;
    }
    return d.slice(k * k);
  }
  // ISA-L gf_gen_rs_matrix(a, k + m, k), rows k..k+m-1
  function isaMatrix(k, m) {
    var a = [], gen = 1;
    for (var i = k; i < k + m; i++) { var p = 1; for (var j = 0; j < k; j++) { a.push(p); p = mul(p, gen); } gen = mul(gen, 2); }
    return a;
  }
  function matrix(plugin, k, m) { return plugin === 'jerasure' ? jerasureMatrix(k, m) : isaMatrix(k, m); }
  function encode(plugin, k, m, data) {          // data: k arrays of chunk bytes
    var M = matrix(plugin, k, m), cs = data[0].length, par = [];
    for (var i = 0; i < m; i++) { var c = new Array(cs).fill(0); for (var j = 0; j < k; j++) { var co = M[i * k + j]; for (var b = 0; b < cs; b++) c[b] ^= mul(co, data[j][b]); } par.push(c); }
    return { matrix: M, parity: par };
  }
  // ErasureCode::_minimum_to_decode for want = all data chunks
  function minimumToDecode(k, avail) {
    var want = []; for (var i = 0; i < k; i++) want.push(i);
    if (want.every(function (x) { return avail.indexOf(x) >= 0; })) return want;
    if (avail.length < k) return null;
    return avail.slice().sort(function (a, b) { return a - b; }).slice(0, k);
  }
  function invert(A, n) {
    var M = A.map(function (r) { return r.slice(); }), I = [];
    for (var i = 0; i < n; i++) { I.push(new Array(n).fill(0)); I[i][i] = 1; }
    for (var c = 0; c < n; c++) {
      var p = c; while (p < n && M[p][c] === 0) p++;
      if (p === n) return null;
      var t = M[p]; M[p] = M[c]; M[c] = t; t = I[p]; I[p] = I[c]; I[c] = t;
      var iv = div(1, M[c][c]);
      for (var j = 0; j < n; j++) { M[c][j] = mul(M[c][j], iv); I[c][j] = mul(I[c][j], iv); }
      for (var r = 0; r < n; r++) if (r !== c && M[r][c]) { var f = M[r][c]; for (var q = 0; q < n; q++) { M[r][q] ^= mul(f, M[c][q]); I[r][q] ^= mul(f, I[c][q]); } }
    }
    return I;
  }
  // decode the data chunks from the chunks in `use` (k ids), chunks = all k+m chunk arrays (lost ones unused)
  function decode(plugin, k, m, chunks, use) {
    var M = matrix(plugin, k, m), rows = use.map(function (id) { if (id < k) { var r = new Array(k).fill(0); r[id] = 1; return r; } return M.slice((id - k) * k, (id - k + 1) * k); });
    var inv = invert(rows, k), cs = chunks[use[0]].length, out = [];
    for (var i = 0; i < k; i++) { var d = new Array(cs).fill(0); for (var j = 0; j < k; j++) { var co = inv[i][j]; for (var b = 0; b < cs; b++) d[b] ^= mul(co, chunks[use[j]][b]); } out.push(d); }
    return { data: out, inv: inv };
  }
  function split(str, k) {
    var enc = NODE ? Array.from(Buffer.from(str, 'utf8')) : Array.from(new TextEncoder().encode(str));
    var cs = Math.max(1, Math.ceil(enc.length / k)), data = [];
    for (var i = 0; i < k; i++) { var c = enc.slice(i * cs, (i + 1) * cs); while (c.length < cs) c.push(0); data.push(c); }
    return { data: data, cs: cs, len: enc.length };
  }
  function hex(a, n) { return a.slice(0, n).map(function (x) { return (x < 16 ? '0' : '') + x.toString(16); }).join(' ') + (a.length > n ? ' …' : ''); }
  function txt(a) { return a.map(function (x) { return x >= 32 && x < 127 ? String.fromCharCode(x) : '·'; }).join(''); }

  S.X = S.X || {};
  S.X.ecdecode = {
    mul: mul, matrix: matrix, encode: encode, decode: decode, minimumToDecode: minimumToDecode,
    test: function (t) {
      (t.G.ec_encode || []).forEach(function (c, ci) {
        var data = c[3].map(function (hx) { var a = []; for (var i = 0; i < hx.length; i += 2) a.push(parseInt(hx.substr(i, 2), 16)); return a; });
        var e = encode(c[0], c[1], c[2], data);
        t.eq(e.matrix, c[4], c[0] + ' matrix k=' + c[1] + ' m=' + c[2]);
        t.eq(e.parity.map(function (p) { return p.map(function (x) { return (x < 16 ? '0' : '') + x.toString(16); }).join(''); }), c[5], c[0] + ' parity case ' + ci);
        // every set of k surviving chunks rebuilds the data (MDS property), for a few random erasure patterns
        var all = data.concat(e.parity), n = c[1] + c[2];
        for (var trial = 0; trial < 6; trial++) {
          var lost = [], seed = ci * 7 + trial;
          for (var x = 0; x < n && lost.length < c[2]; x++) if (((seed * 2654435761 + x * 40503) >>> 7) % 3 === 0) lost.push(x);
          var avail = []; for (var y = 0; y < n; y++) if (lost.indexOf(y) < 0) avail.push(y);
          var use = minimumToDecode(c[1], avail);
          t.eq(decode(c[0], c[1], c[2], all, use).data, data, c[0] + ' decode case ' + ci + ' lost ' + lost);
        }
      });
      t.eq(minimumToDecode(4, [0, 1, 2, 3, 5]), [0, 1, 2, 3], 'all data chunks present: read only them');
      t.eq(minimumToDecode(4, [1, 2, 4, 5, 3]), [1, 2, 3, 4], 'otherwise the first k available');
      t.eq(minimumToDecode(4, [1, 2, 4]), null, 'fewer than k: EIO');
    }
  };

  S.DEFS.ecdecode = {
    icon: 'M3 6h4v12H3zM9 6h4v12H9zM15 6h3v12h-3zM20 9v6M8 3l8 18',
    defaults: function () { return { plugin: 'isa', k: 4, m: 2, text: 'Ceph keeps every object safe, one chunk at a time.', lost: [] }; },
    refs: [['jerasure src/reed_sol.c :: reed_sol_vandermonde_coding_matrix, reed_sol_big_vandermonde_distribution_matrix', 'ecdecode_r1'],
           ['isa-l erasure_code/ec_base.c :: gf_gen_rs_matrix, ec_encode_data_base', 'ecdecode_r2'],
           ['src/erasure-code/ErasureCode.cc :: ErasureCode::_minimum_to_decode', 'ecdecode_r3'],
           ['src/erasure-code/jerasure/ErasureCodeJerasure.cc, src/erasure-code/isa/ErasureCodeIsa.cc :: technique=reed_sol_van', 'ecdecode_r4'],
           ['src/common/options/global.yaml.in :: osd_pool_default_erasure_code_profile (plugin=isa technique=reed_sol_van k=2 m=2)', 'ecdecode_r5']],
    controls: function (st) {
      var n = st.k + st.m, btns = '';
      for (var i = 0; i < n; i++) btns += '<button type="button" class="lx-tbtn" data-act="fail" data-p="' + i + '" aria-pressed="' + (st.lost.indexOf(i) >= 0) + '" aria-label="' + esc(T('ecdecode_fail', { n: i })) + '">s' + i + (i < st.k ? '' : ' P') + '</button>';
      return '<div class="sim-row">' + field('plugin', sel('plugin', [['isa', 'isa'], ['jerasure', 'jerasure']], st.plugin)) + field('k', sel('k', [2, 3, 4, 5, 6, 8], st.k)) + field('m', sel('m', [1, 2, 3, 4], st.m))
        + field(T('ecdecode_text'), '<input type="text" dir="auto" data-k="text" maxlength="160" value="' + esc(st.text) + '">') + '</div>'
        + '<div class="sim-f"><span>' + esc(T('ecdecode_failh')) + '</span><div class="lx-btns" dir="ltr">' + btns + ' <button type="button" class="sim-btn sm" data-act="heal">' + esc(T('ecdecode_heal')) + '</button></div></div>';
    },
    view: function (st) {
      var sp = split(st.text || ' ', st.k), e = encode(st.plugin, st.k, st.m, sp.data), all = sp.data.concat(e.parity), n = st.k + st.m;
      var avail = []; for (var i = 0; i < n; i++) if (st.lost.indexOf(i) < 0) avail.push(i);
      var use = minimumToDecode(st.k, avail), dec = use ? decode(st.plugin, st.k, st.m, all, use) : null;
      var cards = all.map(function (c, id) {
        var lost = st.lost.indexOf(id) >= 0, used = use && use.indexOf(id) >= 0, isD = id < st.k;
        return '<div class="lx-card ' + (lost ? 'bad' : used ? 'on' : 'dim') + '"><h4 dir="ltr">shard ' + id + ' <span class="sim-pill">' + esc(T(isD ? 'ecdecode_data' : 'ecdecode_par')) + '</span></h4>'
          + (lost ? '<p class="lx-mono">' + esc(T('ecdecode_lost')) + '</p>' : '<div class="lx-hex" dir="ltr">' + hex(c, 12) + '</div>' + (isD ? '<div class="lx-mono" dir="ltr">“' + esc(txt(c)) + '”</div>' : ''))
          + '<small>' + esc(T(lost ? 'ecdecode_c_lost' : used ? 'ecdecode_c_read' : 'ecdecode_c_idle')) + '</small></div>';
      }).join('');
      var M = e.matrix, mt = '<table class="sim-t lx-mat" dir="ltr"><tbody>' + M.reduce(function (rows, v, idx) { if (idx % st.k === 0) rows.push([]); rows[rows.length - 1].push(v); return rows; }, []).map(function (r, ri) {
        return '<tr><th>P' + (st.k + ri) + '</th>' + r.map(function (v) { return '<td>' + v + '</td>'; }).join('') + '</tr>';
      }).join('') + '</tbody></table>';
      var res;
      if (!dec) res = '<p class="sim-warn">' + tx('ecdecode_eio', { a: L(avail.length), k: L(st.k) }) + '</p>';
      else {
        var bytesOut = [].concat.apply([], dec.data).slice(0, sp.len), ok = JSON.stringify(dec.data) === JSON.stringify(sp.data);
        var str = NODE ? Buffer.from(bytesOut).toString('utf8') : new TextDecoder().decode(new Uint8Array(bytesOut));
        var direct = use.every(function (x) { return x < st.k; });
        res = '<div class="lx-card on"><h4>' + esc(T(direct ? 'ecdecode_direct' : 'ecdecode_rebuilt', { s: use.join(', ') })) + ' ' + (ok ? '✓' : '✗') + '</h4><div class="lx-mono" dir="auto">' + esc(str) + '</div></div>'
          + (direct ? '' : '<details class="ps-hist"><summary>' + esc(T('ecdecode_inv')) + '</summary><table class="sim-t lx-mat" dir="ltr"><tbody>' + dec.inv.map(function (r, ri) { return '<tr><th>D' + ri + '</th>' + r.map(function (v) { return '<td>' + v + '</td>'; }).join('') + '</tr>'; }).join('') + '</tbody></table></details>');
      }
      var cs = sp.cs, readB = use ? use.length * cs : 0, repairB = st.k * cs;
      return '<div class="sim-stats">' + stat(L(avail.length) + ' / ' + L(n), T('ecdecode_s_alive'), avail.length < st.k ? 'warn' : st.lost.length ? 'hot' : '') + stat(L(st.m - st.lost.length < 0 ? 0 : st.m - st.lost.length), T('ecdecode_s_more'), st.lost.length >= st.m ? 'warn' : '')
        + stat(bytes(cs) + ' × ' + L(n), T('ecdecode_s_chunks')) + stat(L(Math.round(n / st.k * 100) / 100) + '×', T('ecdecode_s_over')) + stat(bytes(repairB), T('ecdecode_s_repair'), 'hot') + '</div>'
        + '<div class="lx-grid">' + cards + '</div>' + res
        + '<details class="ps-hist"><summary>' + esc(T('ecdecode_mat', { p: st.plugin })) + '</summary>' + mt + '</details>'
        + '<div class="sim-formula" dir="ltr">P<sub>i</sub>[b] = ⊕<sub>j</sub> M[i][j] · D<sub>j</sub>[b] in GF(2⁸), polynomial 0x11d · read for decode: ' + (use ? '{' + use.join(',') + '}' : '-EIO') + ' (all data shards if present, else the first k available) · rebuilding one lost shard reads k = ' + st.k + ' chunks</div>'
        + '<p class="sim-note">' + tx('ecdecode_note') + '</p>';
    },
    input: function (st, k, v) {
      if (k === 'plugin') { st.plugin = v; return 'out'; }
      if (k === 'k' || k === 'm') { st[k] = +v; st.lost = st.lost.filter(function (x) { return x < st.k + st.m; }); return 'all'; }
      if (k === 'text') { st.text = String(v).slice(0, 160); return 'out'; }
      return null;
    },
    act: function (st, a, el) {
      if (a === 'fail') { var i = +el.getAttribute('data-p'), at = st.lost.indexOf(i); if (at >= 0) st.lost.splice(at, 1); else st.lost.push(i); return 'all'; }
      if (a === 'heal') { st.lost = []; return 'all'; }
      return null;
    },
    say: function (st) { return T('ecdecode_s_alive') + ': ' + L(st.k + st.m - st.lost.length) + ' / ' + L(st.k + st.m); },
    fallbackState: function (st) { st.lost = [1, 4]; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
