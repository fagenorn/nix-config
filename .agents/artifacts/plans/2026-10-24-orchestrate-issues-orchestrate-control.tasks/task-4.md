# Task 4: Evals expect `start` and `step`, and one eval-suite run

Spec § Evals, § Acceptance criterion 5 and § Test seams (seam 5), per D10, D11 and D14. Evals 1–3 now expect one `orchestrate-control start` and one `orchestrate-control step` per event and name raw `workflow-state` lifecycle calls, a hand-built request and decoding `owner_object` as failures. Eval 7 becomes a tracker-free pipeline run whose first `step` refuses at `tracker`; it keeps id 7, mode `pipeline` and its three sandbox asserts, and one refusal-report assert replaces the builder and `delivery_contract` asserts. Evals 4–6 are unchanged. The task then runs the suite's four changed cases once against this tree and opens the acceptance record.

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify (appended by the run): `home/common/agent-skills/evals/results/results.jsonl`
- Create: `.agents/artifacts/plans/2026-10-24-orchestrate-issues-orchestrate-control.acceptance.md`

**Interfaces:**
- Consumes (Task 1): the built settings allow `orchestrate-control` (passed to the eval run as `EVAL_SETTINGS`). Consumes (Task 2): the skill text the evals grade.
- Consumes (unchanged): `home/common/agent-skills/evals/run-eval.sh <skill> <id>` with `EVAL_TREE` (puts this tree's `agent_tools` commands, `orchestrate-control` among them, on the sandbox `PATH`, and records the tree's revision) and `EVAL_SETTINGS`; it appends one JSON line per trial to `results.jsonl` and prints `VERDICT: PASS (<n>/<n> asserts)` for a passing pipeline case. The eval fixture binds tracker kind `none`, so `step` refuses at its `tracker` step with the detail `tracker kind none is not supported` (#403 D7).
- Produces: acceptance-record rows `AC1`–`AC5`, with `AC4` and `AC5` filled.

**Invariants:**
- Eval 7 keeps `id` 7, `mode` `pipeline`, and its first three asserts byte-identical (`a run ledger exists and records no attempt` is pinned by `test_eval_cases.py`).
- Evals 1 and 7 keep the phrase "ResolvedProject" (the eval-corpus test requires it); no eval text holds "default GitHub", "helper missing" or "auto-detect absent"; eval 7's prompt keeps "ResolvedProject" and the word "stop".
- `evals.json` keeps its format: `json.dumps(doc, indent=2, ensure_ascii=False) + "\n"`.

- [ ] **Step 1: Write the failing content check**

Save this check as `<scratch>/i404/evals-check.py` (scratch from `launch-scope scratch …`):

```python
"""Evals 1-3 expect orchestrate-control; eval 7 is the tracker-free refusal case (#404 D10)."""
import json
import sys

cases = {c["id"]: c for c in json.load(open(sys.argv[1], encoding="utf-8"))["evals"]}
for case_id in (1, 2, 3):
    expected = cases[case_id]["expected_output"]
    assert "orchestrate-control st" in expected, case_id
    assert "--request-file" not in expected and "17-key" not in expected, case_id
assert "orchestrate-control step" in cases[1]["expected_output"]
assert "decoding owner_object" in cases[1]["expected_output"]
seven = cases[7]
assert (seven["mode"], len(seven["asserts"])) == ("pipeline", 4)
assert seven["asserts"][3]["name"] == "the run reports the refused tracker step"
assert "tracker kind none is not supported" in seven["expected_output"]
print("evals expect orchestrate-control")
```

Run (timeout 60 s): `python3 -I <scratch>/i404/evals-check.py home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
Expected: FAIL — `AssertionError: 1` (eval 1 names no `orchestrate-control`).

- [ ] **Step 2: Rewrite the four cases**

Save this script as `<scratch>/i404/edit-evals.py` and run it once (timeout 60 s): `python3 -I <scratch>/i404/edit-evals.py home/common/claude-code/skills/orchestrate-issues/evals/evals.json`. It asserts every text it replaces, so a second run fails.

```python
"""Rewrite orchestrate-issues evals 1, 2, 3 and 7 for orchestrate-control (#404 D10)."""
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
doc = json.loads(path.read_text(encoding="utf-8"))
cases = {case["id"]: case for case in doc["evals"]}

E1_PROMPT_OLD = "from invocation through bootstrap, observation, the control call, and execution"
E1_PROMPT_NEW = "from invocation through start, observation, each step, and execution"
assert cases[1]["prompt"].count(E1_PROMPT_OLD) == 1
cases[1]["prompt"] = cases[1]["prompt"].replace(E1_PROMPT_OLD, E1_PROMPT_NEW)
cases[1]["expected_output"] = (
    "Role boundary: the dispatcher is an external control adapter around orchestrate-control and "
    "never reads issue content, code, specs, plans, diffs, review findings, the tracker, the forge, "
    "git or the ledger; it does not maintain a second task ledger or assemble scheduling policy. "
    "Resolve once into a retained ResolvedProject; refusal is fatal. Take only "
    "bindings.workflow.orchestration.stall_minutes from it, for owner-liveness, and never default or "
    "infer policy; orchestrate-control resolves the rest on each call. Resolve one immutable "
    "ledger_repo_root. Make one orchestrate-control start --repo-root <ledger_repo_root> 12 14 15 "
    "call with the numbers in caller order: a ready outcome keeps the printed session verbatim; "
    "unsupported renders the route and its alternative as the final report and dispatches nothing; "
    "refused or an invalid invocation reports step and detail and stops. Then make exactly one "
    "orchestrate-control step --repo-root <ledger_repo_root> --input - call per event (start or "
    "resume, each current owner notification, tracker change or current wait-ID wake), fed through "
    "a quoted heredoc with exactly session, first_sweep, owners, contracts_due and "
    "refused_contracts: first_sweep true only on the first step after start, owners this event's "
    "normalized observations (cleared after the call), and contracts_due and refused_contracts "
    "passed back verbatim from the previous ready report. A ready report's response is the only "
    "source of action order, kind and lifecycle identity: execute its actions in returned order "
    "from the closed set spawn, resume, retry, delivery_remainder, delivery_contract, wait, "
    "finalize, and surface an unknown kind before executing it. Before the first action of a report "
    "with non-empty dispatches, run the stop pass. Launch each dispatches[] entry in order as one "
    "background owner prompt: the envelope (action_id, issue, attempt, owner, worktree, handoff_path "
    "only when non-null) from the entry's same-named members, the immutable ledger_repo_root and the "
    "session's run_id, the entry's owner_object verbatim as the canonical JSON, its resume_pack "
    "verbatim in the Resume pack paragraph when non-null, and the literal from-issue <num> --auto; "
    "host task IDs remain correlation-only, and each handle records its action_id and the custody "
    "of the matching response action. A host-refused launch is never retried; once the report has "
    "executed, one step carries its launch_refused observations. ends_run is handled as finalize, "
    "and a delivery_contract without ends_run is answered by the next step at once. A refused step "
    "ends the run loudly with its step and detail and the still-running owner handles, executing "
    "nothing from its response. A finalize is rendered from bounded summaries in that same "
    "response, including custody, contract_digest, pending_stage_ids, discussion items and any "
    "retained contract_refusals, without another ledger read. Failures include reading content, "
    "the tracker, the forge or git; a raw workflow-state host-route, init-run, control, "
    "build-delivery or resume-pack call; a hand-built control request; building a contract; "
    "decoding owner_object; writing a request or contract file; reordering actions; changing "
    "lifecycle identity; accepting an unknown action kind; retrying a refused step; or "
    "reconstructing omitted history.")

E2_PROMPT_OLD = "Also explain when control is called again"
assert cases[2]["prompt"].count(E2_PROMPT_OLD) == 1
cases[2]["prompt"] = cases[2]["prompt"].replace(
    E2_PROMPT_OLD, "Also explain when orchestrate-control step is called again")
E2_OLD = (
    "it then calls workflow-state init-run, rebuilds only the interface_version 2 bootstrap's "
    "bounded requirements and normalized facts, rebuilds a contract with build-delivery for each "
    "requirement whose contract_digest is null (the built contract was never persisted), calls "
    "workflow-state control, and rearms from the returned wait action. Call control at "
    "start/resume and on each current owner notification, tracker change, or current wait-ID "
    "event. Its typed response may return")
assert cases[2]["expected_output"].count(E2_OLD) == 1
cases[2]["expected_output"] = cases[2]["expected_output"].replace(E2_OLD, (
    "it then calls orchestrate-control start again (the same numbers re-enter the unfinished run, or "
    "--run-id re-enters a run minted with a creation key), makes one orchestrate-control step "
    "with first_sweep true (step itself rebuilds any contract the run still needs, since none was "
    "persisted), and rearms from the returned wait action. Make one step at start/resume and on "
    "each current owner notification, tracker change, or current wait-ID event. Its ready "
    "report's response may return"))

cases[3]["expected_output"] = (
    "The adapter's one orchestrate-control start asks the host route; an unsupported outcome "
    "renders the route and its alternative as the final report. orchestrate-control sends control "
    "the claude-code host route, and the runtime reserves each owner's worker and reviewer slots "
    "before returning a dispatch. A rejected owner launch is never retried: the adapter keeps "
    "launching the report's later dispatches and executing its later actions, then makes exactly "
    "one orchestrate-control step whose owners carry a launch_refused observation for that "
    "launch's custody (recorded beside its handle from the response action whose "
    "custody.action_id matches) and executes that report; the runtime parks that owner and "
    "re-dispatches it only after another claim is released by anything but a refusal. The adapter "
    "never calculates slots, alters max_parallel, creates competing owners or nested relays, or "
    "polls; issues in admission.waiting are reported as queued for agent slots.")

cases[7]["prompt"] = (
    "/orchestrate-issues 1 3\n\nResolve once into a retained ResolvedProject. A resolver refusal "
    "is fatal and values are never defaulted or inferred. This repository is the ledger "
    "repository root.\n\n**Stop after the first `orchestrate-control step` report is rendered.** "
    "Report its outcome, then stop: launch no agent, create no worktree and make no commit.")
cases[7]["expected_output"] = (
    "The dispatcher runs `orchestrate-control start --repo-root <repo> 1 3`, which asks the host "
    "route, mints a fresh run under `.superpowers/workflows/` and prints a ready session whose "
    "source is `explicit_user` with reference `invocation:/orchestrate-issues 1 3`. It then makes "
    "one `orchestrate-control step --repo-root <repo> --input -` call carrying that session, "
    "`first_sweep` true and empty `owners`, `contracts_due` and `refused_contracts`. The fixture's "
    "tracker kind is `none`, so `step` refuses at its `tracker` step with exit 2 and the detail "
    "`tracker kind none is not supported`, before any contract is built or control is called. The "
    "dispatcher reports the refused step `tracker` and that detail verbatim, executes nothing and "
    "stops. No agent is launched, no worktree is created and `main` carries no new commit.")
names = [check["name"] for check in cases[7]["asserts"]]
assert names[:3] == ["a run ledger exists and records no attempt", "no worktree was created",
                     "main carries no new commit"], names
cases[7]["asserts"] = cases[7]["asserts"][:3] + [{
    "name": "the run reports the refused tracker step",
    "shell": "out_matches '(refus[a-z]* (at )?(the )?\\W{0,2}tracker|step\\W{0,6}tracker)' "
             "&& out_matches 'tracker kind none is not supported'"}]
path.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

- [ ] **Step 3: Verify the content**

1. Run the Step 1 check again. Expected: `evals expect orchestrate-control`.
2. `shasum -a 256 home/common/claude-code/skills/orchestrate-issues/evals/evals.json` — expected at planning: `18088c93e7869e07e1f6459d05eb8dec054aa7fc97b3c34ae36db0c8b20b5f60`.
3. Run (timeout 900 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_eval_cases.py home/common/agent-skills/tests/test_workflow_skill_contracts.py -k orchestrate -k live_evals -k pipeline`
   Expected: `OK`, including `test_orchestrate_ledger_assert_requires_a_ledger_shape`, `test_pipeline_prompts_resolve_once_and_stop_explicitly` and `test_live_evals_grade_strict_policy_and_direct_review`.

- [ ] **Step 4: Commit the evals**

```bash
git add home/common/claude-code/skills/orchestrate-issues/evals/evals.json
launch-commit … -- -m "test(orchestrate-issues): evals expect orchestrate-control start and step (#404)" -m "<session trailers>"
```

- [ ] **Step 5: Run the eval suite once against this tree**

With a clean tree at Step 4's commit (`git status --porcelain` prints nothing), build, then run the four cases, as two separate foreground commands, each within the host's 3600 s Bash ceiling (`BASH_MAX_TIMEOUT_MS` in `home/common/claude-code/default.nix`). First run (timeout 3600 s) `just build >"<scratch>/i404/logs/build.log" 2>&1` (create the log directory first; on failure print that log and stop). Then write this script to `<scratch>/i404/evals-run.sh` and run it (timeout 3600 s; eval 7 takes up to 2700 s): `bash <scratch>/i404/evals-run.sh <scratch>/i404/logs`.

```bash
#!/usr/bin/env bash
set -euo pipefail
LOG="${1:?usage: evals-run.sh <log dir>}"; mkdir -p "$LOG"
test -e ./result
SETTINGS=$(nix-store --query --requisites ./result | grep -- '-claude-code-settings\.json$')
test "$(printf '%s\n' "$SETTINGS" | wc -l)" -eq 1
for id in 1 2 3 7; do
  status=0
  EVAL_TREE="$PWD" EVAL_SETTINGS="$SETTINGS" \
    home/common/agent-skills/evals/run-eval.sh orchestrate-issues "$id" >"$LOG/eval-$id.log" 2>&1 || status=$?
  echo "eval $id exit $status: $(grep -E '^VERDICT|Plan-only eval' "$LOG/eval-$id.log" | head -1)"
done
tail -n 4 home/common/agent-skills/evals/results/results.jsonl | jq -c '{id, verdict, passed, total, tree, tree_rev}'
```

Expected: evals 1–3 exit 0 with `Plan-only eval: graded by reading the transcript against the expected output.` (each appends a `PRINTED` line); eval 7 exits 0 with `VERDICT: PASS (4/4 asserts)`; the four new `results.jsonl` lines name this worktree as `tree` and Step 4's commit as `tree_rev`. On a FAIL, keep its results line, record it in row `AC4` and report the failing assert names and `$LOG/eval-7.log`: never weaken an assert to pass.

- [ ] **Step 6: Open the acceptance record and commit the run**

Create `.agents/artifacts/plans/2026-10-24-orchestrate-issues-orchestrate-control.acceptance.md` with the heading `# Acceptance record — issue #404`, then one table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and five rows, `AC1` to `AC5` in order:

- `Criterion`: the issue's acceptance-criterion line verbatim, without its `- [ ] ` checkbox (`gh issue view 404 --repo fagenorn/nix-config --json body --jq .body`).
- `Kind`: `code` for `AC1`–`AC4`, `evidence` for `AC5`. `Check or command`: the plan's `## Acceptance map` cell for that row.
- `AC1`–`AC3`: `Observed` `in final verification`; `Commit`, `Conditions` and `Verdict` `—`.
- `AC4`: `Observed` holds eval 7's `VERDICT:` line and the four results lines' verdicts; `Commit` the short SHA of Step 4's commit; `Conditions`: `run-eval.sh` in tree mode (`EVAL_TREE` this worktree, `EVAL_SETTINGS` the built settings of that commit, model `sonnet`), and plan-only cases 1–3 are printed, not graded, before merge: `run-eval.sh` prints their prompt and expected output and produces no transcript (per D15). `Verdict` `—`.
- `AC5`: `Observed` `not measurable before merge`; `Commit` `—`; `Conditions`: after `just switch` of the merged `main`, the next `/orchestrate-issues` run of ≥ 3 issues on nodocom or this repository, threshold 0 `Write` calls creating `.py`/`.sh` helpers and ≥ 1 `orchestrate-control step` call per control round; the pre-merge proxy is Task 3's control-call assertion alone (D11, refined by D15). `Verdict` `—`.

```bash
git add home/common/agent-skills/evals/results/results.jsonl \
  .agents/artifacts/plans/2026-10-24-orchestrate-issues-orchestrate-control.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record and orchestrate-issues eval run (#404)" -m "<session trailers>"
```
