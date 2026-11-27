"""The host readings cache and its registry (issue 1289).

Pins that a host is evaluated once per checkout content, that the answer is shared across
processes under the host lock, what the key covers, and that a failed or unusable cache never
becomes an evaluation per reader. Needs nix and git; the freshness cases evaluate a scratch flake.
Run: just agent-workflow-tests
"""
import fcntl
import importlib
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path
from unittest import mock

from agent_tools.verification import verified_tree

from . import accounts_sandbox
from . import host_readings

ROOT = host_readings.ROOT
GIT = ["git", "-c", "commit.gpgsign=false", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
VALUE = {"value": host_readings.Part("c: u: c.value", ("anis-desktop", "mbp", "eleven-m5"))}
ALL = ("anis-desktop", "mbp", "eleven-m5")


def repository_selection():
    """The variables with which a caller points git at a repository (git's own list of them)."""
    done = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True, check=True)
    return done.stdout.split()


def without_repository_selection():
    selected = set(repository_selection())
    return {name: value for name, value in os.environ.items() if name not in selected}


def scratch_repo(tmp, files, name="repo"):
    """A committed scratch repository that no inherited GIT_DIR or GIT_WORK_TREE can redirect."""
    repo = Path(tmp) / name
    repo.mkdir()
    env = without_repository_selection()
    subprocess.run([*GIT, "init", "-q"], cwd=repo, check=True, env=env)
    for name, text in files.items():
        (repo / name).parent.mkdir(parents=True, exist_ok=True)
        (repo / name).write_text(text, encoding="utf-8")
    subprocess.run([*GIT, "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run([*GIT, "commit", "-q", "-m", "init"], cwd=repo, check=True, env=env)
    return repo


def fake_nix(bin_dir, log, gate=None, version="nix (Nix) 0-fake"):
    """A `nix` that answers the version, the username and `config show`, and logs each evaluation."""
    Path(bin_dir).mkdir(parents=True, exist_ok=True)
    gate_lines = ""
    if gate is not None:
        gate_lines = (
            f': > "{gate}/evaluating"\n'
            "n=0\n"
            f'while [ ! -e "{gate}/release" ] && [ "$n" -lt 300 ]; do sleep 0.1; n=$((n+1)); done\n'
        )
    script = (
        "#!/bin/sh\n"
        f'if [ "$1" = "--version" ]; then echo "{version}"; exit 0; fi\n'
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    --file) printf tester; exit 0;;\n"
        '    config) echo \'{"system":{"value":"x86_64-linux"},"extra-platforms":{"value":[]},'
        '"builders":{"value":""}}\'; exit 0;;\n'
        '    *.config) ref="$a";;\n'
        "  esac\n"
        "done\n"
        f'echo "$*" >> "{log}"\n'
        f"{gate_lines}"
        'printf \'{"value": "%s"}\\n\' "$ref"\n'
    )
    path = Path(bin_dir) / "nix"
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path


def child(code, env_extra):
    env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **env_extra}
    return subprocess.Popen([sys.executable, "-c", code], cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


SNIPPET = (
    "import json, pathlib\n"
    "from tests import host_readings as h\n"
    "V = {'value': h.Part('c: u: c.value', ('anis-desktop', 'mbp', 'eleven-m5'))}\n"
)


class Scratch(unittest.TestCase):
    def setUp(self):
        # Every git a scratch test runs, and every child it starts, sees no inherited repository.
        patch = mock.patch.dict(os.environ)
        patch.start()
        self.addCleanup(patch.stop)
        for name in repository_selection():
            os.environ.pop(name, None)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.cache = Path(self.tmp) / "cache"
        self.bin = Path(self.tmp) / "bin"
        self.log = Path(self.tmp) / "evaluations.log"


class ScratchIsolationTest(unittest.TestCase):
    def test_a_callers_repository_selection_does_not_reach_a_scratch_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            caller = scratch_repo(tmp, {"a.txt": "1\n"}, name="caller")
            (caller / "a.txt").write_text("2\n", encoding="utf-8")

            def state():
                head = subprocess.run(["git", "-C", str(caller), "rev-parse", "HEAD"],
                                      capture_output=True, text=True, check=True).stdout
                status = subprocess.run(["git", "-C", str(caller), "status", "--porcelain"],
                                        capture_output=True, text=True, check=True).stdout
                return head, status

            before = state()
            selection = {"GIT_DIR": str(caller / ".git"), "GIT_WORK_TREE": str(caller)}
            with mock.patch.dict(os.environ, selection):
                scratch = scratch_repo(tmp, {"s.txt": "s\n"}, name="scratch")
                case = Scratch()
                case.setUp()
                try:
                    for name in selection:
                        self.assertNotIn(name, os.environ)
                finally:
                    case.doCleanups()
            self.assertEqual(state(), before)
            listed = subprocess.run(["git", "-C", str(scratch), "ls-files"],
                                    capture_output=True, text=True, check=True).stdout
            self.assertEqual(listed.split(), ["s.txt"])


class FreshnessTest(Scratch):
    def setUp(self):
        super().setUp()
        self.repo = scratch_repo(self.tmp, {
            "flake.nix": '{ outputs = _: { darwinConfigurations.mbp.config = { home-manager.users.tester = { };'
                         ' value = import ./value.nix; services.github-runners = { }; }; }; }\n',
            "flake.lock": '{"nodes":{"root":{}},"root":"root","version":7}\n',
            "vars/default.nix": '{ username = "tester"; }\n',
            "value.nix": '"one"\n',
            "justfile": "register-runners target_host=hostname:\n"
                        "  #!/usr/bin/env bash\n"
                        "  triples=$(nix eval --raw \".#x\" --apply 'rs: \"one\"')\n",
        })
        patcher = mock.patch.object(host_readings, "_evaluate", wraps=host_readings._evaluate)
        self.evaluate = patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, parts):
        return host_readings.reading("mbp", root=self.repo, cache=self.cache, parts=parts)

    def test_a_changed_tracked_file_gives_a_fresh_answer(self):
        self.assertEqual(self.read(VALUE), {"value": "one"})
        self.assertEqual(self.read(VALUE), {"value": "one"})
        self.assertEqual(self.evaluate.call_count, 1)
        (self.repo / "value.nix").write_text('"two"\n', encoding="utf-8")
        self.assertEqual(self.read(VALUE), {"value": "two"})
        self.assertEqual(self.evaluate.call_count, 2)

    def test_an_untracked_file_reuses_the_answer(self):
        self.assertEqual(self.read(VALUE), {"value": "one"})
        (self.repo / "notes.txt").write_text("x\n", encoding="utf-8")
        self.assertEqual(self.read(VALUE), {"value": "one"})
        self.assertEqual(self.evaluate.call_count, 1)

    def test_an_edited_recipe_gives_its_own_triples(self):
        parts = {"runner-triples": host_readings.PARTS["runner-triples"]}
        self.assertEqual(self.read(parts), {"runner-triples": "one"})
        justfile = self.repo / "justfile"
        justfile.write_text(justfile.read_text(encoding="utf-8").replace('"one"', '"two"'), encoding="utf-8")
        self.assertEqual(self.read(parts), {"runner-triples": "two"})
        self.assertEqual(self.evaluate.call_count, 2)


