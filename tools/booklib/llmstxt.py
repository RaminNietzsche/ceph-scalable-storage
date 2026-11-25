"""LLM-facing catalogue (llms.txt), full-text dumps and per-page Markdown alternates.

The catalogue follows https://llmstxt.org/ (v2): an H1, a blockquote summary,
optional notes, then H2 sections of Markdown file lists. Per-page files live at
``/<lang>/<slug>.md``. The English full text is ``/llms-full.txt``; the Persian
full text is ``/fa/llms-full.txt``.
"""
from __future__ import annotations

import glob
import os
import re
from html import unescape

import yaml
from bs4 import BeautifulSoup, NavigableString, Tag

from booklib.mdlower import split_front_matter

CONCEPT_DOI = '10.5281/zenodo.24253822'
LICENSE = 'CC BY-NC-SA 4.0'
LICENSE_URL = 'https://creativecommons.org/licenses/by-nc-sa/4.0/'
AUTHOR = 'Ramin Najarbashi'
VERSIONS = ('Reef', 'Squid', 'Tentacle', 'Umbrella')
FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')

# Appendices that have a committed Markdown source (the rest are generated).
APP_SRC = {
    'troubleshooting': os.path.join('appendices', 'troubleshooting.md'),
    'versions': os.path.join('appendices', 'versions.md'),
    'upgrade': os.path.join('appendices', 'upgrade.md'),
}

# Pages included in llms-full.txt, in reading order (slug, kind).
FULL_ORDER = (
    ('preface', 'front'),
    # chapters are inserted by number
    ('glossary', 'appendix'),
    ('cheatsheet', 'appendix'),
    ('troubleshooting', 'appendix'),
    ('versions', 'appendix'),
    ('answers', 'appendix'),
    ('bibliography', 'appendix'),
    ('algorithms', 'appendix'),
    ('changes', 'appendix'),
    ('upgrade', 'appendix'),
)

CALLOUT_LABEL = {
    'tip': 'Tip', 'warn': 'Warning', 'note': 'Note', 'try': 'Try it',
    'deep': 'Deeper', 'debug': 'Troubleshooting', 'tldr': 'TL;DR',
    'box': 'Box', 'summary': 'Summary',
}

_DIV_OPEN = re.compile(r'^:::+\s*\{(.*)\}\s*$')
_HEAD_ID = re.compile(r'\s+\{#[\w:.-]+\}\s*$')
_IMG = re.compile(r'^!\[(.*)\]\((\S+?)\)(?:\{#[\w:.-]+\})?\s*$')
_TLDR_IMG = re.compile(r'^\[!\[(.*)\]\((\S+?)\)\]\(#([\w:.-]+)\)\s*$')
_ATTR = re.compile(r'([\w-]+)="((?:[^"\\]|\\.)*)"')


def loc(n, lang):
    s = str(n)
    return s.translate(FA_DIGITS) if lang == 'fa' else s


def lastmod_date(date):
    """Return a W3C date (YYYY-MM-DD). Month-only values become YYYY-MM-01."""
    s = str(date or '').strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return s
    if re.fullmatch(r'\d{4}-\d{2}', s):
        return s + '-01'
    m = re.search(r'(\d{4}-\d{2}-\d{2})', s)
    if m:
        return m.group(1)
    raise ValueError(f'cannot turn {date!r} into a YYYY-MM-DD lastmod')


def _ui(root, lang):
    return yaml.safe_load(open(os.path.join(root, 'content', lang, 'ui.yaml'), encoding='utf-8'))


def _meta(root, lang):
    return yaml.safe_load(open(os.path.join(root, 'content', lang, 'metadata.yaml'), encoding='utf-8'))


def chapter_files(root, lang):
    """Return [(number, slug, path, title), ...] in chapter order."""
    out = []
    for path in sorted(glob.glob(os.path.join(root, 'content', lang, 'chapters', '[0-9][0-9]-*.md'))):
        text = open(path, encoding='utf-8').read()
        fm, _ = split_front_matter(text)
        data = yaml.safe_load(fm) or {}
        slug = os.path.splitext(os.path.basename(path))[0]
        out.append((int(data['chapter']), slug, path, str(data.get('title') or slug)))
    out.sort(key=lambda r: r[0])
    return out


