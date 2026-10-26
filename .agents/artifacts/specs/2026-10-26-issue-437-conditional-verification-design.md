# Path-conditional verification: skip the agent workflow tests when no agent tooling changed — issue 437

Design for https://github.com/fagenorn/nix-config/issues/437. Base: `ca6ba1ae`.
A bare "Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a path-condition member to the project contract's workflow.verification declaration and to the resolved snapshot the resolver returns"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "the verified-tree record persisted in the git dir may need to carry skipped commands, changing a persisted schema"}, "open_design_questions": {"value": "hit", "evidence": "the declaration shape, how the changed-path set is computed, and how a skip is recorded and reported are all open"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria, one of them a human review of the path list"}}, "paths": [".agents/project.json", "python/agent_tools/resolve_project.py", "python/agent_tools/verified_tree.py", "home/common/agent-skills/tests/test_resolve_project.py", "tests/test_verified_tree.py", "home/common/agent-skills/skills/ship-issue/SKILL.md", "home/common/agent-skills/skills/sdd/final-review.md", "python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Local verification runs every id in `bindings.workflow.verification` on every
change: sdd's final review **Final verification** step and ship-issue's
**Phase 2 — Verify locally**, both gated by `verified-tree check`/`record`.
This repository declares `nix-build` and `agent-workflow-tests`, so a change
that edits only a nix-darwin host module pays the whole agent workflow suite
even though nothing that suite reads changed.

The owner wants the project contract to say that a verification command runs
only when the change touches its listed paths, and that otherwise verification
reports it as **skipped, with its reason** ("no agent-tooling paths changed"),
never as passed. `nix-build` stays unconditional. The resolver validates the
declaration and returns it in the resolved snapshot; consumers read the
condition from the resolved project and never infer it. CI is unchanged.

## Solution

1. **Contract.** `resolve-project` accepts one new optional member,
   `bindings.workflow.verification_conditions`: a map from a verification id to
   `{"when_changed": [<glob>, ...], "skip_reason": "<text>"}`. The
   `verification` list itself is untouched, so every existing reader of it keeps
   working (D1, D9). The resolver validates the member with named violations
   (D2) and returns it as authored.
2. **Plan.** `verified-tree` resolves the worktree's project itself, computes
   the change as the paths that differ between the merge base with
   `origin/<integration_branch>` and the tree it verifies (D4), and partitions
   the declared ids into `run` and `skipped` (D3, D6). `check` prints that plan
   beside `status` and `tree`; `record` writes only the ids that ran. A skipped
   id never enters the record, so a skip can never read as a pass.
3. **Consumers.** sdd's Final verification and ship-issue's Phase 2 run exactly
   the `run` ids and write each skip, with its reason, into their own
   persistent record: the SDD ledger line and the PR body's Summary (D7).
4. **This repository.** The spec proposes the gated path list
   (§ Proposed gated paths) for the owner to approve in the PR. The member is
   authored in `.agents/project.json` by a follow-up commit after `just switch`,
   because the installed resolver refuses an unknown member (D10).

## Decisions

### Contract grammar (D1, D2)

Authored shape, inside `bindings.workflow`:

```json
"verification": ["nix-build", "agent-workflow-tests"],
"verification_conditions": {
  "agent-workflow-tests": {
    "when_changed": ["python/*", "tests/*", "justfile"],
    "skip_reason": "no agent-tooling paths changed"
  }
}
```

- `verification_conditions` joins `light_lane` in the optional-member set of
  `bindings.workflow`. Absent or `null` means no id is conditional; `{}` is
  accepted and means the same. An id with no key is unconditional.
- Every key must be an id listed in `workflow.verification`.
- Each value is an object with exactly the members `when_changed` and
  `skip_reason`, both required.
- `when_changed` is a non-empty list. Each entry passes the existing `risk_paths`
  rules unchanged: a safe repository-relative path (non-empty, no leading `/`,
  no `..` segment) spelled canonically (`/`-separated, no backslash, no empty
  or `.` segment, no trailing `/`). Glob metacharacters are allowed.
- `skip_reason` is a non-empty string, reported verbatim. No default exists.
- At least one id in a non-empty `workflow.verification` list has no
  condition, so a verified tree has always run at least one command.

Refusals use the existing collected-violation machinery (one
`invalid_contract`, violations ordered by pointer, the first one's repair id
published). Pointers are rooted at `/bindings/workflow/verification_conditions`:

| Case | Pointer suffix | Repair id |
|---|---|---|
| member not an object (and not `null`) | (none) | `contract.workflow.not_object` (existing) |
| key names no `workflow.verification` id | `/<id>` | `contract.workflow.unknown_verification_id` (new) |
| condition value not an object | `/<id>` | `contract.workflow.not_object` (existing) |
| `when_changed` or `skip_reason` absent | `/<id>/<member>` | `contract.workflow.member_missing` (existing) |
| any other key in a condition (the issue's "unknown key") | `/<id>/<key>` | `contract.workflow.member_unexpected` (existing) |
| `when_changed` not a list | `/<id>/when_changed` | `contract.workflow.not_list` (existing) |
| `when_changed` empty (the issue's "empty path list") | `/<id>/when_changed` | `contract.workflow.empty_path_list` (new) |
| entry absolute, `..`, empty or not a string (the issue's "absolute path") | `/<id>/when_changed/<n>` | `contract.workflow.unsafe_path` (existing) |
| entry safe but non-canonical | `/<id>/when_changed/<n>` | `contract.workflow.noncanonical_path` (existing) |
| `skip_reason` not a non-empty string | `/<id>/skip_reason` | `contract.workflow.not_string` (existing) |
| every verification id has a condition | (none) | `contract.workflow.no_unconditional_verification` (new) |

The two `when_changed` entry rules are the same predicates `risk_paths` uses
(`check_safe_path`, `is_canonical_path`, `CANONICAL_PATH_MESSAGE`), never a copy.
Pointer segments are not JSON-pointer-escaped, which matches how the resolver
already spells command-id pointers.

### Resolved snapshot (D1)

`bindings.workflow.verification_conditions` is passed through byte-for-byte as
authored. Absent stays absent, `null` stays `null`. `when_changed` globs stay
repository-relative and are never made absolute: bootstrap rewrites only
`paths` members and command `cwd`s. There is no schema bump, the platform
manifest is unchanged and no capability is added. Readiness of the
`verification` capability is unchanged: it still requires every declared
id's `argv[0]` to resolve, the conditional ones included, because they may run.

### The change and the matching rule (D3, D4)

- **Base:** `git merge-base HEAD refs/remotes/origin/<bindings.vcs.integration_branch>`.
  The remote is `origin`, as everywhere else in the lifecycle (ship's sync and
  `review-range`).
- **Tree:** the tree `verified-tree` already computes: the index's entries with
  tracked working-tree edits applied, untracked files excluded.
- **Changed paths:** the names `git diff-tree -r --no-renames --name-only -z
  <base> <tree>` prints. A rename counts as both its old and its new path, and
  a deleted file counts. Paths come out repository-relative and canonical.
- **Match:** a conditional id runs when any changed path matches any of its
  `when_changed` globs under `fnmatch.fnmatchcase` on the unchanged strings. As
  with `risk_paths`, `*` also crosses `/`, so `python/*` covers the whole
  subtree, and a bare directory name such as `python` matches only a file of
  that exact name. An empty changed set runs no conditional id. The predicate
  (`any` over paths × globs) lives once in `resolve_project`, beside
  `is_canonical_path`, and `lane-triage`'s `risk_path` signal switches to it
  with no behaviour change.
- **Failure:** a missing `origin/<integration>` ref, no merge base, an unborn
  `HEAD` or any git failure is `verified-tree`'s existing exit 2 with one
  stderr line, never a skip.
- **Moving and stale bases.**
  - Main advancing after the fork does not move the merge base until main is
    merged in. Once it is merged, the base is main's tip, so only the branch's
    own net change counts. main's agent-tooling changes, which arrive through
    that merge, never trigger the suite: their own PRs verified them.
  - A stale local `origin` ref can only widen the diff. Widening runs more
    commands, never fewer.

### `verified-tree` interface (D5, D6)

Both verbs drop `--verification`. Before reading or writing any record, each
calls `resolve_project.resolve(<worktree top level>, ["verification"])`. A
`ContractError`, including a non-`available` verification capability, is exit 2
with one line, `verified-tree: resolve-project refused: <code> <repair_id>`,
and empty stdout. The verbs read only `workflow.verification`,
`workflow.verification_conditions` and `vcs.integration_branch` from the
snapshot.

**Plan.** `run` holds the declared ids, in declared order, that are
unconditional or whose condition matched. `skipped` holds the rest, in
declared order, each as `{"id": <id>, "reason": <skip_reason>}`. The plan is a
pure function of the snapshot and the changed paths, importable from the
module per agent-helpers rule 2.

**`verified-tree check`** prints one canonical JSON line and exits 0:

```json
{"run":["nix-build"],"skipped":[{"id":"agent-workflow-tests","reason":"no agent-tooling paths changed"}],"status":"unverified","tree":"<tree id>"}
```

`status` is `verified` only when a record exists, its `tree` equals the
current tree and its `verification` list equals `run`, element for element. The
plan is printed with either status, so a consumer that reuses a pass still
learns what was skipped.

**`verified-tree record --tree <id>`** checks the tree first, so a mismatch is
exit 3 `tree_changed` exactly as today, with no resolution needed. Otherwise it
resolves, recomputes the plan and atomically writes the record with
`verification` set to `run`. It prints `{"recorded":true,"tree":"<id>"}` as
today. The plan is deterministic for a fixed tree and an unchanged merge base,
so it equals the plan `check` printed for the commands the consumer ran.

**Record.** The schema stays `verified-tree/v1`, `{schema, tree, verification}`,
with its closed shape and strict parsing unchanged. `verification` now means
"the ids that ran and passed on this tree", which is also what every record
the old helper wrote means. It is non-empty, because D2 guarantees an
unconditional id. A skipped id never appears in it. An old record holding
both ids therefore reads as `unverified` against a plan that skips one, which
costs one re-run and is never an error.

Every other exit-2 case, usage error and invariant (the temporary index, no
change to the real index or `HEAD`, the per-worktree record path) is
unchanged. `check` now also refuses when the branch has broken its own
contract or let its projections drift. sdd routes that exit 2 to its existing
repair-once step, and ship to its existing run-everything rule. `--verification`
gets no compatibility handling (D13). The module docstring and the command's section of `python/README.md`
are rewritten to match, and the README section is where the
`verification_conditions` grammar is documented, as `lane-triage`'s section
documents `light_lane`.

### Consumers (D7, D8)

**sdd final review, Final verification.** The intro says the step runs each id
`verified-tree check` lists under `run`, in order, dereferenced through
`bindings.commands`, and that an id under `skipped` is not run. The steps
become:

1. Run `verified-tree check`, keeping `tree`, `run` and `skipped`.
2. Run each `run` command, then `verified-tree record --tree <the checked tree>`.
3. Ledger: `Final verification: passed (head <full sha>, tree <tree id>)`,
   then `skipped <id>: <reason>` for each skipped entry.

Step 4 (repair once) is unchanged, so `check` exit 2 there is still not a
pass. The `Declared verification:` line in the conformance dispatch still lists
every declared id (D8). The edit must not grow the file: at the base,
`implementation-owner`'s hot ceiling has 8 bytes of slack and this file is
hot there. A drafted wording measured −8 bytes.

**ship-issue Phase 2.**

- Step 1 runs `verified-tree check` and keeps `tree`, `run` and `skipped`. On
  Phase 2's own run, it notes each skipped entry as
  `verification skipped: <id> (<reason>)` in the PR body's Summary, whether or
  not the pass is reused. This is the issue's demo.
- Step 3 runs each `run` id's `bindings.commands` argv and cwd, then
  `verified-tree record --tree <the checked tree>`.
- `check` exit 2 means: run every retained `bindings.workflow.verification` id,
  and leave the pass unrecorded. Without a plan, nothing is skipped.
- The Project-bindings paragraph keeps its pinned clause ("only sanctioned
  exception is `workflow-state build-delivery`, which performs its own
  sealed, read-only resolution") verbatim. It appends a parenthetical naming
  `verified-tree` as reading `bindings.workflow.verification` and its
  conditions itself, following from-issue's `lane-triage` precedent.
- A `run` id the retained `bindings.commands` cannot dereference stops, like
  any other dereference failure. No new prose covers it.
- The drafted ship-issue wording grows the file by about 130 bytes, against
  about 1,788 bytes of slack in every profile that loads it.

No instruction-budget raise is allowed: the label is owner-only. Pins in the
skill-contract suite move from `verified-tree check --verification <id>` to
the new argv in both machine-text tables. The sanctioned-exception pin is
untouched. ship-issue's eval shell check changes from
`verified-tree check --verification test` to `verified-tree check`.

### Other readers of `workflow.verification` (D9)

These are unchanged:

- adopt-apply's `workflow-verification-commands` gate. It runs every declared
  id, a superset of any plan, so it can never give a false pass, and adoption
  has no base to diff against.
- conformance's `verification.commands.no_shell_indirection` check, which
  reads `bindings.commands`.
- `capabilities.verification` readiness.
- codex-collaboration's plan-review context line.
- `lane-triage`'s policy.
- `build-delivery`'s sealed policy, because `workflow` is unsealed.
- The eval fixture project's contract. Tests inject conditions into a copy, as
  `lane-triage`'s tests inject `light_lane`.

### Proposed gated paths for this repository (D10, D11)

The owner approves or edits this list in the PR (the [human] criterion). The
follow-up commit authors exactly the approved object:

```json
"verification_conditions": {
  "agent-workflow-tests": {
    "when_changed": [
      "python/*", "home/common/agent-skills/*", "home/common/claude-code/*",
      "tests/*", "AGENTS.md", "CLAUDE.md", ".agents/instructions/*",
      "home/common/agent-guidance/*", "justfile",
      ".agents/project.json", ".agents/knowledge/*", ".agents/artifacts/evidence/*",
      ".agents/runtime/*", "home/common/codex/*", "lib/agent-tools.nix",
      ".gitignore", ".github/*"
    ],
    "skip_reason": "no agent-tooling paths changed"
  }
}
```

**The issue's six categories.**

- The agent helper package: `python/*`.
- The agent skills: `home/common/agent-skills/*`, which includes their tests,
  evals and the instruction-budget model.
- The Claude Code module: `home/common/claude-code/*`.
- The top-level tests: `tests/*`.
- The instruction files: `AGENTS.md`, `CLAUDE.md`, the projection source
  `.agents/instructions/*`, and the global guidance source
  `home/common/agent-guidance/*`.
- The `justfile`.

**Additions.** The suite reads each of these from the repository itself, so a
change to one could change its outcome:

- `.agents/project.json`: the resolver, adopt and conformance tests.
- `.agents/knowledge/*` and `.agents/artifacts/evidence/*`: the promotion tests.
- `.agents/runtime/*` and `.gitignore`: the conformance doctor demo and the
  scratch-pattern test.
- `home/common/codex/*`: the instruction-load and skill-contract tests.
- `lib/agent-tools.nix`: the command table the skill-contract suite reads.
- `.github/*`: the branch-protection and instruction-budget tests.

**Deliberately excluded.** `.agents/artifacts/specs/*` and
`.agents/artifacts/plans/*`. Every lifecycle delivery writes them and the suite
never reads them, so gating them would mean the suite is never skipped.
`docs/*` is also excluded, because the suite does not read it.

### Acceptance handling (D10, D16)

- AC1 and AC2 are measured by the `verified-tree` tests.
- AC3 is measured by the `resolve-project` tests.
- AC4 keeps its `code` tag in the plan's `## Acceptance map` and is graded
  `unmet` on this branch, the run's accepted residual (D16); AC5 is
  `human_pending`. AC4's measure, `resolve-project resolve` on the
  repository at the head, is cited by the follow-up commit once the owner has
  approved the list and run `just switch`.
- Ship therefore holds the issue `needs-verification`, which AC5 forces
  anyway.
- No task, fixer or ship step on this branch edits `.agents/project.json`.

## Test seams

All of them run in `just agent-workflow-tests`.

- **`verified-tree`, CLI level** (the existing `test_verified_tree` module,
  driven by `python -m agent_tools.verified_tree` in a throwaway repository,
  per #263 D6). The harness copies the eval fixture project, adds a second
  command and a `verification_conditions` entry in its contract copy, puts the
  committed platform manifest under a temporary `HOME` (the `lane-triage` test
  precedent), commits a base and points `refs/remotes/origin/main` at it.
  - AC1: a change touching only a non-listed path. `check` prints `run` = the
    unconditional id and `skipped` = `[{"id", "reason"}]` with the authored
    reason. After `record`, the record's `verification` is the unconditional id
    alone and the next `check` is `verified` with the same `skipped`.
  - AC2: a change touching a listed path, covered once each for a committed
    edit, a staged new file, a tracked working-tree edit, a deletion and a
    rename out of a listed directory. `run` includes the conditional id, and
    `record` writes it.
  - AC2 inverse: a record written while the conditional id was skipped (or a
    record whose `verification` lacks it) answers `unverified` once a listed
    path changes.
  - Also covered: an untracked file under a listed path changes nothing; a
    contract without conditions keeps today's behaviour (every id in `run`,
    `skipped` empty).
  - Each of these exits 2 with empty stdout and one stderr line, writing no
    record: a resolver refusal and an absent `origin/<integration>` ref.
    `--verification` is now a usage error: argparse prints its multi-line
    usage on stderr, and the call exits 2 with empty stdout, writing no record.
  - The existing invariant tests carry over onto the new harness.
- **Resolver** (the `resolve-project` tests). A conditions test class modelled
  on `LightLaneTest`:
  - A valid member round-trips unchanged, with globs not absolutized.
  - Absent stays absent and `null` stays `null`.
  - A refusal table asserts `invalid_contract`, the repair id and the single
    pointer for every row of the grammar table above. AC3's three named cases
    are the empty list, the absolute path and the unknown key.
- **Shared matcher.** No new test. `lane-triage`'s existing tests prove its
  behaviour is unchanged.
- **Skill text** (the skill-contract suite). The machine-text pins follow the
  new argv (agent-helpers rule 6), and no English phrase is pinned. The
  instruction budget gate (`just agent-instruction-budget`) passes with no
  raise.

## Out of scope

- CI workflows (the suite's CI job is already advisory).
- Making `nix-build` or any other id conditional.
- Light-lane routing and `lane-triage` semantics.
- Conditions on review, deploy or adoption commands.
- Persisting skips in the `verified-tree` record.
- A `verified-tree` verb that runs commands.
- Authoring the member in this repository's contract (D10's follow-up).
- Changing the eval fixture project's contract.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The condition is a new optional `bindings.workflow.verification_conditions` map (id → `{when_changed, skip_reason}`) beside an unchanged `verification` id list. Absent or `null` means none. It is passed through as authored, globs unabsolutized, with no schema bump and no new capability | #279 D2 (optional member, absent stays absent, `null` accepted, as `light_lane` and `stall_minutes` do); bootstrap: no defaulting, and only `paths` and `cwd` are rewritten | Object entries inside the `verification` list: a mixed-type list breaks every id reader (adopt gate, capability readiness, skill prose, plan-review context). A condition on `commands.<id>`: commands are shared executables, not verification policy |
| D2 | Grammar: keys must be declared verification ids; condition members are exact; `when_changed` is a non-empty list of safe, canonical globs; `skip_reason` is a non-empty authored string; at least one id stays unconditional. New repair ids are `unknown_verification_id`, `empty_path_list` and `no_unconditional_verification`, and every other case reuses an existing `contract.workflow.*` id | Issue AC3; #279 D4 and D18 (one glob grammar, shared predicates); the bar's truthful terminal states (a verification that ran nothing is not a pass) | A helper-constant reason: a generic helper cannot know this repo's "agent-tooling" wording. All-conditional lists: a tree could read "verified" with nothing run. A bare-prefix path grammar: a second path grammar in one contract |
| D3 | Matching is `fnmatch.fnmatchcase` on unchanged canonical strings (`*` crosses `/`). The any-path × any-glob predicate lives once in `resolve_project`, and `lane-triage` reuses it | #279 D4 and D18; the bar's DRY (one grammar's matcher has one home) | `PurePosixPath.full_match` with `**`: stricter, so a near-miss glob would under-match and wrongly skip the suite. A private copy in `verified_tree`: two matchers for one grammar would drift |
| D4 | The change is `diff-tree -r --no-renames` from `merge-base(HEAD, origin/<integration_branch>)` to the verified tree (index plus tracked edits). Renames count both paths and deletions count. A missing ref or git failure is exit 2, never a skip | Ship syncs and reviews against `origin/<integration>`; #263's tree definition; the bar's fail loud | A diff against `HEAD`, which misses committed branch work. A diff against the origin tip, which counts main's newer changes as the branch's. The local integration branch, which is stale in worktrees. A caller-supplied path list, where the skill would infer the change |
| D5 | `verified-tree` resolves the worktree itself (`resolve(root, ["verification"])`) and drops `--verification`. `check` prints `{run, skipped, status, tree}`. ship-issue's sanctioned-exception sentence keeps its pinned clause and names `verified-tree` | #279 D1 (helpers read policy through the public `resolve`) and D10 (name self-resolving helpers); issue: consumers read the condition from the resolved project; the bar's token economy | The skill passes ids, globs and base as argv: the model transcribes policy, and the prose grows in a file with 8 bytes of slack. Keeping `--verification` beside self-resolution: two sources for one list |
| D6 | The record stays `verified-tree/v1`, and `verification` holds only the ids that ran and passed (the plan's `run`). `check` is verified iff the tree matches and the record equals `run`. Skips are recomputed and printed on every check, never persisted | Issue decision: a skip is never a pass; the bar's DRY (the skip derives from contract plus diff); #263's exact-match semantics | A v2 record persisting skips: it stores derivable data, and v1 records in worktrees crossing the switch would need migration handling, where sdd treats an unreadable record as a failure. Treating a superset record as verified: it loosens #263 for no gain |
| D7 | Consumers run exactly `run`. The skip and its reason are recorded where verification is recorded: an SDD ledger suffix `skipped <id>: <reason>` and a PR-body Summary line `verification skipped: <id> (<reason>)`. ship's `check` exit 2 runs every declared id. sdd's final-review text must not grow, and no budget raise is taken | Issue demo and decision; the instruction-budget gate (implementation-owner hot slack is 8 bytes, and the raise label is owner-only); ship's existing exit-2 rule | Skipping on a `check` failure, which skips without a plan. A new report field (`verification_state: skipped`), which would be a schema change no consumer needs |
| D8 | The conformance dispatch's `Declared verification:` line still lists every declared id | Gating premise: a skip asserts that nothing the suite reads changed, so its outcome is main's, and the owner-approved list (AC5) is that premise; the budget (D7) | Building the line from a first-pass `check`: an extra helper call and prose in an 8-byte-slack file, and the plan can change across the fix wave |
| D9 | Other readers are unchanged: the adopt gate (runs all ids, so it is a superset), conformance's shell check, capability readiness, plan-review context, `lane-triage` policy, `build-delivery` (workflow unsealed) and the fixture contract. Only ship's eval argv changes | YAGNI; #279 D3 (demonstrated on copies); adoption has no base to diff | Honouring conditions in adoption: there is no change to evaluate, and running more never yields a false pass |
| D10 | This PR authors nothing in `.agents/project.json`. The spec's list is the approval artifact, and after the owner's approval and `just switch` a follow-up commit authors it and cites `resolve-project resolve` at its head. The plan's Acceptance map classifies AC4 `human`, graded `human_pending`, and ship holds the issue | #279 D3 and #310 D15: the installed resolver refuses an unknown member, so ship Phase 0, `build-delivery`'s worktree resolve and concurrent owners syncing main would refuse until a switch. The conformance prompt takes the kind from the Acceptance map. Issue: the list is the owner's call in this PR | Authoring now: this branch's own ship refuses at Phase 0, and after merge every unswitched host refuses main. Grading AC4 `code`/`unmet`: it forces Residuals and sends the final-review fixer to author the member |
| D11 | The proposed list is the issue's six categories plus every repo path the suite reads (`.agents/project.json`, `knowledge`, `artifacts/evidence`, `runtime`, `.gitignore`, `.github`, `home/common/codex`, `lib/agent-tools.nix`). It excludes `.agents/artifacts/specs` and `plans` | Inventory of the suite's repository reads; #279 D4 (over-matching errs safe); issue: the owner approves the list | `.agents/*` whole: the suite would never be skipped for a lifecycle delivery. The six categories only: a `.github` or `lib/agent-tools.nix` change could break a skipped suite |
| D12 | Test seams: `verified-tree` at CLI level in a throwaway repository holding a copied fixture contract, a temporary-`HOME` manifest and an `origin/main` ref; the resolver through a `LightLaneTest`-style class; skill pins moved to the new argv | #263 D6; the `lane-triage` harness; agent-helpers rules 5 and 6 | In-process tests of the plan function alone: they would miss the git diff and resolution seams the ACs name |
| D13 | Grill: the CLI change ships with no compatibility handling for `--verification`. Skills and helper switch together through home-manager. A run that loaded old skill text and straddles a `just switch` gets a usage exit 2, which its existing exit-2 route handles loudly | The bar's YAGNI (no compatibility shim) and fail loud; skills (`skillsDir`) and `~/.agents/bin` launchers come from the same home-manager generation | Accept-and-ignore `--verification`: it silently discards input. Accept it as a cross-check against the resolved list: a second source kept only for a transition window |
| D14 | Plan: `verified-tree` computes the merge base and the changed paths only when some declared id has a condition. A contract with no conditions (absent, `null` or `{}`) needs no `origin/<integration>` ref, runs every id and records exactly what the old helper did | Spec § Test seams ("a contract without conditions keeps today's behaviour"); #263 (the helper never needed a remote); the bar's YAGNI. With a condition, D4's exit 2 on a missing ref or merge base stands | Always computing the base: a project with no conditions and no `origin` ref would turn every sdd final verification into a `check` exit 2, then a repair attempt and Residuals, for a diff nothing reads |
| D15 | Plan: the machine-text pin for the new argv is the backtick-delimited `` `verified-tree check` `` in `SDD_MACHINE_TEXT` and `SHIP_ISSUE_MACHINE_TEXT`; the `record` pin is unchanged. The plan fixes the skill wording verbatim, measured at base: `sdd/final-review.md` −16 bytes and `ship-issue/SKILL.md` +137 bytes, with the sdd ledger suffix spelled `; skipped <id>: <reason>` | Agent-helpers rule 6 (pin helper argv only); D7's budget (implementation-owner hot slack 8 bytes; ship profiles ~1,788) | A bare `verified-tree check` pin: the old `verified-tree check --verification <id>` text also contains it, so the pin could never catch a stale consumer. Leaving the wording to the implementer: one extra byte in `final-review.md` past 8 fails the budget gate with no raise available |
| D16 | Phase-5 review (reverses D10's AC4 classification only): AC4 stays `code`, owned by Task 1, and is graded `unmet` in this PR. D10's authoring decision stands: no task or fixer authors `.agents/project.json`, and the unmet row is the run's accepted residual until the owner's post-switch follow-up | REVIEW-CONTRACT § Acceptance map check (a kind contradicting the issue's tag is Blocking); Codex plan review R1 | Keep `human`: contradicts the issue's `[code]` tag. Author the member now: D10's refusal hazard |
| D17 | Final review (supersedes § `verified-tree` interface's `record` paragraph where they differ): `check` also persists the plan it printed (`verified-tree-plan.json`, `{schema, tree, run}`) beside the record; `record --tree` compares the tree first (exit 3), then exits 2 unless a persisted plan exists for that tree and the recomputed `run` equals it, and records the persisted `run` | Codex correctness review C1: the plan depends on the shared, mutable `origin/<integration>` ref, so a merge-base move between `check` and `record` could certify an id that never ran; issue: a skip is never a pass. The skills already treat any `record` exit 2 as unrecorded, so their prose is unchanged | Passing the run ids back to `record`: a second policy source (D5) and bytes the sdd instruction budget lacks. Leaving `record` to recompute: the race above |
| D18 | Ship PR review (extends D17): `record` consumes the persisted plan once read, recorded or refused, and a `check` of a tree with a pending plan narrows `run` to the ids both plans run, never widening it; both verbs hold an exclusive lock on `verified-tree-plan.lock`. ship-issue Phase 2 reruns step 1 on `record`'s `plan changed since check` | Codex correctness review C1 at ship: a second `check` of the same tree after `origin` moved replaced the pending plan, so the first caller could record an id it skipped; C2: ship continued past a changed plan without running the newly required id; issue: a skip is never a pass | A check receipt passed back to `record`: new argv in both consumers and bytes the sdd budget lacks (D17). Refusing every second check of a pending tree: one abandoned check would block the tree until it changes |
