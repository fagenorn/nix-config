# Task 7: Skill rewrite, contract, evals, ceilings

**Files:**
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md` (rewrite)
- Modify: `home/common/agent-skills/skills/ship-release/CHANGELOG.md` (two references only)
- Modify: `home/common/agent-skills/skills/ship-release/evals/evals.json`
- Modify: `home/common/agent-skills/tests/test_ship_release_contracts.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (the
  `SHARED_POLICY_ENTRIES` row for `ship-release/SKILL.md` only)
- Modify: `home/common/agent-skills/instruction-load.json` (ceilings, through `tighten`)

**Interfaces:**
- Consumes Task 4's CLI (`release.build_parser()` parses every example) and Tasks 2–6's
  refusal codes, `next` values, `status` members (`reason`, `legacy`) and D17's tokens.
- Produces the skill text Task 8 measures; this commit is the AC5 candidate (D24).

**Invariants** (§8, D9, D10, D17; agent-helpers rule 6):
- `SKILL.md` is at most 9,400 bytes (`wc -c`). Its sections, in order:
  1. Frontmatter: `name: ship-release`, a rewritten `description` no longer than the
     current one, still triggered by "release" and "ship to prod", and an `argument-hint`.
  2. `# Ship Release`: one paragraph. The unit of work is `origin/<integration>`'s
     verified tip, released through the release core.
  3. `## Ownership`:
     - the existing marker line verbatim,
       `<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus effort=high -->`;
     - the `Agent(...)` line after it verbatim;
     - the direct-invocation sentence;
     - D17's delegated return: the owner ends at the preview and returns its JSON. The
       controller relaunches one owner with the user's answer, and that owner re-runs
       `preview` with the same arguments and runs only on equal tokens.
  4. `## Project bindings (resolve first)`: exactly one `resolve-project resolve` occurrence
     in the whole file, in `Run \`resolve-project resolve --repo-root <checkout>\`.`,
     followed verbatim by the existing resolution and refusal sentences
     (`RESOLUTION_SENTENCE`, `REFUSAL_REPORTING_SENTENCE` in
     `test_workflow_skill_contracts.py`). It names `bindings.vcs` and `bindings.tracker`
     only.
  5. `## Authorization`:
     - invoking the skill authorizes the reversible predeclared set;
     - the preview is the one stop, and both irreversible confirmations are collected
       there in one turn;
     - silence or any other reply is never yes;
     - a changed version needs a new preview.
  6. `## Doc-grounded escalations`, kept as is.
  7. `## Phase 0 — Pre-flight`, in this order (D28):
     - main checkout, clean tree, `git fetch origin --prune --tags`, and local
       `<integration>` in sync with origin;
     - then `release transaction status`. A nonterminal release goes straight to
       Phase 3 in resume form, skipping the next item, and `legacy` or `shape` refusals
       are reported, not worked around;
     - only with no nonterminal release, "nothing to release" against the previous tag,
       keeping the line `git describe --tags --abbrev=0 origin/<default>`.
  8. `## Phase 1 — Changelog`: read `CHANGELOG.md` first. The template's body becomes the
     notes, written with the file-writing tool to a path outside both working trees.
  9. `## Phase 2 — Version`:
     - the previous tag line, exactly
       `git for-each-ref --count=1 --merged "$COMMIT" --sort=-v:refname --format='%(refname:short)' 'refs/tags/v[0-9]*'`,
       with `COMMIT` set in the same call;
     - the bootstrap `v0.1.0` rule, with no silent `v1.0.0`;
     - the rubric link `CHANGELOG.md#version-bump-signals`.
  10. `## Phase 3 — Preview`:
      - the preview examples;
      - one bounded CI wait on `verification_pending`;
      - present the confirmations, then stop and end the turn.
  11. `## Phase 4 — Run`:
      - the run examples;
      - `next`: re-run on `wait`, re-preview on `confirm`, report on `attention`;
      - the abandon example, run only on the user's explicit word and only when no action
        took effect.
  12. `## Phase 5 — Report`:
      - rendered only from `release transaction status`;
      - a parked release is reported with its `reason`, never as released, with resume
        offered, plus `abandon` when no action took effect;
      - tags are never deleted.
- The only `release transaction` example lines, each alone on a line inside a fenced block:

```text
release transaction status --repo-root <main-checkout>
release transaction preview --repo-root <main-checkout> --commit <commit> --version <version> --title "<title>" --notes-file <notes-path>
release transaction preview --repo-root <main-checkout>
release transaction run --repo-root <main-checkout> --commit <commit> --version <version> --title "<title>" --notes-file <notes-path> --confirm <token> --confirm <token>
release transaction run --repo-root <main-checkout> --confirm <token>
release transaction abandon --repo-root <main-checkout>
```

- **Deleted:** all of §8's "What it deletes" list. Write the remaining prose from the
  implemented commands' behaviour.
- **`CHANGELOG.md`.**
  - Line `(SKILL.md §5d)`: drop that parenthetical only.
  - `[\`SKILL.md\` Phase 4.5d](./SKILL.md#45d-decide-major--minor--patch)`: becomes
    `[\`SKILL.md\` Phase 2](./SKILL.md#phase-2--version)`.

  Nothing else in the file changes.
- **`evals.json`.**
  - Four `plan-only` cases (§8):
    - a nix-config preview naming `tag` and `github-release`, then stopping on silence;
    - re-entry through `status` into a resume preview;
    - the `legacy_release_in_flight` refusal;
    - the `merge_not_declared` two-branch refusal.

    Each prompt carries a `plan-only` or `dry-run` guard.
  - One `pipeline` case, `setup.kind` `release-ready`, prompt containing `kind=none`. Its
    expected output is the resolver refusal reported byte for byte, and no tag. Its asserts
    keep "origin carries no new tag" and add one for no new local `v*` tag:
    `[ "$(git -C "$REPO" tag -l 'v*')" = v0.1.0 ] || fail "local tags: $(git -C "$REPO" tag -l | tr '\n' ' ')"`.
  - `notes` is rewritten to match.
- **Ceilings (D10).** `instruction_load tighten` after the rewrite; its diff touches only the
  `ship-release` and `release-owner` `ceiling_bytes`, plus `corpus_ceiling_bytes` and
  `description_ceiling_bytes` when lowered.

- [ ] **Step 1: Rewrite the contract tests (red against the old skill)**

In `test_ship_release_contracts.py`:
- Delete `test_merge_sha_command_targets_local_default_not_remote`,
  `test_merge_sha_command_resolves_local_merge_in_a_real_repo`,
  `test_forge_less_skip_check_reads_the_tags_at_the_merge_sha`,
  `test_release_creation_uses_the_guarded_spelling`,
  `test_phase_zero_reads_the_state_file_and_merged_prs`,
  `test_durable_state_names_every_field` and
  `test_phase_five_polls_the_registered_adapter_command`.
- Drop helpers that only those tests used.
- Update the module docstring: it now pins the release-command examples, the dispatch
  marker and the cross-file anchors. In the two previous-tag tests, `$MERGE_SHA` becomes
  `$COMMIT`: in the asserted `--merged "$COMMIT"` and in `extra_env={"COMMIT": merge_sha}`.
- Replace `test_cross_file_anchors_resolve`, and add the rest:

```python
    def test_cross_file_anchors_resolve(self):
        self.assertIn("CHANGELOG.md#version-bump-signals", self.skill)
        self.assertIn("## Version bump signals", self.changelog)
        self.assertIn("](./SKILL.md#phase-2--version)", self.changelog)
        self.assertIn("\n## Phase 2 — Version\n", self.skill)
        for gone in ("§5d", "#45d-"):
            self.assertNotIn(gone, self.changelog)

    def test_skill_names_no_legacy_state(self):
        for gone in (".superpowers/workflows", "state.json", "headSha", "mergeSha", "prUrl",
                     "releaseUrl", "deployState", "gh pr create", "gh pr merge",
                     "gh release create", "git tag -a", "--auto"):
            self.assertNotIn(gone, self.skill)

    def test_release_examples_parse_and_cover_every_subcommand(self):
        from agent_tools import release
        lines = [line for line in self.skill.splitlines()
                 if line.startswith("release transaction ")]
        actions = set()
        for line in lines:
            with self.subTest(line=line):
                args = release.build_parser().parse_args(shlex.split(line)[1:])
                self.assertEqual(args.area, "transaction")
                actions.add(args.action)
        self.assertEqual(actions, {"status", "preview", "run", "abandon"})
        self.assertEqual(len(lines), 6)

    def test_status_is_read_before_nothing_to_release(self):
        phase0 = self.skill.split("## Phase 0", 1)[1].split("\n## ", 1)[0]
        self.assertLess(phase0.index("release transaction status"),
                        phase0.index("git describe --tags --abbrev=0"))

    def test_ownership_keeps_the_dispatch_marker_and_one_resolver_call(self):
        marker = ("<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus "
                  "effort=high -->")
        self.assertEqual(self.skill.count(marker), 1)
        self.assertEqual(self.skill.count("resolve-project resolve --repo-root <checkout>"), 1)
```

