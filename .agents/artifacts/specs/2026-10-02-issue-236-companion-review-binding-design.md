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

The user needs two things. First, a configured Codex review on the companion
binding delivers the packet, returns a result attributed to Codex, and passes a
validation as strict as the `codex exec` route's. Second, any binding the skill
cannot drive is reported as a specific configuration error, not as a runtime
failure followed by a silent fallback.

## Solution

The skill recognises a closed set of two **review binding shapes** from the
authored base argv and builds a different invocation and validation for each:

- **exec shape.** This is today's route and is unchanged: the `codex exec` tail,
  the packet on stdin, JSONL plus last-message validation.
- **companion shape.** The skill appends companion flags that pin the model and
  reasoning effort, the worktree and JSON output. It sends the packet on stdin
  with no positional prompt, then validates the companion's single JSON result
  payload.

Any other argv is a **binding shape error**. The skill stops before calling
Codex, names the cause, and takes no fallback. The companion's JSON payload does
not report the runtime selection, so the patched companion gains that report:
the model and reasoning effort that Codex's app-server confirms when the thread
starts.

## Decisions

### Review binding shape (skill)

After routing `available` and dereferencing `bindings.commands[review_id]`,
classify its `argv` before building any invocation (per D1, D2):

- **exec shape:** the basename of `argv[0]` is exactly `codex`. The base argv,
  cwd and declared env are preserved and the existing tail is appended
  unchanged.
- **companion shape:** the basename of `argv[0]` is exactly `codex-companion`,
  `argv[1]` is `task`, and the remaining tokens are exactly `--reviewer <op>`
  plus an optional `--fresh`, in any order. `<op>` must equal the running
  operation (`plan-review` or `diff-review`). No other flag and no positional
  token may appear: the skill owns model, effort, cwd and output selection, and
  a positional token would displace the stdin packet.
- **anything else:** a binding shape error.

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
(per D5, D6):

1. Exit status 0, and stdout parses as exactly one JSON object.
2. Its `status` is `0`, its `touchedFiles` is empty, and its `runtime.model` is
   `gpt-6-astra` and `runtime.reasoningEffort` is `xhigh`.
3. Its `rawOutput` is a non-empty string. It is the turn's single terminal agent
   message, taken byte for byte, and it passes the operation's heading
   validation.

The exec route's JSONL and last-message candidates are not created on this
route. Every existing failure class carries over unchanged. A daemon, slot or
capacity rejection stops verbatim with no retry and no fallback. A completed
runtime failure, a malformed or mismatched payload, or a schema failure takes
exactly one native fallback with the same packet.

### Binding shape error

A binding shape error is a configuration error, not a runtime failure (per D3).
The skill makes no Codex call, makes no retry and takes no native fallback, and
stops the operation with one error. The error names the operation, the
`review_id`, the authored argv and the specific cause:

- unrecognised executable
- a companion subcommand other than `task`
- a missing or mismatched `--reviewer`
- an unsupported companion token

Its handling matches how `blocked` stops, but it is reported as a binding shape
error and carries no capability repair ID. Calling controllers (`from-issue`
Phase 5, `sdd`, `ship-issue`) already route `blocked` before they invoke the
skill, and they already receive a capacity rejection as a stopped operation
with a verbatim error. A shape error reaches them through that same stop
path, so no caller document changes (per D8).

### Companion runtime report (patched codex-plugin-cc)

- When a task requests an effort and starts a fresh thread, it sends that effort
  to `thread/start` as the config override `model_reasoning_effort`, in addition
  to the turn's effort it already sends. That makes the app-server's start
  response confirm the selection the turn runs under.
- The `task --json` payload gains `runtime: { model, reasoningEffort }`, copied
  verbatim from the app-server's thread start or resume response, with `null`
  where the response has none. The field is added for every task, not only for
  reviewer tasks (per D5). Existing payload fields are unchanged.
- The fake-codex test fixture echoes that config override in its `thread/start`
  reply, so the suite can observe the field.

Evidence (2026-10-02, codex-cli 0.159.0): a `thread/start` with
`model: gpt-6-astra` returns `model: gpt-6-astra` and returns
`reasoningEffort: xhigh` or `low` exactly as the config override requests.
Without an override it returns the `config.toml` default.

### Docs that change

- **SKILL.md:** the direct configured review states both shapes, the classifier
  and the shape error.
- **PLAN-REVIEW.md / DIFF-REVIEW.md:** only where they restate the invocation or
  the validation.
- **evals.json:** eval 1 covers the plan review on the companion binding, and
  evals 2–3 describe both shapes' invocations.
