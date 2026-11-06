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

`add_origin()`, which only the gathering tests call, gives the project a local bare `origin`
cloned from it, a `publisher` clone that advances it, and a fourth shim, `git`, that logs each
`git fetch` call's argv as tool `git` and runs the real Git (issue 546 D11).
"""
import json
import os
import shutil
import stat
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
ROUTE = "claude-code"
# The third name is one no implementation would know, so only honouring the contract's bound
# `unset_before_invocation` list keeps it out of a tracker child (D30).
TOKENS = ("GITHUB_TOKEN", "GH_TOKEN", "ORCH_TEST_SENTINEL")
# The committed unmutated fixture project per concrete test class (issue 500 D5, D9).
_TEMPLATES: dict[type, Path] = {}

PRELUDE = '''#!{python}
import json, os, re, subprocess, sys
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

# The real script runs in this process, as `python script argv` would run it, so a tool
# call costs one interpreter start (issue 612): the consumed stdin is handed back as
# `sys.stdin`, and the script's own exit and output are the shim's.
REAL_TAIL = '''import io, runpy
sys.argv = [script, *argv]
sys.path[0] = os.path.dirname(script)
sys.stdin = io.TextIOWrapper(io.BytesIO(stdin), encoding="utf-8")
runpy.run_path(script, run_name="__main__")
'''

GIT_SHIM = '''#!{python}
import json, os, sys
argv = sys.argv[1:]
words = argv
while words[:1] == ["-C"]:
    words = words[2:]
if words[:1] == ["fetch"]:
    with open({log!r}, "a", encoding="utf-8") as handle:
        handle.write(json.dumps({{"tool": "git", "argv": argv, "stdin": "", "call": 0,
                                  "token_visible": False}}) + "\\n")
os.execv({git!r}, [{git!r}, *argv])
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
if argv[:2] == ["api", "graphql"]:
    query = next(a for a in argv if a.startswith("query="))
    if "--paginate" in argv:
        pulls = sorted(world["pulls"], key=lambda pull: pull["number"])
        pages = [pulls[i:i + 2] for i in range(0, len(pulls), 2)] or [[]]
        sys.stdout.write(json.dumps([
            {"data": {"repository": {"pullRequests": {
                "pageInfo": {"hasNextPage": i < len(pages) - 1 or world["forge_truncated"],
                             "endCursor": f"c{i}"},
                "nodes": page}}}} for i, page in enumerate(pages)]))
        sys.exit(0)
    fallback = {"typename": "Issue", "state": "OPEN", "blocked_by": [], "truncated": False}
    aliases = {}
    for alias, number in re.findall(r"(i\\d+): issueOrPullRequest\\(number: (\\d+)\\)", query):
        spec = world["issues"].get(number, fallback)
        if int(number) in world["missing"]:
            aliases[alias] = None
            continue
        node = {"__typename": spec["typename"], "number": int(number)}
        if spec["typename"] == "Issue":
            node["state"] = spec["state"]
            node["blockedBy"] = {"pageInfo": {"hasNextPage": spec["truncated"]},
                                 "nodes": spec["blocked_by"]}
        aliases[alias] = node
    sys.stdout.write(json.dumps({"data": {"repository": aliases}}))
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
                    "PYTHONPATH": str(ROOT / "python"),
                    "GITHUB_TOKEN": "harness-token", "GH_TOKEN": "harness-token",
                    "ORCH_TEST_SENTINEL": "harness-token",
                    "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
                    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid",
                    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        if mutate is None:
            shutil.copytree(self._template(), self.root, symlinks=True, dirs_exist_ok=True)
        else:
            self._commit_project(self.root, mutate)

    def _template(self) -> Path:
        """The test class's unmutated committed project, built by its first world (issue 500 D5).

        The class cleanup that removes the directory and the cache entry is registered
        before the build, so a failed build leaves nothing behind and caches nothing.
        """
        owner = type(self.case)
        template = _TEMPLATES.get(owner)
        if template is None:
            tmp = tempfile.TemporaryDirectory()
            owner.addClassCleanup(tmp.cleanup)
            owner.addClassCleanup(_TEMPLATES.pop, owner, None)
            template = Path(tmp.name).resolve() / "project"
            template.mkdir()
            self._commit_project(template, None)
            _TEMPLATES[owner] = template
        return template

    def _commit_project(self, root: Path, mutate) -> None:
        contract = json.loads((ROOT / ".agents/project.json").read_text("utf-8"))
        contract["bindings"]["tracker"]["credential_env"]["unset_before_invocation"] = list(TOKENS)
        if mutate is not None:
            mutate(contract)
        self._git_in(root, "init", "--quiet", "-b", "main")
        self._git_in(root, "config", "commit.gpgsign", "false")
        (root / ".agents/instructions").mkdir(parents=True)
        (root / ".agents/project.json").write_text(json.dumps(contract, indent=2) + "\n",
                                                   "utf-8")
        (root / ".agents/instructions/bootstrap.md").write_text("# invariants\n", "utf-8")
        paths = contract["bindings"]["paths"]
        for name in ("standards", "rejections"):
            for relative in paths[name]:
                (root / relative).mkdir(parents=True, exist_ok=True)
                (root / relative / "keep.md").write_text("# keep\n", "utf-8")
        for relative in paths["architecture"]:
            if not (root / relative).exists():
                (root / relative).parent.mkdir(parents=True, exist_ok=True)
                (root / relative).write_text("# architecture\n", "utf-8")
        done = subprocess.run(
            [sys.executable, "-m", "agent_tools.resolve_project", "write-projections",
             "--repo-root", str(root)],
            capture_output=True, text=True, timeout=120, env=self.env)
        if done.returncode != 0:
            raise AssertionError(f"fixture projections could not be rendered: {done.stdout}")
        self._git_in(root, "add", "-A")
        self._git_in(root, "commit", "--quiet", "-m", "fixture")

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

    def validate(self, value: dict) -> subprocess.CompletedProcess:
        """The source `artifact-budget` validating `value` at the workflow-response boundary,
        unlogged and without the fault rules."""
        return subprocess.run(
            [sys.executable, str(BUDGET), "validate-report", "--boundary", "workflow-response",
             "--input", "-"], input=json.dumps(value).encode(), capture_output=True,
            env=self.env, timeout=120)

    def git(self, *args) -> str:
        return self._git_in(self.root, *args)

    def _git_in(self, root: Path, *args) -> str:
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              text=True, check=True, env=self.env).stdout

    def _gh_world(self, change) -> None:
        world = json.loads((self.state / "gh.json").read_text("utf-8"))
        change(world)
        self._write_gh(world)

    def issue(self, number, *, state="OPEN", blocked_by=(), typename="Issue",
              truncated=False) -> None:
        self._gh_world(lambda world: world["issues"].__setitem__(str(number), {
            "typename": typename, "state": state, "blocked_by": list(blocked_by),
            "truncated": truncated}))

    @staticmethod
    def blocker(number, *, state="OPEN", labels=(), repo=SLUG, labels_truncated=False) -> dict:
        return {"number": number, "state": state,
                "url": f"https://github.com/{repo}/issues/{number}",
                "repository": {"nameWithOwner": repo},
                "labels": {"pageInfo": {"hasNextPage": labels_truncated},
                           "nodes": [{"name": label} for label in labels]}}

    def missing(self, number) -> None:
        self._gh_world(lambda world: world["missing"].append(number))

    def truncate_forge(self) -> None:
        self._gh_world(lambda world: world.__setitem__("forge_truncated", True))

    def pull(self, number, head, *, state="OPEN", cross=False, merge_oid=None) -> None:
        self._gh_world(lambda world: world["pulls"].append({
            "number": number, "headRefName": head, "isCrossRepository": cross, "state": state,
            "url": f"https://github.com/{SLUG}/pull/{number}",
            "mergeCommit": {"oid": merge_oid} if merge_oid else None}))

    def candidate(self, issue, suffix="") -> str:
        return str(self.root / ".worktrees" / f"worktree-issue-{issue}-orchestrated{suffix}")

    def add_worktree(self, path, branch) -> None:
        self.git("worktree", "add", "--quiet", "-b", branch, str(path))

    def step(self, session, *, first_sweep=False, owners=(), contracts_due=(),
             refused_contracts=(), repo_root=None) -> tuple[subprocess.CompletedProcess, dict | None]:
        stdin = json.dumps({"session": session, "first_sweep": first_sweep,
                            "owners": list(owners), "contracts_due": list(contracts_due),
                            "refused_contracts": list(refused_contracts)})
        done = self.run("step", "--repo-root", repo_root or self.root, "--input", "-",
                        stdin=stdin)
        return done, json.loads(done.stdout) if done.stdout else None

    def snapshot(self, path) -> list[tuple[str, str, int | None]]:
        """Every entry under `path` as (relative path, "d" | "f" | "l", mtime in ns for a regular
        file), links not followed and the top-level `.superpowers` directory left out."""
        base, entries = Path(path), []
        for here, dirs, files in os.walk(base):
            if here == str(base) and ".superpowers" in dirs:
                dirs.remove(".superpowers")
            for name in (*dirs, *files):
                full = Path(here, name)
                mode = full.lstat().st_mode
                kind = "l" if stat.S_ISLNK(mode) else "d" if stat.S_ISDIR(mode) else "f"
                entries.append((str(full.relative_to(base)), kind,
                                full.lstat().st_mtime_ns if kind == "f" else None))
        return sorted(entries)

    def add_origin(self) -> None:
        """A bare `origin` cloned from the project, a `publisher` clone and the `git` shim."""
        real = shutil.which("git", path=os.environ["PATH"])
        self.origin = self.root.parent / "origin.git"
        self.publisher = self.root.parent / "publisher"
        self._git_in(self.root.parent, "clone", "--quiet", "--bare", str(self.root),
                     str(self.origin))
        self.git("remote", "add", "origin", str(self.origin))
        self._git_in(self.root.parent, "clone", "--quiet", str(self.origin), str(self.publisher))
        self._git_in(self.publisher, "config", "commit.gpgsign", "false")
        shim = self.bin / "git"
        shim.write_text(GIT_SHIM.format(python=sys.executable, git=real,
                                        log=str(self.state / "calls.jsonl")), "utf-8")
        shim.chmod(0o755)

    def publish(self, files: dict[str, str]) -> None:
        """One commit on `origin`'s main from the publisher, writing `files`."""
        for name, text in files.items():
            (self.publisher / name).write_text(text, "utf-8")
        self._git_in(self.publisher, "add", "-A")
        self._git_in(self.publisher, "commit", "--quiet", "-m", "publish")
        self._git_in(self.publisher, "push", "--quiet", "origin", "HEAD:main")

    def entry(self, path: str) -> dict:
        """The `{path, mode, object}` entry `origin`'s main holds at `path`, read with Git
        independently of the command; `mode` and `object` are None when it holds nothing."""
        listed = self._git_in(self.origin, "ls-tree", "--full-tree", "main", "--", path).strip()
        if not listed:
            return {"path": path, "mode": None, "object": None}
        mode, _, rest = listed.partition(" ")
        return {"path": path, "mode": mode, "object": rest.split("\t")[0].split(" ")[1]}

    def failure(self, path: str) -> dict:
        """A `verification-failure` of the project's `nix-build` whose one fact selects `path`
        as `origin` holds it now."""
        contract = json.loads((self.root / ".agents/project.json").read_text("utf-8"))
        return {"kind": "verification-failure", "schema_version": 1,
                "repository": {"project_id": contract["project"]["id"],
                               "integration_branch":
                                   contract["bindings"]["vcs"]["integration_branch"]},
                "command": {"id": "nix-build", "argv": ["just", "build"], "cwd": ".",
                            "env": []},
                "failure_class": "dependency",
                "facts": [{"name": "pinned", "source": {"paths": [path]},
                           "value": {"objects": [self.entry(path)]}}]}

    def park(self, session: dict, action_id: str, failure: dict) -> None:
        """Suspend `action_id` on `failure` through the source `workflow-state`, unlogged."""
        done = self.ws("suspend", "--repo-root", self.root, "--run-id", session["run_id"],
                       "--action-id", action_id, "--blocked-on", "verification",
                       "--verification-input", "-", stdin=json.dumps(failure).encode())
        self.case.assertEqual(done.returncode, 0, done.stdout + done.stderr)

    def requests(self) -> list[dict]:
        return [json.loads(call["stdin"]) for call in self.calls("workflow-state", "control")]

    def seed_spawn(self, session, issues, *, paths=None) -> dict[int, dict]:
        """Act as the adapter through the source `workflow-state`, unlogged: build the delivery
        pair of each issue in `issues`, then run one control round that spawns them."""
        paths = {n: self.candidate(n) for n in session["issues"]} if paths is None else paths
        pairs = {}
        for number in issues:
            built = self.ws("build-delivery", "--repo-root", self.root, "--kind", "contract",
                            "--input", "-", stdin=json.dumps({
                                "issue": number, "worktree": paths[number],
                                "source_kind": session["source"]["kind"],
                                "source_reference": session["source"]["reference"]}).encode())
            self.case.assertEqual(built.returncode, 0, built.stdout + built.stderr)
            pairs[number] = json.loads(built.stdout)
        every = session["issues"]
        keyed = lambda value: {str(n): value(n) for n in every}
        request = {
            "interface_version": 4, "host_route": ROUTE, "max_parallel": len(every),
            "attempt_budget_minutes": 240, "human_directed": session["human_directed"],
            "issues": every,
            "tracker": [{"issue": n, "state": "open", "open_blockers": [],
                         "decision_blockers": []} for n in every],
            "owners": [],
            "worktrees": [{"issue": n, "recorded": None,
                           "candidate": {"path": paths[n], "state": "absent"}} for n in every],
            "forge": keyed(lambda n: {"state": "none", "url": None, "merge_sha": None}),
            "delivery_contracts": keyed(lambda n: pairs[n]["contract"] if n in pairs else None),
            "authorization_intents": keyed(
                lambda n: [pairs[n]["initial_intent"]] if n in pairs else []),
            "authority_observations": keyed(lambda n: []),
            "reevaluation_evidence": keyed(lambda n: []),
            "delivery_observations": keyed(lambda n: []),
            "requested_scopes": keyed(lambda n: None), "recoveries": keyed(lambda n: None),
            "verification": []}
        done = self.ws("control", "--repo-root", self.root, "--run-id", session["run_id"],
                       "--request-file", "-", stdin=json.dumps(request).encode())
        self.case.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        spawned = {action["issue"]: action for action in json.loads(done.stdout)["actions"]
                   if action["kind"] == "spawn"}
        self.case.assertLessEqual(set(issues), set(spawned))
        return spawned
