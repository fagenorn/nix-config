"""`register_check`: the verify check that the page registers a repository and the host is restored (#1052).

`python -m agent_tools.console.register_check [--url URL] [--token-file PATH] [--contract PATH] [--wait SECONDS]`
exercises the console's register-project write (ADR-console-028) on the host where it runs. It builds
a throwaway adopted repository (`adopted_repository`), asks the running console to register it as the
owner's page would, waits for the run to settle, then restores what the run changed. The URL is `http`
on `127.0.0.1` or `localhost` (default `http://127.0.0.1:27184`), else exit 2; `--token-file`
defaults to `state_root()/console/page-token`; `--contract` is the pinned schema-2 contract
(`CONTRACT_SOURCE`, relative to the checkout root the wrapper runs from); `--wait` is the seconds to
wait for the registration result (default `SETTLE_SECONDS`, 670).

Output is exactly one stdout line of JSON with sorted keys; the exits are 0 met, 1 not met, 75 not
yet, 2 usage. In this order:

1. the view (`/api/state`) does not answer 200: `{"status": "not_running"}`, 75;
2. the view JSON has no `registration` key (the console predates the write): `{"status":
   "not_deployed"}`, 75;
3. the view's registration is open (`register.open_shown`: not null and not a dismissed one, status
   done with the note `register.LATER_NOTE`, the owner's Not now): `{"status": "busy"}`, 75, building
   and posting nothing (#1334, ADR-console-084 D3);
4. the token file is unreadable: `{"status": "no_token"}`, 75;
5. the registry is present but unreadable: `{"status": "registry_unreadable"}`, 75.

Then it snapshots the registry (`before`), builds the fixture in a fresh `console-register-check-*`
directory with a throwaway project id `console-check/register-<hex>`. After building the fixture and
right before posting it reads the view again: no answer or no `registration` member is
`not_running`, a registration not equal to the first read's (a card that opened, or one the owner
cancelled) is `busy`; either removes the fixture and reads the console no more (no trust card can be
the run's). Otherwise it POSTs `{"path": <root>, "unless_open": true}` to `/api/register-project` with
the console's own `Origin`, the token header and a socket timeout of `POST_TIMEOUT` (60 s). A fixture
that cannot be built is `{"status": "no_fixture", "reason": <exception type>}`, 75.

- A status from 400 to 499 is a definite refusal: nothing was dispatched. A 409 whose text starts with
  `a registration is already running`, or whose text is `register.OPEN_SHOWN`, is `{"status": "busy"}`,
  75 (another run owns the console, or the console found a registration open on the page: it decides
  under its lock, ADR-console-084 D2); a console older than that refuses with 400, which is `not_met`;
  any other is `{"status": "not_met", "reason": "refused <status> <text>"}`, 1.
- A 5xx, or any other status but 204, is `not_met` with the same reason, though it may have
  dispatched a run.
- A 204, or no answer at all, may have dispatched a run. The check polls the view every second until
  `registration.root` is the posted root and its `status` is `done`, at most `--wait` seconds (else
  `not_met`, reason `no result`), or the project id is among the view's project entries. The adopted
  fixture first ends in the waiting row (ADR-console-034), which the view reduces to
  a Register card in `inbox.open` (reason `register_confirm`, this root): the check answers the card
  it found open in the document it saw done, as the owner's page does, with `POST /api/register-confirm
  {"root": <root>, "choice": "register"}` (same headers, same refusal rules as the first POST), and
  polls again, for a done row of this root whose `at` differs from the waiting row's, or the project
  id listed. A listed project is `met` (the view drops a registered root's result, ADR-console-035); a
  `result` other than `registered` is `not_met` with the `headline` as the reason; otherwise it polls
  at most 30 s for the project id among the view's project entries, quiet groups included (else
  `not_met`, reason `not listed`).

Two sprint rules govern what it leaves behind. S1: the check leaves no trace of itself, so it removes
the throwaway directory, its registry entry, its folder-trust entries and every stored plan whose
`handoff.repo_root` is its root. S2: it never writes the registry except to remove its own entry, never writes a `.claude.json`
except to remove its own root's project entry (the approval grants the folder's client trust, ADR-console-034),
and writes nothing else.

The settle gate. No restore happens while the console's run may still write. Every outcome after the
POST, except a definite refusal and a fixture failure, polls the view until it answers 200 and its
`registration` is not this root `running`, for at most `settle` seconds counted from when the POST
returned. This is sound because the console appends the ended row and clears `running` only after
both children (the plan and the verify) have returned, and `manager.run_in_own_group` reaps the
whole group before returning; and a POST that has returned, even by timeout, has outlasted the
console's bounded pre-dispatch work, so the console has either started the run or never will. A gate
that is not passed in time restores nothing and answers `{"status": "unsettled", "project_id": <id>,
"root": <root>}`, 1, which takes precedence over the verdict: it names the leftover so the owner can
remove it, because a cleanup before then could be undone by a late registry or plan write. A console
that dies with no `close` while a child runs leaves that child unbounded; the view then does not
answer 200 and the gate reports `unsettled`.

Restore runs after the gate: a Check again card the run left for the root (`inbox.open`, reason
`trust_failed`) is answered through `POST /api/trust-check`, because the card lives in the console's log
and only a granted retry clears it, and a card still open afterwards is a leftover named `trust card
<profile>` (`trust cards unread` when the view does not answer); then the registry entry is removed under `registry_transaction()`, the root's
trust entry is removed from `~/.claude.json` and every profile's `.claude.json` (`folder_trust.remove_entry`,
the key being the root's real path), plans are deleted, the directory is removed, and the registry must
equal `before` (by project id) with the directory gone and no matching plan left, else `{"status":
"not_restored", "leftovers": [<path>, ...]}`, 1 replaces any answer; the leftovers name each trust file
whose entry could not be removed, each plan or directory that could not be removed and the registry when
it differs. The settle bound counts from the last POST.

After the restore of a run whose POST may have dispatched, the check polls the view at most
`SHOWN_SECONDS` (30 s; the deadline is tested before each request, so the bound adds only the one
request under way at the deadline, a view read of `FETCH_TIMEOUT` or the single Cancel POST of
`POST_TIMEOUT`) until it answers with a `registration` member and an `entries` list, the project id
is no longer listed and the registration is the complete entry the first view showed (or both null).
A done registration of its own root that offers Cancel is cancelled once through `POST
/api/register-cancel {"root", "restore": true}`, after which the trust cards still open are read again
(the Cancel drops that root's trust failures). A view that never shows it adds the leftover
`registration`, and a not-restored answer of a run that was not met carries that run's answer as
`verdict`. Met is `{"status": "met", "project_id": <id>,
"root": <root>, "restored": true}`, 0.
"""

