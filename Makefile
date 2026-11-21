# Ceph: Scalable Storage — bilingual book build
#
#   make                 # PDF of the default edition (LANG=fa)
#   make pdf LANG=en     # PDF of the English edition
#   make html            # multi-page web book for LANG (build/site/LANG)
#   make all             # pdf + web book + single HTML + epub + docx for fa and en
#   make check           # lint, spell, refs, links (offline), parity
#   make site SITE_URL=https://example.org/ceph   # web book with canonical and absolute OG/sitemap URLs
#   make help            # list targets
#
# LANG selects the edition and must be fa or en. A locale value inherited from
# the environment (e.g. LANG=en_US.UTF-8) is ignored and the default fa is used.

SHELL       := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := pdf
MAKEFLAGS   += --no-builtin-rules --warn-undefined-variables
# a recipe that fails removes its half-written target (no empty book.html or PDF left behind)
.DELETE_ON_ERROR:

EDITIONS    := fa en
BOOK_LANG   := $(if $(filter $(EDITIONS),$(LANG)),$(LANG),fa)
L           := $(BOOK_LANG)
unexport LANG
export LC_ALL     := C.UTF-8
export PYTHONUTF8 := 1
export PYTHONDONTWRITEBYTECODE := 1

PYTHON      ?= python3
PANDOC      ?= pandoc
MDLINT      ?= $(shell command -v markdownlint-cli2 || echo node_modules/.bin/markdownlint-cli2)
NAME        := ceph-scalable-storage
VERSION     := $(shell sed -n 's/^version: *"\(.*\)"/\1/p' content/fa/metadata.yaml)
B           := build/$(L)
DIST        := dist

