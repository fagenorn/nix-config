"""A hermetic world for the bypass proof (#1152): a throwaway repository, a fake `gh`, a fake `claude`.

`BypassProofWorld(test_case)` builds a temporary directory holding a `HOME` with the platform
manifest, a push fixture whose `main` carries a scaffolded contract with production rules, a
pushed pull-request branch, the guard's base and compiled policies, a fake `gh` (first on `PATH`
and the base policy's `gh_bin`) and a fake `claude`. The fake `claude` runs the real guard
source as its PreToolUse hook, so a refusal is the guard's own text. No test support here is a
`TestCase`.

The fake `gh` answers exactly the argv shapes the proof and the guard use and exits 1 with
`fake gh: unsupported` on every other call; its state file's absolute path is written into its own
text, because the guard runs `gh` children without the caller's environment.

The fake `claude` parses argv by the CLI's grammar (a variadic `--mcp-config`; an argument
after it is a second config and the run fails with no init event), records its argv and the settings document it was given, reads the prompt's
last line (`Tool call: <json>`), emits stream-json (init, `tool_use`, `tool_result`) and runs the
call unless the guard or a mode denies it. Modes are `FAKE_CLAUDE_*` variables of the run's
environment: `SKIP_GUARD`, `MODE=auto`, `NO_CALL`, `PLAIN_DENY`, `DENY_ROUTE`, `RUN_AND_REFUSE`,
`HANG`. `RUN_AND_REFUSE` runs the call without the guard, then reports a refusal.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import bypass_proof
from agent_tools.guard.push_fixture import make_push_fixture

from .guard_policy_world import MANIFEST, REAL_GIT, REPO_ROOT
from .pre_push_world import FAKE_DERIVE, GUARD_SOURCE

JQ = shutil.which("jq")
SLUG = "fagenorn/bypass-proof-fixture"
PROJECT_ID = "bypass-proof/fixture"
PR = 7
PR_BRANCH = "bypass-proof-pr"
TEMPLATE = REPO_ROOT / ".agents/project.json"

PR_FIELDS = "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup"
PROOF_FIELDS = "state,headRefOid"
LOOK_FIELDS = "title,body,closingIssuesReferences"
PLAN_GATED = ('{"message": "Upgrade to GitHub Pro or make this repository public to enable this '
              'feature.", "status": "403"}')

FAKE_GH = """#!{python}
import json
import sys

STATE = {state!r}
SLUG = {slug!r}
PR = {pr!r}
FIELD_LISTS = {fields!r}
PLAN_GATED = {gated!r}

argv = sys.argv[1:]
with open(STATE, encoding="utf-8") as handle:
    state = json.load(handle)


def save():
    with open(STATE, "w", encoding="utf-8") as handle:
        json.dump(state, handle)


def fail(message, code=1):
    sys.stderr.write(message + "\\n")
    sys.exit(code)


if len(argv) == 7 and argv[:2] == ["pr", "view"] and argv[3] == "--repo" and argv[4] == SLUG \\
        and argv[5] == "--json" and argv[6] in FIELD_LISTS and argv[2] in state["prs"]:
    if argv[6] == FIELD_LISTS[1] and state["guard_lookup_fails"]:
        fail("fake gh: lookup down")
    pr = state["prs"][argv[2]]
    print(json.dumps({{name: pr[name] for name in argv[6].split(",")}}))
elif argv == ["api", "--paginate", "--slurp",
              "repos/" + SLUG + "/pulls/" + str(PR) + "/commits?per_page=100"]:
    print(json.dumps([[{{"sha": state["prs"][str(PR)]["headRefOid"],
                         "commit": {{"message": "bypass proof pr"}}}}]]))
elif argv == ["api", "repos/" + SLUG + "/branches/main/protection"]:
    print(PLAN_GATED)
    sys.exit(1)
elif len(argv) >= 5 and argv[:2] == ["pr", "merge"] and argv[2] in state["prs"] \\
        and argv[3:5] == ["--repo", SLUG]:
    state["prs"][argv[2]]["state"] = "MERGED"
    save()
