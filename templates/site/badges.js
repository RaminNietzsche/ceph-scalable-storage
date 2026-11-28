/* Badge art renderer for the web edition. tools/render_badges.py prepends the data
   (window.__BADGES__: SVG defs, frame shapes, categories and one glyph per badge, made from
   references/badges.yaml) and writes the result to assets/badges.js; game.js calls
   BadgeArt.svg(id, tier, opt) wherever a badge is shown. Pure SVG, no images, no network. */
(function () {
  'use strict';
  var A = window.__BADGES__;
  if (!A) return;
  var mounted = false;
  function mount() {
    if (mounted || document.getElementById('bdg-defs')) { mounted = true; return; }
    var box = document.createElement('div');
    box.innerHTML = A.defs;
    var s = box.firstChild;
    // the defs must stay rendered (display:none would drop the gradients), so park them off-screen
    document.body.insertBefore(s, document.body.firstChild);
    mounted = true;
  }
  function star(cx, cy, r) {
    var p = [];
    for (var i = 0; i < 10; i++) {
      var a = Math.PI / 5 * i - Math.PI / 2, rr = i % 2 ? r * 0.45 : r;
      p.push((cx + rr * Math.cos(a)).toFixed(2) + ' ' + (cy + rr * Math.sin(a)).toFixed(2));
    }
    return 'M' + p.join('L') + 'Z';
  }
  /* id: badge id; tier: 0 (locked) to 3; opt.hidden: draw the secret face; opt.pop: play the unlock animation;
     opt.cls: extra classes. The SVG is decorative (aria-hidden): the caller puts the name and tier in text. */
  function svg(id, tier, opt) {
    opt = opt || {};
    mount();
    var b = A.b[id];
    if (!b) return '';
    var shape = A.cats[b.c].s, sh = A.shapes[shape], locked = !tier;
    var rim = locked ? 'ml' : (b.c === 'secret' ? 'mh' : 'm' + tier), metal = locked ? 'ml' : 'm' + tier;
    var field = locked ? 'fl' : 'f-' + b.c, glyph = opt.hidden ? 'secret' : id, g = sh.g;
    var o = ['<svg class="bdg s-' + shape + ' c-' + b.c + (locked ? ' locked' : ' t' + tier) + (opt.pop ? ' pop' : '') + (opt.cls ? ' ' + opt.cls : '') +
      '" viewBox="0 0 64 64" aria-hidden="true" focusable="false">'];
    if (sh.tails) o.push('<path d="' + sh.tails + '" fill="url(#bdg-' + field + ')"/><path d="' + sh.tails + '" fill="#000" opacity=".22"/>');
    o.push('<path class="bdg-rim" d="' + sh.rim + '" fill="url(#bdg-' + rim + ')" stroke="url(#bdg-' + rim + ')" stroke-width="3" stroke-linejoin="round"/>');
    o.push('<path d="' + sh.field + '" fill="url(#bdg-' + field + ')" stroke="#000" stroke-opacity=".28" stroke-width="1.4"/>');
    o.push('<g clip-path="url(#bdg-k-' + shape + ')"><ellipse cx="32" cy="' + sh.gloss + '" rx="30" ry="15" fill="#fff" opacity=".16"/></g>');
    var at = ' x="' + g[0] + '" y="' + g[1] + '" width="' + g[2] + '" height="' + g[2] + '"';
    o.push('<use class="bdg-gs" href="#bdg-g-' + glyph + '"' + at + ' transform="translate(0 .9)"/>');
    o.push('<use class="bdg-gl" href="#bdg-g-' + glyph + '"' + at + '/>');
    if (b.c === 'secret' && !locked) o.push('<circle cx="32" cy="7" r="3.4" fill="url(#bdg-m' + tier + ')" stroke="#fff" stroke-width=".8"/>');
    if (b.t === 'tiered') {
      o.push('<path class="bdg-ban" d="' + sh.banner + '" fill="url(#bdg-' + metal + ')" stroke="#000" stroke-opacity=".25" stroke-width=".8"/>');
      for (var i = 1; i <= 3; i++) o.push('<path class="bdg-st' + (i <= tier ? ' on' : '') + '" d="' + star(18 + i * 7, 53.3, 3.3) + '"/>');
    }
    o.push('<g clip-path="url(#bdg-k-' + shape + ')"><g class="bdg-shine"><rect x="-6" y="-8" width="10" height="84" fill="url(#bdg-sh)" transform="rotate(22 32 32)"/></g></g>');
    if (locked) o.push('<circle class="bdg-lk" cx="' + sh.lock[0] + '" cy="' + sh.lock[1] + '" r="8.5"/><use class="bdg-lkg" href="#bdg-g-lock" x="' + (sh.lock[0] - 5.75) + '" y="' + (sh.lock[1] - 5.75) + '" width="11.5" height="11.5"/>');
    o.push('</svg>');
    return o.join('');
  }
  window.BadgeArt = { svg: svg, mount: mount, cat: function (id) { return A.b[id] ? A.b[id].c : null; },
    tiered: function (id) { return !!(A.b[id] && A.b[id].t === 'tiered'); }, cats: A.order, ids: A.ids };
})();
