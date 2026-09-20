#!/usr/bin/env python3
"""Per-issue agent-cost telemetry for Claude Code and Codex sessions.

Scans ~/.claude/projects for root sessions (<project>/<session>.jsonl) plus their
subagent transcripts (<project>/<session>/subagents/**/*.jsonl) and reports token
spend and estimated list-price cost grouped by issue. `--strata` also mines the
Codex rollouts under ~/.codex/sessions, and `--format json` projects whichever
strata were selected into one `agent-cost-record` document instead of tables.

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
import hashlib
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# List price per million tokens: (input, output, cache_write_1h, cache_write_5m, cache_read).
# Matches the pricing model the transcript-mining report used, so numbers stay
# comparable to its 35-day baseline. claude-fable-5 is priced as Opus-class.
PRICING = {
    "opus": (15.0, 75.0, 30.0, 18.75, 1.50),
    "sonnet": (3.0, 15.0, 6.0, 3.75, 0.30),
    "haiku": (1.0, 5.0, 2.0, 1.25, 0.10),
}

SCHEMA_VERSION = 1
RECORD_KIND = "agent-cost-record"
EXECUTION_TELEMETRY_SCHEMA_VERSION = 1
EXECUTION_TELEMETRY_PRODUCER_VERSION = 1
TELEMETRY_REASON_CODES: tuple[str, ...] = (
    "timestamp_missing", "request_missing", "request_host_missing",
    "request_host_conflict", "result_missing", "child_missing",
    "dispatch_missing", "role_ambiguous", "execution_model_missing",
    "execution_effort_missing", "runtime_version_missing",
    "source_unsupported", "cohort_incomplete",
)
ROUTING_AUTHORITIES = ("assistant-execution", "codex-rollout")
SCHEDULING_METRICS = ("spawn_attempts", "capacity_rejections", "waits", "follow_ups",
                      "wait_input_tokens", "covered_input_tokens", "slot_capacity_seconds",
                      "claimed_slot_seconds")
# The one authoritative home for the comparative-telemetry caveat (D18): the
# text footer prints it behind "NOTE: " and the record carries it as `notes`.
DISCLAIMER = (
    "cache reads measure logical context re-processing (tokens the model"
    "\nattended to via prompt cache), and est $ applies public list prices — this is"
    "\ncomparative telemetry for run-over-run analysis, NOT billing data."
)

TOKEN_FIELDS = ("fresh", "cache_create", "cache_read", "output")
SUM_FIELDS = TOKEN_FIELDS + ("cost", "turns")
# Scalar extras summed (or maxed, for peak_ctx) across a group's transcripts.
EXTRA_INT_FIELDS = ("agents_killed", "interventions")
# Counter-valued extras merged across a group's transcripts.
COUNTER_FIELDS = ("models", "efforts", "stop_reasons", "phase_turns", "attr_turns",
                  "agents_by_type", "agent_statuses", "cost_by_family")
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
    cost_by_family = Counter()
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

            family = model_family(model)
            p_in, p_out, p_1h, p_5m, p_read = PRICING[family]
            message_cost = (
                f_in * p_in + c_out * p_out + cw_1h * p_1h + cw_5m * p_5m + c_read * p_read
            ) / 1e6
            cost += message_cost
            cost_by_family[family] += message_cost

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
        "cost_by_family": dict(cost_by_family),
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


def codex_usage(usage, *, modern):
    """Return validated Codex usage, or ``None`` for an unusable observation.

    Legacy token-count records predate some of the subset counters, so those
    omitted fields are zero there.  A modern response record has the complete
    shape and must say so explicitly.
    """
    if not isinstance(usage, dict):
        return None
    required = ("input_tokens", "output_tokens")
    optional = ("cached_input_tokens", "cache_write_input_tokens",
                "reasoning_output_tokens")
    if modern:
        required += optional + ("total_tokens",)
    values = {}
    fields = required if modern else required + optional
    for field in fields:
        if field not in usage:
            if modern or field not in optional:
                return None
            values[field] = 0
            continue
        value = usage[field]
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        values[field] = value
    if not modern:
        total = usage.get("total_tokens")
        if total is None:
            values["total_tokens"] = None
        elif (not isinstance(total, int) or isinstance(total, bool)
              or total < 0):
            return None
        else:
            values["total_tokens"] = total
    if (values["cached_input_tokens"] + values["cache_write_input_tokens"]
            > values["input_tokens"]):
        return None
    if values["reasoning_output_tokens"] > values["output_tokens"]:
        return None
    if modern and values["total_tokens"] != (
            values["input_tokens"] + values["output_tokens"]):
        return None
    return values


def codex_usage_key(usage):
    """A stable cumulative signature and duplicate-comparison key."""
    return tuple(usage[field] for field in (
        "input_tokens", "cached_input_tokens", "cache_write_input_tokens",
        "output_tokens", "reasoning_output_tokens", "total_tokens",
    ))


def add_codex_usage(result, usages, source):
    """Replace a rollout's selected usage without exposing response identities."""
    input_total = cache_create = cache_read = output = reasoning = 0
    peak_ctx = 0
    for usage in usages:
        input_total += usage["input_tokens"]
        cache_read += usage["cached_input_tokens"]
        cache_create += usage["cache_write_input_tokens"]
        output += usage["output_tokens"]
        reasoning += usage["reasoning_output_tokens"]
        peak_ctx = max(peak_ctx, usage["input_tokens"])
    result.update(
        fresh=input_total - cache_read - cache_create,
        cache_create=cache_create,
        cache_read=cache_read,
        output=output,
        reasoning=reasoning,
        input_total=input_total,
        peak_ctx=peak_ctx,
        turns=len(usages),
        usage_measured=bool(usages),
    )
    result["measurement"]["selected_source_counts"] = {
        "modern": len(usages) if source == "modern" else 0,
        "legacy": len(usages) if source == "legacy" else 0,
    }


