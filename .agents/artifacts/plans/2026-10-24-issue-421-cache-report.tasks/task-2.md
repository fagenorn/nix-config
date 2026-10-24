# Task 2: The per-transcript cache scanner

Spec § Transcript model, § Cache deaths, § Context above the threshold and § Subagent start-up overhead, per D2–D8, D10, D12 and D13. A new module, `agent_tools.agent_cache_report`, holds one function that a process pool can map over `(path, is_root)` jobs: it reads one transcript once and returns that transcript's calls in the window, its cache deaths with cause and premium, its reread cost above the threshold, its peak context and, for a subagent, its start-up overhead. Aggregation and printing are Task 3's.

**Files:**
- Create: `python/agent_tools/agent_cache_report.py`
- Test: `tests/test_agent_costs.py` (new helpers and `CacheScanTest`, placed directly before `class ModuleEntryPointTest`)

**Interfaces:**
- Consumes (Task 1): `agent_costs.cache_write_split(usage) -> (cw_1h, cw_5m)` and `agent_costs.PRICING["opus"] == (5.0, 25.0, 10.0, 6.25, 0.50)`. Also, from base: `agent_costs.PRICING`, `model_family`, `parse_rfc3339_utc` (raises `ValueError` on a non-string or a non-RFC3339 value), `event_in_window(value, start, end) -> bool | None`.
- Produces:
  - `agent_cache_report.DEFAULT_CONTEXT_THRESHOLD = 120_000`
  - `agent_cache_report.STARTUP_ATTACHMENTS = ("skill_listing", "instructions", "mcp_instructions_delta", "deferred_tools_delta", "agent_listing_delta", "environment")` — Task 3 prints the start-up columns in this order.
  - `agent_cache_report.scan_transcript(job, *, since, before, threshold) -> dict | None`, where `job = (path: Path, is_root: bool)`, `since`/`before` are aware UTC datetimes or both `None`, `threshold` a positive int. `None` when the transcript cannot be opened. Otherwise exactly these keys (D13):
    - `agent_type: str` — `"main"` for a root transcript; for a subagent the `agentType` of the sibling `<stem>.meta.json`, or `"unknown"` when that file is missing, unreadable, not a JSON object, or its `agentType` is not a non-empty string.
    - `is_root: bool` — the job's flag.
    - `calls: int` — counting calls.
    - `deaths: list[dict]` — one `{"kind": str, "gap_s": float, "premium": float}` per death, in call order; `premium` in dollars.
    - `reread_above: float` — dollars; `0.0` when nothing counts.
    - `peak_ctx: int | None` — the largest counting-call context; `None` when no call counts.
    - `startup: dict | None` — `{"write": int, "read": int, "attachments": {attachment type: characters}}` for a subagent whose first call counts, else `None`.
  - Test helpers in `tests/test_agent_costs.py` that Task 3 reuses: `CACHE_T0`, `at`, `cache_usage`, `cache_call`, `tool_use`, `tool_result`, `user_prompt`, `wake`, `attachment`, `HANDBACK`, `write_root`, `write_subagent`, `scan_cache`, `handback_death_lines`.

