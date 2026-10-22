# `orchestrate-control`: the adapter's fact gathering and control round as one helper call

Origin: retro of nodocom session `bacdf125` (2026-10-16 → 21), finding #3. Tracker: #403.

## Triage

input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a new public agent_tools command orchestrate-control with start/step JSON I/O contracts and a lib/agent-tools.nix command row"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "the helper writes nothing to disk but drives workflow-state init-run/control/build-delivery, which reserve dispatches in the persisted run ledger"}, "open_design_questions": {"value": "no", "evidence": "issue carries decisions D1-D10 from an existing design spec on local branch worktree-retro-orch-facts"}, "criteria_shape": {"value": "hit", "evidence": "nine acceptance criteria, over the four-criterion threshold"}}, "paths": ["python/agent_tools/orchestrate_control.py", "lib/agent-tools.nix", "tests/test_orchestrate_control.py", "tests/test_agent_tools_launchers.py", "python/README.md", ".agents/artifacts/specs/2026-10-21-orchestrate-control-facts-design.md"]}
verdict: {"hits":["contract_change","concurrency_or_persistence","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

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
helper; everything that needs the host's task handles stays in the adapter.
This change delivers the helper and its contract; teaching the skill to call it
is a follow-up (D11).

**`orchestrate-control start --repo-root <ledger_repo_root> (<n>… | --label X | --milestone Y) [--run-id <id>]`**
runs four steps in order — `bindings`, `route`, `issues`, `bootstrap` — and
stops at the first failure (D15). It resolves the project, asks
`host-route --route claude-code`, takes the explicit numbers in the caller's
order or resolves a label or milestone with one tracker call (D16), and
bootstraps with `init-run --issue-set`, or with `--run-id` to re-enter an
existing run (D14). It prints:

```json
{"command": "start", "outcome": "ready",
 "session": {"interface_version": 1, "run_id": "rel_…", "issues": [12, 14],
             "human_directed": true,
             "source": {"kind": "explicit_user",
                        "reference": "invocation:/orchestrate-issues 12 14"}}}
```

A label or milestone gives `human_directed: false` and
`{"kind": "standing_repository", "reference": "sweep:<label|milestone>:<value>"}`.
An `unsupported` route answer prints
`{"command": "start", "outcome": "unsupported", "route": <the validated host_route answer>}`,
exits 0, and bootstraps nothing.

**`orchestrate-control step --repo-root <ledger_repo_root> --input -`** reads one
JSON object from stdin (a quoted heredoc):

```json
{"session": {"…": "start's session, verbatim"},
 "first_sweep": true,
 "owners": [],
 "contracts_due": [],
 "refused_contracts": []}
```

`owners` are the host's normalized `{event_id, issue, custody, state}` owner
observations (`unavailable`, `launch_refused`), passed through unchanged;
`contracts_due` and `refused_contracts` are the previous step's outputs of the
same names, passed back verbatim (D17). The session must have exactly the
shape `start` prints and every list must name only session issues, or the call
is an invalid invocation. It then runs, in order, stopping at the
first failure and naming it: `bindings`, `bootstrap`, `tracker`, `forge`,
`worktrees`, `contracts`, `control`, `project`.

Ready, exit 0, one compact JSON object:

```json
{"command": "step", "outcome": "ready", "run_id": "rel_…",
 "control_calls": 1,
 "response": {"…": "the validated interface_version 3 control response"},
 "dispatches": [{"action_id": "12:1:1", "launch_kind": "spawn", "issue": 12,
                 "attempt": 1, "owner": "12:1",
                 "worktree": "/abs/.worktrees/worktree-issue-12-orchestrated",
                 "handoff_path": null,
                 "owner_object": "<canonical JSON text>", "resume_pack": null}],
 "contracts_due": [14], "refused_contracts": [9],
 "contract_refusals": [{"issue": 9, "detail": "workflow-state: build-delivery refused: …"}],
 "ends_run": false}
```

Refused, exit 2, for either subcommand:
`{command, outcome: "refused", step, detail, completed_steps, response}`.
`detail` is one line of at most 300 characters; `response` is the latest
validated control response when the refusal came after a `control` call
returned (so the adapter can render it and fail loudly), else null (always null
for `start`). An argv or stdin that does not fit the contract prints
`orchestrate-control: invalid invocation` on stderr, nothing on stdout, and
exits 2.

After this change the adapter's §2–§4 reduce to: call `step` with the host
facts, run the stop pass when `dispatches` is non-empty, launch each dispatch
with its envelope fields, `owner_object` and `resume_pack` in the existing owner
prompt, record handles, and execute the `response`'s non-dispatch action
(`wait`, `delivery_contract` via another `step` unless `ends_run`, `finalize`).
Notification classification, owner liveness, the stop pass, wait arming and the
final report stay in the adapter unchanged.

## Decisions

### Placement and shape

`orchestrate-control` is a module of `agent_tools` plus one row in the command
table, a thin shell over importable functions, following `sdd-gate`'s
ready/refused report and fixed step order (D1, D2). It resolves the project in
process through the resolver module (D12) and runs `workflow-state`,
`artifact-budget`, `git` and the bound tracker CLI as children by command name on
`PATH`. The helper writes no file: built contract pairs, the request and every
reply live only in the process (D3); the only writes a call causes are
`workflow-state`'s own ledger writes (D22). `--repo-root` must be absolute.
One adapter process calls `step` serially per run; the helper takes no lock
(D25).

### Bindings

Both subcommands resolve the project at `--repo-root` (`step` on every call,
D5) and take from the retained result: `bindings.workflow.orchestration` for
`max_parallel` and `attempt_budget_minutes`; `bindings.tracker` for `kind`, `cli`
and `repo_slug`; `bindings.tracker.credential_env.unset_before_invocation` as the
variables removed from every tracker-CLI child's environment;
`bindings.vcs.worktree.{root,prefix}`, with `root` joined to `project.root`,
for candidate paths. A missing binding refuses at `bindings`, never
defaulted. A resolver refusal is step `bindings` with the resolver's
`error.code` and `repair_id` in `detail`. Only `kind: github` is supported;
another kind refuses at the first step that calls the tracker (`issues` for a
`start` sweep, `tracker` for `step`) (D7).

### Start

- `issues`: explicit numbers must be unique positive integers and keep their
  order. A label or milestone is one `gh issue list` call (D16). An empty set
  refuses.
- `bootstrap`: without `--run-id`, `init-run --issue-set <numbers joined by ->`;
  with it, `init-run --run-id <id>`. A set too long for the issue-set caller
  key refuses here with the helper's stderr line (D14).
- Every `workflow-state` reply — the `host_route` answer and the
  `workflow_bootstrap` — passes `artifact-budget validate-report --boundary
  workflow-response` before any field is read (D13).

### Facts

- **Bootstrap** — `init-run --run-id <session.run_id>`, validated; a `run_id`
  that differs from the session's refuses. Requirements for issues outside
  `session.issues` are not observed or built for, but their recorded paths
  still exclude candidates (D19).
- **Tracker** — one `gh api graphql` call per 100 issues reading each issue's
  `state` and its `blockedBy` (number, state, url, labels, repository), with
  fixed page sizes (D20). An open blocker labelled
  `wayfinder:research|prototype|grilling|task` is a decision blocker
  `{issue, url}`; every other open blocker is an `open_blockers` number; closed
  blockers are dropped. An open blocker whose repository differs from
  `repo_slug` (compared case-insensitively) refuses at `tracker` (D8).
- **Forge** — one `gh api graphql --paginate --slurp` call listing every pull
  request (number, head branch, `isCrossRepository`, state, url, merge
  commit); only same-repository pull requests match (D24), by the
  `issue-<n>-` rule on the head branch less any worktree prefix; several
  matches take the highest-numbered. Normalized exactly as
  `{state: none|open|closed|merged, url, merge_sha}`, `url` null only for
  `none`, `merge_sha` present exactly when `merged` (D9).
- **Worktrees** — one `git -C <ledger_repo_root> worktree list --porcelain`
  and one `git -C <ledger_repo_root> for-each-ref refs/heads` (D21). A recorded
  path is `matching_issue_branch` when it is a live worktree whose branch less
  the prefix starts with `issue-<n>-`, `absent` when nothing exists at the
  path, else `mismatch`; its observation is `{issue, recorded, candidate: null}`.
  An issue without a requirement gets `{issue, recorded: null, candidate:
  {path, state: "absent"}}` with the candidate
  `<root>/<prefix>issue-<n>-orchestrated`, then `-2` … `-9`: the first absent
  from the filesystem and the live set, disjoint from every recorded path and
  other candidate, and whose branch (the final component, with and without the
  prefix) does not exist; none free refuses at `worktrees` (D10).

### Contracts

`step` builds with `workflow-state build-delivery --repo-root <ledger_repo_root>
--kind contract --input -` for: on `first_sweep`, every in-session bootstrap
requirement whose `contract_digest` is null; and every issue in
`contracts_due`. It builds each issue at most once per call and never for an
issue in `refused_contracts`. The input
is `{issue, worktree, source_kind, source_reference}`: the recorded worktree
when there is one, else the candidate; source from the session. Exit 0 with a
strictly parsed `{contract, initial_intent}` object sends `contract` and
`[initial_intent]`; exit 2 with empty stdout is a builder refusal: null and
`[]`, an entry in `contract_refusals` with the builder's stderr line, and the
issue joins `refused_contracts`. Any other builder outcome refuses at
`contracts` (D13).

### The control round

The request is the interface_version 3 shape: `host_route: "claude-code"`, the
bound `max_parallel` and `attempt_budget_minutes`, the session's
`human_directed` and ordered `issues`, the facts above, the passed-through
`owners`, contracts and intents as above, and `[]`/null for every issue's
`authority_observations`, `reevaluation_evidence`, `delivery_observations`,
`requested_scopes` and `recoveries`; `now` omitted. It goes to
`workflow-state control --repo-root <ledger_repo_root> --run-id <run_id>
--request-file -` on stdin. Every reply passes `validate-report` before any
field is read; a non-zero exit or a validation failure refuses at `control`.

Chaining (D6, D18): when the reply's only action is `delivery_contract`,
`step` builds each listed issue not yet built in this call and not refused;
if at least one listed issue then has a pair, it makes exactly one further
control call and reports that reply (`control_calls: 2`), else it reports the
first. The chained request repeats the facts, sends `owners: []`, and carries a
pair for every issue whose first-reply summary carries
`delivery_contract_required` and has one. A reply with any dispatch action is
never followed by a second call.

Outputs: `contracts_due` is every issue whose reported summary has a
`requirements` entry with `reason_code: "delivery_contract_required"`, less
`refused_contracts`. `refused_contracts` is the input list plus this step's
refusals, ascending. `ends_run` is true exactly when the reported reply's only
action is `delivery_contract` and every issue it lists is in
`refused_contracts`; the adapter then ends the run as for `finalize`.

### Projection

Actions are read in returned order against the closed set `spawn`, `resume`,
`retry`, `delivery_remainder`, `delivery_contract`, `wait`, `finalize`; any
other kind refuses at `project` (D23). `spawn`, `resume` and `retry` become the
interface-2 owner object exactly as the skill's §4 states (rename
`id`→`action_id`, `kind`→`launch_kind`, add `kind: owner`,
`interface_version: 2`, `ledger_repo_root`, `run_id`, keep every other member);
a `delivery_remainder` object is the action verbatim. Each object passes
`validate-report`, and its stdout, decoded and without the trailing newline, is
the `owner_object` text. The dispatch entry carries the envelope (D17): for an
owner, the action's id, kind, issue, attempt, owner, worktree and handoff path;
for a remainder, its custody's `action_id`, `launch_kind:
"delivery_remainder"`, `attempt` = `source_attempt`, and `handoff_path: null`.
For each `resume`, `workflow-state resume-pack --repo-root <ledger_repo_root>
--run-id <run_id> --action-id <id>` stdout is carried as text and never
decoded; a non-zero exit leaves `resume_pack` null and never refuses. Any other
projection or validation failure refuses at `project` with the response
attached, and no partial `dispatches` list is printed.

### Trust boundary

The helper is first-party and validates every `workflow-state` reply that is a
workflow response at that boundary itself (D13); the adapter parses `step`'s
stdout as it parses `sdd-gate`'s, and owners still validate their
`owner_object` on receipt (D2).

## Test seams

1. **Command contract from source** — `python -m agent_tools.orchestrate_control`
   under the recipe `PYTHONPATH`, against a real temporary git repository with
   a resolvable `.agents/project.json` (declaring a credential variable in
   `unset_before_invocation`) and a host-route declaration, real
   `workflow-state` and `artifact-budget` from source as `PATH` shims, and a
   fake `gh` that answers by subcommand, logs argv, and exits non-zero when a
   variable named by `unset_before_invocation` is visible. Prior art:
   `tests/test_sdd_gate.py` (real `workflow-state` beside the command, the
   lifecycle harness) and `tests/forge_world.py` (logged fake `gh` that
   refuses a leaked token). Covers every AC of #403: each step's refusal with
   `completed_steps` and the response attached after `control`; candidate
   collision and exhaustion; the three recorded-worktree states; decision vs
   open vs cross-repo blockers; the one-call-per-100 tracker reads and the
   paginated forge listing; contract first-sweep/due/refused and
   `contract_refusals`; chaining (`control_calls: 2`, never after a dispatch,
   `ends_run`); projection validated and resume-pack text or null; and a
   snapshot of the ledger root and working directory, less the
   `.superpowers/` ledger store, unchanged by the call (D22).
2. **Installed layout** — the launcher row in
   `tests/test_agent_tools_launchers.py` (`LAUNCHER_FLOOR`), run by
   `just agent-installed-skill-tests`, which builds first; the new suite joins
   `just agent-workflow-tests`.

## Out of scope

- Rewriting `orchestrate-issues` (Claude Code) §1–§4 to call the helper, and
  driving `home/common/agent-skills/tests/test_admission_replay.py` through
  `step`: a follow-up issue (D11).
- A `start --creation-key` route for a set too long for the issue-set key
  (D14).
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
| D7 | GitHub only; another tracker kind refuses at the first tracker step. | The only bound tracker kind in practice; YAGNI. | A pluggable tracker adapter — no second consumer. |
| D8 | Decision blockers are open blockers labelled `wayfinder:research|prototype|grilling|task`; a cross-repo open blocker refuses. | Control-plane design: decision blockers are open `wayfinder:*` decisions with their URL; `wayfind` names the four decision ticket types (`map`, `slice` are not decisions). | Sending `[]` always (the retro) — fogged readiness never fires; numbering a cross-repo blocker — ambiguous and silently wrong. |
| D9 | Forge read lists every PR by paginated GraphQL and takes the highest-numbered match. | The skill's `issue-<n>-` prefix rule needs prefix matching, which the PR filter APIs do not offer by exact branch; a capped list silently drops PRs. | `gh pr list --limit 400` (the retro) — silent truncation; GitHub search `head:` — prefix semantics unverified. |
| D10 | Candidate collision moves to `-2`…`-9` suffixes and also excludes existing branches; exhaustion refuses. | Skill §2: candidates must be absent, pairwise distinct and a branch the pattern accepts; the retro asserted on a leftover `worktree-issue-2066-orchestrated`. | Asserting absence — stops the run on harmless leftovers; reusing the leftover — not an absent candidate. |
| D11 | Scope is the helper, its suite, the command-table and launcher-test rows and the `python/README.md` contract; the skill rewrite and the admission-replay seam move to a follow-up issue. | #403's "What to build" and all nine ACs name only the helper; the replay test injects control `now` per simulated minute, which `step` omits; a skill rewrite pulls in skill-lint, shell-example contracts, evals and the Instruction Budget gate. | Rewriting §1–§4 in the same change — doubles the review surface and ships skill text that no AC measures. |
| D12 | The project is resolved in process with `agent_tools.resolve_project.resolve`, not by running `resolve-project`. | `agent-helpers.md` rule 3: a packaged sibling is imported or run through `sibling_argv`, never by name; precedent `guard_policy.resolver`. | A `resolve-project` child on `PATH` (the adopted spec's wording) — breaks rule 3 and costs a process per step. |
| D13 | Only workflow responses (`host_route`, `workflow_bootstrap`, control replies, projected owner and remainder objects) pass `validate-report`; `build-delivery` output is strictly parsed and shape-checked and control validates the contract on receipt; builder exit 2 with empty stdout is a refusal, any other failure refuses at `contracts`. | The delivery model's `workflow-response` boundary has no kind for `{contract, initial_intent}` and rejects it; skill §3 names exit 2 with empty stdout as the refusal; skill §4 exempts `resume-pack`. | Piping builder output through `workflow-response` (the issue's "every child reply") — it always fails; treating every non-zero builder exit as a refusal — hides a crashed builder. |
| D14 | `--run-id` only re-enters an existing run; a fresh set whose issue-set key exceeds the caller-key grammar refuses at `bootstrap`, and `python/README.md` names minting it with `workflow-state init-run --creation-key` then `start --run-id`. Corrects the issue's "`--run-id` is the route for a set too long". | `init-run --run-id` "never creates one"; `issue-set:<numbers>:<k>` is bounded at 128 characters by the caller-key grammar (#337). | A `start --creation-key` flag — no AC asks for it (follow-up); a helper-derived digest key — run identity grammar belongs to `attempt_identity`. |
| D15 | `start` runs `bindings`, `route`, `issues`, `bootstrap`; both subcommands share one refusal key set (`response` null for `start`); a malformed argv or stdin is `orchestrate-control: invalid invocation`, exit 2, empty stdout. | Skill §1: resolve at phase entry, fatal before mutation; `sdd-gate` keeps one refusal shape and one invalid-invocation line across subcommands. | Skipping resolution for explicit numbers — `init-run` would write before the project is validated; refusal objects for stdin shape errors — caller bugs are invocation errors in `sdd-gate`. |
| D16 | A label or milestone resolves with one `gh issue list --state open --json number --limit 1000`, ordered by ascending number; a result of exactly 1000 or of none refuses at `issues`. | Skill §1: one configured tracker-list call; `gh` resolves a milestone title itself; D9's rule against silent truncation. | A GraphQL search — capped at 1000 and eventually consistent; newest-first order — reverses the dispatch order between sweeps as issues are added. |
| D17 | `step` outputs `refused_contracts` (input plus this step's refusals) beside `contract_refusals`, and each dispatch carries the full owner envelope (`attempt`, `owner` included; a remainder maps `source_attempt` and its custody's `action_id`). | The issue makes the inputs "the previous step's outputs" but listed no `refused_contracts` output; skill §4's envelope needs `attempt` and `owner`, and a remainder has no `id`. | The adapter merging refusal lists or decoding `owner_object` text for the envelope — adapter glue this helper exists to remove. |
| D18 | The chained call sends `owners: []`, repeats the facts, and carries a pair for every issue whose first-reply summary still asks for one; the response attached to a refusal is the latest validated reply. | Skill §4: a `launch_refused` observation travels in exactly one control call, and the first call consumed the observations; skill §3 sends a pair only while its summary carries `delivery_contract_required`. | Resending `owners` — applies an observation twice; sending only the listed issues' pairs — drops a pair another summary still asks for. |
| D19 | Bootstrap requirements for issues outside `session.issues` are not observed or built for, but their recorded paths still exclude candidates. | Bootstrap lists every undelivered ledger issue, while control's issue-keyed maps must equal the requested issues; skill §2: candidates are disjoint from every returned durable path. | Refusing the step — breaks re-entering a run with a subset; dropping their paths — a candidate could collide with another issue's worktree. |
| D20 | The tracker query pages `blockedBy(first: 50)` and `labels(first: 25)`; a `hasNextPage`, a missing issue or a pull-request number refuses at `tracker`. | GitHub's 500,000-node limit per GraphQL call bounds 100 issues × blockers × labels; D9's rule against silent truncation. | 100 × 100 pages — 1,000,000 nodes, refused by GitHub; ignoring `hasNextPage` — a blocker silently disappears. |
| D21 | Worktree facts take one porcelain worktree list and one `for-each-ref refs/heads` in the ledger root; paths compare after `realpath`. | D10 needs branch existence for each candidate; the retro's per-path `git -C` on a removed path failed. | A git call per candidate — unbounded children and the retro's failure mode; raw string comparison — macOS `/private` aliases mismatch. |
| D22 | The helper creates no file; `init-run` and `control`'s ledger writes under `.superpowers/` are the only writes, so AC8's snapshot excludes that store; a refusal after `control` reserved dispatches leaves them to the ledger's deadline expiry while the adapter fails loudly. | D3; `control` and `init-run` commit their ledger by design; `demote_expired_attempt` reaps an attempt past its deadline into a resumable suspension. | Snapshotting `.superpowers/` too — fails on the ledger writes every round makes; undoing a reservation — the helper may not write the ledger. |
| D23 | `project` checks every action kind against the closed set and refuses on any other, all-or-nothing. | Skill §4: any other kind "is a contract error … fail loudly"; the bar's fail-loud rule at closed-set dispatch. | Skipping unknown kinds — a new dispatch kind would be silently dropped. |
| D24 | The forge read matches only pull requests whose head is in the bound repository (`isCrossRepository: false`). | Control writes a reconciled `merged` forge observation into the ledger permanently; an owner pushes its issue branch to the bound repository. | Matching fork pull requests by branch name too — a fork's `issue-<n>-…` branch could close an issue's delivery for good. |
| D25 | The helper holds no lock and assumes one serial `step` caller per run; `control`'s ledger transaction remains the only serialization. | Skill §2–§3: one adapter process drives a run and refreshes facts per event; D3 forbids helper state on disk. | A helper-side lock file around candidate reservation — a disk write D3 forbids, guarding a caller pattern the adapter never has. |
| D26 | The suite builds its own world, `tests/orchestrate_world.py`: real `git`; a fixture project made from this repository's contract with `unset_before_invocation` set to `GITHUB_TOKEN` and `GH_TOKEN`; logging `PATH` shims that run the source `workflow-state` and `artifact-budget` unless a per-test fault rule answers; and a fake `gh` that answers `issue list` and the two GraphQL query shapes from world data. Fault rules cover only outcomes the real children cannot be driven to: a builder refusal or crash for one issue, a failing `init-run`, `host-route`, `control` or `resume-pack`, a doctored bootstrap with a null digest, and validator pass-through for a canned reply carrying an unknown kind or a remainder. A resume and the recorded-worktree states come from a spawn the world seeds through `workflow-state` directly. | Seam 1 names a fake `gh` that answers by subcommand and the real children; `tests/test_sdd_gate.py`'s forced budget shim is the fault precedent; the builder and the resolver need a resolvable project. | `ForgeWorld` — an exact-argv registry with a fake `git`, it cannot answer an aliased GraphQL query or run real worktrees; `LifecycleHarness` — its root has no resolvable project, so `build-delivery --kind contract` and the in-process resolver refuse. |
| D27 | The GitHub wire is pinned: per chunk of at most 100 issues, `<cli> api graphql -f query=<Q> -f owner=<o> -f name=<n>`, where `Q` aliases each issue as `i<n>: issueOrPullRequest(number: <n>)` and `__typename` must be `Issue`; the forge read is `<cli> api graphql --paginate --slurp` over `pullRequests(first: 100, after: $endCursor)`, and its last page must report `hasNextPage: false`; a sweep is `<cli> issue list --repo <repo_slug> …`. `open_blockers` and `decision_blockers` are ascending by number. | D8, D9, D16, D20; GraphQL cannot loop over a list of issue numbers, so aliases are the one-call form; `--repo` binds the bound slug whatever the working directory's remote is. | Per-issue REST dependency reads (the retro's two calls per issue); a sweep that trusts the working directory's git remote. |
| D28 | A failure in the chained phase (a builder crash for a listed issue, or a second `control` call that fails or does not validate) refuses at `control` with the first validated reply attached; only builds made before the first call refuse at `contracts`. A step name never appears in `completed_steps` after the step that refused. Amends the spec's "any other builder outcome refuses at `contracts`" for the chained builds. | D6, D18: chaining is part of the control round; `sdd-gate` names the step that was running. | Refusing at `contracts` after `control` completed — `completed_steps` would end in `control` while the refusal names an earlier step. |
| D29 | Interface details the spec left open: an owner object's and dispatch's `ledger_repo_root` is `--repo-root` exactly as given; `contract_refusals[].detail` is the builder's stderr line verbatim less its newline (not capped); duplicate explicit numbers refuse at `issues`, while a numeral that is not a positive integer, a relative `--repo-root`, numbers mixed with `--label`/`--milestone`, or `--input` other than `-` is an invalid invocation; `owners` entries are only checked to be objects with an integer `issue` in the session, and `control` validates the rest. | Skill §1: `ledger_repo_root` is the run's exact immutable value; skill §3 reports the builder's line verbatim; D15 keeps argv and stdin shape errors invocation errors. | Realpathing the root — a second spelling of the run's root; truncating the builder line — the final report loses the refusal reason. |
