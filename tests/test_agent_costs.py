"""Offline tests for scripts/agent-costs.py against tiny synthetic transcripts.

Covers the load-bearing counting rules (message-ID usage dedup, the tool-use-ID
and tool-result-ID guards), token accounting, model/effort extraction, peak
per-turn context, outcome derivation, the proceed-nudge matcher, and the
artifact pass. Runs entirely offline: fixtures are built in a temp dir.

Run: python3 -m unittest -v tests/test_agent_costs.py
"""

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SCRIPT = REPO / "scripts" / "agent-costs.py"

_spec = importlib.util.spec_from_file_location("agent_costs", SCRIPT)
agent_costs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(agent_costs)


def record(rec):
    """Compact JSON line, matching the real transcripts' non-spaced encoding
    (scan_file's prefilter looks for '"type":"assistant"' without spaces)."""
    return json.dumps(rec, separators=(",", ":")) + "\n"


def assistant(msg_id, usage=None, content=None, model="claude-opus-5",
              effort="xhigh", stop_reason="tool_use", cwd="/Users/me/repo"):
    return record({
        "type": "assistant",
        "cwd": cwd,
        "effort": effort,
        "message": {
            "id": msg_id,
            "model": model,
            "stop_reason": stop_reason,
            "usage": usage,
            "content": content or [],
        },
    })


USAGE_1 = {"input_tokens": 10, "output_tokens": 20,
           "cache_read_input_tokens": 100, "cache_creation_input_tokens": 5}
USAGE_2 = {"input_tokens": 1, "output_tokens": 2,
           "cache_read_input_tokens": 300, "cache_creation_input_tokens": 0}


class ScanFileTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)

    def write(self, name, lines):
        p = self.dir / name
        p.write_text("".join(lines))
        return p

    def scan(self, lines):
        return agent_costs.scan_file(self.write("t.jsonl", lines))

    def test_usage_deduped_by_message_id(self):
        # The same message written twice (one record per content block) must
        # count its usage exactly once.
        skill_block = {"type": "tool_use", "id": "toolu_1",
                       "name": "Skill", "input": {"skill": "sdd"}}
        lines = [
            assistant("msg_1", usage=USAGE_1, content=[skill_block]),
            assistant("msg_1", usage=USAGE_1, content=[{"type": "text", "text": "hi"}]),
            assistant("msg_2", usage=USAGE_2),
        ]
        r = self.scan(lines)
        self.assertEqual(r["turns"], 2)
        self.assertEqual(r["fresh"], 11)
        self.assertEqual(r["output"], 22)
        self.assertEqual(r["cache_read"], 400)
        self.assertEqual(r["cache_create"], 5)

    def test_tool_use_id_guard(self):
        # A replayed tool_use block (same block id) must not double-count the
        # Skill load or the Agent launch.
        skill_block = {"type": "tool_use", "id": "toolu_s",
                       "name": "Skill", "input": {"skill": "from-issue"}}
        agent_block = {"type": "tool_use", "id": "toolu_a", "name": "Agent",
                       "input": {"subagent_type": "implementer", "prompt": "x" * 120}}
        lines = [
            assistant("msg_1", usage=USAGE_1, content=[skill_block, agent_block]),
            # duplicate record of the same message repeating both blocks
            assistant("msg_1", usage=USAGE_1, content=[skill_block, agent_block]),
        ]
        r = self.scan(lines)
        self.assertEqual(r["skills"], {"from-issue": 1})
        self.assertEqual(r["agents_by_type"], {"implementer": 1})
        self.assertEqual(r["agent_prompt_bytes"], [120])

    def test_tool_result_id_guard_and_result_bytes(self):
        result_line = record({
            "type": "user",
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "toolu_a", "content": "done"},
            ]},
            "toolUseResult": {"agentType": "reviewer", "status": "completed",
                              "content": "y" * 200},
        })
        r = self.scan([result_line, result_line])  # exact replay
        self.assertEqual(r["agent_statuses"], {"completed": 1})
        self.assertEqual(r["agent_result_bytes"], [200])

    def test_model_effort_stop_reason_extraction(self):
        lines = [
            assistant("m1", usage=USAGE_1, model="claude-opus-5", effort="xhigh",
                      stop_reason="tool_use"),
            assistant("m2", usage=USAGE_2, model="claude-sonnet-5", effort="high",
                      stop_reason="end_turn"),
        ]
        r = self.scan(lines)
        self.assertEqual(r["models"], {"claude-opus-5": 1, "claude-sonnet-5": 1})
        self.assertEqual(r["efforts"], {"xhigh": 1, "high": 1})
        self.assertEqual(r["stop_reasons"], {"tool_use": 1, "end_turn": 1})

    def test_peak_context_is_max_single_turn_footprint(self):
        lines = [
            assistant("m1", usage=USAGE_1),  # 10 + 100 + 5 = 115
            assistant("m2", usage=USAGE_2),  # 1 + 300 + 0 = 301
        ]
        r = self.scan(lines)
        self.assertEqual(r["peak_ctx"], 301)

    def test_cost_uses_model_family_pricing(self):
        lines = [assistant("m1", usage=USAGE_1, model="claude-sonnet-5")]
        r = self.scan(lines)
        # sonnet: in 3.0, out 15.0, cache_write_5m 3.75, cache_read 0.30 per Mtok
        expected = (10 * 3.0 + 20 * 15.0 + 5 * 3.75 + 100 * 0.30) / 1e6
        self.assertAlmostEqual(r["cost"], expected, places=12)

    def test_proceed_nudges_counted_and_bounded(self):
        def user(text, sidechain=False):
            return record({"type": "user", "isSidechain": sidechain,
                           "message": {"role": "user", "content": text}})
        lines = [
            user("proceed"),
            user("ok, continue"),
            user("sorry proceed"),
            user("yes, lets do the handoff"),   # instruction, not a nudge
            user("proceed", sidechain=True),    # sidechain records don't count
            user("what are the issue numbers"),
        ]
        r = self.scan(lines)
        self.assertEqual(r["interventions"], 3)

    def test_phase_marker_turn_attribution(self):
        lines = [
            assistant("m1", usage=USAGE_1,
                      content=[{"type": "text", "text": "Starting Phase 0 now"}]),
            assistant("m2", usage=USAGE_2),
            assistant("m3", usage=USAGE_1 | {"input_tokens": 7},
                      content=[{"type": "text", "text": "## Phase 5 — review"}]),
        ]
        r = self.scan(lines)
        self.assertEqual(r["phase_turns"], {"0": 2, "5": 1})

    def test_agents_killed_and_final_text(self):
        lines = [
            assistant("m1", usage=USAGE_1,
                      content=[{"type": "text", "text": "PR merged, issue closed."}]),
            record({"type": "system", "subtype": "agents_killed"}),
        ]
        r = self.scan(lines)
        self.assertEqual(r["agents_killed"], 1)
        self.assertIn("merged", r["final_text"])


