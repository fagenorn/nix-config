"""The launchd-agent adapter (issue 547). Run: just agent-workflow-tests"""
import ast
import inspect as introspect
import json
import os
import plistlib
import stat
import unittest
from unittest import mock

from agent_tools import launchd_agent_adapter as adapter, release_adapter
from .host_world import HostWorld

LABEL = "dev.example.notifier"
CONFIG = {"program": "notifierd", "arguments": ["serve", "--quiet"], "keep_alive": True,
          "background": True, "stdout_path": "logs/out.log", "stderr_path": "logs/err.log"}
DESCRIPTOR = {"name": "launchd-agent", "adapter_contract_version": "1.0.0",
              "operations": {"activate": {
                  "mode": "local_apply", "support": "supported", "inspect": "supported",
                  "reason": None, "mutability": "in_place", "config_schema_version": 1,
                  "config_schema": {"members": {"arguments": "string_list", "background": "boolean",
                                                "keep_alive": "boolean", "program": "string",
                                                "stderr_path": "string", "stdout_path": "string"},
                                    "required": ["keep_alive", "program"]},
                  "effects": ["reversible_no_incremental_spend", "irreversible"],
                  "recovery_capable": False, "candidate_members": []}},
              "predicates": {"agent_running": {"support": "supported", "reason": None},
                             "publication_visible": {"support": "unsupported",
                                                     "reason": "no_publication_mode"},
                             "running_subject_identity": {"support": "supported", "reason": None}},
              "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
              "target_kinds": {"launchd_gui_agent": ["label"]},
              "credential_classes": ["gui_session"], "executables": ["git", "launchctl"],
              "host_capacity": "not_required"}
FACT_KEYS = {"checkout", "domain", "label", "loaded", "path", "pid", "plist", "runs", "stamp",
             "state", "working_directory"}


class Case(unittest.TestCase):
    def setUp(self):
        self.world = HostWorld(self)
        self.world.program("notifierd")
        self.candidate = {"version": "v1.2.3", "commit": self.world.head()}

    def parameters(self, candidate=True, **config):
        parameters = {"action": "agent", "operation": "activate",
                      "target": {"handle": "agent", "kind": "launchd_gui_agent", "label": LABEL},
                      "config": {**CONFIG, **config}}
        if candidate:
            parameters["candidate"] = dict(self.candidate)
        return parameters

    def effect(self, parameters=None):
        return adapter.inspect({"kind": "effect", "operation": "activate",
                                "parameters": parameters or self.parameters()})

    def predicate(self, name, parameters=None):
        return adapter.inspect({"kind": "predicate", "predicate": name, "operation": "activate",
                                "parameters": parameters or self.parameters(
                                    candidate=name != "agent_running")})

    def managed(self, stamp="candidate", **changes):
        stamp = (self.candidate["version"], self.candidate["commit"]) if stamp == "candidate" else stamp
        environment = {} if stamp is None else {adapter.STAMP_VERSION: stamp[0],
                                                adapter.STAMP_COMMIT: stamp[1]}
        self.world.load_job(LABEL, path=str(self.world.plist_path(LABEL)), environment=environment,
                            working_directory=str(self.world.checkout), **changes)

    def snapshot(self):
        return (self.world.tree(), (self.world.state / "launchd.json").read_bytes(),
                (self.world.checkout / ".git/index").read_bytes())


class DescribeTest(Case):
    def test_descriptor_is_exact_valid_fresh_and_registered(self):
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])
        adapter.describe()["operations"].clear()
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertIs(release_adapter.REGISTRY["launchd-agent"], adapter)
        for node in ast.walk(ast.parse(introspect.getsource(adapter))):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("agent_tools"):
                self.assertEqual(node.module, "agent_tools.canonical")
            if isinstance(node, ast.Import):
                self.assertFalse([a.name for a in node.names if a.name.startswith("agent_tools")])


