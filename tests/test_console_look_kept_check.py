"""The verify check that a kept look approval merged without a second one (#1211, AC6).

Run: just agent-workflow-tests
"""
import base64
import contextlib
import io
import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path

from agent_tools.claims import forge_markers
from agent_tools.console import look_kept_check
from agent_tools.delivery import look_marker as lm
from agent_tools.system.forge_api import ForgeError
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)
from tests.test_verify_checks import committed_mode

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/look-approval-kept"
SLUG = "octo/widgets"
R = f"repos/{SLUG}/"
SINCE = "0" * 39 + "1"
A0 = "7" * 40
A = "5" * 40
H = "1a2b3c4" + "d" * 33
L = "c" * 40
MC = "2" * 40
BT = "3" * 40
FORK = "e" * 40
X = "8" * 40
PAGE = "python/agent_tools/console/page.html"
VIEW = "python/agent_tools/console/view.py"
TESTF = "tests/test_console_page.py"
GLOB = "python/agent_tools/console/**"
ACTIVATED = datetime(2026, 11, 17, 9, 0, tzinfo=timezone.utc)
BODY = "## Acceptance criteria\n\n- [ ] [human] before merge: the page — measured: the owner\n"
BEFORE = "2026-11-17T11:00:00Z"
AFTER = "2026-11-17T13:00:00Z"
Q = "?per_page=100&page="
CLOSED = R + "pulls?state=closed&sort=updated&direction=desc&per_page=100&page=1"


def contents(text):
    raw = base64.b64encode(text.encode()).decode()
    return {"type": "file", "encoding": "base64",
            "content": "\n".join(raw[i:i + 60] for i in range(0, len(raw), 60))}


def edit(name):
    return {"filename": name, "status": "modified",
            "patch": f"@@ -1,2 +1,2 @@\n {name} line 0\n-{name} old\n+{name} e"}


def cmp(files=(), commits=()):
    return {"status": "ahead", "files": [edit(name) for name in files], "total_commits": len(commits),
            "commits": [{"sha": sha, "parents": [{"sha": p} for p in parents]} for sha, parents in commits]}


def commit_item(sha, parents):
    return {"sha": sha, "parents": [{"sha": p} for p in parents]}


TWO = [commit_item(A, [FORK]), commit_item(H, [A])]


def pull(merged="2026-11-17T12:00:00Z", updated="2026-11-17T12:00:00Z", merge_commit=MC):
    found = {"number": 12, "merged_at": merged, "updated_at": updated, "body": "Closes #7\n",
             "head": {"sha": H, "ref": "issue-7-page"}}
    if merge_commit is not None:
        found["merge_commit_sha"] = merge_commit
    return found


def stamped(cid, body, created=BEFORE, association="OWNER"):
    return {"id": cid, "author_association": association, "created_at": created,
            "updated_at": created, "body": body}


def answer(cid, head, what, **more):
    return stamped(cid, lm.approval_body(7, 12, head, what, f"m{cid}"), **more)


def approval(cid, head, **more):
    return answer(cid, head, "approved", **more)


def changes(cid, head, **more):
    return answer(cid, head, "changes", **more)


def world(comments, commits=TWO, merge_commit=MC, files=None):
    return {
        R + f"commits/{SINCE}": {"commit": {"committer": {"date": "2026-11-17T10:00:00Z"}}},
        CLOSED: [pull(merge_commit=merge_commit)],
        R + "pulls/12/files" + Q + "1": [{"filename": PAGE}] if files is None else files,
        R + "pulls/12/commits" + Q + "1": commits,
        R + "issues/7": {"number": 7, "body": BODY},
        R + "issues/7/comments" + Q + "1": comments,
        R + f"commits/{MC}": {"parents": [{"sha": BT}, {"sha": H}]},
        R + lm.contents_path(BT): contents(
            '{"version": 1, "sets": {"console": ["python/agent_tools/console/**"]}}'),
        R + lm.compare_path(BT, A): cmp([PAGE, VIEW], commits=[(A, [FORK])]),
        R + lm.compare_path(A, H): cmp([TESTF]),
        R + lm.compare_path(BT, H): cmp(commits=[(A, [FORK]), (H, [A])]),
    }


def put(reads, path, value):
    reads[R + path] = value


