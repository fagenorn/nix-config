# Task 3: Host acceptance: timing series, dry adjudication, measured cost and final gate

Spec section 6, per D7 and D12. This task changes no code. It builds the configuration, measures the built row check against the host's real Nodo checkout, dry-adjudicates a Nodo PR into `dev` with the built guard, writes the measured figures into the guard README, runs the final gate and records the acceptance evidence.

**Files:**
- Modify: `home/common/claude-code/README.md` (§ Guard policy, **Cost and offline behaviour** only)
- Create: `.agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md`

**Interfaces:**
- Consumes (Tasks 1–2): the built `claude-guard-row-check` (`guard-policy derive` with `CONTRACT_READER`) and the built `claude-bash-lifecycle-guard`, whose `--derive-bin` names that row check. (Host): the fleet registry and compiled policy under `~/.agents/state/`, the registered Nodo checkout `/Users/anis/Projects/nodocom` (`origin` over ssh, default `main`, integration `dev`) and the `gh` keyring credential.
- Produces: the acceptance record with rows `AC1`–`AC4`, and the README's measured cost sentence.

**Invariants:**
- Never run `just switch`. Run no command a dry payload names, create no worktree or branch, and push nothing. The installed `claude-guard-policy` runs only in step 2, and only when the host's compiled policy lacks the Nodo row.
- Every run of the check has `GITHUB_TOKEN` and `GH_TOKEN` unset and stdin at `/dev/null`.
- Thresholds are fixed (D7): AC1 passes when the median of 10 consecutive runs is ≤ 5.0 s, no run exceeds 10.0 s, and every run exits 0 with `outcome` `derived`, `default_branch` `main` and `integration_branch` `dev`. AC2 passes when the guard exits 0 with empty stderr.
- A fetch is detected per run by comparing Nodo's `refs/remotes/origin/main` and `refs/remotes/origin/dev` before and after it (D12). A run that fetched is named in the record. The fetch path is never forced.
- A missed threshold is reported, not tuned: stop after recording the series, set the verdict to `not met`, and return the record to the controller without editing code (D12).

- [ ] **Step 1: Build and locate the built paths**

Run (timeout 3600 s):

```bash
set -e -o pipefail
just build 2>&1 | tail -3
REQ=$(nix-store --query --requisites ./result)
CHECK=$(printf '%s\n' "$REQ" | grep -- '-claude-guard-row-check$')
GUARD_DIR=$(printf '%s\n' "$REQ" | grep -- '-claude-bash-lifecycle-guard$')
test "$(printf '%s\n' "$CHECK" | wc -l)" -eq 1
test "$(printf '%s\n' "$GUARD_DIR" | wc -l)" -eq 1
GUARD="$GUARD_DIR/bin/claude-bash-lifecycle-guard"
grep -qF -- "--derive-bin $CHECK" "$GUARD"
printf 'CHECK=%s\nGUARD=%s\n' "$CHECK" "$GUARD"
```

Expected: exit 0, and both paths printed. Any failing line means the build does not carry this branch's row check, so stop.

- [ ] **Step 2: Confirm the host has a Nodo row**

Run: `python3 -I -c 'import json,pathlib; p=pathlib.Path.home()/".agents/state/guard/policy.json"; r=json.loads(p.read_text())["derived_repositories"].get("elevenyellow/nodocom"); print(r and (r["default_branch"], r["integration_branch"]))'`
Expected: `('main', 'dev')`. Otherwise run the installed `claude-guard-policy` once (timeout 300 s) and re-run the check. If it still prints anything else, record AC2 as `not met` with that output and stop.

- [ ] **Step 3: AC1, the timing series**

Write this script to `<launch-scope scratch root>/i385-acceptance/ac1.py`:

```python
"""AC1: 10 consecutive runs of the built row check for Nodo (issue 385 D7, D12)."""
import json
import os
import statistics
import subprocess
import sys
import time

check, checkout = sys.argv[1], sys.argv[2]
env = {k: v for k, v in os.environ.items() if k not in ("GITHUB_TOKEN", "GH_TOKEN")}
refs = ("refs/remotes/origin/main", "refs/remotes/origin/dev")


def tips():
    return [subprocess.run(["git", "-C", checkout, "rev-parse", "--verify", "--quiet", ref],
                           capture_output=True, text=True).stdout.strip() for ref in refs]


walls, ok = [], True
for run in range(1, 11):
    before = tips()
    start = time.monotonic()
    done = subprocess.run([check, "--repository", "elevenyellow/nodocom"], env=env,
                          stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=60)
    wall = time.monotonic() - start
    walls.append(wall)
    try:
        report = json.loads(done.stdout)
    except ValueError:
        report = {"outcome": "unreadable", "row": None}
    row = report.get("row") or {}
    passed = (done.returncode == 0 and report.get("outcome") == "derived"
              and (row.get("default_branch"), row.get("integration_branch")) == ("main", "dev"))
    ok = ok and passed
    print(json.dumps({"run": run, "wall_s": round(wall, 2), "exit": done.returncode,
                      "outcome": report.get("outcome"),
                      "branches": [row.get("default_branch"), row.get("integration_branch")],
                      "fetched": tips() != before,
                      "refused": report.get("refused"), "cause": report.get("cause")}))
median, worst = statistics.median(walls), max(walls)
met = ok and median <= 5.0 and worst <= 10.0
print(json.dumps({"median_s": round(median, 2), "max_s": round(worst, 2), "met": met}))
sys.exit(0 if met else 1)
```

