"""router: the routed set of one change at one stage, computed with no model and no network.

    router --repo-root <abs> --stage <stage> (--path <p>... | --diff <range>) [--platform-standards <abs>]
    router <building|final-review> --worktree-path <abs> --integration-branch <name> --branch <name>
        [--platform-standards <abs>]

At `planning` and `plan review` the change is its `--path` arguments; from `building` on it is the
paths of `--diff <range>`. Prints one JSON line (`schema_version` 1) naming files, never pasting
them: the bar, the stack shards the extensions choose, the project shards whose `governs` globs
match, the stage's hint file, the records the changed files cite, a one-line index of the records
of each matching context-map area, each shard's rule ids, the platform revision and the total
size in bytes, and `routed_files`: every file to read, as absolute paths, each shard in order, then
the hint file when it exists, then each must-read record (never an index line). A wide change is
never cut. The engine form (a first argument that is no flag) routes the stage word's stage over
`--diff refs/remotes/origin/<integration-branch>...<head>`, `head` the worktree's HEAD read once as
a full sha; it refuses a `--branch` whose `refs/heads/<branch>` is not that sha, and no unqualified
name reaches Git; both branch names must be literal branch names (`git check-ref-format`), never a revision
expression. Its document also carries `diff` (that range) and `head` (that sha) as members of their own, so a
consumer reads the revision the files were routed for; the flag form's are null. Every Git read is of `--repo-root`'s (or the worktree's) repository, whatever
`GIT_DIR` and its siblings name. Exit 0 with that line, 2 with one `router: <reason>`
line on stderr and nothing on stdout for a misuse.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import NoReturn

from agent_tools.delivery import hint_phases, routing
from agent_tools.delivery.context_map_lint import CITATION_RE
from agent_tools.delivery.issue_setup import REPOSITORY_ENV
from agent_tools.delivery.rule_ids import rule_headings
from agent_tools.project_contract import agent_platform

COMMAND = "router"
SCHEMA_VERSION = 1
PATH_STAGES = ("planning", "plan review")
GIT_TIMEOUT = 60
ENGINE_STAGES: Mapping[str, str] = {"building": "building", "final-review": "final review"}


class Misuse(Exception):
    pass


def regular_size(path: Path) -> int | None:
    return path.stat().st_size if path.is_file() else None


def project_files(root: Path) -> dict[str, bytes]:
    found = {}
    patterns = (f"{routing.LAYER2_DIR}/*.md", routing.CONTEXT_MAP, "docs/areas/*/adr/*.md")
    for pattern in patterns:
        for path in sorted(root.glob(pattern)):
            relative = path.relative_to(root).as_posix()
            if path.is_file() and routing.is_input(relative):
                found[relative] = path.read_bytes()
    return found


def check_path(path: str) -> str:
    pure = PurePosixPath(path)
    if not path or path.startswith("/") or ".." in pure.parts:
        raise Misuse(f"--path must be a relative path without '..': {path!r}")
    return path


def git_read(root: Path, *args: str) -> str:
    """One Git read of `root`'s own repository: the variables that select another one are dropped."""
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(["git", "-C", str(root), *args], capture_output=True,
                              stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        raise Misuse(f"cannot read git {' '.join(args)}: {error}") from error
    if done.returncode != 0:
        reason = " ".join(done.stderr.decode("utf-8", errors="replace").split())
        raise Misuse(f"cannot read git {' '.join(args)}: {reason}")
    return done.stdout.decode("utf-8", errors="replace").strip()


def diff_paths(root: Path, change: str) -> list[str]:
    if change.startswith("-"):
        raise Misuse(f"--diff must be a revision range: {change!r}")
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--no-renames", change, "--"],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT, env=env)
    except (OSError, subprocess.SubprocessError) as error:
        raise Misuse(f"git diff failed: {error}") from error
    if done.returncode != 0:
        reason = done.stderr.decode("utf-8", errors="replace").strip()
        raise Misuse(f"git diff {change} failed: {reason}")
    return [name.decode("utf-8", errors="replace") for name in done.stdout.split(b"\0") if name]


def change_paths(args: argparse.Namespace, root: Path) -> list[str]:
    if args.stage in PATH_STAGES:
        if not args.path or args.diff is not None:
            raise Misuse(f"stage {args.stage!r} takes --path and no --diff")
        paths = [check_path(path) for path in args.path]
    else:
        if args.diff is None or args.path:
            raise Misuse(f"stage {args.stage!r} takes --diff and no --path")
        paths = diff_paths(root, args.diff)
    return sorted(set(paths))


def rules(text: bytes) -> list[str]:
    ids, _ = rule_headings(text.decode("utf-8", errors="replace"))
    return [f"{prefix}{number}" for prefix, number, _ in ids]


def must_read(root: Path, project: routing.Project, paths: list[str]) -> list[dict]:
    known = {r.id: r for area in project.areas for r in area.records}
    cited: set[str] = set()
    for path in paths:
        target = root / path
        if target.is_file():
            text = target.read_text(encoding="utf-8", errors="replace")
            cited.update(f"ADR-{slug}-{number}" for slug, number in CITATION_RE.findall(text))
    records = sorted((known[i] for i in cited if i in known), key=lambda r: r.path)
    return [{"id": r.id, "path": str(root / r.path), "bytes": len(project.files[r.path])}
            for r in records]


def route(args: argparse.Namespace, root: Path, platform_dir: Path) -> dict:
    paths = change_paths(args, root)
    platform = routing.load_platform(platform_dir)
    project = routing.read_project(project_files(root))
    names = sorted({name for path in paths for name in routing.stack_shards(path)})
    shards = [{"layer": "bar", "path": str(platform_dir / routing.BAR),
               "bytes": len(platform.files[routing.BAR]), "rules": rules(platform.files[routing.BAR])}]
    for name in names:
        key = f"{routing.STACKS_DIR}/{name}"
        if key not in platform.files:
            raise ValueError(f"the platform has no {key}")
        shards.append({"layer": "stack", "path": str(platform_dir / key),
                       "bytes": len(platform.files[key]), "rules": rules(platform.files[key])})
    for shard in project.shards:
        if any(routing.glob_matches(g, p) for g in shard.globs for p in paths):
            content = project.files[shard.path]
            shards.append({"layer": "project", "path": str(root / shard.path),
                           "bytes": len(content), "rules": rules(content)})
    hint_path = root / hint_phases.HINT_DIR / hint_phases.hint_file(args.stage)
    size = regular_size(hint_path)
    hint = None if size is None else {"path": str(hint_path), "bytes": size}
    required = must_read(root, project, paths)
    areas = [a for a in project.areas
             if any(routing.glob_matches(g, p) for g in a.globs for p in paths)]
    index = [{"area": a.name, "records": [routing.index_line(r) for r in a.records]} for a in areas]
    index_size = routing.index_bytes(areas)
    revision = agent_platform.platform_revision()
    total = (sum(s["bytes"] for s in shards) + (hint["bytes"] if hint else 0)
             + sum(m["bytes"] for m in required) + index_size)
    return {
        "schema_version": SCHEMA_VERSION, "stage": args.stage,
        "change": {"diff": args.diff, "paths": paths},
        "diff": args.diff, "head": getattr(args, "head", None),
        "platform_revision": revision["rev"] if revision else None,
        "shards": shards, "hint": hint, "must_read": required, "index": index,
        "index_bytes": index_size, "total_bytes": total,
        "routed_files": ([s["path"] for s in shards] + ([hint["path"]] if hint else [])
                         + [m["path"] for m in required])}


class EngineParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        raise Misuse(message)


def check_directory(name: str, path: Path) -> None:
    if not path.is_absolute():
        raise Misuse(f"{name} must be absolute: {path}")
    if not path.is_dir():
        raise Misuse(f"not a directory: {path}")


def engine_form(words: Sequence[str]) -> tuple[argparse.Namespace, Path, str | None]:
    word, flags = words[0], list(words[1:])
    if word not in ENGINE_STAGES:
        raise Misuse(f"unknown stage {word}; one of {', '.join(ENGINE_STAGES)}")
    parser = EngineParser(prog=COMMAND, add_help=False, allow_abbrev=False)
    parser.add_argument("--worktree-path", required=True)
    parser.add_argument("--integration-branch", required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--platform-standards")
    given = parser.parse_args(flags)
    for name in ("integration_branch", "branch"):
        value = getattr(given, name)
        if not value or value.startswith("-"):
            raise Misuse(f"--{name.replace('_', '-')} must be a branch name: {value!r}")
    worktree = Path(given.worktree_path)
    check_directory("--worktree-path", worktree)
    for name, prefix in (("integration_branch", "refs/remotes/origin/"), ("branch", "refs/heads/")):
        try:
            git_read(worktree, "check-ref-format", prefix + getattr(given, name))
        except Misuse:
            raise Misuse(f"--{name.replace('_', '-')} must be a literal branch name: "
                         f"{getattr(given, name)!r}") from None
    head = git_read(worktree, "rev-parse", "--verify", "HEAD")
    tip = git_read(worktree, "rev-parse", "--verify", f"refs/heads/{given.branch}")
    if tip != head:
        raise Misuse(f"branch {given.branch} is at {tip}, the worktree's HEAD is {head}")
    change = f"refs/remotes/origin/{given.integration_branch}...{head}"
    args = argparse.Namespace(stage=ENGINE_STAGES[word], diff=change, path=None, head=head)
    return args, worktree, given.platform_standards


def main(argv: Sequence[str] | None = None) -> int:
    words = list(sys.argv[1:] if argv is None else argv)
    engine = bool(words) and not words[0].startswith("-")
    if not engine:
        parser = argparse.ArgumentParser(prog=COMMAND)
        parser.add_argument("--repo-root", required=True)
        parser.add_argument("--stage", required=True, choices=hint_phases.HINT_STAGES)
        parser.add_argument("--path", action="append")
        parser.add_argument("--diff")
        parser.add_argument("--platform-standards")
        args = parser.parse_args(words)
        root, standards = Path(args.repo_root), args.platform_standards
    try:
        if engine:
            args, root, standards = engine_form(words)
        platform_dir = Path(standards) if standards else agent_platform.standards_dir()
        for name, path in (("--repo-root", root), ("--platform-standards", platform_dir)):
            check_directory(name, path)
        doc = route(args, root, platform_dir)
    except (Misuse, ValueError, OSError) as error:
        print(f"{COMMAND}: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(doc, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
