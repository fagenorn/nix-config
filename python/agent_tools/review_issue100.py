"""Issue-100 retained history: archive envelope, two byte domains and the two-level payload (issue 234; S10, S11).

Archive members come from an explicit directory, bounded and unfollowed, with raw sizes and digests checked
before any decode. Historical and fresh records are separate domains, each under its own policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
from pathlib import Path, PurePosixPath
import re
import subprocess

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import (RECORD_POLICY, RECORD_POLICY_SHA256, GenerationError, _split_diff,
                                       actual_inputs_from_trees)
from agent_tools.review_forecast import (ForecastError, canonical_bytes, edge_facts, read_regular, strict_json,
                                         tree_entry)
from agent_tools.review_git import HistoryError, original_commit, original_range

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
     "candidate_reconciliation": 4, "pending_overlaps": 4, "reconciled": 0})


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


def _rehashed(row: dict) -> bool:
    return row["id"] == telemetry_digest({k: v for k, v in row.items() if k != "id"})


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
    """Closed pins over R3's criteria, each text hashing to its original digest."""
    p, bad = pins, "invalid_pins"
    _require(isinstance(p, Issue100Pins), bad)
    pending, domains = p.pending_paths, (p.historical, p.fresh)
    _require(all(_hex(v) for v in (p.base, p.head, p.live)) and isinstance(p.manifest_name, str)
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
             and all(_count(v) for v in p.expected_counts.values()), bad)
    return p


def _read(directory, relative, size, sha256=None) -> bytes:
    try:
        raw = read_regular(directory, relative, size)
    except (OSError, ForecastError) as exc:
        raise Issue100Error("archive_unreadable") from exc
    _require(len(raw) == size and sha256 in (None, _sha(raw)), "archive_digest_mismatch")
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
        base, head = (original_commit(repo, oid).tree for oid in (pins.base, pins.head))
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
        and isinstance(artifact["path"], str) and PurePosixPath(artifact["path"]).name == pins.manifest_name, bad)
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
        base, head = (original_commit(repo, oid).tree for oid in (pins.base, pins.head))
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


def derive_100(issue_repo: Path, live_repo: Path, archive_dir: Path, pins: Issue100Pins, limits) -> dict:
    """The validated payload: archive and domains verified, then raw parent edges in range order."""
    pins, repo, live_repo = _checked(pins), Path(issue_repo), Path(live_repo)
    _, historical = _verified(Path(archive_dir), repo, pins)
    fresh = fresh_records(repo, pins, limits)
    with _authenticated():
        commits = original_range(repo, pins.base, pins.head)
        original_commit(live_repo, pins.live)  # the live repository holds the same commit
        trees = {name: original_commit(repo, getattr(pins, name)).tree for name in ("base", "live", "head")}
        parent_edges, edges = [], []
        for oid in commits:
            for ordinal, parent in enumerate(original_commit(repo, oid).parents, 1):
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
    validate_100(payload, pins)
    return payload


def _entry(value) -> bool:
    return value is None or (_closed(value, ("mode", "kind", "oid")) and _match("[0-7]{6}", value["mode"])
                             and value["kind"] in ("blob", "tree", "commit") and _hex(value["oid"]))


def _validate_history(payload, pins) -> None:
    """Raw parent edges in range order, ordinals from 1, each parent the base or an earlier range commit."""
    span, commits = payload["range"], payload["range"]["commits"]
    _require(_same({**span, "commits": 0}, {"base": pins.base, "head": pins.head, "live": pins.live, "commits": 0})
             and isinstance(commits, list) and all(_hex(c) for c in commits) and len(set(commits)) == len(commits))
    position = {oid: n for n, oid in enumerate(commits)}
    parent_edges, edges, keys = payload["parent_edges"], payload["edges"], []
    _require(isinstance(parent_edges, list) and isinstance(edges, list) and len(edges) == len(parent_edges))
    for raw, edge in zip(parent_edges, edges):
        _closed(raw, ("parent", "commit", "parent_ordinal"))
        _closed(edge, (*raw, "records"))
        parent, commit, ordinal = raw["parent"], raw["commit"], raw["parent_ordinal"]
        _require(_same(raw, {k: edge[k] for k in raw}) and commit in position and type(ordinal) is int and ordinal > 0
                 and isinstance(edge["records"], list)
                 and (parent == pins.base or position.get(parent, len(commits)) < position[commit]))
        keys.append((position[commit], ordinal))
        for record in edge["records"]:
            _closed(record, ("operation", "path", "old_path", "before", "after", "record_bytes", "record_sha256"))
            operation, path, old, before, after = (record[k] for k in ("operation", "path", "old_path", "before", "after"))
            _require(operation in ("A", "M", "D", "T", "R100") and _text(path) and _text(old)
                     and (operation == "R100") == (path != old) and _entry(before) and _entry(after)
                     and (before is None) == (operation == "A") and (after is None) == (operation == "D")
                     and _count(record["record_bytes"]) and _match("sha256:[0-9a-f]{64}", record["record_sha256"]))
    _require(keys == sorted(set(keys)) and {n for n, _ in keys} == set(range(len(commits)))
             and all(ordinal == 1 or (i and keys[i - 1] == (n, ordinal - 1)) for i, (n, ordinal) in enumerate(keys)))


