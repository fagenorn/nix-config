# Task 4: The offline rule and the tracker credential check

**Files:**
- Modify: `home/common/agent-skills/scripts/conformance.py`
- Modify: `home/common/agent-skills/tests/test_conformance.py`

**Interfaces:**
- Consumes from Task 2: `Check`, `Outcome`, `Context` (with `context.offline` and `context.contract`), `bounded_run`, `evaluate`, `REGISTRY`, `REPAIRS`, `bound_fact`; from Task 1: `run`, `doctor`, `fixture`, `make_stub_bin`, `HERMETIC_ENV`.
- Produces:
  - A new `Check` field `network: bool = False`, defaulted so every existing registry entry is unchanged.
  - The offline rule inside `evaluate`.
  - `check_tracker_credential(context)` and the registry entry `host.tracker.credential`.
  - `TRACKERS: dict[str, dict]`, the closed dispatch on `tracker.kind`.
  - Repairs `conformance.rerun_online` and `host.tracker.authenticate`.

**Invariants:**
- `--offline` is the **only** way the engine learns it is offline; no evaluator may write `context.offline` (D7, the root's offline rule).
- When `context.offline` is true and the entry's `network` is true, the evaluator body **never runs**: the rule is applied in `evaluate`, before the `getattr` dispatch. That is what mechanically prevents a skipped probe from becoming a pass.
- `workflow_entry` selects no network-flagged check, so `--offline` cannot change its outcome. Assert it; do not assume it.
- The check records a boolean and a hostname. Never a token, a username, a raw CLI stdout line, or an environment variable value.
- An unrecognised `tracker.kind` is `not_run` / `unsupported_tracker_kind`, never a pass (D20).
- No test reaches a real tracker: every case runs through the hermetic runner with a stub CLI on `PATH` (D35). The S3 in-process seam inherits the caller's environment instead, so every S3 case calling `main` passes `--offline`; the rule below is what keeps this check from spawning `gh` there. Never add an S3 case that runs this registry online.

## The offline rule in `evaluate`

Insert between the suppression step and the evaluator dispatch:

```
if context.offline and entry.network:
    result = Outcome("not_run", "offline_constraint", "conformance.rerun_online")
else:
    result = getattr(module, entry.run)(context)
```

`offline_constraint` must therefore be a declared member of every network-flagged entry's `findings`, so the Task 2 guard still holds. For `workflow_entry`, `not_run` is already a stopping status, so an offline entry run would stop there — but no `workflow_entry` entry is network-flagged, so the branch is unreachable for that purpose and the test below pins it.

## Registry entry this task adds

Append after `host.executor.helper_on_path`:

| Id | Domain | Subject kind | Req. | Net | Depends on | `findings`: reason code → repair id |
|---|---|---|---|---|---|---|
| `host.tracker.credential` | host | tracker | required | **yes** | `repository.contract.valid` | `offline_constraint` → `conformance.rerun_online`; `unsupported_tracker_kind` → `host.tracker.authenticate`; `tracker_credential_missing` → `host.tracker.authenticate` |

Repairs added:
- `conformance.rerun_online` → `{"module": "conformance", "safety_class": "read_only", "operation": None}` — `null`: a rerun repeats the caller's own request without `--offline`, so no fixed argv performs it, and bare `run` is an argparse usage error (D25).
- `host.tracker.authenticate` → `{"module": "conformance", "safety_class": "user_action", "operation": None}`

## `check_tracker_credential`

```python
TRACKERS = {"github": {"argv": ("auth", "status"), "host": "github.com"}}
```

One closed table so kind, subcommand and hostname have a single home.

1. Read `tracker = context.contract["bindings"]["tracker"]`; take `kind = tracker["kind"]`, `cli = tracker["cli"]`.
2. `kind not in TRACKERS` → `Outcome("not_run", "unsupported_tracker_kind", "host.tracker.authenticate", {"kind": bound_fact(kind), "cli": bound_fact(cli)})`. This is a **required** check, so the `not_run` drives the outcome to `incomplete` — the engine never passes a tracker it cannot interrogate (D20). Do not raise: an unknown kind is authored data the resolver deliberately accepts as a free string, so it is a finding, not an engine bug.
3. Build the child environment: `env = dict(os.environ)`, then `env.pop(name, None)` for every name in `tracker["credential_env"]["unset_before_invocation"]`. The contract is the single home for that policy; this repository declares an empty list, so nothing is scrubbed here (D20). Never scrub a name the contract does not list.
4. `proc = bounded_run([cli, *TRACKERS[kind]["argv"]], cwd=context.root, env=env)` (D19).
5. `proc is None` — the CLI could not be spawned at all — is not this check's finding; `host.executor.helper_on_path` already reports a missing tracker CLI. Return `Outcome("not_run", "tracker_credential_missing", "host.tracker.authenticate", {"authenticated": False, "cli_invoked": False})`.
6. `proc.returncode == 0` → `Outcome("passed", None, None, {"authenticated": True, "cli_invoked": True, "host": TRACKERS[kind]["host"]})`.
7. Otherwise → `Outcome("failed", "tracker_credential_missing", "host.tracker.authenticate", {"authenticated": False, "cli_invoked": True, "host": TRACKERS[kind]["host"]})`.

The hostname comes from the closed table, never from CLI output: `tracker["repo_slug"]` is `<owner>/<name>` and carries no host, and parsing stdout would put unbounded tool output into the report. Never place `proc.stdout` or `proc.stderr` in `facts` — `gh auth status` prints the account name, exactly the class of value #69 forbids.

- [ ] **Step 1: Write the failing test**

Append to `home/common/agent-skills/tests/test_conformance.py`. Cases that need a specific tool outcome build their own bin and override the hermetic `PATH`:

```python
def gh_env(tmp: Path, exit_code: int) -> dict:
    """The hermetic environment with a `gh` stub exiting `exit_code`."""
    return dict(HERMETIC_ENV,
                PATH=make_stub_bin(tmp / "stubbin", {"gh": exit_code}))


class OfflineRuleTest(ReportAssertions, unittest.TestCase):
    """AC4: offline is an input; a network check reports not_run and the
    outcome is incomplete, never a pass."""

    def test_doctor_offline_marks_the_network_check_not_run_and_incomplete(self):
        with fixture() as tmp:
            report, by_id = doctor(self, make_root(tmp), "--offline",
                                   env=gh_env(tmp, 0))
            self.assertTrue(report["request"]["offline"])
            check = by_id["host.tracker.credential"]
            self.assertEqual(
                [check["status"], check["reason_code"], check["repair_id"],
                 check["facts"]],
                ["not_run", "offline_constraint", "conformance.rerun_online", {}])
            self.assertEqual(report["outcome"], {
                "status": "incomplete",
                "primary_check_id": "host.tracker.credential"})
            repair = {r["repair_id"]: r for r in report["repairs"]}[
                "conformance.rerun_online"]
            self.assertEqual(repair["safety_class"], "read_only")
            self.assertIsNone(repair["operation"])
            self.assert_validates(report)

    def test_offline_never_yields_a_passing_network_check(self):
        """The body must not run: a stub that would pass online still not_run."""
        with fixture() as tmp:
            root, env = make_root(tmp), gh_env(tmp, 0)
            online = doctor(self, root, env=env)[1]["host.tracker.credential"]
            offline = doctor(self, root, "--offline",
                             env=env)[1]["host.tracker.credential"]
            self.assertEqual([online["status"], offline["status"]],
                             ["passed", "not_run"])

    def test_workflow_entry_selects_no_network_check(self):
        """Asserted, not assumed: --offline cannot change the entry outcome."""
        with fixture() as tmp:
            root, env = make_root(tmp), gh_env(tmp, 1)
            plain = run("run", "--purpose", "workflow_entry", "--repo-root",
                        str(root), env=env)
            offline = run("run", "--purpose", "workflow_entry", "--repo-root",
                          str(root), "--offline", env=env)
            self.assertEqual(plain[0], 0, plain[2])
            self.assertEqual(offline[0], 0, offline[2])
            self.assertEqual(json.loads(plain[1])["outcome"],
                             json.loads(offline[1])["outcome"])
            self.assertNotIn("host.tracker.credential",
                             [c["id"] for c in json.loads(offline[1])["checks"]])
```

`TrackerCredentialTest` covers the online branches through the same `gh_env` fixture, reading each report with `doctor(self, make_root(tmp), env=gh_env(tmp, <code>))`:

| Case | Stub exit / contract | Expected |
|---|---|---|
| authenticated | `gh` exits 0 | `status`/`subject_kind`/`repair_id` are `passed`/`tracker`/null, and `facts == {"authenticated": True, "cli_invoked": True, "host": "github.com"}` — a boolean and a table-sourced hostname, nothing from stdout |
| unauthenticated | `gh` exits 1 | `failed` / `tracker_credential_missing`, `facts["authenticated"]` false, and `host.tracker.authenticate` is `user_action` |
| unknown kind (D20) | set `bindings.tracker.kind` to `"forgejo"`, `gh` exits 0 | `not_run` / `unsupported_tracker_kind`, `facts["kind"] == "forgejo"`, `outcome.status == "incomplete"` — a tracker the engine cannot interrogate never passes, even when the CLI would have succeeded |
| CI omits it | `--purpose ci`, `gh` exits 1 | exit 0 and `host.tracker.credential` absent from `checks` |

Every failing case also calls `assert_validates(report)`. The last row pins the spec's "CI owns its own auth": `ci` selects `repository`, `compatibility` and `verification`, never `host`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py`
Expected: the two new classes fail with `KeyError: 'host.tracker.credential'`; every earlier class still passes.

- [ ] **Step 3: Write the minimal implementation**

Add the `network: bool = False` field to `Check`, the offline branch to `evaluate`, the closed `TRACKERS` table, the evaluator, the registry entry and the two repairs.

```python
def check_tracker_credential(context: "Context") -> "Outcome":
    """Contract: passed when the declared tracker CLI reports an authenticated
    credential; not_run for a tracker kind this engine cannot interrogate.
    Records a boolean and a hostname from the closed table, never CLI output."""
```

- [ ] **Step 4: Verify**

```bash
python3 -m unittest -v home/common/agent-skills/tests/test_conformance.py
just agent-workflow-tests
python3 home/common/agent-skills/scripts/conformance.py run --purpose doctor --repo-root . --offline \
  > /tmp/conformance-offline.json
python3 - <<'PY'
import json
report = json.load(open("/tmp/conformance-offline.json"))
check = {c["id"]: c for c in report["checks"]}["host.tracker.credential"]
print(check["status"], check["reason_code"], report["outcome"]["status"])
assert check["status"] == "not_run", "offline produced a non-skipped network check"
PY
rm -f /tmp/conformance-offline.json
```

Expected: unittest OK; `just agent-workflow-tests` passes; the script prints `not_run offline_constraint incomplete` and the assertion holds. The guard parses the report and inspects that one check object rather than grepping: the engine emits the whole report as a single compact line, so a text search from the check id through any later `"passed"` token would match a passing *repository* check further along the same line and never fail (SF-004).

Falsifiability at the base commit: the script raises `KeyError: 'host.tracker.credential'`.

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
