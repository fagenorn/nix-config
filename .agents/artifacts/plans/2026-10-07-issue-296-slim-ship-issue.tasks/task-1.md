# Task 1: Split the lifecycle routes into DELIVERY-LOOP.md and REMAINDER.md

**Files** (under `home/common/agent-skills/`):
- Create: `skills/ship-issue/DELIVERY-LOOP.md`, `skills/ship-issue/REMAINDER.md`
- Modify: `skills/ship-issue/SKILL.md` (the two sections, Phase 7's and Phase 8's lifecycle notes, and a new `## Files beside this one` index)
- Modify: `instruction-load.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the merged tree at the plan's base. The ship-issue documents are byte-identical to `baac2897`.
- Produces:
  - `DELIVERY-LOOP.md`, headed `# Delivery loop (lifecycle identity)`, with sections `## Lifecycle calls and the checkpoint` and `## Loop steps` (numbered 1–7, the numbers unchanged).
  - `REMAINDER.md`, headed `# Remainder mode`, with sections `## Entry and start points`, `## Close or hold from the PR body` and `## Exits and finish`.
  - In `SKILL.md`: a `## Files beside this one` section directly before `## The flow`, and the `## Delivery loop` and `## Remainder mode` headings kept as stubs (per D4, D5). Tasks 2 and 5 edit the index.
  - Test constants `SHIP_ISSUE_DELIVERY_LOOP` and `SHIP_ISSUE_REMAINDER`, and the keys of the same names in `SHIP_ISSUE_MACHINE_TEXT`.

**Invariants:**
- Loop steps 1–7 keep their order, their closed sets (stage ids, observation kinds, `state: suspended`, `blocked_on: human_gate`, `delivery_stalled`, `delivery_complete`, `terminal_failed`) and every argv. So do the remainder's start points, its four acceptance values and its release-then-`finish` order.
- The checkpoint fence and the `finish` fence move byte for byte, as `text` fences.
- Neither new file spells `build-delivery` or names a sibling basename (per D5, D6). `CI-MERGE.md`'s `## Post-selection sync` becomes "the post-selection sync route", and `REVIEW.md`'s fix pushes become "Phase 5's fix pushes". The heading names `## Delivery loop`, `## Launch guard`, `### Local commits` and `## Remainder mode` stay, because they name `SKILL.md` sections.
- Byte targets: `DELIVERY-LOOP.md` 4,500, `REMAINDER.md` 2,600.

- [ ] **Step 1: Re-point the machine-read tests (they fail until Step 3)**

In `tests/test_workflow_skill_contracts.py`, add these beside `SHIP_ISSUE_HUMAN_GATE`:

```python
SHIP_ISSUE_DELIVERY_LOOP = SHIP_ISSUE.parent / "DELIVERY-LOOP.md"
SHIP_ISSUE_REMAINDER = SHIP_ISSUE.parent / "REMAINDER.md"
```

Replace `LIFECYCLE_DOCS` (spec Test-pin deletion item 2):

```python
LIFECYCLE_DOCS = (*sorted((REPO_ROOT / "home/common/agent-skills/skills/from-issue").glob("*.md")),
                  *sorted(SHIP_ISSUE.parent.glob("*.md")), ORCHESTRATE)
```

In `SHIP_ISSUE_MACHINE_TEXT[SHIP_ISSUE]`, delete these items: `"--kind selected-output"`, `"--kind current-selection"`, `"checkpoint-delivery"`, `"finish --summary-file -"`, the `"workflow-state release-worker … --event returned"` item, `"--kind scope"`, `` "`test_ref`" ``, `` "`tracker_held`" ``, `` "`comment_url`" ``, `` "`record_path`" `` and `` "`github:issue:<num>:held`" ``. Add two keys after it (per D7, D16):

```python
    SHIP_ISSUE_DELIVERY_LOOP: (
        "--kind selected-output", "checkpoint-delivery", "--kind scope", "`test_ref`",
        "`tracker_held`", "`comment_url`", "`record_path`", "`github:issue:<num>:held`",
        "--boundary ship-checkpoint", "ship-checkpoint/v2", "--worker-id <worker_id>",
        "~/.agents/bin/workflow-state current-launch --repo-root <ledger_repo_root> "
        "--run-id <run-id> --action-id <custody action_id>",
        "validate-report --boundary ship-summary",
    ),
    SHIP_ISSUE_REMAINDER: (
        "--kind current-selection", "finish --summary-file -",
        "workflow-state release-worker --repo-root <ledger_repo_root> --run-id <run-id> "
        "--worker-id <worker_id> --event returned",
        "gh pr view <pr-num> --repo <resolved-repository> --json body",
        "Held for verification: <PR URL>",
    ),
```

In `test_lifecycle_calls_are_single_stdin_commands_on_interface_two`, change the `STDIN_CLAUSE` loop to `for path in (ORCHESTRATE,):` (spec item 3).

