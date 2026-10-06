# Task 3: Source/built parity, full-shape case and final gates

**Files:**
- Modify: `tests/test_agent_tools_launchers.py` (one new `AgentToolsLauncherTest` case; `RetainedLauncherTest`'s built run made hostile)
- Modify: `tests/test_review_retained_full.py` (one new `RetainedFullTest` case)

**Interfaces:**
- Consumes: `tests.hostile_git_test_support.hostile_git_env(owned, base, repos=()) -> dict[str, str]` (Task 1, standard library only, so the installed tier may import it); in the launcher module `self.root`, `self.hostile`, `self.dependency_env()`, `self.hostile_env()`, `MARKER`, `TIMEOUT_SECONDS`, `RETAINED`, and in `RetainedLauncherTest` `self.full` and `self.retained`; in the full tier `COMMITS`, `DERIVE`, `ISSUE_100`, `ISSUE_121`, `ESTIMATE`, `BUNDLE`, `derive_argv`, `self.disposable_clone()`, `self.env`, `self.tool_commit`, `self.summary`, `self.bundle`, `self.root`, `self.tmp`.
- Produces: no new name.

**Invariants:**
- The clean source run, the hostile source run and the hostile built run of `review-package` write the same report (path aside) and the same package bytes (D8).
- The retained root is never written: hostile repository files go only into the disposable clone, and `RetainedLauncherTest` uses environment-only hostility (`repos=()`) (RP11).
- Under hostility, a derivation from a clone writes the class bundle's five files, and its three payload members equal the committed bundle's (D2).
- Every hostile case carries a control that shows raw Git renders differently under it (D6). Each control's clean run comes before `hostile_git_env` writes into the repository it reads.

- [ ] **Step 1: Write the installed-tier case**

In `tests/test_agent_tools_launchers.py`, add `from .hostile_git_test_support import hostile_git_env` beside the existing `retained_evidence_test_support` import. Add this method to `AgentToolsLauncherTest`, directly after `test_relocated_actual_command_matches_source`:

```python
    def test_review_package_ignores_hostile_git_alike_from_source_and_built(self):
        """Issue 255: the clean source run, and the source and built runs under every hostile record source a
        test can own, write the same package. The control: raw Git renders the range differently there."""
        source = Path(__file__).resolve().parents[1]
        top = self.hostile / 'hostile-git'
        top.mkdir()
        repo = top / 'repo'; repo.mkdir()
        home = top / 'home'; home.mkdir()
        (home / '.agents').symlink_to(self.root / '.agents', target_is_directory=True)
        env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and k not in
               ('XDG_CONFIG_HOME', 'PYTHONPATH', 'NIX_PYTHONPATH', 'NIX_PYTHONPREFIX', 'NIX_PYTHONEXECUTABLE')}
        env.update(HOME=str(home), PYTHONPATH=str(source / 'python'), PATH=self.dependency_env()['PATH'],
                   GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM='1')
        def git(*args, run_env=env):
            result = subprocess.run(['git', *args], cwd=repo, env=run_env, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            return result.stdout
        git('init', '-q'); git('config', 'user.name', 'Fixture')
        git('config', 'user.email', 'fixture@example.test'); git('config', 'commit.gpgsign', 'false')
        (repo / 'value.md').write_text('title\n\nbefore\n')
        git('add', '-A'); git('commit', '-qm', 'base'); base = git('rev-parse', 'HEAD').decode().strip()
        (repo / 'value.md').write_text('title\n\nafter\n')
        (repo / 'plan.md').write_text('# Plan\n\n## Task index\n\nTask 1 — Case — value.md — full — '
                                    '[task-1.md](plan.tasks/task-1.md)\n')
        (repo / 'plan.tasks').mkdir(); (repo / 'plan.tasks/task-1.md').write_text('# Task 1\n')
        git('add', '-A'); git('commit', '-qm', 'café change'); head = git('rev-parse', 'HEAD').decode().strip()
        source_argv = [sys.executable, '-m', 'agent_tools.review_package']
        outcomes = {}
        def produce(label, argv, run_env):
            out = top / label; out.mkdir(); root = out / 'review.json'
            produced = subprocess.run([*argv, str(repo / 'plan.md'), base, head, str(root)], cwd=repo,
                                      env=run_env, capture_output=True, timeout=TIMEOUT_SECONDS)
            self.assertEqual(produced.returncode, 0, produced.stderr)
            self.assertNotIn(MARKER.encode(), produced.stdout + produced.stderr)
            report = json.loads(produced.stdout)
            self.assertEqual(report['artifact'].pop('path'), str(root))
            outcomes[label] = report, {p.relative_to(out).as_posix(): p.read_bytes()
                                       for p in sorted(out.rglob('*')) if p.is_file()}
        clean_raw = git('diff', '--binary', '-U10', base, head)
        produce('clean-source', source_argv, env)
        hostile = hostile_git_env(top / 'owned', env, [repo])
        self.assertNotEqual(git('diff', '--binary', '-U10', base, head, run_env=hostile), clean_raw,
                            'the hostile sources never bit')
        produce('hostile-source', source_argv, hostile)
        produce('hostile-built', [str(self.root / '.agents/bin/review-package')],
                dict(hostile, PYTHONPATH=str(self.hostile), NIX_PYTHONPATH=str(self.hostile)))
        self.assertEqual(outcomes['hostile-source'], outcomes['clean-source'])
        self.assertEqual(outcomes['hostile-built'], outcomes['clean-source'])
```

- [ ] **Step 2: Make the retained parity run hostile**

In `RetainedLauncherTest.test_real_derivation_and_replay_match_from_source_and_built`, keep the `source` run clean and run the `built` derivation under environment-only hostility. Directly after `source_env = ...`, insert:

```python
        hostile_env = hostile_git_env(self.hostile / "hostile-git", self.hostile_env())
        pair = ("diff", "--binary", "-U10", *self.full.COMMITS[:2])
        control = [subprocess.run(["git", "-C", str(self.retained), *pair], env=dict(e, GIT_OPTIONAL_LOCKS="0"),
                                  check=True, capture_output=True, timeout=TIMEOUT_SECONDS).stdout
                   for e in (dict(source_env, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1"), hostile_env)]
        self.assertNotEqual(control[0], control[1], "the hostile sources never bit")
```

and change the `"built"` entry of `runs` to use `hostile_env` in place of `self.hostile_env()`. The existing assertions then prove that the built launcher under hostility derives the clean source bundle byte for byte (D8). Add one sentence to the class docstring: `The built derivation runs under every environment-only hostile record source (issue 255).`

- [ ] **Step 3: Write the full-shape case**

In `tests/test_review_retained_full.py`, add `from .hostile_git_test_support import hostile_git_env` beside the other support imports. Add this method to `RetainedFullTest`, directly after `test_committed_evidence_reproduces_with_the_reviewed_tool`:

```python
    def test_hostile_record_sources_reproduce_the_clean_bundle(self):
        """Issue 255 (D2, D8): a derivation from a disposable clone carrying every hostile record source a test
        can own writes the class bundle's five files. Its payload members, which carry no tool identity, equal
        the committed bundle's, so the clean-run bytes are unchanged on the real objects."""
        clone = self.disposable_clone()
        pair = ("diff", "--binary", "-U10", COMMITS[0], COMMITS[1])
        clean = subprocess.run(["git", "-C", str(clone), *pair], check=True, capture_output=True,
                               env=dict(self.env, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")).stdout
        env = hostile_git_env(Path(tempfile.mkdtemp(dir=self.tmp, prefix="hostile-")), self.env, [clone])
        hostile = subprocess.run(["git", "-C", str(clone), *pair], env=env, check=True, capture_output=True).stdout
        self.assertNotEqual(clean, hostile, "the hostile sources never bit")
        out = self.tmp / "hostile-bundle"
        done = subprocess.run([sys.executable, "-m", "agent_tools." + DERIVE.replace("-", "_"),
                               *derive_argv(self.root, self.tool_commit, issue_121_repo=clone,
                                            issue_100_repo=clone, output_dir=out)],
                              env=env, cwd=self.tmp, capture_output=True)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, self.summary, b""))
        files = {path.name: path.read_bytes() for path in out.iterdir()}
        self.assertEqual(files, {path.name: path.read_bytes() for path in self.bundle.iterdir()})
        for name in (ISSUE_100, ISSUE_121, ESTIMATE):
            self.assertEqual(files[name], (BUNDLE / name).read_bytes(), name)
```

The class bundle is the clean derivation of the same objects with the same tool commit, so no second clean run is made (D8). `watch_root` already compares the root before and after the case (RP11).

- [ ] **Step 4: Prove the installed case can fail**

The case is green on arrival, because Tasks 1–2 already isolate the runner and the recipe builds first. Prove that it fails without them: build once, then run the case from a scratch copy whose `python/` is the delivery base's (`31be729`), so its source half is the unisolated package. The scratch copy takes the working tree's `tests/` (the new case is not committed until Step 6), never `HEAD`'s.

```bash
timeout 3600 just build >/dev/null 2>&1 || exit 1
HMF=$(nix-store --query --requisites ./result | grep -- '-home-manager-files$')
tmp=$(mktemp -d "${TMPDIR:-/tmp}/issue-255-red-XXXXXX"); trap 'rm -rf -- "$tmp"' EXIT
cp -R tests "$tmp/" && git archive 31be729 python | tar -x -C "$tmp"
(cd "$tmp" && AGENT_SKILLS_INSTALLED_HOME="$HMF" timeout 900 python3 -m unittest \
  tests.test_agent_tools_launchers.AgentToolsLauncherTest.test_review_package_ignores_hostile_git_alike_from_source_and_built 2>&1 | tail -3)
```

Expected: `FAILED (failures=1)`, raised by `assertEqual(outcomes['hostile-source'], outcomes['clean-source'])`, never by the control. The same command from the worktree itself (`cd` to the worktree root instead of `$tmp`) → `OK`.

- [ ] **Step 5: Final gates**

Run each from the worktree root and check the observation. A skip is never acceptance.

Each gate keeps its producer's exit status and log, never a pipe's: `LOG=$(mktemp "${TMPDIR:-/tmp}/issue-255-gate-XXXXXX"); <command> > "$LOG" 2>&1; echo "exit=$?"; tail -3 "$LOG"`.

- `timeout 3600 just build` → `exit=0`.
- `timeout 7200 just agent-workflow-tests` → `exit=0`, the tail shows `OK`, and `grep -c skipped "$LOG"` prints `0`.
- `timeout 3600 just agent-installed-skill-tests` → `exit=0`, the tail shows `OK`, and `grep -E 'test_review_package_ignores_hostile_git_alike_from_source_and_built .*\.\.\. ok' "$LOG"` matches.
- Quiescent retained run (RP11): `timeout 14400 just agent-retained-tests /Users/anis/tmp/nix-config > "$LOG" 2>&1; echo "exit=$?"`, with `LOG` a `mktemp` file outside every worktree → `exit=0`; `grep -E 'test_hostile_record_sources_reproduce_the_clean_bundle|test_real_derivation_and_replay_match_from_source_and_built' "$LOG"` shows both `... ok`.
- `git diff --stat <plan base>..HEAD -- tests/fixtures/retained-review-evidence tests/retained_evidence_test_support.py` → empty (D2).

- [ ] **Step 6: Commit**

```bash
git add tests/test_agent_tools_launchers.py tests/test_review_retained_full.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-255-256-259 --worker-id <worker> -- \
  -m "test(review): prove isolation built and on real objects (#255)" -m "<session trailer lines>"
```
