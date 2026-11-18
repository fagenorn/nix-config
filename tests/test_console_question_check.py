"""The fixed project question check (#1271): each answer reads its own console records.

Run: just agent-workflow-tests
"""

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from agent_tools.console import event_log, project_question, question_check, view
from agent_tools.verification import verify_exec
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = "home/common/verify-pending/checks/console-question-check"
PROJECT = "owner/p01"
REV = "1" * 40
READ = "/s/project-question-settings/{}.records.json"
T1 = "What shipped, and what is live, in the last 7 days?"
T2 = "What costs the most time or tokens per issue, and is anything in the backlog to improve it?"
T3 = "Why did the most recent failed production run fail?"
TEXTS = (T1, T2, T3)
KEYS = ("a" * 32, "b" * 32, "c" * 32)
START = datetime.fromisoformat("2026-11-20T10:00:00+00:00")


def grounded(qid):
    return "Answer: figures\nRead: " + READ.format(qid)


class Harness:
    """One check scenario: the console's own view code over a list of rows, and the seams."""

    def __init__(self, case, events=None):
        directory = Path(case.enterContext(tempfile.TemporaryDirectory()))
        self.case = case
        self.seq = 0
        self.events = []
        for row in events if events is not None else [self.registered(PROJECT)]:
            self.events.append(row)
        self.state_file = directory / "checks" / "state.json"
        self.result_file = directory / "checks" / "result.json"
        self.token_file = directory / "token"
        self.token_file.write_text("tok\n", encoding="utf-8")
        self.posts = []
        self.saved_before_post = []
        self.views = []
        self.sleeps = []
        self.clock = START
        self.keys = iter(KEYS)
        self.new_keys = 0
        self.rev = REV
        self.after_post = None
        self.view_hook = None

    def row(self, kind, project, payload):
        self.seq += 1
        return event_log.Event(self.seq, f"2026-11-17T10:00:{self.seq:02d}Z", kind, project, payload)

    def registered(self, project):
        return self.row("project.registered", project, {"root": "/srv/" + project.split("/")[1]})

    def asked(self, qid, text, key=None):
        payload = {"question_id": qid, "question": text}
        if key is not None:
            payload["request_key"] = key
        return self.row(event_log.PROJECT_QUESTION_ASKED, PROJECT, payload)

    def answered(self, qid, answer):
        return self.row(event_log.PROJECT_QUESTION_ANSWERED, PROJECT,
                        {"question_id": qid, "outcome": "answered", "answer": answer})

    def settled(self, qid, outcome, reason):
        return self.row(event_log.PROJECT_QUESTION_ANSWERED, PROJECT,
                        {"question_id": qid, "outcome": outcome, "reason": reason})

    def add(self, *rows):
        self.events.extend(rows)

    def seed(self, answers, keys=KEYS):
        """Ask the three fixed questions under `keys` as q1..q3, answered by `answers` (None: working)."""
        for number, (text, key, answer) in enumerate(zip(TEXTS, keys, answers), 1):
            qid = f"q{number}"
            self.add(self.asked(qid, text, key))
            if answer is not None:
                self.add(self.answered(qid, answer))

    # the seams
    def state(self, url):
        if self.view_hook:
            self.view_hook()
        shown = view.derive_view(view.project_states(self.events).values(),
                                 project_questions=project_question.asked_questions(self.events))
        self.views.append(shown)
        return shown

    def post(self, url, token, document):
        keys = {}
        if self.state_file.exists():
            saved = json.loads(self.state_file.read_text(encoding="utf-8"))
            keys = saved["projects"].get(document["project_id"], {}).get("keys", {})
        self.saved_before_post.append(keys.get(document["question"]) == document["request_key"])
        self.posts.append((url, token, document))
        if self.after_post:
            return self.after_post(document)
        return 204, ""

    def now(self):
        return self.clock

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.clock += timedelta(seconds=seconds)

    def new_key(self):
        self.new_keys += 1
        return next(self.keys)

    def revision(self):
        return self.rev

    def run(self, *extra, **seams):
        argv = ["--project", PROJECT, "--token-file", str(self.token_file),
                "--state-file", str(self.state_file), "--result-file", str(self.result_file), *extra]
        wired = dict(state=self.state, post=self.post, now=self.now, sleep=self.sleep,
                     new_key=self.new_key, revision=self.revision)
        wired.update(seams)
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = question_check.main(argv, **wired)
        self.case.assertEqual(err.getvalue(), "")
        lines = out.getvalue().splitlines()
        self.case.assertEqual(len(lines), 1, out.getvalue())
        self.stdout = out.getvalue()
        return code, json.loads(lines[0])

    def result(self):
        return json.loads(self.result_file.read_text(encoding="utf-8"))

    def saved(self):
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def documents(self):
        return [document for _, _, document in self.posts]


