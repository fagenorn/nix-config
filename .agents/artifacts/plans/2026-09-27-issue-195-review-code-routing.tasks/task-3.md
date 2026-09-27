# Task 3: sdd's final review routes the correctness axis the same way, then the final gate runs

Decisions: D1 (sdd changes in this issue), D2 (the routing-error action and
where it is recorded), D4 and D5 (the ladder and "installed"), D8 (the axis
identity stays `native`, and no failure class is added), D9 (rung 2 points to
the configured-review paragraph above), D10 (the tiers and header pins and the
sdd self-check), D11 (sdd eval 2 stays as it is). Spec §5, AC3, AC4 and AC5.
Work from the worktree root. Every shell block starts with `set -euo pipefail`
and these abbreviations, which the blocks below omit:

```bash
T=home/common/agent-skills/tests/test_workflow_skill_contracts.py
D=home/common/agent-skills/skills/sdd
```

**Files:**
- Modify: `home/common/agent-skills/skills/sdd/final-review.md` (the
  `- **Correctness axis**` bullet only)
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md` (the `## Agent tiers`
  bullet that starts `- The **final review's two axes**`)
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`
  (the header above the `sdd-final-correctness-review` marker)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Task 2), from `T`: `CORRECTNESS_ROUTE_OPENER`,
  `assert_correctness_route_ladder(case, route, native_target)` and its phrase
  set. That set is the rung leads `1. `blocked``, `2. `available``,
  `3. `unsupported`` and the phrases "routing error", "discard its outcome",
  "beside the correctness verdict", "rung-3 native dispatch" and "no retry,
  stop or suspension". The helper normalizes whitespace, so the nested list's
  indentation does not matter to it.
- Consumes (Task 1): the configured-review paragraph at the top of
  `final-review.md`, which rung 2 calls "the configured-review terms above".
- Produces: nothing a later task uses.

**Invariants:**
- The `sdd-final-correctness-review` marker and its call line in
  `correctness-reviewer-prompt.md` stay byte for byte. The fenced prompt body
  does not change.
- `final-review.md` gains no code fence. Its paragraph that starts `Point the
  conformance dispatch` stays unchanged, including the identity set
  `` `Codex` | `native` | `fallback` + failure class ``, the `diff-review` scope
  sentence, and "the native reviewer dispatched directly returns no scope, so
  record none there".
- In `SKILL.md`, the `## Agent tiers` section keeps the two leaf-agent clauses
  exactly once, because `test_dispatch_contracts.py` reads that section as a
  carrier.

**Existing pins this task touches** (none needs an edit; all must stay green):
`test_calling_controllers_record_the_correctness_scope`,
`test_correctness_rubric_discloses_scope_only_when_the_packet_says_so` (it bans
"Codex"/"native" only inside the fenced prompt's `## Output Format` and
`## Diff Under Review` sections, and the header sits outside both),
`test_sdd_review_paths_use_validated_manifest_packages`,
`test_sdd_review_contracts_preserve_adaptive_whole_file_coverage`,
`test_review_capability_routes_before_command_lookup`, the model-matrix row
`sdd-final-correctness-review`, and every `test_dispatch_contracts.py` test.
That includes `test_every_single_fence_template_is_an_enrolled_fence_carrier`.

- [ ] **Step 1: Write the failing tests**

All edits are in `T`.

1. Directly above `def ship_correctness_route(text=None):`, the function that
   Task 2 added, insert:

```python
SDD_CORRECTNESS_TARGET = "[correctness-reviewer-prompt.md](correctness-reviewer-prompt.md)"
# sdd final-review's correctness routing before issue 195, kept only so the
# ladder helper's self-check can put it back.
SDD_PRE_FIX_ROUTE = (
    "When the `codex-collaboration` skill is available, invoke its `diff-review` "
    "operation for this axis; that skill solely owns the isolated Codex transport "
    "launch and one-time native fallback, while the external Codex reviewer keeps "
    "its independently configured model. Unavailable → use the Opus/high native "
    "reviewer selected in [correctness-reviewer-prompt.md]"
    "(correctness-reviewer-prompt.md). Either way the axis is never skipped."
)


def sdd_correctness_route(text=None):
    """sdd final-review's correctness-axis bullet, through its routing-error paragraph."""
    if text is None:
        text = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
    start = text.index("- **Correctness axis**")
    return text[start:text.index("Point the conformance dispatch", start)]


```

