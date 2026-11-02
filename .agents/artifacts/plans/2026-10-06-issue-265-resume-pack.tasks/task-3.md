# Task 3: Relauncher and owner guidance, contract test, CLAUDE.md and ceilings

Lane: full (instructions that drive lifecycle owners). Decisions: per D2, D8,
D9, D14 and D16 of the spec's ledger. Read the spec's "Who puts the pack in the
prompt" and "What the relaunched owner does with it" sections first.

**Files:**
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/instruction-load.json`
- Modify: `CLAUDE.md`
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Tasks 1–2, on this branch): the verb
  `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`,
  its exit-0 pack with `action_id`, `current`, `worktree.head`,
  `worktree.dirty_paths` and `next_action` (`read_handoff`, `reorient`,
  `resume_task`, `finish_phase`, `start_phase`), and its exit-2 refusals. The
  pack is not a `workflow-response` document: the closed validator in
  `home/common/agent-skills/scripts/delivery_model/_wire.py` rejects its
  kind, so no skill pipes it through `validate-report` (per D16).
- Produces: nothing later tasks consume; this is the last task.

**Invariants:**
- Every dictated sentence describes the code merged in Tasks 1–2. Before
  committing, check each clause against `command_resume_pack`,
  `resume_pack_attempt` and `resume_next_action`; where they differ, the code
  wins: correct the sentence and say so in your report.
- Shell examples stay single plain commands (the shell-example contract);
  every `workflow-state resume-pack` example is the exact command line above
  with `<action_id>` or `<action-id>` as in the surrounding file.
- Existing contract classes stay green unedited, in particular the
  orchestrate-issues prompt-field test and `LaunchFencedWorkerContractsTest`.
- No instruction-load profile exceeds its ceiling.

## Steps

- [ ] **Step 1: Write the failing contract test**

Append to `home/common/agent-skills/tests/test_workflow_skill_contracts.py`,
directly after `ProgressMarkerContractsTest`:

```python
class ResumePackContractsTest(unittest.TestCase):
    """#265: relaunchers carry a resume pack and owners verify it before use."""

    PACK = ("workflow-state resume-pack --repo-root <ledger_repo_root> "
            "--run-id <run-id> --action-id <action_id>")
    DISPATCHER_PACK = ("workflow-state resume-pack --repo-root <ledger_repo_root> "
                       "--run-id <run-id> --action-id <action-id>")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            next_position = text.find(anchor, position + 1)
            self.assertGreaterEqual(next_position, 0, anchor)
            position = next_position

    @staticmethod
    def read(path):
        return normalized(path.read_text(encoding="utf-8"))

    def test_both_skills_exempt_the_pack_from_workflow_response_validation(self):
        self.assert_ordered(
            self.read(ORCHESTRATE), "untrusted transport",
            "and validate before decoding any field.",
            "The one exception is `resume-pack`", "is not a workflow response",
            "never pipes or decodes it", "## 1. Resolve issue set and bindings")
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Lifecycle identity", "untrusted transport",
            "and validate before decoding.", "The one exception is `resume-pack`",
            "is not a workflow response", "the checks in `### Resume pack`",
            "### Dispatcher-owned acquisition")

    def test_from_issue_defers_the_auto_read_on_a_pack_carrying_relaunch(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Files beside this one",
            "Read it *once*, now, only if the invocation contains the literal token `--auto`.",
            "When the prompt carries a resume pack, defer that read",
            "limits it to the sections that subsection names",
            "restores the whole read", "## Lifecycle identity")

    def test_orchestrate_adds_the_pack_to_resume_prompts_only(self):
        self.assert_ordered(
            self.read(ORCHESTRATE), "## 4. Execute control actions",
            "For a `resume` action", self.DISPATCHER_PACK,
            "add its stdout verbatim to the owner prompt's `Resume pack` paragraph",
            "never stops the dispatch", "`spawn` and `retry` carry no pack",
            "> `<canonical-json>`", "> Resume pack", "> `<resume-pack-json>`",
            "## 5. Final report")

    def test_from_issue_owner_verifies_the_pack_and_reads_only_the_phase(self):
        self.assert_ordered(
            self.read(FROM_ISSUE), "## Lifecycle identity",
            "### Resume pack A relaunched owner's prompt may carry a resume pack",
            self.PACK, "an accelerator, never a gate", "not a workflow response",
            "still resolves the project once", "runs `check-launch`",
            "`#### Fresh delegated owner` check",
            "`git -C <worktree> rev-parse HEAD` must equal `worktree.head`",
            "re-orient in full",
            "A verified pack replaces only your own ad-hoc re-orientation",
            "do not dump the ledger", "re-validate the plan",
            "read only the skill sections its phase needs",
            "this file's `## Phase <n>` section", "(not the whole file)",
            "`sdd` for Phase 6", "`ship-issue` for Phase 7",
            "Everything the pack does not replace still runs unchanged",
            "sdd's own `progress.md` check", "sdd's ledger wins",
            "never stops a relaunch", "## The flow")

    def test_from_issue_direct_reentry_and_delegate_carry_the_pack(self):
        text = self.read(FROM_ISSUE)
        self.assert_ordered(
            text, "### Direct autonomous acquisition", "**`kind: owner`**",
            "When its `launch_kind` is `resume`", self.PACK,
            "### Interactive direct acquisition")
        self.assert_ordered(
            text, "4. **`delegate`** —", "the fresh owner adopts this launch",
            self.PACK, "as a `Resume pack` paragraph",
            "Exception — **ledger-only remainder**")

    def test_auto_rollover_passes_the_pack_beside_the_continuation(self):
        self.assert_ordered(
            self.read(AUTO), "#### Mandatory transfer gate",
            "Beside the continuation, never inside it", self.PACK,
            "does not stop the transfer", "#### Fresh delegated owner",
            "Any mismatch stops the attempt as a contract failure.",
            "only after every check above has passed", "replaces none of them",
            "#### Earlier controller stop")

    def test_claude_md_describes_the_resume_pack(self):
        self.assert_ordered(
            self.read(REPO_ROOT / "CLAUDE.md"),
            "A relaunched owner's prompt carries a resume pack", self.PACK,
            "`read_handoff`", "`start_phase`", "`current: false` preview",
            "still runs `check-launch`")
