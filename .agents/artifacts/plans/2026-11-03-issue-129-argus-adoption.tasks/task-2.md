# Task 2: Switch `mbp` and prove installed/source conformance

Spec § 4 step 2 and § 6 "Installed/source conformance", per D11 and D20; it supplies AC9's first conformance pass. The installed resolver predates the 561 merge (`ed332155`) and refuses `required_checks`, so the switch must come before Argus's contract is resolved (Task 3). This task holds the run's first human gate.

**Files:**
- Modify: `.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md` (`E`)

**Interfaces:**
- Consumes: Task 1's section of `E`; the ledger repository `/Users/anis/tmp/nix-config` and its `origin`; the host's `sudo` (Touch ID).
- Produces: the section `## Task 2 — Switch and installed/source conformance`, holding the lines `Switch commit: <C>` (40 hex), `System: <R>` (the store path), `Guard wrapper: <G>` (absolute path) and `Platform version: <V>`, plus the four conformance results with their UTC times. Tasks 3, 5, 6 and 8 read `G` and `V`, and Task 6 reads `C` and `R`.

**Invariants:**
- `C` contains `ed33215598521ba745f6262233e0c2c98ef1479f`. Once `C` is written to `E` (in a gate block or the section), every later attempt uses that `C`, never a newer `origin/main` (D20).
- The switch runs at most once per attempt, from a clean scratch checkout of `C`. It never runs from this worktree or from the primary checkout.
- A failed `sudo` authentication is a human gate, never retried in a loop. Any other build or activation failure is a task failure, reported with its last 30 lines.

- [ ] **Step 1: Confirm the red state**

Run: `grep -c '^## Task 2 — Switch and installed/source conformance$' .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`
Expected: `0` (exit 1).

- [ ] **Step 2: Pin the switch commit `C`**

If `E` holds a line `Switch gate: commit <C>` (written by an earlier attempt of this task), take that `<C>`. Otherwise run `launch-scope exec … -- git -C /Users/anis/tmp/nix-config fetch --quiet origin` (timeout 300 s) and set `C=$(git -C /Users/anis/tmp/nix-config rev-parse origin/main)`.
Then run `git -C /Users/anis/tmp/nix-config merge-base --is-ancestor ed33215598521ba745f6262233e0c2c98ef1479f "$C"`. Expected: exit 0.

- [ ] **Step 3: Scratch checkout and build**

Run (timeout 300 s): `launch-scope exec … -- git -C /Users/anis/tmp/nix-config worktree add --detach "$SCR/nix-config-switch" "$C"`. If `$SCR/nix-config-switch` already exists at `C` with a clean tree, keep it.
Run (timeout 3600 s): `launch-scope exec … -- just --justfile "$SCR/nix-config-switch/justfile" --working-directory "$SCR/nix-config-switch" build`
Then set `R=$(readlink -f "$SCR/nix-config-switch/result")`. Expected: a `/nix/store/…-darwin-system-…` path.

- [ ] **Step 4: Switch, unless already installed**

If `readlink -f /run/current-system` equals `R`, record `Switch: already installed` and go to Step 5. This happens on resume after the owner ran the gate.

Otherwise run (timeout 3600 s): `launch-scope exec … -- just --justfile "$SCR/nix-config-switch/justfile" --working-directory "$SCR/nix-config-switch" switch`. Its `sudo` asks for Touch ID on the host.

- Exit 0: record `Switch: run at <UTC time>`.
- Non-zero with `sudo` authentication output (a terminal or password required, or authentication failed or timed out): append this gate block to `E`, commit it as in Step 7 with the subject `docs(issue-129/T2): switch gate block`, then return `BLOCKED human_gate` quoting the block:

  ```markdown
  ## Task 2 — Switch gate
  Switch gate: commit <C>
  The switch needs owner presence for sudo (Touch ID). From a clean checkout of <C> of
  /Users/anis/tmp/nix-config on mbp, run `just switch`. The run then resumes at Task 2 Step 2,
  which uses commit <C> and skips the switch once /run/current-system is that build.
  ```

- Any other failure: return `BLOCKED` with the last 30 lines of output; it is not a gate.

- [ ] **Step 5: Installed/source conformance (D11)**

Run (timeout 120 s):

```bash
set -e
W="$SCR/nix-config-switch"
test -z "$(git -C "$W" status --porcelain)"
test "$(git -C "$W" rev-parse HEAD)" = "$C"
test "$(readlink -f /run/current-system)" = "$R"
GUARD_PKG=$(nix-store --query --requisites "$R" | grep -- '-claude-bash-lifecycle-guard$')
test "$(printf '%s\n' "$GUARD_PKG" | wc -l)" -eq 1
G=$(jq -r '.hooks.PreToolUse[] | select(.matcher == "Bash") | .hooks[].command | select(endswith("/bin/claude-bash-lifecycle-guard"))' ~/.claude/settings.json)
test "$G" = "$GUARD_PKG/bin/claude-bash-lifecycle-guard"
test -x "$G"
printf 'G=%s\n' "$G"
```

Expected: exit 0, then `G=…`. Next run (timeout 600 s):
`launch-scope exec … -- bash -c 'set -o pipefail; cd "$1" && PYTHONPATH="$1/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_installed_policy_surface_matches_source_contract 2>&1 | tail -4' _ "$SCR/nix-config-switch"`
Expected: `OK`, exit 0.

Then record the platform version and the compiled policy's derivation:
`resolve-project platform-status | jq -r .platform.platform_version` gives `V`, which must be strict SemVer, and the command
`python3 -I -c 'import json, os; print(json.dumps(json.load(open(os.path.expanduser("~/.agents/state/guard/policy.json")))["derivation"]))'`
should print `"schema_version": 3`. If the derivation is not schema 3, the guard policy was not recompiled by the 561 activation: return `BLOCKED` with that observation.

- [ ] **Step 6: Write the section**

Append `## Task 2 — Switch and installed/source conformance` to `E`. List the four `Produces` lines and the `Switch:` line from Step 4. Then add a table `| Check | Result | Time |` with these rows: clean tree at `C`; `/run/current-system` = `R`; hook names `G` from `R`'s closure; `test_installed_policy_surface_matches_source_contract`. Close with the derivation line.

- [ ] **Step 7: Verify and commit**

Run:

```bash
set -e
E=.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
test "$(wc -c < "$E")" -le 18432
test "$(grep -c '^## Task 2 — Switch and installed/source conformance$' "$E")" -eq 1
grep -Eq '^Switch commit: [0-9a-f]{40}$' "$E"
grep -Eq '^Guard wrapper: /nix/store/[^ ]+/bin/claude-bash-lifecycle-guard$' "$E"
grep -Eq '^Platform version: [0-9]+\.[0-9]+\.[0-9]+$' "$E"
```

Expected: exit 0.

```bash
git add .agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-129/T2): switch and installed/source conformance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"58f89f6744b68bc208aedfd6e27f509c113bb1e7","head":"02f0884e3e73070733f18ce7333d44f0394a5e4c"}],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":460,"boundary":"all","deleted_lines":0,"record_bytes":19456,"support":{"covers":["e1","e2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"e2","last_task":8,"owner":2,"path":".agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md"}]}}
```
