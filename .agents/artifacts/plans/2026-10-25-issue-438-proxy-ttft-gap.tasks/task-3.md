# Task 3: Wrapper lever (winner E3, E1 or C)

This task covers spec § Pass branch: wrapper levers, per D6, with D4's measured surface. It builds the screen winner's wrapper half into `route_cache_proxy`. E3 is fine-grained tool streaming. E1, and C's wrapper half, is the first-party variable. Task 4 builds C's proxy half.

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account` (`route_cache_proxy` and its comment)
- Modify: `tests/test_claude_account_routing.py`
- Modify: `home/common/claude-code/README.md` (§ Cache proxy)

**Interfaces:**
- Consumes: the whole-line `Screen winner: <E3|G|E1|C|E2|none>` and report § Screens (E1's wire-check line naming the rows it removed) in `docs/spikes/cache-proxy-ttft-gap.md`. It also consumes the current `route_cache_proxy`:
  - an empty `CACHE_PROXY_URL` returns at once;
  - a caller-set `ANTHROPIC_BASE_URL` other than the proxy's returns;
  - a healthy probe exports the URL, plus `ENABLE_TOOL_SEARCH=true` unless the caller set it;
  - anything else unsets `ANTHROPIC_BASE_URL`.
- Produces for Task 5: the built wrapper carries `export CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1` (E3) or `export _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` (E1, C) on its routed branch.

**Invariants:**
- A lever is exported only on a launch the wrapper routes (D6).
- E3: a caller-set `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING`, of any value, is kept.
- E1/C: `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL` is `1` on every routed launch and absent on every launch the wrapper decides not to route (a failed probe, or a caller-set URL other than the proxy's). An unsubstituted copy (empty `CACHE_PROXY_URL`) changes nothing.
- The function stays silent: stdout and stderr belong to claude.
- `home/linux/claude-local/` is not edited (D6).

- [ ] **Step 0: Branch gate**

Run (timeout 30 s): `W=$(grep -Ex 'Screen winner: (E3|G|E1|C|E2|none)' docs/spikes/cache-proxy-ttft-gap.md | sed 's/^Screen winner: //'); test "$(printf '%s\n' "$W" | grep -c .)" -eq 1 && echo "$W"`
- If it prints `G`, `E2` or `none`, report DONE with `skipped: Screen winner is <W>`. Commit nothing.
- If the check fails, report BLOCKED.
- Otherwise do the E3 steps when `W` is `E3`, and the E1 steps when `W` is `E1` or `C`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_claude_account_routing.py`, add the variant's variable to the `SCRUBBED` tuple, add its constant after `CALLER_URL`, and add its tests to `RoutingTest`. Also add `self.assertNotIn(<constant>, environment)` as the last line of `assert_direct`.

E3:

```python
FGTS = "CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING"

    def test_a_routed_launch_turns_fine_grained_tool_streaming_on(self):
        url = self.healthy_proxy()
        environment = self.launch(url)
        self.assert_routed(environment, url)
        self.assertEqual(environment.get(FGTS), "1")

    def test_a_caller_set_fine_grained_streaming_value_is_kept(self):
        url = self.healthy_proxy()
        environment = self.launch(url, {FGTS: "0"})
        self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get(FGTS)), (url, "0"))

    def test_a_caller_set_endpoint_gets_no_fine_grained_streaming(self):
        environment = self.launch(self.healthy_proxy(), {"ANTHROPIC_BASE_URL": CALLER_URL})
        self.assertNotIn(FGTS, environment)
```

E1 (also for C):

```python
FIRST_PARTY = "_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL"

    def test_a_routed_launch_marks_the_proxy_first_party(self):
        url = self.healthy_proxy()
        environment = self.launch(url, {FIRST_PARTY: "0"})
        self.assert_routed(environment, url)
        self.assertEqual(environment.get(FIRST_PARTY), "1")

    def test_an_inherited_first_party_mark_is_dropped_when_the_launch_goes_direct(self):
        self.assert_direct(self.launch("http://127.0.0.1:%d" % closed_port(), {FIRST_PARTY: "1"}))

    def test_an_inherited_first_party_mark_is_dropped_for_a_caller_set_endpoint(self):
        environment = self.launch(self.healthy_proxy(), {"ANTHROPIC_BASE_URL": CALLER_URL, FIRST_PARTY: "1"})
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
        self.assertNotIn(FIRST_PARTY, environment)

    def test_an_unsubstituted_copy_leaves_the_first_party_mark_alone(self):
        environment = self.launch(self.healthy_proxy(), {FIRST_PARTY: "1"}, substitute=False)
        self.assertEqual(environment.get(FIRST_PARTY), "1")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py 2>&1 | tail -15`
