# The guard refuses the raise label (#294)

Slice S2 of #291. Program spec:
`.agents/artifacts/specs/2026-10-07-issue-291-skill-best-practices-design.md`
("The gate", the "label is a human signal" decision, program row D2). Blocker
#292 (the `Instruction Budget` gate) is merged.

## Problem

The `Instruction Budget` check lets a PR raise an instruction ceiling, or edit
the gate itself, only when the PR carries the `instruction-budget-raise` label.
The label stands for the user's decision. Nothing stops an agent from adding
it to its own PR with one `gh pr edit --add-label`, and a well-meaning agent
blocked by the gate is the agent most likely to do this. That would turn the
user's check into the agent's own. The user wants this mistake caught before
the command runs. They also want the rule written where every agent reads it,
and its limits written down, so that no one mistakes the guard for enforcement.

## Solution

1. **Guard rule.** The Claude `PreToolUse` lifecycle guard refuses
   `gh pr edit` and `gh issue edit` when they add the raise label. Every
   other label edit passes unexamined.
2. **Frame sentence.** The global guidance frame (`AGENTS.md`, installed for
   both hosts) gains one sentence: only the user applies the
   `instruction-budget-raise` label.
3. **Limits note.** The repository `CLAUDE.md` guard bullet records the rule
   and what it cannot see.
4. **Budget offset.** One redundant sentence is cut from the corpus, so the
   PR passes the gate with no label and no change to `instruction-load.json`
   (D4).

## Decisions

### The label operation (guard)

A fifth guarded operation, `label`, sits beside the four existing ones. It
reuses the same splitter, tokeniser and command-position logic. It differs
from them in one way: it is **mention-gated** (D1). The operation is
considered only in a segment that mentions the raise label. A mention is a
case-insensitive substring of any token value, or of the raw segment text
when the segment cannot be tokenised. A segment that does not mention the
label is never adjudicated for this rule, whatever `gh pr edit` it contains.
Because the existing four verbs are left alone, this keeps
`xargs gh pr edit 1 --add-label bug` and
`sh -c 'gh pr edit 1 --add-label bug'` passing, as they do today.

Within a segment that does mention the label:

- **Fail closed where the guard cannot see.** The segment is refused when the
  command cannot be split, when the segment cannot be tokenised, or when it
  hands shell source to an evaluator (`eval`, `sh -c`, …). These are the same
  three cases that already refuse the other verbs. In these cases the verb
  itself does not need to be found: a mention is enough.
- **A `gh` invocation adding the label.** A `gh` invocation is a word whose
  basename is `gh`, together with every later word of the command's
  tokenised segments, operator tokens skipped (D9, D10). Its label values are the token after each `--add-label` and the
  remainder of each `--add-label=<v>`. It adds the label when any value
  contains the raise label as a case-insensitive substring. The subcommand
  is not parsed (D1). `gh pr -R owner/repo edit …` is valid gh, and so is an
  alias, so matching only the sequence `gh pr edit` would miss them. Only
  `gh pr edit` and `gh issue edit` accept `--add-label`.
  - An invocation that adds the label is refused wherever its `gh` word
    sits. That includes a command position, and a non-command position such
    as an argument to `xargs`, `timeout` or `nice`, which may run it.
  - An invocation that adds no raise label passes. The label in `--body` or
    `--title` text, or in `--remove-label` (D3), is not an add.
  - The substring test covers comma lists (`bug,instruction-budget-raise`),
    padded items (`"bug, instruction-budget-raise"`), CSV-quoted items and
    repeated flags, with no separate parsing. It over-blocks only label
    names that contain the raise label, and no such label exists.
- **A mention alone passes** in a segment that can be parsed. Examples are a
  commit message given with `-m`, or `echo` of a quoted command line.

