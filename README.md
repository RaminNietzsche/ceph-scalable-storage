# Ceph: Scalable Storage — راهنمای جامع Ceph

An original Persian book on Ceph, with a parallel English edition (*The Comprehensive Ceph Guide*). It goes from first cluster to source code and on-disk bytes, in 42 chapters with 375 figures and 188 algorithm boxes, and is built from Markdown sources with one `make` command.

**Read it:** [book.ceph-s3.ir](https://book.ceph-s3.ir) · [Persian](https://book.ceph-s3.ir/fa/) · [English](https://book.ceph-s3.ir/en/) · Cheat Sheet ([FA](https://book.ceph-s3.ir/fa/cheatsheet.html) / [EN](https://book.ceph-s3.ir/en/cheatsheet.html) · [PDF FA](https://book.ceph-s3.ir/fa/ceph-cheatsheet-fa.pdf) / [PDF EN](https://book.ceph-s3.ir/en/ceph-cheatsheet-en.pdf)) · [Releases](https://github.com/RaminNietzsche/ceph-scalable-storage/releases)

[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.24253822.svg)](https://doi.org/10.5281/zenodo.24253822)

| | Persian (`fa`, canonical) | English (`en`) |
|---|---|---|
| Content | `content/fa/` | `content/en/` (translation of the Persian text) |
| Print | `make pdf` | `make pdf LANG=en` |
| Status | v1.8, 1392 pages | v1.8, 1405 pages, translated (see `make check-parity`) |
| Live site | [book.ceph-s3.ir/fa/](https://book.ceph-s3.ir/fa/) | [book.ceph-s3.ir/en/](https://book.ceph-s3.ir/en/) |

## Building

**Prerequisites:** Python 3.11 or newer, GNU Make, Pandoc 3.6 (for HTML, EPUB and DOCX), Node.js 20 or newer (for KaTeX math, markdownlint and Mermaid figures), Chrome or Chromium (only to re-render figures and the cover), and the Vazirmatn, Inter, Source Serif and JetBrains Mono fonts.

```sh
python3 -m pip install -r requirements.txt   # WeasyPrint, Matplotlib, PyYAML, Pygments, codespell
npm install                                  # KaTeX (math, required), markdownlint-cli2, mermaid-cli (optional)
make html                                    # web book for LANG; fetches missing fonts on first run (make fonts)
make pdf                                     # build/fa/ceph-scalable-storage-fa.pdf
make site                                    # web book, fa and en: build/site/index.html
make site SITE_URL=https://example.org/ceph  # the same, with canonical links and absolute OG/sitemap URLs
make all                                     # pdf + web book + html-single + epub + docx, fa and en
make check                                   # lint, spell, refs, links, parity, reading paths
```

`LANG` must be `fa` or `en`. A locale value inherited from the environment, such as `en_US.UTF-8`, is ignored, so the default edition is `fa`. `make` and `make pdf` build the Persian edition; use `make pdf LANG=en` for English. `make help` lists every target.

- Fonts are installed automatically: `make pdf`, `make html` and `make site` depend on `make fonts`, which runs `tools/install_fonts.sh` only when fontconfig cannot find Vazirmatn, Inter, JetBrains Mono or Source Serif (Linux: `~/.local/share/fonts`, macOS: `~/Library/Fonts`; no root). On macOS, install fontconfig first with `brew install fontconfig`. After a fresh clone, `make html` is enough.
- `make html` writes the multi-page web book to `build/site/<lang>/`: one page per chapter and appendix, a collapsible sidebar (right-hand in Persian), in-page contents, previous/next, breadcrumbs, offline search (with ی/ي, ک/ك, ZWNJ and Persian-digit folding), figure zoom (wheel, drag, pinch), light/dark theme, highlighted code with copy buttons, a language switcher and a print stylesheet. Fonts, scripts and figures are copied next to the pages, so the site works offline and from `file://`. `make site` builds both editions and `make check-site` checks links and anchors. `make webfig` renders high-resolution web figures (3× Mermaid, SVG Matplotlib plots) so zoom stays sharp. The English build inserts soft hyphens with Pyphen patterns so justified text on a narrow screen does not leave large gaps.
- `make html-single`, `make epub` and `make docx` write Pandoc exports to `build/<lang>/`.
- Figures are committed, so Chrome is not needed to build the book. `make figures` re-renders only figures whose source (`.mmd`, `.bf.json` or `figures/i18n` labels) has changed. Change detection is a content hash, not the file mtime.
- To build without installing the toolchain on the host: `docker build -t ceph-book . && docker run --rm -v "$PWD":/book ceph-book make all`.

| Target | What it does |
|---|---|
| `pdf` | Print PDF (WeasyPrint, two-pass page-number index) for `LANG` |
| `cheatsheet` | Standalone printable A4 command cheat-sheet PDF (`build/LANG/ceph-cheatsheet-LANG.pdf`) |
| `html` | Multi-page web book for `LANG` in `build/site/LANG/` (see the notes above) |
| `site` | `html` for both editions; open `build/site/index.html` |
| `fonts` | Install Vazirmatn, Inter, JetBrains Mono and Source Serif with `tools/install_fonts.sh`, only if fontconfig cannot find them (Linux `~/.local/share/fonts`, macOS `~/Library/Fonts`, no root). `pdf`, `html` and `site` depend on it, so a fresh clone needs only `make html`; on macOS install fontconfig first (`brew install fontconfig`) |
| `webfig` | Render high-resolution web figures (3x mermaid / 2x byte-layout WebP, SVG plots) into `build/webfig/`; `make html` runs it |
| `check-site` / `shoot-site` | Check every link, anchor and offline resource of the web book, then the SEO audit (`tools/check_seo.py`) / headless-Chrome smoke test with screenshots |
| `html-single` / `epub` / `docx` | Pandoc exports for `LANG`; `html-single` is one self-contained file |
| `all` | Every format for both editions |
| `figures` | Re-render changed Mermaid / byte-layout figures and English label variants |
| `cover` | Regenerate the cover/back images for `LANG` |
| `lint` | markdownlint + prose/orthography rules (both editions) |
| `spell` | codespell (English, docs, tooling) + Persian orthography rules |
| `check-refs` | Figure, ALGO, section and answer cross-references resolve |
| `check-links` / `check-links-online` | URL syntax and `https`; `-online` also fetches |
| `check-parity` | `fa` and `en` have the same chapters, figure ids, ALGO ids and section anchors |
| `check-versions` / `check-tldr` / `check-publish` | Release labels (`{since=...}`) agree in fa and en and the release-changes data is complete / every chapter opens with a 3–5 bullet TL;DR / `.zenodo.json` and `CITATION.cff` match the book version |
| `check` | All offline checks |
| `sync-translations` | Create English placeholders for new Persian files |
| `stats` | Counts (chapters, figures, algorithms, references, answers) |
| `clean` / `distclean` / `dist` | Housekeeping; `dist` collects outputs and a `git archive` |

Web-edition options (edit links, feedback endpoint, newsletter form, cookie-less analytics, custom domain) are read from the environment at build time, for example `make site SITE_URL=https://book.ceph-s3.ir CF_BEACON_TOKEN=…`; none is stored in the repository. CI, GitHub Pages, releases, Zenodo DOIs and DNS are described in [docs/PUBLISHING.md](docs/PUBLISHING.md).

## Layout

```text
content/<lang>/
  metadata.yaml  ui.yaml      edition metadata and UI strings
  front/preface.md
  chapters/NN-slug.md         one file per chapter (YAML front matter + Pandoc Markdown)
  answers/NN.md               answers to each chapter's review questions
  appendices/                 troubleshooting guide, release table, upgrade guide, RGW security, multisite and DR, CLI reference pointer
  data/tools.yaml             tool descriptions
labs/                         hands-on labs with scripts (see labs/README.md)
figures/
  chNN/                       committed PNGs + sources (.mmd Mermaid, .bf.json byte layouts)
  app/                        the same, for figures of the appendices
  i18n/en.yaml                English label strings for Mermaid figures
  mermaid/                    Mermaid theme/config per language
  scripts/                    plot_*/measure_*/compute_* scripts (+ lib/ models)
  data/                       raw measurement/simulation data used by the plots
glossary/glossary.yaml        bilingual glossary (single source)
references/references.json    CSL-JSON bibliography (curated official sources)
references/ceph-release-changes.yaml  changes per Ceph release (appendix H) for the release labels
references/cheatsheet.yaml           bilingual command cheat sheet (Appendix B, web page & A4 PDF)
references/reading-paths.yaml        suggested reading paths per reader (web page paths.html, preface table, on-page hint)
references/cli-reference.yaml        every command and option of the main CLI tools, generated from the Ceph source (Appendix L, cli-reference.html; docs/CLI-REFERENCE.md)
templates/                    html front matter, print CSS (RTL/LTR), cover, Pandoc filter/CSS,
                              site/ (web book page template, CSS, JS, UI strings)
assets/                       rendered covers
tools/                        build, export, render and check scripts (Python, executable)
```

## Writing conventions (short)

The full guide is in [CONTRIBUTING.md](CONTRIBUTING.md). Planned additions, including the gaps found against a 2016 Ceph book, are listed in [ROADMAP.md](ROADMAP.md).

- Callouts are fenced divs: `::: {.tip}`, `.warn`, `.note`, `.try`, `.deep`, `.debug`, `.box`, `.summary`.
- Algorithms: `::: {.algo #alg-NN-K title="…" src="file::function" complexity="…"}`.
- Figures: `![caption](figures/chNN/name.png){#fig-NN-name}`. When a file `name.<lang>.png` exists, that edition uses it.
- Headings carry stable ids (`{#sec-NN-K}`), and the English edition keeps the Persian ids. `tools/renumber_sections.py` fixes them after you reorder sections.

## Citing this book

If you use the book, please cite it. GitHub’s “Cite this repository” button reads [CITATION.cff](CITATION.cff). The concept DOI (all versions) is [10.5281/zenodo.24253822](https://doi.org/10.5281/zenodo.24253822); the DOI of version 1.7 is [10.5281/zenodo.24434974](https://doi.org/10.5281/zenodo.24434974) (version 1.6: [10.5281/zenodo.24253823](https://doi.org/10.5281/zenodo.24253823)).

Najarbashi, Ramin. *The Comprehensive Ceph Guide: Designing, Implementing and Operating Scalable Storage — from the Code to Operations*. 1.8. 2026. <https://doi.org/10.5281/zenodo.24253822>. <https://book.ceph-s3.ir>. CC BY-NC-SA 4.0. ORCID: [0009-0000-7622-8130](https://orcid.org/0009-0000-7622-8130).

## Contributing and feedback

See [CONTRIBUTING.md](CONTRIBUTING.md) for the workflow, Markdown conventions and translation notes. On the [live site](https://book.ceph-s3.ir) every page has an “Edit this page” link back to the source file on `main`. After a “No” on “Was this section helpful?”, the site can open a prefilled GitHub issue with the `feedback` label; you can also [browse or open feedback issues](https://github.com/RaminNietzsche/ceph-scalable-storage/issues?q=label%3Afeedback) directly. Run `make check` before you send a change; it must report 0 errors.

## Licence

The text, figures, templates and the tools/scripts are under a single licence, [CC BY-NC-SA 4.0](LICENSE) (Attribution-NonCommercial-ShareAlike 4.0 International): free to share and adapt with attribution, under the same licence, and **not for commercial use**. Quoted upstream code excerpts keep their original licences; see [NOTICE.md](NOTICE.md).
