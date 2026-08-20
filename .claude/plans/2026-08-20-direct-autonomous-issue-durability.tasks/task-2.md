# Task 2: Route direct autonomous from-issue through durable acquisition

**Files:**
- Modify: `.claude/specs/2026-08-19-workflow-control-plane-design.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1's strict `workflow-state direct-owner --repo-root <root> --request-file <absolute-path>` command and its `observe | owner | terminal` responses; the existing tracker/worktree adapters; the existing dispatcher lifecycle envelope; D2/D6/D8–D10/D12/D13/D15.
- Produces: one explicit `### Direct autonomous acquisition` adapter contract in `from-issue/SKILL.md` and matching false-by-default authorization rules in `AUTO.md`.
- Preserves: dispatcher-envelope adoption without `direct-owner`; ordinary interactive direct ledger-free behavior; explicit durable interactive `init-run`/`control`; Phase 0–7, `progress`, `finish`, and terminal-return contracts after an owner response is adopted.

**Invariants:**
- Invocation selection is exhaustive and ordered: supplied dispatcher envelope wins unchanged; `--auto` without an envelope uses only `direct-owner`; interactive direct without explicit durability remains ledger-free; existing explicit durable interactive use remains `init-run` plus `control`.
- Before the first direct call, resolve the immutable absolute ledger repository root, attempt budget, issue, and current UTC instant through existing bindings/adapters. Each call writes an absolute temporary request file with exactly the version-1 fields and passes only that file/root to `direct-owner`.
- Always send both flags. Default both to false. Set `owner_unavailable` true only when the current user instruction explicitly authorizes takeover of the currently discovered unexpired active attempt; set `new_run` true only when it explicitly authorizes a new run after terminal replay. Never infer either from restart, missing/silent process state, active ledger, tracker reopening, terminal response, or a request to continue.
- On `observe`, accept only the three exact requirement shapes. Query tracker only for `tracker`; inspect exactly the returned path only for `recorded_worktree`; reserve and verify one absent issue-branch candidate only for `candidate_worktree`. For the duration of this acquisition, retain every observation kind the helper has requested and carry all collected facts into each later strict request, refreshing a value when its external state may have changed; never send a fact kind before the helper requests it. Clear the observation set on `owner`, `terminal`, or failure. Call again and fail loudly on unknown/duplicate/malformed requirements (per D15).
- On `owner`, validate the exact closed shape, adopt `ledger_repo_root`, run, issue, attempt, owner, action ID, worktree, handoff, deadline, and launch kind as the invocation's lifecycle identity, then continue the existing Phase 0–7 owner flow. Do not spawn or reserve another owner/worktree.
- On `terminal`, validate and return the compact response unchanged to the caller, stop before Phase 1, and install no wait observer. A loud helper error is surfaced; it is never bypassed through `init-run`, `control`, a fabricated envelope, or the ledger-free path.
- Direct acquisition never consumes or interprets dispatcher summaries, deltas, wait IDs, `wait`, or `finalize`. Dispatcher and explicit-durable interactive prose retain their existing bounded `init-run`/`control` behavior.
- Handoff and Phase-1 worktree prose are acquisition-mode-specific: dispatcher-owned resumptions arrive only through `control`; direct autonomous resumptions arrive through the persisted `direct-owner` envelope; only ledger-free interactive direct creates an ordinary worktree. A direct autonomous owner always adopts the exact returned path, including a retained handoff/retry path.
- Amend the accepted issue-47 control-plane spec inline to state that issue 73 supersedes only its blanket direct-standalone paragraph: direct autonomous now uses `direct-owner`, while interactive ledger-free and explicitly durable interactive behavior remain as described.
- Contract tests assert behavior-bearing wording and ordered branches, not incidental line counts. Prose added to the live skill states the implemented behavior precisely and contains no placeholder.

- [ ] **Step 1: Write failing invocation-routing and adapter-loop contract tests**

Add the following complete tests to `WorkflowSkillContractsTest`:

```python
    def test_direct_auto_acquires_only_through_direct_owner(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        direct = self.section(
            identity, "### Direct autonomous acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assert_ordered(
            identity,
            "### Dispatcher-owned acquisition",
            "### Direct autonomous acquisition",
            "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assertIn("workflow-state direct-owner", direct)
        self.assertIn("--repo-root <ledger_repo_root>", direct)
        self.assertIn("--request-file <absolute-json-path>", direct)
        self.assertNotIn("workflow-state init-run", direct)
        self.assertNotIn("workflow-state control", direct)
        self.assertNotIn("wait envelope", direct)

    def test_direct_auto_observe_owner_terminal_loop_is_closed(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        direct = self.section(
            identity, "### Direct autonomous acquisition",
            "### Explicit durable interactive acquisition",
        )
        self.assert_ordered(
            direct,
            "kind: observe",
            "tracker",
            "recorded_worktree",
            "candidate_worktree",
            "retain every fact previously requested during this acquisition",
            "carry all collected facts into each later strict request",
            "never send a fact kind before the helper requests it",
            "call `direct-owner` again",
            "kind: owner",
            "adopt",
            "kind: terminal",
            "return",
        )
        for field in (
            "ledger_repo_root", "run_id", "issue", "attempt", "owner",
            "action_id", "launch_kind", "worktree", "handoff_path",
            "deadline_at",
        ):
            self.assertIn(field, direct)
        self.assertIn("unknown", direct)
        self.assertIn("fail loudly", direct)
        self.assertIn("no waiter", direct)

    def test_direct_auto_authorizations_are_explicit_and_never_inferred(self):
        combined = self.from_issue + "\n" + self.auto
        for flag in ("new_run", "owner_unavailable"):
            self.assertIn(flag, self.from_issue)
            self.assertIn(flag, self.auto)
        self.assertIn("both flags", combined)
        self.assertIn("false", combined)
        for forbidden_inference in (
            "restart", "missing process handle", "silence", "active ledger",
            "terminal replay", "reopened tracker", "desire to continue",
        ):
            self.assertIn(forbidden_inference, combined)
        self.assertIn("current user instruction explicitly authorizes", combined)

    def test_adjacent_from_issue_acquisition_modes_remain_unchanged(self):
        identity = self.section(
            self.from_issue, "## Lifecycle identity", "## The flow"
        )
        dispatcher = self.section(
            identity, "### Dispatcher-owned acquisition",
            "### Direct autonomous acquisition",
        )
        interactive = self.section(
            identity, "### Interactive direct acquisition",
            "### Explicit durable interactive acquisition",
        )
        durable = self.section(
            identity, "### Explicit durable interactive acquisition",
            "The `workflow-state` executable",
        )
        self.assertIn("adopt", dispatcher)
        self.assertNotIn("direct-owner", dispatcher)
        self.assertIn("ledger-free", interactive)
        self.assertNotIn("direct-owner", interactive)
        self.assert_ordered(
            durable, "workflow-state init-run", "bounded `requirements`",
            "max_parallel: 1", "workflow-state control", "first `spawn` envelope",
        )
        self.assertNotIn("direct-owner", durable)
```

Revise the existing `test_owner_lifecycle_is_optional_for_direct_use_and_covers_all_stops` and `test_from_issue_standalone_modes_use_live_lifecycle_interfaces` assertions so they select the new named subsections and retain all assertions about immutable ledger root, exact worktree identity, `progress`, `finish`, and terminal persistence. Do not weaken an existing assertion merely because headings moved.

Replace the global handoff/worktree assertions with acquisition-specific contracts:

```python
    def test_from_issue_handoff_resume_is_acquisition_mode_specific(self):
        phase_gate = self.section(
            self.from_issue, "## Dispatch, phase-budget and attempt-budget rules",
            "## Terminal return procedure",
        )
        self.assertIn("dispatcher-owned", phase_gate)
        self.assertIn("returned `resume` envelope", phase_gate)
        self.assertIn("direct autonomous", phase_gate)
        self.assertIn("persisted `direct-owner` owner envelope", phase_gate)
        self.assertNotIn("workflow-state launch", phase_gate)

    def test_lifecycle_phase_one_paths_are_acquisition_mode_specific(self):
        phase_one = self.section(self.from_issue, "## Phase 1", "## Phase 2")
        self.assert_ordered(
            phase_one,
            "dispatcher-owned or direct-autonomous lifecycle envelope",
            "use its exact absolute `worktree`",
            "**Absent** from both the filesystem",
            "checked out on this issue's branch",
            "adopt it",
            "Do not re-create it, do not move it, do not reset it",
            "a different branch",
            "fail the attempt through the terminal return procedure",
            "never choose another path",
        )
        self.assertIn("fail the attempt", phase_one)
        self.assert_ordered(
            phase_one,
            "No lifecycle acquisition falls through to ordinary worktree creation",
            "ledger-free interactive direct",
            "standard `worktrees` flow",
        )
```

