#!/usr/bin/env python3
"""Render standalone printable A4 multi-column PDF cheat sheets from references/cheatsheet.yaml.

Usage: tools/render_cheatsheet.py --lang fa|en [--out FILE] [--max-pages 4]
"""
from __future__ import annotations

import argparse
import html
import os
import re
import sys

import weasyprint
import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib import cephver  # noqa: E402

FA_DIGITS = str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹')


def esc(s: str) -> str:
    return html.escape(str(s), quote=True)


def loc(s: str | int, lang: str) -> str:
    return str(s).translate(FA_DIGITS) if lang == 'fa' else str(s)


def format_ref(ref: str, lang: str, ui: dict) -> str:
    m = re.match(r'^sec-0?(\d+)-(.+)$', ref)
    if m:
        ch = m.group(1)
        sub = m.group(2).replace('-', '.')
        if lang == 'fa':
            return f'بخش {loc(ch, lang)}.{loc(sub, lang)}'
        return f'§{ch}.{sub}'
    app_map = {
        'appA': 'glossary', 'appB': 'cheatsheet', 'appC': 'troubleshooting',
        'appD': 'versions', 'appF': 'answers', 'appG': 'bibliography',
        'appH': 'algorithms', 'appI': 'changes', 'appJ': 'upgrade', 'appK': 'security', 'appL': 'multisite-dr', 'appM': 'cli-reference',
    }
    key = app_map.get(ref)
    if key and key in ui.get('app', {}):
        letter = ui['app'][key][0]
        return f'{ui["appendix"]} {letter}'
    return ref