def select_modern_observations(observations):
    """Select unambiguous modern observations and count every participant.

    The observation list is intentionally retained only until collection: its
    response identities are required to make copied files and in-file replays
    produce the same coverage counters.
    """
    by_identity = defaultdict(list)
    for identity, usage in observations:
        by_identity[identity].append(usage)
    selected = []
    duplicates = ambiguous = 0
    for identity in sorted(by_identity, key=lambda value: (value[0] or "", value[1])):
        usages = by_identity[identity]
        if len({codex_usage_key(usage) for usage in usages}) != 1:
            ambiguous += len(usages)
            continue
        selected.append(usages[0])
        duplicates += len(usages) - 1
    return selected, duplicates, ambiguous


def codex_is_root(payload):
    """Use each format's metadata shape to classify root and child rollouts."""
    source = payload.get("source")
    if source == "cli":
        return True
    if isinstance(source, dict) and isinstance(source.get("subagent"), dict):
        return False
    return payload.get("thread_source") == "user"


def new_codex_measurement():
    """Public, additive coverage metadata for one selected Codex run."""
    return {
        "selected_source_counts": {"modern": 0, "legacy": 0},
        "duplicate_observations_skipped": 0,
        "missing_usage_observations": 0,
        "invalid_usage_observations": 0,
        "ambiguous_legacy_observations": 0,
        "ambiguous_modern_observations": 0,
        "legacy_observations_excluded": 0,
        "files_selected": 0,
        "files_with_usage": 0,
    }


def scan_codex_file(path):
    """Parse one Codex rollout, retaining only transient response identities.

    Modern response usage wins for the rollout.  The collector later performs
    the same identity comparison across selected files; response IDs never
    reach the JSON record.
    """
    meta = None
    models = Counter()
    efforts = Counter()
    legacy = []
    previous_cumulative = None
    modern_observations = []
    modern_seen = 0
    measurement = new_codex_measurement()

    try:
        fh = open(path, "r", errors="replace")
    except OSError:
        return None
    with fh:
        for line in fh:
            # Cheap prefilter, matching scan_file's style: only these three
            # record kinds carry identity, usage or the model/effort mix.
            if ("session_meta" not in line and "token_count" not in line
                    and "token_usage_record" not in line
                    and "turn_context" not in line):
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                continue
            kind = rec.get("type")
            payload = rec.get("payload") or {}
            if kind == "session_meta":
                if meta is None:  # a later session_meta is ignored
                    session_id = payload.get("session_id") or payload.get("id")
                    meta = {
                        "session_id": session_id,
                        "rollout_id": payload.get("id") or session_id,
                        "is_root": codex_is_root(payload),
                        "cwd": payload.get("cwd") or "",
                    }
            elif kind == "event_msg" and payload.get("type") == "token_count":
                info = payload.get("info") or {}
                last = codex_usage(info.get("last_token_usage"), modern=False)
                if last is None:
                    if info.get("last_token_usage") is None:
                        measurement["missing_usage_observations"] += 1
                    else:
                        measurement["invalid_usage_observations"] += 1
                    continue
                cumulative = codex_usage(info.get("total_token_usage"), modern=False)
                if cumulative is None:
                    measurement["ambiguous_legacy_observations"] += 1
                    if info.get("total_token_usage") is None:
                        measurement["missing_usage_observations"] += 1
                    else:
                        measurement["invalid_usage_observations"] += 1
                    legacy.append(last)
                    continue
                signature = codex_usage_key(cumulative)
                if signature == previous_cumulative:
                    measurement["duplicate_observations_skipped"] += 1
                    continue
                # A changed cumulative signature is either progress or a new
                # epoch after compaction/reset.  In both cases `last` is one
                # observed completion; the cumulative total is never summed.
                previous_cumulative = signature
                legacy.append(last)
            elif kind == "token_usage_record":
                modern_seen += 1
                response_id = payload.get("response_id")
                usage = codex_usage(payload.get("usage"), modern=True)
                if not isinstance(response_id, str) or not response_id:
                    measurement["invalid_usage_observations"] += 1
                    continue
                if usage is None:
                    if payload.get("usage") is None:
                        measurement["missing_usage_observations"] += 1
                    else:
                        measurement["invalid_usage_observations"] += 1
                    continue
                thread_id = payload.get("thread_id") or (
                    meta["session_id"] if meta else None)
                if not isinstance(thread_id, str) or not thread_id:
                    measurement["invalid_usage_observations"] += 1
                    continue
                identity = (thread_id, response_id)
                modern_observations.append((identity, usage))
            elif kind == "turn_context":
                if payload.get("model"):
                    models[payload["model"]] += 1
                if payload.get("effort"):
                    efforts[payload["effort"]] += 1

    if meta is None:
        return None
    result = {
        "session_id": meta["session_id"],
        "rollout_id": meta["rollout_id"],
        "is_root": meta["is_root"],
        "cwd": meta["cwd"],
        "models": dict(models),
        "efforts": dict(efforts),
        "measurement": measurement,
        "modern_observations": modern_observations,
        "modern_seen": modern_seen,
        "legacy_records": legacy,
        "path": str(path),
    }
    if modern_seen:
        measurement["legacy_observations_excluded"] = len(legacy)
        selected, duplicates, ambiguous = select_modern_observations(modern_observations)
        measurement["duplicate_observations_skipped"] += duplicates
        measurement["ambiguous_modern_observations"] += ambiguous
        result["modern_duplicate_observations"] = duplicates
        result["modern_ambiguous_observations"] = ambiguous
        add_codex_usage(result, selected, "modern")
    else:
        result["modern_duplicate_observations"] = 0
        result["modern_ambiguous_observations"] = 0
        add_codex_usage(result, legacy, "legacy")
    return result


# The only keys a Codex rollout can measure. Anything Claude-only is simply
# absent, which is what makes it `null` in the record without an exception list.
CODEX_SUM_FIELDS = ("fresh", "cache_create", "cache_read", "output", "reasoning", "turns")


