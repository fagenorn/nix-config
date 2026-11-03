# Task 3: Owner dispatch sites launch `issue-owner`

Spec § Solution 2–3, § The role-to-type mapping, § Documentation, per D4 and D5. The five owner dispatch sites of from-issue and orchestrate-issues name `subagent_type="issue-owner"` instead of `"general-purpose"`; that rename is the whole skill-text change (4 bytes shorter per site, no other wording moves). The matrix call strings, the `ALLOWED_SUBAGENT_TYPES` mapping and its test mirror follow, a new site test pins the five sites, and the Claude Code module's agents comment names the new type.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (sites `from-issue-phase-delegate`, `from-issue-ship-owner`)
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md` (sites `from-issue-design-grill`, `from-issue-planning`)
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md` (site `orchestration-issue-owner`)
- Modify: `home/common/agent-skills/model-matrix.json` (the same five `call` strings)
- Modify: `python/agent_tools/agent_model_matrix.py` (`ALLOWED_SUBAGENT_TYPES`)
- Modify: `home/common/claude-code/default.nix` (the comment above `home.file.".claude/agents"`)
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py` (`EXPECTED_SUBAGENT_TYPES`, class `AgentModelMatrixTest`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (`test_dispatcher_passes_immutable_ledger_root_separately_from_worktree`)

**Interfaces:**
- Consumes: Task 2's `issue-owner` definition and `CUSTOM_AGENT_ROLES` entry.
- Produces: `ALLOWED_SUBAGENT_TYPES["issue-owner"] == {"issue-owner", "general-purpose"}`, `["auto-owner"] == {"issue-owner"}`, `["ship-owner"] == {"issue-owner", "general-purpose"}`; every other role's set unchanged.

**Invariants:**
- In each of the five call lines (in the skill and in its `model-matrix.json` `call`), only `"general-purpose"` → `"issue-owner"` changes; `model`, `effort`, `run_in_background` and the trailing sentence are byte-identical, and so is every marker line.
- `improve-architecture-scan-owner`, `ship-release-owner` and `research-background-researcher` keep `subagent_type="general-purpose"` in their skill and matrix rows; their skill directories are byte-identical to base (D4).
- No file under `home/common/agent-skills/skills/from-issue/` or `home/common/claude-code/skills/orchestrate-issues/` contains `subagent_type="general-purpose"`; prose mentions of `general-purpose` (from-issue `SKILL.md`'s "Prefer the tiered agent types over `general-purpose`.") stay.
- `agent_model_matrix.validate(REPO_ROOT) == []`; `just agent-instruction-budget` passes with no `--raise-label`.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_agent_model_matrix.py`:

1. In `EXPECTED_SUBAGENT_TYPES`, the three owner rows become `"issue-owner": {"issue-owner", "general-purpose"}`, `"auto-owner": {"issue-owner"}`, `"ship-owner": {"issue-owner", "general-purpose"}`.
2. Below `EXPECTED_OWNER_SITES`' closing brace, add:

```python
OWNER_ROLES = {"issue-owner", "auto-owner", "ship-owner"}
OWNER_SKILL_DIRECTORIES = (
    "home/common/agent-skills/skills/from-issue",
    "home/common/claude-code/skills/orchestrate-issues",
)
```

3. Add this method directly after `test_owner_design_and_research_dispatches_select_exact_tiers`:

```python
    def test_from_issue_and_orchestration_owner_sites_launch_issue_owner(self):
        # Issue 447 (D4, D5): the five owner sites of from-issue and
        # orchestrate-issues launch the issue-owner type, none general-purpose.
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        owner_sites = {
            site["id"]: site
            for site in data["dispatch_sites"]
            if site["role"] in OWNER_ROLES
            and any(site["path"].startswith(f"{d}/") for d in OWNER_SKILL_DIRECTORIES)
        }
        self.assertEqual(
            set(owner_sites),
            {
                "orchestration-issue-owner",
                "from-issue-phase-delegate",
                "from-issue-design-grill",
                "from-issue-planning",
                "from-issue-ship-owner",
            },
        )
        for site_id, site in owner_sites.items():
            self.assertTrue(
                site["call"].startswith('Agent(subagent_type="issue-owner", '), site_id
            )
            text = (REPO_ROOT / site["path"]).read_text(encoding="utf-8")
            self.assertIn(site["call"], text, site_id)
        for directory in OWNER_SKILL_DIRECTORIES:
            for path in sorted((REPO_ROOT / directory).rglob("*")):
                if path.is_file():
                    text = path.read_text(encoding="utf-8", errors="replace")
                    self.assertNotIn('subagent_type="general-purpose"', text, path)
```

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, in `test_dispatcher_passes_immutable_ledger_root_separately_from_worktree`, the anchor line `'Agent(subagent_type="general-purpose", model="opus", effort="high", '` becomes `'Agent(subagent_type="issue-owner", model="opus", effort="high", '` (the next line, `'run_in_background=true)'`, is unchanged).

