# ADR-console-033 — The drafted contract and the question cards read plainly and fit the screen

- **Status:** accepted; D1 amended by ADR-console-082; D3 amended in #1445; D1, D2, D3, D4 and D10 amended in place by #1485 (five fields and five facts)
- **Decided in:** #1079

## Context

The first screenshots of the register cards (ADR-console-029) and the drafted contract (ADR-console-031) showed eight faults:

- The Work column listed 25 to 27 drafted values, each with its own Change button, in the platform's internal terms (`issue-<num>-<slug>`, `.worktrees`, `light lane`, `hint paths`, `rejection paths`), and `the console's starting value` about twenty times.
- Half the Change buttons wrapped onto a line of their own.
- A card's text field had no label or placeholder.
- With the project-id card current, the Enter hint showed on another card, and a detached `[1] choose` line sat under the card list.
- The title sat above the ask on one card and below it on another.
- The default-branch card of a repository with no remote said `Its remote did not say`.
- Asks were set so large that one took five lines at 480 px, and a one-option card carried an added sentence.

The owner's rules for this sprint: everything that needs the owner is a counted question card, the Work column holds only plain lines, the page reads in plain words, and every guessed value stays shown and changeable before the plan is applied. #1079 settles the words and the layout. It changes what ADR-console-029 and ADR-console-031 shipped and keeps their wire, stored rows and field ids.

## Decision

**D1. The main group is a fixed set.** The three main fields `integration-branch`, `lint-command` and `test-command`, then the five fact lines (the project id and issue tracker, the checks a pull request must pass, the platform versions it runs on, the minutes per delivery attempt, the agent knowledge files it holds), in that order, whatever their source. Every other settled field (`release`, `production`) is in the more group. Each main field keeps its own Change control, so at most three are visible before the fold opens; a fact line is `<label>: <value> (<source>)` and has none.

**D2. Plain words.** `contract_draft.py` owns every drafted-value word, and the page shows them verbatim. A draft saved before this wording is read back through `contract_draft.refresh`, which gives it the current labels, option labels and card questions and leaves every value, source and reason as saved.

- A more-group field at its start value reads as one plain sentence with no source suffix, for example `work branches are named after their issue`. At any other value it reads `<plain label>: <value> (<source words>)`.
- Labels are plain everywhere: asks, refusals and lines.
- The counted line is `and 2 more settings at their usual values`, or `and 2 more settings, 1 of them set by you` once the owner changed any. A count of one is singular: `and 1 more setting at its usual value`, `and 1 more setting, set by you`.

**D3. The more group is changed by choosing a value.**

- The counted line is a fold. Its opened list is plain lines, each a quiet button that opens the same change box as Change, so the list adds no Change buttons.
- The fold opens by itself when its entry has a refusal or an open change. Otherwise it keeps its open or closed state across every redraw of the same repository's registration. It starts closed for another repository, and after any draw that showed no fold (a running registration).
- The choice buttons of a change box are drafted-value text too, so they are plain: `production` offers `It declares no production rules`, and `release` offers `It makes no releases`.

**D4. Placeholders come from the view.** `contract_draft.placeholder(field)` gives every text field its words, such as `a branch name`, `the lint command` or `the test command`. The page falls back to `Type your answer` and `Type the new value` only for a frame without one.

**D5. The key hint is the strip, and it sits on its card.**

- The current card is the first open brief, decision or text card. It holds the strip as its last child. When nothing is current, the strip goes on the first waiting card.
- There is one strip however many renders run: the page removes the strip it placed last before placing the next, because brief cards are kept between renders.
- When the current card is a brief inside a closed row, the strip sits in that row's summary line, so it is always visible.
- Folding or unfolding that row moves the strip at once, to the summary line while closed and to the card while open.
- No button carries an Enter key hint any more. This amends ADR-console-002, where the primary named its key.
- A text card's strip says Enter `sends what you typed`, or with options `sends your choice or what you typed`. A card whose one option is the action says Enter `sends this answer`.

**D6. Enter on a current text card**, from outside its field, sends the typed text when there is some. Otherwise it sends a pick when one is complete. Otherwise it focuses the field and sends nothing. Digits do nothing on a card without options.

**D7. One register card layout.** Lead and row alike: the head line with the title `Register <name>`, then the ask, then the options or field, then the hint. Manager question rows keep their layout.

**D8. Readable asks.** The register ask is 1.25rem on wide screens and at most 1rem under 480 px. This amends ADR-console-002's type scale for register asks only, and the lead question of other cards keeps 1.5rem.

**D9. A single option is the action.** A `register` card with exactly one option and no text field shows no option list. Its one action button is labelled with the option and is pre-picked, so Enter sends it. `plan_questions` no longer appends `This is the only thing the adoption can do with this file.`, which amends ADR-console-029 D5. The retry card keeps its why line and its `Retry` option, and the apply card of #1073 has two options and is untouched.

**D10. The integration-branch ask follows the remote count.** The card reads `Which branch does finished work of <name> merge into?` and then one of three tails:

- No remote: `It has no remote, so the console cannot tell: choose a branch or type its name.`
- More than one: `It has N remotes, so the console cannot tell which one to ask: choose a branch or type its name.`
- One: `Its remote did not say: choose a branch or type its name.`

## Consequences

- The stored row, the wire contract, the field ids and the start values are unchanged. Only words, grouping and layout change, so a stored drafting row reads in the new words.
- ADR-console-031's body keeps `the console's starting value` as the name of the start source. The page no longer repeats it.
- #1073 (the apply card) landed first and #1078 (folder trust) is reconciled by whichever of the two lands second: a card of either follows D5 to D9 and adds no layout of its own.
- Playwright measures of the 480 px fit skip in CI, which has no browser, so static CSS cases hold the 1.25rem and 1rem bounds and the no-wrap rule there.
- The screenshots of the new layout are the sprint manager's, taken after merge. This delivery writes none.
- Related: ADR-console-002, ADR-console-029, ADR-console-031.
