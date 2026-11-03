# Task 2: The transform module and its registry

Spec § The reorder and § Interface, switch and keepalive, per D12–D17, D19 and D26. The task creates the library module `agent_tools.subagent_prefix`: one object, `SubagentPrefix`, holds the agent-id registry, and its one method `transform` returns the body, the header list and an outcome. The tests run on Task 1's sanitised fixtures and on variants derived from them. Nothing calls the module yet; Task 3 wires it into `cache-proxy`.

Task 1's harness ran the module text of Step 4, extracted from this file (D26). That text is the contract: create the module with it byte for byte, and change none of it.

**Files:**
- Create: `python/agent_tools/subagent_prefix.py`
- Modify: `tests/test_cache_proxy.py` (imports, docstring, fixture helpers, the new class `SubagentPrefixTest`)
- Read only: `tests/fixtures/cache_proxy/*.json` (committed by Task 1)

**Interfaces:**
- Consumes: Task 1's seven fixtures, each compact UTF-8 JSON with one trailing newline: `sibling1-first`, `sibling2-first` and `sibling1-second`, each as `.received.json` and `.forwarded.json`, and `parent-first.json`. Also `agent_tools.canonical.reject_duplicate_keys` and `reject_nonfinite_literal`, and `agent_tools.cache_keepalive.AGENT_HEADER`, `Headers` (`list[tuple[str, str]]`) and `header_value(headers, name)` (first value, case-insensitive, empty counts as absent).
- Produces (Tasks 3–5 rely on these exact names):
  - `subagent_prefix.SubagentPrefix(capacity: int = REGISTRY_CAPACITY)`, with `REGISTRY_CAPACITY == 4096`;
  - `.transform(method: str, path: str, headers: Headers, body: bytes) -> tuple[bytes, Headers, str]`;
  - `subagent_prefix.OUTCOMES` (frozenset `applied`, `applied_at_cap`, `not_subagent`, `unregistered`, `unparsed`, `shape`) and `subagent_prefix.REWRITTEN` (frozenset `applied`, `applied_at_cap`);
  - in `tests/test_cache_proxy.py`: `FIXTURES`, `MESSAGES`, `RANK`, `BUDGET`, `BUDGET_LINE`, `fixture_bytes`, `fixture`, `agent`, `encode`, `holders`, `marks`, `unmarked`, `kind` and `prompt_index`.

**Invariants:**
- Outside `REWRITTEN`, `transform` returns the very `body` and `headers` objects passed in (D17).
- A request that fails the method, path or agent-id check is never parsed (D12).
- An `applied` output has exactly one more mark than its input and an `applied_at_cap` output the same marks; neither has more than four, and the TTLs in prefix order never increase (D16).
- A rewrite returns compact UTF-8 JSON in the original key order, and every `Content-Length` header keeps its name and place with the new length as its value (D17, D26).
- An agent id is registered only by a first request (no assistant message) that comes out in `REWRITTEN` (D13). The registry is one lock-guarded map of at most `capacity` ids, oldest out first.
- The module starts nothing at import and uses only the standard library, `agent_tools.canonical` and `agent_tools.cache_keepalive`.

- [ ] **Step 1: Check the starting state**

Run (timeout 30 s): `grep -qx 'Attempt 2 verdict: go' docs/spikes/cache-proxy-prefix-retest.md && test "$(ls tests/fixtures/cache_proxy | wc -l | tr -d ' ')" -eq 7 && test ! -e python/agent_tools/subagent_prefix.py && echo ready`
Expected: `ready`. Without the `go` line, report BLOCKED `re-test gate not go` (D2).

- [ ] **Step 2: Write the failing tests**

