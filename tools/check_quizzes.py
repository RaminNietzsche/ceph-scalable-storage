#!/usr/bin/env python3
"""Validate the end-of-chapter quizzes in references/quizzes/chNN.yaml (web edition).

One bilingual file per chapter is the single source for the fa and en quizzes. Checks:
  * one file per chapter of the book (chNN.yaml with chapter: NN), nothing else in the folder
  * 4-6 questions per chapter, ids unique (lowercase, [a-z0-9-]) within the book
  * every question, option and explanation has both fa and en text (parity)
  * 3-5 options, no two options with the same text; exactly one correct option unless the
    question declares multi: true (then at least two correct and at least one wrong)
  * ref is a section anchor ({#sec-NN-...}) of that same chapter, present in fa and en
  * the correct answer is not always in the same position within a chapter
  * no question repeats one of the chapter's open review questions word for word
  * the prose rules of tools/lint_prose.py (Persian orthography, spacing); no math ($) and no
    raw HTML, only `code` and **bold** inline markup
"""
from __future__ import annotations

import glob
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
QDIR = os.path.join(ROOT, 'references', 'quizzes')
LANGS = ('fa', 'en')
MIN_Q, MAX_Q, MIN_O, MAX_O = 4, 6, 3, 5
ID_RX = re.compile(r'^[a-z0-9][a-z0-9-]{1,40}$')
ANCHOR_RX = re.compile(r'\{#(sec-\d\d[\w-]*)\}')
RULES_FA = [
    (re.compile('[\u064A\u0643]'), 'Arabic ي/ك instead of Persian ی/ک'),
    (re.compile(r'(?<![\w\u200c])(ن?می) (?=[\u0600-\u06FF]{2,})'), '"می"/"نمی" prefix should use ZWNJ'),
    (re.compile(r' [،؛؟:]'), 'space before punctuation'),
    (re.compile(r'(?<![\d۰-۹])\?'), 'Latin ? in Persian text (use ؟)'),
]
RULES_EN = [
    (re.compile('[\u0600-\u06FF]'), 'Persian letters in the English text'),
]
RULES_ALL = [
    (re.compile(r'\S  +\S'), 'double space'),
    (re.compile(r'^\s|\s$'), 'leading or trailing whitespace'),
    (re.compile(r'\$'), 'math ($) is not supported in quizzes'),
    (re.compile(r'<[a-zA-Z/]'), 'raw HTML is not allowed'),
    (re.compile(r'\w\)?\^[\w({-]'), 'bare ^ exponent'),
]


def chapters(lang: str) -> dict[int, str]:
    out = {}
    for p in glob.glob(os.path.join(ROOT, 'content', lang, 'chapters', '[0-9][0-9]-*.md')):
        out[int(os.path.basename(p)[:2])] = open(p, encoding='utf-8').read()
    return out


def review_questions(text: str) -> list[str]:
    """The numbered items of the chapter's review-questions section (first heading level 2 that holds an <ol>)."""
    m = re.search(r'^## (?:Review questions|پرسش‌های مرور)\b.*$', text, re.M)
    if not m:
        return []
    rest = text[m.end():]
    nxt = re.search(r'^#{1,2} ', rest, re.M)
    block = rest[:nxt.start()] if nxt else rest
    return [re.sub(r'\s+', ' ', x).strip() for x in re.findall(r'^\d+\.\s+(.*)$', block, re.M)]


def norm(s: str) -> str:
    return re.sub(r'[\W_]+', ' ', s.replace('\u200c', '')).strip().lower()


def lint(text, lang: str, where: str, errs: list[str]) -> None:
    if not isinstance(text, str) or not text.strip():
        errs.append(f'{where}: missing {lang} text')
        return
    prose = re.sub(r'`[^`]*`', 'CODE', text)   # code spans are shown verbatim
    for rx, msg in RULES_ALL + (RULES_FA if lang == 'fa' else RULES_EN):
        if rx.search(prose):
            errs.append(f'{where} ({lang}): {msg}: {text!r}')
    if text.count('`') % 2:
        errs.append(f'{where} ({lang}): unbalanced backtick')
    if text.count('**') % 2:
        errs.append(f'{where} ({lang}): unbalanced **')


def bi(node, where: str, errs: list[str]) -> None:
    if not isinstance(node, dict):
        errs.append(f'{where}: must be a mapping with fa and en')
        return
    extra = set(node) - set(LANGS) - {'correct'}
    if extra:
        errs.append(f'{where}: unknown keys {sorted(extra)}')
    for lang in LANGS:
        lint(node.get(lang), lang, where, errs)


def load_all() -> dict[int, dict]:
    out = {}
    for p in sorted(glob.glob(os.path.join(QDIR, '*'))):
        m = re.match(r'^ch(\d\d)\.yaml$', os.path.basename(p))
        out[int(m.group(1)) if m else -1] = (p, yaml.safe_load(open(p, encoding='utf-8')) if m else None)
    return out


