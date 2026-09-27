# Task 6: Activate and verify the exact installed migration

**Files:**
- Verify after managed activation: `~/.agents/bin/resolve-project`
- Verify after managed activation: `~/.agents/bin/context-map-lint`
- Verify absent after managed activation: `~/.agents/bin/resolve-bindings`
- Verify after managed activation: `~/.agents/skills/**`
- Verify after managed activation: `~/.claude/skills/**`
- Repository source edits: none

**Interfaces:**
- Consumes: Task 5's reviewed commit and one phase-entry `ResolvedProject`; `bindings.commands.nix-build`, `bindings.commands.nix-activate`, and the ordinary `agent-workflow-tests` verification command.
- Produces: an activated local nix-config generation whose installed helpers and workflow consumers pass the same D4 matrix as source.

**Invariants:**
- Start only after Task 5's build, source tests, signed commit, and full-lane review are complete.
- Resolve once at this phase entry and retain the returned object. Invoke build, activation, and workflow verification by their resolved command entries, preserving argv, absolute cwd, and declared env-name removal.
- Activation is exactly `just switch` from the repository root. It does not use a deploy adapter and does not change `capabilities.deploy` from unsupported (D6).
- Installed Agents phase entries equal `SHARED_POLICY_ENTRIES`; installed Claude phase entries equal `SHARED_POLICY_ENTRIES | CLAUDE_POLICY_ENTRIES`. Missing roots or consumers fail rather than downgrading.
- Both installed trees and installed `context-map-lint` have zero `resolve-bindings`, `.claude/skills.config.json`, and `unsetGithubToken` references. `~/.agents/bin/resolve-bindings` is absent; `resolve-project` and `context-map-lint` are executable.
- Do not inspect, mutate, or onboard Nodo, Argus, or Arcwave. Do not run garbage collection, prune generations, or disturb issue-130 recovery generations.

- [ ] **Step 1: Resolve once and verify the reviewed head**

Run the phase-entry resolver once in the issue worktree and retain the successful snapshot. Assert the current clean HEAD contains Task 5's reviewed commit; the returned `nix-build` and `nix-activate` entries are exact; verification capability is available; deploy is unsupported.

Expected: one successful snapshot, clean `git status --short`, `nix-activate.argv == ["just","switch"]`, normalized cwd equals the worktree root, env is empty, and no capability repair is required.

- [ ] **Step 2: Rebuild the exact reviewed source**

Invoke retained `bindings.commands.nix-build` exactly.

Expected: exit 0 at the reviewed HEAD. A rebuild failure stops before activation.

- [ ] **Step 3: Activate through the authored command**

Invoke retained `bindings.commands.nix-activate` exactly: argv `just switch`, retained absolute cwd, empty env-removal list.

Expected: exit 0 and Home Manager switches the local managed paths to the reviewed generation. Do not invoke a deploy command or any external-repository action.

- [ ] **Step 4: Run the ordinary source-and-installed workflow suite**

Invoke the retained `agent-workflow-tests` command without `WORKFLOW_POLICY_SURFACE=source`.

Expected: PASS. `ProjectPolicySurfaceTest.test_installed_policy_surface_matches_source_contract` runs rather than skips, both managed roots exist, every expected consumer is present, and the same assertion helper passes for source and installed paths.

- [ ] **Step 5: Run explicit installed zero-reference/helper checks**

Run:

```bash
test -x "$HOME/.agents/bin/resolve-project"
test -x "$HOME/.agents/bin/context-map-lint"
test ! -e "$HOME/.agents/bin/resolve-bindings"
if rg -n 'resolve-bindings|\.claude/skills\.config\.json|unsetGithubToken' "$HOME/.agents/skills" "$HOME/.claude/skills" "$HOME/.agents/bin/context-map-lint"; then exit 1; fi
```

Expected: exit 0 and no grep output. This gate scopes exactly to nix-config's installed helper and skill surfaces; it does not search unrelated repositories or historical source artifacts.

- [ ] **Step 6: Reconfirm installed resolver behavior at the managed project**

Run the installed `~/.agents/bin/resolve-project resolve --repo-root /Users/anis/tmp/nix-config/.worktrees/worktree-issue-100-strict-project-resolver` as a fresh diagnostic invocation.

Expected: exit 0 with the four-member snapshot, exact `nix-activate`, deploy unsupported, and current projections. This diagnostic is separate from the phase owner's retained policy and must not be reused to drive another workflow action.

- [ ] **Step 7: Record the no-source-change completion**

Run: `git status --short`

Expected: empty. Task 6 makes no repository commit; the durable result is the activated generation plus passing installed gates. Report the build, activation, ordinary suite, explicit zero-reference check, and installed resolver result. State that external repositories and recovery generations were untouched.
