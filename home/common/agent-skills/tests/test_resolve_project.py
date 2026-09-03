"""Contract tests for scripts/resolve-project.

Runs the resolver as a subprocess against temporary repository roots and parses
its stdout, the seam established by test_resolve_bindings.py and
test_workflow_state.py. The resolver is imported only by the two cases whose
seam no subprocess run can reach — the generic failure wrapper and the
emit-side non-finite guard — through the shared `load_module` below.
"""

from __future__ import annotations

import contextlib
import copy
import io
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve-project.py"
LIBRARY = Path(__file__).resolve().parents[1] / "scripts" / "agent_platform.py"
MANIFEST = Path(__file__).resolve().parents[1] / "platform-manifest.json"
REPO_ROOT = Path(__file__).resolve().parents[4]

# `install_home`'s default: copy the committed manifest verbatim. A distinct
# sentinel because `None` already means "install no manifest at all".
COMMITTED = object()

CAPABILITY_NAMES = (
    "tracker", "worktrees", "knowledge.context", "knowledge.standards",
    "knowledge.architecture", "knowledge.hints", "verification",
    "review.plan", "review.code", "release", "deploy",
)
BINDING_NAMESPACES = ("vcs", "tracker", "paths", "commands", "workflow", "deploy")
CAPABILITY_STATES = ("available", "unsupported", "blocked")


def install_home(home: Path, manifest: object = COMMITTED, *,
                 library: bool = True) -> Path:
    """Populate `home` as the platform installation the resolver reads (D23).

    Every invocation in this suite runs under a temporary `HOME`, so the
    library and the manifest have to be materialized there: the resolver
    imports `agent_platform` from `$HOME/.agents/lib/python` and loads the
    manifest from `$HOME/.agents/share`, with no fallback path either side.

    `manifest` is the override hook: `COMMITTED` copies the repository's own
    manifest byte for byte, `None` installs none at all, a `str` is written
    verbatim (for the malformed-JSON cases) and anything else is serialized as
    JSON. `library=False` leaves the library uninstalled, which only a script
    run from the deployed layout can observe (see `PlatformLibraryTest`).
    """
    library_dir = home / ".agents" / "lib" / "python"
    library_dir.mkdir(parents=True, exist_ok=True)
    installed_library = library_dir / "agent_platform.py"
    installed_library.unlink(missing_ok=True)
    if library:
        shutil.copy(LIBRARY, installed_library)
    share = home / ".agents" / "share"
    share.mkdir(parents=True, exist_ok=True)
    target = share / "platform-manifest.json"
    target.unlink(missing_ok=True)
    if manifest is COMMITTED:
        shutil.copy(MANIFEST, target)
    elif manifest is None:
        pass
    elif isinstance(manifest, str):
        target.write_text(manifest, encoding="utf-8")
    else:
        target.write_text(json.dumps(manifest), encoding="utf-8")
    return home


def make_home(manifest: object = COMMITTED, *, library: bool = True) -> Path:
    return install_home(Path(tempfile.mkdtemp()).resolve(), manifest,
                        library=library)


def registry(*entries: dict) -> dict:
    """The fleet registry document naming `entries`, in the order given.

    The file's shape is the design's, not the reader's: two members, and each
    entry exactly `{project_id, root}` (D18). Task 6 owns the writer; the suite
    stages this file by hand so the read side can be exercised before it
    exists.
    """
    return {"schema_version": 1, "projects": list(entries)}


def install_registry(home: Path, content: object) -> Path:
    """Write `$HOME/.agents/state/fleet/registry.json` and return its path.

    A `str` is written verbatim, for the malformed cases; anything else is
    serialized as JSON.
    """
    path = home / ".agents" / "state" / "fleet" / "registry.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return path


def library_members() -> tuple[str, ...]:
    """The resolver's declared `PLATFORM_LIBRARY_MEMBERS`, read from its source.

    Read rather than copied: a second literal here would drift from the one
    the guard actually enforces, which is the failure this suite is about.
    """
    text = SCRIPT.read_text("utf-8")
    body = text.split("PLATFORM_LIBRARY_MEMBERS = (", 1)[1].split(")", 1)[0]
    return tuple(re.findall(r'"([^"]+)"', body))


def committed_manifest() -> dict:
    return json.loads(MANIFEST.read_text("utf-8"))


def mutated_manifest(**changes: object) -> dict:
    manifest = committed_manifest()
    manifest.update(changes)
    return manifest


MANIFEST_MEMBERS = (
    "schema_version", "platform_version", "project_schema_versions",
    "resolved_schema_version", "migrations", "deprecations", "removals",
)
SUBCOMMANDS = ("resolve", "check-projections", "write-projections",
               "platform-status")


def run(*args: str, home: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
        env={**os.environ, "HOME": str(home)},
    )
    return proc.returncode, proc.stdout, proc.stderr


def git(root: Path, *args: str) -> str:
    """Run git in `root` with a hermetic identity and return its stdout."""
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True, text=True, timeout=60, check=True,
        env=dict(
            os.environ,
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_CONFIG_SYSTEM=os.devnull,
            GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
            GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
        ),
    )
    return proc.stdout


def tree_snapshot(root: Path) -> list[tuple[str, str, int | None]]:
    """Every path under `root` outside `.git`, with its type and file mtime.

    Directories are included so that creating an empty one is caught; `.git`
    is excluded because git's own bookkeeping is not the resolver's writing.
    """
    out = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        kind = "d" if path.is_dir() else "f"
        out.append((
            str(path.relative_to(root)), kind,
            None if kind == "d" else path.stat().st_mtime_ns,
        ))
    return out


def assert_read_only(case: unittest.TestCase, root: Path,
                     expected_code: int, *args: str) -> None:
    """Assert the resolver invocation `args` writes nothing under `root`.

    Three independent witnesses, because each misses what the others catch:
    `git status --porcelain` bytes catch a tracked-content or index change, the
    recursive path/type set catches a created empty directory, and the file
    mtimes catch a rewrite with identical bytes (SF-001, AC-5).
    """
    git(root, "add", "-A")
    git(root, "commit", "--quiet", "-m", "fixture")
    before_status = git(root, "status", "--porcelain")
    before_tree = tree_snapshot(root)
    code, _, err = run(*args, "--repo-root", str(root), home=case.home)
    case.assertEqual(code, expected_code, err)
    case.assertEqual(git(root, "status", "--porcelain"), before_status)
    case.assertEqual(tree_snapshot(root), before_tree)


def source_contract() -> dict:
    return json.loads((REPO_ROOT / ".agents" / "project.json").read_text("utf-8"))


CODEX_HEADER = (
    "<!-- generated by resolve-project from .agents/instructions/bootstrap.md "
    "(project schema 1). Do not edit; edit the source and run "
    "`resolve-project write-projections`. -->"
)
MANAGED_LINE = "@.agents/instructions/bootstrap.md"


