# Issue 262 Test Suite Speed Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Halve the serial wall time of `just agent-workflow-tests` and keep every module at or under 90 s, with the same collected test IDs and unchanged `test_*` bodies (https://github.com/fagenorn/nix-config/issues/262).

**Architecture:** Fix the two production root causes first: the workflow-state CLI's per-call delivery reload (H1) and the review Git authority's spawn-heavy guard and repeated closures (H2). Then run the dominant lifecycle harness in process (H3). Share derived fixtures per class only where a module still measures above 90 s (H4). The [spec](../specs/2026-10-06-issue-262-test-suite-speed-design.md) owns the profile, the hotspots and the decision ledger D1–D11.

**Tech stack:** Python 3 standard library, unittest, Git plumbing, just, Nix.

## Global Constraints

- Base commit `31be7292b40159c5a3f49cc24f21b3292ba4ce89` (`BASE`). Work only in `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-262-orchestrated`. Never touch the primary checkout `/Users/anis/tmp/nix-config`.
- No test is added, deleted, skipped, renamed or weakened. No `test_*` method body changes. The collected test-ID list equals `BASE`'s (2077 IDs at `BASE`) after every task (per D7). Only support modules, `setUp`/`setUpClass` and the two `LifecycleHarness` methods may differ.
- No parallel or sharded execution, and no host-load scheduling (per D8). Do not change any `just` recipe, `.github/workflows/ci.yaml`, `lib/*.nix` or an installed launcher.
- No cache spans review entry-point calls. Every `_closure` still runs `_guard` before and after its walk, and the comment "No retained cache: every API boundary observes current metadata and objects." stays in `review_git.py` verbatim (per D2, D3).
- Every error code, `WorkflowError` text and exit code an existing test can observe is unchanged. A change that alters one is reverted at that site, never fixed by editing a test.
- Outputs are byte-identical. That includes the committed retained evidence under `tests/fixtures/retained-review-evidence/`, which `tests/test_review_evidence.py` replays.
- Nothing measured is committed: timings, spawn counts and probe scripts go to `${TMPDIR:-/tmp}`, and the profile goes into the PR description (per D6).
- Commits go through `launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- <git commit args>`, run in the worktree. They are SSH-signed, with subjects of 64 bytes or fewer, and end with the session's `Co-Authored-By:` and `Claude-Session:` trailer lines.
- Payload discipline: summarize test output to the `Ran N tests`/`OK`/failing lines, and write long logs to `${TMPDIR:-/tmp}` and pass their paths. Each command that runs longer than 2 minutes runs with a bounded `timeout`.

## Test seams