In `tests/test_cache_proxy.py`, add `import copy`, `import re` and `from pathlib import Path` to the imports, and `from agent_tools import subagent_prefix` after `from agent_tools import cache_proxy`. Replace the docstring's first line with `` `cache-proxy` forwards requests and streamed responses (#422); `--reorder` reshapes subagent first messages (#429). `` and add, as the docstring's last sentence, `` `SubagentPrefixTest` calls `agent_tools.subagent_prefix` directly on the sanitised re-test captures in `tests/fixtures/cache_proxy/`. `` After `CLOSING_REPLY`, add:

```python
FIXTURES = Path(__file__).parent / "fixtures" / "cache_proxy"
MESSAGES = "/v1/messages?beta=true"
RANK = {"5m": 0, "1h": 1}
BUDGET = "<total_tokens>48213 tokens left</total_tokens>"
BUDGET_LINE = re.compile(r"<total_tokens>(?:[0-9]+|Infinite) tokens left</total_tokens>")


def fixture_bytes(name):
    return (FIXTURES / name).read_bytes()


def fixture(name):
    return json.loads(fixture_bytes(name))


def agent(agent_id=None, length=0):
    """Upstream headers as the proxy assembles them, with `agent_id` as the subagent header."""
    headers = [("Host", "api.anthropic.com"), ("content-type", "application/json")]
    if agent_id is not None:
        headers.append(("x-claude-code-agent-id", agent_id))
    return headers + [("Content-Length", str(length))]


def encode(value):
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def holders(value):
    """The test's own oracle: every object whose cache_control is a breakpoint, in prefix order."""
    found = [tool for tool in value.get("tools", []) if isinstance(tool, dict)]
    if isinstance(value.get("system"), list):
        found += [block for block in value["system"] if isinstance(block, dict)]
    for message in value.get("messages", []):
        content = message.get("content")
        for block in content if isinstance(content, list) else []:
            inner = block.get("content")
            found += [item for item in inner if isinstance(item, dict)] if isinstance(inner, list) else []
            found.append(block)
    found.append(value)
    return found


def marks(value):
    return [holder["cache_control"] for holder in holders(value) if "cache_control" in holder]


def unmarked(value):
    value = copy.deepcopy(value)
    for holder in holders(value):
        holder.pop("cache_control", None)
    return value


def kind(block):
    text = block["text"]
    if text.startswith("<system-reminder>"):
        return "attachment"
    return "budget" if BUDGET_LINE.fullmatch(text) else "prompt"


def prompt_index(content):
    [index] = [i for i, block in enumerate(content) if kind(block) == "prompt"]
    return index
```

Before `class CommandTest`, add:

```python
class SubagentPrefixTest(unittest.TestCase):
    """The transform on the re-test's sanitised captures (D19) and variants derived from them."""

    PAIRS = (("sibling1-first", "agent-1"), ("sibling2-first", "agent-2"),
             ("sibling1-second", "agent-1"))
    HOUR = {"type": "ephemeral", "ttl": "1h"}

    def run_transform(self, transform, source, agent_id="agent-1", path=MESSAGES, method="POST"):
        """(body, headers, result): what was passed and the transform's (body, headers, outcome)."""
        body = fixture_bytes(source) if isinstance(source, str) else encode(source)
        headers = agent(agent_id, len(body))
        return body, headers, transform.transform(method, path, headers, body)

    def assert_unchanged(self, body, headers, result, outcome):
        self.assertEqual(result[2], outcome)
        self.assertIs(result[0], body)
        self.assertIs(result[1], headers)

    def first(self):
        """Sibling 1's first request with every mark removed: the base of the variants."""
        return unmarked(fixture("sibling1-first.received.json"))

    def variant(self, places=(), top=None):
        """`first()` with marks at "tool0", "tool1", "system-1" (the last system block) or
        "tail" (the last block of messages[0]), and `top` as a top-level cache_control."""
        value = self.first()
        for where, mark in places:
            if where.startswith("tool"):
                value["tools"][int(where[4:])]["cache_control"] = mark
            elif where == "system-1":
                value["system"][-1]["cache_control"] = mark
            else:
                value["messages"][0]["content"][-1]["cache_control"] = mark
        if top is not None:
            value["cache_control"] = top
        return value

    def with_budget(self, offset):
        """`first()` with a budget line inserted at the prompt's index plus `offset`."""
        value = self.first()
        content = value["messages"][0]["content"]
        content.insert(prompt_index(content) + offset, {"type": "text", "text": BUDGET})
        return value

    def applied(self, value, expected="applied"):
        """A fresh transform's parsed output, and the mark on the block before its prompt."""
        _, _, (forwarded, _, outcome) = self.run_transform(subagent_prefix.SubagentPrefix(), value)
        self.assertEqual(outcome, expected)
        output = json.loads(forwarded)
        content = output["messages"][0]["content"]
        return output, content[prompt_index(content) - 1].get("cache_control")

    def test_fixture_pairs_transform_received_into_forwarded(self):
        transform = subagent_prefix.SubagentPrefix()
        for name, agent_id in self.PAIRS:
            with self.subTest(name=name):
                _, headers, (forwarded, sent, outcome) = self.run_transform(
                    transform, f"{name}.received.json", agent_id)
                self.assertIn(outcome, subagent_prefix.REWRITTEN)
                self.assertEqual(json.loads(forwarded), fixture(f"{name}.forwarded.json"))
                self.assertEqual(forwarded, encode(json.loads(forwarded)))
                self.assertEqual(sent, [(header, str(len(forwarded)) if header == "Content-Length"
                                         else value) for header, value in headers])

    def test_applied_outputs_add_one_mark_and_keep_ttls_non_increasing(self):
        transform = subagent_prefix.SubagentPrefix()
        for name, agent_id in self.PAIRS:
            with self.subTest(name=name):
                body, _, (forwarded, _, outcome) = self.run_transform(
                    transform, f"{name}.received.json", agent_id)
                before, after = marks(json.loads(body)), marks(json.loads(forwarded))
                self.assertEqual(len(after), len(before) + (outcome == "applied"))
                self.assertLessEqual(len(after), 4)
                ranks = [RANK[mark.get("ttl", "5m")] for mark in after]
                self.assertEqual(ranks, sorted(ranks, reverse=True))

    def test_sibling_outputs_agree_through_the_block_before_the_prompt(self):
        transform = subagent_prefix.SubagentPrefix()
        one, two = (json.loads(self.run_transform(transform, f"sibling{k}-first.received.json",
                                                  f"agent-{k}")[2][0]) for k in (1, 2))
        self.assertEqual(one["tools"], two["tools"])
        self.assertEqual(one["system"][1:], two["system"][1:])
        first, second = one["messages"][0]["content"], two["messages"][0]["content"]
        index = prompt_index(first)
        self.assertEqual(prompt_index(second), index)
        self.assertEqual(first[:index], second[:index])
        self.assertNotEqual(first[index], second[index])

    def test_a_later_turn_keeps_the_first_requests_reordered_first_message(self):
        transform = subagent_prefix.SubagentPrefix()
        first = json.loads(self.run_transform(transform, "sibling1-first.received.json")[2][0])
        _, _, (forwarded, _, outcome) = self.run_transform(transform,
                                                           "sibling1-second.received.json")
        self.assertIn(outcome, subagent_prefix.REWRITTEN)
        self.assertEqual(unmarked({"messages": [json.loads(forwarded)["messages"][0]]}),
                         unmarked({"messages": [first["messages"][0]]}))

    def test_a_later_turn_on_a_fresh_transform_is_unregistered_and_unchanged(self):
        self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(),
                                                  "sibling1-second.received.json"), "unregistered")

    def test_a_fork_shaped_request_is_unregistered_and_unchanged(self):
        transform = subagent_prefix.SubagentPrefix()
        self.run_transform(transform, "sibling1-first.received.json")
        self.assert_unchanged(*self.run_transform(transform, "sibling1-second.received.json",
                                                  "agent-fork"), "unregistered")

    def test_the_registry_evicts_its_oldest_id_past_capacity(self):
        transform = subagent_prefix.SubagentPrefix(capacity=2)
        for agent_id in ("agent-a", "agent-b", "agent-c"):
            self.assertIn(self.run_transform(transform, "sibling1-first.received.json",
                                             agent_id)[2][2], subagent_prefix.REWRITTEN)
        self.assertEqual(self.run_transform(transform, "sibling1-second.received.json",
                                            "agent-a")[2][2], "unregistered")
        for agent_id in ("agent-b", "agent-c"):
            self.assertIn(self.run_transform(transform, "sibling1-second.received.json",
                                             agent_id)[2][2], subagent_prefix.REWRITTEN)

    def test_blocks_before_the_prompt_and_attachments_after_it_keep_their_order(self):
        value = self.variant()
        content = value["messages"][0]["content"]
        index = prompt_index(content)
        later = content[index + 1:]
        expected = (content[:index] + [b for b in later if kind(b) == "attachment"]
                    + [content[index]] + [b for b in later if kind(b) == "budget"])
        output, _ = self.applied(value)
        self.assertEqual([b["text"] for b in output["messages"][0]["content"]],
                         [b["text"] for b in expected])
        self.assertEqual({k: v for k, v in output.items() if k != "messages"},
                         {k: v for k, v in value.items() if k != "messages"})
        self.assertEqual(output["messages"][1:], value["messages"][1:])

    def test_the_tail_mark_stays_on_the_last_block(self):
        tail = {"type": "ephemeral", "ttl": "5m"}
        output, mark = self.applied(self.variant([("tail", tail)]))
        content = output["messages"][0]["content"]
        self.assertEqual(content[-1]["cache_control"], tail)
        self.assertEqual([i for i, b in enumerate(content) if "cache_control" in b],
                         [prompt_index(content) - 1, len(content) - 1])
        self.assertEqual(mark, tail)

    def test_a_1h_system_mark_and_a_5m_tail_give_a_5m_mark(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR),
                                             ("tail", {"type": "ephemeral", "ttl": "5m"})]))
        self.assertEqual(mark, {"type": "ephemeral", "ttl": "5m"})

    def test_all_1h_marks_give_a_1h_mark(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR), ("tail", self.HOUR)]))
        self.assertEqual(mark, self.HOUR)

    def test_with_no_mark_after_it_the_new_mark_takes_the_preceding_ttl(self):
        _, mark = self.applied(self.variant([("system-1", self.HOUR)]))
        self.assertEqual(mark, self.HOUR)

    def test_with_no_marks_the_new_mark_has_no_ttl(self):
        output, mark = self.applied(self.variant())
        self.assertEqual(mark, {"type": "ephemeral"})
        self.assertEqual(marks(output), [{"type": "ephemeral"}])

    def test_four_marks_reorder_at_the_cap_with_marks_unchanged(self):
        value = self.variant([("tool0", self.HOUR), ("tool1", self.HOUR),
                              ("system-1", self.HOUR), ("tail", {"type": "ephemeral"})])
        output, mark = self.applied(value, "applied_at_cap")
        self.assertIsNone(mark)
        self.assertEqual(marks(output), marks(value))
        self.assertNotEqual(kind(output["messages"][0]["content"][-1]), "attachment")

    def test_a_top_level_cache_control_takes_a_slot_and_comes_last(self):
        self.applied(self.variant([("tool0", self.HOUR), ("system-1", self.HOUR),
                                   ("tail", {"type": "ephemeral"})], top={"type": "ephemeral"}),
                     "applied_at_cap")
        _, mark = self.applied(self.variant([("system-1", self.HOUR)], top={"type": "ephemeral"}))
        self.assertEqual(mark, {"type": "ephemeral"})

    def with_inner(self, value, mark):
        """`value` plus a later user message whose tool_result holds `mark` in its inner content."""
        value["messages"].append({"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "toolu_inner",
            "content": [{"type": "text", "text": "inner", "cache_control": mark}]}]})
        return value

    def test_an_inner_content_mark_takes_a_slot(self):
        places = [("tool0", self.HOUR), ("tool1", self.HOUR), ("system-1", self.HOUR)]
        self.applied(self.variant(places))
        value = self.with_inner(self.variant(places), {"type": "ephemeral"})
        output, mark = self.applied(value, "applied_at_cap")
        self.assertIsNone(mark)
        self.assertEqual(marks(output), marks(value))

    def test_an_inner_content_mark_sets_the_ttl_and_its_order(self):
        _, mark = self.applied(self.with_inner(self.variant([("system-1", self.HOUR)]),
                                               {"type": "ephemeral", "ttl": "5m"}))
        self.assertEqual(mark, {"type": "ephemeral", "ttl": "5m"})
        value = self.with_inner(self.variant([("system-1", {"type": "ephemeral", "ttl": "5m"})]),
                                dict(self.HOUR))
        self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(), value),
                              "shape")

    def test_a_budget_line_after_the_prompt_stays_after_it(self):
        output, mark = self.applied(self.with_budget(1))
        content = output["messages"][0]["content"]
        self.assertEqual(content[-1], {"type": "text", "text": BUDGET})
        self.assertEqual(prompt_index(content), len(content) - 2)
        self.assertEqual(mark, {"type": "ephemeral"})

    def test_a_budget_line_before_the_prompt_keeps_its_place(self):
        value = self.with_budget(0)
        index = prompt_index(value["messages"][0]["content"])
        output, _ = self.applied(value)
        self.assertEqual(output["messages"][0]["content"][index - 1]["text"], BUDGET)

    def test_unexpected_shapes_pass_through_as_shape(self):
        def prompt_first(value):
            content = value["messages"][0]["content"]
            content.insert(0, content.pop(prompt_index(content)))

        def two_prompts(value):
            value["messages"][0]["content"].append({"type": "text", "text": "a second prompt"})

        def budget_with_text(value):
            value["messages"][0]["content"].append({"type": "text", "text": BUDGET + "\nand a note"})

        def non_text_block(value):
            value["messages"][0]["content"][0] = {
                "type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ""}}

        def middle_mark(value):
            value["messages"][0]["content"][0]["cache_control"] = {"type": "ephemeral"}

        def five_marks(value):
            for tool in value["tools"][:4]:
                tool["cache_control"] = dict(self.HOUR)
            value["messages"][0]["content"][-1]["cache_control"] = {"type": "ephemeral"}

        def unknown_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "2h"}

        def unhashable_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": ["1h"]}

        def rising_ttl(value):
            value["system"][-1]["cache_control"] = {"type": "ephemeral", "ttl": "5m"}
            value["messages"][0]["content"][-1]["cache_control"] = dict(self.HOUR)

        def mark_not_an_object(value):
            value["system"][-1]["cache_control"] = "ephemeral"

        self.assertGreaterEqual(len(self.first()["tools"]), 4)
        for change in (prompt_first, two_prompts, budget_with_text, non_text_block, middle_mark,
                       five_marks, unknown_ttl, unhashable_ttl, rising_ttl, mark_not_an_object):
            with self.subTest(change=change.__name__):
                value = self.first()
                change(value)
                self.assert_unchanged(*self.run_transform(subagent_prefix.SubagentPrefix(), value),
                                      "shape")

    def test_unparseable_bodies_pass_through_as_unparsed(self):
        for body in (b'{"a":1,"a":2}', b'{"system":NaN}', b"[]", b'{"system":"\\ud800"}',
                     b"\xff", b"", b"[" * 100000 + b"]" * 100000):
            with self.subTest(body=body[:20]):
                headers = agent("agent-1", len(body))
                self.assert_unchanged(body, headers, subagent_prefix.SubagentPrefix().transform(
                    "POST", MESSAGES, headers, body), "unparsed")

    def test_requests_other_than_subagent_messages_are_never_rewritten(self):
        sibling = fixture_bytes("sibling1-first.received.json")
        parent = fixture_bytes("parent-first.json")
        main = fixture("sibling1-first.received.json")
        prefix = "x-anthropic-billing-header:"
        fields = main["system"][0]["text"][len(prefix):].split(";")
        self.assertIn("cc_is_subagent=true", [field.strip() for field in fields])
        main["system"][0]["text"] = prefix + ";".join(
            field for field in fields if field.strip() != "cc_is_subagent=true")
        cases = (("POST", MESSAGES, None, sibling), ("POST", MESSAGES, "", sibling),
                 ("GET", MESSAGES, "agent-1", sibling),
                 ("POST", "/v1/messages/count_tokens?beta=true", "agent-1", sibling),
                 ("POST", MESSAGES, "agent-1", encode(main)),
                 ("POST", MESSAGES, "agent-1", parent), ("POST", MESSAGES, None, parent))
        for method, path, agent_id, body in cases:
            with self.subTest(method=method, path=path, agent_id=agent_id):
                headers = agent(agent_id, len(body))
                self.assert_unchanged(body, headers, subagent_prefix.SubagentPrefix().transform(
                    method, path, headers, body), "not_subagent")
```

