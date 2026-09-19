# Task 4: Onboard the eval fixture and remove the legacy surface

**Files:**
- Delete: `.claude/skills.config.json`
- Modify: `CLAUDE.md`
- Modify: `home/common/agent-skills/default.nix`
- Delete: `home/common/agent-skills/scripts/resolve-bindings`
- Delete: `home/common/agent-skills/tests/test_resolve_bindings.py`
- Modify: `home/common/agent-skills/tests/test_resolve_project.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/evals/run-eval.sh`
- Modify: `home/common/agent-skills/evals/assert-lib.sh`
- Modify: `home/common/agent-skills/evals/README.md`
- Delete: `home/common/agent-skills/evals/fixture-repo/.claude/skills.config.json`
- Create: `home/common/agent-skills/evals/fixture-repo/.agents/project.json`
- Create: `home/common/agent-skills/evals/fixture-repo/.agents/instructions/bootstrap.md`
- Create: `home/common/agent-skills/evals/fixture-repo/AGENTS.md`
- Create: `home/common/agent-skills/evals/fixture-repo/CLAUDE.md`
- Modify: `home/common/claude-code/default.nix`
- Modify: `tests/test_claude_permission_guard.py`

**Interfaces:**
- Consumes: Task 2/3's phase-entry tables and assertion helper; resolver schema 1 and projection writer; D2/D4 living-surface scope.
- Produces: one strict eval-fixture project contract, a once-per-trial retained fixture snapshot, no legacy executable/config/test/install declaration, source zero-reference gate, and installed-surface descriptor for Task 6.

**Invariants:**
- The fixture contract is complete schema 1: project `fixture/tinytask`; Git/main with `issue-<num>-<slug>` and `.worktrees`/`worktree-`; tracker unsupported with kind `none`; artifact paths `.claude/specs` and `.claude/plans`; its existing context/standards/architecture paths; verification command argv `["python3","-m","unittest","discover"]`; orchestration 180 minutes / max 2; plan/code review, release, and deploy unsupported; deploy adapter `none`; current Claude/Codex projections.
- `run-eval.sh` resolves each fresh sandbox once after initialization, retains the JSON in one shell variable, and derives only snapshot fields with `jq`. Resolver refusal terminates the trial; no legacy config/default path exists.
- Source and installed descriptors name the same consumers. Installed shared files live under `~/.agents/skills`; installed Claude-only files live under `~/.claude/skills`. If either managed root exists, both and every expected consumer are mandatory (D4).
- Living-source checks enumerate tracked paths with `git ls-files -z`, skip entries deleted in the working tree, admit only explicit text suffixes/extensionless managed scripts, and cover managed source, evaluation harness/fixtures, installation declarations, root guidance, lifecycle-guard comments, and `scripts/context-map-lint.py`. They explicitly exclude historical `.claude/specs/**` and `.claude/plans/**`; ignored caches, binaries, generated build output, untracked files, and deleted paths are never opened as UTF-8. Separate assertions require every legacy path scheduled for deletion to be absent (D8).
- Parser symbols for the allowed literal `unset GITHUB_TOKEN` remain. Comments/tests describe the allowed names as coming from `bindings.tracker.credential_env.unset_before_invocation`; issue 116's parser architecture is unchanged.

- [ ] **Step 1: Add zero-reference and installed-matrix tests first**

Extend `ProjectPolicySurfaceTest` with the source scan and installed descriptor. Use the same `assert_policy_entries()` function for installed files.

```python
def test_living_source_has_no_legacy_policy_surface(self):
    tracked = subprocess.run(
        ["git", "ls-files", "-z", "--",
         "AGENTS.md", "CLAUDE.md", ".agents/instructions",
         "home/common/agent-skills", "home/common/claude-code",
         "scripts/context-map-lint.py", "tests"],
        cwd=REPO_ROOT, check=True, capture_output=True,
    ).stdout.split(b"\0")
    text_suffixes = {
        ".md", ".py", ".sh", ".nix", ".json", ".toml", ".yaml", ".yml",
    }
    historical_prefixes = (
        Path(".claude/specs"), Path(".claude/plans"),
    )
    legacy_names = (
        "resolve-" "bindings",
        ".claude/skills." "config.json",
        "unsetGithub" "Token",
    )
    legacy = re.compile("|".join(re.escape(name) for name in legacy_names))
    matches = []
    for encoded in tracked:
        if not encoded:
            continue
        relative = Path(os.fsdecode(encoded))
        if any(relative == prefix or prefix in relative.parents
               for prefix in historical_prefixes):
            continue
        path = REPO_ROOT / relative
        if not path.is_file():
            continue
        if path.suffix not in text_suffixes and path.name not in {
            "resolve-project", "context-map-lint", "artifact-budget",
            "agent-evidence", "agent-model-matrix", "diff-scope",
            "review-package", "sdd-workspace", "workflow-state",
        }:
            continue
        for line_number, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), 1):
            if legacy.search(line):
                matches.append(f"{relative}:{line_number}")
    self.assertEqual(matches, [])
    self.assertFalse((REPO_ROOT / ".claude" / ("skills." "config.json")).exists())
    self.assertFalse((REPO_ROOT /
        ("home/common/agent-skills/scripts/resolve-" "bindings")).exists())
    self.assertFalse((REPO_ROOT /
        ("home/common/agent-skills/tests/test_resolve_" "bindings.py")).exists())
    self.assertFalse((REPO_ROOT / "home/common/agent-skills/evals/fixture-repo" /
        ".claude" / ("skills." "config.json")).exists())

def test_installed_policy_surface_matches_source_contract(self):
    if os.environ.get("WORKFLOW_POLICY_SURFACE") == "source":
        self.skipTest("explicit pre-activation source-only verification")
    agents_root = Path.home() / ".agents/skills"
    claude_root = Path.home() / ".claude/skills"
    if not agents_root.exists() and not claude_root.exists():
        self.skipTest("managed skill roots are not installed on this host")
    self.assertTrue(agents_root.is_dir())
    self.assertTrue(claude_root.is_dir())
    assert_policy_entries(self, agents_root, SHARED_POLICY_ENTRIES)
    assert_policy_entries(
        self, claude_root, SHARED_POLICY_ENTRIES | CLAUDE_POLICY_ENTRIES)
    self.assertFalse((Path.home() /
        (".agents/bin/resolve-" "bindings")).exists())
    installed_linter = Path.home() / ".agents/bin/context-map-lint"
    self.assertTrue(installed_linter.is_file())
    installed_legacy = re.compile("|".join(re.escape(name) for name in (
        "resolve-" "bindings",
        ".claude/skills." "config.json",
        "unsetGithub" "Token",
    )))
    self.assertIsNone(installed_legacy.search(
        installed_linter.read_text(encoding="utf-8")))
```

