# Task 4: The architecture sentence and the parent audit

The repository says where the evidence is and how to check it, and parent https://github.com/fagenorn/nix-config/issues/226 gets its requirement-to-evidence map (spec § *Architecture sentence*, § *Parent audit*; EV7, EV9, EV12). No `python/` byte and no test changes.

**Files:**
- Modify: `CLAUDE.md` (one sentence appended to the paragraph that starts `**Agent helper package.**`)
- Create: `.agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md`

**Interfaces:**
- Consumes (Tasks 1 to 3, by name only): the bundle directory `tests/fixtures/retained-review-evidence/`; `tests/retained_evidence_test_support.py`; the suite `tests/test_review_evidence.py` (`CommittedEvidenceTest`); the cases `test_committed_evidence_replays_alike_from_source_and_built` (`tests/test_agent_tools_launchers.py`) and `test_committed_evidence_reproduces_with_the_reviewed_tool` (`tests/test_review_retained_full.py`).
- Consumes: the tracker through `gh`, read-only. This task writes nothing to the tracker.
- Produces: the audit document, which both final reviewers read and whose verdict the controller posts on issue 226 after the merge.

**Invariants:**
- `CLAUDE.md` gains exactly one sentence on one existing line. `.agents/instructions/bootstrap.md` and `AGENTS.md` are untouched and no projection is regenerated.
- The sentence does not hold the anchor digest (EV9).
- Every audit row is `delivered`, `open follow-up` or `unmapped`, and each claim in a row was checked against the tracker or the tree while writing it. A row you cannot prove is `unmapped`; never write `delivered` from memory or from this task text.
- Neither file, and no commit message, holds a closing keyword (`close`, `fix`, `resolve` and their inflections) directly followed by a reference to issue 226. A sentence that says the parent stays open names it in words, as "parent 226".
- References are full URLs, never a bare `#N`.

- [ ] **Step 1: Watch the gate fail.**

```bash
if grep -q 'tests/fixtures/retained-review-evidence/' CLAUDE.md; then exit 1; fi
if [ -e .agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md ]; then exit 1; fi
```

- [ ] **Step 2: Append the sentence.** The paragraph is one line. Append, after its final full stop and one space:

```text
The retained review evidence that `derive-review-feasibility-fixtures` derives is committed as five files under `tests/fixtures/retained-review-evidence/` (#235); `replay-retained` replays that directory under the anchor digest held in `tests/retained_evidence_test_support.py`, and an authentic replay exits 2 with `projection_unavailable`, because two of the retained issue-121 boundaries are authenticated refusals rather than measurements.
```

  `(#235)` matches the paragraph's own issue tags. Before committing, confirm each claim against the tree: the directory holds five files, the support module holds `ANCHOR_SHA256`, and `test_authentic_copy_replays_to_the_historical_refusal` asserts exit 2 with `projection_unavailable: tasks-1-3,tasks-4-6`. If one does not hold, stop and report it instead of rewording.

- [ ] **Step 3: Gather the audit's sources.**

```bash
gh issue view 226 --repo fagenorn/nix-config
for n in 233 234 248 249 254 255 256; do gh issue view "$n" --repo fagenorn/nix-config --json number,state,title,url; done
for n in 246 251 253 257; do gh pr view "$n" --repo fagenorn/nix-config --json number,state,mergeCommit,url; done
gh issue view 234 --repo fagenorn/nix-config --json comments --jq '.comments[] | select(.body | test("^## Parent (re-)?audit")) | .url, .body'
git log --format='%H %s' --no-merges 8971e41802fd2ee4de8d1c85626ea1cdcf2d384d..HEAD ^origin/main
```

  Known at planning, to be confirmed by those commands: CORE is issue 233, merged by pull request 246 at `93e6059a6fece769a621657c5889278b9cb9e0d7`. DERIVE is issue 234, delivered through issue 248 (pull request 251, `218f5bc0bf3556fa05959e6ba24175685b58e2a9`), issue 249 (pull request 253, `7e17c8196569b0a96950f07ff886884690ffa224`) and issue 254 (pull request 257, `8971e41802fd2ee4de8d1c85626ea1cdcf2d384d`). Issues 255 and 256 are open follow-ups. The children's specs and plans, with their decision ledgers and recorded review findings, are in `.agents/artifacts/specs/` and `.agents/artifacts/plans/` under the issue numbers 233, 248, 249 and 254. Parent 226's own design is not in this tree, so the issue body is the requirement source.

