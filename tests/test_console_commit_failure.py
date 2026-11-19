"""A failed adoption commit puts the failing hook and its last lines on the approval's failure card (#1236).

The approval runs the real adopter on a throwaway repository whose `core.hooksPath` holds a hook that
fails; every case has its own HOME and nothing reaches the real one.

Run: just agent-workflow-tests
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import subprocess
import time
from pathlib import Path

from agent_tools.console import approve, contract_draft, register, register_check

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from . import console_test_support as support
from . import test_console_approve_service as approve_tests
from .test_console_approve_service import ApproveCase
from .test_console_register_service import ROOT, CancelChecks, answer_of, git, sample_repository
from .test_console_stream import next_frame, next_view, open_stream

SLUG = "fixture/console-commit-failure"
GUEST_HOST = "desk.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
ERROR_LINE = "console: plan_approve_error "
NEEDS_CONFIG = ("#!/bin/sh\nif [ ! -f .generated-hook-config ]; then "
                "echo \"hook config missing\" >&2; exit 1; fi\n")
ENTER = ["sh", "-c", "printf 'generated\\n' > .generated-hook-config && exec \"$@\"", "dev-shell"]
INSIDE = ["sh", "-c", "printf 'entered\\n' > .entered && exec \"$@\"", "dev-shell"]
UNTRUE = "without the project's development environment"
CHATTY = ("#!/bin/sh\ni=1\nwhile [ $i -le 12 ]; do echo \"hook line $i\"; i=$((i+1)); done\n"
          "echo \"checking $PWD/README.md\"\necho \"config missing [$0]\" >&2\nexit 1\n")


class CommitFailureCase(ApproveCase):
    become_ready = approve_tests.PlanApproveRealTest.become_ready

    def hooked(self, hook_text: str, *, signed: bool = False,
               environment: list[str] | None = None) -> None:
        contract = json.loads((ROOT / register_check.CONTRACT_SOURCE).read_text("utf-8"))
        contract["bindings"]["vcs"]["commit"]["signed"] = signed
        contract["bindings"]["commands"]["nix-build"]["argv"] = ["true"]
        if environment is not None:
            contract["bindings"]["commands"]["dev-shell"] = {
                "argv": environment, "cwd": ".", "env": []}
            contract["bindings"]["vcs"]["commit"]["environment"] = "dev-shell"
        source = self.parent / "contract.json"
        source.write_text(json.dumps(contract), "utf-8")
        self.repo = register_check.adopted_repository(self.parent / "approve", SLUG, source)
        for name, text in ((".claude/odd.md", "# odd\n"), (".claude/specs/a.md", "# a\n")):
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "legacy")
        self.hooks = self.parent / "hooks"
        self.hooks.mkdir()
        self.write_hook(hook_text)
        git(self.repo, "config", "core.hooksPath", str(self.hooks))
        if signed:
            git(self.repo, "config", "gpg.format", "openpgp")
            git(self.repo, "config", "gpg.program", str(self.parent / "no-such-signing-program"))
            git(self.repo, "config", "user.signingkey", "DEADBEEF")
        self.start(register.Adopter(), pusher=approve.push, slug_of=lambda root: SLUG)
        self.shown = self.become_ready()

    def write_hook(self, hook_text: str) -> None:
        hook = self.hooks / "pre-commit"
        hook.write_text(hook_text)
        hook.chmod(0o755)

    def failed(self) -> dict:
        self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.assertEqual(self.steps()[-1], "apply_failed")
        (card,) = self.apply_cards()
        return card

    def kept_worktree(self) -> Path:
        return Path(approve.retained(self.shown["plan_id"])["worktree"])

    def last_evidence(self):
        return self.rows("adoption.step")[-1][1]["evidence"]


class CommitFailureCardTest(CommitFailureCase):
    def test_a_failing_pre_commit_hook_shows_its_name_and_last_lines(self):
        self.hooked(CHATTY)
        card = self.failed()
        self.assertEqual(
            card["headline"],
            "The adoption of repo was not applied: the project's pre-commit hook stopped the "
            "adoption commit: it ended with exit status 1.")
        self.assertEqual(card["why"], approve.HOOK_NOTE)
        self.assertEqual(card["lines"], [
            "hook line 7", "hook line 8", "hook line 9", "hook line 10", "hook line 11",
            "hook line 12", "checking README.md", "config missing [pre-commit]"])
        for text in [card["headline"], card["why"], *card["lines"]]:
            self.assertIsNone(approve.PAGE_PATTERN.search(text), text)
            for host in (str(self.hooks), str(self.parent), os.path.realpath(self.parent),
                         str(self.home), "[/"):
                self.assertNotIn(host, text)
        self.assertTrue(self.kept_worktree().is_dir())
        self.assertEqual(self.last_evidence()["hook"], "pre-commit")

    def test_a_hook_that_needs_a_missing_development_tool_names_the_hook_and_why(self):
        self.hooked("#!/bin/sh\necho \"entering the development environment\"\n"
                    "no-such-devenv-tool-1236 run pre-commit\n")
        card = self.failed()
        self.assertIn("pre-commit hook", card["headline"])
        self.assertTrue(card["headline"].endswith("a command it runs was not found."))
        self.assertEqual(card["lines"][0], "entering the development environment")
        self.assertTrue(any("no-such-devenv-tool-1236" in line for line in card["lines"]))
        for line in card["lines"]:
            self.assertIsNone(approve.PAGE_PATTERN.search(line), line)
        self.assertTrue(self.kept_worktree().is_dir())

    def test_the_original_output_is_logged_before_it_is_worded(self):
        self.hooked(CHATTY)
        _, errors = self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        (line,) = [one for one in errors.splitlines() if one.startswith(ERROR_LINE)]
        last = json.loads(line.removeprefix(ERROR_LINE))["error"]["commit_output"]["lines"][-1]
        self.assertTrue(last.startswith("config missing ["), last)
        self.assertIn(str(self.hooks), last)

    def test_apply_it_again_after_a_hook_failure_shows_the_new_failure(self):
        self.hooked(CHATTY)
        self.failed()
        self.write_hook("#!/bin/sh\necho \"second try\"\nexit 2\n")
        card = self.failed()
        self.assertEqual(card["lines"], ["second try"])
        self.assertTrue(card["headline"].endswith("exit status 2."))
        self.assertTrue(self.kept_worktree().is_dir())

    def test_a_silent_hook_in_a_signed_repository_is_named_beside_the_signing_failure(self):
        self.hooked("#!/bin/sh\nexit 1\n", signed=True)
        card = self.failed()
        self.assertTrue(card["headline"].endswith(approve.SIGNING_REASON + "."))
        why = approve.hook_signing_note("pre-commit", "it ended with exit status 1")
        self.assertEqual(card["why"], why)
        self.assertIn("pre-commit hook", why)
        self.assertEqual(self.last_evidence(),
                         {"hook": "pre-commit", "why": "it ended with exit status 1", "lines": []})
        for text in (card["headline"], card["why"], *card["lines"]):
            self.assertIsNone(approve.PAGE_PATTERN.search(text), text)
        self.assertTrue(self.kept_worktree().is_dir())


class CommitEnvironmentApprovalTest(CommitFailureCase):
    """The demo of issue 1249: a hook that needs a generated file adopts through the environment."""

    def test_a_project_whose_hook_needs_a_generated_file_adopts_through_its_environment(self):
        self.hooked(NEEDS_CONFIG, environment=ENTER)
        self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.assertEqual(self.steps(), ["applied", "opened"])
        self.assertIsNone(approve.retained(self.shown["plan_id"]))
        self.assertFalse((self.repo / ".generated-hook-config").exists())

    def test_the_same_project_without_the_binding_stops_at_its_hook(self):
        self.hooked(NEEDS_CONFIG)
        card = self.failed()
        self.assertIn("pre-commit hook", card["headline"])
        self.assertEqual(card["lines"], ["hook config missing"])
        self.assertEqual(card["why"], approve.HOOK_NOTE)
        self.assertTrue(self.kept_worktree().is_dir())

    def test_a_hook_failing_inside_the_environment_is_named_and_worded_truthfully(self):
        self.hooked("#!/bin/sh\necho \"inside the environment\"\nexit 3\n", environment=INSIDE)
        card = self.failed()
        self.assertEqual(
            card["headline"],
            "The adoption of repo was not applied: the project's pre-commit hook stopped the "
            "adoption commit: it ended with exit status 3.")
        self.assertEqual(card["why"], approve.HOOK_NOTE)
        self.assertNotIn(UNTRUE, card["why"])
        self.assertEqual(card["lines"], ["inside the environment"])
        self.assertTrue((self.kept_worktree() / ".entered").is_file())

    def test_a_hook_and_signer_failing_inside_the_environment_word_the_signing_note_truthfully(
            self):
        self.hooked("#!/bin/sh\nexit 1\n", signed=True, environment=INSIDE)
        card = self.failed()
        self.assertTrue(card["headline"].endswith(approve.SIGNING_REASON + "."))
        self.assertEqual(card["why"],
                         approve.hook_signing_note("pre-commit", "it ended with exit status 1"))
        self.assertNotIn(UNTRUE, card["why"])
        self.assertTrue((self.kept_worktree() / ".entered").is_file())


class DraftedEnvironmentTest(CommitFailureCase):
    """A devenv checkout with an installed hook registers through its proposed environment (#1268)."""

    def arrange(self, *, devenv: bool) -> None:
        self.repo = sample_repository(self.parent, remote=True)
        if devenv:
            (self.repo / "devenv.nix").write_text("{ ... }: { }\n")
            git(self.repo, "add", "-A")
            git(self.repo, "commit", "-q", "-m", "devenv")
        common = Path(git(self.repo, "rev-parse", "--path-format=absolute",
                          "--git-common-dir").strip())
        (common / "hooks").mkdir(exist_ok=True)
        hook = common / "hooks" / "pre-commit"
        hook.write_text(NEEDS_CONFIG + f"printf 'passed\\n' > '{self.parent / 'hook-passed'}'\n")
        hook.chmod(0o755)
        (self.parent / "bin").mkdir()
        stub = self.parent / "bin" / "devenv"
        stub.write_text(
            "#!/bin/sh\n"
            f"echo \"$*\" >> '{self.parent / 'devenv-calls'}'\n"
            "if [ \"$1\" != shell ] || [ \"$2\" != -- ]; then exit 64; fi\n"
            "shift 2\n"
            "printf 'generated\\n' > .generated-hook-config\n"
            "exec \"$@\"\n")
        stub.chmod(0o755)
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{self.parent / 'bin'}{os.pathsep}{saved}"
        self.addCleanup(os.environ.__setitem__, "PATH", saved)
        self.start(register.Adopter(), pusher=approve.push,
                   slug_of=lambda root: "sample-owner/sample-app")
        self.shown = self.become_ready()

    def stored(self, plan_id: str) -> dict:
        path = self.home / ".agents/state/adopt/plans" / (plan_id.partition(":")[2] + ".json")
        return json.loads(path.read_text("utf-8"))["plan"]["contract_draft"]

    def test_a_devenv_checkout_with_a_hook_plans_its_commit_environment_and_applies_through_it(self):
        self.arrange(devenv=True)
        (card,) = self.apply_cards()
        self.assertEqual(card["lines"][0],
                         "commits run in its development shell: devenv shell (found in its files)")
        plan = self.stored(self.shown["plan_id"])
        self.assertEqual(plan["bindings"]["vcs"]["commit"]["environment"], "commit-environment")
        self.assertEqual(plan["bindings"]["commands"]["commit-environment"]["argv"],
                         ["devenv", "shell", "--"])
        self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.assertEqual(self.steps(), ["applied", "opened"])
        self.assertIsNone(approve.retained(self.shown["plan_id"]))
        calls = (self.parent / "devenv-calls").read_text().splitlines()
        self.assertTrue(calls[0].startswith("shell -- env GIT_TRACE2_EVENT="), calls[0])
        self.assertEqual((self.parent / "hook-passed").read_text(), "passed\n")
        self.assertFalse((self.repo / ".generated-hook-config").exists())
        branch = self.view()["registration"]["adoption"]["branch"]
        shipped = json.loads(git(self.repo, "show", f"{branch}:.agents/project.json"))
        self.assertEqual(shipped["bindings"]["vcs"]["commit"]["environment"], "commit-environment")

    def test_the_owner_changes_the_proposed_command_before_applying(self):
        self.arrange(devenv=True)
        plan_id = self.shown["plan_id"]
        self.assertEqual(self.defer(plan_id)[0], 204)
        self.assertEqual(self.apply_cards(), [])
        (entry,) = [d for d in self.view()["registration"]["draft"]
                    if d["field"] == "commit-environment"]
        self.assertEqual(entry["line"],
                         "commits run in its development shell: devenv shell (found in its files)")
        self.assertIs(entry["more"], False)
        given = {"id": contract_draft.QUESTION_ID, "subject": "commit-environment", "value": "none"}
        self.assertEqual(self.answer(answer_of(plan_id, given))[0], 204)
        self.wait_for(lambda r: r["status"] == "done" and r["plan_id"] != plan_id
                      and r["state"] == "ready")
        (card,) = self.apply_cards()
        self.assertEqual(card["lines"][0], "commits run in its development shell: none (set by you)")
        plan = self.stored(self.view()["registration"]["plan_id"])
        self.assertNotIn("environment", plan["bindings"]["vcs"]["commit"])
        self.assertNotIn("commit-environment", plan["bindings"]["commands"])

    def test_the_same_checkout_without_devenv_plans_as_today_and_stops_at_its_hook(self):
        self.arrange(devenv=False)
        (card,) = self.apply_cards()
        self.assertFalse([x for x in card["lines"] if x.startswith("commits run in its development shell")])
        plan = self.stored(self.shown["plan_id"])
        self.assertNotIn("environment", plan["bindings"]["vcs"]["commit"])
        self.assertNotIn("commit-environment", plan["bindings"]["commands"])
        card = self.failed()
        self.assertIn("pre-commit hook", card["headline"])
        self.assertEqual(card["lines"], ["hook config missing"])
        self.assertFalse((self.parent / "devenv-calls").exists())
        self.assertFalse((self.parent / "hook-passed").exists())


class CancelUntilShownTest(CancelChecks, CommitFailureCase):
    """Cancel keeps the failed commit's copy until its card was sent to a page stream (#1236)."""

    def setUp(self):
        super().setUp()
        self.hooked(CHATTY)
        self.failed()
        self.branch = approve.branch_of(self.shown["plan_id"])

    def start(self, fake, **kwargs):
        kwargs.setdefault("guest_socket", support.guest_socket_path(self))
        kwargs.setdefault("status_reader", lambda: {"Self": {"DNSName": GUEST_HOST + "."}})
        return super().start(fake, **kwargs)

    def open_guest_stream(self, login):
        """A listed colleague's open guest stream; its response."""
        support.write_registry(self.registry, support.entries(1))
        self.svc.refresh()
        self.svc.set_sharing(True)
        self.svc.poll_serve()
        self.svc.set_colleague(login, ("owner/p00",))
        connection = support.UnixHTTPConnection(self.svc.guest_socket)
        self.addCleanup(connection.close)
        connection.putrequest("GET", "/api/stream", skip_host=True)
        connection.putheader("Host", "localhost")
        connection.putheader("X-Forwarded-Host", GUEST_HOST)
        connection.putheader("Tailscale-User-Login", login)
        connection.endheaders()
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        return response

    def branch_exists(self) -> bool:
        try:
            git(self.repo, "rev-parse", "--verify", "--quiet", f"refs/heads/{self.branch}")
        except subprocess.CalledProcessError:
            return False
        return True

    def shown_on_a_stream(self) -> None:
        response = open_stream(self, self.svc)
        for _ in range(20):
            items = next_view(response)["inbox"]["open"]
            if any(one["reason"] == "register_apply" and one["lines"] for one in items):
                return
        self.fail("the failure card never reached the stream")

    def cancel_once_sent(self):
        """The cancel's answer, retried while the stream's write is still being marked."""
        end = time.monotonic() + 3
        while True:
            with contextlib.redirect_stderr(io.StringIO()):
                status, _, body = self.cancel({"root": str(self.repo)})
            if status != 409 or time.monotonic() > end:
                return status, body
            time.sleep(0.05)

    def test_a_cancel_before_the_card_was_shown_keeps_the_worktree(self):
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_UNSEEN)
        self.assertTrue(self.kept_worktree().is_dir())
        self.assertTrue(self.branch_exists())
        self.assertEqual(self.rows("registration.cancelled"), [])
        self.assertEqual(len(self.apply_cards()), 1)

    def test_a_cancel_after_the_card_was_shown_removes_the_worktree(self):
        worktree = self.kept_worktree()
        self.shown_on_a_stream()
        self.assertEqual(self.cancel_once_sent(), (204, b""))
        self.assertFalse(worktree.exists())
        self.assertFalse(self.branch_exists())
        self.assertEqual(len(self.rows("registration.cancelled")), 1)

    def test_reading_the_state_route_does_not_count_as_shown(self):
        support.get_page(self.svc.address, "/api/state", self.own())
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_UNSEEN)
        self.assertTrue(self.kept_worktree().is_dir())

    def test_a_frame_written_to_a_colleague_does_not_count_as_shown(self):
        response = self.open_guest_stream(COLLEAGUE)
        self.assertTrue(next_frame(response).startswith(b"event: view\ndata: "))
        time.sleep(0.3)
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_UNSEEN)
        self.assertTrue(self.kept_worktree().is_dir())

    def test_not_now_lets_the_cancel_remove_the_worktree(self):
        worktree = self.kept_worktree()
        self.assertEqual(self.defer(self.shown["plan_id"])[0], 204)
        self.assertEqual(self.cancel({"root": str(self.repo)})[::2], (204, b""))
        self.assertFalse(worktree.exists())

    def test_a_new_failure_needs_its_own_showing(self):
        self.svc.delivered(self.svc.version)
        self.write_hook("#!/bin/sh\necho \"second try\"\nexit 2\n")
        self.run_approval("opened", "apply_failed", plan_id=self.shown["plan_id"])
        self.refused_cancel({"root": str(self.repo)}, register.CANCEL_UNSEEN)
        self.assertTrue(self.kept_worktree().is_dir())
