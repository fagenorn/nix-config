# Learning Promotion Loop v1 Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship the `promotion` command (capture, evaluate, validate, advance) over three
clockless candidate documents and the required conformance check
`repository.residue.promoted_duplicate`, delivered as three reviewable packages in one PR.

**Architecture:** Three standard-library modules in `python/agent_tools/`
(`promotion_schema`, `promotion`, `promotion_lifecycle`) behind one command-table row, per
D2. `agent_gate_bundle` gains `verify_bundle` (D8). The flat conformance engine gains one
evaluator that reads candidate files directly, with its literals pinned to the package by a
test (D10, D27).

**Tech stack:** Python 3 standard library, `unittest`, Just, Nix (`lib/agent-tools.nix`).

The design spec is `.agents/artifacts/specs/2026-09-28-issue-127-learning-promotion-loop-design.md`.
It is the source of truth; every "per Dn" below cites its `## Decision ledger`.

## Global Constraints

- Standard library only; no new dependency, no `docs/` tree, ADR or glossary (D18). No change to
  `.agents/project.json`, `.gitignore`, the projections or `CLAUDE.md`.
- Package code obeys `docs/standards/agent-helpers.md` rules 1–5: no `sys.path` edits, no
  `importlib`, no `__file__`-derived lookups; `resolve-project` runs by command name on `PATH` (D5).
- Ids come from `agent_tools.canonical.telemetry_digest`; strict loads compose
  `reject_duplicate_keys` and `reject_nonfinite_literal` (D13). A file-content digest
  (`local_duplicates[].sha256`) is `hashlib.sha256(bytes).hexdigest()`, 64 lowercase hex.
- Documents are clockless: no member named `created_at`, `generated_at`, `time` or
  `timestamp` at any depth (D13).
- Every JSON the module prints or writes is
  `json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False) + "\n"`.
- Exit 0 document, 3 gate refusal (candidate byte-identical), 2 tool/structural failure and
  every argparse usage error (no JSON) (D12). The refusal object is exactly
  `{"error":{"code","candidate_id","state","violations":[{"pointer","message"}]}}`.
- No override, force or skip flag on any subcommand (D7).
- `conformance-registry.py` and `conformance-checks.py` never contain the text `agent_tools` (D27).
- Every file the branch adds or changes keeps a whole-file diff under 65536 bytes; target 48 KiB
  per new file (D20).
- Commits are SSH-signed (never disable signing), subject `feat(issue-127/T<n>): …`, and end with
  the attribution trailer lines supplied to the executing session (never a session URL copied
  from this plan).
- Run package suites as `PYTHONPATH=python python3 -m unittest <file> 2>&1 | tail -5`, from
  the worktree root, the way the `agent-workflow-tests` recipe runs them.

## Test seams

Exactly the five seams of D16. A task that seems to need a sixth is a plan bug.

1. `[sys.executable, "-m", "agent_tools.promotion", …]` as a subprocess, with an explicit env
   whose `PATH` holds only a stub `resolve-project` (`tests/promotion_test_support.py`).
2. `promotion validate` as a subprocess; each fault is a refused file naming its pointer.
3. The source `conformance` CLI (`run --purpose doctor --repo-root <fixture>`) through
   `conformance_test_support`.
4. Committed-root gates: `AcceptanceDemoTest` (flat) and `tests/test_promotion_demo.py` (D28).
5. `tests/test_promotion_installed.py` under `agent-installed-skill-tests`, plus the pin case
   in `test_conformance_registry.py`.

## Delivery estimate and boundaries

Estimates only. P1 (Tasks 1–2): ~5 files, `promotion_schema.py` ~28 KB, `promotion.py`
~9 KB, `test_promotion_documents.py` ~22 KB. P2 (Tasks 3–5): ~6 files,
`promotion_lifecycle.py` ~16 KB, lifecycle suites ~18 KB and ~12 KB. P3 (Tasks 6–7): ~12
files, registry/checks growth ~5 KB, suites ~14 KB. The aggregate diff is the largest
risk. Each package is independently reviewable: its final task runs
`review-package <this plan> <pkg-base> HEAD <out>`, which must print `"state":"complete"`
(D20, D28).

