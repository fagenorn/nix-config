# Task 3: Primary-rooted, per-checkout SDD workspace

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/scripts/sdd-workspace`
- Create: `home/common/agent-skills/tests/test_sdd_workspace.py`
- Modify: `justfile`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `sdd-workspace PLAN_FILE` prints `<primary>/.superpowers/sdd/<bucket>/<plan-basename>` where `<bucket>` is `primary` or `wt-<worktree-name>`. Task 4 documents exactly this shape in `sdd/SKILL.md` and `task-brief`'s header; `task-brief:47` and `review-package`'s workspace call keep invoking it unchanged.

**Invariants:**
- The CLI surface is unchanged: one positional argument, one absolute path on stdout, exit 2 plus a stderr message for every refusal, no flags (per D4).
- The printed directory exists when the command exits 0, and no `.superpowers/` directory is ever created inside a linked worktree.
- Every refusal creates nothing: an exit-2 run leaves no `.superpowers` under the primary.
- Two checkouts executing the same plan basename get two distinct directories; `primary` and `wt-<name>` cannot collide because a worktree bucket always carries the `wt-` prefix (per D5).
- The checkout-identity branch runs **first**. A checkout whose git dir *is* its common dir is the primary whatever its on-disk shape — a submodule working tree (`…/super/.git/modules/sub`) and a `git init --separate-git-dir=` checkout (`…/gd`) both land there and both resolve through `--show-toplevel`. The `basename == ".git"` and `dirname` derivation apply **only** on the linked-worktree branch, where they are the validation that the primary really is the common dir's parent. Measured on git 2.51.2: applying that guard before the branch refuses both shapes with `invalid common Git directory`, which the base-commit script (`root=$(git rev-parse --show-toplevel)`) handles correctly today — so guard-first would be a regression that removes `sdd` from whole classes of repository.
- `git worktree list --porcelain` is not the primitive: in a submodule and in a separate-git-dir repository its first `worktree` line reports the git directory, not the working tree.
- `<primary>/.superpowers/sdd/.gitignore` holds exactly `*\n`.
- The workspace stays outside `.git/` and the header keeps saying why (per D3).

Cites D3, D4, D5, D15.

- [ ] **Step 1: Write the failing test**

Create `home/common/agent-skills/tests/test_sdd_workspace.py`:

```python
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).parents[4]
WORKSPACE = ROOT / "home/common/agent-skills/skills/sdd/scripts/sdd-workspace"


