# Task 2: workflow-state finds the installing ledger and serves its intent

Decisions: D2, D3, D4, D5, D7, D8, D11 (help text and the command docstring),
D13 (the lookup details the spec leaves open). Spec §1, §2 "Finding the
installing ledger", §4 "Refusal behaviour", §5 and "Test seams" 1–3. Work from
the worktree root. Every shell block starts with `set -euo pipefail`
(`set -uo pipefail` in the watch-it-fail step) and these abbreviations, which
the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (four new
  functions directly above `command_check_launch`; `command_check_launch` calls
  the extracted reader; `command_build_delivery`'s docstring and body; the
  `build-delivery` subparser description in `build_parser`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py`
  (`DeliveryLoopTest`: two new helpers and a `NOT_INSTALLED` constant, `deliver`
  gains a keyword, two new tests; `WorktreePolicyTest.test_help_states_the_contract_resolution_root`
  gains two clauses)

**Interfaces:**
- Consumes (Task 1): `DeliveryRuntime.requires_installed_intent(contract: object) -> bool`
  and `DeliveryRuntime.build_delivery(kind, value, *, policy, installed_intent=None)`.
  Task 1's builder raises `ValueError("<R>; no ledger under the repo root installs this contract")`
  when `installed_intent` is `None` for a contract that does not re-derive.
- Consumes (live): `resolve_repo_root`, `path_status`, `validate_state`, `_call`,
  `_delivery`, `RUN_ID_PATTERN`, `WorkflowError`, and the already-imported
  `copy`, `json`, `stat`, `Path`, `Any`, `Callable`.
- Produces: `read_state_unlocked(state_path: Path, run_id: str) -> dict[str, Any]`
  and `installed_initial_intent(runtime: Any, repo_root_value: str, contract: dict[str, Any]) -> dict[str, Any] | None`
  in workflow-state.py. In the tests: `DeliveryLoopTest.hand_built(built) -> (contract, intent)`,
  `DeliveryLoopTest.assert_not_installed(contract, intent) -> None`, and
  `DeliveryLoopTest.deliver(proposed, *, hand_built=False)`.

**Invariants:**
- The command consults ledgers only when the kind is not `contract`, the input is
  an object with a `contract` member, and `requires_installed_intent` is true
  (spec §1). A contract that re-derives never resolves `--repo-root` and reads
  no ledger, even beside an invalid one or under an absent root.
- `check-launch` behaves exactly as at base. Its lines move verbatim into
  `read_state_unlocked`, so it keeps its error texts and still returns the stored
  document for schemas 1–3 (D4, D13).
- The lookup takes no lock and writes nothing. It creates no `.superpowers/`,
  run directory, `.gitignore` or `state.lock`.
- The first raw match in sorted run-name order decides. A match that fails
  validation, or whose validated contract no longer carries the digest, refuses
  with `build-delivery refused: installing ledger <run-id> is invalid` (D4, D13).
- An absent `--repo-root` or one that is not a non-symlink directory refuses with
  `resolve_repo_root`'s own message, unprefixed (D13).
- Every refusal exits 2 with empty stdout and one stderr line.

- [ ] **Step 1: Write the failing tests**

In `T/test_delivery_workflow.py`, in `WorktreePolicyTest.test_help_states_the_contract_resolution_root`,
append two clauses to the `for clause in (...)` tuple. Its last line today is
`"document"):`; make it `"document",` and follow it with:

```python
                "It takes no lock, reads no clock and writes nothing.",
                "A contract the builder cannot re-derive is served only when a ledger under "
                "--repo-root has installed it, and then against that ledger's stored initial "
                "intent; that is the only time it reads a ledger."):
```

In `DeliveryLoopTest`, replace `deliver`'s signature, docstring and the start of
its body, from `self.project()` through the
`state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"`
line, with the block below, and insert `hand_built`, `NOT_INSTALLED` and
`assert_not_installed` directly above it. Everything from
`head, merge_sha = "a" * 40, "b" * 40` on stays, except one line.

