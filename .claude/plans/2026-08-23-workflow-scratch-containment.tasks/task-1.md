# Task 1: Producer-report candidates leave the working tree

**Files:**
- Modify: `home/common/agent-skills/skills/design/SKILL.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/SKILL.md`
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/handoff/SKILL.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Produces: the module-level constants `REPORT_CANDIDATE_CLAUSE`, `SKILL_ROOTS`, `SIBLING_CANDIDATE_RE` and the helpers `normalized(text)` and `corpus_documents()` in `test_workflow_skill_contracts.py`. Tasks 2 and 4 import nothing — they add tests to the same module and reuse `normalized()`, `SKILL_ROOTS` and `corpus_documents()` by name, so spell them exactly as given. Task 5 reuses none of them.
- Consumes: nothing from earlier tasks.

**Invariants:**
- The clause below appears byte-for-byte identically (after whitespace normalization) in all four skills; no skill paraphrases it.
- `handoff`'s publication temporary keeps its sibling placement (per D2). The prose names the durable publication route's two temporaries and says the third — the default nondurable candidate `handoff` already creates at its top — is neither, so a later reader cannot "fix" the load-bearing one.
- No `*.md` under either skill root prescribes a candidate that is a sibling of anything.
- Nothing else in any Return-control section changes: the state rows, the metrics, the `notes` bound, "return only the exact validated stdout bytes", and the exit-2-is-`failed` rule all survive.
- The three existing ordered assertions that anchor on `candidate JSON` *before* `validate-report` are this task's to re-anchor (Step 4), not Task 6's. This task is not done while `just agent-workflow-tests` is red.

Cites D1, D2, D10.

- [ ] **Step 1: Write the failing tests**

Add at module level, after the existing `GATE_FILE_BOUNDARY` constant:

```python
# `re`, `os`, `subprocess`, `tempfile` and `Path` are already imported at the
# top of this module; add no new imports.

SKILL_ROOTS = (
    REPO_ROOT / "home/common/agent-skills/skills",
    REPO_ROOT / "home/common/claude-code/skills",
)

# The producer-report candidate contract, spelled once for the whole corpus so
# the four skills that carry it cannot drift apart (D1).
REPORT_CANDIDATE_CLAUSE = (
    "a report candidate outside every working tree — create it with `mktemp "
    '"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` '
    "template works on both macOS/BSD and Linux) — invoke `artifact-budget "
    "validate-report --boundary producer --input <report-candidate>`, and "
    "remove that candidate under an unconditional cleanup that runs on every "
    "outcome, including validation rejection and failure: a shell `trap` on "
    "`EXIT HUP INT TERM`, or the equivalent `finally`"
)

# "sibling <=2 words> candidate" — the in-working-tree prescription being
# removed. The bounded gap keeps it off handoff's legitimate
# "candidate ... sibling temporary" sentences, where the words appear in the
# other order (D2).
SIBLING_CANDIDATE_RE = re.compile(r"sibling(?:\s+\S+){0,2}\s+candidate")


def normalized(text):
    """Collapse every whitespace run to one space (the corpus hard-wraps ~80c)."""
    return re.sub(r"\s+", " ", text)


def corpus_documents():
    """Every skill document in both skill trees, as (path, text) pairs."""
    for root in SKILL_ROOTS:
        for path in sorted(root.rglob("*.md")):
            yield path, path.read_text(encoding="utf-8")
