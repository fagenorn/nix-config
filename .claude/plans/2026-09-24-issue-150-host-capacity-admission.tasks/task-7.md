# Task 7: Entry paths — Claude adapter, `from-issue` direct route, Codex stub, docs

**Files:**
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`, `home/common/claude-code/skills/orchestrate-issues/evals/evals.json`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md` (explicit durable interactive acquisition)
- Create: `home/common/codex/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/codex/default.nix`, `CLAUDE.md`, `justfile` (`agent-installed-skill-tests`)
- Test: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes (Tasks 1, 4, 5): `workflow-state host-route` and its typed result; control interface 3 (`host_route`, `admission` with `waiting`); owner observation state `launch_refused`.
- Produces: skill prose only; the Codex stub at `~/.agents/skills/orchestrate-issues` (per D10, D25).

**Invariants:**
- The adapter never calculates slots or alters `max_parallel`; the `admission` report is rendering data only; the retired policy anchors in `test_dispatcher_is_a_control_adapter_not_a_policy_owner` stay absent from §2–§4 (per D9).
- The owner, remainder and bootstrap objects stay interface 2; only the control request and response say 3 (per D8).
- The Codex stub never drives control, spawns, counts threads, archives sessions, starts an app-server or retries; its result shape lives only in `host-route` (per D9, D10, D14).

- [ ] **Step 1: Write the failing tests**

In `T/test_workflow_skill_contracts.py` add beside the existing constants:

```python
V3_CONTROL_REQUEST_KEYS = V2_CONTROL_REQUEST_KEYS | {"host_route"}
CODEX_ORCHESTRATE = REPO_ROOT / "home/common/codex/skills/orchestrate-issues/SKILL.md"
CODEX_MODULE = REPO_ROOT / "home/common/codex/default.nix"
```

Change `test_direct_and_control_requests_are_interface_two`: the §3 block must satisfy
`(set(request), request["interface_version"], request["host_route"]) == (V3_CONTROL_REQUEST_KEYS, 3, "claude-code")`
(with `request = json_block(decide)`), and assert `'`host_route: "direct"`'` is in the
normalized durable section. Extend the anchor tuple in
`test_lifecycle_calls_are_single_stdin_commands_on_interface_two` with
`"interface_version 3", "host-route", "launch_refused"`. Add to `WorkflowSkillContractsTest`:

```python
    def test_orchestrate_asks_the_host_route_first_and_never_retries_a_refusal(self):
        resolve = normalized(self.section(self.orchestrate,
            "## 1. Resolve issue set and bindings", "## 2. Bootstrap and observe"))
        self.assert_ordered(resolve, "workflow-state host-route --route claude-code",
                            "--boundary workflow-response",
                            "`unsupported` answer ends the run", "`alternative`",
                            '`host_route: "claude-code"`', "never calculates slots")
        for retired in ("Treat known host capacity as a capability boundary",
                        "This does not add reservation"):
            self.assertNotIn(retired, normalized(self.orchestrate))
        observe = normalized(self.section(self.orchestrate,
            "## 2. Bootstrap and observe", "## 3. Decide"))
        self.assertIn("`launch_refused` for an owner launch the host refused", observe)
        decide = normalized(self.section(self.orchestrate,
            "## 3. Decide", "## 4. Execute control actions"))
        self.assertIn("interface_version 3 control response", decide)
        self.assertIn("`admission`", decide)
        execute = normalized(self.section(self.orchestrate,
            "## 4. Execute control actions", "## 5. Final report"))
        self.assert_ordered(execute, "host refuses an owner launch, never retry it",
                            "exactly one control call", "`launch_refused`")
        report = normalized(self.orchestrate.split("## 5. Final report", 1)[1])
        self.assertIn("`admission.waiting` as queued for agent slots", report)
        self.assertIn("bounded summaries in the same interface_version 3 control response",
                      report)
        self.assertNotIn("interface_version 2 summaries", report)

    def test_codex_orchestrate_stub_relays_the_unsupported_route(self):
        raw = CODEX_ORCHESTRATE.read_text(encoding="utf-8")
        self.assertTrue(raw.startswith("---\nname: orchestrate-issues\n"))
        text = normalized(raw)
        self.assert_ordered(text, "workflow-state host-route --route codex",
                            "--boundary workflow-response", "verbatim",
                            "/from-issue <n> --auto", "one at a time")
        self.assertIn("Never spawn owners, count threads, archive sessions, start an "
                      "app-server, or retry", text)
        for forbidden in ("workflow-state control", "init-run", "run_in_background",
                          "agent-dispatch"):
            self.assertNotIn(forbidden, text)
        self.assertIn('home.file.".agents/skills/orchestrate-issues".source = '
                      './skills/orchestrate-issues;', CODEX_MODULE.read_text(encoding="utf-8"))
        self.assertFalse((REPO_ROOT / "home/common/agent-skills/skills/orchestrate-issues")
                         .exists())
```

