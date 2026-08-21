#!/usr/bin/env node
/*
 * Static fallback figures of the interactive simulators (used by tools/build_site.py).
 * Reads {"lang": "fa"|"en", "strings": {...}, "names": [...]} on stdin and writes
 * {"html": {name: "<html>"}, "icon": {name: "<svg path>"}, "names": [...]} on stdout: the same view code as the browser, of a fixed
 * state, so print and no-JavaScript readers see a real snapshot of each simulator.
 */
'use strict';
const path = require('path');
const dir = path.join(__dirname, '..', 'templates', 'site', 'sims');
const S = require(path.join(dir, 'sims.js'));
for (const part of ['crush', 'calc', 'peering', 'flow', 'striping', 'ui']) require(path.join(dir, `sim-${part}.js`));
let buf = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { buf += c; });
process.stdin.on('end', () => {
  const req = JSON.parse(buf), out = { html: {}, icon: {}, names: Object.keys(S.DEFS) };
  for (const n of req.names || Object.keys(S.DEFS)) { out.html[n] = S.staticHTML(n, req.strings, req.lang); out.icon[n] = S.DEFS[n].icon; }
  process.stdout.write(JSON.stringify(out));
});