from __future__ import annotations

import argparse
import http.client
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from urllib.parse import urlsplit

from agent_tools.console import folder_trust, register, service, write_guard
from agent_tools.project_contract import agent_platform
from agent_tools.system import siblings

CONTRACT_SOURCE = Path("home/common/agent-skills/tests/fixtures/project-contract-schema-2.json")
SETTLE_SECONDS = 2 * register.RUN_TIMEOUT + register.GIT_TIMEOUT + 60
POST_TIMEOUT = 60
LISTED_SECONDS = 30
SHOWN_SECONDS = 30
FETCH_TIMEOUT = 5.0
NOT_YET = 75
LOOPBACK = ("127.0.0.1", "localhost")
REGISTER_PATH = "/api/register-project"
CONFIRM_PATH = "/api/register-confirm"
CANCEL_PATH = "/api/register-cancel"
TRUST_CHECK_PATH = "/api/trust-check"
STATE_PATH = "/api/state"
DIGEST = "a1" * 32
GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
           "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(root: Path, *arguments: str) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), *arguments], check=True, text=True, timeout=120,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, env={**os.environ, **GIT_ENV})
    return done.stdout


def _write(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _commit(root: Path, message: str) -> None:
    _git(root, "add", "-A")
    _git(root, "commit", "--quiet", "-m", message)


def _contract(contract_source: Path, project_id: str) -> dict:
    contract = json.loads(contract_source.read_text("utf-8"))
    contract["project"] = {"id": project_id, "name": project_id.split("/")[-1]}
    contract["bindings"]["paths"]["artifacts"] = {
        "specs": ".agents/artifacts/specs", "plans": ".agents/artifacts/plans"}
    contract["bindings"]["paths"]["rejections"] = [".agents/knowledge/rejections"]
    contract["release"] = "unsupported"
    review = contract["bindings"]["workflow"]["review"]
    for role in ("plan", "code"):
        contract["bindings"]["commands"][review[role]]["argv"] = ["true"]
    contract["bindings"]["tracker"]["cli"] = "gh"
    contract["bindings"]["vcs"]["integration_branch"] = "main"
    return contract


def _scaffold(root: Path, contract: dict, environ: Mapping[str, str]) -> None:
    _write(root, ".agents/instructions/bootstrap.md", "# invariants\n")
    for standards in contract["bindings"]["paths"]["standards"]:
        (root / standards).mkdir(parents=True, exist_ok=True)
    _write(root, ".agents/project.json", json.dumps(contract, indent=2) + "\n")
    done = subprocess.run(
        [*siblings.sibling_argv("project_contract.resolve_project"),
         "write-projections", "--repo-root", str(root)],
        env=dict(environ), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, text=True, timeout=120)
    if done.returncode != 0:
        raise RuntimeError(f"the fixture projections could not be rendered: {done.stdout}")


def _adoption_records(root: Path) -> None:
    migration_map = f".agents/knowledge/archive/path-migrations/{DIGEST}.json"
    _write(root, migration_map, json.dumps({
        "schema_version": 1, "migration_id": f"sha256:{DIGEST}", "moves": []}) + "\n")
    _write(root, f".agents/artifacts/evidence/{DIGEST}.json", json.dumps({
        "schema_version": 1, "plan_id": f"sha256:{DIGEST}", "outcome": "no_change",
        "base_revision": _git(root, "rev-parse", "HEAD").strip(),
        "platform": {"platform_version": "1.0.0", "project_schema_versions": [1],
                     "resolved_schema_version": 1},
        "decisions_accepted": [], "sources": [], "checks": [],
        "path_migration_map": migration_map}) + "\n")


def adopted_repository(parent: Path, project_id: str, contract_source: Path, *,
                       environ: Mapping[str, str] | None = None) -> Path:
    root = parent / "repo"
    root.mkdir(parents=True)
    root = root.resolve()
    _git(root, "init", "--quiet", "-b", "main")
    _git(root, "config", "user.name", "t")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "commit.gpgsign", "false")
    contract = _contract(contract_source, project_id)
    _scaffold(root, contract, os.environ if environ is None else environ)
    _write(root, ".agents/runtime/.gitignore", "*\n")
    _git(root, "add", "-f", ".agents/runtime/.gitignore")
    for standards in contract["bindings"]["paths"]["standards"]:
        _write(root, f"{standards}/bar.md", "# the bar\n")
    _commit(root, "fixture")
    _adoption_records(root)
    _commit(root, "adopt")
    bare = parent / "origin.git"
    _git(parent, "init", "--quiet", "--bare", "-b", "main", str(bare))
    _git(root, "remote", "add", "origin", str(bare))
    _git(root, "push", "--quiet", "origin", "main")
    return root


