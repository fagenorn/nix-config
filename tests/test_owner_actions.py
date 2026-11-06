"""owner-actions (issue 624): repository identity, refresh against the fake gh, statusline from the cache."""
import contextlib
import fcntl
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import agent_platform, siblings
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

    def test_a_repo_named_with_a_leading_dot_is_a_fleet_repo(self):
        dot = "octo/.github"
        self.register(checkout(self.root / "d", dot))
        self.assertEqual(oa.checkout_slug(self.root / "d"), dot)
        self.assertEqual(oa.fleet_slugs(), frozenset({dot}))
        self.world.respond_json("gh", oa.search_argv(dot), answer([]))
        self.assertEqual(run_main(["refresh", "--repo", dot])[0], 0)
        self.assertEqual(oa.read_entry(dot)["count"], 0)

    def test_dot_names_and_dot_owners_are_not_slugs(self):
        for bad in ("octo/.", "octo/..", ".octo/widgets", "octo/", "/widgets"):
            self.assertIsNone(oa.SLUG_PATTERN.fullmatch(bad), bad)

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


def answer(nodes, label_exists=True, next_cursor=None, total=None):
    """One search page; `total` is the search's issueCount, the number of nodes when omitted."""
    return {"data": {"repository": {"label": {"name": "owner-action"} if label_exists else None},
                     "search": {"issueCount": len(nodes) if total is None else total,
                                "pageInfo": {"hasNextPage": next_cursor is not None,
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
        ], next_cursor="c1", total=3))
        self.world.respond_json("gh", oa.search_argv(SLUG, "c1"), answer([
            node(["agent:human-required"], [("agent:human-required", "2026-10-15T00:00:00Z")]),
        ], label_exists=False, total=3))
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

    def test_a_search_capped_below_its_issue_count_is_incomplete(self):
        oa.write_entry(SLUG, 3, "2026-10-01T00:00:00Z")
        before = oa.cache_path(SLUG).read_bytes()
        nodes = [node(["owner-action"]) for _ in range(1000)]
        self.world.respond_json("gh", oa.search_argv(SLUG), answer(nodes, total=1101))
        code, out, err = run_main(["refresh", "--repo", SLUG])
        self.assertEqual((code, json.loads(out)["failed"]), (1, [{"repo": SLUG, "error": "payload_incomplete"}]))
        self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)

    def test_the_search_asks_for_its_issue_count_and_requires_one(self):
        self.assertIn("issueCount", oa.QUERY)
        for count in (None, True, "1", 1.5):
            self.world.reset()
            payload = answer([node(["owner-action"])])
            if count is None:
                del payload["data"]["search"]["issueCount"]
            else:
                payload["data"]["search"]["issueCount"] = count
            self.world.respond_json("gh", oa.search_argv(SLUG), payload)
            with self.assertRaises(oa.forge_markers.ForgeError) as raised:
                oa.refresh(SLUG)
            self.assertEqual(raised.exception.code, "payload_invalid", count)
        self.assertIsNone(oa.read_entry(SLUG))

    def test_a_missing_or_non_boolean_has_next_page_is_invalid(self):
        oa.write_entry(SLUG, 3, "2026-10-01T00:00:00Z")
        before = oa.cache_path(SLUG).read_bytes()
        for info in ({}, {"hasNextPage": None}, {"hasNextPage": "false"}, {"hasNextPage": 0},
                     {"endCursor": "c1"}):
            self.world.reset()
            payload = answer([])
            payload["data"]["search"]["pageInfo"] = info
            self.world.respond_json("gh", oa.search_argv(SLUG), payload)
            code, out, err = run_main(["refresh", "--repo", SLUG])
            self.assertEqual((code, json.loads(out)["failed"]),
                             (1, [{"repo": SLUG, "error": "payload_invalid"}]), info)
            self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)

    def test_a_malformed_api_timestamp_is_invalid_and_writes_nothing(self):
        oa.write_entry(SLUG, 3, "2026-10-01T00:00:00Z")
        before = oa.cache_path(SLUG).read_bytes()
        for at in ("yesterday", "2026-13-45T00:00:00Z", "2026-11-01T00:00:00", ""):
            self.world.reset()
            self.world.respond_json("gh", oa.search_argv(SLUG), answer([
                node(["owner-action"], [("owner-action", at)])]))
            code, out, err = run_main(["refresh", "--repo", SLUG])
            self.assertEqual((code, json.loads(out)["failed"]),
                             (1, [{"repo": SLUG, "error": "payload_invalid"}]), at)
            self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)

    def test_a_malformed_timestamp_fails_one_repo_not_the_fleet(self):
        self.register(checkout(self.root / "widgets", SLUG), checkout(self.root / "gadgets", OTHER))
        self.world.respond_json("gh", oa.search_argv(OTHER), answer([
            node(["owner-action"], [("owner-action", "not a date")])]))
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"])]))
        code, out, err = run_main(["refresh"])
        self.assertEqual((code, json.loads(out)), (1, {"refreshed": [SLUG],
                                                       "failed": [{"repo": OTHER, "error": "payload_invalid"}]}))

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

    def test_a_cache_write_failure_for_one_repo_does_not_stop_the_fleet(self):
        self.register(checkout(self.root / "w", SLUG), checkout(self.root / "g", OTHER))
        self.world.respond_json("gh", oa.search_argv(OTHER), answer([]))
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"])]))
        real = oa.write_entry

        def write(slug, count, oldest):
            if slug == OTHER:
                raise PermissionError(13, "Permission denied")
            real(slug, count, oldest)

        with mock.patch.object(oa, "write_entry", write):
            code, out, err = run_main(["refresh"])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out), {"refreshed": [SLUG], "failed": [{"repo": OTHER, "error": "cache_write"}]})
        self.assertIn(f"owner-actions: {OTHER}: ", err)
        self.assertEqual(oa.read_entry(SLUG)["count"], 1)

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
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": 1, "oldest": None, "x": 1}),
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": 1, "oldest": "not a date"}),
                     json.dumps({"schema_version": 1, "repo": SLUG, "count": 1, "oldest": "2026-11-01T00:00:00"})):
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


