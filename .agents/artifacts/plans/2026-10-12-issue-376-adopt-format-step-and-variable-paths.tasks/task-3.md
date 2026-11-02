# Task 3: The `reference-format` answer, `reference_formatting`, the tenth `plan_id` input and the human line

**Files:**
- Modify: `python/agent_tools/adopt_planning.py`
- Modify: `python/agent_tools/adopt_project.py`
- Modify: `python/README.md` (§ `adopt-project`, the `--answer` paragraph only)
- Test: `home/common/agent-skills/tests/test_adopt_project.py`
- Test: `home/common/agent-skills/tests/test_adopt_apply.py` (one guard case, removed again by Task 4)

**Interfaces:**
- Consumes: `adopt_references.rewritten`, `adopt_references.file_class`, `reference_answers`, `policy_answers`, `load_contract_source`.
- Produces (Task 4 relies on these):
  - `adopt_planning.format_answers(answered: list[dict]) -> dict[str, str]` — `class -> command id` of the settled `reference-format` answers.
  - `adopt_planning.contract_command_ids(contract_source: dict | None) -> frozenset[str]` — the keys of the authored `bindings.commands`, empty when there is no contract or no such object.
  - `adopt_planning.reference_formatting(reference_files: Mapping[str, tuple[str, str]], answered: list[dict]) -> list[dict]` — one `{"class", "command", "files"}` row per class with an edited file, sorted by class; `files` sorted; `command` the answered id or None.
  - `apply_answers(root, found, inventory, answers, excluded, commands: frozenset[str])` — new last parameter.
  - `compute_plan_id(..., reference_policies, reference_formatting)` — tenth positional parameter, no default (D14).
  - `bookkeeping_operations(..., reference_policies, reference_formatting)` — the evidence record gains a `reference_formatting` member.
  - The plan document gains a top-level `reference_formatting` member (eleven members).

**Invariants:**
- `reference-format` opens no question; `QUESTION_IDS` is unchanged; a plan with no such answer differs from today only by `reference_formatting` and the id it feeds (D2).
- Rows come only from `adopt_references.rewritten`'s keys (the path-reference edits), classed by `file_class` of the target; Markdown link rewrites, the contract, records and projections never appear (D3).
- `reference-format` answers are validated after every other answer and before any candidate mutation, per answer in `(subject, value)` order: repeated subject → `adopt.decisions.invalid_answer`; class of no edited file → `adopt.decisions.unmatched_answer`; value not in `commands` → `adopt.decisions.invalid_answer` (D11). Every refusal points at `/decisions/answered` and stores nothing.
- The answer changes no planned operation's `after`: formatting happens in `apply` (D4).
- Fail-closed until Task 4 (D16): `apply` of a plan with a `reference_formatting` row whose `command` is not None refuses `verification_failed`, `adopt.format.failed`, pointer `/reference_formatting`, at the point Task 4's step will run (after every operation executed and matched, before `GateRun`), so the worktree and branch are retained and every commit gate is recorded `not_run`. A plan whose rows all have `command` None applies exactly as today.

- [ ] **Step 1: Write the failing tests**

In `home/common/agent-skills/tests/test_adopt_project.py` (D14 — these are the only edits to existing tests):
- `TOP_LEVEL_MEMBERS`: add `"reference_formatting"` in sorted position (before `"reference_policies"`); rename `test_exactly_ten_top_level_members` to `test_exactly_eleven_top_level_members`.
- `documented_plan_id`: add `"reference_formatting": doc["reference_formatting"]` to `source`; its docstring says "the ten named members".
- The evidence-record rebuild in `TypedOperationTest` (the `record = {...}` holding `"reference_policies": doc["reference_policies"]`): add `"reference_formatting": doc["reference_formatting"]`.
- Each `adopt_planning.compute_plan_id(...)` call (`rg -n "compute_plan_id\(" home/common/agent-skills/tests`): append the document's `reference_formatting` as the last argument (`doc[...]`, `extended[...]` or `rewritten[...]` as the call site names it).
- Run `rg -n "reference_policies" home/common/agent-skills/tests` and make the same addition wherever a full member list of the document or the record is pinned.

