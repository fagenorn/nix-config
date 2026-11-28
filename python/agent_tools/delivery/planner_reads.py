"""The files a run's planner sessions read (D8), found in the Claude Code transcripts the sessions left.

A planner session is one named by a record `sessions/<step>.<visit>*.json` of a step whose role is `planner` in the
run's own procedure copy. Its transcript is the first `<projects root>/*/<session>.jsonl` that exists, where the
roots are `$CLAUDE_CONFIG_DIR/projects` when set, then `<home>/.claude/projects`. A transcript line is JSON whose
`message.content` lists items; an item of type `tool_use` named `Read` carries its path in `input.file_path`. A line
of any other shape is skipped. A session with no transcript adds nothing. Paths are distinct, in first-read order.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_tools.delivery import outline_record


def projects_roots(environ: Mapping[str, str], home: Path) -> tuple[Path, ...]:
    candidates = []
    if environ.get("CLAUDE_CONFIG_DIR"):
        candidates.append(Path(environ["CLAUDE_CONFIG_DIR"]) / "projects")
    candidates.append(Path(home) / ".claude" / "projects")
    roots: list[Path] = []
    for candidate in candidates:
        if all(candidate.resolve() != root.resolve() for root in roots):
            roots.append(candidate)
    return tuple(roots)


def read_files(transcript: Path) -> list[str]:
    paths: list[str] = []
    try:
        lines = Path(transcript).read_text(encoding="utf-8").splitlines()
    except (OSError, ValueError):
        return paths
    for line in lines:
        try:
            content = json.loads(line)["message"]["content"]
        except (ValueError, KeyError, TypeError):
            continue
        if not isinstance(content, list):
            continue
        for item in content:
            if not (isinstance(item, dict) and item.get("type") == "tool_use" and item.get("name") == "Read"):
                continue
            target = item.get("input")
            path = target.get("file_path") if isinstance(target, dict) else None
            if isinstance(path, str) and path not in paths:
                paths.append(path)
    return paths


def _sessions(run_dir: Path) -> list[str]:
    """The sessions of the run's planner steps: procedure order, visit order, each distinct."""
    sessions: list[str] = []
    for step in outline_record.procedure_steps(run_dir).values():
        if step.get("role") != "planner":
            continue
        records = []
        for path in (run_dir / "sessions").glob(f"{step['id']}.*.json"):
            match = re.fullmatch(re.escape(step["id"]) + r"\.([1-9][0-9]*)\..*json", path.name)
            if match:
                records.append((int(match.group(1)), path.name, path))
        for _, _, path in sorted(records):
            try:
                session = json.loads(path.read_text(encoding="utf-8")).get("session")
            except (OSError, ValueError, AttributeError):
                continue
            if isinstance(session, str) and session not in sessions:
                sessions.append(session)
    return sessions


def planner_reads(run_dir: Path, roots: Sequence[Path]) -> list[str]:
    paths: list[str] = []
    for session in _sessions(Path(run_dir)):
        transcript = next((found for root in roots for found in sorted(Path(root).glob(f"*/{session}.jsonl"))
                           if found.is_file()), None)
        if transcript is None:
            continue
        paths += [path for path in read_files(transcript) if path not in paths]
    return paths
