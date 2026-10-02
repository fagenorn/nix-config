# Task 2: Shared caller paragraph, companion-only

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (the one line starting `For configured code review,`)
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (the same line)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes, from Task 1 (module constants in the test file): `CODEX_COMPANION_INVOCATION_ANCHORS = ("no positional argument", "--model gpt-6-astra --effort xhigh", "--cwd <absolute-worktree> --json")`, `CODEX_COMPANION_VALIDATION_ANCHORS` (seven anchors from `"exactly one JSON object"` to `"last captured agent message"`), and `RETIRED_EXEC_REVIEW_TOKENS`. Also the existing `CAPACITY_SCOPE_ANCHORS`, `CONFIGURED_REVIEW_UNSUPPORTED_ROUTE`, `CONFIGURED_REVIEW_AVAILABLE_FALLBACK` and `test_configured_review_paragraph_copies_stay_identical`.
- Produces: nothing for other tasks.

**Invariants:**
- Both files carry the byte-identical paragraph below; `test_configured_review_paragraph_copies_stay_identical` stays green (per D15).
- The paragraph's closing sentences, from `` `blocked` stops. `` to the end, are unchanged, so the callers' stop paths are unchanged (per D8, D15).
- Neither file contains any of `RETIRED_EXEC_REVIEW_TOKENS` (per D17).
- The owner-file check (`bindings.workflow.review.code` → `capabilities.review.code` → `bindings.commands[review_id].argv` in each caller's `SKILL.md`) is unchanged.

- [ ] **Step 1: Write the failing test.** Replace the body of `assert_configured_code_review_pair` from its `case.assert_ordered(\n        support_text,` call through the `case.assertNotIn("exec --sandbox", companion)` line with:

```python
    case.assert_ordered(
        support_text,
        "review binding shape",
        "basename of `argv[0]`",
        "`codex-companion task --reviewer diff-review`", "optional `--fresh`",
        *CODEX_COMPANION_INVOCATION_ANCHORS,
        *CODEX_COMPANION_VALIDATION_ANCHORS,
        "binding shape error",
        "`codex-companion task [--fresh] --reviewer <op>`",
        "no Codex call",
        "`blocked` stops", *CAPACITY_SCOPE_ANCHORS,
        CONFIGURED_REVIEW_UNSUPPORTED_ROUTE, CONFIGURED_REVIEW_AVAILABLE_FALLBACK,
    )
    case.assertIn('bare `["codex"]` included', support_text)
    for retired in RETIRED_EXEC_REVIEW_TOKENS:
        case.assertNotIn(retired, support_text)
```

Leave the owner `assert_ordered`, the `Authored unsupported or a completed non-capacity` guard and the final loop as they are.

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k configured_review 2>&1 | tail -5`
Expected: FAIL in `test_sdd_configured_review_pair_is_complete` and `test_ship_issue_configured_review_pair_is_complete` — the expected-form anchor is missing and `exec --sandbox` is present.

- [ ] **Step 3: Rewrite the paragraph.** In both files, replace the whole `For configured code review,` line with this single line, verbatim:

```markdown
For configured code review, copy the selected command entry, unset only its declared environment names, and check that its authored argv has the one review binding shape exactly as `codex-collaboration`'s direct configured review does: the basename of `argv[0]` is `codex-companion` (the shape `codex-companion task --reviewer diff-review`), followed by `task --reviewer diff-review` with an optional `--fresh` and no other token. Send the packet on stdin with no positional argument and execute its base argv followed exactly by `--model gpt-6-astra --effort xhigh --cwd <absolute-worktree> --json`; require exit status 0 and stdout that parses as exactly one JSON object whose `status` is `0`, whose `touchedFiles` is empty, whose `runtime.model` is `gpt-6-astra` and `runtime.reasoningEffort` is `xhigh`, and whose `rawOutput` is a non-empty string, the last captured agent message, before operation headings identify Codex. Any other argv, bare `["codex"]` included, is a binding shape error naming the expected form `codex-companion task [--fresh] --reviewer <op>`: the operation stops with no Codex call, no retry and no native fallback. `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection. Authored `unsupported` takes the caller's native correctness route directly and makes no Codex call. On the `available` route, a completed non-capacity runtime/output failure uses the existing single native fallback and records why.
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -3`
Expected: `OK`.
Run: `if grep -nE 'exec --sandbox|output-last-message|JSONL|exec shape' home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md; then exit 1; fi`
Expected: no output, exit 0. At the start commit both files match, so this gate can fail.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/skills/sdd/final-review.md home/common/agent-skills/skills/ship-issue/REVIEW.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(review): state only the companion binding shape in the shared configured-review paragraph (#236)"
```
