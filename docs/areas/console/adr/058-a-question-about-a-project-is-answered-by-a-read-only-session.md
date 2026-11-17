# ADR-console-058 — A question about a project is answered by a read-only session

- **Status:** accepted
- **Decided in:** #1176

## Context

The owner can state a goal and read the desk, but cannot ask the console a plain question about a registered project ("what does production show?", "where is the retry decided?") without starting a sprint. Answering needs a client that reads the project's code and docs and, where the project's contract declares one, runs a read-only production command. That client must never change anything: a question is not a goal (ADR-console-011), and a session that can push, write or reach a tracker would turn a question into a delivery. The owner also wants the answer to come from a smaller model than the managers run on, and wants a session that fails closed rather than one that is only asked to behave.

## Decision

**D1. The route.** `POST /api/project-question` joins `PAGE_WRITES` (ADR-console-008), so it takes the page token and the console's own origin. The body is `{"project_id", "question"}`, the question at most 2000 characters. A question for an unregistered project, an empty or over-long question, a host that cannot run the session, a console that is stopping and a console with no chosen profile are 409 refusals that append nothing; once the asked row is written exactly one answered row follows.

**D2. The session.** The console runs `claude-account run -p --model sonnet --permission-mode dontAsk --setting-sources "" --strict-mcp-config --tools <Read,Grep,Glob[,Bash]> --output-format json --settings <file>` in the project's root, under the profile the console chose (ADR-console-015, ADR-console-023). It runs on Linux only, like a manager. A session that has not answered within 300 s is killed with its process group and recorded `timed_out`.

**D3. The model.** The question session names `sonnet`. The manager keeps its profile's default model and its launches are unchanged, so "smaller than the manager's" is the owner's choice: the comparison is not enforced by any test or check.

**D4. Fail closed.** The settings file's hook entry carries `"onFailure": "block"`, so a hook that errors, fails to start or times out denies the call. The permission layer refuses on its own as well: no user, project or local settings (`--setting-sources ""`), `dontAsk`, an allow list equal to the hook's admissions, a deny list of Edit, Write, NotebookEdit, WebFetch, WebSearch, Agent and the five lifecycle verbs, and `--tools` without Bash when the project has no route. Read-only is enforced by the settings and the hook, never by the prompt.

**D5. The settings file.** It is `project-question-settings/<id>.settings.json` beside the console's store, mode 0600 in a 0700 directory, and is removed after the run. It runs `agent_tools.console.project_question_hook` on every tool, by the console's own interpreter; the hook has no command-table row.

**D6. The hook's admission rule.** The hook admits Read, Grep and Glob, and a Bash command only when it is made of plain words with U+0020 spaces as the only separator and equals one declared read-only argv exactly. Separators are checked before any split, so a bare `just` that would run a project's default recipe, a newline or any metacharacter is refused; a command naming a lifecycle verb is refused whatever the routes hold.

**D7. The routes.** Routes come from `production.read_only.commands` (ADR-guard-009, ADR-guard-011), only those whose `cwd` is the resolved snapshot's `project.root`; the cwd is compared there, never with the registry root, which may be a symlink. With none, the console appends `Production cannot be read for this project: its contract declares no read-only command that runs from its root.` to the answer itself. A contract that cannot be resolved is a `failed` answer naming the resolver's error, and no session starts.

**D8. The answer.** The prompt fixes the shape: Answer, Read, Ran, Could not find out, Question for you. A step that needs money or a credential is put in Question for you, never attempted.

**D9. The log.** Two rows, `project_question.asked` and `project_question.answered`, the second with the outcome `answered`, `failed` or `timed_out` and the answer or the reason. They are not kept kinds, so the schema stays 10 (ADR-console-001) and retention removes them like any other. Nothing reaches a tracker (ADR-console-011).

**D10. The lifecycle.** Admission is refused once the console is stopping. An accepted question is counted open in the same lock section as its asked row, and `close` waits for every open question to record its answer before the log closes. The session runs inside the profile's client-run count, so an account removal waits for it, and a question on a profile being or already removed fails without a session (#1030).

## Consequences

- No page shows a question yet: the route and the log rows exist, and the page that asks and shows the answer is a later change.
- Reads are not confined to the project root: Read, Grep and Glob can read any file the account's user can.
- With no user settings, neither the user-wide lifecycle guard nor the console's session hooks run in the session, so lifecycle verbs are refused by the deny rules, `dontAsk` and the question hook, and the session never shows on the console as a session.
- A declared read-only command whose `cwd` is not the project's root is not offered, so the answer says production cannot be read.
- A console stop cancels a running session and waits for every accepted question before the log closes, recording `the console stopped before the session answered`; a question asked while it stops is refused with `the console is stopping`.
- An account removal can be refused as busy for as long as a question runs under that profile, up to the 300 s cap.
- If a profile's default model were ever `sonnet` or smaller, the question session would not be smaller than the manager's, and nothing would report it.
- Related: ADR-console-001, ADR-console-008, ADR-console-011, ADR-console-015, ADR-console-023, ADR-guard-009, ADR-guard-011.
