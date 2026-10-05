# Task 3: Built parity and reproduction from the retained objects

The committed copy replays alike from the built launcher and from source, and the reviewed tool derives the same five files again from the real objects (spec § *Tamper and incomplete copies* "Built cases", § *Reproduction from the retained objects*, § *Test seams*; EV3, EV4, EV10; CP18, CP19; RP8, RP10, RP11). No `python/` byte changes.

**Files:**
- Modify: `tests/retained_review_test_support.py` (`source_budget_env` gains an optional source root)
- Modify: `tests/test_review_retained_full.py` (one new case in `RetainedFullTest`)
- Modify: `tests/test_agent_tools_launchers.py` (one new case in `AgentToolsLauncherTest`)

**Interfaces:**
- Consumes (Task 1): `tests/retained_evidence_test_support.py` with `BUNDLE`, `ANCHOR_SHA256`, `TOOL_COMMIT`; it imports no `agent_tools`.
- Consumes (tier module today): `RetainedFullTest` with `cls.root`, `cls.tmp`, `disposable_clone(source=None)` (a fresh `git clone --shared --no-checkout`), `derive_argv(root, commit, **replaced)`, `DERIVE`, `SOURCE`, the hermetic `git(repo, *args)`, and `watch_root`, which every test's `setUp` already applies.
- Consumes (launcher module today): `AgentToolsLauncherTest.sealed_replay_pair(bundle, digest) -> [built, source]`, each `(exit, stdout, stderr)`; `self.hostile`, a per-test scratch directory; and the module function `canonical(value) -> bytes`.
- Produces: `source_budget_env(tmp, source=SOURCE) -> dict`; `RetainedFullTest.test_committed_evidence_reproduces_with_the_reviewed_tool`; `AgentToolsLauncherTest.test_committed_evidence_replays_alike_from_source_and_built`.

**Invariants:**
- The launcher module still imports no `agent_tools` at module level. Its new case builds every change with `json` and `hashlib` (CP18) and every replay run is the existing sealed pair (CP19).
- The reproduction case derives with the package, the budget helper and the policy of a disposable clone checked out at `TOOL_COMMIT`. It does not read `AGENT_RETAINED_TOOL_COMMIT` and does not use this checkout's `python/` (EV4). The class setup is unchanged and still applies its own selector, so the tier runs with that variable unset or naming a commit whose `python` tree is `HEAD`'s (EV14).
- `source_budget_env(tmp)` with one argument behaves exactly as today; every existing caller is unchanged.
- Nothing skips once `AGENT_RETAINED_ROOT` is set, and the root is compared around the new case like every other (RP10, RP11). A changed root voids the run: repeat it on a quiescent root, with no commit, fetch or gc in any worktree of the root meanwhile.
- No recipe changes (EV10). `RetainedLauncherTest` inherits the new launcher case, so the retained recipe runs it too.

- [ ] **Step 1: Write the reproduction case.** In `tests/test_review_retained_full.py`, add `from .retained_evidence_test_support import ANCHOR_SHA256, BUNDLE, TOOL_COMMIT` directly above the existing `from .retained_review_test_support import …` line, and add this case to `RetainedFullTest`, before `test_bundle_files_fit_the_whole_record_caps`:

```python
    def test_committed_evidence_reproduces_with_the_reviewed_tool(self):
        """Issue 235 (EV4): the reviewed tool derives the committed bundle again from the retained objects. The
        package, the budget helper and its policy come from a clone of this checkout at `TOOL_COMMIT`, not from
        the class's tool commit, so the case holds after this checkout's package moves on."""
        clone = self.disposable_clone(SOURCE)
        git(clone, "checkout", "-q", "--detach", TOOL_COMMIT)
        env = source_budget_env(tempfile.mkdtemp(dir=self.tmp, prefix="reviewed-"), clone)
        out = self.tmp / "reproduced"
        done = subprocess.run([sys.executable, "-m", "agent_tools." + DERIVE.replace("-", "_"),
                               *derive_argv(self.root, TOOL_COMMIT, tool_repo=clone, output_dir=out)],
                              env=env, cwd=self.tmp, capture_output=True)
        self.assertEqual((done.returncode, done.stderr), (0, b""))
        self.assertEqual(json.loads(done.stdout)["anchor_sha256"], ANCHOR_SHA256)
        self.assertEqual({path.name: path.read_bytes() for path in out.iterdir()},
                         {path.name: path.read_bytes() for path in BUNDLE.iterdir()})
```

  Name issue 235 and this case in the module docstring, in one sentence that says what the case does.

- [ ] **Step 2: Watch it fail.** On a quiescent root (about six minutes; the bound is thirty):