elif len(argv) >= 5 and argv[:2] == ["release", "create"] and argv[3:5] == ["--repo", SLUG]:
    state["releases"].append(argv[2])
    save()
elif len(argv) == 7 and argv[:2] == ["release", "view"] and argv[3:5] == ["--repo", SLUG] \\
        and argv[5:] == ["--json", "tagName"]:
    if argv[2] not in state["releases"]:
        fail("release not found")
    print(json.dumps({{"tagName": argv[2]}}))
else:
    fail("fake gh: unsupported")
"""

FAKE_CLAUDE = """#!{python}
import json
import os
import subprocess
import sys

LOG = os.environ["FAKE_CLAUDE_LOG"]
PREFIX = "Tool call: "
argv = sys.argv[1:]


def append(name, text):
    with open(os.path.join(LOG, name), "a", encoding="utf-8") as handle:
        handle.write(text + "\\n")


def emit(event):
    print(json.dumps(event), flush=True)


append("argv.log", json.dumps(sys.argv))
settings_path = argv[argv.index("--settings") + 1]
with open(settings_path, encoding="utf-8") as handle:
    settings = json.load(handle)
append("settings.log", json.dumps(settings))
# The CLI's own option grammar: `--mcp-config` is variadic and takes every argument after it up
# to the next flag, so a prompt placed there is read as a second configuration and the run fails.
VALUE_FLAGS = ("--settings", "--output-format")
BOOLEAN_FLAGS = ("-p", "--verbose", "--strict-mcp-config")
configs, positional, index = [], [], 0
while index < len(argv):
    item = argv[index]
    if item in VALUE_FLAGS:
        index += 2
    elif item == "--mcp-config":
        index += 1
        while index < len(argv) and not argv[index].startswith("-"):
            configs.append(argv[index])
            index += 1
    elif item in BOOLEAN_FLAGS:
        index += 1
    else:
        positional.append(item)
        index += 1
if len(configs) != 1 or len(positional) != 1:
    sys.stderr.write("error: invalid MCP configuration or no prompt\\n")
    sys.exit(1)
PROMPT = positional[0]
with open(configs[0], encoding="utf-8") as handle:
    append("mcp.log", json.dumps(json.load(handle)))
if os.environ.get("FAKE_CLAUDE_HANG"):
    grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
    append("grandchildren", str(grandchild.pid))
    import time
    time.sleep(600)
    sys.exit(0)
mode = "auto" if os.environ.get("FAKE_CLAUDE_MODE") == "auto" else settings["permissions"]["defaultMode"]
emit({{"type": "system", "subtype": "init", "permissionMode": mode}})
if os.environ.get("FAKE_CLAUDE_NO_CALL"):
    sys.exit(0)
call = json.loads(PROMPT.splitlines()[-1][len(PREFIX):])
tool, tool_input = call["tool"], call["input"]
emit({{"type": "assistant", "message": {{"content": [
    {{"type": "tool_use", "id": "t1", "name": tool, "input": tool_input}}]}}}})


def result(text, is_error):
    emit({{"type": "user", "message": {{"content": [
        {{"type": "tool_result", "tool_use_id": "t1", "is_error": is_error, "content": text}}]}}}})
    sys.exit(0)


if os.environ.get("FAKE_CLAUDE_PLAIN_DENY"):
    result("denied", True)
if not (os.environ.get("FAKE_CLAUDE_SKIP_GUARD") or os.environ.get("FAKE_CLAUDE_RUN_AND_REFUSE")):
    payload = {{"tool_name": tool, "tool_input": tool_input, "cwd": os.getcwd()}}
    done = subprocess.run(json.loads(os.environ["FAKE_CLAUDE_GUARD"]), input=json.dumps(payload),
                          capture_output=True, text=True)
    if done.returncode != 0:
        result(done.stderr.strip(), True)
if os.environ.get("FAKE_CLAUDE_DENY_ROUTE") and tool == "Bash" \\
        and tool_input["command"].strip() == "./scripts/proof-read":
    result("lifecycle guard: denied by the fake", True)
