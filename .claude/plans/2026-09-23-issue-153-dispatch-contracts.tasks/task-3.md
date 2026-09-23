# Task 3: Installed-tree class and recipe

Decisions: D7, D8, D10, D16 (and D12 for the final provenance gate). Work from
the worktree root; paths are repo-relative. New work — no `Recovered-From`
trailer.

**Files:**
- Modify: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Modify: `justfile` (new `agent-installed-skill-tests` recipe)
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py`

**Interfaces:**
- Consumes (Tasks 1–2, in `test_dispatch_contracts.py`): `CARRIERS` (nine
  entries; `carrier.tree` is `"shared"` or `"claude-only"`,
  `carrier.relative` is `"<skill>/<file>"`), `missing_contracts(carrier,
  document_text) -> frozenset[str]`, the `# Region breakages per carrier kind`
  comment line that precedes `REGION_BREAKERS`.
- Produces: `INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"`,
  `INSTALLED_RECIPE = "just agent-installed-skill-tests"`, `INSTALLED_VIEWS`,
  `InstalledTreeContractsTest`, and the `just agent-installed-skill-tests` recipe.

**Invariants:**
- Variable absent → the class is skipped with a reason naming the recipe (D8).
- Variable present → never a skip and never a source-tree fallback: a root that
  is not an absolute directory (D16), a missing view directory, or a missing
  carrier file is a failure (D8).
- Claude view `<root>/.claude/skills` checks all nine carriers; Codex view
  `<root>/.agents/skills` checks the eight `shared` carriers only (D7).
- The recipe refuses unless exactly one `-home-manager-files` requisite of
  `./result` exists, exactly like `show-claude-settings` (D7).

- [ ] **Step 1: Add the installed class**

In `test_dispatch_contracts.py`, add `import os` directly after
`from dataclasses import dataclass`. Directly after the `SOURCE_TREES = …` line
add:

```python

# Any directory laid out like the home home-manager populates: the built
# home-manager-files output, or $HOME after a switch.
INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
# (view, skill directory under the installed home, source trees it publishes)
INSTALLED_VIEWS = (
    ("claude", ".claude/skills", frozenset({"shared", "claude-only"})),
    ("codex", ".agents/skills", frozenset({"shared"})),
)
```

Directly before the `# Region breakages per carrier kind, …` comment add:

```python
class InstalledTreeContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the skill trees the Nix build installs"
            )
        cls.root = Path(root)

    def assert_contract_installed(self, contract_id):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        for view, skills_dir, trees in INSTALLED_VIEWS:
            base = self.root / skills_dir
            if not base.is_dir():
                with self.subTest(view=view):
                    self.fail(f"the {view} view is missing: {base}")
                continue
            for carrier in CARRIERS:
                if carrier.tree not in trees:
                    continue
                path = base / carrier.relative
                with self.subTest(view=view, carrier=carrier.relative):
                    self.assertTrue(path.is_file(), f"the {view} view lacks {path}")
                    self.assertNotIn(
                        contract_id,
                        missing_contracts(carrier, path.read_text(encoding="utf-8")),
                        f"{path}: the {contract_id} clause must occur exactly "
                        "once in the rendered region",
                    )

    def test_launch_by_type(self):
        self.assert_contract_installed("launch-by-type")

    def test_read_before_write(self):
        self.assert_contract_installed("read-before-write")


```

- [ ] **Step 2: Watch it skip and fail truthfully**

`T=home/common/agent-skills/tests/test_dispatch_contracts.py`

1. Run: `env -u AGENT_SKILLS_INSTALLED_HOME python3 -m unittest -v $T 2>&1 | grep -c 'skipped .*just agent-installed-skill-tests'`
   — prints `1`; the run ends `OK (skipped=1)`.
2. Run: `d=$(mktemp -d); AGENT_SKILLS_INSTALLED_HOME="$d" python3 -m unittest $T 2>&1 | tail -1; rmdir "$d"`
   — `FAILED (failures=4)` (both views missing, both methods; not a skip).
3. Run: `AGENT_SKILLS_INSTALLED_HOME= python3 -m unittest $T 2>&1 | tail -1` —
   `FAILED (failures=2)` (D16).
4. Run against the activated generation, which predates these clauses:
   `hmf=$(nix-store --query --requisites /run/current-system | grep -- '-home-manager-files$'); AGENT_SKILLS_INSTALLED_HOME="$hmf" python3 -m unittest -k InstalledTree $T 2>&1 | tail -1`
   — `FAILED (failures=34)` (9 Claude-view + 8 Codex-view carriers × 2). If
   the host was already switched to a generation carrying the clauses this
   reads `OK`; items 2 and 3 remain the falsifiable gate.

- [ ] **Step 3: Add the recipe**

In `justfile`, insert directly before the `## claude code` line (after the
`agent-model-matrix` recipe and its trailing blank line), keeping one blank line
after it:

```just
# Check the dispatch contracts against the skill trees the Nix build installs.
agent-installed-skill-tests: build
  @set -- $(nix-store --query --requisites ./result \
    | grep -- '-home-manager-files$' || true); \
    if [ "$#" -ne 1 ]; then \
      echo "expected exactly one built home-manager-files output; found $#" >&2; \
      exit 1; \
    fi; \
    AGENT_SKILLS_INSTALLED_HOME="$1" python3 -m unittest -v \
      home/common/agent-skills/tests/test_dispatch_contracts.py
```

- [ ] **Step 4: Verify**

Run: `log=$(mktemp); just agent-installed-skill-tests >"$log" 2>&1; echo "exit=$?"; tail -3 "$log"; grep -c skipped "$log"; rm "$log"`
Expected: `exit=0`, `Ran 11 tests`, `OK`, and the skipped count `0` — the
build ran and the installed class ran against its `home-manager-files`.
Run: `just agent-workflow-tests 2>&1 | tail -3` — `OK` (the installed class is
skipped there, D8).
Run: `just --list 2>&1 | grep -c agent-installed-skill-tests` — `1`.

- [ ] **Step 5: Commit**

Stage exactly the two Files above and commit (signed; harness attribution
trailers only):

```
test(agent-skills): check dispatch contracts in the built skill trees

Add InstalledTreeContractsTest over the Claude and Codex views of
AGENT_SKILLS_INSTALLED_HOME (skipped when unset; failing when the root
is not an absolute directory or a view or carrier is missing) and the
agent-installed-skill-tests recipe, which builds the configuration and
points the variable at its single home-manager-files output.
```

- [ ] **Step 6: Final branch gates**

Run: `git log -1 --format='%(trailers:key=Recovered-From,valueonly)'` — an empty line.
Run: `git log --no-merges --format='%(trailers:key=Recovered-From,valueonly)' origin/main..HEAD | grep -c 3c9709ca470bd473d49b39a611ca6cab258973db`
— `1` (Task 1's recovery commit only).
Run the root's **AC4 exclusion gate** — `AC4 exclusion gate: pass`.
Run: `git status --porcelain` — empty (`./result` is git-ignored).
