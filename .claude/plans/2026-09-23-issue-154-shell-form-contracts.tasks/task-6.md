# Task 6: Installed sweep and recipe

Decisions: D13, D15 (final provenance gate), and #153's D8/D16 rules the
support module carries. Work from the worktree root; paths are repo-relative.
New work — no `Recovered-From` trailer.

**Files:**
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`
- Modify: `justfile` (`agent-installed-skill-tests` recipe)

**Interfaces:**
- Consumes (Task 1, `skill_tree_support.py`): `INSTALLED_VIEWS`,
  `installed_home_or_skip()`, `installed_root_error(root)`.
- Consumes (Tasks 2 and 5, `test_shell_example_contracts.py`):
  `refused_examples`, `swept_documents`, `findings_report`.
- Produces: `InstalledTreeSweepTest.test_no_installed_example_teaches_a_refused_form`;
  `just agent-installed-skill-tests` runs `test_dispatch_contracts.py` and
  `test_shell_example_contracts.py`.

**Invariants:**
- Variable unset → the class is skipped with the support module's reason naming
  the recipe; set → never a skip and never a source fallback (D13).
- The documents checked are exactly `swept_documents()` filtered by each view's
  trees, read by relative path under `<root>/<view dir>`; a missing view or a
  missing document is a failure, never a pass (D13).
- The installed copies go through the same `refused_examples` call as the
  source sweep (spec AC4).

- [ ] **Step 1: Write the failing test**

Extend the support import in `test_shell_example_contracts.py` with
`INSTALLED_VIEWS`, `installed_home_or_skip`, `installed_root_error`, and add
after `SourceTreeSweepTest`:

```python
class InstalledTreeSweepTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = installed_home_or_skip()

    def test_no_installed_example_teaches_a_refused_form(self):
        error = installed_root_error(self.root)
        self.assertIsNone(error, error)
        for view, skills_dir, trees in INSTALLED_VIEWS:
            base = self.root / skills_dir
            if not base.is_dir():
                with self.subTest(view=view):
                    self.fail(f"the {view} view is missing: {base}")
                continue
            for tree, relative in swept_documents():
                if tree not in trees:
                    continue
                path = base / relative
                with self.subTest(view=view, document=relative):
                    self.assertTrue(path.is_file(), f"the {view} view lacks {path}")
                    findings = refused_examples(path.read_text(encoding="utf-8"))
                    self.assertEqual(findings, (), findings_report(str(path), findings))
```

- [ ] **Step 2: Watch it skip, fail closed, and red on a stale tree**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: `OK (skipped=1)`; the skip reason names `just agent-installed-skill-tests`.

Run: `env AGENT_SKILLS_INSTALLED_HOME=relative/home python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: exit 1, one failure containing `is not an absolute directory`.

Run: `readlink ~/.agents/bin/resolve-bindings`
and take the `/nix/store/<hash>-home-manager-files` prefix of what it prints
(the tree the live system installed, which predates these rewrites and still
carries the old examples). Then run
`env AGENT_SKILLS_INSTALLED_HOME=<that store path> python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`.
Expected: exit 1 with installed-sweep subtest failures naming
`ship-release/SKILL.md` in both views — proof the installed class reads the
installed text, not the source. (If the live system was already switched to a
build of this branch, skip this check and say so in the task report.)

- [ ] **Step 3: Extend the recipe**

In `justfile`, `agent-installed-skill-tests`, change the last line
`home/common/agent-skills/tests/test_dispatch_contracts.py` to
`home/common/agent-skills/tests/test_dispatch_contracts.py \` and add
`      home/common/agent-skills/tests/test_shell_example_contracts.py` after it
(same indentation as the dispatch line).

- [ ] **Step 4: Verify**

Run: `just agent-installed-skill-tests`
Expected: exit 0, `OK`, no skips — both views of the freshly built
`home-manager-files` pass both modules.

Run: `just agent-workflow-tests`
Expected: exit 0.

Run: `just agent-model-matrix`
Expected: exit 0 and `agent model matrix: valid` (no dispatch marker moved).

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/tests/test_shell_example_contracts.py justfile
git commit -m "test(agent-skills): sweep the built skill trees for refused shell forms"
```

- [ ] **Step 6: Provenance and exclusion gate (AC5)**

Each is one command; every expectation must hold.

Run: `git rev-parse worktree-issue-99-skill-prose-fixes`
Expected: `3c9709ca470bd473d49b39a611ca6cab258973db`.

Run: `git diff --name-only -G "env -u GITHUB_TOKEN|skills\.config\.json|Launch any subagent by type only" origin/main...HEAD -- home/common/agent-skills home/common/claude-code/skills justfile`
Expected: no output (no excluded #99 hunk added or touched).

Run: `git log --no-merges --format='%s%n%(trailers:key=Recovered-From,valueonly)' origin/main..HEAD -- home/common/agent-skills justfile`
Expected: the Task 2, 3, 4 and 5 subjects each followed by
`3c9709ca470bd473d49b39a611ca6cab258973db`; the Task 1 and Task 6 subjects
followed by an empty line. Subjects from `docs(plans):`/`docs(specs):` artifact
commits and review fix-ups are exempt.

Run: `git diff --name-only origin/main...HEAD -- '*.nix' CLAUDE.md .github docs`
Expected: no output (D17).
