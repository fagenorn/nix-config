"""Deriving an adoption plan from a bounded inspection.

Everything between the inventory and the document: the project's identity and
its open questions (D35), the `.gitignore` amendment, the ordered typed
operations, the seven routing rules (D10), the ready gates, and the
content-addressed `plan_id` (D15).

Every closed set, hash and path predicate it works over comes from
`adopt_inspection`, so the two halves cannot disagree about the vocabulary.
Like that module it is imported, never run, imports no resolver (D26), and is
a module of the `agent_tools` package.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path, PurePosixPath

from agent_tools import (adopt_links, adopt_references, agent_platform,
                         release_profile)
from agent_tools.adopt_inspection import (
    ADOPT_SCHEMA_VERSION,
    APPROVAL_CLASSES,
    ARCHIVE_ADOPTED_DIR,
    AdoptError,
    CANDIDATE_BASIS,
    CONTRACT_FILENAME,
    Candidates,
    EVIDENCE_RECORD_DIR,
    GITIGNORE,
    Inventory,
    LEGACY_BINDING_CONFIGS,
    LEGACY_BINDING_KEYS,
    MIGRATION_MAP_DIR,
    NOTES,
    OPERATION_KINDS,
    PATH_REFERENCE_BASIS,
    QUESTION_IDS,
    READY_GATES,
    RUNTIME_IGNORE_PATTERN,
    RUNTIME_SENTINEL,
    RUNTIME_SENTINEL_BYTES,
    approval_class_for,
    authored_bytes,
    candidate_answer,
    canonical_json,
    contained_path,
    document_bytes,
    gate_entry,
    git_or_fail,
    is_evidence_record_path,
    is_secret_path,
    object_hash,
    plan_state_is_terminal,
    question_impact,
    question_recommendation,
    read_bytes_bounded,
    refuse,
    sha256_hash,
)
from agent_tools.adopt_links import LinkRewrites
from agent_tools.adopt_references import References
from agent_tools.release_bridge import project_legacy_deploy

# --------------------------------------------------------------------------
# Project identity (D35)
# --------------------------------------------------------------------------


def normalize_remote_url(url: str) -> str | None:
    """`owner/repo` for the two documented remote spellings, else None.

    A URL matching neither form is deliberately not normalized: guessing an
    identity from an unrecognised spelling is exactly the inference the
    contract forbids, and the caller turns None into an open question.
    """
    value = url.strip()
    if not value:
        return None
    if value.endswith(".git"):
        value = value[:-len(".git")]
    if value.startswith("git@"):
        _, separator, suffix = value.partition(":")
        if not separator or not suffix:
            return None
        segments = [part for part in suffix.split("/") if part]
        return "/".join(segments[-2:]) if len(segments) >= 2 else None
    if "://" in value:
        _, _, rest = value.partition("://")
        segments = [part for part in rest.split("/") if part]
        # host plus owner plus repo at the very least.
        return "/".join(segments[-2:]) if len(segments) >= 3 else None
    return None


def remote_urls(root: Path) -> list[str]:
    """The distinct fetch URLs of every configured remote, by remote name."""
    out = git_or_fail(root, "remote", "-v")
    urls: dict[str, str] = {}
    for line in out.decode("utf-8", "surrogateescape").splitlines():
        fields = line.split()
        if len(fields) >= 2:
            urls.setdefault(fields[0], fields[1])
    return [urls[name] for name in sorted(urls)]


def registry_collision(project_id: str, root: Path) -> bool:
    """Whether the fleet already holds this id at a different root (D35)."""
    try:
        entries = agent_platform.read_registry()
    except agent_platform.PlatformManifestError as error:
        raise AdoptError("adopt_failure", "adopt.registry.invalid",
                         error.violations) from None
    for entry in entries:
        if (entry["project_id"] == project_id
                and Path(entry["root"]).resolve() != root):
            return True
    return False


def derive_identity(root: Path, contract_id: str | None) -> tuple[
        str | None, list[dict], list[dict]]:
    """`(project_id, recommended, open)` for this repository.

    The contract answers whenever it can; otherwise exactly one remote yields a
    recommendation ratified by approving the ready plan id (D16), and every
    other shape yields exactly one open question that keeps the plan `draft`.
    """
    if contract_id is not None:
        return contract_id, [], []
    question_id = QUESTION_IDS[0]
    urls = remote_urls(root)
    value = normalize_remote_url(urls[0]) if len(urls) == 1 else None
    basis = f"derived from {len(urls)} configured git remote(s)"
    if value is not None and not registry_collision(value, root):
        return value, [{"id": question_id, "value": value, "basis": basis}], []
    return None, [], [{
        "id": question_id,
        "value": value,
        "basis": basis,
        "impact": question_impact(question_id),
        "recommendation": question_recommendation(question_id),
    }]



def candidate_questions(found: Candidates) -> list[dict]:
    """One open `candidate-class` question per undecided candidate (#340).

    Every prose member is fixed and never names the candidate: the entry's
    `subject` does, so the question is stable across plans of one tree.
    """
    return sorted(
        ({"id": "candidate-class",
          "subject": entry["path"],
          "value": candidate_answer(entry["provenance"], entry["path"],
                                    entry["path"] not in found.uncontained),
          "basis": CANDIDATE_BASIS,
          "impact": question_impact("candidate-class"),
          "recommendation": question_recommendation("candidate-class")}
         for entry in found.entries if entry["action"] == "needs-decision"),
        key=lambda entry: entry["subject"])

def reference_questions(references: References,
                        answers: dict[str, str]) -> list[dict]:
    """One open `path-reference` question per unanswered occurrence (#350).

    In occurrence order. Every prose member is fixed and never names the file
    or the literal: the entry's `subject` does, so the question is stable
    across plans of one tree. The entry carries no `value`, because the
    answer is the operator's choice among the occurrence's own `answers`.
    """
    return [{"id": "path-reference",
             "subject": occurrence.subject,
             "answers": list(occurrence.answers),
             "basis": PATH_REFERENCE_BASIS,
             "impact": question_impact("path-reference"),
             "recommendation": question_recommendation("path-reference")}
            for occurrence in references.occurrences
            if occurrence.subject not in answers]


def reference_answers(answered: list[dict]) -> dict[str, str]:
    """`subject -> value` of the settled `path-reference` answers."""
    return {answer["subject"]: answer["value"] for answer in answered
            if answer["id"] == "path-reference"}


def apply_answers(root: Path, found: Candidates, inventory: Inventory,
                  answers: list[dict],
                  excluded: set[str]) -> tuple[list[dict], References]:
    """Settle the answered questions; return the answers, sorted, and the
    references the settled moves leave.

    Each answer is `{"id", "subject", "value"}`, all strings, and answers a
    `candidate-class` or a `path-reference` question. They are validated in
    order of `(id, subject, value)`, refusing on the first violation: an id
    other than those two, a question answered twice and then, for a
    `candidate-class`, a subject that is not the path of a `needs-decision`
    entry and a value other than the one that candidate's open question
    offers or, for a `path-reference`, a subject that is no occurrence of this
    inspection and a value that occurrence does not offer. Nothing in `found`
    is mutated until every answer has validated, so a refusal changes nothing.

    The references are derived once, from the base revision's tracked text
    with `excluded` skipped, over the moves the answers settle (D12): at the
    first `path-reference` answer, over `found.moves` plus the archive
    destination of every `archive-history` answer validated before it, which
    is every one of them because `candidate-class` sorts first; with no such
    answer, after the candidate mutation below, over `found.moves`. The two
    are the same moves, so the answers' order on the command line changes
    nothing.

    A valid `candidate-class` answer sets the entry's action to the value and
    its note to the answered note, leaving it `unclassified`. Archiving also
    gives it its archive destination, registers it as a one-member group and
    records the move; retaining adds nothing (D4). The answers, sorted by
    `(id, subject)`, enter the plan id unchanged (D5, D15), and are returned
    with the derived `References`.
    """
    pointer = "/decisions/answered"
    entries = {entry["path"]: entry for entry in found.entries
               if entry["action"] == "needs-decision"}
    seen: set[tuple[str, str]] = set()
    moves = list(found.moves)
    references: References | None = None
    for answer in sorted(answers, key=lambda a: (a["id"], a["subject"],
                                                 a["value"])):
        question = answer["id"]
        if question not in ("candidate-class", "path-reference"):
            raise refuse("adopt_failure", "adopt.decisions.invalid_answer",
                         pointer, "only a candidate-class or path-reference "
                         "question can be answered")
        if (question, answer["subject"]) in seen:
            raise refuse("adopt_failure", "adopt.decisions.invalid_answer",
                         pointer, "a candidate is answered more than once"
                         if question == "candidate-class" else
                         "a path reference is answered more than once")
        seen.add((question, answer["subject"]))
        if question == "path-reference":
            if references is None:
                references = adopt_references.derive_references(
                    root, inventory.base_revision, moves, excluded)
            occurrence = next(
                (o for o in references.occurrences
                 if o.subject == answer["subject"]), None)
            if occurrence is None:
                raise refuse("adopt_failure",
                             "adopt.decisions.unmatched_answer", pointer,
                             "the answered subject is not a path reference "
                             "of this inspection")
            if answer["value"] not in occurrence.answers:
                raise refuse("adopt_failure",
                             "adopt.decisions.invalid_answer", pointer,
                             "the answer is not one this path reference's "
                             "open question offers")
            continue
        entry = entries.get(answer["subject"])
        if entry is None:
            raise refuse("adopt_failure", "adopt.decisions.unmatched_answer",
                         pointer, "the answered subject is not an undecided "
                         "candidate of this inspection")
        if answer["value"] != candidate_answer(
                entry["provenance"], entry["path"],
                entry["path"] not in found.uncontained):
            raise refuse("adopt_failure", "adopt.decisions.invalid_answer",
                         pointer, "the answer is not the one this "
                         "candidate's open question offers")
        if answer["value"] == "archive-history":
            moves.append((answer["subject"],
                          f"{ARCHIVE_ADOPTED_DIR}/{answer['subject']}"))

    tracked = dict(inventory.tracked)
    settled = sorted(answers, key=lambda a: (a["id"], a["subject"]))
    for answer in settled:
        if answer["id"] != "candidate-class":
            continue
        path, value = answer["subject"], answer["value"]
        entry = entries[path]
        entry["action"] = value
        entry["note"] = NOTES["answered"]
        if value == "archive-history":
            target = f"{ARCHIVE_ADOPTED_DIR}/{path}"
            entry["target"] = target
            found.groups[path] = {"action": value, "target": target,
                                  "members": [(path, tracked[path])]}
            found.moves.append((path, target))
    if references is None:
        references = adopt_references.derive_references(
            root, inventory.base_revision, found.moves, excluded)
    return settled, references

# --------------------------------------------------------------------------
# The `.gitignore` amendment
# --------------------------------------------------------------------------


def amend_gitignore_text(text: str) -> str:
    """`text` without the `.agents/runtime/` pattern, and without a comment
    block the removal would orphan.

    The only heuristic in this module, and deliberately a narrow one: the
    pattern line is matched exactly, the comment block immediately above it is
    removed only when nothing between the removal point and the next blank line
    or the end of the file still needs it, and a blank line doubled by the
    removal is collapsed to one.
    """
    trailing_newline = text.endswith("\n")
    lines = text.split("\n")
    if trailing_newline:
        lines = lines[:-1]
    index = next((position for position, line in enumerate(lines)
                  if line.strip() == RUNTIME_IGNORE_PATTERN), None)
    if index is None:
        return text
    remaining = lines[:index] + lines[index + 1:]

    start = index
    block_start = index
    while block_start > 0 and remaining[block_start - 1].strip().startswith("#"):
        block_start -= 1
    if block_start < index:
        still_needed = False
        for line in remaining[index:]:
            if not line.strip():
                break
            if not line.strip().startswith("#"):
                still_needed = True
                break
        if not still_needed:
            remaining = remaining[:block_start] + remaining[index:]
            start = block_start

    if 0 < start < len(remaining) and not remaining[start - 1].strip() \
            and not remaining[start].strip():
        remaining = remaining[:start] + remaining[start + 1:]
    return "\n".join(remaining) + ("\n" if trailing_newline else "")

# --------------------------------------------------------------------------
# Typed operations
# --------------------------------------------------------------------------


def operation(kind: str, sources: list[str], targets: list[str],
              before: str | None, after: str | None) -> dict:
    if kind not in OPERATION_KINDS:
        raise ValueError(f"unknown operation kind: {kind!r}")
    approval = approval_class_for(kind)
    if approval not in APPROVAL_CLASSES:
        raise ValueError(f"unknown approval class: {approval!r}")
    return {"op": kind, "sources": sources, "targets": targets,
            "before": before, "after": after, "approval_class": approval}


def derived_interval(platform_version: str) -> dict:
    """The interval a freshly amended contract declares.

    The running platform is the floor and its next major the ceiling: the one
    interval that is legal under R2.2 (a strict, non-pin range) and that admits
    exactly the compatibility the current generation promises.
    """
    parsed = agent_platform.parse_semver(platform_version)
    if parsed is None:
        raise refuse("adopt_failure", "adopt.manifest.invalid",
                     "/platform_version",
                     "the manifest's platform version is not strict SemVer")
    return {"min_inclusive": platform_version,
            "max_exclusive": f"{parsed[0] + 1}.0.0"}


def amended_contract(source: dict, interval: dict,
                     found: Candidates) -> dict:
    """The contract this adoption would write: `platform` plus moved bindings.

    Nothing else is touched. The amendment is confined to the one member the
    platform requires and the path bindings whose authored values name a tree
    this plan relocates, so a contract cannot acquire policy it did not author.
    """
    amended = json.loads(json.dumps(source))
    if "platform" not in amended:
        amended["platform"] = interval
    relocations = {group: info["target"] for group, info in found.groups.items()
                   if info["action"] == "move-canonical" and info["target"]
                   and info["target"] != group}
    bindings = amended.get("bindings")
    if not isinstance(bindings, dict):
        return amended
    paths = bindings.get("paths")
    if not isinstance(paths, dict):
        return amended
    artifacts = paths.get("artifacts")
    if isinstance(artifacts, dict):
        for key in ("specs", "plans"):
            if artifacts.get(key) in relocations:
                artifacts[key] = relocations[artifacts[key]]
    rejections = paths.get("rejections")
    if isinstance(rejections, list):
        paths["rejections"] = [relocations.get(value, value)
                               if isinstance(value, str) else value
                               for value in rejections]
    return amended


def binding_value(contract: dict, route: tuple) -> object:
    paths = contract.get("bindings", {}).get("paths", {})
    if route[0] == "artifacts":
        artifacts = paths.get("artifacts")
        return artifacts.get(route[1]) if isinstance(artifacts, dict) else None
    values = paths.get(route[0])
    if isinstance(values, list) and len(values) > route[1]:
        return values[route[1]]
    return None


def legacy_binding_operations(root: Path,
                              contract: dict) -> tuple[list[dict],
                                                       dict[str, bytes]]:
    """The living-reference rewrites (D30) — one per member of the closed
    tuple, and never a path outside it.

    Each rewrite merges the three fixed keys into the existing JSON and leaves
    every other key exactly as authored; a file that is absent, unreadable, not
    a JSON object, or already in agreement produces no operation at all.
    Agreement is a property of the parsed value, not of its bytes: a file that
    already holds every merged key in its own formatting is not work. When the
    contract's `release` is admissible, the file is also projected through
    `project_legacy_deploy` (#148 D30): the profile owns the deploy intent, so
    the legacy `deploy` member is dropped.
    """
    operations: list[dict] = []
    contents: dict[str, bytes] = {}
    for target in LEGACY_BINDING_CONFIGS:
        resolved = contained_path(root, target)
        if resolved is None or not resolved.is_file():
            continue
        current = read_bytes_bounded(resolved)
        if current is None:
            continue
        try:
            config = json.loads(current)
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        if not isinstance(config, dict):
            continue
        authored = json.loads(json.dumps(config))
        for key, route in LEGACY_BINDING_KEYS:
            value = binding_value(contract, route)
            if isinstance(value, str):
                config[key] = value
        candidate = current if config == authored else authored_bytes(config)
        release = contract.get("release")
        if (release == "unsupported" or isinstance(release, dict)) \
                and not release_profile.grammar_violations(release, contract):
            candidate = project_legacy_deploy(candidate, release)
        if candidate == current:
            continue
        operations.append(operation("write-file", [target], [target],
                                    sha256_hash(current), sha256_hash(candidate)))
        contents[target] = candidate
    return operations, contents


def evidence_record_members(found: Candidates) -> list[tuple[str, str]]:
    """Every adoption evidence record in the inspected tree, as sorted
    `(path, object_id)` pairs: the records a re-adoption supersedes, and
    paths the link derivation treats as deleted, so a link to one is
    unrewritable."""
    return sorted(
        (path, object_id) for info in found.groups.values()
        for path, object_id in info["members"]
        if is_evidence_record_path(path))


def generated_targets(contract_source: dict | None) -> set[str]:
    """The `target` of every `generated_file` projection the contract names.

    Those files are regenerated from their source rather than edited, so the
    link rewriter leaves them alone (D13). A missing or malformed contract
    names none."""
    projections = (contract_source or {}).get("projections")
    if not isinstance(projections, list):
        return set()
    return {entry["target"] for entry in projections
            if isinstance(entry, dict)
            and entry.get("kind") == "generated_file"
            and isinstance(entry.get("target"), str)}


def reference_excluded(contract_source: dict | None) -> set[str]:
    """The files no path-reference is read from or written to (D10): the
    contract, the `.gitignore`, the runtime sentinel, the legacy binding
    configs and every `generated_file` projection target. Each is amended or
    regenerated by an operation of its own, so an edit of the same bytes would
    be a second answer to what the file becomes."""
    return ({CONTRACT_FILENAME, GITIGNORE, RUNTIME_SENTINEL,
             *LEGACY_BINDING_CONFIGS} | generated_targets(contract_source))


def check_markdown_writes(changes: list[dict],
                          link_targets: set[str]) -> None:
    """Refuse an operation list whose Markdown handling is not the link
    rewrite's alone (D7).

    The `write-file` operations that target a Markdown path must be exactly
    the link rewrites, one per target, and no `delete-file` may name a
    Markdown path: a plan that rewrites a file's links and deletes it, or
    writes it twice, would disagree with itself. This is a derivation bug,
    never a repository condition, so it raises rather than gating."""
    written = [op["targets"][0] for op in changes
               if op["op"] == "write-file"
               and adopt_links.is_markdown_path(op["targets"][0])]
    if sorted(written) != sorted(link_targets) or len(set(written)) != len(
            written):
        raise ValueError(
            "Markdown write-file operations do not match the link rewrites: "
            f"{sorted(written)!r} against {sorted(link_targets)!r}")
    deleted = [path for op in changes if op["op"] == "delete-file"
               for path in op["sources"]
               if adopt_links.is_markdown_path(path)]
    if deleted:
        raise ValueError(
            f"a delete-file operation names Markdown: {sorted(deleted)!r}")


def check_reference_writes(changes: list[dict],
                           reference_targets: set[str]) -> None:
    """Refuse an operation list that does not hold each path-reference file
    exactly once, as a plain in-place write (D9).

    For every target exactly one operation may hold it, and that one is a
    `write-file` whose `sources` and `targets` are both `[target]`: a file
    edited by a reference answer and also moved, deleted, regenerated or
    written a second time would disagree with itself. An operation holds a
    file it names in `targets`, or in `sources` unless it is a
    `regenerate-projection`, which only reads its source and runs after the
    write, so a projection source a reference answer edits has one writer, as
    one the link rewriter edits does under `check_markdown_writes`. This is a
    derivation bug, never a repository condition, so it raises rather than
    gating."""
    for target in sorted(reference_targets):
        naming = [op for op in changes
                  if target in op["targets"]
                  or (target in op["sources"]
                      and op["op"] != "regenerate-projection")]
        if len(naming) != 1 or not (
                naming[0]["op"] == "write-file"
                and naming[0]["sources"] == [target]
                and naming[0]["targets"] == [target]):
            raise ValueError(
                f"{target!r} is not held by exactly one in-place write-file "
                f"operation: {naming!r}")


def build_operations(root: Path, found: Candidates, manifest: dict,
                     contract_source: dict | None,
                     plan_id: str, links: LinkRewrites,
                     reference_files: dict[str, tuple[str, str]]
                     ) -> tuple[list[dict], list[dict], dict[str, bytes]]:
    """The typed operations either side of the adoption's own bookkeeping.

    Returned as `(head, tail, contents)` rather than one list because
    the migration map and the evidence record sit between them and cannot be
    built until the outcome is known — and the outcome is decided by whether
    this list has anything in it. The apply order is the concatenation: the
    contract amendment, the relocations sorted by old path, the runtime
    sentinel and the `.gitignore` amendment, then the deletion of any
    superseded evidence record and the two records, then the living-reference
    rewrite, the Markdown link rewrites sorted by target, the path-reference
    writes sorted by target, and finally the projection regenerations.
    `reference_files` maps each non-Markdown file an answered path reference
    edits onto its `(before, after)` texts.

    `contents` maps each `write-file` target onto the exact bytes whose hash
    the operation publishes as `after`. The plan document carries the hash and
    `apply` carries out the write, so the bytes are generated here once and
    handed to both — a second generator would be a second answer to "what does
    adoption write", which is the duplication the bar forbids.
    """
    operations: list[dict] = []
    contents: dict[str, bytes] = {}

    interval = derived_interval(manifest["platform_version"])
    amended = (amended_contract(contract_source, interval, found)
               if contract_source is not None else None)
    # Compared as values, never as bytes: `contract_source` is the file this
    # parsed, so a contract the amendment leaves unchanged is no work however
    # it happens to be formatted, and only a real change is re-serialized.
    if amended is not None and amended != contract_source:
        current = read_bytes_bounded(root / CONTRACT_FILENAME)
        after = authored_bytes(amended)
        if current is not None:
            operations.append(operation(
                "write-file", [CONTRACT_FILENAME], [CONTRACT_FILENAME],
                sha256_hash(current), sha256_hash(after)))
            contents[CONTRACT_FILENAME] = after

    object_ids = {path: object_id for path, object_id in
                  [(p, o) for info in found.groups.values()
                   for p, o in info["members"]]}
    for old_path, new_path in sorted(found.moves):
        content = object_hash(object_ids[old_path])
        operations.append(operation("git-mv", [old_path], [new_path],
                                    content, content))

    sentinel = read_bytes_bounded(root / RUNTIME_SENTINEL)
    if sentinel != RUNTIME_SENTINEL_BYTES:
        operations.append(operation(
            "write-file", [RUNTIME_SENTINEL], [RUNTIME_SENTINEL],
            None if sentinel is None else sha256_hash(sentinel),
            sha256_hash(RUNTIME_SENTINEL_BYTES)))
        contents[RUNTIME_SENTINEL] = RUNTIME_SENTINEL_BYTES

    ignore_bytes = read_bytes_bounded(root / GITIGNORE)
    if ignore_bytes is not None:
        try:
            amended_ignore = amend_gitignore_text(
                ignore_bytes.decode("utf-8")).encode("utf-8")
        except UnicodeDecodeError:
            amended_ignore = ignore_bytes
        if amended_ignore != ignore_bytes:
            operations.append(operation(
                "write-file", [GITIGNORE], [GITIGNORE],
                sha256_hash(ignore_bytes), sha256_hash(amended_ignore)))
            contents[GITIGNORE] = amended_ignore

    tail: list[dict] = []
    if amended is not None:
        rewrites, rewritten = legacy_binding_operations(root, amended)
        tail.extend(rewrites)
        contents.update(rewritten)

    # One `write-file` per Markdown file whose relative links the moves
    # change, at the path the file has after them: a moved file is written
    # where `git-mv` left it, a retained one where it already is.
    for target in sorted(links.files):
        rewrite = links.files[target]
        before = rewrite.before.encode("utf-8")
        after = rewrite.after.encode("utf-8")
        tail.append(operation("write-file", [target], [target],
                              sha256_hash(before), sha256_hash(after)))
        contents[target] = after

    # One in-place `write-file` per non-Markdown file an answered path
    # reference edits (#350). Those files are never moved (a move source is
    # not read for references), so the target is where the file already is.
    for target in sorted(reference_files):
        before, after = (text.encode("utf-8")
                         for text in reference_files[target])
        tail.append(operation("write-file", [target], [target],
                              sha256_hash(before), sha256_hash(after)))
        contents[target] = after

    projections = (amended or {}).get("projections")
    if isinstance(projections, list):
        rows = [entry for entry in projections if isinstance(entry, dict)
                and isinstance(entry.get("target"), str)
                and isinstance(entry.get("source"), str)]
        for entry in sorted(rows, key=lambda row: row["target"]):
            # The one variable path this module opens. It is authored in the
            # contract, and this runs whether or not the resolver accepted that
            # contract, so the boundary's two guards are applied here rather
            # than borrowed from a validation that may never have happened: a
            # secret-shaped target is never read and never hashed, and a target
            # resolving outside the root is never followed. Either way the
            # operation is still emitted, with the `before` a path that was not
            # read truthfully has — null.
            target = entry["target"]
            resolved = (None if is_secret_path(target)
                        else contained_path(root, target))
            current = (None if resolved is None
                       else read_bytes_bounded(resolved))
            tail.append(operation(
                "regenerate-projection", [entry["source"]], [target],
                None if current is None else sha256_hash(current),
                # The rendered bytes are the resolver's to produce, so the
                # plan states the source it regenerates from rather than
                # predicting the output it has not asked for yet.
                None))
    return operations, tail, contents


def adoption_records(plan_id: str) -> dict:
    """Where this adoption's own two committed records live."""
    digest = plan_id.split(":", 1)[1]
    return {"migration_map": f"{MIGRATION_MAP_DIR}/{digest}.json",
            "evidence_record": f"{EVIDENCE_RECORD_DIR}/{digest}.json"}


def bookkeeping_operations(found: Candidates, plan_id: str, outcome: str,
                           base_revision: str, platform_block: dict,
                           decisions: dict,
                           ready_gates: list[dict],
                           link_rewrites: dict,
                           path_references: list[dict]) -> tuple[
                               list[dict], dict[str, bytes]]:
    """The path-migration map and the adoption evidence record, preceded by
    the deletion of every evidence record an earlier adoption committed.

    Both are named by the plan id and neither exists yet, so each is a
    `write-file` whose `before` is null; the record carries the outcome, which
    is why these two are built after routing rather than beside the moves.

    `verify` discovers exactly one record (D34), so a re-adoption supersedes
    its predecessor instead of committing a second one beside it: each prior
    candidate is a `delete-file`, which therefore needs the D16
    acknowledgement. Earlier migration maps stay, because they are the archive
    of paths that did move.

    Returned with the same `{target: bytes}` map `build_operations` returns,
    for the same reason: `apply` writes the very bytes this hashed.
    """
    records = adoption_records(plan_id)
    superseded = [(path, object_id)
                  for path, object_id in evidence_record_members(found)
                  if path != records["evidence_record"]]
    map_bytes = document_bytes({
        "schema_version": 1,
        "migration_id": plan_id,
        "moves": [{"old_path": old, "new_path": new}
                  for old, new in sorted(found.moves)],
    })
    record_bytes = document_bytes({
        "schema_version": 1,
        "plan_id": plan_id,
        "outcome": outcome,
        "base_revision": base_revision,
        "platform": platform_block,
        "decisions_accepted": decisions["recommended"] + decisions["answered"],
        # One row per inspected group: what it was fingerprinted as, and the
        # canonical home it ends up in (null when adoption leaves it alone).
        "sources": [{"path": entry["path"], "before": entry["fingerprint"],
                     "after": entry["target"]} for entry in found.entries],
        "checks": [{"id": gate["id"], "status": gate["status"]}
                   for gate in ready_gates],
        "link_rewrites": link_rewrites,
        "path_references": path_references,
        "path_migration_map": records["migration_map"],
    })
    return [
        operation("delete-file", [path], [], object_hash(object_id), None)
        for path, object_id in superseded
    ] + [
        operation("write-file", [records["migration_map"]],
                  [records["migration_map"]], None, sha256_hash(map_bytes)),
        operation("write-file", [records["evidence_record"]],
                  [records["evidence_record"]], None,
                  sha256_hash(record_bytes)),
    ], {records["migration_map"]: map_bytes,
        records["evidence_record"]: record_bytes}

# --------------------------------------------------------------------------
# Outcome routing (D10)
# --------------------------------------------------------------------------


def select_forward_step(manifest: dict, schema_version: object) -> dict | None:
    """The unique `migrations` record stepping forward from `schema_version`.

    Never a nearest match and never a guess (D36): more than one candidate is a
    refusal, and the absent case is returned as None for the caller to route.
    """
    matches = [entry for entry in manifest["migrations"]
               if isinstance(entry, dict)
               and entry.get("from_schema") == schema_version]
    if len(matches) > 1:
        raise refuse("adopt_failure", "adopt.manifest.forward_step_ambiguous",
                     "/migrations",
                     "more than one migration steps forward from the "
                     "project's declared schema")
    return matches[0] if matches else None


def route_outcome(manifest: dict, contract_source: dict | None,
                  contract_resolves: bool, agent_surface: bool,
                  pending_work: bool) -> tuple[str, str | None]:
    """The first matching routing rule, as `(outcome, forward_migration_id)`.

    Written as an ordered evaluation rather than a lookup so that the ordering
    is the thing a reader checks.
    """
    # 1. Nothing to adopt from and nothing declared.
    if contract_source is None and not agent_surface:
        return "bootstrap", None
    # 2. Legacy surface without a contract.
    if contract_source is None:
        return "reconcile", None
    versions = manifest["project_schema_versions"]
    declared = contract_source.get("schema_version")
    # 3. A supported schema that is not the highest supported one.
    if declared in versions and declared != versions[-1]:
        forward = select_forward_step(manifest, declared)
        if forward is None:
            raise refuse("adopt_failure",
                         "adopt.manifest.forward_step_missing", "/migrations",
                         "no migration steps forward from the project's "
                         "declared schema")
        return "migration_required", forward["id"]
    # 4. A schema this platform does not support at all.
    if declared not in versions:
        forward = select_forward_step(manifest, declared)
        if forward is not None:
            return "migration_required", forward["id"]
        return "repair_required", None
    # 5. The current schema with adoption work outstanding.
    if pending_work:
        return "reconcile", None
    # 6. The current schema, valid, conformant, nothing left.
    if contract_resolves:
        return "no_change", None
    # 7. The current schema, invalid or drifted, with no legacy surface.
    return "repair_required", None

# --------------------------------------------------------------------------
# Ready gates
# --------------------------------------------------------------------------


def evaluate_ready_gates(root: Path, found: Candidates,
                         contract_source: dict | None,
                         contract_resolves: bool,
                         unfixable_pointers: list[str],
                         untracked: list[str],
                         decisions: dict,
                         link_rewrites: dict) -> list[dict]:
    """One entry per gate, in declaration order. All must pass for `ready`."""
    gates: list[dict] = []

    if contract_source is None:
        gates.append(gate_entry(READY_GATES[0], "failed",
                                "adopt.contract.absent"))
    elif contract_resolves or not unfixable_pointers:
        gates.append(gate_entry(READY_GATES[0], "passed", None))
    else:
        gates.append(gate_entry(READY_GATES[0], "failed",
                                "adopt.contract.unfixable_violations"))

    undecided = [entry for entry in found.entries
                 if entry["action"] == "needs-decision"]
    gates.append(gate_entry(
        READY_GATES[1], "failed" if undecided else "passed",
        "adopt.candidate.unclassified" if undecided else None))

    gates.append(gate_entry(
        READY_GATES[2], "failed" if decisions["open"] else "passed",
        "adopt.decisions.open" if decisions["open"] else None))

    gates.append(gate_entry(
        READY_GATES[3], "failed" if untracked else "passed",
        "adopt.worktree.untracked_overlap" if untracked else None))

    # A planned destination that already exists (a dangling symlink
    # included) or sits under an existing file or any symlink, or that
    # collides with another: the same path, or one inside the other.
    def present(path: Path) -> bool:
        return path.is_symlink() or path.exists()

    def not_a_directory(path: Path) -> bool:
        return path.is_symlink() or (path.exists() and not path.is_dir())

    destinations = [new for _, new in found.moves]
    counts = Counter(destinations)
    planned = set(destinations)
    occupied = [
        new for new in destinations
        if present(root / new)
        or any(not_a_directory(root / str(parent))
               for parent in PurePosixPath(new).parents)
        or counts[new] > 1
        or any(str(parent) in planned
               for parent in PurePosixPath(new).parents)]
    gates.append(gate_entry(
        READY_GATES[4], "failed" if occupied else "passed",
        "adopt.destination.occupied" if occupied else None))

    untracked_sources = [old for old, _ in found.moves
                         if old not in found.tracked_paths]
    gates.append(gate_entry(
        READY_GATES[5], "failed" if untracked_sources else "passed",
        "adopt.move.source_untracked" if untracked_sources else None))

    secret_moves = [path for pair in found.moves for path in pair
                    if is_secret_path(path)]
    gates.append(gate_entry(
        READY_GATES[6], "failed" if secret_moves else "passed",
        "adopt.move.secret_shaped" if secret_moves else None))

    unrewritable = link_rewrites["unrewritable"]
    gates.append(gate_entry(
        READY_GATES[7], "failed" if unrewritable else "passed",
        "adopt.link.unrewritable" if unrewritable else None))
    return gates


GATE_MESSAGES = {
    "contract-valid-after-amendment":
        "the contract is absent, or carries violations the planned amendment "
        "does not address",
    "no-needs-decision": "a discovered candidate carries no lifecycle class",
    "no-open-decisions": "an open question has no answer",
    "no-untracked-overlap":
        "an untracked file sits inside an inspected source or a planned "
        "destination",
    "no-existing-destination": (
        "a planned destination already exists, sits under a file or "
        "symlink, or collides with another"),
    "move-sources-tracked": "a planned move source is not tracked",
    "no-secret-path-in-moves":
        "a secret-shaped path is a planned move source or target",
    "no-unrewritable-link":
        "a relative Markdown link into or out of a moved path cannot be "
        "rewritten to resolve to the same target",
}


def blockers_for(gates: list[dict]) -> list[dict]:
    return sorted(
        ({"id": gate["id"], "message": GATE_MESSAGES[gate["id"]]}
         for gate in gates if gate["status"] == "failed"),
        key=lambda item: item["id"])

# --------------------------------------------------------------------------
# The plan document
# --------------------------------------------------------------------------


def compute_plan_id(project_id: str | None, base_revision: str,
                    platform_block: dict, evidence: list[dict],
                    answered: list[dict], link_rewrites: dict,
                    path_references: list[dict]) -> str:
    """D15's content address over exactly eight inputs: the project id, the
    base revision, the platform block, the evidence, the answered decisions,
    the schema version, the `link_rewrites` summary (#345) and the
    `path_references` rows (#350).

    The manifest's `migrations` array is deliberately *not* one of them (D36):
    it can only route toward `migration_required` or `repair_required`, and
    both produce `state: not_applicable` with `changes: []`, so no appliable
    plan's meaning can turn on it. Timestamps, prose, the absolute checkout
    path and the human view are outside it for the same reason — the id is a
    property of the repository, not of the machine that inspected it.
    """
    source = {
        "adopt_schema_version": ADOPT_SCHEMA_VERSION,
        "project_id": project_id,
        "base_revision": base_revision,
        "platform": platform_block,
        "evidence": evidence,
        "decisions_answered": answered,
        "link_rewrites": link_rewrites,
        "path_references": path_references,
    }
    return "sha256:" + hashlib.sha256(canonical_json(source)).hexdigest()


def next_command_for(state: str, outcome: str, root: Path, plan_id: str,
                     forward_migration: str | None,
                     repair_id: str | None) -> str | None:
    """What the caller does next, or None while the plan is still `draft`."""
    if outcome == "no_change":
        return f"adopt-project verify --register --repo-root {root}"
    if outcome == "migration_required":
        return f"migrate {forward_migration}"
    if outcome == "repair_required":
        return f"repair {repair_id or 'adopt.schema.no_forward_step'}"
    if plan_state_is_terminal(state):
        raise ValueError(f"appliable outcome in a terminal state: {outcome!r}")
    if state == "ready":
        return f"adopt-project apply --plan-id {plan_id}"
    return None


# --------------------------------------------------------------------------
# The plan document's home on disk
#
# One derivation, one identifier, one file: a plan is stored under the digest
# half of its own content-addressed id, in user scope and nowhere near the
# target checkout (D14). `apply` reads a plan back from exactly here, and
# retains a failed attempt by rewriting the same file.
# --------------------------------------------------------------------------


def stored_plan_path(digest: str) -> Path:
    return agent_platform.state_root() / "adopt" / "plans" / f"{digest}.json"


def store_plan_path(plan_id: str) -> Path:
    return stored_plan_path(plan_id.split(":", 1)[1])


def stored_repo_root(plan_id: str) -> str | None:
    """The checkout a plan already stored under this id was derived from.

    None when nothing is stored, and None as well when what is stored will not
    parse or names no `repo_root`: a file in that state describes no checkout,
    so it claims none, and `apply` refuses it as `adopt.plan.malformed` anyway.
    """
    data = read_bytes_bounded(store_plan_path(plan_id))
    if data is None:
        return None
    try:
        document = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    handoff = document.get("handoff") if isinstance(document, dict) else None
    root = handoff.get("repo_root") if isinstance(handoff, dict) else None
    return root if isinstance(root, str) else None


def require_unclaimed_digest(plan_id: str, root: Path) -> None:
    """Refuse to re-point a stored plan at a second checkout.

    The content address deliberately excludes the absolute checkout path (D15),
    so two checkouts holding identical content at one revision produce one
    `plan_id` — and therefore one stored document, at one path. Without this,
    planning the second checkout would silently rewrite the first document's
    `handoff.repo_root`, and `apply <plan_id>` — whose only argument is that id
    (D16) — would carry an approval given for one checkout out against the
    other. Storing is what binds the id to a checkout, so the binding is made
    immutable here rather than re-checked at apply time: `apply` reads its
    target from the document, and by then there is nothing left to compare it
    against.

    Re-planning the same checkout is unaffected and stays idempotent.
    """
    claimed = stored_repo_root(plan_id)
    if claimed is not None and claimed != str(root):
        raise refuse(
            "adopt_failure", "adopt.plan.repo_root_claimed",
            "/handoff/repo_root",
            "a plan under this identifier is already stored for a different "
            "checkout")


def store_document(plan_id: str, document: dict) -> None:
    """Write a plan document to its one user-scope home, atomically (D14)."""
    plan_path = store_plan_path(plan_id)
    agent_platform.ensure_directory(plan_path.parent)
    agent_platform.write_atomically(
        plan_path, canonical_json(document) + b"\n")
