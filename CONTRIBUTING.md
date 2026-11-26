# Contributing

Thanks for helping. This file covers the workflow, the Markdown conventions and how
to translate.

## Licence of contributions

This repository is licensed under [CC BY-NC-SA 4.0](LICENSE) — text, figures and
tools alike. By contributing, you agree that your contribution is released under the
same licence. Do not add material that cannot be distributed under it; quoted
upstream code excerpts must stay short, attributed and keep their original licence.

## Workflow

1. Edit the sources under `content/fa/` (canonical) or translate under `content/en/`.
2. Run `make check`. It must report 0 errors.
3. Run `make pdf` (and `make pdf LANG=en` if you touched English) and look at the
   pages you changed.
4. Commit in small, focused commits. Use an imperative subject line, for example
   `ch12: correct min_alloc_size default for HDD`, and add a `CHANGELOG.md` entry
   under *Unreleased*.

## Content rules

- **Original text only.** Do not copy prose, figures or exercises from any book.
- **No invented facts.** Never invent version numbers, defaults or behaviour. Mark
  version-specific behaviour, for example "(since Squid 19.2)". Mark examples that
  were not measured as examples.
- **Code excerpts are short and attributed**, with project, licence and path, for
  example `ceph/ceph, LGPL — src/osd/PrimaryLogPG.cc`.
- **No secrets or customer data.** Redact cephx/OSD keys (`AQ…==` → `<redacted>`)
  and anonymise host names, IPs and customers.

## Markdown conventions

| Construct | Syntax |
|---|---|
| Chapter metadata | YAML front matter: `chapter`, `id`, `title`, `part` (`main`, `special`, `lower`), `lang` |
| Section | `# Title {#sec-NN-K}`, and `## Title {#sec-NN-K-M}` for subsections |
| Figure | `![caption](figures/chNN/name.png){#fig-NN-name}`; in an appendix `![caption](figures/app/name.png){#fig-app-name}` |
| Callout | `::: {.tip}` … `:::`; also `.warn` `.note` `.try` `.deep` `.debug` |
| TL;DR | `::: {.tldr}` … `:::` (right after front matter) |
| Box | `::: {.box title="…"}` |
| Summary | `::: {.summary title="…"}` |
| Algorithm | `::: {.algo #alg-NN-K title="…" src="file::function" complexity="…"}` |
| Table | pipe tables; write a literal pipe inside a cell as `\|` |
| Inline math | `$p = 10^{-14}$`, `$(1-p)^N \approx e^{-pN}$`, `$3.2 \times 10^{14}$` |

Math is TeX between dollars, with no space just inside the dollars (a `$` followed
by a digit is not math, so prices stay plain text). Use Latin digits inside math in
both editions: the Persian build keeps Persian digits in the surrounding prose and
isolates each formula left-to-right. Titles, headings, figure captions and algorithm
attributes are plain text, so write Unicode superscripts there (`GF(2⁸)`, `O(k³)`).
The web book and the PDF render math with the bundled KaTeX
(`templates/vendor/katex`, `tools/render_math.mjs`; offline, needs `npm install`);
the EPUB and HTML exports get MathML and DOCX gets Word equations from Pandoc.
`make lint` rejects a bare `^` exponent outside code or math, an unbalanced `$`, and
Persian digits or bidi marks inside math. The site never contains soft hyphens:
hyphenation is CSS `hyphens: auto` with the page `lang`, so copied text stays clean.

### Chapter TL;DR boxes

Every chapter opens right after its YAML front matter with a single `::: {.tldr}` box containing:

1. **Three to five `- ` bullets**, matching in count and inline code spans between `fa` and `en`.
2. **One key Ceph CLI command** in a fenced code block (```` ```bash ```` or ```` ```bash {since=...} ```` when the command needs a release newer than Reef).
   - **Rule for chapters without a command block:** if a chapter has no fenced command block in its body, put the most illustrative real Ceph CLI command discussed in that chapter's prose or tables (present in both `fa` and `en`). For a purely conceptual chapter where no CLI command applies, omit the fenced command block in both `fa` and `en` rather than inventing one.
3. **One figure thumbnail link** reusing an existing figure from the same chapter: `[![caption](figures/chNN/name.png)](#fig-NN-name)`. Never use `{#fig-...}` inside `.tldr` (that would duplicate the figure id and shift figure numbering); clicking the thumbnail jumps to the full figure in the chapter.

`make check-tldr` checks all of these rules across both editions.

An appendix written in Markdown may open with the same box (appendix I, the upgrade guide, appendix J, RGW security, and appendix K, multisite and DR, do). Its figure lives in `figures/app/` and the thumbnail points to an appendix figure: `[![caption](figures/app/name.png)](#fig-app-name)`. `check-tldr` covers chapters only; `check-parity` keeps the two editions of the appendix in step.

The Python tools and the Pandoc filter (`templates/pandoc/book.lua`) both read this
format. `tools/booklib/mdlower.py` turns it into the print renderer's directive
stream.

## Translating to English

Every English file starts as a placeholder copy of the Persian file. Placeholders
carry `translation: pending` in the front matter, or a first line of
`<!-- translation: pending -->` for answer files. `make sync-translations` creates
placeholders for new Persian files.

To translate a file:

1. Translate the prose **from our Persian text**, faithfully and completely.
   Keep commands, identifiers, numbers and URLs byte-identical. Inside code
   blocks, translate only the `#` comments and leave the commands untouched.
2. Keep every id unchanged: `{#sec-…}`, `{#fig-…}`, `{#alg-…}`. Keep the same
   number and order of sections, figures and algorithm boxes.
3. Use these exact headings for the two fixed sections, because the build
   recognises them: `Review questions` and `Sources for this chapter`.
4. Remove `translation: pending` (or the comment line).
5. Translate the chapter's Mermaid labels. Run
   `tools/translate_figures.py --lang en --extract chNN`, fill in the `null` values
   in `figures/i18n/en.yaml`, then run `make figures`. A variant is generated only
   when every label of the figure is translated.
6. Run `make check-parity`. It compares chapters, section anchors, figure ids and
   ALGO ids between the two editions and must report 0 errors.

The glossary is a single file (`glossary/glossary.yaml`): each entry has `term`,
`fa` and `en`. The English edition falls back to the Persian definition until `en`
is filled in.

## Tools

The scripts in `tools/` and `figures/scripts/` follow these rules:

- verb–noun names (`render_pdf.py`, `check_parity.py`);
- a `#!/usr/bin/env python3` shebang and the executable bit;
- repository-relative paths only;
- `--help` works.

Measurement scripts (`figures/scripts/measure_*`) need a disposable test cluster
(`CEPH_CONF=/path/ceph.conf`). Never run them against production.
