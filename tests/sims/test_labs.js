#!/usr/bin/env node
/*
 * Tests for the labs that the site loads on demand (templates/site/sims/lab-*.js; `make check-sims`).
 * Reference data: tests/sims/golden-labs.json, produced by tools/simref/gen_golden_labs.py from an
 * unmodified Ceph tree (functions cut out of the Ceph sources and compiled unchanged) and from
 * jerasure and gf-complete, plus published test vectors. Every lab also renders its view in both languages.
 */
'use strict';
const path = require('path');
const fs = require('fs');
const dir = path.join(__dirname, '..', '..', 'templates', 'site', 'sims');
const yaml = (f) => fs.readFileSync(path.join(dir, f), 'utf8');
const S = require(path.join(dir, 'sims.js'));
require(path.join(dir, 'sim-ui.js'));
const NAMES = [...yaml('labs.yaml').matchAll(/^- (\w+)$/gm)].map((m) => m[1]);
NAMES.forEach((n) => require(path.join(dir, `lab-${n}.js`)));
const G = fs.existsSync(path.join(__dirname, 'golden-labs.json')) ? JSON.parse(fs.readFileSync(path.join(__dirname, 'golden-labs.json'), 'utf8')) : {};
let pass = 0, fail = 0;
const fails = [];
const T = {
  eq(a, b, what) { const ok = JSON.stringify(a) === JSON.stringify(b); if (ok) pass++; else { fail++; if (fails.length < 30) fails.push(`${what}: got ${JSON.stringify(a)} want ${JSON.stringify(b)}`); } },
  ok(c, what) { if (c) pass++; else { fail++; if (fails.length < 30) fails.push(what); } },
  near(a, b, what, eps) { if (Math.abs(a - b) <= (eps || 1e-9)) pass++; else { fail++; if (fails.length < 30) fails.push(`${what}: got ${a} want ${b}`); } },
  G, S
};
const groups = {};
function group(name, fn) { const p0 = pass, f0 = fail; fn(); groups[name] = [pass - p0, fail - f0]; }

// strings: every key a lab uses exists in both languages, and the Persian file has no key the English one lacks
function keys(f) { return new Set([...yaml(f).matchAll(/^([a-z0-9_]+):/gm)].map((m) => m[1])); }
const KF = keys('strings-fa.yaml'), KE = keys('strings-en.yaml');
group('strings in both languages', () => {
  for (const k of KF) T.ok(KE.has(k), `strings-en.yaml lacks ${k}`);
  for (const k of KE) T.ok(KF.has(k), `strings-fa.yaml lacks ${k}`);
  for (const n of NAMES) for (const k of ['_t', '_d', '_what', '_limit']) T.ok(KF.has(n + k), `missing ${n}${k}`);
});

// the per-lab tests: each lab-NAME.js exports S.X[NAME].test(T) next to its code
for (const n of NAMES) {
  const X = (S.X || {})[n];
  if (X && X.test) group(`lab ${n}`, () => X.test(T));
}

// every lab renders its static figure in both languages without throwing and without leftover {placeholders}
const ys = (f) => { const o = {}; for (const m of yaml(f).matchAll(/^([a-z0-9_]+): (.*)$/gm)) { let v = m[2]; if (v.startsWith('"')) v = JSON.parse(v); o[m[1]] = v; } return o; };
group('views render (fa, en)', () => {
  for (const [lang, f] of [['fa', 'strings-fa.yaml'], ['en', 'strings-en.yaml']]) {
    const strings = ys(f);
    for (const n of NAMES) {
      let h = '';
      try { h = S.staticHTML(n, strings, lang); } catch (e) { T.ok(false, `${n} (${lang}) throws: ${e.message}`); continue; }
      T.ok(h.length > 200, `${n} (${lang}) renders`);
      T.ok(!/\{[a-z]\w*\}/.test(h.replace(/<code[^>]*>[\s\S]*?<\/code>|<pre[\s\S]*?<\/pre>/g, '')), `${n} (${lang}) has an unfilled {placeholder}`);
      T.ok(!new RegExp('>' + n + '_[a-z0-9_]+<').test(h), `${n} (${lang}) shows a raw string key`);
      const def = S.DEFS[n], st = def.defaults();
      try { def.controls(st); } catch (e) { T.ok(false, `${n} (${lang}) controls throw: ${e.message}`); }
      if (def.steps) { const k = def.steps(st); for (let i = 0; i < k; i++) { st.i = i; try { def.view(st, false); } catch (e) { T.ok(false, `${n} step ${i} (${lang}) throws: ${e.message}`); } } }
    }
  }
});

for (const [g, [p, f]] of Object.entries(groups)) console.log(`${f ? 'FAIL' : 'ok  '} ${g}: ${p} passed${f ? `, ${f} failed` : ''}`);
console.log(`labs: ${pass} checks passed, ${fail} failed (${NAMES.length} labs)`);
if (fail) { fails.forEach((x) => console.log('  ' + x)); process.exit(1); }