Add after `ReferencePolicyPlanTest` (and after `VariablePolicyPlanTest` if present):

```python
# What `POLICY_READY_ANSWERS` edits, by class, before any format answer.
FORMAT_ROWS = [
    {"class": ".nix", "command": None,
     "files": [f"{POLICY_NEW}/devenv.nix"]},
    {"class": ".py", "command": None,
     "files": [f"{POLICY_NEW}/paths.py", f"{POLICY_NEW}/report.py",
               RUN_REPORT]},
    {"class": ".toml", "command": None, "files": [LINT_TOML]},
]


class ReferenceFormattingPlanTest(AdoptTestCase):
    """#376 D2, D3, D11: a formatter is declared per edited class by an
    answer, never asked for, and published in `reference_formatting`."""

    def answered(self, root: Path, *triples: tuple[str, str, str]) -> object:
        code, doc, err = self.plan(root, *answer_args(*triples))
        self.assertEqual(code, 0, err or doc)
        return doc

    def command(self, root: Path) -> str:
        """A command id the fixture's contract declares; `plan` never runs
        it, and any declared id is accepted (D2)."""
        contract = json.loads(
            (root / ".agents" / "project.json").read_text("utf-8"))
        return sorted(contract["bindings"]["commands"])[0]

    def stored_plans(self) -> list[str]:
        store = self.home / ".agents" / "state" / "adopt" / "plans"
        return sorted(path.name for path in store.iterdir()) \
            if store.is_dir() else []

    def test_rows_list_every_edited_class_without_a_command(self):
        self.assertEqual(
            self.answered(nix_config_shape_repo(self.home))
            ["reference_formatting"], [])
        doc = self.answered(policy_repo(self.home), *POLICY_READY_ANSWERS)
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["reference_formatting"], FORMAT_ROWS)

    def test_a_format_answer_names_the_command_and_changes_the_id(self):
        root = policy_repo(self.home)
        command = self.command(root)
        without = self.answered(root, *POLICY_READY_ANSWERS)
        doc = self.answered(root, *POLICY_READY_ANSWERS,
                            ("reference-format", ".py", command))
        self.assertEqual(doc["plan"]["state"], "ready",
                         doc["plan"]["blockers"])
        self.assertEqual(doc["decisions"]["open"], [])
        self.assertIn(
            {"id": "reference-format", "subject": ".py", "value": command},
            doc["decisions"]["answered"])
        self.assertEqual(doc["reference_formatting"], [
            FORMAT_ROWS[0], {**FORMAT_ROWS[1], "command": command},
            FORMAT_ROWS[2]])
        self.assertNotEqual(doc["plan"]["plan_id"],
                            without["plan"]["plan_id"])
        self.assertEqual(doc["plan"]["plan_id"], documented_plan_id(doc))

        def code_writes(document: object) -> dict[str, str]:
            return {op["targets"][0]: op["after"]
                    for op in document["changes"]
                    if op["op"] == "write-file"
                    and op["targets"][0].startswith((POLICY_NEW, "tools/"))}
        self.assertEqual(code_writes(doc), code_writes(without))

    def test_compute_plan_id_covers_the_rows(self):
        root = policy_repo(self.home)
        doc = self.answered(root, *POLICY_READY_ANSWERS,
                            ("reference-format", ".py", self.command(root)))
        inputs = (doc["plan"]["project_id"], doc["plan"]["base_revision"],
                  doc["plan"]["platform"], doc["evidence"],
                  doc["decisions"]["answered"], doc["link_rewrites"],
                  doc["path_references"], doc["reference_policies"])
        self.assertEqual(
            adopt_planning.compute_plan_id(*inputs,
                                           doc["reference_formatting"]),
            doc["plan"]["plan_id"])
        other = json.loads(json.dumps(doc["reference_formatting"]))
        other[1]["files"] = other[1]["files"][:-1]
        self.assertNotEqual(adopt_planning.compute_plan_id(*inputs, other),
                            doc["plan"]["plan_id"])

    def test_invalid_format_answers_refuse_and_store_nothing(self):
        root = policy_repo(self.home)
        command = self.command(root)
        no_python_edit = tuple(
            triple for triple in POLICY_READY_ANSWERS
            if triple[1] not in (PY_POLICY, RUN_SUBJECT)) + (
            ("reference-policy", PY_POLICY, "retain"),
            ("path-reference", RUN_SUBJECT, "retain"))
        unmatched = "adopt.decisions.unmatched_answer"
        invalid = "adopt.decisions.invalid_answer"
        for triples, repair_id in (
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".md", command)), unmatched),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".json", command)), unmatched),
                ((*no_python_edit,
                  ("reference-format", ".py", command)), unmatched),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".py", "no-such-command")), invalid),
                ((*POLICY_READY_ANSWERS,
                  ("reference-format", ".py", command),
                  ("reference-format", ".py", "zz-other")), invalid),
                # Validated after the other ids, though it sorts first.
                ((("reference-policy", ".claude/notes:.md", "retain"),
                  ("reference-format", ".py", "no-such-command")),
                 unmatched)):
            with self.subTest(triples=triples):
                before = self.stored_plans()
                code, payload, err = self.plan(root, *answer_args(*triples))
                self.assertEqual(code, 2, err or payload)
                self.assertEqual(payload["error"]["code"], "adopt_failure")
                self.assertEqual(payload["error"]["repair_id"], repair_id)
                self.assertEqual(
                    payload["error"]["violations"][0]["pointer"],
                    "/decisions/answered")
                self.assertEqual(self.stored_plans(), before)

    def test_the_human_view_prints_each_format_row(self):
        root = policy_repo(self.home)
        command = self.command(root)
        code, out, err = run(
            "plan", "--repo-root", str(root), "--format", "human",
            *answer_args(*POLICY_READY_ANSWERS,
                         ("reference-format", ".py", command)),
            home=self.home)
        self.assertEqual(code, 0, err)
        for line in ("format .nix: 1 files, command none",
                     f"format .py: 3 files, command {command}",
                     "format .toml: 1 files, command none"):
            with self.subTest(line=line):
                self.assertIn(f"\n{line}\n", out)
        self.assertLess(out.rindex("\npolicy "), out.index("\nformat "))
```

