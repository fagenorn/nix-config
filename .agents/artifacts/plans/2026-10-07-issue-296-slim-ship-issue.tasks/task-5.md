# Task 5: Cut SKILL.md to the hub

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/ship-issue/SKILL.md`
- Modify: `instruction-load.json` (`tighten` only), `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 4's tree. Every route and phase file exists, `SKILL.md` has its `## Files beside this one` index and the two stubs, and no reference file names a sibling.
- Produces: `SKILL.md` with these `##` headings in this order: `Project bindings (resolve first)`, `Files beside this one`, `The flow`, `Standing authorization`, `Launch guard` (with `### Local commits`), `Doc-grounded escalations`, `gh hygiene`, `Phase 0 — Pre-flight` through `Phase 8 — Cleanup` (titles unchanged), `Notes`, `Delivery loop`, `Remainder mode`.

**Invariants:**
- Frontmatter `description` is exactly `Delivers a finished feature-branch worktree: integration-branch sync, PR, review, CI, merge, issue close or hold, cleanup. Phase 7 of from-issue. Use for "ship #X", "land it".` (per D10).
- The resolve paragraph is byte-identical to the one at `baac2897` (#295 D10). So are the `### Local commits` paragraph (its `Lifecycle worker:` line and two `launch-scope` sentences), the four marker lines with their call lines, every fenced command (`check-launch`, `capability_gap: agent_dispatch`, Phase 1's fetch, Phase 4's push and `gh pr create`, Phase 5's `BASE_SHA`/`HEAD_SHA`, the bare-fenced required watch, the merge, the worktree-removal block), and every item left in `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE]`.
- Kept anchors (per D4): the Phase-0 probe (first step, before any write, testing the capability rather than the host, the gap line, the standalone message), Phase 5's range selection (its four conditions, the `review-range` argv, the closed routes `delta`/`empty`/`full`, `review-range unavailable`), Phase 8 step 1's close and hold sequence in order, `## gh hygiene`'s `unset GITHUB_TOKEN && gh ...` sentence, and the flow diagram's optional-subject merge line.
- Phase 6's docs-only skip sentence stays verbatim, rationale parenthetical included (finding 1, per D12).
- The interim-child-results paragraph stays in Phase 5 with every clause of today's text in order (re-engage by recorded identity, may end the turn, no text-only reply, no suspension, no replacement or stop, a worker stays registered, the undeliverable case through from-issue's **Writing workers** route, only the final hand-back counts), shortened (per D8).
- `workflow-state build-delivery` appears only in the resolve paragraph and the `## Delivery loop` stub (per D5).
- Targets: ≤ 22,000 bytes and ≤ 280 reflowed body lines. The hard line is 300 (AC2).

- [ ] **Step 1: Delete the pins on the text this task rewrites**

In `tests/test_workflow_skill_contracts.py` (per D8, spec item 3):
- `InterimChildResultContractsTest.OWNERS` becomes `(FROM_ISSUE, SDD)`. In `test_the_paragraph_copies_stay_identical` the loop becomes `for path in (SDD,):`. In `test_each_copy_sits_in_its_owner_section` delete the `SHIP_ISSUE` row.
- `test_durable_review_detail_precedes_every_removable_cleanup`: the loop becomes `for text in (self.sdd, self.ship_handoff):`.

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k InterimChildResult -k durable_review_detail` (timeout 300 s). Expected: OK.

- [ ] **Step 2: Cut, section by section**

Apply the spec's content-class table. Named cuts:
1. Frontmatter: the D10 description. Opening paragraph: one sentence.
2. `## Project bindings`: keep the resolve paragraph. Merge the three capability paragraphs that follow into one: select `bindings.workflow.review.code` and route retained `capabilities.review.code` (`blocked` stops, authored `unsupported` takes its documented route, only `available` dereferences `bindings.commands[review_id].argv`), and an unsupported tracker takes the tracker-free route, where sync, verify, consolidate and merge still apply. Keep **Invocation paths** and the plan-member paragraph with every check. Cut the second "validate … before decoding" restatement, if any.
3. `## Standing authorization`: one paragraph per idea (grant scope, the guard-covered chain, review-adjudicating hosts with the `HUMAN-GATE.md` pointer). The checks that "still bind" stay listed.
4. `## Launch guard`:
   - Keep the rule sentence, with the unsupported-tracker push still guarded, and the `check-launch` fence. Keep the `action_id` sentence through "never derived from `attempt`".
   - Replace the output contract and the degrade-gracefully paragraph with: "Proceed only on `current: true`. Anything else — `current: false`, a non-zero exit, a missing helper, or output that does not parse into the exact four keys `action_id`, `current`, `current_action_id` and `reason` — refuses the write; this check never degrades gracefully." The four-key list stays verbatim (Standards review R1).
   - Keep the guarded list, the refusal stop with its summary fields and its `unpublished` exception, and the ledger-free skip without its rationale clause. Cut the opening sentence about why a superseded attempt can push.
