"""Strict `MAJOR.MINOR.PATCH` versions, shared by the platform manifest, the release
adapters and the release profiles.
"""

import re

# D9: strict `MAJOR.MINOR.PATCH` only. No pre-release, no build metadata, no
# leading `v`, no leading zeros, no fourth component.
SEMVER_PATTERN = re.compile(r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)")


def parse_semver(value: object) -> tuple[int, int, int] | None:
    """The `(major, minor, patch)` triple, or None when `value` is not strict.

    None is the whole vocabulary for "not a version" (D9): a pre-release or
    build-metadata suffix, a leading `v`, a fourth component and a leading zero
    all return it, so no caller can accept a looser spelling by accident.
    """
    if not isinstance(value, str):
        return None
    match = SEMVER_PATTERN.fullmatch(value)
    if match is None:
        return None
    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


def compare_semver(a: str, b: str) -> int:
    """-1, 0 or 1 by tuple comparison over the two parsed triples.

    Both arguments must already parse; an unparseable one is a programming
    error here, not an authored one, because shape validation is the caller's
    job and has already run.
    """
    left = parse_semver(a)
    right = parse_semver(b)
    if left is None or right is None:
        raise ValueError("compare_semver requires two strict SemVer strings")
    return (left > right) - (left < right)
