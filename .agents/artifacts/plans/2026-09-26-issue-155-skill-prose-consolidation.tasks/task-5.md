# Task 5: Instruction-load model core — load, validate, measure, ceilings

**Files:**
- Create: `IL` (`python/agent_tools/instruction_load.py`)
- Modify: `python/agent_tools/agent_model_matrix.py`, `justfile`
- Test: `T/test_instruction_load.py` (create)

**Interfaces:**
- Consumes, from `agent_tools.agent_model_matrix`: `MATRIX_PATH`
  (`Path("home/common/agent-skills/model-matrix.json")`) and `AGENTS_PATH`
  (`Path("home/common/claude-code/agents")`). From `agent_tools.canonical`:
  `reject_duplicate_keys` and `reject_nonfinite_literal`.
- Produces in `agent_model_matrix` (D22):
  `parse_matrix(text: str, source: str) -> dict[str, Any]`. It is strict JSON
  with `object_pairs_hook=reject_duplicate_keys`. A parse failure raises
  `ValueError(f"cannot load {source}: {error}")`, and a non-object raises
  `ValueError(f"{source}: top level must be an object")`. `load_matrix` keeps
  its signature and messages: it reads the file (an `OSError` or `ValueError`
  becomes `ValueError(f"cannot load {path}: {error}")`) and returns
  `parse_matrix(text, str(path))`.
- Produces in `IL`. Tasks 6 and 7 rely on these exact names:
  - Constants: `MODEL_PATH = "home/common/agent-skills/instruction-load.json"`,
    `SHARED_TREE = "home/common/agent-skills/skills"`,
    `CLAUDE_TREE = "home/common/claude-code/skills"`,
    `AGENTS_DIR = AGENTS_PATH.as_posix()`,
    `FRAME_MEMBER = "agent-guidance/AGENTS.md"`,
    `FRAME_PATH = "home/common/agent-guidance/AGENTS.md"`,
    `HOSTS = ("claude", "codex")`.
  - `Reader = Callable[[str], Optional[bytes]]`: a repository-relative POSIX path
    maps to bytes, or to `None` when absent.
  - `tree_reader(root: Path) -> Reader`.
  - `load_model(data: bytes) -> dict`.
  - `resolve(member: str, read: Reader) -> list[tuple[str, str]]`: the
    `(tree, path)` pairs that exist, where tree is `"shared"`, `"claude-only"` or
    `"agents"`.
  - `validate(model: dict, read: Reader) -> list[str]`.
  - `measure(model: dict, read: Reader) -> dict`, for a valid model.
  - `over_ceiling(model: dict, measurement: dict) -> list[str]`.

**Invariants:**
- One seam: `validate` and `measure` read the model's documents and the matrix
  only through `read` (D17). Nothing in them touches the filesystem or git.
- `tree_reader(root)` returns `None` unless each path component is an exact entry
  of `os.listdir` of its parent and the final entry is a regular file. That makes
  it case-exact on a case-insensitive filesystem (D25).
- `load_model` decodes the bytes as UTF-8 and applies both canonical hooks. A
  failure raises `ValueError(f"cannot load {MODEL_PATH}: {error}")`, and a
  non-object raises `ValueError(f"{MODEL_PATH}: top level must be an object")`.
- Member spelling (spec §Member spelling). `<skill>/<file>` is exactly two
  non-empty `/`-separated parts, and its candidates are `(shared,
  f"{SHARED_TREE}/{member}")` and `(claude-only, f"{CLAUDE_TREE}/{member}")`. When
  the first part is `agents`, add `(agents, f"{AGENTS_DIR}/{file}")`. Any other
  spelling has no candidates. `resolve` keeps the candidates `read` finds.
- Host counting: tree `shared` counts on both hosts; `claude-only` and `agents`
  count on `claude` only. An absent member (tree `None`) is listed on every host
  with 0 bytes.
