# Task 4: The offline rule and the tracker credential check

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (with `context.offline` and `context.contract`), `bounded_run`, `evaluate`, `REGISTRY`, `REPAIRS`.
- Produces:
  - A new `Check` field `network: bool = False`, defaulted so every existing registry entry is unchanged.
  - The offline rule inside `evaluate`.
  - `check_tracker_credential(context)` and the registry entry `host.tracker.credential`.
  - `TRACKER_CREDENTIAL_ARGV: dict[str, tuple[str, ...]]`, the closed dispatch on `tracker.kind`.
  - Repairs `conformance.rerun_online` and `host.tracker.authenticate`.

**Invariants:**
- `--offline` is the **only** way the engine learns it is offline. Nothing probes the network to decide, and no evaluator may write `context.offline` (D7, the plan root's offline rule).
- When `context.offline` is true and the entry's `network` is true, the evaluator body **never runs**: the rule is applied in `evaluate`, before the `getattr` dispatch. This is what mechanically prevents a skipped probe from becoming a pass.
- A required `not_run` drives `outcome.status` to `incomplete`; a `warning` never does (D8).
- `workflow_entry` selects no network-flagged check, so `--offline` cannot change its outcome. Assert it; do not assume it.
- The credential check records a boolean and a hostname. It never records a token, a username, a raw CLI stdout line, or an environment variable value.
- An unrecognised `tracker.kind` is `not_run` / `unsupported_tracker_kind`, never a pass (D20).

## The offline rule in `evaluate`

Insert between the suppression step and the evaluator dispatch:

```
if context.offline and entry.network:
    result = Outcome("not_run", "offline_constraint", "conformance.rerun_online")
else:
    result = getattr(module, entry.run)(context)
```

`offline_constraint` must therefore be a declared member of every network-flagged entry's `reason_codes`, so the Task 2 assertion in step 5 of `evaluate` still holds.

For `workflow_entry`, `not_run` is already a stopping status (Task 2, step 4), so an offline entry run would stop there — but no `workflow_entry` entry is network-flagged, so the branch is unreachable for that purpose and the test below pins it.

## Registry entry this task adds

Append after `host.executor.helper_on_path`:

| Id | Domain | Subject kind | Req. | Net | Depends on | Reason codes |
|---|---|---|---|---|---|---|
| `host.tracker.credential` | host | tracker | required | **yes** | `repository.contract.valid` | `offline_constraint`, `unsupported_tracker_kind`, `tracker_credential_missing` |

Repairs added:
- `conformance.rerun_online` → `{"module": "conformance", "safety_class": "read_only", "operation": {"subcommand": "run", "args": []}}`
- `host.tracker.authenticate` → `{"module": "conformance", "safety_class": "user_action", "operation": None}`

## `check_tracker_credential`

```python
TRACKER_CREDENTIAL_ARGV = {"github": ("auth", "status")}
```

1. Read `tracker = context.contract["bindings"]["tracker"]`. Take `kind = tracker["kind"]` and `cli = tracker["cli"]`.
2. If `kind not in TRACKER_CREDENTIAL_ARGV`: return
   `Outcome("not_run", "unsupported_tracker_kind", "host.tracker.authenticate", {"kind": kind[:200], "cli": cli[:200]})`.
   This is a **required** check, so a `not_run` here drives the outcome to `incomplete` — the engine never passes a tracker it cannot interrogate (D20).
3. Build the child environment: `env = dict(os.environ)`, then `env.pop(name, None)` for every name in `tracker["credential_env"]["unset_before_invocation"]`. The contract is the single home for that policy; this repository declares an empty list, so nothing is scrubbed here (D20). Never scrub a name the contract does not list.
4. `proc = bounded_run([cli, *TRACKER_CREDENTIAL_ARGV[kind]], cwd=context.root, env=env)` (D19).
5. `proc is None` — the CLI could not be spawned at all — is not this check's finding: `host.executor.helper_on_path` already reports a missing tracker CLI. Return
   `Outcome("not_run", "tracker_credential_missing", "host.tracker.authenticate", {"authenticated": False, "cli_invoked": False})`.
6. `proc.returncode == 0` → `Outcome("passed", None, None, {"authenticated": True, "cli_invoked": True, "host": <hostname>})`.
7. Otherwise → `Outcome("failed", "tracker_credential_missing", "host.tracker.authenticate", {"authenticated": False, "cli_invoked": True, "host": <hostname>})`.

**The hostname fact.** Derive it from the contract, not from CLI output: `tracker["repo_slug"]` is `<owner>/<name>` and carries no host, so use the fixed value `"github.com"` for `kind == "github"`, taken from the same closed dispatch table — extend it to `{"github": {"argv": ("auth", "status"), "host": "github.com"}}` so kind, subcommand and host have one home. Parsing the CLI's stdout for a hostname would put unbounded tool output into the report; the closed table cannot.

Never place `proc.stdout` or `proc.stderr` in `facts`. `gh auth status` prints the account name, which is exactly the class of value #69 forbids.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`. Add a fixture helper:

```python
def stub_path(tmp: Path, name: str, exit_code: int) -> str:
    """A PATH containing only an executable `name` stub exiting `exit_code`."""
    bindir = tmp / "stubbin"
    bindir.mkdir(exist_ok=True)
    stub = bindir / name
    stub.write_text(f"#!/bin/sh\nexit {exit_code}\n", encoding="utf-8")
    stub.chmod(0o755)
    for extra in ("git", "just", "codex"):
        link = bindir / extra
        if not link.exists():
            link.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            link.chmod(0o755)
    return str(bindir)


def run_with_path(path: str, *args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *args], capture_output=True, text=True,
        timeout=60, env=dict(os.environ, PATH=path))
    return proc.returncode, proc.stdout, proc.stderr
```

```python
class OfflineRuleTest(ReportAssertions, unittest.TestCase):
    """AC4: offline is an input; a network check reports not_run and the
    outcome is incomplete, never a pass."""

    def test_doctor_offline_marks_the_network_check_not_run_and_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            path = stub_path(Path(tmp), "gh", 0)
            code, out, err = run_with_path(
                path, "run", "--purpose", "doctor", "--repo-root", str(root), "--offline")
            self.assertEqual(code, 0, err)
            report = json.loads(out)
            self.assertTrue(report["request"]["offline"])
            check = {c["id"]: c for c in report["checks"]}["host.tracker.credential"]
            self.assertEqual(check["status"], "not_run")
            self.assertEqual(check["reason_code"], "offline_constraint")
            self.assertEqual(check["repair_id"], "conformance.rerun_online")
            self.assertEqual(check["facts"], {})
            self.assertEqual(report["outcome"]["status"], "incomplete")
            self.assertEqual(report["outcome"]["primary_check_id"],
                             "host.tracker.credential")
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "conformance.rerun_online"]
            self.assertEqual(repair["safety_class"], "read_only")
            self.assertEqual(repair["operation"], {"subcommand": "run", "args": []})
            self.assert_validates(report)

    def test_offline_never_yields_a_passing_network_check(self):
        """The body must not run: a stub that would pass online still reports not_run."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            path = stub_path(Path(tmp), "gh", 0)
            _, online, _ = run_with_path(path, "run", "--purpose", "doctor",
                                         "--repo-root", str(root))
            _, offline, _ = run_with_path(path, "run", "--purpose", "doctor",
                                          "--repo-root", str(root), "--offline")
            online_check = {c["id"]: c for c in json.loads(online)["checks"]}[
                "host.tracker.credential"]
            offline_check = {c["id"]: c for c in json.loads(offline)["checks"]}[
                "host.tracker.credential"]
            self.assertEqual(online_check["status"], "passed")
            self.assertEqual(offline_check["status"], "not_run")

    def test_workflow_entry_selects_no_network_check(self):
        """Asserted, not assumed: --offline cannot change the entry outcome."""
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            path = stub_path(Path(tmp), "gh", 1)
            plain = run_with_path(path, "run", "--purpose", "workflow_entry",
                                  "--repo-root", str(root))
            offline = run_with_path(path, "run", "--purpose", "workflow_entry",
                                    "--repo-root", str(root), "--offline")
            self.assertEqual(plain[0], 0, plain[2])
            self.assertEqual(offline[0], 0, offline[2])
            self.assertEqual(json.loads(plain[1])["outcome"],
                             json.loads(offline[1])["outcome"])
            self.assertNotIn("host.tracker.credential",
                             [c["id"] for c in json.loads(offline[1])["checks"]])


class TrackerCredentialTest(ReportAssertions, unittest.TestCase):
    def test_authenticated_cli_passes_and_records_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, err = run_with_path(
                stub_path(Path(tmp), "gh", 0), "run", "--purpose", "doctor",
                "--repo-root", str(root))
            self.assertEqual(code, 0, err)
            check = {c["id"]: c for c in json.loads(out)["checks"]}[
                "host.tracker.credential"]
            self.assertEqual(check["status"], "passed")
            self.assertEqual(check["subject_kind"], "tracker")
            self.assertEqual(check["facts"],
                             {"authenticated": True, "cli_invoked": True,
                              "host": "github.com"})
            self.assertIsNone(check["repair_id"])

    def test_unauthenticated_cli_fails_with_a_user_action_repair(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run_with_path(
                stub_path(Path(tmp), "gh", 1), "run", "--purpose", "doctor",
                "--repo-root", str(root))
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}["host.tracker.credential"]
            self.assertEqual(check["status"], "failed")
            self.assertEqual(check["reason_code"], "tracker_credential_missing")
            self.assertFalse(check["facts"]["authenticated"])
            self.assertEqual(
                {r["repair_id"]: r for r in report["repairs"]}[
                    "host.tracker.authenticate"]["safety_class"], "user_action")
            self.assert_validates(report)

    def test_unknown_tracker_kind_is_not_run_and_never_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            contract = json.loads(
                (root / ".agents/project.json").read_text(encoding="utf-8"))
            contract["bindings"]["tracker"]["kind"] = "forgejo"
            (root / ".agents/project.json").write_text(
                json.dumps(contract), encoding="utf-8")
            code, out, _ = run_with_path(
                stub_path(Path(tmp), "gh", 0), "run", "--purpose", "doctor",
                "--repo-root", str(root))
            self.assertEqual(code, 0)
            report = json.loads(out)
            check = {c["id"]: c for c in report["checks"]}["host.tracker.credential"]
            self.assertEqual(check["status"], "not_run")
            self.assertEqual(check["reason_code"], "unsupported_tracker_kind")
            self.assertEqual(check["facts"]["kind"], "forgejo")
            self.assertEqual(report["outcome"]["status"], "incomplete")

    def test_ci_purpose_omits_the_credential_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = make_root(Path(tmp))
            code, out, _ = run_with_path(
                stub_path(Path(tmp), "gh", 1), "run", "--purpose", "ci",
                "--repo-root", str(root))
            self.assertEqual(code, 0)
            self.assertNotIn("host.tracker.credential",
                             [c["id"] for c in json.loads(out)["checks"]])
```

`test_ci_purpose_omits_the_credential_check` pins the spec's "CI owns its own auth": `ci` selects `repository`, `compatibility` and `verification`, never `host`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the four new classes fail with `KeyError: 'host.tracker.credential'`; every earlier class still passes.

- [ ] **Step 3: Write the minimal implementation**

Add the `network: bool = False` field to `Check`, the offline branch to `evaluate`, the closed `TRACKER_CREDENTIAL_ARGV` table (extended to carry `host`), the evaluator, the registry entry and the two repairs.

```python
def check_tracker_credential(context: "Context") -> "Outcome":
    """Contract: passed when the declared tracker CLI reports an authenticated
    credential; not_run for a tracker kind this engine cannot interrogate.
    Records a boolean and a hostname from the closed table, never CLI output."""
```

Dispatch on `kind` through the closed table and return the `not_run` branch for an unrecognised key — do **not** raise here: an unknown kind is authored data the resolver deliberately accepts as a free string, so it is a finding, not an engine bug (D20).

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . --offline \
  | python3 -c 'import json,sys; r=json.load(sys.stdin); c={x["id"]:x for x in r["checks"]}["host.tracker.credential"]; print(c["status"], c["reason_code"], r["outcome"]["status"])'
if python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . --offline \
   | grep -q '"host.tracker.credential".*"passed"'; then echo "offline produced a pass"; exit 1; fi
```

Expected: unittest OK; `just agent-workflow-tests` passes; the third command prints `not_run offline_constraint incomplete`; the guard prints nothing and exits 0.

Falsifiability at the base commit: the third command fails with `KeyError: 'host.tracker.credential'`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/scripts/conformance.py \
        home/common/agent-skills/tests/test_conformance.py
git commit -m "$(cat <<'MSG'
feat(conformance): make offline an input and register the tracker credential check

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy
MSG
)"
```
