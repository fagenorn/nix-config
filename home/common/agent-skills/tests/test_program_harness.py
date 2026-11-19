"""One program server answers each harness scenario as a fresh process would (issue 1288).

Run: just agent-workflow-tests
"""

import os
import shutil
import signal
import stat
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from program_harness import ProgramServer, server_for, run_fresh  # noqa: E402

REPO_ROOT = Path(__file__).parents[4]
PROGRAMS = REPO_ROOT / "home/common/claude-code/skills/deliver-standard"
STANDARD = (Path(__file__).with_name("deliver_standard_harness.mjs"), PROGRAMS / "deliver-standard.js")
BATCH = (Path(__file__).with_name("deliver_batch_harness.mjs"), PROGRAMS / "deliver-batch.js")
HARNESSES = {"standard": STANDARD[0], "batch": BATCH[0]}
NODE = shutil.which("node")

STD_ARGS = {"repo_root": "/r", "issue": 9, "session_id": "s1"}
BATCH_ARGS = {"repo_root": "/r", "batch_id": "b1", "child_script": "/s/deliver-standard.js", "issues": [1]}
CHILD_ARGS = {"repo_root": "/r", "issue": 1, "batch_id": "b1", "mode": "ready", "lane": "standard"}
DONE_REPLY = {"status": "done", "start_head": "a" * 40, "commit": "c0ffee", "tests": ["t"], "notes": "ok"}
PLAN4 = {
    "status": "planned",
    "plan_root": "/g/plan.md",
    "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
    "tasks": [{"n": n, "title": f"t{n}", "file": f"/g/task-{n}.md", "risk": "standard"} for n in range(1, 5)],
}
BATCH_SETUP = {
    "ok": True, "host": "h1", "slug": "owner/repo", "integration_branch": "dev", "default_branch": "main",
    "merge_strategy": "merge", "delete_branch": True, "unset_env": [], "max_parallel": 2, "required_checks": None,
}

FIXTURE = """\
if (args.boom) throw new Error('boom')
if (args.hang) await new Promise(() => {})
if (args.spin) { for (;;) {} }
if (args.stray) { Promise.reject(new Error('stray rejection')); await new Promise(r => setImmediate(r)) }
if (args.noisy) { for (let i = 0; i < 2000; i++) console.error('x'.repeat(100)) }
if (args.leak) { if (typeof leaked !== 'undefined') return { leaked: true }; leaked = 1; return { leaked: false } }
if (args.pin) { const had = Object.getOwnPropertyDescriptor(globalThis, 'pinned') !== undefined; if (!had) Object.defineProperty(globalThis, 'pinned', { value: 1 }); return { leaked: had } }
if (args.late) { setImmediate(() => log('late')); Promise.resolve().then(() => log('micro')); log('now'); return { ok: true } }
if (args.timer) { setTimeout(() => { globalThis.lateTimer = 1 }, 30).unref(); return { ok: true } }
if (args.wait) { await new Promise(r => setTimeout(r, 150)); return { late: typeof lateTimer !== 'undefined' } }
if (args.chatty) { console.log('debug'); return { ok: true } }
if (args.echo) return { echo: args.echo }
if (args.exit) { process.exitCode = 1; return { ok: true } }
if (args.noreflect) { delete globalThis.Reflect; return { ok: true } }
if (args.readopt) { const c = await workflow({ scriptPath: '/s/c.js' }, { issue: 1, mode: 'ready', batch_id: 'b1' }); c.acceptance[0].text = 'edited'; const r = await agent('p', { label: 'readopt-1' }); return { text: r.acceptance[0].text } }
if (args.child) { const c = await workflow({ scriptPath: '/s/c.js' }, { issue: 1, mode: 'ready', batch_id: 'b1' }); const before = c.acceptance ? c.acceptance[0].text : null; if (c.acceptance) c.acceptance[0].text = 'edited'; return { stage: c.stage, before } }
return { ok: true }
"""


class NodeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if NODE is None:
            raise AssertionError("node is not on PATH; the harness tests need it")
        tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(tmp.cleanup)
        cls.tmp = Path(tmp.name)
        cls.fixture = cls.tmp / "fixture.js"
        cls.fixture.write_text(FIXTURE)

    def server(self):
        s = ProgramServer(NODE)
        self.addCleanup(s.close)
        return s