class ResolverTestCase(unittest.TestCase):
    def setUp(self) -> None:
        # Every subcommand loads the installed manifest before it looks at the
        # repository (R1.3), so a case without one on disk would refuse
        # `resolver_failure` whatever else it meant to exercise.
        self.home = make_home()

    def set_manifest(self, manifest: object) -> None:
        """Replace this case's installed manifest with the fixture given."""
        install_home(self.home, manifest)

    def make_root(self, contract: object | None = None, *,
                  projections: bool = True) -> Path:
        """A temp root holding a valid contract, its instruction source, and —
        unless `projections=False` — both projection targets rendered current.

        `resolve` refuses a drifted projection before it reaches anything else
        (D10), so a root without current targets would refuse for a reason no
        caller here means to exercise. Only the cases that must start from an
        unwritten state opt out.
        """
        # `.resolve()` because the platform temp dir is reached through a
        # symlink on macOS (/var -> /private/var) while the resolver's own
        # root is always the physical path; without it every `str(root)`
        # comparison below would compare two spellings of one directory.
        root = Path(tempfile.mkdtemp()).resolve()
        git(root, "init", "--quiet")
        (root / "home" / "common" / "agent-skills" / "standards").mkdir(parents=True)
        (root / ".out-of-scope").mkdir()
        (root / ".worktrees").mkdir()
        (root / ".agents" / "instructions").mkdir(parents=True)
        (root / ".agents" / "instructions" / "bootstrap.md").write_text(
            "# invariants\n", encoding="utf-8")
        if contract is None:
            contract = source_contract()
        if contract is not False:
            (root / ".agents" / "project.json").write_text(
                json.dumps(contract), encoding="utf-8")
        body = "# authored body\n"
        if projections:
            source = (root / ".agents" / "instructions" / "bootstrap.md").read_bytes()
            (root / "AGENTS.md").write_bytes(
                CODEX_HEADER.encode() + b"\n\n" + source)
            body += MANAGED_LINE + "\n"
        (root / "CLAUDE.md").write_text(body, encoding="utf-8")
        return root

    def resolve(self, root: Path, *extra: str) -> tuple[int, object, str]:
        code, out, err = run("resolve", "--repo-root", str(root), *extra,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err


class SnapshotShapeTest(ResolverTestCase):
    def test_resolve_returns_exactly_four_top_level_members(self):
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(
            sorted(snap), ["bindings", "capabilities", "project", "schema_version"])
        self.assertEqual(snap["schema_version"], 1)
        self.assertEqual(sorted(snap["project"]), ["id", "name", "root"])
        self.assertEqual(sorted(snap["bindings"]), sorted(BINDING_NAMESPACES))
        self.assertEqual(sorted(snap["capabilities"]), sorted(CAPABILITY_NAMES))
        for name, entry in snap["capabilities"].items():
            with self.subTest(capability=name):
                self.assertEqual(sorted(entry), ["reason_code", "repair_id", "state"])
                self.assertIn(entry["state"], CAPABILITY_STATES)

    def test_identity_is_copied_verbatim_from_the_source(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["project"]["id"], "fagenorn/nix-config")
        self.assertEqual(snap["project"]["name"], "nix-config")
        self.assertEqual(snap["project"]["root"], str(root.resolve()))

    def test_unsupported_capabilities_carry_null_reason_and_repair(self):
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        for name in ("release", "deploy", "knowledge.context", "knowledge.hints"):
            with self.subTest(capability=name):
                entry = snap["capabilities"][name]
                self.assertEqual(entry["state"], "unsupported")
                self.assertIsNone(entry["reason_code"])
                self.assertIsNone(entry["repair_id"])

    def test_two_runs_emit_byte_identical_stdout(self):
        root = self.make_root()
        first = run("resolve", "--repo-root", str(root), home=self.home)
        second = run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")


class NormalizationTest(ResolverTestCase):
    def test_every_path_is_absolute_under_project_root(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        paths = snap["bindings"]["paths"]
        candidates = [paths["artifacts"]["specs"], paths["artifacts"]["plans"]]
        for key in ("context", "standards", "architecture", "operations",
                    "hints", "rejections"):
            candidates.extend(paths[key])
        candidates.extend(c["cwd"] for c in snap["bindings"]["commands"].values())
        for value in candidates:
            with self.subTest(path=value):
                self.assertTrue(Path(value).is_absolute())
                self.assertTrue(
                    value == str(root.resolve())
                    or value.startswith(str(root.resolve()) + "/"))

    def test_the_source_file_keeps_its_relative_values(self):
        """D30: exactly what the name promises, and no literal path.

        The authored value stays relative — not absolute, no leading `/`, no
        `..` segment — and the snapshot's value is that same path joined to the
        project root. Pinning a literal directory here would instead make this
        case fail the moment an artifact directory is relocated, which is a
        move the contract is meant to absorb.
        """
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        on_disk = json.loads((root / ".agents" / "project.json").read_text("utf-8"))
        for name in ("specs", "plans"):
            with self.subTest(artifacts=name):
                authored = on_disk["bindings"]["paths"]["artifacts"][name]
                self.assertIsInstance(authored, str)
                self.assertTrue(authored)
                self.assertFalse(authored.startswith("/"))
                self.assertFalse(Path(authored).is_absolute())
                self.assertNotIn("..", Path(authored).parts)
                self.assertEqual(
                    snap["bindings"]["paths"]["artifacts"][name],
                    str(root / authored))

    def test_non_path_binding_values_pass_through_unchanged(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        source = json.loads((root / ".agents" / "project.json").read_text("utf-8"))
        self.assertEqual(snap["bindings"]["vcs"], source["bindings"]["vcs"])
        self.assertEqual(snap["bindings"]["tracker"], source["bindings"]["tracker"])
        self.assertEqual(snap["bindings"]["workflow"], source["bindings"]["workflow"])


class ReadOnlyTest(ResolverTestCase):
    """AC-5: running the resolver leaves the working tree unchanged (SF-001)."""

    def test_resolve_leaves_the_tree_untouched(self):
        assert_read_only(self, self.make_root(), 0, "resolve")

    def test_a_refusing_resolve_leaves_the_tree_untouched(self):
        root = self.make_root()
        (root / ".agents" / "project.json").write_text("{", encoding="utf-8")
        assert_read_only(self, root, 2, "resolve")

    def test_platform_status_leaves_the_tree_untouched(self):
        assert_read_only(self, self.make_root(), 0, "platform-status")

    def test_a_refusing_platform_status_leaves_the_tree_untouched(self):
        root = self.make_root()
        (root / ".agents" / "project.json").write_text("{", encoding="utf-8")
        assert_read_only(self, root, 2, "platform-status")


class ErrorOutputTest(ResolverTestCase):
    def assert_refusal(self, code: int, payload: object, expected: str) -> dict:
        self.assertEqual(code, 2)
        self.assertIsInstance(payload, dict)
        self.assertEqual(sorted(payload), ["error"])
        self.assertNotIn("schema_version", payload)
        error = payload["error"]
        # D7: `reason_code` is a member of the error object exactly when the
        # code is `unsupported_schema`, and of no other refusal.
        self.assertEqual(
            sorted(error),
            ["code", "reason_code", "repair_id", "violations"]
            if expected == "unsupported_schema"
            else ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], expected)
        self.assertTrue(error["violations"])
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertEqual(pointers, sorted(pointers))
        for violation in error["violations"]:
            self.assertEqual(sorted(violation), ["message", "pointer"])
        return error

    def test_missing_contract_is_not_onboarded(self):
        root = self.make_root(contract=False)
        code, payload, _ = self.resolve(root)
        error = self.assert_refusal(code, payload, "not_onboarded")
        self.assertEqual(error["repair_id"], "onboarding.contract.missing")

    def test_repo_root_does_not_walk_up(self):
        root = self.make_root()
        nested = root / "sub" / "deeper"
        nested.mkdir(parents=True)
        code, payload, _ = self.resolve(nested)
        self.assert_refusal(code, payload, "not_onboarded")

    def test_non_json_contract_is_invalid_contract(self):
        root = self.make_root()
        (root / ".agents" / "project.json").write_text("{not json", encoding="utf-8")
        code, payload, _ = self.resolve(root)
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.parse")

    def test_a_non_finite_number_is_invalid_contract(self):
        """COR-001: Python's decoder accepts bare `NaN`; the contract does not.

        `bindings.deploy.config` is an unconstrained dict, so no later shape
        rule would have stopped the token: it would reach the snapshot and be
        re-emitted as JSON no standards parser can read. The refusal is the
        closed `invalid_contract`, not `resolver_failure`.
        """
        expected = (".agents/project.json holds NaN, Infinity or -Infinity, "
                    "which JSON has no value for")
        for token, value in (("NaN", float("nan")),
                             ("Infinity", float("inf")),
                             ("-Infinity", float("-inf"))):
            with self.subTest(token=token):
                contract = source_contract()
                contract["bindings"]["deploy"]["config"] = {"threshold": value}
                root = self.make_root(contract)
                # The fixture writes the contract with `json.dumps`, which
                # emits the bare token: assert the input really carries it.
                self.assertIn(
                    f": {token}}}",
                    (root / ".agents" / "project.json").read_text("utf-8"))
                code, payload, _ = self.resolve(root)
                error = self.assert_refusal(code, payload, "invalid_contract")
                self.assertEqual(error["repair_id"], "contract.parse")
                self.assertEqual(
                    [v["message"] for v in error["violations"]], [expected])

    def test_non_object_contract_is_invalid_contract(self):
        root = self.make_root(contract=[1, 2, 3])
        error = self.assert_refusal(*self.resolve(root)[:2], "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.parse")

    def test_missing_schema_version_is_invalid_contract(self):
        contract = source_contract()
        del contract["schema_version"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.schema_version.invalid")

    def test_boolean_schema_version_is_invalid_contract(self):
        contract = source_contract()
        contract["schema_version"] = True
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.schema_version.invalid")

    def test_other_integer_schema_version_is_unsupported_schema(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "unsupported_schema")
        self.assertEqual(error["repair_id"], "contract.schema_version.unsupported")

    def test_an_unknown_top_level_member_is_refused(self):
        contract = source_contract()
        contract["extra"] = {}
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assert_refusal(code, payload, "invalid_contract")

    def test_all_violations_are_reported_in_one_pass(self):
        contract = source_contract()
        del contract["bindings"]["deploy"]
        del contract["capabilities"]["release"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertIn("/bindings/deploy", pointers)
        self.assertIn("/capabilities/release", pointers)


class NoDefaultingTest(ResolverTestCase):
    def test_dropping_any_binding_namespace_refuses(self):
        for namespace in BINDING_NAMESPACES:
            with self.subTest(namespace=namespace):
                contract = source_contract()
                del contract["bindings"][namespace]
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")
                self.assertIn(f"/bindings/{namespace}",
                              [v["pointer"] for v in payload["error"]["violations"]])

    def test_dropping_any_capability_declaration_refuses(self):
        for name in CAPABILITY_NAMES:
            with self.subTest(capability=name):
                contract = source_contract()
                del contract["capabilities"][name]
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_a_dangling_command_id_refuses(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["verification"] = ["no-such-command"]
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_unsafe_authored_paths_refuse(self):
        for value in ("/etc", "../escape", "a/../../b"):
            with self.subTest(path=value):
                contract = source_contract()
                contract["bindings"]["paths"]["artifacts"]["plans"] = value
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_a_refusal_emits_no_snapshot_member(self):
        contract = source_contract()
        del contract["bindings"]["vcs"]
        code, out, _ = run("resolve", "--repo-root", str(self.make_root(contract)),
                           home=self.home)
        self.assertEqual(code, 2)
        for member in ("schema_version", "project", "bindings", "capabilities"):
            self.assertNotIn(f'"{member}"', out)


class MalformedValueTest(ResolverTestCase):
    """B-003: a wrongly typed or empty leaf is a violation, never a snapshot."""

    CASES = (
        ("/bindings/vcs/default_branch", ("bindings", "vcs", "default_branch"), None),
        ("/bindings/vcs/branch_pattern", ("bindings", "vcs", "branch_pattern"), ""),
        ("/bindings/vcs/kind", ("bindings", "vcs", "kind"), 1),
        ("/bindings/vcs/commit/signed", ("bindings", "vcs", "commit", "signed"), 1),
        ("/bindings/tracker/repo_slug", ("bindings", "tracker", "repo_slug"), []),
        ("/bindings/tracker/cli", ("bindings", "tracker", "cli"), ""),
        ("/bindings/deploy/adapter", ("bindings", "deploy", "adapter"), None),
    )

    def test_each_malformed_leaf_is_an_invalid_contract_violation(self):
        for pointer, path, bad in self.CASES:
            with self.subTest(pointer=pointer):
                source = source_contract()
                target = source
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = bad
                root = self.make_root(source)
                code, payload, _ = self.resolve(root)
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")
                self.assertIn(pointer,
                              [v["pointer"] for v in payload["error"]["violations"]])
                self.assertNotIn("schema_version", payload)


class CommandArgvTest(ResolverTestCase):
    """COR-002: every `argv` word is a non-empty string, at its own pointer.

    An empty `argv` list is already refused, and an empty word is the same
    break one level down: `[""]` names no executable, and an empty later word
    is an argument the callee cannot have meant.
    """

    CASES = (
        ("an empty executable", ["", "build"], 0),
        ("an empty later argument", ["just", ""], 1),
    )

    def test_an_empty_argv_word_is_an_invalid_contract_violation(self):
        for label, argv, index in self.CASES:
            with self.subTest(case=label):
                contract = source_contract()
                contract["bindings"]["commands"]["nix-build"]["argv"] = argv
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")
                self.assertIn(
                    f"/bindings/commands/nix-build/argv/{index}",
                    [v["pointer"] for v in payload["error"]["violations"]])

    def test_an_unreferenced_commands_entry_is_validated_too(self):
        """Validation walks every entry, not only the ids workflow names."""
        contract = source_contract()
        contract["bindings"]["commands"]["orphan"] = {
            "argv": [""], "cwd": ".", "env": []}
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertIn("/bindings/commands/orphan/argv/0",
                      [v["pointer"] for v in payload["error"]["violations"]])

    def test_a_non_string_argv_word_is_still_refused(self):
        contract = source_contract()
        contract["bindings"]["commands"]["nix-build"]["argv"] = ["just", 7]
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertIn("/bindings/commands/nix-build/argv/1",
                      [v["pointer"] for v in payload["error"]["violations"]])


class OnePassCollectionTest(ResolverTestCase):
    """B-004: `invalid_contract` reports every violation, `schema_version` included."""

    def test_an_invalid_schema_version_is_collected_with_the_others(self):
        source = source_contract()
        source["schema_version"] = "1"
        del source["bindings"]["deploy"]
        root = self.make_root(source)
        code, payload, _ = self.resolve(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        pointers = [v["pointer"] for v in payload["error"]["violations"]]
        self.assertIn("/schema_version", pointers)
        self.assertIn("/bindings/deploy", pointers)
        self.assertEqual(pointers, sorted(pointers))

    def test_an_unsupported_integer_version_short_circuits(self):
        source = source_contract()
        source["schema_version"] = 2
        del source["bindings"]["deploy"]
        root = self.make_root(source)
        code, payload, _ = self.resolve(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "unsupported_schema")
        self.assertEqual(
            [v["pointer"] for v in payload["error"]["violations"]],
            ["/schema_version"])

    def test_every_interval_shape_violation_joins_the_same_pass(self):
        """R2.2: the interval is validated with the rest, not on its own."""
        source = source_contract()
        source["platform"] = {"min_inclusive": "1.0", "max_exclusive": 7,
                              "extra": True}
        del source["bindings"]["deploy"]
        code, payload, _ = self.resolve(self.make_root(source))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        pointers = [v["pointer"] for v in payload["error"]["violations"]]
        for pointer in ("/bindings/deploy", "/platform/extra",
                        "/platform/max_exclusive", "/platform/min_inclusive"):
            self.assertIn(pointer, pointers)
        self.assertEqual(pointers, sorted(pointers))

    def test_an_inverted_interval_joins_the_same_pass(self):
        """The ordering violation needs both bounds to parse, so it is a
        separate case from the malformed-bound one above."""
        source = source_contract()
        source["platform"] = {"min_inclusive": "2.0.0",
                              "max_exclusive": "1.0.0"}
        del source["capabilities"]["release"]
        code, payload, _ = self.resolve(self.make_root(source))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        pointers = [v["pointer"] for v in payload["error"]["violations"]]
        self.assertIn("/capabilities/release", pointers)
        self.assertIn("/platform/max_exclusive", pointers)
        self.assertEqual(pointers, sorted(pointers))


class DiscoveryTest(ResolverTestCase):
    """SF-002: the nearest-ancestor walk taken without `--repo-root`."""

    def resolve_from(self, cwd: Path) -> tuple[int, object, str]:
        proc = subprocess.run(
            [sys.executable, str(SCRIPT), "resolve"],
            capture_output=True, text=True, timeout=60, cwd=str(cwd),
            env={**os.environ, "HOME": str(self.home)})
        try:
            payload: object = json.loads(proc.stdout)
        except json.JSONDecodeError:
            payload = None
        return proc.returncode, payload, proc.stderr

    def test_a_nested_directory_finds_the_nearest_ancestor(self):
        root = self.make_root()
        nested = root / "home" / "common" / "agent-skills" / "standards"
        code, snap, err = self.resolve_from(nested)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["project"]["root"], str(root))

    def test_no_contract_above_the_start_directory_is_not_onboarded(self):
        bare = Path(tempfile.mkdtemp())
        code, payload, _ = self.resolve_from(bare)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "not_onboarded")


class UsageErrorTest(ResolverTestCase):
    """SF-002: a missing subcommand is argparse's error, not JSON.

    `write-projections` left this list when Task 3 registered it, and
    `check-projections` when this task did (D18): every subcommand the
    resolver names is now implemented, so only the empty argv remains. A
    registered subcommand cannot stand in for one, because this case passes
    no `--repo-root` and would walk up from the runner's own directory onto
    the live checkout.
    """

    def test_an_unregistered_subcommand_exits_two_without_json(self):
        for args in ((),):
            with self.subTest(args=args):
                code, out, err = run(*args, home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(out, "")
                self.assertNotEqual(err, "")


def load_module():
    """The resolver as an imported module, loaded by path (its name is hyphenated).

    Reserved for the seams no subprocess run can reach: the generic failure
    wrapper, and the emit-side guard that the parse-side guard keeps unreachable
    from any authored contract. The importing case must already have pointed
    `HOME` at an installed platform, because the module resolves
    `agent_platform` from `$HOME/.agents/lib/python` as it loads.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("resolve_project", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InProcessTestCase(unittest.TestCase):
    """A temporary `HOME` for the two cases that import the resolver in process.

    `HOME` is patched on this process rather than a child's environment, and
    restored afterwards, because both the load-time library import and the
    manifest load inside `main` read it directly.
    """

    def setUp(self) -> None:
        self.home = make_home()
        previous = os.environ["HOME"]
        os.environ["HOME"] = str(self.home)
        self.addCleanup(os.environ.__setitem__, "HOME", previous)


class ResolverFailureTest(InProcessTestCase):
    """SF-002: the generic handler maps an unexpected exception to the closed code.

    No external input reaches this branch deterministically — every I/O and
    shape failure is already classified — so the seam is the wrapper itself.
    """

    def test_an_unexpected_exception_becomes_resolver_failure(self):
        module = load_module()
        original = module.load_contract
        # A sentinel no fixed refusal sentence can contain: the prescribed
        # message is "the resolver failed unexpectedly", so a shorter probe
        # like "unexpected" would match the message rather than the leak.
        module.load_contract = lambda root: (_ for _ in ()).throw(
            RuntimeError("sentinel-exception-detail"))
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                code = module.main(["resolve", "--repo-root", str(REPO_ROOT)])
        finally:
            module.load_contract = original
        self.assertEqual(code, 2)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["error"]["code"], "resolver_failure")
        self.assertEqual(payload["error"]["repair_id"], "resolver.internal")
        self.assertNotIn("schema_version", payload)
        self.assertNotIn("sentinel-exception-detail", json.dumps(payload),
                         "the internal message must not leak the exception text")


class EmitGuardTest(InProcessTestCase):
    """COR-001: the writing side refuses a non-finite float on its own.

    The parse-side guard keeps this unreachable from any authored contract,
    which is the point — it is the second half of the check, not a duplicate
    of the first: `emit_json` never prints a token another JSON parser would
    reject, whatever put the value in front of it.
    """

    def test_emitting_a_non_finite_float_raises(self):
        module = load_module()
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(value=repr(value)):
                buffer = io.StringIO()
                with self.assertRaises(ValueError):
                    with contextlib.redirect_stdout(buffer):
                        module.emit_json({"deploy": {"config": value}})
                self.assertNotIn("NaN", buffer.getvalue())
                self.assertNotIn("Infinity", buffer.getvalue())

    def test_emitting_finite_values_is_unchanged(self):
        module = load_module()
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            module.emit_json({"b": 1, "a": [2.5, "x"]})
        self.assertEqual(buffer.getvalue(), '{"a":[2.5,"x"],"b":1}\n')


class CommittedContractTest(ResolverTestCase):
    def test_the_repositorys_own_contract_is_structurally_valid(self):
        contract = source_contract()
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(sorted(contract["capabilities"]), sorted(CAPABILITY_NAMES))
        self.assertEqual(sorted(contract["bindings"]), sorted(BINDING_NAMESPACES))

    def test_orchestration_values_match_the_legacy_config(self):
        legacy = json.loads(
            (REPO_ROOT / ".claude" / "skills.config.json").read_text("utf-8"))
        orchestration = source_contract()["bindings"]["workflow"]["orchestration"]
        self.assertEqual(orchestration["max_parallel"],
                         legacy["orchestration"]["maxParallel"])
        self.assertEqual(orchestration["attempt_budget_minutes"],
                         legacy["orchestration"]["agentBudgetMinutes"])


def run_with_path(path_value: str, *args: str, home: Path) -> tuple[int, str, str]:
    """Run the resolver with `PATH` replaced by exactly `path_value`.

    The interpreter is `sys.executable`, an absolute path, because `PATH` here
    holds only the stub directory and no Python (B-002).
    """
    env = dict(os.environ, PATH=path_value, HOME=str(home))
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60, env=env,
    )
    return proc.returncode, proc.stdout, proc.stderr


def make_stub_bin(names: tuple[str, ...]) -> Path:
    """A directory holding executable no-op stubs for the named binaries."""
    stub = Path(tempfile.mkdtemp())
    for name in names:
        target = stub / name
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
    return stub


class CapabilityStateTest(ResolverTestCase):
    def resolve_with_path(self, root: Path, stub: Path, *extra: str):
        code, out, err = run_with_path(
            str(stub), "resolve", "--repo-root", str(root), *extra,
            home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, out, err

    def test_available_when_every_prerequisite_is_present(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        for name in ("tracker", "worktrees", "knowledge.standards",
                     "knowledge.architecture", "verification",
                     "review.plan", "review.code"):
            with self.subTest(capability=name):
                entry = snap["capabilities"][name]
                self.assertEqual(entry["state"], "available")
                self.assertIsNone(entry["reason_code"])
                self.assertIsNone(entry["repair_id"])

    def test_tracker_is_blocked_when_its_cli_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["tracker"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "tracker_cli_missing")
        self.assertEqual(entry["repair_id"], "capability.tracker.tracker_cli_missing")

    def test_worktrees_is_blocked_when_git_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["worktrees"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "vcs_worktree_unsupported")
        self.assertEqual(entry["repair_id"],
                         "capability.worktrees.vcs_worktree_unsupported")

    def test_verification_is_blocked_when_a_command_binary_is_absent(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["verification"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "command_missing")
        self.assertEqual(entry["repair_id"], "capability.verification.command_missing")

    def test_knowledge_is_blocked_when_a_declared_path_is_absent(self):
        # The absent path is declared rather than deleted: `CLAUDE.md` is a
        # projection target, and removing it would refuse as drift (D10)
        # before any readiness is computed.
        contract = source_contract()
        contract["bindings"]["paths"]["architecture"] = ["docs/architecture.md"]
        root = self.make_root(contract)
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["knowledge.architecture"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "knowledge_path_missing")
        self.assertEqual(entry["repair_id"],
                         "capability.knowledge.architecture.knowledge_path_missing")

    def test_every_blocked_reason_code_is_from_the_closed_set(self):
        root = self.make_root()
        code, snap, _, err = self.resolve_with_path(root, make_stub_bin(()))
        self.assertEqual(code, 0, err)
        for name, entry in snap["capabilities"].items():
            with self.subTest(capability=name):
                if entry["state"] == "blocked":
                    self.assertIn(entry["reason_code"],
                                  ("tracker_cli_missing", "vcs_worktree_unsupported",
                                   "knowledge_path_missing", "command_missing"))
                    self.assertEqual(entry["repair_id"],
                                     f"capability.{name}.{entry['reason_code']}")
                else:
                    self.assertIsNone(entry["reason_code"])
                    self.assertIsNone(entry["repair_id"])

    def test_unsupported_capabilities_never_evaluate_prerequisites(self):
        root = self.make_root()
        code, snap, _, err = self.resolve_with_path(root, make_stub_bin(()))
        self.assertEqual(code, 0, err)
        for name in ("release", "deploy", "knowledge.context", "knowledge.hints"):
            with self.subTest(capability=name):
                self.assertEqual(snap["capabilities"][name]["state"], "unsupported")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "mode bits do not bind root")
    def test_worktrees_is_blocked_when_the_worktree_parent_is_unwritable(self):
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        # The parent of `.worktrees` is the checkout itself: a read-only
        # checkout is the failure this prerequisite exists to catch.
        parent = root
        original = parent.stat().st_mode
        parent.chmod(0o500)
        try:
            code, snap, _, err = self.resolve_with_path(root, stub)
        finally:
            parent.chmod(original)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["worktrees"]
        self.assertEqual(entry["state"], "blocked")
        self.assertEqual(entry["reason_code"], "vcs_worktree_unsupported")

    def test_worktrees_is_available_when_the_worktree_root_is_absent(self):
        """The worktree root is created on first use, so its absence is normal.

        `.worktrees` is ignored by git and therefore missing from every fresh
        clone; blocking on it would report a working capability as broken.
        """
        root = self.make_root()
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        shutil.rmtree(root / ".worktrees")
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        entry = snap["capabilities"]["worktrees"]
        self.assertEqual(entry["state"], "available")
        self.assertIsNone(entry["reason_code"])
        self.assertIsNone(entry["repair_id"])

    def test_a_relative_executable_resolves_against_its_command_cwd(self):
        """DISC-001: the base is the entry's `cwd`, not `project.root`."""
        source = source_contract()
        source["bindings"]["commands"]["local-check"] = {
            "argv": ["./check"], "cwd": "tools", "env": []}
        source["bindings"]["workflow"]["verification"] = ["local-check"]
        root = self.make_root(source)
        stub = make_stub_bin(("gh", "git", "just", "codex"))

        (root / "tools").mkdir()
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "blocked")

        target = root / "tools" / "check"
        target.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        target.chmod(target.stat().st_mode | stat.S_IXUSR)
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "available")

    def test_a_relative_executable_at_the_root_does_not_satisfy_a_cwd_entry(self):
        source = source_contract()
        source["bindings"]["commands"]["local-check"] = {
            "argv": ["./check"], "cwd": "tools", "env": []}
        source["bindings"]["workflow"]["verification"] = ["local-check"]
        root = self.make_root(source)
        (root / "tools").mkdir()
        decoy = root / "check"
        decoy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        decoy.chmod(decoy.stat().st_mode | stat.S_IXUSR)
        stub = make_stub_bin(("gh", "git", "just", "codex"))
        code, snap, _, err = self.resolve_with_path(root, stub)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["capabilities"]["verification"]["state"], "blocked")


class ContradictionTest(ResolverTestCase):
    def refuse(self, contract: dict) -> dict:
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        return payload["error"]

    def test_supported_tracker_with_kind_none_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["tracker"]["kind"] = "none"
        self.assertIn("/bindings/tracker/kind",
                      [v["pointer"] for v in self.refuse(contract)["violations"]])

    def test_supported_tracker_with_an_empty_cli_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["tracker"]["cli"] = ""
        self.refuse(contract)

    def test_supported_worktrees_with_a_non_git_vcs_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["vcs"]["kind"] = "hg"
        self.refuse(contract)

    def test_supported_knowledge_with_an_empty_path_list_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["paths"]["standards"] = []
        self.assertIn("/bindings/paths/standards",
                      [v["pointer"] for v in self.refuse(contract)["violations"]])

    def test_supported_verification_with_no_ids_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["verification"] = []
        self.refuse(contract)

    def test_supported_review_with_a_null_id_is_a_contract_error(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["review"]["plan"] = None
        self.refuse(contract)

    def test_unsupported_capabilities_impose_no_binding_requirement(self):
        contract = source_contract()
        self.assertEqual(contract["capabilities"]["release"]["support"], "unsupported")
        self.assertIsNone(contract["bindings"]["workflow"]["release"])
        self.assertEqual(contract["bindings"]["deploy"]["adapter"], "none")
        code, _, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)

    def test_a_supported_deploy_needs_an_adapter_and_a_command(self):
        contract = source_contract()
        contract["capabilities"]["deploy"]["support"] = "supported"
        self.refuse(contract)


class RequireTest(ResolverTestCase):
    def test_requiring_an_unsupported_capability_refuses(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "release",
            home=self.home)
        payload = json.loads(out)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "capability_unavailable")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/capabilities/release"])
        self.assertEqual(error["repair_id"], "capability.release.unsupported")
        self.assertNotIn("schema_version", payload)

    def test_requiring_a_blocked_capability_names_its_reason_code(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "tracker",
            home=self.home)
        error = json.loads(out)["error"]
        self.assertEqual(code, 2)
        self.assertEqual(error["code"], "capability_unavailable")
        self.assertEqual(error["repair_id"], "capability.tracker.tracker_cli_missing")

    def test_several_offending_requirements_are_reported_in_pointer_order(self):
        root = self.make_root()
        code, out, _ = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root),
            "--require", "release", "--require", "deploy", home=self.home)
        error = json.loads(out)["error"]
        self.assertEqual(code, 2)
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertEqual(pointers, ["/capabilities/deploy", "/capabilities/release"])
        self.assertEqual(error["repair_id"], "capability.deploy.unsupported")

    def test_requiring_an_available_capability_returns_the_snapshot(self):
        root = self.make_root()
        code, out, err = run_with_path(
            str(make_stub_bin(("gh", "git", "just", "codex"))),
            "resolve", "--repo-root", str(root), "--require", "tracker",
            home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_an_unknown_require_name_is_an_argparse_usage_error(self):
        root = self.make_root()
        code, out, err = run("resolve", "--repo-root", str(root),
                             "--require", "orchestration", home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("orchestration", err)


class NoSubprocessTest(ResolverTestCase):
    def test_readiness_runs_no_child_process(self):
        """An empty PATH must still produce a snapshot, not an execution error."""
        root = self.make_root()
        code, out, err = run_with_path(
            str(make_stub_bin(())), "resolve", "--repo-root", str(root),
            home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_platform_status_runs_no_child_process(self):
        """R3.6: the administrative operation reads too, and starts nothing."""
        root = self.make_root()
        code, out, err = run_with_path(
            str(make_stub_bin(())), "platform-status", "--repo-root", str(root),
            "--fleet", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertTrue(payload["compatibility"]["compatible"])
        self.assertEqual(payload["fleet"], [])


class WriteProjectionsTest(ResolverTestCase):
    def write(self, root: Path) -> tuple[int, object, str]:
        code, out, err = run("write-projections", "--repo-root", str(root),
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def actions(self, payload: object) -> dict:
        return {p["id"]: p["action"] for p in payload["projections"]}

    def test_a_fresh_root_writes_both_projections(self):
        root = self.make_root(projections=False)
        code, payload, err = self.write(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), ["projections"])
        self.assertEqual(self.actions(payload),
                         {"codex.entry": "written", "claude.entry": "written"})
        self.assertTrue((root / "AGENTS.md").is_file())

    def test_the_codex_target_is_header_blank_line_then_the_source(self):
        root = self.make_root(projections=False)
        source = (root / ".agents" / "instructions" / "bootstrap.md").read_bytes()
        self.assertEqual(self.write(root)[0], 0)
        rendered = (root / "AGENTS.md").read_bytes()
        self.assertEqual(rendered, CODEX_HEADER.encode() + b"\n\n" + source)

    def test_the_claude_target_keeps_its_authored_body_and_gains_one_line(self):
        root = self.make_root(projections=False)
        body = (root / "CLAUDE.md").read_text("utf-8")
        self.assertEqual(self.write(root)[0], 0)
        after = (root / "CLAUDE.md").read_text("utf-8")
        self.assertIn(body, after)
        self.assertEqual(after.splitlines().count(MANAGED_LINE), 1)

    def test_a_second_run_reports_unchanged_and_touches_no_mtime(self):
        root = self.make_root(projections=False)
        self.assertEqual(self.write(root)[0], 0)
        before = {name: (root / name).stat().st_mtime_ns
                  for name in ("AGENTS.md", "CLAUDE.md")}
        code, payload, err = self.write(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.actions(payload),
                         {"codex.entry": "unchanged", "claude.entry": "unchanged"})
        after = {name: (root / name).stat().st_mtime_ns
                 for name in ("AGENTS.md", "CLAUDE.md")}
        self.assertEqual(before, after)

    def test_a_hand_edited_codex_target_is_rewritten(self):
        root = self.make_root()
        self.assertEqual(self.write(root)[0], 0)
        (root / "AGENTS.md").write_bytes(b"hand written\n")
        code, payload, err = self.write(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(self.actions(payload)["codex.entry"], "written")
        source = (root / ".agents" / "instructions" / "bootstrap.md").read_bytes()
        self.assertEqual((root / "AGENTS.md").read_bytes(),
                         CODEX_HEADER.encode() + b"\n\n" + source)

    def test_a_missing_claude_target_is_created_holding_only_the_line(self):
        root = self.make_root()
        (root / "CLAUDE.md").unlink()
        contract = source_contract()
        contract["bindings"]["paths"]["architecture"] = ["AGENTS.md"]
        (root / ".agents" / "project.json").write_text(
            json.dumps(contract), encoding="utf-8")
        self.assertEqual(self.write(root)[0], 0)
        self.assertEqual((root / "CLAUDE.md").read_text("utf-8"),
                         MANAGED_LINE + "\n")

    def test_a_duplicated_managed_line_is_refused_and_not_rewritten(self):
        root = self.make_root()
        (root / "CLAUDE.md").write_text(
            f"# body\n{MANAGED_LINE}\nmore\n{MANAGED_LINE}\n", encoding="utf-8")
        before = (root / "CLAUDE.md").read_text("utf-8")
        code, payload, _ = self.write(root)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "invalid_projection")
        self.assertEqual(error["repair_id"], "projection.claude.entry.stale")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/claude.entry"])
        self.assertEqual((root / "CLAUDE.md").read_text("utf-8"), before)

    def test_a_missing_source_is_a_contract_error(self):
        root = self.make_root()
        (root / ".agents" / "instructions" / "bootstrap.md").unlink()
        code, payload, _ = self.write(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertEqual(payload["error"]["repair_id"],
                         "contract.projections.source_missing")

    def test_rendering_is_deterministic_across_runs(self):
        root = self.make_root()
        self.assertEqual(self.write(root)[0], 0)
        first = (root / "AGENTS.md").read_bytes()
        (root / "AGENTS.md").unlink()
        self.assertEqual(self.write(root)[0], 0)
        self.assertEqual((root / "AGENTS.md").read_bytes(), first)

    def test_a_write_preserves_the_targets_permission_bits(self):
        """The atomic replace must not narrow the mode tempfile creates at."""
        root = self.make_root(projections=False)
        # 0750, a mode no other actor here produces: under the umask below a
        # created file lands on 0644 and `tempfile` creates at 0600, so an
        # implementation that ignored the existing target's bits — whichever
        # of those two it fell back to — fails this assertion instead of
        # matching it by coincidence (COR-004).
        os.chmod(root / "CLAUDE.md", 0o750)
        # The child inherits this umask, so the created target's mode is a
        # fixed expectation rather than whatever the machine happens to set.
        previous = os.umask(0o022)
        self.addCleanup(os.umask, previous)
        self.assertEqual(self.write(root)[0], 0)
        kept = (root / "CLAUDE.md").stat().st_mode & 0o777
        self.assertEqual(oct(kept), oct(0o750))
        created = (root / "AGENTS.md").stat().st_mode & 0o777
        self.assertEqual(oct(created), oct(0o644))
        self.assertTrue(created & stat.S_IRGRP and created & stat.S_IROTH,
                        oct(created))

    def test_no_stray_temporary_file_survives_a_write(self):
        root = self.make_root(projections=False)
        before = sorted(path.name for path in root.iterdir())
        self.assertEqual(self.write(root)[0], 0)
        self.assertEqual(sorted(path.name for path in root.iterdir()),
                         sorted([*before, "AGENTS.md"]))

    def test_a_failed_replace_leaves_no_temporary_file_behind(self):
        """A non-empty directory cannot be replaced by a file, so the write
        fails with the temporary file already on disk."""
        root = self.make_root(projections=False)
        (root / "AGENTS.md").mkdir()
        (root / "AGENTS.md" / "occupant").write_text("x", encoding="utf-8")
        before = sorted(path.name for path in root.iterdir())
        code, _, _ = self.write(root)
        self.assertEqual(code, 2)
        self.assertEqual(sorted(path.name for path in root.iterdir()), before)


class ProjectionCollisionTest(ResolverTestCase):
    """The writer visits entries in order and never re-reads what it wrote, so
    a collision between two declared entries has to be refused by the validator
    or it exits 0 having left one projection stale.
    """

    def contract_with(self, mutate) -> dict:
        contract = copy.deepcopy(source_contract())
        mutate(contract["projections"])
        return contract

    def refusal(self, contract: dict) -> dict:
        root = self.make_root(contract, projections=False)
        before = tree_snapshot(root)
        code, out, err = run("write-projections", "--repo-root", str(root),
                             home=self.home)
        self.assertEqual(code, 2, err)
        # The refusal precedes every write: nothing under the root moved.
        self.assertEqual(tree_snapshot(root), before)
        return json.loads(out)["error"]

    def test_two_entries_on_one_target_are_refused(self):
        error = self.refusal(self.contract_with(
            lambda entries: entries[1].__setitem__("target", entries[0]["target"])))
        self.assertEqual(error["code"], "invalid_contract")
        self.assertEqual(error["repair_id"],
                         "contract.projections.duplicate_target")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/1/target"])

    def test_a_target_that_is_also_a_source_is_refused(self):
        error = self.refusal(self.contract_with(
            lambda entries: entries[0].__setitem__(
                "target", entries[0]["source"])))
        self.assertEqual(error["code"], "invalid_contract")
        self.assertEqual(error["repair_id"],
                         "contract.projections.target_is_source")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/0/target"])

    def test_a_nested_target_is_written_rather_than_failing_on_its_parent(self):
        """`generated/AGENTS.md` is a safe path the validator accepts; the
        writer must create the directory it names instead of surfacing the
        missing parent as `resolver_failure`.
        """
        contract = self.contract_with(
            lambda entries: entries[0].__setitem__("target", "generated/AGENTS.md"))
        root = self.make_root(contract, projections=False)
        code, out, err = run("write-projections", "--repo-root", str(root),
                             home=self.home)
        self.assertEqual(code, 0, err)
        self.assertEqual(
            {p["id"]: p["action"] for p in json.loads(out)["projections"]},
            {"codex.entry": "written", "claude.entry": "written"})
        source = (root / ".agents" / "instructions" / "bootstrap.md").read_bytes()
        self.assertEqual((root / "generated" / "AGENTS.md").read_bytes(),
                         CODEX_HEADER.encode() + b"\n\n" + source)


class CommittedProjectionTest(ResolverTestCase):
    def test_the_repository_projections_are_present_and_current(self):
        agents = (REPO_ROOT / "AGENTS.md").read_bytes()
        source = (REPO_ROOT / ".agents" / "instructions" / "bootstrap.md").read_bytes()
        self.assertEqual(agents, CODEX_HEADER.encode() + b"\n\n" + source)
        claude = (REPO_ROOT / "CLAUDE.md").read_text("utf-8")
        self.assertEqual(claude.splitlines().count(MANAGED_LINE), 1)


class CheckProjectionsTest(ResolverTestCase):
    def check(self, root: Path) -> tuple[int, object, str]:
        code, out, err = run("check-projections", "--repo-root", str(root),
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def test_in_sync_reports_every_projection_unchanged(self):
        code, payload, err = self.check(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), ["projections"])
        self.assertEqual({p["action"] for p in payload["projections"]}, {"unchanged"})
        self.assertEqual([p["id"] for p in payload["projections"]],
                         ["codex.entry", "claude.entry"])

    def test_an_appended_byte_in_the_codex_target_is_drift(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("\nhand edit\n")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "invalid_projection")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/codex.entry"])
        self.assertEqual(error["repair_id"], "projection.codex.entry.stale")

    def test_a_missing_codex_target_is_drift(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["repair_id"], "projection.codex.entry.missing")

    def test_a_deleted_managed_line_is_drift(self):
        root = self.make_root()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/claude.entry"])
        self.assertEqual(error["repair_id"], "projection.claude.entry.stale")

    def test_a_duplicated_managed_line_is_drift(self):
        root = self.make_root()
        with (root / "CLAUDE.md").open("a", encoding="utf-8") as handle:
            handle.write(MANAGED_LINE + "\n")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_projection")

    def test_both_drifted_projections_are_reported_in_pointer_order(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/projections/claude.entry", "/projections/codex.entry"])
        self.assertEqual(payload["error"]["repair_id"],
                         "projection.claude.entry.stale")

    def test_a_missing_source_is_a_contract_error_not_drift(self):
        root = self.make_root()
        (root / ".agents" / "instructions" / "bootstrap.md").unlink()
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_check_projections_writes_nothing(self):
        """SF-001: the same three witnesses Task 1's `ReadOnlyTest` uses."""
        assert_read_only(self, self.make_root(), 0, "check-projections")

    def test_a_refusing_check_projections_writes_nothing(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("x\n")
        assert_read_only(self, root, 2, "check-projections")

    def test_a_refusing_resolve_on_drift_writes_nothing(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("x\n")
        assert_read_only(self, root, 2, "resolve")


class ResolveFreshnessTest(ResolverTestCase):
    def test_resolve_refuses_a_drifted_projection_with_no_snapshot(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("hand edit\n")
        code, out, _ = run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "invalid_projection")
        for member in ("schema_version", "project", "bindings", "capabilities"):
            self.assertNotIn(f'"{member}"', out)

    def test_resolve_refuses_a_deleted_managed_line(self):
        root = self.make_root()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.resolve(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_projection")

    def test_resolve_still_writes_nothing_when_it_refuses(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
        self.assertEqual(self.resolve(root)[0], 2)
        after = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
        self.assertEqual(before, after)


class DriftGateTest(ResolverTestCase):
    """Seam 9: this repository's own committed contract must resolve."""

    def test_the_repository_resolves_and_its_projections_are_current(self):
        code, out, err = run("resolve", "--repo-root", str(REPO_ROOT),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        snapshot = json.loads(out)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(sorted(snapshot["capabilities"]), sorted(CAPABILITY_NAMES))
        self.assertEqual(snapshot["project"]["id"], "fagenorn/nix-config")
        self.assertEqual(snapshot["project"]["root"], str(REPO_ROOT))

    def test_the_repository_check_projections_is_clean(self):
        code, out, err = run("check-projections", "--repo-root", str(REPO_ROOT),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        self.assertEqual({p["action"] for p in json.loads(out)["projections"]},
                         {"unchanged"})


class ManifestGateTest(ResolverTestCase):
    """R1.3: a broken platform installation refuses loudly, from every subcommand.

    `write-projections` is included deliberately: the gate has to close before
    the writer, not just before the two readers.
    """

    def refusals(self, manifest: object, root: Path) -> list[list[dict]]:
        """Refuse `resolver_failure` from every subcommand; return each list."""
        self.set_manifest(manifest)
        collected = []
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, err = run(subcommand, "--repo-root", str(root),
                                     home=self.home)
                self.assertEqual(code, 2, err or out)
                payload = json.loads(out)
                self.assertEqual(sorted(payload), ["error"])
                error = payload["error"]
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])
                self.assertEqual(error["code"], "resolver_failure")
                self.assertTrue(error["repair_id"])
                self.assertTrue(error["violations"])
                pointers = [v["pointer"] for v in error["violations"]]
                self.assertEqual(pointers, sorted(pointers))
                for entry in error["violations"]:
                    self.assertEqual(sorted(entry), ["message", "pointer"])
                collected.append(error)
        repair_ids = {error["repair_id"] for error in collected}
        self.assertEqual(len(repair_ids), 1, repair_ids)
        return [error["violations"] for error in collected]

    def assert_pointers(self, manifest: object, expected: list[str]) -> None:
        for violations in self.refusals(manifest, self.make_root()):
            self.assertEqual([v["pointer"] for v in violations], expected)

    def assert_repair_id(self, manifest: object, expected: str) -> None:
        """The three whole-file failures share the empty pointer, so only the
        repair id tells a caller which one it hit."""
        self.set_manifest(manifest)
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["repair_id"], expected)

    def test_a_missing_manifest_refuses(self):
        self.assert_pointers(None, [""])
        self.assert_repair_id(None, "platform.manifest.missing")

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root reads a 0000 file, so the case cannot be staged")
    def test_an_unreadable_manifest_refuses(self):
        root = self.make_root()
        self.set_manifest(COMMITTED)
        installed = self.home / ".agents" / "share" / "platform-manifest.json"
        installed.chmod(0o000)
        self.addCleanup(installed.chmod, 0o600)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                error = json.loads(out)["error"]
                self.assertEqual(error["code"], "resolver_failure")
                self.assertEqual([v["pointer"] for v in error["violations"]], [""])
                self.assertEqual(error["repair_id"],
                                 "platform.manifest.unreadable")

    def test_a_manifest_that_is_not_valid_json_refuses(self):
        self.assert_pointers("{", [""])
        self.assert_repair_id("{", "platform.manifest.parse")

    def test_a_manifest_that_is_not_an_object_refuses(self):
        self.assert_pointers([], [""])
        self.assert_repair_id([], "platform.manifest.not_object")

    def test_an_unexpected_member_refuses(self):
        self.assert_pointers(mutated_manifest(surprise=1), ["/surprise"])

    def test_a_missing_member_refuses(self):
        manifest = committed_manifest()
        del manifest["resolved_schema_version"]
        self.assert_pointers(manifest, ["/resolved_schema_version"])

    def test_a_non_semver_platform_version_refuses(self):
        self.assert_pointers(mutated_manifest(platform_version="one"),
                             ["/platform_version"])

    def test_a_malformed_schema_version_refuses(self):
        for value in (0, -1, True, "1"):
            with self.subTest(schema_version=value):
                self.assert_pointers(mutated_manifest(schema_version=value),
                                     ["/schema_version"])

    def test_a_malformed_resolved_schema_version_refuses(self):
        for value in (0, -1, True, "1"):
            with self.subTest(resolved_schema_version=value):
                self.assert_pointers(
                    mutated_manifest(resolved_schema_version=value),
                    ["/resolved_schema_version"])

    def test_a_malformed_project_schema_versions_refuses(self):
        cases = (
            ({}, "/project_schema_versions"),
            ([], "/project_schema_versions"),
            ([1, 1], "/project_schema_versions"),
            ([2, 1], "/project_schema_versions"),
            ([0], "/project_schema_versions/0"),
            ([True], "/project_schema_versions/0"),
            ([1, "2"], "/project_schema_versions/1"),
        )
        for value, pointer in cases:
            with self.subTest(project_schema_versions=value):
                self.assert_pointers(
                    mutated_manifest(project_schema_versions=value), [pointer])

    def test_the_refusal_bytes_are_stable_across_runs(self):
        root = self.make_root()
        self.set_manifest(None)
        first = run("resolve", "--repo-root", str(root), home=self.home)
        second = run("resolve", "--repo-root", str(root), home=self.home)
        self.assertEqual(first[0], 2)
        self.assertEqual(first[1], second[1])

    def test_the_gate_closes_before_the_repository_is_read(self):
        """A root with no contract at all still reports `resolver_failure`.

        Without the gate this repository is `not_onboarded`, which is exactly
        the masking R1.3 forbids — so the control below pins the other half:
        with a valid manifest the same root does refuse `not_onboarded`.
        """
        root = self.make_root(contract=False, projections=False)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand, manifest="valid"):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["code"], "not_onboarded")
        self.set_manifest(None)
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand, manifest="missing"):
                code, out, _ = run(subcommand, "--repo-root", str(root),
                                   home=self.home)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(out)["error"]["code"],
                                 "resolver_failure")

    def test_a_manifest_refusal_leaves_the_tree_untouched(self):
        """SF-001: the gate reads the manifest and nothing else."""
        self.set_manifest(None)
        # A root each: `assert_read_only` commits its fixture before running,
        # and a second call against the same root has nothing left to commit.
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                assert_read_only(self, self.make_root(), 2, subcommand)

    def test_a_manifest_refusal_runs_no_child_process(self):
        root = self.make_root()
        self.set_manifest(None)
        code, out, err = run_with_path(
            str(make_stub_bin(())), "resolve", "--repo-root", str(root),
            home=self.home)
        self.assertEqual(code, 2)
        self.assertEqual(err, "")
        self.assertEqual(json.loads(out)["error"]["code"], "resolver_failure")


class ManifestLifecycleArrayTest(ResolverTestCase):
    """D36: `migrations` is validated strictly; `deprecations` and `removals`
    are validated as arrays and never read."""

    def assert_pointer(self, changes: dict, expected: str) -> None:
        self.set_manifest(mutated_manifest(**changes))
        code, out, _ = run("resolve", "--repo-root", str(self.make_root()),
                           home=self.home)
        self.assertEqual(code, 2)
        error = json.loads(out)["error"]
        self.assertEqual(error["code"], "resolver_failure")
        self.assertEqual([v["pointer"] for v in error["violations"]], [expected])

    def test_migrations_must_be_an_array(self):
        self.assert_pointer({"migrations": {}}, "/migrations")

    def test_an_entry_must_be_an_object(self):
        self.assert_pointer({"migrations": ["1-2"]}, "/migrations/0")

    def test_an_entry_member_may_not_be_absent(self):
        self.assert_pointer(
            {"migrations": [{"id": "a", "from_schema": 1}]},
            "/migrations/0/to_schema")

    def test_an_entry_member_may_not_be_unexpected(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2, "note": "x"}]},
            "/migrations/0/note")

    def test_an_id_must_be_a_non_empty_string(self):
        for value in (1, "", None):
            with self.subTest(id=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": value, "from_schema": 1, "to_schema": 2}]},
                    "/migrations/0/id")

    def test_ids_must_be_distinct(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2},
                {"id": "a", "from_schema": 2, "to_schema": 3}]},
            "/migrations")

    def test_from_schema_must_be_a_positive_non_bool_integer(self):
        for value in ("1", True, 0, -1):
            with self.subTest(from_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": value, "to_schema": 2}]},
                    "/migrations/0/from_schema")

    def test_to_schema_must_be_a_positive_non_bool_integer(self):
        for value in ("2", True, 0, -1):
            with self.subTest(to_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": 1, "to_schema": value}]},
                    "/migrations/0/to_schema")

    def test_to_schema_must_be_one_step_past_from_schema(self):
        for value in (1, 3):
            with self.subTest(to_schema=value):
                self.assert_pointer(
                    {"migrations": [
                        {"id": "a", "from_schema": 1, "to_schema": value}]},
                    "/migrations/0/to_schema")

    def test_from_schemas_must_be_distinct(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 1, "to_schema": 2},
                {"id": "b", "from_schema": 1, "to_schema": 2}]},
            "/migrations")

    def test_from_schemas_must_ascend(self):
        self.assert_pointer(
            {"migrations": [
                {"id": "a", "from_schema": 2, "to_schema": 3},
                {"id": "b", "from_schema": 1, "to_schema": 2}]},
            "/migrations")

    def test_a_well_formed_migration_chain_is_accepted(self):
        self.set_manifest(mutated_manifest(migrations=[
            {"id": "1-to-2", "from_schema": 1, "to_schema": 2},
            {"id": "2-to-3", "from_schema": 2, "to_schema": 3}]))
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err or out)

    def test_deprecations_and_removals_must_be_arrays(self):
        for name in ("deprecations", "removals"):
            for value in ({}, 1, "x"):
                with self.subTest(member=name, value=value):
                    self.assert_pointer({name: value}, f"/{name}")

    def test_opaque_array_entries_are_never_read(self):
        """Neither array has a declared entry shape at v1, so any entry passes."""
        self.set_manifest(mutated_manifest(
            deprecations=[{"anything": [1, 2]}], removals=["whatever"]))
        code, out, err = run("resolve", "--repo-root", str(self.make_root()),
                             home=self.home)
        self.assertEqual(code, 0, err or out)


