# Labs

[فارسی](README.fa.md)

Hands-on labs that go with the book. Each lab is a directory with its own README,
prerequisites, scripts and a "Tested on" section that states exactly what has been
validated.

| Lab | What it builds | Chapters |
|---|---|---|
| [cephadm-single-host](cephadm-single-host/README.md) | a one-VM cluster with three OSDs, RBD, CephFS and RGW | 1, 2, 4, 6, 11, 19 |

Conventions for every lab script: `set -euo pipefail`, idempotent steps, `--help`
and `--dry-run`, settings in a local env file that is not committed, and a clean
`shellcheck` run (checked in CI).

The labs are under the same licence as the book (CC BY-NC-SA 4.0).
