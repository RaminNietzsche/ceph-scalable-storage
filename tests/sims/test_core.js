#!/usr/bin/env node
/*
 * Unit tests for templates/site/sims/sim-core.js (no dependencies; `make check-sims`).
 * Reference data: tests/sims/golden.json, produced from an unmodified Ceph tree by
 * tools/simref/gen_golden.py (Ceph's own C CRUSH code and pg_autoscaler module),
 * plus the vectors of Ceph's src/test/test_striper.cc and the book's worked examples.
 */
'use strict';
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const C = require(path.join(__dirname, '..', '..', 'templates', 'site', 'sims', 'sim-core.js'));
const G = JSON.parse(fs.readFileSync(path.join(__dirname, 'golden.json'), 'utf8'));
let pass = 0, fail = 0;
const fails = [];
function eq(a, b, what) {
  const ok = JSON.stringify(a) === JSON.stringify(b);
  if (ok) pass++; else { fail++; if (fails.length < 25) fails.push(`${what}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`); }
}
function near(a, b, what, eps) { if (Math.abs(a - b) <= (eps || 1e-6)) pass++; else { fail++; fails.push(`${what}: got ${a} want ${b}`); } }
const groups = {};
function group(name, fn) { const p0 = pass, f0 = fail; fn(); groups[name] = [pass - p0, fail - f0]; }

