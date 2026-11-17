"""The manager's permission mode per project (#1151).

Run: just agent-workflow-tests
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from agent_tools.console import permission
from agent_tools.project_contract import resolve_project
from .accounts_sandbox import setUpModule, tearDownModule  # noqa: F401 -- module fixtures (#1027)

REPO_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = REPO_ROOT / "home/common/claude-code/lifecycle_guard.py"
BYPASS = "bypassPermissions"
AUTO = "auto"


def snap(status, commands=(), key_files=(), mcp_tools=(), read_only=()):
    """A resolved snapshot declaring `status`; `commands` and `read_only` map a command id to its argv."""
    production = {"status": status}
    if status == "declared":
        production.update(
            changes={"commands": list(commands), "key_files": list(key_files),
                     "mcp_tools": list(mcp_tools)},
            read_only={"commands": list(read_only), "mcp_tools": []}, release_profile="r")
    return {"production": production,
            "bindings": {"commands": {name: {"argv": list(argv)}
                                      for name, argv in {**dict(read_only), **dict(commands)}.items()}}}


def row(project_id, production=True):
    value = {
        "default_branch": "main",
        "integration_branch": "main",
        "required_checks": [],
        "evidence": {"project_id": project_id},
    }
    if production:
        value["production"] = {
            "changes": [], "read_only": [], "release_profile": "r", "key_files": [], "mcp_tools": [],
        }
    return value


def document(rows):
    return {"derived_repositories": rows, "derivation": {"schema_version": 5}}


def write(directory, content, name="policy.json"):
    path = Path(directory) / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content)
    else:
        path.write_text(json.dumps(content))
    return path


def load_guard():
    spec = importlib.util.spec_from_file_location("lifecycle_guard_source", GUARD_SOURCE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def padded(rows):
    text = json.dumps(document(rows))
    return text + " " * ((1 << 20) + 1 - len(text))


def dropped_matching_row():
    return document({"owner/p01": {**row("owner/p01"), "production": {}}})


def bad_slug_key():
    return document({"owner/p01": row("owner/p01"), "not-a-slug": row("owner/p02")})


def bad_mcp_tools():
    other = row("owner/p02")
    other["production"] = {**other["production"], "mcp_tools": ["x"]}
    return document({"owner/p01": row("owner/p01"), "owner/p02": other})


def with_activation(value, changes=("deploy",)):
    """A policy whose one row's production carries `console_activation` `value`."""
    entry = row("owner/p01")
    entry["production"] = {
        **entry["production"],
        "changes": [{"id": name, "argv": ["x"]} for name in changes],
        "console_activation": value,
    }
    return document({"owner/p01": entry})


