"""Fresh Git records and shared adaptive actual review candidates."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Callable, Iterable, Iterator, Mapping

from agent_tools.canonical import telemetry_digest
from agent_tools.review_git import HistoryError, original_commits, original_range
from agent_tools.review_pack import (ReviewEvidenceSize, ReviewLimits, ReviewRecord, ReviewRecordSize,
    canonical_manifest as _canonical, measure_lengths, pack_whole_records, place_record_sizes)

RECORD_POLICY = {
    "kind": "review-git-records/v2",
    "git_config": ["-c", "diff.renames=true", "-c", "diff.renameLimit=0",
                   "-c", "core.quotePath=true"],
    "diff_args": ["--find-renames=50%", "--no-ext-diff", "--no-textconv",
                  "--ignore-submodules=none", "--submodule=short",
                  "--full-index", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
                  "--diff-algorithm=myers", "--no-indent-heuristic", "--inter-hunk-context=0",
                  "--no-color", "--line-prefix=", "--output-indicator-new=+",
                  "--output-indicator-old=-", "--output-indicator-context= "],
}
RECORD_POLICY_SHA256 = telemetry_digest(RECORD_POLICY)
PACKING_POLICY = {
    "kind": "review-packing/v1",
    "record_policy_sha256": RECORD_POLICY_SHA256,
    "initial": {"context_lines": 10, "strategy": "sequential"},
    "adaptive": [{"context_lines": context, "strategy": "stable-first-fit-whole-file"}
                 for context in (7, 5, 3, 1, 0)],
    "adaptive_violations": ["member_count", "aggregate_bytes"],
    "fallback": "initial",
    "manifest_encoding": "canonical-json-utf8-lf/v1",
    "forecast_measurement": {"kind": "whole-record-lengths/v1",
                             "subject_encoding": "repeated-json-control-u0001/v1",
                             "subject_json_bytes_per_reserved_byte": 6},
}
PACKING_POLICY_SHA256 = telemetry_digest(PACKING_POLICY)
# The retained review evidence's record domain (issue 569): frozen, never the living policy.
RECORD_POLICY_V1 = {
    "kind": "review-git-records/v1",
    "git_config": ["-c", "diff.renames=true", "-c", "diff.renameLimit=0",
                   "-c", "core.quotePath=true"],
    "diff_args": ["--find-renames=100%", "--no-ext-diff", "--no-textconv",
                  "--ignore-submodules=none", "--submodule=short",
                  "--full-index", "--no-relative", "--src-prefix=a/", "--dst-prefix=b/",
                  "--diff-algorithm=myers", "--no-indent-heuristic", "--inter-hunk-context=0",
                  "--no-color", "--line-prefix=", "--output-indicator-new=+",
                  "--output-indicator-old=-", "--output-indicator-context= "],
}
RECORD_POLICY_V1_SHA256 = telemetry_digest(RECORD_POLICY_V1)
PACKING_POLICY_V1 = {
    "kind": "review-packing/v1",
    "record_policy_sha256": RECORD_POLICY_V1_SHA256,
    "initial": {"context_lines": 10, "strategy": "sequential"},
    "adaptive": [{"context_lines": context, "strategy": "stable-first-fit-whole-file"}
                 for context in (7, 5, 3, 1, 0)],
    "adaptive_violations": ["member_count", "aggregate_bytes"],
    "fallback": "initial",
    "manifest_encoding": "canonical-json-utf8-lf/v1",
    "forecast_measurement": {"kind": "whole-record-lengths/v1",
                             "subject_encoding": "repeated-json-control-u0001/v1",
                             "subject_json_bytes_per_reserved_byte": 6},
}
PACKING_POLICY_V1_SHA256 = telemetry_digest(PACKING_POLICY_V1)
# Names that follow each `--name-status -z` operation letter (issue 569).
RECORD_OPERATIONS = {"A": 1, "M": 1, "D": 1, "T": 1, "R": 2}
_RENAME_FLOOR_RE = re.compile(r"--find-renames=([0-9]{1,3})%\Z")
_RENAME_SCORE_RE = re.compile(r"R[0-9]{3}\Z")
GENERATED_EVIDENCE_KINDS = ("ef-core-migration-designer", "whole-file-deletion")

SHA_RE = re.compile(r"[0-9a-f]{40}\Z")
DIFF_BOUNDARY = re.compile(br"(?m)^diff --git ")
MIGRATION_ID_RE = re.compile(br'\[Migration\("([^"\r\n]+)"\)\]')
PRODUCT_VERSION_RE = re.compile(
    br'\.HasAnnotation\("ProductVersion",\s*"([^"\r\n]+)"\)'
)
# Worst-case field widths for a planned designer's evidence (ef_designer_evidence_bound):
# encoded bytes of the migration id and product version, and decimal digits of a count.
EF_BOUND_MIGRATION_ID_BYTES = 255
EF_BOUND_PRODUCT_VERSION_BYTES = 64
EF_BOUND_COUNT_DIGITS = 16


class InvocationError(Exception):
    """The caller supplied invalid syntax, identity, or destination authority."""


class GenerationError(Exception):
    """The package could not be generated, measured, or published."""


def _policies(record_policy: Mapping) -> Mapping:
    """The packing policy that binds `record_policy`; the set is closed, by object identity."""
    if record_policy is RECORD_POLICY:
        record_sha, packing, packing_sha = RECORD_POLICY_SHA256, PACKING_POLICY, PACKING_POLICY_SHA256
    elif record_policy is RECORD_POLICY_V1:
        record_sha, packing, packing_sha = RECORD_POLICY_V1_SHA256, PACKING_POLICY_V1, PACKING_POLICY_V1_SHA256
    else:
        raise GenerationError("unsupported record policy")
    if telemetry_digest(record_policy) != record_sha:
        raise GenerationError("unsupported record policy")
    if telemetry_digest(packing) != packing_sha:
        raise GenerationError("unsupported packing policy")
    return packing


def _packing_choices(record_policy: Mapping = RECORD_POLICY) -> tuple[dict, ...]:
    packing = _policies(record_policy)
    return (packing["initial"], *packing["adaptive"])


def record_operation(token: bytes, record_policy: Mapping = RECORD_POLICY) -> tuple[str, int]:
    """`token`, one `--name-status -z` operation field, under `record_policy`, and how many names follow it.

    `A`, `M`, `D` and `T` take one name. `R<score>` takes two, old then new, when its three-digit score is at
    least the floor in the policy's `--find-renames=<N>%` argument and at most 100. Anything else is refused
    (issue 569).
    """
    _policies(record_policy)
    try:
        operation = token.decode("ascii")
    except UnicodeDecodeError as exc:
        raise GenerationError("unsupported Git record operation") from exc
    if operation in RECORD_OPERATIONS and operation != "R":
        return operation, RECORD_OPERATIONS[operation]
    if _RENAME_SCORE_RE.match(operation):
        floor = next(int(match.group(1)) for arg in record_policy["diff_args"]
                     if (match := _RENAME_FLOOR_RE.match(arg)))
        if floor <= int(operation[1:]) <= 100:
            return operation, RECORD_OPERATIONS["R"]
    raise GenerationError("unsupported Git record operation")


@dataclass(frozen=True)
class FutureCommit:
    """Measurement-only metadata for a conservative future subject byte bound."""
    sha: str
    subject_bytes: int

    def __post_init__(self) -> None:
        if (not isinstance(self.sha, str) or SHA_RE.fullmatch(self.sha) is None
                or type(self.subject_bytes) is not int or self.subject_bytes < 0):
            raise GenerationError("invalid future commit measurement")


@dataclass(frozen=True)
class CandidateInput:
    context_lines: int | None
    records: tuple[ReviewRecord | ReviewRecordSize | ReviewEvidenceSize, ...]
    commits: tuple[Mapping, ...]
    stat: Mapping
    source_diff_bytes: int
    base: str
    head: str
    package_name: str
    future_commits: tuple[FutureCommit, ...] = ()


@dataclass(frozen=True)
class ReviewCandidate:
    manifest: Mapping
    shards: tuple[bytes, ...]
    metrics: Mapping
    status: str
    violations: tuple[str, ...]


@dataclass(frozen=True)
class ReviewMeasurement:
    """A nonpublishable result: no concrete manifest or shard payloads exist."""
    context_lines: int | None
    metrics: Mapping
    status: str
    violations: tuple[str, ...]


def git_diff(repo: Path, base_tree: str, head_tree: str, *view: str,
             record_policy: Mapping = RECORD_POLICY) -> bytes:
    """Every measurement view of one record domain uses that domain's explicit record policy."""
    choices = _packing_choices(record_policy)
    if view not in (("--numstat", "-z"), ("--name-only", "-z"), ("--name-status", "-z"),
                    *(("--binary", f"-U{choice['context_lines']}") for choice in choices)):
        raise GenerationError("unsupported diff view")
    return record_git(repo, *record_policy["git_config"], "diff",
                      *record_policy["diff_args"], *view, base_tree, head_tree)


