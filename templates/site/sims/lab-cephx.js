/* cephx tickets, step by step (lab, loaded on demand). CC BY-NC-SA 4.0, Ramin Najarbashi.
 * The message flow and the key that protects each part follow doc/dev/cephx.rst (Nautilus and later);
 * the code is src/auth/cephx (CephxServiceHandler, CephxClientHandler, CephxProtocol, CephxKeyServer). */
(function (root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports;
  var S = NODE ? require('./sims.js') : root.Sims;
  var h = S.h, T = h.T, tx = h.tx, L = h.L, esc = h.esc, sel = h.sel, field = h.field, stat = h.stat;
  // keys: ps = client principal secret, rauth = AUTH rotating secret, rosd = OSD rotating secret,
  //       ska = auth session key, sko = OSD session key, cs = connection secret
  var KNOW0 = { client: ['ps'], mon: ['ps', 'rauth', 'rosd'], osd: ['rosd'] };
  // each part: [label, key or null (plain), who must open it (or '' if opaque to the receiver), keys it reveals]
  var STEPS = [
    { from: 'client', to: 'mon', id: 'hello', parts: [['auth method = cephx, name = client.app', null, 'mon', []]] },
    { from: 'mon', to: 'client', id: 'chal', parts: [['CephxServerChallenge (server_challenge)', null, 'client', []]] },
    { from: 'client', to: 'mon', id: 'getkey', parts: [['CEPHX_GET_AUTH_SESSION_KEY, client_challenge', null, 'mon', []], ['key = digest(client_challenge, server_challenge)', 'ps', 'mon', []]] },
    { from: 'mon', to: 'client', id: 'ticket', parts: [['CephxServiceTicket (auth session_key, expires)', 'ps', 'client', ['ska']], ['CephxTicketBlob (AuthTicket: name, global_id, caps)', 'rauth', '', []],
        ['connection_secret', 'ska', 'client', ['cs']], ['OSD CephxServiceTicket (OSD session_key)', 'ska', 'client', ['sko']], ['OSD CephxTicketBlob (session_key, AuthTicket, caps)', 'rosd', '', []]] },
    { from: 'client', to: 'osd', id: 'authz', parts: [['global_id, service_id = OSD', null, 'osd', []], ['OSD CephxTicketBlob', 'rosd', 'osd', ['sko']], ['CephxAuthorize (nonce)', 'sko', 'osd', []]] },
    { from: 'osd', to: 'client', id: 'achal', parts: [['CephxAuthorizeChallenge (server_challenge)', 'sko', 'client', []]] },
    { from: 'client', to: 'osd', id: 'authz2', parts: [['OSD CephxTicketBlob', 'rosd', 'osd', []], ['CephxAuthorize (new nonce, server_challenge + 1)', 'sko', 'osd', []]] },
    { from: 'osd', to: 'client', id: 'reply', parts: [['CephxAuthorizeReply (nonce + 1, connection secret)', 'sko', 'client', []]] },
    { from: 'osd', to: 'mon', id: 'rotate', parts: [['CEPHX_GET_ROTATING_KEY', null, 'mon', []], ['new OSD rotating secret (current and previous kept)', 'osdkey', 'osd', []]] }
  ];
  // where each attack stops the flow
  var ATTACK = { none: -1, wrongkey: 2, replay: 6, oldkey: 4, expired: 4 };
  function knowledge(upto) {
    var k = { client: KNOW0.client.slice(), mon: KNOW0.mon.slice(), osd: KNOW0.osd.slice().concat(['osdkey']) };
    k.mon.push('osdkey');
    for (var i = 0; i <= upto && i < STEPS.length; i++) STEPS[i].parts.forEach(function (p) { if (p[2]) p[3].forEach(function (x) { if (k[p[2]].indexOf(x) < 0) k[p[2]].push(x); }); });
    return k;
  }

  S.X = S.X || {};
  S.X.cephx = {
    STEPS: STEPS, knowledge: knowledge,
    test: function (t) {
      // every part a receiver must open is protected by a key it already holds when the message arrives
      STEPS.forEach(function (s, i) {
        var k = knowledge(i - 1);
        s.parts.forEach(function (p) {
          if (p[2]) p[3].forEach(function (x) { if (p[1] === null || k[p[2]].indexOf(p[1]) >= 0) k[p[2]].push(x); });
          if (p[2]) t.ok(p[1] === null || k[p[2]].indexOf(p[1]) >= 0 || (p[1] === 'rosd' && k[p[2]].indexOf('rosd') >= 0), s.id + ': ' + p[2] + ' can open "' + p[0] + '"');
          else t.ok(k[s.to].indexOf(p[1]) < 0, s.id + ': "' + p[0] + '" stays opaque to the ' + s.to);
        });
      });
      // the client never learns a rotating service secret; the OSD never learns the client's principal secret
      var all = knowledge(STEPS.length);
      t.ok(all.client.indexOf('rosd') < 0 && all.client.indexOf('rauth') < 0, 'client never holds a service secret');
      t.ok(all.osd.indexOf('ps') < 0, 'OSD never holds the client secret');
      t.ok(all.osd.indexOf('sko') >= 0 && all.client.indexOf('sko') >= 0, 'client and OSD share the OSD session key');
      // no secret ever travels in clear
      STEPS.forEach(function (s) { s.parts.forEach(function (p) { if (p[1] === null) t.ok(!/session_key|secret/.test(p[0]) || /auth method|ROTATING/.test(p[0]), 'plain part carries no key: ' + p[0]); }); });
      Object.keys(ATTACK).forEach(function (a) { t.ok(ATTACK[a] < STEPS.length, 'attack ' + a + ' stops inside the flow'); });
    }
  };

  var KEYCLS = { ps: 'k1', rauth: 'k2', rosd: 'k3', ska: 'k4', sko: 'k5', osdkey: 'k1' };
  S.DEFS.cephx = {
    icon: 'M15 7a4 4 0 11-3.5 6H9v2H7v2H4v-3l6.5-6.5A4 4 0 0115 7z',
    defaults: function () { return { i: 0, attack: 'none' }; },
    refs: [['doc/dev/cephx.rst :: Phase I, Phase III, Rotating service secrets', 'cephx_r1'],
           ['src/auth/cephx/CephxServiceHandler.cc, CephxClientHandler.cc, CephxProtocol.cc', 'cephx_r2'],
           ['src/auth/cephx/CephxKeyServer.cc :: rotating secrets', 'cephx_r3'],
           ['src/common/options/global.yaml.in :: auth_service_ticket_ttl (1 h), auth_mon_ticket_ttl (72 h)', 'cephx_r4']],
    steps: function () { return STEPS.length; },
    controls: function (st) {
      return '<div class="sim-row">' + field(T('cephx_attack'), sel('attack', Object.keys(ATTACK).map(function (a) { return [a, T('cephx_a_' + a)]; }), st.attack)) + '</div>';
    },
    view: function (st) {
      var i = Math.min(st.i, STEPS.length - 1), s = STEPS[i], stop = ATTACK[st.attack], failed = stop >= 0 && i >= stop, k = knowledge(failed ? stop - 1 : i);
      var X = { client: 70, mon: 320, osd: 570 }, W = 640, svg = '<svg class="lx-svg" viewBox="0 0 ' + W + ' 130" role="img" aria-label="' + esc(T('cephx_fig')) + '" dir="ltr">';
      ['client', 'mon', 'osd'].forEach(function (e) { svg += '<rect x="' + (X[e] - 55) + '" y="10" width="110" height="34" rx="8" class="lx-bg"/><text x="' + X[e] + '" y="32" text-anchor="middle" class="lx-th">' + esc(T('cephx_e_' + e)) + '</text><line x1="' + X[e] + '" x2="' + X[e] + '" y1="44" y2="125" class="lx-gl"/>'; });
      var y = 85, x1 = X[s.from], x2 = X[s.to], dir = x2 > x1 ? 1 : -1;
      svg += '<line x1="' + x1 + '" x2="' + (x2 - dir * 8) + '" y1="' + y + '" y2="' + y + '" stroke="' + (failed && i === stop ? 'var(--sim-bad)' : 'var(--sim-a)') + '" stroke-width="3"/>'
        + '<path d="M' + x2 + ' ' + y + ' l' + (-dir * 12) + ' -6 v12 z" fill="' + (failed && i === stop ? 'var(--sim-bad)' : 'var(--sim-a)') + '"/>'
        + '<text x="' + ((x1 + x2) / 2) + '" y="' + (y - 10) + '" text-anchor="middle" class="lx-th">' + esc(L(i + 1)) + '</text></svg>';
      var parts = s.parts.map(function (p) {
        var opaque = !p[2], can = p[1] === null || k[s.to].indexOf(p[1]) >= 0;
        return '<li class="cx-part ' + (p[1] ? KEYCLS[p[1]] : 'plain') + '"><span class="lx-mono" dir="ltr">' + (p[1] ? '{ ' + esc(p[0]) + ' }<sup>' + esc(T('cephx_k_' + p[1])) + '</sup>' : esc(p[0])) + '</span> <small>' + esc(T(opaque ? 'cephx_opaque' : can ? 'cephx_open' : 'cephx_cannot', { e: T('cephx_e_' + s.to) })) + '</small></li>';
      }).join('');
      var ring = ['client', 'mon', 'osd'].map(function (e) {
        return '<div class="lx-card dim"><h4>' + esc(T('cephx_e_' + e)) + '</h4><p>' + k[e].filter(function (x) { return x !== 'cs'; }).map(function (x) { return '<span class="cx-key ' + (KEYCLS[x] || 'plain') + '">' + esc(T('cephx_k_' + x)) + '</span>'; }).join(' ') + '</p></div>';
      }).join('');
      return '<div class="sim-stats">' + stat(L(i + 1) + ' / ' + L(STEPS.length), T('cephx_s_step')) + stat(failed ? T('cephx_fail') : i === STEPS.length - 1 || i === 7 ? T('cephx_done') : '…', T('cephx_s_state'), failed ? 'warn' : '') + '</div>'
        + '<div class="sim-fig">' + svg + '</div>'
        + '<div class="lx-card ' + (failed && i === stop ? 'bad' : 'on') + '"><h4>' + esc(T('cephx_t_' + s.id)) + '</h4><p>' + tx('cephx_b_' + s.id) + '</p><ul class="cx-parts">' + parts + '</ul>'
        + (failed && i >= stop ? '<p class="sim-warn">' + tx('cephx_f_' + st.attack) + '</p>' : '') + '</div>'
        + '<h4>' + esc(T('cephx_ring')) + '</h4><div class="lx-grid">' + ring + '</div>'
        + '<p class="sim-note">' + tx('cephx_note') + '</p>';
    },
    input: function (st, k, v) { if (k === 'attack') { st.attack = v; return 'out'; } return null; },
    say: function (st) { return T('cephx_t_' + STEPS[Math.min(st.i, STEPS.length - 1)].id); },
    fallbackState: function (st) { st.i = 3; return st; }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
