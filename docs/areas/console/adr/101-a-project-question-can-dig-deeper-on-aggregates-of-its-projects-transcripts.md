# ADR-console-101 — A project question can dig deeper, on aggregates of its project's transcripts

- **Status:** accepted
- **Decided in:** #1274

## Context

Ask could not answer an analysis question such as where a project's delivery time or tokens go: its session read only the console's records of the project (ADR-console-089), which hold no per-phase or per-agent figures. The delivery transcripts hold them, but they also hold every tool result, so the hook protects them (ADR-console-089 D2). Separately, the light session's Read is not confined to its checkout: its read rules allow every path and the hook denies only the protected roots, so a file of another checkout is readable today.

## Decision

**D1. The console aggregates, the session reads the result.** For a deeper question the console reads the project's own delivery transcripts itself and writes only counts, times and token sums, by script, by phase and by issue, into a `transcripts` part of the records file. Attribution is per record: a record counts only when its own `cwd` maps, through the checkout it belongs to and the registry, to the asked project. The vocabulary of the part is closed: run ids, agent labels, session ids, paths and any message, tool or journal text are read only to attribute and never returned, and issue numbers come from the console's own delivery rows. The read starts at the later of the spend window's first day and the day the project began to hold its checkout, so a checkout taken over within the window never hands over its predecessor's runs, and unreadable transcript roots fail the question rather than report zero runs. The hook gains only the deeper session's checkout root: outside that root and its own records file every read is denied, so the transcript stores stay denied and the session still cannot open a transcript. A symlink the checkout itself holds keeps the existing walk rule, which is the stated limit.

**D2. A deeper question runs on a stronger model with a longer limit.** `--model opus` and 1200 seconds, where a light question keeps `sonnet` and 300 seconds. Everything else about the session is a light one's.

**D3. Dig deeper is a follow-up of the same thread with the same question text and `deep` true.** The thread's earlier answer becomes context. Under the admission lock the console honours it only when the thread's last question is answered, light and of that text, so a confirmation made stale by another tab appends no row and starts no second paid run. The route also accepts `deep` on a new question, which is a new thread; a `deep` that is not a boolean is refused as a bad question.

**D4. Its spend is shown before and after.** Before it starts the page shows an estimate from the project's finished deeper questions, or only the limit and model when there is none. After, the question's own tokens and dollars are read from the spend view's session dimension on every question that is no longer working, and a deeper question reads spend once after its answer is recorded, so the figure does not wait for the next poll.

**D5. The fixed set gains one deeper question.** The question check asks it alone, with its own state and result files, grades it grounded only when its answer cites the transcripts part and quotes a figure of it, and reports it met only after the lead has recorded agreement with a hand analysis of the same figures.

## Consequences

- A deeper answer costs more than a light one, and its estimate is shown before and its spend after.
- A session still cannot open a transcript. What stays limited: a record without a `cwd`, a line that is not one JSON object and an encoding real transcripts do not produce are skipped, and a symlink inside the checkout keeps the existing walk rule.
- Amends ADR-console-058 and ADR-console-089.
- Related: ADR-console-059, ADR-console-062, ADR-console-090, ADR-console-093.
