"""Restart the eleven-m5 oMLX server for pending settings, but only while it is idle.

A restart drops every request the server is serving, so the gate reads `/health` first:
it restarts when the server is down or reports no loaded model, and defers when a model
is loaded or the pinned models are still preloading. Any state it cannot read (a timeout,
another status, a body that is not the expected JSON) also defers: a restart that waits
costs one more activation, a restart that does not wait can cut off a running request.
`--now` skips the check. The marker `<state-dir>/.restart-needed` holds one reason per line;
it is removed only by a restart that succeeded, so a deferral and a failure both keep it.
A reason starting with `launchd plist changed: ` is applied by `--reload-bin` (an unload and load
of the job) instead of a kill, because a kill only relaunches the job definition launchd holds.
The kill is given the uid of `--server-user`, the user the server runs as, never the caller's, so
root through sudo signals the server's processes. Its exit 1 means it matched no server process: that
is reported as nothing restarted and keeps the marker, and exits 1 unless `/health` found the server
down (a stopped server has nothing to end, and launchd starts it on the new code). A caller that
cannot read the server's private state directory (another account without sudo) is refused with a
message naming the server's user, before any kill.

`--reactive` is the gate for a restart nobody scheduled: it needs no marker, reads the API key from the
first line of stdin and asks the authenticated `/api/status` for the requests in flight. It restarts only
when no request is active or waiting and no model but a `--pinned-model` is loaded or loading, and it
sends the key to a loopback `http` URL only, through a read that follows no redirect, and only after
`lsof` shows that this account's `omlx-server` is the listener on the status port (a health answer
cannot tell whose server answered). Every state it
cannot read defers. Exit 0 is restarted, 75 deferred (one stderr line), 1 the kill failed.
"""

import argparse
import http.client
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HEALTH_TIMEOUT_SECONDS = 5
# The server is on this host: a proxy from the environment must never answer for it.
DIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}))
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
DEFERRED = 75
LISTENER_BIN = "/usr/sbin/lsof"
SERVER_NAME = "omlx-server"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


# A redirect would carry the key to another URL: the 3xx answer is raised as an HTTPError instead.
STATUS_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
UNRECORDED = "unrecorded change"
RELOAD_PREFIX = "launchd plist changed: "
NOTHING_MATCHED = 1
SERVER_DOWN = "server down"


def read_reasons(marker):
    try:
        lines = marker.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    return [line for line in lines if line.strip()] or [UNRECORDED]


