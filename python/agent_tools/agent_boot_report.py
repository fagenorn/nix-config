"""The agent-costs boot report (issue 448).

A fresh owner's boot is the calls from its first through its registering call (or the last
call before the first child goes out), as agent_tools.agent_owner_report.boot_facts defines
it. This module splits each boot's context B into twelve buckets: call 0 into tool schemas,
harness and prompt from the transcript's request records (a fixed 2.44 characters per
token), and every later call's growth by the character share of what the call added.
collect_host reads one transcript root through agent_owner_report.collect; build_document
projects the hosts as the `agent-boot-report` document and print_document prints it.
agent_costs.main runs the report for `--report boot`. python/README.md (agent-costs) holds
the contract.
"""

import json
import os
import posixpath
import re
import socket
import statistics
from pathlib import Path, PurePosixPath

from agent_tools.agent_costs import DISCLAIMER, ROOT_LABEL, human, print_table, scan_paths
from agent_tools.agent_owner_report import (
    _SAVED_TO,
    _TASK_FILE,
    _print_capped,
    boot_facts,
    boot_slice,
    collect,
)
from agent_tools.context_meter_commands import SEPARATORS, lex
from agent_tools.transcript_calls import read_transcript

SCHEMA_VERSION = 1
REPORT_KIND = "agent-boot-report"
CHARS_PER_TOKEN = 2.44
RATIO_MIN_CHARS = 2_000
ALL = "all"
BUCKETS = ("tool_schemas", "harness", "prompt", "skill_bodies", "skill_files", "plan_reads",
           "resume_reads", "rereads", "other_reads", "commands", "assistant", "unexplained")
READERS = ("cat", "sed", "head", "tail", "nl", "awk", "jq", "less")
COHORTS = ("fresh", "spawned")
PHASE_GROUPS = ("0-5", "6-7", ALL)

_SYSTEM_REMINDER = "<system-reminder>"
_RESUME_PACK = re.compile(r'"kind"\s*:\s*"resume_pack"')
_OWNER_KIND = re.compile(r'"kind"\s*:\s*"owner"')
_OWNER_VERSION = re.compile(r'"interface_version"\s*:\s*2\b')
_HEREDOC = re.compile(r"""(?<!<)<<-?(?!<)\s*(['"]?)([A-Za-z_]\w*)\1""")
_ASSIGNMENT = re.compile(r"[A-Za-z_]\w*=")
_VARIABLE = re.compile(r"\$(?:(\w+)|\{(\w+)\})")
_FILE_LIKE = re.compile(r"\.[A-Za-z0-9]+$")
_MARKERS = ('"type":"api-request', '"isMeta":true')


def short_hostname() -> str:
    return socket.gethostname().split(".", 1)[0]


def parse_roots(values, *, hostname):
    """The `(label, root)` pairs of the `[LABEL=]PATH` values, in argument order.

    A bare path takes `hostname`. The label `all` is the pooled host's, so it is reserved,
    and a label may be given only once.
    """
    roots, seen = [], set()
    for value in values:
        found = ROOT_LABEL.fullmatch(value)
        label, path = found.groups() if found else (hostname, value)
        if label == ALL:
            raise ValueError(f"--projects-dir label {ALL!r} is reserved")
        if label in seen:
            raise ValueError(f"--projects-dir label {label!r} is given twice")
        seen.add(label)
        roots.append((label, Path(os.path.expanduser(path))))
    return roots


# ---- read keys -------------------------------------------------------------------


def _expand(word, env):
    return _VARIABLE.sub(lambda match: env.get(match.group(1) or match.group(2), match.group(0)),
                         word)


def _command_text(command):
    """`command` with each heredoc operator and the heredoc body after it removed."""
    kept, delimiter = [], None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        found = _HEREDOC.search(line)
        while found:
            delimiter = found.group(2)
            line = line[:found.start()] + line[found.end():]
            found = _HEREDOC.search(line)
        kept.append(line)
    return "\n".join(kept)


def _simple_commands(tokens):
    """The word lists of the simple commands of `tokens`, redirections and their targets dropped."""
    commands, words, skip = [], [], False
    for token in tokens:
        if token.kind == "op" and token.value in SEPARATORS:
            commands.append(words)
            words, skip = [], False
        elif token.kind == "op":
            skip = True
        elif skip:
            skip = False
        else:
            words.append(token.value)
    commands.append(words)
    return commands


def _join(cwd, operand):
    if operand.startswith(("/", "~")) or not cwd:
        return operand
    return posixpath.normpath(cwd + "/" + operand)


