# In-process Builder CLI and Per-class Fixtures Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The builder CLI helper runs workflow-state in the test process with its stdin and working directory honoured. The issue-207 delivery and the orchestrate fixture project are built once per test class, and each test gets its own copy.

**Architecture:** Task 1 gives the shared in-process runner `subprocess.run`'s `input`, `cwd` and `text`, and restores the process directory on every outcome. Task 2 routes `BuilderHarness.cli` through the runner, which reaches every class that inherits it. Tasks 3 and 4 cache the migration ledger text and the orchestrate project template per concrete test class, and copy them per call.

**Tech stack:** the Python 3.12+ standard library (`io`, `os`, `shutil`, `tempfile`, `unittest`, `sys.addaudithook`), git, and one `justfile` recipe line.

Spec: `.agents/artifacts/specs/2026-11-02-issue-500-inprocess-delivery-cli-class-fixtures-design.md`. A bare "Dn" cites its `## Decision ledger`, to which this plan appends D9 and D10, and its standards review D11. "262 Dn" and "498 Dn" cite those issues' ledgers. Issue: https://github.com/fagenorn/nix-config/issues/500 (parent: issue 436).

## Global Constraints

- Base: `0a25b8072c8252d069774f68e75981c39c137691` (`0a25b807`), under the spec and plan commits. The tasks land in index order, each on the one before.
- Standard library only, on Python 3.12 (the hosted runner) and 3.13 (the dev hosts), Linux and darwin.
- This is a test-only change. These stay unchanged: every product file (`workflow-state.py` and its modules, `artifact_budget.py`, everything under `python/agent_tools`), every file outside the plan's `Files:` paths (D1), every existing `test_*` body, and `PYTHONDONTWRITEBYTECODE` in the helper's and the world's environments (D8).
- Committed code adds no by-path load, `importlib` or `sys.path` machinery (agent-helpers rule 3). The scratch tools use it, and they are never committed (262 D6).
- A new comment or docstring cites this issue's ledger as `issue 500 Dn`. The bare `Dn` already in these files cite other issues and stay. Comments and docstrings describe the code at their task's commit. No `TODO` or `FIXME`.
- Run every command from the worktree root, in the foreground, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout above its duration. Commit through `launch-commit … -- <git commit args>` (it runs `git commit <args>`), signed, ending with the session's trailers. Before any gate, export `SCRATCH` as the directory that `launch-scope scratch …` prints. Scratch files go there.
- Focused test form (timeout 1800 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest <path>… [-k <pattern>]… 2>&1 | tail -6'`.
- **Coverage gate** (262 D7), run by every task before it commits (timeout 1800 s): `bash "$SCRATCH/coverage-gate.sh"`, with the script below written there. It fails on a lost test ID, an import failure or a changed existing `test_*` body, and on success prints `COVERAGE-GATE-OK base 3575 head <n> test ids`, where `<n>` is the count each task names.

```bash
set -euo pipefail
BASE=0a25b8072c8252d069774f68e75981c39c137691
work=$(mktemp -d "${SCRATCH:?}/issue500-gate-XXXXXX"); trap 'rm -rf "$work"' EXIT HUP INT TERM
git archive "$BASE" | tar -x -C "$work"
ids() { (cd "$1" && PYTHONPATH=python python3 - <<'PY'
import re, unittest
from unittest.main import _convert_names
block = open("justfile", encoding="utf-8").read().split("agent-workflow-tests *args:\n", 1)[1].split("\n\n", 1)[0]
def walk(suite):
    for item in suite:
        yield from (walk(item) if isinstance(item, unittest.TestSuite) else (item.id(),))
found = sorted(walk(unittest.defaultTestLoader.loadTestsFromNames(_convert_names(re.findall(r"\S+\.py", block)))))
broken = [i for i in found if i.startswith("unittest.loader.")]
if broken: raise SystemExit(f"import failures: {broken}")
print("\n".join(found))
PY
) }
ids "$work" > "$work/base.ids"; ids . > "$work/head.ids"
missing=$(LC_ALL=C comm -23 <(LC_ALL=C sort "$work/base.ids") <(LC_ALL=C sort "$work/head.ids"))
if [ -n "$missing" ]; then echo "test ids lost:"; echo "$missing"; exit 1; fi
python3 - "$work" <<'PY'
import ast, re, sys
work = sys.argv[1]
block = open(f"{work}/justfile", encoding="utf-8").read().split("agent-workflow-tests *args:\n", 1)[1].split("\n\n", 1)[0]
def bodies(path):
    out = {}
    for node in ast.walk(ast.parse(open(path, encoding="utf-8").read())):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name.startswith("test"):
                    out[f"{node.name}.{item.name}"] = ast.dump(item)
    return out
changed = []
for path in re.findall(r"\S+\.py", block):
    old, new = bodies(f"{work}/{path}"), bodies(path)
    changed += [f"{path}::{k}" for k in sorted(old) if new.get(k) != old[k]]
if changed: raise SystemExit("test bodies differ:\n" + "\n".join(changed))
PY
echo "COVERAGE-GATE-OK base $(wc -l < "$work/base.ids" | tr -d ' ') head $(wc -l < "$work/head.ids" | tr -d ' ') test ids"
```

- **Final gate** (sdd, once on the final head), in order:
  1. The Coverage gate. Expected: `head 3580`.
  2. `just agent-workflow-tests` (timeout 3600 s). It exits 0 and ends with `suite-runner: summary … failed=0`. Keep its timing rows for `test_delivery_workflow`, `test_attempt_migration` and `test_orchestrate_control`.
  3. `just build` (timeout 3600 s), which exits 0.
  4. The paired measurement (D10, timeout 3600 s). Write the driver below to `$SCRATCH/paired-timings.py`, then run `git worktree add --detach "$SCRATCH/base-500" 0a25b8072c8252d069774f68e75981c39c137691`, then `python3 "$SCRATCH/paired-timings.py" "$SCRATCH/base-500" .`, which exits 0. Then run `git worktree remove --force "$SCRATCH/base-500"`. The `workflow_state` column of `test_delivery_workflow` and `test_attempt_migration`, and the `write_projections` column of `test_orchestrate_control`, are lower at head than at base.
  5. The controller records step 2's three rows and step 4's table in acceptance-record row `AC2` as branch direction. The row stays `unverified` (D8).

  A failure in a module this plan does not touch is re-run once, with both outputs recorded. A second failure is BLOCKED and returned.

```python
"""Scratch only (262 D6, D10): serial paired timings and spawn counts, base then head."""
import os, re, subprocess, sys, time
base, head = (os.path.abspath(p) for p in sys.argv[1:3])
modules = sys.argv[3:] or ["home/common/agent-skills/tests/test_delivery_workflow.py",
                           "home/common/agent-skills/tests/test_attempt_migration.py",
                           "tests/test_orchestrate_control.py"]
HOOK = r'''import atexit, sys, unittest
n = [0, 0, 0]
def hook(event, args):
    if event == "subprocess.Popen":
        line = " ".join(map(str, args[1] if isinstance(args[1], (list, tuple)) else [args[1]]))
        n[0] += 1; n[1] += "workflow-state.py" in line; n[2] += "write-projections" in line
sys.addaudithook(hook)
atexit.register(lambda: sys.stderr.write("SPAWNS %d %d %d\n" % tuple(n)))
unittest.main(module=None, argv=["unittest", sys.argv[1]])
'''
print("module\ttree\ttests\twall_s\tpopen\tworkflow_state\twrite_projections\tload1\texit", flush=True)
bad = False
for module in modules:
    for label, tree in (("base", base), ("head", head)):
        env = {**os.environ, "PYTHONPATH": os.path.join(tree, "python"),
               "GIT_CONFIG_PARAMETERS": "'maintenance.auto'='false' 'gc.auto'='0'"}
        load, start = os.getloadavg()[0], time.monotonic()
        done = subprocess.run([sys.executable, "-c", HOOK, module], cwd=tree, env=env,
                              capture_output=True, text=True)
        ran = re.search(r"^Ran (\d+) tests?", done.stderr, re.M)
        spawns = re.search(r"^SPAWNS (\d+) (\d+) (\d+)$", done.stderr, re.M)
        print(module, label, ran and ran.group(1), f"{time.monotonic() - start:.1f}",
              *(spawns.groups() if spawns else "---"), f"{load:.1f}", done.returncode,
              sep="\t", flush=True)
        bad |= done.returncode != 0 or not ran
sys.exit(1 if bad else 0)
```

## Test seams

- Seam 1: `home/common/agent-skills/tests/test_inprocess_cli.py::InProcessRunnerTest`. It compares the runner with a real child row by row, and checks that the process is restored on every outcome (Task 1; D2, D3, D6).
- Seam 2: `home/common/agent-skills/tests/test_delivery_workflow.py::BuilderTransportTest`. It runs the helper inside `recorded_spawns()` with a relative `--repo-root` under `cwd` and a malformed stdin (Task 2; D1, D6).
- Seam 3: `home/common/agent-skills/tests/test_attempt_migration.py::MigrateOnWriteTest::test_each_delivered_207_call_is_the_callers_own_copy` (Task 3; D4, D6).
- Seam 4: `tests/test_orchestrate_control.py::WorktreeTest::test_a_world_never_sees_another_worlds_git_changes` (Task 4; D5, D6).
- Scratch-only checks, never committed (D10): the driver-run counter (Task 3), the build counter (Task 4), the mutations (Tasks 3 and 4) and the paired timings (final gate).
- Regression net, unchanged: `test_attempt_custody`'s custody fence (it fails if `cwd` is dropped), every `build-delivery --input -` test, the byte-exact stderr pins, and a green run of the ten modules that inherit the helper (Task 2).

## Delivery estimate and boundaries

These are estimates. Seven files change, besides this plan and the spec ledger, for about +270/−35 lines, or about 15 KB of diff in one review package:
- `_inprocess_cli.py` grows by about 25 lines net, and the new `test_inprocess_cli.py` adds about 90.
- `test_delivery_workflow.py` grows by about 30 lines, `test_attempt_migration.py` by about 35, `orchestrate_world.py` by about 30, and `test_orchestrate_control.py` by about 16.
- `justfile` gains one line.

Task 1 ships alone. Task 2 needs Task 1. Tasks 3 and 4 are correct on their own: Task 3's driver gets fast only after Task 2, and Task 4 needs no other task.

## Task index

Task 1 — The in-process runner honours stdin, cwd and bytes — `home/common/agent-skills/tests/_inprocess_cli.py`, `home/common/agent-skills/tests/test_inprocess_cli.py`, `justfile` — full — [task-1.md](2026-11-02-issue-500-inprocess-delivery-cli-class-fixtures.tasks/task-1.md)
Task 2 — The builder CLI helper runs workflow-state in-process — `home/common/agent-skills/tests/test_delivery_workflow.py` — full — [task-2.md](2026-11-02-issue-500-inprocess-delivery-cli-class-fixtures.tasks/task-2.md)
Task 3 — Issue 207 is delivered once per migration test class — `home/common/agent-skills/tests/test_attempt_migration.py` — full — [task-3.md](2026-11-02-issue-500-inprocess-delivery-cli-class-fixtures.tasks/task-3.md)
Task 4 — The orchestrate fixture project is built once per test class — `tests/orchestrate_world.py`, `tests/test_orchestrate_control.py` — full — [task-4.md](2026-11-02-issue-500-inprocess-delivery-cli-class-fixtures.tasks/task-4.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 4 | The four seams in one run (Task 4, Step 4, check 4): `test_inprocess_cli.py::InProcessRunnerTest` (two tests), `test_delivery_workflow.py::BuilderTransportTest`, `test_attempt_migration.py::MigrateOnWriteTest::test_each_delivered_207_call_is_the_callers_own_copy` and `test_orchestrate_control.py::WorktreeTest::test_a_world_never_sees_another_worlds_git_changes`, `Ran 5 tests` and `OK`. `just agent-workflow-tests` runs them all, locally and on the PR's Linux CI run. |
| AC2 | evidence | Task 4 | Post-merge only, measured by ship (D8). Conditions: the merge commit's push run to `main`, job "Agent Workflow Tests (advisory)", hosted ubuntu-24.04, default worker cap. Run these two commands for that run and again for the last push run to `main` before the merge. First `gh run view <run-id> --repo fagenorn/nix-config --log > <log>`. Then `awk '/Agent Workflow Tests \(advisory\)/ && index($0, "test_delivery_workflow.py") + index($0, "test_attempt_migration.py") + index($0, "test_orchestrate_control.py") && match($0, /suite-runner: +[0-9]+\.[0-9]s /) { split(substr($0, RSTART, RLENGTH), f, " "); s += f[2] } END { printf "%.1f\n", s }' <log>`. It sums the three modules' wall seconds from the timing rows and skips their `end` lines. Threshold: the merge run's sum is at least 120.0 s below the earlier run's (419.7 s on run 41314186007 when the issue was filed). Acceptance-record row `AC2` stays `unverified` on the branch and carries the final gate's branch direction. Ship fills it after the merge. |

## Decisions

- The runner's keywords, directory handling and process-wide caches: D2, D3, D7 (Task 1).
- The helper's transport and what stays a real process: D1, D2 (Task 2).
- The migration ledger text per class: D4. The world template per class: D5. The cache shape for both: D9 (Tasks 3 and 4).
- The four seams: D6. The scratch-only falsifiers and the paired base worktree: D10 (Tasks 3 and 4, final gate). Seam 3 red before its change, and `pipefail` on every counter command: D11 (Tasks 3 and 4).
- AC2 as post-merge evidence, and the overlap with #499: D8.

## Standards review provenance

- Reviewer: Codex (gpt-6-astra, xhigh), isolated read-only mode, no focus; base `0a25b8072c8252d069774f68e75981c39c137691`; no fallback.
- Findings: 0 blocking, 2 should-fix, 0 discussion. Accepted 2 (SF-001: Task 3's guard is red before its change; SF-002: `set -o pipefail` on the Task 3 and Task 4 counter commands; both D11), rejected 0, deferred 0.

---
