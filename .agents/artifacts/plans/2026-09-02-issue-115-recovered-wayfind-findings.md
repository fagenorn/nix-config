# Recovered wayfind research findings — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** The four "Attached findings" permalinks in the resolution comments of
#60, #61, #62 and #80 resolve, because each linked `.claude/specs/` path now
holds a committed, re-derived research document that provably discharges its
ticket's enumerated claim contract.

**Architecture:** Four Markdown *document packages*, one per ticket, each with a
root at the exact path its resolution comment links. A root over the
`review-package` per-member cap also carries evidence members under
`<root-stem>.evidence/` (per D22). A root always holds provenance, research
question, coverage table, unverified inheritance, syntheses and conclusions; a
member holds bulk evidence tables only. Each obeys one shared front-matter and
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
`## Decision ledger` (D1–D25). This plan cites ledger rows by ID and never
restates them. Its `## Out of scope` is binding.

**Issue:** https://github.com/fagenorn/nix-config/issues/115

**Tech stack:** Markdown only. Verification is Bash plus standard command-line
tools (`git`, `grep`, `sed`, `awk`, `diff`) — the gates use Bash-only
constructs such as `$'…'` and process substitution — plus `gh` for reading
tracker comments. No Nix evaluation, no
Python, no new dependency, no new file outside the two directories above.

## Global Constraints

Every task's requirements implicitly include this section.

- **Scope.** Four Markdown document packages plus the spec and this plan
  package. The only files it may create outside the four linked roots are
  evidence members at `<root-stem>.evidence/<name>.md` (per D22) and this plan's
  own task members. Do not create a checker script, a glossary, a context map or an ADR
  (per D15, D17). Do not touch `home/`, `hosts/`, `lib/`, `flake.nix`,
  `justfile`, `tests/` or any `.nix` file. Should a task nevertheless touch a
  `.nix` file, `CLAUDE.md`'s standing rule reactivates and `just build` becomes
  a gate for that task.
- **Paths are exact and non-negotiable.** The four filenames and their
  `2026-08-20` prefix are the *decision date* of each ticket, not the authorship
  date. Nothing renames these files or moves a root out of `.claude/specs/`: the
  four permalinks must resolve to the roots themselves. A member's directory is
  the root's stem plus `.evidence`.
- **Every substantive sentence in the four documents is authored during
  execution from primary sources.** This plan dictates the claim contract, the
  required structure and the falsifiable gates; it deliberately dictates no
  finding prose (per D17). Where this plan quotes an exact string, that string
  is a required literal of the document contract — front matter, headings, claim
  IDs — never a finding.
- **Citation form** is the spec's four-row table under `### Citation form`
  (per D3): fleet claims carry repo name, repo-relative path, observed `HEAD`
  and date; prototype claims carry the full 40-character sha and the reaching
  `origin` branch; an inherited claim not re-verified against a primary source
  is marked inline and listed in the document's unverified-inheritance list.
- **Drift rule** (per D5, D18): where the live tree contradicts a summary claim,
  record the as-of-decision claim, the observed fact with its exact command and
  date, and an explicit reconciliation. Never silently restate or drop.
  Re-observe every drift-sensitive claim yourself; never copy a count or a
  tracked/ignored verdict out of the spec or this plan.
- **Terminology guards** (per D10) are binding, and the spec states each one:
  the #61 triad, the #80 state/identity/seam-class distinctions, and the
  `.superpowers/`-is-historical note.
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
  document package** that discharges it. The heading text in column four must
  match a real heading character-for-character — that is what makes coverage
  checkable rather than promised. A root heading is named alone; a member
  heading is named `<member path> § <heading text>`, so coverage still resolves
  to exactly one file per row (per D22).
- **Proportionality** (per D8): `artifact-budget` declares no `research` kind, so
  never run it against the four documents. Length is governed by the-bar's
  *Token economy* — as long as the coverage obligation and the citations
  require, and no longer.
- **Review-package bound** (per D22) — a different bound from D8, enforced by a
  different tool. The real limit is the policy's `member_max_bytes`, **65,536
  bytes** per file diff, with the branch package fitting eight shards; V6
  measures exactly that and nothing else, so no task may assert a bound V6 does
  not check. One task-local target is tighter and is stated where it binds: the
  #80 root must be at or under **35,000 bytes** when Task 4 ends, to leave Task
  6 room. Files already finished under 65,536 are left alone.
- **Fleet checkouts are read-only.** `/Users/anis/Projects/nodocom` and
  `/Users/anis/Projects/argus` may be read and may have their `HEAD` observed.
  Never write, `checkout`, `fetch`, `stash` or otherwise mutate them.
- **The checked-out fleet snapshot is the cited evidence, and its divergence is
  stated, not hidden** (per D21). Every fleet citation names the checkout's
  observed `HEAD` and, where it is behind its own `origin` integration ref, how
  far and which ref — re-observed at execute time, never copied from this plan.
  A conclusion whose truth could turn on that gap is marked snapshot-bound in
  `## Unverified inheritance`.
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

