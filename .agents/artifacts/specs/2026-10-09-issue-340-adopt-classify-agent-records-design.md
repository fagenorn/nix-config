# Issue #340 — adopt-project classifies agent records and answers candidate questions

Issue: https://github.com/fagenorn/nix-config/issues/340 (blocks #210). Lineage: the
#148 adoption design (`2026-09-24-issue-148-adoption-plan-apply-verify-design.md`),
whose inherited-ID digest is where `D15`, `D16`, `D30`, `D33` and `D35` resolve; #72's
lifecycle decision for `.agents/artifacts/`.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "AC2 adds stable question ids to the public D35 question contract (QUESTION_IDS) and an answer input covered by plan_id"}, "concurrency_or_persistence": {"value": "no", "evidence": "plan classification and plan-id derivation only; stored-plan format unchanged in kind"}, "open_design_questions": {"value": "hit", "evidence": "canonical targets for handoffs/notes/research and the shape of the answer input are undecided"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each verified by fixture tests and just agent-workflow-tests"}}, "paths": ["python/agent_tools/adopt_inspection.py", "python/agent_tools/adopt_planning.py", "python/agent_tools/adopt_project.py", "python/agent_tools/adopt_apply.py", "home/common/agent-skills/tests/test_adopt_project.py", "python/README.md"]}
Verdict: {"hits":["contract_change","open_design_questions"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

An operator adopting Nodo runs `adopt-project plan` and gets outcome `reconcile`
with a plan that stays `draft` forever. Twenty-one tracked files under
`.claude/handoffs/`, `.claude/notes/` and `.claude/research/` match no
classification row, so each is a `needs-decision` candidate and the
`no-needs-decision` gate fails (`adopt.candidate.unclassified`). Nothing tells the
operator how to settle them: `decisions.open` lists no question for a candidate,
there is no way to answer one, and `decisions.answered` is always `[]`. The only
escapes are local workarounds in the target repository, which #210 and #71 forbid.

## Solution

Two central changes, both in the adoption modules:

1. **Classify the three record trees.** They are durable workflow records, and
   #72 already gives handoffs and notes a canonical bucket under
   `.agents/artifacts/`. Three new classification rows relocate them there, so a
   repository holding only these trees plans to `ready` with no question at all
   (AC1).
2. **Make every remaining unclassified candidate answerable.** Each one gets an
   open question under one new literal id, `candidate-class`, keyed by the
   candidate's path. `plan --answer` settles it; the answer enters
   `decisions.answered`, and therefore `plan_id` (D15), and `apply` re-derives the
   same plan by reading the answers back from the stored document (AC2).

## Decisions

### Classification rows (per D1)

Three rows join `CLASSIFICATION_RULES`, each `prefix`, lifecycle class
`durable-artifact`, action `move-canonical`:

| Group | Target |
|---|---|
| `.claude/handoffs` | `.agents/artifacts/handoffs` |
| `.claude/notes` | `.agents/artifacts/notes` |
| `.claude/research` | `.agents/artifacts/specs` |

They sit beside the existing `.claude/specs` and `.claude/plans` rows. The moves
become `git-mv` operations in the migration map like any other relocation. The
resolver's `paths.artifacts` contract does not change: handoffs and notes have no
binding, and the conformance engine already admits both buckets.

### Distinct destinations (per D2)

Two groups now relocate into one directory (`.claude/specs` and
`.claude/research` into `.agents/artifacts/specs`), so two moves could name the
same destination. The existing `no-existing-destination` gate widens: it fails
when a planned destination exists on disk **or** is the destination of more than
one planned move. Its id, repair id (`adopt.destination.occupied`) and message
stay; `READY_GATES` does not grow.

### The `candidate-class` question (per D3, D4)

`QUESTION_IDS` becomes `("project-id", "candidate-class")`, both literals.
`question_impact` and `question_recommendation` gain the second branch and keep
raising on any other id.

Every evidence entry whose action is still `needs-decision` after answers are
applied yields one open entry:

```json
{"id": "candidate-class", "subject": "<candidate path>", "value": "<answer>",
 "basis": "<fixed prose>", "impact": "<fixed prose>", "recommendation": "<fixed prose>"}
```

`subject` is the evidence entry's `path`; `(id, subject)` is the stable key.
`value` is the one answer `apply` and `verify` can honour for that candidate,
fixed by its provenance:

| Provenance | Answer | Effect |
|---|---|---|
| `tracked` | `archive-history` | action `archive-history`, target `.agents/knowledge/archive/adopted/<path>`, one `git-mv` |
| `targeted-ignored` | `retain-product` | action `retain-product`, no operation |

A tracked candidate cannot be retained in place: `apply`'s
`no-unclassified-agent-path` commit gate and `verify`'s check of the same name
would still find it unclassified. An ignored one is outside both checks, and
adoption never touches ignored bytes. `project-id` entries keep their current
member set; only `candidate-class` entries carry `subject`. `decisions.open` is
sorted by `(id, subject)`, with `project-id` first. `basis`, `impact` and
`recommendation` are fixed prose, never formatted from the path, like `NOTES`.

`action_relocates("archive-history")` becomes true, which makes
`overlap_targets` cover the archived source and its destination through the
same path the classified groups use. No classification row emits
`archive-history`, so nothing else changes behaviour.

### The answer input (per D4, D5)

`plan` takes a repeatable `--answer QUESTION SUBJECT VALUE` (three tokens, no
delimiter parsing). One policy function in `adopt_planning` applies a list of
answers to the classified candidates before the untracked-overlap pass, and both
verbs call it through `compose_plan(root, manifest, answered)`. It refuses with
`adopt_failure` when:

- `adopt.decisions.invalid_answer`: the id is not `candidate-class`, the value is
  not the provenance's one answer, or one subject is answered twice;
- `adopt.decisions.unmatched_answer`: the subject is not a `needs-decision`
  candidate of this inspection.

An answered entry keeps lifecycle class `unclassified` (the inspection's finding)
and takes the answer's action and target, with a new fixed note
(`NOTES["answered"]`). `decisions.answered` holds
`{"id", "subject", "value"}` objects sorted by `(id, subject)`. It enters
`plan_id` unchanged through `compute_plan_id`, and the evidence record's
`decisions_accepted` through the existing concatenation.

`apply` keeps exactly its two flags (D16). It validates the stored
`decisions.answered` shape (a list of objects with exactly those three string
members, else `adopt.plan.malformed`) and passes it to `compose_plan`. A
tampered answer changes the recomputed digest, which already refuses
`plan_stale`/`adopt.plan.inputs_changed`. An answer whose candidate disappeared
refuses `adopt.decisions.unmatched_answer` from the shared derivation.

`--format human` prints an open `candidate-class` entry with its subject and an
answered entry as `answered <id> <subject>: <value>`.

### References to relocated paths (per D6)

Nodo has about 283 tracked files outside the moved trees that mention the old
paths. `apply` neither rewrites nor reports them in this issue. The living
reference sweep stays the closed `LEGACY_BINDING_CONFIGS` tuple (D30). The
recommended future behaviour is **report, never rewrite**: most mentions sit in
point-in-time records that keep their original text, and the migration map
already resolves every old path.

### Documentation

`python/README.md` gains an `adopt-project` section stating the question
contract (`project-id`, `candidate-class`), the `--answer` input, its refusals,
and that answers are authenticated by `plan_id` rather than by any `apply` flag.

## Test seams

All three are existing seams, driven as `python -m agent_tools.adopt_project`
under the recipe's `PYTHONPATH`:

- **`plan` on a fixture repository** (`test_adopt_project.py`, `AdoptTestCase.plan`):
  a fixture with tracked files under all three trees reaches `ready` with the
  expected `git-mv` targets (AC1). A fixture with an unrecognised `.claude/` file
  shows one `candidate-class` open entry. Answering it changes `plan_id`, empties
  `open` and reaches `ready`; the refusals and the duplicate-destination gate each
  get a test (AC2).
- **`apply` by plan id** (`test_adopt_apply.py`, `ApplyTestCase`): an answered
  plan applies, the archived file lands at its target, and the commit gates pass.
  Editing the stored `decisions.answered` refuses `plan_stale`; a malformed one
  refuses `adopt.plan.malformed`.
- **`verify` after apply** (`test_adopt_verify.py`): the archived result is
  conformant.

The existing `project-id` key-set pins stay green unchanged. AC3 is
`just agent-workflow-tests`.

## Out of scope

- Rewriting or reporting references to relocated paths outside
  `LEGACY_BINDING_CONFIGS` (D6). Filing the report-only follow-up issue is a ship
  step, not part of this change.
- Answering `project-id` through `--answer`: its documented routes, one remote or
  an authored contract, stay.
- Any `resolve_project` change, including new `paths.artifacts` keys, and any new
  conformance bucket.
- Nodo-specific rows, and retention in place of a tracked unclassified path.
- Stale `!.claude/handoffs/`-style negations in a target's `.gitignore`: they
  match nothing after the move, and the amendment stays narrow.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `.claude/handoffs`→`.agents/artifacts/handoffs`, `.claude/notes`→`.agents/artifacts/notes`, `.claude/research`→`.agents/artifacts/specs`, all `durable-artifact`/`move-canonical` | #72 commits `artifacts/{specs,plans,evidence,handoffs,notes}`, and `ARTIFACTS_BUCKETS` admits them; the `research` skill files findings under `paths.artifacts.specs`, and this repo keeps its research reports there | A new `research` bucket, which changes the conformance closed set for one file; research into `notes`, which departs from where the platform's own research skill writes |
| D2 | `no-existing-destination` also fails when two planned moves share a destination | D1 merges two sources into one directory; the bar's fail loud; `READY_GATES` is a published closed set | A new gate id, which grows the public gate contract for a case the existing gate's meaning already covers |
| D3 | One literal question id, `candidate-class`, plus a `subject` member holding the candidate path; `(id, subject)` is the stable key | D35 makes question ids literals, never formatted, so callers dispatch exhaustively | Formatted per-path ids (`candidate-class:<path>`), which break exhaustive dispatch; adding `subject` to `project-id` entries, which changes a pinned shape for no consumer |
| D4 | The answer set is fixed by provenance: a tracked candidate takes only `archive-history` (git-mv to `.agents/knowledge/archive/adopted/<path>`), an ignored one only `retain-product`; the open entry's `value` names that answer | `apply`'s `no-unclassified-agent-path` gate and `verify`'s check classify tracked paths with the rules alone; #72 puts history under `.agents/knowledge/archive/`; YAGNI | Retaining a tracked candidate in place, which needs a persisted per-repository classification that both checks read; a delete answer, which nothing has asked for and which needs `--acknowledge-deletions` |
| D5 | `plan --answer QUESTION SUBJECT VALUE` (repeatable); `apply` reads the answers back from the stored document, and the recomputed `plan_id` authenticates them | D15 puts `decisions.answered` in the digest; D16 makes the id the approval and keeps `apply` to two flags; D33's one shared derivation | An answers file in the target repo, which is a Nodo-local workaround #210 forbids; an `--answer` flag on `apply`, which breaks D16 |
| D6 | References to moved paths outside `LEGACY_BINDING_CONFIGS` are neither rewritten nor reported here; the recorded future direction is report-only | D30's closed sweep; the bar's "moves keep their history" (point-in-time records keep original paths); the migration map resolves old paths | Rewriting all ~283 Nodo mentions, which edits point-in-time records and is not mechanically decidable (D30) |
