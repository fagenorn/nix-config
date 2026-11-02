# Task 6: Opt-in routing switch (AC3)

This task covers spec § Opt-in branch, per D8, D13 and D15. Unless the confirmation passed, `claude` stops routing by default: only `CLAUDE_CACHE_PROXY=1` probes and routes. The service stays declared. This task also fills acceptance row `AC3` on both branches.

**Files:**
- Modify: `home/common/claude-code/accounts/bin/claude-account` (`route_cache_proxy` and its comment)
- Modify: `tests/test_claude_account_routing.py`
- Modify: `home/common/claude-code/default.nix` (the comment above `cacheProxyPort` only)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy)
- Modify: `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` (row `AC3`)

**Interfaces:**
- Consumes:
  - the report's whole-line `Confirmation: <passed|failed|invalid|smoke-failed|deadline-skipped|not-run>`, and its § Screens and § Confirmation numbers;
  - `route_cache_proxy` as it is at the base, which Task 5's revert restores when a winner had landed;
  - `die()` in `claude-account`, which prints `claude-account: <msg>` to stderr and exits 1.
- Produces the `CLAUDE_CACHE_PROXY` closed set for Task 7's README check and for users:
  - `1` keeps #422's routing;
  - unset, empty or `0` means no probe, an `ANTHROPIC_BASE_URL` equal to the proxy URL is unset, and any other URL is left alone;
  - any other value dies before claude starts.

**Invariants:**
- No health probe runs unless `CLAUDE_CACHE_PROXY=1`.
- The closed-set check is the first statement of `route_cache_proxy`, before the empty-`CACHE_PROXY_URL` return (D13).
- A caller-set `ANTHROPIC_BASE_URL` other than the proxy URL is untouched under every switch value.
- `launchd.agents.claude-cache-proxy`, `systemd.user.services.claude-cache-proxy` and `cacheProxyPort` are unchanged (D8).
- `home/linux/claude-local/` is not edited.

- [ ] **Step 0: Branch gate**

Run (timeout 30 s): `C=$(grep -Ex 'Confirmation: (passed|failed|invalid|smoke-failed|deadline-skipped|not-run)' docs/spikes/cache-proxy-ttft-gap.md | sed 's/^Confirmation: //'); test "$(printf '%s\n' "$C" | grep -c .)" -eq 1 && echo "$C"`
- If the check fails, report BLOCKED.
- On `passed`: fill row `AC3` with Observed `not triggered: Confirmation: passed (AC2 met at the final head)`, Commit `git rev-parse --short HEAD` and Conditions `—`. Run the credential scans from Global Constraints, commit only the acceptance record (`docs(issue-438): AC3 not triggered`) and report DONE.
- Otherwise, also confirm that the revert left no lever behind (timeout 30 s): `if grep -nE 'FINE_GRAINED_TOOL_STREAMING|ASSUME_FIRST_PARTY' home/common/claude-code/accounts/bin/claude-account; then exit 1; fi`

- [ ] **Step 1: Write the failing tests**

Restructure `tests/test_claude_account_routing.py`:

1. Add `"CLAUDE_CACHE_PROXY"` to `SCRUBBED`. Change the module docstring's first line to: `The `claude` launcher routes through the cache proxy only when CLAUDE_CACHE_PROXY=1 and its health check answers (#422, #438).`
2. Rename `class RoutingTest(unittest.TestCase)` to `class LauncherCase(unittest.TestCase)` and keep its helpers (`setUp`, `serve`, `healthy_proxy`, `foreign_listener`, `redirecting_listener`, `assert_routed`, `assert_direct`). Add `switch = {}` as a class attribute, and replace `launch` with these two methods:

