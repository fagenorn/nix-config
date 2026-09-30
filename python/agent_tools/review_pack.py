"""Deterministic whole-record review-package packing and in-memory metrics."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
from typing import Literal, Mapping, Sequence


class ReviewPackError(Exception):
    """A caller supplied an invalid review record or packing request."""


@dataclass(frozen=True)
class ReviewLimits:
    root_max_bytes: int
    member_max_bytes: int
    max_members: int
    aggregate_max_bytes: int

    def __post_init__(self) -> None:
        for value in (self.root_max_bytes, self.member_max_bytes,
                      self.max_members, self.aggregate_max_bytes):
            _integer(value, "review limit")


@dataclass(frozen=True)
class ReviewRecord:
    path: str
    payload: bytes
    source_bytes: int
    generated_evidence: Mapping[str, object] | None

    def __post_init__(self) -> None:
        _path(self.path)
        if type(self.payload) is not bytes:
            raise ReviewPackError("record payload is not bytes")
        _integer(self.source_bytes, "record source bytes")
        if self.generated_evidence is not None and not isinstance(
            self.generated_evidence, Mapping
        ):
            raise ReviewPackError("record generated evidence is not a mapping")

    @property
    def review_bytes(self) -> int:
        return len(self.payload)


@dataclass(frozen=True)
class ReviewRecordSize:
    """An ordinary whole-record length for measurement, never a publishable payload."""
    path: str
    review_bytes: int

    def __post_init__(self) -> None:
        _path(self.path)
        _integer(self.review_bytes, "record review bytes")

    @property
    def source_bytes(self) -> int:
        return self.review_bytes

    @property
    def generated_evidence(self) -> None:
        return None


def _integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ReviewPackError(f"invalid {label}")
    return value


def _path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ReviewPackError("invalid record path")
    parsed = PurePosixPath(value)
    if (parsed.is_absolute() or str(parsed) != value or value == "."
            or any(part in {".", ".."} for part in parsed.parts)):
        raise ReviewPackError("invalid record path")
    return value


def canonical_manifest(value: object) -> bytes:
    """Encode a review manifest with the producer's existing wire format."""
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def pack_whole_records(
    records: Sequence[ReviewRecord],
    ceiling: int,
    *,
    strategy: Literal["sequential", "stable-first-fit-whole-file"],
) -> tuple[bytes, ...]:
    """Pack complete record payloads in the selected deterministic strategy."""
    checked = tuple(records)
    if any(not isinstance(record, ReviewRecord) for record in checked):
        raise ReviewPackError("invalid review record")
    if len({record.path for record in checked}) != len(checked):
        raise ReviewPackError("duplicate record path")
    placement = place_record_sizes(tuple(record.review_bytes for record in checked), ceiling, strategy=strategy)
    return tuple(b"".join(checked[index].payload for index in shard) for shard in placement)


def place_record_sizes(
    sizes: Sequence[int], ceiling: int, *,
    strategy: Literal["sequential", "stable-first-fit-whole-file"],
) -> tuple[tuple[int, ...], ...]:
    """Place whole records once, independent of whether their bytes are materialized."""
    _integer(ceiling, "ceiling")
    if strategy not in {"sequential", "stable-first-fit-whole-file"}:
        raise ReviewPackError("invalid packing strategy")
    checked = tuple(_integer(size, "record size") for size in sizes)
    if strategy == "sequential":
        return _sequential(checked, ceiling)
    return _stable_first_fit(checked, ceiling)


def _sequential(sizes: Sequence[int], ceiling: int) -> tuple[tuple[int, ...], ...]:
    shards: list[tuple[int, ...]] = []
    current: list[int] = []
    current_size = 0
    for index, size in enumerate(sizes):
        if current and current_size + size > ceiling:
            shards.append(tuple(current))
            current = []
            current_size = 0
        current.append(index)
        current_size += size
        if current_size > ceiling:
            shards.append(tuple(current))
            current = []
            current_size = 0
    if current:
        shards.append(tuple(current))
    return tuple(shards)


def _stable_first_fit(
    records: Sequence[int], ceiling: int
) -> tuple[tuple[int, ...], ...]:
    shards: list[list[int]] = []
    sizes: list[int] = []
    for record, amount in enumerate(records):
        for index, size in enumerate(sizes):
            if size + amount <= ceiling:
                shards[index].append(record)
                sizes[index] += amount
                break
        else:
            shards.append([record])
            sizes.append(amount)
    return tuple(tuple(shard) for shard in shards)


def measure_candidate(
    manifest: Mapping[str, object],
    shards: Sequence[bytes],
    limits: ReviewLimits,
) -> tuple[Mapping[str, int], str, tuple[str, ...]]:
    """Measure package bytes with artifact-budget's closed violation order."""
    if not isinstance(manifest, Mapping):
        raise ReviewPackError("manifest is not a mapping")
    raw_members = tuple(shards)
    if any(type(member) is not bytes for member in raw_members):
        raise ReviewPackError("member is not bytes")
    return measure_lengths(len(canonical_manifest(manifest)), tuple(map(len, raw_members)), limits)


def measure_lengths(
    root_bytes: int, member_sizes: Sequence[int], limits: ReviewLimits,
) -> tuple[Mapping[str, int], str, tuple[str, ...]]:
    """Apply the common metric and violation rules to exact encoded lengths."""
    root_bytes = _integer(root_bytes, "root bytes")
    member_sizes = tuple(_integer(size, "member bytes") for size in member_sizes)
    try:
        root_max = _integer(getattr(limits, "root_max_bytes"), "root limit")
        member_max = _integer(getattr(limits, "member_max_bytes"), "member limit")
        max_members = _integer(getattr(limits, "max_members"), "member count limit")
        aggregate_max = _integer(
            getattr(limits, "aggregate_max_bytes"), "aggregate limit"
        )
    except AttributeError as exc:
        raise ReviewPackError("invalid artifact limits") from exc
    metrics = {
        "root_bytes": root_bytes,
        "total_bytes": root_bytes + sum(member_sizes),
        "file_count": 1 + len(member_sizes),
        "largest_member_bytes": max(member_sizes, default=0),
    }
    violations = tuple(
        name for name, exceeds in (
            ("root_bytes", root_bytes > root_max),
            ("member_bytes", metrics["largest_member_bytes"] > member_max),
            ("member_count", len(member_sizes) > max_members),
            ("aggregate_bytes", metrics["total_bytes"] > aggregate_max),
        ) if exceeds
    )
    return metrics, "over_budget" if violations else "within_budget", violations