Run (timeout 900 s): `python3 -I <scratch>/i385-acceptance/ac1.py "$CHECK" /Users/anis/Projects/nodocom | tee <scratch>/i385-acceptance/ac1.log`
Expected: 11 lines, the last `{"median_s": <≤ 5.0>, "max_s": <≤ 10.0>, "met": true}`, exit 0. The script exits 1 when AC1 is missed.

- [ ] **Step 4: AC2, the dry adjudication**

Pick the head branch: run `git -C /Users/anis/Projects/nodocom worktree list --porcelain` and take the first worktree whose path exists, does not lie under a temporary or scratch directory, and whose `branch refs/heads/<b>` has `<b>` neither `main` nor `dev`. Record its path and branch.

Write to `<scratch>/i385-acceptance/ac2.py`:

```python
"""AC2: the built guard adjudicates a Nodo PR into dev from a Nodo worktree, dry."""
import json
import subprocess
import sys
import time

guard, cwd, branch = sys.argv[1], sys.argv[2], sys.argv[3]
command = (f'unset GITHUB_TOKEN && gh pr create --repo elevenyellow/nodocom --base dev '
           f'--head {branch} --title "x" --body "y"')
payload = {"hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": cwd,
           "tool_input": {"command": command}}
start = time.monotonic()
done = subprocess.run([guard], input=json.dumps(payload), capture_output=True, text=True,
                      timeout=40)
print(json.dumps({"exit": done.returncode, "stderr": done.stderr.strip(),
                  "stdout": done.stdout.strip(), "wall_s": round(time.monotonic() - start, 2),
                  "cwd": cwd, "branch": branch}))
sys.exit(0 if done.returncode == 0 and not done.stderr.strip() else 1)
```

Run (timeout 120 s): `python3 -I <scratch>/i385-acceptance/ac2.py "$GUARD" <worktree path> <branch> | tee <scratch>/i385-acceptance/ac2.log`
Expected: `"exit": 0`, `"stderr": ""`, exit 0. Nothing runs `gh`, because the guard only adjudicates.

- [ ] **Step 5: Write the measured cost**

Only if AC1 was met: in `home/common/claude-code/README.md` § Guard policy, **Cost and offline behaviour**, replace the estimate sentence Task 2 wrote with the measured figures, written from `ac1.log`. Give the date, the host `mbp`, 10 runs of the built row check for `elevenyellow/nodocom`, the median and the maximum, and how many runs fetched (with their times when any did). Leave the rest of the paragraph unchanged.

- [ ] **Step 6: Final gate**

Run: `just agent-workflow-tests 2>&1 | tail -4` (timeout 3600 s)
Expected: `OK`, exit 0.

Run: the guard-suite invocation (Global Constraints; it runs `just build` itself, timeout 1200 s; give the build 3600 s if it is cold).
Expected: `OK`.

- [ ] **Step 7: The acceptance record**

Create `.agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md` with the heading `# Acceptance record — issue 385` and one table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict`. Use the issue's four criteria verbatim (https://github.com/fagenorn/nix-config/issues/385) and the plan's Acceptance map kinds. Fill the columns as follows:
- `AC1`: Observed holds the 10 wall times, the median, the maximum and the fetched runs. Conditions name the host, the store path of `$CHECK`, that the tokens were unset and the date.
- `AC2`: Observed holds the exit, the stderr and the wall time. Conditions name the worktree and the branch, and whether step 2 ran `claude-guard-policy`.
- `AC3`: the guard-suite result and the `tests/test_guard_policy.py` refusal classes.
- `AC4`: the exit statuses of `just build`, `just agent-workflow-tests` and the guard suite.
- `Commit` is the head the evidence was taken on. Each `Verdict` is `met` or `not met`.

- [ ] **Step 8: Commit**

```bash
git add home/common/claude-code/README.md .agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md
launch-commit … -- -m "docs(issue-385): measured row-check cost and acceptance record"
```

Verify: `git show --stat HEAD -- home/common/claude-code/README.md .agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md | tail -3` lists the record. `grep -c '| AC[1-4] |' .agents/artifacts/plans/2026-10-13-issue-385-cheap-row-check.acceptance.md` prints `4`.
