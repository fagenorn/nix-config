# Task 4: `release transaction` command, README, P1 feasibility

**Files:**
- Modify: `python/agent_tools/release.py`
- Modify: `tests/test_release_command.py`
- Modify: `python/README.md`

**Interfaces:**
- Consumes:
  - Task 2's `release_driver.Project`, `Driver(project, profile_id=…)`, `Refusal`
    (`.as_object()`), `main_checkout(root)` and `require_cwd(root, cwd)`.
  - Task 3's `Driver.run(candidate, confirmations)` and `Driver.abandon()`.
  - `resolve_project.resolve(repo_root, ["release"])`, `load_contract(root)`,
    `add_repo_root(parser)` and `emit_json(value)`. `emit_json` always returns 0.
  - Task 1's `ForgeWorld.verification_ready`.
- Produces the CLI surface below, which Task 7's skill examples must parse:

```text
release transaction status  [--profile P] [--repo-root R]
release transaction preview [--profile P] [--commit C --version V --title T --notes-file F] [--repo-root R]
release transaction run     [--profile P] [--commit C --version V --title T --notes-file F] [--confirm TOKEN]... [--repo-root R]
release transaction abandon [--profile P] [--repo-root R]
```

**Invariants** (§1, §4, §5, §7, D3, D18, D19):
- `command_transaction(args)` does, in order:
  1. `snapshot = resolve(args.repo_root, ["release"])`. A refusal reaches stdout through
     the existing `ContractError` handler, exit 2, byte for byte as
     `python -m agent_tools.resolve_project resolve --require release` prints it
     (divergence 4).
  2. `root = Path(snapshot["project"]["root"])` and `common = main_checkout(root)`.
  3. For `run` and `abandon` only, `require_cwd(root, Path.cwd())`.
  4. `Project(project_id=snapshot["project"]["id"], root=root, common_dir=common,
     integration_branch=vcs["integration_branch"], default_branch=vcs["default_branch"],
     deploy_adapter=snapshot["bindings"]["deploy"]["adapter"],
     contract=load_contract(root))`, where `vcs` is `snapshot["bindings"]["vcs"]`.
  5. `Driver(project, profile_id=args.profile)`.
- **Candidate** (`preview` and `run`):
  - When all four of `--commit`, `--version`, `--title` and `--notes-file` are absent, it is
    `None`.
  - When some are absent, it refuses `candidate_required`, naming the missing flags.
  - Otherwise the notes file is read as UTF-8. An `OSError` or `UnicodeDecodeError`
    refuses `candidate_invalid`.
  - The candidate is `{"version", "commit", "title", "notes"}`.
- **Exits:**
  - `status`, `run` and `abandon` print their document and exit 0.
  - `preview` prints its document and exits 0 when `runnable`, else 3.
  - A `Refusal` prints `{"error": refusal.as_object()}` and exits 3.
  - Every other failure keeps `main`'s existing exit-2 envelope.
- `--confirm` is `action="append"` with default `[]`. `build_parser`'s description and the
  module docstring both say that adapter `invoke` is reachable only through
  `release transaction run`, which drives the core (§9). The old "No adapter `invoke` is
  reachable from any command" sentence is gone from the docstring.

- [ ] **Step 1: Write the failing command tests**

In `tests/test_release_command.py`:
- Give `run_release` a keyword `cwd=None`, passed to `subprocess.run`.
- Add `CANONICAL` and `ROWS` to the existing `.forge_world` import if absent.
- Add:

```python
class TransactionCommandTest(ReleaseCommandCase):
    """`release transaction` against nix-config's own profile (#128 spec §1, §4–§7)."""

    def setUp(self):
        super().setUp()
        self.world = ForgeWorld(self)
        self.world.verification_ready()
        notes = tempfile.TemporaryDirectory()
        self.addCleanup(notes.cleanup)
        self.notes = Path(notes.name) / "notes.md"
        self.notes.write_text("notes body\n", encoding="utf-8")

    def candidate(self):
        return ["--commit", CANONICAL["commit"], "--version", CANONICAL["tag"],
                "--title", CANONICAL["title"], "--notes-file", str(self.notes)]

    def store_exists(self):
        return (self.root / ".git/agent-release").exists()

    def preview(self):
        code, document, err = self.run_release("transaction", "preview", *self.candidate())
        self.assertEqual(code, 0, err)
        return document

    def run_with(self, tokens):
        confirms = [part for token in tokens for part in ("--confirm", token)]
        return self.run_release("transaction", "run", *self.candidate(), *confirms, cwd=self.root)

    def test_preview_names_tag_and_release(self):
        document = self.preview()
        self.assertEqual([c["action"] for c in document["confirmations"]], ["tag", "github-release"])
        self.assertEqual({c["version"] for c in document["confirmations"]}, {CANONICAL["tag"]})
        self.assertFalse(self.store_exists())

    def test_run_without_every_current_token_writes_nothing(self):
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        for code, supplied in (("confirmation_required", []),
                               ("confirmation_required", tokens[:1]),
                               ("confirmation_stale", ["tag:000000000000", tokens[1]])):
            with self.subTest(supplied=supplied):
                exit_code, document, err = self.run_with(supplied)
                self.assertEqual((exit_code, document["error"]["code"]), (3, code), err)
        self.assertFalse(self.store_exists())

    def test_status_shows_a_nonterminal_release(self):
        self.world.invoke_ready(guard_exit=1)
        self.world.not_found("gh", ROWS["tag.ref"]["argv"][1:])
        self.world.not_found("gh", ROWS["release.view"]["argv"][1:])
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        exit_code, result, err = self.run_with(tokens)
        self.assertEqual((exit_code, result["next"]), (0, "attention"), err)
        code, status, err = self.run_release("transaction", "status")
        self.assertEqual(code, 0, err)
        release = status["release"]
        self.assertEqual((release["state"], release["terminal"]), ("attention_required", None))
        self.assertEqual([(a["name"], a["status"], a["attempts"]) for a in release["actions"]],
                         [("tag", "absent", 1), ("github-release", None, 0)])
        self.assertEqual(sorted(g["grant_id"] for g in release["grants"]), sorted(tokens))

    def test_a_release_already_on_the_forge_runs_to_done(self):
        self.world.canonical()
        tokens = [c["token"] for c in self.preview()["confirmations"]]
        exit_code, result, err = self.run_with(tokens)
        self.assertEqual((exit_code, result["state"], result["next"]), (0, "succeeded", "done"), err)
        code, status, err = self.run_release("transaction", "status")
        self.assertIsNotNone(status["release"]["receipt"])
        self.assertFalse(any(c["argv"][:2] == ["release", "create"] for c in self.world.calls()))

    def test_typed_refusals(self):
        code, document, _ = self.run_release("transaction", "preview", "--commit", "1" * 40)
        self.assertEqual((code, document["error"]["code"]), (3, "candidate_required"))
        code, document, _ = self.run_release("transaction", "abandon", cwd=self.world.checkout)
        self.assertEqual((code, document["error"]["code"]), (3, "cwd_mismatch"))

    def test_an_unadopted_repository_gets_the_resolver_refusal_byte_for_byte(self):
        bare = self.root.parent / "bare"
        (bare / ".git").mkdir(parents=True)
        env = dict(os.environ, PYTHONPATH=str(PYTHON), HOME=str(self.home))
        def raw(*argv):
            return subprocess.run([sys.executable, "-m", *argv, "--repo-root", str(bare)],
                                  capture_output=True, env=env, timeout=120)
        ours = raw("agent_tools.release", "transaction", "status")
        theirs = raw("agent_tools.resolve_project", "resolve", "--require", "release")
        self.assertEqual((ours.returncode, ours.stdout), (2, theirs.stdout))
        self.assertEqual(theirs.returncode, 2)
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_command.py 2>&1 | tail -4`
Expected: FAIL. argparse rejects `transaction` with exit 2 and empty stdout, so
`json.loads` raises in `run_release`. The existing classes still pass.

- [ ] **Step 3: Implement the area and update the docs**

`release.py`: add `command_transaction` to the Invariants, the `transaction` subparsers
and the `Refusal` handler in `main`, which comes before the `ContractError` handler.

`python/README.md`:
- In `## Release profiles`, replace "No adapter `invoke` is reachable from any command; it
  is reachable only through the transaction core." with "Adapter `invoke` is reachable
  only through `release transaction run`, which drives the transaction core."
- Add `## Release driver` after `## Release adapters`. Write it from the implemented code,
  covering:
  - the four subcommands and their arguments;
  - the resolve step and the gates: `not_main_checkout`, `cwd_mismatch` for `run` and
    `abandon`, `merge_not_declared`, `deploy_watch_unowned` and `anchors_unsupported`;
  - selection;
  - the store root, mode and creation key, and the version reservation with the
    `abandoned` exception;
  - the verification reads and receipt;
  - `plan_digest` and the token formula;
  - the run pass and its `next` values;
  - `abandon`;
  - `status`'s members;
  - the refusal envelope and exits;
  - one closing line naming the legacy gate as Task 6's addition. Task 6 replaces that line.

  Keep each fact once and cite spec §n and Dn rather than restating rationale.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.suite_runner tests/test_release_command.py tests/test_release_driver.py tests/test_release_verification.py 2>&1 | tail -4`
Expected: `summary members=3 passed=3 failed=0`.

Run: `just build` in the foreground with a timeout of at least 30 minutes. The package's
`pythonImportsCheck` now imports the three new modules.
Expected: exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/release.py tests/test_release_command.py python/README.md
git commit -m "feat(issue-128/T4): release transaction command"
```

- [ ] **Step 6: P1 feasibility (P1 = Tasks 1–4, D23)**

```bash
set -euo pipefail
BASE="$(git log --reverse --format=%H -F --grep='feat(issue-128/T1):' | head -1)"
test -n "$BASE"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/rp-XXXXXX")/review.json"
review-package .agents/artifacts/plans/2026-11-02-issue-128-ship-release-release-core.md \
  "$(git rev-parse "$BASE^")" "$(git rev-parse HEAD)" "$OUT" > "$OUT.report"
grep -q '"state":"complete"' "$OUT.report"
```

Expected: exit 0. A `decompose_required` report names a member diff over the limit. Split
that file, re-run Step 4, and commit before continuing. This step has nothing to commit.
