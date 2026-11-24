"""Contract tests for `landing` (`agent_tools.delivery.landing`).

Each reading runs through `main` against a real git project with a local bare origin and a fake
`gh` (`ForgeWorld`): the pull-request readings answer exact argv, `prepare` and `pushed` read real
repositories. No reading changes anything.
"""

from __future__ import annotations

import json
import os
import shlex
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timezone
from email.utils import format_datetime
from io import StringIO
from pathlib import Path
from unittest import mock

from agent_tools.claims import forge_land_lock, forge_markers
from agent_tools.delivery import engine_commands, landing
from agent_tools.project_contract import resolve_project
from agent_tools.system import forge_api
from agent_tools.verification import verified_tree

from .engine_fixture import FixtureProject
from .forge_world import ForgeWorld
from .guard_policy_world import GuardPolicyWorld
from .test_issue_setup import gh_only
from .test_land_tally import LedgerMaker, answer

TIER = "integration"

SLUG = "example/fixture"
ISSUE = 41
BODY = "## Acceptance criteria\n\n- [ ] [code] greet() returns the greeting\n"
SHA = "1" * 40
OTHER = "2" * 40
PULL_LIST = ["pr", "list", "--repo", SLUG, "--head", "issue-41-x", "--state", "open", "--json",
             "number,headRefOid,baseRefName,url"]
PULL_VIEW = ["pr", "view", "7", "--repo", SLUG, "--json", "state,headRefOid,mergeCommit"]
CHECKS_VIEW = ["pr", "view", "7", "--repo", SLUG, "--json", "headRefOid,statusCheckRollup"]
LOCK_REF = "refs/agent-locks/land/main"
FORGE_NOW = ["api", "--include", "rate_limit"]


def criteria(*lines: str) -> str:
    return "Intro.\n\n## Acceptance criteria\n\n" + "\n".join(lines) + "\n\n## Notes\n\n- [ ] [human] later\n"


class LandingWorld:
    """The fixture project, its fake forge and an environment that reaches both."""

    def __init__(self, test: unittest.TestCase, title: str = "Add a greeting",
                 project: type[FixtureProject] = FixtureProject) -> None:
        self.test = test
        self.world = GuardPolicyWorld(test)
        self.fixture = project(test, self.world, slug=SLUG)
        self.forge = ForgeWorld(test)
        issue = {"number": ISSUE, "title": title, "state": "open", "labels": [], "body": BODY}
        self.forge.respond_json("gh", ["api", f"repos/{SLUG}/issues/{ISSUE}"], issue)
        self.forge.respond_json("gh", ["api", "--paginate", "--slurp",
                                       f"repos/{SLUG}/pulls?state=open&per_page=100"], [[]])
        tmp = self.world.tmp / "landing"
        tmp.mkdir()
        self.env = {**self.world.env, "FORGE_WORLD": str(self.forge.state),
                    "VERIFY_SLOT_DIR": str(tmp / "slots"),
                    "PATH": os.pathsep.join([str(gh_only(self.forge, tmp / "gh")),
                                             self.world.env["PATH"]])}

    def call(self, *args: str) -> tuple[int, dict]:
        """`main(args)` under this world's environment: (exit status, the one JSON line printed)."""
        out = StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(out):
            status = landing.main(list(args))
        lines = out.getvalue().splitlines()
        self.test.assertEqual(len(lines), 1, out.getvalue())
        return status, json.loads(lines[0])

    def prepare(self) -> tuple[int, dict]:
        return self.call("prepare", "--repo-root", str(self.fixture.root), "--issue", str(ISSUE),
                         "--repo", SLUG)

    def worktree(self) -> Path:
        """Add the issue's worktree on its branch from `origin/main`."""
        with mock.patch.dict(os.environ, self.env):
            place = landing.placement(str(self.fixture.root), ISSUE)
        self.world.git(self.fixture.root, "worktree", "add", "--no-track", "-b", place["branch"],
                       place["worktree_path"], "origin/main")
        return Path(place["worktree_path"])

    def commit(self, root: Path, name: str) -> str:
        (root / name).write_text(f"{name}\n", encoding="utf-8")
        self.world.git(root, "add", name)
        self.world.git(root, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                       "commit", "--quiet", "-m", name)
        return self.world.git(root, "rev-parse", "HEAD").strip()


def lock_main(test: unittest.TestCase, *args: str) -> tuple[int, dict]:
    """`landing.main(args)` with its one JSON line parsed: (exit status, answer)."""
    out = StringIO()
    with redirect_stdout(out):
        status = landing.main(list(args))
    lines = out.getvalue().splitlines()
    test.assertEqual(len(lines), 1, out.getvalue())
    return status, json.loads(lines[0])


