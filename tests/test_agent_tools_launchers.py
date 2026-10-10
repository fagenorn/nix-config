"""Installed-layout seam for the agent_tools launchers (#175 D8, D11; #179 D8; #177 D9; parent D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Every
`.agents/bin` entry that names the package, other than `NOT_LAUNCHERS`, must be a
generated launcher, and
each launcher must run its store module even with a fake `agent_tools` and a fake
top-level `agent_platform` on the
`PYTHONPATH`, `NIX_PYTHONPATH` (with a `.pth` file) and working-directory
channels.
"""

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from .retained_evidence_test_support import ANCHOR_SHA256, BUNDLE

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
PACKAGE_BYTES = b"agent_tools"
# `writeShellScript` prepends the shebang and appends a newline to the body.
LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I -m agent_tools\.(?P<module>[a-z][a-z0-9_]*) "\$@"\n*'
)
SCRIPT_LAUNCHER = re.compile(
    rb"#![^\n]+\n"
    rb"unset NIX_PYTHONPATH NIX_PYTHONPREFIX NIX_PYTHONEXECUTABLE\n"
    rb"exec (?P<python>/nix/store/[^/\s]+/bin/python3)"
    rb' -I (?P<script>/nix/store/[^/\s]+-workflow-state\.py) "\$@"\n*'
)
MARKER = "HOSTILE agent_tools IMPORTED"
HOSTILE_EXIT = 97
TIMEOUT_SECONDS = 60
# Flat installed scripts that name the package without being `-m` launchers: only
# `workflow-state`, a script launcher under the same interpreter, checked by
# `SCRIPT_LAUNCHER` (#337 D11, D16); its transitional lookups run
# `agent_tools.resolve_project` and load `host_admission` from `~/.agents/lib/python`
# (#177 D6, D13). #178 deletes this entry with them.
NOT_LAUNCHERS = ("workflow-state",)
# The commands #175, #179, #177, #249, #264 and #279 accepted as launchers: a floor, not the full
# set, which the command table in lib/agent-tools.nix owns (#175 D8).
LAUNCHER_FLOOR = ("adopt-project", "agent-evidence", "agent-model-matrix", "conformance",
                  "context-map-lint", "derive-review-feasibility-fixtures", "diff-scope",
                  "lane-triage", "replay-retained", "resolve-project", "review-feasibility",
                  "review-package", "review-range")
# The retained commands (#249) and their modules: refusal parity cases below.
RETAINED = {"derive-review-feasibility-fixtures": "derive_review_feasibility_fixtures",
            "replay-retained": "replay_retained"}
# Legacy commands may treat --help as misuse, including parser-backed commands
# with help disabled; pin each existing exit/stdout/stderr contract.
MISUSE_USAGE = {"context-map-lint": "Usage: context-map-lint --repo-root ",
                **{name: f"{name}: invalid: usage\n" for name in RETAINED}}
# Stub retained members (#254): a kind and an old schema version, and no fact. They are no compact payload,
# so replay refuses them once the envelope around them is authentic. `RetainedLauncherTest` holds the proof
# for each whole SOURCE encoding.
STUB_MEMBERS = {"issue-100-derived.json": {"kind": "issue-100-retained-history", "schema_version": 1},
                "issue-121.json": {"kind": "issue-121-retained-history", "schema_version": 3}}