Answer = tuple[int | None, bytes]


def _request(method: str, url: str, headers: Mapping[str, str], body: bytes | None,
             timeout: float) -> Answer:
    parts = urlsplit(url)
    path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
    connection = http.client.HTTPConnection(parts.hostname, parts.port, timeout=timeout)
    try:
        connection.request(method, path, body=body, headers=dict(headers))
        response = connection.getresponse()
        return response.status, response.read()
    except (OSError, http.client.HTTPException):
        return None, b""
    finally:
        connection.close()


def default_fetch(url: str) -> Answer:
    return _request("GET", url, {}, None, FETCH_TIMEOUT)


def default_post(url: str, headers: Mapping[str, str], body: bytes) -> Answer:
    return _request("POST", url, headers, body, POST_TIMEOUT)


def _loopback_url(text: str) -> str:
    try:
        parts = urlsplit(text)
        parts.port  # noqa: B018  raises ValueError on a bad port
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a URL: {text}") from None
    if parts.scheme != "http" or parts.hostname not in LOOPBACK:
        raise argparse.ArgumentTypeError("the URL must be http on 127.0.0.1 or localhost")
    return text


def _seconds(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"not a number: {text}") from None
    if not value > 0:
        raise argparse.ArgumentTypeError("must be positive")
    return value


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(prog="register_check", description=__doc__.splitlines()[0])
    result.add_argument("--url", type=_loopback_url,
                        default=f"http://127.0.0.1:{service.DEFAULT_PORT}")
    result.add_argument("--token-file", type=Path, default=None)
    result.add_argument("--contract", type=Path, default=CONTRACT_SOURCE)
    result.add_argument("--wait", type=_seconds, default=SETTLE_SECONDS)
    return result


