"""The Task-7 adoption estimate table and the fileless Task-8 effect (issue 234 D4, D17, D18).

A `task7-estimate/v1` row bounds one whole review record of the adoption commit
with no reserve: a move by its exact C-quoted R100 header, maximized over every
same-blob, same-mode source; a write or add by one full delete/add record whose
output sums each `RendererSpec`'s fixed portion and `count * max_encoded_bytes`
per field. Zero specs are the tool closure, bound once if every target runs it.
A write row adds `_write_allowance`, so its bound also covers a multi-hunk record.
Rows keep only what the pins cannot re-derive (D18): a move's old path, class
and rule follow from its root, its output is its input, and `rows_sha256`
digests the rows. The project identity is an `authored-estimate`.

`validate_task7` is Git-free. It proves that a table is the exact rebuild of
its own input facts plus the pins; it cannot prove that those facts are the
pinned tree's facts. Authenticity is `derive_task7` equality against the
pinned tree, which REPLAY's derivation runs before it writes its anchor.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import (PACKING_POLICY, PACKING_POLICY_SHA256, RECORD_POLICY,
                                       GenerationError, actual_inputs_from_trees, git_diff)
from agent_tools.review_forecast import ForecastError, history_commit

MODEL_VERSION = "task7-operation-model/v1"
DIGEST_PLACEHOLDER = "0" * 64  # a plan digest the run computes, charged at full length
PROJECT_ID_FIELD, FRAGMENT_FIELD = "<project_id>", "<12-char fragment>"
NO_NEWLINE = len(b"\n\\ No newline at end of file\n")
FUNCNAME_MAX_BYTES = 80  # Git's function-context truncation width (xdiff `struct func_line`)
CODES = ("unsupported_estimate", "unsupported_composition", "invalid_table", "inventory_mismatch")
MOVE_FIELDS = ("moves.old_path", "moves.new_path")
RULES = {"move": "r100-compatible-maximum/v1", "write": "full-delete-add/v1", "add": "full-add/v1"}
BLOB_MODES = ("100644", "100755", "120000")  # Git's closed set of blob modes
# The signed Task-7 brief's typed targets: path, operation, bounded fields.
TARGETS = (
    (".agents/project.json", "write", ("project_id",)), (".gitignore", "write", ()),
    (".claude/skills.config.json", "write", ()), ("AGENTS.md", "write", ()),
    ("CLAUDE.md", "write", ()), (".agents/runtime/.gitignore", "add", ()),
    (f".agents/knowledge/archive/path-migrations/{DIGEST_PLACEHOLDER}.json", "add",
     ("migration_id", *MOVE_FIELDS)),
    (f".agents/artifacts/evidence/{DIGEST_PLACEHOLDER}.json", "add",
     ("plan_id", "path_migration_map", "base_revision", "sources.before")),
)
TASK8_EFFECT = {"task": 8, "repository_bytes": 0, "state": "unexecuted",
                "acceptance": "post-integration-registration-evidence"}


class EstimateError(Exception):
    """The table cannot be derived, validated or composed; `code` names why."""

    def __init__(self, code: str):
        if code not in CODES:
            raise ValueError(f"unknown estimate code {code!r}")
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RendererSpec:
    target: str
    renderer_path: str
    renderer_blob: str
    fixed_bytes: int
    fixed_lines: int
    fields: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class Task7Pins:
    prerequisite_commit: str
    prerequisite_tree: str
    plan_root_blob: str
    task7_blob: str
    model_version: str
    subject_template: str
    move_roots: tuple[tuple[str, str, str], ...]
    renderers: tuple[RendererSpec, ...]
    project_id_max_bytes: int


def _count(value):
    return type(value) is int and value >= 0


def _hex(value, length):
    return isinstance(value, str) and re.fullmatch("[0-9a-f]{%d}" % length, value) is not None


def _quoted(text):
    """Byte length of `text` as Git writes a path under `core.quotePath=true`."""
    raw = text.encode("utf-8")
    if not any(b < 32 or b in (34, 92) or b >= 127 for b in raw):
        return len(raw)
    return 2 + sum(2 if b in (7, 8, 9, 10, 11, 12, 13, 34, 92) else 4 if b < 32 or b >= 127 else 1
                   for b in raw)


def _r100(old, new):
    return (len("diff --git  \nsimilarity index 100%\nrename from \nrename to \n")
            + _quoted("a/" + old) + _quoted("b/" + new) + _quoted(old) + _quoted(new))


def _record(path, source, output, hexlen):
    """One full delete/add record of `source` (None for an add) replaced by `output`."""
    old, new = _quoted("a/" + path), _quoted("b/" + path)
    # `@@ -1,N +1,M @@`: `-0,0` and a bare `1` are never longer than `1,N`.
    hunk = len("@@ -1, +1, @@\n") + len(str(source["lines"] if source else 0)) + len(str(output["lines"]))
    if source is None:
        header = len("diff --git  \nnew file mode 100644\nindex ..\n--- /dev/null\n+++ \n") + old + 2 * new
        removal = 0
    else:
        header = len("diff --git  \nindex .. \n--- \n+++ \n") + len(source["mode"]) + 2 * (old + new)
        removal = source["bytes"] + source["lines"] + NO_NEWLINE
    return header + 2 * hexlen + hunk + removal + output["bytes"] + output["lines"] + NO_NEWLINE


def _hunk_header_max(width):
    """The longest hunk header whose four numbers have at most `width` digits."""
    return len("@@ -, +, @@ ") + 4 * width + FUNCNAME_MAX_BYTES + len("\n")


def _write_allowance(source, output):
    """What a write record may exceed `_record` by, for any hunking at any admitted context.

    CORE renders records under `--inter-hunk-context=0` at each packing-policy
    context `c`, so two hunks stay separate only across more than `2c` unchanged
    lines. Of `n = min(input, output)` lines at most `n` are unchanged, so at most
    `n // (2c + 1)` hunks follow the first. The full delete/add record charges
    every unchanged line at least 2 bytes more than any hunk shows it, and every
    hunk header is at most `_hunk_header_max`, which includes Git's truncated
    function-context text. The first header may outgrow the one `_record` charges,
    and each extra header costs at most its maximum less the `2 * (2c + 1)` bytes
    its separating lines save.
    """
    longest = _hunk_header_max(len(str(max(source["lines"], output["lines"]) + 1)))
    first = len("@@ -1, +1, @@\n") + len(str(source["lines"])) + len(str(output["lines"]))
    lines = min(source["lines"], output["lines"])
    contexts = (PACKING_POLICY["initial"]["context_lines"],
                *(choice["context_lines"] for choice in PACKING_POLICY["adaptive"]))
    return (longest - first) + max((lines // (2 * c + 1)) * max(0, longest - 2 * (2 * c + 1))
                                   for c in contexts)


def _encoded(path):
    # Inside a rendered JSON string (`ensure_ascii=False`).
    return len(json.dumps(path, ensure_ascii=False)[1:-1].encode("utf-8"))


def _pins(pins):
    """Check every pin's type and closed vocabulary; return the object-id length."""
    if not isinstance(pins, Task7Pins):
        raise EstimateError("unsupported_estimate")
    hexlen = len(pins.prerequisite_commit) if isinstance(pins.prerequisite_commit, str) else 0
    template, roots = pins.subject_template, pins.move_roots
    if (hexlen not in (40, 64) or not all(_hex(getattr(pins, name), hexlen) for name in (
                "prerequisite_commit", "prerequisite_tree", "plan_root_blob", "task7_blob"))
            or pins.model_version != MODEL_VERSION or not isinstance(template, str)
            or template.count(PROJECT_ID_FIELD) != 1 or template.count(FRAGMENT_FIELD) != 1
            or not _count(pins.project_id_max_bytes) or not pins.project_id_max_bytes
            or not isinstance(pins.renderers, tuple) or not isinstance(roots, tuple) or not roots
            or any(not isinstance(root, tuple) or len(root) != 3 or root[2] not in ("spec", "plan", "decision")
                   or not all(isinstance(part, str) and part for part in root) for root in roots)):
        raise EstimateError("unsupported_estimate")
    # Equal or path-prefix-overlapping roots on either side would give a path two roots.
    for side in (0, 1):
        prefixes = [root[side] for root in roots]
        if any(n != m and (a == b or b.startswith(a + "/"))
               for n, a in enumerate(prefixes) for m, b in enumerate(prefixes)):
            raise EstimateError("unsupported_estimate")
    return hexlen


