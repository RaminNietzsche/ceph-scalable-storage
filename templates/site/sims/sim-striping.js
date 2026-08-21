/* RBD striping mapper (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, C = h.C, T = h.T, L = h.L, esc = h.esc, bytes = h.bytes, sel = h.sel, field = h.field, numIn = h.numIn, stat = h.stat, clamp = h.clamp;
  var K = 1024, M = K * K, G = M * K;
  var COLORS = 6;
  function lay(st) { var os = Math.pow(2, st.order), su = Math.min(st.su * K, os); return { object_size: os, stripe_unit: st.sc === 1 ? os : su, stripe_count: st.sc }; }
  S.DEFS.striping = {
    icon: 'M3 5h18M3 10h18M3 15h18M3 20h18M8 3v19M16 3v19',
    defaults: function () { return { gib: 10, order: 22, su: 64, sc: 4, id: '10226b8b4567', off: 1000000, len: 300000 }; },
    refs: [['src/osdc/Striper.cc :: Striper::file_to_extents', 'r_st_fte'], ['Striper.cc :: get_num_objects, get_file_offset, object_truncate_size', 'r_st_misc'],
           ['src/librbd/ImageCtx.cc :: ImageCtx::init (format_string "%s.%016llx")', 'r_st_name'], ['src/include/rbd_types.h :: RBD_DATA_PREFIX "rbd_data."', 'r_st_prefix'],
           ['src/test/test_striper.cc :: the upstream test vectors used by tests/sims', 'r_st_test']],
    controls: function (st) {
      var os = Math.pow(2, st.order), sus = [4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048, 4096].filter(function (x) { return x * K <= os; });
      return '<div class="sim-row">' + field(T('st_size'), numIn('gib', st.gib, 1, 65536, 1)) + field('order', sel('order', [[16, '16 (64 KiB)'], [20, '20 (1 MiB)'], [22, '22 (4 MiB)'], [23, '23 (8 MiB)'], [25, '25 (32 MiB)']], st.order))
        + field('stripe_unit', sel('su', sus.map(function (x) { return [x, bytes(x * K)]; }), st.su)) + field('stripe_count', sel('sc', [1, 2, 4, 8, 16], st.sc)) + '</div>'
        + '<div class="sim-row">' + field(T('st_id'), '<input type="text" dir="ltr" spellcheck="false" data-k="id" value="' + esc(st.id) + '">')
        + field(T('st_off'), numIn('off', st.off, 0, 1e15, 1)) + field(T('st_len'), numIn('len', st.len, 1, 1e10, 1)) + '</div>';
    },
    view: function (st) {
      var l = lay(st), size = st.gib * G, off = clamp(st.off, 0, Math.max(0, size - 1)), len = clamp(st.len, 1, size - off);
      var ex = C.fileToExtents(l, off, len, 0), nobj = C.numObjects(l, size), spo = l.object_size / l.stripe_unit, sc = l.stripe_count;
      var setBytes = l.object_size * sc, set0 = Math.floor(off / setBytes), set1 = Math.floor((off + len - 1) / setBytes);
      var col = {}; ex.forEach(function (e, i) { col[e.object_no] = i % COLORS; });
      // one grid per touched object set (at most two); rows are stripes, columns are the objects of the set
      var grids = '', rowsShown = Math.min(spo, 32), group = spo / rowsShown;
      for (var s = set0; s <= Math.min(set1, set0 + 1); s++) {
        var cell = '';
        for (var r = 0; r < rowsShown; r++) {
          cell += '<tr><th dir="ltr">' + (group > 1 ? 's' + (r * group) + '…' : 's' + (s * spo + r)) + '</th>';
          for (var c = 0; c < sc; c++) {
            var objno = s * sc + c, lo = r * group * l.stripe_unit, hi = (r + 1) * group * l.stripe_unit, hit = 0;
            ex.forEach(function (e) { if (e.object_no === objno) { var a = Math.max(lo, e.offset), b = Math.min(hi, e.offset + e.length); if (b > a) hit += b - a; } });
            var fo = C.fileOffset(l, objno, lo);
            cell += '<td class="' + (hit ? 'hit c' + col[objno] : '') + '" title="' + bytes(fo) + '"' + (hit ? ' style="--f:' + (hit / (hi - lo)).toFixed(2) + '"' : '') + '>' + (hit ? '<i></i>' : '') + '</td>';
          }
          cell += '</tr>';
        }
        grids += '<figure class="st-set"><figcaption dir="ltr">object set ' + s + ' · objects ' + (s * sc) + '…' + (s * sc + sc - 1) + (group > 1 ? ' · ' + esc(T('st_grouped', { n: L(group) })) : '') + '</figcaption>'
          + '<table dir="ltr"><thead><tr><th></th>' + Array.from({ length: sc }, function (_, c) { return '<th>' + (s * sc + c).toString(16) + '</th>'; }).join('') + '</tr></thead><tbody>' + cell + '</tbody></table></figure>';
      }
      var rows = ex.slice(0, 64).map(function (e) {
        return '<tr class="c' + col[e.object_no] + '"><td dir="ltr"><code>' + esc(C.rbdDataName(st.id || 'ID', e.object_no)) + '</code></td><td dir="ltr">' + e.offset + '</td><td dir="ltr">' + e.length + '</td><td dir="ltr">'
          + e.buffer_extents.slice(0, 6).map(function (b) { return '[' + b[0] + ', ' + b[1] + ']'; }).join(' ') + (e.buffer_extents.length > 6 ? ' …' : '') + '</td></tr>';
      }).join('');
      return '<div class="sim-stats">' + stat(L(nobj), T('st_s_objs')) + stat(bytes(l.object_size), 'object_size') + stat(bytes(setBytes), T('st_s_set')) + stat(L(ex.length), T('st_s_touched')) + '</div>'
        + '<div class="sim-formula" dir="ltr">blockno = ⌊off / su⌋ · stripeno = ⌊blockno / sc⌋ · stripepos = blockno % sc · objectsetno = ⌊stripeno / (os / su)⌋ · objectno = objectsetno × sc + stripepos · '
        + 'offset in object = (stripeno % (os / su)) × su + off % su</div>'
        + '<div class="st-sets">' + grids + '</div>'
        + '<div class="table-wrap"><table class="sim-t"><thead><tr><th>' + esc(T('st_obj')) + '</th><th>' + esc(T('st_ooff')) + '</th><th>' + esc(T('st_olen')) + '</th><th>buffer_extents</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        + (ex.length > 64 ? '<p class="sim-note">' + tx('st_more', { n: L(ex.length - 64) }) + '</p>' : '')
        + '<pre class="sim-cmd" dir="ltr"><code>rbd create pool/img --size ' + st.gib + 'G --object-size ' + bytes(l.object_size).replace(' ', '').replace('iB', '') + (sc > 1 ? ' --stripe-unit ' + (l.stripe_unit / K) + 'K --stripe-count ' + sc : '') + '</code></pre>';
    },
    input: function (st, k, v) {
      if (k === 'gib') { st.gib = clamp(parseInt(v, 10) || 1, 1, 65536); return 'out'; }
      if (k === 'order') { st.order = +v; st.su = Math.min(st.su, Math.pow(2, st.order) / K); return 'all'; }
      if (k === 'su' || k === 'sc') { st[k] = +v; return 'out'; }
      if (k === 'id') { st.id = String(v).replace(/[^0-9a-zA-Z]/g, '').slice(0, 32); return 'out'; }
      if (k === 'off') { st.off = Math.max(0, Math.floor(+v || 0)); return 'out'; }
      if (k === 'len') { st.len = Math.max(1, Math.floor(+v || 1)); return 'out'; }
      return null;
    }
  };
})(typeof self !== 'undefined' ? self : this);
