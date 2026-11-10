"""verify-pending: the commands over a `verify` block.

`verify-pending lint --input <path|->` prints the verdict as one line of
`json.dumps(verdict, sort_keys=True)` and exits 0 when the block is accepted,
1 when it is refused and 2 on a usage error, a `--repo-root` that is not a git
work tree, an unreadable input path, a `--pr-head` that is not a sha, or `--pr-workflow`
with neither `--pr-head` nor `--pr-branch`. The grammar, the findings and the context options
(`--repo-root`, `--code-unmet`, `--pr-workflow` with `--pr-head` or `--pr-branch`, `--blocks`) are
in `agent_tools.verify_block`; this module builds the real reference lookups and prints the verdict.

`verify-pending count-since --input <path|-> --since T --n N [--key K]` reads a
JSON array whose elements are times or objects with a time at `K` (default
`createdAt`), prints `{"count", "needed"}` and exits 0 when at least N are
strictly after T, 75 ("not yet", never a failure) when fewer are, and 2 on bad input.

`verify-pending run --host H [--repo SLUG] [--issue N] [--report]` (and `just verify H [args...]`,
which passes the rest through) runs, for every project in the fleet registry, the read-only checks of the open `needs-verification` issues that are due on
host H (issue 630). The contract of each project is read at the integration branch commit
`origin` lists, never the checkout; `--repo` keeps the one project whose tracker repository is
SLUG and `--issue` keeps one issue number in every project it runs over, as that project's tracker
writes it (the two are independent, P14, and both may be given); `--report` (P11) prints what is
due and posts, labels, files and runs nothing. Stdout is one `json.dumps(line, sort_keys=True)` per
line, each `{repo, issue, check, ac, state, reason}`, with `issue`, `check` and `ac` null for a
project or issue level line. The states are `due`, `pending`, `pass`, `fail`, `hit`, `miss`, `expired`,
`rejected`, `closed` and `skipped`; the reasons are closed (`due`, `changed`, `unchanged`,
`resolved`, `verified`, `not_verified`, `not_this_host`, `lost_contest`, `owner_check`,
`effects_live`, `effects_paid`, `command_not_verification`, `not_yet`, `timeout`,
`exit_unexpected`, `fail_ask`, `no_block`, `block_invalid`, `block_changed`, `project_unresolved`,
`tracker_not_github`, `forge_error`, `runner_untrusted`, `owner_asked`, `owner_waiting`,
`owner_ambiguous`, `owner_answered`, `owner_waived`, plus the `when` reasons that name what is
awaited). The `ask`, `act`, `live` and `paid` checks and the `on_fail: ask` and `on_expire: ask`
decisions reach the owner through the prompts of `agent_tools.verify_owner`.
A project that cannot be read is a `skipped` line with reason `project_unresolved`, one whose
tracker is not GitHub is `tracker_not_github` (both omitted when `--repo` is given), and a forge
failure while listing is `forge_error`. A write pass whose `gh` account the forge would not label
`OWNER` or `MEMBER` (it could not read back its own markers) is a `runner_untrusted` line, written
before any write or run. Exit 1 when any line is a `forge_error` or `runner_untrusted`, 2 on a usage
error (a host that is not a hostname, a `--repo` no project registers, a refused registry) and
otherwise 0, including with no forge credential: that prints `verify-pending: no-forge-credential`
on stderr, nothing on stdout, and makes no other `gh` call.

`verify-pending approve --repo OWNER/NAME --all-live` (both required; issue 631) ticks the `Run it`
box of every live, unconsumed `approve` prompt of the repository's open `needs-verification`
issues whose check has `effects: live`, and never a `paid` one. It reads every page of issues and
every comment of each before the first edit, and ends with `forge_error` rather than act on an
incomplete listing. Stdout is one `json.dumps(line, sort_keys=True)` per prompt ticked, each
`{repo, issue, check, ac, comment, state, reason}`; a second call ticks nothing. Exit 1 when a line
is a `forge_error` or `runner_untrusted` (the `gh` account could not read its own markers), 2 when
`--repo` is not `owner/name` or an argument is missing, otherwise 0. Only the host a prompt names
runs the command, and only when the prompt's digest still matches it: the tick only permits a run,
and the runner still consumes it on the named host. An issue with more comments than the listing
returned is read from the REST listing.
"""

