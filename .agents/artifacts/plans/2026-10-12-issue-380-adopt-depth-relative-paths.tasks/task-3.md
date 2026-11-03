# Task 3: The depth read set, depth occurrences in plan, apply and verify, and the documented contract

**Files:**
- Modify: `python/agent_tools/adopt_references.py` (`derive_references`, module docstring)
- Modify: `python/agent_tools/adopt_planning.py` (the `reference_questions` docstring only)
- Modify: `python/README.md` (§ `adopt-project`)
- Test: `home/common/agent-skills/tests/test_adopt_references.py`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `home/common/agent-skills/tests/test_adopt_verify.py`

**Interfaces:**
- Consumes (Tasks 1–2): `plan_references(texts, paths, moves, trees, depth_texts=...)`, `Occurrence.depth`, the `/depth` occurrence class; in tests, `SPECS` and `git` of `test_adopt_references.py`, and `AdoptTestCase`, `nix_config_shape_repo`, `write`, `commit`, `answer_args`, `policy_row`, `run`, `git` of `test_adopt_project.py`, `ApplyTestCase`, `apply_repo` of `test_adopt_apply.py`, `VerifyTestCase` of `test_adopt_verify.py`.
- Produces: `derive_references(root, revision, moves, excluded, trees) -> References` (signature unchanged) now also reading the depth read set; test fixtures `DEPTH_DIR`, `DEPTH_NEW`, `DEPTH_CODE`, `DEPTH_POLICIES`, `DEPTH_ROWS`, `DEPTH_REWRITE_ANSWERS`, `DEPTH_RETAIN_ANSWERS`, `write_depth_tree` in `test_adopt_project.py`.

**Invariants:**
- The first-segment `git grep` and the three existing readings over its files are unchanged, so every existing `path_references` row, `reference_policies` row and `plan_id` is byte-identical; no existing test is edited (AC4, D7, D10).
- The depth read set is: the moved files (sources of `moves`) that a second `git grep --no-color -I -l -z -F -e .. -e __file__ <revision> -- <pathspecs>` returns, the pathspecs being `:(literal)<tree>` for each distinct tree of a move source (`trees.get(source, source)`), then the existing filters (regular mode, not Markdown, not secret-shaped, not in `excluded`, not under `RECORD_HOMES` by base path, strict UTF-8) (D7).
- Each blob is read once even when both scans return it; a git exit other than 0 or 1 refuses `adopt.git.failed` as today; no references are returned only when neither scan returns a file (D10).
- A plan whose moved files hold a depth occurrence stays `draft` through `no-open-decisions` until its `/depth` policies or occurrences are answered (D9); a plan with none has the same document and `plan_id` as at base (D6).
- No change to `adopt_apply.py`, `adopt_verify.py`, `adopt_project.py`, `QUESTION_IDS`, `EVIDENCE_RECORD_MEMBERS`, the `plan_id` inputs or any row's member set (D6).

- [ ] **Step 1: Write the failing tests**

(a) `home/common/agent-skills/tests/test_adopt_references.py` — append after `DerivationTest`, before `if __name__ == "__main__":`:

```python
class DepthDerivationTest(unittest.TestCase):
    """#380 D7: the depth reading's own read set, beside the first-segment
    prefilter's."""

    FILES = {
        ".claude/specs/tool/run.py": b"ROOT = Path(__file__).parents[2]\n",
        ".claude/specs/tool/both.toml":
            b'lib = "../../../vendor/lib"\nspec = ".claude/plans/y.md"\n',
        ".claude/specs/tool/notes.md": b"[up](../../../README.md)\n",
        ".claude/specs/tool/blob.bin": b"\x00../../../x\n",
        ".claude/specs/tool/.env.ci": b"../../../x\n",
        ".claude/specs/tool/dots.txt": b"see ../../../README.md\n",
        ".claude/plans/y.md": b"# y\n",
        ".claude/odd.py": b"UP = Path(__file__).parents[1]\n",
        "tools/up.py": b"ROOT = Path(__file__).parents[1]\nX = '../x/y'\n",
        "README.md": b"# r\n",
    }
    MOVES = [(p, p.replace(".claude/specs", SPECS, 1)) for p in (
        ".claude/specs/tool/run.py", ".claude/specs/tool/both.toml",
        ".claude/specs/tool/notes.md", ".claude/specs/tool/blob.bin",
        ".claude/specs/tool/.env.ci", ".claude/specs/tool/dots.txt")] + [
        (".claude/plans/y.md", ".agents/artifacts/plans/y.md"),
        (".claude/odd.py", ".agents/knowledge/archive/adopted/.claude/odd.py")]
    TREES = {**{s: "/".join(s.split("/")[:2]) for s, _ in MOVES},
             ".claude/odd.py": ".claude/odd.py"}

    def setUp(self):
        self.root = Path(tempfile.mkdtemp()).resolve()
        git(self.root, "init", "--quiet", "-b", "main")
        git(self.root, "config", "commit.gpgsign", "false")
        for path, data in self.FILES.items():
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        git(self.root, "add", "-A", "-f")
        git(self.root, "commit", "--quiet", "-m", "fixture")

    def found(self, excluded=(), moves=None, trees=None):
        return [(o.subject, o.depth)
                for o in adopt_references.derive_references(
                    self.root, "HEAD", self.MOVES if moves is None else moves,
                    excluded, self.TREES if trees is None else trees
                ).occurrences]

    def test_moved_text_files_holding_a_climb_are_read(self):
        self.assertEqual(self.found(), [
            (".claude/odd.py:1:20", True),
            (".claude/specs/tool/both.toml:1:8", True),
            (".claude/specs/tool/both.toml:2:9", False),
            (".claude/specs/tool/dots.txt:1:5", True),
            (".claude/specs/tool/run.py:1:22", True)])

    def test_excluded_files_are_not_read(self):
        self.assertEqual(self.found([".claude/specs/tool/run.py"]), [
            (".claude/odd.py:1:20", True),
            (".claude/specs/tool/both.toml:1:8", True),
            (".claude/specs/tool/both.toml:2:9", False),
            (".claude/specs/tool/dots.txt:1:5", True)])

    def test_a_move_no_file_names_is_still_read_for_climbs(self):
        # No blob holds `tools`, so the first-segment prefilter finds nothing.
        self.assertEqual(
            self.found(moves=[("tools/up.py", "lib/tools/up.py")],
                       trees={"tools/up.py": "tools"}),
            [("tools/up.py:1:22", True), ("tools/up.py:2:6", True)])
```

(b) `home/common/agent-skills/tests/test_adopt_project.py` — the fixture, after `policy_row` and before `def write_dissolved_tree(`:

```python
# #380: a `.claude/notes` tree one level shallower than its destination,
# whose tooling climbs to the repository root (D1-D3, D6).
DEPTH_DIR = ".claude/notes/tool"
DEPTH_NEW = ".agents/artifacts/notes/tool"
DEPTH_CODE = {
    f"{DEPTH_DIR}/run.py": (
        "from pathlib import Path\n"
        "\n"
        "HERE = Path(__file__).resolve().parent\n"
        "ROOT = HERE.parents[2]\n"
        "NOTES = HERE.parent\n"
        'DATA = "../data/x"\n'),
    f"{DEPTH_DIR}/pyproject.toml": (
        "[tool.uv.sources]\n"
        'lib = { path = "../../../vendor/lib" }\n'),
    f"{DEPTH_DIR}/uv.lock": (
        "[[package]]\n"
        'name = "lib"\n'
        'source = { editable = "../../../vendor/lib" }\n'),
    "vendor/lib/__init__.py": "",
}
DEPTH_POLICIES = (".claude/notes:.lock/depth", ".claude/notes:.py/depth",
                  ".claude/notes:.toml/depth")
DEPTH_ROWS = (
    (f"{DEPTH_DIR}/pyproject.toml:2:17", "../../../vendor/lib",
     "../../../../vendor/lib", ".claude/notes:.toml/depth"),
    (f"{DEPTH_DIR}/run.py:4:12", ".parents[2]", ".parents[3]",
     ".claude/notes:.py/depth"),
    (f"{DEPTH_DIR}/uv.lock:3:24", "../../../vendor/lib",
     "../../../../vendor/lib", ".claude/notes:.lock/depth"))
DEPTH_REWRITE_ANSWERS = tuple(("reference-policy", subject, "rewrite")
                              for subject in DEPTH_POLICIES)
DEPTH_RETAIN_ANSWERS = tuple(("reference-policy", subject, "retain")
                             for subject in DEPTH_POLICIES)


def write_depth_tree(root: Path) -> None:
    for path, text in DEPTH_CODE.items():
        write(root, path, text)
    commit(root, "add tooling that climbs to the repository root")
```