def record_git(repo: Path, *args: str) -> bytes:
    """Run `git <args>` for a record in a fresh view of `repo`'s objects, isolated from every attribute and
    configuration source (issue 255; D1, D7).

    The view is a new bare Git directory made without `git init`, so no template applies. It holds an unborn
    `HEAD`, an empty `refs/`, a `config` that declares only the repository format, and an absolute alternate
    to `repo`'s object directory. Git runs there under the caller's environment without any `GIT_*` variable
    or `XDG_CONFIG_HOME`, with `HOME` set to the view and system configuration and attributes off. No
    working tree, index, attributes file or configuration beyond Git's defaults and the argv's own `-c`
    reaches the output. The view is removed on every outcome.
    """
    found = _run_git(repo, "rev-parse", "--path-format=absolute", "--git-path", "objects",
                     "--show-object-format")
    lines = found.split("\n")
    if len(lines) != 3 or lines[2] or not os.path.isabs(lines[0]) or lines[1] not in ("sha1", "sha256"):
        raise GenerationError("git command failed")
    objects, object_format = lines[0], lines[1]
    env = {key: value for key, value in os.environ.items()
           if not key.startswith("GIT_") and key != "XDG_CONFIG_HOME"}
    try:
        with tempfile.TemporaryDirectory(prefix="record-view-") as name:
            view = Path(name)
            (view / "refs").mkdir()
            (view / "objects/info").mkdir(parents=True)
            (view / "HEAD").write_text("ref: refs/heads/record-view\n", encoding="utf-8")
            config = ("[core]\n\trepositoryformatversion = "
                      f"{0 if object_format == 'sha1' else 1}\n\tbare = true\n")
            if object_format != "sha1":
                config += f"[extensions]\n\tobjectFormat = {object_format}\n"
            (view / "config").write_text(config, encoding="utf-8")
            (view / "objects/info/alternates").write_text(objects + "\n", encoding="utf-8")
            env.update(HOME=str(view), GIT_CONFIG_NOSYSTEM="1", GIT_ATTR_NOSYSTEM="1")
            return subprocess.run(["git", f"--git-dir={view}", *args], cwd=view, env=env,
                                  check=True, capture_output=True).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GenerationError("git command failed") from exc


