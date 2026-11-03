# Delivery Family Move Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Move `workflow-state`, the delivery runtime with its wire and builder modules, the delivery model and the budget validator into `agent_tools`, deploy `workflow-state` and `artifact-budget` as package launchers with no `~/.agents/lib/python`, name the delivery format for delivery, and prove a pre-move ledger still progresses (https://github.com/fagenorn/nix-config/issues/178).

**Architecture:** Task 1 is the one atomic move (D1): ten `git mv`s, the loader, handshake and `__file__` deletions (D4–D6), the two command rows, the suites' re-points (D8, D16–D18), the installed floor (D10) and the living documents (D11, D19). Task 2 renames `canonical_bytes`/`canonical_digest` to `delivery_bytes`/`delivery_digest`, alone (D3). Task 3 adds the base-helper ledger replay that covers both (D7, D13).

**Tech stack:** Python 3 standard library (`unittest`, subprocess round trips), nixpkgs `buildPythonPackage` through `lib/agent-tools.nix`, Home Manager, `just`, bash, Markdown.

Spec (source of truth; read it whole): `.agents/artifacts/specs/2026-11-03-issue-178-delivery-family-move-design.md`. A bare "Dn" cites its `## Decision ledger`; "parent Dn" and "#177 Dn" cite the specs it names.

## Global Constraints

- Base `f6a48dcf66fbb2171f66920c32afd4f9e5056a93` (tree `5d3433e22a707472fc57364974e2741deee2c025`): the delivery base, and Task 3's pinned pre-move helper.
- Command names, `~/.agents/bin` and `~/.agents/share` paths, argv/stdin/stdout/exit contracts, `--help` bytes, sealed delivery digests and stored ledgers do not change (parent D15); the only deleted refusals are D4's. `SCHEMA_VERSION = 11`, `CONTROL_INTERFACE_VERSION = 4`, `DIRECT_OWNER_INTERFACE_VERSION = 2`, `DIRECT_OWNER_REQUEST_INTERFACE_VERSION = 3` and the wire kinds stay.
- Each move is `git mv`, and its content edits are exactly Task 1's list for that file: no reformatting, reflow, split function or renamed helper beyond D3 (parent D14). The shebang and executable bit go; the `__main__` block stays; imports left unused go.
- Pre-existing assertions stay unedited apart from D4's deletions and re-homings, D3's rename and location literals.
- A living document naming a moved path is re-pointed in the move's commit; point-in-time records under `.agents/artifacts` keep their paths. `CLAUDE.md` does not grow (Instruction Budget).
- Scope is the spec's `## Out of scope`: the packaged-ahead callers keep their by-name `PATH` calls (D6); `python/README.md`, `review_budget`, `review_feasibility` and the policy file are not edited (D12); `artifact_budget` keeps its local hooks (D9).
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit; code prose cites "#178", never a bare `Dn`.
- Never run `nixfmt` or `just switch`; never push. Flakes see tracked files only: `git add` before `just build`.
- Run every command from the worktree root, in the foreground, with an explicit timeout, as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`; scratch goes under `launch-scope scratch`; commits go through `launch-commit` with the same three values, SSH-signed, subjects at most 64 bytes, ending with the session's trailer lines.
- Final gate (sdd runs it once, on the final head), each with timeout 3600 s: `just build`; `WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`; the same with `HOME` set to a new empty directory (D17); `just agent-installed-skill-tests`.

## Test seams

- **Seam 1, from source** (parent D9): suites run under the recipe's `PYTHONPATH`, through `-m` children, `-m` `PATH` shims, normal imports and the in-process runner given `workflow_state`'s source file (D8, D15). Each workflow-state run reads the policy from a test `HOME`'s share (D5, D17). Task 3's replay archives the base commit's package, `scripts` and policy (D7, D16).
- **Seam 2, installed layout:** `tests/test_agent_tools_launchers.py` under `just agent-installed-skill-tests` (D10).
- Seam 3, the guard's registered hook, is untouched. The `--help` identity and the demo are shown, not committed (Tasks 1 and 3).

## Delivery estimate and boundaries

- One boundary, `all`: the move cannot be split (D1), and Tasks 2 and 3 depend on it.
- Each moved file is forecast as a whole-file delete plus a whole-file add (D20). The `workflow_state` add alone is about 290 KB against the 65,536-byte member bound, so the projection overflows `member_bytes` and `aggregate_bytes` whatever the boundary: the delivery is not reviewable as one package under the current record policy.

## Task index

Task 1 — Move the delivery family into the package — 10 × `git mv` `home/common/agent-skills/scripts/…` → `python/agent_tools/…`, the wrapper's deletion, 4 package docstrings, `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `.agents/project.json`, 7 living documents, 24 test files — full — [task-1.md](2026-11-03-issue-178-delivery-family-move.tasks/task-1.md)