- [ ] **Step 3: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py 2>&1 | tail -n 30`
Expected: FAIL. The test module does not import: `ModuleNotFoundError: No module named 'agent_tools.subagent_prefix'`.

- [ ] **Step 4: Write the module**

Create `python/agent_tools/subagent_prefix.py` from the block below with the same extraction Task 1's harness used, so its bytes are the ones the re-test ran (D26). Run (timeout 30 s) from the worktree root:

```bash
python3 -I - .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.tasks/task-2.md python/agent_tools/subagent_prefix.py <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
start = [i for i, line in enumerate(lines) if line.startswith('"""Reorder a subagent\'s first user message')]
if len(start) != 1:
    sys.exit(f"want one module block, found {len(start)}")
end = lines.index("```", start[0])
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines[start[0]:end]) + "\n")
EOF
```

The block (the mark order, the TTL inheritance, the budget-line rule and the in-place reorder are the contract, D14–D16):

```python
"""Reorder a subagent's first user message so sibling subagents share a cached prefix (#429).

`SubagentPrefix().transform(method, path, headers, body)` returns the body and header list to
forward and an outcome from `OUTCOMES`. For a Claude Code subagent's `POST /v1/messages` it moves
the delegation prompt in `messages[0]` after the `<system-reminder>` attachments that follow it,
keeps any `<total_tokens>` budget line that followed the prompt after it, and, while the body
holds fewer than four cache breakpoints, marks the block just before the prompt as one. A
subagent's later turns are reordered only once its first request was, so a forked subagent keeps
its parent's prefix. Every other request, and every body of another shape, comes back as the
bytes and headers it arrived with.
"""