def build_html(lang: str) -> str:
    cs = yaml.safe_load(open(os.path.join(ROOT, 'references', 'cheatsheet.yaml'), encoding='utf-8'))
    ui = yaml.safe_load(open(os.path.join(ROOT, 'content', lang, 'ui.yaml'), encoding='utf-8'))
    meta = yaml.safe_load(open(os.path.join(ROOT, 'content', lang, 'metadata.yaml'), encoding='utf-8'))

    rtl = lang == 'fa'
    dir_attr = 'rtl' if rtl else 'ltr'
    font_sans = '"Vazirmatn", "DejaVu Sans", sans-serif' if rtl else '"Inter", "DejaVu Sans", sans-serif'

    if rtl:
        title = 'برگه‌ی تقلب دستورهای Ceph'
        subtitle = f'{ui["book"]} · ویرایش {loc(meta["version_display"], lang)}'
        danger_lbl = '⚠ خطرناک'
        legend = '⚠ دستور پرخطر/تغییردهنده‌ی داده · برچسب‌های نسخه (Squid+ و جدیدتر) حداقل نسخه‌ی مورد نیاز را نشان می‌دهند · پیش‌فرض: Reef 18.2'
        footer_left = f'{ui["book"]} — برگه‌ی تقلب دستورها (CC BY-NC-SA 4.0)'
        page_tpl = 'صفحه counter(page) از counter(pages)'
    else:
        title = 'Ceph Command Cheat Sheet'
        subtitle = f'{ui["book"]} · Edition {meta["version_display"]}'
        danger_lbl = '⚠ Danger'
        legend = '⚠ Destructive or high-risk command · Release badges (Squid+ etc.) mark minimum required release · Baseline: Reef 18.2'
        footer_left = f'{ui["book"]} — Command Cheat Sheet (CC BY-NC-SA 4.0)'
        page_tpl = 'Page counter(page) of counter(pages)'

    cats = cs.get('categories', [])
    n_cmds = sum(len(c.get('commands', [])) for c in cats)
    count_txt = (f'{loc(len(cats), lang)} دسته · {loc(n_cmds, lang)} دستور' if rtl
                 else f'{len(cats)} categories · {n_cmds} commands')

    sections = []
    for cat in cats:
        rows_html = []
        for entry in cat['commands']:
            cmd = entry['cmd']
            desc = entry[lang]
            ref_txt = format_ref(entry['ref'], lang, ui)
            since = entry.get('since')
            danger = bool(entry.get('danger'))
            tags = []
            if danger:
                tags.append(f'<span class="bdg bdg-danger" dir="{dir_attr}">{esc(danger_lbl)}</span>')
            if since and since != cephver.BASELINE:
                tags.append(f'<span class="bdg s-{esc(since)}" dir="ltr">{esc(cephver.label(since, lang))}</span>')
            tags.append(f'<span class="ref" dir="{dir_attr}">{esc(ref_txt)}</span>')
            cls = 'row danger' if danger else 'row'
            rows_html.append(
                f'<div class="{cls}">'
                f'<div class="top" dir="ltr"><code class="cmd">{esc(cmd)}</code>'
                f'<span class="tags">{"".join(tags)}</span></div>'
                f'<div class="desc">{esc(desc)}</div>'
                f'</div>'
            )
        sections.append(
            f'<section class="cat">'
            f'<h2>{esc(cat[lang])}</h2>'
            f'<div class="rows">{"".join(rows_html)}</div>'
            f'</section>'
        )

    css = f"""
@page {{
  size: A4 portrait;
  margin: 8.5mm 8mm 10.5mm 8mm;
  @bottom-left {{
    content: "{esc(footer_left)}";
    font-family: {font_sans};
    font-size: 6.4pt;
    color: #64748b;
  }}
  @bottom-right {{
    content: "https://book.ceph-s3.ir/{lang}/cheatsheet.html";
    font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
    font-size: 6.2pt;
    color: #64748b;
    direction: ltr;
  }}
  @bottom-center {{
    content: {'"صفحه " counter(page, persian) " از " counter(pages, persian)' if rtl else '"Page " counter(page) " of " counter(pages)'};
    font-family: {font_sans};
    font-size: 6.4pt;
    color: #475569;
  }}
}}
* {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  padding: 0;
  font-family: {font_sans};
  font-size: 6.7pt;
  line-height: 1.32;
  color: #0f172a;
}}
.hdr {{
  display: flex;
  justify-content: space-between;
  align-items: flex-end;
  border-bottom: 1.5pt solid #1f3864;
  padding-bottom: 2.2mm;
  margin-bottom: 2mm;
}}
.hdr h1 {{
  margin: 0;
  font-size: 13pt;
  line-height: 1.15;
  color: #1f3864;
  font-weight: 800;
}}
.hdr .sub {{
  margin-top: .5mm;
  font-size: 7.2pt;
  color: #475569;
}}
.hdr .cnt {{
  font-size: 7.2pt;
  font-weight: 700;
  color: #1f3864;
  background: #eef2fa;
  padding: .8mm 2.2mm;
  border-radius: 1.2mm;
  white-space: nowrap;
}}
.legend {{
  font-size: 6.2pt;
  color: #475569;
  background: #f8fafc;
  border: .4pt solid #e2e8f0;
  border-radius: 1mm;
  padding: 1mm 2mm;
  margin-bottom: 2.4mm;
}}
.cols {{
  column-count: 2;
  column-gap: 4mm;
  column-rule: .4pt solid #dce3ee;
}}
.cat {{
  margin-bottom: 2.2mm;
}}
.cat h2 {{
  margin: 0 0 1mm 0;
  padding: .8mm 2mm;
  background: #1f3864;
  color: #ffffff;
  font-size: 7.4pt;
  font-weight: 700;
  border-radius: .9mm;
  break-after: avoid;
  page-break-after: avoid;
}}
.row {{
  padding: .75mm 1.2mm .8mm 1.2mm;
  border-bottom: .35pt solid #e2e8f0;
  break-inside: avoid;
  page-break-inside: avoid;
}}
.row.danger {{
  background: #fef2f2;
  border-inline-start: 1.8pt solid #b42318;
  padding-inline-start: 1.4mm;
}}
.top {{
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: 1.4mm;
  direction: ltr;
  unicode-bidi: isolate;
}}
code.cmd {{
  font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace;
  font-size: 6.1pt;
  font-weight: 600;
  color: #0f172a;
  direction: ltr;
  unicode-bidi: isolate;
  text-align: left;
  word-break: break-word;
  overflow-wrap: anywhere;
}}
.tags {{
  display: inline-flex;
  align-items: center;
  gap: .9mm;
  flex-shrink: 0;
  white-space: nowrap;
}}
.bdg {{
  display: inline-block;
  font-size: 5.3pt;
  font-weight: 700;
  padding: .15mm 1mm;
  border-radius: .7mm;
  color: #fff;
  line-height: 1.25;
}}
.bdg-danger {{
  background: #b42318;
  font-family: {font_sans};
}}
.s-squid {{ background: #1d5fa8; font-family: "JetBrains Mono", monospace; }}
.s-tentacle {{ background: #7a3fa0; font-family: "JetBrains Mono", monospace; }}
.s-umbrella {{ background: #a6531b; font-family: "JetBrains Mono", monospace; }}
.s-main {{ background: #b42318; font-family: "JetBrains Mono", monospace; }}
.s-quincy {{ background: #5b6472; font-family: "JetBrains Mono", monospace; }}
.ref {{
  font-size: 5.6pt;
  color: #64748b;
  font-weight: 600;
}}
.desc {{
  margin-top: .25mm;
  font-size: 6.4pt;
  color: #334155;
  line-height: 1.3;
}}
"""
    _ = page_tpl
    return (
        f'<!DOCTYPE html><html lang="{lang}" dir="{dir_attr}"><head><meta charset="utf-8">'
        f'<title>{esc(title)}</title><style>{css}</style></head><body>'
        f'<header class="hdr"><div><h1>{esc(title)}</h1><div class="sub">{esc(subtitle)}</div></div>'
        f'<div class="cnt">{esc(count_txt)}</div></header>'
        f'<div class="legend">{esc(legend)}</div>'
        f'<main class="cols">{"".join(sections)}</main>'
        f'</body></html>'
    )


def render(lang: str, out: str, max_pages: int = 4) -> int:
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    html_src = build_html(lang)
    doc = weasyprint.HTML(string=html_src, base_url=ROOT).render()
    pages = len(doc.pages)
    doc.write_pdf(out)
    print(f'render-cheatsheet ({lang}): {pages} page(s) -> {os.path.relpath(out, ROOT)}')
    if pages < 1 or pages > max_pages:
        print(f'ERROR: expected 1..{max_pages} pages, got {pages}', file=sys.stderr)
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--lang', default='fa', choices=['fa', 'en'])
    ap.add_argument('--out')
    ap.add_argument('--max-pages', type=int, default=4)
    a = ap.parse_args()
    out = a.out or os.path.join(ROOT, 'build', a.lang, f'ceph-cheatsheet-{a.lang}.pdf')
    return render(a.lang, out, a.max_pages)


if __name__ == '__main__':
    sys.exit(main())