PYTHON_DIR = Path(__file__).resolve().parent.parent / "python"
DAY = 86400


def iso(seconds_ago: float) -> str:
    from datetime import datetime, timezone
    return datetime.fromtimestamp(time.time() - seconds_ago, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def age(path: Path, seconds: float) -> None:
    then = time.time() - seconds
    os.utime(path, (then, then))


def attempted(slug: str, seconds_ago: float) -> None:
    """Record a refresh attempt `seconds_ago` in the claim file, as claim_refresh would."""
    path = oa.claim_path(slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{time.time() - seconds_ago:.3f}\n", encoding="utf-8")


def claim_free(slug: str) -> bool:
    fd = os.open(oa.claim_path(slug), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return True
    except BlockingIOError:
        return False
    finally:
        os.close(fd)


def wait_for(condition, message, timeout=15):
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError(message)
        time.sleep(0.05)


class StatuslineTest(Scratch):
    """A two-repo fleet with a fixture cache: SLUG has 2 items (oldest 3 days 1 hour), OTHER has 0.
    A third checkout, STRANGER, has a cache entry but is not registered."""

    def setUp(self):
        super().setUp()
        self.widgets = checkout(self.root / "widgets", SLUG)
        self.gadgets = checkout(self.root / "gadgets", OTHER)
        self.stranger = checkout(self.root / "stranger", STRANGER)
        self.register(self.widgets, self.gadgets)
        oa.write_entry(SLUG, 2, iso(3 * DAY + 3600))
        oa.write_entry(OTHER, 0, None)
        oa.write_entry(STRANGER, 5, iso(9 * DAY))
        popen = mock.patch.object(oa.subprocess, "Popen")
        self.popen = popen.start()
        self.addCleanup(popen.stop)

    def line(self, payload, code=0) -> str:
        text = payload if isinstance(payload, str) else json.dumps(payload)
        out, err = io.StringIO(), io.StringIO()
        with mock.patch.object(sys, "stdin", io.StringIO(text)), contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            self.assertEqual(oa.main(["statusline"]), code)
        self.assertEqual(self.world.calls(), [])
        self.err = err.getvalue()
        return out.getvalue()

    def test_prints_count_and_age_for_the_cwd_repo_only(self):
        (self.widgets / "src").mkdir()
        self.assertEqual(self.line({"cwd": str(self.widgets / "src")}), "owner 2 (oldest 3d)\n")
        self.assertEqual(self.line({"workspace": {"current_dir": str(self.widgets)}}), "owner 2 (oldest 3d)\n")
        self.assertEqual(self.err, "")
        self.popen.assert_not_called()

    def test_count_without_a_label_time(self):
        oa.write_entry(SLUG, 1, None)
        self.assertEqual(self.line({"cwd": str(self.widgets)}), "owner 1\n")

    def test_blank_for_zero_non_fleet_non_git_and_bad_input(self):
        plain = self.root / "plain"
        plain.mkdir()
        for payload in ({"cwd": str(self.gadgets)}, {"cwd": str(self.stranger)}, {"cwd": str(plain)},
                        "not json", "[]", {"cwd": 7}, {}):
            self.assertEqual(self.line(payload), "", payload)
            self.assertEqual(self.err, "", payload)
        self.popen.assert_not_called()

    def test_corrupt_registry_is_blank_and_reported(self):
        agent_platform.registry_path().write_text("{", encoding="utf-8")
        self.assertEqual(self.line({"cwd": str(self.widgets)}, code=1), "")
        self.assertIn("PlatformManifestError", self.err)
        self.popen.assert_not_called()

    def test_an_unexpected_failure_is_blank_and_reported(self):
        with mock.patch.object(oa, "read_entry", side_effect=RuntimeError("boom")):
            self.assertEqual(self.line({"cwd": str(self.widgets)}, code=1), "")
        self.assertIn("RuntimeError: boom", self.err)
        self.popen.assert_not_called()

    def test_fresh_entry_spawns_nothing(self):
        age(oa.cache_path(SLUG), 14 * 60)
        self.line({"cwd": str(self.widgets)})
        self.popen.assert_not_called()

    def test_stale_entry_spawns_one_detached_refresh_and_prints_fast(self):
        age(oa.cache_path(SLUG), 16 * 60)
        started = time.perf_counter()
        printed = self.line({"cwd": str(self.widgets)})
        elapsed = time.perf_counter() - started
        self.assertEqual(printed, "owner 2 (oldest 3d)\n")
        self.assertLess(elapsed, 0.1)
        self.popen.assert_called_once()
        args, kwargs = self.popen.call_args
        self.assertEqual(args[0], siblings.sibling_argv("owner_actions") + ["refresh", "--repo", SLUG])
        self.assertTrue(kwargs["start_new_session"])
        self.assertEqual(kwargs["cwd"], "/")
        self.assertIs(kwargs["stdin"], subprocess.DEVNULL)
        for stream in ("stdout", "stderr"):
            self.assertEqual(kwargs[stream].name, str(oa.log_path(SLUG)))
        self.assertEqual(len(kwargs["pass_fds"]), 1)
        self.assertTrue(claim_free(SLUG), "the parent must close its claim descriptor")

    def test_a_failed_attempt_spaces_retries(self):
        age(oa.cache_path(SLUG), 16 * 60)
        self.line({"cwd": str(self.widgets)})
        self.popen.assert_called_once()
        # The mocked child refreshed nothing: the entry is still stale and the claim is free.
        for _ in range(3):
            self.assertEqual(self.line({"cwd": str(self.widgets)}), "owner 2 (oldest 3d)\n")
        self.popen.assert_called_once()
        attempted(SLUG, oa.RETRY_AFTER + 1)
        self.line({"cwd": str(self.widgets)})
        self.assertEqual(self.popen.call_count, 2)

    def test_a_held_claim_blocks_the_spawn(self):
        age(oa.cache_path(SLUG), 16 * 60)
        attempted(SLUG, 10 * 60)
        fd = os.open(oa.claim_path(SLUG), os.O_RDWR)
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            self.assertEqual(self.line({"cwd": str(self.widgets)}), "owner 2 (oldest 3d)\n")
            self.popen.assert_not_called()
        finally:
            os.close(fd)
        self.line({"cwd": str(self.widgets)})
        self.popen.assert_called_once()

    def test_garbage_or_future_attempt_times_expire(self):
        age(oa.cache_path(SLUG), 16 * 60)
        oa.claim_path(SLUG).write_text("not a time\n", encoding="utf-8")
        self.line({"cwd": str(self.widgets)})
        attempted(SLUG, -3600)
        self.line({"cwd": str(self.widgets)})
        self.assertEqual(self.popen.call_count, 2)

    def test_concurrent_calls_spawn_once(self):
        age(oa.cache_path(SLUG), 16 * 60)
        self.popen.side_effect = lambda *a, **k: time.sleep(0.05)
        barrier = threading.Barrier(8)
        printed, errors = [], []
        payload = json.dumps({"cwd": str(self.widgets)})

        def call():
            try:
                barrier.wait()
                printed.append(oa.statusline(payload))
            except Exception as error:  # surfaced below
                errors.append(error)

        threads = [threading.Thread(target=call) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(10)
        self.assertEqual(errors, [])
        self.assertEqual(printed, ["owner 2 (oldest 3d)\n"] * 8)
        self.popen.assert_called_once()

    def test_missing_entry_of_a_fleet_repo_spawns_and_prints_nothing(self):
        oa.cache_path(OTHER).unlink()
        self.assertEqual(self.line({"cwd": str(self.gadgets)}), "")
        self.popen.assert_called_once()
        self.assertEqual(self.popen.call_args[0][0][-2:], ["--repo", OTHER])

    def test_a_spawn_failure_still_prints_and_is_reported(self):
        age(oa.cache_path(SLUG), 16 * 60)
        self.popen.side_effect = OSError("exec format error")
        self.assertEqual(self.line({"cwd": str(self.widgets)}), "owner 2 (oldest 3d)\n")
        self.assertIn(f"owner-actions: refresh spawn for {SLUG} failed: exec format error", self.err)

    def test_an_unreadable_fresh_entry_counts_as_missing(self):
        oa.cache_path(SLUG).write_text("{", encoding="utf-8")
        self.assertEqual(self.line({"cwd": str(self.widgets)}), "")
        self.popen.assert_called_once()

    def test_a_malformed_cached_timestamp_counts_as_missing_and_schedules_a_refresh(self):
        for oldest in ("not a date", "2026-11-01T00:00:00"):
            self.popen.reset_mock()
            attempted(SLUG, 600)
            oa.write_entry(SLUG, 2, oldest)
            self.assertEqual(self.line({"cwd": str(self.widgets)}), "", oldest)
            self.assertEqual(self.err, "")
            self.popen.assert_called_once()

    def test_a_claim_failure_still_prints_and_is_reported(self):
        age(oa.cache_path(SLUG), 16 * 60)
        with mock.patch.object(oa.os, "open", side_effect=PermissionError("denied")):
            self.assertEqual(self.line({"cwd": str(self.widgets)}), "owner 2 (oldest 3d)\n")
        self.assertIn(f"owner-actions: refresh claim for {SLUG} failed: denied", self.err)
        self.popen.assert_not_called()

    def test_render(self):
        now = time.time()
        self.assertEqual(oa.render(None, now), "")
        self.assertEqual(oa.render({"count": 0, "oldest": None}, now), "")
        self.assertEqual(oa.render({"count": 4, "oldest": iso(DAY - 60)}, now), "owner 4 (oldest 0d)")
        self.assertEqual(oa.render({"count": 4, "oldest": iso(10 * DAY + 60)}, now), "owner 4 (oldest 10d)")
        self.assertEqual(oa.render({"count": 4, "oldest": iso(-3600)}, now), "owner 4 (oldest 0d)")


class StatuslineEndToEndTest(Scratch):
    """Real statusline processes against the fake gh: the detached child really runs."""

    def setUp(self):
        super().setUp()
        self.widgets = checkout(self.root / "widgets", SLUG)
        self.register(self.widgets)
        oa.write_entry(SLUG, 1, iso(2 * DAY + 60))
        age(oa.cache_path(SLUG), 20 * 60)
        self.env = {**self.world.env(), "HOME": str(self.home), "PYTHONPATH": str(PYTHON_DIR)}

    def start(self):
        return subprocess.Popen([sys.executable, "-m", "agent_tools.owner_actions", "statusline"],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, env=self.env)

    def finish(self, process):
        out, err = process.communicate(json.dumps({"cwd": str(self.widgets)}), timeout=10)
        return process.returncode, out, err

    def test_returns_before_the_refresh_finishes(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"]), node(["owner-action"])]),
                                sleep=2)
        started = time.monotonic()
        result = self.finish(self.start())
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertEqual(result, (0, "owner 1 (oldest 2d)\n", ""))
        wait_for(lambda: (oa.read_entry(SLUG) or {}).get("count") == 2 and claim_free(SLUG),
                 "the detached refresh never rewrote the cache and released the claim")
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG)])
        self.assertEqual(self.world.argvs("git"), [])
        self.assertIn('"refreshed": ["octo/widgets"]', oa.log_path(SLUG).read_text("utf-8"))

    def test_concurrent_processes_start_one_refresh(self):
        self.world.respond_json("gh", oa.search_argv(SLUG), answer([node(["owner-action"]), node(["owner-action"])]),
                                sleep=2)
        processes = [self.start() for _ in range(4)]
        for process in processes:
            self.assertEqual(self.finish(process), (0, "owner 1 (oldest 2d)\n", ""))
        wait_for(lambda: (oa.read_entry(SLUG) or {}).get("count") == 2 and claim_free(SLUG),
                 "the detached refresh never rewrote the cache and released the claim")
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG)])

    def test_a_second_call_after_a_failed_refresh_starts_nothing(self):
        self.world.respond("gh", oa.search_argv(SLUG), exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        before = oa.cache_path(SLUG).read_bytes()
        self.assertEqual(self.finish(self.start()), (0, "owner 1 (oldest 2d)\n", ""))
        wait_for(lambda: self.world.argvs("gh") and claim_free(SLUG), "the failed refresh never finished")
        self.assertIn("gh_failed", oa.log_path(SLUG).read_text("utf-8"))
        claim = oa.claim_path(SLUG).read_bytes()
        self.assertEqual(self.finish(self.start()), (0, "owner 1 (oldest 2d)\n", ""))
        # A spawn always rewrites the attempt time first, so an unchanged claim proves none happened.
        self.assertEqual(oa.claim_path(SLUG).read_bytes(), claim)
        self.assertTrue(claim_free(SLUG))
        self.assertEqual(self.world.argvs("gh"), [oa.search_argv(SLUG)])
        self.assertEqual(oa.cache_path(SLUG).read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
