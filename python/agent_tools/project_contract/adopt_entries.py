"""Adoption's entry-file conversion: hand-written root entry files become the
bootstrap source (ADR-project-contract-019).

A repository's own `AGENTS.md` and `CLAUDE.md` are the projections the platform
generates from `.agents/instructions/bootstrap.md`. When a checkout has a
contract (or a drafted one) and either file holds authored text, adoption moves
that text into the source, writes `CLAUDE.md` as the managed import line alone,
and leaves `AGENTS.md` to its projection regeneration. This module plans that
conversion: which files convert, the text each contributes, the source's final
bytes, the projections the contract must gain, and the links and Claude imports
that would not mean the same thing in the source.

It is imported, never run: no `main` and no argparse. It reads blobs through git
only, never the working tree, because `apply` re-runs the derivation. It imports
`adopt_inspection`, `adopt_links` and `agent_platform`, never the resolver
(D26); the rest is the standard library.
"""

from __future__ import annotations

import posixpath
import re
from typing import NamedTuple

from agent_tools.project_contract import adopt_links, agent_platform
from agent_tools.project_contract.adopt_inspection import (
    BOOTSTRAP_SOURCE,
    ENTRY_FILES,
    ENTRY_PROJECTIONS,
    Candidates,
    Inventory,
    blob_at,
    classify,
    evidence_entry,
    is_agent_path,
    is_secret_path,
    object_hash,
    refuse,
    tree_records,
)
from agent_tools.project_contract.adopt_links import LinkRewrites

REGULAR_MODES = ("100644", "100755")
# A Claude `@path` import: not inside a word or an inline code span.
CLAUDE_IMPORT = re.compile(r"(?<![\w`])@([^\s`]+)")
INLINE_CODE = re.compile(r"`[^`]*`")
GENERATED_PREFIX = agent_platform.GENERATED_HEADER_TEMPLATE.split("{source}")[0]
MANAGED_LINE = agent_platform.MANAGED_IMPORT_TEMPLATE.format(source=BOOTSTRAP_SOURCE)


class EntryConversion(NamedTuple):
    """What the conversion moves: `paths` in block order, the base bytes of
    each (and of the source when tracked) and the authored text per path."""

    paths: tuple[str, ...]
    nested: tuple[str, ...]
    before: dict[str, bytes]
    blocks: tuple[tuple[str, str], ...]
    authored: tuple[tuple[str, str], ...] = ()


NO_CONVERSION = EntryConversion((), (), {}, ())


def authored_entry_text(name: str, text: str) -> str:
    """The text of an entry file that is not the platform's own output."""
    if name.rsplit("/", 1)[-1] == "AGENTS.md":
        return "" if text.startswith(GENERATED_PREFIX) else text
    kept = "".join(line for line in text.splitlines(keepends=True)
                   if line.rstrip("\r\n") != MANAGED_LINE)
    return kept if kept.strip() else ""


