"""The verify scripts that read the landings of a host after its deployment.

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import unittest
from unittest import mock
from urllib.parse import parse_qs, urlsplit

from agent_tools.claims import forge_markers as fm
from agent_tools.claims import landing_reading
from agent_tools.delivery import look_marker as lm
from tests.test_verify_checks import committed_mode

TIER = "fast"
SCRIPTS = ("home/common/verify-pending/checks/land-queue-syncs",
           "home/common/verify-pending/checks/land-queue-ci-runs")
SLUG = "o/r"
HOST = "eleven-m5"
DEPLOYED = "2026-11-20T10:00:00Z"
BEFORE = "2026-11-20T09:00:00Z"


def sha(tag, n=0):
    return (tag + f"{n:02d}").ljust(40, "0")


class World:
    """A stand-in forge: the default branch, the closed pulls, the issues' comments, the commits."""

    def __init__(self, deployed=DEPLOYED):
        self.pulls, self.comments, self.commits, self.runs, self.attempts = [], {}, {}, {}, {}
        self.closing, self.next_id = {}, 100
        self.reads = []
        self.comment(1679, fm.render("verify-due", {"block": "b", "check": "c", "host": HOST}, "Due."),
                     deployed)

    def comment(self, issue, body, at, association="OWNER"):
        self.next_id += 1
        self.comments.setdefault(issue, []).append(
            {"id": self.next_id, "body": body, "created_at": at, "updated_at": at,
             "author_association": association})

    def landing(self, pr, *, holder=f"{HOST}/session-x", approvals=((None, "2026-11-20T11:00:00Z"),),
                merged_at="2026-11-20T12:00:00Z", created_at="2026-11-20T10:30:00Z",
                head=None, indirect=False):
        """Pull request `pr` closing issue `pr`; `approvals` are (head, created_at) pairs."""
        branch = f"issue-{pr}-x"
        head = head or sha("1", pr % 100)
        self.closing[pr] = [pr]
        self.pulls.append({"number": pr, "merged_at": merged_at, "created_at": created_at,
                           "merge_commit_sha": head if indirect else sha("2", pr % 100),
                           "head": {"ref": branch, "sha": head}})
        self.comment(pr, fm.render("claim", {"issue": str(pr), "holder": holder, "branch": branch}, "Claimed."),
                     "2026-11-20T10:20:00Z")
        for approved_head, at in approvals:
            self.comment(pr, lm.approval_body(pr, pr, approved_head or head, "approved", f"m{self.next_id}"), at)
        return head

    def read(self, path):
        self.reads.append(path)
        split = urlsplit(path)
        query = {key: values[0] for key, values in parse_qs(split.query).items()}
        page = int(query.get("page", "1"))
        parts = split.path.split("/")[3:]
        if parts == []:
            return {"default_branch": "main"}
        if parts == ["pulls"]:
            assert query["state"] == "closed" and query["base"] == "main", path
            return self.pulls[(page - 1) * 100:page * 100]
        if parts[0] == "issues" and parts[2] == "comments":
            return self.comments.get(int(parts[1]), [])[(page - 1) * 100:page * 100]
        if parts[0] == "commits":
            return {"sha": parts[1], "parents": [{"sha": p} for p in self.commits[parts[1]]]}
        if parts[:2] == ["actions", "workflows"]:
            assert parts[2] == "ci.yaml", path
            found = self.runs.get(query["branch"], [])
            return {"total_count": len(found), "workflow_runs": found[(page - 1) * 100:page * 100]}
        if parts[:2] == ["actions", "runs"] and parts[3] == "attempts":
            return self.attempts[(int(parts[2]), int(parts[4]))]
        raise AssertionError(path)

    def run(self, action, *extra, landings=2):
        argv = [action, "--repo", SLUG, "--issue", "1679", "--host", HOST, "--landings", str(landings),
                *extra]
        out = io.StringIO()
        with contextlib.redirect_stdout(out), mock.patch.object(
                landing_reading.fm, "closing_issues", side_effect=lambda slug, pr: self.closing[pr]):
            code = landing_reading.main(argv, read=self.read)
        return code, json.loads(out.getvalue())