from __future__ import annotations

from collections import OrderedDict
import json
import re
import threading
from urllib.parse import urlsplit

from agent_tools.cache_keepalive import AGENT_HEADER, Headers, header_value
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal

MESSAGES_PATH = "/v1/messages"
BILLING_PREFIX = "x-anthropic-billing-header:"
SUBAGENT_FIELD = "cc_is_subagent=true"
ATTACHMENT_PREFIX = "<system-reminder>"
BUDGET_LINE = re.compile(r"<total_tokens>(?:[0-9]+|Infinite) tokens left</total_tokens>")
MAX_MARKS = 4  # the API's breakpoint limit; a top-level cache_control takes one slot
TTL_RANK = {"5m": 0, "1h": 1}
DEFAULT_TTL = "5m"
REGISTRY_CAPACITY = 4096
REWRITTEN = frozenset({"applied", "applied_at_cap"})
OUTCOMES = REWRITTEN | {"not_subagent", "unregistered", "unparsed", "shape"}


def _encode(value) -> bytes:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _decode(body: bytes):
    """The body as a JSON object that re-encodes, or None (`unparsed`)."""
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=reject_duplicate_keys,
                           parse_constant=reject_nonfinite_literal)
        if isinstance(value, dict):
            _encode(value)
            return value
    except (ValueError, RecursionError):  # UnicodeError is a ValueError
        pass
    return None


