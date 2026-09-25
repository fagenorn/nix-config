# Agent-Cost Telemetry and the #70 Evidence Bundle — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Give `scripts/agent-costs.py` a schema-versioned, content-addressed
`agent-cost-record` JSON projection covering a Claude and a Codex stratum, and add
`scripts/agent-gate-bundle.py`, which pairs cited records into #70's gate arithmetic and
emits an `agent-gate-bundle` whose terminal state a downstream gate can cite.

**Architecture:** `agent-costs.py` keeps exactly one derivation. The existing scan →
`build_groups` pipeline is unchanged; a new Codex scanner produces the *same* group shape
from `~/.codex/sessions` rollout files, and a new pure `build_record` projects a mapping of
stratum name to groups into the record document. The text printer is not touched, so #97's
byte-identity holds structurally (D2, D15). `agent-gate-bundle.py` is a separate standalone
script: it loads a trials manifest, resolves each cited record by recomputing its digest and
extracting the named run, and hands the resolved evidence to one total pure `decide` function.
Both documents are content-addressed over canonical JSON and written to stdout only (D9, D22).

**Tech stack:** Python 3 standard library only (`argparse`, `json`, `hashlib`, `statistics`,
`pathlib`, `datetime`, `concurrent.futures`), `unittest` with fixtures built in temp dirs, Just.

## Global Constraints

- The authoritative design is `.claude/specs/2026-09-02-agent-cost-telemetry-design.md`. Cite
  D1–D31 by ID; never restate their rationale in code, tests, docstrings or commits.
- Python standard library only. No new dependency, no new Nix change, no `docs/` tree, no ADR
  (D23), no new `.gitignore` entry (D17).
- `schema_version` is the integer `1` on all three documents. `kind` is exactly
  `"agent-cost-record"`, `"agent-gate-trials"`, `"agent-gate-bundle"`. The bundle also carries
  `"gate_contract": "issue-70"` and `"gate_version": 1`.
- Canonical form is `json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)`
  encoded UTF-8; a document id is `"sha256:" + hashlib.sha256(canonical).hexdigest()` over the
  document minus its own id field and `generated_at`. Every other field is inside the digest (D9).
- `generated_at` is RFC3339 UTC, `datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")`.
- An absent measurement is emitted as `null` (or `{}` / `[]` for a mapping or list), never `0` (D6).
- `input_total = fresh + cache_create + cache_read`, and the three categories stay as sibling keys.
- Every run and stratum total carries `cost_by_family` beside `cost_usd`; both are `null` for the
  Codex stratum, and `fleet` carries neither (D32, D7, D8).
- Nothing in a cited record is read before it is type-checked, and each resolved trial carries the
  record's `generated_at` and the run's `outcome` (D34, D35, D39).
- Quality evidence carries a declared `evaluator_stability`; `"unstable"` is `unmeasured` (D37).
- Every field inside a document digest is deterministic from declared inputs — the override's
  `authorized_at` is `--override-at`, never a clock sample (D38).
- Text mode's stdout bytes are byte-identical to today's for every invocation that passes no new
  flag, and `--strata` with any value other than `claude` in text mode is a usage error, exit 2 (D15).
- Gate thresholds, transcribed from #70 and frozen behind `gate_version: 1`: context saving
  `≥10%` **or** `≥500` tokens; no-regression breach `>2%` **and** `>128` tokens (conjunctive);
  quality veto `base − candidate > 5` one-sided (D13); checks saving
  `static_fallback_checks.candidate == 0` with `base > 0` **and** `discovery_preflight_ops` down
  `≥20%`; maintenance saving `manual_update_sites` down `≥50%` **and** `≥1` site with
  `new_hand_authored_projections == 0`; paired-trial cardinality is **exact** — 3 per side, or 3
  or 10 when `expansion.expanded` is `true` with a non-empty `checkpoint_ref` (D36).
- `case_class` is the closed enum `cold-resolution`, `routine-issue`, `fuzzy-design`,
  `review-ship`, `repo-specific`. The first four must each appear at least once; the fifth is
  optional. There is no per-case `required` flag (D20).
- `agent-gate-bundle.py` exit codes: **0** `approved`, **3** `rejected` or `unmeasured`, **2**
  tool failure (unreadable/malformed manifest, argparse usage error) (D16, D31).
- Diagnostics are sorted strings of the form `CODE $.json.path: message`, carried inside the
  bundle. They are empty for `approved` and `rejected`; only `unmeasured` populates them.
- `decide` takes only the resolved evidence structure. `override` is not one of its parameters
  and has no state-bearing field (D14).