import argparse
import json
import os
import subprocess
import sys

from collections.abc import Collection
from pathlib import Path

from agent_tools import agent_platform, verify_exec, verify_run
from agent_tools.claims import forge_markers
from agent_tools.claims.forge_markers import ForgeError
from agent_tools.claims.owner_actions import SLUG_PATTERN
from agent_tools.resolve_project import ContractError, resolve
from agent_tools.verify_block import HOST, SHA, count_after, count_since, lint_block, parse_block

GIT_TIMEOUT = 60


def git_ok(root: str, *args: str) -> bool:
    """True when `git -C root args` exits 0; raises OSError, SubprocessError or ValueError when git cannot run."""
    return subprocess.run(["git", "-C", root, *args], capture_output=True, timeout=GIT_TIMEOUT,
                          env=verify_exec.child_env()).returncode == 0


def git_blob(root: str, spec: str) -> bool:
    """True when `spec` names a blob; a directory or a missing path is not one."""
    result = subprocess.run(["git", "-C", root, "cat-file", "-t", spec], capture_output=True, timeout=GIT_TIMEOUT,
                            env=verify_exec.child_env())
    return result.returncode == 0 and result.stdout.strip() == b"blob"


def git_object(root: str, sha: str, path: str | None) -> tuple[str, str]:
    """`(commit_state, path_state)` of `sha` (and `path` at it) in the repository at `root`."""
    try:
        if not git_ok(root, "cat-file", "-e", f"{sha}^{{commit}}"):
            return "absent", "unknown"
        if path is None:
            return "present", "unknown"
        return ("present", "present") if git_blob(root, f"{sha}:{path}") else ("present", "absent")
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown", "unknown"


def git_script(root: str, sha: str, path: str) -> tuple[str, str]:
    """`(commit_state, path_state)` of a script: only an executable file (mode 100755) is `"present"`."""
    try:
        if not git_ok(root, "cat-file", "-e", f"{sha}^{{commit}}"):
            return "absent", "unknown"
        result = subprocess.run(
            ["git", "-C", root, "ls-tree", "-z", "--full-tree", sha, "--", path],
            capture_output=True, timeout=GIT_TIMEOUT, env=verify_exec.child_env(),
        )
    except (OSError, subprocess.SubprocessError, ValueError):
        return "unknown", "unknown"
    if result.returncode != 0:
        return "present", "unknown"
    for entry in result.stdout.split(b"\0"):
        meta, _, name = entry.partition(b"\t")
        if name != path.encode():
            continue  # only the exact path counts, never a directory prefix or a pattern match
        mode = meta.split(b" ")[0]
        if mode == b"100755":
            return "present", "present"
        # A plain file lacks the executable bit; a directory, symbolic link or submodule is no file.
        return "present", "not_executable" if mode == b"100644" else "absent"
    return "present", "absent"


class CliReferences:
    """The real D9 lookups: the resolved project contract and git objects."""

    def __init__(self, root: str | None):
        self.root = root
        self.commands: set | None = None
        self.resolved = False

    def command(self, command_id: str) -> str:
        if self.root is None:
            return "unknown"
        if not self.resolved:
            self.resolved = True
            try:
                self.commands = set(resolve(self.root)["bindings"]["commands"])
            except ContractError:
                self.commands = None
        if self.commands is None:
            return "unknown"
        return "present" if command_id in self.commands else "absent"

    def script(self, path: str, sha: str) -> tuple[str, str]:
        if self.root is None:
            return "unknown", "unknown"
        return git_script(self.root, sha, path)

    def flake(self, merge: str) -> tuple[str, str] | None:
        if self.root is None:
            return None
        return git_object(self.root, merge, "flake.nix")