def new_codex_group():
    group = dict.fromkeys(CODEX_SUM_FIELDS + ("sessions", "subagents", "peak_ctx"), 0)
    group["models"] = {}
    group["efforts"] = {}
    group["measurement"] = new_codex_measurement()
    group["usage_measured"] = False
    return group


def collect_codex_groups(root, cutoff, project_filter=None,
                         executor_factory=ProcessPoolExecutor):
    """Group Codex rollouts into {(project, issue): group} by session thread."""
    if not root.is_dir():
        sys.exit(f"no Codex session root at {root}")
    paths = sorted(
        path for path in root.rglob("*.jsonl")
        if cutoff is None or path.stat().st_mtime >= cutoff
    )
    results = [r for r in scan_paths(paths, executor_factory, scanner=scan_codex_file) if r]

    # Source choice belongs to a stable rollout, even when its records are
    # copied across selected files.  Resolve that choice before cross-file
    # response deduplication so legacy copies cannot restore modern usage.
    rollouts = defaultdict(list)
    for result in results:
        rollouts[(result["session_id"], result["rollout_id"])].append(result)

    identities = defaultdict(list)
    for rollout in rollouts.values():
        has_modern = any(result["modern_seen"] for result in rollout)
        for result in rollout:
            measurement = result["measurement"]
            measurement["duplicate_observations_skipped"] -= result[
                "modern_duplicate_observations"]
            measurement["ambiguous_modern_observations"] -= result[
                "modern_ambiguous_observations"]
            measurement["legacy_observations_excluded"] = 0
            add_codex_usage(result, [], None)
            result["selected_modern_usages"] = []
            if has_modern:
                measurement["legacy_observations_excluded"] += len(result["legacy_records"])
                for identity, usage in result["modern_observations"]:
                    identities[identity].append((result, usage))
            else:
                add_codex_usage(result, result["legacy_records"], "legacy")

    # Modern response identities are thread-scoped and deduped across every
    # selected modern rollout. Prefer a root occurrence when a child copied it;
    # all duplicate or conflicting participants receive the same accounting.
    for identity in sorted(identities, key=lambda value: (value[0] or "", value[1])):
        observations = identities[identity]
        usages = {codex_usage_key(usage) for _result, usage in observations}
        if len(usages) != 1:
            for result, _usage in observations:
                result["measurement"]["ambiguous_modern_observations"] += 1
            continue
        chosen_index, (chosen, usage) = min(enumerate(observations), key=lambda item: (
            not item[1][0]["is_root"], item[1][0]["path"], item[0],
        ))
        chosen["selected_modern_usages"].append(usage)
        for index, (result, _usage) in enumerate(observations):
            if index != chosen_index:
                result["measurement"]["duplicate_observations_skipped"] += 1
    for result in results:
        if result["modern_seen"]:
            add_codex_usage(result, result["selected_modern_usages"], "modern")

    threads = defaultdict(list)
    for result in results:
        threads[result["session_id"]].append(result)

    groups = {}
    for session_id in sorted(threads, key=lambda sid: sid or ""):
        rollouts = threads[session_id]
        root_cwds = Counter(r["cwd"] for r in rollouts if r["is_root"] and r["cwd"])
        if not root_cwds:
            root_cwds = Counter(r["cwd"] for r in rollouts if r["cwd"])
        # Codex has no encoded project-dir name; the literal stands in for one
        # and matches neither ISSUE_RE nor a project, so both helpers fall
        # through to the cwd evidence.
        project = project_name("codex", root_cwds)
        if project_filter and project_filter.lower() not in project.lower():
            continue
        issue = issue_key("codex", root_cwds)

        group = groups.setdefault((project, issue), new_codex_group())
        models = Counter(group["models"])
        efforts = Counter(group["efforts"])
        for result in rollouts:
            if result["usage_measured"]:
                for field in CODEX_SUM_FIELDS:
                    group[field] += result[field]
                group["usage_measured"] = True
            if result["peak_ctx"] is not None:
                group["peak_ctx"] = max(group["peak_ctx"], result["peak_ctx"])
            models.update(result["models"])
            efforts.update(result["efforts"])
            for field, value in result["measurement"].items():
                if isinstance(value, dict):
                    for key, count in value.items():
                        group["measurement"][field][key] += count
                else:
                    group["measurement"][field] += value
            group["measurement"]["files_selected"] += 1
            if result["usage_measured"]:
                group["measurement"]["files_with_usage"] += 1
            if result["is_root"]:
                group["sessions"] += 1
            else:
                group["subagents"] += 1
        group["models"] = dict(models)
        group["efforts"] = dict(efforts)
    # A project/issue can span several session threads. Keep its accumulators
    # numeric until all of those threads have contributed, then project a
    # genuinely unmeasured group as null.
    for group in groups.values():
        if not group["usage_measured"]:
            for field in CODEX_SUM_FIELDS:
                group[field] = None
            group["peak_ctx"] = None
    return groups


def scan_paths(paths, executor_factory=ProcessPoolExecutor, scanner=None):
    """Scan in order, falling back all-or-nothing when a process pool fails.

    `scanner` defaults to `scan_file` at call time, not at `def` time, so a test
    that patches the module attribute still reaches both branches (D41).
    """
    if scanner is None:
        scanner = scan_file
    paths = list(paths)
    try:
        with executor_factory(max_workers=os.cpu_count() or 4) as pool:
            return list(pool.map(scanner, paths, chunksize=8))
    except Exception as error:
        print(
            f"Process pool unavailable ({type(error).__name__}); scanning sequentially.",
            file=sys.stderr,
        )
    return [scanner(path) for path in paths]


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


# Record projection. A run's scalars are read with .get: a key a stratum never
# measures is absent from its group and projects as null, never as a truthful 0.
RUN_SCALAR_FIELDS = ("peak_ctx", "turns", "sessions", "subagents",
                     "skill_loads", "repeats", "agents_killed", "interventions")