def register_lock(forge: ForgeWorld, lock: str | None, pulls: dict[str, int] | None, **store) -> None:
    """Serve the land lock of `main` at `lock` and the open pull request of each head sha from `forge`."""
    forge.ref_store(SLUG, {LOCK_REF: lock} if lock else {}, **store)
    stamp = format_datetime(datetime(2026, 11, 6, 10, tzinfo=timezone.utc), usegmt=True)
    forge.respond("gh", FORGE_NOW, stdout=f"HTTP/2.0 200 OK\ndate: {stamp}\n\n{{}}")
    repo = {"full_name": SLUG}
    for sha in (SHA, OTHER):
        number = (pulls or {}).get(sha)
        forge.respond_json("gh", ["api", f"repos/{SLUG}/commits/{sha}/pulls?per_page=100"], [] if number is None else [
            {"number": number, "state": "open", "merged_at": None,
             "base": {"ref": "main", "repo": repo},
             "head": {"ref": f"issue-{number}-add-a-greeting", "sha": sha, "repo": repo}}])
    for number in set((pulls or {}).values()):  # the holder is read from the issues it closes
        forge.respond_json("gh", ["api", "graphql", "-f", f"query={forge_markers.CLOSING_ISSUES}",
                                  "-f", "owner=example", "-f", "name=fixture", "-F", f"number={number}"],
                           {"data": {"repository": {"pullRequest": {"closingIssuesReferences": {"nodes": []}}}}})
    forge.respond_json("gh", ["api", f"repos/{SLUG}/pulls?state=open&base=main&sort=updated"
                                     "&direction=desc&per_page=100&page=1"], [])


class LockTest(unittest.TestCase):
    """`lock`, `held` and `unlock` against the fake forge's ref store, answered in this process."""

    def world(self, lock: str | None = None, *, pulls: dict[str, int] | None = None, **store) -> ForgeWorld:
        """The fake forge: the land lock of `main` at `lock` and the open pull request of each head sha."""
        forge = ForgeWorld(self)
        forge.answer_in_process(forge_api)
        register_lock(forge, lock, pulls, **store)
        return forge

    def call(self, verb: str, sha: str = SHA) -> tuple[int, dict]:
        return lock_main(self, verb, "--repo", SLUG, "--integration-branch", "main", "--head", sha)

    def test_lock_held_and_unlock_take_and_release_the_land_lock_at_the_head(self):
        forge = self.world(pulls={SHA: 7})
        status, taken = self.call("lock")
        self.assertEqual((status, taken["verdict"], taken["lock"]["verdict"]), (0, "held", "acquired"), taken)
        self.assertEqual(forge.refs()[LOCK_REF], SHA)
        status, kept = self.call("held")
        self.assertEqual((status, kept["verdict"]), (0, "held"), kept)
        status, freed = self.call("unlock")
        self.assertEqual((status, freed["verdict"]), (0, "released"), freed)
        self.assertNotIn(LOCK_REF, forge.refs())

    def test_held_answers_retaken_when_the_lock_was_lost_and_taken_again(self):
        forge = self.world(pulls={SHA: 7})
        status, answer = self.call("held")
        self.assertEqual((status, answer["verdict"]), (0, "retaken"), answer)
        self.assertEqual(forge.refs()[LOCK_REF], SHA)

    def test_unlock_reports_an_unreleased_lock_when_the_release_fails(self):
        forge = self.world(SHA, pulls={SHA: 7}, refuse_to=["0" * 40])
        status, answer = self.call("unlock")
        self.assertEqual((status, answer["verdict"]), (0, "unreleased"), answer)
        self.assertTrue(answer["detail"])
        self.assertEqual(forge.refs()[LOCK_REF], SHA)

    def test_held_and_lock_answer_no_pull_when_no_open_pull_request_is_headed_at_the_sha(self):
        forge = self.world(SHA)
        status, answer = self.call("held")
        self.assertEqual((status, answer["verdict"]), (0, "no-pull"), answer)
        self.assertEqual(forge.refs()[LOCK_REF], SHA)
        forge = self.world()
        with mock.patch.object(forge_land_lock, "BOUND", 0), mock.patch.object(forge_land_lock, "sleep"):
            status, answer = self.call("lock")
        self.assertEqual((status, answer["verdict"]), (0, "no-pull"), answer)
        self.assertEqual(forge.refs(), {})

    def test_unlock_of_a_lock_another_pull_request_holds_answers_released_and_leaves_its_ref(self):
        forge = self.world(OTHER, pulls={SHA: 7, OTHER: 8})
        status, answer = self.call("unlock")
        self.assertEqual((status, answer["verdict"]), (0, "released"), answer)
        self.assertEqual(answer["lock"]["verdict"], "not_held")
        self.assertEqual(forge.refs()[LOCK_REF], OTHER)

    def test_lock_held_by_another_open_pull_request_is_contended_past_the_wait(self):
        forge = self.world(OTHER, pulls={SHA: 7, OTHER: 8})
        with mock.patch.object(forge_land_lock, "BOUND", 0), mock.patch.object(forge_land_lock, "sleep"):
            status, answer = self.call("lock")
        self.assertEqual((status, answer["verdict"]), (0, "contended"), answer)
        self.assertEqual(forge.refs()[LOCK_REF], OTHER)

    def test_lock_waits_for_the_holder_and_takes_the_lock_once_it_is_released(self):
        forge = self.world(OTHER, pulls={SHA: 7, OTHER: 8})
        with mock.patch.object(forge_land_lock, "sleep", lambda _: forge.set_ref(LOCK_REF, None)):
            status, answer = self.call("lock")
        self.assertEqual((status, answer["verdict"], answer["lock"]["verdict"]), (0, "held", "acquired"), answer)
        self.assertEqual(forge.refs()[LOCK_REF], SHA)


