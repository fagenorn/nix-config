# Task 7: Verdict, record and build

This task covers spec § Evidence, § Pass branch (routing default) and § Decision rule (resolution), per D4, D6, D9, D14, D15 and the issue's AC4 and AC5. It writes the report's verdict with its two acceptance markers. On the pass branch it also names the shipped lever in README § Cache proxy. It runs the mbp build and fills acceptance rows `AC4` and `AC5`. No measured-surface file changes.

**Files:**
- Modify: `docs/spikes/cache-proxy-ttft-gap.md` (append `## Verdict`)
- Modify: `home/common/claude-code/README.md` (§ Cache proxy, pass branch only)
- Modify: `.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md` (rows `AC4`, `AC5`)

**Interfaces:**
- Consumes:
  - the report's whole-line `Screen winner:` (W) and `Confirmation:` (C), with § Screens and § Confirmation numbers;
  - Task 3's AC5 comment (E1, C) or Task 4's (E2);
  - Task 6's refusal message `CLAUDE_CACHE_PROXY must be 1, 0 or unset` in `claude-account` (opt-in branch).
- Produces the whole-line markers `Shipped lever: <E3|G|E1|C|E2|none>` and `Routing default: <on|opt-in>` (D9).

**Invariants:**
- `Shipped lever` is W when C is `passed`, and `none` otherwise. `Routing default` is `on` exactly when C is `passed`.
- The product agrees with the markers: on `opt-in`, `claude-account` carries Task 6's refusal and no lever export; on `on`, it carries no refusal.
- Nothing under the measured surface changes (D4). `home/linux/claude-local/` is unchanged since `git merge-base HEAD origin/main` (AC4, D14).

- [ ] **Step 1: Read the branch**

