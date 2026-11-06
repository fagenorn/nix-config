# Task 4: Install the launcher, join the gating suite, document the contract

**Files:**
- Modify: `lib/agent-tools.nix`
- Modify: `tests/test_agent_tools_launchers.py`
- Modify: `justfile`
- Modify: `python/README.md`

**Interfaces:**
- Consumes: Tasks 1–3: modules `agent_tools.forge_markers` and `agent_tools.forge_claim` (`main`, subcommands `acquire|renew|release|status`, verdicts, exit codes per D8), tests `tests/test_forge_markers.py` and `tests/test_forge_claim.py`.
- Produces: an installed `~/.agents/bin/forge-claim` launcher (the command-table row generates it; `home/common/agent-skills/default.nix` is unchanged); both test modules in the `agent-workflow-tests` member list; a `## forge-claim` contract section in `python/README.md`.

**Invariants:**
- `forge_markers` gets no command-table row (a library, no `main`).
- The command table stays alphabetical; `LAUNCHER_FLOOR` stays a floor.
- No change to `.github/workflows/ci.yaml` or `.github/branch-protection.json`: the `Agent Workflow Tests` job already runs `just agent-workflow-tests`.

- [ ] **Step 1: Write the failing check**

In `tests/test_agent_tools_launchers.py`, add `"forge-claim"` to `LAUNCHER_FLOOR` (after `"diff-scope"`) and add `623` to the issue list in the comment above it.

- [ ] **Step 2: Run it and watch it fail**

Run: `just agent-installed-skill-tests 2>&1 | grep -E "forge-claim|^(OK|FAILED)" | tail -5`
Expected: FAIL — `test_the_command_table_generates_each_deployed_command` subtest `launcher='forge-claim'`: `'forge-claim' not found`.

- [ ] **Step 3: Wire it**

1. `lib/agent-tools.nix`: add `"forge-claim"` to `commands` between `"diff-scope"` and `"guard-policy"`.
2. `justfile`, recipe `agent-workflow-tests`: add `    tests/test_forge_markers.py \` and `    tests/test_forge_claim.py \` directly after the `    tests/test_lane_triage.py \` line.
3. `python/README.md`: add a `## forge-claim` section after `## lane-triage`, one paragraph each, stating (issue 623; source entries `python -m agent_tools.forge_claim`, library `agent_tools.forge_markers`):
   - the marker grammar and liveness (D1), the smallest-live-id winner and the post / re-read / delete-own write with its listing assumption (D2), and that labels are filters while markers decide;
   - the four subcommands with their arguments, the holder format `<host>/<batch_id>` or `<host>/session-<id>`, `--branch` (D4), `--reason` (default `done`);
   - every verdict with its exit code (D8) and the output object's keys, including `released_by_owner`, `activity_at`, `owner_action_comment_id`, `owner_action_posted`, `label_removed`;
   - staleness: activity sources (D4), server `Date` as now (D5), `>= 24 h`, renewal bumps `renewed` (D3);
   - stale is never stolen: the one `owner-action` marker with its `- [ ] Release this claim` box, the label, and how the next `status` or `acquire` honours a ticked box (D6, D7);
   - that every `gh` child runs without `GITHUB_TOKEN`/`GH_TOKEN`, so the keyring credential answers.

- [ ] **Step 4: Verify**

Run: `just build 2>&1 | tail -3`
Expected: exit 0.
Run: `just agent-installed-skill-tests 2>&1 | tail -3`
Expected: `OK` (no failure in `tests/test_agent_tools_launchers.py`).
Run: `grep -c "tests/test_forge_markers.py\|tests/test_forge_claim.py" justfile`
Expected: `2`.
Run: `if ! grep -q '^## forge-claim' python/README.md; then exit 1; fi`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add lib/agent-tools.nix tests/test_agent_tools_launchers.py justfile python/README.md
git commit -m "feat(issue-623): install forge-claim and gate its suites

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