def commit_subject(repo: Path, sha: str) -> str:
    """`sha`'s subject line through `record_git`, strictly UTF-8, without its trailing newline (D10)."""
    raw = record_git(repo, "show", "-s", "--no-show-signature", "--format=%s", sha).removesuffix(b"\n")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise GenerationError("commit metadata is not UTF-8") from exc


def actual_inputs(repo: Path, base: str, head: str, package_name: str,
                  limits: ReviewLimits, *, record_policy: Mapping = RECORD_POLICY) -> Iterator[CandidateInput]:
    try:
        base_commit, head_commit = original_commits(repo, (base, head))
        base_tree, head_tree = base_commit.tree, head_commit.tree
    except HistoryError as exc:
        raise GenerationError("invalid original history") from exc
    yield from actual_inputs_from_trees(repo, base_tree, head_tree, base=base, head=head,
        commits=tuple(_commits(repo, base, head)), package_name=package_name, limits=limits,
        record_policy=record_policy)


def actual_inputs_from_trees(repo: Path, base_tree: str, head_tree: str, *,
                            base: str, head: str, commits: tuple[Mapping, ...],
                            package_name: str, limits: ReviewLimits,
                            record_policy: Mapping = RECORD_POLICY) -> Iterator[CandidateInput]:
    for tree in (base_tree, head_tree):
        if not isinstance(tree, str) or SHA_RE.fullmatch(tree) is None:
            raise GenerationError("invalid tree identity")
    paths = _changed_paths(git_diff(repo, base_tree, head_tree, "--name-only", "-z",
                                    record_policy=record_policy))
    stats = _parse_numstat(git_diff(repo, base_tree, head_tree, "--numstat", "-z",
                                    record_policy=record_policy))
    if len(set(paths)) != len(paths) or len(paths) != stats["files_changed"]:
        raise GenerationError("diff coverage does not match numstat")
    operations = _record_operations(
        git_diff(repo, base_tree, head_tree, "--name-status", "-z", record_policy=record_policy), paths,
        record_policy)
    for number, choice in enumerate(_packing_choices(record_policy)):
        context = None if number == 0 else choice["context_lines"]
        raw = git_diff(repo, base_tree, head_tree, "--binary", f"-U{choice['context_lines']}",
                       record_policy=record_policy)
        chunks = _chunks_by_path(_split_diff(raw), operations)
        records = []
        for path, operation, chunk in zip(paths, operations, chunks):
            evidence = None
            payload = chunk
            # A rename record keeps its whole section: generated evidence reads one path's sides (issue 569).
            if len(chunk) > limits.member_max_bytes and not operation.startswith("R"):
                item = _ef_designer_evidence(repo, base_tree, head_tree, path, len(chunk))
                if item is None and operation == "D":
                    item = _whole_file_deletion_evidence(repo, base_tree, path, len(chunk))
                if item is not None:
                    compact = _canonical({"review-package-generated-evidence": item})
                    if len(compact) <= limits.member_max_bytes:
                        evidence, payload = item, compact
            records.append(ReviewRecord(path, payload, len(chunk), evidence))
        yield CandidateInput(context, tuple(records), commits, stats, len(raw), base, head, package_name)


