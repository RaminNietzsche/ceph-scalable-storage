#!/usr/bin/env python3
"""Split the built web book into retrieval chunks for the book-ask Worker.

Reads build/site/{en,fa}/*.html (run `make site` first) and writes JSON Lines,
one passage per line: id, lang, slug, title, section, anchor, url, text.
Chunks follow the h2/h3 sections of each page; long sections are split on
paragraph boundaries. Interactive and navigation pages are skipped.

    python3 infra/book-ask/build_chunks.py > build/ask-chunks.jsonl
"""
import json
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

SITE = Path(sys.argv[1] if len(sys.argv) > 1 else "build/site")
BASE = "https://book.ceph-s3.ir"
SKIP = re.compile(r"^(index|contents|book-index|figures|progress|review|certificate|bibliography|changes|lab.*|404)$")
DROP = ["script", "style", "svg", "button", "nav", "form", "noscript",
        "span.ixa", "a.hanchor", "div.fb", "aside", "div.sim-slot", "ul.refs",
        "ol.qs", "p.ansref", "img", "div.code-head", "div.call-head"]
MAX, MIN = 1600, 200


def clean(text):
    text = text.replace("\xa0", " ")
    text = re.sub(r"[\u200e\u200f\u202a-\u202e]", "", text)  # bidi marks around Latin terms
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def block_text(el):
    if el.name in ("pre",) or "code" in (el.get("class") or []):
        return el.get_text("", strip=False).strip()
    if el.name in ("ul", "ol"):
        return "\n".join("- " + li.get_text(" ", strip=True) for li in el.find_all("li", recursive=False))
    if "table-wrap" in (el.get("class") or []) or el.name == "table":
        rows = []
        for tr in el.find_all("tr"):
            rows.append(" | ".join(c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])))
        return "\n".join(rows)
    return el.get_text(" ", strip=True)


def split(text):
    if len(text) <= MAX:
        return [text]
    out, cur = [], ""
    for para in text.split("\n\n"):
        while len(para) > MAX:  # very long paragraph or code block
            cut = para.rfind(" ", 0, MAX)
            cut = cut if cut > MAX // 2 else MAX
            if cur:
                out.append(cur)
                cur = ""
            out.append(para[:cut])
            para = para[cut:].lstrip()
        if cur and len(cur) + len(para) + 2 > MAX:
            out.append(cur)
            cur = para
        else:
            cur = f"{cur}\n\n{para}" if cur else para
    if cur:
        if out and len(cur) < MIN:
            out[-1] += "\n\n" + cur
        else:
            out.append(cur)
    return out


def page_chunks(lang, path):
    slug = path.stem
    soup = BeautifulSoup(path.read_text(encoding="utf-8"), "lxml")
    art = soup.select_one("article.content") or soup.find("main")
    if art is None:
        return
    h1 = art.find("h1")
    title = clean(h1.get_text(" ", strip=True)) if h1 else slug
    for sel in DROP:
        for el in art.select(sel):
            el.decompose()
    url = f"{BASE}/{lang}/{slug}.html"
    sections = [{"section": "", "anchor": "", "parts": []}]
    for el in art.find_all(recursive=False):
        if el.name == "header":
            continue
        if el.name in ("h2", "h3") and el.get("id"):
            sections.append({"section": clean(el.get_text(" ", strip=True)), "anchor": el["id"], "parts": []})
            continue
        if el.name == "details" and "tldr" in (el.get("class") or []):
            el.find("summary") and el.find("summary").decompose()
        t = clean(block_text(el))
        if t:
            sections[-1]["parts"].append(t)
    n = 0
    for sec in sections:
        body = "\n\n".join(sec["parts"])
        if len(body) < 40:
            continue
        for piece in split(body):
            n += 1
            yield {
                "id": f"{lang}/{slug}/{n}",
                "lang": lang,
                "slug": slug,
                "title": title,
                "section": sec["section"],
                "anchor": sec["anchor"],
                "url": url + (f"#{sec['anchor']}" if sec["anchor"] else ""),
                "text": piece,
            }


def main():
    total = 0
    for lang in ("en", "fa"):
        for path in sorted((SITE / lang).glob("*.html")):
            if SKIP.match(path.stem):
                continue
            for c in page_chunks(lang, path):
                sys.stdout.write(json.dumps(c, ensure_ascii=False) + "\n")
                total += 1
    print(f"{total} chunks", file=sys.stderr)


if __name__ == "__main__":
    main()
