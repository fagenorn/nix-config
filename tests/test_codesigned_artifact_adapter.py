"""The codesigned-artifact adapter (issue 547). Run: just agent-workflow-tests"""
import ast
import contextlib
import inspect as introspect
import os
import plistlib
import unittest
from pathlib import Path
from unittest import mock

from agent_tools import codesigned_artifact_adapter as adapter, release_adapter
from .host_world import IDENTITY, OTHER, HostWorld

PATH = "~/Library/Application Support/Notifier/Notifier.app"
CONFIG = {"source": "build/Notifier.app", "identity_prefix": "Apple Development",
          "identity_env": "NOTIFIER_SIGNING_IDENTITY", "adhoc_fallback": False}
DESCRIPTOR = {"name": "codesigned-artifact", "adapter_contract_version": "1.0.0",
              "operations": {"install": {
                  "mode": "materialize", "support": "supported", "inspect": "supported",
                  "reason": None, "mutability": "in_place", "config_schema_version": 1,
                  "config_schema": {"members": {"adhoc_fallback": "boolean", "identity_env": "string",
                                                "identity_prefix": "string", "source": "string"},
                                    "required": ["adhoc_fallback", "identity_prefix", "source"]},
                  "effects": ["reversible_no_incremental_spend", "irreversible"],
                  "recovery_capable": False, "candidate_members": []}},
              "predicates": {"publication_visible": {"support": "supported", "reason": None},
                             "running_subject_identity": {"support": "unsupported",
                                                          "reason": "no_activation_mode"}},
              "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
              "target_kinds": {"installed_bundle": ["path"]},
              "credential_classes": ["codesigning_identity"],
              "executables": ["codesign", "git", "security"], "host_capacity": "not_required"}


class Case(unittest.TestCase):
    def setUp(self):
        self.world = HostWorld(self)
        self.world.environ(NOTIFIER_SIGNING_IDENTITY=None)
        self.world.identities(IDENTITY)
        self.candidate = {"version": "v1.2.3", "commit": self.world.head()}

    def parameters(self, **config):
        return {"action": "notifier", "operation": "install",
                "target": {"handle": "notifier", "kind": "installed_bundle", "path": PATH},
                "candidate": dict(self.candidate), "config": {**CONFIG, **config}}

    def effect(self, parameters=None):
        return adapter.inspect({"kind": "effect", "operation": "install",
                                "parameters": parameters or self.parameters()})

    def visible(self, parameters=None):
        return adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                "operation": "install", "parameters": parameters or self.parameters()})

    def install(self, stamp="candidate", identity=IDENTITY[0]):
        stamp = (self.candidate["version"], self.candidate["commit"]) if stamp == "candidate" else stamp
        return self.world.installed(PATH[2:], stamp=stamp, identity=identity)

    def linked_ancestor(self):
        """`~/Library/Application Support` links outside `$HOME` to a signed candidate bundle
        and stale staging siblings (issue 547 D26); returns that outside directory."""
        outside = self.world.root / "outside"
        installed = self.install()
        os.makedirs(outside)
        os.rename(installed.parent.parent, outside / "Application Support")
        (outside / "Application Support/Notifier/.Notifier.app.release-staging").mkdir()
        (outside / "Application Support/Notifier/.Notifier.app.release-previous").mkdir()
        (self.world.home / "Library/Application Support").symlink_to(outside / "Application Support")
        return outside


class DescribeTest(Case):
    def test_descriptor_is_exact_valid_fresh_and_registered(self):
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])
        adapter.describe()["operations"].clear()
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertIs(release_adapter.REGISTRY["codesigned-artifact"], adapter)


