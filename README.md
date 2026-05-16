# Ceph: Scalable Storage — راهنمای جامع Ceph

An original Persian book on Ceph, with a parallel English edition. It goes from first
cluster to source code and on-disk bytes, in 42 chapters with 375 figures and 188
algorithm boxes, and is built from Markdown sources with one `make` command.

<div dir="rtl">

راهنمای فارسی و جامع Ceph، با ویرایش انگلیسی موازی. کتاب از نخستین کلاستر شروع می‌کند و تا کد منبع و بایت‌های روی دیسک پیش می‌رود: ۴۲ فصل، ۳۷۵ شکل و ۱۸۸ کادر الگوریتم. همه‌ی خروجی‌ها از منابع Markdown و با یک فرمان `make` ساخته می‌شوند.

</div>

| | Persian (`fa`, canonical) | English (`en`) |
|---|---|---|
| Content | `content/fa/` | `content/en/` (translation of the Persian text) |
| Print | `make pdf` | `make pdf LANG=en` |
| Status | v1.6, 1250 pages | in progress (see `make check-parity`) |

## ساختن کتاب (فارسی)

<div dir="rtl">

**پیش‌نیازها:** Python 3.11 یا جدیدتر، GNU Make، Pandoc 3.6 (برای HTML، EPUB و DOCX)، Node.js 20 یا جدیدتر (فقط برای markdownlint و رندر شکل‌های Mermaid)، Chrome یا Chromium (فقط برای رندر دوباره‌ی شکل‌ها و جلد)، و فونت‌های Vazirmatn، Inter، Source Serif و JetBrains Mono.

</div>

```sh
python3 -m pip install -r requirements.txt   # WeasyPrint, Matplotlib, PyYAML, Pygments, codespell
npm install                                  # markdownlint-cli2, mermaid-cli (optional)
make html                                    # web book for LANG; fetches missing fonts on first run (make fonts)
make pdf                                     # build/fa/ceph-scalable-storage-fa.pdf
make site                                    # web book, fa and en: build/site/index.html
make all                                     # pdf + web book + html-single + epub + docx, fa and en
make check                                   # lint, spell, refs, links, parity
```

<div dir="rtl">

- فونت‌ها خودکار نصب می‌شوند: `make pdf`، `make html` و `make site` به هدف `make fonts` وابسته‌اند که فقط اگر fontconfig یکی از فونت‌های Vazirmatn، Inter، JetBrains Mono یا Source Serif را پیدا نکند، `tools/install_fonts.sh` را اجرا می‌کند (لینوکس: `~/.local/share/fonts`، مک: `~/Library/Fonts`؛ بدون نیاز به root). در مک، fontconfig را با `brew install fontconfig` نصب کنید. پس از یک clone تازه همین `make html` کافی است.
- `make` و `make pdf` نسخه‌ی فارسی را می‌سازند. نسخه‌ی انگلیسی را با `make pdf LANG=en` بسازید.
- `make html` نسخه‌ی وب چندصفحه‌ای کتاب را در `build/site/<lang>/` می‌سازد: یک صفحه برای هر فصل و پیوست، فهرست کناری تاشو (در نسخه‌ی فارسی سمت راست)، فهرست «در این صفحه»، قبلی/بعدی، جست‌وجوی آفلاین با یکسان‌سازی ی/ي، ک/ك، نیم‌فاصله و ارقام فارسی، بزرگ‌نمایی شکل‌ها با چرخ، کشیدن و دو انگشت، پوسته‌ی روشن و تیره، رنگ‌آمیزی کد و دکمه‌ی کپی، تعویض زبان و برگه‌ی چاپ. فونت‌ها، اسکریپت‌ها و شکل‌ها کنار صفحه‌ها کپی می‌شوند و سایت بدون اینترنت و حتی با `file://` کار می‌کند. `make site` هر دو زبان را می‌سازد و `make check-site` پیوندها و anchorها را بررسی می‌کند. `make webfig` نسخه‌ی پرتراکم شکل‌ها را برای وب می‌سازد (نمودارهای mermaid با مقیاس ۳ و نمودارهای matplotlib به‌صورت SVG) تا بزرگ‌نمایی تیز بماند؛ در نسخه‌ی انگلیسی هنگام ساخت، نشانه‌ی شکستن کلمه (soft hyphen) با الگوهای Pyphen افزوده می‌شود تا متن هم‌تراز در موبایل فاصله‌ی زیاد نگیرد.
- `make html-single`، `make epub` و `make docx` خروجی‌های Pandoc را در `build/<lang>/` می‌سازند.
- شکل‌ها در مخزن ثبت شده‌اند، پس برای ساختن کتاب به Chrome نیازی نیست. `make figures` فقط شکل‌هایی را دوباره رندر می‌کند که منبعشان (`.mmd`، `.bf.json` یا برچسب‌های `figures/i18n`) تغییر کرده است. تشخیص تغییر با hash محتوا است، نه زمان فایل.
- اگر نمی‌خواهید چیزی نصب کنید، Docker کافی است: `docker build -t ceph-book . && docker run --rm -v "$PWD":/book ceph-book make all`.
- `make help` همه‌ی هدف‌ها را فهرست می‌کند.

