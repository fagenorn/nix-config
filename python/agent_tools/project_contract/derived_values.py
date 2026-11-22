"""The four values a schema-3 contract does not author, derived from the repository.

A schema-3 contract leaves out the project id, the tracker repository slug, the
merge's required checks and the platform interval, because the repository
already states each of them (ADR-project-contract-014):

- `/project/id` and `/bindings/tracker/repo_slug`: the `owner/repo` of the git
  remote `origin`, read from the repository's git config. A linked worktree's
  `.git` file points at a gitdir whose `commondir` names the config that holds
  the remote. `include`, `includeIf` and `url.*.insteadOf` are not followed.
- `/bindings/vcs/merge/required_checks`: the `context` of each entry of
  `required_status_checks.checks` in `.github/branch-protection.json`, in file
  order. A `null` `required_status_checks` is no required check, and the value
  is then left out.
- `/platform`: `[X.Y.Z, (X+1).0.0)` for the `platform_version` of the platform
  manifest. A tree that carries the manifest (the platform's own) reads its own;
  every other repository reads the manifest of the revision its `devenv.lock`
  pins as the `agent-platform` input, found in the Nix store at the path Nix
  computes from the locked `narHash`.

The module reads files and nothing else: it starts no child process and opens
no connection, and it reads each through a nonblocking regular-file open, so a
FIFO at a source path is refused instead of waited on. Every helper raises `Underivable` carrying a message that names
its source (`git remote origin`, `git config`, `.github/branch-protection.json`,
`devenv.lock`, `Nix store`, `platform manifest`) and never an absolute path;
`derive` is the only function that turns them into violations and it never
raises. It is imported, never run, and imports no resolver.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
from pathlib import Path
from typing import NamedTuple

from agent_tools.project_contract.agent_platform import read_regular_file
from agent_tools.system.semver import parse_semver

STORE_DIR = "/nix/store"
REMOTE = "origin"
PROTECTION_SOURCE = ".github/branch-protection.json"
LOCK_SOURCE = "devenv.lock"
LOCK_INPUT = "agent-platform"
TREE_MANIFEST = "home/common/agent-skills/platform-manifest.json"

PROJECT_ID = "/project/id"
REPO_SLUG = "/bindings/tracker/repo_slug"
REQUIRED_CHECKS = "/bindings/vcs/merge/required_checks"
PLATFORM = "/platform"
POINTERS = (PROJECT_ID, REPO_SLUG, REQUIRED_CHECKS, PLATFORM)

# The files of a tree `derive` reads besides the git config, which only a checkout holds.
# A scratch export of a pinned commit carries these (`contract_export`) and is given the
# checkout's origin remote (`adopt_inspection.seed_origin`).
INPUT_PATHS = (PROTECTION_SOURCE, LOCK_SOURCE, TREE_MANIFEST)

NIX_BASE32 = "0123456789abcdfghijklmnpqrsvwxyz"


ESCAPES = {"n": "\n", "t": "\t", "b": "\b", "\\": "\\", '"': '"'}


def read_text(path: Path) -> str:
    """The text of the regular file at `path`; a FIFO or other kind raises `OSError`, never blocks."""
    return read_regular_file(path).decode("utf-8")


class Derived(NamedTuple):
    values: dict[str, object]
    violations: list[dict]


NONE = Derived({}, [])


class Underivable(Exception):
    """A value the repository's files cannot state."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


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


# --------------------------------------------------------------------------
# The remote
# --------------------------------------------------------------------------

GIT_CONFIG_UNREADABLE = "cannot be derived: the repository's git config could not be read"


def git_config_path(root: Path) -> Path:
    """The git config that holds the remote, following a linked worktree's gitdir."""
    try:
        dot_git = root / ".git"
        if dot_git.is_dir():
            return dot_git / "config"
        if dot_git.is_file():
            first = read_text(dot_git).split("\n", 1)[0]
            if first.startswith("gitdir: "):
                gitdir = root / first[len("gitdir: "):].strip()
                commondir = gitdir / "commondir"
                if commondir.is_file():
                    common = gitdir / read_text(commondir).strip()
                    return common / "config"
                return gitdir / "config"
    except (OSError, UnicodeDecodeError):
        pass
    raise Underivable(GIT_CONFIG_UNREADABLE)