RUN_COUNTER_FIELDS = ("models", "efforts", "stop_reasons", "phase_turns",
                      "attr_turns", "agents_by_type", "agent_statuses")
RUN_DISTRIBUTION_FIELDS = ("agent_prompt_bytes", "agent_result_bytes")
RECORD_TOKEN_FIELDS = ("input_total", "fresh", "cache_create", "cache_read",
                       "output", "reasoning")


def canonical_digest(body):
    """Contract: 'sha256:' + sha256 over canonical JSON of `body` (D9)."""
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


RFC3339_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")


def parse_rfc3339_utc(value: str) -> datetime:
    """Parse an RFC3339 instant and return an aware UTC datetime."""
    if not isinstance(value, str) or not RFC3339_UTC_RE.fullmatch(value):
        raise ValueError("timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00" if value.endswith("Z") else value)
    except ValueError as error:
        raise ValueError("invalid RFC3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timestamp must include an offset")
    return parsed.astimezone(timezone.utc)


def format_rfc3339_utc(value):
    return value.isoformat().replace("+00:00", "Z")


def event_in_window(value: object, start: datetime | None, end: datetime | None) -> bool | None:
    """Whether a source event is in [start, end), or None when unknowable."""
    try:
        event = parse_rfc3339_utc(value)
    except ValueError:
        return None
    return (start is None or event >= start) and (end is None or event < end)


def coverage(eligible: int, paired: int, reasons: Counter) -> dict:
    items = [{"code": code, "count": reasons[code]} for code in sorted(reasons) if reasons[code]]
    if not items:
        state = "full"
    elif paired:
        state = "partial"
    else:
        state = "none"
    return {"state": state, "eligible_events": eligible, "paired_events": paired,
            "reasons": items}


def _routing_coverage(events, extra_reasons=None):
    reasons = Counter()
    eligible = paired = 0
    for event in events:
        eligible += 1
        paired += bool(event["paired"])
        reasons.update(event["reasons"])
    reasons.update(extra_reasons or {})
    return coverage(eligible, paired, reasons)


def _merge_coverage(values):
    reasons = Counter()
    eligible = paired = 0
    for value in values:
        eligible += value["eligible_events"]
        paired += value["paired_events"]
        reasons.update({item["code"]: item["count"] for item in value["reasons"]})
    return coverage(eligible, paired, reasons)


def cohort_digest(identities: list[tuple[str, ...]]) -> str:
    """Return a stable digest for the bounded cohort identities."""
    return canonical_digest(sorted([list(identity) for identity in identities]))


def merge_metric_coverage(metrics: list[dict]) -> dict:
    """Merge scheduling coverage without treating unavailable cohorts as full."""
    return _merge_coverage(metrics)


def unsupported_metric(reason_count=1):
    return {"value": None, "coverage": coverage(0, 0, Counter({"source_unsupported": reason_count})),
            "cohort_digest": None}


def _metric(value, metric_coverage, digest):
    if metric_coverage["state"] != "full":
        value = None
    if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
        raise ValueError("scheduling metric value must be a non-negative integer")
    return {"value": value, "coverage": metric_coverage, "cohort_digest": digest if value is not None else None}


def _validate_scheduling(metrics, event_window):
    for name, metric in metrics.items():
        if metric["coverage"]["state"] != "full" and metric["value"] is not None:
            raise ValueError("incomplete scheduling coverage cannot project a value")
        value = metric["value"]
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or value < 0):
            raise ValueError("scheduling metric value must be a non-negative integer")
    for left, right in (("wait_input_tokens", "covered_input_tokens"),
                        ("slot_capacity_seconds", "claimed_slot_seconds")):
        a, b = metrics[left], metrics[right]
        if (a["value"] is None) != (b["value"] is None):
            raise ValueError("paired scheduling metrics must project together")
        digest = a["cohort_digest"]
        if a["value"] is not None and (a["coverage"]["state"] != "full" or
                                        b["coverage"]["state"] != "full" or
                                        not isinstance(digest, str) or
                                        not re.fullmatch(r"sha256:[0-9a-f]{64}", digest) or
                                        digest != b["cohort_digest"]):
            raise ValueError("paired scheduling metrics require one full cohort")
    capacity, claimed = metrics["slot_capacity_seconds"], metrics["claimed_slot_seconds"]
    if capacity["value"] is not None:
        if capacity["cohort_digest"] != canonical_digest(event_window):
            raise ValueError("slot metrics require the event-window cohort")
        if claimed["value"] > capacity["value"]:
            raise ValueError("claimed slots exceed capacity")


def _spawn_metric(source, launches, start, end):
    if source != "claude":
        return unsupported_metric()
    reasons = Counter()
    identities = []
    eligible = paired = 0
    for tool_id, timestamps in launches.items():
        selected = {event_in_window(timestamp, start, end) for timestamp in timestamps}
        if selected == {False}:
            continue
        eligible += 1
        if None in selected:
            reasons["timestamp_missing"] += 1
        elif len({format_rfc3339_utc(parse_rfc3339_utc(timestamp)) for timestamp in timestamps}) != 1:
            # Replayed launch records must identify one event instant. Conflicting
            # timestamps leave that instant unavailable to the bounded cohort.
            reasons["timestamp_missing"] += 1
        else:
            paired += 1
            identities.append((tool_id,))
    if start is None or end is None:
        reasons["cohort_incomplete"] += 1
    metric_coverage = coverage(eligible, paired, reasons)
    return _metric(len(identities), metric_coverage, cohort_digest(identities))


def _scheduling(source, launches, start, end):
    metrics = {"spawn_attempts": _spawn_metric(source, launches, start, end)}
    metrics.update({name: unsupported_metric() for name in SCHEDULING_METRICS[1:]})
    _validate_scheduling(metrics, {"start": format_rfc3339_utc(start) if start else None,
                                   "end": format_rfc3339_utc(end) if end else None})
    return metrics


