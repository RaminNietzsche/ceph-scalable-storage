# Gamification in the web edition

The web edition (`make site`) has an optional game layer. It is there to support studying the book, not to replace it. Everything runs in the reader's browser: no account, no server, no analytics, no network requests. State is kept in `localStorage`, one record per language edition (`book-progress:fa`, `book-progress:en`), next to the reading progress that already existed.

Code: `templates/site/game.js` (logic and UI), `templates/site/game.yaml` (strings, level titles, badge names), `tools/build_site.py` (generates `<lang>/game-data.js`, `<lang>/learn-data.js` and the pages `progress.html`, `review.html`, `certificate.html`), styles in `templates/site/site.css`.

## Principles

The design follows three ideas from the research and from well-known learning products.

1. **Self-Determination Theory** (Ryan and Deci): motivation lasts when people feel *competence*, *autonomy* and *relatedness*. Rewards that feel controlling can crowd out the interest the reader already has.
   - Competence: XP, levels, a progress bar to the next level, badges with visible progress, spaced-repetition boxes, quiz feedback.
   - Autonomy: the reader picks the daily goal (10, 20 or 30 minutes, or one section), picks a learning path, can turn rest days on or off, and can switch the whole game layer off. No feature is locked behind the game.
   - Relatedness: in a book with no social backend this means a shared vocabulary rather than leaderboards. The level titles come from Ceph itself («کلاینت», «OSD», …, «معمار CRUSH»), the learning paths are the same "Where to start" paths as the home page, and finishing a path gives a certificate the reader can print.
2. **Octalysis** (Yu-kai Chou): use mostly the "white hat" drives (meaning, accomplishment, empowerment) and only a light touch of the "black hat" ones (scarcity, unpredictability, loss avoidance). Black-hat drives push people to act but make them feel worse. Here, hidden badges add a little curiosity. Loss avoidance is softened on purpose (see streaks).
3. **Learning science**: retrieval practice (testing yourself beats rereading; Roediger and Karpicke) and spacing (reviews spread over growing intervals; Cepeda et al.). The flashcards and the glossary quiz exist because they help people remember, and XP is only a light incentive on top.

## Avoiding dark patterns

- **No punishing streaks.** A streak counts days on which the daily goal was met. Missing a day never deletes anything; the streak just starts again, with a friendly message. **Streak freezes** (one per 500 XP, up to 3) are applied automatically. They are used only when the freezes can cover the *whole* gap, so a freeze is never wasted on a streak that would be lost anyway. **Rest days** (Friday in the Persian edition, Saturday and Sunday in the English one) are on by default: reading on a rest day still earns XP, and skipping one never breaks a streak. Duolingo's streak freeze is the model (see references); unlike Duolingo there is no currency and no purchase.
- **No nagging.** No notifications and no pop-ups that interrupt reading. Toasts are small, at the bottom, gone in a few seconds, at most three at a time, and announced through an ARIA live region. Suggestions ("best next chapter", "N cards ready") appear only on the dashboard and as a small strip on the home page.
- **Opt-out.** «نمایش امتیاز، نشان و روند» / "Show XP, badges and streaks" hides every game element (`html.no-game`). Reading progress, bookmarks and card review keep working. The data is still recorded locally, so switching the layer back on loses nothing. "Reset game data" clears only the game record and leaves read chapters and bookmarks alone.
- **No fake scarcity, no variable-ratio loot, no leaderboards, no social pressure.**
- **Honest rewards.** Energy points on Khan Academy measure effort, not mastery; XP here does the same and the dashboard says what it counts. The certificate states that it was generated in the reader's browser and that no central registry exists.
- **Sound is off by default.** It can be switched on for a tiny WebAudio tone; there are no audio files.
- **Reduced motion.** Under `prefers-reduced-motion` there is no confetti and no flicker, and transitions are off; the information is still shown as text.

## Mechanics

### XP and anti-farming

| Action | XP | Guard |
|---|---|---|
| Reading a section | 5 | Credited once per section, only after time spent with the section on screen (35 % of its estimated reading time, 6–120 s) *and* scrolling to its end, while the tab is visible and the reader was active in the last 90 s; 300 XP per day |
| Finishing a chapter | 50 | Once per chapter; only 10 if fewer than half of its sections were credited (a "mark as read" click alone earns little) |
| Reviewing a flashcard | 2 | 150 XP per day |
| Quiz answer | 3 right, 1 wrong | 120 XP per day; a wrong answer still earns effort XP |
| Seeing an algorithm box | 1 | Box at least half visible for 1.5 s; once per box; 60 XP per day |
| Daily goal met | 20 | Once per day |
| Weekly challenge done | 40 | Three challenges per week, chosen deterministically from the week number |
| Badge tier | 10 / 25 / 50 | Bronze / silver / gold |

Reading time is counted in 5-second steps under the same visibility and activity conditions.

### Levels

Twelve levels with thresholds 0, 100, 250, 500, 850, 1300, 1900, 2700, 3700, 5000, 6500 and 8500 XP. Persian titles go from «کلاینت» through «OSD», «مانیتور», «دروازه‌ی RGW» and «نگهبان BlueStore» to «معمار CRUSH». Reaching a new level shows a toast with light confetti (none under reduced motion).

### Badges