def _is_subagent(value) -> bool:
    system = value.get("system")
    block = system[0] if isinstance(system, list) and system else None
    text = block.get("text") if isinstance(block, dict) and block.get("type") == "text" else None
    if not isinstance(text, str) or not text.startswith(BILLING_PREFIX):
        return False
    return SUBAGENT_FIELD in {field.strip() for field in text[len(BILLING_PREFIX):].split(";")}


def _has_assistant(value) -> bool:
    messages = value.get("messages")
    return isinstance(messages, list) and any(
        isinstance(message, dict) and message.get("role") == "assistant" for message in messages)


def _holders(value) -> list:
    """Every object whose `cache_control` is a breakpoint, in prefix order (D14, D16)."""
    holders = []
    for key in ("tools", "system"):
        items = value.get(key)
        if isinstance(items, list):
            holders.extend(item for item in items if isinstance(item, dict))
    messages = value.get("messages")
    for message in messages if isinstance(messages, list) else ():
        content = message.get("content") if isinstance(message, dict) else None
        for block in content if isinstance(content, list) else ():
            if isinstance(block, dict):
                inner = block.get("content")
                if isinstance(inner, list):  # a block's inner content precedes its own mark
                    holders.extend(item for item in inner if isinstance(item, dict))
                holders.append(block)
    holders.append(value)  # a top-level cache_control (automatic caching) sits last
    return holders