def _header(line: str) -> tuple[str, str | None]:
    """The `(name, subsection)` of a `[name "sub"]` header; a plain header has None."""
    inner = line[1:line.find("]")] if "]" in line else line[1:]
    name, quote, rest = inner.strip().partition('"')
    if not quote:
        return inner.strip().lower(), None
    sub = rest.rsplit('"', 1)[0]
    return name.strip().lower(), sub


def _value(raw: str) -> str:
    """The value text of a config line as git reads it.

    An unquoted `#` or `;` starts a comment wherever it stands, a double quote
    toggles quoting anywhere in the value, a backslash escapes only `n`, `t`,
    `b`, `\\` and `"`, and whitespace around the value is dropped. A bad escape,
    a backslash that ends the line (a continuation) and an unterminated quote are
    a config git refuses, so they raise `Underivable`.
    """
    unreadable = Underivable(GIT_CONFIG_UNREADABLE)
    text = raw.lstrip()
    out: list[str] = []
    kept = 0
    quoted = False
    index = 0
    while index < len(text):
        char = text[index]
        index += 1
        if char == "\\":
            if index >= len(text) or text[index] not in ESCAPES:
                raise unreadable
            out.append(ESCAPES[text[index]])
            index += 1
            kept = len(out)
        elif char == '"':
            quoted = not quoted
        elif not quoted and char in "#;":
            break
        else:
            out.append(char)
            if quoted or not char.isspace():
                kept = len(out)
    if quoted:
        raise unreadable
    return "".join(out[:kept])


def origin_url(config_text: str) -> str | None:
    """The first `url` of the `[remote "origin"]` section, else None."""
    in_origin = False
    for line in config_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped[0] in "#;":
            continue
        if stripped.startswith("["):
            name, sub = _header(stripped)
            in_origin = name == "remote" and sub == REMOTE
            continue
        if not in_origin:
            continue
        key, separator, value = stripped.partition("=")
        if separator and key.strip().lower() == "url":
            return _value(value)
    return None


def remote_slug(root: Path) -> str:
    """The `owner/repo` of the remote `origin`."""
    path = git_config_path(root)
    try:
        text = read_text(path)
    except (OSError, UnicodeDecodeError):
        raise Underivable(GIT_CONFIG_UNREADABLE) from None
    url = origin_url(text)
    if url is None:
        raise Underivable("cannot be derived: the git remote origin has no url")
    slug = normalize_remote_url(url)
    if slug is None:
        raise Underivable(
            "cannot be derived: the git remote origin url is not a recognised owner/repo spelling")
    return slug


# --------------------------------------------------------------------------
# The required checks
# --------------------------------------------------------------------------


def required_checks(root: Path) -> list[str]:
    """The contexts of the branch protection's required checks, in file order."""
    try:
        text = read_text(root / PROTECTION_SOURCE)
    except OSError:
        raise Underivable(f"cannot be derived: {PROTECTION_SOURCE} could not be read") from None
    except UnicodeDecodeError:
        raise Underivable(f"cannot be derived: {PROTECTION_SOURCE} is not valid JSON") from None
    try:
        document = json.loads(text)
    except (ValueError, RecursionError):
        raise Underivable(f"cannot be derived: {PROTECTION_SOURCE} is not valid JSON") from None
    refusal = Underivable(
        f"cannot be derived: {PROTECTION_SOURCE} does not list "
        "required_status_checks.checks[].context")
    if not isinstance(document, dict) or "required_status_checks" not in document:
        raise refusal
    section = document["required_status_checks"]
    if section is None:
        return []
    if not isinstance(section, dict) or not isinstance(section.get("checks"), list):
        raise refusal
    contexts: list[str] = []
    for entry in section["checks"]:
        context = entry.get("context") if isinstance(entry, dict) else None
        if not isinstance(context, str) or not context or context in contexts:
            raise refusal
        contexts.append(context)
    return contexts


# --------------------------------------------------------------------------
# The platform interval
# --------------------------------------------------------------------------

NO_NAR_HASH = f"cannot be derived: {LOCK_SOURCE} has no {LOCK_INPUT} input with a narHash"