class InvokeTest(Case):
    def invoke(self, parameters=None):
        return adapter.invoke({"kind": "effect", "operation": "activate",
                               "parameters": parameters or self.parameters()})

    def rendered(self, **overrides):
        root = str(self.world.checkout)
        plist = {"Label": LABEL, "ProgramArguments": [str(self.world.bin / "notifierd"), "serve", "--quiet"],
                 "WorkingDirectory": root, "RunAtLoad": True, "KeepAlive": True,
                 "ProcessType": "Background",
                 "EnvironmentVariables": {"AGENT_RELEASE_VERSION": "v1.2.3",
                                          "AGENT_RELEASE_COMMIT": self.candidate["commit"]},
                 "StandardOutPath": os.path.join(root, "logs/out.log"),
                 "StandardErrorPath": os.path.join(root, "logs/err.log")}
        plist.update(overrides)
        return {key: value for key, value in plist.items() if value is not None}

    def written(self):
        with open(self.world.plist_path(LABEL), "rb") as handle:
            return plistlib.load(handle)

    def test_bootstraps_a_rendered_plist_then_inspects_satisfied(self):
        service, path = f"gui/{os.getuid()}/{LABEL}", self.world.plist_path(LABEL)
        self.assertEqual(self.invoke(), {"result": "accepted", "error_class": None, "reference": service})
        self.assertEqual(self.written(), self.rendered())
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o644)
        self.assertEqual([c["argv"] for c in self.world.calls("launchctl")],
                         [["print", service], ["bootstrap", f"gui/{os.getuid()}", str(path)]])
        self.assertEqual(self.world.calls("claude-bash-lifecycle-guard"), [])
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))

    def test_a_loaded_older_release_is_booted_out_and_back_in(self):
        self.managed(stamp=("v1.2.2", "f" * 40))
        self.assertEqual(self.invoke()["result"], "accepted")
        self.assertEqual([c["argv"][0] for c in self.world.calls("launchctl")],
                         ["print", "bootout", "bootstrap"])
        job = self.world.job(LABEL)
        self.assertEqual(job["runs"], 1)
        self.assertNotEqual(job["pid"], 4000)
        self.assertEqual(job["environment"], {"AGENT_RELEASE_VERSION": "v1.2.3",
                                              "AGENT_RELEASE_COMMIT": self.candidate["commit"]})

    def test_optional_members_are_omitted(self):
        program = str(self.world.bin / "notifierd")
        none = dict(ProgramArguments=[program], KeepAlive=False, ProcessType=None,
                    StandardOutPath=None, StandardErrorPath=None)
        parameters = self.parameters()
        parameters["config"] = {"program": "notifierd", "keep_alive": False}
        self.assertEqual(self.invoke(parameters)["result"], "accepted")
        self.assertEqual(self.written(), self.rendered(**none))
        self.setUp()
        parameters = self.parameters(background=False)
        self.assertEqual(self.invoke(parameters)["result"], "accepted")
        self.assertEqual(self.written(), self.rendered(ProcessType=None))

    def test_each_refusal(self):
        stale = ("v1.2.2", "f" * 40)
        plist = lambda: self.world.plist_path(LABEL)
        verbs = lambda: [c["argv"][0] for c in self.world.calls("launchctl")]

        def symlink():
            plist().parent.mkdir(parents=True)
            plist().symlink_to(self.world.checkout)

        def replace_fails():
            return mock.patch.object(adapter.os, "replace", side_effect=OSError("disk full"))

        def loaded_with(*knobs):
            def arrange():
                self.managed(stamp=stale)
                for verb, kwargs in knobs:
                    self.world.fail("launchctl", verb, **kwargs)
            return arrange

        def set_label(parameters):
            parameters["target"]["label"] = "-x"

        def set_commit(parameters):
            parameters["candidate"]["commit"] = "f" * 40

        def set_program(parameters):
            parameters["config"]["program"] = "missingd"

        def knob(verb, **kwargs):
            return lambda: self.world.fail("launchctl", verb, **kwargs)

        def foreign():
            self.world.load_job(LABEL, path="/Library/LaunchAgents/x.plist")
        # name, operation, edit, arrange, patch, (result, class, step), launchctl verbs, plist written
        rows = (
            ("label -x", "activate", set_label, None, None,
             ("rejected", "invalid_input", "shape"), [], False),
            ("operation install", "install", None, None, None,
             ("rejected", "unsupported_operation", "shape"), [], False),
            ("uid 0", "activate", None, None, lambda: mock.patch.object(adapter.os, "getuid", return_value=0),
             ("rejected", "authorization_denied", "authority"), [], False),
            ("commit moved", "activate", set_commit, None, None,
             ("rejected", "precondition_failed", "checkout"), [], False),
            ("dirty", "activate", None, lambda: self.world.dirty(), None,
             ("rejected", "precondition_failed", "checkout"), [], False),
            ("program missing", "activate", set_program, None, None,
             ("rejected", "precondition_failed", "program"), [], False),
            ("plist symlink", "activate", None, symlink, None,
             ("rejected", "precondition_failed", "plist path"), [], False),
            ("foreign job", "activate", None, foreign, None,
             ("rejected", "precondition_failed", "print"), ["print"], False),
            ("print exit 5", "activate", None, knob("print", exit=5), None,
             ("rejected", "provider_unavailable", "print"), ["print"], False),
            ("bootout exit 1", "activate", None, loaded_with(("bootout", {"exit": 1})), None,
             ("rejected", "transient_transport", "bootout"), ["print", "bootout", "print"], False),
            ("bootout exit 1, job gone", "activate", None,
             loaded_with(("bootout", {"exit": 1, "apply": True})), None,
             ("unknown", "transient_transport", "bootout"), ["print", "bootout", "print"], False),
            ("bootout timeout", "activate", None, loaded_with(("bootout", {"exit": 0, "sleep": 3})),
             lambda: mock.patch.object(adapter, "INVOKE_BUDGET_SECONDS", 1),
             ("unknown", "transient_transport", "bootout"), ["print", "bootout"], False),
            ("bootstrap exit 5", "activate", None, knob("bootstrap", exit=5), None,
             ("unknown", "transient_transport", "bootstrap"), ["print", "bootstrap"], True),
            ("write fails, nothing loaded", "activate", None, None, replace_fails,
             ("rejected", "provider_unavailable", "plist write"), ["print"], False),
            ("write fails after bootout", "activate", None, loaded_with(), replace_fails,
             ("unknown", "transient_transport", "plist write"), ["print", "bootout"], False))
        for name, operation, edit, arrange, patch, (result, error_class, step), expected, wrote in rows:
            with self.subTest(row=name):
                self.setUp()
                if arrange:
                    arrange()
                parameters = self.parameters()
                if edit:
                    edit(parameters)
                before = self.world.tree()
                with patch() if patch else mock.MagicMock():
                    answer = adapter.invoke({"kind": "effect", "operation": operation,
                                             "parameters": parameters})
                self.assertEqual((answer["result"], answer["error_class"]), (result, error_class))
                self.assertTrue(answer["reference"].startswith(f"{step}: "), answer["reference"])
                self.assertLessEqual(len(answer["reference"]), 240)
                self.assertEqual(release_adapter.invoke_result_problems(answer), [])
                self.assertEqual(verbs(), expected)
                self.assertEqual(plist().is_file() and not plist().is_symlink(), wrote)
                if step in ("shape", "authority"):
                    self.assertEqual(self.world.calls(), [])
                if step == "plist write":
                    self.assertEqual(os.listdir(plist().parent), [])
                elif not wrote:
                    self.assertEqual(self.world.tree(), before)
                if name == "foreign job":
                    self.assertEqual(self.world.job(LABEL)["path"], "/Library/LaunchAgents/x.plist")
                if name == "plist symlink":
                    self.assertTrue(plist().is_symlink())
                if name == "bootout exit 1":
                    self.assertIsNotNone(self.world.job(LABEL))
                if name == "bootout exit 1, job gone":
                    self.assertIsNone(self.world.job(LABEL))
                if name == "write fails after bootout":
                    self.assertIsNone(self.world.job(LABEL))

    def test_a_failed_bootout_is_rejected_only_while_the_job_stays_loaded(self):
        """Issue 547 D24: after a non-zero bootout, a re-read decides `rejected` or `unknown`."""
        stale = ("v1.2.2", "f" * 40)
        rows = (("still loaded", {}, ("rejected", "transient_transport"), True),
                ("unloaded", {"apply": True}, ("unknown", "transient_transport"), False))
        for name, knob, expected, loaded in rows:
            with self.subTest(row=name):
                self.setUp()
                self.managed(stamp=stale)
                self.world.fail("launchctl", "bootout", exit=5, stderr="Boot-out failed: 5", **knob)
                answer = self.invoke()
                self.assertEqual((answer["result"], answer["error_class"]), expected)
                self.assertEqual(answer["reference"], "bootout: Boot-out failed: 5")
                self.assertEqual([c["argv"][0] for c in self.world.calls("launchctl")],
                                 ["print", "bootout", "print"])
                self.assertEqual(self.world.job(LABEL) is not None, loaded)
                self.assertFalse(self.world.plist_path(LABEL).exists())

    def test_a_failed_bootout_whose_re_read_fails_is_unknown(self):
        self.managed(stamp=("v1.2.2", "f" * 40))
        self.world.fail("launchctl", "bootout", exit=5, stderr="Boot-out failed: 5")
        real_run = adapter._run

        def run(argv, deadline):
            if argv[1] == "print" and any(c["argv"][0] == "bootout"
                                          for c in self.world.calls("launchctl")):
                raise adapter._Unreadable("lookup_timeout")
            return real_run(argv, deadline)

        with mock.patch.object(adapter, "_run", run):
            answer = self.invoke()
        self.assertEqual((answer["result"], answer["error_class"]), ("unknown", "transient_transport"))
        self.assertIsNotNone(self.world.job(LABEL))

    def test_missing_log_parents_are_made_inside_the_checkout_and_the_job_runs(self):
        """Issue 547 D25: launchd makes no log directory, so `invoke` does before the bootout."""
        self.managed(stamp=("v1.2.2", "f" * 40))
        parameters = self.parameters(stdout_path="home/daemon/logs/out.log",
                                     stderr_path="home/daemon/err/err.log")
        self.assertEqual(self.invoke(parameters)["result"], "accepted")
        self.assertTrue((self.world.checkout / "home/daemon/logs").is_dir())
        self.assertTrue((self.world.checkout / "home/daemon/err").is_dir())
        job = self.world.job(LABEL)
        self.assertEqual(job["state"], "running")
        self.assertIsNotNone(job["pid"])
        observed = self.effect(parameters)
        self.assertEqual((observed["outcome"], observed["reason"]), ("satisfied", "running"))

    def test_a_log_parent_that_is_not_a_directory_is_refused_before_the_bootout(self):
        outside = self.world.root / "outside"

        def linked():
            outside.mkdir()
            (self.world.checkout / "home").mkdir()
            (self.world.checkout / "home/daemon").symlink_to(outside)

        def regular_file():
            (self.world.checkout / "home").mkdir()
            (self.world.checkout / "home/daemon").write_text("x")
        for name, arrange in (("symlink", linked), ("regular file", regular_file)):
            with self.subTest(component=name):
                self.setUp()
                self.managed(stamp=("v1.2.2", "f" * 40))
                pid = self.world.job(LABEL)["pid"]
                arrange()
                seed = len(self.world.calls("launchctl"))
                answer = self.invoke(self.parameters(stdout_path="home/daemon/logs/out.log"))
                self.assertEqual((answer["result"], answer["error_class"]),
                                 ("rejected", "precondition_failed"))
                self.assertTrue(answer["reference"].startswith("log directory: "), answer["reference"])
                self.assertEqual({c["argv"][0] for c in self.world.calls("launchctl")[seed:]}, {"print"})
                self.assertEqual(self.world.job(LABEL)["pid"], pid)
                self.assertFalse(self.world.plist_path(LABEL).exists())
                if name == "symlink":
                    self.assertEqual(list(outside.iterdir()), [])


