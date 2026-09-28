# Task 6: `repository.residue.promoted_duplicate` (package P3 begins)

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance-registry.py`
- Modify: `home/common/agent-skills/scripts/conformance-checks.py`
- Modify: `home/common/agent-skills/tests/test_conformance_checks.py`
- Modify: `home/common/agent-skills/tests/test_conformance_registry.py`

Read the spec's "The conformance check (D10, D11)". D10, D11, D15, D16 (seams 3–5) and D27
govern this task. Existing patterns to follow: `NESTED_LEDGER_FINDINGS`, the `REPAIRS` entries,
`check_residue_nested_ledger`, `listed`, `first_symlinked_component`, `bound_facts`, and the
suites' `doctor`, `make_root`, `write_file`, `fixture`, `load_module`, `ReportAssertions`.

**Interfaces:**
- Consumes (Task 1, test-only): `agent_tools.promotion_schema` constants `CANDIDATES_RELATIVE`,
  `CANDIDATE_KIND`, `PROMOTED`, `LOCAL_DUPLICATES_MEMBER`, `DUPLICATE_MEMBERS`,
  `REMOVE_DISPOSITION`, `PROJECT_ONLY_RESIDUE`, `COMMAND_NAME`.
- Produces in `conformance-registry.py` (Task 7's installed test relies on the check id and codes):

```python
REPAIR_MODULES = ("conformance", "resolve-project", "promotion")
PROMOTION_CANDIDATES_RELATIVE = (".agents", "knowledge", "promotions", "candidates")
PROMOTION_CANDIDATE_KIND = "promotion-candidate"
PROMOTION_PROMOTED_STATE = "promoted"
PROMOTION_DUPLICATES_MEMBER = "local_duplicates"
PROMOTION_DUPLICATE_MEMBERS = ("repository", "path", "sha256", "disposition")
PROMOTION_REMOVE_DISPOSITION = "remove"
PROMOTION_PROJECT_ONLY_RESIDUE = "project_only_residue"
PROMOTION_REPAIR_MODULE = "promotion"
PROMOTED_DUPLICATE_DRIFTED = "promoted_duplicate_drifted"
PROMOTED_DUPLICATE_PRESENT = "promoted_duplicate_present"
PROMOTED_DUPLICATE_FINDINGS = (
    (PROMOTED_DUPLICATE_DRIFTED, "promotion.duplicate.reconcile"),
    (PROMOTED_DUPLICATE_PRESENT, "promotion.duplicate.remove"),
)
# REPAIRS gains:
# "promotion.duplicate.remove": {"module": "promotion", "safety_class": "worktree", "operation": None}
# "promotion.duplicate.reconcile": {"module": "promotion", "safety_class": "user_action", "operation": None}
# REGISTRY gains, after repository.residue.root_scratch:
# Check("repository.residue.promoted_duplicate", "repository", "residue", "required",
#       ("repository.contract.valid",), PROMOTED_DUPLICATE_FINDINGS,
#       "check_residue_promoted_duplicate")
```

- Produces in `conformance-checks.py`:
  `check_residue_promoted_duplicate(context: Context) -> Outcome`.

**Invariants:**
- Neither script contains the text `agent_tools` anywhere (D27). The comment above the literals
  says they mirror "the helper package's `promotion_schema` module" and are pinned by
  `test_conformance_registry`.
- The evaluator is pure and read-only; it spawns nothing and imports no package module (D10).
- It lists `listed(context.root.joinpath(*PROMOTION_CANDIDATES_RELATIVE))`, keeping entries
  whose name ends `.json` that are regular files and not symlinks; a file that fails to read or
  parse, is not an object, or has another `kind` or `state` is ignored.
- For each promoted candidate, each `local_duplicates` object in order: `disposition ==
  PROJECT_ONLY_RESIDUE` → `retained_count += 1`; else `disposition == REMOVE` and
  `repository != context.contract["project"]["id"]` → `deferred_count += 1`; else
  `disposition == REMOVE` → judged; anything else is ignored.
- A judged entry is **drifted** when its `path` is not a non-empty, non-absolute string free of
  `..` parts, when `first_symlinked_component(root, path)` is not `None`, when something exists
  (`os.path.lexists`) but is not a regular file, when reading fails, or when `sha256` is not a
  string equal to `hashlib.sha256(bytes).hexdigest()`; **present** when the bytes match; and
  contributes nothing when nothing exists at the path (D15).
- `facts = {"duplicates": bound_facts(<offending paths as str>), "count": <offenders>,
  "deferred_count": n, "retained_count": n}` on every outcome, including `passed` and the
  absent-directory case. With offenders the status is `failed` and the reason/repair are the
  first `PROMOTED_DUPLICATE_FINDINGS` entry with a non-zero count (drift before presence, D11).

- [ ] **Step 1: Write the failing seam-3 cases** (append to `test_conformance_checks.py`;
  add `import hashlib` to its imports)

```python
LEFTOVER = b"Investigate before changing.\n"
LEFTOVER_SHA = hashlib.sha256(LEFTOVER).hexdigest()
HERE = "fagenorn/nix-config"


