# Task 6: The merge, doctor report 2, verify and conformance

Spec § 4 steps 9–10 and § 6, per D8, D10, D11, D14, D16, D17 and D20. This task holds AC3's and AC9's checks. It is the resume point after the owner gate: its first step confirms the owner's merge, and it suspends again if the merge has not happened.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: from `E`, Task 2's `Switch commit: <C>`, `System: <R>` and `Guard wrapper: <G>`; Task 3's doctor report 1; Task 4's `Adoption branch: adopt-<digest12>`, `Contract commit: <K>` (or `Contract commit (rebuilt)`) and `Adoption commit: <H>`; Task 5's `### Owner gate` block.
- Produces: the section `## Task 6 — Merge, doctor report 2, verify and conformance`, holding the lines `Merged PR: <url>`, `Merge commit: <M>`, `Doctor 2 passed: <UTC time>`, `Verify adopted: <UTC time>` and `Conformance held: <UTC time>`. Task 7 compares the three times with its registration time.

**Invariants:**
- Nothing here writes to Argus, the registry or the guard policy. Every Argus read happens in a fresh clone `$SCR/argus-verify` at the merged `origin/main` (D14, D17).
- Every one of the three AC9 passes happens before Task 7 starts. If one fails, the task stops, and registration never runs on a failed pass.

- [ ] **Step 1: Confirm the red state and the merge**

Run: `grep -c '^## Task 6 — Merge, doctor report 2, verify and conformance$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`. Expected: `0`.
Run (timeout 120 s): `env -u GITHUB_TOKEN -u GH_TOKEN gh pr list --repo fagenorn/argus --state all --head adopt-<digest12> --json number,state,headRefOid,mergeCommit,mergedAt,mergedBy,url`.

- No PR, or one in state `OPEN`: return `BLOCKED human_gate`, quoting Task 5's `### Owner gate` block unchanged. The run resumes at this step.
- `CLOSED` and not merged: return `BLOCKED human_gate`, stating that the owner closed the PR without merging and asking whether to re-run from Task 4.
- `MERGED`: require exactly one such PR, with `headRefOid` equal to `H`. Set `M` to `mergeCommit.oid`.

- [ ] **Step 2: The floor the owner applied, and the merge shape**

Run (timeout 120 s):
- `env -u GITHUB_TOKEN -u GH_TOKEN gh api 'repos/fagenorn/argus/commits/<H>/check-runs?per_page=100' --jq '.check_runs[] | [.name, .status, .conclusion, .completed_at] | @tsv'`. Expected: at least one `memory foundation (unit + forced checks)` row, with every such row `completed` / `success`. Every such row's `completed_at` must be earlier than Step 1's `mergedAt`; record both times and the comparison as `Floor before merge: <completed_at> < <mergedAt>`. A check that completed only after the merge counts as a missing check.
- `env -u GITHUB_TOKEN -u GH_TOKEN gh api repos/fagenorn/argus/commits/<M> --jq '[.parents[].sha]'`. Expected: two parents, the second equal to `H`, which marks a merge commit (D8).

A red or missing check, or a squash or rebase merge, is recorded as observed. The task then returns `BLOCKED human_gate` with that observation; a squash or rebase leaves the adoption commit unreachable and registration would refuse it as `not_integrated`.

- [ ] **Step 3: A fresh clone at the merged `main`**

Run (timeout 600 s): `launch-scope exec … -- git clone --quiet git@github.com:fagenorn/argus.git "$SCR/argus-verify"`. Then run `git -C "$SCR/argus-verify" merge-base --is-ancestor <H> HEAD` and `git -C "$SCR/argus-verify" merge-base --is-ancestor <M> HEAD`. Expected: exit 0 for both. Record `git -C "$SCR/argus-verify" rev-parse HEAD` as `T`.

- [ ] **Step 4: Doctor report 2 (AC3)**

Run (timeout 900 s): `launch-scope exec … -- conformance run --purpose doctor --repo-root "$SCR/argus-verify" > "$SCR/doctor-2.json"`, then condense it exactly as Task 3 did:

```bash
python3 -I - "$SCR/doctor-2.json" <<'EOF'
import json, sys
report = json.load(open(sys.argv[1], encoding="utf-8"))
print("outcome", json.dumps(report["outcome"]))
for check in report["checks"]:
    if check["id"].startswith("host.") or check["status"] != "passed":
        print(check["id"], check["status"], check.get("reason_code"), check.get("repair_id"))
EOF
date -u +%Y-%m-%dT%H:%M:%SZ
```

Expected: outcome status `passed`, every `host.*` line `passed` (`host.capability.required` included), and no other line. For each non-`passed` repository check of report 1, state that it is now `passed` and name the Task 4 operation that closed it.
If a `host` check `failed`, take the route of Task 3 Step 7 (the named repair, or `BLOCKED human_gate` for a `user_action` repair, resuming at this step). Any other failure is `BLOCKED` with the check.

- [ ] **Step 5: Plain verify**

Run (timeout 900 s): `launch-scope exec … -- adopt-project verify --repo-root "$SCR/argus-verify"`, then `date -u +%Y-%m-%dT%H:%M:%SZ`.
Expected: `result` `adopted`, and each of the six checks `passed`: `contract-resolves`, `projections-in-sync`, `no-unclassified-agent-path`, `adoption-evidence-record`, `adoption-commit-derived` and `path-migration-map`. Anything else is a stop. An inexpressible class is a contract gap; otherwise return `BLOCKED` with the report.

- [ ] **Step 6: Installed/source conformance again (D11, D20)**

Run (timeout 300 s): if `$SCR/nix-config-switch` is absent, run `launch-scope exec … -- git -C /Users/anis/tmp/nix-config worktree add --detach "$SCR/nix-config-switch" <C>`. Then run:

```bash
set -e
test "$(readlink -f /run/current-system)" = '<R>'
test "$(jq -r '.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[].command | select(endswith("/bin/claude-bash-lifecycle-guard"))' ~/.claude/settings.json)" = '<G>'
test -z "$(git -C '<SCR>/nix-config-switch' status --porcelain)"
test "$(git -C '<SCR>/nix-config-switch' rev-parse HEAD)" = '<C>'
```

Then run (timeout 600 s): `launch-scope exec … -- bash -c 'set -o pipefail; cd "$1" && PYTHONPATH="$1/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_installed_policy_surface_matches_source_contract 2>&1 | tail -4' _ "$SCR/nix-config-switch"`, followed by `date -u +%Y-%m-%dT%H:%M:%SZ`.
Expected: exit 0 and `OK`. A changed generation or hook means the host was switched since Task 2: return `BLOCKED` with both values.

- [ ] **Step 7: Write the section**

Append `## Task 6 — Merge, doctor report 2, verify and conformance` with the five `Produces` lines, the PR's `mergedBy` login and `mergedAt`, the check-run rows for `H`, `M`'s parents and `T`. Then add doctor report 2 (outcome and every `host.*` status), the report-1 finding closure table `| Report-1 check | Report-2 status | Closed by |`, the six verify checks, and the conformance table `| Check | Result | Time |`.

- [ ] **Step 8: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 49152
test "$(grep -c '^## Task 6 — Merge, doctor report 2, verify and conformance$' "$E")" -eq 1
for k in 'Merge commit' 'Doctor 2 passed' 'Verify adopted' 'Conformance held'; do grep -Eq "^$k: [0-9a-zA-Z:-]+\$" "$E" || exit 1; done
```

Expected: exit 0.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T6): Argus merge, doctor 2, verify, conformance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"40b698e9e86695082b1caec4787ac09ce5d3d195","head":"5bb3ca0e52d5a87754ee6cb23c69daa64017e7b0"}],"commit_subject_bytes":[64],"id":6,"records":[{"bounds":[{"added_lines":1228,"boundary":"all","deleted_lines":0,"record_bytes":51200,"support":{"covers":["e1","e2","e3","e4","e5","e6"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e6","last_task":8,"owner":6,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
