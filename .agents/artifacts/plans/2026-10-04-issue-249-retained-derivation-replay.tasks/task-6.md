# Task 6: Full-shape retained tier

The authoritative real-input acceptance for both commands and for SOURCE's models (spec § *Full-shape tier*; RP7, RP10, RP11; parent D8, D10, D14, D17). No `python/` byte changes.

**Files:**
- Modify: `justfile` (new recipe `agent-retained-tests root: build`, after `agent-installed-skill-tests`; final contribution)
- Create: `tests/test_review_retained_full.py`
- Modify: `tests/test_agent_tools_launchers.py` (new class `RetainedLauncherTest`; second contribution)

**Interfaces:**
- Consumes, with the real pins `TASK7_PINS`, `ISSUE_121_PINS`, `ISSUE_100_PINS`:
  - `review_issue121`: `classify(repo, pins)`, `contribution_edges(repo, pins, classes)`, `plan_anchors(repo, pins)`, `reconstruct_boundary(repo, pins, *, boundary, prerequisite, edges, table, task7_pins, authority)`, `ContributionError`.
  - `review_task7`: `derive_task7(repo, pins)`; `review_issue100`: `historical_records(issue_repo, pins)`, `fresh_records(issue_repo, pins, limits)`, `validate_100(payload, pins)`, `Issue100Error`.
  - `review_witness`: `authenticate(bundle_dir, expected)`, `validate_bundle(anchor, raw, *, task7_pins, issue121_pins, issue100_pins)`, `build_witness(components, payloads, raw)`, `build_anchor(components, raw)`, `ANCHOR_NAME`, `ANCHOR_MAX_BYTES`, `WitnessError`.
  - `review_actual.actual_inputs_from_trees(repo, base_tree, head_tree, *, base, head, commits, package_name, limits)`; `review_budget.describe`; `review_forecast.canonical_bytes`; `canonical.telemetry_digest`.
  - Commands, as `sys.executable -m agent_tools.derive_review_feasibility_fixtures` / `agent_tools.replay_retained` and as the built launchers; exit contract per the spec's table.
  - Support: `git`, `snapshot`, `rehash_edges`, `ssh_signer`, `source_budget_env` (source runs and `describe` use it; the ambient helper may lack `describe`). The launcher module's `AgentToolsLauncherTest`, its `dependency_env()`/`hostile_env()` and `retained_pair(command, args)` from Task 5.
- Produces the recipe:

```just
# Full-shape retained tier (#249): the real retained objects and archive under `root`. Not part of agent-workflow-tests.
agent-retained-tests root: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    log=$(mktemp "${TMPDIR:-/tmp}/agent-retained-XXXXXX") || exit 1; \
    trap 'rm -f -- "$log"' EXIT; \
    status=0; \
    AGENT_RETAINED_ROOT="{{root}}" AGENT_SKILLS_INSTALLED_HOME="$1" PYTHONPATH="{{agent_tools_path}}" \
      python3 -m unittest -v tests/test_review_retained_full.py tests/test_agent_tools_launchers.py \
      >"$log" 2>&1 || status=$?; \
    cat "$log"; \
    if [ "$status" -ne 0 ]; then exit "$status"; fi; \
    if grep -Eq '\.\.\. skipped|^OK \(.*skipped=' "$log"; then \
      echo "agent-retained-tests: a skipped test is not acceptance" >&2; \
      exit 1; \
    fi
```