And a new module-level class:

```python
class InstalledOrchestrateRoutesTest(unittest.TestCase):
    """D25: each agent's installed tree holds its own orchestrate-issues."""

    @classmethod
    def setUpClass(cls):
        root = os.environ.get("AGENT_SKILLS_INSTALLED_HOME")
        if root is None:
            raise unittest.SkipTest("AGENT_SKILLS_INSTALLED_HOME is unset; run "
                                    "`just agent-installed-skill-tests`")
        cls.root = Path(root)

    def test_codex_tree_holds_the_stub_and_claude_tree_the_adapter(self):
        installed = lambda tree: (self.root / tree / "orchestrate-issues/SKILL.md"
                                  ).read_text(encoding="utf-8")
        self.assertEqual(installed(".agents/skills"),
                         CODEX_ORCHESTRATE.read_text(encoding="utf-8"))
        self.assertEqual(installed(".claude/skills"), ORCHESTRATE.read_text(encoding="utf-8"))
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -4`
Expected: FAIL — the 17-key v2 block, missing anchors, and no Codex stub.

- [ ] **Step 3: Implement**

`OI/SKILL.md`:
1. §1 — replace the paragraph beginning "Treat known host capacity as a capability boundary" with:

   > Before `init-run`, ask for the host route once and validate the answer at the boundary:
   >
   > ```text
   > workflow-state host-route --route claude-code | artifact-budget validate-report --boundary workflow-response --input -
   > ```
   >
   > An `unsupported` answer ends the run: render that validated result and its `alternative` as the final report and stop, dispatching nothing. A `supported` answer means every control request carries `host_route: "claude-code"`. The runtime reserves each owner's worker and reviewer slots before it returns a dispatch; the adapter never calculates slots, alters `max_parallel`, creates competing owners or nested relays, or repeats a rejected launch, and it reads the response's `admission` report as rendering data only.

   (Unquote the blockquote when pasting; keep the fence as a `text` block.)
2. §2 — after the sentence ending "for that exact issue, attempt, and launch identity.", add: "Its `state` is `unavailable` for an owner that died and `launch_refused` for an owner launch the host refused."
3. §3 — the JSON block gains `"host_route": "claude-code",` after `"interface_version": 3,`; "Every control call sends exactly this interface_version 2 request" → "interface_version 3"; "Accept only the validated interface_version 2 control response with its bounded `run_id`, `now`, `summaries`, `deltas`, `actions`, and `next_deadline` fields." → "Accept only the validated interface_version 3 control response with its bounded `run_id`, `now`, `summaries`, `deltas`, `actions`, `next_deadline`, and `admission` fields."
4. §4 — after the paragraph that records the host task handle, add: "If the host refuses an owner launch, never retry it: make exactly one control call carrying a `launch_refused` owner observation for that action's `custody`, and execute that response. The runtime parks the refused owner and dispatches it again only after another owner's claim is released."
5. §5 — "Render a `finalize` action from the bounded interface_version 2 summaries in the same control response." → "Render a `finalize` action from the bounded summaries in the same interface_version 3 control response." (the summaries are unchanged; only the response they ride in moved to 3). After the per-issue table sentence, add: "List every issue in the finalize response's `admission.waiting` as queued for agent slots, with its summary state."
6. Notes — append: "Codex has its own `orchestrate-issues` stub, which answers with `workflow-state host-route --route codex` and names `/from-issue <n> --auto`."

`OI/evals/evals.json`: eval 1's "Send the exact 17-key interface_version 2 control request with ordered issues" → "Send the exact 18-key interface_version 3 control request, with host_route claude-code, ordered issues", and prefix its "Resolve issue numbers" sentence with "Before init-run, ask workflow-state host-route --route claude-code once and validate it; an unsupported answer is the final report." Eval 3 becomes `name` `host-capacity-is-admitted-by-the-runtime`, `prompt` "Plan-only: the host refuses to launch an issue owner because it already runs its maximum number of agents. Explain how orchestrate-issues responds.", `expected_output` "Before init-run the adapter asks workflow-state host-route --route claude-code once and validates it at the workflow-response boundary; an unsupported answer and its alternative are the final report. Every interface_version 3 control request carries host_route claude-code, and the runtime reserves each owner's worker and reviewer slots before returning a dispatch. A rejected owner launch is never retried: the adapter makes exactly one control call with a launch_refused owner observation for that action's custody and executes the response; the runtime parks that owner and re-dispatches it only after another claim is released. The adapter never calculates slots, alters max_parallel, creates competing owners or nested relays, or polls; issues in admission.waiting are reported as queued for agent slots."

