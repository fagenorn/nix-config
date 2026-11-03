"""Offline tests for agent_tools.agent_costs and agent_cache_report on tiny synthetic transcripts.

Covers the load-bearing counting rules (message-ID usage dedup, the tool-use-ID
and tool-result-ID guards), token accounting, model/effort extraction, peak
per-turn context, outcome derivation, the proceed-nudge matcher, and the
artifact pass; and agent_tools.agent_cache_report: its transcript scanner, the
`--report cache` CLI and the report's aggregation. Runs entirely offline:
fixtures are built in a temp dir.

Run: just agent-workflow-tests
"""

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from agent_tools import agent_cache_report
from agent_tools import agent_costs
from agent_tools import model_pricing
from agent_tools.canonical import telemetry_digest


def record(rec):
    """Compact JSON line, matching the real transcripts' non-spaced encoding
    (scan_file's prefilter looks for '"type":"assistant"' without spaces)."""
    return json.dumps(rec, separators=(",", ":")) + "\n"


def assistant(msg_id, usage=None, content=None, model="claude-opus-5",
              effort="xhigh", stop_reason="tool_use", cwd="/Users/me/repo",
              agent_id=None, attribution_skill=None, sidechain=False, *,
              timestamp=None, version=None):
    value = {
        "type": "assistant",
        "cwd": cwd,
        "effort": effort,
        "agentId": agent_id,
        "attributionSkill": attribution_skill,
        "isSidechain": sidechain,
        "message": {
            "id": msg_id,
            "model": model,
            "stop_reason": stop_reason,
            "usage": usage,
            "content": content or [],
        },
    }
    if timestamp is not None:
        value["timestamp"] = timestamp
    if version is not None:
        value["version"] = version
    return record(value)


def agent_result(tool_id, agent_id, *, timestamp, status="completed"):
    return record({
        "type": "user", "timestamp": timestamp,
        "message": {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": tool_id, "content": "done",
        }]},
        "toolUseResult": {"agentId": agent_id, "agentType": "reviewer",
                          "status": status, "content": "done"},
    })


