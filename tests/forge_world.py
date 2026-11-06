"""A fake provider world for the forge adapter suites (#124 D12, D22).

`ForgeWorld(test_case, tools=())` writes executable `gh`, `git` and `claude-bash-lifecycle-guard`
scripts, plus one more for each name in `tools`, into a temporary `bin/` and patches
`os.environ` until the test's cleanup: `PATH` is that `bin/` alone, `GITHUB_TOKEN` is a harness token, and `FORGE_WORLD` names the state
directory. Each script logs `{tool, argv, stdin, token_visible}` to `calls.jsonl` and answers
from `responses.json`, keyed by `json.dumps([tool, *argv])`. An unregistered call exits 64,
and a `gh` that sees a token variable exits 65, so a leaked credential fails loudly.

The standard responses are built from the shared spelling fixture, never from copied
literals, so the world and the guard suite cannot disagree about a provider spelling.

`invoke_ready(...)` registers the invoke happy path (D12, D23): `checkout` is a real temporary
directory the fake `git rev-parse --show-toplevel` names. A call whose argv carries
`--notes-file <path>` is keyed with that path replaced by `<NOTES>`; the real path is logged.

`merge_ready(...)` registers the `pr_merge` invoke path (issue 554 D6, D13): the protection
read, the head-branch auto-delete read, the pull request view, the base ref and the one
`gh pr merge`, each adjustable by a keyword. `FLOOR_PROTECTION` is the protection payload that
meets the release floor, and `verification_ready` registers it for its default checks.

`verification_ready(...)` registers the three `gh api` reads of `release_verification` (#128
D12). They stay outside the spelling fixture: the fixture pins the guard's rows, and these
reads are read-only paths the guard never adjudicates.

`merge_observation_ready(...)` registers the three reads of `release_verification.observe_merge`
(issue 554 D3): the open release pull requests, the default branch tip and the compare of that
tip against the candidate. The tip read spells the fixture's `pr_merge.base_ref` row, so it
agrees with `merge_ready` on the same `base_tip`.

`comment_store(slug, issue, comments, ...)` makes the fake `gh` serve one issue's comments from
shared state (issue 623): list, POST, PATCH and DELETE of that issue's comments act on one
`store.json` under an exclusive `flock`, and every other argv falls through to the registered
responses. An optional `schedule` forces the order of named store operations across concurrent
callers: an operation that matches a schedule entry beyond the cursor waits until the cursor
reaches it, and one that matches no entry at or past the cursor runs unscheduled. `stored()`
reads the comments now and `wait_cursor(n)` blocks until `n` entries have run. `host_clock`
makes every host-clock read of the named modules return one instant, so a module that reads
the host clock instead of the server's fails its test.
"""
import contextlib
import json
import os
import stat
import sys
import tempfile
import time
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures/forge-adapter-spellings.json").read_text("utf-8"))
CANONICAL = FIXTURE["canonical"]
ROWS = {row["id"]: row for row in FIXTURE["rows"]}
TOOLS = ("gh", "git", "claude-bash-lifecycle-guard")
CLASS_BRANCHES = {"elevenyellow/nodocom": "dev"}
FLOOR_PROTECTION = {
    "required_status_checks": {
        "strict": True, "contexts": ["Nix Eval", "Instruction Budget"],
        "checks": [{"context": "Nix Eval", "app_id": None},
                   {"context": "Instruction Budget", "app_id": None}]},
    "enforce_admins": {"enabled": True}}