class Run:
    def __init__(self, reads):
        self.reads = reads
        self.paths = []

    def get(self, path):
        self.paths.append(path)
        if path not in self.reads:
            raise ForgeError("not_found", path)
        found = self.reads[path]
        if isinstance(found, Exception):
            raise found
        return found

    def check(self, argv=None, activated=ACTIVATED):
        argv = ["--repo", SLUG, "--since", SINCE, "--glob", GLOB] if argv is None else argv
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = look_kept_check.main(argv, get=self.get, activated_at=lambda: activated,
                                        fixed_activation=lambda since, current: current)
        lines = out.getvalue().splitlines()
        assert len(lines) == 1, out.getvalue()
        return code, json.loads(lines[0])


def run(comments, **kwargs):
    return Run(world(comments, **kwargs)).check()


def two_look_world(comments, mid_files):
    """[A <- FORK, L <- A, H <- L]: L changes the look files, H changes tests only."""
    reads = world(comments, commits=[commit_item(A, [FORK]), commit_item(L, [A]), commit_item(H, [L])])
    put(reads, lm.compare_path(A, L), cmp([PAGE]))
    put(reads, lm.compare_path(L, H), cmp([TESTF]))
    put(reads, lm.compare_path(A, H), cmp(mid_files))
    put(reads, lm.compare_path(BT, H), cmp(commits=[(A, [FORK]), (L, [A]), (H, [L])]))
    return reads