```bash
AGENT_RETAINED_ROOT=/Users/anis/tmp/nix-config PYTHONPATH=python timeout 1800 python3 -m unittest \
  tests.test_review_retained_full.RetainedFullTest.test_committed_evidence_reproduces_with_the_reviewed_tool 2>&1 | tail -4
```

  Expected: `TypeError`, because `source_budget_env` takes one positional argument.

- [ ] **Step 3: Give `source_budget_env` its source root.** In `tests/retained_review_test_support.py` the signature becomes `def source_budget_env(tmp, source=SOURCE) -> dict:`. The helper symlinks, the policy symlink, the `PATH` entry and `PYTHONPATH` are all taken under `Path(source)` instead of `SOURCE`. Rewrite the docstring's first sentence to say that the environment's `artifact-budget` and `agent_tools` are those of the source tree `source`, this checkout unless another is named. Repeat Step 2's command: it ends `Ran 1 test` and `OK`.

- [ ] **Step 4: Write the built case.** In `tests/test_agent_tools_launchers.py`, add `from .retained_evidence_test_support import ANCHOR_SHA256, BUNDLE` after the standard-library imports, with a blank line before it, and add this case to `AgentToolsLauncherTest`, before `test_replay_refuses_a_forged_bundle_alike_from_source_and_built`:

```python
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
```

  The order inside `malformed` matters: the witness row is refreshed before the anchor row that digests the witness.

- [ ] **Step 5: Verify.**

```bash
set -euo pipefail
LOG=$(mktemp "${TMPDIR:-/tmp}/ev235-installed-XXXXXX")
timeout 3600 just agent-installed-skill-tests > "$LOG" 2>&1 || { tail -20 "$LOG"; exit 1; }
grep -A1 '^test_committed_evidence_replays_alike_from_source_and_built ' "$LOG" | grep -q '\.\.\. ok$'
sed -i.bak 's/^ANCHOR_SHA256 = "sha256:d/ANCHOR_SHA256 = "sha256:e/' tests/retained_evidence_test_support.py
if timeout 3600 just agent-installed-skill-tests > "$LOG.mutant" 2>&1; then exit 1; fi
mv tests/retained_evidence_test_support.py.bak tests/retained_evidence_test_support.py
grep -q 'test_committed_evidence_replays_alike_from_source_and_built' "$LOG.mutant"
test -z "$(git status --porcelain -- tests/retained_evidence_test_support.py tests/fixtures)"
PYTHONPATH=python timeout 600 python3 -m unittest tests/test_review_evidence.py 2>&1 | tail -3
timeout 7200 just agent-workflow-tests 2>&1 | tail -3
test "$(git log --format=%H --no-merges 8971e41802fd2ee4de8d1c85626ea1cdcf2d384d..HEAD ^origin/main -- python | wc -l)" -eq 0
```

  The installed log must show the new case as `ok`: a skipped case is not acceptance (the class skips when the recipe's variable is unset, and that would pass silently). With one digit of the trusted digest changed the installed run must fail in the new case. Step 3's green reproduction run is part of this gate; quote its last four lines in the report. The whole retained tier runs at G3.

- [ ] **Step 6: Commit.** Stage only the three Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `test(review): built parity and reproduction of evidence (#235)`. A review-fix commit uses `fix(review): address Task-3 review findings (#235)`.

- [ ] **Step 7: G1 (controller).** Run the plan root's closure check and G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence` in a process-only commit, then renew G0 at `--completed-through 3`.

## Forecast basis

Estimates. A modify record is the U10 diff against `DELIVERY_BASE`. The edits above measured, at planning, 4,989 B / +43 for the launcher module, 4,713 B / +17 for the tier module and 2,469 B / +5 / −4 for the support module, and both new cases ran green there. With room for the docstring edits and review fixes: 7,168 B / +60 / −2, 6,656 B / +28 / −2 and 3,584 B / +8 / −6.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"d0dd665546c84f561a47218ebf7d7a96260b4d8b","head":"9b68dd396e6035c715abd347c1a5a11e5e4c87ab"}],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":8,"boundary":"evidence","deleted_lines":6,"record_bytes":3584,"support":{"covers":["t3-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-1","last_task":3,"owner":3,"path":"tests/retained_review_test_support.py"},{"bounds":[{"added_lines":28,"boundary":"evidence","deleted_lines":2,"record_bytes":6656,"support":{"covers":["t3-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-2","last_task":3,"owner":3,"path":"tests/test_review_retained_full.py"},{"bounds":[{"added_lines":60,"boundary":"evidence","deleted_lines":2,"record_bytes":7168,"support":{"covers":["t3-3"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-3","last_task":3,"owner":3,"path":"tests/test_agent_tools_launchers.py"}]}}
```
