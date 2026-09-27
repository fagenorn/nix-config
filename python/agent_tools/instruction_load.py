"""Measure the instruction documents each agent profile loads, per host, and compare two revisions."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from typing import Any, Callable, Optional

from agent_tools.agent_model_matrix import (
    AGENTS_PATH,
    MATRIX_PATH,
    SUBAGENT_TYPE,
    parse_matrix,
)
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal


MODEL_PATH = "home/common/agent-skills/instruction-load.json"
SHARED_TREE = "home/common/agent-skills/skills"
CLAUDE_TREE = "home/common/claude-code/skills"
AGENTS_DIR = AGENTS_PATH.as_posix()
FRAME_MEMBER = "agent-guidance/AGENTS.md"
FRAME_PATH = "home/common/agent-guidance/AGENTS.md"
HOSTS = ("claude", "codex")
TOP_LEVEL_KEYS = ("frame", "profiles", "excluded_sites")
PROFILE_KEYS = (
    "id",
    "hosts",
    "prompt",
    "hot",
    "conditional",
    "unread",
    "ceiling_bytes",
    "note",
)
PROFILE_CHOICE_KEYS = ("entry", "launch")
SKILL_NAME = re.compile(r"[A-Za-z0-9_-]+")
REGENERATE = "just agent-instruction-load report --base {base} --head {head} --output <path>"

Reader = Callable[[str], Optional[bytes]]

_BOUNDARY_BEFORE = r"(?<![A-Za-z0-9_-])"
_BOUNDARY_AFTER = r"(?![A-Za-z0-9_-])"
_BASENAME_BEFORE = r"(?<![A-Za-z0-9_.-])(?<![A-Za-z0-9_-]/)"   # not inside "<skill>/<file>"
_MD_TOKEN = re.compile(_BASENAME_BEFORE + r"([A-Za-z0-9_-]+\.md)" + _BOUNDARY_AFTER)


def tree_reader(root: Path) -> Reader:
    """Read repository-relative POSIX paths under `root`, matching names exactly."""

    def read(path: str) -> Optional[bytes]:
        current = Path(root)
        try:
            for part in path.split("/"):
                if part not in os.listdir(current):
                    return None
                current = current / part
            return current.read_bytes() if current.is_file() else None
        except OSError:
            return None

    return read


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if completed.returncode != 0:
        lines = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"git {args[0]} failed: {lines[-1] if lines else ''}")
    return completed.stdout


def revision_reader(root: Path, revision: str) -> tuple[str, Reader]:
    """The full commit SHA of `revision`, and a reader over that commit's tree."""
    try:
        sha = _git(root, "rev-parse", "--verify", "--quiet", "--end-of-options",
                   f"{revision}^{{commit}}").decode("ascii").strip()
    except ValueError:
        raise ValueError(f"unknown revision {revision!r}") from None
    present = set(filter(None, _git(root, "ls-tree", "-r", "-z", "--name-only", sha)
                         .decode("utf-8", "surrogateescape").split("\0")))
    cache: dict[str, bytes] = {}

    def read(path: str) -> Optional[bytes]:
        if path not in present:
            return None
        if path not in cache:
            cache[path] = _git(root, "show", f"{sha}:{path}")
        return cache[path]

    return sha, read


def load_model(data: bytes) -> dict:
    """Load the model as strict UTF-8 JSON through the canonical hooks."""
    try:
        model = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_nonfinite_literal,
        )
    except ValueError as error:
        raise ValueError(f"cannot load {MODEL_PATH}: {error}") from error
    if not isinstance(model, dict):
        raise ValueError(f"{MODEL_PATH}: top level must be an object")
    return model


def _split(member: object) -> Optional[tuple[str, str]]:
    """`(skill, file)` for a `<skill>/<file>` spelling, else None."""
    parts = member.split("/") if isinstance(member, str) else []
    if len(parts) != 2 or not all(parts):
        return None
    return parts[0], parts[1]


def _sibling(member: str, name: str) -> str:
    """The member spelling of `name` in `member`'s own skill."""
    skill, _ = _split(member)
    return f"{skill}/{name}"