class FingerprintTest(Scratch):
    def test_the_checkout_is_the_tree_a_git_build_sees(self):
        repo = scratch_repo(self.tmp, {"a.txt": "1\n", "b.txt": "1\n"})
        (repo / "a.txt").write_text("2\n", encoding="utf-8")
        (repo / "new.txt").write_text("n\n", encoding="utf-8")
        subprocess.run([*GIT, "add", "new.txt"], cwd=repo, check=True)
        (repo / "untracked.txt").write_text("u\n", encoding="utf-8")
        got = host_readings.fingerprint(repo)
        self.assertEqual(got, verified_tree.current_tree(repo))
        (repo / "untracked.txt").unlink()
        self.assertEqual(host_readings.fingerprint(repo), got)


class ConcurrencyTest(Scratch):
    def setUp(self):
        super().setUp()
        self.repo = scratch_repo(self.tmp, {"a.txt": "1\n"})
        self.gate = Path(self.tmp) / "gate"
        (self.gate / "started").mkdir(parents=True)
        fake_nix(self.bin, self.log, gate=self.gate)
        self.env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "HOST_READINGS_CACHE": str(self.cache)}

    def wait_for(self, path):
        deadline = time.monotonic() + 30
        while not Path(path).exists():
            self.assertLess(time.monotonic(), deadline, f"{path} never appeared")
            time.sleep(0.05)

    def test_concurrent_readers_of_one_host_make_one_evaluation(self):
        code = SNIPPET + f"print(json.dumps(h.reading('mbp', root=pathlib.Path({str(self.repo)!r}), parts=V)))"
        first = child(code, self.env)
        self.wait_for(self.gate / "evaluating")
        fd = os.open(self.cache / "mbp.lock", os.O_RDWR | os.O_CREAT, 0o644)
        try:
            with self.assertRaises(BlockingIOError):
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(fd)
        others = [
            child(f"import pathlib; pathlib.Path({str(self.gate / 'started' / str(i))!r}).touch()\n" + code, self.env)
            for i in (1, 2, 3)
        ]
        for i in (1, 2, 3):
            self.wait_for(self.gate / "started" / str(i))
        (self.gate / "release").touch()
        for proc in (first, *others):
            out, err = proc.communicate(timeout=120)
            self.assertEqual(proc.returncode, 0, err)
            self.assertEqual(json.loads(out), {"value": f"{self.repo}#darwinConfigurations.mbp.config"})
        self.assertEqual(len(self.log.read_text().splitlines()), 1, self.log.read_text())

    def test_each_host_gets_its_own_answer_once(self):
        (self.gate / "release").touch()
        code = SNIPPET + (
            "hosts = ['anis-desktop', 'mbp', 'eleven-m5']\n"
            "start = int(__import__('sys').argv[1])\n"
            "out = {}\n"
            "for host in hosts[start:] + hosts[:start]:\n"
            f"    out[host] = h.reading(host, root=pathlib.Path({str(self.repo)!r}), parts=V)\n"
            "print(json.dumps(out))\n"
        )
        procs = []
        for i in range(3):
            env = {**os.environ, "PYTHONPATH": str(ROOT / "python"), **self.env}
            procs.append(subprocess.Popen([sys.executable, "-c", code, str(i)], cwd=ROOT, env=env,
                                          stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
        for proc in procs:
            out, err = proc.communicate(timeout=120)
            self.assertEqual(proc.returncode, 0, err)
            for host, answer in json.loads(out).items():
                self.assertEqual(answer, {"value": f"{self.repo}#{host_readings.output(host)}.config"})
        lines = self.log.read_text().splitlines()
        self.assertEqual(len(lines), 3)
        for host in ALL:
            self.assertEqual(sum(f"#{host_readings.output(host)}.config" in line for line in lines), 1)


class Counted(Scratch):
    """In-process reads with `_evaluate` replaced by a counting fake and a deterministic nix."""

    def setUp(self):
        super().setUp()
        self.repo = scratch_repo(self.tmp, {"value.nix": '"one"\n'})
        fake_nix(self.bin, self.log, version="nix (Nix) 0")
        patch = mock.patch.dict(os.environ, {"PATH": f"{self.bin}:{os.environ['PATH']}"})
        patch.start()
        self.addCleanup(patch.stop)
        evaluate = mock.patch.object(host_readings, "_evaluate", side_effect=self.answer)
        self.evaluate = evaluate.start()
        self.addCleanup(evaluate.stop)

    def answer(self, host, selected, pure, root):
        return {"value": 1}

    def read(self, parts=VALUE, host="mbp"):
        return host_readings.reading(host, root=self.repo, cache=self.cache, parts=parts)

    def entries(self, host="mbp"):
        return sorted(self.cache.glob(f"{host}-*.json"))


class KeyTest(Counted):
    def test_changed_parts_give_a_fresh_evaluation(self):
        self.read(VALUE)
        self.read({"value": host_readings.Part("c: u: c.other", ALL)})
        self.assertEqual(self.evaluate.call_count, 2)

    def test_another_nix_gives_a_fresh_evaluation(self):
        for version in ("nix (Nix) 1", "nix (Nix) 2"):
            other = Path(self.tmp) / f"bin-{version[-1]}"
            fake_nix(other, self.log, version=version)
            with mock.patch.dict(os.environ, {"PATH": f"{other}:{os.environ['PATH']}"}):
                self.read()
        self.assertEqual(self.evaluate.call_count, 2)

    def test_an_edit_during_the_evaluation_publishes_nothing(self):
        value = self.repo / "value.nix"

        def edit(host, selected, pure, root):
            value.write_text('"two"\n', encoding="utf-8")
            return {"value": "two"}

        self.evaluate.side_effect = edit
        with self.assertRaises(AssertionError) as raised:
            self.read()
        self.assertIn("changed during", str(raised.exception))
        self.assertEqual(self.entries(), [])
        value.write_text('"one"\n', encoding="utf-8")
        self.evaluate.side_effect = lambda host, selected, pure, root: {"value": value.read_text().strip()}
        self.assertEqual(self.read(), {"value": '"one"'})
        self.assertEqual(self.evaluate.call_count, 2)


class SelectTest(unittest.TestCase):
    def test_a_darwin_host_is_pure_where_no_darwin_part_joins(self):
        selected, pure = host_readings.select("mbp", host_readings.PARTS, darwin_machine=False, linux_builder=True)
        self.assertFalse([n for n, p in selected.items() if p.needs == "darwin-machine"])
        self.assertTrue(pure)
        self.assertIn("console-darwin", selected)
        self.assertIn("runner-triples", selected)

    def test_on_a_darwin_machine_the_activation_parts_join_and_allow_ifd(self):
        for host in ("mbp", "eleven-m5"):
            selected, pure = host_readings.select(host, host_readings.PARTS, darwin_machine=True, linux_builder=False)
            self.assertIn("verify-pending-activation", selected)
            self.assertEqual("owner-activation" in selected, host == "eleven-m5")
            self.assertFalse(pure)

    def test_the_platform_package_reading_joins_every_host_on_every_machine(self):
        # It reads the definitions of `home.file`, never the merged option (an import-from-derivation), so the
        # required CI job on Linux reads the darwin hosts too, and a darwin host stays in a pure evaluation.
        for host in host_readings.ALL_HOSTS:
            for darwin in (False, True):
                for builder in (False, True):
                    selected, pure = host_readings.select(
                        host, host_readings.PARTS, darwin_machine=darwin, linux_builder=builder)
                    self.assertIn("agent-platform", selected, (host, darwin, builder))
                    self.assertNotIn("agent-platform-linux", selected)
        selected, pure = host_readings.select(
            "mbp", host_readings.PARTS, darwin_machine=False, linux_builder=False)
        self.assertTrue(pure)

    def test_the_linux_host_is_never_pure_and_takes_the_console_only_with_a_builder(self):
        for darwin in (False, True):
            for builder in (False, True):
                selected, pure = host_readings.select(
                    "anis-desktop", host_readings.PARTS, darwin_machine=darwin, linux_builder=builder)
                self.assertFalse(pure)
                self.assertEqual("console" in selected, builder)

    def test_reading_a_part_this_machine_does_not_evaluate_names_why(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(host_readings, "can_build", return_value=False), \
                mock.patch.object(host_readings, "_evaluate", return_value={"system-packages": []}):
            with self.assertRaises(AssertionError) as raised:
                host_readings.read("anis-desktop", "console", cache=Path(tmp) / "cache")
        for word in ("console", "anis-desktop", "x86_64-linux-builder"):
            self.assertIn(word, str(raised.exception))


class CacheStoreTest(Counted):
    def test_a_failed_evaluation_is_not_stored(self):
        self.evaluate.side_effect = [AssertionError("boom"), {"value": 1}]
        with self.assertRaises(AssertionError):
            self.read()
        self.assertEqual(list(self.cache.glob("*.json")), [])
        self.assertEqual(self.read(), {"value": 1})
        self.assertEqual(self.evaluate.call_count, 2)

    def test_an_unwritable_cache_fails_before_evaluating(self):
        (Path(self.tmp) / "file").write_text("x", encoding="utf-8")
        cache = Path(self.tmp) / "file" / "cache"
        with self.assertRaises(AssertionError) as raised:
            host_readings.reading("mbp", root=self.repo, cache=cache, parts=VALUE)
        self.assertIn(str(cache), str(raised.exception))
        self.assertEqual(self.evaluate.call_count, 0)

    def test_a_failed_publish_does_not_evaluate_again(self):
        with mock.patch.object(host_readings.os, "replace", side_effect=OSError("denied")):
            with self.assertRaises(AssertionError) as raised:
                self.read()
        self.assertIn(str(self.cache), str(raised.exception))
        self.assertIn("denied", str(raised.exception))
        self.assertEqual(self.evaluate.call_count, 1)
        self.assertEqual(self.entries(), [])
        self.assertEqual(list(self.cache.glob(".mbp-*.tmp")), [])

    def test_two_processes_sharing_an_unwritable_cache_evaluate_nothing(self):
        (Path(self.tmp) / "file").write_text("x", encoding="utf-8")
        self.assert_processes_evaluate_nothing(Path(self.tmp) / "file" / "cache")

    def test_two_processes_sharing_a_read_only_cache_with_its_lock_evaluate_nothing(self):
        if os.geteuid() == 0:
            self.skipTest("root writes to a read-only directory")
        self.cache.mkdir()
        (self.cache / "mbp.lock").touch()
        self.cache.chmod(0o500)
        self.addCleanup(self.cache.chmod, 0o700)
        self.assert_processes_evaluate_nothing(self.cache)

    def assert_processes_evaluate_nothing(self, cache):
        gate = Path(self.tmp) / "gate"
        gate.mkdir()
        (gate / "release").touch()
        fake_nix(self.bin, self.log, gate=gate)
        env = {"PATH": f"{self.bin}:{os.environ['PATH']}", "HOST_READINGS_CACHE": str(cache)}
        code = SNIPPET + f"h.reading('mbp', root=pathlib.Path({str(self.repo)!r}), parts=V)"
        procs = [child(code, env) for _ in range(2)]
        for proc in procs:
            _, err = proc.communicate(timeout=120)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn(str(cache), err)
        self.assertTrue(not self.log.exists() or self.log.read_text() == "")

    def test_publishing_replaces_only_the_hosts_generated_entries(self):
        self.cache.mkdir()
        digest = "a" * 64
        stale = self.cache / f"mbp-{digest}.json"
        kept = [self.cache / name for name in (
            "mbp-report.json", f"mbp-{digest[:-1]}.json", f"mbp-{digest}.json.bak", f"eleven-m5-{digest}.json",
            f"mbp-{'g' * 64}.json")]
        for path in (stale, *kept):
            path.write_text("x", encoding="utf-8")
        self.read()
        self.assertFalse(stale.exists())
        for path in kept:
            self.assertTrue(path.exists(), path)
        self.assertEqual(len(self.entries()), 1 + 3)

    def test_an_edit_while_a_reader_waits_for_the_lock_gives_a_fresh_answer(self):
        value = self.repo / "value.nix"
        self.evaluate.side_effect = lambda host, selected, pure, root: {"value": value.read_text().strip()}
        self.assertEqual(self.read(), {"value": '"one"'})
        real = fcntl.flock

        def edited_while_waiting(descriptor, operation):
            value.write_text('"two"\n', encoding="utf-8")
            return real(descriptor, operation)

        with mock.patch.object(host_readings.fcntl, "flock", side_effect=edited_while_waiting):
            self.assertEqual(self.read(), {"value": '"two"'})
        self.assertEqual(self.evaluate.call_count, 2)

    def test_a_corrupt_entry_is_evaluated_again(self):
        self.read()
        (entry,) = self.entries()
        entry.write_text("{", encoding="utf-8")
        self.assertEqual(self.read(), {"value": 1})
        self.assertEqual(self.evaluate.call_count, 2)

    def test_a_new_entry_replaces_the_hosts_older_entry(self):
        self.read()
        (first,) = self.entries()
        before = json.loads(first.read_text())["key"]
        (self.repo / "value.nix").write_text('"two"\n', encoding="utf-8")
        self.read()
        (second,) = self.entries()
        self.assertNotEqual(json.loads(second.read_text())["key"], before)

    def test_each_reading_is_a_fresh_copy(self):
        self.read()["value"] = 99
        self.assertEqual(self.read(), {"value": 1})
        self.assertEqual(self.evaluate.call_count, 1)

    def test_the_cache_lives_in_the_git_directory_unless_overridden(self):
        git_dir = subprocess.run(["git", "-C", str(self.repo), "rev-parse", "--absolute-git-dir"],
                                 capture_output=True, text=True, check=True).stdout.strip()
        env = {k: v for k, v in os.environ.items() if k != host_readings.CACHE_ENV}
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(host_readings.cache_dir(self.repo), Path(git_dir) / "host-readings")
        with mock.patch.dict(os.environ, {host_readings.CACHE_ENV: f"{self.tmp}/x"}):
            self.assertEqual(host_readings.cache_dir(self.repo), Path(f"{self.tmp}/x"))
        with mock.patch.dict(os.environ, {host_readings.CACHE_ENV: ""}):
            self.assertEqual(host_readings.cache_dir(self.repo), Path(git_dir) / "host-readings")


class EvaluationEnvironmentTest(unittest.TestCase):
    """The environment each `nix` child starts with (#1286); nothing here evaluates."""

    CACHE_INPUTS = ("NIX_CACHE_HOME", "XDG_CACHE_HOME")
    P = {"p": host_readings.Part("c: u: 1", ("anis-desktop", "mbp"))}

    def record(self):
        calls = []
        real = subprocess.run

        def fake(argv, **kwargs):
            if argv[0] != "nix":
                return real(argv, **kwargs)
            # The child's environment as of the call: a fixture's tear-down must not change it.
            env = dict(os.environ) if kwargs.get("env") is None else dict(kwargs["env"])
            calls.append((argv, env))
            return subprocess.CompletedProcess(argv, 0, stdout="{}", stderr="")

        return calls, fake

    def act(self):
        calls, fake = self.record()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        with mock.patch.object(subprocess, "run", fake):
            host_readings.reading("anis-desktop", cache=Path(tmp) / "cache", parts=self.P)
            host_readings.reading("mbp", cache=Path(tmp) / "cache", parts=self.P)
        self.assertEqual(len(calls), 6)
        for start in (0, 3):
            self.assertIn("--version", calls[start][0])
            self.assertIn("--file", calls[start + 1][0])
            self.assertIn("--json", calls[start + 2][0])
        # Only the pure darwin evaluation forbids IFD.
        for index, (argv, _) in enumerate(calls):
            self.assertEqual("allow-import-from-derivation" in argv, index == 5, argv)
        return calls

    def test_a_sandboxed_evaluation_runs_with_the_environment_from_before_the_sandbox(self):
        self.assertIsNone(accounts_sandbox.root())
        variables = accounts_sandbox.VARIABLES
        with tempfile.TemporaryDirectory() as t:
            before = {"HOME": f"{t}/real-home", "CLAUDE_ACCOUNTS_DIR": f"{t}/real-accounts"}
            cases = {
                "both cache inputs absent": {},
                "XDG_CACHE_HOME only": {"XDG_CACHE_HOME": f"{t}/xdg"},
                "NIX_CACHE_HOME present and empty": {"NIX_CACHE_HOME": ""},
            }
            for name, inputs in cases.items():
                with self.subTest(name), mock.patch.dict(os.environ, clear=False):
                    os.environ.update(before)
                    os.environ.pop("CLAUDE_CONFIG_DIR", None)
                    for v in self.CACHE_INPUTS:
                        os.environ.pop(v, None)
                    os.environ.update(inputs)
                    parent = dict(os.environ)
                    accounts_sandbox.setUpModule()
                    try:
                        calls = self.act()
                    finally:
                        accounts_sandbox.tearDownModule()
                    for _, env in calls:
                        self.assertEqual(
                            {v: env.get(v) for v in variables},
                            {v: parent.get(v) for v in variables},
                        )
                        for v in self.CACHE_INPUTS:
                            self.assertEqual((v in env, env.get(v)), (v in parent, parent.get(v)), v)
                        self.assertEqual(
                            {k: x for k, x in env.items() if k not in variables},
                            {k: x for k, x in parent.items() if k not in variables},
                        )

    def test_an_unsandboxed_evaluation_inherits_the_callers_environment(self):
        self.assertIsNone(accounts_sandbox.root())
        with mock.patch.dict(os.environ, {"HOME": "/nonexistent-1286/later-home"}):
            calls = self.act()
            for _, env in calls:
                self.assertEqual(env["HOME"], "/nonexistent-1286/later-home")


def measure(suite):
    """Run `suite`; return its result and output, and the `(host, part)` reads made from a
    `setUpClass` or `setUpModule` frame (set-up reads) and those made anywhere else (a test body,
    its per-test set-up or a helper it calls)."""
    setup, elsewhere = [], []
    real = host_readings.read

    def recording(*args, **kwargs):
        frame, from_setup = sys._getframe(1), False
        while frame is not None and not from_setup:
            from_setup = frame.f_code.co_name in ("setUpClass", "setUpModule")
            frame = frame.f_back
        (setup if from_setup else elsewhere).append(tuple(args[:2]))
        return real(*args, **kwargs)

    stream = io.StringIO()
    with mock.patch.object(host_readings, "read", recording):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    return result, stream.getvalue(), set(setup), set(elsewhere)


def refusing_nix(directory, real_nix, refused):
    """A `nix` that refuses an `eval` naming a host output in any argument, and runs `real_nix` otherwise."""
    wrapper = Path(directory) / "nix"
    wrapper.write_text(
        "#!/bin/sh\n"
        'evaluating=no; host=no\n'
        'for a in "$@"; do\n'
        '  case "$a" in\n'
        "    eval) evaluating=yes;;\n"
        "    *nixosConfigurations*|*darwinConfigurations*) host=yes;;\n"
        "  esac\n"
        "done\n"
        'if [ "$evaluating" = yes ] && [ "$host" = yes ]; then\n'
        f'  echo "$*" >> "{refused}"; exit 1\n'
        "fi\n"
        f'exec "{real_nix}" "$@"\n', encoding="utf-8")
    wrapper.chmod(0o755)
    return wrapper


def linked(source, target):
    return {"source": source, "enable": True, "target": target, "recursive": False}


PKG = "/nix/store/" + "a" * 32 + "-agent-platform"


def stub_reading(definitions):
    """The `agent-platform` part applied to a stub host whose `home.file` definitions are `definitions` (Nix text)."""
    expression = f"""let
      package = {{ outPath = "{PKG}"; python = "/nix/store/{'b' * 32}-python3";
        launchers = {{ tool = "{PKG}/bin/tool"; }}; }};
      channel = {{ legacyPackages.x86_64-linux.python3 = "/nix/store/{'b' * 32}-python3"; }};
      host = {{
        config.networking.hostName = "stub";
        options.home-manager.users.valueMeta.attrs.tester.configuration.options.home.file.definitionsWithLocations =
          [ {definitions} ];
      }};
      c = {{
        nixpkgs.hostPlatform.system = "x86_64-linux";
        networking.hostName = "stub";
        home-manager.extraSpecialArgs.inputs = {{
          self = {{ packages.x86_64-linux.agent-platform = package;
            {host_readings.HOSTS['mbp']} = {{ }}; {host_readings.HOSTS['anis-desktop']}.stub = host; }};
          nixpkgs = channel; nixpkgs-darwin = channel;
        }};
      }};
    in ({host_readings.AGENT_PLATFORM}) c {{ home.username = "tester"; home.homeDirectory = "/home/tester"; }}"""
    done = subprocess.run(
        [*host_readings.NIX, "--json", "--expr", expression],
        capture_output=True, text=True, timeout=120, env=accounts_sandbox.unsandboxed_environment())
    if done.returncode != 0:
        raise AssertionError(f"stub evaluation failed:\n{done.stderr[-4000:]}")
    return json.loads(done.stdout)


def definition(*entries):
    return "{ file = \"stub\"; value = { " + " ".join(entries) + " }; }"


TOOL = f'".agents/bin/tool" = {{ source = "{PKG}/bin/tool"; }};'
STANDARDS = f'".agents/standards" = {{ source = "{PKG}/share/agent-platform/standards"; }};'


class AgentPlatformPartTest(unittest.TestCase):
    def test_a_plain_entry_reads_as_a_link(self):
        got = stub_reading(definition(TOOL, STANDARDS))
        self.assertEqual(got["bin"]["tool"], linked(f"{PKG}/bin/tool", ".agents/bin/tool"))
        self.assertEqual(got["binEntries"], [".agents/bin/tool"])

    def test_an_enabled_entry_redirected_into_the_bin_directory_is_listed_by_its_target(self):
        got = stub_reading(definition(TOOL, 'extraTool = { source = "/x"; target = ".agents/bin/extra"; };'))
        self.assertEqual(sorted(got["binEntries"]), [".agents/bin/extra", ".agents/bin/tool"])

    def test_an_absolute_target_under_the_home_directory_is_read_as_home_manager_reads_it(self):
        got = stub_reading(definition(TOOL, 'extra = { source = "/x"; target = "/home/tester/.agents/bin/extra"; };'))
        self.assertEqual(sorted(got["binEntries"]), [".agents/bin/extra", ".agents/bin/tool"])

    def test_a_link_of_the_bin_directory_or_of_the_agents_directory_is_listed(self):
        for target in (".agents/bin", ".agents"):
            with self.subTest(target):
                entry = f'"{target}" = {{ source = "/x"; recursive = true; }};'
                got = stub_reading(definition(TOOL, entry))
                self.assertEqual(sorted(got["binEntries"]), sorted([target, ".agents/bin/tool"]))

    def test_a_disabled_entry_in_the_bin_directory_is_not_listed(self):
        got = stub_reading(definition(TOOL, '".agents/bin/extra" = { source = "/x"; enable = false; };'))
        self.assertEqual(got["binEntries"], [".agents/bin/tool"])

    def test_a_second_entry_for_one_path_is_not_a_link(self):
        got = stub_reading(definition(TOOL, STANDARDS, 'other = { source = "/y"; target = ".agents/standards"; };'))
        self.assertIsInstance(got["standards"], list)
        self.assertNotEqual(got["standards"], linked(f"{PKG}/share/agent-platform/standards", ".agents/standards"))

    def test_a_forced_source_does_not_read_as_a_plain_link(self):
        forced = '".agents/bin/tool" = { source = { _type = "override"; priority = 50; content = "/x"; }; };'
        got = stub_reading(definition(forced))
        self.assertNotEqual(got["bin"]["tool"], linked(f"{PKG}/bin/tool", ".agents/bin/tool"))


class MeasureTest(unittest.TestCase):
    """The sweep's measurement tells a set-up read from a read made anywhere else."""

    def run_case(self, case):
        with mock.patch.object(host_readings, "reading", return_value={"sudo": 1}):
            return measure(unittest.defaultTestLoader.loadTestsFromTestCase(case))

    def test_a_read_in_set_up_class_is_a_set_up_read(self):
        class InSetUp(unittest.TestCase):
            @classmethod
            def setUpClass(cls):
                host_readings.read("mbp", "sudo")

            def test_it(self):
                pass

        result, _, setup, elsewhere = self.run_case(InSetUp)
        self.assertTrue(result.wasSuccessful())
        self.assertEqual((setup, elsewhere), ({("mbp", "sudo")}, set()))

    def test_a_read_in_a_test_body_or_its_set_up_is_not_a_set_up_read(self):
        class InBody(unittest.TestCase):
            def test_it(self):
                host_readings.read("mbp", "sudo")

        class InPerTestSetUp(unittest.TestCase):
            def setUp(self):
                host_readings.read("eleven-m5", "sudo")

            def test_it(self):
                pass

        for case, host in ((InBody, "mbp"), (InPerTestSetUp, "eleven-m5")):
            _, _, setup, elsewhere = self.run_case(case)
            self.assertEqual((setup, elsewhere), (set(), {(host, "sudo")}))


class RefusingNixTest(unittest.TestCase):
    def run_wrapper(self, *argv):
        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "real" / "nix"
            real.parent.mkdir()
            real.write_text("#!/bin/sh\necho passed\n", encoding="utf-8")
            real.chmod(0o755)
            refused = Path(tmp) / "refused"
            wrapper = refusing_nix(tmp, real, refused)
            done = subprocess.run([str(wrapper), *argv], capture_output=True, text=True)
            return done, refused.exists()

    def test_a_host_evaluation_is_refused_in_every_form(self):
        forms = (
            ["eval", "--json", ".#nixosConfigurations.anis-desktop.config"],
            ["eval", ".#darwinConfigurations", "--apply", "hs: hs.mbp.config"],
            ["eval", "--apply", "hs: hs.mbp.config", ".#darwinConfigurations"],
            ["eval", "--expr", "(builtins.getFlake (toString ./.)).darwinConfigurations.mbp.config"],
        )
        for argv in forms:
            with self.subTest(argv=argv):
                done, was_refused = self.run_wrapper(*argv)
                self.assertEqual((done.returncode, was_refused), (1, True))

    def test_other_nix_invocations_run(self):
        for argv in (["--version"], ["config", "show", "--json"], ["eval", "--raw", "--file", "vars/default.nix", "username"]):
            with self.subTest(argv=argv):
                done, was_refused = self.run_wrapper(*argv)
                self.assertEqual((done.returncode, done.stdout.strip(), was_refused), (0, "passed", False))


class RunReadsEachHostOnce(unittest.TestCase):
    """Every host-reading test reads the cached answer in setUpClass, so a run evaluates each host once (AC1)."""

    # reader module -> the parts it reads
    READERS = {
        "tests.test_verify_pending_units": ("verify-pending", "verify-pending-darwin", "verify-pending-activation"),
        "tests.test_console_units": ("console", "console-darwin"),
        "tests.test_darwin_user_agent_reload": ("user-launchd",),
        "tests.test_darwin_path_order": ("zsh-init",),
        "tests.test_host_sudo": ("sudo",),
        "tests.test_runner_home": ("runner-home",),
        "tests.test_system_packages": ("system-packages",),
        "tests.test_owner_services_units": ("owner-services", "owner-activation"),
        "tests.test_proof_run_units": ("proof-run",),
        "tests.test_github_runners": ("runners", "runner-triples"),
        "tests.test_platform_package_hosts": ("agent-platform",),
        "tests.test_omlx_declaration": ("omlx",),
        "tests.test_omlx_activation_hold": ("omlx",),
        "tests.test_memory_budget": ("memory-budget",),
    }
    # test ids the sweep does not run because they evaluate for real
    REAL_EVALUATIONS = ("tests.test_github_runners.RegisterRunnersTest.test_one_recipe_run_evaluates_the_real_configuration",)
    MENTIONS_ALLOWED = {
        "tests/host_readings.py": "the cache itself",
        "tests/test_host_readings.py": "the cache's own tests",
        "tests/test_branch_protection.py": "CI's Nix Eval job text, not an evaluation",
        "tests/test_verification_command.py": "CI's Nix Eval step text, not an evaluation",
    }

    @staticmethod
    def members():
        lines = (ROOT / "justfile").read_text(encoding="utf-8").splitlines()
        start = lines.index("agent-workflow-tests *args:")
        body = []
        for line in lines[start + 1:]:
            if not line.startswith("  "):
                break
            body.append(line)
        return [line.strip().removesuffix(" \\") for line in body[1:]]

    @staticmethod
    def cases(suite):
        for item in suite:
            if isinstance(item, unittest.TestSuite):
                yield from RunReadsEachHostOnce.cases(item)
            else:
                yield item

    def test_no_other_test_names_a_host_output(self):
        paths = set(self.members()) | {f"tests/{path.name}" for path in (ROOT / "tests").glob("*.py")}
        naming = {
            path for path in paths
            if re.search(r"(nixos|darwin)Configurations", (ROOT / path).read_text(encoding="utf-8"))
        }
        self.assertLessEqual(naming, set(self.MENTIONS_ALLOWED), sorted(naming - set(self.MENTIONS_ALLOWED)))

    def test_a_run_evaluates_each_host_once_and_every_reader_reads_that_answer(self):
        real_nix = shutil.which("nix")
        self.assertIsNotNone(real_nix)
        with mock.patch.object(host_readings, "_evaluate", wraps=host_readings._evaluate) as evaluate:
            for host in host_readings.HOSTS:
                host_readings.reading(host)
        counts = Counter(call.args[0] for call in evaluate.call_args_list)
        self.assertTrue(all(count <= 1 for count in counts.values()), counts)

        darwin_machine = platform.system() == "Darwin"
        linux_builder = host_readings.can_build("x86_64-linux")
        with tempfile.TemporaryDirectory() as tmp:
            refused = Path(tmp) / "refused"
            refusing_nix(tmp, real_nix, refused)
            recorded = {}
            body_reads = {}
            results = {}
            with mock.patch.dict(os.environ, {"PATH": f"{tmp}:{os.environ['PATH']}"}):
                for name in self.READERS:
                    module = importlib.import_module(name)
                    cases = [case for case in self.cases(unittest.defaultTestLoader.loadTestsFromModule(module))
                             if case.id() not in self.REAL_EVALUATIONS]
                    result, output, setup, body = measure(unittest.TestSuite(cases))
                    results[name] = (result, output)
                    recorded[name] = setup
                    body_reads[name] = body
            for name, parts in self.READERS.items():
                with self.subTest(name):
                    result, stream = results[name]
                    self.assertTrue(result.wasSuccessful(), stream)
                    self.assertEqual(body_reads[name], set(), "a test reads a host outside setUpClass")
                    allowed = {(h, p) for p in parts for h in host_readings.PARTS[p].hosts}
                    expected = {
                        (h, p) for p in parts for h in host_readings.PARTS[p].hosts
                        if p in host_readings.select(
                            h, host_readings.PARTS, darwin_machine=darwin_machine, linux_builder=linux_builder)[0]
                    }
                    self.assertLessEqual(expected, recorded[name])
                    self.assertLessEqual(recorded[name], allowed)
            refusals = refused.read_text() if refused.exists() else ""
            self.assertEqual(refusals, "", "a reader ran a host evaluation of its own")

        paths = set(self.members()) | {f"tests/{path.name}" for path in (ROOT / "tests").glob("test_*.py")}
        readers = {
            path for path in paths
            if path != "tests/test_host_readings.py" and "host_readings" in (ROOT / path).read_text(encoding="utf-8")
        }
        self.assertEqual(readers, {name.replace(".", "/") + ".py" for name in self.READERS})


if __name__ == "__main__":
    unittest.main()
