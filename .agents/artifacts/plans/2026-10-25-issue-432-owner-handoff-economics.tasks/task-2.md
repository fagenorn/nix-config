# Task 2: The owner report — lineages, delivery, eval grouping

Spec § The owner report and test seam 1; per D3, D4, D17, D19 and D20. Adds `agent-costs --report owners` (text or `--format json`): one lineage per `(run_id, issue)`, every other transcript attributed to its nearest owner, and dollars per delivered issue with variance for the live corpus and eval trials. Task 4 adds the replay to the same module.

**Files:**
- Create: `python/agent_tools/agent_owner_report.py`
- Modify: `python/agent_tools/context_meter_commands.py` (add `Invocation`/`invocations`; `registers_owner` returns `any(...)` over them, and its behaviour is unchanged)
- Modify: `python/agent_tools/agent_costs.py` (`main`: `--report owners`, `--eval-results`, `--eval`, refusals; the module docstring gains one paragraph naming the report)
- Create: `tests/owner_transcripts.py` (builders, below)
- Create: `tests/test_agent_owner_report.py`
- Modify: `justfile` (add `tests/test_agent_owner_report.py` to `agent-workflow-tests`, after `tests/test_agent_costs.py`)
- Modify: `python/README.md` (§ agent-costs: the owners report contract: owner test, lineage, descendants, delivered, eval grouping, the JSON keys below)

