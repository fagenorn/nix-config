# Task 1: Commit the truthful pre-terminal evidence checkpoint

**Files:**
- Create: `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`

**Interfaces:**
- Consumes: the committed design and full plan package at the fresh delegated owner's exact reviewed HEAD; the `direct-75-000002` owner envelope; the sealed pre-rollover controller prefix and structured Phase-5 `delegate`/relay records; the fresh owner's session metadata and adoption record; canonical ledger path; issue-74 merge `f3fac9554761d0c3085d70bf4526cf3e7486de3e` and base `c780b38f613c59a7d6674dc081d9f67666054ebf`; activated installed files; historical sessions `01a01acf-a82d-7953-813b-401d252e02da` and `01a01bd9-8c37-7181-86de-58c82f6a643a`; D1–D7.
- Produces: `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md` with the seven design-specified sections, verdict `pending`, exact already-observed anchors/results, a complete current role inventory, and an explicit closed list of evidence that Task 2 must add.

**Invariants:**
- Start only after the fresh controller has validated the unchanged run/attempt/owner/worktree envelope, distinct session identity, reviewed full HEAD, tracked spec/plan roots, and Phase-5 `delegate` handoff. The earlier controller performs no report edit.
- The report records the immutable issue-74 merge/base, reviewed HEAD, activated store path, deployment/session timestamps, installed-file identities, pre-rollover sealed prefix, Phase-5 observation, fresh-owner identity, pre-rollover Git range, structured dispatch inventory, and rechecked historical observations only when directly measured.
- The pre-rollover allowed Git paths are exactly the design, plan root, and `task-1.md`/`task-2.md` members. Any other changed path, any pre-delegate SDD launch, or any implementation edit is recorded as a failed invariant, never omitted.
- The pending report does not name a representative-run merge, terminal outcome, terminal-ledger digest, fresh-owner terminal prefix size/digest, fresh-owner maximum token record, final verdict, or final evidence commit as if known. It names each as remaining evidence.
- Runtime evidence is compact structured data, never transcript prose. Every mutable-path claim carries an absolute path and, once its relevant prefix is closed, exact bytes plus SHA-256.
- The historical observations are re-extracted from `/Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T17-16-51-01a01acf-a82d-7953-813b-401d252e02da.jsonl` and `/Users/anis/.codex/sessions/2026/08/19/rollout-2026-08-19T22-07-17-01a01bd9-8c37-7181-86de-58c82f6a643a.jsonl`; they are not copied from Markdown.
- All reproduction rows use literal resolved paths and full object IDs, produce compact output, and have `pass`, `fail`, or `remaining` dispositions. Symbolic shell variables may be used while gathering facts but do not remain in the committed commands.
- This task makes no lifecycle call and does not activate, ship, reacquire, or start SDD. Lifecycle progression remains the fresh owner's responsibility outside the report implementation.

- [ ] **Step 1: Write and run the pending-report structural test and observe the missing artifact**

```bash
python3 - <<'PY'
from pathlib import Path

path = Path(".claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md")
text = path.read_text(encoding="utf-8")
required = [
    "## Verdict and scope",
    "## Deployment freshness",
    "## Lifecycle trace",
    "## Controller input",
    "## Pre-rollover boundary",
    "## Historical comparison",
    "## Reproduction matrix",
]
assert all(text.count(heading) == 1 for heading in required)
assert "- Verdict: `pending`" in text
assert "direct-75-000002" in text
assert "150000" in text
assert "remaining" in text.lower()
PY
```

Expected: FAIL with `FileNotFoundError` because the evidence report does not exist at the reviewed planning commit.

- [ ] **Step 2: Capture immutable deployment, ownership, and historical facts**

Use a temporary directory outside the worktree for bounded command outputs. Resolve and record, without changing lifecycle state:

