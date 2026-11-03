# Task 8: Guard probes, central-literal diff and the acceptance record

Spec § 4 steps 13–14 and § 6, per D13 and D18. This task holds AC2's and AC8's checks and writes the acceptance record for all nine criteria. Every probe is fed to the installed guard and never executed.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)
- Create: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md` (`A`)

**Interfaces:**
- Consumes: every section of `E`: Task 2's `G`, `R` and `C`, Task 7's `Row:` line, and Tasks 1–7's evidence.
- Produces: the section `## Task 8 — Guard probes and central-literal diff` in `E`, and `A` with one row per criterion, `AC1`–`AC9`.

**Invariants:**
- The guard is only fed payload files. Nothing is pushed, opened or merged (D13, D16).
- AC2's merge half is `met` only when both merge probes ran on one qualifying PR. With no qualifying PR it is `human_pending`, and the issue is held `needs-verification` (spec § 6).
- `A` restates no evidence. Each `Observed` cell cites the `E` section it came from, plus the key value.

**The probe.** `<clone>` is an Argus clone whose `origin` is `git@github.com:fagenorn/argus.git` and whose `refs/remotes/origin/HEAD` is `origin/main`. Run this as one Bash call (timeout 120 s), with literals substituted and each command passed only as a single-quoted argument:

```bash
python3 -I -c 'import json, sys; json.dump({"tool_name": "Bash", "tool_input": {"command": sys.argv[2]}, "cwd": sys.argv[1]}, open(sys.argv[3], "w", encoding="utf-8"))' '<clone>' '<command>' '<SCR>/probe-<name>.json'
'<G>' < '<SCR>/probe-<name>.json' 2> '<SCR>/probe-<name>.err'; echo "exit=$?"; cat '<SCR>/probe-<name>.err'
```

Exit 0 with no output means allowed. Exit 2 with `lifecycle guard: <reason>` means refused.

- [ ] **Step 1: Confirm the red state; the wrapper and a clone**

Run: `grep -c '^## Task 8 — Guard probes and central-literal diff$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`. Expected: `0`. Also `test ! -e .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md`.
The settings wrapper (`jq -r '.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[].command | select(endswith("/bin/claude-bash-lifecycle-guard"))' ~/.claude/settings.json`) must equal `G`.
Run (timeout 600 s): `launch-scope exec … -- git clone --quiet git@github.com:fagenorn/argus.git "$SCR/argus-probe"`, unless the clone exists. Its `origin/HEAD` must be `origin/main`.

- [ ] **Step 2: Push and PR-creation probes**

- `push`: `git push -u origin issue-129-guard-probe`. Expected: `exit=0`.
- `pr-create`: `gh pr create --repo fagenorn/argus --base main --head issue-129-guard-probe --title "Guard probe" --body "A non-executing guard probe for nix-config issue 129."` Expected: `exit=0`.

Since Task 7, the guard confirms Argus's derived row on these verbs and takes the base from it. Record each exit and output.

- [ ] **Step 3: Merge probes on a qualifying PR (D13)**

Run (timeout 120 s): `env -u GITHUB_TOKEN -u GH_TOKEN gh pr list --repo fagenorn/argus --state open --base main --json number`. For each listed PR, starting with 115 and then in ascending order, run `env -u GITHUB_TOKEN -u GH_TOKEN gh pr view <n> --repo fagenorn/argus --json headRefOid,mergeStateStatus,statusCheckRollup`.
A PR qualifies when `mergeStateStatus` is not `BEHIND` and every rollup entry named `memory foundation (unit + forced checks)` is a `CheckRun` with `status` `COMPLETED` and `conclusion` `SUCCESS`, with at least one such entry. Take the first qualifying PR, then run:

- `merge-floor`: `gh pr merge <n> --repo fagenorn/argus --merge --match-head-commit <headRefOid> --delete-branch`. Expected: `exit=0`.
- `merge-no-head`: `gh pr merge <n> --repo fagenorn/argus --merge --delete-branch`. Expected: `exit=2` with `lifecycle guard: unsafe merge: main cannot be protected on this repository's plan, so the merge must carry --match-head-commit with the reviewed PR head`.

