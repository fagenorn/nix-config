# Task 2: Re-point the sibling-added reference

This task was added at owner step B1 under D10 and D13. The restarted B1 synced
`origin/main` at `763465f`, which landed #176. That merge added one living legacy
reference that Task 1 could not see. It lands before any tool output, like Task 1,
because `adopt-project plan` needs a clean tree at the head it plans. The lane is `full`,
because the lane rules exclude migration work from `low-risk`.

**Files:**
- Modify: `docs/standards/agent-helpers.md` (1 line, the lifecycle-guard paragraph
  after rule 5)
- Test: none committed. The gate below is an uncommitted script under `$TMPDIR`
  (spec "Test seams": no test is added).

**Interfaces:**
- Consumes: the same classifier row as Task 1: `.claude/specs` goes to
  `.agents/artifacts/specs`. The engine is read, never changed.
- Produces: one new target. Owner step B3 checks it against the live plan's `git-mv`
  targets, and B6 checks that it resolves at the adoption commit.
  - `.agents/artifacts/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md`

**Invariants:**
- Exactly one line changes, with numstat `1/1` in `docs/standards/agent-helpers.md`.
  Nothing else on that line changes, and no other file changes.
- At this commit the new target does not exist yet. The link resolves only after the
  adoption commit, which is expected (D4). Never create, copy or move a target file
  here. The engine does that.
- The old target is tracked today, so the adoption moves it to the new path.
- No commit message carries a closing keyword for #149 (D6).

## Exact edit

Replace the old string with the new one. Nothing else changes.

1. `docs/standards/agent-helpers.md`, line 16 (the one occurrence):
   ```text
   old: ([design](../../.claude/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))
   new: ([design](../../.agents/artifacts/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))
   ```

- [ ] **Step 1: Record the start and write the gate**

```bash
cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-149-orchestrated
START=$(git rev-parse HEAD)
GATE=$(mktemp "${TMPDIR:-/tmp}/a2-gate-XXXXXX.sh")
{ printf 'START=%s\n' "$START"; cat; } > "$GATE" <<'EOF'
set -euo pipefail
S=home/common/agent-skills
# (1) No legacy artifact path in the living tree. The exclusions match Task 1's gate.
if git grep -n -E '\.claude/(specs|plans)|\.out-of-scope' -- . \
    ':!.claude/specs' ':!.claude/plans' ':!.out-of-scope' ':!.agents/project.json' \
    ":!$S/tests" ":!$S/evals/fixture-repo" ":!$S/scripts/adopt_inspection.py"; then
  echo "legacy path left in the living tree" >&2; exit 1
fi
# (2) The exact new reference, with its exact count.
test "$(grep -c -F '([design](../../.agents/artifacts/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md))' docs/standards/agent-helpers.md)" = 1
# (3) The old target is tracked, so the adoption moves it to the new path.
git ls-files --error-unmatch -- \
  .claude/specs/2026-09-24-issue-176-lifecycle-guard-extraction-design.md > /dev/null
# (4) Exactly one line, in exactly one file, since START.
test "$(git diff --numstat "$START" | awk '{print $1"/"$2" "$3}')" = "1/1 docs/standards/agent-helpers.md"
echo "A2 gate ok"
EOF
echo "START=$START GATE=$GATE"
```

Shell variables do not survive between separate tool calls. The gate script carries
`START` itself, and Step 1 prints the gate's path. Later steps write that printed path in
place of `<GATE>`.

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash <GATE>`
Expected: exit 1. Check (1) lists `docs/standards/agent-helpers.md:16` and nothing else.

- [ ] **Step 3: Make the edit**

Apply the one edit exactly. Change nothing else on the line.

- [ ] **Step 4: Verify**

Run: `bash <GATE>`
Expected: `A2 gate ok`, exit 0.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > <GATE>.log 2>&1; echo "exit $?"; tail -n 3 <GATE>.log`
Expected: `exit 0` and a final `OK` line, which may be `OK (skipped=N)`.

- [ ] **Step 5: Commit** (signed, with no closing keyword)

The trailer is the Global Constraints' line. The controller dispatches this task on that
model, so the line is also the true author.

```bash
git add docs/standards/agent-helpers.md
git commit -F - <<'EOF'
docs: re-point the lifecycle-guard design link to its adopted path

The adoption for https://github.com/fagenorn/nix-config/issues/149 moves
.claude/specs under .agents/. A sync with main brought one more living
reference to the old tree. Re-point it to the classifier's destination
path (spec D4, D10).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA
EOF
bash <GATE>; rm -f <GATE> <GATE>.log
```

Expected: one signed commit, and the gate prints `A2 gate ok` again at `HEAD`.
