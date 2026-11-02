# Task 4: `check` and `tighten`, and `just agent-instruction-budget`

Per D1, D7, D8, D9, D16, D18, D19, D20. Measures issue #292 AC2 and AC3.

**Files:**
- Modify: `python/agent_tools/instruction_load.py`
- Modify: `home/common/agent-skills/tests/test_instruction_load.py` (add constants and the classes `CheckTest`, `CheckCommandTest` and `LiveBudgetTest` before `if __name__ == "__main__":`)
- Modify: `justfile` (add the `agent-instruction-budget` recipe directly after `agent-instruction-load`)

**Interfaces:**
- Consumes:
  - From Task 1/2 (`agent_tools.skill_lint`): `Snapshot`, `working_tree`, `tree_lister`, `lint`, `load_debt`, `DEBT_PATH`.
  - From Task 3 (`agent_tools.instruction_load`): `measure_corpus`, `ceiling_locations`, `Ceiling`, `ceilings`, `breached`, the extended `validate`.
  - From the test module: `dict_snapshot(files)`, `git_env()`.
- Produces, in `agent_tools.instruction_load`:
  - `WORKFLOW_PATH = ".github/workflows/instruction-budget.yaml"` and `RAISE_LABEL = "instruction-budget-raise"`.
  - `GATE_FILES = (WORKFLOW_PATH, "python/agent_tools/skill_lint.py", "python/agent_tools/instruction_load.py", ".github/branch-protection.json")`. It excludes the debt file (per D19).
  - `revision_snapshot(root: Path, revision: str) -> tuple[str, Snapshot]`. `revision_reader` becomes `sha, snapshot = revision_snapshot(root, revision); return sha, snapshot.read`.
  - `loose(found: list[Ceiling]) -> list[Ceiling]`: the ceilings with `100 * ceiling > 105 * measured` (per D7).
  - `lowered_to(model: dict, base: dict) -> dict` (per D8).
  - `tightened(model: dict, found: list[Ceiling]) -> tuple[dict, list[str]]`.
  - `run_check(head: Snapshot, base: Optional[Snapshot], raise_label: bool) -> list[str]`. It raises `ValueError` when it cannot run.
  - The CLI subcommands `check [--base REV] [--raise-label] [--root PATH]` and `tighten [--root PATH]`.
  - The recipe `just agent-instruction-budget *args`.

**Invariants:**
- `run_check` reports every failing step. Each line starts with `lint: `, `ceiling: `, `tightness: `, `raise: ` or `debt: `, in that step order. The exact texts are below.
- Step 4 (raise control and debt shrink) runs only when `base is not None` and `base.read(WORKFLOW_PATH) is not None` (per D1).
- The label waives only the `raise:` lines. It never waives `debt:` lines (per D19).
- `tighten` never raises a ceiling. Every value it writes is ≤ the value it replaced. It rewrites the model only when something changed, as `json.dumps(model, indent=2, ensure_ascii=False) + "\n"`.
- Exit codes. `check` exits 0 on no lines (stdout `check: pass`), 1 with lines (one per stdout line), and 2 when it cannot run (one stderr line prefixed `agent-instruction-load: `, empty stdout). `tighten` exits 0, or 1 when a breach remains, or 2 when it cannot run (per D18).
- `report` is unchanged, including through `revision_reader`'s delegation.

Exact `run_check` line texts (`L` = `RAISE_LABEL`, `c` a `Ceiling`):
- `f"lint: {line}"` for each `skill_lint.lint(head)` line.
- `f"ceiling: invalid model: {violation}"` for each `validate` violation. Measurement and tightness are then skipped (per D18).
- `f"ceiling: {c.label} measures {c.measured} bytes, above its ceiling {c.ceiling}; cut the text, or raise the ceiling in a PR carrying the {L} label"`.
- ``f"tightness: {c.label} ceiling {c.ceiling} is more than 5% above its measured {c.measured} bytes; run `just agent-instruction-load tighten`"``.
- `f"raise: {MODEL_PATH} changes more than lowering a ceiling; revert it, or have a human apply the {L} label"`.
- `f"raise: gate file {path} differs from the base; revert it, or have a human apply the {L} label"`, in `GATE_FILES` order.
- `f"debt: {key} is not in the base's {DEBT_PATH}; the debt file may only shrink, so fix the violation instead"`, in sorted key order.

- [ ] **Step 1: Write the failing test**

Append to `test_instruction_load.py`, before `if __name__ == "__main__":`:

```python
DEBT = "home/common/agent-skills/skill-lint-debt.json"
WORKFLOW = ".github/workflows/instruction-budget.yaml"
DEMO = "home/common/agent-skills/skills/demo/SKILL.md"
LOOSE = "home/common/agent-skills/skills/demo/LOOSE.md"
GATE_SITE = {"id": "demo-plugin", "path": DEMO,
             "call": 'Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") '
                     'transports.'}
# A lint-clean three-tree repository carrying the gate workflow; GATE_MODEL's
# ceilings are hand-counted: demo 75, solo 74, stub 74, frame 11; descriptions 31 each.
GATE_TREE = {
    "home/common/agent-skills/model-matrix.json": json.dumps(
        {"roles": {}, "dispatch_sites": [GATE_SITE], "scenarios": {}}).encode(),
    DEMO: b"---\nname: demo\ndescription: Demos things. Use when testing.\n---\nsee `solo`\n",
    "home/common/claude-code/skills/solo/SKILL.md":
        b"---\nname: solo\ndescription: Solos things. Use when testing.\n---\nsolo body\n",
    "home/common/codex/skills/stub/SKILL.md":
        b"---\nname: stub\ndescription: Stubs things. Use when testing.\n---\nstub body\n",
    "home/common/agent-guidance/AGENTS.md": b"frame text\n",
    DEBT: b'{"debt": []}\n',
    WORKFLOW: b"name: Instruction Budget\n",
}
TIGHTEN = "run `just agent-instruction-load tighten`"
WAIVER = "revert it, or have a human apply the instruction-budget-raise label"


def gate_model():
    return {
        "frame": "agent-guidance/AGENTS.md",
        "profiles": [{"id": "demo", "entry": "demo", "hosts": ["claude", "codex"],
                      "prompt": None, "hot": ["demo/SKILL.md"], "conditional": ["solo/SKILL.md"],
                      "unread": {}, "ceiling_bytes": {"claude": 75, "codex": 75},
                      "conditional_ceiling_bytes": {"claude": 74, "codex": 0},
                      "note": "gate fixture"}],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
        "corpus_ceiling_bytes": 234,
        "description_ceiling_bytes": 93,
    }


def gate_files(model=None, extra=None, drop=()):
    files = {**GATE_TREE,
             instruction_load.MODEL_PATH: json.dumps(model or gate_model(), indent=2).encode()}
    files.update(extra or {})
    for path in drop:
        files.pop(path)
    return files


def debt_line(key):
    return (f"debt: {key} is not in the base's {DEBT}; the debt file may only shrink, "
            f"so fix the violation instead")


class CheckTest(unittest.TestCase):
    def check(self, head, base=None, label=False):
        return instruction_load.run_check(
            dict_snapshot(head), None if base is None else dict_snapshot(base), label)

    def found(self, files, model):
        snapshot = dict_snapshot(files)
        return instruction_load.ceilings(model, instruction_load.measure(model, snapshot.read),
                                         instruction_load.measure_corpus(snapshot))

    def test_the_tight_unchanged_tree_passes(self):
        self.assertEqual(self.check(gate_files(), gate_files()), [])
        self.assertEqual(self.check(gate_files()), [])

    def test_each_raise_fails_unlabelled_and_passes_labelled(self):
        def mutated(change):
            model = gate_model()
            change(model)
            return gate_files(model)

        def move_to_conditional(m):
            profile = m["profiles"][0]
            profile["hot"], profile["conditional"] = [], ["demo/SKILL.md", "solo/SKILL.md"]
            profile["ceiling_bytes"] = {"claude": 0, "codex": 0}
            profile["conditional_ceiling_bytes"] = {"claude": 149, "codex": 75}

        def new_profile(m):
            m["profiles"].append({
                "id": "solo", "entry": "solo", "hosts": ["claude"], "prompt": None,
                "hot": ["solo/SKILL.md"], "conditional": [], "unread": {},
                "ceiling_bytes": {"claude": 74}, "conditional_ceiling_bytes": {"claude": 0},
                "note": "a second profile"})

        model_line = (f"raise: {instruction_load.MODEL_PATH} changes more than lowering a "
                      f"ceiling; {WAIVER}")
        cases = (
            ("raised hot ceiling",
             mutated(lambda m: m["profiles"][0]["ceiling_bytes"].update(claude=76)), model_line),
            ("raised conditional ceiling",
             mutated(lambda m: m["profiles"][0]["conditional_ceiling_bytes"].update(claude=75)),
             model_line),
            ("raised corpus ceiling",
             mutated(lambda m: m.update(corpus_ceiling_bytes=235)), model_line),
            ("raised description ceiling",
             mutated(lambda m: m.update(description_ceiling_bytes=94)), model_line),
            ("hot member moved to conditional", mutated(move_to_conditional), model_line),
            ("new profile", mutated(new_profile), model_line),
            ("excluded_sites edit",
             mutated(lambda m: m["excluded_sites"].update({"demo-plugin": "reworded"})),
             model_line),
            ("gate file edited",
             gate_files(extra={WORKFLOW: b"name: Instruction Budget\n# edited\n"}),
             f"raise: gate file {WORKFLOW} differs from the base; {WAIVER}"),
            ("gate file added",
             gate_files(extra={"python/agent_tools/skill_lint.py": b"# new\n"}),
             f"raise: gate file python/agent_tools/skill_lint.py differs from the base; {WAIVER}"),
        )
        for label, head, expected in cases:
            with self.subTest(case=label):
                self.assertEqual(self.check(head, gate_files()), [expected])
                self.assertEqual(self.check(head, gate_files(), label=True), [])

    def test_a_grown_debt_file_fails_with_and_without_the_label(self):
        key = f"L4a {LOOSE}"
        head = gate_files(extra={LOOSE: b"", DEBT: json.dumps({"debt": [key]}).encode()})
        self.assertEqual(self.check(head, gate_files()), [debt_line(key)])
        self.assertEqual(self.check(head, gate_files(), label=True), [debt_line(key)])

    def test_paying_debt_passes_unlabelled(self):
        key = f"L4a {LOOSE}"
        base = gate_files(extra={LOOSE: b"", DEBT: json.dumps({"debt": [key]}).encode()})
        self.assertEqual(self.check(gate_files(), base), [])

    def test_a_lowering_only_change_passes_unlabelled(self):
        base_model = gate_model()
        base_model["profiles"][0]["ceiling_bytes"]["claude"] = 78
        base_model["corpus_ceiling_bytes"] = 240
        self.assertEqual(self.check(gate_files(), gate_files(base_model)), [])

    def test_a_base_without_the_gate_workflow_skips_raise_control(self):
        raised = gate_model()
        raised["profiles"][0]["ceiling_bytes"]["claude"] = 76
        head = gate_files(raised, extra={LOOSE: b"",
                                         DEBT: json.dumps({"debt": [f"L4a {LOOSE}"]}).encode()})
        self.assertEqual(self.check(head, gate_files(drop=(WORKFLOW,))), [])

    def test_a_loose_ceiling_fails_and_tighten_fixes_it_without_raising(self):
        within = gate_model()
        within["profiles"][0]["ceiling_bytes"]["claude"] = 78        # 7800 <= 105 * 75
        self.assertEqual(self.check(gate_files(within)), [])
        model = gate_model()
        model["profiles"][0]["ceiling_bytes"]["claude"] = 79         # 7900 > 105 * 75
        model["corpus_ceiling_bytes"] = 250
        self.assertEqual(self.check(gate_files(model)), [
            "tightness: profile demo on claude: hot ceiling 79 is more than 5% above its "
            f"measured 75 bytes; {TIGHTEN}",
            f"tightness: corpus ceiling 250 is more than 5% above its measured 234 bytes; {TIGHTEN}",
        ])
        tight, lowered = instruction_load.tightened(model, self.found(gate_files(model), model))
        self.assertEqual(tight, gate_model())
        self.assertEqual(lowered, ["lowered profile demo on claude: hot: 79 -> 75",
                                   "lowered corpus: 250 -> 234"])
        self.assertEqual(self.check(gate_files(tight)), [])

    def test_a_breach_survives_tighten(self):
        head = gate_files(extra={DEMO: GATE_TREE[DEMO] + b" "})
        expected = [
            "ceiling: profile demo on claude: hot measures 76 bytes, above its ceiling 75",
            "ceiling: profile demo on codex: hot measures 76 bytes, above its ceiling 75",
            "ceiling: corpus measures 235 bytes, above its ceiling 234",
        ]
        self.assertEqual([line.split(";")[0] for line in self.check(head)], expected)
        self.assertEqual(instruction_load.tightened(gate_model(), self.found(head, gate_model())),
                         (gate_model(), []))

    def test_lint_and_invalid_model_lines_carry_their_steps(self):
        self.assertEqual(self.check(gate_files(extra={LOOSE: b""})),
                         [f"lint: L4a {LOOSE}: not named in its SKILL.md"])
        broken = gate_model()
        del broken["excluded_sites"]["demo-plugin"]
        self.assertEqual(self.check(gate_files(broken)),
                         ["ceiling: invalid model: matrix site demo-plugin is in no profile"])

    def test_what_cannot_be_checked_raises(self):
        for head, base in ((gate_files(drop=(instruction_load.MODEL_PATH,)), None),
                           (gate_files(extra={instruction_load.MODEL_PATH: b"{"}), None),
                           (gate_files(), gate_files(drop=(instruction_load.MODEL_PATH,))),
                           (gate_files(), gate_files(extra={instruction_load.MODEL_PATH: b"{"})),
                           (gate_files(extra={DEBT: b"{"}), None)):
            with self.subTest(head=sorted(head)[:1], base=base is not None):
                with self.assertRaises(ValueError):
                    self.check(head, base)


class CheckCommandTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        self.env = git_env()
        for args in (("init", "-q", "-b", "main"), ("config", "commit.gpgsign", "false")):
            subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True)
        self.write(gate_files())
        for args in (("add", "-A"), ("commit", "-q", "-m", "base")):
            subprocess.run(["git", "-C", str(self.repo), *args], env=self.env, check=True)

    def write(self, files):
        for relative, data in files.items():
            path = self.repo / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)

    def run_tool(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.instruction_load", *args, "--root", str(self.repo)],
            env=self.env, capture_output=True, text=True, check=False)

    def test_check_exit_codes_and_the_label_flag(self):
        clean = self.run_tool("check", "--base", "HEAD")
        self.assertEqual((clean.returncode, clean.stdout), (0, "check: pass\n"), clean.stderr)
        raised = gate_model()
        raised["profiles"][0]["ceiling_bytes"]["claude"] = 76
        self.write({instruction_load.MODEL_PATH: json.dumps(raised, indent=2).encode()})
        unlabelled = self.run_tool("check", "--base", "HEAD")
        self.assertEqual(unlabelled.returncode, 1)
        self.assertTrue(unlabelled.stdout.startswith("raise: "), unlabelled.stdout)
        self.assertEqual(self.run_tool("check", "--base", "HEAD", "--raise-label").returncode, 0)
        for args in (("check", "--base", "no-such-revision"), ("check", "--raise-label")):
            with self.subTest(args=args):
                refused = self.run_tool(*args)
                self.assertEqual((refused.returncode, refused.stdout), (2, ""))
                self.assertEqual(len(refused.stderr.splitlines()), 1, refused.stderr)
                self.assertTrue(refused.stderr.startswith("agent-instruction-load: "))

    def test_tighten_lowers_in_canonical_form_and_fails_on_a_breach(self):
        model = gate_model()
        model["profiles"][0]["ceiling_bytes"]["claude"] = 79
        self.write({instruction_load.MODEL_PATH: json.dumps(model, indent=2).encode()})
        tightened = self.run_tool("tighten")
        self.assertEqual((tightened.returncode, tightened.stdout),
                         (0, "lowered profile demo on claude: hot: 79 -> 75\n"), tightened.stderr)
        self.assertEqual((self.repo / instruction_load.MODEL_PATH).read_text(encoding="utf-8"),
                         json.dumps(gate_model(), indent=2, ensure_ascii=False) + "\n")
        self.assertEqual(self.run_tool("check", "--base", "HEAD").returncode, 0)
        self.write({DEMO: GATE_TREE[DEMO] + b" "})
        breached = self.run_tool("tighten")
        self.assertEqual(breached.returncode, 1)
        self.assertIn("breach profile demo on claude: hot: measures 76 bytes, above its "
                      "ceiling 75", breached.stdout)


class LiveBudgetTest(unittest.TestCase):
    def test_the_live_tree_passes_steps_one_to_three(self):
        self.assertEqual(
            instruction_load.run_check(skill_lint.working_tree(REPO_ROOT), None, False), [])
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: ERRORS. `run_check` and `tightened` do not exist; the CLI rejects `check`/`tighten` with exit 2.

- [ ] **Step 3: Write the minimal implementation**

`revision_snapshot(root, revision)` is the body of today's `revision_reader`. It also returns a lister over the same `present` set: `lambda prefix: sorted(p for p in present if p.startswith(prefix + "/"))`. Then `revision_reader` delegates to it.

`lowered_to(model, base)` embodies D8 and walks Task 3's `ceiling_locations`, so it can never disagree with `ceilings` about which ceilings exist (D16, D20). Implement it exactly so:

```python
def _is_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _slot(model: dict, location: tuple[str, ...]) -> Optional[dict]:
    """The dict holding `location`'s last key, or None when it does not resolve.

    A profile is matched by id, and only when `model` holds exactly one profile with it.
    """
    if len(location) == 1:
        return model
    _, profile_id, kind, _ = location
    profiles = model.get("profiles") if isinstance(model.get("profiles"), list) else []
    matches = [p for p in profiles if isinstance(p, dict) and p.get("id") == profile_id]
    if len(matches) != 1 or not isinstance(matches[0].get(kind), dict):
        return None
    return matches[0][kind]