class ClassificationTest(Case):
    def test_each_row_of_the_inspect_table(self):
        plist = lambda: self.world.plist_path(LABEL)
        rows = (
            ("plist symlink", lambda: plist().parent.mkdir(parents=True) or
             plist().symlink_to(self.world.checkout), ("diverged", "plist_unexpected"),
             ("unsatisfied", "subject_mismatch")),
            ("plist directory", lambda: plist().mkdir(parents=True), ("diverged", "plist_unexpected"),
             ("unsatisfied", "subject_mismatch")),
            ("not loaded", lambda: None, ("absent", "agent_not_loaded"), ("unsatisfied", "subject_absent")),
            ("foreign path", lambda: self.world.load_job(LABEL, path="/Library/LaunchAgents/x.plist"),
             ("diverged", "agent_path_foreign"), ("unsatisfied", "subject_mismatch")),
            ("unmanaged", lambda: self.managed(stamp=None), ("absent", "agent_unmanaged"),
             ("unsatisfied", "unrelated_subject_running")),
            ("stamp only in default environment", lambda: self.managed(
                stamp=None, default_environment={adapter.STAMP_VERSION: "v1.2.3",
                                                 adapter.STAMP_COMMIT: self.candidate["commit"]}),
             ("absent", "agent_unmanaged"), ("unsatisfied", "unrelated_subject_running")),
            ("other release", lambda: self.managed(stamp=("v1.2.2", "f" * 40)),
             ("absent", "agent_other_release"), ("unsatisfied", "subject_mismatch")),
            ("head moved", lambda: self.managed() or self.world.commit(),
             ("diverged", "checkout_moved"), ("unsatisfied", "subject_mismatch")),
            ("tracked change", lambda: self.managed() or self.world.dirty(),
             ("diverged", "checkout_moved"), ("unsatisfied", "subject_mismatch")),
            ("not running", lambda: self.managed(state="not running"),
             ("in_progress", "agent_not_running"), ("unsatisfied", "subject_absent")),
            ("running", lambda: self.managed(), ("satisfied", "running"), ("satisfied", "running")),
            ("print exit 5", lambda: self.world.fail("launchctl", "print", exit=5),
             ("unknown", "lookup_failed"), ("unknown", "identity_unobservable")),
            ("no runs line", lambda: self.world.fail("launchctl", "print", exit=0,
                                                     stdout=f"gui/1/{LABEL} = {{\n\tpath = x\n}}\n"),
             ("unknown", "payload_invalid"), ("unknown", "identity_unobservable")),
            ("launchctl missing", lambda: (self.world.bin / "launchctl").unlink(),
             ("unknown", "executable_missing"), ("unknown", "identity_unobservable")))
        for name, arrange, effect, identity in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                observed = self.effect()
                self.assertEqual((observed["outcome"], observed["reason"]), effect)
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                self.assertEqual(set(observed["facts"]) - {"detail"}, FACT_KEYS)
                predicate = self.predicate("running_subject_identity")
                self.assertEqual((predicate["outcome"], predicate["reason"]), identity)
                self.assertEqual(release_adapter.predicate_observation_problems(predicate), [])

    def test_a_checkout_that_is_not_there_is_an_unreadable_checkout(self):
        self.world.load_job(LABEL, path=str(self.world.plist_path(LABEL)), environment={
            adapter.STAMP_VERSION: "v1.2.3", adapter.STAMP_COMMIT: self.candidate["commit"]},
            working_directory=str(self.world.root / "gone"))
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("unknown", "lookup_failed"))
        self.assertTrue(observed["facts"]["detail"])

    def test_a_stamped_job_with_no_working_directory_has_no_checkout(self):
        self.world.load_job(LABEL, path=str(self.world.plist_path(LABEL)), environment={
            adapter.STAMP_VERSION: "v1.2.3", adapter.STAMP_COMMIT: self.candidate["commit"]})
        observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("diverged", "checkout_moved"))
        self.assertIsNone(observed["facts"]["checkout"])
        self.assertEqual(self.world.calls("git"), [])


