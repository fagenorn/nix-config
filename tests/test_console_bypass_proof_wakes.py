"""The bypass proof's `wakes` step: two console relays reach a bypass manager (#1230).

Run: just agent-workflow-tests
"""
import json
import os
import unittest

from agent_tools.console import bypass_proof, manager, nudge
from agent_tools.verification import verify_exec

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from .wake_proof_world import WakeProofWorld

STEPS = list(bypass_proof.WAKE_TEARDOWN_STEPS)


def verdicts(report):
    return [row["verdict"] for row in report["wakes"]]


def teardown(report):
    return {entry["step"]: entry for entry in report["teardown"]}


def stops_and_removals(world):
    return [argv[1:] for argv in world.argv_log() if argv[1:3] in (["run", "stop"], ["run", "rm"])]


class BypassProofWakesTest(unittest.TestCase):
    def test_two_wakes_reach_the_bypass_manager_and_each_reads_its_inbox(self):
        world = WakeProofWorld(self)

        code, report, stderr, _ = world.run()

        self.assertEqual(code, 0, stderr)
        self.assertEqual(report["outcome"], "passed")
        self.assertEqual([(w["wake"], w["sent"], w["inbox_calls"], w["verdict"])
                          for w in report["wakes"]],
                         [(1, True, 1, "delivered"), (2, True, 2, "delivered")])
        self.assertTrue(all(w["sender_bypass"] is True for w in report["wakes"]))
        self.assertEqual(report["manager"],
                         {"permission_mode": "bypassPermissions", "ready": True})
        self.assertEqual([entry["step"] for entry in report["teardown"]], STEPS)
        self.assertTrue(all(entry["ok"] for entry in report["teardown"]), report["teardown"])
        self.assertEqual(world.record(), report)
        path = world.home / ".agents/state/console/bypass-proof-wakes.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(world.scratch_entries(), [])
        self.assertEqual(world.live_daemons(), [])

    def test_each_wake_is_the_consoles_own_relay_and_the_manager_runs_under_manager_settings(self):
        world = WakeProofWorld(self)
        code, report, stderr, _ = world.run()
        self.assertEqual(code, 0, stderr)

        relays = world.relay_argvs()
        self.assertEqual(len(relays), 2)
        for argv in relays:
            self.assertEqual(os.path.basename(argv[0]), "claude-account")
            self.assertEqual(argv[1:], ["run", *nudge.relay_arguments(
                report["session_name"], nudge.NUDGE_TEXT, True)])
        launches = [argv for argv in world.argv_log() if "--bg" in argv]
        self.assertEqual(len(launches), 1)
        self.assertTrue(launches[0][-1].startswith(manager.PROMPT_LEAD))
        self.assertTrue(launches[0][-1].endswith(bypass_proof.WAKE_GOAL))
        (entry,) = world.launch_log()
        settings = entry["settings"]
        self.assertEqual(settings, manager.settings_document(settings["env"],
                                                             bypass_proof.PERMISSION))
        self.assertNotIn("crossSessionInbound", json.dumps(settings))
        self.assertIs(entry["sprint_executable"], True)

    def test_a_wake_held_after_the_first_fails_the_proof(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run("--wake-wait", "2", env={"FAKE_CLIENT_HOLD_AFTER": "1"})

        self.assertEqual(code, 1)
        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(verdicts(report), ["delivered", "not_delivered"])
        self.assertEqual([w["inbox_calls"] for w in report["wakes"]], [1, 1])
        self.assertTrue(all(entry["ok"] for entry in report["teardown"]))
        self.assertEqual(stops_and_removals(world), [["run", "stop", "m1aaaaaa"],
                                                     ["run", "rm", "m1aaaaaa"]])

    def test_a_wake_from_a_prompting_sender_is_held_by_the_bypass_manager(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run("--wake-wait", "2",
                                       env={"FAKE_CLIENT_FORCE_DEFAULT_SENDER": "1"})

        self.assertEqual(verdicts(report), ["not_delivered", "not_delivered"])
        self.assertEqual(code, 1)

    def test_a_relay_that_does_not_confirm_is_not_sent(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run(env={"FAKE_CLIENT_RELAY_FAILS": "1"})

        self.assertEqual(verdicts(report), ["not_sent", "not_sent"])
        self.assertEqual([w["detail"] for w in report["wakes"]],
                         ["the relay did not confirm the message"] * 2)
        self.assertEqual(code, 1)

    def test_a_manager_that_never_reads_its_contract_gets_no_wake_and_is_still_removed(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run("--ready-wait", "2", env={"FAKE_CLIENT_NOT_READY": "1"})

        self.assertIs(report["manager"]["ready"], False)
        self.assertEqual(report["wakes"], [])
        self.assertEqual(report["reason"], "the manager did not start")
        self.assertEqual(world.relay_argvs(), [])
        steps = teardown(report)
        self.assertTrue(steps["stop_manager"]["ok"] and steps["remove_manager"]["ok"])
        self.assertEqual(world.live_daemons(), [])
        self.assertEqual(code, 1)

    def test_a_failed_stop_names_the_command_that_finishes_it_and_fails_the_exit(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run(env={"FAKE_CLIENT_STOP_FAILS": "1"})

        self.assertEqual(report["outcome"], "passed")
        self.assertEqual(code, 1)
        steps = teardown(report)
        self.assertIs(steps["stop_manager"]["ok"], False)
        self.assertIn("finish by hand: CLAUDE_ACCOUNT=work claude-account run stop m1aaaaaa",
                      steps["stop_manager"]["detail"])
        for step in ("remove_manager", "untrust", "remove_checkout"):
            self.assertIs(steps[step]["ok"], True, steps[step])

    def test_the_checkout_is_trusted_during_the_step_and_untrusted_after(self):
        world = WakeProofWorld(self)

        code, _, stderr, _ = world.run()

        self.assertEqual(code, 0, stderr)
        self.assertEqual([entry["trusted"] for entry in world.launch_log()], [True])
        self.assertEqual(json.loads(world.trust_file().read_text())["projects"], {})

    def test_setup_refusals_exit_not_yet_and_start_nothing(self):
        for label in ("CLAUDECODE", "no profile"):
            with self.subTest(label):
                world = WakeProofWorld(self)
                env = {}
                if label == "CLAUDECODE":
                    env["CLAUDECODE"] = "1"
                else:
                    (world.accounts / "chosen-profile").unlink()

                code, report, stderr, _ = world.run(env=env)

                self.assertEqual(code, 75, stderr)
                self.assertEqual(report["outcome"], "refused")
                self.assertEqual(report["teardown"], [])
                self.assertTrue(stderr.startswith("bypass-proof: "), stderr)
                self.assertEqual(world.argv_log(), [])
                self.assertEqual(world.scratch_entries(), [])

    def test_the_wake_steps_time_limit_fits_the_verify_runner_and_keeps_teardown_time(self):
        self.assertLess(bypass_proof.WAKE_LIMIT, verify_exec.TIMEOUT)
        self.assertGreaterEqual(bypass_proof.TEARDOWN_RESERVE,
                                nudge.LISTING_TIMEOUT + manager.STOP_TIMEOUT
                                + manager.REMOVE_TIMEOUT)
        args = bypass_proof._parser().parse_args(["wakes"])
        self.assertEqual((args.ready_wait, args.idle_wait, args.wake_wait, args.time_limit,
                          args.teardown_reserve),
                         (bypass_proof.READY_WAIT, bypass_proof.IDLE_WAIT,
                          bypass_proof.WAKE_WAIT, bypass_proof.WAKE_LIMIT,
                          bypass_proof.TEARDOWN_RESERVE))
        for bad in (["--time-limit", "541"], ["--time-limit", "10", "--teardown-reserve", "10"],
                    ["--wake-wait", "0"]):
            with self.subTest(bad):
                world = WakeProofWorld(self)
                code, _, _, _ = world.run(*bad)
                self.assertEqual(code, 2)
                self.assertEqual(world.argv_log(), [])

    def test_an_inbox_call_late_in_the_previous_turn_is_not_counted_for_the_next_wake(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run(
            "--wake-wait", "6",
            env={"FAKE_CLIENT_HOLD_AFTER": "1", "FAKE_CLIENT_LATE_INBOX": "3"})

        self.assertEqual(verdicts(report), ["delivered", "not_delivered"])
        self.assertEqual([w["inbox_calls"] for w in report["wakes"]], [1, 2])
        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(code, 1)

    def test_a_manager_that_never_goes_idle_gets_no_wake(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run("--idle-wait", "2", env={"FAKE_CLIENT_STAYS_BUSY": "1"})

        self.assertEqual(verdicts(report), ["not_idle", "not_idle"])
        self.assertEqual([w["sent"] for w in report["wakes"]], [False, False])
        self.assertEqual(world.relay_argvs(), [])
        self.assertTrue(all(entry["ok"] for entry in report["teardown"]), report["teardown"])
        self.assertEqual(code, 1)

    def test_a_slow_setup_stops_at_the_time_limit_and_still_tears_down(self):
        world = WakeProofWorld(self)

        code, report, _, seconds = world.run("--time-limit", "8", "--teardown-reserve", "4",
                                             env={"FAKE_GIT_DELAY": "2"})

        self.assertEqual(report["outcome"], "failed")
        self.assertEqual(report["reason"], bypass_proof.OUT_OF_TIME)
        self.assertFalse(any("--bg" in argv for argv in world.argv_log()))
        self.assertEqual([entry["step"] for entry in report["teardown"]], STEPS)
        self.assertTrue(all(entry["ok"] for entry in report["teardown"]), report["teardown"])
        self.assertEqual(world.scratch_entries(), [])
        self.assertEqual(code, 1)
        self.assertLess(seconds, 8)

    def test_a_relay_that_hangs_is_cut_at_the_time_limit_and_the_manager_is_still_removed(self):
        world = WakeProofWorld(self)

        code, report, _, seconds = world.run("--time-limit", "12", "--teardown-reserve", "6",
                                             env={"FAKE_CLIENT_RELAY_DELAY": "60"})

        self.assertEqual(report["reason"], bypass_proof.OUT_OF_TIME)
        self.assertEqual(verdicts(report), ["not_sent"])
        steps = teardown(report)
        self.assertTrue(steps["stop_manager"]["ok"] and steps["remove_manager"]["ok"])
        self.assertEqual(stops_and_removals(world), [["run", "stop", "m1aaaaaa"],
                                                     ["run", "rm", "m1aaaaaa"]])
        self.assertEqual(world.live_daemons(), [])
        self.assertEqual(code, 1)
        self.assertLess(seconds, 12)

    def test_a_session_the_listing_cannot_name_is_found_in_the_registry(self):
        world = WakeProofWorld(self)

        code, report, stderr, _ = world.run(env={"FAKE_CLIENT_LISTING_FAILS": "1"})

        self.assertEqual(report["outcome"], "passed")
        self.assertEqual(code, 0, stderr)
        self.assertEqual(stops_and_removals(world), [["run", "stop", "m1aaaaaa"],
                                                     ["run", "rm", "m1aaaaaa"]])
        self.assertEqual(world.live_daemons(), [])

    def test_a_launch_that_fails_after_starting_its_session_still_removes_it(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run(env={"FAKE_CLIENT_LAUNCH_FAILS": "1"})

        self.assertEqual(report["reason"], "the manager could not start: launch broke")
        self.assertEqual(report["wakes"], [])
        steps = teardown(report)
        self.assertTrue(steps["stop_manager"]["ok"] and steps["remove_manager"]["ok"])
        self.assertEqual(stops_and_removals(world), [["run", "stop", "m1aaaaaa"],
                                                     ["run", "rm", "m1aaaaaa"]])
        self.assertEqual(world.live_daemons(), [])
        self.assertEqual(code, 1)

    def test_a_session_that_cannot_be_found_fails_teardown_with_the_recovery(self):
        world = WakeProofWorld(self)

        code, report, _, _ = world.run(
            "--ready-wait", "2",
            env={"FAKE_CLIENT_LISTING_FAILS": "1", "FAKE_CLIENT_NO_REGISTRY": "1"})

        self.assertIs(report["manager"]["ready"], False)
        steps = teardown(report)
        for step in ("stop_manager", "remove_manager"):
            self.assertIs(steps[step]["ok"], False)
            self.assertTrue(steps[step]["detail"].startswith(bypass_proof.NOT_FOUND))
            self.assertIn("finish by hand: CLAUDE_ACCOUNT=work claude-account run agents "
                          "--json --all", steps[step]["detail"])
            self.assertIn(report["session_name"], steps[step]["detail"])
        self.assertTrue(steps["untrust"]["ok"] and steps["remove_checkout"]["ok"])
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
