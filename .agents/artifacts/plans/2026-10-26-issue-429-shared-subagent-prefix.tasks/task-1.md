# Task 1: Blind re-test and the go/no-go gate

Spec § Re-test and § Go/no-go and the billing question, per D2–D11, D21 and D24–D26. A throwaway harness in launch scratch runs fresh sibling pairs through a recording pass-through to `https://api.anthropic.com`. The on arm applies the transform that ships: the module block of Task 2's file at the rules commit, extracted unchanged (D26). The harness appends § Attempt 2 to the committed report and writes its usage file and, on go only, the sanitised fixtures and the acceptance record. No product code is written here, and the harness is never committed.

**This is a blind measurement (D3).** Every rule, phrase, threshold and scoring step below is fixed by the spec and this plan, committed before the first slot. None of them is changed after data is taken, for any reason. A pair that fails a rule is invalid as scored, and a second invalid pair is `instrument-failure`.

**Files:**
- Modify: `docs/spikes/cache-proxy-prefix-retest.md` (append `## Attempt 2`; every attempt-1 byte stays as committed, D10)
- Create: `docs/spikes/cache-proxy-prefix-retest-2-usage.md`, and `docs/spikes/cache-proxy-prefix-retest-2-structure.md` only when the usage file would pass 65,536 bytes (D25)
- Create, on go only: `tests/fixtures/cache_proxy/{sibling1-first,sibling2-first,sibling1-second}.{received,forwarded}.json`, `tests/fixtures/cache_proxy/parent-first.json`, `.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md`
- Scratch only (never committed): `$S/i429/harness.py`, `$S/i429/subagent_prefix.py`, `$S/i429/results/`, the `$S/i429/retest-*` worktrees

**Interfaces:**
- Consumes: the deployed wrapper `/etc/profiles/per-user/anis/bin/claude` (Claude Code 2.1.310 at planning), which leaves a caller-set `ANTHROPIC_BASE_URL` alone; the module block of `.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.tasks/task-2.md`; `agent_tools.canonical` and `agent_tools.cache_keepalive` from the worktree's `python/`; the root's **Parent prompt**, **Scratch worktrees** and **Routed-launch environment**.
- Produces, as whole lines of the report: `Attempt 2 billing suffix: equal|ignored|splits|inconclusive`, `Attempt 2 gain: <int> tokens` or `Attempt 2 gain: n/a`, `Attempt 2 verdict: go|no-go|instrument-failure`, `Attempt 2 transform sha256: <64 hex>` and `Attempt 2 request log: <n> requests, <m> unaccounted`. On go: the seven fixtures by those names (compact UTF-8 JSON, one trailing newline), which Tasks 2 and 3 load, and the acceptance record with rows `AC1`–`AC4`.

**Invariants:**
- Credential custody per the root. No bearer, cookie or agent-id value reaches a file; an agent id appears only as 12 hex digits of its sha256.
- Off arm: every forwarded body and header list is the one received, apart from the recorder's hop-by-hop drop and `Accept-Encoding: identity`.
- On arm: one `SubagentPrefix()` per slot sees every request, and the body and header list it returns are what is sent.
- Every request the recorder relays or the harness sends is in the request log with its status and raw usage, or its error.
- A measured value is never a reason to rerun. Only the first invalid pair (once, D4), a void slot (on resume, D4, D24) and a slot cut short by a harness exception are rerun, each whole with a new worktree and nonce.

- [ ] **Step 1: Check the starting state**

Run (timeout 60 s) from the worktree root:

```bash
set -euo pipefail
test "$(hostname -s)" = mbp
test -z "$(git status --short)"
if grep -qx '## Attempt 2' docs/spikes/cache-proxy-prefix-retest.md; then exit 1; fi
test -x /etc/profiles/per-user/anis/bin/claude
test "$(git worktree list | grep -c /i429/ || true)" = 0
git rev-parse HEAD; git log -1 --format=%cI HEAD
readlink -f /etc/profiles/per-user/anis/bin/claude; /etc/profiles/per-user/anis/bin/claude --version
```

