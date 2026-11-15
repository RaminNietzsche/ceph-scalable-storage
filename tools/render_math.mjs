#!/usr/bin/env node
// Render the book's inline TeX formulas offline with KaTeX (no CDN, no browser).
// stdin: JSON array of TeX strings. stdout: JSON array of HTML strings
// (KaTeX HTML + MathML). The web edition styles them with the bundled
// katex.min.css and fonts; render_pdf.py drops the MathML copy so the PDF
// (WeasyPrint) keeps one selectable, TeX-typeset rendering.
//
// KaTeX is taken from node_modules (npm install) when present, otherwise from
// the copy vendored in templates/vendor/katex/katex.min.js, so a fresh clone
// builds with Node.js alone and no npm install.
import { createRequire } from 'node:module';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const require = createRequire(import.meta.url);
const here = path.dirname(fileURLToPath(import.meta.url));
const vendored = path.join(here, '..', 'templates', 'vendor', 'katex', 'katex.min.js');

function loadKatex() {
  try {
    return require('katex');
  } catch (e) {
    if (existsSync(vendored)) return require(vendored);
    process.stderr.write('render_math: KaTeX not found. Run `npm install` or restore ' +
      path.relative(process.cwd(), vendored) + ' (vendored KaTeX 0.19.1).\n');
    process.exit(3);
  }
}

const katex = loadKatex();
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const out = JSON.parse(raw || '[]').map((tex) =>
    katex.renderToString(tex, { output: 'htmlAndMathml', throwOnError: true, strict: 'error' }));
  process.stdout.write(JSON.stringify(out));
});
