"""forge-issue (issue 697): file an issue and record its blocking edges natively, by database id, read back."""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import forge_issue
from agent_tools import forge_markers as fm
from .forge_world import ForgeWorld

FIXTURE = json.loads((Path(__file__).parent / "fixtures/forge-issue-dependencies.json").read_text("utf-8"))
SLUG = FIXTURE["repo"]
B1, B2, DOWN = (FIXTURE["issues"][n] for n in ("555", "688", "689"))
PR, CHILD, FOREIGN = FIXTURE["pull_request"], FIXTURE["created"], FIXTURE["foreign"]
NEW = CHILD["number"]
TITLE, BODY = "Wire the widget", "## Blocked by\n\n- #555\n- #688\n"
KEYS = {"command", "repo", "issue", "verdict", "blocked_by", "blocks", "missing_blocked_by", "missing_blocks",
        "unexpected_blocked_by", "unexpected_blocks", "error", "detail"}
NUMBERS = {str(r["number"]) for r in (B1, B2, DOWN, CHILD)}


def ref(record):
    return f"{record['repository_url'].split('/repos/', 1)[1]}#{record['number']}"


def get(n):
    return ["api", f"repos/{SLUG}/issues/{n}"]


def create(labels=()):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues", "-f", f"title={TITLE}", "-f", f"body={BODY}",
            *(a for name in labels for a in ("-f", f"labels[]={name}"))]


def link(issue, blocker_id):
    return ["api", "--method", "POST", f"repos/{SLUG}/issues/{issue}/dependencies/blocked_by",
            "-F", f"issue_id={blocker_id}"]


def listing(issue, side):
    return ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{issue}/dependencies/{side}?per_page=100"]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_issue.main(list(argv))
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, out.getvalue()  # exactly one JSON object, one line (D8)
    result = json.loads(lines[0])
    assert set(result) == KEYS, sorted(result)
    return code, result


class Base(unittest.TestCase):
    def setUp(self):
        self.world = ForgeWorld(self)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.body_file = Path(tmp.name) / "body.md"
        self.body_file.write_text(BODY, encoding="utf-8")
        for record in (B1, B2, DOWN, PR):
            self.world.respond_json("gh", get(record["number"]), record)

    def posts(self):
        return [argv for argv in self.world.argvs("gh") if "POST" in argv]

    def links(self):
        return [argv for argv in self.posts() if argv[3].endswith("/dependencies/blocked_by")]

    def file(self, *extra):
        return run("create", "--repo", SLUG, "--title", TITLE, "--body-file", str(self.body_file), *extra)

    def lists(self, issue, blocked_by, blocking):
        self.world.respond_json("gh", listing(issue, "blocked_by"), [blocked_by])
        self.world.respond_json("gh", listing(issue, "blocking"), [blocking])

    def created_world(self, blocked_by, blocking, labels=()):
        self.world.respond_json("gh", create(labels), CHILD)
        self.world.respond_json("gh", get(NEW), CHILD)
        for argv in (link(NEW, B1["id"]), link(NEW, B2["id"]), link(DOWN["number"], CHILD["id"])):
            self.world.respond_json("gh", argv, CHILD)
        self.lists(NEW, blocked_by, blocking)


