"""context-meter (issue 424): the PreToolUse hook that measures an agent's context."""

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
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
        for command in ("git status --short", 'echo "$(date)"',
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
        # next to a redirection, bash itself must see the intended argv (P424-01)
        redirections = {
            "workflow-state progress>out --phase 3":
                "workflow-state progress --context-tokens 87412 >out --phase 3",
            "workflow-state progress --phase 3 --context-tokens 5>out":
                "workflow-state progress --context-tokens 87412 --phase 3 5>out",
        }
        for command, expected in redirections.items():
            with self.subTest(command=command):
                rewritten = self.rewritten(self.run_meter(self.payload(command))[1])
                self.assertEqual(rewritten, expected)
                shown = subprocess.run(
                    ["bash", "-c", 'workflow-state() { printf "%s\\n" "$@" >&2; }; ' + rewritten],
                    cwd=str(self.root), capture_output=True, text=True, check=True)
                self.assertEqual(shown.stderr.splitlines(),
                                 ["progress", "--context-tokens", "87412", "--phase", "3"])

    def test_an_unprovable_removal_leaves_the_command_unchanged_with_a_message(self):
        self.append(self.agent_transcript, assistant_record(87412, message_id="01"))
        for command in ("workflow-state progress --phase 3 --context-tokens $(printf 85000)",
                        "workflow-state progress --phase 3 --context-tokens=$(printf 85000)",
                        "workflow-state progress --phase 3 --context-tokens=`printf 85000`"):
            with self.subTest(command=command):
                self.assertEqual(self.run_meter(self.payload(command)), (0, {
                    "systemMessage": "context-meter: left a workflow-state progress call "
                                     "unchanged (the rewrite failed its proof)."}, ""))

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
                        "workflow-state progress --phase 3 <<'EOF'\nbody\nEOF",
                        'out="$(workflow-state progress --phase 3 --context-tokens 5)"',
                        'out="`workflow-state progress --phase 3`"'):
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
            try:
                meter.stdin.write(json.dumps(self.payload("git status --short")))
                meter.stdin.close()
                meter.stdin = None  # communicate() would flush the closed stream (P424-03)
                time.sleep(1.5)
                self.assertIsNone(meter.poll(), "the meter finished while the state lock was held")
            except BaseException:
                meter.kill()
                meter.communicate()
                raise
        try:
            stdout, stderr = meter.communicate(timeout=60)
        finally:
            if meter.poll() is None:
                meter.kill()
                meter.communicate()
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


if __name__ == "__main__":
    unittest.main()