def clean_source_markdown(text, fig_prefix='../figures/'):
    """Turn a book source file into a cleaner Markdown page for agents."""
    _, body = split_front_matter(text)
    out, i, n = [], 0, len(body)
    while i < n:
        line = body[i]
        m = _DIV_OPEN.match(line.rstrip())
        if m:
            inner = m.group(1)
            attrs = {k: v for k, v in _ATTR.findall(inner)}
            kind = None
            for tok in inner.replace('.', ' ').split():
                if tok in CALLOUT_LABEL or tok in ('algo', 'sim'):
                    kind = tok
                    break
            block = []
            i += 1
            depth = 1
            while i < n:
                if _DIV_OPEN.match(body[i].rstrip()):
                    depth += 1
                    block.append(body[i])
                elif re.match(r'^:::+\s*$', body[i].rstrip()):
                    depth -= 1
                    if depth == 0:
                        break
                    block.append(body[i])
                else:
                    block.append(body[i])
                i += 1
            inner_md = clean_source_markdown('---\n---\n' + '\n'.join(block), fig_prefix=fig_prefix).strip()
            if kind == 'sim':
                name = attrs.get('name') or 'simulator'
                out.append(f'\n*Interactive simulator `{name}` — available in the HTML edition.*\n')
            elif kind == 'algo':
                title = attrs.get('title') or 'Algorithm'
                bits = [f'\n#### Algorithm: {title}']
                if attrs.get('src'):
                    bits.append(f'*Source: `{attrs["src"]}`*')
                if attrs.get('complexity'):
                    bits.append(f'*Complexity: {attrs["complexity"]}*')
                bits.append(inner_md)
                out.append('\n'.join(bits) + '\n')
            elif kind:
                label = CALLOUT_LABEL.get(kind, kind)
                if attrs.get('title'):
                    label = f'{label}: {attrs["title"]}'
                quoted = '\n'.join('> ' + (ln if ln.strip() else '') for ln in (f'**{label}**\n\n{inner_md}').split('\n'))
                out.append('\n' + quoted + '\n')
            else:
                out.append(inner_md)
            i += 1
            continue
        im = _IMG.match(line.rstrip())
        if im:
            cap, src = im.group(1), im.group(2)
            if src.startswith('figures/'):
                src = fig_prefix.rstrip('/') + '/' + src[len('figures/'):]
            out.append(f'![{cap}]({src})')
            if cap:
                out.append(f'*Figure. {cap}*')
            i += 1
            continue
        tim = _TLDR_IMG.match(line.rstrip())
        if tim:
            cap, src, tgt = tim.groups()
            if src.startswith('figures/'):
                src = fig_prefix.rstrip('/') + '/' + src[len('figures/'):]
            out.append(f'[![{cap}]({src})](#{tgt})')
            i += 1
            continue
        out.append(_HEAD_ID.sub('', line))
        i += 1
    # collapse 3+ blank lines
    text = re.sub(r'\n{3,}', '\n\n', '\n'.join(out)).strip() + '\n'
    return text


def html_to_md(node):
    """A compact HTML-to-Markdown conversion for generated book pages."""
    if node is None:
        return ''
    if isinstance(node, NavigableString):
        return unescape(str(node)).replace('\xa0', ' ')
    if not isinstance(node, Tag):
        return ''
    if node.name in ('script', 'style', 'svg', 'button', 'form', 'nav', 'template'):
        return ''
    if node.name in ('h1', 'h2', 'h3', 'h4', 'h5', 'h6'):
        hashes = '#' * int(node.name[1])
        return f'\n{hashes} {_inline(node).strip()}\n'
    if node.name == 'p':
        t = _inline(node).strip()
        return f'\n{t}\n' if t else ''
    if node.name == 'pre':
        return '\n```\n' + node.get_text() + '\n```\n'
    if node.name == 'blockquote':
        inner = ''.join(html_to_md(c) for c in node.children).strip()
        return '\n' + '\n'.join('> ' + (ln if ln.strip() else '') for ln in inner.split('\n')) + '\n'
    if node.name in ('ul', 'ol'):
        items = []
        for i, li in enumerate(node.find_all('li', recursive=False), 1):
            mark = f'{i}.' if node.name == 'ol' else '-'
            items.append(f'{mark} {_inline(li).strip()}')
        return '\n' + '\n'.join(items) + '\n'
    if node.name == 'table':
        return '\n' + _table(node) + '\n'
    if node.name in ('br',):
        return '  \n'
    if node.name in ('hr',):
        return '\n---\n'
    if node.name in ('div', 'section', 'article', 'main', 'td', 'th', 'span', 'li', 'body', 'html'):
        return ''.join(html_to_md(c) for c in node.children)
    return _inline(node)