def pack_input(item: CandidateInput, limits: ReviewLimits) -> ReviewCandidate:
    result = _build_candidate(item, limits, measurement_only=False)
    assert isinstance(result, ReviewCandidate)
    return result


def measure_input(item: CandidateInput, limits: ReviewLimits) -> ReviewMeasurement:
    result = _build_candidate(item, limits, measurement_only=True)
    assert isinstance(result, ReviewMeasurement)
    return result


def _build_candidate(item: CandidateInput, limits: ReviewLimits, *,
                     measurement_only: bool) -> ReviewCandidate | ReviewMeasurement:
    choices = _packing_choices()
    contexts = (None, *(choice["context_lines"] for choice in choices[1:]))
    if (not isinstance(item, CandidateInput) or item.context_lines not in contexts
            or isinstance(item.context_lines, bool)):
        raise GenerationError("invalid candidate context")
    if (Path(item.package_name).name != item.package_name
            or Path(item.package_name).suffix != ".json" or not Path(item.package_name).stem):
        raise GenerationError("invalid package name")
    if (any(not isinstance(record, (ReviewRecord, ReviewRecordSize, ReviewEvidenceSize))
            for record in item.records)
            or len({record.path for record in item.records}) != len(item.records)
            or any(not isinstance(commit, FutureCommit) for commit in item.future_commits)):
        raise GenerationError("invalid candidate measurement data")
    if not measurement_only and (item.future_commits or any(
            isinstance(record, (ReviewRecordSize, ReviewEvidenceSize)) for record in item.records)):
        raise GenerationError("symbolic measurements cannot be published as concrete candidates")
    if (type(item.source_diff_bytes) is not int
            or item.source_diff_bytes != sum(record.source_bytes for record in item.records)
            or item.stat.get("files_changed") != len(item.records)):
        raise GenerationError("invalid candidate coverage")
    generated = []
    for record in item.records:
        if record.generated_evidence is not None:
            evidence = record.generated_evidence
            if (evidence.get("path") != record.path
                    or evidence.get("kind") not in GENERATED_EVIDENCE_KINDS
                    or evidence.get("source_diff_bytes") != record.source_bytes
                    or record.source_bytes <= limits.member_max_bytes
                    or len(record.payload) > limits.member_max_bytes
                    or record.payload != _canonical({"review-package-generated-evidence": evidence})):
                raise GenerationError("invalid generated evidence record")
            generated.append(evidence)
        elif record.source_bytes != record.review_bytes:
            raise GenerationError("incomplete ordinary record")
    strategy = choices[contexts.index(item.context_lines)]["strategy"]
    record_sizes = tuple(record.review_bytes for record in item.records)
    placement = place_record_sizes(record_sizes, limits.member_max_bytes, strategy=strategy)
    member_sizes = tuple(sum(record_sizes[index] for index in shard) for shard in placement)
    shard_dir = Path(item.package_name).with_suffix(".shards").name
    common = {"kind": "review-package", "purpose": "diff-review",
              "range": {"base": item.base, "head": item.head},
              "commits": [*item.commits, *({"sha": commit.sha, "subject": ""}
                                           for commit in item.future_commits)], "stat": dict(item.stat),
              "shards": [{"path": f"{shard_dir}/shard-{number:03d}.diff", "bytes": size}
                         for number, size in enumerate(member_sizes, 1)]}
    if item.context_lines is not None or generated:
        manifest = {"interface_version": 3 if item.context_lines is not None else 2, **common,
                    "source_diff_bytes": item.source_diff_bytes,
                    "total_review_bytes": sum(member_sizes), "generated_evidence": generated,
                    "coverage": {"complete": True, "file_diff_count": len(item.records),
                                 "byte_complete_file_count": len(item.records) - len(generated),
                                 "generated_evidence_file_count": len(generated)}}
        if item.context_lines is not None:
            manifest["packaging"] = {"context_lines": item.context_lines, "shard_strategy": strategy}
    else:
        manifest = {"interface_version": 1, **common, "total_diff_bytes": item.source_diff_bytes,
                    "coverage": {"complete": True, "file_diff_count": len(item.records)}}
    reserved_json_bytes = (sum(commit.subject_bytes for commit in item.future_commits)
                           * PACKING_POLICY["forecast_measurement"]["subject_json_bytes_per_reserved_byte"])
    metrics, status, violations = measure_lengths(len(_canonical(manifest)) + reserved_json_bytes,
                                                member_sizes, limits)
    if measurement_only:
        return ReviewMeasurement(item.context_lines, metrics, status, violations)
    shards = pack_whole_records(item.records, limits.member_max_bytes, strategy=strategy)
    return ReviewCandidate(manifest, shards, metrics, status, violations)


