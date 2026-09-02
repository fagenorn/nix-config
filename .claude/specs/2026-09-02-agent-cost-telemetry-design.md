# Machine-readable agent-cost telemetry and the #70 evidence bundle

Issue: [#120](https://github.com/fagenorn/nix-config/issues/120). Absorbs [#97](https://github.com/fagenorn/nix-config/issues/97).
Binding contract: [#70](https://github.com/fagenorn/nix-config/issues/70). Storage posture: [#72](https://github.com/fagenorn/nix-config/issues/72).
Downstream, not built here: [#68](https://github.com/fagenorn/nix-config/issues/68), [#71](https://github.com/fagenorn/nix-config/issues/71).

## Problem

Every standardization refactor, every promotion (#68) and the Stage-4 cutover (#71)
must clear #70's token-and-quality gate, and #70 says the gate is decided by a
versioned before/after *evidence bundle* — not by a claim. No such instrument
exists. The nearest thing, `scripts/agent-costs.py`, already derives everything
the context axis needs (deduped per-group token totals, cost by model family,
peak per-turn context, outcome, model/effort mix, subagent launches, turns by
phase and by skill) and then throws the structure away by printing tables. A gate
that wanted those numbers would have to re-implement transcript mining, including
the two load-bearing counting rules — dedup by `message.id` (naive summing
over-counts ~2.5x) and subagent attribution to the agreeing issue worktree.

Two things are therefore missing. A machine-readable, schema-versioned cost
record covering both agents as separate strata — today only Claude transcripts
are read at all; the 2,653 Codex rollout files under `~/.codex/sessions` are
untouched. And a tool that pairs before/after records, applies #70's arithmetic,
and emits an artifact whose terminal state a downstream gate can cite.

## Solution

Two deliverables, both stdlib-only Python in `scripts/`, both wired into
`justfile` and `just agent-workflow-tests`.

**1. `agent-costs.py` gains a record projection and a Codex stratum.**
`--format json` emits an `agent-cost-record` document — a pure projection of the
same in-memory group structure the tables already print, so both modes cannot
disagree (D2). `--strata` selects `claude` (default), `codex`, or `both` and is
meaningful only in JSON mode; a new Codex scanner mines `~/.codex/sessions` into
the same group shape. With no new flags the text output is byte-identical to
today's, because the text path's bytes are not touched at all.

**2. `scripts/agent-gate-bundle.py`** reads a *trials manifest* citing emitted
records, resolves each cited run, applies #70's quality veto, three savings gates
and no-regression bound, and emits a content-addressed `agent-gate-bundle`
document whose `state` is exactly one of `approved`, `rejected`, `unmeasured`.
It scores nothing and mines no transcripts: quality, checks and maintenance
arrive as declared evidence; context is computed from the cited records.

### Demo

```sh
just agent-costs --days 7 --strata both --format json > /tmp/before.json
# ... apply the candidate, re-run the same cases ...
just agent-costs --days 1 --strata both --format json > /tmp/after.json
just agent-gate-bundle --trials /tmp/trials.json
```

prints a bundle ending in, for example:

```json
{"state":"unmeasured","bundle_id":"sha256:1f3c…","diagnostics":[
  "TRIALS_INSUFFICIENT $.cases[0].strata.claude: 2 paired trials, 3 required"]}
```

and exits 3. The same manifest run twice yields the same `bundle_id`.

## Decisions

### The cost record

One document per invocation, `schema_version: 1` (integer, pinned — the repo's
established shape in `.agents/project.json`, `agent-evidence.py` and
`artifact_budget.py`), `kind: "agent-cost-record"`.

```
{ "schema_version": 1, "kind": "agent-cost-record",
  "record_id": "sha256:<64 hex>",          # digest of the body, see below
  "generated_at": "<RFC3339 UTC>",         # outside the digest
  "window": {"days": 35, "cutoff_epoch": <int|null>,
             "strata": ["claude","codex"],
             "sources": {"claude": "<path>", "codex": "<path>"}},
  "strata": { "<stratum>": {"cost_basis": "...", "totals": {...}, "runs": [...]} },
  "fleet": {"informative": true, "totals": {<token fields only>}},
  "notes": "<the comparative-telemetry disclaimer>" }
```

A **run** is the reporter's existing `(project, issue)` group (D1). Each run:

```
{ "run_id": "<stratum>:<project>:<issue|none|multi>",
  "stratum": "claude"|"codex", "project": "...", "issue": "120"|null|"*",
  "outcome": "completed"|"interrupted"|"blocked"|"abandoned"|"-",
  "tokens": {"input_total": n, "fresh": n, "cache_create": n, "cache_read": n,
             "output": n, "reasoning": n|null},
  "cost_usd": <float>|null,
  "cost_by_family": {"opus": <float>, "sonnet": <float>, "haiku": <float>}|null,
  "peak_ctx": n,
  "turns": n, "sessions": n, "subagents": n, "skill_loads": n, "repeats": n,
  "agents_killed": n, "interventions": n,
  "models": {...}, "efforts": {...}, "stop_reasons": {...},
  "phase_turns": {...}, "attr_turns": {...},
  "agents_by_type": {...}, "agent_statuses": {...},
  "agent_prompt_bytes": {"n": n, "p50": n, "p90": n, "max": n},
  "agent_result_bytes": {"n": n, "p50": n, "p90": n, "max": n} }
```

`input_total = fresh + cache_create + cache_read` — #70's context axis is "total
observed input tokens per completed run, including cached input with cache
categories reported separately", so the categories stay as sibling keys and
`output` is carried but is diagnostic only. The byte distributions are emitted as
the same percentiles the table prints, not as raw lists (D2: identical numbers,
bounded size).

`notes` carries the reporter's comparative-telemetry disclaimer from a single
module constant that the text footer also prints, so the caveat has one
authoritative home rather than a third copy (D18). The footer's bytes are
unchanged; only their source moves.

`record_id` is `"sha256:" + sha256(canonical(body))` where `body` is the document
minus `record_id` and `generated_at`, canonicalized as
`json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
encoded UTF-8 — the canonical form already used by `resolve-project.py`,
`workflow-state.py` and `diff-scope.py` (D9).

### The Codex stratum

Grouping mirrors Claude's root-session/subagent structure, which the rollout
format already encodes (measured; see below). `session_meta.payload.session_id`
is the root thread and groups every file of one run; `payload.id` identifies the
individual rollout; `thread_source` is `user` (root, `id == session_id`) or
`subagent`, with `source.subagent.thread_spawn` carrying
`parent_thread_id`/`depth`/`agent_nickname`/`agent_role` and
`source.subagent.other` naming helpers such as `guardian`. Subagent files roll up
to their root thread's group unconditionally — Codex has no `aissue-<n>-owner-<n>`
identity, so Claude's proven-owner reattribution has no analogue (D5).

Attribution to a project and issue reuses `repo_root` / `project_name` /
`issue_key` unchanged against `session_meta.payload.cwd`, which carries the
worktree path verbatim (`…/.claude/worktrees/issue-1189-eager-credits-skip`) (D4).

Counting rule (D3), the Codex analogue of Claude's dedup-by-`message.id`:

- Per rollout file, sum `info.last_token_usage` over `event_msg`/`token_count`
  records. **Never** sum or trust `total_token_usage`: it is a running counter
  that a `compacted` record rebases. Measured on 25 recent sessions — the sum
  equalled the final total on all 22 without compaction, and undercounted on all
  3 with it (27,055,920 vs 26,816,837 on the largest).
- `cached_input_tokens` is a subset of `input_tokens`, and
  `reasoning_output_tokens` a subset of `output_tokens`. Adding either on top
  double-counts. Mapping: `input_total = Σ input_tokens`,
  `cache_read = Σ cached_input_tokens`,
  `cache_create = Σ cache_write_input_tokens` (0 throughout the sampled corpus),
  `fresh = input_total − cache_read − cache_create`, `output = Σ output_tokens`,
  `reasoning = Σ reasoning_output_tokens`.
- `peak_ctx = max(input_tokens)` over the group's records, matching Claude's
  "largest single-turn input+cache footprint".
- There is no record-level dedup key: `ordinal` is absent on many records, and
  keying on `(ordinal, timestamp)` over-dedups — of 104 cross-rollout collisions
  measured, 0 carried the same usage value. The dedup unit is the rollout file,
  and each file's records are disjoint by construction, which the sum-equals-total
  check above independently confirms.

`models` and `efforts` come from `turn_context.model` / `turn_context.effort`,
present on every sampled `turn_context` record. `outcome`, `phase_turns`,
`attr_turns`, `agents_by_type`, `agent_statuses`, `stop_reasons`,
`interventions`, `agents_killed`, `skill_loads` and the byte distributions have no
Codex equivalent in this format and are emitted as `null`/empty rather than
guessed (D6) — an absent measurement is not a zero.

`cost_by_family` carries the same `PRICING` arithmetic split by `model_family`,
summed over the same deduplicated messages as `cost_usd`, so
`sum(cost_by_family.values()) == cost_usd` by construction rather than by test
(D32). Model turn counts cannot reconstruct it — token usage differs per turn —
and #120 asks for per-model-family cost explicitly.

`cost_usd` is `null` for the Codex stratum with `cost_basis: "subscription"`;
Claude's stratum keeps `cost_basis: "list-price"` and today's `PRICING` table
(D7); `cost_by_family` is `null` for Codex on the same basis. Inventing GPT list prices would fabricate an authority `PRICING` does not
have, and #70 explicitly bounds subscription-backed runs "by the declared trial
matrix and worst-case invocation count rather than an arbitrary dollar estimate".
Every gate in this design is token-based, so nothing needs the number.

The `fleet` block sums both strata's **token** fields only, and is flagged
`informative: true`. It carries no cost: summing a list-priced stratum with a
subscription-backed one would manufacture a number neither basis supports. The
bundle tool never reads the block at all — #70: fleet aggregates "cannot hide a
failing stratum" (D8).

### The trials manifest

`kind: "agent-gate-trials"`, `schema_version: 1`, supplied with `--trials FILE`.
Unknown keys and duplicate JSON keys are rejected (`agent-evidence.py` precedent).

```
{ "schema_version": 1, "kind": "agent-gate-trials",
  "identity": {
    "bound":  {"commit": {"base": "...", "candidate": "..."},
               "project_contract_version": {"base": "...", "candidate": "..."},
               "shared_platform_version":  {"base": "...", "candidate": "..."}},
    "pinned": {"evaluator_version":       {"base": "...", "candidate": "..."},
               "rubric_version":          {"base": "...", "candidate": "..."},
               "environment_fingerprint": {"base": "...", "candidate": "..."},
               "builds": {"claude": {"agent": {"base": "...", "candidate": "..."},
                                     "model": {"base": "...", "candidate": "..."}},
                          "codex":  { … }}}},
  "expansion": {"expanded": false, "checkpoint_ref": null},
  "cases": [
    { "case_id": "cold-resolution",
      "case_class": "cold-resolution"|"routine-issue"|"fuzzy-design"|
                    "review-ship"|"repo-specific",
      "strata": { "claude": {
          "base":      [{"record": "<path>", "run_id": "...", "record_id": "sha256:…"}, …],
          "candidate": [ … ],
          "quality": {"critical_all_pass": true,
                      "noncritical_median": {"base": 87.0, "candidate": 85.5}},
          "checks":  {"static_fallback_checks": {"base": 3, "candidate": 0},
                      "discovery_preflight_ops": {"base": 40, "candidate": 25}},
          "maintenance": {"manual_update_sites": {"base": 8, "candidate": 3},
                          "new_hand_authored_projections": 0} },
        "codex": { … } } } ] }
```

`checks` and `maintenance` are optional; `quality` and both strata are not (D11).
A trial is one invocation of one case, so #70's "per invocation" and its
"three-trial median" are the same quantity and no division is introduced (D12).

Every field under `identity.bound` is recorded and may differ between sides — the
candidate commit differing from the base is the point. Every field under
`identity.pinned` must be *equal* on both sides, and any inequality is
`unmeasured`: #70 holds that changed fixtures, deployed definitions, model strata
or evaluator definitions invalidate the old baseline (D19).

There is no per-case `required` flag. #70's no-regression bound speaks of
"required cases", and every case in a manifest is one — `case_class` is a closed
enum over #70's required corpus. A flag able to exempt a case from the bound
would be exactly the input that turns a `rejected` bundle into an `approved` one
(D20). For the same reason the four core classes (`cold-resolution`,
`routine-issue`, `fuzzy-design`, `review-ship`) must each appear at least once;
`repo-specific` is the conditional fifth and stays optional.

Trials are *paired*: a case/stratum's `base` and `candidate` arrays must be the
same length, at least 3, and are aligned by index.

The tool loads each cited record file, recomputes its `record_id`, and extracts
the run by `run_id`. This makes "reproducible from the same input records"
literal: the bundle binds the extracted measurements, not the file paths, so the
same records reproduce the same bundle from any location — and an unreadable,
tampered, or missing record is a real, tested path to `unmeasured`.

### Gate arithmetic

Per case and per stratum, from the resolved trials:
`context_median(side) = median(input_total over that side's trials)`.

- **Quality veto.** Fails when `critical_all_pass` is false, or when
  `base.noncritical_median − candidate.noncritical_median > 5` on the 100-point
  rubric. Applied one-sided: #70 phrases it as "within 5 points of baseline", but
  the veto exists to catch regression and a candidate that scores *higher* is not
  a failure (D13). Any failing case in any stratum vetoes the whole bundle.
- **Context saving.** Fires when at least one case in the stratum cuts its median
  by ≥10% **or** ≥500 tokens, **and** no case in that stratum rises by *both*
  >2% **and** >128 tokens. #70's "affected case" needs no separate flag: a
  manifest declares exactly the corpus the candidate affects. The no-regression
  bound is conjunctive — a rise clearing only one of the two is not a regression.
- **Checks saving.** Fires when some case in the stratum has
  `static_fallback_checks.candidate == 0` with `base > 0` (the check disappeared
  from every affected invocation) **and** `discovery_preflight_ops` down ≥20%.
  Live runtime-truth checks are ineligible by construction: the manifest has no
  field for them.
- **Maintenance saving.** Fires when some case in the stratum cut
  `manual_update_sites` by ≥50% **and** by ≥1 site, with
  `new_hand_authored_projections == 0`.
- **Cross-stratum.** A saving qualifies only when the *other* stratum shows no
  material context regression, i.e. no case there breaches the same conjunctive
  bound.
- **Disagreement.** Pairing base[i] with candidate[i], a case whose pairs
  *straddle* a gate — at least one pair qualifying as a context saving while at
  least one other breaches the no-regression bound — is `unmeasured`. #70 sends a
  disagreeing case to ten pairs after a human checkpoint and, if it still crosses
  both sides, calls the result `unmeasured`; since this tool does not gate the
  human, straddling is `unmeasured` at three pairs and at ten alike, and the
  `expansion` block only records which of the two was run (D21).

Verdict, computed by one total pure function of the resolved evidence:

1. `unmeasured` if any required evidence is missing, unresolvable, inconsistent
   or invalid — identity field absent or empty; a cited record that will not
   load, fails its `record_id` recomputation, or lacks the cited `run_id`; fewer
   than three trials on a side, or unequal `base`/`candidate` lengths; a stratum
   absent from a case; one of the four core `case_class` values absent from the
   manifest; `quality` absent; an `identity.pinned` field differing between
   sides; or a case whose pairs straddle a gate (D10, D11, D19, D20, D21).
2. else `rejected` if the quality veto fails;
3. else `approved` if ≥1 savings gate fires under the cross-stratum condition;
4. else `rejected`.

Ordering matters and is asserted: `unmeasured` dominates, so an incomplete bundle
can never present as a measured rejection or an approval.

### The bundle document and the no-upgrade invariant

```
{ "schema_version": 1, "kind": "agent-gate-bundle",
  "bundle_id": "sha256:<64 hex>", "generated_at": "<RFC3339 UTC>",
  "gate_contract": "issue-70", "gate_version": 1,
  "state": "approved"|"rejected"|"unmeasured",
  "identity": { … copied from the manifest … },
  "expansion": { … },
  "evidence": {"cases": [ {case_id, case_class,
                           strata: {<s>: {context: {base_median, candidate_median,
                                                    delta_tokens, delta_pct,
                                                    trials: [{run_id, record_id,
                                                              input_total, peak_ctx}]},
                                          quality, checks, maintenance}}} ]},
  "gates": {"quality": {...}, "context": {...}, "checks": {...},
            "maintenance": {...}, "cross_stratum": {...}},
  "override": null | {"reason": "...", "authorized_by": "...",
                      "authorized_at": "...", "scope": "further-experimentation"},
  "diagnostics": ["CODE $.json.path: message", …] }
```

`bundle_id` is the same canonical-JSON sha256 as `record_id`, over the document
minus `bundle_id` and `generated_at` — every other field, `state` included, is
inside the digest, so a differing verdict is a differing bundle (D9).

The no-upgrade invariant is enforced twice, per the-bar's defense-in-depth (D14):

- `decide(evidence) -> state` takes only the resolved evidence structure.
  `--override` is parsed into the `override` block, which is not in `decide`'s
  parameter list and has a closed four-key schema with no state-bearing field;
  its only documented power is #70's "authorize further experimentation".
- After assembly, the emitter re-runs `decide` on the bundle's own `evidence`
  and refuses to write if the result differs from `state`.

Diagnostics use `agent-evidence.py`'s vocabulary — sorted `CODE $.path: message`
strings — and are carried *inside* the bundle so an `unmeasured` artifact says
why, rather than only appearing on stderr. They are empty for `approved` and
`rejected`, whose reasons live in `gates`; `unmeasured` is the only state that
populates them.

The bundle's thresholds are not new policy in #97's sense: #97 forbids new
analysis and thresholds in the *telemetry* half, and every constant here is
transcribed from #70's resolution, which is why they sit behind one
`gate_version`.

### CLI surface

`agent-costs.py` adds `--format text|json` (default `text`), `--strata
claude|codex|both` (default `claude`) and `--codex-sessions DIR` (default
`~/.codex/sessions`). `--strata` is meaningful only with `--format json`; any
other value in text mode is a usage error (exit 2). Text mode therefore has
exactly today's scan set and exactly today's printer, which makes #97's
byte-identity guarantee structural rather than tested-by-hope (D15). `--format
json` writes only the record document, to stdout. The Codex scan reuses
`scan_paths`, inheriting the existing process pool and its all-or-nothing
sequential fallback.

`agent-gate-bundle.py` takes `--trials FILE` and
`--override REASON --override-by WHO`. Neither tool has an `--out`: each writes
one document to stdout and the shell owns redirection (D22). Exit codes follow `artifact_budget`'s
convention: **0** = bundle emitted, `approved`; **3** = bundle emitted,
`rejected` or `unmeasured` (the `state` field disambiguates); **2** = tool
failure — unreadable or malformed manifest, usage error (D16). A gate can branch
on the exit code without parsing, and a non-zero exit is never silently an
approval. `--override` changes neither the state nor the exit code.

`justfile` gains `agent-gate-bundle *args`; `just agent-workflow-tests` gains
`tests/test_agent_gate_bundle.py`.

### Storage

Both documents go to stdout; where a caller redirects them, their homes are
`$TMPDIR` and `.agents/runtime/`, both already ignored, so no new `.gitignore`
entry is needed and per #72 neither class is ever tracked (D17).

## Test seams

Existing, reused as-is — the suite already loads the hyphenated script through
`importlib.util.spec_from_file_location`:

- `scan_file(path)` — one Claude transcript in, one dict out.
- `build_groups(sessions, per_session, project_filter)` — the shared derivation.
- `main(argv, executor_factory=...)` with captured stdout — CLI contract.

Added, and the only seams implementers may test at:

- `build_record(groups_by_stratum, window)` — pure projection to the record
  document. Covers the `input_total` composition, the null-vs-zero rule, the
  `fleet.informative` flag and `record_id` stability.
- `scan_codex_file(path)` — one rollout file in, one dict out. Covers the
  sum-of-`last_token_usage` rule against a fixture containing a `compacted`
  record whose `total_token_usage` disagrees, the cached/reasoning subset trap,
  `peak_ctx`, and root-vs-subagent classification.
- `resolve_trials(manifest, loader)` — manifest plus record loader to resolved
  evidence or diagnostics.
- `decide(evidence) -> state` — the gate arithmetic in isolation, including each
  threshold's boundary (exactly 10%, exactly 500 tokens, exactly 5 quality
  points, exactly 2%/128 tokens, exactly 20%, exactly 50%) and the ordering that
  makes `unmeasured` dominate.
- `main(argv)` for `agent-gate-bundle.py` — exit codes and emitted bytes.

Two named adversarial tests, in the spirit of
`tests/test_claude_permission_guard.py`'s table:

- **byte-identity**: a fixture tree scanned with no new flags and with
  `--format text --strata claude` produces byte-identical stdout, and the JSON
  mode's numbers equal the ones the table printed for the same window.
- **no-upgrade**: a table with one row per manifest surface — override block,
  unknown keys, a manifest-declared `state`, a declared `bundle_id`, an empty
  `cases` list, absent strata, a missing core `case_class`, a straddling case, a
  mismatched `identity.pinned` field — asserting that none of them yields
  `approved` from evidence that does not earn it.

Fixtures are shaped like real transcripts (a rollout fixture is copied down from
a real `session_meta`/`turn_context`/`token_count` sequence), per the-bar's
"fixtures shaped like the values production actually carries".

## Out of scope

- The evaluator and the rubric. The bundle consumes declared quality scores; it
  never scores anything, and it has no model call.
- Running the paired trials. Nothing here launches an agent.
- The human checkpoint that expands three pairs to ten. The manifest's
  `expansion` block *records* that an expansion happened; the tool does not gate
  a human and does not decide when to expand.
- Age-based freshness. The bundle binds evidence timestamps so #71 can judge
  freshness; `unmeasured` here means missing, unresolvable, inconsistent or
  invalid, not old.
- Cost figures for the Codex stratum, and any GPT pricing table.
- Promotion (#68) and the Stage-4 cutover (#71). Their consumption of a bundle is
  designed for, not implemented.
- Any commit or storage policy beyond honoring #72's ignore posture.
- Codex outcome/phase/skill telemetry that the rollout format does not carry.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A record "run" is the reporter's existing `(project, issue)` group, one row per stratum; a bundle "trial" is one such run cited from one record document | #97 asks for "per-group token totals"; dedup and subagent attribution already resolve at that key in `build_groups` | A single root session as the unit — splits one issue's work across rows and puts the two counting rules back in the caller's hands |
| D2 | The JSON record is a pure projection of the same in-memory group structure the tables print; the text printer's output bytes are unchanged, and byte distributions are emitted as the printed percentiles | #97: byte-identical default output, both modes identical numbers, rules applied once and shared | A separate JSON derivation path — two derivations that must be kept agreeing by test rather than by construction |
| D3 | Codex tokens are `Σ last_token_usage` per rollout file; `total_token_usage` is never summed or trusted | Measured: sum equals the final total on 22/25 sampled sessions and undercounts on all 3 containing a `compacted` record, which rebases the running counter | Reading the final `total_token_usage` — silently loses every pre-compaction turn on exactly the longest runs |
| D4 | Codex issue attribution reuses `repo_root`/`project_name`/`issue_key` against `session_meta.payload.cwd` | The cwd carries `…/.claude/worktrees/issue-<n>-<slug>` verbatim; the existing regexes parse it unchanged | A Codex-specific attribution rule — a second authority for one policy, against the-bar's DRY |
| D5 | Codex subagent rollouts roll up to their root thread's group unconditionally | `thread_source`/`source.subagent.thread_spawn.parent_thread_id` give the parent directly; Codex has no `aissue-<n>-owner-<n>` identity for Claude's proven-owner reattribution to key off | Porting the owner-attribution rule — it would have to guess an owner from a cwd alone, the exact ambiguity the Claude rule refuses |
| D6 | Codex telemetry the rollout format does not carry (outcome, phases, skill attribution, nudges, agent statuses) is `null`/empty, never 0 | the-bar, truthful terminal states: an absent measurement is not a zero | Emitting 0 — makes a fleet aggregate read as measured when nothing was measured |
| D7 | `cost_usd` is `null` for Codex with `cost_basis: "subscription"`; Claude keeps `list-price` and today's `PRICING` | The sampled corpus is `plan_type: "pro"`; #70 bounds subscription-backed runs by the trial matrix "rather than an arbitrary dollar estimate"; every gate here is token-based | Adding GPT list prices to `PRICING` — invents an authority the table does not have and that nothing consumes |
| D8 | Strata are separate top-level keys; a `fleet` block exists but carries token fields only, is flagged `informative: true`, and is never read by the bundle tool | #70: "fleet aggregates are informative only and cannot hide a failing stratum" | Emitting one merged total, or a fleet cost mixing a list-priced stratum with a subscription-backed one — the first is the hiding #70 forbids, the second manufactures a number neither basis supports |
| D9 | Both documents are content-addressed as `sha256` over canonical JSON (`sort_keys`, `(",", ":")`, `ensure_ascii`, UTF-8) of the document minus its own id and `generated_at`; every other field, `state` included, is inside | Canonical form already used by `resolve-project.py`, `workflow-state.py`, `diff-scope.py`; `content_sha256` naming precedent in `artifact_budget.py`; #120 AC "reproducible from the same input records" | Including `generated_at` — the same records would never reproduce the same bundle |
| D10 | The bundle loads cited record files, recomputes each `record_id`, and extracts the run by `run_id`, rather than trusting measurements inlined in the manifest | #120 AC phrases reproducibility over "the same input records"; it also makes missing/tampered evidence a real, tested route to `unmeasured` | Inlined measurements with the digest as a decorative provenance string — nothing would ever verify it |
| D11 | Quality and both strata are required evidence (absence ⇒ `unmeasured`); `checks` and `maintenance` are optional declarations whose absence only means those gates cannot fire | #70: quality is a hard veto that must be *measured*, "each [stratum] must satisfy quality", and a saving in one qualifies only when the other has no material regression — which presupposes measuring the other | Treating an absent axis as a passing gate, or allowing a single-stratum bundle — both let an unmeasured candidate reach `approved` |
| D12 | A trial is one invocation of one case, so "per invocation" and "three-trial median" are the same quantity; no per-turn division is introduced | #70 states the context gate as a three-trial median per case | Dividing by the run's `turns` — invents a denominator #70 never names and makes the threshold mean something else |
| D13 | The 5-point quality bound is applied one-sided: only `base − candidate > 5` fails | #70's veto exists to reject "token reductions that make agents less reliable"; a candidate scoring higher is not a reliability regression | Symmetric `abs(delta) > 5` — vetoes a quality improvement, which no reading of #70 intends |
| D14 | `decide()` takes only the resolved evidence; `--override` writes a closed four-key block with no state field and is not a parameter of `decide`, and the emitter re-runs `decide` on the written evidence before writing | #70: an override "may authorize further experimentation but cannot relabel a rejected or unmeasured bundle as approved"; the-bar, defense in depth | A single check inside `decide` — one refactor away from the override becoming reachable |
| D15 | Codex scanning is opt-in behind `--strata`, defaulting to `claude`, and `--strata` is meaningful only with `--format json` — any other value in text mode is a usage error | #97's byte-identity clause; a default Codex scan would also add 2,653 files to every routine run | Always scanning both, or printing a Codex text section — the first breaks the default output and the default cost of the tool, the second adds a printing surface nobody asked for and puts byte-identity back at risk |
| D16 | Exit 0 = `approved`, 3 = `rejected` or `unmeasured`, 2 = tool failure | `artifact_budget`'s established 0/3/2 split between success, a measured failing outcome, and tool failure | A distinct exit code per terminal state — invents a fourth code with no precedent; the `state` field already disambiguates |
| D17 | The bundle tool lives at `scripts/agent-gate-bundle.py` beside the reporter, not under `home/common/agent-skills/scripts/`; both documents default to stdout and add no `.gitignore` entry | `scripts/` holds repo-local instruments wired by the `justfile`, while `agent-skills/scripts/` holds the portable cross-project platform exported to `~/.agents/bin`; #72 keeps runtime artifacts untracked and `$TMPDIR`/`.agents/runtime/` are already ignored | Shipping it as a platform script now — the larger, less reversible move, made before any cross-project consumer exists |
| D18 | The comparative-telemetry disclaimer becomes one module constant that both the text footer and the record's `notes` read; the footer's bytes are unchanged | the-bar, DRY on knowledge: one authoritative home per contract, and the caveat is a contract about how the numbers may be read | A second literal in the JSON emitter — a third copy of a caveat that must change together |
| D19 | Manifest identity splits into `bound` (recorded, may differ between sides) and `pinned` (must be equal on both sides; inequality ⇒ `unmeasured`) | #70: changed fixtures, deployed definitions, model strata or evaluator definitions invalidate the old baseline, and "historical prose and stale or incomplete runs cannot certify a candidate" | One flat identity block declared once — nothing can then disagree, so the invalidation rule has nothing to check and silently never fires |
| D20 | No per-case `required` flag; every case in a manifest is a required case, and the four core `case_class` values must each appear at least once (`repo-specific` stays conditional) | #70's required corpus is exactly those four classes plus a conditional fifth, and `case_class` is a closed enum over them | A `required: false` opt-out — the cheapest input for turning a `rejected` bundle into an `approved` one, which AC3 forbids |
| D21 | A case whose index-paired trials straddle a gate (one pair saving, another breaching the no-regression bound) is `unmeasured` at three pairs and at ten alike; `expansion` records which was run and decides nothing | #70: a disagreeing case expands after a human checkpoint and, if it still crosses both sides of a gate, "the result is `unmeasured`"; gating the human is out of scope | Averaging the disagreement away into a median verdict — reports a decided gate where #70 says the evidence has not decided |
| D22 | Neither tool takes `--out`; each writes exactly one document to stdout and the shell owns redirection | the-bar, YAGNI and token economy — every parameter is a failure site; redirection is already the shell's job | An `--out PATH` on both — a second write path, a second set of I/O failures, and nothing gained over `>` |
| D23 | No `docs/` glossary, context map or ADR is created; the spec and `CLAUDE.md` carry the vocabulary | `.claude/specs/2026-08-08-docs-structure-adr-design.md` puts "nix-config's own repo layout (it has no `docs/`; it hosts the spec)" explicitly out of scope, and none of this design's decisions meets all three ADR criteria | Standing up the standard `docs/areas/` tree here — reverses a settled decision as a side effect of an unrelated slice |
| D24 | Codex grouping — subagent roll-up to the root thread, project/issue attribution, and the per-run counters — is exercised only through `scan_codex_file` and the existing `main(argv)` seam; no `build_codex_groups` test seam is added | The spec's "Added, and the only seams implementers may test at" list is closed, and grouping is fully observable in the emitted record | A directly tested grouping helper — widens the agreed seam set without covering anything `main` does not already reach |
| D25 | The canonical-JSON sha256 helper is written independently in each of the two scripts rather than extracted into a shared importable module | `scripts/` holds standalone stdlib scripts with no shared package, and D9's own precedent (`resolve-project.py`, `workflow-state.py`, `diff-scope.py`) is three independent copies of exactly this function | A new `scripts/_canonical.py` — introduces an import surface `scripts/` has never had, and a second file both tools must find at runtime, for eight lines |
| D26 | The Codex scan honors the existing `--days` window by rollout-file mtime, mirroring `find_sessions`, so `window.days` and `window.cutoff_epoch` describe both strata | The record carries one `window` block over all strata; a stratum outside it would make that block false | Scanning every Codex session regardless of `--days` — the window block would then misdescribe the codex stratum, and every JSON run would read all 2,653 files |
| D27 | Codex per-run counters are `turns` = count of `token_count` records carrying `info.last_token_usage`, `sessions` = count of root (`thread_source == "user"`) rollout files in the group, `subagents` = count of subagent rollout files; `skill_loads` and `repeats` are `null` (D6) | One `last_token_usage` record is emitted per model turn, the same unit Claude's `turns` counts; D6 forbids substituting 0 for an absent measurement | Counting `turn_context` records — a resumed or compacted thread re-emits turn context without a model turn, so the count would drift from Claude's meaning of `turns` |
| D28 | `strata.<s>.runs` is emitted sorted by `run_id` ascending, and every counter/mapping value is emitted as a plain `dict` | D9 requires the same records to reproduce the same digest, but `build_groups` returns a dict whose order follows filesystem iteration; `sort_keys` canonicalizes mappings and not list order | Emitting runs in the table's cost-descending order — makes `record_id` depend on cost ties and scan order, breaking the reproducibility AC |
| D29 | JSON-mode CLI semantics: an empty scan emits a valid record with empty `runs` instead of the text path's `sys.exit`; `--project` filters both strata; `--top` is a text-only display cap and is ignored; `--artifacts` in JSON mode is a usage error (exit 2) | The record is the gate's input, and a gate must be able to tell "measured, nothing matched" from a crashed tool; the record carries no artifact block and no display cap, so those two flags have nothing to project | Reusing the text path's `sys.exit` on an empty window — an empty stratum would look identical to a broken tool, and a bundle citing it would report a tool failure rather than `unmeasured` |
| D30 | The bundle's `evidence.…context.trials` is an object `{"base": [...], "candidate": [...]}` rather than the single flat list the design sketch drew, and the resolved evidence carries no derived `pairs` member — index pairing is recomputed by `decide` | The gate arithmetic is per side and per index pair (D12, D21); a flat list would force the consumer to re-split it, and a stored `pairs` member would be a second representation of the same numbers that could disagree with the trials it came from | Keeping the flat list and storing derived pairs beside it — two derivations of one fact, the shape D2 rejects for the record |
| D31 | Manifest *document* faults — unreadable file, invalid JSON, duplicate JSON keys, wrong `kind` or `schema_version`, an unknown key, a wrong JSON type, a `case_class` outside the enum — exit 2 with diagnostics on stderr and no bundle; *evidence* faults — the nine conditions the verdict list names — produce an `unmeasured` bundle at exit 3 | D16 splits "tool failure — unreadable or malformed manifest" from a measured terminal state, and the verdict list enumerates exactly the evidence faults; `agent-evidence.py` already rejects unknown and duplicate keys as document faults | Routing unknown keys to `unmeasured` — an `unmeasured` bundle would then be emitted for a manifest the tool never understood, and its `identity` block would be copied from unvalidated input |
| D32 | The record carries `cost_by_family` (a `model_family` → USD mapping) on every run and stratum total, derived in `scan_file` beside the existing `cost` accumulator and merged through `COUNTER_FIELDS`; `null` for Codex | #120 names per-model-family cost as required telemetry, and this spec's Problem section already claims `agent-costs.py` derives "cost by model family"; the aggregate `cost_usd` plus `models` turn counts cannot reconstruct it because token usage differs per turn | Emitting only aggregate cost and letting a consumer re-derive families from turn counts — arithmetically impossible, and it would need a second transcript derivation (D2 forbids) |
| D33 | Text byte-identity is proven against a committed golden stdout fixture captured from the pre-change script at the base commit, not by comparing two post-change invocations | A test that runs the new implementation twice drifts with it; #97's clause is about the *old* bytes, so the oracle must predate the change | Comparing bare flags to explicit defaults only — both paths can regress together and the test stays green |
| D34 | `resolve_trials` strictly validates each cited record before extraction — `schema_version`, `kind`, non-empty `generated_at`, stratum/run shape, field types, non-negative integer tokens (rejecting `bool`), finite rubric values in `[0, 100]` — and reports faults as sorted `RECORD_INVALID`/`FIELD_*` diagnostics | Task 3 promises bad evidence never raises while doing unchecked nested indexing; a wrong-kind document with a recomputed digest would otherwise certify, and a missing nested field would raise `KeyError` | Trusting the digest alone as the record's contract — the digest proves self-consistency, not that the document is a cost record of the right shape |
| D35 | Each resolved trial carries the cited record's `generated_at`, so the bundle digest covers the measurement time | This spec already states the bundle binds evidence timestamps so #71 can judge freshness; the record digest deliberately excludes `generated_at`, so nothing else would carry it | Leaving freshness to the record files on disk — the bundle is the citable artifact and would bind no time at all |
| D36 | Paired-trial cardinality is exact, not a minimum: exactly 3 per side when `expansion.expanded` is `false` (which then requires `checkpoint_ref: null`), and 3 or 10 when it is `true` with a non-empty `checkpoint_ref`; anything else is `unmeasured` | #70 prescribes three paired trials and ten only after a recorded human checkpoint; a floor of three lets four-through-nine selectively retained pairs, or ten with no checkpoint, approve | "At least 3" — the cheapest way to buy an approval by dropping the pairs that disagree, which AC3 forbids |
| D37 | Quality evidence gains a required declared `evaluator_stability` of `"stable"` or `"unstable"`; `"unstable"` is an evidence fault resolving to `unmeasured`, while its absence is a manifest document fault (exit 2) under D31 | #70 makes continued evaluator instability an `unmeasured` outcome, and the tool declares rather than scores; D31 already routes absent required manifest keys to exit 2 | Resolving an absent key to `unmeasured` — reverses D31's document/evidence split for one field, and would emit a bundle copying `identity` from a manifest the tool never validated |
| D38 | The override's `authorized_at` is a required declared input (`--override-at`, RFC3339 UTC), never a clock sample; `build_override` reads no clock | The override block is inside `bundle_id`, and this spec promises the same manifest run twice yields the same bundle; `generated_at` is outside the digest precisely because it is a clock sample, so a hashed clock sample contradicts it | Excluding `authorized_at` from the digest — D9 keeps every non-id, non-`generated_at` field inside, and an unbound authorization time is exactly the provenance the block exists to record |
| D39 | "Completed run" is a trusted manifest precondition, not bundle-validity evidence: each resolved trial carries the cited run's `outcome` verbatim (`null` for Codex) so the bundle binds it, but no gate reads it | Codex's rollout format carries no outcome at all (D6, and this spec's non-goals), so requiring completedness as evidence would make every Codex trial permanently unresolvable; carrying it is the smaller, reversible half | Rejecting or unmeasuring trials whose `outcome != "completed"` — un-gates nothing on the Claude side and hard-blocks the Codex stratum that D11 requires |
| D40 | Task 2 also rewrites `agent-costs.py`'s module docstring and the `justfile` `agent-costs` recipe comment, both of which describe Claude transcripts only | Both go false the moment the Codex stratum and `--format json` land; the-bar keeps one truthful description per surface, and neither edit touches stdout so D2/D15 byte-identity is untouched | Leaving them for a follow-up — the two sentences an operator reads first would describe a tool that no longer exists |
| D41 | `scan_paths` takes `scanner=None` and binds `scanner = scan_file` in the body, not `scanner=scan_file` in the signature | Python evaluates a default once at `def` time, so a captured default would bypass `mock.patch.object(agent_costs, "scan_file", ...)` and silently void the two existing process-pool fallback tests, which stay as the regression gate | `scanner=scan_file` in the signature — reads better and disables the only tests that cover the sequential fallback |