class PinnedReferences:
    """The lint's lookups for the runner: the snapshot's commands and git objects at pinned commits.

    It never reads the checkout's working tree or contract file; a commit the checkout lacks is
    fetched from `origin` first (P17).
    """

    def __init__(self, root: Path, commands: Collection[str]):
        self.root = root
        self.commands = set(commands)

    def command(self, command_id: str) -> str:
        return "present" if command_id in self.commands else "absent"

    def script(self, path: str, sha: str) -> tuple[str, str]:
        verify_exec.ensure_commit(self.root, sha)
        return git_script(str(self.root), sha, path)

    def flake(self, merge: str) -> tuple[str, str] | None:
        verify_exec.ensure_commit(self.root, merge)
        return git_object(str(self.root), merge, "flake.nix")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="verify-pending")
    commands = parser.add_subparsers(dest="command", required=True)
    lint = commands.add_parser("lint", help="check a verify block")
    lint.add_argument("--input", required=True, help="a hold comment or JSON block; - reads stdin")
    lint.add_argument("--repo-root", help="a git work tree, to check command and script references")
    lint.add_argument("--code-unmet", action="append", default=[], metavar="ID", help="an acceptance criterion unmet in code")
    lint.add_argument("--pr-workflow", action="append", default=[], metavar="NAME", help="a CI workflow that runs on the pull request")
    lint.add_argument("--pr-head", help="the pull request head sha")
    lint.add_argument("--pr-branch", help="the pull request branch")
    lint.add_argument("--blocks", action="append", default=[], metavar="ISSUE", help="an issue this one blocks")
    since = commands.add_parser("count-since", help="count times after a moment; exit 75 when fewer than --n")
    since.add_argument("--input", required=True, help="a JSON array of times or of objects; - reads stdin")
    since.add_argument("--since", required=True, help="the moment, an ISO 8601 time with a UTC offset")
    since.add_argument("--n", required=True, type=int, help="how many times are needed")
    since.add_argument("--key", default="createdAt", help="the member of an object element that holds its time")
    run = commands.add_parser("run", help="run this host's due read-only checks across the fleet")
    run.add_argument("--host", required=True, help="the host this run is on")
    run.add_argument("--repo", help="only the project whose tracker repository is this owner/name")
    run.add_argument("--issue", type=int, help="only this issue number, in every project the run covers")
    run.add_argument("--report", action="store_true", help="print what is due and run nothing")
    approve = commands.add_parser("approve", help="tick the live approve prompts of one repository")
    approve.add_argument("--repo", required=True, help="the tracker repository, owner/name")
    approve.add_argument("--all-live", action="store_true", required=True, help="tick every live prompt")
    return parser


