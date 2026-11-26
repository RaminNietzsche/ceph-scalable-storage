# End-of-chapter quizzes

Every chapter page of the web edition ends with a short multiple-choice quiz: 4 to 6 questions on that chapter's own text. Each question links to the section it tests, and an explanation appears right after the reader answers. The quizzes complement the chapter's open **review questions** and their answers in Appendix E; they do not repeat them.

## Source files

One bilingual file per chapter, `references/quizzes/chNN.yaml`, is the single source for both editions:

```yaml
chapter: 2
questions:
  - id: rbd-netdev            # unique in the whole book: lowercase letters, digits and -
    ref: sec-02-4-2           # the section the question tests; a {#sec-NN-...} anchor of this chapter
    q:
      fa: "..."
      en: "..."
    options:                  # 3-5 options, in the order shown
      - fa: "..."
        en: "..."
      - fa: "..."
        en: "..."
        correct: true         # exactly one, unless the question sets multi: true
    why:                      # shown after answering
      fa: "..."
      en: "..."
  - id: ...
    multi: true               # multi-select: at least two correct options and at least one wrong one
```

Inline markup is limited to `` `code` `` (rendered left to right and bidi-isolated, so commands read correctly inside Persian sentences) and `**bold**`. Math and raw HTML are not allowed.

Guidelines for writing questions:

- Ask about one idea from the chapter, in words a reader of that chapter can answer. Prefer "why" and "what happens if" over recall of a number.
- Wrong options should be plausible mistakes a reader might make, not jokes. Avoid "all of the above" and "none of the above".
- Vary the position of the correct option.
- The explanation says why the right answer is right, in one to three sentences, using the chapter's own facts.
- Write the Persian and English text together, so the two editions stay the same quiz.

## Validation

`make check-quizzes` (part of `make check`) runs `tools/check_quizzes.py`. It fails when:

- a chapter has no quiz file, or a file does not belong to a chapter;
- a chapter has fewer than 4 or more than 6 questions, or a question has fewer than 3 or more than 5 options;
- an id is malformed or used twice in the book;
- a question, option or explanation lacks its Persian or English text;
- a question does not have exactly one correct option (or, with `multi: true`, at least two correct and one wrong);
- two options of a question have the same text;
- `ref` is not a section anchor of that chapter in both editions;
- the correct option is in the same position for every question of a chapter;
- a question repeats one of the chapter's review questions word for word;
- the text breaks the prose rules (Arabic ي/ك, «می» without ZWNJ, space before punctuation, Latin `?` in Persian, Persian letters in English, double or trailing spaces, `$`, HTML).

`make check-site` checks the built pages: each chapter page has its quiz with the same number of questions as the source, every question has a working link to its section, and every question has exactly one correct option (or more for multi-select).

## On the site

`tools/build_site.py` renders the quiz as a `<section id="chapter-quiz">` after the chapter text, and adds it to the chapter's "On this page" list. Each question is a `<fieldset>` with native radio buttons (checkboxes for multi-select), so the keyboard works as everywhere else: Tab moves between questions, the arrow keys move between options (in the right direction in the Persian edition too), Space selects, and Enter checks the answer. Feedback is announced through a live region; correct and chosen options are marked with text for screen readers, not only with colour.

Without JavaScript the quiz is still readable: each question has a "Show answer and explanation" disclosure. `templates/site/game.js` turns it into the interactive quiz.

A run is **passed** when every answer is right. The reader can try again at any time. Progress is stored in the browser only, in the same `book-progress:<lang>` record as the rest of the game layer (see [GAMIFICATION.md](GAMIFICATION.md)):

- `g.cq[N]`: per chapter, `p` (time of the first pass, or 0), `b` (best score) and `a` (number of completed runs);
- `g.cqa[id]`: the first answer ever given to a question (1 right, 2 wrong).

## In print

The print PDF, EPUB and Word editions do not include the multiple-choice quizzes. They already end every chapter with open review questions and have the full answer key in Appendix E, which suits paper better: a printed multiple-choice quiz shows the options and the answer key together, and gives no immediate feedback, the part that makes these quizzes useful. Leaving them out also keeps more than 200 extra questions (around 40 pages) out of a book that is already very long. The introduction to Appendix E tells print readers that the web edition has the quizzes.
