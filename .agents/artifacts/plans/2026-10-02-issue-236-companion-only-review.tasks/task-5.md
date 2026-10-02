# Task 5 — Callers point at the skill instead of restating it (per D20)

- Lane: full.
- Files: `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/ship-issue/REVIEW.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
- Must not touch: `home/common/agent-skills/instruction-load.json` (the user rejected raising any ceiling), `codex-collaboration/SKILL.md`.
- Consumes from Tasks 1–2: `RETIRED_EXEC_REVIEW_TOKENS`, `CODEX_COMPANION_INVOCATION_ANCHORS`, `CODEX_COMPANION_VALIDATION_ANCHORS`, `CAPACITY_SCOPE_ANCHORS`, `CONFIGURED_REVIEW_UNSUPPORTED_ROUTE`, `CONFIGURED_REVIEW_AVAILABLE_FALLBACK`, `test_configured_review_paragraph_copies_stay_identical`.

Why: both callers reach Codex only by invoking `codex-collaboration`'s `diff-review` (`sdd/final-review.md` rung 2: "that skill solely owns the isolated Codex transport launch"; `ship-issue/SKILL.md` rung 2), so the copied invocation and validation text is duplication that only costs instruction bytes.

- [ ] **Step 1: Write the failing test.** In `assert_configured_code_review_pair`, replace the `support_text` `assert_ordered` call and the `bare ["codex"] included` assertion with:

```python
    case.assert_ordered(
        support_text,
        "For configured code review,",
        "`codex-collaboration`'s `diff-review`",
        "binding shape error",
        "no Codex call",
        "`blocked` stops", *CAPACITY_SCOPE_ANCHORS,
        CONFIGURED_REVIEW_UNSUPPORTED_ROUTE, CONFIGURED_REVIEW_AVAILABLE_FALLBACK,
    )
    # The skill owns the shape, invocation and validation; a caller restating
    # them is the duplication D20 removed.
    for restated in ("basename of `argv[0]`", *CODEX_COMPANION_INVOCATION_ANCHORS[1:],
                     *CODEX_COMPANION_VALIDATION_ANCHORS[:-1]):
        case.assertNotIn(restated, support_text)
```

Keep the `RETIRED_EXEC_REVIEW_TOKENS` loop, the pre-D15 negative pin and the owner-text loop as they are. Leave `test_configured_review_paragraph_copies_stay_identical` unchanged: it still keeps the two copies identical.

- [ ] **Step 2: Run and watch it fail.** `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k configured_review 2>&1 | tail -5` — expected: the two `*_configured_review_pair_is_complete` tests fail on a restated anchor.

- [ ] **Step 3: Replace the paragraph.** In both files, replace the whole line that starts `For configured code review,` with exactly this one line (identical in both files):

```markdown
For configured code review, the correctness axis reaches Codex only through `codex-collaboration`'s `diff-review`, which alone owns the review binding shape, its invocation and its validation; a binding shape error it reports stops this review with no Codex call, no retry and no native fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection. Authored `unsupported` takes the caller's native correctness route directly and makes no Codex call. On the `available` route, a completed non-capacity runtime/output failure uses the existing single native fallback and records why.
```

Before writing, confirm every sentence is true of the live skill text (`codex-collaboration/SKILL.md` at HEAD); if one is not, correct this paragraph to match the skill, not the reverse.

- [ ] **Step 4: Verify the task.**

```bash
PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3
just agent-workflow-tests 2>&1 | tail -3
git diff --quiet origin/main -- home/common/agent-skills/instruction-load.json && echo ceilings-unchanged
for f in home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md; do
  test "$(wc -c < "$f")" -le "$(git show origin/main:"$f" | wc -c)" && echo "$f not larger than main"
done
```

Expected: both test runs end `OK` (including `test_the_live_tree_breaches_no_ceiling`), `ceilings-unchanged`, and both files report not larger than main. These gates can fail at the start commit: the ceiling test fails there.

- [ ] **Step 5: Commit** with message `refactor(review): callers point at codex-collaboration diff-review instead of restating it (#236)` and the session trailers.

- [ ] **Step 6: Re-run the final gate** — task-4 Step 7 (build + installed-skill check) and task-4 Step 8 (live companion demo), unchanged.
