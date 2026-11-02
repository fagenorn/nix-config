# Task 6: Keepalive ping spend

Spec § Keepalive pings, § Aggregates (*Lineage values*), § Document (`pings`), § CLI rules (the `--proxy-log` rows), § Modules (`keepalive_pings`) and § Test seams (*Fixture*, *AC (b), pings*). Rests on D5, D6, D9, D11, D12 and D13. After this task `--proxy-log PATH` reads one cache-proxy log. Each well-formed `ping` line is priced and matched to a transcript by conversation handle. A ping is then added to its counted lineage, counted as unattributed, or left out, and the document gains `pings`. This task owns AC2.

**Files:**
- Create: `python/agent_tools/keepalive_pings.py`
- Modify: `python/agent_tools/agent_owner_report.py`
- Modify: `python/agent_tools/agent_costs.py`
- Modify: `tests/owner_transcripts.py`
- Test: `tests/test_agent_owner_report.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes:
  - Task 3: the lineage-row keys `owner_ping_dollars` and `ping_dollars` (0.0) and the arm aggregate that adds them.
  - Task 4: `collect(..., windows=..., settle_days=...)`, `_select_started`'s left-out list, `StartWindow`, `run`, `assert_usage_errors`, `DAY` and `HOUR`.
  - Present at base: `cache_keepalive.conversation_handle(session, agent)`, `model_pricing.usage_cost(model, usage) -> (dollars, approximate)`, `agent_costs.parse_rfc3339_utc`, and the scan keys `"session"` and `"agent_id"` (`None` for a root transcript).
- Produces, in `agent_tools.keepalive_pings`:
  - `Ping`, a frozen dataclass: `ts: datetime` (aware UTC), `conversation: str`, `dollars: float`, `priced: bool` (the line had a `usage` object) and `approximate: bool`.
  - `PingLog`, a frozen dataclass: `log: str` (the path as given), `pings: tuple[Ping, ...]` and `skipped: int`.
  - `read_pings(path: str) -> PingLog`. It opens with `encoding="utf-8", errors="replace"` and lets `OSError` propagate.
- Produces, in `agent_owner_report`:
  - the scan key `"handle"`, which is `conversation_handle(session, agent_id)`;
  - `Lineage.members: tuple = ()`, a new last field of `(handle, is_owner)` for every transcript of the lineage's group (`is_owner` is `scan is owner_scan`), filled by `_lineage`; `_merge_trial` leaves it empty, because eval grouping refuses `--proxy-log`;
  - `collect(..., pings=None)`, taking a `PingLog` or `None`, and the footer key `"pings"`;
  - `_attribute_pings(log, counted, left_out, *, attributed_scope, unattributed_scope) -> tuple[dict, int]`;
  - `build_document` emits `"pings": footer["pings"]` between `"calibration"` and `"comparison"`.
- Produces, in `agent_costs`: the flag `--proxy-log PATH`.
- Produces, in `tests/owner_transcripts.py`: `ping_line(seconds, session, agent=None, *, read=50_000, priced=True, model="claude-opus-5-5")`, `request_line(seconds)`, `STDERR_LINE` and `ping_cost(read)` (Task 7 uses `ping_line`).

**Invariants:**
- `read_pings` handles each line as follows:
  - A line `json.loads` rejects, or whose value is not a dict, is skipped and counted, blank lines included.
  - An object whose `event` is not `"ping"` is ignored.
  - A ping object whose `ts` fails `parse_rfc3339_utc`, or whose `conversation` is not a `str`, is skipped and counted.
  - Any other ping is priced by `usage_cost(model, usage)`, where `model` is its `model` when that is a `str`, else `None`. Without a `usage` dict it costs `0.0` with `priced=False` and `approximate=False`.
- Scopes, built in `collect` (D6):
  - `attributed_scope(ts)` is `since <= ts < before` with an event window and always true otherwise.
  - `unattributed_scope(ts)` holds when `ts` lies in a start window if there are windows, else in the event window if there is one, else when `cutoff is None or ts.timestamp() >= cutoff`.
- `left_out` is `_select_started`'s left-out list in start mode and empty otherwise. In event mode a lineage none of whose owner calls start in the window is not a lineage of the report (`_lineages` drops it, as today), so its in-window pings are unattributed: the event window counts spend, not lineages, and the spec's neither-attributed-nor-unattributed rule covers only start mode's left-out lineages (PR-03). `pings=None` gives footer `"pings": None` and leaves every ping field 0.
- `pricing.approximate_calls` gains the count `_attribute_pings` returns (D12).
- `--proxy-log` is refused, exit 2 with nothing on stdout, without `--report owners` and with `--eval-results`/`--eval`. `_owners_report` reads the log before collecting. An `OSError` exits 1 through `sys.exit(f"cannot read proxy log: {error}")`.
- Lineage rows' `owner_dollars` and `total_dollars` stay calls-only (D6).

`_attribute_pings` embodies D5, D6 and D12; write it as given:

```python
def _attribute_pings(log, counted, left_out, *, attributed_scope, unattributed_scope):
    """The `pings` footer of `log` and the count of approximately priced pings it counts.

    A ping whose conversation is a member of a counted lineage adds to that lineage (its owner
    share too, for an owner transcript) when `attributed_scope` holds; one of a left-out
    lineage is dropped; any other counts as unattributed when `unattributed_scope` holds."""
    members = {handle: (lineage, owner) for lineage in counted for handle, owner in lineage.members}
    dropped = {handle for lineage in left_out for handle, _ in lineage.members}
    attributed = {"pings": 0, "dollars": 0.0, "owner_dollars": 0.0}
    unattributed = {"pings": 0, "dollars": 0.0}
    unpriced = approximate = 0
    for ping in log.pings:
        hit = members.get(ping.conversation)
        if hit is not None:
            if not attributed_scope(ping.ts):
                continue
            lineage, owner = hit
            lineage.facts["ping_dollars"] += ping.dollars
            attributed["pings"] += 1
            attributed["dollars"] += ping.dollars
            if owner:
                lineage.facts["owner_ping_dollars"] += ping.dollars
                attributed["owner_dollars"] += ping.dollars
        elif ping.conversation in dropped or not unattributed_scope(ping.ts):
            continue
        else:
            unattributed["pings"] += 1
            unattributed["dollars"] += ping.dollars
        unpriced += not ping.priced
        approximate += ping.approximate
    return ({"log": log.log, "lines": len(log.pings), "skipped_lines": log.skipped,
             "unpriced": unpriced, "attributed": attributed, "unattributed": unattributed},
            approximate)
