# Task 1: One application of the agent-tools builder

Spec § Solution 1 and § One application of the builder; per D1 (first guarantee) and D2. After this task, `home/common/agent-tools/default.nix` is the only module that applies `lib/agent-tools.nix`. It sets the home-manager module argument `agentTools`, and the agent-skills and claude-code modules take `agentTools` as an argument instead of applying the builder themselves. Both sites already produced the same derivations, so the build does not change: the agent_tools package and all 26 launchers keep their store paths. A difference is investigated and fixed, never accepted.

**Files:**
- Create: `home/common/agent-tools/default.nix`
- Modify: `home/common/agent-skills/default.nix` (the argument set; delete the `let`-bound `agentTools`)
- Modify: `home/common/claude-code/default.nix` (the argument set; delete the `let`-bound `agentTools`)
- Modify: `home/common/claude-code/README.md` (§ Guard policy, the **Row check.** paragraph: one sentence)

**Interfaces:**
- Consumes: `lib/agent-tools.nix`, `{ pkgs }: { launchers; scriptLauncher; }`, unchanged. `launchers` is an attribute set of launcher store files keyed by command name, and `scriptLauncher` is a function `name: script:` returning a store file. `pkgs` is home-manager's module `pkgs` (`home-manager.useGlobalPkgs = true` in `lib/helpers.nix`). `libx.scanPaths ./common` in `home/default.nix` imports the new directory with no list to edit.
- Produces: the module argument `agentTools`, holding exactly the builder's value, visible to every home module. Task 2's throwaway red edit and its README text rely on this name.

**Invariants:**
- Exactly one `.nix` file under `home`, `hosts` and `lib` applies the builder: the regex `agent-tools\.nix[[:space:]]*\{` matches only in `home/common/agent-tools/default.nix`.
- `nix-store --query --requisites ./result | grep -- '-agent-tools-' | sort` is byte-identical before and after. It holds 27 lines: 25 command launchers, `agent-tools-workflow-state` and one `python3.13-agent-tools-0.1.0`.
- Every use site keeps its text and the comment above it: `agentToolFiles`, `".agents/bin/workflow-state"`, `cacheProxyArgs`, `claudeGuardPolicy`, `lifecycleGuardRowCheck` and the context-meter hook still read `agentTools.…` exactly as at base.
- `agentTools` is never read to compute `imports`.

- [ ] **Step 1: Record the baseline**

From the worktree root at the task's starting commit, run the Build, then:

```bash
nix-store --query --requisites ./result | grep -- '-agent-tools-' | sort > "$SCRATCH/agent-tools-before.txt"
wc -l < "$SCRATCH/agent-tools-before.txt"
```

Expected: `27`.

- [ ] **Step 2: Watch the single-application gate fail**

```bash
test "$(grep -rlE --include='*.nix' 'agent-tools\.nix[[:space:]]*\{' home hosts lib)" = home/common/agent-tools/default.nix
```

Expected: exit 1, because the grep lists `home/common/agent-skills/default.nix` and `home/common/claude-code/default.nix`.

- [ ] **Step 3: Write the implementation**

Create `home/common/agent-tools/default.nix` as a home-manager module taking
`{ pkgs, ... }`. Its sole definition is `_module.args.agentTools`, the result of
`import ../../../lib/agent-tools.nix { inherit pkgs; }`. Add a concise comment
explaining that one shared application prevents consumers silently diverging
(issue 467 D2). The module neither exports the environment separately nor reads
`agentTools` to compute imports.

In `home/common/agent-skills/default.nix`:
- the argument set becomes `{ inputs, lib, pkgs, agentTools, ... }:`, keeping the file's one-name-per-line layout;
- delete the line `  agentTools = import ../../../lib/agent-tools.nix { inherit pkgs; };`. The three comment lines above it (`# Each command-table row of lib/agent-tools.nix becomes ~/.agents/bin/<name>.` and the two after it) now sit directly above `agentToolFiles`.

In `home/common/claude-code/default.nix`:
- add `agentTools,` to the argument set, on its own line after `libx,`;
- delete the line `  agentTools = import ../../../lib/agent-tools.nix { inherit pkgs; };` from the `let` block. `agentPlugins` stays.

Stage the new file: `git add home/common/agent-tools/default.nix`.

- [ ] **Step 4: Verify the refactor**

1. Run Step 2's command again. Expected: exit 0.
2. Run the Build. Expected: exit 0, with the last line `Done. The new configuration is /nix/store/…`.
3. Compare the store paths:

```bash
nix-store --query --requisites ./result | grep -- '-agent-tools-' | sort > "$SCRATCH/agent-tools-after.txt"
diff -u "$SCRATCH/agent-tools-before.txt" "$SCRATCH/agent-tools-after.txt"
```

Expected: exit 0 with no output. On a darwin host, run the Build there too, or say in the report that it was not run (Global Constraints).

- [ ] **Step 5: Document the shared launcher**

In `home/common/claude-code/README.md` § Guard policy, find the **Row check.** paragraph. Its second sentence describes the script and ends with the words "it is not installed on `PATH`.". Directly after that sentence, in the same paragraph, insert:

```markdown
That launcher, and the one `claude-guard-policy` execs, come from the `agentTools` module argument, which `home/common/agent-tools/default.nix` sets as the one application of `lib/agent-tools.nix` per home configuration, so the row check, the compile wrapper and every `~/.agents/bin` launcher exec one agent_tools environment (issue 467).
```

Gate (exits 1 at the starting commit, because the README never names `agentTools`):

```bash
grep -qF 'come from the `agentTools` module argument' home/common/claude-code/README.md || exit 1
```

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-tools/default.nix home/common/agent-skills/default.nix \
  home/common/claude-code/default.nix home/common/claude-code/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "refactor(agent-tools): apply the builder once per home configuration (issue 467)" \
  -m "<session trailer lines>"
```

Scope check: `git diff --stat HEAD~1 -- home/common/agent-tools home/common/agent-skills/default.nix home/common/claude-code/default.nix home/common/claude-code/README.md` lists exactly those four files.
