# Task 3: Default-on routing candidate

This task covers spec § Routing default (the default-on candidate and its docs), per D3 and D4. It flips the switch's mapping. Unset, empty or `1` now probe and route, as `1` does today. `0` does what "not opted in" does today: no probe, a proxy URL inherited from a routed parent is unset, and any other caller URL is left alone. Any other value is refused with today's text. This commit is the *candidate* that Task 4 measures. If AC3 misses, Task 6 reverts exactly this commit, so it changes only the mapping, its tests and the default-on wording, and nothing in the routed path.

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account` (the `case` at the top of `route_cache_proxy`, and the function's comment)
- Modify: `tests/test_claude_account_routing.py` (the module docstring, the `RoutingTest` docstring, and `OptInRoutingTest`, which is replaced)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy)
- Modify: `home/common/claude-code/default.nix` (the comment above `cacheProxyPort` only)

**Interfaces:**
- Consumes:
  - `route_cache_proxy` as Task 2 left it, starting:

```bash
  case "${CLAUDE_CACHE_PROXY:-}" in
    1) ;;
    "" | 0)
      # Not opted in: no probe, and a proxy URL inherited from an opted-in parent goes too.
      if [ -n "$CACHE_PROXY_URL" ] && [ "${ANTHROPIC_BASE_URL:-}" = "$CACHE_PROXY_URL" ]; then
        unset ANTHROPIC_BASE_URL
      fi
      return 0
      ;;
    *) die "CLAUDE_CACHE_PROXY must be 1, 0 or unset" ;;
  esac