def _inline(node):
    if node is None:
        return ''
    if isinstance(node, NavigableString):
        return re.sub(r'\s+', ' ', unescape(str(node)).replace('\xa0', ' '))
    if not isinstance(node, Tag):
        return ''
    if node.name in ('script', 'style', 'svg', 'button'):
        return ''
    if node.name in ('strong', 'b'):
        return f'**{_inline_children(node)}**'
    if node.name in ('em', 'i'):
        return f'*{_inline_children(node)}*'
    if node.name == 'code':
        return f'`{node.get_text()}`'
    if node.name == 'a' and node.get('href'):
        href = node['href']
        text = _inline_children(node).strip() or href
        return f'[{text}]({href})'
    if node.name == 'img':
        return f'![{node.get("alt") or ""}]({node.get("src") or ""})'
    if node.name == 'br':
        return ' '
    return _inline_children(node)


def _inline_children(node):
    return ''.join(_inline(c) for c in node.children)


def _table(table):
    rows = []
    for tr in table.find_all('tr'):
        cells = [_inline(c).strip() for c in tr.find_all(['th', 'td'])]
        if cells:
            rows.append(cells)
    if not rows:
        return ''
    width = max(len(r) for r in rows)
    rows = [r + [''] * (width - len(r)) for r in rows]
    lines = ['| ' + ' | '.join(rows[0]) + ' |']
    lines.append('| ' + ' | '.join('---' for _ in rows[0]) + ' |')
    for r in rows[1:]:
        lines.append('| ' + ' | '.join(r) + ' |')
    return '\n'.join(lines)


def _page_header(title, lang, slug, u, extra=None):
    lines = [f'# {title}', '']
    if extra:
        lines.append(extra.rstrip())
        lines.append('')
    html = u.root(f'{lang}/{slug}.html')
    lines.append(f'*HTML: {html}*')
    lines.append(f'*Licence: {LICENSE}. Author: {AUTHOR}.*')
    lines.append('')
    return '\n'.join(lines) + '\n'


def answers_markdown(root, lang, fig_prefix='../figures/'):
    parts = []
    for path in sorted(glob.glob(os.path.join(root, 'content', lang, 'answers', '*.md'))):
        text = open(path, encoding='utf-8').read()
        fm, _ = split_front_matter(text)
        data = yaml.safe_load(fm) or {}
        n = data.get('chapter') or os.path.splitext(os.path.basename(path))[0]
        parts.append(f'## {("فصل" if lang == "fa" else "Chapter")} {loc(n, lang)}\n')
        parts.append(clean_source_markdown(text, fig_prefix=fig_prefix).strip())
    return '\n\n'.join(parts).strip() + '\n'


def write_page_markdown(out_dir, slug, title, lang, u, root=None, source=None,
                        html=None, kind=None, lead=None):
    """Write ``<out_dir>/<slug>.md`` and return its path."""
    os.makedirs(out_dir, exist_ok=True)
    fig_prefix = u.root('figures/') if u.base else '../figures/'
    body = ''
    if source and os.path.exists(source):
        body = clean_source_markdown(open(source, encoding='utf-8').read(), fig_prefix=fig_prefix)
    elif slug == 'answers' and root:
        body = answers_markdown(root, lang, fig_prefix=fig_prefix)
    elif html:
        soup = BeautifulSoup(html, 'html.parser') if isinstance(html, str) else html
        body = re.sub(r'\n{3,}', '\n\n', html_to_md(soup)).strip() + '\n'
    elif lead:
        body = lead.strip() + '\n'
    else:
        body = ''
    text = _page_header(title, lang, slug, u) + body
    path = os.path.join(out_dir, f'{slug}.md')
    open(path, 'w', encoding='utf-8').write(text)
    return path


def _href(u, rel):
    return u.root(rel)


