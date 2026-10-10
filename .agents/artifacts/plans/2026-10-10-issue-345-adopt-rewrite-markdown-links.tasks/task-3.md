# Task 3: `apply` commits the rewrites behind `no-new-broken-link`

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`COMMIT_GATES`)
- Modify: `python/agent_tools/adopt_apply.py` (`expected_status`, `fold_split_renames`, `gate_worktree_status_matches`, `gate_no_new_broken_link`, `COMMIT_GATE_CHECKS`)
- Test: `home/common/agent-skills/tests/test_adopt_apply.py`

**Interfaces:**
- Consumes (Task 1, `agent_tools.adopt_links`): `tree_records(root, revision)`, `index_records(root)` → `[(path, mode, object_id)]`; `markdown_texts(root, records) -> dict[str, str]`; `Tree(paths)`; `broken_count(container, text, tree) -> int`; `links(text)`; `resolve(container, target, tree)`.
- Consumes (Task 2, `test_adopt_project.py`): `LINKED_BASE`, `LINKED_AFTER`, `LINKED_SOURCES`, `LINKED_SUMMARY`, `write_linked_tree(root)`, `write_dissolved_tree(root)`; (Task 2, product) the plan document's `link_rewrites` member and the evidence record's `link_rewrites` member.
- Produces:
  - `adopt_inspection.COMMIT_GATES == ("worktree-status-matches-operations", "projections-in-sync", "no-unclassified-agent-path", "no-new-broken-link", "cold-clone-resolves", "resolve-capabilities-available", "workflow-verification-commands")` (D9).
  - `adopt_apply.expected_status(operations)` — a `write-file` whose target is the target of a `git-mv` in the same list contributes no record (D7).
  - `adopt_apply.fold_split_renames(actual: list[tuple], required: list[tuple]) -> list[tuple]` — for every required `("R ", (target, source))` absent from `actual` while both `("D ", (source,))` and `("A ", (target,))` are present, those two records are replaced by the `R ` record (at the `D ` record's position); everything else is returned unchanged and in order (D16).
  - `adopt_apply.gate_no_new_broken_link(run: GateRun) -> bool`, registered in `COMMIT_GATE_CHECKS` under `"no-new-broken-link"`; a failure records repair id `adopt.gate.no-new-broken-link` through `run_commit_gates`' existing derivation.

**Invariants:**
- `gate_worktree_status_matches` reads `actual = fold_split_renames(status_records(run.worktree), required)` and is otherwise unchanged.
- `gate_no_new_broken_link`: the base is the worktree's `HEAD` tree (`tree_records(run.worktree, "HEAD")`), the result is its index (`index_records(run.worktree)`), each with a `Tree` of all its own paths and the `markdown_texts` of its records. With `origin = {op["targets"][0]: op["sources"][0] for op in run.operations if op["op"] == "git-mv"}`, it fails when any result file `p` has `broken_count(p, text, result_tree)` greater than `broken_count(origin.get(p, p), base_text, base_tree)`, the latter `0` when `origin.get(p, p)` has no base text (D9). It adds no `GateRun` member.
- `expected_commit_paths`, `prove_commit_content`, `execute_operation` and `operation_result_matches` are unchanged (D7).
- `assert_retained` moves from `CommitGateTest` to `ApplyTestCase` unchanged, so every apply test class can use it.

- [ ] **Step 1: Write the failing tests**

In `test_adopt_apply.py`: extend the import from `.test_adopt_project` with `LINKED_AFTER`, `LINKED_BASE`, `LINKED_SOURCES`, `LINKED_SUMMARY`, `write_dissolved_tree`, `write_linked_tree`; add `from agent_tools import adopt_apply, adopt_links, adopt_planning`; move `assert_retained` (body unchanged) from `CommitGateTest` into `ApplyTestCase` under the `-- running --` helpers. Add after `answered_repo`:

```python
def linked_apply_repo(home: Path) -> Path:
    """`apply_repo` plus #345's inbound and outbound relative links."""
    root = apply_repo(home)
    write_linked_tree(root)
    return root
```

Add a test class after `ReadoptionTest`:

```python
class LinkRewriteApplyTest(ApplyTestCase):
    """#345: the adoption commit keeps every resolving relative link
    resolving, and refuses one that would break."""

    def test_the_linked_fixture_applies_with_every_link_resolving(self):
        root = linked_apply_repo(self.home)
        document = self.ready_plan(root)
        branch = self.succeed(root, document["plan"]["plan_id"])["branch"]
        for path, text in LINKED_AFTER.items():
            self.assertEqual(git(root, "show", f"{branch}:{path}"), text)
        # Already-broken links, URLs and files no link change touches are
        # byte-identical, wherever they now live.
        for old, new in ((".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
                         (".out-of-scope/z.md",
                          ".agents/knowledge/rejections/z.md"),
                         (".agents/instructions/bootstrap.md",
                          ".agents/instructions/bootstrap.md")):
            self.assertEqual(git(root, "show", f"{branch}:{new}"),
                             git(root, "show", f"HEAD:{old}"))
        base_tree = adopt_links.Tree(
            git(root, "ls-tree", "-r", "--name-only", "HEAD").splitlines())
        after_tree = adopt_links.Tree(
            git(root, "ls-tree", "-r", "--name-only", branch).splitlines())
        for new, source in LINKED_SOURCES.items():
            before = adopt_links.links(LINKED_BASE[source])
            after = adopt_links.links(LINKED_AFTER[new])
            self.assertEqual(len(after), len(before), new)
            for old_link, new_link in zip(before, after):
                if not adopt_links.is_relative(old_link.target):
                    self.assertEqual(new_link.target, old_link.target)
                elif adopt_links.resolve(source, old_link.target,
                                         base_tree) is None:
                    self.assertEqual(new_link.target, old_link.target)
                else:
                    self.assertIsNotNone(adopt_links.resolve(
                        new, new_link.target, after_tree), new_link.target)

    def test_the_evidence_record_carries_the_summary(self):
        root = linked_apply_repo(self.home)
        document = self.ready_plan(root)
        self.assertEqual(document["link_rewrites"], LINKED_SUMMARY)
        result = self.succeed(root, document["plan"]["plan_id"])
        record = json.loads(git(
            root, "show", f"{result['branch']}:{result['evidence_record']}"))
        self.assertEqual(record["link_rewrites"], LINKED_SUMMARY)

    def test_an_unrewritable_link_fails_the_commit_gate(self):
        root = apply_repo(self.home)
        write_dissolved_tree(root)
        code, out, err = run("plan", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "draft")
        plan_id = document["plan"]["plan_id"]
        # Forced past the ready gate (D11): only the commit gate stands
        # between this plan and a commit that breaks `README.md`'s link.
        stored = json.loads(self.stored_plan(plan_id).read_text("utf-8"))
        stored["plan"]["state"] = "ready"
        self.rewrite_stored_plan(plan_id, stored)
        base = git(root, "rev-parse", "HEAD").strip()
        self.assert_retained(root, plan_id, base,
                             "adopt.gate.no-new-broken-link")
        record = json.loads(self.state(
            "adopt", "worktrees",
            self.digest(plan_id) + ".failure.json").read_text("utf-8"))
        self.assertEqual([gate["id"] for gate in record["gates"]
                          if gate["status"] == "failed"],
                         ["no-new-broken-link"])


class StatusFoldTest(unittest.TestCase):
    """A rewritten move may be reported as a deletion plus an addition."""

    def test_a_write_onto_a_move_target_folds_into_the_move(self):
        move = adopt_planning.operation(
            "git-mv", ["a.md"], ["b/a.md"], "git-object:" + "0" * 40,
            "git-object:" + "0" * 40)
        write = adopt_planning.operation(
            "write-file", ["b/a.md"], ["b/a.md"], "sha256:" + "0" * 64,
            "sha256:" + "1" * 64)
        required, optional = adopt_apply.expected_status([move, write])
        self.assertEqual(required, [("R ", ("b/a.md", "a.md"))])
        self.assertEqual(optional, set())

    def test_a_split_rename_folds_only_as_a_whole_pair(self):
        required = [("R ", ("b/a.md", "a.md"))]
        fold = adopt_apply.fold_split_renames
        self.assertEqual(
            fold([("M ", ("x",)), ("D ", ("a.md",)), ("A ", ("b/a.md",))],
                 required),
            [("M ", ("x",)), ("R ", ("b/a.md", "a.md"))])
        self.assertEqual(fold([("D ", ("a.md",))], required),
                         [("D ", ("a.md",))])
        self.assertEqual(fold([("R ", ("b/a.md", "a.md"))], required),
                         [("R ", ("b/a.md", "a.md"))])

    def test_the_commit_gates_place_the_link_gate_before_the_cold_clone(self):
        gates = adopt_apply.COMMIT_GATES
        self.assertEqual(gates.index("no-new-broken-link") + 1,
                         gates.index("cold-clone-resolves"))
        self.assertIn("no-new-broken-link", adopt_apply.COMMIT_GATE_CHECKS)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k LinkRewriteApplyTest -k StatusFoldTest`
Expected: FAIL — the linked fixtures refuse `verification_failed` / `adopt.gate.worktree-status-matches-operations` (the link writes add `M `/`A ` records the status gate does not expect), `expected_status` returns an extra `M ` record, and `fold_split_renames` and the gate id are missing.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection.COMMIT_GATES`: insert `"no-new-broken-link"` before `"cold-clone-resolves"`.
2. `adopt_apply.expected_status`: collect the `git-mv` targets first; skip a `write-file` whose target is one of them; docstring adds "a write onto a move's target is that move's content, so it is satisfied by the move's record".
3. `adopt_apply.fold_split_renames` per Produces, and use it in `gate_worktree_status_matches`.
4. `adopt_apply.gate_no_new_broken_link` per the invariant, with a docstring saying the base is the worktree's `HEAD` (the plan's base revision until the commit) and the result is the index, each counted against its own tree's tracked paths; register it in `COMMIT_GATE_CHECKS` in `COMMIT_GATES` order.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py`
Expected: PASS, every test in the module (the existing `ApplySuccessTest` records seven passed commit gates).
Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_apply.py home/common/agent-skills/tests/test_adopt_apply.py
launch-commit … -- -m "feat(adopt): commit link rewrites behind a no-new-broken-link gate (#345)"
```