- **The patch:** source, fixture and tests, with `patchRevision` bumped.

## Test seams

Per D7:

1. **Skill contract tests** (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
   the existing ordered-anchor helpers for the operation pair and the configured
   code-review pair). They pin the classifier, both invocations, both validations
   and the shape error's handling ahead of the fallback. They also pin that the
   evals describe both shapes.
2. **Companion node suite** (the patched plugin's `tests/*.test.mjs`, existing
   fake-codex fixture). It asserts that a `task --json` run reports
   `runtime.model` and `runtime.reasoningEffort` matching the requested values.
   It also asserts that a stdin packet with no positional argument is the
   thread's first prompt.
3. **Build** (`just build`). It proves that the patch applies and that the
   installed skill text is the edited source.

The live demo is acceptance evidence, not a test seam: a nodocom-shaped plan
review run through the skill returns Codex-attributed `Blocking` /
`Should fix` / `Discussion` with no fallback.

## Out of scope

- nodocom's `.agents/project.json` and any project's authored bindings.
- The resolver schema. No declared shape field is added.
- The `codex:codex-reviewer` plugin bridge and its background route.
- Review packet content, heading schemas, disposition rules, capability routing
  and capacity semantics.
- Any third binding shape, such as a wrapper script or `codex` with an embedded
  subcommand.
- Effort attestation for resumed companion threads beyond copying what the
  resume response reports.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Support both the companion `task` shape and the exec shape as a closed set; anything else is an error | Issue acceptance criteria 1–3 require the companion binding to succeed; nodocom's bindings are out of scope; the-bar *Fail loud* | Requiring exec-compatible bindings only: it fails the issue's demo and forces an out-of-scope edit to nodocom |
| D2 | Classify by the authored argv: the basename of `argv[0]` (`codex` or `codex-companion`), plus an exact companion token set whose `--reviewer` equals the running operation; skill-owned flags and positional tokens are rejected | bootstrap: argv is policy as authored, so reading its structure is dispatch, not defaulting; the shipped `["codex"]` binding stays valid | A declared shape field in the resolver schema: a schema change the issue scopes out; a binding field nobody else needs |
| D3 | A binding shape error stops before any Codex call, with no retry and no native fallback, naming the operation, `review_id`, argv and cause | Issue acceptance criterion 4; the-bar *Truthful terminal states*; bootstrap "fix the contract; never guess" | Treating it as a completed runtime failure with one native fallback: that is exactly the silent masking the issue reports |
| D4 | The companion route sends the packet on stdin with no positional argument, and appends `--model gpt-6-astra --effort xhigh --cwd <worktree> --json`, run in the foreground | `readTaskPrompt` uses stdin when no prompt file and no positional are given; the `codex:codex-reviewer` bridge uses the same stdin form; one packet-delivery rule across both shapes | `--prompt-file`: it needs another temp file and cleanup, and the shape rule already guarantees no positional |
| D5 | Patch the companion to report `runtime: {model, reasoningEffort}` from the app-server's thread response for every task, and carry the requested effort into `thread/start` config so the response confirms it | The exec route accepts only selections the runtime reports; a live probe shows `thread/start` echoes the override; the field is additive and harmless outside reviewer tasks | Trusting the requested `--model`/`--effort` flags: no attestation, a weaker check than the exec route; parsing the job log: not a contract |
| D6 | Companion success = exit 0, one JSON object, `status` 0, empty `touchedFiles`, matching `runtime`, non-empty `rawOutput` as the single terminal message, then headings; no JSONL or last-message candidates on this route | The issue sanctions validation "reworked to match the companion's output"; the companion captures exactly one turn's last agent message | Wrapping the companion to emit codex-exec JSONL: it mimics a format the runtime does not produce |
| D7 | Test seams: the skill contract tests (existing ordered-anchor helpers), the patched plugin's node suite with the fake-codex fixture, and `just build`; the live demo is acceptance evidence only | Existing seams in `test_workflow_skill_contracts.py` and the plugin suite; the-bar *Tests that can fail* | A new `agent_tools` classifier command: it adds a command-table row and surface for a rule the skill already states in prose (YAGNI) |
| D8 | A shape error uses the callers' existing stopped-operation path (the same one a capacity rejection takes); `sdd`, `ship-issue` and `from-issue` stay unchanged | Callers already route `blocked` themselves and surface a codex-collaboration stop verbatim; scope is limited to the skill, evals, tests and patch | A new caller-visible outcome class: it changes three controllers for an error a contract fix resolves |