def _reader_operands(words, env, cwd):
    """The expanded, cwd-joined file operands of a reader's words after its program word."""
    operands, consume, program_text = [], False, False
    needs_program = posixpath.basename(words[0]) in ("sed", "awk", "jq")
    for word in words[1:]:
        if consume:
            consume = False
        elif word.startswith("-"):
            consume = (posixpath.basename(words[0]) in ("head", "tail")
                       and word in ("-n", "-c"))
        elif needs_program and not program_text:
            program_text = True
        else:
            expanded = _expand(word, env)
            if "/" in expanded or _FILE_LIKE.search(expanded):
                operands.append(_join(cwd, expanded))
    return operands


def _bash_keys(command):
    tokens = lex(_command_text(command))
    if tokens is None:
        return []
    keys, env, cwd = [], {}, ""
    for words in _simple_commands(tokens):
        while words and _ASSIGNMENT.match(words[0]):
            name, _, value = words[0].partition("=")
            env[name] = _expand(value, env)
            words = words[1:]
        if not words:
            continue
        if words[0] == "cd" and len(words) > 1:
            cwd = _join(cwd, _expand(words[1], env))
        elif posixpath.basename(words[0]) in READERS:
            keys.extend((path, tuple(words)) for path in _reader_operands(words, env, cwd))
    return keys


def read_keys(name, tool_input):
    """The (path, ...) keys a tool call reads; empty for every tool but Read and Bash."""
    if name == "Read" and isinstance(tool_input.get("file_path"), str):
        return [(tool_input["file_path"], tool_input.get("offset"), tool_input.get("limit"))]
    if name == "Bash" and isinstance(tool_input.get("command"), str):
        return _bash_keys(tool_input["command"])
    return []


# ---- classifying tool results ----------------------------------------------------


def _skill_file_key(path):
    parts = PurePosixPath(path).parts
    last = max((index for index, part in enumerate(parts) if part == "skills"), default=None)
    if last is None or len(parts) - last - 1 < 2:
        return None
    return "/".join(parts[last + 1:])


def _is_plan(path):
    pure = PurePosixPath(path)
    if _TASK_FILE.search(path):
        return True
    if pure.suffix == ".md" and pure.parent.name == "plans":
        return not pure.name.endswith(".acceptance.md")
    return pure.name == "progress.md" and ".superpowers" in pure.parts and "sdd" in pure.parts


def _classify(name, tool_input, text, keys, seen, saved):
    """The (bucket, sub key) of a tool result by the first rule that holds (D2, D17)."""
    paths = [key[0] for key in keys]
    if name == "Read" and tool_input.get("file_path") in saved:
        verdict = saved[tool_input["file_path"]]
    elif keys and all(key in seen for key in keys):
        verdict = ("rereads", None)
    elif _RESUME_PACK.search(text) or (_OWNER_KIND.search(text) and _OWNER_VERSION.search(text)):
        verdict = ("resume_reads", None)
    elif any(map(_skill_file_key, paths)):
        verdict = ("skill_files", next(filter(None, map(_skill_file_key, paths))))
    elif any(_is_plan(path) for path in paths):
        verdict = ("plan_reads", None)
    elif paths:
        verdict = ("other_reads", None)
    elif name == "Skill":
        verdict = ("skill_bodies", tool_input.get("skill"))
    else:
        verdict = ("commands", None)
    seen.update(keys)
    for path in _SAVED_TO.findall(text):
        saved[path] = verdict
    return verdict


# ---- attributing one boot --------------------------------------------------------


def _text_length(blocks):
    return sum(len(block.get("text", "")) for block in blocks
               if isinstance(block, dict) and isinstance(block.get("text"), str))


def _records(handle, stop):
    """The request records and meta user records of a transcript, up to line `stop`.

    Returns shapes and requests as `(line, value)` lists, meta records likewise, and the
    hash-to-message map of the blobs (the first occurrence of a hash wins).
    """
    shapes, requests, metas, blobs = [], [], [], {}
    for line_no, line in enumerate(handle):
        if line_no > stop:
            break
        if not any(marker in line for marker in _MARKERS):
            continue
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if not isinstance(value, dict):
            continue
        kind = value.get("type")
        if kind == "api-request-shape" and isinstance(value.get("shape"), dict):
            shapes.append((line_no, value["shape"]))
        elif kind == "api-request" and isinstance(value.get("tail"), list):
            requests.append((line_no, value["tail"]))
        elif kind == "api-request-blob" and isinstance(value.get("message"), dict):
            blobs.setdefault(value.get("hash"), value["message"])
        elif kind == "user" and value.get("isMeta") is True:
            metas.append((line_no, value))
    return shapes, requests, metas, blobs


