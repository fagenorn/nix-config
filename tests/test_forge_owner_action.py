"""forge-claim owner-action (issue 636): decision, conflict and needs-label markers against the fake gh."""
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

from agent_tools import forge_claim
from agent_tools import forge_markers as fm
from agent_tools import forge_owner_action as foa
from .forge_world import ForgeWorld

SLUG, ISSUE = "octo/widgets", 7
ME = "h1/b1"
T0 = "2026-11-06T10:00:00Z"
OA_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-action", "-f", "color=D93F0B"]
OA_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-action"]
OA_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-action"]
IP_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=in-progress", "-f", "color=FBCA04"]
IP_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=in-progress"]
IP_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/in-progress"]
OK_ENSURE = ["api", "-X", "POST", f"repos/{SLUG}/labels", "-f", "name=owner-answered", "-f", "color=0E8A16"]
OK_ADD = ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/labels", "-f", "labels[]=owner-answered"]
OK_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/owner-answered"]
REPO_ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = [{"question": "Which host runs the paid smoke test?", "options": ["Run it on host one.", "Run it on host two."]},
             {"question": "May the delivery push the scratch branch?", "options": ["Approve: push the scratch branch."]}]


OLD = "2026-11-01T00:00:00Z"  # the store's server clock is T0, more than 24 hours later
NOW = ["api", "--include", "rate_limit"]


def comment(cid, body, association="OWNER", login="octo", updated_at=T0):
    return {"id": cid, "body": body, "updated_at": updated_at, "created_at": updated_at,
            "author_association": association, "user": {"login": login}}


def marker_body(reason="decision", items=("Which flag?",), holder=ME):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": reason, "holder": holder},
                     foa.SENTENCES[reason], "\n".join(f"- {item}" for item in items))


def box_body(questions=QUESTIONS, ticks=(), clears=None, round_no=1):
    """A decision prompt; `ticks` holds (question index, option index) pairs to tick."""
    fields = {"issue": str(ISSUE), "reason": "decision", "holder": ME, "round": str(round_no),
              "opts": foa.options_digest(questions), **({"clears": clears} if clears else {})}
    lines = []
    for qi, q in enumerate(questions):
        lines += ["", f"**Q{qi + 1}.** {q['question']}"]
        lines += [f"- [{'x' if (qi, oi) in ticks else ' '}] {o}" for oi, o in enumerate(q["options"])]
    return fm.render("owner-action", fields, foa.SENTENCES["decision"], "\n".join(lines))


def claim_body(holder=ME):
    return fm.render("claim", {"issue": str(ISSUE), "holder": holder}, f"Claimed by {holder}.")


def stale_body(claim_id, holder=ME):
    return fm.render("owner-action", {"issue": str(ISSUE), "reason": "stale-claim", "claim": str(claim_id)},
                     f"The claim of {holder} has had no renewal, push or pull request activity for 24 hours.",
                     "- [ ] Release this claim")


def post(body):
    return ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f", f"body={body}"]


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = forge_claim.main(list(argv))
    lines = out.getvalue().splitlines()
    assert len(lines) == 1, out.getvalue()
    return code, json.loads(lines[0])


def action(name, reason="decision", *extra):
    return ["owner-action", name, "--repo", SLUG, "--issue", str(ISSUE), "--reason", reason, *extra]


class Base(unittest.TestCase):
    def setUp(self):
        self.slept = []
        patcher = mock.patch.object(forge_claim, "sleep", self.slept.append)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.world = ForgeWorld(self)
        for argv in (OA_ENSURE, OA_ADD, OA_REMOVE, IP_ENSURE, IP_ADD, IP_REMOVE, OK_ENSURE, OK_ADD, OK_REMOVE):
            self.world.respond("gh", argv)
        self.world.respond("gh", NOW, stdout="HTTP/2.0 200 OK\nDate: Fri, 06 Nov 2026 10:00:00 GMT\n\n{}")
        self.tmp = Path(tempfile.mkdtemp())

    def store(self, *comments, next_id=40):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=next_id)

    def items(self, value):
        path = self.tmp / f"items-{len(list(self.tmp.iterdir()))}.json"  # one file per call
        path.write_text(value if isinstance(value, str) else json.dumps(value), encoding="utf-8")
        return str(path)

    def mutations(self):
        return [argv for argv in self.world.argvs("gh") if "-X" in argv]

    def live(self):
        markers = [m for m in (fm.parse(c) for c in self.world.stored()) if m]
        return [m.comment_id for m in markers if m.kind == "owner-action" and fm.is_live(m, markers)]

    def post_argv(self, reason="conflict", items=("Which flag?",)):
        return action("post", reason, "--holder", ME, "--items-file", self.items(list(items)))


