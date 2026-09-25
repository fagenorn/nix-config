# Task 3: Sandbox Limits Are Not Findings; Per-Operation Wall Clock

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/evals/evals.json`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

All five are repo-owned; this task touches nothing in `patches/` or `lib/` and needs no `patchRevision` bump. `CERTIFICATION.md` names "timeout contracts" but no number and is not edited.

**Interfaces:**
- Consumes: `SKILL.md`'s `## Read-only rules (both operations)` block, whose three bullets are already declared "Include these verbatim in substance in every packet" and which both operation files already declare they apply "alongside"; `PLAN-REVIEW.md` packet item 6 and `DIFF-REVIEW.md` packet item 5; both operations' existing could-not-verify channels — PLAN-REVIEW.md's "Explicitly report which supplied artifacts could not be read", DIFF-REVIEW.md's "unreadable artifacts reported explicitly", and the per-finding unknowns field both contracts already require.
- Consumes (test module): `REPO_ROOT`, the `WorkflowSkillContractsTest.setUpClass` loaders `cls.collaboration` / `cls.codex_plan_review` / `cls.diff_review`, and the helpers `self.section(text, heading, next_heading)` and `self.assert_ordered(text, *anchors)`.
- Produces (test module): a module-level `CODEX_COLLABORATION_EVALS` path constant, a `cls.codex_collaboration_evals` loader, and two new test methods — `test_codex_collaboration_states_a_per_operation_wall_clock` and `test_codex_collaboration_never_reports_sandbox_limits_as_findings`.

**Invariants:**
- The read-only rule is added as a **fourth bullet under `## Read-only rules (both operations)`** — the only shared text a packet actually carries — and not in the Launch paragraph, which is caller-facing narration the reviewer never receives (per D14).
- The rule is about **attribution, not topic**: a limitation of the reviewer's own execution environment is never a finding, while a defect in the reviewed artifact stays reportable even when a failed command is what exposed it, provided it is anchored in the artifact rather than in the transcript of the denial (per D6).
- It extends an existing channel rather than adding a mechanism: sandbox-blocked checks go to the could-not-verify statement and the per-finding unknowns field both operations already require (per D6).
- `test_codex_collaboration_dispatch_carries_operation_envelope` slices `SKILL.md` between `"Build the operation's packet"` and `"Parallel reviews are valid."`. The wall-clock edit happens **between** those anchors; neither anchor moves. `test_codex_plan_review_validates_before_packet_and_remeasures` slices `PLAN-REVIEW.md` between `"## Build the review packet"` and `"## Reviewer contract"` and requires `"Supply no member list or plan content"` inside it; the item-6 edit leaves both untouched.
- The caller-facing wall clock is a deliberate second copy of the registry's values, kept because callers schedule around it and no test may derive prose from the patch; it is therefore pinned in the repo contract suite, in both of its homes (per D8, D15).
- `evals/evals.json` stays valid JSON with its three evals, ids and modes unchanged; only the two wall-clock figures move.
- Nothing here widens the isolation model: no writable roots, no network, no non-fresh `CODEX_HOME` (per D6).

Cites: D6, D7, D8, D14, D15.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, add the path constant beside the other `codex-collaboration` constants near the top of the module:

```python
CODEX_COLLABORATION_EVALS = (
    REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/evals/evals.json"
)
```

and the loader inside `setUpClass`, beside `cls.codex_plan_review`:

```python
        cls.codex_collaboration_evals = json.loads(
            CODEX_COLLABORATION_EVALS.read_text(encoding="utf-8")
        )
```

Then add both test methods to `WorkflowSkillContractsTest`, next to `test_codex_collaboration_dispatch_carries_operation_envelope`:

```python
    def test_codex_collaboration_states_a_per_operation_wall_clock(self):
        # A deliberate second copy of the runtime's per-operation budget: callers
        # schedule around the number and prose cannot be derived from a patch, so
        # the copy is pinned here instead (D8).
        launch = self.section(
            self.collaboration,
            "Build the operation's packet",
            "Parallel reviews are valid.",
        )
        self.assertIn("roughly 28 minutes of wall clock for `plan-review`", launch)
        self.assertIn("roughly 14 minutes for `diff-review`", launch)
        for stale in ("~14 min", "~15 min"):
            with self.subTest(stale=stale, doc="SKILL.md"):
                self.assertNotIn(stale, self.collaboration)
        # The eval grades a model against this same number; unpinned, it would
        # keep grading against a figure the skill no longer states (D15).
        evals = json.dumps(self.codex_collaboration_evals)
        self.assertIn("~28 min of external wall clock", evals)
        self.assertIn("~28 minutes for plan-review", evals)
        self.assertNotIn("~15 min", evals)

    def test_codex_collaboration_never_reports_sandbox_limits_as_findings(self):
        # The rule lives in the packet-borne shared rules, not in the Launch
        # paragraph, because only these bullets travel to the reviewer (D14).
        rules = self.section(
            self.collaboration,
            "## Read-only rules (both operations)",
            "## Launch",
        )
        self.assert_ordered(
            rules,
            "limitation of your own execution environment is never a finding",
            "denies every write",
            "could not verify",
            "unresolved unknowns",
            "still reportable",
            "anchor it in the artifact",
        )
        # Stop provoking it as well as prohibiting it: neither packet may hand a
        # read-only reviewer commands that read as instructions (D7).
        for name, packet in (
            ("PLAN-REVIEW.md", self.codex_plan_review),
            ("DIFF-REVIEW.md", self.diff_review),
        ):
            with self.subTest(packet=name):
                self.assertIn("not a request to execute anything", packet)
        self.assertIn(
            "so the reviewer need not re-measure them", self.codex_plan_review
        )
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py -k codex_collaboration`
Expected: FAIL — both new methods. The wall-clock test fails on the missing `roughly 28 minutes` string (the skill still says `~14 min` / `~15 minutes`), and the sandbox test fails in `assert_ordered` with `missing anchor: 'limitation of your own execution environment is never a finding'`. The pre-existing `test_codex_collaboration_dispatch_carries_operation_envelope` still passes.

