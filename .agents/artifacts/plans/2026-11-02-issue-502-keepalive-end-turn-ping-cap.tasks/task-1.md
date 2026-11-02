# Task 1: Cap pings after an end_turn reply

Spec § Solution, § Decisions (D1–D5), § Test seams cases 1–7, § Docs. Rests on D1–D8. After this task a conversation whose *last reply* (the `stop_reason` of the completed 2xx response to its newest thread request, D1) is `end_turn` ends `end_turn_cap` at the first due time at which its idle period already holds `END_TURN_PINGS` (2) pings. The check comes after `ceiling` and `session_idle` and before a ping is built (D3). A conversation pending a tool, or with any other last reply or none, keeps today's window. This task owns AC1 and AC2. Its red run proves the new tests fail on the base code, and it writes the acceptance record.

**Files:**
- Modify: `python/agent_tools/cache_keepalive.py`
- Test: `tests/test_cache_keepalive.py`
- Modify: `python/README.md`
- Modify: `home/common/claude-code/README.md`
- Create: `.agents/artifacts/plans/2026-11-02-issue-502-keepalive-end-turn-ping-cap.acceptance.md`

**Interfaces:**
- Consumes (present at base): in `tests/test_cache_keepalive.py`, `KeepaliveCase` (`self.clock`, `self.keepalive`, `self.upstream`; `exchange(agent, value=None, *, session=SESSION, status=200, stop_reason="end_turn", finish=True)`, which returns the track and, with `finish=False`, stops after `started`; `busy_main()`, a main conversation pending `tool_use`; `due(seconds)`; `events(event)`; `ends()`, a list of `(conversation, reason, pings)`; `handle(agent, session=SESSION)`), `SideRequestTest.pinged(seconds)`, and the module names `AGENT_P`, `document`, `pieces`, `sse`.
- Produces: `cache_keepalive.END_TURN_PINGS = 2`; `"end_turn_cap"` appended as the last member of `cache_keepalive.END_REASONS`; `_Conversation.last_reply: str | None = None`; `KeepaliveCase.pinged(seconds) -> list[str]` (moved, unchanged); `EndTurnCapTest(KeepaliveCase)` with seven tests.