```python
    def hand_built(self, built):
        """An adapter's pre-builder contract re-sealed from a built one (#193 D8).

        Its provenance kind is outside the builder's source kinds, and its PR
        stages declare the literal PR ref "5", which the builder never derives,
        so a served contract whose scopes were re-derived cannot finish the loop.
        """
        contract = copy.deepcopy(built["contract"])
        intent = copy.deepcopy(built["initial_intent"])
        contract["provenance"]["kind"] = "orchestrate-issues"
        intent["source"]["reference"] = "orchestrate-issues:orch-171"
        for scope in intent["scopes"]:
            if scope["action"] in {"open_pull_request", "merge_pull_request"}:
                scope["target"]["pr_ref"] = {"kind": "literal", "value": "5"}
                seal(self.model, scope)
        intent["scopes"].sort(key=lambda item: item["id"])
        seal(self.model, intent)
        contract["initial_authorization_intent_id"] = intent["id"]
        contract["initial_authorization_intent_digest"] = self.model.canonical_digest(intent)
        return contract, intent

    NOT_INSTALLED = (b"workflow-state: build-delivery refused: source kind of the contract "
                     b"cannot source an initial intent; no ledger under the repo root "
                     b"installs this contract\n")

    def assert_not_installed(self, contract, intent):
        """Every contract-taking kind refuses a contract no ledger installs (AC2)."""
        common = {"observed_at": NOW, "evidence": "e"}
        for kind, value in (
                ("initial-intent", {"contract": contract}),
                ("scope", {"contract": contract, "stage_id": "merge_pr"}),
                ("selected-output", {"contract": contract, "head": "a" * 40,
                    "tree": "c" * 40, "acceptance_ref": "spec", "review_ref": "clean",
                    "test_ref": "checks"}),
                ("observation", {"contract": contract, "observation_kind": "branch_published",
                    "source_kind": "repository", "source_reference": "probe",
                    "head": "a" * 40, **common}),
                ("authority-observation", {"contract": contract,
                    "scope_id": intent["scopes"][0]["id"], "launch_id": "171:1:1",
                    "authority_kind": "native_guard", "verdict": "allowed",
                    "reason_code": "guard_allowed", **common}),
                ("authorization-chain", {"contract": contract,
                                         "authorization_intents": [intent]})):
            with self.subTest(kind=kind):
                refused = self.build(kind, value, ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", self.NOT_INSTALLED))
        self.assertFalse(os.path.lexists(self.root / ".superpowers"))

    def deliver(self, proposed, *, hand_built=False):
        """Drive one implementation custody through every stage with builder outputs only.

        With `hand_built`, the installed contract is `hand_built`'s: it is
        refused before installation and when mutated, and served once installed.
        """
        self.project()
        built = self.build("contract", self.contract_input())
        contract, intent = (self.hand_built(built) if hand_built
                            else (built["contract"], built["initial_intent"]))
        self.contract = contract; self.digest = self.model.canonical_digest(self.contract)
        if hand_built:
            self.assert_not_installed(contract, intent)
        owner = self.acquire(self.contract, intent)
        self.custody = owner["custody"]
        self.run_args = ("--repo-root", self.root, "--run-id", owner["run_id"])
        state = self.root / f".superpowers/workflows/{owner['run_id']}/state.json"
        if hand_built:
            served = self.cli("build-delivery", "--repo-root", self.root, "--kind",
                              "initial-intent", "--input", "-",
                              stdin=json.dumps({"contract": contract}).encode()).stdout
            self.assertEqual(served, self.model.canonical_bytes(intent))
            stored = json.loads(state.read_text(encoding="utf-8"))["issues"]["171"]["delivery"]
            self.assertEqual(self.build("authorization-chain", {"contract": contract,
                "authorization_intents": [intent]})["authorization_chain_digest"],
                stored["authorization_chain_digest"])
            mutated = copy.deepcopy(contract)
            mutated["deliverable"]["summary"] += " (edited)"
            self.assertEqual(self.build("initial-intent", {"contract": mutated},
                                        ok=False).stderr, self.NOT_INSTALLED)
        policy = json.loads(POLICY.read_text(encoding="utf-8"))
        handed = self.validated("ship-handoff", self.handoff(owner, intent))
        # A real handoff outgrows the phase-report bound; that is why D28 moves it.
        self.assertGreater(len(handed), policy["phase_reports"]["wire_max_bytes"])
        self.assertLessEqual(len(handed), policy["workflow_responses"]["wire_max_bytes"])
```

The one other line in `deliver`: `if stage["id"] == "merge_pr":` becomes
`if stage["id"] == "merge_pr" and not hand_built:`. The second-PR refusal
depends on slot-bound PR numbers, so it stays on the builder source (spec
"Test seams" 1).

Insert these two tests directly above `test_evidence_kinds_are_exact_and_closed`:

```python
    def test_an_installed_hand_built_contract_completes_the_loop(self):
        self.deliver({"select_reviewed_output", "publish_branch", "open_pr", "merge_pr",
                      "close_tracker", "delete_remote_branch", "remove_worktree",
                      "delete_local_branch"}, hand_built=True)

    def test_only_a_contract_that_does_not_re_derive_reads_a_ledger(self):
        self.project()
        built = self.build("contract", self.contract_input())
        contract, _ = self.hand_built(built)
        workflows = self.root / ".superpowers" / "workflows"
        for run_id, raw in (
                ("a-unparsable", b"{"),
                ("run-derived", json.dumps({"schema_version": 4, "issues": {"171": {
                    "delivery": {"contract_digest": self.model.canonical_digest(
                        built["contract"])}}}}).encode()),
                ("run-legacy", json.dumps({"schema_version": 4, "issues": {"171": {
                    "delivery": {"contract_digest": self.model.canonical_digest(
                        contract)}}}}).encode())):
            (workflows / run_id).mkdir(parents=True)
            (workflows / run_id / "state.json").write_bytes(raw)
        refused = self.build("initial-intent", {"contract": contract}, ok=False)
        self.assertEqual((refused.returncode, refused.stdout, refused.stderr), (2, b"",
            b"workflow-state: build-delivery refused: installing ledger run-legacy is invalid\n"))
        self.assertEqual(self.build("initial-intent", {"contract": built["contract"]}),
                         built["initial_intent"])
        self.assertEqual([path.name for path in (workflows / "run-legacy").iterdir()],
                         ["state.json"])
        (self.root / ".superpowers").rename(self.root / "elsewhere")
        (self.root / ".superpowers").symlink_to(self.root / "elsewhere")
        self.assertEqual(self.build("initial-intent", {"contract": contract}, ok=False).stderr,
                         self.NOT_INSTALLED)
        absent = str(self.root / "absent")
        for value, expected in ((built["contract"], 0), (contract, 2)):
            completed = self.cli("build-delivery", "--repo-root", absent, "--kind",
                                 "initial-intent", "--input", "-",
                                 stdin=json.dumps({"contract": value}).encode(), ok=False)
            with self.subTest(derives=expected == 0):
                self.assertEqual(completed.returncode, expected)
        self.assertEqual(completed.stderr,
                         b"workflow-state: repository root does not exist\n")
```

The skipped `a-unparsable` run sorts first, so the refusal naming `run-legacy`
proves the skip rule. `run-derived` is invalid too, so the derived build beside
it proves the derivation path reads no ledger, and the absent root proves it
resolves none (D2, D8). The lone `state.json` proves the lookup took no lock,
and the symlinked `.superpowers` proves it is not followed (D4, D13).

- [ ] **Step 2: Run the tests and watch them fail**

```bash
set -uo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k DeliveryLoopTest -k test_help 2>&1 \
  | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: `Ran 6 tests` and `FAILED (failures=4)`: the loop test (its
post-install `initial-intent` exits 2 with the not-installed clause), the
ledger-read test (the not-installed line where `installing ledger run-legacy is
invalid` is expected), and both new help clauses. A planning probe saw exactly
this with Task 1 applied.

- [ ] **Step 3: Implement the lookup**

In `S/workflow-state.py`:

1. **Shared reader and lookup.** Insert these four functions directly above
   `command_check_launch`. The body of `read_state_unlocked` is the block that
   `command_check_launch` runs today from its `# No lock:` comment through its
   `validate_state` call, moved verbatim except for the two returns. The lookup
   is given in full because its skip, match and refusal order is D4 and D13:

```python
def read_state_unlocked(state_path: Path, run_id: str) -> dict[str, Any]:
    """Read one run's state and validate it without a lock or a write (#193 D4).

    check-launch and the build-delivery ledger lookup share this reader. No
    lock: `atomic_write_state` publishes by `os.replace`, so an unlocked reader
    sees either the whole prior file or the whole new one, never a torn one — and
    taking the lock would mean creating `state.lock`, which is a write. Schemas
    1–3 are migrated and validated on a detached copy; the document is returned
    as stored.
    """
    try:
        raw_state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise WorkflowError("invalid workflow state") from error
    if isinstance(raw_state, dict) and raw_state.get("schema_version") in {1, 2, 3}:
        candidate = _call("invalid legacy workflow state",
            _delivery().migrate, raw_state, migration_contracts={})
        validate_state(candidate, run_id=run_id)
        return raw_state
    return validate_state(raw_state, run_id=run_id)


def _stored_contract_digest(raw_state: object, issue: str) -> object:
    """The contract digest a raw, unvalidated state records for ``issue``, if any."""
    issues = raw_state.get("issues") if isinstance(raw_state, dict) else None
    entry = issues.get(issue) if isinstance(issues, dict) else None
    delivery = entry.get("delivery") if isinstance(entry, dict) else None
    return delivery.get("contract_digest") if isinstance(delivery, dict) else None


def _non_symlink(path: Path, kind: Callable[[int], bool]) -> bool:
    status = path_status(path)
    return status is not None and not stat.S_ISLNK(status.st_mode) and kind(status.st_mode)


def installed_initial_intent(runtime: Any, repo_root_value: str,
                             contract: dict[str, Any]) -> dict[str, Any] | None:
    """The root intent a ledger under the repo root installed with ``contract``, or None.

    Read-only like check-launch: no lock, no clock and no write (#193 D3, D4).
    Runs are scanned in sorted order. A run that is not a run-id-named
    non-symlink directory, or whose state file is absent, not a non-symlink
    regular file, unparsable, or records another contract digest for the issue,
    is skipped. The first match is re-read through ``read_state_unlocked``; a
    match that fails validation, or whose validated contract does not carry the
    digest, refuses naming its run.
    """
    repo_root = resolve_repo_root(repo_root_value)
    workflows = repo_root / ".superpowers" / "workflows"
    if not all(_non_symlink(path, stat.S_ISDIR) for path in (workflows.parent, workflows)):
        return None
    digest = runtime.model.canonical_digest(contract)
    issue = str(contract["issue"])
    for run_dir in sorted(workflows.iterdir(), key=lambda path: path.name):
        state_path = run_dir / "state.json"
        if (not RUN_ID_PATTERN.fullmatch(run_dir.name)
                or not _non_symlink(run_dir, stat.S_ISDIR)
                or not _non_symlink(state_path, stat.S_ISREG)):
            continue
        try:
            raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if _stored_contract_digest(raw_state, issue) != digest:
            continue
        invalid = f"build-delivery refused: installing ledger {run_dir.name} is invalid"
        try:
            state = read_state_unlocked(state_path, run_dir.name)
        except WorkflowError as error:
            raise WorkflowError(invalid) from error
        entry = state["issues"].get(issue)
        delivery = None if entry is None else entry["delivery"]
        if delivery is None or delivery["contract"] is None \
                or runtime.model.canonical_digest(delivery["contract"]) != digest:
            raise WorkflowError(invalid)
        return copy.deepcopy(next(item for item in delivery["authorization_intents"]
                                  if item["predecessor_intent_id"] is None))
    return None
```

   `ValueError` in the raw read covers both `json.JSONDecodeError` and
   `UnicodeDecodeError`. A validated delivery's chain has exactly one root, so
   `next` always finds it.