class PostTest(Base):
    def test_label_constants_match_forge_claim(self):
        self.assertEqual((foa.KIND, foa.LABEL), (forge_claim.OWNER_ACTION_KIND, forge_claim.OWNER_ACTION))

    def test_post_writes_one_marker_with_its_items_and_the_label(self):
        self.store()
        code, out = run(*self.post_argv(items=("Which flag?", "Which  host?\n now")))
        self.assertEqual((code, out["verdict"], out["comment_id"], out["holder"]), (0, "posted", 40, ME))
        body = marker_body("conflict", items=("Which flag?", "Which host? now"))
        self.assertTrue(body.startswith(
            f"<!-- agent:owner-action v1 issue={ISSUE} reason=conflict holder={ME} -->\n"))
        self.assertEqual(self.mutations(), [post(body), OA_ENSURE, OA_ADD])

    def test_post_re_adopts_a_live_marker_of_the_same_reason(self):
        self.store(comment(30, marker_body("conflict")))
        code, out = run(*self.post_argv())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_posted", 30))
        self.assertEqual(self.mutations(), [OA_ENSURE, OA_ADD])

    def test_post_after_an_ended_marker_posts_again(self):
        self.store(comment(30, marker_body("conflict")), comment(31, fm.end_body(30, "resolved")))
        code, out = run(*self.post_argv())
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))

    def test_each_reason_has_its_own_marker(self):
        self.store(comment(30, marker_body("needs-label")))
        code, out = run(*self.post_argv("conflict", ("Merge conflict in a.py",)))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertEqual(self.live(), [30, 40])

    def test_bad_items_and_reasons_are_usage_errors_before_any_gh_call(self):
        self.store()
        cases = [self.items("not json"), self.items([]), self.items([""]), self.items(["  "]),
                 self.items([1]), self.items({"a": "b"}), self.items(["q"] * 21), str(self.tmp / "missing.json")]
        for index, path in enumerate(cases):
            with self.subTest(case=index):
                code, out = run(*action("post", "conflict", "--holder", ME, "--items-file", path))
                self.assertEqual((code, out["verdict"], out["error"], out["command"]), (2, "error", "usage", "owner-action"))
        code, out = run(*action("post", "stale-claim", "--holder", ME, "--items-file", self.items(["q"])))
        self.assertEqual((code, out["error"]), (2, "usage"))
        self.assertEqual(self.world.argvs("gh"), [])


class EndTest(Base):
    def test_end_ends_every_live_marker_of_the_reason_and_drops_the_label(self):
        self.store(comment(30, marker_body()))
        code, out = run(*action("end"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "ended", [30]))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "resolved")), OK_REMOVE, OA_REMOVE])
        self.assertEqual(self.live(), [])

    def test_end_keeps_the_label_while_another_owner_action_lives(self):
        self.store(comment(30, marker_body()), comment(31, marker_body("conflict", ("x",))))
        code, out = run(*action("end"))
        self.assertEqual((code, out["ended"]), (0, [30]))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "resolved")), OK_REMOVE])

    def test_end_with_nothing_live_is_none(self):
        self.store()
        code, out = run(*action("end", "conflict"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "none", []))
        self.assertEqual(self.mutations(), [])

    def test_a_decision_end_with_nothing_live_still_clears_the_labels(self):
        self.store()
        code, out = run(*action("end"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "none", []))
        self.assertEqual(self.mutations(), [OK_REMOVE, OA_REMOVE])


class StatusTest(Base):
    def test_status_without_replies_is_open_and_without_marker_is_none(self):
        self.store(comment(30, marker_body()), comment(31, "do X", "NONE", "stranger"))
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")
        self.assertEqual(run(*action("status", "conflict"))[1]["verdict"], "none")