def read_health(url):
    """Return (status, body) of the health answer; a refused connection is (None, None)."""
    try:
        with DIRECT.open(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read()
    except urllib.error.URLError as error:
        if isinstance(error.reason, ConnectionRefusedError):
            return None, None
        raise


def loaded_count(body):
    pool = body.get("engine_pool")
    count = pool.get("loaded_count") if isinstance(pool, dict) else None
    return count if isinstance(count, int) and not isinstance(count, bool) else None


def classify(url):
    """Return None or SERVER_DOWN when the server may be restarted, else why it must wait."""
    try:
        status, raw = read_health(url)
        if status is None:
            return SERVER_DOWN
        body = json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return f"server state unknown: {error}"
    if not isinstance(body, dict):
        return "server state unknown: health answer is not an object"
    if status == 503 and body.get("status") == "loading":
        return "pinned models still loading"
    count = loaded_count(body)
    if status == 200 and body.get("status") == "healthy" and count is not None:
        if count == 0:
            return None
        return "1 model loaded" if count == 1 else f"{count} models loaded"
    return f"server state unknown: status {status} with an unexpected body"


def restart(restart_bin, reload_bin, server_user, down, marker, reasons):
    reloading = any(reason.startswith(RELOAD_PREFIX) for reason in reasons)
    verb, done = ("reload", "reloaded its launchd job") if reloading else ("restart", "restarted")
    if reloading:
        returncode = subprocess.run([reload_bin]).returncode
    else:
        try:
            uid = pwd.getpwnam(server_user).pw_uid
        except KeyError:
            print(f"oMLX: restart failed (no user {server_user}); .restart-needed retained", file=sys.stderr)
            return 1
        returncode = subprocess.run([restart_bin, str(uid)]).returncode
        if returncode == NOTHING_MATCHED:
            kept = "; .restart-needed retained for the next activation" if marker.exists() else ""
            print(f"oMLX: nothing was restarted (no omlx-server process of user {server_user}){kept}", file=sys.stderr)
            return 0 if down else 1
    if returncode != 0:
        print(
            f"oMLX: {verb} failed (exit {returncode}); .restart-needed retained for the next activation",
            file=sys.stderr,
        )
        return 1
    marker.unlink(missing_ok=True)
    print(f"oMLX: {done} for: {'; '.join(reasons)}", file=sys.stderr)
    return 0


def loopback(url):
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "http" and parts.hostname in LOOPBACK


def read_status(url, key):
    """Return (status, body bytes) of the authenticated status answer, following no redirect."""
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        with STATUS_OPENER.open(request, timeout=HEALTH_TIMEOUT_SECONDS) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        with error:
            return error.code, b""


def count_ok(value):
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def classify_health(health_url):
    """Return None when the server is up and serving, else why the restart must wait."""
    try:
        status, raw = read_health(health_url)
        if status is None:
            return "server not running"
        body = json.loads(raw)
    except (OSError, ValueError, http.client.HTTPException) as error:
        return f"server state unknown: {error}"
    if not isinstance(body, dict):
        return "server state unknown: health answer is not an object"
    if status == 503 and body.get("status") == "loading":
        return "pinned models still loading"
    if status == 200 and body.get("status") == "healthy":
        return None
    return f"server state unknown: status {status} with an unexpected body"


def own_server_listens(listener_bin, status_url):
    """True when every listener `listener_bin` (lsof) shows on the status port is this account's oMLX server.

    lsof lists only this account's sockets, so a listener of another account shows as none."""
    port = urllib.parse.urlsplit(status_url).port or 80
    uid = os.getuid()
    argv = [listener_bin, "+c", "0", "-nP", "-a", "-u", str(uid), f"-iTCP:{port}", "-sTCP:LISTEN", "-Fpcu"]
    try:
        found = subprocess.run(
            argv, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=HEALTH_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return False
    owners: list[dict] = []
    for line in found.stdout.splitlines():
        if line.startswith("p"):
            owners.append({})
        elif owners and line[:1] in ("c", "u"):
            owners[-1][line[0]] = line[1:]
    return bool(owners) and all(
        owner.get("c") == SERVER_NAME and owner.get("u") == str(uid) for owner in owners)


def classify_reactive(health_url, status_url, key, pinned, listener_bin=LISTENER_BIN):
    """Return None when the server holds no request and no unpinned model, else why to wait."""
    if not (loopback(health_url) and loopback(status_url)):
        return "endpoint is not loopback"
    if not key:
        return "API key unreadable"
    why = classify_health(health_url)
    if why is not None:
        return why
    # The health answer proves nothing about who answered: the key goes only to this account's server.
    if not own_server_listens(listener_bin, status_url):
        return "listener is not the oMLX server"
    try:
        status, raw = read_status(status_url, key)
    except (OSError, http.client.HTTPException) as error:
        return f"request status unknown: {type(error).__name__}"
    if status != 200:
        return f"request status unknown: status {status}"
    unexpected = "request status unknown: unexpected body"
    try:
        body = json.loads(raw)
    except ValueError:
        return unexpected
    if not isinstance(body, dict):
        return unexpected
    loaded = body.get("loaded_models")
    counts = [body.get(name) for name in ("active_requests", "waiting_requests", "models_loading")]
    if not all(count_ok(count) for count in counts):
        return unexpected
    if not isinstance(loaded, list) or not all(isinstance(model, str) for model in loaded):
        return unexpected
    active, waiting, loading = counts
    others = sorted(set(loaded) - set(pinned))
    if others:
        return f"other model loaded: {', '.join(others)}"
    if loading > 0:
        return "a model is loading"
    if active > 0 or waiting > 0:
        return f"{active} active, {waiting} waiting requests"
    return None


def restart_reactive(restart_bin):
    returncode = subprocess.run([restart_bin]).returncode
    if returncode == 0:
        print("oMLX: restarted (reactive)", file=sys.stderr)
        return 0
    if returncode == 1:
        print("oMLX: restart deferred (no server process to signal)", file=sys.stderr)
        return DEFERRED
    print(f"oMLX: restart failed (exit {returncode})", file=sys.stderr)
    return 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--restart-bin", required=True)
    parser.add_argument("--reload-bin", required=True)
    parser.add_argument("--server-user", help="the user the oMLX server runs as (required without --reactive)")
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--status-url", default="http://127.0.0.1:8000/api/status")
    parser.add_argument("--pinned-model", action="append", default=[])
    parser.add_argument("--listener-bin", default=LISTENER_BIN)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--now", action="store_true", help="restart without reading /health")
    mode.add_argument("--reactive", action="store_true", help="restart only while no request is in flight")
    args = parser.parse_args(argv)

    if args.reactive:
        key = sys.stdin.readline().strip()
        why = classify_reactive(args.health_url, args.status_url, key, args.pinned_model, args.listener_bin)
        if why is not None:
            print(f"oMLX: restart deferred ({why})", file=sys.stderr)
            return DEFERRED
        return restart_reactive(args.restart_bin)

    if args.server_user is None:
        parser.error("--server-user is required without --reactive")
    if not os.access(args.state_dir, os.R_OK | os.X_OK):
        print(
            f"oMLX: cannot read {args.state_dir}; run omlx-restart as {args.server_user} or with sudo",
            file=sys.stderr,
        )
        return 1
    marker = args.state_dir / ".restart-needed"
    if not marker.exists() and not args.now:
        return 0
    reasons = read_reasons(marker)
    why = None if args.now else classify(args.health_url)
    if why in (None, SERVER_DOWN):
        return restart(args.restart_bin, args.reload_bin, args.server_user, why == SERVER_DOWN, marker, reasons)
    print(
        f"oMLX: restart deferred ({why}); pending: {'; '.join(reasons)}. "
        "Apply it with omlx-restart --now when the server may drop its requests.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