5. `## Doc-grounded escalations`: one sentence. `## gh hygiene`: keep both sentences.
6. Phase 0: keep the probe (Invariants) without the sentences restating what the probe does not prove. Keep the four checks, "Any failure: pause, ground, surface", and the effective-acceptance paragraph.
7. Phase 1: "Read `SYNC.md` first." Then the fetch fence and the merge-and-commit paragraph. Delete "The load-bearing rules, in brief" and its three bullets (their home is `SYNC.md`).
8. Phase 2: keep the three numbered steps. Step 3 keeps exactly these mapping lines (per D9): `record` exit 3 `tree_changed` is a failing verification; `check` exit 2 means run anyway and leave the pass unrecorded; `record` exit 2 leaves the pass unrecorded. Keep the baseline-in-a-scratch-worktree rule in one sentence.
9. Phase 4: keep both fences byte for byte. Reduce the guard-form paragraph to: "The lifecycle guard accepts only this form; render the body in place, with no `"`, `$`, backtick or backslash, never through a file, heredoc or substitution." Keep the `## Acceptance` paragraph, the title rule, the default-branch auto-close paragraph and the full-URL rule, each in one or two sentences.
10. Phase 5: keep the range-selection block and the routing. Keep the four sites in order: merge-delta (with its pointer to `POST-SELECTION-SYNC.md`), conformance, the three-rung correctness list with its fallback site, and the scoped re-review with its stop-and-return sentence. Keep the routing-error paragraph. Shorten the interim paragraph (Invariants).
11. Phase 6: keep the docs-only sentence verbatim, the tip check with its one clause "two attempts of one issue share this checkout, so live local HEAD is not evidence", the divergence stop, the bare-fenced watch, and the exit-code paragraph. Cut "Divergence here is also evidence of a superseded launch, which is why …".
12. Phase 7: replace the subject sentence with: "Pass `--subject` only when the rendered subject is non-empty and contains none of `"`, `$`, backtick, backslash, NUL, LF or CR; otherwise omit it." Keep the `--no-ff` ban, the fence, the verify-don't-trust-the-exit-code rule and the `git ls-remote` rule.
13. Phase 8: keep the review-package paragraph, step 1 whole, the step-2 fence, and the bucket rule cut to its rule: remove only `$BUCKET` — the shape `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/` — captured from the worktree's own git directory before removal, never `primary/` and never another worktree's. The `<primary-checkout>/.superpowers/sdd/wt-<worktree-name>/` literal stays verbatim: `test_ship_issue_prunes_the_removed_worktrees_sdd_bucket` asserts `WORKTREE_BUCKET_LITERAL` (Standards review R2). Keep step 3, step 4 and the closing summary paragraph, minus the "two roles" explanation already covered by the `## Delivery loop` stub.
14. `## Notes`: three one-line bullets.

- [ ] **Step 3: Models**

- `skill-lint-debt.json`: delete `L2 …/ship-issue/SKILL.md` (per D14).
- Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 4: Verify**

Run the focused suite, the lint and the gate. Expected: OK, exit 0, `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import subprocess
from pathlib import Path
from agent_tools import skill_lint
path = "home/common/agent-skills/skills/ship-issue/SKILL.md"
text = Path(path).read_text(encoding="utf-8")
fields, body = skill_lint.parse_frontmatter(text)
lines = skill_lint.reflowed_lines(body)
print("reflowed body lines:", lines, "bytes:", len(text.encode()))
assert lines <= 300, lines
if lines > 280 or len(text.encode()) > 22000:
    print("over target (name it in the commit body)")
assert fields["description"] == ('Delivers a finished feature-branch worktree: integration-branch sync, PR, '
    'review, CI, merge, issue close or hold, cleanup. Phase 7 of from-issue. Use for "ship #X", "land it".')
base = subprocess.run(["git", "show", f"baac2897f15daab46a4f25ec625b40d384d3573c:{path}"],
                      capture_output=True, text=True, check=True).stdout
resolve = next(l for l in base.splitlines() if l.startswith("Run `resolve-project resolve"))
assert resolve in text.splitlines()
assert text.count("Agent(") == 4
for n in range(9):
    assert sum(l.startswith(f"## Phase {n} — ") for l in text.splitlines()) == 1, n
EOF
```

Expected: exit 0. At Task 4's head it fails on `lines <= 300` (about 670).

- [ ] **Step 5: Commit**

Commit as `refactor(ship-issue): cut SKILL.md to the hub (#296)`.
