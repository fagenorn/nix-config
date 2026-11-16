"""Tests for the program bridge (issue 1142): a Workflow program's agent calls
relayed to a Python actor over the line protocol in program_bridge.mjs."""
import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

from .program_bridge import BRIDGE, NODE, AgentThrow, run_program


class ProgramBridgeTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def write(self, name, body):
        path = self.dir / name
        path.write_text(body, encoding="utf-8")
        return path

    def test_each_agent_call_reaches_the_actor_with_its_label_prompt_and_schema(self):
        path = self.write(
            "p.js",
            "const r = await agent('hello', { label: 'x', schema: { type: 'object' }, agentType: 'clerk' }); return { got: r }",
        )
        seen = []

        def actor(message):
            seen.append(message)
            return {"v": 1}

        out = run_program(path, {"issue": 5, "mode": "plan"}, actor)
        self.assertEqual(out["result"], {"got": {"v": 1}})
        self.assertIsNone(out["error"])
        self.assertEqual(len(seen), 1)
        message = dict(seen[0])
        del message["id"]
        self.assertEqual(
            message,
            {
                "type": "agent",
                "label": "x",
                "program": "p",
                "issue": 5,
                "mode": "plan",
                "prompt": "hello",
                "schema": {"type": "object"},
                "agentType": "clerk",
            },
        )

    def test_a_child_workflow_runs_its_program_with_the_child_issue_and_mode(self):
        child = self.write("child.js", "return await agent('c', { label: 'child-step' })")
        parent = self.write(
            "parent.js",
            "return await workflow({ scriptPath: %s }, { issue: 7, mode: 'ready' })" % json.dumps(str(child)),
        )
        seen = []

        def actor(message):
            seen.append(message)
            return {"ok": True}

        out = run_program(parent, {}, actor)
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0]["label"], "child-step")
        self.assertEqual(seen[0]["program"], "child")
        self.assertEqual(seen[0]["issue"], 7)
        self.assertEqual(seen[0]["mode"], "ready")
        self.assertEqual(out["result"], {"ok": True})
        self.assertEqual(
            out["children"],
            [{"issue": 7, "mode": "ready", "program": "child", "result": {"ok": True}}],
        )

    def test_an_agent_throw_rejects_only_that_call(self):
        path = self.write(
            "p.js",
            "try { await agent('p', { label: 'x' }); return 'no' } catch (e) { return 'caught ' + e.message }",
        )

        def actor(message):
            raise AgentThrow("boom")

        out = run_program(path, {}, actor)
        self.assertEqual(out["result"], "caught boom")

    def test_an_actor_failure_kills_the_program_and_is_reraised(self):
        path = self.write("p.js", "await agent('p', { label: 'x' }); return 1")

        def actor(message):
            raise ValueError("actor broke")

        with self.assertRaisesRegex(ValueError, "^actor broke$"):
            run_program(path, {}, actor)

    def test_parallel_calls_each_reach_the_actor_with_distinct_ids(self):
        path = self.write(
            "p.js",
            "return await parallel([() => agent('a', { label: 'a' }), () => agent('b', { label: 'b' })])",
        )
        seen = []

        def actor(message):
            seen.append(message)
            return {"label": message["label"]}

        out = run_program(path, {}, actor)
        self.assertEqual(out["result"], [{"label": "a"}, {"label": "b"}])
        self.assertEqual(len(seen), 2)
        self.assertNotEqual(seen[0]["id"], seen[1]["id"])

    def test_a_program_throw_is_reported_as_error(self):
        path = self.write("p.js", "throw new Error('bad args')")
        out = run_program(path, {}, lambda message: None)
        self.assertEqual(out["error"], "bad args")
        self.assertIsNone(out["result"])

    def test_a_large_result_reaches_python_whole(self):
        path = self.write("p.js", "return 'x'.repeat(4 * 1024 * 1024)")
        out = run_program(path, {}, lambda message: self.fail("the actor must not be called"))
        self.assertIsNone(out["error"])
        self.assertIsInstance(out["result"], str)
        self.assertEqual(len(out["result"]), 4 * 1024 * 1024)
        self.assertEqual(set(out["result"]), {"x"})

    def test_answers_out_of_order_reach_the_right_calls(self):
        self.assertIsNotNone(NODE)
        path = self.write(
            "p.js",
            "return await parallel([() => agent('a', { label: 'a' }), () => agent('b', { label: 'b' })])",
        )
        proc = subprocess.Popen(
            [NODE, str(BRIDGE)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        watchdog = threading.Timer(30, proc.kill)
        watchdog.start()

        def cleanup():
            watchdog.cancel()
            proc.kill()
            proc.wait()
            for stream in (proc.stdin, proc.stdout, proc.stderr):
                stream.close()

        self.addCleanup(cleanup)

        def send(obj):
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()

        send({"program": str(path), "args": {}})
        first = json.loads(proc.stdout.readline())
        second = json.loads(proc.stdout.readline())
        by_label = {first["label"]: first, second["label"]: second}
        self.assertEqual(set(by_label), {"a", "b"})
        self.assertEqual(first["type"], "agent")
        self.assertEqual(second["type"], "agent")
        send({"id": by_label["b"]["id"], "reply": {"for": "b"}})
        send({"id": by_label["a"]["id"], "reply": {"for": "a"}})
        last = json.loads(proc.stdout.readline())
        self.assertEqual(last["type"], "result")
        self.assertEqual(last["result"], [{"for": "a"}, {"for": "b"}])
        self.assertIsNone(last["error"])
        self.assertEqual(proc.wait(timeout=30), 0)


if __name__ == "__main__":
    unittest.main()
