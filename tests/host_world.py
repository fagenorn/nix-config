"""A fake macOS host for the host-local adapter suites (issue 547 D3, D13, D21).

`HostWorld(test_case)` builds a temporary `root/` with a `bin/`, a `state/`, a `home/` and a git
`checkout/`, and patches `os.environ` and the working directory until the test's cleanup: `PATH`
is that `bin/` alone, `HOME` is `home/`, `HOST_WORLD` names `state/`, and git reads no global or
system configuration. No test reaches this host's `launchctl`, `codesign` or `security`: the
`bin/` holds a logging `git` wrapper over the real git, and fake `security`, `codesign` and
`launchctl` scripts. Each logs `{tool, argv}` to `state/calls.jsonl`, then answers from `state/` files; an
unregistered argv exits 64.

The fake `codesign` signs by writing `Contents/_CodeSignature/CodeResources`, a JSON seal over
every other entry of the bundle and the signing identity, verifies by recomputing the seal, and
prints the `-d --verbose=2` lines on stderr as the real tool does. `knobs.json` makes one
`{tool: {verb: ...}}` call sleep, write stderr and exit with a chosen code instead.

The fake `launchctl` keeps `state/launchd.json` (`{"jobs": {label: job}, "next_pid": n}`) and
answers `print gui/<uid>/<label>` with the block the real tool prints (issue 547 D21),
`bootout gui/<uid>/<label>` and `bootstrap gui/<uid> <plist>`; `load_job` seeds a job directly. A
knob on `launchctl` may also write `stdout`, before its stderr.
"""
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

# Computed once, before any world patches PATH, so a table that calls setUp() again while the
# previous world's patch is active never wraps that world's own wrapper.
REAL_GIT = os.path.realpath(shutil.which("git"))
IDENTITY = ("0123456789ABCDEF0123456789ABCDEF01234567", "Apple Development: Example Person (TEAM000001)")
OTHER = ("89ABCDEF0123456789ABCDEF0123456789ABCDEF", "Developer ID Application: Example Org (TEAM000002)")
TEAM = "TEAMID0001"
GIT_CONFIG = ("-c", "user.name=world", "-c", "user.email=world@example.invalid",
              "-c", "commit.gpgsign=false")
SEAL_DIRECTORY = "Contents/_CodeSignature"
NOT_SIGNED = "code object is not signed at all"

GIT_SCRIPT = """#!{python}
import json, os, sys
from pathlib import Path

with open(Path(os.environ["HOST_WORLD"]) / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "git", "argv": sys.argv[1:]}}) + "\\n")
os.execv({git!r}, [{git!r}, *sys.argv[1:]])
"""

SECURITY_SCRIPT = """#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["HOST_WORLD"])
argv = sys.argv[1:]
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "security", "argv": argv}}) + "\\n")
if argv != ["find-identity", "-v", "-p", "codesigning"]:
    sys.stderr.write("fake security: unregistered call\\n")
    sys.exit(64)
knobs = state / "knobs.json"
knob = json.loads(knobs.read_text("utf-8")).get("security", {{}}).get("find-identity") if knobs.exists() else None
if knob:
    time.sleep(knob["sleep"])
    sys.stderr.write(knob["stderr"])
    sys.exit(knob["exit"])
listing = json.loads((state / "identities.json").read_text("utf-8"))
time.sleep(listing["sleep"])
sys.stderr.write(listing["stderr"])
if listing["exit"]:
    sys.exit(listing["exit"])
for number, (digest, name) in enumerate(listing["pairs"], 1):
    sys.stdout.write(f'  {{number}}) {{digest}} "{{name}}"\\n')
sys.stdout.write(f"     {{len(listing['pairs'])}} valid identities found\\n")
"""

