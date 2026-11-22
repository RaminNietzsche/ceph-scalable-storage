/* Classic monitor elections and quorum, CC BY-NC-SA 4.0, Ramin Najarbashi.
 * doc/dev/mon-elections.rst; src/mon/ElectionLogic.cc end_election_period; src/mon/Paxos.cc handle_accept. */
(function(root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports,
    S = NODE ? require('./sims.js') : root.Sims,
    h = S.h,
    T = h.T,
    tx = h.tx,
    esc = h.esc,
    L = h.L;

  function groups(n, split, down) {
    var a = [],
      b = [];
    for (var i = 0; i < n; i++)
      if (down.indexOf(i) < 0)(i < split ? a : b).push(i);
    return [a, b];
  }

  function result(n, split, down) {
    return groups(n, split, down).map(function(g) {
      return {
        members: g,
        leader: g.length > n / 2 ? Math.min.apply(null, g) : null
      };
    });
  }
  S.X = S.X || {};
  S.X.quorum = {
    result: result,
    test: function(t) {
      for (var n = 1; n <= 9; n += 2)
        for (var split = 0; split <= n; split++)
          for (var mask = 0; mask < (1 << n); mask++) {
            var d = [];
            for (var i = 0; i < n; i++)
              if (mask & (1 << i)) d.push(i);
            var r = result(n, split, d),
              q = r.filter(function(g) {
                return g.leader !== null;
              });
            t.ok(q.length <= 1, 'no two disjoint majority quorums ' + n + ':' + split + ':' + mask);
            q.forEach(function(g) {
              t.eq(g.leader, Math.min.apply(null, g.members), 'classic chooses lowest reachable rank');
            });
          }
      t.eq(result(5, 3, [])[0].leader, 0, '3/5 majority');
      t.eq(result(5, 3, [0])[0].leader, null, '2/5 cannot elect');
    }
  };
  S.DEFS.quorum = {
    icon: 'M12 3v5M4 18l4-5M20 18l-4-5M9 8h6v5H9zM1 18h6v4H1zM17 18h6v4h-6z',
    defaults: function() {
      return {
        n: 5,
        split: 3,
        down: [],
        i: 0
      };
    },
    refs: [
      ['doc/dev/mon-elections.rst :: The Original Algorithm', 'quorum_r1'],
      ['src/mon/ElectionLogic.cc :: end_election_period, receive_ack', 'quorum_r2'],
      ['src/mon/Paxos.cc :: handle_accept, accept_timeout, lease_ack_timeout', 'quorum_r3']
    ],
    controls: function(st) {
      var bs = '';
      for (var i = 0; i < st.n; i++) bs += '<button type="button" class="lx-tbtn" data-act="down" data-p="' + i + '" aria-pressed="' + (st.down
        .indexOf(i) >= 0) + '">mon.' + i + '</button>';
      return '<div class="sim-row">' + h.field(T('quorum_n'), h.sel('n', [3, 5, 7, 9], st.n)) + h.field(T('quorum_split'), h.sel('split', h
          .range(0, st.n), st.split)) + '</div><div class="lx-btns" dir="ltr">' + bs + '</div><p class="sim-note">' + tx('quorum_toggle') +
        '</p>';
    },
    steps: function() {
      return 5;
    },
    view: function(st) {
      var gs = result(st.n, st.split, st.down),
        win = gs.filter(function(g) {
          return g.leader !== null;
        })[0],
        W = 640,
        H = 180,
        svg = '<svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('quorum_fig')) + '" dir="ltr">';

      function pos(id) {
        return {
          x: 35 + (id + .5) * 570 / st.n,
          y: id < st.split ? 50 : 130
        };
      }
      for (var i = 0; i < st.n; i++)
        for (var j = i + 1; j < st.n; j++) {
          var a = pos(i),
            b = pos(j),
            live = st.down.indexOf(i) < 0 && st.down.indexOf(j) < 0,
            same = (i < st.split) === (j < st.split);
          if (same && live) svg += '<line x1="' + a.x + '" y1="' + a.y + '" x2="' + b.x + '" y2="' + b.y + '" class="lx-gl"/>';
        }
      for (var id = 0; id < st.n; id++) {
        var p = pos(id),
          off = st.down.indexOf(id) >= 0,
          lead = win && win.leader === id;
        svg += '<circle cx="' + p.x + '" cy="' + p.y + '" r="21" fill="' + (off ? 'var(--sim-bad)' : lead ? 'var(--sim-ok)' : 'var(--sim-c0)') +
          '" opacity="' + (off ? .35 : 1) + '"/><text x="' + p.x + '" y="' + (p.y + 4) + '" fill="white" text-anchor="middle" font-size="12">' +
          id + '</text>';
      }
      svg += '</svg>';
      var cards = gs.map(function(g) {
        return '<div class="lx-card ' + (g.leader !== null ? 'on' : 'bad') + '"><h4 dir="ltr">{' + g.members.join(', ') + '}</h4><p>' + tx(g
          .leader !== null ? 'quorum_yes' : 'quorum_no', {
            n: L(g.members.length),
            q: L(Math.floor(st.n / 2) + 1),
            l: L(g.leader)
          }) + '</p></div>';
      }).join('');
      return '<div class="sim-stats">' + h.stat(L(Math.floor(st.n / 2) + 1), T('quorum_s_need')) + h.stat(L(Math.floor((st.n - 1) / 2)), T(
          'quorum_s_fail')) + h.stat(win ? 'mon.' + win.leader : '—', T('quorum_s_lead')) + '</div><div class="sim-fig">' + svg +
        '</div><div class="lx-grid">' + cards + '</div><div class="lx-card on"><h4>' + esc(T('quorum_step' + st.i)) + '</h4><p>' + tx(
          'quorum_body' + st.i) + '</p></div><p class="sim-note">' + tx('quorum_note') + '</p>';
    },
    input: function(st, k, v) {
      st[k] = +v;
      if (k === 'n') {
        st.split = Math.min(st.split, st.n);
        st.down = st.down.filter(function(x) {
          return x < st.n;
        });
        return 'all';
      }
      return 'out';
    },
    act: function(st, a, el) {
      if (a === 'down') {
        var i = +el.getAttribute('data-p'),
          x = st.down.indexOf(i);
        if (x < 0) st.down.push(i);
        else st.down.splice(x, 1);
        return 'all';
      }
      return null;
    }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
