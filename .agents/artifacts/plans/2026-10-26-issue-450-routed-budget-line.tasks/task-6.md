# Task 6: Routing default, record and build (AC4, AC5)

This task covers spec § Routing default (selection, the opt-in branch and the docs for either branch) and § Sequence step 5, per D3, D4, D8 and D15. It reads the verdict line that Task 5 wrote. On `on`, M's product code ships unchanged, and this task checks that the code, tests and docs say default-on. On `opt-in`, it reverts exactly Task 3's commit, the one product change allowed after M, and then rewrites the reason sentence and the Nix comment for #450. Either way it builds the final head and fills acceptance rows AC4 and AC5.

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md` (rows AC4 and AC5)
- On `opt-in` only: `git revert` of Task 3's commit, which touches `home/common/claude-code/accounts/bin/claude-account`, `tests/test_claude_account_routing.py`, `home/common/claude-code/README.md` and `home/common/claude-code/default.nix`. After the revert, also modify `home/common/claude-code/README.md` (one sentence) and `home/common/claude-code/default.nix` (one comment line).

**Interfaces:**
- Consumes:
  - From the report `docs/spikes/cache-proxy-ttft-gap.md`, the whole lines `Issue 450 routing default: <on|opt-in>`, `Issue 450 measured head: <40-hex>` (M) and `Issue 450 timed run: <estimate e ms, 95% CI [lo, hi] ms, … | no valid measurement>`.
  - From `docs/spikes/cache-proxy-ttft-gap-450-runs.md`, the whole line `Timed run head: <40-hex>`.
  - Task 3's commit, whose subject is exactly `feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out`.
  - Task 2's routed path: `cache_proxy_health`, and `route_cache_proxy` from `  local verdict=` to its closing `}`.
- Produces: the shipped routing default in code, tests and docs, and rows AC4 and AC5 (Observed, Commit, Conditions). The controller writes `Verdict`.

**Invariants:**
- AC3's verdict alone picks the branch (D8).
- On `on`, nothing in the measured surface changes after M (D4).
- On `opt-in`, the routed path at the final head is byte-identical to M's. The switch maps unset and empty to the unprobed direct path again, `OptInRoutingTest` is back, and `DefaultRoutingTest` is gone. The `default.nix` change after the revert is a comment line only (D15).
- #438's sections of the report and its acceptance record are not edited.
- `home/linux/claude-local/` is unchanged since `51e2b7c9` (AC5).

- [ ] **Step 0: Branch gate**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; s=docs/spikes/cache-proxy-ttft-gap-450-runs.md
D=$(grep -Ex 'Issue 450 routing default: (on|opt-in)' "$f" | sed 's/^Issue 450 routing default: //')
test "$(printf '%s\n' "$D" | grep -c .)" -eq 1
M=$(sed -n 's/^Issue 450 measured head: //p' "$f"); test "$(printf '%s\n' "$M" | grep -c .)" -eq 1
test "$(sed -n 's/^Timed run head: //p' "$s")" = "$M"
test "$(grep -c '^Issue 450 timed run: ' "$f")" -eq 1
surface=(home/common/claude-code/accounts home/common/claude-code/default.nix python/agent_tools/cache_proxy.py)
if git diff -U0 "$M" HEAD -- "${surface[@]}" | grep -E '^[-+]' | grep -Ev '^(\+\+\+|---) ' | grep -Ev '^[-+][[:space:]]*(#.*)?$'; then echo 'measured surface changed since M: Task 4 § Re-measurement'; exit 1; fi
n() { git show "$1:flake.lock" | jq -c '.nodes["claude-code"].locked'; }; test "$(n "$M")" = "$(n HEAD)"
echo "$D $M"
```

Any failure is BLOCKED, with the output. On `on`, go to Step 1. On `opt-in`, go to Step 2, unless `grep -qxF '    "" | 0)' home/common/claude-code/accounts/bin/claude-account` already succeeds. That means a re-measurement brought this task back after an earlier revert: go straight to Step 4.

- [ ] **Step 1: On — check that the default-on candidate shipped**

