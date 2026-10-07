# Task 2: L1–L5 rules, the debt file and the `skill-lint` command

Per D5, D6, D11, D12, D17. Measures issue #292 AC1.

**Files:**
- Modify: `python/agent_tools/skill_lint.py`
- Create: `home/common/agent-skills/skill-lint-debt.json`
- Modify: `home/common/agent-skills/tests/test_skill_lint.py` (append four classes before `if __name__ == "__main__":`)
- Modify: `lib/agent-tools.nix` (add `"skill-lint"` to `commands`, between `"review-range"` and `"verified-tree"`)

**Interfaces:**
- Consumes (Task 1, `agent_tools.skill_lint`): `Snapshot`, `working_tree`, `skill_dirs`, `SkillDir`, `parse_frontmatter`, `reflowed_lines`, `names`, `MD_TOKEN`. Test helpers in `test_skill_lint.py`: `clean_files()`, `dict_snapshot(files)`, `skill(name, description=..., body=...)`, `ALPHA`, `SHARED`, `CODEX`, `REPO_ROOT`.
- Produces (Task 4 relies on these exact names):
  - `DEBT_PATH = "home/common/agent-skills/skill-lint-debt.json"`.
  - `@dataclass(frozen=True, order=True) class Violation: key: str; text: str`.
  - `violations(snapshot: Snapshot) -> list[Violation]`, sorted with duplicates removed.
  - `load_debt(raw: bytes) -> list[str]`, which raises `ValueError`.
  - `lint(snapshot: Snapshot) -> list[str]`: one failure line per unlisted violation or stale debt key; `[]` when clean. It raises `ValueError` when it cannot run.
  - `main(argv=None) -> int`: `skill-lint check [--root PATH]`.

**Invariants:**
- A key is `<rule> <repo-relative path>`, where the rule is one of `L1 L2 L3 L4a L4b`/`L5`. Only an L4b key appends ` names <basename>`. Several violations of one rule on one file share one key (per D17).
- `lint` lines are `f"{key}: {text}"` for each violation whose key is not in the debt, in `violations` order. They are followed by `f"{key}: stale debt entry; delete it from {DEBT_PATH}"` for each debt key no violation produces, in debt order.
- The debt file is `{"debt": [<key>, …]}` and nothing else. Its keys are strings, sorted and unique, and it is loaded through the canonical strict-JSON hooks (per D5).
- Exit codes: 0 clean, 1 failure lines (on stdout, one per line), 2 cannot run (one stderr line prefixed `skill-lint: `, empty stdout).
- The live tree lints clean against the committed debt file.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_skill_lint.py`, before `if __name__ == "__main__":`:

```python
DEBT = "home/common/agent-skills/skill-lint-debt.json"
ALPHA_BODY = "Read GUIDE.md first.\nHand alpha-prompt.md and CONTRACT.md to the reviewer.\n"


