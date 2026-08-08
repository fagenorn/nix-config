#!/usr/bin/env python3
"""Per-issue agent-cost telemetry for Claude Code transcripts.

Scans ~/.claude/projects for root sessions (<project>/<session>.jsonl) plus their
subagent transcripts (<project>/<session>/subagents/**/*.jsonl) and reports token
spend and estimated list-price cost grouped by issue.

Two counting rules are load-bearing (see the transcript-mining report):
  * Assistant records are written once per content block and every copy repeats
    the same message.usage. Usage is deduped by message.id; summing naively
    over-counts tokens ~2.5x.
  * Subagent transcripts hold ~64% of all tokens. They are attributed to the
    root session that spawned them.
"""

import argparse
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

# List price per million tokens: (input, output, cache_write_1h, cache_write_5m, cache_read).
# Matches the pricing model the transcript-mining report used, so numbers stay
# comparable to its 35-day baseline. claude-fable-5 is priced as Opus-class.
PRICING = {
    "opus": (15.0, 75.0, 30.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 6.0, 3.75, 0.30),
    "haiku": (1.0, 5.0, 2.0, 1.25, 0.10),
}

TOKEN_FIELDS = ("fresh", "cache_create", "cache_read", "output")
SUM_FIELDS = TOKEN_FIELDS + ("cost", "turns")

ISSUE_RE = re.compile(r"(?:^|[-/])(?:worktree-)?issue-(\d+)")
MULTI_ISSUE = "*"  # root session that roamed across several issue worktrees
HOME = os.path.expanduser("~")


def model_family(model):
    m = (model or "").lower()
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    # opus, fable and anything unrecognised are priced Opus-class.
    return "opus"


