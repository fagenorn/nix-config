"""fallback-audit: the checks behind #130's "no fallback ladder remains" (P1) and
"traces show zero removed-fallback executions" (P4), issue 579 P8.

`ladders` reports every tracked workflow-entry file that still names a removed
resolution route. `traces` reports every shell call recorded after an instant
that ran one. Both are read-only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Any

from agent_tools import agent_costs, agent_platform, resolve_project

ENTRY_PATHSPECS = (
    "home/common/agent-skills/skills",
    "home/common/agent-guidance",
    "python/agent_tools",
    "AGENTS.md",
    "CLAUDE.md",
    ".claude",
    ".agents/instructions",
    ".codex",
)
SELF_PATH = "python/agent_tools/fallback_audit.py"
EXCLUDED_DIRECTORIES = ("tests", "evals")

# The 2026-08-20 fallback inventory's removable cluster, plus the bridge paths.
INVENTORY_MARKERS = (
    ("resolve-bindings", "resolve-bindings"),
    ("legacy-skills-config", "skills.config.json"),
    ("bare-name-fallback", "if the bare name does not resolve"),
    ("release-deploy-inspect", "release deploy inspect"),
    ("release-bridge", "release_bridge"),
    ("bindings-deploy", "bindings.deploy"),
    ("manifest-sniffing", "else the manifest"),
)

# Each row exempts every hit of exactly that marker in exactly that path,
# because the hit is not a resolution route. Nothing else is exempt. The rows
# belong to this repository: they apply only to a root whose contract declares
# NON_LADDER_PROJECT_ID, so another project's audit neither inherits them nor
# reports them as stale.
NON_LADDER_PROJECT_ID = "fagenorn/nix-config"
NON_LADDER_SITES = (
    ("python/agent_tools/adopt_inspection.py", "legacy-skills-config",
     "adoption classifies a legacy store it finds in a project being adopted; "
     "detection, not a route"),
    ("python/agent_tools/review_issue100.py", "resolve-bindings",
     "digest-pinned retained review record of issue 100"),
    ("python/agent_tools/review_task7.py", "legacy-skills-config",
     "digest-pinned retained review record of issue 234 Task 7"),
    ("home/common/agent-skills/skills/ship-release/CHANGELOG.md", "bindings-deploy",
     "release history, not an instruction"),
)

CODEX_SHELL_TOOLS = ("shell", "shell_command", "exec_command", "local_shell")
TRACE_MARKER_IDS = ("release-deploy-inspect", "resolve-bindings", "legacy-skills-config")
UNREADABLE_MARKER_ID = "unreadable_input"
REMOVAL_SUBJECT_KINDS = ("project_file", "platform_behavior")
EXCERPT_CHARACTERS = 200
PROBE_TIMEOUT_SECONDS = 60


class AuditUsageError(Exception):
    """A condition that is the caller's or the host's, not a finding; main exits 2."""


def _emit(report: dict[str, Any]) -> None:
    print(json.dumps(report, sort_keys=True))


def _marker_literals(manifest_path: Path | None, root: Path) -> list[tuple[str, str]]:
    markers = list(INVENTORY_MARKERS)
    if manifest_path is None:
        candidate = root / "home/common/agent-skills/platform-manifest.json"
        manifest_path = candidate if candidate.is_file() else None
    if manifest_path is not None:
        try:
            manifest, _ = agent_platform.load_manifest(manifest_path)
        except agent_platform.PlatformManifestError as error:
            raise AuditUsageError(f"the manifest does not load: {error}") from None
        for entry in manifest["removals"]:
            if entry["kind"] in REMOVAL_SUBJECT_KINDS and entry["subject"]:
                markers.append((entry["id"], entry["subject"]))
    return markers


def _entry_files(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--", *ENTRY_PATHSPECS],
        cwd=root, capture_output=True, check=False)
    if result.returncode != 0:
        raise AuditUsageError(f"git ls-files failed in {root}")
    paths = sorted({p.decode("utf-8", "surrogateescape")
                    for p in result.stdout.split(b"\0") if p})
    return [p for p in paths
            if p != SELF_PATH
            and not set(Path(p).parts[:-1]) & set(EXCLUDED_DIRECTORIES)]


def _scan(root: Path, markers: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Every marker hit, plus one `unreadable_input` finding for each tracked
    entry file that could not be read: a scan that skipped a file is not clean."""
    hits: list[dict[str, Any]] = []
    for relative in _entry_files(root):
        try:
            text = (root / relative).read_text(encoding="utf-8", errors="replace")
        except OSError:
            hits.append({"path": relative, "line": None, "marker_id": UNREADABLE_MARKER_ID})
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            seen: set[str] = set()
            for marker_id, literal in markers:
                if literal in line and marker_id not in seen:
                    seen.add(marker_id)
                    hits.append({"path": relative, "line": number, "marker_id": marker_id})
    return hits