- **V6 — review packageability** (per D22). After committing, run
  `review-package <this plan file> "$(git merge-base origin/main HEAD)" HEAD
  "$OUT/v6.json"` with `OUT=$(mktemp -d)`, require exit 0 with `within_budget`,
  then delete `$OUT`. **Always give that fourth positional destination** (in
  diff mode `--output` is rejected as an invalid invocation; the flag belongs to
  detail mode): the default destination is keyed to the range,
  `MERGE_BASE..HEAD` is exactly what the mandatory final review publishes to,
  and `review-package` publishes exclusively — a V6 run left at the default
  makes the final review's own generation fail, and re-running at the same
  `HEAD` does not clear it. Exit 2 is a generation failure of any kind, never
  assumed stale. V6 is the only gate here measuring *delivery shape*, and the
  one the single-file architecture failed; run it at the end of every task from
  task 4 onward.

Implementers verify at these six seams and nowhere else. A task that appears to
need a seventh seam is a plan bug, not an implementer's call.

## Task index

Task 1 — #60 cross-agent project surfaces — `.claude/specs/2026-08-20-cross-agent-project-surfaces-research.md` — full — [task-1.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-1.md)
Task 2 — #61 agent fallback inventory — `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` — full — [task-2.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-2.md)
Task 3 — #62 project knowledge inventory — `.claude/specs/2026-08-20-project-knowledge-inventory-research.md` — full — [task-3.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-3.md)
Task 4 — #80 release-unit seams, inherited claims, and the #80 package decomposition — `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` and its evidence members — full — [task-4.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-4.md)
Task 5 — decompose the #61 document into a root-plus-evidence-member package — `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` and its evidence members — full — [task-5.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-5.md)
Task 6 — #80 added seams, prototype references, correction, package sweep — `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` and any evidence member it adds — full — [task-6.md](2026-09-02-issue-115-recovered-wayfind-findings.tasks/task-6.md)

**The D22 amendment reopened Task 4 and added Task 5.** The sdd ledger records
task 4 as not reviewed and not complete, and sdd resumes at the first task
without a `complete` line, so that is where execution restarts; its remaining
work is the #80 decomposition, without which its own mandatory review cannot be
packaged. The new task 5 decomposes the #61 document, whose task completed
before the cap was known. The added-seams task that held number 5 is now task 6:
the index runs in ascending order, and it must follow both decompositions
because it appends to the #80 root.

Lane notes: every task is `full`. Each produces a document cited as evidence by
settled decisions (#71 Stage 0, #79, #84, #88) — a public contract, which
`low-risk` excludes outright. `mechanical` is unavailable to all six: none is a
deletion or rename, and every one has semantic documentation effect, that lane's
stated exclusion. Being Markdown, or short, does not qualify a lane. Task 6
additionally carries release, security and lifecycle subject matter, each
independently `full`. The decompositions are `full` too: relocating a claim's
evidence changes where a reader must go to check it, which is exactly that
semantic effect.

## Acceptance-criteria coverage

| AC | Discharged by |
|----|---------------|
| AC1 — each document's conclusions cover every claim in its ticket's resolution summary | Tasks 1–4 (V2 per document), Task 5 (V2 across the #61 package), Task 6 (whole-package V2 sweep) |
| AC2 — #80 adds the permission guard and the five durable state systems as seams with identity, evidence and rollback | Task 6 (V3) |
| AC3 — #80 records immutable references for both prototype artifacts and corrects #86 | Task 6 (V4) |
| AC4 — the four linked paths resolve | Tasks 1–6 (V1 in-branch, re-run after each decomposition), completed on merge to `main` |

## Decisions

The spec owns the single issue-level ledger (D1–D25), and is the only place
those rows are written out. This plan cites them by ID and never restates them.
Planning appended D16–D18; the Phase-5 standards review D19–D21; the Phase-6
back-up to planning D22; and that amendment's own re-review D23–D25.

## Standards review provenance

Both passes ran on Codex in an isolated read-only runtime (fresh `CODEX_HOME`,
approval `never`, sandbox `read-only`), with no native fallback and no configured
focus. Every finding was re-verified against the live worktree before being
applied, and no reviewer transcript is stored in this repository, the issue, the
PR, or any commit message.

- **Phase 5, base `9206f3ea92e2dde06b998b1a9e402fc2b1ad1e6d`.** 6 findings, 6
  accepted: 3 Blocking, 2 Should fix, 1 Discussion. B-01 (each task's Step 4
  expected `PASS` while its own gate runs V1, which cannot pass before Step 5's
  commit) is corrected in all five members; B-02/B-03 are D19, SF-01/SF-02 are
  D20, D-01 is D21. Two sub-claims of B-02/B-03 were stale and were narrowed.
- **Re-review of the D22 amendment, base `177c963`.** 8 findings, 8 accepted: 6
  Blocking, 1 Should fix, 1 Discussion. D-01 confirmed the diagnosis and the
  package architecture. B-01 is D23, B-05 is D24, B-06 is D25; B-02 (members
  carry bulk evidence records, not only tables) and B-03 (V6's 65,536-byte cap
  is the only asserted bound) are edits to D22 itself, made before it executed;
  B-04 and SF-01 are gate and cross-reference corrections.
