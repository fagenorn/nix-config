"""Narrow read-only repository inspection for the issue #79 prototype."""

from __future__ import annotations

import hashlib
import re
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from model import Evidence, aggregate_fingerprint, evidence_for_tracked_group, tracked_group


TARGETED_IGNORED = (
    ".agents",
    ".claude/skills",
    ".claude/hints",
    ".claude/rules",
    ".claude/settings.local.json",
    ".codex",
    ".superpowers",
    "AGENTS.md",
    "CLAUDE.md",
    ".mcp.json",
)

TARGETED_UNTRACKED = (
    ".agents",
    ".claude",
    ".codex",
    ".out-of-scope",
    "AGENTS.md",
    "CLAUDE.md",
    ".mcp.json",
)

SECRET_MARKERS = {
    ".env",
    "credential",
    "credentials",
    "private",
    "secret",
    "secrets",
    "token",
    "tokens",
}


def run_git(root: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        check=True,
        capture_output=True,
    )
    return result.stdout


def nul_paths(payload: bytes) -> list[str]:
    return [item.decode("utf-8", errors="surrogateescape") for item in payload.split(b"\0") if item]


def safe_to_hash(path: str) -> bool:
    lowered_parts = [part.lower() for part in Path(path).parts]
    return not any(
        part.startswith(".env") or any(marker in part for marker in SECRET_MARKERS)
        for part in lowered_parts
    )


