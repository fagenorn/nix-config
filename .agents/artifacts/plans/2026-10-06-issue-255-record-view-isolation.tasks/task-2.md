# Task 2: Issue-100 recipe through the runner, portable derivation and RP24 lift

**Files:**
- Modify: `python/agent_tools/review_issue100.py` (`_recipe`)
- Modify: `python/agent_tools/review_derivation.py` (module docstring's determinism paragraph)
- Test: `tests/test_review_derivation.py`

**Interfaces:**
- Consumes: `review_actual.record_git(repo: Path, *args: str) -> bytes` and `GenerationError` (Task 1); `tests.hostile_git_test_support.hostile_git_env(owned, base, repos=()) -> dict[str, str]` (Task 1); `DerivationTest.inputs`, `.pins`, `.derive(out, inputs=None, **changed)`, `.shared()`.
- Produces: no new name. `_recipe(repo, pins, old_tree, new_tree, *paths) -> bytes` keeps its signature and its error, `Issue100Error("evidence_unavailable")`.

**Invariants:**
- The recipe argv after `git` is unchanged: `*pins.recipe, old_tree, new_tree`, then `--` and the paths when there are any. Pins, domains and their digests do not move (D2, D4).
- Under every hostile source a test can own, copies of the class repositories derive the five files of the clean bundle byte for byte, the anchor and `issue-121.json` among them.
- `review_issue100.py` imports no `subprocess` once it has no use for it.

- [ ] **Step 1: Write the failing test**

In `tests/test_review_derivation.py`, add `from agent_tools.review_actual import RECORD_POLICY` beside the other `agent_tools` imports and `from .hostile_git_test_support import hostile_git_env` above the `retained_review_test_support` import. Add this case to `DerivationTest`, directly after `test_two_derivations_are_byte_identical_and_inputs_unchanged`:

```python
    def test_hostile_record_sources_leave_the_bundle_unchanged(self):
        """Issue 255: copies of the class repositories under every record-shaping source a test can own derive
        the clean bundle byte for byte. The control: raw Git renders the issue-121 range differently there."""
        owned = Path(tempfile.mkdtemp(dir=self.tmp, prefix="hostile-"))
        i = self.inputs
        repos = [Path(shutil.copytree(repo, owned / name, symlinks=True)) for name, repo in
                 (("121", i.issue_121_repo), ("100", i.issue_100_repo), ("tool", i.tool_repo))]
        (owned / "home").mkdir()
        env = hostile_git_env(owned, dict(os.environ, HOME=str(owned / "home")), repos)
        clean = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        policy = (*RECORD_POLICY["git_config"], "diff", *RECORD_POLICY["diff_args"], "--binary", "-U10",
                  self.pins[1].base, "HEAD")
        control = [subprocess.run(["git", "-C", str(repo), *policy], env=e, check=True, capture_output=True).stdout
                   for repo, e in ((i.issue_121_repo, clean), (repos[0], env))]
        self.assertNotEqual(control[0], control[1], "the hostile sources never bit")
        hostile = owned / "bundle"
        with patch.dict(os.environ, env, clear=True):
            self.derive(hostile, replace(i, issue_121_repo=repos[0], issue_100_repo=repos[1], tool_repo=repos[2]))
        self.assertEqual({p.name: p.read_bytes() for p in hostile.iterdir()},
                         {p.name: p.read_bytes() for p in self.shared()[0].iterdir()})
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python timeout 1200 python3 -m unittest tests.test_review_derivation.DerivationTest.test_hostile_record_sources_leave_the_bundle_unchanged 2>&1 | grep -E 'Error|FAILED|OK'`
Expected: `agent_tools.review_issue100.Issue100Error: domain_mismatch`, then `FAILED (errors=1)`. Task 1 isolated CORE's records, but issue 100's recipe still renders in the hostile source, so its domain digest no longer matches the pin.

- [ ] **Step 3: Route the recipe**

In `review_issue100._recipe`, call `record_git(repo, *pins.recipe, old_tree, new_tree, *(("--", *paths) if paths else ()))` and map `GenerationError` to `Issue100Error("evidence_unavailable")`, the code a failed `subprocess.run` produced before (D4). Import `record_git` from `agent_tools.review_actual` in the existing import list, which already names `GenerationError`. Delete `import subprocess` when nothing else in the module uses it (`grep -n 'subprocess' python/agent_tools/review_issue100.py` prints nothing afterwards).

- [ ] **Step 4: Lift RP24 in the living statement**

In `python/agent_tools/review_derivation.py`'s module docstring, replace the paragraph that begins `Every output byte is` with this text. Keep the first and last paragraphs unchanged.

```text
Every output byte is `canonical_bytes` of a value the pins, the repositories,
the archive and the budget authority determine: no path, clock, hostname,
locale or environment value is written. Every Git call that renders a record,
a commit subject or the issue-100 recipe runs in `review_actual.record_git`'s
isolated view, so no attribute or configuration source of the host or of the
repositories reaches it (issue 255, which lifts RP24's narrowing). Two
derivations of the same pins are therefore byte-identical on any host and any
repository configuration, for one Git version.
```

Do not edit the REPLAY or EVIDENCE specs (D5).

- [ ] **Step 5: Verify**

- The Step 2 command → `OK`.
- `PYTHONPATH=python timeout 1800 python3 -m unittest tests.test_review_issue100 tests.test_review_compact100 tests.test_review_derivation tests.test_review_replay tests.test_review_evidence 2>&1 | tail -3` → `OK`.
- `grep -c 'record_git' python/agent_tools/review_issue100.py` → at least 2 (import and call); at the start commit it is 0.
- `grep -c 'issue 255' python/agent_tools/review_derivation.py` → 1; at the start commit it is 0.
- `git diff --stat <start>..HEAD -- tests/fixtures/retained-review-evidence .agents/artifacts/specs/2026-10-04-issue-249-retained-derivation-replay-design.md .agents/artifacts/specs/2026-10-05-issue-235-retained-review-evidence-design.md` → empty.

- [ ] **Step 6: Commit**

```bash
git add python/agent_tools/review_issue100.py python/agent_tools/review_derivation.py tests/test_review_derivation.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-255-256-259 --worker-id <worker> -- \
  -m "feat(review): isolate the issue-100 recipe and lift RP24 (#255)" -m "<session trailer lines>"
```