def _validate_tables(payload, pins) -> list:
    tables = _closed(payload["tables"], ("historical", "fresh"))
    for name, domain, keys in (("historical", pins.historical, ()), ("fresh", pins.fresh, ("path",))):
        table = _closed(tables[name], ("record_table_policy", "records"))
        records = table["records"]
        _require(_same(table["record_table_policy"], _policy(domain)) and isinstance(records, list)
                 and len(records) == domain.records)
        for record in records:
            _closed(record, ("bytes", "sha256", *keys))
            _require(_count(record["bytes"]) and _hex(record["sha256"], 64) and all(_text(record[k]) for k in keys))
        _require(sum(record["bytes"] for record in records) == domain.bytes)
    _require(len({record["path"] for record in records}) == len(records))
    return records


def _validate_contributions(payload, pins, fresh) -> None:
    """A row per fresh record, each label recomputed, each overlap referenced once."""
    overlaps, rows = payload["pending_overlaps"], payload["contributions"]
    _require(isinstance(overlaps, list) and len(overlaps) == len(pins.pending_paths))
    by_id = {}
    for row, path in zip(overlaps, pins.pending_paths):
        _closed(row, ("path", "base_entry", "live_entry", "head_entry", *(f"{a}_{b}_sha256" for a, b in _PAIRS), "id"))
        _require(row["path"] == path and all(_entry(row[f"{name}_entry"]) for name in ("base", "live", "head"))
                 and all(_hex(row[f"{a}_{b}_sha256"], 64) for a, b in _PAIRS) and _rehashed(row))
        by_id[row["id"]] = row
    _require(isinstance(rows, list) and len(rows) == len(fresh))
    referenced = []
    for row, record in zip(rows, fresh):
        _closed(row, ("path", "record_sha256", "head_entry", "live_entry", "edge_refs", "disposition", "pending", "id"))
        path, label = row["path"], row["disposition"]
        _require(path == record["path"] and row["record_sha256"] == record["sha256"]
                 and _entry(row["head_entry"]) and _entry(row["live_entry"])
                 and _same(row["edge_refs"], _refs(payload["edges"], path)) and label in DISPOSITIONS
                 and (label == "historical_process") == (process := path in pins.process_paths)
                 and (label == "integrated") == (not process and _same(row["head_entry"], row["live_entry"]))
                 and (row["pending"] is not None) == (label == "candidate" and path in pins.pending_paths)
                 and _rehashed(row))
        if row["pending"] is not None:
            overlap = by_id.get(row["pending"], {})
            _require(_same([overlap.get(k) for k in ("path", "head_entry", "live_entry")],
                           [path, row["head_entry"], row["live_entry"]]))
            referenced.append(row["pending"])
    _require(sorted(referenced) == sorted(by_id))


def validate_100(payload: dict, pins: Issue100Pins) -> None:
    """Git-free: closed shapes, edge order and coverage, both domains, labels, criteria, and every count
    recomputed from the tables, never trusted (S10)."""
    pins = _checked(pins)
    try:
        _closed(payload, ("schema_version", "kind", "range", "parent_edges", "edges", "contributions",
                          "pending_overlaps", "criteria", "tables", "summary"))
        _require(_same([payload["schema_version"], payload["kind"]], [1, KIND]))
        _validate_history(payload, pins)
        _validate_contributions(payload, pins, _validate_tables(payload, pins))
        _require(_same(payload["criteria"], pins.criteria))
        counts = _counts(payload)
        _require(_same(payload["summary"], counts) and _same(counts, pins.expected_counts))
    except (KeyError, TypeError, AttributeError, ValueError) as exc:
        raise Issue100Error("invalid_payload") from exc
