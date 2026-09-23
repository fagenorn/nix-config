# Task 1: Skill-tree support module

Decisions: D13 (and #153's D7, D8, D16, which it preserves). Work from the
worktree root; paths are repo-relative. New work — no `Recovered-From` trailer.

**Files:**
- Create: `home/common/agent-skills/tests/skill_tree_support.py`
- Modify: `home/common/agent-skills/tests/test_dispatch_contracts.py`
- Test: `home/common/agent-skills/tests/test_dispatch_contracts.py` (unchanged
  behaviour is the contract)

**Interfaces:**
- Consumes: `test_dispatch_contracts.py` as merged at `a6ac80f` — its
  `REPO_ROOT`, `SHARED_TREE`, `CLAUDE_ONLY_TREE`, `SOURCE_TREES`,
  `INSTALLED_HOME_ENV`, `INSTALLED_RECIPE`, `INSTALLED_VIEWS` constants and the
  skip/validation code in `InstalledTreeContractsTest`.
- Produces (in `skill_tree_support.py`, later tasks import exactly these):
  - `REPO_ROOT: Path` (`Path(__file__).resolve().parents[4]`)
  - `SHARED_TREE`, `CLAUDE_ONLY_TREE: Path`
  - `SOURCE_TREES: dict[str, Path]` — keys `"shared"`, `"claude-only"`
  - `INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"`
  - `INSTALLED_RECIPE = "just agent-installed-skill-tests"`
  - `INSTALLED_VIEWS: tuple[tuple[str, str, frozenset[str]], ...]` —
    `("claude", ".claude/skills", {"shared", "claude-only"})`,
    `("codex", ".agents/skills", {"shared"})`
  - `installed_home_or_skip() -> Path`
  - `installed_root_error(root: Path) -> str | None`

**Invariants:**
- The support module declares no `TestCase` and is not listed in any recipe.
- Each constant above has exactly one definition in
  `home/common/agent-skills/tests/` — in the support module (D13).
- `test_dispatch_contracts.py` behaves exactly as before: same test ids, same
  skip reason, same failure messages, under both recipes.

- [ ] **Step 1: Create the support module**

`home/common/agent-skills/tests/skill_tree_support.py`:

```python
"""Where the agent skills live: the two source trees and the installed views.

Shared by the contract suites that read skill documents (test_dispatch_contracts,
test_shell_example_contracts), so the tree layout, the installed-home variable
and its skip/fail rules have one home. It declares no TestCase, so it is
support rather than a suite and is not listed as one.
"""
import os
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[4]
SHARED_TREE = REPO_ROOT / "home/common/agent-skills/skills"
CLAUDE_ONLY_TREE = REPO_ROOT / "home/common/claude-code/skills"
SOURCE_TREES = {"shared": SHARED_TREE, "claude-only": CLAUDE_ONLY_TREE}

# Any directory laid out like the home home-manager populates: the built
# home-manager-files output, or $HOME after a switch.
INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
# (view, skill directory under the installed home, source trees it publishes)
INSTALLED_VIEWS = (
    ("claude", ".claude/skills", frozenset({"shared", "claude-only"})),
    ("codex", ".agents/skills", frozenset({"shared"})),
)


def installed_home_or_skip():
    """The installed home to check; unset variable → skip naming the recipe."""
    root = os.environ.get(INSTALLED_HOME_ENV)
    if root is None:
        raise unittest.SkipTest(
            f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
            "check the skill trees the Nix build installs"
        )
    return Path(root)


def installed_root_error(root):
    """Why `root` cannot be checked, or None. A set variable never falls back."""
    if root.is_absolute() and root.is_dir():
        return None
    return f"{INSTALLED_HOME_ENV}={str(root)!r} is not an absolute directory"
```

- [ ] **Step 2: Point the dispatch suite at it**

In `test_dispatch_contracts.py`:
- Delete the `REPO_ROOT`, `SHARED_TREE`, `CLAUDE_ONLY_TREE`, `SOURCE_TREES`
  lines and the `INSTALLED_*` block with its two comments, and the `import os`
  line.
- Directly after `import unittest` add:

```python
import sys

# unittest loads suites by path, so the directory is not a package; the
# shared support module lives beside this file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from skill_tree_support import (  # noqa: E402
    INSTALLED_VIEWS,
    SOURCE_TREES,
    installed_home_or_skip,
    installed_root_error,
)
```

- `InstalledTreeContractsTest.setUpClass` body becomes
  `cls.root = installed_home_or_skip()`.
- In `assert_contract_installed`, replace the `self.assertTrue(self.root.is_absolute() and self.root.is_dir(), …)`
  call with:

```python
        error = installed_root_error(self.root)
        self.assertIsNone(error, error)
```

Leave every other line of the module untouched. If any other name in the module
still references a deleted constant, import that name from the support module
too rather than redefining it.

- [ ] **Step 3: Verify the source run**

Run: `python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: `OK (skipped=2)`, and the skip reason (visible with `-v`) still reads
`AGENT_SKILLS_INSTALLED_HOME is unset; run `just agent-installed-skill-tests` …`.

- [ ] **Step 4: Verify the fail-closed root rule still fails**

Run: `env AGENT_SKILLS_INSTALLED_HOME=relative/home python3 -m unittest home/common/agent-skills/tests/test_dispatch_contracts.py`
Expected: exit 1, two failures whose message contains
`AGENT_SKILLS_INSTALLED_HOME='relative/home' is not an absolute directory`.

- [ ] **Step 5: Verify the single home**

Run: `git grep -n -e "INSTALLED_HOME_ENV = " -e "SOURCE_TREES = " -e "INSTALLED_VIEWS = " -- home/common/agent-skills/tests`
Expected: exactly three lines, all in `skill_tree_support.py` (at the base
commit this prints three lines in `test_dispatch_contracts.py` — the check that
fails before the move).

- [ ] **Step 6: Verify the installed run and the suite**

Run: `just agent-installed-skill-tests`
Expected: exit 0, `OK`, no skips (the recipe builds first).

Run: `just agent-workflow-tests`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add home/common/agent-skills/tests/skill_tree_support.py home/common/agent-skills/tests/test_dispatch_contracts.py
git commit -m "refactor(agent-skills): share the skill-tree layout between contract suites"
```
