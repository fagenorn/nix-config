"""Restart the eleven-m5 oMLX server for pending settings, but only while it is idle.

A restart drops every request the server is serving, so the gate reads `/health` first:
it restarts when the server is down or reports no loaded model, and defers when a model
is loaded or the pinned models are still preloading. Any state it cannot read (a timeout,
another status, a body that is not the expected JSON) also defers: a restart that waits
costs one more activation, a restart that does not wait can cut off a running request.
`--now` skips the check. The marker `<state-dir>/.restart-needed` holds one reason per line;
it is removed only by a restart that succeeded, so a deferral and a failure both keep it.
"""

import argparse
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request

HEALTH_TIMEOUT_SECONDS = 5
UNRECORDED = "unrecorded change"


def read_reasons(marker):
    try:
        lines = marker.read_text().splitlines()
    except FileNotFoundError:
        lines = []
    return [line for line in lines if line.strip()] or [UNRECORDED]


def read_health(url):
    """Return (status, body) of the health answer; a refused connection is (None, None)."""
    try:
        with urllib.request.urlopen(url, timeout=HEALTH_TIMEOUT_SECONDS) as response:
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
    """Return None when the server may be restarted, else why it must wait."""
    try:
        status, raw = read_health(url)
        if status is None:
            return None
        body = json.loads(raw)
    except (OSError, ValueError, urllib.error.URLError) as error:
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


def restart(restart_bin, marker, reasons):
    returncode = subprocess.run([restart_bin]).returncode
    if returncode != 0:
        print(
            f"oMLX: restart failed (exit {returncode}); .restart-needed retained for the next activation",
            file=sys.stderr,
        )
        return 1
    marker.unlink(missing_ok=True)
    print(f"oMLX: restarted for: {'; '.join(reasons)}", file=sys.stderr)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--restart-bin", required=True)
    parser.add_argument("--health-url", default="http://127.0.0.1:8000/health")
    parser.add_argument("--now", action="store_true", help="restart without reading /health")
    args = parser.parse_args(argv)

    marker = args.state_dir / ".restart-needed"
    if not marker.exists() and not args.now:
        return 0
    reasons = read_reasons(marker)
    why = None if args.now else classify(args.health_url)
    if why is None:
        return restart(args.restart_bin, marker, reasons)
    print(
        f"oMLX: restart deferred ({why}); pending: {'; '.join(reasons)}. "
        "Apply it with omlx-restart --now when the server may drop its requests.",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
