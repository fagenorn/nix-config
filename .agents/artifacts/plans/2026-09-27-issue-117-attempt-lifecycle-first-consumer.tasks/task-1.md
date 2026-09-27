# Task 1: Correct the record's shipped-engine inventory and close-before-merge seam

**Files:**
- Modify: `.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md` (below: SPEC)
- Verify only, must stay byte-identical: `CLAUDE.md`

**Interfaces:**
- Consumes: SPEC at the task base, with ledger rows D1–D18 and the nine-row acceptance cross-check, plus the `CLAUDE.md` pointer paragraph that links to SPEC.
- Produces: SPEC with the five replacements below applied. It feeds the final two-axis review; no later task consumes it.

**Invariants:**
- Each replacement is applied exactly once, and every old string is absent afterwards.
- Reversing the five replacements in memory reproduces `git show HEAD:SPEC` byte for byte, so no other byte changes.
- Ledger row IDs read exactly D1…D18 in order, and the acceptance cross-check keeps nine rows.
- `CLAUDE.md` has no diff, contains exactly one `](SPEC)` link, and SPEC is tracked.
- `git status` shows only SPEC modified. No code, test, skill, declaration or generated file changes.

Run every command from the worktree root. Keep logs and scratch files outside the worktree.

- [ ] **Step 1: Confirm the live facts the new text states (must PASS at base)**

These probes pin every fact the replacements add, per D17 and D18. They cover:
- the `host-route` answers;
- control's `direct` route: one issue, no declaration read, no claims;
- handed-off, dead-owner and suspended attempts over a closed tracker;
- the CLI refusal of late v2 reports, plus the positive control and the internal reason.

On any failure, stop and report which probe failed: the code has moved, and the replacement text is no longer true.

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
import json
import runpy
import sys
import unittest

sys.path.insert(0, "home/common/agent-skills")
sys.path.insert(0, "home/common/agent-skills/tests")
import test_workflow_state as lifecycle
from tests._delivery_model_fixtures import custody, issue_with_attempt


