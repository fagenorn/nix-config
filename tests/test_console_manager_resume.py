"""The resume launch of a takeover manager, its fresh lead and its fresh fallback (#1962).

Run: just agent-workflow-tests
"""
import dataclasses
import subprocess
import tempfile
import unittest
from pathlib import Path

from agent_tools.console import manager, sprints
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

    def test_transcript_ids_are_the_sessions_of_the_launched_short_id(self):
        work, home = self.tmp / "work", self.tmp / "home"
        write_transcript(work, SESSION)
        write_transcript(home, SESSION, slug="-srv-p02")
        write_transcript(work, OTHER, slug="-srv-p02")
        (work / "projects" / "-srv-p01" / "aaaaaaaa-dir.jsonl").mkdir()
        dirs = [work, home, self.tmp / "missing"]
        self.assertEqual(manager.transcript_ids(dirs, "aaaaaaaa"), {SESSION})
        self.assertEqual(manager.transcript_ids(dirs, "bbbbbbbb"), {OTHER})
        for short in (None, "", "AAAAAAAA", "aaaaaaa", "*", "aaaaaaaa*"):
            with self.subTest(short=short):
                self.assertEqual(manager.transcript_ids(dirs, short), set())

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
                raise manager.ResumeRefused("No conversation found with session ID: x")
            return "bbbbbbbb"

        return fake, calls

    def test_only_a_refused_resume_is_followed_by_a_fresh_launch(self):
        resumed = launch_in(self.tmp, resume=SESSION)
        for reason in ("the launch did not return within 60 s", "the launch exited 1",
                       "No conversation found"):
            with self.subTest(reason=reason):
                timed_out, calls = self.launcher((manager.LaunchFailed(reason), False))
                with self.assertRaises(manager.LaunchFailed) as raised:
                    manager.launch_or_fresh(timed_out, resumed)
                self.assertNotIsInstance(raised.exception, manager.ResumeRefused)
                self.assertEqual(calls, [resumed])

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

        both, calls = self.launcher((manager.ResumeRefused("again"), True))
        with self.assertRaises(manager.LaunchFailed):
            manager.launch_or_fresh(both, resumed)
        self.assertEqual(len(calls), 2)


class RunResumeTest(unittest.TestCase):
    ENVIRON = {"PATH": "/p", "HOME": "/h"}

    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)
        self.root = self.tmp / "project"
        self.root.mkdir()

    def launch(self, resume):
        return manager.new_launch(SID, "owner/p01", "g", str(self.root), "work", "s3cret",
                                  self.tmp / "settings", takeover=resume is not None,
                                  resume=resume)

    def run_with(self, launch, returncode=1, stderr=b"", raises=None):
        def run(argv, **kwargs):
            if raises is not None:
                raise raises
            kwargs["stderr"].write(stderr)
            return subprocess.CompletedProcess(argv, returncode)

        return manager.run_launch(launch, platform="linux", run=run, environ=self.ENVIRON)

    def test_only_the_clients_refusal_of_the_conversation_is_a_refused_resume(self):
        refusal = b"warming up\nNo conversation found with session ID: " + SESSION.encode() + b"\n"
        with self.assertRaises(manager.ResumeRefused):
            self.run_with(self.launch(SESSION), stderr=refusal)
        with self.assertRaises(manager.LaunchFailed) as fresh:
            self.run_with(self.launch(None), stderr=refusal)
        self.assertNotIsInstance(fresh.exception, manager.ResumeRefused)
        later = b"No conversation found\nthe supervisor refused the session\n"
        for label, kwargs in (("later line", dict(stderr=later)), ("silent", {}),
                              ("timeout", dict(raises=subprocess.TimeoutExpired("c", 60)))):
            with self.subTest(label):
                with self.assertRaises(manager.LaunchFailed) as raised:
                    self.run_with(self.launch(SESSION), **kwargs)
                self.assertNotIsInstance(raised.exception, manager.ResumeRefused)


class RecordedResumeTest(unittest.TestCase):
    def setUp(self):
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        self.tmp = Path(holder.name)

    def test_a_resume_of_a_session_the_account_still_records_carries_no_name_or_settings(self):
        resumed = launch_in(self.tmp, resume=SESSION)
        recorded = dataclasses.replace(resumed, recorded=True)
        self.assertIs(resumed.recorded, False)
        self.assertEqual(manager.launch_command(recorded, "darwin"), [
            "claude-account", "run", "--resume", SESSION, "--bg", manager.RESUME_LEAD + "finish it"])
        self.assertEqual(manager.launch_command(recorded, "linux")[-6:],
                         manager.launch_command(recorded, "darwin"))
        self.assertIn("--name", manager.launch_command(resumed, "darwin"))
        self.assertEqual(manager.without_resume(recorded), launch_in(self.tmp))

    def test_the_earlier_session_is_the_one_the_launch_id_names_never_a_later_namesake(self):
        launched = "bbbbbbbb-2222-4222-8222-222222222222"
        namesake = "cccccccc-3333-4333-8333-333333333333"

        def sprint(short_id):
            return sprints.SprintState(SID, "owner/p01", "g", 1, "2026-11-17T08:00:01+00:00",
                                       manager_session=namesake, manager_short_id=short_id)

        named = sprint("bbbbbbbb")
        self.assertEqual(manager.earlier_session(named, (namesake, launched)), launched)
        self.assertIsNone(manager.earlier_session(named, (namesake,)))
        self.assertIsNone(manager.earlier_session(named, ()))
        unnamed = sprint(None)
        self.assertEqual(manager.earlier_session(unnamed, (launched,)), namesake)
        self.assertEqual(manager.earlier_session(unnamed, ()), namesake)
        self.assertIsNone(manager.earlier_session(
            dataclasses.replace(unnamed, manager_session=None), (launched,)))


if __name__ == "__main__":
    unittest.main()