If no PR qualifies, record `no qualifying open PR; merge half human_pending` and the reasons each PR failed to qualify.

- [ ] **Step 4: Central-literal diff (AC8)**

Run:

```bash
set -e
git fetch --quiet origin
git log --no-merges --oneline ed33215598521ba745f6262233e0c2c98ef1479f..HEAD ^origin/main -- home/common/claude-code/ python/agent_tools/ home/common/agent-skills/scripts/ lib/ hosts/
BP=$(nix-store --query --requisites '<R>' | grep -- '-claude-bash-lifecycle-guard-base-policy\.json$')
test "$(printf '%s\n' "$BP" | wc -l)" -eq 1
jq -c '{authorized_owners, integration_bases}' "$BP"
if grep -qi argus "$BP"; then echo "argus literal in base policy"; exit 1; fi
```

Expected: the log prints nothing (no commit of this branch's own touches a central path; a sync merge from `main` is not this delivery's); `authorized_owners` holds only the owner literal (`fagenorn`, which names no Argus fact, per 126 D3); `integration_bases` is `{}`; and the script exits 0. Also record, for AC8's tracing, where each Argus fact came from: the row (Task 7), the floor check (Task 3's contract `required_checks`), the release targets and the adapter executables (Task 4's inspection). Each traces to Argus's contract.

- [ ] **Step 5: Write the section in `E`**

Append `## Task 8 — Guard probes and central-literal diff` with `| Probe | Command | cwd | Exit | Guard output | Time |` for Steps 2–3, the qualifying-PR choice and its head, the diff result, the base policy's two members, and the tracing lines.

- [ ] **Step 6: Write `A`**

Create `A`. It opens with `# Acceptance record — issue 129`, then one sentence naming host `mbp`, the date, `git rev-parse HEAD` and the evidence file `E`. Then add the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`, with rows `AC1`–`AC9` in this order:
- First, the five checkbox lines under the issue's `## Acceptance criteria`.
- Then the four under `### Additional acceptance criteria`.

Read them with `env -u GITHUB_TOKEN -u GH_TOKEN gh issue view 129 --repo fagenorn/nix-config --json body --jq .body`, copied verbatim without the checkbox. Every `Kind` is `evidence (classified)`. `Check or command` is the plan's Acceptance map check. `Observed` is the measured value with its `E` section. `Commit` is the nix-config `HEAD` the measurement ran on: the commit that holds that task's section, or for Task 8's rows, the `HEAD` before this commit. `Conditions` names the host, the switch commit `C`, and anything the threshold depends on, such as AC2's chosen PR or AC3's "the classes did not recur on this host" when both checks passed in report 1.
`Verdict` uses one grading token, `met`, `unmet`, `unverified` or `human_pending`, judged against the plan's threshold. The sdd final review owns the final verdicts.

- [ ] **Step 7: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
A=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md
test "$(wc -c < "$E")" -le 57344
test "$(wc -c < "$A")" -le 12288
test "$(grep -c '^## Task [1-8] — ' "$E")" -ge 8
test "$(grep -Ec '^\| AC[1-9] \|' "$A")" -eq 9
if grep -Eq '^\| AC[1-9] \|.*\| *\|$' "$A"; then exit 1; fi
git log --no-merges --name-only --format= ed33215598521ba745f6262233e0c2c98ef1479f..HEAD ^origin/main -- . ':!.agents/artifacts/specs/2026-11-03-issue-129-argus-adoption-design.md' ':!.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.md' ':!.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.tasks' ':!.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md'
```

Expected: exit 0. The last command prints nothing, because none of this branch's own commits touches a file outside the plan package and `E`; `A` is not yet committed.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T8): guard probes, central-literal diff and acceptance record" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64],"id":8,"records":[{"bounds":[{"added_lines":1433,"boundary":"all","deleted_lines":0,"record_bytes":59392,"support":{"covers":["e1","e2","e3","e4","e5","e6","e7","e8"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e8","last_task":8,"owner":8,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"},{"bounds":[{"added_lines":300,"boundary":"all","deleted_lines":0,"record_bytes":13312,"support":{"covers":["a8"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"a8","last_task":8,"owner":8,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.acceptance.md"}]}}
```