def promoted(root, duplicates, *, state="promoted", kind="promotion-candidate",
             name="c.json"):
    """A candidate file carrying only the members the evaluator reads."""
    target = root / ".agents/knowledge/promotions/candidates" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({"kind": kind, "state": state,
                                  "local_duplicates": duplicates}), encoding="utf-8")
    return target


def dup(path="docs/lesson.md", sha=LEFTOVER_SHA, repository=HERE, disposition="remove"):
    return {"repository": repository, "path": path, "sha256": sha,
            "disposition": disposition}


class PromotedDuplicateResidueTest(ReportAssertions, unittest.TestCase):
    """#127 AC4: a promoted lesson's leftover local copy fails a required check."""

    CHECK_ID = "repository.residue.promoted_duplicate"
    REMOVE_ID = "promotion.duplicate.remove"
    RECONCILE_ID = "promotion.duplicate.reconcile"

    def judge(self, root):
        report, by_id = doctor(self, root)
        self.assert_validates(report)
        return report, by_id[self.CHECK_ID]

    def test_no_candidates_directory_passes_with_zero_facts(self):
        with fixture() as tmp:
            _, check = self.judge(make_root(tmp))
            self.assertEqual(
                [check["domain"], check["subject_kind"], check["requirement"],
                 check["status"], check["reason_code"], check["repair_id"], check["facts"]],
                ["repository", "residue", "required", "passed", None, None,
                 {"duplicates": [], "count": 0, "deferred_count": 0, "retained_count": 0}])

    def test_absent_foreign_and_retained_duplicates_pass_with_scope_facts(self):
        with fixture() as tmp:
            root = make_root(tmp)
            write_file(root, "docs/keep.md")
            promoted(root, [dup(), dup(repository="fagenorn/argus"),
                            dup("docs/keep.md", disposition="project_only_residue")])
            _, check = self.judge(root)
            self.assertEqual([check["status"], check["facts"]], ["passed", {
                "duplicates": [], "count": 0, "deferred_count": 1, "retained_count": 1}])

    def test_an_unchanged_leftover_fails_with_the_remove_repair(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "docs").mkdir()
            (root / "docs/lesson.md").write_bytes(LEFTOVER)
            promoted(root, [dup()])
            report, check = self.judge(root)
            self.assertEqual([check["status"], check["reason_code"], check["repair_id"],
                              check["facts"]["duplicates"], check["facts"]["count"]],
                             ["failed", "promoted_duplicate_present", self.REMOVE_ID,
                              ["docs/lesson.md"], 1])
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.REMOVE_ID]
            self.assertEqual([repair["module"], repair["safety_class"], repair["operation"]],
                             ["promotion", "worktree", None])
            self.assertEqual(report["outcome"]["status"], "failed")

    def test_drift_outranks_presence(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "docs").mkdir()
            (root / "docs/lesson.md").write_bytes(LEFTOVER)
            (root / "docs/other.md").write_bytes(b"edited\n")
            promoted(root, [dup(), dup("docs/other.md")])
            report, check = self.judge(root)
            self.assertEqual([check["reason_code"], check["repair_id"],
                              check["facts"]["count"]],
                             ["promoted_duplicate_drifted", self.RECONCILE_ID, 2])
            repair = {r["repair_id"]: r for r in report["repairs"]}[self.RECONCILE_ID]
            self.assertEqual(repair["safety_class"], "user_action")

    def test_every_drift_shape_is_drifted(self):
        def other_bytes(root):
            (root / "docs/lesson.md").write_bytes(b"edited\n")

        def directory(root):
            (root / "docs/lesson.md").mkdir()

        def leaf_link(root):
            (root / "real.md").write_bytes(LEFTOVER)
            (root / "docs/lesson.md").symlink_to(root / "real.md")

        def parent_link(root):
            (root / "real").mkdir()
            (root / "real/lesson.md").write_bytes(LEFTOVER)
            (root / "docs").rmdir()
            (root / "docs").symlink_to(root / "real", target_is_directory=True)

        def leftover(root):
            (root / "docs/lesson.md").write_bytes(LEFTOVER)

        cases = {"other_bytes": (other_bytes, dup()), "null_digest": (leftover, dup(sha=None)),
                 "directory": (directory, dup()), "leaf_link": (leaf_link, dup()),
                 "parent_link": (parent_link, dup()),
                 "traversal": (leftover, dup("../outside.md")),
                 "absolute": (leftover, dup("/etc/hosts"))}
        for name, (make, entry) in cases.items():
            with self.subTest(case=name), fixture() as tmp:
                root = make_root(tmp)
                (root / "docs").mkdir()
                make(root)
                promoted(root, [entry])
                _, check = self.judge(root)
                self.assertEqual([check["status"], check["reason_code"]],
                                 ["failed", "promoted_duplicate_drifted"])

    def test_only_promoted_candidate_files_are_judged(self):
        with fixture() as tmp:
            root = make_root(tmp)
            (root / "docs").mkdir()
            (root / "docs/lesson.md").write_bytes(LEFTOVER)
            promoted(root, [dup()], state="authorized", name="a.json")
            promoted(root, [dup()], kind="promotion-evaluation", name="b.json")
            promoted(root, [dup()], name="c.txt")
            broken = root / ".agents/knowledge/promotions/candidates/d.json"
            broken.write_text("{ broken", encoding="utf-8")
            _, check = self.judge(root)
            self.assertEqual([check["status"], check["facts"]["count"]], ["passed", 0])