class RuleTest(unittest.TestCase):
    def setUp(self):
        self.files = clean_files()

    def keys(self, files=None):
        return {v.key for v in skill_lint.violations(dict_snapshot(files or self.files))}

    def test_the_clean_tree_has_no_violation(self):
        self.assertEqual(skill_lint.violations(dict_snapshot(self.files)), [])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [])

    def test_l1_reports_every_frontmatter_form(self):
        path = f"{ALPHA}/SKILL.md"
        body = ALPHA_BODY.encode()
        cases = {
            "name differs": skill("alphax", body=ALPHA_BODY),
            "missing name": b"---\ndescription: Alphas. Use when testing.\n---\n" + body,
            "missing description": b"---\nname: alpha\n---\n" + body,
            "empty description": b"---\nname: alpha\ndescription:\n---\n" + body,
            "long description": skill("alpha", "Use when testing. " + "x" * 1010, ALPHA_BODY),
            "xml description": skill("alpha", "Alphas <b>things</b>. Use when testing.",
                                     ALPHA_BODY),
            "no fence": body,
            "unclosed fence": b"---\nname: alpha\n" + body,
            "block scalar": b"---\nname: alpha\ndescription: >\n---\n" + body,
            "duplicate key": b"---\nname: alpha\nname: alpha\n"
                             b"description: Alphas. Use when x.\n---\n" + body,
        }
        for label, data in cases.items():
            with self.subTest(case=label):
                files = clean_files()
                files[path] = data
                self.assertEqual(self.keys(files), {f"L1 {path}"})

    def test_l1_judges_the_name_itself(self):
        for name in ("a" * 65, "Upper", "claude-helper", "anthropic-x"):
            with self.subTest(name=name):
                files = clean_files()
                path = f"{SHARED}/{name}/SKILL.md"
                files[path] = skill(name)
                self.assertEqual(self.keys(files), {f"L1 {path}"})

    def test_l1_reports_a_skill_directory_without_skill_md(self):
        self.files[f"{SHARED}/orphan/NOTES.md"] = b"notes\n"
        self.assertEqual(self.keys(), {f"L1 {SHARED}/orphan/SKILL.md"})

    def test_l2_counts_reflowed_body_lines(self):
        path = f"{ALPHA}/SKILL.md"
        for body, expected in ((ALPHA_BODY + "x\n" * 498, set()),
                               (ALPHA_BODY + "x\n" * 499, {f"L2 {path}"}),
                               (ALPHA_BODY + "x\n" * 496 + "y" * 201 + "\n", {f"L2 {path}"})):
            with self.subTest(lines=body.count("\n")):
                files = clean_files()
                files[path] = skill("alpha", "Alphas things. Use when testing.", body)
                self.assertEqual(self.keys(files), expected)

    def test_l3_demands_a_contents_list_past_100_reflowed_lines(self):
        guide = f"{ALPHA}/GUIDE.md"
        filler = "line\n"
        cases = (
            ("100 lines, no contents", "# Guide\n" + filler * 99, set()),
            ("101 lines, no contents", "# Guide\n" + filler * 100, {f"L3 {guide}"}),
            ("101 lines with contents",
             "# Guide\n## Contents\n- [A](#a)\n## A\n" + filler * 97, set()),
            ("contents after another heading",
             "# Guide\n## A\n## Contents\n- [A](#a)\n" + filler * 97, {f"L3 {guide}"}),
            ("contents heading without a list",
             "# Guide\n## Contents\nprose\n## A\n" + filler * 97, {f"L3 {guide}"}),
            ("a fenced heading comes first",
             "# Guide\n```\n## Not a heading\n```\n## Contents\n- a\n" + filler * 95, set()),
        )
        for label, text, expected in cases:
            with self.subTest(case=label):
                files = clean_files()
                files[guide] = text.encode()
                self.assertEqual(self.keys(files), expected)

    def test_l4a_reports_a_reference_its_skill_md_does_not_name(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.assertEqual(self.keys(), {f"L4a {ALPHA}/ORPHAN.md"})

    def test_l4b_reports_a_reference_naming_a_sibling_reference(self):
        self.files[f"{ALPHA}/OTHER.md"] = b"other\n"
        self.files[f"{ALPHA}/SKILL.md"] = skill("alpha", "Alphas things. Use when testing.",
                                                ALPHA_BODY + "See OTHER.md.\n")
        self.files[f"{ALPHA}/GUIDE.md"] = b"# Guide\nsee OTHER.md\n"
        self.assertEqual(self.keys(), {f"L4b {ALPHA}/GUIDE.md names OTHER.md"})

    def test_l4_exempts_payloads_and_naming_skill_md_or_a_payload(self):
        # GUIDE.md names SKILL.md and the payload CONTRACT.md; the payload
        # alpha-prompt.md names the reference GUIDE.md. None of it is a violation.
        self.files[f"{ALPHA}/CONTRACT.md"] = b"contract naming GUIDE.md\n"
        self.assertEqual(self.keys(), set())

    def test_l5_demands_third_person_and_a_trigger_clause(self):
        path = f"{ALPHA}/SKILL.md"
        for description, expected in (("You alpha things. Use when testing.", {f"L5 {path}"}),
                                      ("I alpha things. Use when testing.", {f"L5 {path}"}),
                                      ("Alphas things.", {f"L5 {path}"}),
                                      ("Alphas things. Invoke before planning.", set())):
            with self.subTest(description=description):
                files = clean_files()
                files[path] = skill("alpha", description, ALPHA_BODY)
                self.assertEqual(self.keys(files), expected)


class DebtTest(unittest.TestCase):
    def setUp(self):
        self.files = clean_files()

    def debt(self, keys):
        self.files[DEBT] = json.dumps({"debt": keys}).encode()

    def test_a_listed_violation_is_suppressed(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.debt([f"L4a {ALPHA}/ORPHAN.md"])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [])

    def test_an_unlisted_violation_is_one_failure_line(self):
        self.files[f"{ALPHA}/ORPHAN.md"] = b"orphan\n"
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)),
                         [f"L4a {ALPHA}/ORPHAN.md: not named in its SKILL.md"])

    def test_a_stale_entry_fails(self):
        self.debt(["L4a gone.md"])
        self.assertEqual(skill_lint.lint(dict_snapshot(self.files)), [
            "L4a gone.md: stale debt entry; delete it from "
            "home/common/agent-skills/skill-lint-debt.json"])

    def test_a_malformed_debt_file_cannot_run(self):
        for raw in (b'{"debt": ["b", "a"]}', b'{"debt": ["a", "a"]}', b'{"debt": "a"}',
                    b'{"debt": [], "extra": 1}', b'{"debt": [1]}', b"[]",
                    b'{"debt": [], "debt": []}', b"\xff", None):
            with self.subTest(raw=raw):
                files = clean_files()
                if raw is None:
                    del files[DEBT]
                else:
                    files[DEBT] = raw
                with self.assertRaises(ValueError):
                    skill_lint.lint(dict_snapshot(files))


