# Task 1: Re-point the eight living references to the adopted paths

This is the hand-authored half of the #72 path migration, per D3 and D4. It is the
branch's only planned product change. It lands before any tool output, because
`adopt-project plan` fingerprints `CLAUDE.md` into its `plan_id`. The lane is `full`,
because the lane rules exclude migration work from `low-risk`.

**Files** (`S=home/common/agent-skills`):
- Modify: `CLAUDE.md` (1 line), `docs/standards/agent-helpers.md` (5 lines),
  `S/README.md` (1 line), `S/skills/ship-issue/HUMAN-GATE.md` (1 line)
- Test: none committed. The gate below is an uncommitted script under `$TMPDIR`
  (spec "Test seams": no test is added).

**Interfaces:**
- Consumes: the classifier's closed rows in `S/scripts/adopt_inspection.py`
  (`CLASSIFICATION_RULES` with `destination_for(group, target, relative) = target +
  relative[len(group):]`). `.claude/specs` goes to `.agents/artifacts/specs`, and
  `.out-of-scope` goes to `.agents/knowledge/rejections`. The engine is read, never
  changed.
- Produces: the three new targets below. Owner step B3 checks them against the live
  plan's `git-mv` targets, and B6 checks that they resolve at the adoption commit.
  - `.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md`
  - `.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md`
  - `.agents/knowledge/rejections/ungated-agent-merges.md`

**Invariants:**
- Exactly eight lines change, with numstat `1/1`, `5/5`, `1/1` and `1/1`. Nothing else
  on those lines changes, and no other file changes.
- At this commit the new targets do not exist yet. The links resolve only after the
  adoption commit, which is expected (D4). Never create, copy or move a target file
  here. The engine does that.
- Every old target is tracked today, so the adoption moves it to the new path.
- The README row names the binding and not nix-config's path, because the row
  describes every project's convention (D4). It has the same form as the
  neighbouring **Prose hints** row.
- No commit message carries a closing keyword for #149 (D6).

## Exact edits

Each edit replaces the old string with the new one, and nothing else changes.

1. `CLAUDE.md`, line 63:
   ```text
   old: [guard/core decision](.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md)
   new: [guard/core decision](.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md)
   ```
2. `docs/standards/agent-helpers.md`, lines 6, 8, 10, 12 and 14 (all five):
   ```text
   old: ([design](../../.claude/specs/2026-09-24-agent-tools-package-design.md))
   new: ([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))
   ```
3. `S/README.md`, line 14. Only the middle cell changes, and the third cell stays
   byte-identical:
   ```text
   old: | **Rejection KB** | `.out-of-scope/*.md` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
   new: | **Rejection KB** | paths in `bindings.paths.rejections` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
   ```
4. `S/skills/ship-issue/HUMAN-GATE.md`, line 104:
   ```text
   old:   `.out-of-scope/ungated-agent-merges.md`.
   new:   `.agents/knowledge/rejections/ungated-agent-merges.md`.
   ```

- [ ] **Step 1: Record the start and write the gate**

```bash
cd /Users/anis/tmp/nix-config/.worktrees/worktree-issue-149-orchestrated
START=$(git rev-parse HEAD); echo "$START"
GATE=$(mktemp "${TMPDIR:-/tmp}/a1-gate-XXXXXX.sh")
cat > "$GATE" <<'EOF'
set -euo pipefail
S=home/common/agent-skills
# (1) No legacy artifact path in the living tree. The exclusions are the three trees
#     the adoption moves, the contract (the apply amends it), the test fixtures, the
#     eval fixture repository and the engine classifier.
if git grep -n -E '\.claude/(specs|plans)|\.out-of-scope' -- . \
    ':!.claude/specs' ':!.claude/plans' ':!.out-of-scope' ':!.agents/project.json' \
    ":!$S/tests" ":!$S/evals/fixture-repo" ":!$S/scripts/adopt_inspection.py"; then
  echo "legacy path left in the living tree" >&2; exit 1
fi
# (2) The exact new references, with exact counts.
test "$(grep -c -F '[guard/core decision](.agents/artifacts/specs/2026-09-20-issue-116-permission-guard-core-design.md)' CLAUDE.md)" = 1
test "$(grep -c -F '([design](../../.agents/artifacts/specs/2026-09-24-agent-tools-package-design.md))' docs/standards/agent-helpers.md)" = 5
test "$(grep -c -F '| **Rejection KB** | paths in `bindings.paths.rejections` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |' $S/README.md)" = 1
test "$(grep -c -F '`.agents/knowledge/rejections/ungated-agent-merges.md`.' $S/skills/ship-issue/HUMAN-GATE.md)" = 1
# (3) Every old target is tracked, so the adoption moves it to the new path.
git ls-files --error-unmatch -- \
  .claude/specs/2026-09-20-issue-116-permission-guard-core-design.md \
  .claude/specs/2026-09-24-agent-tools-package-design.md \
  .out-of-scope/ungated-agent-merges.md > /dev/null
# (4) Exactly the eight lines, in exactly the four files, since START.
got=$(git diff --numstat "$START" -- CLAUDE.md docs/standards/agent-helpers.md \
  "$S/README.md" "$S/skills/ship-issue/HUMAN-GATE.md" | awk '{print $1"/"$2" "$3}' | sort)
want=$(printf '%s\n' "1/1 CLAUDE.md" "5/5 docs/standards/agent-helpers.md" \
  "1/1 $S/README.md" "1/1 $S/skills/ship-issue/HUMAN-GATE.md" | sort)
test "$got" = "$want"
echo "A1 gate ok"
EOF
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `START="$START" bash "$GATE"`
Expected: exit 1. Check (1) lists the four files at their eight legacy references.

- [ ] **Step 3: Make the four edits**

Apply the four edits exactly. In `agent-helpers.md`, replace all five occurrences of
the same string. Change nothing else on any line.

- [ ] **Step 4: Verify**

Run: `START="$START" bash "$GATE"`
Expected: `A1 gate ok`, exit 0.

Run: `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests > "$GATE.log" 2>&1; echo "exit $?"; tail -n 3 "$GATE.log"`
Expected: `exit 0` and a final `OK` line, which may be `OK (skipped=N)`.

- [ ] **Step 5: Commit** (signed, with no closing keyword)

```bash
git add CLAUDE.md docs/standards/agent-helpers.md \
  home/common/agent-skills/README.md home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md
git commit -F - <<'EOF'
docs: re-point living references to the adopted artifact paths

The adoption for #149 moves .claude/specs and .out-of-scope under .agents/.
Re-point the eight living references to the classifier's destination paths,
and name the rejection binding in the adapter contract (spec D4).

Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XJQu22Bg2fayzv7KNKKbaA
EOF
START="$START" bash "$GATE"; rm -f "$GATE" "$GATE.log"
```

Expected: one signed commit, and the gate prints `A1 gate ok` again at `HEAD`.