```

- [ ] **Step 2: Write the failing registry cases** in `test_conformance_registry.py`: add
  `"repository.residue.promoted_duplicate",` to `REGISTERED_CHECK_IDS` (sorted position, between
  `repository.residue.nested_ledger` and `repository.residue.root_scratch`), rename
  `test_the_registry_is_exactly_the_eighteen_declared_checks` to `..._nineteen_...`, append to
  `AcceptanceDemoTest.test_doctor_on_this_repository_reports_every_registered_check`:

```python
        promoted = by_id["repository.residue.promoted_duplicate"]
        self.assertEqual([promoted["status"], promoted["facts"]], ["passed", {
            "duplicates": [], "count": 0, "deferred_count": 0, "retained_count": 0}])
```

and add this class before `AcceptanceDemoTest`:

```python
class PromotionLiteralPinTest(unittest.TestCase):
    """#127 D10, D27: the engine's promotion literals are the package's constants,
    and no installed engine file names the package."""

    def test_registry_literals_equal_the_promotion_schema(self):
        from agent_tools import promotion_schema as schema
        registry = load_module().registry
        self.assertEqual(
            [registry.PROMOTION_CANDIDATES_RELATIVE, registry.PROMOTION_CANDIDATE_KIND,
             registry.PROMOTION_PROMOTED_STATE, registry.PROMOTION_DUPLICATES_MEMBER,
             registry.PROMOTION_DUPLICATE_MEMBERS, registry.PROMOTION_REMOVE_DISPOSITION,
             registry.PROMOTION_PROJECT_ONLY_RESIDUE, registry.PROMOTION_REPAIR_MODULE],
            [schema.CANDIDATES_RELATIVE, schema.CANDIDATE_KIND, schema.PROMOTED,
             schema.LOCAL_DUPLICATES_MEMBER, schema.DUPLICATE_MEMBERS,
             schema.REMOVE_DISPOSITION, schema.PROJECT_ONLY_RESIDUE, schema.COMMAND_NAME])
        self.assertIn(registry.PROMOTION_REPAIR_MODULE, registry.REPAIR_MODULES)

    def test_no_installed_engine_file_names_the_package(self):
        scripts = Path(__file__).resolve().parents[1] / "scripts"
        for name in ("conformance.py", "conformance-registry.py", "conformance-checks.py"):
            with self.subTest(name=name):
                self.assertNotIn(b"agent_tools", (scripts / name).read_bytes())
```

- [ ] **Step 3: Run and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py 2>&1 | tail -3`
Expected: FAILED — `KeyError: 'repository.residue.promoted_duplicate'` and missing `PROMOTION_*` attributes.

- [ ] **Step 4: Implement** the registry literals, repairs, `REPAIR_MODULES`, the `Check`, and
  the evaluator (import the new names from `conformance_registry`; add `import hashlib`).

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_conformance_checks.py home/common/agent-skills/tests/test_conformance_registry.py home/common/agent-skills/tests/test_conformance.py 2>&1 | tail -3`
Expected: `OK`.
Run: `if grep -n agent_tools home/common/agent-skills/scripts/conformance*.py; then exit 1; fi`
Run: `just build 2>&1 | tail -3` — success (the scripts are installed files).

- [ ] **Step 6: Commit** — `git add` the four files; subject
  `feat(issue-127/T6): conformance check repository.residue.promoted_duplicate`, with the trailers.