class ClassificationTest(Case):
    def test_each_row_of_the_inspect_table(self):
        def tamper():
            path = self.install()
            (path / "Contents/MacOS/notifier").write_bytes(b"changed")
        rows = (
            ("no entry", lambda: None, ("absent", "bundle_absent"), ("unsatisfied", "ref_absent")),
            ("symlink", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).symlink_to(self.world.checkout),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("regular file", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).write_text("x"),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("symlinked ancestor", self.linked_ancestor,
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("regular-file ancestor", lambda: (self.world.home / "Library").mkdir() or
             (self.world.home / "Library/Application Support").write_text("x"),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("no stamp", lambda: self.install(stamp=None), ("absent", "bundle_unmanaged"),
             ("unsatisfied", "subject_mismatch")),
            ("other release", lambda: self.install(stamp=("v1.2.2", "f" * 40)),
             ("absent", "bundle_other_release"), ("unsatisfied", "subject_mismatch")),
            ("unsigned", lambda: self.install(identity=None), ("diverged", "signature_invalid"),
             ("unsatisfied", "digest_mismatch")),
            ("unloadable plist", lambda: self.install() and (
                self.world.home / PATH[2:] / "Contents/Info.plist").write_bytes(
                b'<?xml version="1.0"?><plist version="1.0"><dict><key>a</key><date>x</date></dict></plist>'),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("tampered", tamper, ("diverged", "signature_invalid"), ("unsatisfied", "digest_mismatch")),
            ("ad hoc refused", lambda: self.install(identity="-"), ("diverged", "signature_policy"),
             ("unsatisfied", "subject_mismatch")),
            ("signed", lambda: self.install(), ("satisfied", "installed"), ("satisfied", "installed")),
            ("verify exit 2", lambda: self.install() and self.world.fail("codesign", "verify", exit=2),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("display fails", lambda: self.install() and self.world.fail("codesign", "display", exit=1),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("codesign missing", lambda: self.install() and (self.world.bin / "codesign").unlink(),
             ("unknown", "executable_missing"), ("unknown", "store_unreachable")))
        for name, arrange, effect, visible in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                before = self.world.tree()
                observed = self.effect()
                self.assertEqual((observed["outcome"], observed["reason"]), effect)
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.visible()
                self.assertEqual((predicate["outcome"], predicate["reason"]), visible)
                self.assertEqual(sorted(predicate), ["observed_at", "outcome", "reason", "references"])
                self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])
                self.assertEqual(self.world.tree(), before)
                self.assertEqual({c["tool"] for c in self.world.calls()} - {"codesign"}, set())

    def test_ad_hoc_is_installed_when_the_policy_allows_it(self):
        self.install(identity="-")
        observed = self.effect(self.parameters(adhoc_fallback=True))
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "installed"))
        self.assertEqual(observed["facts"]["signature"],
                         {"identifier": "dev.example.notifier", "authority": None,
                          "team_identifier": None, "adhoc": True})

    def test_a_verify_past_the_budget_is_lookup_timeout(self):
        self.install()
        self.world.fail("codesign", "verify", exit=0, sleep=3)
        with mock.patch.object(adapter, "INSPECT_BUDGET_SECONDS", 1):
            observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("unknown", "lookup_timeout"))
        self.assertEqual(observed["facts"]["detail"], "")