class DecisionBoxTest(Base):
    def post_q(self, value=QUESTIONS, *extra):
        return run(*action("post", "decision", "--holder", ME, "--questions-file", self.items(value), *extra))

    def test_post_renders_each_question_with_one_box_per_option(self):
        self.store()
        code, out = self.post_q()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertEqual(self.mutations(), [post(box_body()), OA_ENSURE, OA_ADD])

    def test_clears_is_recorded_on_the_marker(self):
        self.store()
        self.post_q(QUESTIONS, "--clears", "agent:human-required")
        self.assertEqual(self.mutations()[0], post(box_body(clears="agent:human-required")))

    def test_usage_errors_come_before_any_gh_call(self):
        self.store()
        bad = [[], [{"question": "Q?", "options": []}], [{"question": "Q?", "options": ["a", "a"]}],
               [{"question": " ", "options": ["a"]}], [{"question": "Q?", "options": ["a"], "x": 1}],
               [{"question": "Q?", "options": [str(i) for i in range(foa.MAX_OPTIONS + 1)]}], ["Q?"]]
        for value in bad:
            with self.subTest(value=value):
                code, out = self.post_q(value)
                self.assertEqual((code, out["error"]), (2, "usage"))
        for argv in (action("post", "decision", "--holder", ME, "--items-file", self.items(["Which?"])),
                     action("post", "conflict", "--holder", ME, "--questions-file", self.items(QUESTIONS)),
                     action("post", "conflict", "--holder", ME, "--items-file", self.items(["x"]), "--clears", "a"),
                     action("post", "decision", "--holder", ME, "--questions-file", self.items(QUESTIONS),
                            "--clears", "a b"),
                     action("post", "decision", "--holder", ME, "--questions-file", self.items(QUESTIONS),
                            "--items-file", self.items(["x"])),
                     action("post", "conflict", "--holder", ME, "--questions-file", self.items(QUESTIONS),
                            "--items-file", self.items(["x"]))):
            with self.subTest(argv=argv):
                self.assertEqual(run(*argv)[0], 2)
        self.assertEqual(self.world.argvs("gh"), [])

    def test_status_reads_a_ticked_approve_box_as_answered(self):
        one = [QUESTIONS[1]]
        self.store(comment(30, box_body(one, ticks={(0, 0)})))
        code, out = run(*action("status"))
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "answered", 30))
        self.assertEqual(out["questions"], [dict(one[0], chosen="Approve: push the scratch branch.", comment_id=30)])
        self.assertEqual(out["decisions"],
                         "May the delivery push the scratch branch? Chosen: Approve: push the scratch branch.")
        self.assertEqual(self.mutations(), [])

    def test_status_reads_one_ticked_option_per_question_as_answered(self):
        self.store(comment(30, box_body(ticks={(0, 1), (1, 0)})))
        out = run(*action("status"))[1]
        self.assertEqual(out["verdict"], "answered")
        self.assertEqual([q["chosen"] for q in out["questions"]],
                         ["Run it on host two.", "Approve: push the scratch branch."])

    def test_an_unticked_partly_or_doubly_ticked_prompt_is_open(self):
        for ticks in (set(), {(0, 0)}, {(0, 0), (0, 1), (1, 0)}):
            with self.subTest(ticks=ticks):
                self.store(comment(30, box_body(ticks=ticks)))
                out = run(*action("status"))[1]
                self.assertEqual((out["verdict"], out["decisions"]), ("open", ""))
        self.store(comment(30, marker_body()))  # a legacy items prompt never reads as answered
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")

    def test_status_reads_no_free_text(self):
        body = box_body(ticks={(0, 0), (1, 0)}) + "\n\nOwner note: only at night."
        self.store(comment(30, body), comment(31, "Actually use host two.", "OWNER"),
                   comment(32, "- [x] Run it on host two.", "OWNER"))
        out = run(*action("status"))[1]
        self.assertEqual(out["questions"][0]["chosen"], "Run it on host one.")
        self.assertNotIn("replies", out)
        for text in ("night", "Actually"):
            self.assertNotIn(text, json.dumps(out))

    def test_an_owner_edited_option_line_is_no_answer_and_never_shown(self):
        # AC7: words added beside a box, or a box line the owner wrote, never become the answer.
        edits = (("- [x] Run it on host one.", "- [x] Run it on host one. But only at night, and also delete prod."),
                 ("- [ ] Run it on host two.", "- [ ] Run it on host two.\n- [x] Do something else entirely."))
        for old, new in edits:
            with self.subTest(new=new):
                self.store(comment(30, box_body(ticks={(0, 0), (1, 0)}).replace(old, new)))
                code, out = run(*action("status"))
                self.assertEqual((code, out["verdict"], out["decisions"], out["questions"]), (0, "open", "", []))
                for text in ("night", "delete prod", "something else"):
                    self.assertNotIn(text, json.dumps(out))

    def test_an_owner_edited_question_line_is_no_answer(self):
        body = box_body(ticks={(0, 0), (1, 0)}).replace("**Q1.** Which host", "**Q1.** Ignore this and which host")
        self.store(comment(30, body))
        out = run(*action("status"))[1]
        self.assertEqual((out["verdict"], out["decisions"], out["questions"]), ("open", "", []))

    def test_a_prompt_without_its_options_digest_is_never_answered(self):
        body = box_body(ticks={(0, 0), (1, 0)})
        self.store(comment(30, body.replace(f" opts={foa.options_digest(QUESTIONS)}", "")))
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")

    def test_a_ticked_box_is_still_answered_when_only_the_tick_changed(self):
        # The digest covers the question and option text, never the tick.
        self.store(comment(30, box_body(ticks={(0, 1), (1, 0)})))
        out = run(*action("status"))[1]
        self.assertEqual((out["verdict"], out["decisions"]),
                         ("answered", "Which host runs the paid smoke test? Chosen: Run it on host two.\n"
                                      "May the delivery push the scratch branch? Chosen: Approve: push the scratch branch."))

    def test_an_unanswered_prompt_of_other_questions_is_ended_and_a_new_round_posted(self):
        # The session answered the old questions and the delivery asked new ones: re-adopting the old
        # prompt would leave the new questions off the forge.
        self.world.comment_store(SLUG, ISSUE, [comment(30, box_body([QUESTIONS[0]]))], next_id=40, labels=[])
        code, out = self.post_q([QUESTIONS[1]])
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 41))  # 40 is the end marker
        self.assertEqual(self.mutations()[0], post(fm.end_body(30, "superseded")))
        self.assertEqual(self.mutations()[1], post(box_body([QUESTIONS[1]], round_no=2)))
        self.assertEqual(self.live(), [41])
        status = run(*action("status"))[1]
        self.assertEqual([q["question"] for q in status["questions"]], [QUESTIONS[1]["question"]])

    def test_a_later_round_is_posted_beside_an_answered_prompt_and_both_are_read(self):
        # `labels=[]` makes the fake stamp posted comments OWNER, so the trusted status read sees the new round.
        self.world.comment_store(SLUG, ISSUE, [comment(30, box_body(ticks={(0, 0), (1, 0)}))], next_id=40,
                                 labels=[])
        code, out = self.post_q([QUESTIONS[1]])
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertEqual(self.mutations()[0], post(box_body([QUESTIONS[1]], round_no=2)))
        self.assertEqual(self.live(), [30, 40])
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")

    def re_adopts(self, body):
        self.store(comment(30, body))
        code, out = self.post_q()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "already_posted", 30))
        self.assertEqual(self.mutations(), [OA_ENSURE, OA_ADD])

    # One test per body: the fake's call log is never cleared by `store`, so a loop would accumulate.
    def test_a_live_partly_ticked_prompt_is_re_adopted(self):
        self.re_adopts(box_body(ticks={(0, 0)}))

    def supersedes_and_posts(self, body, round_no):
        # A prompt that carries no options digest can never be answered, so re-adopting it would keep
        # the new questions off the forge for good: it is ended and a new round posted.
        self.world.comment_store(SLUG, ISSUE, [comment(30, body)], next_id=40, labels=[])
        code, out = self.post_q()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 41))
        self.assertEqual(self.mutations()[0], post(fm.end_body(30, "superseded")))
        self.assertEqual(self.mutations()[1], post(box_body(round_no=round_no)))
        self.assertEqual(self.live(), [41])
        status = run(*action("status"))[1]
        self.assertEqual(status["verdict"], "open")
        self.assertEqual([q["question"] for q in status["questions"]], [q["question"] for q in QUESTIONS])

    def test_a_live_legacy_prompt_is_superseded_by_a_new_round(self):
        self.supersedes_and_posts(marker_body(), 1)

    def test_a_live_prompt_without_its_options_digest_is_superseded_by_a_new_round(self):
        self.supersedes_and_posts(box_body().replace(f" opts={foa.options_digest(QUESTIONS)}", ""), 2)

    def test_untrusted_markers_never_suppress_or_round_a_post(self):
        self.store(comment(30, box_body(ticks={(0, 0), (1, 0)})),
                   comment(31, box_body(round_no=7), "NONE"),           # an untrusted unanswered prompt
                   comment(32, fm.end_body(30, "resolved"), "NONE"))    # an untrusted end of the real one
        code, out = self.post_q()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertEqual(self.mutations()[0], post(box_body(round_no=2)))
        self.assertEqual(run(*action("status"))[1]["questions"][0]["comment_id"], 30)

    def test_an_untrusted_same_round_prompt_never_wins_the_contest(self):
        self.store(comment(31, box_body(round_no=1), "NONE"))  # smaller than the new comment, same round
        code, out = self.post_q()
        self.assertEqual((code, out["verdict"], out["comment_id"]), (0, "posted", 40))
        self.assertNotIn(["api", "-X", "DELETE", f"repos/{SLUG}/issues/comments/40"], self.mutations())

    def test_the_round_counts_ended_prompts_too(self):
        self.store(comment(30, box_body(ticks={(0, 0), (1, 0)}, round_no=3)), comment(31, fm.end_body(30, "resolved")))
        self.post_q()
        self.assertEqual(self.mutations()[0], post(box_body(round_no=4)))

    def test_box_lines_before_any_question_header_are_ignored(self):
        body = fm.render("owner-action", {"issue": str(ISSUE), "reason": "decision", "holder": ME},
                         foa.SENTENCES["decision"], "- [x] stray\n- [ ] other")
        self.assertEqual(foa.read_questions(body), [])

    def test_end_never_ends_an_untrusted_decision_prompt(self):
        self.store(comment(30, box_body(ticks={(0, 0), (1, 0)})), comment(31, box_body(round_no=2), "NONE"))
        code, out = run(*action("end"))
        self.assertEqual((code, out["ended"]), (0, [30]))

    def test_a_retried_end_repairs_both_labels(self):
        self.world.comment_store(SLUG, ISSUE, [comment(30, box_body(ticks={(0, 0), (1, 0)}))], next_id=40,
                                 labels=["owner-action", "owner-answered"], fail_once=["remove_label"])
        self.assertEqual(run(*action("end"))[0], 1)            # the end posted, the label removal failed
        self.assertEqual(self.live(), [])
        code, out = run(*action("end"))                         # the retry finds nothing live
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "none", []))
        self.assertEqual(self.world.issue()["labels"], [])

    def test_end_drops_both_labels(self):
        self.store(comment(30, box_body(ticks={(0, 0), (1, 0)})), comment(31, box_body(round_no=2)))
        code, out = run(*action("end"))
        self.assertEqual((code, out["verdict"], out["ended"]), (0, "ended", [30, 31]))
        self.assertEqual(self.mutations(), [post(fm.end_body(30, "resolved")), post(fm.end_body(31, "resolved")),
                                            OK_REMOVE, OA_REMOVE])

    def test_no_text_says_reply_on_this_issue(self):
        roots = [REPO_ROOT / "python/agent_tools", REPO_ROOT / "home/common/claude-code/skills",
                 REPO_ROOT / "home/common/agent-skills/skills", REPO_ROOT / "home/common/agent-skills/standards"]
        def hits(phrase, among):
            return [str(p) for root in among for p in root.rglob("*") if p.is_file()
                    and p.suffix in (".py", ".js", ".md") and phrase in p.read_text(encoding="utf-8").lower()]
        self.assertEqual(hits("reply on this issue", roots), [])
        self.assertEqual(hits("say how", roots[:1]), [])
        self.assertNotIn("say how", " ".join(foa.SENTENCES.values()))