and the plan cases, after `VariablePolicyPlanTest` and before the `# What \`POLICY_READY_ANSWERS\` edits` comment:

```python
class DepthPolicyPlanTest(AdoptTestCase):
    """#380 AC1, AC2: climbs out of a moved tree are asked about under the
    `<tree>:<class>/depth` policies, with no recommendation."""

    def test_climbs_to_the_root_open_their_own_policies(self):
        root = nix_config_shape_repo(self.home)
        write_depth_tree(root)
        code, doc, err = self.plan(root)
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            [(row["subject"], row["literal"], row["replacement"],
              row["policy"], row["answers"])
             for row in doc["path_references"]],
            [(*row, ["rewrite", "retain"]) for row in DEPTH_ROWS])
        self.assertEqual(
            [(entry["id"], entry["subject"], entry["value"])
             for entry in doc["decisions"]["open"]],
            [("reference-policy", subject, None)
             for subject in DEPTH_POLICIES])
        self.assertEqual(doc["reference_policies"],
                         [policy_row(subject, None, 1, 1)
                          for subject in DEPTH_POLICIES])

    def test_answering_the_depth_policies_reaches_ready(self):
        root = nix_config_shape_repo(self.home)
        write_depth_tree(root)
        code, doc, err = self.plan(root, *answer_args(*DEPTH_REWRITE_ANSWERS))
        self.assertEqual(code, 0, err or doc)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(
            [(row["subject"], row["answer"], row["decided_by"])
             for row in doc["path_references"]],
            [(row[0], "rewrite", "policy") for row in DEPTH_ROWS])
        self.assertEqual(
            [(row["class"], row["files"])
             for row in doc["reference_formatting"]],
            [(".lock", [f"{DEPTH_NEW}/uv.lock"]),
             (".py", [f"{DEPTH_NEW}/run.py"]),
             (".toml", [f"{DEPTH_NEW}/pyproject.toml"])])
```

(c) `home/common/agent-skills/tests/test_adopt_apply.py` — add `import posixpath` after `import json`, make the pathlib import `from pathlib import Path, PurePosixPath`, add `DEPTH_CODE`, `DEPTH_DIR`, `DEPTH_NEW`, `DEPTH_RETAIN_ANSWERS`, `DEPTH_REWRITE_ANSWERS`, `DEPTH_ROWS` and `write_depth_tree` to the alphabetical `from .test_adopt_project import (...)` list, and insert after `VariablePolicyApplyTest`, before the `# #376 D15:` comment:

```python
def climbed(directory: str, climb: str) -> str:
    """Where a text climb or a `.parents[N]` chain on `directory` lands,
    under a stand-in root `/r`, so a climb above the root stays visible."""
    start = PurePosixPath("/r", directory)
    if climb.startswith(".parents["):
        return str(start.parents[int(climb[len(".parents["):-1])])
    return posixpath.normpath(posixpath.join(str(start), climb))


class DepthPolicyApplyTest(ApplyTestCase):
    """#380 AC1: `rewrite` keeps each climb's landing point, `retain` keeps
    each file byte-identical."""

    def applied(self, answers: tuple) -> tuple[Path, dict, dict]:
        root = apply_repo(self.home)
        write_depth_tree(root)
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*answers), home=self.home)
        self.assertEqual(code, 0, err or out)
        document = json.loads(out)
        self.assertEqual(document["plan"]["state"], "ready",
                         document["plan"]["blockers"])
        return root, document, self.succeed(root, document["plan"]["plan_id"])

    def test_rewrite_lands_where_the_base_climb_landed(self):
        root, document, result = self.applied(DEPTH_REWRITE_ANSWERS)
        branch = result["branch"]
        rows = document["path_references"]
        self.assertEqual([row["subject"] for row in rows],
                         [row[0] for row in DEPTH_ROWS])
        for row in rows:
            with self.subTest(subject=row["subject"]):
                base = posixpath.dirname(row["path"])
                after = posixpath.dirname(row["target"])
                self.assertEqual(climbed(after, row["replacement"]),
                                 climbed(base, row["literal"]))
                self.assertNotEqual(climbed(after, row["literal"]),
                                    climbed(base, row["literal"]))
                text = git(root, "show", f"{branch}:{row['target']}")
                self.assertEqual(text, DEPTH_CODE[row["path"]].replace(
                    row["literal"], row["replacement"]))
        record = json.loads(git(
            root, "show", f"{branch}:{result['evidence_record']}"))
        for question, subject, value in DEPTH_REWRITE_ANSWERS:
            with self.subTest(subject=subject):
                self.assertIn(
                    {"id": question, "subject": subject, "value": value},
                    record["decisions_accepted"])
        self.assertEqual(record["path_references"], rows)
        self.assertEqual(record["reference_policies"],
                         document["reference_policies"])

    def test_retain_keeps_the_base_blobs(self):
        root, _, result = self.applied(DEPTH_RETAIN_ANSWERS)
        branch = result["branch"]
        for name in ("run.py", "pyproject.toml", "uv.lock"):
            with self.subTest(name=name):
                self.assertEqual(
                    git(root, "rev-parse", f"{branch}:{DEPTH_NEW}/{name}"),
                    git(root, "rev-parse", f"HEAD:{DEPTH_DIR}/{name}"))
```

(d) `home/common/agent-skills/tests/test_adopt_verify.py` — add `DEPTH_REWRITE_ANSWERS`, `answer_args` and `write_depth_tree` to the `from .test_adopt_project import (...)` list, and insert after `AnsweredCandidateVerifyTest`, before the `# Registration (D19, D18)` banner:

```python
class DepthRewriteVerifyTest(VerifyTestCase):
    def test_a_rewritten_climb_verifies_as_derived(self):
        """#380 AC5: the depth rewrites are planned writes of the adoption
        commit, so `adoption-commit-derived` passes."""
        root = apply_repo(self.home)
        write_depth_tree(root)
        code, out, err = run("plan", "--repo-root", str(root),
                             *answer_args(*DEPTH_REWRITE_ANSWERS),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        plan_id = json.loads(out)["plan"]["plan_id"]
        code, out, err = run("apply", "--plan-id", plan_id, home=self.home)
        self.assertEqual(code, 0, err or out)
        git(root, "merge", "--ff-only", "--quiet", json.loads(out)["branch"])
        report = self.report(root)
        self.assertEqual(report["result"], "adopted", report["checks"])
        self.assertEqual(
            self.check(report, "adoption-commit-derived")["status"], "passed")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py -k DepthDerivationTest`
Expected: FAIL, 3 tests — the depth read set is not derived yet: only `.claude/specs/tool/both.toml:2:9` (the plain reading) is found, and the `tools` move finds `[]`.

