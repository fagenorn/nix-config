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

from agent_tools.console import approve, register, register_check

from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1052)
from . import console_test_support as support
from . import test_console_approve_service as approve_tests
from .test_console_approve_service import ApproveCase
from .test_console_register_service import ROOT, CancelChecks, git
from .test_console_stream import next_frame, next_view, open_stream

SLUG = "fixture/console-commit-failure"
GUEST_HOST = "desk.invented-tailnet.ts.net"
COLLEAGUE = "colleague@example.invalid"
ERROR_LINE = "console: plan_approve_error "
CHATTY = ("#!/bin/sh\ni=1\nwhile [ $i -le 12 ]; do echo \"hook line $i\"; i=$((i+1)); done\n"
          "echo \"checking $PWD/README.md\"\necho \"config missing [$0]\" >&2\nexit 1\n")


class CommitFailureCase(ApproveCase):
    become_ready = approve_tests.PlanApproveRealTest.become_ready

    def hooked(self, hook_text: str, *, signed: bool = False) -> None:
        contract = json.loads((ROOT / register_check.CONTRACT_SOURCE).read_text("utf-8"))
        contract["bindings"]["vcs"]["commit"]["signed"] = signed
        contract["bindings"]["commands"]["nix-build"]["argv"] = ["true"]
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


class CancelUntilShownTest(CancelChecks, CommitFailureCase):
    """Cancel keeps the failed commit's copy until its card was sent to a page stream (#1236)."""

    def setUp(self):
        super().setUp()
        self.hooked(CHATTY)
        self.failed()
        self.branch = approve.branch_of(self.shown["plan_id"])

    def start(self, fake, **kwargs):
        return super().start(fake, **{"guest_port": 0, **kwargs})

    def open_guest_stream(self, login):
        """A listed colleague's open guest stream; its response."""
        support.write_registry(self.registry, support.entries(1))
        self.svc.refresh()
        self.svc.set_tailnet(GUEST_HOST)
        self.svc.set_colleague(login, ("owner/p00",))
        connection = http.client.HTTPConnection(*self.svc.guest_address, timeout=5)
        self.addCleanup(connection.close)
        connection.putrequest("GET", "/api/stream", skip_host=True)
        connection.putheader("Host", GUEST_HOST)
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
