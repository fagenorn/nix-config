# Task 2: `plan` derives the rewrites, the summary, the id input and the ready gate

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py` (`READY_GATES`)
- Modify: `python/agent_tools/adopt_planning.py` (`evidence_record_members`, `generated_targets`, `check_markdown_writes`, `build_operations`, `bookkeeping_operations`, `evaluate_ready_gates`, `GATE_MESSAGES`, `compute_plan_id`)
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `emit_human`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes (Task 1, `agent_tools.adopt_links`): `derive_link_rewrites(root, revision, moves, deleted, excluded) -> LinkRewrites`, `LinkRewrites.summary: dict`, `LinkRewrites.files: dict[str, RewrittenFile]`, `RewrittenFile(source, before, after)` (texts), `is_markdown_path(path) -> bool`, `links(text) -> list[Link]`.
- Produces:
  - `adopt_inspection.READY_GATES` ends `..., "no-secret-path-in-moves", "no-unrewritable-link"` (D9).
  - `adopt_planning.evidence_record_members(found: Candidates) -> list[tuple[str, str]]` — sorted `(path, object_id)` of every `found.groups` member for which `is_evidence_record_path` holds; `bookkeeping_operations` builds its superseded list from it (excluding its own record name, as now).
  - `adopt_planning.generated_targets(contract_source: dict | None) -> set[str]` — the `target` of every `projections` entry that is a dict with `kind == "generated_file"` and a string `target`; empty for a missing or malformed contract (D10, D13).
  - `adopt_planning.check_markdown_writes(changes: list[dict], link_targets: set[str]) -> None` — raises `ValueError` unless the `write-file` operations whose target `is_markdown_path` name exactly `link_targets`, each once, and no `delete-file` names a Markdown path (D7).
  - `adopt_planning.compute_plan_id(project_id, base_revision, platform_block, evidence, answered, link_rewrites: dict) -> str` — seven inputs; the digested source gains the key `"link_rewrites"` (D8).
  - `adopt_planning.evaluate_ready_gates(..., decisions, link_rewrites: dict)` — appends `no-unrewritable-link`, `failed` with `adopt.link.unrewritable` when `link_rewrites["unrewritable"]` is non-empty, else `passed`.
  - `adopt_planning.build_operations(root, found, manifest, contract_source, plan_id, links: LinkRewrites)` — after the legacy-binding rewrites and before the projection regenerations, one `operation("write-file", [t], [t], sha256_hash(before_bytes), sha256_hash(after_bytes))` per `t` in `sorted(links.files)`, with `contents[t] = after_bytes` (bytes are `.encode("utf-8")` of the texts) (D6, D7).
  - `adopt_planning.bookkeeping_operations(..., ready_gates, link_rewrites: dict)` — the evidence record gains the member `"link_rewrites"` with the summary; `EVIDENCE_RECORD_MEMBERS` is unchanged (D8).
  - The plan document gains the top-level member `link_rewrites` (the summary) for every outcome (D13); `--format human` prints, directly after the `changes:` line, `links: inbound <n> in <m> files, outbound <n> in <m> files, unrewritable <k>, already broken <b>`.

**Invariants:**
- In `compose_plan` the derivation runs after `apply_answers` and `load_contract_source` and before `compute_plan_id`: `links = adopt_links.derive_link_rewrites(root, inventory.base_revision, found.moves, [path for path, _ in adopt_planning.evidence_record_members(found)], adopt_planning.generated_targets(contract_source))` (D6, D12, D13).
- For an appliable outcome, `check_markdown_writes(changes, set(links.files))` runs on the assembled `changes` before the document is built; a not-applicable outcome keeps `changes == []` and still publishes `link_rewrites`.
- `GATE_MESSAGES["no-unrewritable-link"] == "a relative Markdown link into or out of a moved path cannot be rewritten to resolve to the same target"`.
- `composed.overlap` is unchanged (D6). No new operation kind (D7).
- `compute_plan_id`'s docstring says it digests seven inputs and names `link_rewrites` among them.

- [ ] **Step 1: Write the failing tests**

In `test_adopt_project.py`, add `adopt_links` to the import (`from agent_tools import adopt_inspection, adopt_links, adopt_planning, adopt_project`), add `"link_rewrites"` to `TOP_LEVEL_MEMBERS` (keep the list sorted), rename `test_exactly_seven_top_level_members` to `test_exactly_eight_top_level_members` and add inside its loop:

```python
                self.assertEqual(sorted(doc["link_rewrites"]),
                                 ["already_broken", "inbound", "outbound",
                                  "unrewritable"])