**Interfaces:**
- Consumes: Task 1's `model_pricing.rates`/`usage_cost`/`cache_write_split`, and `transcript_calls.read_transcript`/`is_death`/`TTL_SECONDS`/`Call`/`ToolResult`; `agent_costs.find_sessions`, `scan_paths`, `percentile`, `print_table`, `human`; `context_meter.MEASURED_NOTE` (its text up to `{tokens}` is the measured-note prefix).
- Produces:
  - `context_meter_commands.Invocation` — frozen dataclass `(helper: str, subcommand: str | None, options: dict[str, str | None], absolute: bool)`. `helper` is the last path component of the command word (`workflow-state`, `sdd-gate`), and `absolute` is whether that word contains `/`. `subcommand` is the next word when it does not start with `-`. `options` maps every later word of the simple command that starts with `--` to its value: the text after `=`, else the following word unless that word starts with `-`, else `None`.
  - `context_meter_commands.invocations(tokens) -> list[Invocation]`, for each `workflow-state` or `sdd-gate` command word in `tokens`.
  - `agent_owner_report.Gate` — frozen dataclass `(phase: int, turn_count: int | None, next_needs_context: bool, artifacts_sufficient: bool, remainder_self_contained: bool, handoff_path: bool, action: str | None)`. `action` is the `phase_gate` reply's `action`, `None` when there is no such reply.
  - `agent_owner_report.OwnerCall` — frozen dataclass `(start: float, end: float, model: str | None, fresh: int, read: int, write_5m: int, write_1h: int, output: int, death: bool, is_root: bool, phase: int | None, bash: bool, children_out: bool, gate: Gate | None, registers: bool, help: bool, mark_progress: str | None, slimmable: int)`, with `context` = `fresh + read + write_5m + write_1h`. `mark_progress` is a `mark-progress` reply's `outcome`, else `None` (D25). `start`/`end` are epoch seconds.
  - `agent_owner_report.Launch` — frozen dataclass `(transcript: str, launch: int | None, calls: tuple[OwnerCall, ...], registered_index: int | None, transfer: str | None)`. `transfer` is `"handoff"` when the transcript finalised a `--handoff-path` progress call, else its last `phase_gate` reply's action, else `None`.
  - `agent_owner_report.Lineage` — dataclass `(run_id: str, issue: int, direct: bool, launches: list[Launch], descendant_dollars: float, delivered: bool, facts: dict, relauncher: tuple[tuple[float, int], ...])`. `facts` holds the per-lineage JSON fields below; `relauncher` is the `(end, context)` series of the lineage's root owner transcript's calls, empty when the session root is not an owner of this lineage (Task 4's wake call).
  - `agent_owner_report.call_cost(call: OwnerCall) -> float` prices one call at `rates(call.model, call.context)`.
  - `agent_owner_report.collect(root: Path, *, cutoff, since, before, eval_rows: list[dict] | None, executor_factory) -> tuple[list[Lineage], dict]` returns the lineages and the footer facts.
  - `agent_owner_report.build_document(lineages, footer, *, window: str) -> dict` and `print_document(doc, *, top: int) -> None`.

**Invariants (per D3, D4, D20):**
- An owner transcript has a Bash call whose invocation is a `workflow-state progress`/`mark-progress` or an `sdd-gate`, carrying both `--run-id` and `--action-id`. Its run ID is that `--run-id` value; its action ID is an opaque string. Its issue, attempt and launch come, in order, from: (1) a JSON reply of its own (`phase_gate`, `finish`, `direct-owner` `kind: owner`) with `issue` and `custody.{attempt, launch}`, or `issue`/`attempt` at top level; (2) `--issue`/`--attempt` of its progress or suspend calls; (3) another owner transcript of the same run with the same action ID that resolved. An owner that stays unresolved counts in `unattributed.unresolved_owners`, and its spend and its descendants' spend count as unattributed.
- A reply is the first JSON object of the tool result's text (`json.JSONDecoder().raw_decode` on the left-stripped text). Text after the object (`exit=0`) is ignored. A result that does not start with an object has no reply.
- Descendants: a subagent's parent is the transcript `agent-<parentAgentId>.jsonl` in the same session's `subagents/` tree, and the session root when `parentAgentId` is absent. Walk up to the nearest owner. A transcript reaching no owner is unattributed.
- Lineage launches are ordered by `launch` (`None` last), then by first call start.
- Phases: a call before a transcript's first progress call, and that call itself, take its `--phase`; a call after a progress call reporting `n` takes `n + 1`. A transcript whose first registering call is `sdd-gate` or `mark-progress` is in Phase 6 until a progress call says otherwise. A transcript with no gate call has phase `None`.
- Death: `transcript_calls.is_death(prev, call, TTL_SECONDS[is_root])`. `children_out`: a child is a transcript whose `.meta.json` `toolUseId` is an `Agent`/`Task` tool use of this transcript, issued by an earlier call; it is out while its last call `end` is after this call's `start`. A long child wait is a gap `call.start − prev.end > 300` with a child out across it (issued at or before `prev`, last `end` after `prev.end`), counted once per gap.
- Delivered: live — some transcript of the lineage (owner or descendant) has a `workflow-state finish` reply with `kind == "delivery_complete"` whose `run_id` and `issue` equal the lineage's; eval — the trial row's `verdict == "PASS"`.
- Measured gate call: a progress call whose tool use has a `hook_notes` entry containing the measured-note prefix. `phase7_entered`: some progress `--phase 6` call has a `phase_gate` reply. `help_calls`: invocations of `workflow-state progress` carrying `--help`. `absolute_path_calls`: `workflow-state` invocations with `absolute` true.
- Boot of a non-root owner transcript: its calls from the first through `registered_index`, inclusive. `B` = the registering call's context, `start` = the first call's context, phase group `"0-5"` or `"6-7"` by the registering call's phase. `slimmable` (D12, D21) is assigned to a boot call issuing tool uses. Take its growth `max(0, next.context − call.context)` and split it across the call's tool results by `ToolResult.size`. A tool use's share is slimmable when it is a `Read` whose `file_path` matches `\.tasks/task-(\d+)\.md$` with a number other than the resumed task, or ends in `ship-handoff.md` while the boot's phase is below 7. It is also slimmable when it re-reads (`Read`) a persisted output file whose path appeared after `saved to: ` in such a tool use's result. The resumed task is the `--task` of the transcript's first `sdd-gate review` invocation; with none, task members are not slimmable.
- Dollars: `owner_dollars` = Σ `call_cost` over owner calls; `total_dollars` = owner + descendants. Per arm, `dollars_per_delivered` = Σ `total_dollars` of every row in the arm ÷ delivered rows (`None` when 0), `undelivered_dollars` = Σ of the undelivered rows, and `sd` = sample standard deviation of `total_dollars` over delivered rows (`None` below 2).
- Eval mode (`--eval-results PATH --eval SKILL:ID`): rows whose `skill` and `id` match. A row's transcripts are the sessions of project directories whose name equals, or starts with `-` after, its `workdir` with every non-alphanumeric character replaced by `-`. The mtime window does not apply. A row is one lineage row: its lineages are merged (sums, max peak, any phase-7 entry), `arm` = `f"{tree_rev[:12]}/{policy or 'default'}"`, and `trial` and `verdict` come from the row. Only a row with `claude_exit` 0 is a sample; any other (124 from `EVAL_TIMEOUT`, a budget stop, a kill) forms no lineage, whatever its `verdict`, and is listed in `interrupted` as `{"trial", "tree_rev", "claude_exit"}` and counted in the text footer (D26). Live mode puts every lineage in arm `"live"`, with `interrupted` empty.
- JSON document: `{"kind": "agent-owner-report", "schema_version": 1, "window", "pricing": {"source", "date", "approximate_calls"}, "lineages": [...], "arms": [...], "boots": [...], "simulated": [], "calibration": null, "unattributed": {"transcripts", "dollars", "unresolved_owners"}, "interrupted": [...]}`.
  - Each lineage row has exactly the keys `key, run_id, issue, arm, trial, verdict, direct, launches, handoffs, boots, deaths, long_child_waits, peak_context, owner_dollars, total_dollars, delivered, phase_reached, phase7_entered, gate_calls, measured_gate_calls, help_calls, absolute_path_calls`.
  - Each arm row: `arm, n, delivered, dollars_per_delivered, sd, undelivered_dollars, peak_p50, peak_p90`.
  - Each boots row: `phase_group, count, b_p50, b_p90, start_p50, calls_p50, slimmable_p50`.
  - `direct` is true when a lineage transcript got a `direct-owner` reply of `kind: owner`. `handoffs` counts finalised `--handoff-path` calls, `boots` counts non-root owner transcripts, `phase_reached` is the highest owner-call phase, where a call whose progress `--phase n` got a `phase_gate` reply counts as `n + 1`, and `peak_context` the maximum owner-call context.
- Text output: the six tables of spec § Output with their headings (`Lineages`, `Arms`, `Fresh-owner boots by phase`, `Simulated arms`, `Calibration`; the footer prints `Pricing: …`, unattributed transcripts and dollars, unresolved owners and `NOTE: ` + `agent_costs.DISCLAIMER`). Tables 4 and 5 print `(none: pass --policy or --sweep)` until Task 4.
- Flags: `--report owners` accepts `--format json`, `--days`, `--projects-dir`, `--top` and `--events-since/--events-before`, the latter counting only calls that start inside the window. It refuses `--project`, `--artifacts`, `--context-threshold` and `--strata` other than `claude`. `--eval-results` and `--eval` require each other and `--report owners`. Each refusal goes through `ap.error`.

- [ ] **Step 1: Write the builders** — `tests/owner_transcripts.py`, in full:

```python
"""Production-shaped owner transcripts for the owner report and replay tests (issue 432).

Usage repeats on every content block of a message, as Claude Code writes it.
"""
import json
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 10, 25, 9, 0, tzinfo=timezone.utc)
RUN = "rel_01a1test-0000-7000-8000-000000000001"


def _line(value):
    """Compact JSON, as transcripts are written (the reader's prefilter needs it)."""
    return json.dumps(value, separators=(",", ":")) + "\n"


def at(seconds):
    return (T0 + timedelta(seconds=seconds)).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def progress(phase, *, action_id="7:1:1", handoff=None, absolute=False):
    helper = "/Users/me/.agents/bin/workflow-state" if absolute else "workflow-state"
    words = [helper, "progress", "--repo-root", "/Users/me/repo", "--run-id", RUN,
             "--issue", action_id.split(":")[0], "--attempt", "1", "--action-id", action_id,
             "--phase", str(phase), "--next-needs-context", "true",
             "--artifacts-sufficient", "false", "--remainder-self-contained", "false"]
    if handoff:
        words += ["--handoff-path", handoff]
    return " ".join(words) + " | artifact-budget validate-report --boundary workflow-response --input -"


def gate_reply(action, *, issue=7, launch=1, handoff_path=None):
    return json.dumps({"interface_version": 2, "kind": "phase_gate", "run_id": RUN, "issue": issue,
                       "custody": {"action_id": f"{issue}:1:{launch}", "attempt": 1,
                                   "kind": "implementation", "launch": launch},
                       "action": action, "handoff_path": handoff_path}) + "\nexit=0"


def finish_reply(issue=7, kind="delivery_complete"):
    return json.dumps({"interface_version": 2, "issue": issue, "kind": kind, "run_id": RUN,
                       "state": kind, "pending_stage_ids": []})


FINISH = f"workflow-state finish --repo-root /Users/me/repo --run-id {RUN} --summary-file - <<'EOF'"


class Session:
    """One session under <root>/<project>/<session>.jsonl plus its subagents."""

    def __init__(self, root, project="-Users-me-repo", session="s1"):
        self.dir = root / project
        self.session = session
        self.lines = {None: []}
        self.meta = {}
        self.ids = 0

    def _id(self, prefix):
        self.ids += 1
        return f"{prefix}{self.ids:04d}"

    def child(self, agent_id, *, tool_use_id, parent=None, agent_type="general-purpose"):
        self.lines[agent_id] = []
        meta = {"agentType": agent_type, "description": "fixture", "toolUseId": tool_use_id}
        if parent is not None:
            meta["parentAgentId"] = parent
        self.meta[agent_id] = meta

    def call(self, agent, seconds, *, context, write, fresh=2, out=40, ttl="5m",
             model="claude-opus-5-5", bash=None, agent_tool=False, read_file=None, end=None):
        """One API call; returns the id of its tool use, if it made one."""
        write = min(write, context - fresh)
        usage = {"input_tokens": fresh, "cache_read_input_tokens": context - write - fresh,
                 "cache_creation_input_tokens": write, "output_tokens": out,
                 "cache_creation": {"ephemeral_5m_input_tokens": write if ttl == "5m" else 0,
                                    "ephemeral_1h_input_tokens": write if ttl == "1h" else 0},
                 "service_tier": "standard"}
        blocks, tool_id = [{"type": "text", "text": "Working."}], None
        if bash is not None or agent_tool or read_file is not None:
            tool_id = self._id("toolu_")
            name, tool_input = (("Bash", {"command": bash}) if bash is not None else
                                ("Agent", {"subagent_type": "general-purpose", "prompt": "x"})
                                if agent_tool else ("Read", {"file_path": read_file}))
            blocks.append({"type": "tool_use", "id": tool_id, "name": name, "input": tool_input})
        message_id = self._id("msg_")
        for index, block in enumerate(blocks):
            stamp = seconds if end is None or index == 0 else end
            self.lines[agent].append(_line({
                "type": "assistant", "isSidechain": agent is not None, "timestamp": at(stamp),
                "message": {"id": message_id, "model": model, "role": "assistant",
                            "content": [block], "usage": usage}}))
        return tool_id

    def result(self, agent, seconds, tool_id, text="ok"):
        self.lines[agent].append(_line({
            "type": "user", "isSidechain": agent is not None, "timestamp": at(seconds),
            "message": {"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": tool_id, "content": text}]}}))

    def measured(self, agent, tool_id, tokens):
        self.lines[agent].append(_line({
            "type": "attachment", "isSidechain": agent is not None, "attachment": {
                "type": "hook_additional_context", "hookName": "PreToolUse:Bash",
                "toolUseID": tool_id,
                "content": [f"context-meter: this workflow-state progress call carries "
                            f"--context-tokens {tokens}, measured from your transcript."]}}))

    def write(self):
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / f"{self.session}.jsonl").write_text("".join(self.lines[None]), encoding="utf-8")
        subagents = self.dir / self.session / "subagents"
        for agent_id, lines in self.lines.items():
            if agent_id is None:
                continue
            subagents.mkdir(parents=True, exist_ok=True)
            (subagents / f"agent-{agent_id}.jsonl").write_text("".join(lines), encoding="utf-8")
            (subagents / f"agent-{agent_id}.meta.json").write_text(
                json.dumps(self.meta[agent_id]), encoding="utf-8")


def cost(context, write, *, fresh=2, out=40, write_price=5.0, read_price=0.20):
    """The Opus 5.5 list price of one builder call, in dollars (writes capped as `call` caps them)."""
    write = min(write, context - fresh)
    return (fresh * 4.0 + out * 20.0 + write * write_price
            + (context - write - fresh) * read_price) / 1e6
```

- [ ] **Step 2: Write the failing tests** — `tests/test_agent_owner_report.py`:

```python
"""agent-costs --report owners (issue 432, spec test seam 1)."""
import json
import statistics
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .owner_transcripts import FINISH, RUN, Session, cost, finish_reply, gate_reply, progress


def report(root, *extra):
    completed = subprocess.run(
        [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--format",
         "json", "--days", "0", "--projects-dir", str(root), *extra],
        capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


class OwnerReportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    @staticmethod
    def chain(session):
        """Root owner (launch 1) hands off at Phase 2; owner a2 (launch 2) boots 29k → 98k."""
        g1 = session.call(None, 0, context=40_000, write=40_000, ttl="1h", bash=progress(1))
        session.result(None, 5, g1, gate_reply("continue"))
        session.measured(None, g1, 40_000)
        g2 = session.call(None, 60, context=120_000, write=80_000, ttl="1h", bash=progress(2))
        session.result(None, 65, g2, gate_reply("handoff"))
        session.measured(None, g2, 120_000)
        fin = session.call(None, 70, context=121_000, write=1_000, ttl="1h",
                           bash=progress(2, handoff="/r/.superpowers/workflows/x/handoffs/h.md"))
        session.result(None, 75, fin, gate_reply("handoff", handoff_path="h.md"))
        dispatch = session.call(None, 80, context=122_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("a2", tool_use_id=dispatch)
        for second, context in ((100, 29_000), (110, 50_000), (120, 75_000)):
            session.call("a2", second, context=context, write=context - 20_000 if context > 29_000 else 29_000)
        g3 = session.call("a2", 130, context=98_000, write=23_000,
                          bash=progress(3, action_id="7:1:2"))
        session.result("a2", 135, g3, gate_reply("continue", launch=2))
        session.measured("a2", g3, 98_000)
        work = session.call("a2", 140, context=99_000, write=1_000, agent_tool=True)
        session.child("w1", tool_use_id=work, parent="a2")
        session.call("w1", 150, context=30_000, write=30_000)
        session.result("a2", 400, work, "worker done")
        session.call("a2", 401, context=101_000, write=2_000)
        session.result(None, 402, dispatch, "a2 returned")
        return session

    def test_a_relaunched_owner_boot_from_29k_to_98k(self):
        self.chain(Session(self.root)).write()
        boots = report(self.root)["boots"]
        self.assertEqual(boots, [{"phase_group": "0-5", "count": 1, "b_p50": 98_000,
                                  "b_p90": 98_000, "start_p50": 29_000, "calls_p50": 4,
                                  "slimmable_p50": 0}])

    def test_a_two_launch_handoff_chain_with_a_worker_child(self):
        self.chain(Session(self.root)).write()
        [row] = report(self.root)["lineages"]
        self.assertEqual((row["run_id"], row["issue"], row["launches"], row["handoffs"],
                          row["boots"], row["peak_context"]), (RUN, 7, 2, 1, 1, 122_000))
        self.assertAlmostEqual(row["total_dollars"] - row["owner_dollars"], cost(30_000, 30_000),
                               places=9)
        self.assertEqual((row["gate_calls"], row["measured_gate_calls"]), (4, 3))
        self.assertEqual(row["long_child_waits"], 0)  # a2's gaps are under 300 s

    def test_a_six_minute_gap_rewrite_is_a_death_priced_as_a_5_minute_write(self):
        session = Session(self.root)
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        g = session.call("o1", 10, context=60_000, write=60_000, bash=progress(5))
        session.result("o1", 15, g, gate_reply("continue"))
        session.call("o1", 375, context=60_500, write=60_500)
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual(row["deaths"], 1)
        self.assertAlmostEqual(row["owner_dollars"],
                               cost(60_000, 60_000) + cost(60_500, 60_500), places=9)

    def test_dollars_per_delivered_issue_counts_undelivered_spend(self):
        delivered = Session(self.root, session="s1")
        g = delivered.call(None, 0, context=20_000, write=20_000, ttl="1h", bash=progress(6))
        delivered.result(None, 5, g, gate_reply("continue"))
        keeper = delivered.call(None, 10, context=21_000, write=1_000, ttl="1h", agent_tool=True)
        delivered.child("k1", tool_use_id=keeper)
        f = delivered.call("k1", 20, context=15_000, write=15_000, bash=FINISH)
        delivered.result("k1", 25, f, finish_reply(7))
        delivered.write()
        other = Session(self.root, project="-Users-me-other", session="s2")
        g8 = other.call(None, 0, context=30_000, write=30_000, ttl="1h",
                        bash=progress(3, action_id="8:1:1"))
        other.result(None, 5, g8, gate_reply("continue", issue=8))
        other.write()
        doc = report(self.root)
        rows = {row["issue"]: row for row in doc["lineages"]}
        self.assertEqual((rows[7]["delivered"], rows[8]["delivered"]), (True, False))
        [arm] = doc["arms"]
        self.assertEqual((arm["arm"], arm["n"], arm["delivered"]), ("live", 2, 1))
        self.assertAlmostEqual(arm["dollars_per_delivered"],
                               rows[7]["total_dollars"] + rows[8]["total_dollars"], places=9)
        self.assertAlmostEqual(arm["undelivered_dollars"], rows[8]["total_dollars"], places=9)
        self.assertIsNone(arm["sd"])

    def test_eval_grouping_two_arms_two_trials(self):
        rows, dollars = [], {}
        for index, (rev, verdict, write, exit_code) in enumerate(
                (("a" * 40, "PASS", 20_000, 0), ("a" * 40, "PASS", 40_000, 0),
                 ("b" * 40, "PASS", 30_000, 0), ("b" * 40, "FAIL", 50_000, 0),
                 ("b" * 40, "PASS", 60_000, 124)), 1):   # trial 5 timed out with its asserts passing
            workdir = f"/private/tmp/eval-from-issue-8.T{index}"
            session = Session(self.root, project=workdir.replace("/", "-").replace(".", "-") + "-repo",
                              session=f"s{index}")
            g = session.call(None, 0, context=write, write=write, ttl="1h", bash=progress(6))
            session.result(None, 5, g, gate_reply("continue"))
            session.write()
            dollars[index] = cost(write, write, write_price=8.0)
            rows.append({"skill": "from-issue", "id": 8, "trial": index, "verdict": verdict,
                         "workdir": workdir, "tree_rev": rev, "policy": None,
                         "claude_exit": exit_code})
        results = self.root / "results.jsonl"
        results.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
        doc = report(self.root, "--eval-results", str(results), "--eval", "from-issue:8")
        arms = {arm["arm"]: arm for arm in doc["arms"]}
        a, b = arms["aaaaaaaaaaaa/default"], arms["bbbbbbbbbbbb/default"]
        self.assertEqual((a["n"], a["delivered"], b["n"], b["delivered"]), (2, 2, 2, 1))
        self.assertAlmostEqual(a["dollars_per_delivered"], (dollars[1] + dollars[2]) / 2, places=9)
        self.assertAlmostEqual(a["sd"], statistics.stdev([dollars[1], dollars[2]]), places=9)
        self.assertAlmostEqual(b["dollars_per_delivered"], dollars[3] + dollars[4], places=9)
        self.assertEqual(sorted(row["verdict"] for row in doc["lineages"]),
                         ["FAIL", "PASS", "PASS", "PASS"])
        self.assertEqual(doc["interrupted"], [{"trial": 5, "tree_rev": "b" * 40, "claude_exit": 124}])

    def test_an_unknown_model_is_priced_approximately(self):
        session = Session(self.root)
        g = session.call(None, 0, context=10_000, write=10_000, ttl="1h", model="claude-opus-9",
                         bash=progress(1))
        session.result(None, 5, g, gate_reply("continue"))
        session.write()
        self.assertEqual(report(self.root)["pricing"]["approximate_calls"], 1)

    def test_phase_seven_entry_and_an_owner_long_child_wait(self):
        session = Session(self.root)
        g5 = session.call(None, 0, context=50_000, write=50_000, ttl="1h", bash=progress(5))
        session.result(None, 5, g5, gate_reply("continue"))
        child = session.call(None, 10, context=51_000, write=1_000, ttl="1h", agent_tool=True)
        session.child("i1", tool_use_id=child)
        session.call("i1", 20, context=20_000, write=20_000)
        session.call("i1", 500, context=21_000, write=1_000)
        session.result(None, 510, child, "done")
        g6 = session.call(None, 520, context=52_000, write=1_000, ttl="1h", bash=progress(6))
        session.result(None, 525, g6, gate_reply("delegate"))
        session.write()
        [row] = report(self.root)["lineages"]
        self.assertEqual((row["phase7_entered"], row["long_child_waits"], row["phase_reached"]),
                         (True, 1, 7))

    def test_owners_report_refuses_foreign_flags(self):
        for extra in (["--project", "x"], ["--artifacts", "docs"], ["--eval", "from-issue:8"],
                      ["--context-threshold", "5"]):
            with self.subTest(extra=extra):
                completed = subprocess.run(
                    [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners",
                     "--projects-dir", str(self.root), *extra],
                    capture_output=True, text=True, check=False)
                self.assertEqual(completed.returncode, 2)

    def test_text_output_prints_the_six_tables(self):
        self.chain(Session(self.root)).write()
        out = subprocess.run(
            [sys.executable, "-m", "agent_tools.agent_costs", "--report", "owners", "--days", "0",
             "--projects-dir", str(self.root)], capture_output=True, text=True, check=True).stdout
        for heading in ("Lineages", "Arms", "Fresh-owner boots by phase", "Simulated arms",
                        "Calibration", "Pricing: "):
            self.assertIn(heading, out)
```

In `chain`, the gate calls are the root's two progress calls, its finalise call and a2's gate; three carry measured notes. Before writing the module, check every asserted value by hand and fix the fixture (not the invariant) where one disagrees.

- [ ] **Step 3: Run the tests and watch them fail**

Run: **Report tests** naming `tests/test_agent_owner_report.py`.
Expected: FAIL — `agent-costs: error: argument --report: invalid choice: 'owners'`.

- [ ] **Step 4: Implement**

Put each invariant in its own function: `_owner_identity`, `_parent_of`, `_phases`, `_children`, `_slimmable`, `_delivered`, `_lineage_row`, `_arm_rows`, `_boot_rows`. One transcript scan, `scan_owner_transcript(job)`, runs in `agent_costs.scan_paths`'s pool and returns a plain picklable dict. Lineages are assembled in the parent process. `agent_costs.main` imports `agent_owner_report` only for `--report owners`, as it does for the cache report. `context_meter_commands.registers_owner` keeps its docstring and becomes:

```python
    return any(item.options.get("--action-id") is not None for item in invocations(tokens)
               if item.helper == "sdd-gate"
               or (item.helper == "workflow-state" and item.subcommand in ("progress", "mark-progress")))
```

It also keeps accepting `--action-id=<v>` (an `=` value is not `None`); `tests/test_context_meter.py` must stay green unchanged.

- [ ] **Step 5: Verify**

Run: **Report tests** naming `tests/test_agent_costs.py tests/test_agent_owner_report.py`, then **Meter and policy tests** naming only `tests/test_context_meter.py`.
Expected: `OK` from both. Then, on this host, run `just agent-costs --report owners --days 3 | head -30` and confirm it prints lineages with a `Pricing:` footer and exits 0. Paste nothing from it into the repo.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/agent_owner_report.py python/agent_tools/context_meter_commands.py \
  python/agent_tools/agent_costs.py tests/owner_transcripts.py tests/test_agent_owner_report.py \
  justfile python/README.md
launch-commit … -- -m "feat(agent-costs): owner report — dollars per delivered issue by lineage (issue 432)"
```