def _json_object(answer: Answer) -> dict | None:
    status, body = answer
    if status != 200:
        return None
    try:
        document = json.loads(body)
    except ValueError:
        return None
    return document if isinstance(document, dict) else None


def _is_running(document: Mapping, root: str) -> bool:
    registration = document.get("registration")
    return (isinstance(registration, dict) and registration.get("root") == root
            and registration.get("status") == "running")


def _listed(document: Mapping, project_id: str) -> bool:
    for entry in document.get("entries") or ():
        if not isinstance(entry, dict):
            continue
        members = entry["projects"] if entry.get("type") == "quiet_group" else (entry,)
        if any(isinstance(m, dict) and m.get("project_id") == project_id for m in members):
            return True
    return False


def _asking(document: Mapping, root: str) -> bool:
    inbox = document.get("inbox")
    cards = inbox.get("open") if isinstance(inbox, dict) else None
    return any(isinstance(c, dict) and c.get("reason") == "register_confirm"
               and c.get("root") == str(root) for c in cards or ())


def _shown_back(document: Mapping, project_id: str, registration_before: object) -> bool:
    """True when the view shows the registration it showed before the run and no longer lists the project."""
    return ("registration" in document and isinstance(document.get("entries"), list)
            and not _listed(document, project_id)
            and document["registration"] == registration_before)


def _poll(fetch: Callable[[str], Answer], url: str, poll: float, bound: float,
          ready: Callable[[dict], bool]) -> bool:
    end = time.monotonic() + bound
    while True:
        document = _json_object(fetch(url))
        if document is not None and ready(document):
            return True
        if time.monotonic() >= end:
            return False
        time.sleep(poll)


def _trust_cards(fetch, base: str, root: Path) -> list[dict] | None:
    keys = {os.path.realpath(root), str(root)}
    document = _json_object(fetch(base + STATE_PATH))
    if document is None:
        return None
    inbox = document.get("inbox")
    found = inbox.get("open") if isinstance(inbox, dict) else None
    return [card for card in found or ()
            if isinstance(card, dict) and card.get("reason") == "trust_failed"
            and card.get("root") in keys]


def _trust_left(fetch, base: str, root: Path) -> list[str]:
    """The Check again cards still open for the root, named; `trust cards unread` when the view fails."""
    cards = _trust_cards(fetch, base, root)
    if cards is None:
        return ["trust cards unread"]
    return [f"trust card {card.get('profile')}" for card in cards]


def _clear_trust_cards(fetch, post, base: str, token: str, root: Path) -> list[str]:
    """Check again each Check again card the fixture's grant left; the cards still open, named.

    The cards live in the console's event log, which the check cannot edit: a granted retry is what
    clears one, so this runs before the trust entries are removed.
    """
    cards = _trust_cards(fetch, base, root)
    if cards is None:
        return ["trust cards unread"]
    headers = {"Origin": base, write_guard.TOKEN_HEADER: token, "Content-Type": "application/json"}
    for card in cards:
        post(base + TRUST_CHECK_PATH, headers,
             json.dumps({"root": card["root"], "profile": card.get("profile")}).encode("utf-8"))
    return _trust_left(fetch, base, root)


def _restore(tmp: Path, root: Path | None, project_id: str, before: list[dict],
             clear: Callable[[Path], list[str]] = lambda root: []) -> list[str]:
    """Remove what the run left; the paths still left, the registry's included, else an empty list."""
    leftovers: list[str] = []
    try:
        if any(entry["project_id"] == project_id
               for entry in service.read_fleet(agent_platform.registry_path()) or []):
            with agent_platform.registry_transaction() as entries:
                agent_platform.write_registry(
                    [entry for entry in entries if entry["project_id"] != project_id])
    except Exception as error:  # noqa: BLE001 -- the comparison below decides
        print(f"register_check: {type(error).__name__}", file=sys.stderr)
    if root is not None:
        try:
            leftovers.extend(clear(root))
        except Exception as error:  # noqa: BLE001 -- a card left is named, never raised
            print(f"register_check: {type(error).__name__}", file=sys.stderr)
            leftovers.append("trust cards")
        key = os.path.realpath(root)
        for _, path in folder_trust.targets(Path.home(), service.default_profile_dirs()):
            try:
                if folder_trust.remove_entry(path, key) == folder_trust.FAILED:
                    leftovers.append(str(path))
            except Exception as error:  # noqa: BLE001 -- a file left is named, never raised
                print(f"register_check: {type(error).__name__}", file=sys.stderr)
                leftovers.append(str(path))
        for plan in (agent_platform.state_root() / "adopt" / "plans").glob("*.json"):
            try:
                handoff = json.loads(plan.read_text("utf-8")).get("handoff")
                if isinstance(handoff, dict) and handoff.get("repo_root") == str(root):
                    plan.unlink()
            except FileNotFoundError:
                continue
            except OSError:
                leftovers.append(str(plan))
            except (ValueError, AttributeError):
                continue
    shutil.rmtree(tmp, ignore_errors=True)
    if os.path.lexists(tmp):
        leftovers.append(str(tmp))
    after = service.read_fleet(agent_platform.registry_path()) or []
    if (sorted(after, key=lambda e: e["project_id"])
            != sorted(before, key=lambda e: e["project_id"])):
        leftovers.append(str(agent_platform.registry_path()))
    return leftovers