```

In `documented_plan_id`, add `"link_rewrites": doc["link_rewrites"],` to `source` and change "the six named members" to "the seven named members".

Add after `record_trees_repo` (module level):

```python
LINK_README_BEFORE = (
    "# readme\n"
    "\n"
    "See [spec x](.claude/specs/x.md#intro) and [plans](./.claude/plans/).\n"
    "Image: ![diagram](<.claude/specs/x.md> \"Spec x\") and [plan y][y].\n"
    "Broken: [gone](.claude/specs/missing.md). "
    "Web: [site](https://example.com/.claude/specs/x.md).\n"
    "Self: [me](README.md). Code: `[c](.claude/specs/x.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.claude/specs/x.md)\n"
    "~~~\n"
    "\n"
    "[y]: .claude/plans/y.md \"Plan y\"\n")
LINK_README_AFTER = (
    "# readme\n"
    "\n"
    "See [spec x](.agents/artifacts/specs/x.md#intro) and "
    "[plans](./.agents/artifacts/plans/).\n"
    "Image: ![diagram](<.agents/artifacts/specs/x.md> \"Spec x\") and "
    "[plan y][y].\n"
    "Broken: [gone](.claude/specs/missing.md). "
    "Web: [site](https://example.com/.claude/specs/x.md).\n"
    "Self: [me](README.md). Code: `[c](.claude/specs/x.md)`.\n"
    "\n"
    "~~~\n"
    "[fenced](.claude/specs/x.md)\n"
    "~~~\n"
    "\n"
    "[y]: .agents/artifacts/plans/y.md \"Plan y\"\n")

# Base path -> base text, and path after the moves -> rewritten text (#345).
LINKED_BASE = {
    "README.md": LINK_README_BEFORE,
    ".claude/rules/r.md": "# rule r\n\nFollow [spec x](../specs/x.md).\n",
    ".claude/specs/x.md": (
        "# spec x\n\nBack to [readme](../../README.md), "
        "[plan y](../plans/y.md) and "
        "[rejected z](../../.out-of-scope/z.md).\n"),
}
LINKED_AFTER = {
    "README.md": LINK_README_AFTER,
    ".claude/rules/r.md": (
        "# rule r\n\nFollow [spec x](../../.agents/artifacts/specs/x.md).\n"),
    ".agents/artifacts/specs/x.md": (
        "# spec x\n\nBack to [readme](../../../README.md), "
        "[plan y](../plans/y.md) and "
        "[rejected z](../../knowledge/rejections/z.md).\n"),
}
LINKED_SOURCES = {"README.md": "README.md",
                  ".claude/rules/r.md": ".claude/rules/r.md",
                  ".agents/artifacts/specs/x.md": ".claude/specs/x.md"}
LINKED_SUMMARY = {
    "inbound": {"links": 5, "files": [".claude/rules/r.md", "README.md"]},
    "outbound": {"links": 2, "files": [".agents/artifacts/specs/x.md"]},
    "unrewritable": [],
    "already_broken": 1,
}
DISSOLVED_README = "# readme\n\nAgent records: [records](.claude/).\n"


