"""Convert the book's Pandoc-flavoured Markdown into the internal block stream.

Source files use standard Pandoc Markdown:

* YAML front matter (``---`` ... ``---``)
* fenced divs for callouts: ``::: {.tip}``, ``.warn``, ``.note``, ``.try``,
  ``.deep``, ``.debug``, ``.box``, ``.summary title="..."``, ``.tldr`` (the chapter-opening TL;DR list)
* ``::: {.algo #alg-NN-K title="..." src="..." complexity="..."}`` + ``:::``
* ``::: {.sim name="crush"}`` + ``:::``: an interactive simulator of the web edition
* figures: ``![caption](figures/chNN/name.png){#fig-NN-name}``
* pipe tables
* headings with explicit ids: ``# Title {#sec-NN-K}``

The internal stream is a list of lines in the legacy directive syntax
(``!TIP``, ``!IMG path|caption`` ...) that ``build_book.py`` renders to HTML.
Keeping the two in a reversible mapping lets ``tests`` prove that the
migration from the legacy sources is lossless.
"""
from __future__ import annotations

import re

CALLOUTS = {"tip": "!TIP", "warn": "!WARN", "note": "!NOTE", "try": "!TRY",
            "deep": "!DEEP", "debug": "!DEBUG"}
DIRECTIVE_OF = {v: k for k, v in CALLOUTS.items()}

_ATTR = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"')
_DIV_OPEN = re.compile(r'^:::+\s*\{(.*)\}\s*$')
_IMG = re.compile(r'^!\[(.*)\]\((\S+?)\)\{#([\w:.-]+)\}\s*$')
_HID = re.compile(r'\s+\{#[\w:.-]+\}\s*$')


def attr_escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


def attr_unescape(s: str) -> str:
    return re.sub(r'\\(.)', r'\1', s)


def _split_code(s: str):
    """Yield (is_code, text) segments, code spans delimited by backticks."""
    for k, part in enumerate(re.split(r'(`[^`]*`)', s)):
        if part:
            yield (part.startswith('`') and part.endswith('`') and len(part) >= 2), part


def bracket_escape(s: str) -> str:
    return ''.join(p if c else p.replace('[', '\\[').replace(']', '\\]') for c, p in _split_code(s))


def bracket_unescape(s: str) -> str:
    return ''.join(p if c else p.replace('\\[', '[').replace('\\]', ']') for c, p in _split_code(s))


def parse_div(line: str):
    m = _DIV_OPEN.match(line)
    if not m:
        return None
    inner = m.group(1)
    classes = re.findall(r'(?:^|\s)\.([\w-]+)', _ATTR.sub('', inner))
    ident = re.findall(r'(?:^|\s)#([\w:.-]+)', _ATTR.sub('', inner))
    attrs = {k: attr_unescape(v) for k, v in _ATTR.findall(inner)}
    return classes, (ident[0] if ident else ''), attrs


def split_front_matter(text: str):
    """Return (yaml_text, body_lines)."""
    lines = text.split('\n')
    if lines and lines[0].strip() == '---':
        for i in range(1, len(lines)):
            if lines[i].strip() in ('---', '...'):
                return '\n'.join(lines[1:i]), lines[i + 1:]
    return '', lines


def _cells(row: str):
    row = row.strip()
    if row.startswith('|'):
        row = row[1:]
    if row.endswith('|') and not row.endswith('\\|'):
        row = row[:-1]
    return [c.strip() for c in re.split(r'(?<!\\)\|', row)]


def lower(lines, resolve_image=None):
    """Lower Pandoc-flavoured lines to the internal directive stream."""
    out = []
    i = 0
    n = len(lines)
    while i < n:
        l = lines[i]
        if l.startswith('```'):
            j = i + 1
            while j < n and not lines[j].startswith('```'):
                j += 1
            out.extend(lines[i:j + 1])
            i = j + 1
            continue
        d = parse_div(l)
        if d:
            classes, ident, attrs = d
            j = i + 1
            body = []
            while j < n and not re.match(r'^:::+\s*$', lines[j]):
                body.append(lines[j])
                j += 1
            content = [b for b in body if b.strip()]
            kind = classes[0] if classes else ''
            if kind == 'algo':
                out.append(f"!ALGO {attrs.get('title', '')}|{attrs.get('src', '')}|{attrs.get('complexity', '')}")
            elif kind == 'sim':
                out.append(f"!SIM {attrs.get('name', '')}")
            elif kind in CALLOUTS:
                if content:
                    out.append(CALLOUTS[kind] + ' ' + content[0])
                    out.extend('+ ' + b for b in content[1:])
            elif kind == 'box':
                out.append('!BOX')
                out.extend(content)
                out.append('!ENDBOX')
            elif kind == 'signature':
                out.extend('!SIGN ' + b for b in content)
            elif kind == 'tldr':
                out.append('!TLDR')
                out.extend(content)
                out.append('!ENDTLDR')
            elif kind == 'summary':
                t = attrs.get('title', '')
                out.append('!SUM' + (' ' + t if t else ''))
                out.extend(content)
                out.append('!ENDSUM')
            else:
                out.extend(content)
            i = j + 1
            continue
        m = _IMG.match(l)
        if m:
            cap, path = bracket_unescape(m.group(1)), m.group(2)
            if resolve_image:
                path = resolve_image(path)
            out.append(f'!IMG {path}|{cap}')
            i += 1
            continue
        if l.startswith('|') and i + 1 < n and re.match(r'^\|?\s*:?-{3,}', lines[i + 1]):
            hdr = _cells(l)
            j = i + 2
            rows = []
            while j < n and lines[j].startswith('|'):
                rows.append(_cells(lines[j]))
                j += 1
            out.append('!TABLE ' + '|'.join(hdr))
            out.extend('|'.join(r) for r in rows)
            out.append('!ENDTABLE')
            i = j
            continue
        if re.match(r'^#{1,6} ', l):
            out.append(_HID.sub('', l))
            i += 1
            continue
        out.append(l)
        i += 1
    return out


def heading_ids(lines, chap: int):
    """Yield (line_index, level, id) for numbered headings (level 1 and 2)."""
    inc = False
    n1 = n2 = 0
    for k, l in enumerate(lines):
        if l.startswith('```'):
            inc = not inc
            continue
        if inc:
            continue
        m = re.match(r'^(#{1,2}) ', l)
        if not m:
            continue
        if len(m.group(1)) == 1:
            n1 += 1
            n2 = 0
            yield k, 1, f'sec-{chap:02d}-{n1}'
        else:
            n2 += 1
            yield k, 2, f'sec-{chap:02d}-{n1}-{n2}'
