"""The agent-costs cache report (issue 421).

scan_transcript reads one Claude Code transcript through agent_tools.transcript_calls,
prices it through agent_tools.model_pricing and returns its calls in the
window, its cache deaths with their cause and premium, its cache-read cost above
a context threshold, its peak context and, for a subagent, its start-up overhead.
agent_costs.main runs the report for `--report cache`: transcript_jobs selects the
transcripts, scan_jobs scans them through agent_costs.scan_paths and print_report
prints the three tables. python/README.md (agent-costs) holds the contract.
"""

import functools
import json
from collections import defaultdict

from agent_tools.agent_costs import (
    DISCLAIMER,
    event_in_window,
    find_sessions,
    human,
    percentile,
    print_table,
    scan_paths,
)
from agent_tools.model_pricing import SOURCE_DATE, SOURCE_URL, cache_write_split, rates
from agent_tools.transcript_calls import TTL_SECONDS, is_death, read_transcript

DEFAULT_CONTEXT_THRESHOLD = 120_000
STARTUP_ATTACHMENTS = (
    "skill_listing",
    "instructions",
    "mcp_instructions_delta",
    "deferred_tools_delta",
    "agent_listing_delta",
    "environment",
)


def _agent_type(path, is_root):
    if is_root:
        return "main"
    try:
        with open(path.with_name(path.stem + ".meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        return "unknown"
    name = meta.get("agentType") if isinstance(meta, dict) else None
    return name if isinstance(name, str) and name else "unknown"


def _counts(calls, since, before):
    """Per call, whether it is in the window; with no window every call counts."""
    if since is None and before is None:
        return [True] * len(calls)
    return [call.start_raw is not None
            and event_in_window(call.start_raw, since, before) is True for call in calls]


def _cause(prev, call, user_entries):
    """Death kind of `call`, from the user records between it and `prev` (D5, D12)."""
    between = [entry for entry in user_entries if prev.first_line < entry[1] < call.first_line]
    tool = None
    for entry in between:
        if entry[0] == "result" and not entry[3]:          # ("result", line, ids, ends_turn)
            for tool_id in entry[2]:
                if tool_id in prev.tool_names:
                    tool = prev.tool_names[tool_id]
    if tool is not None:
        if tool in ("Agent", "Task"):
            return "child dispatch"
        if tool == "Bash":
            return "long foreground command"
        return "other tool"
    for entry in between:
        if entry[0] == "wake":                              # ("wake", line, kind)
            return entry[2]
    return "unclassified"


def _premium(prev, call):
    """Rewrite cost beyond a warm read of the prefix that was cached (D6), in dollars."""
    price, _ = rates(call.model, call.context)
    cw_1h, cw_5m = cache_write_split(call.usage)
    write = (cw_1h * price.write_1h + cw_5m * price.write_5m) / (cw_1h + cw_5m)
    return min(call.usage["cache_creation_input_tokens"], prev.context) * (write - price.read) / 1e6


def _deaths(calls, counts, user_entries, is_root):
    ttl = TTL_SECONDS[is_root]
    deaths = []
    for index in range(1, len(calls)):
        prev, call = calls[index - 1], calls[index]
        if counts[index] and is_death(prev, call, ttl):
            deaths.append({
                "kind": _cause(prev, call, user_entries),
                "gap_s": (call.start - prev.end).total_seconds(),
                "premium": _premium(prev, call),
            })
    return deaths


def _reread_above(calls, counts, threshold):
    total = 0.0
    for call, counted in zip(calls, counts):
        if counted:
            price, _ = rates(call.model, call.context)
            total += max(0, call.usage["cache_read_input_tokens"] - threshold) * price.read / 1e6
    return total


def _startup(calls, counts, attachments, is_root):
    if is_root or not calls or not counts[0]:
        return None
    first = calls[0]
    cutoff = calls[1].first_line if len(calls) > 1 else None
    sizes = {name: size for name, (line_no, size) in attachments.items()
             if size is not None and (cutoff is None or line_no < cutoff)}
    return {
        "write": first.usage["cache_creation_input_tokens"],
        "read": first.usage["cache_read_input_tokens"],
        "attachments": {name: sizes[name] for name in STARTUP_ATTACHMENTS if name in sizes},
    }


def scan_transcript(job, *, since, before, threshold):
    """Scan one transcript `(path, is_root)`; None when it cannot be opened."""
    path, is_root = job
    try:
        with open(path, "r", errors="replace") as handle:
            transcript = read_transcript(handle)
    except OSError:
        return None
    calls = transcript.calls
    agent_type = _agent_type(path, is_root)
    counts = _counts(calls, since, before)
    counted = [call for call, flag in zip(calls, counts) if flag]
    return {
        "agent_type": agent_type,
        "is_root": is_root,
        "calls": len(counted),
        "approximate_calls": sum(rates(call.model, call.context)[1] for call in counted),
        "deaths": _deaths(calls, counts, transcript.user_entries, is_root),
        "reread_above": _reread_above(calls, counts, threshold),
        "peak_ctx": max((call.context for call in counted), default=None),
        "startup": _startup(calls, counts, transcript.attachments, is_root),
    }


def transcript_jobs(root, mtime_cutoff):
    """`(path, is_root)` for every transcript of every session in the window, roots first."""
    jobs = []
    for _home, root_files, sub_files in find_sessions(root, mtime_cutoff):
        jobs.extend((path, True) for path in root_files)
        jobs.extend((path, False) for path in sub_files)
    return jobs


def scan_jobs(jobs, *, since, before, threshold, executor_factory):
    """Scan the jobs in order through `scan_paths`, dropping transcripts that cannot be opened."""
    scanner = functools.partial(scan_transcript, since=since, before=before, threshold=threshold)
    return [result for result in scan_paths(jobs, executor_factory, scanner=scanner) if result]


def _print_capped(rows, top, headers, aligns):
    print_table(rows[:top], headers, aligns)
    if len(rows) > top:
        print(f"\n... {len(rows) - top} more rows not shown (--top {len(rows)} for all)")


def _death_rows(results):
    groups = defaultdict(list)
    for result in results:
        for death in result["deaths"]:
            groups[(result["agent_type"], death["kind"])].append(death)
    rows = []
    for (agent_type, kind), deaths in groups.items():
        premium = sum(death["premium"] for death in deaths)
        median_gap = percentile([death["gap_s"] for death in deaths], 50)
        rows.append((premium, len(deaths), agent_type, kind, median_gap))
    rows.sort(key=lambda row: (-row[0], -row[1], row[2], row[3]))
    return [[agent_type, kind, f"{count:,}", f"{median_gap / 60:.1f}m", f"${premium:,.0f}"]
            for premium, count, agent_type, kind, median_gap in rows]


def _death_totals(results):
    totals = {True: [0, 0.0], False: [0, 0.0]}
    for result in results:
        for death in result["deaths"]:
            totals[result["is_root"]][0] += 1
            totals[result["is_root"]][1] += death["premium"]
    return totals


def _reread_rows(results):
    groups = defaultdict(list)
    for result in results:
        groups[result["agent_type"]].append(result)
    rows = []
    for agent_type, members in groups.items():
        peaks = [member["peak_ctx"] for member in members]
        reread = sum(member["reread_above"] for member in members)
        rows.append((reread, agent_type, len(members), peaks))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [[agent_type, f"{count:,}", f"${reread:,.0f}", human(percentile(peaks, 50)),
             human(percentile(peaks, 90)), human(max(peaks))]
            for reread, agent_type, count, peaks in rows]


def _startup_rows(results):
    groups = defaultdict(list)
    for result in results:
        if result["startup"] is not None:
            groups[result["agent_type"]].append(result["startup"])
    rows = []
    for agent_type, startups in groups.items():
        cells = [agent_type, f"{len(startups):,}",
                 human(percentile([s["write"] for s in startups], 50)),
                 human(percentile([s["read"] for s in startups], 50))]
        for name in STARTUP_ATTACHMENTS:
            sizes = [s["attachments"][name] for s in startups if name in s["attachments"]]
            cells.append(human(percentile(sizes, 50)) if sizes else "-")
        rows.append((len(startups), agent_type, cells))
    rows.sort(key=lambda row: (-row[0], row[1]))
    return [cells for _count, _agent_type, cells in rows]


def print_report(results, *, window, threshold, top):
    """Print the cache report for scan_transcript results that have a counting call."""
    results = [result for result in results if result["calls"] > 0]
    transcripts, calls = len(results), sum(result["calls"] for result in results)
    print(f"Cache report ({window}, {transcripts:,} transcripts, {calls:,} calls)\n")
    print("Cache deaths (idle gap > TTL - 10s, TTL 5m for subagents and 1h for main sessions; "
          "rewrite > 50% of a > 5k-token context; premium = rewrite at write price less a warm "
          "read):\n")
    _print_capped(_death_rows(results), top,
                  ["agent type", "cause", "deaths", "median gap", "premium"],
                  ["l", "l", "r", "r", "r"])
    totals = _death_totals(results)
    (sub_count, sub_premium), (root_count, root_premium) = totals[False], totals[True]
    print(f"\nSubagent deaths {sub_count:,} (${sub_premium:,.0f} premium); "
          f"main-session deaths {root_count:,} (${root_premium:,.0f})")
    print(f"\nReread above {human(threshold)} tokens of context (cache reads past that position "
          "at the read price; peak = largest single-call context per transcript):\n")
    _print_capped(_reread_rows(results), top,
                  ["agent type", "transcripts", "reread above", "peak p50", "peak p90", "peak max"],
                  ["l", "r", "r", "r", "r", "r"])
    print("\nSubagent start-up (first request's cache write and read; characters of each start-up "
          "attachment sent before the second request; medians over the subagents that carried "
          "it):\n")
    _print_capped(_startup_rows(results), top,
                  ["agent type", "subagents", "1st write", "1st read", "skill listing",
                   "instructions", "MCP instructions", "deferred tools", "agent listing",
                   "environment"],
                  ["l"] + ["r"] * 9)
    approximate = sum(result["approximate_calls"] for result in results)
    print(f"\nPricing: {SOURCE_URL} ({SOURCE_DATE}); {approximate:,} calls priced approximately")
    print(f"NOTE: {DISCLAIMER}")
