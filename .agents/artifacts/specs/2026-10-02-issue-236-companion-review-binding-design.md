# Issue 236 — codex-collaboration drives the companion `task` review binding

Issue: https://github.com/fagenorn/nix-config/issues/236

## Problem

A project may bind its configured review to the Codex companion instead of to
the Codex CLI. nodocom binds `review-plan` and `review-code` to
`codex-companion task --fresh --reviewer <plan-review|diff-review>`. The
`codex-collaboration` skill only knows one invocation shape. It appends a
`codex exec` argument tail to whatever base argv the binding declares and sends
the packet on stdin. The companion's `task` command builds its prompt from
`--prompt-file` first, then from the joined positional arguments, and only then
from piped stdin. The appended tail therefore becomes the prompt and the packet
is dropped. Codex answers that it received only an execution command. No JSONL
and no last-message file are produced, validation fails, and the skill quietly
takes its one native fallback. Every `--auto` plan review on such a project runs
on a Claude reviewer while looking like a transient Codex failure.

The `codex exec` route is no better. On codex-cli 0.159.0, `codex exec --json`
emits only `thread.started`, `turn.started`, `item.*` and `turn.completed`. It
has no runtime-selection event, and a turn carries several `agent_message`
items. The exec route's model/effort check can never pass, so this repo's own
`["codex"]` reviews have always fallen back to Claude silently. This run's own
Phase-5 plan review showed it live.

The user needs three things. First, a configured Codex review delivers the
packet and returns a result attributed to Codex. That result must pass a
validation that attests model and effort from the runtime. Second, any binding
the skill cannot drive is reported as a specific configuration error, not as a
runtime failure followed by a silent fallback. Third, nix-config's own reviews
must actually run on Codex. The user's decision: there is one review route, and
it is the companion.

## Solution

The skill supports exactly one **review binding shape**, the companion `task`
reviewer form. It recognises that shape from the authored base argv. It appends
flags that pin the model, the reasoning effort, the worktree and JSON output. It
sends the packet on stdin with no positional prompt. It then validates the
companion's single JSON result payload. The `codex exec` invocation and its
JSONL/last-message validation are removed.

Any other argv, bare `["codex"]` included, is a **binding shape error**. The
skill stops before calling Codex and names the cause and the expected form. It
takes no fallback. The companion's JSON payload does not report the runtime
selection, so the patched companion gains that report: the model and reasoning
effort that Codex's app-server confirms when the thread starts.

nix-config migrates its own two review bindings to that shape, with one command
entry per operation.

## Decisions

### Review binding shape (skill)

After routing `available` and dereferencing `bindings.commands[review_id]`,
classify its `argv` before building any invocation (per D13). It is the
companion shape only when all of the following hold:

- the basename of `argv[0]` is exactly `codex-companion`;
- `argv[1]` is `task`;
- the remaining tokens are exactly `--reviewer <op>` plus an optional `--fresh`,
  in any order;
- `<op>` equals the running operation (`plan-review` or `diff-review`).

No other flag and no positional token may appear. The skill owns model, effort,
cwd and output selection, and a positional token would displace the stdin
packet. Anything else is a binding shape error.

### Companion invocation

Keep the base argv, cwd and declared env, then append:

```text
bindings.commands[review_id].argv \
  --model gpt-6-astra --effort xhigh \
  --cwd <absolute-worktree> --json
```

Send the complete packet on stdin, with no positional argument (per D4). Run in
the foreground. The companion's reviewer mode already forces a fresh,
read-only, ephemeral thread and applies the operation's registered wall-clock
budget, so the skill passes none of these.

### Companion validation

Success, and with it reviewer identity `Codex`, requires all of the following
(per D5, D6, D15):

1. Exit status 0, and stdout parses as exactly one JSON object.
2. Its `status` is `0`, its `touchedFiles` is empty, its `runtime.model` is
   `gpt-6-astra` and its `runtime.reasoningEffort` is `xhigh`.
3. Its `rawOutput` is a non-empty string, the companion's last captured agent
   message, and it passes the operation's heading validation.

Every existing failure class carries over unchanged. A daemon, slot or capacity
rejection stops verbatim with no retry and no fallback. A completed runtime
failure, a malformed or mismatched payload, or a schema failure takes exactly
one native fallback with the same packet.