1. `git show -s --format='%H%n%P%n%cI'` for the issue-74 merge, its base, and reviewed HEAD; `git cat-file -e <full-sha>^{commit}` for each; `git diff --name-only f3fac9554761d0c3085d70bf4526cf3e7486de3e <reviewed-head> --` for the exact pre-rollover range.
2. `readlink /run/current-system`, platform `stat` for its activation epoch, and `realpath` for `/Users/anis/.agents/skills/from-issue/SKILL.md`, `/Users/anis/.agents/skills/from-issue/AUTO.md`, and `/Users/anis/.agents/bin/workflow-state`. Compare each with `cmp` against `git show f3fac9554761d0c3085d70bf4526cf3e7486de3e:<tracked-path>` bytes and prove the corresponding `c780b38f613c59a7d6674dc081d9f67666054ebf:<tracked-path>` differs. The tracked paths are `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/AUTO.md`, and `home/common/agent-skills/scripts/workflow-state.py`.
3. Extract only `session_meta` identity/start/cwd plus the structured owner/adoption/progress/dispatch/task/relay records needed by the report. Derive the pre-rollover prefix endpoint from its Phase-5 terminal relay record, then record `wc -c` over that exact prefix and `shasum -a 256` over exactly those bytes. Record the compact Phase-5 fields `run_id`, `issue`, `attempt`, `owner`, `worktree`, `phase`, and `phase_action` from the sealed observation.
4. Enumerate every session associated with this run from structured dispatch/task ownership records, not from a free-text hit. For each, record session ID, role, authority evidence, and D2 inclusion decision. Require the fresh owner's session ID to differ from the pre-rollover controller, its start to follow the Phase-5 observation, and its adoption envelope to equal the run/attempt/owner/worktree values.
5. For each of the two fixed historical rollout paths, use `session_meta` plus completed `token_count` records to select maximum logical input with later-timestamp tie-break; record the exact session ID, path, file size, full-file SHA-256, selected timestamp, logical, cached, and derived fresh values. These rows are context only per D5.

If a required pre-terminal fact is unavailable, record that fact as unavailable with `remaining` or `fail` according to whether it is genuinely terminal-dependent; do not infer it. If deployment ordering or the ownership boundary already fails, preserve that observed failure while keeping the overall pre-terminal verdict `pending`.

- [ ] **Step 3: Write the compact pending report**

Create the report with exactly the seven required level-two sections. Populate prose from the live compact results rather than from predicted values. The sections must carry these contracts:

- `Verdict and scope`: the exact line ``- Verdict: `pending` ``; run, attempt, owner, exact worktree, inclusive logical ceiling, reviewed HEAD; one-trace limitation; a closed list of terminal-ledger state, representative merge, fresh-controller sealed metrics, final matrix replay, and final evidence commit as remaining.
- `Deployment freshness`: full merge/base IDs, merge/activation/process/session times, activated store path, the three installed/tracked byte-equality results, base-difference results, and the explicit ordering disposition.
- `Lifecycle trace`: direct-owner and fresh-owner session identities, sealed pre-controller path/bytes/digest, exact Phase-5 `delegate` observation, unchanged envelope comparison, and current role-inventory table.
- `Controller input`: a row for the pre-rollover controller only if its prefix is closed and measurable; a visibly pending row for the still-active fresh controller; columns `role`, `session`, `prefix path`, `bytes`, `sha256`, `selected at`, `logical`, `cached`, `fresh`, `<=150000`, and `status`. Do not place a provisional maximum in the fresh row.
- `Pre-rollover boundary`: full range, exact changed-path result, structured dispatch/task inventory, no-SDD conclusion, and first-fresh-owner activity known at capture time.
- `Historical comparison`: the two fixed sessions' rechecked compact rows and only the descriptive limitations in D5.
- `Reproduction matrix`: one row per claim with immutable anchor, literal command/query, compact observed result, and `pass`/`fail`/`remaining`. Commands that depend on terminal facts are described as remaining evidence, not fabricated invocations/results.

- [ ] **Step 4: Verify the pending checkpoint**

Run the Step-1 Python contract again.

Expected: PASS with no output; any missing/duplicated section, missing `pending`, run ID, ceiling, or remaining-evidence marker leaves the task incomplete.

Run every `pass` or `fail` reproduction row from the report against the exact named anchor.

Expected: each compact output byte-for-byte matches its recorded result and disposition. Any mismatch must be corrected in the report; an unavailable value remains explicit and never becomes a pass.

Run: `git diff --check -- .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`

Expected: exit 0 with no output.

Run: `bash -c 'set -euo pipefail; actual=$(mktemp); trap '\''rm -f "$actual"'\'' EXIT; { git diff --name-only HEAD --; git ls-files --others --exclude-standard; } | LC_ALL=C sort -u >"$actual"; if ! cmp -s "$actual" <(printf "%s\n" ".claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md"); then cat "$actual"; exit 1; fi'`

Expected: exit 0 with no output; any current-task edit outside the evidence report is printed and fails.

- [ ] **Step 5: Commit**

```bash
git add .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md
git commit -m "docs(issue-75): capture pending controller evidence" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

After the commit, rerun the structural contract and all non-remaining reproduction rows. If a hook changed the report, correct it and create a new commit before returning Task 1 as complete. The fresh owner may then continue the ordinary Phase-6/7 lifecycle; it must not dispatch Task 2 during this run.