def lowered_to(model: dict, base: dict) -> dict:
    """`model` with each ceiling that is at or below its base value set to that value.

    Raise control compares the result with `base`: anything still unequal is a change
    other than lowering a ceiling. Non-dict and non-list values are skipped, never lowered.
    """
    result = copy.deepcopy(model)
    for location in ceiling_locations(result):
        target, source, key = _slot(result, location), _slot(base, location), location[-1]
        if target is not None and source is not None and _is_count(target.get(key)) \
                and _is_count(source.get(key)) and target[key] <= source[key]:
            target[key] = source[key]
    return result
```

`tightened(model, found)`:
- Deep-copy `model`.
- For each `c` in `found` with `c.ceiling > c.measured`, set `_slot(copy, c.location)[c.location[-1]]` to `c.measured` and append `f"lowered {c.label}: {c.ceiling} -> {c.measured}"`.
- Return `(copy, lines)`.

`run_check(head, base, raise_label)`:
1. `lines = [f"lint: {line}" for line in skill_lint.lint(head)]`.
2. Read `head.read(MODEL_PATH)`. If it is `None`, raise `ValueError(f"no {MODEL_PATH} in the working tree")`. Then `model = load_model(raw)`. Collect `violations = validate(model, head.read)`.
   - If there are violations, append the `ceiling: invalid model:` lines.
   - Otherwise build `found = ceilings(model, measure(model, head.read), measure_corpus(head))`. Append one breach line per `breached(found)`, then one tightness line per `loose(found)`.
3. Step 4 runs when `base` is not `None` and `base.read(WORKFLOW_PATH)` is not `None`:
   - Read the base model. When it is absent, raise `ValueError(f"no {MODEL_PATH} at the base")`. Load it with `load_model`, so a malformed one raises.
   - Unless `raise_label` is set: append the model `raise:` line when `lowered_to(model, base_model) != base_model`. Append one gate `raise:` line per path in `GATE_FILES` whose `head.read(path) != base.read(path)`.
   - Debt: `head_keys = set(load_debt(head.read(DEBT_PATH)))`. `base_keys` is the empty set when the base has no debt file, else `set(load_debt(...))`. Append a `debt:` line for each key in `sorted(head_keys - base_keys)`.
4. Return `lines`.

CLI:
- Add the `check` parser (`--base`, `--raise-label` as `store_true`, `--root` defaulting to `Path(".")`) and the `tighten` parser (`--root`). Split `main` into `_report(args)`, `_check(args)` and `_tighten(args)` under the existing `try`/`except (ValueError, OSError)`, which keeps the one-line stderr and exit 2.
- `_check`:
  - `--raise-label` without `--base` raises `ValueError("--raise-label needs --base")`.
  - `head = skill_lint.working_tree(args.root)`. `base = revision_snapshot(args.root, args.base)[1]` when `--base` is given.
  - When `base` lacks `WORKFLOW_PATH`, print `agent-instruction-load: the base has no {WORKFLOW_PATH}; raise control and debt shrink skipped` to stderr.
  - Print the lines, or `check: pass`. Return `1 if lines else 0`.
- `_tighten`:
  - Load the working-tree model and validate it. Any violation raises `ValueError("invalid model: " + "; ".join(violations))`.
  - Compute `found`, then `tightened`. Write the model only if it changed, and print the `lowered` lines.
  - Then print `f"breach {c.label}: measures {c.measured} bytes, above its ceiling {c.ceiling}"` for each `breached(found)`. Return 1 if any was printed, else 0.

`justfile`, after the `agent-instruction-load` recipe:

```just
# Run the Instruction Budget gate against origin/main; pass --raise-label for a labelled raise (#292 D9).
agent-instruction-budget *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.instruction_load check --base origin/main {{args}}
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py`
Expected: PASS. `CheckTest` has 10 tests, `CheckCommandTest` 2 and `LiveBudgetTest` 1, and every earlier test still passes.

Run: `timeout 120 just agent-instruction-budget; echo "exit=$?"`
Expected: `exit=0`, with the stderr note that the base has no gate workflow (D1). `origin/main` does not carry the workflow yet.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/instruction_load.py home/common/agent-skills/tests/test_instruction_load.py justfile
git commit -m "feat(agent-tools): add instruction_load check and tighten (#292)"
```
