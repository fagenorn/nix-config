"""The approve service tests' shared waits and fixtures (#1615).

A console that notices a shutdown at once, a reconcile repository built once per process and copied
per test, and waits that wake on the console's own publish.
"""

from __future__ import annotations

import shutil
import socketserver
import tempfile
import time
import unittest
from pathlib import Path

from agent_tools.console import event_log

from .test_console_register_service import PID_B, git, reconcile_repository

_RECONCILE_TEMPLATES: dict[str, Path] = {}


def forget_reconcile_templates(root: Path) -> None:
    "Remove the template directory with the cache entries that name it, so a second run in this process rebuilds."
    shutil.rmtree(root, True)
    if _RECONCILE_TEMPLATES.get("root") == root:
        _RECONCILE_TEMPLATES.clear()


def reconciled(parent: Path, *, contract: bool = False) -> Path:
    """`reconcile_repository(parent, contract=contract)`, copied from one build per flag per process.

    The repository's only absolute path is its origin URL, so a copy re-points it at its own bare origin;
    the index is refreshed because the copy's files are new inodes and product code reads that index.
    """
    if "root" not in _RECONCILE_TEMPLATES:
        root = Path(tempfile.mkdtemp(prefix="approve-reconcile-"))
        unittest.addModuleCleanup(forget_reconcile_templates, root)
        _RECONCILE_TEMPLATES["root"] = root
    flag = "contract" if contract else "plain"
    template = _RECONCILE_TEMPLATES["root"] / flag
    if flag not in _RECONCILE_TEMPLATES:
        reconcile_repository(template, contract=contract)
        _RECONCILE_TEMPLATES[flag] = template
    parent.mkdir(parents=True, exist_ok=True)
    copy = parent / "reconcile"
    shutil.copytree(template / "reconcile", copy, symlinks=True)
    shutil.copytree(template / "origin.git", parent / "origin.git", symlinks=True)
    git(copy, "remote", "set-url", "origin", str(parent / "origin.git"))
    git(copy, "update-index", "-q", "--refresh")
    return copy.resolve()


SERVER_POLL_SECONDS = 0.01


def quick_serve_forever(server, poll_interval=SERVER_POLL_SECONDS):
    "The stdlib serve loop with a short selector poll, so a console's shutdown returns at once."
    return socketserver.BaseServer.serve_forever(server, poll_interval)


PENDING = object()


def awaited(svc, probe, bound: float, recheck: float):
    """`probe()`'s first answer that is not `PENDING`, waiting on the console's publish between probes.

    Any other answer, falsey ones included, ends the wait; `PENDING` comes back past `bound`.

    The version is read before each probe, so a publish between the two wakes the next wait at once.
    A closing console answers `wait_for_change` at once, so it is slept out instead of spun on.
    """
    end = time.monotonic() + bound
    while time.monotonic() < end:
        seen = svc.version
        found = probe()
        if found is not PENDING:
            return found
        wait = min(recheck, end - time.monotonic())
        if wait > 0:
            if svc.closing:
                time.sleep(wait)
            else:
                svc.wait_for_change(seen, wait)
    return PENDING


class PublishWaits:
    "The wait helpers of the approve case, each woken by the service's publish."

    def until(self, *steps, after=0, bound=120):
        def probe():
            with self.svc._ingest:
                found = self.steps()
                busy = self.svc._approving
                shown = self.view()["registration"]
            return shown if len(found) > after and found[-1] in steps and not busy else PENDING

        found = awaited(self.svc, probe, bound, 0.05)
        if found is PENDING:
            self.fail("the approval never reached the expected step")
        return found

    def wait_done(self, root, bound=120):
        def probe():
            found = self.view()["registration"]
            if found is not None and found["root"] == str(root) and found["status"] == "done":
                return found
            return PENDING

        found = awaited(self.svc, probe, bound, 0.1)
        if found is PENDING:
            self.fail("no registration result")
        return found

    def wait_for(self, predicate, bound=120):
        def probe():
            found = self.view()["registration"]
            return found if found is not None and predicate(found) else PENDING

        found = awaited(self.svc, probe, bound, 0.1)
        if found is PENDING:
            self.fail("the registration never reached the expected state")
        return found

    def settled_row(self, root, bound=120):
        """The stored payload of the root's last ended registration, once the run has finished.

        It observes completion through the log and the service's run mark, not through the view,
        which a card or a registered project reduces or drops (ADR-console-035).
        """
        def probe():
            with self.svc._ingest:
                found = [payload for _, payload in self.rows(event_log.REGISTRATION_ENDED)
                         if payload.get("root") == str(root)]
                running = self.svc._registering
            return found[-1] if running is None and found else PENDING

        found = awaited(self.svc, probe, bound, 0.05)
        if found is PENDING:
            self.fail("no registration result")
        return found

    def settled(self, count, bound=120):
        def probe():
            found = self.registrations()
            with self.svc._ingest:
                busy = PID_B in self.svc._enrolling
            return found if len(found) >= count and not busy else PENDING

        found = awaited(self.svc, probe, bound, 0.05)
        if found is PENDING:
            self.fail("the registration never settled")
        return found
