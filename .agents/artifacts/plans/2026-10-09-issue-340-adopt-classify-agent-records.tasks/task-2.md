# Task 2: Every undecided candidate opens a `candidate-class` question

**Files:**
- Modify: `python/agent_tools/adopt_inspection.py`
- Modify: `python/agent_tools/adopt_planning.py`
- Modify: `python/agent_tools/adopt_project.py` (`compose_plan`, `emit_human`)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`

**Interfaces:**
- Consumes: Task 1's classification rows (the fixtures below rely on `nix_config_shape_repo` planning to `ready`).
- Produces, in `adopt_inspection`:
  - `QUESTION_IDS = ("project-id", "candidate-class")` (D3).
  - `ARCHIVE_ADOPTED_DIR = ".agents/knowledge/archive/adopted"`.
  - `CANDIDATE_BASIS: str` — fixed prose (D8).
  - `candidate_answer(provenance: str, path: str) -> str | None` — `"tracked"` → `None` when `is_secret_path(path)`, else `"archive-history"`; `"targeted-ignored"` → `"retain-product"`; any other value raises `ValueError` (D4, D7).
  - `question_impact` / `question_recommendation` gain a `"candidate-class"` branch and still raise `ValueError` for every other id.
- Produces, in `adopt_planning`: `candidate_questions(found: Candidates) -> list[dict]` — one open entry per evidence entry whose `action` is `"needs-decision"`, shape `{"id": "candidate-class", "subject": entry["path"], "value": candidate_answer(entry["provenance"], entry["path"]), "basis": CANDIDATE_BASIS, "impact": question_impact("candidate-class"), "recommendation": question_recommendation("candidate-class")}`, sorted by `subject`.
- Produces, in `adopt_project.compose_plan`: `decisions["open"]` is `derive_identity`'s open list plus `candidate_questions(found)`, sorted by `(QUESTION_IDS.index(entry["id"]), entry.get("subject", ""))`, so `project-id` comes first (D3). Computed from `found` after the untracked-overlap entries are appended (those are never `needs-decision`).

**Invariants:**
- `project-id` entries keep exactly `basis, id, impact, recommendation, value`; only `candidate-class` entries carry `subject` (D3).
- `basis`, `impact`, `recommendation` never contain the candidate path (D8).
- Fixed strings, dictated verbatim (D8):
  - `CANDIDATE_BASIS = "no classification row covers this agent path"`
  - impact: `"the candidate keeps the needs-decision action, so the no-needs-decision and no-open-decisions gates fail and the plan stays draft"`
  - recommendation, interim and true at this task's commit (no answer is accepted yet): `"add a central classification row for this path, or remove it from the repository in its own commit, then plan again"`. Task 3, which lands `--answer` and `apply`'s replay together, replaces it with D8's final sentence; nothing in this task names `--answer`.
- `emit_human` prints a `candidate-class` open entry as `open candidate-class <subject> (answer: <value>): <recommendation>`, with `none` for a null value; a `project-id` line is unchanged (`open project-id: <recommendation>`) (D8).
- No change to `plan_id` inputs in this task: `decisions.answered` stays `[]`.

- [ ] **Step 1: Write the failing tests**

Change the module import to `from agent_tools import adopt_inspection, adopt_planning, adopt_project`. Add module-level fixtures after `record_trees_repo`:

```python
def candidate_repo(home: Path, *paths: str) -> Path:
    """`nix_config_shape_repo` plus tracked agent paths no row classifies."""
    root = nix_config_shape_repo(home)
    for path in paths:
        write(root, path, f"# {path}\n")
    commit(root, "add unclassified agent paths")
    return root


def ignored_symlink_repo(home: Path) -> Path:
    """`nix_config_shape_repo` plus an ignored `.claude/settings.local.json`
    that is a symlink out of the checkout: the one way an ignored candidate
    stays `needs-decision`."""
    root = nix_config_shape_repo(home)
    outside = Path(tempfile.mkdtemp()).resolve() / "settings.json"
    outside.write_text("{}\n", encoding="utf-8")
    with (root / ".gitignore").open("a", encoding="utf-8") as handle:
        handle.write(".claude/settings.local.json\n")
    (root / ".claude" / "settings.local.json").symlink_to(outside)
    commit(root, "ignore an escaping local settings link")
    return root
