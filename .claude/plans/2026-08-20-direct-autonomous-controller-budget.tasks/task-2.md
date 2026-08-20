# Task 2: Seal the post-terminal certification

**Files:**
- Modify: `.claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`

**Interfaces:**
- Consumes: Task 1's merged pending report and its containing full commit; the representative-run merge commit; canonical terminal ledger bytes for `direct-75-000002`; the unchanged pre-rollover sealed prefix; the fresh controller's closed prefix ending at terminal relay/task completion; the complete structured role inventory; D1–D8.
- Produces: the same evidence report with no `pending`/`remaining` dispositions, exact terminal anchors and per-controller maximum records, a replayed reproduction matrix, and one D8 final verdict. Its containing final evidence commit is identified by the D7 path-scoped query from a clean checkout.

**Invariants:**
- A separate post-terminal certifier starts from `origin/main` containing the representative-run merge, creates an ordinary follow-up branch, and verifies the canonical ledger is terminal before editing. It is not either lifecycle controller.
- This task never calls `workflow-state`, `direct-owner`, SDD, ship/release commands, activation, or any command that mutates the ledger/run. It reads runtime evidence and writes only the report.
- The ledger's exact bytes, size, and SHA-256 are captured before the report edit and must be byte-identical after verification and commit. The pre-rollover prefix must still match Task 1's size/digest.
- Both required controller prefixes end at that controller's terminal relay/task-complete record. Later appended conversation bytes are excluded. Every unexpected authority-bearing session is promoted to a required controller per D2.
- For every required controller, D3 is applied independently inside its sealed prefix. The chosen row carries one timestamp plus paired integer logical/cached values and derived fresh value; the ceiling is evaluated only against logical input.
- Any observed deployment, lifecycle, ownership, counter, or ceiling failure is retained as `fail`; otherwise an unavailable required fact is `unknown`. D8 is applied mechanically and cannot be overridden by narrative.
- The historical rows are rechecked from the two Task-1 fixed paths and remain descriptive. No new trace, transcript copy, percentage, aggregation, or causal claim is introduced.
- The representative merge is embedded as a full object ID. Per D7, the final evidence commit is not embedded recursively: from the clean final checkout, the report gives and uses `git log -1 --format=%H -- .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md` as its identity query.

- [ ] **Step 1: Write and run the final-report structural test after proving the terminal precondition**

First resolve the canonical ledger path from the merged pending report's owner envelope. Read it with `jq` and require exactly one attempt for issue `75` matching run `direct-75-000002`, attempt `1`, owner `75:1`, the recorded worktree, non-null `finished_at`, non-null `result`, non-null `result_source`, and terminal attempt/outcome state. Locate each controller's terminal relay/task-complete record and prove both prefix endpoints exist. Stop without editing if either condition is absent.

Then run:

```bash
python3 - <<'PY'
from pathlib import Path
import re

path = Path(".claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md")
text = path.read_text(encoding="utf-8")
assert "`pending`" not in text
assert "remaining" not in text.lower()
match = re.search(r"(?m)^- Verdict: `(certified|not certified|unknown)`$", text)
assert match is not None
for heading in (
    "## Verdict and scope",
    "## Deployment freshness",
    "## Lifecycle trace",
    "## Controller input",
    "## Pre-rollover boundary",
    "## Historical comparison",
    "## Reproduction matrix",
):
    assert text.count(heading) == 1
PY
```

Expected: FAIL because Task 1's merged report still contains verdict `pending` and remaining terminal evidence. The terminal precondition itself must pass before this expected failure is accepted.

- [ ] **Step 2: Seal the runtime evidence and extract each controller maximum**

Record the terminal ledger's absolute path, exact full byte count, and `shasum -a 256` before editing. Extract only compact run/issue/attempt/owner/worktree/state/finished/result/result-source fields. Recompute the pre-rollover prefix digest over Task 1's exact byte count. Determine the fresh controller's prefix endpoint at its terminal relay/task-complete record, then record its absolute path, exact covered bytes, SHA-256, `session_meta.id`, and start timestamp.

For each D2-required controller prefix, run the following `jq` algorithm over exactly `head -c <covered-bytes> <absolute-log-path>`; substitute literal size/path in the report's reproduction row:

```jq
def integer: if type == "number" then floor == . else false end;
[
  .[]
  | select(.type == "event_msg" and .payload.type == "token_count")
  | . as $event
  | $event.payload.info.last_token_usage as $usage
  | select($usage != null)
  | {
      timestamp: $event.timestamp,
      logical: $usage.input_tokens,
      cached: $usage.cached_input_tokens
    }
] as $records
| if ($records | length) == 0 then error("no completed token record")
  elif any($records[]; ((.timestamp | type) != "string") or ((.logical | integer) | not))
  then error("invalid timestamp or logical input")
  else ($records | max_by([.logical, .timestamp])) as $selected
  | if (($selected.cached | integer) | not)
       or $selected.cached < 0
       or $selected.cached > $selected.logical
    then error("invalid cached input")
    else $selected + {
      fresh: ($selected.logical - $selected.cached),
      ceiling: 150000,
      within_ceiling: ($selected.logical <= 150000)
    }
    end
  end
```

Invoke it as `jq -s -c '<program>'` so the compact selected object is the only stdout. Later timestamp breaks equal-logical ties through the array ordering. A program error or absent record marks that required controller unmeasurable; do not substitute a cumulative counter, another row, or an estimate.

Rebuild the structured role inventory through the sealed endpoints. Require the pre/fresh session IDs to differ, the fresh start to follow the captured Phase-5 `delegate`, and the run/attempt/owner/worktree envelope to remain unchanged. Promote and measure any additional session that acquired/adopted the envelope or persisted issue-level phase progression. Re-run both historical maximum queries and hashes from Task 1.

- [ ] **Step 3: Finalize every section and derive the verdict**

Replace every terminal-dependent pending statement with the compact observed value or an explicit unavailable/failed result. Preserve the seven-section layout and update it as follows:

- `Verdict and scope`: full representative-run merge; exact terminal run/attempt/owner/worktree; one-trace scope; D7 final-evidence-commit query; final verdict derived only after the matrix is complete.
- `Deployment freshness`: replay all Task-1 comparisons and timestamp ordering against the same immutable merge/base and sealed session anchors.
- `Lifecycle trace`: final role inventory, both controller identities/prefix anchors, Phase-5 sealed `delegate`, distinct fresh adoption, and terminal ledger path/bytes/digest/result.
- `Controller input`: one complete row per D2-required controller using the D3 object. Keep logical, cached, and fresh separate; give each row `pass`, `fail`, or `unknown`.
- `Pre-rollover boundary`: replay the reviewed Git diff and sealed dispatch inventory; record whether only the design/plan package changed before rollover and whether the first SDD launch belonged to the fresh owner.
- `Historical comparison`: retain exact rechecked rows and say only whether each measurable issue-75 controller is at/below `150000` and descriptively lower than each historical observation, with scope/runtime/workflow limitations.
- `Reproduction matrix`: replace every `remaining` row with a literal resolved command/query, compact observed result, and `pass`, `fail`, or `unknown`. Include Git identity/content, deployment, lifecycle, controller, ownership, ledger-integrity, and report-identity rows.

Derive the single overall verdict per D8: if any matrix row is `fail`, write ``- Verdict: `not certified` ``; else if any row is `unknown`, write ``- Verdict: `unknown` ``; else write ``- Verdict: `certified` ``. Do not close issue 75 in this task; shipping/issue disposition is outside this read-only evidence writer.

- [ ] **Step 4: Commit, replay from a clean checkout, and prove ledger preservation**

Run the Step-1 Python structural contract.

Expected: PASS with no output; any `pending`, remaining marker, missing/duplicated section, or absent/ambiguous final verdict fails.

Run every reproduction-matrix command and compare its compact stdout with the recorded result and disposition.

Expected: every row matches. The D8 verdict equals the matrix; any mismatch is a report defect, not a reason to soften the row.

Run: `git diff --check -- .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`

Expected: exit 0 with no output.

Run: `bash -c 'set -euo pipefail; actual=$(mktemp); trap '\''rm -f "$actual"'\'' EXIT; { git diff --name-only HEAD --; git ls-files --others --exclude-standard; } | LC_ALL=C sort -u >"$actual"; if ! cmp -s "$actual" <(printf "%s\n" ".claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md"); then cat "$actual"; exit 1; fi'`

Expected: exit 0 with no output; any edit outside the evidence report is printed and fails.

Commit:

```bash
git add .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md
git commit -m "docs(issue-75): seal controller budget evidence" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

Create a temporary clean detached worktree at the new commit. From it, run every reproduction row, including `git log -1 --format=%H -- .claude/specs/2026-08-20-direct-autonomous-controller-budget-evidence.md`, and require the latter to equal that checkout's full HEAD. Recompute the terminal ledger byte count and SHA-256 from its absolute runtime path and require both to equal the pre-edit values and the report. Remove only the temporary verification worktree after the clean replay succeeds.

Expected: all compact outputs match; report identity equals clean-checkout HEAD; ledger size/digest are unchanged. Any failure leaves Task 2 incomplete and forbids a certification claim.