The revised assertions must prove that dispatcher-owned handoffs name `control`, direct autonomous handoffs name `direct-owner`, and neither route falls through to ordinary worktree creation.

- [ ] **Step 2: Run the focused contract tests and confirm the new routing prose is absent**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -v`

Expected: FAIL in the new subsection/routing tests because direct standalone currently describes only ledger-free and explicit durable interactive routes; all unrelated workflow contracts remain green.

- [ ] **Step 3: Rewrite lifecycle acquisition as four explicit invocation-shape branches**

Within `## Lifecycle identity` in `from-issue/SKILL.md`, preserve the shared exact lifecycle identity rules and replace the ambiguous direct-standalone paragraphs with these behavior-complete subsections:

1. `### Dispatcher-owned acquisition`: when all five dispatcher envelope fields are supplied, validate/adopt them unchanged and never call `direct-owner`.
2. `### Direct autonomous acquisition`: when the invocation contains literal `--auto` and has no envelope, resolve the immutable ledger repository root, construct the strict request with injected current UTC and configured attempt budget, send both false-by-default authorization flags, and loop only on the helper's closed response discriminator. Spell out exact requirement-to-adapter mapping, retain/resend all previously requested observation kinds within the current acquisition without inventing an unrequested kind (per D15), and spell out owner-field adoption. State that terminal returns unchanged with no waiter and helper refusal is terminal for acquisition, not a fallback signal.
3. `### Interactive direct acquisition`: without `--auto` or an explicit durability request, retain the ordinary ledger-free worktree flow and compact direct return.
4. `### Explicit durable interactive acquisition`: preserve the current `init-run` bootstrap, normalized tracker/worktree request with `max_parallel: 1`, `control`, exact single `spawn` adoption, and no-waiter behavior.

In `AUTO.md`, add the exact exceptional-authorization rule beside the self-answer/lifecycle rules: both fields are always present and false unless the current instruction explicitly authorizes that exact transition; self-answering cannot infer authority from any process/tracker/terminal observation. Keep `progress` at every phase checkpoint and `finish` before notification unchanged.

Audit the adjacent live sections rather than stopping at Lifecycle identity:

- In the phase-budget handoff branch, say a dispatcher-owned owner is relaunched only from `control`'s returned `resume` envelope, while a direct autonomous restart reacquires the handed-off attempt through the persisted `direct-owner` owner envelope.
- In Phase 1, apply exact-path adopt/create/fail handling to both dispatcher-owned and direct-autonomous lifecycle envelopes; reserve the standard `worktrees` flow for ledger-free interactive direct invocations.
- In `.claude/specs/2026-08-19-workflow-control-plane-design.md`, add an issue-73 inline amendment beside the blanket direct-standalone paragraph, preserving its interactive and explicitly durable branches but replacing direct autonomous acquisition with `direct-owner` (per D13).

- [ ] **Step 4: Verify focused skill behavior**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -v`

Expected: PASS; direct autonomous, dispatcher-owned, interactive ledger-free, and explicit durable interactive assertions all pass, with no retired `launch`/`reconcile` prose introduced.

- [ ] **Step 5: Run the complete repository verification gates**

Run: `just agent-workflow-tests`

Expected: exit 0; helper behavior, direct acquisition, existing dispatcher policy, and every workflow skill contract pass.

Run: `just build`

Expected: exit 0; Nix evaluation/build publishes the modified helper and `from-issue` package through the existing wiring.

- [ ] **Step 6: Verify the owned diff and commit the adapter tracer**

Run: `git diff --check -- .claude/specs/2026-08-19-workflow-control-plane-design.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: exit 0 with no output. Then inspect `git diff --stat --` with the same four pathspecs; the dispatcher skill, Nix wiring, and any unrelated skill are unchanged.

```bash
git add .claude/specs/2026-08-19-workflow-control-plane-design.md home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(issue-73): adopt durable direct owner state" -m "Co-Authored-By: Codex <noreply@openai.com>"
```

The task is complete only after its full-lane SDD review reports both spec compliance and quality clean (or clean after its scoped fix/re-review loop). After this task, SDD must run its two independent final axes and the controller must rerun `just agent-workflow-tests` and `just build` at the final reviewed HEAD.