def resolve(member: str, read: Reader) -> list[tuple[str, str]]:
    """The `(tree, path)` documents a member spelling names that exist."""
    parts = _split(member)
    if parts is None:
        return []
    skill, name = parts
    candidates = [("shared", f"{SHARED_TREE}/{member}"), ("claude-only", f"{CLAUDE_TREE}/{member}")]
    if skill == "agents":
        candidates.append(("agents", f"{AGENTS_DIR}/{name}"))
    return [(tree, path) for tree, path in candidates if read(path) is not None]


def _names(source: str, text: str, target: str) -> bool:
    """Whether document `source`, whose content is `text`, names `target`."""
    parts = _split(target)
    if parts is None:
        return False
    skill, name = parts
    if re.search(_BOUNDARY_BEFORE + re.escape(target) + _BOUNDARY_AFTER, text):
        return True
    source_parts = _split(source)
    if source_parts is not None and source_parts[0] == skill and re.search(
        _BASENAME_BEFORE + re.escape(name) + _BOUNDARY_AFTER, text
    ):
        return True
    return name == "SKILL.md" and f"`{skill}`" in text


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_reason_map(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(reason, str) for reason in value.values())


def _top_level_violations(model: dict, read: Reader) -> list[str]:
    found = [f"model: missing key '{key}'" for key in TOP_LEVEL_KEYS if key not in model]
    found += [f"model: unknown key '{key}'" for key in sorted(set(model) - set(TOP_LEVEL_KEYS))]
    if "frame" in model:
        if model["frame"] != FRAME_MEMBER:
            found.append(f"model: frame must be {FRAME_MEMBER!r}")
        elif read(FRAME_PATH) is None:
            found.append(f"model: frame {FRAME_MEMBER} resolves to no document")
    excluded = model.get("excluded_sites", {})
    if not _is_reason_map(excluded):
        found.append("model: excluded_sites must map site ids to reasons")
    else:
        found += [
            f"excluded site {site}: empty reason"
            for site, reason in excluded.items()
            if not reason.strip()
        ]
    if not isinstance(model.get("profiles", []), list):
        found.append("model: profiles must be a list")
    return found


def _profile_violations(profile: object) -> list[str]:
    """Unprefixed structural violations of one profile."""
    if not isinstance(profile, dict):
        return ["must be an object"]
    found = [f"missing key '{key}'" for key in PROFILE_KEYS if key not in profile]
    unknown = set(profile) - set(PROFILE_KEYS) - set(PROFILE_CHOICE_KEYS)
    found += [f"unknown key '{key}'" for key in sorted(unknown)]
    if "id" in profile and not (isinstance(profile["id"], str) and profile["id"]):
        found.append("id must be a non-empty string")
    if ("entry" in profile) == ("launch" in profile):
        found.append("needs exactly one of 'entry' or 'launch'")
    if "entry" in profile:
        entry = profile["entry"]
        if not (isinstance(entry, str) and SKILL_NAME.fullmatch(entry)):
            found.append("entry must be a skill name")
        if profile.get("prompt") is not None:
            found.append("an entry has no prompt")
    if "launch" in profile:
        launch = profile["launch"]
        if not (_is_string_list(launch) and launch and all(launch)):
            found.append("launch must be a non-empty list of site ids")
        if not isinstance(profile.get("prompt"), str):
            found.append("a launch needs a prompt")
    hosts = profile.get("hosts")
    hosts_valid = (
        _is_string_list(hosts)
        and bool(hosts)
        and set(hosts) <= set(HOSTS)
        and len(set(hosts)) == len(hosts)
    )
    if not hosts_valid:
        found.append(f"hosts must be a non-empty subset of {list(HOSTS)}")
    listed: list[str] = []
    for kind in ("hot", "conditional"):
        if _is_string_list(profile.get(kind)):
            listed += profile[kind]
        else:
            found.append(f"{kind} must be a list of members")
    unread = profile.get("unread")
    if _is_reason_map(unread):
        listed += list(unread)
        found += [
            f"unread {member} has an empty reason"
            for member, reason in unread.items()
            if not reason.strip()
        ]
    else:
        found.append("unread must map members to reasons")
    found += [
        f"{member} listed more than once"
        for member in dict.fromkeys(listed)
        if listed.count(member) > 1
    ]
    ceiling = profile.get("ceiling_bytes")
    if not isinstance(ceiling, dict):
        found.append("ceiling_bytes must map hosts to byte counts")
    else:
        if hosts_valid and set(ceiling) != set(hosts):
            found.append(
                f"ceiling_bytes hosts {sorted(ceiling)} differ from hosts {sorted(hosts)}"
            )
        found += [
            f"ceiling_bytes {host} must be a non-negative integer"
            for host, value in ceiling.items()
            if isinstance(value, bool) or not isinstance(value, int) or value < 0
        ]
    note = profile.get("note")
    if not isinstance(note, str) or not note.strip():
        found.append("empty note")
    return found