`SK/from-issue/SKILL.md` durable section: "Then send the interface-2 control request — orchestrate-issues' exact 17-key shape, with `max_parallel: 1`," → "Then send the interface-3 control request — orchestrate-issues' exact 18-key shape, with `host_route: "direct"`, `max_parallel: 1`," (rest unchanged).

`home/common/codex/skills/orchestrate-issues/SKILL.md` (exactly):

````markdown
---
name: orchestrate-issues
description: Codex answer for "orchestrate issues X, Y, Z" — reports that multi-owner orchestration is unsupported on Codex and names the sequential /from-issue route. Never launches owners.
---

# orchestrate-issues — unsupported on Codex

Codex has no orchestration adapter: native Codex collaboration exposes no
pre-launch slot claim and no owner-completion event that `workflow-state` could
bind. Answer with the host's typed result instead of improvising a scheduler.

1. Run this once (if the bare `workflow-state` name does not resolve on PATH,
   use `~/.agents/bin/workflow-state`):

   ```text
   workflow-state host-route --route codex | artifact-budget validate-report --boundary workflow-response --input -
   ```

2. Return the validated result verbatim.
3. Name the supported sequential route: run `/from-issue <n> --auto` for each
   requested issue, one at a time, in the caller's order.

Never spawn owners, count threads, archive sessions, start an app-server, or
retry this answer.
````

`home/common/codex/default.nix`, after the skills comment:

```nix
  # Codex-only `orchestrate-issues`: Claude's adapter is linked into
  # ~/.claude/skills; this stub relays `workflow-state host-route --route codex`
  # instead. A whole-directory link, because Codex ignores a skill whose SKILL.md
  # is itself a symlink.
  home.file.".agents/skills/orchestrate-issues".source = ./skills/orchestrate-issues;
```

`CLAUDE.md` (per D17): in the "Two skills stay out of the shared tree" bullet, after "…so a Codex session runs `/from-issue` per issue instead.", add "Codex gets its own `orchestrate-issues`: a stub in `home/common/codex/skills/`, linked by the Codex module as the whole directory `~/.agents/skills/orchestrate-issues`, that relays `workflow-state host-route --route codex` (declared unsupported) and names `/from-issue <n> --auto` per issue." After the "Delivery objects are built" bullet, add the bullet: "Orchestration admission is declared, not measured: `home/common/agent-skills/host-declaration.json` (installed as `~/.agents/share/host-declaration.json`, validated by `host_admission.py`) gives each orchestration route its support and its `agent_slots` — the concurrent agents one root session may run: the controller plus each owner's owner, worker and reviewer. `workflow-state control` claims an owner's whole role set against that budget before dispatching it, `workflow-state host-route` returns the typed supported/unsupported answer, and the conformance check `host.admission.declaration` reports the declaration. It is no CPU, memory or build-load figure (`.out-of-scope/host-contention-scheduling.md`)."

`justfile` `agent-installed-skill-tests`: the unittest invocation also runs `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (per D25).

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py 2>&1 | tail -3`
Expected: `OK` (the installed classes skip).

Run: `just agent-installed-skill-tests 2>&1 | tail -3`
Expected: `OK` with `InstalledOrchestrateRoutesTest` run, not skipped (it builds first; the `.agents/skills/orchestrate-issues` link is absent at the base commit).

Run: `just agent-model-matrix`
Expected: exit 0 and `agent model matrix: valid`.

Run: `grep -c 'host-declaration.json' CLAUDE.md`
Expected: `1` or more (`0` at the base commit).

Run: `just agent-workflow-tests 2>&1 | tail -3`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add home/common/claude-code/skills/orchestrate-issues home/common/agent-skills/skills/from-issue/SKILL.md \
  home/common/codex/skills/orchestrate-issues/SKILL.md home/common/codex/default.nix CLAUDE.md justfile \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "docs(skills): drive orchestration admission and give Codex a typed unsupported answer (#150)"
```
