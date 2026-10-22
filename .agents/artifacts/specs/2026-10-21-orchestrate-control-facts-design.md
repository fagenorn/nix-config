# `orchestrate-control`: the adapter's fact gathering and control round as one helper call

Origin: retro of nodocom session `bacdf125` (2026-10-16 → 21), finding #3.

## Problem

`orchestrate-issues` tells its adapter to resolve bindings, bootstrap the run,
read the tracker and the forge, observe recorded worktrees, reserve absent
candidates, build delivery contracts, assemble an interface_version 3 control
request, run `control`, validate the reply, project each dispatch into an owner
object and fetch resume packs. No helper does any of that, so every orchestrated
run writes its own glue.

In the retro session the orchestrator wrote a 48-line `facts.py`, a `step.sh` it
called 75 times, a `build.py` for contracts and a hand-kept `adapter.json`; its
scratch folder ended with 957 files. The glue was wrong in ways the skill
already forbids and nobody could see:

- It persisted built contract pairs to `contracts.json` (the skill: "never
  persist it") and wrote `request.json` (the skill: "no request file is
  written").
- It hard-coded `attempt_budget_minutes: 480`, the repository slug, the root and
  the `GITHUB_TOKEN` unset, instead of reading bindings.
- When a summary asked for a contract it called `control` a second time at once
  and used only the second reply, so any dispatch the first reply reserved was
  never executed.
- It made two REST calls per issue per round (126 for 63 issues) and listed a
  capped 400 pull requests, so an older PR fell silently out of view.
- Iterations failed on the way: a pre-existing candidate worktree tripped an
  assertion, `init-run --issue-set` refused a 63-issue set, response file
  numbering broke, and a `git -C` on a removed path failed.

Each run pays this cost again, on the most expensive model, and each run's glue
can be wrong differently.

## Solution

A new `agent_tools` command, `orchestrate-control`, with two subcommands. The
adapter calls `start` once and `step` once per event (start/resume, each current
owner notification, tracker change or wait wake). Everything that reads only
bindings, the tracker, the forge, git and `workflow-state` moves into the
helper; everything that needs the host's task handles stays in the skill.

**`orchestrate-control start --repo-root <ledger_repo_root> (<n>… | --label X | --milestone Y) [--run-id <id>]`**
asks `host-route --route claude-code`, resolves a label or milestone to its
ordered issue numbers with one tracker call, and bootstraps the run with
`init-run`: `--issue-set` by default, `--run-id` to re-enter a run (the only route for a set too long for the issue-set grammar). It prints a `session`
object the adapter passes back verbatim on every `step`:
`{interface_version: 1, run_id, issues, human_directed, source: {kind, reference}}`.
An `unsupported` host route prints the validated route answer as
`outcome: "unsupported"`, exit 0, and no session.

**`orchestrate-control step --repo-root <ledger_repo_root> --input -`** reads one
JSON object from stdin (a quoted heredoc):

```json
{"session": "<start's session, verbatim>",
 "first_sweep": true,
 "owners": [],
 "contracts_due": [],
 "refused_contracts": []}
```

`owners` are the normalized host owner observations (`unavailable`,
`launch_refused`) the skill already defines; `contracts_due` and
`refused_contracts` are the previous step's outputs, passed back. It then runs,
in order, stopping at the first failure and naming it: `bindings`, `bootstrap`,
`tracker`, `forge`, `worktrees`, `contracts`, `control`, `project`. It makes the
control call, applies the one chaining rule (D6), projects every `spawn`,
`resume` and `retry` action into its interface-2 owner object and every
`delivery_remainder` verbatim, validates each through
`artifact-budget validate-report --boundary workflow-response`, and fetches the
resume pack for each `resume`.

Ready, exit 0, one compact JSON object:

```json
{"command": "step", "outcome": "ready", "run_id": "rel_…",
 "control_calls": 1,
 "response": {"…": "the validated interface_version 3 control response"},
 "dispatches": [{"action_id": "12:1:1", "launch_kind": "spawn", "issue": 12,
                 "worktree": "/abs/…", "handoff_path": null,
                 "owner_object": "<canonical JSON text>", "resume_pack": null}],
 "contracts_due": [14], "contract_refusals": [{"issue": 9, "detail": "…"}],
 "ends_run": false}
```

Refused, exit 2: `{command, outcome: "refused", step, detail, completed_steps,
response}` where `response` is the validated control response when the refusal
came after `control` returned (so the adapter can render it and fail loudly),
else null. `detail` is one line of at most 300 characters.

The skill's §2–§4 shrink to: call `step` with the host facts, run the stop pass
when `dispatches` is non-empty, launch each dispatch with its `owner_object` and
`resume_pack` in the existing owner prompt, record handles, and execute the
`response`'s non-dispatch action (`wait`, `delivery_contract`, `finalize`) as
today. Notification classification, owner liveness, the stop pass, wait arming
and the final report stay in the skill unchanged.

## Decisions

### Placement and shape

`orchestrate-control` is a module of `agent_tools` plus one row in the command
table, a thin shell over importable functions, following `sdd-gate`'s
ready/refused report and fixed step order (D1, D2). It runs `workflow-state`,
`artifact-budget`, `resolve-project`, `git` and `gh` as children by command
name on `PATH`. It writes nothing to disk: built contract pairs, the request and
every reply live only in the process (D3).

### Bindings

`step` resolves the project at `--repo-root` on every call (the control-plane
contract resolves `max_parallel` and `attempt_budget_minutes` "on every
request") and takes from the retained result: `bindings.workflow.orchestration`
for `max_parallel` and `attempt_budget_minutes`; `bindings.tracker` for kind,
CLI and `repo_slug`; `bindings.tracker.credential_env.unset_before_invocation`
as the variables removed from every `gh` child; `bindings.vcs.worktree.{root,prefix}`
against `project.root` for candidate paths. A resolver refusal is step
`bindings` with the resolver's `error.code` in `detail`. Only `kind: github`
is supported; another kind refuses at `tracker` (D7).

### Facts

- **Tracker** — one GraphQL `gh api graphql` call per 100 issues reading each
  issue's `state` and its `blockedBy` (number, state, labels, repository).
  An open blocker labelled `wayfinder:research|prototype|grilling|task` is a
  decision blocker `{issue, url}`; every other open blocker is an
  `open_blockers` number. An open blocker in another repository refuses at
  `tracker` (D8).
- **Forge** — all pull requests of the repository by paginated GraphQL (number,
  head branch, state, url, merge commit), matched by the skill's `issue-<n>-`
  rule on the head branch less any worktree prefix; several matches take the
  highest-numbered. Normalized exactly as the skill's `{state, url, merge_sha}`
  (D9).
- **Worktrees** — `init-run --run-id` gives the bootstrap requirements; one
  `git -C <ledger_repo_root> worktree list --porcelain` is the live set. A
  recorded path is `matching_issue_branch` when it is a live worktree whose
  branch less the prefix starts with `issue-<n>-`, `absent` when it is not on
  the filesystem, else `mismatch`. An issue without a requirement gets the
  candidate `<root>/<prefix>issue-<n>-orchestrated`, then `-2` … `-9`, the
  first that is absent from the filesystem and the live set, disjoint from every
  recorded path and other candidate, and whose branch (with and without the
  prefix) does not exist; none free refuses at `worktrees` (D10).

### Contracts

`step` builds a contract with `workflow-state build-delivery --kind contract`
for: on `first_sweep`, every bootstrap requirement whose `contract_digest` is
null; and every issue in `contracts_due`. It never builds for an issue in
`refused_contracts`. The worktree is the recorded worktree when there is one,
else the candidate. `source_kind`/`source_reference` come from the session
(`explicit_user` + `invocation:/orchestrate-issues <numbers>`, or
`standing_repository` + `sweep:<label|milestone>:<value>`). A builder refusal
sends null and `[]` and is reported in `contract_refusals` with its stderr
line. After control returns, `contracts_due` is every issue whose summary
carries `delivery_contract_required`, less refused ones (D4, D5).

### The control round

The request is the skill's interface_version 3 shape: ordered `issues`, the
facts above, the passed-through `owners`, contracts and intents as above, and
`[]`/null for `authority_observations`, `reevaluation_evidence`,
`delivery_observations`, `requested_scopes`, `recoveries`; `now` omitted. Every
child reply is piped through `validate-report` before any field is read; a
validation failure refuses at the step that made the call.

Chaining (D6): when a reply's only action is `delivery_contract` and at least
one listed issue was built in this call or can be built now, `step` makes
exactly one further control call carrying those contracts and reports that
reply; otherwise it reports the first. When every issue a `delivery_contract`
action lists is refused, `ends_run` is true and the adapter ends the run as
for `finalize`. A reply with any dispatch action is never followed by a second
call.

### Projection

Owner objects are projected exactly as §4 states (rename `id`→`action_id`,
`kind`→`launch_kind`, add `kind: owner`, `interface_version: 2`,
`ledger_repo_root`, `run_id`, keep every other member) and carried as the
validator's canonical stdout text. A `delivery_remainder` object is the action
verbatim. `resume-pack` stdout is carried as text and never decoded; its
failure leaves `resume_pack` null and never refuses. A projection or
validation failure refuses at `project` with the response attached.

### Trust boundary

The helper is first-party and validates every `workflow-state` reply at the
`workflow-response` boundary itself; the adapter parses `step`'s stdout as it
parses `sdd-gate`'s, and owners still validate their `owner_object` on receipt
(D2).

### Skill

`orchestrate-issues` (Claude Code) replaces the §1 resolution, the §2 bootstrap
and observation paragraphs, the §3 request template and contract rule, and the
§4 projection paragraph with the two calls and the `step` I/O above. The
notification rules (a)–(d), the stop pass, wait/finalize handling, owner prompt
and final report stay. The Codex stub is unchanged. `python/README.md` gains an
`orchestrate-control` section holding the command contract.

## Test seams

1. **Command contract from source** — `python -m agent_tools.orchestrate_control`
   under the recipe `PYTHONPATH`, against a real temporary git repository with
   a resolvable `.agents/project.json`, real `workflow-state`, `artifact-budget`
   and `resolve-project` from source, and a fake `gh` that answers from
   registered responses, logs argv and fails when a variable named by
   `credential_env.unset_before_invocation` is visible. Prior art:
   `tests/test_sdd_gate.py` (real `workflow-state` beside the command) and
   `tests/forge_world.py` (logged fake `gh` that refuses a leaked token).
   Covers each step's refusal, candidate collision, recorded-worktree states,
   decision vs open blockers, forge matching, contract first-sweep/due/refused,
   the chaining rule (including the "dispatch reply is never chained" case) and
   projection.
2. **Adapter replay** — `home/common/agent-skills/tests/test_admission_replay.py`
   drives its simulated adapter through `orchestrate-control step` instead of
   hand-built requests, keeping its admission assertions.
3. **Installed layout and skill text** — the launcher row in
   `tests/test_agent_tools_launchers.py`; `skill-lint`,
   `test_shell_example_contracts` (the new shell examples), the dispatch
   contracts and `orchestrate-issues/evals`.

## Out of scope

- The stray `GITHUB_TOKEN` export and the lifecycle guard's env-prefix and
  grammar messages (sibling retro findings #1, #2). The helper only honours the
  binding's declared unset list.
- Rendering the owner dispatch prompt into a file (the `sdd-gate` brief pattern);
  the prompt stays in the skill.
- Moving `workflow-state` into the package (#178) or adding subcommands to it.
- Automating the stop pass, owner liveness, notification classification or wait
  arming: they need host task handles.
- Adding issues to a running set (the retro's hand-kept decomposition map), a
  non-GitHub tracker, and Codex orchestration.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A new `agent_tools` command `orchestrate-control` (`start`, `step`), not a `workflow-state` subcommand. | `docs/standards/agent-helpers.md` rules 1–2: new helper code is a package module plus a command-table row; #178 is moving `workflow-state` out of the flat script. | `workflow-state gather-facts`/`step` — grows the legacy script #178 is emptying and mixes tracker/forge I/O into the ledger engine, which by design "does not know how GitHub represents edges". |
| D2 | Reports follow `sdd-gate`: fixed step order, first failure named, ready exit 0 / refused exit 2; the helper validates child replies itself and no new `artifact-budget` boundary is added. | #353's `sdd-gate` contract in `python/README.md`; the skill's validate-before-decode rule applies to the `workflow-state` wire, which the helper now owns. | A new `validate-report` boundary for the step report — a schema to maintain for a first-party, same-store helper whose payloads are already validated. |
| D3 | Nothing is written to disk; contract pairs, request and replies are process-local. | Skill §3: "The built pair is process-local request data: never persist it"; "No request file is written". | Caching contracts or responses between steps (what the retro's glue did) — the forbidden persistence. |
| D4 | Adapter-carried state is only `session`, `owners`, `contracts_due` and `refused_contracts`, passed back on stdin. | Owner observations need host handles; "send null until its latest summary carries `delivery_contract_required`" needs the last summary, which the adapter may not read from the ledger. | The helper reading the previous summary from the ledger — the adapter boundary forbids raw ledger reads; or rebuilding every round — violates "never rebuild an issue whose build this invocation refused". |
| D5 | `step` re-resolves bindings on every call; the session carries no bindings. | Control-plane design: `max_parallel`/`attempt_budget_minutes` are "resolved by the caller from the authoritative project bindings on every request". | Carry bindings in the session — adapter-mutable policy, and drift from the retro's hard-coded 480-minute budget. |
| D6 | Chain one extra control call only when the reply's sole action is `delivery_contract`; never after a reply with a dispatch. | Skill §4: on `delivery_contract` "make the next control call at once; that response takes over". The retro's always-chain lost reserved dispatches. | Always re-call when a summary wants a contract — drops the first reply's dispatches; or never chain — one extra adapter turn per contract round for no safety gain. |
| D7 | GitHub only; another tracker kind refuses at `tracker`. | The only bound tracker kind in practice; YAGNI. | A pluggable tracker adapter — no second consumer. |
| D8 | Decision blockers are open blockers labelled `wayfinder:research|prototype|grilling|task`; a cross-repo open blocker refuses. | Control-plane design: decision blockers are open `wayfinder:*` decisions with their URL; `wayfind` names the four decision ticket types (`map`, `slice` are not decisions). | Sending `[]` always (the retro) — fogged readiness never fires; numbering a cross-repo blocker — ambiguous and silently wrong. |
| D9 | Forge read lists every PR by paginated GraphQL and takes the highest-numbered match. | The skill's `issue-<n>-` prefix rule needs prefix matching, which the PR filter APIs do not offer by exact branch; a capped list silently drops PRs. | `gh pr list --limit 400` (the retro) — silent truncation; GitHub search `head:` — prefix semantics unverified. |
| D10 | Candidate collision moves to `-2`…`-9` suffixes and also excludes existing branches; exhaustion refuses. | Skill §2: candidates must be absent, pairwise distinct and a branch the pattern accepts; the retro asserted on a leftover `worktree-issue-2066-orchestrated`. | Asserting absence — stops the run on harmless leftovers; reusing the leftover — not an absent candidate. |
