---
id: cli-reference
lang: en
---

This appendix describes the command-line reference that comes with the web edition of the book. The reference lists every command and option of `ceph`, `rados`, `radosgw-admin`, `rbd`, `ceph-volume` and `cephfs-journal-tool` in Ceph 20.2.5 (Tentacle): 1438 commands and 2952 options. That is too long for print and it is meant to be searched rather than read, so only this summary is printed. The full reference, with a search box and filters by tool and by tag, is at `https://book.ceph-s3.ir/en/cli-reference.html`. The commands used in the chapters are in [Appendix B: Command Cheat Sheet](#appB).

# How the reference is built

The list is not copied from the manual pages. A script in the book's repository (`tools/gen_cli_reference.py`) reads the Ceph source tree at the release tag and extracts what each tool really accepts: the monitor and manager command tables and the commands of the manager modules for `ceph`, the command table and the option loop of `radosgw-admin`, the command dispatch of `rados`, the registered actions and their option sets for `rbd`, and the argument parsers of `ceph-volume` and `cephfs-journal-tool`. It then looks for each command and option in the Ceph documentation (the manual pages and the command lines quoted in the guides) and in the tool's own usage text, and tags the result. The data records the tag and the commit it was built from, so the reference can be rebuilt for a later point release with `make cli-reference`.

# What the tags mean

| Tag | Meaning |
|---|---|
| both | The code accepts it and the documentation mentions it. |
| code-only | The code accepts it but the documentation does not mention it: undocumented. |
| docs-only | The documentation mentions it but the code does not accept it: stale or removed. |
| usage-only | The tool's own help text lists it but the code does not parse it. |
| no-usage | The code parses it but the tool's own help text does not list it. |

The last two tags apply only where the help text is written by hand (`radosgw-admin`, `rados` and `cephfs-journal-tool`) and to the per-command help of `rbd`. A docs-only or code-only tag is a pointer, not a verdict: a guide may describe a command in other words. Each entry in the web edition links to its line in the Ceph source and in the documentation, so it can be checked before you rely on it.

# Notable findings in 20.2.5

- `radosgw-admin --help` lists `zone rm` and `period rm`, while the command table has only `zone delete` and `period delete` (and the alias `del`). `pool add`, `pool rm` and `pools list` are still in the help text and the manual page but no longer in the code.
- `radosgw-admin sync status` and `bucket sync status`, two of the most used multisite commands, are accepted but missing from `radosgw-admin --help`.
- The manual page of `radosgw-admin` describes `role rm`, `role modify` and `role-policy rm`; in the code they are `role delete`, `role-trust-policy modify` (the assume-role policy) and `role-policy delete`.
- `rbd group info`, `rbd pool stats` and `rbd perf image iostat` and `iotop` are missing from the `rbd` manual page, and `ceph-volume raw` has no page of its own in the guides.
- Some guides quote commands that no longer exist under that name, for example `ceph osd crush rule remove` (the command is `osd crush rule rm`) and `ceph osd listpools` (now `osd lspools`).

In the web edition, the commands that are also in the cheat sheet carry the book's short note, an example and a link to the section that explains them; the others show the name, the options and the help string printed by the tool itself.