class CommandTest(unittest.TestCase):
    def run_lint(self, files):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for relative, data in files.items():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_bytes(data)
            return subprocess.run(
                [sys.executable, "-m", "agent_tools.skill_lint", "check", "--root", str(root)],
                capture_output=True, text=True, check=False)

    def test_exit_codes(self):
        clean = self.run_lint(clean_files())
        self.assertEqual((clean.returncode, clean.stdout, clean.stderr), (0, "", ""))
        orphaned = self.run_lint({**clean_files(), f"{ALPHA}/ORPHAN.md": b"orphan\n"})
        self.assertEqual((orphaned.returncode, orphaned.stdout),
                         (1, f"L4a {ALPHA}/ORPHAN.md: not named in its SKILL.md\n"))
        no_codex = {p: d for p, d in clean_files().items() if not p.startswith(CODEX)}
        for files in ({**clean_files(), DEBT: b"{"}, no_codex):
            broken = self.run_lint(files)
            self.assertEqual((broken.returncode, broken.stdout), (2, ""))
            self.assertEqual(len(broken.stderr.splitlines()), 1, broken.stderr)
            self.assertTrue(broken.stderr.startswith("skill-lint: "))


class LiveTreeTest(unittest.TestCase):
    def test_the_live_tree_lints_clean_against_its_debt_file(self):
        self.assertEqual(skill_lint.lint(skill_lint.working_tree(REPO_ROOT)), [])

    def test_every_live_debt_key_names_a_known_rule(self):
        raw = (REPO_ROOT / DEBT).read_bytes()
        for key in skill_lint.load_debt(raw):
            with self.subTest(key=key):
                self.assertIn(key.split(" ", 1)[0], {"L1", "L2", "L3", "L4a", "L4b", "L5"})
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py`
Expected: ERRORS. `AttributeError: module 'agent_tools.skill_lint' has no attribute 'violations'` (and `lint`, `load_debt`); `CommandTest` exits non-zero.

- [ ] **Step 3: Write the minimal implementation**

In `skill_lint.py`, add `TRIGGERS = ("Use when", "Use for", "Use to", "Use before", "Use after", "Invoke before")` and `XML = re.compile(r"<[A-Za-z/]")`. `violations(snapshot)` runs the following for each `SkillDir` from `skill_dirs`. The quoted texts are exact.

1. **No SKILL.md.** If `skill_md is None`, emit `L1 <path>/SKILL.md` "missing SKILL.md" and judge nothing else in that directory.
2. **Read it.** Decode `SKILL.md` as UTF-8. A decode error emits L1 "SKILL.md is not UTF-8" and skips the directory.
3. **Frontmatter.** Call `parse_frontmatter`. On `ValueError`, emit L1 with `str(error)`, then use the whole text as the body and skip the field checks in steps 4–5.
4. **L1 field checks, on `SKILL.md`.**
   - The name: "missing name"; `f"name {name!r} differs from its directory {dir!r}"`; "name is longer than 64 characters"; "name must match [a-z0-9-]+"; "name contains 'anthropic' or 'claude'"; "name contains XML".
   - The description: "missing description"; "description is empty"; "description is longer than 1024 characters"; "description contains XML".
5. **L5**, only for a non-empty description. "description opens with 'I ' or 'You '" applies when the description starts with either. "description has no trigger clause (Use when, Use for, Use to, Use before, Use after, Invoke before)" applies when it contains none of `TRIGGERS`.
6. **L2.** Emit `f"body is {n} reflowed lines, over 500"` when `n = reflowed_lines(body) > 500`.
7. **References.** For each reference `r`, decode its text with `errors="replace"`, then apply:
   - **L3** — `f"{n} reflowed lines and no ## Contents list before its first other ## heading"`. It applies when `reflowed_lines > 100` and `has_contents(text)` is false. `has_contents` skips the lines inside ```` ``` ```` fences, which toggle on any line whose `lstrip()` starts with ```` ``` ````. The first remaining line that starts with `"## "` must equal `"## Contents"`. The next non-blank line after it must start with `"- "` or `"1. "`. With no `## ` heading at all, `has_contents` is false.
   - **L4a** — "not named in its SKILL.md", when `not names(f"{name}/SKILL.md", skill_text, f"{name}/{basename(r)}")`.
   - **L4b** — for each other reference `o`: key `f"L4b {r} names {basename(o)}"`, text `f"names the sibling reference file {basename(o)}"`. It applies when `names(f"{name}/{basename(r)}", text, f"{name}/{basename(o)}")`. Payloads are never sources or targets.