In `home/common/agent-skills/tests/test_adopt_apply.py`, one guard case (D16), which Task 4 deletes when it adds `ReferenceFormattingApplyTest`: `ReferenceFormatGuardTest(ApplyTestCase)` with `test_a_declared_formatter_is_refused_until_apply_runs_it`. Build `apply_repo(self.home, commands={"format": ["true"]})`, add a tracked non-Markdown text file holding a quoted `.claude/specs/x.md` literal and commit it, plan with that occurrence's `path-reference` answer `rewrite` and `("reference-format", "<its class>", "format")`, require the plan `ready`, then `self.assert_retained(root, plan_id, base, "adopt.format.failed")` and require every gate of the stored `.failure.json` record `not_run` (the same reads Task 4's refusal case makes). Reuse the helpers the module already has; if `apply_repo` has no `commands` parameter yet, add it here with the shape Task 4's fixture calls it with (`commands: dict[str, list[str]] | None = None`, written into the contract's `bindings.commands`).

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py -k ReferenceFormattingPlanTest -k DocumentShapeTest -k PlanIdentityTest` (timeout 1800 s)
Expected: FAIL/ERROR — `KeyError: 'reference_formatting'`, the refusal cases exit 2 with "only a candidate-class, path-reference or reference-policy question can be answered" (`invalid_answer` where `unmatched_answer` is expected), and `compute_plan_id` takes 9 positional arguments.

- [ ] **Step 3: Write the minimal implementation**

`python/agent_tools/adopt_planning.py`:
1. `format_answers`, `contract_command_ids` and `reference_formatting` beside `reference_answers`/`policy_answers`, with the signatures in **Interfaces**. `contract_command_ids` reads `contract_source["bindings"]["commands"]` only through `isinstance` checks; `reference_formatting` groups `reference_files` keys by `adopt_references.file_class(target)`.
2. `_ANSWERED_THING["reference-format"] = "reference format"`.
3. `apply_answers(..., excluded, commands)`: the accepted id set gains `reference-format` (the refusal message names all four ids). In the sorted loop a `reference-format` answer is set aside before the repeat check and skipped. After the loop and **before** the candidate mutation, when any were set aside: derive `references` from the loop's `moves` and `trees` if not yet derived (the call the loop already makes); take the edited classes as `{file_class(t) for t in adopt_references.rewritten(references, reference_answers(answers), policy_answers(answers))}`; then validate the set-aside answers in `(subject, value)` order per the **Invariants** (D11). Settled answers stay sorted by `(id, subject)` and are returned unchanged otherwise. Update the docstring: the four ids, the deferred validation and its order, and that nothing is mutated before every answer validated.
4. `compute_plan_id`: tenth parameter `reference_formatting: list[dict]`, source key `"reference_formatting"`; docstring: exactly ten inputs, naming the `reference_formatting` rows (#376).
5. `bookkeeping_operations`: new last parameter `reference_formatting: list[dict]`; the record dict gains `"reference_formatting": reference_formatting` after `"reference_policies"`. `EVIDENCE_RECORD_MEMBERS` is not changed (the required minimum).

`python/agent_tools/adopt_project.py`:
0. `command_apply` (D16): inside the existing `try` that executes the operations, after the loop, when any row of `composed.document["reference_formatting"]` has a `command`, raise `adopt_inspection.refuse("verification_failed", "adopt.format.failed", "/reference_formatting", <message saying this apply cannot run a declared formatter>)` (reach `refuse` the way the module already reaches it), so the refusal takes the existing `retain_failure` path with every commit gate `not_run`. A one-line comment says Task 4's formatting step replaces it; no TODO is left in a docstring.
1. `compose_plan`: pass `adopt_planning.contract_command_ids(contract_source)` to `apply_answers`; after `reference_files`, `reference_formatting = adopt_planning.reference_formatting(reference_files, answered)`; pass it to `compute_plan_id` and `bookkeeping_operations`; the document gains `"reference_formatting": reference_formatting` after `"reference_policies"`. The `compose_plan` docstring names `reference-format` among the answers.
2. `emit_human`: after the `policy …` lines, one line per row: `f"format {row['class']}: {len(row['files'])} files, command {row['command'] or 'none'}"`.
3. `build_parser`: the `--answer` help names `reference-format` (a command id of the contract, run by `apply` over a class's reference-edited files).
4. The module docstring: the plan document has eleven members, `reference_formatting` included, and `plan_id` covers exactly ten inputs, `reference_formatting` added to the listed set.

`python/README.md` § `adopt-project`, the first paragraph (the one listing `candidate-class`, `path-reference` and `reference-policy` as the only answerable ids): written from the implemented code, it names `reference-format` as a fourth answerable id that opens no question (described in a later paragraph), keeps the refusal list true (an id other than the four), and says the `reference-format` answers are validated after the others, in `(subject, value)` order, so the `(id, subject, value)` order statement covers the other three ids only. Keep the count of open-question kinds unchanged.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_project_boundaries.py` (timeout 1800 s)
Expected: PASS, no failures.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k ApplySuccessTest -k ReferencePolicyApplyTest` (timeout 1800 s)
Expected: PASS — a plan without `reference-format` still applies.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_adopt_apply.py -k ReferenceFormatGuardTest` (timeout 1800 s)
Expected: PASS — the declared formatter is refused `adopt.format.failed` with every gate `not_run`.

Run: `rg -q "reference-format" python/README.md`
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/adopt_planning.py python/agent_tools/adopt_project.py python/README.md home/common/agent-skills/tests/test_adopt_project.py home/common/agent-skills/tests/test_adopt_apply.py
launch-commit … -- -m "feat(adopt): declare a formatter per edited class and publish reference_formatting (#376)"
```