def _structure_violations(profiles: list) -> tuple[list[str], list[dict]]:
    """Every profile's structural violations, and the profiles that have none."""
    violations: list[str] = []
    sound: list[dict] = []
    seen: set[str] = set()
    for index, profile in enumerate(profiles):
        profile_id = profile.get("id") if isinstance(profile, dict) else None
        named = isinstance(profile_id, str) and bool(profile_id)
        label = profile_id if named else f"#{index}"
        found = _profile_violations(profile)
        if named:
            if profile_id in seen:
                found.append("duplicate id")
            seen.add(profile_id)
        violations += [f"profile {label}: {message}" for message in found]
        if not found:
            sound.append(profile)
    return violations, sound


def _matrix_sites(read: Reader) -> tuple[list[str], Optional[list[dict]]]:
    """The matrix's dispatch sites through `read`, or the violation that hides them."""
    source = MATRIX_PATH.as_posix()
    raw = read(source)
    if raw is None:
        return [f"matrix: {source} is absent"], None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return [f"matrix: cannot load {source}: {error}"], None
    try:
        matrix = parse_matrix(text, source)
    except ValueError as error:
        return [f"matrix: {error}"], None
    sites = matrix.get("dispatch_sites")
    if not isinstance(sites, list) or not all(
        isinstance(site, dict)
        and isinstance(site.get("id"), str)
        and site["id"]
        and isinstance(site.get("call"), str)
        for site in sites
    ):
        return ["matrix: dispatch_sites must be a list of objects with an id and a call"], None
    return [], sites


def _completeness_violations(model: dict, profiles: list, sites: list[dict]) -> list[str]:
    excluded = model.get("excluded_sites")
    excluded = excluded if isinstance(excluded, dict) else {}
    launches = [
        profile["launch"]
        for profile in profiles
        if isinstance(profile, dict) and isinstance(profile.get("launch"), list)
    ]
    found = []
    for site in sites:
        count = sum(site["id"] in launch for launch in launches) + (site["id"] in excluded)
        if count == 0:
            found.append(f"matrix site {site['id']} is in no profile")
        elif count > 1:
            found.append(f"matrix site {site['id']} is claimed {count} times")
    known = {site["id"] for site in sites}
    claimed = [item for launch in launches for item in launch if isinstance(item, str)]
    claimed += list(excluded)
    found += [
        f"unknown matrix site {site_id}"
        for site_id in dict.fromkeys(claimed)
        if site_id not in known
    ]
    return found