2. In `ProjectPolicySurfaceTest`, directly above
   `def test_context_map_selection_uses_only_authored_order(self):`, add:

```python
    def test_sdd_correctness_route_is_the_capability_ladder(self):
        route = sdd_correctness_route()
        assert_correctness_route_ladder(self, route, SDD_CORRECTNESS_TARGET)
        route = normalized(route)
        self.assertIn(
            "This is the only rung that reaches Codex and the only one where a "
            "capacity rejection binds, on the configured-review terms above.", route)
        self.assertIn(
            "record the routing error in the ledger beside the correctness "
            "verdict, with the axis's reviewer identity still `native`", route)
        # The agent-tiers bullet and the rubric header restate the same route.
        self.assertIn(
            "the correctness axis via `codex-collaboration`'s `diff-review` when "
            "`capabilities.review.code` is `available` and that skill is "
            "installed, and as `reviewer` on Opus/high when the capability is "
            "`unsupported` or the skill is not installed (`blocked` stops)",
            normalized(SDD.read_text(encoding="utf-8")))
        self.assertIn(
            "dispatched directly when `capabilities.review.code` is `unsupported` "
            "or `codex-collaboration` is not installed. When the capability is "
            "`available` and that skill is installed, its `diff-review` operation "
            "carries this file",
            normalized((SDD_DIR / "correctness-reviewer-prompt.md").read_text(
                encoding="utf-8")))

    def test_correctness_route_ladder_rejects_the_pre_fix_sdd_route(self):
        # Putting sdd's skill-presence routing back makes the helper raise
        # (issue 195, D3).
        text = (SDD_DIR / "final-review.md").read_text(encoding="utf-8")
        end_anchor = "`blocked` stops the whole review instead."
        self.assertTrue(CORRECTNESS_ROUTE_OPENER in text and end_anchor in text,
                        "sdd ladder anchors missing")
        start = text.index(CORRECTNESS_ROUTE_OPENER)
        end = text.index(end_anchor, start) + len(end_anchor)
        with self.assertRaises(AssertionError):
            assert_correctness_route_ladder(
                self,
                sdd_correctness_route(text[:start] + SDD_PRE_FIX_ROUTE + text[end:]),
                SDD_CORRECTNESS_TARGET)
```

- [ ] **Step 2: Run the tests and watch them fail**

```bash
PYTHONPATH=python python3 -m unittest $T -k correctness_route 2>&1 \
  | grep -E '^(FAIL|ERROR):|^AssertionError|^Ran |^OK|^FAILED' | cut -c1-200
```

Expected: `Ran 4 tests` and `FAILED (failures=2)`. The sdd ladder test fails on
the missing `CORRECTNESS_ROUTE_OPENER`, and the sdd self-check fails with `sdd
ladder anchors missing`. Task 2's two ship tests pass.

- [ ] **Step 3: Edit the three sdd documents**

1. In `$D/final-review.md`, the `- **Correctness axis**` bullet is one line. Keep
   its first sentence, which runs up to and including "cross-task
   integration.". Replace the rest of that line, which starts at "When the
   `codex-collaboration` skill is available" and ends at "Either way the axis
   is never skipped.", so that the bullet becomes exactly the block below. The
   rung lines are indented two spaces, a blank line comes before the
   continuation paragraph, that paragraph is indented two spaces, and the blank
   line before `Point the conformance dispatch` stays:

```text
- **Correctness axis** — is it built right: bugs, boundary error handling, dead branches, assertions that pin the documented contract, DRY, cross-task integration. Choose the correctness route from the retained `capabilities.review.code` state before either axis is dispatched, never from how a Codex call failed:
  1. `blocked` stops with its capability reason and repair ID; neither axis is dispatched.
  2. `available`, with `codex-collaboration` installed → invoke its `diff-review` operation for this axis; that skill solely owns the isolated Codex transport launch and one-time native fallback, while the external Codex reviewer keeps its independently configured model. This is the only rung that reaches Codex and the only one where a capacity rejection binds, on the configured-review terms above.
  3. `unsupported`, or `available` without `codex-collaboration` installed → dispatch the Opus/high native reviewer selected in [correctness-reviewer-prompt.md](correctness-reviewer-prompt.md) directly; `codex-collaboration` is never invoked on this rung.

  A Codex call made under `unsupported` anyway is a routing error: discard its outcome — verdict, refusal or failure — record the routing error in the ledger beside the correctness verdict, with the axis's reviewer identity still `native`, and run the rung-3 native dispatch, with no retry, stop or suspension. The axis is never skipped; `blocked` stops the whole review instead.
```