class ReuseMatchesAFreshProcessTest(NodeCase):
    def test_a_reused_standard_harness_answers_a_per_call_reply_list_as_a_fresh_process(self):
        sc = {"args": STD_ARGS, "replies": {"impl-1": [{"status": "blocked", "notes": "no"}, DONE_REPLY]}, "patch": {}, "after": {}}
        fresh = run_fresh(NODE, *STANDARD, sc)
        s = self.server()
        first = s.run(*STANDARD, sc)
        pid = s.pid
        second = s.run(*STANDARD, sc)
        self.assertEqual(fresh["result"]["stage"], "task")
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)
        self.assertEqual(s.pid, pid)

    def test_a_reused_standard_harness_reopens_its_after_gates_for_each_scenario(self):
        sc = {"args": STD_ARGS, "replies": {"plan": PLAN4}, "patch": {}, "after": {"final-codex": "final-integration"}}
        fresh = run_fresh(NODE, *STANDARD, sc)
        s = self.server()
        first = s.run(*STANDARD, sc)
        second = s.run(*STANDARD, sc)
        events = fresh["events"]
        self.assertLess(events.index("call final-integration"), events.index("reply final-codex"))
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)

    def test_a_reused_batch_harness_answers_a_per_call_reply_list_as_a_fresh_process(self):
        sc = {
            "args": BATCH_ARGS, "replies": {"setup": [BATCH_SETUP, dict(BATCH_SETUP, slug=None)]},
            "patch": {}, "children": {}, "turns": {}, "delays": {},
        }
        fresh = run_fresh(NODE, *BATCH, sc)
        s = self.server()
        first = s.run(*BATCH, sc)
        pid = s.pid
        second = s.run(*BATCH, sc)
        self.assertEqual(fresh["result"]["table"][0]["outcome"], "landed")
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)
        self.assertEqual(s.pid, pid)

    def test_one_server_answers_batch_and_standard_child_scenarios_in_one_process(self):
        s = server_for(NODE)
        batch = {"args": BATCH_ARGS, "replies": {}, "patch": {}, "children": {}, "turns": {}, "delays": {}}
        child = {"args": CHILD_ARGS, "replies": {}, "patch": {}}
        fresh_batch = run_fresh(NODE, *BATCH, batch)
        fresh_child = run_fresh(NODE, *STANDARD, child)
        out1 = s.run(*BATCH, batch)
        pid = s.pid
        out2 = s.run(*STANDARD, child)
        pid2 = s.pid
        out3 = s.run(*BATCH, batch)
        pid3 = s.pid
        self.assertIs(server_for(NODE), s)
        self.assertEqual(out1, fresh_batch)
        self.assertEqual(out2, fresh_child)
        self.assertEqual(out3, fresh_batch)
        self.assertEqual(fresh_child["result"]["stage"], "ready")
        self.assertIsNotNone(pid)
        self.assertEqual(pid, pid2)
        self.assertEqual(pid, pid3)

    def test_work_left_running_after_the_program_returns_is_left_out_as_a_fresh_process_leaves_it(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                sc = {"args": {"late": True}}
                fresh = run_fresh(NODE, harness, self.fixture, sc)
                s = self.server()
                first = s.run(harness, self.fixture, sc)
                second = s.run(harness, self.fixture, sc)
                self.assertIn("now", fresh["logs"])
                self.assertNotIn("late", fresh["logs"])
                self.assertEqual(first, fresh)
                self.assertEqual(second, fresh)

    def test_a_scenario_that_changes_the_global_object_is_answered_then_the_next_runs_in_a_new_process(self):
        for name, harness in HARNESSES.items():
            for branch in ("leak", "pin"):
                with self.subTest(harness=name, branch=branch):
                    sc = {"args": {branch: True}}
                    fresh = run_fresh(NODE, harness, self.fixture, sc)
                    s = self.server()
                    first = s.run(harness, self.fixture, sc)
                    after_first = s.pid
                    second = s.run(harness, self.fixture, sc)
                    plain1 = s.run(harness, self.fixture, {"args": {}})
                    pid1 = s.pid
                    plain2 = s.run(harness, self.fixture, {"args": {}})
                    pid2 = s.pid
                    self.assertEqual(fresh["result"], {"leaked": False})
                    self.assertEqual(first, fresh)
                    self.assertIsNone(after_first)
                    self.assertEqual(second, fresh)
                    self.assertEqual(plain1["result"], {"ok": True})
                    self.assertEqual(plain2["result"], {"ok": True})
                    self.assertIsNotNone(pid1)
                    self.assertEqual(pid1, pid2)

    def test_a_reused_batch_harness_answers_a_per_call_child_list_as_a_fresh_process(self):
        sc = {"args": {"child": True}, "children": {"1": [{"stage": "first"}, {"stage": "second"}]}}
        fresh = run_fresh(NODE, BATCH[0], self.fixture, sc)
        s = self.server()
        first = s.run(BATCH[0], self.fixture, sc)
        second = s.run(BATCH[0], self.fixture, sc)
        self.assertEqual(fresh["result"], {"stage": "first", "before": None})
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)

    def test_a_program_that_edits_the_default_ready_child_does_not_change_the_next_scenarios_default(self):
        sc = {"args": {"child": True}}
        fresh = run_fresh(NODE, BATCH[0], self.fixture, sc)
        s = self.server()
        first = s.run(BATCH[0], self.fixture, sc)
        pid = s.pid
        second = s.run(BATCH[0], self.fixture, sc)
        self.assertEqual(fresh["result"], {"stage": "ready", "before": "works"})
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)
        self.assertEqual(s.pid, pid)

    def test_a_program_that_edits_a_ready_child_changes_the_readopt_default_as_in_a_fresh_process(self):
        sc = {"args": {"readopt": True}}
        fresh = run_fresh(NODE, BATCH[0], self.fixture, sc)
        s = self.server()
        first = s.run(BATCH[0], self.fixture, sc)
        second = s.run(BATCH[0], self.fixture, sc)
        self.assertEqual(fresh["result"], {"text": "edited"})
        self.assertEqual(first, fresh)
        self.assertEqual(second, fresh)

    def test_a_timer_left_unref_ed_by_one_scenario_never_fires_in_the_next(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                fresh = run_fresh(NODE, harness, self.fixture, {"args": {"wait": True}})
                s = self.server()
                s.run(harness, self.fixture, {"args": {"timer": True}})
                after_timer = s.pid
                out = s.run(harness, self.fixture, {"args": {"wait": True}})
                self.assertEqual(fresh["result"], {"late": False})
                self.assertIsNone(after_timer)
                self.assertEqual(out, fresh)

    def test_a_scenario_that_deletes_a_global_the_restart_check_uses_still_returns_its_result(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                sc = {"args": {"noreflect": True}}
                fresh = run_fresh(NODE, harness, self.fixture, sc)
                s = self.server()
                out = s.run(harness, self.fixture, sc)
                self.assertEqual(out, fresh)
                self.assertIsNone(s.pid)
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})

    def test_a_reused_harness_answers_a_throw_as_a_fresh_process_does(self):
        boom = {"args": {"boom": True}}
        s = self.server()
        shape = {"result": None, "error": "boom", "calls": [], "logs": [], "events": []}
        self.assertEqual(run_fresh(NODE, STANDARD[0], self.fixture, boom), shape)
        self.assertEqual(s.run(STANDARD[0], self.fixture, boom), shape)
        with self.assertRaises(AssertionError) as fresh:
            run_fresh(NODE, BATCH[0], self.fixture, boom)
        self.assertIn("harness failed", str(fresh.exception))
        with self.assertRaises(AssertionError) as served:
            s.run(BATCH[0], self.fixture, boom)
        self.assertIn("harness failed: program threw:", str(served.exception))
        self.assertIn("boom", str(served.exception))
        pid = s.pid
        self.assertEqual(s.run(BATCH[0], self.fixture, {"args": {}})["result"], {"ok": True})
        self.assertEqual(s.pid, pid)

    def test_a_server_compiles_each_program_once(self):
        once = self.tmp / "once.js"
        once.write_text("return { n: 1 }")
        s = self.server()
        first = s.run(STANDARD[0], once, {"args": {}})
        once.write_text("return { n: 2 }")
        second = s.run(STANDARD[0], once, {"args": {}})
        self.assertEqual(first["result"], {"n": 1})
        self.assertEqual(second["result"], {"n": 1})
        self.assertEqual(run_fresh(NODE, STANDARD[0], once, {"args": {}})["result"], {"n": 2})