def three_posts(keys=KEYS):
    return [{"project_id": PROJECT, "question": text, "request_key": key}
            for text, key in zip(TEXTS, keys)]


class QuestionCheckTest(unittest.TestCase):
    def test_a_first_run_asks_each_fixed_question_once_under_a_saved_key_and_waits(self):
        quiet = [Harness(self, []).registered(f"owner/p0{n}") for n in range(1, 6)]
        for name, events in (("one project", None), ("a quiet group", quiet)):
            with self.subTest(name):
                h = Harness(self, events)
                code, line = h.run()
                self.assertEqual((code, line["status"]), (75, "waiting"))
                self.assertEqual(h.documents(), three_posts())
                self.assertEqual(h.saved_before_post, [True, True, True])
                self.assertEqual({token for _, token, _ in h.posts}, {"tok"})
                self.assertGreaterEqual(sum(h.sleeps), 480)
                self.assertLessEqual(sum(h.sleeps), 480 + question_check.POLL_SECONDS)
                self.assertEqual(h.saved(), {"projects": {PROJECT: {
                    "revision": REV, "keys": dict(zip(TEXTS, KEYS))}}})
                if events is not None:
                    shown = h.views[0]
                    self.assertEqual([e["type"] for e in shown["entries"]], ["quiet_group"])
                    self.assertIsNone(shown["entries"][0]["projects"][0]["questions"])

    def test_a_rerun_of_the_same_revision_after_an_interruption_posts_the_saved_keys_once(self):
        h = Harness(self)
        old = ("d" * 32, "e" * 32, "f" * 32)
        h.state_file.parent.mkdir(parents=True)
        h.state_file.write_text(json.dumps({"projects": {PROJECT: {
            "revision": REV, "keys": dict(zip(TEXTS, old))}}}), encoding="utf-8")
        code, line = h.run()
        self.assertEqual((code, line["status"]), (75, "waiting"))
        self.assertEqual(h.documents(), three_posts(old))
        self.assertEqual(h.new_keys, 0)

    def test_an_older_revisions_answered_questions_are_never_judged(self):
        h = Harness(self)
        old = ("d" * 32, "e" * 32, "f" * 32)
        h.state_file.parent.mkdir(parents=True)
        h.state_file.write_text(json.dumps({"projects": {PROJECT: {
            "revision": "0" * 40, "keys": dict(zip(TEXTS, old))}}}), encoding="utf-8")
        h.seed([grounded("q1"), grounded("q2"), grounded("q3")], keys=old)
        code, line = h.run()
        self.assertEqual((code, line["status"]), (75, "waiting"))
        self.assertEqual(h.documents(), three_posts())
        self.assertEqual(h.saved(), {"projects": {PROJECT: {
            "revision": REV, "keys": dict(zip(TEXTS, KEYS))}}})
        result = h.result()
        self.assertEqual(result["revision"], REV)
        self.assertEqual([q["shown"] for q in result["questions"]], [None] * 3)

    def test_an_accepted_post_whose_response_was_lost_is_found_and_not_posted_again(self):
        h = Harness(self)

        def lost(document):
            number = len(h.posts)
            h.add(h.asked(f"q{number}", document["question"], document["request_key"]),
                  h.answered(f"q{number}", grounded(f"q{number}")))
            return None, "the console did not answer"

        h.after_post = lost
        code, line = h.run()
        self.assertEqual((code, line["status"], len(h.posts)), (0, "met", 3))
        h.after_post = None
        code, line = h.run()
        self.assertEqual((code, line["status"], len(h.posts)), (0, "met", 3))

    def test_an_owners_question_with_the_same_text_is_never_judged(self):
        for key in (None, "9" * 32):
            with self.subTest(key=key):
                h = Harness(self)
                h.seed([grounded("q1"), grounded("q2"), grounded("q3")], keys=(key,) * 3)
                code, line = h.run()
                self.assertEqual((code, line["status"]), (75, "waiting"))
                self.assertEqual(h.documents(), three_posts())

    def test_three_answers_that_read_their_own_records_are_met(self):
        h = Harness(self)
        h.seed([grounded("q1"), grounded("q2"), grounded("q3")])
        code, line = h.run()
        self.assertEqual((code, line["status"], line["verdicts"]), (0, "met", ["grounded"] * 3))
        questions = h.result()["questions"]
        self.assertEqual([q["shown"]["id"] for q in questions], ["q1", "q2", "q3"])
        last = {q["id"]: q for t in h.views[-1]["entries"][0]["questions"]["threads"]
                for q in t["questions"]}
        for question in questions:
            self.assertEqual(question["shown"], last[question["shown"]["id"]])

    def test_a_citation_in_the_prompts_path_formats_is_grounded(self):
        path = READ.format("q2")
        for read in ("`" + path + "`", "flake.nix, " + path + ":1-40.",
                     "the records file (" + path + ")", "- " + path):
            with self.subTest(read=read):
                h = Harness(self)
                h.seed([grounded("q1"), "Answer: x\nRead: " + read, grounded("q3")])
                code, line = h.run()
                self.assertEqual(line["verdicts"][1], "grounded")
        self.assertIs(question_check.cites(None, "q2.records.json"), False)

    def test_another_file_a_backup_or_a_missing_citation_is_ungrounded(self):
        for answer in ("Answer: x\nRead: " + READ.format("q1"),
                       "Answer: x\nRead: " + READ.format("q2") + ".bak",
                       "Answer: x\nRead: /s/xq2.records.json",
                       "Answer: x\nRead: flake.nix",
                       "Answer: x",
                       "Answer: x\nRead: none",
                       "Read: " + READ.format("q2")):
            with self.subTest(answer=answer):
                h = Harness(self)
                h.seed([grounded("q1"), answer, grounded("q3")])
                code, line = h.run()
                self.assertEqual((code, line["status"]), (1, "not_met"))
                self.assertEqual(line["verdicts"][1], "ungrounded")

    def test_a_failed_or_timed_out_question_is_not_met(self):
        for outcome, reason in (("failed", "the session broke"), ("timed_out", "ran too long")):
            with self.subTest(outcome=outcome):
                h = Harness(self)
                h.add(h.asked("q1", T1, KEYS[0]), h.settled("q1", outcome, reason))
                h.add(h.asked("q2", T2, KEYS[1]), h.answered("q2", grounded("q2")),
                      h.asked("q3", T3, KEYS[2]), h.answered("q3", grounded("q3")))
                code, line = h.run()
                self.assertEqual(code, 1)
                self.assertIn("failed", line["verdicts"])
                self.assertIn(reason, h.result()["questions"][0]["shown"]["state_text"])

    def test_it_waits_within_the_run_until_the_answers_settle(self):
        h = Harness(self)
        reads = []

        def after_post(document):
            number = len(h.posts)
            h.add(h.asked(f"q{number}", document["question"], document["request_key"]))
            return 204, ""

        def on_read():
            reads.append(1)
            if len(reads) == 3:
                h.add(*(h.answered(f"q{n}", grounded(f"q{n}")) for n in (1, 2, 3)))

        h.after_post, h.view_hook = after_post, on_read
        code, line = h.run()
        self.assertEqual((code, line["status"]), (0, "met"))
        self.assertEqual(len(h.sleeps), 2)
        self.assertEqual(len(h.posts), 3)

    def test_no_revision_no_console_no_project_or_no_token_posts_nothing(self):
        cases = [("no_revision", 2), ("not_running", 75), ("not_registered", 75), ("no_token", 75)]
        for status, code in cases:
            with self.subTest(status):
                h = Harness(self, None if status != "not_registered" else [])
                seams = {}
                if status == "no_revision":
                    seams["revision"] = lambda: None
                elif status == "not_running":
                    seams["state"] = lambda url: None
                elif status == "no_token":
                    h.token_file.unlink()
                got = h.run(**seams)
                self.assertEqual((got[0], got[1]["status"]), (code, status))
                self.assertEqual(h.posts, [])

    def test_a_refused_question_keeps_its_key_and_its_reason_stays_local(self):
        h = Harness(self)
        refusals = iter([(409, "the console is stopping LOCAL-ONLY-7f3a")])
        h.after_post = lambda document: next(refusals, (204, ""))
        code, line = h.run()
        self.assertEqual((code, line["verdicts"][0]), (75, "refused"))
        self.assertEqual(set(line), {"status", "verdicts", "result_file"})
        self.assertNotIn("LOCAL-ONLY-7f3a", h.stdout)
        self.assertNotIn("stopping", h.stdout)
        self.assertEqual(h.result()["questions"][0]["post"],
                         "refused: 409: the console is stopping LOCAL-ONLY-7f3a")
        self.assertEqual(h.saved()["projects"][PROJECT]["keys"][T1], KEYS[0])
        h.posts.clear()
        h.run()
        self.assertEqual(h.documents(), three_posts())

    def test_the_result_file_keeps_every_answer_section(self):
        h = Harness(self)
        text = project_question.answer_text(
            "Answer: I cannot tell.\nRead: " + READ.format("q1")
            + "\nCould not find out: which host is deployed\n"
            "Question for you: Which export should I run?\n- The free summary\n- The paid export", ())
        h.seed([text, grounded("q2"), grounded("q3")])
        h.run()
        shown = h.result()["questions"][0]["shown"]
        self.assertEqual(shown["unknown_text"], "Could not find out: which host is deployed")
        self.assertEqual(shown["back_text"], "Question for you: Which export should I run?")
        self.assertEqual(shown["back_choices"], ["The free summary", "The paid export"])
        self.assertEqual(shown["production_text"], project_question.NO_PRODUCTION_LINE)
        self.assertIn(shown, [q for t in h.views[-1]["entries"][0]["questions"]["threads"]
                              for q in t["questions"]])

    def test_stdout_holds_no_answer_and_stays_under_the_runner_limit(self):
        h = Harness(self)
        answers = [f"Answer: {c * 5000}\nRead: " + READ.format(f"q{n}")
                   for n, c in enumerate("xyz", 1)]
        h.seed(answers)
        code, line = h.run()
        self.assertEqual(code, 0)
        self.assertLess(len(h.stdout), verify_exec.OUTPUT_LIMIT)
        for needle in [c * 40 for c in "xyz"] + list(TEXTS):
            self.assertNotIn(needle, h.stdout)
        result = h.result()
        for question, c in zip(result["questions"], "xyz"):
            self.assertEqual(question["shown"]["answer"], c * 5000)
        self.assertEqual(h.result_file.stat().st_mode & 0o777, 0o600)

    def test_a_named_run_is_the_third_question(self):
        self.assertEqual(question_check.questions("deploy-42")[2],
                         "Why did production run deploy-42 fail?")
        self.assertEqual(question_check.questions(None)[2],
                         "Why did the most recent failed production run fail?")

    def test_the_wrapper_is_executable_in_the_index_and_runs_the_module(self):
        listed = subprocess.run(["git", "ls-files", "-s", WRAPPER], cwd=ROOT,
                                capture_output=True, text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755"), listed)
        last = (ROOT / WRAPPER).read_text(encoding="utf-8").splitlines()[-1]
        self.assertEqual(
            last, 'PYTHONPATH=python exec python3 -m agent_tools.console.question_check "$@"')

    def test_an_off_loopback_url_is_refused(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            question_check.main(["--project", "x", "--url", "http://example.com"])
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
