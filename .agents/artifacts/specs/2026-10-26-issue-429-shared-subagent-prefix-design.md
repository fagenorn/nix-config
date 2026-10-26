# Cache proxy: shared subagent start-up prefix, blind re-test, then the reorder — issue 429

Design for https://github.com/fagenorn/nix-config/issues/429, attempt 2. Base:
`20241ee3` (`origin/main`, which carries #422's proxy, #423's keepalive and
#450's default-on routing). This spec supersedes
`2026-10-25-issue-429-shared-subagent-prefix-design.md` (branch
`worktree-issue-429-orchestrated` at `5d2f73e3`, "the attempt-1 spec") and
stands alone: the settled decisions it keeps are restated in the ledger below.
A bare "Dn" cites this spec's ledger; "#422 Dn", "#423 Dn" and "450 Dn" cite
those issues' specs.

## Triage

Lane triage input: {"signals": {"contract_change": {"value": "hit", "evidence": "adds a cache-proxy --reorder flag and rewrites subagent request bodies sent upstream by every default (routed) launch"}, "concurrency_or_persistence": {"value": "hit", "evidence": "the transform keeps a lock-guarded in-memory agent-id registry shared across the threaded proxy's request handlers"}, "open_design_questions": {"value": "no", "evidence": "the user approved the amended validity rules and the AC3 rewording; the prior spec settles transform shape, breakpoint and switch"}, "criteria_shape": {"value": "hit", "evidence": "four acceptance criteria, three of them live evidence runs no deterministic code check verifies"}}, "paths": ["python/agent_tools/subagent_prefix.py", "python/agent_tools/cache_proxy.py", "tests/test_cache_proxy.py", "tests/fixtures/cache_proxy", "docs/spikes/cache-proxy-prefix-retest.md", "docs/spikes/cache-proxy-prefix-retest-2-usage.md", "home/common/claude-code/default.nix", "home/common/claude-code/README.md", "python/README.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

Two subagents of the same type, started one after the other, open with the
same start-up attachments: project and user instructions, context, the skill
listing, deferred tools, environment and date. Each still writes those
attachments into the prompt cache, because Claude Code puts the per-agent
delegation prompt between them and places no breakpoint where the shared part
ends. The second sibling has nothing to read past `tools` and `system`.

#422's spike could not settle whether a reorder fixes this (#422 D21).
Attempt 1 of this issue re-tested it on Claude Code 2.1.302 and scored
`Verdict: instrument-failure`: every pair broke two validity rules that did
not fit 2.1.x's request layout (D7, D8). Under the amended rules it would have
computed R2 off = 8,249 and 8,249, R2 on = 14,942 and 14,934, a gain of 6,685,
and billing suffix `equal`. Those numbers were seen before the rules were
amended, so they cannot decide anything. The user approved the amendments,
reworded AC3, which the off arm's 8.2k `tools` + `system` read made
impossible, and asked for a blind re-run (D1, D3, D22). Since #450, every
default `claude` launch is routed through the proxy, so a shipped reorder
reaches every default session.

## Solution

There are two stages, and the first is a hard gate.

1. **Blind re-test.** This spec fixes every rule, threshold, phrase table and
   scoring step before any data is taken (D3). A throwaway recording harness
   on a free loopback port runs fresh sibling pairs on account `p2`,
   interleaved off/on/off/on. Their environment mirrors a default routed
   launch (D4, D5). In the on arm the harness applies this spec's exact
   reorder. The result is appended as § Attempt 2 to the attempt-1 report
   (D10). On anything but go, only the report is committed and the attempt
   stops for the user (D2).
2. **Reorder (go only).** The library module `agent_tools.subagent_prefix`
   holds the transform. `cache-proxy --reorder` applies it to subagent message
   requests before the keepalive sees them, and every other request is
   forwarded byte-identical (D12–D18). The service runs
   `--keepalive --reorder`. Unit tests run over the re-test's sanitised
   captures (D19). Two evidence runs, against built-launcher instances on
   free ports, measure the shared prefix (AC3) and regression and cost (AC4)
   (D23).

## Decisions

### Re-test (AC1; D2–D8)

**Harness.** This is attempt 1's harness design (attempt-1 plan, Task 1),
amended only as this spec says: one standard-library Python process in the
launch's scratch directory, never committed. It is a recording pass-through
to `https://api.anthropic.com`, bound to `127.0.0.1` port 0, and it refuses
to run if the bound port is 27183, 8160, 4322, 27450 or 27451. Its upstream
leg sends `Accept-Encoding: identity`, so that it can parse SSE usage. It
runs no keepalive (D6). Credential custody follows #422 D2: a bearer needed
for count-tokens calls is taken from a captured request and held only in
memory, bodies stay in scratch, header values are kept only for the #422
allowlist, agent ids appear only as 12-hex digests, and before any commit a
scan for `sk-ant-`, `Bearer ` and `oat01` finds nothing. The harness never
touches the installed service on 27183.

**Runs (D4).** There are four slots, run in the order off, on, off, on. Each
slot is one parent session,
`claude -p --model sonnet --output-format json "<parent prompt>"`, started
through the deployed `claude` wrapper from a new scratch worktree of the
branch head under the launch-scope scratch path. Its environment is the
caller's with these overrides (D5):

- `ANTHROPIC_BASE_URL=http://127.0.0.1:<harness port>`;
- `ENABLE_TOOL_SEARCH=true`;
- `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`;
- `CLAUDE_ACCOUNT=p2`.

The parent prompt dispatches two `general-purpose` subagents in sequence. The
second is launched only after the first has returned. Each gets a prompt
carrying the slot's nonce and its own sibling number, and it asks the
subagent to read `flake.nix` and reply with its first line. The read gives
each sibling at least two requests. The worktree path is new per slot, so
each slot's attachments are unique to it. A slot's child process group is
killed at 600 s. A slot in which any request is answered `429` is void, not
an invalid pair. The re-test stops there, unscored and uncommitted, and the
owner suspends with `blocked_on=usage_limit`. On resume, the void slot is
rerun whole with a new worktree and nonce, and the slots before it stand.

**Selection and records.** A subagent request is a `POST` whose path is
`/v1/messages`, with any query, carrying an `x-claude-code-agent-id` header. A
sibling's first request is the first request with that agent id. It holds no
assistant message, and its one user message holds the sibling's marker. Per
request the harness records: sequence, slot, arm, role (parent, sibling 1,
sibling 2, other), turn, agent digest, status, start and end, header names,
the raw `usage` of `message_start` and of the final `message_delta`
(#422 D25), the outcome (on arm), the marks before and after, and the sha256
of the body received and forwarded. For each sibling's first request it also
records the structure: for every block of `system` and of every message, its
type, character count, a 12-hex digest, its kind labels and whether it equals
its counterpart in the other sibling. It also records both siblings'
`cc_version` values and whether the two `system` arrays differ only in that
suffix. For each sibling, it records whether its turn-2 forwarded
`messages[0]` equals its turn-1 forwarded `messages[0]` with every
`cache_control` removed. That property is reported, but it does not gate.

**Phrase table (D3, D7).** It is pinned here, from strings present in the
pinned 2.1.310 binary, and it is never corrected from the captures:

| Label | Lead phrase |
|---|---|
| `instructions` | `Codebase and user instructions are shown below.` |
| `context` | `As you answer the user's questions, you can use the following context:` |
| `skill listing` | `The following skills are available for use with the Skill tool:` |
| `deferred tools` | `The following deferred tools are now available via` |
| `agent listing` | `Available agent types for the Agent tool:` |
| `MCP instructions` | `# MCP Server Instructions` |
| `environment` | `# Environment` followed by a newline |
| `date` | `Today's date is` |

**Kind labels (D7).** A request's attachment kinds are the union of two
readings:

- **Tagged, in `messages[0]`.** For every `<system-reminder>` tag in a text
  block of `messages[0]`, the text after the tag, with leading whitespace
  removed, gets the label of the table phrase it begins with, or `other`
  when it begins with none. This is attempt 1's reading.
- **Paragraph starts, in every later message.** For every text block of
  `messages[1:]`, whatever the message's role, each paragraph start is
  checked. A paragraph starts at the start of the text, after a newline, or
  right after a `<system-reminder>` tag, with leading spaces and tabs
  skipped. Each table phrase that the text begins with at such a position
  adds its label.

**Positions.** For sibling 1 of every on pair, the harness counts two
positions with `/v1/messages/count_tokens` on the body it forwarded. `P_sys`
is its tools and `system` with one user message `.`, and `P_att` is its tools
and `system` with one user message holding only the forwarded `messages[0]`
blocks before the prompt, in order. If count-tokens refuses, both positions
are recorded as refused and the billing answer is `inconclusive`. The gate
never depends on them.

**Validity.** A pair is valid when all of these hold:

1. Exactly two subagent agent ids appear.
2. Sibling 2's first request starts after sibling 1's first response ends,
   and no more than 240 s after it.
3. Sibling 1's first request is 2xx with `cache_creation_input_tokens > 0`.
   The digest of its received `messages[0]` blocks, leaving out the block
   that holds the sibling's marker, differs from every earlier slot's.
4. Sibling 1's first-request kinds include `instructions`, `skill listing`
   and `deferred tools` (D7).
5. In the on arm, both siblings' first requests are `applied` with exactly
   one mark added. Sibling 1's turn 2 is `applied` or `applied_at_cap`, and
   when it is `applied_at_cap`, its forwarded marks, listed in prefix order,
   equal its received marks as values (D8).
6. In the off arm, every forwarded body is byte-identical to the one
   received.

The first invalid pair is replaced in its arm slot by one rerun, with a new
worktree and nonce, so there are at most five runs. A second invalid pair
ends the re-test with `instrument-failure`. That outcome is not a
measurement: the report records which rule failed, nothing ships, and the
attempt stops for the user (D3).

### Go/no-go and the billing question (AC1; D9, D11)

**Gate.** `R2` is sibling 2's first-request `cache_read_input_tokens` from its
`message_start` usage. Over the valid pairs:

`Gain = min(R2 over on pairs) − max(R2 over off pairs)`.

The result is **go** when `Gain ≥ 4000` and every sibling first request was
2xx. Anything else is **no-go**. The report also states, without gating,
whether `min(R2 on) ≥ 10000`, as the forecast for the reworded AC3 (D22).

**Billing suffix (D11).** The answer comes from the valid on pairs and the
recorded structure:

- `equal`: the siblings' `system` arrays are identical in every valid pair;
- `ignored`: some valid on pair whose `system` arrays differ only in the
  suffix has `R2 ≥ 0.99 × P_att`;
- `splits`: every valid on pair differs only in the suffix, has equal tools
  and equal pre-prompt blocks, and has `R2 < 0.99 × P_sys`;
- `inconclusive`: anything else, a count-tokens refusal included.

The proxy never changes the billing header, whatever the answer. A no-go
that comes with `splits` names normalisation as the only lever left, and the
user's decision.

**Report (D10).** The attempt-1 report, `docs/spikes/cache-proxy-prefix-retest.md`,
enters this branch byte-identical from `5d2f73e3`, in the same commit as this
spec. It is a point-in-time record and is never edited. Attempt 2 appends `## Attempt 2`,
which opens with three lines, each matched as a whole line:

- `Attempt 2 billing suffix: equal|ignored|splits|inconclusive`
- `Attempt 2 gain: <int> tokens`, or `Attempt 2 gain: n/a` on an instrument
  failure
- `Attempt 2 verdict: go|no-go|instrument-failure`

Next comes a line naming the commit that fixed the rules, which precedes the
first data timestamp. Then come the run conditions (host, head, Claude Code
version, wrapper path, account, environment overrides, harness port), the
per-pair table with each pair's validity reasons, the arithmetic, the billing
rules applied, the structure tables, and the whole line
`Attempt 2 request log: <n> requests, <m> unaccounted`, where `m` must be 0.
Every request's raw usage goes, unchanged, to the sibling file
`docs/spikes/cache-proxy-prefix-retest-2-usage.md`, which the section links.
Once committed, the § Attempt 2 re-test text is never edited. AC3 and AC4
evidence is appended after it as later sections.

**Outcomes.** On go, the report, its usage file and the sanitised fixtures
(D19) are committed together. On no-go or instrument failure, only the
report and its usage file are committed, in the worktree. No product code is
written and no PR is opened, and the issue stays open for the user.

### The reorder (AC2; D12–D16, D20)

The transform is a function of one request plus one bounded registry of
agent ids. With `--reorder`, the proxy calls it for every forwarded request,
and forwards whatever it returns.

1. **Selection (D12).** A request whose method is not `POST`, whose path is
   not `/v1/messages`, or whose `x-claude-code-agent-id` header is missing or
   empty is `not_subagent`, and its body is never parsed. Otherwise the body
   is parsed strictly, with the `agent_tools.canonical` duplicate-key and
   non-finite hooks. A body that fails to parse, is not an object, or cannot
   be re-encoded is `unparsed`. A parsed body whose `system[0]` is not a text
   block starting `x-anthropic-billing-header:` with `cc_is_subagent=true`
   among its `;`-separated fields is `not_subagent`.
2. **First request, then every turn (D13).** A request whose `messages` hold
   no `assistant` message is a first request. When it comes out `applied` or
   `applied_at_cap`, its agent id enters the registry. A later request is
   reordered only when its agent id is registered. A request with an
   assistant message and an unregistered id, a fork's for one, is
   `unregistered` and is forwarded unchanged. The registry is an in-memory
   map behind one lock. It holds at most 4,096 ids, in insertion order, and
   evicts the oldest.
3. **Shape (D14, D15).** `messages[0]` must have role `user`, and its
   `content` must be a list of text blocks. Each block is classified:
   - an *attachment* is a block whose text starts with `<system-reminder>`;
   - a *budget line* is a block whose whole text is
     `<total_tokens>N tokens left</total_tokens>`, where N is a decimal
     integer or `Infinite`;
   - the *prompt* is any other block. Exactly one is allowed, and it must not
     sit at index 0.

   Only the last block of `messages[0]` may carry `cache_control`. Marks are
   the `cache_control` values of `tools[i]`, of `system[j]`, of each message
   block's inner `content[k]` followed by the block's own, and last a
   top-level `cache_control`; that is prefix order. A mark that is not an
   object, a `ttl` other than `5m` or `1h`, more than four marks, or TTLs
   that increase in prefix order (a missing `ttl` counts as `5m`) are all
   `shape`. Every other `messages[0]` layout is `shape` as well.
4. **Output.** Every block before the prompt, and every attachment after it,
   keeps its relative order. Then comes the prompt, then the budget lines that
   followed it, in order. A mark that was on the original last block stays on
   the last block. No other part of the body changes in value.
5. **Breakpoint (D16).** With `n` marks counted as in step 3: if `n < 4`, the
   block just before the prompt in the output gains `{"type":"ephemeral"}`.
   It also takes the `ttl` key, when present, of the nearest mark after it in
   prefix order. With no mark after it, it takes the nearest mark before it;
   with neither, it gets no `ttl`. The outcome is `applied`, with `n + 1`
   marks. If `n = 4`, the blocks are reordered and no mark is added:
   `applied_at_cap`. No existing mark is retimed or removed, and each keeps
   its place in prefix order.
6. **Encoding.** An applied body is encoded as compact UTF-8 JSON
   (`separators=(",", ":")`, `ensure_ascii=False`), keeping key order. The
   value of the client's `Content-Length` header is replaced in place. For
   every other outcome, the bytes the client sent are forwarded.
7. **A bug never blocks work (D20).** If an exception escapes the transform,
   the proxy forwards the original bytes and headers. It writes a
   `reorder_error` line (`method`, `path`, `error`, the exception's class and
   message) at once, and the request's `request` line says `reorder`
   `error`.

### Interface, switch and keepalive (D17, D18)

- `agent_tools.subagent_prefix` is a library module, not a command. One
  object holds the registry, and one method on it takes the method, path,
  header list and body bytes. It returns the body and header list to forward,
  and an outcome from the closed set `applied`, `applied_at_cap`,
  `not_subagent`, `unregistered`, `unparsed`, `shape`. The proxy adds
  `error`. Dispatch on the outcome fails loud on an unknown value.
- `cache-proxy --port N [--upstream URL] [--keepalive] [--reorder]`. Without
  `--reorder`, every byte sent upstream and every log line are what they are
  today. With it, the `listening` line gains `"reorder":true`, and every
  `request` line of a request that reached the transform gains `reorder`
  with the outcome. A request rejected while its body was read (`411`, `400`)
  and the health path carry no `reorder` field. `ProxyServer` takes the
  module's object as a constructor argument, or none.
- **Order in the handler (D18).** The handler reads the body, answers the
  health path, and assembles the upstream header list. Then it runs the
  transform, and only then calls the keepalive's `observe` on the transformed
  body and headers. The keepalive's candidate, and every ping replayed from
  it, therefore carry the reordered prefix that the conversation's cache
  entries were written under. Pings go out on the keepalive's own connection
  and never pass through the handler, so no body is transformed twice. The
  added mark copies an existing mark's `ttl`, so the keepalive's `ttl_1h`
  verdict never changes. Its tail-mark test changes only for a request whose
  last message is an unmarked `messages[0]`. That request then passes the
  test, so its pings would refresh the shared prefix.
- `cacheProxyArgs` in the claude-code module gains `--reorder` after
  `--keepalive`, so both hosts' services run with both. Turning it off means
  dropping the flag and rebuilding. Nobody runs `just switch`, `launchctl` or
  `systemctl` in this work. The user activates it.

### Fixtures (AC2; D19)

On go, the first valid on pair's captures are sanitised and committed under
`tests/fixtures/cache_proxy/`, each file under 64 KiB:

- sibling 1's and sibling 2's first requests, each as received and as
  forwarded;
- sibling 1's second request, as received and as forwarded;
- the parent's first request.

The sanitiser runs once, in scratch. It keeps every key, `type` and `role`
value, `cache_control` object, tool name, number and boolean, the billing
header line, the `<system-reminder>` tags and any budget line. It fills every
other string with `f` plus 16 hex of an HMAC-SHA256 under a random key that
is then discarded, so equal strings stay equal and different strings stay
different. It drops request metadata values. A file still over 64 KiB has
every `tools[i].input_schema` replaced by `{"type":"object"}`, in every
fixture. Before commit, the fixtures must show none of the credential
shapes, the user's email address, or `/Users/`. The transform reads only
what the sanitiser keeps, and the fixture test asserts that
transform(received) equals forwarded.

### Evidence runs (AC3, AC4; D6, D22, D23)

Every evidence run is on mbp, account `p2`, after the go and the code. Each
arm starts its own instance of the closure's built `cache-proxy` launcher in
the foreground: `<launcher> --port 0 --keepalive [--reorder]`, with the built
service's `SSL_CERT_FILE`. The port comes from its `listening` line and must
not be 27183, 8160, 4322, 27450 or 27451. The instance is stopped when the arm
ends. Each arm's sessions get the four overrides of § Runs, with
`ANTHROPIC_BASE_URL` pointing at that instance, and the built `claude`
wrapper first on `PATH`.
The two arms differ only in `--reorder`. Each arm's proxy log shows which arm
it is: the on arm has at least one `applied` `reorder` line, and the off arm
has no `reorder` field.

- **AC3, shared prefix.** Two runs, on then off. Each uses the re-test's
  parent prompt from a new scratch worktree, with
  `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1`. The read is
  `just agent-costs --report cache` over an isolated copy of that run's own
  transcripts. Its window runs from sibling 2's first transcript record, the
  later-starting `general-purpose` transcript, to the end of the run, so the
  row reports sibling 2's first call alone. The `general-purpose` start-up
  row's `1st read` must be at least 10,000 on, and at least 4,000 higher on
  than off (D22).
- **AC4, no regression.** `just evals from-issue 1` runs once per arm, on
  first and otherwise identical. The on run must print `VERDICT: PASS`. Each
  run's cost is the claude stratum's `totals.cost_usd` (`cost_basis`
  `list-price`) from `just agent-costs --format json --days 0 --projects-dir`
  over an isolated copy of that eval's own transcripts. These are every root
  transcript whose `cwd` is the sandbox's `repo` or below it, with its
  subagent directory. The threshold is on ≤ off. Both `results.jsonl` lines
  are cited. Transcripts do not hold keepalive pings, so each arm's `ping`
  lines and their usage are reported beside its cost, without gating.
- **Conditions.** There is one trial per run, never repeated to pass
  (#422 D27). The cutoff is the attempt deadline, `2026-10-26T22:27:10Z`. The
  re-test starts only with at least 45 minutes left, each AC3 run needs 15
  and each eval arm 50. A re-test that cannot start is reported blocked,
  with nothing committed. An evidence run that does not fit is recorded
  `human-pending` with its exact command, and only the arms that ran are
  measured and verified.

### Docs

`python/README.md` § `cache-proxy` gains `--reorder`: its selection, shape,
breakpoint and TTL rules, its outcomes, the `reorder` and `reorder_error` log
fields, and that it runs before the keepalive's observation. The claude-code
README's § Cache proxy says the service runs `--keepalive --reorder`, what
the reorder does, how to run an A/B (the built launcher on `--port 0` with
and without the flag), the billing-header stance, and links to the re-test
report. CLAUDE.md and AGENTS.md do not change.

## Test seams

Every test is in `tests/test_cache_proxy.py`, which `just agent-workflow-tests`
already runs. The seams follow #422 D15 and #423's keepalive tests.

- **Transform.** The module's object is called directly, on the D19 fixtures
  and on variants that the tests derive from them:
  - received equals forwarded as JSON values, for every fixture pair; the
    later turn runs after its first request, on the same object;
  - the two siblings' outputs are equal through the block before the prompt,
    `system[0]` aside, and the later turn's reordered `messages[0]` equals
    the first request's, marks aside;
  - registry: the later-turn fixture on a fresh object is `unregistered` and
    byte-identical, and so is a fork-shaped variant (assistant messages, an
    id never seen first); a registry over capacity drops its oldest id;
  - every `applied` output has `n + 1` marks, no more than four, and TTLs
    that do not increase in prefix order;
  - TTL and cap variants: four marks give `applied_at_cap` with the marks
    unchanged; a top-level `cache_control` counts and comes last; a `1h`
    system with a `5m` tail gives a `5m` new mark; all-`1h` gives `1h`; with
    no mark after the new one, the preceding mark's TTL; no marks, no `ttl`;
  - budget lines: one after the prompt stays after it and the mark lands
    before the prompt; one before the prompt keeps its place; a block that
    holds a budget line plus other text counts as a second prompt;
  - `shape` for the prompt at index 0, two prompts, a non-text block, a mark
    on a middle block, and an unknown `ttl`; `unparsed` for a duplicate key,
    a `NaN` and a non-object body; `not_subagent` without the header, with an
    empty one, or with the header but no `cc_is_subagent=true`.
- **Proxy, in-process.** `ProxyServer` on port 0 against `FakeUpstream`,
  which records raw bytes.
  - With the reorder on, a subagent fixture reaches upstream as the
    transformed bytes, with a matching `Content-Length`. The parent fixture,
    and the same subagent body sent to `/v1/messages/count_tokens`, reach
    upstream byte-identical, headers included. With the reorder off, the
    subagent fixture reaches upstream byte-identical.
  - `reorder` appears on log lines only with the flag, and never on a `411`
    or the health path. A transform that raises leaves the request
    byte-identical and writes `reorder_error`.
  - With the reorder and a keepalive both on, under the keepalive's injected
    clock, the ping due for that conversation carries the transformed body
    with only `max_tokens` changed (D18).
- **Command.** `--help` lists `--reorder`, and the existing round trip still
  passes without it.
- **Nix.** `just build`, plus an evaluation of both darwin agents and the
  anis-desktop unit showing `--keepalive --reorder` in their arguments
  (#422 D17). CI `Nix Eval` covers anis-desktop.

## Acceptance mapping

The reworded AC3 sentence, for the issue body (D22):

> - [ ] [evidence] Shared prefix works: the second of two sibling subagents of the same type gets a first-request cache read of at least 10,000 tokens with the reorder on, and at least 4,000 tokens more than with it off — measured: the `just agent-costs` start-up overhead table for the two runs, on mbp

| AC | Decided in | Verified by |
|----|-----------|-------------|
| AC1 re-test | § Re-test, § Go/no-go (D2–D11) | § Attempt 2's three lines, its pair, structure and billing sections, and the usage file with every request's raw usage |
| AC2 reorder code | § The reorder, § Interface, § Fixtures (D12–D20) | the transform and in-process tests under `just agent-workflow-tests`, and `just build` |
| AC3 shared prefix | § Evidence runs (D22, D23) | the two start-up rows: on ≥ 10,000 and on − off ≥ 4,000 |
| AC4 no regression | § Evidence runs (D6, D23) | the on eval's `PASS`, and its list-price cost ≤ the off eval's |

## Out of scope

- TTL rewriting of any kind, and any change to the keepalive or #423's spike
  record.
- Normalising or otherwise changing the billing header (D11).
- Moving the attachments that Claude Code places in later messages, such as
  2.1.302's system-role `messages[1]`, before the prompt. That is a
  cross-message transform this issue did not ask for.
- Reordering main-session requests, sharing a prefix across agent types, and
  changing Claude Code's own breakpoints.
- Stopping, restarting or reconfiguring the installed service on 27183, and
  `just switch`, `launchctl` or `systemctl`.
- A shadow phase, a Nix module option or runtime toggle for the reorder, and
  parsing response bodies in the proxy.
- Editing the issue body (the owner applies D22's sentence), and posting to
  anthropics/claude-code.
- Remote Control on routed sessions (#422 D21), and `claude-local`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | User decisions for attempt 2, not reopened: (a) the two validity amendments (D7, D8); (b) AC3 reworded (D22); (c) a blind re-run with the gate `min(R2 on) − max(R2 off) ≥ 4000` over valid fresh pairs, where a failing rule scores `instrument-failure` and stops for the user. This spec supersedes the attempt-1 spec. Blocker #422 counts as satisfied: its proxy is on `main` | User-approved scope (Phase 0); attempt-1 report § Informational; attempt-1 spec D1 | Reusing attempt 1's numbers under the amended rules (they were seen before the amendment, so they cannot be pre-registered); a fresh design (the deadline, and the transform's settled decisions still hold) |
| D2 | The re-test is plan task 1 and a hard gate. It runs a throwaway harness in launch scratch with #422 D2's credential custody. The on arm applies this spec's exact transform. Go commits the report, the usage file and the fixtures; anything else commits only the report and usage file, with no product code and no PR | Issue: re-test first, no-go "ship[s] nothing"; agent-helpers rule 1 (no committed top-level scripts); attempt-1 spec D2 | Building the transform first (wasted on no-go); a harness transform that differs from the product's (would measure a rule that does not ship) |
| D3 | Blind pre-registration. Every rule, threshold, phrase table and scoring step is fixed in this spec, and the plan adds only mechanics; both are committed before any pair runs. The phrase table is pinned now from the 2.1.310 binary's strings, with no correction path, which reverses attempt-1 D17's correction clause. § Attempt 2 names the commit that fixed the rules. A rule that fails again scores `instrument-failure`, and nothing is amended after the data | User decision (c); 450 precedent (rule committed before any timed pair ran); the eight phrases appear in the 2.1.310 binary | Correcting phrases from the captures (a rule amended after seeing data); a structure-only probe run before the gate (data taken before the rules are final, and the two-invalid-pair stop already bounds the cost) |
| D4 | Four slots, off/on/off/on, at most five runs (the first invalid pair is replaced once). Each slot is a `claude -p --model sonnet` parent through the deployed wrapper, from a new scratch worktree, dispatching two `general-purpose` siblings one after the other. Each sibling reads `flake.nix` under a nonce prompt, and the child is killed at 600 s. The account is `p2`, by name, through `CLAUDE_ACCOUNT`. A slot with any `429` is void: the re-test stops unscored for `blocked_on=usage_limit`, and that slot is rerun whole on resume | Issue: realistic attachments, fresh pairs, never replays; p1 and t1 are on weekly limits, and the owner suspends on a usage limit (Phase 0); the bar: truthful terminal states; attempt-1 spec D3 and D17; #425: `general-purpose` keeps CLAUDE.md and the skill listing | Replaying captured bodies (already cached, #422's invalid baseline); parallel dispatch (sibling 2 could arrive before sibling 1's write); one pair per arm (a single cache miss would decide the gate); scoring a `429` slot as an invalid pair (would turn a quota refusal into an instrument failure) |
| D5 | Every experiment session mirrors a default routed launch: a caller-set `ANTHROPIC_BASE_URL` pointing at the experiment's own instance on port 0 (never 27183, 8160, 4322 or 27450–27451), plus `ENABLE_TOOL_SEARCH=true` and `CLAUDE_CODE_TOTAL_TOKENS_REMINDER=padded-countdown`, both set explicitly. Reverses attempt-1 D18's `--port 27183` | claude-code README § Cache proxy: `claude-account` leaves a caller-set endpoint alone and exports neither variable for it, while a routed launch exports both (#450); Phase-0 constraint: the installed service is never touched; the reorder ships into default routed traffic | No budget-line variable (would measure a layout no default launch sends); reusing 27183 (would stop or reconfigure the installed service) |
| D6 | The re-test harness runs no keepalive. Every built-launcher evidence instance runs `--keepalive` in both arms, as the service does, so the arms differ only in `--reorder` | A ping is due only after 270 s idle (`DUE_AFTER`), past the gate's 240 s window, so it cannot change R2; AC4's "otherwise identical" baseline is today's service (`--keepalive`); AC4 is the only live run of the D18 composition | Keepalive in the harness (a second component in the gate's instrument, for no effect on R2); evidence arms without it (would compare against a configuration no host runs) |
| D7 | Amended rule (a), kinds: the union of the lead phrase after each `<system-reminder>` tag in `messages[0]`'s text blocks, and every table phrase at a paragraph start of a text block in `messages[1:]`, whatever the message's role. A paragraph starts at the text's start, after a newline, or right after a tag, with leading spaces and tabs skipped. `instructions`, `skill listing` and `deferred tools` are required | User decision (a); attempt-1 report: 2.1.302 put the skill listing, deferred tools, environment and date as plain paragraphs in a system-role `messages[1]`; Phase 0: write the rule for the system-role layout in general, not for one capture | Reading `messages[1]` only (one capture's index); also reading `system` (beyond the approved amendment); blank-line-only paragraph starts (would depend on one separator style) |
| D8 | Amended rule (b), marks: both sibling first requests must be `applied` with exactly one mark added. Sibling 1's turn 2 may be `applied` or `applied_at_cap`, and in the cap case its forwarded marks equal its received marks in prefix order. Turn-to-turn `messages[0]` equality is recorded, not gated | User decision (a); attempt-1 report: rolling marks put every turn 2 at the four-mark cap | Requiring turn 2 to be `applied` (cannot hold on 2.1.x); gating on turn-to-turn equality (a condition the user did not approve; the fixture test asserts it on go) |
| D9 | `R2` is sibling 2's first-request `message_start` `cache_read_input_tokens`. Go requires `Gain = min(R2 on) − max(R2 off) ≥ 4000` over valid pairs, with every sibling first request 2xx. `min(R2 on) ≥ 10000` is reported as AC3's forecast and does not gate | Issue's 4k go/no-go; #422 D19 and D22; attempt-1 spec D4 | The mean over pairs (one outlier pair could carry the gate); gating on AC3's absolute floor (the issue gates on the difference) |
| D10 | The attempt-1 report enters this branch byte-identical from `5d2f73e3`, in this spec's commit, and is never edited. Attempt 2 appends `## Attempt 2`, opened by the whole lines `Attempt 2 billing suffix:`, `Attempt 2 gain:` and `Attempt 2 verdict:`, with the request-log line and every raw usage line in `docs/spikes/cache-proxy-prefix-retest-2-usage.md`. AC3 and AC4 evidence is appended after it | 450 precedent: § Issue 450 appended to #438's report, with prefixed keys and a sibling runs file; the bar: point-in-time records are never rewritten; attempt 1's 45 KB plus a second log would pass the 64 KiB member cap (#422 D26) | A separate attempt-2 report (splits one issue's evidence across two documents); unprefixed keys (two `Verdict:` lines in one file); usage inline (over the cap) |
| D11 | The billing answer is `equal`, `ignored` (`R2 ≥ 0.99·P_att` with only the suffix differing), `splits` (`R2 < 0.99·P_sys` with tools and pre-prompt blocks equal) or `inconclusive`. Positions come from count-tokens on sibling 1's forwarded body. The proxy never alters the billing header. A no-go with `splits` names normalisation as the user's decision | Issue AC1; the header is Anthropic's attribution field, and the attempt may not grant itself new authorisation; attempt-1 spec D5 | Swapped-suffix probes (forge an attribution value to take a measurement); normalising the suffix (changes billing attribution without authorisation) |
| D12 | Selection: `POST` to path `/v1/messages` with a non-empty `x-claude-code-agent-id`, checked before any parse. Inside the body, the billing header must carry `cc_is_subagent=true`. Main-session bodies are never parsed, and everything else passes byte-identical | Issue: non-subagent requests byte-identical; #423's keepalive keys on the same header; the bar: defense in depth; attempt-1 spec D6 | The billing check alone (would parse every main-session body); the header alone (one inner check fewer against a client that sends it on main requests) |
| D13 | The transform reorders a first request (no assistant message) and registers its id on `applied` or `applied_at_cap`, then reorders every later request with that id. An unknown id with assistant messages, such as a fork, is `unregistered`. The registry is in-memory and lock-guarded, capped at 4,096 ids with the oldest evicted, and a restart or eviction costs one miss | Claude Code resends `messages[0]` unchanged each turn; a forked subagent carries its parent's first message and reads its parent's cache; attempt-1 spec D7 | First request only (turn 2 would miss turn 1's entry and rewrite the whole first message); stateless reordering (would reorder a fork's inherited message); a persisted registry (one miss does not justify a store) |
| D14 | Shape and output: `messages[0]` is a user message of text blocks. Attachments start `<system-reminder>`, and exactly one prompt sits anywhere but index 0. Only the last block carries a mark; marks are those of tools, `system`, message blocks with their inner content first, then top level. TTLs are `5m` or `1h` and never increase. The output keeps the blocks before the prompt and the attachments after it in order, then the prompt; the tail mark stays on the last block, and anything else is `shape` | Attempt 1: the prompt was block 3 of 5, with reminders on both sides; keeping block 0 in place keeps prompt-derived fingerprint inputs unchanged; attempt-1 spec D8 and D16 | Moving block 0 (could change a fingerprint input); marks that travel with their block (the tail mark would land on an attachment); walking every nested `cache_control` key (would count a tool parameter of that name) |
| D15 | A block whose whole text is Claude Code's budget line `<total_tokens>N tokens left</total_tokens>` (N digits or `Infinite`) is neither attachment nor prompt. One that follows the prompt stays after it, in order, and one before the prompt keeps its place. A block mixing the line with other text is a prompt | #450: routed launches now send the line; the 2.1.310 binary matches `^<total_tokens>(\d+) tokens left<\/total_tokens>$` and documents the line "after each regular user prompt"; without this rule such a block would make every default first request `shape`. Grounded in the binary, not in captures | Treating it as an attachment (would move Claude Code's post-prompt budget hint in front of the task); no rule (a likely blind instrument failure on default traffic) |
| D16 | Breakpoint: count every mark, a top-level one included. Below four, add `{"type":"ephemeral"}` to the block just before the prompt, with the `ttl` key of the nearest following mark (else the nearest preceding one, else none): `applied`. At four, reorder and add nothing: `applied_at_cap`. Existing marks are never moved, retimed or removed | API limit of four breakpoints, longer TTLs first, automatic caching takes a slot (claude-api prompt-caching reference); issue: exactly one breakpoint, no TTL rewriting; attempt-1 spec D9 | Moving or dropping one of Claude Code's marks at the cap (changes its own caching); a fixed `5m` TTL (breaks the order before a `1h` mark); skipping the reorder at the cap (breaks turn-to-turn prefix identity) |
| D17 | A library module, `agent_tools.subagent_prefix`, whose object holds the registry and returns body, headers and a closed-set outcome. `cache-proxy --reorder` is opt-in, and without it every byte and log line is unchanged. `cacheProxyArgs` gain `--reorder`. Applied bodies are compact UTF-8 JSON with `Content-Length` replaced in place. `reorder` appears on `request` lines that reached the transform, and an escaped exception is its own `reorder_error` line | Single responsibility (reshaping is a concern beside the relay); issue: switchable for A/B, no shadow phase; DRY (the service arguments' one home); attempt-1 spec D10 and D15 | An environment or per-request header switch (a second control channel); reorder on by default in the command (changes #422's contract for every caller and test); a Nix option (YAGNI) |
| D18 | The transform runs after the upstream headers are assembled and before the keepalive's `observe`, so the keepalive's candidate and pings carry the reordered bytes and the new `Content-Length`. Pings bypass the handler and are never transformed twice. AC4 reports each arm's `ping` usage beside its transcript cost, without gating | A ping must replay the prefix the cache entry was written under, or it refreshes nothing and writes a new entry (#423 fact 2); `cache_proxy._handle` already passes the assembled headers to `observe`; Phase-0 default | The keepalive observing the client's original body (its pings would carry Claude Code's order, which is never cached under `--reorder`); transforming pings (a ping is already a forwarded body) |
| D19 | Fixtures are the first valid on pair's sanitised captures: both siblings' first requests and sibling 1's second, each received and forwarded, plus the parent's first. Fillers are `f` plus 16 hex of an HMAC-SHA256 under a discarded key. Structure, marks, tool names, the billing line, reminder tags and budget lines are kept. Files are under 64 KiB, shrinking `input_schema` if needed, and are scanned for credentials, email and `/Users/`. The test asserts transform(received) equals forwarded | Issue: unit tests over recorded fixtures; the bar: production-shaped fixtures; #422 D26 member cap; attempt-1 spec D11 and D17 | Hand-written fixtures (could agree with a wrong classifier); raw bodies (personal data, and over the cap); plain digests (short strings could be guessed back) |
| D20 | An exception escaping the transform forwards the original bytes and headers and logs `reorder_error` before the request continues; the catch wraps only the transform call | #422's posture (a failing proxy never stops work); the bar: log before absorbing; Claude Code body shapes move on `just update`; attempt-1 spec D13 | Letting the handler fail (every routed subagent request would fail until a fix ships); a silent fallback (hides the bug) |
| D21 | The breakpoint rules rest on documented cache semantics: a read lands only where an earlier request wrote a breakpoint, marks are not part of the key, and an entry is readable once its response starts streaming. So the off arm cannot read unmarked attachments, and sequential dispatch is enough | claude-api prompt-caching reference; attempt-1 spec D14 | Re-measuring documented semantics in the re-test (spends quota on stated facts; the gate measures their combined effect) |
| D22 | AC3 is reworded to the sentence in § Acceptance mapping: on ≥ 10,000, and on − off ≥ 4,000 | User decision (b); attempt-1 report: the off arm already reads the 8,249-token `tools` + `system` prefix, so "under 6k off" fails whatever the reorder does; ≥ 4,000 matches the gate | The ratio `on ≥ 1.5 × off` (a new threshold shape with no precedent); dropping the off comparison (would credit a gain that is not the reorder's) |
| D23 | Evidence runs use the built launcher in the foreground, `--port 0 --keepalive [--reorder]`, with the built service's `SSL_CERT_FILE`, under the D5 environment, and stop it afterwards. There is one trial per run, and the deadline thresholds are 45 minutes (re-test), 15 (each AC3 run) and 50 (each eval arm); past them a run is `human-pending`. AC3 reads a windowed `--report cache` over an isolated transcript copy. AC4's cost is `agent-costs --format json --days 0 --projects-dir` over each eval's isolated transcripts, with `CLAUDE_CODE_FORCE_SESSION_PERSISTENCE=1` | #422 D14, D20, D24 and D27; attempt-1 spec D12, D18, D19 and D20 (a nested `-p` writes no transcript without the variable; a project-name filter selects nothing for an eval sandbox) | The built plist's command (it now carries `--keepalive --reorder` on 27183); host-wide windows (would count the orchestrator's own agents); rerunning until on ≤ off |
| D24 | (Plan.) Re-test pins, fixed before any data and mechanics only: (a) a slot is void only when a request Claude Code sent is answered `429`; a non-2xx count-tokens answer, `429` included, is a refusal; (b) billing is read in order: a refusal in any valid on pair gives `inconclusive`, then `equal` over every valid pair of both arms, then `ignored`, then `splits`, else `inconclusive`; (c) an on pair whose sibling 1 has no turn 2 fails rule 5; (d) the rules commit is the head Task 1 starts from; (e) a usage-limit stop names its results directory, and the resumed re-test copies the standing slots from it, or stops blocked when they are gone; (f) an instrument failure reads billing `inconclusive`; (g) a non-2xx sibling-2 first request counts `R2 = 0` and makes the verdict `no-go` | D3 (the plan adds only mechanics); § Positions: "the gate never depends on them"; D4 (the void rule exists for the account's usage limit) | Voiding on a count-tokens `429` (a harness-side refusal would suspend the attempt for a limit the sessions never hit); `equal` over on pairs only (weaker than "every valid pair") |
| D25 | (Plan.) Refines D10's layout. § Attempt 2 holds the three lines, the rules-commit line, the run conditions, the pair table, the gate arithmetic, the billing inputs with positions, and the request-log line. The structure tables and every request record with its raw usage (compact JSON, sorted keys) go to the usage file, and past 65,536 bytes the structure tables move to `docs/spikes/cache-proxy-prefix-retest-2-structure.md`. The report stays at most 65,536 bytes: the AC3 and AC4 sections move their fenced blocks to the usage file when they would not fit | D10 (the 64 KiB member cap); the attempt-1 report is 45,464 bytes, with 7.5 KB of structure for `system` and `messages[0]` alone, and attempt 2 reads every message | Structure tables in the report (about 65 KB before AC3 and AC4 are appended) |
| D26 | (Plan.) The transform's text has one home, Task 2's module block. Task 1's harness imports a scratch copy extracted from it, and Task 2 commits it unchanged. The module takes `AGENT_HEADER`, `Headers` and `header_value` from `agent_tools.cache_keepalive`, so `cache_proxy` imports it lazily, in `main` and in the handler's `_reorder`, as it does `cache_keepalive` (#423 D24). `transform` returns `(body, headers, outcome)`: the objects passed in, or new bytes and a new header list with every `Content-Length` value replaced in place | D2 (the harness measures the rule that ships); the bar, DRY: the agent-id header and its lookup must change together; `cache_keepalive` already imports `cache_proxy`'s constants; the keepalive is not edited (§ Out of scope) | A transform rewritten by hand in the harness (two copies that can drift); a local header lookup and constant (a second home); moving `header_value` into `cache_proxy` (edits the keepalive) |
| D27 | (Plan.) The D18 composition test is in `tests/test_cache_keepalive.py`'s `KeepaliveProxyTest`, on sibling 1's first-request fixture with every mark's `ttl` and the top-level `thinking` dropped, so the keepalive tracks it whatever TTLs the capture holds. Every other new test is in `tests/test_cache_proxy.py` | That class already owns the keepalive-and-proxy seam (`FakeClock`, `sse_reply`, `start`, `send`); the bar, DRY; `test_cache_keepalive` imports `test_cache_proxy`, so the reverse import would be circular | Copying the clock and SSE helpers into `tests/test_cache_proxy.py` (a second home for test machinery) |
| D28 | (Plan.) Re-test pin, fixed before any data: `run` appends and fsyncs each request record to `records-<id>-<N>.jsonl` as its relay ends and scores only from that file. A slot cut short by a harness exception stays as an excluded attempt. It is never deleted, scored, counted as an executed slot, or used in the gate or billing, but its records enter the request log, and a `429` among them voids it as in D4. The rerun keeps the slot id with a new nonce and worktree | Codex plan review B2: deleting the slot loses requests already sent, against "every request's raw usage" (D10, D25); D3 (mechanics only, pinned before data) | Deleting and rerunning under the same id (the audit trail loses billed requests); scoring an interrupted attempt (a harness fault would become a measured value) |
| D29 | (Plan.) Re-test pin, fixed before any data: D23's 45-minute admission stays, and `next --deadline` prints a `run` line only with at least 17 minutes left (the 11-minute slot bound plus 6 for the report and commit). Otherwise `stop deadline`: unscored, nothing committed, results kept, BLOCKED `re-test: attempt deadline cutoff` | Codex plan review S1: one admission check does not bound up to five 11-minute slots plus exception reruns; D23's cutoff | Killing a slot at the deadline (an unscorable half-slot); a larger admission threshold (changes D23's approved value) |
| D30 | (Plan.) AC4's transcript copy selects session ids through `agent_costs.find_sessions`, copies every project dir's `<id>.jsonl` and `<id>/` for them, and fails unless the copy's sessions match the source's. Refines D23's "with its subagent directory" | Codex plan review B1: `find_sessions` documents that a session entering a worktree writes subagents under another project dir (`python/agent_tools/agent_costs.py`); DRY: one home for session grouping | Copying only the root's sibling directory (drops worktree subagents' cost from AC4); a second session-grouping walk in the script |
| D31 | AC4 is met by the user's decision, and #429 closes rather than holds. The on eval passed (9/9) and cost 1.042106 USD list-price against 0.984163 off; the 0.058 USD gap (about 6%) is accepted as run-to-run noise, with both numbers kept in the acceptance record. Refines D23's one-trial rule for this criterion only | User decision, this session ("ok, do that"): the gap is inside the observed variance of a single paired eval, since #423's identical pair swung 0.083 USD (about 7%) with no mechanism behind it; the reorder only lengthens the shared, cached prefix (about 8.4k to 15.2k tokens, AC3), and cached reads are billed far below fresh input, so it can only lower the cost per request | One more eval pair (D23 and #422 D27 forbid rerunning toward a pass, and one pair could not settle a gap this size either way); holding #429 open as `needs-verification` (no further measurement could clear it) |
