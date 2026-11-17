"""A hermetic world for the bypass proof's `wakes` step (#1230): a fake `claude-account` that keeps a registry.

`WakeProofWorld(test_case)` builds a temporary directory holding a `HOME` with the platform
manifest, an accounts directory with the chosen profile `work` (its `.claude.json` and an empty
`sessions/` registry directory), a scratch `TMPDIR`, and a `bin/` first on `PATH` with three fakes:
`systemd-run` (drops its arguments through the first `--` and runs the rest), `git` (the real git,
after the `FAKE_GIT_DELAY` seconds when that variable is set) and `claude-account`. No test
support here is a `TestCase`.

The fake `claude-account` logs each argv and keeps one background session, `m1aaaaaaaaaaaaaa`, in
a state file: a launch (`run --bg`) starts a daemon, registers the session the way the client
does (a `<pid>.json` record in the profile's `sessions/`, with `procStart` and `pidDomain` that
`sessions.process_matches` accepts), runs `sprint contract` from the manager's settings
environment and goes idle. A relay (`run -p`) applies the client's rule: it delivers a message
only when sender and receiver are both bypassing or both are not, runs `sprint inbox` in the
receiver and goes idle. The `FAKE_CLIENT_*` variables of a run's environment make it fail:
`LAUNCH_FAILS`, `NOT_READY`, `NO_REGISTRY`, `STAYS_BUSY`, `LISTING_FAILS`, `RELAY_FAILS`,
`RELAY_DELAY=S`, `FORCE_DEFAULT_SENDER`, `HOLD_AFTER=N`, `LATE_INBOX=S` (the same turn calls
`sprint inbox` again after `S` seconds) and `STOP_FAILS`.
"""
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from .guard_policy_world import MANIFEST, REPO_ROOT

PROFILE = "work"
SESSION_ID = "m1aaaaaaaaaaaaaa"

FAKE_SYSTEMD_RUN = """#!{python}
import os
import sys

argv = sys.argv[1:]
rest = argv[argv.index("--") + 1:]
os.execvp(rest[0], rest)
"""

FAKE_GIT = """#!{python}
import os
import sys
import time

delay = os.environ.get("FAKE_GIT_DELAY")
if delay:
    time.sleep(float(delay))
os.execv({real!r}, ["git", *sys.argv[1:]])
"""

