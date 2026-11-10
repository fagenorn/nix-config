"""Profile the token cost of Workflow runs from their agent transcripts (#715).

Usage: `just agent-run-profile <run-dir>... [--json] [--top N]`, or
`python -m agent_tools.run_profile`. It reads the Workflow run directories given as
arguments and prints phase totals, the costliest agents, label families and a per-issue
table as text or, with `--json`, one JSON document with the keys `incomplete`, `runs`,
`phases`, `agents`, `families`, `issues`. `--top N` (default 15) caps agents and families.

Each run dir holds one `agent-<id>.jsonl` transcript per agent, an optional
`journal.jsonl` naming each agent's phase, label and result, and optional
`agent-<id>.meta.json` files.

`fresh` = input + cache_creation + output tokens. Cache reads are reported
separately (`cache_read`) because they cost about a tenth of a fresh token. Usage is
deduplicated per message id (the per-field maximum) and tool calls per tool_use id.

A label's family drops its numeric parts. For a label in a batch phase (`Intake`,
`Deliver`, `Land`) the first numeric part of the label names the issue; any other agent
takes the first explicit `issue #N` of its first prompt, else its first bare `#N` that is
not a pull request (`PR #N`), skipping the workflow harness's user-request relay. An
agent's model is the meta file's `model`, else the commonest model recorded in its
transcript's assistant messages, else `?`. Issues are keyed by the run's repository slug
from its setup result. An issue is listed only once a `close-out` agent for it returned
`released: true`, and its planner calls count its `plan`, `plan-revise` and
`plan-rules-revise` agents.

A transcript or journal that cannot be read in full (including one holding a line that is
not a JSON object: truncated, not UTF-8) is listed under `incomplete` (a table in text
mode) and on stderr as `incomplete evidence:` lines, the totals omit what could not be
read, and the command exits 1. An absent journal or meta file is normal. Exit 2 is a
usage error or a run directory that does not exist.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

BATCH_PHASES: frozenset[str] = frozenset({"Intake", "Deliver", "Land"})
PLANNER_FAMILIES: frozenset[str] = frozenset({"plan", "plan-revise", "plan-rules-revise"})
USER_RELAY_PREFIX: str = "[Workflow harness — user request]"

_USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens",
                 "cache_read_input_tokens", "output_tokens")


def label_family(label: str) -> str:
    return re.sub(r"-\d+", "", label)


def label_issue(label: str, phase: str) -> int | None:
    if phase in BATCH_PHASES:
        match = re.search(r"-(\d+)", label)
        if match:
            return int(match.group(1))
    return None


def prompt_issue(text: str) -> int | None:
    """The issue a prompt is about: an explicit `issue #N` first, else the first
    bare `#N` that is not a pull request (`PR #N`), whose number is not an issue's."""
    match = (re.search(r"\bissue #(\d+)", text, re.IGNORECASE)
             or re.search(r"(?<!\bPR )(?<!\bpr )#(\d+)", text))
    return int(match.group(1)) if match else None


def _read_jsonl(path: Path) -> tuple[list[dict], str | None]:
    """The dict records of `path` and a read error, if any. The records read before
    an error are kept, so the caller can still report them as incomplete. A line that
    is not a JSON object (truncated, not UTF-8, another JSON type) is skipped but
    counted into the error: its tokens or result are missing from the totals."""
    records: list[dict] = []
    malformed = 0
    first_bad = 0
    os_error: str | None = None
    try:
        with open(path, "rb") as handle:
            for number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                try:
                    # A line cut inside a multibyte character (an agent killed or
                    # still writing) is not JSON either: decode per line.
                    record = json.loads(line.decode("utf-8"))
                except ValueError:  # includes UnicodeDecodeError
                    record = None
                if isinstance(record, dict):
                    records.append(record)
                else:
                    malformed += 1
                    first_bad = first_bad or number
    except OSError as error:
        os_error = f"{type(error).__name__}: {error}"
    problems = ([os_error] if os_error else [])
    if malformed:
        problems.append(f"{malformed} malformed record(s), first at line {first_bad}")
    return records, "; ".join(problems) or None