# ---- dependency sets -------------------------------------------------------
TOOLS       := $(wildcard tools/*.py tools/booklib/*.py)
CONTENT     := $(shell find content/$(L) -type f) glossary/glossary.yaml references/references.json templates/site/sims/strings-$(L).yaml references/ceph-release-changes.yaml
TEMPLATES   := $(wildcard templates/html/*.$(L).html templates/css/book.$(L).css templates/cover/cover.$(L).yaml)
PANDOC_TPL  := $(wildcard templates/pandoc/*)
FIG_SRC     := $(wildcard figures/ch*/*.mmd figures/ch*/*.bf.json) $(wildcard figures/i18n/*.yaml)
FIG_STAMP   := build/.figures.stamp
COVER       := assets/cover.$(L).png assets/back.$(L).png

PDF         := $(B)/$(NAME)-$(L).pdf
BOOK_HTML   := $(B)/book.html
HTML        := $(B)/$(NAME)-$(L).html
EPUB        := $(B)/$(NAME)-$(L).epub
DOCX        := $(B)/$(NAME)-$(L).docx
SITE        := build/site
SITE_STAMP  := $(SITE)/$(L)/.stamp
SITE_URL    ?=
# web-edition deployment options, read by tools/build_site.py from the environment
# (see tools/booklib/siteconf.py); none of them is stored in the repository
export REPO_URL REPO_BRANCH FEEDBACK_ENDPOINT FEEDBACK_ISSUES ASK_ENDPOINT NEWSLETTER_ACTION ANALYTICS CF_BEACON_TOKEN PLAUSIBLE_DOMAIN CNAME
SITE_SRC    := tools/build_site.py tools/booklib/seo.py tools/booklib/siteconf.py CHANGELOG.md tools/sim_fallback.js $(wildcard templates/site/*) $(wildcard templates/site/sims/*)
WEBFIG_STAMP := build/webfig/.stamp

.PHONY: help all pdf html epub docx book figures cover lint markdownlint spell check-commands \
        check check-labs check-links check-links-online check-refs check-parity check-versions check-tldr check-publish check-sims \
        html-single site check-site shoot-site webfig fonts \
        sync-translations stats clean distclean dist

help: ## show this help
	@grep -hE '^[a-z][a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) | \
	  awk -F':.*## ' '{printf "  %-20s %s\n", $$1, $$2}'
	@echo "  LANG=fa|en (current: $(L)); version $(VERSION)"

all: ## every format for both editions
	@for l in $(EDITIONS); do $(MAKE) --no-print-directory LANG=$$l pdf html html-single epub docx; done

pdf: fonts $(PDF) ## print PDF (WeasyPrint, two-pass index) for LANG
html: fonts $(SITE_STAMP) ## multi-page web book (offline search, zoom, themes) into build/site/LANG
html-single: $(HTML) ## single-file HTML (Pandoc, embedded resources) for LANG
site: fonts ## web book for both editions (build/site, with language switcher)
	@for l in $(EDITIONS); do $(MAKE) --no-print-directory LANG=$$l html; done
epub: $(EPUB) ## EPUB 3 for LANG
docx: $(DOCX) ## Word document for LANG
book: $(BOOK_HTML) ## intermediate print HTML only

# Fonts: a fresh clone needs only `make html` / `make pdf`. tools/install_fonts.sh is
# run only when fontconfig cannot find a book font (Linux: ~/.local/share/fonts,
# macOS: ~/Library/Fonts). It is an order-only prerequisite, so it never forces a rebuild.
fonts: ## install Vazirmatn, Inter, JetBrains Mono and Source Serif if fontconfig lacks them
	@if bash tools/install_fonts.sh --check >/dev/null 2>&1; then echo "fonts: ok"; \
	 else bash tools/install_fonts.sh --check || true; bash tools/install_fonts.sh; fi

# ---- figures ---------------------------------------------------------------
figures: $(FIG_STAMP) ## render changed Mermaid / byte-layout figures (+ en label variants)
$(FIG_STAMP): $(FIG_SRC) tools/render_figures.py tools/render_bytefig.py tools/translate_figures.py
	$(PYTHON) tools/translate_figures.py --lang en
	$(PYTHON) tools/render_figures.py
	@mkdir -p $(@D) && touch $@

cover: ## regenerate the cover/back images for LANG into assets/
	$(PYTHON) tools/render_cover.py --lang $(L) --out $(B)/cover
	cp $(B)/cover/cover.png assets/cover.$(L).png
	cp $(B)/cover/back.png assets/back.$(L).png

# ---- print book (identical renderer to v1.4) ------------------------------
$(BOOK_HTML): $(CONTENT) $(TEMPLATES) $(COVER) $(TOOLS) $(FIG_STAMP) | fonts
	$(PYTHON) tools/build_book.py --lang $(L) --out $(B)

$(PDF): $(BOOK_HTML) tools/render_pdf.py | fonts
	$(PYTHON) tools/render_pdf.py --lang $(L) --build $(B) --out $@

# ---- web edition -----------------------------------------------------------
webfig: $(WEBFIG_STAMP) ## high-resolution web figure variants (3x Mermaid, 2x byte layouts, SVG plots) in build/webfig
$(WEBFIG_STAMP): $(FIG_STAMP) tools/render_web_figures.py $(wildcard figures/scripts/*.py figures/scripts/lib/*.py)
	$(PYTHON) tools/render_web_figures.py || echo "webfig: some variants failed; the web book falls back to the print PNGs"
	@mkdir -p $(@D) && touch $@

$(SITE_STAMP): $(BOOK_HTML) $(SITE_SRC) $(WEBFIG_STAMP) | fonts
	$(PYTHON) tools/build_site.py --lang $(L) --book $(B) --out $(SITE) --site-url '$(SITE_URL)'
	@touch $@

check-site: ## links, anchors, offline-only resources, SEO metadata and content checks (check_lists.py) of the built web book
	$(PYTHON) tools/check_site.py --site $(SITE)
	$(PYTHON) tools/check_seo.py --site $(SITE)
	$(PYTHON) tools/check_lists.py --site $(SITE)
	$(PYTHON) tools/check_features.py --site $(SITE)

shoot-site: ## headless-Chrome smoke test + screenshots of the web book (needs playwright)
	$(PYTHON) tools/shoot_site.py --site $(SITE) --out build/site-shots

# ---- Pandoc exports --------------------------------------------------------
$(B)/$(NAME)-$(L).%: $(CONTENT) $(PANDOC_TPL) tools/export_pandoc.py $(FIG_STAMP)
	PANDOC=$(PANDOC) $(PYTHON) tools/export_pandoc.py --lang $(L) --format $* --out $@

# ---- quality gates ----------------------------------------------------------
lint: markdownlint ## markdownlint + prose/orthography lint (both editions)
	$(PYTHON) tools/lint_prose.py --lang all

markdownlint:
	$(MDLINT) "content/**/*.md" "*.md" "figures/scripts/README.md"

spell: ## codespell (en + tooling) and Persian orthography rules (fa)
	$(PYTHON) tools/lint_prose.py --lang fa
	$(PYTHON) tools/lint_prose.py --lang en
	codespell --ignore-words .codespell-ignore README.md CONTRIBUTING.md CHANGELOG.md tools figures/scripts

check-labs: ## shellcheck every lab script under labs/ (needs shellcheck; run in CI)
	shellcheck -x $(wildcard labs/*/*.sh)

check-links: ## URL syntax/https check (offline)
	$(PYTHON) tools/check_links.py --lang all

check-links-online: ## also fetch every URL (network)
	$(PYTHON) tools/check_links.py --lang all --online

check-refs: ## figure/ALGO/section/answer cross-references resolve
	$(PYTHON) tools/check_refs.py --lang all

check-parity: ## fa and en have the same chapters, figure ids, ALGO ids, anchors
	$(PYTHON) tools/check_parity.py

check-sims: ## simulator math (CRUSH, autoscaler, Striper, ...) against Ceph's own code (tests/sims/golden.json)
	node tests/sims/test_core.js

check: lint spell check-refs check-links check-parity check-versions check-tldr check-publish check-sims ## all offline checks

check-publish: ## .zenodo.json and CITATION.cff are complete and match the book version
	$(PYTHON) tools/check_publish.py

check-tldr: ## every chapter opens with a 3-5 bullet TL;DR, fa and en in step
	$(PYTHON) tools/check_tldr.py

check-versions: ## release labels on command blocks (fa/en) and references/ceph-release-changes.yaml
	$(PYTHON) tools/check_versions.py

check-commands: ## Ceph command lines vs the Ceph source, main and release branches (network: shallow clones of ceph/ceph)
	$(PYTHON) tools/check_ceph_commands.py $(if $(CEPH_SRC),--ceph-src $(CEPH_SRC))

sync-translations: ## create/refresh en placeholders for new fa files
	$(PYTHON) tools/sync_translations.py --lang en

stats: $(BOOK_HTML) ## print counts (figures, ALGO, references) for LANG
	@cat $(B)/stats.json; echo

# ---- housekeeping ----------------------------------------------------------
clean: ## remove build outputs for every edition
	rm -rf build
	find . -name __pycache__ -type d -prune -exec rm -rf {} +

distclean: clean ## also remove dist/ and node_modules/
	rm -rf $(DIST) node_modules

dist: ## build/fa+en outputs into dist/ and a source archive (git archive)
	$(MAKE) --no-print-directory all
	mkdir -p $(DIST)
	for l in $(EDITIONS); do cp build/$$l/$(NAME)-$$l.{pdf,html,epub,docx} $(DIST)/; done
	cd build && rm -f ../$(DIST)/$(NAME)-$(VERSION)-site.zip && zip -qr ../$(DIST)/$(NAME)-$(VERSION)-site.zip site -x 'site/*/.stamp'
	git archive --format=tar.gz --prefix=$(NAME)-$(VERSION)/ -o $(DIST)/$(NAME)-$(VERSION)-src.tar.gz HEAD
	cd $(DIST) && sha256sum * > SHA256SUMS