2. In `$D/SKILL.md`, in the bullet that starts `- The **final review's two
   axes**`, replace exactly
   ```
   — the conformance axis as `reviewer` on Sonnet/high, the correctness axis via `codex-collaboration`'s `diff-review` when that skill is available, else as `reviewer` on Opus/high.
   ```
   with
   ```
   — the conformance axis as `reviewer` on Sonnet/high; the correctness axis via `codex-collaboration`'s `diff-review` when `capabilities.review.code` is `available` and that skill is installed, and as `reviewer` on Opus/high when the capability is `unsupported` or the skill is not installed (`blocked` stops).
   ```

3. In `$D/correctness-reviewer-prompt.md`, replace these lines (lines 3–9):
   ```
   The native form of the correctness axis — dispatched directly when
   `codex-collaboration` is unavailable. When that skill IS available, its `diff-review`
   operation carries this file by absolute path as the Codex reviewer's rubric, so keep
   the body reviewer-agnostic: nothing in it may assume which model is reading it.

   When the native fallback owns this first-pass whole-branch axis, it uses the
   explicit full reviewer tier:
   ```
   with:
   ```
   The native form of the correctness axis — dispatched directly when
   `capabilities.review.code` is `unsupported` or `codex-collaboration` is not
   installed. When the capability is `available` and that skill is installed, its
   `diff-review` operation carries this file by absolute path as the Codex reviewer's
   rubric, so keep the body reviewer-agnostic: nothing in it may assume which model is
   reading it.

   When the native form owns this first-pass whole-branch axis, it uses the
   explicit full reviewer tier:
   ```
   "native form" replaces "native fallback" because, under `unsupported`, this
   dispatch is the documented primary route (spec §5).

- [ ] **Step 4: Verify the documents**

```bash
if grep -qF 'When the `codex-collaboration` skill is available' $D/final-review.md; then exit 1; fi
if grep -qF 'when that skill is available, else' $D/SKILL.md; then exit 1; fi
if grep -qiF 'unavailable' $D/correctness-reviewer-prompt.md; then exit 1; fi
if grep -qE '^```' $D/final-review.md; then exit 1; fi
if git diff HEAD -- $D | grep -qE '^[-+](<!-- agent-dispatch|Agent\()'; then exit 1; fi
PYTHONPATH=python python3 -m unittest $T -k correctness_route 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T home/common/agent-skills/tests/test_dispatch_contracts.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
git diff --numstat HEAD -- home/common/agent-skills/skills home/common/claude-code/skills
```

Expected: all five prohibitions pass. Then `Ran 4 tests` and `OK`. Then the four
suites give `Ran 222 tests` and `OK (skipped=3)`, which is Task 2's 220 plus 2.
The numstat lists exactly `$D/final-review.md` (6 lines added, 1 deleted),
`$D/SKILL.md` (1, 1) and `$D/correctness-reviewer-prompt.md` (6, 4).

- [ ] **Step 5: Final gate**

```bash
LOG="${TMPDIR:-/tmp}"; LOG="${LOG%/}/issue-195-build.log"
just agent-workflow-tests 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if just build > "$LOG" 2>&1; then echo build-ok; else grep -E 'error:' "$LOG" | head -20; exit 1; fi
if git diff HEAD -- home/common/agent-skills/model-matrix.json | grep -q .; then exit 1; fi
git status --short
```

Expected: `Ran 1321 tests` and `OK (skipped=3)`. That is the base 1316 at
`87ad07e` plus this plan's 5, and the number grows only if a sync merge adds
tests. The suite takes about 9 minutes. The build prints
`build-ok`. `model-matrix.json` has no diff. `git status --short` shows only
this task's four files before the commit. Summarize any failure to its test ids
or `error:` lines. Never run `just switch`.

- [ ] **Step 6: Commit**

```bash
git add $T $D/final-review.md $D/SKILL.md $D/correctness-reviewer-prompt.md
git commit -m "fix(sdd): route the final correctness axis on review.code (#195)" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
