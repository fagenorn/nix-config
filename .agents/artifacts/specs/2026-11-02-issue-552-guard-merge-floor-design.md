# Lifecycle guard: a declared required-check floor where the forge cannot enforce branch protection — issue 552

Issue: https://github.com/fagenorn/nix-config/issues/552. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.
The owner chose option 2 on 2026-11-02
(https://github.com/fagenorn/nix-config/issues/552#issuecomment-6586978692).

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a required-checks declaration to the project contract schema (resolve_project.py) and a member to the compiled guard policy's derived row"}, "concurrency_or_persistence": {"value": "hit", "evidence": "changes the persisted compiled policy file ~/.agents/state/guard/policy.json row schema and derivation schema_version"}, "open_design_questions": {"value": "hit", "evidence": "contract location of the declared checks and how the guard decides the provider cannot enforce protection are open"}, "criteria_shape": {"value": "no", "evidence": "two acceptance criteria, both verified by guard and guard-policy unit tests"}}, "paths": ["home/common/claude-code/lifecycle_guard.py", "python/agent_tools/guard_policy.py", "python/agent_tools/resolve_project.py", "tests/test_claude_permission_guard.py", "tests/test_guard_policy.py", "tests/test_resolve_project.py", "home/common/claude-code/README.md", "python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","risk_path"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

The lifecycle guard lets an agent merge a feature PR into a repository's default branch only
after it reads that branch's protection from the forge and sees at least one required status
check and admin enforcement. Every other answer refuses.

`fagenorn/argus` is a private repository on a plan without branch protection. On 2026-11-02
its protection read (`gh api repos/fagenorn/argus/branches/main/protection`) exited 1, wrote
`{"message":"Upgrade to GitHub Pro or make this repository public to enable this feature.","documentation_url":"https://docs.github.com/rest/branches/branch-protection#get-branch-protection","status":"403"}`
to stdout and `gh: Upgrade to GitHub Pro or make this repository public to enable this
feature. (HTTP 403)` to stderr. Argus integrates on `main`, which is also its default branch,
so the integration-branch exemption does not apply. Even once Argus is adopted
(https://github.com/fagenorn/nix-config/issues/129), the guard would refuse every agent merge
into Argus with `protection lookup failed`. Today the owner merges Argus PRs by hand, for
example https://github.com/fagenorn/argus/pull/114.

Neither the project contract nor the guard can state "these checks must be green before a
merge" for a repository whose forge cannot enforce that rule. Issue 129 rules out an
Argus-local workaround. Declaring a separate integration branch for Argus would drop the floor
altogether.

## Solution

A project's contract may declare its required checks. The guard-policy derivation copies them
into the project's derived row, and the row check confirms them just as it confirms the row's
branches. When a feature merge into the default branch gets the forge's plan-gated answer to
the protection read, and the confirmed row declares checks, the guard reads the PR's own check
rollup instead. Every declared check must be present and green there, on the reviewed head
the merge names.

Everything else keeps its current verdict:

- a protected default branch;
- a declared integration branch;
- the release arm;
- a repository whose row declares no checks, or that has no row;
- every other answer to the protection read.

The floor is weaker than forge enforcement, because nothing stops a merge made outside the
guard. The owner accepted that when choosing option 2 (per D9).

## Decisions

### The contract member (per D1)

`bindings.vcs.merge` gains one optional member, `required_checks`, beside `strategy` and
`delete_branch`. An absent member and `null` both mean that the project declares no required
checks. The resolver never inserts the member, and the project schema version stays 1.

A present, non-null value must be a non-empty list. Each entry must be a non-empty string, and
no entry may appear twice. Each entry is the exact name GitHub shows for the check: a check
run's `name` or a commit status's `context`. The resolver restricts no characters, because
GitHub names carry spaces, parentheses and `+` (Argus's CI job is
`memory foundation (unit + forced checks)`).

Violations join the resolver's one ordered list, under the `vcs` section's repair ids:

| Violation | Pointer | Repair id |
|---|---|---|
| not a list | `/bindings/vcs/merge/required_checks` | `contract.vcs.not_list` |
| an empty list | the same | `contract.vcs.empty_required_checks` |
| an entry that is not a non-empty string | `/bindings/vcs/merge/required_checks/<i>` | `contract.vcs.not_string` |
| a repeated entry | the second occurrence's pointer | `contract.vcs.duplicate_required_check` |

The snapshot passes the member through unchanged, like every other `vcs` value.

### The derived row (per D4)

A derived row becomes `{default_branch, integration_branch, required_checks, evidence}`.
`required_checks` is the contract's declared list, sorted, or `[]` when the contract declares
none. It is a required member of every row. The proof reads it from the resolved snapshot of
the pinned contract, as it reads the two branches. `evidence` is unchanged.

The compiled policy's `derivation.schema_version` becomes 3. The `derive` report's
`schema_version` becomes 2, because its `row` member is the row `compile` would write. The
report's other members and the three outcomes do not change.

The guard's loader adds `required_checks` to the derived row's closed key set and demands a
list of distinct non-empty strings. As with any malformed row, a violation makes the whole
compiled policy contribute no row. The loader's rule and the resolver's rule accept the same
entries, so a resolving contract always yields a row the guard loads. `unsupported_name`
therefore gains no case.

Transition. A schema-2 compiled policy lacks the member, so the new guard reads it as
contributing no row. The activation step recompiles on every home-manager activation, so the
switch that installs the new guard also writes a schema-3 file. A Claude Code session started
before the switch still runs the old guard, which reads the schema-3 file as contributing no
row. In both cases only a repository that relies on a derived row for its authorization is
refused, until the recompile or the session restart that the guard README already asks for
after an agent_tools change. A repository authorized by an owner literal keeps its
authorization.

### The row check (per D5)

The row check confirms a row's required checks as well as its branches. In the report's
`derived` outcome, `row.required_checks` must be a list of strings, or the report is
unreadable. After the two branches compare equal, the two lists must be equal as lists. The
compiler writes the list sorted, so an honest row compares equal, and any other difference,
order included, refuses as
`repository <slug>: the row check did not confirm its derived policy row: it derives required checks <derived>, the row names <compiled>; repair: run claude-guard-policy`.
Each list is shown as compact JSON. `evidence` is still never compared.

`Context` exposes the declared checks of a confirmed row and none otherwise. A row with a
problem declares nothing, as it already declares no integration branch. A literal
`integration_bases` row and a repository without a row declare none.

### The merge floor (per D2, D3, D6, D11)

Only the feature arm changes. Its order up to the protection read is unchanged: the PR lookup,
the open/base/URL predicate, the base read-back, the permanent-head refusal, the mergeability
check and the integration-base exemption. The PR lookup's argv already asks for
`statusCheckRollup`, so it is unchanged too. The protection read then branches:

1. **Exit 0.** The protection predicate runs as today. Declared checks are not consulted.
2. **Timeout.** It refuses as today.
3. **Non-zero exit.** The floor applies only when both of these hold:
   - the context declares at least one required check;
   - the lookup's stdout parses as a JSON object whose `status` is the string `403` and whose
     `message` is exactly `Upgrade to GitHub Pro or make this repository public to enable
     this feature.` (the **plan-gated answer**).

   The guard reads this from gh's response body on stdout and does not parse stderr. Any other
   non-zero exit keeps today's refusal, `protection lookup failed: <bounded child
   diagnostic>`, byte for byte. That includes a 404 `Branch not protected`, a 403 for missing
   admin rights or a rate limit, a body that is not JSON, and the plan-gated answer for a
   context that declares no checks.

The **floor** is a predicate over the PR facts the lookup already parsed. It starts no child,
and no check name ever becomes program text. It decides in this order:

1. **The reviewed head.** The command must carry `--match-head-commit` (per D11). The
   mergeability check has already refused a value other than the PR's `headRefOid`, and the
   rollup comes from the same lookup, so the head the floor judges is the head GitHub
   merges, or GitHub refuses the merge atomically. The form table is unchanged: the flag
   stays optional in the grammar and is required only on this path.
2. **Readable rollup.** `statusCheckRollup` must be a list. Each entry must be an object that
   is either a `CheckRun` with a string `name` or a `StatusContext` with a string `context`.
   Any other shape refuses as `cannot read the PR check rollup`. GitHub's rollup union has
   exactly those two members, so an unknown one is a fact the guard cannot judge.
3. **Each declared check, in row order.** An entry *names* a check when its `name` (CheckRun)
   or `context` (StatusContext) equals the check exactly. At least one entry must name the
   check, and every entry that names it must be green. Entries that name no declared check are
   ignored. The first declared check that fails is the verdict.

**Green** has one home, shared with the release arm. A CheckRun is green when its `status`
is `COMPLETED` and its `conclusion` is one of `SUCCESS`, `SKIPPED` or `NEUTRAL`. A
StatusContext is green when its `state` is `SUCCESS`. The release arm's jq predicate is
rendered from that home and stays the same program, so its verdicts and its refusal do not
change.

When every declared check passes, the merge is allowed. A forge that later gains protection
for the branch answers the read with exit 0, and the guard is back on the protection demand
without any change to the contract.

### Refusals (per D7, D11)

The floor's refusals are forge-state refusals: they go through the merge refusal with no
accepted forms and no prefix clause (issue 402 D3). The missing flag is one of them too,
because the form table admits the command and only the forge state demands the flag. Names
and observed values are shown escaped, as every refusal value is.

- `unsafe merge: <base> cannot be protected on this repository's plan, so the merge must carry --match-head-commit with the reviewed PR head`
- `unsafe merge: cannot read the PR check rollup`
- `unsafe merge: <base> cannot be protected on this repository's plan, and the declared required check <name> is missing from the PR's check rollup`
- `unsafe merge: <base> cannot be protected on this repository's plan, and the declared required check <name> is not green (<observed>)`

`<observed>` belongs to the first non-green entry that names the check: `CheckRun
<status>/<conclusion>`, with a null or missing conclusion shown as `none`, or `StatusContext
<state>`.

The plan-gated answer for a context with no declared checks keeps today's refusal text, so no
existing refusal changes.

### Documentation

The Claude Code module README remains the one home of guard semantics. It changes in the same
change as the code:

- `## Adjudicated verbs`: the feature arm's default-branch demand gains the plan-gated floor
  and its `--match-head-commit` requirement. The refusal-classes paragraph adds the floor's
  refusals to the forge-state class.
- `## Guard policy`: the row has four members. The guard takes a row's two branches and its
  required checks from the compiled policy. Step 4 compares the checks. The schema-2 to
  schema-3 transition is described.
- `## Guard/core decision`: one sentence records the floor as a native-guard exception of the
  kind issue 116 D6 lists as a gap. It is not core-admission evidence (per D9).

`python/README.md` § guard-policy gets the four-member row, `schema_version` 3, the `derive`
report's `schema_version` 2 and the contract member. The member is documented as an optional
`resolve-project` member whose absence or `null` means none, following the
`verification_conditions` paragraph. Every docstring and comment that says the guard reads or
compares only a row's two branches is corrected. There is nothing to write in context docs or
ADRs, because `knowledge.context` is unsupported and no ADR directory is bound.

### Acceptance mapping

- **AC1.** One guard-suite round trip covers it (Test seams, seam 4). The real compiler and
  the real row check run over an Argus-shaped project whose contract declares a check. The
  fake `gh` replays the plan-gated answer. The merge, in ship-issue's form, is allowed with
  the declared check green and refused with it missing or red, so the floor is in force. The
  base policy, the Nix literals and the guard's constants gain no repository slug. The declaration lives in the
  fixture's contract, as it will live in Argus's own contract. The live run on
  `fagenorn/argus` belongs to issue 129, once that contract declares its checks and Argus is
  registered (per D8).
- **AC2.** `tests/test_claude_permission_guard.py` stays green with its assertions unchanged.
  Its row fixtures gain `"required_checks": []`, a data-only change that the closed key set
  forces. New rows pin the unchanged verdicts (Test seams, seam 1).

## Test seams

These are the existing seams only (per D10).

1. **The built guard, run as registered.** `run_guard` drives it against the fake `gh` and
   the fake row check in `tests/test_claude_permission_guard.py`, as in issues 116, 377, 402
   and 476.
   - The fake `gh` gets one protection mode for an HTTP error. It exits 1, writes a JSON body
     to stdout (the grounded plan-gated body by default, `FAKE_PROTECTION_JSON` otherwise) and
     writes gh's `gh: <message> (HTTP <status>)` line to stderr, as the live read did. The
     default protected answer and the other modes stay.
   - Fake-derive rows and compiled rows carry `required_checks`.
   - New rows, all on a derived row in an `acme/` repository, so authorization visibly comes
     from the row:
     - The floor allows a green declared check. A CheckRun with `SKIPPED` or `NEUTRAL` counts
       as green, and so does a green StatusContext.
     - It refuses a merge without `--match-head-commit`, a missing check, a pending or failed
       CheckRun, a pending StatusContext, a red duplicate beside a green one, and an
       unreadable rollup.
     - With declared checks and readable protection, the protection predicate governs: a
       merge whose rollup lacks a declared check is allowed when protection passes, and
       refused when the protection predicate fails.
     - With declared checks, the `nonzero`, `timeout` and 404 answers, and a non-plan 403,
       each keep today's refusal.
     - With no declared checks, the plan-gated answer keeps today's refusal.
     - With checks declared, a feature merge into a declared integration base stays exempt,
       and a release merge with an all-green rollup that lacks a declared check is allowed.
     - A row whose checks differ from the derivation is refused at use.
     - A compiled row whose `required_checks` is malformed contributes no row.
2. **`guard-policy compile` and `derive` from source** over `tests/guard_policy_world.py`,
   with `project(..., mutate=...)` declaring checks. The derived row carries the sorted list,
   or `[]` with none declared. `derivation.schema_version` is 3 and the `derive` report's is 2.
3. **`resolve-project resolve`** through the resolver suite, which lives at
   `home/common/agent-skills/tests/test_resolve_project.py`, not under `tests/`. It covers
   each violation row in the contract-member table. It also checks that absent and `null`
   both resolve, and that the snapshot passes the list through unchanged.
4. **One round trip** in the guard suite, after `test_an_arcwave_shaped_project_is_judged_by_its_compiled_row`.
   - The fixture is an Argus-shaped project: slug `fagenorn/argus`, integration branch equal
     to the default `main`, and the declared check named like Argus's CI job.
   - The real compiler builds the row and the real row check confirms it.
   - Against the plan-gated answer, a feature merge into `main` in ship-issue's form (with
     `--match-head-commit`) is allowed with that check green, and refused when it is missing
     or failed.
   - A plain `nonzero` protection failure still refuses.

## Out of scope

Per D8:

- Declaring Argus's checks in Argus's own contract, registering Argus, and the live merge.
  These belong to https://github.com/fagenorn/nix-config/issues/129.
- The merge that first publishes Argus's contract. No derived row can exist before that
  contract is on `origin`'s default branch, so the guard refuses that merge as it does today.
- The release arm, the integration-base exemption and their gaps under issue 116 D6.
- Push, PR creation, release creation and branch deletion.
- `release_verification`'s protection read for the release core.
- Rulesets and the `rules/branches` read.
- Setting up or changing branch protection, billing or repository visibility.
- Declaring nix-config's own checks.
- Requiring the whole rollup to be green on the feature arm.
- Pinning a check to the app that posts it.
- Codex, which has no hook.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The declaration is the optional `bindings.vcs.merge.required_checks`, where absent or `null` means none and the resolver never inserts it. A present value is a non-empty list of distinct non-empty strings, each an exact check-run name or status context, with no character restriction. Project schema version 1 is kept | The issue's option 2 and the Phase-0 summary's suggested location beside the other merge settings. Optional-member precedent: `light_lane`, `verification_conditions` and `stall_minutes` (null and absent mean none, added within schema 1). Argus's live job name `memory foundation (unit + forced checks)` | A new top-level or `bindings.workflow` member: workflow binds agent verification commands, not forge checks. A schema-version bump: every existing contract would need a migration for an additive member. A name pattern: GitHub names carry spaces, parentheses and `+` |
| D2 | The floor replaces the protection demand only on the feature arm into the default branch, when the confirmed row declares checks and the protection read exits non-zero with the plan-gated body (`status` `403`, the exact "Upgrade to GitHub Pro…" message, read from stdout). Every other answer, readable protection included, keeps today's verdict and text | Owner decision: the floor is "used when the provider cannot enforce branch protection". The live read of 2026-11-02. README: every uncertainty blocks. AC2 | Declaring the checks replaces protection outright: a repository that can enforce would stop being checked, and one that later gains protection would keep the weaker floor. Any lookup failure: an unprotected branch on a plan that could protect it (`just unprotect-main`), or a transient failure, would silently fall back. Any 403: missing admin rights and rate limits also answer 403 |
| D3 | Each declared check needs at least one rollup entry naming it (CheckRun `name`, StatusContext `context`), and every entry naming it must be green by the release arm's rule (CheckRun COMPLETED with SUCCESS, SKIPPED or NEUTRAL; StatusContext SUCCESS). Undeclared entries are ignored. A rollup outside the two-member union is unreadable and refuses | The issue's option 2: "every declared check completed and green, the same way the release arm already reads the rollup". GitHub counts a skipped or neutral required check as passing. The bar: fail loud at a closed set | Whole rollup green: an optional failing check would block, which the forge floor this stands in for does not do. SUCCESS only: diverges from the release arm and from GitHub (issue 116 D6's stricter skipped rule binds core admission, which this does not claim). Latest entry wins for duplicates: needs timestamps, while refusing on any red duplicate fails closed |
| D4 | `required_checks` is a required member of every derived row (sorted, `[]` when none). The loader demands a list of distinct non-empty strings. `derivation.schema_version` goes to 3 and the `derive` report's to 2. A schema-2 file contributes no row until the activation recompile | Issue 377: closed key sets, a bad compiled policy contributes no row (D4), and issue 375's seven-member file as the precedent for a transition. The activation step recompiles on every activation | An optional row member: two row shapes in a closed schema, and an absent-versus-empty case for the row check. Accepting both schemas during the transition: a compatibility path for a file that every switch rewrites |
| D5 | The row check confirms the checks: the derived report's list must equal the compiled row's, and a difference refuses with the `claude-guard-policy` repair. The guard uses the compiled list only once it is confirmed | Issue 377 D1 and D2: the compiled policy is user-writable and a row is a claim confirmed at use, and adopting fresh values silently was rejected | Comparing branches only: a forged file could swap in an always-green check name, so the floor would rest on an unconfirmed value. Taking the report's list over the file's: the silent adoption 377 D2 rejected |
| D6 | The floor is a guard predicate over the already-parsed PR facts, with no child and no name in program text. Green gets one home that the floor reads and from which the release arm's jq program is rendered unchanged | Issue 476: `mergeability_problem` is Python over the same facts. The 27-second invocation deadline. The bar: DRY, one home for a policy | A jq floor with names passed by `--argjson`: one more child under the deadline, and a refusal that cannot name the failing check. A second copy of the green rule: two homes that must change together. Porting the release arm to Python: changes an out-of-scope arm and its refusal |
| D7 | The floor's refusals are forge-state refusals naming the first failing declared check in row order, with its observed state and the fact that the base cannot be protected on this plan. The plan-gated answer without declared checks keeps today's `protection lookup failed` text | Issue 402 D3: forge-state refusals name only their problem. README: the first failure is the verdict. AC2 | Listing every failing check: departs from the guard's first-failure style, and ship-issue's check wait already shows them all. Adding a "declare required_checks" hint to the existing refusal: changes an existing refusal, and an unregistered owner-literal repository could not follow it |
| D8 | Scope: the contract member, its derivation, the guard's loader, row check and feature-arm floor, their tests and the two READMEs. Argus's declaration, registration and live merge belong to issue 129. The merge that first publishes Argus's contract stays refused, because no row can exist before that contract is on `origin`'s default branch | The brief's scope boundary. Issue 129 owns Argus's contract. Issue 126 and 377: rows derive only from the registered branch on `origin` | Reading the checks from the PR head's contract for that first merge: a declaration that is unmerged and unconfirmed, which the PR itself controls |
| D9 | The floor is a recorded native-guard exception. The guard/core README section gets one sentence saying it is not core-admission evidence. Issue 116 and the rejection record keep their text | Owner decision of 2026-11-02, which accepts that the floor is "weaker than forge enforcement". The floor is still a required status check on the PR, as `ungated-agent-merges.md` demands, only enforced by the guard. The bar: point-in-time records keep their text | Refusing per issue 116 D6: overrides the owner's direct decision. Editing issue 116 or the rejection record: rewrites accepted records |
| D10 | The tests use only existing seams: the registered guard with the fake `gh` (one HTTP-error protection mode replaying the grounded answer) and the fake row check; `guard-policy` from source over `GuardPolicyWorld`; `resolve-project resolve`; and one real compile-plus-row-check round trip for AC1. Existing row fixtures change only by gaining `required_checks: []` | Issue 476 D8 and D9 (the registered-guard seam, data-only fixture changes). Issue 377 D8 (stub row check plus one real round trip). The bar: fixtures shaped like production | A unit seam that imports the guard: the guard is a standalone file tested as registered. A live provider read in the suite: not hermetic |
| D11 | On the floor's path the merge must carry `--match-head-commit`, which the mergeability check has already held to the PR's `headRefOid`. Without it the guard refuses as forge state. The form table and every other path keep the flag optional | Forge protection binds the merged head to its checks atomically, and the floor would otherwise leave a window between the guard's rollup read and the merge. GitHub compares the flag atomically with the merge (issue 476 D3). ship-issue always passes the flag with the reviewed head | Leaving the flag optional: a push after the verdict would merge a head whose checks nobody read. Requiring the flag everywhere: changes the accepted form that issue 402 made optional and that issue 476 D3 kept optional |
| D12 | `<observed>` shows a CheckRun's `status` and `conclusion` and a StatusContext's `state` through `shown_value` when the fact is a string, and as `none` otherwise (null, missing or another type) | § Refusals: a null or missing conclusion is `none`. GitHub's rollup sends string states and a null conclusion while a run is pending. Issue 402 D18: every refusal value is shown escaped, on one line | A JSON or `repr` rendering of a non-string fact: a second display rule for values GitHub does not send, with quotes no other refusal shows |
| D13 | The release predicate's byte identity with the base jq program is checked once, by a Task 3 step gate that loads the guard file from a scratch script. No committed test imports the guard, and the release-arm rows keep pinning its verdicts | D6: the release arm's program stays the same. D10: existing seams only | A committed test with a fake `jq` that records its program: a fake beyond D10's seams. Verdict rows alone: they cannot tell an equivalent rewritten program from the same one |
| D14 | The AC1 round trip is named in the new plan-gated floor paragraph of the guard README's `## Adjudicated verbs`. The `## Allow surface and lifecycle guard` sentence that names three derive-from-source tests keeps its text, which stays true of those three | The review package holds a file's whole diff as one record under the 65,536-byte member limit. The planned README diff measures about 54.7 KB, and that sentence's line is 5.9 KB, which an edit counts twice | Rewriting that line: about 60.6 KB, too close to the limit to absorb wording drift and the Phase-5 edits |
| D15 | The loader keeps two distinct refusals for a row: one that lacks `required_checks` (a schema-2 row) fails the existing closed-key check with its existing reason, and only a present but malformed value gets the dedicated `required_checks must be a list of distinct non-empty strings` reason | Phase-5 standards review PR-552-02 (Codex): the closed-key check in `load_compiled_policy` runs first, so a missing member never reaches the member check | One reason for both cases: it would need the closed-key check reordered or special-cased for one member, a larger change to a security loader for no verdict difference |