FAKE_CLIENT = """#!{python}
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, {source!r})  # the verify check sets a relative PYTHONPATH the fake's cwd cannot resolve
from agent_tools.console import sessions

LOG = Path(os.environ["FAKE_WAKE_LOG"])
STATE = Path(os.environ["FAKE_WAKE_STATE"])
ACCOUNTS = Path(os.environ["CLAUDE_ACCOUNTS_DIR"])
PROFILE = {profile!r}
SESSION_ID = {session_id!r}
BYPASS = "bypassPermissions"
argv = sys.argv[1:]


def load():
    return json.loads(STATE.read_text(encoding="utf-8"))


def write_atomically(path, text):
    temporary = Path(str(path) + ".tmp" + str(os.getpid()))
    temporary.write_text(text, encoding="utf-8")
    os.replace(temporary, path)


def save(state):
    write_atomically(STATE, json.dumps(state))


def proc_start(pid):
    stat = Path("/proc/" + str(pid) + "/stat").read_text(encoding="utf-8")
    return stat.rsplit(")", 1)[1].split()[19]


def set_status(status):
    if os.environ.get("FAKE_CLIENT_NO_REGISTRY"):
        return
    state = load()
    pid, session = state["pid"], state["session"]
    document = {{"sessionId": SESSION_ID, "cwd": session["cwd"], "pid": pid,
                "procStart": proc_start(pid), "pidDomain": sessions.own_pid_domain(),
                "status": status, "name": session["name"],
                "updatedAt": int(time.time() * 1000)}}
    target = ACCOUNTS / "profiles" / PROFILE / "sessions" / (str(pid) + ".json")
    write_atomically(target, json.dumps(document))


def sprint(command, env):
    subprocess.run(["/bin/sh", "-c", command], env=env, cwd=load()["session"]["cwd"],
                   capture_output=True, check=False)


def receiver_env():
    with open(load()["session"]["settings"], encoding="utf-8") as handle:
        return {{**os.environ, **json.load(handle)["env"]}}


if argv[:1] == ["__late"]:
    time.sleep(float(argv[1]))
    sprint("sprint inbox", json.loads(argv[2]))
    set_status("idle")
    sys.exit(0)

with open(LOG / "argv.log", "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv) + "\\n")

if argv[:2] == ["run", "--bg"]:
    name = argv[argv.index("--name") + 1]
    settings_path = argv[argv.index("--settings") + 1]
    with open(settings_path, encoding="utf-8") as handle:
        document = json.load(handle)
    cwd = os.getcwd()
    with open(ACCOUNTS / "profiles" / PROFILE / ".claude.json", encoding="utf-8") as handle:
        entry = json.load(handle).get("projects", {{}}).get(os.path.realpath(cwd), {{}})
    first = document["env"]["PATH"].split(":")[0]
    entry_log = {{"settings": document,
                 "trusted": entry.get("hasTrustDialogAccepted") is True,
                 "sprint_executable": os.access(os.path.join(first, "sprint"), os.X_OK)}}
    with open(LOG / "launch.log", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry_log) + "\\n")
    daemon = subprocess.Popen([sys.executable, "-c", "import signal; signal.pause()"],
                              start_new_session=True, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    state = load()
    state["pid"] = daemon.pid
    state["daemons"].append(daemon.pid)
    state["session"] = {{"sessionId": SESSION_ID, "name": name, "settings": settings_path,
                        "cwd": cwd, "stopped": False, "removed": False}}
    save(state)
    set_status("busy")
    if not os.environ.get("FAKE_CLIENT_NOT_READY"):
        sprint("sprint contract", {{**os.environ, **document["env"]}})
    if not os.environ.get("FAKE_CLIENT_STAYS_BUSY"):
        set_status("idle")
    if os.environ.get("FAKE_CLIENT_LAUNCH_FAILS"):
        sys.stderr.write("launch broke\\n")
        sys.exit(1)
    sys.exit(0)

if argv == ["run", "agents", "--json", "--all"]:
    if os.environ.get("FAKE_CLIENT_LISTING_FAILS"):
        sys.stderr.write("listing broken\\n")
        sys.exit(1)
    session = load().get("session")
    rows = []
    if session is not None and not session["removed"]:
        rows.append({{"sessionId": SESSION_ID, "name": session["name"], "cwd": session["cwd"],
                     "kind": "background", "state": "idle"}})
    print(json.dumps(rows))
    sys.exit(0)

if argv[:2] == ["run", "-p"]:
    if os.environ.get("FAKE_CLIENT_RELAY_DELAY"):
        time.sleep(float(os.environ["FAKE_CLIENT_RELAY_DELAY"]))
    sender_bypass = False
    if "--permission-mode" in argv:
        sender_bypass = argv[argv.index("--permission-mode") + 1] == BYPASS
    if os.environ.get("FAKE_CLIENT_FORCE_DEFAULT_SENDER"):
        sender_bypass = False
    if os.environ.get("FAKE_CLIENT_RELAY_FAILS"):
        print("FAILED")
        sys.exit(0)
    marker = 'peer session named "'
    target = argv[-1].split(marker, 1)[1].split('"', 1)[0]
    state = load()
    session = state.get("session")
    if session is not None and session["name"] == target:
        with open(session["settings"], encoding="utf-8") as handle:
            document = json.load(handle)
        receiver_bypass = document["permissions"]["defaultMode"] == BYPASS
        held = state["deliveries"] >= int(os.environ.get("FAKE_CLIENT_HOLD_AFTER", "1000000"))
        if sender_bypass == receiver_bypass and not held:
            state["deliveries"] += 1
            save(state)
            env = {{**os.environ, **document["env"]}}
            set_status("busy")
            sprint("sprint inbox", env)
            late = os.environ.get("FAKE_CLIENT_LATE_INBOX")
            if late:
                subprocess.Popen([sys.argv[0], "__late", late, json.dumps(env)],
                                 start_new_session=True, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif not os.environ.get("FAKE_CLIENT_STAYS_BUSY"):
                set_status("idle")
    print("SENT")
    sys.exit(0)

if argv[:2] in (["run", "stop"], ["run", "rm"]) and len(argv) == 3:
    state = load()
    session = state.get("session")
    if session is None or not SESSION_ID.startswith(argv[2]):
        sys.stderr.write("no such session\\n")
        sys.exit(1)
    if argv[1] == "stop":
        if os.environ.get("FAKE_CLIENT_STOP_FAILS"):
            sys.stderr.write("cannot stop\\n")
            sys.exit(1)
        try:
            os.kill(state["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        session["stopped"] = True
    else:
        session["removed"] = True
    save(state)
    sys.exit(0)

sys.stderr.write("fake claude-account: unsupported\\n")
sys.exit(1)
"""


