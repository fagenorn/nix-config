"""The stubbed world's fake pull-request forge: a `gh` front.

Run as `python gh_pulls.py <state.json> <forge gh> <args...>`. It answers the pull-request calls
a landing makes from the state file, against the bare `origin` the state names, and execs
`<forge gh>` (the tracker fake) for every other argv:

  pr create --repo S --base B --head H --title T --body Y
  pr list --repo S --head H --state open|merged|all --json <fields>
  pr view N --repo S --json <fields>
  pr merge N --repo S --merge --match-head-commit SHA --delete-branch
  api repos/S/commits/<sha>/pulls?per_page=100
  api repos/S/pulls?state=<open|closed|all>&base=...&head=...
  api repos/S/branches/<b>/protection      GitHub's plan-gated 403, as `gh` reports it
  api repos/S/branches/<b>
  api graphql (the closingIssuesReferences query of a pull request: its body's `Closes #<n>` lines)

The state is `{"slug", "bare", "git", "next", "pulls", "rollup", "events"}`, read and written under
an exclusive lock. A merge lands only the head named by `--match-head-commit` and only with
`--delete-branch`; it is a real `--no-ff` merge into `main` of the bare, and it does not close the
issue. Each event of `events` fires once, on the first read of `statusCheckRollup` of a pull
request and after that read's answer is computed: `move-head` adds a commit on top of the head
branch, `steal-lock` moves the land lock of `main` (in the tracker fake's ref store) to the sha of a
second open pull request. A token variable in the environment is refused with exit 65.

The tracker fake answers a read of the issue from one fixed response; once the tracker fake's store
holds the issue closed, this front lays that state over the read's `state` and `state_reason`.
"""

import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PLAN_GATED = ('{"message":"Upgrade to GitHub Pro or make this repository public to enable this '
              'feature.","documentation_url":"https://docs.github.com/rest/branches/'
              'branch-protection#get-branch-protection","status":"403"}')
LOCK_REF = "refs/agent-locks/land/main"
PLAIN = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_SYSTEM": os.devnull,
         "GIT_AUTHOR_NAME": "forge", "GIT_AUTHOR_EMAIL": "forge@example.invalid",
         "GIT_COMMITTER_NAME": "forge", "GIT_COMMITTER_EMAIL": "forge@example.invalid"}


def fail(message: str, code: int = 1) -> None:
    sys.stderr.write(f"fake gh: {message}\n")
    sys.exit(code)


