# Command-line reference

Appendix L of the web edition (`cli-reference.html`) lists every command and option of `ceph`, `rados`, `radosgw-admin`, `rbd`, `ceph-volume` and `cephfs-journal-tool` for one Ceph release, with a tag that says whether the code and the documentation agree. The print and Pandoc editions carry only a short pointer (`content/<lang>/appendices/cli-reference.md`), because the full list is long and is meant to be searched.

## Data

`references/cli-reference.yaml` is generated; do not edit it by hand.

```yaml
meta:
  ceph_tag: v20.2.5                  # the release tag the data was built from
  ceph_commit: ed27c686...           # full SHA of that tag
  ceph_commit_date: '2026-10-27'
  generator: tools/gen_cli_reference.py
  tags: [both, code-only, docs-only, usage-only, no-usage]
  summary: {<tool>: {commands, options, command_tags, option_tags}}
tools:
  - id: radosgw-admin
    sources: {code: [...], docs: [...], usage: ...}   # files the entries were read from
    commands:
      - name: zone list
        alias: zones list            # other names in the command table for the same command
        doc: doc/man/8/radosgw-admin.rst:303   # first place in doc/ that mentions it
        help: list all zones set on this cluster   # the tool's own one-line help string
        in: {code: true, docs: true, usage: true}
        tags: [both]
  - id: ceph
    commands:
      - name: osd pool create
        src: src/mon/MonCommands.h:1024        # where the code defines it, when there is one line
        daemon: mon                  # ceph only: mon, mgr, or the module (module: ...)
        perm: rw
        options:                     # per-command options and arguments (ceph, rbd, ceph-volume)
          - {name: pg_num, type: CephInt, optional: true, in: {...}, tags: [...]}
    options: [...]                   # tool-wide options (same fields)
```

`in` records where the entry was found; `tags` is derived from it (the rule is in `tools/booklib/clirefs.py`):

| Tag | Rule |
|---|---|
| both | code and docs |
| code-only | code, not docs (undocumented) |
| docs-only | docs, not code (stale or removed) |
| usage-only | in the tool's usage()/help text but not parsed |
| no-usage | parsed but not in the usage()/help text |

`usage` is present only for tools with a hand-written usage text (`radosgw-admin`, `rados`, `cephfs-journal-tool`) and for the per-command help of `rbd`.

## Where the data comes from

| Tool | Code | Documentation |
|---|---|---|
| ceph | `src/mon/MonCommands.h`, `src/mgr/MgrCommands.h`, the mgr modules (`COMMANDS` tables, `CLI*Command` decorators, dashboard settings commands), argparse options of `src/ceph.in` | `doc/man/8/ceph.rst` Usage blocks, `ceph ...` lines in literal blocks and inline literals under `doc/` |
| rados | `strcmp(nargs[0], ...)` dispatch, `ceph_argparse_*` loop, `usage()` in `src/tools/rados/rados.cc` | `doc/man/8/rados.rst`, `rados ...` lines in the guides |
| radosgw-admin | the `all_cmds` table and aliases, `ceph_argparse_*` loop and `usage()` in `src/rgw/radosgw-admin/radosgw-admin.cc` | `doc/man/8/radosgw-admin.rst`, `radosgw-admin ...` lines in `doc/radosgw/` and other guides |
| rbd | `Shell::Action` registrations in `src/tools/rbd/action/*.cc`; per-command option sets from `src/test/cli/rbd/help.t`, the cram test that pins `rbd help <command>` to the code | `doc/man/8/rbd.rst` (command synopses and options), `rbd ...` lines in `doc/rbd/` |
| ceph-volume | argparse `mapper` tables, `add_argument` calls and the common argument tables in `src/ceph-volume/ceph_volume/` | `doc/man/8/ceph-volume.rst`, `doc/ceph-volume/` |
| cephfs-journal-tool | `JournalTool.cc` dispatch and `usage()`, `JournalFilter.cc` | `doc/cephfs/cephfs-journal-tool.rst` |

Options parsed for every C++ tool by `ceph_argparse_early_args()` and `md_config_t::parse_argv()` are marked `kind: global`; `--<config-option>` arguments that the tools accept through the configuration system are marked `kind: config`. `ceph_argparse` treats `-` and `_` alike, so option names are normalised to dashes.

Docs matching is textual, so a tag is a pointer to check, not a verdict: each entry carries the `src` and `doc` locations to look at.

Only names and the tools' own short help strings are stored. Documentation prose is never copied (Ceph's documentation is CC BY-SA); the book's notes on the page come from `references/cheatsheet.yaml`.

## Regenerating

```bash
make cli-reference                         # shallow clone of meta.ceph_tag into build/
make cli-reference CEPH_TAG=v20.2.6        # another point release
make cli-reference CEPH_SRC=~/src/ceph     # an existing checkout at a release tag
```

The target runs the generator and then the validator. After a regeneration, update the counts in the two pointer files (the validator says which numbers it expects) and the findings list if it changed.

## Checks

`make check-cli-reference` (part of `make check`, so it runs in CI) validates the file without the Ceph tree: a Tentacle release tag and a full SHA, the six tools in order, unique sorted names, `in` records of booleans with matching `tags`, one-line help strings, `doc/`/`src/` locations, a summary equal to the entries, at least 150 cheat-sheet commands resolving to entries, and the release and counts in the pointer files. A full regeneration needs the network and a Ceph checkout, so CI does not run it.

## Web page

`tools/build_site.py` writes `cli-ref-data.js` for each edition and adds the search bar, the tool selector, the tag chips and the legend to `cli-reference.html`; `templates/site/cliref.js` renders the list 120 entries at a time and keeps the filter in the URL hash (`#tool=rbd&tag=code-only&q=snap`). Commands that are also in the cheat sheet show the book's note, the cheat-sheet line as an example and a link to the section that explains them.
