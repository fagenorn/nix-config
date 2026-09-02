# Recovered wayfind research findings — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The four "Attached findings" permalinks in the resolution comments of
#60, #61, #62 and #80 resolve, because each linked `.claude/specs/` path now
holds a committed, re-derived research document that provably discharges its
ticket's enumerated claim contract.

**Architecture:** Four Markdown documents, one per ticket, written at the exact
paths their resolution comments link. Each obeys one shared front-matter and
citation contract (spec, `## Document contract`) and carries a
`## Coverage of the resolution summary` table keyed by the spec's literal claim
IDs. That table is the *traceability* seam: a `grep` proves every claim ID is
present and names a real discharging section, which is a necessary floor and not
a sufficient one. Whether the discharged prose is true of the live tree is
settled only by the per-task semantic audit (V5), never by a gate. Three documents (#60, #61, #62) are re-derived from their in-ticket
conclusions plus the live tree; the fourth (#80) is re-derived from primary
sources across all three fleet repositories and is built in two passes along the
spec's own inherited/added claim boundary. No `.nix` file, and no file outside
`.claude/specs/` and `.claude/plans/`, is touched.

**Spec (the contract):**
`.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md`.
**Read it in full before any task** — it owns the shared document contract, the
per-document claim tables, the #80 seam taxonomy, the terminology guards and the
`## Decision ledger` (D1–D18). This plan cites ledger rows by ID and never
restates them. Its `## Out of scope` is binding.

**Issue:** https://github.com/fagenorn/nix-config/issues/115

**Tech stack:** Markdown only. Verification is Bash plus standard command-line
tools (`git`, `grep`, `sed`, `awk`, `diff`) — the gates use Bash-only
constructs such as `$'…'` and process substitution — plus `gh` for reading
tracker comments. No Nix evaluation, no
Python, no new dependency, no new file outside the two directories above.

## Global Constraints

Every task's requirements implicitly include this section.

- **Scope.** This work is four Markdown files plus the spec and this plan
  package. Do not create a checker script, a glossary, a context map or an ADR
  (per D15, D17). Do not touch `home/`, `hosts/`, `lib/`, `flake.nix`,
  `justfile`, `tests/` or any `.nix` file. Should a task nevertheless touch a
  `.nix` file, `CLAUDE.md`'s standing rule reactivates and `just build` becomes
  a gate for that task.
- **Paths are exact and non-negotiable.** The four filenames and their
  `2026-08-20` prefix are the *decision date* of each ticket, not the authorship
  date. Nothing renames these files.
- **Every substantive sentence in the four documents is authored during
  execution from primary sources.** This plan dictates the claim contract, the
  required structure and the falsifiable gates; it deliberately dictates no
  finding prose (per D17). Where this plan quotes an exact string, that string
  is a required literal of the document contract — front matter, headings, claim
  IDs — never a finding.
- **Citation form** is the spec's four-row table under `### Citation form`
  (per D3). Fleet-checkout claims carry the repository name, the repo-relative
  path, the checkout's observed `HEAD` sha and the observation date. Prototype
  claims carry the full 40-character sha and the `origin` branch that reaches
  it. An inherited summary claim not re-verified against a primary source is
  marked inline and listed in that document's unverified-inheritance list.
- **Drift rule** (per D5, D18): where the live tree contradicts a summary claim,
  record (a) the as-of-decision claim, (b) the observed fact with the exact
  command and the observation date, (c) an explicit reconciliation sentence.
  Never silently restate, never silently drop. Re-observe every drift-sensitive
  claim yourself; never copy a count or a tracked/ignored verdict out of the
  spec or out of this plan.
- **Terminology guards** (per D10) are binding: fallback vs fail-closed refusal
  vs declared runtime alternative (#61); release state vs durable state store,
  subject identity vs record identity, and the three declared seam classes
  (#80); and the note that `.superpowers/` is a historical directory name with
  no Superpowers input, patch, marketplace or plugin in this repository.
- **Canonical section names.** All four documents use these headings verbatim,
  in this order, so one gate shape works across the package: `## Provenance`,
  `## Research question`, `## Coverage of the resolution summary`,
  `## Unverified inheritance`, then the document's own body sections, then
  `## What this document does not decide` last. `## Unverified inheritance` is
  never omitted: when a document has no unverified inherited claim it says so in
  one sentence, because silence is not permitted (spec, `### Citation form`).
- **Coverage-table shape.** Four columns: the spec's literal claim ID with its
  source tag in the form `C60.1 (summary)`; a one-line restatement of the claim;
  the claim's source; and the exact text of a `##`/`###` heading **in the same
  document** that discharges it. The heading text in column four must match a
  real heading character-for-character — that is what makes coverage checkable
  rather than promised.
- **Proportionality** (per D8): `artifact-budget` declares no `research` kind, so
  never run it against the four documents. Length is governed by the-bar's
  *Token economy* — as long as the coverage obligation and the citations
  require, and no longer.
- **Fleet checkouts are read-only.** `/Users/anis/Projects/nodocom` and
  `/Users/anis/Projects/argus` may be read and may have their `HEAD` observed.
  Never write, `checkout`, `fetch`, `stash` or otherwise mutate them.
- **The checked-out fleet snapshot is the cited evidence, and its divergence is
  stated, not hidden** (per D21). These documents record what was observable on
  2026-09-02, not the current integration tip of another repository, and no task
  may refresh a checkout to close the gap. Every fleet citation therefore names
  the checkout's observed `HEAD` and, where the checkout is behind its own
  `origin` integration ref, says by how many commits and names that ref. At the
  time of planning `/Users/anis/Projects/nodocom` was at `7a3dab7`, 111 commits
  behind its local `origin/dev`; re-observe both numbers at execute time rather
  than copying these. A conclusion whose truth could turn on that gap is marked
  as snapshot-bound in `## Unverified inheritance`.
- **Tracker access.** The ambient `GITHUB_TOKEN` lacks access to this repo.
  Prefix every `gh` call with `unset GITHUB_TOKEN GH_TOKEN &&` and pass
  `--repo fagenorn/nix-config`. Never edit a tracker comment, including #86's
  (per D7).
- **Commits** are SSH-signed. Never pass `-c commit.gpgsign=false` or
  `--no-gpg-sign`; surface signing failures rather than working around them.
  Every commit carries the trailer
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`.

## Test seams

The spec's `## Test seams` table owns these; the plan inherits them. There is no
unit-test suite for documentation in this repository and this work edits no
`.nix` file, so `just build` is not a gate here.

- **V1 — path existence.** `git show HEAD:<path>` for each of the four paths,
  run in this worktree at the task's own commit. AC4's `git show main:<path>`
  form is the same seam observed after merge and is a ship-time consequence, not
  a pre-merge gate (per D16).
- **V2 — claim-ID coverage.** `grep`/`awk` over the
  `## Coverage of the resolution summary` section of each document for that
  document's claim IDs, exactly as the spec enumerates them. This is the AC1
  *traceability* floor, made mechanical (per D12). It proves a claim is
  addressed somewhere; it proves nothing about whether the address is correct.
- **V5 — source-backed semantic audit.** A reading, not a gate, and the only
  seam that can discharge AC1. For each claim ID in a document's coverage
  table, the task's reviewer opens the named discharging section and the live
  sources it cites, then confirms every enumerated field, matrix cell and list
  item that claim owes is actually answered from those sources. A conclusion
  with no cited source, a citation that does not support the sentence it
  anchors, and an enumerated field left unanswered without an explicit
  no-answer statement are each a rejection. These documents are recovered
  historical findings whose entire value is being true of the live tree, so an
  unsupported-but-plausible sentence at one of these four paths is a worse
  outcome than a missing one (per D19).
- **V3 — the #80 roster.** Inspection of the `## Seam roster` table for eleven
  rows across the three declared classes, each carrying its required fields
  (AC2).
- **V4 — prototype reference immutability.** `git cat-file -e <sha>^{commit}`
  and `git ls-remote origin` for both prototype shas (AC3).

Implementers verify at these five seams and nowhere else. A task that appears to
need a sixth seam is a plan bug, not an implementer's call.

## Task index

Task 1 — #60 cross-agent project surfaces — `.claude/specs/2026-08-20-cross-agent-project-surfaces-research.md` — full — [task-1.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-1.md)
Task 2 — #61 agent fallback inventory — `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` — full — [task-2.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-2.md)
Task 3 — #62 project knowledge inventory — `.claude/specs/2026-08-20-project-knowledge-inventory-research.md` — full — [task-3.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-3.md)
Task 4 — #80 release-unit seams and inherited claims — `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` — full — [task-4.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-4.md)
Task 5 — #80 added seams, prototype references, correction, package sweep — `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` — full — [task-5.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-5.md)

Lane notes: every task is `full`. Each produces a document that is cited as
evidence by settled decisions (#71 Stage 0, #79, #84, #88) — a public contract,
which the `low-risk` lane excludes outright. `mechanical` is unavailable to all
five: none of them is a deletion or rename, and every one has semantic
documentation effect, which is that lane's stated exclusion. Being Markdown, or
being short, does not qualify a lane. Task 5 additionally carries release,
security and lifecycle subject matter (the permission guard, the five durable
state systems), each of which is independently `full` by the exclusion list.

## Acceptance-criteria coverage

| AC | Discharged by |
|----|---------------|
| AC1 — each document's conclusions cover every claim in its ticket's resolution summary | Tasks 1–4 (V2 per document), Task 5 (whole-package V2 sweep) |
| AC2 — #80 adds the permission guard and the five durable state systems as seams with identity, evidence and rollback | Task 5 (V3) |
| AC3 — #80 records immutable references for both prototype artifacts and corrects #86 | Task 5 (V4) |
| AC4 — the four linked paths resolve | Tasks 1–5 (V1 in-branch), completed on merge to `main` |

## Decisions

The spec owns the single issue-level ledger (D1–D21). Cite rows by ID; never
restate them. Planning appended D16–D18 and the Phase-5 standards review
appended D19–D21 to the **spec's** ledger:

- **D16** — in-branch gates observe `git show HEAD:<path>`; the `main` form of V1
  is a ship-time consequence of merging, not a task gate.
- **D17** — the plan dictates claim contracts, required structure and falsifiable
  gates, and dictates no finding prose; it also creates no verification script,
  keeping the deliverable at four Markdown files.
- **D18** — C62.2's parenthetical drift observation is itself planning-time
  unverified and is superseded by the execute-phase re-observation, whatever
  that finds — including "no drift".
- **D19** — the claim-ID gates prove traceability, not truth; V5's source-backed
  semantic audit is the only seam that discharges AC1, and the #80 gate checks
  substantive seam values and associated prototype triples.
- **D20** — the guard inventory covers both authorized owners and the `dev`
  integration base, and the durable-state sources name the two sdd scripts.
- **D21** — fleet citations record the checked-out snapshot and its distance
  behind `origin`; no task refreshes a checkout.

## Standards review provenance

- **Reviewer:** Codex, isolated read-only runtime (fresh `CODEX_HOME`, approval
  policy `never`, sandbox `read-only`). No native fallback was used.
- **Base SHA:** `9206f3ea92e2dde06b998b1a9e402fc2b1ad1e6d`, branch
  `worktree-issue-115-recover-wayfind-research-findings`.
- **Focus:** none configured; the standard bar was applied.
- **Counts:** 6 findings, 6 accepted, 0 rejected, 0 deferred — 3 Blocking, 2
  Should fix, 1 Discussion.
- **Dispositions.** Every finding was re-verified against the live plan members
  before being applied. B-01 (each task's Step 4 expected `PASS` while its own
  gate runs V1, which cannot pass before Step 5's commit) is corrected in all
  five members. B-02 and B-03 are recorded together as D19; SF-01 and SF-02 as
  D20; the Discussion item D-01 as D21. Two of B-02/B-03's sub-claims were
  partly stale and were narrowed rather than applied as written: task 4's gate
  did already check twelve `C80.4` fields (the other eleven are now added), and
  task 5's guard literals did already include `elevenyellow/nodocom` (only bare
  `elevenyellow` and `dev` were missing).
- No reviewer transcript is stored in this repository, the issue, the PR, or any
  commit message.

