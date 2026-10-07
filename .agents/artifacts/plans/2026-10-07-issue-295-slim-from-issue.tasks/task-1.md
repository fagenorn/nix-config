# Task 1: Delete bindings.md and grounding.md; cut the per-file policy-support sentences

**Files** (all under `home/common/agent-skills/` unless absolute):
- Delete: `skills/from-issue/bindings.md`, `skills/from-issue/grounding.md`
- Modify: `skills/from-issue/SKILL.md`, `skills/from-issue/AUTO.md`, `skills/from-issue/investigate.md`, `skills/from-issue/standards-review.md`, `skills/from-issue/ship-handoff.md`, `skills/from-issue/REVIEW-CONTRACT.md`
- Modify: `instruction-load.json`, `skill-lint-debt.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: the base tree at `a891b08c`.
- Produces: no `from-issue/bindings.md` or `from-issue/grounding.md`, and no profile that lists either one. `SKILL.md` gains two index lines that later tasks keep:
  - the placeholder line: "`<tracker-cli>` is `bindings.tracker.cli`; before invoking it, unset only the names `bindings.tracker.credential_env.unset_before_invocation` lists."
  - the grounding line: "Phases 2–5 ground through `doc-grounded-questions` before their first question, option set or review pass; that skill owns the pass and its git-dir `GROUNDING.md` cache."

**Invariants:**
- `SKILL.md`'s resolve paragraph (the body's first paragraph) is byte-identical to the base (per D10).
- The phrase "retained `ResolvedProject`" no longer appears in `AUTO.md`, `investigate.md`, `standards-review.md` or `ship-handoff.md` (per D10).
- `REVIEW-CONTRACT.md` keeps one clause telling its reader to use only the binding values and capability states the caller supplies, never resolving or inferring policy (per D14).
- No from-issue file names `bindings.md` or `grounding.md`.
- `SHARED_POLICY_ENTRIES["from-issue/SKILL.md"]` is unchanged (per D10).

- [ ] **Step 1: Re-point the policy tests (they fail until Step 3)**

In `tests/test_workflow_skill_contracts.py`:

1. In `SHARED_POLICY_SUPPORT`, delete the four `from-issue/...` rows: `grounding.md`, `investigate.md`, `ship-handoff.md`, `standards-review.md`. In `RETAINED_SUPPORT_CONTRACTS`, delete the three `from-issue/...` rows: `bindings.md`, `AUTO.md`, `REVIEW-CONTRACT.md`. Leave every other row unchanged.
2. Replace `ProjectPolicySurfaceTest.test_build_delivery_callers_name_the_sanctioned_resolution_exception` with this version. Scoped from-issue reference files leave the sweep (per D13), and `SKILL.md`'s resolve paragraph keeps carrying the exception (per D10):

```python
    def test_build_delivery_callers_name_the_sanctioned_resolution_exception(self):
        exception = ("only sanctioned exception is `workflow-state build-delivery`, "
                     "which performs its own sealed, read-only resolution")
        scoped = "home/common/agent-skills/skills/from-issue/"
        callers = []
        for root in (REPO_ROOT / "home/common/agent-skills/skills",
                     REPO_ROOT / "home/common/claude-code/skills"):
            for path in sorted(root.rglob("*.md")):
                relative = path.relative_to(REPO_ROOT).as_posix()
                if relative.startswith(scoped) and relative != scoped + "SKILL.md":
                    continue
                text = normalized(path.read_text(encoding="utf-8"))
                if "build-delivery" not in text:
                    continue
                callers.append(relative)
                with self.subTest(path=relative):
                    self.assertIn(exception, text)
        self.assertEqual(sorted(callers), [
            "home/common/agent-skills/skills/from-issue/SKILL.md",
            "home/common/agent-skills/skills/ship-issue/SKILL.md",
            "home/common/claude-code/skills/orchestrate-issues/SKILL.md",
        ])
