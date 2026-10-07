# Task 3: Move the four acquisition routes and the resume pack into route files

**Files** (under `home/common/agent-skills/`):
- Create: `skills/from-issue/acquire-dispatcher.md`, `skills/from-issue/acquire-direct.md`, `skills/from-issue/acquire-interactive.md`, `skills/from-issue/acquire-durable.md`, `skills/from-issue/resume-pack.md`
- Modify: `skills/from-issue/SKILL.md` (`## Files beside this one`, `## Lifecycle identity` and its four `###` routes, `### Resume pack`, Phase 1's ledger-free list)
- Modify: `skills/from-issue/AUTO.md` (move its opening "Under direct autonomous acquisition, a resume is not a takeover" paragraph out)
- Modify: `instruction-load.json`
- Test: `tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 2's layout: `rollover.md`, `delegated-owner.md`, and `AUTO.md`'s headings as Task 2 lists them.
- Produces:
  - Route files, each headed by the moved `###` heading's text at `#` level: `# Dispatcher-owned acquisition`, `# Direct autonomous acquisition`, `# Interactive direct acquisition` and `# Explicit durable interactive acquisition`. `resume-pack.md` is headed `# Resume pack`.
  - `SKILL.md` keeps `## Lifecycle identity` and a `### Resume pack` stub (per D9).
  - Test constants `ACQUIRE_DISPATCHER`, `ACQUIRE_DIRECT`, `ACQUIRE_INTERACTIVE`, `ACQUIRE_DURABLE` and `RESUME_PACK`, which Task 6 reuses.

**Invariants:**
- The selector in `## Lifecycle identity` is four lines in today's order, with one condition per route (spec "Route selection is unchanged"):
  1. a complete dispatcher envelope → `acquire-dispatcher.md`;
  2. otherwise literal `--auto` → `acquire-direct.md`;
  3. otherwise an explicit request for durable orchestration → `acquire-durable.md`;
  4. otherwise → `acquire-interactive.md`.
- `## Lifecycle identity` keeps:
  - the identity paragraph (the seven fields, `--repo-root <ledger_repo_root>`, the full-path fallback, `action_id` verbatim);
  - the `launch-scope exec` and `launch-scope scratch` sentences byte for byte;
  - the lifecycle-call rule, starting "Every lifecycle call is one command that reads its input from stdin through a quoted heredoc" (per D9);
  - one clause exempting `resume-pack` stdout from `validate-report`;
  - the "the ledger … selects the next delivery stage" rule.
- Machine-read blocks keep their exact text in their new file (per D3):
  - `acquire-direct.md`: the 16-key request JSON (```` ```json ````), both ```` ```text ```` command blocks (`direct-owner`, `build-delivery --kind contract`), the five requirement shapes, and the four reply kinds with their exact field lists;
  - `acquire-durable.md`: the `init-run` / `build-delivery` / `control` argv and `host_route: "direct"`, `max_parallel: 1`, `human_directed: true`;
  - `resume-pack.md`: the `resume-pack` argv and the three equalities (`action_id`, `git -C <worktree> rev-parse HEAD` = `worktree.head`, `git -C <worktree> status --porcelain` count = `worktree.dirty_paths`).
- No route file names a sibling. A route file writes "the `## Remainder owner prompt` that `SKILL.md`'s index names for Phase 7", "the resume pack's checks" and "Phase 7", never a file name.
- `resume-pack.md` carries no per-file reading list. The always-read headings and each phase's `AUTO.md` scoping move into `SKILL.md`'s index line for `AUTO.md` and the `resume-pack.md` bullet ("Cross-file pointers go through `SKILL.md`", spec Decisions). The always-read headings are `Lifecycle identity`, `Decision ledger (artifact discipline)`, `Skill-tool invocations`, `Dispatch, phase-budget and attempt-budget rules`, `Terminal return procedure` and `Suspension procedure`.
- Byte targets (root Global Constraints): `acquire-dispatcher.md` 1,500, `acquire-direct.md` 5,500, `acquire-interactive.md` 1,000, `acquire-durable.md` 2,000, `resume-pack.md` 2,400.
- Membership follows D2.

- [ ] **Step 1: Re-point the machine-read tests (they fail until Step 3)**

Add after `FROM_ISSUE_DIR`:

```python
ACQUIRE_DISPATCHER = FROM_ISSUE_DIR / "acquire-dispatcher.md"
ACQUIRE_DIRECT = FROM_ISSUE_DIR / "acquire-direct.md"
ACQUIRE_INTERACTIVE = FROM_ISSUE_DIR / "acquire-interactive.md"
ACQUIRE_DURABLE = FROM_ISSUE_DIR / "acquire-durable.md"
RESUME_PACK = FROM_ISSUE_DIR / "resume-pack.md"
```

Replace `WorkflowSkillContractsTest.test_direct_and_control_requests_are_interface_two`. The orchestrate half is unchanged (per D13):

```python
    def test_direct_and_control_requests_are_interface_two(self):
        direct = ACQUIRE_DIRECT.read_text(encoding="utf-8")
        request = json_block(direct)
        self.assertEqual((set(request), request["interface_version"]),
                         (V2_DIRECT_REQUEST_KEYS, 2))
        for anchor in ("`delivery_contract`", "--kind contract", "`authorization_intents`",
                       "kind: delivery_remainder", "--request-file -"):
            self.assertIn(anchor, normalized(direct))
        decide = self.section(self.orchestrate, "## 3. Decide", "## 4. Execute control actions")
        request = json_block(decide)
        self.assertEqual((set(request), request["interface_version"], request["host_route"]),
                         (V3_CONTROL_REQUEST_KEYS, 3, "claude-code"))
        for anchor in ("workflow-state build-delivery",
                       "while its latest summary carries `delivery_contract_required`",
                       "report the refusal", "--request-file -",
                       "only when this invocation created the run"):
            self.assertIn(anchor, normalized(decide))
        self.assertIn('`host_route: "direct"`',
                      normalized(ACQUIRE_DURABLE.read_text(encoding="utf-8")))
```

In `test_contract_builders_state_the_resolution_root_and_relay_refusals`, delete the from-issue `direct` slice and its tuple entry. Keep the orchestrate subtest (per D13).

- [ ] **Step 2: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k direct_and_control_requests` (timeout 300 s)
Expected: ERROR, `FileNotFoundError` for `acquire-direct.md`.

- [ ] **Step 3: Move and cut**

1. Move each `###` route section of `SKILL.md` § Lifecycle identity into its file. Move `### Resume pack` into `resume-pack.md`. Then cut by the spec's content-class table:
   - helper-enforced rules become "run X; obey its reply or refusal". `acquire-direct.md` keeps one sentence for the builder seal and refusal: "a builder refusal (exit 2, empty stdout) fails loudly; report its stderr line verbatim".
   - Restated "validate before decoding" sentences go, because `## Lifecycle identity` states it once.
   - The "concrete values stand for…" sentence goes, and so do the interface-history phrases.
2. `acquire-dispatcher.md`: add one sentence saying a generic `delegate` owner receives this same envelope (per D2).
3. `acquire-direct.md`: also takes `AUTO.md`'s "Under direct autonomous acquisition, a resume is not a takeover…" paragraph. On `launch_kind: resume` it runs the `resume-pack` command and uses the pack as the resume pack's checks say.
4. `acquire-interactive.md`: the ledger-free route sentence plus Phase 1's three-step ledger-free `worktrees` flow, moved out of `## Phase 1 — Worktree`. `SKILL.md` Phase 1 keeps the lifecycle-envelope rules and points ledger-free invocations at `acquire-interactive.md`.
5. `resume-pack.md`: the pack definition, the checks in order (validate the owner object and `check-launch` first; a rollover-delegated owner passes its delegated-owner checks first; then the three equalities), what a verified pack replaces, the `next_action` handling, and the sentence "a `resume-pack` refusal only means no pack". For what to read next it says: "read the sections `SKILL.md`'s index names for your phase".
6. `SKILL.md`:
   - Replace the four `###` sections with the selector (Invariants), and `### Resume pack` with the one-line stub: "A relaunched owner whose prompt carries a resume pack follows `resume-pack.md` before using it."
   - Add one index bullet per new file, with its load condition.
   - Extend the `AUTO.md` bullet with the resume-pack scoping, per phase (per D15). At every phase an autonomous resumed owner reads `AUTO.md`'s opening, `The self-answer pattern` and `When *not* to auto-resolve`. It then adds its phase's route section: `Phases 2–4 run as subagents` for Phases 2–4; for Phases 5–7, `Other Phase 5–7 routes` with `Interface_version 2 delivery relay`, except that the direct-autonomous controller at Phase 5 reads `rollover.md` and the delegated owner reads `delegated-owner.md` in place of `Other Phase 5–7 routes` (each still with `Interface_version 2 delivery relay`).

- [ ] **Step 4: Delete the prose pins on the moved text**

Apply D11 and D13 to these `WorkflowSkillContractsTest` methods:
- `test_lifecycle_phase_one_paths_are_acquisition_mode_specific`
- `test_from_issue_handoff_resume_is_acquisition_mode_specific`
- `test_from_issue_standalone_modes_use_live_lifecycle_interfaces`
- `test_direct_auto_acquires_only_through_direct_owner`
- `test_direct_auto_observe_owner_terminal_loop_is_closed`
- `test_direct_auto_authorizations_are_explicit_and_never_inferred`
- `test_adjacent_from_issue_acquisition_modes_remain_unchanged`
- `test_dispatcher_answers_a_contract_request_with_one_rule`

Also apply them to every `ResumePackContractsTest` method, and to `LaunchScopeWiringContractsTest.test_the_owner_runs_long_commands_through_exec`. That test keeps `"## Lifecycle identity"`, `OWNER_EXEC` and `OWNER_SCRATCH` in order, ends its slice at `"### Resume pack"`, and drops its English anchors.

How to treat each assertion:
- Keep and re-point the JSON key sets and the requirement shapes (`{"kind":"tracker"}` …).
- Keep the closed reply-kind values, the field lists and the argv orderings, re-pointed to the route file now holding them.
- Delete every English-phrase assertion.

- [ ] **Step 5: Models**

`instruction-load.json` (per D2):
- `from-issue-controller`:
  - `hot` + `from-issue/acquire-direct.md`;
  - `conditional` + `from-issue/acquire-interactive.md`, `from-issue/acquire-durable.md`, `from-issue/resume-pack.md`;
  - unread `"from-issue/acquire-dispatcher.md": "a controller invocation carries no dispatcher envelope"`.
- `orchestrated-issue-owner`:
  - `hot` + `from-issue/acquire-dispatcher.md`;
  - `conditional` + `from-issue/resume-pack.md`;
  - unread `acquire-direct.md`, `acquire-interactive.md` and `acquire-durable.md`, each with the reason `"an orchestrated owner acquires only through its dispatcher envelope"`.
- `implementation-owner`:
  - `conditional` + `from-issue/acquire-dispatcher.md`, `from-issue/resume-pack.md`;
  - unread `acquire-direct.md`, `acquire-interactive.md` and `acquire-durable.md`, each with the reason `"a delegated owner adopts its delegator's identity and performs no acquisition"`.

Run `just agent-instruction-load tighten` (timeout 300 s). Then run `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Each conditional ceiling of C, O and I that it reports as breached is set to the reported measure (per D12). Write each one as a `raise:` line in the commit body.

- [ ] **Step 6: Verify**

Run the focused suite. Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
python3 - <<'EOF'
from pathlib import Path
F = Path("home/common/agent-skills/skills/from-issue")
caps = {"acquire-dispatcher.md": 1500, "acquire-direct.md": 5500, "acquire-interactive.md": 1000,
        "acquire-durable.md": 2000, "resume-pack.md": 2400}
for name, cap in caps.items():
    size = len((F / name).read_bytes())
    if size > cap:
        print(f"over target: {name} {size} > {cap} (name it in the commit body)")
skill = (F / "SKILL.md").read_text(encoding="utf-8")
identity = skill[skill.index("## Lifecycle identity"):skill.index("### Resume pack")]
order = [identity.index(n) for n in ("acquire-dispatcher.md", "acquire-direct.md",
                                     "acquire-durable.md", "acquire-interactive.md")]
assert order == sorted(order), "selector order changed"
for heading in ("### Dispatcher-owned acquisition", "### Direct autonomous acquisition",
                "### Interactive direct acquisition", "### Explicit durable interactive acquisition"):
    assert heading not in skill, heading
EOF
```

Expected: exit 0, with any `over target` line named in the commit body. At Task 2's head it fails, because the route files are absent.

- [ ] **Step 7: Commit**

Commit as `refactor(from-issue): move the acquisition routes and the resume pack into route files (#295)`, with one `raise:` body line per conditional raise.
