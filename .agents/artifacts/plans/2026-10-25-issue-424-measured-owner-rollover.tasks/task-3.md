# Task 3: Owners and the once-per-crossing instruction

Spec § Owners and the crossing, § Failure posture; per D6, D8, D9, D10, D14 and D15. The meter learns which agents are owners, keeps one state file per owner under an exclusive `flock`, and injects one instruction per crossing of the hand-off threshold.

**Files:**
- Create: `python/agent_tools/context_meter_crossing.py`
- Modify: `python/agent_tools/context_meter_commands.py` (adds `registers_owner`)
- Modify: `python/agent_tools/context_meter.py` (`respond` gains the owner path; `main` passes the state dir and threshold)
- Modify: `python/agent_tools/phase_budget.py` (docstring only: the meter also reads it)
- Test: `tests/test_context_meter.py` (adds `CrossingTest`)

**Interfaces:**
- Consumes (Task 1): `lex`, `progress_starts`, `simple_command_end`, `Token`, `AgentIdentity`, `agent_identity`, `measure`, `Measurement`, `respond`, `MEASURED_NOTE`. (Task 2): `phase_budget.CONTEXT_CEILING`, `phase_budget.CONTEXT_HEADROOM`.
- Produces:
  - `context_meter_commands.registers_owner(tokens: Sequence[Token]) -> bool`.
  - `context_meter_crossing`: `state_dir(home: Path) -> Path` (`home / ".agents" / "state" / "context-meter"`); `state_path(directory: Path, identity: AgentIdentity) -> Path` (`<session_id>.main.json` for a main session, `<session_id>.agent-<agent_id>.json` for a subagent); `is_owner(directory: Path, identity: AgentIdentity) -> bool`; `record(directory: Path, identity: AgentIdentity, *, register: bool, measured: int | None, progress: bool, threshold: int) -> bool` (True when the instruction is due).
  - `context_meter.respond(payload: object, *, state_dir: Path, threshold: int) -> dict | None` (replaces Task 1's one-argument form) and `CROSSING_NOTE` below.

**Invariants:**
- An agent is an owner once a call carries a registering command: a word whose basename is `workflow-state` followed by `progress` or `mark-progress`, or a word whose basename is `sdd-gate`, with a word `--action-id` or one starting `--action-id=` after it in the same simple command (D8, D15).
- A call that registers nothing from an agent with no state file reads no transcript and writes nothing; a state file exists only for owners (D9).
- Under the lock, for an owner: unmeasured changes nothing; measured below `threshold` clears `notified`; the first measurement at or above `threshold` sets `notified` and is due unless the call holds a progress invocation; later ones are not due. The comparison is `measured >= threshold` (spec § Owners and the crossing).
- State content is `{"notified": <bool>, "owner": true}` (`json.dumps(…, sort_keys=True)`); an empty file is an owner being registered; any other content that is not exactly that shape raises `ValueError` naming the path, which `main` turns into exit 1 (D6, D14).
- Task 1's outputs are unchanged for every case its tests cover; the instruction and the progress note never share one output.

```python
CROSSING_NOTE = (
    "context-meter: your context is {tokens} tokens, at or above the {threshold}-token "
    "hand-off threshold. At the next safe point (the step in hand committed, no worker you "
    "dispatched still running), run your phase gate: workflow-state progress for your last "
    "completed phase, with truthful booleans, then obey its action. This notice is not "
    "repeated.")
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_context_meter.py`, above the `if __name__` block (add `import fcntl` and `import time` to the imports):

```python
CROSSING = ("context-meter: your context is {} tokens, at or above the 110000-token hand-off "
            "threshold. At the next safe point (the step in hand committed, no worker you "
            "dispatched still running), run your phase gate: workflow-state progress for your "
            "last completed phase, with truthful booleans, then obey its action. This notice is "
            "not repeated.")
MARK = "workflow-state mark-progress --repo-root /ledger --run-id run-1 --action-id 7:1:1"


class CrossingTest(MeterHarness):
    def setUp(self):
        super().setUp()
        self.calls = 0

    def call(self, context, command="git status --short", *, agent=True):
        self.calls += 1
        transcript = self.agent_transcript if agent else self.main_transcript
        self.append(transcript, assistant_record(context, message_id=f"c{self.calls}",
                                                 sidechain=agent))
        code, output, stderr = self.run_meter(self.payload(command, agent=agent))
        self.assertEqual((code, stderr), (0, ""))
        return None if output is None else output["hookSpecificOutput"].get("additionalContext")

    def test_105k_to_112k_injects_once_and_118k_does_not(self):
        self.assertIsNone(self.call(105000, MARK))
        self.assertEqual(self.call(112000), CROSSING.format(112000))
        self.assertIsNone(self.call(118000))

    def test_dropping_below_the_threshold_rearms_the_trigger(self):
        self.assertIsNone(self.call(105000, MARK))
        self.assertEqual(self.call(112000), CROSSING.format(112000))
        self.assertIsNone(self.call(90000))
        self.assertEqual(self.call(111000), CROSSING.format(111000))
        self.assertIsNone(self.call(113000))

    def test_a_non_owner_is_never_notified(self):
        for context, command in (
                (105000, "git status --short"), (112000, "git log -1"),
                (113000, "sdd-gate next plan.md --skill-dir /skills --task 2"),
                (114000, "workflow-state check-launch --repo-root /ledger --run-id run-1"
                         " --action-id 7:1:1"),
                (115000, "launch-scope exec --repo-root /ledger --run-id run-1"
                         " --action-id 7:1:1 -- sdd-gate next plan.md --task 2"),
                (118000, "git status --short")):
            with self.subTest(command=command):
                self.assertIsNone(self.call(context, command))

    def test_a_progress_call_at_the_threshold_sets_notified_without_injecting(self):
        self.assertEqual(self.call(112000, PROGRESS.format(tokens="")), MEASURED.format(112000))
        self.assertIsNone(self.call(115000))

    def test_sdd_gate_with_an_action_id_registers_an_owner(self):
        self.assertIsNone(self.call(100000, "sdd-gate next plan.md --skill-dir /skills --task 2"
                                            " --repo-root /ledger --run-id run-1"
                                            " --action-id=7:1:1"))
        self.assertEqual(self.call(110000), CROSSING.format(110000))

    def test_a_main_session_owner_is_keyed_apart_from_its_subagents(self):
        self.assertIsNone(self.call(105000, MARK, agent=False))
        self.assertIsNone(self.call(112000))
        self.assertEqual(self.call(112000, agent=False), CROSSING.format(112000))

    def test_an_unmeasured_call_changes_nothing(self):
        self.assertIsNone(self.call(105000, MARK))
        self.agent_transcript.unlink()
        self.assertIsNone(self.run_meter(self.payload("git status --short"))[1])
        self.assertEqual(self.call(112000), CROSSING.format(112000))

    def test_an_owner_update_waits_for_the_state_lock(self):
        self.assertIsNone(self.call(105000, MARK))
        self.append(self.agent_transcript, assistant_record(112000, message_id="locked",
                                                            sidechain=True))
        state = self.home / ".agents/state/context-meter" / f"{SESSION}.agent-{AGENT}.json"
        with state.open("r+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            meter = subprocess.Popen(
                [sys.executable, "-m", "agent_tools.context_meter"], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                env={**os.environ, "HOME": str(self.home)}, cwd=str(self.root))
            meter.stdin.write(json.dumps(self.payload("git status --short")))
            meter.stdin.close()
            time.sleep(1.5)
            self.assertIsNone(meter.poll(), "the meter finished while the state lock was held")
        stdout, stderr = meter.communicate(timeout=60)
        self.assertEqual((meter.returncode, stderr), (0, ""))
        self.assertEqual(json.loads(stdout)["hookSpecificOutput"]["additionalContext"],
                         CROSSING.format(112000))

    def test_a_corrupt_state_file_is_a_loud_non_blocking_error(self):
        self.assertIsNone(self.call(105000, MARK))
        state = self.home / ".agents/state/context-meter" / f"{SESSION}.agent-{AGENT}.json"
        state.write_text("{not json", encoding="utf-8")
        self.append(self.agent_transcript, assistant_record(112000, message_id="bad",
                                                            sidechain=True))
        code, output, stderr = self.run_meter(self.payload("git status --short"))
        self.assertEqual((code, output), (1, None))
        self.assertIn(str(state), stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the meter tests (timeout 600 s). Expected: `FAILED`; the `CrossingTest` cases that expect `CROSSING` get `None`, the lock test fails with `the meter finished while the state lock was held` or a missing state file, and the corrupt-state test gets exit 0; Task 1's ten tests still pass.

- [ ] **Step 3: Write the minimal implementation**

`context_meter_commands.registers_owner`: for each word token at index `i` whose value's basename is `workflow-state` with `tokens[i + 1]` the word `progress` or `mark-progress`, or whose basename is `sdd-gate`, it is true when some word in `tokens[i + 1:simple_command_end(tokens, i)]` has the value `--action-id` or starts with `--action-id=`.

`context_meter_crossing.record`, in order:
1. `path = state_path(directory, identity)`. Not `register` and the path does not exist → return `False`.
2. Open it: when registering, `directory.mkdir(mode=0o700, parents=True, exist_ok=True)` and `os.open(path, os.O_RDWR | os.O_CREAT, 0o600)`; otherwise `os.open(path, os.O_RDWR)`, where `FileNotFoundError` returns `False`.
3. `fcntl.flock(fd, fcntl.LOCK_EX)`, then read the whole file. Empty → `{"notified": False, "owner": True}`; otherwise `json.loads` must succeed and give exactly that key set with `owner is True` and a `bool` `notified`; a decode failure or any other shape raises `ValueError(f"context-meter: {path} is not an owner state record")` (chained `from` the decode error where there is one).
4. Apply the transition of **Invariants** to get `(state, due)`; write the state back with `os.lseek(fd, 0, 0)`, `os.ftruncate(fd, 0)` and one `os.write` of the `sort_keys` JSON; close the descriptor (releasing the lock) in a `finally`. Return `due`.

`is_owner(directory, identity)` is `state_path(directory, identity).exists()`.

`context_meter.respond(payload, *, state_dir, threshold)`, after the Bash-call check and `lex` exactly as in Task 1:
1. `starts = progress_starts(tokens)`, `register = registers_owner(tokens)`, `identity = agent_identity(payload)`, `owner = identity is not None and (register or context_meter_crossing.is_owner(state_dir, identity))`.
2. No `starts` and not `owner` → `None` (no transcript read).
3. `measurement = measure(payload)`; `output` is Task 1's progress output when `starts`, else `None`.
4. When `owner`, `due = context_meter_crossing.record(state_dir, identity, register=register, measured=measurement.tokens, progress=bool(starts), threshold=threshold)`; a due call returns `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": CROSSING_NOTE.format(tokens=measurement.tokens, threshold=threshold)}}`.
5. Return `output`.

`context_meter.py` imports the module (`from agent_tools import context_meter_crossing, phase_budget`) rather than its names, so `respond`'s `state_dir` parameter shadows nothing; `main` calls `respond(payload, state_dir=context_meter_crossing.state_dir(Path.home()), threshold=phase_budget.CONTEXT_CEILING - phase_budget.CONTEXT_HEADROOM)`. Extend the `context_meter.py` docstring with the owner rule and the state location, and `phase_budget.py`'s docstring with one sentence: the context meter hands an owner off at `CONTEXT_CEILING - CONTEXT_HEADROOM`.

- [ ] **Step 4: Verify**

Run the meter tests. Expected: `Ran 19 tests` and `OK`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/context_meter_crossing.py python/agent_tools/context_meter_commands.py \
  python/agent_tools/context_meter.py python/agent_tools/phase_budget.py tests/test_context_meter.py
launch-commit … -- -m "feat(context-meter): tell an owner once per crossing to run its phase gate (issue 424)" -m "<session trailers>"
```

Verify: `git status --short -- python tests` prints nothing.
