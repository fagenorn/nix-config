# Issue 353 — `sdd-gate`: one helper call per task boundary, and rendered dispatch briefs

Issue: https://github.com/fagenorn/nix-config/issues/353

## Problem

An sdd owner runs on the most expensive model, and between a task's review and
the next dispatch it does two things by hand.

It runs the per-task gate as separate calls: release the returned worker, build
the review package, validate the producer report, check the package against the
artifact budget, compare the four metrics, mark progress, extract the next task
brief, register the next worker. Owners on a consumer project took 9–14 turns
per task; two that wrote themselves a chaining script took 7.5.

It also types every implementer and reviewer prompt out in full from the
template: a median of 8.0k characters per implementer dispatch and 7.8k per task
review, almost all of it text that is the same for every task. Each prompt then
stays in the owner's context for the rest of the run.

The task body already travels the other way: `task-brief` writes it to a file in
the plan's workspace and the prompt names the path.

## Solution

A new command, `sdd-gate`, does both jobs. The owner calls it once at each of
the two boundaries a task has:

- `sdd-gate review`, after the implementer reports DONE: releases the worker,
  builds and gates the task's review package, and writes the complete reviewer
  brief to a file.
- `sdd-gate next`, after a clean review (and before the first task): records the
  completed task, marks progress, runs the cumulative delivery gate, extracts the
  next task brief, registers the next worker, and writes the complete implementer
  brief to a file.

Each call runs its steps in a fixed order, stops at the first step that fails
and names it. The owner's `Agent` prompt becomes one sentence naming the file.
The brief is the template's own text with its placeholders filled, so the
assembler changes and the template stays the single source of the wording.

## Terms

- **Dispatch brief**: the file `sdd-gate` renders for one dispatch. The existing
  **task brief** (`task-N-brief.md`, the plan member `task-brief` copies) keeps
  its name and is referenced from the dispatch brief.
- **Standards document**: a file from the standards layers. The word "shard"
  alone keeps meaning a review-package shard, as in the sdd skill today.
- **Lifecycle identity**: the caller's `ledger_repo_root`, `run_id` and
  `action_id`, as the sdd skill defines it.
- **Ledger**: the plan workspace's `progress.md`.

## Decisions

### Command home and shape (D1, D2)

`sdd-gate` is one row in the agent-tools command table and a thin command
module, `agent_tools.sdd_gate`, that parses argv, calls importable functions,
prints one JSON object and maps the outcome to an exit code. Step sequencing and
ledger handling are functions of that module; template extraction, placeholder
filling and standards selection live in a second module, `agent_tools.sdd_brief`,
because rendering has its own reason to change.

It reaches its collaborators the way the package already does:

- the `review-package` producer as a packaged sibling, through
  `agent_tools.siblings.sibling_argv`, with its stdout captured unchanged;
- `artifact-budget` through `agent_tools.review_budget`'s authority (`check` and
  `validate_report`), which runs the external command by name on `PATH`;
- `workflow-state`, `sdd-workspace` and `task-brief` by name on `PATH`.

`task-brief` is not on `PATH` today. It is installed as `~/.agents/bin/task-brief`
beside `sdd-workspace`, from the same source file, unchanged. Its own lookup of
`sdd-workspace` next to itself keeps working in both locations.

The skill directory is not discoverable from the package without a `__file__`
lookup, so both subcommands take a required `--skill-dir`: the directory of the
`SKILL.md` the owner loaded. The two templates are read from it. An owner running
a working-tree copy of the skill therefore renders that copy's templates.

### Invocation

```
sdd-gate review PLAN_FILE --skill-dir DIR --task N
    [--standards PATH]...
    [--repo-root R --run-id I --action-id A --worker-id W]

sdd-gate next PLAN_FILE --skill-dir DIR
    [--completed N [--parked K]] [--task M [--context-stdin]]
    [--delivery-base SHA] [--standards PATH]...
    [--repo-root R --run-id I --action-id A]
```

- `--standards` is repeatable: one per entry of the owner's retained
  `bindings.paths.standards`. The command never resolves the project itself.
- The lifecycle flags are all present or all absent. `review` under a lifecycle
  identity requires `--worker-id`; `--worker-id` without the identity is an
  invalid invocation.
- `next` needs at least one of `--completed` and `--task`. `--parked` and
  `--context-stdin` are valid only with the flag they follow. `--context-stdin`
  reads the owner's context text from stdin as UTF-8, the quoted-heredoc form
  the lifecycle calls already use, so no prose passes through shell quoting.