def _scheduling_coverage(metrics):
    return {name: metrics[name]["coverage"] for name in SCHEDULING_METRICS}


def _empty_telemetry(selected, start=None, end=None):
    versions = {source: None for source in selected}
    contributions = {
        source: coverage(0, 0, Counter({"runtime_version_missing": 1,
                                         "cohort_incomplete": 1 if start is None else 0}))
        for source in selected
    }
    scheduling = {source: _scheduling_coverage(_scheduling(source, {}, start, end))
                  for source in selected}
    aggregate = _merge_coverage(contributions.values()) if contributions else coverage(
        0, 0, Counter({"cohort_incomplete": 1})
    )
    return {
        "schema_version": EXECUTION_TELEMETRY_SCHEMA_VERSION,
        "producer": {"name": "agent-costs", "version": EXECUTION_TELEMETRY_PRODUCER_VERSION,
                     "harness_versions": versions},
        "event_window": {"start": format_rfc3339_utc(start) if start else None,
                         "end": format_rfc3339_utc(end) if end else None},
        "source_coverage": {"routing": aggregate,
                            "scheduling": {name: merge_metric_coverage(
                                [item[name] for item in scheduling.values()])
                                           for name in SCHEDULING_METRICS},
                            "source_only": {source: {"routing": contribution,
                                                      "scheduling": scheduling[source]}
                                            for source, contribution in contributions.items()}},
        "runs": [],
    }


def _read_jsonl(path):
    try:
        with open(path, "r", errors="replace") as fh:
            for line in fh:
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _request_host(value, target, reasons):
    if "host" not in value:
        return target
    host = value["host"]
    if not isinstance(host, str) or host == "":
        reasons["request_host_missing"] += 1
    elif host != target:
        reasons["request_host_conflict"] += 1
    else:
        return target
    return None


def _declaration(value, reasons):
    dispatch = value.get("dispatch_id") if isinstance(value.get("dispatch_id"), str) else None
    role = value.get("role") if isinstance(value.get("role"), str) else None
    subagent_type = value.get("subagent_type")
    # The matrix is deliberately not read here. These are the source's known
    # canonical role spellings; shared transport types remain ambiguous.
    canonical = {"bookkeeper", "codex-transport", "conformance-reviewer", "explorer",
                 "implementer", "issue-owner", "mechanic", "researcher", "reviewer",
                 "reviewer-lite", "ship-owner"}
    if role in canonical:
        authority = "structured-dispatch" if dispatch else "runtime-agent-type"
        return {"dispatch_id": dispatch, "role": role, "authority": authority}
    if subagent_type in canonical - {"reviewer", "mechanic"}:
        return {"dispatch_id": dispatch, "role": subagent_type,
                "authority": "runtime-agent-type"}
    reasons["role_ambiguous"] += 1
    if dispatch is None:
        reasons["dispatch_missing"] += 1
    return {"dispatch_id": dispatch, "role": None, "authority": "unknown"}


def _escalation(value):
    if "source_dispatch_id" not in value and "reason_code" not in value:
        return None
    return {"source_dispatch_id": value.get("source_dispatch_id")
            if isinstance(value.get("source_dispatch_id"), str) else None,
            "reason_code": value.get("reason_code")
            if isinstance(value.get("reason_code"), str) else None}


def _add_observation(bucket, observation, event_at):
    key = json.dumps({k: observation[k] for k in ("declaration", "requested", "configured",
                                                    "observed", "escalation")},
                     sort_keys=True, separators=(",", ":"))
    current = bucket.get(key)
    if current is None:
        current = dict(observation, count=0, first_event_at=event_at, last_event_at=event_at)
        bucket[key] = current
    current["count"] += 1
    current["first_event_at"] = min(current["first_event_at"], event_at)
    current["last_event_at"] = max(current["last_event_at"], event_at)


