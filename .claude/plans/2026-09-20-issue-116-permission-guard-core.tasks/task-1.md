# Task 1: Align living guard authorization prose

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the accepted D1–D9 decision at `.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md` and the current `authorizedOwners` roster in `home/common/claude-code/default.nix`.
- Produces: one living owner clause that points to that roster and one relative link that states the guard/core decision's current gaps and downstream admission boundary.
- Review handoff: the controller packages the complete issue branch so final review covers the already committed decision record and this prose change together.

**Invariants:**
- `CLAUDE.md` contains no claim that guarded repository origins are restricted to `fagenorn`.
- The replacement clause refers to the guard's `authorizedOwners` set in `home/common/claude-code/default.nix` as the authoritative roster, without enumerating a second owner list.
- The decision link occurs exactly once and resolves to the accepted tracked spec.
- The added sentence preserves the required-check floor, calls the current protection exceptions and missing permanent-head deletion check gaps, and withholds future core admission pending downstream enforcement and conformance work.
- The surrounding exact command grammar, current legacy exceptions, generated import, guard implementation, tests and historical records remain unchanged.

- [ ] **Step 1: Run the scoped assertion and observe the stale living truth**

```bash
python3 - <<'PY'
from pathlib import Path
text = Path("CLAUDE.md").read_text(encoding="utf-8")
stale = "origin slug to be `fagenorn`-owned"
roster = "origin owner to belong to the guard's `authorizedOwners` set in `home/common/claude-code/default.nix` (the authoritative roster)"
link = "[guard/core decision](.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md)"
assert text.count(stale) == 0, "stale fagenorn-only owner clause remains"
assert text.count(roster) == 1, "authoritative roster clause missing or duplicated"
assert text.count(link) == 1, "decision link missing or duplicated"
PY
```

Expected: FAIL with `stale fagenorn-only owner clause remains`. Before editing, separately confirm the base has exactly one stale clause and zero roster/link clauses; any other shape is a plan contract mismatch.

- [ ] **Step 2: Apply the exact living-prose correction**

In the existing long permission-guard bullet, replace only:

```text
the three repository-bound verbs additionally require the origin slug to be `fagenorn`-owned
```

with:

```text
the three repository-bound verbs additionally require the origin owner to belong to the guard's `authorizedOwners` set in `home/common/claude-code/default.nix` (the authoritative roster)
```

Immediately after that bullet, add exactly:

```markdown
  - The [guard/core decision](.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md) preserves the required-check floor for both merge arms and records the current protection exceptions and missing permanent-head deletion check as gaps. Core grants cannot override the final guard, host or provider verdict; future core admission waits for the named enforcement and conformance work.
```

Do not reflow or otherwise rewrite the surrounding guard description. This implements D4/D9 and accurately preserves D1/D5–D8.

- [ ] **Step 3: Prove the scoped prose and link contract**

```bash
python3 - <<'PY'
from pathlib import Path
text = Path("CLAUDE.md").read_text(encoding="utf-8")
stale = "origin slug to be `fagenorn`-owned"
roster = "origin owner to belong to the guard's `authorizedOwners` set in `home/common/claude-code/default.nix` (the authoritative roster)"
link = "[guard/core decision](.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md)"
target = Path(".claude/specs/2026-09-20-issue-116-permission-guard-core-design.md")
assert stale not in text
assert text.count(roster) == 1
assert text.count(link) == 1
assert target.is_file()
assert "protection exceptions and missing permanent-head deletion check as gaps" in text
assert "future core admission waits for the named enforcement and conformance work" in text
PY
git diff --check -- CLAUDE.md
```

Expected: both commands exit 0. `git diff --name-only -- CLAUDE.md` prints only `CLAUDE.md`; `rg -n -i 'fagenorn-owned|authorizedOwners|guard/core decision' CLAUDE.md` shows the authoritative-roster clause and decision link, with no stale clause.

- [ ] **Step 4: Run declared final-state verification**

Run: `just agent-workflow-tests`

Expected: exit 0 with the complete managed workflow suite passing.

Run: `just build`

Expected: exit 0 with the nix-darwin configuration built. These results do not certify future core enforcement, provider support or the D8 downstream fixture corpus.

- [ ] **Step 5: Verify scope and commit**

```bash
python3 - <<'PY'
import subprocess

status = subprocess.run(
    ["git", "status", "--porcelain=v1", "-z"],
    check=True,
    capture_output=True,
).stdout
assert status == b" M CLAUDE.md\0", repr(status)
PY
spec=.claude/specs/2026-09-20-issue-116-permission-guard-core-design.md
git ls-files --error-unmatch -- "$spec" >/dev/null
test "$(shasum -a 256 "$spec" | awk '{print $1}')" = \
  8f9b341897b59d85a3f6f5883db56b4df384f35c29947af942c4592e2e4171a8
git diff --check -- CLAUDE.md
```

Expected: exit 0. The NUL-delimited whole-worktree inventory proves the index and untracked set are empty and `CLAUDE.md` is the only changed path. The accepted decision spec is tracked and still hashes to `8f9b341897b59d85a3f6f5883db56b4df384f35c29947af942c4592e2e4171a8`.

```bash
git add CLAUDE.md
test -z "$(git diff --name-only)"
test "$(git diff --cached --name-only)" = "CLAUDE.md"
git commit -S -m "docs: align guard authorization truth" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
