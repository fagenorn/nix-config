# Task 4: Adoption plan, apply, profile inspection and push

Spec § 4 steps 5–7 (the push only; D16 moves PR creation to the owner) and § 3; per D7, D10, D16, D17 and D18. It holds the checks for AC4, AC5 and AC7. The push comes last, so the reviewed adoption branch survives a suspension (D17).

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: Task 3's clone `$SCR/argus-129` at contract commit `K`; Task 3's section in `E` (`Argus base`, `Contract commit`, `Contract sha256`, the compact contract line and doctor report 1's findings).
- Produces: the remote branch `origin/adopt-<digest12>` whose tip `H` is the tool's adoption commit, whose parent is `K`, and whose grandparent is `B`.
- Produces: the section `## Task 4 — Adoption plan, apply and inspection`, with the lines `Plan id: sha256:<hex>`, `Adoption branch: adopt-<digest12>`, `Adoption commit: <H>` and `Pushed: <UTC time>`. Tasks 5–8 read them.

**Invariants:**
- `apply` runs at most once per plan id, with no `--acknowledge-deletions`. A plan with a `delete-file` operation is never applied. A retained failed-apply worktree under `~/.agents/state/adopt/worktrees/` is never deleted by this task.
- `origin/main..adopt-<digest12>` holds exactly two commits, `K` then `H`, and nothing is pushed except that branch.
- Each repository finding in doctor report 1 is matched to the plan operation that repairs it, or the stage stops (D10).

- [ ] **Step 1: Confirm the red state; make sure the clone exists**

Run: `grep -c '^## Task 4 — Adoption plan, apply and inspection$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`. Expected: `0`.
If `git -C "$SCR/argus-129" rev-parse HEAD` prints the `Contract commit:` value from `E`, continue. Otherwise the launch changed since Task 3, so rebuild the contract commit:
1. Clone with `launch-scope exec … -- git clone --quiet git@github.com:fagenorn/argus.git "$SCR/argus-129"` (timeout 600 s), then `git -C "$SCR/argus-129" switch --quiet -c project-contract <B>`.
2. Run `mkdir -p "$SCR/argus-129/.agents"` (the base tracks no `.agents/` directory). Take the compact line from `E`'s Task 3 `json` block and write it as `python3 -I -c 'import json, sys; open(sys.argv[2], "w", encoding="utf-8").write(json.dumps(json.loads(open(sys.argv[1], encoding="utf-8").read()), indent=2) + "\n")' <line file> "$SCR/argus-129/.agents/project.json"`. Save the line to a file under `SCR` first.
3. `shasum -a 256` of the file must equal `Contract sha256:`.
4. Commit exactly as Task 3 Step 4, staging in the clone: `git -C "$SCR/argus-129" add .agents/project.json`, then `env -C "$SCR/argus-129" launch-commit … -- -m "chore: add the project contract" -m "Declares Argus's project policy for the cross-agent project system, adopted under https://github.com/fagenorn/nix-config/issues/129." -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"`.
5. Record `Contract commit (rebuilt): <K'>` for the section and use `K'` as `K` from here on. The pre-flight is not repeated: `apply`'s `workflow-verification-commands` gate runs every verification command in full.

- [ ] **Step 2: The adoption plan**

Run (timeout 900 s): `launch-scope exec … -- adopt-project plan --repo-root "$SCR/argus-129" > "$SCR/plan.json"`, then summarize:

```bash
python3 -I - "$SCR/plan.json" <<'EOF'
import collections, json, sys
doc = json.load(open(sys.argv[1], encoding="utf-8"))
plan = doc["plan"]
print("state", plan["state"], "outcome", plan["outcome"], "plan_id", plan["plan_id"], "base", plan["base_revision"])
print("blockers", json.dumps(plan["blockers"]))
for gate in doc["verification"]["ready_gates"]:
    print("ready-gate", json.dumps(gate, sort_keys=True))
for row in doc["evidence"]:
    print("evidence", json.dumps(row, sort_keys=True)[:300])
print("open", json.dumps(doc["decisions"]["open"]))
print("ops", dict(collections.Counter(op["op"] for op in doc["changes"])))
print("handoff", doc["handoff"]["next_command"], doc["handoff"]["evidence_record"], doc["handoff"]["migration_map"])
EOF
```

Expected: `state ready`, `outcome reconcile`, `base` equal to `K`, all eight ready gates `passed`, `open []`, no `delete-file` key in `ops`, and no evidence row whose action is `needs-decision`.
- Some question is open: if it has one recommended value, re-run the plan with `--answer <QUESTION> <SUBJECT> <VALUE>` for that value, and record it in an `Answered questions` table. A question without one recommended value means `BLOCKED human_gate`, naming the question; the run resumes at this step.
- A `delete-file` operation means `BLOCKED human_gate`, naming the paths; deletions are outside the owner's authorization.
- Any other failed gate: `contract-valid-after-amendment` refusing a value the contract cannot express is a contract gap. Anything else is `BLOCKED` with the gate verbatim.

- [ ] **Step 3: Match doctor report 1's findings (D10)**

For each non-`passed` repository check in Task 3's doctor report 1, name the operation in `ops`/`changes` that repairs it. Expected pairs: projection drift goes to the `regenerate-projection` operation for `CLAUDE.md`, and `repository.ignore.runtime_sentinel` goes to the `.gitignore` amendment and runtime sentinel operations. A finding with no repairing operation is a stop, routed like a failed gate in Step 2.

- [ ] **Step 4: Apply**

Run (timeout 3600 s; it runs every verification command in a fresh worktree): `launch-scope exec … -- adopt-project apply --plan-id <plan_id> > "$SCR/apply.json"`
Expected: exit 0 and JSON `{"branch": "adopt-<digest12>", "commit": "<H>", "plan_id": …, "migration_map": …, "evidence_record": …}`. Then:
`python3 -I -c 'import json, sys; d = json.load(open(sys.argv[1])); print([(g["id"], g["status"]) for g in d["verification"]["commit_gates"]])' ~/.agents/state/adopt/plans/<plan file>`
Name the plan file from the handoff's `plan_path`. Expected: all seven commit gates `passed`.
A refusal: record its JSON, and do not retry or clean up. If the apply report or a gate names a binding, capability or artifact class the contract cannot express, it is a contract gap. Otherwise return `BLOCKED` with the refusal.

- [ ] **Step 5: Inspect the adoption branch (AC5, AC7)**

Run `git -C "$SCR/argus-129" switch --quiet adopt-<digest12>`, then:
- `git -C "$SCR/argus-129" log --format='%H %P %s' origin/main..HEAD`. Expected: exactly two lines, `H` (parent `K`) and `K`.
- `git -C "$SCR/argus-129" diff --name-status origin/main...HEAD | cut -c1-4 | sort | uniq -c` (record the counts).
- `resolve-project resolve --repo-root "$SCR/argus-129" | jq -c '[.capabilities.release, [.release.targets[] | [.profile, .adapter, .target.handle, .operations]]]'`. Expected: `{"state":"available",…}`, plus the targets `forge-main/github-forge/repository/[]`, `local-host/launchd-agent/daemon/["activate"]` and `local-host/codesigned-artifact/notifier/["install"]`.
- For `P` in `local-host` and `forge-main`: `release profile inspect "$P" --repo-root "$SCR/argus-129" | jq -c '.conformance.checks, .conformance.findings'`. Expected: exit 0, with `repository.release_profile.observation_deadline`, `.restore_anchor` and `.rolled_back_reachable` all `passed`, and findings `[]`.

A result other than expected is a stop: an inexpressible unit is a contract gap (AC5's rewind), and anything else is `BLOCKED`.

- [ ] **Step 6: Push**

Run this alone in its own Bash call, not inside `launch-scope exec` (timeout 300 s):
`git -C <SCR literal>/argus-129 push -u origin adopt-<digest12>`
Then `git -C "$SCR/argus-129" ls-remote origin refs/heads/adopt-<digest12>` must print `H`. A guard refusal stops the task: report it verbatim and never route around it.

- [ ] **Step 7: Write the section**

Append `## Task 4 — Adoption plan, apply and inspection` with:
- The four `Produces` lines (plus `Contract commit (rebuilt)` if Step 1 rebuilt it).
- The plan summary (state, outcome, ready gates, op counts), the `Answered questions` table if any, and the plan's evidence rows for `.claude/skills`, `AGENTS.md` and `CLAUDE.md`.
- The finding-to-operation table from Step 3, the seven commit gates, the diff counts, and the resolve and inspection results.
- This statement (AC7, D5), verbatim: `The four bare helpers authd, ocr-helper, wa-bridge and wkfetch are signed in place inside the checkout, gitignored, and rebuilt by Argus's devenv shell entry only when absent. They are inputs of the daemon unit, not release units. The daemon unit's identity proves the checkout at the candidate commit with no tracked change, which an untracked stale helper binary passes, so a release does not prove that the helpers were rebuilt from the candidate commit.`

- [ ] **Step 8: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 38912
test "$(grep -c '^## Task 4 — Adoption plan, apply and inspection$' "$E")" -eq 1
grep -Eq '^Adoption commit: [0-9a-f]{40}$' "$E"
H=$(sed -n 's/^Adoption commit: //p' "$E"); BR=$(sed -n 's/^Adoption branch: //p' "$E")
test "$(git -C "$SCR/argus-129" ls-remote origin "refs/heads/$BR" | cut -f1)" = "$H"
grep -q '^The four bare helpers authd' "$E"
```

Expected: exit 0.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T4): Argus adoption plan, apply and push" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"0882b079830426c506de23e5f005c7b6c887991e","head":"72ccd35d61c65585266e53c82b37684ff60123c3"}],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":972,"boundary":"all","deleted_lines":0,"record_bytes":40960,"support":{"covers":["e1","e2","e3","e4"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e4","last_task":8,"owner":4,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