def _tool_characters(shape):
    tools = shape.get("tools")
    return sum(len(json.dumps(tool, separators=(",", ":"))) for tool in tools or ())


def _blocks(message):
    content = message.get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return [block for block in content or () if isinstance(block, dict)]


def _opening(shape, request, blobs):
    """The harness and prompt characters of call 0 and the blob hashes it already counted."""
    system = shape.get("system")
    harness = _text_length(system if isinstance(system, list) else [])
    prompt = 0
    for digest in request:
        message = blobs.get(digest)
        if message is None:
            continue
        for block in _blocks(message):
            if block.get("type") != "text" or not isinstance(block.get("text"), str):
                continue
            if message.get("role") == "system" or block["text"].startswith(_SYSTEM_REMINDER):
                harness += len(block["text"])
            else:
                prompt += len(block["text"])
    return harness, prompt


def _last_before(records, line):
    found = [value for number, value in records if number < line]
    return found[-1] if found else None


def _between(records, low, high):
    return [value for number, value in records if low < number < high]


def _meta_text(value):
    message = value.get("message")
    blocks = _blocks(message) if isinstance(message, dict) else []
    return "\n".join(block["text"] for block in blocks
                     if block.get("type") == "text" and isinstance(block.get("text"), str))


class _Boot:
    """The mutable state of attributing one boot's calls."""

    def __init__(self, transcript, count, shapes, requests, metas, blobs):
        self.calls = transcript.calls[:count]
        self.results = sorted(transcript.results.items(), key=lambda item: item[1].line)
        self.names, self.inputs = {}, {}
        for call in transcript.calls:
            self.names.update(call.tool_names)
            self.inputs.update(call.tool_inputs)
        self.shapes, self.requests, self.metas, self.blobs = shapes, requests, metas, blobs
        self.buckets = dict.fromkeys(BUCKETS, 0)
        self.skills, self.skill_files = {}, {}
        self.ratio_chars = self.ratio_tokens = 0
        self.counted, self.seen, self.saved = set(), set(), {}
        self.tool_chars = 0

    def add(self, bucket, key, tokens):
        self.buckets[bucket] += tokens
        if bucket == "skill_bodies":
            self.skills[key] = self.skills.get(key, 0) + tokens
        elif bucket == "skill_files":
            self.skill_files[key] = self.skill_files.get(key, 0) + tokens

    def open(self):
        """Split call 0; False when the boot has no shape or no request record before it."""
        line = self.calls[0].first_line
        shape, request = _last_before(self.shapes, line), _last_before(self.requests, line)
        if shape is None or request is None:
            return False
        harness_chars, prompt_chars = _opening(shape, request, self.blobs)
        harness = round(harness_chars / CHARS_PER_TOKEN)
        prompt = round(prompt_chars / CHARS_PER_TOKEN)
        self.buckets["harness"], self.buckets["prompt"] = harness, prompt
        self.buckets["tool_schemas"] = self.calls[0].context - harness - prompt
        self.tool_chars = _tool_characters(shape)
        self.counted.update(request)
        return True

    def _result_chunks(self, low, high):
        chunks = []
        for tool_id, result in self.results:
            if not low < result.line < high:
                continue
            name, tool_input = self.names.get(tool_id), self.inputs.get(tool_id, {})
            keys = read_keys(name, tool_input)
            bucket, key = _classify(name, tool_input, result.text, keys, self.seen, self.saved)
            chunks.append((bucket, key, result.size))
        return chunks

    def _skill_metas(self, metas):
        """The meta records of `metas` that carry the body a Skill call loaded."""
        return [value for value in metas
                if self.names.get(value.get("sourceToolUseID")) == "Skill"]

    def _meta_chunks(self, metas):
        return [("skill_bodies", self.inputs.get(value.get("sourceToolUseID"), {}).get("skill"),
                 len(_meta_text(value))) for value in metas]

    def _request_chunks(self, requests, metas):
        """The blobs not yet counted, less assistant messages (the previous call's output,
        already charged) and text equal to a Skill meta message of the segment."""
        skipped = {_meta_text(value) for value in metas}
        chunks = []
        for tail in requests:
            for digest in tail:
                if digest in self.counted:
                    continue
                self.counted.add(digest)
                message = self.blobs.get(digest)
                if message is None or message.get("role") == "assistant":
                    continue
                for block in _blocks(message):
                    if block.get("type") == "text" and isinstance(block.get("text"), str):
                        if block["text"] not in skipped:
                            chunks.append(("harness", None, len(block["text"])))
                    elif block.get("type") == "tool_addition":
                        chunks.append(("tool_schemas", None,
                                       len(json.dumps(block, separators=(",", ":")))))
        return chunks

    def _shape_chunks(self, shapes):
        chunks = []
        for shape in shapes:
            characters = _tool_characters(shape)
            chunks.append(("tool_schemas", None, max(0, characters - self.tool_chars)))
            self.tool_chars = characters
        return chunks

    def grow(self, index):
        """Attribute the growth from call `index - 1` to call `index`.

        The segment's chunks are classified even when the growth is not positive, so its
        reads, read-back origins, counted blobs and schema size carry to later calls; the
        growth itself is then `unexplained`.
        """
        before, call = self.calls[index - 1], self.calls[index]
        growth = call.context - before.context
        low, high = before.first_line, call.first_line
        metas = self._skill_metas(_between(self.metas, low, high))
        chunks = (self._result_chunks(low, high) + self._meta_chunks(metas)
                  + self._request_chunks(_between(self.requests, low, high), metas)
                  + self._shape_chunks(_between(self.shapes, low, high)))
        if growth <= 0:
            self.buckets["unexplained"] += growth
            return
        assistant = min(growth, before.usage["output_tokens"])
        self.buckets["assistant"] += assistant
        residual = growth - assistant
        total = sum(chars for _, _, chars in chunks)
        if residual <= 0:
            return
        if total <= 0:
            self.buckets["unexplained"] += residual
            return
        shares = [residual * chars // total for _, _, chars in chunks]
        largest = max(range(len(chunks)), key=lambda position: chunks[position][2])
        shares[largest] += residual - sum(shares)
        for (bucket, key, _), tokens in zip(chunks, shares):
            self.add(bucket, key, tokens)
        if total > RATIO_MIN_CHARS:
            self.ratio_chars += total
            self.ratio_tokens += residual


def attribute(job):
    """Split one boot `(transcript path, boot call count)` into buckets; None when unsplit.

    A boot is unsplit when the file cannot be opened or no `api-request-shape` and
    `api-request` record precede its call 0.
    """
    path, count = job
    try:
        with open(path, "r", errors="replace") as handle:
            transcript = read_transcript(handle)
        if not transcript.calls[:count]:
            return None
        with open(path, "r", errors="replace") as handle:
            records = _records(handle, transcript.calls[count - 1].first_line)
    except OSError:
        return None
    boot = _Boot(transcript, count, *records)
    if not boot.open():
        return None
    for index in range(1, count):
        boot.grow(index)
    return {"start": boot.calls[0].context, "b": boot.calls[-1].context, "buckets": boot.buckets,
            "skills": boot.skills, "skill_files": boot.skill_files,
            "ratio_chars": boot.ratio_chars, "ratio_tokens": boot.ratio_tokens}


# ---- collecting hosts ------------------------------------------------------------


def _cohort(lineage, launch):
    fresh = (launch is not lineage.launches[0]
             or (isinstance(launch.launch, int) and launch.launch >= 2))
    return "fresh" if fresh else "spawned"


def collect_host(label, root, *, cutoff, since, before, executor_factory):
    """The boot rows of the transcripts under `root`, labelled `label`."""
    lineages, _ = collect(root, cutoff=cutoff, since=since, before=before, eval_rows=None,
                          executor_factory=executor_factory)
    pending = []
    for lineage in lineages:
        for launch in lineage.launches:
            facts = boot_facts(launch)
            if facts is None:
                continue
            pending.append((launch.transcript, len(boot_slice(launch)), {
                "host": label, "transcript": launch.transcript, "run_id": lineage.run_id,
                "issue": lineage.issue, "cohort": _cohort(lineage, launch),
                "phase_group": facts[0]}))
    results = scan_paths([(transcript, calls) for transcript, calls, _ in pending],
                         executor_factory, scanner=attribute)
    host = {"label": label, "root": str(root), "boots": [], "unsplit": 0,
            "ratio_chars": 0, "ratio_tokens": 0}
    for (_, calls, identity), result in zip(pending, results):
        if result is None:
            host["unsplit"] += 1
            continue
        host["ratio_chars"] += result["ratio_chars"]
        host["ratio_tokens"] += result["ratio_tokens"]
        host["boots"].append({
            **identity, "calls": calls, "start": result["start"], "b": result["b"],
            "buckets": result["buckets"], "skills": result["skills"],
            "skill_files": result["skill_files"]})
    return host


# ---- the document ----------------------------------------------------------------


def _group_rows(label, boots):
    rows = []
    for cohort in COHORTS:
        for group in PHASE_GROUPS:
            members = [boot for boot in boots if boot["cohort"] == cohort
                       and group in (ALL, boot["phase_group"])]
            if not members:
                continue
            rows.append({
                "host": label, "cohort": cohort, "phase_group": group, "count": len(members),
                "b_mean": statistics.fmean(boot["b"] for boot in members),
                "b_without_schemas_mean": statistics.fmean(
                    boot["b"] - boot["buckets"]["tool_schemas"] for boot in members),
                "buckets": {name: statistics.fmean(boot["buckets"][name] for boot in members)
                            for name in BUCKETS}})
    return rows


def build_document(hosts, *, window):
    """The `agent-boot-report` document of the collected `hosts`."""
    boots = [boot for host in hosts for boot in host["boots"]]
    ratio_chars = sum(host["ratio_chars"] for host in hosts)
    ratio_tokens = sum(host["ratio_tokens"] for host in hosts)
    groups = [row for host in hosts for row in _group_rows(host["label"], host["boots"])]
    groups += _group_rows(ALL, boots)
    return {
        "kind": REPORT_KIND, "schema_version": SCHEMA_VERSION, "window": window,
        "hosts": [{"label": host["label"], "root": host["root"]} for host in hosts],
        "chars_per_token": CHARS_PER_TOKEN,
        "observed_chars_per_token": round(ratio_chars / ratio_tokens, 2) if ratio_tokens else None,
        "unsplit": {host["label"]: host["unsplit"] for host in hosts},
        "boots": boots, "groups": groups,
    }


def _mean_table(groups):
    names = [f"{group['cohort']} {group['phase_group']}" for group in groups]
    rows = [["boots", *(f"{group['count']:,}" for group in groups)]]
    rows += [[name, *(human(round(group["buckets"][name])) for group in groups)]
             for name in BUCKETS]
    rows.append(["B", *(human(round(group["b_mean"])) for group in groups)])
    rows.append(["B without tool schemas",
                 *(human(round(group["b_without_schemas_mean"])) for group in groups)])
    print_table(rows, ["", *names], ["l"] + ["r"] * len(groups))


def _top_skills(boots, top):
    fresh = [boot for boot in boots if boot["cohort"] == "fresh"]
    rows = []
    for kind, field in (("skill", "skills"), ("file", "skill_files")):
        keys = {key for boot in fresh for key in boot[field]}
        rows += [(statistics.fmean(boot[field].get(key, 0) for boot in fresh), kind, key)
                 for key in keys]
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [[kind, key, human(round(mean))] for mean, kind, key in rows[:top]]


def print_document(doc, *, top):
    """Print the boot report's tables for `doc` (build_document's result)."""
    boots = doc["boots"]
    fresh = sum(boot["cohort"] == "fresh" for boot in boots)
    hosts = ", ".join(f"{host['label']} {host['root']}" for host in doc["hosts"])
    print(f"Boot composition ({doc['window']}; hosts: {hosts}; {len(boots):,} boots: "
          f"{fresh:,} fresh, {len(boots) - fresh:,} spawned; call 0 at "
          f"{doc['chars_per_token']} characters per token)")
    for label in [host["label"] for host in doc["hosts"]] + [ALL]:
        title = "all hosts" if label == ALL else f"host {label}"
        print(f"\nMean boot buckets, {title} (tokens per boot):\n")
        _mean_table([group for group in doc["groups"] if group["host"] == label])
    print("\nTop skill bodies and skill files (mean tokens per fresh boot, all hosts):\n")
    print_table(_top_skills(boots, top), ["kind", "key", "mean"], ["l", "l", "r"])
    print("\nBoots by B (host, issue, cohort, phase, calls, start, B, then each bucket):\n")
    ordered = sorted(boots, key=lambda boot: (-boot["b"], boot["transcript"]))
    _print_capped(
        [[boot["host"], str(boot["issue"]), boot["cohort"], boot["phase_group"],
          f"{boot['calls']:,}", human(boot["start"]), human(boot["b"]),
          *(human(boot["buckets"][name]) for name in BUCKETS)] for boot in ordered],
        top, ["host", "issue", "cohort", "phase", "calls", "start", "B", *BUCKETS],
        ["l", "r", "l", "l", "r", "r", "r"] + ["r"] * len(BUCKETS))
    observed = doc["observed_chars_per_token"]
    print(f"\nObserved characters per token (boot calls adding more than "
          f"{RATIO_MIN_CHARS:,} characters): {'none' if observed is None else f'{observed:.2f}'}")
    print("Unsplit boots (no request records, left out): "
          + ", ".join(f"{label} {count:,}" for label, count in doc["unsplit"].items()))
    print(f"NOTE: {DISCLAIMER}")
