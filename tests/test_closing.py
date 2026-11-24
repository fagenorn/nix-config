"""Contract tests for `closing` (`agent_tools.delivery.closing`).

Each call runs through `main` against a real git project with a local bare origin and a fake `gh`
(`ForgeWorld`): `read` and `issue` answer exact argv, `worktree`, `forward` and `branch` act on real
repositories. Nothing is forced, so each test also reads back what git or the forge holds.
"""

from __future__ import annotations

import json
import os
import stat
import sys
import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest import mock

from agent_tools.delivery import closing, holding

from .forge_world import ForgeWorld
from .test_landing import BODY, ISSUE, SLUG, LandingWorld

TIER = "integration"

ISSUE_READ = ["api", f"repos/{SLUG}/issues/{ISSUE}"]
PR_LIST = ["pr", "list", "--repo", SLUG, "--head", "issue-41-add-a-greeting", "--state", "merged",
           "--json", "number,mergeCommit,headRefOid"]
SHA = "1" * 40
HEAD = "b" * 40
NOT_BEFORE = {"not_before": "2099-01-01T00:00:00Z"}
EVIDENCE = {"ac": "AC2", "kind": "evidence", "host": "any", "when": NOT_BEFORE, "run": {"command": "test"}}
ASK = {"ac": "AC3", "kind": "human", "host": "any", "when": NOT_BEFORE,
       "run": {"ask": "Does the greeting read well?"}, "reason": "taste"}
OPEN_BODY = ("## Acceptance criteria\n\n- [ ] [code] The greeting is printed.\n"
             "- [ ] [evidence] The greeting reads well in production.\n")
LOOK_LINE = "- [ ] [human] before merge: the greeting looks right — measured: the owner, on the console\n"
PR_VIEW = ["pr", "view", "7", "--repo", SLUG, "--json", "headRefOid,headRefName,statusCheckRollup"]
BLOCKING = ["api", f"repos/{SLUG}/issues/{ISSUE}/dependencies/blocking"]
# A `gh` that reads the issue from the store (so a close shows on the next read) and leaves every
# other call to the world's fake.
STORE_GH = """#!{python}
import json, os, sys
if sys.argv[1:] == {read!r}:
    state = json.loads(open(os.path.join(os.environ["FORGE_WORLD"], "store.json")).read())["issue_state"]
    sys.stdout.write(json.dumps({{"number": {issue}, "state": state["state"],
                                 "state_reason": state["state_reason"], "labels": []}}))
    sys.exit(0)
os.execv({fake!r}, [{fake!r}, *sys.argv[1:]])
"""


def call(env: dict, *args: str) -> tuple[int, dict]:
    """`closing.main(args)` under `env`: (exit status, the one JSON line printed)."""
    out = StringIO()
    with mock.patch.dict(os.environ, env), redirect_stdout(out):
        status = closing.main(list(args))
    lines = out.getvalue().splitlines()
    if len(lines) != 1:
        raise AssertionError(f"expected one stdout line, got {out.getvalue()!r}")
    return status, json.loads(lines[0])


class IssueTest(unittest.TestCase):
    def test_issue_closes_an_open_issue_only_when_its_criteria_close_it(self):
        forge = ForgeWorld(self)
        forge.comment_store(SLUG, ISSUE, [], labels=[])
        directory = forge.state.parent / "store-gh"
        directory.mkdir()
        wrapper = directory / "gh"
        wrapper.write_text(STORE_GH.format(python=sys.executable, read=ISSUE_READ, issue=ISSUE,
                                           fake=str(forge.bin / "gh")), encoding="utf-8")
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        env = {"PATH": str(directory), "FORGE_WORLD": str(forge.state)}

        def issue(closes: str) -> tuple[int, dict]:
            return call(env, "issue", "--repo", SLUG, "--issue", str(ISSUE), "--closes", closes)

        self.assertEqual(issue("false"), (0, {"verdict": "open-criteria"}))
        self.assertEqual(forge.issue()["state"], "open")
        self.assertEqual(forge.argvs("gh"), [])
        self.assertEqual(issue("true"), (0, {"verdict": "closed"}))
        self.assertEqual((forge.issue()["state"], forge.issue()["state_reason"]), ("closed", "completed"))
        self.assertEqual(issue("true"), (0, {"verdict": "closed"}))
        closes = [argv for argv in forge.argvs("gh") if argv[:3] == ["api", "-X", "PATCH"]]
        self.assertEqual(len(closes), 1, closes)