def _probe() -> dict[str, Any]:
    """`resolve-project resolve` on a fresh git repository must refuse, closed."""
    with tempfile.TemporaryDirectory(prefix="fallback-audit-probe-") as scratch:
        try:
            subprocess.run(["git", "init", "--quiet", scratch], check=True,
                           capture_output=True)
            result = subprocess.run(
                ["resolve-project", "resolve", "--repo-root", scratch],
                capture_output=True, text=True, check=False,
                timeout=PROBE_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError):
            return {"code": None, "exit": None}
    code = None
    try:
        payload = json.loads(result.stdout)
        candidate = payload["error"]["code"]
        code = candidate if isinstance(candidate, str) else None
    except (ValueError, KeyError, TypeError):
        pass
    return {"code": code, "exit": result.returncode}


def _declared_project_id(root: Path) -> str | None:
    """The `project.id` the root's contract declares, or None when it declares
    none it can be read as: an unreadable or malformed contract owns no exemption."""
    try:
        source = resolve_project.load_contract(root)
    except resolve_project.ContractError:
        return None
    return resolve_project.declared_facts(source)["project_id"]


def _exemption_sites(root: Path) -> tuple[tuple[str, str, str], ...]:
    return NON_LADDER_SITES if _declared_project_id(root) == NON_LADDER_PROJECT_ID else ()


def ladders(args: argparse.Namespace) -> int:
    root = Path(args.repo_root).resolve()
    markers = _marker_literals(Path(args.manifest) if args.manifest else None, root)
    sites = _exemption_sites(root)
    exempt_rows = {(path, marker_id): reason for path, marker_id, reason in sites}
    findings: list[dict[str, Any]] = []
    exempt: list[dict[str, Any]] = []
    matched: set[tuple[str, str]] = set()
    for hit in _scan(root, markers):
        key = (hit["path"], hit["marker_id"])
        if key in exempt_rows:
            matched.add(key)
            exempt.append({**hit, "reason": exempt_rows[key]})
        else:
            findings.append(hit)
    for path, marker_id, _reason in sites:
        if (path, marker_id) not in matched:
            findings.append({"path": path, "line": None,
                             "marker_id": f"stale_exemption:{marker_id}"})
    probe = _probe()
    closed = probe["exit"] == 2 and probe["code"] in resolve_project.ERROR_CODES
    clean = not findings and closed
    _emit({"findings": findings, "exempt": exempt, "probe": probe, "clean": clean})
    return 0 if clean else 1


def _argv_text(command: Any, fallback: str) -> str:
    """An argv command as the one line a shell would see; anything else as given."""
    if isinstance(command, list) and command and all(isinstance(part, str) for part in command):
        return " ".join(command)
    return fallback


