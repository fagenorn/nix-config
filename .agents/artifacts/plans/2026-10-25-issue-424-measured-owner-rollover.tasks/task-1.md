# Task 1: The meter command — measured `--context-tokens` on every progress call

Spec § The meter command, § Measurement, § Progress rewrite, § Failure posture; per D1, D3, D4, D5, D6, D10, D14, D15. This task builds the `context-meter` command as a source module with its rewrite only; owners and the crossing come in Task 3, the Nix row and hook registration in Task 4.

**Files:**
- Create: `python/agent_tools/context_meter.py` (the command: shell plus `respond`)
- Create: `python/agent_tools/context_meter_transcript.py` (where the agent's transcript is and how its last call is read)
- Create: `python/agent_tools/context_meter_commands.py` (lexing, progress recognition, rewrite, proof)
- Create: `tests/test_context_meter.py`
- Modify: `justfile` (the `agent-workflow-tests` recipe gains `tests/test_context_meter.py \` on the line after `tests/test_lane_triage.py \`)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces (Task 3 relies on these names exactly):
  - `context_meter_transcript`: `PLAIN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")`; `WINDOW_BYTES = 1 << 20`; `class AgentIdentity(NamedTuple): session_id: str; agent_id: str | None`; `class Measurement(NamedTuple): tokens: int | None; reason: str | None` (`reason` is set exactly when `tokens` is `None`); `agent_identity(payload: Mapping[str, object]) -> AgentIdentity | None`; `measure(payload: Mapping[str, object]) -> Measurement`.
  - `context_meter_commands`: `class Token(NamedTuple): kind: str; value: str; start: int; end: int` (`kind` is `"word"` or `"op"`; `start`/`end` index `command`, `end` exclusive, closing quotes included); `lex(command: str) -> list[Token] | None`; `progress_starts(tokens: Sequence[Token]) -> list[int]`; `simple_command_end(tokens: Sequence[Token], index: int) -> int`; `class Rewrite(NamedTuple): command: str; proved: bool`; `rewrite_progress(command: str, tokens: Sequence[Token], measured: int | None) -> Rewrite`; `proved(rewritten: str, expected: Sequence[tuple[str, str]]) -> bool`; `mentions_progress(command: str) -> bool`.
  - `context_meter`: `respond(payload: object) -> dict | None`; `build_parser() -> argparse.ArgumentParser` (`prog="context-meter"`, no arguments); `main(argv: list[str] | None = None) -> int`; and the four texts below.

**Invariants:**
- The stdout is empty or exactly one JSON object `{"hookSpecificOutput": {"hookEventName": "PreToolUse", "updatedInput"?, "additionalContext"?}, "systemMessage"?}`; it never holds `permissionDecision`, `permissionDecisionReason`, `decision` or `continue`, and the exit code is never 2 (D3, D6).
- `updatedInput` is present only when the command changed, and is the whole `tool_input` with only `command` replaced.
- A command with no progress invocation produces no output and never reads a transcript.
- A rewrite is emitted only when `proved` holds for it; otherwise the command passes through unchanged with the unchanged-message (D3).
- Every byte outside the removed `--context-tokens` words (and the whitespace before each) and the inserted ` --context-tokens <n>` stays as it was (D5).

The four texts, defined once in `context_meter.py` and copied as literals into the tests:

```python
MEASURED_NOTE = ("context-meter: this workflow-state progress call carries "
                 "--context-tokens {tokens}, measured from your transcript.")
UNMEASURED_NOTE = ("context-meter: your context could not be measured, so this "
                   "workflow-state progress call carries no --context-tokens.")
UNMEASURED_MESSAGE = ("context-meter: could not measure this agent's context ({reason}); "
                      "its workflow-state progress call runs without --context-tokens.")
UNCHANGED_MESSAGE = "context-meter: left a workflow-state progress call unchanged ({reason})."
```

The closed set of `reason` values: `session or agent id is not a plain identifier`, `no transcript path`, `transcript not found`, `transcript unreadable`, `no usage record in the last 1048576 bytes` (unmeasured); `the command could not be tokenised`, `the rewrite failed its proof` (unchanged).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_context_meter.py`:

```python
"""context-meter (issue 424): the PreToolUse hook that measures an agent's context."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SESSION = "5f0c9a52-3d1e-4c7b-9a61-0d2b7c4e8f10"
AGENT = "a070d25dd72898f75"
PROGRESS = ("workflow-state progress --repo-root /ledger --run-id run-1 --issue 7 --attempt 1"
            " --phase 3 --turn-count 40{tokens} --next-needs-context true"
            " --artifacts-sufficient false --remainder-self-contained false --action-id 7:1:1")
FORBIDDEN_KEYS = {"permissionDecision", "permissionDecisionReason", "decision", "continue"}
MEASURED = ("context-meter: this workflow-state progress call carries --context-tokens {}, "
            "measured from your transcript.")
UNMEASURED = ("context-meter: your context could not be measured, so this workflow-state "
              "progress call carries no --context-tokens.")


def assistant_record(context, *, message_id, model="claude-opus-5-5", sidechain=False,
                     block="tool_use"):
    """A production-shaped assistant record whose usage sums to `context`."""
    if block == "tool_use":
        content = {"type": "tool_use", "id": f"toolu_{message_id}", "name": "Bash",
                   "input": {"command": "git status --short"}}
    else:
        content = {"type": "text", "text": "Checking the tree."}
    return {"parentUuid": None, "isSidechain": sidechain, "type": "assistant",
            "uuid": f"uuid-{message_id}-{block}", "sessionId": SESSION,
            "timestamp": "2026-10-25T10:00:00.000Z",
            "message": {"id": f"msg_{message_id}", "type": "message", "role": "assistant",
                        "model": model, "content": [content],
                        "usage": {"input_tokens": 2, "cache_creation_input_tokens": 1000,
                                  "cache_read_input_tokens": context - 1002,
                                  "output_tokens": 180}}}


def user_record(tool_use_id, text="ok"):
    return {"parentUuid": None, "isSidechain": False, "type": "user",
            "uuid": f"uuid-result-{tool_use_id}", "sessionId": SESSION,
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_use_id, "content": text}]}}


class MeterHarness(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        project = self.root / "projects" / "-Users-dev-repo"
        project.mkdir(parents=True)
        self.main_transcript = project / f"{SESSION}.jsonl"
        self.agent_transcript = project / SESSION / "subagents" / f"agent-{AGENT}.jsonl"
        self.agent_transcript.parent.mkdir(parents=True)

    def append(self, path, *records):
        with path.open("a", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record) + "\n")

    def payload(self, command, *, agent=True, **overrides):
        value = {"session_id": SESSION, "transcript_path": str(self.main_transcript),
                 "cwd": str(self.root), "permission_mode": "auto",
                 "hook_event_name": "PreToolUse", "tool_name": "Bash",
                 "tool_input": {"command": command, "description": "Record the phase gate",
                                "timeout": 120000},
                 "tool_use_id": "toolu_current"}
        if agent:
            value.update(agent_id=AGENT, agent_type="general-purpose")
        value.update(overrides)
        return value

    def run_meter(self, payload):
        """Run the command from source: (exit code, stdout object or None, stderr)."""
        stdin = payload if isinstance(payload, str) else json.dumps(payload)
        proc = subprocess.run(
            [sys.executable, "-m", "agent_tools.context_meter"], input=stdin,
            capture_output=True, text=True, timeout=60,
            env={**os.environ, "HOME": str(self.home)}, cwd=str(self.root))
        self.assertNotEqual(proc.returncode, 2, proc.stderr)
        output = json.loads(proc.stdout) if proc.stdout.strip() else None
        if output is not None:
            self.assertEqual(set(output) - {"hookSpecificOutput", "systemMessage"}, set())
            self.assertFalse(FORBIDDEN_KEYS & set(output.get("hookSpecificOutput", {})), output)
        return proc.returncode, output, proc.stderr

    def rewritten(self, output):
        return output["hookSpecificOutput"]["updatedInput"]["command"]


class ProgressRewriteTest(MeterHarness):
    def test_the_87412_fixture_replaces_a_missing_or_wrong_count(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        expected = PROGRESS.format(tokens="").replace(
            "progress", "progress --context-tokens 87412", 1)
        for name, tokens in (("missing", ""), ("separate", " --context-tokens 85000"),
                             ("equals", " --context-tokens=85000"),
                             ("abbreviated", " --context-t 85000"),
                             ("abbreviated equals", " --context-tok=85000")):
            with self.subTest(case=name):
                code, output, _ = self.run_meter(self.payload(PROGRESS.format(tokens=tokens)))
                self.assertEqual(code, 0)
                hook = output["hookSpecificOutput"]
                self.assertEqual(hook["hookEventName"], "PreToolUse")
                self.assertEqual(hook["updatedInput"], {
                    "command": expected, "description": "Record the phase gate",
                    "timeout": 120000})
                self.assertEqual(hook["additionalContext"], MEASURED.format(87412))
                self.assertNotIn("systemMessage", output)

    def test_other_commands_pass_through_untouched(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        for command in ("git status --short",
                        "echo 'workflow-state progress --context-tokens 5'",
                        "cat notes.md # workflow-state progress --context-tokens 5",
                        "workflow-state progressive --context-tokens 5",
                        "workflow-state check-launch --repo-root /ledger --run-id run-1"
                        " --action-id 7:1:1"):
            with self.subTest(command=command):
                self.assertEqual(self.run_meter(self.payload(command)), (0, None, ""))

    def test_a_compound_command_differs_only_in_its_context_tokens_words(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        command = ("cd /ledger && ~/.agents/bin/workflow-state progress --repo-root /ledger"
                   " --run-id run-1 --issue 7 --attempt 1 --phase 3 --context-tokens 5"
                   " --next-needs-context true --artifacts-sufficient false"
                   " --remainder-self-contained false --action-id 7:1:1 2>&1"
                   " | artifact-budget validate-report --boundary workflow-response --input -"
                   " && git push origin x")
        expected = ("cd /ledger && ~/.agents/bin/workflow-state progress --context-tokens 87412"
                    " --repo-root /ledger --run-id run-1 --issue 7 --attempt 1 --phase 3"
                    " --next-needs-context true --artifacts-sufficient false"
                    " --remainder-self-contained false --action-id 7:1:1 2>&1"
                    " | artifact-budget validate-report --boundary workflow-response --input -"
                    " && git push origin x")
        self.assertEqual(self.rewritten(self.run_meter(self.payload(command))[1]), expected)

    def test_edge_shapes_of_one_invocation(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        cases = {
            # a redirection does not end the simple command
            "workflow-state progress --phase 3 2>&1 --context-tokens 5":
                "workflow-state progress --context-tokens 87412 --phase 3 2>&1",
            # every invocation is rewritten, the quoted spelling included
            "workflow-state progress --phase 3 \"--context-tokens\" 1; "
            "workflow-state progress --phase 4 --context-tokens=2":
                "workflow-state progress --context-tokens 87412 --phase 3; "
                "workflow-state progress --context-tokens 87412 --phase 4",
            # words after `--` are not options
            "workflow-state progress --phase 3 -- --context-tokens 5":
                "workflow-state progress --context-tokens 87412 --phase 3 -- --context-tokens 5",
            # an option-looking next word is not taken as the value
            "workflow-state progress --context-tokens --phase 3":
                "workflow-state progress --context-tokens 87412 --phase 3",
            # `--context-` is ambiguous to argparse, so it is not a spelling
            "workflow-state progress --context- 5 --phase 3":
                "workflow-state progress --context-tokens 87412 --context- 5 --phase 3",
            # inside a command substitution
            "action=$(workflow-state progress --phase 3 --context-tokens 9 | jq -r .action)":
                "action=$(workflow-state progress --context-tokens 87412 --phase 3"
                " | jq -r .action)",
        }
        for command, expected in cases.items():
            with self.subTest(command=command):
                self.assertEqual(self.rewritten(self.run_meter(self.payload(command))[1]),
                                 expected)

    def test_a_subagent_reads_its_own_transcript_and_a_main_session_its_session_transcript(self):
        self.append(self.main_transcript, assistant_record(150000, message_id="m1"),
                    assistant_record(99999, message_id="side", sidechain=True))
        self.append(self.agent_transcript,
                    assistant_record(87412, message_id="a1", sidechain=True))
        command = PROGRESS.format(tokens="")
        _, subagent, _ = self.run_meter(self.payload(command))
        self.assertIn("progress --context-tokens 87412 ", self.rewritten(subagent))
        _, main, _ = self.run_meter(self.payload(command, agent=False))
        self.assertIn("progress --context-tokens 150000 ", self.rewritten(main))

    def test_synthetic_and_duplicated_usage_records(self):
        self.append(self.agent_transcript,
                    assistant_record(87412, message_id="01", block="text"),
                    assistant_record(87412, message_id="01"),
                    user_record("toolu_01"),
                    assistant_record(5000, message_id="02", model="<synthetic>"))
        _, output, _ = self.run_meter(self.payload(PROGRESS.format(tokens="")))
        self.assertEqual(output["hookSpecificOutput"]["additionalContext"],
                         MEASURED.format(87412))

    def test_an_unmeasured_progress_call_loses_the_models_value(self):
        command = PROGRESS.format(tokens=" --context-tokens 85000")
        window_filled = self.root / "window.jsonl"
        self.append(window_filled, assistant_record(87412, message_id="old"),
                    user_record("toolu_old", "x" * (1 << 20)))
        cases = {
            "transcript not found": self.payload(command),
            "session or agent id is not a plain identifier": self.payload(
                command, agent_id="../escape"),
            "no transcript path": self.payload(command, agent=False, transcript_path=""),
            "no usage record in the last 1048576 bytes": self.payload(
                command, agent=False, transcript_path=str(window_filled)),
        }
        for reason, payload in cases.items():
            with self.subTest(reason=reason):
                code, output, _ = self.run_meter(payload)
                self.assertEqual(code, 0)
                self.assertEqual(self.rewritten(output), PROGRESS.format(tokens=""))
                self.assertEqual(output["hookSpecificOutput"]["additionalContext"], UNMEASURED)
                self.assertEqual(output["systemMessage"], (
                    f"context-meter: could not measure this agent's context ({reason}); "
                    "its workflow-state progress call runs without --context-tokens."))

    def test_an_untokenisable_progress_call_passes_through_with_a_message(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        for command in ("workflow-state progress --context-tokens 5 'unterminated",
                        "workflow-state progress --phase 3 <<'EOF'\nbody\nEOF"):
            with self.subTest(command=command):
                self.assertEqual(self.run_meter(self.payload(command)), (0, {
                    "systemMessage": "context-meter: left a workflow-state progress call "
                                     "unchanged (the command could not be tokenised)."}, ""))

    def test_malformed_input_passes_through(self):
        for stdin in ("not json", "[]", json.dumps({"tool_name": "Read", "tool_input": {}}),
                      json.dumps({"tool_name": "Bash", "tool_input": {"command": 7}}),
                      json.dumps({"tool_name": "Bash", "tool_input": "workflow-state progress"})):
            with self.subTest(stdin=stdin):
                self.assertEqual(self.run_meter(stdin), (0, None, ""))


class RewriteProofTest(unittest.TestCase):
    def test_a_rewrite_that_changes_another_word_fails_its_proof(self):
        from agent_tools.context_meter_commands import lex, proved
        words = [(token.kind, token.value) for token in lex("workflow-state progress --phase 3")]
        expected = words[:2] + [("word", "--context-tokens"), ("word", "87412")] + words[2:]
        self.assertTrue(proved("workflow-state progress --context-tokens 87412 --phase 3",
                               expected))
        self.assertFalse(proved("workflow-state progress --context-tokens 87412 --phase 4",
                                expected))
        self.assertFalse(proved("workflow-state progress --context-tokens 87412 '--phase 3",
                                expected))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the meter tests (Global Constraints). Expected: errors — `No module named agent_tools.context_meter` in every `ProgressRewriteTest` case and `No module named 'agent_tools.context_meter_commands'` in `RewriteProofTest`.

- [ ] **Step 3: Write the minimal implementation**

`context_meter_transcript.py` (module docstring: what the meter reads, per D4):
- `agent_identity`: `session_id` must be a `str` that `PLAIN_ID.fullmatch`es; an absent or `None` `agent_id` gives `AgentIdentity(session_id, None)`; any other `agent_id` must be a `str` that fullmatches, else `None`.
- `measure`, in order, returning the first reason that applies: identity `None` → `session or agent id is not a plain identifier`; `transcript_path` not a non-empty `str` → `no transcript path`; the path is `Path(transcript_path)` for a main session and `Path(transcript_path).parent / session_id / "subagents" / f"agent-{agent_id}.jsonl"` for a subagent; open it `rb`, seek to `max(0, size - WINDOW_BYTES)` and read to the end (`FileNotFoundError` → `transcript not found`, any other `OSError` → `transcript unreadable`); split on `b"\n"`, drop the first piece when the read started past offset 0, and walk the rest from the end. A piece qualifies when `json.loads` gives a `dict` with `type == "assistant"`, a `dict` `message` whose `model` is not `"<synthetic>"`, a `dict` `usage` whose three fields `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` are each absent, `None` or a non-`bool` `int` ≥ 0, with a sum > 0, and, for a main session only, `isSidechain` is not `True`. Unparseable pieces and non-objects are skipped. The first qualifying piece's sum is `Measurement(sum, None)`; none → `no usage record in the last 1048576 bytes` (built from `WINDOW_BYTES`).

`context_meter_commands.py` (module docstring: the lexer subset and spellings of D15):
- `lex` scans once, left to right. Space and tab end a word. `'…'` appends its interior literally; `"…"` appends its interior, where a backslash before `$`, `` ` ``, `"`, `\` appends that character, before a newline appends nothing, and before anything else appends both; an unterminated quote returns `None`. Outside quotes a backslash before a newline is a line continuation (appends nothing, does not end the word), before any other character appends that character, and as the last character returns `None`. `#` where no word has started skips to the next newline. A newline is the operator `"\n"`. At `;`, `&`, `|`, `(`, `)`, `<`, `>` or a backtick the current word ends and the longest match from `("&>>", "<<<", "<<-", "&&", "||", "|&", ";;", "&>", ">>", ">&", "<&", "<>", ">|", "<<", ";", "&", "|", "(", ")", "<", ">", "`")` is one `op` token; `<<` or `<<-` (a heredoc) returns `None`. Every other character is part of a word.
- `SEPARATORS = {"\n", ";", "&", "&&", "|", "||", "|&", ";;", "(", ")", "`"}`; `simple_command_end(tokens, index)` is the index of the first `op` token after `index` whose value is in `SEPARATORS`, else `len(tokens)`. Every other operator is a redirection, and the word after a redirection is its target, never an option.
- `progress_starts` returns each index `i` where `tokens[i]` is a word whose value's basename (`value.rsplit("/", 1)[-1]`) is `workflow-state` and `tokens[i + 1]` is the word `progress`.
- A spelling is a word value `name` (or the part before the first `=`) with `name.startswith("--context-t") and "--context-tokens".startswith(name)`.
- `rewrite_progress`: for each start `i`, scan `j` from `i + 2` to `simple_command_end(tokens, i + 1)`: a redirection skips itself and its target; the word `--` stops the scan; a spelling with `=` removes its word; a bare spelling removes its word and, when the next token is a word inside the simple command that does not start with `-`, that word too. When `measured` is not `None`, ` --context-tokens <measured>` is inserted at the `progress` word's `end`. Removing word `k` deletes `command[tokens[k - 1].end:tokens[k].end]`. Splice with this exact pass, which orders an insertion before a deletion at the same offset:

```python
def _splice(command: str, deletions: list[tuple[int, int]], insertions: dict[int, str]) -> str:
    events = sorted([(start, 1, end) for start, end in deletions]
                    + [(at, 0, text) for at, text in insertions.items()])
    pieces, cursor = [], 0
    for at, kind, payload in events:
        pieces.append(command[cursor:at])
        if kind == 0:
            pieces.append(payload)
            cursor = at
        else:
            cursor = max(cursor, payload)
    pieces.append(command[cursor:])
    return "".join(pieces)
```

  The expected words are the original `(kind, value)` pairs without the removed indices, with `("word", "--context-tokens"), ("word", str(measured))` after each `progress` word when measured. `Rewrite(result, proved(result, expected))`.
- `proved` is `lex(rewritten)` not `None` and its `(kind, value)` pairs equal `expected`.
- `mentions_progress(command)` is `re.search(r"workflow-state\s+progress(?![\w-])", command) is not None`.

`context_meter.py` (module docstring: the command's contract and that it grants nothing, per D3 and D6):
- `respond(payload)`: `None` unless `payload` is a `dict` with `tool_name == "Bash"` and a `dict` `tool_input` whose `command` is a `str`. `tokens = lex(command)`; when `None`, return `{"systemMessage": UNCHANGED_MESSAGE.format(reason="the command could not be tokenised")}` if `mentions_progress(command)`, else `None`. No progress start → `None` (no transcript read). Otherwise `measurement = measure(payload)`, `rewrite = rewrite_progress(command, tokens, measurement.tokens)`; an unproved rewrite → `{"systemMessage": UNCHANGED_MESSAGE.format(reason="the rewrite failed its proof")}`. Else the hook output with `hookEventName`, `updatedInput` (`{**tool_input, "command": rewrite.command}`) only when the command changed, `additionalContext` `MEASURED_NOTE.format(tokens=…)` or `UNMEASURED_NOTE`, and, when unmeasured, `systemMessage` `UNMEASURED_MESSAGE.format(reason=measurement.reason)`.
- `main`: `build_parser().parse_args(argv)`; read `sys.stdin.buffer.read()`; `json.loads` of those bytes sits in its own `try`, whose `ValueError` (decode errors included) returns 0 with no output; any exception from reading or from `respond`, a `ValueError` included, prints its traceback to stderr and returns 1 (D6); a non-`None` result is written as one `json.dumps` line; return 0. End with `if __name__ == "__main__": sys.exit(main())`.

- [ ] **Step 4: Verify**

Run the meter tests. Expected: `Ran 10 tests` and `OK`; any failing subtest names the case that is not yet met.

Then check the recipe line:

```bash
grep -n 'tests/test_context_meter.py \\' justfile
```

Expected: one line, directly after the `tests/test_lane_triage.py \` line.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/context_meter.py python/agent_tools/context_meter_transcript.py \
  python/agent_tools/context_meter_commands.py tests/test_context_meter.py justfile
launch-commit … -- -m "feat(context-meter): rewrite progress calls to carry the measured context (issue 424)" -m "<session trailers>"
```

Verify: `git status --short -- python tests justfile` prints nothing.