Record `RULES` (the full SHA, D24d), `RULES_AT` (its committer date), the wrapper target and the version. Compute the minutes left (root § Deadline); with fewer than 45, report BLOCKED `re-test: attempt deadline cutoff` with nothing committed (D23).

**Resume after a usage limit (D24e).** When the brief names a prior results directory, copy its `slot-*.json` and `bodies/` into `$S/i429/results/` before anything runs, then go on from Step 2; Step 5's `next --resume` reruns the void slot. If that directory is gone, report BLOCKED `re-test: earlier slots lost`, with nothing committed.

- [ ] **Step 2: Extract the transform**

Run (timeout 30 s):

```bash
set -euo pipefail
mkdir -p "$S/i429/results/bodies"
git show "$RULES:.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.tasks/task-2.md" > "$S/i429/task-2.md"
python3 -I - "$S/i429/task-2.md" "$S/i429/subagent_prefix.py" <<'EOF'
import sys
lines = open(sys.argv[1], encoding="utf-8").read().split("\n")
start = [i for i, line in enumerate(lines) if line.startswith('"""Reorder a subagent\'s first user message')]
if len(start) != 1:
    sys.exit(f"want one module block, found {len(start)}")
end = lines.index("```", start[0])
open(sys.argv[2], "w", encoding="utf-8").write("\n".join(lines[start[0]:end]) + "\n")
EOF
shasum -a 256 "$S/i429/subagent_prefix.py"
```

Record the digest as `TRANSFORM_SHA`. The file is never edited.

- [ ] **Step 3: Write the harness `$S/i429/harness.py`**

One standard-library file, run as `python3 -I $S/i429/harness.py <phase> --repo <worktree root> --out $S/i429/results [options]`. Its first lines put `<repo>/python` and its own directory first on `sys.path`, so it imports `subagent_prefix` (the Step 2 copy), `agent_tools.canonical` and `agent_tools.cache_keepalive`, while the child's environment stays the caller's. Phases: `selfcheck`, `run --arm off|on --slot <id>`, `next [--resume]`, `report --doc <report> --usage <usage file> --meta <json>`, and `fixtures --dest tests/fixtures/cache_proxy`. Slot ids are `1`–`4`, `<id>r` (the D4 rerun of an invalid pair) and `<id>v` (the rerun of a void slot); the arms of `1`–`4` are off, on, off, on, and a rerun keeps its slot's arm.

**`run`** (bound 11 min). It draws the nonce `N = secrets.token_hex(4)`, creates the worktree `$S/i429/retest-<id>-<N>` (root rule), starts the recorder, and runs `[/etc/profiles/per-user/anis/bin/claude, "-p", "--model", "sonnet", "--output-format", "json", <parent prompt with N>]` with that `cwd` and `os.environ` plus the four root overrides, `ANTHROPIC_BASE_URL` naming the recorder's port. The child gets `start_new_session=True`; its process group is killed at 600 s. Then it stops the recorder, takes the positions (on arm), scores the slot, writes `<out>/slot-<id>.json` (records, structure, positions, validity and reasons, void, exit code, stdout's `subtype`, the recorder port, `N`) and removes the worktree with `git worktree remove --force`. Bodies go to `<out>/bodies/<id>-<seq>.received.json` and `.forwarded.json`.

**Recorder.** `socketserver.ThreadingTCPServer` on `127.0.0.1:0` (`daemon_threads = True`) with an HTTP/1.1 `BaseHTTPRequestHandler`. A bound port of 27183, 8160, 4322, 27450 or 27451 is closed and rebound. Each request goes upstream on a fresh `http.client.HTTPSConnection("api.anthropic.com", timeout=600)` by `putrequest(method, path, skip_host=True, skip_accept_encoding=True)`. The header list is the client's in order minus `host`, `connection`, `keep-alive`, `proxy-*`, `te`, `trailer`, `transfer-encoding`, `upgrade` and `accept-encoding`, with `("Host", "api.anthropic.com")` first and `("Accept-Encoding", "identity")` last, so SSE usage can be parsed. In the on arm that list and the body go through `transform(method, path, headers, body)`, and its returned body and list are sent; in the off arm the body is sent as received. The response streams back (`read1(65536)`, an unsized body re-chunked, a flush per chunk) while its bytes accumulate for parsing. Header values live only in an in-memory dict keyed by `seq`, the only bearer store.

**Record per request:** `seq`, `slot`, `arm`, `role` (`parent`, `sibling1`, `sibling2`, `other`), `turn`, `agent` (12-hex digest or `null`), `method`, `path`, `status`, `start` and `end` (UTC ISO to ms: head received, relay finished), `header_names`, `headers_kept` (values of `anthropic-version`, `anthropic-beta`, `content-type`, `user-agent`, `x-app` and `x-stainless-*` only), `outcome` (on arm), `marks_before` and `marks_after` (the count by the module's `_marks(_holders(value))` on the received and forwarded bodies, `null` when not a JSON object), `received_sha256`, `forwarded_sha256`, `usage_start` (`message_start.message.usage`), `usage_delta` (the last `message_delta.usage`; for a JSON reply, its `usage`), `error_body` (first 2 KiB when `status >= 400`; with no response, `status` is `null` and `error_body` holds the exception's class and message) and `position` (`P_sys`, `P_att` or `null`).

**Selection, roles and turns.** A subagent request is a `POST` whose `urlsplit(path).path` is `/v1/messages` with a non-empty `x-claude-code-agent-id`. `sibling<k>` is every subagent request whose agent id first appeared on a request with no assistant message and exactly one `user` message, which contains `I429-SIBLING-<k>-<N>`; that request is its first request (turn 1), and later ones count up. Any other agent id is `other`. A request without the header is `parent`. The parent's first request is the first parent `/v1/messages` `POST` with no assistant message whose `messages[0]` contains `I429-PARENT-<N>`, whose `tools` is a non-empty list and whose billing line lacks `cc_is_subagent=true`.

**Kinds (D7).** The phrase table, pinned and never corrected:

| Label | Lead phrase |
|---|---|
| `instructions` | `Codebase and user instructions are shown below.` |
| `context` | `As you answer the user's questions, you can use the following context:` |
| `skill listing` | `The following skills are available for use with the Skill tool:` |
| `deferred tools` | `The following deferred tools are now available via` |
| `agent listing` | `Available agent types for the Agent tool:` |
| `MCP instructions` | `# MCP Server Instructions` |
| `environment` | `# Environment` followed by `\n` |
| `date` | `Today's date is` |