Run the plan's focused test command (timeout 600 s). Expected: `OK`, with 17 tests. Then run (timeout 30 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account; r=home/common/claude-code/README.md
grep -qxF '    "" | 1) ;;' "$w"
grep -q '^class DefaultRoutingTest(LauncherCase):$' tests/test_claude_account_routing.py
grep -qF 'unless launched with `CLAUDE_CACHE_PROXY=0`. Routing is on by default since #450' "$r"
grep -qF "opts one launch out, which also keeps that launch's Remote Control" "$r"
grep -qF '(on by default since #450).' home/common/claude-code/default.nix
if grep -nF 'only when launched with `CLAUDE_CACHE_PROXY=1`' "$r"; then exit 1; fi
echo default-on-shipped
```

Expected: `default-on-shipped`. Then go to Step 5.

- [ ] **Step 2: Opt-in — revert the switch commit**

Run (timeout 120 s):

```bash
set -euo pipefail
C=$(git log --no-merges --format=%H -F --grep='feat(issue-450): route through the cache proxy by default, CLAUDE_CACHE_PROXY=0 opts out' 51e2b7c9..HEAD)
test "$(printf '%s\n' "$C" | grep -c .)" -eq 1
git revert --no-commit "$C"
git diff --cached --name-only | sort
```

Expected: exactly `home/common/claude-code/README.md`, `home/common/claude-code/accounts/bin/claude-account`, `home/common/claude-code/default.nix` and `tests/test_claude_account_routing.py`. A conflict is BLOCKED; leave the tree for the controller. Commit with `launch-commit … -- -m "revert(issue-450): routing stays opt-in (#450 re-measurement)"` and record `git rev-parse --short HEAD` as the revert commit.

- [ ] **Step 3: Opt-in — check the revert**

Run the focused test command (timeout 600 s). Expected: `OK`, with 18 tests. Then run (timeout 30 s):

```bash
set -euo pipefail
w=home/common/claude-code/accounts/bin/claude-account
M=$(sed -n 's/^Issue 450 measured head: //p' docs/spikes/cache-proxy-ttft-gap.md)
routed() { sed -n '/^cache_proxy_health() {$/,/^}$/p; /^  local verdict=/,/^}$/p'; }
diff <(git show "$M:$w" | routed) <(routed < "$w")
grep -qxF '    1) ;;' "$w"; grep -qxF '    "" | 0)' "$w"
grep -q '^class OptInRoutingTest(LauncherCase):$' tests/test_claude_account_routing.py
if grep -q '^class DefaultRoutingTest' tests/test_claude_account_routing.py; then exit 1; fi
grep -qF 'export CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown' "$w"
echo revert-clean
```

Expected: `revert-clean`.

- [ ] **Step 4: Opt-in — #450's reason in the docs**

Read the timed-run line: `T=$(sed -n 's/^Issue 450 timed run: //p' docs/spikes/cache-proxy-ttft-gap.md)`.

In `home/common/claude-code/README.md`, replace the one sentence that starts `Routing is opt-in because `, from those words through the first `).` after them, with the sentence for `T`. After Step 2 that sentence is #438's, which ends `over the +100 ms bound (#438, docs/spikes/cache-proxy-ttft-gap.md).` with the path in backticks; on a return from a re-measurement it is #450's own. `«M»` is M, short; `«e»` and `«hi»` are the estimate and the CI's upper end from `T`.

With `T` starting `estimate`:

```text
Routing is opt-in because #450's re-measurement at «M» put the paired median difference, routed with the probe minus direct, at «e» ms, with the 95% CI's upper end at «hi» ms, over the +100 ms bound (`docs/spikes/cache-proxy-ttft-gap.md` § Issue 450).
```

With `T` equal to `no valid measurement`:

```text
Routing is opt-in because #450's re-measurement at «M» gave no valid measurement (`docs/spikes/cache-proxy-ttft-gap.md` § Issue 450).
```

In `home/common/claude-code/default.nix`, the comment line above `cacheProxyPort` that ends `(opt-in since #438).` now ends `(opt-in; #450 re-measured).`. If it already reads that, leave it.

Run (timeout 30 s):

```bash
set -euo pipefail
r=home/common/claude-code/README.md; n=home/common/claude-code/default.nix
test "$(grep -o 'Routing is opt-in because ' "$r" | grep -c .)" -eq 1
grep -qF "Routing is opt-in because #450's re-measurement at " "$r"
if grep -nF "the screen winner's confirmation at 1250a968" "$r"; then exit 1; fi
grep -qF 'only when launched with `CLAUDE_CACHE_PROXY=1`' "$r"
grep -qF '(opt-in; #450 re-measured).' "$n"
if git diff -U0 HEAD -- "$n" | grep -E '^[-+]' | grep -Ev '^(\+\+\+|---) ' | grep -Ev '^[-+][[:space:]]*(#.*)?$'; then exit 1; fi
if grep -n '«' "$r" "$n"; then exit 1; fi
echo opt-in-documented
```

Expected: `opt-in-documented`. At Step 3's commit the second `grep` fails. Commit both files with `launch-commit … -- -m "docs(issue-450): opt-in routing default from #450's re-measurement"`.

- [ ] **Step 5: Row AC4**

Fill row `AC4` in `.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md`:
- On: Observed `DefaultRoutingTest (5 tests) and RoutingTest, in final verification; README § Cache proxy and the cacheProxyPort comment state default-on, with CLAUDE_CACHE_PROXY=0 as the opt-out`. Commit: M, short. Conditions: `Issue 450 routing default: on`.
- Opt-in: Observed `OptInRoutingTest (6 tests) and RoutingTest, in final verification; switch commit reverted at «revert sha»; README § Cache proxy gives #450's reason and the cacheProxyPort comment reads opt-in; #450 re-measured`. Commit: Step 4's commit, short. Conditions: `Issue 450 routing default: opt-in`.

- [ ] **Step 6: Build and row AC5**

Run (timeout 3600 s): `launch-scope exec … -- just build mbp`. Expected: exit 0. Then run (timeout 30 s): `git diff --quiet 51e2b7c9 HEAD -- home/linux/claude-local && echo claude-local-unchanged`.

Fill row `AC5`. Observed: `just build mbp: exit 0 at «short HEAD»; home/linux/claude-local unchanged since 51e2b7c9; CI Nix Eval: the PR's required check`. Commit: that short HEAD. Conditions: `host mbp; finished «date -u +%FT%TZ»`.

- [ ] **Step 7: Verify and commit**

Run (timeout 30 s):

```bash
set -euo pipefail
a=.agents/artifacts/plans/2026-10-26-issue-450-routed-budget-line.acceptance.md
test "$(grep -c '^| AC[1-5] |' "$a")" -eq 5
if grep '^| AC[1-5] |' "$a" | grep -q 'pending'; then exit 1; fi
if grep -n '«' "$a"; then exit 1; fi
if grep -nE 'sk-ant-|Bearer |oat01' "$a"; then exit 1; fi
if grep -nF "$HOME" "$a"; then exit 1; fi
git diff --quiet 51e2b7c9 HEAD -- home/linux/claude-local
echo acceptance-recorded
```

Expected: `acceptance-recorded`. At the starting commit, the `pending` check fails on rows AC4 and AC5. Commit the acceptance record with `launch-commit … -- -m "docs(issue-450): AC4 and AC5 recorded"`, then report DONE with the branch taken and the build result.