class GitTest(unittest.TestCase):
    def setUp(self):
        self.landing = LandingWorld(self)
        self.world = self.landing.world
        self.root = self.landing.fixture.root
        self.env = self.landing.env

    def call(self, *args: str) -> tuple[int, dict]:
        return call(self.env, *args)

    def git(self, *args: str, root=None) -> str:
        return self.world.git(root or self.root, *args).strip()


class WorktreeTest(GitTest):
    def test_a_clean_worktree_is_removed_and_a_dirty_one_is_kept(self):
        path = self.landing.worktree()
        args = ("worktree", "--repo-root", str(self.root), "--worktree-path")
        (path / "scratch.txt").write_text("kept\n", encoding="utf-8")
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "dirty"}))
        self.assertTrue((path / "scratch.txt").is_file())
        (path / "scratch.txt").unlink()
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "removed"}))
        self.assertFalse(path.exists())
        self.assertEqual(self.call(*args, str(path)), (0, {"verdict": "removed"}))
        self.assertEqual(self.call(*args, str(self.root.parent / "nowhere")), (0, {"verdict": "removed"}))


class ForwardTest(GitTest):
    def forward(self) -> tuple[int, dict]:
        return self.call("forward", "--repo-root", str(self.root), "--integration-branch", "main")

    def test_forward_fast_forwards_only_a_clean_checkout_on_the_integration_branch(self):
        before = self.git("rev-parse", "main")
        advanced = self.world.advance(self.root, "main")
        self.git("checkout", "--quiet", "-b", "elsewhere")
        self.assertEqual(self.forward(), (0, {"verdict": "skipped"}))
        self.assertEqual(self.git("rev-parse", "main"), before)
        self.assertEqual(self.git("rev-parse", "origin/main"), advanced)

        self.git("checkout", "--quiet", "main")
        (self.root / "README.md").write_text("changed\n", encoding="utf-8")
        self.assertEqual(self.forward(), (0, {"verdict": "skipped"}))
        self.assertEqual(self.git("rev-parse", "main"), before)

        self.git("checkout", "--quiet", "--", "README.md")
        (self.root / "untracked.txt").write_text("not tracked\n", encoding="utf-8")
        self.assertEqual(self.forward(), (0, {"verdict": "forwarded"}))
        self.assertEqual((self.git("rev-parse", "main"), self.git("rev-parse", "origin/main")),
                         (advanced, advanced))
        self.assertEqual(self.forward(), (0, {"verdict": "forwarded"}))


class BranchTest(GitTest):
    def test_branch_reads_gone_or_kept(self):
        args = ("branch", "--repo-root", str(self.root), "--branch")
        self.assertEqual(self.call(*args, "main"), (0, {"verdict": "kept"}))
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "gone"}))
        self.git("branch", "issue-41-x")
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "kept"}))
        self.git("branch", "-d", "issue-41-x")
        self.assertEqual(self.call(*args, "issue-41-x"), (0, {"verdict": "gone"}))


class ReadTest(GitTest):
    def read(self, *extra: str) -> tuple[int, dict]:
        return self.call("read", "--repo-root", str(self.root), "--issue", str(ISSUE), "--repo", SLUG, *extra)

    def test_read_answers_merged_with_the_placement_and_the_criteria(self):
        forge = self.landing.forge
        forge.respond_json("gh", PR_LIST, [{"number": 7, "mergeCommit": {"oid": SHA}}])
        status, merged = self.read()
        place = {"branch": "issue-41-add-a-greeting",
                 "worktree_path": str(self.landing.fixture.worktree_root
                                      / (self.landing.fixture.worktree_prefix + "issue-41-add-a-greeting")),
                 "integration_branch": "main"}
        self.assertEqual((status, merged), (0, {"verdict": "merged", **place, "closes": True,
                                                "pr": 7, "merge_commit": SHA}))
        forge.respond_json("gh", ISSUE_READ, {"number": ISSUE, "title": "Add a greeting", "state": "open",
                                              "labels": [], "body": BODY.replace("[code]", "[human]")})
        self.assertEqual(self.read()[1]["closes"], False)
        forge.respond_json("gh", PR_LIST, [])
        self.assertEqual(self.read(), (0, {"verdict": "unmerged"}))

    def test_read_given_a_head_settles_only_on_a_merged_pull_request_with_that_head(self):
        forge = self.landing.forge
        other, head = "b" * 40, "c" * 40
        earlier = {"number": 7, "mergeCommit": {"oid": SHA}, "headRefOid": other}
        forge.respond_json("gh", PR_LIST, [earlier])
        self.assertEqual(self.read("--head", head), (0, {"verdict": "unmerged"}))
        self.assertEqual(self.read()[1]["pr"], 7)
        later = {"number": 9, "mergeCommit": {"oid": SHA}, "headRefOid": head}
        forge.respond_json("gh", PR_LIST, [later, earlier])
        status, merged = self.read("--head", head)
        self.assertEqual((status, merged["verdict"], merged["pr"]), (0, "merged", 9))
        forge.respond_json("gh", PR_LIST, [{"number": 9, "mergeCommit": {"oid": SHA}}])
        self.assertEqual(self.read("--head", head), (0, {"verdict": "unmerged"}))


