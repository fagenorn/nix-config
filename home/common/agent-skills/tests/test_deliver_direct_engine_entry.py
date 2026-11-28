"""A session runs `engine deliver`; the delivery programs keep reading the old text unchanged.

The shell examples of the session text are every inline code span, every line of a fenced block and every indented
line, so an example in any of the three forms is judged the same way."""
import hashlib
import json
from pathlib import Path
import re
import unittest

TIER = "fast"

REPO_ROOT = Path(__file__).parents[4]
SKILL = REPO_ROOT / "home/common/agent-skills/skills/deliver-direct/SKILL.md"
COMMANDS = (
    "engine", "git", "gh", "forge-claim", "forge-issue",
    "look-approval", "resolve-project", "verify-pending",
)
# `forge-claim release` is allowed: it frees the claim an engine run holds (the only claim command a session runs).
LIFECYCLE = re.compile(
    r"forge-claim (?:acquire|renew|land|status)|worktree|\bpush\b|\bmerge\b|gh pr (?:create|merge)")
START = "engine deliver <n>"
RELEASE = "forge-claim release --repo <slug> --issue <n> --holder <host>/<run>"
PROGRAM_DIGEST = "7da6115f67b6bcf6a72e7dccf4d13524b118b3f3c79583882ffb1b0f1eaf2280"
FENCE = re.compile(r"^[ \t]*(`{3,})")


def normalized(text):
    return re.sub(r"\s+", " ", text)


def session(text):
    return text[text.index("**Session.**"):text.index("**Delivery programs.**")]


def examples(text):
    """The examples of `text`: fenced and indented lines (stripped), then the inline code spans, in order."""
    found, prose, fence = [], [], None
    for line in text.split("\n"):
        match = FENCE.match(line)
        if fence is None and match:
            fence = len(match.group(1))
        elif fence is not None:
            if match and len(match.group(1)) >= fence and line.strip() == match.group(1):
                fence = None
            elif line.strip():
                found.append(line.strip())
        elif line.startswith(("    ", "\t")) and line.strip():
            found.append(line.strip())
        else:
            prose.append(line)
    return found + re.findall(r"`([^`]+)`", normalized("\n".join(prose)))


def violations(text):
    """The examples of `text` that run a lifecycle command or a command other than the two a session may run."""
    found = []
    for example in examples(text):
        command = example.removeprefix("$ ")
        words = command.split()
        head = words[0].rsplit("/", 1)[-1] if words else ""
        if LIFECYCLE.search(command) or (head in COMMANDS and command not in (START, RELEASE)):
            found.append(example)
    return found


def shell_examples(text):
    return [e for e in examples(text) if e.removeprefix("$ ").split()[0] in COMMANDS]


class DirectLaneEngineEntryTest(unittest.TestCase):
    def read(self):
        return SKILL.read_text(encoding="utf-8")

    def test_the_session_runs_engine_deliver_and_no_lifecycle_command(self):
        text = self.read()
        self.assertIn("**Session.**", text)
        self.assertIn("**Delivery programs.**", text)
        self.assertEqual(violations(session(text)), [])
        self.assertEqual(set(shell_examples(session(text))), {START, RELEASE})

    def test_a_shell_example_in_any_form_is_judged(self):
        host = "**Session.** Start `engine deliver <n>`.\n\n{}\n\n**Delivery programs.** x"
        forms = {
            "inline": "Then run `git push origin HEAD`.",
            "indented": "Then run:\n\n    git push origin HEAD\n",
            "tab indented": "Then run:\n\n\tgh pr merge 1 --merge\n",
            "fenced": "Then run:\n\n```sh\nforge-claim acquire --repo r --issue 1 --holder h\n```\n",
            "unlabeled fence": "Then run:\n\n```\n$ git worktree add x\n```\n",
            "long fence": "Then run:\n\n````bash\n```\ngit commit -m x\n```\n````\n",
            "another command": "Then run:\n\n    git commit -m x\n",
        }
        for name, form in forms.items():
            with self.subTest(name):
                self.assertNotEqual(violations(session(host.format(form))), [])
        for name, form in {"prose": "Never push or merge by hand.", "start": "Run:\n\n    engine deliver <n>\n",
                           "release": f"Run `{RELEASE}`.", "other fence": "```json\n{\"end\": 1}\n```"}.items():
            with self.subTest(name):
                self.assertEqual(violations(session(host.format(form))), [])

    def test_the_session_starts_in_the_background_and_reruns_on_retry(self):
        found = examples(session(self.read()))
        self.assertEqual(shell_examples(session(self.read())).count(START), 2)
        for token in ("run_in_background: true", "end", "need", "detail", "run",
                      "done", "retry", "owner-decision"):
            with self.subTest(token=token):
                self.assertIn(token, found)

    def test_an_owner_stop_is_handled_before_the_generic_rerun(self):
        found = examples(session(self.read()))
        self.assertIn("stopped-by-request", found)
        self.assertLess(found.index("stopped-by-request"), found.index("retry"))
        self.assertLess(found.index("stopped-by-request"), len(found) - 1 - found[::-1].index(START))

    def test_the_lane_stops_send_standard_design_and_marked_issues_elsewhere(self):
        text = normalized(self.read())
        self.assertLess(text.index("**Session.**"), text.index("**Lane stops.**"))
        lane = examples(text[text.index("**Lane stops.**"):text.index("**Delivery programs.**")])
        self.assertEqual(lane.count("deliver-standard"), 2)
        for token in ("ineligible", "look-not-on-engine", "lane: direct"):
            with self.subTest(token=token):
                self.assertIn(token, lane)

    def test_the_engine_claim_is_released_before_the_look_handoff(self):
        text = normalized(self.read())
        lane = examples(text[text.index("**Lane stops.**"):text.index("**Delivery programs.**")])
        self.assertEqual(lane.count(RELEASE), 1)
        self.assertLess(lane.index("look-not-on-engine"), lane.index(RELEASE))
        prose = text[text.index("**Lane stops.**"):text.index("**Delivery programs.**")]
        self.assertLess(prose.index(f"`{RELEASE}`"), prose.rindex("do the same"))

    def test_the_session_holds_no_step_list_and_no_continuation_value(self):
        text = normalized(self.read())
        self.assertIsNone(re.search(r"(?:^|\s)\d+\. \*\*", session(text)))
        self.assertNotIn("cont", examples(session(text)))
        self.assertNotIn("args.cont", session(text))

    def test_the_programs_text_is_the_base_text_byte_for_byte(self):
        raw = self.read()
        start = raw.index("Run `resolve-project resolve")
        self.assertLess(raw.index("**Delivery programs.**"), start)
        self.assertEqual(hashlib.sha256(raw[start:].encode("utf-8")).hexdigest(), PROGRAM_DIGEST)

    def test_the_session_text_stays_within_its_cap(self):
        raw = self.read()
        self.assertLessEqual(len(session(raw).encode("utf-8")), 1280)
        self.assertLessEqual(len(raw.encode("utf-8")), 6400)

    def test_the_eval_cases_point_at_the_programs_steps(self):
        cases = json.loads((SKILL.parent / "evals/evals.json").read_text(encoding="utf-8"))["evals"]
        for case in cases:
            with self.subTest(case=case["id"]):
                self.assertIn("**Delivery programs.**", examples(case["prompt"]))


if __name__ == "__main__":
    unittest.main()