## Task index

Task 1 — Schema, validator and `promotion validate` — `python/agent_tools/promotion_schema.py`, `python/agent_tools/promotion.py`, `tests/promotion_test_support.py`, `tests/test_promotion_documents.py`, `lib/agent-tools.nix`, `justfile` — full — [task-1.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-1.md)

Task 2 — `capture` and `evaluate`, the resolver child, P1 feasibility — `python/agent_tools/promotion_schema.py`, `python/agent_tools/promotion.py`, `tests/test_promotion_documents.py` — full — [task-2.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-2.md)

Task 3 — `agent_gate_bundle.verify_bundle` — `python/agent_tools/agent_gate_bundle.py`, `tests/test_agent_gate_bundle.py` — full — [task-3.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-3.md)

Task 4 — `advance`: classification and the gates up to `authorized` — `python/agent_tools/promotion_lifecycle.py`, `python/agent_tools/promotion.py`, `tests/promotion_test_support.py`, `tests/test_promotion_lifecycle.py`, `justfile` — full — [task-4.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-4.md)

Task 5 — Deployment, `superseded`, P2 feasibility — `python/agent_tools/promotion_lifecycle.py`, `python/agent_tools/promotion.py`, `tests/test_promotion_deployment.py`, `justfile` — full — [task-5.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-5.md)

Task 6 — `repository.residue.promoted_duplicate` — `home/common/agent-skills/scripts/conformance-registry.py`, `home/common/agent-skills/scripts/conformance-checks.py`, `home/common/agent-skills/tests/test_conformance_checks.py`, `home/common/agent-skills/tests/test_conformance_registry.py` — full — [task-6.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-6.md)

Task 7 — Demo documents, committed-root and installed gates, P3 feasibility — `.agents/knowledge/promotions/drafts/investigate-before-changing.json`, `.agents/knowledge/promotions/candidates/investigate-before-changing.json`, `.agents/artifacts/evidence/promotion-127-trials.json`, `.agents/artifacts/evidence/promotion-127-bundle.json`, `tests/test_promotion_demo.py`, `tests/test_promotion_installed.py`, `justfile` — full — [task-7.md](2026-09-28-issue-127-learning-promotion-loop.tasks/task-7.md)

## Decisions

The spec's ledger holds every choice; this plan appended D27–D32. Task coverage:

| Decisions | Tasks |
|---|---|
| D1, D4, D5, D14, D19, D25, D30 (capture, evaluate, resolver, outputs, faults) | 1, 2 |
| D2, D12, D13, D15, D16 (modules, exits, ids, path safety, seams) | every task |
| D3, D17, D31 (document homes, the demo, its manifest) | 7 |
| D6, D7, D23, D29 (classification, gates, whole-line anchor, gate order) | 4 |
| D8 (`verify_bundle`) | 3, 4 |
| D9, D24, D26, D32 (deployment, re-run gates, rule 1 parity, superseded) | 5 |
| D10, D11, D21, D27 (the check, its literals, installed proof) | 6, 7 |
| D20, D28 (packages, suites, review ranges) | 2, 5, 7 |
| D22 (not a `transaction_core` consumer) | 4 |

---

## Standards review provenance

- Reviewer: Claude fallback (Opus reviewer). The configured Codex `plan-review` run completed, but its output failed the metadata contract (no runtime-selection event reporting the model and effort, and several agent messages instead of one terminal message), so one native fallback ran with the same packet and Codex was not retried.
- Base SHA `66ccba5844eab2af9c68962c54a28f874585ee80`, plan reviewed at `f576297`; isolated, read-only; no focus.
- Accepted 7: B1 (task-4 unique capture names per loop iteration), B2 (task-2 one resolver stub directory per case), S1–S3 (per D33), Discussion D2 (spec purpose-selection prose), Discussion D3 (trailer from the executing session).
- Rejected 1: Discussion D4. The `bin` listing assertion is redundant but harmless; the exit-0 run without `gh` on `PATH` carries the evidence.
- Deferred 1: Discussion D1 (overflowing-float hook in `agent_tools.canonical`). Out of #127's scope, because promotion documents carry no floats and bundle verification is #120's code.
