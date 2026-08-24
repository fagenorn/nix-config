# Task 6: Forced-failure cleanup pins, residual containment, rollout

**Files:**
- Modify: `home/common/agent-skills/tests/test_review_package.py`
- Modify: `home/common/agent-skills/tests/test_task_brief.py`

**Interfaces:**
- Consumes: `sdd-workspace`'s post-Task-3 behaviour (the live-resolution gate in Step 6 exercises it from this worktree) and the tracked `.gitignore` from Task 5. Run this task last.
- Produces: nothing later tasks depend on.

**Invariants:**
- The cleanup code under test is **already correct** — `task-brief:97` sets `trap 'rm -f "$tmp"' EXIT HUP INT TERM` before its `cp`, and `review-package._validated_report` unlinks in a `finally`. What issue #102's second acceptance criterion is missing is a *test that forces those branches*. Do not modify either script to "make the test fail first"; the falsifiable observation is that the test does not exist at the base commit (per D11).
- The report-validation stub must reach the candidate. If the run stops at `review-package: validator unavailable`, the stub broke the in-process API and the test is vacuous — the assertion on the exact stderr is what catches that (per D16).
- Nothing in this task deletes a `.superpowers/` directory anywhere. The nested ledgers inside other agents' running worktrees are live controller state and disappear with their worktree (per D8). The one exception is bookkeeping, not deletion: Step 6's own gate calls `sdd-workspace`, which unconditionally creates a workspace, and the step `rmdir`s exactly the empty directories it just caused.
- This worktree is asserted free of **stray candidates and temporaries**. Its own pre-Task-3 `.superpowers/` ledger is deliberately left alone; the two claims are different and neither one weakens the other.

Cites D8, D9, D11, D13, D16.

- [ ] **Step 1: Write the failing report-validation test**

Add at module level in `home/common/agent-skills/tests/test_review_package.py`:

```python
# An artifact_budget shim: the real API when imported, a hard refusal when run
# as a script. review-package uses both faces — check_artifact/load_limits
# in-process, then `sys.executable <artifact_budget.__file__> validate-report`
# for the producer report — so only the second one may fail (D16). The
# sys.modules registration is load-bearing: dataclasses resolves
# cls.__module__ through sys.modules while exec_module runs.
REPORT_VALIDATOR_STUB = '''import sys

if __name__ == "__main__":
    sys.stderr.write("stub validator refuses validate-report\\n")
    raise SystemExit(9)

import types
from importlib.machinery import SourceFileLoader

_real = types.ModuleType("_real_artifact_budget")
sys.modules["_real_artifact_budget"] = _real
SourceFileLoader("_real_artifact_budget", REAL_MODULE_PATH).exec_module(_real)
ArtifactBudgetError = _real.ArtifactBudgetError
CheckResult = _real.CheckResult
check_artifact = _real.check_artifact
load_limits = _real.load_limits
'''
```

Add this test to `ReviewPackageCliTest`:

```python
    def test_report_validation_failure_removes_the_report_candidate(self):
        with tempfile.TemporaryDirectory() as raw:
            repo = Path(raw) / "repo"
            repo.mkdir()
            plan, env = self.setup_repo(repo)
            (repo / "a.txt").write_text("before\n", encoding="utf-8")
            base = self.commit(repo, "base", env)
            (repo / "a.txt").write_text("after\n", encoding="utf-8")
            head = self.commit(repo, "change a", env)

            shim = Path(env["PYTHONPATH"]) / "artifact_budget.py"
            shim.unlink()
            shim.write_text(
                REPORT_VALIDATOR_STUB.replace("REAL_MODULE_PATH", repr(str(MODULE))),
                encoding="utf-8",
            )
            scratch = Path(raw) / "tmp"
            scratch.mkdir()
            env["TMPDIR"] = str(scratch)

            result = self.invoke(repo, plan, base, head, repo / "review.json", env)

            # Non-vacuity: the run reached the candidate rather than refusing at
            # bootstrap. "validator unavailable" here would mean the shim broke
            # the in-process API and nothing was ever created to clean up.
            self.assertEqual(result.stderr, "review-package: generation failed\n")
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(
                sorted(p.name for p in scratch.glob("review-package-report-*.json")),
                [],
            )
```

- [ ] **Step 2: Write the failing member-copy test**

Add this test to `TaskBriefPackageTest` in `home/common/agent-skills/tests/test_task_brief.py`:

```python
    def test_failed_member_copy_leaves_no_temporary_sibling(self):
        with tempfile.TemporaryDirectory() as raw:
            root, env = self.make_repo(Path(raw))
            self.write_package(root)
            marker = Path(raw) / "cp-was-called"
            stub = Path(raw) / "bin/cp"
            stub.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n", encoding="utf-8")
            stub.chmod(0o755)
            out_dir = Path(raw) / "briefs"
            out_dir.mkdir()
            out = out_dir / "brief.md"

            result = subprocess.run(
                [str(TASK_BRIEF), str(root), "1", str(out)], env=env,
                text=True, capture_output=True, check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            # Non-vacuity: the copy branch was reached, not some earlier refusal.
            self.assertTrue(marker.exists())
            self.assertFalse(out.exists())
            self.assertEqual(sorted(p.name for p in out_dir.iterdir()), [])
```

- [ ] **Step 3: Run both and watch them fail for the right reason**

Run:
```bash
python3 -m unittest home/common/agent-skills/tests/test_review_package.py \
                    home/common/agent-skills/tests/test_task_brief.py -v 2>&1 | tail -10
```

