#!/usr/bin/env node
// Render the book's inline TeX formulas offline with KaTeX (no CDN, no browser).
// stdin: JSON array of TeX strings. stdout: JSON array of HTML strings
// (KaTeX HTML + MathML). The web edition styles them with the bundled
// katex.min.css and fonts; render_pdf.py drops the MathML copy so the PDF
// (WeasyPrint) keeps one selectable, TeX-typeset rendering.
import { createRequire } from 'node:module';
const require = createRequire(import.meta.url);
const katex = require('katex');

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (c) => { raw += c; });
process.stdin.on('end', () => {
  const out = JSON.parse(raw || '[]').map((tex) =>
    katex.renderToString(tex, { output: 'htmlAndMathml', throwOnError: true, strict: 'error' }));
  process.stdout.write(JSON.stringify(out));
});