Expected for E3: FAIL in `test_a_routed_launch_turns_fine_grained_tool_streaming_on` (`None != '1'`); the other two new tests pass. Expected for E1: FAIL in `test_a_routed_launch_marks_the_proxy_first_party`, `test_an_inherited_first_party_mark_is_dropped_when_the_launch_goes_direct` and `test_an_inherited_first_party_mark_is_dropped_for_a_caller_set_endpoint`.

- [ ] **Step 3: Write the minimal implementation**

E3: in the routed branch of `route_cache_proxy`, after the `ENABLE_TOOL_SEARCH` line, add:

```bash
    # Claude Code turns fine-grained tool streaming off behind a non-first-party base URL;
    # turning it back on is the lever docs/spikes/cache-proxy-ttft-gap.md screened in (#438).
    [ -n "${CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING+set}" ] || export CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1
```

E1/C:
1. The caller-set early return becomes `unset _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL; return 0`.
2. The `else` branch becomes `unset ANTHROPIC_BASE_URL _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`.
3. The routed branch, after the `ENABLE_TOOL_SEARCH` line, gains the AC5 comment and the export:

```bash
    # Undocumented (https://github.com/anthropics/claude-code/issues/98464),
    # verified on Claude Code 2.1.302: it marks this base URL first-party, which restores
    # «fill: the rows E1's wire check removed, from docs/spikes/cache-proxy-ttft-gap.md § Screens» behind the proxy (#438).
    export _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1
```

4. The function's header comment gains one sentence: `The first-party variable belongs to this function: a routed launch exports it and every other decided launch unsets it, so a caller's own endpoint is never marked first-party.`

- [ ] **Step 4: Document**

In `home/common/claude-code/README.md` § Cache proxy, add a sentence after the one that ends with the words `a dead proxy costs at most half a second.`:
- E3: "A routed launch also exports `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1` unless the caller set it, because Claude Code turns fine-grained tool streaming off behind a non-first-party base URL (`docs/spikes/cache-proxy-ttft-gap.md`)."
- E1/C: "A routed launch also exports the undocumented `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1` (anthropics/claude-code#98464, verified on 2.1.302), which restores «fill: the same rows as the comment» (`docs/spikes/cache-proxy-ttft-gap.md`). Every launch the wrapper decides not to route unsets it, so a caller's own endpoint is never marked first-party."

Then replace the paragraph's last sentence, the one that begins with the words `One started inside a routed session inherits`:
- E3 replacement: "One started inside a routed session inherits `ENABLE_TOOL_SEARCH=true` and `CLAUDE_CODE_ENABLE_FINE_GRAINED_TOOL_STREAMING=1`; from 2.1.304 on, tool search is the default behind any gateway regardless."
- E1/C replacement: "One started inside a routed session inherits `ENABLE_TOOL_SEARCH=true` and `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1`, so it treats the NInfer endpoint as first-party too; from 2.1.304 on, tool search is the default behind any gateway regardless."

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py 2>&1 | tail -4`
Expected: `OK`, with every test passing, the existing ones included.

Run (timeout 60 s): `if grep -rn '«fill' home/common/claude-code/accounts/bin/claude-account home/common/claude-code/README.md; then exit 1; fi; git diff --quiet 3f4c5072 -- home/linux/claude-local && echo clean`
Expected: `clean`. For E1/C also run: `grep -B3 'export _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1' home/common/claude-code/accounts/bin/claude-account | grep -c -e 'issues/98464' -e 'verified on Claude Code 2.1.302'`. Expected: `2`.

Run (timeout 3600 s): `just build mbp`
Expected: exit 0. The accounts-mod build runs `claude-account status`.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/README.md
git commit -m "feat(issue-438): routed launches export the <E3|E1> lever"
```

Use the variable's short name in the subject. Report DONE with the variant you built.
