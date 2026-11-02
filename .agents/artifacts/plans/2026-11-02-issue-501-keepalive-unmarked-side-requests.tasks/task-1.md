# Task 1: Side requests leave a conversation's turn alone

Spec § Solution, § Decisions (D1–D3), § Test seams cases 1–6, § Docs. Rests on D1, D2, D3, D4, D5 and D6. After this task a `no_tail_mark` request (a *side request*) only registers its flight in `Keepalive.observe`. It leaves the conversation's request sequence, pending tool, last request and idle period as they were. A `tool_use` that is pending therefore survives side requests until the conversation's own next request, and a side request never supersedes a ping. This task owns AC1 and AC2. Its red run proves the new tests fail on the base code, and it writes the acceptance record.

**Files:**
- Modify: `python/agent_tools/cache_keepalive.py`
- Test: `tests/test_cache_keepalive.py`
- Modify: `python/README.md`
- Create: `.agents/artifacts/plans/2026-11-02-issue-501-keepalive-unmarked-side-requests.acceptance.md`

**Interfaces:**
- Consumes (present at base): in `tests/test_cache_keepalive.py`, `KeepaliveCase` (`self.clock`, `self.keepalive`, `exchange(agent, value=None, *, session=SESSION, status=200, stop_reason="end_turn", finish=True)`, which returns the track and, with `finish=False`, stops after `started`; `due(seconds)`; `events(event)`; `ends()`, a list of `(conversation, reason, pings)`; `handle(agent, session=SESSION)`), and the module names `AGENT_P`, `AGENT_Q`, `OTHER_SESSION`, `document`, `pieces`, `sse`.
- Produces: `Track.__init__(..., sequence: int | None = None, ...)`, where the default changes from `0` to `None` and every other parameter stays the same. Also `SideRequestTest(KeepaliveCase)` with helpers `side(agent=AGENT_P, **kwargs)` and `pinged(seconds) -> list[str]`, and its six tests.