class OutcomeTest(unittest.TestCase):
    def test_completed(self):
        self.assertEqual(agent_costs.classify_outcome("PR #12 merged; issue closed."),
                         "completed")
        self.assertEqual(agent_costs.classify_outcome("review_state: clean, done"),
                         "completed")

    def test_blocked(self):
        self.assertEqual(agent_costs.classify_outcome(
            "Cannot proceed: needs your decision on the schema."), "blocked")
        self.assertEqual(agent_costs.classify_outcome("BLOCKED on missing token"),
                         "blocked")

    def test_abandoned(self):
        self.assertEqual(agent_costs.classify_outcome("Reading the next file."),
                         "abandoned")

    def test_group_rollup_prefers_completed(self):
        g = agent_costs.new_group()
        g["outcomes"] = ["abandoned", "blocked", "completed"]
        self.assertEqual(agent_costs.group_outcome(g), "completed")
        g["outcomes"] = ["abandoned", "blocked"]
        self.assertEqual(agent_costs.group_outcome(g), "blocked")
        g["outcomes"] = []
        self.assertEqual(agent_costs.group_outcome(g), "-")


class ArtifactStatsTest(unittest.TestCase):
    def test_fenced_and_decision_shares(self):
        with tempfile.TemporaryDirectory() as tmp:
            specs = Path(tmp) / "specs"
            specs.mkdir()
            (specs / "2026-01-01-thing-spec.md").write_text(
                "# Spec\n\nBody text.\n\n"
                "## Decision ledger\n\n"
                "| D1 | keep JSON | ADR-001 | rejected sqlite |\n"
                "| D2 | one file | CONTEXT.md | rejected split |\n\n"
                "## Other\n\n"
                "```python\nprint('hi')\n```\n"
            )
            stats = agent_costs.artifact_stats([str(specs)])
            spec = stats["spec"]
            self.assertEqual(spec["files"], 1)
            self.assertEqual(spec["ledger_rows"], 2)
            self.assertGreater(spec["decision"], 0)
            self.assertGreater(spec["fenced"], 0)
            self.assertGreater(spec["bytes"], spec["decision"])


class EndToEndTest(unittest.TestCase):
    """main() over a fake projects dir: grouping, issue keys, output sections."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        proj = root / "-Users-me-repo"
        proj.mkdir()
        wt_cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        (proj / "sess1.jsonl").write_text("".join([
            assistant("m1", usage=USAGE_1, cwd=wt_cwd, content=[
                {"type": "tool_use", "id": "t1", "name": "Skill",
                 "input": {"skill": "from-issue"}},
            ]),
            assistant("m2", usage=USAGE_2, cwd=wt_cwd, content=[
                {"type": "text", "text": "PR merged and issue #7 closed."},
            ], stop_reason="end_turn"),
        ]))
        subdir = proj / "sess1" / "subagents"
        subdir.mkdir(parents=True)
        (subdir / "agent-a.jsonl").write_text(
            assistant("s1", usage=USAGE_1, cwd=wt_cwd, model="claude-sonnet-5",
                      effort="high"),
        )
        self.projects = str(root)

    def run_script(self, *extra):
        return subprocess.run(
            [sys.executable, str(SCRIPT), "--projects-dir", self.projects,
             "--days", "0", *extra],
            capture_output=True, text=True, timeout=120,
        )

    def test_end_to_end_grouping_and_sections(self):
        res = self.run_script()
        self.assertEqual(res.returncode, 0, res.stderr)
        out = res.stdout
        self.assertIn("#7", out)          # issue key from the worktree cwd
        self.assertIn("repo", out)        # project name trimmed at the dot-dir
        self.assertIn("completed", out)   # outcome derived from the final message
        self.assertIn("TOTAL", out)
        self.assertIn("NOT billing data", out)
        # 3 deduped turns across root + subagent: fresh 10+1+10=21 output 20+2+20=42
        self.assertIn("3 turns", out)
        self.assertIn("xhigh 2", out)
        self.assertIn("high 1", out)
        self.assertIn("claude-opus-5 2", out)
        self.assertIn("claude-sonnet-5 1", out)


if __name__ == "__main__":
    unittest.main()
