"""Issue-100 retained history: archive envelope, two byte domains and the two-level payload (issue 234; S10, S11).

Archive members come from an explicit directory, bounded and unfollowed, with raw sizes and digests checked
before any decode. Historical and fresh records are separate domains, each under its own policy.

The model is SOURCE's object, `schema_version` 1: `model_100` reads it from Git and it exists only in
memory. The payload is the compact object, `schema_version` 2, whose canonical bytes are the bundle file
(issue 254). `compact_100` and `expand_100` map each to the other, and they and `validate_100` are Git-free.
"""
from __future__ import annotations

import base64
from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess
from types import SimpleNamespace

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import (RECORD_POLICY, RECORD_POLICY_SHA256, GenerationError, _split_diff,
                                       actual_inputs_from_trees)
from agent_tools.review_forecast import (ForecastError, canonical_bytes, edge_facts, read_regular, strict_json,
                                         tree_entry)
from agent_tools.review_git import HistoryError, original_commit, original_commits, original_range

KIND = "issue-100-retained-history"
HISTORICAL_DOMAIN = "retained-git-records/v1"
SOURCE_COMMIT, SOURCE_BLOB = "55cef0357fc648bede7e6840d6186d7dd4d10dd8", "913ab952801cf9d8dc59d89fa674a3ba38a3ed2d"
# Parent R3's archive producer as its D11 argv and `-c` config, applied to the authenticated base and head trees.
RECIPE = ("-c", "diff.renames=true", "-c", "diff.renameLimit=0", "-c", "core.quotePath=true", "-c", "core.abbrev=8",
          "diff", "--no-ext-diff", "--no-textconv", "--binary", "-U10", "--find-renames=50%", "--diff-algorithm=myers",
          "--indent-heuristic", "--no-color", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
          "--inter-hunk-context=0", "--line-prefix=", "--output-indicator-new=+", "--output-indicator-old=-",
          "--output-indicator-context= ")
DISPOSITIONS = ("historical_process", "integrated", "candidate")
_PAIRS = (("base", "live"), ("live", "head"), ("base", "head"))
_INITIAL, _MIGRATION = "issue-100-initial", "issue-100-migration-2026-09-19"
# R3's criteria: id, original SHA-256, text.
_CRITERIA = """
AC-OLD-01 ad3509117c6ad03e49f68fd20520843553706cc683f98102e2b380642f0d398a Output distinguishes configured, auto-detected, and defaulted for every emitted key
AC-OLD-02 c8abf7706c75658ef6a8ba73fa40140f1d9e5403da6ab73318b849df56be23c0 A strict mode exits non-zero and names every key that resolved only to a default
AC-OLD-03 dc718580d7766bdd7be987b8158c561af3504231ab93853ddfe456144ef8e9cd Default non-strict output remains backward compatible for existing readers
AC-OLD-04 5021471e205ed01c84d243730b27d572c65a16ac6bc4423e811cd028e7eb49f8 Skills that require a project-specific binding to be real — integration branch, verify commands — treat a defaulted value as blocked and report it, rather than proceeding on the default
AC-OLD-05 1127af5424bd319b0e9f7be1911bfffaf908f71b8ae19a00b348cdbe08d87fa2 Covered by the binding-resolution test suite, including the no-config and not-a-repository cases
AC-MIG-01 c11d9f65c0c025fceec62b9f8c202a00d5ef15cad0eea94960db706f13fd302c Every living skill and workflow consumer resolves project policy once through `resolve-project` and uses the returned `ResolvedProject` without a second policy read.
AC-MIG-02 15afd03262cb1b2df80182c55170ab4fe3ca7d86819ba36fda85135651164d19 No living source or installed-skill reference invokes `resolve-bindings`; historical point-in-time artifacts remain unchanged.
AC-MIG-03 db493e82e5504764c471f4789481e6291be21d6478886756fcec1bd897486219 Legacy default-fallback behavior is deleted or quarantined so it cannot serve a living consumer.
AC-MIG-04 374722326039232ca88c9dde41078aae76f840398097c1a5b50f6e2ff380783e Managed source and installed skill trees pass the same zero-reference and behavior checks.
AC-MIG-05 0ce5e6a18e92c7da6a6bb9fbf27ca04e465228f47791035f942de0fee636d839 Fixtures for missing configuration, malformed configuration, a non-repository directory, and generated-projection drift fail closed with the resolver's documented error shape.
"""


def _criterion(identifier: str, sha256: str, text: str) -> dict:
    """A superseded criterion has no obligation; a governing one names the children it binds."""
    old = identifier.startswith("AC-OLD")
    return {"id": identifier, "contract": _INITIAL if old else _MIGRATION, "state": "superseded" if old else "governing",
            "text": text, "text_sha256": sha256, "superseded_by": _MIGRATION if old else None,
            "obligations": [] if old else ["source-cutover"] + ([] if identifier == "AC-MIG-05" else ["host-activation"])}