def _member_violations(profile: dict, read: Reader, sites: Optional[list[dict]]) -> list[str]:
    """Resolution, reachability and closure of one sound profile's members."""
    prompt = [] if profile["prompt"] is None else [profile["prompt"]]
    loaded = [*profile["hot"], *profile["conditional"]]
    listed = {*loaded, *profile["unread"]}
    found = []
    resolved: dict[str, tuple[str, str]] = {}
    for member in dict.fromkeys([*prompt, *loaded, *profile["unread"]]):
        documents = resolve(member, read)
        if not documents:
            found.append(f"{member} resolves to no document")
        elif len(documents) > 1:
            found.append(f"{member} resolves to {len(documents)} documents")
        else:
            resolved[member] = documents[0]
    texts = {
        member: read(path).decode("utf-8", "replace")
        for member, (_, path) in resolved.items()
    }
    skill_documents = [m for m in loaded if m in resolved and resolved[m][0] != "agents"]
    prompt_sources = [m for m in prompt if m in resolved]
    own_entry = f"{profile['entry']}/SKILL.md" if "entry" in profile else None
    calls = None
    if sites is not None:
        launch = profile.get("launch", [])
        calls = [site["call"] for site in sites if site["id"] in launch]

    for member in loaded:
        if member not in resolved or member == own_entry:
            continue
        tree, path = resolved[member]
        if tree == "agents":
            name = posixpath.basename(path).removesuffix(".md")
            if calls is not None and not any(
                name in SUBAGENT_TYPE.findall(call) for call in calls
            ):
                found.append(f"{member} is not the subagent_type of any of its sites")
            continue
        sources = prompt_sources + [d for d in skill_documents if d != member]
        if not any(_names(source, texts[source], member) for source in sources):
            found.append(f"{member} is named by neither its prompt nor another member")

    for member in skill_documents:
        folder = posixpath.dirname(resolved[member][1])
        for token in sorted(set(_MD_TOKEN.findall(texts[member]))):
            sibling = _sibling(member, token)
            if read(f"{folder}/{token}") is not None and sibling not in listed:
                found.append(f"{member} names {sibling}, which the profile does not list")
    return [f"profile {profile['id']}: {message}" for message in found]


def validate(model: dict, read: Reader) -> list[str]:
    """Every violation of the model, in report order; empty when it is sound."""
    violations = _top_level_violations(model, read)
    profiles = model.get("profiles")
    profiles = profiles if isinstance(profiles, list) else []
    structure, sound = _structure_violations(profiles)
    violations += structure
    matrix, sites = _matrix_sites(read)
    violations += matrix
    if sites is not None:
        violations += _completeness_violations(model, profiles, sites)
    for profile in sound:
        violations += _member_violations(profile, read, sites)
    return violations


def _size(raw: bytes) -> dict[str, int]:
    return {"bytes": len(raw), "words": len(raw.decode("utf-8").split())}


def _document(member: str, read: Reader) -> dict[str, Any]:
    documents = resolve(member, read)
    if len(documents) > 1:
        raise ValueError(f"{member} resolves to {len(documents)} documents")
    if not documents:
        return {"path": None, "tree": None, "bytes": 0, "words": 0, "absent": True}
    tree, path = documents[0]
    return {"path": path, "tree": tree, **_size(read(path)), "absent": False}


def _counts_on(tree: Optional[str], host: str) -> bool:
    """Shared and absent members count on every host; the rest on Claude only."""
    return tree in (None, "shared") or host == "claude"


def _total(members: list[str], documents: dict, host: str) -> dict[str, Any]:
    counted = [m for m in members if _counts_on(documents[m]["tree"], host)]
    return {
        "members": counted,
        "bytes": sum(documents[m]["bytes"] for m in counted),
        "words": sum(documents[m]["words"] for m in counted),
    }


def measure(model: dict, read: Reader) -> dict:
    """Bytes and words of the frame, each loaded member and each profile per host."""
    frame_raw = read(FRAME_PATH)
    frame = (
        {"bytes": 0, "words": 0, "absent": True}
        if frame_raw is None
        else {**_size(frame_raw), "absent": False}
    )
    documents: dict[str, dict[str, Any]] = {}
    for profile in model["profiles"]:
        for member in [*profile["hot"], *profile["conditional"]]:
            if member not in documents:
                documents[member] = _document(member, read)
    profiles = {
        profile["id"]: {
            host: {
                kind: _total(profile[kind], documents, host)
                for kind in ("hot", "conditional")
            }
            for host in profile["hosts"]
        }
        for profile in model["profiles"]
    }
    return {"frame": frame, "documents": documents, "profiles": profiles}


def over_ceiling(model: dict, measurement: dict) -> list[str]:
    """One message per profile and host whose hot bytes exceed its ceiling."""
    found = []
    for profile in model["profiles"]:
        for host in profile["hosts"]:
            hot = measurement["profiles"][profile["id"]][host]["hot"]
            ceiling = profile["ceiling_bytes"][host]
            if hot["bytes"] > ceiling:
                listing = ", ".join(
                    f"{member} {measurement['documents'][member]['bytes']}"
                    for member in hot["members"]
                )
                found.append(
                    f"profile {profile['id']} on {host}: hot {hot['bytes']} bytes "
                    f"exceed ceiling {ceiling} ({listing})"
                )
    return found


