"""The console records a look approval itself (#1260).

Run: just agent-workflow-tests
"""
import contextlib
import io
import json
import threading
import unittest

from agent_tools.claims import forge_markers
from agent_tools.console import answer, manager, sessions, sprints
from agent_tools.delivery import look_marker
from agent_tools.system.forge_api import ForgeError

from . import console_test_support as support
from .forge_world import ForgeWorld
from .test_console_answer import view_of
from .test_console_messages import GOAL_TEXT, PARTS
from .test_console_questions import JSON, Q0, QuestionRoutes, withdraw
from .test_console_reports import CHECKED
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

SLUG = "owner/p01"
ISSUE = 7
PR = 12
HEAD = "a" * 40
MOVED = "b" * 40
PULL = ["api", f"repos/{SLUG}/pulls/{PR}"]
COMMENTS = ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{ISSUE}/comments?per_page=100"]
MARKED_BODY = ("## Acceptance criteria\n\n"
               "- [ ] [code] the heading reads well — measured: a test\n"
               "- [ ] [human] before merge: the settings page — measured: the owner, on the console\n")
LOOK_Q = {"question": "Does the settings page look right?", "blocks": "the merge of issue 7",
          "options": ["Approve this head", "Approve with one fix", "Ask for changes"],
          "recommended": "Approve this head",
          "look": {"issue": ISSUE, "pr": PR, "head": HEAD, "approve": "Approve this head"}}


def with_pictures(svc, sid, secret, question=None):
    """The look question with the before and after pictures a look card must carry, stored for the sprint."""
    before = svc.store_picture(sid, secret, support.PIXEL)
    after = svc.store_picture(sid, secret, support.WIDE)
    return {**(LOOK_Q if question is None else question), "pictures": [
        {"picture": before, "line": "The settings page before", "pair": "before"},
        {"picture": after, "line": "The settings page now", "pair": "after"}]}


def gh_argvs(world):
    try:
        return world.argvs("gh")
    except FileNotFoundError:
        return []


def posts(world):
    return [argv for argv in gh_argvs(world) if "-X" in argv and "POST" in argv]


class LookMovedWordsTest(unittest.TestCase):
    def test_the_moved_head_line_asks_nothing_of_the_owner(self):
        self.assertEqual(
            answer.LOOK_MOVED.format(found="bbbbbbb", head="aaaaaaa"),
            "Nothing was recorded: the pull request is now at bbbbbbb, not at aaaaaaa, the head "
            "these pictures show. The manager will send the new pictures.")