**Invariants:**
- `RetainedFullTest` and `RetainedLauncherTest` raise a class-level `SkipTest` naming the recipe only when `AGENT_RETAINED_ROOT` is unset. When it is set, a missing commit (`fe85677c`, `65748f48`, `a7b7c6f4`, `cba57498`) or archive file fails `setUpClass`; nothing skips (RP10).
- Inputs: the archive is `<root>/.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f`; both issue repositories are `<root>`; the tool repository is the checkout holding the test file. `--tool-commit` is `AGENT_RETAINED_TOOL_COMMIT` when set, else `git rev-parse HEAD`; `setUpClass` fails unless `<that commit>:python` and `HEAD:python` are the same tree (parent D17).
- Every mutation happens in a disposable `git clone --shared --no-checkout <root> <tmp>` or in a copied bundle. Before and after each test the root's refs, index digest, `info/grafts`, `shallow`, `objects` listing and every archive file's bytes are compared strictly (RP11). Nothing writes the root.
- `setUpClass` keeps `cls.table = derive_task7(root, TASK7_PINS)`, `cls.authority`, and one bundle derived into scratch through the source command; `derive_cli(**overrides)` runs that command with one input replaced, and `disposable_clone()` returns a fresh clone. Tests copy the bundle before altering it.
- Renderer run (parent D10): stage every distinct `(renderer_path, renderer_blob)` of `TASK7_PINS.renderers` with `git cat-file blob` into a scratch `HOME`, laid out as the pinned Task-7 brief (blob `TASK7_PINS.task7_blob`, section on the staging `HOME`) prescribes; run by command name on a scratch `PATH`; `GIT_CONFIG_GLOBAL` is a scratch config with `gpg.format=ssh` and an ephemeral `ssh-keygen` key; `plan`, then `apply --plan-id`, in a disposable clone checked out at `TASK7_PINS.prerequisite_commit`. `verify --register` is never run and the user's key and Git config are never read. The pinned `apply` runs its own commit gates; give it a long timeout. At the pinned commit it stops at `workflow-verification-commands` with its five other gates passed and makes no commit (RP23): assert exactly that stop, and treat any other gate failure as a test failure.
- Neither new file contains a token of `LEGACY_POLICY_SURFACE` (`home/common/agent-skills/tests/test_workflow_skill_contracts.py`); `just agent-workflow-tests` refuses one. If the renderer run cannot be written without one, stop and report `NEEDS_CONTEXT`.
- The recipe is not listed in `agent-workflow-tests`.

- [ ] **Step 1: Write the tests.** `tests/test_review_retained_full.py` holds one `RetainedFullTest`. Write this case in full:

