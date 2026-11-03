# Task 3: `tag` and `release` target the merge commit

Per D7, D8 and D17; spec §5. Read the plan root's Global Constraints first.

**Files:**
- Modify: `python/agent_tools/forge_adapter.py` (new `_released`; `_tag_state`, `_inspect_tag`, `_inspect_release`, `_contained`, `_invoke`'s `tag` branch, module docstring)
- Modify: `tests/fixtures/forge-adapter-spellings.json` (new row `tag.merged_compare`)
- Modify: `tests/forge_world.py` (`invoke_ready` gains `merged_compare` and `fetch_exit`)
- Modify: `tests/test_forge_adapter.py` (new `MergedTagTest`; one assertion in `InvokeResultSetTest.test_happy_paths_render_the_fixture_and_pass_the_guard`)
- Modify: `python/README.md` (§ Release adapters: one sentence appended to the `pr_merge` paragraph Task 2 added)

**Interfaces:**
- Consumes: Task 2's `_merge_outcome(state, base, parents, parameters)`, the `pr_merge.view` and `pr_merge.merge_commit` spellings, `MERGE_CANDIDATE` in `tests/test_forge_adapter.py`, `forge_world.merge_ready`.
- Produces:
  - `_released(parameters, read) -> str | None`. Without `candidate.merge` it is `candidate.commit` and makes no read. With `candidate.merge` it reads `pr_merge.view`, and for `MERGED` also `pr_merge.merge_commit`, through `read(argv_without_gh) -> parsed JSON`. It returns `mergeCommit.oid` only when `_merge_outcome(...)` is `satisfied`, else `None`. A malformed answer raises `_Unknown("payload_invalid", …)`. This helper and `pr_merge`'s inspect share `_merge_outcome`, so the two judgments cannot disagree (D8).
  - Fixture row `tag.merged_compare` (`operation: tag`, `kind: read`): raw `gh api repos/fagenorn/nix-config/compare/3333333333333333333333333333333333333333...main --jq .status`.
  - `ForgeWorld.invoke_ready(..., merged_compare="identical", fetch_exit=0)` also registers `tag.merged_compare`, `git fetch --no-tags origin refs/heads/main` (exit `fetch_exit`) and `git tag -a v1.2.3 <merge_commit> -m "release: v1.2.3"` (exit `tag_create_exit`).

**Invariants:**
- Inspect `tag` and `release` read the tag exactly as at base. A missing tag is `absent/tag_absent` with no PR read. A lightweight tag is `diverged/tag_not_annotated` with no PR read. Only for an annotated tag does it call `_released`. The peeled commit equal to the released commit is `satisfied`. Otherwise it is `diverged/tag_target_mismatch`, including when `_released` is `None`. A read that cannot be judged is `unknown`, as at base. `publication_visible` follows through `_effect`, unchanged.
- `tag` invoke with `merge` follows this order after the same-repository proof:
  1. `_released` through precondition reads. `None` is `rejected/precondition_failed` with reference `release PR not merged as bound`, and a failed or malformed read is `rejected/provider_unavailable` (`transient_transport` on timeout).
  2. Containment `repos/<slug>/compare/<released>...<branch> --jq .status`, which must be `identical` or `ahead`.
  3. `git fetch --no-tags origin refs/heads/<branch>` in the checkout, where a non-zero exit is `rejected/provider_unavailable`.
  4. The local annotated tag at `<released>`.
  5. `git push origin refs/tags/<tag>` through the guard, as at base.
- `tag` invoke without `merge` makes exactly the calls it makes at base: no fetch and no PR read (D17). `release` invoke is unchanged in both cases.
- The guard's tag-push arm and every existing spelling row are unchanged.

- [ ] **Step 1: Write the failing test**

Add the fixture row and the `invoke_ready` keywords. In `InvokeResultSetTest.test_happy_paths_render_the_fixture_and_pass_the_guard`, assert `self.assertFalse(any(c["argv"][:1] == ["fetch"] for c in self.world.calls() if c["tool"] == "git"))` and that no `gh` argv starts with `["pr", "view"]`. Then add:

```python
class MergedTagTest(InvokeCase):
    """Issue 554 D8: with a merge binding, tag and release target the release PR's merge commit."""

    def landed(self, state="MERGED", parents=(C["base_tip"], C["commit"])):
        self.world.respond_json("gh", ROWS["pr_merge.view"]["argv"][1:], {
            "state": state, "baseRefName": C["branch"], "headRefName": "dev", "headRefOid": C["commit"],
            "mergeCommit": {"oid": C["merge_commit"]} if state == "MERGED" else None,
            "url": f"https://github.com/{C['slug']}/pull/{C['pr']}", "statusCheckRollup": []})
        self.world.respond_json("gh", ROWS["pr_merge.merge_commit"]["argv"][1:],
                                {"parents": [{"sha": sha} for sha in parents]})

    def tag_at(self, peeled):
        self.tag_ref()
        self.tag_object(peeled=peeled)

    def test_tag_inspect_compares_the_tag_with_the_merge_commit(self):
        self.landed()
        self.tag_at(C["merge_commit"])
        observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
        self.assertEqual((observation["outcome"], observation["observed_subject"]["commit"]),
                         ("satisfied", C["merge_commit"]))
        self.assertEqual(self.world.argvs("gh"), [ROWS[i]["argv"][1:] for i in (
            "tag.ref", "tag.object", "pr_merge.view", "pr_merge.merge_commit")])

    def test_a_tag_at_the_integration_tip_is_diverged(self):
        """Issue 554 row 14."""
        self.landed()
        self.tag_at(C["commit"])
        observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
        self.assertEqual((observation["outcome"], observation["reason"]), ("diverged", "tag_target_mismatch"))

    def test_an_unresolvable_released_commit_never_satisfies(self):
        for state, parents in (("OPEN", ()), ("MERGED", ("6" * 40, C["commit"]))):
            with self.subTest(state=state, parents=parents):
                self.world.reset()
                self.landed(state, parents)
                self.tag_at(C["merge_commit"])
                observation = self.inspect(effect("tag", candidate=MERGE_CANDIDATE))
                self.assertEqual((observation["outcome"], observation["reason"]),
                                 ("diverged", "tag_target_mismatch"))
        self.world.reset()
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.assertEqual(self.inspect(effect("tag", candidate=MERGE_CANDIDATE))["reason"], "tag_absent")
        self.assertEqual(self.world.argvs("gh"), [ROWS["tag.ref"]["argv"][1:]])

    def test_release_inspect_and_its_predicate_follow_the_merge_commit(self):
        self.landed()
        self.tag_at(C["merge_commit"])
        self.world.respond_json("gh", ROWS["release.view"]["argv"][1:], {
            "tag_name": C["tag"], "draft": False, "html_url": "u"})
        parameters = {"target": TARGET, "candidate": MERGE_CANDIDATE, "title": C["title"], "notes": "n"}
        self.assertEqual(self.inspect({"kind": "effect", "operation": "release",
                                       "parameters": parameters})["outcome"], "satisfied")
        predicate = forge_adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                           "operation": "release", "parameters": parameters})
        self.assertEqual((predicate["outcome"], predicate["reason"]), ("satisfied", "observed"))

    def test_tag_invoke_tags_and_pushes_the_merge_commit(self):
        self.world.invoke_ready()
        self.landed()
        self.assertEqual(self.invoke("tag", candidate=MERGE_CANDIDATE)["result"], "accepted")
        git = [c["argv"] for c in self.world.calls() if c["tool"] == "git"]
        fetch = ["fetch", "--no-tags", "origin", "refs/heads/main"]
        tag = ["tag", "-a", C["tag"], C["merge_commit"], "-m", f"release: {C['tag']}"]
        self.assertLess(git.index(fetch), git.index(tag))
        self.assertIn(ROWS["tag.merged_compare"]["argv"][1:], self.world.argvs("gh"))
        self.assertNotIn(ROWS["tag.compare"]["argv"][1:], self.world.argvs("gh"))
        self.assertEqual(["git", *self.mutations()[0]["argv"]], ROWS["tag.push"]["argv"])

    def test_tag_invoke_refuses_before_the_pr_merged(self):
        """Issue 554 row 13."""
        self.world.invoke_ready()
        self.landed("OPEN")
        self.assertEqual(self.invoke("tag", candidate=MERGE_CANDIDATE),
                         {"result": "rejected", "error_class": "precondition_failed",
                          "reference": "release PR not merged as bound"})
        self.assertEqual(self.mutations(), [])
        self.assertFalse(any(c["tool"] == "claude-bash-lifecycle-guard" for c in self.world.calls()))

    def test_a_failed_fetch_or_uncontained_merge_refuses_with_no_push(self):
        for ready, error_class in ((dict(fetch_exit=1), "provider_unavailable"),
                                   (dict(merged_compare="diverged"), "precondition_failed")):
            with self.subTest(ready=ready):
                self.world.reset()
                self.world.invoke_ready(**ready)
                self.landed()
                result = self.invoke("tag", candidate=MERGE_CANDIDATE)
                self.assertEqual((result["result"], result["error_class"]), ("rejected", error_class))
                self.assertEqual(self.mutations(), [])
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py -k MergedTag 2>&1 | tail -4'`
Expected: FAIL. The inspect compares the tag with `candidate.commit`, so the merge-commit tag is `tag_target_mismatch`, and invoke tags `candidate.commit` with no fetch.

- [ ] **Step 3: Write the minimal implementation**

Implement `_released` and the Invariants. `_tag_state` returns the peeled commit, and the caller compares. The comparison for `tag` and `release` resolves the released commit lazily, only after an annotated tag peels. In invoke, `read` wraps `_precondition_read(["gh", *argv], toplevel)` and `json.loads`. It turns `ValueError` and `_Unknown` into `_Refusal("rejected", "provider_unavailable", …)`. `_contained` takes the released commit. In the module docstring, add one sentence: with a merge binding, `tag` and `release` judge and tag the release PR's merge commit (issue 554 D8).

In `python/README.md`, append one sentence to the `pr_merge` paragraph that Task 2 added. It says that with `candidate.merge`, `tag` and `release` judge an existing tag against the release PR's merge commit with parents exactly `[base_tip, commit]`, else `tag_target_mismatch`. It also says that `tag` invoke refuses `release PR not merged as bound`, then checks that merge commit's containment, fetches `refs/heads/<branch>` and tags it, while without `merge` both are unchanged (issue 554 D8, D17).

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_forge_adapter.py tests/test_release_driver.py tests/test_release_crash_matrix.py tests/test_release_command.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `bash -c 'set -o pipefail; python3 -m unittest tests/test_claude_permission_guard.py -k adapter 2>&1 | tail -4'`
Expected: PASS, `OK` (the new read row is admitted in every class).

Run (timeout 3600 s): `just build`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/forge_adapter.py tests/fixtures/forge-adapter-spellings.json tests/forge_world.py tests/test_forge_adapter.py python/README.md
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-554/T3): tag the release PR's merge commit" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"d0a11a23314e70ae9b1d9c9f947103ec2e9bdf07","head":"e472765cc8d8306ee0637ad6bbe6ae8f6e82527a"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":250,"boundary":"all","deleted_lines":60,"record_bytes":34816,"support":{"covers":["r2a","r3a"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3a","last_task":3,"owner":3,"path":"python/agent_tools/forge_adapter.py"},{"bounds":[{"added_lines":46,"boundary":"all","deleted_lines":2,"record_bytes":4096,"support":{"covers":["r2b","r3b"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3b","last_task":3,"owner":3,"path":"tests/fixtures/forge-adapter-spellings.json"},{"bounds":[{"added_lines":65,"boundary":"all","deleted_lines":10,"record_bytes":8192,"support":{"covers":["r2c","r3c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3c","last_task":4,"owner":3,"path":"tests/forge_world.py"},{"bounds":[{"added_lines":320,"boundary":"all","deleted_lines":30,"record_bytes":37888,"support":{"covers":["r2d","r3d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3d","last_task":3,"owner":3,"path":"tests/test_forge_adapter.py"},{"bounds":[{"added_lines":4,"boundary":"all","deleted_lines":2,"record_bytes":38912,"support":{"covers":["r1f","r2k","r3e"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r3e","last_task":5,"owner":3,"path":"python/README.md"}]}}
```
