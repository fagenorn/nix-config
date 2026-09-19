# Task 5: Author activation policy and prove the reviewed source generation

**Files:**
- Modify: `.agents/project.json`
- Modify: `home/common/agent-skills/tests/test_resolve_project.py`
- Modify only if the resolver reports projection drift: `AGENTS.md`, `CLAUDE.md`

**Interfaces:**
- Consumes: D6's pre-resolution bootstrap exception; the existing `nix-build` command object as the reviewed structural patch anchor; Tasks 1–4's green source contracts.
- Produces: `bindings.commands.nix-activate = {"argv":["just","switch"],"cwd":".","env":[]}`, a retained successful `ResolvedProject` for this task, and a buildable source generation with deploy still unsupported.

**Invariants:**
- This task never prints, parses, or reads raw `.agents/project.json`. Its only pre-resolution mutation is one narrow `apply_patch` that inserts the exact sibling command at the existing `nix-build` structural anchor (D6).
- Immediately after that patch, invoke `resolve-project resolve --repo-root <worktree>` exactly once, retain the successful object in memory for the task, and make no second project-policy read.
- `nix-activate` preserves exact argv words, authored cwd `.`, and empty env names; normalized cwd equals the project root. `bindings.deploy` remains adapter `none`, command null, config `{}`, and `capabilities.deploy.state` remains `unsupported`.
- Command entries do not participate in projection rendering, so the expected resolver result is success with current projections. Run `write-projections` only if the resolver specifically reports projection drift caused by the patch; inspect the two generated targets and restart this task's resolution boundary before any other mutation.
- Source build/tests finish and Task 5's full-lane review completes before Task 6 activates anything.

- [ ] **Step 1: Add the exact public-contract test**

Append to `CommittedContractTest`:

```python
def test_nix_activate_is_exact_and_deploy_stays_unsupported(self):
    code, out, err = run("resolve", "--repo-root", str(REPO_ROOT))
    self.assertEqual(code, 0, err or out)
    snapshot = json.loads(out)
    self.assertEqual(snapshot["bindings"]["commands"]["nix-activate"], {
        "argv": ["just", "switch"],
        "cwd": str(REPO_ROOT),
        "env": [],
    })
    self.assertEqual(snapshot["bindings"]["deploy"], {
        "adapter": "none", "command": None, "config": {},
    })
    self.assertEqual(snapshot["capabilities"]["deploy"], {
        "state": "unsupported", "reason_code": None, "repair_id": None,
    })
```

Run before the contract patch: `python3 home/common/agent-skills/tests/test_resolve_project.py CommittedContractTest.test_nix_activate_is_exact_and_deploy_stays_unsupported -v`

Expected: FAIL because `nix-activate` is absent. A deploy assertion failure indicates scope drift and must not be accepted.

- [ ] **Step 2: Apply the single bootstrap patch without reading the contract**

Use `apply_patch` against the existing `nix-build` command object captured by the retained caller contract. Insert exactly this sibling JSON member and change no other byte:

```json
"nix-activate": {
  "argv": ["just", "switch"],
  "cwd": ".",
  "env": []
}
```

Do not use `cat`, `jq`, Python, `rg`, `sed`, or an editor to inspect or rewrite `.agents/project.json`. A patch-context mismatch is a stop for review, not permission to read the raw file.

- [ ] **Step 3: Perform the first and only phase resolution**

Run: `resolve-project resolve --repo-root /Users/anis/tmp/nix-config/.worktrees/worktree-issue-100-strict-project-resolver`

Expected: exit 0; retain this `ResolvedProject` in memory. Assert from the returned object that the exact normalized `nix-activate` entry exists, deploy remains unsupported, and projections were accepted. Do not persist the output.

- [ ] **Step 4: Verify the command contract and source-only workflow suite**

Run: `python3 home/common/agent-skills/tests/test_resolve_project.py CommittedContractTest.test_nix_activate_is_exact_and_deploy_stays_unsupported -v`

Expected: PASS.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`

Expected: PASS across resolver, workflow, eval-harness, and lifecycle-guard tests while explicitly skipping only the installed descriptor. Any other skip/failure is incomplete.

- [ ] **Step 5: Build the managed generation without activating it**

Invoke the retained `bindings.commands.nix-build` entry exactly: preserve argv, use its absolute cwd, and unset only its declared env names.

Expected: `just build` exits 0. Inspect the build result/declaration tests: it contains `resolve-project` and the migrated skill trees, contains no installed declaration for `resolve-bindings`, and keeps deploy unsupported. Do not run `just switch` in this task.

- [ ] **Step 6: Commit for full-lane review**

```bash
git add .agents/project.json home/common/agent-skills/tests/test_resolve_project.py AGENTS.md CLAUDE.md
git commit -S -m "feat(project): declare local nix activation" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Expected: `AGENTS.md` and `CLAUDE.md` are staged only if Step 3 required projection repair. The committed source build and tests now receive Task 5's normal full-lane review; activation waits for that review to pass.