### Binding shape error

A binding shape error is a configuration error, not a runtime failure (per D3).
The skill makes no Codex call, no retry and no native fallback. It stops the
operation with one error that names the operation, the `review_id`, the
authored argv, the expected form `codex-companion task [--fresh] --reviewer
<op>` and one specific cause (per D13):

- an executable other than `codex-companion`, bare `codex` included
- a companion subcommand other than `task`
- a missing or mismatched `--reviewer`
- an unsupported companion token

It stops the way `blocked` does, but it is reported as a binding shape error
and carries no capability repair ID. Callers receive it through their existing
stopped-operation path, so no caller adds a new outcome (per D8).

### Companion runtime report (patched codex-plugin-cc)

This part is already delivered and kept as is:

- When a task requests an effort and starts a fresh thread, it sends that effort
  to `thread/start` as the config override `model_reasoning_effort` (per D10).
  The override goes in alongside the turn's effort it already sends.
- The `task --json` payload gains `runtime: { model, reasoningEffort }`, copied
  verbatim from the app-server's thread start or resume response, with `null`
  where the response has none. The field is added for every task (per D5).
- The fake-codex fixture echoes that override in its `thread/start` reply.

Evidence (2026-10-02, codex-cli 0.159.0): a `thread/start` with
`model: gpt-6-astra` returns `model: gpt-6-astra`. It returns
`reasoningEffort: xhigh` or `low`, exactly as the config override requests.

### nix-config's review bindings

The committed contract replaces the single `codex-review` entry (`["codex"]`)
with two command entries (per D14):

- `codex-plan-review`: `["codex-companion","task","--fresh","--reviewer","plan-review"]`
- `codex-diff-review`: `["codex-companion","task","--fresh","--reviewer","diff-review"]`

Both take cwd `.` and no env. `workflow.review.plan` names `codex-plan-review`
and `workflow.review.code` names `codex-diff-review`. The resolver schema is
unchanged: command ids are free keys and each review member names one of them.
The projections are generated from the instruction source, not from commands,
so they are unaffected.

### What changes

- **codex-collaboration SKILL.md:** the direct configured review states the
  single companion shape, its invocation, its validation and the shape error.
  The exec subsection is removed.
- **The shared caller paragraph** in `sdd`'s final review and `ship-issue`'s
  review is rewritten identically in both files to the companion shape only.
  Their stop paths stay unchanged (per D9, D15).
- **evals.json:** evals 1–3 describe the companion invocation and validation
  only.
- **The committed contract:** the two entries and repointed review bindings
  above.
- **Test fixtures** that stub the review executable as `codex`, or that name
  the `codex-review` id, follow the new contract (per D16).
- **PLAN-REVIEW.md / DIFF-REVIEW.md, the patch:** unchanged by the redo.

## Test seams

Per D7 and D16:

1. **Skill contract tests** (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
   the existing ordered-anchor helpers for the operation pair and the configured
   code-review pair). They pin the classifier, the one invocation, the
   validation and the shape error's handling ahead of the fallback. They pin
   that the direct-review section carries exactly one tail block and no exec
   tail, and that the evals describe the companion shape. The committed-bindings case
   lives in `test_resolve_project.py` instead (per D18).
2. **Resolver and conformance suites** (`test_resolve_project.py`,
   `conformance_test_support.py`, `test_conformance_checks.py`). These are the
   existing fixtures, with `codex-companion` stubbed wherever `codex` stood for
   the review executable, and a remaining command id used where `codex-review`
   appeared.
