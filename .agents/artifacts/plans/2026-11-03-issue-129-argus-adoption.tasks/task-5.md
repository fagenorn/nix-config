# Task 5: Pre-registration guard probes and the owner gate

Spec § 4 steps 7–9 and § 5, as amended by D16, per D8 and D13. The guard reads a `gh` verb's repository from the hook payload's `cwd`, and every agent here runs from the nix-config launch directory. So the owner opens and merges the bootstrap PR, and this task proves what the installed guard would decide, without executing anything. The task ends the run's second human gate: after review, the controller suspends `blocked_on=human_gate` and the run resumes at Task 6.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: from `E`, Task 2's `Guard wrapper: <G>` and Task 4's `Adoption branch: adopt-<digest12>` and `Adoption commit: <H>`; the clone `$SCR/argus-129` if this launch still has it.
- Produces: the section `## Task 5 — Pre-registration probes and owner gate`, holding the two probe verdicts and the subsection `### Owner gate` (the block below). Task 6 reads the block's head `H` and branch.

**Invariants:**
- The guard is only ever fed a payload file. No `gh pr create`, `gh pr merge` or `git push` runs in this task, and each probed command appears in the Bash text only as one single-quoted argument.
- The wrapper fed is the one `~/.claude/settings.json` registers now, and it must equal Task 2's `G` (spec § 5: the switch installed it).
- An unexpected verdict is recorded as observed and never acted on (D16). The gate block is written whatever the verdicts are.

**The probe** (reused below). `<clone>` is an Argus clone whose `origin` is `git@github.com:fagenorn/argus.git` and whose `refs/remotes/origin/HEAD` is `origin/main`. `<name>` is a short label. Run this as one Bash call (timeout 120 s), with literals substituted:

```bash
python3 -I -c 'import json, sys; json.dump({"tool_name": "Bash", "tool_input": {"command": sys.argv[2]}, "cwd": sys.argv[1]}, open(sys.argv[3], "w", encoding="utf-8"))' '<clone>' '<command>' '<SCR>/probe-<name>.json'
'<G>' < '<SCR>/probe-<name>.json' 2> '<SCR>/probe-<name>.err'; echo "exit=$?"; cat '<SCR>/probe-<name>.err'
```

Exit 0 with no output means the guard allowed the command. Exit 2 with `lifecycle guard: <reason>` means it refused.

- [ ] **Step 1: Confirm the red state; check the wrapper**

Run: `grep -c '^## Task 5 — Pre-registration probes and owner gate$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`. Expected: `0`.
Run: `jq -r '.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[].command | select(endswith("/bin/claude-bash-lifecycle-guard"))' ~/.claude/settings.json`. Expected: exactly `G`. A different path means the installation moved since Task 2: return `BLOCKED` with both paths.

- [ ] **Step 2: A probe clone**

If `$SCR/argus-129` exists, use it as `<clone>`. Otherwise run (timeout 600 s) `launch-scope exec … -- git clone --quiet git@github.com:fagenorn/argus.git "$SCR/argus-probe"` and use that. In either case, `git -C <clone> symbolic-ref refs/remotes/origin/HEAD` must print `refs/remotes/origin/main`.

- [ ] **Step 3: Probe the PR creation the owner will run**

`<name>` is `pr-create`, and `<command>` is exactly:
`gh pr create --repo fagenorn/argus --base main --head adopt-<digest12> --title "Adopt the project contract" --body "Adds the Argus project contract and the adopt-project adoption commit for https://github.com/fagenorn/nix-config/issues/129. Merge with a merge commit once the required check is green on the pushed head."`
Expected: `exit=0`, which the `fagenorn` owner literal authorizes (spec § 6).

- [ ] **Step 4: Probe a pre-registration merge**

Run: `env -u GITHUB_TOKEN -u GH_TOKEN gh pr list --repo fagenorn/argus --state open --base main --json number,headRefOid,mergeStateStatus`. Choose PR 115 if it is listed; otherwise choose the lowest-numbered listed PR. `<name>` is `merge-pre`, and `<command>` is:
`gh pr merge <n> --repo fagenorn/argus --merge --match-head-commit <headRefOid> --delete-branch`
Expected: `exit=2` with `lifecycle guard: protection lookup failed: …`. With no registered row, the plan-gated 403 declares no check, which is the bootstrap refusal (552 D8). If no open PR into `main` exists, record `no open PR into main; merge probe not run`.

- [ ] **Step 5: Remove the clones**

For each clone made in this launch (`$SCR/argus-129`, `$SCR/argus-probe`): `git -C <clone> status --porcelain` must be empty. For `$SCR/argus-129`, `git -C "$SCR/argus-129" ls-remote origin refs/heads/adopt-<digest12>` must also print `H`. Then remove each clone with `rm -rf <clone>` (spec § 4 step 9). The branch is safe on `origin`.

- [ ] **Step 6: Write the section and the gate block**

Append `## Task 5 — Pre-registration probes and owner gate` with `| Probe | Command | cwd | Exit | Guard output | Time |` for Steps 3 and 4. Then add this subsection, with literals substituted:

```markdown
### Owner gate
Owner gate: open and merge adopt-<digest12> at head <H>
1. Open the PR from any Argus checkout, or on GitHub with base main and head adopt-<digest12>:
   gh pr create --repo fagenorn/argus --base main --head adopt-<digest12> --title "Adopt the project contract" --body "<the body from Step 3>"
2. Wait until the check memory foundation (unit + forced checks) is green on head <H>. If it is red, leave the PR open and unmerged.
3. Merge with a merge commit, never squash or rebase, deleting the branch:
   gh pr merge <n> --repo fagenorn/argus --merge --match-head-commit <H> --delete-branch
   or use GitHub's Create a merge commit.
Resume: the run continues at Task 6, which confirms the merge before anything else.
```

- [ ] **Step 7: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 44032
test "$(grep -c '^## Task 5 — Pre-registration probes and owner gate$' "$E")" -eq 1
grep -Eq '^Owner gate: open and merge adopt-[0-9a-f]{12} at head [0-9a-f]{40}$' "$E"
test "$(sed -n 's/^Owner gate: open and merge adopt-[0-9a-f]* at head //p' "$E")" = "$(sed -n 's/^Adoption commit: //p' "$E")"
```

Expected: exit 0.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T5): pre-registration probes and the owner gate" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Report `DONE`, with the line `human_gate: owner open-and-merge (E § Task 5, Owner gate)` so the controller suspends after review.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"76e46b54691a7292275095e7bd4641cdbf446bb2","head":"675093485373f61c6f13aefdfbd659dc527932ce"}],"commit_subject_bytes":[64],"id":5,"records":[{"bounds":[{"added_lines":1100,"boundary":"all","deleted_lines":0,"record_bytes":46080,"support":{"covers":["e1","e2","e3","e4","e5"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e5","last_task":8,"owner":5,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
