# Task 8: Delete the host-admission prep note

**Files:**
- Delete: `.claude/specs/2026-09-20-host-admission-prep.md`

**Interfaces:**
- Consumes: nothing. The note's conclusions already live in the design spec (D2, D3, D7, D9 and its honesty boundary), which is what makes the deletion mechanical (per D15).
- Produces: nothing.

**Invariants:**
- Only that one file changes; no other file references it except the #150 design spec's historical mention, which stays.

- [ ] **Step 1: Confirm the precondition**

Run: `test -f .claude/specs/2026-09-20-host-admission-prep.md && grep -rl 'host-admission-prep' --exclude-dir=.git . | sort`
Expected: the file exists, and the only listed references are `./.claude/specs/2026-09-24-issue-150-host-capacity-admission-design.md` and this plan package. Any other referrer is a blocker to report, not to edit.

- [ ] **Step 2: Delete**

Run: `git rm .claude/specs/2026-09-20-host-admission-prep.md`

- [ ] **Step 3: Verify**

Run: `if test -e .claude/specs/2026-09-20-host-admission-prep.md; then echo "prep note still present"; exit 1; fi; git diff --cached --name-status -- .claude/specs`
Expected: exactly `D	.claude/specs/2026-09-20-host-admission-prep.md` (at the base commit the file is present, so the first check fails).

- [ ] **Step 4: Commit**

```bash
git commit -m "docs(spec): retire the host-admission prep note recorded in #150's design"
```