def _marks(holders) -> list:
    return [holder["cache_control"] for holder in holders if "cache_control" in holder]


def _marks_valid(marks) -> bool:
    """At most four marks, each an object with a known TTL, none longer than one before it."""
    if len(marks) > MAX_MARKS:
        return False
    ranks = []
    for mark in marks:
        ttl = mark.get("ttl", DEFAULT_TTL) if isinstance(mark, dict) else None
        if not isinstance(ttl, str) or ttl not in TTL_RANK:
            return False
        ranks.append(TTL_RANK[ttl])
    return all(earlier >= later for earlier, later in zip(ranks, ranks[1:]))


def _kind(text: str) -> str:
    if text.startswith(ATTACHMENT_PREFIX):
        return "attachment"
    return "budget" if BUDGET_LINE.fullmatch(text) else "prompt"


def _reorder(value) -> str | None:
    """Reorder `value` in place and return the outcome, or None (`shape`) before any change."""
    messages = value.get("messages")
    first = messages[0] if isinstance(messages, list) and messages else None
    if not isinstance(first, dict) or first.get("role") != "user":
        return None
    content = first.get("content")
    if not isinstance(content, list) or not all(
            isinstance(block, dict) and block.get("type") == "text"
            and isinstance(block.get("text"), str) for block in content):
        return None
    kinds = [_kind(block["text"]) for block in content]
    if kinds.count("prompt") != 1 or kinds[0] == "prompt":
        return None
    if any("cache_control" in block for block in content[:-1]):
        return None
    marks = _marks(_holders(value))
    if not _marks_valid(marks):
        return None
    index = kinds.index("prompt")
    later = list(zip(content[index + 1:], kinds[index + 1:]))
    attachments = [block for block, kind in later if kind == "attachment"]
    reordered = (content[:index] + attachments + [content[index]]
                 + [block for block, kind in later if kind == "budget"])
    if reordered[-1] is not content[-1] and "cache_control" in content[-1]:
        reordered[-1]["cache_control"] = content[-1].pop("cache_control")
    first["content"] = reordered
    if len(marks) == MAX_MARKS:
        return "applied_at_cap"
    target = reordered[index + len(attachments) - 1]  # the block just before the prompt
    holders = _holders(value)
    position = next(i for i, holder in enumerate(holders) if holder is target)
    following, preceding = _marks(holders[position + 1:]), _marks(holders[:position])
    source = following[0] if following else preceding[-1] if preceding else None
    mark = {"type": "ephemeral"}
    if source is not None and "ttl" in source:
        mark["ttl"] = source["ttl"]
    target["cache_control"] = mark
    return "applied"