class SyncsTest(unittest.TestCase):
    def test_syncs_is_met_when_two_landings_each_have_one_approval_and_at_most_one_sync(self):
        world = World()
        approved = sha("3", 1)
        merged = world.landing(1701, approvals=((approved, "2026-11-20T11:00:00Z"),),
                               head=sha("4", 1), merged_at="2026-11-20T12:00:00Z")
        world.commits[merged] = [approved, sha("5", 1)]
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(0, code)
        self.assertEqual("met", printed["status"])
        self.assertEqual(DEPLOYED, printed["since"])
        self.assertEqual([{"pr": 1701, "approvals": 1, "syncs_after_first_approval": 1},
                          {"pr": 1702, "approvals": 1, "syncs_after_first_approval": 0}],
                         printed["landings"])

    def chain(self, world, pr, approvals, syncs):
        """Landing `pr` first approved at head A; `syncs` merge commits follow, each approval
        `(index, created_at)` naming the head after that many of them."""
        first = sha("3", pr % 100)
        heads = [first]
        for n in range(syncs):
            heads.append(sha("4", (pr % 10) * 10 + n))
            world.commits[heads[-1]] = [heads[-2], sha("5", n)]
        world.landing(pr, approvals=[(heads[i], at) for i, at in approvals], head=heads[-1])

    def test_a_second_approval_does_not_reset_the_sync_count(self):
        world = World()
        self.chain(world, 1701, [(0, "2026-11-20T11:00:00Z"), (1, "2026-11-20T11:30:00Z")], 2)
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(1, code)
        self.assertEqual("not_met", printed["status"])
        self.assertEqual({"pr": 1701, "approvals": 2, "syncs_after_first_approval": 2},
                         printed["landings"][0])

    def test_two_approvals_are_not_met(self):
        world = World()
        head = sha("1", 1)
        world.landing(1701, approvals=[(head, "2026-11-20T11:00:00Z"), (head, "2026-11-20T11:30:00Z")],
                      head=head)
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(1, code)
        self.assertEqual({"pr": 1701, "approvals": 2, "syncs_after_first_approval": 0},
                         printed["landings"][0])

    def test_two_syncs_after_the_first_approval_are_not_met(self):
        world = World()
        self.chain(world, 1701, [(0, "2026-11-20T11:00:00Z")], 2)
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(1, code)
        self.assertEqual(2, printed["landings"][0]["syncs_after_first_approval"])

    def test_a_landing_of_another_host_is_not_counted(self):
        world = World()
        world.landing(1701, holder="mbp/session-y")
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(75, code)
        self.assertEqual("not_yet", printed["status"])
        self.assertEqual([1702], [row["pr"] for row in printed["landings"]])

    def test_a_landing_first_approved_before_the_deployment_is_not_counted(self):
        world = World()
        world.landing(1701, approvals=((None, BEFORE), (None, "2026-11-20T11:00:00Z")))
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(75, code)
        self.assertEqual([1702], [row["pr"] for row in printed["landings"]])

    def test_no_verify_due_marker_is_not_yet(self):
        world = World()
        world.comments[1679] = [{
            "id": 7, "created_at": DEPLOYED, "updated_at": DEPLOYED, "author_association": "OWNER",
            "body": fm.render("verify-due", {"block": "b", "check": "c", "host": "mbp"}, "Due.")}]
        world.landing(1701)
        world.landing(1702, merged_at="2026-11-20T13:00:00Z")
        for action, extra in (("syncs", ()), ("ci-runs", ("--baseline-runs", "89"))):
            code, printed = world.run(action, *extra)
            self.assertEqual(75, code)
            self.assertEqual("not_deployed", printed["status"])

    def test_one_landing_is_not_yet(self):
        world = World()
        world.landing(1701)
        code, printed = world.run("syncs")
        self.assertEqual(75, code)
        self.assertEqual("not_yet", printed["status"])

    def test_an_indirect_merge_is_no_landing(self):
        world = World()
        world.landing(1701, indirect=True, merged_at="2026-11-20T11:30:00Z")
        world.landing(1702, merged_at="2026-11-20T12:00:00Z")
        world.landing(1703, merged_at="2026-11-20T13:00:00Z")
        code, printed = world.run("syncs")
        self.assertEqual(0, code)
        self.assertEqual([1702, 1703], [row["pr"] for row in printed["landings"]])


class CiRunsTest(unittest.TestCase):
    def world(self, attempts):
        """One landing per entry of `attempts`: that many attempts of one `ci.yaml` run, each inside
        the pull request's interval."""
        world = World()
        for n, count in enumerate(attempts):
            pr = 1700 + n
            world.landing(pr, created_at="2026-11-20T10:30:00Z", merged_at=f"2026-11-20T12:{n:02d}:00Z")
            world.runs[f"issue-{pr}-x"] = [{"id": pr, "run_attempt": count}]
            for attempt in range(1, count + 1):
                world.attempts[(pr, attempt)] = {"run_started_at": f"2026-11-20T11:{attempt:02d}:00Z"}
        return world

    def test_ci_runs_is_met_below_the_baseline(self):
        world = self.world([2] * 39)
        code, printed = world.run("ci-runs", "--baseline-runs", "89", landings=39)
        self.assertEqual(0, code)
        self.assertEqual({"status": "met", "since": DEPLOYED, "landings": 39, "runs": 78,
                          "baseline_runs": 89}, printed)

    def test_ci_runs_is_not_met_at_the_baseline(self):
        world = self.world([3] * 11 + [2] * 28)
        code, printed = world.run("ci-runs", "--baseline-runs", "89", landings=39)
        self.assertEqual(1, code)
        self.assertEqual(("not_met", 89), (printed["status"], printed["runs"]))


class ScriptsTest(unittest.TestCase):
    def test_the_scripts_are_committed_executable(self):
        for path in SCRIPTS:
            self.assertEqual("100755", committed_mode(path), path)


if __name__ == "__main__":
    unittest.main()