- [ ] **Step 2: Run the tests and watch them fail**

Run the **Matrix tests** (Global Constraints).
Expected: FAILED — `test_from_issue_and_orchestration_owner_sites_launch_issue_owner` (`'Agent(subagent_type="general-purpose", …'` does not start with the issue-owner prefix), `test_executable_subagent_type_mapping_is_exhaustive` (mapping mismatch) and `test_dispatcher_passes_immutable_ledger_root_separately_from_worktree` (`ValueError: substring not found`).

- [ ] **Step 3: Write the minimal implementation**

1. In each skill file, replace `subagent_type="general-purpose"` with `subagent_type="issue-owner"`; the file must hold exactly that many occurrences before the edit: from-issue `SKILL.md` 2 (the lines after the `from-issue-phase-delegate` and `from-issue-ship-owner` markers), `AUTO.md` 2 (after `from-issue-design-grill` and `from-issue-planning`), orchestrate-issues `SKILL.md` 1 (after `orchestration-issue-owner`).
2. In `home/common/agent-skills/model-matrix.json`, in the `call` of exactly the dispatch sites `orchestration-issue-owner`, `from-issue-phase-delegate`, `from-issue-design-grill`, `from-issue-planning` and `from-issue-ship-owner`, replace `subagent_type=\"general-purpose\"` with `subagent_type=\"issue-owner\"`. Leave `research-background-researcher`, `ship-release-owner` and `improve-architecture-scan-owner` alone.
3. In `python/agent_tools/agent_model_matrix.py`, `ALLOWED_SUBAGENT_TYPES`' first three rows become:

```python
    "issue-owner": {"issue-owner", "general-purpose"},
    "auto-owner": {"issue-owner"},
    "ship-owner": {"issue-owner", "general-purpose"},
```

4. In `home/common/claude-code/default.nix`, the comment above `home.file.".claude/agents" = {` becomes:

```nix
  # ~/.claude/agents/<name>.md — tiered pipeline agent definitions. Global
  # effortLevel stays xhigh for interactive/orchestrator sessions; pipeline
  # subagents dispatch explicitly as reviewer (opus/high), implementer
  # (sonnet/high for a planned sdd task and its first fix rounds, opus/high
  # for stuck-task escalation and the final-review fixer), mechanic
  # (sonnet/high) or reviewer-lite (sonnet/medium). from-issue and
  # orchestrate-issues launch their issue owners as issue-owner (opus/high,
  # xhigh for the autonomous design and planning owners), a definition with
  # no body that blocks the Artifact tools and the claude.ai Docs connector.
  # Skills reference them by name; home/common/agent-skills/model-matrix.json
  # owns every tier.
```

- [ ] **Step 4: Verify**

From the worktree root (timeout 600 s):

```bash
set -e
if grep -rn 'subagent_type="general-purpose"' home/common/agent-skills/skills/from-issue home/common/claude-code/skills/orchestrate-issues; then exit 1; fi
test "$(grep -c 'subagent_type=\\"issue-owner\\"' home/common/agent-skills/model-matrix.json)" = 5
test "$(grep -c 'subagent_type=\\"general-purpose\\"' home/common/agent-skills/model-matrix.json)" = 3
git diff --quiet ca6ba1ae2b37e56c1361a8656c29af1f39b89348 -- home/common/agent-skills/skills/improve-codebase-architecture home/common/agent-skills/skills/ship-release home/common/agent-skills/skills/research
test "$(git diff ca6ba1ae2b37e56c1361a8656c29af1f39b89348 --numstat -- home/common/agent-skills/skills/from-issue home/common/claude-code/skills/orchestrate-issues | awk '{a+=$1; d+=$2} END {print a, d}')" = "5 5"
```

Expected: every command exits 0; the first fails at the commit you start from (five matches).

Run the **Matrix tests**. Expected: `OK`, no failure; the three Step 2 tests pass and `test_repository_contract_validates` stays green.

Run the **Budget gate**. Expected: last line `check: pass`; the touched profiles shrink by 4–8 bytes, so neither an exceeded ceiling nor a `tightness` line can appear. Either one stops the task as BLOCKED with the gate's output.

Run the **Build** (the `default.nix` comment is evaluated with the module). Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/model-matrix.json python/agent_tools/agent_model_matrix.py home/common/claude-code/default.nix home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit … -- -m "feat(skills): from-issue and orchestrate-issues owners launch as issue-owner (issue 447)" -m "<session trailers>"
```

Verify: `git status --short -- home python` prints nothing.