class ClaimInteractionTest(Base):
    def common(self, command):
        return [command, "--repo", SLUG, "--issue", str(ISSUE), "--holder", ME]

    def test_renew_and_release_never_end_a_decision_marker(self):
        self.store(comment(5, claim_body()), comment(30, marker_body()))
        self.assertEqual(run(*self.common("renew"))[1]["verdict"], "renewed")
        self.assertEqual(run(*self.common("release"))[1]["verdict"], "released")
        self.assertEqual(self.live(), [30])
        self.assertNotIn(OA_REMOVE, self.mutations())

    def test_status_of_a_free_issue_never_ends_a_decision_marker(self):
        self.store(comment(30, marker_body()))
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "free")
        self.assertEqual(self.live(), [30])

    def test_status_of_a_stale_claim_keeps_a_decision_marker_and_its_label(self):
        # The batch keeps its claim while the owner thinks; 24 h later the claim is stale and the
        # relaunch's facts agent runs `forge-claim status` before `owner-action status`.
        self.store(comment(5, claim_body(), updated_at=OLD), comment(30, marker_body(), updated_at=OLD),
                   next_id=40)
        code, out = run(*self.common("status"))
        self.assertEqual((code, out["verdict"], out["owner_action_comment_id"]), (0, "stale", 40))
        self.assertEqual(self.live(), [30, 40])  # the decision marker and the new stale-claim marker
        self.assertNotIn(OA_REMOVE, self.mutations())
        self.assertNotIn(post(fm.end_body(30, "released")), self.mutations())
        self.assertEqual(run(*action("status"))[1]["verdict"], "open")

    def test_status_of_a_stale_claim_still_retires_an_obsolete_stale_claim_marker(self):
        # Unchanged behaviour for markers that name a claim: one naming an older, ended claim goes.
        self.store(comment(3, claim_body("h2/b9"), updated_at=OLD), comment(4, fm.end_body(3, "done"), updated_at=OLD),
                   comment(5, claim_body(), updated_at=OLD), comment(20, stale_body(3, "h2/b9"), updated_at=OLD),
                   comment(30, marker_body(), updated_at=OLD), next_id=40)
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "stale")
        self.assertIn(post(fm.end_body(20, "released")), self.mutations())
        self.assertIn(30, self.live())

    def test_fresh_claim_status_and_release_keep_a_decision_marker_and_its_label(self):
        self.store(comment(5, claim_body()), comment(30, marker_body()), comment(31, marker_body("conflict", ("x",))))
        self.assertEqual(run(*self.common("status"))[1]["verdict"], "held_by")
        self.assertEqual(run(*self.common("release"))[1]["verdict"], "released")
        self.assertEqual(self.live(), [30, 31])
        self.assertNotIn(OA_REMOVE, self.mutations())