```python
    switch = {}  # the CLAUDE_CACHE_PROXY setting every launch of the class starts from

    def run_launcher(self, proxy_url, env=None, substitute=True):
        """`claude-account run` from a fresh copy of the mod, as a finished process."""
        copy = Path(tempfile.mkdtemp(dir=self.root)) / "accounts"
        shutil.copytree(ACCOUNTS, copy)
        script = copy / "bin" / "claude-account"
        text = script.read_text()
        self.assertEqual(text.count(PLACEHOLDER), 1)
        if substitute:
            script.write_text(text.replace(PLACEHOLDER, PLACEHOLDER + proxy_url))
        home, work = self.root / "home", self.root / "work"
        home.mkdir(exist_ok=True)
        work.mkdir(exist_ok=True)
        child = {key: value for key, value in os.environ.items() if key not in SCRUBBED}
        child.update(HOME=str(home), CLAUDE_ACCOUNTS_DIR=str(self.root / "accounts-state"),
                     CLAUDE_BIN=shutil.which("env"), **{**self.switch, **(env or {})})
        return subprocess.run([shutil.which("bash"), str(script), "run"], cwd=work, env=child,
                              capture_output=True, text=True, timeout=TIMEOUT, check=False)

    def launch(self, proxy_url, env=None, substitute=True):
        """The environment the stand-in claude printed; the launch must succeed silently."""
        completed = self.run_launcher(proxy_url, env, substitute)
        self.assertEqual((completed.returncode, completed.stderr), (0, ""))
        return dict(line.split("=", 1) for line in completed.stdout.splitlines() if "=" in line)
```

3. Move the nine existing `test_*` methods, unchanged, into:

```python
class RoutingTest(LauncherCase):
    """Opted-in launches keep #422's health-checked routing."""

    switch = {"CLAUDE_CACHE_PROXY": "1"}
```

4. Add:

```python
class OptInRoutingTest(LauncherCase):
    """Routing is opt-in (#438 D8): only CLAUDE_CACHE_PROXY=1 probes and routes."""

    def test_an_unset_switch_launches_direct_with_a_healthy_proxy(self):
        self.assert_direct(self.launch(self.healthy_proxy()))

    def test_an_empty_or_zero_switch_launches_direct_with_a_healthy_proxy(self):
        url = self.healthy_proxy()
        for value in ("", "0"):
            with self.subTest(value=value):
                self.assert_direct(self.launch(url, {"CLAUDE_CACHE_PROXY": value}))

    def test_an_opted_in_launch_routes_and_goes_direct_when_the_proxy_is_down(self):
        url = self.healthy_proxy()
        self.assert_routed(self.launch(url, {"CLAUDE_CACHE_PROXY": "1"}), url)
        self.assert_direct(self.launch("http://127.0.0.1:%d" % closed_port(), {"CLAUDE_CACHE_PROXY": "1"}))

    def test_an_inherited_proxy_url_is_unset_when_not_opted_in(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": "0"}):
            with self.subTest(switch=switch):
                self.assert_direct(self.launch(url, {"ANTHROPIC_BASE_URL": url, **switch}))

    def test_a_caller_set_endpoint_is_left_alone_either_way(self):
        url = self.healthy_proxy()
        for switch in ({}, {"CLAUDE_CACHE_PROXY": "1"}):
            with self.subTest(switch=switch):
                environment = self.launch(url, {"ANTHROPIC_BASE_URL": CALLER_URL, **switch})
                self.assertEqual(environment.get("ANTHROPIC_BASE_URL"), CALLER_URL)
                self.assertNotIn("ENABLE_TOOL_SEARCH", environment)

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

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py 2>&1 | tail -20`
Expected: every `RoutingTest` test passes. These `OptInRoutingTest` tests fail: `test_an_unset_switch_launches_direct_with_a_healthy_proxy`, `test_an_empty_or_zero_switch_…`, `test_an_inherited_proxy_url_is_unset_when_not_opted_in` (the proxy is healthy, so they route today) and `test_any_other_switch_value_fails_before_claude_starts` (exit 0).

- [ ] **Step 3: Write the minimal implementation**

Make this the start of `route_cache_proxy`, before `[ -n "$CACHE_PROXY_URL" ] || return 0`:

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

Replace the function's comment with: `Routes this launch through the cache proxy only when CLAUDE_CACHE_PROXY=1 (#438) and the proxy's health check answers, and sends it direct otherwise. Unset, empty or 0 runs no probe and unsets a base URL equal to the proxy URL, which a routed parent passed down; any other value is refused. With 1, a base URL the caller set to anything but the proxy is the caller's own endpoint and is left alone, and one equal to the proxy URL is decided again. Silent except for the refusal: stdout and stderr belong to claude.`

In `home/common/claude-code/default.nix`, the comment above `cacheProxyPort` ends: `rewritten to it, so a `claude` launched with CLAUDE_CACHE_PROXY=1 routes` / `through the proxy while it is healthy (opt-in since #438).`

