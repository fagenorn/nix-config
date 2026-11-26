"""Contract tests for `independent-review code` (`agent_tools.delivery.independent_review`).

Each case runs the module as a child process in a real git project with a local bare origin, the
stand-in `codex-companion` (`tests/fixtures/engine-stubbed-run/codex_companion_stub.py`) first on
`PATH`, and reads the one JSON line it printed and the stand-in's log.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

from agent_tools.delivery import independent_review

from .guard_policy_world import GuardPolicyWorld, install_platform_manifest_in_environ

TIER = "integration"  # every case starts the module and the stand-in as processes

setUpModule = install_platform_manifest_in_environ

REPO_ROOT = Path(__file__).resolve().parents[1]
STUB = REPO_ROOT / "tests/fixtures/engine-stubbed-run/codex_companion_stub.py"
SKILL = REPO_ROOT / "home/common/claude-code/skills/codex-collaboration/SKILL.md"
SLUG = "example/review"
ACCEPTANCE = '[{"id": "AC1", "text": "t", "kind": "code"}]'
COMPANION = ["codex-companion", "task", "--fresh", "--reviewer", "diff-review"]
RUNTIME = {"model": "gpt-6.2-astra", "reasoningEffort": "high"}
FINDING = "I1 src/a.py:3 add() drops the carry. confidence: high; unknowns: none"
CLEAN = "## Critical\nNone.\n## Important\nNone.\n## Minor\nNone.\n"


def payload(raw: str) -> str:
    return json.dumps({"status": 0, "touchedFiles": [], "runtime": RUNTIME, "rawOutput": raw})


VALID = {"stdout": payload(f"## Critical\nNone.\n## Important\n- {FINDING}\n## Minor\nNone.\n"), "exit": 0}
CLEAN_ANSWER = {"stdout": payload(CLEAN), "exit": 0}
LIMIT = {"stdout": json.dumps({"status": 1, "error": "You've hit your usage limit. Try again at 12:27."}),
         "exit": 1}


class ReviewCase(unittest.TestCase):
    def arrange(self, answers, *, supported=True, argv=None, files=("src/a.py",)):
        self.world = GuardPolicyWorld(self)
        shims = self.world.tmp / "shims"
        shims.mkdir()
        self.answers_path = shims / "answers.json"
        self.log = shims / "log.jsonl"
        self.answers_path.write_text(json.dumps(answers), encoding="utf-8")
        shim = shims / "codex-companion"
        shim.write_text(f'#!/bin/sh\nexec {sys.executable} {STUB} {self.answers_path} {self.log} "$@"\n',
                        encoding="utf-8")
        shim.chmod(0o755)
        self.world.env["PATH"] = f"{shims}:{self.world.env['PATH']}"

        def mutate(contract):
            if supported:
                contract["capabilities"]["review.code"]["support"] = "supported"
            contract["bindings"]["commands"]["codex-diff-review"]["argv"] = argv or COMPANION

        self.root = self.world.project(SLUG, SLUG, mutate=mutate)
        self.world.git(self.root, "checkout", "--quiet", "-b", "topic")
        for name in files:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x = 1\n", encoding="utf-8")
        self.world.git(self.root, "add", "-A")
        self.world.git(self.root, "commit", "--quiet", "-m", "change")
        self.head = self.world.git(self.root, "rev-parse", "HEAD").strip()
        self.base = self.world.git(self.root, "merge-base", "refs/remotes/origin/main", "HEAD").strip()

    def run_review(self, *extra, routed=("/s/the-bar.md",), raw_routed=None, head="head", merge_base="base"):
        flag = [] if raw_routed is None and routed is None else [
            "--routed-files", json.dumps(list(routed)) if raw_routed is None else raw_routed]
        if head is not None:
            flag += ["--head", self.head if head == "head" else head]
        if merge_base is not None:
            flag += ["--merge-base", self.base if merge_base == "base" else merge_base]
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.independent_review", "code",
             "--repo-root", str(self.root), "--issue", "7", "--worktree-path", str(self.root),
             "--branch", "topic", "--integration-branch", "main", "--acceptance", ACCEPTANCE, *flag, *extra],
            capture_output=True, text=True, timeout=300, env=self.world.env, cwd=self.world.tmp)
        lines = done.stdout.splitlines()
        self.assertEqual(len(lines), 1, done.stdout + done.stderr)
        return done.returncode, json.loads(lines[0])

    def calls(self):
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text(encoding="utf-8").splitlines()]


class ReviewTest(ReviewCase):
    def test_a_configured_companion_review_returns_its_important_finding(self):
        self.arrange([VALID])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "findings"), reply)
        self.assertEqual(reply["findings"], [{"failing_input": "", "file": "src/a.py:3",
                                              "severity": "important", "summary": FINDING}])
        (call,) = self.calls()
        self.assertEqual(call["argv"][-7:], ["--model", "gpt-6.2-astra", "--effort", "high",
                                             "--cwd", str(self.root), "--json"])
        for text in (self.base, self.head, "AC1", "diff-review"):
            self.assertIn(text, call["stdin"])

    def test_routed_files_replace_the_standards_section_of_the_packet(self):
        self.arrange([CLEAN_ANSWER])

        code, reply = self.run_review(routed=["/s/the-bar.md", "/s/stacks/python.md"])

        self.assertEqual(code, 0, reply)
        (call,) = self.calls()
        self.assertIn("Routed files:\n/s/the-bar.md\n/s/stacks/python.md", call["stdin"])
        self.assertNotIn("Standards:", call["stdin"])
        self.assertNotIn("stacks/\n", call["stdin"])

    def test_a_review_without_routed_files_is_a_usage_error(self):
        self.arrange([CLEAN_ANSWER])

        code, reply = self.run_review(routed=None)

        self.assertEqual((code, reply["verdict"]), (2, "error"), reply)
        self.assertEqual(self.calls(), [])

    def test_routed_files_that_are_not_a_list_of_strings_are_a_usage_error(self):
        self.arrange([CLEAN_ANSWER])
        for raw in ('["/s/the-bar.md", 3]', '{"a": 1}'):
            with self.subTest(raw=raw):
                code, reply = self.run_review(raw_routed=raw)

                self.assertEqual((code, reply["verdict"]), (2, "error"), reply)
                self.assertEqual(self.calls(), [])

    def test_a_review_without_the_routed_head_or_with_a_head_that_is_no_commit_id_is_a_usage_error(self):
        self.arrange([CLEAN_ANSWER])
        for head in (None, "HEAD", self.head[:12], self.head.upper()):
            with self.subTest(head=head):
                code, reply = self.run_review(head=head)

                self.assertEqual((code, reply["verdict"]), (2, "error"), reply)
                self.assertEqual(self.calls(), [])

    def test_a_commit_landing_after_routing_is_unavailable_before_any_review_starts(self):
        self.arrange([VALID])
        routed = self.head
        (self.root / "web").mkdir()
        (self.root / "web/page.js").write_text("y = 2\n", encoding="utf-8")
        self.world.git(self.root, "add", "-A")
        self.world.git(self.root, "commit", "--quiet", "-m", "later")

        code, reply = self.run_review(head=routed)

        self.assertEqual((code, reply["verdict"], reply["findings"]), (0, "unavailable", []), reply)
        self.assertIn("head moved since routing", reply["detail"])
        self.assertIn(routed, reply["detail"])
        self.assertEqual(self.calls(), [])

    def test_the_range_is_the_routed_heads(self):
        self.arrange([CLEAN_ANSWER])

        code, reply = self.run_review()

        self.assertEqual(code, 0, reply)
        self.assertIn(f"base {self.base} head {self.head}", reply["raw_summary"])

    def test_the_range_is_the_routed_merge_base_though_the_integration_ref_moved(self):
        self.arrange([CLEAN_ANSWER])
        self.world.git(self.root, "update-ref", "refs/remotes/origin/main", self.head)

        code, reply = self.run_review()

        self.assertEqual(code, 0, reply)
        self.assertIn(f"base {self.base} head {self.head}", reply["raw_summary"])
        (call,) = self.calls()
        self.assertIn(f"Base: {self.base}", call["stdin"])

    def test_a_merge_base_that_is_no_ancestor_of_the_head_is_unavailable(self):
        self.arrange([CLEAN_ANSWER])
        orphan = self.world.git(self.root, "commit-tree", "HEAD^{tree}", "-m", "orphan").strip()
        for merge_base in ("c" * 40, orphan):
            with self.subTest(merge_base=merge_base):
                code, reply = self.run_review(merge_base=merge_base)

                self.assertEqual((code, reply["verdict"], reply["findings"]), (0, "unavailable", []), reply)
                self.assertEqual(self.calls(), [])

    def test_a_review_without_the_routed_merge_base_or_with_one_that_is_no_commit_id_is_a_usage_error(self):
        self.arrange([CLEAN_ANSWER])
        for merge_base in (None, "main", self.base[:12]):
            with self.subTest(merge_base=merge_base):
                code, reply = self.run_review(merge_base=merge_base)

                self.assertEqual((code, reply["verdict"]), (2, "error"), reply)
                self.assertEqual(self.calls(), [])

    def test_an_unsupported_review_code_answers_none_and_starts_nothing(self):
        self.arrange([VALID], supported=False)

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"], reply["findings"]), (0, "none", []))
        self.assertEqual(self.calls(), [])

    def test_a_binding_that_is_not_the_companion_shape_is_unavailable_with_no_call(self):
        self.arrange([VALID], argv=[sys.executable, "-c", "pass"])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "unavailable"), reply)
        self.assertIn("expected codex-companion task [--fresh] --reviewer diff-review", reply["detail"])
        self.assertEqual(self.calls(), [])

    def test_a_usage_limit_twice_is_unavailable_with_the_message(self):
        self.arrange([LIMIT, LIMIT])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "unavailable"), reply)
        self.assertEqual(reply["detail"], "runtime: You've hit your usage limit. Try again at 12:27.")
        self.assertEqual(len(self.calls()), 2)

    def test_a_malformed_first_reply_is_retried_once(self):
        self.arrange([{"stdout": "not json", "exit": 0}, CLEAN_ANSWER])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "pass"), reply)
        self.assertEqual(len(self.calls()), 2)

    def test_a_reply_reporting_effort_xhigh_is_a_schema_failure(self):
        stale = json.dumps({"status": 0, "touchedFiles": [],
                            "runtime": {**RUNTIME, "reasoningEffort": "xhigh"}, "rawOutput": CLEAN})
        self.arrange([{"stdout": stale, "exit": 0}, {"stdout": stale, "exit": 0}])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "unavailable"), reply)
        self.assertTrue(reply["detail"].startswith("payload:"), reply["detail"])

    def test_a_reply_missing_a_heading_is_a_schema_failure(self):
        headless = {"stdout": payload("## Critical\nNone.\n## Important\nNone.\n"), "exit": 0}
        self.arrange([headless, headless])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "unavailable"), reply)
        self.assertTrue(reply["detail"].startswith("schema:"), reply["detail"])


class SliceTest(ReviewCase):
    def test_a_range_over_twenty_product_files_is_reviewed_in_slices_of_twenty(self):
        self.arrange([VALID], files=[f"src/f{n:02d}.py" for n in range(1, 22)])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "findings"), reply)
        self.assertEqual(len(reply["findings"]), 2)
        self.assertEqual(reply["findings"][0], reply["findings"][1])
        stdins = [call["stdin"] for call in self.calls()]
        self.assertEqual(len(stdins), 2)
        first = [s for s in stdins if "scoped to 20 of 21" in s]
        second = [s for s in stdins if "scoped to 1 of 21" in s]
        self.assertEqual((len(first), len(second)), (1, 1))
        self.assertIn("src/f01.py", first[0])
        self.assertNotIn("src/f21.py", first[0])
        self.assertIn("src/f21.py", second[0])
        self.assertNotIn("src/f01.py", second[0])
        for stdin in stdins:
            self.assertNotIn("diff --git", stdin)
        self.assertTrue(reply["raw_summary"].startswith("scope: 2 slices over 21 product files\n"),
                        reply["raw_summary"])
        lines = reply["raw_summary"].splitlines()
        self.assertIn("slice 1: scoped to 20 of 21 product files; findings", lines)
        self.assertIn("slice 2: scoped to 1 of 21 product files; findings", lines)

    def test_a_slice_that_fails_its_retry_is_unavailable_and_keeps_the_other_slices_findings(self):
        limit = {"when": "scoped to 1 of 21",
                 "stdout": json.dumps({"status": 1, "error": "You've hit your usage limit."}), "exit": 1}
        self.arrange([limit, VALID], files=[f"src/f{n:02d}.py" for n in range(1, 22)])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "unavailable"), reply)
        self.assertEqual(reply["detail"], "runtime: You've hit your usage limit.")
        self.assertEqual(len(reply["findings"]), 1)
        self.assertEqual(reply["raw_summary"].splitlines()[-1], "failed slices: 2")
        self.assertEqual(len(self.calls()), 3)

    def test_exactly_twenty_product_files_dispatch_whole(self):
        self.arrange([CLEAN_ANSWER], files=[f"src/f{n:02d}.py" for n in range(1, 21)])

        code, reply = self.run_review()

        self.assertEqual((code, reply["verdict"]), (0, "pass"), reply)
        (call,) = self.calls()
        self.assertNotIn("scoped to", call["stdin"])
        self.assertTrue(reply["raw_summary"].startswith("scope: full"), reply["raw_summary"])


class ParseFindingsTest(unittest.TestCase):
    def test_an_indented_sub_bullet_continues_its_finding_instead_of_opening_one(self):
        raw = ("## Critical\nNone.\n## Important\n- I1 src/a.py:3 add() drops the carry.\n"
               "  - evidence: tests/t.py:9 asserts nothing\n## Minor\nNone.\n")

        self.assertEqual(independent_review.parse_findings(raw), [{
            "failing_input": "", "file": "src/a.py:3", "severity": "important",
            "summary": "I1 src/a.py:3 add() drops the carry. - evidence: tests/t.py:9 asserts nothing"}])


class ContractTest(unittest.TestCase):
    def test_the_tail_matches_the_codex_collaboration_skill(self):
        found = re.search(r"--model (\S+) --effort (\S+)", SKILL.read_text(encoding="utf-8"))

        self.assertEqual(found.groups(), (independent_review.MODEL, independent_review.EFFORT))


if __name__ == "__main__":
    unittest.main()
