"""Offline tests for scripts/agent-costs.py against tiny synthetic transcripts.

Covers the load-bearing counting rules (message-ID usage dedup, the tool-use-ID
and tool-result-ID guards), token accounting, model/effort extraction, peak
per-turn context, outcome derivation, the proceed-nudge matcher, and the
artifact pass. Runs entirely offline: fixtures are built in a temp dir.

Run: python3 -m unittest -v tests/test_agent_costs.py
"""

import contextlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

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
              effort="xhigh", stop_reason="tool_use", cwd="/Users/me/repo",
              agent_id=None, attribution_skill=None, sidechain=False):
    return record({
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
        self.assertAlmostEqual(direct["cost"], 0.0113625, places=12)
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
               thread_source="user", parent=None):
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
        self.assertEqual(rec["record_id"], agent_costs.canonical_digest(body))
        self.assertTrue(rec["record_id"].startswith("sha256:"))
        self.assertEqual(len(rec["record_id"]), 71)
        again = agent_costs.build_record(self.strata(), self.window())
        self.assertEqual(rec["record_id"], again["record_id"])
        mutated = self.strata()
        mutated["claude"]["groups"][("repo", "120")]["fresh"] = 101
        self.assertNotEqual(
            rec["record_id"],
            agent_costs.build_record(mutated, self.window())["record_id"])

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

    def test_empty_window_in_json_mode_emits_a_record_with_no_runs(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "empty-project").mkdir()
        raw, code = run_main("--projects-dir", str(tmp), "--days", "0",
                             "--format", "json")
        self.assertIsNone(code)
        self.assertEqual(json.loads(raw)["strata"]["claude"]["runs"], [])


if __name__ == "__main__":
    unittest.main()
