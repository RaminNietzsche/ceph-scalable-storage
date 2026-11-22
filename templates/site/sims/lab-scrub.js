/* Scrub windows and random scheduling. CC BY-NC-SA 4.0, Ramin Najarbashi.
 * src/osd/scrubber/scrub_job.cc adjust_{shallow,deep}_schedule; osd_scrub.cc isbetween_modulo.
 * The seeded draws are for repeatable teaching, not Ceph's random engine. */
(function(root) {
  'use strict';
  var NODE = typeof module !== 'undefined' && module.exports,
    S = NODE ? require('./sims.js') : root.Sims,
    h = S.h,
    T = h.T,
    tx = h.tx,
    L = h.L,
    esc = h.esc,
    field = h.field,
    sel = h.sel,
    numIn = h.numIn,
    stat = h.stat;

  function between(f, t, p) {
    return t === f || !!((t >= f) ^ (p >= f) ^ (p < t));
  }

  function delay(kind, interval, ratio, draw) {
    return kind === 'deep' ? Math.max(interval - 2 * interval * ratio, Math.min(interval + 2 * interval * ratio, interval + interval * ratio *
      draw)) : interval * (1 + ratio * draw);
  }

  function random(seed) {
    return function() {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return (seed + 0.5) / 4294967296;
    };
  }

  function samples(st) {
    var r = random(st.seed),
      a = [];
    for (var i = 0; i < st.pgs; i++) {
      var u = r(),
        z = Math.sqrt(-2 * Math.log(r())) * Math.cos(2 * Math.PI * r());
      a.push(delay(st.kind, st.interval, st.ratio, st.kind === 'deep' ? z : u));
    }
    return a;
  }

  function nextHour(day, begin, end) {
    var hour = day * 24;
    for (var i = 0; i < 169; i++) {
      if (between(begin, end, Math.floor(hour) % 24)) return hour / 24;
      hour = Math.floor(hour) + 1;
    }
    return null;
  }
  S.X = S.X || {};
  S.X.scrub = {
    between: between,
    delay: delay,
    nextHour: nextHour,
    test: function(t) {
      var g = t.G.scrub_window;
      [24, 7].forEach(function(n) {
        var a = '';
        for (var f = 0; f < n; f++)
          for (var e = 0; e < n; e++)
            for (var p = 0; p < n; p++) a += between(f, e, p) ? '1' : '0';
        t.eq(a, g[n === 24 ? 'hours' : 'days'], 'all ' + n + '-slot windows match Ceph C++');
      });
      t.eq(delay('shallow', 1, .5, 0), 1, 'shallow lower bound');
      t.eq(delay('shallow', 1, .5, 1), 1.5, 'shallow upper bound');
      t.eq(delay('deep', 7, .2, -5), 4.199999999999999, 'deep clipped at -2 sigma');
      t.eq(delay('deep', 7, .2, 5), 9.8, 'deep clipped at +2 sigma');
      t.eq(nextHour(1.5, 22, 6), 46 / 24, 'overnight window starts at 22');
      t.eq(nextHour(1.1, 22, 6), 1.1, 'overnight window includes 02');
    }
  };
  S.DEFS.scrub = {
    icon: 'M5 5h14v14H5zM8 2v6M16 2v6M5 10h14M9 14l2 2 4-4',
    defaults: function() {
      return {
        kind: 'shallow',
        interval: 1,
        ratio: .5,
        pgs: 128,
        begin: 22,
        end: 6,
        seed: 7
      };
    },
    refs: [
      ['src/osd/scrubber/scrub_job.cc :: adjust_shallow_schedule, adjust_deep_schedule', 'scrub_r1'],
      ['src/osd/scrubber/osd_scrub.cc :: isbetween_modulo, scrub_time_permit', 'scrub_r2'],
      ['src/common/options/osd.yaml.in :: osd_scrub_*', 'scrub_r3']
    ],
    controls: function(st) {
      return '<div class="sim-row">' + field(T('scrub_kind'), sel('kind', [
          ['shallow', T('scrub_shallow')],
          ['deep', T('scrub_deep')]
        ], st.kind)) + field(T('scrub_interval'), numIn('interval', st.interval, .1, 30, .1)) + field(T('scrub_ratio'), numIn('ratio', st.ratio,
          0, .49, .01)) + field('PGs', sel('pgs', [32, 64, 128, 256], st.pgs)) + '</div><div class="sim-row">' + field('osd_scrub_begin_hour',
          sel('begin', h.range(0, 23), st.begin)) + field('osd_scrub_end_hour', sel('end', h.range(0, 23), st.end)) +
        '<button type="button" class="sim-btn" data-act="draw">' + esc(T('scrub_draw')) + '</button></div>';
    },
    view: function(st) {
      var a = samples(st),
        b = a.map(function(x) {
          return nextHour(x, st.begin, st.end);
        }),
        min = Math.min.apply(null, a),
        max = Math.max.apply(null, a),
        avg = b.reduce(function(s, x, i) {
          return s + x - a[i];
        }, 0) / a.length,
        W = 640,
        H = 210,
        range = st.interval * (1 + Math.max(1, st.ratio * 2)) + .5,
        x = function(d) {
          return 35 + 580 * d / range;
        };
      var svg = '<svg class="lx-svg" viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + esc(T('scrub_fig')) + '" dir="ltr">';
      for (var day = 0; day < Math.ceil(range); day++) {
        svg += '<line x1="' + x(day) + '" x2="' + x(day) + '" y1="15" y2="175" class="lx-gl"/><text x="' + x(day) + '" y="195" class="lx-th">' +
          day + 'd</text>';
      }
      a.forEach(function(d, i) {
        var y = 20 + (i % 24) * 6;
        svg += '<line x1="' + x(d) + '" x2="' + x(b[i]) + '" y1="' + y + '" y2="' + y + '" class="lx-line"/><circle cx="' + x(d) +
          '" cy="' + y + '" r="2" class="lx-dot"/><circle cx="' + x(b[i]) + '" cy="' + (y + 2) + '" r="2" fill="var(--sim-hot)"/>';
      });
      svg += '</svg>';
      var hours = h.range(0, 23).map(function(hr) {
        return '<span class="sim-pill" style="opacity:' + (between(st.begin, st.end, hr) ? 1 : .3) + '">' + L(hr) + '</span>';
      }).join(' ');
      return '<div class="sim-stats">' + stat(h.num(min, 2) + '–' + h.num(max, 2), T('scrub_s_range')) + stat(h.num(avg * 24, 1) + ' h', T(
          'scrub_s_wait')) + stat(L(h.range(0, 23).filter(function(hr) {
          return between(st.begin, st.end, hr);
        }).length) + '/24', T('scrub_s_window')) + '</div><div class="lx-btns" dir="ltr">' + hours + '</div><div class="sim-fig">' + svg +
        '</div><p class="sim-note">' + tx('scrub_legend') + '</p><div class="sim-formula" dir="ltr">' + (st.kind === 'deep' ?
          'delay = clamp(N(interval, interval × CV), interval ± 2σ)' : 'delay = interval × (1 + ratio × U[0,1))') +
        '</div><p class="sim-note">' + tx('scrub_note') + '</p>';
    },
    input: function(st, k, v) {
      if (k === 'kind') {
        st.kind = v;
        st.interval = v === 'deep' ? 7 : 1;
        st.ratio = v === 'deep' ? .2 : .5;
        return 'all';
      }
      var n = +v;
      if (!isFinite(n)) return null;
      st[k] = k === 'ratio' ? h.clamp(n, 0, .5) : k === 'interval' ? h.clamp(n, .1, 30) : n;
      return 'out';
    },
    act: function(st, a) {
      if (a === 'draw') {
        st.seed++;
        return 'out';
      }
      return null;
    }
  };
  if (!NODE && S.boot) S.boot();
})(typeof self !== 'undefined' ? self : this);