def write_linked_tree(root: Path) -> None:
    """Inbound links from a root file and a retained `.claude/` file, and
    outbound links from a moved spec, over any fixture carrying
    `.claude/specs/x.md`, `.claude/plans/y.md` and `.out-of-scope/z.md`."""
    for path, text in LINKED_BASE.items():
        write(root, path, text)
    commit(root, "link the agent trees")


def linked_repo(home: Path) -> Path:
    root = nix_config_shape_repo(home)
    write_linked_tree(root)
    return root


def write_dissolved_tree(root: Path) -> None:
    """`.claude/` loses its last retained file and gains a research record,
    so its members move under two different prefixes and a link to the
    directory itself has no single successor (D5)."""
    git(root, "rm", "--quiet", ".claude/skills.config.json")
    write(root, ".claude/research/r.md", "# research r\n")
    write(root, "README.md", DISSOLVED_README)
    commit(root, "link the dissolving agent tree")
```

Add a test class after `CandidateAnswerTest`:

```python
class LinkRewritePlanTest(AdoptTestCase):
    """#345: `plan` rewrites relative Markdown links across the moves."""

    def link_writes(self, doc: object) -> list[dict]:
        return [op for op in doc["changes"] if op["op"] == "write-file"
                and op["targets"][0] in LINKED_AFTER]

    def test_the_linked_fixture_plans_to_ready_with_the_rewrites(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        writes = self.link_writes(doc)
        self.assertEqual([op["targets"] for op in writes],
                         [[".agents/artifacts/specs/x.md"],
                          [".claude/rules/r.md"], ["README.md"]])
        for op in writes:
            target = op["targets"][0]
            self.assertEqual(op["sources"], [target])
            self.assertEqual(op["before"], sha256_hash(
                LINKED_BASE[LINKED_SOURCES[target]].encode("utf-8")))
            self.assertEqual(op["after"], sha256_hash(
                LINKED_AFTER[target].encode("utf-8")))
        order = [(op["op"], op["targets"][0] if op["targets"] else None)
                 for op in doc["changes"]]
        legacy = order.index(("write-file", ".claude/skills.config.json"))
        first = order.index(("write-file", ".agents/artifacts/specs/x.md"))
        projections = [index for index, (kind, _) in enumerate(order)
                       if kind == "regenerate-projection"]
        self.assertLess(legacy, first)
        self.assertTrue(projections)
        self.assertLess(first + 2, min(projections))

    def test_anchors_titles_and_reference_definitions_survive_and_urls_stay(self):
        doc = self.ready_plan(linked_repo(self.home))
        readme = next(op for op in self.link_writes(doc)
                      if op["targets"] == ["README.md"])
        self.assertEqual(readme["after"], sha256_hash(
            LINK_README_AFTER.encode("utf-8")))
        before = [link.target
                  for link in adopt_links.links(LINK_README_BEFORE)]
        after = [link.target for link in adopt_links.links(LINK_README_AFTER)]
        self.assertEqual(list(zip(before, after)), [
            (".claude/specs/x.md#intro", ".agents/artifacts/specs/x.md#intro"),
            ("./.claude/plans/", "./.agents/artifacts/plans/"),
            (".claude/specs/x.md", ".agents/artifacts/specs/x.md"),
            (".claude/specs/missing.md", ".claude/specs/missing.md"),
            ("https://example.com/.claude/specs/x.md",
             "https://example.com/.claude/specs/x.md"),
            ("README.md", "README.md"),
            (".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
        ])

    def test_the_summary_is_published_and_enters_the_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        self.assertEqual(doc["link_rewrites"], LINKED_SUMMARY)
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

    def test_a_different_rewrite_set_is_a_different_plan_id(self):
        doc = self.ready_plan(linked_repo(self.home))
        inputs = (doc["plan"]["project_id"], doc["plan"]["base_revision"],
                  doc["plan"]["platform"], doc["evidence"],
                  doc["decisions"]["answered"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs, doc["link_rewrites"]),
            doc["plan"]["plan_id"])
        other = json.loads(json.dumps(LINKED_SUMMARY))
        other["inbound"] = {"links": 4, "files": ["README.md"]}
        self.assertNotEqual(adopt_planning.compute_plan_id(*inputs, other),
                            doc["plan"]["plan_id"])

    def test_the_human_view_prints_one_link_line(self):
        code, out, err = run("plan", "--repo-root",
                             str(linked_repo(self.home)), "--format", "human",
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("\nlinks: inbound 5 in 2 files, outbound 2 in 1 files, "
                      "unrewritable 0, already broken 1\n", out)

    def test_a_dissolved_directory_link_keeps_the_plan_draft(self):
        root = nix_config_shape_repo(self.home)
        write_dissolved_tree(root)
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [gate for gate in doc["verification"]["ready_gates"]
             if gate["status"] == "failed"],
            [{"id": "no-unrewritable-link", "status": "failed",
              "repair_id": "adopt.link.unrewritable"}])
        self.assertEqual(doc["link_rewrites"]["unrewritable"],
                         [{"path": "README.md", "target": ".claude/"}])
        self.assertIn(
            {"id": "no-unrewritable-link",
             "message": "a relative Markdown link into or out of a moved "
                        "path cannot be rewritten to resolve to the same "
                        "target"},
            doc["plan"]["blockers"])

    def test_the_link_gate_is_the_last_ready_gate(self):
        self.assertEqual(adopt_inspection.READY_GATES[-2:],
                         ("no-secret-path-in-moves", "no-unrewritable-link"))

    def test_a_markdown_file_any_other_operation_names_is_a_derivation_bug(self):
        op = adopt_planning.operation
        link = op("write-file", ["README.md"], ["README.md"],
                  "sha256:" + "0" * 64, "sha256:" + "1" * 64)
        adopt_planning.check_markdown_writes([link], {"README.md"})
        delete = op("delete-file", ["notes.md"], [],
                    "git-object:" + "0" * 40, None)
        for changes, targets in (([link], set()),
                                 ([link, link], {"README.md"}),
                                 ([], {"README.md"}),
                                 ([delete], set())):
            with self.subTest(changes=changes, targets=targets):
                with self.assertRaises(ValueError):
                    adopt_planning.check_markdown_writes(changes, targets)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k LinkRewritePlanTest -k DocumentShapeTest -k PlanIdentityTest`
Expected: FAIL — `KeyError: 'link_rewrites'` in the shape and identity tests, no link `write-file` operations, and `AttributeError` for `check_markdown_writes`.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection.READY_GATES`: append `"no-unrewritable-link"`.
2. `adopt_planning`: import `adopt_links` and `LinkRewrites`; add `evidence_record_members`, `generated_targets` and `check_markdown_writes` per Produces; route `bookkeeping_operations`' superseded list through `evidence_record_members` and add the `link_rewrites` member to its record; extend `compute_plan_id`, `evaluate_ready_gates` (the new gate is `READY_GATES[7]`), `GATE_MESSAGES` and `build_operations` per Produces. Update `build_operations`' docstring order sentence: "... then the living-reference rewrite, the Markdown link rewrites sorted by target, and finally the projection regenerations".
3. `adopt_project.compose_plan`: derive `links` per the first invariant; pass `links.summary` to `compute_plan_id`, `evaluate_ready_gates` and `bookkeeping_operations`, and `links` to `build_operations`; for an appliable outcome call `check_markdown_writes(changes, set(links.files))` after `changes = head + bookkeeping + tail`; add `"link_rewrites": links.summary` to `document`. `emit_human`: append the `links:` line after the `changes:` line, read from `document["link_rewrites"]`.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py home/common/agent-skills/tests/test_adopt_verify.py`
Expected: PASS, every test (the new class included).
Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py`
Expected: PASS (no existing apply fixture carries a relative link, so no link write reaches the status gate).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py
launch-commit … -- -m "feat(adopt): plan relative Markdown link rewrites inside the plan id (#345)"
```