- [ ] **Step 4: Write the audit.** `.agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md` has these parts, in this order:

  1. A title, then one paragraph: what was audited (parent 226 against its three deliveries), the branch head the audit read (`git rev-parse HEAD` before this task's commit), the date, and the sentence that this document does not close issue 226.
  2. **Deliveries.** One table row per child: CORE, the three DERIVE children and this EVIDENCE child, each with its issue URL, its pull request URL and merge commit, or for this child the branch and the commits of Tasks 1 to 3.
  3. **Requirements.** A table with the columns `Item`, `Source`, `Owner`, `Accepted at`, `Proof`, `Status`. One row per item, and every item of these sources has a row:
     - each clause of each of parent 226's eight acceptance criteria (split a criterion wherever two clauses could be proved or fail separately);
     - the approved acceptance amendment of 2026-09-29, clause by clause;
     - each bullet of parent 226's *Decisions* that states a checkable requirement.
  4. **Findings.** The same columns. One row for each of the three original Important findings (incomplete issue-121 attribution, invalid boundary graphs, unchecked witness identities), and one for every residual finding the children recorded: the grafted-ancestry finding, issue 248's same-commit file and directory swap, issue 249's attribute finding, issue 254's expansion-cost finding, and one row per child that points to its recorded Minor findings.
  5. **Verdict.** One line that says whether any row is `unmapped`. When none is, it says that parent 226 may close once the pull request for issue 235 has merged with both final reviews accepted and required CI green, and it lists the open follow-ups https://github.com/fagenorn/nix-config/issues/255 and https://github.com/fagenorn/nix-config/issues/256 as residuals that whoever closes the parent must accept or keep it open for. When a row is `unmapped`, the line says the parent may not close and names the rows.

  Row rules:
  - `Owner` is the child issue's URL. `Accepted at` is its merged pull request URL and merge commit. For a row this child proves, it is the branch commit that added the proof, from Step 3's `git log`.
  - `Proof` names a test case, a committed file or a recorded gate result that a reader can open: a path with a case name, or a URL. Check that each named case exists with `grep -n "def <case>" <file>`.
  - `Status` is `delivered` when the proof exists at an accepted commit; `open follow-up` with the tracking issue's URL when the item is tracked but not done; `unmapped` otherwise.
  - The clauses that can only become true at this child's merge (the final conformance and correctness reviews, required CI) share one row. Its proof is the pull request for issue 235, its status is `open follow-up` with https://github.com/fagenorn/nix-config/issues/235 as the tracking issue, and the verdict line carries the condition (EV12).

- [ ] **Step 5: Verify.**

```bash
set -euo pipefail
AUDIT=.agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md
test "$(git diff --numstat -- CLAUDE.md | cut -f1,2)" = "1	1"
test "$(grep -c 'tests/fixtures/retained-review-evidence/' CLAUDE.md)" -eq 1
if grep -q 'd0968f6a9ca20160' CLAUDE.md; then exit 1; fi
test -z "$(git status --porcelain -- AGENTS.md .agents/instructions)"
if grep -Eq '\| *unmapped *\|' "$AUDIT"; then echo "unmapped rows remain"; exit 1; fi
if grep -Eiq '(clos|fix|resolv)(e|es|ed|ing)? +(#226|https://github.com/fagenorn/nix-config/issues/226)' "$AUDIT" CLAUDE.md; then exit 1; fi
if grep -Eq '(^|[^&[:alnum:]/])#[0-9]+' "$AUDIT"; then echo "bare issue reference"; exit 1; fi
for n in 233 248 249 254 255 256; do grep -q "https://github.com/fagenorn/nix-config/issues/$n" "$AUDIT"; done
for sha in 93e6059a6fece769a621657c5889278b9cb9e0d7 218f5bc0bf3556fa05959e6ba24175685b58e2a9 7e17c8196569b0a96950f07ff886884690ffa224 8971e41802fd2ee4de8d1c85626ea1cdcf2d384d; do grep -q "$sha" "$AUDIT"; done
test "$(wc -c < "$AUDIT")" -le 26000
PYTHONPATH=python timeout 600 python3 -m unittest tests/test_review_evidence.py 2>&1 | tail -3
timeout 7200 just agent-workflow-tests 2>&1 | tail -3
test "$(git log --format=%H --no-merges 8971e41802fd2ee4de8d1c85626ea1cdcf2d384d..HEAD ^origin/main -- python | wc -l)" -eq 0
```

  An `unmapped` row is a finding, not something to reword away: if one remains after honest checking, leave it, let the gate fail and report the row, because it means the parent is not ready to close. The size bound is this task's forecast; a longer audit needs a committed forecast revision and a renewed G0 before it is committed, never a shortened row.

- [ ] **Step 6: Commit.** Stage only the two Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `docs(review): record evidence and audit parent 226 (#235)`. A review-fix commit uses `fix(review): address Task-4 review findings (#235)`.

- [ ] **Step 7: G1 and G3 (controller).** Run the plan root's closure check and G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 4` and check the actual-only equality. G3 follows.

## Forecast basis

Estimates. The `CLAUDE.md` record measured 11,594 B / +1 / −1 at planning with the sentence above, because the paragraph and its neighbours are very long lines, and is forecast at 13,312 B. The audit is priced from its row count: about sixty rows of about 330 B, the deliveries table and the prose, 26,000 B at most, which is a 28,672 B record with its lines and header, / +130.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":4,"records":[{"bounds":[{"added_lines":1,"boundary":"evidence","deleted_lines":1,"record_bytes":13312,"support":{"covers":["t4-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t4-1","last_task":4,"owner":4,"path":"CLAUDE.md"},{"bounds":[{"added_lines":130,"boundary":"evidence","deleted_lines":0,"record_bytes":28672,"support":{"covers":["t4-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t4-2","last_task":4,"owner":4,"path":".agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md"}]}}
```