class LiveFacts(lifecycle.LifecycleHarness, unittest.TestCase):
    def closed_sweep(self, issue, worktree, **fields):
        return self.control(
            now="2026-08-13T20:05:00Z", issues=[issue],
            tracker=[self.tracker_fact(issue, state="closed")],
            worktrees=[self.worktree_fact(issue, recorded={
                "path": str(worktree), "state": "matching_issue_branch"})],
            max_parallel=100, **fields)

    def test_unexpired_handoff_resumes_over_closed_tracker(self):
        self.init_run()
        worktree = self.root / "wt-a"
        self.spawn(issue=14, worktree=worktree)
        handoff = self.write_handoff(14)
        self.progress(turn_count=118, context_tokens=20000, handoff_path=handoff)
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][-1]["state"], "handed_off")
        response = self.closed_sweep(14, worktree)
        self.assertIn("resume", [action["kind"] for action in response["actions"]])
        self.assertEqual(
            self.read_state()["issues"]["14"]["attempts"][-1]["state"], "active")

    def test_dead_owner_resumes_over_closed_tracker(self):
        self.init_run()
        worktree = self.root / "wt-d"
        self.spawn(issue=18, worktree=worktree)
        response = self.closed_sweep(18, worktree, owners=[self.owner_fact(
            event_id="18-exit", issue=18, attempt=1, launch=1)])
        self.assertIn("resume", [action["kind"] for action in response["actions"]])
        attempt = self.read_state()["issues"]["18"]["attempts"][-1]
        self.assertEqual((attempt["state"], len(attempt["launches"])), ("active", 2))

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

    def test_direct_route_is_one_issue_reads_no_declaration_and_records_no_claims(self):
        self.init_run()
        (self.home / ".agents/share/host-declaration.json").unlink()
        fields = dict(now=lifecycle.DEFAULT_NOW, issues=[19],
                      tracker=[self.tracker_fact(19)],
                      worktrees=[self.worktree_fact(19, candidate={
                          "path": str(self.root / "wt-e"), "state": "absent"})],
                      host_route="direct")
        before = self.state_path.read_bytes()
        refused = self.control_raw(max_parallel=2, ok=False, **fields)
        self.assertIn("the direct host route controls exactly one issue at max_parallel 1",
                      refused.stderr)
        self.assertEqual(self.state_path.read_bytes(), before)
        response = self.control(max_parallel=1, **fields)
        self.assertIn("spawn", [action["kind"] for action in response["actions"]])
        admission = self.read_state()["admission"]
        self.assertEqual((admission["route"], admission["claims"], admission["releases"]),
                         ("direct", [], 0))

    @staticmethod
    def v2_reports(issue, custody_ref, digest):
        historical = {"issue": issue, "state": "failed", "pr_url": None, "merge_sha": None,
                      "issue_closed": False, "discussion_items": [], "detail_state": "none",
                      "report_path": None, "notes": "late"}
        summary = {"interface_version": 2, "issue": issue, "state": "terminal_failed",
                   "custody": custody_ref, "historical_owner_result": historical,
                   "delivery_contract_digest": digest, "delivery_observations": [],
                   "authority_observations": [], "reevaluation_evidence": [],
                   "detail_state": "none", "report_path": None, "notes": "late"}
        checkpoint = {"interface_version": 2, "issue": issue, "custody": custody_ref,
                      "contract_digest": digest, "delivery_observations": [],
                      "authority_observations": [], "reevaluation_evidence": [],
                      "requested_scope": None, "detail_state": "none",
                      "report_path": None, "notes": ""}
        return (("checkpoint-delivery", "--checkpoint-file", checkpoint,
                 "checkpoint transition refused"),
                ("finish", "--summary-file", summary, "delivery finish refused"))

    def send(self, verb, flag, value, *, ok):
        path = self.root / f"report-{verb}.json"
        path.write_text(json.dumps(value), encoding="utf-8")
        return self.run_cli(verb, "--repo-root", self.root, "--run-id", self.run_id,
                            "--now", "2026-08-13T20:30:00Z", flag, path, ok=ok)

    def test_the_same_v2_reports_are_accepted_under_current_custody(self):
        self.init_run()
        self.spawn(issue=20, worktree=self.root / "wt-f")
        digest = self.read_state()["issues"]["20"]["delivery"]["contract_digest"]
        current = {"kind": "implementation", "attempt": 1, "launch": 1, "action_id": "20:1:1"}
        for verb, flag, value, _ in self.v2_reports(20, current, digest):
            with self.subTest(verb=verb):
                self.send(verb, flag, value, ok=True)

    def test_v2_reports_after_a_synthetic_stop_are_refused_without_a_write(self):
        self.init_run()
        worktree = str(self.root / "wt-c")
        self.spawn(issue=16, worktree=worktree, budget_minutes=10)
        for index in range(3):
            self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                         now=f"2026-08-13T20:0{2 * index + 1}:00Z")
            self.resume(issue=16, worktree=worktree,
                        now=f"2026-08-13T20:0{2 * index + 2}:00Z")
        self.suspend(issue=16, attempt=1, blocked_on="usage_limit",
                     now="2026-08-13T20:08:00Z")
        issue = self.read_state()["issues"]["16"]
        attempt = issue["attempts"][-1]
        self.assertEqual((attempt["state"], attempt["result_source"]), ("stopped", "stalled"))
        launch = len(attempt["launches"])
        stopped = {"kind": "implementation", "attempt": 1, "launch": launch,
                   "action_id": f"16:1:{launch}"}
        for verb, flag, value, message in self.v2_reports(
                16, stopped, issue["delivery"]["contract_digest"]):
            with self.subTest(verb=verb):
                before = self.state_path.read_bytes()
                completed = self.send(verb, flag, value, ok=False)
                self.assertEqual(completed.returncode, 2, completed.stderr)
                self.assertEqual(completed.stderr, f"workflow-state: {message}\n")
                self.assertEqual(self.state_path.read_bytes(), before)

    def test_the_refusal_reason_is_that_custody_is_not_current(self):
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

Expected: `Ran 7 tests … OK`, then `live facts confirmed`, exit 0, and `git status --porcelain` still empty.

- [ ] **Step 2: Save the record check and watch it fail**

Run `mktemp "${TMPDIR:-/tmp}/issue117-record-check-XXXXXX.py"` once. Write this program verbatim to the path it prints. Shell variables do not survive between tool calls, so use that literal path as `CHECK` in Steps 2, 4 and 6:

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
     "A suspended attempt is withheld from resume without a write; unexpired handed-off and dead-owner "
     "resumes, remainders and a live owner's merge ignore closure (#125 gap)."),
    ("Legacy finish replaces a synthetic `expiry`/`stalled` result in place, losing that event (#125 gap).",
     "Legacy finish replaces a synthetic `expiry`/`stalled` result in place, losing that event; a v2 "
     "checkpoint or summary fails with `checkpoint transition refused` or `delivery finish refused`, "
     "since its custody is no longer current, and writes nothing (#125 gaps)."),
    ("#125 extends the shipped attempt-lane hold to remainders and live-custody merges.",
     "#125 extends the shipped suspended-attempt hold to unexpired handed-off and dead-owner resumes, "
     "remainders and live-custody merges."),
    ("Close the tracker\n"
     "   before merge under remainder and live custody (D15).\n",
     "Close the tracker\n"
     "   before merge under remainder, live custody, an unexpired handed-off resume and a dead-owner\n"
     "   resume (D15, D18).\n"),
)