- The naming predicates are decisions (D11, D18, D23). Spell them exactly:
  ```python
  _BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_-])"
  _BOUNDARY_AFTER = r"(?![A-Za-z0-9_-])"
  _BASENAME_BEFORE = r"(?<![A-Za-z0-9_.-])(?<![A-Za-z0-9_-]/)"   # not inside "<skill>/<file>"
  _MD_TOKEN = re.compile(_BASENAME_BEFORE + r"([A-Za-z0-9_-]+\.md)" + _BOUNDARY_AFTER)
  _SUBAGENT_TYPE = re.compile(r'subagent_type="([^"]+)"')
  ```
  Document `source` (a member spelling) names `target` when any one of these
  holds:
  1. `target` appears framed by `_BOUNDARY_BEFORE` and `_BOUNDARY_AFTER`.
  2. The two share a skill and the target's file name appears framed by
     `_BASENAME_BEFORE` and `_BOUNDARY_AFTER`.
  3. The target file is `SKILL.md` and the text contains `` `<skill>` ``.
- The violation messages are exact strings, since Task 7 asserts them. They are
  returned in this order.
  1. Top level, in `("frame", "profiles", "excluded_sites")` order:
     `model: missing key '<k>'`, then `model: unknown key '<k>'` sorted. Then
     `model: frame must be 'agent-guidance/AGENTS.md'`, or
     `model: frame agent-guidance/AGENTS.md resolves to no document` when
     `read(FRAME_PATH)` is `None`. Then
     `model: excluded_sites must map site ids to reasons`,
     `excluded site <id>: empty reason`, and `model: profiles must be a list`.
  2. Each profile, in model order. The label is its `id` when that is a non-empty
     string, else `#<index>`. First `profile <label>: must be an object`. Then
     `missing key '<k>'` in the order `id, hosts, prompt, hot, conditional,
     unread, ceiling_bytes, note`, followed by `unknown key '<k>'` sorted. Every
     message from here on carries the `profile <label>: ` prefix:
     - `needs exactly one of 'entry' or 'launch'`
     - `entry must be a skill name` and `an entry has no prompt`
     - `launch must be a non-empty list of site ids` and `a launch needs a prompt`
     - `hosts must be a non-empty subset of ['claude', 'codex']`
     - `hot must be a list of members`, `conditional must be a list of members`
     - `unread must map members to reasons`, `unread <m> has an empty reason`
     - `<m> listed more than once`, across hot, conditional and unread
     - `ceiling_bytes must map hosts to byte counts`
     - `ceiling_bytes hosts [<sorted keys>] differ from hosts [<sorted hosts>]`,
       formatted with Python's `list` repr
     - `ceiling_bytes <host> must be a non-negative integer`, where a bool is
       not an integer
     - `empty note` for a missing, non-string or whitespace-only note
     - `duplicate id` for the second and every later profile with an id already
       seen

     A profile with any message from this step is not sound.
  3. The matrix, read through `read(MATRIX_PATH.as_posix())` and
     `parse_matrix`. The messages are `matrix: home/common/agent-skills/model-matrix.json is absent`,
     `matrix: <parse_matrix error>` and
     `matrix: dispatch_sites must be a list of objects with an id and a call`.
     Any of these skips completeness and the agent-definition check below.
  4. Completeness. For each matrix site in matrix order, count the profiles
     whose `launch` holds it plus 1 if it is in `excluded_sites`. A count of 0
     gives `matrix site <id> is in no profile`, and `n > 1` gives
     `matrix site <id> is claimed <n> times`. Then every claimed id not in the
     matrix gives `unknown matrix site <id>`, in first-claim order.
  5. Members, for each sound profile in model order. For the prompt, then hot,
     then conditional, then unread members, the resolution messages are
     `<m> resolves to no document` and `<m> resolves to <n> documents`. An
     unresolved member is skipped below. Reachability applies to each resolved
     hot or conditional member, except an entry profile's own
     `<entry>/SKILL.md`. An agent definition gives
     `<m> is not the subagent_type of any of its sites` unless its name without
     `.md` is a `_SUBAGENT_TYPE` match in one of the profile's sites' `call`. A
     skill document gives
     `<m> is named by neither its prompt nor another member` unless the resolved
     prompt, or another resolved hot or conditional skill document, names it.
     Closure applies to each resolved hot or conditional skill document: for each
     sorted, distinct `_MD_TOKEN` match `t`, if `read(<member's folder>/<t>)` is
     not `None` and `<skill>/<t>` is not listed as hot, conditional or unread,
     the message is `<m> names <skill>/<t>, which the profile does not list`.
     Unread members are neither naming sources nor closure subjects (D23).