```python
    def test_grafted_clone_reproduces_i1_and_every_entry_point_refuses(self):
        clone = self.disposable_clone()
        clean = contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        self.assertEqual(len(clean), 30)
        target, parent, extra = clean[10]["commit"], clean[10]["parent"], clean[3]["commit"]
        forged = [*clean[:11], *rehash_edges([{**clean[10], "parent": extra, "parent_ordinal": 2}]), *clean[11:]]
        self.assertEqual(len(forged), 31)
        (clone / ".git/info").mkdir(exist_ok=True)
        (clone / ".git/info/grafts").write_text(f"{target} {parent} {extra}\n")
        for edges in (clean, forged):
            with self.assertRaises(ContributionError):
                reconstruct_boundary(clone, ISSUE_121_PINS, boundary="tasks-1", prerequisite={"kind": "delivery-base"},
                                     edges=edges, table=self.table, task7_pins=TASK7_PINS, authority=self.authority)
        with self.assertRaises(ContributionError):
            contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        out = self.tmp / "derive-grafted"
        done = self.derive_cli(issue_121_repo=clone, output_dir=out)
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertRegex(done.stderr.decode(), r"\Aderive-review-feasibility-fixtures: invalid: [a-z0-9_]+\n\Z")
        self.assertFalse(out.exists())
```

  Add these named cases with exact assertions (the spec's five checks and its closing paragraph):
  - `test_real_assignments_anchors_and_task7_counts`: 30 edges, 12 process and 18 task commits; `plan_anchors` matches both pinned plan blobs; the table's `counts` are `{paths: 173, moves: 165, specs: 54, plans: 108, decisions: 3, rewrites: 5, additions: 3}` and `observed_actual` is `None`.
  - `test_pinned_renderer_output_within_row_bounds`: the renderer run; every record of the tree `apply` staged in its retained worktree (`git write-tree`), measured with `actual_inputs_from_trees` over the prerequisite tree and that tree (RP23), has `source_bytes` at most the `record_bytes` of the table row whose `new_path` is its path, each record matches exactly one row and each row at most one record. The run's migration map and evidence record are named by the actual plan digest (`adopt_planning.adoption_records(plan_id)`), while their rows carry `DIGEST_PLACEHOLDER`: map those two paths to their placeholder rows from the `plan_id` the `plan` step returned before matching.
  - `test_issue100_domains_are_exact_and_distinct`: historical 1,005,707 B / 115 records, fresh 1,012,913 B / 115, digests differ; the derived payload with its two table policies swapped fails `validate_100`.
  - `test_two_derivations_are_byte_identical`: a second source-command derivation equals the class bundle file by file; both summaries are equal canonical bytes; the anchor is at most `ANCHOR_MAX_BYTES`.
  - `test_dirty_or_mismatched_tool_tree_refuses`: in a disposable clone of the tool repository, `--tool-commit` naming a commit whose `python` tree differs from the running package → exit 2, `invalid: tool_closure`, no output.
  - `test_replay_with_sources_unreachable`: a copied bundle, `cwd` and `HOME` in scratch, a `PATH` holding only a directory without `git` or `artifact-budget`. Assert the spec's exit table for whatever the proof produced: exit 0 with a canonical v3 result and empty stderr, or exit 2 with empty stdout and one `replay-retained: projection_unavailable: <ids>` line whose ids are in outcome order. Never assert a named status.
  - `test_substitutions_refused_under_the_trusted_digest`: in copies, change each of: one member of each component group in the anchor; one record digest in each payload; one edge reference; then recompute every in-bundle hash (members, witness, anchor). Replay with the original digest → `invalid: anchor_digest` or `invalid: member_digest` every time (RP7 layer 1).
  - `test_git_free_substitutions_refused_under_trust_injection`: the same edits for every pin-determined component member and every cross-table reference, passed to `validate_bundle` with the rebuilt anchor → `WitnessError`, `EstimateError`, `ContributionError` or `Issue100Error`; a malformed issue-100 payload and a truncated estimate beside the unaltered issue-121 payload are each invalid (RP7 layer 2). `tool.commit` and re-measured record bytes are not in this list.
  - `test_outputs_hold_no_bodies_paths_or_credentials`: no output file contains a line of any archive shard longer than 40 bytes, the scratch path, `HOME`, the ephemeral key's bytes, or a line of `artifact-budget-policy.json` longer than 16 bytes after stripping (punctuation-only lines such as `{` occur in every canonical bundle).

  In the launcher module, `RetainedLauncherTest(AgentToolsLauncherTest)` derives with the built launcher under `hostile_env()` and with the source module, into two scratch directories, and requires equal summaries and byte-identical bundles; then replays one bundle both ways with `retained_pair` and requires identical outcomes. The root comparison above brackets it.

- [ ] **Step 2: Watch it fail.** `just agent-retained-tests /Users/anis/tmp/nix-config` → unknown recipe. Running the module without the variable skips, which is never acceptance.

- [ ] **Step 3: Add the recipe** exactly as above.

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PIN=<the G2 source commit>
AGENT_RETAINED_TOOL_COMMIT="$PIN" just agent-retained-tests /Users/anis/tmp/nix-config 2>&1 | tail -6
just agent-installed-skill-tests 2>&1 | tail -3
just agent-workflow-tests 2>&1 | tail -3
if just --show agent-workflow-tests | grep -q retained_full; then exit 1; fi
test "$(git diff --name-only "$PIN" HEAD -- python | wc -l)" -eq 0
```

  The retained run ends `OK` with no `skipped`, and must be quiescent (RP11): if the root comparison differs, the run is void and is repeated. To see the skip guard fail, run the recipe with a temporary `self.skipTest("probe")` in one test: it must exit 1.

- [ ] **Step 5: Commit.** Stage only the three Files; subject at most 64 bytes: `test(review): add full-shape retained derivation tier (#249)`. A review-fix commit uses `fix(review): address Task-6 review findings (#249)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence`, then renew G0 at `--completed-through 6`, which equals the actual gate (RP14). G3 follows.

## Forecast basis

Parent D15 price plus about ten percent:
- Full-shape module: 620 lines / 32,500 B → 33,632 → 36,864 B / +680.
- Launcher module, cumulative with Task 5 (modify, U10): about 190 added lines → 20,480 B / +215 / −6.
- `justfile`, cumulative: the three list lines plus a second hunk of 19 recipe lines → 6,144 B / +24 / −0.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"7af9fdfc8e4d55b04ab5ef72d2386d7a28e1e5cb","head":"2fd142b97ef9c6d530144253fcbf73d72d3f262e"},{"base":"fbb8a676d0a0655d9434d18acf88e4c878509b51","head":"e6f9adc66fd0751f25c19ab2bb848f68d45df641"}],"commit_subject_bytes":[64,64],"id":6,"records":[{"bounds":[{"added_lines":24,"boundary":"replay","deleted_lines":0,"record_bytes":6144,"support":{"covers":["t2-4","t3-4","t4-4","t6-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t6-1","last_task":6,"owner":6,"path":"justfile"},{"bounds":[{"added_lines":680,"boundary":"replay","deleted_lines":0,"record_bytes":36864,"support":{"covers":["t6-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t6-2","last_task":6,"owner":6,"path":"tests/test_review_retained_full.py"},{"bounds":[{"added_lines":215,"boundary":"replay","deleted_lines":6,"record_bytes":20480,"support":{"covers":["t5-2","t6-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t6-3","last_task":6,"owner":6,"path":"tests/test_agent_tools_launchers.py"}]}}
```