CODESIGN_SCRIPT = """#!{python}
import hashlib, json, os, plistlib, sys, time
from pathlib import Path

state = Path(os.environ["HOST_WORLD"])
argv = sys.argv[1:]
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "codesign", "argv": argv}}) + "\\n")
SEAL_DIRECTORY = {seal_directory!r}


def seal(bundle):
    entries = []
    for current, directories, files in os.walk(bundle):
        for name in directories + files:
            full = os.path.join(current, name)
            relative = os.path.relpath(full, bundle).replace(os.sep, "/")
            if relative == SEAL_DIRECTORY or relative.startswith(SEAL_DIRECTORY + "/"):
                continue
            if os.path.islink(full):
                entries.append((relative, b"link", os.readlink(full).encode()))
            elif os.path.isdir(full):
                entries.append((relative, b"dir", b""))
            else:
                entries.append((relative, b"file", Path(full).read_bytes()))
    digest = hashlib.sha256()
    for relative, kind, content in sorted(entries):
        digest.update(relative.encode() + b"\\0" + kind + b"\\0" + content)
    return digest.hexdigest()


def stored(bundle):
    resources = Path(bundle) / SEAL_DIRECTORY / "CodeResources"
    return json.loads(resources.read_text("utf-8")) if resources.exists() else None


if argv[:2] == ["--force", "--sign"] and len(argv) == 4:
    verb, bundle = "sign", argv[3]
elif argv[:3] == ["--verify", "--deep", "--strict"] and len(argv) == 4:
    verb, bundle = "verify", argv[3]
elif argv[:2] == ["-d", "--verbose=2"] and len(argv) == 3:
    verb, bundle = "display", argv[2]
else:
    sys.stderr.write("fake codesign: unregistered call\\n")
    sys.exit(64)
knobs = state / "knobs.json"
knob = json.loads(knobs.read_text("utf-8")).get("codesign", {{}}).get(verb) if knobs.exists() else None
if knob:
    time.sleep(knob["sleep"])
    sys.stderr.write(knob["stderr"])
    sys.exit(knob["exit"])
if verb == "sign":
    directory = Path(bundle) / SEAL_DIRECTORY
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "CodeResources").write_text(
        json.dumps({{"identity": argv[2], "seal": seal(bundle)}}), "utf-8")
    sys.exit(0)
current = stored(bundle)
if current is None:
    sys.stderr.write(f"{{bundle}}: {not_signed}\\n")
    sys.exit(1)
if verb == "verify":
    if current["seal"] != seal(bundle):
        sys.stderr.write(f"{{bundle}}: a sealed resource is missing or invalid\\n")
        sys.exit(1)
    sys.exit(0)
with open(Path(bundle) / "Contents/Info.plist", "rb") as handle:
    identifier = plistlib.load(handle)["CFBundleIdentifier"]
names = dict(json.loads((state / "identities.json").read_text("utf-8"))["pairs"])
lines = [f"Executable={{bundle}}/Contents/MacOS/notifier", f"Identifier={{identifier}}",
         "Format=app bundle with Mach-O thin (arm64)",
         "CodeDirectory v=20400 size=403 flags=0x0(none) hashes=6+3 location=embedded"]
if current["identity"] == "-":
    lines += ["Signature=adhoc", "TeamIdentifier=not set"]
else:
    lines += ["Signature size=4792", f"Authority={{names.get(current['identity'], current['identity'])}}",
              "Authority=Apple Worldwide Developer Relations Certification Authority",
              "Authority=Apple Root CA", "TeamIdentifier=TEAMID0001"]
lines.append("Sealed Resources version=2 rules=13 files=2")
sys.stderr.write("\\n".join(lines) + "\\n")
"""

LAUNCHCTL_SCRIPT = """#!{python}
import json, os, plistlib, sys, time
from pathlib import Path

state = Path(os.environ["HOST_WORLD"])
argv = sys.argv[1:]
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": "launchctl", "argv": argv}}) + "\\n")
uid = os.getuid()
domain = f"gui/{{uid}}"
if len(argv) == 2 and argv[0] in ("print", "bootout") and argv[1].startswith(domain + "/"):
    verb, label = argv[0], argv[1][len(domain) + 1:]
elif len(argv) == 3 and argv[0] == "bootstrap" and argv[1] == domain:
    verb, label = "bootstrap", None
else:
    sys.stderr.write("fake launchctl: unregistered call\\n")
    sys.exit(64)
knobs = state / "knobs.json"
knob = json.loads(knobs.read_text("utf-8")).get("launchctl", {{}}).get(verb) if knobs.exists() else None
if knob:
    time.sleep(knob["sleep"])
    sys.stdout.write(knob.get("stdout", ""))
    sys.stdout.flush()
    sys.stderr.write(knob["stderr"])
    sys.exit(knob["exit"])
store = state / "launchd.json"
table = json.loads(store.read_text("utf-8"))
jobs = table["jobs"]


def save():
    store.write_text(json.dumps(table), "utf-8")


def block(label, job):
    lines = [f"{{domain}}/{{label}} = {{{{", "\\tactive count = 1", f"\\tpath = {{job['path']}}",
             "\\ttype = LaunchAgent", f"\\tstate = {{job['state']}}", "",
             f"\\tprogram = {{job['program']}}", "\\targuments = {{",
             *[f"\\t\\t{{argument}}" for argument in job["arguments"]], "\\t}}", ""]
    if job["working_directory"]:
        lines += [f"\\tworking directory = {{job['working_directory']}}", ""]
    lines += ["\\tinherited environment = {{",
              "\\t\\tSSH_AUTH_SOCK => /var/run/com.apple.launchd.fake/Listeners", "\\t}}", "",
              "\\tdefault environment = {{", "\\t\\tPATH => /usr/bin:/bin:/usr/sbin:/sbin",
              *[f"\\t\\t{{name}} => {{value}}" for name, value in job["default_environment"].items()],
              "\\t}}", "", "\\tenvironment = {{",
              *[f"\\t\\t{{name}} => {{value}}" for name, value in job["environment"].items()],
              f"\\t\\tXPC_SERVICE_NAME => {{label}}", "\\t}}", "",
              "\\tLWCR = {{", '\\t\\t"vers" => 1', "\\t}}", "",
              f"\\tdomain = {{domain}} [100016]", f"\\truns = {{job['runs']}}"]
    if job["pid"] is not None:
        lines.append(f"\\tpid = {{job['pid']}}")
    lines += ["\\timmediate reason = speculative", "}}"]
    return "\\n".join(lines) + "\\n"


if verb == "print":
    if label not in jobs:
        sys.stderr.write(f'Bad request.\\nCould not find service "{{label}}" in domain for user gui: {{uid}}\\n')
        sys.exit(113)
    sys.stdout.write(block(label, jobs[label]))
elif verb == "bootout":
    if label not in jobs:
        sys.stderr.write("Boot-out failed: 3: No such process\\n")
        sys.exit(3)
    del jobs[label]
    save()
else:
    with open(argv[2], "rb") as handle:
        definition = plistlib.load(handle)
    if definition["Label"] in jobs:
        sys.stderr.write("Bootstrap failed: 5: Input/output error\\n")
        sys.exit(5)
    arguments = definition["ProgramArguments"]
    jobs[definition["Label"]] = {{
        "path": argv[2], "state": "running", "pid": table["next_pid"], "runs": 1,
        "program": arguments[0], "arguments": arguments,
        "working_directory": definition.get("WorkingDirectory"),
        "environment": definition.get("EnvironmentVariables", {{}}), "default_environment": {{}}}}
    table["next_pid"] += 1
    save()
"""


class HostWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name).resolve()
        self.bin, self.state = self.root / "bin", self.root / "state"
        self.home, self.checkout = self.root / "home", self.root / "checkout"
        for directory in (self.bin, self.state, self.home, self.checkout):
            directory.mkdir()
        self._script("git", GIT_SCRIPT.format(python=sys.executable, git=REAL_GIT))
        self._script("security", SECURITY_SCRIPT.format(python=sys.executable))
        self._script("codesign", CODESIGN_SCRIPT.format(
            python=sys.executable, seal_directory=SEAL_DIRECTORY, not_signed=NOT_SIGNED))
        self._script("launchctl", LAUNCHCTL_SCRIPT.format(python=sys.executable))
        (self.state / "launchd.json").write_text(json.dumps({"jobs": {}, "next_pid": 4000}), "utf-8")
        self.identities()
        self._git("init", "-q", "-b", "main")
        (self.checkout / "README").write_text("world\n", "utf-8")
        self._git("add", "README")
        self._git(*GIT_CONFIG, "commit", "-q", "-m", "initial")
        patch = mock.patch.dict(os.environ, {
            "PATH": str(self.bin), "HOME": str(self.home), "HOST_WORLD": str(self.state),
            "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})
        patch.start()
        test_case.addCleanup(patch.stop)
        previous = os.getcwd()
        os.chdir(self.checkout)
        test_case.addCleanup(os.chdir, previous)

    def _script(self, name: str, source: str) -> None:
        path = self.bin / name
        path.write_text(source, "utf-8")
        path.chmod(0o755)

    def _git(self, *argv: str) -> str:
        """The real git on the checkout, unlogged: the world's own setup and commits."""
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        return subprocess.run([REAL_GIT, "-C", str(self.checkout), *argv], check=True, env=env,
                              capture_output=True, text=True).stdout.strip()

    def environ(self, **values: str | None) -> None:
        """Set each variable inside the world's patch, or remove it for `None`."""
        for name, value in values.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def head(self) -> str:
        return self._git("rev-parse", "HEAD")

    def commit(self, message: str = "change") -> str:
        with open(self.checkout / "README", "a", encoding="utf-8") as readme:
            readme.write(f"{message}\n")
        self._git("add", "README")
        self._git(*GIT_CONFIG, "commit", "-q", "-m", message)
        return self.head()

    def dirty(self) -> None:
        with open(self.checkout / "README", "a", encoding="utf-8") as readme:
            readme.write("uncommitted\n")

    def bundle(self, relative: str = "build/Notifier.app", *, identifier: str = "dev.example.notifier",
               binary: bool = False) -> Path:
        """An untracked bundle in the checkout: a plist, an executable and a relative symlink."""
        path = self.checkout / relative
        (path / "Contents/MacOS").mkdir(parents=True, exist_ok=True)
        (path / "Contents/Resources").mkdir(parents=True, exist_ok=True)
        with open(path / "Contents/Info.plist", "wb") as handle:
            plistlib.dump({"CFBundleIdentifier": identifier, "CFBundleName": "Notifier"}, handle,
                          fmt=plistlib.FMT_BINARY if binary else plistlib.FMT_XML)
        (path / "Contents/MacOS/notifier").write_bytes(b"\x7fnotifier")
        link = path / "Contents/Resources/current"
        if not link.is_symlink():
            link.symlink_to("../MacOS/notifier")
        return path

    def installed(self, home_relative: str, *, stamp: tuple[str, str] | None,
                  identity: str | None) -> Path:
        """Copy the checkout's bundle under `$HOME`, stamp it, then sign it with `identity`."""
        source = self.checkout / "build/Notifier.app"
        if not source.exists():
            source = self.bundle()
        path = self.home / home_relative
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, path, symlinks=True)
        if stamp is not None:
            plist = path / "Contents/Info.plist"
            data = plist.read_bytes()
            fmt = plistlib.FMT_BINARY if data.startswith(b"bplist") else plistlib.FMT_XML
            info = plistlib.loads(data)
            info["AgentReleaseVersion"], info["AgentReleaseCommit"] = stamp
            with open(plist, "wb") as handle:
                plistlib.dump(info, handle, fmt=fmt)
        if identity is not None:
            subprocess.run([str(self.bin / "codesign"), "--force", "--sign", identity, str(path)],
                           check=True, capture_output=True)
        return path

    def identities(self, *pairs: tuple[str, str], exit: int = 0, stderr: str = "",
                   sleep: float = 0) -> None:
        """Replace what `security find-identity` lists, and how it exits."""
        (self.state / "identities.json").write_text(json.dumps(
            {"pairs": [list(pair) for pair in pairs], "exit": exit, "stderr": stderr,
             "sleep": sleep}), "utf-8")

    def fail(self, tool: str, verb: str, *, exit: int, stdout: str = "", stderr: str = "",
             sleep: float = 0) -> None:
        """Make one verb of `tool` sleep, write `stdout` then `stderr` and exit with `exit`.

        Only the fake `launchctl` writes a knob's `stdout`; `security` and `codesign` never print
        on stdout from a knob, so a `stdout` for them is refused rather than silently dropped.
        """
        if stdout and tool != "launchctl":
            raise ValueError(f"the fake {tool} has no knob stdout")
        knobs = self.state / "knobs.json"
        table = json.loads(knobs.read_text("utf-8")) if knobs.exists() else {}
        table.setdefault(tool, {})[verb] = {"exit": exit, "stdout": stdout, "stderr": stderr,
                                            "sleep": sleep}
        knobs.write_text(json.dumps(table), "utf-8")

    def program(self, name: str) -> str:
        """An executable no-op stub `name` in `bin/`, returning its absolute path."""
        self._script(name, "#!/bin/sh\nexit 0\n")
        return str(self.bin / name)

    def plist_path(self, label: str) -> Path:
        return self.home / "Library/LaunchAgents" / f"{label}.plist"

    def load_job(self, label: str, *, path: str, environment: dict[str, str] | None = None,
                 state: str = "running", runs: int = 1, working_directory: str | None = None,
                 default_environment: dict[str, str] | None = None) -> None:
        """Seed a loaded job; a job that is not `running` has no pid."""
        store = self.state / "launchd.json"
        table = json.loads(store.read_text("utf-8"))
        program = str(self.bin / "notifierd")
        pid = None
        if state == "running":
            pid, table["next_pid"] = table["next_pid"], table["next_pid"] + 1
        table["jobs"][label] = {
            "path": path, "state": state, "pid": pid, "runs": runs, "program": program,
            "arguments": [program, "serve", "--quiet"], "working_directory": working_directory,
            "environment": dict(environment or {}), "default_environment": dict(default_environment or {})}
        store.write_text(json.dumps(table), "utf-8")

    def job(self, label: str) -> dict | None:
        return json.loads((self.state / "launchd.json").read_text("utf-8"))["jobs"].get(label)

    def calls(self, tool: str | None = None) -> list[dict]:
        log = self.state / "calls.jsonl"
        entries = [json.loads(line) for line in log.read_text("utf-8").splitlines()] \
            if log.exists() else []
        return [entry for entry in entries if tool is None or entry["tool"] == tool]

    def tree(self) -> dict[str, str]:
        """Every path under `home`: `dir`, `-> <target>` for a symlink, else the file's SHA-256."""
        entries = {}
        for current, directories, files in os.walk(self.home):
            for name in directories + files:
                full = Path(current) / name
                relative = full.relative_to(self.home).as_posix()
                if full.is_symlink():
                    entries[relative] = f"-> {os.readlink(full)}"
                elif full.is_dir():
                    entries[relative] = "dir"
                else:
                    entries[relative] = hashlib.sha256(full.read_bytes()).hexdigest()
        return entries