class CliTest(Base):
    def test_cli_prints_one_json_line_and_forge_errors_exit_1(self):
        self.store(comment(30, marker_body()))
        done = subprocess.run([sys.executable, "-m", "agent_tools.forge_claim", *action("status")],
                              capture_output=True, text=True, env=dict(os.environ), timeout=120)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(len(done.stdout.splitlines()), 1)
        self.assertEqual(json.loads(done.stdout)["verdict"], "open")

    def test_forge_error_is_exit_1(self):
        code, out = run(*action("status"))  # no comment store: the listing is unregistered and fails
        self.assertEqual((code, out["verdict"], out["action"]), (1, "error", "status"))


class TransientRetryTest(Base):
    """Issue 740 D3: owner-action status retries whole on a transport error; post and end run once."""

    def test_status_after_two_network_failures_reads_the_prompt(self):
        self.store(comment(30, marker_body()))
        self.world.outage(2)
        code, out = run(*action("status"))
        self.assertEqual((code, out["verdict"]), (0, "open"))
        self.assertEqual(self.slept, [20, 40])
        self.assertEqual(self.mutations(), [])

    def test_status_in_a_lasting_outage_is_error_transient(self):
        self.store(comment(30, marker_body()))
        self.world.outage()
        code, out = run(*action("status"))
        self.assertEqual((code, out["verdict"], out["transient"]), (1, "error", True))
        self.assertEqual(self.slept, [20, 40])

    def test_post_and_end_run_once(self):
        for argv in (self.post_argv(), action("end", "conflict")):
            with self.subTest(action=argv[1]):
                self.slept.clear()
                self.store(comment(30, marker_body("conflict")))
                self.world.outage()
                code, out = run(*argv)
                self.assertEqual((code, out["verdict"], out["transient"]), (1, "error", True))
                self.assertEqual(self.slept, [])


