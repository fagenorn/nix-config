# Task 1: Correct the record's shipped-engine inventory

**Files:**
- Modify: `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md` (below: SPEC)
- Verify only, must stay byte-identical: `CLAUDE.md`

**Interfaces:**
- Consumes: SPEC at the task base, with ledger rows D1–D17 and the nine-row acceptance cross-check, plus the `CLAUDE.md` pointer paragraph that links to SPEC.
- Produces: SPEC with the four replacements below applied. It feeds the final two-axis review; no later task consumes it.

**Invariants:**
- Each replacement is applied exactly once, and every old string is absent afterwards.
- Reversing the four replacements in memory reproduces `git show HEAD:SPEC` byte for byte, so no other byte changes.
- Ledger row IDs read exactly D1…D17 in order, and the acceptance cross-check keeps nine rows.
- `CLAUDE.md` has no diff, contains exactly one `](SPEC)` link, and SPEC is tracked.
- `git status` shows only SPEC modified. No code, test, skill, declaration or generated file changes.

Run every command from the worktree root. Keep logs and scratch files outside the worktree.

- [ ] **Step 1: Confirm the live facts the new text states (must PASS at base)**

These probes pin the three behaviors per D17. On any failure, stop and report which probe failed. The code has moved, so the replacement text is no longer true.

```bash
set -euo pipefail
probe_home=$(mktemp -d "${TMPDIR:-/tmp}/issue117-home-XXXXXX")
trap 'rm -rf "$probe_home"' EXIT HUP INT TERM
mkdir -p "$probe_home/.agents/share"
cp home/common/agent-skills/host-declaration.json "$probe_home/.agents/share/"
state=home/common/agent-skills/scripts/workflow-state.py
HOME="$probe_home" PYTHONPATH=python python3 "$state" host-route --route claude-code \
  | python3 -c 'import json, sys; v = json.load(sys.stdin); assert (v["support"], v["agent_slots"]) == ("supported", 7), v'
HOME="$probe_home" PYTHONPATH=python python3 "$state" host-route --route codex \
  | python3 -c 'import json, sys; v = json.load(sys.stdin); assert (v["support"], v["reason_code"]) == ("unsupported", "declared_unsupported"), v'
if direct_err=$(HOME="$probe_home" PYTHONPATH=python python3 "$state" host-route --route direct 2>&1 >/dev/null); then
  echo "host-route accepted direct"; exit 1
fi
case "$direct_err" in *"invalid route: 'direct'"*) ;; *) echo "unexpected: $direct_err"; exit 1 ;; esac
PYTHONPATH=python python3 - <<'PY'
import runpy
import sys
import unittest

sys.path.insert(0, "home/common/agent-skills")
sys.path.insert(0, "home/common/agent-skills/tests")
import test_workflow_state as lifecycle
from tests._delivery_model_fixtures import custody, issue_with_attempt


class LiveFacts(lifecycle.LifecycleHarness, unittest.TestCase):
    def test_unexpired_handoff_resumes_over_closed_tracker(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff)
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[-1]["state"], "handed_off")
        response = self.control(
            now="2026-08-13T20:05:00Z", issues=[14],
            tracker=[self.tracker_fact(14, state="closed")],
            worktrees=[self.worktree_fact(14, recorded={
                "path": str(worktree), "state": "matching_issue_branch"})],
            max_parallel=100)
        self.assertIn("resume", [action["kind"] for action in response["actions"]])
        attempts = self.read_state()["issues"]["14"]["attempts"]
        self.assertEqual(attempts[-1]["state"], "active")

    def test_suspended_attempt_is_held_over_closed_tracker(self):
        self.init_run()
        worktree = str(self.root / "wt-b")
        self.spawn(issue=15, worktree=worktree, budget_minutes=10)
        self.expire(issue=15, worktree=worktree, now="2026-08-13T20:10:00Z")
        before = self.state_path.read_bytes()
        response = self.control(
            now="2026-08-13T21:00:00Z", issues=[15],
            tracker=[self.tracker_fact(15, state="closed")],
            worktrees=[self.worktree_fact(15, recorded={
                "path": worktree, "state": "matching_issue_branch"})])
        self.assertNotIn("resume", [action["kind"] for action in response["actions"]])
        self.assertEqual(self.state_path.read_bytes(), before)

    def test_v2_report_after_a_stop_is_not_current(self):
        runtime = runpy.run_path(
            "home/common/agent-skills/scripts/workflow_delivery.py")["DeliveryRuntime"](
                notes_max_characters=10_000)
        runtime.record_for_custody(issue_with_attempt({}, state="active"), custody())
        for state in ("stopped", "failed"):
            with self.subTest(state=state):
                with self.assertRaisesRegex(ValueError, "^custody is not current$"):
                    runtime.record_for_custody(
                        issue_with_attempt({}, state=state), custody())


result = unittest.main(argv=["issue117-live-facts"], exit=False, verbosity=1).result
sys.exit(0 if result.wasSuccessful() else 1)
PY
echo "live facts confirmed"
```

Expected: `Ran 3 tests … OK`, then `live facts confirmed`, exit 0, and `git status --porcelain` still empty.

- [ ] **Step 2: Save the record check and watch it fail**