class InvokeTest(Case):
    def invoke(self, parameters=None):
        return adapter.invoke({"kind": "effect", "operation": "install",
                               "parameters": parameters or self.parameters()})

    def signed_with(self):
        """The identity argument of every `codesign --sign` call, in order."""
        return [c["argv"][2] for c in self.world.calls("codesign") if "--sign" in c["argv"]]

    def installed_plist(self):
        with open(self.world.home / PATH[2:] / "Contents/Info.plist", "rb") as handle:
            return plistlib.load(handle)

    def test_installs_a_stamped_signed_bundle_then_inspects_satisfied(self):
        self.world.bundle()
        installed = self.world.home / PATH[2:]
        self.assertEqual(self.invoke(), {"result": "accepted", "error_class": None,
                                         "reference": str(installed)})
        self.assertEqual(self.installed_plist(), {
            "CFBundleIdentifier": "dev.example.notifier", "CFBundleName": "Notifier",
            "AgentReleaseVersion": "v1.2.3", "AgentReleaseCommit": self.candidate["commit"]})
        self.assertEqual(os.readlink(installed / "Contents/Resources/current"), "../MacOS/notifier")
        signs = [c["argv"] for c in self.world.calls("codesign") if "--sign" in c["argv"]]
        self.assertEqual([argv[:3] for argv in signs], [["--force", "--sign", IDENTITY[0]]])
        self.assertEqual((Path(signs[0][3]).name, Path(signs[0][3]).parent.name),
                         ("Notifier.app", ".Notifier.app.release-staging"))
        self.assertEqual(sorted(p.name for p in installed.parent.iterdir()), ["Notifier.app"])
        self.assertEqual(self.world.calls("claude-bash-lifecycle-guard"), [])
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "installed"))

    def test_each_refusal_leaves_the_installed_bundle_unchanged(self):
        date_plist = (b'<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict>'
                      b'<key>CFBundleIdentifier</key><string>dev.example.notifier</string>'
                      b'<key>Built</key><date>x</date></dict></plist>')
        huge_plist = date_plist.replace(b"<date>x</date>", b"<integer>" + b"9" * 23 + b"</integer>")

        def old_release():
            self.install(stamp=("v1.2.2", "f" * 40))

        def operation(stack):
            parameters = self.parameters()
            parameters["operation"] = "publish"
            return {"kind": "effect", "operation": "publish", "parameters": parameters}

        def target(stack):
            parameters = self.parameters()
            parameters["target"]["path"] = "/abs/N.app"
            return {"kind": "effect", "operation": "install", "parameters": parameters}

        def uid_zero(stack):
            stack.enter_context(mock.patch.object(adapter.os, "getuid", return_value=0))

        def unknown_commit(stack):
            self.candidate["commit"] = "f" * 40

        def outside_directory(stack):
            os.chdir(self.world.home)

        def linked_plist(stack):
            plist = self.world.checkout / "build/Notifier.app/Contents/Info.plist"
            outside = self.world.root / "outside.plist"
            outside.write_bytes(plistlib.dumps({"CFBundleIdentifier": "dev.example.notifier"}))
            plist.unlink()
            plist.symlink_to(outside)

        def linked_contents(stack):
            contents = self.world.checkout / "build/Notifier.app/Contents"
            contents.rename(self.world.root / "OutsideContents")
            contents.symlink_to(self.world.root / "OutsideContents")

        def source_plist(content):
            def arrange(stack):
                (self.world.checkout / "build/Notifier.app/Contents/Info.plist").write_bytes(content)
            return arrange

        def list_plist(stack):
            plist = self.world.checkout / "build/Notifier.app/Contents/Info.plist"
            plist.write_bytes(plistlib.dumps([1]))

        def nobody(stack):
            self.world.environ(NOTIFIER_SIGNING_IDENTITY="Nobody")
            return {"kind": "effect", "operation": "install",
                    "parameters": self.parameters(adhoc_fallback=True)}

        def linked_install(stack):
            installed = self.world.home / PATH[2:]
            installed.parent.mkdir(parents=True)
            installed.symlink_to(self.world.checkout)

        def sign_fails(stack):
            old_release()
            self.world.fail("codesign", "sign", exit=1, stderr="errSecInternalComponent")

        def verify_fails(stack):
            old_release()
            self.world.fail("codesign", "verify", exit=1)

        def sign_times_out(stack):
            old_release()
            self.world.fail("codesign", "sign", exit=0, sleep=3)
            stack.enter_context(mock.patch.object(adapter, "INVOKE_BUDGET_SECONDS", 1))

        def swap_fails(stack):
            stack.enter_context(mock.patch.object(adapter.os, "rename", refuse_install))

        real_rename = os.rename

        def refuse_install(source, destination):
            if str(destination) == str(self.world.home / PATH[2:]):
                raise OSError("rename refused")
            return real_rename(source, destination)

        # (name, arrange(stack) -> request or None, (result, error_class), fragment, children, staging)
        rows = (
            ("target path", target, ("rejected", "invalid_input"), "", False, False),
            ("operation", operation, ("rejected", "unsupported_operation"), "publish", False, False),
            ("uid 0", uid_zero, ("rejected", "authorization_denied"), "", False, False),
            ("other commit", unknown_commit, ("rejected", "precondition_failed"), "checkout",
             "no-sign", False),
            ("dirty", lambda stack: self.world.dirty(), ("rejected", "precondition_failed"),
             "checkout", "no-sign", False),
            ("no checkout", outside_directory, ("rejected", "provider_unavailable"), "checkout",
             "no-sign", False),
            ("no bundle", lambda stack: (self.world.checkout / "build/Notifier.app").rename(
                self.world.root / "moved.app"), ("rejected", "precondition_failed"), "source",
             "no-sign", False),
            ("linked plist", linked_plist, ("rejected", "precondition_failed"), "source",
             "no-sign", False),
            ("linked contents", linked_contents, ("rejected", "precondition_failed"), "source",
             "no-sign", False),
            ("date plist", source_plist(date_plist), ("rejected", "precondition_failed"), "source",
             "no-sign", False),
            ("overflow plist", source_plist(huge_plist), ("rejected", "precondition_failed"),
             "stage", "no-sign", True),
            ("list plist", list_plist, ("rejected", "precondition_failed"), "source",
             "no-sign", False),
            ("security fails", lambda stack: self.world.identities(IDENTITY, exit=1,
                                                                  stderr="keychain locked"),
             ("rejected", "provider_unavailable"), "keychain locked", "no-sign", False),
            ("no identity", lambda stack: self.world.identities(OTHER),
             ("rejected", "precondition_failed"), "no_signing_identity", "no-sign", False),
            ("env names nobody", nobody, ("rejected", "precondition_failed"),
             "no_signing_identity", "no-sign", False),
            ("linked install", linked_install, ("rejected", "precondition_failed"), "install",
             "no-sign", False),
            ("sign fails", sign_fails, ("rejected", "precondition_failed"),
             "errSecInternalComponent", True, True),
            ("verify fails", verify_fails, ("rejected", "precondition_failed"), "verify",
             True, True),
            ("sign times out", sign_times_out, ("rejected", "transient_transport"), "sign",
             True, True),
            ("rename refused", swap_fails, ("rejected", "provider_unavailable"), "swap",
             True, True),
        )
        for name, arrange, expected, fragment, children, staging in rows:
            with self.subTest(row=name), contextlib.ExitStack() as stack:
                self.setUp()
                self.world.bundle()
                request = arrange(stack)
                before, started = self.world.tree(), len(self.world.calls())
                signed_before = len(self.signed_with())
                result = adapter.invoke(request) if isinstance(request, dict) else self.invoke()
                self.assertEqual((result["result"], result["error_class"]), expected)
                self.assertIn(fragment, result["reference"])
                self.assertEqual(release_adapter.invoke_result_problems(result), [])
                installed = self.world.home / PATH[2:]
                self.assertFalse((installed.parent / ".Notifier.app.release-staging").exists())
                if staging:
                    prefix = PATH[2:]
                    kept = {k: v for k, v in before.items() if k.startswith(prefix)}
                    self.assertEqual({k: v for k, v in self.world.tree().items()
                                      if k.startswith(prefix)}, kept)
                else:
                    self.assertEqual(self.world.tree(), before)
                if children is False:
                    self.assertEqual(len(self.world.calls()), started)
                else:
                    signed = len(self.signed_with()) - signed_before
                    self.assertEqual(signed, 1 if children is True else 0)
                if name == "linked plist":
                    self.assertEqual((self.world.root / "outside.plist").read_bytes(),
                                     plistlib.dumps({"CFBundleIdentifier": "dev.example.notifier"}))
                if name == "linked install":
                    self.assertEqual(os.readlink(installed), str(self.world.checkout))

    def test_identity_selection_and_replacement(self):
        def stale_siblings():
            parent = (self.world.home / PATH[2:]).parent
            for name in (".Notifier.app.release-staging", ".Notifier.app.release-previous"):
                (parent / name).mkdir()

        cases = (
            ("env hash", lambda: (self.world.identities(IDENTITY, OTHER),
                                  self.world.environ(NOTIFIER_SIGNING_IDENTITY=OTHER[1])),
             {}, OTHER[0]),
            ("env hash lowercase", lambda: (self.world.identities(IDENTITY, OTHER),
                                            self.world.environ(NOTIFIER_SIGNING_IDENTITY=OTHER[0].lower())),
             {}, OTHER[0]),
            ("empty env", lambda: (self.world.identities(IDENTITY, OTHER),
                                   self.world.environ(NOTIFIER_SIGNING_IDENTITY="")), {}, IDENTITY[0]),
            ("ad hoc", lambda: self.world.identities(), {"adhoc_fallback": True}, "-"),
            ("old release and stale siblings",
             lambda: (self.install(stamp=("v1.2.2", "f" * 40)), stale_siblings()), {}, IDENTITY[0]),
        )
        for name, arrange, config, identity in cases:
            with self.subTest(case=name):
                self.setUp()
                self.world.bundle()
                arrange()
                baseline = len(self.signed_with())
                result = self.invoke(self.parameters(**config))
                self.assertEqual(result["result"], "accepted")
                self.assertEqual(self.signed_with()[baseline:], [identity])
                self.assertEqual(self.installed_plist()["AgentReleaseVersion"], "v1.2.3")
                self.assertEqual(self.installed_plist()["AgentReleaseCommit"], self.candidate["commit"])
                self.assertEqual(sorted(p.name for p in (self.world.home / PATH[2:]).parent.iterdir()),
                                 ["Notifier.app"])
                observed = self.effect(self.parameters(**config))
                self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "installed"))
        with self.subTest(case="binary plist"):
            self.setUp()
            self.world.bundle(binary=True)
            self.assertEqual(self.invoke()["result"], "accepted")
            self.assertTrue((self.world.home / PATH[2:] / "Contents/Info.plist")
                            .read_bytes().startswith(b"bplist00"))

    def test_an_ancestor_outside_home_is_refused_before_any_write(self):
        """Issue 547 D26: no component between `$HOME` and the install path's parent is a link."""
        def outside_tree(root):
            entries = {}
            for current, directories, files in os.walk(root):
                for name in directories + files:
                    full = Path(current) / name
                    entries[str(full.relative_to(root))] = (
                        "dir" if full.is_dir() and not full.is_symlink() else full.read_bytes()
                        if not full.is_symlink() else os.readlink(full))
            return entries

        def regular_file():
            (self.world.home / "Library").mkdir()
            (self.world.home / "Library/Application Support").write_text("x")
            return None
        for name, arrange in (("symlink", self.linked_ancestor), ("regular file", regular_file)):
            with self.subTest(ancestor=name):
                self.setUp()
                self.world.bundle()
                outside = arrange()
                before = outside_tree(outside) if outside else None
                home_before, signed = self.world.tree(), len(self.signed_with())
                result = self.invoke()
                self.assertEqual((result["result"], result["error_class"]),
                                 ("rejected", "precondition_failed"))
                self.assertTrue(result["reference"].startswith("install path: "), result["reference"])
                self.assertEqual(release_adapter.invoke_result_problems(result), [])
                self.assertEqual(len(self.signed_with()), signed)
                self.assertEqual(self.world.tree(), home_before)
                if outside:
                    self.assertEqual(outside_tree(outside), before)
                    self.assertTrue((outside / "Application Support/Notifier/"
                                     ".Notifier.app.release-staging").is_dir())

    def test_a_failed_swap_after_the_old_bundle_moved_is_unknown(self):
        self.world.bundle()
        self.install(stamp=("v1.2.2", "f" * 40))
        real_rename, installed = os.rename, str(self.world.home / PATH[2:])

        def refuse_install(source, destination):
            if str(destination) == installed:
                raise OSError("rename refused")
            return real_rename(source, destination)

        with mock.patch.object(adapter.os, "rename", refuse_install):
            result = self.invoke()
        self.assertEqual((result["result"], result["error_class"]), ("unknown", "transient_transport"))
        self.assertEqual(release_adapter.invoke_result_problems(result), [])
        parent = Path(installed).parent
        with open(parent / ".Notifier.app.release-previous/Contents/Info.plist", "rb") as handle:
            self.assertEqual(plistlib.load(handle)["AgentReleaseVersion"], "v1.2.2")
        with open(parent / ".Notifier.app.release-staging/Notifier.app/Contents/Info.plist",
                  "rb") as handle:
            self.assertEqual(plistlib.load(handle)["AgentReleaseVersion"], "v1.2.3")
        self.assertFalse(Path(installed).exists())