**Invariants:**
- Read pass (D12). Open with `open(path, "r", errors="replace")`; `OSError` returns `None` before anything else is read. Line `i` (0-based) is parsed only when it contains `"type":"assistant"`, `"type":"user"` or `"type":"attachment"`; a line that is not valid JSON, or not an object, is skipped. Dispatch on the record's own `type`.
- Calls (D4). An `assistant` record with a `message` object belongs to the call keyed `message.id`, else `requestId`, else `uuid` (no key: skipped). A call keeps its first and last line, its earliest and latest parsable record `timestamp` (the earliest also as the raw string), its first non-empty `message.model`, the per-field maximum of `input_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens`, `output_tokens` and of `cache_creation.ephemeral_1h_input_tokens`/`ephemeral_5m_input_tokens` over its records' `message.usage` objects (missing or `null` read as 0), and a map from each `tool_use` content block's `id` to its `name`. Calls are ordered by first line. A call's **context** is `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`; a call whose context is 0 is dropped before anything below (a synthetic error message).
- Window (D3, D12). With `since` and `before` given, a call counts when its earliest raw timestamp exists and `event_in_window(raw, since, before) is True`; with both `None`, every call counts, untimed ones included.
- Deaths (issue rule, D5, D6). Call `k ≥ 1` with predecessor `p = k − 1` is a death when `k` counts, `context(p) > 5_000`, both `end(p)` and `start(k)` exist, `gap = (start(k) − end(p)).total_seconds()` exceeds `TTL − 10` (TTL 3,600 for a root transcript, 300 for a subagent) and `2 × cache_creation(k) > context(p)`.
- Cause (D5, D12). Only `user` records whose line lies strictly between `p`'s first line and `k`'s first line are read. A record whose `message.content` is a list holding a `tool_result` block is a **result** carrying its blocks' `tool_use_id`s and whether the record has `toolEndsTurn: true`; any other `user` record is a **waker** — `hand-back after end of turn` when `origin.kind == "peer"` and `origin.handback is True`, `task notification after end of turn` when `origin.kind == "task-notification"`, else `message after end of turn`. The tool of the last non-turn-ending result whose id is one of `p`'s own tool uses decides first: `Agent` or `Task` → `child dispatch`, `Bash` → `long foreground command`, any other → `other tool`. Without one, the first waker's kind; without either, `unclassified`.
- Premium (D6): `min(cache_creation(k), context(p)) × (w − p_read) / 1e6`, where `p_in, p_out, p_1h, p_5m, p_read = PRICING[model_family(model(k))]`, `cw_1h, cw_5m = cache_write_split(usage(k))` and `w = (cw_1h × p_1h + cw_5m × p_5m) / (cw_1h + cw_5m)`; the denominator is positive because a death has `cache_creation > 0`.
- Reread (D7): the sum over counting calls of `max(0, cache_read_input_tokens − threshold) × p_read / 1e6`, each at its own family's read price.
- Start-up (D8, D12): for a subagent whose first call counts, `write`/`read` are that call's `cache_creation_input_tokens`/`cache_read_input_tokens`. For each type in `STARTUP_ATTACHMENTS`, the first `attachment` record whose `attachment.type` is that type is kept when its line is before the second call's first line (any line when there is no second call) and it has a `rendered` list; its size is the summed `len` of the string `content` of the list's object items. A type without such a record is absent from `attachments`.
- The module copies nothing `agent_costs` owns (Global Constraints) and starts no process at import.

- [ ] **Step 1: Write the failing tests**

Add `from datetime import datetime, timedelta, timezone` to the imports and `from agent_tools import agent_cache_report` beside `from agent_tools import agent_costs`. Then add, directly before `class ModuleEntryPointTest`:

```python
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
        # the rewrite is min(32,500 created, 32,002 prior context), at the Opus
        # 5-minute write price less the read a warm cache would have paid
        self.assertAlmostEqual(death["premium"], 32_002 * (6.25 - 0.50) / 1e6, places=12)
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
        weighted = (30_000 * 10.0 + 10_000 * 6.25) / 40_000
        self.assertAlmostEqual(result["deaths"][0]["premium"],
                               36_002 * (weighted - 0.50) / 1e6, places=12)

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
            cache_call("m3", 21, 150_000, 1_000),                              # above, Opus
            cache_call("m4", 31, 130_000, 1_000, model="claude-sonnet-5-5"),   # above, Sonnet
        ])
        result = scan_cache(path)
        self.assertEqual(result["calls"], 4)
        self.assertAlmostEqual(result["reread_above"],
                               (30_000 * 0.50 + 10_000 * 0.30) / 1e6, places=12)
        self.assertEqual(result["peak_ctx"], 2 + 150_000 + 1_000)
        self.assertEqual(result["deaths"], [])
        self.assertAlmostEqual(scan_cache(path, threshold=140_000)["reread_above"],
                               10_000 * 0.50 / 1e6, places=12)

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
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (focused test run, timeout 600 s): `-k CacheScanTest`
Expected: the module fails to import — `ModuleNotFoundError: No module named 'agent_tools.agent_cache_report'`.

- [ ] **Step 3: Implement `python/agent_tools/agent_cache_report.py`**

Module docstring, exactly (Task 3 extends it):

```python
"""The cache report's per-transcript scanner (issue 421).

scan_transcript reads one Claude Code transcript and returns its calls in the
window, its cache deaths with their cause and premium, its cache-read cost above
a context threshold, its peak context and, for a subagent, its start-up overhead.
"""
```

Imports: `json`; `dataclass`, `field` from `dataclasses`; `PRICING`, `cache_write_split`, `event_in_window`, `model_family`, `parse_rfc3339_utc` from `agent_tools.agent_costs`. Constants: `DEFAULT_CONTEXT_THRESHOLD`, `STARTUP_ATTACHMENTS` (Interfaces), `TTL_SECONDS = {True: 3_600, False: 300}` with a comment naming root transcript and subagent, `TTL_SLACK_SECONDS = 10`, `MIN_DEATH_CONTEXT = 5_000`.

One private `@dataclass` per call with the fields `first_line`, `last_line`, `start`, `start_raw`, `end`, `model`, `usage` and `tool_names` and a `context` property, holding what the Calls invariant lists. `usage` is created (through a `default_factory`) holding the four token keys and a `cache_creation` object with both TTL keys, all 0 until a record raises them; `tool_names` starts as an empty dict. `scan_transcript` does the read pass, drops zero-context calls, reads the agent type (only after the transcript opened), and computes the window flags once, then the four measures. Keep the decision logic in small private functions; the cause and premium, which embody D5, D6 and D12, are exactly:

```python
def _cause(prev, call, user_records):
    """Death kind of `call`, from the user records between it and `prev` (D5, D12)."""
    between = [entry for entry in user_records if prev.first_line < entry[1] < call.first_line]
    tool = None
    for entry in between:
        if entry[0] == "result" and not entry[3]:          # ("result", line, ids, ends_turn)
            for tool_id in entry[2]:
                if tool_id in prev.tool_names:
                    tool = prev.tool_names[tool_id]
    if tool is not None:
        if tool in ("Agent", "Task"):
            return "child dispatch"
        if tool == "Bash":
            return "long foreground command"
        return "other tool"
    for entry in between:
        if entry[0] == "wake":                              # ("wake", line, kind)
            return entry[2]
    return "unclassified"


def _premium(prev, call):
    """Rewrite cost beyond a warm read of the prefix that was cached (D6), in dollars."""
    _, _, p_1h, p_5m, p_read = PRICING[model_family(call.model)]
    cw_1h, cw_5m = cache_write_split(call.usage)
    write = (cw_1h * p_1h + cw_5m * p_5m) / (cw_1h + cw_5m)
    return min(call.usage["cache_creation_input_tokens"], prev.context) * (write - p_read) / 1e6
```

`call.usage` is the merged usage in a transcript usage object's shape (`cache_creation` a nested object), so `cache_write_split` reads it unchanged. A `wake` entry's kind is one of the three waker labels in the Cause invariant, decided when the record is read.

- [ ] **Step 4: Verify**

Run (focused test run, timeout 600 s): `-k CacheScanTest`
Expected: `Ran 12 tests` … `OK`.

Run (focused test run, timeout 600 s) with no `-k`.
Expected: `Ran 102 tests` … `OK`.

Run: `bash -c 'if grep -nE "^(PRICING|DISCLAIMER) =|^def (model_family|cache_write_split|event_in_window|parse_rfc3339_utc|percentile|human|print_table|find_sessions|scan_paths)\(|TODO|FIXME" python/agent_tools/agent_cache_report.py; then exit 1; fi'`
Expected: exit 0, no output.

Run (build, timeout 3600 s).
Expected: exit 0 (the new module passes the build-time import check).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/agent_cache_report.py tests/test_agent_costs.py
launch-commit … -- -m "feat(agent-costs): per-transcript cache scanner (issue 421)" \
  -m "Calls in the window, cache deaths with cause and premium, reread above a context threshold, peak context and subagent start-up overhead." \
  -m "<session trailers>"
```
