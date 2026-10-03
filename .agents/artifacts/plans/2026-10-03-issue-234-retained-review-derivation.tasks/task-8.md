# Task 8: Full-shape retained tier

**Files:**
- Modify: `justfile` (new recipe `agent-retained-tests root: build`; final contribution)
- Create: `tests/test_review_retained_full.py`
- Modify: `tests/test_agent_tools_launchers.py` (new `RetainedLauncherTest` class; second contribution)

**Interfaces:**
- Consumes: every library entry from Tasks 1–6 with the real pins; `snapshot` from the support module; the Task-7 launchers. Recipe variables: `AGENT_RETAINED_ROOT` and `AGENT_SKILLS_INSTALLED_HOME` (D14).
- Produces the recipe below. It is not listed in `agent-workflow-tests`, so CI does not run it (D8).

```just
# Full-shape retained tier (#234 D8, D14): needs the checkout holding the retained objects and archive.
agent-retained-tests root: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then echo "expected exactly one built home-manager-files output; found $#" >&2; exit 1; fi; \
    AGENT_RETAINED_ROOT="{{root}}" AGENT_SKILLS_INSTALLED_HOME="$1" PYTHONPATH="{{agent_tools_path}}" \
      python3 -m unittest -v tests/test_review_retained_full.py tests/test_agent_tools_launchers.py
```

The existing launcher class also runs under this recipe, and it must pass there too.

**Invariants:**
- An unset `AGENT_RETAINED_ROOT` gives a class-level `SkipTest` that names the recipe, following the `AGENT_SKILLS_INSTALLED_HOME` precedent. When it is set, a missing commit (`fe85677c`, `65748f48`, `a7b7c6f4`, `cba57498`, `55cef035`) or archive file fails the run. It never skips.
- The archive is `<root>/.superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f`. The issue-121 and issue-100 repositories are both `<root>`. The tool repository is the recipe checkout, with `--tool-commit` equal to `git rev-parse HEAD`. The controller's authoritative run happens at the reviewed pin (D13).
- Every mutation runs in a disposable clone (`git clone --shared --no-checkout <root> <tmp>`, alternates-backed) or a copied bundle. The root's refs, index, `info/grafts`, `objects/` listing and archive bytes are compared before and after every test.
- The D10 renderer run follows these rules:
  - Stage the pinned `adopt-project.py`, its five libraries, `resolve-project.py` and `platform-manifest.json` into a scratch `HOME`, using `git cat-file` from `fe85677c` exactly as the signed Task-7 brief stages them.
  - Run by command name on a scratch `PATH`.
  - Set `GIT_CONFIG_GLOBAL` to a scratch config whose `user.signingkey` is an ephemeral `ssh-keygen` key, with `gpg.format=ssh`.
  - Run `plan`, then `apply --plan-id`, in a disposable worktree of the pinned tree.
  - Never use `verify --register`.
  - Never read the user's key or `~/.config/git/config`.

  The pinned apply runs its own commit gates, including the pinned tree's `just build` and `agent-workflow-tests`. Let them run and give the test a long timeout. A gate failure is a test failure to investigate, not a skip.

- [ ] **Step 1: Write the tests.** `tests/test_review_retained_full.py` holds one `RetainedFullTest` class whose `setUpClass` resolves the inputs above. Write this key case in full:

```python
    def test_grafted_clone_reproduces_i1_and_both_entry_points_refuse(self):
        clone = self.disposable_clone()
        clean = contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        self.assertEqual(len(clean), 30)
        target, parent = clean[10]["commit"], clean[10]["parent"]
        (clone / ".git/info/grafts").write_text(f"{target} {parent} {clean[3]['commit']}\n")
        with self.assertRaises(ContributionError):
            contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        with self.assertRaises(ContributionError):
            reconstruct_boundary(clone, ISSUE_121_PINS, boundary="tasks-1", prerequisite={"kind": "delivery-base"},
                                 edges=rehash_with_extra(clean, target, clean[3]["commit"]),
                                 table=self.table, task7_pins=TASK7_PINS, authority=self.authority)
        out = self.tmp / "derive-grafted"
        done = self.derive_cli(issue_121_repo=clone, output_dir=out)
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertFalse(out.exists())
        self.assertEqual(snapshot(self.root), self.root_snapshot)
```

  Add these named cases with exact assertions, covering the spec's full-shape column:
  - `test_real_assignments_and_anchors`: 30 edges, 12 process commits and 18 task commits; `8e6f0681` is Task 3; both plan blobs pinned.
  - `test_task7_counts_on_pinned_tree`: 173/165/54/108/3/5/3; `observed_actual` is null; Task 8 has 0 bytes and is unexecuted.
  - `test_pinned_renderer_output_within_row_bounds`: the D10 run. Every record of the single adoption commit, measured with `actual_inputs_from_trees`, is at most its row's `record_bytes`.
  - `test_issue100_domains_and_counts`: 1,005,707/115 and 1,012,913/115 are distinct; a label swap fails; 543/115/8-38-69 (65+4)/4/0; every criterion holds; the archive is byte-identical.
  - `test_two_derivations_byte_identical_and_bounded`
  - `test_replay_with_sources_unreachable`: copy the bundle, run replay with `cwd` and `HOME` in scratch, and assert the D7 exit/stdout/stderr contract for whichever outcomes the proof produced.
  - `test_component_and_reference_substitutions_with_recomputed_hashes_refused`: tool, source, tree, archive and estimate components, record digests and references. Rehash every payload and the anchor, then replay against the new digest and expect `invalid:`.
  - `test_trust_injection_malformed_sibling_is_invalid`: call `validate_bundle` directly.
  - `test_outputs_hold_no_bodies_paths_or_credentials`: no shard body line, scratch path, `HOME`, key material or policy file text appears in the outputs.

  In the launcher module, `RetainedLauncherTest` skips like the class above when `AGENT_RETAINED_ROOT` is unset. It derives with the built `derive-review-feasibility-fixtures` and the source module under a hostile `PYTHONPATH`/`NIX_PYTHON*`, and asserts byte-identical bundles and summaries. Built and source `replay-retained` must give an identical exit, stdout and stderr, and the inputs must be unchanged.
- [ ] **Step 2: Watch the tests fail.** Before the recipe exists, `just agent-retained-tests <root>` fails with an unknown recipe. Running the module without the variable skips, which is not acceptance.
- [ ] **Step 3: Add the recipe.** Add it exactly as above, after `agent-installed-skill-tests`.
- [ ] **Step 4: Verify.** Run `just agent-retained-tests /Users/anis/tmp/nix-config` with zero failures and zero skips. Run `just agent-workflow-tests`, which must not list the new module. To confirm the check can fail: `grep -c agent-retained-tests justfile` printed `0` before Step 3.
- [ ] **Step 5: Commit.** Stage only these three files and commit `test(review): add full-shape retained derivation tier (#234)`.

## Forecast basis

Estimates per D15:
- Full test: 600 lines / 33,000 B → 34,112.
- Launcher module: second contribution, adding 140 lines / 8,000 B for a cumulative 22,528 B / +316 / −12.
- `justfile`: final contribution, a separate hunk of about 12 lines, for a cumulative 6,144 B / +24 / −1.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":8,"records":[{"bounds":[{"added_lines":24,"boundary":"derive","deleted_lines":1,"record_bytes":6144,"support":{"covers":["t1-4","t2-4","t3-4","t4-3","t5-5","t6-4","t8-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-1","last_task":8,"owner":8,"path":"justfile"},{"bounds":[{"added_lines":600,"boundary":"derive","deleted_lines":0,"record_bytes":34112,"support":{"covers":["t8-2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t8-2","last_task":8,"owner":8,"path":"tests/test_review_retained_full.py"},{"bounds":[{"added_lines":316,"boundary":"derive","deleted_lines":12,"record_bytes":22528,"support":{"covers":["t7-2","t8-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t8-3","last_task":8,"owner":8,"path":"tests/test_agent_tools_launchers.py"}]}}
```
