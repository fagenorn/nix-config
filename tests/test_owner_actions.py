"""owner-actions (issue 624): repository identity, refresh against the fake gh, statusline from the cache."""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import agent_platform
from agent_tools import owner_actions as oa
from .forge_world import ForgeWorld

SLUG, OTHER, STRANGER = "octo/widgets", "octo/gadgets", "octo/stranger"


def checkout(root: Path, slug: str | None, *, remote: str = "origin", url: str | None = None) -> Path:
    """A plain checkout at `root`: a `.git/config` whose `remote` names `slug` on github.com."""
    (root / ".git").mkdir(parents=True)
    lines = ["[core]", "\tbare = false"]
    if slug is not None or url is not None:
        lines += [f'[remote "{remote}"]', f"\turl = {url or f'git@github.com:{slug}.git'}",
                  "\tfetch = +refs/heads/*:refs/remotes/origin/*"]
    (root / ".git" / "config").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return root


class Scratch(unittest.TestCase):
    """A fake gh/git world, and HOME at a temporary directory."""

    def setUp(self):
        self.world = ForgeWorld(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.home = self.root / "home"
        self.home.mkdir()
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)

    def register(self, *roots: Path) -> None:
        agent_platform.write_registry(
            [{"project_id": f"p{i}", "root": str(r)} for i, r in enumerate(roots)])


class IdentityTest(Scratch):
    def test_plain_checkout_from_a_subdirectory(self):
        repo = checkout(self.root / "widgets", SLUG)
        (repo / "a" / "b").mkdir(parents=True)
        self.assertEqual(oa.checkout_slug(repo / "a" / "b"), SLUG)
        self.assertEqual(oa.checkout_slug(repo), SLUG)

    def test_https_and_ssh_spellings(self):
        self.assertEqual(oa.checkout_slug(checkout(self.root / "h", None,
                                                   url="https://github.com/octo/widgets.git")), SLUG)
        self.assertEqual(oa.checkout_slug(checkout(self.root / "s", None,
                                                   url="ssh://git@github.com/octo/widgets")), SLUG)

    def test_linked_worktree_reads_the_common_config(self):
        main = checkout(self.root / "main", SLUG)
        gitdir = main / ".git" / "worktrees" / "wt"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt = self.root / "wt"
        wt.mkdir()
        (wt / ".git").write_text(f"gitdir: {gitdir}\n", encoding="utf-8")
        self.assertEqual(oa.checkout_slug(wt), SLUG)

    def test_relative_gitdir_file(self):
        main = checkout(self.root / "main", SLUG)
        gitdir = main / ".git" / "worktrees" / "rel"
        gitdir.mkdir(parents=True)
        (gitdir / "commondir").write_text("../..\n", encoding="utf-8")
        wt = self.root / "rel"
        wt.mkdir()
        (wt / ".git").write_text("gitdir: ../main/.git/worktrees/rel\n", encoding="utf-8")
        self.assertEqual(oa.checkout_slug(wt), SLUG)

    def test_none_without_a_github_origin(self):
        self.assertIsNone(oa.checkout_slug(checkout(self.root / "u", SLUG, remote="upstream")))
        self.assertIsNone(oa.checkout_slug(checkout(self.root / "n", None)))
        self.assertIsNone(oa.checkout_slug(checkout(self.root / "g", None,
                                                    url="git@gitlab.com:octo/widgets.git")))
        self.assertIsNone(oa.checkout_slug(checkout(self.root / "l", None,
                                                    url="git@github.com.evil:octo/widgets.git")))
        plain = self.root / "plain"
        plain.mkdir()
        self.assertIsNone(oa.checkout_slug(plain))
        broken = self.root / "broken"
        broken.mkdir()
        (broken / ".git").write_text("not a gitdir line\n", encoding="utf-8")
        self.assertIsNone(oa.checkout_slug(broken))

    def test_origin_after_another_remote(self):
        repo = self.root / "both"
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(
            '[remote "upstream"]\n\turl = git@github.com:octo/upstream.git\n'
            '# a comment\n[remote "origin"]\n  url=git@github.com:octo/widgets.git\n', encoding="utf-8")
        self.assertEqual(oa.checkout_slug(repo), SLUG)

    def raw(self, name: str, text: str) -> Path:
        repo = self.root / name
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(text, encoding="utf-8")
        return repo

    def test_git_config_syntax_forms(self):
        forms = {
            "inline-hash": '[remote "origin"]\n\turl = https://github.com/octo/widgets.git # origin\n',
            "inline-semicolon": '[remote "origin"]\n\turl = git@github.com:octo/widgets.git ; note\n',
            "quoted": '[remote "origin"]\n\turl = "https://github.com/octo/widgets.git"\n',
            "quoted-hash": '[remote "origin"]\n\turl = "git@github.com:octo/widgets.git" # "x"\n',
            "case": '[Remote "origin"]\n\tURL = git@github.com:octo/widgets.git\n',
            "same-line": '[remote "origin"] url = git@github.com:octo/widgets.git\n',
            "legacy": '[remote.origin]\n\turl = git@github.com:octo/widgets.git\n',
            "continued": '[remote "origin"]\n\turl = https://github.com/octo/\\\nwidgets.git\n',
            "spaced-header": '[ remote  "origin" ]\n\turl=git@github.com:octo/widgets.git\n',
        }
        for name, text in forms.items():
            self.assertEqual(oa.checkout_slug(self.raw(name, text)), SLUG, name)

    def test_other_subsections_and_malformed_configs_are_none(self):
        forms = {
            "subsection-case": '[remote "Origin"]\n\turl = git@github.com:octo/widgets.git\n',
            "valueless": '[remote "origin"]\n\turl\n',
            "open-quote": '[remote "origin"]\n\turl = "git@github.com:octo/widgets.git\n',
            "bad-escape": '[remote "origin"]\n\turl = git@github.com:octo/\\qwidgets.git\n',
            "open-header": '[remote "origin"\n\turl = git@github.com:octo/widgets.git\n',
            "commented-out": '[remote "origin"]\n#\turl = git@github.com:octo/widgets.git\n',
        }
        for name, text in forms.items():
            self.assertIsNone(oa.checkout_slug(self.raw(name, text)), name)

    def test_fleet_slugs_from_the_registry(self):
        self.assertEqual(oa.fleet_slugs(), frozenset())
        self.register(checkout(self.root / "w", SLUG), checkout(self.root / "g", OTHER),
                      checkout(self.root / "x", None), self.root / "missing")
        self.assertEqual(oa.fleet_slugs(), frozenset({SLUG, OTHER}))

    def test_corrupt_registry_propagates(self):
        path = agent_platform.registry_path()
        path.parent.mkdir(parents=True)
        path.write_text("{", encoding="utf-8")
        with self.assertRaises(agent_platform.PlatformManifestError):
            oa.fleet_slugs()

    def test_identity_starts_no_process(self):
        self.register(checkout(self.root / "w", SLUG))
        with mock.patch.object(subprocess, "run", side_effect=AssertionError("run")), \
                mock.patch.object(subprocess, "Popen", side_effect=AssertionError("Popen")):
            self.assertEqual(oa.checkout_slug(self.root / "w"), SLUG)
            self.assertEqual(oa.fleet_slugs(), frozenset({SLUG}))
        self.assertEqual(self.world.calls(), [])


if __name__ == "__main__":
    unittest.main()