def _restore_view(fetch, post, base: str, token: str, root: Path, project_id: str,
                  registration_before: object, poll: float, bound: float) -> tuple[list[str], bool]:
    """Wait for the page to show the registration it showed before the run; the leftovers, whether it cancelled.

    A done registration of the check's own root that offers Cancel is cancelled once, restoring.
    The deadline is tested before each request, so at most the one request under way overruns it.
    """
    end = time.monotonic() + bound
    cancelled = False
    while True:
        if time.monotonic() >= end:
            return ["registration"], cancelled
        document = _json_object(fetch(base + STATE_PATH))
        if document is not None:
            if _shown_back(document, project_id, registration_before):
                return [], cancelled
            if time.monotonic() >= end:
                return ["registration"], cancelled
            shown = document.get("registration")
            if (not cancelled and isinstance(shown, dict) and shown.get("root") == str(root)
                    and shown.get("status") == "done" and shown.get("cancel") is True):
                headers = {"Origin": base, write_guard.TOKEN_HEADER: token,
                           "Content-Type": "application/json"}
                post(base + CANCEL_PATH, headers,
                     json.dumps({"root": str(root), "restore": True}).encode("utf-8"))
                cancelled = True
        time.sleep(min(poll, max(0.0, end - time.monotonic())))


def _text(body: bytes) -> str:
    return body.decode("utf-8", "replace").strip()


def _exercise(args, token: str, fetch, post, root: Path, project_id: str, poll: float,
              reached: list[float]) -> tuple[int, dict]:
    parts = urlsplit(args.url)
    base = f"http://{parts.netloc}"
    status, body = post(
        base + REGISTER_PATH,
        {"Origin": base, write_guard.TOKEN_HEADER: token, "Content-Type": "application/json"},
        json.dumps({"path": str(root), "unless_open": True}).encode("utf-8"))
    if status is not None and 400 <= status <= 499:
        if status == 409 and (_text(body).startswith("a registration is already running")
                              or _text(body) == register.OPEN_SHOWN):
            return NOT_YET, {"status": "busy"}
        return 1, {"status": "not_met", "reason": f"refused {status} {_text(body)}"}
    reached.append(time.monotonic())
    if status is not None and status != 204:
        return 1, {"status": "not_met", "reason": f"refused {status} {_text(body)}"}
    state = base + STATE_PATH
    found: dict = {}
    asked: list[bool] = []
    listed: list[bool] = []

    def done(document: dict) -> bool:
        registration = document.get("registration")
        if (isinstance(registration, dict) and registration.get("root") == str(root)
                and registration.get("status") == "done"):
            found.update(registration)
            asked.append(_asking(document, str(root)))
            listed.append(_listed(document, project_id))
            return True
        return _listed(document, project_id)

    if not _poll(fetch, state, poll, args.wait, done):
        return 1, {"status": "not_met", "reason": "no result"}
    if asked and asked[-1]:
        waited = found.get("at")
        headers = {"Origin": base, write_guard.TOKEN_HEADER: token,
                   "Content-Type": "application/json"}
        status, body = post(base + CONFIRM_PATH, headers, json.dumps(
            {"root": str(root), "choice": register.CONFIRM_VALUE}).encode("utf-8"))
        if status is not None and 400 <= status <= 499:
            return 1, {"status": "not_met", "reason": f"refused {status} {_text(body)}"}
        reached.append(time.monotonic())
        if status is not None and status != 204:
            return 1, {"status": "not_met", "reason": f"refused {status} {_text(body)}"}
        found.clear()
        listed.clear()

        def answered(document: dict) -> bool:
            registration = document.get("registration")
            if (isinstance(registration, dict) and registration.get("root") == str(root)
                    and registration.get("status") == "done" and registration.get("at") != waited):
                found.update(registration)
                listed.append(_listed(document, project_id))
                return True
            return _listed(document, project_id)

        if not _poll(fetch, state, poll, args.wait, answered):
            return 1, {"status": "not_met", "reason": "no result"}
    if found and not (listed and listed[-1]) and found.get("result") != "registered":
        return 1, {"status": "not_met", "reason": str(found.get("headline"))}
    if not _poll(fetch, state, poll, LISTED_SECONDS, lambda d: _listed(d, project_id)):
        return 1, {"status": "not_met", "reason": "not listed"}
    return 0, {"status": "met", "project_id": project_id, "root": str(root), "restored": True}