def git(state: dict, *args: str, cwd: str | None = None, check: bool = True) -> str:
    done = subprocess.run([state["git"], *args], cwd=cwd, capture_output=True, text=True,
                          env={**os.environ, **PLAIN})
    if check and done.returncode != 0:
        fail(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip() if done.returncode == 0 else ""


def tip(state: dict, branch: str) -> str:
    return git(state, "-C", state["bare"], "rev-parse", "--verify", "--quiet",
               f"refs/heads/{branch}^{{commit}}", check=False)


def scratch(state: dict, branch: str) -> str:
    """A clone of the bare on `branch`, in a new temporary directory."""
    clone = tempfile.mkdtemp(prefix="forge-scratch-")
    git(state, "clone", "--quiet", "--branch", branch, state["bare"], clone)
    return clone


def options(argv: list[str]) -> dict:
    found: dict = {}
    index = 0
    while index < len(argv):
        word = argv[index]
        if word.startswith("--") and index + 1 < len(argv) and not argv[index + 1].startswith("--"):
            found[word] = argv[index + 1]
            index += 2
        else:
            found[word] = True
            index += 1
    return found


def head_of(state: dict, pull: dict) -> str:
    if pull["state"] == "OPEN" and "fixedHead" not in pull:
        return tip(state, pull["headRefName"]) or pull["headRefOid"]
    return pull.get("fixedHead", pull["headRefOid"])


def commits_of(state: dict, pull: dict) -> list[dict]:
    if pull["state"] == "MERGED":
        span = f"{pull['mergeCommit']['oid']}^1..{pull['mergeCommit']['oid']}^2"
    elif "fixedHead" in pull:
        return []
    else:
        span = f"refs/heads/main..{head_of(state, pull)}"
    text = git(state, "-C", state["bare"], "log", "--reverse", "--format=%H%x00%s%x00%b%x01", span)
    commits = []
    for entry in text.split("\x01"):
        if entry.strip():
            oid, headline, body = (entry.strip("\n").split("\x00") + ["", ""])[:3]
            commits.append({"oid": oid, "messageHeadline": headline, "messageBody": body.strip()})
    return commits


def view(state: dict, pull: dict) -> dict:
    head = head_of(state, pull)
    return {**pull, "headRefOid": head, "mergeStateStatus": "CLEAN",
            "statusCheckRollup": state["rollup"], "commits": commits_of(state, pull),
            "closingIssuesReferences": [], "mergeCommit": pull.get("mergeCommit")}


def rest(state: dict, pull: dict) -> dict:
    repo = {"full_name": state["slug"]}
    merged = pull["state"] == "MERGED"
    return {"number": pull["number"], "state": "open" if pull["state"] == "OPEN" else "closed",
            "merged_at": "2026-11-06T10:00:00Z" if merged else None,
            "html_url": pull["url"], "updated_at": "2026-11-06T10:00:00Z",
            "base": {"ref": pull["baseRefName"], "repo": repo},
            "head": {"ref": pull["headRefName"], "sha": head_of(state, pull), "repo": repo}}


def find(state: dict, number: str) -> dict:
    for pull in state["pulls"]:
        if str(pull["number"]) == number:
            return pull
    fail(f"no pull request {number}")
    raise SystemExit(1)


def fire(state: dict) -> None:
    """Fire every pending event, once; the read that called this has already been answered."""
    pending, state["events"] = state["events"], []
    for event in pending:
        if event["event"] == "move-head":
            pull = next(p for p in state["pulls"] if p["state"] == "OPEN")
            clone = scratch(state, pull["headRefName"])
            Path(clone, "moved.txt").write_text("the head moved\n", encoding="utf-8")
            git(state, "-C", clone, "add", "moved.txt")
            git(state, "-C", clone, "commit", "--quiet", "-m", "move the head")
            git(state, "-C", clone, "push", "--quiet", state["bare"],
                f"HEAD:refs/heads/{pull['headRefName']}")
        elif event["event"] == "steal-lock":
            number = state["next"]
            state["next"] += 1
            state["pulls"].append({
                "number": number, "state": "OPEN", "baseRefName": "main",
                "headRefName": "stolen-lock", "headRefOid": event["sha"], "fixedHead": event["sha"],
                "title": "A second pull request", "body": "",
                "url": f"https://github.com/{state['slug']}/pull/{number}"})
            steal(event["sha"])


def steal(sha: str) -> None:
    """Move the land lock of `main` in the tracker fake's ref store to `sha`."""
    forge = Path(os.environ["FORGE_WORLD"])
    with open(forge / "refs.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        store = json.loads((forge / "refs.json").read_text("utf-8"))
        store["refs"][LOCK_REF] = sha
        scratch_file = forge / "refs.json.tmp"
        scratch_file.write_text(json.dumps(store), encoding="utf-8")
        os.replace(scratch_file, forge / "refs.json")


def create(state: dict, flags: dict) -> None:
    head = tip(state, flags["--head"])
    if not head:
        fail(f"no branch {flags['--head']} on the remote")
    number = state["next"]
    state["next"] += 1
    url = f"https://github.com/{state['slug']}/pull/{number}"
    state["pulls"].append({"number": number, "state": "OPEN", "baseRefName": flags["--base"],
                           "headRefName": flags["--head"], "headRefOid": head,
                           "title": flags["--title"], "body": flags.get("--body", ""), "url": url})
    print(url)


def merge(state: dict, number: str, flags: dict) -> None:
    pull = find(state, number)
    head = head_of(state, pull)
    if pull["state"] != "OPEN":
        fail(f"pull request {number} is not open")
    if "--delete-branch" not in flags:
        fail("this fake lands only with --delete-branch")
    if flags.get("--match-head-commit") != head:
        fail(f"head branch was modified: the head is {head}")
    clone = scratch(state, pull["baseRefName"])
    git(state, "-C", clone, "merge", "--quiet", "--no-ff", "--no-edit", f"origin/{pull['headRefName']}")
    git(state, "-C", clone, "push", "--quiet", state["bare"], f"HEAD:refs/heads/{pull['baseRefName']}")
    git(state, "-C", state["bare"], "update-ref", "-d", f"refs/heads/{pull['headRefName']}")
    pull.update(state="MERGED", headRefOid=head,
                mergeCommit={"oid": tip(state, pull["baseRefName"])})


def listing(state: dict, flags: dict) -> list[dict]:
    wanted = {"open": ("OPEN",), "merged": ("MERGED",), "closed": ("MERGED", "CLOSED"),
              "all": ("OPEN", "MERGED", "CLOSED")}[flags.get("--state", "open")]
    return [p for p in state["pulls"] if p["state"] in wanted
            and ("--head" not in flags or p["headRefName"] == flags["--head"])]


def project(entry: dict, fields: str) -> dict:
    return {name: entry[name] for name in fields.split(",") if name in entry}


def api(state: dict, path: str) -> object:
    route, _, query = path.partition("?")
    params = dict(part.partition("=")[::2] for part in query.split("&") if part)
    parts = route.split("/")
    prefix = ["repos", *state["slug"].split("/")]
    if parts[:3] != prefix:
        return None
    rest_of = parts[3:]
    if len(rest_of) == 3 and rest_of[0] == "commits" and rest_of[2] == "pulls":
        return [rest(state, p) for p in state["pulls"] if head_of(state, p) == rest_of[1]]
    if rest_of == ["pulls"]:
        if params.get("page", "1") != "1":
            return []
        wanted = {"open": ("OPEN",), "closed": ("MERGED", "CLOSED"),
                  "all": ("OPEN", "MERGED", "CLOSED")}[params.get("state", "open")]
        found = [p for p in state["pulls"] if p["state"] in wanted
                 and ("base" not in params or p["baseRefName"] == params["base"])
                 and ("head" not in params or f"{prefix[1]}:{p['headRefName']}" == params["head"])]
        return [rest(state, p) for p in found]
    if len(rest_of) == 3 and rest_of[0] == "branches" and rest_of[2] == "protection":
        sys.stdout.write(PLAN_GATED + "\n")
        sys.stderr.write("gh: Upgrade to GitHub Pro or make this repository public to enable this "
                         "feature. (HTTP 403)\n")
        sys.exit(1)
    if len(rest_of) == 2 and rest_of[0] == "branches":
        found_tip = tip(state, rest_of[1])
        if not found_tip:
            sys.stdout.write('{"message":"Branch not found","status":"404"}\n')
            fail("Branch not found (HTTP 404)")
        return {"name": rest_of[1], "commit": {"sha": found_tip}}
    return None


def handle(state: dict, argv: list[str]) -> bool:
    """Answer `argv` and return true, or return false when it is not a pull-request call."""
    flags = options(argv[2:] if argv[:1] == ["pr"] and len(argv) > 1 else argv)
    if argv[:2] == ["pr", "create"] and flags.get("--repo") == state["slug"]:
        create(state, flags)
        return True
    if argv[:2] == ["pr", "list"] and "--search" not in flags and flags.get("--repo") == state["slug"]:
        print(json.dumps([project(view(state, p), flags["--json"]) for p in listing(state, flags)]))
        return True
    if argv[:2] == ["pr", "view"] and len(argv) > 2 and flags.get("--repo") == state["slug"]:
        pull = find(state, argv[2])
        print(json.dumps(project(view(state, pull), flags["--json"])))
        if "statusCheckRollup" in flags["--json"].split(","):
            fire(state)
        return True
    if argv[:2] == ["pr", "merge"] and len(argv) > 2 and flags.get("--repo") == state["slug"]:
        merge(state, argv[2], flags)
        return True
    if argv[:2] == ["api", "graphql"] and "closingIssuesReferences" in " ".join(argv):
        number = next((a[len("number="):] for a in argv if a.startswith("number=")), "")
        pull = next((p for p in state["pulls"] if str(p["number"]) == number), None)
        closes = re.findall(r"^Closes #(\d+)", pull["body"], re.MULTILINE) if pull else []
        print(json.dumps({"data": {"repository": {"pullRequest": {"closingIssuesReferences": {
            "nodes": [{"number": int(n)} for n in closes]}}}}}))
        return True
    if len(argv) == 2 and argv[0] == "api":
        answer = api(state, argv[1])
        if answer is None:
            return False
        print(json.dumps(answer))
        return True
    return False


def issue_read(state: dict, forge: str, argv: list[str]) -> bool:
    """Answer a read of the tracker's issue with the store's closed state laid over the fixed answer."""
    if len(argv) != 2 or argv[0] != "api" or not argv[1].startswith(f"repos/{state['slug']}/issues/"):
        return False
    number = argv[1].rsplit("/", 1)[1]
    store = json.loads((Path(os.environ["FORGE_WORLD"]) / "store.json").read_text("utf-8"))
    held = store.get("issue_state")
    if not number.isdigit() or held is None or int(number) != store["issue"] or held["state"] != "closed":
        return False
    done = subprocess.run([forge, *argv], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        sys.stdout.write(done.stdout)
        sys.stderr.write(done.stderr)
        sys.exit(done.returncode)
    answer = json.loads(done.stdout)
    answer.update(state="closed", state_reason=held["state_reason"])
    print(json.dumps(answer))
    return True


def main() -> None:
    state_path, forge, argv = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
    if os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"):
        fail("a token variable reached the child", 65)
    with open(f"{state_path}.lock", "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        before = json.dumps(state, sort_keys=True)
        try:
            handled = handle(state, argv)
        finally:
            if json.dumps(state, sort_keys=True) != before:
                scratch_file = Path(f"{state_path}.tmp")
                scratch_file.write_text(json.dumps(state), encoding="utf-8")
                os.replace(scratch_file, state_path)
    if not handled and not issue_read(state, forge, argv):
        os.execv(forge, [forge, *argv])


if __name__ == "__main__":
    main()