def collect_execution_telemetry(selected: tuple[str, ...], claude_root: Path | None,
                                codex_root: Path | None, start: datetime | None,
                                end: datetime | None, project_filter: str | None,
                                executor_factory) -> dict:
    """Independently correlate routing evidence from every selected source file."""
    del executor_factory  # correlation requires a deterministic global index
    source_versions = {source: set() for source in selected}
    runs = defaultdict(lambda: {"events": [], "observations": {}, "reasons": Counter(),
                                "launches": defaultdict(list)})
    source_events = defaultdict(list)
    source_reasons = defaultdict(Counter)
    unassigned_events = defaultdict(list)

    if "claude" in selected and claude_root and claude_root.is_dir():
        children = defaultdict(list)
        roots = []
        for path in sorted(claude_root.rglob("*.jsonl")):
            records = list(_read_jsonl(path))
            if "subagents" in path.parts:
                for rec in records:
                    if rec.get("type") == "assistant" and rec.get("agentId"):
                        children[(path.parent.parent.name, str(rec["agentId"]))].append(rec)
            else:
                roots.append((path, records))
        for path, records in roots:
            root_cwds = Counter()
            for rec in records:
                if rec.get("type") == "assistant" and rec.get("cwd"):
                    root_cwds[rec["cwd"]] += 1
            project = project_name(path.parent.name, root_cwds)
            if project_filter and project_filter.lower() not in project.lower():
                continue
            run_id = "claude:%s:%s" % (project, "none" if issue_key(path.parent.name, root_cwds) is None
                                        else issue_key(path.parent.name, root_cwds))
            runs[run_id]
            requests, results = {}, defaultdict(list)
            for rec in records:
                if rec.get("type") == "assistant":
                    version = rec.get("version")
                    if isinstance(version, str) and version:
                        source_versions["claude"].add(version)
                    for block in ((rec.get("message") or {}).get("content") or []):
                        if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") in ("Agent", "Task"):
                            bid = block.get("id")
                            if isinstance(bid, str) and bid not in requests:
                                requests[bid] = (block.get("input") if isinstance(block.get("input"), dict) else {}, rec.get("timestamp"))
                            if isinstance(bid, str):
                                runs[run_id]["launches"][bid].append(rec.get("timestamp"))
                elif rec.get("type") == "user":
                    tur = rec.get("toolUseResult")
                    content = (rec.get("message") or {}).get("content")
                    if isinstance(tur, dict) and isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "tool_result" and isinstance(block.get("tool_use_id"), str):
                                results[block["tool_use_id"]].append(tur.get("agentId"))
            used_agents = set()
            for tool_id, (request, _request_at) in requests.items():
                reasons = Counter()
                candidates = results.get(tool_id, [])
                agent_id = candidates[0] if len(candidates) == 1 else None
                if agent_id:
                    used_agents.add(str(agent_id))
                if not agent_id:
                    reasons["result_missing"] += 1
                executions = children.get((path.stem, str(agent_id)), []) if agent_id else []
                if not executions:
                    reasons["child_missing"] += 1
                    request_window = event_in_window(_request_at, start, end)
                    if request_window is not False:
                        local = Counter(reasons)
                        if request_window is None:
                            local["timestamp_missing"] += 1
                        event = {"paired": False, "reasons": local}
                        source_events["claude"].append(event); runs[run_id]["events"].append(event)
                    continue
                # A child transcript normally contains several assistant turns.
                # The final timestamped assistant record is the deterministic
                # execution-side evidence for this completed launch; selecting
                # one avoids turning a multi-turn child into duplicate events.
                execution = max(enumerate(executions), key=lambda item: (
                    parse_rfc3339_utc(item[1].get("timestamp"))
                    if event_in_window(item[1].get("timestamp"), None, None) is not None
                    else datetime.min.replace(tzinfo=timezone.utc), item[0]))[1]
                for execution in (execution,):
                    in_window = event_in_window(execution.get("timestamp"), start, end)
                    if in_window is False:
                        continue
                    local = Counter(reasons)
                    if in_window is None:
                        local["timestamp_missing"] += 1
                        source_events["claude"].append({"paired": False, "reasons": local})
                        runs[run_id]["events"].append({"paired": False, "reasons": local})
                        continue
                    requested_host = _request_host(request, "claude", local)
                    declaration = _declaration(request, local)
                    if not request.get("model") or not request.get("effort"):
                        local["request_missing"] += 1
                    msg = execution.get("message") or {}
                    model, effort = msg.get("model"), execution.get("effort")
                    if not model: local["execution_model_missing"] += 1
                    if not effort: local["execution_effort_missing"] += 1
                    # Pairing proves request-to-child correlation.  Missing
                    # execution tiers remain paired observations so the
                    # consumer can report their explicit inconclusive state.
                    paired = True
                    version = execution.get("version")
                    if isinstance(version, str) and version:
                        source_versions["claude"].add(version)
                    event = {"paired": paired, "reasons": local}
                    source_events["claude"].append(event); runs[run_id]["events"].append(event)
                    obs = {"declaration": declaration,
                           "requested": {"host": requested_host, "model": request.get("model"), "effort": request.get("effort")},
                           "configured": {"host": None, "model": None, "effort": None},
                           "observed": {"host": "claude", "model": model, "effort": effort,
                                        "authority": "assistant-execution"},
                           "escalation": _escalation(request)}
                    _add_observation(runs[run_id]["observations"], obs, format_rfc3339_utc(parse_rfc3339_utc(execution["timestamp"])))
            for (session_id, agent_id), executions in children.items():
                if session_id != path.stem or agent_id in used_agents:
                    continue
                for execution in executions:
                    verdict = event_in_window(execution.get("timestamp"), start, end)
                    if verdict is not False:
                        why = Counter({"request_missing": 1})
                        if verdict is None:
                            why["timestamp_missing"] += 1
                        event = {"paired": False, "reasons": why}
                        source_events["claude"].append(event); runs[run_id]["events"].append(event)

    if "codex" in selected and codex_root and codex_root.is_dir():
        # Mirror collect_codex_groups: a thread's root rollout CWD owns its
        # project/issue identity, with all-CWD fallback only when no root exists.
        thread_cwds = defaultdict(lambda: (Counter(), Counter()))
        for candidate in sorted(codex_root.rglob("*.jsonl")):
            for candidate_rec in _read_jsonl(candidate):
                if candidate_rec.get("type") != "session_meta":
                    continue
                candidate_payload = candidate_rec.get("payload") or {}
                session_id = candidate_payload.get("session_id") or candidate_payload.get("id")
                cwd = candidate_payload.get("cwd") or ""
                if session_id and cwd:
                    all_cwds, root_cwds = thread_cwds[session_id]
                    all_cwds[cwd] += 1
                    if codex_is_root(candidate_payload):
                        root_cwds[cwd] += 1
                break
        for path in sorted(codex_root.rglob("*.jsonl")):
            records = list(_read_jsonl(path)); meta = next((r for r in records if r.get("type") == "session_meta"), None)
            if not meta: continue
            payload = meta.get("payload") or {}; version = payload.get("cli_version")
            session_id = payload.get("session_id") or payload.get("id")
            all_cwds, root_cwds = thread_cwds.get(session_id, (Counter(), Counter()))
            canonical_cwds = root_cwds or all_cwds
            project = project_name("codex", canonical_cwds)
            if project_filter and project_filter.lower() not in project.lower():
                continue
            spawn = ((payload.get("source") or {}).get("subagent") or {}).get("thread_spawn") if isinstance(payload.get("source"), dict) else None
            if not isinstance(spawn, dict):
                # A subagent rollout is execution-side evidence even when its
                # structured launch was lost; do not manufacture full zero coverage.
                if payload.get("thread_source") == "subagent" or payload.get("source"):
                    verdict = event_in_window(meta.get("timestamp"), start, end)
                    if verdict is not False:
                        reasons = Counter({"request_missing": 1})
                        if verdict is None:
                            reasons["timestamp_missing"] += 1
                        unassigned_events["codex"].append({"paired": False, "reasons": reasons})
                continue
            issue = issue_key("codex", canonical_cwds)
            run_id = "codex:%s:%s" % (project, "none" if issue is None else issue)
            contexts = [r for r in records if r.get("type") == "turn_context"] or [meta]
            for context in contexts[:1]:
                verdict = event_in_window(context.get("timestamp"), start, end)
                local = Counter()
                if verdict is False: continue
                if verdict is None:
                    local["timestamp_missing"] += 1; paired = False
                else: paired = True
                if isinstance(version, str) and version:
                    source_versions["codex"].add(version)
                requested_host = _request_host(spawn, "codex", local)
                declaration = _declaration({"role": spawn.get("agent_role"), "dispatch_id": spawn.get("dispatch_id")}, local)
                if not spawn.get("model") or not spawn.get("effort"):
                    local["request_missing"] += 1
                configured = (context.get("payload") or {})
                local["execution_model_missing"] += 1; local["execution_effort_missing"] += 1
                event = {"paired": paired, "reasons": local}
                source_events["codex"].append(event); runs[run_id]["events"].append(event)
                if verdict is not None:
                    obs = {"declaration": declaration,
                           "requested": {"host": requested_host, "model": spawn.get("model"), "effort": spawn.get("effort")},
                           "configured": {"host": "codex", "model": configured.get("model"), "effort": configured.get("effort")},
                           "observed": {"host": "codex", "model": None, "effort": None, "authority": "codex-rollout"},
                           "escalation": _escalation(spawn)}
                    _add_observation(runs[run_id]["observations"], obs, format_rfc3339_utc(parse_rfc3339_utc(context["timestamp"])))

    source_only, projected_runs = {}, []
    run_sources = {run_id.split(":", 1)[0] for run_id in runs}
    for source in selected:
        if not source_versions[source]:
            if source in run_sources:
                first = next((value for key, value in runs.items() if key.startswith(source + ":")), None)
                if first is not None:
                    first["reasons"]["runtime_version_missing"] += 1
            else:
                source_reasons[source]["runtime_version_missing"] += 1
        if start is None:
            target = next((v for k, v in runs.items() if k.startswith(source + ":")), None)
            (target["reasons"] if target else source_reasons[source])["cohort_incomplete"] += 1
    for run_id in sorted(runs):
        item = runs[run_id]; routing = _routing_coverage(item["events"], item["reasons"])
        projected_runs.append({"run_id": run_id, "routing": {"coverage": routing,
                              "observations": sorted(item["observations"].values(), key=lambda x: json.dumps(x, sort_keys=True))}, "scheduling": {}})
    for source in selected:
        if source not in run_sources or unassigned_events[source]:
            source_only[source] = {"routing": _routing_coverage(
                unassigned_events[source] if source in run_sources else source_events[source],
                source_reasons[source]), "scheduling": _scheduling_coverage(
                    _scheduling(source, {}, start, end))}
    for run, item in zip(projected_runs, (runs[run_id] for run_id in sorted(runs))):
        run["scheduling"] = _scheduling(run["run_id"].split(":", 1)[0], item["launches"], start, end)
    top = _merge_coverage([run["routing"]["coverage"] for run in projected_runs] +
                          [item["routing"] for item in source_only.values()])
    return {"schema_version": EXECUTION_TELEMETRY_SCHEMA_VERSION,
            "producer": {"name": "agent-costs", "version": EXECUTION_TELEMETRY_PRODUCER_VERSION,
                         "harness_versions": {source: sorted(source_versions[source]) or None for source in selected}},
            "event_window": {"start": format_rfc3339_utc(start) if start else None,
                             "end": format_rfc3339_utc(end) if end else None},
            "source_coverage": {"routing": top,
                                "scheduling": {name: merge_metric_coverage(
                                    [run["scheduling"][name]["coverage"] for run in projected_runs] +
                                    [item["scheduling"][name] for item in source_only.values()])
                                               for name in SCHEDULING_METRICS},
                                "source_only": source_only}, "runs": projected_runs}


