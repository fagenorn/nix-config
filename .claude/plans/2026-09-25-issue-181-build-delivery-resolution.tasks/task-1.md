# Task 1: Relay resolver refusals and label every resolver outcome

Decisions: D1, D2, D8, D9 (the `unsupported_schema` case). Spec §1 "Resolver
outcome handling". Work from the worktree root. Every shell block starts with
`set -euo pipefail` (`set -uo pipefail` in a
watch-it-fail step) and these abbreviations, which the blocks below omit:

```bash
S=home/common/agent-skills/scripts; T=home/common/agent-skills/tests
```

**Files:**
- Modify: `home/common/agent-skills/scripts/workflow-state.py` (`resolve_project_policy`
  and its new helpers, about line 3110, plus the one call in `command_build_delivery`)
- Test: `home/common/agent-skills/tests/test_delivery_workflow.py` (the import line,
  one `BuilderHarness` method and one `DeliveryBuilderTest` method)
- Test: `home/common/agent-skills/tests/test_workflow_state.py` (one new class)

**Interfaces:**
- Consumes: the existing `resolve_project_argv() -> list[str]`, `WorkflowError`,
  and the existing `main`, which prints `workflow-state: <message>` to stderr and
  returns 2 for any `WorkflowError`.
- Produces (workflow-state.py):
  - `resolver_refusal(stdout: bytes) -> dict[str, Any] | None`, the structural
    refusal check.
  - `resolver_json(value: object) -> str`, which gives sorted, compact,
    ASCII-escaped JSON with `allow_nan=False`. That is the resolver's own
    `emit_json` form without its newline.
  - `classify_resolver_outcome(completed: subprocess.CompletedProcess, label: str) -> dict[str, Any]`.
  - `resolve_project_policy(root: str, label: str) -> dict[str, Any]`. `label`
    is the literal `"repo-root"` or `"worktree"`. Task 3 calls it with
    `"worktree"`.
- Produces (tests): `BuilderHarness.resolver_refusal_line(root, label) -> bytes`,
  the builder's exact expected stderr for a resolver refusal at `root`. Task 3
  reuses it.

**Invariants:**
- A resolver exit 2 whose stdout is a well-formed refusal gives exactly one
  stderr line, `workflow-state: resolve-project refused at <label>: <document>\n`.
  `<document>` is byte-identical to the resolver's stdout minus its trailing
  newline. Stdout stays empty and the exit code is 2.
- Well-formed means exactly one top-level member, `error`. Its members are
  exactly `code`, `repair_id` and `violations`, plus an optional `reason_code`.
  `code`, `repair_id` and `reason_code` are strings. `violations` is a list of
  objects with exactly `pointer` and `message`, both strings. The check never
  restates the code set or the `reason_code` position (D1).
- Every other outcome gives `resolve-project failed at <label>: {"exit":<int>,"stderr":"<text>","stdout":"<text>"}`.
  That covers every non-zero exit except exit 2 with a well-formed refusal, and
  every exit 0 whose stdout is not one JSON object. The JSON is
  `resolver_json({"exit", "stderr", "stdout"})`, and each stream is decoded as
  UTF-8 with `errors="replace"`. A timeout gives
  `resolve-project timed out at <label>` (D2).
- An exit 0 with a JSON object returns that object unchanged.
- The argv, `capture_output=True`, `check=False` and `timeout=60` stay as they are.

- [ ] **Step 1: Write the failing tests**

In `T/test_delivery_workflow.py`, change the import line
`from .test_resolve_project import make_home, make_project_root, source_contract`
to:

```python
from .test_resolve_project import make_home, make_project_root, run as run_resolver, source_contract
```

In `class BuilderHarness`, add this method directly after `build`:

```python
    def resolver_refusal_line(self, root, label):
        """The builder's exact stderr when the resolver refuses at `root` (D1, D8).

        The resolver runs directly on the same root and HOME, so the expected
        bytes are the resolver's own stdout, never a literal.
        """
        code, stdout, stderr = run_resolver("resolve", "--repo-root", str(root),
                                            home=self.home)
        self.assertEqual(code, 2, stderr)
        return (f"workflow-state: resolve-project refused at {label}: "
                + stdout.removesuffix("\n") + "\n").encode()
```

In `class DeliveryBuilderTest`, add this method directly after
`test_contract_refusals_exit_two_with_empty_stdout`:

