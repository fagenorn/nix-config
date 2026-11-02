# Task 2: The `issue-owner` definition, registered and pinned

Spec § The definition, § No body, § Tiers, per D1, D2, D3, D5 and D7. Add the body-less agent definition Task 1 probed, byte-identical, and make the matrix validator and the tests know it: `issue-owner` joins `CUSTOM_AGENT_ROLES` (its frontmatter tier is checked against the `issue-owner` role, opus/high, like the other four), a new frontmatter test pins its fields, and the carrier test enrols only definitions that have a body. No dispatch site changes here (Task 3).

**Files:**
- Create: `home/common/claude-code/agents/issue-owner.md`
- Modify: `python/agent_tools/agent_model_matrix.py` (`CUSTOM_AGENT_ROLES`)
- Test: `home/common/agent-skills/tests/test_agent_model_matrix.py` (class `AgentModelMatrixTest`, `write_fixture`)
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py` (class `CarrierDeclarationTest`)

**Interfaces:**
- Consumes: Task 1's recorded sha256 `02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56` in `.agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md`.
- Produces: the agent type `issue-owner` at `~/.claude/agents/issue-owner.md` after activation (the existing recursive `home.file.".claude/agents"` source picks it up; `default.nix` is not edited here); `agent_model_matrix.CUSTOM_AGENT_ROLES == {"implementer", "issue-owner", "reviewer", "reviewer-lite", "mechanic"}`; the test helper `_has_body(path) -> bool` in `test_dispatch_contracts.py`.

**Invariants:**
- `issue-owner.md` is exactly the seven lines below (248 bytes); its sha256 equals Task 1's.
- No frontmatter `tools`, no `omitClaudeMd`, no body; the four other definitions are byte-identical to base.
- `agent_model_matrix.validate(REPO_ROOT) == []`; `ALLOWED_SUBAGENT_TYPES` is unchanged in this task.
- `just agent-instruction-budget` passes with no `--raise-label`; no profile lists `agents/issue-owner.md` (D2).

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_agent_model_matrix.py`:

1. In `write_fixture`, the role tuple becomes `("implementer", "issue-owner", "mechanic", "reviewer", "reviewer-lite")`.
2. In `test_every_custom_agent_explicitly_matches_its_matrix_role`, the expected file list becomes `["implementer.md", "issue-owner.md", "mechanic.md", "reviewer-lite.md", "reviewer.md"]`.
3. In `test_only_the_brief_driven_agents_omit_claude_md`, the expected map gains `"issue-owner": None` (after `"implementer": None`).
4. In `test_task_implementer_is_a_sonnet_role_on_the_opus_implementer_type`, the `CUSTOM_AGENT_ROLES` expectation becomes `{"implementer", "issue-owner", "reviewer", "reviewer-lite", "mechanic"}`.
5. Add this method directly after `test_only_the_brief_driven_agents_omit_claude_md`:

```python
    def test_issue_owner_blocks_exactly_the_listed_tools(self):
        # Issue 447 (D1, D2): named tools, never an allowlist; no body, so the
        # definition loads no instruction text into the owner profiles.
        path = AGENTS / "issue-owner.md"
        metadata = frontmatter(path)
        self.assertEqual(
            set(metadata), {"name", "description", "model", "effort", "disallowedTools"}
        )
        self.assertEqual(metadata["name"], "issue-owner")
        blocked = [entry.strip() for entry in metadata["disallowedTools"].split(",")]
        self.assertEqual(
            blocked,
            ["Artifact", "ArtifactComments", "ArtifactData", "mcp__claude_ai_Claude_Docs"],
        )
        for kept in ("Agent", "Skill", "Bash", "Read", "Edit", "Write", "Glob", "Grep",
                     "NotebookEdit", "ToolSearch", "mcp__*"):
            self.assertNotIn(kept, blocked)
        body = path.read_text(encoding="utf-8").split("\n---\n", 1)[1]
        self.assertEqual(body.strip(), "")
```

In `home/common/agent-skills/tests/test_dispatch_contracts.py`, add this module-level helper directly above `class CarrierDeclarationTest`:

```python
def _has_body(path):
    """Whether an agent definition has text after its closing frontmatter
    delimiter; a body-less definition (issue 447, D2) carries no clause."""
    return bool(path.read_text(encoding="utf-8").split("\n---\n", 1)[1].strip())
```

and replace `test_every_agent_definition_is_an_own_commands_body_carrier` with:

```python
    def test_every_agent_definition_with_a_body_is_an_own_commands_body_carrier(self):
        enrolled = {c.relative: c for c in CARRIERS if c.tree == "agents"}
        bodied = {p.name for p in AGENT_DEFINITIONS.glob("*.md") if _has_body(p)}
        self.assertEqual(set(enrolled), bodied)
        self.assertEqual(
            {p.name for p in AGENT_DEFINITIONS.glob("*.md")} - bodied, {"issue-owner.md"}
        )
        for carrier in enrolled.values():
            with self.subTest(carrier=carrier.relative):
                self.assertEqual((carrier.kind, carrier.contracts), ("body", AGENT_CLAUSES))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the **Matrix tests** (Global Constraints).
Expected: FAILED — `test_issue_owner_blocks_exactly_the_listed_tools` errors with `FileNotFoundError` for `issue-owner.md`; the file-list, `omitClaudeMd`, `CUSTOM_AGENT_ROLES` and carrier tests fail on the missing `issue-owner` entries.

- [ ] **Step 3: Write the minimal implementation**

Create `home/common/claude-code/agents/issue-owner.md` with exactly these seven lines, ending in a newline:

```text
---
name: issue-owner
description: Owns one tracker issue for the from-issue and orchestrate-issues owner sites; not for other work.
model: opus
effort: high
disallowedTools: Artifact, ArtifactComments, ArtifactData, mcp__claude_ai_Claude_Docs
---
```

In `python/agent_tools/agent_model_matrix.py`, the line `CUSTOM_AGENT_ROLES = {"implementer", "reviewer", "reviewer-lite", "mechanic"}` becomes `CUSTOM_AGENT_ROLES = {"implementer", "issue-owner", "reviewer", "reviewer-lite", "mechanic"}`. `_agent_errors` needs no other change: the `issue-owner` role already exists in `model-matrix.json` at opus/high (D3).

- [ ] **Step 4: Verify**

From the worktree root (timeout 600 s):

```bash
set -e
test "$(shasum -a 256 home/common/claude-code/agents/issue-owner.md | cut -d' ' -f1)" = 02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56
grep -q 02f2999e7eccfb3eec026aa843452f04b16273f975b48fb8f6cbc91f7254ae56 .agents/artifacts/plans/2026-10-26-issue-447-issue-owner-agent.acceptance.md
git diff --quiet ca6ba1ae2b37e56c1361a8656c29af1f39b89348 -- home/common/claude-code/agents/implementer.md home/common/claude-code/agents/mechanic.md home/common/claude-code/agents/reviewer.md home/common/claude-code/agents/reviewer-lite.md
if grep -q 'issue-owner.md' home/common/agent-skills/instruction-load.json; then exit 1; fi
```

Expected: every command exits 0; the first fails at the commit you start from (no file).

Run the **Matrix tests**. Expected: `OK`, no failure; `test_repository_contract_validates` passes and `test_no_clause_occurs_outside_an_enrolled_region` still passes over the new file.

Run (timeout 600 s) `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_agent_model_drift_*.py 2>&1 | tail -3'` (its fixture copies every agent definition). Expected: `OK` (53 tests at base).

Run the **Budget gate**. Expected: last line `check: pass`. A corpus or profile violation means the file deviates from Step 3; stop as BLOCKED with the gate's output (D2 forbids a raise).

Run the **Build**. Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/agents/issue-owner.md python/agent_tools/agent_model_matrix.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_dispatch_contracts.py
launch-commit … -- -m "feat(agents): body-less issue-owner type blocks the Artifact tools and the Docs connector (issue 447)" -m "<session trailers>"
```

Verify: `git status --short -- home python` prints nothing.
