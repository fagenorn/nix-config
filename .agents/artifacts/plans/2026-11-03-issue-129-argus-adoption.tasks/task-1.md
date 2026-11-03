# Task 1: Fresh baseline

Spec § 6 "The fresh baseline", step 1 of § 4; AC6. This task only reads, and its one write is the new evidence file. It runs before anything else, so the baseline predates the adoption plan (Task 4).

**Files:**
- Create: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: host and forge state. That covers `/Users/anis/Projects/argus/.superpowers/workflows/*/state.json` (read-only), `fagenorn/argus` on GitHub, `launchctl print`, `/run/current-system`, `~/.agents/state/fleet/registry.json` and `~/.agents/state/guard/policy.json`.
- Produces: `E`, starting with the line `# Evidence — issue 129, Argus adoption`. A blank line follows, then the sentence `One section per task of the plan; raw outputs stay in the launch scratch (spec D18).`, then the section `## Task 1 — Fresh baseline` with the five subsections `### Workflow outcomes`, `### Argus PRs since 2026-08-01`, `### CI duration and bound`, `### Daemon-to-child handoff` and `### Host`.

**Invariants:**
- Nothing is written outside `E` and `SCR`. No `launchctl` verb other than `print` runs, and no file under `/Users/anis/Projects/argus` is opened for writing.
- The CI bound gate: take the ten most recent `CI` runs whose `status` is `completed` and whose `conclusion` is not `cancelled`. Each must have `updatedAt − startedAt ≤ 15 min`, where 15 is the workflow's `timeout-minutes` as read in Step 4. If any run exceeds it, adoption does not proceed (see Step 4).

- [ ] **Step 1: Confirm the red state**

Run: `grep -c '^## Task 1 — Fresh baseline$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`
Expected: exit 2 (no such file). Record the start time: `date -u +%Y-%m-%dT%H:%M:%SZ`.

- [ ] **Step 2: Workflow outcomes**

Run (timeout 60 s):

```bash
python3 -I - <<'EOF'
import glob, json
for path in sorted(glob.glob("/Users/anis/Projects/argus/.superpowers/workflows/*/state.json")):
    data = json.load(open(path, encoding="utf-8"))
    for issue, entry in sorted((data.get("issues") or {}).items()):
        outcome = entry.get("outcome") or {}
        last = (entry.get("attempts") or [{}])[-1]
        print("|", path.split("/")[-2], "|", issue, "|", outcome.get("state") or last.get("state"),
              "|", last.get("blocked_on"), "|", outcome.get("merge_sha"), "|", data.get("updated_at"), "|")
EOF
```

Expected: one table row per (run, issue). Put them under `### Workflow outcomes` with the header `| Run | Issue | Outcome | Blocked on | Merge SHA | Run updated |`. Then add one line counting the issues whose outcome is `merged` and the issues whose outcome is anything else.

- [ ] **Step 3: Argus PRs merged or closed since 2026-08-01**

Run (timeout 120 s): `env -u GITHUB_TOKEN -u GH_TOKEN gh pr list --repo fagenorn/argus --state all --limit 300 --json number,state,mergedAt,closedAt,mergedBy`. Keep each PR whose `mergedAt` or `closedAt` is on or after `2026-08-01T00:00:00Z`, and write `| PR | State | Merged or closed at | Merged by |` (`mergedBy.login`, or `—`). Then add one line giving the merged count, the closed-unmerged count and the set of merger logins.

- [ ] **Step 4: CI duration and bound**

Run (timeout 120 s):
- `env -u GITHUB_TOKEN -u GH_TOKEN gh api 'repos/fagenorn/argus/contents/.github/workflows/ci.yml?ref=main' --jq .content | base64 --decode | grep -n 'timeout-minutes\|name: memory foundation'`. Expected: `timeout-minutes: 15` and the job name `memory foundation (unit + forced checks)`.
- `env -u GITHUB_TOKEN -u GH_TOKEN gh run list --repo fagenorn/argus --workflow CI --limit 20 --json databaseId,event,headBranch,status,conclusion,startedAt,updatedAt`
- `env -u GITHUB_TOKEN -u GH_TOKEN gh issue view 5 --repo fagenorn/argus --json number,title,state,closedAt`, and the same for issue 80.

Write `| Run | Event | Branch | Status | Conclusion | Started | Minutes |` for all of the returned runs (up to 20), with the minutes to one decimal. Below the table, write the gate line `Bound: last ten completed non-cancelled runs, max <m> min against timeout-minutes 15 — within bound` or `— exceeded by run <id>`. Then record Argus issue 5's state and title, with the run ids that contradict "never completes" (completed `success` runs).

If the gate line says `exceeded`: finish Steps 5–7, commit, and return `BLOCKED human_gate` with the gate line as the block. Adoption needs bounded CI (the issue's 2026-09-19 refresh). The run resumes at Task 1, with a fresh baseline.

- [ ] **Step 5: Daemon-to-child handoff**

Run (timeout 60 s): `launchctl print "gui/$(id -u)/dev.argus.daemon" | grep -E '^\s*(state|pid|runs|last exit code) = '`
Expected: the `state`, `pid` and `runs` lines (`last exit code` if present). If the service is not loaded, record launchctl's message. Under `### Daemon-to-child handoff`, record those values and Argus issue 80's state from Step 4.

- [ ] **Step 6: Host**

Run (timeout 60 s):

```bash
readlink /run/current-system
readlink /nix/var/nix/profiles/system
stat -f '%Sm' -t '%Y-%m-%dT%H:%M:%S%z' /nix/var/nix/profiles/system
python3 -I -c 'import json, os; print(json.dumps(json.load(open(os.path.expanduser("~/.agents/state/fleet/registry.json")))["projects"]))'
python3 -I -c 'import json, os; d = json.load(open(os.path.expanduser("~/.agents/state/guard/policy.json"))); print(json.dumps(d.get("derivation")), sorted(d.get("derived_repositories", {})))'
if test -e "$HOME/Applications/ArgusPing.app"; then echo ArgusPing present; else echo ArgusPing absent; fi
```

Under `### Host`, record the generation link and its time, the registry's project ids, roots and `branch_override` reasons, and the compiled policy's `derivation` and derived repositories. Record whether `~/Applications/ArgusPing.app` is present (spec § 2: absent is expected, and nothing is removed).

- [ ] **Step 7: Write `E`**

Create `E` with the opening lines from Interfaces, then `## Task 1 — Fresh baseline`. Its first line names the host `mbp`, the start and end times, and `git rev-parse HEAD` of the worktree. The five subsections follow, holding Steps 2–6.

- [ ] **Step 8: Verify**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 14336
test "$(grep -c '^## Task 1 — Fresh baseline$' "$E")" -eq 1
for h in 'Workflow outcomes' 'Argus PRs since 2026-08-01' 'CI duration and bound' 'Daemon-to-child handoff' 'Host'; do grep -q "^### $h\$" "$E" || exit 1; done
grep -q '^Bound: last ten completed non-cancelled runs' "$E"
git diff --name-only HEAD
```

Expected: exit 0, and `git diff --name-only HEAD` lists nothing tracked (`E` is still untracked).

- [ ] **Step 9: Commit**

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T1): fresh Argus baseline" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Verify: `git status --short -- .agents/artifacts/plans` prints nothing.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64],"id":1,"records":[{"bounds":[{"added_lines":358,"boundary":"all","deleted_lines":0,"record_bytes":15360,"support":{"covers":["e1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"e1","last_task":8,"owner":1,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
