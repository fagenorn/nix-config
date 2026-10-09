"""Measure the instruction documents each agent profile loads, per host, and compare two revisions."""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
import json
from pathlib import Path
import posixpath
import re
import subprocess
import sys
from typing import Any, Optional

from agent_tools.agent_model_matrix import (
    MATRIX_PATH,
    SUBAGENT_TYPE,
    parse_matrix,
)
from agent_tools.canonical import reject_duplicate_keys, reject_nonfinite_literal
from agent_tools import skill_lint
from agent_tools.skill_lint import (
    AGENTS_DIR,
    CLAUDE_TREE,
    MD_TOKEN,
    SHARED_TREE,
    Reader,
    Snapshot,
    names,
    parse_frontmatter,
    read_listed,
    skill_dirs,
    split_member,
    tree_reader,
)


MODEL_PATH = "home/common/agent-skills/instruction-load.json"
FRAME_MEMBER = "agent-guidance/AGENTS.md"
FRAME_PATH = "home/common/agent-guidance/AGENTS.md"
HOSTS = ("claude", "codex")
TOP_LEVEL_KEYS = (
    "frame",
    "profiles",
    "excluded_sites",
    "corpus_ceiling_bytes",
    "description_ceiling_bytes",
)
PROFILE_KEYS = (
    "id",
    "hosts",
    "prompt",
    "hot",
    "conditional",
    "unread",
    "ceiling_bytes",
    "conditional_ceiling_bytes",
    "note",
)
PROFILE_CHOICE_KEYS = ("entry", "launch")
# The gate's ceilings (#292 D4). A model committed before the gate has none of
# them, and `report` still reads such a model; `check` and `tighten` require them.
GATE_TOP_LEVEL_KEYS = ("corpus_ceiling_bytes", "description_ceiling_bytes")
GATE_PROFILE_KEYS = ("conditional_ceiling_bytes",)
SKILL_NAME = re.compile(r"[A-Za-z0-9_-]+")
WORKFLOW_PATH = ".github/workflows/instruction-budget.yaml"
RAISE_LABEL = "instruction-budget-raise"
GATE_FILES = (
    WORKFLOW_PATH,
    "python/agent_tools/skill_lint.py",
    "python/agent_tools/instruction_load.py",
    ".github/branch-protection.json",
)
REGENERATE = "just agent-instruction-load report --base {base} --head {head} --output <path>"


def _git(root: Path, *args: str) -> bytes:
    completed = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if completed.returncode != 0:
        lines = completed.stderr.decode("utf-8", "replace").strip().splitlines()
        raise ValueError(f"git {args[0]} failed: {lines[-1] if lines else ''}")
    return completed.stdout


def revision_snapshot(root: Path, revision: str) -> tuple[str, Snapshot]:
    """The full commit SHA of `revision`, and a snapshot of that commit's tree."""
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

    return sha, Snapshot(
        read=read,
        list_files=lambda prefix: sorted(p for p in present if p.startswith(prefix + "/")),
    )


def revision_reader(root: Path, revision: str) -> tuple[str, Reader]:
    """The full commit SHA of `revision`, and a reader over that commit's tree."""
    sha, snapshot = revision_snapshot(root, revision)
    return sha, snapshot.read


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


def _sibling(member: str, name: str) -> str:
    """The member spelling of `name` in `member`'s own skill."""
    skill, _ = split_member(member)
    return f"{skill}/{name}"


def resolve(member: str, read: Reader) -> list[tuple[str, str]]:
    """The `(tree, path)` documents a member spelling names that exist."""
    parts = split_member(member)
    if parts is None:
        return []
    skill, name = parts
    candidates = [("shared", f"{SHARED_TREE}/{member}"), ("claude-only", f"{CLAUDE_TREE}/{member}")]
    if skill == "agents":
        candidates.append(("agents", f"{AGENTS_DIR}/{name}"))
    return [(tree, path) for tree, path in candidates if read(path) is not None]


def _is_string_list(value: object) -> bool:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _is_reason_map(value: object) -> bool:
    return isinstance(value, dict) and all(isinstance(reason, str) for reason in value.values())


