# Task 6: Eval 8, the `tracked-issue` setup and the acquisition probe

Spec § The live eval and test seam 6; per D15 and D16. Eval 8, `lifecycle-owner-economics`, runs `/from-issue 4 --auto` on the direct route. It uses a seeded four-part issue whose acceptance test takes about 5½ minutes, in a sandbox whose `gh` is a read-only shim. Its asserts read the owner report (Task 2). This task also proves acquisition by hand, with no model spend, and creates the acceptance record. Right after this task's commit the sdd controller runs Task 8 § Part A (D22).

**Files:**
- Create: `home/common/agent-skills/evals/setups/tracked-issue/setup.sh` (`setup.sh <WORK> <REPO>`)
- Create: `home/common/agent-skills/evals/setups/tracked-issue/gh.py` (the shim's implementation)
- Create: `home/common/agent-skills/evals/fixture-repo/issues/004-priorities-and-due-dates.md`
- Create: `home/common/agent-skills/evals/fixture-repo/tests/test_acceptance.py`
- Modify: `home/common/agent-skills/evals/run-eval.sh` (`tracked-issue)` arm; `$WORK/bin` first on the claude run's `PATH` for that kind)
- Modify: `home/common/agent-skills/evals/assert-lib.sh` (`owner_report`, `owner_lineage_has`)
- Modify: `home/common/agent-skills/skills/from-issue/evals/evals.json` (eval 8)
- Modify: `home/common/agent-skills/tests/test_eval_cases.py` (`SETUP_KINDS` gains `tracked-issue`; the eval-8 shape test)
- Modify: `home/common/agent-skills/evals/tests/test-run-eval-tree.sh` (shim checks)
- Modify: `home/common/agent-skills/evals/README.md` (the kind, the shim, eval 8's invocation and cost)
- Create: `.agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md`

**Interfaces:**
- Consumes: Task 2's report JSON (`lineages[].issue`, `phase_reached`, `gate_calls`, `measured_gate_calls`, `peak_context`, `phase7_entered`, `long_child_waits`); Task 5's tree shims.
- Produces:
  - Eval 8: id 8, `mode: pipeline`, `setup: {"kind": "tracked-issue"}`, and no parameters.
  - `owner_report` (assert-lib) prints the path of `$WORK/owners.json`, building it once.
  - The acceptance record with rows `AC1`–`AC6` (every row's evidence cells reading `pending`) and a filled `## Acquisition probe` section.

**Invariants:**
- `setup.sh` (bash, `set -euo pipefail`):
  - Writes `$WORK/bin/gh`, an executable wrapper running `exec python3 -I <evals>/setups/tracked-issue/gh.py --repo "$REPO" --log "$WORK/gh-calls.jsonl" "$@"`, with absolute paths baked in.
  - Rewrites the sandbox's `.agents/project.json` with `jq`: `bindings.tracker.kind = "github"` and `capabilities.tracker.support = "supported"`, every other key unchanged.
  - Then runs `git -C "$REPO" commit -qam "chore: track issues on github"` and `git -C "$REPO" push -q origin main`. Any failure exits non-zero.
- `gh.py` (standard library; the first `--repo`/`--log` pair is its own, the rest is the `gh` argv). Every call appends `{"argv": [...], "exit": n}` to the log. It answers:
  - `issue view <n>`: `--json <fields>` → a JSON object restricted to the requested fields, from `number`, `title` (the file's first line without `# `), `body` (the rest), `state: "OPEN"`, `labels: []`, `comments: []`, `url: "https://github.com/fixture/tinytask/issues/<n>"`. `--jq <expr>` is applied with `jq` from `PATH`, and an absent jq is an error. With neither flag, a text rendering: title, `state:\tOPEN`, then the body. `<n>` is the number in `issues/<nnn>-*.md`.
  - `api <path>` containing `sub_issues` or `dependencies` → `[]`.
  - `pr list` → `[]`; `pr view` → stderr `no pull requests found for branch`, exit 1.
  - `auth status` → exit 0; `issue comment`, `issue edit` → exit 0, logged.
  - Anything else, `pr create` and `pr merge` included → stderr `gh shim: <verb> is not available in this sandbox`, exit 1.
- `run-eval.sh`: the `tracked-issue)` arm runs `bash "$SETUPS/tracked-issue/setup.sh" "$WORK" "$REPO" || die "setup: tracked-issue failed"`. For this kind, the claude subshell exports `PATH="$WORK/bin:$PATH"`, so every agent of the run inherits it.
- Issue 4: one feature across model, store, CLI and docs. The model gains `priority` (`low|normal|high`, default `normal`) and an optional `due` ISO date. The store loads old files without the fields. The CLI gains `add --priority P --due YYYY-MM-DD`, `list --sort id|priority|due`, `list --long` (printing `id<TAB>state<TAB>priority<TAB>due-or-dash<TAB>title`; bare `list` output unchanged) and `edit ID [--priority P] [--due D | --clear-due]`. `--sort priority` orders high, normal, low with ties by id; `--sort due` puts dated tasks first in date order, then undated ones by id. Docs cover the README usage and the backlog CONTEXT glossary. Its criteria are `[code]`-tagged like issue 1's, and one reads: `` `TINYTASK_ACCEPTANCE=1 python3 -m unittest tests.test_acceptance` passes — measured: that command ``.
- `tests/test_acceptance.py` is skipped unless `TINYTASK_ACCEPTANCE == "1"`. It runs about 330 s and fails against today's CLI. Write it in full:

```python
"""Issue 4 acceptance soak: priorities and due dates through the CLI (slow; opt in)."""
import contextlib
import io
import os
import tempfile
import time
import unittest

from tinytask.cli import main

SOAK_SECONDS = 330


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = main(list(argv))
    return code, out.getvalue().splitlines()


@unittest.skipUnless(os.environ.get("TINYTASK_ACCEPTANCE") == "1", "set TINYTASK_ACCEPTANCE=1")
class PriorityAcceptance(unittest.TestCase):
    def test_priorities_and_due_dates_hold_for_the_whole_soak(self):
        deadline, rounds = time.monotonic() + SOAK_SECONDS, 0
        while time.monotonic() < deadline:
            with tempfile.TemporaryDirectory() as tmp:
                path = os.path.join(tmp, "tasks.json")
                self.assertEqual(run("--file", path, "add", "low one", "--priority", "low")[0], 0)
                self.assertEqual(run("--file", path, "add", "urgent", "--priority", "high",
                                     "--due", "2026-11-01")[0], 0)
                self.assertEqual(run("--file", path, "add", "plain")[0], 0)
                code, lines = run("--file", path, "list", "--sort", "priority", "--long")
                self.assertEqual(code, 0)
                self.assertEqual([line.split("\t")[2] for line in lines], ["high", "normal", "low"])
                self.assertEqual(lines[0].split("\t")[3], "2026-11-01")
                self.assertEqual(run("--file", path, "edit", "1", "--priority", "high")[0], 0)
                code, lines = run("--file", path, "list", "--sort", "due", "--long")
                self.assertEqual(lines[0].split("\t")[4], "urgent")
                self.assertEqual(run("--file", path, "list")[1][0], "1\topen\tlow one")
            rounds += 1
            time.sleep(0.5)
        self.assertGreater(rounds, 100)
```

- The eval-8 prompt contains the resolver preamble, as eval 1's does (`ResolvedProject` and a fatal refusal), and authorises self-answering every decision and recording it in the ledgers. It states that the sandbox's GitHub is a read-only shim that cannot publish, and that the run must stop when ship-issue stops at the forge boundary. It names no phase to stop at.
- Eval 8's asserts are tree mode only. `owner_report` fails with `eval 8 needs EVAL_TREE (tree mode)` when `EVAL_TREE` is empty. Otherwise it copies every `~/.claude/projects/<mangled $WORK>*` directory into `$WORK/projects`, then runs `PYTHONPATH="$EVAL_TREE/python" python3 -P -m agent_tools.agent_costs --report owners --format json --days 0 --projects-dir "$WORK/projects" >"$WORK/owners.json"`. Asserts (each a `jq -e` over `[.lineages[] | select(.issue == 4)]`, guarded with `|| fail "<why>"`):
  1. some lineage has `phase_reached >= 6`;
  2. `gate_calls >= 1` and `measured_gate_calls == gate_calls` for every lineage;
  3. some `peak_context >= 110000`;
  4. some `phase7_entered`;
  5. some `long_child_waits >= 1`;
  6. in `$WT`, `python3 -m unittest discover` exits 0 and `grep -q -- '--priority' tinytask/cli.py`.
- `test_eval_cases.py`:
  - `SETUP_KINDS` gains `"tracked-issue"`.
  - A new test asserts: eval 8's setup is exactly `{"kind": "tracked-issue"}`; its prompt contains `/from-issue 4 --auto`; it has six asserts and five of them call `owner_report`; the issue file exists; and `tests/test_acceptance.py` skips without the variable. Check the skip by running `python3 -m unittest tests.test_acceptance` in the fixture with the variable unset and expecting `OK (skipped=1)`.
- `test-run-eval-tree.sh` gains a `tracked-issue` scenario. It runs the setup script on a sandbox copy built the way the runner builds one (or runs the runner on a stub case file with the fake claude). It checks that `bin/gh issue view 4 --json title,state` prints `"state":"OPEN"`, that `bin/gh pr list` prints `[]`, and that `bin/gh pr create` exits 1 naming `pr create`. It checks that every call is in `gh-calls.jsonl`, and that `resolve-project resolve --repo-root <sandbox>` reports tracker kind `github`.

- [ ] **Step 1: Write the failing tests** — the `test_eval_cases.py` changes and the `test-run-eval-tree.sh` scenario above.
- [ ] **Step 2: Run them and watch them fail**

Run: **Harness tests**.
Expected: FAIL — `SETUP_KINDS` lacks `tracked-issue`, no eval 8, and no setup script.

- [ ] **Step 3: Implement** the files above. Then check the fixture: `cd home/common/agent-skills/evals/fixture-repo && python3 -m unittest discover 2>&1 | tail -2` prints `OK (skipped=1)`, and `TINYTASK_ACCEPTANCE=1 timeout 30 python3 -m unittest tests.test_acceptance` fails at once (the CLI rejects `--priority`).
- [ ] **Step 4: The acquisition probe** (no model spend; per spec § Acquisition probe)

Under the root that `launch-scope scratch …` prints, build a sandbox the way `run_trial` does: copy the fixture, `git init -b main`, make the initial commit, create a bare origin and push. Then run `setup.sh`. With `<WORK>/bin` first on `PATH`, drive `workflow-state direct-owner --repo-root <sandbox> --request-file -` by hand, using acquire-direct.md's interface_version 2 request for issue 4 with `attempt_budget_minutes` 180. Answer each `observe` requirement:
- `tracker` with `{"issue": 4, "state": "open", "open_blockers": [], "decision_blockers": []}`, built from `gh issue view 4 --json state` and the empty `gh api` dependency reads;
- `candidate_worktree` by reserving `.worktrees/worktree-issue-4-priorities`;
- `delivery_contract` through `workflow-state build-delivery`, as acquire-direct.md shows.

Repeat until the reply is `kind: owner`. Use the tree's `workflow-state` (`PYTHONPATH=$PWD/python python3 -P home/common/agent-skills/scripts/workflow-state.py`). Expected: a `kind: owner` reply with `action_id` `4:1:1`. Any refusal stops the task as BLOCKED with the refusal text: eval 8 cannot run until acquisition works. Then create the acceptance record. Follow the #424 record's header and table columns (`AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict`), with one row per acceptance-map row, `pending` in the evidence cells, and an `## Acquisition probe` section holding the commands and the final reply's `kind`, `action_id` and `deadline_at`. Remove the probe sandbox.
- [ ] **Step 5: Verify**

Run: **Harness tests** (both).
Expected: all `ok`, `OK`.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/evals home/common/agent-skills/skills/from-issue/evals/evals.json \
  home/common/agent-skills/tests/test_eval_cases.py \
  .agents/artifacts/plans/2026-10-25-issue-432-owner-handoff-economics.acceptance.md
launch-commit … -- -m "feat(evals): eval 8 — a lifecycle-identity pipeline on a tracked issue (issue 432)"
```

(`git add home/common/agent-skills/evals` stages only this task's paths; check `git status --short` first and stage nothing else.)