class SemverBoundaryTest(ResolverTestCase):
    """D9: strict `MAJOR.MINOR.PATCH`, exercised through the manifest validator."""

    def test_a_loose_version_is_rejected(self):
        for value in ("1.0", "1.0.0.0", "v1.0.0", "1.0.0-rc.1", "1.0.0+build",
                      "01.0.0"):
            with self.subTest(platform_version=value):
                self.set_manifest(mutated_manifest(platform_version=value))
                code, out, _ = run("resolve", "--repo-root",
                                   str(self.make_root()), home=self.home)
                self.assertEqual(code, 2)
                error = json.loads(out)["error"]
                self.assertEqual(error["code"], "resolver_failure")
                self.assertEqual([v["pointer"] for v in error["violations"]],
                                 ["/platform_version"])

    def test_a_strict_version_is_accepted(self):
        # Both spellings sit inside this repository's committed contract
        # interval, so the range check (R2.3) cannot mask the shape question
        # this case is about.
        for value in ("1.0.0", "1.20.30"):
            with self.subTest(platform_version=value):
                self.set_manifest(mutated_manifest(platform_version=value))
                code, out, err = run("resolve", "--repo-root",
                                     str(self.make_root()), home=self.home)
                self.assertEqual(code, 0, err or out)


class PlatformLibraryTest(ResolverTestCase):
    """R1.3 / D12: the library half of the installation refuses like the
    manifest half.

    Every case here runs a copy of the script from `$HOME/.agents/bin`, the
    deployed layout, because in the repository checkout the script's own
    directory holds `agent_platform.py` as a sibling — so a run from `scripts/`
    imports the library whatever `HOME` says and could never observe an
    uninstalled one.
    """

    def deployed(self, home: Path) -> Path:
        binary = home / ".agents" / "bin" / "resolve-project"
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(SCRIPT, binary)
        return binary

    def run_deployed(self, home: Path, *args: str,
                     unset_home: bool = False) -> tuple[int, str, str]:
        binary = self.deployed(home)
        env = {**os.environ, "HOME": str(home)}
        # `PYTHONPATH` would be a second lookup path the deployed machine does
        # not have; the runner's own may carry one.
        env.pop("PYTHONPATH", None)
        if unset_home:
            env.pop("HOME", None)
        proc = subprocess.run(
            [sys.executable, str(binary), *args],
            capture_output=True, text=True, timeout=60,
            cwd=str(home), env=env)
        return proc.returncode, proc.stdout, proc.stderr

    def assert_library_refusal(self, code: int, out: str, err: str) -> None:
        self.assertEqual(code, 2, err or out)
        self.assertEqual(err, "")
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["error"])
        error = payload["error"]
        self.assertEqual(sorted(error), ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], "resolver_failure")
        self.assertEqual(error["repair_id"], "platform.library.missing")
        self.assertTrue(error["violations"])
        for entry in error["violations"]:
            self.assertEqual(sorted(entry), ["message", "pointer"])

    def test_an_uninstalled_library_refuses_on_stdout(self):
        """A valid manifest is installed, so only the missing library can refuse."""
        home = make_home(library=False)
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                self.assert_library_refusal(
                    *self.run_deployed(home, subcommand, "--repo-root", str(root)))

    def test_a_library_missing_one_member_refuses_the_same_way(self):
        """The library and the binary are installed separately, so an older
        library can pair with a newer resolver. Every member the resolver uses
        must therefore refuse as `platform.library.missing`, not as an
        `AttributeError` swallowed into `resolver.internal` (R1.3, D12).
        """
        root = self.make_root()
        source = LIBRARY.read_text("utf-8")
        for name in library_members():
            with self.subTest(member=name):
                home = make_home()
                # A module-level `del` after the definitions: the module still
                # imports, and only this one attribute is gone.
                (home / ".agents" / "lib" / "python"
                 / "agent_platform.py").write_text(
                    source + f"\n\ndel {name}\n", encoding="utf-8")
                self.assert_library_refusal(
                    *self.run_deployed(home, "resolve", "--repo-root", str(root)))

    def test_the_declared_members_are_exactly_the_members_used(self):
        """The guard is only as wide as its tuple: a member the resolver reads
        but does not declare is a hole this case closes."""
        used = set(re.findall(r"\bagent_platform\.([A-Za-z_][A-Za-z0-9_]*)",
                              SCRIPT.read_text("utf-8")))
        # `agent_platform.py` appears inside the refusal message, not as an
        # attribute read.
        used.discard("py")
        self.assertEqual(sorted(library_members()), sorted(used))

    def test_an_unset_home_refuses_on_stdout(self):
        home = make_home()
        code, out, err = self.run_deployed(
            home, "resolve", "--repo-root", str(self.make_root()),
            unset_home=True)
        self.assert_library_refusal(code, out, err)

    def test_the_refusal_bytes_are_stable_across_runs(self):
        home = make_home(library=False)
        root = self.make_root()
        first = self.run_deployed(home, "resolve", "--repo-root", str(root))
        second = self.run_deployed(home, "resolve", "--repo-root", str(root))
        self.assertEqual(first[0], 2)
        self.assertEqual(first[1], second[1])

    def test_the_installed_library_answers_in_the_deployed_layout(self):
        """The control: the same shape with the library installed resolves."""
        home = make_home()
        code, out, err = self.run_deployed(
            home, "resolve", "--repo-root", str(self.make_root()))
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["schema_version"], 1)

    def test_a_usage_error_still_belongs_to_argparse(self):
        """D16: the library guard runs after parsing, so no JSON appears here."""
        home = make_home(library=False)
        code, out, err = self.run_deployed(home)
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertNotEqual(err, "")