- The existing suite is the only seam (per the spec's § Test seams). The adversarial review-history tests hold H2. The lifecycle and delivery suites hold H1. The unchanged stdout, stderr and return-code assertions in `test_workflow_state` hold H3.
- Probes are scratch scripts under `${TMPDIR:-/tmp}`. Each one is written to fail at `BASE` and pass at the task's head, and none is committed.
- Run a test module as `PYTHONPATH=python python3 -m unittest <path>` from the worktree root. A single test is `PYTHONPATH=python python3 -m unittest <dotted.module.Class.test>`. A dotted path containing `agent-skills` works as written.

**Coverage gate.** Every task runs this before it commits, from the worktree root. Pass means it prints `COVERAGE-GATE-OK 2077 test ids`. A `diff` hunk, `import failures` or `test bodies differ` is a failure.

```bash
set -euo pipefail
BASE=31be7292b40159c5a3f49cc24f21b3292ba4ce89
work=$(mktemp -d "${TMPDIR:-/tmp}/issue262-gate-XXXXXX"); trap 'rm -rf "$work"' EXIT HUP INT TERM
git archive "$BASE" | tar -x -C "$work"
ids() { (cd "$1" && PYTHONPATH=python python3 - <<'PY'
import re, unittest
from unittest.main import _convert_names
block = open("justfile", encoding="utf-8").read().split("agent-workflow-tests:\n", 1)[1].split("\n\n", 1)[0]
paths = re.findall(r"\S+\.py", block)
def walk(suite):
    for item in suite:
        yield from (walk(item) if isinstance(item, unittest.TestSuite) else (item.id(),))
found = sorted(walk(unittest.defaultTestLoader.loadTestsFromNames(_convert_names(paths))))
broken = [i for i in found if i.startswith("unittest.loader.")]
if broken: raise SystemExit(f"import failures: {broken}")
print("\n".join(found))
PY
) }
ids "$work" > "$work/base.ids"; ids . > "$work/head.ids"
diff "$work/base.ids" "$work/head.ids"
python3 - "$work" <<'PY'
import ast, re, sys
work = sys.argv[1]
block = open("justfile", encoding="utf-8").read().split("agent-workflow-tests:\n", 1)[1].split("\n\n", 1)[0]
def bodies(source):
    out = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)) and item.name.startswith("test"):
                    out[f"{node.name}.{item.name}"] = ast.dump(item)
    return out
changed = []
for path in re.findall(r"\S+\.py", block):
    old = bodies(open(f"{work}/{path}", encoding="utf-8").read())
    new = bodies(open(path, encoding="utf-8").read())
    changed += [f"{path}::{k}" for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)]
if changed: raise SystemExit("test bodies differ:\n" + "\n".join(changed))
PY
echo "COVERAGE-GATE-OK $(wc -l < "$work/head.ids" | tr -d ' ') test ids"
```

**Timing driver.** Tasks 6 and 7 write this verbatim to `${TMPDIR:-/tmp}/issue262-timing.py` and never commit it (per D6). `python3 issue262-timing.py <tree> [module paths...]` runs each of the recipe's modules (or only the listed ones, in recipe order) as its own serial `unittest` process from `<tree>` with `PYTHONPATH=<tree>/python`. For each it prints one TSV row: tests run, wall seconds, `subprocess.Popen` count in the test process, 1-minute load before the module, and exit code.

```python
"""Serial per-module timing of the agent-workflow-tests recipe: one unittest process per module."""
import os, re, subprocess, sys, time
tree = os.path.abspath(sys.argv[1]); only = sys.argv[2:]
block = open(os.path.join(tree, "justfile"), encoding="utf-8").read().split("agent-workflow-tests:\n", 1)[1].split("\n\n", 1)[0]
paths = [p for p in re.findall(r"\S+\.py", block) if not only or p in only]
hook = ("import atexit, sys, unittest\n"
        "n = [0]\n"
        "sys.addaudithook(lambda e, a: e == 'subprocess.Popen' and n.__setitem__(0, n[0] + 1))\n"
        "atexit.register(lambda: sys.stderr.write(f'SPAWNS {n[0]}\\n'))\n"
        "unittest.main(module=None, argv=['unittest', sys.argv[1]])\n")
env = {**os.environ, "PYTHONPATH": os.path.join(tree, "python")}
print("module\ttests\twall_s\tspawns\tload1_before\texit", flush=True)
total = 0.0
for path in paths:
    load = os.getloadavg()[0]
    start = time.monotonic()
    done = subprocess.run([sys.executable, "-c", hook, path], cwd=tree, env=env, capture_output=True, text=True)
    wall = time.monotonic() - start; total += wall
    ran = re.search(r"^Ran (\d+) tests?", done.stderr, re.M)
    spawns = re.search(r"^SPAWNS (\d+)$", done.stderr, re.M)
    print(f"{path}\t{ran and ran.group(1)}\t{wall:.1f}\t{spawns and spawns.group(1)}\t{load:.1f}\t{done.returncode}", flush=True)
print(f"TOTAL\t-\t{total:.1f}\t-\t-\t-")
```

## Delivery estimate and boundaries

- Estimate: about 10 changed files. Production files are `workflow-state.py` and the review modules `review_git`, `review_forecast`, `review_projection`, `review_actual`, `review_issue100` and `review_issue121`. The test-side files are one new support module, `test_workflow_state.py`, and up to three H4 test modules. The estimated net diff is under 400 lines.
- Tasks 1, 2, 5 and the D3 pair (Tasks 3–4) are independently deliverable slices. Task 6 depends on measuring after Tasks 1–5. Task 7 changes no file.

## Task index

Task 1 — Memoize the delivery runtime per process — home/common/agent-skills/scripts/workflow-state.py — full — [task-1.md](2026-10-06-issue-262-test-suite-speed.tasks/task-1.md)
Task 2 — Three-spawn review history guard — python/agent_tools/review_git.py — full — [task-2.md](2026-10-06-issue-262-test-suite-speed.tasks/task-2.md)
Task 3 — One closure per edge and per commit set — python/agent_tools/review_git.py, python/agent_tools/review_forecast.py, python/agent_tools/review_projection.py — full — [task-3.md](2026-10-06-issue-262-test-suite-speed.tasks/task-3.md)
Task 4 — Shared closures at the paired and looped call sites — python/agent_tools/review_actual.py, python/agent_tools/review_issue100.py, python/agent_tools/review_issue121.py — full — [task-4.md](2026-10-06-issue-262-test-suite-speed.tasks/task-4.md)
Task 5 — In-process lifecycle CLI runner — home/common/agent-skills/tests/_inprocess_cli.py, home/common/agent-skills/tests/test_workflow_state.py — full — [task-5.md](2026-10-06-issue-262-test-suite-speed.tasks/task-5.md)
Task 6 — Class fixture templates for modules still over 90 s — tests/test_review_issue121.py, tests/test_review_issue100.py, tests/test_review_task7.py (each only if measured over 90 s) — full — [task-6.md](2026-10-06-issue-262-test-suite-speed.tasks/task-6.md)
Task 7 — Suite-wide acceptance evidence — no repository file (logs under ${TMPDIR:-/tmp}) — low-risk — [task-7.md](2026-10-06-issue-262-test-suite-speed.tasks/task-7.md)

## Decisions

Task 1 rests on D1. Task 2 rests on D2. Tasks 3 and 4 rest on D3 and D9. Task 5 rests on D4 and D10. Task 6 rests on D5 and D11. Task 7 rests on D6, D7 and D8. The spec's `## Decision ledger` holds every row.

---
