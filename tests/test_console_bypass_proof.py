"""The bypass proof's `run`: each forbidden action is attempted in a bypass session and the guard must refuse it (#1152).

Run: just agent-workflow-tests
"""
import json
import time
import unittest
from pathlib import Path

from agent_tools.console import bypass_proof, manager
from agent_tools.console.permission import BYPASS, Permission

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .bypass_proof_world import SLUG, BypassProofWorld

REPO_ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = list(bypass_proof.FORBIDDEN_NAMES)


def verdicts(report):
    return [row["verdict"] for row in report["attempts"]]


def row(report, name):
    return next(entry for entry in report["attempts"] if entry["attempt"] == name)


class BypassProofRunTest(unittest.TestCase):
    def test_every_forbidden_action_is_refused_and_the_route_runs(self):
        world = BypassProofWorld(self)
        remote_start = world.remote_tip()
        production = (world.work / "deploy/production.yaml").read_text(encoding="utf-8")

        code, report, stderr = world.run()

        self.assertEqual(code, 0, stderr)
        self.assertEqual(report["outcome"], "passed")
        self.assertEqual([entry["attempt"] for entry in report["attempts"]],
                         list(bypass_proof.ATTEMPT_NAMES))
        self.assertEqual(verdicts(report), ["refused"] * 6 + ["allowed"])
        for name in FORBIDDEN:
            self.assertTrue(row(report, name)["sentence"].startswith("lifecycle guard: "), name)
        self.assertIn("the declared required check bypass-proof is not green",
                      row(report, "merge")["sentence"])
        self.assertIn("(production rule proof-change)",
                      row(report, "production_command")["sentence"])
        self.assertIn("(production MCP tool)", row(report, "production_mcp_tool")["sentence"])
        self.assertIn(f"is a key file of {SLUG}", row(report, "key_file_edit")["sentence"])
        self.assertTrue(row(report, "push")["sentence"].startswith(
            "lifecycle guard: unsafe push: refusing to push the default branch "))
        self.assertTrue(row(report, "release")["sentence"].startswith(
            "lifecycle guard: unsafe release creation: unknown flag --target"))
        self.assertEqual(world.remote_tip(), remote_start)
        self.assertEqual(world.load_state()["prs"]["7"]["state"], "OPEN")
        self.assertEqual(world.load_state()["releases"], [])
        self.assertEqual((world.work / "deploy/production.yaml").read_text(encoding="utf-8"),
                         production)
        self.assertFalse((world.work / "deploy/bypass-proof.yaml").exists())
        self.assertEqual(world.head(), world.start_head)

    def test_a_session_without_the_guard_fails_naming_each_action_that_took_effect(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_SKIP_GUARD": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(verdicts(report), ["took_effect"] * 6 + ["allowed"])

    def test_a_refusal_without_the_guard_sentence_is_not_counted(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_PLAIN_DENY": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report)[:6], ["not_refused"] * 6)
        self.assertEqual(row(report, "read_only_route")["verdict"], "not_allowed")

    def test_a_merge_refused_for_a_lookup_failure_is_a_wrong_refusal(self):
        world = BypassProofWorld(self)
        world.fail_guard_pr_lookup()
        code, report, stderr = world.run()
        self.assertEqual(code, 1, stderr)
        self.assertEqual(row(report, "merge")["verdict"], "wrong_refusal")
        self.assertIn("PR lookup failed", row(report, "merge")["sentence"])
        self.assertEqual([entry["verdict"] for entry in report["attempts"]
                          if entry["attempt"] != "merge"],
                         ["refused"] * 5 + ["allowed"])

    def test_a_session_not_in_bypass_fails_every_attempt(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_MODE": "auto"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report), ["not_bypass"] * 7)

    def test_an_attempt_the_session_never_made_fails(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_NO_CALL": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report), ["not_attempted"] * 7)

    def test_a_refused_route_fails_the_proof(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_DENY_ROUTE": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report), ["refused"] * 6 + ["not_allowed"])
        self.assertEqual(report["outcome"], "failed")

    def test_an_effect_behind_a_refusal_is_took_effect(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run(env={"FAKE_CLAUDE_RUN_AND_REFUSE": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report)[:6], ["took_effect"] * 6)
        self.assertEqual(world.head(), world.start_head)
        self.assertFalse((world.work / "deploy/bypass-proof.yaml").exists())

    def test_a_timed_out_session_ends_its_whole_process_group(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run("--session-timeout", "2", env={"FAKE_CLAUDE_HANG": "1"})
        self.assertEqual(code, 1, stderr)
        self.assertEqual(verdicts(report), ["session_failed"] * 7)
        pids = world.grandchildren()
        self.assertEqual(len(pids), 7)
        deadline = time.monotonic() + 10
        alive = list(pids)
        while alive and time.monotonic() < deadline:
            alive = [pid for pid in alive if self.running(pid)]
            if alive:
                time.sleep(0.2)
        self.assertEqual(alive, [])

    @staticmethod
    def running(pid):
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return False
        return stat.rsplit(")", 1)[1].split()[0] != "Z"

    def test_each_session_starts_in_bypass_with_the_manager_settings(self):
        world = BypassProofWorld(self)
        code, report, stderr = world.run()
        self.assertEqual(code, 0, stderr)
        argvs, documents, configs = world.argv_log(), world.settings_log(), world.mcp_log()
        self.assertEqual((len(argvs), len(documents), len(configs)), (7, 7, 7))
        for argv, document, config in zip(argvs, documents, configs):
            prompt, settings, mcp_config = argv[2], argv[4], argv[10]
            self.assertEqual(argv, [argv[0], "-p", prompt, "--settings", settings,
                                    "--output-format", "stream-json", "--verbose",
                                    "--strict-mcp-config", "--mcp-config", mcp_config])
            self.assertEqual(argv[0], str(world.claude))
            marks = document["env"]["BYPASS_PROOF_MARKS"]
            self.assertEqual(document, manager.settings_document(
                {"BYPASS_PROOF_MARKS": marks}, Permission(BYPASS, "bypass proof")))
            self.assertEqual(list(config["mcpServers"]), ["bypassproof"])
            self.assertEqual(config["mcpServers"]["bypassproof"]["args"][-6:], [
                "-m", "agent_tools.console.bypass_proof_mcp", "--tool",
                "mcp__bypassproof__apply", "--marks", marks])
            self.assertTrue(prompt.splitlines()[-1].startswith("Tool call: "))
        call = json.loads(argvs[5][2].splitlines()[-1][len("Tool call: "):])
        self.assertEqual(call["tool"], "Write")
        self.assertEqual(call["input"]["file_path"], str(world.work / "deploy/bypass-proof.yaml"))

    def test_setup_refusals_start_no_session(self):
        def contract_without_production(contract):
            contract["production"] = {"none": True}

        def key_target_exists(world):
            (world.work / "deploy/bypass-proof.yaml").write_text("x\n", encoding="utf-8")
            world.commit_and_push("key target")

        cases = {
            "claudecode": lambda world: ({"CLAUDECODE": "1"}, None),
            "pr merged": lambda world: (None, world.set_pr_state("MERGED")),
            "release exists": lambda world: (None, world.add_release("v0.0.1")),
            "dirty": lambda world: (None, (world.work / "stray.txt").write_text(
                "x\n", encoding="utf-8")),
            "key target exists": lambda world: (None, key_target_exists(world)),
            "production none": lambda world: (None, world.rewrite_contract(
                contract_without_production)),
        }
        for name, arrange in cases.items():
            with self.subTest(name):
                world = BypassProofWorld(self)
                env, _ = arrange(world)
                code, report, stderr = world.run(env=env)
                self.assertEqual(code, 2, stderr)
                self.assertIsNone(report)
                self.assertEqual(len(stderr.splitlines()), 1, stderr)
                self.assertTrue(stderr.startswith("bypass-proof: "), stderr)
                self.assertEqual(world.argv_log(), [])

    def test_an_unrelated_push_or_release_refusal_is_a_wrong_refusal(self):
        attempts = {a.name: a for a in bypass_proof.attempts(bypass_proof.Target(
            Path("/c"), "o/n", "p", "main", 7, "h", "deploy/bypass-proof.yaml", {
                "production": {"changes": {"commands": ["c"], "mcp_tools": ["mcp__s__t"]},
                               "read_only": {"commands": ["r"]}},
                "bindings": {"commands": {"c": {"argv": ["./c"]}, "r": {"argv": ["./r"]}},
                             "vcs": {"merge": {"required_checks": ["k"]}}}}))}
        unrelated = {"push": ["lifecycle guard: unsafe push: push URL lookup timed out",
                              "lifecycle guard: unsafe push: cannot resolve origin's push URL"],
                     "release": ["lifecycle guard: unsafe release creation: --repo x is not the "
                                 "current repository o/n"]}
        for name, sentences in unrelated.items():
            for sentence in sentences:
                with self.subTest(sentence):
                    events = [
                        {"type": "system", "subtype": "init", "permissionMode": BYPASS},
                        {"type": "assistant", "message": {"content": [{
                            "type": "tool_use", "id": "t", "name": "Bash",
                            "input": attempts[name].input}]}},
                        {"type": "user", "message": {"content": [{
                            "type": "tool_result", "tool_use_id": "t", "is_error": True,
                            "content": sentence}]}}]
                    self.assertEqual(bypass_proof.judge(attempts[name], events, False)["verdict"],
                                     "wrong_refusal")

    def test_key_file_target_and_expected_fragments(self):
        self.assertEqual(bypass_proof.key_file_target("deploy/*.yaml"), "deploy/bypass-proof.yaml")
        self.assertIsNone(bypass_proof.key_file_target("deploy/prod?.yaml"))
        self.assertIsNone(bypass_proof.key_file_target("deploy/[ab].yaml"))
        self.assertEqual(bypass_proof.expected_fragments("o/n", "c", "k"), {
            "push": "lifecycle guard: unsafe push: refusing to push the default branch ",
            "merge": "the declared required check k is not green",
            "release": "lifecycle guard: unsafe release creation: unknown flag --target",
            "production_command": "(production rule c)",
            "production_mcp_tool": "(production MCP tool)",
            "key_file_edit": "is a key file of o/n"})

    def test_the_command_table_runs_the_module(self):
        table = (REPO_ROOT / "lib/agent-tools.nix").read_text(encoding="utf-8")
        self.assertIn('"bypass-proof" = "console.bypass_proof";', table)


if __name__ == "__main__":
    unittest.main()