STORE_HANDLER = """\
if tool == "gh" and (state / "store.json").exists():
    import fcntl

    def store_op(store):
        slug, issue = store["slug"], store["issue"]
        base = "repos/" + slug + "/issues/" + str(issue) + "/comments"
        one = "repos/" + slug + "/issues/comments/"
        body = argv[5][5:] if len(argv) == 6 and argv[4] == "-f" and argv[5].startswith("body=") else None
        if argv == ["api", "--paginate", "--slurp", base + "?per_page=100"]:
            return "list", None, None
        if body is not None and argv[:4] == ["api", "-X", "POST", base]:
            return "post", None, body
        if body is not None and argv[:3] == ["api", "-X", "PATCH"] and argv[3].startswith(one) and argv[3][len(one):].isdigit():
            return "patch", int(argv[3][len(one):]), body
        if len(argv) == 4 and argv[:3] == ["api", "-X", "DELETE"] and argv[3].startswith(one) and argv[3][len(one):].isdigit():
            return "delete", int(argv[3][len(one):]), None
        return None

    def entry_matches(entry, op):
        kind, target, body = op
        parts = entry.split(":", 1) if kind == "post" else entry.split(":", 2)
        if parts[0] != kind:
            return False
        if kind == "list":
            return len(parts) == 1
        if kind == "post":
            return len(parts) == 2 and parts[1] in body.split("\\n", 1)[0]
        if len(parts) < 2 or parts[1] != str(target):
            return False
        return len(parts) == 2 or (kind == "patch" and parts[2] in body.split("\\n", 1)[0])

    def save(store):
        tmp = state / "store.json.tmp"
        tmp.write_text(json.dumps(store), encoding="utf-8")
        os.replace(tmp, state / "store.json")

    def fail_404():
        sys.stderr.write("gh: Not Found (HTTP 404)\\n")
        sys.exit(1)

    waiting_for = None
    deadline = time.monotonic() + 10
    while True:
        with open(state / "store.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            store = json.loads((state / "store.json").read_text("utf-8"))
            op = store_op(store)
            if op is None:
                break
            kind, target, body = op
            cursor = store["cursor"]
            matches = [i for i, entry in enumerate(store["schedule"])
                       if i >= cursor and entry_matches(entry, op)]
            if not matches or matches[0] == cursor:
                if matches:
                    store["cursor"] = cursor + 1
                comments = store["comments"]
                found = [c for c in comments if c["id"] == target]
                if kind == "list":
                    out = sorted(comments, key=lambda c: c["id"])
                elif kind == "post":
                    out = {"id": store["next_id"], "body": body, "created_at": store["clock"],
                           "updated_at": store["clock"]}
                    store["next_id"] += 1
                    comments.append(out)
                elif not found:
                    fail_404()
                elif kind == "patch":
                    found[0]["body"] = body
                    found[0]["updated_at"] = store["clock"]
                    out = found[0]
                else:
                    comments.remove(found[0])
                    out = None
                save(store)
                if kind == "list":
                    out = [out]
                if out is not None:
                    sys.stdout.write(json.dumps(out))
                sys.exit(0)
            waiting_for = matches[0]
        if time.monotonic() > deadline:
            sys.stderr.write("fake gh: schedule entry " + str(waiting_for) + " never reached\\n")
            sys.exit(66)
        time.sleep(0.01)
"""

SCRIPT = """#!{python}
import json, os, sys, time
from pathlib import Path

state = Path(os.environ["FORGE_WORLD"])
tool = Path(sys.argv[0]).name
argv = sys.argv[1:]
token = bool(os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN"))
stdin = sys.stdin.read() if tool == "claude-bash-lifecycle-guard" else ""
with open(state / "calls.jsonl", "a", encoding="utf-8") as log:
    log.write(json.dumps({{"tool": tool, "argv": argv, "stdin": stdin,
                          "token_visible": token}}) + "\\n")
if tool == "gh" and token:
    sys.stderr.write("gh: a token variable reached the child\\n")
    sys.exit(65)
# store handler
responses = json.loads((state / "responses.json").read_text("utf-8"))
keyed = list(argv)
if "--notes-file" in keyed:
    keyed[keyed.index("--notes-file") + 1] = "<NOTES>"
response = responses.get(json.dumps([tool, *keyed]))
if response is None:
    sys.stderr.write("fake " + tool + ": unregistered call\\n")
    sys.exit(64)
time.sleep(response["sleep"])
sys.stdout.write(response["stdout"])
sys.stderr.write(response["stderr"])
sys.exit(response["exit"])
"""