```

- [ ] **Step 1: Write the fixture and the failing tests**

Append to `tests/owner_transcripts.py`, importing `conversation_handle` from `agent_tools.cache_keepalive` at the top:

```python
def ping_line(seconds, session, agent=None, *, read=50_000, priced=True, model="claude-opus-5-5"):
    """One `ping` line as cache-proxy logs it: LineLog's `event` and `ts`, then the keepalive's
    fields; a failed ping carries an error and no `usage`."""
    fields = {"event": "ping", "ts": at(seconds), "conversation": conversation_handle(session, agent),
              "model": model, "idle_s": 270.0, "status": 200 if priced else 529, "ttfb_ms": 80.0,
              "duration_ms": 120.0, "outcome": "complete" if priced else "upstream_error"}
    if priced:
        fields["usage"] = {"input_tokens": 3, "cache_creation_input_tokens": 0,
                           "cache_read_input_tokens": read, "output_tokens": 1,
                           "cache_creation": {"ephemeral_5m_input_tokens": 0,
                                              "ephemeral_1h_input_tokens": 0}}
    else:
        fields["error"] = "HTTP 529"
    return _line(fields)


def request_line(seconds):
    """A forwarded request's line, which the ping reader ignores."""
    return _line({"event": "request", "ts": at(seconds), "method": "POST", "path": "/v1/messages",
                  "status": 200, "upstream_conn": "new", "ttfb_ms": 90.0, "duration_ms": 900.0,
                  "bytes": 2048, "outcome": "complete"})


STDERR_LINE = "Traceback (most recent call last):\n"   # launchd appends stderr to the same log


def ping_cost(read):
    """The Opus 5.5 list price of one priced `ping_line`: 3 fresh, `read` cached, 1 output."""
    return cost(read + 3, 0, fresh=3, out=1)
