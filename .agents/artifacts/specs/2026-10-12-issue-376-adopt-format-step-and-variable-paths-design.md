# Issue 376 — adopt-project formats what it rewrote, and reads variable-joined shell paths

Issue: https://github.com/fagenorn/nix-config/issues/376 (blocks
https://github.com/fagenorn/nix-config/issues/371, follows
https://github.com/fagenorn/nix-config/issues/372). Lineage, cited below as
"issue 345", "issue 350" and "issue 372" with their ledger rows: the specs
`2026-10-10-issue-345-adopt-rewrite-markdown-links-design.md`,
`2026-10-10-issue-350-adopt-path-references-design.md` and
`2026-10-12-issue-372-adopt-moved-file-references-design.md`, whose terms
(token, occurrence, successor, carried form, shape, target, tree, class, policy,
effective answer) are used unchanged.

## Triage

Input: `contract_change=hit` (plan document, evidence record and `plan_id` inputs gain a formatting step and a new policy class; the contract may gain a declared formatter command), `concurrency_or_persistence=doubt` (stored plan document shape changes; no locking change), `open_design_questions=hit` (the issue says the spec chooses the design for both gaps), `criteria_shape=hit` (five acceptance criteria); paths: `python/agent_tools/adopt_references.py`, `adopt_planning.py`, `adopt_apply.py`, `adopt_verify.py`, `adopt_project.py`, `adopt_inspection.py`, `resolve_project.py`, `python/README.md`, `home/common/agent-skills/tests/test_adopt_references.py`, `test_adopt_project.py`, `test_adopt_apply.py`, `test_adopt_verify.py`. Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}`. `ran: full (shadow)`.

## Problem

An operator whose plan is `ready` can still be refused at `apply` by the
target's own lint: a `rewrite` or `extend` answer writes a longer line, the
target's formatter limit is crossed, and the `workflow-verification-commands`
commit gate fails on a file that passed on the base revision. The tool offers no
way out. The adopt commit may not be fixed by hand, and retaining the literal
leaves the code pointing at a path that moved.

The same operator is told nothing about a shell script that builds a path as
`"$root/.claude/notes/x"` or `"${ROOT}/.claude/notes/x"`. The token is no
occurrence today, so the plan asks no question, the tree moves, and the script
points at a directory that no longer exists. Nothing runs it in CI, so nothing
fails.

## Solution

Two additions to the central tool, neither specific to any repository:

1. **A formatting step.** The operator names, per file class, a command of the
   target's contract with `plan --answer reference-format <class> <command-id>`.
   The plan publishes which reference-edited files each command will format.
   `apply` runs each command over exactly those files after the planned
   operations and before the commit gates, proves that nothing else changed, and
   commits once. Without the answer nothing is formatted, as today.
2. **A variable reading.** In a shell-class file, a token that neither existing
   reading makes an occurrence is read a third time as a variable prefix
   (`$name/` or `${name}/`) followed by a path. Such an occurrence in a moved
   file belongs to its own policy, `<tree>:<class>/variable`, with the closed
   answers `rewrite` and `retain` and no recommendation. In a file the plan does
   not move it is an ordinary `path-reference` question.

## Decisions

### The formatting answer (per D1, D2)

`--answer` accepts a fourth id, `reference-format`. It is a declaration, not a
question: no plan opens a `reference-format` entry, `QUESTION_IDS` does not
grow, and a plan with no such answer is exactly the plan of today.

- **Subject**: a file class as issue 372 defines it (`.py`, or `-`), taken from
  the file name of an edited file's target. The `/variable` policy classes below
  are never a subject: formatting is chosen per file, not per reading.
- **Value**: a command id, one key of `bindings.commands` in the contract the
  plan reads. The contract's shape is unchanged; the target declares its
  formatter as an ordinary `commands` entry.

`reference-format` answers are validated after every answer of the other three
ids has validated, in subject order, because the set of edited files depends on
those answers. The refusals are the existing codes:
`adopt.decisions.unmatched_answer` when the subject is the class of no file the
settled answers edit, `adopt.decisions.invalid_answer` when the subject is
answered twice or the value names no `bindings.commands` entry (always, when the
repository has no contract). The answers enter `decisions.answered` as
`{id, subject, value}` like any other, so `stored_answers` and the replay in
`apply` carry them unchanged and `decisions_accepted` lists them.

A command declared this way must accept file paths as trailing arguments,
rewrite those files in place and leave no untracked, unignored file behind. That
is the whole interface. It formats whole files, so a file that was not
format-clean at the base revision may change beyond the edited line; the
operator who does not want that for a class does not name a command for it. Any
`commands` entry is accepted: the row below shows the choice before the plan id
is approved.

### What the plan reports about formatting (per D3)

The plan document and the evidence record gain `reference_formatting`: one row
per class that has at least one file the reference answers edit, sorted by
class.

```json
{"class": ".py", "command": "format", "files": ["tests/test_analyzer.py"]}
```

`files` are the targets of the reference `write-file` operations whose file name
has that class, sorted; `command` is the answered command id or null. A draft
plan therefore already shows which classes a `reference-format` answer could
name. Only files edited by path-reference answers appear: Markdown link
rewrites, the contract, the records and projections are never formatted.

`reference_formatting` is the tenth input of `compute_plan_id`. A plan with no
edited file publishes `[]`. As with issue 372, a plan stored before this change
no longer equals its re-derivation and `apply` refuses it as stale.

`--format human` adds one line per row after the policy lines:
`format <class>: <n> files, command <id or none>`.

### The formatting step in `apply` (per D4, D5)

`apply` runs the step once, after every planned operation has executed and been
checked against its published `after`, and before the commit gates. For each
row with a command, in class order:

1. The command is read from the resolver's `resolve` observation of the
   worktree, the same one the commit gates read, as `bindings.commands[<id>]`.
2. It runs as the `workflow-verification-commands` gate runs a command: the
   entry's `argv` and `cwd`, output captured, no timeout. The row's files are
   appended to `argv` as absolute paths inside the worktree, in the row's order.
3. Each of the row's files is staged.

Then confinement is proved:

- for every path that is not a formatted file, the last operation that names
  it as its target and publishes an `after` still matches that `after` (a moved
  file a later `write-file` edits is judged by the write, as at execution);
- each formatted file is still a regular file at its path.

The existing `worktree-status-matches-operations` gate and `prove_commit_content`
already refuse any change to a path the plan does not name, and
`projections-in-sync` refuses a changed projection, so a formatter cannot widen
the commit.

Failures are refusals with the worktree and branch retained and every commit
gate recorded `not_run`, as for a failed operation:

| Condition | Code | Repair id |
|---|---|---|
| The contract does not resolve in the worktree, the command id has no entry, the command cannot be started, or it exits non-zero | `verification_failed` | `adopt.format.failed` |
| A confinement check fails | `verification_failed` | `adopt.format.unplanned_content` |

The published `after` of a formatted file's `write-file` stays the hash of the
planned, unformatted bytes: it is what the plan can derive and what `apply`
checks before the step. The row in `reference_formatting` is the statement that
the committed bytes of those files are the command's output over them. The
evidence record's bytes are fixed by the plan and written before the step; a
commit that carries the record exists only if the step ran and was confined, so
the record's rows are a true account of the commit.

The commit stays derivable: it is the plan's operations followed by a command
the base revision's contract declares, over files the plan lists, all three
covered by `plan_id` (the base revision, the answer, the rows). `verify` is
unchanged, and `adoption-commit-derived` passes as before.

### The variable reading (per D6, D7)

`adopt_references` gains one closed table, the **shell classes**: `.sh`,
`.bash`, `.zsh`. In a scanned file whose class is one of them, a token that the
plain reading and the pattern reading both leave without an occurrence is read
a third time:

- the **variable prefix** is `$name/` or `${name}/` at the start of the token,
  the slash included, where `name` is a letter or `_` followed by letters,
  digits and `_`;
- after it come `/`-separated segments; the path is the longest leading run of
  segments that are non-empty and hold neither a glob character nor `$`; the
  tail is the rest of the token, verbatim.

So `$root/.claude/notes/x` reads as path `.claude/notes/x`, and
`${ROOT}/.claude/notes/$run/out` as path `.claude/notes` with tail `/$run/out`.
The three occurrence conditions and the successors then apply to that path as
they do to a plain one. A carried form is the variable prefix, the successor and
the tail, and exists only when it is one token and reads back through the
variable reading to that successor.

A variable-joined occurrence offers `rewrite`, when it has a single successor
with a carried form, and always `retain`. It never offers `extend`: the
`quoted` shape adds comma-separated elements, which is not how a shell list is
written (per D10). An ancestor such as `"$root/.claude"`, whose directory
survives the moves, therefore offers `retain` only and stays an open
`path-reference` question until it is answered.

Not read: positional and special parameters (`$1/`), parameter expansions
(`${name:-x}/`, `${name%/*}/`), a variable that is not at the start of the
token, and a second variable before the path. A command substitution needs no
new reading: `(`, `)` and the backtick are token delimiters, so
`"$(git rev-parse --show-toplevel)/.claude/notes/x"` already yields the plain
occurrence `/.claude/notes/x`, and stays one.

The variable is never followed to its definition. The tool does not know
whether `$root` is the repository root or `$HOME`, which is why the reading has
its own policy and no recommendation.

### The variable policy (per D8)

An occurrence records the reading that made it. The **class** of an occurrence
is the file's class, or `<file class>/variable` when the variable reading made
it (`.sh/variable`). A file class never holds `/`, so the two cannot collide,
and the subject `<tree>:<class>` stays derived and partitioning:
`.claude/notes:.sh` for the literal occurrences of the tree's shell scripts and
`.claude/notes:.sh/variable` for their variable-joined ones.

Everything else is issue 372's mechanism without change: the policy answers
`rewrite` and `retain`, the precedence of an occurrence's own answer, a policy value the
occurrence does not offer leaving it open, the open-question rule, the
`reference-policy` refusals, and the `reference_policies` row, whose `class` is
the occurrence class and whose `recommended` is null because the class is in
neither recommendation table. An answer to `<tree>:.sh` never decides a
variable-joined occurrence.

A `rewrite` is computed as for any moved file (issue 372 D1): the token is
replaced on the base bytes by base offsets, and the file is one `write-file` at
its destination after its `git-mv`. `retain` plans no write, so the moved blob
is byte-identical. In a shell-class file the plan does not move, the occurrence
has no policy and opens an ordinary `path-reference` question.

The `path_references` row keeps its twelve members: the literal shows the
variable, and `policy` shows the class for a moved file.

### Documentation

`python/README.md`'s `adopt-project` section gains the `reference-format`
answer, its validation order and refusals, `reference_formatting` as the tenth
`plan_id` input, the formatting step with its two repair ids and the trailing
file-argument interface, the variable reading with its table and limits, and
the `/variable` policy class. The sentences "Variables are not followed" and "a
joined path is not resolved as a whole" are narrowed to say what is still true.

## Test seams

The three seams of issue 350, driven as `python -m agent_tools.adopt_project`
under the recipe's `PYTHONPATH`, plus `verify` on the applied fixture. No new
seam. Fixture commands are small standard-library Python scripts committed in
the fixture and declared in its contract, following `apply_repo`'s
`bindings.commands` prior art in `test_adopt_apply.py`.

- **`adopt_references` functions** (`test_adopt_references.py`): a table for the
  variable reading (both prefixes, a `$` segment ending the path, each unread
  form, a token the plain reading already takes, a non-shell class); carried
  forms and their read-back; the answers offered, never `extend`, for a single
  successor and for an ancestor; the class and policy subject of a variable-joined
  occurrence in a moved and an unmoved file; `policy_summary` rows where
  `<tree>:.sh` and `<tree>:.sh/variable` are answered differently.
- **`plan`** (`test_adopt_project.py`).
  - AC2: a fixture whose moved tree holds a shell script with one literal and
    one `$root/`-joined path into the tree, and whose unmoved shell script holds
    one `${ROOT}/`-joined path. The plan is `draft` with two open
    `reference-policy` questions for the tree (`.sh` and `.sh/variable`, the
    second with `value` null) and one open `path-reference` question for the
    unmoved script. Answering `.sh` alone leaves the variable policy open.
  - AC3: the existing plan tests of issues 345, 350 and 372 pass unchanged
    except the pinned plan-document and evidence-record key sets; the same
    fixture with its shell scripts renamed to a non-shell class yields no
    variable-joined row.
  - AC4: plans that differ only in a `reference-format` answer have different
    ids; `compute_plan_id` over two `reference_formatting` values differing in
    one file yields two ids. An unedited class refuses
    `adopt.decisions.unmatched_answer`; an unknown command id and a repeated
    subject refuse `adopt.decisions.invalid_answer`.
- **`apply` by plan id** (`test_adopt_apply.py`).
  - AC1: the fixture's contract declares `lint` (fails on any tracked `.py`
    line over the fixture's limit) as its verification command and `format`
    (rewraps over-limit lines and strips trailing whitespace in the files it is
    given). A `rewrite` answer lengthens one `.py` line past the limit; a second
    `.py` file carries trailing whitespace and no occurrence. With
    `reference-format .py format`, `apply` commits; `lint` exits zero on an
    export of the adopt commit; the commit's changed paths are exactly the
    planned ones; the second file is byte-identical to its base blob; `verify`
    on the adopt branch reports `adoption-commit-derived` `passed`. The plan of the same answers
    without `reference-format` is refused at
    `adopt.gate.workflow-verification-commands`.
  - AC1 refusals: a `format` command that exits non-zero refuses
    `adopt.format.failed`; one that also rewrites another planned file refuses
    `adopt.format.unplanned_content`; one that rewrites an unplanned tracked
    file, or leaves an untracked one, is refused by the status gate; a moved
    Markdown file with a rewritten link in the same plan does not trip the
    confinement proof. Each refusal retains the worktree and leaves no
    commit on the target branch.
  - AC2: with the variable policy answered `rewrite`, the script at its
    destination holds `$root/<successor>` and no old path; with `retain`, its
    blob at the destination equals its base blob.
  - AC4: the evidence record's `decisions_accepted` holds the `reference-format`
    and `reference-policy` answers, and its `reference_formatting`,
    `reference_policies` and `path_references` equal the plan's.
- AC5 is `just agent-workflow-tests`.

## Out of scope

- Any Arcwave-specific case, and running the adoption on Arcwave
  (https://github.com/fagenorn/nix-config/issues/371).
- A contract member that declares formatters, a line limit read by the tool,
  plan-time overflow detection, and any wrapping the tool performs itself.
- Formatting a file no path-reference answer edits: Markdown link rewrites, the
  contract, the two records, projections and untouched files.
- Following a variable to its definition, parameter expansions, positional
  parameters, and a `$var/` path in a file outside the three shell classes
  (YAML, Makefiles, JavaScript template strings, extensionless scripts by
  shebang).
- A recommendation for a `/variable` policy, `extend` for a variable-joined
  occurrence, the `quoted` shape of existing literal occurrences in shell
  files, a new member on the
  `path_references` row, and widening the plain or pattern readings.
- Paths relative to a moved script's own directory, and a new gate, operation
  kind or `verify` check.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The overflow is answered by running a formatter in `apply`, not by a plan-time question about a line limit | The issue's first acceptance criterion needs the rewrite made, the target's lint green on the adopt commit and formatting confined to rewritten files; only the target's formatter knows its own limit and how it wraps; issue 350 D6 forbids a per-language parser in the package | Detecting the overflow against a declared limit and asking: the only answers would be `retain`, which leaves the code broken, or a rewrite that still fails the lint |
| D2 | The formatter is named by an optional answer, `reference-format <class> <command-id>`, whose value is a `bindings.commands` key; the contract schema does not change and no question opens | The bootstrap invariant that every executable invocation is a `commands` entry addressed by id; issue 350 D7 (answers are `{id, subject, value}`, replayed from the stored plan, so `plan_id` authenticates them); formatters are per language, hence the class subject; the smaller, reversible choice that keeps `resolve_project` untouched | A `workflow` contract member mapping classes to commands, which changes the contract schema and every consumer for one adoption-time need; a separate `plan` flag, which needs a second replay path; an opening question, which would turn every existing ready plan with an edit into a draft |
| D3 | `reference_formatting` lists every class with an edited file, `command` null when undeclared, and is the tenth `plan_id` input and an evidence-record member | The issue's "covered by the plan id and listed in the evidence record"; issue 350 D8 (each published summary is an id input); a null row is how a draft plan shows the operator which classes can be given a formatter | Rows only for answered classes, which hides the option; leaving the rows out of the id because the answers imply them, which lets the file-selection rule drift under one id |
| D4 | The step runs once in `apply`, after the checked operations and before the gates; each write keeps its planned `after`; confinement is proved by re-checking every other published `after` and by the existing status gate and commit-content proof | The formatted bytes are not known at plan time, and the plan reads only base blobs; `prove_commit_content` already holds the commit to the planned paths, and a formatted file is one of them; the gates must judge the formatted tree, since the verification commands are the lint | Formatting at plan time on temporary copies, where the formatter cannot find the target's configuration; publishing a null `after` for formatted files, which drops the pre-format check; a second commit, which breaks the atomic adopt commit |
| D5 | A formatter failure or a confinement failure is a `verification_failed` refusal (`adopt.format.failed`, `adopt.format.unplanned_content`) with the worktree retained, not a commit gate | The bar's fail loud and truthful terminal states; the step mutates the worktree, and `COMMIT_GATES` are read-only verdicts that all run even after one fails | A new commit gate, which would mix a mutation into the gate list and still run the later gates on a half-formatted tree |
| D6 | The variable reading covers `$name/` and `${name}/` only, is tried last, and ends the path at a segment holding `$`; command substitution keeps its existing plain reading | The issue's two examples; trying it last keeps every issue 350 and 372 occurrence byte-identical (the route issue 372 D6 took for patterns); the delimiters already split `$(...)/path` into a plain root-anchored occurrence | Reading parameter expansions, which needs a shell parser; treating `$(...)` as a variable prefix, which would change an occurrence that exists today |
| D7 | Shell-like means the closed suffix table `.sh`, `.bash`, `.zsh`; the reading applies to moved and unmoved files of those classes. This reverses issue 372's out-of-scope clause on variables for these three classes only | The issue's "shell-like files"; issue 372 D2's suffix classes are the tool's only notion of a file kind; an unmoved script with the same path breaks the same way, and issue 372 gives unmoved files per-occurrence questions | Shebang sniffing for extensionless scripts and reading every file class, both of which widen the scanned grammar past what the issue names; moved files only, which leaves the same silent breakage outside the tree |
| D8 | Variable-joined occurrences of a moved file form their own policy, class `<file class>/variable`, answers `rewrite` and `retain`, recommendation null, and no row member is added | The issue's "as a file class under the policy-answer mechanism with closed answers, default not to rewrite silently"; issue 372 D3 (a recommendation is never applied) and D4; the variable may be `$HOME`, so a `<tree>:.sh` answer of `rewrite` must not sweep these in; `/` cannot occur in a file class | Folding them into `<tree>:.sh`, which rewrites them on an answer given for literals; recommending `rewrite`, which presumes the variable is the repository root |
| D9 | Grill: confinement judges each unformatted path by the last operation that publishes an `after` for it; the declared command formats whole files and must leave no untracked residue, and both are stated as its interface | A moved file that a later `write-file` edits no longer matches its `git-mv` `after` once the write is staged, so re-checking every operation would refuse plans that apply today; the status gate reads untracked files and now runs after the formatter; the bar's "known limitations belong in docs" | Re-checking every published `after`, which fails on every edited moved file; confining the formatter to the edited lines, which no formatter interface offers |
| D10 | Grill: a variable-joined occurrence never offers `extend` | `extend`'s `quoted` shape inserts `, "<form>"`, and a shell array or word list is space-separated, so the edit would corrupt the script; the issue asks for `rewrite` and `retain` | Offering `extend` as for any occurrence, which carries an existing literal-shape weakness into a new reading; fixing the shape for shell files here, which widens the literal rules the issue puts out of scope |
| D11 | Plan: `reference-format` answers are set aside in the sorted pass and validated after it, before any candidate is mutated, in `(subject, value)` order: a repeated subject refuses `invalid_answer`, then a class no settled answer edits `unmatched_answer`, then an undeclared command `invalid_answer` | The spec's "validated after every answer of the other three ids"; `reference-format` sorts before `reference-policy`, so the existing pass would check it first; `apply_answers`' promise that a refusal mutates nothing | Validating it in the sorted pass, which checks it before the policy answers whose edits it depends on |
| D12 | Plan: the formatting step takes its own `resolve` observation of the worktree, only when a row names a command; the commit gates keep the one `GateRun` takes after the step. This refines the spec's "the same one the commit gates read" to "the same kind of observation" | D4 (the gates judge the formatted tree); `projections-in-sync` must see a projection a formatter changed; a plan with no `reference-format` answer must run exactly as today | Building `GateRun` before the step and sharing its observation, which lets the gates judge the projections of an unformatted tree |
| D13 | Plan: an occurrence records the variable reading as `Occurrence.variable: bool = False`, and `occurrence_class` is a derived property that `policy`, `policy_summary` and `reference_questions` read | D8 ("an occurrence records the reading that made it"); only the variable reading changes a class; existing positional constructions stay valid | A three-valued `reading` member, which changes every pattern occurrence for no consumer |
| D14 | Plan: existing tests change only where they pin the document's member list, the plan-id formula (`documented_plan_id` and the four `compute_plan_id` call sites gain the tenth argument) or the hand-rebuilt evidence-record bytes; `compute_plan_id`'s tenth parameter has no default | AC3 ("existing tests stay green"), read with the spec's AC3 seam, which already exempts the pinned key sets; the bar's single source for the id formula | A default for `reference_formatting`, which would let a caller drop an id input silently |
| D15 | Plan: the AC1 fixture's lint and formatter are standard-library scripts that walk `*.py` from their working directory, and one formatter script with `--fail` and `--touch PATH` options backs every refusal command | The lint must run both in the worktree gate and on a `git archive` export, which has no `.git` for `git ls-files`; one script keeps the fixture small (the spec's test seams) | `git ls-files` in the lint, which fails on the export; one script per refusal, which multiplies fixture text |
| D16 | Phase-5 review: until the formatting step exists (Task 3's commit), `apply` refuses `adopt.format.failed`, fail-closed, every plan whose `reference_formatting` names a command, at the step's place; Task 4 replaces the refusal with the step | Codex plan review (blocking): an intermediate head that accepts and publishes a formatting answer it does not execute writes false evidence when the lint already passes; the bar bans committed half-wired paths | Folding Tasks 3 and 4 into one task, which doubles the largest review unit; leaving the gap and relying on the verification gate, which does not fail when the lint passes |
| D17 | Phase-5 review: the confinement proof also requires a non-formatted path whose last operation publishes a `git-object:` hash to hash to it on disk (`git hash-object`), not only in the index | Codex plan review (blocking): `operation_result_matches` answers a `git-object:` hash from the index, so an unstaged formatter edit of a move-only destination passed confinement and reached the gates, against D5's refusal with every gate `not_run` | Leaving it to the `worktree-status-matches-operations` gate, which runs the gates first and reports a different repair id; changing `operation_result_matches` itself, whose index reading the operation checks rely on |