47 badges: 27 general ones and 20 lab medals. Twelve are tiered (bronze, silver, gold): chapters, sections, hours, streak, algorithm boxes, zoomed figures, reviewed cards, correct quiz answers, mastered glossary terms, bookmarks, XP, goal days. Seven are single: one per part (Part IV is the specialist badge), one path, all paths, and clearing the review queue. Eight are hidden until earned, a light "curiosity" drive: night owl, early bird, rest-day reader, comeback after a week away, a 60-minute day, ten correct answers in a row, reading both editions, a streak saved by a freeze. The gallery shows locked badges greyed out with a progress bar toward the next tier.

**Lab medals.** Each of the 20 interactive labs has its own medal (single tier, silver, 25 XP, never hidden), with its own icon and name in both editions, for example «نقشه‌بردار CRUSH» / "CRUSH Cartographer" or «ساعت‌ساز mClock» / "Clock Keeper". A medal is earned the first time the reader works hands-on in that lab (changes a control or presses a button; the same `sim:use` event that feeds the tiered *Experimenter* badge). The gallery has a separate "Lab medals" section that shows all 20 locked or earned, and each lab page shows its own medal under the intro line. Saved progress is unaffected: medals are stored in the same `badges` map as other badges, and medals for labs already used are awarded on the next page load.

### Review: flashcards and quiz

- **Flashcards** come only from the book: each chapter's review questions with the answers from the answers appendix (420 cards in the Persian edition; the English edition has none until its answers are translated). The reader reveals the answer and rates themselves *Again / Hard / Knew it*. Each card links back to its source.
- **Glossary quiz**: multiple choice built from the glossary, either "which definition belongs to this term" or "which term does this definition describe". The three wrong options are other glossary definitions or terms, so nothing is invented.
- **Spaced repetition**: a Leitner system with six boxes and intervals of 1, 2, 4, 8, 16 and 32 days. *Knew it* moves a card up one box, *Hard* keeps it in its box at half the interval, *Again* sends it back to box 1 and repeats it later in the same round. Cards of a chapter join the daily queue once the chapter is read, with at most 10 new cards a day. Glossary terms are optional («واژه‌نامه را هم در مرور روزانه بیاور»). «مرور امروز» shows how many cards are due.

### Daily goal, streak, heatmap

The heatmap shows the last 26 weeks (17 on narrow screens) in the style of a GitHub contribution graph. In the Persian edition it runs right to left, so the newest week is on the left, and weeks start on Saturday. Colour shows minutes read; outlined cells mark days on which the goal was met, light blue cells are days saved by a freeze, and today has a ring.

### Learning paths and certificates

The six paths match the home page's "Where to start" cards. When every chapter of a path is marked read, `certificate.html?p=N` shows a printable certificate. The reader types a name, which is stored only in the browser, and prints it or saves it as PDF. Print CSS hides everything else.

## Data and privacy

- Schema: the progress record is now version 2. Version 1 records (from earlier builds) are migrated on load by adding an empty `g` object. The game record has its own version (`g.v`); missing keys are filled with defaults.
- "Export JSON" in the «مطالعه‌ی من» panel includes the game record, and "Import JSON" accepts both versions.
- Day history is trimmed to the last 420 days.
- Nothing is sent anywhere, and the build checks this: `tools/shoot_site.py` aborts every network request and fails if any page tries one.

## Testing

`tools/shoot_site.py` seeds a reading history and checks:

- the dashboard (level, heatmap cells, badge count and unlocked badges, certificate button)
- that the opt-out hides the game UI
- that a flashcard reveals its answer and moves to the next Leitner box when rated
- the level-up toast
- that the quiz marks the right answer
- the certificate with the stored name

It also takes screenshots of each of these.

## References

- Ryan, R. M. and Deci, E. L. (2000). Self-determination theory and the facilitation of intrinsic motivation, social development, and well-being. *American Psychologist* 55(1), 68–78. Overview: <https://selfdeterminationtheory.org/theory/>
- Deci, E. L., Koestner, R. and Ryan, R. M. (1999). A meta-analytic review of experiments examining the effects of extrinsic rewards on intrinsic motivation. *Psychological Bulletin* 125(6), 627–668.
- Chou, Y. (2015). *Actionable Gamification: Beyond Points, Badges, and Leaderboards*. Octalysis framework: <https://octalysisgroup.com/octalysis-framework/>
- Deterding, S., Dixon, D., Khaled, R. and Nacke, L. (2011). From game design elements to gamefulness: defining "gamification". *Proceedings of MindTrek '11*, 9–15.
- Hamari, J., Koivisto, J. and Sarsa, H. (2014). Does gamification work? A literature review of empirical studies on gamification. *Proceedings of HICSS-47*, 3025–3034.
- Roediger, H. L. and Karpicke, J. D. (2006). Test-enhanced learning: taking memory tests improves long-term retention. *Psychological Science* 17(3), 249–255.
- Cepeda, N. J., Pashler, H., Vul, E., Wixted, J. T. and Rohrer, D. (2006). Distributed practice in verbal recall tasks: a review and quantitative synthesis. *Psychological Bulletin* 132(3), 354–380.
- Leitner, S. (1972). *So lernt man lernen*. Herder. (The Leitner box system.)
- Duolingo Help Center, "What is a streak?" (streak and streak freeze): <https://www.duolingo.com/help/what-is-a-streak>
- Khan Academy Help Center, "What are energy points, badges, and avatars?": <https://support.khanacademy.org/hc/en-us/articles/202487710-What-are-energy-points-badges-and-avatars>
- Brignull, H. Deceptive patterns (dark patterns) catalogue: <https://deceptive.design/>
- W3C, WCAG 2.2, Success Criterion 2.3.3 Animation from Interactions: <https://www.w3.org/WAI/WCAG22/Understanding/animation-from-interactions.html>
