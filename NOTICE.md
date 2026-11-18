# NOTICE / Attribution

## Licence of this work

The book text, figures, templates and the tools and scripts in this repository are
licensed under a single licence, [CC BY-NC-SA 4.0](LICENSE)
(Attribution-NonCommercial-ShareAlike 4.0 International). Commercial use is not
permitted without separate written permission. Quoted upstream code excerpts keep
their original licences (see below).

## Original work

This book is an original work by Ramin Najarbashi. Every sentence, diagram,
algorithm write-up and question in it was written for this book. The English
edition (`content/en/`) is the author's English version of the Persian text
(`content/fa/`).

## Quoted source code

The book quotes short excerpts (usually a few lines) and names functions, constants
and on-disk structures from the projects below. Each excerpt is attributed where it
appears and keeps its original upstream licence. It is not covered by the book's
CC BY-NC-SA 4.0 licence.

| Project | Upstream | Licence (as published upstream) |
|---|---|---|
| Ceph | <https://github.com/ceph/ceph> | LGPL-2.1 / LGPL-3.0 (per file; see upstream `COPYING`) |
| ceph-nvmeof | <https://github.com/ceph/ceph-nvmeof> | LGPL-3.0 |
| dmclock | <https://github.com/ceph/dmclock> | LGPL-2.1 |
| RocksDB | <https://github.com/meta/rocksdb> | GPL-2.0 or Apache-2.0 (dual) |
| Linux kernel (`net/ceph`, `fs/ceph`, `drivers/block/rbd.c`) | <https://github.com/torvalds/linux> | GPL-2.0 |
| Seastar | <https://github.com/scylladb/seastar> | Apache-2.0 |
| SPDK | <https://github.com/spdk/spdk> | BSD-3-Clause |
| ISA-L | <https://github.com/intel/isa-l> | BSD-3-Clause |
| Jerasure / GF-Complete | <https://github.com/ceph/jerasure> | BSD-3-Clause |
| liburing | <https://github.com/axboe/liburing> | MIT / LGPL-2.1 (dual) |
| Boost.Intrusive | <https://www.boost.org> | BSL-1.0 |
| Prometheus alert rules (ceph-mixin) | <https://github.com/ceph/ceph/tree/main/monitoring/ceph-mixin> | as listed in Ceph `COPYING` for `monitoring/` |

Before you redistribute an excerpt outside this book, check the licence header of
the exact upstream file. The table above is a summary, not legal advice.

`figures/data/rgw_reshard_primes.json` lists the `reshard_primes` constant table
from `src/rgw/driver/rados/rgw_reshard.cc` (Ceph, LGPL). It is used only to plot a
figure.

`templates/site/sims/crush-ln-table.js` contains the `crush_ln` lookup tables
(`__RH_LH_tbl`, `__LL_tbl`) of `src/crush/crush_ln_table.h` (Ceph; Copyright (C) 2015
Intel Corporation; LGPL-2.1), generated from that file by `tools/simref/gen_golden.py`.
It keeps the LGPL-2.1 licence and is shipped as a separate file of the web edition.
`tools/simref/crush_ref.c` compiles Ceph's own CRUSH sources from a local checkout at
test time; no Ceph source file is copied into this repository.

## Measurements

The numbers in the "measured" figures (chapters 2, 8–10, 15, 17, 19, 22, 24, 33)
come from a single-host test cluster (Ceph 18.2.7, memstore/BlueStore on sparse
files). They show **relative** behaviour only. The scripts and raw data are in
`figures/scripts/` and `figures/data/`.

## Fonts (not redistributed)

| Font | Licence | Used for |
|---|---|---|
| Vazirmatn (Saber Rastikerdar) | SIL OFL 1.1 | Persian text, Persian figure labels |
| Inter (Rasmus Andersson) | SIL OFL 1.1 | English headings and figure labels |
| Source Serif (Adobe) | SIL OFL 1.1 | English body text |
| JetBrains Mono | SIL OFL 1.1 | Code (English edition) |
| DejaVu Sans Mono | Bitstream Vera / public domain | Code (Persian edition) |

## Tools

The book is built with Pandoc (GPL-2.0-or-later), WeasyPrint (BSD-3-Clause),
Matplotlib (PSF-based), Mermaid CLI (MIT), markdownlint-cli2 (MIT) and codespell
(GPL-2.0). These are invoked as external programs and are not included here.