class LivenessTest(Case):
    def test_each_row_of_the_liveness_table(self):
        rows = (
            ("not loaded", lambda: None, ("unsatisfied", "agent_not_loaded")),
            ("foreign path", lambda: self.world.load_job(LABEL, path="/Library/LaunchAgents/x.plist"),
             ("unsatisfied", "agent_path_foreign")),
            ("not running", lambda: self.managed(state="not running"),
             ("unsatisfied", "agent_not_running")),
            ("restarted", lambda: self.managed(runs=2), ("unsatisfied", "agent_restarted")),
            ("running", lambda: self.managed(stamp=None), ("satisfied", "running")),
            ("print exit 5", lambda: self.world.fail("launchctl", "print", exit=5),
             ("unknown", "lookup_failed")))
        for name, arrange, expected in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                observed = self.predicate("agent_running")
                self.assertEqual((observed["outcome"], observed["reason"]), expected)
                self.assertEqual(release_adapter.predicate_observation_problems(observed), [])
                self.assertEqual({c["tool"] for c in self.world.calls()}, {"launchctl"})


class ObservationTest(Case):
    def test_a_satisfied_observation_names_service_plist_and_pid(self):
        self.managed()
        head = self.world.head()
        observed = self.effect()
        self.assertEqual(observed["observed_subject"], {"version": "v1.2.3", "commit": head, "pid": 4000})
        self.assertEqual(observed["references"], [f"gui/{os.getuid()}/{LABEL}",
                                                  str(self.world.plist_path(LABEL))])
        facts = observed["facts"]
        self.assertEqual(set(facts), FACT_KEYS)
        self.assertEqual(facts["checkout"], {"head": head, "clean": True})
        self.assertIs(facts["loaded"], True)
        self.assertEqual((facts["runs"], facts["pid"], facts["state"]), (1, 4000, "running"))
        self.assertEqual(facts["stamp"], self.candidate)

    def test_inspect_never_mutates(self):
        for name, arrange in (("running", lambda: self.managed()),
                              ("head moved", lambda: self.managed() or self.world.commit())):
            with self.subTest(arrangement=name):
                self.setUp()
                arrange()
                before = self.snapshot()
                self.effect()
                self.predicate("running_subject_identity")
                self.predicate("agent_running")
                self.assertEqual(self.snapshot(), before)
                self.assertEqual({c["argv"][0] for c in self.world.calls("launchctl")}, {"print"})
                git = self.world.calls("git")
                self.assertTrue(git)
                self.assertTrue(all(c["argv"][0] == "--no-optional-locks" for c in git))

    def test_a_print_past_the_budget_is_lookup_timeout(self):
        self.world.fail("launchctl", "print", exit=0, sleep=3)
        with mock.patch.object(adapter, "INSPECT_BUDGET_SECONDS", 1):
            observed = self.effect()
        self.assertEqual((observed["outcome"], observed["reason"]), ("unknown", "lookup_timeout"))