class LookKeptCheckTest(unittest.TestCase):
    def test_a_kept_landing_with_one_approval_is_met(self):
        self.assertEqual((0, {"approvals": 1, "issue": 7, "pr": 12, "second": 0, "status": "met"}),
                         run([approval(5, A)]))

    def test_a_needless_re_approval_is_not_met(self):
        self.assertEqual((1, {"approvals": 2, "issue": 7, "pr": 12, "second": 1, "status": "not_met"}),
                         run([approval(5, A), approval(6, H)]))

    def test_a_merge_on_an_exact_approval_is_no_landing(self):
        look_commit = two_look_world([approval(5, A), approval(6, H)], [PAGE, TESTF])
        rows = {
            "a look commit before the re-approval": look_commit,
            "the owner approved only the merged head": world([approval(5, H)]),
            "a changes answer before the re-approval":
                world([approval(5, A), changes(6, A), approval(7, H)]),
            "an older head approved after the merged head": world([approval(5, H), approval(6, A)]),
        }
        for name, reads in rows.items():
            with self.subTest(name):
                self.assertEqual((75, {"status": "waiting"}), Run(reads).check())

    def test_a_re_approval_after_a_look_change_is_met_when_carried_after(self):
        reads = world([approval(4, A0), approval(5, A)],
                      commits=[commit_item(A0, [FORK]), commit_item(A, [A0]), commit_item(H, [A])])
        put(reads, lm.compare_path(A0, A), cmp([PAGE]))
        put(reads, lm.compare_path(BT, A), cmp([PAGE, VIEW], commits=[(A0, [FORK]), (A, [A0])]))
        put(reads, lm.compare_path(BT, H), cmp(commits=[(A0, [FORK]), (A, [A0]), (H, [A])]))
        code, out = Run(reads).check()
        self.assertEqual((0, 2, 0, "met"), (code, out["approvals"], out["second"], out["status"]))

    def test_a_dropped_head_does_not_make_a_second_approval(self):
        code, out = run([approval(5, FORK), approval(6, A)])
        self.assertEqual((0, 2, 0), (code, out["approvals"], out["second"]))

    def test_a_second_page_is_read(self):
        filler = [stamped(100 + i, "hello") for i in range(99)]
        reads = world([approval(5, A)] + filler)
        put(reads, "issues/7/comments" + Q + "2", [approval(205, H)])
        code, out = Run(reads).check()
        self.assertEqual((1, 1), (code, out["second"]))
        reads = world([approval(5, A)] + filler)
        put(reads, "issues/7/comments" + Q + "2", [stamped(206, forge_markers.end_body(5, "withdrawn"))])
        self.assertEqual((75, {"status": "waiting"}), Run(reads).check())
        reads = world([approval(5, A)], files=[{"filename": f"docs/{i}.md"} for i in range(100)])
        put(reads, "pulls/12/files" + Q + "2", [{"filename": PAGE}])
        self.assertEqual(0, Run(reads).check()[0])

    def test_these_candidates_are_passed_over(self):
        merge = world([approval(5, A), approval(6, H)], commits=[commit_item(A, [FORK]), commit_item(H, [A, X])])
        put(merge, lm.compare_path(BT, H), cmp(commits=[(A, [FORK]), (H, [A, X])]))
        put(merge, lm.compare_path(A, H), cmp(["docs/x.md"]))
        put(merge, lm.compare_path(A, X), cmp(["docs/x.md"]))
        put(merge, lm.compare_path(X, A), cmp([PAGE]))
        put(merge, lm.compare_path(X, H), cmp([PAGE]))
        merge_one = dict(merge)
        merge_one[R + "issues/7/comments" + Q + "1"] = [approval(5, A)]
        no_q = world([approval(5, A), approval(6, H)])
        put(no_q, lm.compare_path(A, H), cmp([PAGE]))
        unrelated = world([approval(5, A)])
        put(unrelated, lm.compare_path(BT, H), cmp(commits=[(A, [FORK]), (H, [FORK])]))
        late = world([approval(5, A, created=AFTER)])
        rows = {
            "all files under docs": world([approval(5, A)], files=[{"filename": "docs/a.md"}]),
            "merged before the boundary": {**world([approval(5, A, created="2026-11-17T08:00:00Z")]), CLOSED: [
                pull(merged="2026-11-17T09:00:00Z", updated="2026-11-17T09:30:00Z")]},
            "an untrusted approval only": world([approval(5, A, association="NONE")]),
            "an approval created after merged_at only": late,
            "no commit without a look file after the approval": no_q,
            "the only commit after A is a merge": merge,
            "the only commit after A is a merge, one approval": merge_one,
            "an approval of FORK only": world([approval(5, FORK)]),
            "a later changes answer on an older head": world([approval(5, A), changes(6, A)]),
            "no merge commit": world([approval(5, A)], merge_commit=None),
            "no merge commit, two approvals": world([approval(5, A), approval(6, H)], merge_commit=None),
            "an unrelated head": unrelated,
        }
        for name, reads in rows.items():
            with self.subTest(name):
                self.assertEqual((75, {"status": "waiting"}), Run(reads).check())

    def test_usage_and_forge_errors_exit_2(self):
        flags = ["--repo", SLUG, "--since", SINCE]
        for argv in (["--repo", SLUG, "--since", "abc", "--glob", GLOB], flags, flags + ["--glob", "/a/**"]):
            with self.subTest(argv):
                code, out = Run(world([])).check(argv)
                self.assertEqual((2, "error"), (code, out["status"]))
        many = [commit_item(f"{i:040x}", [FORK]) for i in range(1, 251)]
        broken = world([approval(5, A)], commits=[{"sha": A}, commit_item(H, [A])])
        reads = {
            "the commit read fails": {**world([]), R + f"commits/{SINCE}": ForgeError("rate_limited", "x")},
            "a comments page that is not a list": world({"message": "no"}),
            "a commit listing of 250": {**world([approval(5, A)]), R + "pulls/12/commits" + Q + "1": many[:100],
                                         R + "pulls/12/commits" + Q + "2": many[100:200],
                                         R + "pulls/12/commits" + Q + "3": many[200:]},
            "a commit with no parents": broken,
            "the Q compare answers {}": {**world([approval(5, A)]), R + lm.compare_path(A, H): {}},
            "the head is not in C": world([approval(5, A)], commits=[commit_item(A, [FORK])]),
            "the settle read is missing": {k: v for k, v in world([approval(5, A)]).items()
                                           if k != R + lm.compare_path(BT, H)},
            "the settle read is malformed": {**world([approval(5, A)]), R + lm.compare_path(BT, H): {}},
        }
        for name, found in reads.items():
            with self.subTest(name):
                code, out = Run(found).check()
                self.assertEqual((2, "error"), (code, out["status"]))

    def test_a_marker_comment_edited_after_the_merge_is_incomplete_evidence(self):
        edited = {**approval(5, A), "updated_at": AFTER}
        unstamped = {k: v for k, v in approval(5, A).items() if k != "updated_at"}
        for name, comments in {"edited into an approval": [edited], "no updated_at": [unstamped]}.items():
            with self.subTest(name):
                code, out = run(comments)
                self.assertEqual((2, "error"), (code, out["status"]))
        plain = {**stamped(9, "hello"), "updated_at": AFTER}
        early = {**approval(5, A), "updated_at": "2026-11-17T11:30:00Z"}
        self.assertEqual(0, run([early, plain])[0])

    def test_activation_unknown_waits(self):
        running = Run(world([approval(5, A)]))
        self.assertEqual((75, {"status": "activation_unknown"}), running.check(activated=None))
        self.assertFalse([p for p in running.paths if "pulls" in p])

    def test_the_wrapper_is_committed_executable(self):
        self.assertEqual("100755", committed_mode(ROOT / WRAPPER))
        done = subprocess.run([str(ROOT / WRAPPER)], cwd=ROOT, text=True, timeout=60,
                              stdin=subprocess.DEVNULL, capture_output=True)
        self.assertEqual(2, done.returncode)


if __name__ == "__main__":
    unittest.main()