class CommittedManifestTest(ResolverTestCase):
    """The committed manifest is the one the store installs (D1), so the suite
    checks that file rather than a fixture."""

    def test_it_declares_exactly_the_seven_members_with_the_v1_values(self):
        manifest = committed_manifest()
        self.assertEqual(sorted(manifest), sorted(MANIFEST_MEMBERS))
        self.assertEqual(manifest["schema_version"], 1)
        self.assertEqual(manifest["platform_version"], "1.0.0")
        self.assertEqual(manifest["project_schema_versions"], [1])
        self.assertEqual(manifest["resolved_schema_version"], 1)
        for name in ("migrations", "deprecations", "removals"):
            with self.subTest(member=name):
                self.assertEqual(manifest[name], [])

    def test_it_loads_and_validates(self):
        # `setUp` installs this exact file; a subcommand that gets as far as
        # answering has loaded and validated it.
        root = self.make_root()
        for subcommand in SUBCOMMANDS:
            with self.subTest(subcommand=subcommand):
                code, out, err = run(subcommand, "--repo-root", str(root),
                                     home=self.home)
                self.assertEqual(code, 0, err or out)



class PlatformIntervalShapeTest(ResolverTestCase):
    """R2.1 / R2.2: the interval's shape is `invalid_contract`, never a range
    verdict. A malformed interval and an out-of-range one are two different
    refusals and are never confused."""

    CASES = (
        ("the member is absent", None, "/platform"),
        ("the member is not an object", "1.0.0", "/platform"),
        ("min_inclusive is absent",
         {"max_exclusive": "2.0.0"}, "/platform/min_inclusive"),
        ("max_exclusive is absent",
         {"min_inclusive": "1.0.0"}, "/platform/max_exclusive"),
        ("an unexpected member",
         {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0", "pin": "1.0.0"},
         "/platform/pin"),
        ("a non-string bound",
         {"min_inclusive": 1, "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("a null bound",
         {"min_inclusive": "1.0.0", "max_exclusive": None},
         "/platform/max_exclusive"),
        ("a non-SemVer bound",
         {"min_inclusive": "1.0", "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("a pre-release bound",
         {"min_inclusive": "1.0.0", "max_exclusive": "2.0.0-rc.1"},
         "/platform/max_exclusive"),
        ("a build-metadata bound",
         {"min_inclusive": "1.0.0+build", "max_exclusive": "2.0.0"},
         "/platform/min_inclusive"),
        ("an exact pin",
         {"min_inclusive": "1.0.0", "max_exclusive": "1.0.0"},
         "/platform/max_exclusive"),
        ("an inverted interval",
         {"min_inclusive": "2.0.0", "max_exclusive": "1.9.9"},
         "/platform/max_exclusive"),
    )

    def test_each_malformed_interval_is_an_invalid_contract_violation(self):
        for label, value, pointer in self.CASES:
            with self.subTest(case=label):
                contract = source_contract()
                if value is None:
                    del contract["platform"]
                else:
                    contract["platform"] = value
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                error = payload["error"]
                self.assertEqual(error["code"], "invalid_contract")
                self.assertNotIn("reason_code", error)
                self.assertIn(pointer,
                              [v["pointer"] for v in error["violations"]])
                self.assertNotIn("schema_version", payload)


class PlatformRangeTest(ResolverTestCase):
    """R2.3 / R2.4: the range and schema-set questions, answered only after
    shape validation has passed, as `unsupported_schema` with a reason code."""

    def assert_unsupported(self, code: int, payload: object,
                           reason_code: str, pointer: str) -> None:
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "unsupported_schema")
        self.assertEqual(error["reason_code"], reason_code)
        self.assertEqual([v["pointer"] for v in error["violations"]], [pointer])
        self.assertNotIn("schema_version", payload)

    def test_a_platform_at_the_max_bound_is_out_of_range(self):
        # The committed contract declares [1.0.0, 2.0.0); `max_exclusive` is
        # exclusive, so 2.0.0 is already outside it.
        self.set_manifest(mutated_manifest(platform_version="2.0.0"))
        code, payload, _ = self.resolve(self.make_root())
        self.assert_unsupported(code, payload, "platform_too_new", "/platform")

    def test_a_platform_below_the_min_bound_is_out_of_range(self):
        self.set_manifest(mutated_manifest(platform_version="0.9.0"))
        code, payload, _ = self.resolve(self.make_root())
        self.assert_unsupported(code, payload, "platform_too_old", "/platform")

    def test_the_min_bound_itself_is_inside_the_range(self):
        self.set_manifest(mutated_manifest(platform_version="1.0.0"))
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["schema_version"], 1)

    def test_a_malformed_interval_never_reaches_the_range_check(self):
        """An out-of-range platform *and* a malformed interval: the shape
        answer wins, because the range check runs only after it passes."""
        self.set_manifest(mutated_manifest(platform_version="9.9.9"))
        contract = source_contract()
        contract["platform"] = {"min_inclusive": "1.0", "max_exclusive": "2.0.0"}
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertNotIn("reason_code", payload["error"])

    def test_a_schema_absent_from_the_manifest_set_is_unsupported(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assert_unsupported(code, payload, "project_schema_unsupported",
                                "/schema_version")
        self.assertEqual(payload["error"]["repair_id"],
                         "contract.schema_version.unsupported")

    def test_a_supported_non_current_schema_resolves(self):
        """R2.5: no refusal, no deprecation notice, still four members."""
        self.set_manifest(mutated_manifest(project_schema_versions=[1, 2]))
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(
            sorted(snap),
            ["bindings", "capabilities", "project", "schema_version"])
        for word in ("deprecat", "removal", "migration", "notice"):
            self.assertNotIn(word, json.dumps(snap).lower())

    def test_the_snapshot_version_is_the_manifests_resolved_version(self):
        """D8: the snapshot's interface version comes from the manifest, not
        from the contract's declared schema and not from a source literal."""
        self.set_manifest(mutated_manifest(
            project_schema_versions=[1, 2], resolved_schema_version=2))
        contract = source_contract()
        self.assertEqual(contract["schema_version"], 1)
        code, snap, err = self.resolve(self.make_root(contract))
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["schema_version"], 2)


class ReasonCodePositionTest(ResolverTestCase):
    """D7: `reason_code` is a member of the error object exactly when the code
    is `unsupported_schema`, and of no other refusal this tool can emit."""

    def refusal(self, *args: str, root: Path | None = None) -> dict:
        code, out, err = run(*args, home=self.home)
        self.assertEqual(code, 2, err or out)
        return json.loads(out)["error"]

    def test_every_other_error_code_carries_no_reason_code(self):
        cases: list[tuple[str, dict]] = []

        empty = Path(tempfile.mkdtemp()).resolve()
        cases.append(("not_onboarded", self.refusal(
            "resolve", "--repo-root", str(empty))))

        contract = source_contract()
        del contract["bindings"]["deploy"]
        cases.append(("invalid_contract", self.refusal(
            "resolve", "--repo-root", str(self.make_root(contract)))))

        drifted = self.make_root()
        (drifted / "AGENTS.md").write_text("hand edited\n", encoding="utf-8")
        cases.append(("invalid_projection", self.refusal(
            "check-projections", "--repo-root", str(drifted))))

        cases.append(("capability_unavailable", self.refusal(
            "resolve", "--repo-root", str(self.make_root()),
            "--require", "release")))

        broken = self.make_root()
        self.set_manifest(None)
        cases.append(("resolver_failure", self.refusal(
            "resolve", "--repo-root", str(broken))))

        seen = {code for code, _ in cases}
        self.assertEqual(seen, {"not_onboarded", "invalid_contract",
                                "invalid_projection", "capability_unavailable",
                                "resolver_failure"})
        for code, error in cases:
            with self.subTest(code=code):
                self.assertEqual(error["code"], code)
                self.assertNotIn("reason_code", error)
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])

    def test_unsupported_schema_always_carries_one_from_the_closed_set(self):
        closed = ("platform_too_old", "platform_too_new",
                  "project_schema_unsupported")
        contract = source_contract()
        contract["schema_version"] = 2
        errors = [self.refusal("resolve", "--repo-root",
                               str(self.make_root(contract)))]
        for version in ("0.9.0", "2.0.0"):
            self.set_manifest(mutated_manifest(platform_version=version))
            errors.append(self.refusal("resolve", "--repo-root",
                                       str(self.make_root())))
        for error in errors:
            self.assertEqual(error["code"], "unsupported_schema")
            self.assertIn(error["reason_code"], closed)
            self.assertEqual(
                sorted(error),
                ["code", "reason_code", "repair_id", "violations"])
        self.assertEqual({error["reason_code"] for error in errors},
                         set(closed))