Add `import shlex`. Keep `test_prev_tag_selection_is_reachability_restricted`,
`test_prev_tag_command_ignores_unreachable_tags_in_a_real_repo` (as edited) and
`test_evals_cover_the_fixture_shape_and_release_only_in_the_sandbox` unchanged otherwise.
`agent_tools` imports because the suite runner sets `PYTHONPATH=python`.

In `test_workflow_skill_contracts.py`, set `SHARED_POLICY_ENTRIES["ship-release/SKILL.md"]`
to `("bindings.tracker", "bindings.vcs")`.

- [ ] **Step 2: Run the contract and watch it fail**

Run the root's suite form on `home/common/agent-skills/tests/test_ship_release_contracts.py`.
Expected: FAIL against the old skill (legacy state, anchors, examples).

- [ ] **Step 3: Rewrite `SKILL.md`, edit `CHANGELOG.md` and `evals.json`, tighten**

Write the skill to the Invariants. Then run:
`PYTHONPATH=python python3 -m agent_tools.instruction_load tighten --root .`
Inspect `git diff --stat -- home/common/agent-skills/instruction-load.json` against the
Ceilings invariant.

- [ ] **Step 4: Verify**

```bash
set -euo pipefail
test "$(wc -c < home/common/agent-skills/skills/ship-release/SKILL.md)" -le 9400
PYTHONPATH=python python3 -m agent_tools.suite_runner \
  home/common/agent-skills/tests/test_ship_release_contracts.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py \
  home/common/agent-skills/tests/test_eval_cases.py \
  home/common/agent-skills/tests/test_instruction_load.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_skill_lint.py \
  home/common/agent-skills/tests/test_shell_example_contracts.py 2>&1 | tail -4
PYTHONPATH=python python3 -m agent_tools.instruction_load check --base origin/main
```

Expected: every command exits 0, and the suite prints `summary members=7 passed=7 failed=0`.

Run: `just build` in the foreground with a timeout of at least 30 minutes. Skill files are
in the home-manager closure.
Expected: exit 0.

- [ ] **Step 5: Commit** exactly the Files paths, subject `feat(issue-128/T7): ship-release becomes a release-core client`.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64,64],"id":7,"records":[{"bounds":[{"added_lines":150,"boundary":"all","deleted_lines":316,"record_bytes":36864,"support":{"covers":["r7a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7a","last_task":7,"owner":7,"path":"home/common/agent-skills/skills/ship-release/SKILL.md"},{"bounds":[{"added_lines":2,"boundary":"all","deleted_lines":2,"record_bytes":8192,"support":{"covers":["r7b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7b","last_task":7,"owner":7,"path":"home/common/agent-skills/skills/ship-release/CHANGELOG.md"},{"bounds":[{"added_lines":45,"boundary":"all","deleted_lines":42,"record_bytes":16384,"support":{"covers":["r7c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7c","last_task":7,"owner":7,"path":"home/common/agent-skills/skills/ship-release/evals/evals.json"},{"bounds":[{"added_lines":75,"boundary":"all","deleted_lines":130,"record_bytes":20480,"support":{"covers":["r7d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7d","last_task":7,"owner":7,"path":"home/common/agent-skills/tests/test_ship_release_contracts.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":1,"record_bytes":4096,"support":{"covers":["r7e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7e","last_task":7,"owner":7,"path":"home/common/agent-skills/tests/test_workflow_skill_contracts.py"},{"bounds":[{"added_lines":6,"boundary":"all","deleted_lines":6,"record_bytes":4096,"support":{"covers":["r7f"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r7f","last_task":7,"owner":7,"path":"home/common/agent-skills/instruction-load.json"}]}}
```