- [ ] **Step 4: Document**

In `home/common/claude-code/README.md` § Cache proxy:

1. **First sentence.** Rewrite the paragraph's first sentence: "`claude` reaches the Anthropic API through `cache-proxy` (`python/README.md` § `cache-proxy`) only when launched with `CLAUDE_CACHE_PROXY=1`, and only while the proxy is healthy. Routing is opt-in because «fill: the clause for the `Confirmation:` state, below» (#438, `docs/spikes/cache-proxy-ttft-gap.md`)." The clause per state (D15), with numbers from report § Confirmation or § Screens:
   - `failed`: "the screen winner's confirmation at <measured head, short> measured a Δ of <Δ> ms, over the +100 ms bound";
   - `smoke-failed`: "the screen winner's confirmation met the +100 ms bound (Δ <Δ> ms) but the tool-use smoke run failed";
   - `invalid`: "no valid confirmation run could be made at <head, short>";
   - `deadline-skipped`: "the confirmation did not run before the attempt deadline";
   - `not-run`: "no candidate passed its screen against the +100 ms bound (smallest valid screened Δ <Δ> ms)", or, when no screen gave a valid timed run, "no candidate passed its screen, and none gave a valid timed run".
2. **Service sentence.** Replace the sentence that begins with the words `The service starts at activation` with: "The service starts at activation (`just switch`) and stays declared, so opting in needs no rebuild; until something answers on the port, an opted-in launch goes direct too."
3. **Second paragraph's opening.** In the second paragraph, replace the words from `` `claude-account run` leaves alone `` up to `since that is the caller's own endpoint.` with: "`claude-account run` reads `CLAUDE_CACHE_PROXY`. Unset, empty or `0` runs no probe: it unsets an `ANTHROPIC_BASE_URL` equal to the proxy URL, inherited from an opted-in parent, and leaves any other alone. Any other value stops the launch before claude starts, with `claude-account: CLAUDE_CACHE_PROXY must be 1, 0 or unset`. With `1`, it leaves alone an `ANTHROPIC_BASE_URL` set to anything but the proxy URL, since that is the caller's own endpoint."
4. **One-launch sentence.** Replace the sentence `` `ANTHROPIC_BASE_URL=https://api.anthropic.com claude` goes direct for one launch. `` with: "`CLAUDE_CACHE_PROXY=1 claude` routes one launch. Exporting it in the shell routes every launch, and `CLAUDE_CACHE_PROXY=0 claude` then opts one launch out."

Fill row `AC3`:
- Observed: `OptInRoutingTest (6 tests) and RoutingTest under the switch, in final verification; routing opt-in since <short sha>`.
- Commit: that sha.
- Conditions: `Confirmation: <state>`.

- [ ] **Step 5: Verify**

Run (timeout 600 s): `env PYTHONPATH="$PWD/python" python3 -m unittest -v tests/test_claude_account_routing.py 2>&1 | tail -4`
Expected: `OK`, with 15 tests.

Run (timeout 60 s):

```bash
set -euo pipefail
files=(home/common/claude-code/accounts/bin/claude-account home/common/claude-code/README.md home/common/claude-code/default.nix)
if grep -n '«fill' "${files[@]}"; then exit 1; fi
grep -q 'CLAUDE_CACHE_PROXY=1 claude' home/common/claude-code/README.md
if grep -n 'while the proxy is healthy\. It forwards' home/common/claude-code/README.md; then exit 1; fi
grep -q 'CLAUDE_CACHE_PROXY=1' home/common/claude-code/default.nix
git diff --quiet "$(git merge-base HEAD origin/main)" -- home/linux/claude-local
a=.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
if grep '^| AC3 |' "$a" | grep -q 'pending Task 6'; then exit 1; fi
echo opt-in-documented
```

Expected: `opt-in-documented`.

Run (timeout 3600 s): `just build mbp`. Expected: exit 0. The accounts-mod build runs `claude-account status`, which never calls `route_cache_proxy`.

- [ ] **Step 6: Commit**

```bash
git add home/common/claude-code/accounts/bin/claude-account tests/test_claude_account_routing.py home/common/claude-code/default.nix home/common/claude-code/README.md .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
git commit -m "feat(issue-438): cache-proxy routing is opt-in with CLAUDE_CACHE_PROXY=1"
```

Report DONE with the branch taken.