class CommittedIntervalTest(ResolverTestCase):
    """The mutual gate: the committed manifest and the committed contract
    check each other, so bumping one without the other fails here."""

    def test_the_committed_contract_declares_the_interval(self):
        platform = source_contract()["platform"]
        self.assertEqual(sorted(platform), ["max_exclusive", "min_inclusive"])
        self.assertEqual(platform["min_inclusive"], "1.0.0")
        self.assertEqual(platform["max_exclusive"], "2.0.0")

    def test_the_committed_platform_version_is_inside_the_interval(self):
        platform = source_contract()["platform"]
        version = committed_manifest()["platform_version"]
        low = tuple(int(part) for part in platform["min_inclusive"].split("."))
        high = tuple(int(part) for part in platform["max_exclusive"].split("."))
        active = tuple(int(part) for part in version.split("."))
        self.assertTrue(low <= active < high,
                        f"{version} is outside "
                        f"[{platform['min_inclusive']}, "
                        f"{platform['max_exclusive']})")

    def test_the_committed_schema_version_is_one_the_manifest_supports(self):
        self.assertIn(source_contract()["schema_version"],
                      committed_manifest()["project_schema_versions"])

    def test_this_repository_resolves_under_the_committed_manifest(self):
        code, out, err = run("resolve", "--repo-root", str(REPO_ROOT),
                             home=self.home)
        self.assertEqual(code, 0, err or out)
        self.assertEqual(json.loads(out)["schema_version"],
                         committed_manifest()["resolved_schema_version"])