def _renderers(pins, hexlen):
    """Each target's contributing renderer facts, the tool closure and the renderer identities."""
    groups, closure, identities = {}, {}, {}
    for spec in pins.renderers:
        if (not isinstance(spec, RendererSpec) or not isinstance(spec.renderer_path, str)
                or not _hex(spec.renderer_blob, hexlen) or not isinstance(spec.fields, tuple)
                or not _count(spec.fixed_bytes) or not _count(spec.fixed_lines)
                or identities.setdefault(spec.renderer_path, spec.renderer_blob) != spec.renderer_blob):
            raise EstimateError("unsupported_estimate")
        fields = []
        for field in spec.fields:
            if (not isinstance(field, tuple) or len(field) != 3 or not isinstance(field[0], str)
                    or field[0].count(":") != 1 or not _count(field[1]) or not _count(field[2])):
                raise EstimateError("unsupported_estimate")
            source, member = field[0].split(":")
            if not source or not member or member == "project_id" and field[2] != pins.project_id_max_bytes:
                raise EstimateError("unsupported_estimate")
            fields.append({"name": member, "source": source, "count": field[1], "max_encoded_bytes": field[2]})
        facts = {"path": spec.renderer_path, "fixed_bytes": spec.fixed_bytes, "fixed_lines": spec.fixed_lines}
        if spec.fixed_bytes or spec.fixed_lines or fields:
            groups.setdefault(spec.target, []).append({**facts, "fields": fields})
        else:
            closure.setdefault(spec.target, set()).add(spec.renderer_path)
    targets = {target for target, _, _ in TARGETS}
    shared = {frozenset(closure.get(target, ())) for target in targets}
    if set(groups) - targets or set(closure) - targets or len(shared) != 1:
        raise EstimateError("unsupported_estimate")
    return groups, sorted(shared.pop()), [{"path": p, "blob": blob} for p, blob in sorted(identities.items())]