Return `sorted(set(found))`.

`load_debt(raw)`:
- Use `json.loads(raw.decode("utf-8"), object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite_literal)`. Wrap any `ValueError` (including `UnicodeDecodeError`) as `ValueError(f"cannot load {DEBT_PATH}: {error}")`.
- Require a `dict` whose key set is exactly `{"debt"}`, holding a `list` of `str` that equals `sorted(set(debt))`. Otherwise raise `ValueError(f"{DEBT_PATH}: must be {{\"debt\": [sorted unique keys]}}")`.

`lint(snapshot)`:
- `raw = snapshot.read(DEBT_PATH)`. If it is `None`, raise `ValueError(f"{DEBT_PATH} is absent")`.
- Then build the lines as the Invariants state.

`main`:
- `argparse` with `prog="skill-lint"` and one required subcommand `check`, which takes `--root` (`type=Path`, default `Path(".")`).
- `lint(working_tree(args.root))`. Catch `ValueError`/`OSError` and print `f"skill-lint: {' '.join(str(error).split())}"` to stderr, returning 2.
- Print each line to stdout. Return `1 if lines else 0`.
- End the module with `if __name__ == "__main__": raise SystemExit(main())`.

Generate the live debt file from the live tree, once:

```bash
PYTHONPATH=python python3 - <<'EOF'
import json
from pathlib import Path
from agent_tools import skill_lint
keys = sorted({v.key for v in skill_lint.violations(skill_lint.working_tree(Path(".")))})
Path(skill_lint.DEBT_PATH).write_text(json.dumps({"debt": keys}, indent=2) + "\n", encoding="utf-8")
print(len(keys), sorted({k.split(" ", 1)[0] for k in keys}))
EOF
```

Expect about 37 keys across L2, L3, L4b and L5. A large L1 or L4a count is a classification bug, not debt. Stop and report it rather than committing it.

Add `"skill-lint"` to `commands` in `lib/agent-tools.nix`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_skill_lint.py`
Expected: PASS, every class green.

Run: `PYTHONPATH=python timeout 120 python3 -m agent_tools.skill_lint check; echo "exit=$?"`
Expected: no violation lines, `exit=0`.

Run: `timeout 3600 just build 2>&1 | tail -5`
Expected: build succeeds (the command table now holds `skill-lint`, and the import check covers `agent_tools.skill_lint`).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/skill_lint.py home/common/agent-skills/skill-lint-debt.json home/common/agent-skills/tests/test_skill_lint.py lib/agent-tools.nix
git commit -m "feat(agent-tools): add skill-lint with L1-L5 and a shrink-only debt file (#292)"
```
