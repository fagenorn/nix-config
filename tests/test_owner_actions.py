"""owner-actions (issue 624): repository identity, refresh against the fake gh, statusline from the cache."""
import contextlib
import io
import json
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


OA_CREATE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]


def node(labels, events=(), *, label_total=None, event_total=None):
    """A search node: its current labels, and (label, createdAt) LabeledEvents in timeline order.
    The totals default to complete connections."""
    return {"labels": {"totalCount": len(labels) if label_total is None else label_total,
                       "nodes": [{"name": n} for n in labels]},
            "timelineItems": {"totalCount": len(events) if event_total is None else event_total,
                              "nodes": [{"createdAt": at, "label": {"name": n}} for n, at in events]}}


def answer(nodes, label_exists=True, next_cursor=None):
    return {"data": {"repository": {"label": {"name": "owner-action"} if label_exists else None},
                     "search": {"pageInfo": {"hasNextPage": next_cursor is not None,
                                             "endCursor": next_cursor},
                                "nodes": nodes}}}


def run_main(argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = oa.main(argv)
    return code, out.getvalue(), err.getvalue()


class RefreshTest(Scratch):
    def test_counts_only_owner_action_labels(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([
            node(["agent:human-required"], [("agent:human-required", "2026-10-27T08:00:00Z")]),
            node(["owner-action", "in-progress"], [("owner-action", "2026-11-01T00:00:00Z")]),
            node(["needs-verification"], [("needs-verification", "2026-01-01T00:00:00Z")]),
            node(["verification-failed", "in-progress"], [("in-progress", "2026-01-02T00:00:00Z")]),
        ]))
        self.assertEqual(oa.refresh(SLUG), {"schema_version": 1, "repo": SLUG, "count": 2,
                                            "oldest": "2026-10-27T08:00:00Z"})
        self.assertEqual(oa.read_entry(SLUG)["count"], 2)
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG)])
        self.assertEqual(oa.cache_path(SLUG), self.home / ".agents/state/owner-actions/octo/widgets.json")
        self.assertEqual(sorted(p.name for p in oa.cache_path(SLUG).parent.iterdir()), ["widgets.json"])

    def test_label_time_is_the_latest_application_of_a_current_label(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([
            node(["agent:human-required"], [("agent:human-required", "2026-10-01T00:00:00Z"),
                                            ("agent:human-required", "2026-11-02T00:00:00Z")]),
            node(["owner-action", "agent:human-required"], [("agent:human-required", "2026-11-04T00:00:00Z"),
                                                            ("owner-action", "2026-11-03T00:00:00Z")]),
        ]))
        self.assertEqual(oa.refresh(SLUG)["oldest"], "2026-11-02T00:00:00Z")

    def test_an_item_without_a_label_event_counts_with_no_time(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"])]))
        self.assertEqual(oa.refresh(SLUG), {"schema_version": 1, "repo": SLUG, "count": 1, "oldest": None})

    def test_zero_items(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([]))
        self.assertEqual(oa.refresh(SLUG)["count"], 0)

    def test_creates_the_owner_action_label_when_missing(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([], label_exists=False))
        self.world.respond_json("gh", OA_CREATE, {"name": "owner-action"})
        oa.refresh(SLUG)
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG), OA_CREATE])

    def test_search_names_the_repo_and_both_labels(self):
        argv = oa.search_argv(SLUG)
        self.assertEqual(argv[:2], ["api", "graphql"])
        for pair in (["-f", "owner=octo"], ["-f", "name=widgets"],
                     ["-f", f"search=repo:{SLUG} is:open label:owner-action,agent:human-required"]):
            self.assertIn(pair[1], argv)
            self.assertEqual(argv[argv.index(pair[1]) - 1], "-f")
        self.assertFalse(any(a.startswith("after=") for a in argv))
        self.assertEqual(oa.search_argv(SLUG, "Y3Vy")[-2:], ["-f", "after=Y3Vy"])

    def test_follows_search_pages_to_a_complete_count(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([
            node(["owner-action"], [("owner-action", "2026-11-01T00:00:00Z")]),
            node(["owner-action"], [("owner-action", "2026-11-02T00:00:00Z")]),
        ], next_cursor="c1"))
        self.world.respond_json("gh", oa.search_argv(SLUG, "c1"), answer([
            node(["agent:human-required"], [("agent:human-required", "2026-10-15T00:00:00Z")]),
        ], label_exists=False))
        self.assertEqual(oa.refresh(SLUG), {"schema_version": 1, "repo": SLUG, "count": 3,
                                            "oldest": "2026-10-15T00:00:00Z"})
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG), oa.search_argv(SLUG, "c1")])

    def test_truncated_item_connections_are_incomplete(self):
        oa.write_entry(SLUG, 3, "2026-10-01T00:00:00Z")
        before = oa.cache_path(SLUG).read_bytes()
        for nodes in ([node(["owner-action"], label_total=101)],
                      [node(["owner-action"], [("in-progress", "2026-11-01T00:00:00Z")], event_total=101)]):
            self.world.reset()
            self.world.respond_json("gh", oa.search_argv(SLUG), answer(nodes))
            code, out, err = run_main(["refresh", "--repo", SLUG])
            self.assertEqual((code, json.loads(out)["failed"]), (1, [{"repo": SLUG, "error": "payload_incomplete"}]))
            self.assertIn(f"owner-actions: {SLUG}: payload_incomplete", err)
            self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)

    def test_a_found_event_needs_no_complete_timeline(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([
            node(["owner-action"], [("owner-action", "2026-11-01T00:00:00Z")], event_total=500)]))
        self.assertEqual(oa.refresh(SLUG)["oldest"], "2026-11-01T00:00:00Z")

    def test_a_search_past_the_page_cap_is_incomplete(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"])], next_cursor="c1"))
        self.world.respond_json("gh", oa.search_argv(SLUG, "c1"), answer([node(["owner-action"])], next_cursor="c2"))
        with mock.patch.object(oa, "MAX_PAGES", 2), self.assertRaises(oa.forge_markers.ForgeError) as raised:
            oa.refresh(SLUG)
        self.assertEqual(raised.exception.code, "payload_incomplete")
        self.assertIsNone(oa.read_entry(SLUG))

    def test_a_repeated_cursor_is_invalid(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([], next_cursor="c1"))
        self.world.respond_json("gh", oa.search_argv(SLUG, "c1"), answer([], next_cursor="c1"))
        with self.assertRaises(oa.forge_markers.ForgeError) as raised:
            oa.refresh(SLUG)
        self.assertEqual(raised.exception.code, "payload_invalid")

    def test_a_failed_refresh_keeps_the_entry_and_logs_the_error(self):
        oa.write_entry(SLUG, 3, "2026-10-01T00:00:00Z")
        before = oa.cache_path(SLUG).read_bytes()
        self.world.respond("gh", oa.search_argv(SLUG), exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        code, out, err = run_main(["refresh", "--repo", SLUG])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"refreshed": [], "failed": [{"repo": SLUG, "error": "gh_failed"}]})
        self.assertIn(f"owner-actions: {SLUG}: gh_failed: gh: Bad Gateway (HTTP 502)", err)
        self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)

    def test_an_unexpected_payload_writes_nothing(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), {"data": {"search": None}})
        code, out, err = run_main(["refresh", "--repo", SLUG])
        self.assertEqual((code, json.loads(out)["failed"]), (1, [{"repo": SLUG, "error": "payload_invalid"}]))
        self.assertIsNone(oa.read_entry(SLUG))

    def test_without_repo_refreshes_every_fleet_repo_even_after_a_failure(self):
        self.register(checkout(self.root / "w", SLUG), checkout(self.root / "g", OTHER))
        self.world.respond("gh", oa.search_argv(OTHER), exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"])]))
        oa.write_entry(OTHER, 0, None)
        code, out, err = run_main(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"refreshed": [SLUG], "failed": [{"repo": OTHER, "error": "gh_failed"}]})
        self.assertEqual(oa.read_entry(SLUG)["count"], 1)
        self.assertEqual(oa.read_entry(OTHER)["count"], 0)

    def test_success_exits_zero(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([]))
        self.assertEqual(run_main(["refresh", "--repo", SLUG]), (0, json.dumps(
            {"failed": [], "refreshed": [SLUG]}, sort_keys=True) + "\n", ""))

    def test_corrupt_registry(self):
        agent_platform.registry_path().parent.mkdir(parents=True)
        agent_platform.registry_path().write_text("{", encoding="utf-8")
        code, out, err = run_main(["refresh"])
        self.assertEqual((code, json.loads(out)), (1, {"refreshed": [], "failed": [{"repo": None, "error": "registry"}]}))
        self.assertIn("owner-actions: registry: ", err)

    def test_bad_repo_is_a_usage_error(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            oa.main(["refresh", "--repo", "../etc"])
        self.assertEqual(raised.exception.code, 2)
        self.assertEqual(self.world.calls(), [])

    def test_write_entry_round_trips_as_bytes(self):
        oa.write_entry(SLUG, 2, None)
        self.assertEqual(oa.cache_path(SLUG).read_bytes(), (json.dumps(
            {"count": 2, "oldest": None, "repo": SLUG, "schema_version": 1}, sort_keys=True) + "\n").encode("utf-8"))
        self.assertEqual(oa.read_entry(SLUG), {"schema_version": 1, "repo": SLUG, "count": 2, "oldest": None})

    def test_read_entry_rejects_other_shapes(self):
        path = oa.cache_path(SLUG)
        path.parent.mkdir(parents=True)
        for text in ("{", "[]", json.dumps({"schema_version": 1, "repo": OTHER, "count": 1, "oldest": None}),
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": True, "oldest": None}),
                     json.dumps({"schema_version": 2, "repo": SLUG, "count": 1, "oldest": None}),
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": -1, "oldest": None}),
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": 1, "oldest": None, "x": 1})):
            path.write_text(text, encoding="utf-8")
            self.assertIsNone(oa.read_entry(SLUG), text)


    def test_an_item_time_is_the_earliest_of_its_counted_labels(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([
            node(["owner-action", "agent:human-required"], [("owner-action", "2026-11-04T00:00:00Z"),
                                                            ("agent:human-required", "2026-11-03T00:00:00Z")])]))
        self.assertEqual(oa.refresh(SLUG)["oldest"], "2026-11-03T00:00:00Z")

    def test_a_boolean_total_or_a_malformed_page_is_invalid(self):
        for payload in (answer([node(["owner-action"], label_total=True)]),
                        answer([node(["owner-action"], event_total=True)]),
                        {"data": {"search": {"nodes": [], "pageInfo": None}}}):
            self.world.reset()
            self.world.respond_json("gh", oa.search_argv(SLUG), payload)
            with self.assertRaises(oa.forge_markers.ForgeError) as raised:
                oa.refresh(SLUG)
            self.assertEqual(raised.exception.code, "payload_invalid")
        self.assertIsNone(oa.read_entry(SLUG))


if __name__ == "__main__":
    unittest.main()