def safe_file_fingerprint(root: Path, path: str) -> str | None:
    if not safe_to_hash(path):
        return None
    allowed = path == ".claude/settings.local.json" or path.startswith(
        (".claude/specs/", ".claude/plans/", ".claude/hints/", ".claude/skills/")
    )
    candidate = root / path
    if not allowed or not candidate.is_file() or candidate.is_symlink():
        return None
    digest = hashlib.sha256()
    with candidate.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def parse_index(root: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for record in run_git(root, "ls-files", "-s", "-z").split(b"\0"):
        if not record:
            continue
        metadata, raw_path = record.split(b"\t", 1)
        _mode, object_id, _stage = metadata.decode("ascii").split()
        path = raw_path.decode("utf-8", errors="surrogateescape")
        entries.append((path, object_id))
    return entries


def project_id_from_remote(remote: str) -> str:
    normalized = remote.removesuffix(".git").rstrip("/")
    if ":" in normalized and not normalized.startswith(("http://", "https://", "ssh://")):
        normalized = normalized.split(":", 1)[1]
    else:
        normalized = urlparse(normalized).path.lstrip("/")
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug or "nix-config"


def ignored_evidence(root: Path) -> list[Evidence]:
    paths = nul_paths(
        run_git(
            root,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
            "--",
            *TARGETED_IGNORED,
        )
    )
    groups: dict[str, list[str]] = defaultdict(list)
    for path in paths:
        if path == ".claude/settings.local.json":
            groups[path].append(path)
        elif path.startswith(".superpowers/"):
            groups[".superpowers/**"].append(path)
        elif path.startswith(".claude/skills/"):
            groups[".claude/skills/**"].append(path)
        elif path.startswith(".claude/hints/"):
            groups[".claude/hints/**"].append(path)
        else:
            groups[path].append(path)

    evidence: list[Evidence] = []
    for group, members in sorted(groups.items()):
        if group == ".claude/settings.local.json":
            evidence.append(
                Evidence(
                    group,
                    "targeted-ignored",
                    "native-policy-legacy",
                    "generate-projection",
                    ".agents/adapters/claude/** + .claude/settings.json",
                    len(members),
                    safe_file_fingerprint(root, group),
                    "Behavior-changing ignored native policy must become canonical adapter input and a tracked projection.",
                )
            )
        elif group == ".superpowers/**":
            evidence.append(
                Evidence(
                    group,
                    "targeted-ignored-metadata-only",
                    "runtime-residue",
                    None,
                    ".agents/runtime/** for future runs; existing residue remains state-governed",
                    len(members),
                    None,
                    "Names/counts only: review packages, ledgers, locks, and handoffs are already covered by ignored runtime and doctor cleanup rules.",
                )
            )
        else:
            fingerprints = [(path, safe_file_fingerprint(root, path) or "metadata-only") for path in members]
            evidence.append(
                Evidence(
                    group,
                    "targeted-ignored",
                    "canonical-import-candidate",
                    "move-canonical",
                    group.replace(".claude/", ".agents/"),
                    len(members),
                    hashlib.sha256(repr(fingerprints).encode("utf-8")).hexdigest(),
                    "Known ignored agent-development source; contents are considered only through the explicit target path.",
                )
            )
    return evidence


def worktree_evidence(root: Path) -> tuple[Evidence | None, list[str]]:
    records = run_git(root, "worktree", "list", "--porcelain").decode("utf-8").splitlines()
    paths = [line.removeprefix("worktree ") for line in records if line.startswith("worktree ")]
    legacy = [path for path in paths if "/.claude/worktrees/" in path]
    if not legacy:
        return None, []
    return (
        Evidence(
            ".claude/worktrees/**",
            "git-worktree-metadata-only",
            "runtime-residue",
            None,
            ".agents/runtime/worktrees/** for future worktrees",
            len(legacy),
            None,
            "Registered worktree paths only; contents are never traversed and existing worktrees remain governed by state-based cleanup.",
        ),
        legacy,
    )


def inspect(root_arg: str) -> dict[str, Any]:
    root = Path(root_arg).resolve()
    top = Path(run_git(root, "rev-parse", "--show-toplevel").decode("utf-8").strip())
    base_revision = run_git(top, "rev-parse", "HEAD").decode("ascii").strip()
    remote = run_git(top, "remote", "get-url", "origin").decode("utf-8").strip()

    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for path, object_id in parse_index(top):
        group = tracked_group(path)
        if group:
            grouped[group].append((path, object_id))
    evidence = [evidence_for_tracked_group(group, entries) for group, entries in sorted(grouped.items())]
    evidence.extend(ignored_evidence(top))

    worktrees, legacy_worktree_paths = worktree_evidence(top)
    if worktrees:
        evidence.append(worktrees)

    untracked_agent_paths = nul_paths(
        run_git(
            top,
            "ls-files",
            "--others",
            "--exclude-standard",
            "-z",
            "--",
            *TARGETED_UNTRACKED,
        )
    )
    status_paths = nul_paths(run_git(top, "status", "--porcelain=v1", "-z", "--untracked-files=all"))
    legacy_temp_paths = sorted(
        record[3:] for record in status_paths if len(record) > 3 and re.fullmatch(r"\.tmp-workflow-state-[^/]+\.json", record[3:])
    )
    if legacy_temp_paths:
        evidence.append(
            Evidence(
                ".tmp-workflow-state-*.json",
                "untracked-metadata-only",
                "runtime-residue",
                None,
                ".agents/runtime/state/** for future runs",
                len(legacy_temp_paths),
                None,
                "Legacy scratch paths are already covered by ignored runtime; contents are not read.",
            )
        )

    if untracked_agent_paths:
        fingerprints = [
            (path, safe_file_fingerprint(top, path)) for path in untracked_agent_paths
        ]
        complete_fingerprint = (
            aggregate_fingerprint(
                [(path, fingerprint) for path, fingerprint in fingerprints if fingerprint]
            )
            if all(fingerprint for _, fingerprint in fingerprints)
            else None
        )
        evidence.append(
            Evidence(
                "untracked agent-development inputs",
                "untracked-explicit-paths",
                "durable-artifact",
                "move-canonical",
                ".agents/artifacts/**",
                len(untracked_agent_paths),
                complete_fingerprint,
                "These paths overlap inspected adoption sources/destinations and block readiness until committed, moved, or otherwise reconciled.",
            )
        )

    evidence.sort(key=lambda item: item.path)
    return {
        "root": str(top),
        "base_revision": base_revision,
        "remote": remote,
        "project_id": project_id_from_remote(remote),
        "evidence": evidence,
        "untracked_agent_paths": sorted(untracked_agent_paths),
        "blockers": [],
        "legacy_worktree_paths": legacy_worktree_paths,
    }
