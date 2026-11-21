# ADR-console-090 — A question's records hold spend from the first question, are read by part, and a cost answer cites a spend figure

- **Status:** accepted
- **Decided in:** #1357

## Context

The 20 Nov check (#1355) answered the cost question from an old profile. The records' spend was null right after a console restart: the console's spend poll first runs 60 s after start, and the records were observed null at +32 s. The check called the answer met, and the session read only the first 1582 lines of a records file far longer than that. ADR-console-089 fixed the records file, its one-file confinement and the fixed check this ADR amends, and ADR-console-049 fixed how the spend view is read into memory.

## Decision

**D1. Spend is read before the first gathering.** A question job that finds no spend view runs the console's own spend poll once before gathering the records, under the lock that serializes every spend read (`ConsoleService._spend_lock`), and reads nothing when it finds a view once it holds that lock. The records' spend is null only when that read failed, and a read whose every transcript root cannot be listed (a permission error, not an absent directory) is a failure when the console has no spend view yet (`SpendReader.roots_unreadable`), so a cold start never shows 30 zero days; a service that already holds a view keeps it. This amends ADR-console-089 D8, and amends ADR-console-049 D1: the restart read is no longer only the `console-spend` thread's, because a question worker may make it first.

**D2. One file, read by part.** The records stay one file. The prompt gives each section's Read offset and limit, in `question_records.SECTIONS` order (`question_records.section_lines`, `project_question.SECTIONS_TEXT`), and asks the session to name the file with the parts it read, as `<path> (spend)`. This amends ADR-console-089 D5.

**D3. A cost answer quotes a figure of its own records' spend.** The check grounds the cost question only when its Answer quotes at least one figure that occurs in the spend section of its own question's records file, and a Read citation of the records file followed by its parts in parentheses, the spend part among them (`question_check.cites_part`). A figure is a token count or a two-place dollar amount exactly as the records print it, with any thousands separators in the answer. The check reads the spend values from the records file and tests membership (`question_check.spend_figures`, `question_check.spend_figure`); it judges no figure by the shape of its prose, so an issue number or a shell error is no figure only because it is no spend value. The session's instructions tell it to quote each spend figure exactly as the records print it (`project_question.RECORDS_TEXT`). This amends ADR-console-089 D10.

**D3a. The records file of an answered question is kept.** The check runs after the session, so it needs the file: the console keeps `<question id>.records.json` when the outcome is an answer (it is still removed on every other outcome), in the same 0700 directory at mode 0600, and removes a kept file older than 90 days, the question's own retention (`project_question.RECORDS_KEPT_SECONDS`), whenever it writes a records file. The hook's one-file confinement is unchanged: another session still reads no file of the state directory. This amends ADR-console-089 D1.

**D4. Spend stays per project.** The records' spend stays per project by day, run, issue, phase and sprint; there is no per-project session split.

## Considered Options

- One file per section: it widens the hook's one-file confinement (ADR-console-089 D2).
- Polling at start only: a question asked before the first poll still finds nothing, and the start is not where a question's need is known.
- Comparing the answer's figures with the console's view: the records file is gone after the run, the view drifts, and issue totals need the log.

## Consequences

- A question's first gathering after a restart waits for one spend read.
- The check cannot tell a figure the session invented from one it read, only that the answer quotes a value of the spend section and cites the spend part. Two limits are stated and are never findings: a non-spend number in an answer that happens to equal a spend value, and a figure the session reformats (rounded, converted or reworded).
- A kept records file holds the project's deliveries, activations and held checks for up to 90 days in the private state directory.
- Related: ADR-console-049, ADR-console-089.
