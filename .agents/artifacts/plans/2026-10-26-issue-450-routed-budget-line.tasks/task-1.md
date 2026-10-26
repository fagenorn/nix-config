# Task 1: Budget line on routed launches (AC1)

This task covers spec § Budget line on routed launches, per D1. When `route_cache_proxy` routes a launch, it also exports `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`, unless the caller already set that variable to any value, including empty. Nothing else changes: the probe is still curl and jq (Task 2 replaces it), and routing is still opt-in (Task 3 flips it).

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account` (the healthy branch of `route_cache_proxy`)
- Modify: `tests/test_claude_account_routing.py`
- Modify: `home/common/claude-code/README.md` (§ Cache proxy, two sentences)

**Interfaces:**
- Consumes the healthy branch of `route_cache_proxy` as it is at `51e2b7c9`:

```bash
    export ANTHROPIC_BASE_URL="$CACHE_PROXY_URL"
    # Before Claude Code 2.1.304 a non-first-party base URL turns tool search off.
    [ -n "${ENABLE_TOOL_SEARCH+set}" ] || export ENABLE_TOOL_SEARCH=true
  else
    unset ANTHROPIC_BASE_URL
```

- Produces, for Tasks 2–6:
  - In that branch, right after the `ENABLE_TOOL_SEARCH` line, a three-line comment whose last line ends `verified on Claude Code 2.1.310.`, then the line `[ -n "${CLAUDE_CODE_TOTAL_TOKENS_REMINDER+set}" ] || export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`. Task 4's version gate reads the version back with `sed -nE 's/.*verified on Claude Code ([0-9][0-9.]*[0-9]).*/\1/p'`.
  - The test constant `REMINDER = "CLAUDE_CODE_TOTAL_TOKENS_REMINDER"`. `LauncherCase.assert_routed` requires `padded-countdown`, and `LauncherCase.assert_direct` requires the variable to be absent.

**Invariants:**
- The variable is exported only on the line path that exports `ANTHROPIC_BASE_URL="$CACHE_PROXY_URL"`.
- A caller-set value is kept on a routed launch, whether it is `countdown` or empty (`${VAR+set}`, as for `ENABLE_TOOL_SEARCH`).
- A launch that is not routed exports nothing. That covers an unset, empty or `0` switch, a closed port, a foreign listener, a 302 carrying the marker, a caller-set endpoint and an unsubstituted copy.
- The switch check, the probe, the check order and the refusal text are unchanged.
- `home/linux/claude-local/` is not edited.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_claude_account_routing.py`:

1. After `CALLER_URL = "http://127.0.0.1:9/caller"`, add:

```python
REMINDER = "CLAUDE_CODE_TOTAL_TOKENS_REMINDER"
```

2. Replace `assert_routed` and `assert_direct` in `LauncherCase` with:

```python
    def assert_routed(self, environment, url):
        self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), url)
        self.assertEqual(environment.get("ENABLE_TOOL_SEARCH"), "true")
        self.assertEqual(environment.get(REMINDER), "padded-countdown")

    def assert_direct(self, environment):
        self.assertNotIn("ANTHROPIC_BASE_URL", environment)
        self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
        self.assertNotIn(REMINDER, environment)
```

3. In `RoutingTest.test_a_caller_set_endpoint_is_left_alone`, add `self.assertNotIn(REMINDER, environment)` after its `ENABLE_TOOL_SEARCH` assertion.

4. In `RoutingTest`, right after `test_a_caller_set_tool_search_value_is_kept`, add:

```python
    def test_a_caller_set_reminder_value_is_kept_even_when_empty(self):
        url = self.healthy_proxy()
        for value in ("countdown", ""):
            with self.subTest(value=value):
                environment = self.launch(url, {REMINDER: value})
                self.assertEqual((environment.get("ANTHROPIC_BASE_URL"), environment.get(REMINDER)),
                                 (url, value))
```

