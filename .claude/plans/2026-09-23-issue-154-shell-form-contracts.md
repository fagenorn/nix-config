# Shell-Form Contracts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Shared-skill shell examples stop teaching the four forms the worktree
isolation checker refuses, the `worktrees` skill states the checker contract,
and one classifier holds source trees, installed trees and fixtures to it
([#154](https://github.com/fagenorn/nix-config/issues/154)).

**Architecture:** A support module takes over the skill-tree and installed-view
layout from `test_dispatch_contracts.py` (Task 1). A new contract module,
`test_shell_example_contracts.py`, owns the one public classifier
`refused_examples(document_text)`, its fixtures and the vocabulary guard, and the
`worktrees` probe is rewritten so the fixture host is clean (Task 2); Task 2's
fix round keeps #171's lifecycle helper calls through a derived sanction and
reads list-item fences de-indented. The `worktrees` guidance section follows
(Task 3), then the from-issue/ship-issue rewrites (Task 4), the ship-release
rewrites together with the source sweep (Task 5), and last the installed sweep
and its recipe (Task 6).

**Tech stack:** Python 3 `unittest` (stdlib only; CI's Ubuntu 24.04 Python
3.12), Markdown skill prose, `just`, Nix (`just build`).

Spec (source of truth, read whole):
`.claude/specs/2026-09-23-issue-154-shell-form-contracts-design.md`, D1–D26.

## Global Constraints

- Swept documents: every `*.md` under `home/common/agent-skills/skills` and
  `home/common/claude-code/skills` whose path below the tree has no `evals`
  component (per D1).
- Refused forms, closed: `chain`, `pipe`, `redirect`, `heredoc`, `unparseable`
  (per D4). Command substitution is not a form (per D8).
- The one sanctioned chain is the guard's literal, read from the single
  `UNSET_GITHUB_TOKEN_PREFIX = "…"` assignment in
  `home/common/claude-code/default.nix`; never restated in a test, never
  replaced by `env -u GITHUB_TOKEN` (per D5).
- The one sanctioned pipeline is a lifecycle helper call; the helpers are the
  basenames of `default.nix`'s single-word `"Bash(<word>:*)"` allow entries,
  derived, never named in a test's implementation; #171's lifecycle calls are
  never rewritten (per D23, D26).
- Every rewrite keeps the example's meaning (per D7); existing `$(…)` sites
  stay (per D8); no exemption list anywhere (per D9, D20).
- Retained branch `worktree-issue-99-skill-prose-fixes` stays read-only at
  `3c9709ca470bd473d49b39a611ca6cab258973db`: read it only with
  `git show 3c9709ca:<path>` or `git diff 95b6caf 3c9709ca -- <path>`; never
  check out, cherry-pick, merge, rebase or add a worktree for it (per D15).
- A commit that lands a recovered or adapted hunk (Tasks 2, 3, 4, 5) lists
  those hunks in its body and carries
  `Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db` in the same final
  trailer paragraph as the attribution lines; Tasks 1 and 6 carry none (per D15).
- Out of scope, never added: `env -u GITHUB_TOKEN`, any
  `.claude/skills.config.json` "if it exists" wording, leaf-agent clauses,
  `writing-plans` edits, `.nix`, CI, `CLAUDE.md`, ADR or `docs/` changes, the
  permission-guard suite (per D5, D16, D17).
- Commits are SSH-signed (never disable signing) and end with the attribution
  trailer lines the executing harness prescribes.
- Every task leaves `just agent-workflow-tests` green (per D20).
- HOME note: at `d4bcfdb`,
  `test_artifact_budget.ArtifactBudgetCliTest.test_workflow_response_partial_package_import_cleans_namespace`
  failed under the real `HOME` only. At `a311fda` it passes (2026-09-24: 1057
  tests, `OK (skipped=1)`, under both the real and an empty `HOME`). If it
  alone reds again, run `mktemp -d`, then
  `env HOME=<that directory> just agent-workflow-tests`; green there → report
  it as the pre-existing environment failure, not the task's. Any other
  failure is the task's.
- Verification commands in this plan are single plain commands: no chain,
  pipe, redirect or heredoc — the shapes this issue removes.

## Test seams

- `home/common/agent-skills/tests/test_shell_example_contracts.py` only (D3,
  D16): public boundary `refused_examples(document_text) -> tuple[Finding, ...]`
  plus `FORMS`, `COMMAND_VOCABULARY`, `SANCTIONED_PREFIX`, `shell_fence_heads`,
  `swept_documents`, `whole_allowed_helpers` and `LIFECYCLE_HELPERS` (D14,
  D19, D23).
- Classes: `RefusedFormFixtureTest`, `LifecycleHelperCallTest`,
  `FenceIndentationTest`, `SanctionedPrefixTest`, `VocabularyGuardTest`,
  `WorktreesGuidanceTest`, `SourceTreeSweepTest`, `InstalledTreeSweepTest`
  (D13, D18, D21, D23, D24).
- Installed trees enter only through `AGENT_SKILLS_INSTALLED_HOME`, laid out by
  `home/common/agent-skills/tests/skill_tree_support.py` (D13).
- Existing pins adjusted in place: `test_workflow_skill_contracts.py` Gate 1
  anchor (D11), `test_ship_release_contracts.py` PREV_TAG execution (D12).

## Delivery estimate and boundaries

Estimate: 14 product files — 2 new test modules, 3 modified test modules
(~40 lines net), `justfile` (2 lines), 8 skill documents (~65 lines net). The
classifier module landed at 645 lines against a ~420 estimate; the fix round
adds an estimated ~150 (about 90 of them tests), Tasks 3, 5 and 6 about 60
more, so ~850 lines at the end — the largest single file in the review
package, still one package. Tasks are sequential: each consumes the previous
one's module state.

## Execution state

Recorded 2026-09-24 against the spec amended at `7cf395d` (the branch merged
origin/main `185cc1a` as `a311fda`); resume at Task 2 Step 7.

- Task 1 — complete: `5b64f90`, low-risk lane review Spec ✅ Quality ✅, no
  findings.
- Task 2 — Steps 1–6 committed as `d4bcfdb` (implementer DONE_WITH_CONCERNS:
  module size; the HOME-dependent failure in Global Constraints). Full-lane
  review of `5b64f90..d4bcfdb`: Spec ❌. Fix round pending — Steps 7–12 of
  `task-2.md` fix Important-1 and Important-2 and fold D23–D26; because the
  round adds new classifier behavior, not only the named fixes, its range gets
  a full-lane review. Minors deferred to the final review: module size vs
  estimate; `>|` scanned as redirect plus pipe; an escaped `\|` in a
  Markdown table-cell span not reported. The fourth, the positional
  open-fence entry, is absorbed by Step 9d.
- Tasks 3–6 — not started; re-anchored to `a311fda`.

## Task index

Task 1 — Skill-tree support module — `home/common/agent-skills/tests/skill_tree_support.py` (create), `home/common/agent-skills/tests/test_dispatch_contracts.py` — low-risk — complete — [task-1.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-1.md)

Task 2 — Classifier, fixtures, vocabulary guard and isolation probe — `home/common/agent-skills/tests/test_shell_example_contracts.py` (create), `justfile`, `worktrees/SKILL.md` — full — fix round pending — [task-2.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-2.md)

Task 3 — Checker-contract guidance — `worktrees/SKILL.md`, `test_shell_example_contracts.py` — full — not started — [task-3.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-3.md)

Task 4 — from-issue and ship-issue rewrites — `from-issue/SKILL.md`, `ship-issue/{SKILL,HUMAN-GATE,CI-MERGE,SYNC}.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full — not started — [task-4.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-4.md)

Task 5 — ship-release rewrites and the source sweep — `ship-release/{SKILL,CHANGELOG}.md`, `home/common/agent-skills/tests/test_ship_release_contracts.py`, `test_shell_example_contracts.py` — full — not started — [task-5.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-5.md)

Task 6 — Installed sweep and recipe — `test_shell_example_contracts.py`, `justfile` — low-risk — not started — [task-6.md](2026-09-23-issue-154-shell-form-contracts.tasks/task-6.md)

(Skill paths without a prefix are under `home/common/agent-skills/skills/`; a
bare `test_shell_example_contracts.py` is under `home/common/agent-skills/tests/`.)

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D18 from design
and the three rows planning added: D19 (per-call examples, finding lines, the
fixed vocabulary), D20 (the source sweep lands with the last rewrite; earlier
rewrites gate on the classifier directly) and D21 (per-operator fixtures and
the heredoc-body control). Standards review added D22 (expansions are scanned
contexts; substitutions nested in them are live). The amendment after the
origin/main merge added D23 (the lifecycle helper call sanction; Tasks 2, 3, 4,
5), D24 (fence bodies de-indented; Tasks 2, 5) and D25 (the absolute-path
isolation probe; Task 2), and this plan amendment D26 (the sanction's
fail-closed edges and where the bare-prefix exemption lives; Task 2).

## Standards review provenance

Reviewer: Codex (isolated, read-only runtime; no fallback), base
`a6ac80f630bf4a98ea9613840c21aa7e30c7eb8b`, reviewed plan head `fc06df1`, no
focus configured. Findings: 1 Blocking, 3 Should fix, 0 Discussion — all 4
verified against the live worktree and accepted, 0 rejected, 0 deferred.
154-B1 → Task 2 scanner and fixtures (D22); 154-S1 → Task 1 Steps 3 and 5
(one class-level skip; `rg` for the untracked support file); 154-S2 → Task 2
Step 3's expected failures now include the host-appended fixtures; 154-S3 →
Task 5's PREV_TAG fixture gains an older reachable tag.

---