**Invariants:**
- `last_reply` is written only in `observe` (set to `None` for every thread request, beside the pending-tool clear) and in `_done` (set to the track's `stop_reason` under the guard that already marks a tool pending: 2xx status, outcome `complete`, `track._sequence == record.epoch`). Only `tick` reads it. Every access runs under `self._lock` with no I/O held (#423 D2). A side track's sequence is `None`, so a side request never sets or clears it (D1).
- `pending_since` is set exactly when it is at base: under the same guard, when `stop_reason` is `tool_use`.
- `tick` checks `ceiling`, then `session_idle`, then the cap (`record.last_reply == "end_turn" and record.pings >= END_TURN_PINGS`), then builds the ping (D3). The cap ends through `_end`, so its `keepalive_end` line carries `conversation`, `reason`, `pings` and `idle_s`, resets `pings`, and clears the candidate (D4, #423 D24).
- The bodies of `_prune`, `_active`, `_apply`, `_build_ping`, `_log_end`, `_end`, `_settle`, `send` and `Track` do not change. `_prune`'s rule ignores `last_reply` (D1).

- [ ] **Step 1: Write the failing tests**

In `tests/test_cache_keepalive.py` make exactly these three changes (D6, D8):

1. Move `pinged` from `SideRequestTest` to `KeepaliveCase`. Delete these six lines and the blank line after them from `SideRequestTest`:

   ```python
       def pinged(self, seconds):
           """Advance the clock, send every ping now due, and return their conversations."""
           pings = self.due(seconds)
           for ping in pings:
               self.keepalive.send(ping)
           return [ping.conversation for ping in pings]
   ```

   Insert the same six lines, followed by one blank line, into `KeepaliveCase` immediately after its `due` method (before `def events(self, event):`).

2. Case 2 (D6). In `KeepaliveTest.test_pings_repeat_while_the_session_is_active_and_stop_at_the_ceiling`, change the line `        self.exchange(AGENT_P)` to `        self.exchange(AGENT_P, stop_reason="tool_use")`. Leave the rest of the test alone.

3. Insert this class, followed by two blank lines, immediately before the line `class FailingPingTest(KeepaliveCase):`:

```python
class EndTurnCapTest(KeepaliveCase):
    """A conversation whose last reply ended its turn (`end_turn`) ends `end_turn_cap` at the
    first due time at which its idle period holds two pings; any other last reply, or none, keeps
    the window (issue 502)."""

    def test_an_end_turn_reply_gets_two_pings_then_ends_end_turn_cap(self):
        self.busy_main()
        self.exchange(AGENT_P)
        self.assertEqual([self.pinged(270), self.pinged(270)], [[self.handle(AGENT_P)]] * 2)
        self.assertEqual(self.due(270), [])
        [end] = self.events("keepalive_end")
        self.assertEqual((end["conversation"], end["reason"], end["pings"], end["idle_s"]),
                         (self.handle(AGENT_P), "end_turn_cap", 2, 810.0))
        self.assertEqual(self.due(270), [])
        self.assertEqual((len(self.events("keepalive_end")), len(self.upstream.requests)), (1, 2))

    def test_a_reply_with_another_stop_reason_is_not_capped(self):
        self.busy_main()
        self.exchange(AGENT_P, stop_reason="max_tokens")
        self.assertEqual([self.pinged(270), self.pinged(270), self.pinged(270)],
                         [[self.handle(AGENT_P)]] * 3)
        self.assertEqual(self.ends(), [])

    def test_each_idle_period_after_an_end_turn_reply_gets_its_own_two_pings(self):
        self.busy_main()
        self.exchange(AGENT_P)
        self.assertEqual([self.pinged(270), self.pinged(270)], [[self.handle(AGENT_P)]] * 2)
        self.clock.advance(60)
        self.exchange(AGENT_P, document(note="next turn"))
        self.assertEqual([self.pinged(270), self.pinged(270), self.pinged(270)],
                         [[self.handle(AGENT_P)], [self.handle(AGENT_P)], []])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "resumed", 2),
                                       (self.handle(AGENT_P), "end_turn_cap", 2)])

    def test_a_side_request_never_lifts_the_cap(self):
        self.busy_main()
        self.exchange(AGENT_P)
        self.assertEqual(self.pinged(270), [self.handle(AGENT_P)])
        self.clock.advance(9)
        self.exchange(AGENT_P, document(tail_mark=False, note="side"), stop_reason="tool_use")
        self.assertEqual([self.pinged(261), self.pinged(270)], [[self.handle(AGENT_P)], []])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "end_turn_cap", 2)])

    def test_pings_sent_while_the_reply_streams_count_toward_the_cap(self):
        self.busy_main()
        reply = self.exchange(AGENT_P, finish=False)
        self.assertEqual([self.pinged(270), self.pinged(270), self.pinged(270)],
                         [[self.handle(AGENT_P)]] * 3)
        self.clock.advance(5)
        for piece in pieces(sse("end_turn")):
            reply.chunk(piece)
        reply.done("complete")
        self.assertEqual(self.pinged(265), [])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "end_turn_cap", 3)])

    def test_an_idle_session_ends_session_idle_before_the_cap(self):
        self.busy_main()
        self.exchange(AGENT_P)
        self.assertEqual(self.pinged(270), [self.handle(AGENT_P)])
        self.clock.advance(30)
        self.exchange(None, document(ttl="1h", note="tool result"))
        self.assertEqual([self.pinged(240), self.pinged(270)], [[self.handle(AGENT_P)], []])
        self.assertEqual(self.ends(), [(self.handle(AGENT_P), "session_idle", 2)])

    def test_a_newer_thread_request_clears_the_last_reply_even_when_it_fails(self):
        self.busy_main()
        self.exchange(AGENT_P)
        self.clock.advance(100)
        self.exchange(AGENT_P, document(note="overloaded"), status=529)
        self.assertEqual([self.pinged(170), self.pinged(270), self.pinged(270)],
                         [[self.handle(AGENT_P)]] * 3)
        self.assertEqual(self.ends(), [])
```

The clock starts at 1000.0, so P's first thread request is sent at 1000 and its dues fall at 1270, 1540 and 1810. The tests map to the spec's cases in order: case 1 (the issue's demo), case 3, case 4, case 5, case 6, case 7, and D8's case. Case 4's next turn at 1600 restarts the count, so its cap line comes at 2410. Case 6's reply completes at 1815, after three pings, so its cap comes at 2080 with 3. Case 7's main conversation stops pending at 1300, so P's second ping at 1540 is the last before `session_idle`. D8's 529 request at 1100 clears the last reply and leaves the candidate alone.

- [ ] **Step 2: Run the new tests on the base code and watch four fail**

Run (timeout 300 s, about 5 s):

```bash
bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest tests/test_cache_keepalive.py -k EndTurnCapTest -k test_pings_repeat_while 2>&1 | grep -E "^(FAIL:|ERROR:|AssertionError|Ran|FAILED|OK)"'
```

Expected: `Ran 8 tests` and `FAILED (failures=4)`, with no `ERROR:` line. The four `FAIL:` lines name these tests, each followed by the `AssertionError` below. P's handle is `341530a3c0c8`:

- `test_an_end_turn_reply_gets_two_pings_then_ends_end_turn_cap`: `Lists differ: [Ping(conversation='341530a3c0c8', method=[83 chars]h=1)] != []`
- `test_each_idle_period_after_an_end_turn_reply_gets_its_own_two_pings`: `Lists differ: [['341530a3c0c8'], ['341530a3c0c8'], ['341530a3c0c8']] != [['341530a3c0c8'], ['341530a3c0c8'], []]`
- `test_a_side_request_never_lifts_the_cap`: `Lists differ: [['341530a3c0c8'], ['341530a3c0c8']] != [['341530a3c0c8'], []]`
- `test_pings_sent_while_the_reply_streams_count_toward_the_cap`: `Lists differ: ['341530a3c0c8'] != []`

The other four pass at base: case 2, case 3, case 7 and D8's case. Any other result, such as an error, a fifth failure or a failure at a different assertion, means the tests do not pin the change: stop and report it. Keep this output for Step 6.

- [ ] **Step 3: Write the minimal implementation**

In `python/agent_tools/cache_keepalive.py`:

1. Replace `END_REASONS = ("resumed", "ceiling", "session_idle", "ping_failed", "evicted")` with `END_REASONS = ("resumed", "ceiling", "session_idle", "ping_failed", "evicted", "end_turn_cap")`. Between `WINDOW = 3600.0` and `MAX_CANDIDATES = 64`, insert (D2):

   ```python
   # An idle period whose conversation's last reply was `end_turn` ends `end_turn_cap` at the first
   # due time at which it holds this many pings. Two keep the cache about 14 minutes past the request
   # (2 x 270 s, then the 5-minute lifetime) and gave the best net saving on mbp's proxy log for
   # 2026-10-26..11-01 (issue 502 D2).
   END_TURN_PINGS = 2
   ```

2. `_Conversation`: add `last_reply: str | None = None` on the line after `pending_since: float | None = None`.

3. `Keepalive.observe`: replace the last two lines of its docstring (from `clears a pending tool.` to the closing `"""`) with:

   ```python
           clears a pending tool and the last reply. A side request (`no_tail_mark`) does none of
           these, so it counts as session activity only while it is in flight (issue 501)."""
   ```

   In the thread-request branch, add `record.last_reply = None` on the line after `record.pending_since = None`.

4. `Keepalive.tick`: add this docstring as its first line, and between the `session_idle` branch and the `else:` add the cap branch (D3, D4):

   ```python
           """The pings now due. At its due time a candidate's conversation ends `ceiling` or
           `session_idle` when their rules apply, else `end_turn_cap` when its last reply was
           `end_turn` and its idle period already holds `END_TURN_PINGS` pings or more; otherwise it
           is pinged."""
   ```

   ```python
                   elif record.last_reply == "end_turn" and record.pings >= END_TURN_PINGS:
                       self._end(record, "end_turn_cap", now)
   ```

5. `Keepalive._done`: add the docstring, and replace its final `if` statement (the one that sets `pending_since`) with the following. Full code is given because it keeps D1's single guard for both fields:

   ```python
           """End a request's flight. A completed 2xx response to its conversation's newest thread
           request sets the last reply to its `stop_reason` (`None` when the tap read none), and a
           `tool_use` one also marks a tool pending."""
   ```

   ```python
               if (track._status is not None and 200 <= track._status < 300 and outcome == "complete"
                       and track._sequence == record.epoch):
                   record.last_reply = track.stop_reason
                   if track.stop_reason == "tool_use":
                       record.pending_since = self._clock()
   ```

Change nothing else in the module.

- [ ] **Step 4: Update the two READMEs**

In `python/README.md`, the `--keepalive` paragraph is the single line that contains `prompt cache warm while it is idle`. Make exactly these three replacements in it. Each old text occurs exactly once in the file:

1. Old: ``or has sent a thread request since the candidate's last touch; pings never count.``
   New: ``or has sent a thread request since the candidate's last touch; pings never count. A conversation's *last reply* is the `stop_reason` the tap read from the 2xx response to its newest thread request once that response completed; it has none while that response streams, or when the response was not 2xx, was cut short or carried no `stop_reason` the tap could read, and a side request never sets or clears it.``
2. Old: ``with `session_idle` when the session is not active, and otherwise sends the ping.``
   New: ``with `session_idle` when the session is not active, with `end_turn_cap` when its last reply was `end_turn` and its idle period already holds at least two pings (`END_TURN_PINGS`; the pings sent since its last thread request, those sent while that reply streamed included), checked in that order, and otherwise sends the ping.``
3. Old: ``the other end reasons are `ceiling`, `session_idle`, `ping_failed` and `evicted`.``
   New: ``the other end reasons are `ceiling`, `session_idle`, `end_turn_cap`, `ping_failed` and `evicted`.``

In `home/common/claude-code/README.md`, line 107 (§ Cache proxy), replace exactly this sentence, which occurs once:

- Old: ``The accepted cost is that a subagent that has finished for good is still pinged while the rest of its session stays active, for up to 60 minutes, because the proxy cannot tell "done" from "waiting to be woken"; the `keepalive_end` lines measure it.``
- New: ``The proxy cannot tell a subagent that has finished for good from one waiting to be woken, so the accepted cost has two parts: a subagent whose last reply ended its turn (`end_turn`) stops being pinged once it has had two pings since its last thread request, about 14 minutes of cache, so one woken later pays a cache rewrite, while any other subagent, one pending a tool among them, is pinged while its session stays active, for up to 60 minutes; the `keepalive_end` lines measure both.``

`python/README.md` keeps 256 lines and `home/common/claude-code/README.md` keeps 113.

- [ ] **Step 5: Verify**

1. Focused run (Step 2's command). Expected: `Ran 8 tests` and `OK`.
2. Keepalive tests (the plan root's command, timeout 300 s, about 25 s). Expected: `Ran 63 tests` and `OK`. A failure in any existing test means the change altered behaviour outside the cap.
3. Existing test lines. Only the six moved `pinged` lines, their blank line and case 2's one line are removed. This gate exits 1 at the start commit, where nothing is removed:

   ```bash
   bash -c 'set -e; test "$(git diff --numstat 4e944cb4 -- tests/test_cache_keepalive.py | cut -f2)" = 8'
   ```

4. READMEs. This gate exits 1 at the start commit:

   ```bash
   bash -c 'set -e; p=$(grep -F "prompt cache warm while it is idle" python/README.md); printf %s "$p" | grep -qF "*last reply*"; test "$(printf %s "$p" | grep -oF "end_turn_cap" | wc -l | tr -d " ")" = 2; if grep -qF "finished for good is still pinged" home/common/claude-code/README.md; then exit 1; fi; grep -qF "stops being pinged once it has had two pings" home/common/claude-code/README.md; test "$(wc -l < python/README.md | tr -d " ")" = 256; test "$(wc -l < home/common/claude-code/README.md | tr -d " ")" = 113'
   ```

5. `just build` (timeout 3600 s), because `lib/agent-tools.nix` packages `python/`. Expected: exit 0.

- [ ] **Step 6: Write the acceptance record**

Create `.agents/artifacts/plans/2026-11-02-issue-502-keepalive-end-turn-ping-cap.acceptance.md` with exactly this content, filling in each `<…>`. The sdd controller writes the `Verdict` column, so leave it as `—`:

```markdown
# Acceptance record — issue 502

| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |
|----|-----------|------|------------------|----------|--------|------------|---------|
| AC1 | [code] A conversation whose last reply is `end_turn` receives at most the capped number of pings and then ends with its own end reason. A conversation pending on `tool_use` keeps being pinged up to the window. Measured by: tests added to `tests/test_cache_keepalive.py` that fail on the current code. | code | `tests/test_cache_keepalive.py::EndTurnCapTest::test_an_end_turn_reply_gets_two_pings_then_ends_end_turn_cap`, `::test_each_idle_period_after_an_end_turn_reply_gets_its_own_two_pings`, `::test_a_side_request_never_lifts_the_cap` and `::test_pings_sent_while_the_reply_streams_count_toward_the_cap`; the `tool_use` half is `::KeepaliveTest::test_pings_repeat_while_the_session_is_active_and_stop_at_the_ceiling`; run by `just agent-workflow-tests` | red at base `4e944cb4`: <Step 2's `Ran`/`FAILED` lines and its four `AssertionError` lines>; green in final verification | — | red on the base code (Step 2), green under `just agent-workflow-tests` on the final head with `failed=0` | — |
| AC2 | [evidence] Measured by: the keepalive ping lines in `~/Library/Logs/claude-cache-proxy.log` on mbp over the 7 days after the first `just switch` that includes this change; threshold: no conversation whose last reply was `end_turn` receives more pings than the documented cap. | evidence | the read-only `python3 -I -c` command in `2026-11-02-issue-502-keepalive-end-turn-ping-cap.md` § AC2 measurement, run on mbp over `~/Library/Logs/claude-cache-proxy.log` (D7's reading); threshold: its printed `over_cap` is `0`, i.e. every idle period whose last reply is `end_turn` has at most 2 (`END_TURN_PINGS`) pings | not measured — post-merge (D7) | — | post-merge, per D7: `START` is the `ts` of the first `listening` line written after the first `just switch` on mbp that includes the merge, `END` is `START` plus 7 days; evidence pending, never claimed by the delivery | — |

## Demo

The issue's demo is AC1's first test: a conversation whose reply ends `end_turn`, in a session kept active by the main conversation. It is pinged at 270 s and 540 s, and at 810 s it ends `end_turn_cap` with 2 pings, after which no due builds a ping.
```

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/cache_keepalive.py tests/test_cache_keepalive.py python/README.md home/common/claude-code/README.md .agents/artifacts/plans/2026-11-02-issue-502-keepalive-end-turn-ping-cap.acceptance.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "feat(cache-keepalive): cap pings after an end_turn reply (issue 502)" -m "<session trailer lines>"
```
