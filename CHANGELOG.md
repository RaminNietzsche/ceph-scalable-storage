# Changelog

All notable changes to this book are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Book versions are
`MAJOR.MINOR`: a minor version adds or corrects content, and a major version
restructures the book.

## [Unreleased]

### Changed

- Relicensed the whole repository (text, figures, templates, tools and scripts)
  under a single licence, CC BY-NC-SA 4.0 (previously CC BY-SA 4.0). Quoted
  upstream code excerpts keep their original licences.

### Added

- The book is now a source repository. The content is Pandoc Markdown with fenced
  divs, organised as `content/fa` and `content/en` with the same structure.
- Shared figures with per-language label strings (`figures/i18n/<lang>.yaml`) and
  generated `<name>.<lang>.mmd` / `.png` variants.
- Single-source bilingual glossary (`glossary/glossary.yaml`) and a CSL-JSON
  bibliography (`references/references.json`).
- A `Makefile` with `LANG=fa|en`. It builds PDF (WeasyPrint), HTML, EPUB and DOCX
  (Pandoc), and runs the `lint`, `spell`, `check-refs`, `check-links` and
  `check-parity` checks. `make all` builds both editions.
- CI workflow (`.github/workflows/build.yml`), `Dockerfile`, pinned
  `requirements.txt` / `package.json`, `.editorconfig`, markdownlint config.
- 53 figure scripts (`figures/scripts/plot_*`, `measure_*`, `compute_*`) and their
  raw data (`figures/data/`). Before this they lived outside the book sources.
- English edition: started (see `content/en`, `make check-parity`).

### Fixed

- Troubleshooting appendix: the `jq` cell lost its escaped pipe
  (`ceph pg <pgid> query | jq .recovery_state`).

## [1.4] — 2026-11-15

### Added

- 18 new figures (350 in total) and 14 new algorithm boxes (143 in total). Many of
  them come from measurements on a Ceph 18.2.7 test cluster:
  - `rbd du` with and without `--exact` (ch. 2);
  - copyset and rebuild models computed exactly with `osdmaptool` (ch. 1);
  - host add / reweight data movement (ch. 8);
  - mgr stats lag against `mgr_stats_period`, and `pg dump` cost per PG (ch. 9);
  - Little's law and block-size sweep with `rados bench` (ch. 10);
  - `numops` against read-modify-write and Lua against client-side reads (ch. 15);
  - PG state timeline and host failure (ch. 17);
  - upmap and PG split (ch. 19);
  - OpTracker stages (ch. 22);
  - BlueStore label bytes and allocator free map (ch. 24);
  - pg-log memory and per-item cost (ch. 33).
- Preface section «تازه‌های نسخه‌ی ۱٫۴».

### Changed

- Version strings in every chapter document that still said 1.2.
- The PromQL table in ch. 20 was checked against the metric names in the mgr
  `prometheus` module and `prometheus_alerts.yml`.

### Fixed

- ch. 15: the `cls_lua` global table is `objclass`, not `cls`. This was checked on
  18.2.7 and against `cls_lua.cc`.
- ch. 15: corrected the error codes for `assert_version` (ERANGE / EOVERFLOW) and
  `cmpxattr` (ECANCELED).
- 1080 pages.

## [1.3] — 2026-11-15

### Added

- About 61 new figures (332 in total) and 52 new algorithm boxes (129 in total).
  They cover striping, object map, fast-diff, bucket-index sharding and resharding,
  datalog and mdlog sharding, dirfrag split and merge, Paxos failure handling,
  dmclock, autoscaler, compression and min_alloc amplification, and more.
- Preface section «تازه‌های نسخه‌ی ۱٫۳».

### Fixed

- ch. 16: the cache-tier eviction condition was inverted. It was checked against
  `PrimaryLogPG::agent_maybe_evict`.
- ch. 24: `range_seg_t` is 80 bytes (checked with a compile test).
- ch. 24: RGW lifecycle marker format, and the worked hash example recomputed.
- `!TABLE` blocks without `!ENDTABLE` (ch. 14, 16, 24).
- 1050 pages.

## [1.2] — 2026-11-15

### Added

- New chapters 30–33: Crimson/Seastar, SPDK and NVMe-oF, scrub/recovery/repair,
  memory and CPU.
- Algorithm boxes (77) with pseudocode, complexity, a worked example and the source
  `file::function` for each. Appendix «فهرست الگوریتم‌ها».
- Byte-layout figure generator. Figures grew from 177 to 271.
- 16 new glossary terms. 954 pages.

## [1.1] — 2026-11-15

### Added

- New section of low-level chapters 23–29: block device and bufferlist, BlueStore
  on-disk format, RocksDB, msgr2, erasure-code math, CRUSH internals, kernel
  clients.
- Expanded chapters 13, 14, 16, 18, 20 and 21.
- 758 pages, 177 figures, 230 references, 290 answers.

## [1.0] — 2026-11-15

### Added

- First complete edition with 22 chapters. Chapters 1–21 follow the public TOC.
  Chapter 22, "Ceph code architecture", walks end to end through a RADOS write, RBD,
  an RGW PUT and CephFS.
- "From the code" deep dives in every chapter, with short attributed excerpts
  (ceph/ceph, LGPL).
- Review questions with answers, a glossary, a troubleshooting appendix and a
  versions appendix.
- 587 pages, 134 figures, 191 references.

[Unreleased]: #unreleased
[1.4]: #14--2026-11-15
[1.3]: #13--2026-11-15
[1.2]: #12--2026-11-15
[1.1]: #11--2026-11-15
[1.0]: #10--2026-11-15