CRITERIA = tuple(_criterion(*line.split(" ", 2)) for line in _CRITERIA.strip().splitlines())


def _historical_policy(recipe) -> str:
    return telemetry_digest({"kind": HISTORICAL_DOMAIN, "source_commit": SOURCE_COMMIT, "source_blob": SOURCE_BLOB,
                             "recipe": list(recipe)})


class Issue100Error(Exception):
    """Issue-100 evidence is unreadable, unauthenticated or invalid; `code` names why."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class Domain:
    name: str
    policy_sha256: str
    bytes: int
    records: int
    sha256: str


@dataclass(frozen=True)
class Issue100Pins:
    base: str
    head: str
    live: str
    producer_name: str
    manifest_name: str
    producer_bytes: int
    manifest_bytes: int
    producer_sha256: str
    manifest_sha256: str
    process_paths: frozenset[str]
    pending_paths: tuple[str, ...]
    criteria: tuple[dict, ...]
    recipe: tuple[str, ...]
    historical: Domain
    fresh: Domain
    expected_counts: dict
    parent_edges_sha256: str  # `telemetry_digest` of the raw parent edges, in range order (S23)


_R3 = "2026-09-19-issue-100-strict-project-resolver"
ISSUE_100_PINS = Issue100Pins(
    "6d4b7a49dd3a44c079c8310e902a86665a6805f0", "a7b7c6f45787c7c928d064b46ed499087b5b3c46",
    "cba57498b1ec25f904bd2653029636c79abba41f", "source-integration-cumulative-producer.raw",
    "review-6d4b7a4..a7b7c6f.json", 452, 10786, "7e6f109010a086cbc824f725901295a8d55c206581ccc01ea13252b4f8690c03",
    "b875b841df469dde60578d4f5ea523b5c4aa86c8db26cadf4942c332628e82b7",
    frozenset({f".claude/specs/{_R3}-design.md", f".claude/plans/{_R3}.md",
               *(f".claude/plans/{_R3}.tasks/task-{n}.md" for n in range(1, 7))}),
    (".github/workflows/ci.yaml", "CLAUDE.md", "justfile", "tests/test_branch_protection.py"), CRITERIA, RECIPE,
    Domain(HISTORICAL_DOMAIN, _historical_policy(RECIPE), 1005707, 115,
           "3869e4bf81caa1374f7a49591ec4551aa7de56cdec37468bb1e62293662492bc"),
    Domain(RECORD_POLICY["kind"], RECORD_POLICY_SHA256, 1012913, 115,
           "5c6c4fbe291994ee9d08e6ebf45f6369e6a8b3db4f96908989e2a152ca3ec9d4"),
    {"commits": 82, "parent_edges": 91, "merge_edges": 9, "edge_records": 543, "contributions": 115,
     "historical_process": 8, "integrated": 38, "candidate": 69, "candidate_ordinary": 65,
     "candidate_reconciliation": 4, "pending_overlaps": 4, "reconciled": 0},
    "sha256:b210dd7252a94fbf46078a093905661404c0ee02ac62cde7937d941f2b918101")


def _require(condition, code="invalid_payload") -> None:
    if not condition:
        raise Issue100Error(code)


def _closed(value, keys, code="invalid_payload") -> dict:
    _require(isinstance(value, dict) and set(value) == set(keys), code)
    return value


def _same(left, right) -> bool:  # canonical, so `True` never stands in for `1`
    try:
        return canonical_bytes(left) == canonical_bytes(right)
    except (TypeError, ValueError):
        return False


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _match(pattern, value) -> bool:
    return isinstance(value, str) and re.fullmatch(pattern, value) is not None


def _hex(value, size=40) -> bool:
    return _match("[0-9a-f]{%d}" % size, value)


def _count(value) -> bool:
    return type(value) is int and value >= 0


def _text(value) -> bool:
    return isinstance(value, str) and value != ""


def _identified(row: dict) -> dict:
    return {**row, "id": telemetry_digest(row)}


def _policy(domain: Domain) -> dict:
    return {"domain": domain.name, "policy_sha256": domain.policy_sha256}


@contextmanager
def _authenticated():
    try:
        yield
    except (HistoryError, ForecastError) as exc:
        raise Issue100Error("history_unauthenticated") from exc
    except GenerationError as exc:
        raise Issue100Error("evidence_unavailable") from exc


def _checked(pins: Issue100Pins) -> Issue100Pins:
    """Closed pins over R3's criteria, each text hashing to its original digest; each archive digest pin
    is a `str` of 64 lowercase hex."""
    p, bad = pins, "invalid_pins"
    _require(isinstance(p, Issue100Pins), bad)
    pending, domains = p.pending_paths, (p.historical, p.fresh)
    _require(all(_hex(v) for v in (p.base, p.head, p.live)) and isinstance(p.manifest_name, str)
             and all(_hex(v, 64) for v in (p.producer_sha256, p.manifest_sha256))
             and p.manifest_name.endswith(".json") and p.producer_name != p.manifest_name
             and all(type(n) is int and n > 0 for n in (p.producer_bytes, p.manifest_bytes))
             and isinstance(p.process_paths, frozenset) and all(_text(path) for path in p.process_paths)
             and isinstance(pending, tuple) and all(_text(path) for path in pending)
             and len(pending) == len(set(pending) - p.process_paths), bad)
    _require(isinstance(p.criteria, tuple) and _same(p.criteria, CRITERIA)
             and all(_sha(row["text"].encode()) == row["text_sha256"] for row in CRITERIA)
             and isinstance(p.recipe, tuple) and all(isinstance(a, str) for a in p.recipe) and "diff" in p.recipe
             and all(isinstance(d, Domain) and _count(d.bytes) and _count(d.records) and _hex(d.sha256, 64)
                     for d in domains)
             and _same([_policy(d) for d in domains], [
                 {"domain": HISTORICAL_DOMAIN, "policy_sha256": _historical_policy(p.recipe)},
                 {"domain": RECORD_POLICY["kind"], "policy_sha256": RECORD_POLICY_SHA256}])
             and isinstance(p.expected_counts, dict) and set(p.expected_counts) == set(ISSUE_100_PINS.expected_counts)
             and all(_count(v) for v in p.expected_counts.values())
             and _match("sha256:[0-9a-f]{64}", p.parent_edges_sha256), bad)
    return p


def _read(directory, relative, size, sha256=...) -> bytes:
    try:
        raw = read_regular(directory, relative, size)
    except (OSError, ForecastError) as exc:
        raise Issue100Error("archive_unreadable") from exc
    _require(len(raw) == size and sha256 in (..., _sha(raw)), "archive_digest_mismatch")
    return raw


def _recipe(repo, pins, old_tree, new_tree, *paths) -> bytes:
    argv = ["git", "-C", str(repo), *pins.recipe, old_tree, new_tree, *(("--", *paths) if paths else ())]
    try:
        return subprocess.run(argv, check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Issue100Error("evidence_unavailable") from exc


def _historical(repo, pins) -> tuple[bytes, tuple]:
    """The recipe over the authenticated trees: its bytes and a `{bytes, sha256}` row per record."""
    with _authenticated():
        base, head = (c.tree for c in original_commits(repo, (pins.base, pins.head)))
        raw = _recipe(repo, pins, base, head)
        rows = tuple({"bytes": len(chunk), "sha256": _sha(chunk)} for chunk in _split_diff(raw))
    domain = pins.historical
    _require((len(raw), len(rows), _sha(raw)) == (domain.bytes, domain.records, domain.sha256), "domain_mismatch")
    return raw, rows


def _verified(archive_dir, repo, pins) -> tuple[dict, tuple]:
    producer = _read(archive_dir, pins.producer_name, pins.producer_bytes, pins.producer_sha256)
    manifest_raw = _read(archive_dir, pins.manifest_name, pins.manifest_bytes, pins.manifest_sha256)
    bad, domain = "archive_mismatch", pins.historical
    try:
        envelope, manifest = strict_json(producer), strict_json(manifest_raw)
    except ForecastError as exc:
        raise Issue100Error(bad) from exc
    fixed = {"interface_version": 1, "kind": "review-package", "purpose": "diff-review",
             "range": {"base": pins.base, "head": pins.head}, "total_diff_bytes": domain.bytes,
             "coverage": {"complete": True, "file_diff_count": domain.records}}
    _closed(manifest, (*fixed, "commits", "shards", "stat"), bad)
    shards, stem = manifest["shards"], pins.manifest_name[:-len(".json")]
    _require(isinstance(shards, list) and shards and isinstance(manifest["commits"], list)
             and _same({k: manifest[k] for k in fixed}, fixed), bad)
    for n, item in enumerate(shards, 1):
        _closed(item, ("path", "bytes"), bad)
        _require(item["path"] == f"{stem}.shards/shard-{n:03d}.diff" and _count(item["bytes"]), bad)
    # R3's producer envelope; its metrics are the manifest as root plus its shards.
    _require(isinstance(envelope, dict) and isinstance(envelope.get("artifact"), dict), bad)
    artifact, sizes = envelope["artifact"], [item["bytes"] for item in shards]
    metrics = {"file_count": len(shards) + 1, "largest_member_bytes": max(pins.manifest_bytes, *sizes),
               "root_bytes": pins.manifest_bytes, "total_bytes": pins.manifest_bytes + sum(sizes)}
    _require(_same({**envelope, "artifact": {**artifact, "path": None}}, {
        "notes": "validated review package", "state": "decompose_required", "artifact": {
            "budget_status": "over_budget", "kind": "review-package", "metrics": metrics, "path": None,
            "violations": ["member_count", "aggregate_bytes"]}})
        and isinstance(artifact.get("path"), str) and PurePosixPath(artifact["path"]).name == pins.manifest_name, bad)
    chunks = [_read(archive_dir, item["path"], item["bytes"]) for item in shards]
    combined = b"".join(chunks)
    _require(len(combined) == domain.bytes and _sha(combined) == domain.sha256, "archive_digest_mismatch")
    raw, rows = _historical(repo, pins)
    _require(combined == raw, "domain_mismatch")
    with _authenticated():
        listed = original_range(repo, pins.base, pins.head, topological=False)
    _require(all(isinstance(c, dict) and set(c) == {"sha", "subject"} and isinstance(c["subject"], str)
                 for c in manifest["commits"]) and [c["sha"] for c in manifest["commits"]] == list(listed), bad)
    shards = [{"path": item["path"], "bytes": len(c), "sha256": _sha(c)} for item, c in zip(shards, chunks)]
    return {"producer_sha256": _sha(producer), "manifest_sha256": _sha(manifest_raw), "shards": shards}, rows


def verify_archive(archive_dir: Path, issue_repo: Path, pins: Issue100Pins) -> dict:
    """The envelope at the explicit `archive_dir`, its shards reproducing the recipe byte for byte."""
    return _verified(Path(archive_dir), Path(issue_repo), _checked(pins))[0]


def historical_records(issue_repo: Path, pins: Issue100Pins) -> tuple[dict, ...]:
    """`{bytes, sha256}` per recipe record; never a review-package measurement."""
    return _historical(Path(issue_repo), _checked(pins))[1]


def fresh_records(issue_repo: Path, pins: Issue100Pins, limits) -> tuple[dict, ...]:
    """`{path, bytes, sha256}` per initial `actual_inputs_from_trees` record."""
    pins, repo = _checked(pins), Path(issue_repo)
    with _authenticated():
        base, head = (c.tree for c in original_commits(repo, (pins.base, pins.head)))
        initial = next(actual_inputs_from_trees(repo, base, head, base=pins.base, head=pins.head, commits=(),
                                                package_name="issue-100.json", limits=limits))
    records, domain = initial.records, pins.fresh
    raw = b"".join(record.payload for record in records)
    _require(all(record.generated_evidence is None for record in records)
             and (len(raw), len(records), _sha(raw)) == (domain.bytes, domain.records, domain.sha256), "domain_mismatch")
    return tuple({"path": r.path, "bytes": r.source_bytes, "sha256": _sha(r.payload)} for r in records)


def _refs(edges, path) -> list:
    """`[edge, record]` per record on `path` or a name it was renamed from or to."""
    names, size = {path}, 0
    while size != len(names):
        size = len(names)
        for edge in edges:
            for record in edge["records"]:
                if {record["path"], record["old_path"]} & names:
                    names |= {record["path"], record["old_path"]}
    return [[e, r] for e, edge in enumerate(edges) for r, record in enumerate(edge["records"])
            if {record["path"], record["old_path"]} & names]


def _counts(payload: dict) -> dict:
    rows, edges = payload["contributions"], payload["parent_edges"]
    labels = [row["disposition"] for row in rows]
    pending = [row["pending"] is not None for row in rows if row["disposition"] == "candidate"]
    return {"commits": len(payload["range"]["commits"]), "parent_edges": len(edges),
            "merge_edges": sum(edge["parent_ordinal"] > 1 for edge in edges),
            "edge_records": sum(len(edge["records"]) for edge in payload["edges"]), "contributions": len(rows),
            **{label: labels.count(label) for label in (*DISPOSITIONS, "reconciled")},
            "candidate_ordinary": pending.count(False), "candidate_reconciliation": pending.count(True),
            "pending_overlaps": len(payload["pending_overlaps"])}


def model_100(issue_repo: Path, live_repo: Path, archive_dir: Path, pins: Issue100Pins, limits) -> dict:
    """The schema-1 model, read from Git as SOURCE's derivation reads it: archive and domains verified, then
    raw parent edges in range order."""
    pins, repo, live_repo = _checked(pins), Path(issue_repo), Path(live_repo)
    _, historical = _verified(Path(archive_dir), repo, pins)
    fresh = fresh_records(repo, pins, limits)
    with _authenticated():
        commits = original_range(repo, pins.base, pins.head)
        original_commit(live_repo, pins.live)  # the live repository holds the same commit
        trees = dict(zip(("base", "live", "head"), (c.tree for c in original_commits(repo, (pins.base, pins.live, pins.head)))))
        parent_edges, edges = [], []
        held = dict(zip(commits, original_commits(repo, commits)))
        for oid in commits:
            for ordinal, parent in enumerate(held[oid].parents, 1):
                parent_edges.append({"parent": parent, "commit": oid, "parent_ordinal": ordinal})
                edges.append(edge_facts(repo, parent, oid, ordinal))
        overlaps = []
        for path in pins.pending_paths:
            entries = {f"{name}_entry": tree_entry(repo, trees[name], path) for name in ("base", "live", "head")}
            digests = {f"{a}_{b}_sha256": _sha(_recipe(repo, pins, trees[a], trees[b], path)) for a, b in _PAIRS}
            overlaps.append(_identified({"path": path, **entries, **digests}))
        pending = {row["path"]: row["id"] for row in overlaps}
        contributions = []
        for record in fresh:
            path = record["path"]
            head_entry, live_entry = tree_entry(repo, trees["head"], path), tree_entry(live_repo, trees["live"], path)
            disposition = ("historical_process" if path in pins.process_paths
                           else "integrated" if head_entry == live_entry else "candidate")
            contributions.append(_identified({
                "path": path, "record_sha256": record["sha256"], "head_entry": head_entry, "live_entry": live_entry,
                "edge_refs": _refs(edges, path), "disposition": disposition,
                "pending": pending.get(path) if disposition == "candidate" else None}))
    tables = {name: {"record_table_policy": _policy(domain), "records": list(records)} for name, domain, records in
              (("historical", pins.historical, historical), ("fresh", pins.fresh, fresh))}
    payload = {"schema_version": 1, "kind": KIND, "parent_edges": parent_edges, "edges": edges,
               "range": {"base": pins.base, "head": pins.head, "live": pins.live, "commits": list(commits)},
               "contributions": contributions, "pending_overlaps": overlaps, "tables": tables,
               "criteria": [{**row, "obligations": list(row["obligations"])} for row in pins.criteria]}
    payload["summary"] = _counts(payload)
    return payload


def derive_100(issue_repo: Path, live_repo: Path, archive_dir: Path, pins: Issue100Pins, limits) -> dict:
    """The validated schema-2 payload of the model `model_100` returns."""
    payload = compact_100(model_100(issue_repo, live_repo, archive_dir, pins, limits))
    validate_100(payload, pins)
    return payload


def _packed(hexes) -> str:
    """Hex digests as RFC 1924 base85 of their concatenated bytes: one token of 25 characters per object
    id, of 40 per SHA-256."""
    return base64.b85encode(bytes.fromhex("".join(hexes))).decode("ascii")


def _unpacked(text, size: int) -> list:
    """The hex digests, `size` bytes each, that a packed string holds. `text` must be a `str` that
    `b85decode` accepts and that decodes to whole items. Its text need not be whole tokens: one dangling
    character after the last whole token decodes to no byte (unless it overflows its group, which
    `b85decode` rejects), so such a string yields the same digests here. The canonical-form check in
    `validate_100` refuses it."""
    _require(isinstance(text, str))
    try:
        raw = base64.b85decode(text)
    except ValueError as exc:
        raise Issue100Error("invalid_payload") from exc
    _require(len(raw) % size == 0)
    return [raw[i:i + size].hex() for i in range(0, len(raw), size)]


def _pack(m: dict) -> dict:
    """The schema-2 members of model `m`: digests packed, paths and tree entries interned in sorted tables,
    each distinct edge record stored once in first-use order, and none of the members `expand_100` recomputes."""
    commits, rows = m["range"]["commits"], m["contributions"]
    nodes, records = [m["range"]["base"], *commits], [r for e in m["edges"] for r in e["records"]]
    used = [x for r in records for x in (r["before"], r["after"])]
    used += [row[k] for row in rows for k in ("head_entry", "live_entry")]
    used += [o["base_entry"] for o in m["pending_overlaps"]]
    groups = {}
    for e in used:
        if e is not None:
            groups.setdefault((e["mode"], e["kind"]), set()).add(e["oid"])
    entries, index = [], {}
    for key in sorted(groups):
        for oid in sorted(groups[key]):
            index[(*key, oid)] = len(index)
        entries.append([*key, _packed(sorted(groups[key]))])  # [mode, kind, packed oids]

    def ref(e):
        return None if e is None else index[(e["mode"], e["kind"], e["oid"])]
    fresh, historical = m["tables"]["fresh"], m["tables"]["historical"]
    paths = sorted({p for r in records for p in (r["path"], r["old_path"])}
                   | {r["path"] for r in fresh["records"]} | {o["path"] for o in m["pending_overlaps"]})
    at = {p: i for i, p in enumerate(paths)}
    table, seen, digests, edges = [], {}, [], []
    for edge in m["edges"]:
        refs = []
        for r in edge["records"]:
            key = canonical_bytes(r)
            if key not in seen:
                seen[key] = len(table)
                # [operation, path, before, after, record_bytes] and, for a rename, the old path
                table.append([r["operation"], at[r["path"]], ref(r["before"]), ref(r["after"]), r["record_bytes"],
                              *([at[r["old_path"]]] if r["old_path"] != r["path"] else [])])
                digests.append(r["record_sha256"][len("sha256:"):])
            refs.append(seen[key])
        edges.append(refs)
    parents, position = [[] for _ in commits], {c: i for i, c in enumerate(commits)}
    for edge in m["parent_edges"]:
        parents[position[edge["commit"]]].append(nodes.index(edge["parent"]))
    return {"schema_version": 2, "kind": m["kind"], "range": {k: m["range"][k] for k in ("base", "head", "live")},
            "commits": _packed(commits), "parents": parents, "paths": paths, "entries": entries, "records": table,
            "record_sha256": _packed(digests), "edges": edges,
            "tables": {"historical": {"record_table_policy": historical["record_table_policy"],
                                      "bytes": [r["bytes"] for r in historical["records"]],
                                      "sha256": _packed([r["sha256"] for r in historical["records"]])},
                       "fresh": {"record_table_policy": fresh["record_table_policy"],
                                 "paths": [at[r["path"]] for r in fresh["records"]],
                                 "bytes": [r["bytes"] for r in fresh["records"]],
                                 "sha256": _packed([r["sha256"] for r in fresh["records"]])}},
            "live": [ref(row["live_entry"]) for row in rows],
            # [fresh index, entry] where the head holds a directory; [path, base entry] per overlap
            "head_trees": [[i, ref(row["head_entry"])] for i, row in enumerate(rows)
                           if row["head_entry"] and row["head_entry"]["kind"] == "tree"],
            "process": [i for i, row in enumerate(rows) if row["disposition"] == "historical_process"],
            "pending_overlaps": [[at[o["path"]], ref(o["base_entry"])] for o in m["pending_overlaps"]],
            "overlap_sha256": _packed([o[f"{a}_{b}_sha256"] for o in m["pending_overlaps"] for a, b in _PAIRS]),
            "criteria": [{k: v for k, v in row.items() if k != "text_sha256"} for row in m["criteria"]]}


def compact_100(model: dict) -> dict:
    """The schema-2 payload of `model`. Pure. A model that `expand_100` of its payload does not equal
    canonically, a malformed model included, is `invalid_payload`."""
    try:
        payload = _pack(model)
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise Issue100Error("invalid_payload") from exc
    _require(_same(expand_100(payload), model))
    return payload


def _rows(value, *sizes: int) -> list:
    """`value`, a list of lists, each of a length among `sizes` where any is given."""
    _require(isinstance(value, list)
             and all(isinstance(row, list) and (not sizes or len(row) in sizes) for row in value))
    return value


def _columns(*columns) -> zip:
    """The rows across `columns`, lists of one length."""
    _require(all(isinstance(column, list) for column in columns) and len({len(column) for column in columns}) == 1)
    return zip(*columns)


def _at(rows, index):
    """`rows[index]`, for an in-range `int` that is not a `bool`."""
    _require(type(index) is int and 0 <= index < len(rows))
    return rows[index]


def expand_100(payload: dict) -> dict:
    """The schema-1 model that the schema-2 `payload` encodes. Pure: it reads the payload alone and leaves
    it unchanged. Every refusal it makes of a JSON value is `invalid_payload`. That describes its checks; it
    guards no interpreter limit: a value nested about as deep as the JSON decoder allows raises
    `RecursionError`, and nothing bounds the memory that the model of a large payload takes. Anything but
    the closed version-2 object of this kind is refused, and so are a value of the wrong type where one is
    read, a row or a column of the wrong length, an index that is not an in-range `int`, and a packed string
    that is not a `str`, that `b85decode` rejects, or whose bytes are not whole items. One second spelling
    passes that last test (see `_unpacked`): a single dangling character after the last whole token decodes
    to no byte, so the string expands to the same items. Expansion does not refuse it; the canonical-form
    check in `validate_100` does. So that the first-parent walk ends, the base and the commits are distinct,
    the head is one of them, and each commit names a parent, every one the base or an earlier commit. A
    fresh path and an overlap path have a head entry to take: the first is recorded on the walk, the second
    is a fresh path. Edge identity, repeated records, labels, references, ids, the summary and criterion
    digests are recomputed, never read. So is a head entry, except for a path that `head_trees` lists, a
    directory at the head: that entry is read from its row."""
    c = _closed(payload, ("schema_version", "kind", "range", "commits", "parents", "paths", "entries", "records",
                          "record_sha256", "edges", "tables", "live", "head_trees", "process", "pending_overlaps",
                          "overlap_sha256", "criteria"))
    _require(type(c["schema_version"]) is int and c["schema_version"] == 2 and c["kind"] == KIND)
    span, tables = _closed(c["range"], ("base", "head", "live")), _closed(c["tables"], ("historical", "fresh"))
    paths, commits, criteria = c["paths"], _unpacked(c["commits"], 20), c["criteria"]
    nodes = [span["base"], *commits]
    _require(isinstance(paths, list) and all(isinstance(path, str) for path in paths)
             and isinstance(c["process"], list) and isinstance(criteria, list)
             and all(isinstance(row, dict) and isinstance(row.get("text"), str) for row in criteria)
             and isinstance(span["base"], str) and len(set(nodes)) == len(nodes) and span["head"] in nodes
             and all(_rows(c["parents"])))
    parent_edges = [{"parent": _at(nodes[:i + 1], p), "commit": commit, "parent_ordinal": n}
                    for i, (commit, listed) in enumerate(_columns(commits, c["parents"]))
                    for n, p in enumerate(listed, 1)]
    entries = [{"mode": mode, "kind": kind, "oid": oid}
               for mode, kind, packed in _rows(c["entries"], 3) for oid in _unpacked(packed, 20)]

    def entry(index):
        return None if index is None else dict(_at(entries, index))
    facts = list(_columns(_rows(c["records"], 5, 6), _unpacked(c["record_sha256"], 32)))

    def record(index):
        row, digest = _at(facts, index)
        old = row[5] if len(row) > 5 else row[1]
        return {"operation": row[0], "path": _at(paths, row[1]), "old_path": _at(paths, old),
                "before": entry(row[2]), "after": entry(row[3]), "record_bytes": row[4],
                "record_sha256": "sha256:" + digest}
    edges = [{**raw, "records": [record(i) for i in refs]} for raw, refs in _columns(parent_edges, _rows(c["edges"]))]
    old, new = (_closed(tables[name], ("record_table_policy", "bytes", "sha256", *more))
                for name, more in (("historical", ()), ("fresh", ("paths",))))
    historical = [{"bytes": size, "sha256": digest}
                  for size, digest in _columns(old["bytes"], _unpacked(old["sha256"], 32))]
    fresh = [{"path": _at(paths, path), "bytes": size, "sha256": digest}
             for path, size, digest in _columns(new["paths"], new["bytes"], _unpacked(new["sha256"], 32))]
    m = {"schema_version": 1, "kind": KIND, "parent_edges": parent_edges, "edges": edges,
         "range": {**span, "commits": commits}}
    # `_at_head` reads `head` and `base` alone from its second argument, so the stored range stands for pins.
    at_head = _at_head(m, SimpleNamespace(**span))
    slots = range(len(fresh))  # `_at(slots, i)` is `i`, checked as a fresh index
    trees = {_at(slots, i): ref for i, ref in _rows(c["head_trees"], 2)}
    process, rows = {_at(slots, i) for i in c["process"]}, []
    for i, (row, live) in enumerate(_columns(fresh, c["live"])):
        path = row["path"]
        _require(path in at_head)
        head, live = entry(trees[i]) if i in trees else at_head[path], entry(live)
        label = "historical_process" if i in process else "integrated" if head == live else "candidate"
        rows.append({"path": path, "record_sha256": row["sha256"], "head_entry": head, "live_entry": live,
                     "edge_refs": _refs(edges, path), "disposition": label, "pending": None})
    by_path = {row["path"]: row for row in rows}
    stored, digests, overlaps = _rows(c["pending_overlaps"], 2), _unpacked(c["overlap_sha256"], 32), []
    _require(len(digests) == len(_PAIRS) * len(stored))
    for n, (path, before) in enumerate(stored):
        path = _at(paths, path)
        _require(path in by_path)
        overlaps.append(_identified({
            "path": path, "base_entry": entry(before), "live_entry": by_path[path]["live_entry"],
            "head_entry": by_path[path]["head_entry"],
            **{f"{a}_{b}_sha256": digests[len(_PAIRS) * n + k] for k, (a, b) in enumerate(_PAIRS)}}))
    pending = {row["path"]: row["id"] for row in overlaps}
    for row in rows:
        if row["disposition"] == "candidate":
            row["pending"] = pending.get(row["path"])
    m.update(contributions=[_identified(row) for row in rows], pending_overlaps=overlaps,
             tables={"historical": {"record_table_policy": old["record_table_policy"], "records": historical},
                     "fresh": {"record_table_policy": new["record_table_policy"], "records": fresh}},
             # A lone surrogate, which JSON can spell, is hashed rather than raised on.
             criteria=[{**row, "text_sha256": _sha(row["text"].encode("utf-8", "surrogatepass"))} for row in criteria])
    m["summary"] = _counts(m)
    return m


def _entry(value, file=None) -> bool:
    """A `tree_entry` fact. An edge record's side says whether its operation has a `file` there: a file
    where it has one, else nothing or the directory at that path (as `review_issue121._entry`)."""
    if value is None:
        return not file
    kinds = ("blob", "tree", "commit") if file is None else ("blob", "commit") if file else ("tree",)
    return _match("[0-7]{6}", value["mode"]) and value["kind"] in kinds


def _validate_history(payload, pins) -> None:
    """The pinned range ending at its head, the raw parent edges hashing to their pin (no parent is
    substituted, dropped or moved, however rehashed) and the shape of each edge record."""
    span, commits = payload["range"], payload["range"]["commits"]
    _require(_same({**span, "commits": 0}, {"base": pins.base, "head": pins.head, "live": pins.live, "commits": 0})
             and commits[-1:] == [pins.head])
    _require(telemetry_digest(payload["parent_edges"]) == pins.parent_edges_sha256)
    for edge in payload["edges"]:
        for record in edge["records"]:
            operation, path, old, before, after = (record[k] for k in ("operation", "path", "old_path", "before", "after"))
            _require(operation in ("A", "M", "D", "T", "R100") and _text(path) and _text(old)
                     and (operation == "R100") == (path != old)
                     and _entry(before, operation != "A") and _entry(after, operation != "D")
                     and _count(record["record_bytes"]))


def _validate_tables(payload, pins) -> None:
    """Each domain under its pinned policy, record count and byte sum, and each fresh path once."""
    for name, domain in (("historical", pins.historical), ("fresh", pins.fresh)):
        table = payload["tables"][name]
        records = table["records"]
        _require(_same(table["record_table_policy"], _policy(domain))
                 and len(records) == domain.records)
        for record in records:
            _require(_count(record["bytes"]))
        _require(sum(record["bytes"] for record in records) == domain.bytes)
    _require(len({record["path"] for record in records}) == len(records))


def _at_head(payload, pins) -> dict:
    """Each recorded path's file entry at the head, None where it holds no file: its latest record along the
    first-parent chain, whose edges are the whole tree difference of each step from the base to the head.
    A deletion leaves no file, though it may name the directory that replaced it, whose tree later changes."""
    first = {edge["commit"]: edge for edge in payload["edges"] if edge["parent_ordinal"] == 1}
    entries, oid = {}, pins.head
    while oid != pins.base:
        records, oid = first[oid]["records"], first[oid]["parent"]
        after = {r["path"]: None if r["operation"] == "D" else r["after"] for r in records}
        entries = {**{r["old_path"]: None for r in records}, **after, **entries}
    return entries


def _validate_contributions(payload, pins) -> None:
    """The overlaps on the pinned paths, each referenced once, each process label where the pins name the
    path, each stored entry shaped as one, and each head entry the one `_at_head` finds: where that is no
    file but a file lies below the path, a directory of whatever oid."""
    overlaps, rows, at_head = payload["pending_overlaps"], payload["contributions"], _at_head(payload, pins)
    _require(len(overlaps) == len(pins.pending_paths))
    by_id = {}
    for row, path in zip(overlaps, pins.pending_paths):
        _require(row["path"] == path and _entry(row["base_entry"]))
        by_id[row["id"]] = row
    referenced = []
    for row in rows:
        path, label, head = row["path"], row["disposition"], row["head_entry"]
        _require(_entry(row["live_entry"]) and (label == "historical_process") == (path in pins.process_paths))
        below = at_head[path] is None and any(e and name.startswith(path + "/") for name, e in at_head.items())
        _require(_same(head, {"mode": "040000", "kind": "tree", "oid": (head or {}).get("oid")}) if below
                 else _same(head, at_head[path]))
        if row["pending"] is not None:
            referenced.append(row["pending"])
    _require(sorted(referenced) == sorted(by_id))


def validate_100(payload: dict, pins: Issue100Pins) -> dict:
    """Git-free: the model of a schema-2 `payload`. In order, the pins are checked, the payload is expanded,
    an expansion that the pins do not determine is refused (range, raw parent edges, record shapes, both
    domains, overlaps, labels, head entries, criteria and the counts, which expansion recomputes from the
    tables: S10), and so is a payload that is not `compact_100` of its expansion."""
    pins = _checked(pins)
    model = expand_100(payload)
    _validate_history(model, pins)
    _validate_tables(model, pins)
    _validate_contributions(model, pins)
    _require(_same(model["criteria"], pins.criteria) and _same(model["summary"], pins.expected_counts))
    _require(_same(compact_100(model), payload))
    return model