A request's kinds are the union of two readings; a string `content` counts as one text block. (1) For each text block of `messages[0]` and each occurrence of `<system-reminder>` in it, the text after the tag with `str.lstrip()` applied gets the label of the phrase it starts with, else `other`. (2) For each text block of each message in `messages[1:]`, whatever its role, the paragraph starts are offset 0, every offset just after a `\n`, and every offset just after a `<system-reminder>`; from each, spaces and tabs are skipped, and every phrase the text starts with there adds its label.

**Structure** (each sibling's first request, received body): for every block of `system` and of every message, its place (`system`, `messages[i]`), index, type, character count (the text's length, else that of its compact JSON), 12 hex of the sha256 of its compact sorted-key JSON, its kind labels, and whether it equals the same place and index in the other sibling. Also both `cc_version` values (`re.search(r"cc_version=([^;]+)", system[0].text)`), `system_equal`, `suffix_only` (the arrays differ but are equal once each `cc_version` value is replaced by `X`), `tools_equal`, `pre_prompt_equal` (the forwarded `messages[0]` blocks before the prompt are equal as JSON values), and for each sibling `second_equal`: whether its turn-2 forwarded `messages[0]` equals its turn-1 forwarded `messages[0]` once every `cache_control` is removed (reported, never gating, D8).