Run `mktemp "${TMPDIR:-/tmp}/issue117-record-check-XXXXXX.py"` once. Write this program verbatim to the path it prints, and use that literal path as `CHECK` in Steps 2, 4 and 6, since shell variables do not survive between tool calls:

```python
import re
import subprocess
import sys
from pathlib import Path

SPEC = ".agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md"
REPLACEMENTS = (
    ("`host-route` returns the typed supported/unsupported answer: `claude-code` is supported, `codex` is\n"
     "declared unsupported, and the single-owner `direct` route records no claims. Nothing schedules CPU,\n",
     "`host-route` returns the typed supported/unsupported answer: `claude-code` is supported and `codex`\n"
     "is declared unsupported. It refuses `direct`, control's reserved single-owner route (one issue at\n"
     "`max_parallel` 1), which reads no declaration and records no claims. Nothing schedules CPU,\n"),
    ("A suspended attempt is withheld from resume without a write; remainders and a live owner's merge "
     "ignore closure (#125 gap).",
     "A suspended attempt is withheld from resume without a write; an unexpired handed-off attempt's "
     "resume, remainders and a live owner's merge ignore closure (#125 gap)."),
    ("Legacy finish replaces a synthetic `expiry`/`stalled` result in place, losing that event (#125 gap).",
     "Legacy finish replaces a synthetic `expiry`/`stalled` result in place, losing that event; a v2 "
     "summary or checkpoint is refused as `custody is not current` and the ledger retains none of its "
     "evidence (#125 gaps)."),
    ("#125 extends the shipped attempt-lane hold to remainders and live-custody merges.",
     "#125 extends the shipped suspended-attempt hold to unexpired handed-off resumes, remainders and "
     "live-custody merges."),
)

text = Path(SPEC).read_text(encoding="utf-8")
for old, new in REPLACEMENTS:
    assert text.count(old) + text.count(new) == 1, f"contract mismatch: {old[:48]!r}"
ids = re.findall(r"^\| (D\d+) \|", text, flags=re.M)
assert ids == [f"D{n}" for n in range(1, 18)], ids
criteria = text.split("| Criterion | Covered by |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
assert len(criteria.splitlines()) == 9, criteria
claude = Path("CLAUDE.md").read_text(encoding="utf-8")
assert claude.count(f"]({SPEC})") == 1
subprocess.run(["git", "ls-files", "--error-unmatch", "--", SPEC], check=True,
               stdout=subprocess.DEVNULL)
assert subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "CLAUDE.md"]).returncode == 0
for old, new in REPLACEMENTS:
    assert old not in text, f"stale shipped-inventory text remains: {old[:48]!r}"
    assert text.count(new) == 1, f"replacement missing: {new[:48]!r}"
base = subprocess.run(["git", "show", f"HEAD:{SPEC}"], check=True,
                      capture_output=True).stdout.decode("utf-8")
reconstructed = text
for old, new in REPLACEMENTS:
    reconstructed = reconstructed.replace(new, old)
assert reconstructed == base, "bytes outside the four replacements changed"
print("record check passed")
```

Run: `python3 CHECK`
Expected: FAIL, exit 1, with `AssertionError: stale shipped-inventory text remains: '`host-route` returns the typed supported/unsuppo'`. A `contract mismatch`, ledger, criteria or `CLAUDE.md` failure means the base is not what this task expects. Stop and report it.

- [ ] **Step 3: Apply the four replacements to SPEC**

Replace each old string in `REPLACEMENTS` with its new string, exactly once, and change nothing else. The replacements fall in these places:
1. `### Host admission and authorization continuity`: the two lines starting "`host-route` returns" become three lines (D10's mapping stated precisely: `host-route` refuses `direct`).
2. Scenario table, row "Tracker close before merge", third cell: the handed-off resume gap is added.
3. Scenario table, row "Late owner after synthetic stop", third cell: the v2 refusal is added (D5/D16 inventory).
4. Ledger row D15, final clause of its Choice cell: its gap clause is corrected (per D17).

Do not rewrap other lines, touch other rows, add a ledger row or edit `CLAUDE.md`.

- [ ] **Step 4: Verify GREEN and scope**

Run: `python3 CHECK && git diff --check -- .agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md && test "$(git status --porcelain=v1)" = " M .agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md"`
Expected: `record check passed`, exit 0. The reverse oracle shows that only the four replacements changed.

- [ ] **Step 5: Run the repository gates once at the final bytes**

Run `just agent-workflow-tests` and then `just build` from the worktree root. Write each one's combined output to a log beside your task report, never inside the worktree, and record the process's real exit code. Expected: both exit 0. On failure, report the failing lines only. These gates prove repository integrity, not core delivery.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
# Use your session's attribution trailer instead only if it names a different agent.
trailer='Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>'
spec=.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md
git add -- "$spec"
test "$(git diff --cached --name-only)" = "$spec"
git commit -m "docs(issue-117): correct the record's shipped-engine inventory" \
  -m "Name the handed-off resume and late v2 report gaps and state that host-route refuses direct (per D17)." \
  -m "$trailer"
git status --porcelain=v1
rm -f CHECK
```

Expected: a signed commit, an empty `git status` and no leftover check file. Report the Step-2 RED message, the Step-4 result, both gate exits with log paths, and the commit SHA.