```

Add a test class after `RecordTreeClassificationTest`:

```python
class CandidateQuestionTest(AdoptTestCase):
    """#340 AC2: every undecided candidate carries a stable question."""

    OPEN_MEMBERS = ["basis", "id", "impact", "recommendation", "subject",
                    "value"]

    def only_open(self, doc: object) -> dict:
        self.assertEqual(len(doc["decisions"]["open"]), 1,
                         doc["decisions"]["open"])
        entry = doc["decisions"]["open"][0]
        self.assertEqual(sorted(entry), self.OPEN_MEMBERS)
        self.assertEqual(entry["id"], "candidate-class")
        return entry

    def test_a_tracked_candidate_opens_one_archive_question(self):
        doc = self.ready_plan(candidate_repo(self.home, ".claude/odd.md"))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/odd.md", "archive-history"))
        for member in ("basis", "impact", "recommendation"):
            self.assertNotIn(".claude/odd.md", entry[member])
        self.assertEqual(doc["plan"]["state"], "draft")
        self.assertEqual(
            sorted(blocker["id"] for blocker in doc["plan"]["blockers"]),
            ["no-needs-decision", "no-open-decisions"])

    def test_the_prose_is_fixed_across_candidates(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/zeta/b.md", ".claude/a.md"))
        entries = doc["decisions"]["open"]
        self.assertEqual([entry["subject"] for entry in entries],
                         [".claude/a.md", ".claude/zeta/b.md"])
        for member in ("basis", "impact", "recommendation"):
            self.assertEqual(entries[0][member], entries[1][member])

    def test_a_secret_shaped_candidate_has_no_answer(self):
        doc = self.ready_plan(candidate_repo(
            self.home, ".claude/secrets/key.md"))
        entry = self.only_open(doc)
        self.assertEqual(entry["subject"], ".claude/secrets/key.md")
        self.assertIsNone(entry["value"])

    def test_an_ignored_candidate_is_offered_retention(self):
        doc = self.ready_plan(ignored_symlink_repo(self.home))
        entry = self.only_open(doc)
        self.assertEqual((entry["subject"], entry["value"]),
                         (".claude/settings.local.json", "retain-product"))

    def test_project_id_sorts_before_candidate_questions(self):
        root = reconcile_repo(self.home, remotes=())
        write(root, ".claude/odd.md", "# odd\n")
        commit(root, "add an unclassified agent path")
        doc = self.ready_plan(root)
        self.assertEqual([entry["id"] for entry in doc["decisions"]["open"]],
                         ["project-id", "candidate-class"])
        self.assertEqual(sorted(doc["decisions"]["open"][0]),
                         ["basis", "id", "impact", "recommendation", "value"])

    def test_the_human_view_names_each_subject_and_its_answer(self):
        root = candidate_repo(self.home, ".claude/odd.md",
                              ".claude/secrets/key.md")
        code, human, err = run("plan", "--repo-root", str(root),
                               "--format", "human", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertIn("open candidate-class .claude/odd.md "
                      "(answer: archive-history): ", human)
        self.assertIn("open candidate-class .claude/secrets/key.md "
                      "(answer: none): ", human)

    def test_the_question_set_is_closed(self):
        self.assertEqual(adopt_inspection.QUESTION_IDS,
                         ("project-id", "candidate-class"))
        for function in (adopt_inspection.question_impact,
                         adopt_inspection.question_recommendation):
            with self.subTest(function=function.__name__):
                with self.assertRaises(ValueError):
                    function("candidate-class:.claude/odd.md")
        with self.assertRaises(ValueError):
            adopt_inspection.candidate_answer("untracked-explicit-paths",
                                              ".claude/odd.md")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k CandidateQuestionTest`
Expected: FAIL, 7 tests — `decisions.open` is `[]` for every candidate fixture, and `candidate_answer` is not defined.

- [ ] **Step 3: Write the minimal implementation**

1. `adopt_inspection`: the constants, `candidate_answer` beside the other closed-set dispatchers, and the two new question branches, all as pinned above. Update the D35 comment over `QUESTION_IDS` only to say that a `candidate-class` entry is keyed by its `subject`.
2. `adopt_planning.candidate_questions` as pinned; import the new names from `adopt_inspection`.
3. `adopt_project.compose_plan`: build `decisions["open"]` as pinned. `emit_human`: the two line shapes as pinned.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py`
Expected: PASS, both modules, no failures (the existing `project-id` key-set pins stay green unchanged).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_inspection.py python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py home/common/agent-skills/tests/test_adopt_project.py
launch-commit … -- -m "feat(adopt): open a candidate-class question per undecided candidate (#340)"
```