**Positions (on arm, sibling 1, D11).** Two `POST /v1/messages/count_tokens?beta=true` calls with sibling 1's in-memory first-request headers (`Content-Length` recomputed, `Accept-Encoding: identity`). Bodies: `model`, `system` and `tools` of sibling 1's forwarded first request, with `messages` `[{"role":"user","content":"."}]` for `P_sys`, or `[{"role":"user","content":<the forwarded messages[0] blocks before the prompt, in order>}]` for `P_att`. A non-2xx answer, `429` included, records that position `refused` (D24a).

**Void (D4, D24a).** A slot in which any request the recorder relayed was answered `429` is void: `slot-<id>.json` gets `"void": "usage_limit"`, and the slot is not scored.

**Validity** (each failed rule is recorded as a reason):
1. Exactly two distinct agent ids appear on subagent requests, and both siblings were found.
2. `0 s < start(sibling 2 first) − end(sibling 1 first) ≤ 240 s`.
3. Sibling 1's first request is 2xx with `usage_start.cache_creation_input_tokens > 0`, and the sha256 of the compact sorted-key JSON of its received `messages[0]` blocks, without the block holding `I429-SIBLING-1-<N>`, differs from that of every earlier executed slot.
4. Sibling 1's first-request kinds include `instructions`, `skill listing` and `deferred tools`.
5. On arm: both siblings' first requests are `applied` with `marks_after == marks_before + 1`; sibling 1 has a turn 2 (D24c), which is `applied` or `applied_at_cap`, and when `applied_at_cap`, its forwarded marks in prefix order equal its received marks as values.
6. Off arm: `forwarded_sha256 == received_sha256` for every request.

**`next`** prints one line. With a void last slot: `stop usage_limit`, or under `--resume` `run <id>v <arm>`. With two invalid executed slots: `stop instrument-failure`. With one, and its rerun not run: `run <id>r <arm>`. Otherwise the first of `1`–`4` not run, as `run <id> <arm>`, and with all done, `score`. The four scored pairs are slots `1`–`4`, each replaced by its `r` or `v` rerun when there is one.

**Gate (D9, D24g).** `R2` is sibling 2's first-request `usage_start.cache_read_input_tokens`, counted as 0 when that request is not 2xx. With four valid scored pairs, `Gain = min(R2 over on) − max(R2 over off)`, and the verdict is `go` when `Gain >= 4000` and every sibling first request of those pairs is 2xx, else `no-go`. A second invalid pair gives `instrument-failure` with `Attempt 2 gain: n/a`. The forecast `min(R2 on) >= 10000` is reported, never gating.

**Billing (D11, D24b, D24f)**, first match: `inconclusive` on `instrument-failure` or when any valid on pair has a refused position; `equal` when every valid pair of both arms has `system_equal`; `ignored` when some valid on pair has `suffix_only` and `R2 >= 0.99 * P_att`; `splits` when every valid on pair has `suffix_only`, `tools_equal` and `pre_prompt_equal` and `R2 < 0.99 * P_sys`; else `inconclusive`. A `no-go` with `splits` adds the sentence `Normalising the billing header is the only lever left, and that is the user's decision (D11).`

**Report (D10, D25).** `report` reads only the slot files and the meta JSON and appends to the report, after one blank line:

```text
## Attempt 2

Attempt 2 billing suffix: <answer>
Attempt 2 gain: <int> tokens          (or: Attempt 2 gain: n/a)
Attempt 2 verdict: <verdict>

Attempt 2 rules commit: <RULES>, committed <RULES_AT>; first data <earliest record start>.
Attempt 2 transform sha256: <TRANSFORM_SHA>
```

