/* Write-path animations: BlueStore write and RGW PUT (sims.js part). CC BY-NC-SA 4.0, Ramin Najarbashi. */
(function (root) {
  'use strict';
  var S = (typeof module !== 'undefined' && module.exports) ? require('./sims.js') : root.Sims;
  var h = S.h, tx = h.tx, rich = h.rich, C = h.C, T = h.T, L = h.L, esc = h.esc, num = h.num, bytes = h.bytes, sel = h.sel, field = h.field, numIn = h.numIn, seg = h.seg, stat = h.stat, code = h.code, clamp = h.clamp;
  var K = 1024, M = 1024 * 1024;

  // a sequence diagram; lanes are mirrored in the Persian edition so time still flows with the reading direction
  var SEQN = 0;
  function seqSVG(lanes, steps, cur, all) {
    var mid0 = (all ? 'sim-ahs' : 'sim-ah') + (++SEQN), fa = h.fa(), n = lanes.length, W = 640, lw = W / n, top = 34, rh = 30, H = top + steps.length * rh + 12;
    function x(i) { return (fa ? n - 1 - i : i) * lw + lw / 2; }
    var g = lanes.map(function (l, i) {
      return '<text class="ln" x="' + x(i) + '" y="16" text-anchor="middle">' + esc(l) + '</text><line class="lf" x1="' + x(i) + '" x2="' + x(i) + '" y1="24" y2="' + (H - 4) + '"/>';
    }).join('');
    g += steps.map(function (s, j) {
      var y = top + j * rh + 14, cls = all || j < cur ? 'done' : j === cur ? 'cur' : 'todo', a = x(s.from), b = x(s.to), lab = esc(T(s.key + '_s'));
      if (s.from === s.to) {
        var d = fa ? -1 : 1;
        return '<g class="st ' + cls + '"><path d="M' + a + ' ' + (y - 8) + ' h' + (d * 26) + ' v14 h' + (-d * 22) + '" marker-end="url(#' + mid0 + ')"/><text x="' + (a + d * 32) + '" y="' + (y + 2) + '" text-anchor="' + (fa ? 'end' : 'start') + '">' + L(j + 1) + '. ' + lab + '</text></g>';
      }
      var mid = (a + b) / 2;
      return '<g class="st ' + cls + '"><line x1="' + a + '" x2="' + (b + (b > a ? -6 : 6)) + '" y1="' + y + '" y2="' + y + '" marker-end="url(#' + mid0 + ')"' + (s.dash ? ' stroke-dasharray="5 4"' : '') + '/>'
        + '<text x="' + mid + '" y="' + (y - 5) + '" text-anchor="middle">' + L(j + 1) + '. ' + lab + '</text></g>';
    }).join('');
    return '<svg class="sim-seq" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('seq_label')) + '"><defs><marker id="' + mid0 + '" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>' + g + '</svg>';
  }
  function stepBox(steps, i, all) {
    if (all) return '<ol class="sim-steps">' + steps.map(function (s) { return '<li><b>' + tx(s.key + '_s') + '</b> ' + tx(s.key, s.v) + ' <span class="sim-ref">' + code(s.ref) + '</span></li>'; }).join('') + '</ol>';
    var s = steps[i];
    return '<div class="sim-step" aria-live="off"><h4>' + L(i + 1) + '/' + L(steps.length) + ' · ' + tx(s.key + '_s') + (s.state ? ' <span class="sim-pill" dir="ltr">' + s.state + '</span>' : '') + '</h4><p>' + tx(s.key, s.v) + '</p><p class="sim-ref">' + esc(T('follows')) + ' ' + code(s.ref) + '</p></div>';
  }

  /* ---------------------------------------------------------------- BlueStore */
  var BS_PRESETS = { s4o: [0, 4 * K, true], s6u: [2 * K, 6 * K, true], n16: [0, 16 * K, false], n1m: [0, M, false], o128: [64 * K, 128 * K, true] };
  function bsCalc(st) {
    var pds = st.dev === 'hdd' ? 64 * K : 0;
    return { pds: pds, r: C.bluestoreWrite(st.off, st.len, { minAlloc: 4 * K, preferDeferred: pds, block: 4 * K, overwrite: st.over }) };
  }
  function bsPlan(st) {
    var c = bsCalc(st), r = c.r, ps = r.pieces, anyDef = ps.some(function (p) { return p.deferred; }), anyNew = ps.some(function (p) { return p.path === 'new'; });
    var rmw = ps.reduce(function (a, p) { return a + p.readPenalty; }, 0), steps = [];
    steps.push({ from: 0, to: 1, key: 'bs_s_queue', state: 'PREPARE', ref: 'BlueStore::queue_transactions, _txc_create' });
    steps.push({ from: 1, to: 1, key: 'bs_s_split', v: { n: L(ps.length) }, ref: 'BlueStore::_do_write_data, _do_write_small, _do_write_big' });
    if (rmw) steps.push({ from: 1, to: 3, key: 'bs_s_rmw', v: { b: bytes(rmw) }, ref: 'BlueStore::_do_write_small (head_read / tail_read), _do_read' });
    if (anyNew) steps.push({ from: 1, to: 2, key: 'bs_s_alloc', v: { b: bytes(ps.reduce(function (a, p) { return a + p.alloc; }, 0)) }, ref: 'BlueStore::_do_alloc_write, Allocator::allocate' });
    if (anyNew && !r.deferNew) steps.push({ from: 1, to: 3, key: 'bs_s_aio', v: { b: bytes(r.newData) }, state: 'AIO_WAIT', ref: 'BlueStore::_do_alloc_write, _txc_aio_submit' });
    if (anyDef) steps.push({ from: 1, to: 4, key: 'bs_s_defop', ref: 'bluestore_deferred_op_t, BlueStore::_txc_add_transaction' });
    steps.push({ from: 1, to: 4, key: anyDef ? 'bs_s_kv_def' : 'bs_s_kv', state: 'KV_SUBMITTED', ref: 'BlueStore::_kv_sync_thread, _txc_apply_kv' });
    steps.push({ from: 1, to: 0, key: 'bs_s_ack', state: 'KV_DONE', dash: true, ref: 'BlueStore::_txc_committed_kv, _txc_state_proc' });
    if (anyDef) {
      steps.push({ from: 1, to: 3, key: 'bs_s_defio', state: 'DEFERRED_QUEUED', ref: 'BlueStore::_deferred_queue, _deferred_submit_unlock' });
      steps.push({ from: 1, to: 4, key: 'bs_s_clean', state: 'DEFERRED_CLEANUP', ref: 'BlueStore::_deferred_aio_finish' });
    }
    return steps;
  }
  S.DEFS.bluestore = {
    icon: 'M4 5h16v5H4zM4 14h16v5H4zM7 7.5h.1M7 16.5h.1',
    defaults: function () { return { dev: 'hdd', off: 0, len: 4 * K, over: true, preset: 's4o', i: 0 }; },
    steps: function (st) { return bsPlan(st).length; },
    refs: [['src/os/bluestore/BlueStore.cc :: _do_write, _do_write_data', 'r_bs_split'], ['BlueStore.cc :: _do_write_small, _do_write_big', 'r_bs_paths'],
           ['BlueStore.cc :: _do_alloc_write (prefer_deferred_size)', 'r_bs_alloc'], ['BlueStore.cc :: _txc_state_proc, _kv_sync_thread, _deferred_queue', 'r_bs_txc'],
           ['src/os/bluestore/BlueStore_components.h :: TransContext::state_t', 'r_bs_states'],
           ['src/common/options/global.yaml.in :: bluestore_min_alloc_size_hdd/ssd (4K), bluestore_prefer_deferred_size_hdd (64K) / _ssd (0)', 'r_bs_opts']],
    controls: function (st) {
      return '<div class="sim-row"><div class="sim-f"><span>' + esc(T('bs_dev')) + '</span>' + seg('dev', [['hdd', 'HDD'], ['ssd', 'SSD/NVMe']], st.dev) + '</div>'
        + field(T('bs_preset'), sel('preset', [['s4o', T('bs_p_s4o')], ['s6u', T('bs_p_s6u')], ['n16', T('bs_p_n16')], ['n1m', T('bs_p_n1m')], ['o128', T('bs_p_o128')], ['custom', T('bs_p_custom')]], st.preset)) + '</div>'
        + '<div class="sim-row">' + field(T('bs_off'), numIn('off', st.off / K, 0, 4096, 0.5)) + field(T('bs_len'), numIn('len', st.len / K, 0.5, 4096, 0.5))
        + '<div class="sim-f"><span>' + esc(T('bs_target')) + '</span>' + seg('over', [['0', T('bs_new')], ['1', T('bs_over')]], st.over ? '1' : '0') + '</div></div>';
    },
    view: function (st, all) {
      var c = bsCalc(st), r = c.r, steps = bsPlan(st), i = clamp(st.i, 0, steps.length - 1);
      var lo = Math.floor(st.off / (4 * K)) * 4 * K, hi = Math.ceil((st.off + st.len) / (4 * K)) * 4 * K, span = Math.max(hi - lo, 4 * K), W = 640;
      var units = span / (4 * K), cells = '';
      if (units <= 64) for (var u = 0; u < units; u++) cells += '<rect class="mau" x="' + (u * W / units) + '" y="18" width="' + (W / units) + '" height="26"/>';
      var bars = r.pieces.map(function (p) {
        var x = (p.off - lo) / span * W, w = Math.max(2, p.len / span * W);
        return '<rect class="pc ' + p.path + (p.deferred ? ' def' : '') + '" x="' + x + '" y="20" width="' + w + '" height="22" rx="3"><title>' + p.kind + ' ' + bytes(p.len) + '</title></rect>';
      }).join('');
      var fig = '<svg class="bs-bar" viewBox="0 0 ' + W + ' 60" role="img" aria-label="' + esc(T('bs_bar')) + '" dir="ltr">' + cells + bars
        + '<text x="0" y="12">' + bytes(lo) + '</text><text x="' + W + '" y="12" text-anchor="end">' + bytes(hi) + '</text><text x="' + (W / 2) + '" y="58" text-anchor="middle">min_alloc_size = 4 KiB</text></svg>';
      var rows = r.pieces.map(function (p) {
        return '<tr><td dir="ltr">' + p.kind + '</td><td dir="ltr">' + bytes(p.off) + ' + ' + bytes(p.len) + '</td><td>' + esc(T('bs_why_' + p.path)) + '</td><td>' + esc(T(p.deferred ? 'bs_def' : 'bs_dir'))
          + '</td><td dir="ltr">' + (p.readPenalty ? bytes(p.readPenalty) : '–') + '</td><td dir="ltr">' + (p.alloc ? bytes(p.alloc) : '–') + '</td></tr>';
      }).join('');
      var wal = r.pieces.reduce(function (a, p) { return a + (p.deferred ? p.disk : 0); }, 0);
      return '<div class="sim-stats">' + stat(L(r.pieces.length), T('bs_st_pieces')) + stat(wal ? bytes(wal) : '–', T('bs_st_wal'), wal ? 'hot' : '') + stat(r.newData && !r.deferNew ? bytes(r.newData) : '–', T('bs_st_aio'))
        + stat(c.pds ? bytes(c.pds) : '0', 'prefer_deferred_size') + '</div>' + '<figure class="sim-fig">' + fig + '<figcaption>' + esc(T('bs_bar_cap')) + '</figcaption></figure>'
        + '<div class="table-wrap"><table class="sim-t"><thead><tr><th>' + esc(T('bs_piece')) + '</th><th>' + esc(T('bs_range')) + '</th><th>' + esc(T('bs_why')) + '</th><th>' + esc(T('bs_how')) + '</th><th>' + esc(T('bs_read')) + '</th><th>' + esc(T('bs_alloc')) + '</th></tr></thead><tbody>' + rows + '</tbody></table></div>'
        + '<figure class="sim-fig">' + seqSVG(T('bs_lanes').split('|'), steps, i, all) + '</figure>' + stepBox(steps, i, all)
        + '<div class="sim-formula" dir="ltr">new data: deferred ⇔ data_size &lt; prefer_deferred_size (' + bytes(c.pds) + ') · small overwrite: always deferred · big overwrite: deferred ⇔ len ≤ 2 × prefer_deferred_size</div>';
    },
    say: function (st) { var s = bsPlan(st)[clamp(st.i, 0, 99)]; return s ? T(s.key + '_s') : ''; },
    input: function (st, k, v) {
      if (k === 'dev') { st.dev = v; st.i = 0; return 'all'; }
      if (k === 'preset') { st.preset = v; if (BS_PRESETS[v]) { st.off = BS_PRESETS[v][0]; st.len = BS_PRESETS[v][1]; st.over = BS_PRESETS[v][2]; } st.i = 0; return 'all'; }
      if (k === 'off') { st.off = Math.round(clamp(parseFloat(v) || 0, 0, 4096) * 2) * K / 2; st.preset = 'custom'; st.i = 0; return 'outctl'; }
      if (k === 'len') { st.len = Math.round(clamp(parseFloat(v) || 0.5, 0.5, 4096) * 2) * K / 2; st.preset = 'custom'; st.i = 0; return 'outctl'; }
      if (k === 'over') { st.over = v === '1'; st.preset = 'custom'; st.i = 0; return 'all'; }
      return null;
    }
  };

  /* ---------------------------------------------------------------- RGW PUT */
  function rgPlan(st) {
    var size = st.size * M, shard = C.bucketShardIndex(st.key, st.shards), steps = [], v = { k: st.key, n: L(st.shards), sh: L(shard), b: bytes(size) };
    if (st.mode === 'atomic') {
      var tails = Math.max(0, Math.ceil((size - 4 * M) / (4 * M)));
      v.t = L(tails);
      steps.push({ from: 0, to: 1, key: 'rg_s_put', v: v, ref: 'RGWPutObj::execute (rgw_op.cc)' });
      steps.push({ from: 1, to: 2, key: 'rg_s_auth', ref: 'rgw::auth::s3::AWSAuthStrategy, AWSv4ComplSingle (rgw_auth_s3.cc)' });
      if (tails) steps.push({ from: 1, to: 4, key: 'rg_s_tail', v: v, ref: 'AtomicObjectProcessor::process, RadosWriter::process' });
      steps.push({ from: 1, to: 3, key: 'rg_s_prep', v: v, ref: 'RGWRados::Bucket::UpdateIndex::prepare, cls_rgw rgw_bucket_prepare_op' });
      steps.push({ from: 1, to: 4, key: 'rg_s_head', v: v, ref: 'RGWRados::Object::Write::_do_write_meta (write_full + xattrs)' });
      steps.push({ from: 1, to: 3, key: 'rg_s_comp', v: v, ref: 'UpdateIndex::complete, rgw_bucket_complete_op (+ bilog)' });
      steps.push({ from: 1, to: 0, key: 'rg_s_ok', dash: true, ref: 'RGWPutObj_ObjStore_S3::send_response (rgw_rest_s3.cc)' });
    } else {
      v.p = L(Math.ceil(st.size / st.part));
      steps.push({ from: 0, to: 1, key: 'rg_m_init', ref: 'RGWInitMultipart::execute' });
      steps.push({ from: 1, to: 2, key: 'rg_s_auth', ref: 'rgw::auth::s3::AWSAuthStrategy (rgw_auth_s3.cc)' });
      steps.push({ from: 1, to: 4, key: 'rg_m_meta', v: v, ref: 'RadosMultipartUpload::init' });
      steps.push({ from: 0, to: 1, key: 'rg_m_part', v: v, ref: 'RGWPutObj::execute + MultipartObjectProcessor::process' });
      steps.push({ from: 1, to: 4, key: 'rg_m_pdata', v: v, ref: 'MultipartObjectProcessor::complete (omap on the meta object)' });
      steps.push({ from: 0, to: 1, key: 'rg_m_comp', v: v, ref: 'RGWCompleteMultipart::execute, RadosMultipartUpload::complete' });
      steps.push({ from: 1, to: 3, key: 'rg_s_prep', v: v, ref: 'UpdateIndex::prepare, rgw_bucket_prepare_op' });
      steps.push({ from: 1, to: 4, key: 'rg_m_head', v: v, ref: 'RGWRados::Object::Write::_do_write_meta (manifest of parts)' });
      steps.push({ from: 1, to: 3, key: 'rg_s_comp', v: v, ref: 'UpdateIndex::complete, rgw_bucket_complete_op' });
      steps.push({ from: 1, to: 0, key: 'rg_m_ok', v: v, dash: true, ref: 'RGWCompleteMultipart_ObjStore_S3::send_response' });
    }
    return steps;
  }
  S.DEFS.rgwput = {
    icon: 'M4 9l8-5 8 5v10H4zM9 19v-6h6v6',
    defaults: function () { return { key: 'photos/2026/11/img_0001.jpg', size: 10, mode: 'atomic', part: 5, shards: 11, i: 0 }; },
    steps: function (st) { return rgPlan(st).length; },
    refs: [['src/rgw/rgw_op.cc :: RGWPutObj::execute, RGWCompleteMultipart::execute', 'r_rg_op'], ['src/rgw/driver/rados/rgw_putobj_processor.cc :: AtomicObjectProcessor, MultipartObjectProcessor', 'r_rg_proc'],
           ['src/rgw/driver/rados/rgw_rados.cc :: Object::Write::_do_write_meta, Bucket::UpdateIndex::prepare / complete', 'r_rg_meta'],
           ['src/cls/rgw/cls_rgw.cc :: rgw_bucket_prepare_op, rgw_bucket_complete_op', 'r_rg_cls'],
           ['src/rgw/services/svc_bi_rados.h :: bucket_shard_index; src/common/ceph_hash.cc :: ceph_str_hash_linux', 'r_rg_shard'],
           ['src/rgw/driver/rados/rgw_obj_manifest.cc :: RGWObjManifest (head, stripes, rgw_obj_stripe_size 4M)', 'r_rg_man']],
    controls: function (st) {
      return '<div class="sim-row">' + field(T('rg_key'), '<input type="text" dir="ltr" spellcheck="false" data-k="key" value="' + esc(st.key) + '">') + field(T('rg_size'), numIn('size', st.size, 0, 4096, 1)) + '</div>'
        + '<div class="sim-row"><div class="sim-f"><span>' + esc(T('rg_mode')) + '</span>' + seg('mode', [['atomic', T('rg_atomic')], ['multipart', 'multipart']], st.mode) + '</div>'
        + (st.mode === 'multipart' ? field(T('rg_part'), numIn('part', st.part, 5, 1024, 1)) : '') + field('bucket_index_max_shards', sel('shards', [1, 11, 23, 101, 1999], st.shards)) + '</div>';
    },
    view: function (st, all) {
      var size = st.size * M, parts = null;
      if (st.mode === 'multipart') { parts = []; for (var left = size; left > 0; left -= st.part * M) parts.push(Math.min(st.part * M, left)); if (!parts.length) parts = [0]; }
      var objs = C.rgwLayout(st.key, size, parts ? { parts: parts } : {}), shard = C.bucketShardIndex(st.key, st.shards), hsh = C.strHashLinux(st.key);
      var steps = rgPlan(st), i = clamp(st.i, 0, steps.length - 1), shown = objs.slice(0, 40);
      var list = '<ol class="rg-objs" dir="ltr">' + shown.map(function (o) { return '<li class="ns-' + o.ns + '"><span>' + esc(o.name) + '</span><b>' + bytes(o.len) + (o.meta ? ' + xattrs' : '') + '</b></li>'; }).join('')
        + (objs.length > shown.length ? '<li>… +' + (objs.length - shown.length) + '</li>' : '') + '</ol>';
      return '<div class="sim-stats">' + stat(L(objs.length), T('rg_s_objs')) + stat('.dir.MARKER.' + shard, T('rg_s_shard')) + stat(bytes(size), T('rg_s_size')) + '</div>'
        + '<div class="sim-formula" dir="ltr">ceph_str_hash_linux("' + esc(st.key) + '") = ' + hsh + ' → sid ^ ((sid &amp; 0xff) &lt;&lt; 24) → % ' + (st.shards <= 7877 ? 7877 : 65521) + ' % ' + st.shards + ' = <b>' + shard + '</b></div>'
        + '<figure class="sim-fig">' + seqSVG(T('rg_lanes').split('|'), steps, i, all) + '</figure>' + stepBox(steps, i, all)
        + '<details class="rg-lay" open><summary>' + esc(T('rg_layout')) + '</summary>' + list + '<p class="sim-note">' + tx('rg_note') + '</p></details>';
    },
    say: function (st) { var s = rgPlan(st)[clamp(st.i, 0, 99)]; return s ? T(s.key + '_s') : ''; },
    input: function (st, k, v) {
      if (k === 'key') { st.key = String(v).slice(0, 200) || 'object'; st.i = 0; return 'out'; }
      if (k === 'size') { st.size = clamp(parseInt(v, 10) || 0, 0, 4096); st.i = 0; return 'out'; }
      if (k === 'part') { st.part = clamp(parseInt(v, 10) || 5, 5, 1024); st.i = 0; return 'out'; }
      if (k === 'mode') { st.mode = v; st.i = 0; return 'all'; }
      if (k === 'shards') { st.shards = +v; return 'out'; }
      return null;
    }
  };
  S.seqSVG = seqSVG;
})(typeof self !== 'undefined' ? self : this);
