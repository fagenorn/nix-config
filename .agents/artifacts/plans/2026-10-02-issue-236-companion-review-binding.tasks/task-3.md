# Task 3: Shared caller configured-review paragraph

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (the one line that starts `For configured code review,`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (the same line)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: from Task 2, the module-level tuples `CODEX_COMPANION_INVOCATION_ANCHORS` (`"no positional argument"`, `"--model gpt-6-astra --effort xhigh"`, `"--cwd <absolute-worktree> --json"`) and `CODEX_COMPANION_VALIDATION_ANCHORS` (`"exactly one JSON object"`, `` "`status` is `0`" ``, `` "`touchedFiles` is empty" ``, `` "`runtime.model` is `gpt-6-astra`" ``, `` "`runtime.reasoningEffort` is `xhigh`" ``, `` "`rawOutput` is a non-empty string" ``, `"last captured agent message"`, `"No JSONL or last-message candidate"`). Both are already defined in the test module.
- Produces: nothing new for later tasks.

**Invariants:**
- The paragraph is one line, and it stays byte-identical in both files (`test_configured_review_paragraph_copies_stay_identical`, per D9).
- Every existing `assert_configured_code_review_pair` anchor keeps its order. The companion and shape-error anchors sit between `"last-message"` and `` "`blocked` stops" ``.
- The last three sentences (the `unsupported` route and the `available` fallback) are unchanged. `CONFIGURED_REVIEW_UNSUPPORTED_ROUTE` and `CONFIGURED_REVIEW_AVAILABLE_FALLBACK` still match.
- No other line of either file changes (per D8, D9).

- [ ] **Step 1: Write the failing test.** In `assert_configured_code_review_pair`, replace the `support_text` `assert_ordered` call with:

```python
    case.assert_ordered(
        support_text,
        "review binding shape",
        "exec", "--sandbox read-only", "--model gpt-6-astra",
        'model_reasoning_effort="xhigh"', "--json", "--output-last-message",
        "--ephemeral", "selected model", "selected reasoning effort",
        "terminal agent-message", "last-message",
        "`codex-companion task --reviewer diff-review`", "optional `--fresh`",
        *CODEX_COMPANION_INVOCATION_ANCHORS,
        *CODEX_COMPANION_VALIDATION_ANCHORS,
        "binding shape error", "no Codex call",
        "`blocked` stops", *CAPACITY_SCOPE_ANCHORS,
        CONFIGURED_REVIEW_UNSUPPORTED_ROUTE, CONFIGURED_REVIEW_AVAILABLE_FALLBACK,
    )
    # The companion tail never inherits the exec tail's stdin marker or subcommand.
    companion = support_text[support_text.index("`codex-companion task --reviewer diff-review`"):]
    case.assertNotIn("exec --sandbox", companion)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k configured_review 2>&1 | tail -5`
Expected: FAIL in `test_sdd_configured_review_pair_is_complete` and `test_ship_issue_configured_review_pair_is_complete`, with `missing anchor: 'review binding shape'`.

- [ ] **Step 3: Replace the paragraph.** In both files, replace the whole `For configured code review, …` line with this exact line, written once and pasted into both:

```text
For configured code review, copy the selected command entry, unset only its declared environment names, and classify its authored argv into one review binding shape exactly as `codex-collaboration`'s direct configured review does. For the exec shape, where the basename of `argv[0]` is `codex`, execute its base argv followed exactly by `exec --sandbox read-only --model gpt-6-astra -c model_reasoning_effort="xhigh" --json --output-last-message <absolute-last-message> --ephemeral -C <absolute-worktree> -`. Keep JSONL and last-message files outside worktrees under unconditional cleanup. Validate the selected model and selected reasoning effort, then require terminal agent-message equality with the non-empty last-message before operation headings identify Codex. For the companion shape, `codex-companion task --reviewer diff-review` with an optional `--fresh`, send the packet on stdin with no positional argument and execute its base argv followed exactly by `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`; require exit status 0 and stdout that parses as exactly one JSON object whose `status` is `0`, whose `touchedFiles` is empty, whose `runtime.model` is `gpt-6-astra` and `runtime.reasoningEffort` is `xhigh`, and whose `rawOutput` is a non-empty string, the last captured agent message, before operation headings identify Codex. No JSONL or last-message candidate is created for that shape. Any other argv is a binding shape error: the operation stops with no Codex call, no retry and no native fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection. Authored `unsupported` takes the caller's native correctness route directly and makes no Codex call. On the `available` route, a completed non-capacity runtime/output failure uses the existing single native fallback and records why.
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK`, including `test_configured_review_paragraph_copies_stay_identical`, both `..._configured_review_pair_is_complete` tests, and the correctness-ladder tests.
Run: `git diff --numstat -- home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md`
Expected: exactly `1	1` for each file.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(review): state both binding shapes in the shared configured-review paragraph (#236)"
```
