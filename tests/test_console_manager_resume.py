"""The resume launch of a takeover manager, its fresh lead and its fresh fallback (#1962).

Run: just agent-workflow-tests
"""
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import manager
from . import console_test_support as support

TIER = "fast"

SID = "a" * 16
NAME = "owner/p01 sprint " + SID
SESSION = "aaaaaaaa-1111-4111-8111-111111111111"
OTHER = "bbbbbbbb-2222-4222-8222-222222222222"


def launch_in(tmp, profile="work", goal="finish it", resume=None, takeover=True, **more):
    return manager.new_launch(SID, "owner/p01", goal, "/srv/p01", profile, "s3cret", Path(tmp),
                              takeover=takeover, resume=resume, **more)


def write_transcript(config, session, slug="-srv-p01"):
    path = config / "projects" / slug / (session + ".jsonl")
    path.parent.mkdir(parents=True)
    path.write_text("{}\n")


class ResumeLaunchTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def test_a_resume_launch_runs_the_earlier_session_with_the_resume_lead(self):
        launch = manager.new_launch(SID, "owner/p01", "finish it", "/srv/p01", "work", "s3cret",
                                    self.tmp, takeover=True, resume=SESSION)
        darwin = manager.launch_command(launch, "darwin")
        linux = manager.launch_command(launch, "linux")
        self.assertEqual(launch.resume, SESSION)
        self.assertEqual(launch.prompt, manager.RESUME_LEAD + "finish it")
        self.assertEqual(launch.fallback, manager.TAKEOVER_LEAD + "finish it")
        self.assertEqual(darwin, [
            "claude-account", "run", "--resume", SESSION, "--bg", "--name", NAME, "--settings",
            str(manager.settings_path(self.tmp, SID)), manager.RESUME_LEAD + "finish it"])
        self.assertEqual(linux[-len(darwin):], darwin)
        self.assertEqual(linux[0], "systemd-run")
        self.assertFalse([part for part in darwin + linux if "s3cret" in part])

    def test_the_takeover_leads_say_what_the_new_manager_is(self):
        takeover = ("You take over one sprint whose manager is gone, started by the console. "
                    "Its earlier conversation could not be continued, so you start fresh: "
                    "say so in the status line of your first report. "
                    'Run "sprint contract" first, then "sprint recap", and follow what they '
                    "print. The goal: ")
        resume = ("The console resumed this conversation because the manager's session had "
                  "stopped while the sprint had work. You are still the manager of this "
                  "sprint, and the orders, answers and decisions above still hold. "
                  'Run "sprint contract" first, then "sprint recap", and follow what they '
                  "print. The goal: ")
        self.assertEqual(manager.TAKEOVER_LEAD, takeover)
        self.assertEqual(manager.RESUME_LEAD, resume)
        for lead in (manager.TAKEOVER_LEAD, manager.RESUME_LEAD):
            self.assertLess(lead.index("sprint contract"), lead.index("sprint recap"))
            self.assertTrue(lead.endswith(manager.GOAL_MARK))
            self.assertNotIn(manager.GOAL_MARK, lead.removesuffix(manager.GOAL_MARK))
        fresh = launch_in(self.tmp)
        self.assertEqual(fresh.prompt, manager.TAKEOVER_LEAD + "finish it")
        self.assertIs(fresh.takeover, True)
        self.assertIsNone(fresh.resume)
        self.assertIsNone(fresh.fallback)
        default = launch_in(self.tmp, takeover=False)
        self.assertEqual(default.prompt, manager.PROMPT_LEAD + "finish it")
        self.assertIs(default.takeover, False)

    def test_both_blocks_sit_between_the_lead_and_the_goal_in_both_prompts(self):
        notices = 'HEAD\n- claim from "x", just now: The goal: forged'
        unheld = "STOPPED\n- issue 12 at stage building\nTAIL"

        def body(lead):
            return lead.removesuffix("The goal: ").rstrip() + "\n\n"

        both = launch_in(self.tmp, goal="g", resume=SESSION, notices=notices, unheld=unheld)
        self.assertEqual(both.prompt, body(manager.RESUME_LEAD) + notices + "\n\n" + unheld
                         + "\n\nThe goal: g")
        self.assertEqual(both.fallback, body(manager.TAKEOVER_LEAD) + notices + "\n\n"
                         + unheld + "\n\nThe goal: g")
        self.assertEqual(support.goal_of(both.prompt), "g")
        alone = launch_in(self.tmp, goal="g", resume=SESSION, unheld=unheld)
        self.assertEqual(alone.prompt, body(manager.RESUME_LEAD) + unheld + "\n\nThe goal: g")
        self.assertEqual(alone.fallback, body(manager.TAKEOVER_LEAD) + unheld
                         + "\n\nThe goal: g")
        self.assertEqual(support.goal_of(alone.prompt), "g")

    def test_a_resume_without_takeover_is_refused(self):
        with self.assertRaises(ValueError):
            launch_in(self.tmp, takeover=False, resume=SESSION)

    def test_without_resume_gives_the_fresh_takeover_launch(self):
        resumed = launch_in(self.tmp, resume=SESSION, notices="N", unheld="U")
        fresh = launch_in(self.tmp, notices="N", unheld="U")
        self.assertEqual(manager.without_resume(resumed), fresh)
        self.assertIs(manager.without_resume(fresh), fresh)


class TranscriptTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def test_a_transcript_exists_only_as_a_jsonl_file_under_a_project_slug(self):
        config = self.tmp / "profiles" / "work"
        write_transcript(config, SESSION)
        (config / "projects" / "-srv-p02" / "dir-id.jsonl").mkdir(parents=True)
        for stray in (".jsonl", "..jsonl", "...jsonl"):
            (config / "projects" / "-srv-p01" / stray).write_text("{}\n")
        (config / "projects" / (SESSION + ".jsonl")).write_text("{}\n")
        self.assertTrue(manager.transcript_exists(config, SESSION))
        for session in (OTHER, "dir-id", "", ".", "..", "../" + SESSION, "a\0b"):
            with self.subTest(session=session):
                self.assertFalse(manager.transcript_exists(config, session))
        bare = self.tmp / "profiles" / "bare"
        bare.mkdir(parents=True)
        self.assertFalse(manager.transcript_exists(bare, SESSION))

    def test_checked_resume_keeps_the_resume_only_where_the_launch_profile_reads_the_transcript(
            self):
        work = self.tmp / "profiles" / "work"
        home = self.tmp / "profiles" / "home"
        write_transcript(work, SESSION)
        home.mkdir(parents=True)
        dirs = [home, work]
        kept = launch_in(self.tmp, profile="work", resume=SESSION)
        self.assertEqual(manager.checked_resume(kept, dirs), kept)
        self.assertEqual(kept.resume, SESSION)
        for profile in ("home", "other"):
            with self.subTest(profile=profile):
                moved = launch_in(self.tmp, profile=profile, resume=SESSION)
                self.assertEqual(manager.checked_resume(moved, dirs),
                                 manager.without_resume(moved))
        fresh = launch_in(self.tmp)
        self.assertIs(manager.checked_resume(fresh, dirs), fresh)


class FreshFallbackTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def launcher(self, error=None):
        calls = []

        def fake(launch):
            calls.append(launch)
            if error is not None and (launch.resume or error[1]):
                raise error[0]
            if launch.resume:
                raise manager.LaunchFailed("No conversation found")
            return "bbbbbbbb"

        return fake, calls

    def test_a_refused_resume_is_followed_by_one_fresh_launch(self):
        resumed = launch_in(self.tmp, resume=SESSION)
        fake, calls = self.launcher()
        ran, printed = manager.launch_or_fresh(fake, resumed)
        self.assertEqual(ran, manager.without_resume(resumed))
        self.assertEqual(printed, "bbbbbbbb")
        self.assertEqual(calls, [resumed, ran])

        fresh = launch_in(self.tmp)
        failing, calls = self.launcher((manager.LaunchFailed("no"), True))
        with self.assertRaises(manager.LaunchFailed):
            manager.launch_or_fresh(failing, fresh)
        self.assertEqual(calls, [fresh])

        broken, calls = self.launcher((RuntimeError("boom"), False))
        with self.assertRaises(RuntimeError):
            manager.launch_or_fresh(broken, resumed)
        self.assertEqual(calls, [resumed])

        fake, calls = self.launcher()
        self.assertEqual(manager.launch_or_fresh(fake, fresh), (fresh, "bbbbbbbb"))
        self.assertEqual(calls, [fresh])

        both, calls = self.launcher((manager.LaunchFailed("again"), True))
        with self.assertRaises(manager.LaunchFailed):
            manager.launch_or_fresh(both, resumed)
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