class SchemaReasonDispatchTest(InProcessTestCase):
    """D7: both mappings over `SCHEMA_REASON_CODES` are exhaustive, and the
    `reason_code` position rule is enforced where the object is emitted rather
    than trusted from the caller."""

    def setUp(self) -> None:
        super().setUp()
        self.module = load_module()
        self.assertTrue(self.module.bootstrap_platform_library())
        self.codes = self.module.agent_platform.SCHEMA_REASON_CODES

    def test_the_closed_set_is_exactly_the_three_members(self):
        self.assertEqual(self.codes, ("platform_too_old", "platform_too_new",
                                      "project_schema_unsupported"))

    def test_every_member_maps_to_a_repair_id_and_a_message(self):
        ids, messages = set(), set()
        for reason_code in self.codes:
            with self.subTest(reason_code=reason_code):
                repair_id = self.module.schema_reason_repair_id(reason_code)
                message = self.module.schema_reason_message(reason_code)
                self.assertTrue(repair_id and isinstance(repair_id, str))
                self.assertTrue(message and isinstance(message, str))
                ids.add(repair_id)
                messages.add(message)
        self.assertEqual(len(ids), len(self.codes))
        self.assertEqual(len(messages), len(self.codes))

    def test_an_unknown_reason_code_raises_in_both_dispatches(self):
        for mapping in (self.module.schema_reason_repair_id,
                        self.module.schema_reason_message):
            with self.subTest(mapping=mapping.__name__):
                with self.assertRaises(ValueError):
                    mapping("platform_sideways")

    def test_emit_error_refuses_a_misplaced_reason_code(self):
        buffer = io.StringIO()
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "invalid_contract", "contract.parse",
                    [{"pointer": "", "message": "x"}], "platform_too_old")
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "unsupported_schema", "contract.platform.too_old",
                    [{"pointer": "", "message": "x"}], None)
        with self.assertRaises(ValueError):
            with contextlib.redirect_stdout(buffer):
                self.module.emit_error(
                    "unsupported_schema", "contract.platform.too_old",
                    [{"pointer": "", "message": "x"}], "platform_sideways")
        self.assertEqual(buffer.getvalue(), "")