env = {{**os.environ, **settings["env"]}}
text, failed = "", False
if tool == "Bash":
    ran = subprocess.run(["/bin/sh", "-c", tool_input["command"]], cwd=os.getcwd(), env=env,
                         capture_output=True, text=True)
    text, failed = ran.stdout + ran.stderr, ran.returncode != 0
elif tool == "Write":
    os.makedirs(os.path.dirname(tool_input["file_path"]), exist_ok=True)
    with open(tool_input["file_path"], "w", encoding="utf-8") as handle:
        handle.write(tool_input["content"])
    text = "written"
else:
    marks = env["BYPASS_PROOF_MARKS"]
    os.makedirs(marks, exist_ok=True)
    open(os.path.join(marks, tool), "w").close()
    text = "the production MCP tool ran"
if os.environ.get("FAKE_CLAUDE_RUN_AND_REFUSE"):
    result("lifecycle guard: refused", True)
result(text, failed)
"""


class BypassProofWorld:
    def __init__(self, test_case: unittest.TestCase) -> None:
        if JQ is None:
            raise AssertionError("jq is not on PATH; the bypass proof world needs it")
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.home = self.tmp / "home"
        (self.home / ".agents/share").mkdir(parents=True)
        shutil.copy(MANIFEST, self.home / ".agents/share/platform-manifest.json")
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.log = self.tmp / "claude-log"
        self.log.mkdir()
        hooks = self.tmp / "no-hooks"
        hooks.mkdir()
        self.fixture = make_push_fixture(self.tmp / "repo", SLUG, git_bin=REAL_GIT,
                                         env=os.environ, hooks_path=hooks)
        self.work = self.fixture.work
        self.env = {**self.fixture.env, "HOME": str(self.home),
                    "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
                    "PYTHONPATH": str(REPO_ROOT / "python"), "FAKE_CLAUDE_LOG": str(self.log)}
        self.env.pop("CLAUDECODE", None)
        self.scaffold_checkout()
        self.fixture.git("add", "-A")
        self.fixture.commit("scaffold")
        self.git("push", "-q", "origin", "main")
        self.git("checkout", "-q", "-b", PR_BRANCH)
        self.pr_head = self.fixture.commit("bypass proof pr")
        self.git("push", "-q", "origin", PR_BRANCH)
        self.git("checkout", "-q", "main")
        self.start_head = self.git("rev-parse", "HEAD").strip()
        self.state_file = self.tmp / "gh-state.json"
        self.state = {"prs": {str(PR): {
            "state": "OPEN", "baseRefName": "main", "headRefName": PR_BRANCH,
            "headRefOid": self.pr_head, "mergeStateStatus": "UNSTABLE",
            "url": f"https://github.com/{SLUG}/pull/{PR}",
            "statusCheckRollup": [{"__typename": "StatusContext",
                                   "context": bypass_proof.REQUIRED_CHECK, "state": "FAILURE"}],
            "title": "bypass proof", "body": "A pull request whose required check fails on purpose.",
            "closingIssuesReferences": []}}, "releases": [], "guard_lookup_fails": False}
        self.save_state()
        gh = self.bin / "gh"
        gh.write_text(FAKE_GH.format(python=sys.executable, state=str(self.state_file), slug=SLUG, pr=PR,
                                     fields=[PROOF_FIELDS, PR_FIELDS, LOOK_FIELDS],
                                     gated=PLAN_GATED), encoding="utf-8")
        gh.chmod(0o755)
        self.claude = self.tmp / "fake-claude"
        self.claude.write_text(FAKE_CLAUDE.format(python=sys.executable), encoding="utf-8")
        self.claude.chmod(0o755)
        self.write_guard_policies()

    def git(self, *args: str) -> str:
        done = self.fixture.git(*args)
        if done.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
        return done.stdout

    def scaffold_checkout(self) -> None:
        with mock.patch.dict(os.environ, {"HOME": str(self.home)}):
            bypass_proof.scaffold(self.work, TEMPLATE, SLUG, PROJECT_ID)

    def write_guard_policies(self) -> None:
        template = json.loads(TEMPLATE.read_text(encoding="utf-8"))
        profile = next(iter(template["release"]["profiles"]))
        row = {"default_branch": "main", "integration_branch": "main",
               "required_checks": [bypass_proof.REQUIRED_CHECK],
               "evidence": {"project_id": PROJECT_ID},
               "production": {
                   "changes": [{"id": bypass_proof.CHANGE_ID, "argv": ["./scripts/proof-change"]}],
                   "read_only": [{"id": bypass_proof.READ_ID, "argv": ["./scripts/proof-read"]}],
                   "release_profile": profile, "key_files": [bypass_proof.KEY_FILE_GLOB],
                   "mcp_tools": [bypass_proof.MCP_TOOL]}}
        base = self.tmp / "base-policy.json"
        base.write_text(json.dumps({
            "authorized_owners": ["fagenorn"], "integration_bases": {}, "git_bin": REAL_GIT,
            "gh_bin": str(self.bin / "gh"), "jq_bin": JQ}), encoding="utf-8")
        policy = self.tmp / "policy.json"
        policy.write_text(json.dumps({"derived_repositories": {SLUG: row}, "derivation": None}),
                          encoding="utf-8")
        derive = self.tmp / "fake-derive"
        derive.write_text(FAKE_DERIVE.format(python=sys.executable, rows=json.dumps({SLUG: row})),
                          encoding="utf-8")
        derive.chmod(0o755)
        self.env["FAKE_CLAUDE_GUARD"] = json.dumps([
            sys.executable, "-I", str(GUARD_SOURCE), "--base-policy", str(base),
            "--policy", str(policy), "--derive-bin", str(derive)])

    def save_state(self) -> None:
        self.state_file.write_text(json.dumps(self.state), encoding="utf-8")

    def load_state(self) -> dict:
        return json.loads(self.state_file.read_text(encoding="utf-8"))

    def fail_guard_pr_lookup(self) -> None:
        self.state["guard_lookup_fails"] = True
        self.save_state()

    def set_pr_state(self, value: str) -> None:
        self.state["prs"][str(PR)]["state"] = value
        self.save_state()

    def add_release(self, tag: str) -> None:
        self.state["releases"].append(tag)
        self.save_state()

    def remote_tip(self, branch: str = "main") -> str | None:
        return self.fixture.remote_ref(SLUG, f"refs/heads/{branch}")

    def head(self) -> str:
        return self.git("rev-parse", "HEAD").strip()

    def commit_and_push(self, message: str) -> None:
        """Commit every change in the checkout and push it to `main`; the new tip is the start."""
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)
        self.git("push", "-q", "origin", "main")
        self.start_head = self.head()

    def rewrite_contract(self, mutate) -> None:
        """Rewrite the contract through `mutate`, render its projections, commit and push."""
        path = self.work / ".agents/project.json"
        contract = json.loads(path.read_text(encoding="utf-8"))
        mutate(contract)
        path.write_text(json.dumps(contract, indent=2) + "\n", encoding="utf-8")
        done = subprocess.run(
            bypass_proof.sibling_argv("project_contract.resolve_project")
            + ["write-projections", "--repo-root", str(self.work)],
            capture_output=True, text=True, timeout=120, env=self.env)
        if done.returncode != 0:
            raise AssertionError(f"projections could not be rendered: {done.stdout}{done.stderr}")
        self.commit_and_push("contract")

    def argv_log(self) -> list[list[str]]:
        path = self.log / "argv.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def settings_log(self) -> list[dict]:
        path = self.log / "settings.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def mcp_log(self) -> list[dict]:
        path = self.log / "mcp.log"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def grandchildren(self) -> list[int]:
        path = self.log / "grandchildren"
        if not path.exists():
            return []
        return [int(line) for line in path.read_text(encoding="utf-8").split()]

    def run(self, *args: str, env: dict[str, str] | None = None):
        """Run the proof against the checkout; `(exit code, report or None, stderr)`."""
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.console.bypass_proof", "run",
             "--checkout", str(self.work), "--pr", str(PR), "--claude", str(self.claude), *args],
            cwd=self.tmp, env={**self.env, **(env or {})}, capture_output=True, text=True,
            timeout=180)
        report = json.loads(done.stdout) if done.stdout.strip() else None
        return done.returncode, report, done.stderr
