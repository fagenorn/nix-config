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
