# Guard: Arcwave by its derived row, not a literal — issue 384

Design for https://github.com/fagenorn/nix-config/issues/384 (parent
https://github.com/fagenorn/nix-config/issues/126, follows
https://github.com/fagenorn/nix-config/issues/377 and
https://github.com/fagenorn/nix-config/issues/385). "Issue 126 Dn" and "issue
377 Dn" cite the ledgers of
`.agents/artifacts/specs/2026-10-12-issue-126-derived-guard-policy-design.md`
and `.agents/artifacts/specs/2026-10-12-issue-377-guard-policy-trust-split-design.md`;
a bare "Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "the store base policy's integration_bases member becomes empty; its schema is unchanged but every guard consumer sees a different literal set"}, "concurrency_or_persistence": {"value": "no", "evidence": "no locking or persisted state changes; the compiled policy file is written by the existing claude-guard-policy activation"}, "open_design_questions": {"value": "no", "evidence": "issue prescribes the change; derived-row mechanics exist since #375/#377/#385"}, "criteria_shape": {"value": "hit", "evidence": "AC1 concerns the host's compiled policy after a switch, which no deterministic in-repo check verifies"}}, "paths": ["home/common/claude-code/default.nix", "home/common/claude-code/README.md", "tests/test_claude_permission_guard.py", "tests/guard_policy_world.py", "tests/test_guard_policy.py"]}
Verdict: {"hits":["contract_change","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Arcwave (`fagenorn/arcwave`) is adopted and registered: its contract declares
integration branch `dev` and the publication-free `forge-main` release profile.
The guard still learns Arcwave's integration branch from a hand-written literal
row in the store base policy. Because a repository may not carry both a literal
and a derived row (issue 377 D5), every `guard-policy compile` refuses Arcwave
as `literal_conflict`, and the host's compiled policy holds rows only for
`elevenyellow/nodocom` and `fagenorn/nix-config`. The literal contradicts the
issue 126 decision that literal rows exist only for repositories that are not
registered projects, and it keeps a second, unverified source for a fact the
registered contract already states.

## Solution

Delete the Arcwave entry and its Arcwave-specific comment from the base
policy's literal integration rows. The literal set becomes empty but stays in
place with its general comment, because the mechanism remains the route for a
repository that is not a registered project (D1). On the next activation,
`claude-guard-policy` compiles a derived row for Arcwave from its contract, and
the guard judges Arcwave like Nodo: authorization and the integration branch
come from the row the row check confirms at use time.

No guard, compiler, row-check or schema change is made. The tests that pinned
the literal move to fixtures that state their literal explicitly (D2, D3), and
the guard suite gains one Arcwave-shaped round trip through the compiler and
the guard (D4).

## Decisions

**Base policy.** The built base policy keeps exactly its five members;
`integration_bases` is `{}`. The general comment over the literal rows (what a
declared branch widens, the protection waiver, the release arm) stays, with one
added sentence saying the set is empty because every repository with an
integration branch is a registered project with a derived row, and a literal is
added only for one that is not (D1). The Arcwave rationale (private free-plan
repository, no branch protection) is removed from the Nix file; it is not
guard semantics and is now carried by Arcwave's own contract.

**Behavior for Arcwave after the switch.** Arcwave has a row, so it is judged
by the row and never by its owner literal (issue 377 R6/D8): each
repository-bound verb runs the row check once per invocation (the cheap check
of issue 385). A feature PR into `dev` and its `--delete-branch` merge are
allowed without a protection demand; the `dev` → `main` release merge without
`--delete-branch` is allowed only on a fully green rollup; a PR into `main`
from a feature branch keeps the default-branch protection demand. These are the
verdicts the literal gave, now reached through the row. If the activation's
compile fails, Arcwave has neither literal nor row and falls back to its
authorized owner with no integration branch: PRs into `dev` and the release arm
are refused, fail closed, and the existing activation message names
`claude-guard-policy` as the repair (accepted, D5).

**Docs.** `home/common/claude-code/README.md` names no repository in its
literal-row text and already states the rule ("an `integration_bases` row
exists only for a repository that is not a registered project"); it gains one
clause that the built set is currently empty. No other doc names the literal.

## Test seams

All at existing seams; no new seam is introduced.

- **Built base policy** (guard suite, `test_built_base_policy_holds_exactly_the_five_trusted_members`):
  pins `integration_bases == {}` and asserts the Nix source no longer contains
  `fagenorn/arcwave`, mirroring its existing `elevenyellow` source assertion
  (D3). This is AC3's check.
- **Literal-plus-row refusal** (guard suite, issue 377 D5 test): runs against a
  fixture base policy written with `write_base(integration_bases={slug: "dev"})`
  and passed as `--base-policy`, for a neutral fixture slug under an authorized
  owner; its final "literal alone still allowed" assertion uses the same
  fixture base (D2). The compiler's `literal_conflict` test already passes its
  literals explicitly and is unchanged except that it no longer needs Arcwave's
  slug; `GuardPolicyWorld.write_base` defaults to `{}` so the world mirrors the
  built base (D2).
- **Compiler-to-guard round trip** (guard suite, prior art
  `test_a_compiled_policy_round_trips_through_the_guard`): a world project
  shaped like Arcwave (`fagenorn/arcwave`, integration `dev`, publication-free)
  compiled against the built base policy must be derived, not refused; the
  guard, with the compiled file and the world's real row check, then allows a
  feature PR create into `dev`, its feature merge, and the `dev` → `main`
  release merge on a green rollup, and refuses an unrelated repository as
  outside standing authorization (D4). This is AC2's check and AC1's in-repo
  half.
- **Host evidence** for AC1 (D6): see the ledger. Grill pre-check on
  2026-10-14 at `0cc5768b`: the installed `guard-policy compile`, run against
  the live registry with the installed base policy minus the literal and a
  scratch `--output`, exited 0 deriving `elevenyellow/nodocom`,
  `fagenorn/arcwave` (`main`/`dev`) and `fagenorn/nix-config` with nothing
  refused; the installed row check confirmed Arcwave's row in 5.4–7.7 s over
  three runs (Nodo 5.3 s), inside the guard's 15 s bound. So removing the
  literal is the only change Arcwave needs; a different refusal at D6(a) would
  be a blocker returned to the caller, not fixed in scope.
- Verification: `just build` and `just agent-workflow-tests`; the adversarial
  table is untouched and must stay green.

## Out of scope

- Guard semantics, the compiler, the row check and either policy schema.
- Arcwave itself: its contract, registry entry, CI and the GitHub runner list
  in `hosts/common/darwin-github-runners.nix`, which names Arcwave for an
  unrelated reason.
- Removing the `integrationBases` mechanism or its loader support.
- Running `just switch` on the host; that is the human step in D6.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Keep `integrationBases` as an empty attrset with its general comment plus one sentence on why it is empty; drop only the Arcwave entry and its rationale. | Issue 126 decision (literals only for non-registered repositories) keeps the mechanism live; YAGNI and scope "Out: guard semantics". | Deleting the attrset and the `integration_bases` member: a schema change to both loaders, outside scope and irreversible for the non-adopted route. |
| D2 | Tests that need a literal write it into a fixture base policy (guard suite `write_base`, compiler world `write_base`) under a neutral fixture slug; the world's default literal set becomes `{}`. | Existing `write_base` fixture seam (issue 377 tests); "Tests that can fail": the D5 test must not depend on a store value that is now empty. | Keeping `fagenorn/arcwave` as the fixture slug: reads as if Arcwave were still literal and couples the suite to a real repository. |
| D3 | The five-member test pins the literal set to exactly `{}` and asserts the Nix source does not name `fagenorn/arcwave`. | Precedent: the same test's `elevenyellow` source assertion; AC3. | Only asserting Arcwave is absent from the set: a new literal could appear unreviewed. |
| D4 | Prove AC2 with one new Arcwave-shaped compile-and-judge round trip (feature create, feature merge into `dev`, green `dev` → `main` release merge, unrelated repository refused) rather than re-parameterizing the Nodo arm tests. | Prior art `test_a_compiled_policy_round_trips_through_the_guard`; the Nodo arm tests already cover the derived-row grammar. | Duplicating every feature/release arm test for Arcwave: no new code path, doubles slow round-trip cost. |
| D5 | Accept that a failed activation compile leaves Arcwave with neither literal nor row (fail closed on `dev` and the release arm) instead of keeping the literal as a fallback. | Issue 377 D5 forbids literal plus row; README activation contract already names the repair; the-bar "Fail loud". | A conditional literal: exactly the dual source D5 refuses. |
| D6 | AC1 evidence has two parts: (a) pre-switch, after `just build`, run the store `guard-policy compile` against the live registry with `--base` set to the newly built base policy and `--output` under the run's scratch directory (never the host's state file), and record that its report derives `fagenorn/arcwave` with integration branch `dev` and no `literal_conflict`; (b) post-switch, a human step recording `derived_repositories["fagenorn/arcwave"]` from `~/.agents/state/guard/policy.json`. | Issue AC1 is host state; CLAUDE.md "switch only when asked"; the compile CLI takes `--base`/`--output`. | Running `just switch` or writing the host policy from the run: unauthorized host mutation. |