In `test_delivery_interface_two_is_one_atomic_production_caller_contract`, drop `SHIP_ISSUE`, `SHIP_ISSUE_REVIEW` and `SHIP_ISSUE_HUMAN_GATE` from the corpus tuple, and drop `"current-launch"`, `"bind the actual invocation"` and `"ship-checkpoint/v2"` from the phrase loop. The other assertions stay; they hold on the from-issue and orchestrate text (per D16).

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ship_issue_documents_carry -k single_stdin_commands` (timeout 300 s)
Expected: ERROR or FAIL, a `FileNotFoundError` for `DELIVERY-LOOP.md` / `REMAINDER.md`.

- [ ] **Step 3: Move and cut**

1. `DELIVERY-LOOP.md` gets `SKILL.md`'s `## Delivery loop` from its second paragraph ("Every lifecycle call is one command …") to the end of step 7. Then:
   - Fold in Phase 7's lifecycle notes (from "Under lifecycle identity the merge is the `merge_pr` cycle" to the end of that paragraph, and the `delete_remote_branch` sentences after the `git ls-remote` line) and Phase 8's stage-order paragraph ("The steps below are the ledger-free order. …"). They go into step 4 as one stage list in contract order: `merge_pr` → `pr_merged`, `close_tracker` → `tracker_closed` or `tracker_held`, `delete_remote_branch` → `remote_branch_absent`, `remove_worktree` → `worktree_absent`, `delete_local_branch` → `local_branch_absent`.
   - Cut the restated "Validate each reply before decoding", the clause "the reducer weighs a rejection only against a proposed scope", and the Phase-2 list of pre-selection effects, which becomes one sentence: everything before the selection gate runs under the native guard and `check-launch`, with no checkpoint.
   - Replace the sentence "Every scope, selection, observation … never compose one." with "Every scope, selection, observation and authority observation comes from the builder named in `SKILL.md`'s `## Delivery loop`, fed the installed contract and the kind's facts in a quoted heredoc; never compose an id or digest."
   - Keep the clause "so a relaunched owner re-derives the identical selection" in step 3, and one clause in step 7 saying why the last cycle is not checkpointed. Those are the short clauses the spec's Rationale row keeps.
2. `REMAINDER.md` gets `## Remainder mode`'s three paragraphs and its `finish` fence, under the headings in Interfaces. Rewrite "from-issue's `## Remainder owner prompt`" as "from-issue's remainder owner prompt". Keep "`## Delivery loop`" and "`## Launch guard`" as heading references.
3. `SKILL.md`:
   - Replace the body of `## Delivery loop` with this stub paragraph, verbatim (the fence is not part of it):

     ```text
     Under lifecycle identity — a validated `ship-handoff/v2`, or the `delivery_remainder` of `## Remainder mode` — every delivery effect from the pre-merge selection gate on runs through this loop. Ledger-free, Phases 7–8 run as written and no ledger call is made. The builder is `workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input -`. The lifecycle-call rule, the checkpoint call, the `ship-checkpoint/v2` keys and loop steps 1–7 are in `DELIVERY-LOOP.md`.
     ```

   - Replace the body of `## Remainder mode` with: "Entered with a validated `delivery_remainder` object instead of a handoff. It skips Phases 0–5 and runs `## Delivery loop` from the ledger's ready stage, as `REMAINDER.md` says."
   - In Phase 7 and Phase 8, leave one line where each moved note stood: "Under lifecycle identity this effect is a `## Delivery loop` cycle."
   - Add `## Files beside this one` before `## The flow`, one bullet per file:
     - "`SYNC.md` — Phase 1: divergence, foreign commits, scope creep, the allowlist, the escalation format."
     - "`CONSOLIDATE.md` — Phase 3: the bar, the rubric, destinations and the procedure."
     - "`REVIEW.md` — Phase 5: Codex failure semantics, templates, the delta brief, the range record, severity mapping, the five-step fix flow, durable Minor/Discussion detail."
     - "`CI-MERGE.md` — Phases 6–7: the CI escalation, failing checks, advisory overflow, merge quirks, and the post-selection sync."
     - "`HUMAN-GATE.md` — the operator gates, entered only when `## Standing authorization` finds no grant."
     - "`DELIVERY-LOOP.md` — lifecycle identity: read it for every `ship-handoff/v2` and every remainder."
     - "`REMAINDER.md` — a `delivery_remainder` owner's entry, start points, close or hold, and `finish`."

- [ ] **Step 4: Models**

- `instruction-load.json` (per D3):
  - `ship-owner`: add `ship-issue/DELIVERY-LOOP.md` to `hot` after `ship-issue/SKILL.md`, and add `ship-issue/REMAINDER.md` to `conditional`.
  - `orchestrated-issue-owner` and `implementation-owner`: add `ship-issue/DELIVERY-LOOP.md` to `conditional` after `ship-issue/SKILL.md`. Add unread `"ship-issue/REMAINDER.md": "from-issue's dispatch-gap fallback covers only the review-bearing ship launch; a delivery_remainder goes to a fresh ship owner"`.
- Run `just agent-instruction-load tighten` (timeout 300 s). Then run the gate. `ship-owner`'s conditional ceiling on both hosts is expected to be breached, because the remainder text moved out of hot `SKILL.md`. Set each breached conditional ceiling to its measure and name it in the commit body (root Global Constraints).

- [ ] **Step 5: Verify**

Run the focused suite, the lint and the gate (root Global Constraints). Expected: OK, exit 0, `check: pass`.
Run:

```bash
set -euo pipefail
python3 - <<'EOF'
from pathlib import Path
S = Path("home/common/agent-skills/skills/ship-issue")
for name, cap in {"DELIVERY-LOOP.md": 4500, "REMAINDER.md": 2600}.items():
    size = len((S / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
skill = (S / "SKILL.md").read_text(encoding="utf-8")
for heading in ("## Delivery loop\n", "## Remainder mode\n", "## Files beside this one\n"):
    assert skill.count(heading) == 1, heading
assert "ship-checkpoint/v2` has exactly" not in skill
for name in ("DELIVERY-LOOP.md", "REMAINDER.md"):
    text = (S / name).read_text(encoding="utf-8")
    assert "build-delivery" not in text, name
EOF
```

Expected: exit 0, with any `over target` line named in the commit body. At the base this fails, because `DELIVERY-LOOP.md` is absent.

- [ ] **Step 6: Commit**

Commit as `refactor(ship-issue): split the delivery loop and remainder mode into route files (#296)`. The body carries the `raise:` lines from Step 4.