def comment(identifier: int, body: str) -> dict:
    return {"id": identifier, "author_association": "OWNER", "body": body,
            "created_at": "2026-11-06T10:00:00Z", "updated_at": "2026-11-06T10:00:00Z"}


def held(block: dict) -> str:
    return "held\n```verify\n" + json.dumps(block) + "\n```"


class HoldTest(GitTest):
    def usage(self, *args: str) -> dict:
        out = StringIO()
        with mock.patch.dict(os.environ, self.env), redirect_stdout(out), self.assertRaises(SystemExit) as raised:
            closing.main(list(args))
        self.assertEqual(raised.exception.code, 2)
        return json.loads(out.getvalue())

    def respond_body(self, body: str) -> None:
        self.landing.forge.respond_json("gh", ISSUE_READ, {"number": ISSUE, "title": "Add a greeting",
                                                           "state": "open", "labels": [], "body": body})

    def merge(self) -> str:
        return self.git("rev-parse", "HEAD")


class HoldFactsTest(HoldTest):
    def facts(self, merge: str) -> tuple[int, dict]:
        return self.call("hold-facts", "--repo-root", str(self.root), "--repo", SLUG, "--issue", str(ISSUE),
                         "--pr", "7", "--merge-commit", merge)

    def test_hold_facts_reads_the_open_criteria_the_posted_fence_and_the_blocked_issues(self):
        forge, merge = self.landing.forge, self.merge()
        self.respond_body(OPEN_BODY)
        forge.comment_store(SLUG, ISSUE, [comment(100, held(holding.block_of([EVIDENCE], merge)))], labels=[])
        forge.respond_json("gh", BLOCKING, [{"number": 50}])
        forge.respond_json("gh", PR_VIEW, {
            "headRefOid": HEAD, "headRefName": "issue-41-add-a-greeting",
            "statusCheckRollup": [{"workflowName": "Fixture", "name": "Fixture Checks"},
                                  {"workflowName": "Fixture", "name": "Other"}, {"workflowName": ""}]})
        status, facts = self.facts(merge)
        evidence = {"id": "AC2", "kind": "evidence", "text": "The greeting reads well in production."}
        self.assertEqual(status, 0)
        self.assertEqual(facts["verdict"], "open")
        self.assertEqual(facts["criteria"], [{"id": "AC1", "kind": "code", "text": "The greeting is printed."},
                                             evidence])
        self.assertEqual(facts["open"], [evidence])
        self.assertEqual((facts["blocks"], facts["verification"], facts["workflows"]),
                         ([50], ["lint", "test"], ["Fixture"]))
        self.assertEqual((facts["pr_head"], facts["pr_branch"]), (HEAD, "issue-41-add-a-greeting"))
        self.assertEqual(facts["posted"], [{"issue": ISSUE, "merge": merge, "checks": [EVIDENCE],
                                            "comment_id": 100, "results": False}])

    def test_hold_facts_reports_a_posted_fence_that_is_not_json_as_posted_with_no_checks(self):
        forge, merge = self.landing.forge, self.merge()
        self.respond_body(OPEN_BODY)
        forge.comment_store(SLUG, ISSUE, [comment(100, "held\n```verify\n{\"v\": 1, \"checks\": [\n```")], labels=[])
        forge.respond_json("gh", BLOCKING, [])
        forge.respond_json("gh", PR_VIEW, {"headRefOid": HEAD, "headRefName": "b", "statusCheckRollup": []})
        self.assertEqual(self.facts(merge)[1]["posted"], [
            {"issue": ISSUE, "merge": None, "checks": [], "comment_id": 100, "results": False}])

    def test_hold_facts_reads_the_results_marker_and_the_split_children_of_this_merge_only(self):
        forge, merge = self.landing.forge, self.merge()
        self.respond_body(OPEN_BODY)
        marker = "<!-- agent:verify-result v1 block=100.abc -->\nresult"
        child = lambda number: {"number": number, "title": "t", "labels": ["needs-verification"],
                                "state": "open", "body": holding.split_line(ISSUE, "AC3", merge) + "\nbody"}
        forge.comment_store(SLUG, ISSUE, [comment(100, held(holding.block_of([EVIDENCE], merge))),
                                          comment(101, marker)], labels=[],
                            created=[child(50), child(52), {**child(53), "body": "unrelated"}])
        for number, at in ((50, merge), (52, "c" * 40)):
            forge.respond_json("gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{number}/comments?per_page=100"],
                               [[comment(200 + number, held(holding.block_of([ASK], at)))]])
        forge.respond_json("gh", BLOCKING, [])
        forge.respond_json("gh", PR_VIEW, {"headRefOid": HEAD, "headRefName": "b", "statusCheckRollup": []})
        self.assertEqual(self.facts(merge)[1]["posted"], [
            {"issue": ISSUE, "merge": merge, "checks": [EVIDENCE], "comment_id": 100, "results": True},
            {"issue": 50, "merge": merge, "checks": [ASK], "comment_id": 250, "results": False}])

    def test_hold_facts_on_an_all_code_body_answers_closes_after_one_read(self):
        self.assertEqual(self.facts(self.merge()), (0, {"verdict": "closes"}))
        self.assertEqual(self.landing.forge.argvs("gh"), [ISSUE_READ])

    def test_hold_facts_on_an_untagged_criterion_answers_bad_kinds(self):
        self.respond_body("## Acceptance criteria\n\n- [ ] [code] a\n- [ ] not tagged\n")
        self.assertEqual(self.facts(self.merge()), (0, {"verdict": "bad-kinds", "acs": ["AC2"]}))

    def test_hold_facts_on_a_merge_commit_the_checkout_lacks_answers_absent_merge(self):
        self.respond_body(OPEN_BODY)
        self.assertEqual(self.facts("c" * 40), (0, {"verdict": "absent-merge"}))
        self.assertEqual(self.landing.forge.argvs("gh"), [ISSUE_READ])