3. **Companion node suite** (the patched plugin's `tests/*.test.mjs`): already
   delivered. It covers `runtime` reporting and the stdin packet.
4. **Build** (`just build`) and `just agent-workflow-tests`.

The live demo is acceptance evidence, not a test seam. A plan review on this
repo's own migrated binding returns Codex-attributed `Blocking` / `Should fix` /
`Discussion` with no fallback.

## Out of scope

- nodocom's `.agents/project.json` and any other project's authored bindings.
- The resolver schema. No declared shape field is added.
- The `codex:codex-reviewer` plugin bridge and its background route.
- Review packet content, heading schemas, disposition rules, capability routing
  and capacity semantics.
- Reworking `codex exec` validation, and any shape besides the companion
  reviewer form, such as a wrapper script.
- Effort attestation for resumed companion threads beyond copying what the
  resume response reports.
- The archived path-migration records that mention `codex-review`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Support both the companion `task` shape and the exec shape as a closed set; anything else is an error | Issue acceptance criteria 1–3 require the companion binding to succeed; nodocom's bindings are out of scope; the-bar *Fail loud* | Requiring exec-compatible bindings only: it fails the issue's demo and forces an out-of-scope edit to nodocom |
| D2 | Classify by the authored argv: the basename of `argv[0]` (`codex` or `codex-companion`), plus an exact companion token set whose `--reviewer` equals the running operation; skill-owned flags and positional tokens are rejected | bootstrap: argv is policy as authored, so reading its structure is dispatch, not defaulting; the shipped `["codex"]` binding stays valid | A declared shape field in the resolver schema: a schema change the issue scopes out; a binding field nobody else needs |
| D3 | A binding shape error stops before any Codex call, with no retry and no native fallback, naming the operation, `review_id`, argv and cause | Issue acceptance criterion 4; the-bar *Truthful terminal states*; bootstrap "fix the contract; never guess" | Treating it as a completed runtime failure with one native fallback: that is exactly the silent masking the issue reports |
| D4 | The companion route sends the packet on stdin with no positional argument, and appends `--model gpt-6-astra --effort xhigh --cwd <worktree> --json`, run in the foreground | `readTaskPrompt` uses stdin when no prompt file and no positional are given; the `codex:codex-reviewer` bridge uses the same stdin form; one packet-delivery rule across both shapes | `--prompt-file`: it needs another temp file and cleanup, and the shape rule already guarantees no positional |
| D5 | Patch the companion to report `runtime: {model, reasoningEffort}` from the app-server's thread response for every task, and carry the requested effort into `thread/start` config so the response confirms it | Attestation from the runtime, not from the requested flags, is what the skill's validation intends (the exec route's selection-event check; see D11 for its live gap); a live probe shows `thread/start` echoes the override; the field is additive and harmless outside reviewer tasks | Trusting the requested `--model`/`--effort` flags: no attestation, a weaker check than the exec route; parsing the job log: not a contract |
| D6 | Companion success = exit 0, one JSON object, `status` 0, empty `touchedFiles`, matching `runtime`, non-empty `rawOutput` (the companion's last captured agent message), then headings; no JSONL or last-message candidates on this route | The issue sanctions validation "reworked to match the companion's output"; the companion keeps the main thread's last non-empty agent message of the turn (`lib/codex.mjs` `lastAgentMessage`) | Wrapping the companion to emit codex-exec JSONL: it mimics a format the runtime does not produce |
| D7 | Test seams: the skill contract tests (existing ordered-anchor helpers), the patched plugin's node suite with the fake-codex fixture, and `just build`; the live demo is acceptance evidence only | Existing seams in `test_workflow_skill_contracts.py` and the plugin suite; the-bar *Tests that can fail* | A new `agent_tools` classifier command: it adds a command-table row and surface for a rule the skill already states in prose (YAGNI) |
| D8 | A shape error uses the callers' existing stopped-operation path (the same one a capacity rejection takes); `sdd`, `ship-issue` and `from-issue` stay unchanged | Callers already route `blocked` themselves and surface a codex-collaboration stop verbatim; scope is limited to the skill, evals, tests and patch | A new caller-visible outcome class: it changes three controllers for an error a contract fix resolves |
| D9 | Reverses D8 in part: the one configured-review paragraph that `sdd/final-review.md` and `ship-issue/REVIEW.md` share, which restates the exec tail, is rewritten identically in both to state both shapes and the shape error; their stop paths stay unchanged | Both files tell the reader to append the exec tail, so they would contradict the skill on a companion binding; the paragraph-identity test from issue 195 keeps them in step | Leaving the callers untouched as D8 said: they would keep the bug in their own text for every diff review |
| D10 | `thread/start` gets `config: {model_reasoning_effort}` only when the task requested an effort; otherwise its params stay byte-identical to today, and `thread/resume` never gets it | Keeps every effort-less task and existing `lastThreadStart` assertion unchanged; the spec scopes resume attestation out | Always sending `config`, with `null` when there is no effort: it changes requests that no reviewer makes, and a null override is not a confirmed selection |
| D11 | Known gap, not fixed here: on codex-cli 0.159.0 `codex exec --json` emits no runtime-selection event and several `agent_message` items, so the exec shape's existing model/effort check (kept unchanged per D1) cannot pass and every exec-shape review takes the native fallback; recorded for a follow-up issue | Phase-5 observation of this run's own exec-shape plan review; the issue scopes the companion route; AUTO.md: a should-fix implying scope change backs up rather than scope-creeps | Reworking exec-shape validation in this issue: a separate contract change outside the issue's acceptance criteria |
| D12 | Reverses D1 and resolves D11 by removal: the companion `task` reviewer form is the one supported review binding shape; the exec invocation and its JSONL/last-message validation are deleted, not reworked | User decision (redo): "one review route only — the companion"; D11's evidence that exec can never attest model/effort on codex-cli 0.159.0; the-bar *Root causes*, *YAGNI* | Keeping exec with a reworked validation: no runtime-selection event exists to attest, so it would trust requested flags or keep silently falling back |
| D13 | Reverses D2: the classifier accepts only basename `codex-companion` + `task` + `--reviewer <op>` (+ optional `--fresh`); bare `["codex"]` and every other argv is a shape error whose message also names the expected form `codex-companion task [--fresh] --reviewer <op>` | User decision (redo); bootstrap "no project policy is defaulted … fix the contract"; D3 | Silently translating `["codex"]` into a companion call: it guesses policy the contract never authored |
| D14 | nix-config replaces `codex-review` with `codex-plan-review` and `codex-diff-review` (`["codex-companion","task","--fresh","--reviewer",<op>]`, cwd `.`, no env) and repoints `workflow.review.plan`/`.code`; no resolver schema or projection change | User decision (redo); `--reviewer` must equal the operation (D13); the resolver takes any command-id key and validates review members only as command-id references; projections derive from the instruction source; delivery seals no command member | One shared entry with the skill appending `--reviewer`: the skill would be authoring policy, and the shape rule forbids a missing `--reviewer` |
| D15 | Reverses D9 in part and amends D6: the shared caller paragraph and the evals state only the companion shape; D6's "no JSONL or last-message candidates on this route" clause is dropped as moot, the rest of D6 stands | D12 leaves one route, so a cross-route contrast has nothing to contrast; the paragraph-identity test keeps both callers in step | Keeping the exec text as "deprecated": it leaves callers describing a route the skill refuses |
| D16 | Amends D7: the resolver and conformance fixtures stub `codex-companion` in place of `codex` and stop naming `codex-review`; one skill-contract case pins the committed bindings through `resolve-project resolve`, never by reading the contract file | Those fixtures copy the committed contract and the resolver blocks a review capability whose `argv[0]` is not on PATH; bootstrap forbids reading `.agents/project.json` directly | No test of the migrated bindings: the demo would be the only guard against a regression to `["codex"]` |
| D17 | Every exec-tail pin in the skill contract tests is replaced by its companion counterpart and inverted into a negative pin: the skill, both caller paragraphs and the evals may carry none of `exec --sandbox`, `--output-last-message`, `terminal agent-message`, `model_reasoning_effort` or JSONL | D12 deletes the route; the-bar *Tests that can fail* | Only deleting the exec anchors: text that reintroduces the exec route would still pass |
| D18 | Amends D16's location: the committed-bindings case lives in `test_resolve_project.py`, resolving a `make_root()` copy of the contract under the suite's hermetic installed home, and asserts bindings only, never capability state | The resolver refuses `platform.manifest.missing` without an installed manifest under `$HOME/.agents/share`, which CI's source-only run lacks; review readiness is `shutil.which(argv0)`, and CI has no `codex-companion` | A case in `test_workflow_skill_contracts.py` against the real `HOME`: it refuses in CI, and asserting `available` would depend on the host |
| D19 | The live demo runs the build-closure companion before activation, and pre-activation Codex reviews of this branch are expected to take the native fallback | Phase-5 review: the PATH companion and installed skill are the pre-branch `.p12` build; activation (`just switch`) needs the user | Requiring `just switch` during delivery: activation is outside standing authorization |