def envelope_user(agent_id, cwd, operation, *, packet="review packet", parent_uuid=None):
    return record({
        "type": "user",
        "isSidechain": True,
        "agentId": agent_id,
        "cwd": cwd,
        "parentUuid": parent_uuid,
        "message": {
            "role": "user",
            "content": (
                f"WORKTREE_ROOT: {cwd}\n"
                f"REVIEW_OPERATION: {operation}\n"
                f"{packet}"
            ),
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

    def test_cost_uses_per_model_pricing(self):
        lines = [assistant("m1", usage=USAGE_1, model="claude-sonnet-5")]
        r = self.scan(lines)
        # Sonnet 5: in 2.0, out 10.0, cache_write_5m 2.50, cache_read 0.20 per Mtok
        expected = (10 * 2.0 + 20 * 10.0 + 5 * 2.50 + 100 * 0.20) / 1e6
        self.assertAlmostEqual(r["cost"], expected, places=12)

    def test_opus_5_5_list_price_is_four_and_twenty_per_mtok(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 3_000_000,
                 "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000,
                                    "ephemeral_5m_input_tokens": 2_000_000}}
        r = self.scan([assistant("m1", usage=usage, model="claude-opus-5-5")])
        # Opus 5.5 row: $4 in + $20 out + 1M x $8 (1h write) + 2M x $5 (5m write)
        # + 1M x $0.20 (read) = $42.20; the Opus 5 row gives $53.
        self.assertAlmostEqual(r["cost"], 42.2, places=9)
        self.assertAlmostEqual(r["cost_by_family"]["opus"], 42.2, places=9)

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

    def test_owner_identity_and_own_cwd_evidence_must_agree(self):
        issue_7 = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        issue_8 = "/Users/me/repo/.claude/worktrees/worktree-issue-8-other"
        cases = [
            ("aissue-7-owner-2-deadbeef", [issue_7], "7"),
            ("aissue-7-owner-2-deadbeef", [f"{issue_7}/scripts"], "7"),
            ("aissue-7-owner-2-deadbeef", [issue_8], None),
            ("aissue-7-owner-2-deadbeef", [issue_7, issue_8], None),
            ("aissue-7-owner-2-deadbeef", ["/tmp/issue-7-not-a-worktree"], None),
            ("areviewer-7-deadbeef", [issue_7], None),
            ("aissue-7-owner-0-deadbeef", [issue_7], None),
        ]
        for agent_id, cwds, expected in cases:
            with self.subTest(agent_id=agent_id, cwds=cwds):
                lines = [
                    assistant(f"m{index}", usage=USAGE_1, cwd=cwd, agent_id=agent_id, sidechain=True)
                    for index, cwd in enumerate(cwds)
                ]
                self.assertEqual(agent_costs.owner_issue(self.scan(lines)), expected)

    def test_exact_initial_envelope_qualifies_codex_skill_attribution(self):
        cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        for operation in ("plan-review", "diff-review"):
            with self.subTest(operation=operation):
                packet = "x" * 5000
                result = self.scan([
                    envelope_user("acodex-reviewer-7-deadbeef", cwd, operation, packet=packet),
                    assistant(
                        "m1",
                        usage=USAGE_1,
                        cwd=cwd,
                        agent_id="acodex-reviewer-7-deadbeef",
                        attribution_skill="codex-collaboration",
                        sidechain=True,
                    ),
                ])
                self.assertEqual(result["review_operation"], operation)
                self.assertEqual(result["attr_turns"], {f"codex-collaboration/{operation}": 1})

    def test_operation_words_outside_exact_root_envelope_are_not_evidence(self):
        cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        malformed = [
            record({
                "type": "user", "isSidechain": True, "agentId": "ahelper", "parentUuid": None,
                "message": {"role": "user", "content": "Discuss diff-review in prose"},
            }),
            envelope_user("ahelper", cwd, "plan-review", parent_uuid="not-root"),
            record({
                "type": "user", "isSidechain": True, "agentId": "ahelper", "cwd": cwd,
                "message": {
                    "role": "user",
                    "content": f"WORKTREE_ROOT: {cwd}\nREVIEW_OPERATION: diff-review\npacket",
                },
            }),
            record({
                "type": "user", "isSidechain": True, "agentId": "ahelper", "parentUuid": None,
                "message": {"role": "user", "content": f"REVIEW_OPERATION: plan-review\nWORKTREE_ROOT: {cwd}\npacket"},
            }),
        ]
        for index, first_record in enumerate(malformed):
            with self.subTest(index=index):
                result = self.scan([
                    first_record,
                    assistant(
                        "m1", usage=USAGE_1, cwd=cwd, agent_id="ahelper",
                        attribution_skill="codex-collaboration", sidechain=True,
                    ),
                ])
                self.assertIsNone(result["review_operation"])
                self.assertEqual(result["attr_turns"], {"codex-collaboration": 1})

    def test_only_one_declaration_in_the_initial_envelope_is_evidence(self):
        cwd = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        initial_prose = record({
            "type": "user", "isSidechain": True, "agentId": "ahelper", "parentUuid": None,
            "message": {"role": "user", "content": "Review this packet."},
        })
        later_envelope = self.scan([
            initial_prose,
            envelope_user("ahelper", cwd, "plan-review"),
            assistant(
                "m1", usage=USAGE_1, cwd=cwd, agent_id="ahelper",
                attribution_skill="codex-collaboration", sidechain=True,
            ),
        ])
        self.assertIsNone(later_envelope["review_operation"])
        self.assertEqual(later_envelope["attr_turns"], {"codex-collaboration": 1})

        for extra_operation in ("diff-review", "plan-review"):
            with self.subTest(extra_operation=extra_operation):
                duplicate = self.scan([
                    envelope_user(
                        "ahelper", cwd, "diff-review",
                        packet=f"REVIEW_OPERATION: {extra_operation}\nreview packet",
                    ),
                    assistant(
                        "m1", usage=USAGE_1, cwd=cwd, agent_id="ahelper",
                        attribution_skill="codex-collaboration", sidechain=True,
                    ),
                ])
                self.assertIsNone(duplicate["review_operation"])
                self.assertEqual(duplicate["attr_turns"], {"codex-collaboration": 1})


class ExecutorFallbackTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = []
        for index, usage in enumerate((USAGE_1, USAGE_2)):
            path = Path(self.tmp.name) / f"{index}.jsonl"
            path.write_text(assistant(f"m{index}", usage=usage), encoding="utf-8")
            self.paths.append(path)

    def assert_fallback(self, executor_factory, exception_name):
        original_scan = agent_costs.scan_file
        scanned = []

        def recording_scan(path):
            scanned.append(path)
            return original_scan(path)

        stderr = io.StringIO()
        with mock.patch.object(agent_costs, "scan_file", side_effect=recording_scan):
            with contextlib.redirect_stderr(stderr):
                actual = agent_costs.scan_paths(self.paths, executor_factory=executor_factory)
        expected = [original_scan(path) for path in self.paths]
        self.assertEqual(actual, expected)
        self.assertEqual(
            stderr.getvalue(),
            f"Process pool unavailable ({exception_name}); scanning sequentially.\n",
        )
        return scanned

    def test_pool_construction_failure_falls_back_in_order(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        self.assert_fallback(ConstructionFailure, "PermissionError")

    def test_partial_iteration_failure_discards_prefix_and_rescans_all(self):
        class IterationFailure:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def map(self, function, paths, chunksize):
                del chunksize
                paths = list(paths)

                def values():
                    yield function(paths[0])
                    raise RuntimeError("worker stream failed")

                return values()

        scanned = self.assert_fallback(IterationFailure, "RuntimeError")
        self.assertEqual(scanned, [self.paths[0]] + self.paths)

    def test_teardown_failure_discards_complete_mapping_and_rescans_all(self):
        class TeardownFailure:
            def __init__(self, **_kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                raise OSError("pool teardown failed")

            def map(self, function, paths, chunksize):
                del chunksize
                return [function(path) for path in paths]

        scanned = self.assert_fallback(TeardownFailure, "OSError")
        self.assertEqual(scanned, self.paths + self.paths)

    def test_sequential_scanner_failure_is_not_swallowed(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        with mock.patch.object(agent_costs, "scan_file", side_effect=ValueError("bad transcript")):
            with self.assertRaisesRegex(ValueError, "bad transcript"):
                agent_costs.scan_paths(self.paths, executor_factory=ConstructionFailure)


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

    def test_canonical_suspension_line_classifies_interrupted(self):
        line = "Suspended (blocked_on=usage_limit). Resume: /from-issue 101 --auto"
        self.assertEqual(agent_costs.classify_outcome(line), "interrupted")

    def test_interrupted_beats_blocked_regex_overlap(self):
        line = "Work paused. Suspended (blocked_on=human_gate). Resume: /from-issue 7 --auto"
        self.assertEqual(agent_costs.classify_outcome(line), "interrupted")

    def test_group_rollup_prefers_completed(self):
        g = agent_costs.new_group()
        g["outcomes"] = ["abandoned", "blocked", "completed"]
        self.assertEqual(agent_costs.group_outcome(g), "completed")
        g["outcomes"] = ["abandoned", "blocked"]
        self.assertEqual(agent_costs.group_outcome(g), "blocked")
        g["outcomes"] = []
        self.assertEqual(agent_costs.group_outcome(g), "-")

    def test_group_rollup_precedence_with_interrupted(self):
        g = agent_costs.new_group()
        g["outcomes"] = ["interrupted", "abandoned"]
        self.assertEqual(agent_costs.group_outcome(g), "interrupted")
        g["outcomes"] = ["blocked", "interrupted"]
        self.assertEqual(agent_costs.group_outcome(g), "interrupted")
        g["outcomes"] = ["completed", "interrupted"]
        self.assertEqual(agent_costs.group_outcome(g), "completed")


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
        project = root / "-Users-me-repo"
        project.mkdir()
        issue_7 = "/Users/me/repo/.claude/worktrees/worktree-issue-7-widget"
        issue_8 = "/Users/me/repo/.claude/worktrees/worktree-issue-8-other"
        (project / "sess1.jsonl").write_text(
            assistant(
                "root-1",
                usage=USAGE_1,
                cwd="/Users/me/repo",
                content=[{"type": "text", "text": "Dispatcher completed."}],
                stop_reason="end_turn",
            ),
            encoding="utf-8",
        )
        subdir = project / "sess1" / "subagents"
        subdir.mkdir(parents=True)
        (subdir / "owner-7.jsonl").write_text(
            assistant(
                "owner-7-1", usage=USAGE_1, cwd=issue_7,
                agent_id="aissue-7-owner-1-owner7", sidechain=True,
            ),
            encoding="utf-8",
        )
        (subdir / "owner-8.jsonl").write_text(
            assistant(
                "owner-8-1", usage=USAGE_1, cwd=issue_8,
                agent_id="aissue-8-owner-2-owner8", sidechain=True,
            ),
            encoding="utf-8",
        )
        (subdir / "helper.jsonl").write_text(
            assistant(
                "helper-1", usage=USAGE_1, cwd=issue_7,
                model="claude-helper-root-only", agent_id="ahelper-7-helper",
                sidechain=True,
            ),
            encoding="utf-8",
        )
        for operation, cwd in (("plan-review", issue_7), ("diff-review", issue_8)):
            agent_id = f"acodex-{operation}-transport"
            (subdir / f"{operation}.jsonl").write_text(
                "".join([
                    envelope_user(agent_id, cwd, operation),
                    assistant(
                        f"{operation}-1", usage=USAGE_1, cwd=cwd,
                        agent_id=agent_id, attribution_skill="codex-collaboration",
                        sidechain=True,
                    ),
                ]),
                encoding="utf-8",
            )
        self.projects = str(root)

    class DeterministicExecutor:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def map(self, function, paths, chunksize):
            del chunksize
            return [function(path) for path in paths]

    def run_main(self, executor_factory):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            agent_costs.main(
                ["--projects-dir", self.projects, "--days", "0"],
                executor_factory=executor_factory,
            )
        return stdout.getvalue(), stderr.getvalue()

    def test_dispatcher_owners_reviews_and_forced_fallback_are_truthful(self):
        class ConstructionFailure:
            def __init__(self, **_kwargs):
                raise PermissionError("semaphores denied")

        successful_stdout, successful_stderr = self.run_main(self.DeterministicExecutor)
        fallback_stdout, fallback_stderr = self.run_main(ConstructionFailure)
        self.assertEqual(successful_stderr, "")
        self.assertEqual(fallback_stdout, successful_stdout)
        self.assertEqual(
            fallback_stderr,
            "Process pool unavailable (PermissionError); scanning sequentially.\n",
        )

        self.assertRegex(successful_stdout, r"(?m)^#7\s+repo\s+")
        self.assertRegex(successful_stdout, r"(?m)^#8\s+repo\s+")
        self.assertRegex(successful_stdout, r"(?m)^\(multi-issue\)\s+repo\s+")
        self.assertIn("codex-collaboration/plan-review 1", successful_stdout)
        self.assertIn("codex-collaboration/diff-review 1", successful_stdout)
        self.assertIn("6 transcripts", successful_stdout)
        self.assertIn("5 subagents", successful_stdout)

        sessions = list(agent_costs.find_sessions(Path(self.projects), None))
        jobs = [
            (index, is_root, path)
            for index, (_home, roots, subs) in enumerate(sessions)
            for is_root, path in [(True, path) for path in roots] + [(False, path) for path in subs]
        ]
        ordered_results = [agent_costs.scan_file(path) for _index, _is_root, path in jobs]
        direct = agent_costs.fold_scan_totals([result for result in ordered_results if result])
        self.assertEqual(direct["turns"], 6)
        self.assertEqual(direct["fresh"], 60)
        self.assertEqual(direct["output"], 120)
        self.assertEqual(direct["cache_create"], 30)
        self.assertEqual(direct["cache_read"], 600)
        # five Opus 5 USAGE_1 calls at 10 x 5 + 20 x 25 + 5 x 6.25 + 100 x 0.50 = 631.25 per 1e6,
        # and the helper's unlisted ID at the Opus 5.5 row: 10 x 4 + 20 x 20 + 5 x 5 + 100 x 0.20 = 485
        self.assertAlmostEqual(direct["cost"], (5 * 631.25 + 485) / 1e6, places=12)
        self.assertIn("6 turns", successful_stdout)
        self.assertIn("fresh 60", successful_stdout)
        self.assertIn("cache_create 30", successful_stdout)
        self.assertIn("cache_read 600", successful_stdout)
        self.assertIn("output 120", successful_stdout)

        per_session = agent_costs.defaultdict(list)
        for (session_index, is_root, _path), result in zip(jobs, ordered_results):
            if result:
                per_session[session_index].append((is_root, result))
        groups, retained, kept_sessions, kept_files = agent_costs.build_groups(sessions, per_session)
        root_group = groups[("repo", agent_costs.MULTI_ISSUE)]
        self.assertEqual(root_group["models"]["claude-helper-root-only"], 1)
        self.assertNotIn("claude-helper-root-only", groups[("repo", "7")]["models"])
        self.assertEqual(root_group["sessions"], 1)
        self.assertEqual(groups[("repo", "7")]["sessions"], 0)
        self.assertEqual(groups[("repo", "8")]["sessions"], 0)
        self.assertEqual(sum(group["subagents"] for group in groups.values()), 5)
        self.assertEqual(sum(group["turns"] for group in groups.values()), direct["turns"])
        for field in agent_costs.TOKEN_FIELDS:
            self.assertEqual(sum(group[field] for group in groups.values()), direct[field])
        self.assertAlmostEqual(sum(group["cost"] for group in groups.values()), direct["cost"], places=12)
        self.assertEqual(len(retained), 6)
        self.assertEqual(kept_sessions, 1)
        self.assertEqual(kept_files, 6)

    def test_default_executor_degrades_concisely_when_environment_restricts_it(self):
        expected_stdout, expected_stderr = self.run_main(self.DeterministicExecutor)
        stdout, stderr = self.run_main(agent_costs.ProcessPoolExecutor)
        self.assertEqual(expected_stderr, "")
        self.assertEqual(stdout, expected_stdout)
        if stderr:
            self.assertRegex(
                stderr,
                r"\AProcess pool unavailable \([A-Za-z_][A-Za-z0-9_]*\); "
                r"scanning sequentially\.\n\Z",
            )


def codex_meta(session_id, rollout_id=None, cwd="/Users/me/repo",
               thread_source="user", parent=None, source=None):
    payload = {
        "session_id": session_id,
        "id": rollout_id or session_id,
        "cwd": cwd,
        "thread_source": thread_source,
        "originator": "codex-tui",
    }
    if thread_source == "subagent":
        payload["parent_thread_id"] = parent or session_id
        payload["source"] = {"subagent": {"thread_spawn": {
            "parent_thread_id": parent or session_id,
            "depth": 1, "agent_nickname": "Nash", "agent_role": None}}}
    if source is not None:
        payload["source"] = source
    return record({"timestamp": "2026-08-04T14:08:50.499Z",
                   "type": "session_meta", "payload": payload})


def codex_usage(inp, cached=0, write=0, out=0, reasoning=0, total=None):
    """One token_count event. `total` is the (untrustworthy) running counter."""
    last = {"input_tokens": inp, "cached_input_tokens": cached,
            "cache_write_input_tokens": write, "output_tokens": out,
            "reasoning_output_tokens": reasoning,
            "total_tokens": inp + out}
    running = dict(last) if total is None else dict(last, input_tokens=total)
    return record({"timestamp": "2026-08-04T14:08:55.871Z", "type": "event_msg",
                   "payload": {"type": "token_count",
                               "info": {"total_token_usage": running,
                                        "last_token_usage": last,
                                        "model_context_window": 258400}}})


def codex_response(response_id, inp, cached=0, write=0, out=0, reasoning=0):
    usage = {"input_tokens": inp, "cached_input_tokens": cached,
             "cache_write_input_tokens": write, "output_tokens": out,
             "reasoning_output_tokens": reasoning,
             "total_tokens": inp + out}
    return record({"timestamp": "2026-08-04T14:08:55.871Z", "type": "token_usage_record",
                   "payload": {"thread_id": "thread-1", "response_id": response_id,
                               "usage": usage}})


def codex_turn_context(model="gpt-5.6-sol", effort="xhigh"):
    return record({"timestamp": "2026-08-04T14:08:50.873Z", "type": "turn_context",
                   "payload": {"turn_id": "t1", "cwd": "/Users/me/repo",
                               "model": model, "effort": effort, "summary": "auto"}})


def codex_compacted():
    return record({"timestamp": "2026-08-04T14:20:00.000Z", "type": "event_msg",
                   "payload": {"type": "compacted"}})


class ScanCodexFileTest(unittest.TestCase):
    def write_rollout(self, *lines):
        tmp = Path(tempfile.mkdtemp())
        path = tmp / "rollout-2026-08-04T16-08-42-abc.jsonl"
        path.write_text("".join(lines), encoding="utf-8")
        return path

    def test_sums_last_token_usage_and_ignores_the_rebased_running_total(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_turn_context(),
            codex_usage(1000, cached=600, write=0, out=50, reasoning=20, total=1000),
            codex_compacted(),
            # After compaction the running counter rebases; summing it would
            # lose the pre-compaction turn, and reading the last one alone
            # would report 400 input tokens instead of 1400.
            codex_usage(400, cached=100, write=0, out=10, reasoning=5, total=400),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["input_total"], 1400)
        self.assertEqual(got["cache_read"], 700)
        self.assertEqual(got["cache_create"], 0)
        self.assertEqual(got["fresh"], 700)
        self.assertEqual(got["output"], 60)
        self.assertEqual(got["reasoning"], 25)
        self.assertEqual(got["turns"], 2)

    def test_replayed_legacy_snapshot_is_not_a_new_turn(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "rollout.jsonl"
            event = codex_usage(1000, cached=600, out=50)
            path.write_text("\n".join(json.dumps(x) for x in [
                json.loads(codex_meta("s1")), json.loads(event), json.loads(event),
            ]) + "\n", encoding="utf-8")
            result = agent_costs.scan_codex_file(path)
            self.assertEqual(result["input_total"], 1000)
            self.assertEqual(result["turns"], 1)
            self.assertEqual(result["measurement"]["duplicate_observations_skipped"], 1)

    def test_equal_legacy_calls_with_changed_cumulative_snapshots_are_distinct(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_usage(100, cached=50, out=10, total=100),
            codex_usage(100, cached=50, out=10, total=200),
        )
        result = agent_costs.scan_codex_file(path)
        self.assertEqual((result["input_total"], result["turns"]), (200, 2))

    def test_missing_cumulative_evidence_is_explicitly_ambiguous(self):
        event = json.loads(codex_usage(100))
        del event["payload"]["info"]["total_token_usage"]
        path = self.write_rollout(codex_meta("s1"), record(event))
        result = agent_costs.scan_codex_file(path)
        self.assertEqual(result["input_total"], 100)
        self.assertEqual(result["measurement"]["ambiguous_legacy_observations"], 1)
        self.assertEqual(result["measurement"]["missing_usage_observations"], 1)

    def test_modern_usage_wins_over_legacy_for_a_rollout(self):
        path = self.write_rollout(
            codex_meta("s1", source="cli"), codex_usage(1000, cached=600, out=50),
            codex_response("resp-1", 40, cached=20, out=4, reasoning=2),
        )
        result = agent_costs.scan_codex_file(path)
        self.assertTrue(result["is_root"])
        self.assertEqual((result["input_total"], result["output"], result["turns"]), (40, 4, 1))
        self.assertEqual(result["measurement"]["selected_source_counts"],
                         {"modern": 1, "legacy": 0})
        self.assertEqual(result["measurement"]["legacy_observations_excluded"], 1)

    def test_invalid_modern_usage_does_not_claim_a_measured_zero(self):
        invalid = json.loads(codex_response("resp-1", 10))
        invalid["payload"]["usage"]["cached_input_tokens"] = True
        path = self.write_rollout(codex_meta("s1", source="cli"), record(invalid))
        result = agent_costs.scan_codex_file(path)
        self.assertFalse(result["usage_measured"])
        self.assertEqual(result["measurement"]["invalid_usage_observations"], 1)

    def test_missing_only_codex_run_projects_null_tokens_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            missing = record({"type": "token_usage_record", "payload": {
                "thread_id": "thread-1", "response_id": "resp-1",
            }})
            (day / "missing.jsonl").write_text(
                codex_meta("s1", source="cli") + missing, encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        record_document = agent_costs.build_record(
            {"codex": {"cost_basis": "subscription", "groups": groups}},
            {"days": 0, "cutoff_epoch": None, "strata": ["codex"], "sources": {}})
        run = record_document["strata"]["codex"]["runs"][0]
        self.assertIsNone(run["tokens"]["input_total"])
        self.assertEqual(run["measurement"]["missing_usage_observations"], 1)

    def public_codex_run_for_sessions(self, sessions):
        """Project same-cwd sessions through the public record shape."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            for name, session_id, tokens in sessions:
                contents = codex_meta(session_id, source="cli")
                if tokens is None:
                    contents += record({"type": "token_usage_record", "payload": {
                        "thread_id": session_id, "response_id": f"{session_id}-response",
                    }})
                else:
                    contents += codex_usage(tokens)
                (day / name).write_text(contents, encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        document = agent_costs.build_record(
            {"codex": {"cost_basis": "subscription", "groups": groups}},
            {"days": 0, "cutoff_epoch": None, "strata": ["codex"], "sources": {}})
        return document["strata"]["codex"]["runs"][0]

    def test_same_project_missing_session_before_measured_session_projects_measurement(self):
        run = self.public_codex_run_for_sessions((
            ("missing.jsonl", "a-missing", None),
            ("measured.jsonl", "z-measured", 100),
        ))
        self.assertEqual((run["tokens"]["input_total"], run["tokens"]["fresh"],
                          run["turns"]), (100, 100, 1))
        self.assertEqual((run["measurement"]["files_selected"],
                          run["measurement"]["files_with_usage"],
                          run["measurement"]["missing_usage_observations"]), (2, 1, 1))

    def test_same_project_measured_session_before_missing_session_projects_measurement(self):
        run = self.public_codex_run_for_sessions((
            ("measured.jsonl", "a-measured", 100),
            ("missing.jsonl", "z-missing", None),
        ))
        self.assertEqual((run["tokens"]["input_total"], run["tokens"]["fresh"],
                          run["turns"]), (100, 100, 1))
        self.assertEqual((run["measurement"]["files_selected"],
                          run["measurement"]["files_with_usage"],
                          run["measurement"]["missing_usage_observations"]), (2, 1, 1))

    def test_same_project_multiple_missing_sessions_project_null_and_keep_coverage(self):
        run = self.public_codex_run_for_sessions((
            ("first.jsonl", "a-missing", None),
            ("second.jsonl", "z-missing", None),
        ))
        for field in ("input_total", "fresh", "cache_create", "cache_read", "output",
                      "reasoning"):
            self.assertIsNone(run["tokens"][field], field)
        self.assertIsNone(run["turns"])
        self.assertEqual((run["measurement"]["files_selected"],
                          run["measurement"]["files_with_usage"],
                          run["measurement"]["missing_usage_observations"]), (2, 0, 2))

    def test_modern_source_subagent_metadata_classifies_a_child(self):
        path = self.write_rollout(
            codex_meta("s1", rollout_id="child", thread_source="user",
                       source={"subagent": {}}),
            codex_response("resp-1", 10),
        )
        self.assertFalse(agent_costs.scan_codex_file(path)["is_root"])

    def test_copied_modern_response_across_files_counts_once_at_the_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            (day / "root.jsonl").write_text(
                codex_meta("s1", source="cli") + codex_response("resp-1", 100),
                encoding="utf-8")
            (day / "child.jsonl").write_text(
                codex_meta("s1", rollout_id="child", thread_source="subagent")
                + codex_response("resp-1", 100), encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        group = groups[("repo", None)]
        self.assertEqual((group["fresh"], group["turns"]), (100, 1))
        self.assertEqual((group["sessions"], group["subagents"]), (1, 1))
        self.assertEqual(group["measurement"]["selected_source_counts"],
                         {"modern": 1, "legacy": 0})
        self.assertEqual(group["measurement"]["duplicate_observations_skipped"], 1)

    def test_modern_wins_when_one_rollout_is_split_across_legacy_and_modern_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            (day / "legacy.jsonl").write_text(
                codex_meta("s1", rollout_id="r1", source="cli") + codex_usage(100, out=10),
                encoding="utf-8")
            (day / "modern.jsonl").write_text(
                codex_meta("s1", rollout_id="r1", source="cli")
                + codex_response("resp-1", 40, out=4), encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        group = groups[("repo", None)]
        self.assertEqual((group["fresh"], group["output"], group["turns"]), (40, 4, 1))
        self.assertEqual(group["measurement"]["selected_source_counts"],
                         {"modern": 1, "legacy": 0})
        self.assertEqual(group["measurement"]["legacy_observations_excluded"], 1)

    def test_conflicting_modern_duplicates_are_ambiguous_and_not_summed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            for name, tokens in (("one.jsonl", 100), ("two.jsonl", 200)):
                (day / name).write_text(
                    codex_meta("s1", source="cli") + codex_response("resp-1", tokens),
                    encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        group = groups[("repo", None)]
        self.assertIsNone(group["fresh"])
        self.assertEqual(group["measurement"]["ambiguous_modern_observations"], 2)

    def test_same_file_modern_conflict_has_the_cross_file_coverage_count(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            (day / "conflict.jsonl").write_text(
                codex_meta("s1", source="cli")
                + codex_response("resp-1", 100) + codex_response("resp-1", 200),
                encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        group = groups[("repo", None)]
        self.assertIsNone(group["fresh"])
        self.assertEqual(group["measurement"]["ambiguous_modern_observations"], 2)

    def test_legacy_copy_cannot_restore_a_conflicted_modern_rollout(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            (day / "legacy.jsonl").write_text(
                codex_meta("s1", rollout_id="r1", source="cli") + codex_usage(100, out=10),
                encoding="utf-8")
            (day / "modern-conflict.jsonl").write_text(
                codex_meta("s1", rollout_id="r1", source="cli")
                + codex_response("resp-1", 40, out=4) + codex_response("resp-1", 50, out=5),
                encoding="utf-8")
            groups = agent_costs.collect_codex_groups(
                root, None, executor_factory=EndToEndTest.DeterministicExecutor)
        group = groups[("repo", None)]
        self.assertIsNone(group["fresh"])
        self.assertEqual(group["measurement"]["legacy_observations_excluded"], 1)
        self.assertEqual(group["measurement"]["ambiguous_modern_observations"], 2)

    def test_cached_and_reasoning_are_subsets_not_addends(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_usage(1000, cached=900, write=100, out=80, reasoning=70),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["input_total"], 1000)      # not 1900
        self.assertEqual(got["fresh"], 0)               # 1000 - 900 - 100
        self.assertEqual(got["output"], 80)             # not 150
        self.assertEqual(got["reasoning"], 70)

    def test_peak_ctx_is_the_largest_single_turn_input(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_usage(500), codex_usage(9000), codex_usage(700),
        )
        self.assertEqual(agent_costs.scan_codex_file(path)["peak_ctx"], 9000)

    def test_root_and_subagent_classification_and_identity(self):
        root = self.write_rollout(codex_meta("s1"), codex_usage(10))
        sub = self.write_rollout(
            codex_meta("s1", rollout_id="r2", thread_source="subagent",
                       cwd="/Users/me/repo/.claude/worktrees/issue-120-x"),
            codex_usage(20))
        got_root = agent_costs.scan_codex_file(root)
        got_sub = agent_costs.scan_codex_file(sub)
        self.assertTrue(got_root["is_root"])
        self.assertEqual(got_root["rollout_id"], "s1")
        self.assertFalse(got_sub["is_root"])
        self.assertEqual(got_sub["session_id"], "s1")
        self.assertEqual(got_sub["rollout_id"], "r2")
        self.assertEqual(got_sub["cwd"],
                         "/Users/me/repo/.claude/worktrees/issue-120-x")

    def test_models_and_efforts_come_from_turn_context(self):
        path = self.write_rollout(
            codex_meta("s1"),
            codex_turn_context("gpt-5.6-sol", "xhigh"),
            codex_turn_context("gpt-5.6-sol", "xhigh"),
            codex_turn_context("gpt-5.6", "medium"),
            codex_usage(10),
        )
        got = agent_costs.scan_codex_file(path)
        self.assertEqual(got["models"], {"gpt-5.6-sol": 2, "gpt-5.6": 1})
        self.assertEqual(got["efforts"], {"xhigh": 2, "medium": 1})

    def test_no_session_meta_and_unreadable_file_return_none(self):
        headless = self.write_rollout(codex_usage(10))
        self.assertIsNone(agent_costs.scan_codex_file(headless))
        missing = Path(tempfile.mkdtemp()) / "absent.jsonl"
        self.assertIsNone(agent_costs.scan_codex_file(missing))

    def test_malformed_line_is_skipped_not_raised(self):
        path = self.write_rollout(
            codex_meta("s1"),
            '{"type":"event_msg","payload":{"type":"token_count"\n',
            codex_usage(10))
        self.assertEqual(agent_costs.scan_codex_file(path)["input_total"], 10)



def claude_tree(tmp, dir_name="-Users-me-repo-issue-120-x", session="s1"):
    """A one-session Claude fixture: 2 assistant turns, one deduped message id."""
    proj = tmp / dir_name
    proj.mkdir(parents=True)
    usage = {"input_tokens": 100, "cache_creation_input_tokens": 200,
             "cache_read_input_tokens": 3000, "output_tokens": 40}
    (proj / f"{session}.jsonl").write_text(
        assistant("m1", usage, cwd="/Users/me/repo")
        + assistant("m1", usage, cwd="/Users/me/repo")   # duplicate id: deduped
        + assistant("m2", usage, cwd="/Users/me/repo"),
        encoding="utf-8")
    return proj


def codex_tree(tmp, cwd="/Users/me/repo/.claude/worktrees/issue-120-x"):
    day = tmp / "2026" / "08" / "04"
    day.mkdir(parents=True)
    (day / "rollout-root.jsonl").write_text(
        codex_meta("s1", cwd=cwd) + codex_turn_context() + codex_usage(
            1000, cached=600, out=50, reasoning=20),
        encoding="utf-8")
    (day / "rollout-sub.jsonl").write_text(
        codex_meta("s1", rollout_id="r2", thread_source="subagent", cwd=cwd)
        + codex_usage(500, cached=100, out=10, reasoning=5),
        encoding="utf-8")
    return tmp


def run_main(*argv):
    """main() with stdout captured; returns (stdout, SystemExit code or None)."""
    buf = io.StringIO()
    code = None
    with contextlib.redirect_stdout(buf):
        try:
            agent_costs.main(list(argv),
                             executor_factory=EndToEndTest.DeterministicExecutor)
        except SystemExit as exit_error:
            code = exit_error.code
    return buf.getvalue(), code


class ExecutionTelemetryRoutingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    REQUEST_HOST_ABSENT = object()

    def claude_pair(self, *, request_at="2026-09-20T10:05:00Z",
                    execution_at="2026-09-20T10:06:00Z",
                    request_host=REQUEST_HOST_ABSENT, request_model="opus",
                    request_effort="high", execution_model="claude-opus-5-20260901",
                    execution_effort="high", child_prefix=""):
        project = self.root / "-Users-me-repo-issue-120-x"
        child_dir = project / "s1" / "subagents"
        child_dir.mkdir(parents=True, exist_ok=True)
        launch_input = {"subagent_type": "reviewer", "role": "reviewer",
                        "prompt": "review"}
        if request_model is not None:
            launch_input["model"] = request_model
        if request_effort is not None:
            launch_input["effort"] = request_effort
        if request_host is not self.REQUEST_HOST_ABSENT:
            launch_input["host"] = request_host
        launch = {"type": "tool_use", "id": "toolu-route-1", "name": "Agent",
                  "input": launch_input}
        root_file = project / "s1.jsonl"
        root_file.write_text(assistant("launch", usage=USAGE_1, content=[launch],
                                       timestamp=request_at, version="2.1.0")
                             + agent_result("toolu-route-1", "agent-child-1",
                                            timestamp="2026-09-20T10:05:30Z"), encoding="utf-8")
        (child_dir / "child.jsonl").write_text(child_prefix +
            assistant("child", usage=USAGE_2, model=execution_model, effort=execution_effort,
                      agent_id="agent-child-1", sidechain=True, timestamp=execution_at,
                      version="2.1.0"), encoding="utf-8")
        return root_file

    def json_record(self, *extra):
        raw, code = run_main("--projects-dir", str(self.root), "--days", "1", "--format", "json",
                             "--events-since", "2026-09-20T10:00:00Z",
                             "--events-before", "2026-09-20T11:00:00Z", *extra)
        self.assertIsNone(code)
        return json.loads(raw)

    def test_exact_claude_request_result_child_pair_is_observed(self):
        old_file = self.claude_pair()
        os.utime(old_file, (1, 1))
        telemetry = self.json_record()["execution_telemetry"]
        self.assertEqual(telemetry["event_window"], {"start": "2026-09-20T10:00:00Z",
                                                      "end": "2026-09-20T11:00:00Z"})
        self.assertEqual(telemetry["producer"], {"name": "agent-costs", "version": 1,
                         "harness_versions": {"claude": ["2.1.0"]}})
        self.assertEqual(telemetry["source_coverage"]["routing"],
                         {"state": "full", "eligible_events": 1, "paired_events": 1, "reasons": []})
        self.assertEqual(telemetry["source_coverage"]["source_only"], {})
        self.assertEqual(len(telemetry["runs"]), 1)
        self.assertEqual(telemetry["runs"][0]["run_id"], "claude:repo:120")
        self.assertEqual(telemetry["runs"][0]["routing"]["coverage"],
                         telemetry["source_coverage"]["routing"])
        observation = telemetry["runs"][0]["routing"]["observations"][0]
        self.assertEqual(observation["declaration"], {"dispatch_id": None, "role": "reviewer",
                                                        "authority": "runtime-agent-type"})
        self.assertEqual(observation["requested"], {"host": "claude", "model": "opus", "effort": "high"})
        self.assertEqual(observation["configured"], {"host": None, "model": None, "effort": None})
        self.assertEqual(observation["observed"], {"host": "claude", "model": "claude-opus-5-20260901",
                                                     "effort": "high", "authority": "assistant-execution"})
        self.assertIsNone(observation["escalation"])
        self.assertEqual((observation["count"], observation["first_event_at"], observation["last_event_at"]),
                         (1, "2026-09-20T10:06:00Z", "2026-09-20T10:06:00Z"))
        self.assertEqual(tuple(telemetry["runs"][0]["scheduling"]),
                         agent_costs.SCHEDULING_METRICS)

    def test_replayed_result_preserves_one_exact_pair_but_conflicts_do_not(self):
        root = self.claude_pair()
        replay = agent_result("toolu-route-1", "agent-child-1",
                              timestamp="2026-09-20T10:05:30Z")
        root.write_text(root.read_text(encoding="utf-8") + replay, encoding="utf-8")
        coverage = self.json_record()["execution_telemetry"]["source_coverage"]["routing"]
        self.assertEqual(coverage, {"state": "full", "eligible_events": 1,
                                    "paired_events": 1, "reasons": []})
        root.write_text(root.read_text(encoding="utf-8") + agent_result(
            "toolu-route-1", "agent-child-2", timestamp="2026-09-20T10:05:31Z"),
                        encoding="utf-8")
        coverage = self.json_record()["execution_telemetry"]["source_coverage"]["routing"]
        self.assertEqual((coverage["eligible_events"], coverage["paired_events"]), (2, 0))

    def test_harness_versions_exclude_old_root_history(self):
        root = self.claude_pair()
        root.write_text(assistant("old", usage=USAGE_1, timestamp="2026-09-19T10:00:00Z",
                                  version="old-runtime") + root.read_text(encoding="utf-8"),
                        encoding="utf-8")
        self.assertEqual(self.json_record()["execution_telemetry"]["producer"]["harness_versions"],
                         {"claude": ["2.1.0"]})

    def test_requested_host_missing_or_conflicting_is_null_with_reason(self):
        for host, reason in ((None, "request_host_missing"), ("codex", "request_host_conflict")):
            with self.subTest(host=host):
                self.claude_pair(request_host=host)
                telemetry = self.json_record()["execution_telemetry"]
                self.assertIsNone(telemetry["runs"][0]["routing"]["observations"][0]["requested"]["host"])
                self.assertIn({"code": reason, "count": 1}, telemetry["source_coverage"]["routing"]["reasons"])

    def test_event_window_uses_event_time_while_accounting_keeps_file_mtime(self):
        old_file = self.claude_pair(); os.utime(old_file, (1, 1))
        os.utime(old_file.parent / "s1" / "subagents" / "child.jsonl", (1, 1))
        record_value = self.json_record()
        self.assertEqual(record_value["strata"]["claude"]["runs"], [])
        self.assertEqual(record_value["execution_telemetry"]["runs"][0]["routing"]["observations"][0]["count"], 1)

    def test_missing_execution_timestamp_is_inconclusive_not_outside(self):
        self.claude_pair(execution_at=None)
        routing = self.json_record()["execution_telemetry"]["source_coverage"]["routing"]
        self.assertEqual(routing["state"], "none")
        self.assertIn({"code": "timestamp_missing", "count": 1}, routing["reasons"])

    def test_multi_turn_child_selects_final_execution_once(self):
        earlier = assistant("child-turn-1", usage=USAGE_2,
                            model="claude-opus-5-20260901", effort="high",
                            agent_id="agent-child-1", sidechain=True,
                            timestamp="2026-09-20T10:05:45Z", version="2.1.0")
        self.claude_pair(child_prefix=earlier)
        routing = self.json_record()["execution_telemetry"]["runs"][0]["routing"]
        self.assertEqual(routing["coverage"],
                         {"state": "full", "eligible_events": 1,
                          "paired_events": 1, "reasons": []})
        self.assertEqual(routing["observations"][0]["count"], 1)
        self.assertEqual(routing["observations"][0]["last_event_at"],
                         "2026-09-20T10:06:00Z")

    def test_missing_request_or_execution_tiers_are_paired_with_reasons(self):
        self.claude_pair(request_model=None, request_effort=None)
        routing = self.json_record()["execution_telemetry"]["runs"][0]["routing"]
        self.assertEqual(routing["coverage"]["paired_events"], 1)
        self.assertIn({"code": "request_missing", "count": 1},
                      routing["coverage"]["reasons"])
        self.claude_pair(execution_model=None, execution_effort=None)
        routing = self.json_record()["execution_telemetry"]["runs"][0]["routing"]
        self.assertEqual(routing["coverage"]["paired_events"], 1)
        self.assertIn({"code": "execution_model_missing", "count": 1},
                      routing["coverage"]["reasons"])
        self.assertIn({"code": "execution_effort_missing", "count": 1},
                      routing["coverage"]["reasons"])

    def test_unpaired_event_flags_and_invalid_range_are_usage_errors(self):
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(self.root), "--format", "json",
                                 "--events-since", "2026-09-20T10:00:00Z")
        self.assertEqual((out, code), ("", 2))

        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(self.root), "--format", "json",
                                 "--events-since", "2026-09-20T11:00:00Z",
                                 "--events-before", "2026-09-20T10:00:00Z")
        self.assertEqual((out, code), ("", 2))

    def test_codex_turn_context_is_configured_and_not_observed(self):
        codex = self.root / "codex" / "2026" / "09" / "20"; codex.mkdir(parents=True)
        (codex / "rollout.jsonl").write_text(
            codex_meta("thread-1", thread_source="subagent", source={"subagent": {"thread_spawn": {
                "parent_thread_id": "parent", "depth": 1, "agent_role": "reviewer",
                "model": "gpt-5.6-sol", "effort": "high"}}})
            + codex_turn_context("gpt-5.6-sol", "high") + codex_usage(10), encoding="utf-8")
        raw, code = run_main("--projects-dir", "/nonexistent/claude", "--codex-sessions", str(self.root / "codex"),
                             "--strata", "codex", "--format", "json", "--days", "0",
                             "--events-since", "2026-08-04T00:00:00Z", "--events-before", "2026-08-05T00:00:00Z")
        self.assertIsNone(code)
        observation = json.loads(raw)["execution_telemetry"]["runs"][0]["routing"]["observations"][0]
        self.assertEqual(observation["configured"], {"host": "codex", "model": "gpt-5.6-sol", "effort": "high"})
        self.assertEqual(observation["observed"], {"host": "codex", "model": None, "effort": None,
                                                    "authority": "codex-rollout"})

    def test_unbounded_direct_projection_and_shared_transport_are_inconclusive(self):
        rec = agent_costs.build_record({}, {})
        self.assertIn({"code": "cohort_incomplete", "count": 1},
                      rec["execution_telemetry"]["source_coverage"]["routing"]["reasons"])
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "reviewer"}, reasons)["authority"], "unknown")
        self.assertEqual(reasons["role_ambiguous"], 1)

    def test_the_shared_implementer_type_is_ambiguous_without_a_declared_role(self):
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "implementer"}, reasons),
                         {"dispatch_id": None, "role": None, "authority": "unknown"})
        self.assertEqual(reasons["role_ambiguous"], 1)
        self.assertEqual(reasons["dispatch_missing"], 1)
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "reviewer-lite"}, reasons),
                         {"dispatch_id": None, "role": "reviewer-lite",
                          "authority": "runtime-agent-type"})
        self.assertEqual(reasons["role_ambiguous"], 0)

    def test_the_shared_issue_owner_type_is_ambiguous_without_a_declared_role(self):
        reasons = agent_costs.Counter()
        self.assertEqual(agent_costs._declaration({"subagent_type": "issue-owner"}, reasons),
                         {"dispatch_id": None, "role": None, "authority": "unknown"})
        self.assertEqual(reasons["role_ambiguous"], 1)
        self.assertEqual(reasons["dispatch_missing"], 1)
        for role in ("issue-owner", "auto-owner", "ship-owner"):
            with self.subTest(role=role):
                reasons = agent_costs.Counter()
                self.assertEqual(
                    agent_costs._declaration({"subagent_type": "issue-owner", "role": role,
                                              "dispatch_id": "from-issue-auto-owner"}, reasons),
                    {"dispatch_id": "from-issue-auto-owner", "role": role,
                     "authority": "structured-dispatch"})
                self.assertEqual(reasons["role_ambiguous"], 0)

    def test_a_declared_implementer_role_is_accepted_on_either_tier(self):
        for role in ("task-implementer", "implementer"):
            with self.subTest(role=role):
                reasons = agent_costs.Counter()
                self.assertEqual(
                    agent_costs._declaration({"subagent_type": "implementer", "role": role,
                                              "dispatch_id": "sdd-nonmechanical-implementation"},
                                             reasons),
                    {"dispatch_id": "sdd-nonmechanical-implementation", "role": role,
                     "authority": "structured-dispatch"})
                self.assertEqual(reasons["role_ambiguous"], 0)
                reasons = agent_costs.Counter()
                self.assertEqual(
                    agent_costs._declaration({"role": role}, reasons),
                    {"dispatch_id": None, "role": role, "authority": "runtime-agent-type"})

    def test_unspawned_codex_evidence_respects_the_event_window(self):
        codex = self.root / "codex" / "2026"; codex.mkdir(parents=True)
        spawned = codex_meta("thread-1", thread_source="subagent", source={"subagent": {"thread_spawn": {
            "agent_role": "reviewer", "model": "gpt", "effort": "high"}}}) + codex_turn_context()
        outside = codex_meta("thread-2", thread_source="subagent", source={"subagent": {}}).replace(
            "2026-08-04T14:08:50.499Z", "2026-08-05T14:08:50.499Z")
        (codex / "spawned.jsonl").write_text(spawned, encoding="utf-8")
        (codex / "outside.jsonl").write_text(outside, encoding="utf-8")
        raw, code = run_main("--projects-dir", "/missing", "--codex-sessions", str(self.root / "codex"),
                             "--strata", "codex", "--format", "json", "--days", "0",
                             "--events-since", "2026-08-04T00:00:00Z", "--events-before", "2026-08-05T00:00:00Z")
        self.assertIsNone(code)
        self.assertEqual(json.loads(raw)["execution_telemetry"]["source_coverage"]["source_only"], {})


class ExecutionTelemetrySchedulingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.projects = self.root / "claude"
        self.projects.mkdir()

    def run_record(self, *, bounded=True, strata="claude"):
        args = ["--projects-dir", str(self.projects), "--days", "0", "--format", "json"]
        if strata != "claude":
            codex_root = self.root / "codex"
            codex_root.mkdir(exist_ok=True)
            args += ["--strata", strata, "--codex-sessions", str(codex_root)]
        if bounded:
            args += ["--events-since", "2026-09-20T10:00:00Z",
                     "--events-before", "2026-09-20T11:00:00Z"]
        raw, code = run_main(*args)
        self.assertIsNone(code)
        return json.loads(raw)

    def write_root(self, *lines):
        project = self.projects / "-Users-me-repo-issue-120-x"
        project.mkdir(parents=True, exist_ok=True)
        (project / "s1.jsonl").write_text("".join(lines), encoding="utf-8")

    def test_complete_bounded_source_distinguishes_measured_zero_from_null(self):
        self.write_root(assistant("ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z",
                                  version="2.1.0", stop_reason="end_turn"))
        telemetry = self.run_record()["execution_telemetry"]
        scheduling = telemetry["runs"][0]["scheduling"]
        self.assertEqual(tuple(scheduling), agent_costs.SCHEDULING_METRICS)
        self.assertEqual(scheduling["spawn_attempts"], {
            "value": 0, "coverage": {"state": "full", "eligible_events": 0,
            "paired_events": 0, "reasons": []}, "cohort_digest": agent_costs.cohort_digest([])})
        for name in agent_costs.SCHEDULING_METRICS[1:]:
            self.assertIsNone(scheduling[name]["value"], name)
            self.assertEqual(scheduling[name]["coverage"]["state"], "none", name)
            self.assertIn({"code": "source_unsupported", "count": 1},
                          scheduling[name]["coverage"]["reasons"], name)
            self.assertIsNone(scheduling[name]["cohort_digest"], name)
        self.assertEqual(telemetry["source_coverage"]["scheduling"]["spawn_attempts"],
                         scheduling["spawn_attempts"]["coverage"])

    def test_spawn_attempts_are_event_time_selected_and_tool_id_deduped(self):
        launch = {"type": "tool_use", "id": "toolu-spawn", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "prompt": "review"}}
        outside = {"type": "tool_use", "id": "toolu-outside", "name": "Agent",
                   "input": {"subagent_type": "reviewer", "prompt": "old"}}
        self.write_root(
            assistant("outside", usage=USAGE_1, content=[outside], timestamp="2026-09-20T09:59:59Z", version="2.1.0"),
            assistant("inside", usage=USAGE_1, content=[launch], timestamp="2026-09-20T10:05:00Z", version="2.1.0"),
            assistant("inside", usage=USAGE_1, content=[launch], timestamp="2026-09-20T10:05:00Z", version="2.1.0"))
        metric = self.run_record()["execution_telemetry"]["runs"][0]["scheduling"]["spawn_attempts"]
        self.assertEqual(metric["value"], 1)
        self.assertEqual(metric["coverage"]["state"], "full")
        self.assertEqual(metric["coverage"]["eligible_events"], 1)
        self.assertEqual(metric["coverage"]["paired_events"], 1)

    def test_conflicting_replayed_launch_timestamps_leave_spawn_attempts_unavailable(self):
        launch = {"type": "tool_use", "id": "toolu-conflicting-time", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "prompt": "review"}}
        self.write_root(
            assistant("first", usage=USAGE_1, content=[launch],
                      timestamp="2026-09-20T10:05:00Z", version="2.1.0"),
            assistant("replayed", usage=USAGE_1, content=[launch],
                      timestamp="2026-09-20T10:06:00Z", version="2.1.0"))
        metric = self.run_record()["execution_telemetry"]["runs"][0]["scheduling"]["spawn_attempts"]
        self.assertIsNone(metric["value"])
        self.assertEqual(metric["coverage"], {
            "state": "none", "eligible_events": 1, "paired_events": 0,
            "reasons": [{"code": "timestamp_missing", "count": 1}],
        })
        self.assertIsNone(metric["cohort_digest"])

    def test_missing_timestamp_and_unbounded_cohort_do_not_project_a_zero(self):
        launch = {"type": "tool_use", "id": "toolu-no-time", "name": "Agent",
                  "input": {"subagent_type": "reviewer", "prompt": "review"}}
        self.write_root(assistant("launch", usage=USAGE_1, content=[launch], timestamp=None, version="2.1.0"))
        bounded = self.run_record()["execution_telemetry"]["runs"][0]["scheduling"]["spawn_attempts"]
        self.assertIsNone(bounded["value"])
        self.assertIn({"code": "timestamp_missing", "count": 1}, bounded["coverage"]["reasons"])
        unbounded = self.run_record(bounded=False)["execution_telemetry"]["runs"][0]["scheduling"]["spawn_attempts"]
        self.assertIsNone(unbounded["value"])
        self.assertIn({"code": "cohort_incomplete", "count": 1}, unbounded["coverage"]["reasons"])

    def test_telemetry_contains_no_scheduling_verdict_vocabulary(self):
        self.write_root(assistant("ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z",
                                  version="2.1.0", stop_reason="end_turn"))
        encoded = json.dumps(self.run_record()["execution_telemetry"], sort_keys=True).lower()
        for forbidden in ("waste", "cheap", "useful", "savings", "billing", "utilization"):
            self.assertNotIn(forbidden, encoded)

    def test_selected_empty_codex_contributes_without_a_run(self):
        self.write_root(assistant("ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z",
                                  version="2.1.0", stop_reason="end_turn"))
        telemetry = self.run_record(strata="both")["execution_telemetry"]
        self.assertFalse(any(run["run_id"].startswith("codex:") for run in telemetry["runs"]))
        codex = telemetry["source_coverage"]["source_only"]["codex"]
        self.assertEqual(codex["routing"], {"state": "none", "eligible_events": 0, "paired_events": 0,
                         "reasons": [{"code": "runtime_version_missing", "count": 1}]})
        for name in agent_costs.SCHEDULING_METRICS:
            self.assertEqual(codex["scheduling"][name], {"state": "none", "eligible_events": 0,
                             "paired_events": 0, "reasons": [{"code": "source_unsupported", "count": 1}]})
        self.assertEqual(telemetry["source_coverage"]["routing"]["reasons"], [
            {"code": "runtime_version_missing", "count": 2}])
        self.assertEqual(telemetry["source_coverage"]["scheduling"]["spawn_attempts"],
                         codex["scheduling"]["spawn_attempts"])

    def test_scheduling_only_versionless_root_preserves_routing_coverage(self):
        self.write_root(assistant("ordinary", usage=USAGE_1, timestamp="2026-09-20T10:05:00Z"))
        telemetry = self.run_record()["execution_telemetry"]
        expected = {"state": "none", "eligible_events": 0, "paired_events": 0,
                    "reasons": [{"code": "runtime_version_missing", "count": 1}]}
        self.assertEqual(telemetry["runs"][0]["routing"]["coverage"], expected)
        self.assertEqual(telemetry["source_coverage"]["routing"], expected)
        self.assertEqual(telemetry["runs"][0]["scheduling"]["spawn_attempts"]["value"], 0)

    def test_spawn_attempts_deduplicate_identical_tool_ids_across_root_files(self):
        project = self.projects / "-Users-me-repo-issue-120-x"
        project.mkdir(parents=True)
        launch = {"type": "tool_use", "id": "toolu-copied", "name": "Task",
                  "input": {"subagent_type": "reviewer"}}
        line = assistant("copied", usage=USAGE_1, content=[launch],
                         timestamp="2026-09-20T10:05:00Z", version="2.1.0")
        (project / "s1.jsonl").write_text(line, encoding="utf-8")
        (project / "s2.jsonl").write_text(line, encoding="utf-8")
        metric = self.run_record()["execution_telemetry"]["runs"][0]["scheduling"]["spawn_attempts"]
        self.assertEqual((metric["value"], metric["coverage"]["eligible_events"],
                          metric["coverage"]["paired_events"]), (1, 1, 1))

    def test_future_token_and_slot_pairs_require_declared_digest_shapes(self):
        full = {"state": "full", "eligible_events": 1, "paired_events": 1, "reasons": []}
        event_window = {"start": "2026-09-20T10:00:00Z", "end": "2026-09-20T11:00:00Z"}
        metrics = {name: agent_costs.unsupported_metric() for name in agent_costs.SCHEDULING_METRICS}
        for name, value in (("wait_input_tokens", 1), ("covered_input_tokens", 2)):
            metrics[name] = {"value": value, "coverage": full, "cohort_digest": None}
        with self.assertRaises(ValueError):
            agent_costs._validate_scheduling(metrics, event_window)
        token_digest = agent_costs.cohort_digest([("toolu-1",)])
        for name, value in (("wait_input_tokens", 1), ("covered_input_tokens", 2)):
            metrics[name] = {"value": value, "coverage": full, "cohort_digest": token_digest}
        slot_digest = telemetry_digest(event_window)
        self.assertNotEqual(slot_digest, agent_costs.cohort_digest([tuple(event_window.values())]))
        for name, value in (("slot_capacity_seconds", 10), ("claimed_slot_seconds", 5)):
            metrics[name] = {"value": value, "coverage": full, "cohort_digest": slot_digest}
        agent_costs._validate_scheduling(metrics, event_window)
        for name in ("slot_capacity_seconds", "claimed_slot_seconds"):
            metrics[name]["cohort_digest"] = agent_costs.cohort_digest([tuple(event_window.values())])
        with self.assertRaises(ValueError):
            agent_costs._validate_scheduling(metrics, event_window)


class BuildRecordTest(unittest.TestCase):
    def strata(self):
        claude = agent_costs.new_group()
        claude.update(fresh=100, cache_create=200, cache_read=3000, output=40,
                      cost=1.5, turns=2, sessions=1, peak_ctx=3300)
        claude["models"].update({"claude-opus-5": 2})
        claude["cost_by_family"].update({"opus": 1.2, "sonnet": 0.3})
        claude["outcomes"].append("completed")
        claude["agent_prompt_bytes"].extend([10, 20, 30])
        codex = {"fresh": 300, "cache_create": 0, "cache_read": 700, "output": 60,
                 "reasoning": 25, "turns": 2, "sessions": 1, "subagents": 1,
                 "peak_ctx": 1000, "models": {"gpt-5.6-sol": 1}, "efforts": {}}
        return {"claude": {"cost_basis": "list-price",
                           "groups": {("repo", "120"): claude}},
                "codex": {"cost_basis": "subscription",
                          "groups": {("repo", "120"): codex}}}

    def window(self):
        return {"days": 7, "cutoff_epoch": 1785852530,
                "strata": ["claude", "codex"],
                "sources": {"claude": "/p", "codex": "/c"}}

    def test_input_total_is_the_sum_of_the_three_input_categories(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["claude"]["runs"][0]
        self.assertEqual(run["tokens"]["input_total"], 3300)
        self.assertEqual(run["tokens"]["fresh"], 100)
        self.assertEqual(run["tokens"]["cache_create"], 200)
        self.assertEqual(run["tokens"]["cache_read"], 3000)
        self.assertEqual(run["run_id"], "claude:repo:120")
        self.assertEqual(run["outcome"], "completed")
        self.assertEqual(run["agent_prompt_bytes"],
                         {"n": 3, "p50": 20, "p90": 30, "max": 30})

    def test_cost_is_carried_per_model_family(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["claude"]["runs"][0]
        self.assertEqual(run["cost_by_family"], {"opus": 1.2, "sonnet": 0.3})
        self.assertAlmostEqual(sum(run["cost_by_family"].values()), run["cost_usd"])
        self.assertEqual(rec["strata"]["claude"]["totals"]["cost_by_family"],
                         {"opus": 1.2, "sonnet": 0.3})
        self.assertIsNone(rec["strata"]["codex"]["runs"][0]["cost_by_family"])
        self.assertIsNone(rec["strata"]["codex"]["totals"]["cost_by_family"])
        self.assertNotIn("cost_by_family", rec["fleet"]["totals"])

    def test_absent_measurements_are_null_not_zero(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        run = rec["strata"]["codex"]["runs"][0]
        for field in ("outcome", "cost_usd", "cost_by_family", "phase_turns", "attr_turns",
                      "stop_reasons", "agents_by_type", "agent_statuses",
                      "skill_loads", "repeats", "agents_killed", "interventions",
                      "agent_prompt_bytes", "agent_result_bytes"):
            self.assertIsNone(run[field], field)
        self.assertEqual(run["tokens"]["reasoning"], 25)
        self.assertIsNone(rec["strata"]["claude"]["runs"][0]["tokens"]["reasoning"])
        self.assertEqual(rec["strata"]["codex"]["cost_basis"], "subscription")
        self.assertIsNone(rec["strata"]["codex"]["totals"]["cost_usd"])

    def test_fleet_is_informative_and_carries_no_cost(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        self.assertTrue(rec["fleet"]["informative"])
        self.assertEqual(rec["fleet"]["totals"]["input_total"], 3300 + 1000)
        self.assertNotIn("cost_usd", rec["fleet"]["totals"])
        self.assertNotIn("cost", rec["fleet"]["totals"])
        self.assertIsNone(rec["fleet"]["totals"]["reasoning"])  # claude side is null

    def test_record_id_digests_the_body_and_excludes_generated_at(self):
        rec = agent_costs.build_record(self.strata(), self.window())
        body = {k: v for k, v in rec.items()
                if k not in ("record_id", "generated_at")}
        self.assertEqual(rec["record_id"], telemetry_digest(body))
        self.assertTrue(rec["record_id"].startswith("sha256:"))
        self.assertEqual(len(rec["record_id"]), 71)
        again = agent_costs.build_record(self.strata(), self.window())
        self.assertEqual(rec["record_id"], again["record_id"])
        mutated = self.strata()
        mutated["claude"]["groups"][("repo", "120")]["fresh"] = 101
        self.assertNotEqual(
            rec["record_id"],
            agent_costs.build_record(mutated, self.window())["record_id"])

    def test_fleet_folds_only_the_strata_that_measured_something(self):
        strata = self.strata()
        strata["codex"]["groups"] = {}          # one idle, one measuring
        fleet = agent_costs.build_record(strata, self.window())["fleet"]["totals"]
        self.assertEqual(fleet["input_total"], 3300)
        self.assertEqual(fleet["fresh"], 100)
        self.assertEqual(fleet["cache_create"], 200)
        self.assertEqual(fleet["cache_read"], 3000)
        self.assertEqual(fleet["output"], 40)
        # a measuring stratum's genuinely absent field still propagates as null
        self.assertIsNone(fleet["reasoning"])
        idle = {name: dict(stratum, groups={})
                for name, stratum in strata.items()}
        blank = agent_costs.build_record(idle, self.window())["fleet"]["totals"]
        for field in ("input_total", "fresh", "cache_create", "cache_read",
                      "output", "reasoning"):
            self.assertIsNone(blank[field], field)

    def test_a_stratum_with_no_runs_totals_null_not_zero(self):
        strata = self.strata()
        strata["codex"]["groups"] = {}
        rec = agent_costs.build_record(strata, self.window())
        totals = rec["strata"]["codex"]["totals"]
        self.assertEqual(totals["runs"], 0)
        for field in ("input_total", "fresh", "cache_create", "cache_read",
                      "output", "reasoning", "cost_usd"):
            self.assertIsNone(totals[field], field)
        self.assertEqual(totals["cost_by_family"], {})  # a mapping stays {}

    def test_runs_are_sorted_by_run_id(self):
        strata = self.strata()
        groups = strata["claude"]["groups"]
        for key in (("repo", None), ("repo", agent_costs.MULTI_ISSUE), ("aaa", "9")):
            groups[key] = agent_costs.new_group()
        ids = [r["run_id"] for r in
               agent_costs.build_record(strata, self.window())["strata"]["claude"]["runs"]]
        self.assertEqual(ids, sorted(ids))
        self.assertIn("claude:repo:none", ids)
        self.assertIn("claude:repo:multi", ids)


GOLDEN = Path(__file__).resolve().parent / "fixtures" / "agent_costs_text_golden.txt"


class TextByteIdentityTest(unittest.TestCase):
    def test_default_stdout_is_byte_for_byte_the_pre_change_golden(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        bare, code = run_main("--projects-dir", str(tmp), "--days", "0")
        self.assertIsNone(code)
        self.assertEqual(bare, GOLDEN.read_text(encoding="utf-8"))

    def test_explicit_defaults_reproduce_the_no_flag_bytes(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        bare, code_a = run_main("--projects-dir", str(tmp), "--days", "0")
        explicit, code_b = run_main("--projects-dir", str(tmp), "--days", "0",
                                    "--format", "text", "--strata", "claude")
        self.assertIsNone(code_a)
        self.assertIsNone(code_b)
        self.assertEqual(bare, explicit)
        self.assertIn("NOTE: cache reads measure logical context re-processing", bare)

    def test_json_reports_the_same_numbers_the_table_prints(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        text, _ = run_main("--projects-dir", str(tmp), "--days", "0")
        raw, _ = run_main("--projects-dir", str(tmp), "--days", "0",
                          "--format", "json")
        record = json.loads(raw)
        totals = record["strata"]["claude"]["totals"]
        run = record["strata"]["claude"]["runs"][0]
        printed = agent_costs.human(totals["input_total"] + totals["output"])
        self.assertIn(f"TOTAL  {printed} tokens", text)
        # every shared group/total quantity, not one substring
        self.assertEqual(totals["fresh"], run["tokens"]["fresh"])
        self.assertEqual(totals["cache_create"], run["tokens"]["cache_create"])
        self.assertEqual(totals["cache_read"], run["tokens"]["cache_read"])
        self.assertEqual(totals["output"], run["tokens"]["output"])
        self.assertEqual(totals["input_total"], run["tokens"]["input_total"])
        self.assertEqual(totals["cost_usd"], run["cost_usd"])
        self.assertEqual(totals["cost_by_family"], run["cost_by_family"])
        self.assertAlmostEqual(sum(run["cost_by_family"].values()), run["cost_usd"])
        for value in (agent_costs.human(run["tokens"]["fresh"]),
                      agent_costs.human(run["tokens"]["cache_create"]),
                      agent_costs.human(run["tokens"]["cache_read"]),
                      agent_costs.human(run["tokens"]["output"]),
                      agent_costs.human(run["peak_ctx"]),
                      # the table's own cost format, whole dollars behind a '$'
                      f"${run['cost_usd']:,.0f}"):
            self.assertIn(value, text)


class StrataCliTest(unittest.TestCase):
    def test_non_claude_strata_in_text_mode_is_a_usage_error(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(tmp), "--strata", "both")
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_artifacts_with_json_is_a_usage_error(self):
        tmp = Path(tempfile.mkdtemp())
        claude_tree(tmp)
        with contextlib.redirect_stderr(io.StringIO()):
            out, code = run_main("--projects-dir", str(tmp), "--format", "json",
                                 "--artifacts", str(tmp))
        self.assertEqual(code, 2)
        self.assertEqual(out, "")

    def test_codex_only_run_never_touches_the_claude_root(self):
        tmp = Path(tempfile.mkdtemp())
        codex_tree(tmp)
        raw, code = run_main("--projects-dir", "/nonexistent/claude/root",
                             "--codex-sessions", str(tmp), "--days", "0",
                             "--format", "json", "--strata", "codex")
        self.assertIsNone(code)
        rec = json.loads(raw)
        self.assertEqual(rec["kind"], "agent-cost-record")
        self.assertEqual(rec["schema_version"], 1)
        self.assertEqual(rec["window"]["strata"], ["codex"])
        self.assertNotIn("claude", rec["strata"])
        runs = rec["strata"]["codex"]["runs"]
        self.assertEqual([r["run_id"] for r in runs], ["codex:repo:120"])
        self.assertEqual(runs[0]["tokens"]["input_total"], 1500)
        self.assertEqual(runs[0]["sessions"], 1)
        self.assertEqual(runs[0]["subagents"], 1)
        self.assertEqual(runs[0]["turns"], 2)
        self.assertIsNone(runs[0]["cost_usd"])

    def test_codex_window_selects_by_file_mtime_and_uses_the_whole_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            day = root / "2026" / "08" / "04"
            day.mkdir(parents=True)
            # The event timestamp predates this window.  Its file is new, so
            # mtime selection still includes the record without event filtering.
            (day / "recent-file.jsonl").write_text(
                codex_meta("s1", source="cli") + codex_response("resp-1", 10),
                encoding="utf-8")
            raw, code = run_main("--projects-dir", "/nonexistent/claude/root",
                                 "--codex-sessions", str(root), "--days", "1",
                                 "--format", "json", "--strata", "codex")
        self.assertIsNone(code)
        record = json.loads(raw)
        self.assertTrue(record["window"]["file_mtime_selection"])
        self.assertTrue(record["window"]["whole_selected_file_usage"])
        self.assertEqual(record["strata"]["codex"]["runs"][0]["tokens"]["input_total"], 10)

    def test_empty_window_in_json_mode_emits_a_record_with_no_runs(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "empty-project").mkdir()
        raw, code = run_main("--projects-dir", str(tmp), "--days", "0",
                             "--format", "json")
        self.assertIsNone(code)
        self.assertEqual(json.loads(raw)["strata"]["claude"]["runs"], [])


CACHE_T0 = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)


def at(seconds):
    """A record timestamp `seconds` after CACHE_T0, in the transcripts' millisecond Z form."""
    return ((CACHE_T0 + timedelta(seconds=seconds))
            .isoformat(timespec="milliseconds").replace("+00:00", "Z"))


def cache_usage(read, create, *, fresh=2, out=40, ttl="5m"):
    """A usage object shaped like production's; the TTL split says where the writes went."""
    return {
        "input_tokens": fresh, "cache_read_input_tokens": read,
        "cache_creation_input_tokens": create,
        "cache_creation": {"ephemeral_5m_input_tokens": create if ttl == "5m" else 0,
                           "ephemeral_1h_input_tokens": create if ttl == "1h" else 0},
        "output_tokens": out, "service_tier": "standard",
    }


def cache_call(msg_id, seconds, read, create, *, blocks=None, model="claude-opus-5-5",
               ttl="5m", stop_reason=None):
    """One assistant record of a call; a call written as several blocks repeats the id."""
    return assistant(msg_id, usage=cache_usage(read, create, ttl=ttl),
                     content=blocks or [{"type": "text", "text": "Working."}],
                     model=model, stop_reason=stop_reason, timestamp=at(seconds))


def tool_use(tool_id, name):
    return {"type": "tool_use", "id": tool_id, "name": name, "input": {}}


def tool_result(tool_id, seconds, *, ends_turn=False):
    value = {"type": "user", "isSidechain": True, "timestamp": at(seconds),
             "message": {"role": "user", "content": [
                 {"type": "tool_result", "tool_use_id": tool_id, "content": "ok"}]},
             "toolUseResult": {"success": True}}
    if ends_turn:
        value["toolEndsTurn"] = True
    return record(value)


def user_prompt(seconds, text="Read the dispatch brief."):
    return record({"type": "user", "isSidechain": True, "timestamp": at(seconds),
                   "message": {"role": "user", "content": text}})


def wake(origin, seconds):
    """A message delivered to an idle agent, as the harness records it."""
    return record({"type": "user", "isSidechain": True, "isMeta": True,
                   "timestamp": at(seconds), "origin": origin,
                   "message": {"role": "user", "content": origin.get("body", "")}})


HANDBACK = {"kind": "peer", "from": "a716bbfa2863138b8", "senderTaskId": "a716bbfa2863138b8",
            "name": "implementer", "handback": True,
            "body": "[Subagent hand-back] The text below is the final report of a subagent "
                    "this session delegated to.",
            "handbackReportText": "- **Status:** DONE"}
PEER_MESSAGE = {"kind": "peer", "from": "a4190e79ff437611b", "senderTaskId": "a4190e79ff437611b",
                "name": "implementer", "body": "- **Status:** DONE"}
TASK_NOTIFICATION = {"kind": "task-notification", "producer": "session-task"}


def attachment(kind, chars, seconds, *, rendered=True):
    """A start-up attachment whose rendered content is `chars` characters in two items."""
    value = {"type": "attachment", "isSidechain": True, "timestamp": at(seconds),
             "attachment": {"type": kind}}
    if rendered:
        half = chars // 2
        value["rendered"] = [{"content": "a" * (chars - half)}, {"content": "b" * half}]
        value["renderedRole"] = "system"
    return record(value)


def write_root(root, lines, *, session="s1"):
    project = root / "-Users-me-repo"
    project.mkdir(parents=True, exist_ok=True)
    path = project / f"{session}.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    return path


def write_subagent(root, lines, *, agent_type="general-purpose", name="agent-a1"):
    """A subagent transcript and, unless agent_type is None, its sibling .meta.json."""
    subagents = root / "-Users-me-repo" / "s1" / "subagents"
    subagents.mkdir(parents=True, exist_ok=True)
    path = subagents / f"{name}.jsonl"
    path.write_text("".join(lines), encoding="utf-8")
    if agent_type is not None:
        (subagents / f"{name}.meta.json").write_text(json.dumps(
            {"agentType": agent_type, "description": "fixture", "toolUseId": "toolu_fixture"}),
            encoding="utf-8")
    return path


def scan_cache(path, *, is_root=False, since=None, before=None, threshold=120_000):
    return agent_cache_report.scan_transcript(
        (path, is_root), since=since, before=before, threshold=threshold)


def handback_death_lines():
    """A parent that dispatches a background child, ends its turn, is woken by the
    child's hand-back 9 minutes later and rewrites its whole context."""
    return [
        user_prompt(0),
        cache_call("m1", 1, 0, 30_000, blocks=[{"type": "text", "text": "Dispatching."}]),
        cache_call("m1", 2, 0, 30_000, blocks=[tool_use("toolu_child", "Agent")]),
        tool_result("toolu_child", 2),  # a background dispatch returns at once
        cache_call("m2", 3, 30_000, 2_000, stop_reason="end_turn"),  # context 32,002
        wake(HANDBACK, 543),
        cache_call("m3", 545, 0, 32_500),
    ]


DONE_TEXT = ({"type": "text", "text": "Waiting for the hand-back."},)


def pair_lines(*, prev=(30_000, 10_000), rewrite=40_500, gap=600, ttl="5m",
               prev_blocks=DONE_TEXT, between=()):
    """A call with a context of 2 + read + create at t=10, then one creating `rewrite`
    tokens `gap` seconds later, with the `between` records in the file between them."""
    read, create = prev
    return [user_prompt(0),
            cache_call("p1", 10, read, create, blocks=list(prev_blocks), ttl=ttl),
            *between,
            cache_call("p2", 10 + gap, 0, rewrite, ttl=ttl)]


class CacheScanTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def test_a_hand_back_after_end_of_turn_is_one_death_with_its_premium(self):
        result = scan_cache(write_subagent(self.root, handback_death_lines()))
        self.assertEqual(result["agent_type"], "general-purpose")
        self.assertEqual(result["calls"], 3)
        self.assertEqual(len(result["deaths"]), 1)
        death = result["deaths"][0]
        self.assertEqual(death["kind"], "hand-back after end of turn")
        self.assertEqual(death["gap_s"], 542.0)
        # the rewrite is min(32,500 created, 32,002 prior context), at the Opus 5.5
        # 5-minute write price less the read a warm cache would have paid
        self.assertAlmostEqual(death["premium"], 32_002 * (5.0 - 0.20) / 1e6, places=12)
        # a main session's 1-hour TTL makes the same 9 minutes no death
        main = scan_cache(write_root(self.root, handback_death_lines()), is_root=True)
        self.assertEqual(main["deaths"], [])

    def test_each_cause_kind_is_decided_by_its_record(self):
        cases = [
            ("child dispatch", (tool_use("t1", "Agent"),), [tool_result("t1", 605)]),
            ("child dispatch", (tool_use("t1", "Task"),), [tool_result("t1", 605)]),
            ("long foreground command", (tool_use("t1", "Bash"),), [tool_result("t1", 605)]),
            ("other tool", (tool_use("t1", "Read"),), [tool_result("t1", 605)]),
            # the last of the predecessor's own results decides
            ("child dispatch", (tool_use("t1", "Read"), tool_use("t2", "Agent")),
             [tool_result("t1", 11), tool_result("t2", 605)]),
            # a hand-back delivered after a foreground tool's result leaves the gap to the tool
            ("long foreground command", (tool_use("t1", "Bash"),),
             [tool_result("t1", 605), wake(HANDBACK, 605)]),
            # the subagent's own turn-ending hand-back is no tool wait
            ("message after end of turn", (tool_use("t1", "SubagentHandback"),),
             [tool_result("t1", 11, ends_turn=True), wake(PEER_MESSAGE, 605)]),
            # a result for an earlier call's tool use is not the predecessor's
            ("task notification after end of turn", DONE_TEXT,
             [tool_result("t0", 12), wake(TASK_NOTIFICATION, 605)]),
            ("hand-back after end of turn", DONE_TEXT, [wake(HANDBACK, 605)]),
            ("message after end of turn", DONE_TEXT, [user_prompt(605, "continue")]),
            ("unclassified", DONE_TEXT, []),
        ]
        for index, (kind, blocks, between) in enumerate(cases):
            with self.subTest(index=index, kind=kind):
                path = write_subagent(self.root, pair_lines(prev_blocks=blocks, between=between),
                                      name=f"agent-c{index}")
                self.assertEqual([death["kind"] for death in scan_cache(path)["deaths"]], [kind])

    def test_the_gap_context_and_rewrite_boundaries(self):
        cases = [
            ("gap at TTL - 10 s", pair_lines(gap=290), False, 0),
            ("gap past TTL - 10 s", pair_lines(gap=291), False, 1),
            ("main-session gap at TTL - 10 s", pair_lines(gap=3_590, ttl="1h"), True, 0),
            ("main-session gap past it", pair_lines(gap=3_591, ttl="1h"), True, 1),
            ("prior context of exactly 5k", pair_lines(prev=(0, 4_998), rewrite=5_000), False, 0),
            ("prior context over 5k", pair_lines(prev=(0, 4_999), rewrite=5_001), False, 1),
            ("rewrite of exactly half", pair_lines(rewrite=20_001), False, 0),
            ("rewrite of over half", pair_lines(rewrite=20_002), False, 1),
        ]
        for index, (name, lines, is_root, deaths) in enumerate(cases):
            with self.subTest(name):
                path = (write_root(self.root, lines, session=f"b{index}") if is_root
                        else write_subagent(self.root, lines, name=f"agent-b{index}"))
                self.assertEqual(len(scan_cache(path, is_root=is_root)["deaths"]), deaths)

    def test_premium_weights_the_write_price_by_the_calls_own_ttl_split(self):
        usage = cache_usage(0, 40_000, ttl="1h")
        usage["cache_creation"] = {"ephemeral_1h_input_tokens": 30_000,
                                   "ephemeral_5m_input_tokens": 10_000}
        lines = [user_prompt(0), cache_call("p1", 10, 26_000, 10_000, ttl="1h"),  # 36,002
                 assistant("p2", usage=usage, model="claude-opus-5-5", timestamp=at(3_710))]
        result = scan_cache(write_root(self.root, lines), is_root=True)
        self.assertEqual(len(result["deaths"]), 1)
        weighted = (30_000 * 8.0 + 10_000 * 5.0) / 40_000   # the Opus 5.5 1h and 5m writes
        self.assertAlmostEqual(result["deaths"][0]["premium"],
                               36_002 * (weighted - 0.20) / 1e6, places=12)

    def test_repeated_records_of_one_call_merge_usage_by_per_field_maximum(self):
        # Phase-5 PR421-01: two records per call whose usage differs, so the per-field
        # maximum is distinguishable from the first copy, the last copy and their sum
        def usage(read, create, cw_1h, cw_5m):
            value = cache_usage(read, create, ttl="1h")
            value["cache_creation"] = {"ephemeral_1h_input_tokens": cw_1h,
                                       "ephemeral_5m_input_tokens": cw_5m}
            return value
        opus = "claude-opus-5-5"
        lines = [user_prompt(0),
                 assistant("p1", usage=usage(20_000, 10_000, 10_000, 0), model=opus, timestamp=at(10)),
                 assistant("p1", usage=usage(26_000, 4_000, 4_000, 0), model=opus, timestamp=at(10)),
                 assistant("p2", usage=usage(0, 20_000, 20_000, 0), model=opus, timestamp=at(3_710)),
                 assistant("p2", usage=usage(0, 40_000, 20_000, 20_000), model=opus,
                           timestamp=at(3_710))]
        result = scan_cache(write_root(self.root, lines), is_root=True, threshold=25_000)
        self.assertEqual(result["calls"], 2)
        # p1's context is 2 + max(read) 26,000 + max(create) 10,000 = 36,002; p2's is 40,002
        self.assertEqual(result["peak_ctx"], 2 + 0 + 40_000)
        self.assertEqual(len(result["deaths"]), 1)
        weighted = (20_000 * 8.0 + 20_000 * 5.0) / 40_000   # the Opus 5.5 1h and 5m writes
        self.assertAlmostEqual(result["deaths"][0]["premium"],
                               36_002 * (weighted - 0.20) / 1e6, places=12)
        # only p1's maximum read passes the 25k threshold, at the Opus 5.5 read price
        self.assertAlmostEqual(result["reread_above"], 1_000 * 0.20 / 1e6, places=12)

    def test_a_zero_usage_message_is_no_call_and_does_not_hide_a_death(self):
        synthetic = assistant(
            "synthetic-1", model="<synthetic>", stop_reason="stop_sequence", timestamp=at(400),
            usage={"input_tokens": 0, "output_tokens": 0, "cache_read_input_tokens": 0,
                   "cache_creation_input_tokens": 0},
            content=[{"type": "text", "text": "API Error: Request timed out."}])
        result = scan_cache(write_subagent(self.root, pair_lines(between=[synthetic])))
        self.assertEqual(result["calls"], 2)
        self.assertEqual([death["kind"] for death in result["deaths"]], ["unclassified"])

    def test_only_reads_past_the_threshold_are_priced(self):
        path = write_subagent(self.root, [
            user_prompt(0),
            cache_call("m1", 1, 100_000, 1_000),                               # below
            cache_call("m2", 11, 120_000, 1_000),                              # at
            cache_call("m3", 21, 150_000, 1_000),                              # above, Opus 5.5
            cache_call("m4", 31, 130_000, 1_000, model="claude-sonnet-5-5"),   # above, Sonnet 5.5
        ])
        result = scan_cache(path)
        self.assertEqual(result["calls"], 4)
        self.assertAlmostEqual(result["reread_above"],
                               (30_000 * 0.20 + 10_000 * 0.10) / 1e6, places=12)
        self.assertEqual(result["peak_ctx"], 2 + 150_000 + 1_000)
        self.assertEqual(result["deaths"], [])
        self.assertAlmostEqual(scan_cache(path, threshold=140_000)["reread_above"],
                               10_000 * 0.20 / 1e6, places=12)

    def test_first_call_and_attachments_before_the_second_call_are_the_start_up(self):
        path = write_subagent(self.root, [
            user_prompt(0),
            attachment("environment", 600, 0),
            attachment("date", 50, 0),                    # not a start-up type
            attachment("skill_listing", 24_000, 0),
            attachment("instructions", 5_000, 0),
            attachment("deferred_tools_delta", 3_000, 0),
            attachment("skill_listing", 9_999, 0),        # a later copy: the first one counts
            cache_call("m1", 2, 3_323, 12_907, blocks=[tool_use("toolu_r1", "Read")]),
            attachment("mcp_instructions_delta", 1_200, 3),   # rides the second request
            tool_result("toolu_r1", 3),
            cache_call("m2", 4, 16_230, 900),
            attachment("agent_listing_delta", 2_500, 5),      # after the second call
            cache_call("m3", 6, 17_130, 400),
        ], agent_type="Explore")
        result = scan_cache(path)
        self.assertEqual(result["agent_type"], "Explore")
        self.assertEqual(result["startup"], {
            "write": 12_907, "read": 3_323,
            "attachments": {"environment": 600, "skill_listing": 24_000, "instructions": 5_000,
                            "deferred_tools_delta": 3_000, "mcp_instructions_delta": 1_200},
        })

    def test_an_attachment_without_rendered_content_is_not_measured(self):
        path = write_subagent(self.root, [
            user_prompt(0),
            attachment("instructions", 5_000, 0, rendered=False),
            attachment("environment", 600, 0),
            cache_call("m1", 2, 3_000, 10_000),
        ])
        self.assertEqual(scan_cache(path)["startup"]["attachments"], {"environment": 600})

    def test_agent_type_comes_from_the_meta_file_and_main_sessions_have_no_start_up(self):
        lines = [user_prompt(0), cache_call("m1", 1, 3_000, 10_000)]
        main = scan_cache(write_root(self.root, lines), is_root=True)
        self.assertEqual((main["agent_type"], main["is_root"], main["startup"]), ("main", True, None))
        bare = scan_cache(write_subagent(self.root, lines, agent_type=None, name="agent-a2"))
        self.assertEqual((bare["agent_type"], bare["is_root"]), ("unknown", False))
        self.assertEqual(bare["startup"], {"write": 10_000, "read": 3_000, "attachments": {}})

    def test_bounds_count_calls_by_start_time_half_open(self):
        path = write_subagent(self.root, [
            user_prompt(0),
            cache_call("m1", 0, 3_000, 10_000),
            cache_call("m2", 100, 13_000, 1_000),
            cache_call("m3", 200, 14_000, 1_000),
            assistant("m4", usage=cache_usage(15_000, 1_000), model="claude-opus-5-5"),  # untimed
        ])
        bounded = scan_cache(path, since=CACHE_T0 + timedelta(seconds=100),
                             before=CACHE_T0 + timedelta(seconds=200))
        self.assertEqual((bounded["calls"], bounded["peak_ctx"]), (1, 2 + 13_000 + 1_000))
        self.assertIsNone(bounded["startup"])  # the first call is outside the window
        self.assertEqual(scan_cache(path)["calls"], 4)  # unbounded: untimed calls count too
        empty = scan_cache(path, since=CACHE_T0 + timedelta(days=1),
                           before=CACHE_T0 + timedelta(days=2))
        self.assertEqual((empty["calls"], empty["peak_ctx"], empty["reread_above"]),
                         (0, None, 0.0))

    def test_a_death_counts_when_the_rewriting_call_is_in_the_window(self):
        path = write_subagent(self.root, handback_death_lines())
        inside = scan_cache(path, since=CACHE_T0 + timedelta(seconds=500),
                            before=CACHE_T0 + timedelta(seconds=600))
        self.assertEqual(inside["calls"], 1)
        self.assertEqual([death["kind"] for death in inside["deaths"]],
                         ["hand-back after end of turn"])
        before_it = scan_cache(path, since=CACHE_T0, before=CACHE_T0 + timedelta(seconds=545))
        self.assertEqual(before_it["deaths"], [])

    def test_an_unreadable_transcript_is_skipped(self):
        self.assertIsNone(scan_cache(self.root / "missing.jsonl"))


def cache_tree(root):
    """A main session, the hand-back parent and an Explore subagent with a skill listing."""
    write_root(root, [user_prompt(0), cache_call("r1", 1, 0, 20_000, ttl="1h"),
                      cache_call("r2", 30, 20_000, 500, ttl="1h")])
    write_subagent(root, handback_death_lines(), name="agent-a1")
    write_subagent(root, [user_prompt(0), attachment("skill_listing", 24_000, 0),
                          cache_call("e1", 2, 3_323, 12_907), cache_call("e2", 4, 16_230, 900)],
                   agent_type="Explore", name="agent-a2")
    return root


DEATH_ROW = r"(?m)^general-purpose\s+hand-back after end of turn\s+1\s+9\.0m\s+\$0$"


class CacheReportCliTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = cache_tree(Path(self.tmp.name))

    def report(self, *argv):
        return run_main("--projects-dir", str(self.root), "--report", "cache", *argv)

    def test_the_cache_report_prints_three_tables_and_the_totals(self):
        out, code = self.report("--days", "0")
        self.assertIsNone(code)
        self.assertTrue(out.startswith("Cache report (all time, 3 transcripts, 7 calls)\n\n"),
                        out[:200])
        self.assertRegex(out, r"(?m)^agent type\s+cause\s+deaths\s+median gap\s+premium$")
        self.assertRegex(out, DEATH_ROW)
        self.assertIn("\nSubagent deaths 1 ($0 premium); main-session deaths 0 ($0)\n", out)
        self.assertIn("\nReread above 120.00k tokens of context", out)
        self.assertRegex(out, r"(?m)^agent type\s+transcripts\s+reread above\s+peak p50"
                              r"\s+peak p90\s+peak max$")
        self.assertRegex(out, r"(?m)^main\s+1\s+\$0\s+20\.50k\s+20\.50k\s+20\.50k$")
        self.assertRegex(out, r"(?m)^agent type\s+subagents\s+1st write\s+1st read\s+skill listing"
                              r"\s+instructions\s+MCP instructions\s+deferred tools"
                              r"\s+agent listing\s+environment$")
        self.assertRegex(out, r"(?m)^Explore\s+1\s+12\.91k\s+3\.32k\s+24\.00k(\s+-){5}$")
        self.assertRegex(out, r"(?m)^general-purpose\s+1\s+30\.00k\s+0(\s+-){6}$")
        self.assertRegex(out, r"(?m)^Pricing: https://\S+ \(2026-10-25\); 0 calls priced approximately$")
        self.assertTrue(out.endswith(f"\nNOTE: {agent_costs.DISCLAIMER}\n"))

    def test_event_bounds_select_calls_by_start_and_name_the_window(self):
        out, code = self.report("--events-since", "2026-10-12T09:05:00Z",
                                "--events-before", "2026-10-12T09:10:00Z")
        self.assertIsNone(code)
        self.assertTrue(out.startswith(
            "Cache report (events 2026-10-12T09:05:00Z → 2026-10-12T09:10:00Z, "
            "1 transcripts, 1 calls)\n"), out[:200])
        self.assertRegex(out, DEATH_ROW)

    def test_an_empty_selection_exits_instead_of_printing_zeros(self):
        out, code = self.report("--events-since", "2026-10-13T00:00:00Z",
                                "--events-before", "2026-10-14T00:00:00Z")
        self.assertEqual((out, code), ("", "no calls in window"))
        with tempfile.TemporaryDirectory() as empty:
            (Path(empty) / "-Users-me-empty").mkdir()
            out, code = run_main("--projects-dir", empty, "--report", "cache", "--days", "0")
        self.assertEqual((out, code), ("", "no transcripts in window"))

    def test_top_caps_each_table_and_says_how_many_rows_it_dropped(self):
        out, code = self.report("--days", "0", "--top", "1")
        self.assertIsNone(code)
        self.assertIn("\n... 2 more rows not shown (--top 3 for all)\n", out)  # reread
        self.assertIn("\n... 1 more rows not shown (--top 2 for all)\n", out)  # start-up
        self.assertRegex(out, DEATH_ROW)

    def test_the_threshold_flag_reaches_the_scanner_and_the_caption(self):
        with tempfile.TemporaryDirectory() as tmp:
            write_root(Path(tmp), [user_prompt(0)] + [
                cache_call(f"r{i}", 10 * i, 900_000, 1_000, ttl="1h") for i in range(1, 11)])
            default, _ = run_main("--projects-dir", tmp, "--report", "cache", "--days", "0")
            raised, _ = run_main("--projects-dir", tmp, "--report", "cache", "--days", "0",
                                 "--context-threshold", "500000")
        # ten Opus 5.5 reads of 900k: 10 x 780k x $0.20 / 1e6 = $1.56, which rounds to $2;
        # above 500k, 10 x 400k x $0.20 / 1e6 = $0.80, which rounds to $1
        self.assertRegex(default, r"(?m)^main\s+1\s+\$2\s+")
        self.assertIn("\nReread above 120.00k tokens of context", default)
        self.assertRegex(raised, r"(?m)^main\s+1\s+\$1\s+")
        self.assertIn("\nReread above 500.00k tokens of context", raised)

    def test_cache_report_usage_errors_exit_2_with_nothing_on_stdout(self):
        cases = {
            "json": ("--report", "cache", "--format", "json"),
            "project": ("--report", "cache", "--project", "repo"),
            "artifacts": ("--report", "cache", "--artifacts", str(self.root)),
            "strata": ("--report", "cache", "--strata", "both"),
            "one bound": ("--report", "cache", "--events-since", "2026-10-12T09:00:00Z"),
            "inverted": ("--report", "cache", "--events-since", "2026-10-12T10:00:00Z",
                         "--events-before", "2026-10-12T09:00:00Z"),
            "no offset": ("--report", "cache", "--events-since", "2026-10-12T09:00:00",
                          "--events-before", "2026-10-12T10:00:00Z"),
            "zero threshold": ("--report", "cache", "--context-threshold", "0"),
            "threshold on the issue report": ("--context-threshold", "120000"),
            "bounds on the issue tables": ("--events-since", "2026-10-12T09:00:00Z",
                                           "--events-before", "2026-10-12T10:00:00Z"),
            "unknown report": ("--report", "deaths"),
        }
        for name, argv in cases.items():
            with self.subTest(name), contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(run_main("--projects-dir", str(self.root), *argv), ("", 2))

    def test_the_module_run_reports_through_a_real_process_pool(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--projects-dir", str(self.root),
             "--report", "cache", "--days", "0"],
            capture_output=True, text=True, timeout=120, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        # the pool must not have fallen back to the sequential scan (Phase-5 PR421-02):
        # scan_paths catches every pool failure, pickling included, and retries in-process
        self.assertNotIn("Process pool unavailable", completed.stderr)
        self.assertRegex(completed.stdout, DEATH_ROW)

    def test_aggregation_over_several_transcripts_of_one_type(self):
        # Phase-5 PR421-03: several same-type transcripts with distinct peaks, deaths and
        # attachment sets, so sums, percentiles and carrier-only medians are observable
        def result(agent_type, is_root, calls, deaths, reread, peak, startup, approximate=0):
            return {"agent_type": agent_type, "is_root": is_root, "calls": calls,
                    "approximate_calls": approximate,
                    "deaths": [{"kind": k, "gap_s": g, "premium": p} for k, g, p in deaths],
                    "reread_above": reread, "peak_ctx": peak, "startup": startup}
        handback = "hand-back after end of turn"
        results = [
            result("general-purpose", False, 5,
                   [(handback, 540.0, 1.5), ("child dispatch", 400.0, 0.8)], 1.5, 150_000,
                   {"write": 30_000, "read": 0,
                    "attachments": {"skill_listing": 24_000, "environment": 600}},
                   approximate=2),
            result("general-purpose", False, 3, [(handback, 660.0, 2.0)], 0.75, 90_000,
                   {"write": 10_000, "read": 20_000, "attachments": {"skill_listing": 20_000}},
                   approximate=1),
            result("general-purpose", False, 2, [(handback, 600.0, 0.25)], 2.0, 200_000,
                   {"write": 20_000, "read": 10_000, "attachments": {}}),
            result("main", True, 4, [("message after end of turn", 3_700.0, 3.0)], 0.0,
                   50_000, None),
        ]
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            agent_cache_report.print_report(results, window="all time", threshold=120_000,
                                            top=30)
        out = out.getvalue()
        self.assertTrue(out.startswith("Cache report (all time, 4 transcripts, 14 calls)\n"))
        rows = re.findall(r"(?m)^(general-purpose|main)\s+(hand-back after end of turn|"
                          r"child dispatch|message after end of turn)\s+\d", out)
        self.assertEqual(rows, [("general-purpose", handback), ("main", "message after end of turn"),
                                ("general-purpose", "child dispatch")])  # premium descending
        # three deaths, median of 540/600/660 s, premiums 1.5 + 2.0 + 0.25
        self.assertRegex(out, r"(?m)^general-purpose\s+hand-back after end of turn\s+3\s+10\.0m\s+\$4$")
        self.assertRegex(out, r"(?m)^general-purpose\s+child dispatch\s+1\s+6\.7m\s+\$1$")
        self.assertIn("\nSubagent deaths 4 ($5 premium); main-session deaths 1 ($3)\n", out)
        self.assertIn("; 3 calls priced approximately\n", out)  # the transcripts' 2 + 1
        # reread 1.5 + 0.75 + 2.0 summed; peak median 150k is neither the first nor the max
        self.assertRegex(out, r"(?m)^general-purpose\s+3\s+\$4\s+150\.00k\s+200\.00k\s+200\.00k$")
        self.assertRegex(out, r"(?m)^main\s+1\s+\$0\s+50\.00k\s+50\.00k\s+50\.00k$")
        # medians over the subagents that carried each attachment: environment is 600,
        # not the 0 a missing-as-zero median of (0, 0, 600) would print
        self.assertRegex(out, r"(?m)^general-purpose\s+3\s+20\.00k\s+10\.00k\s+20\.00k"
                              r"(\s+-){4}\s+600$")
        self.assertNotRegex(out, r"(?m)^main\s+\d+\s+[\d.]+k\s+[\d.]+k\s+-")  # no start-up row

    def test_peak_percentiles_take_the_rounded_index_of_the_sorted_peaks(self):
        # CR421-01: the value at index round(p/100 x (n-1)), half-to-even, not nearest
        # rank. Four peaks: p50 is index round(1.5) = 2, 30k (nearest rank: 20k). Six
        # peaks: p90 is index round(4.5) = 4, the fifth value 50k (nearest rank: 60k).
        def result(agent_type, peak):
            return {"agent_type": agent_type, "is_root": False, "calls": 1, "deaths": [],
                    "approximate_calls": 0, "reread_above": 0.0, "peak_ctx": peak,
                    "startup": None}
        four = [10_000, 20_000, 30_000, 40_000]
        six = [10_000, 20_000, 30_000, 40_000, 50_000, 60_000]
        results = ([result("explore", peak) for peak in four]
                   + [result("plan", peak) for peak in six])
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            agent_cache_report.print_report(results, window="all time", threshold=120_000,
                                            top=30)
        out = out.getvalue()
        human = agent_costs.human
        for agent_type, count, p50, p90, peak_max in (
                ("explore", 4, 30_000, 40_000, 40_000),
                ("plan", 6, 30_000, 50_000, 60_000)):
            with self.subTest(agent_type):
                cells = r"\s+".join(re.escape(human(v)) for v in (p50, p90, peak_max))
                self.assertRegex(out, rf"(?m)^{agent_type}\s+{count}\s+\$0\s+{cells}$")


class ModuleEntryPointTest(unittest.TestCase):
    """The recipe runs the tool with `-m`; every other test calls main() in process."""

    def test_the_module_run_reaches_main_under_the_command_name(self):
        completed = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--help"],
            capture_output=True, text=True, timeout=60, check=False)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: agent-costs "),
                        completed.stdout[:200])


class ModelPricingTest(unittest.TestCase):
    def test_opus_5_5_is_priced_at_its_own_row(self):
        self.assertEqual(model_pricing.rates("claude-opus-5-5", 1_000),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), False))

    def test_a_date_suffix_matches_its_base_row(self):
        self.assertEqual(model_pricing.rates("claude-haiku-4-5-20251001", 1_000),
                         (model_pricing.Rates(1.0, 5.0, 1.25, 2.0, 0.10), False))

    def test_haiku_5_5_switches_tier_above_100k_prompt(self):
        low, _ = model_pricing.rates("claude-haiku-5-5", 100_000)
        high, _ = model_pricing.rates("claude-haiku-5-5", 100_001)
        self.assertEqual(low, model_pricing.Rates(0.10, 0.50, 0.125, 0.20, 0.01))
        self.assertEqual(high, model_pricing.Rates(0.50, 2.50, 0.625, 1.0, 0.05))

    def test_unknown_ids_take_the_family_newest_row_and_are_approximate(self):
        self.assertEqual(model_pricing.rates("claude-opus-9-9", 1),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), True))
        self.assertEqual(model_pricing.rates("claude-sonnet-7", 1)[1], True)
        self.assertEqual(model_pricing.rates("mystery-model", 1),
                         (model_pricing.Rates(4.0, 20.0, 5.0, 8.0, 0.20), True))
        self.assertEqual(model_pricing.rates(None, 1)[1], True)

    def test_older_rows_are_exact(self):
        self.assertEqual(model_pricing.rates("claude-sonnet-4-6", 1),
                         (model_pricing.Rates(3.0, 15.0, 3.75, 6.0, 0.30), False))
        self.assertEqual(model_pricing.rates("claude-opus-4-8", 1),
                         (model_pricing.Rates(5.0, 25.0, 6.25, 10.0, 0.50), False))
        self.assertEqual(model_pricing.rates("claude-fable-5", 1),
                         (model_pricing.Rates(10.0, 50.0, 12.5, 20.0, 1.0), False))

    def test_synthetic_costs_nothing(self):
        self.assertEqual(model_pricing.usage_cost("<synthetic>", cache_usage(5_000, 5_000)),
                         (0.0, False))

    def test_usage_cost_prices_each_bucket(self):
        usage = {"input_tokens": 1_000_000, "output_tokens": 1_000_000,
                 "cache_read_input_tokens": 1_000_000,
                 "cache_creation_input_tokens": 3_000_000,
                 "cache_creation": {"ephemeral_1h_input_tokens": 1_000_000,
                                    "ephemeral_5m_input_tokens": 2_000_000}}
        cost, approximate = model_pricing.usage_cost("claude-opus-5-5", usage)
        self.assertAlmostEqual(cost, 4.0 + 20.0 + 8.0 + 2 * 5.0 + 0.20, places=9)
        self.assertFalse(approximate)


if __name__ == "__main__":
    unittest.main()
