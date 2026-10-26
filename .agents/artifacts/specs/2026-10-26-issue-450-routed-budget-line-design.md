# Cache proxy: restore the budget line on routed launches, re-measure, set the routing default — issue 450

Design for https://github.com/fagenorn/nix-config/issues/450. Base: `51e2b7c9`
(`origin/main`). Approval source: autonomous (--auto), decision ledger. A bare
"Dn" cites this spec's ledger; "438 Dn" cites the #438 design spec
(`2026-10-25-issue-438-proxy-ttft-gap-design.md`), and "the investigation" is
the 2026-10-26 report reproduced in the issue body.

## Triage

Input signals: contract_change=hit (routing default may flip), concurrency_or_persistence=no, open_design_questions=doubt (probe method), criteria_shape=hit (5 ACs, live measurement); paths: home/common/claude-code/accounts/bin/claude-account, tests/test_claude_account_routing.py, home/common/claude-code/README.md, home/common/claude-code/default.nix, docs/spikes/cache-proxy-ttft-gap.md. Verdict {"hits":["contract_change","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}. ran: full (shadow).

## Problem

Since #438, `claude` goes through the loopback cache proxy only when it is
launched with `CLAUDE_CACHE_PROXY=1`. #438's confirmation put routed median
TTFT at +206 ms over direct, against a +100 ms bound. The investigation, on
Claude Code 2.1.310, found that this number did not mean what #438 took it to
mean:

- **The proxy hop costs nothing measurable.** Over 130 pooled pairs, proxied
  minus direct was −63 ms mean (95% CI −182 to +55).
- **#438's rule could not resolve 100 ms.** Server latency follows the session
  id, and swapping it alone moves one request by about ±700 ms. Ten pairs
  leave a noise band of ±245–300 ms.
- **One effect is real.** A routed launch loses the
  `<total_tokens>N tokens left</total_tokens>` line, which Claude Code sends
  only to api.anthropic.com. Without it the model opens with a thinking block
  45–58% of the time, against 5–12% direct, and first token comes 0–580 ms
  later. `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` restores the
  identical line on the wire.
- **The wrapper's health probe** adds 27 ms to every routed launch.

The user wants four things: routed launches get the line back, the probe gets
cheaper, a measurement that can actually resolve the bound, and routing back on
by default if that measurement shows it holds. Default-on also means a launch
has no Remote Control unless it opts out. The issue author accepted that
trade-off (Scope 3).

## Solution

1. **Wrapper.** A routed launch exports the reminder (D1). The health probe
   spawns no curl or jq (D2). A default-on routing switch is committed as a
   candidate (D3). Each change comes with its routing tests and with README
   and Nix-comment wording for default-on.
2. **Measure the candidate.** On a `just build mbp` of the candidate head (the
   *measured head*, M), run three things:
   - a wire check that the line is on the routed wire (D7);
   - the probe benchmark, before against after (AC2, D5);
   - the 100-pair timed run (AC3, D6–D8).
3. **Ship one branch.** If AC3's bound holds, the candidate ships: routing is
   on by default, and `CLAUDE_CACHE_PROXY=0` opts a launch out. If it does not
   hold, or no valid run exists, the switch commit is reverted and routing
   stays opt-in, with #450's numbers as the stated reason (D4). The reminder
   and the probe ship in both branches.
4. **Record.** Append the root cause, the corrected method and the
   re-measurement to #438's evidence report without rewriting #438's own text
   (D9). Then run `just build mbp` at the final head, and CI `Nix Eval` must
   be green (AC5).

The Phase-0 questions are settled as follows: the probe is D2, the reminder's
caller-set rule is D1, and the harness is D6.

## Decisions

### Budget line on routed launches (AC1)

- **When it is exported.** When the launcher routes a launch, that is, when it
  exports the proxy URL, it also exports
  `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`. A value the caller
  already set is kept, any value including empty: this is the `${VAR+set}`
  rule `ENABLE_TOOL_SEARCH` uses.
- **When it is not.** The launcher exports nothing for a launch it does not
  route. That covers the opt-out, a failed probe, a caller-set endpoint and an
  unsubstituted copy.
- **The comment beside the export** says why the export exists: Claude Code
  sends the line only to api.anthropic.com, and without it routed turns open
  with thinking more often. It also says the variable is undocumented, links
  https://github.com/anthropics/claude-code/issues/98464, and reads
  `verified on Claude Code <V>`, where `<V>` is the version the wire check ran
  on (D7).
- **What the pinned binary says** (2.1.310):
  - The modes are `infinite`, `fixed`, `countdown` and `padded-countdown`.
  - The first-party default is `padded-countdown` for a model with the
    `total_tokens_reminder` capability, and off otherwise.
  - The env var overrides that default. A routed launch of a model without
    the capability therefore carries a line that direct would not send. This
    is accepted: the measured model's direct requests carry the line.
- **Inheritance**, as for `ENABLE_TOOL_SEARCH`:
  - A launch started inside a routed session inherits the value. If that
    launch goes direct, the inherited value looks caller-set and is kept. For
    a capable model this matches the first-party default.
  - `claude-local` started inside a routed session inherits the value too.
    That is accepted and out of scope.

### Health probe (AC2)

- **What replaces curl and jq.** The probe uses bash's own `/dev/tcp`:
  - Host and port come from the `http://<host>:<port>` URL, the only shape the
    build writes.
  - A process substitution opens the connection and sends one
    `GET /_proxy/health HTTP/1.0` with `Host` and `Connection: close`. It
    reads the status line, the headers and a `Content-Length` body.
  - The substitution prints a single verdict line, and only when the status
    is 2xx and the body contains `"service":"cache-proxy"`.
- **The deadline.** The launcher's own shell reads that line with one
  `read -t 0.5`. That single deadline covers connect, request and answer.
  - If the read times out, the launcher kills the substitution's process,
    named by `$!`, so a probe stuck in connect never outlives the decision.
  - After a verdict or EOF, the process is finishing on its own and is not
    signalled, so a recycled PID is never hit.
  - The probe's stderr is silenced.
- **What stays as it is.**
  - The order of checks: the switch is checked first (438 D13), then the
    empty-URL return.
  - A caller-set endpoint is left alone, and an inherited proxy URL is
    decided again.
  - A 2xx status is required, so a 302 that carries the marker goes direct.
  - A healthy answer exports what it exports today. Anything else unsets
    `ANTHROPIC_BASE_URL`.
  - A dead or hung proxy still costs at most 0.5 s.
  - The launcher stays silent except for the refusal.
- **What it costs.** Measured during grounding on bash 5.3, all local:
  - Today's probe pays for a curl spawn (22.6 ms median, refused connection)
    and a jq spawn (5.0 ms).
  - A sketch of this probe took 2.55 ms against the real `ProxyServer` and
    routed.
  - It went direct after 509 ms on a listener that never answers. A 302 that
    carried the marker went direct, and so did a closed port.
- **Bash version.** The probe needs bash 4.4 or later, because `$!` must name
  a process substitution. The build's `patchShebangs` pins bash 5.3, and the
  routing tests refuse to run under an older bash.
- **curl and jq stay** in the launcher for `status`, so the build's
  substitutions are unchanged.

### Routing default (AC4)

- **The default-on candidate.** The switch keeps its closed set and its
  refusal text (438 D8, D13): `CLAUDE_CACHE_PROXY` must be 1, 0 or unset.
  - Unset, empty or `1` does what `1` does today.
  - `0` does what "not opted in" does today: no probe, an inherited proxy URL
    is unset, and any other caller URL is untouched.
  - The switch commit changes only this mapping, its tests and the
    default-on wording. Nothing in the routed path changes, so reverting the
    commit is clean. The commit comes after the reminder and probe commits.
  - The flip applies on both hosts. Only mbp is measured, as Scope 2 says.
- **Opt-in.** Reverting the switch commit restores #438's mapping and tests.
- **Docs, default-on.** README § Cache proxy says that `claude` routes while
  the proxy is healthy, and that `CLAUDE_CACHE_PROXY=0 claude` opts one launch
  out, which also keeps that launch's Remote Control. The port comment in the
  claude-code Nix module says routing is on by default since #450.
- **Docs, opt-in.** The README keeps #438's opt-in text. Its reason sentence
  replaces 1250a968's Δ with #450's outcome: the estimate and the CI's upper
  end, or "no valid measurement". The Nix comment reads "opt-in; #450
  re-measured".
- **Docs, either branch.** The README describes the reminder export (D1) and
  the fork-free probe (D2). The sentence "a dead proxy costs at most half a
  second" stays true. The README and the Nix comment are the only living docs
  that state the default; `python/README.md` defers to the README.
- **Selection.** AC3's verdict alone picks the branch (D8).

### Sequence and the measured head (AC3, AC4)

1. Product commits: the reminder, the probe and the default-on candidate,
   with tests and wording. The plan places the review of the product diff
   before step 2, so that review fixes land before M is fixed.
2. **Version gate.** Build the head and run the wire check (D7) to get
   `<V>`. If the AC1 comment names another version, correct the comment, a
   comment-only change, and rebuild. That head is M.
3. At M: the probe benchmark (D5), then the timed run (D6–D8). The benchmark
   gates the run: if AC2 is missed, the probe is fixed and M rebuilt before
   any timed pair runs.
4. **Branch.**
   - Within the bound: M's product code ships.
   - Outside the bound, or no valid run: revert the switch commit and apply
     the opt-in wording. This revert is the one product change allowed after
     M, because it maps unset and empty to the unprobed direct path and
     leaves the measured routed path byte-identical.
5. Evidence and docs commits. Then `just build mbp` at the final head, and CI
   `Nix Eval`.

The measured surface is #438's: the accounts mod, the claude-code Nix module,
the `cache-proxy` module and the `claude-code` pin in `flake.lock`. Any other
change to it after M needs a new benchmark and a new timed run at the new head,
and the new run binds. A review fix and an integration merge that moves the pin
both count. Evidence and doc commits do not.

### Probe benchmark (AC2)

- **Before.** The `claude-account` text from base `51e2b7c9`, given the
  build's five substitutions (jq, git, curl, the claude binary, and the proxy
  URL, here the experiment URL) and M's shebang, inside a copy of M's built
  mod.
- **After.** A copy of M's built mod, with its proxy-URL line pointed at the
  experiment port.
- **Runs.** 200 alternating pairs per version of `claude-account run`.
  `CLAUDE_BIN` is an `env` stand-in, and a scratch `CLAUDE_CONFIG_DIR` takes
  the early exec, so no account profile is touched. The routed arm sets
  `CLAUDE_CACHE_PROXY=1` and the direct arm `0`; both values mean the same
  thing in both versions.
- **Validity.** Every routed run must print the proxy URL and every direct run
  none, or the benchmark is invalid.
- **Metric.** For each version, the median and IQR of the paired wall-time
  differences (routed − direct). AC2 is met when after's median is below
  before's and the routing tests pass. After's median is `p`, the probe term
  AC3 adds.

### Timed run (AC3)

**Rig.**

- **The experiment proxy** is M's built `cache-proxy` launcher.
  - It takes the service's arguments except the port, and `SSL_CERT_FILE` as
    the service sets it. The port is 27450, checked free first; it is never
    27183, 8160 or 4322.
  - It runs only for the benchmark and the timed run, and it is stopped
    afterwards. Afterwards nothing listens on 27450.
  - The installed service's launchd PID is the same before and after. The
    check is a read-only listing.
- **The launch** is
  `claude-account run -p --model haiku --output-format stream-json --verbose --include-partial-messages "Reply with exactly: ok"`.
  - It comes from a copy of M's built mod with the proxy URL set to
    `http://127.0.0.1:27450`.
  - The environment is a scrubbed allowlist plus `CLAUDE_ACCOUNT=p1` and the
    harness's timing instrument, set the same way in both arms.
  - The arms are `CLAUDE_CACHE_PROXY` unset (routed) and `0` (direct).
    Nothing else differs: the launcher decides every other routing variable,
    and the generated settings' `env` sets none.
- **The harness** is a scratch derivative of the investigation's `harness.py`.
  For each run it records:
  - the client's `ttft_ms` and `time_to_request_ms`, and the harness-side wall
    TTFT;
  - the type of the first content block, the exit status and the error kind;
  - the number of experiment-proxy `/v1/messages` lines inside the run's
    window.
- **Order.** One warm-up pair, validity-checked and then discarded. Then
  exactly 100 counted pairs, with the order flipping each pair. Each run is a
  fresh `claude -p`, so a fresh session.

**Rule** (fixed before any number exists).

- **Per pair:** `d = (ttft_ms routed + p) − ttft_ms direct`.
- **Estimate:** the median of `d`.
- **95% CI:** a percentile bootstrap over pairs, 10,000 resamples, with the
  seed fixed in the harness and recorded.
- **Within the bound** when the CI's upper end is ≤ +100 ms. That selects
  default-on; anything else selects opt-in.
- **The first block** is a closed set. A run's first `content_block_start` is
  `thinking` or `redacted_thinking` (thinking-first) or `text` (text-first).
  Any other type makes the pair invalid.
- **Diagnostics are recorded and never decide.** They are:
  - per-arm medians and quartiles of `ttft_ms`, and the mean of `d`;
  - the thinking-first count and rate per arm, and the thinking delay per arm
    (median `ttft_ms` of thinking-first runs minus text-first runs);
  - the paired median of harness wall TTFT, and the paired median of startup
    (wall TTFT minus `ttft_ms`) with its own bootstrap CI, so that a routed
    startup cost the rule does not count still shows;
  - proxy `ttfb_ms`.

**Validity and stops.**

- **A pair counts when** both runs exit 0 and carry `ttft_ms` and a first
  content block, the routed run has exactly one proxy `/v1/messages` line in
  its window, and the direct run has none.
- **Invalid pairs.** An invalid pair is recorded and replaced by one more pair
  at the end. An 11th invalid pair makes the run invalid. An invalid run is
  rerun once from scratch; a second invalid run selects opt-in, recorded as
  "no valid measurement".
- **Usage limit.** A run that fails on a usage limit stops the harness at
  once. The executor suspends with `blocked_on=usage_limit` and never switches
  accounts. On resume at the same M and pin, the run continues in the same file
  after one new discarded warm-up pair, and the gap is recorded. Otherwise it
  restarts at the new head.
- **No optional stopping.** The run is never extended or repeated to move the
  CI.

### Wire check

- **The instrument.** Before the timed run, one routed session goes through a
  scratch copy of the proxy module on port 27451. The only change in the copy
  is one per-request boolean: whether the body contains `<total_tokens>`,
  checked after any gzip decode. No body bytes are kept. The copy is stopped
  afterwards.
- **Present:** the version gate and the run proceed.
- **Absent:** the work stops and returns to the owner as blocked. The export
  would do nothing on this binary, and whether to ship it then is a scope
  question.

### Evidence (#438's report)

- **#438's text stays.** Its sections, numbers and whole-line markers stay
  verbatim, including `Routing default: opt-in`, which #438's acceptance
  record cites.
- **A pointer.** One line under the title points to § Issue 450 as the current
  basis for the routing default.
- **The appended `## Issue 450`** holds:
  - the root cause, summarized, with the full report in the issue;
  - the method correction. #438 used 10 pairs, the Δ of per-arm medians and
    harness-side TTFT, with one confirmation, against a noise band of
    ±245–300 ms. The rule above replaces it, and #438's numbers stand as
    recorded;
  - the conditions: date, host, M, the built store paths, `<V>`, account
    `p1`, the ports, the seed and any suspension;
  - the AC2 table;
  - the wire-check result;
  - the AC3 summary with its diagnostics;
  - a verdict with the whole-line marker
    `Issue 450 routing default: <on|opt-in>`.
- **Per-run rows** go to a sibling file, `cache-proxy-ttft-gap-450-runs.md`
  (438 D9 precedent).

## Test seams

- **Wrapper launch environment.** The existing seam (422 D15, D17, #438):
  `claude-account run` runs from a substituted source copy, the system `env`
  stands in for claude, and the real `ProxyServer` answers health. The
  `assert_routed` and `assert_direct` helpers gain the reminder.
  - **AC1.**
    - A routed launch carries `padded-countdown`.
    - A caller-set value is kept on a routed launch.
    - The variable is absent under `0`, a closed port, a caller-set endpoint
      and an unsubstituted copy.
  - **Probe.**
    - Today's fail-to-direct cases stay unchanged: a closed port, a foreign
      listener, a 302 that carries the marker, and an inherited URL with the
      proxy down.
    - The assertion that the proxy receives exactly one `HEALTH_PATH`
      request stays.
    - New: a listener that accepts and never answers must send the launch
      direct within 2 s. Without the deadline the launch would hang until the
      test timeout.
    - `setUp` refuses a bash older than 4.4.
  - **Default.** In the candidate, `DefaultRoutingTest` replaces
    `OptInRoutingTest`. Its cases:
    - unset or empty, with a healthy proxy: routed, after exactly one probe;
    - `0`: direct, with no probe;
    - an inherited proxy URL: unset under `0`, decided again when the switch
      is unset;
    - a caller-set endpoint: untouched either way;
    - a bad value: refused before claude starts.

    The opt-in revert restores `OptInRoutingTest`.
- **Installed launchers.** `tests/test_claude_code_installed.py` is unchanged.
  Under default-on, each of its launches sends one health GET to whatever
  listens on 27183. That GET is a read: it neither stops nor reconfigures the
  service, and those tests assert no routing variable.
- **Live.** The wire check, the benchmark and the timed run use scratch tools
  against the built outputs. Nothing live is committed as a test.
- **Build.** `just build mbp` and CI `Nix Eval` cover the build. `claude-local`
  stays un-routed by construction: the diff changes nothing under its module.

## Out of scope

- Proxy code changes, including restoring `thread`, the message-threads beta
  or first-party headers.
- `_CLAUDE_CODE_ASSUME_FIRST_PARTY_BASE_URL`.
- #429's prefix reorder.
- Changes to `claude-local`, including unsetting an inherited reminder.
- Remote Control behind the proxy.
- Posting on anthropics/claude-code#98464, which needs separate approval.
- Tuning `CLAUDE_CODE_TOTAL_TOKENS_REMINDER_BUDGET` or any other reminder knob.
- A committed test that times the probe. AC2 measures the cost; no test
  asserts it.
- Editing #438's recorded sections or #422's report, and re-running #438's
  screens.
- `just switch`, activation, and anything that stops or reconfigures the
  service on 27183.
- Moving the `claude-code` pin.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Routed launches export `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown` unless caller-set (the `${VAR+set}` rule), unrouted launches export nothing, the comment carries anthropics/claude-code#98464 and `verified on Claude Code <V>` from the wire check; inherited values on later direct or `claude-local` launches are accepted | Phase-0 disposition (same rule as `ENABLE_TOOL_SEARCH`); 438 D6 routed-only levers; 438 AC5; binary 2.1.310: first-party default is `padded-countdown` for capable models | Wrapper-owned unset on every unrouted launch (438 D6's E1 style): erases a user's deliberate value, and an inherited `padded-countdown` equals the first-party default for capable models |
| D2 | The probe is a bash `/dev/tcp` HTTP/1.0 GET in a process substitution: 2xx plus the marker substring, host and port from the built `http://host:port` URL, one `read -t 0.5` over connect, request and answer, the substitution killed only on a timeout (never after a verdict or EOF, so a recycled PID is never hit); bash ≥ 4.4 required | Issue Scope 1 (about 25 ms saved); grounding timings (curl 22.6 ms, jq 5.0 ms, sketch 2.55 ms, hung listener 509 ms); README's 0.5 s bound | Drop only jq (saves about 5 of the 25 ms); `/dev/tcp` without the shell-side deadline (a connect to a full backlog blocks well past 0.5 s, breaking the bound) |
| D3 | Default-on keeps the closed set and refusal: unset, empty or `1` probe and route, `0` is today's unprobed opt-out; the switch commit touches only that mapping, its tests and the wording, after the reminder and probe commits; the flip applies on both hosts, with only mbp measured | Issue Scope 3 (`CLAUDE_CACHE_PROXY=0` as the opt-out) and Scope 2 (mbp); 438 D8, D13 | Empty meaning opt-out under default-on: empty means unset everywhere else in this switch. A per-host default: configuration the issue did not ask for |
| D4 | The default-on candidate is committed before measuring, M is the reviewed candidate head, a pass ships M's product code, and a miss or no valid run reverts only the switch commit (the one product change allowed after M); the AC2 benchmark gates the timed run; #438's measured-surface rule otherwise | Caller constraint (measure the final wrapper code); 438 § Decision rule (implement, confirm at the final head, revert on a miss) | Measure the opt-in code and then flip: ships an unmeasured default path, or needs a second 100-pair run |
| D5 | AC2 is 200 alternating pairs per version of `claude-account run` with an `env` stand-in and a scratch config dir, routed `1` against direct `0`, before (base `51e2b7c9` text under M's substitutions) against after (M); the metric is the paired median increment, met when after < before; after's median is `p` | AC2; 438 D2 wrapper-copy rig | Timing the probe function alone: misses the subshell and exports a real launch pays |
| D6 | Timed rig: M's built proxy on 27450 with the service's arguments, M's built mod copy, account `p1`, `--model haiku`, the #422/#438 prompt, arms differing only in `CLAUDE_CACHE_PROXY` unset or `0`, one warm-up pair then 100 counted pairs, order flipping each pair; the service PID is checked unchanged | Issue Scope 2; caller hard constraints; 438 D2, D3; continuity with e1–e4 | The investigation's harness as is: it calls the binary directly, bypassing the wrapper code under test |
| D7 | A one-session wire check through a scratch proxy copy that records only whether the body has `<total_tokens>` runs before the timed run and sets `<V>`; an absent line stops the work and returns it to the owner | AC1 intent; the investigation's on-wire finding; the bar (verify before claiming done) | Inferring the line from the thinking-first rate alone: a behavioural signal, not proof that the line is on the wire |
| D8 | Rule: `d = (ttft_ms routed + p) − ttft_ms direct`; the median with a 10,000-resample percentile bootstrap at a fixed seed; within the bound when the upper end is ≤ +100 ms; diagnostics never decide, startup's paired CI included; the first block is a closed set (`thinking` or `redacted_thinking`, or `text`; anything else invalidates the pair); invalid pairs replaced up to 10, one rerun of an invalid run, then opt-in; a usage limit suspends with `blocked_on=usage_limit` and resumes at the same M after a new warm-up pair; never extended | AC3; the investigation's noise analysis; 438 D4 (diagnostics never decide; one rerun); the bar (truthful terminal states) | Harness wall TTFT as the metric: adds about 1.1 s of startup noise and is not the client's `ttft_ms` the issue names. Extending pairs until the CI clears: optional stopping biases the bound |
| D9 | Evidence is appended as `## Issue 450` to #438's report, with #438's text and markers verbatim plus one pointer line, a new whole-line marker `Issue 450 routing default: <on\|opt-in>`, and per-run rows in a sibling file | Issue Scope 4; the bar (point-in-time records keep their text); #422's re-measurement in place; 438 D9 | Rewriting #438's `Routing default:` marker: invalidates #438's acceptance record, which cites it |