```

In `tests/test_agent_owner_report.py`, import `STDERR_LINE`, `ping_cost`, `ping_line` and `request_line` from `.owner_transcripts`, and add to `OwnerReportTest`:

```python
    def test_pings_are_priced_and_attributed_or_unattributed_within_the_event_window(self):
        session = Session(self.root)
        dispatch = session.call(None, 0, context=10_000, write=10_000, ttl="1h", agent_tool=True)
        session.child("o1", tool_use_id=dispatch)
        g = session.call("o1", 10, context=30_000, write=30_000, bash=progress(3))
        session.result("o1", 11, g, gate_reply("continue"))
        work = session.call("o1", 20, context=31_000, write=1_000, agent_tool=True)
        session.child("w1", tool_use_id=work, parent="o1")
        session.call("w1", 30, context=20_000, write=20_000)
        session.write()
        log = self.root / "proxy.log"
        log.write_text("".join([
            ping_line(100, "s1", "o1", read=31_000),
            ping_line(110, "s1", "w1", read=20_000, model="claude-opus-9"),   # priced approximately
            ping_line(120, "s1", "o1", priced=False),
            ping_line(130, "s9", "x1", read=40_000),                          # no such transcript
            ping_line(5_000, "s9", "x1", read=40_000),
            ping_line(5_000, "s1", "o1", read=31_000),
            request_line(140), STDERR_LINE,
            '{"event":"ping","conversation":"0123456789ab"}\n',               # no ts
        ]), encoding="utf-8")
        owner, worker, lost = ping_cost(31_000), ping_cost(20_000), ping_cost(40_000)
        window = ("--events-since", at(0), "--events-before", at(1_000))
        for extra, attributed, unattributed in (
                (window, (3, owner + worker, owner), (1, lost)),
                ((), (4, 2 * owner + worker, 2 * owner), (2, 2 * lost))):
            with self.subTest(extra=extra):
                doc = report(self.root, "--proxy-log", str(log), *extra)
                pings = doc["pings"]
                self.assertEqual((pings["log"], pings["lines"], pings["skipped_lines"],
                                  pings["unpriced"], pings["attributed"]["pings"],
                                  pings["unattributed"]["pings"]),
                                 (str(log), 6, 2, 1, attributed[0], unattributed[0]))
                self.assertAlmostEqual(pings["attributed"]["dollars"], attributed[1], places=9)
                self.assertAlmostEqual(pings["attributed"]["owner_dollars"], attributed[2], places=9)
                self.assertAlmostEqual(pings["unattributed"]["dollars"], unattributed[1], places=9)
                self.assertEqual(doc["pricing"]["approximate_calls"], 1)
                [row] = doc["lineages"]
                self.assertAlmostEqual(row["owner_dollars"], cost(30_000, 30_000) + cost(31_000, 1_000),
                                       places=9)   # calls only
                self.assertAlmostEqual(row["owner_ping_dollars"], attributed[2], places=9)
                self.assertAlmostEqual(row["ping_dollars"], attributed[1], places=9)
                [arm] = doc["arms"]
                self.assertAlmostEqual(arm["ping_dollars"], attributed[1], places=9)
                self.assertAlmostEqual(arm["owner_dollars_per_lineage"],
                                       row["owner_dollars"] + attributed[2], places=9)
                self.assertAlmostEqual(arm["undelivered_dollars"],
                                       row["total_dollars"] + attributed[1], places=9)

    def test_a_left_out_lineage_s_pings_are_neither_attributed_nor_unattributed(self):
        s7 = Session(self.root, session="s7")
        g = s7.call(None, DAY, context=20_000, write=20_000, ttl="1h", bash=progress(3))
        s7.result(None, DAY + 5, g, gate_reply("continue"))
        s7.call(None, 6 * DAY, context=21_000, write=1_000, ttl="1h")
        s7.write()
        s9 = Session(self.root, session="s9")
        g = s9.call(None, 2 * DAY + 12 * HOUR, context=25_000, write=25_000, ttl="1h",
                    bash=progress(3, action_id="9:1:1"))
        s9.result(None, 2 * DAY + 12 * HOUR + 5, g, gate_reply("continue", issue=9))
        s9.write()
        log = self.root / "proxy.log"
        log.write_text("".join([
            ping_line(DAY + 300, "s7", read=20_000),                   # settled issue 7's root
            ping_line(6 * DAY + 300, "s7", read=21_000),               # ... after the start window
            ping_line(2 * DAY + 12 * HOUR + 300, "s9", read=25_000),   # unsettled issue 9's root
            ping_line(DAY + 600, "s0", "x1", read=40_000),             # no transcript, in the window
            ping_line(4 * DAY, "s0", "x1", read=40_000),               # no transcript, after it
        ]), encoding="utf-8")
        doc = report(self.root, "--started", "2026-10-25..2026-10-28", "--proxy-log", str(log))
        self.assertEqual([row["issue"] for row in doc["lineages"]], [7])
        self.assertEqual(doc["start_grouping"]["windows"][0]["unsettled"]["lineages"], 1)
        pings = doc["pings"]
        self.assertEqual((pings["lines"], pings["attributed"]["pings"],
                          pings["unattributed"]["pings"]), (5, 2, 1))
        # an attributed ping counts in full, even after the start window (PR-02)
        self.assertAlmostEqual(pings["attributed"]["owner_dollars"],
                               ping_cost(20_000) + ping_cost(21_000), places=9)
        [row] = doc["lineages"]
        self.assertAlmostEqual(row["owner_ping_dollars"], ping_cost(20_000) + ping_cost(21_000),
                               places=9)
        self.assertAlmostEqual(pings["unattributed"]["dollars"], ping_cost(40_000), places=9)

    def test_proxy_log_usage_errors_and_an_unreadable_log(self):
        self.assert_usage_errors(
            ["--report", "boot", "--proxy-log", "proxy.log"],
            ["--report", "owners", "--proxy-log", "proxy.log", "--eval-results", "r.jsonl",
             "--eval", "from-issue:8"])
        completed = run(self.root, "--report", "owners", "--proxy-log", str(self.root / "missing.log"))
        self.assertEqual((completed.returncode, completed.stdout), (1, ""))
        self.assertTrue(completed.stderr.startswith("cannot read proxy log: "), completed.stderr)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the Owner tests command with `-k pings -k proxy_log` (timeout 300 s). It selects the three new tests.