- `--delivery-base` is required when the ledger holds no delivery base and must
  be a full 40-character SHA. When the ledger holds one, the flag may be omitted;
  a different value is refused.

The command runs from the worktree. Every Git read uses the current checkout.

### What the ledger holds (D3)

The command keeps no state file. The two SHAs it needs across calls live in the
ledger, which is already the record the owner trusts after compaction and which
`workflow-state resume-pack` already parses. It appends these lines, one write
each:

| Line | Written by | When |
|---|---|---|
| `Delivery base: <sha40>` | `next` | once, on the first call that passes `--delivery-base` |
| `Task <N>: dispatched (base <sha40>)` | `next --task N` | once per task; a later `next --task N` reuses the recorded base |
| `Task <N>: complete (commits <base7>..<head7>, review clean)` or `…, <K> parked)` | `next --completed N` | once; skipped when the task already has a `complete` line |
| `Delivery gate: <base40>..<head40> root_bytes=<n> total_bytes=<n> file_count=<n> largest_member_bytes=<n>` | `next` | after each passing cumulative gate |

`review --task N` and `next --completed N` read the task base from the task's
`dispatched` line. A task with none is refused: every implementer dispatch,
mechanic dispatches included, starts with `next --task N`. The `complete` line
keeps the format the sdd skill defines, so `resume-pack`'s reading of the ledger
is unchanged; the three new line shapes do not start a `complete` or `fix round`
entry.