def scan_file(path):
    """Parse one transcript. Returns per-file usage, cost, turns, skills, cwds."""
    fresh = cache_create = cache_read = output = 0
    cost = 0.0
    turns = 0
    skills = Counter()
    cwds = Counter()
    seen = set()

    try:
        fh = open(path, "r", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            # Cheap prefilter: only assistant records carry usage and tool_use.
            if '"type":"assistant"' not in line:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            if rec.get("type") != "assistant":
                continue
            msg = rec.get("message") or {}
            if rec.get("cwd"):
                cwds[rec["cwd"]] += 1

            # tool_use blocks are NOT duplicated (one content block per record).
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    if block.get("name") == "Skill":
                        name = (block.get("input") or {}).get("skill")
                        if name:
                            skills[name] += 1

            # usage IS duplicated across the records of one message -> dedupe.
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            if key in seen:
                continue
            seen.add(key)
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            turns += 1

            f_in = usage.get("input_tokens") or 0
            c_out = usage.get("output_tokens") or 0
            c_read = usage.get("cache_read_input_tokens") or 0
            c_create = usage.get("cache_creation_input_tokens") or 0
            split = usage.get("cache_creation") or {}
            cw_1h = split.get("ephemeral_1h_input_tokens") or 0
            cw_5m = split.get("ephemeral_5m_input_tokens") or 0
            if cw_1h + cw_5m == 0:
                cw_5m = c_create  # no TTL breakdown recorded; assume 5m

            fresh += f_in
            output += c_out
            cache_read += c_read
            cache_create += c_create

            p_in, p_out, p_1h, p_5m, p_read = PRICING[model_family(msg.get("model"))]
            cost += (
                f_in * p_in + c_out * p_out + cw_1h * p_1h + cw_5m * p_5m + c_read * p_read
            ) / 1e6

    return {
        "fresh": fresh,
        "cache_create": cache_create,
        "cache_read": cache_read,
        "output": output,
        "cost": cost,
        "turns": turns,
        "skills": dict(skills),
        "cwds": dict(cwds),
    }


def find_sessions(root, cutoff):
    """Group transcripts into root sessions: (home dir, root files, subagents).

    A session's subagent transcripts do not necessarily sit under the same
    project dir as its root transcript — a session that moves into a worktree
    writes its subagents to the worktree's project dir while the root transcript
    stays put. So transcripts are keyed by session id across all project dirs,
    and the session's identity comes from whichever dir holds most of its files.
    """
    roots, subs = defaultdict(list), defaultdict(list)
    for project_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for transcript in project_dir.glob("*.jsonl"):
            roots[transcript.stem].append((project_dir.name, transcript))
        for subdir in project_dir.glob("*/subagents"):
            for transcript in subdir.rglob("*.jsonl"):
                subs[subdir.parent.name].append((project_dir.name, transcript))

    def in_window(f):
        return cutoff is None or f.stat().st_mtime >= cutoff

    for session_id in sorted(set(roots) | set(subs)):
        root_files = [(d, f) for d, f in roots[session_id] if in_window(f)]
        sub_files = [(d, f) for d, f in subs[session_id] if in_window(f)]
        if not root_files and not sub_files:
            continue
        counts = Counter(d for d, _ in root_files + sub_files)
        home, top = counts.most_common(1)[0]
        for d, _ in root_files:  # tie-break toward the root transcript's dir
            if counts[d] == top:
                home = d
                break
        yield home, [f for _, f in root_files], [f for _, f in sub_files]


def repo_root(cwd):
    """Trim at the first dot-directory (.claude/worktrees, .pi-sessions, ...).

    Sessions run inside a worktree or a tool's scratch dir still belong to the
    repo that contains it.
    """
    parts = cwd.rstrip("/").split("/")
    for i, part in enumerate(parts):
        if i and part.startswith("."):
            return "/".join(parts[:i])
    return "/".join(parts)


def project_name(dir_name, root_cwds):
    """Project name from the root session's busiest cwd, else the dir name."""
    for cwd, _ in root_cwds.most_common():
        base = repo_root(cwd)
        # A session run straight from $HOME says nothing about the project.
        if base and base != HOME:
            return os.path.basename(base)
    name = dir_name.lstrip("-").split("--claude-worktrees-")[0]
    return name.rsplit("-", 1)[-1] or dir_name


def issue_key(dir_name, root_cwds):
    """Issue number from the project/worktree dir name, else the root cwd.

    Only the root transcript's own cwds are consulted, and only when they agree.
    An orchestrator that hops between worktrees must not be billed to whichever
    of those issues happens to sort first.
    """
    match = ISSUE_RE.search(dir_name)
    if match:
        return match.group(1)
    found = {m.group(1) for m in (ISSUE_RE.search(c) for c in root_cwds) if m}
    if len(found) == 1:
        return found.pop()
    return MULTI_ISSUE if found else None


def total_tokens(d):
    return sum(d[f] for f in TOKEN_FIELDS)


def human(n):
    for unit, div in (("B", 1e9), ("M", 1e6), ("k", 1e3)):
        if abs(n) >= div:
            return f"{n / div:,.2f}{unit}"
    return f"{n:,}"


def print_table(rows, headers, aligns):
    widths = [
        max(len(headers[i]), max((len(r[i]) for r in rows), default=0))
        for i in range(len(headers))
    ]

    def fmt(cells):
        return "  ".join(
            c.rjust(widths[i]) if aligns[i] == "r" else c.ljust(widths[i])
            for i, c in enumerate(cells)
        ).rstrip()

    print(fmt(headers))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        print(fmt(row))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=35, help="window in days by file mtime (0 = all)")
    ap.add_argument("--project", help="only projects whose name contains this substring")
    ap.add_argument("--top", type=int, default=30, help="rows to print")
    ap.add_argument(
        "--projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
        help="transcript root",
    )
    args = ap.parse_args()

    root = Path(args.projects_dir)
    if not root.is_dir():
        sys.exit(f"no transcript root at {root}")
    cutoff = time.time() - args.days * 86400 if args.days > 0 else None

    sessions = list(find_sessions(root, cutoff))
    # (session index, is_root, path) — pool.map preserves input order.
    jobs = [
        (i, is_root, f)
        for i, (_, root_files, sub_files) in enumerate(sessions)
        for is_root, f in [(True, f) for f in root_files] + [(False, f) for f in sub_files]
    ]
    if not jobs:
        sys.exit("no transcripts in window")

    per_session = defaultdict(list)
    with ProcessPoolExecutor(max_workers=os.cpu_count() or 4) as pool:
        results = pool.map(scan_file, [f for _, _, f in jobs], chunksize=8)
        for (idx, is_root, _), result in zip(jobs, results):
            if result:
                per_session[idx].append((is_root, result))

    groups = {}
    kept_sessions = kept_files = 0
    for idx, (dir_name, _root_files, sub_files) in enumerate(sessions):
        entries = per_session.get(idx)
        if not entries:
            continue
        root_cwds = Counter()
        for is_root, r in entries:
            if is_root:
                root_cwds.update(r["cwds"])
        project = project_name(dir_name, root_cwds)
        if args.project and args.project.lower() not in project.lower():
            continue
        kept_sessions += 1
        kept_files += len(entries)
        issue = issue_key(dir_name, root_cwds)
        g = groups.setdefault(
            (project, issue),
            dict.fromkeys(SUM_FIELDS + ("subagents", "skill_loads", "repeats", "sessions"), 0),
        )
        g["sessions"] += 1
        g["subagents"] += len(sub_files)
        session_skills = Counter()
        for _is_root, r in entries:
            for field in SUM_FIELDS:
                g[field] += r[field]
            session_skills.update(r["skills"])
        loads = sum(session_skills.values())
        g["skill_loads"] += loads
        # A repeat is a load of a skill this root session had already loaded.
        g["repeats"] += loads - len(session_skills)

    if not groups:
        sys.exit("no sessions matched the filters")

    ordered = sorted(
        groups.items(), key=lambda kv: (kv[1]["cost"], total_tokens(kv[1])), reverse=True
    )

    rows = []
    for (project, issue), g in ordered[: args.top]:
        label = "(no issue)" if issue is None else "(multi-issue)" if issue == MULTI_ISSUE else f"#{issue}"
        rows.append([
            label,
            project,
            human(total_tokens(g)),
            f"${g['cost']:,.0f}",
            f"{g['turns']:,}",
            f"{g['sessions']:,}",
            f"{g['subagents']:,}",
            f"{g['skill_loads']:,}",
            f"{g['repeats']:,}",
        ])

    window = f"last {args.days}d" if cutoff else "all time"
    print(
        f"Agent costs by issue ({window}, {kept_files:,} transcripts, "
        f"{kept_sessions:,} root sessions, {len(groups):,} groups)\n"
    )
    print_table(
        rows,
        ["issue", "project", "tokens", "est $", "turns", "sess", "subagents", "skills", "repeat"],
        ["l", "l", "r", "r", "r", "r", "r", "r", "r"],
    )

    tot = {
        k: sum(g[k] for g in groups.values())
        for k in SUM_FIELDS + ("subagents", "skill_loads", "repeats")
    }
    if len(ordered) > args.top:
        print(f"\n... {len(ordered) - args.top} more groups not shown (--top {len(ordered)} for all)")
    print(
        f"\nTOTAL  {human(total_tokens(tot))} tokens  ${tot['cost']:,.0f}  {tot['turns']:,} turns  "
        f"{tot['subagents']:,} subagents  {tot['skill_loads']:,} skill loads "
        f"({tot['repeats']:,} repeats)"
    )
    print(
        f"       fresh {human(tot['fresh'])} | cache_create {human(tot['cache_create'])} | "
        f"cache_read {human(tot['cache_read'])} | output {human(tot['output'])}"
    )

    issue_costs = [
        g["cost"] for (_, issue), g in groups.items() if issue and issue != MULTI_ISSUE
    ]
    if issue_costs:
        plural = "issue" if len(issue_costs) == 1 else "issues"
        print(
            f"\nPer issue ({len(issue_costs)} {plural}): median ${statistics.median(issue_costs):,.0f}  "
            f"mean ${statistics.fmean(issue_costs):,.0f}  max ${max(issue_costs):,.0f}"
        )


if __name__ == "__main__":
    main()