Run before deletion: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest.test_living_source_has_no_legacy_policy_surface -v`

Expected: FAIL with living legacy paths. Do not run the installed test as a completion gate until Task 6 activates the generation; on this managed host it is expected to describe the old installation meanwhile. `WORKFLOW_POLICY_SURFACE=source` is the one explicit pre-activation skip and is never set by the ordinary suite.

- [ ] **Step 2: Onboard the eval fixture to schema 1**

Replace its config with `.agents/project.json` carrying every value in **Invariants**. Use exact empty arrays for absent context classes, exact null workflow review/release and deploy command fields, and all eleven capability declarations. Preserve the fixture's actual docs as paths: context is `docs/CONTEXT-MAP.md`, `docs/areas/backlog/CONTEXT.md`, `docs/areas/system/CONTEXT.md`; standards is `docs/standards`; architecture is `README.md`; hints/operations/rejections are empty. `worktrees`, context, standards, architecture, and verification are supported; every other capability is unsupported.

Create `.agents/instructions/bootstrap.md` with the fixture's strict resolver invariant and declare two projections: generated `AGENTS.md` id `codex.entry`, and the managed import in `CLAUDE.md` id `claude.entry`. From the fixture root run the repository resolver's `write-projections` subcommand once, then its `check-projections` subcommand.

Expected: both entries report current/in-sync; `resolve` returns absolute fixture paths, verification available when Python is on PATH, and authored unsupported states for tracker/review/release/deploy.

- [ ] **Step 3: Make each eval trial consume one snapshot**

In `run-eval.sh`, after initializing/committing the copied fixture and before optional setup, invoke `resolve-project resolve --repo-root "$REPO"` once. Nonzero is `die` with the untouched resolver stdout/stderr path. Retain successful stdout in one shell variable, validate its four top-level members with `jq -e`, and set `SPEC_DIR` / `PLAN_DIR` from `.bindings.paths.artifacts.specs` / `.plans`. Remove the two direct config `jq` reads. Update `assert-lib.sh` comments and `evals/README.md` to describe absolute snapshot-derived paths and the onboarded fixture.

Run: `bash -n home/common/agent-skills/evals/run-eval.sh home/common/agent-skills/evals/assert-lib.sh`

Expected: exit 0. `rg -n 'skills.config|specDir|planDir|resolve-bindings' home/common/agent-skills/evals` returns no living match.

- [ ] **Step 4: Delete the old implementation and align living comments**

Delete the root legacy config, helper, and dedicated tests. Remove `.agents/bin/resolve-bindings` from `default.nix`. Replace `CommittedContractTest.test_orchestration_values_match_the_legacy_config` with exact assertions against the resolved repository snapshot (`max_parallel == 2`, `attempt_budget_minutes == 180`) and assert the legacy root path is absent.

Update `CLAUDE.md`, `home/common/claude-code/default.nix`, and `tests/test_claude_permission_guard.py` so the existing allowed `unset GITHUB_TOKEN` grammar is explained as one concrete command derived from the resolved exhaustive credential-name list. Do not change parsing, accepted command grammar, protected repository maps, or any issue-116 architecture.

- [ ] **Step 5: Prove source parity and legacy absence**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest.test_living_source_has_no_legacy_policy_surface ProjectPolicySurfaceTest.test_shared_source_phase_entries_use_one_resolved_project ProjectPolicySurfaceTest.test_claude_source_phase_entries_use_one_resolved_project -v`

Expected: PASS. Missing expected consumers or legacy-path absence, any living legacy string, fallback instruction, extra resolver entry, attempted read of a deleted/untracked/binary path, or context-map-lint policy discovery fails.

Run: `python3 -m unittest discover -s home/common/agent-skills/tests -p 'test_resolve_project.py' -q`

Expected: PASS with no legacy test module present and the fixture contract/projections current.

Run: `python3 -m unittest tests.test_claude_permission_guard -q`

Expected: PASS; the guard behavior is unchanged.

- [ ] **Step 6: Commit**

```bash
git add .claude/skills.config.json CLAUDE.md home/common/agent-skills home/common/claude-code/default.nix tests/test_claude_permission_guard.py
git commit -S -m "refactor(workflows): remove legacy project bindings" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