class PermissionReadTest(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.tmp = Path(directory.name)

    def read(self, snapshot, policy_path):
        return permission.read(
            "owner/p01", "/srv/p01", resolve=lambda root: snapshot, policy_path=policy_path)

    def test_a_project_with_no_production_runs_in_auto_until_a_bypass_manager_can_be_woken(self):
        result = self.read(snap("none"), self.tmp / "absent.json")
        self.assertEqual(
            result, permission.Permission("auto", "waking a bypass manager is not yet possible"))
        self.assertEqual(result.text, "auto: waking a bypass manager is not yet possible")

    def test_declared_rules_in_the_guards_policy_run_in_auto_until_a_bypass_manager_can_be_woken(self):
        path = write(self.tmp, document({"owner/p01": row("owner/p01")}))
        result = self.read(snap("declared"), path)
        self.assertEqual(
            result, permission.Permission("auto", "waking a bypass manager is not yet possible"))
        self.assertEqual(result.text, "auto: waking a bypass manager is not yet possible")

    def test_a_row_older_than_the_declaration_runs_in_auto(self):
        def stale(**members):
            value = row("owner/p01")
            value["production"] = {**value["production"], **members}
            return document({"owner/p01": value})

        deploy = {"id": "deploy", "argv": ["kubectl", "apply"]}
        declared = snap("declared", commands={"deploy": ["kubectl", "apply"]},
                        key_files=["k8s/*.yaml"], mcp_tools=["mcp__prod__deploy"])
        current = stale(changes=[deploy], key_files=["k8s/*.yaml"], mcp_tools=["mcp__prod__deploy"])
        cases = [
            ("new mcp tool", snap("declared", mcp_tools=["mcp__prod__deploy"]), stale()),
            ("new command", snap("declared", commands={"deploy": ["kubectl", "apply"]}), stale()),
            ("changed argv", snap("declared", commands={"deploy": ["kubectl", "delete"]}),
             stale(changes=[deploy])),
            ("new key file", snap("declared", key_files=["k8s/*.yaml"]), stale()),
            ("new read-only command",
             snap("declared", read_only={"status": ["kubectl", "rollout", "status"]}), stale()),
            ("changed read-only argv",
             snap("declared", commands={"deploy": ["kubectl"]},
                  read_only={"status": ["kubectl", "rollout", "status"]}),
             stale(changes=[{"id": "deploy", "argv": ["kubectl"]}],
                   read_only=[{"id": "status", "argv": ["kubectl", "rollout"]}])),
            ("another mcp tool", declared,
             stale(changes=[deploy], key_files=["k8s/*.yaml"], mcp_tools=["mcp__prod__other"])),
        ]
        for name, snapshot, content in cases:
            with self.subTest(name):
                self.assertEqual(self.read(snapshot, write(self.tmp, content)),
                                 permission.Permission(AUTO, permission.NOT_ENFORCED))
        with self.subTest("a row that holds every declared rule"):
            self.assertEqual(self.read(declared, write(self.tmp, current)),
                             permission.Permission(AUTO, permission.WAKE_BLOCKED))
        with self.subTest("a snapshot too thin to compare"):
            self.assertEqual(
                self.read({"production": {"status": "declared"}}, write(self.tmp, current)),
                permission.Permission(AUTO, permission.NOT_ENFORCED))

    def test_the_declared_rules_are_what_the_guard_compiles(self):
        from agent_tools.guard import guard_policy

        snapshot = snap("declared", commands={"deploy": ["kubectl", "apply"]},
                        key_files=["k8s/*.yaml"], mcp_tools=["mcp__prod__deploy"],
                        read_only={"status": ["kubectl", "rollout", "status"]})
        compiled = guard_policy.production_row(snapshot)
        declared = permission._declared_changes(snapshot)
        self.assertEqual(declared, {member: compiled[member]
                                    for member in ("changes", "read_only", "key_files", "mcp_tools")})
        self.assertTrue(permission._covers(compiled, declared))

    def test_declared_rules_the_guard_does_not_hold_run_in_auto(self):
        (self.tmp / "dir").mkdir()
        cases = [
            ("no production member", document({"owner/p01": row("owner/p01", production=False)}),
             permission.NOT_ENFORCED),
            ("another project", document({"owner/p02": row("owner/p02")}), permission.NOT_ENFORCED),
            ("no rows", document({}), permission.NOT_ENFORCED),
            ("dropped matching row", dropped_matching_row(), permission.POLICY_UNREADABLE),
            ("bad slug beside a match", bad_slug_key(), permission.POLICY_UNREADABLE),
            ("bad mcp tools beside a match", bad_mcp_tools(), permission.POLICY_UNREADABLE),
            ("missing file", None, permission.POLICY_UNREADABLE),
            ("directory", self.tmp / "dir", permission.POLICY_UNREADABLE),
            ("not json", "not json", permission.POLICY_UNREADABLE),
            ("missing derivation", {"derived_repositories": {}}, permission.POLICY_UNREADABLE),
            ("rows not a dict", {"derived_repositories": [], "derivation": {}},
             permission.POLICY_UNREADABLE),
            ("oversize", padded({"owner/p01": row("owner/p01")}), permission.POLICY_UNREADABLE),
        ]
        for name, content, reason in cases:
            with self.subTest(name):
                if content is None:
                    path = self.tmp / "absent.json"
                elif isinstance(content, Path):
                    path = content
                else:
                    path = write(self.tmp, content)
                self.assertEqual(self.read(snap("declared"), path), permission.Permission(AUTO, reason))

    def test_an_undeclared_production_runs_in_auto_whatever_the_policy_holds(self):
        path = write(self.tmp, document({"owner/p01": row("owner/p01")}))
        result = self.read(snap("not_declared"), path)
        self.assertEqual(result, permission.Permission("auto", "no production rules declared"))
        self.assertEqual(result.text, "auto: no production rules declared")

    def test_only_a_declared_production_reads_the_policy(self):
        with mock.patch.object(permission, "policy_rows", side_effect=AssertionError):
            for snapshot, expected in (
                (snap("none"), permission.Permission(AUTO, permission.WAKE_BLOCKED)),
                (snap("not_declared"), permission.Permission(AUTO, permission.NOT_DECLARED)),
            ):
                with self.subTest(snapshot["production"]["status"]):
                    self.assertEqual(self.read(snapshot, self.tmp / "absent.json"), expected)

    def test_a_contract_that_does_not_resolve_runs_in_auto(self):
        expected = permission.Permission("auto", "the project's contract does not resolve")

        def refuse(root):
            raise resolve_project.ContractError("not_onboarded", "x", [])

        with self.subTest("injected"):
            self.assertEqual(
                permission.read("owner/p01", "/srv/p01", resolve=refuse,
                                policy_path=self.tmp / "absent.json"), expected)
        with self.subTest("real resolver"):
            self.assertEqual(permission.read("owner/p01", str(self.tmp)), expected)
        with self.subTest("empty snapshot"):
            self.assertEqual(self.read({}, self.tmp / "absent.json"), expected)

    def test_the_policy_is_the_file_the_guard_reads(self):
        self.assertEqual(
            permission.policy_file(),
            Path(os.environ["HOME"]) / ".agents" / "state" / "guard" / "policy.json")

    def test_a_logged_mode_round_trips_and_a_malformed_one_is_refused(self):
        mode = permission.Permission(BYPASS, permission.RULES_IN_PLACE)
        self.assertEqual(permission.from_payload(mode.payload()), mode)
        for value in (None, {"mode": "plan", "reason": "x"}, {"mode": "auto", "reason": ""},
                      {"mode": "auto"}, {"mode": "auto", "reason": "x", "extra": 1}, "auto"):
            with self.subTest(value=value):
                self.assertIsNone(permission.from_payload(value))
        self.assertEqual(
            permission.FALLBACK, permission.Permission("auto", "the production rules could not be read"))


class PolicyParityTest(unittest.TestCase):
    def test_the_policy_is_read_exactly_as_the_guard_reads_it(self):
        guard = load_guard()
        for name in ("COMPILED_POLICY_KEYS", "DERIVED_ROW_KEYS", "DERIVED_ROW_OPTIONAL_KEYS",
                     "PRODUCTION_KEYS", "PRODUCTION_OPTIONAL_KEYS", "PRODUCTION_COMMAND_KEYS",
                     "POLICY_MAX_BYTES"):
            with self.subTest(name):
                self.assertEqual(getattr(permission, name), getattr(guard, name))
        for name in ("MCP_TOOL_NAME", "SLUG_PATTERN", "REF_NAME_PATTERN"):
            with self.subTest(name):
                self.assertEqual(getattr(permission, name).pattern, getattr(guard, name).pattern)

        def mutated(**changes):
            value = row("owner/p01")
            value.update(changes)
            return document({"owner/p01": value})

        def with_command(**command):
            value = row("owner/p01")
            value["production"] = {**value["production"], "changes": [{"id": "a", **command}]}
            return document({"owner/p01": value})

        no_evidence = row("owner/p01")
        del no_evidence["evidence"]
        table = {
            "valid": document({"owner/p01": row("owner/p01")}),
            "no production": document({"owner/p01": row("owner/p01", production=False)}),
            "dropped matching row": dropped_matching_row(),
            "bad slug key": bad_slug_key(),
            "bad mcp tools": bad_mcp_tools(),
            "no evidence": document({"owner/p01": no_evidence}),
            "activation names a change": with_activation("deploy"),
            "activation names no change": with_activation("other"),
            "activation empty": with_activation(""),
            "activation not a string": with_activation(7),
            "activation with no changes": with_activation("deploy", changes=()),
            "bad branch": mutated(default_branch="bad branch"),
            "duplicate checks": mutated(required_checks=["a", "a"]),
            "empty argv": with_command(argv=[]),
            "good argv": with_command(argv=["x"]),
            "derivation list": {"derived_repositories": {}, "derivation": []},
            "derivation null": {"derived_repositories": {}, "derivation": None},
            "extra key": {**document({}), "extra": 1},
            "deeply nested": "[" * 100000,
            "not utf-8": b"\xff",
            "oversize": padded({"owner/p01": row("owner/p01")}),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {name: write(root, content, f"{index}.json")
                     for index, (name, content) in enumerate(table.items())}
            (root / "dir").mkdir()
            paths["directory"] = root / "dir"
            os.mkfifo(root / "fifo")
            paths["fifo"] = root / "fifo"
            paths["missing"] = root / "missing.json"
            for name, path in paths.items():
                with self.subTest(name):
                    loaded, why = guard.load_compiled_policy(path)
                    self.assertEqual(permission.policy_rows(path), loaded if why is None else None)


if __name__ == "__main__":
    unittest.main()