PREFACE = (
    "Bytes are UTF-8 lengths and words are whitespace-separated tokens; neither is a token "
    "count. A hot member loads on every run of its profile's standard route and a conditional "
    "member only on a named branch. A shared-tree member counts on both hosts; a "
    "Claude-only-tree member or an agent definition counts on Claude only.",
    "Not measured: received prompts (each profile names its prompt's source document), the "
    "harness system prompt and skill listing, project instructions, and plugin or generated "
    "skills. The frame, the global guidance file installed for both hosts, is reported once "
    "and kept out of every profile total.",
)
SIZE_COLUMNS = ("Base bytes", "Head bytes", "Δ bytes", "Base words", "Head words", "Δ words")


def _side(entry: dict) -> dict[str, Any]:
    return {"bytes": entry["bytes"], "words": entry["words"], "absent": entry["absent"]}


def _delta(base: dict, head: dict) -> dict[str, int]:
    return {"bytes": head["bytes"] - base["bytes"], "words": head["words"] - base["words"]}


def _compare_total(head_total: dict, base_documents: dict, head_documents: dict) -> dict:
    members = head_total["members"]
    base = {
        "bytes": sum(base_documents[m]["bytes"] for m in members),
        "words": sum(base_documents[m]["words"] for m in members),
    }
    head = {"bytes": head_total["bytes"], "words": head_total["words"]}
    affected = any(_side(base_documents[m]) != _side(head_documents[m]) for m in members)
    return {"members": members, "base": base, "head": head,
            "delta": _delta(base, head), "affected": affected}


def compare(model: dict, base_measurement: dict, head_measurement: dict,
            base: str, head: str) -> dict:
    """The report data: the frame, each document and each profile's totals at both revisions."""
    base_documents = base_measurement["documents"]
    head_documents = head_measurement["documents"]
    frame_base, frame_head = _side(base_measurement["frame"]), _side(head_measurement["frame"])
    documents = []
    for member in sorted(head_documents):
        side_base, side_head = _side(base_documents[member]), _side(head_documents[member])
        tree = head_documents[member]["tree"]
        documents.append({
            "member": member,
            "hosts": [host for host in HOSTS if _counts_on(tree, host)],
            "base": side_base, "head": side_head, "delta": _delta(side_base, side_head),
        })
    profiles = []
    for profile in model["profiles"]:
        totals = head_measurement["profiles"][profile["id"]]
        profiles.append({
            "id": profile["id"],
            "entry": profile.get("entry"),
            "launch": profile.get("launch"),
            "prompt": profile["prompt"],
            "note": profile["note"],
            "unread": profile["unread"],
            "hosts": {
                host: {
                    **{kind: _compare_total(totals[host][kind], base_documents, head_documents)
                       for kind in ("hot", "conditional")},
                    "ceiling_bytes": profile["ceiling_bytes"][host],
                }
                for host in profile["hosts"]
            },
        })
    return {
        "base": base,
        "head": head,
        "frame": {"member": FRAME_MEMBER, "base": frame_base, "head": frame_head,
                  "delta": _delta(frame_base, frame_head)},
        "documents": documents,
        "profiles": profiles,
    }


def render_json(report: dict) -> str:
    return json.dumps(report, indent=2, ensure_ascii=False) + "\n"


def _signed(value: int) -> str:
    return f"{value:+d}" if value else "0"


def _row(cells: list[str]) -> str:
    return "| " + " | ".join(cells) + " |"


def _table(leading: list[str], trailing: list[str], rows: list[list[str]]) -> list[str]:
    """A pipe table whose six size columns sit between `leading` and `trailing` columns."""
    alignment = ["---"] * len(leading) + ["---:"] * len(SIZE_COLUMNS) + ["---"] * len(trailing)
    return [_row([*leading, *SIZE_COLUMNS, *trailing]), _row(alignment), *map(_row, rows)]