def select_candidate(inputs: Iterable[CandidateInput], limits: ReviewLimits, *,
                     transform: Callable[[CandidateInput], CandidateInput] | None = None,
                     measurement_only: bool = False) -> ReviewCandidate | ReviewMeasurement:
    if type(measurement_only) is not bool:
        raise GenerationError("invalid candidate measurement mode")
    initial = None
    choices = _packing_choices()
    for expected, item in zip((None, *(c["context_lines"] for c in choices[1:])), inputs):
        if item.context_lines != expected:
            raise GenerationError("invalid candidate sequence")
        if transform is not None:
            original = item
            item = transform(item)
            if (item.context_lines, item.base, item.head, item.package_name) != (
                    original.context_lines, original.base, original.head, original.package_name):
                raise GenerationError("transformation changed candidate identity")
            authorized = {r.path: r for r in original.records if r.generated_evidence is not None}
            # A planned entry (ReviewEvidenceSize) is measurement-only: _build_candidate
            # refuses it outside measurement, so it can never be published as evidence.
            if any(r.generated_evidence is not None and r != authorized.get(r.path)
                   and not (measurement_only and isinstance(r, ReviewEvidenceSize))
                   for r in item.records):
                raise GenerationError("transformation added unauthorized generated evidence")
        candidate = measure_input(item, limits) if measurement_only else pack_input(item, limits)
        if initial is None:
            initial = candidate
            if candidate.status == "within_budget" or not set(candidate.violations).issubset(
                    set(PACKING_POLICY["adaptive_violations"])):
                return candidate
        elif candidate.status == "within_budget":
            return candidate
    if initial is None:
        raise GenerationError("missing initial candidate")
    return initial

def _run_git(repo: Path, *args: str, binary: bool = False) -> bytes | str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            capture_output=True,
            text=not binary,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GenerationError("git command failed") from exc
    return result.stdout


def _full_commit(repo: Path, value: str, label: str) -> str:
    if not value or value.startswith("-"):
        raise InvocationError(f"invalid {label}")
    try:
        output = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "--verify", f"{value}^{{commit}}"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise InvocationError(f"invalid {label}") from exc
    if SHA_RE.fullmatch(output) is None:
        raise InvocationError(f"invalid {label}")
    return output


def _split_diff(raw: bytes) -> list[bytes]:
    if not raw:
        return []
    starts = [match.start() for match in DIFF_BOUNDARY.finditer(raw)]
    if not starts or starts[0] != 0:
        raise GenerationError("diff is not split at file boundaries")
    return [raw[start:end] for start, end in zip(starts, starts[1:] + [len(raw)])]