class HoldLookTest(HoldTest):
    def look(self, posted: list) -> tuple[int, dict]:
        return self.call("hold-look", "--repo", SLUG, "--issue", str(ISSUE), "--pr", "7", "--pr-head", HEAD,
                         "--merge-commit", self.merge(), "--posted", json.dumps(posted))

    def approved(self):
        return mock.patch.object(holding, "look_status", return_value={"verdict": "approved"})

    def test_an_unmarked_issue_is_clear_with_nothing_answered(self):
        with mock.patch.object(holding, "look_status", side_effect=AssertionError("no look")):
            self.assertEqual(self.look([]), (0, {"verdict": "clear", "answered": []}))

    def test_an_approved_look_with_a_child_fence_naming_its_criterion_is_stale(self):
        self.respond_body(OPEN_BODY + LOOK_LINE)
        child = {"issue": 50, "merge": self.merge(), "checks": [{**EVIDENCE, "ac": "AC3"}],
                 "comment_id": 9, "results": False}
        with self.approved() as status:
            result = self.look([child])
        self.assertEqual(result, (0, {"verdict": "stale", "answered": ["AC3"], "stale": [{**child, "acs": ["AC3"]}]}))
        self.assertEqual(status.call_args.kwargs, {"repo": SLUG, "issue": ISSUE, "pr": 7, "head": HEAD,
                                                    "merge": self.merge()})

    def test_an_approved_look_answering_every_open_criterion_with_an_own_fence_naming_one_is_stale(self):
        self.respond_body("## Acceptance criteria\n\n- [ ] [code] a\n" + LOOK_LINE)
        own = {"issue": ISSUE, "merge": self.merge(), "checks": [EVIDENCE], "comment_id": 9, "results": False}
        with self.approved():
            status, result = self.look([own])
        self.assertEqual((status, result["verdict"], result["answered"]), (0, "stale", ["AC2"]))
        self.respond_body("## Acceptance criteria\n\n- [ ] [code] a\n" + LOOK_LINE.replace("[human]", "[human]")
                          + "- [ ] [evidence] still open\n")
        with self.approved():
            self.assertEqual(self.look([own])[1]["verdict"], "clear")

    def test_a_look_that_is_not_approved_answers_nothing(self):
        self.respond_body(OPEN_BODY + LOOK_LINE)
        with mock.patch.object(holding, "look_status", return_value={"verdict": "needed"}):
            self.assertEqual(self.look([]), (0, {"verdict": "clear", "answered": []}))

    def test_a_posted_that_is_not_json_is_a_usage_error(self):
        usage = self.usage("hold-look", "--repo", SLUG, "--issue", "41", "--pr", "7", "--pr-head", HEAD,
                           "--merge-commit", SHA, "--posted", "{")
        self.assertEqual((usage["verdict"], usage["error"]), ("error", "usage"))


