# Task 1: Scope the capacity rule to the `available` route at its homes

Decisions: D6 (`codex-collaboration` makes no Codex call under `unsupported`),
D7 (the capacity rule is scoped by "On the `available` route" in both homes), D9
(the classification sits beside each capacity rule it scopes), D10 (the
DIFF-REVIEW pin and the paragraph-identity test). Spec §3 and §4. Work from the
worktree root. Every shell block starts with `set -euo pipefail` and these
abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests/test_workflow_skill_contracts.py
SK=home/common/agent-skills/skills; CC=home/common/claude-code/skills/codex-collaboration
```

**Files:**
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md` (the
  configured-review paragraph, line 7)
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (the same
  paragraph, line 6; nothing else in this file)
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md` (the
  selection paragraph under `## Phase entry and selection` and the capacity
  paragraph under `## Direct configured review`)
- Modify: `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`
  (the second sentence of `## Size pre-flight`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the existing module helpers `normalized(text)`,
  `ProjectPolicySurfaceTest.assert_ordered(text, *anchors)`, and the path
  constants `COLLABORATION`, `DIFF_REVIEW`, `SHIP_ISSUE_REVIEW` and `SDD_DIR`.
- Produces: the module constant `CAPACITY_SCOPE_ANCHORS` (a tuple of 5 str),
  which Tasks 2 and 3 do not use but must not rename. It also produces the
  configured-review paragraph wording that Task 2's `available` rung points to
  ("on the terms in REVIEW.md"), and that Task 3's rung points to ("on the
  configured-review terms above").

**Invariants:**
- The configured-review paragraph is byte-identical in `REVIEW.md` and
  `final-review.md`. It is one line in each file, starting at
  `For configured code review,`.
- In that paragraph, `` `blocked` stops`` comes before "On the `available`
  route", so it cannot be read as limited to that route. The sentence
  "Authored unsupported or a completed non-capacity runtime/output failure uses
  the existing single native fallback and records why." is unchanged.
- In `codex-collaboration` SKILL.md, the `unsupported` clause still comes before
  `` dereference `bindings.commands[review_id]` ``, and the ban "Do not use a
  default, a plugin bridge, or a second resolver" is kept word for word.
- DIFF-REVIEW keeps "retained `capabilities.review.code` selection runs first",
  which `test_diff_review_scopes_oversized_ranges_and_discloses_coverage` pins.
- No `agent-dispatch` marker or `Agent(` line changes in any file.

**Existing pins this task touches:**
- Updated on purpose: `assert_configured_code_review_pair`, which feeds
  `test_sdd_configured_review_pair_is_complete` and
  `test_ship_issue_configured_review_pair_is_complete`;
  `assert_codex_operation_pair`, which feeds
  `test_codex_plan_review_owner_and_support_are_complete` and
  `test_codex_diff_review_owner_and_support_are_complete`; and
  `test_review_capability_routes_before_command_lookup`.
- Must stay green with no edit:
  `test_diff_review_scopes_oversized_ranges_and_discloses_coverage`,
  `test_claude_source_phase_entries_use_one_resolved_project` (it forbids the
  text "default `" in `CC/SKILL.md`),
  `test_refusal_reporting_matrix_rejects_a_missing_clause`,
  `test_codex_collaboration_dispatch_carries_operation_envelope`,
  `test_sdd_generator_stops_are_decided_before_review_dispatch`,
  `test_shared_support_documents_reuse_the_retained_snapshot` and
  `test_listed_support_documents_reuse_only_passed_snapshot_fields`.

- [ ] **Step 1: Write the failing tests**

All edits are in `T`.

1. Directly above `def assert_configured_code_review_pair(case, owner, support):`,
   insert:

```python
# The capacity rule binds only on the `available` route, and a Codex call made
# under `unsupported` is classified beside it (issue 195, D7, D9).
CAPACITY_SCOPE_ANCHORS = (
    "`available` route", "capacity rejection", "no retry", "no native fallback",
    "routing error, never a capacity rejection",
)


```

2. In `assert_configured_code_review_pair`, the support-text `assert_ordered`
   call is one line that ends today with

```python
"terminal agent-message", "last-message", "capacity rejection", "no retry", "no native fallback")
```

   Replace that ending with

```python
"terminal agent-message", "last-message", "`blocked` stops", *CAPACITY_SCOPE_ANCHORS)
```

   The earlier anchors on that line are unchanged.

3. In `assert_codex_operation_pair`, the owner `assert_ordered` call ends today
   with these two lines:

```python
        "terminal agent-message", "last-message", "capacity rejection",
        "no retry", "no native fallback",
```

   Replace them with this one line:

```python
        "terminal agent-message", "last-message", *CAPACITY_SCOPE_ANCHORS,
```

4. In `test_review_capability_routes_before_command_lookup`, after the `for`
   loop and at the method's indentation level, append:

```python
        # codex-collaboration's own side (issue 195, D6): `unsupported` makes no
        # Codex call, and says so before the command entry is dereferenced.
        self.assert_ordered(
            normalized(COLLABORATION.read_text(encoding="utf-8")),
            "capabilities.review.code", "`unsupported` makes no Codex call",
            "dereference `bindings.commands[review_id]`",
        )
        self.assertIn(
            "An unsupported capability never dispatches Codex, because the "
            "calling controller runs its own native correctness route",
            normalized(DIFF_REVIEW.read_text(encoding="utf-8")),
        )
```

5. Directly after `test_ship_issue_configured_review_pair_is_complete`, add:

```python
    def test_configured_review_paragraph_copies_stay_identical(self):
        # ship-issue REVIEW.md and sdd final-review.md share one configured-review
        # paragraph, so its capacity scope changes in both at once (issue 195, D7).
        def paragraph(path):
            text = path.read_text(encoding="utf-8")
            start = text.index("For configured code review,")
            return text[start:text.index("\n", start)]
        self.assertEqual(paragraph(SHIP_ISSUE_REVIEW),
                         paragraph(SDD_DIR / "final-review.md"))
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
PYTHONPATH=python python3 -m unittest $T -k configured_review -k codex_plan_review_owner \
  -k codex_diff_review_owner -k capability_routes_before 2>&1 \
  | grep -E '^(FAIL|ERROR):|^AssertionError|^Ran |^OK|^FAILED'
```

Expected: `Ran 6 tests` and `FAILED (failures=5)`. The two configured-pair tests
fail on `` `blocked` stops``, the two codex-pair tests fail on
`` `available` route``, and the capability test fails on
`` `unsupported` makes no Codex call``. The identity test already passes, because
the copies are identical at the start. It exists to keep them identical.

- [ ] **Step 3: Edit the four documents**

1. In `$SK/ship-issue/REVIEW.md` **and** `$SK/sdd/final-review.md`, replace
   exactly
   ```
   A capacity rejection has no retry and no native fallback; blocked stops.
   ```
   with
   ```
   `blocked` stops. On the `available` route, a capacity rejection has no retry and no native fallback. A Codex call made under `unsupported` is a routing error, never a capacity rejection.
   ```
   The paragraph stays one line, and the rest of it is unchanged.

2. In `$CC/SKILL.md`, replace these six lines:
   ```
   retained capability before dereferencing any command entry: `blocked` stops with
   its capability reason and repair ID; `unsupported` takes that operation's
   documented native route. Only for `available`, retain the selected `review_id`
   and dereference `bindings.commands[review_id]`. Do not use a default, a plugin bridge,
   or a second resolver. `bindings.paths.hints` is the only project-hint input and
   is supplied by path when it is available.
   ```
   with these seven:
   ```
   retained capability before dereferencing any command entry: `blocked` stops with
   its capability reason and repair ID; `unsupported` makes no Codex call and
   returns the operation, with no result and no fallback verdict, to its calling
   controller's documented native route. Only for `available`, retain the selected
   `review_id` and dereference `bindings.commands[review_id]`. Do not use a default,
   a plugin bridge, or a second resolver. `bindings.paths.hints` is the only
   project-hint input and is supplied by path when it is available.
   ```

3. In `$CC/SKILL.md`, replace this paragraph:
   ```
   A daemon, slot, or capacity rejection is a binding capacity rejection: surface
   it verbatim, stop, make no retry, and take no native fallback. A completed
   available-command runtime failure, malformed or mismatched metadata/output, or
   operation-schema failure uses exactly one native fallback with the same packet;
   never retry Codex. The fallback is not route-establishment evidence.
   ```
   with:
   ```
   On the `available` route, a daemon, slot, or capacity rejection is a binding
   capacity rejection: surface it verbatim, stop, make no retry, and take no native
   fallback. A Codex call made under `unsupported` is a routing error, never a
   capacity rejection. A completed available-command runtime failure, malformed or
   mismatched metadata/output, or operation-schema failure uses exactly one native
   fallback with the same packet; never retry Codex. The fallback is not
   route-establishment evidence.
   ```

4. In `$CC/DIFF-REVIEW.md`, replace these two lines:
   ```
   runs after it, never before. An unsupported capability takes the documented native
   route and never dispatches, so measuring first would be wasted work.
   ```
   with:
   ```
   runs after it, never before. An unsupported capability never dispatches Codex,
   because the calling controller runs its own native correctness route, so
   measuring first would be wasted work.
   ```
   The line above them, `The retained `capabilities.review.code` selection runs
   first; this size pre-flight`, is unchanged.

- [ ] **Step 4: Verify**

```bash
if grep -qF 'A capacity rejection has no retry and no native fallback; blocked stops.' \
  $SK/ship-issue/REVIEW.md $SK/sdd/final-review.md; then exit 1; fi
if LC_ALL=C tr -s '[:space:]' ' ' < $CC/SKILL.md | grep -qF "takes that operation's documented native route"; then exit 1; fi
if LC_ALL=C tr -s '[:space:]' ' ' < $CC/DIFF-REVIEW.md | grep -qF 'takes the documented native route'; then exit 1; fi
if git diff HEAD -- $SK $CC | grep -qE '^[-+](<!-- agent-dispatch|Agent\()'; then exit 1; fi
PYTHONPATH=python python3 -m unittest $T -k configured_review -k codex_plan_review_owner \
  -k codex_diff_review_owner -k capability_routes_before 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T home/common/agent-skills/tests/test_dispatch_contracts.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
git diff --numstat HEAD -- $SK $CC
```

Expected: all four prohibitions pass. Then `Ran 6 tests` and `OK`. Then the four
suites give `Ran 218 tests` and `OK (skipped=3)`: the base count was 217, and
this task adds 1 test. The numstat lists exactly `$SK/ship-issue/REVIEW.md`,
`$SK/sdd/final-review.md`, `$CC/SKILL.md` and `$CC/DIFF-REVIEW.md`, and nothing
else under those two roots.

- [ ] **Step 5: Commit**

```bash
git add $T $SK/ship-issue/REVIEW.md $SK/sdd/final-review.md $CC/SKILL.md $CC/DIFF-REVIEW.md
git commit -m "fix(skills): scope the Codex capacity rule to the available route (#195)" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