2. **`command_check_launch`.** Replace the moved block (the three `# No lock:`
   comment lines through the `else:` branch's `validate_state` call) with
   `state = read_state_unlocked(state_path, args.run_id)`. Leave its docstring
   and everything else as is.

3. **`command_build_delivery`.** Replace its one-line docstring with:

```python
    """Print one sealed delivery value; read-only (no lock, clock or write).

    A contract the builder cannot re-derive is served only against the initial
    intent a ledger under --repo-root installed with it, which
    ``installed_initial_intent`` finds; that is the only ledger read (#193 D2).
    """
```

   Directly after the `policy = ...` line, add:

```python
    installed = None
    if (args.kind != "contract" and isinstance(value, dict) and "contract" in value
            and runtime.requires_installed_intent(value["contract"])):
        installed = installed_initial_intent(runtime, args.repo_root, value["contract"])
```

   Then pass `installed_intent=installed` to the existing
   `runtime.build_delivery(args.kind, value, policy=policy)` call. The lookup
   stays outside that call's `try`, so its own refusals are not prefixed twice.

4. **Help.** In the `build-delivery` subparser description, replace the string
   `"It takes no lock, reads no ledger or clock and writes nothing. "` with
   these four literals, in order:

```python
        "It takes no lock, reads no clock and writes nothing. "
        "A contract the builder cannot re-derive is served only when a ledger under "
        "--repo-root has installed it, and then against that ledger's stored initial "
        "intent; that is the only time it reads a ledger. "
```

- [ ] **Step 4: Verify**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k check_launch 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if grep -qF 'reads no ledger or clock' $S/workflow-state.py; then exit 1; fi
if grep -qF 'no lock, ledger, clock or write' $S/workflow-state.py; then exit 1; fi
if grep -qF 'raw_state = json.loads' <(sed -n '/^def command_check_launch/,/^def /p' $S/workflow-state.py); then exit 1; fi
grep -c 'def read_state_unlocked\|def installed_initial_intent' $S/workflow-state.py
grep -c 'read_state_unlocked(state_path' $S/workflow-state.py
```

Expected: `test_delivery_workflow.py` gives `Ran 47 tests` and `OK` (45 at base
plus these 2), in about 90 seconds. The `check_launch` selection of
`test_workflow_state.py` gives `Ran 4 tests` and `OK`; those existing tests
guard the shared reader. The three prohibitions pass, and each would exit the
gate at base: the old help and docstring phrases are gone, and
`command_check_launch` no longer parses the file itself. Then `2`, the two
definitions, and `3`, the definition line plus the calls from
`command_check_launch` and the lookup. Summarize any failure to its test ids.

- [ ] **Step 5: Commit**

```bash
set -euo pipefail
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
git add $S/workflow-state.py $T/test_delivery_workflow.py
git commit -m "feat(workflow): serve a contract its ledger installed without re-deriving it" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_014t9cPhYQiiTKbbAn8vTEaq"
```