def _chunks_by_path(chunks: list[bytes], operations: tuple[str, ...]) -> list[bytes]:
    """One chunk per path: a type change is one path but two `diff --git` sections."""
    grouped: list[bytes] = []
    position = 0
    for operation in operations:
        width = 2 if operation == "T" else 1
        grouped.append(b"".join(chunks[position : position + width]))
        position += width
    if position != len(chunks):
        raise GenerationError("diff coverage does not match paths")
    return grouped


def _changed_paths(raw: bytes) -> list[str]:
    if not raw:
        return []
    items = raw.split(b"\0")
    if items[-1] != b"" or any(not item for item in items[:-1]):
        raise GenerationError("malformed Git path list")
    try:
        return [item.decode("utf-8", errors="strict") for item in items[:-1]]
    except UnicodeDecodeError as exc:
        raise GenerationError("Git path is not UTF-8") from exc


def _record_operations(raw: bytes, paths: list[str], record_policy: Mapping) -> tuple[str, ...]:
    """Each record's `--name-status -z` operation, in the order of the name-only `paths`."""
    if not raw:
        if paths:
            raise GenerationError("Git status does not match paths")
        return ()
    items = raw.split(b"\0")
    if items[-1] != b"":
        raise GenerationError("malformed Git status list")
    items.pop()
    operations: list[str] = []
    destinations: list[bytes] = []
    position = 0
    while position < len(items):
        operation, names = record_operation(items[position], record_policy)
        listed = items[position + 1 : position + 1 + names]
        if len(listed) != names or any(not name for name in listed):
            raise GenerationError("malformed Git status list")
        operations.append(operation)
        destinations.append(listed[-1])
        position += 1 + names
    try:
        decoded = [name.decode("utf-8", errors="strict") for name in destinations]
    except UnicodeDecodeError as exc:
        raise GenerationError("Git path is not UTF-8") from exc
    if decoded != paths:
        raise GenerationError("Git status does not match paths")
    return tuple(operations)