class FailureShapesTest(NodeCase):
    def test_a_program_that_never_settles_fails_its_scenario_and_the_process_answers_the_next(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                with self.assertRaises(AssertionError):
                    run_fresh(NODE, harness, self.fixture, {"args": {"hang": True}})
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {"hang": True}}, timeout=30)
                self.assertIn("harness failed: the program never settled", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertEqual(s.pid, pid)

    def test_a_program_that_sets_a_failing_exit_code_fails_its_scenario_and_the_process_answers_the_next(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                with self.assertRaises(AssertionError):
                    run_fresh(NODE, harness, self.fixture, {"args": {"exit": True}})
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {"exit": True}})
                self.assertIn("harness failed: the program set process.exitCode to 1", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertEqual(s.pid, pid)
                self.assertEqual(s.close(), 0)

    def test_a_program_that_writes_to_stdout_fails_its_scenario_and_is_never_answered_by_a_stale_reply(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                with self.assertRaises(ValueError):
                    run_fresh(NODE, harness, self.fixture, {"args": {"chatty": True}})
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {"chatty": True}})
                self.assertIn("harness failed: the harness wrote a line that is not a reply", str(raised.exception))
                self.assertIsNone(s.pid)
                self.assertEqual(s.run(harness, self.fixture, {"args": {"echo": "next"}})["result"], {"echo": "next"})
                self.assertNotIn(s.pid, (None, pid))

    def test_a_request_larger_than_the_pipe_sent_to_a_process_that_reads_nothing_times_out(self):
        mute = self.tmp / "mute-node"
        mute.write_text("#!/bin/sh\nexec sleep 30\n")
        mute.chmod(mute.stat().st_mode | stat.S_IXUSR)
        s = ProgramServer(str(mute))
        self.addCleanup(s.close)

        def hung(signum, frame):
            s._proc.kill()
            raise AssertionError("run() blocked past its timeout")

        old = signal.signal(signal.SIGALRM, hung)
        self.addCleanup(signal.signal, signal.SIGALRM, old)
        signal.alarm(20)
        self.addCleanup(signal.alarm, 0)
        with self.assertRaises(AssertionError) as raised:
            s.run(STANDARD[0], self.fixture, {"args": {"pad": "x" * 2_000_000}}, timeout=2)
        self.assertIn("harness failed: no reply within 2", str(raised.exception))
        self.assertIsNone(s.pid)

    def test_a_stray_rejection_fails_its_scenario_even_when_the_program_returns(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                with self.assertRaises(AssertionError):
                    run_fresh(NODE, harness, self.fixture, {"args": {"stray": True}})
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {"stray": True}})
                self.assertIn("unhandled rejection:", str(raised.exception))
                self.assertIn("stray rejection", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertEqual(s.pid, pid)

    def test_a_spinning_program_is_killed_at_the_timeout_and_the_next_run_starts_a_new_process(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {"spin": True}}, timeout=2)
                self.assertIn("harness failed: no reply within 2", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertNotIn(s.pid, (None, pid))

    def test_a_dead_server_fails_its_run_and_the_next_run_starts_a_new_process(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                os.kill(pid, signal.SIGKILL)
                with self.assertRaises(AssertionError) as raised:
                    s.run(harness, self.fixture, {"args": {}})
                self.assertIn("harness failed: the harness exited with", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertNotIn(s.pid, (None, pid))

    def test_a_closed_server_exits_on_its_own_and_starts_a_new_process_on_its_next_run(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                code = s.close()
                self.assertEqual(code, 0)
                self.assertIsNone(s.pid)
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertNotEqual(s.pid, pid)

    def test_a_noisy_program_does_not_block_on_its_stderr(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                s = self.server()
                out = s.run(harness, self.fixture, {"args": {"noisy": True}}, timeout=20)
                self.assertEqual(out["result"], {"ok": True})

    def test_a_bad_request_fails_its_run_and_the_server_answers_the_next(self):
        for name, harness in HARNESSES.items():
            with self.subTest(harness=name):
                s = self.server()
                s.run(harness, self.fixture, {"args": {}})
                pid = s.pid
                with self.assertRaises(AssertionError) as raised:
                    s.run(self.tmp / "missing.mjs", self.fixture, {"args": {}})
                self.assertIn("harness failed: bad request:", str(raised.exception))
                self.assertEqual(s.run(harness, self.fixture, {"args": {}})["result"], {"ok": True})
                self.assertEqual(s.pid, pid)


if __name__ == "__main__":
    unittest.main()