```

- [ ] **Step 2: Run it and watch it fail**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k ResumePackContractsTest 2>&1 | tail -3`
Expected: non-zero exit and `FAILED` over the 7 cases.

- [ ] **Step 3: Write the skill prose**

1. `home/common/agent-skills/skills/from-issue/SKILL.md` — insert a new
   subsection at the end of `## Lifecycle identity`, directly before
   `## The flow`:

   ```markdown
   ### Resume pack

   A relaunched owner's prompt may carry a resume pack: the stdout of
   `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`,
   which reads the ledger, the attempt's recorded worktree and that
   worktree's SDD workspace and writes nothing. The pack is an accelerator, never a gate.
   It is not a workflow response and is never piped through `validate-report`:
   it stays untrusted until the checks below pass.
   A pack-carrying relaunch still resolves the project once, validates its
   owner object and runs `check-launch`, and obeys a `current: false` answer
   exactly as it would without a pack; a delegated owner also passes every
   `AUTO.md` `#### Fresh delegated owner` check first. Then it checks the pack
   against what it can see: the pack's `action_id` must equal the envelope's,
   `git -C <worktree> rev-parse HEAD` must equal `worktree.head`, and
   `git -C <worktree> status --porcelain` must list `worktree.dirty_paths`
   entries. On any mismatch the pack is stale: ignore it and re-orient in full.

   A verified pack replaces only your own ad-hoc re-orientation: do not dump
   the ledger, re-read git history, re-validate the plan, read the SDD
   progress log yourself, or read skills end to end. Start from its
   `next_action` and read only the skill sections its phase needs: this file's `## Phase <n>` section, the file
   beside this one that phase names, `AUTO.md`'s section governing that phase
   under `--auto` (not the whole file), and the phase's sub-skill (`sdd` for
   Phase 6, `ship-issue` for Phase 7). Everything the pack does not replace
   still runs unchanged, sdd's own `progress.md` check on entry included: that
   check stays sdd's resume mechanism, and where it disagrees with the pack's
   `resume_task`, sdd's ledger wins. `read_handoff` reads the handoff document
   at its `path`; `reorient` re-orients in full, as does a relaunch with no
   pack.

   orchestrate-issues adds the pack to `resume` prompts; this skill adds it on
   direct re-entry, on `delegate` and on `AUTO.md`'s Phase-5 rollover. A
   `resume-pack` refusal or failure only means the prompt carries no pack; it
   never stops a relaunch.
   ```

   Same file, `## Files beside this one`: after the `AUTO.md` bullet's
   sentence `Read it *once*, now, only if the invocation contains the literal
   token `--auto`.` append, in the same bullet:

   ```markdown
   When the prompt carries a resume pack, defer that read until the checks in
   `### Resume pack`: a pack that passes them limits it to the sections that
   subsection names, and one that fails them restores the whole read.
   ```

   Same file, `## Lifecycle identity`: after the sentence ending `and validate
   before decoding.` append, in the same paragraph:

   ```markdown
   The one exception is `resume-pack`: its stdout is not a workflow response
   and `validate-report` has no route for it, so it is never piped there; it
   stays an untrusted accelerator until the checks in `### Resume pack` pass.
   ```

2. Same file, `### Direct autonomous acquisition`, item 2 (`**`kind:
   owner`**`): after `Do not spawn or reserve another owner or worktree.`
   append:

   ```markdown
   When its `launch_kind` is `resume`, this re-entered session is its own
   relauncher: run
   `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
   with that `action_id` and, on exit 0, use its stdout as this relaunch's
   resume pack (`### Resume pack`).
   ```

3. Same file, `**Executable phase gate.**` item 4 (`**`delegate`**`): after
   the sentence `This is a fresh agent; it reconstructs context from those
   artifacts rather than inheriting conversation history.` append, on the
   same indented paragraph:

   ```markdown
   Before dispatching it, and because the fresh owner adopts this launch, run
   `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
   with this owner's own `action_id` and, on exit 0, put its stdout in the
   prompt as a `Resume pack` paragraph.
   ```

   Note the contract anchor `the fresh owner adopts this launch`: keep those
   words contiguous.