- [ ] **Step 3: Add the shared read-only rule** (per D6, D14)

In `SKILL.md`, append this as the fourth bullet of `## Read-only rules (both operations)`, after the "Inspect the live files at HEAD" bullet and before `## Launch`:

```markdown
- A limitation of your own execution environment is never a finding. The sandbox
  is `read-only` and denies every write, `TMPDIR` included, so test runners,
  mutation checks and anything else needing scratch space cannot run here and are
  not expected to. Report what you could not verify where you already report what
  you could not read, and in each finding's unresolved unknowns field — never as
  a `Blocking` / `Should fix` / `Critical` / `Important` / `Minor` item. A defect
  in the artifact under review is still reportable when a failed command is what
  exposed it; anchor it in the artifact with evidence, not in the transcript of
  the denial.
```

The blunter form — "never report anything that looks like a sandbox problem" — is the one to avoid: it would suppress a real defect that merely presents as one, such as a test that cannot run in *any* environment or a script with a genuinely broken interpreter path.

- [ ] **Step 4: State the per-operation wall clock** (per D8)

In `SKILL.md`'s Launch section, replace the budget clause of the contract sentence. It currently reads `and is bounded by the runtime's internal ~14 min budget — expect up to ~15 minutes wall clock.`; it becomes:

```markdown
and is bounded by a per-operation runtime budget — expect up to roughly 28
minutes of wall clock for `plan-review` and roughly 14 minutes for `diff-review`.
```

Leave the rest of that sentence (the isolation parenthetical, "survives the bridge's own lifetime", the `CODEX_REVIEW_FAILURE:` sentence after it) byte-identical, and do not touch either enclosing anchor.

In `evals/evals.json`, two figures move and nothing else:

- in `notes`, `and ~15 min of external wall clock` becomes `and up to ~28 min of external wall clock`;
- in eval 1's `expected_output`, `expecting an isolated read-only Codex runtime bounded around ~15 minutes` becomes `expecting an isolated read-only Codex runtime bounded per operation — ~28 minutes for plan-review, ~14 for diff-review`.

Evals 2 and 3 are untouched.

- [ ] **Step 5: Reframe the verify commands in both packets** (per D7)

In `PLAN-REVIEW.md`, packet item 6 currently reads `6. Relevant manifests and inferred verification commands.` It becomes:

```markdown
6. Relevant manifests and inferred verification commands, labelled in the packet
   as context describing how this work is verified elsewhere — explicitly not a
   request to execute anything. Item 3's four metrics are supplied so the
   reviewer need not re-measure them, and the caller has already validated them
   at its own input gate; a reviewer shelling out to `artifact-budget` is
   exceeding its contract, not filling a gap in it.
```

In `DIFF-REVIEW.md`, packet item 5 currently reads ``5. Inferred verify commands and every applicable `AGENTS.md`/`CLAUDE.md`.`` It becomes:

```markdown
5. Inferred verify commands, labelled in the packet as context describing how
   this change is verified elsewhere — explicitly not a request to execute
   anything, because the runtime is read-only and cannot run them — plus every
   applicable `AGENTS.md`/`CLAUDE.md`.
```

Item numbering, the "Nothing else rides along" paragraph, and the whole `### When the range is over budget` section (which changes items 2, 4 and 7 only) are unchanged.

- [ ] **Step 6: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py
just agent-workflow-tests
just build
```

Expected: the contract module passes in full — the two new methods and every pre-existing one, including `test_codex_collaboration_dispatch_carries_operation_envelope` and `test_codex_plan_review_validates_before_packet_and_remeasures`, whose sliced spans this task edits inside of. `just agent-workflow-tests` passes end to end (it re-runs the same module alongside the other suites; a JSON syntax error in `evals.json` surfaces here as a load failure in `setUpClass`). `just build` succeeds — the skill files are materialized by home-manager, so a malformed file fails the build.

- [ ] **Step 7: Commit**

```bash
git add home/common/claude-code/skills/codex-collaboration/SKILL.md \
        home/common/claude-code/skills/codex-collaboration/PLAN-REVIEW.md \
        home/common/claude-code/skills/codex-collaboration/DIFF-REVIEW.md \
        home/common/claude-code/skills/codex-collaboration/evals/evals.json \
        home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "$(cat <<'MSG'
feat(agent-skills): report reviewer sandbox limits as unknowns, never as findings

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
MSG
)"
```

**Verification (falsifiable):** at this task's starting commit both new test methods fail — `grep -c 'roughly 28 minutes' home/common/claude-code/skills/codex-collaboration/SKILL.md` is 0 and `grep -c '~14 min' …/SKILL.md` is 1, the exact inverse of what Step 6 requires — so Step 2's observed failure is real and Step 6 cannot pass without the edits. Scope any diff inspection to this task's files (`git diff --stat "$BASE_SHA"..HEAD -- home/common/claude-code/skills/codex-collaboration home/common/agent-skills/tests/test_workflow_skill_contracts.py`); never grade the whole commit range, which also carries the spec and plan commits.

**Not verified here, deliberately:** the collaboration evals are plan-only prose fixtures graded by hand against a model. This task pins their text and claims nothing about how a model scores against them.