text = Path(SPEC).read_text(encoding="utf-8")
for old, new in REPLACEMENTS:
    assert text.count(old) + text.count(new) == 1, f"contract mismatch: {old[:48]!r}"
ids = re.findall(r"^\| (D\d+) \|", text, flags=re.M)
assert ids == [f"D{n}" for n in range(1, 19)], ids
criteria = text.split("| Criterion | Covered by |\n|---|---|\n", 1)[1].split("\n\n", 1)[0]
assert len(criteria.splitlines()) == 9, criteria
claude = Path("CLAUDE.md").read_text(encoding="utf-8")
assert claude.count(f"]({SPEC})") == 1
subprocess.run(["git", "ls-files", "--error-unmatch", "--", SPEC], check=True,
               stdout=subprocess.DEVNULL)
assert subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "CLAUDE.md"]).returncode == 0
for old, new in REPLACEMENTS:
    assert old not in text, f"stale record text remains: {old[:48]!r}"
    assert text.count(new) == 1, f"replacement missing: {new[:48]!r}"
base = subprocess.run(["git", "show", f"HEAD:{SPEC}"], check=True,
                      capture_output=True).stdout.decode("utf-8")
reconstructed = text
for old, new in REPLACEMENTS:
    reconstructed = reconstructed.replace(new, old)
assert reconstructed == base, "bytes outside the five replacements changed"
print("record check passed")
```

Run: `python3 CHECK`
Expected: FAIL, exit 1, with `AssertionError: stale record text remains: '`host-route` returns the typed supported/unsuppo'`. A `contract mismatch`, ledger, criteria or `CLAUDE.md` failure means the base is not what this task expects. Stop and report it.

- [ ] **Step 3: Apply the five replacements to SPEC**

Replace each old string in `REPLACEMENTS` with its new string, exactly once, and change nothing else. The replacements fall in these places:
1. `### Host admission and authorization continuity`: the two lines starting "`host-route` returns" become three lines. This states D10's mapping precisely: `host-route` refuses `direct`.
2. Scenario table, row "Tracker close before merge", third cell: add the handed-off and dead-owner resume gaps (per D17).
3. Scenario table, row "Late owner after synthetic stop", third cell: add the CLI refusal of late v2 reports (the D5/D16 inventory).
4. Ledger row D15, final clause of its Choice cell: correct its gap clause (per D17).
5. `## Test seams`, item 3, final sentence: extend the close-before-merge clause to both resume lanes (per D18).

Do not rewrap other lines, touch other rows or cells, add a ledger row or edit `CLAUDE.md`.

- [ ] **Step 4: Verify GREEN and scope**

Run: `python3 CHECK && git diff --check -- .agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md && test "$(git status --porcelain=v1)" = " M .agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md"`
Expected: `record check passed`, exit 0. The reverse oracle shows that only the five replacements changed.

- [ ] **Step 5: Run the repository gates once at the final bytes**

Run `just agent-workflow-tests`, then `just build`, from the worktree root. Write each one's combined output to a log beside your task report, never inside the worktree, and record the process's real exit code. Expected: both exit 0. On failure, report the failing lines only. These gates prove repository integrity, not core delivery.

- [ ] **Step 6: Commit**

```bash
set -euo pipefail
# Use your session's attribution trailer instead only if it names a different agent.
trailer='Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>'
spec=.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md
git add -- "$spec"
test "$(git diff --cached --name-only)" = "$spec"
git commit -m "docs(issue-117): correct the record's shipped-engine inventory" \
  -m "Name the handed-off, dead-owner and late v2 report gaps, state that host-route refuses direct, and extend the close-before-merge seam (per D17, D18)." \
  -m "$trailer"
git status --porcelain=v1
rm -f CHECK
```

Expected: a signed commit, an empty `git status` and no leftover check file. Report the Step-2 RED message, the Step-4 result, both gate exits with their log paths, and the commit SHA.