```

Add these four tests to `WorkflowSkillContractsTest`:

```python
    def test_four_producer_skills_share_one_report_candidate_clause(self):
        clause = normalized(REPORT_CANDIDATE_CLAUSE)
        for name, text in (
            ("design", self.design),
            ("grill-with-docs", self.grill),
            ("writing-plans", self.writing_plans),
            ("handoff", self.handoff),
        ):
            with self.subTest(skill=name):
                self.assertIn(clause, normalized(text))

    def test_handoff_failure_reemit_uses_a_fresh_report_candidate(self):
        self.assertIn(
            "a fresh report candidate created and cleaned up the same way",
            normalized(self.handoff),
        )

    def test_handoff_keeps_the_publication_sibling(self):
        text = normalized(self.handoff)
        self.assertIn("as a sibling temporary regular file", text)
        self.assertIn("written as a sibling of the durable destination", text)

    def test_no_skill_prescribes_a_sibling_candidate(self):
        offenders = [
            f"{path.relative_to(REPO_ROOT)}: {match.group(0)!r}"
            for path, text in corpus_documents()
            for match in SIBLING_CANDIDATE_RE.finditer(normalized(text))
        ]
        self.assertEqual(offenders, [])
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k report_candidate -k publication_sibling -k sibling_candidate -k failure_reemit -v`

Expected: FAIL. The three positive tests fail because no skill carries the new clause yet; `test_no_skill_prescribes_a_sibling_candidate` fails with exactly five offenders, listed in corpus order — `design/SKILL.md`, `grill-with-docs/SKILL.md`, `handoff/SKILL.md` twice, then `writing-plans/SKILL.md`. (Verified at the base commit: `finditer` reports exactly those five spans and nothing else. `search` would report four — one per file — and would hide `handoff`'s second span, which is why the comprehension iterates every match.)

- [ ] **Step 3: Apply the clause to the four skills**

Replace the block at `design/SKILL.md:120-125` with, exactly:

```markdown
Only after the last artifact check, write the object as UTF-8 to a report
candidate outside every working tree — create it with `mktemp
"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux) — invoke `artifact-budget validate-report
--boundary producer --input <report-candidate>`, and remove that candidate under
an unconditional cleanup that runs on every outcome, including validation
rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, or the equivalent
`finally`. Return only the exact validated stdout bytes. Validation exit 2 is
`failed`: emit no Markdown, YAML, candidate JSON, truncated text, or prose
fallback. Do not invoke `writing-plans`, start implementing, or offer to — the
caller owns the next phase.
```

Replace the block at `grill-with-docs/SKILL.md:147-152` with the identical text through `` `finally`. ``, then its own two closing sentences unchanged:

```markdown
Only after the last artifact check, write the object as UTF-8 to a report
candidate outside every working tree — create it with `mktemp
"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux) — invoke `artifact-budget validate-report
--boundary producer --input <report-candidate>`, and remove that candidate under
an unconditional cleanup that runs on every outcome, including validation
rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, or the equivalent
`finally`. Return only the exact validated stdout bytes. Validation exit 2 is
`failed`: emit no Markdown, YAML, candidate JSON, truncated text, or prose
fallback. Do not invoke the next skill or start implementing — the caller owns
what happens next.
```

Replace the block at `writing-plans/SKILL.md:247-252`. Its lead-in is "Write this object as UTF-8 to …", and the return instruction — attached today by a comma — becomes its own sentence after the clause:

```markdown
Write this object as UTF-8 to a report candidate outside every working tree —
create it with `mktemp "${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the
explicit `XXXXXX` template works on both macOS/BSD and Linux) — invoke
`artifact-budget validate-report --boundary producer --input <report-candidate>`,
and remove that candidate under an unconditional cleanup that runs on every
outcome, including validation rejection and failure: a shell `trap` on `EXIT HUP
INT TERM`, or the equivalent `finally`. Return only the exact validated stdout
bytes. Validator exit 2 is `failed`; do not emit the candidate or a prose
fallback. Do not offer an execution choice, invoke an execution skill, or start
implementing — the caller owns standards review and execution.
```

Replace the block at `handoff/SKILL.md:69-74`. Its lead-in is "Only after the last artifact check, serialize the row as UTF-8 to …", and "hold only the exact validated stdout bytes" becomes its own sentence:

```markdown
Only after the last artifact check, serialize the row as UTF-8 to a report
candidate outside every working tree — create it with `mktemp
"${TMPDIR:-/tmp}/producer-report-XXXXXX.json"` (the explicit `XXXXXX` template
works on both macOS/BSD and Linux) — invoke `artifact-budget validate-report
--boundary producer --input <report-candidate>`, and remove that candidate under
an unconditional cleanup that runs on every outcome, including validation
rejection and failure: a shell `trap` on `EXIT HUP INT TERM`, or the equivalent
`finally`. Hold only the exact validated stdout bytes. Validation exit 2 is
`failed`: emit no Markdown, YAML, candidate JSON, truncated text, or prose
fallback. It must also leave the existing destination byte-identical and remove
unpublished temporary names.
```

In `handoff/SKILL.md:85`, replace `a new sibling report candidate` with `a fresh report candidate created and cleaned up the same way`, leaving the rest of that sentence — "validate and remove it by the same protocol, and return only that validated stdout." — untouched.

Insert this paragraph in `handoff/SKILL.md` immediately after the paragraph ending "Do not open the destination for writing and do not publish yet." (line 25), separated by one blank line. Use no bold markers — the tests match plain text:

```markdown
Two temporaries are involved in the durable publication route below and must not
be confused. The sibling temporary holds the checked artifact bytes and is
written as a sibling of the durable destination, because the install is a
same-directory hard-link or atomic replace — sibling placement is a correctness
requirement, not a convenience. The report candidate holds the producer-report
JSON, is never published, has no life beyond the call, and therefore lives in OS
temp. The default nondurable candidate above is neither and needs no protocol.
```

The count is scoped to the durable publication route on purpose: the nondurable
`mktemp "${TMPDIR:-/tmp}/handoff-XXXXXX.md"` candidate at the top of the file is a
third temporary, and the closing sentence retires it rather than leaving the
paragraph's "two" wrong. The paragraph reuses the file's existing vocabulary —
"sibling temporary" — and coins nothing, so the publication protocol at lines
76–91 needs no matching rename and must not be touched.

Change nothing else in any of the four files. In particular do not touch `handoff`'s "Candidate budget state machine" section, its publication protocol, or the `<candidate-root>` arguments to `artifact-budget check`.

- [ ] **Step 4: Re-anchor the three existing ordered assertions**

Step 3 removed exactly the four blocks that put the literal `candidate JSON`
*before* `validate-report`. Three live assertions in
`home/common/agent-skills/tests/test_workflow_skill_contracts.py` anchor on that
ordering, so the suite is now red in five places across three tests. Re-anchor
them by exact match on the lines quoted below — never by line number.

Two of the three match on raw file text, and the new clause hard-wraps: after
Step 3 both `report candidate outside every working tree` and
`validate-report --boundary producer` straddle a line break, so a raw `str.find`
cannot see either. Those two calls therefore move onto `normalized(...)`, the
module helper Step 1 added, which is what the whitespace-normalization rule (D10)
already requires of every prose match. Verified against the post-Step-3 text: with
`normalized()` all three assertions pass; without it they fail on the first anchor.

In `test_plan_package_contract_is_root_only_and_fail_closed`, replace

```python
        self.assert_ordered(self.writing_plans, "candidate JSON", "validate-report",
                            "validated stdout bytes")
