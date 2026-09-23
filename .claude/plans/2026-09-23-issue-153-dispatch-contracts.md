# Dispatch Contracts Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Every applicable dispatch carrier tells its subagent to launch by type
only and to read an existing file before writing it, held by contract tests that
fail per missing clause and pass on the source and the Nix-built skill trees
([#153](https://github.com/fagenorn/nix-config/issues/153)).

**Architecture:** One new test module, `test_dispatch_contracts.py`, owns the two
clause constants, the nine-carrier table and a region renderer per carrier kind
(fence, blockquote, section). Task 1 lands the module with the six fence
carriers and their recovered clause paragraphs; Task 2 adds the blockquote and
section kinds with the orchestrate-issues owner prompt and the from-issue and
sdd composition rules; Task 3 adds the installed-tree class and the
`agent-installed-skill-tests` recipe that feeds it the built output.

**Tech stack:** Python 3 `unittest` (stdlib only; must run on CI's Ubuntu 24.04
Python 3.12), Markdown skill prose, `just`, Nix (`nix-store --query --requisites`).

Spec (source of truth, read whole):
`.claude/specs/2026-09-23-issue-153-dispatch-contracts-design.md`, D1–D16.

## Global Constraints

- The two clauses, byte-identical in every carrier (whitespace may wrap to the
  carrier's width, indentation and quote markers):
  - `Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work.`
  - `Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see.`
- In every carrier the two sentences form their own paragraph inside the
  rendered region, launch sentence first; existing carrier text keeps its words
  and place (per D5, D6, D14).
- Retained branch `worktree-issue-99-skill-prose-fixes` stays read-only at
  `3c9709ca470bd473d49b39a611ca6cab258973db`: read it only with
  `git show 3c9709ca:<path>` / `git diff 95b6caf 3c9709ca -- <path>`; never
  check out, cherry-pick, merge, rebase or create a worktree for it (per D12).
- Only the commit that lands recovered hunks (Task 1) carries the trailer
  `Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db` in the same final
  trailer paragraph as the co-author and session lines; commits of new work
  carry none (per D12).
- Out of scope, never added: any `.claude/skills.config.json` or
  `.agents/project.json` read or guard (#100); shell-form examples and
  worktree-checker guidance (#154); consolidation into a standing rule (#155);
  the `SendMessage` delivery clause anywhere new (D5); CI, `.nix`, `CLAUDE.md`,
  ADR or `docs/` changes (D13).
- Commits are SSH-signed (never disable signing) and end with the attribution
  trailer lines the executing harness prescribes.
- Every task leaves `just agent-workflow-tests` and `just agent-model-matrix`
  green; no `agent-dispatch` marker or call line changes.

**AC4 exclusion gate** (run where a task names it, from the worktree root, after
committing; prints `pass` or exits 1 naming the violation):

```bash
bash <<'GATE'
BASE=$(git merge-base origin/main HEAD) || exit 1
added=$(git diff "$BASE"..HEAD -- home/common/agent-skills home/common/claude-code/skills justfile | grep '^+')
for forbidden in 'skills.config.json' '.agents/project.json' 'env -u GITHUB_TOKEN' 'SendMessage' 'yourself, as your own final message'; do
  if grep -qF -- "$forbidden" <<<"$added"; then echo "excluded hunk added: $forbidden"; exit 1; fi
done
if [ -n "$(git diff --name-only "$BASE"..HEAD -- home/common/agent-skills/skills/worktrees home/common/agent-skills/skills/ship-release home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_workflow_skill_contracts.py)" ]; then echo "out-of-scope file changed"; exit 1; fi
if [ "$(git rev-parse worktree-issue-99-skill-prose-fixes)" != 3c9709ca470bd473d49b39a611ca6cab258973db ]; then echo "retained branch tip moved"; exit 1; fi
echo "AC4 exclusion gate: pass"
GATE
```

## Test seams

- `home/common/agent-skills/tests/test_dispatch_contracts.py` only (D9): public
  boundary `missing_contracts(carrier, document_text) -> frozenset[str]` over
  the `CONTRACTS` and `CARRIERS` tables, per D4, D6, D14, D15.
- Four classes: `SourceTreeContractsTest`, `InstalledTreeContractsTest`,
  `CheckerMutationTest`, `EnrolmentGuardTest` — one method per contract per tree
  and a live-text mutation matrix (D10, D11, D15).
- Installed trees enter only through `AGENT_SKILLS_INSTALLED_HOME` (D7, D8, D16);
  `just agent-installed-skill-tests` sets it to the built `home-manager-files`.

## Delivery estimate and boundaries

Estimate: 12 product files — 1 new test module (~370 lines), `justfile`
(~13 lines), 10 skill documents (~5 added lines each, no deletions). One
review package; no slice exceeds the gate. Tasks are sequential: Task 2 extends
Task 1's module, Task 3 extends Task 2's.

## Task index

Task 1 — Fence carriers and the dispatch-contract module — `home/common/agent-skills/tests/test_dispatch_contracts.py` (create), `justfile`, `sdd/{implementer,task-reviewer,re-review,correctness-reviewer,conformance-reviewer}-prompt.md`, `from-issue/ship-handoff.md` — full — [task-1.md](2026-09-23-issue-153-dispatch-contracts.tasks/task-1.md)

Task 2 — Blockquote and composition-rule carriers — `test_dispatch_contracts.py`, `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `from-issue/SKILL.md`, `from-issue/AUTO.md`, `sdd/SKILL.md` — full — [task-2.md](2026-09-23-issue-153-dispatch-contracts.tasks/task-2.md)

Task 3 — Installed-tree class and recipe — `test_dispatch_contracts.py`, `justfile` — low-risk — [task-3.md](2026-09-23-issue-153-dispatch-contracts.tasks/task-3.md)

(Skill paths without a prefix are under `home/common/agent-skills/skills/`.)

## Decisions

The spec's `## Decision ledger` is authoritative. Tasks cite D1–D14 from design
and the two rows planning added: D15 (exactly-once checker semantics and the
matrix's duplicate, header and top-of-document mutations) and D16 (installed
root must be an absolute directory).

---