4. `home/common/agent-skills/skills/from-issue/AUTO.md` —
   `#### Mandatory transfer gate`: directly after the paragraph ending `it is
   never a member of the continuation object.` add:

   ```markdown
   Beside the continuation, never inside it, pass a resume pack: after
   `progress` persists `delegate`, run
   `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>`
   with this controller's own `action_id`, which the fresh owner adopts, and on
   exit 0 put its stdout in the prompt as a `Resume pack` paragraph. A refusal
   sends no pack and does not stop the transfer.
   ```

   `#### Fresh delegated owner`: directly after `Any mismatch stops the
   attempt as a contract failure.` add, as its own paragraph:

   ```markdown
   A resume pack beside the continuation is used as `SKILL.md`'s
   `### Resume pack` says, and only after every check above has passed: it
   replaces none of them.
   ```

5. `home/common/claude-code/skills/orchestrate-issues/SKILL.md` — in the
   lifecycle-call paragraph before `## 1. Resolve issue set and bindings`,
   after the sentence ending `and validate before decoding any field.`
   append:

   ```markdown
   The one exception is `resume-pack`: its stdout is not a workflow response
   and `validate-report` has no route for it, so this dispatcher never pipes or
   decodes it; it goes verbatim into the owner prompt (§4), and the owner
   checks it before use.
   ```

   Same file, `## 4.
   Execute control actions`: directly after the paragraph ending `the owner
   validates it again at the same boundary before use.` add:

   ```markdown
   For a `resume` action, after projecting the owner object, run
   `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action-id>`
   with the action's `id`; on exit 0, add its stdout verbatim to the owner prompt's `Resume pack` paragraph
   below. A refusal or helper failure omits that paragraph and never stops the
   dispatch. `spawn` and `retry` carry no pack.
   ```

   In the owner prompt block, directly after the line `> `<canonical-json>``
   add:

   ```markdown
   > Resume pack (only for a `resume` action whose `resume-pack` call exited 0;
   > use it as from-issue's `### Resume pack` says):
   > `<resume-pack-json>`
   ```

6. `CLAUDE.md` — directly after the bullet that begins `The anti-zombie bound
   counts progress, not phase changes`, add one bullet at the same level:

   ```markdown
     - A relaunched owner's prompt carries a resume pack: `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` is read-only (no lock, clock or write) and prints one `resume-pack/v1` object derived from the ledger, the attempt's recorded worktree (HEAD, uncommitted entries, commits since its `progress_marker`) and that worktree's SDD workspace, ending in a closed `next_action` (`read_handoff`, `reorient`, `resume_task`, `finish_phase` or `start_phase`). It is served for the current launch of an active attempt and as a `current: false` preview for the last launch of a suspended or handed-off one; anything else exits 2. orchestrate-issues §4 adds it to `resume` prompts, and from-issue to direct re-entry, `delegate` and the Phase-5 rollover; the pack is not a workflow response and is never piped through `validate-report`; the relaunched owner still runs `check-launch`, checks the pack's HEAD and dirtiness, and then reads only the current phase's skill sections, while sdd's own `progress.md` check still decides the task to resume (#265).
   ```

Change nothing else in these files.

- [ ] **Step 4: Raise the instruction-load ceilings**

Measure:

```bash
PYTHONPATH="$PWD/python" python3 - <<'PY'
from pathlib import Path
from agent_tools import instruction_load as il
root = Path(".").resolve()
model = il.load_model((root / il.MODEL_PATH).read_bytes())
measured = il.measure(model, il.tree_reader(root))
for profile in model["profiles"]:
    for host in profile["hosts"]:
        used = measured["profiles"][profile["id"]][host]["hot"]["bytes"]
        if used > profile["ceiling_bytes"][host]:
            print(profile["id"], host, profile["ceiling_bytes"][host], "->", used)
PY
```

For every `(profile, host)` line it prints, set that profile's
`ceiling_bytes.<host>` in `home/common/agent-skills/instruction-load.json` to
the printed measured value — no slack — and append to that profile's `note`
the sentence `Ceiling raised for #265: relaunchers carry a resume pack and the owner's resume-pack guidance (#155 D10).`
Expect some of `from-issue-controller`, `orchestration-dispatcher`,
`orchestrated-issue-owner` and `implementation-owner`; raise exactly what the
script prints. Keep the file's formatting. Re-run the script: it must print
nothing.

- [ ] **Step 5: Verify**

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `OK` (the 7 new contracts included).

Run: `set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py 2>&1 | tail -3`
Expected: `OK` (`test_the_live_tree_breaches_no_ceiling` included).

Run:
```bash
if ! grep -q 'Ceiling raised for #265' home/common/agent-skills/instruction-load.json; then exit 1; fi
```
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/from-issue/SKILL.md home/common/agent-skills/skills/from-issue/AUTO.md home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/instruction-load.json CLAUDE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): carry a resume pack on owner relaunches (#265)"
```