```

with

```python
        self.assert_ordered(normalized(self.writing_plans),
                            "report candidate outside every working tree",
                            "validate-report", "validated stdout bytes")
```

In `test_design_persists_the_final_measured_spec_before_reporting_complete`,
replace the single anchor line

```python
            "candidate JSON file",
```

with

```python
            "report candidate outside every working tree",
```

Leave that call's seven other anchors and its `design = " ".join(self.design.split())`
lead-in alone — it already matches on normalized text.

In `test_artifact_reports_are_bounded_root_only_shapes`, replace

```python
            self.assert_ordered(producer, "candidate JSON", "validate-report --boundary producer",
                                "validated stdout")
```

with

```python
            self.assert_ordered(normalized(producer),
                                "report candidate outside every working tree",
                                "validate-report --boundary producer",
                                "validated stdout")
```

Change nothing else in those three tests. Every other assertion in them — the
field and metric loops, the `(D5)` / `(D11, D14)` decision markers, the
`notes_max_characters` bound, the forbidden-field regexes — still holds against
the rewritten prose.

- [ ] **Step 5: Verify**

```bash
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -v 2>&1 | tail -5
```
Expected: `OK`. This is the first point in the task where the module is green: the
four new tests pass **and** the three re-anchored ones do. Between Step 3 and
Step 4 it is legitimately red in five places —
`test_artifact_reports_are_bounded_root_only_shapes` once each for `design`,
`grill-with-docs` and `handoff`, plus
`test_plan_package_contract_is_root_only_and_fail_closed` and
`test_design_persists_the_final_measured_spec_before_reporting_complete`.

```bash
if grep -rn 'remove the candidate on every outcome' \
   home/common/agent-skills/skills home/common/claude-code/skills; then exit 1; fi
```
Expected: exit 0 with no output — the old un-mechanised wording is gone everywhere.

```bash
just agent-workflow-tests 2>&1 | tail -5
```
Expected: `OK`. The whole-repo suite runs here, not only in Task 6, so a
corpus-wide regression from this task's prose rewrite surfaces in the task that
caused it.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/design/SKILL.md \
        home/common/agent-skills/skills/grill-with-docs/SKILL.md \
        home/common/agent-skills/skills/writing-plans/SKILL.md \
        home/common/agent-skills/skills/handoff/SKILL.md \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "fix(agent-skills): move producer-report candidates out of the working tree"
```
