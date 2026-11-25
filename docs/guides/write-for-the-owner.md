# Write for the owner

The plain-words rule. It governs every word the console shows the owner: the page's own labels and numbers, and the text the sprint managers write that the page shows, which is each status line, card and question.

The owner runs every project from the console page and is not an engineer. He should be able to tell from the page alone what each sprint is doing, what waits on whom, and why. Judge each line by that, not by whether it is accurate to an engineer.

## The rule

1. **The point comes first.** The first sentence says what is happening, or what the owner is asked to do and why it needs him. Detail follows, only if he needs it.
2. **Short sentences, everyday words.** One idea to a sentence. Write the word you would say to a colleague who does not code.
3. **Gloss an internal name the first time it appears.** Say what it is in a few everyday words, or use the everyday word from [the glossary](./owner-words.md) instead. Never use an internal name the glossary does not know without saying what it is.
4. **Numbers and ids come second.** An issue number, a commit id or a pull request number is never the subject of a sentence and never opens one. It goes after the plain statement, in brackets or on a line behind a fold (ADR-console-014).
5. **Say who acts.** A line that waits on someone names who: you, the manager, a check running on GitHub, another sprint. A line never leaves the owner guessing whether the ball is his.
6. **Say what to do, then why.** A question or card that needs the owner names the choice he makes and what each answer leads to. A card that asks him nothing says so.
7. **Name things by what they are.** An account is an account, not `p1`. A sprint is its title, not its identifier. A count says what it counts ("3 of 94 steps done"), never a bare fraction or a grid of squares with no key.
8. **Keep the long text behind a fold.** A fold opens on the thing it is named for. The last exchange between two agents is never what a "report" fold opens on. A line is a sentence or two; test names, command output and commit lists are never on its face.

## Who owns the words

One module owns a surface's words, and a stored row is read back in current words, never rewritten (ADR-console-033). When the wording of a surface improves, the stored data is not migrated: the page reads it through the module that owns the surface.

## Checking a line

Read the line aloud to someone who has never seen the repository. If they cannot say what is happening, what waits on whom and why, the line breaks this rule. [The audit of the live page](./console-page-audit-2026-11-25.md) is the measured starting point; a later change compares its own reading with it.