group('crush_hash32_2 / _3 (rjenkins1)', () => {
  G.hash32_2.forEach(([a, b, h]) => eq(C.hash2(a, b), h, `hash2(${a},${b})`));
  G.hash32_3.forEach(([a, b, c, h]) => eq(C.hash3(a, b, c), h, `hash3(${a},${b},${c})`));
});
group('ceph_str_hash_rjenkins', () => G.str_hash.forEach(([s, h]) => eq(C.strHash(s), h, `str_hash(${s})`)));
group('ceph_str_hash_linux + rgw bucket_shard_index', () => {
  G.str_hash_linux.forEach(([s, h]) => eq(C.strHashLinux(s), h, `str_hash_linux(${s})`));
  // the book's chapter 4 example (sec-04-10-4): shard of three keys with 11 and 23 shards
  [['photos/2026/11/img_0001.jpg', 11, 5], ['photos/2026/11/img_0002.jpg', 11, 10], ['logs/app.log', 11, 9],
   ['photos/2026/11/img_0001.jpg', 23, 18], ['photos/2026/11/img_0002.jpg', 23, 21], ['logs/app.log', 23, 2]]
    .forEach(([k, n, want]) => eq(C.bucketShardIndex(k, n), want, `shard(${k}, ${n})`));
  eq(C.strHashLinux('photos/2026/11/img_0001.jpg'), 2668161921, 'book hash img_0001');
});
group('crush_ln (all 65536 inputs)', () => {
  const v = [];
  for (let u = 0; u <= 0xffff; u++) v.push(String(C.crushLn(u)));
  eq(crypto.createHash('sha256').update(v.join('\n')).digest('hex'), G.ln.sha256, 'crush_ln sha256');
  Object.entries(G.ln.sample).forEach(([u, x]) => eq(C.crushLn(+u), x, `crush_ln(${u})`));
});
group('straw2 exponential draws', () => G.draw.forEach(([x, y, z, w, d]) => eq(C.expDraw(x, y, z, w), d, `draw(${x},${y},${z},${w})`)));
group('crush_do_rule: replicated firstn and EC indep, through raw_pg_to_pps', () => {
  G.crush.forEach((c) => {
    const m = C.makeMap(c.map.buckets.map((b) => ({ id: b.id, type: b.type, items: b.items.map((x) => x[0]), weights: b.items.map((x) => x[1]) })), G.crush_rules);
    for (let ps = 0; ps < c.pgp_num; ps++) {
      const x = C.pps(ps, c.pgp_num, c.pool);
      eq(C.doRule(m, c.rule, x, c.size, c.weights), c.expect[ps], `${c.name} ps ${ps}`);
    }
  });
});
group('pg_autoscaler (module.py four passes)', () => {
  G.autoscaler.forEach((c, i) => {
    const r = C.autoscale(c.osds, c.target, c.pools);
    r.pools.forEach((p, j) => {
      const [name, fpass, pg, ratio, adj] = c.expect[j];
      eq([p.name, p.pass, p.pg, p.adjust], [name, fpass, pg, adj], `autoscale case ${i} pool ${name}`);
      near(p.ratio, ratio, `autoscale case ${i} ratio ${name}`, 1e-8);
    });
  });
});
group('Striper (src/test/test_striper.cc vectors)', () => {
  const l = { object_size: 262144, stripe_unit: 4096, stripe_count: 3 };
  const ex = C.fileToExtents(l, 5006035, 46419, 5006035);
  eq(ex.length, 3, 'Stripe1 size');
  eq(ex[0].truncate_size, 98304, 'Stripe1 ex[0].truncate_size');
  eq(ex[1].offset, ex[1].truncate_size, 'Stripe1 ex[1] offset == truncate_size');
  eq(ex[2].truncate_size, 94208, 'Stripe1 ex[2].truncate_size');
  const e2 = C.fileToExtents({ object_size: 4194304, stripe_unit: 4194304, stripe_count: 1 }, 725549056, 131072, 72554905600);
  eq(e2.length, 2, 'EmptyPartialResult size');
  eq([C.numObjects(l, 6999), C.numObjects(l, 793320), C.numObjects(l, 805608)], [2, 5, 6], 'GetNumObj');
  eq(C.fileOffset(l, 100, 200000), 26549568, 'GetFileOffset');
});
group('Striper invariants and the book example (chapter 37)', () => {
  // the book: object_size 4 MiB, stripe_unit 64 KiB, stripe_count 4, a 300000-byte write at 1000000
  const l = { object_size: 4 << 20, stripe_unit: 64 << 10, stripe_count: 4 };
  const ex = C.fileToExtents(l, 1000000, 300000, 0);
  eq(ex.map((e) => e.object_no), [0, 1, 2, 3], 'book example objects');
  eq(ex.reduce((s, e) => s + e.length, 0), 300000, 'book example bytes');
  let seed = 7;
  const rnd = (n) => { seed = (Math.imul(seed, 1103515245) + 12345) >>> 0; return seed % n; };
  for (let t = 0; t < 400; t++) {
    const order = 16 + rnd(7), os = 2 ** order, su = os >> rnd(Math.min(5, order - 12)), sc = 1 + rnd(8);
    const L = { object_size: os, stripe_unit: su, stripe_count: sc };
    const off = rnd(64 * os), len = 1 + rnd(6 * os);
    const e = C.fileToExtents(L, off, len, 0);
    const pieces = [];
    e.forEach((x) => { let o = x.offset; x.buffer_extents.forEach(([bo, bl]) => { pieces.push([bo, bl, x.object_no, o]); o += bl; }); });
    pieces.sort((a, b) => a[0] - b[0]);
    let cur = 0, ok = true;
    pieces.forEach(([bo, bl, ono, oo]) => { if (bo !== cur) ok = false; if (C.fileOffset(L, ono, oo) !== off + bo) ok = false; cur += bl; });
    eq([ok, cur], [true, len], `round trip ${JSON.stringify(L)} ${off}~${len}`);
  }
  eq(C.rbdDataName('10226b8b4567', 255), 'rbd_data.10226b8b4567.00000000000000ff', 'rbd_data name');
});
group('EC and replication formulas', () => {
  eq(C.ecPool(4, 2, 'jerasure', {}).minSize, 5, 'k=4 m=2 min_size (book ch. 13)');
  eq(C.ecPool(2, 1, 'isa', {}).minSize, 2, 'k=2 m=1 min_size');
  eq(C.repPool(3).minSize, 2, 'size 3 min_size');
  eq(C.ecPool(4, 2, 'lrc', { l: 3 }).chunks, 8, 'lrc k=4 m=2 l=3 chunks');
  near(C.ecPool(4, 2, 'clay', { d: 5 }).repairRead, 2.5, 'clay d=5 repair read');
  eq(C.pgcalc(100, 10, 1, 3).pg, 256, 'pgcalc 10 OSDs 100% size 3 (333 -> 256, within 25%)');
  eq(C.pgcalc(100, 10, 1.08, 3).pg, 512, 'pgcalc 360 -> 512 (256 is more than 25% below)');
});
group('RGW layout (book ch. 4 example)', () => {
  const s = C.rgwLayout('photo.jpg', 10 << 20, {});
  eq(s.map((o) => [o.ns, o.len]), [['head', 4 << 20], ['shadow', 4 << 20], ['shadow', 2 << 20]], '10 MiB PUT');
  const m = C.rgwLayout('big.iso', 20 << 20, { parts: [10 << 20, 10 << 20] });
  eq(m.length, 7, 'multipart 2 x 10 MiB = 7 RADOS objects');
});
group('BlueStore write path decisions', () => {
  const hdd = { minAlloc: 4096, preferDeferred: 65536, block: 4096 }, ssd = { minAlloc: 4096, preferDeferred: 0, block: 4096 };
  eq(C.bluestoreWrite(0, 16384, { ...hdd, overwrite: false }).deferNew, true, 'HDD new 16K -> deferred');
  eq(C.bluestoreWrite(0, 1 << 20, { ...hdd, overwrite: false }).deferNew, false, 'HDD new 1M -> direct');
  eq(C.bluestoreWrite(0, 16384, { ...ssd, overwrite: false }).deferNew, false, 'SSD new 16K -> direct');
  eq(C.bluestoreWrite(100, 1000, { ...ssd, overwrite: true }).pieces[0].deferred, true, 'SSD small overwrite -> deferred');
});
Object.entries(groups).forEach(([n, [p, f]]) => console.log(`${f ? 'FAIL' : 'ok  '} ${n}: ${p} passed${f ? `, ${f} failed` : ''}`));
fails.forEach((f) => console.log('  ' + f));
console.log(`sims: ${pass} checks passed, ${fail} failed (reference: ceph ${String(G.ceph_rev).slice(0, 12)})`);
process.exit(fail ? 1 : 0);