Then a run-conditions paragraph: date, host, `RULES`' short SHA, Claude Code version, wrapper path and target, account `p2` by `CLAUDE_ACCOUNT`, `--model sonnet`, the four overrides, each slot's recorder port, `Accept-Encoding: identity` upstream, no keepalive (D6), the slots in run order with any void or rerun, any harness exception and its fix, and the phrase table. Then `### Attempt 2 pairs` (one row per executed slot: arm, valid, reasons, `R1 / W1` and `R2 / W2` as cache read and creation of each sibling's first request, the gap, the outcomes of sibling 1, sibling 2 and sibling 1's turn 2, their marks before→after, sibling 1's kinds, exit code and subtype), `### Attempt 2 gate arithmetic` (the formula with its numbers, the 2xx check and the forecast), `### Attempt 2 billing suffix` (each valid pair's `system_equal`, `suffix_only`, `tools_equal`, `pre_prompt_equal`, `R2`, `P_sys`, `P_att`, the rules in order and the answer), and `### Attempt 2 request log`, holding the whole line `Attempt 2 request log: <n> requests, <m> unaccounted` and a link to the usage file. A record is unaccounted when it has neither a non-null `status` nor an `error_body`, or when it is a 2xx `POST /v1/messages` (count-tokens excluded) with neither `usage_start` nor `usage_delta`.