```python
    def test_resolver_refusal_relays_the_resolver_document_exactly(self):
        def two_violations(contract_value):
            del contract_value["bindings"]["tracker"]["repo_slug"]
            contract_value["bindings"]["vcs"]["merge"]["delete_branch"] = "yes"

        def future_schema(contract_value):
            contract_value["schema_version"] = 2

        prefix = b"workflow-state: resolve-project refused at repo-root: "
        for label, mutate, code, pointers in (
                ("two ordered violations", two_violations, "invalid_contract",
                 ["/bindings/tracker/repo_slug", "/bindings/vcs/merge/delete_branch"]),
                ("reason code", future_schema, "unsupported_schema", ["/schema_version"])):
            with self.subTest(label=label):
                self.project(mutate)
                expected = self.resolver_refusal_line(self.root, "repo-root")
                refused = self.build("contract", self.contract_input(), ok=False)
                self.assertEqual((refused.returncode, refused.stdout, refused.stderr),
                                 (2, b"", expected))
                error = json.loads(refused.stderr.removeprefix(prefix))["error"]
                self.assertEqual(
                    (error["code"], [item["pointer"] for item in error["violations"]],
                     "reason_code" in error),
                    (code, pointers, code == "unsupported_schema"))
```

In `T/test_workflow_state.py`, add this class directly before
`class ArtifactBudgetPolicyResolutionTest`:

```python
class ResolverOutcomeTest(unittest.TestCase):
    """D2: resolver outcomes no real resolver produces are failures, never refusals."""

    @classmethod
    def setUpClass(cls):
        cls.workflow = load_source_module(SCRIPT, "workflow_state_resolver_outcome")

    def message(self, returncode, stdout, stderr):
        completed = subprocess.CompletedProcess(
            ["resolve-project", "resolve"], returncode, stdout, stderr)
        with self.assertRaises(self.workflow.WorkflowError) as caught:
            self.workflow.classify_resolver_outcome(completed, "worktree")
        return str(caught.exception)

    def test_non_conforming_outcomes_are_failures_carrying_the_resolver_body(self):
        refusal = (b'{"error":{"code":"not_onboarded","repair_id":"r",'
                   b'"violations":[{"message":"m","pointer":""}]}}\n')
        cases = (
            ("non-JSON stdout on exit 1", 1, b"Traceback: boom\n", b"stack\n",
             r'{"exit":1,"stderr":"stack\n","stdout":"Traceback: boom\n"}'),
            ("a non-object on exit 0", 0, b"[1, 2]\n", b"",
             r'{"exit":0,"stderr":"","stdout":"[1, 2]\n"}'),
            ("a refusal missing members", 2, b'{"error":{"code":"invalid_contract"}}\n', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"invalid_contract\"}}\n"}'),
            ("an unknown error member", 2,
             b'{"error":{"code":"c","hint":"h","repair_id":"r","violations":[]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"hint\":\"h\",'
             r'\"repair_id\":\"r\",\"violations\":[]}}"}'),
            ("a violation missing its message", 2,
             b'{"error":{"code":"c","repair_id":"r","violations":[{"pointer":"/a"}]}}', b"",
             r'{"exit":2,"stderr":"","stdout":"{\"error\":{\"code\":\"c\",\"repair_id\":\"r\",'
             r'\"violations\":[{\"pointer\":\"/a\"}]}}"}'),
            ("a well-formed refusal on exit 1", 1, refusal, b"",
             r'{"exit":1,"stderr":"","stdout":"{\"error\":{\"code\":\"not_onboarded\",'
             r'\"repair_id\":\"r\",\"violations\":[{\"message\":\"m\",\"pointer\":\"\"}]}}\n"}'),
            ("undecodable bytes", 1, b"\xff\n", b"\xfe",
             r'{"exit":1,"stderr":"\ufffd","stdout":"\ufffd\n"}'),
        )
        for label, returncode, stdout, stderr, body in cases:
            with self.subTest(label=label):
                self.assertEqual(self.message(returncode, stdout, stderr),
                                 "resolve-project failed at worktree: " + body)

    def test_a_timeout_is_reported_as_a_timeout_at_its_label(self):
        expired = subprocess.TimeoutExpired(["resolve-project", "resolve"], 60)
        with mock.patch.object(self.workflow.subprocess, "run", side_effect=expired):
            with self.assertRaises(self.workflow.WorkflowError) as caught:
                self.workflow.resolve_project_policy("/nonexistent/ledger", "repo-root")
        self.assertEqual(str(caught.exception), "resolve-project timed out at repo-root")
```

Adjacent raw-string literals concatenate, so each `body` is one JSON object.
`\n`, `\"` and `\ufffd` in a raw string are the escape sequences `json.dumps`
emits.