class ObservationTest(Case):
    def test_a_satisfied_observation_carries_stamp_and_signature(self):
        path = str(self.world.home / PATH[2:])
        self.install()
        observed = self.effect()
        self.assertEqual(observed["observed_subject"], {
            "version": "v1.2.3", "commit": self.world.head(), "identifier": "dev.example.notifier",
            "authority": IDENTITY[1]})
        self.assertEqual(observed["references"], [path])
        self.assertEqual(observed["facts"], {
            "path": path, "stamp": {"version": "v1.2.3", "commit": self.world.head()},
            "signature": {"identifier": "dev.example.notifier", "authority": IDENTITY[1],
                          "team_identifier": "TEAMID0001", "adhoc": False}})

    def test_stderr_detail_is_bounded(self):
        self.install()
        self.world.fail("codesign", "verify", exit=2, stderr="e" * 1000)
        self.assertEqual(len(self.effect()["facts"]["detail"]), 240)


class ShapeTest(Case):
    def test_requests_outside_the_closed_shape_start_no_child(self):
        def with_(mutate):
            parameters = self.parameters()
            mutate(parameters)
            return parameters

        def path(value):
            return lambda p: p["target"].update(path=value)

        mutations = {
            "target kind": lambda p: p["target"].update(kind="github_repository"),
            "target extra": lambda p: p["target"].update(domain="gui/501"),
            "absolute path": path("/Users/x/N.app"),
            "dotdot path": path("~/a/../N.app"),
            "empty segment": path("~//N.app"),
            "dot segment": path("~/./N.app"),
            "control path": path("~/N\n.app"),
            "version": lambda p: p["candidate"].update(version="1.2.3"),
            "uppercase commit": lambda p: p["candidate"].update(commit="A" * 40),
            "missing source": lambda p: p["config"].pop("source"),
            "extra config": lambda p: p["config"].update(entitlements="x"),
            "absolute source": lambda p: p["config"].update(source="/abs/N.app"),
            "dotdot source": lambda p: p["config"].update(source="build/../N.app"),
            "bad env name": lambda p: p["config"].update(identity_env="1BAD"),
            "adhoc string": lambda p: p["config"].update(adhoc_fallback="yes"),
            "extra parameter": lambda p: p.update(title="t"),
            "parameter operation": lambda p: p.update(operation="publish"),
        }
        self.install()
        started = len(self.world.calls())
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                parameters = with_(mutate)
                observed = self.effect(parameters)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
                self.assertEqual(observed["references"], [])
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.visible(parameters)
                self.assertEqual((predicate["outcome"], predicate["reason"]),
                                 ("unknown", "store_unreachable"))
                self.assertEqual(len(self.world.calls()), started)
        with self.subTest(mutation="request operation"):
            request = {"kind": "effect", "operation": "publish", "parameters": self.parameters()}
            self.assertEqual(adapter.inspect(request)["reason"], "parameters_invalid")
            request = {"kind": "predicate", "predicate": "publication_visible",
                       "operation": "publish", "parameters": self.parameters()}
            self.assertEqual(adapter.inspect(request)["reason"], "store_unreachable")
        for name, request in (("not a dict", []), ("no kind", {"operation": "install"})):
            with self.subTest(request=name):
                observed = adapter.inspect(request)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
        self.assertEqual(len(self.world.calls()), started)

    def test_an_undeclared_predicate_is_unsupported(self):
        for predicate in ("running_subject_identity", "agent_running"):
            with self.subTest(predicate=predicate):
                observed = adapter.inspect({"kind": "predicate", "predicate": predicate,
                                            "operation": "install", "parameters": self.parameters()})
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "predicate_unsupported"))

    def test_the_module_imports_only_stdlib_and_canonical(self):
        tree = ast.parse(introspect.getsource(adapter))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_tools"):
                self.assertEqual(node.module, "agent_tools.canonical")
            if isinstance(node, ast.Import):
                self.assertFalse([a.name for a in node.names if a.name.startswith("agent_tools")])