def _moved(pins, path, side):
    """`path` through its move root's old (0) or new (1) prefix, and that root's class.

    `_pins` refuses overlapping roots, so at most one root matches on each side.
    """
    for root in pins.move_roots:
        if path.startswith(root[side] + "/"):
            return root[1 - side] + path[len(root[side]):], root[2]
    return None, None


def _assemble(pins, moves, inputs):
    """The complete table from move input facts, write input facts and the pins."""
    hexlen = _pins(pins)
    groups, closure, renderers = _renderers(pins, hexlen)
    mapped = {}
    for old, source in moves.items():
        new, kind = _moved(pins, old, 0)
        if new is None or new in mapped or new in {target for target, _, _ in TARGETS}:
            raise EstimateError("inventory_mismatch")
        mapped[new] = (old, kind, source)
    if not {pins.plan_root_blob, pins.task7_blob} <= {source["blob"] for source in moves.values()}:
        raise EstimateError("inventory_mismatch")
    widest = dict(zip(MOVE_FIELDS, (max(map(_encoded, paths), default=0) for paths in (moves, mapped))))
    for field in (f for specs in groups.values() for spec in specs for f in spec["fields"]
                  if f["name"] in MOVE_FIELDS):
        if field["count"] != len(moves):
            raise EstimateError("inventory_mismatch")
        if field["max_encoded_bytes"] < widest[field["name"]]:
            raise EstimateError("unsupported_estimate")
    compatible = {}
    for old, source in moves.items():
        compatible.setdefault((source["blob"], source["mode"]), []).append(old)
    rows = [{"operation": "move", "new_path": new, "input": source,
             "record_bytes": max(_r100(other, new) for other in compatible[source["blob"], source["mode"]])}
            for new, (old, kind, source) in mapped.items()]
    for target, operation, members in TARGETS:
        specs = groups.get(target)
        if not specs or not set(members) <= {f["name"] for spec in specs for f in spec["fields"]}:
            raise EstimateError("unsupported_estimate")
        source = inputs.get(target)
        if (operation == "write") != (source is not None):
            raise EstimateError("inventory_mismatch")
        output = {"bytes": sum(spec["fixed_bytes"] + sum(f["count"] * f["max_encoded_bytes"]
                                                         for f in spec["fields"]) for spec in specs),
                  "lines": sum(spec["fixed_lines"] for spec in specs)}
        record = _record(target, source, output, hexlen) + (source and _write_allowance(source, output) or 0)
        rows.append({"operation": operation, "new_path": target, "input": source, "facts": {"renderers": specs},
                     "output": output, "record_bytes": record})
    rows.sort(key=lambda row: row["new_path"])
    kinds = [kind for _, kind, _ in mapped.values()] + [operation for _, operation, _ in TARGETS]
    subject = (len(pins.subject_template.encode("utf-8")) - len(PROJECT_ID_FIELD) - len(FRAGMENT_FIELD)
               + pins.project_id_max_bytes + 12)
    return {
        "schema_version": 1, "kind": "task7-estimate",
        "identities": {
            "record_policy_sha256": telemetry_digest(RECORD_POLICY), "rules": dict(RULES),
            "packing_policy_sha256": PACKING_POLICY_SHA256, "model_version": pins.model_version,
            "prerequisite_commit": pins.prerequisite_commit, "prerequisite_tree": pins.prerequisite_tree,
            "plan_root_blob": pins.plan_root_blob, "task7_blob": pins.task7_blob, "tool_closure": closure,
            "move_roots": [list(root) for root in pins.move_roots], "renderers": renderers,
            "project_identity": {"kind": "authored-estimate", "max_encoded_bytes": pins.project_id_max_bytes}},
        "subject": {"template": pins.subject_template, "max_bytes": subject},
        "rows": rows, "rows_sha256": telemetry_digest(rows),
        "counts": {"paths": len(rows), "moves": len(moves), "specs": kinds.count("spec"),
                   "plans": kinds.count("plan"), "decisions": kinds.count("decision"),
                   "rewrites": kinds.count("write"), "additions": kinds.count("add")},
        "historical_scope": {"tasks": [7, 8], "repository_commits": 1,
                             "operational_effects": [dict(TASK8_EFFECT)]},
        "projection_estimate": {
            "paths": len(rows), "record_bytes": sum(row["record_bytes"] for row in rows),
            "added_lines": sum(row["output"]["lines"] for row in rows if "output" in row),
            "deleted_lines": sum(row["input"]["lines"] for row in rows if row["operation"] == "write"),
            "commit_subject_bytes": [subject]},
        "observed_actual": None,
    }