class NoDeclaredChecks(FixtureProject):
    """A fixture whose contract declares no required check (the member is absent, never `[]`)."""

    def _draft(self) -> dict:
        draft = super()._draft()
        del draft["bindings"]["vcs"]["merge"]["required_checks"]
        return draft


def check_run(name: str, status: str = "COMPLETED", conclusion: str | None = "SUCCESS") -> dict:
    return {"__typename": "CheckRun", "name": name, "status": status, "conclusion": conclusion}


def stamped(entry: dict, clock: str, workflow: str = "Fixture", started: str | None = None) -> dict:
    """The entry as the rollup carries it: `startedAt` (`clock` on 2026-11-06 unless `started`) and `workflowName`."""
    return {**entry, "startedAt": started or f"2026-11-06T{clock}Z", "workflowName": workflow}


def status_context(name: str, state: str) -> dict:
    return {"__typename": "StatusContext", "context": name, "state": state}


class ChecksTest(unittest.TestCase):
    def read(self, land: LandingWorld, rollup: list, head: str = SHA) -> None:
        land.forge.respond_json("gh", CHECKS_VIEW, {"headRefOid": head, "statusCheckRollup": rollup})

    def checks(self, land: LandingWorld) -> tuple[int, dict]:
        args = ("checks", "--repo-root", str(land.fixture.root), "--repo", SLUG, "--pr", "7", "--head", SHA)
        with mock.patch.dict(os.environ, land.env), mock.patch.object(landing, "CHECK_BOUND_SECONDS", 90), \
                mock.patch.object(landing, "sleep"), mock.patch.object(landing, "monotonic", land.clock):
            return lock_main(self, *args)

    def world(self, project: type[FixtureProject] = FixtureProject) -> LandingWorld:
        land = LandingWorld(self, project=project)
        now = [0.0]
        land.clock = lambda: now.__setitem__(0, now[0] + 31) or now[0]  # every read moves a poll on
        return land

    def test_checks_green_only_when_every_declared_check_is_green(self):
        land = self.world()
        rows = (("green", [check_run("Fixture Checks")], "green", None),
                ("missing", [check_run("CI")], "pending", None),
                ("red", [check_run("Fixture Checks", conclusion="FAILURE"), check_run("CI")], "red",
                 ["Fixture Checks"]),
                ("one red of two runs", [check_run("Fixture Checks"),
                                         check_run("Fixture Checks", conclusion="FAILURE")], "red",
                 ["Fixture Checks"]),
                ("re-run green", [stamped(check_run("Fixture Checks", conclusion="FAILURE"), "10:00:00"),
                                  stamped(check_run("Fixture Checks"), "10:05:00")], "green", None),
                ("re-run red", [stamped(check_run("Fixture Checks"), "10:00:00"),
                                stamped(check_run("Fixture Checks", conclusion="FAILURE"), "10:05:00")],
                 "red", ["Fixture Checks"]),
                ("tie stays judged", [stamped(check_run("Fixture Checks", conclusion="FAILURE"), "10:00:00"),
                                      stamped(check_run("Fixture Checks"), "10:00:00")], "red",
                 ["Fixture Checks"]),
                ("another workflow's red stays", [
                    stamped(check_run("Fixture Checks", conclusion="FAILURE"), "10:00:00", "Other"),
                    stamped(check_run("Fixture Checks"), "10:05:00")], "red", ["Fixture Checks"]),
                ("unreadable start stays", [stamped(check_run("Fixture Checks", conclusion="FAILURE"),
                                                    "10:00:00", started="0001-01-01T00:00:00Z"),
                                            stamped(check_run("Fixture Checks"), "10:05:00")], "red",
                 ["Fixture Checks"]),
                ("running", [check_run("Fixture Checks", status="IN_PROGRESS", conclusion=None)], "pending",
                 None),
                ("skipped", [check_run("Fixture Checks", conclusion="SKIPPED")], "green", None))
        for name, rollup, want, failing in rows:
            with self.subTest(name):
                self.read(land, rollup)
                status, answer = self.checks(land)
                self.assertEqual((status, answer["verdict"]), (0, want), answer)
                if failing is not None:
                    self.assertEqual(answer["failing"], failing)

    def test_checks_with_no_declared_check_need_every_entry_green(self):
        land = self.world(NoDeclaredChecks)
        with mock.patch.dict(os.environ, land.env):
            snapshot = resolve_project.resolve(str(land.fixture.root))
        self.assertNotIn("required_checks", snapshot["bindings"]["vcs"]["merge"])
        rows = (("empty", [], "pending"),
                ("one green", [check_run("CI")], "green"),
                ("green status", [status_context("ci/x", "SUCCESS")], "green"),
                ("one red", [check_run("CI"), status_context("ci/x", "FAILURE")], "red"),
                ("one running", [check_run("CI"), check_run("Lint", status="QUEUED", conclusion=None)],
                 "pending"))
        for name, rollup, want in rows:
            with self.subTest(name):
                self.read(land, rollup)
                status, answer = self.checks(land)
                self.assertEqual((status, answer["verdict"]), (0, want), answer)
        self.read(land, [check_run("CI"), status_context("ci/x", "FAILURE")])
        self.assertEqual(self.checks(land)[1]["failing"], ["ci/x"])

    def test_checks_answers_moved_for_a_rollup_of_another_head(self):
        land = self.world()
        self.read(land, [check_run("Fixture Checks")], head=OTHER)
        status, answer = self.checks(land)
        self.assertEqual((status, answer["verdict"], answer["remote"]), (0, "moved", OTHER), answer)

    def test_checks_polls_a_pending_rollup_until_it_turns_green(self):
        land = self.world()
        self.read(land, [check_run("Fixture Checks", status="IN_PROGRESS", conclusion=None)])
        green = [check_run("Fixture Checks")]
        args = ("checks", "--repo-root", str(land.fixture.root), "--repo", SLUG, "--pr", "7", "--head", SHA)
        with mock.patch.dict(os.environ, land.env), mock.patch.object(landing, "monotonic", land.clock), \
                mock.patch.object(landing, "sleep", lambda _: self.read(land, green)):
            status, answer = lock_main(self, *args)
        self.assertEqual((status, answer["verdict"]), (0, "green"), answer)
        reads = [argv for argv in land.forge.argvs("gh") if argv == CHECKS_VIEW]
        self.assertEqual(len(reads), 2)