```

  - The test helpers `LauncherCase.healthy_proxy` (whose `self.proxy_requests` lists the paths received), `assert_routed`, `assert_direct`, `assert_not_probed`, `run_launcher`, `REMINDER` and `closed_port`.
- Produces:
  - The commit subject `feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out`. Task 6 finds the commit by it and reverts it on `opt-in`.
  - The test class `DefaultRoutingTest` (5 tests).
  - The case lines `    "" | 1) ;;` and `    0)`, which Task 4's precondition and Task 6 read.

**Invariants:**
- The closed set and the refusal text are unchanged: `claude-account: CLAUDE_CACHE_PROXY must be 1, 0 or unset` (438 D8, D13). The `case` stays the first statement of `route_cache_proxy`.
- `0` runs no probe.
- The routed path is byte-identical before and after this commit: `cache_proxy_health`, and everything in `route_cache_proxy` from `  local verdict=` to its closing `}` (D4).
- A caller-set `ANTHROPIC_BASE_URL` other than the proxy URL is untouched under every switch value.
- The flip applies on both hosts (D3). `cacheProxyPort`, the service units and `home/linux/claude-local/` are unchanged.
- `RoutingTest` keeps `switch = {"CLAUDE_CACHE_PROXY": "1"}`, a value that means the same thing in both mappings, so the revert stays clean.

- [ ] **Step 1: Write the failing tests**

Edit `tests/test_claude_account_routing.py`:

1. Change the module docstring's first line to: ``"""The `claude` launcher routes through the cache proxy while its health check answers, unless CLAUDE_CACHE_PROXY=0 (#422, #438, #450).``
2. Change the `RoutingTest` docstring to `"""Launches with CLAUDE_CACHE_PROXY=1 keep #422's health-checked routing."""`.
3. Replace the whole `OptInRoutingTest` class, from `class OptInRoutingTest(LauncherCase):` through the end of `test_any_other_switch_value_fails_before_claude_starts`, with:

```python
class DefaultRoutingTest(LauncherCase):
    """Routing is on by default (#450 D3): unset, empty or 1 probes and routes, and only 0 opts out."""

    def test_an_unset_or_empty_switch_routes_after_one_probe(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": ""}):
            with self.subTest(switch=switch):
                self.proxy_requests.clear()
                self.assert_routed(self.launch(url, switch), url)
                self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])

    def test_a_zero_switch_launches_direct_without_a_probe(self):
        self.assert_direct(self.launch(self.healthy_proxy(), {"CLAUDE_CACHE_PROXY": "0"}))
        self.assert_not_probed()

    def test_an_inherited_proxy_url_is_unset_under_zero_and_decided_again_otherwise(self):
        url = self.healthy_proxy()
        self.assert_direct(self.launch(url, {"ANTHROPIC_BASE_URL": url, "CLAUDE_CACHE_PROXY": "0"}))
        self.assert_not_probed()
        self.assert_routed(self.launch(url, {"ANTHROPIC_BASE_URL": url}), url)
        self.assertEqual(self.proxy_requests, [cache_proxy.HEALTH_PATH])
        down = "http://127.0.0.1:%d" % closed_port()
        self.assert_direct(self.launch(down, {"ANTHROPIC_BASE_URL": down}))

    def test_a_caller_set_endpoint_is_left_alone_either_way(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": "0"}):
            with self.subTest(switch=switch):
                environment = self.launch(url, {"ANTHROPIC_BASE_URL": CALLER_URL, **switch})
                self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
                self.assertNotIn("ENABLE_TOOL_SEARCH", environment)
                self.assertNotIn(REMINDER, environment)
        self.assert_not_probed()

    def test_any_other_switch_value_fails_before_claude_starts(self):
        url = self.healthy_proxy()
        for substitute in (True, False):
            with self.subTest(substitute=substitute):
                completed = self.run_launcher(url, {"CLAUDE_CACHE_PROXY": "yes"}, substitute)
                self.assertEqual((completed.returncode, completed.stdout), (1, ""))
                self.assertEqual(completed.stderr,
                                 "claude-account: CLAUDE_CACHE_PROXY must be 1, 0 or unset\n")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run the plan's focused test command (timeout 600 s).
Expected: 17 tests, `FAILED (failures=3)`: `test_an_unset_or_empty_switch_routes_after_one_probe` in both subtests (an unset or empty switch goes direct today), and `test_an_inherited_proxy_url_is_unset_under_zero_and_decided_again_otherwise` (an unset switch unsets the inherited URL today). The other `DefaultRoutingTest` cases and every `RoutingTest` case pass.

- [ ] **Step 3: Write the minimal implementation**

In `route_cache_proxy`, replace the first three lines inside the `case` (`    1) ;;`, `    "" | 0)` and the `# Not opted in: …` comment) with:

```bash
    "" | 1) ;;
    0)
      # Opted out: no probe, and a proxy URL inherited from a routed parent goes too.
```

Replace the seven-line comment above `route_cache_proxy() {` (from `# Routes this launch through the cache proxy only when CLAUDE_CACHE_PROXY=1` through `# for the refusal: stdout and stderr belong to claude.`) with:

```bash
# Routes this launch through the cache proxy while the proxy's health check
# answers, unless CLAUDE_CACHE_PROXY=0 (on by default since #450), and sends it
# direct otherwise. 0 runs no probe and unsets a base URL equal to the proxy URL,
# which a routed parent passed down; any value but unset, empty, 0 or 1 is
# refused. Otherwise a base URL the caller set to anything but the proxy is the
# caller's own endpoint and is left alone, and one equal to the proxy URL is
# decided again. Silent except for the refusal: stdout and stderr belong to claude.
```

In `home/common/claude-code/default.nix`, replace the two comment lines

```nix
  # rewritten to it, so a `claude` launched with CLAUDE_CACHE_PROXY=1 routes
  # through the proxy while it is healthy (opt-in since #438).
```

with

```nix
  # rewritten to it, so `claude` routes through the proxy while it is healthy
  # unless launched with CLAUDE_CACHE_PROXY=0 (on by default since #450).
```

- [ ] **Step 4: Document**

In `home/common/claude-code/README.md` § Cache proxy, make four exact replacements. Each old string is one line of a fenced block below and occurs once in the README; write each new string exactly as its block shows.

1. Old:

```text
`claude` reaches the Anthropic API through `cache-proxy` (`python/README.md` § `cache-proxy`) only when launched with `CLAUDE_CACHE_PROXY=1`, and only while the proxy is healthy. Routing is opt-in because the screen winner's confirmation at 1250a968 measured a Δ of 206.0 ms, over the +100 ms bound (#438, `docs/spikes/cache-proxy-ttft-gap.md`).
```

New:

```text
`claude` reaches the Anthropic API through `cache-proxy` (`python/README.md` § `cache-proxy`) while the proxy is healthy, unless launched with `CLAUDE_CACHE_PROXY=0`. Routing is on by default since #450, which re-measured the routed time-to-first-token gap that had made it opt-in in #438 (`docs/spikes/cache-proxy-ttft-gap.md`).
```

2. Old:

```text
The service starts at activation (`just switch`) and stays declared, so opting in needs no rebuild; until something answers on the port, an opted-in launch goes direct too.
```

New:

```text
The service starts at activation (`just switch`) and stays declared; until something answers on the port, a launch goes direct.
```

3. Old:

```text
Unset, empty or `0` runs no probe: it unsets an `ANTHROPIC_BASE_URL` equal to the proxy URL, inherited from an opted-in parent, and leaves any other alone. Any other value stops the launch before claude starts, with `claude-account: CLAUDE_CACHE_PROXY must be 1, 0 or unset`. With `1`, it leaves alone an `ANTHROPIC_BASE_URL` set to anything but the proxy URL, since that is the caller's own endpoint.
```

New:

```text
`0` runs no probe: it unsets an `ANTHROPIC_BASE_URL` equal to the proxy URL, inherited from a routed parent, and leaves any other alone. Any value but unset, empty, `0` or `1` stops the launch before claude starts, with `claude-account: CLAUDE_CACHE_PROXY must be 1, 0 or unset`. Unset, empty or `1` leaves alone an `ANTHROPIC_BASE_URL` set to anything but the proxy URL, since that is the caller's own endpoint.
```

4. Old:

```text
`CLAUDE_CACHE_PROXY=1 claude` routes one launch. Exporting it in the shell routes every launch, and `CLAUDE_CACHE_PROXY=0 claude` then opts one launch out.
```

New:

```text
`CLAUDE_CACHE_PROXY=0 claude` opts one launch out, which also keeps that launch's Remote Control; exporting `CLAUDE_CACHE_PROXY=0` in the shell opts every launch out.
```

The sentence `A routed session has no Remote Control, which Claude Code turns off behind a non-first-party base URL.` stays, and so do Task 1's and Task 2's sentences.

- [ ] **Step 5: Verify**

Run the focused test command (timeout 600 s).
Expected: `OK`, with 17 tests.

Run, before staging (timeout 60 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account
r=home/common/claude-code/README.md
n=home/common/claude-code/default.nix
grep -qxF '    "" | 1) ;;' "$w"
grep -qxF '    0)' "$w"
grep -qxF '    *) die "CLAUDE_CACHE_PROXY must be 1, 0 or unset" ;;' "$w"
routed() { sed -n '/^cache_proxy_health() {$/,/^}$/p; /^  local verdict=/,/^}$/p'; }
diff <(git show HEAD:"$w" | routed) <(routed < "$w")
grep -qF 'while the proxy is healthy, unless launched with `CLAUDE_CACHE_PROXY=0`. Routing is on by default since #450' "$r"
grep -qF "opts one launch out, which also keeps that launch's Remote Control" "$r"
if grep -nF 'only when launched with `CLAUDE_CACHE_PROXY=1`' "$r"; then exit 1; fi
if grep -nF 'an opted-in launch goes direct too' "$r"; then exit 1; fi
grep -qF '(on by default since #450).' "$n"
if git diff -U0 HEAD -- "$n" | grep -E '^[-+]' | grep -Ev '^(\+\+\+|---) ' | grep -Ev '^[-+][[:space:]]*(#.*)?$'; then exit 1; fi
grep -q '^class DefaultRoutingTest(LauncherCase):$' tests/test_claude_account_routing.py
if grep -q '^class OptInRoutingTest' tests/test_claude_account_routing.py; then exit 1; fi
test "$(git diff --name-only HEAD | LC_ALL=C sort | tr '\n' ' ')" = "home/common/claude-code/README.md home/common/claude-code/accounts/bin/claude-account home/common/claude-code/default.nix tests/test_claude_account_routing.py "
echo default-on-candidate-ok
```

Expected: `default-on-candidate-ok`. At the starting commit the first `grep` fails.

Run `just build mbp` (timeout 3600 s). Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/README.md home/common/claude-code/default.nix
launch-commit --repo-root <R> --run-id <I> --worker-id <W> -- -m "feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out"
```

The subject is exact, because Task 6 finds this commit by it. The message ends with the session's attribution trailer. Report DONE with the test count.