class ForgeWorld:
    def __init__(self, test_case: unittest.TestCase, tools: tuple[str, ...] = ()) -> None:
        tmp = tempfile.TemporaryDirectory()
        test_case.addCleanup(tmp.cleanup)
        root = Path(tmp.name).resolve()
        self.state, self.bin, self.checkout = root / "state", root / "bin", root / "checkout"
        self.state.mkdir()
        self.bin.mkdir()
        self.checkout.mkdir()
        for tool in TOOLS + tuple(tools):
            path = self.bin / tool
            path.write_text(SCRIPT.format(python=sys.executable).replace("# store handler\n", STORE_HANDLER),
                            encoding="utf-8")
            path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        patch = mock.patch.dict(os.environ, {"PATH": str(self.bin), "GITHUB_TOKEN": "harness-token",
                                             "FORGE_WORLD": str(self.state)})
        patch.start()
        test_case.addCleanup(patch.stop)
        self.reset()

    def env(self) -> dict[str, str]:
        """The child environment that reaches this world: its `bin/` as `PATH`, and its state."""
        return {"PATH": str(self.bin), "FORGE_WORLD": str(self.state)}

    def reset(self) -> None:
        """Forget every registered response and every logged call."""
        (self.state / "responses.json").write_text("{}", encoding="utf-8")
        (self.state / "calls.jsonl").write_text("", encoding="utf-8")
        for name in ("store.json", "store.lock"):
            (self.state / name).unlink(missing_ok=True)

    def respond(self, tool: str, argv: list[str], *, exit: int = 0, stdout: str = "",
                stderr: str = "", sleep: float = 0) -> None:
        path = self.state / "responses.json"
        responses = json.loads(path.read_text("utf-8"))
        responses[json.dumps([tool, *argv])] = {
            "exit": exit, "stdout": stdout, "stderr": stderr, "sleep": sleep}
        path.write_text(json.dumps(responses), encoding="utf-8")

    def respond_json(self, tool: str, argv: list[str], value: object, **kwargs) -> None:
        self.respond(tool, argv, stdout=json.dumps(value), **kwargs)

    def not_found(self, tool: str, argv: list[str]) -> None:
        self.respond(tool, argv, exit=1, stderr="gh: Not Found (HTTP 404)")

    def forbidden(self, tool: str, argv: list[str]) -> None:
        self.respond(tool, argv, exit=1, stderr="gh: Forbidden (HTTP 403)")

    def comment_store(self, slug: str, issue: int, comments=(), *, next_id: int = 100,
                      clock: str = "2026-11-06T10:00:00Z", schedule=()) -> None:
        """Serve one issue's comments from shared state (see STORE_HANDLER)."""
        (self.state / "store.json").write_text(json.dumps({
            "slug": slug, "issue": issue, "comments": list(comments), "next_id": next_id,
            "clock": clock, "schedule": list(schedule), "cursor": 0}), encoding="utf-8")

    def stored(self) -> list[dict]:
        """The store's comments now, ascending id."""
        store = json.loads((self.state / "store.json").read_text("utf-8"))
        return sorted(store["comments"], key=lambda c: c["id"])

    def wait_cursor(self, at_least: int, timeout: float = 10.0) -> None:
        """Block until `at_least` schedule entries have run; AssertionError after `timeout`."""
        deadline = time.monotonic() + timeout
        while True:
            store = json.loads((self.state / "store.json").read_text("utf-8"))
            if store["cursor"] >= at_least:
                return
            if time.monotonic() > deadline:
                raise AssertionError(f"schedule cursor stayed at {store['cursor']}, wanted {at_least}")
            time.sleep(0.01)

    def calls(self) -> list[dict]:
        text = (self.state / "calls.jsonl").read_text("utf-8")
        return [json.loads(line) for line in text.splitlines()]

    def argvs(self, tool: str) -> list[list[str]]:
        return [call["argv"] for call in self.calls() if call["tool"] == tool]

    def canonical(self, slug: str = CANONICAL["slug"], **overrides: object) -> None:
        """Register the happy-path responses for the fixture's canonical values, with `slug`
        (and, for a repository class that has one, its branch) substituted. `overrides` name
        canonical values to replace: branch, tag, commit, tag_object, pr, base_tip,
        merge_commit."""
        values = {**CANONICAL, "slug": slug,
                  "branch": CLASS_BRANCHES.get(slug, CANONICAL["branch"]), **overrides}

        def argv(row_id: str) -> list[str]:
            swaps = [(CANONICAL["slug"], values["slug"]), (CANONICAL["tag"], values["tag"]),
                     (CANONICAL["tag_object"], values["tag_object"]),
                     (CANONICAL["merge_commit"], values["merge_commit"]),
                     ("/heads/" + CANONICAL["branch"], "/heads/" + values["branch"]),
                     ("/branches/" + CANONICAL["branch"] + "/", "/branches/" + values["branch"] + "/")]
            out = []
            for part in ROWS[row_id]["argv"][1:]:
                for old, new in swaps:
                    part = part.replace(old, new)
                out.append(str(values["pr"]) if part == str(CANONICAL["pr"]) else part)
            return out

        url = f"https://github.com/{values['slug']}"
        self.respond_json("gh", argv("tag.ref"),
                          {"object": {"type": "tag", "sha": values["tag_object"]}})
        self.respond_json("gh", argv("tag.object"),
                          {"object": {"type": "commit", "sha": values["commit"]}})
        self.respond_json("gh", argv("release.view"), {
            "tag_name": values["tag"], "draft": False, "html_url": f"{url}/releases/tag/{values['tag']}"})
        self.respond_json("gh", argv("pr_merge.view"), {
            "state": "MERGED", "baseRefName": values["branch"], "headRefName": "topic",
            "headRefOid": values["commit"], "mergeCommit": {"oid": values["merge_commit"]},
            "url": f"{url}/pull/{values['pr']}", "statusCheckRollup": []})
        self.respond_json("gh", argv("pr_merge.base_ref"), {"object": {"sha": values["base_tip"]}})
        self.respond_json("gh", argv("pr_merge.merge_commit"),
                          {"parents": [{"sha": values["base_tip"]}, {"sha": values["commit"]}]})
        self.respond_json("gh", argv("pr_merge.protection"), FLOOR_PROTECTION)

    def merge_ready(self, *, protection=FLOOR_PROTECTION, auto_delete="false", pr_state="OPEN",
                    pr_base=CANONICAL["branch"], pr_head=CANONICAL["commit"],
                    base_tip=CANONICAL["base_tip"], merge_exit=0, merge_stderr="",
                    merge_sleep=0.0) -> None:
        """Register the `pr_merge` invoke path on the fixture rows' argv (issue 554 D6, D13).

        `protection` is a payload dict, `404` or `403` for those statuses, `"fail"` for an
        HTTP 500, or `"timeout"` for the floor payload after a 6 s sleep. The merge answers
        with `merge_exit`, `merge_stderr` and `merge_sleep`.
        """

        def row(row_id: str) -> list[str]:
            return ROWS[row_id]["argv"][1:]

        if isinstance(protection, dict):
            self.respond_json("gh", row("pr_merge.protection"), protection)
        elif protection == 404:
            self.not_found("gh", row("pr_merge.protection"))
        elif protection == 403:
            self.forbidden("gh", row("pr_merge.protection"))
        elif protection == "fail":
            self.respond("gh", row("pr_merge.protection"), exit=1,
                         stderr="gh: Internal Server Error (HTTP 500)")
        elif protection == "timeout":
            self.respond_json("gh", row("pr_merge.protection"), FLOOR_PROTECTION, sleep=6)
        else:
            raise ValueError(f"unknown protection answer {protection!r}")
        self.respond("gh", row("pr_merge.head_auto_delete"), stdout=auto_delete + "\n")
        self.respond_json("gh", row("pr_merge.view"), {
            "state": pr_state, "baseRefName": pr_base, "headRefName": "dev", "headRefOid": pr_head,
            "mergeCommit": None, "url": f"https://github.com/{CANONICAL['slug']}/pull/{CANONICAL['pr']}",
            "statusCheckRollup": []})
        self.respond_json("gh", row("pr_merge.base_ref"), {"object": {"sha": base_tip}})
        self.respond("gh", row("pr_merge.merge"), exit=merge_exit, stderr=merge_stderr,
                     sleep=merge_sleep)

    def invoke_ready(self, slug: str = CANONICAL["slug"], *, origin: str | None = None,
                     full_name: str | None = None, push_urls: list[str] | None = None, tag_local: str | None = None,
                     tag_lookup_exit: int = 0, tag_create_exit: int = 0, compare: str = "ahead",
                     merged_compare: str = "identical", fetch_exit: int = 0,
                     guard_exit: int = 0, push_exit: int = 0, push_stderr: str = "",
                     push_sleep: float = 0, create_exit: int = 0,
                     create_stdout: str = f"https://github.com/{CANONICAL['slug']}/releases/tag/"
                                          f"{CANONICAL['tag']}\n",
                     create_stderr: str = "") -> None:
        """Register the invoke happy path, each step's answer adjustable by a keyword.

        `slug` changes only what `origin` is: the target repository stays the canonical one,
        which `invoke.repository` and `tag.compare` are keyed on. `origin` replaces the whole
        origin URL (and so the default push URL), host included. `tag_local` names the commit
        an existing annotated local tag peels to; by default no local tag exists.
        `merged_compare` answers the containment read of the release PR's merge commit and
        `fetch_exit` the `git fetch` that precedes tagging it (issue 554 D8); both are inert
        for a candidate without `merge`.
        """
        tag, commit = CANONICAL["tag"], CANONICAL["commit"]
        origin = origin or f"git@github.com:{slug}.git"
        self.respond("git", ["rev-parse", "--show-toplevel"], stdout=f"{self.checkout}\n")
        self.respond("git", ["remote", "get-url", "origin"], stdout=origin + "\n")
        self.respond("git", ["remote", "get-url", "--push", "--all", "origin"],
                     stdout="".join(url + "\n" for url in (push_urls or [origin])))
        self.respond("gh", ROWS["invoke.repository"]["argv"][1:],
                     stdout=(full_name or CANONICAL["slug"]) + "\n")
        self.respond("gh", ROWS["tag.compare"]["argv"][1:], stdout=compare + "\n")
        listing = ["for-each-ref", "--format=%(objecttype)", f"refs/tags/{tag}"]
        if tag_local is None:
            self.respond("git", listing, exit=tag_lookup_exit)
        else:
            self.respond("git", listing, stdout="tag\n", exit=tag_lookup_exit)
            self.respond("git", ["rev-parse", f"refs/tags/{tag}^{{commit}}"], stdout=tag_local + "\n")
        self.respond("gh", ROWS["tag.merged_compare"]["argv"][1:], stdout=merged_compare + "\n")
        self.respond("git", ["fetch", "--no-tags", "origin", f"refs/heads/{CANONICAL['branch']}"],
                     exit=fetch_exit)
        self.respond("git", ["tag", "-a", tag, commit, "-m", f"release: {tag}"], exit=tag_create_exit)
        self.respond("git", ["tag", "-a", tag, CANONICAL["merge_commit"], "-m", f"release: {tag}"],
                     exit=tag_create_exit)
        self.respond("claude-bash-lifecycle-guard", [], exit=guard_exit,
                     stderr="lifecycle guard: refused" if guard_exit else "")
        self.respond("git", ROWS["tag.push"]["argv"][1:], exit=push_exit, stderr=push_stderr,
                     sleep=push_sleep)
        create = [("<NOTES>" if part == CANONICAL["notes_path"] else part)
                  for part in ROWS["release.create"]["argv"][1:]]
        self.respond("gh", create, exit=create_exit, stdout=create_stdout, stderr=create_stderr)

    def verification_ready(self, *, tip=CANONICAL["commit"], commit=CANONICAL["commit"],
                           checks=None, runs=None, total_count=None, protection_exit=0,
                           slug=CANONICAL["slug"], integration=CANONICAL["branch"],
                           default=CANONICAL["branch"], sleep=0.0):
        """Register release_verification's three reads (spec §3). Defaults: required
        `Nix Eval` and `Instruction Budget` (app_id null), one completed success run each."""
        checks = [{"context": "Nix Eval", "app_id": None},
                  {"context": "Instruction Budget", "app_id": None}] if checks is None else checks
        if runs is None:
            runs = [{"id": index + 1, "name": entry["context"], "status": "completed",
                     "conclusion": "success", "app": {"id": 15368}}
                    for index, entry in enumerate(checks)]
        self.respond_json("gh", ["api", f"repos/{slug}/git/ref/heads/{integration}"],
                          {"object": {"sha": tip, "type": "commit"}}, sleep=sleep)
        protection = ["api", f"repos/{slug}/branches/{default}/protection"]
        if protection_exit:
            self.respond("gh", protection, exit=protection_exit, stderr="gh: Not Found (HTTP 404)")
        else:
            self.respond_json("gh", protection, {
                "required_status_checks": {"strict": True, "contexts": [c["context"] for c in checks],
                                           "checks": checks},
                "enforce_admins": {"enabled": True}})
        self.respond_json("gh", ["api", f"repos/{slug}/commits/{commit}/check-runs?per_page=100"],
                          {"total_count": len(runs) if total_count is None else total_count,
                           "check_runs": runs})

    def merge_observation_ready(self, *, prs=None, base_tip=CANONICAL["base_tip"], compare="ahead",
                                slug=CANONICAL["slug"], integration="dev",
                                default=CANONICAL["branch"], commit=CANONICAL["commit"]):
        """Register observe_merge's three reads (issue 554 D3). By default one open pull request
        from `integration` is at `commit`, and the default branch is `compare` of `base_tip`."""
        if prs is None:
            prs = [{"number": CANONICAL["pr"], "head": {"sha": commit, "ref": integration}}]
        owner = slug.split("/")[0]
        self.respond_json("gh", ["api", f"repos/{slug}/pulls?state=open&base={default}"
                                        f"&head={owner}:{integration}&per_page=2"], prs)
        self.respond_json("gh", ["api", f"repos/{slug}/git/ref/heads/{default}"],
                          {"object": {"sha": base_tip, "type": "commit"}})
        self.respond_json("gh", ["api", f"repos/{slug}/compare/{base_tip}...{commit}"],
                          {"status": compare})


@contextlib.contextmanager
def host_clock(instant: datetime, *modules):
    """Make every host-clock read return `instant`: `time.time`, and `now`/`utcnow`/`today`
    on the `datetime` name of each module in `modules` (issue 623 D5)."""
    class WrongClock(datetime):
        @classmethod
        def now(cls, tz=None):
            return instant.astimezone(tz) if tz else instant.replace(tzinfo=None)

        @classmethod
        def utcnow(cls):
            return instant.astimezone(timezone.utc).replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch("time.time", return_value=instant.timestamp()))
        for module in modules:
            stack.enter_context(mock.patch.object(module, "datetime", WrongClock))
        yield