def main() -> int:
    errs: list[str] = []
    chs = {lang: chapters(lang) for lang in LANGS}
    anchors = {lang: {n: set(ANCHOR_RX.findall(t)) for n, t in chs[lang].items()} for lang in LANGS}
    files = load_all()
    if -1 in files:
        errs.append(f'{os.path.relpath(files.pop(-1)[0], ROOT)}: unexpected file (expected chNN.yaml)')
    for n in sorted(set(chs['fa']) | set(chs['en'])):
        if n not in files:
            errs.append(f'chapter {n}: no references/quizzes/ch{n:02d}.yaml')
    seen_ids: dict[str, str] = {}
    nq = nmulti = 0
    for n, (path, data) in sorted(files.items()):
        rel = os.path.relpath(path, ROOT)
        if n not in chs['fa']:
            errs.append(f'{rel}: chapter {n} does not exist')
            continue
        if not isinstance(data, dict) or data.get('chapter') != n:
            errs.append(f'{rel}: needs "chapter: {n}"')
            continue
        qs = data.get('questions')
        if not isinstance(qs, list) or not MIN_Q <= len(qs) <= MAX_Q:
            errs.append(f'{rel}: needs {MIN_Q}-{MAX_Q} questions, has {len(qs) if isinstance(qs, list) else 0}')
            continue
        rq = {lang: {norm(x) for x in review_questions(chs[lang].get(n, ''))} for lang in LANGS}
        positions = []
        for i, q in enumerate(qs, 1):
            where = f'{rel} #{i}'
            if not isinstance(q, dict):
                errs.append(f'{where}: must be a mapping')
                continue
            extra = set(q) - {'id', 'ref', 'multi', 'q', 'options', 'why'}
            if extra:
                errs.append(f'{where}: unknown keys {sorted(extra)}')
            qid = q.get('id')
            if not isinstance(qid, str) or not ID_RX.match(qid):
                errs.append(f'{where}: id must match {ID_RX.pattern}')
            else:
                where = f'{rel} {qid}'
                if qid in seen_ids:
                    errs.append(f'{where}: duplicate id (also in {seen_ids[qid]})')
                seen_ids[qid] = rel
            ref = q.get('ref')
            if not isinstance(ref, str) or not ref.startswith(f'sec-{n:02d}'):
                errs.append(f'{where}: ref must be a section anchor of chapter {n} (sec-{n:02d}-...), got {ref!r}')
            else:
                for lang in LANGS:
                    if ref not in anchors[lang].get(n, set()):
                        errs.append(f'{where}: ref {ref} not found in the {lang} chapter')
            multi = q.get('multi', False)
            if multi not in (True, False):
                errs.append(f'{where}: multi must be true or false')
            bi(q.get('q'), f'{where} q', errs)
            bi(q.get('why'), f'{where} why', errs)
            for lang in LANGS:
                t = (q.get('q') or {}).get(lang) if isinstance(q.get('q'), dict) else None
                if isinstance(t, str) and norm(t) in rq[lang]:
                    errs.append(f'{where} ({lang}): repeats a review question of chapter {n}')
            opts = q.get('options')
            if not isinstance(opts, list) or not MIN_O <= len(opts) <= MAX_O:
                errs.append(f'{where}: needs {MIN_O}-{MAX_O} options')
                continue
            for k, o in enumerate(opts, 1):
                bi(o, f'{where} option {k}', errs)
                if isinstance(o, dict) and o.get('correct', False) not in (True, False):
                    errs.append(f'{where} option {k}: correct must be true or false')
            ok = [k for k, o in enumerate(opts) if isinstance(o, dict) and o.get('correct') is True]
            if multi:
                nmulti += 1
                if len(ok) < 2 or len(ok) == len(opts):
                    errs.append(f'{where}: a multi-select question needs at least two correct and one wrong option')
            elif len(ok) != 1:
                errs.append(f'{where}: exactly one option must be correct (has {len(ok)}); set multi: true for multi-select')
            if len(ok) == 1:
                positions.append(ok[0])
            for lang in LANGS:
                texts = [norm(o.get(lang, '')) for o in opts if isinstance(o, dict) and isinstance(o.get(lang), str)]
                if len(set(texts)) != len(texts):
                    errs.append(f'{where} ({lang}): two options have the same text')
            nq += 1
        if len(positions) >= 3 and len(set(positions)) == 1:
            errs.append(f'{rel}: the correct option is always number {positions[0] + 1}; vary its position')
    print(f'check-quizzes: {len(files)} chapters, {nq} questions ({nmulti} multi-select), {len(errs)} error(s)')
    for e in errs[:80]:
        print('  ', e)
    if len(errs) > 80:
        print(f'   ... and {len(errs) - 80} more')
    return 1 if errs else 0


if __name__ == '__main__':
    sys.exit(main())
