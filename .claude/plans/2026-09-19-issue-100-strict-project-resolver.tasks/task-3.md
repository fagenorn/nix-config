# Task 3: Migrate Claude-only consumers and live evaluations

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`
- Delete: `home/common/claude-code/skills/codex-collaboration/CERTIFICATION.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify: `home/common/agent-skills/skills/from-issue/evals/evals.json`
- Modify: `home/common/agent-skills/skills/sdd/evals/evals.json`
- Modify: `home/common/agent-skills/skills/ship-issue/evals/evals.json`
- Modify: `home/common/agent-skills/skills/ship-release/evals/evals.json`
- Modify: `home/common/agent-skills/skills/wayfind/evals/evals.json`
- Modify: `home/common/agent-skills/skills/writing-plans/evals/evals.json`

**Interfaces:**
- Consumes: Task 2's `assert_policy_entries()`, resolution sentence, shared review-command contract, and the D1/D3/D7 snapshot mappings.
- Produces: Claude-only `codex-collaboration` and `orchestrate-issues` phase entries that resolve once; plan/diff review packets executed through the resolved command; live evals that grade strict policy instead of defaults.

**Invariants:**
- `codex-collaboration` resolves exactly once for each plan-review or diff-review invocation. It selects `bindings.workflow.review.plan` or `.code`, dereferences `bindings.commands[review_id]`, and follows Task 2's exact direct `exec` protocol (D7).
- A Codex verdict carries validated metadata: requested and selected model are `gpt-6-astra`, requested and selected `model_reasoning_effort` is `xhigh`, JSONL is well formed, terminal agent-message bytes equal the non-empty `--output-last-message` file, and the operation headings validate. The direct route is established only by a real bounded review; it is never called capacity-safe merely because argv validation passes.
- `orchestrate-issues` consumes `bindings.tracker`, `bindings.vcs`, and `bindings.workflow.orchestration` from one snapshot. Its nested issue owners resolve independently at their phase entries.
- No Claude-only document reads raw policy, invokes a second resolver, preserves plugin-bridge launch instructions, defaults a value, or infers policy from Git.
- Evals name resolved fields/capability states and distinguish `unsupported`, `blocked`, and runtime failure. They do not describe the deleted legacy config or helper.

- [ ] **Step 1: Extend the source matrix before changing prose**

Add the Claude table and test to `ProjectPolicySurfaceTest`:

```python
CLAUDE_POLICY_ENTRIES = {
    "codex-collaboration/SKILL.md": (
        "bindings.workflow.review.plan", "bindings.workflow.review.code",
        "bindings.commands", "capabilities.review.plan",
        "capabilities.review.code", "bindings.paths.hints",
    ),
    "orchestrate-issues/SKILL.md": (
        "bindings.tracker", "bindings.vcs",
        "bindings.workflow.orchestration.attempt_budget_minutes",
        "bindings.workflow.orchestration.max_parallel",
    ),
}

def test_claude_source_phase_entries_use_one_resolved_project(self):
    assert_policy_entries(
        self,
        REPO_ROOT / "home/common/claude-code/skills",
        CLAUDE_POLICY_ENTRIES,
    )

def test_live_evals_grade_strict_policy_and_direct_review(self):
    paths = (
        REPO_ROOT / "home/common/agent-skills/skills/from-issue/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/sdd/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/ship-issue/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/ship-release/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/wayfind/evals/evals.json",
        REPO_ROOT / "home/common/agent-skills/skills/writing-plans/evals/evals.json",
        REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json",
        REPO_ROOT / "home/common/claude-code/skills/orchestrate-issues/evals/evals.json",
    )
    corpus = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    for forbidden in (
        "resolve-" "bindings", ".claude/skills." "config.json",
        "unsetGithub" "Token",
        "helper missing", "auto-detect absent", "default GitHub",
    ):
        self.assertNotIn(forbidden, corpus)
    for required in (
        "ResolvedProject", "bindings.workflow.review.code",
        "bindings.commands", "gpt-6-astra", 'model_reasoning_effort="xhigh"',
        "selected model", "last-message",
    ):
        self.assertIn(required, corpus)
```

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest.test_claude_source_phase_entries_use_one_resolved_project ProjectPolicySurfaceTest.test_live_evals_grade_strict_policy_and_direct_review -v`

Expected before migration: FAIL on legacy config/helper references and the absent direct-review metadata contract.

- [ ] **Step 2: Replace the Claude-only policy and review transport**

In `codex-collaboration/SKILL.md`, replace the config/default and plugin-agent sections with one phase-entry resolution and this closed selection:

1. `plan-review` selects `bindings.workflow.review.plan` and `capabilities.review.plan`; `diff-review` selects `.code`.
2. `available` dereferences the selected command ID and invokes its exact base argv/cwd/env plus Task 2's D7 tail. The complete packet is stdin; JSONL and last-message candidates live under `${TMPDIR:-/tmp}` and are removed by `trap`/`finally` on every outcome.
3. Validate each JSONL object, require the runtime-selection event to report `gpt-6-astra` and `xhigh`, require exactly one terminal agent-message, compare its UTF-8 text byte-for-byte with the last-message file, then apply PLAN-REVIEW or DIFF-REVIEW heading validation. Only this success is reviewer identity `Codex`.
4. `blocked` stops with the capability reason and repair ID. `unsupported` takes the operation's documented native route. A daemon/slot/capacity rejection is a binding stop that is surfaced verbatim, with no retry, plugin dispatch, or native bypass. Another available-command runtime failure, malformed/mismatched metadata/output, or operation-schema failure uses the existing one-time native fallback with the same packet; never retry Codex.

Delete `CERTIFICATION.md`, whose bridge certification is no longer a live route. Update PLAN-REVIEW and DIFF-REVIEW to receive the retained snapshot and validated direct-command result; keep their packet contents, scope rules, finding schemas, and disposition behavior unchanged.

In `orchestrate-issues/SKILL.md`, map tracker CLI/repository/credential env, worktree policy, and both orchestration limits directly from the retained snapshot. Remove every config/default/legacy helper instruction; do not add scheduling policy or a second task ledger.

- [ ] **Step 3: Rewrite the live eval expectations**

Update only policy/review portions of the listed JSON files. Each applicable expected result must say: one retained `ResolvedProject`; direct namespace names; fatal refusal; and no default/inference. Review evals must name the exact direct argv augmentation, runtime metadata validation, last-message equality, and capability handling from Step 2. Preserve each eval's domain behavior, limits, packet/scoping rules, and no-side-effect prompt.

Run: `python3 -m json.tool <each-modified-evals.json> >/dev/null`

Expected: every modified JSON file parses. Any parse error or legacy-policy match is incomplete.

- [ ] **Step 4: Verify shared and Claude source behavior**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest -v`

Expected: PASS for both exact phase-entry sets, direct configured review, and eval corpus.

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -q`

Expected: PASS after updating only assertions whose old expected behavior conflicts with D1–D7. Unrelated review scope, fallback count, lifecycle, and artifact assertions remain intact.

Run one real plan-review through the resolved `bindings.workflow.review.plan` command, with the exact D7 argv, against this issue's committed spec and plan package. Bound the command at 1800 seconds and retain JSONL/last-message candidates only until validation finishes.

Expected: the runtime-selection event reports `gpt-6-astra` / `xhigh`, the last-message bytes equal the terminal agent-message, and the plan-review headings validate. If the daemon reports a slot or capacity rejection, stop this task and surface that rejection; do not retry, use the plugin bridge, dispatch a native substitute, or describe the route as established.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/*/evals/evals.json home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/claude-code/skills
git commit -S -m "refactor(reviews): run configured codex commands directly" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
