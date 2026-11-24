"""router: the routed set of one change at one stage, computed with no model and no network.

    router --repo-root <abs> --stage <stage> (--path <p>... | --diff <range>) [--platform-standards <abs>]

At `planning` and `plan review` the change is its `--path` arguments; from `building` on it is the
paths of `--diff <range>`. Prints one JSON line (`schema_version` 1) naming files, never pasting
them: the bar, the stack shards the extensions choose, the project shards whose `governs` globs
match, the stage's hint file, the records the changed files cite, a one-line index of the records
of each matching context-map area, each shard's rule ids, the platform revision and the total
size in bytes. A wide change is never cut. Exit 0 with that line, 2 with one `router: <reason>`
line on stderr and nothing on stdout for a misuse.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path, PurePosixPath

from agent_tools.delivery import hint_phases, routing
from agent_tools.delivery.context_map_lint import CITATION_RE
from agent_tools.delivery.rule_ids import rule_headings
from agent_tools.project_contract import agent_platform

COMMAND = "router"
SCHEMA_VERSION = 1
PATH_STAGES = ("planning", "plan review")
GIT_TIMEOUT = 60


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


def diff_paths(root: Path, change: str) -> list[str]:
    if change.startswith("-"):
        raise Misuse(f"--diff must be a revision range: {change!r}")
    try:
        done = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", "-z", "--no-renames", change, "--"],
            capture_output=True, stdin=subprocess.DEVNULL, timeout=GIT_TIMEOUT)
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
        "platform_revision": revision["rev"] if revision else None,
        "shards": shards, "hint": hint, "must_read": required, "index": index,
        "index_bytes": index_size, "total_bytes": total}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog=COMMAND)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--stage", required=True, choices=hint_phases.HINT_STAGES)
    parser.add_argument("--path", action="append")
    parser.add_argument("--diff")
    parser.add_argument("--platform-standards")
    args = parser.parse_args(argv)
    root = Path(args.repo_root)
    platform_dir = (Path(args.platform_standards) if args.platform_standards
                    else agent_platform.standards_dir())
    try:
        for name, path in (("--repo-root", root), ("--platform-standards", platform_dir)):
            if not path.is_absolute():
                raise Misuse(f"{name} must be absolute: {path}")
            if not path.is_dir():
                raise Misuse(f"not a directory: {path}")
        doc = route(args, root, platform_dir)
    except (Misuse, ValueError, OSError) as error:
        print(f"{COMMAND}: {error}", file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(doc, sort_keys=True, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