def store_path(nar_hash: str, store_dir: str) -> str:
    """The store path Nix computes for a source locked at `nar_hash`."""
    prefix = "sha256-"
    try:
        if not nar_hash.startswith(prefix):
            raise ValueError(nar_hash)
        digest = base64.b64decode(nar_hash[len(prefix):], validate=True)
        if len(digest) != 32:
            raise ValueError(nar_hash)
    except (ValueError, binascii.Error):
        raise Underivable(NO_NAR_HASH) from None
    fingerprint = f"source:sha256:{digest.hex()}:{store_dir}:source"
    folded = bytearray(20)
    for index, byte in enumerate(hashlib.sha256(fingerprint.encode("ascii")).digest()):
        folded[index % 20] ^= byte
    length = (20 * 8 - 1) // 5 + 1
    chars = []
    for index in range(length - 1, -1, -1):
        bit = index * 5
        j, k = divmod(bit, 8)
        value = (folded[j] >> k) | ((folded[j + 1] << (8 - k)) if j + 1 < 20 else 0)
        chars.append(NIX_BASE32[value & 31])
    return f"{store_dir}/{''.join(chars)}-source"


def platform_range(version: str) -> dict:
    """`[X.Y.Z, (X+1).0.0)` for the version `X.Y.Z`."""
    parsed = parse_semver(version)
    if parsed is None:
        raise Underivable("cannot be derived: the platform manifest version is not X.Y.Z")
    return {"min_inclusive": version, "max_exclusive": f"{parsed[0] + 1}.0.0"}


def _manifest_version(tree: Path, where: str) -> str:
    refusal = Underivable(f"cannot be derived: the platform manifest of {where} could not be read")
    try:
        document = json.loads(read_text(tree / TREE_MANIFEST))
    except (OSError, ValueError, RecursionError):
        raise refusal from None
    version = document.get("platform_version") if isinstance(document, dict) else None
    if parse_semver(version) is None:
        raise refusal
    return version


def _locked_nar_hash(root: Path) -> str:
    try:
        text = read_text(root / LOCK_SOURCE)
    except OSError:
        raise Underivable(f"cannot be derived: {LOCK_SOURCE} could not be read") from None
    except UnicodeDecodeError:
        raise Underivable(f"cannot be derived: {LOCK_SOURCE} is not valid JSON") from None
    try:
        lock = json.loads(text)
    except (ValueError, RecursionError):
        raise Underivable(f"cannot be derived: {LOCK_SOURCE} is not valid JSON") from None
    try:
        key = lock["nodes"][lock["root"]]["inputs"][LOCK_INPUT]
        nar = lock["nodes"][key]["locked"]["narHash"]
    except (LookupError, TypeError):
        raise Underivable(NO_NAR_HASH) from None
    if not isinstance(key, str) or not isinstance(nar, str):
        raise Underivable(NO_NAR_HASH)
    return nar


def platform_interval(root: Path) -> dict:
    """The platform interval of this tree's manifest, else of the locked revision's."""
    if os.path.lexists(root / TREE_MANIFEST):
        return platform_range(_manifest_version(root, "this tree"))
    source = Path(store_path(_locked_nar_hash(root), STORE_DIR))
    if not source.is_dir():
        raise Underivable(
            "cannot be derived: the locked agent-platform revision is not in the Nix store")
    return platform_range(_manifest_version(source, "the locked agent-platform revision"))


# --------------------------------------------------------------------------
# All four
# --------------------------------------------------------------------------


def derive(root: Path) -> Derived:
    """Every value the repository states, and a violation for each it cannot."""
    values: dict[str, object] = {}
    violations: list[dict] = []

    def refuse(pointers: tuple[str, ...], section: str, error: Underivable) -> None:
        for pointer in pointers:
            violations.append({
                "pointer": pointer,
                "message": error.message,
                "repair_id": f"contract.{section}.not_derivable",
            })

    try:
        slug = remote_slug(root)
    except Underivable as error:
        refuse((REPO_SLUG,), "tracker", error)
        refuse((PROJECT_ID,), "project", error)
    else:
        values[PROJECT_ID] = slug
        values[REPO_SLUG] = slug
    try:
        checks = required_checks(root)
    except Underivable as error:
        refuse((REQUIRED_CHECKS,), "vcs", error)
    else:
        if checks:
            values[REQUIRED_CHECKS] = checks
    try:
        values[PLATFORM] = platform_interval(root)
    except Underivable as error:
        refuse((PLATFORM,), "platform", error)
    return Derived(values, violations)
