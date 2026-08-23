#!/usr/bin/env python3
"""Per-issue agent-cost telemetry for Claude Code transcripts.

Scans ~/.claude/projects for root sessions (<project>/<session>.jsonl) plus their
subagent transcripts (<project>/<session>/subagents/**/*.jsonl) and reports token
spend and estimated list-price cost grouped by issue.

Two counting rules are load-bearing (see the transcript-mining report):
  * Assistant records are written once per content block and every copy repeats
    the same message.usage. Usage is deduped by message.id; summing naively
    over-counts tokens ~2.5x.
  * Subagent transcripts hold ~64% of all tokens. Proven issue-owner transcripts
    follow their agreeing issue worktree; rooted helper, reviewer, ambiguous,
    and other non-owner transcripts remain overhead of the root session.

Interpretation note — this is comparative telemetry, NOT billing data. The
dominant token bucket, cache reads, measures logical context processing: every
turn re-reads the session prefix from cache, so cache_read counts the tokens
the model attended to, priced at the list cache-read rate. The estimated $
figures apply public list prices per family and exist so runs can be compared
against each other and against the 35-day baseline; they are not what anyone
was billed.

Beyond the per-issue cost table this also derives (heuristically where noted):
issue outcome (completed/blocked/abandoned from each root session's final
assistant message), turns per textual "Phase N" marker and per attributionSkill,
subagent launches by type with prompt/result byte distributions, exact
model+effort mix per group, per-session peak context (max input+cache tokens of
a single turn), stop_reason counts plus lingering agents killed at exit, and
short user "proceed" nudges. `--artifacts DIR` adds a filesystem pass over
spec/plan markdown: bytes, fenced-code share, and decision-section share.
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
# Scalar extras summed (or maxed, for peak_ctx) across a group's transcripts.
EXTRA_INT_FIELDS = ("agents_killed", "interventions")
# Counter-valued extras merged across a group's transcripts.
COUNTER_FIELDS = ("models", "efforts", "stop_reasons", "phase_turns", "attr_turns",
                  "agents_by_type", "agent_statuses")
LIST_FIELDS = ("agent_prompt_bytes", "agent_result_bytes")

ISSUE_RE = re.compile(r"(?:^|[-/])(?:worktree-)?issue-(\d+)")
ISSUE_WORKTREE_RE = re.compile(
    r"(?:^|/)\.claude/worktrees/(?:worktree-)?issue-([1-9][0-9]*)-[^/]+(?:/|$)"
)
OWNER_AGENT_RE = re.compile(r"^aissue-([1-9][0-9]*)-owner-([1-9][0-9]*)-(.+)$")
MULTI_ISSUE = "*"  # root session that roamed across several issue worktrees
HOME = os.path.expanduser("~")

# Textual phase marker in assistant narration ("Phase 3", "## Phase 3 — grill").
PHASE_RE = re.compile(r"\bPhase\s+(\d+)\b")

# Short user messages that only nudge the agent onward ("proceed", "ok continue").
PROCEED_RE = re.compile(
    r"^(?:(?:sorry|please|ok(?:ay)?|yes|yep|yeah)[\s,!.]*)*"
    r"(?:proceed|continue|go ahead|go on|keep going|keep at it|resume|carry on|"
    r"do it|lgtm|approved?|sounds good|yes|yep|ok(?:ay)?|y|go)[\s,!.]*$"
)

# Outcome classification of a root session's final assistant message (heuristic).
STRONG_DONE_RE = re.compile(
    r"\b(merged|shipped|landed|released|issue\s+(?:#\d+\s+)?closed|closed\s+issue|"
    r"review_state:\s*clean|all\s+tasks?\s+complete)", re.I)
BLOCKED_RE = re.compile(
    r"\b(blocked|blocker|cannot\s+proceed|can't\s+proceed|"
    r"stopp(?:ed|ing)\s+(?:here|before|at)|waiting\s+(?:for|on)\s+(?:you|input|human|user)|"
    r"needs?\s+(?:your|human|user)\s+(?:input|decision|review|call)|abort(?:ed|ing)?)", re.I)
WEAK_DONE_RE = re.compile(r"\b(complete[d.!]?|done[.!]?|finished|succeeded|passes)\b", re.I)
# Canonical suspension stop line: "Suspended (blocked_on=<value>). Resume: <command>".
INTERRUPTED_RE = re.compile(r"suspended \(blocked_on=", re.IGNORECASE)


def model_family(model):
    m = (model or "").lower()
    if "sonnet" in m:
        return "sonnet"
    if "haiku" in m:
        return "haiku"
    # opus, fable and anything unrecognised are priced Opus-class.
    return "opus"


def classify_outcome(final_text):
    """completed | interrupted | blocked | abandoned from a session's final message."""
    if STRONG_DONE_RE.search(final_text):
        return "completed"
    # Must precede BLOCKED_RE: the canonical line's "blocked_on" substring would
    # otherwise match BLOCKED_RE first and mislabel a suspension as blocked.
    if INTERRUPTED_RE.search(final_text):
        return "interrupted"
    if BLOCKED_RE.search(final_text):
        return "blocked"
    if WEAK_DONE_RE.search(final_text):
        return "completed"
    return "abandoned"