def _count(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _text_of(message: object) -> str:
    if not isinstance(message, dict):
        return ""
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [block.get("text") for block in content
                 if isinstance(block, dict) and block.get("type") == "text"
                 and isinstance(block.get("text"), str)]
        return "\n".join(parts)
    return ""


def agent_stats(path: Path) -> dict:
    usage_by_id: dict[str, dict[str, int]] = {}
    loose = dict.fromkeys(_USAGE_FIELDS, 0)
    seen_tools: set[str] = set()
    loose_tools = 0
    first_prompt: str | None = None
    models: dict[str, int] = {}
    first_time: datetime | None = None
    last_time: datetime | None = None

    records, read_error = _read_jsonl(path)
    for record in records:
        stamp = _parse_time(record.get("timestamp"))
        if stamp is not None:
            if first_time is None:
                first_time = stamp
            last_time = stamp
        kind = record.get("type")
        message = record.get("message")
        if kind == "user" and first_prompt is None:
            text = _text_of(message)
            if not text.startswith(USER_RELAY_PREFIX):
                first_prompt = text
        elif kind == "assistant" and isinstance(message, dict):
            model = message.get("model")
            if isinstance(model, str) and model and not model.startswith("<"):
                models[model] = models.get(model, 0) + 1  # "<synthetic>" is no model
            usage = message.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            mid = message.get("id")
            if isinstance(mid, str):
                slot = usage_by_id.setdefault(mid, dict.fromkeys(_USAGE_FIELDS, 0))
                for field in _USAGE_FIELDS:
                    slot[field] = max(slot[field], _count(usage.get(field)))
            else:
                for field in _USAGE_FIELDS:
                    loose[field] += _count(usage.get(field))
            content = message.get("content")
            for block in content if isinstance(content, list) else []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    tid = block.get("id")
                    if isinstance(tid, str):
                        seen_tools.add(tid)
                    else:
                        loose_tools += 1

    totals = dict(loose)
    for slot in usage_by_id.values():
        for field in _USAGE_FIELDS:
            totals[field] += slot[field]
    minutes = 0.0
    if first_time is not None and last_time is not None and first_time != last_time:
        minutes = (last_time - first_time).total_seconds() / 60
    return {
        "fresh": totals["input_tokens"] + totals["cache_creation_input_tokens"] + totals["output_tokens"],
        "cache_read": totals["cache_read_input_tokens"],
        "output": totals["output_tokens"],
        "tools": len(seen_tools) + loose_tools,
        "minutes": minutes,
        "first_prompt": first_prompt or "",
        # The meta file leaves `model` out on the default model; the transcript has it.
        "model": max(models, key=lambda name: (models[name], name)) if models else "",
        "read_error": read_error,
    }


def _read_meta(path: Path) -> dict:
    try:
        with open(path, encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return {}
    return meta if isinstance(meta, dict) else {}


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _read_journal(run_dir: Path) -> tuple[dict, dict, str | None, bool, str | None]:
    path = run_dir / "journal.jsonl"
    present = path.is_file()
    starts: dict[str, tuple[str, str]] = {}
    results: dict[str, object] = {}
    slug: str | None = None
    records, read_error = _read_jsonl(path) if present else ([], None)
    for record in records:
        aid = record.get("agentId")
        if not isinstance(aid, str):
            aid = None
        kind = record.get("type")
        if kind == "started" and aid is not None:
            starts[aid] = (_str(record.get("phase")), _str(record.get("label")))
        elif kind == "result":
            result = record.get("result")
            if aid is not None:
                results[aid] = result
            if slug is None and isinstance(result, dict):
                candidate = result.get("slug")
                if isinstance(candidate, str) and candidate:
                    slug = candidate
    return starts, results, slug, present, read_error


def profile_runs(run_dirs: list[Path]) -> dict:
    runs: list[dict] = []
    agents: list[dict] = []
    terminals: set[tuple[str | None, int]] = set()
    issue_rows: dict[tuple[str | None, int], dict] = {}
    incomplete: list[dict] = []

    for run_dir in run_dirs:
        run = run_dir.name
        starts, results, slug, journal, journal_error = _read_journal(run_dir)
        if journal_error is not None:
            incomplete.append({"run": run, "file": "journal.jsonl", "error": journal_error})
        files = sorted(run_dir.glob("agent-*.jsonl"))
        runs.append({"run": run, "slug": slug, "journal": journal, "agents": len(files)})
        for file in files:
            aid = file.name[len("agent-"):-len(".jsonl")]
            meta = _read_meta(run_dir / f"agent-{aid}.meta.json")
            if aid in starts:
                phase, label = starts[aid]
            else:
                phase, label = _str(meta.get("workflowPhase")), _str(meta.get("description"))
            stats = agent_stats(file)
            if stats["read_error"] is not None:
                incomplete.append({"run": run, "file": file.name, "error": stats["read_error"]})
            issue = label_issue(label, phase)
            if issue is None:
                issue = prompt_issue(stats["first_prompt"])
            family = label_family(label)
            row = {
                "run": run, "agent_id": aid, "phase": phase, "label": label, "family": family,
                "model": _str(meta.get("model")) or stats["model"] or "?", "slug": slug, "issue": issue,
                "fresh": stats["fresh"], "cache_read": stats["cache_read"],
                "output": stats["output"], "tools": stats["tools"],
                "minutes": round(stats["minutes"], 2),
            }
            agents.append(row)
            if issue is None:
                continue
            key = (slug, issue)
            result = results.get(aid)
            if family == "close-out" and isinstance(result, dict) and result.get("released") is True:
                terminals.add(key)
            entry = issue_rows.setdefault(key, {"slug": slug, "issue": issue, "agents": 0, "fresh": 0,
                                                "cache_read": 0, "planner_calls": 0})
            entry["agents"] += 1
            entry["fresh"] += row["fresh"]
            entry["cache_read"] += row["cache_read"]
            if family in PLANNER_FAMILIES:
                entry["planner_calls"] += 1

    phase_rows: dict[tuple[str, str], dict] = {}
    family_rows: dict[str, dict] = {}
    for row in agents:
        phase = phase_rows.setdefault((row["run"], row["phase"]), {
            "run": row["run"], "phase": row["phase"], "agents": 0, "fresh": 0,
            "cache_read": 0, "minutes": 0.0})
        fam = family_rows.setdefault(row["family"], {
            "family": row["family"], "agents": 0, "fresh": 0, "cache_read": 0})
        for target in (phase, fam):
            target["agents"] += 1
            target["fresh"] += row["fresh"]
            target["cache_read"] += row["cache_read"]
        phase["minutes"] += row["minutes"]
    for phase in phase_rows.values():
        phase["minutes"] = round(phase["minutes"], 2)

    return {
        "incomplete": incomplete,
        "runs": runs,
        "phases": sorted(phase_rows.values(), key=lambda r: (-r["fresh"], r["run"], r["phase"])),
        "agents": sorted(agents, key=lambda r: (-r["fresh"], r["run"], r["agent_id"])),
        "families": sorted(family_rows.values(), key=lambda r: (-r["fresh"], r["family"])),
        "issues": sorted((issue_rows[key] for key in terminals),
                         key=lambda r: (r["slug"] or "", r["issue"])),
    }


def apply_top(report: dict, top: int) -> dict:
    copy = dict(report)
    copy["agents"] = list(report["agents"][:top])
    copy["families"] = list(report["families"][:top])
    return copy


def _issue_cell(slug: str | None, issue: int | None) -> str:
    if issue is None:
        return "-"
    return f"{slug if slug else '?'}#{issue}"


def _table(title: str | None, header: str, rows: list[list[str]]) -> str:
    lines = ([title] if title else []) + [header] + [" | ".join(row) for row in rows]
    return "\n".join(lines)


def render_text(report: dict) -> str:
    n = "{:,}".format
    m = "{:.0f}".format
    sections = [
        _table(None, "run | phase | agents | fresh tok | cache-read tok | agent-min",
               [[r["run"], r["phase"], n(r["agents"]), n(r["fresh"]), n(r["cache_read"]), m(r["minutes"])]
                for r in report["phases"]]),
        _table("Top agents by fresh tokens", "run | phase | label | model | issue | fresh | cache-read | tools | min",
               [[r["run"], r["phase"], r["label"], r["model"], _issue_cell(r["slug"], r["issue"]),
                 n(r["fresh"]), n(r["cache_read"]), n(r["tools"]), m(r["minutes"])]
                for r in report["agents"]]),
        _table("By label family", "family | agents | fresh | cache-read",
               [[r["family"], n(r["agents"]), n(r["fresh"]), n(r["cache_read"])]
                for r in report["families"]]),
        _table("Per issue (successful terminal result)", "issue | agents | fresh | cache-read | planner calls",
               [[_issue_cell(r["slug"], r["issue"]), n(r["agents"]), n(r["fresh"]),
                 n(r["cache_read"]), n(r["planner_calls"])] for r in report["issues"]]),
    ]
    if report["incomplete"]:
        sections.append(_table("INCOMPLETE: these files could not be read in full", "run | file | error",
                               [[r["run"], r["file"], r["error"]] for r in report["incomplete"]]))
    return "\n\n".join(sections) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="agent-run-profile",
        description="Profile token use of Workflow runs from their agent transcripts.")
    parser.add_argument("run_dir", nargs="+", type=Path, help="a Workflow run directory")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    parser.add_argument("--top", type=int, default=15, help="rows kept in the agent and family lists")
    args = parser.parse_args(argv)
    if args.top < 1:
        parser.error("--top must be at least 1")
    for run_dir in args.run_dir:
        if not run_dir.is_dir():
            print(f"agent-run-profile: not a directory: {run_dir}", file=sys.stderr)
            return 2
    report = apply_top(profile_runs(args.run_dir), args.top)
    if args.json:
        print(json.dumps(report, sort_keys=True, allow_nan=False))
    else:
        print(render_text(report), end="")
    for item in report["incomplete"]:
        print(f"agent-run-profile: incomplete evidence: {item['run']}/{item['file']}: {item['error']}",
              file=sys.stderr)
    return 1 if report["incomplete"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