Command positions are the ones the guard already recognises: after
`(`, `{`, `` ` ``, `$(` and `case` arms, after `!`, `time`, `then` and `do`, and
behind `command`, `env` (with options or assignments), `sudo` and leading
assignments. Token values are unquoted and unescaped, so `"gh" pr edit`,
`gh  pr\tedit` and `instruction\-budget\-raise` all match. A quoted
single-token mention, a heredoc body or a comment is not a command and
passes, as it does for every other verb.

The rule is **global and context-free**, like branch deletion. It runs in
every repository, needs no `cwd`, no repository detection and no forge
lookup, and is judged before the `Context` is built. A label name is not
repository-scoped (D2).

**Block message.** Every refusal of this operation reads
`lifecycle guard: unsafe instruction-budget-raise label edit: <reason>`. The
operation's display name carries the rule, so the fail-closed refusals name it
too. When the guard can see that the label is added, the reason is
`only the user applies this label (Instruction Budget raise control)`. The
three fail-closed cases keep their existing reasons. The exit status is 2, as
for every other refusal.

The label name is one module constant in the guard. It is not a policy key:
the policy holds only Nix-owned values. The guard's policy schema, store
wrapper, hook registration and the 22-entry allow surface stay unchanged.

### Frame sentence (D4)

`AGENTS.md` gains one paragraph after its last one, the single sentence
"Only the user applies the `instruction-budget-raise` label." The frame
loads in every session on both hosts, so this one home reaches every skill's
runner. Skills do not restate it (D3).

### Limits note

The repository `CLAUDE.md` guard bullet stops counting "four lifecycle verbs"
as the hook's whole remit, and gains one sentence. It says the hook
also refuses an agent adding `instruction-budget-raise` through
`gh pr edit`/`gh issue edit --add-label` (#294), and that this catches
mistakes and is not enforcement: Codex has no hook, and `gh api`, GraphQL and
`curl` are outside the guard. The protection that holds is the required check
plus the user seeing the label on the PR
(`.agents/knowledge/rejections/ungated-agent-merges.md`).

### Budget offset (D4)

The corpus measures exactly its ceiling (549810 bytes), so any net growth
fails the gate. The frame sentence and its blank line add 61 bytes.
`doc-grounded-questions/REFERENCE.md` loses the sentence "This does two
things at once: shows the homework, and frames the question precisely around
what's actually unknown." (116 bytes with its trailing space). That sentence
restates `doc-grounded-questions/SKILL.md`, which says "That shows the
homework and frames the question precisely around what's unknown." The skill
file always loads before its reference, so the cut is behavior-neutral. The
worked example and its "When the docs fully answer it:" line stay. Net is
−55 bytes.

The cut lowers only conditional bytes of the profiles that list that
reference. Their ceilings stay well inside the 5% tightness band, so
`instruction-load.json` is not edited and `tighten` is not run, because it
would lower unrelated profile ceilings. The gate files are untouched.

## Test seams

- **The installed hook executable**, invoked through
  `tests/test_claude_permission_guard.py`'s `run_guard`. It reads the
  registered command from the generated settings and passes a JSON payload
  on stdin. This is the existing seam, and only it is used. New methods go in
  the adversarial-table section.
  - *Blocks* (exit 2, stderr names `instruction-budget-raise`). The plain
    `gh pr edit 1 --add-label instruction-budget-raise` and the `gh issue
    edit` form. `--add-label=…`. A comma list, a padded list and a quoted
    value. Upper case. Repeated `--add-label`. An escaped value. `"gh" pr
    edit`, a double space and a tab. A subshell, a group, `$(…)`, backticks,
    `&&` chaining and a `then` arm. `command`, `env -i`, `env FOO=bar`,
    `sudo -u anis` and a leading `GH_REPO=…` assignment.
    `gh pr -R fagenorn/nix-config edit 1 …`, `gh issue --repo=a/b edit 1 …`
    and an absolute-path `gh`. `xargs` and
    `timeout` positions. `eval` and `sh -c`. An unterminated quote. A
    non-fagenorn repository, and a payload with no `cwd`, to show the rule
    is global.
  - *Passes* (exit 0). `gh pr edit 1 --add-label bug` and
    `gh issue edit 23 34 --add-label "bug,help wanted"`.
    `--remove-label instruction-budget-raise`. The label only in `--body`.
    `xargs gh pr edit 1 --add-label bug` and
    `sh -c 'gh pr edit 1 --add-label bug'`, which are not adjudicated. A
    quoted `echo "gh pr edit 1 --add-label instruction-budget-raise"` and a
    heredoc body.
  - Every existing case stays green, unchanged.
- **The gate**, run as `just agent-instruction-budget` against `origin/main`
  without `--raise-label`. It must pass.
- **`just build`**, which builds the guard wrapper and the settings the test
  reads, and `just agent-workflow-tests`.

No test pins the `AGENTS.md` sentence. That would be a pinned English phrase
(`docs/standards/agent-helpers.md` rule 6).

## Acceptance

| Issue criterion | Met by | Measured by |
|-----------------|--------|-------------|
| (1) [code] The guard blocks the label verbs in quoted, wrapped and spaced spellings, and passes other labels through | The label operation | New block and pass rows in the adversarial table of `tests/test_claude_permission_guard.py`, run against the built settings (`just build`, then `CLAUDE_SETTINGS_PATH` set to the `-claude-code-settings.json` store path), not by `just agent-workflow-tests` (D6) |
| (2) [code] `just build` succeeds | Unchanged Nix wiring, and the guard still loads | `Nix Eval` CI, and `just build` locally |

The demo comes from the first rows. `gh pr edit 1 --add-label
instruction-budget-raise` exits 2 with
`unsafe instruction-budget-raise label edit: only the user applies this label …`.
`gh pr edit 1 --add-label bug` exits 0. The PR also passes the
`Instruction Budget` check unlabelled (D4).

## Out of scope

- `gh api`, GraphQL, `curl` or any other HTTP path that adds a label. Skills
  use `gh api` legitimately (program D2). These are documented as limits.
- Codex enforcement. Codex has no `PreToolUse` hook.
- `--add-label` values the guard cannot see, such as `"$LABEL"` or
  `instruction-budget-$X`. A mistake-catcher does not chase obfuscation.
- `gh issue create --label`, which labels an issue and not a PR, and
  `gh pr create --label`, which pr-create's exact grammar already refuses.
- Removing the label (D3).
- The existing four verbs' blind spot that the grill found. They match the
  fixed sequences `gh pr merge` and `gh pr create`, so the valid spellings
  `gh pr -R <repo> merge …` and `gh pr --repo=<repo> create …` are never
  adjudicated. Closing that gap is a follow-up issue (D5).
- Restating the rule in skills, rewriting skills, and any edit to the gate's
  files or to `instruction-load.json`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The label rule is a fifth guard operation, mention-gated. It is considered only in a segment that mentions the raise label (case-insensitive). Within such a segment it fails closed where the guard cannot see. It refuses any `gh` invocation (basename `gh`, in any position) with an `--add-label` value that contains the label, and it does not parse the subcommand | Issue: other labels pass, and the guard must not adjudicate every `gh pr edit`. CLAUDE.md: refuse what the tokeniser cannot vouch for. Grill: `gh pr -R x edit` is valid gh | Adding `gh pr edit`/`gh issue edit` to `GUARDED_TOKEN_LITERALS`: `gh pr edit … bug` under `xargs`/`sh -c`, or unparseable, would start blocking, and `-R` placement would evade it. Exact comma-split matching: misses CSV quoting and padding for no gain |
| D2 | The rule is global and context-free, like branch deletion. The label name is a guard constant, not a policy key | Precedent `validate_branch_delete`. The policy holds only Nix-owned values. YAGNI | Scoping to authorized owners: needs repo detection for no benefit. Making it a policy key: touches Nix wiring and the policy schema for one fixed string |
| D3 | Only adding is refused. `--remove-label` passes. The rule lives in `AGENTS.md` only, not in skills | Removal never raises (program "The gate", step 4). The frame loads on both hosts in every session (the-bar DRY). The issue names `AGENTS.md` only | Refusing removal: blocks the safe direction. Restating it in skills (program S2 row): duplicate homes, and corpus bytes the budget does not have |
| D4 | Budget: the frame sentence (+61 B) is offset by cutting the REFERENCE.md sentence that restates doc-grounded-questions SKILL.md (−116 B). Net −55 B. No `instruction-load.json` edit and no `tighten` run | Corpus = ceiling 549810 at Phase 0. The label is the user's (this rule). Tightness band 5%. The frame is user-authored | Editing the user's own frame wording to make room: a user-preference change. Raising the ceiling: needs the human label. `tighten`: lowers unrelated profile ceilings |
| D5 | This issue leaves the existing verbs' `gh pr -R <repo> merge`/`create` blind spot open and records it for a follow-up issue | Issue scope is the label rule. The merge guard is the ungated-merges floor (`rejections/ungated-agent-merges.md`), and changing its grammar deserves its own review | Widening merge/create detection here: it changes four validators' reach in a slice sized for one rule |
| D6 | The guard's new rows run against the built settings (`just build`, then `CLAUDE_SETTINGS_PATH` = the `-claude-code-settings.json` store path), not through `just agent-workflow-tests`; this corrects the Acceptance table's "run by `just agent-workflow-tests`", and the recipe is not changed | The recipe does not list `tests/test_claude_permission_guard.py`; the test runs the installed store hook, and CI's advisory suite is source-only (CLAUDE.md) | Adding the guard test to `agent-workflow-tests`: the source-only suite would then need a Nix build |
| D7 | `main()` refuses the first `label` finding before adjudicating any other finding, so the label refusal never waits on a repository-bound verb or a `Context` | Spec: the rule is judged before the `Context` is built; branch-deletion precedent of a context-free rule | In-order adjudication: a preceding push in the same command would build `Context`, need a `cwd`, and report a push reason instead |
| D8 | Each refused label row asserts its full expected message (direct-add, evaluator, or parse reason), not just the prefix | Phase-5 Codex plan review PR294-02: a prefix-only assertion passes if every case returned the direct-add reason, hiding the spec's distinct fail-closed reasons | Prefix-only assertions plus one plain-command reason check (the plan's first draft) |
| D9 | Amends D1's word boundary: a `gh` invocation's words now run to the end of its segment, skipping operator tokens, so a label added after a `$(…)`/backtick substitution is caught | Final-review correctness finding CR-294-01 | Ending words at the next operator (the original wording of the rule in Design), which let `gh pr edit $(…) --add-label instruction-budget-raise` pass |
| D10 | Amends D9: once the command's tokens mention the raise label, the `gh` invocation check runs over every tokenised segment of the command at once, so a separator inside a substitution (`gh pr edit $(gh pr view … \| jq …) --add-label …`) cannot split the `gh` word from its label. A later program's own `--add-label` naming the label after an unrelated `gh` call is refused too, which fails closed | PR review correctness finding PR-294-R1 (ship-issue Phase 5; distinct from the parked SDD finding CR-294-02) | Tracking substitution depth in the segment splitter, which reworks the splitter every other verb relies on |