PLATFORM_STATUS_MEMBERS = [
    "compatibility", "fleet", "platform", "project", "schema_version",
]
# The manifest's six data members plus the deployment identity (D2); the
# manifest's own `schema_version` is not one of them.
PLATFORM_BLOCK_MEMBERS = [
    "deprecations", "manifest_path", "migrations", "platform_version",
    "project_schema_versions", "removals", "resolved_schema_version",
]
PROJECT_BLOCK_MEMBERS = [
    "platform_interval", "project_id", "project_schema_version", "root",
]
COMPATIBILITY_MEMBERS = ["compatible", "reason_code", "repair_id"]
FLEET_ROW_MEMBERS = [
    "compatible", "platform_interval", "project_id", "project_schema_version",
    "reason_code", "repair_id", "root",
]


class PlatformStatusTest(ResolverTestCase):
    """R3 / D5 / D6: the fourth subcommand publishes the platform's version
    facts and a compatibility verdict, and refuses only what `resolve` refuses.

    The split this class pins is D6's: a contract that cannot be *parsed* into
    an interval is a refusal, an interval that parses and falls outside the
    range is a reported verdict on exit 0 — the case the operation exists for.
    """

    def status(self, *args: str) -> tuple[int, object, str]:
        code, out, err = run("platform-status", *args, home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def test_with_no_target_the_platform_block_stands_alone(self):
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        self.assertIsNone(payload["project"])
        self.assertIsNone(payload["compatibility"])
        self.assertIsNone(payload["fleet"])

    def test_the_platform_block_reports_the_manifests_data_members(self):
        """The installed manifest is the committed file (`setUp`), so the
        expected values come from that file rather than from a second run."""
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        block = payload["platform"]
        self.assertEqual(sorted(block), PLATFORM_BLOCK_MEMBERS)
        manifest = committed_manifest()
        for name in ("platform_version", "project_schema_versions",
                     "resolved_schema_version", "migrations", "deprecations",
                     "removals"):
            with self.subTest(member=name):
                self.assertEqual(block[name], manifest[name])

    def test_the_manifest_path_is_the_resolved_installed_file(self):
        """D2: the deployment identity is the path of the file actually
        loaded, absolute and reported verbatim."""
        code, payload, err = self.status()
        self.assertEqual(code, 0, err)
        reported = payload["platform"]["manifest_path"]
        self.assertEqual(
            reported,
            str(self.home / ".agents" / "share" / "platform-manifest.json"))
        self.assertTrue(Path(reported).is_absolute())

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("platform-status", home=self.home)
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")

    def test_a_compatible_project_reports_a_clean_verdict(self):
        root = self.make_root()
        code, payload, err = self.status("--repo-root", str(root))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        project = payload["project"]
        self.assertEqual(sorted(project), PROJECT_BLOCK_MEMBERS)
        self.assertEqual(project["project_id"], "fagenorn/nix-config")
        self.assertEqual(project["root"], str(root))
        self.assertEqual(project["project_schema_version"], 1)
        self.assertEqual(project["platform_interval"],
                         source_contract()["platform"])
        self.assertEqual(sorted(payload["compatibility"]),
                         COMPATIBILITY_MEMBERS)
        self.assertEqual(payload["compatibility"], {
            "compatible": True, "reason_code": None, "repair_id": None})
        self.assertIsNone(payload["fleet"])

    def test_an_out_of_range_platform_is_a_verdict_on_exit_zero(self):
        """D6: the committed contract declares [1.0.0, 2.0.0), so 0.9.0 is
        below its floor and 2.0.0 has already reached its exclusive ceiling."""
        cases = (
            ("0.9.0", "platform_too_old", "contract.platform.too_old"),
            ("2.0.0", "platform_too_new", "contract.platform.too_new"),
        )
        for version, reason_code, repair_id in cases:
            with self.subTest(platform_version=version):
                self.set_manifest(mutated_manifest(platform_version=version))
                code, payload, err = self.status(
                    "--repo-root", str(self.make_root()))
                self.assertEqual(code, 0, err)
                self.assertNotIn("error", payload)
                self.assertEqual(payload["compatibility"], {
                    "compatible": False, "reason_code": reason_code,
                    "repair_id": repair_id})
                self.assertEqual(payload["project"]["platform_interval"],
                                 source_contract()["platform"])
                self.assertEqual(payload["platform"]["platform_version"],
                                 version)

    def test_an_unsupported_project_schema_is_a_verdict_on_exit_zero(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, err = self.status(
            "--repo-root", str(self.make_root(contract)))
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(payload["project"]["project_schema_version"], 2)
        self.assertEqual(payload["compatibility"], {
            "compatible": False,
            "reason_code": "project_schema_unsupported",
            "repair_id": "contract.schema_version.unsupported"})

    def test_a_structurally_invalid_contract_refuses_exactly_like_resolve(self):
        """R3.5: the same one-object error, the same code, the same exit."""
        contract = source_contract()
        del contract["bindings"]["deploy"]
        root = self.make_root(contract)
        code, payload, err = self.status("--repo-root", str(root))
        self.assertEqual(code, 2, err)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertEqual((code, payload), self.resolve(root)[:2])

    def test_a_malformed_interval_refuses_rather_than_reporting(self):
        contract = source_contract()
        contract["platform"] = {"min_inclusive": "1.0", "max_exclusive": "2.0.0"}
        code, payload, err = self.status(
            "--repo-root", str(self.make_root(contract)))
        self.assertEqual(code, 2, err)
        self.assertEqual(payload["error"]["code"], "invalid_contract")
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/platform/min_inclusive"])

    def test_a_directory_with_no_contract_refuses_not_onboarded(self):
        empty = Path(tempfile.mkdtemp()).resolve()
        code, payload, err = self.status("--repo-root", str(empty))
        self.assertEqual(code, 2, err)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "not_onboarded")


class PlatformStatusFleetTest(ResolverTestCase):
    """R3.4 / D18: one verdict row per registered project, ordered by
    `project_id`, and never a refusal for a project the operator did not name.

    The registry is staged by hand here: Task 6 owns the writer, and this
    subcommand adds only the reader.
    """

    def fleet(self, *args: str) -> tuple[int, object, str]:
        code, out, err = run("platform-status", "--fleet", *args,
                             home=self.home)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def registered(self, project_id: str,
                   contract: object | None = None) -> tuple[dict, Path]:
        """A fixture root and the registry entry naming it."""
        root = self.make_root(contract)
        return {"project_id": project_id, "root": str(root)}, root

    def assert_reported_broken(self, row: dict, entry: dict) -> None:
        """The graceful row a broken registered project yields (R3.4)."""
        self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
        self.assertEqual(row["project_id"], entry["project_id"])
        self.assertEqual(row["root"], entry["root"])
        self.assertFalse(row["compatible"])
        self.assertEqual(row["reason_code"], "project_schema_unsupported")
        self.assertEqual(row["repair_id"], "contract.schema_version.unsupported")

    def test_an_absent_registry_is_the_empty_fleet(self):
        """And the state root is read, never created (R3.6)."""
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertEqual(payload["fleet"], [])
        self.assertIsNone(payload["project"])
        self.assertIsNone(payload["compatibility"])
        self.assertFalse((self.home / ".agents" / "state").exists())

    def test_two_registered_projects_are_ordered_by_project_id(self):
        alpha_contract = source_contract()
        alpha_contract["project"]["id"] = "fagenorn/alpha"
        beta_contract = source_contract()
        beta_contract["project"]["id"] = "fagenorn/beta"
        alpha, _ = self.registered("fagenorn/alpha", alpha_contract)
        beta, _ = self.registered("fagenorn/beta", beta_contract)
        # Written in descending order, so the order asserted below is the
        # reader's and not the file's.
        install_registry(self.home, registry(beta, alpha))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        rows = payload["fleet"]
        self.assertEqual([row["project_id"] for row in rows],
                         ["fagenorn/alpha", "fagenorn/beta"])
        for row, entry in zip(rows, (alpha, beta)):
            with self.subTest(project_id=entry["project_id"]):
                self.assertEqual(sorted(row), FLEET_ROW_MEMBERS)
                self.assertEqual(row["root"], entry["root"])
                self.assertEqual(row["project_schema_version"], 1)
                self.assertEqual(row["platform_interval"],
                                 source_contract()["platform"])
                self.assertTrue(row["compatible"])
                self.assertIsNone(row["reason_code"])
                self.assertIsNone(row["repair_id"])

    def test_a_registered_root_that_is_gone_is_a_reported_row(self):
        entry, root = self.registered("fagenorn/gone")
        shutil.rmtree(root)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        self.assertIsNone(row["project_schema_version"])
        self.assertIsNone(row["platform_interval"])

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root reads a 0000 file, so the case cannot be staged")
    def test_a_registered_root_with_an_unreadable_contract_is_a_reported_row(self):
        entry, root = self.registered("fagenorn/unreadable")
        contract = root / ".agents" / "project.json"
        self.addCleanup(contract.chmod, stat.S_IMODE(contract.stat().st_mode))
        contract.chmod(0o000)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        self.assertIsNone(row["project_schema_version"])
        self.assertIsNone(row["platform_interval"])

    def test_an_invalid_contract_is_reported_in_the_fleet_and_refused_when_named(self):
        """The split of R3.4 against R3.5, in one case so it cannot regress:
        the operator named this repository, so `--repo-root` refuses it; the
        registry named it, so `--fleet` describes it."""
        contract = source_contract()
        del contract["bindings"]["deploy"]
        entry, root = self.registered("fagenorn/invalid", contract)
        install_registry(self.home, registry(entry))
        code, payload, err = self.fleet()
        self.assertEqual(code, 0, err)
        self.assertNotIn("error", payload)
        self.assertEqual(len(payload["fleet"]), 1)
        row = payload["fleet"][0]
        self.assert_reported_broken(row, entry)
        # Only the verdict is negative: what the contract does declare is
        # reported as declared.
        self.assertEqual(row["project_schema_version"], 1)
        self.assertEqual(row["platform_interval"], source_contract()["platform"])
        named_code, named_out, named_err = run(
            "platform-status", "--repo-root", str(root), home=self.home)
        self.assertEqual(named_code, 2, named_err)
        self.assertEqual(json.loads(named_out)["error"]["code"],
                         "invalid_contract")

    def test_the_broken_rows_touch_neither_the_registry_nor_the_roots(self):
        """The three witnesses of resolver D21 over every broken row at once.

        The two git witnesses are taken with the unreadable fixture in its
        readable state either side of the run, because `git status` cannot read
        a 0000 file; a write by the resolver would still show, as changed bytes
        or as a changed mtime.
        """
        gone_entry, gone_root = self.registered("fagenorn/gone")
        unreadable_entry, unreadable_root = self.registered("fagenorn/unreadable")
        invalid_contract = source_contract()
        del invalid_contract["bindings"]["deploy"]
        invalid_entry, invalid_root = self.registered(
            "fagenorn/invalid", invalid_contract)
        shutil.rmtree(gone_root)
        live = (unreadable_root, invalid_root)
        for root in live:
            git(root, "add", "-A")
            git(root, "commit", "--quiet", "-m", "fixture")
        before = {str(root): (git(root, "status", "--porcelain"),
                              tree_snapshot(root)) for root in live}
        path = install_registry(self.home, registry(
            gone_entry, unreadable_entry, invalid_entry))
        before_registry = (path.read_bytes(), path.stat().st_mtime_ns)
        contract = unreadable_root / ".agents" / "project.json"
        mode = stat.S_IMODE(contract.stat().st_mode)
        contract.chmod(0o000)
        try:
            code, payload, err = self.fleet()
        finally:
            contract.chmod(mode)
        self.assertEqual(code, 0, err)
        self.assertEqual(len(payload["fleet"]), 3)
        for row in payload["fleet"]:
            with self.subTest(project_id=row["project_id"]):
                self.assertFalse(row["compatible"])
        for root in live:
            with self.subTest(root=str(root)):
                self.assertEqual(
                    (git(root, "status", "--porcelain"), tree_snapshot(root)),
                    before[str(root)])
        self.assertFalse(gone_root.exists())
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns),
                         before_registry)

    def test_a_malformed_registry_refuses_as_resolver_failure(self):
        """The registry is platform-written state, so a corrupt one is an
        installation defect and never an assumed empty fleet."""
        cases = (
            ("not JSON", "{"),
            ("not an object", "[]"),
            ("an unexpected member",
             {"schema_version": 1, "projects": [], "pinned": True}),
            ("a missing member", {"schema_version": 1}),
            ("a non-array projects", {"schema_version": 1, "projects": {}}),
            ("an entry that is not an object",
             {"schema_version": 1, "projects": ["a/b"]}),
            ("an entry missing root",
             {"schema_version": 1, "projects": [{"project_id": "a/b"}]}),
            ("an entry with an unexpected member",
             {"schema_version": 1,
              "projects": [{"project_id": "a/b", "root": "/x", "pinned": True}]}),
        )
        for label, content in cases:
            with self.subTest(registry=label):
                install_registry(self.home, content)
                code, payload, err = self.fleet()
                self.assertEqual(code, 2, err)
                self.assertEqual(sorted(payload), ["error"])
                error = payload["error"]
                self.assertEqual(sorted(error),
                                 ["code", "repair_id", "violations"])
                self.assertEqual(error["code"], "resolver_failure")
                self.assertTrue(error["repair_id"].startswith(
                    "platform.registry."), error["repair_id"])
                self.assertTrue(error["violations"])
                pointers = [v["pointer"] for v in error["violations"]]
                self.assertEqual(pointers, sorted(pointers))
                for entry in error["violations"]:
                    self.assertEqual(sorted(entry), ["message", "pointer"])

    def test_repo_root_and_fleet_compose(self):
        entry, _ = self.registered("fagenorn/registered")
        install_registry(self.home, registry(entry))
        named = self.make_root()
        code, payload, err = self.fleet("--repo-root", str(named))
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), PLATFORM_STATUS_MEMBERS)
        self.assertEqual(payload["project"]["root"], str(named))
        self.assertTrue(payload["compatibility"]["compatible"])
        self.assertEqual([row["project_id"] for row in payload["fleet"]],
                         ["fagenorn/registered"])


if __name__ == "__main__":
    unittest.main()
