# Task 3: Conditional, corpus and description ceilings

Per D3, D4, D16.

**Files:**
- Modify: `python/agent_tools/instruction_load.py`
- Modify: `home/common/agent-skills/instruction-load.json` (add the three new ceilings at their measured values)
- Modify: `home/common/agent-skills/tests/test_instruction_load.py` (extend `fixture_model()`, add module constants and one class)

**Interfaces:**
- Consumes (Task 1, `agent_tools.skill_lint`): `Snapshot`, `working_tree`, `skill_dirs`, `parse_frontmatter`, `AGENTS_DIR`.
- Produces (Task 4 relies on these exact names, all in `agent_tools.instruction_load`):
  - `TOP_LEVEL_KEYS = ("frame", "profiles", "excluded_sites", "corpus_ceiling_bytes", "description_ceiling_bytes")`.
  - `PROFILE_KEYS` with `"conditional_ceiling_bytes"` inserted right after `"ceiling_bytes"`.
  - `measure_corpus(snapshot: Snapshot) -> dict[str, int]`, returning exactly the keys `corpus` and `descriptions`.
  - `@dataclass(frozen=True) class Ceiling: label: str; location: tuple[str, ...]; ceiling: int; measured: int`.
  - `ceilings(model: dict, measurement: dict, corpus: dict[str, int]) -> list[Ceiling]`.
  - `breached(found: list[Ceiling]) -> list[Ceiling]`, the ceilings with `measured > ceiling`.

**Invariants:**
- `measure`, `over_ceiling`, `compare`, both renderers and the `report` CLI are unchanged (per D16). `over_ceiling` stays hot-only.
- `ceilings` order: for each profile in model order, for each host in `profile["hosts"]` order, the hot entry and then the conditional one; then `corpus`; then `descriptions`.
- Labels: `f"profile {id} on {host}: hot"`, `f"profile {id} on {host}: conditional"`, `"corpus"`, `"descriptions"`. Locations: `("profiles", id, "ceiling_bytes", host)`, `("profiles", id, "conditional_ceiling_bytes", host)`, `("corpus_ceiling_bytes",)`, `("description_ceiling_bytes",)`.
- The corpus is the bytes of each skill directory's `SKILL.md`, references and payloads. To that it adds every `.md` file directly in `home/common/claude-code/agents/` and the frame `home/common/agent-guidance/AGENTS.md` (per D3).
- `descriptions` is the sum of `len(value.encode("utf-8"))` of each `SKILL.md`'s frontmatter `description`. A `SKILL.md` whose frontmatter does not parse, or that has no description, adds 0.
- The live model file changes only by additions: every pre-existing key and value is unchanged.

- [ ] **Step 1: Write the failing test**

In `test_instruction_load.py`:

1. Add `from agent_tools import instruction_load, skill_lint` in place of the single import.
2. In `fixture_model()`, add `"conditional_ceiling_bytes": {"claude": 38, "codex": 26},` after the `demo` profile's `ceiling_bytes`. Add `"conditional_ceiling_bytes": {"claude": 0, "codex": 0},` after the `demo-reviewer` profile's `ceiling_bytes`. Add `"corpus_ceiling_bytes": 181, "description_ceiling_bytes": 24` after `excluded_sites`.
3. After `dict_reader`, add the constants and helper below. Then add the class right after `ModelCoreTest`:

```python
# HEAD_FILES plus a Codex skill with a description, and two files the corpus skips.
CORPUS_FILES = {
    **HEAD_FILES,
    "home/common/codex/skills/stub/SKILL.md":
        b"---\nname: stub\ndescription: Stubs. Use when testing.\n---\nstub body\n",
    "home/common/agent-skills/skills/demo/evals/evals.md": b"not counted\n",
    "home/common/claude-code/agents/notes.txt": b"not markdown\n",
}


def dict_snapshot(files):
    return skill_lint.Snapshot(
        read=files.get,
        list_files=lambda prefix: sorted(p for p in files if p.startswith(prefix + "/")),
    )


class CeilingTest(unittest.TestCase):
    def all_ceilings(self, model=None, files=CORPUS_FILES):
        model = model or fixture_model()
        snapshot = dict_snapshot(files)
        return instruction_load.ceilings(model, instruction_load.measure(model, snapshot.read),
                                         instruction_load.measure_corpus(snapshot))

    def test_the_corpus_counts_skill_markdown_agents_and_the_frame(self):
        # 51 + 17 + 9 (demo) + 12 (solo) + 67 (stub) + 14 (reviewer.md) + 11 (frame)
        self.assertEqual(instruction_load.measure_corpus(dict_snapshot(CORPUS_FILES)),
                         {"corpus": 181, "descriptions": 24})

    def test_every_ceiling_is_enumerated_with_its_location(self):
        rows = [(c.label, c.location, c.ceiling, c.measured) for c in self.all_ceilings()]
        hot, conditional = "ceiling_bytes", "conditional_ceiling_bytes"
        self.assertEqual(rows, [
            ("profile demo on claude: hot", ("profiles", "demo", hot, "claude"), 51, 51),
            ("profile demo on claude: conditional",
             ("profiles", "demo", conditional, "claude"), 38, 38),
            ("profile demo on codex: hot", ("profiles", "demo", hot, "codex"), 51, 51),
            ("profile demo on codex: conditional",
             ("profiles", "demo", conditional, "codex"), 26, 26),
            ("profile demo-reviewer on claude: hot",
             ("profiles", "demo-reviewer", hot, "claude"), 14, 14),
            ("profile demo-reviewer on claude: conditional",
             ("profiles", "demo-reviewer", conditional, "claude"), 0, 0),
            ("profile demo-reviewer on codex: hot",
             ("profiles", "demo-reviewer", hot, "codex"), 0, 0),
            ("profile demo-reviewer on codex: conditional",
             ("profiles", "demo-reviewer", conditional, "codex"), 0, 0),
            ("corpus", ("corpus_ceiling_bytes",), 181, 181),
            ("descriptions", ("description_ceiling_bytes",), 24, 24),
        ])

    def test_a_breach_of_each_new_ceiling_is_found_and_over_ceiling_stays_hot_only(self):
        files = dict(CORPUS_FILES)
        files["home/common/agent-skills/skills/demo/EXTRA.md"] += b"x"
        files["home/common/codex/skills/stub/SKILL.md"] = (
            b"---\nname: stub\ndescription: Stubs. Use when testing!!\n---\nstub body\n")
        found = instruction_load.breached(self.all_ceilings(files=files))
        self.assertEqual([c.label for c in found], [
            "profile demo on claude: conditional", "profile demo on codex: conditional",
            "corpus", "descriptions"])
        model = fixture_model()
        self.assertEqual(
            instruction_load.over_ceiling(model, instruction_load.measure(model, files.get)), [])

    def test_the_new_ceilings_are_required_and_typed(self):
        model = fixture_model()
        del model["profiles"][0]["conditional_ceiling_bytes"]
        model["profiles"][1]["conditional_ceiling_bytes"] = {"claude": -1, "codex": True}
        del model["corpus_ceiling_bytes"]
        model["description_ceiling_bytes"] = 1.5
        self.assertEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [
            "model: missing key 'corpus_ceiling_bytes'",
            "model: description_ceiling_bytes must be a non-negative integer",
            "profile demo: missing key 'conditional_ceiling_bytes'",
            "profile demo-reviewer: conditional_ceiling_bytes claude must be a non-negative integer",
            "profile demo-reviewer: conditional_ceiling_bytes codex must be a non-negative integer",
        ])

    def test_conditional_ceiling_hosts_must_match_the_profile_hosts(self):
        model = fixture_model()
        del model["profiles"][0]["conditional_ceiling_bytes"]["codex"]
        self.assertEqual(instruction_load.validate(model, dict_reader(HEAD_FILES)), [
            "profile demo: conditional_ceiling_bytes hosts ['claude'] differ from hosts "
            "['claude', 'codex']"])
```

4. In `LiveModelTest`, add:

```python
    def test_the_live_tree_breaches_no_ceiling_of_any_kind(self):
        snapshot = skill_lint.working_tree(REPO_ROOT)
        found = instruction_load.ceilings(self.model, instruction_load.measure(self.model, self.read),
                                          instruction_load.measure_corpus(snapshot))
        self.assertEqual([c.label for c in instruction_load.breached(found)], [])
```

- [ ] **Step 2: Run the test and watch it fail**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: FAIL/ERROR. `fixture_model()` now carries unknown keys, so `test_the_fixture_validates_clean` and the `report` CLI tests fail. `measure_corpus`, `ceilings` and `breached` do not exist yet.

- [ ] **Step 3: Write the minimal implementation**

In `instruction_load.py`:

1. Extend `TOP_LEVEL_KEYS` and `PROFILE_KEYS` as stated under Produces.
2. In `_top_level_violations`, after the `profiles must be a list` check, check each of `corpus_ceiling_bytes` and `description_ceiling_bytes` that is present. When it is a `bool`, a non-`int` or negative, append `f"model: {key} must be a non-negative integer"`.
3. In `_profile_violations`, extract the existing `ceiling_bytes` block into `_ceiling_map_violations(key, value, hosts, hosts_valid) -> list[str]`, keeping the same messages with `key` substituted. Call it for `ceiling_bytes` and then for `conditional_ceiling_bytes`. Existing messages stay byte-identical.
4. `measure_corpus(snapshot)` computes the corpus and description sums as the Invariants state. It reads skill directories with `skill_lint.skill_dirs(snapshot)`, and a `ValueError` from it propagates. The agent definitions are the paths in `snapshot.list_files(AGENTS_DIR)` that end in `.md` and sit directly in that directory. Any missing frame counts 0 bytes.
5. `Ceiling` and `ceilings(model, measurement, corpus)` follow the order, labels and locations stated under Invariants. `measured` is `measurement["profiles"][id][host][kind]["bytes"]`, or `corpus["corpus"]`/`corpus["descriptions"]`.
6. `breached(found)` returns `[c for c in found if c.measured > c.ceiling]`.

Then add the new ceilings to the live model at their measured values, preserving key order:

```bash
PYTHONPATH=python python3 - <<'EOF'
import json
from pathlib import Path
from agent_tools import instruction_load as il, skill_lint
snapshot = skill_lint.working_tree(Path("."))
path = Path(il.MODEL_PATH)
model = json.loads(path.read_text(encoding="utf-8"))
measurement = il.measure(model, snapshot.read)
corpus = il.measure_corpus(snapshot)
for index, profile in enumerate(model["profiles"]):
    rebuilt = {}
    for key, value in profile.items():
        rebuilt[key] = value
        if key == "ceiling_bytes":
            rebuilt["conditional_ceiling_bytes"] = {
                host: measurement["profiles"][profile["id"]][host]["conditional"]["bytes"]
                for host in value}
    model["profiles"][index] = rebuilt
model["corpus_ceiling_bytes"] = corpus["corpus"]
model["description_ceiling_bytes"] = corpus["descriptions"]
path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(corpus)
EOF
```

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python timeout 300 python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_skill_lint.py`
Expected: PASS, including `CeilingTest` (5 tests) and every pre-existing test.

Run:
```bash
git show HEAD:home/common/agent-skills/instruction-load.json > "$TMPDIR/il-before.json"
python3 - "$TMPDIR/il-before.json" <<'EOF'
import json, sys
before = json.load(open(sys.argv[1]))
after = json.load(open("home/common/agent-skills/instruction-load.json"))
for p in after["profiles"]:
    p.pop("conditional_ceiling_bytes")
after.pop("corpus_ceiling_bytes"); after.pop("description_ceiling_bytes")
sys.exit(0 if before == after else "pre-existing model content changed")
EOF
rm -f "$TMPDIR/il-before.json"
```
Expected: exit 0 (only additions). The script fails with `KeyError` if a new key is missing.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/instruction_load.py home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_instruction_load.py
git commit -m "feat(agent-tools): add conditional, corpus and description ceilings (#292)"
```