The owner still creates the ledger and its header in Setup. Every call first
checks that `progress.md` exists in the workspace `sdd-workspace PLAN_FILE`
prints and that its first line is the sdd header naming a path that resolves to
`PLAN_FILE` (absolute, or relative to the checkout's top level). Anything else is
refused at step `ledger`.

### `sdd-gate review`: steps in order

| # | Step name | What it does | Refusal |
|---|---|---|---|
| 1 | `ledger` | workspace, header check, read the task base | missing or foreign ledger, no `dispatched` line |
| 2 | `release-worker` | `workflow-state release-worker --repo-root R --run-id I --worker-id W --event returned` | non-zero exit |
| 3 | `review-package` | pin head to the full `git rev-parse HEAD`, then build the package with the producer on `PLAN_FILE <base> <head>`, or reuse an existing one (below) | producer exit other than 0 or 3; an existing package that cannot be reused |
| 4 | `validate-report` | pass the report bytes (the producer's stdout, or the saved report of a reused package) through producer-boundary report validation; require state `complete` | validation fails; state is `decompose_required` or `failed`; state disagrees with the producer's exit |
| 5 | `budget-check` | independent `review-package` budget check on the report's root | checker error, or status `over_budget` |
| 6 | `metrics-match` | compare all four metrics of the check with the report's | any difference |
| 7 | `render-brief` | render the reviewer brief and write it | see Rendering |

Without a lifecycle identity step 2 is skipped. A repeated release with the same
event is already a no-op in `workflow-state`, so re-running `review` after a
later step failed is safe.

Steps 3–6 are the sdd skill's review-package gate with its three exits
unchanged: all four passing permits dispatch; a validated `decompose_required`
report is the `decompose_required` exit; everything else is `failed`.

**Reusing a package (D10).** The producer refuses to publish over an existing
root (observed: a second run for the same range exits 2 with a `failed` report).
The same range does recur: a repeated call, and the first task's review range
when its base is the delivery base, which the cumulative gate then asks for
again. So after each build that validates, the command saves the validated
report bytes beside the package as `<root stem>.report.json`. When the default
root for the range (`review-<base7>..<head7>.json` in the workspace) already
exists, step 3 does not run the producer. It applies the skill's
existing-package rule instead: the manifest's `range.base` and `range.head` must
equal the intended full SHAs, and the saved report must exist and name that
root. Steps 4–6 then run on the saved report exactly as on a fresh one. An
existing root with a different range or no saved report is refused; the command
never deletes a package.

### `sdd-gate next`: steps in order

| # | Step name | What it does | Refusal |
|---|---|---|---|
| 1 | `ledger` | workspace, header check, resolve the delivery base (writing its line when new) and, with `--completed`, the completed task's base | as above; missing or conflicting delivery base |
| 2 | `ledger-complete` | with `--completed`: append the `complete` line, head being the full `git rev-parse HEAD` | — |
| 3 | `mark-progress` | `workflow-state mark-progress --repo-root R --run-id I --action-id A` | never: a non-zero exit is reported as `refused` and the call continues, as the skill rules today |
| 4 | `review-package` | cumulative range: delivery base to the pinned head | as `review` step 3 |
| 5 | `validate-report` | as `review` step 4 | as `review` step 4 |
| 6 | `budget-check` | as `review` step 5 | as `review` step 5 |
| 7 | `metrics-match` | as `review` step 6, then append the `Delivery gate` line | as `review` step 6 |
| 8 | `task-brief` | with `--task`: run `task-brief PLAN_FILE M` | non-zero exit |
| 9 | `prepare-brief` | with `--task`: record the task base (`dispatched` line) if absent; read the plan header, template and standards; build everything except the worker line | see Rendering |
| 10 | `register-worker` | with `--task` and an identity: `workflow-state register-worker --repo-root R --run-id I --action-id A`, read `worker_id` | non-zero exit or no `worker_id` |
| 11 | `write-brief` | with `--task`: write the implementer brief | write failure |

Without a lifecycle identity steps 3 and 10 are skipped. Step 3 runs on every
call, which covers both "before the first task this session executes" and "after
each task's `complete` line"; an extra call answers `unchanged` and writes
nothing.

Registration is the last step that can refuse before one atomic file write, so
a failure normally leaves no registered worker without a brief. If step 11 itself
fails, the command releases the worker it just registered with `--event stopped`
before reporting the refusal.

`next --completed N` with no `--task` is the call after the last task: it stops
after step 7 and its package is the cumulative package the final review may
reuse under the skill's existing range-identity rule.

### Output and exit codes (D4)

Stdout is one compact JSON object and nothing else.

Ready, exit 0:

```
{"command":"review","outcome":"ready","task":2,"brief_path":"<abs>",
 "base_sha":"<sha40>","head_sha":"<sha40>","manifest_root":"<path>",
 "metrics":{"root_bytes":0,"total_bytes":0,"file_count":0,"largest_member_bytes":0},
 "standards":["<abs>", …]}

{"command":"next","outcome":"ready","completed":2,"task":3,"brief_path":"<abs>",
 "report_path":"<abs>","base_sha":"<sha40>","worker_id":"<id>","mark_progress":"advanced",
 "delivery":{"base_sha":"<sha40>","head_sha":"<sha40>","manifest_root":"<path>","metrics":{…}},
 "standards":["<abs>", …]}
```

Members that do not apply are `null` (`task`, `brief_path`, `report_path`,
`base_sha`, `worker_id`, `completed`). `mark_progress` is the outcome
`workflow-state` printed, `refused`, or `skipped`. `manifest_root` is the path
the producer reported.

Refused:

```
{"command":"review","outcome":"refused","step":"budget-check","gate":"failed",
 "detail":"<one line>","report":null,"completed_steps":["ledger","release-worker", …]}
```

- `step` is the step name from the tables above: the first step that failed.
- `gate` is `decompose_required` only when step `validate-report` saw a
  validated `decompose_required` report; it is `failed` for every other refusal
  of steps `review-package` to `metrics-match`, and `null` for the rest.
- `report` is the validated producer report object when `gate` is
  `decompose_required`, so the owner can record and return it; otherwise `null`.
- `detail` is one line and never carries artifact contents or member lists.

Exit codes: 0 ready; 3 when `gate` is `decompose_required`; 2 for every other
refusal and for an invalid invocation (which prints `sdd-gate: invalid
invocation` on stderr and nothing on stdout).

A refusal leaves earlier steps' effects in place (a released worker stays
released, a `complete` line stays written) and every step is safe to repeat, so
the owner re-runs the same call once the cause is fixed.

Every JSON document the command reads (the producer report, a manifest,
`workflow-state` output) is loaded strictly with the duplicate-key and
non-finite hooks from `agent_tools.canonical`.

### Rendering: which bytes the brief contains (D5)

This is the rule criterion 3 checks. For a template file `T`:

1. **Prompt body.** `T` holds exactly one unlabeled fenced block. Inside it,
   exactly one line equals `prompt: |` after stripping. The prompt body is every
   following line up to the closing fence. A line that is empty or only
   whitespace becomes an empty line; every other line must start with four
   spaces, which are removed. Lines are joined with `\n` and the body ends with
   one `\n`. Any other shape is refused. This is the same region
   `test_dispatch_contracts` treats as the template's prompt text.
2. **Placeholders.** Each template has a closed set of placeholder tokens,
   below. Every token of the set must occur in the body, and after filling no
   token of the form `[` + capital letters, digits and underscores + `]` may
   remain; either failure is refused as template drift. Bracketed prose such as
   `[Approved | Needs fixes]` is not a token and is copied through.
3. **Filling.** All tokens are replaced in one pass; a value is never rescanned.
   Values are inserted byte-for-byte.
4. **Empty values.** Only `[CONTEXT]` and `[LIFECYCLE_WORKER]` may be empty.
   Each stands alone on its line in the template; an empty value removes that
   line and, when the next line is empty, that line too.

The rendered brief is exactly the result: every byte outside a placeholder is
the template's byte. Nothing is prepended or appended.

The brief is written to the plan workspace with a temporary file and a rename:
`task-<N>-implementer-dispatch.md` and `task-<N>-review-dispatch.md`.

**Placeholder sets and values.**

| Token | Template | Value |
|---|---|---|
| `[TASK_NUMBER]` | implementer | the task number |
| `[TASK_NAME]` | implementer | the title field of the task's Task-index row |
| `[BRIEF_FILE]` | both | absolute path of `task-<N>-brief.md` in the workspace |
| `[REPORT_FILE]` | both | absolute path of `task-<N>-report.md` in the workspace |
| `[PLAN_ROOT]`, `[PLAN_ROOT_BYTES]`, `[PLAN_TOTAL_BYTES]`, `[PLAN_FILE_COUNT]`, `[PLAN_LARGEST_MEMBER_BYTES]` | both | absolute plan root path and the four metrics of an `implementation-plan` budget check run in this call |
| `[CONTEXT]` | implementer | the `--context-stdin` text with trailing newlines removed, or empty |
| `[GLOBAL_CONSTRAINTS]` | both | body of the plan root's `## Global Constraints` section |
| `[TEST_SEAMS]` | implementer | body of the plan root's `## Test seams` section |
| `[STANDARDS]` | both | the selected standards documents, below |
| `[STACKS_DIR]` | both | absolute path of the global `stacks/` directory |
| `[LIFECYCLE_WORKER]` | implementer | the worker block, below, or empty |
| `[BASE_SHA]`, `[HEAD_SHA]` | reviewer | the full task base and pinned head |
| `[MANIFEST_ROOT]`, `[ROOT_BYTES]`, `[TOTAL_BYTES]`, `[FILE_COUNT]`, `[LARGEST_MEMBER_BYTES]` | reviewer | the report's root path and the four agreed metrics |

A plan section body is the lines after the heading line up to the next line
starting with `## `, with leading and trailing empty lines dropped. A plan root
with no such heading, or more than one, is refused. The Task-index row is read
by the same row shape `task-brief` validates (`Task N — title — files — lane —
link`).

The worker block is the three lines the sdd skill prescribes today, with the
values substituted: the line `Lifecycle worker: --repo-root R --run-id I
--worker-id W`, then the `launch-scope exec` sentence and the `launch-scope
scratch` sentence. Reviewers are read-only and are not registered, so the
reviewer template has no such token.

**Template edits.** The two templates change only where a token must exist:

- implementer: `Task N: [task name]` becomes `Task [TASK_NUMBER]: [TASK_NAME]`;
  the bracketed scene-setting note in `## Context` becomes `[CONTEXT]`, a plan
  line, and labelled `[GLOBAL_CONSTRAINTS]` and `[TEST_SEAMS]`; a `## Standards`
  section is added; `[LIFECYCLE_WORKER]` opens `## Lifecycle Worker`.
- reviewer: a plan line is added beside the brief path; a `## Standards` section
  is added before `## Calibration`.

The plan line carries what the skill already requires every dispatch to carry
and no template holds today: the plan root path and its four metrics. Everything
else in both prompt bodies, the four leaf-agent clauses included, is untouched,
and the dispatch markers and `Agent(...)` lines above the fence stay where they
are. The `**Placeholders:**` note under the reviewer template is rewritten to say
`sdd-gate` fills them.

### Standards in the brief (D6)

Both briefs gain a `## Standards` section. The task templates carry none today,
while the standards README says a brief pastes Layer 0 in full plus the
documents whose globs intersect the change, and the issue lists them as brief
content. The section's fixed wording lives in the template: one sentence that
the work (or the code under review) is held to the documents below with the most
specific layer winning, the `[STANDARDS]` token, and one sentence telling the
reader to also read the stack document under `[STACKS_DIR]` that matches the
file types involved.

Selection is mechanical exactly where the layers have a machine-readable rule:

- **Layer 0**: `the-bar.md` in the global standards directory,
  `$HOME/.agents/standards`, always. A missing file is refused.
- **Layer 2**: for each `--standards` entry, in the order given. A directory
  whose `README.md` holds a table with a `governs` header cell contributes each
  row's linked document when one of the row's backticked globs matches a touched
  path, in row order. A regular file (the older single-file form) is included
  whole. Any other directory contributes nothing. A row whose link does not
  resolve to a regular file inside its directory is refused.
- **Layer 1** is not selected by the command. Stack documents declare their file
  types in prose, and one of them conditionally, so the reader chooses, as the
  final-review prompts already ask reviewers to.

Touched paths are repository-relative: for the reviewer, the paths changed
between the task base and the pinned head, with renames reported as a deletion
and an addition; for the implementer, the backticked paths in the files field of
the task's Task-index row. A glob matches with `fnmatch.fnmatchcase` on the
whole path, the rule `lane-triage` uses.

The `[STANDARDS]` value is, for each selected document in that order, the line
`Source: <absolute path>`, an empty line, and the document's text with trailing
newlines removed; documents are separated by one empty line. The output's
`standards` array lists the same paths.

### The skill's dispatch contract (D7, D8)

The sdd skill changes as follows.

- **Dispatch by rendered brief.** Step 1 runs `sdd-gate next` and dispatches the
  implementer or mechanic with a prompt of the fixed form: read the dispatch
  brief at `<brief_path>` and follow it exactly. Step 2's DONE route runs
  `sdd-gate review`, and step 3's full-lane review dispatches the reviewer with
  the same one-sentence form. The skill no longer tells the owner to copy
  template text, list dispatch contents or run `task-brief` itself. The
  `description`, agent type, model and effort still come from the template's
  marker lines.
- **Owner-authored context** (where the task fits, interfaces and decisions from
  earlier tasks, a resolved ambiguity, a pointer to a parked finding) goes in
  through `--context-stdin`. It is the only free text in a brief.
- **Refusals.** A `refused` outcome follows the route the skill already has for
  its step: `gate: decompose_required` and `gate: failed` are the review-package
  gate's second and third exits; a `release-worker` or `register-worker` refusal
  is a lifecycle failure handled as the skill's lifecycle rules say; any other
  step is a contract error that stops the run.
- **Lane verification.** A mechanical or low-risk lane task still calls
  `sdd-gate review` for the release and the gate, and the owner's short
  `reviewer-lite` prompt uses the `manifest_root` and `metrics` it prints. The
  rendered reviewer brief is simply not dispatched.
- **Re-dispatch of the same task** (NEEDS_CONTEXT, BLOCKED escalation): the
  owner releases the returned worker as the lifecycle rules say, then calls
  `next --task N` again with the added context. The task base is reused and a
  fresh worker is registered.
- **Unchanged.** The `### Review-package gate` section stays as the definition
  the fix loop and the final review apply by hand. `### Lifecycle workers` stays
  for fix rounds, resumes, the fence-refused route and the deadline rule, and
  says that `sdd-gate` performs the register, release and progress calls for the
  two dispatches it renders. The leaf-agent rule stays true as written: a prompt
  built from a template carries the clauses, now via the brief.

**Instruction budget.** The owner profiles load `SKILL.md` and both task
templates on every run, and have about 520 bytes of headroom each. The skill
edit replaces the hand-assembly prose of steps 1–3 and 5 with the two helper
calls, and the net change across those three files must pass
`just agent-instruction-budget` (profile and corpus ceilings) without a raise
label. If it does not fit, skill
prose is trimmed; the label is not available.

### Verification of the acceptance criteria (D9)

| Criterion | Kind | How this change answers it |
|---|---|---|
| 1. Owner turns per task ≤ 6 | evidence | Not verifiable here. It needs the owner transcript of a later orchestrated issue on the consumer project, run with the merged helper. |
| 2. Median dispatch prompt ≤ 1,000 characters | evidence | Not verifiable here, for the same reason. |
| 3. Rendered reviewer brief equals a hand-assembled one | code | The golden reviewer-brief test and the template identity test, below. |
| 4. Fails closed, naming the step | code | One command test per refusal: over budget, state not `complete`, release refused. |
| 5. Skill instructs dispatch by rendered brief | code | `skill-lint`, the skill-text pins and the updated sdd evals. |

Criteria 1 and 2 stay open after merge. The plan's acceptance record carries
their rows with no observed value, the conformance axis will grade them
`unverified` under its existing rule, and the pull request says that they are
post-merge evidence and how each is measured (the issue's own measurement
lines). Nothing in this change marks them met.

## Test seams

Three seams, all existing kinds.

1. **The command, run from source** as `python -m agent_tools.sdd_gate` in a
   temporary git repository, with a temporary `HOME` and `PATH` shims for the
   external commands. Prior art: `test_review_package.py` (fake `HOME`, policy
   link, `artifact-budget` shim) and `tests/test_launch_commit.py` (a shim that
   runs the source `workflow-state`). This seam carries:
   - the golden reviewer brief: a fixture skill directory holding a small
     fixture template with every reviewer token, a fixture plan, a fixture diff
     and fixture standards directories; the rendered file is compared byte for
     byte with a committed golden that was assembled by hand from those inputs.
     A second fixture diff that touches no governed path must drop the Layer-2
     document;
   - one test per refusal named in criterion 4, each asserting the exit code,
     `step`, `gate` and that no brief file was written: release refused by the
     real `workflow-state` (step `release-worker`); a producer report that
     validates as `decompose_required` (step `validate-report`, exit 3); a
     producer report claiming `complete` whose independent check is
     `over_budget` (step `budget-check`), forced through the `artifact-budget`
     shim;
   - the `next` order and ledger lines, with and without a lifecycle identity,
     including a repeated call writing no second `complete` or `dispatched`
     line, a `mark-progress` refusal not stopping the call, and a range whose
     package already exists being reused rather than rebuilt.
2. **The rendering functions, imported** from `agent_tools.sdd_brief`, for the
   real templates: filling every token of each repository template with the
   token itself must reproduce that template's prompt body, where the test
   derives the body independently (the fence lines after `prompt: |` with their
   first four characters removed). This proves byte fidelity for the shipped
   templates without pinning any of their prose, and fails when a template gains
   a token the helper does not know or loses one it needs.
3. **Skill text and installation**: the existing sdd machine-text pins in
   `test_workflow_skill_contracts.py` replace the `task-brief` argv with the two
   `sdd-gate` argv forms; the shell-example command vocabulary gains `sdd-gate`;
   the installed-layout test covers the new launcher and the installed
   `task-brief` as it covers their siblings. No test pins an English phrase.

The fixture template is deliberately not a copy of a shipped template: a golden
copy of shipped prose would be a phrase pin, which the agent-helpers standard
forbids.

## Documentation that follows

- `python/README.md` gains the `sdd-gate` contract: both subcommands, the step
  names, the output object, the exit codes and the ledger lines.
- `home/common/agent-skills/README.md` records that `task-brief` is installed on
  `PATH` and why.
- The sdd evals' expectations are reworded where they describe hand assembly:
  the dispatch-contents case, the cumulative-gate case and the live one-task
  case.
- `CLAUDE.md` is not edited; command contracts belong in `python/README.md`.

## Out of scope

- Changes to `review-package`, `artifact-budget` or `workflow-state`.
- The fix-loop re-review, the final-review axes and the ship-review brief. They
  keep their hand-assembled prompts and hand-run gate. `sdd-gate review` is the
  natural base for a later re-review mode; none is built here.
- Resumed implementers in fix rounds: a resume message still carries the
  findings and a fresh worker line composed by the owner.
- The deadline headroom check and the fence-refused route.
- Measuring criteria 1 and 2.
- Moving the task templates out of the owner profiles' hot set, or moving their
  dispatch markers into `SKILL.md`. The owner still opens the templates for the
  marker lines.
- A machine-readable file-type index for the Layer-1 stack documents.
- Moving `task-brief` or `sdd-workspace` into the package.

## Triage

- Input: `{"signals":{"contract_change":{"value":"hit","evidence":"adds a new agent_tools command and changes the sdd skill's dispatch contract (prompt = path to rendered brief)"},"concurrency_or_persistence":{"value":"hit","evidence":"the helper chains workflow-state release-worker, mark-progress and register-worker, which write the persisted run ledger"},"open_design_questions":{"value":"hit","evidence":"command home and shape, which gate steps it owns, and whether the task-review brief carries standards shards are undecided"},"criteria_shape":{"value":"hit","evidence":"five acceptance criteria; two [evidence] ones need a future nodocom transcript and no deterministic code check verifies them"}},"paths":["python/agent_tools/sdd_gate.py","lib/agent-tools.nix","python/README.md","home/common/agent-skills/skills/sdd/SKILL.md","home/common/agent-skills/skills/sdd/implementer-prompt.md","home/common/agent-skills/skills/sdd/task-reviewer-prompt.md","home/common/agent-skills/skills/sdd/fix-loop.md","home/common/agent-skills/skills/sdd/evals/evals.json","tests/test_sdd_gate.py","tests/fixtures/sdd-gate/golden-reviewer-brief.md"]}`
- Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}`
- `ran: full (shadow)`

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The helper is the package command `sdd-gate` (`agent_tools.sdd_gate`, rendering in `agent_tools.sdd_brief`); it runs `review-package` as a packaged sibling and `workflow-state`, `artifact-budget`, `sdd-workspace` and `task-brief` by name on `PATH`, which installs `task-brief` beside `sdd-workspace`; templates come from a required `--skill-dir`. | `docs/standards/agent-helpers.md` rules 1–3; `review-package` already calls `sdd-workspace` by `PATH`. | Another script under `sdd/scripts/` (rule 1); running `task-brief` by a path under `--skill-dir` (rule 3 says by name on `PATH`); a default installed template path (an owner on a working-tree skill would render stale templates). |
| D2 | One command with two subcommands, `review` and `next`, one per task boundary; each does its gate steps and renders its brief in the same call. | The issue's demo: one helper call between each review and the next dispatch. The task loop has two boundaries, each ending in a different dispatch. | One undivided call (it would have to guess which boundary it is at); separate gate and render commands (two calls per boundary, missing the issue's goal). |
| D3 | No state file. The delivery base and each task's base are ledger lines the helper appends and later reads; it also appends the `complete` and `Delivery gate` lines. Every step is repeatable. | The sdd skill: after compaction trust the ledger; SHAs and metrics are recorded there. The bar: few parameters, defaults absorb the common case. | The owner passing full SHAs on each call (a model re-typing 40-character values is a failure site, and the task base is lost on compaction today); a `gate.json` beside the ledger (a second store that can go stale across launches). |
| D4 | A refusal prints `{outcome: refused, step, gate, …}`; exit 3 for a validated `decompose_required`, 2 otherwise. `mark-progress` never refuses the call. Registration is the last refusable step before one atomic write, and a failed write releases the worker it registered. | The review-package gate's three exits and the producer's exit codes; the skill's rule that a `mark-progress` refusal never stops the loop; the lifecycle rule that an owner cannot suspend while a registered worker is live. | A single non-zero exit for every refusal (the owner could not tell the return-to-caller exit from a failure); registering before the brief inputs are checked (a refusal would strand a live worker). |
| D5 | The brief is the template's prompt body, dedented by four spaces, with a closed token set filled in one pass and nothing added; templates are edited so every owner-filled slot is a token; unknown or missing tokens are refused. | The issue: the brief is byte-for-byte what the owner would paste, only the assembler changes; `test_dispatch_contracts` already defines the prompt region. | Keeping the template text in the Python module (two homes for the wording); free-form slots such as `[task name]` matched loosely (silent drift). |
| D6 | Both briefs gain a `## Standards` section: Layer 0 pasted in full, Layer-2 documents pasted when a `governs` glob matches a touched path, and Layer 1 left to the reader by one fixed sentence. Reviewer paths come from the diff, implementer paths from the Task-index row. | The standards README's Loading rule and the bar's first paragraph; the issue names the standards whose globs match the diff as brief content, and criterion 3 names them. | No standards (matches today's templates, but contradicts the issue and the Loading rule); listing paths only (the README says paste, and a pasted brief needs no extra reads); a file-type table for Layer 1 in the helper (a second home for prose rules, one of which is conditional). |
| D7 | Only the implementer and first-pass task-review dispatches move to rendered briefs. Fix-loop re-reviews, final-review axes, resumes and the ship review keep their current form; lane verification reuses `review` for the gate only. | The acceptance criteria measure only those two dispatches; the scope boundary excludes the ship-review brief. | Rendering every sdd dispatch now (three more templates and the resume path, well past the size estimate). |
| D8 | With no lifecycle identity the three lifecycle steps are skipped and the worker block is empty; a partial identity, or a worker id without one, is an invalid invocation; `review` under an identity requires the worker id. | The sdd skill: without a lifecycle identity none of the worker rules apply. `workflow-state` treats a repeated release as a no-op. | Inferring the identity from the environment or the ledger (the contract carries no environment values; a successor launch has a new action id). |
| D9 | Criteria 3–5 are verified in code by this change; criteria 1 and 2 remain post-merge evidence, recorded as unmeasured rows and named in the pull request. Criterion 3 is tested with a fixture template plus a token-identity test on the shipped templates, never a golden copy of shipped prose. | The issue's own measurement lines; `docs/standards/agent-helpers.md` rule 6; the conformance axis's rule for evidence rows. | Estimating turns or prompt length from a local dry run and calling it met (not the stated measurement); a golden of the real reviewer template (a phrase pin). |
| D10 | When the range's package already exists the command reuses it under the skill's existing-package rule, using a validated report it saved beside the package at build time; it never rebuilds over or deletes a package. | The sdd skill's cumulative-gate rule for a validated existing package; the producer refuses a second publish to the same root. | Deleting and rebuilding (needs the producer's layout knowledge and destroys review evidence); a unique output path per call (the reviewer and the final review would see several packages for one range). |
| D11 | Plan: owner context reaches `next` as `--context-file PATH`, a UTF-8 file the owner writes with the file-writing tool. This amends the Invocation and the skill contract wherever they name `--context-stdin`; trailing newlines are still removed and it is still the brief's only free text. | `worktrees/SKILL.md`, "Shell forms the isolation checker refuses": a stdin heredoc is sanctioned only for the two helpers the permission allow list admits whole and is never copied to another command, and the stated alternative is a file passed by path; `test_shell_example_contracts` refuses the example. | `--context-stdin` fed by a quoted heredoc (a refused form for a command that is not allowed whole); adding `sdd-gate` to the allow list in `home/common/claude-code/default.nix` (new authorization planning cannot grant; it would save the one extra owner call per task that has context); a quoted argument (prose through shell quoting). |
| D12 | Plan: details the design left open. The token check runs on the template body before filling (its token set must equal the closed set) and the filled brief is not scanned; a Task-index title may contain a spaced em dash (the last three fields are files, lane and link); every row of a `governs` table must link a regular file in its directory, matching or not, and a `--standards` path that does not exist is refused; the validated report is saved beside the package for `decompose_required` too; an identical `Delivery gate` line is not appended twice; `sdd-gate --help` prints usage and exits 0. | D5's rule that a value is never rescanned; `task-brief`'s row pattern; D4's fail-closed refusals; D10 (a repeated call reaches the same exit); D3 (repeatable steps); `tests/test_agent_tools_launchers.py` asks every launcher for `--help`. | Scanning the filled brief for leftover tokens (it would refuse a standards document that mentions token-shaped text); a parser without help plus a special case in the launcher test. |
| D13 | Plan: the skill text lands at +361 bytes against 515 bytes of corpus headroom. It is paid for by deleting text the helper makes dead: the reviewer template's placeholder list (one line stays), step 1's `task-brief` and dispatch-contents bullets, the standalone `mark-progress` paragraph and step 3's two prompt-composition bullets. The template edits land first (+87) with a placeholder line that names no command until the skill switches. Over budget, only the new sentences are shortened; otherwise the task stops and reports. | `agent_tools.instruction_load` run on the base with the dictated text applied: `check: pass`, 154 bytes left; only the user applies the raise label. | Raising a ceiling (not available); keeping the hand-assembly prose beside the helper calls (two instructions for one step, and over budget). |
| D14 | Plan: test-seam details. The over-budget refusal is forced on the reuse path: one passing call, then a shim that answers the independent `review-package` check `over_budget`, because the producer runs that same check itself. The goldens hold `@@NAME@@` slots for run-dependent values (paths, SHAs, metrics) which the test fills from its own observations, and an implementer golden stands beside the reviewer one. | Seam 1's shim boundary, as in `test_review_package.py`; the bar: expected values come from an independent source. | A shim that counts calls (it depends on how often the producer checks); normalizing the rendered brief before comparing (no longer byte for byte). |