HR_REMOVE = ["api", "-X", "DELETE", f"repos/{SLUG}/issues/{ISSUE}/labels/agent%3Ahuman-required"]
ANSWERED = {(0, 0), (1, 0)}


class ReconcileTest(Base):
    def setUp(self):
        super().setUp()
        self.world.respond("gh", HR_REMOVE)

    def labelled(self, *comments, labels=("owner-action",), fail_once=()):
        self.world.comment_store(SLUG, ISSUE, list(comments), next_id=40, labels=list(labels),
                                 fail_once=list(fail_once))

    def label_writes(self):
        return [a for a in self.mutations() if "labels" in a[3]]

    def test_a_ticked_approve_box_is_answered_in_one_pass(self):
        self.labelled(comment(30, box_body([QUESTIONS[1]], ticks={(0, 0)})))
        self.assertEqual([(l["issue"], l["state"], l["reason"]) for l in foa.reconcile(SLUG)],
                         [(ISSUE, "answered", "owner_answered")])
        self.assertEqual(self.world.issue()["labels"], ["owner-answered"])
        self.assertEqual(self.label_writes(), [OK_ENSURE, OK_ADD, OA_REMOVE])

    def test_a_ticked_option_box_is_answered_in_one_pass(self):
        self.labelled(comment(30, box_body(ticks={(0, 1), (1, 0)})))
        foa.reconcile(SLUG)
        self.assertEqual(self.world.issue()["labels"], ["owner-answered"])

    def test_an_unanswered_prompt_keeps_owner_action(self):
        for ticks in (set(), {(0, 0)}):
            with self.subTest(ticks=ticks):
                self.labelled(comment(30, box_body(ticks=ticks)))
                self.assertEqual(foa.reconcile(SLUG)[0]["state"], "open")
                self.assertEqual(self.world.issue()["labels"], ["owner-action"])

    def test_a_second_pass_writes_nothing(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)))
        foa.reconcile(SLUG)
        before = len(self.mutations())
        foa.reconcile(SLUG)
        self.assertEqual(len(self.mutations()), before)

    def test_an_interrupted_label_write_is_repaired_by_the_next_pass(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)), fail_once=["remove_label"])
        self.assertEqual(foa.reconcile(SLUG)[0]["reason"], "forge_error")
        self.assertEqual(sorted(self.world.issue()["labels"]), ["owner-action", "owner-answered"])
        foa.reconcile(SLUG)
        self.assertEqual(self.world.issue()["labels"], ["owner-answered"])

    def test_an_unticked_box_flips_back_to_owner_action(self):
        self.labelled(comment(30, box_body(ticks={(0, 0)})), labels=("owner-answered",))
        foa.reconcile(SLUG)
        self.assertEqual(self.world.issue()["labels"], ["owner-action"])

    def test_an_ended_prompt_drops_owner_answered(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)), comment(31, fm.end_body(30, "resolved")),
                      labels=("owner-answered",))
        self.assertEqual(foa.reconcile(SLUG)[0]["state"], "none")
        self.assertEqual(self.world.issue()["labels"], [])

    def test_an_answered_prompt_that_clears_human_required_removes_it(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED, clears="agent:human-required")),
                      labels=("owner-action", "agent:human-required"))
        foa.reconcile(SLUG)
        self.assertEqual(self.world.issue()["labels"], ["owner-answered"])

    def test_a_prompt_without_clears_keeps_human_required(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)), labels=("owner-action", "agent:human-required"))
        foa.reconcile(SLUG)
        self.assertEqual(sorted(self.world.issue()["labels"]), ["agent:human-required", "owner-answered"])
        self.assertNotIn(HR_REMOVE, self.mutations())

    def test_an_untrusted_prompt_counts_for_nothing(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED), "NONE"))
        self.assertEqual(foa.reconcile(SLUG)[0]["state"], "none")
        self.assertEqual(self.world.issue()["labels"], ["owner-action"])

    def test_an_answered_decision_beside_another_live_owner_action_keeps_both(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)), comment(31, marker_body("conflict", ("Fix it.",))))
        self.assertEqual(foa.reconcile(SLUG)[0]["state"], "open")
        self.assertEqual(sorted(self.world.issue()["labels"]), ["owner-action", "owner-answered"])

    def test_a_later_unanswered_round_keeps_owner_action(self):
        self.labelled(comment(30, box_body(ticks=ANSWERED)), comment(31, box_body(round_no=2)))
        self.assertEqual(foa.reconcile(SLUG)[0]["state"], "open")
        self.assertEqual(self.world.issue()["labels"], ["owner-action"])