Expected: FAIL. Each test meets `unrecognized arguments: --proxy-log`, in `report`'s assertion or in `assert_usage_errors`'s `assertNotIn`.

- [ ] **Step 3: Implement**

Create `python/agent_tools/keepalive_pings.py` with the interfaces and the reading rules above. Its module docstring says:
- it reads the `ping` lines of one log that `cache-proxy --keepalive` writes (through agent_tools.cache_proxy.LineLog) and prices them through agent_tools.model_pricing (issue 503);
- the owner report matches them to transcripts by conversation handle;
- python/README.md (agent-costs) holds the contract.

`agent_owner_report.py`:
- import `conversation_handle` from `agent_tools.cache_keepalive`;
- add the scan's `"handle"`, `Lineage.members` (filled in `_lineage`) and `_attribute_pings` as given;
- `collect` builds the two scopes, calls `_attribute_pings` after the start selection when `pings` is given, adds the count to `pricing.approximate_calls`, and puts `"pings"` in the footer;
- `build_document` emits it;
- the module docstring gains one sentence saying that with a ping log, `collect` adds each counted lineage's keepalive pings to it and counts the rest as unattributed.

`agent_costs.py`:
- add `--proxy-log` with the help text "a cache-proxy log whose ping lines add keepalive spend (darwin: ~/Library/Logs/claude-cache-proxy.log); --report owners only";
- add its two usage rules in `main`, and the read and the exit-1 message in `_owners_report`, which passes `pings=` to `collect`;
- its module docstring's owner paragraph gains: "`--proxy-log PATH` adds the keepalive ping spend of one cache-proxy log."

- [ ] **Step 4: Verify**

Run the Owner tests command (timeout 300 s). Expected: `Ran 30 tests`, `OK`.
Run the Neighbour tests command (timeout 300 s). Expected: `Ran 48 tests`, `OK`.

- [ ] **Step 5: Update the contract**

In `python/README.md` § agent-costs:
- The **Owner report** paragraph's flag lists gain `--proxy-log` and its refusals.
- After *Start mode (issue 503).*, add *Keepalive pings (issue 503).* It states, as the code does:
  - `--proxy-log PATH` has no default and reads one log. On darwin that is `~/Library/Logs/claude-cache-proxy.log`. On anis-desktop it is a file exported with `journalctl --user -u claude-cache-proxy -o cat`.
  - The exit-1 message for an unreadable log.
  - Which lines are read, ignored and skipped.
  - The pricing.
  - The matching by `conversation_handle(session, agent id)`, where a root transcript has no agent id.
  - The attributed, unattributed and dropped rules with their scopes.
  - That an owner transcript's pings add to the owner share.
- In *Document.*, add `pings`: `null` without `--proxy-log`, else its shape with D12's meaning of `lines`, `unpriced` and the approximate count in `pricing.approximate_calls`.

Run: `rg -c 'Keepalive pings \(issue 503\)' python/README.md` — expected `1`.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/keepalive_pings.py python/agent_tools/agent_owner_report.py python/agent_tools/agent_costs.py tests/owner_transcripts.py tests/test_agent_owner_report.py python/README.md
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(agent-costs): add keepalive ping spend from the cache-proxy log (issue 503)" -m "<trailer lines>"
```