class LookAnswerTest(QuestionRoutes):
    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)

    def store_comments(self, **kw):
        self.world.comment_store(SLUG, ISSUE, [], labels=[], **kw)

    def open(self, **kw):
        support.write_registry(self.registry, support.entries(2))
        return self.start(slug_of=lambda root: SLUG, write_sleep=lambda seconds: False, **kw)

    def pull(self, state="open", sha=HEAD, merged=False):
        self.world.respond_json("gh", PULL, {"number": PR, "state": state, "merged": merged,
                                             "head": {"sha": sha}})

    def asked(self, svc):
        sid = self.approved(svc)
        status, _, body = self.inbox(svc, sid)
        self.assertEqual(status, 200)
        messages = json.loads(body)["messages"]
        self.assertEqual([m["kind"] for m in messages], ["approved"])
        status, _, body = self.ask(svc, sid, self.secret(sid), self.look_round(svc, sid))
        self.assertEqual(status, 200, body)
        return sid, json.loads(body)["round"]

    def look_round(self, svc, sid):
        return {"questions": [with_pictures(svc, sid, self.secret(sid))]}

    def approve(self, svc, sid, round_id):
        return self.reply(svc, self.answer_body(sid, round_id, 0, choice=0))

    def read(self, svc, sid):
        """Every unread message of the sprint, the stale-card notices (#1260) included."""
        status, _, body = self.inbox(svc, sid)
        self.assertEqual(status, 200)
        return json.loads(body)["messages"]

    def answers(self, svc, sid):
        return [m for m in self.read(svc, sid) if m["kind"] != "look-moved"]

    def retry(self, svc, sid, round_id):
        body = json.dumps({"project_id": "owner/p01", "sprint_id": sid, "round": round_id,
                           "question": 0}).encode()
        return support.post_page(svc.address, "/api/look-retry", self.own(svc, **JSON), body)

    def failed_post(self, svc):
        sid, round_id = self.asked(svc)
        self.store_comments(fail_once=("post",) * (len(answer.RETRY_DELAYS) + 1))
        self.pull()
        self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        self.store_comments()
        (row,) = self.rows("question.answered")
        return sid, round_id, row["seq"]

    def entry(self, svc, sid):
        return next(item for item in view_of(svc)["inbox"]["open"]
                    if item["reason"] == "question" and item["sprint_id"] == sid)

    def card_pictures(self):
        """The (pair, id) of the pictures on the look card, read from the questions.asked row the test appended."""
        (asked,) = self.rows("questions.asked")
        (question,) = asked["questions"]
        return [(picture.get("pair"), picture["picture"]) for picture in question["pictures"]]

    def marker_for(self, seq):
        return look_marker.approval_body(
            ISSUE, PR, HEAD, "approved", str(seq),
            pictures=look_marker.picture_digest(self.card_pictures()))

    def legacy_marker_for(self, seq):
        """The marker the console posted before it named the pictures."""
        return look_marker.approval_body(ISSUE, PR, HEAD, "approved", str(seq))

    def test_an_approve_answer_posts_the_marker_the_merge_guard_admits(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        (answered,) = self.rows("question.answered")
        seq = answered["seq"]
        self.assertEqual(answered["look"], {"issue": ISSUE, "pr": PR, "head": HEAD, "repo": SLUG})
        (comment,) = self.world.stored()
        self.assertEqual(comment["body"], self.marker_for(seq))
        facts = look_marker.IssueFacts(ISSUE, MARKED_BODY, tuple(self.world.stored()))
        self.assertIs(look_marker.judge(PR, HEAD, [facts]).admit, True)
        (recorded,) = self.rows("look.recorded")
        self.assertEqual((recorded["outcome"], recorded["message"], recorded["comment_id"]),
                         ("posted", seq, comment["id"]))
        (message,) = [m for m in self.answers(svc, sid) if m["kind"] == "answer"]
        self.assertEqual(message["id"], seq)
        self.assertTrue(all(call["token_visible"] is False for call in self.world.calls()))

    def test_an_approval_names_the_digest_of_the_cards_pictures(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        ids = self.card_pictures()
        self.assertEqual(len(ids), 2)
        (comment,) = self.world.stored()
        marker = forge_markers.parse(comment)
        self.assertEqual(marker.fields["pictures"], look_marker.picture_digest(ids))
        self.assertEqual(marker.fields["answer"], "approved")
        candidate = look_marker.carry_candidate(self.world.stored(), ISSUE, PR, "f" * 40)
        self.assertEqual(candidate.pictures, look_marker.picture_digest(ids))
        # The digest names each picture's role: the same two ids with their roles swapped are another card.
        self.assertEqual(sorted(pair for pair, _ in ids), ["after", "before"])
        swapped = [(ids[0][0], ids[1][1]), (ids[1][0], ids[0][1])]
        self.assertNotEqual(marker.fields["pictures"], look_marker.picture_digest(swapped))

    def test_an_approve_for_a_moved_head_records_nothing_and_the_card_says_why(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        table = (
            ({"sha": MOVED}, answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7]), "open"),
            ({"state": "closed"}, answer.LOOK_CLOSED.format(state="closed"), "closed"),
            ({"state": "closed", "merged": True}, answer.LOOK_CLOSED.format(state="merged"),
             "merged"))
        for number, (kw, line, found_state) in enumerate(table, 1):
            with self.subTest(kw=kw):
                self.pull(**kw)
                status, _, body = self.approve(svc, sid, round_id)
                self.assertEqual((status, body), (409, line.encode() + b"\n"))
                self.assertEqual(self.world.stored(), [])
                self.assertEqual(posts(self.world), [])
                self.assertEqual(self.rows("question.answered"), [])
                moved = self.rows("look.recorded")
                self.assertEqual(len(moved), number)
                self.assertEqual((moved[-1]["outcome"], moved[-1]["state"]), ("moved", found_state))
                entry = self.entry(svc, sid)
                self.assertIs(entry["answered"], False)
                self.assertEqual(entry["look"], {"issue": ISSUE, "pr": PR, "head": HEAD,
                                                 "state": "moved", "line": line, "approve_index": 0})
                self.assertEqual([m for m in self.answers(svc, sid)], [])

    def test_a_failed_post_stays_on_the_card_with_retry_and_retry_posts_once(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments(fail_once=("post",) * (len(answer.RETRY_DELAYS) + 1))
        self.pull()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        self.assertEqual(self.world.stored(), [])
        (answered,) = self.rows("question.answered")
        seq = answered["seq"]
        (failed,) = self.rows("look.recorded")
        self.assertEqual((failed["outcome"], failed["reason"]), ("failed", answer.FORGE_DOWN))
        entry = self.entry(svc, sid)
        self.assertIs(entry["answered"], True)
        self.assertEqual((entry["look"]["state"], entry["look"]["line"]),
                         ("failed", answer.FORGE_DOWN))
        self.assertEqual(self.answers(svc, sid), [])
        lines = [line for line in buf.getvalue().splitlines() if "look_post_failed" in line]
        self.assertEqual(len(lines), 1)
        self.assertIn("gh_failed", lines[0])
        self.assertIn("HTTP 502", lines[0])
        self.store_comments()
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        (comment,) = self.world.stored()
        self.assertEqual(comment["body"], self.marker_for(seq))
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed", "posted"])
        self.assertEqual([i for i in view_of(svc)["inbox"]["open"] if i["reason"] == "question"], [])
        self.assertEqual([m["id"] for m in self.answers(svc, sid)], [seq])
        status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, answer.LOOK_NOT_PENDING.encode() + b"\n"))
        self.assertEqual(len(self.world.stored()), 1)

    def test_a_retry_after_a_lost_reply_posts_no_second_marker(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        self.world.append_comment({"id": 900, "body": self.marker_for(seq),
                                   "author_association": "OWNER", "created_at": "2026-11-06T10:00:00Z",
                                   "updated_at": "2026-11-06T10:00:00Z"})
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual(len(posts(self.world)), before)
        (posted,) = [r for r in self.rows("look.recorded") if r["outcome"] == "posted"]
        self.assertEqual(posted["comment_id"], 900)
        self.assertEqual(len(self.world.stored()), 1)

    def test_a_retry_after_a_lost_reply_finds_a_marker_posted_before_the_upgrade(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        self.world.append_comment({"id": 900, "body": self.legacy_marker_for(seq),
                                   "author_association": "OWNER", "created_at": "2026-11-06T10:00:00Z",
                                   "updated_at": "2026-11-06T10:00:00Z"})
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual(len(posts(self.world)), before)
        (posted,) = [r for r in self.rows("look.recorded") if r["outcome"] == "posted"]
        self.assertEqual(posted["comment_id"], 900)
        self.assertEqual(len(self.world.stored()), 1)

    def test_record_look_without_pictures_posts_todays_marker(self):
        world = ForgeWorld(self)
        world.respond_json("gh", PULL, {"number": PR, "state": "open", "merged": False,
                                        "head": {"sha": HEAD}})
        world.comment_store(SLUG, ISSUE, [], labels=[])
        answer.record_look(SLUG, ISSUE, PR, HEAD, "41")
        (comment,) = world.stored()
        self.assertEqual(comment["body"], look_marker.approval_body(ISSUE, PR, HEAD, "approved", "41"))

    def test_a_retry_finds_the_answers_marker_whatever_its_digest(self):
        ids = ["c" * 64, "d" * 64]
        digest = look_marker.picture_digest(ids)
        stamp = {"author_association": "OWNER", "created_at": "2026-11-06T10:00:00Z",
                 "updated_at": "2026-11-06T10:00:00Z"}
        legacy = look_marker.approval_body(ISSUE, PR, HEAD, "approved", "41")
        table = (
            ("the same digest", [{"id": 900, "body": look_marker.approval_body(
                ISSUE, PR, HEAD, "approved", "41", pictures=digest), **stamp}], 900),
            ("no digest", [{"id": 900, "body": legacy, **stamp}], 900),
            ("no digest, ended", [{"id": 900, "body": legacy, **stamp},
                                  {"id": 901, "body": forge_markers.end_body(900, "withdrawn"),
                                   **stamp}], 900),
            ("another digest", [{"id": 900, "body": look_marker.approval_body(
                ISSUE, PR, HEAD, "approved", "41",
                pictures=look_marker.picture_digest(["b" * 64])), **stamp}], None))
        for name, comments, found in table:
            with self.subTest(name):
                world = ForgeWorld(self)
                world.comment_store(SLUG, ISSUE, comments, labels=[])
                if found is None:
                    with self.assertRaises(answer.Refused) as caught:
                        answer.record_look(SLUG, ISSUE, PR, HEAD, "41", ids)
                    self.assertEqual(str(caught.exception), answer.LOOK_PICTURES_DIFFER)
                else:
                    self.assertEqual(answer.record_look(SLUG, ISSUE, PR, HEAD, "41", ids), found)
                self.assertEqual(posts(world), [])
                self.assertEqual([a for a in gh_argvs(world) if any("pulls/" in x for x in a)], [])
                self.assertEqual(len(world.stored()), len(comments))

    def test_record_look_refuses_a_comment_not_counted_as_the_owner(self):
        world = ForgeWorld(self)
        world.respond_json("gh", PULL, {"number": PR, "state": "open", "merged": False,
                                        "head": {"sha": HEAD}})
        world.respond_json("gh", COMMENTS, [[]])
        world.respond_json(
            "gh", ["api", "-X", "POST", f"repos/{SLUG}/issues/{ISSUE}/comments", "-f",
                   "body=" + look_marker.approval_body(ISSUE, PR, HEAD, "approved", "41")], {"id": 9})
        with self.assertRaises(answer.Refused) as caught:
            answer.record_look(SLUG, ISSUE, PR, HEAD, "41")
        self.assertEqual(str(caught.exception), answer.LOOK_UNTRUSTED)

    def replace_round(self, svc, sid, round_id, head):
        """The manager's replacement of the reopened look card, for the head the pull request has now."""
        question = {**with_pictures(svc, sid, self.secret(sid)), "look": {**LOOK_Q["look"], "head": head},
                    "replaces": {"round": round_id, "index": 0}}
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [question]})
        self.assertEqual(status, 200, body)

    def reopened_by_a_retry(self, kw, line, found_state):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        self.pull(**kw)
        status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, line.encode() + b"\n"))
        self.assertEqual(len(posts(self.world)), before)
        self.assertEqual(self.world.stored(), [])
        moved = self.rows("look.recorded")
        self.assertEqual([r["outcome"] for r in moved], ["failed", "moved"])
        self.assertEqual((moved[-1]["message"], moved[-1]["state"]), (seq, found_state))
        entry = self.entry(svc, sid)
        self.assertIs(entry["answered"], False)
        self.assertEqual(entry["look"], {"issue": ISSUE, "pr": PR, "head": HEAD,
                                         "state": "moved", "line": line, "approve_index": 0})
        self.assertEqual(self.answers(svc, sid), [])
        status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, answer.LOOK_NOT_PENDING.encode() + b"\n"))
        self.replace_round(svc, sid, round_id, MOVED)
        return svc, sid

    def test_a_retry_after_the_head_moved_gives_the_question_back_to_the_manager(self):
        self.reopened_by_a_retry({"sha": MOVED}, answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7]),
                                 "open")

    def test_a_retry_after_the_pull_request_closed_gives_the_question_back_to_the_manager(self):
        self.reopened_by_a_retry({"state": "closed"}, answer.LOOK_CLOSED.format(state="closed"),
                                 "closed")

    def test_a_head_that_moves_after_the_answer_was_kept_gives_the_question_back(self):
        svc = self.open(look_reader=lambda slug, pr: ("open", HEAD))
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull(sha=MOVED)
        line = answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7])
        status, _, body = self.approve(svc, sid, round_id)
        self.assertEqual((status, body), (409, line.encode() + b"\n"))
        (answered,) = self.rows("question.answered")
        (moved,) = self.rows("look.recorded")
        self.assertEqual((moved["outcome"], moved["message"], moved["found"], moved["state"]),
                         ("moved", answered["seq"], MOVED, "open"))
        self.assertEqual(self.world.stored(), [])
        self.assertEqual(posts(self.world), [])
        entry = self.entry(svc, sid)
        self.assertIs(entry["answered"], False)
        self.assertEqual((entry["look"]["state"], entry["look"]["line"]), ("moved", line))
        self.assertEqual(self.answers(svc, sid), [])
        self.replace_round(svc, sid, round_id, MOVED)

    def test_a_retry_after_the_sprint_ended_posts_nothing(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        svc.send_closing(sid, self.secret(sid), {
            "summary": "Stopped early", "issues": [], "differently": "ask sooner"})
        self.pull()
        status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, sprints.ENDED.encode() + b"\n"))
        self.assertEqual(len(posts(self.world)), before)
        self.assertEqual(self.world.stored(), [])
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed"])

    def test_a_post_whose_head_moved_between_attempts_is_not_made(self):
        with self.assertRaises(answer.Refused) as caught:
            self.store_comments()
            self.pull(sha=MOVED)
            answer.record_look(SLUG, ISSUE, PR, HEAD, "41")
        self.assertEqual(str(caught.exception),
                         answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7]))
        self.assertEqual(posts(self.world), [])

    def test_a_retry_posts_to_the_repository_the_approval_was_read_for(self):
        repository = {"slug": SLUG}
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(slug_of=lambda root: repository["slug"],
                         write_sleep=lambda seconds: False)
        sid, round_id, seq = self.failed_post(svc)
        (answered,) = self.rows("question.answered")
        self.assertEqual(answered["look"]["repo"], SLUG)
        repository["slug"] = "elsewhere/other"
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        (comment,) = self.world.stored()
        self.assertEqual(comment["body"], self.marker_for(seq))
        self.assertTrue(all("elsewhere/other" not in " ".join(argv) for argv in gh_argvs(self.world)))

    def test_an_approval_goes_to_the_repository_the_card_was_issued_for(self):
        repository = {"slug": SLUG}
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(slug_of=lambda root: repository["slug"],
                         write_sleep=lambda seconds: False)
        sid, round_id = self.asked(svc)
        repository["slug"] = "elsewhere/other"
        self.store_comments()
        self.pull()
        self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        (answered,) = self.rows("question.answered")
        self.assertEqual(answered["look"]["repo"], SLUG)
        (comment,) = self.world.stored()
        self.assertEqual(comment["body"], self.marker_for(answered["seq"]))
        self.assertTrue(all("elsewhere/other" not in " ".join(argv) for argv in gh_argvs(self.world)))

    def test_a_card_issued_without_a_repository_records_nothing_even_when_one_is_known_later(self):
        repository = {"slug": None}
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(slug_of=lambda root: repository["slug"],
                         write_sleep=lambda seconds: False)
        sid, round_id = self.asked(svc)
        repository["slug"] = SLUG
        status, _, body = self.approve(svc, sid, round_id)
        self.assertEqual((status, body), (409, answer.LOOK_NO_REPOSITORY.encode() + b"\n"))
        self.assertEqual(gh_argvs(self.world), [])

    def test_a_retry_does_not_undo_a_withdrawn_approval(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        stamp = {"author_association": "OWNER", "created_at": "2026-11-06T10:00:00Z",
                 "updated_at": "2026-11-06T10:00:00Z"}
        self.world.append_comment({"id": 900, "body": self.marker_for(seq), **stamp})
        self.world.append_comment({"id": 901, "body": forge_markers.end_body(900, "withdrawn"),
                                   **stamp})
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual(len(posts(self.world)), before)
        self.assertEqual(len(self.world.stored()), 2)
        (posted,) = [r for r in self.rows("look.recorded") if r["outcome"] == "posted"]
        self.assertEqual(posted["comment_id"], 900)

    def test_a_retry_does_not_undo_a_withdrawn_approval_posted_before_the_upgrade(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        before = len(posts(self.world))
        stamp = {"author_association": "OWNER", "created_at": "2026-11-06T10:00:00Z",
                 "updated_at": "2026-11-06T10:00:00Z"}
        self.world.append_comment({"id": 900, "body": self.legacy_marker_for(seq), **stamp})
        self.world.append_comment({"id": 901, "body": forge_markers.end_body(900, "withdrawn"),
                                   **stamp})
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual(len(posts(self.world)), before)
        self.assertEqual(len(self.world.stored()), 2)
        (posted,) = [r for r in self.rows("look.recorded") if r["outcome"] == "posted"]
        self.assertEqual(posted["comment_id"], 900)

    def test_an_open_look_card_names_what_its_approving_option_records(self):
        svc = self.open()
        sid = self.approved(svc)
        question = {**with_pictures(svc, sid, self.secret(sid)), "recommended": "Approve this head",
                    "look": {**LOOK_Q["look"], "approve": "Ask for changes"}}
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [question]})
        self.assertEqual(status, 200, body)
        self.assertEqual(
            self.entry(svc, sid)["look"],
            {"issue": ISSUE, "pr": PR, "head": HEAD, "state": "open", "approve_index": 2,
             "line": 'Choosing "Ask for changes" records your approval of aaaaaaa, '
                     'proposed change #12, on issue #7.'})

    def test_an_open_look_card_is_consequential_without_the_mark(self):
        svc = self.open()
        sid = self.approved(svc)
        question = with_pictures(svc, sid, self.secret(sid))
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [question]})
        self.assertEqual(status, 200, body)
        self.assertIs(self.entry(svc, sid)["consequential"], True)

    def test_a_held_approval_is_not_shown_as_sent_or_not_picked_up(self):
        moment = {"now": 1_800_000_000.0}
        svc = self.open(clock=lambda: moment["now"])
        sid, round_id, seq = self.failed_post(svc)
        moment["now"] += 3600
        svc.refresh()
        sprint = next(s for e in view_of(svc)["entries"] for s in e["sprints"]
                      if s["sprint_id"] == sid)
        self.assertEqual([m["id"] for m in sprint["messages"] if m["kind"] == "answer"], [])
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        svc.refresh()
        sprint = next(s for e in view_of(svc)["entries"] for s in e["sprints"]
                      if s["sprint_id"] == sid)
        self.assertEqual([m["id"] for m in sprint["messages"] if m["kind"] == "answer"], [seq])

    def test_look_head_reads_the_pull_request(self):
        for state, merged, expected in (("open", False, "open"), ("closed", False, "closed"),
                                        ("closed", True, "merged")):
            with self.subTest(state=state, merged=merged):
                self.pull(state=state, merged=merged)
                self.assertEqual(answer.look_head(SLUG, PR), (expected, HEAD))
        for payload in ({"state": "open", "merged": False},
                        {"state": "open", "merged": False, "head": {"sha": "abc123"}}):
            with self.subTest(payload=payload):
                self.world.respond_json("gh", PULL, payload)
                with self.assertRaises(ForgeError) as caught:
                    answer.look_head(SLUG, PR)
                self.assertEqual(caught.exception.code, "payload_invalid")

    def test_a_failed_head_read_answers_nothing(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.world.respond("gh", PULL, exit=1, stderr="gh: Service Unavailable (HTTP 503)")
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            status, _, body = self.approve(svc, sid, round_id)
        self.assertEqual((status, body), (502, answer.FORGE_DOWN.encode() + b"\n"))
        self.assertEqual(self.rows("question.answered"), [])
        self.assertEqual(self.rows("look.recorded"), [])
        self.assertEqual(self.entry(svc, sid)["look"]["state"], "open")
        (line,) = [l for l in buf.getvalue().splitlines() if "look_head_failed" in l]
        self.assertIn("gh_failed", line)
        self.assertIn("HTTP 503", line)

    def test_the_approve_option_with_the_owners_words_is_an_ordinary_answer(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        words = "approve, but make the heading bold"
        self.assertEqual(
            self.reply(svc, self.answer_body(sid, round_id, 0, choice=0, text=words))[0], 204)
        self.assertEqual(gh_argvs(self.world), [])
        self.assertEqual(self.world.stored(), [])
        self.assertEqual(self.rows("look.recorded"), [])
        (answered,) = self.rows("question.answered")
        self.assertNotIn("look", answered)
        self.assertEqual((answered["chosen"], answered["words"]), ("Approve this head", words))
        (message,) = [m for m in self.answers(svc, sid) if m["kind"] == "answer"]
        self.assertEqual(message["id"], answered["seq"])
        self.assertEqual([i for i in view_of(svc)["inbox"]["open"] if i["reason"] == "question"], [])

    def test_a_head_that_moves_after_the_post_gives_the_question_back(self):
        reads = iter([("open", HEAD), ("open", MOVED)])
        svc = self.open(look_reader=lambda slug, pr: next(reads))
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        line = answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7])
        status, _, body = self.approve(svc, sid, round_id)
        self.assertEqual((status, body), (409, line.encode() + b"\n"))
        (answered,) = self.rows("question.answered")
        (moved,) = self.rows("look.recorded")
        self.assertEqual((moved["outcome"], moved["message"], moved["found"], moved["state"]),
                         ("moved", answered["seq"], MOVED, "open"))
        marker, ended = self.world.stored()
        self.assertEqual(marker["body"], self.marker_for(answered["seq"]))
        self.assertEqual(ended["body"], forge_markers.end_body(marker["id"], answer.LOOK_ENDED_REASON))
        facts = look_marker.IssueFacts(ISSUE, MARKED_BODY, tuple(self.world.stored()))
        self.assertIs(look_marker.judge(PR, HEAD, [facts]).admit, False)
        (notice,) = self.read(svc, sid)
        self.assertEqual((notice["kind"], notice["text"]), ("look-moved", sprints.LOOK_MOVED_OPEN.format(
            round=round_id, index=0, head=HEAD, pr=PR, found=MOVED)))
        self.assertEqual(notice["id"], self.rows("look.recorded")[-1]["seq"])
        self.assertIs(self.entry(svc, sid)["answered"], False)

    def test_a_stale_card_tells_the_manager_once_and_never_shows_on_the_owners_panel(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull(sha=MOVED)
        self.assertEqual(self.approve(svc, sid, round_id)[0], 409)
        self.assertEqual(self.approve(svc, sid, round_id)[0], 409)
        self.assertEqual(len(self.rows("look.recorded")), 2)
        svc.refresh()
        sprint = next(s for e in view_of(svc)["entries"] for s in e["sprints"]
                      if s["sprint_id"] == sid)
        self.assertEqual([m["kind"] for m in sprint["messages"] if m["kind"] != "approved"], [])
        (notice,) = self.read(svc, sid)
        self.assertEqual((notice["kind"], notice["text"]), ("look-moved", sprints.LOOK_MOVED_OPEN.format(
            round=round_id, index=0, head=HEAD, pr=PR, found=MOVED)))
        self.pull(state="closed")
        self.assertEqual(self.approve(svc, sid, round_id)[0], 409)
        (ended,) = self.read(svc, sid)
        self.assertEqual(ended["text"], sprints.LOOK_MOVED_ENDED.format(
            round=round_id, index=0, head=HEAD, pr=PR, state="closed"))

    def test_an_approval_that_could_not_be_ended_is_a_failed_post_and_retry_ends_it(self):
        reads = iter([("open", HEAD), ("open", MOVED), ("open", MOVED)])
        ends = []

        def ender(slug, issue, comment):
            ends.append(comment)
            if len(ends) == 1:
                raise ForgeError("gh_failed", "gh: Server Error (HTTP 502)", transient=False)
            answer.end_look(slug, issue, comment)

        svc = self.open(look_reader=lambda slug, pr: next(reads), look_ender=ender)
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed"])
        (marker,) = self.world.stored()
        self.assertEqual(self.answers(svc, sid), [])
        line = answer.LOOK_MOVED.format(found=MOVED[:7], head=HEAD[:7])
        with contextlib.redirect_stderr(io.StringIO()):
            status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, line.encode() + b"\n"))
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed", "moved"])
        self.assertEqual(len(self.world.stored()), 2)
        self.assertEqual(ends, [marker["id"], marker["id"]])
        facts = look_marker.IssueFacts(ISSUE, MARKED_BODY, tuple(self.world.stored()))
        self.assertIs(look_marker.judge(PR, HEAD, [facts]).admit, False)

    def test_a_sprint_closed_during_the_backoff_posts_nothing(self):
        calls, closing = [], []

        def recorder(slug, issue, pr, head, message, pictures):
            calls.append(message)
            raise ForgeError("gh_failed", "gh: Bad Gateway (HTTP 502)", transient=True)

        def sleep(seconds):
            sid, svc = closing
            svc.send_closing(sid, self.secret(sid), {
                "summary": "Stopped early", "issues": [], "differently": "ask sooner"})
            return False

        support.write_registry(self.registry, support.entries(2))
        svc = self.start(slug_of=lambda root: SLUG, write_sleep=sleep, look_recorder=recorder)
        sid, round_id = self.asked(svc)
        closing.extend([sid, svc])
        self.store_comments()
        self.pull()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.world.stored(), [])
        self.assertEqual(posts(self.world), [])
        (failed,) = self.rows("look.recorded")
        self.assertEqual((failed["outcome"], failed["reason"]), ("failed", sprints.ENDED))

    def test_a_failed_final_read_keeps_the_answer_held_with_retry(self):
        calls = []

        def reader(slug, pr):
            calls.append(pr)
            if len(calls) == 2:
                raise ForgeError("gh_failed", "gh: Server Error (HTTP 502)", transient=False)
            return "open", HEAD

        svc = self.open(look_reader=reader)
        sid, round_id = self.asked(svc)
        self.store_comments()
        self.pull()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        (failed,) = self.rows("look.recorded")
        self.assertEqual((failed["outcome"], failed["reason"]), ("failed", answer.FORGE_DOWN))
        self.assertEqual(self.answers(svc, sid), [])
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual(len(self.world.stored()), 1)
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed", "posted"])
        (row,) = self.rows("question.answered")
        self.assertEqual([m["id"] for m in self.answers(svc, sid)], [row["seq"]])

    def test_a_failed_approval_keeps_retry_after_the_manager_reported_done(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        svc.send_report(sid, self.secret(sid), {**CHECKED, "phase": "done"})
        self.store_comments(fail_once=("post",) * (len(answer.RETRY_DELAYS) + 1))
        self.pull()
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed"])
        svc.refresh()
        sprint = next(s for e in view_of(svc)["entries"] for s in e["sprints"]
                      if s["sprint_id"] == sid)
        self.assertEqual((sprint["state"], sprint["waiting"]), ("waiting", 1))
        self.assertEqual(sprint["now_text"], "waiting for you to press Retry on your approval")
        self.assertNotIn("tracker", sprint["now_text"])
        self.store_comments()
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed", "posted"])
        self.assertEqual(len(self.world.stored()), 1)
        svc.refresh()
        sprint = next(s for e in view_of(svc)["entries"] for s in e["sprints"]
                      if s["sprint_id"] == sid)
        self.assertEqual((sprint["state"], sprint["waiting"]), ("done", 0))

    def test_a_changes_answer_posts_nothing_and_reaches_the_manager(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments()
        for member in ({"choice": 1}, {"text": "make it bold"}):
            with self.subTest(member=member):
                self.assertEqual(
                    self.reply(svc, self.answer_body(sid, round_id, 0, **member))[0], 204)
                self.assertEqual(gh_argvs(self.world), [])
                (message,) = self.answers(svc, sid)
                self.assertEqual((message["kind"], message["round"]), ("answer", round_id))
                status, _, body = self.ask(svc, sid, self.secret(sid), self.look_round(svc, sid))
                self.assertEqual(status, 200, body)
                round_id = json.loads(body)["round"]

    def test_an_approval_left_posting_by_a_restart_reads_failed_with_retry(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        with svc._ingest:
            asked = svc._sprints[sid].questions[0]
            appended = svc.log.append([("question.answered", "owner/p01", {
                "sprint_id": sid, "goal": svc._sprints[sid].goal, "round": round_id, "index": 0,
                "question": asked.question, "answer": "Approve this head",
                "chosen": "Approve this head", "recommended": asked.recommended,
                "differs": False,
                "look": {"issue": ISSUE, "pr": PR, "head": HEAD, "repo": SLUG}})])
        seq = appended[-1].seq
        svc.close()
        again = self.start(slug_of=lambda root: SLUG, write_sleep=lambda seconds: False)
        (failed,) = self.rows("look.recorded")
        self.assertEqual((failed["outcome"], failed["message"], failed["reason"]),
                         ("failed", seq, answer.LOOK_INTERRUPTED))
        entry = self.entry(again, sid)
        self.assertEqual((entry["look"]["state"], entry["look"]["line"]),
                         ("failed", answer.LOOK_INTERRUPTED))

    def test_a_project_without_a_repository_records_nothing(self):
        support.write_registry(self.registry, support.entries(2))
        svc = self.start(slug_of=lambda root: None, write_sleep=lambda seconds: False)
        sid, round_id = self.asked(svc)
        self.store_comments()
        rows = support.log_rows(self.store)
        status, _, body = self.approve(svc, sid, round_id)
        self.assertEqual((status, body), (409, answer.LOOK_NO_REPOSITORY.encode() + b"\n"))
        self.assertEqual(gh_argvs(self.world), [])
        self.assertEqual(support.log_rows(self.store), rows)

    def test_a_question_withdrawn_while_the_head_is_read_records_nothing(self):
        state = {}

        def reader(slug, pr):
            self.assertEqual(withdraw(state["svc"], state["sid"], self.secret(state["sid"]),
                                      state["round"], 0)[0], 200)
            return "open", HEAD

        svc = state["svc"] = self.open(look_reader=reader)
        state["sid"], state["round"] = self.asked(svc)
        self.store_comments()
        status, _, body = self.approve(svc, state["sid"], state["round"])
        self.assertEqual((status, body), (409, sprints.TAKEN_BACK.encode() + b"\n"))
        self.assertEqual(self.world.stored(), [])
        self.assertEqual(self.rows("question.answered"), [])

    def test_a_second_retry_while_one_is_posting_is_refused(self):
        gate, entered, calls = threading.Event(), threading.Event(), []

        def recorder(slug, issue, pr, head, message, pictures):
            calls.append(message)
            if len(calls) == 1:
                raise answer.Refused(answer.LOOK_UNTRUSTED)
            entered.set()
            self.assertTrue(gate.wait(10))
            return 77

        svc = self.open(look_recorder=recorder)
        sid, round_id = self.asked(svc)
        self.pull()
        self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        (failed,) = self.rows("look.recorded")
        self.assertEqual(failed["reason"], answer.LOOK_UNTRUSTED)
        results = []
        first = threading.Thread(target=lambda: results.append(self.retry(svc, sid, round_id)))
        first.start()
        self.assertTrue(entered.wait(10))
        status, _, body = self.retry(svc, sid, round_id)
        self.assertEqual((status, body), (409, answer.LOOK_SENDING.encode() + b"\n"))
        gate.set()
        first.join(10)
        self.assertEqual(results[0][0], 204)

    def test_a_post_that_fails_once_is_retried_and_recorded(self):
        svc = self.open()
        sid, round_id = self.asked(svc)
        self.store_comments(fail_once=("post",))
        self.pull()
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf):
            self.assertEqual(self.approve(svc, sid, round_id)[0], 204)
        (answered,) = self.rows("question.answered")
        (comment,) = self.world.stored()
        self.assertEqual(comment["body"], self.marker_for(answered["seq"]))
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["posted"])
        self.assertEqual([m["id"] for m in self.answers(svc, sid)], [answered["seq"]])
        text = buf.getvalue()
        (line,) = [l for l in text.splitlines() if "look_post_retry" in l]
        self.assertIn("gh_failed", line)
        self.assertIn("HTTP 502", line)
        self.assertNotIn("look_post_failed", text)

    def test_an_inbox_read_while_an_approval_is_held_does_not_swallow_it(self):
        svc = self.open()
        sid, round_id, seq = self.failed_post(svc)
        status, _, body = self.ask(svc, sid, self.secret(sid), {"questions": [Q0], "blocker": True})
        self.assertEqual(status, 200, body)
        blocker = json.loads(body)["round"]
        self.assertEqual(self.reply(svc, self.answer_body(sid, blocker, 0, choice=0))[0], 204)
        (only,) = self.answers(svc, sid)
        self.assertEqual((only["kind"], only["round"]), ("answer", blocker))
        self.assertEqual(self.retry(svc, sid, round_id)[0], 204)
        (approval,) = self.answers(svc, sid)
        self.assertEqual(approval["id"], seq)
        self.assertEqual(self.answers(svc, sid), [])
        svc.close()
        again = self.open()
        self.assertEqual(self.answers(again, sid), [])


class LookNudgeTest(QuestionRoutes):
    """A look approval released while a nudge runs is still told of (#1260)."""

    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)
        support.write_registry(self.registry, support.entries(2))
        self.queued = support.Queued()
        self.nudges = []
        self.listed = {}

    def nudged(self):
        return [json.loads(row[4]) for row in support.log_rows(self.store)
                if row[2] == "sprint.nudged"]

    def idle_sprint(self, nudger):
        """A started sprint with an idle manager and a look card open; its service, id and round."""
        support.sign_in(self.store, "work")
        svc = self.start(
            launcher=support.Launches(), profile_dirs=[support.profile_dir(self.store, "work")],
            dispatch=self.queued, nudger=nudger, listing=lambda: dict(self.listed),
            slug_of=lambda root: SLUG, write_sleep=lambda seconds: False,
            clock=lambda: 1_800_000_000.0, session_poll_seconds=3600)
        sid = svc.state_goal("owner/p01", GOAL_TEXT)
        self.queued.run_next()
        name = manager.session_name("owner/p01", sid)
        self.listed["s-1"] = sessions.Observation("s-1", "/srv/p01", 1, "idle", None, name, None)
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        self.queued.run_next()
        round_id, _ = svc.ask_questions(sid, self.secret(sid), {"questions": [with_pictures(svc, sid, self.secret(sid))]})
        return svc, sid, round_id

    def test_an_idle_manager_is_nudged_when_the_owner_approves_a_stale_card(self):
        svc, sid, round_id = self.idle_sprint(self.nudges.append)
        self.world.comment_store(SLUG, ISSUE, [], labels=[])
        self.world.respond_json("gh", PULL, {"number": PR, "state": "open", "merged": False,
                                             "head": {"sha": MOVED}})
        settled = len(self.nudges)
        with self.assertRaises(sprints.Refused):
            svc.answer_question("owner/p01", sid, round_id, 0, 0, None)
        (moved,) = self.rows("look.recorded")
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual(len(self.nudges), settled + 1)
        self.assertIn(moved["seq"], self.nudged()[-1]["covers"])
        self.assertEqual(self.world.stored(), [])

    def test_an_approval_released_during_a_nudge_gets_its_own_nudge(self):
        support.sign_in(self.store, "work")
        state = {}

        def nudger(sent):
            self.nudges.append(sent)
            if state.get("armed"):
                state["armed"] = False
                self.world.comment_store(SLUG, ISSUE, [], labels=[])
                self.assertEqual(state["svc"].retry_look("owner/p01", state["sid"],
                                                         state["round"], 0), state["seq"])

        svc = state["svc"] = self.start(
            launcher=support.Launches(), profile_dirs=[support.profile_dir(self.store, "work")],
            dispatch=self.queued, nudger=nudger, listing=lambda: dict(self.listed),
            slug_of=lambda root: SLUG, write_sleep=lambda seconds: False,
            clock=lambda: 1_800_000_000.0, session_poll_seconds=3600)
        sid = state["sid"] = svc.state_goal("owner/p01", GOAL_TEXT)
        self.queued.run_next()
        name = manager.session_name("owner/p01", sid)
        self.listed["s-1"] = sessions.Observation("s-1", "/srv/p01", 1, "idle", None, name, None)
        svc.send_brief(sid, self.secret(sid), PARTS)
        svc.approve_brief("owner/p01", sid, 1)
        self.queued.run_next()
        state["round"], _ = svc.ask_questions(sid, self.secret(sid), {"questions": [with_pictures(svc, sid, self.secret(sid))]})
        self.world.comment_store(SLUG, ISSUE, [], labels=[],
                                 fail_once=("post",) * (len(answer.RETRY_DELAYS) + 1))
        self.world.respond_json("gh", PULL, {"number": PR, "state": "open", "merged": False,
                                             "head": {"sha": HEAD}})
        with contextlib.redirect_stderr(io.StringIO()):
            state["seq"] = svc.answer_question("owner/p01", sid, state["round"], 0, 0, None)
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed"])
        settled = len(self.nudges)
        state["armed"] = True
        text = svc.send_message("owner/p01", sid, "hello")
        self.assertEqual(len(self.queued.jobs), 1)
        self.queued.run_next()
        self.assertEqual([r["outcome"] for r in self.rows("look.recorded")], ["failed", "posted"])
        self.assertEqual(len(self.nudges), settled + 1)
        self.assertEqual(len(self.queued.jobs), 1, "the released approval is nudged for")
        self.queued.run_next()
        self.assertEqual(len(self.nudges), settled + 2)
        first, second = self.nudged()[-2:]
        self.assertEqual(first["through"], text)
        self.assertIn(text, first["covers"])
        self.assertNotIn(state["seq"], first["covers"])
        self.assertIn(state["seq"], second["covers"])
        self.assertTrue(second["ok"])
        self.assertEqual([m for m in sprints.unread(svc._sprints[sid])
                          if m.delivered_at is None], [])