- Sign commits normally; never pass `-c commit.gpgsign=false` or `--no-gpg-sign`. Append
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` to every commit message.

## Test seams

Existing, reused as-is — the suite loads the hyphenated script through
`importlib.util.spec_from_file_location`:

- `scan_file(path)` — one Claude transcript in, one dict out.
- `build_groups(sessions, per_session, project_filter)` — the shared derivation.
- `main(argv, executor_factory=...)` with captured stdout — the `agent-costs.py` CLI contract.

Added, and the only seams implementers may test at:

- `build_record(groups_by_stratum, window)` — pure projection to the record document.
- `scan_codex_file(path)` — one rollout file in, one dict out.
- `resolve_trials(manifest, loader)` — manifest plus record loader to resolved evidence.
- `decide(evidence) -> state` — the gate arithmetic in isolation.
- `main(argv)` for `agent-gate-bundle.py` — exit codes and emitted bytes.

Codex grouping is observed through `build_record` and `main`, not through a grouping helper of
its own (D24). Fixtures are shaped like real transcripts and real rollouts.

## Task index

Task 1 — Codex rollout scanner and its counting rule — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-1.md](2026-09-02-agent-cost-telemetry.tasks/task-1.md)

Task 2 — Record projection, JSON/strata CLI, and the byte-identity guard — `scripts/agent-costs.py`, `tests/test_agent_costs.py` — full — [task-2.md](2026-09-02-agent-cost-telemetry.tasks/task-2.md)

Task 3 — Trials manifest loading and `resolve_trials` — `scripts/agent-gate-bundle.py`, `tests/test_agent_gate_bundle.py`, `justfile` — full — [task-3.md](2026-09-02-agent-cost-telemetry.tasks/task-3.md)

Task 4 — `decide`: gate arithmetic and verdict ordering — `scripts/agent-gate-bundle.py`, `tests/test_agent_gate_bundle.py` — full — [task-4.md](2026-09-02-agent-cost-telemetry.tasks/task-4.md)

Task 5 — Bundle assembly, `--override`, exit codes, and the no-upgrade table — `scripts/agent-gate-bundle.py`, `tests/test_agent_gate_bundle.py`, `justfile` — full — [task-5.md](2026-09-02-agent-cost-telemetry.tasks/task-5.md)

## Decisions

- D1 fixes the `(project, issue)` run unit and the trial-cites-a-run relation, used by every task.
- D2, D15 and D18 fix the pure-projection rule, the opt-in `--strata` default and the single
  disclaimer constant, used by Task 2.
- D3, D4, D5, D6, D7, D26 and D27 fix the Codex counting rule, attribution, subagent roll-up,
  null-vs-zero, subscription cost basis, the mtime window and the per-run counters — Task 1,
  observed in Task 2.
- D8 fixes the separate strata and the informative `fleet` block, used by Task 2.
- D9, D25 and D28 fix content addressing, the per-script digest helper and run ordering, used by
  Tasks 2 and 5.
- D10, D11, D19, D20 and D21 fix required evidence, the identity split, the absent `required`
  flag and the straddling rule, used by Task 3 and asserted in Task 5.
- D12 and D13 fix the trial unit and the one-sided quality bound, used by Task 4.
- D14 fixes the two-layer no-upgrade invariant, used by Task 5.
- D16, D17 and D22 fix exit codes, the script's home and stdout-only output, used by Tasks 3 and 5.
- D23 fixes the absence of any `docs/` artifact, binding on all five tasks.
- D24 fixes the closed seam set, binding on Tasks 1 and 2.
- D25 fixes the per-script digest helper, used by Tasks 2 and 3.
- D26 and D27 fix the Codex window and per-run counters, used by Tasks 1 and 2.
- D28 fixes run ordering for a stable digest, used by Task 2.
- D29 fixes JSON-mode CLI semantics, used by Task 2.
- D30 fixes the `trials` object shape the evidence carries, used by Tasks 3–5.
- D31 fixes the document-fault/evidence-fault split behind exit 2 versus `unmeasured`, used by
  Tasks 3 and 5.
- D32 fixes per-model-family cost on every run and stratum total, used by Task 2.
- D33 fixes the pre-change golden stdout oracle for #97's byte-identity clause, used by Task 2.
- D34 fixes strict pre-extraction record and numeric validation, used by Tasks 3–5.
- D35 fixes the evidence timestamp carried into every resolved trial, used by Tasks 3 and 5.
- D36 fixes exact paired-trial cardinality and expansion consistency, used by Tasks 3–5.
- D37 fixes the declared `evaluator_stability` and its `unmeasured` path, used by Tasks 3–5.
- D38 fixes the override's declared `authorized_at`, used by Task 5.
- D39 fixes "completed run" as a trusted precondition with `outcome` bound but ungated, used by
  Tasks 3 and 4.
- D40 fixes the operator-facing docstring and recipe-comment updates, used by Task 2.
- D41 fixes `scan_paths(..., scanner=None)` so the existing patch-based fallback tests still
  bind, used by Task 2.

## Standards review provenance

A standards review of this plan at `8db514c` was run by **Codex** in an isolated, read-only
runtime against base SHA `5a7aa7cfc83d356f8c3b910c4560cafd27840b1c`, with **no focus configured**
and **no fallback used**. Eleven findings were raised — eight blocking, two should-fix, one
discussion — and every one was verified against the live worktree before disposition:
**11 accepted** (the discussion item resolved by autonomous default), **0 rejected**,
**0 deferred**. The resulting decisions are ledger rows **D32–D41** in the design spec; the raw reviewer transcript is not
stored anywhere in this repository.

---
