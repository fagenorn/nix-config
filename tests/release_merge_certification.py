"""Native certification of the forge `pr_merge` against the live sandbox repository.

Issue 554 D10, D11, D19: the adapter's strict-protection floor and `--match-head-commit`
merge are proved on a real GitHub repository, not on `ForgeWorld`. This module makes live
GitHub calls against `SANDBOX` only and nothing in the repository runs it: it has no `test_`
prefix, so no suite collects it, and `just release-merge-certification` is its one entry.

Three rows run in order. Row a merges with the adapter and proves a second invoke is refused.
Row b moves the base after binding, row c moves the head after binding, and both prove GitHub
itself, asked twice over, refuses the stale merge (D20). The evidence names what GitHub did.
Every child runs with `GITHUB_TOKEN` and `GH_TOKEN` removed, so the keyring login answers.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from agent_tools import forge_adapter
from agent_tools.canonical import telemetry_digest
from agent_tools.github_remote import github_slug

SANDBOX = "fagenorn/release-merge-sandbox"
MARKER = "nix-config issue 554 release-merge certification sandbox"
CONTEXT = "release-merge-certification"
SCHEMA = "release-merge-certification/v1"

REPO_ROOT = Path(__file__).resolve().parents[1]
CHILD_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 2
POLL_LIMIT_SECONDS = 90
DETAIL_LIMIT = 240
TOKEN_VARIABLES = ("GITHUB_TOKEN", "GH_TOKEN")
TOKEN_LIKE = re.compile(r"(?:gh[pousr]_|github_pat_|Bearer )\S*")
MERGE_MUTATION = ("mutation($id:ID!,$head:GitObjectID!){mergePullRequest(input:{pullRequestId:$id,"
                  "expectedHeadOid:$head,mergeMethod:MERGE}){pullRequest{state}}}")
PROTECTION_MEMBERS = ("strict", "required_contexts", "enforce_admins")


def _phrases(*phrases: str) -> re.Pattern[str]:
    return re.compile("|".join(re.escape(phrase) for phrase in phrases), re.IGNORECASE)


TRANSPORT = _phrases("HTTP 5", "connection", "timed out", "could not resolve host", "TLS")
AUTH = _phrases("HTTP 401", "bad credentials", "authentication", "gh auth login")
PERMISSION = _phrases("HTTP 403", "must have admin rights", "resource not accessible", "permission")
MERGE_CONDITION = _phrases("not up to date", "out of date", "head branch was modified",
                           "base branch was modified", "base branch policy prohibits the merge",
                           "expected head")
REQUEST = _phrases("HTTP 400", "HTTP 404", "HTTP 422", "argument", "parse error",
                   "could not resolve to")
CLASSES = (("transport", TRANSPORT), ("auth", AUTH), ("permission", PERMISSION),
           ("merge_condition", MERGE_CONDITION), ("request", REQUEST))


def classify(timed_out: bool, text: str) -> str:
    """The refusal class of one failed attempt (issue 554 D20): the first pattern that matches."""
    if timed_out:
        return "transport"
    for name, pattern in CLASSES:
        if pattern.search(text):
            return name
    return "unclassified"


def _excerpt(text: str) -> str:
    return TOKEN_LIKE.sub("<redacted>", text)[:DETAIL_LIMIT]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Blocked(Exception):
    """GitHub answered an authentication or permission refusal: a human gate (D20)."""


class Stop(Exception):
    """A step the harness cannot continue past: the run is `inconclusive`."""


class Refused(Exception):
    """A refusal before any mutation: exit 2."""


class Child:
    """One finished child: its exit, output and whether it timed out."""

    def __init__(self, timed_out: bool, code: int, out: str, err: str) -> None:
        self.timed_out, self.code, self.out, self.err = timed_out, code, out, err

    @property
    def ok(self) -> bool:
        return not self.timed_out and self.code == 0

    @property
    def text(self) -> str:
        """What a refusal says: the first GraphQL error, else the first line of stderr."""
        try:
            error = json.loads(self.out)["errors"][0]
            return f"{error.get('type', 'error')}: {error['message']}"
        except (ValueError, KeyError, IndexError, TypeError):
            lines = self.err.strip().splitlines()
            return lines[0] if lines else ("timed out" if self.timed_out else "")


def run_child(argv: list[str], cwd: Path | None = None) -> Child:
    env = {name: value for name, value in os.environ.items() if name not in TOKEN_VARIABLES}
    try:
        done = subprocess.run(argv, capture_output=True, text=True, errors="replace", env=env,
                              cwd=cwd, stdin=subprocess.DEVNULL, timeout=CHILD_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return Child(True, -1, "", "")
    except OSError as error:
        return Child(False, 127, "", str(error))
    return Child(False, done.returncode, done.stdout, done.stderr)


class Certification:
    """One run: setup, rows a, b and c, cleanup, and the evidence they add up to."""

    def __init__(self, scratch: Path) -> None:
        self.run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.scratch = scratch
        self.clone = scratch / f"sandbox-{self.run}"
        self.rows: list[dict[str, Any]] = []
        self.opened: list[int] = []  # rows b and c leave their PRs open; cleanup closes them
        self.nodes: set[str] = set()
        self.spelling: str | None = None
        self.protection: dict[str, Any] = dict.fromkeys(PROTECTION_MEMBERS)
        self.actor: str | None = None

    # -- children -----------------------------------------------------------------------

    def _assert_sandbox(self, argv: list[str], cwd: Path | None) -> None:
        """Every mutation names the sandbox, or runs in its clone, before it starts."""
        if argv[0] == "git":
            assert cwd == self.clone, f"git mutation outside the sandbox clone: {argv}"
            return
        assert argv[0] == "gh", f"mutation by an unexpected tool: {argv}"
        if argv[1:3] == ["api", "graphql"]:
            node = next(arg[3:] for arg in argv if arg.startswith("id="))
            assert node in self.nodes, "graphql mutation on a node not read from the sandbox"
            return
        named = [argv[index + 1] for index, arg in enumerate(argv[:-1]) if arg == "--repo"]
        named += [arg for arg in argv if arg.startswith("repos/")]
        named += [argv[3]] if argv[1:3] in (["repo", "create"], ["repo", "clone"]) else []
        assert named and all(name in (SANDBOX, f"repos/{SANDBOX}")
                             or name.startswith(f"repos/{SANDBOX}/") for name in named), \
            f"gh mutation does not name only {SANDBOX}: {argv}"

    def _stop_on_refusal(self, done: Child) -> str:
        """The class of a failed child; an authentication or permission refusal blocks the run."""
        refusal = classify(done.timed_out, done.text)
        if refusal in ("auth", "permission"):
            raise Blocked(f"{refusal}: {_excerpt(done.text)}")
        return refusal

    def mutate(self, argv: list[str], cwd: Path | None = None) -> str:
        self._assert_sandbox(argv, cwd)
        done = run_child(argv, cwd)
        if not done.ok:
            refusal = self._stop_on_refusal(done)
            raise Stop(f"{' '.join(argv[:3])}: {refusal}: {_excerpt(done.text)}")
        return done.out

    def read(self, argv: list[str], cwd: Path | None = None) -> str:
        done = run_child(argv, cwd)
        if not done.ok:
            refusal = self._stop_on_refusal(done)
            raise Stop(f"{' '.join(argv[:3])}: {refusal}: {_excerpt(done.text)}")
        return done.out

    def git(self, *args: str) -> str:
        return self.mutate(["git", *args], self.clone).strip()

    def gh_json(self, *argv: str) -> Any:
        try:
            return json.loads(self.read(["gh", *argv]))
        except ValueError as error:
            raise Stop(f"gh {argv[0]}: output is not JSON: {error}") from error

    # -- setup --------------------------------------------------------------------------

    def login(self) -> str:
        done = run_child(["gh", "api", "user", "--jq", ".login"])
        if not done.ok:
            self._stop_on_refusal(done)
            raise Refused(f"cannot read the signed-in login: {_excerpt(done.text)}")
        return done.out.strip()

    def ensure_sandbox(self) -> None:
        """Refuse a repository without the marker; create it when it does not exist."""
        done = run_child(["gh", "api", f"repos/{SANDBOX}", "--jq", ".description"])
        if done.ok:
            if done.out.strip() != MARKER:
                raise Refused(f"{SANDBOX} does not carry the certification marker")
            return
        refusal = self._stop_on_refusal(done)
        if "HTTP 404" not in done.err:
            raise Refused(f"cannot read {SANDBOX}: {refusal}: {_excerpt(done.text)}")
        self.mutate(["gh", "repo", "create", SANDBOX, "--public", "--add-readme",
                     "--description", MARKER])

    def setup(self) -> None:
        self.mutate(["gh", "api", "--method", "PATCH", f"repos/{SANDBOX}",
                     "-F", "delete_branch_on_merge=false"])
        protection = {"required_status_checks": {"strict": True,
                                                 "checks": [{"context": CONTEXT, "app_id": -1}]},
                      "enforce_admins": True, "required_pull_request_reviews": None,
                      "restrictions": None}
        body = self.scratch / f"protection-{self.run}.json"
        body.write_text(json.dumps(protection), encoding="utf-8")
        self.mutate(["gh", "api", "--method", "PUT", f"repos/{SANDBOX}/branches/main/protection",
                     "--input", str(body)])
        self.mutate(["gh", "repo", "clone", SANDBOX, str(self.clone)])
        origin = self.git("remote", "get-url", "origin")
        if github_slug(origin) != SANDBOX:
            raise Stop(f"the clone's origin is {origin}, not {SANDBOX}")

    # -- pull requests ------------------------------------------------------------------

    def open_pr(self, name: str) -> tuple[int, str, str]:
        """A fresh branch from main's tip with one commit, pushed, statused and opened."""
        branch = f"cert-{self.run}-{name}"
        self.git("fetch", "origin", "main")
        self.git("checkout", "-B", branch, "origin/main")
        base_tip = self.git("rev-parse", "origin/main")
        head = self.commit(f"{self.run}-{name}")
        self.git("push", "origin", branch)
        self.status(head)
        created = self.mutate(["gh", "pr", "create", "--repo", SANDBOX, "--base", "main",
                               "--head", branch, "--title", f"cert {self.run} {name}",
                               "--body", "issue 554 certification"])
        number = int(created.strip().rsplit("/", 1)[-1])
        return number, head, base_tip

    def commit(self, stem: str) -> str:
        path = self.clone / "cert" / f"{stem}.txt"
        path.parent.mkdir(exist_ok=True)
        path.write_text(f"issue 554 certification {stem}\n", encoding="utf-8")
        self.git("add", f"cert/{stem}.txt")
        self.git("commit", "-m", f"cert {stem}")
        return self.git("rev-parse", "HEAD")

    def status(self, sha: str) -> None:
        self.mutate(["gh", "api", "--method", "POST", f"repos/{SANDBOX}/statuses/{sha}",
                     "-f", "state=success", "-f", f"context={CONTEXT}"])

    def wait_for_merge_state(self, number: int) -> None:
        deadline = time.monotonic() + POLL_LIMIT_SECONDS
        while True:
            state = self.gh_json("pr", "view", str(number), "--repo", SANDBOX,
                                 "--json", "mergeStateStatus")["mergeStateStatus"]
            if state != "UNKNOWN":
                return
            if time.monotonic() >= deadline:
                raise Stop(f"PR {number} mergeStateStatus stayed UNKNOWN for {POLL_LIMIT_SECONDS}s")
            time.sleep(POLL_INTERVAL_SECONDS)

    def main_tip(self) -> str:
        return self.read(["gh", "api", f"repos/{SANDBOX}/git/ref/heads/main",
                          "--jq", ".object.sha"]).strip()

    def after_state(self, number: int) -> dict[str, Any] | None:
        """What GitHub holds now, or None when it cannot be read."""
        try:
            view = self.gh_json("pr", "view", str(number), "--repo", SANDBOX,
                                "--json", "state,mergeCommit")
            merge = (view.get("mergeCommit") or {}).get("oid")
            parents = None
            if merge is not None:
                parents = self.gh_json("api", f"repos/{SANDBOX}/git/commits/{merge}",
                                       "--jq", "[.parents[].sha]")
            return {"state": view["state"], "base_tip": self.main_tip(), "merge_commit": merge,
                    "parents": parents}
        except (Stop, KeyError):
            return None

    def new_row(self, name: str, number: int, head: str, base_tip: str) -> dict[str, Any]:
        row = {"id": name, "pr": number, "bound": {"head": head, "base_tip": base_tip},
               "attempts": [], "after": dict.fromkeys(("state", "base_tip", "merge_commit",
                                                       "parents")),
               "verdict": None, "passed": False}
        self.rows.append(row)
        return row

    @staticmethod
    def settle(row: dict[str, Any], verdict: str) -> None:
        row["verdict"], row["passed"] = verdict, verdict == "passed"

    # -- attempts -----------------------------------------------------------------------

    def attempt(self, row: dict[str, Any], via: str, argv: list[str]) -> Child:
        """One mutation GitHub may refuse: recorded with its class, never raised."""
        self._assert_sandbox(argv, None)
        done = run_child(argv)
        refusal = None if done.ok else classify(done.timed_out, done.text)
        row["attempts"].append({"via": via, "outcome": "accepted" if done.ok else "refused",
                                "class": refusal, "detail": _excerpt(done.text)})
        if refusal in ("auth", "permission"):
            raise Blocked(f"{refusal}: {_excerpt(done.text)}")
        return done

    def stale_merge_row(self, row: dict[str, Any], attempts: list[tuple[str, list[str]]],
                        expected_tip: str) -> None:
        """Rows b and c: every attempt must be refused as a merge condition, nothing moves."""
        for via, argv in attempts:
            self.attempt(row, via, argv)
        row["after"] = self.after_state(row["pr"]) or row["after"]
        after = row["after"]
        if after["state"] is None:
            self.settle(row, "inconclusive")
        elif after["state"] != "OPEN" or after["base_tip"] != expected_tip:
            self.settle(row, "failed")
        elif {item["class"] for item in row["attempts"]} != {"merge_condition"}:
            self.settle(row, "inconclusive")
        else:
            self.settle(row, "passed")

    def merge_argv(self, number: int, head: str) -> list[str]:
        return ["gh", "pr", "merge", str(number), "--repo", SANDBOX, "--merge",
                "--match-head-commit", head]

    # -- rows ---------------------------------------------------------------------------

    def parameters(self, row: dict[str, Any]) -> dict[str, Any]:
        return {"action": "merge", "operation": "pr_merge", "config": {},
                "target": {"kind": "github_repository", "repository": SANDBOX, "branch": "main"},
                "candidate": {"version": "v0.0.1", "commit": row["bound"]["head"],
                              "merge": {"pr": row["pr"], "base_tip": row["bound"]["base_tip"]}}}

    def adapter(self, row: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
        """One `forge_adapter.invoke`, recorded as an attempt."""
        answer = forge_adapter.invoke(request)
        accepted = answer["result"] == "accepted"
        refusal = None if accepted else classify(False, answer["reference"])
        row["attempts"].append({"via": "adapter", "outcome": "accepted" if accepted else "refused",
                                "class": refusal, "detail": _excerpt(answer["reference"])})
        if refusal in ("auth", "permission"):
            raise Blocked(f"{refusal}: {_excerpt(answer['reference'])}")
        return answer

    def install_shim(self) -> Path:
        """A `claude-bash-lifecycle-guard` that records the command it is shown and allows it."""
        directory = self.scratch / f"guard-{self.run}"
        directory.mkdir()
        record = directory / "commands.log"
        shim = directory / "claude-bash-lifecycle-guard"
        shim.write_text(
            f"#!{sys.executable}\nimport json, sys\n"
            f"command = json.load(sys.stdin)['tool_input']['command']\n"
            f"with open({str(record)!r}, 'a', encoding='utf-8') as handle:\n"
            f"    handle.write(command + '\\n')\n", encoding="utf-8")
        shim.chmod(0o755)
        return directory

    def row_a(self) -> bool:
        """The adapter merges once and refuses a second merge; False when the floor gate fails."""
        number, head, base_tip = self.open_pr("a")
        row = self.new_row("a", number, head, base_tip)
        request = {"kind": "effect", "operation": "pr_merge", "parameters": self.parameters(row)}
        facts = forge_adapter.inspect(request).get("facts", {}).get("protection", {})
        self.protection = {name: facts.get(name) for name in PROTECTION_MEMBERS}
        if facts != {"status": "protected", "strict": True, "required_contexts": [CONTEXT],
                     "enforce_admins": True}:
            self.settle(row, "failed")
            return False
        self.wait_for_merge_state(number)
        shim = self.install_shim()
        saved_path, saved_cwd = os.environ["PATH"], Path.cwd()
        os.environ["PATH"] = f"{shim}{os.pathsep}{saved_path}"
        os.chdir(self.clone)
        try:
            first = self.adapter(row, request)
            first_inspect = forge_adapter.inspect(request)
            second = self.adapter(row, request)
            second_inspect = forge_adapter.inspect(request)
        finally:
            os.chdir(saved_cwd)
            os.environ["PATH"] = saved_path
        recorded = (shim / "commands.log").read_text(encoding="utf-8").splitlines() \
            if (shim / "commands.log").exists() else []
        self.spelling = recorded[0] if len(recorded) == 1 else None
        row["after"] = self.after_state(number) or row["after"]
        after = row["after"]
        if first["result"] != "accepted":
            transport = classify(False, first["reference"]) == "transport"
            self.settle(row, "inconclusive" if transport else "failed")
        elif after["state"] is None:
            self.settle(row, "inconclusive")
        else:
            expected = " ".join(self.merge_argv(number, head))
            held = (first_inspect["outcome"] == "satisfied"
                    and after["parents"] == [base_tip, head]
                    and second["result"] == "rejected"
                    and second["reference"] == "pr_not_open: MERGED"
                    and after["base_tip"] == after["merge_commit"]
                    and second_inspect["outcome"] == "satisfied"
                    and recorded == [expected])
            self.settle(row, "passed" if held else "failed")
        return True

    def row_b(self) -> None:
        """The base moves after binding: GitHub refuses the merge twice over."""
        number, head, base_tip = self.open_pr("b")
        row = self.new_row("b", number, head, base_tip)
        self.opened.append(number)
        side, side_head, _ = self.open_pr("bside")
        self.wait_for_merge_state(side)
        self.mutate(self.merge_argv(side, side_head))
        moved = self.main_tip()
        self.wait_for_merge_state(number)
        node = self.gh_json("pr", "view", str(number), "--repo", SANDBOX, "--json", "id")["id"]
        self.nodes.add(node)
        graphql = ["gh", "api", "graphql", "-f", f"query={MERGE_MUTATION}", "-f", f"id={node}",
                   "-f", f"head={head}"]
        self.stale_merge_row(row, [("argv", self.merge_argv(number, head)),
                                   ("graphql", graphql)], moved)

    def row_c(self) -> None:
        """The head moves after binding: `--match-head-commit` makes GitHub refuse the merge."""
        number, head, base_tip = self.open_pr("c")
        row = self.new_row("c", number, head, base_tip)
        self.opened.append(number)
        moved = self.commit(f"{self.run}-c-moved")
        self.git("push", "origin", f"cert-{self.run}-c")
        self.status(moved)
        self.wait_for_merge_state(number)
        self.stale_merge_row(row, [("argv", self.merge_argv(number, head))], base_tip)

    def close_open_prs(self) -> None:
        for number in self.opened:
            self.mutate(["gh", "pr", "close", str(number), "--repo", SANDBOX])

    # -- the run ------------------------------------------------------------------------

    def execute(self) -> str:
        """Run setup, the rows and cleanup, and return the result. A stop settles the row it hit."""
        stopped = None
        try:
            self.actor = self.login()
            self.ensure_sandbox()
            self.setup()
            if self.row_a():
                self.row_b()
                self.row_c()
            self.close_open_prs()
        except (Blocked, Stop) as stop:
            stopped = "blocked" if isinstance(stop, Blocked) else "inconclusive"
            print(f"{stopped}: {stop}", file=sys.stderr)
            if stopped == "inconclusive":
                try:
                    self.close_open_prs()
                except Blocked as refusal:
                    stopped = "blocked"
                    print(f"blocked: {refusal}", file=sys.stderr)
                except Stop as failure:
                    print(f"cleanup: {failure}", file=sys.stderr)
        for row in self.rows:
            if row["verdict"] is None:
                self.settle(row, stopped or "inconclusive")
        verdicts = {row["verdict"] for row in self.rows}
        if stopped == "blocked" or "blocked" in verdicts:
            return "blocked"
        if "failed" in verdicts:
            return "failed"
        return "passed" if stopped is None and verdicts == {"passed"} and len(self.rows) == 3 \
            else "inconclusive"

    def evidence(self, started: str, result: str) -> dict[str, Any]:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True,
                              text=True, check=True).stdout.strip()
        digest = telemetry_digest(forge_adapter.describe()["operations"]["pr_merge"])
        return {"schema": SCHEMA, "issue": 554, "repository": SANDBOX, "actor": self.actor,
                "implementation": {"commit": head, "pr_merge_descriptor_digest": digest},
                "protection": self.protection, "spelling": self.spelling,
                "guard": "recording-shim", "rows": self.rows, "result": result,
                "started_at": started, "finished_at": _now()}


EXIT = {"passed": 0, "failed": 1, "inconclusive": 1, "blocked": 3}


def _arguments(argv: list[str] | None) -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(prog="release-merge-certification", description=__doc__)
    parser.add_argument("--scratch", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    options = parser.parse_args(argv)
    scratch, output = options.scratch, options.output
    if not scratch.is_absolute() or not scratch.is_dir():
        raise Refused(f"--scratch {scratch} is not an existing absolute directory")
    output = output.resolve()
    if not output.parent.is_dir():
        raise Refused(f"--output {output} has no existing parent directory")
    return scratch, output


def main(argv: list[str] | None = None) -> int:
    try:
        scratch, output = _arguments(argv)
        started = _now()
        certification = Certification(scratch)
        result = certification.execute()
    except Refused as refusal:
        print(f"refused: {refusal}", file=sys.stderr)
        return 2
    evidence = certification.evidence(started, result)
    output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"result: {result}; evidence: {output}")
    return EXIT[result]


if __name__ == "__main__":
    sys.exit(main())
