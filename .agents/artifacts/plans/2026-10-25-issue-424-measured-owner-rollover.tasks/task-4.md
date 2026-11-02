# Task 4: Registration beside the guard, the command row and the contract docs

Spec § Registration and docs, test seam 4; per D1, D2, D3, D9 and D12. The `context-meter` command gets its command-table row and becomes the second command hook in the one Bash `PreToolUse` entry; the guard suite's discovery learns about it; both READMEs document the meter.

**Files:**
- Modify: `lib/agent-tools.nix` (`commands` gains `"context-meter"`, after `"context-map-lint"`)
- Modify: `home/common/claude-code/default.nix` (`settings.hooks.PreToolUse`)
- Modify: `tests/test_claude_permission_guard.py` (`ClaudePermissionGuardTest.setUpClass` discovery)
- Modify: `tests/test_agent_tools_launchers.py` (`LAUNCHER_FLOOR` and the issue list in its comment)
- Modify: `home/common/claude-code/README.md` (new `## Context meter` section)
- Modify: `python/README.md` (new `## context-meter` section)

**Interfaces:**
- Consumes (Tasks 1–3): the module `agent_tools.context_meter`, run with no arguments, and its contract as implemented; read the four `context_meter*.py` modules and `phase_budget.py` before writing either README.
- Produces: the built settings' single `matcher = "Bash"` entry holds exactly two command hooks, the unchanged guard (`${lifecycleGuard}/bin/claude-bash-lifecycle-guard`, timeout 30) and then the meter (`${agentTools.launchers.context-meter}`, a store path ending in `-agent-tools-context-meter`, timeout 10, no `args`); `~/.agents/bin/context-meter` in the built home.

**Invariants:**
- The guard's hook attrset and `lifecycle_guard.py` are byte-for-byte unchanged; the adversarial table in `tests/test_claude_permission_guard.py` is unchanged (AC4).
- The meter hook carries no `args`, no permission-related key, and no matcher of its own (D2).
- README sentences describe the code as it is at this commit (Global Constraints).

- [ ] **Step 1: Write the failing test**

In `tests/test_claude_permission_guard.py`'s `setUpClass`, replace the block from `command_hooks = [` through `command_hook = command_hooks[0]` with:

```python
        command_hooks = [
            hook
            for hook in matches[0].get("hooks", [])
            if hook.get("type") == "command"
        ]
        # Issue 424: the context meter is the entry's second command hook.
        guards = [hook for hook in command_hooks if str(hook.get("command", "")).endswith(
            "/bin/claude-bash-lifecycle-guard")]
        meters = [hook for hook in command_hooks if str(hook.get("command", "")).endswith(
            "-agent-tools-context-meter")]
        if len(command_hooks) != 2 or len(guards) != 1 or len(meters) != 1:
            raise AssertionError(
                f"expected exactly the guard and the context meter, found {command_hooks!r}")
        meter = meters[0]
        if meter.get("timeout") != 10 or meter.get("args", []) != []:
            raise AssertionError(f"context meter must take no args and time out at 10: {meter!r}")
        cls.meter = Path(meter["command"])
        if " " in meter["command"] or not cls.meter.is_absolute() or not os.access(
                cls.meter, os.X_OK):
            raise AssertionError(f"meter is not an executable absolute path: {meter!r}")
        command_hook = guards[0]
```

Every check after `command_hook = …` stays as it is. In `tests/test_agent_tools_launchers.py`, add `"context-meter"` to `LAUNCHER_FLOOR` after `"context-map-lint"`, and extend the comment above it to `#353, #403 and #424` (that list keeps its existing `#N` form).

- [ ] **Step 2: Run the test and watch it fail**

Build (Global Constraints, timeout 3600 s), then run the guard suite (timeout 1800 s). Expected: `ERROR: setUpClass` with `expected exactly the guard and the context meter, found [{… claude-bash-lifecycle-guard …}]`.

- [ ] **Step 3: Write the minimal implementation**

`lib/agent-tools.nix`: add `"context-meter"` to `commands` directly after `"context-map-lint"`.

`home/common/claude-code/default.nix`: in `hooks.PreToolUse`'s Bash entry, after the guard's attrset, add a comment and the meter's attrset:

```nix
          # The context meter (issue 424): rewrites each `workflow-state progress` call to
          # carry this agent's measured context and, once per crossing of the hand-off
          # threshold, tells an owner to run its phase gate. It never grants or denies,
          # so the guard above still judges every call.
          {
            type = "command";
            command = "${agentTools.launchers.context-meter}";
            timeout = 10;
          }
```

`home/common/claude-code/README.md`: a new `## Context meter` section directly before `## Guard/core decision`, a few short paragraphs covering, from the code: its registration (second command hook in the same Bash entry, the `context-meter` launcher, timeout 10 s); what it rewrites (every `workflow-state progress` invocation drops each argparse spelling of `--context-tokens` and gets the measured value right after `progress`; unmeasured calls only lose the model's value; ceiling and headroom flags untouched; a rewrite that fails its proof passes through unchanged); what it injects (the per-call note, and the once-per-crossing instruction to owners, where owners are the agents that ran `workflow-state progress`, `workflow-state mark-progress` or `sdd-gate` with `--action-id`, and the threshold is `agent_tools.phase_budget`'s context ceiling less headroom); where its state lives (`~/.agents/state/context-meter/`, one file per session and agent, never pruned — a known limitation); that it grants nothing (no permission decision, never exit 2, the guard judges the original command) and fails open (a user-visible `systemMessage`, exit 1 on an unexpected error); the known limitation that a guard denial of the call carrying the instruction can swallow it; and that hosts without hooks send no count. Add one sentence at the end of `## Allow surface and lifecycle guard`'s first paragraph pointing to the new section. Keep the detailed contract out: link `python/README.md`.

`python/README.md`: a new `## context-meter` section directly after `## lane-triage` with the command's contract: stdin payload and stdout shape; the transcript it reads (D4 rules, the 1 MiB window, the sum `agent-costs` also uses); the rewrite (D15 spellings, `--`, redirections, the proof, the refusal shapes) and the four fixed texts with their reasons; owners and the crossing transition; the state file name, content and `flock`; the threshold from `agent_tools.phase_budget`, which also holds `workflow-state progress`'s four defaults; exit codes.

- [ ] **Step 4: Verify**

Build again, then run the guard suite. Expected: `OK`, with `Ran <n> tests` equal to the count printed by the same suite at the task's starting commit (run it there first if unsure; discovery adds no test). Then (timeout 3600 s):

```bash
bash -c 'set -o pipefail; just agent-installed-skill-tests 2>&1 | tail -4'
just show-claude-settings | jq -e '.hooks.PreToolUse | length == 1 and (.[0].hooks | map(.timeout)) == [30, 10]'
```

Expected: `OK`, then `true`.

- [ ] **Step 5: Commit**

```bash
git add lib/agent-tools.nix home/common/claude-code/default.nix tests/test_claude_permission_guard.py \
  tests/test_agent_tools_launchers.py home/common/claude-code/README.md python/README.md
launch-commit … -- -m "feat(claude-code): register the context meter beside the lifecycle guard (issue 424)" -m "<session trailers>"
```

Verify: `git status --short -- lib home tests python` prints nothing, and `git diff HEAD~1 -- home/common/claude-code/lifecycle_guard.py` prints nothing.