def _sizes(base: dict, head: dict, delta: dict) -> list[str]:
    def byte_cell(side: dict) -> str:
        return "absent" if side.get("absent") else str(side["bytes"])

    return [byte_cell(base), byte_cell(head), _signed(delta["bytes"]),
            str(base["words"]), str(head["words"]), _signed(delta["words"])]


def _code_list(members: list[str]) -> str:
    return ", ".join(f"`{member}`" for member in members) or "none"


def _profile_section(profile: dict) -> list[str]:
    if profile["entry"] is not None:
        launched = f"entry `{profile['entry']}`"
    else:
        launched = "sites " + _code_list(profile["launch"])
    prompt = ("none (an entry)" if profile["prompt"] is None
              else f"`{profile['prompt']}` (not measured)")
    lines = [f"### {profile['id']}", "", f"- Launched by: {launched}", f"- Prompt: {prompt}"]
    for host, totals in profile["hosts"].items():
        lines.append(f"- {host} — hot: {_code_list(totals['hot']['members'])}; "
                     f"conditional: {_code_list(totals['conditional']['members'])}")
    lines += [f"- Unread: `{member}` — {reason}" for member, reason in profile["unread"].items()]
    return lines


def render_markdown(report: dict) -> str:
    base, head = report["base"], report["head"]
    frame = report["frame"]
    lines = [
        f"# Instruction load: {base[:7]} → {head[:7]}",
        "",
        f"- Base: `{base}`",
        f"- Head: `{head}`",
        f"- Regenerate: `{REGENERATE.format(base=base, head=head)}`",
        "",
        PREFACE[0],
        "",
        PREFACE[1],
        "",
        "## Frame",
        "",
        *_table(["Member"], [], [[f"`{frame['member']}`",
                                  *_sizes(frame["base"], frame["head"], frame["delta"])]]),
    ]
    for kind, heading in (("hot", "## Hot totals"), ("conditional", "## Conditional totals")):
        rows = [
            [profile["id"], host, *_sizes(total[kind]["base"], total[kind]["head"],
                                          total[kind]["delta"]),
             "yes" if total[kind]["affected"] else "no", profile["note"].replace("|", "\\|")]
            for profile in report["profiles"]
            for host, total in profile["hosts"].items()
        ]
        lines += ["", heading, "", *_table(["Profile", "Host"], ["Affected", "Note"], rows)]
    rows = [[f"`{document['member']}`", ", ".join(document["hosts"]),
             *_sizes(document["base"], document["head"], document["delta"])]
            for document in report["documents"]]
    lines += ["", "## Documents", "", *_table(["Member", "Hosts"], [], rows)]
    lines += ["", "## Members by profile"]
    for profile in report["profiles"]:
        lines += ["", *_profile_section(profile)]
    return "\n".join(lines) + "\n"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-instruction-load",
        description="Compare the instruction documents each agent profile loads at two revisions.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    report = commands.add_parser("report", help="report the load at --base against --head")
    report.add_argument("--base", required=True, help="the base revision")
    report.add_argument("--head", required=True, help="the head revision; the model is read here")
    report.add_argument("--output", type=Path, help="write the report here instead of stdout")
    report.add_argument("--format", choices=("markdown", "json"), default="markdown")
    report.add_argument("--root", type=Path, default=Path("."), help="the repository")
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        base, read_base = revision_reader(args.root, args.base)
        head, read_head = revision_reader(args.root, args.head)
        raw = read_head(MODEL_PATH)
        if raw is None:
            raise ValueError(f"no {MODEL_PATH} at {head}")
        try:
            model = load_model(raw)
        except ValueError as error:
            raise ValueError(f"invalid model at {head}: {error}") from None
        violations = validate(model, read_head)
        if violations:
            raise ValueError(f"invalid model at {head}: " + "; ".join(violations))
        report = compare(model, measure(model, read_base), measure(model, read_head), base, head)
        text = render_json(report) if args.format == "json" else render_markdown(report)
        if args.output is None:
            sys.stdout.buffer.write(text.encode("utf-8"))
        else:
            args.output.write_text(text, encoding="utf-8")
    except (ValueError, OSError) as error:
        print(f"agent-instruction-load: {' '.join(str(error).split())}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