class ShapeTest(Case):
    def test_requests_outside_the_closed_shape_start_no_child(self):
        def config(**changes):
            return lambda p: p["config"].update(changes)

        def without(name):
            return lambda p: p["config"].pop(name)
        mutations = {
            "label -x": lambda p: p["target"].update(label="-x"),
            "label with space": lambda p: p["target"].update(label="a b"),
            "label too long": lambda p: p["target"].update(label="a" * 129),
            "label not a string": lambda p: p["target"].update(label=["a"]),
            "target extra member": lambda p: p["target"].update(domain="system"),
            "target kind": lambda p: p["target"].update(kind="installed_bundle"),
            "program with slash": config(program="/usr/bin/x"),
            "program empty": config(program=""),
            "program dotdot": config(program=".."),
            "arguments empty": config(arguments=[]),
            "arguments duplicate": config(arguments=["a", "a"]),
            "keep_alive string": config(keep_alive="true"),
            "background int": config(background=1),
            "stdout absolute": config(stdout_path="/tmp/x"),
            "stderr parent": config(stderr_path="../x"),
            "config extra": config(run_at_load=True),
            "config missing program": without("program"),
            "candidate version": lambda p: p["candidate"].update(version="1.2.3"),
            "operation install": lambda p: p.update(operation="install"),
        }
        for name, mutate in mutations.items():
            with self.subTest(mutation=name):
                parameters = self.parameters()
                mutate(parameters)
                observed = self.effect(parameters)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                self.assertEqual(set(observed["facts"]) - {"detail"}, FACT_KEYS)
                self.assertTrue(observed["facts"]["detail"])
                running = self.predicate("agent_running", parameters)
                self.assertEqual((running["outcome"], running["reason"]),
                                 ("unknown", "parameters_invalid"))
                identity = self.predicate("running_subject_identity", parameters)
                self.assertEqual((identity["outcome"], identity["reason"]),
                                 ("unknown", "identity_unobservable"))
                self.assertEqual(self.world.calls(), [])
        with self.subTest(mutation="request operation"):
            request = {"kind": "effect", "operation": "install", "parameters": self.parameters()}
            self.assertEqual(adapter.inspect(request)["reason"], "parameters_invalid")
            self.assertEqual(self.world.calls(), [])

    def test_a_missing_candidate_fails_an_effect_and_identity_but_not_liveness(self):
        parameters = self.parameters(candidate=False)
        self.assertEqual(self.effect(parameters)["reason"], "parameters_invalid")
        self.assertEqual(self.predicate("running_subject_identity", parameters)["reason"],
                         "identity_unobservable")
        self.assertEqual(self.world.calls(), [])
        self.assertEqual(self.predicate("agent_running", parameters)["reason"], "agent_not_loaded")

    def test_a_present_candidate_is_checked_for_liveness(self):
        parameters = self.parameters()
        parameters["candidate"]["commit"] = "A" * 40
        self.assertEqual(self.predicate("agent_running", parameters)["reason"], "parameters_invalid")
        self.assertEqual(self.world.calls(), [])

    def test_undeclared_predicates_are_unsupported(self):
        for name in ("publication_visible", "liveness"):
            with self.subTest(predicate=name):
                observed = self.predicate(name)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "predicate_unsupported"))
        self.assertEqual(self.world.calls(), [])

    def test_a_request_that_is_not_closed_is_parameters_invalid(self):
        for name, request in (("not a dict", []), ("no kind", {"operation": "activate"}),
                              ("extra member", {"kind": "effect", "operation": "activate",
                                                "parameters": self.parameters(), "x": 1})):
            with self.subTest(request=name):
                observed = adapter.inspect(request)
                self.assertEqual((observed["outcome"], observed["reason"]),
                                 ("unknown", "parameters_invalid"))
        self.assertEqual(self.world.calls(), [])


if __name__ == "__main__":
    unittest.main()