```

3. Add this test to `ProjectPolicySurfaceTest`. It is the falsifiable check for the deletion:

```python
    def test_from_issue_has_no_bindings_or_grounding_reference_file(self):
        directory = REPO_ROOT / "home/common/agent-skills/skills/from-issue"
        for name in ("bindings.md", "grounding.md"):
            with self.subTest(name=name):
                self.assertFalse((directory / name).exists())
                for path in sorted(directory.glob("*.md")):
                    self.assertNotIn(name, path.read_text(encoding="utf-8"), path.name)
```

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ProjectPolicySurfaceTest` (timeout 300 s)
Expected: FAIL. `test_from_issue_has_no_bindings_or_grounding_reference_file` fails because `bindings.md` exists.

- [ ] **Step 3: Delete the files and rewrite the pointers**

- `git rm` both files.
- `SKILL.md` `## Files beside this one`: replace the `bindings.md` bullet with the placeholder line (Interfaces). Drop `grounding.md` from the "loaded at the named phase" bullet, and add the grounding line. `## Phase 2 — Brainstorm`: replace "Ground first per `grounding.md`." with "Ground first through `doc-grounded-questions`."
- `AUTO.md`: delete the line-6 support sentence. In `## The self-answer pattern` step 1, replace "(see `grounding.md` beside `SKILL.md`)" with nothing, so the step reads "Use this phase's `GROUNDING.md` cache." Keep the rest of the step.
- `investigate.md`, `standards-review.md`: delete each one's "This included document receives …" sentence.
- `ship-handoff.md`: delete its line-3 paragraph, both the support sentence and the build-delivery exception that follows it.
- `REVIEW-CONTRACT.md`: in the first paragraph, replace "This included document receives the phase owner's retained `ResolvedProject`; it uses passed `bindings.workflow.review`, `bindings.commands`, and capability states without resolving or inferring policy." with "Use only the binding values and capability states the caller supplies; never resolve or infer policy." (per D14).

- [ ] **Step 4: Delete the prose pins these edits touch**

Run the focused suite (root Global Constraints). Take each failing method that reads `AUTO.md`, `SKILL.md` § Files beside this one or Phase 2, or any of the four support files' opening lines. Apply D11 to it: delete each prose assertion, delete any method left with no assertion, and keep and re-point each machine-read assertion. Do not touch assertions on other skills (per D13).

- [ ] **Step 5: Models**

- `instruction-load.json`: remove `from-issue/bindings.md` and `from-issue/grounding.md` from `from-issue-controller.hot`, `orchestrated-issue-owner.hot` and `implementation-owner.hot`, and remove the `from-issue/grounding.md` key from `implementation-owner.unread`. Change nothing else by hand.
- `skill-lint-debt.json`: delete `"L4b home/common/agent-skills/skills/from-issue/AUTO.md names grounding.md"` (per D12).
- Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run the focused suite. Expected: OK, with no test erroring on a missing file.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run (fails at the base, passes after this task):

```bash
set -euo pipefail
F=home/common/agent-skills/skills/from-issue
test ! -e "$F/bindings.md" && test ! -e "$F/grounding.md"
for f in AUTO.md investigate.md standards-review.md ship-handoff.md; do
  if grep -q 'retained `ResolvedProject`' "$F/$f"; then echo "support sentence left in $f"; exit 1; fi
done
if grep -q 'grounding.md\|bindings.md' home/common/agent-skills/instruction-load.json home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
git diff --quiet a891b08cc4d1599c71e7802ba49ec5da07631132 -- "$F/SKILL.md" && exit 1
python3 - <<'EOF'
import subprocess
base = subprocess.run(["git", "show", "a891b08cc4d1599c71e7802ba49ec5da07631132:home/common/agent-skills/skills/from-issue/SKILL.md"], capture_output=True, text=True, check=True).stdout
head = open("home/common/agent-skills/skills/from-issue/SKILL.md", encoding="utf-8").read()
para = next(p for p in base.split("\n\n") if p.startswith("Run `resolve-project resolve"))
assert para in head, "resolve paragraph changed"
EOF
```

- [ ] **Step 7: Commit**

Stage the files above and commit as `refactor(from-issue): delete bindings.md and grounding.md and the support-file policy sentences (#295)`. The body names any conditional raise (none is expected).
