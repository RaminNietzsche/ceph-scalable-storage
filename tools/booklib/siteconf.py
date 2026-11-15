"""Deployment options of the web edition, read from the environment at build time.

Nothing here is stored in the repository: CI passes the values (for example the
Cloudflare Web Analytics token from the GitHub Actions variable CF_BEACON_TOKEN),
and a local `make site` builds a site with no analytics, no newsletter form and
no feedback endpoint.

    REPO_URL           public repository, for "Edit this page" and feedback issues
                       (default https://github.com/RaminNietzsche/ceph-scalable-storage)
    REPO_BRANCH        branch the edit links open (default main)
    FEEDBACK_ENDPOINT  optional https URL; "Was this section helpful?" votes are POSTed
                       to it with navigator.sendBeacon as a small JSON text body
    FEEDBACK_ISSUES    1 (default) offers a prefilled GitHub issue after a "No" vote; 0 turns it off
    NEWSLETTER_ACTION  optional https URL of a newsletter signup form (POST, field "email");
                       without it the site offers "Watch releases on GitHub" and releases.xml
    ANALYTICS          cloudflare | plausible | none (default: cloudflare when CF_BEACON_TOKEN is set)
    CF_BEACON_TOKEN    Cloudflare Web Analytics site token (cookie-less beacon)
    PLAUSIBLE_DOMAIN   site domain for ANALYTICS=plausible
    CNAME              custom domain written to build/site/CNAME; by default the host of
                       SITE_URL when SITE_URL has no path and is not *.github.io (CNAME=none writes none)
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import urlsplit

DEFAULT_REPO = 'https://github.com/RaminNietzsche/ceph-scalable-storage'
ANALYTICS_HOSTS = {'cloudflare': 'static.cloudflareinsights.com', 'plausible': 'plausible.io'}


def _https(name, val):
    if val and not re.fullmatch(r'https://[^\s"\'<>]+', val):
        sys.exit(f'build_site: {name} must be an https:// URL, got {val!r}')
    return val


def load(site_url: str, env=os.environ) -> dict:
    repo = _https('REPO_URL', (env.get('REPO_URL') or DEFAULT_REPO).rstrip('/'))
    branch = env.get('REPO_BRANCH') or 'main'
    if not re.fullmatch(r'[\w./-]+', branch):
        sys.exit(f'build_site: REPO_BRANCH {branch!r} is not a branch name')
    token = (env.get('CF_BEACON_TOKEN') or '').strip()
    kind = (env.get('ANALYTICS') or '').strip().lower()
    if kind in ('', 'cloudflare') and token:
        kind = 'cloudflare'
    elif kind in ('', 'none', 'off', '0'):
        kind = ''
    if kind == 'cloudflare':
        if not re.fullmatch(r'[0-9a-f]{32}', token):
            sys.exit('build_site: ANALYTICS=cloudflare needs CF_BEACON_TOKEN (32 hex characters)')
    elif kind == 'plausible':
        if not re.fullmatch(r'[a-z0-9.-]+', env.get('PLAUSIBLE_DOMAIN') or ''):
            sys.exit('build_site: ANALYTICS=plausible needs PLAUSIBLE_DOMAIN')
    elif kind:
        sys.exit(f'build_site: unknown ANALYTICS={kind!r} (cloudflare, plausible or none)')
    cname = (env.get('CNAME') or '').strip().lower()
    if cname in ('none', 'off', '-'):
        cname = ''
    elif not cname:
        u = urlsplit(site_url or '')
        cname = u.hostname if u.hostname and u.path in ('', '/') and not u.hostname.endswith('github.io') else ''
    if cname and not re.fullmatch(r'[a-z0-9.-]+\.[a-z]{2,}', cname):
        sys.exit(f'build_site: CNAME {cname!r} is not a host name')
    return {
        'repo': repo, 'branch': branch,
        'feedback': _https('FEEDBACK_ENDPOINT', env.get('FEEDBACK_ENDPOINT') or ''),
        'feedback_issues': (env.get('FEEDBACK_ISSUES') or '1') not in ('0', 'no', 'false', 'off'),
        'newsletter': _https('NEWSLETTER_ACTION', env.get('NEWSLETTER_ACTION') or ''),
        'analytics': kind, 'cf_token': token if kind == 'cloudflare' else '',
        'plausible_domain': env.get('PLAUSIBLE_DOMAIN', '') if kind == 'plausible' else '',
        'cname': cname,
    }


def analytics_tag(cfg: dict) -> str:
    """The analytics <script>, or '' when none is configured."""
    if cfg['analytics'] == 'cloudflare':
        return ('<script defer src="https://static.cloudflareinsights.com/beacon.min.js" '
                f'data-cf-beacon=\'{{"token": "{cfg["cf_token"]}"}}\'></script>')
    if cfg['analytics'] == 'plausible':
        return f'<script defer data-domain="{cfg["plausible_domain"]}" src="https://plausible.io/js/script.js"></script>'
    return ''


def analytics_name(cfg: dict) -> str:
    return {'cloudflare': 'Cloudflare Web Analytics', 'plausible': 'Plausible Analytics'}.get(cfg['analytics'], '')


# ---------------------------------------------------------------- releases.xml
def changelog_releases(path):
    """[(version, date 'YYYY-MM[-DD]', markdown body)] for released versions, newest first."""
    text = open(path, encoding='utf-8').read()
    out = []
    parts = re.split(r'^## ', text, flags=re.M)[1:]
    for p in parts:
        head, _, body = p.partition('\n')
        m = re.match(r'\[(\d+(?:\.\d+)*)\]\s*[-—–]\s*(\d{4}-\d{2}(?:-\d{2})?)', head)
        if m:
            out.append((m.group(1), m.group(2), body.strip()))
    return out


def _md_html(md):
    import html
    esc = lambda s: html.escape(s, quote=False)  # noqa: E731
    inline = lambda s: re.sub(r'`([^`]+)`', r'<code>\1</code>', esc(s))  # noqa: E731
    out, items = [], []
    lines = []
    for ln in md.split('\n'):          # join wrapped list items
        if ln.startswith('  ') and lines and lines[-1].startswith('- '):
            lines[-1] += ' ' + ln.strip()
        else:
            lines.append(ln)

    def flush():
        if items:
            out.append('<ul>' + ''.join(f'<li>{inline(i)}</li>' for i in items) + '</ul>')
            items.clear()
    for ln in lines:
        if ln.startswith('### '):
            flush()
            out.append(f'<h3>{inline(ln[4:])}</h3>')
        elif ln.startswith('- '):
            items.append(ln[2:])
        elif ln.strip():
            flush()
            out.append(f'<p>{inline(ln)}</p>')
    flush()
    return ''.join(out)


def atom_feed(changelog, cfg, site_url, title, author):
    import html
    rel = changelog_releases(changelog)
    base = (site_url or '').rstrip('/')
    self_url = f'{base}/releases.xml' if base else f'{cfg["repo"]}/releases'
    home = f'{base}/' if base else cfg['repo']

    def stamp(d):
        return (d if len(d) == 10 else d + '-01') + 'T00:00:00Z'
    entries = []
    for ver, date, body in rel:
        link = f'{cfg["repo"]}/releases/tag/v{ver}'
        entries.append(f'<entry><title>{html.escape(title)} {ver}</title><id>{html.escape(link)}</id>'
                       f'<link rel="alternate" href="{html.escape(link)}"/><updated>{stamp(date)}</updated>'
                       f'<content type="html">{html.escape(_md_html(body))}</content></entry>')
    updated = max(stamp(d) for _, d, _ in rel) if rel else '1970-01-01T00:00:00Z'
    return ('<?xml version="1.0" encoding="utf-8"?>\n<feed xmlns="http://www.w3.org/2005/Atom">'
            f'<title>{html.escape(title)} — releases</title><id>{html.escape(self_url)}</id>'
            f'<link rel="self" href="{html.escape(self_url)}"/><link rel="alternate" href="{html.escape(home)}"/>'
            f'<updated>{updated}</updated><author><name>{html.escape(author)}</name></author>'
            + ''.join(entries) + '</feed>\n')