def sum_or_none(values):
    """Total the values, or None when nothing was measured.

    Nothing was measured when a value is itself an absent measurement, and
    equally when there is no value at all: `sum([])` is 0, and a stratum that
    matched no runs has not measured zero tokens, it has measured nothing.
    """
    values = list(values)
    if not values or any(value is None for value in values):
        return None
    return sum(values)


def merge_families(family_maps):
    """Family-keyed sum across runs, or None when any run carries no cost split."""
    family_maps = list(family_maps)
    if any(families is None for families in family_maps):
        return None
    merged = Counter()
    for families in family_maps:
        merged.update(families)
    return dict(merged)


def project_run(stratum, key, g):
    """Project one group into a run object. Reads `g`; never mutates it."""
    project, issue = key
    segment = "none" if issue is None else "multi" if issue == MULTI_ISSUE else str(issue)
    tokens = {field: g.get(field) for field in TOKEN_FIELDS}
    tokens["input_total"] = sum_or_none(
        tokens[field] for field in ("fresh", "cache_create", "cache_read")
    )
    tokens["reasoning"] = g.get("reasoning")

    run = {
        "run_id": f"{stratum}:{project}:{segment}",
        "stratum": stratum,
        "project": project,
        "issue": issue,
        "outcome": group_outcome(g) if "outcomes" in g else None,
        "tokens": tokens,
        "cost_usd": g.get("cost"),
        "cost_by_family": dict(g["cost_by_family"]) if "cost_by_family" in g else None,
    }
    for field in RUN_SCALAR_FIELDS:
        run[field] = g.get(field)
    for field in RUN_COUNTER_FIELDS:
        run[field] = dict(g[field]) if field in g else None
    for field in RUN_DISTRIBUTION_FIELDS:
        if field not in g:
            run[field] = None
            continue
        values = g[field]
        run[field] = {"n": len(values), "p50": percentile(values, 50),
                      "p90": percentile(values, 90), "max": max(values, default=0)}
    run["measurement"] = dict(g["measurement"]) if "measurement" in g else None
    return run


