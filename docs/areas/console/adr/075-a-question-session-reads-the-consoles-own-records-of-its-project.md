# ADR-console-075 — A question session reads the console's own records of its project

- **Status:** accepted
- **Decided in:** #1271

## Context

The owner asked a project what costs the most tokens per issue, and the session answered that nothing records spend. The console does keep it: its spend view reads the transcripts into memory (ADR-console-049), its log holds each project's delivery and activation rows, and its folds hold the sprints and the held checks. The session reaches none of that, because ADR-console-058 admits only Read, Grep, Glob and a few commands, and the console's state is not in the project's folder. ADR-console-058 D6 and ADR-console-065 fixed the session this ADR extends. Handing it the records means handing it a file in the console's own state directory, which also holds the event log, the page token and every other question's records, and ADR-console-058 leaves Read, Grep and Glob unconfined.

## Decision

**D1. The records file.** For each accepted question the console writes one JSON document of that project's records, in the settings directory beside the question's settings file as `<question id>.records.json`, mode 0600 in the 0700 directory, and removes it with the settings file once the session ends. It holds only the asked project's content.

**D2. The hook confines reads of the console's state.** The hook refuses every read of the console's state directory except the question's own records file. It covers every Read path, every word and attached option value of an admitted Bash command, and every entry a Grep or Glob may traverse, with symlinks followed, `..` refused after a wildcard, and a search past `WALK_LIMIT` entries refused. This amends ADR-console-058 D6 and its consequence "Reads are not confined" for the console's own state.

**D3. The contents and their sources.** The document holds the spend view's `project_items` for the project (runs, issues, phases and sprints, in tokens and estimated dollars), the project's retained `delivery.seen` rows and the activation rows of its root, its sprints and held checks from the console's folds (a held check is an inbox item whose reason starts `verify-` or is the review reason), and for each delivery run whether it is `live`. `live` follows the desk's own ownership rule: the run's session is known, not ended, and its repository root maps to the project. The service gathers the records once per accepted question, in its job, after the contract's reach resolves and before the session starts.

**D4. Issue attribution.** Spend is attributed to an issue only from runs whose issues are exactly that issue; a run that named several issues is listed under each issue's `shared_runs` and adds to none of their tokens, so the figures never count a run twice. Every figure comes from the asked project's own columns, because a run id is unique only within a project.

**D5. The prompt names the file.** The prompt tells the session where the file is, what it holds and when to read it, and asks it to name the file under Read when it used it. This amends ADR-console-065 D7.

**D6. Permissions are unchanged.** Read is already admitted, so no allow rule is added; the settings directory also holds the records file. This amends ADR-console-058 D5.

**D7. A failed gathering is a failed answer.** If gathering the records raises, the question is answered once, `failed`, with the reason "the console's records could not be gathered: <Type>: <message>", one stderr line `console: project_question_records_failed <question id> <Type>: <message>`, and no session is started. Nothing new is appended to the log: the question still writes exactly its asked and answered rows.

**D8. Spend is null before the first spend read.** Until the console's first spend poll there is no view, so the document's `spend` is null and the rest is written, and the prompt says so.

**D9. A request key makes a question asked once.** A question request may carry `request_key`, 32 lowercase hex digits (`REQUEST_KEY`); any other value is a bad request. The service asks a key once per project: a key already on a folded question of the project returns that question's id and appends, counts and dispatches nothing, and the same key on another project is a separate question. The check runs under the ingest lock after the unregistered and question checks and before the follow-up check, so a re-sent keyed follow-up is not refused as a follow-up to an unanswered thread. The key is in the asked row's payload only when one is given, the fold keeps it only when it is well formed, and the published view's question carries it (null when absent). The POST answers 204 with no body, so the key is how a client that must judge exactly the question it asked finds it again, and a retry never starts a second paid session. A request without a key behaves and writes exactly as before.

## Considered Options

- A Bash route printing the records: it needs a new admitted argv, for a copy the session's Read reaches anyway.
- An MCP tool: ADR-console-058 D4 rules MCP out.
- A console HTTP read: the session has no tool to reach it.
- Leaving reads unconfined: another question's records, the event log and the page token would be one Glob away.

## Consequences

- Transcripts and checkouts outside the console's state stay readable, as before.
- A project whose root contains the console's state directory has its whole-root searches refused, and so does a project tree holding a symlink into that directory or more than `WALK_LIMIT` entries.
- A hard link made outside the session is not detected, and the session itself cannot make links.
- Spend stays out of the log (ADR-console-049); the file is a copy that lives for one question.
- Related: ADR-console-049, ADR-console-058, ADR-console-059, ADR-console-065.