def read_input(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def run_lint(args: argparse.Namespace) -> int:
    if args.pr_head is not None and not SHA.fullmatch(args.pr_head):
        print(f"verify-pending: --pr-head {args.pr_head} is not a 40-character lowercase hex sha", file=sys.stderr)
        return 2
    if args.pr_workflow and args.pr_head is None and args.pr_branch is None:
        print("verify-pending: --pr-workflow needs --pr-head or --pr-branch", file=sys.stderr)
        return 2
    root = None
    if args.repo_root is not None:
        root = os.path.abspath(args.repo_root)
        try:
            is_repo = git_ok(root, "rev-parse", "--git-dir")
        except (OSError, subprocess.SubprocessError, ValueError):
            is_repo = False
        if not is_repo:
            print(f"verify-pending: --repo-root {args.repo_root} is not a git work tree", file=sys.stderr)
            return 2
    try:
        text = read_input(args.input)
    except (OSError, UnicodeDecodeError) as error:
        print(f"verify-pending: cannot read {args.input}: {error}", file=sys.stderr)
        return 2
    block, parse_errors = parse_block(text)
    if parse_errors:
        verdict = {"ok": False, "errors": parse_errors, "warnings": []}
    else:
        verdict = lint_block(
            block, refs=CliReferences(root), code_unmet=args.code_unmet, pr_workflows=args.pr_workflow,
            pr_head=args.pr_head, pr_branch=args.pr_branch, blocks=args.blocks,
        )
    print(json.dumps(verdict, sort_keys=True))
    return 0 if verdict["ok"] else 1


def run_count_since(args: argparse.Namespace) -> int:
    try:
        elements = json.loads(read_input(args.input))
        if not isinstance(elements, list):
            raise ValueError("input is not a JSON array")
        stamps = [element[args.key] if isinstance(element, dict) else element for element in elements]
        code = count_since(stamps, args.since, args.n)
        count = count_after(stamps, args.since)
    except KeyError as error:
        print(f"verify-pending: an element has no {error} member", file=sys.stderr)
        return 2
    except (OSError, ValueError, RecursionError) as error:
        print(f"verify-pending: count-since: {error}", file=sys.stderr)
        return 2
    print(json.dumps({"count": count, "needed": args.n}, sort_keys=True))
    return code


def skipped(repo: str, reason: str) -> dict:
    return {"repo": repo, "issue": None, "check": None, "ac": None, "state": "skipped", "reason": reason}


def run_run(args: argparse.Namespace) -> int:
    if not HOST.fullmatch(args.host):
        print(f"verify-pending: --host {args.host} is not a hostname", file=sys.stderr)
        return 2
    if not forge_markers.logged_in():
        print("verify-pending: no-forge-credential", file=sys.stderr)
        return 0
    try:
        registry = agent_platform.read_registry()
    except agent_platform.PlatformManifestError as error:
        print(f"verify-pending: the fleet registry is refused: {error.repair_id}", file=sys.stderr)
        return 2
    lines: list[dict] = []
    matched = False
    for entry in registry:
        try:
            with verify_exec.project_source(entry) as source:
                snapshot = source.snapshot
                bindings = snapshot["bindings"]
                tracker = bindings["tracker"]
                if tracker.get("kind") != "github":
                    if args.repo is None:
                        lines.append(skipped(entry["project_id"], "tracker_not_github"))
                    continue
                if args.repo is not None and tracker.get("repo_slug") != args.repo:
                    continue
                matched = True
                slug = tracker["repo_slug"]
                project = verify_run.Project(entry["project_id"], slug, Path(entry["root"]),
                                             source.contract_root, source.commit, bindings)
                refs = PinnedReferences(Path(entry["root"]), bindings["commands"])
                try:
                    lines.extend(verify_run.pass_repo(project, args.host, refs, issue=args.issue,
                                                      report=args.report))
                except ForgeError:
                    lines.append(skipped(slug, "forge_error"))
        except verify_exec.SourceError:
            if args.repo is None:
                lines.append(skipped(entry["project_id"], "project_unresolved"))
    if args.repo is not None and not matched:
        print(f"verify-pending: {args.repo} is not a registered project", file=sys.stderr)
        return 2
    for line in lines:
        print(json.dumps(line, sort_keys=True))
        if line["reason"] == "runner_untrusted":
            print(f"verify-pending: {line['repo']}: the gh account is neither the repository owner nor an "
                  "organization member, so the markers it writes would be invisible to it; "
                  "run `gh auth login` as one", file=sys.stderr)
    return 1 if any(line["reason"] in ("forge_error", "runner_untrusted") for line in lines) else 0


def run_approve(args: argparse.Namespace) -> int:
    if not SLUG_PATTERN.fullmatch(args.repo):
        print(f"verify-pending: --repo {args.repo} is not owner/name", file=sys.stderr)
        return 2
    try:
        lines = verify_run.approve_all_live(args.repo)
    except ForgeError:
        lines = [{**skipped(args.repo, "forge_error"), "comment": None}]
    for line in lines:
        print(json.dumps(line, sort_keys=True))
    return 1 if any(line["reason"] in ("forge_error", "runner_untrusted") for line in lines) else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "count-since":
        return run_count_since(args)
    if args.command == "approve":
        return run_approve(args)
    return run_run(args) if args.command == "run" else run_lint(args)


if __name__ == "__main__":
    sys.exit(main())
