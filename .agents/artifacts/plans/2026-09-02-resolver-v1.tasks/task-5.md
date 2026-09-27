# Task 5: Migrate the `writing-plans` entry onto the resolver

**Files:**
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Tasks 1–4: the installed executable `~/.agents/bin/resolve-project` and the invocation `resolve-project resolve --repo-root <path>`, which prints one `ResolvedProject` snapshot on stdout and exits 0, or prints `{"error": {"code", "repair_id", "violations"}}` on stdout and exits 2. The binding this skill reads is `bindings.paths.artifacts.plans`, an absolute path normalized against `project.root`. The closed error codes are `not_onboarded`, `invalid_contract`, `unsupported_schema`, `invalid_projection`, `capability_unavailable`, `resolver_failure`.
- Produces: nothing consumed by a later task in this plan. `writing-plans` is the only migrated entry (D2, D3).

**Invariants:**
- `writing-plans/SKILL.md` names `resolve-project` and no longer contains the string `resolve-bindings` anywhere.
- Exactly one error code, `not_onboarded`, has a non-fatal branch, and that branch produces the literal `.claude/plans` — not a detected, sniffed, or table-defaulted value (D7).
- Every other error code stops the skill, which reports the code rather than substituting a value.
- The name `planDir` survives in the skill's own prose, so sibling skills citing that name stay correct.
- The other six skills that call `resolve-bindings` are untouched by this task, and `home/common/agent-skills/scripts/resolve-bindings` is neither deleted nor modified (D2).

## Steps

- [ ] **Step 1: Write the failing tests**

Add to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, inside `WorkflowSkillContractsTest` (it already exposes `self.writing_plans`, loaded in `setUpClass`):

```python
    def test_writing_plans_resolves_its_plan_dir_through_the_resolver(self):
        text = normalized(self.writing_plans)
        self.assertIn("resolve-project resolve", text)
        self.assertIn("bindings.paths.artifacts.plans", text)
        self.assertIn("planDir", self.writing_plans)

    def test_writing_plans_no_longer_calls_the_fail_soft_helper(self):
        self.assertNotIn("resolve-bindings", self.writing_plans)
        self.assertNotIn("skills.config.json", self.writing_plans)

    def test_writing_plans_treats_only_not_onboarded_as_non_fatal(self):
        text = normalized(self.writing_plans)
        self.assertIn("not_onboarded", text)
        self.assertIn("`.claude/plans`", text)
        self.assertIn("Every other error code is fatal", text)
        for code in ("invalid_contract", "unsupported_schema",
                     "invalid_projection", "capability_unavailable",
                     "resolver_failure"):
            with self.subTest(code=code):
                self.assertNotIn(f"{code} → ", text)

    def test_only_writing_plans_migrated_off_resolve_bindings(self):
        still_calling = (
            "research", "doc-grounded-questions", "design",
            "ship-issue", "to-issues",
        )
        for name in still_calling:
            path = (REPO_ROOT / "home/common/agent-skills/skills"
                    / name / "SKILL.md")
            with self.subTest(skill=name):
                self.assertIn("resolve-bindings", path.read_text(encoding="utf-8"))
        orchestrate = (REPO_ROOT / "home/common/claude-code/skills"
                       / "orchestrate-issues" / "SKILL.md")
        self.assertIn("resolve-bindings", orchestrate.read_text(encoding="utf-8"))
        self.assertTrue(
            (REPO_ROOT / "home/common/agent-skills/scripts/resolve-bindings").is_file())
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -20`
Expected: FAIL — `test_writing_plans_resolves_its_plan_dir_through_the_resolver` and `test_writing_plans_treats_only_not_onboarded_as_non_fatal` fail because the skill names neither `resolve-project` nor `not_onboarded`, and `test_writing_plans_no_longer_calls_the_fail_soft_helper` fails because the skill still names `resolve-bindings` and `.claude/skills.config.json`. The fourth test passes at the base commit and pins D2 against regression.

- [ ] **Step 3: Rewrite the entry paragraph**

In `home/common/agent-skills/skills/writing-plans/SKILL.md`, replace the existing paragraph

> **Save the package root to** `<planDir>/YYYY-MM-DD-<feature-name>.md`
> (`planDir` from `~/.agents/bin/resolve-bindings`; helper missing →
> `.claude/skills.config.json`, default `.claude/plans`) and its task members to
> the sibling `<planDir>/<stem>.tasks/` directory, committed in the worktree you
> were called in. For example, the first member is `<stem>.tasks/task-1.md`.
> The root path remains the public plan path (D3, D6).

with exactly these two paragraphs:

```markdown
**Resolve `planDir` once at entry.** Run `~/.agents/bin/resolve-project resolve
--repo-root <the checkout you were called in>` and read
`bindings.paths.artifacts.plans` from the snapshot it prints — an absolute path,
because the resolver normalizes every path against `project.root`. That value is
`planDir` for the rest of this skill. Resolve once; never read
`.agents/project.json` yourself and never persist the snapshot. On the single
error code `not_onboarded` — the repository has not adopted the project contract
yet — use the literal `.claude/plans` and say so in one line. Every other error
code is fatal: stop, report the code, and change nothing.

**Save the package root to** `<planDir>/YYYY-MM-DD-<feature-name>.md` and its
task members to the sibling `<planDir>/<stem>.tasks/` directory, committed in
the worktree you were called in. For example, the first member is
`<stem>.tasks/task-1.md`. The root path remains the public plan path (D3, D6).
```

The `(D3, D6)` citation refers to the artifact-budget spec already governing that sentence; leave it unchanged. Add no other `resolve-bindings` reference and change no other paragraph of the file — the report-candidate clause and package-budget prose are pinned by existing contract tests.

- [ ] **Step 4: Verify**

```sh
python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5
just agent-workflow-tests 2>&1 | tail -5
just build 2>&1 | tail -5
```

Expected: all three succeed — the contract suite reports `OK`, the whole workflow suite reports `OK`, and `just build` completes.

Falsifiable gate — scoped to the two files this task owns plus the D2 boundary:

```sh
set -euo pipefail
SKILL=home/common/agent-skills/skills/writing-plans/SKILL.md
if grep -q "resolve-bindings" "$SKILL"; then exit 1; fi
if grep -q "skills.config.json" "$SKILL"; then exit 1; fi
if ! grep -q "resolve-project resolve" "$SKILL"; then exit 1; fi
if ! grep -q "not_onboarded" "$SKILL"; then exit 1; fi
if ! grep -q "resolve-bindings" home/common/agent-skills/scripts/resolve-bindings; then exit 1; fi
git diff --stat HEAD~1..HEAD -- "$SKILL" home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

Expected: the script reaches its last line and the diffstat names exactly those two files. At the base commit the first `grep -q "resolve-bindings" "$SKILL"` matches and the gate exits 1.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/writing-plans/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(writing-plans): resolve planDir through the fail-closed resolver

Per D2, D3, D7.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
