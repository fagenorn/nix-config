"""The picture run's held permission prompts: the constants and the signed posts that hold a manager's prompt open
while a shot is taken."""
from __future__ import annotations

import http.client
import json
import secrets
from collections.abc import Mapping
from typing import TYPE_CHECKING

from agent_tools.console import prompt_card
from agent_tools.console.sprints import read_secret

from .console_test_support import hook_body

if TYPE_CHECKING:
    from agent_tools.console.service import ConsoleService

    from .console_screenshots import Fixture

PERMISSION_MANAGER = "manager-1424"
PERMISSION_PROMPT = "/api/permission-prompt"
PERMISSION_COMMAND = "git worktree add ../.worktrees/issue-12"
PERMISSION_WORDS = "Create the delivery's worktree"
PERMISSION_LONG_WORDS = "Rewrite the upload tests for resumable parts"
PERMISSION_LONG_COMMAND = (
    "python3 - <<'PY'\n"
    "from pathlib import Path\n"
    "test = Path(\"tests/test_uploads.py\")\n"
    "text = test.read_text()\n"
    + "".join(f"text = text.replace(\"chunk_{i}\", \"part_{i}\")\n" for i in range(24))
    + "test.write_text(text)\n"
    "PY\n"
    "cat > /tmp/uploads-notes.md <<'EOF'\n"
    "The upload tests now name parts, not chunks.\n"
    "EOF\n"
    "git diff --stat > review/diff.txt")
HELD_PROMPTS = {"permission-card": (PERMISSION_COMMAND, PERMISSION_WORDS),
                "permission-long": (PERMISSION_LONG_COMMAND, PERMISSION_LONG_WORDS)}


def _permission_post(service: ConsoleService, fixture: Fixture, body: Mapping) -> tuple[int, dict]:
    """One POST of `body`, signed as the manager's hook signs it (a fresh nonce, the sprint's secret never sent).

    It goes to the permission route by its literal path; the result is its status and JSON."""
    sprint_id = fixture.prompting
    body = {**body, "sprint_id": sprint_id, "nonce": secrets.token_hex(16)}
    body["auth"] = prompt_card.request_auth(read_secret(fixture.secrets, sprint_id),
                                            prompt_card.signed_bytes(body))
    connection = http.client.HTTPConnection(*service.address, timeout=10)
    try:
        connection.request("POST", PERMISSION_PROMPT, body=json.dumps(body),
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        raw = response.read()
        return response.status, json.loads(raw) if response.status == 200 else {}
    finally:
        connection.close()


def hold_permission(service: ConsoleService, fixture: Fixture, state: str = "permission-card") -> int | None:
    """The manager's held Bash prompt of `state` (a `HELD_PROMPTS` key): its id, or None on a console without the route.

    A console that does not know the route (the base commit answers 405, another 404) gets the `PermissionRequest`
    hook row alone, which is what its manager's hook produces there.
    """
    command, words = HELD_PROMPTS[state]
    status, answer = _permission_post(service, fixture, {
        "phase": "ask", "session_id": PERMISSION_MANAGER, "command": command, "description": words})
    if status in (404, 405):
        service.ingest_hook(hook_body("permission prompt", session_id=PERMISSION_MANAGER,
                                      cwd=str(fixture.projects[0])))
        return None
    if status != 200 or not isinstance(answer.get("prompt"), int):
        raise RuntimeError(f"the permission prompt was not held ({status})")
    return answer["prompt"]


def keep_permission(service: ConsoleService, fixture: Fixture, prompt: int | None) -> None:
    """Renew the held prompt's contact right before a shot, as its hook's wait does."""
    if prompt is None:
        return
    status, answer = _permission_post(service, fixture, {
        "phase": "wait", "session_id": PERMISSION_MANAGER, "prompt": prompt})
    if status != 200 or answer.get("state") != "open":
        raise RuntimeError(f"the permission prompt is not held open ({status})")