Run (timeout 1800 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py -k Depth`
Expected: FAIL, 5 tests — the plan has no depth row (`path_references` `[]`), so the `/depth` answers refuse `adopt.decisions.unmatched_answer` and the apply and verify cases fail at their first assertion.

- [ ] **Step 3: Write the minimal implementation**

1. `derive_references` in `python/agent_tools/adopt_references.py`: factor the existing grep into a private `_grep(root, revision, patterns, pathspecs) -> list[str]` (exit 1 → `[]`, other non-zero → the existing `adopt.git.failed` refusal, else the NUL-split paths with the `<revision>:` prefix removed); run it once for the first segments (no pathspec) and once for `-e .. -e __file__` over the literal tree pathspecs, keeping only paths that are move sources; return `References({}, ())` when both lists are empty; read each candidate through one memoised filter-and-decode helper (the existing filters, unchanged); pass the first scan's texts as `texts` and the second's as `depth_texts`. Docstring: the two read sets and that the depth set is limited to moved files.
2. The module docstring: the reader paragraph names the second scan and its limit to moved files in the moves' trees.
3. `adopt_planning.reference_questions` docstring: a `reference-policy` entry's `value` is null for every `/variable` and every `/depth` class. No code change there.
4. `python/README.md` § `adopt-project` (facts; write the sentences from the implemented code, D-cited behaviour only):
   - In the paragraph that describes the `git grep` prefilter: the depth reading has its own read set (moved files holding `..` or `__file__`, within the moves' trees, same filters), and the three earlier readings stay limited to the prefilter's files.
   - In the policy paragraph, beside `/variable`: the class of a depth occurrence is `<file class>/depth`, its question's `value` is null, `<tree>:<class>` and `<tree>:<class>/variable` answers never decide it, and a lock file is its own class (`uv.lock` → `.lock/depth`), with no manifest-to-lock pairing.
   - In the `path-reference` paragraph, qualify "A variable is never followed to its definition" with its one exception: the depth reading follows a Python name bound at column 0 to `Path(__file__)` or its `.parent` and rebound nowhere else in the file (the sentence must stay true of the implemented code).
   - A new paragraph after the variable-reading paragraph, citing https://github.com/fagenorn/nix-config/issues/380: the tree root (the group directory, or an archived file's own directory) and the landing point; the text climb (`./` optional, `..` segments, a `/`, anchored at the file's directory; a bare `..` and a rest holding `..` are not read); the Python chain (anchors, grammar, `.py` only, what is not read); when a climb is surfaced (landing point above the tree root and changed by the move, base target not back inside the tree); `rewrite` shifts the height by the depth delta and is offered only when that lands on the same point, the base target names no moved path and the form stays valid; every depth occurrence offers `retain` and never `extend`; climbs in Markdown and in files the plan does not move are not read.
5. Inventory check, by hand at the start of the task: `rg -n '__file__|\.\./' home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py` lists only Markdown fixture text, symlink targets and test-module code, so no existing fixture's moved non-Markdown file holds a climb; if a later rebase adds one, an existing test failing here is a plan bug to report, not a test to edit.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_references.py`
Expected: PASS, every test.

Run (timeout 3000 s): `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py home/common/agent-skills/tests/test_adopt_project_boundaries.py`
Expected: PASS — the five `Depth*` cases and every existing case (AC4), no failures.

Run: `git diff --stat 15ccdd44bb73330e49be63cffa8b7c03f56c709c -- python/agent_tools/adopt_apply.py python/agent_tools/adopt_verify.py python/agent_tools/adopt_project.py`
Expected: no output.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_references.py python/agent_tools/adopt_planning.py python/README.md home/common/agent-skills/tests/test_adopt_references.py home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py home/common/agent-skills/tests/test_adopt_verify.py
launch-commit … -- -m "feat(adopt): surface depth-relative paths in plan and apply (#380)"
```