class HoldGateTest(HoldTest):
    def gate(self, written: list, criteria=None, **flags: str) -> tuple[int, dict]:
        criteria = holding.criteria(OPEN_BODY) if criteria is None else criteria
        given = {"issue": str(ISSUE), "merge-commit": self.merge(), "criteria": json.dumps(criteria),
                 "posted": "[]", "blocks": "[]", "answered": "[]", "written": json.dumps(written), **flags}
        return self.call("hold-gate", "--repo-root", str(self.root),
                         *(word for name, value in given.items() for word in (f"--{name}", value)))

    def test_hold_gate_prints_ready_with_the_block(self):
        status, gate = self.gate([{"ac": "AC2", "check": json.dumps(EVIDENCE)}])
        self.assertEqual((status, gate), (0, {
            "verdict": "ready", "split": [], "block": holding.block_of([EVIDENCE], self.merge()),
            "held": [{"id": "AC2", "kind": "evidence", "text": "The greeting reads well in production."}]}))

    def test_hold_gate_prints_the_gates_refusal(self):
        outside = {**EVIDENCE, "run": {"command": "deploy"}}
        status, gate = self.gate([{"ac": "AC2", "check": json.dumps(outside)}])
        self.assertEqual((status, gate["verdict"], gate["acs"]), (0, "unattended", ["AC2"]))

    def test_a_criteria_member_that_is_not_json_is_a_usage_error(self):
        usage = self.usage("hold-gate", "--repo-root", str(self.root), "--issue", "41", "--merge-commit", SHA,
                           "--criteria", "[", "--posted", "[]", "--blocks", "[]", "--answered", "[]",
                           "--written", "[]")
        self.assertEqual(usage["error"], "usage")