class CreateTest(Base):
    def test_create_posts_one_link_per_edge_by_database_id(self):
        self.created_world([B1, B2], [DOWN])
        code, out = self.file("--blocked-by", "555", "--blocked-by", "688", "--blocks", "689")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["verdict"], out["issue"], out["blocked_by"], out["blocks"]),
                         ("created", NEW, [ref(B1), ref(B2)], [ref(DOWN)]))
        self.assertEqual((out["missing_blocked_by"], out["missing_blocks"],
                          out["unexpected_blocked_by"], out["unexpected_blocks"], out["error"]),
                         ([], [], [], [], None))
        self.assertEqual(self.links(), [link(NEW, B1["id"]), link(NEW, B2["id"]), link(689, CHILD["id"])])
        for argv in self.links():
            self.assertNotIn(argv[-1].split("=", 1)[1], NUMBERS)  # a database id, never a number
        calls = self.world.argvs("gh")
        self.assertEqual(calls.count(create()), 1)
        self.assertLess(max(calls.index(get(n)) for n in (555, 688, 689)), calls.index(create()))

    def test_create_with_no_edges_posts_no_link(self):
        self.created_world([], [])
        code, out = self.file()
        self.assertEqual((code, out["verdict"], out["blocked_by"], out["blocks"]), (0, "created", [], []))
        self.assertEqual(self.links(), [])
        self.assertNotIn(get(NEW), self.world.argvs("gh"))

    def test_labels_are_passed_to_the_filing(self):
        self.created_world([], [], labels=["agent:ready", "bug"])
        code, out = self.file("--label", "agent:ready", "--label", "bug")
        self.assertEqual((code, out["verdict"]), (0, "created"))

    def test_a_missing_link_on_read_back_exits_nonzero(self):
        self.created_world([B1], [DOWN])
        code, out = self.file("--blocked-by", "555", "--blocked-by", "688", "--blocks", "689")
        self.assertEqual(code, 1)
        self.assertEqual((out["verdict"], out["issue"], out["missing_blocked_by"], out["missing_blocks"]),
                         ("links_differ", NEW, [688], []))

    def test_a_missing_blocks_link_exits_nonzero(self):
        self.created_world([B1, B2], [])
        code, out = self.file("--blocked-by", "555", "--blocked-by", "688", "--blocks", "689")
        self.assertEqual((code, out["verdict"], out["missing_blocks"]), (1, "links_differ", [689]))

    def test_an_unexpected_link_on_read_back_exits_nonzero(self):
        self.created_world([B1, DOWN], [])
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["unexpected_blocked_by"]), (1, "links_differ", [ref(DOWN)]))

    def test_a_foreign_issue_sharing_the_number_is_not_the_link(self):
        self.created_world([FOREIGN], [])
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["issue"], out["missing_blocked_by"], out["unexpected_blocked_by"]),
                         (1, "links_differ", NEW, [555], ["other/repo#555"]))

    def test_a_listing_entry_without_an_id_is_payload_invalid(self):
        self.created_world([{"number": 555, "repository_url": B1["repository_url"]}], [])
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["error"], out["issue"]), (1, "error", "payload_invalid", NEW))

    def test_a_pull_request_number_files_nothing(self):
        code, out = self.file("--blocked-by", "709")
        self.assertEqual((code, out["verdict"], out["error"], out["issue"]), (1, "error", "not_an_issue", None))
        self.assertEqual(self.posts(), [])

    def test_an_unknown_number_files_nothing(self):
        self.world.not_found("gh", get(999))
        code, out = self.file("--blocks", "999")
        self.assertEqual((code, out["verdict"], out["error"], out["issue"]), (1, "error", "gh_failed", None))
        self.assertEqual(self.posts(), [])

    def test_a_transferred_issue_answered_by_another_repository_files_nothing(self):
        # GitHub redirects a transferred issue's lookup; the destination's same-numbered issue
        # carries a foreign database id and must not be posted as a dependency (COR-002).
        for n, flag in ((555, "--blocked-by"), (689, "--blocks")):
            with self.subTest(flag=flag):
                self.world.respond_json("gh", get(n), dict(FOREIGN, number=n))
                code, out = self.file(flag, str(n))
                self.assertEqual((code, out["error"], out["issue"]), (1, "payload_invalid", None))
                self.assertEqual(self.posts(), [])

    def test_a_lookup_without_a_repository_url_files_nothing(self):
        self.world.respond_json("gh", get(555), {k: v for k, v in B1.items() if k != "repository_url"})
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["error"], out["issue"]), (1, "payload_invalid", None))
        self.assertEqual(self.posts(), [])

    def test_the_repository_is_matched_case_insensitively(self):
        upper = dict(B1, repository_url=B1["repository_url"].upper().replace("HTTPS://API.GITHUB.COM/REPOS", "https://api.github.com/repos"))
        self.created_world([B1], [])
        self.world.respond_json("gh", get(555), upper)
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"]), (0, "created"))

    def test_a_payload_answering_another_number_files_nothing(self):
        self.world.respond_json("gh", get(555), B2)
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["error"], out["issue"]), (1, "payload_invalid", None))
        self.assertEqual(self.posts(), [])

    def test_a_failed_filing_call_is_reported_unconfirmed(self):
        self.world.respond("gh", create(), exit=1, stderr="gh: Bad Gateway (HTTP 502)")
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["error"], out["issue"]), (1, "error", "create_unconfirmed", None))
        self.assertTrue(out["detail"].startswith("gh_failed: "), out["detail"])
        self.assertEqual(self.links(), [])

    def test_a_lost_filing_response_is_reported_unconfirmed(self):
        with mock.patch.object(fm, "create_issue", side_effect=fm.ForgeError("gh_timeout", "api -X POST")):
            code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["error"], out["issue"]), (1, "create_unconfirmed", None))
        self.assertTrue(out["detail"].startswith("gh_timeout: "), out["detail"])
        self.assertEqual(self.links(), [])

    def test_a_failed_link_names_the_filed_issue(self):
        self.world.respond_json("gh", create(), CHILD)
        self.world.respond("gh", link(NEW, B1["id"]), exit=1, stderr="gh: Validation Failed (HTTP 422)")
        code, out = self.file("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["error"], out["issue"]), (1, "error", "gh_failed", NEW))


class LinkTest(Base):
    def link_cmd(self, *extra):
        return run("link", "--repo", SLUG, "--issue", str(NEW), *extra)

    def posting(self, blocked_by, blocking):
        """Patch add_blocked_by so that, once it posts, the forge lists `blocked_by` and `blocking`."""
        real = fm.add_blocked_by

        def post(*args, **kwargs):
            real(*args, **kwargs)
            self.lists(NEW, blocked_by, blocking)
        return mock.patch.object(fm, "add_blocked_by", post)

    def test_link_posts_only_the_missing_edges_then_reads_back(self):
        self.lists(NEW, [B1], [])
        self.world.respond_json("gh", get(NEW), CHILD)
        for argv in (link(NEW, B2["id"]), link(DOWN["number"], CHILD["id"])):
            self.world.respond_json("gh", argv, CHILD)
        with self.posting([B1, B2], [DOWN]):
            code, out = self.link_cmd("--blocked-by", "555", "--blocked-by", "688", "--blocks", "689")
        self.assertEqual((code, out["verdict"], out["blocked_by"], out["blocks"]),
                         (0, "linked", [ref(B1), ref(B2)], [ref(DOWN)]))
        self.assertEqual(self.links(), [link(NEW, B2["id"]), link(689, CHILD["id"])])

    def test_link_with_every_edge_present_posts_nothing(self):
        self.lists(NEW, [B1, DOWN], [])
        code, out = self.link_cmd("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["unexpected_blocked_by"]), (0, "linked", []))
        self.assertEqual(self.posts(), [])

    def test_link_treats_a_foreign_issue_sharing_the_number_as_missing(self):
        self.lists(NEW, [FOREIGN], [])
        self.world.respond_json("gh", link(NEW, B1["id"]), CHILD)
        with self.posting([FOREIGN, B1], []):
            code, out = self.link_cmd("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["blocked_by"]), (0, "linked", sorted([ref(B1), ref(FOREIGN)])))
        self.assertEqual(self.links(), [link(NEW, B1["id"])])

    def test_link_whose_read_back_holds_only_the_foreign_issue_exits_nonzero(self):
        self.lists(NEW, [FOREIGN], [])
        self.world.respond_json("gh", link(NEW, B1["id"]), CHILD)
        code, out = self.link_cmd("--blocked-by", "555")
        self.assertEqual((code, out["verdict"], out["issue"], out["missing_blocked_by"]),
                         (1, "links_differ", NEW, [555]))

    def test_link_whose_read_back_lacks_an_edge_exits_nonzero(self):
        self.lists(NEW, [B1], [])
        self.world.respond_json("gh", link(NEW, B2["id"]), CHILD)
        code, out = self.link_cmd("--blocked-by", "688")
        self.assertEqual((code, out["verdict"], out["issue"], out["missing_blocked_by"]),
                         (1, "links_differ", NEW, [688]))


class UsageTest(Base):
    def test_usage_errors_exit_2_and_call_no_gh(self):
        body = str(self.body_file)
        base = ["create", "--repo", SLUG, "--title", TITLE, "--body-file", body]
        for argv in (
            base + ["--blocked-by", "555", "--blocked-by", "555"],
            base + ["--blocked-by", "555", "--blocks", "555"],
            base + ["--blocked-by", "0"],
            base + ["--blocks", "x"],
            ["create", "--repo", SLUG, "--title", TITLE, "--body-file", body + ".missing"],
            ["create", "--repo", "not a slug", "--title", TITLE, "--body-file", body],
            ["create", "--repo", SLUG, "--title", "  ", "--body-file", body],
            ["create", "--repo", SLUG, "--body-file", body],
            ["link", "--repo", SLUG, "--issue", str(NEW)],
            ["link", "--repo", SLUG, "--issue", str(NEW), "--blocked-by", str(NEW)],
            base + ["--label", "instruction-budget-raise"],
            base + ["--label", "Instruction-Budget-Raise"],
            base + ["--label", " instruction-budget-raise "],
            ["frobnicate"],
            [],
        ):
            with self.subTest(argv=argv):
                code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["error"]), (2, "error", "usage"))
                self.assertEqual(out["command"], argv[0] if argv and argv[0] in ("create", "link") else None)
        self.assertEqual(self.world.argvs("gh"), [])


class CliTest(Base):
    def test_the_module_prints_one_json_line(self):
        self.created_world([B1], [])
        done = subprocess.run([sys.executable, "-m", "agent_tools.forge_issue", "create", "--repo", SLUG,
                               "--title", TITLE, "--body-file", str(self.body_file), "--blocked-by", "555"],
                              capture_output=True, text=True, env=dict(os.environ), timeout=120)
        lines = done.stdout.splitlines()
        self.assertEqual((done.returncode, len(lines)), (0, 1), done.stdout + done.stderr)
        self.assertEqual(json.loads(lines[0])["verdict"], "created")


if __name__ == "__main__":
    unittest.main()
