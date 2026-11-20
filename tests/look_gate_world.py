"""A throwaway repository for the look-before-merge gate, played end to end (issue 1142).

`LookGateWorld(test_case)` builds a bare origin, a work clone whose origin URL is a github
URL (so the guard derives the slug), the stand-in forge of `forge_world`, and an actor that
answers every agent call of the real programs `deliver-batch.js` and `deliver-standard.js`
(through `program_bridge`): it does the git work for real, runs the real `look-approval`
command, and merges only after the real lifecycle guard, run from source, admits the command.
`play_scenario` plays the six steps of the gate on that one world:

1. a batch of one marked and one unmarked issue; 2. the unmarked one lands, the marked one
awaits the owner's look; 3. the guard refuses a direct merge of the marked pull request;
4. a changes answer moves its head; 5. an approval of the old head is stale and posts nothing;
6. an approval of the new head, recorded as the console records it, lets the delivery merge.

Decisions: P1 the actor merges only on the guard's exit 0; P2 every push goes to the bare
origin by its path so the clone's origin URL stays the github one the guard reads; P3 a
failing step that is a program defect is fixed in the program with its own regression case.
No test support here is a `TestCase`.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from agent_tools.delivery import look_marker

from .forge_world import FLOOR_PROTECTION, ForgeWorld
from .pre_push_world import FAKE_DERIVE
from .program_bridge import NODE, run_program

# Resolved at import, before ForgeWorld patches PATH.
GIT = shutil.which("git")
JQ = shutil.which("jq")

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
PROGRAMS = REPO_ROOT / "home/common/claude-code/skills/deliver-standard"
SLUG = "throwaway/look-gate"
MARKED = 11
UNMARKED = 12
BATCH_ID = "h1-20261116-1200"
REFUSAL = ("lifecycle guard: unsafe merge: issue {issue} needs the owner's look before merge, "
           "and head {short} has no recorded approval; ask the owner and record the answer")
IDENT = ("-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false")
MARKED_BODY = ("## Acceptance criteria\n\n"
               "- [ ] [code] the heading reads well — measured: a test\n"
               "- [ ] [human] before merge: the page heading at 390 px — measured: the owner, on the console\n")
UNMARKED_BODY = ("## Acceptance criteria\n\n"
                 "- [ ] [code] the footer reads well — measured: a test\n")
PR_FIELDS = "state,baseRefName,headRefName,headRefOid,mergeStateStatus,url,statusCheckRollup"
SHA = "a" * 40
PASS = {"verdict": "pass", "findings": []}
PLAN = {"status": "planned", "plan_root": "/r/plan.md",
        "acceptance": [{"id": "AC1", "text": "works", "kind": "code"}],
        "tasks": [{"n": 1, "title": "one", "file": "task-1.md", "risk": "standard"}]}
HOLDER_ID = re.compile(r"--holder <host>/([A-Za-z0-9._-]+) ")
MERGE_COMMAND = re.compile(r"(?:unset GITHUB_TOKEN && )?gh pr merge \d+ --repo \S+[^\n]*")


class StepFailure(AssertionError):
    """A step of the scenario broke its expectation; `world` holds the state it broke in."""

    def __init__(self, step: int, world: "LookGateWorld", message: str) -> None:
        super().__init__(f"step {step}: {message}")
        self.step = step
        self.world = world


class LookGateWorld:
    def __init__(self, test_case: unittest.TestCase, guard_source: Path = GUARD_SOURCE) -> None:
        for name, path in (("node", NODE), ("git", GIT), ("jq", JQ)):
            if path is None:
                raise AssertionError(f"{name} is not on PATH; the look-gate scenario needs it")
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name).resolve()
        self.guard_source = guard_source
        self.forge = ForgeWorld(test_case)
        self.env = {k: v for k, v in os.environ.items()
                    if k not in ("GITHUB_TOKEN", "GH_TOKEN") and not k.startswith("GIT_")}
        self.env.update(self.forge.env())
        (self.tmp / "home").mkdir()
        (self.tmp / "gitconfig").write_text("", encoding="utf-8")
        self.env.update(HOME=str(self.tmp / "home"), GIT_CONFIG_GLOBAL=str(self.tmp / "gitconfig"),
                        GIT_CONFIG_NOSYSTEM="1")
        self.guard_log: list[tuple[str, int, str]] = []
        self.prs: dict[int, dict] = {}
        self.merge_commits: dict[int, str] = {}
        self._scratch = 0
        self._build_repositories()
        self._register_forge()
        self._write_guard_fixtures()
        self.rows = self._rows()

    # ---- git ----

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        proc = subprocess.run([GIT, *IDENT, *args], cwd=cwd, env=self.env, text=True,
                              capture_output=True, timeout=120)
        if check and proc.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} exited {proc.returncode}: {proc.stderr}")
        return proc.stdout.strip() if check else proc

    def _build_repositories(self) -> None:
        self.bare = self.tmp / "origin.git"
        self.clone = self.tmp / "clone"
        self.git("init", "--bare", "-b", "main", str(self.bare))
        seed = self.tmp / "seed"
        self.git("clone", str(self.bare), str(seed))
        self.git("checkout", "-b", "main", cwd=seed)
        (seed / "README").write_text("look gate\n", encoding="utf-8")
        self.git("add", "README", cwd=seed)
        self.git("commit", "-m", "seed", cwd=seed)
        self.git("push", str(self.bare), "HEAD:refs/heads/main", cwd=seed)
        self.git("clone", str(self.bare), str(self.clone))
        self.git("remote", "set-url", "origin", f"git@github.com:{SLUG}.git", cwd=self.clone)
        self.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/main", cwd=self.clone)
        (self.clone / ".git/info/exclude").write_text(".wt/\n", encoding="utf-8")

    def origin_tip(self, ref: str) -> str:
        return self.git("rev-parse", f"refs/heads/{ref}", cwd=self.bare)

    def contains(self, ancestor: str, ref: str = "main") -> bool:
        proc = self.git("merge-base", "--is-ancestor", ancestor, f"refs/heads/{ref}", cwd=self.bare,
                        check=False)
        return proc.returncode == 0

    def fetch(self) -> None:
        self.git("fetch", str(self.bare), "+refs/heads/*:refs/remotes/origin/*", cwd=self.clone)

    def push(self, directory: Path, branch: str) -> None:
        self.git("push", str(self.bare), f"HEAD:refs/heads/{branch}", cwd=directory)
        self.fetch()

    # ---- forge ----

    def _register_forge(self) -> None:
        self.forge.comment_store(SLUG, MARKED, labels=[])
        for number, body in ((MARKED, MARKED_BODY), (UNMARKED, UNMARKED_BODY)):
            self.forge.respond_json("gh", ["api", f"repos/{SLUG}/issues/{number}"],
                                    {"number": number, "title": "Page heading", "body": body})
        self.forge.respond_json(
            "gh", ["api", "--paginate", "--slurp", f"repos/{SLUG}/issues/{UNMARKED}/comments?per_page=100"],
            [[]])
        self.forge.respond_json("gh", ["api", f"repos/{SLUG}/branches/main/protection"], FLOOR_PROTECTION)

    def branch_of(self, issue: int) -> str:
        return f"issue-{issue}-page"

    def worktree_of(self, issue: int) -> Path:
        return self.clone / ".wt" / f"issue-{issue}"

    def register_pr(self, number: int) -> None:
        """(Re)register the two reads of a pull request from the origin and its state now."""
        pr = self.prs[number]
        branch = pr["branch"]
        head = self.origin_tip(branch)
        pr["head"] = head
        view = ["gh", "pr", "view", str(number), "--repo", SLUG, "--json"]
        self.forge.respond_json(*view[:1], view[1:] + [PR_FIELDS], {
            "state": pr["state"], "baseRefName": "main", "headRefName": branch, "headRefOid": head,
            "mergeStateStatus": "CLEAN", "url": f"https://github.com/{SLUG}/pull/{number}",
            "statusCheckRollup": [{"__typename": "CheckRun", "status": "COMPLETED",
                                   "conclusion": "SUCCESS"}]})
        subjects = self.git("log", "--format=%s", f"main..{branch}", cwd=self.bare).splitlines()
        self.forge.respond_json(*view[:1], view[1:] + ["title,body,commits,closingIssuesReferences"], {
            "title": f"Issue {pr['issue']}", "body": f"Closes #{pr['issue']}",
            "commits": [{"messageHeadline": s, "messageBody": ""} for s in subjects],
            "closingIssuesReferences": []})

    def open_pr(self, issue: int, branch: str) -> int:
        number = 100 + issue
        if number not in self.prs:
            self.prs[number] = {"issue": issue, "branch": branch, "state": "OPEN", "head": None}
        self.register_pr(number)
        return number

    def pr_of(self, issue: int) -> dict:
        number = 100 + issue
        pr = self.prs[number]
        return {"number": number, "branch": pr["branch"], "state": pr["state"], "head": pr["head"]}

    def merge_pr(self, number: int) -> str:
        pr = self.prs[number]
        premerge_head = pr["head"]
        self._scratch += 1
        scratch = self.tmp / f"scratch-{self._scratch}"
        self.git("clone", str(self.bare), str(scratch))
        self.git("checkout", "-B", "main", "origin/main", cwd=scratch)
        self.git("merge", "--no-ff", "--no-edit", f"origin/{pr['branch']}", cwd=scratch)
        self.git("push", str(self.bare), "HEAD:refs/heads/main", cwd=scratch)
        self.fetch()
        pr["state"] = "MERGED"
        self.register_pr(number)
        merge_commit = self.origin_tip("main")
        self.merge_commits[pr["issue"]] = merge_commit
        # #1186: the reads and the write of `look-approval tick` against the merged pull request.
        self.forge.respond_json("gh", ["api", f"repos/{SLUG}/pulls/{number}"],
                                {"number": number, "merged": True, "head": {"sha": premerge_head}})
        body = {MARKED: MARKED_BODY, UNMARKED: UNMARKED_BODY}[pr["issue"]]
        self.forge.respond_json(
            "gh", ["api", "-X", "PATCH", f"repos/{SLUG}/issues/{pr['issue']}",
                   "-f", "body=" + look_marker.tick_markers(body)[0]], {"number": pr["issue"]})
        return merge_commit

    def look_comments(self) -> list[dict]:
        return [c for c in self.forge.stored()
                if str(c["body"]).split("\n", 1)[0].startswith("<!-- agent:look")]

    # ---- the guard and the look command ----

    def _write_guard_fixtures(self) -> None:
        self.base_policy = self.tmp / "base-policy.json"
        self.base_policy.write_text(json.dumps({
            "authorized_owners": ["throwaway"], "integration_bases": {}, "git_bin": GIT,
            "gh_bin": GIT, "jq_bin": JQ}), encoding="utf-8")
        self.policy = self.tmp / "policy.json"
        self.policy.write_text(json.dumps({"derived_repositories": {}, "derivation": None}), encoding="utf-8")
        self.derive_bin = self.tmp / "fake-derive"
        self.derive_bin.write_text(FAKE_DERIVE.format(python=sys.executable, rows=json.dumps({})),
                                   encoding="utf-8")
        self.derive_bin.chmod(0o755)
        self.look_bin = self.tmp / "look-bin"
        self.look_bin.write_text(
            f"#!{sys.executable}\n"
            "import os\nimport sys\n"
            f"os.environ['PYTHONPATH'] = {str(REPO_ROOT / 'python')!r}\n"
            "os.execv(sys.executable, [sys.executable, '-m', 'agent_tools.delivery.look_approval',"
            " 'judge', *sys.argv[1:]])\n", encoding="utf-8")
        self.look_bin.chmod(0o755)

    def guard(self, command: str) -> subprocess.CompletedProcess:
        proc = subprocess.run(
            [sys.executable, "-I", str(self.guard_source), "--base-policy", str(self.base_policy),
             "--policy", str(self.policy), "--derive-bin", str(self.derive_bin),
             "--look-bin", str(self.look_bin), "--gh-bin", str(self.forge.bin / "gh"),
             "--child-timeout-seconds", "5"],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": command},
                              "cwd": str(self.clone)}),
            cwd=self.clone, env=self.env, text=True, capture_output=True, timeout=120)
        self.guard_log.append((command, proc.returncode, proc.stderr))
        return proc

    def look_approval(self, *argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "agent_tools.delivery.look_approval", *argv], cwd=self.clone,
            env={**self.env, "PYTHONPATH": str(REPO_ROOT / "python")}, text=True,
            capture_output=True, timeout=120)

    def look_of(self, issue: int) -> dict:
        proc = self.look_approval("marked", "--repo", SLUG, "--issue", str(issue))
        out = json.loads(proc.stdout.strip().splitlines()[-1])
        return {"verdict": out["verdict"], "covers": out.get("covers", []), "acs": out.get("acs", [])}

    # ---- the actor ----

    def actor(self, message: dict) -> object:
        label = message["label"] or ""
        for pattern, handler in self.rows:
            match = re.search(pattern, label)
            if match:
                return handler(message, match)
        raise AssertionError(f"no actor reply for {label} ({message['program']}, "
                             f"issue {message['issue']}, mode {message['mode']})")

    def issue_of(self, message: dict, match: re.Match | None = None) -> int:
        if message["issue"] is not None:
            return message["issue"]
        return int(re.search(r"-(\d+)(?:-|$)", message["label"]).group(1))

    def head_of(self, issue: int) -> str:
        pr = self.prs.get(100 + issue)
        if pr is not None and pr["head"]:
            return pr["head"]
        return self.git("rev-parse", "HEAD", cwd=self.worktree_of(issue))

    def ensure_worktree(self, issue: int) -> Path:
        path = self.worktree_of(issue)
        if not path.exists():
            self.git("worktree", "add", "--no-track", "-b", self.branch_of(issue), str(path),
                     "origin/main", cwd=self.clone)
        return path

    def commit_line(self, issue: int, line: str) -> dict:
        path = self.ensure_worktree(issue)
        before = self.git("rev-parse", "HEAD", cwd=path)
        with open(path / f"page-{issue}.txt", "a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        self.git("add", f"page-{issue}.txt", cwd=path)
        self.git("commit", "-m", line, cwd=path)
        after = self.git("rev-parse", "HEAD", cwd=path)
        return {"status": "done", "start_head": before, "commit": after, "tests": ["t"], "notes": "ok",
                "renew": {"verdict": "renewed"}}

    def _setup_batch(self, message, match):
        return {"ok": True, "host": "h1", "slug": SLUG, "integration_branch": "main",
                "default_branch": "main", "merge_strategy": "merge", "delete_branch": True,
                "unset_env": [], "max_parallel": 2, "required_checks": None}

    def _setup_standard(self, message, match):
        issue = message["issue"]
        path = self.ensure_worktree(issue)
        reply = {
            "ok": True, "host": "h1", "slug": SLUG, "integration_branch": "main",
            "default_branch": "main", "branch": self.branch_of(issue), "worktree_path": str(path),
            "dirty": False, "unset_env": [], "merge_strategy": "merge", "delete_branch": True,
            "review": {"code": "cr", "plan": "pr"},
            "review_state": {"code": "available", "plan": "available"},
            "knowledge": {"standards": [str(self.clone / "docs/standards")], "hints": [], "rejections": []},
            "verification": [{"id": "build", "argv": ["true"], "cwd": "."}],
            "head": self.git("rev-parse", "HEAD", cwd=path), "look": self.look_of(issue)}
        holder = HOLDER_ID.search(message["prompt"])
        if holder:
            plan_dir = self.tmp / f"plan-{issue}"
            plan_dir.mkdir(exist_ok=True)
            reply.update(
                holder=f"h1/{holder.group(1)}", acquire={"verdict": "acquired", "comment_id": 7},
                claim={"ok": True, "worktree": str(path),
                       "base_sha": self.git("rev-parse", "origin/main", cwd=self.clone),
                       "plan_dir": str(plan_dir)},
                answer={"verdict": "none", "comment_id": None, "questions": [], "decisions": ""},
                renew={"verdict": "renewed"})
        return reply

    def _setup(self, message, match):
        return (self._setup_batch if message["program"] == "deliver-batch" else self._setup_standard)(
            message, match)

    def _facts(self, message, match):
        issue = self.issue_of(message)
        return {"state": "OPEN", "labels": [], "title": "t", "branch": self.branch_of(issue),
                "claim": {"verdict": "free", "by": None}, "merged_refs": [], "open_pr": None,
                "native": {"verdict": "read", "blocked_by": []}, "blockers": [],
                "decision": {"verdict": "none", "comment_id": None, "questions": [], "decisions": ""},
                "lane": "standard", "why": "x", "look": self.look_of(issue)}

    def _commit(self, message, match):
        issue = message["issue"]
        return self.commit_line(issue, f"{message['label']} for issue {issue}")

    def _verify(self, message, match):
        issue = message["issue"]
        return {"head": self.git("rev-parse", "HEAD", cwd=self.worktree_of(issue)), "clean": True,
                "results": [{"id": "build", "status": "pass", "summary": "ok"}],
                "renew": {"verdict": "renewed"}}

    def _pull_request(self, message, match):
        issue = self.issue_of(message)
        path = self.worktree_of(issue)
        branch = self.branch_of(issue)
        self.push(path, branch)
        number = self.open_pr(issue, branch)
        head = self.origin_tip(branch)
        behind = self.git("merge-base", "--is-ancestor", "origin/main", "HEAD", cwd=path,
                          check=False).returncode != 0
        reply = {"pr": number, "head": head, "probe": {"conflicted": False}, "behind": behind,
                 "renew": {"verdict": "renewed"}}
        if message["label"] == "pr" or message["label"].startswith("land-pr-"):
            reply.update(lock={"verdict": "already_held", "lock_sha": head},
                         checks={"state": "passed", "head": head, "required": ["ci"], "passed": ["ci"]})
        return reply

    def _sync(self, message, match):
        issue = self.issue_of(message)
        path = self.worktree_of(issue)
        self.git("merge", "--no-edit", "origin/main", cwd=path)
        head = self.git("rev-parse", "HEAD", cwd=path)
        return {"status": "done", "conflicted": False, "merge_commit": head, "head": head, "notes": "clean"}

    def _push(self, message, match):
        issue = self.issue_of(message)
        self.push(self.worktree_of(issue), self.branch_of(issue))
        if 100 + issue in self.prs:
            self.register_pr(100 + issue)
        return {"head": self.origin_tip(self.branch_of(issue)), "renew": {"verdict": "renewed"}}

    def _look_head(self, message, match):
        pr = self.pr_of(message["issue"])
        return {"state": pr["state"], "head": pr["head"], "renew": {"verdict": "renewed"}}

    def _look_post(self, message, match):
        line = re.search(r"Run alone and exactly: (look-approval post[^\n]*)", message["prompt"]).group(1)
        proc = self.look_approval(*line.split()[1:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def _look_read(self, message, match):
        line = re.search(r"Run alone and exactly: (look-approval status[^\n]*)", message["prompt"]).group(1)
        proc = self.look_approval(*line.split()[1:])
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def _close_out(self, message, match):
        out = {"issue_state": "CLOSED", "branch_deleted": True, "released": True, "decision_ended": True,
               "notes": "ok", "release": {"verdict": "released"}}
        found = re.search(r"Run alone and exactly: (look-approval tick[^\n]*)", message["prompt"])
        if found:
            proc = self.look_approval(*found.group(1).split()[1:])
            out["look_tick"] = json.loads(proc.stdout.strip().splitlines()[-1])
        return out

    def _merge(self, message, match):
        command = MERGE_COMMAND.search(message["prompt"]).group(0)
        number = int(re.search(r"gh pr merge (\d+) ", command).group(1))
        head = self.prs[number]["head"]
        lock = {"verdict": "already_held", "lock_sha": head}
        proc = self.guard(command)
        if proc.returncode == 0:
            merge_commit = self.merge_pr(number)
            return {"merged": True, "merge_commit": merge_commit, "notes": "merged", "lock": lock,
                    "renew": {"verdict": "renewed"}}
        return {"merged": False, "notes": proc.stderr, "lock": lock, "renew": {"verdict": "renewed"}}

    def _lock(self, message, match):
        issue = self.issue_of(message)
        head = self.head_of(issue)
        return {"renew": {"verdict": "renewed"}, "lock": {"verdict": "acquired", "lock_sha": head}}

    def _checks(self, message, match):
        issue = self.issue_of(message)
        head = self.head_of(issue)
        return {"state": "passed", "head": head, "required": ["ci"], "passed": ["ci"],
                "renew": {"verdict": "renewed"}, "lock": {"verdict": "already_held", "lock_sha": head}}

    def _hold(self, message, match):
        issue = message["issue"]
        merge = self.merge_commits.get(issue) or self.head_of(issue)
        criteria = re.search(r"Criteria: (\[.*\])", message["prompt"])
        checks = [{"ac": a["id"], "kind": a["kind"]}
                  for a in (json.loads(criteria.group(1)) if criteria else []) if a["kind"] != "code"]
        return {"merge_commit_local": True, "code_unmet": [], "blocks": [], "split": [],
                "block": {"v": 1, "merge": merge, "checks": checks}, "lint": {"ok": True, "errors": []},
                "verify_run": {"ran": True, "exit": 0}, "issue_state": "OPEN", "notes": "held",
                "release": {"verdict": "released"}}

    def _rows(self) -> list:
        def const(value):
            return lambda message, match: json.loads(json.dumps(value))

        return [
            (r"^setup$", self._setup),
            (r"^facts-\d+$", self._facts),
            (r"^(impl-\d+|look-fix|fix-.*)$", self._commit),
            (r"^verify-fix-", const({"status": "done", "start_head": "b0", "commit": "c0ffee",
                                     "tests": ["t"], "notes": "ok"})),
            (r"^verify(-|$)", self._verify),
            (r"^(look-pr|pr|land-pr-\d+|land-open-\d+)$", self._pull_request),
            (r"^sync-resolve-", const({"status": "done", "conflicted": True, "merge_commit": SHA,
                                       "resolved_files": ["a.py"], "notes": "resolved"})),
            (r"^sync-\d+$", self._sync),
            (r"^(look-push|land-push-.*)$", self._push),
            (r"^look-head$", self._look_head),
            (r"^look-post$", self._look_post),
            (r"^look-read$", self._look_read),
            (r"^(merge|land-merge-\d+)$", self._merge),
            (r"^land-unlock", const({"verdict": "released"})),
            (r"^land-(re)?lock-", self._lock),
            (r"^(land-)?checks-", self._checks),
            (r"^acquire(-|$)", const({"verdict": "acquired", "comment_id": 7})),
            (r"^renew-", const({"verdict": "renewed", "comment_id": 7})),
            (r"^plan(-revise|-rules-revise|-branch-revise|-task-revise)?$", const(PLAN)),
            (r"-codex$", const({"available": True, **PASS})),
            (r"^diff-size$", const({"measured": True, "changed_lines": 10})),
            (r"^owner-answer$", const({"verdict": "none", "comment_id": None, "questions": [],
                                       "decisions": "", "renew": {"verdict": "renewed"}})),
            (r"review|^final-", const(PASS)),
            (r"^hold$", self._hold),
            (r"^close-out", self._close_out),
            (r"^settle-", const({"state": "OPEN", "release": None})),
            (r"^release-", const({"verdict": "released"})),
        ]


def mutant_guard(directory: Path) -> Path:
    """Write a copy of the guard whose `look_problem` returns None first, and return its path."""
    anchor = "def look_problem(context, number, pr_facts, head_commit, subject=None):\n"
    inserted = "    return None  # mutant (#1142): the look refusal removed\n"
    source = GUARD_SOURCE.read_text()
    found = source.count(anchor)
    if found != 1:
        raise AssertionError(f"the look_problem anchor occurs {found} times in the guard, not once")
    path = directory / "lifecycle_guard.py"
    path.write_text(source.replace(anchor, anchor + inserted, 1))
    return path


def play_scenario(test_case: unittest.TestCase, guard_source: Path = GUARD_SOURCE,
                  through: int = 6) -> dict:
    """Play steps 1..`through`; a broken expectation of step k raises StepFailure(k, ...)."""
    world = LookGateWorld(test_case, guard_source)
    out: dict = {"world": world}
    clone = str(world.clone)

    def fail(step: int, message: str):
        raise StepFailure(step, world, message)

    def expect(step: int, ok: bool, message: str) -> None:
        if not ok:
            fail(step, message)

    def play(program: str, args: dict) -> tuple[dict, list[str]]:
        labels: list[str] = []

        def counting(message: dict) -> object:
            labels.append(message["label"])
            return world.actor(message)

        return run_program(PROGRAMS / program, args, counting), labels

    def resume(cont: dict, look: dict) -> tuple[dict, list[str]]:
        return play("deliver-standard.js", {
            "repo_root": clone, "issue": MARKED, "batch_id": BATCH_ID, "mode": "ship", "cont": cont,
            "look": look})

    # 1 and 2: the batch lands the unmarked issue and stops the marked one at the owner's look.
    batch, _ = play("deliver-batch.js", {
        "repo_root": clone, "batch_id": BATCH_ID, "child_script": str(PROGRAMS / "deliver-standard.js"),
        "issues": [MARKED, UNMARKED]})
    out["batch"] = batch
    result = batch["result"] or {}
    rows = {row.get("issue"): row for row in result.get("table", [])
            if isinstance(row, dict)}
    expect(2, batch["error"] is None, f"the batch program threw: {batch['error']}")
    expect(2, rows.get(UNMARKED, {}).get("outcome") == "landed",
           f"the unmarked issue did not land: {rows.get(UNMARKED)}")
    marked = rows.get(MARKED, {})
    expect(2, marked.get("outcome") == "awaiting-look", f"the marked issue is not awaiting its look: {marked}")
    expect(2, marked.get("pr") == 100 + MARKED, f"the marked pull request is not 111: {marked}")
    h1 = world.origin_tip(world.branch_of(MARKED))
    expect(2, h1 == world.pr_of(MARKED)["head"], "the registry head of pull request 111 is not the origin tip")
    expect(2, marked.get("head") == h1, f"the awaiting row names {marked.get('head')}, not the pushed head {h1}")
    expect(2, world.pr_of(MARKED)["state"] == "OPEN", "pull request 111 is not open")
    expect(2, world.contains(world.origin_tip(world.branch_of(UNMARKED))),
           "the unmarked issue's branch is not in main")
    expect(2, not world.contains(h1), "the marked head is already in main")
    actions = [a for a in result.get("owner_actions", []) if isinstance(a, dict)]
    expect(2, len(actions) == 1 and actions[0].get("reason") == "awaiting-look"
           and actions[0].get("issue") == MARKED and actions[0].get("head") == h1,
           f"owner_actions is not one awaiting-look entry for issue 11 at {h1}: {actions}")
    expect(2, not any(f"gh pr merge {100 + MARKED} " in command for command, _, _ in world.guard_log),
           "a merge of pull request 111 was already tried")
    cont1 = actions[0]["cont"]
    main1 = world.origin_tip("main")
    if through < 3:
        return out

    # 3: the guard refuses a direct merge of the marked pull request.
    r = world.guard(f"gh pr merge 111 --repo {SLUG} --merge --match-head-commit {h1} --delete-branch")
    expect(3, r.returncode == 2 and REFUSAL.format(issue=MARKED, short=h1[:7]) in r.stderr.splitlines(),
           f"the guard did not refuse the direct merge of the marked pull request "
           f"(exit {r.returncode}): {r.stderr}")
    expect(3, world.origin_tip("main") == main1, "main moved")
    if through < 4:
        return out

    # 4: a changes answer fixes and pushes, and the head moves.
    changes, labels = resume(cont1, {"answer": "changes", "words": "make the heading bold"})
    out["changes"] = changes
    res = changes["result"] or {}
    expect(4, changes["error"] is None, f"the changes run threw: {changes['error']}")
    expect(4, res.get("stage") == "awaiting-look", f"the changes run stopped at {res.get('stage')}: {res}")
    h2 = res.get("head")
    expect(4, h2 != h1, "the head did not move")
    expect(4, h2 == world.origin_tip(world.branch_of(MARKED)) == world.pr_of(MARKED)["head"],
           f"the new head {h2} is not the origin tip and the registry head")
    expect(4, world.git("merge-base", "--is-ancestor", h1, h2, cwd=world.bare, check=False).returncode == 0,
           "the old head is not an ancestor of the new head")
    expect(4, labels.count("look-fix") == 1, f"look-fix ran {labels.count('look-fix')} times")
    expect(4, world.origin_tip("main") == main1, "main moved")
    if through < 5:
        return out

    # 5: an approval of the old head is stale.
    posted = world.look_approval("post", "--repo", SLUG, "--issue", str(MARKED), "--pr", str(100 + MARKED),
                                 "--head", h1, "--answer", "approved", "--message", "owner-old")
    verdict = json.loads(posted.stdout.strip().splitlines()[-1]) if posted.stdout.strip() else {}
    expect(5, posted.returncode == 0 and verdict.get("verdict") == "posted",
           f"the approval of the old head was not posted: {posted.stdout} {posted.stderr}")
    r = world.guard(f"gh pr merge 111 --repo {SLUG} --merge --match-head-commit {h2} --delete-branch")
    expect(5, r.returncode == 2 and REFUSAL.format(issue=MARKED, short=h2[:7]) in r.stderr.splitlines(),
           f"the guard did not refuse the new head on an approval of the old one "
           f"(exit {r.returncode}): {r.stderr}")
    comments = len(world.look_comments())
    stale, labels = resume(res["cont"], {"answer": "approve", "head": h1})
    out["stale"] = stale
    res_stale = stale["result"] or {}
    expect(5, stale["error"] is None, f"the stale run threw: {stale['error']}")
    expect(5, res_stale.get("stage") == "awaiting-look" and res_stale.get("head") == h2,
           f"the stale approval did not stop at awaiting-look at {h2}: {res_stale}")
    expect(5, "look-post" not in labels and "merge" not in labels, f"the stale run called {labels}")
    expect(5, len(world.look_comments()) == comments, "the stale run posted a look comment")
    expect(5, world.origin_tip("main") == main1, "main moved")
    if through < 6:
        return out

    # 6: the owner's approval of the new head, recorded as the console records it, lets the delivery merge.
    recorded = world.look_approval("post", "--repo", SLUG, "--issue", str(MARKED), "--pr", str(100 + MARKED),
                                   "--head", h2, "--answer", "approved", "--message", "1")
    answered = json.loads(recorded.stdout.strip().splitlines()[-1]) if recorded.stdout.strip() else {}
    expect(6, recorded.returncode == 0 and answered.get("verdict") == "posted",
           f"the approval of the new head was not posted: {recorded.stdout} {recorded.stderr}")
    approve, labels = resume(res_stale["cont"], {"answer": "approve", "head": h2})
    out["approve"] = approve
    final = approve["result"] or {}
    expect(6, approve["error"] is None, f"the approving run threw: {approve['error']}")
    expect(6, final.get("stage") == "done", f"the approving run stopped at {final.get('stage')}: {final}")
    expect(6, labels.count("look-read") == 1, f"look-read ran {labels.count('look-read')} times")
    expect(6, "look-post" not in labels, f"the approving run posted: {labels}")
    last = world.look_comments()
    first_line = str(last[-1]["body"]).split("\n", 1)[0] if len(last) == comments + 1 else ""
    expect(6, f"head={h2}" in first_line and "answer=approved" in first_line,
           f"the new look comment does not approve {h2}: {first_line!r}")
    command, code, _ = world.guard_log[-1]
    expect(6, code == 0 and command.startswith(f"gh pr merge {100 + MARKED} ")
           and f"--match-head-commit {h2} --delete-branch" in command,
           f"the last guard decision is not the admitted merge at {h2}: {command} (exit {code})")
    expect(6, world.contains(h2), "the approved head is not in main")
    expect(6, world.pr_of(MARKED)["state"] == "MERGED", "pull request 111 is not merged")
    expect(6, final.get("look_tick", {}).get("verdict") == "ticked",
           f"the close-out did not tick the look marker: {final.get('look_tick')}")
    return out
