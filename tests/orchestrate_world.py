"""A hermetic world for the `orchestrate-control` suite (#403 D26).

`OrchestrateWorld(case)` builds a temporary `HOME` holding the platform manifest, the budget
policy and a host declaration, a resolvable fixture project (a committed contract, rendered
projections) and a `bin/` first on the `PATH` of `env`. `bin/` holds three shims: the source
`workflow-state` and `artifact-budget` run behind a fault rule layer, and a fake `gh`.

Every shim logs each call to `state/calls.jsonl` (tool, argv, stdin, the call's ordinal among
its tool and subcommand, and whether a name in `TOKENS` was visible) and consults
`state/faults.json` before it answers; a rule matches by tool, subcommand and optional call
ordinal, request issue, request kind or an argv member, then replaces the real answer with its
`stdout`, `stderr` and `exit`, or echoes the request (`passthrough`). The fake `gh` exits 65
when any name in `TOKENS` (the contract's bound `unset_before_invocation` list) is visible to
it, answers `issue list` from `state/gh.json` listings and exits 64 for any call it does not
know. `env` exports every name in `TOKENS`, so a command that does not remove the bound names
fails loudly. Nothing contacts a network remote.
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "home/common/agent-skills"
WORKFLOW = SKILLS / "scripts/workflow-state.py"
BUDGET = SKILLS / "scripts/artifact_budget.py"
POLICY = SKILLS / "artifact-budget-policy.json"
MANIFEST = SKILLS / "platform-manifest.json"
COMMAND = [sys.executable, "-m", "agent_tools.orchestrate_control"]
INVALID = "orchestrate-control: invalid invocation\n"
SLUG = "fagenorn/nix-config"
# The third name is one no implementation would know, so only honouring the contract's bound
# `unset_before_invocation` list keeps it out of a tracker child (D30).
TOKENS = ("GITHUB_TOKEN", "GH_TOKEN", "ORCH_TEST_SENTINEL")

PRELUDE = '''#!{python}
import json, os, subprocess, sys
from pathlib import Path

state = Path({state!r})
tool = {tool!r}
script = {script!r}
argv = sys.argv[1:]
stdin = sys.stdin.buffer.read()
sub = argv[0] if argv else ""
log = state / "calls.jsonl"
earlier = [json.loads(line) for line in log.read_text("utf-8").splitlines()]
ordinal = 1 + sum(1 for c in earlier if c["tool"] == tool and c["argv"][:1] == [sub])
try:
    sent = json.loads(stdin) if stdin else None
except ValueError:
    sent = None
token = any(name in os.environ for name in {tokens!r})
with log.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps({{"tool": tool, "argv": argv, "stdin": stdin.decode("utf-8", "replace"),
                              "call": ordinal, "token_visible": token}}) + "\\n")

def field(name):
    return sent.get(name) if isinstance(sent, dict) else None

def matches(rule):
    return (rule["tool"] == tool and rule["sub"] == sub
            and rule.get("call", ordinal) == ordinal
            and ("issue" not in rule or rule["issue"] == field("issue"))
            and ("stdin_kind" not in rule or rule["stdin_kind"] == field("kind"))
            and ("argv_has" not in rule or rule["argv_has"] in argv))

rule = next((r for r in json.loads((state / "faults.json").read_text("utf-8")) if matches(r)), None)
if rule is not None and rule.get("passthrough"):
    sys.stdout.write(json.dumps(sent, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\\n")
    sys.exit(0)
if rule is not None:
    sys.stdout.write(rule["stdout"])
    sys.stderr.write(rule["stderr"])
    sys.exit(rule["exit"])
'''

REAL_TAIL = '''done = subprocess.run([sys.executable, script, *argv], input=stdin, capture_output=True)
sys.stdout.buffer.write(done.stdout)
sys.stderr.buffer.write(done.stderr)
sys.exit(done.returncode)
'''

GH_TAIL = '''if token:
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
world = json.loads((state / "gh.json").read_text("utf-8"))
if argv[:2] == ["issue", "list"]:
    flag = next(a for a in argv if a in ("--label", "--milestone"))
    key = flag + "=" + argv[argv.index(flag) + 1]
    if key in world["listings"]:
        sys.stdout.write(json.dumps([{"number": n} for n in world["listings"][key]]))
        sys.exit(0)
sys.stderr.write("fake gh: unregistered call\\n")
sys.exit(64)
'''


class OrchestrateWorld:
    def __init__(self, case: unittest.TestCase, *, mutate=None,
                 claude_code: str = "supported") -> None:
        self.case = case
        tmp = tempfile.TemporaryDirectory()
        case.addCleanup(tmp.cleanup)
        tmp_root = Path(tmp.name).resolve()
        self.home, self.bin, self.state, self.cwd, self.root = (
            tmp_root / name for name in ("home", "bin", "state", "cwd", "project"))
        share = self.home / ".agents/share"
        for directory in (share, self.bin, self.state, self.cwd, self.root):
            directory.mkdir(parents=True)
        (share / "platform-manifest.json").write_bytes(MANIFEST.read_bytes())
        (share / "artifact-budget-policy.json").symlink_to(POLICY)
        route = {"support": claude_code}
        if claude_code == "supported":
            route["agent_slots"] = 64
        (share / "host-declaration.json").write_text(json.dumps(
            {"schema_version": 1,
             "routes": {"claude-code": route, "codex": {"support": "unsupported"}}}), "utf-8")
        (self.state / "calls.jsonl").write_text("", "utf-8")
        self.clear_faults()
        self._write_gh({"listings": {}, "issues": {}, "missing": [], "pulls": [],
                        "forge_truncated": False})
        for tool, script, tail in (("workflow-state", WORKFLOW, REAL_TAIL),
                                   ("artifact-budget", BUDGET, REAL_TAIL),
                                   ("gh", None, GH_TAIL)):
            shim = self.bin / tool
            shim.write_text(PRELUDE.format(python=sys.executable, state=str(self.state),
                                           tool=tool, script=str(script) if script else None,
                                           tokens=TOKENS) + tail, "utf-8")
            shim.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(ROOT / "python"), "PYTHONDONTWRITEBYTECODE": "1",
                    "GITHUB_TOKEN": "harness-token", "GH_TOKEN": "harness-token",
                    "ORCH_TEST_SENTINEL": "harness-token",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        self._commit_project(mutate)

    def _commit_project(self, mutate) -> None:
        contract = json.loads((ROOT / ".agents/project.json").read_text("utf-8"))
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = list(TOKENS)
        if mutate is not None:
            mutate(contract)
        self.git("init", "--quiet", "-b", "main")
        self.git("config", "commit.gpgsign", "false")
        (self.root / ".agents/instructions").mkdir(parents=True)
        (self.root / ".agents/project.json").write_text(json.dumps(contract, indent=2) + "\n",
                                                        "utf-8")
        (self.root / ".agents/instructions/bootstrap.md").write_text("# invariants\n", "utf-8")
        paths = contract["bindings"]["paths"]
        for name in ("standards", "rejections"):
            for relative in paths[name]:
                (self.root / relative).mkdir(parents=True, exist_ok=True)
                (self.root / relative / "keep.md").write_text("# keep\n", "utf-8")
        for relative in paths["architecture"]:
            if not (self.root / relative).exists():
                (self.root / relative).parent.mkdir(parents=True, exist_ok=True)
                (self.root / relative).write_text("# architecture\n", "utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.resolve_project", "write-projections",
             "--repo-root", str(self.root)],
            capture_output=True, text=True, timeout=120, env=self.env)
        if done.returncode != 0:
            raise AssertionError(f"fixture projections could not be rendered: {done.stdout}")
        self.git("add", "-A")
        self.git("commit", "--quiet", "-m", "fixture")

    def _write_gh(self, world: dict) -> None:
        (self.state / "gh.json").write_text(json.dumps(world), "utf-8")

    def run(self, *argv, stdin=None, cwd=None) -> subprocess.CompletedProcess:
        return subprocess.run(COMMAND + [str(a) for a in argv], input=stdin, text=True,
                              capture_output=True, cwd=cwd or self.cwd, env=self.env,
                              timeout=300)

    def start(self, *argv) -> dict:
        done = self.run("start", "--repo-root", self.root, *argv)
        self.case.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        return json.loads(done.stdout)

    def fault(self, tool: str, sub: str, **rule) -> None:
        if not rule.get("passthrough"):
            rule = {"exit": 0, "stdout": "", "stderr": "", **rule}
        faults = json.loads((self.state / "faults.json").read_text("utf-8"))
        faults.append({"tool": tool, "sub": sub, **rule})
        (self.state / "faults.json").write_text(json.dumps(faults), "utf-8")

    def clear_faults(self) -> None:
        (self.state / "faults.json").write_text("[]", "utf-8")

    def listing(self, flag: str, value: str, numbers) -> None:
        world = json.loads((self.state / "gh.json").read_text("utf-8"))
        world["listings"][f"{flag}={value}"] = list(numbers)
        self._write_gh(world)

    def calls(self, tool: str | None = None, sub: str | None = None) -> list[dict]:
        entries = [json.loads(line) for line in
                   (self.state / "calls.jsonl").read_text("utf-8").splitlines()]
        return [c for c in entries if (tool is None or c["tool"] == tool)
                and (sub is None or c["argv"][:1] == [sub])]

    def ws(self, *argv, stdin=None) -> subprocess.CompletedProcess:
        return subprocess.run([sys.executable, str(WORKFLOW), *[str(a) for a in argv]],
                              input=stdin, capture_output=True, env=self.env, timeout=300)

    def git(self, *args) -> str:
        return subprocess.run(["git", "-C", str(self.root), *args], capture_output=True,
                              text=True, check=True, env=self.env).stdout