**مجوز.** متن، شکل‌ها، قالب‌ها و ابزارها و اسکریپت‌های این مخزن همه با یک مجوز واحد، [CC BY-NC-SA 4.0](LICENSE) (اِسناد، غیرتجاری، اشتراک همسان ۴.۰ بین‌المللی)، منتشر شده‌اند: بازنشر و اقتباس با ذکر منبع و با همان مجوز آزاد است، اما **استفاده‌ی تجاری مجاز نیست**. تکه‌های کد نقل‌شده از پروژه‌های بالادستی مجوز اصلی خودشان را حفظ می‌کنند؛ [NOTICE.md](NOTICE.md) را ببینید.

</div>

## Building (English)

The prerequisites are the same as above. `LANG` must be `fa` or `en`. A locale value
inherited from the environment, such as `en_US.UTF-8`, is ignored, so the default
edition is `fa`.

| Target | What it does |
|---|---|
| `pdf` | Print PDF (WeasyPrint, two-pass page-number index) for `LANG` |
| `html` | Multi-page web book for `LANG` in `build/site/LANG/`: one page per chapter and appendix, collapsible sidebar (right-hand in Persian), in-page contents, previous/next, breadcrumbs, offline Persian-aware search, figure zoom (wheel, drag, pinch), light/dark theme, highlighted code with copy buttons, language switcher, print stylesheet; self-hosted fonts and no network access (works from `file://`) |
| `site` | `html` for both editions; open `build/site/index.html` |
| `fonts` | Install Vazirmatn, Inter, JetBrains Mono and Source Serif with `tools/install_fonts.sh`, only if fontconfig cannot find them (Linux `~/.local/share/fonts`, macOS `~/Library/Fonts`, no root). `pdf`, `html` and `site` depend on it, so a fresh clone needs only `make html`; on macOS install fontconfig first (`brew install fontconfig`) |
| `webfig` | Render high-resolution web figures (3x mermaid / 2x byte-layout WebP, SVG plots) into `build/webfig/`; `make html` runs it |
| `check-site` / `shoot-site` | Check every link, anchor and offline resource of the web book / headless-Chrome smoke test with screenshots |
| `html-single` / `epub` / `docx` | Pandoc exports for `LANG`; `html-single` is one self-contained file |
| `all` | Every format for both editions |
| `figures` | Re-render changed Mermaid / byte-layout figures and English label variants |
| `cover` | Regenerate the cover/back images for `LANG` |
| `lint` | markdownlint + prose/orthography rules (both editions) |
| `spell` | codespell (English, docs, tooling) + Persian orthography rules |
| `check-refs` | Figure, ALGO, section and answer cross-references resolve |
| `check-links` / `check-links-online` | URL syntax and `https`; `-online` also fetches |
| `check-parity` | `fa` and `en` have the same chapters, figure ids, ALGO ids and section anchors |
| `check` | All offline checks |
| `sync-translations` | Create English placeholders for new Persian files |
| `stats` | Counts (chapters, figures, algorithms, references, answers) |
| `clean` / `distclean` / `dist` | Housekeeping; `dist` collects outputs and a `git archive` |

## Layout

```text
content/<lang>/
  metadata.yaml  ui.yaml      edition metadata and UI strings
  front/preface.md
  chapters/NN-slug.md         one file per chapter (YAML front matter + Pandoc Markdown)
  answers/NN.md               answers to each chapter's review questions
  appendices/                 troubleshooting guide, release table
  data/tools.yaml             command cheat sheet
figures/
  chNN/                       committed PNGs + sources (.mmd Mermaid, .bf.json byte layouts)
  i18n/en.yaml                English label strings for Mermaid figures
  mermaid/                    Mermaid theme/config per language
  scripts/                    plot_*/measure_*/compute_* scripts (+ lib/ models)
  data/                       raw measurement/simulation data used by the plots
glossary/glossary.yaml        bilingual glossary (single source)
references/references.json    CSL-JSON bibliography (curated official sources)
templates/                    html front matter, print CSS (RTL/LTR), cover, Pandoc filter/CSS,
                              site/ (web book page template, CSS, JS, UI strings)
assets/                       rendered covers
tools/                        build, export, render and check scripts (Python, executable)
```

## Writing conventions (short)

The full guide is in [CONTRIBUTING.md](CONTRIBUTING.md).

- Callouts are fenced divs: `::: {.tip}`, `.warn`, `.note`, `.try`, `.deep`,
  `.debug`, `.box`, `.summary`.
- Algorithms: `::: {.algo #alg-NN-K title="…" src="file::function" complexity="…"}`.
- Figures: `![caption](figures/chNN/name.png){#fig-NN-name}`. When a file
  `name.<lang>.png` exists, that edition uses it.
- Headings carry stable ids (`{#sec-NN-K}`), and the English edition keeps the
  Persian ids. `tools/renumber_sections.py` fixes them after you reorder sections.

## Licence

The text, figures, templates and the tools/scripts are under a single licence,
[CC BY-NC-SA 4.0](LICENSE) (Attribution-NonCommercial-ShareAlike 4.0 International):
free to share and adapt with attribution, under the same licence, and **not for
commercial use**. Quoted upstream code excerpts keep their original licences; see
[NOTICE.md](NOTICE.md).