def _with_length(headers: Headers, length: int) -> Headers:
    return [(name, str(length)) if name.lower() == "content-length" else (name, value)
            for name, value in headers]


class SubagentPrefix:
    """The reorder, plus the registry of agent ids whose first request it reordered (D13)."""

    def __init__(self, capacity: int = REGISTRY_CAPACITY):
        self.capacity = capacity
        self._registry: OrderedDict[str, None] = OrderedDict()
        self._lock = threading.Lock()

    def transform(self, method: str, path: str, headers: Headers,
                  body: bytes) -> tuple[bytes, Headers, str]:
        """`(body, headers, outcome)` to forward. Outside `REWRITTEN` the body and headers are
        the very objects passed in; a rewrite returns new bytes and a new header list whose every
        `Content-Length` value is the new length, each header keeping its name and place."""
        agent_id = header_value(headers, AGENT_HEADER)
        if method != "POST" or urlsplit(path).path != MESSAGES_PATH or agent_id is None:
            return body, headers, "not_subagent"
        value = _decode(body)
        if value is None:
            return body, headers, "unparsed"
        if not _is_subagent(value):
            return body, headers, "not_subagent"
        first_request = not _has_assistant(value)
        if not first_request and not self._registered(agent_id):
            return body, headers, "unregistered"
        outcome = _reorder(value)
        if outcome is None:
            return body, headers, "shape"
        if first_request:
            self._register(agent_id)
        forwarded = _encode(value)
        return forwarded, _with_length(headers, len(forwarded)), outcome

    def _registered(self, agent_id: str) -> bool:
        with self._lock:
            return agent_id in self._registry

    def _register(self, agent_id: str) -> None:
        with self._lock:
            self._registry[agent_id] = None
            self._registry.move_to_end(agent_id)
            while len(self._registry) > self.capacity:
                self._registry.popitem(last=False)
```

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_cache_proxy.py tests/test_cache_keepalive.py 2>&1 | tail -n 30`
Expected: PASS, every test (the existing `ForwardingTest`, `CommandTest` and keepalive cases unchanged), no warnings.

Run (timeout 30 s), the check that the module is the text the re-test ran (D26): `test "$(shasum -a 256 python/agent_tools/subagent_prefix.py | cut -d' ' -f1)" = "$(sed -n 's/^Attempt 2 transform sha256: \([0-9a-f]\{64\}\)$/\1/p' docs/spikes/cache-proxy-prefix-retest.md)" && echo same-transform`. Expected: `same-transform`; anything else is BLOCKED `module differs from the re-test's transform`.

Run (timeout 30 s): `git diff --stat 20241ee3 -- python tests home lib justfile`. Expected: only `python/agent_tools/subagent_prefix.py` and `tests/test_cache_proxy.py`, besides Task 1's `tests/fixtures/cache_proxy/` files.

If a fixture test fails because a capture contradicts the spec (the siblings disagree before the prompt, or a later turn's `messages[0]` differs from the first request's), change neither the fixture, the test nor the module. Report BLOCKED with the failing assertion: the capture contradicts D13 or D14.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/subagent_prefix.py tests/test_cache_proxy.py
launch-commit … -- -m "feat(cache-proxy): subagent prefix transform and its agent-id registry (issue 429)" -m "<session trailers>"
```
