# Task 2: Deploy the review-range command

**Files:**
- Modify: `lib/agent-tools.nix`
- Modify: `justfile`
- Modify: `tests/test_agent_tools_launchers.py`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`

**Interfaces:**
- Consumes: Task 1's `python/agent_tools/review_range.py` (module `agent_tools.review_range`, parser `prog="review-range"`) and `tests/test_review_range.py`.
- Produces: an installed launcher `~/.agents/bin/review-range` that runs `python3 -I -m agent_tools.review_range`, generated from the command table. Task 4's skill prose calls it as `~/.agents/bin/review-range`.

**Invariants:**
- `lib/agent-tools.nix`'s `commands` list stays the only command-to-module mapping. The new row is the string `"review-range"`, placed after `"review-package"`. No other Nix file changes, because `home/common/agent-skills/default.nix` already turns every row into a launcher.
- `just agent-workflow-tests` runs `tests/test_review_range.py` (seam 1).
- The launcher floor and the shell-fence vocabulary name the new command, so a dropped row or an unknown fence head fails a test.

- [ ] **Step 1: Write the failing assertions**

In `tests/test_agent_tools_launchers.py`, add `"review-range"` to the end of the `LAUNCHER_FLOOR` tuple, and change the comment above it from `The commands #175, #179, #177 and #249 accepted as launchers` to `The commands #175, #179, #177, #249 and #264 accepted as launchers`.

In `home/common/agent-skills/tests/test_shell_example_contracts.py`, add `"review-range"` to `COMMAND_VOCABULARY`, alphabetically between `"review-package"` and `"rg"`.

- [ ] **Step 2: Watch the deployment gate fail**

Run: `rg -c '"review-range"' lib/agent-tools.nix || echo MISSING`
Expected at the starting commit: `MISSING`.

Run: `rg -c 'tests/test_review_range.py' justfile || echo MISSING`
Expected at the starting commit: `MISSING`.

- [ ] **Step 3: Add the command-table row and the recipe line**

In `lib/agent-tools.nix`, insert the line `    "review-range"` right after `    "review-package"` in `commands`.

In the `justfile`'s `agent-workflow-tests` recipe, insert the line `    tests/test_review_range.py \` right after `    tests/test_launch_commit.py \`.

- [ ] **Step 4: Verify**

Run: `rg -c '"review-range"' lib/agent-tools.nix && rg -c 'tests/test_review_range.py' justfile`
Expected: `1` and `1`.

Run: `timeout 1800 just build 2>&1 | tail -5`
Expected: exit 0. A row whose module is missing fails evaluation with `agent-tools: command review-range has no module`, and a broken import fails the import check.

Run the installed-launcher seam against the built home:

```bash
set -euo pipefail
set -- $(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
[ "$#" -eq 1 ]
AGENT_SKILLS_INSTALLED_HOME="$1" timeout 900 python3 -m unittest tests/test_agent_tools_launchers.py 2>&1 | tail -3
test -x "$1/.agents/bin/review-range"
"$1/.agents/bin/review-range" --help | head -1
```

Expected: `OK`, then `usage: review-range …`.

Run: `PYTHONPATH=python timeout 600 python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py tests/test_review_range.py 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add lib/agent-tools.nix justfile tests/test_agent_tools_launchers.py home/common/agent-skills/tests/test_shell_example_contracts.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- -m "feat(agent-tools): deploy the review-range command (#264)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01QpGEgn23dNP1QXn2of1cto"
```