- `measure` returns
  `{"frame": {"bytes", "words", "absent"}, "documents": {member: {"path", "tree",
  "bytes", "words", "absent"}}, "profiles": {id: {host: {"hot": {"members",
  "bytes", "words"}, "conditional": {...}}}}}`.
  - `documents` holds every hot or conditional member of any profile. Bytes are
    `len(raw)`, words are `len(raw.decode("utf-8").split())`, and an absent
    member is `{"path": None, "tree": None, "bytes": 0, "words": 0, "absent": True}`.
  - `members` keeps the profile's listing order, filtered by host counting.
  - A member resolving to two or more documents raises `ValueError`.
- `over_ceiling` checks each profile in model order and each host in its `hosts`
  order where hot bytes exceed the ceiling. It emits exactly
  `profile <id> on <host>: hot <b> bytes exceed ceiling <c> (<m> <bytes>, …)`,
  listing every counted hot member with its bytes.

- [ ] **Step 1: Write the failing test**

Create `T/test_instruction_load.py`:

```python
"""The instruction-load model: validation, measurement, ceilings and the report command."""

from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from agent_tools import instruction_load


REPO_ROOT = Path(__file__).parents[4]

# A two-profile model over a small tree, read through a dict reader. Byte and
# word counts in the assertions are hand-computed from these literals.
FIXTURE_MATRIX = {
    "roles": {},
    "dispatch_sites": [
        {"id": "demo-review",
         "call": 'Agent(subagent_type="reviewer", model="opus", effort="high") reviews the demo.'},
        {"id": "demo-plugin",
         "call": 'Agent(subagent_type="codex:rescue", model="sonnet", effort="medium") transports.'},
    ],
    "scenarios": {},
}
BASE_FILES = {
    "home/common/agent-skills/model-matrix.json": json.dumps(FIXTURE_MATRIX).encode(),
    "home/common/agent-skills/skills/demo/SKILL.md": b"one two three\nsee EXTRA.md and `solo`\n",
    "home/common/agent-skills/skills/demo/EXTRA.md": b"extra words here\n",
    "home/common/claude-code/skills/solo/SKILL.md": b"claude only\n",
    "home/common/claude-code/agents/reviewer.md": b"reviewer body\n",
    "home/common/agent-guidance/AGENTS.md": b"frame text\n",
}
HEAD_FILES = {
    **BASE_FILES,
    "home/common/agent-skills/skills/demo/SKILL.md":
        b"one two three four\nsee EXTRA.md, NEW.md and `solo`\n",
    "home/common/agent-skills/skills/demo/NEW.md": b"new file\n",
}


def fixture_model():
    return {
        "frame": "agent-guidance/AGENTS.md",
        "profiles": [
            {"id": "demo", "entry": "demo", "hosts": ["claude", "codex"], "prompt": None,
             "hot": ["demo/SKILL.md"],
             "conditional": ["demo/EXTRA.md", "demo/NEW.md", "solo/SKILL.md"],
             "unread": {}, "ceiling_bytes": {"claude": 51, "codex": 51},
             "note": "fixture entry"},
            {"id": "demo-reviewer", "launch": ["demo-review"], "hosts": ["claude", "codex"],
             "prompt": "demo/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [],
             "unread": {}, "ceiling_bytes": {"claude": 14, "codex": 0},
             "note": "fixture reviewer"},
        ],
        "excluded_sites": {"demo-plugin": "a plugin agent outside both trees"},
    }


def dict_reader(files):
    return lambda path: files.get(path)


class ModelCoreTest(unittest.TestCase):
    def setUp(self):
        self.model = fixture_model()
        self.files = dict(HEAD_FILES)

    def violations(self):
        return instruction_load.validate(self.model, dict_reader(self.files))

    def profile(self, profile_id):
        return next(p for p in self.model["profiles"] if p["id"] == profile_id)

    def test_the_fixture_validates_clean(self):
        self.assertEqual(self.violations(), [])

    def test_a_dropped_site_is_reported(self):
        del self.model["excluded_sites"]["demo-plugin"]
        self.assertEqual(self.violations(), ["matrix site demo-plugin is in no profile"])

    def test_a_site_claimed_twice_and_an_unknown_site_are_reported(self):
        self.model["excluded_sites"]["demo-review"] = "also excluded"
        self.model["excluded_sites"]["ghost-site"] = "not in the matrix"
        self.assertEqual(self.violations(), [
            "matrix site demo-review is claimed 2 times",
            "unknown matrix site ghost-site",
        ])

    def test_an_unknown_member_is_reported(self):
        self.profile("demo")["conditional"].append("demo/NOPE.md")
        self.assertEqual(self.violations(), ["profile demo: demo/NOPE.md resolves to no document"])

    def test_an_ambiguous_member_is_reported(self):
        self.files["home/common/claude-code/skills/demo/EXTRA.md"] = b"a second copy\n"
        self.assertEqual(self.violations(),
                         ["profile demo: demo/EXTRA.md resolves to 2 documents"])

    def test_an_unnamed_member_is_reported(self):
        self.files["home/common/agent-skills/skills/demo/LONE.md"] = b"nobody names me\n"
        self.profile("demo")["conditional"].append("demo/LONE.md")
        self.assertEqual(self.violations(), [
            "profile demo: demo/LONE.md is named by neither its prompt nor another member"])

    def test_an_agent_definition_needs_a_launch_site_of_its_type(self):
        self.profile("demo")["hot"].append("agents/reviewer.md")
        self.assertEqual(self.violations(), [
            "profile demo: agents/reviewer.md is not the subagent_type of any of its sites"])

    def test_a_named_sibling_left_unlisted_is_reported(self):
        self.profile("demo")["conditional"].remove("demo/EXTRA.md")
        self.assertEqual(self.violations(), [
            "profile demo: demo/SKILL.md names demo/EXTRA.md, which the profile does not list"])

    def test_an_unread_sibling_satisfies_closure_but_names_nothing(self):
        profile = self.profile("demo")
        profile["conditional"].remove("demo/EXTRA.md")
        profile["unread"]["demo/EXTRA.md"] = "read only on a branch this fixture never takes"
        self.assertEqual(self.violations(), [])

    def test_schema_violations_are_reported(self):
        demo = self.profile("demo")
        demo["extra"] = 1
        demo["note"] = " "
        del demo["ceiling_bytes"]["codex"]
        self.profile("demo-reviewer")["id"] = "demo"
        self.model["surplus"] = True
        self.assertEqual(self.violations(), [
            "model: unknown key 'surplus'",
            "profile demo: unknown key 'extra'",
            "profile demo: ceiling_bytes hosts ['claude'] differ from hosts ['claude', 'codex']",
            "profile demo: empty note",
            "profile demo: duplicate id",
        ])

    def test_a_member_listed_twice_is_reported(self):
        self.profile("demo")["unread"]["demo/EXTRA.md"] = "also unread"
        self.assertEqual(self.violations(), ["profile demo: demo/EXTRA.md listed more than once"])

    def test_entry_and_launch_are_exclusive_and_set_the_prompt_rule(self):
        self.profile("demo")["prompt"] = "demo/SKILL.md"
        self.profile("demo-reviewer")["prompt"] = None
        self.assertEqual(self.violations(), [
            "profile demo: an entry has no prompt",
            "profile demo-reviewer: a launch needs a prompt",
        ])

    def test_the_frame_must_resolve(self):
        del self.files["home/common/agent-guidance/AGENTS.md"]
        self.assertEqual(self.violations(),
                         ["model: frame agent-guidance/AGENTS.md resolves to no document"])

    def test_a_matrix_with_a_duplicate_key_is_reported(self):
        self.files["home/common/agent-skills/model-matrix.json"] = b'{"roles": {}, "roles": {}}'
        violations = self.violations()
        self.assertEqual(len(violations), 1)
        self.assertTrue(violations[0].startswith("matrix: cannot load "), violations)

    def test_load_model_is_strict(self):
        for raw in (b'{"frame": 1, "frame": 2}', b'{"profiles": NaN}', b"[]", b"\xff"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    instruction_load.load_model(raw)

    def test_measure_counts_bytes_and_words_per_host(self):
        measurement = instruction_load.measure(self.model, dict_reader(self.files))
        demo = measurement["profiles"]["demo"]
        self.assertEqual(demo["claude"]["hot"], {"members": ["demo/SKILL.md"], "bytes": 51, "words": 9})
        self.assertEqual(demo["codex"]["hot"], {"members": ["demo/SKILL.md"], "bytes": 51, "words": 9})
        self.assertEqual(demo["claude"]["conditional"]["bytes"], 38)
        self.assertEqual(demo["claude"]["conditional"]["words"], 7)
        self.assertEqual(demo["codex"]["conditional"],
                         {"members": ["demo/EXTRA.md", "demo/NEW.md"], "bytes": 26, "words": 5})
        reviewer = measurement["profiles"]["demo-reviewer"]
        self.assertEqual(reviewer["claude"]["hot"],
                         {"members": ["agents/reviewer.md"], "bytes": 14, "words": 2})
        self.assertEqual(reviewer["codex"]["hot"], {"members": [], "bytes": 0, "words": 0})
        self.assertEqual(measurement["frame"], {"bytes": 11, "words": 2, "absent": False})

    def test_an_absent_member_measures_zero_and_is_marked(self):
        measurement = instruction_load.measure(self.model, dict_reader(BASE_FILES))
        self.assertEqual(measurement["documents"]["demo/NEW.md"],
                         {"path": None, "tree": None, "bytes": 0, "words": 0, "absent": True})

    def test_ceilings_hold_at_the_measured_values_and_break_one_byte_past(self):
        read = dict_reader(self.files)
        self.assertEqual(
            instruction_load.over_ceiling(self.model, instruction_load.measure(self.model, read)), [])
        self.files["home/common/agent-skills/skills/demo/SKILL.md"] += b" "
        grown = instruction_load.measure(self.model, dict_reader(self.files))
        self.assertEqual(instruction_load.over_ceiling(self.model, grown), [
            "profile demo on claude: hot 52 bytes exceed ceiling 51 (demo/SKILL.md 52)",
            "profile demo on codex: hot 52 bytes exceed ceiling 51 (demo/SKILL.md 52)",
        ])

    def test_the_tree_reader_matches_names_exactly(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "skills/demo").mkdir(parents=True)
            (root / "skills/demo/SKILL.md").write_bytes(b"body\n")
            read = instruction_load.tree_reader(root)
            self.assertEqual(read("skills/demo/SKILL.md"), b"body\n")
            self.assertIsNone(read("skills/demo/skill.md"))
            self.assertIsNone(read("skills/Demo/SKILL.md"))
            self.assertIsNone(read("skills/demo"))
            self.assertIsNone(read("skills/demo/ABSENT.md"))


if __name__ == "__main__":
    unittest.main()
```