The usage file opens `# Cache proxy prefix re-test, attempt 2: structure and request log — issue 429`, links back to the report, and holds `## Structure` (per slot, both siblings' block tables and the structure values) and `## Request log` (the header sets by name, then every record, with `usage_start` and `usage_delta` as compact sorted-key JSON, unchanged). If that file would pass 65,536 bytes, `## Structure` goes instead to `docs/spikes/cache-proxy-prefix-retest-2-structure.md`, linked from both (D25).

**Fixtures (go only, D19).** Source: the first valid on pair. `sanitise(value)` walks recursively, keeping every key and key order, and keeps verbatim: numbers, booleans and `null`; the string values of keys `type` and `role`; every `cache_control` value whole; `tools[i].name`; `system[0].text` when it starts `x-anthropic-billing-header:`; and every string that is wholly a budget line (`re.fullmatch(r"<total_tokens>(?:[0-9]+|Infinite) tokens left</total_tokens>", s)`). Each value under a top-level `metadata` becomes `"dropped"`. Every other string `s` becomes `F(s) = "f" + hmac.new(key, s.encode("utf-8", "surrogatepass"), "sha256").hexdigest()[:16]`, except that one starting `<system-reminder>` becomes `"<system-reminder>" + F(s)`, plus `"</system-reminder>"` when `s.rstrip()` ends with it. One `key = secrets.token_bytes(32)` serves all seven files and is never written. Write `json.dumps(v, ensure_ascii=False, separators=(",", ":")) + "\n"`. If any file is then 65,536 bytes or more, every `tools[i].input_schema` in every file becomes `{"type":"object"}` and all seven are rewritten. The files: both siblings' first requests and sibling 1's turn 2, as `.received.json` and `.forwarded.json`, and the parent's first request as `parent-first.json`.

- [ ] **Step 4: Self-check the harness offline (no data)**

`selfcheck` makes no network call and must print `selfcheck-ok`, asserting on synthetic inputs built in the harness: (1) a `messages` list whose `messages[0]` holds tagged instructions and context blocks and a prompt, and whose system-role `messages[1]` text holds the skill listing at a line start, a deferred-tools reminder after a `<system-reminder>` tag, `  # Environment\n` after a newline and two spaces, and `Today's date is`, yields exactly `instructions`, `context`, `skill listing`, `deferred tools`, `environment` and `date`; (2) `SubagentPrefix().transform` on a synthetic subagent body (billing line with `cc_is_subagent=true`, `messages[0]` of two attachments, the prompt and one attachment) returns `applied` with one mark more, and as a `GET` returns `not_subagent` with the very objects passed; (3) four synthetic valid pairs with `R2` off 8249 and 8300, on 12400 and 12500 score `Gain 4100` and `go`, with on 12000 instead `Gain 3700` and `no-go`, and two invalid pairs `instrument-failure` with `n/a`; (4) equal `system` arrays give `equal`, and the same with one refused position give `inconclusive`; (5) `next` over synthetic slot files walks `1`, `2`, `2r` after an invalid `2`, then `3`, `4`, `score`, and stops `instrument-failure` at a second invalid slot. Run (timeout 120 s): `python3 -I $S/i429/harness.py selfcheck --repo "$PWD" --out $S/i429/results`. A failing self-check is a harness bug: fix the harness, never a rule, and rerun the self-check.

- [ ] **Step 5: Run the slots**

Compute the minutes left again; with fewer than 45, report BLOCKED `re-test: attempt deadline cutoff`, with nothing committed. Then repeat: run (timeout 30 s) `python3 -I $S/i429/harness.py next --repo "$PWD" --out $S/i429/results` (with `--resume` on a resumed attempt's first call), and for `run <id> <arm>` run (timeout 720 s) `launch-scope exec … -- python3 -I $S/i429/harness.py run --arm <arm> --slot <id> --repo "$PWD" --out $S/i429/results`, until it prints `score` or `stop …`.

- `stop usage_limit`: stop, commit nothing, remove the slot worktrees, and report BLOCKED `blocked_on=usage_limit` naming the absolute `$S/i429/results` (D4, D24e).
- A harness exception (a traceback, not a scored result) is fixed in the harness's mechanics only, never in a rule, phrase, threshold or scoring step. The slot it cut short is deleted and rerun whole under the same id, and the fix and the slot go into the run conditions.

- [ ] **Step 6: Write the report**

Write `$S/i429/meta.json` with `RULES`, `RULES_AT`, `TRANSFORM_SHA`, the date, host, version and wrapper target. Run (timeout 60 s): `python3 -I $S/i429/harness.py report --repo "$PWD" --out $S/i429/results --doc docs/spikes/cache-proxy-prefix-retest.md --usage docs/spikes/cache-proxy-prefix-retest-2-usage.md --meta $S/i429/meta.json`.

- [ ] **Step 7: Verify the report**

Run (timeout 60 s) from the worktree root:

```bash
set -euo pipefail
f=docs/spikes/cache-proxy-prefix-retest.md
u=docs/spikes/cache-proxy-prefix-retest-2-usage.md
git show "$RULES:$f" > "$S/i429/attempt-1.md"
head -c "$(wc -c < "$S/i429/attempt-1.md")" "$f" | cmp - "$S/i429/attempt-1.md"
test "$(grep -cx '## Attempt 2' "$f")" -eq 1
grep -Eqx 'Attempt 2 billing suffix: (equal|ignored|splits|inconclusive)' "$f"
grep -Eqx 'Attempt 2 gain: (-?[0-9]+ tokens|n/a)' "$f"
grep -Eqx 'Attempt 2 verdict: (go|no-go|instrument-failure)' "$f"
test "$(grep -Ec '^Attempt 2 (billing suffix|gain|verdict): ' "$f")" -eq 3
grep -qx "Attempt 2 transform sha256: $TRANSFORM_SHA" "$f"
grep -Eqx "Attempt 2 rules commit: $RULES, committed .*; first data .*\." "$f"
if grep -qx 'Attempt 2 verdict: go' "$f"; then
  test "$(sed -n 's/^Attempt 2 gain: \(-\{0,1\}[0-9][0-9]*\) tokens$/\1/p' "$f")" -ge 4000
fi
if grep -qx 'Attempt 2 verdict: instrument-failure' "$f"; then
  grep -qx 'Attempt 2 gain: n/a' "$f"; grep -qx 'Attempt 2 billing suffix: inconclusive' "$f"
fi
grep -Eqx 'Attempt 2 request log: [0-9]+ requests, 0 unaccounted' "$f"
for p in "$f" docs/spikes/cache-proxy-prefix-retest-2-*.md; do test "$(wc -c < "$p")" -le 65536; done
grep -q 'cache_read_input_tokens' "$u"
if grep -nE 'sk-ant-|Bearer |oat01' "$f" docs/spikes/cache-proxy-prefix-retest-2-*.md; then exit 1; fi
if grep -nF "$(git config user.email)" "$f" docs/spikes/cache-proxy-prefix-retest-2-*.md; then exit 1; fi
if git status --porcelain --untracked-files=all | grep -v -e ' docs/spikes/cache-proxy-prefix-retest\.md$' -e ' docs/spikes/cache-proxy-prefix-retest-2-\(usage\|structure\)\.md$'; then exit 1; fi
echo retest-report-ok
```

Expected: `retest-report-ok`. At the starting commit it fails at `test "$(grep -cx '## Attempt 2' …)"`, because there is no § Attempt 2. Check by hand that the rules commit's date precedes the first data timestamp.

- [ ] **Step 8: On go only, write and verify the fixtures and the acceptance record**

Skip this step unless the report holds `Attempt 2 verdict: go`. Run (timeout 60 s): `python3 -I $S/i429/harness.py fixtures --repo "$PWD" --out $S/i429/results --dest tests/fixtures/cache_proxy`. Then check that the transform turns each sanitised `received` into its `forwarded` (one `SubagentPrefix()` for sibling 1's first, sibling 2's first and sibling 1's turn 2, in that order, with agent ids `agent-1`, `agent-2`, `agent-1`), comparing as JSON values. If it does not, delete the fixtures, commit the report and usage file alone (Step 9's no-go form), and report BLOCKED `fixture sanitiser breaks the transform`.

Create `.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md`: the heading `# Acceptance record — issue #429`; the sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/429).`; and the table `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |` with rows `AC1`–`AC4` in order. `Criterion` is the issue's criterion line verbatim without its `- [ ] ` (`gh issue view 429 --repo fagenorn/nix-config --json body --jq .body`), each `|` escaped as `\|`; `Kind` and `Check or command` come from the root's Acceptance map. `AC1`: `Observed` holds the three `Attempt 2` lines and the forecast, `Commit` is `RULES`' short SHA, `Conditions` the account, model, version, wrapper and slot list. `AC2`: `Observed` reads `in final verification`. `AC3`: `pending (Task 4)`. `AC4`: `pending (Task 5)`. `Verdict` is `—` in every row; the sdd controller writes it.

Run (timeout 60 s):

```bash
set -euo pipefail
d=tests/fixtures/cache_proxy
for n in sibling1-first sibling2-first sibling1-second; do
  for v in received forwarded; do test -s "$d/$n.$v.json"; done
done
test -s "$d/parent-first.json"; test "$(ls "$d" | wc -l | tr -d ' ')" -eq 7
for p in "$d"/*.json; do
  test "$(wc -c < "$p")" -lt 65536
  python3 -I -c 'import json, sys; assert isinstance(json.load(open(sys.argv[1], encoding="utf-8")), dict)' "$p"
done
if grep -nE 'sk-ant-|Bearer |oat01|/Users/' "$d"/*.json; then exit 1; fi
if grep -nF "$(git config user.email)" "$d"/*.json; then exit 1; fi
a=.agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
test "$(grep -c '^| AC[1-4] |' "$a")" -eq 4
grep -q '^| AC3 |.*pending (Task 4)' "$a"; grep -q '^| AC4 |.*pending (Task 5)' "$a"
echo fixtures-ok
```

Expected: `fixtures-ok`.

- [ ] **Step 9: Commit, then apply the gate**

On go:

```bash
git add docs/spikes/cache-proxy-prefix-retest.md docs/spikes/cache-proxy-prefix-retest-2-*.md tests/fixtures/cache_proxy .agents/artifacts/plans/2026-10-26-issue-429-shared-subagent-prefix.acceptance.md
launch-commit … -- -m "docs(spike): shared subagent prefix re-test attempt 2, go, with fixtures (issue 429)" -m "<session trailers>"
```

On no-go or instrument failure: `git add docs/spikes/cache-proxy-prefix-retest.md docs/spikes/cache-proxy-prefix-retest-2-*.md`, then commit with `-m "docs(spike): shared subagent prefix re-test attempt 2, <verdict> (issue 429)"`.

Before reporting, stop every process the harness started, check that `test "$(git worktree list | grep -c /i429/ || true)" = 0` passes and that `git status --short` prints nothing, and leave `$S/i429/results` in place. On go, report DONE with the three lines. On no-go or instrument failure, report BLOCKED `re-test gate: <verdict>` with the three lines and the report path: per D2, nothing further is built, and the owner stops the attempt for the user.
