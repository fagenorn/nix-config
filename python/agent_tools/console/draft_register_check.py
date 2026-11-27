"""`draft_register_check`: the verify check that a drafted registration ends on schema 3 and resolves.

`python -m agent_tools.console.draft_register_check [--url URL] [--token-file PATH] [--wait SECONDS]`
exercises, on the host where it runs, the console's registration of a repository that has no project
contract. It builds a throwaway repository (`fixture`), asks the running console to register it as
the owner's page would, waits for the run to settle, reads the plan the console stored, then
restores what the run changed. It never applies the plan: applying commits through `devenv shell` and
contacts the forge. The URL, `--token-file` and `--wait` are `register_check`'s (loopback `http`,
default `http://127.0.0.1:27184`, `state_root()/console/page-token`, `SETTLE_SECONDS`).

Output is exactly one stdout line of JSON with sorted keys; the exits are 0 met, 1 not met, 75 not
yet, 2 usage. The preconditions are `register_check`'s, in its order: `not_running`, `not_deployed`,
`busy`, `no_token`, `registry_unreadable`; then `no_platform_revision` (the installed revision record
is unknown) and `no_platform_source` (the store has no source directory of that revision, so no
resolver could derive the platform range), all 75, none posting anything. A fixture that cannot be
built is `{"status": "no_fixture", "reason": <exception type>}`, 75, and a view that changed after the
fixture was built is `not_running` or `busy`.

The fixture is a fresh `console-register-draft-*` directory holding a repository on `main` with a
tracked `justfile` (`lint` and `test` recipes that run `true`), `.github/branch-protection.json`
naming the one check `CI`, a `devenv.lock` that already pins `agent-platform` at the installed
revision and a `devenv.yaml` declaring that input, so the plan's own writes are not needed for the
resolve. Its origin is authored `https://github.com/console-check/draft-<hex>.git` and rewritten by
`url.<local bare clone>.insteadOf`, so the console reads the default branch with no network and
nothing reaches GitHub. It has no `.agents/project.json`.

It POSTs `/api/register-project` `{"path": <root>, "unless_open": true}` with `register_check`'s
headers and refusal rules (a 409 that is a running or open registration is `busy`, any other 4xx or
a status that is not 204 is `not_met` `refused <status> <text>`), then polls the view for this
root's done row, at most `--wait` seconds. Met is `{"status": "met", "schema_version": 3}` exactly
when the row's `state` is `ready`; the stored plan has `plan.contract_draft.schema_version` 3; the
bytes of that draft with the conformance projection entry appended hash to the `after` of the
plan's `write-file` operation targeting `.agents/project.json`; and, in a copy of the fixture holding
those bytes, the resolver's `write-projections` and then `resolve` both exit 0. Otherwise `not_met`
with the reason `open questions: <subjects>` (a drafting row), `plan not schema 3` (no resolver
runs), `contract bytes differ from the plan`, `resolve refused: <first violation pointer or repair
id>`, `plan unreadable`, the row's `headline` (any other row) or `no result` (no row in time).

Restore follows `register_check`'s settle gate and rules: nothing is restored while the console's run
may still write, an unsettled run is `{"status": "unsettled", "root": <root>}`, 1 and restores
nothing; afterwards the plans whose `handoff.repo_root` is the root, the directory and any registry
entry are removed, and the restoring Cancel `{"root", "restore": true}` is posted once so the page
shows the registration it showed before the run. Any leftover, the prior row not shown again
included, is `{"status": "not_restored", "leftovers": [...], "verdict": <the verdict>}`, 1.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import register, register_check, service, write_guard
from agent_tools.console.register_check import NOT_YET, STATE_PATH
from agent_tools.project_contract import (
    adopt_conformance,
    adopt_inspection,
    adopt_planning,
    adopt_project,
    agent_platform,
    derived_values,
)

SCHEMA = 3
CONTRACT_FILE = ".agents/project.json"
LOCK = json.dumps({"nodes": {"root": {"inputs": {}}}, "root": "root", "version": 7},
                  indent=2, sort_keys=True) + "\n"
INPUTS = "inputs:\n  nixpkgs:\n    url: github:cachix/devenv-nixpkgs/rolling\n"
PROTECTION = json.dumps(
    {"required_status_checks": {"strict": True, "checks": [{"context": "CI"}]}}) + "\n"
JUSTFILE = "lint:\n\ttrue\ntest:\n\ttrue\n"


def fixture(parent: Path, project_id: str, revision: dict) -> Path:
    """The throwaway repository the console drafts a contract for, built under `parent`."""
    root = parent / "repo"
    root.mkdir(parents=True)
    root = root.resolve()
    git, write = register_check._git, register_check._write
    git(root, "init", "--quiet", "-b", "main")
    git(root, "config", "user.name", "t")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "commit.gpgsign", "false")
    entry = adopt_conformance.lock_with_platform(LOCK.encode("utf-8"), revision)
    declared = adopt_conformance.declare_input(
        INPUTS.encode("utf-8"), entry.locked["owner"], entry.locked["repo"])
    write(root, "justfile", JUSTFILE)
    write(root, ".github/branch-protection.json", PROTECTION)
    write(root, "devenv.lock", (entry.after or b"").decode("utf-8"))
    write(root, "devenv.yaml", (declared or INPUTS.encode("utf-8")).decode("utf-8"))
    register_check._commit(root, "fixture")
    bare = parent / "origin.git"
    git(parent, "clone", "--quiet", "--bare", str(root), str(bare))
    authored = f"https://github.com/{project_id}.git"
    git(root, "remote", "add", "origin", authored)
    git(root, "config", f"url.{bare}.insteadOf", authored)
    return root


def _refusal(code: int, payload: object) -> str:
    error = payload.get("error") if isinstance(payload, dict) else None
    violations = error.get("violations") if isinstance(error, dict) else None
    if isinstance(violations, list) and violations and isinstance(violations[0], dict):
        pointer = violations[0].get("pointer")
        if isinstance(pointer, str) and pointer:
            return pointer
    repair = error.get("repair_id") if isinstance(error, dict) else None
    return str(repair) if repair else f"exit {code}"


def _plan(found: dict) -> dict | None:
    try:
        document = json.loads(adopt_planning.store_plan_path(found["plan_id"]).read_text("utf-8"))
    except (OSError, ValueError, KeyError, IndexError, AttributeError, TypeError):
        return None
    return document if isinstance(document, dict) else None


def _verdict(found: dict, root: Path, tmp: Path, resolver) -> tuple[int, dict]:
    def not_met(reason: str) -> tuple[int, dict]:
        return 1, {"status": "not_met", "reason": reason}

    if found.get("state") == "drafting":
        subjects = ", ".join(str(q.get("subject")) for q in found.get("questions") or ()
                             if isinstance(q, dict))
        return not_met(f"open questions: {subjects}")
    if found.get("state") != "ready":
        return not_met(str(found.get("headline")))
    document = _plan(found)
    plan = document.get("plan") if document else None
    draft = plan.get("contract_draft") if isinstance(plan, dict) else None
    if document is None or not isinstance(plan, dict):
        return not_met("plan unreadable")
    if not isinstance(draft, dict) or draft.get("schema_version") != SCHEMA:
        return not_met("plan not schema 3")
    contract = adopt_inspection.authored_bytes(
        {**draft, "projections": [*draft.get("projections", []), adopt_conformance.PROJECTION_ENTRY]})
    planned = [op.get("after") for op in document.get("changes") or ()
               if isinstance(op, dict) and op.get("op") == "write-file"
               and CONTRACT_FILE in (op.get("targets") or ())]
    if planned != [adopt_inspection.sha256_hash(contract)]:
        return not_met("contract bytes differ from the plan")
    copy = tmp / "resolved"
    shutil.copytree(root, copy, symlinks=True)
    (copy / CONTRACT_FILE).parent.mkdir(parents=True, exist_ok=True)
    (copy / CONTRACT_FILE).write_bytes(contract)
    try:
        for verb in ("write-projections", "resolve"):
            code, payload = resolver(copy, verb)
            if code != 0:
                return not_met(f"resolve refused: {_refusal(code, payload)}")
    except adopt_inspection.AdoptError as error:
        pointer = error.violations[0].get("pointer") if error.violations else None
        return not_met(f"resolve refused: {pointer or error.repair_id}")
    return 0, {"status": "met", "schema_version": SCHEMA}


def _exercise(args, token: str, fetch, post, root: Path, tmp: Path, resolver, poll: float,
              reached: list[float]) -> tuple[int, dict]:
    base = f"http://{urlsplit(args.url).netloc}"
    status, body = post(
        base + register_check.REGISTER_PATH,
        {"Origin": base, write_guard.TOKEN_HEADER: token, "Content-Type": "application/json"},
        json.dumps({"path": str(root), "unless_open": True}).encode("utf-8"))
    text = register_check._text(body)
    if status is not None and 400 <= status <= 499:
        if status == 409 and (text.startswith("a registration is already running")
                              or text == register.OPEN_SHOWN):
            return NOT_YET, {"status": "busy"}
        return 1, {"status": "not_met", "reason": f"refused {status} {text}"}
    reached.append(time.monotonic())
    if status is not None and status != 204:
        return 1, {"status": "not_met", "reason": f"refused {status} {text}"}
    found: dict = {}

    def done(document: dict) -> bool:
        registration = document.get("registration")
        if (isinstance(registration, dict) and registration.get("root") == str(root)
                and registration.get("status") == "done"):
            found.update(registration)
            return True
        return False

    if not register_check._poll(fetch, base + STATE_PATH, poll, args.wait, done):
        return 1, {"status": "not_met", "reason": "no result"}
    return _verdict(found, root, tmp, resolver)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="draft_register_check",
                                     description=__doc__.splitlines()[0])
    result.add_argument("--url", type=register_check._loopback_url,
                        default=f"http://127.0.0.1:{service.DEFAULT_PORT}")
    result.add_argument("--token-file", type=Path, default=None)
    result.add_argument("--wait", type=register_check._seconds,
                        default=register_check.SETTLE_SECONDS)
    return result


def main(argv: list[str] | None = None, *, fetch=None, post=None, resolver=None, tmp_root=None,
         poll: float = 1.0, settle: float = register_check.SETTLE_SECONDS,
         shown: float = register_check.SHOWN_SECONDS) -> int:
    args = parser().parse_args(argv)
    code, result = _decide(
        args, fetch or register_check.default_fetch, post or register_check.default_post,
        resolver or adopt_project.run_resolver, tmp_root, poll, settle, shown)
    print(json.dumps(result, sort_keys=True))
    return code


def _precondition(args, fetch) -> tuple[tuple[int, dict] | None, object, str, list, dict]:
    """The 75 answer when a precondition fails, else None with what the run needs."""
    nothing: tuple = (None, None, "", [], {})
    answer = fetch(f"http://{urlsplit(args.url).netloc}{STATE_PATH}")
    if answer[0] != 200:
        return (NOT_YET, {"status": "not_running"}), *nothing[1:]
    document = register_check._json_object(answer)
    if document is None or "registration" not in document:
        return (NOT_YET, {"status": "not_deployed"}), *nothing[1:]
    before = document["registration"]
    if register.open_shown(before):
        return (NOT_YET, {"status": "busy"}), *nothing[1:]
    token_file = args.token_file or agent_platform.state_root() / "console" / "page-token"
    try:
        token = token_file.read_text("utf-8").strip()
    except (OSError, ValueError):
        return (NOT_YET, {"status": "no_token"}), *nothing[1:]
    registry = agent_platform.registry_path()
    entries = register.read_fleet(registry)
    if entries is None and os.path.lexists(registry):
        return (NOT_YET, {"status": "registry_unreadable"}), *nothing[1:]
    revision = agent_platform.platform_revision()
    if revision is None:
        return (NOT_YET, {"status": "no_platform_revision"}), *nothing[1:]
    try:
        source = Path(derived_values.store_path(revision["narHash"], derived_values.STORE_DIR))
    except derived_values.Underivable:
        source = None
    if source is None or not source.is_dir():
        return (NOT_YET, {"status": "no_platform_source"}), *nothing[1:]
    return None, before, token, entries or [], revision


def _decide(args, fetch, post, resolver, tmp_root, poll, settle, shown) -> tuple[int, dict]:
    refused, registration_before, token, registry_before, revision = _precondition(args, fetch)
    if refused is not None:
        return refused
    base = f"http://{urlsplit(args.url).netloc}"
    state = base + STATE_PATH
    tmp = Path(tempfile.mkdtemp(prefix="console-register-draft-", dir=tmp_root))
    pid = "console-check/draft-" + secrets.token_hex(4)
    root: Path | None = None
    reached: list[float] = []
    verdict: tuple[int, dict] = (1, {"status": "not_met"})
    settled = True
    leftovers: list[str] = []
    try:
        try:
            root = fixture(tmp, pid, revision)
        except Exception as error:  # noqa: BLE001 -- any builder failure is "no fixture"
            return NOT_YET, {"status": "no_fixture", "reason": type(error).__name__}
        again = register_check._json_object(fetch(state))
        if again is None or "registration" not in again:
            verdict = (NOT_YET, {"status": "not_running"})
        elif again["registration"] != registration_before:
            verdict = (NOT_YET, {"status": "busy"})
        else:
            verdict = _exercise(args, token, fetch, post, root, tmp, resolver, poll, reached)
    finally:
        if reached:
            settled = register_check._poll(
                fetch, state, poll, settle - (time.monotonic() - reached[-1]),
                lambda d: not register_check._is_running(d, str(root)))
        if settled:
            leftovers = register_check._restore(tmp, root, pid, registry_before,
                                                dispatched=bool(reached))
            if reached and root is not None:
                left, _ = register_check._restore_view(
                    fetch, post, base, token, root, pid, registration_before, poll, shown)
                leftovers += left
    if not settled:
        return 1, {"status": "unsettled", "root": str(root)}
    if leftovers:
        return 1, {"status": "not_restored", "leftovers": leftovers, "verdict": verdict[1]}
    return verdict


if __name__ == "__main__":
    sys.exit(main())