def canonical(value) -> bytes:
    """CORE's canonical JSON bytes, spelled here because this module imports no `agent_tools`."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def stub_bundle(directory) -> str:
    """Write a five-file bundle around `STUB_MEMBERS` into the new `directory`; the anchor's digest.

    The anchor, the witness and the member rows agree with one another, so replay authenticates the bundle
    and refuses it only for what it reads inside the retained members."""
    groups = dict.fromkeys(("tool", "issue_121", "issue_100", "archive", "estimate"), {})
    raw = {name: canonical(value) for name, value in {**STUB_MEMBERS, "task7-estimate.json": {}}.items()}

    def rows():
        return [{"path": name, "bytes": len(raw[name]), "raw_sha256": hashlib.sha256(raw[name]).hexdigest()}
                for name in sorted(raw)]
    raw["derivation-witness.json"] = canonical({
        "schema_version": 2, "kind": "review-feasibility-derivation-witness", "components": groups,
        "fixtures": rows(), "tables": [], "table_policies": {}})
    anchor = {"schema_version": 2, "kind": "review-feasibility-derivation-anchor", **groups,
              "payload": {"encoding": "canonical-json-ascii-lf/v1", "members": rows()}}
    directory.mkdir()
    for name, data in {**raw, "derivation-anchor.json": canonical(anchor)}.items():
        (directory / name).write_bytes(data)
    return "sha256:" + hashlib.sha256(canonical(anchor)[:-1]).hexdigest()


class AgentToolsLauncherTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the launchers the Nix build installs"
            )
        cls.root = Path(root)

    def setUp(self):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.hostile = Path(scratch.name).resolve()
        package = self.hostile / "agent_tools"
        package.mkdir()
        (package / "__init__.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )
        # A site directory's .pth `import` line runs at startup, so this puts
        # the fake package ahead of the environment's site-packages.
        (self.hostile / "hostile.pth").write_text(
            f"import sys; sys.path.insert(0, {str(self.hostile)!r})\n",
            encoding="utf-8",
        )
        # A bare `import agent_platform` was the old resolver bootstrap's
        # adversary; a launcher must never reach this one (#177 D9).
        (self.hostile / "agent_platform.py").write_text(
            f"import sys\nsys.stderr.write({MARKER!r} + '\\n')\n"
            f"raise SystemExit({HOSTILE_EXIT})\n",
            encoding="utf-8",
        )

    def launchers(self):
        """{command: (environment python, module)} for every entry naming the package."""
        found = {}
        for entry in sorted((self.root / ".agents" / "bin").iterdir()):
            data = entry.read_bytes()
            if entry.name in NOT_LAUNCHERS:
                self.assertIsNone(LAUNCHER.fullmatch(data),
                                  f"{entry} is a generated launcher; drop it from NOT_LAUNCHERS")
                continue
            if PACKAGE_BYTES not in data:
                continue
            match = LAUNCHER.fullmatch(data)
            self.assertIsNotNone(
                match, f"{entry} names agent_tools but is not a generated launcher")
            found[entry.name] = (match["python"].decode(), match["module"].decode())
        return found

    def run_child(self, argv, env, cwd):
        return subprocess.run(argv, env=env, cwd=cwd, capture_output=True, text=True,
                              timeout=TIMEOUT_SECONDS, check=False)

    def workflow_state_launcher(self):
        data = (self.root / ".agents/bin/workflow-state").read_bytes()
        match = SCRIPT_LAUNCHER.fullmatch(data)
        self.assertIsNotNone(match, data[:300])
        return match

    def test_workflow_state_runs_under_the_package_interpreter(self):
        match = self.workflow_state_launcher()
        pythons = {python for python, _module in self.launchers().values()}
        self.assertEqual(pythons, {match["python"].decode()})

    def test_workflow_state_ignores_a_hostile_agent_tools(self):
        completed = self.run_child(
            [str(self.root / ".agents/bin/workflow-state"), "--help"],
            self.hostile_env(), self.hostile)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertTrue(completed.stdout.startswith("usage: workflow-state "))
        self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_installed_workflow_state_mints_a_run_against_the_store_core(self):
        with tempfile.TemporaryDirectory() as repo:
            completed = self.run_child(
                [str(self.root / ".agents/bin/workflow-state"), "init-run", "--repo-root",
                 repo, "--creation-key", "installed-check"],
                self.hostile_env(), self.hostile)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertRegex(json.loads(completed.stdout)["run_id"], r"^rel_[0-9a-f-]{36}$")
            self.assertNotIn(MARKER, completed.stdout + completed.stderr)
            self.assertTrue((Path(repo) / ".superpowers/attempt-transactions").is_dir())

    def test_the_command_table_generates_each_deployed_command(self):
        launchers = self.launchers()
        for name in LAUNCHER_FLOOR:
            with self.subTest(launcher=name):
                self.assertIn(name, launchers)

    def test_each_launcher_is_named_for_its_module(self):
        for name, (_python, module) in self.launchers().items():
            with self.subTest(launcher=name):
                self.assertEqual(name, module.replace("_", "-"))

    def dependency_env(self):
        home = self.hostile / 'dependencies'
        bins = self.hostile / 'dependency-bin'
        if not home.exists():
            home.mkdir(); bins.mkdir()
            (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
            (bins / 'python3').symlink_to(self.launchers()['review-package'][0])
        return dict(os.environ, HOME=str(home),
                    PATH=str(bins) + os.pathsep + str(self.root / '.agents/bin')
                    + os.pathsep + os.environ['PATH'])

    def hostile_env(self):
        return dict(self.dependency_env(), PYTHONPATH=str(self.hostile),
                    NIX_PYTHONPATH=str(self.hostile))

    def test_a_hostile_agent_tools_on_every_channel_is_ignored(self):
        for name in self.launchers():
            with self.subTest(launcher=name):
                completed = self.run_child(
                    [str(self.root / '.agents/bin' / name), '--help'],
                    self.hostile_env(), self.hostile)
                if name == 'review-package':
                    self.assertEqual((completed.returncode, completed.stdout, completed.stderr),
                                     (2, '', 'review-package: invalid invocation\n'))
                elif name in MISUSE_USAGE:
                    self.assertEqual(completed.returncode, 2, completed.stderr)
                    self.assertEqual(completed.stdout, '')
                    self.assertIn(MISUSE_USAGE[name], completed.stderr)
                else:
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    self.assertTrue(completed.stdout.startswith(f'usage: {name} '), completed.stdout[:200])
                self.assertNotIn(MARKER, completed.stdout + completed.stderr)

    def test_each_hostile_channel_is_live_without_the_launcher(self):
        # Each control opens exactly one channel, so a dead channel cannot hide
        # behind a live one.
        clean = {key: value for key, value in self.dependency_env().items()
                 if key not in ("PYTHONPATH", "NIX_PYTHONPATH")}
        pythonpath_only = dict(clean, PYTHONPATH=str(self.hostile))
        nix_only = dict(clean, NIX_PYTHONPATH=str(self.hostile))
        for name, (python, module) in self.launchers().items():
            plain = [python, "-m", f"agent_tools.{module}", "--help"]
            controls = {
                # (a) PYTHONPATH alone reaches a plain run.
                "not isolated, PYTHONPATH only": (plain, pythonpath_only, self.root),
                # (a') the working directory alone reaches a plain run.
                "not isolated, working directory only": (plain, clean, self.hostile),
                # (b) -I alone leaves NIX_PYTHONPATH open, so the unset line
                # is load-bearing; if nixpkgs stops honouring it, this control
                # and that line go together (D11).
                "isolated, NIX_PYTHONPATH only": (
                    [python, "-I", "-m", f"agent_tools.{module}", "--help"],
                    nix_only, self.root),
            }
            for control, (argv, env, cwd) in controls.items():
                with self.subTest(launcher=name, control=control):
                    completed = self.run_child(argv, env, cwd)
                    self.assertEqual(completed.returncode, HOSTILE_EXIT, completed.stderr)
                    self.assertIn(MARKER, completed.stderr)


    def test_relocated_actual_command_matches_source(self):
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'actual-parity'
        top.mkdir()
        repo = top / 'repo'; repo.mkdir()
        home = top / 'home'; home.mkdir()
        (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
        env = {k: v for k, v in os.environ.items() if k not in
               ('PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        env.update(HOME=str(home), PYTHONPATH=str(source / 'python'),
                   PATH=self.dependency_env()['PATH'])
        def git(*args):
            result = subprocess.run(['git', *args], cwd=repo, env=env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.decode().strip()
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test'); git('config', 'commit.gpgsign', 'false')
        (repo / 'value.txt').write_text('before\n')
        git('add', '-A'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD')
        (repo / 'value.txt').write_text('after\n')
        (repo / 'plan.md').write_text('# Plan\n\n## Task index\n\nTask 1 — Case — value.txt — full — '
                                    '[task-1.md](plan.tasks/task-1.md)\n')
        (repo / 'plan.tasks').mkdir(); (repo / 'plan.tasks/task-1.md').write_text('# Task 1\n')
        git('add', '-A'); git('commit', '-qm', 'change'); head = git('rev-parse', 'HEAD')
        roots = []
        for label in ('source', 'built'):
            out = top / label; out.mkdir(); root = out / 'review.json'; roots.append(root)
            childenv = dict(env)
            argv = [sys.executable, '-m', 'agent_tools.review_package']
            if label == 'built':
                argv = [str(self.root / '.agents/bin/review-package')]
                childenv.update(PYTHONPATH=str(self.hostile), NIX_PYTHONPATH=str(self.hostile))
            produced = subprocess.run([*argv, str(repo / 'plan.md'), base, head, str(root)],
                                      cwd=repo, env=childenv, capture_output=True)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            self.assertNotIn(MARKER.encode(), produced.stdout + produced.stderr)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json'], env=env, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            self.assertEqual(json.loads(produced.stdout)['artifact']['metrics'],
                             json.loads(checked.stdout)['metrics'])
        self.assertEqual(roots[0].read_bytes(), roots[1].read_bytes())
        for member in roots[0].with_suffix('.shards').iterdir():
            self.assertEqual(member.read_bytes(), (roots[1].with_suffix('.shards') / member.name).read_bytes())

    def test_review_source_and_built_canonical_actual_parity(self):
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'review-case'
        top.mkdir()
        repo = top / 'repo'
        repo.mkdir()
        clean = {k: v for k, v in os.environ.items()
                 if k not in ('PYTHONPATH', 'NIX_PYTHONPATH',
                              'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        envs = {}
        for label, agents in (('source', source / 'home/common/agent-skills'),
                              ('built', self.root / '.agents')):
            home = top / (label + '-home')
            home.mkdir()
            if label == 'built':
                (home / '.agents').symlink_to(agents, target_is_directory=True)
                bins = agents / 'bin'
            else:
                lib = home / '.agents/lib/python'
                lib.mkdir(parents=True)
                (lib / 'artifact_budget.py').symlink_to(agents / 'scripts/artifact_budget.py')
                (lib / 'delivery_model').symlink_to(agents / 'scripts/delivery_model',
                                                    target_is_directory=True)
                (home / '.agents/share').mkdir()
                (home / '.agents/share/artifact-budget-policy.json').symlink_to(
                    agents / 'artifact-budget-policy.json')
                bins = agents / 'scripts'
            runtime = top / (label + '-bin'); runtime.mkdir()
            interpreter = sys.executable if label == 'source' else self.launchers()['review-package'][0]
            (runtime / 'python3').symlink_to(interpreter)
            envs[label] = dict(clean, HOME=str(home),
                PATH=str(runtime) + os.pathsep + str(bins) + os.pathsep + clean['PATH'])
        envs['source']['PYTHONPATH'] = str(source / 'python')
        envs['built'].update(PYTHONPATH=str(self.hostile),
            NIX_PYTHONPATH=str(self.hostile), NIX_PYTHONPREFIX=str(self.hostile),
            NIX_PYTHONEXECUTABLE=str(self.hostile / 'no-python'))
        def run(argv, *, label='source', payload=None):
            return subprocess.run(argv, cwd=repo, env=envs[label], input=payload,
                                  capture_output=True, timeout=60)
        def git(*args):
            result = run(['git', *args])
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout.decode().strip()
        def write(path, value):
            target = repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(value if isinstance(value, bytes) else value.encode())
        def commit(subject):
            git('add', '-A'); git('commit', '-qm', subject)
            return git('rev-parse', 'HEAD')
        def wire(value):
            return (json.dumps(value, sort_keys=True, separators=(',', ':'),
                               ensure_ascii=True) + '\n').encode()
        def command(label, name, *args, payload=None):
            argv = ([sys.executable, '-m', 'agent_tools.' + name.replace('-', '_')]
                    if label == 'source' else [str(self.root / '.agents/bin' / name)])
            result = run([*argv, *args], label=label, payload=payload)
            self.assertNotIn(MARKER.encode(), result.stdout + result.stderr)
            return result
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test')
        git('config', 'commit.gpgsign', 'false')
        write('seed.txt', 'seed\n'); base = commit('base')
        write('seed.txt', 'seed\nchanged\n'); product = commit('product')
        package = dict(spec='spec.md', plan='plan.md', tasks=['plan.tasks/task-1.md'])
        paths = [package['spec'], package['plan'], *package['tasks']]
        records = [dict(id=f'p{n}', owner=0, path=path, change='add', last_task=1,
            bounds=[dict(boundary='core', added_lines=1, deleted_lines=0, record_bytes=1,
                support=dict(kind='authored-cumulative/v1', covers=[f'p{n}']))])
            for n, path in enumerate(paths)]
        delivery = dict(schema_version=3, kind='review-feasibility-delivery',
            delivery_base=base, proposed_boundary='core', derived_from=None,
            boundaries=[dict(id='core', parent=None, tasks=[1], acceptance='Generic source/built parity',
                depends_on=[], prerequisite=dict(kind='delivery-base'), process_package=package,
                process_forecast_ids=[r['id'] for r in records], process_commit_subject_bytes=[])],
            process_records=records, actual_evidence=dict(kind='git-range-ownership/v1',
                head=product, tree=git('rev-parse', product + '^{tree}'), process_ranges=[]))
        task = dict(schema_version=3, kind='review-feasibility-task', task=dict(id=1,
            commit_subject_bytes=[], actual_ranges=[dict(base=base, head=product)], records=[]))
        write('spec.md', '# Generic parity\n')
        write('plan.md', '# Plan\n\n## Task index\n\nTask 1 — Case — seed.txt — full — '
            '[task-1.md](plan.tasks/task-1.md)\n\n## Review feasibility delivery\n\n```json\n'
            + wire(delivery).decode() + '```\n')
        write('plan.tasks/task-1.md', '# Task 1\n\n## Review feasibility task\n\n```json\n'
            + wire(task).decode() + '```\n')
        head = commit('process package')
        before = git('status', '--porcelain'), git('rev-parse', 'HEAD^{tree}')
        projected = {}
        for label in ('source', 'built'):
            outdir = top / (label + '-out'); outdir.mkdir()
            root = outdir / 'review.json'
            actual = command(label, 'review-package', str(repo / 'plan.md'), base, head, str(root))
            self.assertEqual(actual.returncode, 0, actual.stderr)
            # The external checker uses the same private layout but no hostile startup variables.
            checkenv = dict(envs[label])
            for key in ('PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE'):
                checkenv.pop(key, None)
            checked = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json'], env=checkenv, capture_output=True)
            self.assertEqual(checked.returncode, 0, checked.stderr)
            metrics = json.loads(actual.stdout)['artifact']['metrics']
            self.assertEqual(metrics, json.loads(checked.stdout)['metrics'])
            result = command(label, 'review-feasibility', 'project', '--plan', str(repo / 'plan.md'),
                '--base', base, '--head', head, '--completed-through', '1', '--package-name', 'review.json')
            self.assertEqual(result.returncode, 0, result.stderr)
            value = json.loads(result.stdout)
            self.assertEqual(value['metrics'], metrics)
            self.assertEqual((value['base'], value['head'], value['tree']),
                             (base, head, git('rev-parse', head + '^{tree}')))
            self.assertEqual((value['completed_through'], value['boundary'], value['package_name']),
                             (1, 'core', 'review.json'))
            self.assertEqual((value['state'], value['budget_status'], value['violations'],
                              value['recommended_boundary']), ('complete', 'within_budget', [], None))
            validated = command(label, 'review-feasibility', 'validate-result', '--input', '-',
                                '--producer-exit', '0', payload=result.stdout)
            self.assertEqual((validated.returncode, validated.stdout), (0, result.stdout), validated.stderr)
            for bad, status in ((b'', '0'), (result.stdout + b' ', '0'),
                    (result.stdout.replace(b'"schema_version":3', b'"schema_version":true'), '0'),
                    (result.stdout, '3')):
                refused = command(label, 'review-feasibility', 'validate-result', '--input', '-',
                                  '--producer-exit', status, payload=bad)
                self.assertEqual((refused.returncode, refused.stdout), (2, b''), refused.stderr)
            projected[label] = result.stdout
            description = subprocess.run(['artifact-budget', 'describe', '--kind', 'review-package',
                '--format', 'json'], env=checkenv, capture_output=True)
            self.assertEqual(description.returncode, 0, description.stderr)
            policy = Path(checkenv['HOME']) / '.agents/share/artifact-budget-policy.json'
            self.assertEqual(json.loads(description.stdout)['policy_sha256'],
                             'sha256:' + hashlib.sha256(policy.read_bytes()).hexdigest())
            self.assertEqual(value['artifact_policy_sha256'], json.loads(description.stdout)['policy_sha256'])
            refused = subprocess.run(['artifact-budget', 'check', '--kind', 'review-package',
                '--root', str(root), '--format', 'json', '--expected-policy-sha256', 'sha256:' + '0' * 64],
                env=checkenv, capture_output=True)
            self.assertEqual(refused.returncode, 2, refused.stderr)
        self.assertEqual(projected['source'], projected['built'])
        self.assertEqual((top / 'source-out/review.json').read_bytes(),
                         (top / 'built-out/review.json').read_bytes())
        for a in (top / 'source-out/review.shards').iterdir():
            self.assertEqual(a.read_bytes(), (top / 'built-out/review.shards' / a.name).read_bytes())
        self.assertEqual(before, (git('status', '--porcelain'), git('rev-parse', 'HEAD^{tree}')))

    def retained_pair(self, command, args):
        """`(built, source)` outcomes of one retained command: (exit, stdout bytes, stderr bytes) each."""
        source_env = dict(self.dependency_env(), PYTHONPATH=str(Path(__file__).resolve().parents[1] / "python"))
        clean = self.hostile / "clean"; clean.mkdir(exist_ok=True)
        runs = (([str(self.root / ".agents/bin" / command)], self.hostile_env(), self.hostile),
                ([sys.executable, "-m", "agent_tools." + RETAINED[command]], source_env, clean))
        outcomes = []
        for argv, env, cwd in runs:
            done = subprocess.run([*argv, *args], env=env, cwd=cwd, capture_output=True,
                                  timeout=TIMEOUT_SECONDS, check=False)
            self.assertNotIn(MARKER.encode(), done.stdout + done.stderr)
            outcomes.append((done.returncode, done.stdout, done.stderr))
        return outcomes

    def test_retained_commands_refuse_alike_from_source_and_built(self):
        existing = self.hostile / "exists"; existing.mkdir()
        repo = self.hostile / "repo"; repo.mkdir()
        # A repository input must answer `git rev-parse --git-common-dir`, or the refusal is `invalid_inputs`.
        subprocess.run(["git", "init", "-q", str(repo)], check=True, capture_output=True, timeout=TIMEOUT_SECONDS)
        cases = (("replay-retained", "anchor_unreadable",
                  ["--fixtures-dir", str(self.hostile / "missing"), "--expected-anchor-sha256", "sha256:" + "0" * 64]),
                 ("replay-retained", "usage", ["--fixtures-dir", str(repo)]),
                 ("derive-review-feasibility-fixtures", "output_exists",
                  ["--issue-121-repo", str(repo), "--issue-100-repo", str(repo), "--archive-dir", str(repo),
                   "--tool-repo", str(repo), "--tool-commit", "0" * 40, "--output-dir", str(existing)]),
                 ("derive-review-feasibility-fixtures", "tool_closure",
                  ["--issue-121-repo", str(repo), "--issue-100-repo", str(repo), "--archive-dir", str(repo),
                   "--tool-repo", str(repo), "--tool-commit", "0" * 40, "--output-dir", str(self.hostile / "absent")]))
        for command, code, args in cases:
            with self.subTest(command=command, code=code):
                built, source = self.retained_pair(command, args)
                self.assertEqual(built, source)
                self.assertEqual(built, (2, b"", f"{command}: invalid: {code}\n".encode()))
        self.assertEqual(list(existing.iterdir()), [])
        self.assertFalse((self.hostile / "absent").exists())

    def sealed_replay_pair(self, bundle, digest):
        """`(built, source)` outcomes of `replay-retained` with the sources unreachable: `HOME` is a scratch
        directory and `PATH` one empty directory, so neither run can find Git or the budget helper. The built
        launcher names its interpreter by store path and the source run is this interpreter, so neither needs
        `PATH`. The built run keeps the hostile package on every channel; the source run names the source tree."""
        sealed = self.hostile / "sealed"
        (sealed / "bin").mkdir(parents=True, exist_ok=True)
        env = {"HOME": str(sealed), "PATH": str(sealed / "bin")}
        self.assertEqual([shutil.which(name, path=env["PATH"]) for name in ("git", "artifact-budget")], [None, None])
        args = ["--fixtures-dir", str(bundle), "--expected-anchor-sha256", digest]
        hostile, source = str(self.hostile), str(Path(__file__).resolve().parents[1] / "python")
        runs = (([str(self.root / ".agents/bin/replay-retained")],
                 dict(env, PYTHONPATH=hostile, NIX_PYTHONPATH=hostile), self.hostile),
                ([sys.executable, "-m", "agent_tools." + RETAINED["replay-retained"]],
                 dict(env, PYTHONPATH=source), sealed))
        outcomes = []
        for argv, run_env, cwd in runs:
            done = subprocess.run([*argv, *args], env=run_env, cwd=cwd, capture_output=True,
                                  timeout=TIMEOUT_SECONDS, check=False)
            self.assertNotIn(MARKER.encode(), done.stdout + done.stderr)
            outcomes.append((done.returncode, done.stdout, done.stderr))
        return outcomes

    def test_replay_refuses_stub_bundles_alike_from_source_and_built(self):
        """The envelope refusals on a bundle that holds no retained fact, with the sources unreachable: a stub
        member under coherent digests, a replacement anchor, a changed member and a partial bundle."""
        def replace_anchor(bundle):
            path = bundle / "derivation-anchor.json"
            path.write_bytes(canonical({**json.loads(path.read_bytes()), "tool": {"commit": "0" * 40}}))
        cases = (("invalid_payload", lambda bundle: None), ("anchor_digest", replace_anchor),
                 ("member_digest", lambda bundle: (bundle / "issue-121.json").write_bytes(canonical({}))),
                 ("member_set", lambda bundle: (bundle / "task7-estimate.json").unlink()))
        for code, alter in cases:
            with self.subTest(code=code):
                bundle = self.hostile / f"stub-{code}"
                digest = stub_bundle(bundle)
                alter(bundle)
                before = {path.name: path.read_bytes() for path in bundle.iterdir()}
                built, source = self.sealed_replay_pair(bundle, digest)
                self.assertEqual(built, source)
                self.assertEqual(built, (2, b"", f"replay-retained: invalid: {code}\n".encode()))
                self.assertEqual({path.name: path.read_bytes() for path in bundle.iterdir()}, before)

    def test_committed_evidence_replays_alike_from_source_and_built(self):
        """Issue 235: copies of the committed bundle, with the sources unreachable. The authentic copy is the
        historical refusal, and each changed copy is refused under the trusted digest. The last copy is rebuilt
        as a forger would and replayed under the forger's own digest, where the malformed issue-100 member is
        invalid beside the unchanged issue-121 refusal."""
        def changed(bundle):
            path = bundle / "issue-121.json"
            data = path.read_bytes()
            path.write_bytes(data[:100] + (b"1" if data[100:101] != b"1" else b"0") + data[101:])

        def replaced(bundle):
            path = bundle / "derivation-anchor.json"
            anchor = json.loads(path.read_bytes())
            path.write_bytes(canonical({**anchor, "tool": {**anchor["tool"], "commit": "0" * 40}}))

        def malformed(bundle):
            decoded = {path.name: json.loads(path.read_bytes()) for path in bundle.iterdir()}
            del decoded["issue-100-derived.json"]["process"]
            anchor, witness = decoded["derivation-anchor.json"], decoded["derivation-witness.json"]
            for name, rows in (("issue-100-derived.json", witness["fixtures"]),
                               ("issue-100-derived.json", anchor["payload"]["members"]),
                               ("derivation-witness.json", anchor["payload"]["members"])):
                raw = canonical(decoded[name])
                (row,) = (row for row in rows if row["path"] == name)
                row.update(bytes=len(raw), raw_sha256=hashlib.sha256(raw).hexdigest())
            for name, value in decoded.items():
                (bundle / name).write_bytes(canonical(value))
            return "sha256:" + hashlib.sha256(canonical(anchor)[:-1]).hexdigest()

        cases = (("projection_unavailable: tasks-1-3,tasks-4-6", lambda bundle: None),
                 ("invalid: member_digest", changed),
                 ("invalid: member_set", lambda bundle: (bundle / "task7-estimate.json").unlink()),
                 ("invalid: anchor_digest", replaced), ("invalid: invalid_payload", malformed))
        for n, (reason, alter) in enumerate(cases):
            with self.subTest(reason=reason):
                bundle = Path(shutil.copytree(BUNDLE, self.hostile / f"evidence-{n}"))
                digest = alter(bundle) or ANCHOR_SHA256
                built, source = self.sealed_replay_pair(bundle, digest)
                self.assertEqual(built, source)
                self.assertEqual(built, (2, b"", f"replay-retained: {reason}\n".encode()))

    def test_replay_refuses_a_forged_bundle_alike_from_source_and_built(self):
        forged = self.hostile / "forged"; forged.mkdir()
        names = ("derivation-anchor.json", "derivation-witness.json", "issue-100-derived.json",
                 "issue-121.json", "task7-estimate.json")
        for name in names:
            (forged / name).write_bytes(b"{}\n")
        digest = "sha256:" + hashlib.sha256(b"{}").hexdigest()   # telemetry_digest({}): coherent with the anchor
        built, source = self.retained_pair(
            "replay-retained", ["--fixtures-dir", str(forged), "--expected-anchor-sha256", digest])
        self.assertEqual(built, source)
        self.assertEqual(built, (2, b"", b"replay-retained: invalid: anchor_shape\n"))
        self.assertEqual(sorted(p.name for p in forged.iterdir()), sorted(names))


RETAINED_ROOT_ENV = "AGENT_RETAINED_ROOT"
RETAINED_RECIPE = "just agent-retained-tests <root>"
# One derivation over the real retained inputs takes minutes, not `TIMEOUT_SECONDS`.
DERIVE_TIMEOUT_SECONDS = 60 * 60


class RetainedLauncherTest(AgentToolsLauncherTest):
    """Full-shape parity (#249): both retained commands, built and from source, over the real retained inputs.

    Run: just agent-retained-tests <root>. That recipe sets AGENT_RETAINED_ROOT beside the built tree; without
    it the class skips, which is never acceptance. The retained root is compared before and after each test.
    """

    @classmethod
    def setUpClass(cls):
        if os.environ.get(RETAINED_ROOT_ENV) is None:
            raise unittest.SkipTest(f"{RETAINED_ROOT_ENV} is unset; run `{RETAINED_RECIPE}` for the full-shape tier")
        if os.environ.get(INSTALLED_HOME_ENV) is None:  # nothing skips once the retained root is named
            raise AssertionError(f"{INSTALLED_HOME_ENV} is unset; `{RETAINED_RECIPE}` sets it")
        super().setUpClass()

    def setUp(self):
        super().setUp()
        # Imported here, not above: it imports `agent_tools`, which only the retained recipe puts on the path.
        from . import test_review_retained_full as full
        self.full, self.retained = full, full.retained_root()
        full.watch_root(self, self.retained)

    def test_real_derivation_and_replay_match_from_source_and_built(self):
        derive, replay = RETAINED
        clean = self.hostile / "clean"; clean.mkdir()
        source_env = dict(self.dependency_env(), PYTHONPATH=str(Path(__file__).resolve().parents[1] / "python"))
        runs = {"built": ([str(self.root / ".agents/bin" / derive)], self.hostile_env(), self.hostile),
                "source": ([sys.executable, "-m", "agent_tools." + RETAINED[derive]], source_env, clean)}
        commit, summaries, bundles = self.full.tool_commit(), {}, {}
        for label, (argv, env, cwd) in runs.items():
            out = self.hostile / f"{label}-bundle"
            done = subprocess.run([*argv, *self.full.derive_argv(self.retained, commit, output_dir=out)], env=env,
                                  cwd=cwd, capture_output=True, timeout=DERIVE_TIMEOUT_SECONDS, check=False)
            self.assertEqual((done.returncode, done.stderr), (0, b""), label)
            summaries[label], bundles[label] = done.stdout, {p.name: p.read_bytes() for p in out.iterdir()}
        self.assertEqual(summaries["built"], summaries["source"])
        self.assertEqual(bundles["built"], bundles["source"])
        self.assertEqual(len(bundles["built"]), 5)
        built, source = self.retained_pair(replay, [
            "--fixtures-dir", str(self.hostile / "built-bundle"),
            "--expected-anchor-sha256", json.loads(summaries["built"])["anchor_sha256"]])
        self.assertEqual(built, source)
        # Whatever the proof produced, the outcome is a row of the exit table that is not a refusal.
        status, stdout, stderr = built
        if status == 0:
            self.assertEqual((json.loads(stdout)["schema_version"], stderr), (3, b""))
        else:
            self.assertEqual((status, stdout), (2, b""))
            self.assertRegex(stderr.decode(), rf"\A{replay}: projection_unavailable: [a-z0-9.,-]+\n\Z")
        # Rehashed alterations of the real bundle, with the sources unreachable: each is invalid under the
        # forger's own digest and never authentic under the trusted one. They are a changed fact, then a
        # missing edge, a reordered edge, a duplicate record and the whole SOURCE encoding, for each payload.
        full, trusted = self.full, json.loads(summaries["built"])["anchor_sha256"]
        changes = [("issue-100 process path", full.substituted(full.ISSUE_100, "process", 0)),
                   *((label, change) for _, label, change in full.REHASHED_FORGERIES)]
        for n, (label, change) in enumerate(changes):
            forged = Path(shutil.copytree(self.hostile / "built-bundle", self.hostile / f"forged-{n}"))
            anchor, raw = full.rebuilt(forged, trusted, change)
            for name, data in {**raw, full.ANCHOR_NAME: full.canonical_bytes(anchor)}.items():
                (forged / name).write_bytes(data)
            for digest, code in ((full.telemetry_digest(anchor), "invalid_payload"), (trusted, "anchor_digest")):
                with self.subTest(forgery=label, code=code):
                    built, source = self.sealed_replay_pair(forged, digest)
                    self.assertEqual(built, source)
                    self.assertEqual(built, (2, b"", f"{replay}: invalid: {code}\n".encode()))


if __name__ == "__main__":
    unittest.main()
