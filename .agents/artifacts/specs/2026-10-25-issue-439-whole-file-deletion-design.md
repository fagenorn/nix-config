# Review packages: bounded evidence for oversized whole-file deletions — issue 439

Design for https://github.com/fagenorn/nix-config/issues/439, surfaced by
elevenyellow/nodocom#2471. Base: `3f4c5072`. A bare "Dn" cites this spec's ledger.

## Triage

Input: {"signals": {"contract_change": {"value": "hit", "evidence": "review-package v2/v3 manifest generated_evidence gains a new kind accepted by artifact-budget's validator and reviewer prompts"}, "concurrency_or_persistence": {"value": "no", "evidence": "pure diff-record packaging and validation; no locking or persisted state"}, "open_design_questions": {"value": "no", "evidence": "issue fixes the evidence shape, the precedent and both negative cases; residual details (line-count definition, binary deletions) have defensible defaults"}, "criteria_shape": {"value": "hit", "evidence": "five acceptance criteria"}}, "paths": ["python/agent_tools/review_actual.py", "home/common/agent-skills/scripts/artifact_budget.py", "home/common/agent-skills/skills/sdd/task-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md", "home/common/agent-skills/skills/sdd/re-review-prompt.md", "home/common/agent-skills/tests/test_review_package.py", "home/common/agent-skills/tests/test_artifact_budget.py", "home/common/agent-skills/tests/test_workflow_skill_contracts.py"]}
Verdict: {"hits":["contract_change","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)

## Problem

sdd gates every reviewer dispatch on a `review-package` whose members are whole
diff records of at most 65,536 B (`member_max_bytes`), never truncated. A record
larger than that makes the range `decompose_required` (exit 3), and the only cure
is a smaller range. A file deleted outright cannot be split: its record is every
line of the file as a minus line. nodocom#2471 stopped at Task 3 because deleting
`landing/src/app/app/page.tsx` produced an 81,291 B record, so no range containing
that commit could ever be packaged, and the delivery could not reach review.

A reviewer gains nothing from 80 KB of minus lines. What it must judge is whether
the deletion was intended and whether anything still points at the removed path.

## Solution

When a record is a whole-file deletion and its whole record exceeds
`member_max_bytes`, the generator replaces it with a bounded generated-evidence
entry of a new kind, `whole-file-deletion`, through the same channel the
`ef-core-migration-designer` precedent uses. The package stays
`complete/within_budget`; coverage counts the file as generated evidence, so
`byte_complete_file_count + generated_evidence_file_count == file_diff_count`
holds unchanged. `artifact-budget`'s manifest validator accepts the kind with a
strict shape, and the four sdd reviewer prompts name it with its corroboration
rule. Modifications and renames keep their whole records, so an oversized one is
still `decompose_required`.

## Decisions

### Evidence shape

```json
{"path": "<repo-relative path>", "kind": "whole-file-deletion",
 "source_diff_bytes": <int, the replaced record's length>,
 "base": {"blob_sha": "<40 hex>", "bytes": <int>, "content_sha256": "<64 hex>",
          "line_count": <int>},
 "head": null}
```

- `blob_sha` is the base tree's blob id for the path; `bytes` and
  `content_sha256` are the length and SHA-256 of that blob's raw bytes. These
  three fields mean exactly what they mean on an EF designer side, and one
  helper computes them for both kinds.
- `line_count` counts LF bytes, plus one when the blob is non-empty and does not
  end in LF (per D4).
- The top-level key set is the EF entry's, so the existing path, uniqueness,
  coverage and `source_diff_bytes` rules apply unchanged.
- The entry is canonical JSON wrapped as
  `{"review-package-generated-evidence": entry}`, the shard payload EF entries
  already use. It replaces the record only when that payload fits
  `member_max_bytes`, which is the existing fit guard.

### Which records qualify

- The record's operation comes from the record policy's `--name-status -z` view,
  read once per range and aligned record-for-record with the `--name-only` paths
  the generator already zips with the diff chunks. The operation set is closed
  (`A`, `M`, `D`, `T`, `R100`). An unknown operation, or a status path that
  differs from the name-only path at the same position, fails generation loudly
  (per D1).
- Only status `D` qualifies. The base side is read from the base tree; the head
  side is `null` because of that status, and the deletion builder never probes
  the head tree for the path.
- Any regular blob qualifies, text or binary (per D3). Symlinks and gitlinks
  never produce an oversized record, so in practice they never reach this path.
- Renames follow the record policy's `--find-renames=100%`. An exact rename is
  one small `R100` record with no evidence. A rename with edits is two records,
  `D` plus `A`: the `D` half qualifies like any deletion, and the `A` half keeps
  its whole record, so an oversized one keeps the range at exit 3 (per D2).
- Modifications (`M`) and typechanges (`T`) never qualify.
- Precedence per oversized record: the EF designer builder first, then the
  whole-file-deletion builder. The first one that applies supplies the entry,
  and the fit guard then decides. There is no second fallback (per D5).
- The trigger is a single oversized record only, the same as for EF (per D12).

### Generator self-check

The candidate builder's re-validation of each evidence record keeps its checks
(path, `source_diff_bytes`, record oversize, payload size and canonical bytes).
Its kind check becomes membership in one closed set of kinds that the generator
module owns: `ef-core-migration-designer` and `whole-file-deletion`. Shape
validation stays with `artifact-budget`, which the review-package command already
runs on every published package before it reports (per D6).

### Blob lookup reads a literal path

The tree lookup that both evidence builders use passes `--literal-pathspecs`.
Without it, a path that begins with pathspec magic such as `:(top)` lists
nothing. A deletion of that path would then fail generation (exit 2) where today
it is an honest exit 3 (per D11).

### Validator (artifact-budget)

- The generated-evidence validator dispatches on `kind` over a closed set. An
  unknown kind is rejected, as it is today.
- For `ef-core-migration-designer`, the rules are unchanged: at least one side,
  each present side EF-shaped.
- For `whole-file-deletion`:
  - `head` must be `null`, and `base` must be non-null.
  - `base` has exactly the keys `{blob_sha, bytes, content_sha256, line_count}`.
  - `blob_sha` is 40 lowercase hex characters and `content_sha256` is 64.
  - `bytes` and `line_count` are integers of at least 1 (`bool` is rejected).
- The blob-identity checks (`blob_sha`, `bytes`, `content_sha256`) are one
  helper, shared with the EF side validator.
- The manifest versions, coverage rules and `validate-report` are unchanged:
  `validate-report` validates report shape and never opens a manifest.

### Manifest version

The version rule is unchanged. A range whose only oversized record is the
deletion packages at the initial context as `interface_version` 2. Version 3
appears only when adaptive packaging ran. The issue's demo says v3, so the
generator test asserts 2 and the validator test covers v3 as AC3 states (per D7).

### Reviewer prompts

- The generated-evidence paragraph of the task, conformance, correctness and
  re-review prompts is restated per kind, naming each by its literal `kind`:
  - `ef-core-migration-designer` keeps its current corroboration: identities
    and model-shape counts against the companion migration and snapshot diff,
    plus the report's no-pending-model-change, generated-SQL and
    provider-backed migration evidence.
  - `whole-file-deletion`: confirm that the plan or spec intends the deletion
    and that no surviving file references the deleted path. Missing
    corroboration is a finding, and generated evidence is never a waiver to
    approve.
- Each prompt keeps its own register and stays as compact as the rules allow.
- `final-review.md` and ship-issue's `REVIEW.md` do not change (per D8).

### Instruction budget

At base, the prompt growth exceeds the 55 B left under the
`implementation-owner` hot ceiling (both hosts). That profile hot-loads the
task, conformance, correctness and final-review documents. A draft measured
about +130 B there. The other profiles that load these prompts have room.

- The change raises exactly the breached ceilings to their measured value,
  with a note in the existing form ("Ceiling raised for #439: … (#155 D10)").
- The PR therefore needs the user to apply the `instruction-budget-raise`
  label. The ship step names that request in the PR body and holds for it,
  and never applies the label itself (per D9).

### Documentation

`python/README.md`'s "Review packaging and feasibility" section gains one
sentence. It names the two generated-evidence kinds and the record each one
replaces, which is the contract's documented home per CLAUDE.md.

## Test seams

All tests drive the source commands (agent-helpers rule 5).

1. **`review-package` CLI**, end to end through `python -m
   agent_tools.review_package`, in `test_review_package.py`. It extends the EF
   precedent `test_oversized_ef_designer_uses_bounded_semantic_evidence` and
   the existing oversized-file stop test. The fixture is a 1,000-line, ~80 KB
   text file at `landing/src/app/app/page.tsx` with a distinctive line. The
   cases:
   - Deleted (AC1): exit 0, `complete/within_budget`, `interface_version` 2,
     and exactly one entry equal to the shape above. Its values are computed
     independently in the test (`git rev-parse base:path`, `hashlib`, LF
     count). Coverage counts one file diff, zero byte-complete and one generated,
     the shards hold the wrapper and not the distinctive line, and `artifact-budget check --kind review-package`
     agrees.
   - Modified in place, every line rewritten (AC2): exit 3,
     `decompose_required`, `member_bytes`, and no generated evidence.
   - Renamed with an edit (AC2): exit 3, `decompose_required`, `member_bytes`.
   - Exact rename: exit 0 with no generated evidence, and the shards carry the
     `rename from`/`rename to` record (per D2).
   - Deleted binary blob of about 60 KB of incompressible deterministic bytes:
     exit 0 with one `whole-file-deletion` entry (per D3).
   - Deleted oversized auto-generated EF designer: the entry's kind is
     `ef-core-migration-designer`, with `head` null (per D5).
2. **`actual_inputs_from_trees`**, in the same module. A deleted oversized
   file named `:(top)page.tsx` yields a `whole-file-deletion` record whose
   `base.blob_sha` matches (per D11).
3. **Candidate builder**, in `tests/test_review_pack.py` beside the transform
   test. A record whose evidence carries an unknown kind is refused with
   `GenerationError` (per D6).
4. **`artifact-budget check --kind review-package`**, in
   `test_artifact_budget.py`, extending
   `test_generated_evidence_manifest_is_strict_and_within_budget`. A v3
   manifest with one `whole-file-deletion` entry is accepted (AC3). Each
   mutation exits 2 with empty stdout: non-null head, null base, an EF-shaped
   base, missing `line_count`, boolean `line_count`, zero `bytes`, a bad
   digest, a bad blob sha, and an unknown kind.
5. **Skill machine text**, in `test_workflow_skill_contracts.py`.
   `SDD_MACHINE_TEXT` gains both kind literals for the four reviewer prompts
   (AC4, per D10).
6. **Gates**: `just agent-workflow-tests` and `just build` (AC5, the repo's
   verification commands). `just agent-instruction-budget --raise-label`
   passes, and without the flag the only failing lines are the labelled-raise
   lines.

The deletion, binary and literal-path cases yield exit 3 or no evidence at the
base commit, and the validator, kind-set and machine-text cases have nothing to
accept there, so each fails before the change. The modification, rename and
EF-precedence cases pass at the base on purpose: they pin behaviour that must
not change.

## Out of scope

- Raising `member_max_bytes` or any budget, truncating or summarising other
  records, and partial coverage.
- Changing rename detection (no second rename pass, no similarity threshold).
- An exemption for aggregate pressure from many small deletions, and for
  modifications, typechanges or additions of any size (per D12).
- `review-feasibility` projection and forecast, which keep generated evidence
  an observed-record exception (per D12).
- Issue-specific retained models (`review_issue100`, `review_issue121`,
  `review_task7`) and their fixtures. If a retained replay changes, stop and
  report; never re-derive an anchor in this slice.
- The reviewer-lite fix-range brief in `final-review.md`, which names no rule
  for either kind today (per D8).
- Splitting nodocom#2471's delivery: this slice unblocks it.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | A record qualifies by its `--name-status -z` status `D` (aligned to name-only paths, closed op set, fail loud on mismatch); base blob read from the base tree, head side null by that status, never probed | Precedent `review_forecast.edge_facts` (status + chunk zip); probe: a file replaced by a same-named directory makes a head-tree blob lookup raise | Probing both trees for blobs (raises on file→directory); parsing the chunk's header text |
| D2 | Renames are what `--find-renames=100%` says: an exact rename stays one small record with no evidence; a rename-with-edits is `D`+`A`, its `D` half qualifies, its oversized `A` half keeps exit 3. AC2's rename negative is measured on the rename-with-edits fixture, and an exact-rename case proves no evidence | Issue: "a rename or move still produces a real diff" plus "rename handling changes" out of scope; probe: exact rename record 93 B, rename+edit = two ~82 KB records | A second rename-detection pass to withhold the exemption from split renames (changes rename handling; the add half already is the real diff) |
| D3 | Every regular-blob deletion qualifies, binary included; the evidence is content-agnostic | Probe: a 60 KB binary deletion is an 81,689 B base85 record (exit 3 today) that no reviewer can read | Text-only exemption (needs a binary heuristic, keeps an unreviewable record) |
| D4 | `line_count` = LF count + 1 for a non-empty unterminated tail, which equals Git's numstat deletion count for a text blob | Probe: 1,000 LF + tail → numstat 1001; `len(raw.splitlines())` also splits on CR | `len(bytes.splitlines())` (counts lone CR, disagrees with Git) |
| D5 | EF designer evidence takes precedence over whole-file deletion; first applicable builder, then the existing fit guard, no second fallback | EF evidence carries semantic counts and its own corroboration rule; a deleted designer already gets EF evidence today | Deletion first (drops EF semantics for deleted designers) |
| D6 | Validator dispatches per kind over a closed set (deletion: head null, base exact `{blob_sha, bytes≥1, content_sha256, line_count≥1}`, blob identity shared with EF); generator self-check generalises only its kind check to a closed set | the-bar defense in depth and fail loud; build_diff already runs the authoritative check; the-bar "Tests that can fail" against redundant guards | Duplicating side-shape checks in the candidate builder (redundant with construction and the check in the same pipeline) |
| D7 | Manifest version rule unchanged: a lone oversized deletion yields v2; generator test asserts 2, validator test covers v3 | `_build_candidate` versioning (initial context + evidence = v2) | Forcing v3 to match the issue demo (changes the version contract for no consumer) |
| D8 | The four sdd reviewer prompts carry the rule; `final-review.md` (its axes use the conformance/correctness prompts) and ship-issue `REVIEW.md` (no package at ship; reuses those prompts) stay unchanged, and so does the reviewer-lite fix-range brief | final-review.md and REVIEW.md delegate; the brief's gap predates this issue and covers EF too | A shared `generated-evidence.md` (profile closure forces a model change and an extra read); a reviewer-lite clause (hot-budget bytes for a rare route) |
| D9 | Pay the prompt growth with a labelled raise of exactly the breached `implementation-owner` hot ceilings; the PR asks the user for `instruction-budget-raise` and holds | Measured headroom 55 B vs about +130 B; "Only the user applies the instruction-budget-raise label"; established raise-note practice | Cutting unrelated reviewer guidance to fit (out of scope, weakens other rules) |
| D10 | AC4's assertion pins only the two kind literals per prompt in `SDD_MACHINE_TEXT`; the corroboration sentence is not pinned | docs/standards/agent-helpers.md rule 6; precedent pin `stable-first-fit-whole-file` | A phrase pin of the rule (forbidden by rule 6) |
| D11 | The shared blob lookup passes `--literal-pathspecs` (found while grounding) | Probe: `ls-tree <tree> -- ':(top)x'` lists nothing without it; a generic deletion of such a path would regress from exit 3 to exit 2 | Leaving it (exotic paths fail generation) |
| D12 | Scope stays per-record: only an oversized single deletion record is exempt; aggregate pressure from small deletions stays `decompose_required`; projection and retained models unchanged | Issue trigger "its whole-file diff record exceeds the member limit"; narrow slice to unblock nodocom#2471 | Exempting every deletion, or forecasting evidence in projection (wider contract change, no forcing case) |