def _git(repo, *args, code, data=None, env=None):
    try:
        return subprocess.run(["git", "--no-replace-objects", "-C", str(repo), *args], input=data,
                              env=dict(os.environ, GIT_NO_REPLACE_OBJECTS="1", **(env or {})),
                              check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise EstimateError(code) from exc


def _entries(repo, tree, code):
    """Each path of `tree` as `(mode, kind, oid)`."""
    entries = {}
    for row in _git(repo, "ls-tree", "-r", "-z", "--full-tree", tree, code=code).split(b"\0")[:-1]:
        metadata, _, path = row.partition(b"\t")
        try:
            entries[path.decode("utf-8")] = tuple(metadata.decode("ascii").split())
        except UnicodeDecodeError as exc:
            raise EstimateError(code) from exc
    return entries


def _blobs(repo, oids, hexlen):
    ordered = sorted(oids)
    raw = _git(repo, "cat-file", "--batch", code="inventory_mismatch", data="\n".join(ordered).encode() + b"\n")
    contents, position = {}, 0
    for oid in ordered:
        end = raw.find(b"\n", position)
        header = raw[position:end].split()
        if len(header) != 3 or header[:2] != [oid.encode("ascii"), b"blob"] or not header[2].isdigit():
            raise EstimateError("inventory_mismatch")
        size = int(header[2])
        data = raw[end + 1:end + 1 + size]
        digest = hashlib.new("sha1" if hexlen == 40 else "sha256", b"blob %d\0" % size + data)
        if len(data) != size or digest.hexdigest() != oid:
            raise EstimateError("inventory_mismatch")
        contents[oid], position = data, end + 2 + size
    return contents


def _facts(entry, data):
    lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
    return {"blob": entry[2], "mode": entry[0], "bytes": len(data), "lines": lines}


def derive_task7(repo: Path, pins: Task7Pins) -> dict:
    """The `task7-estimate/v1` table relative to `pins.prerequisite_tree`."""
    hexlen = _pins(pins)
    _renderers(pins, hexlen)
    try:
        tree = history_commit(repo, pins.prerequisite_commit).tree
    except ForecastError as exc:
        raise EstimateError("inventory_mismatch") from exc
    if tree != pins.prerequisite_tree:
        raise EstimateError("inventory_mismatch")
    entries = _entries(repo, tree, "inventory_mismatch")
    if any(entries.get(spec.renderer_path, ())[1:] != ("blob", spec.renderer_blob) for spec in pins.renderers):
        raise EstimateError("unsupported_estimate")
    moving = {path: (entry, new) for path, entry in entries.items()
              for new in (_moved(pins, path, 0)[0],) if new is not None}
    if any(entry[1] != "blob" for entry, _ in moving.values()):
        raise EstimateError("unsupported_estimate")
    if any(new in entries for _, new in moving.values()):
        raise EstimateError("inventory_mismatch")
    targets = {target: entries.get(target) for target, _, _ in TARGETS}
    if any((targets[target] is not None) != (operation == "write")
           or (targets[target] or ("", "blob"))[1] != "blob" for target, operation, _ in TARGETS):
        raise EstimateError("inventory_mismatch")
    written = [entry for entry in targets.values() if entry]
    contents = _blobs(repo, {entry[2] for entry in (*(e for e, _ in moving.values()), *written)}, hexlen)
    if any(b"\0" in contents[entry[2]] for entry in written):
        raise EstimateError("unsupported_estimate")
    return _assemble(pins, {path: _facts(entry, contents[entry[2]]) for path, (entry, _) in moving.items()},
                     {target: entry and _facts(entry, contents[entry[2]]) for target, entry in targets.items()})


def _plain(value):
    """Admit only JSON objects, arrays, strings, non-Boolean ints and null."""
    if isinstance(value, (dict, list)):
        if isinstance(value, dict) and not all(isinstance(key, str) for key in value):
            raise EstimateError("invalid_table")
        for item in value.values() if isinstance(value, dict) else value:
            _plain(item)
    elif not (value is None or isinstance(value, str) or type(value) is int):
        raise EstimateError("invalid_table")


def _source(value, hexlen):
    if (not isinstance(value, dict) or set(value) != {"blob", "mode", "bytes", "lines"}
            or not _hex(value["blob"], hexlen) or not isinstance(value["mode"], str)
            or value["mode"] not in BLOB_MODES
            or not _count(value["bytes"]) or not _count(value["lines"])):
        raise EstimateError("invalid_table")
    return value


def validate_task7(table: dict, pins: Task7Pins) -> None:
    """Refuse a table that differs from its Git-free rebuild from its own input facts.

    A bad pin set is `unsupported_estimate`, as from `derive_task7`; every table
    fault after that is `invalid_table`. Each member is type-checked before it is
    used as a key, an index or a set member.
    """
    hexlen = _pins(pins)
    _renderers(pins, hexlen)
    _plain(table)  # Only input facts are read; equality closes every shape.
    if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
        raise EstimateError("invalid_table")
    moves, inputs = {}, {}
    for row in table["rows"]:
        if not isinstance(row, dict):
            raise EstimateError("invalid_table")
        operation, key, source = row.get("operation"), row.get("new_path"), row.get("input")
        if not isinstance(operation, str) or operation not in RULES or not isinstance(key, str):
            raise EstimateError("invalid_table")
        move = operation == "move"
        key = _moved(pins, key, 1)[0] if move else key
        if key is None or key in (moves if move else inputs):
            raise EstimateError("invalid_table")
        (moves if move else inputs)[key] = None if source is None and not move else _source(source, hexlen)
    try:
        expected = _assemble(pins, moves, inputs)
    except EstimateError as exc:
        raise EstimateError("invalid_table") from exc
    if table != expected:
        raise EstimateError("invalid_table")


def _numstat(scratch, base_tree, tree):
    """Each changed path's added and deleted lines; a binary (`-`) count is 0."""
    fields, counts = git_diff(scratch, base_tree, tree, "--numstat", "-z").split(b"\0"), {}
    if fields.pop() != b"":
        raise EstimateError("unsupported_composition")
    fields = iter(fields)
    for row in fields:
        parts = row.split(b"\t", 2)
        if len(parts) != 3 or not all(part == b"-" or part.isdigit() for part in parts[:2]):
            raise EstimateError("unsupported_composition")
        path = parts[2] or (next(fields, None), next(fields, None))[1]  # a rename: old, then new
        if not path:
            raise EstimateError("unsupported_composition")
        counts[path.decode("utf-8")] = tuple(0 if part == b"-" else int(part) for part in parts[:2])
    return counts


def _measure(scratch, base_tree, tree, limits):
    """Each record's size, with its line counts from numstat over the same trees."""
    item = next(actual_inputs_from_trees(scratch, base_tree, tree, base=base_tree, head=tree,
                                         commits=(), package_name="review.json", limits=limits))
    counts, measured = _numstat(scratch, base_tree, tree), {}
    for record in item.records:
        if record.path not in counts:
            raise EstimateError("unsupported_composition")
        measured[record.path] = (record.source_bytes, *counts[record.path])
    return measured


def _composed_trees(repo, scratch, table, pins, base_tree, final_tree):
    """The final tree with every move relocated, and the base tree without the targets."""
    code = "unsupported_composition"
    _git(scratch.parent, "init", "-q", scratch.name, code=code)
    objects = _git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects", code=code)
    (scratch / ".git/objects/info/alternates").write_bytes(objects.strip() + b"\n")
    final, base = (_entries(scratch, tree, code) for tree in (final_tree, base_tree))
    zero = "0" * len(final_tree)
    relocate, remove = [], []
    for row in table["rows"]:
        path, source = row["new_path"], row["input"]
        if row["operation"] == "move":
            old = _moved(pins, path, 1)[0]
            if final.get(old) != (source["mode"], "blob", source["blob"]) or path in final:
                raise EstimateError(code)
            relocate += [f"0 {zero}\t{old}", f"{source['mode']} {source['blob']}\t{path}"]
            continue
        if any(entries.get(path, ("", "blob"))[1] != "blob" for entries in (final, base)):
            raise EstimateError(code)
        if path in base:
            remove.append(f"0 {zero}\t{path}")
    trees = []
    for name, tree, changes in (("composed", final_tree, relocate), ("removed", base_tree, remove)):
        env = {"GIT_INDEX_FILE": str(scratch / ".git" / f"{name}-index")}
        _git(scratch, "read-tree", tree, code=code, env=env)
        _git(scratch, "update-index", "-z", "--index-info", code=code, env=env,
             data="".join(change + "\0" for change in changes).encode("utf-8"))
        trees.append(_git(scratch, "write-tree", code=code, env=env).decode().strip())
    return trees[0], trees[1]


def compose(repo: Path, table: dict, pins: Task7Pins, *, base_tree: str, final_tree: str,
            limits) -> tuple[dict, ...]:
    """Every record of `base_tree` against `final_tree` plus the table, path-sorted.

    A record the composed tree already holds is measured. A target takes the
    larger of its measured record and its bound: the measured removal of its base
    content plus the add bound, with `_write_allowance` when the base holds it.
    """
    validate_task7(table, pins)
    try:  # CORE's routing guard, before any source or scratch write.
        history_commit(repo, pins.prerequisite_commit)
    except ForecastError as exc:
        raise EstimateError("unsupported_composition") from exc
    targets = {row["new_path"]: row for row in table["rows"] if row["operation"] != "move"}
    try:
        with tempfile.TemporaryDirectory(prefix="review-task7-") as raw:
            scratch = Path(raw) / "repo"
            composed, removed = _composed_trees(repo, scratch, table, pins, base_tree, final_tree)
            status = git_diff(scratch, base_tree, composed, "--name-status", "-z").split(b"\0")[:-1]
            records = _measure(scratch, base_tree, composed, limits)
            removals = _measure(scratch, base_tree, removed, limits)
    except (GenerationError, OSError, UnicodeError) as exc:
        raise EstimateError("unsupported_composition") from exc
    fields = iter(status)
    for operation in fields:
        paths = [next(fields, None) for _ in range(2 if operation == b"R100" else 1)]
        # A rename into or out of a target would hide the other side's record.
        if (operation not in (b"A", b"M", b"D", b"T", b"R100") or None in paths
                or (len(paths) == 2 and any(p.decode("utf-8") in targets for p in paths))):
            raise EstimateError("unsupported_composition")
    if base_tree == pins.prerequisite_tree and any(
            records.get(row["new_path"], (row["record_bytes"] + 1,))[0] > row["record_bytes"]
            for row in table["rows"] if row["operation"] == "move"):
        raise EstimateError("unsupported_composition")
    for path, row in targets.items():  # max(base removal + add bound, observed); moves relocate exactly
        removal, observed = removals.get(path, (0, 0, 0)), records.get(path, (0, 0, 0))
        bound = removal[0] + _record(path, None, row["output"], len(pins.prerequisite_commit))
        if path in removals:  # a base-to-output write may split into many hunks (S19)
            bound += _write_allowance({"lines": removal[2]}, row["output"])
        records[path] = (max(bound, observed[0]), max(row["output"]["lines"], observed[1]),
                         max(removal[2], observed[2]))
    return tuple({"path": path, "record_bytes": size, "added_lines": added, "deleted_lines": deleted}
                 for path, (size, added, deleted) in sorted(records.items()))


_SCRIPTS = "home/common/agent-skills/scripts/"
_PLANNING = (_SCRIPTS + "adopt_planning.py", "bcdc442f43204e81cac3dbef8b28a007de98681c")
_INSPECTION = (_SCRIPTS + "adopt_inspection.py", "9fa03acab904616bcc33a5a7af99659782661e24")
_RESOLVER = (_SCRIPTS + "resolve-project.py", "f2dc141dbee07429b50ef52b67fc20207faa286d")
# The rest of the pinned tool, which `adopt-project` needs staged: no bytes of its own.
_CLOSURE = ((_SCRIPTS + "adopt-project.py", "21ece399359ee60ffa72847dbf228a057e0bc88e"),
            (_SCRIPTS + "adopt_apply.py", "949cd46d1fd476077ddcc0bea6e38ed06ba091e9"),
            (_SCRIPTS + "adopt_verify.py", "e88b7f08ad873679e37f2419d42138e4367fe9dc"),
            (_SCRIPTS + "agent_platform.py", "098d13ec98b4ae006de223613078de2d5606b79a"),
            ("home/common/agent-skills/platform-manifest.json", "dd912a0180f8aff8309e699dadf983f2bf16e0a9"))
PROJECT_ID_MAX_BYTES = 140  # authored estimate: a GitHub owner (39) + "/" + repository (100)
_BOOK = "bookkeeping_operations:"
# Fixed portions: the pinned renderers' output over the pinned tree less every field.
_PRIMARY = (
    (_PLANNING, 3074, 153, (("amended_contract:project_id", 1, PROJECT_ID_MAX_BYTES),)),
    (_PLANNING, 405, 15, ()), (_PLANNING, 212, 9, ()), (_RESOLVER, 1403, 22, ()),
    (_RESOLVER, 16566, 67, ()), (_INSPECTION, 2, 1, ()),
    (_PLANNING, 9312, 666, ((_BOOK + "migration_id", 1, 64), (_BOOK + "moves.old_path", 165, 103),
                            (_BOOK + "moves.new_path", 165, 113))),
    (_PLANNING, 2425, 122, ((_BOOK + "plan_id", 1, 64), (_BOOK + "path_migration_map", 1, 64),
                            (_BOOK + "base_revision", 1, 40), (_BOOK + "sources.before", 15, 64))),
)
TASK7_PINS = Task7Pins(
    prerequisite_commit="fe85677c8bd26c808ac69c2ee21b17ff6e262923",
    prerequisite_tree="0f0d10d60e1e4a85471051b1d454ae274856fdce",
    plan_root_blob="8294252bb15684d9bf6054d7faf84ac98a376923",
    task7_blob="c8c622dd6389dc844a7fc638c305d2ab71223cb8",
    model_version=MODEL_VERSION,
    subject_template=f"chore(adopt): adopt {PROJECT_ID_FIELD} at plan {FRAGMENT_FIELD}",
    move_roots=((".claude/specs", ".agents/artifacts/specs", "spec"),
                (".claude/plans", ".agents/artifacts/plans", "plan"),
                (".out-of-scope", ".agents/knowledge/rejections", "decision")),
    renderers=(*(RendererSpec(target, path, blob, size, lines, fields)
                 for (target, _, _), ((path, blob), size, lines, fields) in zip(TARGETS, _PRIMARY)),
               *(RendererSpec(target, path, blob, 0, 0, ())
                 for target, _, _ in TARGETS for path, blob in _CLOSURE)),
    project_id_max_bytes=PROJECT_ID_MAX_BYTES,
)