def review_operation_from_envelope(rec):
    """Return the operation from an exact sidechain root transport envelope."""
    if (rec.get("type") != "user" or rec.get("isSidechain") is not True
            or "parentUuid" not in rec or rec.get("parentUuid") is not None):
        return None
    content = (rec.get("message") or {}).get("content")
    if not isinstance(content, str):
        return None
    lines = content.splitlines()
    if len(lines) < 2 or not lines[0].startswith("WORKTREE_ROOT: "):
        return None
    if not os.path.isabs(lines[0][len("WORKTREE_ROOT: "):]):
        return None
    prefix = "REVIEW_OPERATION: "
    if not lines[1].startswith(prefix):
        return None
    if sum(line.startswith(prefix) for line in lines) != 1:
        return None
    operation = lines[1][len(prefix):]
    return operation if operation in ("plan-review", "diff-review") else None


def scan_file(path):
    """Parse one transcript. Returns per-file usage, cost, turns, skills, cwds,
    plus the extended telemetry fields (models, efforts, agents, phases, ...)."""
    fresh = cache_create = cache_read = output = 0
    cost = 0.0
    turns = 0
    skills = Counter()
    cwds = Counter()
    seen = set()             # message ids — usage is duplicated per content block
    seen_tool_ids = set()    # assistant tool_use block ids — guard against replays
    seen_result_ids = set()  # user tool_result ids — same guard for agent results
    models = Counter()
    efforts = Counter()
    stop_reasons = Counter()
    phase_turns = Counter()
    raw_attr_turns = Counter()
    agents_by_type = Counter()
    agent_statuses = Counter()
    agent_prompt_bytes = []
    agent_result_bytes = []
    agents_killed = 0
    interventions = 0
    peak_ctx = 0
    current_phase = None
    final_text = ""
    agent_ids = set()
    review_operation = None
    initial_record_pending = True

    try:
        fh = open(path, "r", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            # Cheap prefilter. Assistant records carry usage and tool_use; user
            # records matter only when short (a possible "proceed" nudge), when
            # they carry an Agent result, or when they carry the exact review
            # envelope marker; system records only for agents_killed. The first
            # valid JSON record is always parsed because only it may be envelope
            # evidence.
            if initial_record_pending:
                pass
            elif '"type":"assistant"' in line:
                pass
            elif '"type":"user"' in line:
                if ('"agentType"' not in line and "REVIEW_OPERATION:" not in line
                        and len(line) > 4096):
                    continue
            elif '"type":"system"' in line:
                if '"subtype":"agents_killed"' not in line:
                    continue
            else:
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            is_initial_record = initial_record_pending
            initial_record_pending = False
            rtype = rec.get("type")
            agent_id = rec.get("agentId")
            if agent_id:
                agent_ids.add(str(agent_id))

            if rtype == "system":
                if rec.get("subtype") == "agents_killed":
                    agents_killed += 1
                continue

            if rtype == "user":
                msg = rec.get("message") or {}
                content = msg.get("content")
                if is_initial_record:
                    review_operation = review_operation_from_envelope(rec)
                tur = rec.get("toolUseResult")
                if isinstance(tur, dict) and "agentType" in tur:
                    # An Agent subagent's result. Dedup by the tool_result id.
                    rid = None
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_result":
                                rid = block.get("tool_use_id")
                                break
                    if rid is None:
                        # String-content replays carry no tool_result block;
                        # fall back to record identity so they dedup too.
                        rid = rec.get("uuid") or rec.get("requestId")
                    if rid:
                        if rid in seen_result_ids:
                            continue
                        seen_result_ids.add(rid)
                    agent_statuses[str(tur.get("status") or "?")] += 1
                    rcontent = tur.get("content")
                    if rcontent is not None:
                        agent_result_bytes.append(
                            len(rcontent) if isinstance(rcontent, str) else len(str(rcontent))
                        )
                elif not rec.get("isSidechain") and not rec.get("isMeta"):
                    if isinstance(content, str):
                        text = content
                    elif isinstance(content, list):
                        text = " ".join(
                            block.get("text", "")
                            for block in content
                            if isinstance(block, dict) and block.get("type") == "text"
                        )
                    else:
                        text = ""
                    text = text.strip().lower()
                    if text and len(text) <= 48 and PROCEED_RE.match(text):
                        interventions += 1
                continue

            if rtype != "assistant":
                continue
            msg = rec.get("message") or {}
            if rec.get("cwd"):
                cwds[rec["cwd"]] += 1

            # tool_use blocks are NOT duplicated (one content block per record),
            # but guard by block id anyway so a replayed record can't double-count.
            content = msg.get("content")
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "tool_use":
                        bid = block.get("id")
                        if bid:
                            if bid in seen_tool_ids:
                                continue
                            seen_tool_ids.add(bid)
                        name = block.get("name")
                        binput = block.get("input") or {}
                        if name == "Skill":
                            sname = binput.get("skill")
                            if sname:
                                skills[sname] += 1
                        elif name in ("Agent", "Task"):
                            agents_by_type[str(binput.get("subagent_type") or "general-purpose")] += 1
                            prompt = binput.get("prompt")
                            if isinstance(prompt, str):
                                agent_prompt_bytes.append(len(prompt))
                    elif btype == "text":
                        text = block.get("text") or ""
                        if "Phase" in text:
                            markers = PHASE_RE.findall(text)
                            if markers:
                                current_phase = markers[-1]
                        if text.strip():
                            final_text = text[-500:]

            # usage IS duplicated across the records of one message -> dedupe.
            key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
            if key in seen:
                continue
            seen.add(key)
            usage = msg.get("usage")
            if not isinstance(usage, dict):
                continue
            turns += 1

            model = msg.get("model")
            if model:
                models[model] += 1
            effort = rec.get("effort")
            if effort:
                efforts[str(effort)] += 1
            sreason = msg.get("stop_reason")
            if sreason:
                stop_reasons[str(sreason)] += 1
            askill = rec.get("attributionSkill")
            if askill:
                raw_attr_turns[str(askill)] += 1
            if current_phase is not None:
                phase_turns[current_phase] += 1

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
            ctx = f_in + c_read + c_create
            if ctx > peak_ctx:
                peak_ctx = ctx

            p_in, p_out, p_1h, p_5m, p_read = PRICING[model_family(model)]
            cost += (
                f_in * p_in + c_out * p_out + cw_1h * p_1h + cw_5m * p_5m + c_read * p_read
            ) / 1e6

    attr_turns = Counter()
    for skill, count in raw_attr_turns.items():
        if skill == "codex-collaboration" and review_operation:
            skill = f"{skill}/{review_operation}"
        attr_turns[skill] += count

    return {
        "fresh": fresh,
        "cache_create": cache_create,
        "cache_read": cache_read,
        "output": output,
        "cost": cost,
        "turns": turns,
        "skills": dict(skills),
        "cwds": dict(cwds),
        "models": dict(models),
        "efforts": dict(efforts),
        "stop_reasons": dict(stop_reasons),
        "phase_turns": dict(phase_turns),
        "attr_turns": dict(attr_turns),
        "agents_by_type": dict(agents_by_type),
        "agent_statuses": dict(agent_statuses),
        "agent_prompt_bytes": agent_prompt_bytes,
        "agent_result_bytes": agent_result_bytes,
        "agents_killed": agents_killed,
        "interventions": interventions,
        "peak_ctx": peak_ctx,
        "final_text": final_text,
        "agent_id": next(iter(agent_ids)) if len(agent_ids) == 1 else None,
        "review_operation": review_operation,
    }


def owner_issue(result):
    """Return an issue only for an owner identity with agreeing cwd evidence."""
    match = OWNER_AGENT_RE.fullmatch(result.get("agent_id") or "")
    if not match:
        return None
    cwd_issues = {
        cwd_match.group(1)
        for cwd in result.get("cwds", {})
        for cwd_match in ISSUE_WORKTREE_RE.finditer(cwd)
    }
    if len(cwd_issues) != 1:
        return None
    issue = next(iter(cwd_issues))
    return issue if issue == match.group(1) else None


def scan_paths(paths, executor_factory=ProcessPoolExecutor):
    """Scan in order, falling back all-or-nothing when a process pool fails."""
    paths = list(paths)
    try:
        with executor_factory(max_workers=os.cpu_count() or 4) as pool:
            return list(pool.map(scan_file, paths, chunksize=8))
    except Exception as error:
        print(
            f"Process pool unavailable ({type(error).__name__}); scanning sequentially.",
            file=sys.stderr,
        )
    return [scan_file(path) for path in paths]


def fold_scan_totals(results):
    """Fold additive global fields once, preserving raw scan-result order."""
    totals = dict.fromkeys(SUM_FIELDS, 0)
    for result in results:
        for field in SUM_FIELDS:
            totals[field] += result[field]
    return totals


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


def percentile(values, p):
    """Nearest-rank percentile; 0 for an empty list."""
    if not values:
        return 0
    ordered = sorted(values)
    k = max(0, min(len(ordered) - 1, int(round(p / 100 * (len(ordered) - 1)))))
    return ordered[k]


def counter_mix(counter, top=2, strip_prefix=""):
    """'a 61%|b 39%' for the top entries of a Counter."""
    total = sum(counter.values())
    if not total:
        return "-"
    parts = []
    for name, count in counter.most_common(top):
        label = name[len(strip_prefix):] if strip_prefix and name.startswith(strip_prefix) else name
        parts.append(f"{label} {100 * count // total}%")
    return "|".join(parts)


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


def new_group():
    g = dict.fromkeys(
        SUM_FIELDS + EXTRA_INT_FIELDS
        + ("subagents", "skill_loads", "repeats", "sessions", "peak_ctx"),
        0,
    )
    for field in COUNTER_FIELDS:
        g[field] = Counter()
    for field in LIST_FIELDS:
        g[field] = []
    g["outcomes"] = []
    return g


def group_outcome(g):
    """Roll session outcomes up to the group (heuristic, from final messages)."""
    outcomes = g["outcomes"]
    if not outcomes:
        return "-"
    if "completed" in outcomes:
        return "completed"
    if "interrupted" in outcomes:
        return "interrupted"
    if "blocked" in outcomes:
        return "blocked"
    return "abandoned"


def build_groups(sessions, per_session, project_filter=None):
    """Partition ordered scan results into one destination per transcript."""
    groups = {}
    retained_results = []
    kept_sessions = kept_files = 0

    for idx, (dir_name, _root_files, _sub_files) in enumerate(sessions):
        entries = per_session.get(idx)
        if not entries:
            continue

        root_cwds = Counter()
        for is_root, result in entries:
            if is_root:
                root_cwds.update(result["cwds"])
        project = project_name(dir_name, root_cwds)
        if project_filter and project_filter.lower() not in project.lower():
            continue

        attributed = [
            (is_root, result, None if is_root else owner_issue(result))
            for is_root, result in entries
        ]
        owner_issues = {issue for _is_root, _result, issue in attributed if issue}
        root_issue = (
            MULTI_ISSUE if len(owner_issues) >= 2 else issue_key(dir_name, root_cwds)
        )
        root_key = (project, root_issue)
        root_group = groups.setdefault(root_key, new_group())
        root_group["sessions"] += 1

        session_skills = defaultdict(Counter)
        for is_root, result, issue in attributed:
            destination = root_key if is_root or issue is None else (project, issue)
            group = groups.setdefault(destination, new_group())
            retained_results.append(result)

            for field in SUM_FIELDS:
                group[field] += result[field]
            for field in COUNTER_FIELDS:
                group[field].update(result[field])
            for field in LIST_FIELDS:
                group[field].extend(result[field])
            group["agents_killed"] += result["agents_killed"]
            group["peak_ctx"] = max(group["peak_ctx"], result["peak_ctx"])
            if is_root:
                group["interventions"] += result["interventions"]
                if result["final_text"]:
                    group["outcomes"].append(classify_outcome(result["final_text"]))
            else:
                group["subagents"] += 1
            session_skills[destination].update(result["skills"])

        for destination, skills in session_skills.items():
            loads = sum(skills.values())
            group = groups[destination]
            group["skill_loads"] += loads
            group["repeats"] += loads - len(skills)

        kept_sessions += 1
        kept_files += len(entries)

    return groups, retained_results, kept_sessions, kept_files


def artifact_stats(paths):
    """Filesystem pass over spec/plan markdown artifacts.

    For every .md under each path: size, share of bytes inside ``` fences, and
    share of bytes inside sections whose heading mentions 'decision' (the
    decision ledger), plus a count of compact ledger table rows (>=3 '|'
    separators) inside those sections.
    """
    per_class = defaultdict(lambda: {"files": 0, "bytes": 0, "sizes": [],
                                     "fenced": 0, "decision": 0, "ledger_rows": 0})
    for base in paths:
        base = Path(os.path.expanduser(base))
        files = [base] if base.is_file() else sorted(base.rglob("*.md")) if base.is_dir() else []
        if not files:
            print(f"  (no markdown artifacts under {base})")
            continue
        for f in files:
            try:
                text = f.read_text(errors="replace")
            except OSError:
                continue
            low = str(f).lower()
            cls = "spec" if "spec" in low else "plan" if "plan" in low else "other"
            st = per_class[cls]
            st["files"] += 1
            st["bytes"] += len(text)
            st["sizes"].append(len(text))
            in_fence = False
            in_decision = False
            decision_level = 0
            for line in text.splitlines(keepends=True):
                stripped = line.strip()
                if stripped.startswith("```"):
                    in_fence = not in_fence
                    st["fenced"] += len(line)
                    continue
                if in_fence:
                    st["fenced"] += len(line)
                    continue
                if stripped.startswith("#"):
                    level = len(stripped) - len(stripped.lstrip("#"))
                    if "decision" in stripped.lower():
                        in_decision = True
                        decision_level = level
                    elif in_decision and level <= decision_level:
                        in_decision = False
                if in_decision:
                    st["decision"] += len(line)
                    if stripped.count("|") >= 3 and not set(stripped) <= set("|-: "):
                        st["ledger_rows"] += 1
    return per_class


def print_artifact_stats(per_class):
    if not per_class:
        return
    rows = []
    for cls in ("spec", "plan", "other"):
        st = per_class.get(cls)
        if not st or not st["files"]:
            continue
        total = st["bytes"] or 1
        rows.append([
            cls,
            f"{st['files']:,}",
            human(st["bytes"]),
            human(percentile(st["sizes"], 50)),
            f"{100 * st['fenced'] // total}%",
            f"{100 * st['decision'] // total}%",
            f"{st['ledger_rows']:,}",
        ])
    if rows:
        print_table(
            rows,
            ["class", "files", "bytes", "p50", "fenced", "decision", "ledger rows"],
            ["l", "r", "r", "r", "r", "r", "r"],
        )


def main(argv=None, *, executor_factory=ProcessPoolExecutor):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--days", type=int, default=35, help="window in days by file mtime (0 = all)")
    ap.add_argument("--project", help="only projects whose name contains this substring")
    ap.add_argument("--top", type=int, default=30, help="rows to print")
    ap.add_argument(
        "--projects-dir",
        default=os.path.expanduser("~/.claude/projects"),
        help="transcript root",
    )
    ap.add_argument(
        "--artifacts",
        action="append",
        default=[],
        metavar="PATH",
        help="also analyze spec/plan markdown under PATH (repeatable): bytes, "
             "fenced-code share, decision-ledger share",
    )
    args = ap.parse_args(argv)

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

    results = scan_paths([path for _idx, _is_root, path in jobs], executor_factory)
    per_session = defaultdict(list)
    for (idx, is_root, _path), result in zip(jobs, results):
        if result:
            per_session[idx].append((is_root, result))

    groups, retained_results, kept_sessions, kept_files = build_groups(
        sessions, per_session, args.project
    )

    if not groups:
        sys.exit("no sessions matched the filters")

    ordered = sorted(
        groups.items(), key=lambda kv: (kv[1]["cost"], total_tokens(kv[1])), reverse=True
    )

    def issue_label(issue):
        return "(no issue)" if issue is None else "(multi-issue)" if issue == MULTI_ISSUE else f"#{issue}"

    rows = []
    for (project, issue), g in ordered[: args.top]:
        rows.append([
            issue_label(issue),
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

    tot = fold_scan_totals(retained_results)
    for field in ("subagents", "skill_loads", "repeats"):
        tot[field] = sum(group[field] for group in groups.values())
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

    # ---- extended telemetry ------------------------------------------------

    print("\nOutcome, model & context per group (outcome is a final-message heuristic;"
          "\npeak-ctx = largest single-turn input+cache footprint in any of the group's transcripts):\n")
    ext_rows = []
    for (project, issue), g in ordered[: args.top]:
        ext_rows.append([
            issue_label(issue),
            project,
            group_outcome(g),
            counter_mix(g["models"], top=2, strip_prefix="claude-"),
            counter_mix(g["efforts"], top=2),
            human(g["peak_ctx"]),
            f"{sum(g['agents_by_type'].values()):,}",
            f"{g['interventions']:,}",
            f"{g['agents_killed']:,}",
        ])
    print_table(
        ext_rows,
        ["issue", "project", "outcome", "models", "effort", "peak-ctx", "agents", "nudges", "killed"],
        ["l", "l", "l", "l", "l", "r", "r", "r", "r"],
    )

    all_models = Counter()
    all_efforts = Counter()
    all_stops = Counter()
    all_phases = Counter()
    all_attr = Counter()
    all_agents = Counter()
    all_statuses = Counter()
    prompt_bytes = []
    result_bytes = []
    outcome_counts = Counter()
    killed = nudges = 0
    for g in groups.values():
        all_models.update(g["models"])
        all_efforts.update(g["efforts"])
        all_stops.update(g["stop_reasons"])
        all_phases.update(g["phase_turns"])
        all_attr.update(g["attr_turns"])
        all_agents.update(g["agents_by_type"])
        all_statuses.update(g["agent_statuses"])
        prompt_bytes.extend(g["agent_prompt_bytes"])
        result_bytes.extend(g["agent_result_bytes"])
        outcome_counts[group_outcome(g)] += 1
        killed += g["agents_killed"]
        nudges += g["interventions"]

    def counter_line(counter, top=8):
        return " | ".join(f"{k} {v:,}" for k, v in counter.most_common(top)) or "-"

    print(f"\nOutcomes (groups): {counter_line(outcome_counts)}")
    print(f"Models (turns): {counter_line(all_models)}")
    print(f"Effort (turns): {counter_line(all_efforts)}")
    print(f"Stop reasons (turns): {counter_line(all_stops)}; sessions with agents killed at exit: {killed:,}")
    print(f"Agent launches by type: {counter_line(all_agents)}")
    print(f"Agent result statuses: {counter_line(all_statuses)}")
    if prompt_bytes:
        print(
            f"Agent prompt bytes (n={len(prompt_bytes):,}): "
            f"p50 {human(percentile(prompt_bytes, 50))}  p90 {human(percentile(prompt_bytes, 90))}  "
            f"max {human(max(prompt_bytes))}"
        )
    if result_bytes:
        print(
            f"Agent result bytes (n={len(result_bytes):,}): "
            f"p50 {human(percentile(result_bytes, 50))}  p90 {human(percentile(result_bytes, 90))}  "
            f"max {human(max(result_bytes))}"
        )
    if all_phases:
        ordered_phases = " | ".join(
            f"P{k} {v:,}" for k, v in sorted(all_phases.items(), key=lambda kv: int(kv[0]))
        )
        print(f"Turns by textual phase marker (sessions that narrate 'Phase N'): {ordered_phases}")
    if all_attr:
        print(f"Turns by skill attribution: {counter_line(all_attr, top=10)}")
    print(f"User 'proceed' nudges (short continue-style messages): {nudges:,}")

    if args.artifacts:
        print("\nArtifact pass (spec/plan markdown under --artifacts paths):\n")
        print_artifact_stats(artifact_stats(args.artifacts))

    print(
        "\nNOTE: cache reads measure logical context re-processing (tokens the model"
        "\nattended to via prompt cache), and est $ applies public list prices — this is"
        "\ncomparative telemetry for run-over-run analysis, NOT billing data."
    )


if __name__ == "__main__":
    main()
