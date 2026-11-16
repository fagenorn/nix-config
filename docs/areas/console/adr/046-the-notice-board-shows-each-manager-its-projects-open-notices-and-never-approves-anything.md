# ADR-console-046 — The notice board shows each manager its project's open notices and never approves anything

- **Status:** accepted; amended by ADR-console-051
- **Decided in:** #1118

## Context

ADR-console-044 lets a manager post, list and withdraw notices, but a manager sees them only if it runs `sprint notices`. Several sprints of one project run at once, and each manager must know what the others own before it cuts or starts work. An overlap must reach the owner instead of becoming a conflict or a silent wait.

## Decision

**D1. What a notice is.** A notice is one of claim, heads-up or hand-off, with the bounds of ADR-console-044 D2 (280, 200 and 140 characters, at most 5 open per sprint). Only a manager posts one (ADR-console-044 D9), so every notice names its sprint by its title.

**D2. Where it lives.** A notice lives only in the console's log (ADR-console-044 D8), never in the tracker, a commit or a pull request. The block a manager reads is derived when it is read and stored nowhere.

**D3. How it ends.** A notice ends when it is withdrawn, or when its sprint closes, is stopped or is dropped (ADR-console-044 D6).

**D4. Shown without asking.** The open notices of the project's other sprints reach every manager as one block: in the first prompt of every new manager (a first launch, the owner's retry and a takeover), before the goal; after the messages `sprint inbox` prints; and after the line `sprint status` prints. A wake of the same session carries none: its manager reads the block with `sprint inbox` (ADR-console-016). The block has one line per notice: kind, the sprint's title, age and words, and a claim's what and until. A hand-off addressed to the reader reads "for you". The reader's own notices are left out, and with none the block is absent. In a prompt the block sits between the lead's instruction and `The goal: `, which then starts its own line. A notice may quote `The goal: `, so the goal is the text after the first `The goal: ` not on a line beginning with `- `; every notice line begins with `- ` and holds no line break, because each field's whitespace collapses to one space. A prompt with no block is the one of ADR-console-015.

**D5. How the command reads it.** `sprint inbox` and `sprint status` read the block through `POST /api/notices` under the sprint's secret (ADR-console-044 D3); `/api/inbox` and `/api/sprint-status` are unchanged. `sprint inbox` asks for the notices first, so a refusal reads no message. `sprint status` stays usable without a secret: it shows the block only with the sprint's own secret (`--secret-file`, or the environment's secret beside the environment's id) and never for a withdrawn sprint.

**D6. Never approval.** A notice informs and never grants or denies. The console refuses nothing because of one (ADR-console-044 D7), and the manager's contract says a notice is never approval, never the owner's permission for anything. A manager checks each slice against the other sprints' open claims before cutting or starting it, and an overlap goes to the owner as a question card with `sprint ask` (ADR-console-019) instead of the manager proceeding with that slice.

**D7. No Instruction Budget raise.** The contract is outside the instruction corpus (ADR-console-015).

## Consequences

- The launch prompt grows with the project's open notices: at most 5 per other sprint, each line bounded.
- Ages are read against the reader's clock.
- An overlap costs one question round, and the owner decides it.
- Related: ADR-console-015, ADR-console-016, ADR-console-019, ADR-console-044.
