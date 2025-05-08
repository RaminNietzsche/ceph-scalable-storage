# NOTICE / Attribution

## What this book is based on

The **order of topics** in chapters 1–21 follows the *public table of contents* of
*Ceph: Designing and Implementing Scalable Storage Systems* (Vikhyat Umrao, Karan Singh, Nick Fisk, Anthony D'Atri, Vaibhav Bhembre, 2019, ISBN 9781788295413). No text, figures, code or exercises
from that book were used. Every sentence, diagram, algorithm write-up and question
here is original. Chapter headings that repeat the public TOC wording are kept in
the `original_heading` front-matter field only.

The English edition (`content/en/`) is a translation of **this book's own Persian
text** (`content/fa/`), not of the original book.

## Quoted source code

The book quotes short excerpts (usually a few lines) and names functions, constants
and on-disk structures from the projects below. Each excerpt is attributed where it
appears and keeps its upstream licence. It is not covered by CC BY-SA 4.0.

| Project | Upstream | Licence (as published upstream) |
|---|---|---|
| Ceph | <https://github.com/ceph/ceph> | LGPL-2.1 / LGPL-3.0 (per file; see upstream `COPYING`) |
| ceph-nvmeof | <https://github.com/ceph/ceph-nvmeof> | LGPL-3.0 |
| dmclock | <https://github.com/ceph/dmclock> | LGPL-2.1 |
| RocksDB | <https://github.com/facebook/rocksdb> | GPL-2.0 or Apache-2.0 (dual) |
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