def write_llms_txt(out, u, root, version='1.6'):
    """Write the root catalogue ``llms.txt`` with links to every chapter and appendix .md."""
    books = {l: _ui(root, l)['book'] for l in ('en', 'fa')}
    ui = {l: _ui(root, l) for l in ('en', 'fa')}
    chs = {l: chapter_files(root, l) for l in ('en', 'fa')}
    summary = (
        f'The Comprehensive Ceph Guide (Persian: {books["fa"]}) is a bilingual open handbook '
        f'(Persian original, English translation) by {AUTHOR}. It covers Ceph operations through '
        f'the source and on-disk layout, kept current for {", ".join(VERSIONS[:-1])} and {VERSIONS[-1]} '
        f'(version {version}). The text is licensed under {LICENSE}. '
        f'Concept DOI: https://doi.org/{CONCEPT_DOI}.'
    )
    lines = [
        f'# {books["en"]} · {books["fa"]}',
        '',
        f'> {summary}',
        '',
        'Each HTML page has a Markdown alternate at the same path with a `.md` extension '
        '(`rel="alternate" type="text/markdown"`). Prefer those files, or the full-text dumps below, '
        f'when citing or indexing this book. Licence: [{LICENSE}]({LICENSE_URL}).',
        '',
        '## English edition',
        '',
        f'- [Preface]({_href(u, "en/preface.md")}): {ui["en"]["preface"]}',
    ]
    for n, slug, _, title in chs['en']:
        lines.append(f'- [Chapter {n}. {title}]({_href(u, f"en/{slug}.md")})')
    lines.append('')
    lines.append('### English appendices')
    lines.append('')
    for key, (letter, title, short) in ui['en']['app'].items():
        lines.append(f'- [Appendix {letter}. {title}]({_href(u, f"en/{key}.md")})')
    lines += [
        '',
        '## Persian edition (متن اصلی)',
        '',
        f'- [مقدمه]({_href(u, "fa/preface.md")}): {ui["fa"]["preface"]}',
    ]
    for n, slug, _, title in chs['fa']:
        lines.append(f'- [فصل {loc(n, "fa")}. {title}]({_href(u, f"fa/{slug}.md")})')
    lines.append('')
    lines.append('### پیوست‌های فارسی')
    lines.append('')
    for key, (letter, title, short) in ui['fa']['app'].items():
        lines.append(f'- [پیوست {letter}. {title}]({_href(u, f"fa/{key}.md")})')
    lines += [
        '',
        '## Full text',
        '',
        f'- [English full text]({_href(u, "llms-full.txt")}): the preface, every chapter and every appendix in one file',
        f'- [Persian full text]({_href(u, "fa/llms-full.txt")}): متن کامل فارسی (مقدمه، فصل‌ها و پیوست‌ها) در یک پرونده',
        '',
        '## Optional',
        '',
        f'- [English HTML edition]({_href(u, "en/index.html")})',
        f'- [Persian HTML edition]({_href(u, "fa/index.html")})',
        f'- [English home (Markdown)]({_href(u, "en/index.md")})',
        f'- [Persian home (Markdown)]({_href(u, "fa/index.md")})',
        f'- [Concept DOI](https://doi.org/{CONCEPT_DOI})',
        f'- [Licence: {LICENSE}]({LICENSE_URL})',
        f'- [Source repository](https://github.com/RaminNietzsche/ceph-scalable-storage)',
        '',
    ]
    path = os.path.join(out, 'llms.txt')
    open(path, 'w', encoding='utf-8').write('\n'.join(lines))
    return path