5. In `RoutingTest.test_an_unsubstituted_copy_never_routes`, add `self.assertNotIn(REMINDER, environment)` after its last line.

6. In `OptInRoutingTest.test_a_caller_set_endpoint_is_left_alone_either_way`, add `self.assertNotIn(REMINDER, environment)` inside the `subTest` block, after its `ENABLE_TOOL_SEARCH` assertion.

- [ ] **Step 2: Run the tests and watch them fail**

Run the plan's focused test command (timeout 600 s).
Expected: 16 tests, `FAILED (failures=3)`. The failures are `RoutingTest.test_a_healthy_proxy_routes_the_launch`, `RoutingTest.test_a_caller_chosen_config_dir_takes_the_early_exec_and_is_routed` and `OptInRoutingTest.test_an_opted_in_launch_routes_and_goes_direct_when_the_proxy_is_down`: each launch routes without the reminder. The new caller-set test passes at the base, because nothing touches the variable yet; it guards against an implementation that overwrites a caller's value.

- [ ] **Step 3: Write the minimal implementation**

In `route_cache_proxy`, insert these four lines right after `[ -n "${ENABLE_TOOL_SEARCH+set}" ] || export ENABLE_TOOL_SEARCH=true`, at the same indentation:

```bash
    # Claude Code sends the <total_tokens> budget line only to api.anthropic.com; without it a
    # routed turn opens with a thinking block far more often (#450). The variable is undocumented
    # (https://github.com/anthropics/claude-code/issues/98464); verified on Claude Code 2.1.310.
    [ -n "${CLAUDE_CODE_TOTAL_TOKENS_REMINDER+set}" ] || export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown
```

2.1.310 is the version the `claude-code` pin in `flake.lock` builds at `51e2b7c9`. Task 4 checks it against the built binary (D7).

- [ ] **Step 4: Document**

In `home/common/claude-code/README.md` § Cache proxy, make two exact replacements. Each old string occurs once.

1. Replace `so the launch goes direct and a dead proxy costs at most half a second.` with:

> so the launch goes direct and a dead proxy costs at most half a second. A routed launch also exports `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` unless the caller set that variable, to any value including empty: Claude Code sends its `<total_tokens>` budget line only to api.anthropic.com, and without the line a routed turn opens with a thinking block far more often (#450). The variable is undocumented (https://github.com/anthropics/claude-code/issues/98464). A launch that goes direct exports nothing; one started inside a routed session inherits the value and keeps it, which for a model with the `total_tokens_reminder` capability is the first-party default.

2. Replace ``One started inside a routed session inherits `ENABLE_TOOL_SEARCH=true`;`` with ``One started inside a routed session inherits `ENABLE_TOOL_SEARCH=true` and `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`;``

Write the README text exactly as quoted (without the `>` marker).

- [ ] **Step 5: Verify**

Run the focused test command (timeout 600 s).
Expected: `OK`, with 16 tests.

Run (timeout 60 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account
r=home/common/claude-code/README.md
test "$(grep -cF 'export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown' "$w")" -eq 1
block=$(grep -B3 -F 'export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown' "$w")
printf '%s\n' "$block" | grep -qF 'https://github.com/anthropics/claude-code/issues/98464'
printf '%s\n' "$block" | grep -qF 'verified on Claude Code 2.1.310'
grep -qF 'A routed launch also exports `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`' "$r"
grep -qF 'inherits `ENABLE_TOOL_SEARCH=true` and `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`;' "$r"
git diff --quiet 51e2b7c9 -- home/linux/claude-local
echo budget-line-ok
```

Expected: `budget-line-ok`. At the starting commit the first `test` fails, because the count is 0.

Run `just build mbp` (timeout 3600 s). Expected: exit 0. The accounts-mod build runs `claude-account status`, which never calls `route_cache_proxy`.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/README.md
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(issue-450): routed launches restore the token-budget line"
```

The message ends with the session's attribution trailer. Report DONE with the test count.