- [ ] **Step 2: Run the tests and watch them fail**

```bash
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k test_resolver_refusal_relays 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k ResolverOutcomeTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
```

Expected: the first run is `FAILED`, because stderr is
`workflow-state: resolve-project refused: invalid_contract`. The second run is
`FAILED` with errors for both tests, because `classify_resolver_outcome` does
not exist and the timeout message has no label.

- [ ] **Step 3: Implement the classifier**

Replace `resolve_project_policy` in `S/workflow-state.py` with the following.
The code is exact because it fixes the wire format: the refusal line's document
must reproduce the resolver's `emit_json` settings byte for byte.

```python
RESOLVER_REFUSAL_MEMBERS = frozenset({"code", "repair_id", "violations"})


def resolver_refusal(stdout: bytes) -> dict[str, Any] | None:
    """The resolver's refusal document when ``stdout`` is one, else None.

    Structure only (D1): the resolver's ``emit_error`` owns which codes exist
    and where ``reason_code`` may appear, so neither is checked again here.
    """
    try:
        document = json.loads(stdout)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(document, dict) or set(document) != {"error"}:
        return None
    error = document["error"]
    if not isinstance(error, dict) or set(error) - {"reason_code"} != RESOLVER_REFUSAL_MEMBERS:
        return None
    texts = (error["code"], error["repair_id"], error.get("reason_code", ""))
    if not all(isinstance(text, str) for text in texts) \
            or not isinstance(error["violations"], list):
        return None
    for item in error["violations"]:
        if not isinstance(item, dict) or set(item) != {"pointer", "message"} \
                or not all(isinstance(item[name], str) for name in ("pointer", "message")):
            return None
    return document


def resolver_json(value: object) -> str:
    """Sorted, compact, ASCII-escaped JSON: the resolver's emitted form, one line."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def classify_resolver_outcome(completed: subprocess.CompletedProcess,
                              label: str) -> dict[str, Any]:
    """Return the snapshot, or raise the labelled refused or failed line (D1, D2)."""
    if completed.returncode == 0:
        try:
            snapshot = json.loads(completed.stdout)
        except (UnicodeDecodeError, json.JSONDecodeError):
            snapshot = None
        if isinstance(snapshot, dict):
            return snapshot
    elif completed.returncode == 2:
        document = resolver_refusal(completed.stdout)
        if document is not None:
            raise WorkflowError(f"resolve-project refused at {label}: {resolver_json(document)}")
    body = {"exit": completed.returncode,
            "stderr": completed.stderr.decode("utf-8", errors="replace"),
            "stdout": completed.stdout.decode("utf-8", errors="replace")}
    raise WorkflowError(f"resolve-project failed at {label}: {resolver_json(body)}")


def resolve_project_policy(root: str, label: str) -> dict[str, Any]:
    """Run ``resolve-project resolve`` at ``root``; every other outcome is a refusal."""
    try:
        completed = subprocess.run(
            [*resolve_project_argv(), "resolve", "--repo-root", root],
            capture_output=True, check=False, timeout=60)
    except subprocess.TimeoutExpired as error:
        raise WorkflowError(f"resolve-project timed out at {label}") from error
    return classify_resolver_outcome(completed, label)
```

In `command_build_delivery`, change the call to
`resolve_project_policy(args.repo_root, "repo-root")`. Change nothing else in
that function. Task 3 owns the worktree call.

- [ ] **Step 4: Verify**

```bash
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py -k DeliveryBuilderTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_workflow_state.py -k ResolverOutcomeTest 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
PYTHONPATH=python python3 -m unittest $T/test_delivery_workflow.py 2>&1 | grep -E '^(FAIL|ERROR):|^Ran |^OK|^FAILED'
if grep -nE 'resolve-project refused: |"resolve-project returned a non-object"|"resolve-project timed out"' $S/workflow-state.py; then exit 1; fi
grep -c 'resolve-project refused at {label}: ' $S/workflow-state.py
```

Expected: `Ran 5 tests` and `OK`, then `Ran 2 tests` and `OK`, then `OK` for the
whole delivery-workflow file. The `if grep` finds nothing, and the last line
prints `1`. Summarize any failure to its test ids.

- [ ] **Step 5: Commit**

```bash
git add $S/workflow-state.py $T/test_delivery_workflow.py $T/test_workflow_state.py
git commit -m "fix(workflow-state): relay resolve-project refusals exactly in build-delivery" \
  -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
