# Contributing

Thanks for helping. This file covers the workflow, the Markdown conventions and how
to translate.

## Workflow

1. Edit the sources under `content/fa/` (canonical) or translate under `content/en/`.
2. Run `make check`. It must report 0 errors.
3. Run `make pdf` (and `make pdf LANG=en` if you touched English) and look at the
   pages you changed.
4. Commit in small, focused commits. Use an imperative subject line, for example
   `ch12: correct min_alloc_size default for HDD`, and add a `CHANGELOG.md` entry
   under *Unreleased*.

## Content rules

- **Original text only.** Do not copy prose, figures or exercises from any book. The
  original book is used only for the order of topics (public TOC).
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
| Chapter metadata | YAML front matter: `chapter`, `id`, `title`, `part` (`main`, `special`, `lower`), `original_heading`, `lang` |
| Section | `# Title {#sec-NN-K}`, and `## Title {#sec-NN-K-M}` for subsections |
| Figure | `![caption](figures/chNN/name.png){#fig-NN-name}` |
| Callout | `::: {.tip}` … `:::`; also `.warn` `.note` `.try` `.deep` `.debug` |
| Box | `::: {.box title="…"}` |
| Summary | `::: {.summary title="…"}` |
| Algorithm | `::: {.algo #alg-NN-K title="…" src="file::function" complexity="…"}` |
| Table | pipe tables; write a literal pipe inside a cell as `\|` |

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
   Keep commands, code blocks, identifiers, numbers and URLs byte-identical.
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