def ended(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def decoded(data: bytes, message: str) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise refuse("adopt_failure", "adopt.entry.undecodable", "/evidence",
                     message) from None


def named(row: dict, member: str) -> str | None:
    """A declared projection's `target` or `source` as a normal path, or None
    when it is not a string (the resolver refuses that, never this module)."""
    value = row.get(member)
    return posixpath.normpath(value) if isinstance(value, str) else None


def projection_paths(contract_source: dict) -> set[str]:
    """Every `target` and `source` a declared projection names."""
    rows = declared_rows(contract_source.get("projections"))
    return {path for _, row in rows for member in ("target", "source")
            if (path := named(row, member)) is not None}


def nested_candidates(records: dict[str, tuple[str, str]],
                      declared: set[str]) -> list[str]:
    """The tracked nested entry files that convert (D9), sorted: a regular file
    that no projection names, outside the agent and secret paths, whose
    classification is none or a `retain-product` row that is not product source."""
    chosen = []
    for path, (mode, _) in records.items():
        rule = classify(path)
        if ("/" in path and path.rsplit("/", 1)[-1] in ENTRY_FILES
                and mode in REGULAR_MODES and path not in declared
                and not is_agent_path(path) and not is_secret_path(path)
                and (rule is None or (rule[2] == "retain-product"
                                      and rule[1] != "product-source"))):
            chosen.append(path)
    return sorted(chosen)


def plan_entry_conversion(root, found: Candidates, inventory: Inventory,
                          contract_source: dict | None) -> EntryConversion:
    """The entry files that convert, marked `convert-to-source` in the
    evidence and the groups: the two root files, then every nested one. Nothing
    converts without a contract or a draft."""
    if contract_source is None:
        return NO_CONVERSION
    revision = inventory.base_revision
    records = {path: (mode, oid) for path, mode, oid in tree_records(root, revision)}
    indexed = dict(inventory.tracked)
    source_bytes = blob_at(root, revision, BOOTSTRAP_SOURCE) \
        if BOOTSTRAP_SOURCE in records else None
    seen: list[str] | None = None
    paths, nested, blocks, texts, stale = [], [], [], [], []
    before: dict[str, bytes] = {}
    roots = [name for name in ENTRY_FILES if records.get(name, (None,))[0] in REGULAR_MODES]

    def convert(name: str, data: bytes | None) -> None:
        mark_converted(found, indexed, name, records[name][1])
        if name not in ENTRY_FILES:
            nested.append(name)
        paths.append(name)
        before[name] = data or b""

    for name in (*roots, *nested_candidates(records, projection_paths(contract_source))):
        data = blob_at(root, revision, name)
        if name.rsplit("/", 1)[-1] == "AGENTS.md" and (data or b"").startswith(
                GENERATED_PREFIX.encode("utf-8")):
            # The projection of a source that may not be UTF-8 text. A root
            # one is regenerated; a nested one no projection names is stale.
            if name not in ENTRY_FILES:
                stale.append((name, data))
            continue
        text = decoded(data or b"", "a hand-written entry file is not UTF-8 "
                       "text, so its text cannot move into the bootstrap source")
        authored = authored_entry_text(name, text)
        if not authored:
            continue
        if seen is None:
            source = None if source_bytes is None else decoded(
                source_bytes, "the bootstrap source is not UTF-8 text, so "
                "adopted text cannot be joined to it")
            seen = [] if not source else [ended(source)]
        convert(name, data)
        texts.append((name, authored))
        if ended(authored) not in seen:
            seen.append(ended(authored))
            blocks.append((name, authored))
    if paths or source_bytes is not None:
        for name, data in stale:
            convert(name, data)
    if not paths:
        return NO_CONVERSION
    if source_bytes is not None:
        before[BOOTSTRAP_SOURCE] = source_bytes
    return EntryConversion(tuple(paths), tuple(nested), before, tuple(blocks),
                           tuple(texts))


def mark_converted(found: Candidates, indexed: dict[str, str], name: str,
                   oid: str) -> None:
    """Mark `name` `convert-to-source` in the evidence and the groups."""
    if indexed.get(name) != oid:
        raise refuse("dirty_worktree", "adopt.worktree.dirty", "/evidence",
                     "an entry file is staged differently from the base "
                     "revision, so its authored text cannot be judged")
    if name in ENTRY_FILES:
        found.groups[name]["action"] = "convert-to-source"
        found.groups[name]["target"] = BOOTSTRAP_SOURCE
        for entry in found.entries:
            if entry["path"] == name and entry["provenance"] == "tracked":
                entry["action"] = "convert-to-source"
                entry["target"] = BOOTSTRAP_SOURCE
    else:
        found.entries.append(evidence_entry(
            name, "tracked", "native-projection", "convert-to-source",
            BOOTSTRAP_SOURCE, 1, object_hash(oid), None))
        found.groups[name] = {"action": "convert-to-source",
                              "target": BOOTSTRAP_SOURCE,
                              "members": [(name, oid)]}


def declared_rows(projections: object) -> list[tuple[int, dict]]:
    return [(index, row) for index, row in enumerate(projections)
            if isinstance(row, dict)] if isinstance(projections, list) else []


def check_entry_projections(contract_source: dict) -> None:
    """Refuse a declared projection that would not carry the converted text."""
    rows = declared_rows(contract_source.get("projections"))
    targets = {named(row, "target") for _, row in rows}
    ids = {entry["id"] for entry in ENTRY_PROJECTIONS
           if entry["target"] not in targets}
    for index, row in rows:
        row_id = row.get("id")
        clash = isinstance(row_id, str) and row_id in ids
        for entry in ENTRY_PROJECTIONS:
            if named(row, "target") == entry["target"] and (
                    row.get("kind") != entry["kind"]
                    or named(row, "source") != entry["source"]):
                clash = True
        if clash:
            raise refuse(
                "adopt_failure", "adopt.entry.projection_conflict",
                f"/projections/{index}",
                "a declared projection names an entry file or an entry "
                "projection id with another kind or source, so the converted "
                "text would not reach it")


def missing_entry_projections(projections: list) -> list[dict]:
    """The entry projections no declared row names, as fresh copies."""
    targets = {named(row, "target") for _, row in declared_rows(projections)}
    return [dict(entry) for entry in ENTRY_PROJECTIONS
            if entry["target"] not in targets]


def entry_base_text(conversion: EntryConversion, links: LinkRewrites) -> str | None:
    """The source's text before the blocks: after its link rewrite, else as at base."""
    if BOOTSTRAP_SOURCE in links.files:
        return links.files[BOOTSTRAP_SOURCE].after
    data = conversion.before.get(BOOTSTRAP_SOURCE)
    return None if data is None else data.decode("utf-8")


def entry_source_text(conversion: EntryConversion, base_text: str | None) -> str:
    """The base text, then one block per converted file, one blank line apart."""
    parts = [ended(base_text)] if base_text else []
    parts.extend(ended(f"<!-- adopted from {path} -->\n{text}")
                 for path, text in conversion.blocks)
    return "\n".join(parts)


def entry_source(conversion: EntryConversion, links: LinkRewrites) -> bytes | None:
    """The source's final bytes, or None when nothing converts or they do not change."""
    if not conversion.paths:
        return None
    data = entry_source_text(
        conversion, entry_base_text(conversion, links)).encode()
    return None if data == conversion.before.get(BOOTSTRAP_SOURCE) else data


def claude_imports(text: str) -> list[str]:
    """The relative `@path` imports outside code: they resolve from another directory."""
    found, fenced = [], False
    for line in text.splitlines():
        if line.startswith("```"):
            fenced = not fenced
        elif not fenced:
            found.extend(match.group(1) for match in
                         CLAUDE_IMPORT.finditer(INLINE_CODE.sub("", line))
                         if not match.group(1).startswith(("/", "~")))
    return found


def entry_unrewritable(conversion: EntryConversion,
                       base_text: str | None) -> list[dict]:
    """Links and imports that could not stay correct in the source (D8)."""
    if not conversion.paths:
        return []
    rows = {(BOOTSTRAP_SOURCE, link.target) for link in adopt_links.links(base_text or "")
            if adopt_links.is_relative(link.target)}
    for path, text in conversion.blocks:
        rows.update((path, link.target) for link in adopt_links.links(text)
                    if adopt_links.is_relative(link.target))
    # Every converted `CLAUDE.md`, a block another file's text made redundant
    # included: its imports resolve from `.agents/instructions/` all the same.
    for path, text in conversion.authored:
        if path.rsplit("/", 1)[-1] == "CLAUDE.md":
            rows.update((path, target) for target in claude_imports(text))
    return [{"path": path, "target": target} for path, target in sorted(rows)]


def markdown_write_targets(links: LinkRewrites, conversion: EntryConversion,
                           source: bytes | None) -> set[str]:
    """Every Markdown file the plan writes: the link rewrites, with the source's
    one write replacing its link write when a conversion is planned."""
    if not conversion.paths:
        return set(links.files)
    return ((set(links.files) - {BOOTSTRAP_SOURCE})
            | ({BOOTSTRAP_SOURCE} if source is not None else set())
            | ({"CLAUDE.md"} if "CLAUDE.md" in conversion.paths else set()))