**Invariants:**
- For a `no_tail_mark` request, `observe` finds or creates the record, builds the track as today (outcome, handle, identity headers) with sequence `None`, and adds the track to `record.in_flight`. It never logs `keepalive_end`, never writes `last_request`, `epoch` or `pending_since`, and never resets `pings` (D2, D3).
- For every other outcome except `untracked`, `observe` behaves exactly as at base, and the track's sequence is the record's `epoch` after the increment.
- `observe` is the only place that tests for `no_tail_mark` to decide the sequence (D3). The bodies of `_done`, `_apply`, `_settle`, `tick`, `_prune`, `_active`, `_build_ping` and `_log_end` do not change. A `None` sequence never equals `record.epoch`, so a side track never marks pending. A side track still leaves `in_flight` and records its `stop_reason` at `done`.
- A side-only conversation, which has no thread request yet and so `last_request` `None`, never breaks `tick`. `_active` already guards `None`, `_prune` treats `None` as old, and every other reader runs only for candidate holders. The planning prototype saw such a record pruned at the first tick. No code change is needed for it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_cache_keepalive.py`, insert this class, followed by two blank lines, immediately before the line `class FailingPingTest(KeepaliveCase):`. Change no other line of the file.

```python
class SideRequestTest(KeepaliveCase):
    """Side requests (`no_tail_mark`) in a conversation whose own request is pending a tool:
    session activity only while in flight, never the conversation's next turn (issue 501)."""

    def side(self, agent=AGENT_P, **kwargs):
        """A side request as Claude Code sends a fork or side query: the conversation's own agent
        id and no cache mark on the last message."""
        return self.exchange(agent, document(tail_mark=False, note="side"), **kwargs)

    def pinged(self, seconds):
        """Advance the clock, send every ping now due, and return their conversations."""
        pings = self.due(seconds)
        for ping in pings:
            self.keepalive.send(ping)
        return [ping.conversation for ping in pings]

    def test_a_side_request_after_a_tool_use_keeps_the_tool_pending_until_its_result(self):
        self.exchange(AGENT_P, stop_reason="tool_use")
        self.clock.advance(9)
        self.side()
        self.assertEqual([self.pinged(261), self.pinged(270), self.pinged(270)],
                         [[self.handle(AGENT_P)]] * 3)
        self.clock.advance(30)
        self.exchange(AGENT_P, document(note="tool result"))
        [end] = self.events("keepalive_end")
        self.assertEqual((end["conversation"], end["reason"], end["pings"], end["idle_s"]),
                         (self.handle(AGENT_P), "resumed", 3, 840.0))

    def test_a_side_request_while_the_tool_use_still_streams_leaves_it_pending(self):
        thread = self.exchange(AGENT_P, finish=False)
        self.clock.advance(3)
        self.side()
        self.clock.advance(4)
        for piece in pieces(sse("tool_use")):
            thread.chunk(piece)
        thread.done("complete")
        self.assertEqual([self.pinged(263), self.pinged(270)], [[self.handle(AGENT_P)]] * 2)
        self.assertEqual(self.ends(), [])

    def test_a_side_request_inside_a_pinged_period_neither_ends_it_nor_resets_its_count(self):
        self.exchange(AGENT_P, stop_reason="tool_use")
        self.assertEqual(self.pinged(270), [self.handle(AGENT_P)])
        self.clock.advance(9)
        self.side()
        self.assertEqual(self.ends(), [])
        self.assertEqual(self.pinged(261), [self.handle(AGENT_P)])
        self.clock.advance(30)
        self.exchange(AGENT_P, document(note="tool result"))
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "resumed", 2)])

    def test_a_side_request_while_a_ping_is_in_flight_does_not_supersede_it(self):
        self.exchange(AGENT_P, stop_reason="tool_use")
        [ping] = self.due(270)
        self.clock.advance(5)
        self.side()
        self.clock.advance(5)
        self.keepalive.send(ping)
        self.assertEqual(self.due(5), [])
        self.assertEqual(self.due(264), [])
        self.assertEqual(self.pinged(1), [self.handle(AGENT_P)])

    def test_a_finished_side_request_leaves_no_activity_whatever_its_stop_reason(self):
        self.exchange(AGENT_P)
        self.exchange(AGENT_Q, session=OTHER_SESSION)
        self.clock.advance(9)
        self.side()
        forked = self.side(AGENT_Q, session=OTHER_SESSION, stop_reason="tool_use")
        self.assertEqual(self.due(261), [])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "session_idle", 0),
                                       (self.handle(AGENT_Q, OTHER_SESSION), "session_idle", 0)])
        self.assertEqual(forked.log_fields(),
                         {"keepalive": "no_tail_mark",
                          "conversation": self.handle(AGENT_Q, OTHER_SESSION),
                          "stop_reason": "tool_use"})

    def test_a_side_request_in_flight_keeps_the_session_active(self):
        self.exchange(AGENT_P)
        self.clock.advance(9)
        self.side(finish=False)
        self.assertEqual(self.pinged(261), [self.handle(AGENT_P)])
```

The clock starts at 1000.0, so P's thread request is sent at 1000 and its dues fall at 1270, 1540 and 1810. Case 1's tool result arrives at 1840, so `idle_s` is 840.0, counted from P's thread request and not from the side request at 1009 (D2, D6). Case 4 sends the ping at 1280, so the next due is 1550. Case 6 passes at base and pins the in-flight rule (D2).

- [ ] **Step 2: Run the new tests on the base code and watch five fail**

Run (timeout 300 s, about 3 s):

```bash
bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest tests/test_cache_keepalive.py -k SideRequestTest 2>&1 | grep -E "^(FAIL:|ERROR:|AssertionError|Ran|FAILED|OK)"'
```

Expected: `Ran 6 tests` and `FAILED (failures=5)`, with no `ERROR:` line. The five `FAIL:` lines name cases 1–5, and each is followed by the `AssertionError` below. P's handle is `341530a3c0c8`:

- case 1: `Lists differ: [['341530a3c0c8'], [], []] != [['341530a3c0c8'], ['341530a3c0c8'], ['341530a3c0c8']]`. Base ends P `session_idle` at its second due.
- case 2: `Lists differ: [['341530a3c0c8'], []] != [['341530a3c0c8'], ['341530a3c0c8']]`
- case 3: `Lists differ: [('341530a3c0c8', 'resumed', 1)] != []`
- case 4: `Lists differ: [Ping(conversation='341530a3c0c8', …)] != []`, at `self.due(5)`
- case 5: `Lists differ: [Ping(conversation='341530a3c0c8', …), Ping(…)] != []`, at `self.due(261)`

The run must show exactly these five failures, with case 6 passing. Any other result, such as a test that errors, passes or fails at a different assertion, means the tests do not pin the bug: stop and report it. Keep this output for Step 6.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/cache_keepalive.py`:

1. `Track.__init__`: change `sequence: int = 0` to `sequence: int | None = None`. Leave the rest of the signature alone. Replace the class docstring's second paragraph with:

   ```python
       A track of an untracked request has no owner and ignores every call. A side request's track
       (`no_tail_mark`) has no sequence: it holds no place in its conversation's request order, so it
       never marks a tool pending and never supersedes a ping.
   ```

2. `Keepalive.observe`: add this docstring:

   ```python
           """Classify one request and, unless it is `untracked`, register its flight.

           A thread request (any other outcome but `no_tail_mark`) is its conversation's next turn:
           it ends a pinged idle period `resumed`, stamps the last request, advances the sequence and
           clears a pending tool. A side request (`no_tail_mark`) does none of these, so it counts as
           session activity only while it is in flight (issue 501)."""
   ```

   Then replace the body from `record = self._conversation(...)` to `return track` with the following. Full code is given here because it preserves D3: `observe` alone decides the side sequence.

   ```python
               record = self._conversation(verdict.session, verdict.agent)
               sequence = None
               if verdict.outcome != "no_tail_mark":
                   if record.pings > 0:
                       self._log_end(record, "resumed", now)
                   record.last_request = now
                   record.epoch += 1
                   record.pending_since = None
                   sequence = record.epoch
               candidate = None
               if verdict.outcome == "tracked":
                   candidate = _Candidate(method, path, tuple(sent_headers), body, verdict.model, now)
               track = Track(sent_headers, self, verdict.outcome, record, sequence, now, candidate)
               record.in_flight[track] = now
               return track
   ```

3. `Keepalive._active`: replace its docstring with the following and leave its body alone:

   ```python
           """Some conversation of the session has a request in flight, a pending tool or a thread
           request newer than this candidate's last touch (D8)."""
   ```

Change nothing else in the module.

- [ ] **Step 4: Rewrite the `--keepalive` paragraph of `python/README.md`**

The paragraph is the single line that contains `prompt cache warm while it is idle`. Make exactly these six replacements in it. Each old text occurs exactly once in the file:

1. Old: ``and `tracked` is a subagent request that can be replayed. A `tracked` request whose response starts 2xx``
   New: ``and `tracked` is a subagent request that can be replayed. A `no_tail_mark` request is a *side request* (Claude Code's forks and side queries look like this), and a request with any other outcome but `untracked` is a *thread request*, its conversation's own turn. A side request counts as session activity only while it is in flight: whatever its `stop_reason`, it never clears or sets its conversation's pending tool, ends an idle period, restarts the ceiling, moves the eviction order or supersedes a ping in flight. A `tracked` request whose response starts 2xx``
2. Old: `the 65th evicts the one whose last client request is oldest` → New: `the 65th evicts the one whose last thread request is oldest`
3. Old: ``A session counts as active for a candidate when one of its conversations has a request in flight (under 60 minutes old), is pending a tool (its last 2xx response completed with `stop_reason` `tool_use`, under 60 minutes ago, and it has sent nothing since), or has sent a request since the candidate's last touch; pings never count.``
   New: ``A session counts as active for a candidate when one of its conversations has a request in flight (under 60 minutes old, side requests included), is pending a tool (the 2xx response to its newest thread request completed with `stop_reason` `tool_use`, under 60 minutes ago), or has sent a thread request since the candidate's last touch; pings never count.``
4. Old: `when 60 minutes have passed since its last client request` → New: `when 60 minutes have passed since its last thread request`
5. Old: `and a ping superseded by a newer client request while in flight changes nothing` → New: `and a ping superseded by a newer thread request of its conversation while in flight changes nothing`
6. Old: `A client request that arrives after at least one ping ends that idle period` → New: `A thread request that arrives after at least one ping ends that idle period`

The file keeps 256 lines.

- [ ] **Step 5: Verify**

1. Keepalive tests (the plan root's command, timeout 300 s, about 20 s). Expected: `Ran 56 tests` and `OK`. A failure in any of the 50 existing tests means the implementation changed a thread request's behaviour.
2. Existing tests unchanged. This gate exits 1 at the start commit, where there are no additions, and also exits 1 if any existing line was changed:

   ```bash
   bash -c 'set -e; test "$(git diff --numstat a40b1270 -- tests/test_cache_keepalive.py | cut -f2)" = 0'
   ```

3. README paragraph. This gate exits 1 at the start commit:

   ```bash
   bash -c 'set -e; p=$(grep -F "prompt cache warm while it is idle" python/README.md); if printf %s "$p" | grep -qF "client request"; then exit 1; fi; printf %s "$p" | grep -qF "*side request*"; printf %s "$p" | grep -qF "*thread request*"'
   ```

4. `just build` (timeout 3600 s), because `lib/agent-tools.nix` packages `python/`. Expected: exit 0.

- [ ] **Step 6: Write the acceptance record**

Create `.agents/artifacts/plans/2026-11-02-issue-501-keepalive-unmarked-side-requests.acceptance.md` with exactly this content, filling in each `<…>`. The sdd controller writes the `Verdict` column, so leave it as `—`:

```markdown
# Acceptance record — issue #501

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] With a main request whose tool use is pending, an unmarked side request in the same conversation leaves the pending tool state and the request counter unchanged. Pings continue past the point where the current code ends the conversation with `session_idle`. Measured by: a test added to `tests/test_cache_keepalive.py` that fails on the current code. | code | `tests/test_cache_keepalive.py::SideRequestTest::test_a_side_request_after_a_tool_use_keeps_the_tool_pending_until_its_result`, `::test_a_side_request_while_the_tool_use_still_streams_leaves_it_pending` and `::test_a_side_request_while_a_ping_is_in_flight_does_not_supersede_it`, run by `just agent-workflow-tests` | red at base `a40b1270`: <Step 2's `Ran`/`FAILED` lines and the three AC1 cases' `AssertionError` lines>; green in final verification | — | red on the base code (Step 2), green under `just agent-workflow-tests` on the final head with `failed=0` | — |
| AC2 | [evidence] Measured by: `just agent-costs --days 7 --report cache` on mbp, 7 days starting at the first `just switch` that includes this change; threshold: issue-owner "long foreground command" cache deaths ≤ 30 (127 in the 7 days to 2026-11-01). | evidence | `just agent-costs --days 7 --report cache` on mbp; threshold: issue-owner "long foreground command" cache deaths ≤ 30 | not measured — post-merge (D5) | — | post-merge, per D5: run no sooner than 7 days after the first `just switch` on mbp that includes the merge, so the whole window follows it; evidence pending, never claimed by the delivery | — |

## Demo

The issue's demo is AC1's first test: a thread request ending `tool_use`, then a side request 9 s later. The conversation is pinged at each due until the tool result ends the period `resumed` with 3 pings.
```

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/cache_keepalive.py tests/test_cache_keepalive.py python/README.md .agents/artifacts/plans/2026-11-02-issue-501-keepalive-unmarked-side-requests.acceptance.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "fix(cache-keepalive): side requests leave a pending tool alone (issue 501)" -m "<session trailer lines>"
```