def _is_byte_count(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _top_level_violations(model: dict, read: Reader, gate_fields: bool = True) -> list[str]:
    found = [f"model: missing key '{key}'" for key in TOP_LEVEL_KEYS
             if key not in model and (gate_fields or key not in GATE_TOP_LEVEL_KEYS)]
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
    for key in ("corpus_ceiling_bytes", "description_ceiling_bytes"):
        if key in model and not _is_byte_count(model[key]):
            found.append(f"model: {key} must be a non-negative integer")
    return found


def _ceiling_map_violations(key: str, value: object, hosts: object,
                            hosts_valid: bool) -> list[str]:
    """Violations of one per-host ceiling map of a profile."""
    if not isinstance(value, dict):
        return [f"{key} must map hosts to byte counts"]
    found = []
    if hosts_valid and set(value) != set(hosts):
        found.append(f"{key} hosts {sorted(value)} differ from hosts {sorted(hosts)}")
    found += [
        f"{key} {host} must be a non-negative integer"
        for host, ceiling in value.items()
        if not _is_byte_count(ceiling)
    ]
    return found


def _profile_violations(profile: object, gate_fields: bool = True) -> list[str]:
    """Unprefixed structural violations of one profile."""
    if not isinstance(profile, dict):
        return ["must be an object"]
    found = [f"missing key '{key}'" for key in PROFILE_KEYS
             if key not in profile and (gate_fields or key not in GATE_PROFILE_KEYS)]
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
    for key in ("ceiling_bytes", "conditional_ceiling_bytes"):
        if gate_fields or key not in GATE_PROFILE_KEYS or key in profile:
            found += _ceiling_map_violations(key, profile.get(key), hosts, hosts_valid)
    note = profile.get("note")
    if not isinstance(note, str) or not note.strip():
        found.append("empty note")
    return found


def _structure_violations(profiles: list,
                          gate_fields: bool = True) -> tuple[list[str], list[dict]]:
    """Every profile's structural violations, and the profiles that have none."""
    violations: list[str] = []
    sound: list[dict] = []
    seen: set[str] = set()
    for index, profile in enumerate(profiles):
        profile_id = profile.get("id") if isinstance(profile, dict) else None
        named = isinstance(profile_id, str) and bool(profile_id)
        label = profile_id if named else f"#{index}"
        found = _profile_violations(profile, gate_fields)
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
        if not any(names(source, texts[source], member) for source in sources):
            found.append(f"{member} is named by neither its prompt nor another member")

    for member in skill_documents:
        folder = posixpath.dirname(resolved[member][1])
        for token in sorted(set(MD_TOKEN.findall(texts[member]))):
            sibling = _sibling(member, token)
            if read(f"{folder}/{token}") is not None and sibling not in listed:
                found.append(f"{member} names {sibling}, which the profile does not list")
    return [f"profile {profile['id']}: {message}" for message in found]


def validate(model: dict, read: Reader, *, gate_fields: bool = True) -> list[str]:
    """Every violation of the model, in report order; empty when it is sound.

    With ``gate_fields`` false, a model that predates the gate's ceilings is
    still sound: ``report`` reads models committed before them.
    """
    violations = _top_level_violations(model, read, gate_fields)
    profiles = model.get("profiles")
    profiles = profiles if isinstance(profiles, list) else []
    structure, sound = _structure_violations(profiles, gate_fields)
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


CEILING_KINDS = {"ceiling_bytes": "hot", "conditional_ceiling_bytes": "conditional"}


def measure_corpus(snapshot: Snapshot) -> dict[str, int]:
    """Bytes of every instruction document, and of every skill description."""
    total = 0
    descriptions = 0
    for directory in skill_dirs(snapshot):
        members = [directory.skill_md] if directory.skill_md is not None else []
        members += [*directory.references, *directory.payloads]
        total += sum(len(read_listed(snapshot, path)) for path in members)
        if directory.skill_md is not None:
            raw = read_listed(snapshot, directory.skill_md)
            try:
                fields, _ = parse_frontmatter(raw.decode("utf-8"))
            except ValueError:
                continue
            descriptions += len(fields.get("description", "").encode("utf-8"))
    for path in snapshot.list_files(AGENTS_DIR):
        if path.endswith(".md") and "/" not in path[len(AGENTS_DIR) + 1:]:
            total += len(read_listed(snapshot, path))
    total += len(snapshot.read(FRAME_PATH) or b"")   # the frame is read by path: absent counts 0
    return {"corpus": total, "descriptions": descriptions}


@dataclass(frozen=True)
class Ceiling:
    label: str
    location: tuple[str, ...]
    ceiling: int
    measured: int


def ceiling_locations(model: dict) -> list[tuple[str, ...]]:
    """Where each ceiling lives in `model`; the one definition, tolerant of an invalid model."""
    found: list[tuple[str, ...]] = []
    profiles = model.get("profiles")
    for profile in profiles if isinstance(profiles, list) else []:
        if not (isinstance(profile, dict) and isinstance(profile.get("id"), str)):
            continue
        hosts = profile.get("hosts")
        if not _is_string_list(hosts):
            continue
        for host in hosts:
            found += [("profiles", profile["id"], key, host) for key in CEILING_KINDS]
    return [*found, ("corpus_ceiling_bytes",), ("description_ceiling_bytes",)]


def _ceiling_at(model: dict, location: tuple[str, ...]) -> int:
    if location[0] != "profiles":
        return model[location[0]]
    _, profile_id, key, host = location
    return next(p for p in model["profiles"]
                if isinstance(p, dict) and p.get("id") == profile_id)[key][host]


def ceilings(model: dict, measurement: dict, corpus: dict[str, int]) -> list[Ceiling]:
    """Every ceiling of a valid model with its measured size, in `ceiling_locations` order."""
    found = []
    for location in ceiling_locations(model):
        if location[0] == "profiles":
            _, profile_id, key, host = location
            kind = CEILING_KINDS[key]
            label = f"profile {profile_id} on {host}: {kind}"
            measured = measurement["profiles"][profile_id][host][kind]["bytes"]
        elif location[0] == "corpus_ceiling_bytes":
            label, measured = "corpus", corpus["corpus"]
        else:
            label, measured = "descriptions", corpus["descriptions"]
        found.append(Ceiling(label, location, _ceiling_at(model, location), measured))
    return found


def breached(found: list[Ceiling]) -> list[Ceiling]:
    return [c for c in found if c.measured > c.ceiling]


def loose(found: list[Ceiling]) -> list[Ceiling]:
    """The ceilings more than 5% above what they measure."""
    return [c for c in found if 100 * c.ceiling > 105 * c.measured]


def _slot(model: dict, location: tuple[str, ...]) -> Optional[dict]:
    """The dict holding `location`'s last key, or None when it does not resolve.

    A profile is matched by id, and only when `model` holds exactly one profile with it.
    """
    if len(location) == 1:
        return model
    _, profile_id, kind, _ = location
    profiles = model.get("profiles") if isinstance(model.get("profiles"), list) else []
    matches = [p for p in profiles if isinstance(p, dict) and p.get("id") == profile_id]
    if len(matches) != 1 or not isinstance(matches[0].get(kind), dict):
        return None
    return matches[0][kind]


def lowered_to(model: dict, base: dict) -> dict:
    """`model` with each ceiling that is at or below its base value set to that value.

    Raise control compares the result with `base`: anything still unequal is a change
    other than lowering a ceiling. Non-dict and non-list values are skipped, never lowered.
    """
    result = copy.deepcopy(model)
    for location in ceiling_locations(result):
        target, source, key = _slot(result, location), _slot(base, location), location[-1]
        if target is not None and source is not None and _is_byte_count(target.get(key)) \
                and _is_byte_count(source.get(key)) and target[key] <= source[key]:
            target[key] = source[key]
    return result


def tightened(model: dict, found: list[Ceiling]) -> tuple[dict, list[str]]:
    """`model` with every ceiling above its measure lowered to it, and the lines saying so."""
    result = copy.deepcopy(model)
    lines = []
    for c in found:
        if c.ceiling > c.measured:
            _slot(result, c.location)[c.location[-1]] = c.measured
            lines.append(f"lowered {c.label}: {c.ceiling} -> {c.measured}")
    return result, lines


def run_check(head: Snapshot, base: Optional[Snapshot], raise_label: bool) -> list[str]:
    """Every failing line of the gate, in step order; raises ValueError when it cannot run."""
    lines = [f"lint: {line}" for line in skill_lint.lint(head)]
    raw = head.read(MODEL_PATH)
    if raw is None:
        raise ValueError(f"no {MODEL_PATH} in the working tree")
    model = load_model(raw)
    violations = validate(model, head.read)
    if violations:
        lines += [f"ceiling: invalid model: {violation}" for violation in violations]
    else:
        found = ceilings(model, measure(model, head.read), measure_corpus(head))
        lines += [
            f"ceiling: {c.label} measures {c.measured} bytes, above its ceiling {c.ceiling}; "
            f"cut the text, or raise the ceiling in a PR carrying the {RAISE_LABEL} label"
            for c in breached(found)
        ]
        lines += [
            f"tightness: {c.label} ceiling {c.ceiling} is more than 5% above its measured "
            f"{c.measured} bytes; run `just agent-instruction-load tighten`"
            for c in loose(found)
        ]
    if base is not None and base.read(WORKFLOW_PATH) is not None:
        base_raw = base.read(MODEL_PATH)
        if base_raw is None:
            raise ValueError(f"no {MODEL_PATH} at the base")
        base_model = load_model(base_raw)
        if not raise_label:
            if lowered_to(model, base_model) != base_model:
                lines.append(f"raise: {MODEL_PATH} changes more than lowering a ceiling; "
                             f"revert it, or have a human apply the {RAISE_LABEL} label")
            lines += [
                f"raise: gate file {path} differs from the base; "
                f"revert it, or have a human apply the {RAISE_LABEL} label"
                for path in GATE_FILES if head.read(path) != base.read(path)
            ]
    return lines


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
    check = commands.add_parser("check", help="run the growth gate on the working tree")
    check.add_argument("--base", help="the base revision for raise control")
    check.add_argument("--raise-label", action="store_true",
                       help="the pull request carries the raise label")
    check.add_argument("--root", type=Path, default=Path("."), help="the repository")
    tighten = commands.add_parser("tighten", help="lower every loose ceiling to its measure")
    tighten.add_argument("--root", type=Path, default=Path("."), help="the repository")
    return parser


def _report(args: argparse.Namespace) -> int:
    base, read_base = revision_reader(args.root, args.base)
    head, read_head = revision_reader(args.root, args.head)
    raw = read_head(MODEL_PATH)
    if raw is None:
        raise ValueError(f"no {MODEL_PATH} at {head}")
    try:
        model = load_model(raw)
    except ValueError as error:
        raise ValueError(f"invalid model at {head}: {error}") from None
    violations = validate(model, read_head, gate_fields=False)
    if violations:
        raise ValueError(f"invalid model at {head}: " + "; ".join(violations))
    report = compare(model, measure(model, read_base), measure(model, read_head), base, head)
    text = render_json(report) if args.format == "json" else render_markdown(report)
    if args.output is None:
        sys.stdout.buffer.write(text.encode("utf-8"))
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


def _check(args: argparse.Namespace) -> int:
    if args.raise_label and args.base is None:
        raise ValueError("--raise-label needs --base")
    head = skill_lint.working_tree(args.root)
    base = None if args.base is None else revision_snapshot(args.root, args.base)[1]
    if base is not None and base.read(WORKFLOW_PATH) is None:
        print(f"agent-instruction-load: the base has no {WORKFLOW_PATH}; "
              f"raise control skipped", file=sys.stderr)
    lines = run_check(head, base, args.raise_label)
    print("\n".join(lines) if lines else "check: pass")
    return 1 if lines else 0


def _tighten(args: argparse.Namespace) -> int:
    snapshot = skill_lint.working_tree(args.root)
    raw = snapshot.read(MODEL_PATH)
    if raw is None:
        raise ValueError(f"no {MODEL_PATH} in the working tree")
    model = load_model(raw)
    violations = validate(model, snapshot.read)
    if violations:
        raise ValueError("invalid model: " + "; ".join(violations))
    found = ceilings(model, measure(model, snapshot.read), measure_corpus(snapshot))
    result, lowered = tightened(model, found)
    if lowered:
        (args.root / MODEL_PATH).write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("\n".join(lowered))
    over = breached(found)
    for c in over:
        print(f"breach {c.label}: measures {c.measured} bytes, above its ceiling {c.ceiling}")
    return 1 if over else 0


def main(argv: Optional[list[str]] = None) -> int:
    args = _parser().parse_args(argv)
    handler = {"report": _report, "check": _check, "tighten": _tighten}[args.command]
    try:
        return handler(args)
    except (ValueError, OSError) as error:
        print(f"agent-instruction-load: {' '.join(str(error).split())}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