Expected at the base commit: both new tests are **absent** — that is the falsifiable observation. Once added, both pass immediately, because the cleanup they pin already works. If either fails, the failure is real and must be investigated, not papered over: `review-package: validator unavailable` means the shim is wrong (see D16), and a surviving `*.tmp.*` in `out_dir` means `task-brief`'s trap regressed.

- [ ] **Step 4: Verify the pins and the whole suite**

```bash
python3 -m unittest home/common/agent-skills/tests/test_review_package.py -v 2>&1 | tail -5
python3 -m unittest home/common/agent-skills/tests/test_task_brief.py -v 2>&1 | tail -5
just agent-workflow-tests 2>&1 | tail -5
```
Expected: `OK` from each; the recipe's run includes `SddWorkspaceTest` (registered in Task 3).

```bash
just build 2>&1 | tail -5
```
Expected: a successful build — every changed skill file is materialised through the flake, so this is the gate for Tasks 1–4.

- [ ] **Step 5: Verify the documentation claim (D13)**

```bash
if ! grep -q 'per-plan `sdd` task artifacts beneath the primary checkout in a per-checkout bucket' CLAUDE.md; then
  echo "CLAUDE.md no longer carries the corrected claim"; exit 1
fi
echo "CLAUDE.md claim present"
```
Expected: `CLAUDE.md claim present`. `CLAUDE.md` was corrected in the design commit — do not edit it here; Step 6 proves the shipped behaviour matches it.

- [ ] **Step 6: Residual containment — verify, and reclaim only what this gate created**

```bash
primary=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")
plan=.claude/plans/2026-08-23-workflow-scratch-containment.md
expected="$primary/.superpowers/sdd/wt-worktree-issue-102/2026-08-23-workflow-scratch-containment"
actual=$(home/common/agent-skills/skills/sdd/scripts/sdd-workspace "$plan")
if [ "$actual" != "$expected" ]; then
  echo "resolved to $actual, expected $expected"; exit 1
fi
echo "live resolution lands under the primary checkout"
```
Expected: `live resolution lands under the primary checkout`. This is the end-to-end proof of the issue's first acceptance criterion in the real environment: the resolver, run from inside an issue worktree, puts the workspace in the primary. It writes only that correct home.

```bash
rmdir "$actual" 2>/dev/null || true
rmdir "$(dirname "$actual")" 2>/dev/null || true
echo "gate scratch reclaimed"
```
Expected: `gate scratch reclaimed`. The gate above *created* `$actual` — a
verification step for a scratch-containment issue must not leave scratch behind.
Both `rmdir`s are guarded and non-fatal: `rmdir` refuses a non-empty directory,
so a real workspace with a ledger in it survives untouched, and the `|| true`
keeps a refusal from failing the step under `set -e`. Verified in a scratch
repository: the empty leaf and its then-empty bucket are removed, a leaf holding
a `progress.md` is not.

```bash
strays=$(find . -path ./.git -prune -o \
  \( -name 'producer-report-*.json' \
     -o -name 'review-package-report-*.json' \
     -o -name '*.tmp.??????' \) -print)
if [ -n "$strays" ]; then
  printf '%s\n' "$strays"
  echo "stray workflow scratch left in this worktree"; exit 1
fi
echo "no stray candidate or temporary in this worktree"
```
Expected: `no stray candidate or temporary in this worktree` — the executable
form of the issue's fourth acceptance criterion. The three shapes are exactly the
ones this plan's own machinery produces and Task 5's patterns ignore:
`producer-report-*.json` from Task 1's `mktemp
"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"`, `review-package-report-*.json`
from `review-package`'s `NamedTemporaryFile(prefix="review-package-report-",
suffix=".json")`, and `*.tmp.??????` from `task-brief:96`'s
`mktemp "${out}.tmp.XXXXXX"`. `.git` is pruned so a linked worktree's own
administrative files cannot trip it. Verified against a scratch repository
seeded with one of each shape (all three reported, `.git` contents ignored) and
against this worktree (empty).

```bash
if [ -n "$(git diff --name-only --diff-filter=D f6743e5d55864902104c9f0949a1f000b1114e5b..HEAD)" ]; then
  git diff --name-only --diff-filter=D f6743e5d55864902104c9f0949a1f000b1114e5b..HEAD
  echo "this branch deletes tracked files; issue #102 deletes none"; exit 1
fi
echo "no tracked file deleted"
```
Expected: `no tracked file deleted` — the encoded form of D8.

The residue assertion above is about **stray candidates and temporaries**, not about `.superpowers/`. If `.superpowers/` exists in this worktree, it is **this run's own SDD ledger**, created by the pre-Task-3 resolver before Task 3 landed. Leave it. It is now covered by the tracked ignore, is not committable from any clone, and disappears with the worktree at ship time. Deleting a live controller's ledger is the exact failure D8 forbids — and the same rule applies to the nested ledgers in `worktree-issue-104` and `worktree-issue-99-skill-prose-fixes`: do not touch them.

- [ ] **Step 7: Record the rollout rule (D9)**

There is no migration for legacy nested workspaces: `task-brief` re-resolves the workspace on every task, so a rebuild landing mid-run would leave the ledger at the old path and new briefs at the new one. State this in the PR body, verbatim:

> **Rollout:** finish or abandon in-flight `sdd` runs before the `just switch` that ships this change. No workspace is migrated (D9).

Do not run `just switch` here — this repository switches only when asked.

- [ ] **Step 8: Commit**

```bash
git add home/common/agent-skills/tests/test_review_package.py \
        home/common/agent-skills/tests/test_task_brief.py
git commit -m "test(agent-skills): force the report-validation and member-copy cleanup branches"
```