Register the suite. In `justfile`'s `agent-workflow-tests` list, add
`home/common/agent-skills/tests/test_instruction_load.py \` directly after the
`home/common/agent-skills/tests/test_agent_model_matrix.py \` line.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: ERROR at import, with
`ModuleNotFoundError: No module named 'agent_tools.instruction_load'`.

- [ ] **Step 3: Implement**

1. In `agent_model_matrix.py`, extract `parse_matrix` exactly as described under
   Interfaces, and make `load_matrix` delegate to it.
2. Create `IL` with the module docstring `"""Measure the instruction documents
   each agent profile loads, per host."""`. It gets the constants, `Reader`,
   the regexes above, and the seven functions under the Invariants. Keep
   `validate` a thin orchestration over private helpers: top level,
   per-profile structure, matrix sites, completeness, and member checks.
   `resolve` and the naming predicate are the only places that interpret a
   member spelling.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py home/common/agent-skills/tests/test_agent_model_matrix.py`
Expected: OK, with 19 tests in `ModelCoreTest` and the matrix suite unchanged.

Run: `just agent-model-matrix`
Expected: `agent model matrix: valid` followed by the representative trace.

Run: `git grep -n -e "sys.path" -e "importlib" -e "__file__" -- python/agent_tools/instruction_load.py`
Expected: no output and exit 1 (agent-helpers rule 3).

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/instruction_load.py python/agent_tools/agent_model_matrix.py home/common/agent-skills/tests/test_instruction_load.py justfile
git commit -m "feat(agent-tools): validate and measure the instruction-load model (#155)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Decision IDs: D7, D11, D14, D16, D17, D18, D22, D23, D25.