class PrepareTest(unittest.TestCase):
    def test_prepare_answers_ready_with_the_verified_head_only_for_the_recorded_tree(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            status, verified = verified_tree.run(worktree)
        self.assertEqual((status, verified["verdict"]), (0, "passed"), verified)
        code, ready = land.prepare()
        self.assertEqual((code, ready["verdict"]), (0, "ready"), ready)
        self.assertEqual(ready["head"], land.world.git(worktree, "rev-parse", "HEAD").strip())
        self.assertIs(ready["closes"], True)
        self.assertEqual(ready["body"], "Closes #41. Delivered by the engine.")
        self.assertEqual((ready["integration_branch"], ready["title"]), ("main", "Add a greeting"))
        land.commit(worktree, "more.txt")
        code, moved = land.prepare()
        self.assertEqual((code, moved["verdict"]), (0, "unverified"), moved)

    def test_prepare_is_unverified_for_a_dirty_worktree_of_the_recorded_tree(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            verified_tree.run(worktree)
        (worktree / "stray.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(land.prepare()[1]["verdict"], "unverified")

    def test_prepare_ignores_git_variables_naming_another_repository(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        land.commit(worktree, "unverified.txt")
        other = land.fixture.root
        with mock.patch.dict(os.environ, land.env):
            tree = verified_tree.current_tree(other)
            record = verified_tree.record_path(other)
        record.write_text(json.dumps({"schema": verified_tree.SCHEMA, "tree": tree,
                                      "verification": ["x"]}) + "\n", encoding="utf-8")
        land.env = {**land.env, "GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
        code, answer = land.prepare()
        self.assertEqual((code, answer["verdict"]), (0, "unverified"), answer)
        self.assertEqual(answer["head"], land.world.git(worktree, "rev-parse", "HEAD").strip())

    def test_the_criteria_close_only_when_every_open_criterion_is_code(self):
        rows = {
            "all code": (criteria("- [ ] [code] a", "- [x] [code] b"), True),
            "code and note": (criteria("- [ ] [code] a", "- [ ] [note] b"), True),
            "one evidence": (criteria("- [ ] [code] a", "- [ ] [evidence] b"), False),
            "one human": (criteria("- [ ] [code] a", "- [ ] [human] b"), False),
            "one untagged": (criteria("- [ ] [code] a", "- [ ] b"), False),
            "star bullet human": (criteria("- [ ] [code] a", "* [ ] [human] b"), False),
            "plus bullet evidence": (criteria("- [ ] [code] a", "+ [ ] [evidence] b"), False),
            "star bullet code": (criteria("* [ ] [code] a", "+ [x] [note] b"), True),
            "no section": ("Intro.\n\n- [ ] [code] a\n", False),
            "no criterion line": (criteria("prose only"), False),
        }
        for name, (body, want) in rows.items():
            with self.subTest(name):
                self.assertIs(landing.criteria_close(body), want)

    def test_the_title_and_body_hold_no_shell_active_character(self):
        land = LandingWorld(self, title="Say \"hi\" to $USER `now`! \\ ok\n  again")
        worktree = land.worktree()
        with mock.patch.dict(os.environ, land.env):
            verified_tree.run(worktree)
        _, ready = land.prepare()
        self.assertEqual(ready["title"], "Say hi to USER now ok again")
        argv = ["gh", "pr", "create", "--repo", SLUG, "--base", "main", "--head", ready["branch"],
                "--title", ready["title"], "--body", ready["body"]]
        self.assertEqual(shlex.split(engine_commands.command_text(argv)), argv)


class PushedTest(unittest.TestCase):
    def test_pushed_compares_origins_branch_with_the_head(self):
        land = LandingWorld(self)
        root = land.fixture.root
        land.world.git(root, "branch", "issue-41-x", "main")
        land.world.git(root, "push", "--quiet", "origin", "issue-41-x")
        head = land.world.git(root, "rev-parse", "issue-41-x").strip()

        def pushed(branch: str, sha: str) -> tuple[int, dict]:
            return land.call("pushed", "--repo-root", str(root), "--branch", branch, "--head", sha)

        self.assertEqual(pushed("issue-41-x", head), (0, {"verdict": "pushed"}))
        remote = land.world.advance(root, "issue-41-x")
        self.assertEqual(pushed("issue-41-x", head), (0, {"verdict": "head-moved", "remote": remote}))
        self.assertEqual(pushed("issue-41-absent", head), (0, {"verdict": "absent"}))


class PullTest(unittest.TestCase):
    def test_pull_finds_the_one_open_pull_request_into_the_integration_branch(self):
        forge = ForgeWorld(self)
        entry = {"number": 7, "headRefOid": SHA, "baseRefName": "main", "url": "https://x/pull/7"}
        args = ("pull", "--repo", SLUG, "--branch", "issue-41-x", "--integration-branch", "main")
        for name, listing, want in (
                ("one", [entry], {"verdict": "open", "pr": 7, "head": SHA, "url": "https://x/pull/7"}),
                ("none", [], {"verdict": "absent"}),
                ("another base", [{**entry, "baseRefName": "release"}], {"verdict": "absent"})):
            with self.subTest(name):
                forge.respond_json("gh", PULL_LIST, listing)
                out = StringIO()
                with redirect_stdout(out):
                    status = landing.main(list(args))
                self.assertEqual((status, json.loads(out.getvalue())), (0, want))
        forge.respond_json("gh", PULL_LIST, [entry, {**entry, "number": 8}])
        out = StringIO()
        with redirect_stdout(out):
            status = landing.main(list(args))
        self.assertEqual((status, json.loads(out.getvalue())["verdict"]), (1, "error"))


class MergedTest(unittest.TestCase):
    def test_merged_reads_the_merge_commit(self):
        forge = ForgeWorld(self)
        args = ("merged", "--repo", SLUG, "--pr", "7", "--head", SHA)
        for name, view, want in (
                ("merged", {"state": "MERGED", "headRefOid": SHA, "mergeCommit": {"oid": OTHER}},
                 {"verdict": "merged", "merge_commit": OTHER, "head": SHA}),
                ("open", {"state": "OPEN", "headRefOid": SHA, "mergeCommit": None},
                 {"verdict": "open", "head": SHA})):
            with self.subTest(name):
                forge.respond_json("gh", PULL_VIEW, view)
                out = StringIO()
                with redirect_stdout(out):
                    status = landing.main(list(args))
                self.assertEqual((status, json.loads(out.getvalue())), (0, want))


class TallyCommandTest(LedgerMaker, unittest.TestCase):
    """`pending`, `red`, `lock-budget` and `sync-fixes` answer from the delivery's run ledger."""

    def world(self) -> tuple[LandingWorld, str, Path]:
        """A landing world, the holder of a delivery two attempts deep and its current attempt run."""
        land = LandingWorld(self)
        self.use_home(Path(land.env["HOME"]))
        return land, *self.holder()

    def holder(self) -> tuple[str, Path]:
        root, _, _, _, current = self.delivery()
        return f"host-a/{root.name}", current

    def test_pending_answers_spent_on_the_third_pending_read_of_the_current_attempt(self):
        land, holder, attempt = self.world()
        self.visit(attempt, "gate", 1, "pending", {"verdict": "pending"})
        self.visit(attempt, "gate", 2, "pending", {"verdict": "pending"})
        self.assertEqual(land.call("pending", "--holder", holder), (0, {"verdict": "wait"}))
        self.visit(attempt, "gate", 3, "pending", {"verdict": "pending"})
        self.assertEqual(land.call("pending", "--holder", holder), (0, {"verdict": "spent"}))

    def test_red_answers_presync_behind_without_the_lock_sync_behind_with_it_and_carries_the_failing_names(self):
        land = LandingWorld(self)
        self.use_home(Path(land.env["HOME"]))
        worktree = land.worktree()
        land.world.advance(land.fixture.root, "main")
        red = {"verdict": "red", "failing": ["Fixture Checks"]}
        for name, held, want in (("without the lock", False, "presync"), ("with the lock", True, "sync")):
            with self.subTest(name):
                root, _, _, _, attempt = self.delivery()
                if held:
                    self.visit(attempt, "lock", 1, "held", {"verdict": "held"})
                self.visit(attempt, "gate", 1, "red", red)
                status, answer = land.call("red", "--holder", f"host-a/{root.name}", "--worktree-path",
                                           str(worktree), "--integration-branch", "main")
                self.assertEqual((status, answer["verdict"]), (0, want), answer)
                self.assertEqual(answer["failing"], ["Fixture Checks"])
                self.assertIs(answer["behind"], True)

    def test_red_answers_fix_with_no_earlier_fix_and_checks_after_one_in_an_earlier_attempt(self):
        land = LandingWorld(self)
        self.use_home(Path(land.env["HOME"]))
        worktree = land.worktree()
        root, _, first, _, attempt = self.delivery()
        self.visit(attempt, "gate", 1, "red", {"verdict": "red", "failing": ["Fixture Checks"]})
        args = ("red", "--holder", f"host-a/{root.name}", "--worktree-path", str(worktree),
                "--integration-branch", "main")
        status, answer = land.call(*args)
        self.assertEqual((status, answer["verdict"], answer["behind"]), (0, "fix", False), answer)
        self.enter(first, "ci-fix")
        self.assertEqual(land.call(*args)[1]["verdict"], "checks")
        self.visit(attempt, "ci-fixed", 1, "unchanged", {})
        self.visit(attempt, "gate", 2, "pending", {"verdict": "pending"})
        self.visit(attempt, "gate", 3, "red", {"verdict": "red", "failing": ["Fixture Checks"]})
        self.assertEqual(land.call(*args)[1]["verdict"], "stale")

    def test_lock_budget_and_sync_fixes_answer_from_the_ledger(self):
        land, holder, attempt = self.world()
        for visit in (1, 2, 3):
            self.visit(attempt, "lock", visit, "contended", {"verdict": "contended", "lock": answer(2)})
        self.assertEqual(land.call("lock-budget", "--holder", holder), (0, {"verdict": "again", "waits": 3}))
        self.visit(attempt, "lock", 4, "contended", {"verdict": "contended", "lock": answer(2)})
        self.assertEqual(land.call("lock-budget", "--holder", holder), (0, {"verdict": "spent", "waits": 4}))
        self.assertEqual(land.call("sync-fixes", "--holder", holder), (0, {"verdict": "fix"}))
        self.enter(attempt, "merge-fix")
        self.assertEqual(land.call("sync-fixes", "--holder", holder), (0, {"verdict": "spent"}))

    def test_a_holder_without_a_run_is_an_error(self):
        land, _, _ = self.world()
        status, answer = land.call("pending", "--holder", "host-a/9-20261124T090000Z-zzzz")
        self.assertEqual((status, answer["verdict"], answer["error"]), (1, "error", "no_run"))


class ReleaseTest(LedgerMaker, unittest.TestCase):
    """`free` and `release` free the land lock only at a sha the landing's lock steps held."""

    def world(self, lock: str) -> tuple[LandingWorld, str, Path]:
        land = LandingWorld(self)
        self.use_home(Path(land.env["HOME"]))
        register_lock(land.forge, lock, {SHA: 7, OTHER: 8})
        root, _, _, _, attempt = self.delivery()
        self.visit(attempt, "lock", 1, "held", {"verdict": "held", "lock": {"lock_sha": SHA}})
        return land, f"host-a/{root.name}", attempt

    def free(self, land: LandingWorld, holder: str) -> tuple[int, dict]:
        return land.call("free", "--repo", SLUG, "--integration-branch", "main", "--holder", holder)

    def test_free_releases_the_lock_only_at_a_sha_this_landing_held(self):
        land, holder, _ = self.world(SHA)
        status, answer = self.free(land, holder)
        self.assertEqual((status, answer["verdict"]), (0, "released"), answer)
        self.assertNotIn(LOCK_REF, land.forge.refs())
        land, holder, _ = self.world(OTHER)
        status, answer = self.free(land, holder)
        self.assertEqual((status, answer["verdict"]), (0, "released"), answer)
        self.assertEqual(land.forge.refs()[LOCK_REF], OTHER)

    def test_release_answers_the_attempt_end_once_the_lock_is_free(self):
        land, holder, attempt = self.world(SHA)
        items = json.dumps([{"end": "checks", "item": None, "run": attempt.name}])
        status, answer = land.call("release", "--repo-root", str(land.fixture.root), "--issue", str(ISSUE),
                                   "--repo", SLUG, "--holder", holder, "--items", items)
        self.assertEqual((status, answer["verdict"]), (0, "checks"), answer)
        self.assertNotIn(LOCK_REF, land.forge.refs())

    def test_a_failed_release_answers_unreleased(self):
        land, holder, attempt = self.world(SHA)
        land.forge.ref_store(SLUG, {LOCK_REF: SHA}, refuse_to=["0" * 40])
        items = json.dumps([{"end": "checks", "item": None, "run": attempt.name}])
        status, answer = land.call("release", "--repo-root", str(land.fixture.root), "--issue", str(ISSUE),
                                   "--repo", SLUG, "--holder", holder, "--items", items)
        self.assertEqual((status, answer["verdict"]), (0, "unreleased"), answer)
        self.assertEqual(land.forge.refs()[LOCK_REF], SHA)


def publish(land: LandingWorld, name: str, text: str) -> str:
    """Push a commit of `name` holding `text` onto origin's `main` from another clone; return its id."""
    git = land.world.git
    bare = git(land.fixture.root, "remote", "get-url", "origin").strip()
    other = land.world.tmp / f"publisher-{len(os.listdir(land.world.tmp))}"
    git(land.world.tmp, "clone", "--quiet", "--branch", "main", bare, str(other))
    (other / name).parent.mkdir(parents=True, exist_ok=True)
    (other / name).write_text(text, encoding="utf-8")
    git(other, "add", name)
    git(other, "commit", "--quiet", "-m", f"publish {name}")
    git(other, "push", "--quiet", "origin", "HEAD:refs/heads/main")
    return git(other, "rev-parse", "HEAD").strip()


def commit_text(land: LandingWorld, root: Path, name: str, text: str) -> str:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")
    land.world.git(root, "add", name)
    land.world.git(root, "commit", "--quiet", "-m", f"commit {name}")
    return land.world.git(root, "rev-parse", "HEAD").strip()


class HeadTest(unittest.TestCase):
    def test_head_answers_clean_with_the_head_and_dirty_for_an_untracked_file(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        head = land.world.git(worktree, "rev-parse", "HEAD").strip()
        args = ("head", "--worktree-path", str(worktree))
        self.assertEqual(land.call(*args), (0, {"verdict": "clean", "head": head}))
        (worktree / "stray.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(land.call(*args), (0, {"verdict": "dirty", "head": head}))


class ProbeTest(unittest.TestCase):
    def probe(self, land: LandingWorld, worktree: Path, branch: str = "main") -> tuple[int, dict]:
        return land.call("probe", "--worktree-path", str(worktree), "--integration-branch", branch)

    def test_probe_answers_conflicted_with_the_files_when_the_base_changed_the_same_lines(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        commit_text(land, worktree, "fixture/farewell.py", "one\n")
        publish(land, "fixture/farewell.py", "two\n")
        status, answer = self.probe(land, worktree)
        self.assertEqual((status, answer), (0, {"verdict": "conflicted", "files": ["fixture/farewell.py"]}))
        self.assertEqual(land.world.git(worktree, "status", "--porcelain"), "")

    def test_probe_answers_clean_when_up_to_date_and_behind_when_main_moved_without_a_conflict(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        commit_text(land, worktree, "mine.txt", "mine\n")
        self.assertEqual(self.probe(land, worktree), (0, {"verdict": "clean", "files": []}))
        publish(land, "theirs.txt", "theirs\n")
        self.assertEqual(self.probe(land, worktree), (0, {"verdict": "behind", "files": []}))
        self.assertEqual(land.world.git(worktree, "status", "--porcelain"), "")

    def test_probe_answers_error_for_a_missing_integration_branch(self):
        land = LandingWorld(self)
        status, answer = self.probe(land, land.worktree(), "absent")
        self.assertEqual((status, answer["verdict"], answer["error"]), (1, "error", "probe_failed"), answer)


class MergeOfTest(unittest.TestCase):
    def merge_of(self, land: LandingWorld, worktree: Path) -> tuple[int, dict]:
        return land.call("merge-of", "--worktree-path", str(worktree), "--integration-branch", "main")

    def moved(self, land: LandingWorld) -> Path:
        """A worktree with one commit of its own and a fetched `origin/main` that moved on."""
        worktree = land.worktree()
        commit_text(land, worktree, "mine.txt", "mine\n")
        publish(land, "theirs.txt", "theirs\n")
        land.world.git(worktree, "fetch", "--quiet", "origin")
        return worktree

    def head(self, land: LandingWorld, worktree: Path) -> str:
        return land.world.git(worktree, "rev-parse", "HEAD").strip()

    def test_a_clean_merge_of_main_at_head_answers_clean(self):
        land = LandingWorld(self)
        worktree = self.moved(land)
        land.world.git(worktree, "merge", "--quiet", "--no-edit", "origin/main")
        head = self.head(land, worktree)
        self.assertEqual(self.merge_of(land, worktree), (0, {"verdict": "clean", "merge_commit": head, "head": head}))

    def test_a_conflicted_merge_answers_review_with_its_merge_commit(self):
        land = LandingWorld(self)
        worktree = land.worktree()
        commit_text(land, worktree, "fixture/farewell.py", "one\n")
        publish(land, "fixture/farewell.py", "two\n")
        land.world.git(worktree, "fetch", "--quiet", "origin")
        with self.assertRaises(Exception):
            land.world.git(worktree, "merge", "--no-edit", "origin/main")
        commit_text(land, worktree, "fixture/farewell.py", "resolved\n")
        head = self.head(land, worktree)
        self.assertEqual(self.merge_of(land, worktree), (0, {"verdict": "review", "merge_commit": head, "head": head}))

    def test_an_evil_merge_answers_review(self):
        land = LandingWorld(self)
        worktree = self.moved(land)
        land.world.git(worktree, "merge", "--quiet", "--no-commit", "--no-ff", "origin/main")
        commit_text(land, worktree, "extra.txt", "snuck in\n")
        head = self.head(land, worktree)
        self.assertEqual(self.merge_of(land, worktree), (0, {"verdict": "review", "merge_commit": head, "head": head}))

    def test_plain_commits_on_top_of_the_merge_answer_review_with_the_head(self):
        land = LandingWorld(self)
        worktree = self.moved(land)
        land.world.git(worktree, "merge", "--quiet", "--no-edit", "origin/main")
        merge = self.head(land, worktree)
        top = commit_text(land, worktree, "more.txt", "more\n")
        self.assertEqual(self.merge_of(land, worktree), (0, {"verdict": "review", "merge_commit": merge, "head": top}))

    def test_a_head_with_no_merge_of_the_moved_main_answers_none(self):
        land = LandingWorld(self)
        worktree = self.moved(land)
        head = self.head(land, worktree)
        self.assertEqual(self.merge_of(land, worktree), (0, {"verdict": "none", "merge_commit": "", "head": head}))
        land.world.git(worktree, "merge", "--quiet", "--no-edit", "origin/main")
        publish(land, "later.txt", "later\n")
        land.world.git(worktree, "fetch", "--quiet", "origin")
        verdict = self.merge_of(land, worktree)[1]
        self.assertEqual((verdict["verdict"], verdict["merge_commit"]), ("none", ""))


class FixedTest(unittest.TestCase):
    def test_each_reply_reads_its_verdict(self):
        tests = json.dumps(["python3 -m unittest"])
        rows = (("committed", "done", SHA, OTHER, tests, "", "committed"),
                ("committed with no test", "done", SHA, OTHER, "[]", "", "untested"),
                ("committed with tests not json", "done", SHA, OTHER, "not json", "", "untested"),
                ("committed with tests not strings", "done", SHA, OTHER, "[1]", "", "untested"),
                ("untested before not-done", "blocked", SHA, OTHER, "[]", "", "untested"),
                ("blocked", "blocked", SHA, OTHER, tests, "", "not-done"),
                ("started elsewhere", "done", OTHER, SHA, tests, "", "not-done"),
                ("no commit", "done", SHA, "", tests, "", "not-done"),
                ("unchanged", "done", SHA, SHA, "[]", "already fine", "unchanged"),
                ("silent", "done", SHA, SHA, "[]", "  ", "silent"))
        for name, status, start, commit, given, notes, want in rows:
            with self.subTest(name):
                answer = lock_main(self, "fixed", "--status", status, "--start-head", start, "--commit", commit,
                                   "--tests", given, "--notes", notes, "--head", SHA)
                self.assertEqual(answer, (0, {"verdict": want}))


class MergeStateTest(unittest.TestCase):
    def test_behind_blocked_and_any_other_state_read_their_verdicts(self):
        forge = ForgeWorld(self)
        view = ["pr", "view", "7", "--repo", SLUG, "--json", "mergeStateStatus"]
        for state, want in (("BEHIND", "behind"), ("BLOCKED", "blocked"), ("CLEAN", "other"), ("UNKNOWN", "other")):
            with self.subTest(state):
                forge.respond_json("gh", view, {"mergeStateStatus": state})
                self.assertEqual(lock_main(self, "merge-state", "--repo", SLUG, "--pr", "7"),
                                 (0, {"verdict": want, "state": state}))
        for name, payload in (("missing", {}), ("not a string", {"mergeStateStatus": 3})):
            with self.subTest(name):
                forge.respond_json("gh", view, payload)
                status, answer = lock_main(self, "merge-state", "--repo", SLUG, "--pr", "7")
                self.assertEqual((status, answer["verdict"]), (1, "error"), answer)


class PrHeadTest(unittest.TestCase):
    def test_pr_head_compares_the_pull_requests_head_with_the_expected_one(self):
        forge = ForgeWorld(self)
        view = ["pr", "view", "7", "--repo", SLUG, "--json", "headRefOid"]
        args = ("pr-head", "--repo", SLUG, "--pr", "7", "--head", SHA)
        forge.respond_json("gh", view, {"headRefOid": SHA})
        self.assertEqual(lock_main(self, *args), (0, {"verdict": "pushed", "remote": SHA}))
        forge.respond_json("gh", view, {"headRefOid": OTHER})
        self.assertEqual(lock_main(self, *args), (0, {"verdict": "head-moved", "remote": OTHER}))
        forge.respond_json("gh", view, {})
        status, answer = lock_main(self, *args)
        self.assertEqual((status, answer["verdict"]), (1, "error"), answer)


class BoundSeamTest(unittest.TestCase):
    def setUp(self):
        for module, name in ((landing, "CHECK_BOUND_SECONDS"), (forge_land_lock, "BOUND")):
            patcher = mock.patch.object(module, name, getattr(module, name))
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_zero_bound_answers_a_pending_rollup_after_one_read(self):
        land = LandingWorld(self)
        land.forge.respond_json("gh", CHECKS_VIEW, {"headRefOid": SHA, "statusCheckRollup": []})
        with mock.patch.dict(os.environ, {**land.env, "LANDING_BOUND_SECONDS": "0"}), \
                mock.patch.object(landing, "sleep", side_effect=AssertionError("slept")):
            status, answer = lock_main(self, "checks", "--repo-root", str(land.fixture.root), "--repo", SLUG,
                                       "--pr", "7", "--head", SHA)
        self.assertEqual((status, answer["verdict"]), (0, "pending"), answer)
        self.assertEqual(sum(argv == CHECKS_VIEW for argv in land.forge.argvs("gh")), 1)

    def test_a_zero_bound_answers_a_lock_another_pull_request_holds_as_contended_without_sleeping(self):
        forge = ForgeWorld(self)
        forge.answer_in_process(forge_api)
        register_lock(forge, OTHER, {SHA: 7, OTHER: 8})
        with mock.patch.dict(os.environ, {"LANDING_BOUND_SECONDS": "0"}), \
                mock.patch.object(forge_land_lock, "sleep", side_effect=AssertionError("slept")):
            status, answer = lock_main(self, "lock", "--repo", SLUG, "--integration-branch", "main", "--head", SHA)
        self.assertEqual((status, answer["verdict"]), (0, "contended"), answer)

    def test_a_bound_that_is_not_a_number_is_ignored(self):
        land = LandingWorld(self)
        land.forge.respond_json("gh", ["pr", "view", "7", "--repo", SLUG, "--json", "mergeStateStatus"],
                                {"mergeStateStatus": "CLEAN"})
        for text in ("soon", "-1", "1.5", ""):
            with self.subTest(text), mock.patch.dict(os.environ, {"LANDING_BOUND_SECONDS": text}):
                lock_main(self, "merge-state", "--repo", SLUG, "--pr", "7")
                self.assertEqual((landing.CHECK_BOUND_SECONDS, forge_land_lock.BOUND), (3000, 3000))


if __name__ == "__main__":
    unittest.main()
