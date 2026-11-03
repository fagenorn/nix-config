# Task 7: Registration and the derived row

Spec § 4 steps 11–12, per D12 and D14; AC1, plus the row that AC2 consumes. This task makes the run's one fleet-registry write and the guard-policy rebuild that the authorized switch exists to produce.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: Task 6's lines `Doctor 2 passed:`, `Verify adopted:` and `Conformance held:` in `E`; the registered root `/Users/anis/Projects/argus`, read only through its `origin`.
- Produces: the registry entry `{"project_id": "fagenorn/argus", "root": "/Users/anis/Projects/argus"}`; the compiled policy row `derived_repositories["fagenorn/argus"]` in `~/.agents/state/guard/policy.json`; and the section `## Task 7 — Registration and derived row`, holding the lines `Registered: <UTC time>` and `Row: main main ["memory foundation (unit + forced checks)"]`.

**Invariants:**
- The primary checkout's `HEAD`, its branch, its working tree and its untracked files are identical before and after this task. Only its remote-tracking refs and fetched objects may change (126 § 2, D14).
- Registration happens after Task 6's three times: `Registered` is later than each of them (AC9).
- The guard policy is rebuilt only by `claude-guard-policy`, which runs the activation's compile alone (D12). The compiled file is never hand-edited.

- [ ] **Step 1: Confirm the red state and the preconditions**

Run: `grep -c '^## Task 7 — Registration and derived row$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`. Expected: `0`.
Require the three Task 6 lines in `E`. Then snapshot the primary checkout:

```bash
git -C /Users/anis/Projects/argus rev-parse HEAD
git -C /Users/anis/Projects/argus symbolic-ref --short HEAD
git -C /Users/anis/Projects/argus status --porcelain=v1 --untracked-files=all | shasum -a 256
```

- [ ] **Step 2: Register**

Run (timeout 900 s): `launch-scope exec … -- adopt-project verify --register --repo-root /Users/anis/Projects/argus > "$SCR/register.json"`, then `date -u +%Y-%m-%dT%H:%M:%SZ`.
Then run `jq -c '{result, registered, checks: [.checks[]? | {id, status}]}' "$SCR/register.json"`. Expected: `result` `adopted`, `registered` `true`, and every check `passed`. On a `not_integrated` or any other refusal, record it and return `BLOCKED`, without retrying or passing `--integration-branch` (spec § 5).

- [ ] **Step 3: The registry entry**

Run: `python3 -I -c 'import json, os; print(json.dumps([p for p in json.load(open(os.path.expanduser("~/.agents/state/fleet/registry.json")))["projects"] if p["project_id"] == "fagenorn/argus"]))'`
Expected: exactly `[{"project_id": "fagenorn/argus", "root": "/Users/anis/Projects/argus"}]`, with no `branch_override`.

- [ ] **Step 4: Rebuild the guard policy (D12)**

Run (timeout 600 s): `launch-scope exec … -- claude-guard-policy > "$SCR/compile.json"`; record its exit status.
Then run `jq -c '{outcome, derived, refused: [.refused[] | {project_id, reason_code}]}' "$SCR/compile.json"`. Expected: `derived` contains `fagenorn/argus`, and no `refused` entry names it. Exit 1 is acceptable only when another project is refused; record those refusals as conditions.
Then run `python3 -I -c 'import json, os; d = json.load(open(os.path.expanduser("~/.agents/state/guard/policy.json"))); print(json.dumps(d["derivation"]), json.dumps(d["derived_repositories"]["fagenorn/argus"], sort_keys=True))'`
Expected: `derivation` has `schema_version` 3, and the row has `default_branch` `main`, `integration_branch` `main` and `required_checks` `["memory foundation (unit + forced checks)"]`.

- [ ] **Step 5: Re-derive the row alone**

Run (timeout 300 s): `launch-scope exec … -- guard-policy derive --repository fagenorn/argus | jq -c '{outcome, row}'`
Expected: `outcome` `derived`, and a `row` equal to Step 4's row.

- [ ] **Step 6: Fleet compatibility**

Run: `resolve-project platform-status --fleet | jq -c '.fleet[] | select(.project_id == "fagenorn/argus")'`
Expected: `compatible` `true`, `reason_code` `null`, and `root` `/Users/anis/Projects/argus`.

- [ ] **Step 7: The primary checkout is unchanged**

Re-run Step 1's three snapshot commands. Expected: identical output. A difference is reported verbatim and returns `BLOCKED` (D14).

- [ ] **Step 8: Write the section**

Append `## Task 7 — Registration and derived row` with the `Registered:` and `Row:` lines, the register report summary, the registry entry, the compile report summary (derived list and refusals), the derivation, the derive outcome, the fleet row, and the before/after snapshot of the primary checkout.

- [ ] **Step 9: Verify and commit**

Run:

```bash
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(grep -c '^## Task 7 — Registration and derived row$' "$E")" -eq 1
grep -qx 'Row: main main \["memory foundation (unit + forced checks)"\]' "$E"
python3 -I - "$E" <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read()
def at(key):
    return re.search(rf"^{key}: (\S+)$", text, re.M).group(1)
registered = at("Registered")
assert all(at(key) < registered for key in ("Doctor 2 passed", "Verify adopted", "Conformance held"))
EOF
```

Expected: exit 0. The times are ISO-8601 UTC, so they compare as strings.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T7): Argus registration and derived row" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":7,"records":[{"bounds":[{"added_lines":500,"boundary":"all","deleted_lines":0,"record_bytes":70656,"support":{"covers":["e1","e2","e3","e4","e5","e6","e7"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e7","last_task":8,"owner":7,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