def write_llms_full(out, u, root, lang, version='1.6'):
    """Write a single-file Markdown dump of one edition."""
    ui = _ui(root, lang)
    book = ui['book']
    meta = _meta(root, lang)
    fig_prefix = u.root('figures/') if u.base else ('figures/' if lang == 'en' else '../figures/')
    header = [
        f'# {book}',
        '',
        f'> {AUTHOR}. Version {meta.get("version", version)}. '
        f'Licence: {LICENSE}. Concept DOI: https://doi.org/{CONCEPT_DOI}. '
        f'Covered Ceph releases: {", ".join(VERSIONS)}.',
        '',
        f'This file is the full text of the {"English translation" if lang == "en" else "original Persian edition"}. '
        f'Individual chapters are also at `/{lang}/<slug>.md`. HTML edition: {_href(u, f"{lang}/index.html")}.',
        '',
    ]
    parts = ['\n'.join(header)]
    # preface
    pref = os.path.join(root, 'content', lang, 'front', 'preface.md')
    if os.path.exists(pref):
        parts.append(f'# {ui["preface"]}\n')
        parts.append(clean_source_markdown(open(pref, encoding='utf-8').read(), fig_prefix=fig_prefix))
    ch_word = 'Chapter' if lang == 'en' else 'فصل'
    for n, slug, path, title in chapter_files(root, lang):
        parts.append(f'# {ch_word} {loc(n, lang)}. {title}\n')
        parts.append(clean_source_markdown(open(path, encoding='utf-8').read(), fig_prefix=fig_prefix))
    app_word = ui.get('appendix') or ('Appendix' if lang == 'en' else 'پیوست')
    for key, (letter, title, short) in ui['app'].items():
        parts.append(f'# {app_word} {letter}. {title}\n')
        src = APP_SRC.get(key)
        if key == 'answers':
            parts.append(answers_markdown(root, lang, fig_prefix=fig_prefix))
        elif src:
            p = os.path.join(root, 'content', lang, src)
            parts.append(clean_source_markdown(open(p, encoding='utf-8').read(), fig_prefix=fig_prefix))
        else:
            md_path = os.path.join(out, lang, f'{key}.md')
            if os.path.exists(md_path):
                # drop the per-page header (first heading + HTML/licence lines)
                text = open(md_path, encoding='utf-8').read()
                text = re.sub(r'^# .*\n+(?:\*.*\n)*\n*', '', text, count=1)
                parts.append(text.strip() + '\n')
            else:
                parts.append(f'*See the HTML appendix: {_href(u, f"{lang}/{key}.html")}*\n')
    text = re.sub(r'\n{3,}', '\n\n', '\n\n'.join(parts)).strip() + '\n'
    if lang == 'en':
        path = os.path.join(out, 'llms-full.txt')
    else:
        os.makedirs(os.path.join(out, 'fa'), exist_ok=True)
        path = os.path.join(out, 'fa', 'llms-full.txt')
    open(path, 'w', encoding='utf-8').write(text)
    return path, len(text.encode('utf-8'))


def write_edition_markdowns(out, u, root, lang, pages, home_lead=None):
    """Write a .md alternate for every emitted page of one edition.

    ``pages`` is an iterable of objects with ``slug``, ``title_text``, ``kind``,
    and optional ``body`` (BeautifulSoup) and ``chap``.
    """
    lout = os.path.join(out, lang)
    os.makedirs(lout, exist_ok=True)
    ch_by_slug = {slug: path for _, slug, path, _ in chapter_files(root, lang)}
    written = []
    # home
    ui = _ui(root, lang)
    meta = _meta(root, lang)
    book = ui['book']
    lead = home_lead or (
        f'{meta.get("subtitle") or ""}\n\n'
        f'Author: {AUTHOR}. Version {meta.get("version")}. Licence: {LICENSE}. '
        f'Concept DOI: https://doi.org/{CONCEPT_DOI}.\n'
    )
    write_page_markdown(lout, 'index', book, lang, u, lead=lead)
    written.append('index')
    for p in pages:
        slug = p.slug
        title = p.title_text
        kind = getattr(p, 'kind', '')
        source = None
        if slug == 'preface':
            source = os.path.join(root, 'content', lang, 'front', 'preface.md')
        elif slug in ch_by_slug:
            source = ch_by_slug[slug]
        elif slug in APP_SRC:
            source = os.path.join(root, 'content', lang, APP_SRC[slug])
        html = None
        if not source and slug != 'answers' and getattr(p, 'body', None) is not None:
            html = p.body
        write_page_markdown(lout, slug, title, lang, u, root=root, source=source, html=html, kind=kind)
        written.append(slug)
    return written


# User-agents explicitly allowed to crawl the book. Bytespider is intentionally
# omitted (not invited). A blanket "User-agent: * / Allow: /" still applies.
AI_BOTS = (
    'GPTBot',
    'OAI-SearchBot',
    'ChatGPT-User',
    'ClaudeBot',
    'Claude-Web',
    'anthropic-ai',
    'PerplexityBot',
    'Google-Extended',
    'Applebot-Extended',
    'CCBot',
    'meta-externalagent',
)


def robots_txt(u):
    """robots.txt: allow the site, name the main AI crawlers, keep Sitemap."""
    lines = ['User-agent: *', 'Allow: /', 'Disallow: /404.html', '']
    for bot in AI_BOTS:
        lines += [f'User-agent: {bot}', 'Allow: /', '']
    if u.base:
        lines += [f'Sitemap: {u.abs("sitemap.xml")}', '']
    else:
        lines += ['# Build with SITE_URL=https://example.org/book to add the absolute Sitemap: line.', '']
    return '\n'.join(lines)