class HoldLintTest(HoldTest):
    def lint(self, block, split=(), posted=(), answered=(), created=()) -> tuple[int, dict]:
        self.landing.forge.comment_store(SLUG, ISSUE, list(posted), labels=[], created=list(created))
        return self.call("hold-lint", "--repo-root", str(self.root), "--repo", SLUG, "--issue", str(ISSUE),
                         "--pr-head", HEAD, "--pr-branch", "issue-41-add-a-greeting", "--workflows", "[]",
                         "--blocks", "[]", "--answered", json.dumps(list(answered)),
                         "--block", json.dumps(block), "--split", json.dumps(list(split)))

    def test_a_valid_block_lints_valid(self):
        status, lint = self.lint(holding.block_of([EVIDENCE], self.merge()))
        self.assertEqual((status, lint["verdict"]), (0, "valid"))
        self.assertEqual([(entry["issue"], entry["ac"], entry["ok"]) for entry in lint["lints"]],
                         [(ISSUE, None, True)])

    def test_a_block_with_a_bad_time_lints_invalid_naming_the_field(self):
        bad = {**EVIDENCE, "when": {"not_before": "not-a-time"}}
        status, lint = self.lint(holding.block_of([bad], self.merge()))
        self.assertEqual((status, lint["verdict"]), (0, "invalid"))
        self.assertEqual([error["field"] for error in lint["lints"][0]["errors"]], ["checks[0].when.not_before"])

    def test_an_existing_fence_is_linted_instead_of_the_drafted_block(self):
        bad = {**EVIDENCE, "when": {"not_before": "not-a-time"}}
        posted = comment(100, held(holding.block_of([bad], self.merge())))
        status, lint = self.lint(holding.block_of([EVIDENCE], self.merge()), posted=[posted])
        self.assertEqual((status, lint["verdict"]), (0, "invalid"))
        self.assertEqual([error["field"] for error in lint["lints"][0]["errors"]], ["checks[0].when.not_before"])

    def test_a_posted_fence_that_is_not_json_or_has_no_checks_is_linted_not_the_drafted_block(self):
        merge = self.merge()
        broken = "held\n```verify\n" + json.dumps({"v": 1, "merge": merge, "checks": []})[:-2] + "\n```"
        for text in (broken, "held\n```verify\n" + json.dumps({"v": 1, "merge": merge}) + "\n```"):
            with self.subTest(text=text):
                status, lint = self.lint(holding.block_of([EVIDENCE], merge), posted=[comment(100, text)])
                self.assertEqual((status, lint["verdict"]), (0, "invalid"))
                self.assertEqual([(entry["issue"], entry["ac"], entry["ok"]) for entry in lint["lints"]],
                                 [(ISSUE, None, False)])

    def test_an_existing_fence_is_linted_without_the_checks_naming_an_answered_criterion(self):
        stale = {**ASK, "ac": "ac3", "when": {"not_before": "not-a-time"}}
        posted = comment(100, held(holding.block_of([EVIDENCE, stale], self.merge())))
        status, lint = self.lint(None, posted=[posted], answered=["AC3"])
        self.assertEqual((status, lint["verdict"], len(lint["lints"])), (0, "valid", 1))

    def test_each_split_entry_is_linted_with_no_blocks_and_a_null_block_is_skipped(self):
        bad = {**ASK, "when": {"not_before": "not-a-time"}}
        split = [{"ac": "AC3", "block": holding.block_of([bad], self.merge())},
                 {"ac": "AC4", "block": holding.block_of([{**ASK, "ac": "AC4"}], self.merge())}]
        status, lint = self.lint(None, split=split)
        self.assertEqual((status, lint["verdict"]), (0, "invalid"))
        self.assertEqual([(entry["issue"], entry["ac"], entry["ok"]) for entry in lint["lints"]],
                         [(None, "AC3", False), (None, "AC4", True)])

    def test_a_split_childs_posted_fence_is_linted_instead_of_the_entrys_block(self):
        bad = {**ASK, "when": {"not_before": "not-a-time"}}
        child = {"number": 50, "title": "t", "labels": ["needs-verification"], "state": "open",
                 "body": holding.split_line(ISSUE, "AC3", self.merge()) + "\nbody"}
        self.landing.forge.respond_json(
            "gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/50/comments?per_page=100"],
            [[comment(250, held(holding.block_of([ASK], self.merge())))]])
        status, lint = self.lint(None, split=[{"ac": "AC3", "block": holding.block_of([bad], self.merge())}],
                                 created=[child])
        self.assertEqual((status, lint["verdict"]), (0, "valid"))
        self.assertEqual([(entry["issue"], entry["ac"]) for entry in lint["lints"]], [(50, "AC3")])


class DeclarationTest(unittest.TestCase):
    def test_the_closing_declaration_lists_every_hold_subcommand(self):
        path = os.path.join(os.path.dirname(closing.__file__), "command_verdicts.json")
        with open(path, encoding="utf-8") as handle:
            subcommands = json.load(handle)["closing"]["subcommands"]
        self.assertEqual({name: subcommands[name] for name in subcommands if name.startswith("hold-")}, {
            "hold-facts": ["closes", "open", "bad-kinds", "absent-merge", "error"],
            "hold-look": ["clear", "stale", "error"],
            "hold-gate": ["ready", "missing-checks", "human-checks", "unattended", "owner-checks",
                          "script-checks", "note-checks", "error"],
            "hold-lint": ["valid", "invalid", "error"]})


if __name__ == "__main__":
    unittest.main()
