# Task 1: Finalize decision delivery-authority wording

**Files:**
- Modify: `.claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md`

**Interfaces:**
- Consumes: the accepted D1–D8 architecture record, its nine-criterion acceptance cross-check, and the existing tracked `CLAUDE.md` discovery pointer.
- Produces: one precise out-of-scope sentence that distinguishes architecture-decision authority from separately scoped delivery authority under current host enforcement.
- Review handoff: the controller packages the complete fixed-base range and counts the decision spec as product; incoming synced history remains visible provenance.

**Invariants:**
- The replacement occurs exactly once, and the old sentence is absent.
- No other byte in the accepted spec changes; D1–D8, scenario outcomes, test seams, downstream ownership and non-activation claims remain exact.
- `CLAUDE.md` remains byte-identical at SHA-256 `cf0ab131efb93fae481b9953cb9d50713fac7805023456303e7b5dabb1d26d87`, contains one #117 pointer, and its relative target remains tracked.
- The new sentence grants no publication, merge, tracker or cleanup authority. It does not invalidate enclosing scoped authorization and does not override current host enforcement or an actual denial.
- Runtime/core/adapter/guard/provider code, generated projections, tracker state and host state remain untouched.

- [ ] **Step 1: Run the exact postcondition assertion and observe RED**

```bash
python3 - <<'PY'
from pathlib import Path

text = Path(".claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md").read_text(encoding="utf-8")
old = (
    "Publication, merge, tracker\n"
    "closure and remote cleanup are not authorized by this decision task."
)
new = (
    "This record grants no publication, merge, tracker or cleanup authority; those actions require the\n"
    "enclosing delivery’s scoped authorization and remain subject to current host enforcement."
)
assert text.count(old) == 1, "accepted old authority sentence missing or duplicated"
assert text.count(new) == 0, "replacement already present at task base"
assert old not in text, "old delivery-authority sentence remains"
PY
```

Expected: exit nonzero with `AssertionError: old delivery-authority sentence remains`. Any failure in the two preceding shape assertions is a contract mismatch and stops the task before editing.

- [ ] **Step 2: Replace only the scoped sentence**

In `## Out of scope`, replace exactly:

```text
Publication, merge, tracker
closure and remote cleanup are not authorized by this decision task.
```

with exactly:

```text
This record grants no publication, merge, tracker or cleanup authority; those actions require the
enclosing delivery’s scoped authorization and remain subject to current host enforcement.
```

Preserve every other byte in the spec. Do not edit `CLAUDE.md`; its discovery pointer is already delivered.

- [ ] **Step 3: Prove GREEN, byte reconstruction, pointer validity and scoped formatting**

```bash
set -euo pipefail
python3 - <<'PY'
from hashlib import sha256
from pathlib import Path
import subprocess

spec = Path(".claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md")
text = spec.read_text(encoding="utf-8")
old = (
    "Publication, merge, tracker\n"
    "closure and remote cleanup are not authorized by this decision task."
)
new = (
    "This record grants no publication, merge, tracker or cleanup authority; those actions require the\n"
    "enclosing delivery’s scoped authorization and remain subject to current host enforcement."
)
assert old not in text
assert text.count(new) == 1
reconstructed = text.replace(new, old)
assert sha256(reconstructed.encode("utf-8")).hexdigest() == "66401c772aec1a3011380503e3693ebd5796a8c83d822c7c1bfea85d4e10e22c"

claude = Path("CLAUDE.md")
assert sha256(claude.read_bytes()).hexdigest() == "cf0ab131efb93fae481b9953cb9d50713fac7805023456303e7b5dabb1d26d87"
link = ".claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md"
assert claude.read_text(encoding="utf-8").count(link) == 1
subprocess.run(["git", "ls-files", "--error-unmatch", "--", link], check=True, stdout=subprocess.DEVNULL)
PY
git diff --check -- .claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md
```

Expected: exit 0. The reconstruction hash proves all accepted architecture, scenarios, criterion coverage and test seams remain byte-identical outside the one replacement.

- [ ] **Step 4: Run final-state verification once and retain durable evidence**

Use this SDD workspace:

```text
/Users/anis/tmp/nix-config/.superpowers/sdd/wt-worktree-issue-117-attempt-lifecycle-core-first-consumer/2026-09-21-issue-117-attempt-lifecycle-first-consumer
```

Run `just agent-workflow-tests` and `just build` from the worktree, each once at the final spec bytes. Capture combined output in `task-1-agent-workflow-tests.log` and `task-1-build.log`, and write each actual process exit to its matching `.exit` file without inferring it from an outer tool result. Require both exits to be `0`.

For each command, write a compact `-receipt.json` beside its log with the exact argv, cwd, immutable delivery base, tested spec SHA-256, exit code, log byte count and log SHA-256. After commit, add the final commit and committed spec SHA-256; they must equal the tested bytes. These commands prove repository integrity only, not downstream core/runtime conformance.

- [ ] **Step 5: Verify exact scope and commit**

```bash
set -euo pipefail
python3 - <<'PY'
import subprocess

expected = b" M .claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md\0"
actual = subprocess.run(
    ["git", "status", "--porcelain=v1", "-z"],
    check=True,
    capture_output=True,
).stdout
assert actual == expected, repr(actual)
PY
git diff --check -- .claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md
```

Expected: exit 0; the index and untracked set are empty and only the accepted decision spec differs.

```bash
set -euo pipefail
spec=.claude/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md
git add -- "$spec"
test -z "$(git diff --name-only)"
test "$(git diff --cached --name-only)" = "$spec"
git commit -S -m "docs(issue-117): clarify decision delivery authority" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

After committing, prove the worktree is clean and update both verification receipts with the signed final commit and matching committed spec hash. The task report must name the exact RED failure, GREEN reconstruction hash, full-suite/build exits, changed file, commit and any concerns.
