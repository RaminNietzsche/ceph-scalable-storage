"""Ceph release labels for command blocks ("Reef+", "Squid+", ...).

Source annotation, on the opening fence of a code block (Pandoc attribute syntax):

    ```bash {since=squid}

Every code block that runs a Ceph command-line tool (ceph, rados, rbd,
radosgw-admin, cephadm, ceph-volume, ...) gets a badge. Unannotated blocks get
the book's baseline, BASELINE (Reef 18.2): the command works unchanged on Reef
and every later release. ``since=`` names a newer release when the command or
an option in it first appeared later; ``since=main`` marks commands that exist
only on the development branch, and ``since=none`` suppresses the badge (for
example a block that only quotes a tool's output or a deliberately obsolete
command). The same mechanism is used by the print, web and Pandoc editions,
and tools/check_versions.py keeps fa and en in step.
"""
from __future__ import annotations

import re

# (key, major number, display name, first stable point release)
RELEASES = [
    ('quincy', 17, 'Quincy', '17.2'),
    ('reef', 18, 'Reef', '18.2'),
    ('squid', 19, 'Squid', '19.2'),
    ('tentacle', 20, 'Tentacle', '20.2'),
    ('umbrella', 21, 'Umbrella', '21.2'),
]
REL = {k: (n, name, ver) for k, n, name, ver in RELEASES}
BASELINE = 'reef'
SPECIAL = ('main', 'none')
VALID = tuple(REL) + SPECIAL

TOOLS = ('ceph-objectstore-tool', 'ceph-bluestore-tool', 'ceph-kvstore-tool', 'ceph-monstore-tool', 'ceph-dencoder',
         'ceph-volume', 'ceph-fuse', 'ceph-authtool', 'ceph-conf', 'ceph-post-file', 'ceph-crash',
         'cephfs-journal-tool', 'cephfs-data-scan', 'cephfs-table-tool', 'cephfs-top', 'cephfs-shell', 'cephfs-mirror',
         'radosgw-admin', 'rbd-nbd', 'rbd-mirror', 'rbd', 'rados', 'osdmaptool', 'crushtool', 'monmaptool',
         'cephadm', 'ceph')
# a command line: optional prompt / sudo / env, then a Ceph tool and an argument
_PROMPT = r'(?:(?:\[[^\]]*\]\s*)?[$#]\s+)?(?:sudo\s+(?:-\S+\s+)*)?'
CMD = re.compile(r'^\s*' + _PROMPT + r'(?:\./)?(' + '|'.join(re.escape(t) for t in TOOLS) + r')\s+[-\w"\'./@:=<{]')
PROMPTED = re.compile(r'^\s*(?:\[[^\]]*\]\s*)?[$#]\s+')
SHELL_LANGS = ('', 'bash', 'sh', 'shell', 'console', 'zsh')
_FENCE = re.compile(r'^```+\s*([\w+-]*)\s*(?:\{([^}]*)\})?\s*$')
_KV = re.compile(r'([\w-]+)=("[^"]*"|\S+)')


def parse_fence(line):
    """'```bash {since=squid}' -> ('bash', {'since': 'squid'}); None if the line is not an opening fence."""
    m = _FENCE.match(line.strip())
    if not m:
        return None
    attrs = {k: v.strip('"') for k, v in _KV.findall(m.group(2) or '')}
    return m.group(1), attrs


def is_ceph_command(lang, lines):
    """True when a code block runs a Ceph CLI tool.

    Shell blocks (bash, sh, console or no language) count any command line; ``text``
    blocks count only prompted lines ("$ ceph ...", "# rbd ..."), because they usually
    quote output such as "ceph version 18.2.7 ...".
    """
    if lang in SHELL_LANGS:
        return any(CMD.match(x) for x in lines)
    if lang == 'text':
        return any(PROMPTED.match(x) and CMD.match(x) for x in lines)
    return False


def since_of(lang, attrs, lines):
    """The release key a block is labelled with, or None for no badge."""
    s = (attrs or {}).get('since')
    if s == 'none':
        return None
    if s:
        return s
    return BASELINE if is_ceph_command(lang, lines) else None


def label(key, lang='en'):
    if key == 'main':
        return 'main' if lang == 'en' else 'فقط main'
    return REL[key][1] + '+'


def title(key, lang='en'):
    if key == 'main':
        return ('Only on the development branch (main); not yet in a stable release' if lang == 'en'
                else 'فقط در شاخه‌ی توسعه (main)؛ هنوز در هیچ نسخه‌ی پایداری نیست')
    n, name, ver = REL[key]
    if lang == 'en':
        return f'Works on Ceph {name} ({ver}) and later'
    return f'از Ceph {name} ({ver}) به بعد درست است'


def blocks(lines):
    """Yield (start_line_index, lang, attrs, body_lines) for every fenced code block."""
    i, n = 0, len(lines)
    while i < n:
        if lines[i].startswith('```'):
            f = parse_fence(lines[i]) or ('', {})
            j = i + 1
            while j < n and not lines[j].startswith('```'):
                j += 1
            yield i, f[0], f[1], lines[i + 1:j]
            i = j + 1
            continue
        i += 1