def main(argv: list[str] | None = None, *, fetch=None, post=None, tmp_root=None,
         project_id: str | None = None, poll: float = 1.0, settle: float = SETTLE_SECONDS,
         shown: float = SHOWN_SECONDS) -> int:
    args = parser().parse_args(argv)
    fetch = fetch or default_fetch
    post = post or default_post
    code, result = _decide(args, fetch, post, tmp_root, project_id, poll, settle, shown)
    print(json.dumps(result, sort_keys=True))
    return code


def _decide(args, fetch, post, tmp_root, project_id, poll, settle, shown) -> tuple[int, dict]:
    state = f"http://{urlsplit(args.url).netloc}{STATE_PATH}"
    answer = fetch(state)
    if answer[0] != 200:
        return NOT_YET, {"status": "not_running"}
    document = _json_object(answer)
    if document is None or "registration" not in document:
        return NOT_YET, {"status": "not_deployed"}
    registration_before = document["registration"]
    if register.open_shown(registration_before):
        return NOT_YET, {"status": "busy"}
    token_file = args.token_file or agent_platform.state_root() / "console" / "page-token"
    try:
        token = token_file.read_text("utf-8").strip()
    except (OSError, ValueError):
        return NOT_YET, {"status": "no_token"}
    registry = agent_platform.registry_path()
    registry_before = service.read_fleet(registry)
    if registry_before is None and os.path.lexists(registry):
        return NOT_YET, {"status": "registry_unreadable"}
    registry_before = registry_before or []
    base = f"http://{urlsplit(args.url).netloc}"
    tmp = Path(tempfile.mkdtemp(prefix="console-register-check-", dir=tmp_root))
    pid = project_id or "console-check/register-" + secrets.token_hex(4)
    root: Path | None = None
    reached: list[float] = []
    posted = False
    trust: list[str] = []
    verdict: tuple[int, dict] = (1, {"status": "not_met"})
    settled = True

    def clear(one: Path) -> list[str]:
        trust[:] = _clear_trust_cards(fetch, post, base, token, one) if posted else []
        return []

    try:
        try:
            root = adopted_repository(tmp, pid, args.contract)
        except Exception as error:  # noqa: BLE001 -- any builder failure is "no fixture"
            return NOT_YET, {"status": "no_fixture", "reason": type(error).__name__}
        again = _json_object(fetch(state))
        if again is None or "registration" not in again:
            verdict = (NOT_YET, {"status": "not_running"})
        elif again["registration"] != registration_before:
            verdict = (NOT_YET, {"status": "busy"})
        else:
            posted = True
            verdict = _exercise(args, token, fetch, post, root, pid, poll, reached)
    finally:
        if reached:
            settled = _poll(fetch, state, poll, settle - (time.monotonic() - reached[-1]),
                            lambda d: not _is_running(d, str(root)))
        leftovers = _restore(tmp, root, pid, registry_before, clear) if settled else []
        if settled and reached and root is not None:
            left, cancelled = _restore_view(fetch, post, base, token, root, pid,
                                            registration_before, poll, shown)
            if cancelled and trust:
                trust[:] = _trust_left(fetch, base, root)
            leftovers = trust + leftovers + left
        else:
            leftovers = trust + leftovers
    if not settled:
        return 1, {"status": "unsettled", "project_id": pid, "root": str(root)}
    if leftovers:
        answer = {"status": "not_restored", "leftovers": leftovers}
        if verdict[0] != 0:
            answer["verdict"] = verdict[1]
        return 1, answer
    return verdict


if __name__ == "__main__":
    sys.exit(main())