def _calls(record: dict[str, Any]) -> list[tuple[str, str]]:
    """The (source, text) of each shell call a transcript record holds."""
    calls: list[tuple[str, str]] = []
    if record.get("type") == "assistant":
        message = record.get("message")
        content = message.get("content") if isinstance(message, dict) else None
        for item in content if isinstance(content, list) else []:
            if (isinstance(item, dict) and item.get("type") == "tool_use"
                    and item.get("name") == "Bash"):
                tool_input = item.get("input")
                command = tool_input.get("command") if isinstance(tool_input, dict) else None
                if isinstance(command, str):
                    calls.append(("claude", command))
    elif record.get("type") == "response_item":
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return calls
        kind, name = payload.get("type"), payload.get("name")
        if kind == "function_call" and name in CODEX_SHELL_TOOLS:
            arguments = payload.get("arguments")
            if isinstance(arguments, str):
                try:
                    decoded = json.loads(arguments)
                except ValueError:
                    decoded = None
                command = decoded.get("command") if isinstance(decoded, dict) else None
                calls.append(("codex", _argv_text(command, arguments)))
        elif kind == "custom_tool_call" and name == "exec":
            if isinstance(payload.get("input"), str):
                calls.append(("codex", payload["input"]))
        elif kind == "local_shell_call" and "action" in payload:
            action = payload["action"]
            command = action.get("command") if isinstance(action, dict) else None
            calls.append(("codex", _argv_text(command, json.dumps(action))))
    return calls


def _transcripts(root: Path) -> list[Path]:
    return sorted(root.rglob("*.jsonl")) if root.is_dir() else []


def traces(args: argparse.Namespace) -> int:
    try:
        since = agent_costs.parse_rfc3339_utc(args.since)
    except ValueError:
        print("fallback-audit: --since must be RFC 3339 with an offset", file=sys.stderr)
        return 2
    literals = dict(INVENTORY_MARKERS)
    wanted = [(marker_id, literals[marker_id]) for marker_id in TRACE_MARKER_IDS]
    executions: list[dict[str, Any]] = []
    files_read = 0
    skipped = 0
    for source_root in (Path(args.claude_root).expanduser(), Path(args.codex_root).expanduser()):
        for path in _transcripts(source_root):
            try:
                if path.stat().st_mtime < since.timestamp():
                    continue
                handle = path.open(encoding="utf-8", errors="replace")
            except OSError as error:
                print(f"fallback-audit: cannot open {path}: {error}", file=sys.stderr)
                return 2
            files_read += 1
            with handle:
                try:
                    for raw in handle:
                        try:
                            record = json.loads(raw)
                        except ValueError:
                            skipped += 1
                            continue
                        if not isinstance(record, dict):
                            skipped += 1
                            continue
                        calls = _calls(record)
                        if not calls:
                            continue
                        try:
                            moment = agent_costs.parse_rfc3339_utc(record.get("timestamp"))
                        except ValueError:
                            skipped += 1
                            continue
                        if moment <= since:
                            continue
                        for source, text in calls:
                            for marker_id, literal in wanted:
                                if literal in text:
                                    executions.append({
                                        "source": source, "path": str(path),
                                        "timestamp": record["timestamp"],
                                        "marker_id": marker_id,
                                        "excerpt": text[:EXCERPT_CHARACTERS]})
                except OSError as error:
                    print(f"fallback-audit: cannot read {path}: {error}", file=sys.stderr)
                    return 2
    _emit({"since": args.since, "executions": executions,
           "files_read": files_read, "skipped_lines": skipped})
    return 1 if executions else 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fallback-audit", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    ladder = commands.add_parser("ladders", help="report remaining fallback-ladder markers")
    ladder.add_argument("--repo-root", default=".")
    ladder.add_argument("--manifest")
    ladder.set_defaults(handler=ladders)
    trace = commands.add_parser("traces", help="report removed-fallback executions in transcripts")
    trace.add_argument("--since", required=True)
    trace.add_argument("--claude-root", default="~/.claude/projects")
    trace.add_argument("--codex-root", default="~/.codex/sessions")
    trace.set_defaults(handler=traces)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return args.handler(args)
    except AuditUsageError as error:
        print(f"fallback-audit: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