def build_record(groups_by_stratum, window, execution_telemetry=None):
    """Project {stratum: {cost_basis, groups}} into one agent-cost-record (D9)."""
    strata = {}
    for name in sorted(groups_by_stratum):
        stratum = groups_by_stratum[name]
        runs = sorted(
            (project_run(name, key, group) for key, group in stratum["groups"].items()),
            key=lambda run: run["run_id"],
        )
        totals = {"runs": len(runs)}
        for field in RECORD_TOKEN_FIELDS:
            totals[field] = sum_or_none(run["tokens"][field] for run in runs)
        totals["cost_usd"] = sum_or_none(run["cost_usd"] for run in runs)
        totals["cost_by_family"] = merge_families(run["cost_by_family"] for run in runs)
        strata[name] = {"cost_basis": stratum["cost_basis"], "totals": totals, "runs": runs}

    # The fleet folds the strata that measured something. An idle stratum
    # contributes nothing rather than nulling the roll-up, so `None` here means
    # no selected stratum had a run — while a measuring stratum's own absent
    # field (Claude's `reasoning`) still propagates through sum_or_none.
    measuring = [s["totals"] for s in strata.values() if s["totals"]["runs"]]
    fleet = {
        "informative": True,
        "totals": {
            field: sum_or_none(totals[field] for totals in measuring)
            for field in RECORD_TOKEN_FIELDS
        },
    }
    body = {
        "schema_version": SCHEMA_VERSION,
        "kind": RECORD_KIND,
        "window": window,
        "strata": strata,
        "fleet": fleet,
        "notes": DISCLAIMER,
        "execution_telemetry": execution_telemetry if execution_telemetry is not None else _empty_telemetry(()),
    }
    return dict(
        body,
        record_id=canonical_digest(body),
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
    )


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
    ap.add_argument("--format", choices=("text", "json"), default="text",
                    help="text tables (default) or one agent-cost-record JSON document")
    ap.add_argument("--strata", choices=("claude", "codex", "both"), default="claude",
                    help="which strata to scan; meaningful only with --format json")
    ap.add_argument("--codex-sessions", default=os.path.expanduser("~/.codex/sessions"),
                    help="Codex rollout root")
    ap.add_argument("--events-since", help="RFC3339 event-time lower bound (JSON only)")
    ap.add_argument("--events-before", help="RFC3339 event-time upper bound (JSON only)")
    args = ap.parse_args(argv)

    json_mode = args.format == "json"
    if not json_mode and args.strata != "claude":
        ap.error("--strata is meaningful only with --format json")
    if json_mode and args.artifacts:
        ap.error("--artifacts is not available with --format json")
    if not json_mode and (args.events_since or args.events_before):
        ap.error("--events-since/--events-before are available only with --format json")
    if bool(args.events_since) != bool(args.events_before):
        ap.error("--events-since and --events-before must be used together")
    event_start = event_end = None
    if args.events_since:
        try:
            event_start = parse_rfc3339_utc(args.events_since)
            event_end = parse_rfc3339_utc(args.events_before)
        except ValueError:
            ap.error("event bounds must be RFC3339 instants with an offset")
        if event_start >= event_end:
            ap.error("--events-since must be before --events-before")
    selected = ("claude", "codex") if args.strata == "both" else (args.strata,)

    cutoff = time.time() - args.days * 86400 if args.days > 0 else None

    root = codex_root = None
    groups, retained_results, kept_sessions, kept_files = {}, [], 0, 0
    if "claude" in selected:
        root = Path(args.projects_dir)
        if not root.is_dir():
            sys.exit(f"no transcript root at {root}")

        sessions = list(find_sessions(root, cutoff))
        # (session index, is_root, path) — pool.map preserves input order.
        jobs = [
            (i, is_root, f)
            for i, (_, root_files, sub_files) in enumerate(sessions)
            for is_root, f in [(True, f) for f in root_files] + [(False, f) for f in sub_files]
        ]
        if not jobs and not json_mode:
            sys.exit("no transcripts in window")

        results = scan_paths([path for _idx, _is_root, path in jobs], executor_factory)
        per_session = defaultdict(list)
        for (idx, is_root, _path), result in zip(jobs, results):
            if result:
                per_session[idx].append((is_root, result))

        groups, retained_results, kept_sessions, kept_files = build_groups(
            sessions, per_session, args.project
        )

        if not groups and not json_mode:
            sys.exit("no sessions matched the filters")

    codex_groups = {}
    if "codex" in selected:
        codex_root = Path(os.path.expanduser(args.codex_sessions))
        codex_groups = collect_codex_groups(
            codex_root, cutoff, args.project, executor_factory
        )

    if json_mode:
        sources = {}
        groups_by_stratum = {}
        if "claude" in selected:
            sources["claude"] = str(root)
            groups_by_stratum["claude"] = {"cost_basis": "list-price", "groups": groups}
        if "codex" in selected:
            sources["codex"] = str(codex_root)
            groups_by_stratum["codex"] = {"cost_basis": "subscription", "groups": codex_groups}
        record_window = {"days": args.days,
                         "cutoff_epoch": int(cutoff) if cutoff else None,
                         # `--days` selects transcript files by mtime; all
                         # records in each selected file are then accounted.
                         "file_mtime_selection": True,
                         "whole_selected_file_usage": True,
                         "strata": sorted(selected),
                         "sources": sources}
        execution_telemetry = collect_execution_telemetry(
            selected, root, codex_root, event_start, event_end, args.project, executor_factory
        )
        json.dump(build_record(groups_by_stratum, record_window, execution_telemetry), sys.stdout,
                  separators=(",", ":"))
        print()
        return

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

    print(f"\nNOTE: {DISCLAIMER}")


if __name__ == "__main__":
    main()