def _blob_at(repo: Path, commit: str, path: str) -> tuple[str, bytes] | None:
    try:
        listed = subprocess.run(
            ["git", "--literal-pathspecs", "-C", str(repo), "ls-tree", "-z", commit, "--", path],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GenerationError("git tree lookup failed") from exc
    if not listed:
        return None
    rows = listed.split(b"\0")
    if rows[-1] != b"" or len(rows) != 2 or b"\t" not in rows[0]:
        raise GenerationError("ambiguous git tree lookup")
    metadata, listed_path = rows[0].split(b"\t", 1)
    fields = metadata.split(b" ")
    if (len(fields) != 3 or fields[1] != b"blob"
            or SHA_RE.fullmatch(fields[2].decode("ascii", errors="ignore")) is None
            or listed_path != path.encode("utf-8")):
        raise GenerationError("invalid git tree entry")
    sha = fields[2].decode("ascii")
    try:
        raw = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", sha],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise GenerationError("git blob lookup failed") from exc
    return sha, raw


def _blob_identity(blob: tuple[str, bytes]) -> dict[str, object]:
    sha, raw = blob
    return {"blob_sha": sha, "bytes": len(raw), "content_sha256": hashlib.sha256(raw).hexdigest()}


def _ef_designer_side(blob: tuple[str, bytes] | None) -> dict[str, object] | None:
    if blob is None:
        return None
    sha, raw = blob
    migration = MIGRATION_ID_RE.search(raw)
    if migration is None:
        raise GenerationError("invalid EF migration designer")
    product = PRODUCT_VERSION_RE.search(raw)
    try:
        migration_id = migration.group(1).decode("utf-8", errors="strict")
        product_version = (
            product.group(1).decode("utf-8", errors="strict")
            if product is not None else None
        )
    except UnicodeDecodeError as exc:
        raise GenerationError("invalid EF migration metadata") from exc
    return {
        **_blob_identity(blob),
        "migration_id": migration_id,
        "product_version": product_version,
        "entity_types": raw.count(b"modelBuilder.Entity("),
        "properties": raw.count(b"b.Property<"),
        "indexes": raw.count(b"b.HasIndex("),
        "foreign_keys": raw.count(b"b.HasOne("),
        "tables": raw.count(b"b.ToTable("),
    }


def ef_designer_path(path: str) -> bool:
    """The paths actual production may compact as `ef-core-migration-designer` evidence."""
    return "Migrations" in path.split("/") and path.endswith(".Designer.cs")


def ef_designer_evidence_bound(path: str, source_diff_bytes: int) -> dict[str, object]:
    """A worst-case placeholder for the evidence _ef_designer_evidence builds for `path`.

    Same keys and nesting, both sides present, and every variable-width field at
    its EF_BOUND_* width, so its canonical encoding is at least as long as the real
    entry's whenever the real fields fit those widths (see python/README.md).
    """
    count = int("9" * EF_BOUND_COUNT_DIGITS)
    side = {"blob_sha": "0" * 40, "bytes": count, "content_sha256": "0" * 64,
            "migration_id": "x" * EF_BOUND_MIGRATION_ID_BYTES,
            "product_version": "x" * EF_BOUND_PRODUCT_VERSION_BYTES,
            "entity_types": count, "properties": count, "indexes": count,
            "foreign_keys": count, "tables": count}
    return {"path": path, "kind": "ef-core-migration-designer",
            "source_diff_bytes": source_diff_bytes, "base": dict(side), "head": dict(side)}


def _ef_designer_evidence(
    repo: Path, base: str, head: str, path: str, source_diff_bytes: int,
) -> dict[str, object] | None:
    if not ef_designer_path(path):
        return None
    base_blob = _blob_at(repo, base, path)
    head_blob = _blob_at(repo, head, path)
    probe = head_blob or base_blob
    if probe is None:
        raise GenerationError("changed path has no Git blob")
    first_lines = b"\n".join(probe[1][:8192].splitlines()[:5])
    if (b"<auto-generated" not in first_lines
            or b"BuildTargetModel" not in probe[1]
            or MIGRATION_ID_RE.search(probe[1]) is None):
        return None
    return {
        "path": path,
        "kind": "ef-core-migration-designer",
        "source_diff_bytes": source_diff_bytes,
        "base": _ef_designer_side(base_blob),
        "head": _ef_designer_side(head_blob),
    }


def _whole_file_deletion_evidence(
    repo: Path, base: str, path: str, source_diff_bytes: int,
) -> dict[str, object]:
    """Bounded evidence for a path the range deletes outright: its base blob, and a head that is null because the status is `D`."""
    blob = _blob_at(repo, base, path)
    if blob is None:
        raise GenerationError("deleted path has no base blob")
    raw = blob[1]
    line_count = raw.count(b"\n") + (1 if raw and not raw.endswith(b"\n") else 0)
    return {
        "path": path,
        "kind": "whole-file-deletion",
        "source_diff_bytes": source_diff_bytes,
        "base": {**_blob_identity(blob), "line_count": line_count},
        "head": None,
    }


def _parse_numstat(raw: bytes) -> dict[str, int]:
    position = 0
    files = insertions = deletions = 0
    while position < len(raw):
        first = raw.find(b"\t", position)
        second = raw.find(b"\t", first + 1) if first >= 0 else -1
        end = raw.find(b"\0", second + 1) if second >= 0 else -1
        if min(first, second, end) < 0:
            raise GenerationError("malformed Git numstat")
        added, removed = raw[position:first], raw[first + 1 : second]
        for value, label in ((added, "insertions"), (removed, "deletions")):
            if value == b"-":
                amount = 0
            elif value and all(48 <= byte <= 57 for byte in value):
                amount = int(value)
            else:
                raise GenerationError("malformed Git numstat count")
            if label == "insertions":
                insertions += amount
            else:
                deletions += amount
        path = raw[second + 1 : end]
        position = end + 1
        if not path:
            old_end = raw.find(b"\0", position)
            new_end = raw.find(b"\0", old_end + 1) if old_end >= 0 else -1
            if min(old_end, new_end) < 0:
                raise GenerationError("malformed Git rename numstat")
            position = new_end + 1
        files += 1
    return {
        "files_changed": files,
        "insertions": insertions,
        "deletions": deletions,
    }


def _commits(repo: Path, base: str, head: str) -> list[dict[str, str]]:
    try:
        listed = original_range(repo, base, head, topological=False)
    except HistoryError as exc:
        raise GenerationError("invalid original history") from exc
    commits: list[dict[str, str]] = []
    for sha in listed:
        if SHA_RE.fullmatch(sha) is None:
            raise GenerationError("malformed Git commit list")
        commits.append({"sha": sha, "subject": commit_subject(repo, sha)})
    return commits
