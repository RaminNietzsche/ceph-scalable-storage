# Changelog

All notable changes to this book are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Book versions are
`MAJOR.MINOR`: a minor version adds or corrects content, and a major version
restructures the book.

## [Unreleased]

### Web edition redesign

- New home page: hero with the cover, a version badge, gradient title, call-to-action buttons and a stats row (chapters, figures, algorithms, parts); a decorative `ceph -s` terminal panel.
- "Where to start" section (`#get-started`) with six reader paths (new to Ceph, deployment, operations, troubleshooting, developer, Part IV specialist).
- "Four parts of the book" cards with chapter chips; Part IV marked as new.
- Header: logo mark and a "Get started" pill; sidebar groups chapters under part labels.
- New slate/cyan/emerald/indigo palette for light and dark themes; own CSS and SVG icons.
- `tools/shoot_site.py` skips the lightbox step on chapters without figures (pending English chapters) and records it as a note.

### Reading progress and motion (web edition)

- Reading-progress bar under the header on every page; back-to-top button with a progress ring.
- Per-chapter read state, stored per language in `localStorage` only: marked automatically at 90 % of the chapter, or with the toggle in the chapter header; shown as checkmarks and in-progress rings in the sidebar, chapter chips, home contents and part-card rings.
- Home "progress through the book" panel with a "Continue reading" button that reopens the last page at the saved scroll position.
- Estimated reading time per page (whitespace word count, so Persian words joined by ZWNJ count once; code lines and figures add time) in chapter headers, home contents and part cards.
- Bookmark buttons on section headings, highlighted bookmarked headings and a "My reading" panel listing bookmarks with export/import of progress as JSON and a reset.
- Motion: scroll reveal for cards, figures and headings; hero entrance and animated stat counters; hover micro-interactions; cross-document View Transitions where the browser supports them. All of it is switched off under `prefers-reduced-motion`.
- Mobile header no longer cuts off the book title (the "Get started" pill is hidden below 600 px).
- `tools/shoot_site.py` seeds a reading history and checks the progress panel, continue button, read toggle, bookmarks, the panel's Escape handling and, once with full motion, the hero counters and scroll reveal.

## [1.6] - 2026-11

### Added

- Part IV, "Specialist Part" (chapters 34–42), on RADOS, RBD and RGW, checked against the
  Ceph main branch (November 2026): RADOS object model and op path; pg log, past intervals
  and recovery; snapshots, watch/notify and cls; RBD image layout, striping and object map;
  the librbd I/O path, exclusive lock and caches; rbd-mirror internals; the RGW data model
  (bucket index, OLH versioning, manifest, multipart); the RGW request path (SigV4, quota,
  rate limit, gc, lifecycle); and multisite internals (period commit, log records, sync
  status objects, bilog generations, conflict resolution). 45 new algorithm boxes and 25
  new figures, with answers for every review question.
- English placeholder pages for chapters 34–42, so numbering matches the Persian edition.
- Glossary: 20 new terms (OLH, bilog, mdlog, period, error repo, bilog generation, SigV4,
  placement target, delete marker, multipart upload, RGW gc, RGW rate limit, SnapSet,
  SnapMapper, PastIntervals, divergent entry, watch/notify, hobject_t, PWL, mirror snapshot).
- Bibliography: Ceph developer docs for the bucket index, RGW placement and multisite.

### Changed

- Version 1.6 in metadata, covers (back text lists the specialist part), preface and README.

## [1.5] - 2026-11

### Changed

- The book is presented as an original authored work. Every reference to another book
  (title, authors, publisher, ISBN, rights notice, "not a translation" wording, page
  correspondences and the `original_heading` front-matter field) was removed from the
  front matter, colophon, preface, chapters, appendices, cover, metadata, README, NOTICE,
  CONTRIBUTING and LICENSE. Citations of Ceph documentation and papers are unchanged.
- New cover for both editions (`tools/render_cover.py`): an abstract CRUSH hierarchy and
  placement-group grid on a deep ink background, Vazirmatn / Inter, CC BY-NC-SA note.

### Earlier unreleased changes

- English edition: every chapter (1–33) and its answers is now a placeholder page with the
  note "The English translation of this chapter is in progress…" (`translation: pending`),
  so chapter, section, figure and algorithm numbering stay identical to the Persian edition.
  The existing English drafts (chapters 1–25 and part of 26) are kept on the `en-drafts`
  branch; chapters will be brought back one by one after the Persian pages are reviewed.
- `make fonts` installs the book fonts with `tools/install_fonts.sh` only when fontconfig
  cannot find them (macOS: `~/Library/Fonts`); `pdf`, `html` and `site` depend on it.
- The web book serves high-resolution figures: `make webfig` (`tools/render_web_figures.py`)
  renders mermaid diagrams at 3x and byte-layout figures at 2x as WebP (`srcset` 1x/2x) and
  re-runs the matplotlib scripts as SVG with text converted to paths, so zoomed figures stay
  sharp. Variants live in `build/webfig/`; any figure that fails falls back to the print PNG.
- English web pages are hyphenated at build time (Pyphen en_US patterns insert soft hyphens
  into long words outside code, headings and URLs), so justified text on narrow screens does
  not open wide gaps even where the browser has no English hyphenation dictionary.
- `make html` now builds a multi-page web book (`tools/build_site.py`,
  `templates/site/`): one page per chapter and appendix with stable source anchors,
  collapsible sidebar and in-page contents, previous/next and breadcrumbs, offline
  Persian-aware search, figure lightbox with wheel/drag/pinch zoom, light/dark theme,
  Pygments highlighting with copy buttons, fa/en switcher, print stylesheet and
  self-hosted fonts. The Pandoc single file moved to `make html-single`.
  `make check-site` and `make shoot-site` test the result.

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

- First complete edition with 22 chapters.
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