Task 2 — Name the delivery format for delivery — `python/agent_tools/delivery_model/*`, `workflow_state.py`, `workflow_delivery.py`, `workflow_delivery_build.py`, 14 test files — full — [task-2.md](2026-11-03-issue-178-delivery-family-move.tasks/task-2.md)

Task 3 — Replay a pre-move ledger across the move — `home/common/agent-skills/tests/test_delivered_control.py` — low-risk — [task-3.md](2026-11-03-issue-178-delivery-family-move.tasks/task-3.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code (classified) | Task 1 | `tests/test_agent_tools_launchers.py` under `just agent-installed-skill-tests`: `test_the_command_table_generates_each_deployed_command` (floor with `artifact-budget`, `workflow-state`, `review-package`), `test_a_hostile_agent_tools_on_every_channel_is_ignored` and `test_each_hostile_channel_is_live_without_the_launcher` |
| AC2 | code (classified) | Task 1 | the `.agents/lib/python` `lexists` assertion in `test_the_command_table_generates_each_deployed_command`; Task 1 Step 6 gate 6's `lib/python` grep |
| AC3 | code (classified) | Task 1 | Task 1 Step 6 gate 6: the handshake/loader/`sys.path` grep over `python` prints nothing, and `importlib` appears only in `review_witness.py` |
| AC4 | code (classified) | Task 2 | Task 2 Step 4 gates 1–2 and `home/common/agent-skills/tests/test_delivery_model.py::DeliveryModelTest::test_import_is_pure_and_interface_is_exact` |
| AC5 | code (classified) | Task 1 | Task 1 Step 6 gate 6: `__file__` only in `adopt_references.py`, and `git ls-files home/common/agent-skills/scripts` empty |

## Decisions

The spec's D1–D15 bind. Planning appended D16 (the attempt-migration replay runs its own package), D17 (every suite `HOME` holds the policy; the empty-`HOME` gate), D18 (`source_budget_env` follows the source tree's layout), D19 (four more living-document re-points) and D20 (moves forecast as delete plus add; one boundary).

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"f6a48dcf66fbb2171f66920c32afd4f9e5056a93","kind":"git-range-ownership/v1","process_ranges":[],"tree":"5d3433e22a707472fc57364974e2741deee2c025"},"boundaries":[{"acceptance":"Issue 178 complete: AC1-AC5 green under the focused suites, the empty-HOME and source just agent-workflow-tests, just agent-installed-skill-tests and just build","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2","t3"],"process_package":{"plan":".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.md","spec":".agents/artifacts/specs/2026-11-03-issue-178-delivery-family-move-design.md","tasks":[".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-1.md",".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-2.md",".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-3.md"]},"tasks":[1,2,3]}],"delivery_base":"f6a48dcf66fbb2171f66920c32afd4f9e5056a93","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":572,"boundary":"all","deleted_lines":0,"record_bytes":51200,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":3,"owner":0,"path":".agents/artifacts/specs/2026-11-03-issue-178-delivery-family-move-design.md"},{"bounds":[{"added_lines":126,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.md"},{"bounds":[{"added_lines":628,"boundary":"all","deleted_lines":0,"record_bytes":57344,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-1.md"},{"bounds":[{"added_lines":152,"boundary":"all","deleted_lines":0,"record_bytes":16384,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-2.md"},{"bounds":[{"added_lines":223,"boundary":"all","deleted_lines":0,"record_bytes":15360,"support":{"covers":["t3"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t3","last_task":3,"owner":0,"path":".agents/artifacts/plans/2026-11-03-issue-178-delivery-family-move.tasks/task-3.md"}],"proposed_boundary":"all","schema_version":3}
```