Run (timeout 30 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; k=home/common/claude-code/accounts/bin/claude-account
W=$(grep -Ex 'Screen winner: (E3|G|E1|C|E2|none)' "$f" | sed 's/^Screen winner: //')
C=$(grep -Ex 'Confirmation: (passed|failed|invalid|smoke-failed|deadline-skipped|not-run)' "$f" | sed 's/^Confirmation: //')
test "$(printf '%s\n' "$W" | grep -c .)" -eq 1 && test "$(printf '%s\n' "$C" | grep -c .)" -eq 1
if grep -Eq '^(Shipped lever|Routing default): ' "$f"; then exit 1; fi
if [ "$C" = passed ]; then
  if grep -q 'CLAUDE_CACHE_PROXY must be 1, 0 or unset' "$k"; then exit 1; fi
  echo "lever=$W default=on"
else
  grep -q 'CLAUDE_CACHE_PROXY must be 1, 0 or unset' "$k"
  if grep -nE 'FINE_GRAINED_TOOL_STREAMING|ASSUME_FIRST_PARTY' "$k"; then exit 1; fi
  echo "lever=none default=opt-in"
fi
```

Expected: one `lever=… default=…` line. Any failure is BLOCKED: an earlier task did not land its branch.

- [ ] **Step 2: Write the verdict**

Append `## Verdict` to the report, containing these parts in order:

1. **The markers.** The line `Shipped lever: <lever>`, then the line `Routing default: <default>`, both as Step 1 printed them.
2. **Reason (pass).** "<W> passed its screen (Δ «fill: § Screens Δ» ms) and its confirmation at «fill: confirm head» (Δ «fill: § Confirmation Δ» ms against the +100 ms bound), and the tool-use smoke run passed, so routing stays on by default with this lever (AC2)."
3. **Reason (opt-in).** "No lever shipped: «fill: the same state clause as README § Cache proxy (Task 6 Step 4, D15)», so `claude` routes only with `CLAUDE_CACHE_PROXY=1` (AC3). The measurements are § Screens and § Confirmation above."
4. **AC5.** For E1 or C: "This relies on the undocumented `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL` (https://github.com/anthropics/claude-code/issues/98464); the export in `claude-account` carries that link and the version it was verified on, <V> (AC5)." For E2: "This relies on the undocumented semantics of «fill: the `FIRST_PARTY_HEADERS` names» (https://github.com/anthropics/claude-code/issues/98464), commented in `cache_proxy.py` with the version it was verified on, <V> (AC5). Its known cost: the proxy cannot tell query sources apart, so it sends these headers on auxiliary queries, where the client sends none, and the client's own `v2p` fallback after a 5xx is lost." Otherwise: "AC5: not applicable: no undocumented variable or header shipped."
5. **The rule's limits** (spec § Decision rule), verbatim:
   - Run 2 of #422 gave Δ = +221.5 ms but a median within-pair difference of +80 ms, and the per-arm interquartile ranges spanned about 0.45–1.0 s.
   - One n = 10 run cannot separate a lever's effect from noise at 100 ms.
   - With the run count capped and one confirmation, a lever that does nothing must pass twice by chance to ship, and a lever that works can still fail its confirmation.
   - AC2's bound is the issue author's, and it stays the verdict.

- [ ] **Step 3: README (pass branch only)**

When `Routing default: on`, insert this sentence in `home/common/claude-code/README.md` § Cache proxy, right after the first sentence, which ends with the words `while the proxy is healthy.`:

"Routed launches «fill: for E3 or E1, 'export the lever named below'; for G or E2, 'have their large request bodies gzipped by the proxy'; for C, both», which closed the routed time-to-first-token gap measured in `docs/spikes/cache-proxy-ttft-gap.md` (#438)."

On the opt-in branch, Task 6 already links the evidence, and this step changes nothing.

- [ ] **Step 4: AC4 and AC5**

Run (timeout 3600 s): `just build mbp`, then (timeout 30 s) `git diff --quiet "$(git merge-base HEAD origin/main)" HEAD -- home/linux/claude-local && git rev-parse --short HEAD`.

Fill row `AC4`:
- Observed: `just build mbp: exit 0; home/linux/claude-local: unchanged since the merge base with origin/main; CI Nix Eval: the PR's required check`.
- Commit: that sha.
- Conditions: host mbp, with the finish time.

Then run the AC5 gate for the shipped lever (timeout 30 s), with `$V` set as in the plan root; each string is checked on its own:
- **E1 and C:** `c=$(grep -B3 'export _CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL=1' home/common/claude-code/accounts/bin/claude-account); grep -qF 'https://github.com/anthropics/claude-code/issues/98464' <<<"$c" && grep -qF "verified on Claude Code $V" <<<"$c" && echo ac5-ok` prints `ac5-ok`.
- **E2:** the same checks on `c=$(grep -B3 '^FIRST_PARTY_HEADERS' python/agent_tools/cache_proxy.py)` print `ac5-ok`.

Fill row `AC5`:
- Observed: the gate's command and output, or `not applicable: no undocumented variable or header shipped`.
- Commit: the sha.
- Conditions: `Shipped lever: <lever>`.

- [ ] **Step 5: Verify**

Run (timeout 60 s):

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-ttft-gap.md; a=.agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
test "$(grep -Ec '^Shipped lever: (E3|G|E1|C|E2|none)$' "$f")" -eq 1
test "$(grep -Ec '^Routing default: (on|opt-in)$' "$f")" -eq 1
C=$(sed -n 's/^Confirmation: //p' "$f"); W=$(sed -n 's/^Screen winner: //p' "$f")
L=$(sed -n 's/^Shipped lever: //p' "$f"); D=$(sed -n 's/^Routing default: //p' "$f")
if [ "$C" = passed ]; then test "$L/$D" = "$W/on"; else test "$L/$D" = "none/opt-in"; fi
if grep -n 'pending Task' "$a"; then exit 1; fi
test "$(grep -c '^| AC[1-5] |' "$a")" -eq 5
if grep -rn '«fill' "$f" home/common/claude-code/README.md; then exit 1; fi
if grep -nE 'sk-ant-|Bearer |oat01' "$f" "$a"; then exit 1; fi
if grep -nF "$HOME" "$f" "$a"; then exit 1; fi
git diff --quiet "$(git merge-base HEAD origin/main)" HEAD -- home/linux/claude-local
echo verdict-recorded
```

Expected: `verdict-recorded`. At the starting commit the first `grep` fails, because there are no markers yet.

- [ ] **Step 6: Commit**

```bash
git add docs/spikes/cache-proxy-ttft-gap.md home/common/claude-code/README.md .agents/artifacts/plans/2026-10-25-issue-438-proxy-ttft-gap.acceptance.md
git commit -m "docs(issue-438): verdict, routing default and acceptance rows"
```

Report DONE with both markers.