def _executable(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)


class WakeProofWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home = self.tmp / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents/share/platform-manifest.json")
        self.accounts = self.tmp / "accounts"
        (self.accounts / "profiles" / PROFILE / "sessions").mkdir(parents=True)
        (self.accounts / "chosen-profile").write_text(PROFILE + "\n", encoding="utf-8")
        self.trust = self.accounts / "profiles" / PROFILE / ".claude.json"
        self.trust.write_text('{"projects": {}}', encoding="utf-8")
        self.scratch = self.tmp / "scratch"
        self.scratch.mkdir()
        self.log = self.tmp / "log"
        self.log.mkdir()
        self.state_file = self.tmp / "state.json"
        self.state_file.write_text(json.dumps({"daemons": [], "deliveries": 0}), encoding="utf-8")
        real_git = shutil.which("git")
        if real_git is None:
            raise AssertionError("git is not on PATH; the wake proof world needs it")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        _executable(self.bin / "systemd-run", FAKE_SYSTEMD_RUN.format(python=sys.executable))
        _executable(self.bin / "git", FAKE_GIT.format(python=sys.executable, real=real_git))
        _executable(self.bin / "claude-account", FAKE_CLIENT.format(
            python=sys.executable, profile=PROFILE, session_id=SESSION_ID,
            source=str(REPO_ROOT / "python")))
        self.env = {**os.environ, "HOME": str(self.home),
                    "CLAUDE_ACCOUNTS_DIR": str(self.accounts), "TMPDIR": str(self.scratch),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(REPO_ROOT / "python"),
                    "FAKE_WAKE_LOG": str(self.log), "FAKE_WAKE_STATE": str(self.state_file)}
        self.env.pop("CLAUDECODE", None)
        test_case.addCleanup(self.kill_daemons)

    def daemons(self) -> list[int]:
        return json.loads(self.state_file.read_text(encoding="utf-8"))["daemons"]

    def kill_daemons(self) -> None:
        for pid in self.daemons():
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def run(self, *args: str, env: dict[str, str] | None = None):
        """Run `bypass-proof wakes`; `(exit code, report or None, stderr, seconds)`."""
        started = time.monotonic()
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.console.bypass_proof", "wakes", *args],
            cwd=self.tmp, env={**self.env, **(env or {})}, capture_output=True, text=True,
            timeout=120)
        seconds = time.monotonic() - started
        report = json.loads(done.stdout) if done.stdout.strip() else None
        return done.returncode, report, done.stderr, seconds

    def _lines(self, name: str) -> list:
        path = self.log / name
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def argv_log(self) -> list[list[str]]:
        return self._lines("argv.log")

    def launch_log(self) -> list[dict]:
        return self._lines("launch.log")

    def relay_argvs(self) -> list[list[str]]:
        return [argv for argv in self.argv_log() if argv[1:2] == ["run"] and "-p" in argv]

    def record(self) -> dict | None:
        path = self.home / ".agents/state/console/bypass-proof-wakes.json"
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def trust_file(self) -> Path:
        return self.trust

    def scratch_entries(self) -> list[str]:
        return sorted(entry.name for entry in self.scratch.iterdir())

    def live_daemons(self) -> list[int]:
        return [pid for pid in self.daemons() if self._running(pid)]

    @staticmethod
    def _running(pid: int) -> bool:
        try:
            stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
        except OSError:
            return False
        return stat.rsplit(")", 1)[1].split()[0] != "Z"
