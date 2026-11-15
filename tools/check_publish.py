#!/usr/bin/env python3
"""Check the publishing metadata: .zenodo.json, CITATION.cff and the release workflow inputs.

* .zenodo.json: a book (upload_type publication, publication_type book), license
  cc-by-nc-sa-4.0, the author's ORCID, keywords, and no affiliation;
* CITATION.cff: CFF 1.2.0 with title, author ORCID, license, version and date-released;
  its version equals the book version in content/{fa,en}/metadata.yaml;
* CHANGELOG.md has a "## [version] - date" section for that version;
* with --tag vX.Y (the release workflow): the tag names that same version.

Usage: tools/check_publish.py [--tag v1.7]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

import yaml

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(ROOT, 'tools'))
from booklib.siteconf import changelog_releases  # noqa: E402

ORCID = '0009-0000-7622-8130'
ap = argparse.ArgumentParser()
ap.add_argument('--tag')
a = ap.parse_args()
errors: list[str] = []

z = json.load(open(os.path.join(ROOT, '.zenodo.json'), encoding='utf-8'))
for k, v in (('upload_type', 'publication'), ('publication_type', 'book'), ('license', 'cc-by-nc-sa-4.0'), ('access_right', 'open')):
    if z.get(k) != v:
        errors.append(f'.zenodo.json: {k} is {z.get(k)!r}, expected {v!r}')
for k in ('title', 'description'):
    if not z.get(k):
        errors.append(f'.zenodo.json: no {k}')
if len(z.get('keywords') or []) < 5:
    errors.append('.zenodo.json: fewer than 5 keywords')
cr = z.get('creators') or []
if not cr or cr[0].get('orcid') != ORCID:
    errors.append(f'.zenodo.json: the first creator must carry ORCID {ORCID}')
if any('affiliation' in c for c in cr) or 'affiliation' in json.dumps(z).lower():
    errors.append('.zenodo.json: creators must not have an affiliation')

c = yaml.safe_load(open(os.path.join(ROOT, 'CITATION.cff'), encoding='utf-8'))
if c.get('cff-version') != '1.2.0':
    errors.append('CITATION.cff: cff-version must be 1.2.0')
for k in ('title', 'message', 'authors', 'version', 'date-released', 'license'):
    if not c.get(k):
        errors.append(f'CITATION.cff: no {k}')
if c.get('license') != 'CC-BY-NC-SA-4.0':
    errors.append('CITATION.cff: license must be CC-BY-NC-SA-4.0')
if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', str(c.get('date-released', ''))):
    errors.append('CITATION.cff: date-released must be YYYY-MM-DD')
for au in (c.get('authors') or []) + ((c.get('preferred-citation') or {}).get('authors') or []):
    if au.get('orcid') != f'https://orcid.org/{ORCID}':
        errors.append(f'CITATION.cff: author ORCID must be https://orcid.org/{ORCID}')
    if 'affiliation' in au:
        errors.append('CITATION.cff: authors must not have an affiliation')
pc = c.get('preferred-citation') or {}
if pc.get('type') != 'book':
    errors.append('CITATION.cff: preferred-citation.type must be book')

vers = {lang: str(yaml.safe_load(open(os.path.join(ROOT, 'content', lang, 'metadata.yaml'), encoding='utf-8'))['version'])
        for lang in ('fa', 'en')}
if len(set(vers.values())) != 1:
    errors.append(f'metadata.yaml: fa and en versions differ: {vers}')
ver = vers['en']
for where, v in (('CITATION.cff version', str(c.get('version'))), ('CITATION.cff preferred-citation.edition', str(pc.get('edition', ver)))):
    if v != ver:
        errors.append(f'{where} is {v}, the book is {ver}')
rel = {v for v, _, _ in changelog_releases(os.path.join(ROOT, 'CHANGELOG.md'))}
if ver not in rel:
    errors.append(f'CHANGELOG.md has no "## [{ver}] - date" section')
if a.tag and a.tag != f'v{ver}':
    errors.append(f'tag {a.tag} does not match the book version {ver} (expected v{ver})')

for e in errors:
    print('publish:', e)
print(f'publish: version {ver}, .zenodo.json and CITATION.cff checked{", tag " + a.tag if a.tag else ""}; {len(errors)} problems')
sys.exit(1 if errors else 0)