class SddWorkspaceTest(unittest.TestCase):
    def git(self, repo: Path, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(repo), *args], check=True,
            capture_output=True, text=True,
        ).stdout

    def make_primary(self, directory: Path, name: str = "main") -> tuple[Path, Path]:
        """A real primary checkout with one commit. Returns (primary, plan)."""
        primary = directory / name
        primary.mkdir()
        self.git(primary, "init", "-q")
        self.git(primary, "config", "user.name", "Fixture")
        self.git(primary, "config", "user.email", "fixture@example.test")
        plan = primary / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        self.git(primary, "add", "-A")
        self.git(primary, "commit", "-q", "-m", "seed")
        return primary, plan

    def add_worktree(self, primary: Path, path: Path, branch: str) -> Path:
        self.git(primary, "worktree", "add", "-q", "-b", branch, str(path))
        plan = path / "plan.md"
        plan.write_text("# Plan\n", encoding="utf-8")
        return plan

    def invoke(self, cwd: Path, plan: Path, env: dict[str, str] | None = None):
        return subprocess.run(
            [str(WORKSPACE), str(plan)], cwd=cwd, env=env,
            capture_output=True, text=True, check=False,
        )

    def test_primary_checkout_uses_the_primary_bucket(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            result = self.invoke(primary, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(primary / ".superpowers/sdd/primary/plan"),
            )
            self.assertTrue(Path(result.stdout.strip()).is_dir())

    def test_linked_worktree_buckets_under_the_primary_and_leaves_no_nest(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            primary, _ = self.make_primary(base)
            worktree = base / "one"
            plan = self.add_worktree(primary, worktree, "issue-102")
            result = self.invoke(worktree, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(primary / ".superpowers/sdd/wt-one/plan"),
            )
            self.assertFalse((worktree / ".superpowers").exists())

    def test_submodule_working_tree_resolves_to_its_own_toplevel(self):
        """A submodule's common dir is <super>/.git/modules/<name> — not `.git`."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            child, _ = self.make_primary(base, "child")
            parent, _ = self.make_primary(base, "parent")
            self.git(parent, "-c", "protocol.file.allow=always",
                     "submodule", "add", "-q", str(child), "sub")
            self.git(parent, "commit", "-q", "-m", "add submodule")
            checkout = parent / "sub"
            result = self.invoke(checkout, checkout / "plan.md")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(checkout / ".superpowers/sdd/primary/plan"),
            )
            self.assertFalse((parent / ".superpowers").exists())

    def test_separate_git_dir_checkout_resolves_to_its_own_toplevel(self):
        """`git init --separate-git-dir=<gd>` gives a common dir named <gd>."""
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            checkout = base / "sep"
            subprocess.run(
                ["git", "init", "-q", "--separate-git-dir", str(base / "gd"),
                 str(checkout)], check=True,
            )
            plan = checkout / "plan.md"
            plan.write_text("# Plan\n", encoding="utf-8")
            result = self.invoke(checkout, plan)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                result.stdout.strip(),
                str(checkout / ".superpowers/sdd/primary/plan"),
            )

    def test_two_worktrees_running_one_plan_do_not_share_a_ledger(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            primary, _ = self.make_primary(base)
            first = self.add_worktree(primary, base / "one", "issue-102")
            second = self.add_worktree(primary, base / "two", "issue-103")
            one = Path(self.invoke(base / "one", first).stdout.strip())
            two = Path(self.invoke(base / "two", second).stdout.strip())
            self.assertNotEqual(one, two)
            (one / "progress.md").write_text("# SDD ledger\n", encoding="utf-8")
            self.assertFalse((two / "progress.md").exists())

    def test_workspace_base_self_ignores(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            self.invoke(primary, plan)
            ignore = primary / ".superpowers/sdd/.gitignore"
            self.assertEqual(ignore.read_bytes(), b"*\n")

    def test_unresolvable_checkout_identity_refuses_and_creates_nothing(self):
        """A Git dir that is neither the common dir nor <common>/worktrees/<name>.

        Driven by a decoy bare repository inside the common dir (D15): a
        GIT_DIR that is not itself a repository makes `git rev-parse` fail
        outright, so the script would refuse before ever comparing git dir to
        common dir and the identity branch this test is about would go
        unexercised. The decoy keeps both rev-parse calls succeeding and lands
        exactly on the mismatch.
        """
        with tempfile.TemporaryDirectory() as raw:
            primary, plan = self.make_primary(Path(raw).resolve())
            common = primary / ".git"
            decoy = common / "decoy.git"
            subprocess.run(["git", "init", "-q", "--bare", str(decoy)], check=True)
            env = os.environ.copy()
            env["GIT_DIR"] = str(decoy)
            env["GIT_COMMON_DIR"] = str(common)
            result = self.invoke(primary, plan, env)
            self.assertEqual(result.returncode, 2)
            self.assertEqual(result.stdout, "")
            self.assertEqual(result.stderr, "cannot resolve checkout identity\n")
            self.assertFalse((primary / ".superpowers").exists())

    def test_missing_plan_file_still_refuses(self):
        with tempfile.TemporaryDirectory() as raw:
            primary, _ = self.make_primary(Path(raw).resolve())
            result = self.invoke(primary, primary / "absent.md")
            self.assertEqual(result.returncode, 2)
            self.assertFalse((primary / ".superpowers").exists())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_sdd_workspace.py -v 2>&1 | tail -25`

Expected: `FAILED (failures=5)` of 8, verified at the base commit. Failing:

- `test_primary_checkout_uses_the_primary_bucket` and `test_linked_worktree_buckets_under_the_primary_and_leaves_no_nest` — today's script prints `<cwd-toplevel>/.superpowers/sdd/plan`, which for a linked worktree is a path *inside* that worktree, and which carries no bucket at all.
- `test_submodule_working_tree_resolves_to_its_own_toplevel` and `test_separate_git_dir_checkout_resolves_to_its_own_toplevel` — today's script gets the working tree right but the bucket missing, so the expected `primary` component is absent. These two are also the guard against the wrong fix: against a resolution that applies the `basename == ".git"` check *before* deciding which checkout this is, both fail with `invalid common Git directory` — measured.
- `test_unresolvable_checkout_identity_refuses_and_creates_nothing` — today's script has no identity branch; with `GIT_DIR` pointed at the decoy it dies inside `git rev-parse --show-toplevel` under `set -e` rather than exiting 2 with the contract message.

The other three pass at the base commit and are pins, not drivers — do not "make them fail first". `test_two_worktrees_running_one_plan_do_not_share_a_ledger` passes today because cwd-rooting gets per-worktree isolation for free; the bucket is what *preserves* that property after the move (per D5), and this test is what proves it was not lost. `test_workspace_base_self_ignores` and `test_missing_plan_file_still_refuses` pin unchanged behaviour.

- [ ] **Step 3: Rewrite the resolution**

Replace `home/common/agent-skills/skills/sdd/scripts/sdd-workspace` in full with
the following. The argument parsing and slug derivation above `gitdir=` are
unchanged from the current file; everything from `gitdir=` down is new. The
header is rewritten because the old one describes a working-tree root that no
longer exists — it keeps the `.git/`-is-protected reason (per D3) and adds the
primary-checkout and bucket reasons.

The order of the resolution is load-bearing: **decide which checkout this is
first, derive the primary second.** A submodule working tree reports
`--git-common-dir` as `<super>/.git/modules/<name>` and a `--separate-git-dir=`
checkout reports it as the bare `<gd>` path; neither basename is `.git` and
neither primary is `dirname(common)`. Both are ordinary primary checkouts whose
git dir equals their common dir, so `--show-toplevel` answers them correctly —
which is what the base-commit script does today, and what a `basename == ".git"`
guard placed before the branch would break.

```bash
#!/usr/bin/env bash
# Resolve and ensure the directory SDD uses for one plan's short-lived
# artifacts: task briefs, implementer reports, review packages, and the
# progress ledger. Print the plan directory's absolute path.
#
# The workspace is rooted at the PRIMARY checkout — the working tree that owns
# the common Git directory — resolved from git, never assumed to be the process
# cwd's toplevel. Run from a linked worktree, a cwd-rooted workspace nests a
# second ledger inside that worktree: the substitution the lifecycle contract
# forbids for state that must outlive one checkout.
#
# Within the primary the path is .superpowers/sdd/<bucket>/<plan-basename>/,
# where <bucket> is `primary` for the primary checkout itself and
# `wt-<worktree-name>` for a linked worktree. One directory per plan so a
# follow-up plan can never read or overwrite another plan's artifacts; one
# bucket per checkout so a second attempt at the same plan on another branch
# cannot read the first attempt's completed-task lines. A stale ledger misread
# as current progress makes controllers skip whole task sequences. The bucket
# narrows that failure: two checkouts running one plan never share a ledger. It
# does not make a stale read impossible — a bucket outlives the worktree that
# named it, which is why ship-issue removes a feature worktree's bucket when it
# removes the worktree.
#
# Which checkout this is gets decided BEFORE the primary is derived. A checkout
# whose git dir is its own common dir is the primary, whatever that dir is
# called: a submodule sees <super>/.git/modules/<name> and a
# --separate-git-dir= checkout sees the bare git-dir path, and for both the
# answer is simply `git rev-parse --show-toplevel`. Only the linked-worktree
# branch may assume the common dir is named .git and that the primary is its
# parent, because only there is that true.
#
# The workspace lives in a working tree (not under .git/) because Claude Code
# treats .git/ as a protected path and denies agent writes there — which blocks
# an implementer subagent from writing its report file. A self-ignoring
# .gitignore at .superpowers/sdd/ keeps every plan's workspace out of
# `git status` and out of accidental commits without modifying any tracked
# file; a project whose own .gitignore already covers these shapes gets it
# twice over, and a project whose .gitignore does not gets it only from here.
#
# Single source of truth for the workspace location, so task-brief and
# review-package cannot drift to different directories.
#
# Usage: sdd-workspace PLAN_FILE
set -euo pipefail

if [ $# -ne 1 ]; then
  echo "usage: sdd-workspace PLAN_FILE" >&2
  exit 2
fi

plan=$1
[ -f "$plan" ] || { echo "no such plan file: $plan" >&2; exit 2; }

slug=$(basename "$plan" .md)
[ -n "$slug" ] && [ "$slug" != "." ] && [ "$slug" != ".." ] \
  || { echo "cannot derive a workspace name from: $plan" >&2; exit 2; }

gitdir=$(git rev-parse --path-format=absolute --git-dir 2>/dev/null) || gitdir=
common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null) || common=
[ -n "$gitdir" ] && [ -n "$common" ] \
  || { echo "cannot resolve checkout identity" >&2; exit 2; }

if [ "$gitdir" = "$common" ]; then
  # This checkout owns the common dir: it IS the primary, whatever the dir is
  # named. No basename check here — that is what breaks submodules and
  # --separate-git-dir checkouts.
  primary=$(git rev-parse --path-format=absolute --show-toplevel 2>/dev/null) || primary=
  [ -n "$primary" ] && [ -d "$primary" ] \
    || { echo "invalid primary checkout" >&2; exit 2; }
  bucket=primary
else
  # A linked worktree: exactly one component under <common>/worktrees/.
  name=${gitdir#"$common/worktrees/"}
  [ "$gitdir" = "$common/worktrees/$name" ] \
    && [ -n "$name" ] && [ "$name" != "." ] && [ "$name" != ".." ] \
    && [ "${name#*/}" = "$name" ] \
    || { echo "cannot resolve checkout identity" >&2; exit 2; }
  [ "$(basename "$common")" = ".git" ] \
    || { echo "invalid common Git directory" >&2; exit 2; }
  primary=$(dirname "$common")
  shown=$(git -C "$primary" rev-parse --path-format=absolute --show-toplevel 2>/dev/null) || shown=
  [ "$shown" = "$primary" ] && [ -d "$primary" ] && [ ! -L "$primary" ] \
    || { echo "invalid primary checkout" >&2; exit 2; }
  bucket="wt-$name"
fi

base="$primary/.superpowers/sdd"
dir="$base/$bucket/$slug"
mkdir -p "$dir" && printf '*\n' > "$base/.gitignore" \
  || { echo "cannot create the SDD workspace beneath: $primary" >&2; exit 2; }
printf '%s\n' "$dir"
```

Three details that are load-bearing and easy to lose. The final line is
`printf '%s\n' "$dir"`, not the old `cd "$dir" && pwd` — `pwd` would re-resolve
symlinks and disagree with the path the tests compute. The creation guard names
`$primary`, so a primary outside the agent's writable area fails loudly instead
of silently landing elsewhere. And the linked-worktree branch keeps the full
`basename`/`--show-toplevel` round-trip: a *worktree of a submodule* reaches it,
fails the `.git` basename check, and refuses with `invalid common Git directory`
— the honest refusal, because `dirname(<super>/.git/modules/sub)` is not a
working tree and there is no correct primary to name.

- [ ] **Step 4: Register the new suite and verify**

In `justfile`, inside the `agent-workflow-tests` recipe, add a line for the new suite immediately after `home/common/agent-skills/tests/test_task_brief.py \`:

```
    home/common/agent-skills/tests/test_sdd_workspace.py \
```

Run: `python3 -m unittest home/common/agent-skills/tests/test_sdd_workspace.py -v 2>&1 | tail -5`
Expected: `OK`, 8 tests.

Run: `just agent-workflow-tests 2>&1 | tail -5`
Expected: `OK` — the new suite is picked up by the recipe (a missing registration shows as a lower test count and no `SddWorkspaceTest` lines in the verbose output).

Run: `bash -n home/common/agent-skills/skills/sdd/scripts/sdd-workspace && test -x home/common/agent-skills/skills/sdd/scripts/sdd-workspace && echo mode-ok`
Expected: `mode-ok` — the file still parses and stays executable.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/scripts/sdd-workspace \
        home/common/agent-skills/tests/test_sdd_workspace.py justfile
git commit -m "fix(sdd): root the workspace at the primary checkout, bucketed per checkout"
```
