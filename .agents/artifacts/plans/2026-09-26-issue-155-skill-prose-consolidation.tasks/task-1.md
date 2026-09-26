# Task 1: One resolver statement per policy entry (E1) and its guard

**Files:**
- Modify: `SK/design/SKILL.md`, `SK/doc-grounded-questions/SKILL.md`,
  `SK/from-issue/SKILL.md`, `SK/grill-with-docs/SKILL.md`, `SK/research/SKILL.md`,
  `SK/ship-issue/SKILL.md`, `SK/ship-release/SKILL.md`, `SK/to-issues/SKILL.md`,
  `SK/wayfind/SKILL.md`, `SK/worktrees/SKILL.md`, `SK/writing-plans/SKILL.md`,
  `CL/codex-collaboration/SKILL.md`, `CL/orchestrate-issues/SKILL.md`
- Test: `T/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (existing, in `T/test_workflow_skill_contracts.py`): `normalized(text)`,
  `RESOLUTION_SENTENCE`, `assert_refusal_reporting`, `assert_policy_entries(case,
  root, entries, require_refusal_reporting=False)`, `SHARED_POLICY_ENTRIES`,
  `CLAUDE_POLICY_ENTRIES`, the `DESIGN` path constant, and the class
  `ProjectPolicySurfaceTest`.
- Produces: the module constant `RESOLUTION_STATEMENT = "`ResolvedProject` in
  memory"`, and `assert_single_resolution_statement(case, text)`. The helper
  raises `AssertionError` unless `normalized(text)` holds `RESOLUTION_STATEMENT`
  exactly once. It is called by `assert_policy_entries` for every entry, and so
  also by the live-home `test_installed_policy_surface_matches_source_contract`
  (D27). A new test,
  `ProjectPolicySurfaceTest.test_policy_entry_rejects_a_restated_resolution`,
  exercises it.

**Invariants:**
- Each of the 13 entries keeps `resolve-project resolve` exactly once,
  `RESOLUTION_SENTENCE`, `REFUSAL_REPORTING_SENTENCE`, every binding it names, and
  its sanctioned exception, word for word (D5).
- After the edit, each entry's whitespace-normalized text contains
  "`ResolvedProject` in memory" exactly once, inside `RESOLUTION_SENTENCE`. It
  contains "retain the full `ResolvedProject`" zero times.
- The helper is called outside `subTest` in the mutation test, following the
  precedent of `test_refusal_reporting_matrix_rejects_a_missing_clause`. A failure
  inside `subTest` is recorded, not raised.

- [ ] **Step 1: Write the failing test**

In `T/test_workflow_skill_contracts.py`, add the constant and helper directly
below `assert_refusal_reporting`:

```python
# RESOLUTION_SENTENCE is the one statement of the resolver rule in a policy
# entry; an opener that restates it is the un-held copy #155 removed (D13).
RESOLUTION_STATEMENT = "`ResolvedProject` in memory"


def assert_single_resolution_statement(case, text):
    case.assertEqual(
        normalized(text).count(RESOLUTION_STATEMENT), 1,
        "a policy entry states the resolver rule once, in RESOLUTION_SENTENCE",
    )
```

In `assert_policy_entries`, directly after the existing
`case.assertIn(RESOLUTION_SENTENCE, normalized(text))` line, add
`assert_single_resolution_statement(case, text)`.

Add this method to `ProjectPolicySurfaceTest`, directly before
`test_worktree_contract_uses_retained_schema_fields_and_root`:

```python
    def test_policy_entry_rejects_a_restated_resolution(self):
        text = normalized(DESIGN.read_text(encoding="utf-8"))
        assert_single_resolution_statement(self, text)
        restated = text.replace(
            "Run `resolve-project resolve --repo-root <checkout>`.",
            "Run `resolve-project resolve --repo-root <checkout>` once at phase "
            "entry and retain the full `ResolvedProject` in memory.",
            1,
        )
        self.assertNotEqual(restated, text)
        with self.assertRaises(AssertionError):
            assert_single_resolution_statement(self, restated)
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ProjectPolicySurfaceTest`
Expected: FAIL. `test_policy_entry_rejects_a_restated_resolution` fails with
`2 != 1`. Both `test_shared_source_phase_entries_use_one_resolved_project` and
`test_claude_source_phase_entries_use_one_resolved_project` fail with one
`2 != 1` subtest per entry.

- [ ] **Step 3: Make E1 in the 13 entries**

In each entry, replace only the opening sentence of the resolver paragraph.
Leave everything after it untouched.

| Entry | Current opener (whitespace-normalized) | Replacement |
|---|---|---|
| `design`, `from-issue`, `grill-with-docs`, `research`, `ship-issue`, `ship-release`, `to-issues`, `wayfind`, `worktrees` (one line each) and `codex-collaboration`, `orchestrate-issues` (wrapped over two lines) | "Run `resolve-project resolve --repo-root <checkout>` once at phase entry and retain the full `ResolvedProject` in memory." | "Run `resolve-project resolve --repo-root <checkout>`." |
| `doc-grounded-questions` | "Run `resolve-project resolve --repo-root <checkout>` once and retain the full `ResolvedProject` in memory." | "Run `resolve-project resolve --repo-root <checkout>`." |
| `writing-plans` (spans lines 10–11, inside the `**Resolve once at entry.**` paragraph) | "Run `resolve-project resolve --repo-root <the checkout you were called in>` and retain the full `ResolvedProject` in memory." | "Run `resolve-project resolve --repo-root <the checkout you were called in>`." Keep the existing line break inside the code span. |

In the two wrapped Claude-only entries, the replacement joins the line that
follows. Re-wrap only that one line, if at all. The next sentence, "Resolve once
at phase entry, retain the returned `ResolvedProject` in memory, …", stays
byte-identical.

- [ ] **Step 4: Verify**

Run: `env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py`
Expected: OK. The skipped count equals the run at the start commit.

Run: `git grep -c -F "retain the full" -- home/common/agent-skills/skills home/common/claude-code/skills`
Expected: no output and exit 1. At the start commit it lists 13 files, one match
each.

Run: `git grep -c -F "resolve-project resolve" -- home/common/agent-skills/skills home/common/claude-code/skills`
Expected: the same 13 files, `1` each. Only the opener sentence changed.

Run: `env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: OK. The shortened inline span stays a single sanctioned command.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/design/SKILL.md home/common/agent-skills/skills/doc-grounded-questions/SKILL.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/grill-with-docs/SKILL.md home/common/agent-skills/skills/research/SKILL.md home/common/agent-skills/skills/ship-issue/SKILL.md home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/to-issues/SKILL.md home/common/agent-skills/skills/wayfind/SKILL.md home/common/agent-skills/skills/worktrees/SKILL.md home/common/agent-skills/skills/writing-plans/SKILL.md home/common/claude-code/skills/codex-collaboration/SKILL.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "refactor(skills): state the resolver rule once per policy entry (#155 E1)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D1, D2, D5, D13, D27.
