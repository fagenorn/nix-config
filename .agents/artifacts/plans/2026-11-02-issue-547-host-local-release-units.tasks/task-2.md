# Task 2: Host world and the `codesigned-artifact` read half

Per D1, D3, D4, D6, D7, D8, D13, D17, D19, D21. Read the plan root's Global Constraints and the spec's § `codesigned-artifact` (target, config, `inspect` table) first: this task implements that `inspect` table exactly.

**Files:**
- Create: `tests/host_world.py`
- Create: `python/agent_tools/codesigned_artifact_adapter.py` (`describe`, `inspect`; no `invoke` yet, not registered)
- Create: `tests/test_codesigned_artifact_adapter.py`
- Modify: `justfile` (add the new suite after `tests/test_release_adapter_core.py`)

**Interfaces:**
- Produces, in `tests/host_world.py`:
  - `REAL_GIT` (see below), `IDENTITY = ("0123456789ABCDEF0123456789ABCDEF01234567", "Apple Development: Example Person (TEAM000001)")`, `OTHER = ("89ABCDEF0123456789ABCDEF0123456789ABCDEF", "Developer ID Application: Example Org (TEAM000002)")`, `TEAM = "TEAMID0001"`.
  - `class HostWorld(test_case)` with attributes `root`, `bin`, `state`, `home`, `checkout` (all resolved `Path`s) and methods `environ(**values: str | None) -> None` (set, or remove for `None`, inside the world's patch), `head() -> str`, `commit(message="change") -> str` (appends a line to the tracked `README`, commits, returns the new HEAD), `dirty() -> None` (modifies `README`, no commit), `bundle(relative="build/Notifier.app", *, identifier="dev.example.notifier", binary=False) -> Path`, `installed(home_relative, *, stamp: tuple[str, str] | None, identity: str | None) -> Path`, `identities(*pairs, exit=0, stderr="", sleep=0) -> None`, `fail(tool, verb, *, exit, stderr="", sleep=0) -> None`, `calls(tool=None) -> list[dict]`, `tree() -> dict[str, str]`.
- Produces, in `agent_tools.codesigned_artifact_adapter`: `describe() -> dict`, `inspect(request) -> dict`, constants `INSPECT_BUDGET_SECONDS = 30`, `DETAIL_LIMIT = 240`, `STAMP_VERSION = "AgentReleaseVersion"`, `STAMP_COMMIT = "AgentReleaseCommit"`, `CONFIG_MEMBERS` (the four members and types below). Task 3 adds `invoke` and registers the module; Tasks 4, 5 and 7 extend and use `HostWorld`.

**Invariants:**
- `describe()` returns a fresh dict equal to `DESCRIPTOR` in Step 1, and `release_adapter.descriptor_problems(describe()) == []`.
- `inspect` never raises and never mutates: `world.tree()` and every checkout byte are identical before and after any call, and it starts only `codesign` children.
- Every observation passes `release_adapter.effect_observation_problems` or `predicate_observation_problems`; `facts.detail` is at most 240 characters.
- Every non-`satisfied` `publication_visible` reason is one of `ref_absent`, `subject_mismatch`, `digest_mismatch`, `store_unreachable` (D19).
- The module imports only the standard library and `agent_tools.canonical`, and is not in `release_adapter.REGISTRY`.

## The host world (`tests/host_world.py`)

Module docstring in the `forge_world`/`actions_world` style, stating what the world is and that no test reaches this host's `launchctl`, `codesign` or `security`. `HostWorld.__init__`:

1. A `tempfile.TemporaryDirectory` cleaned up by the test; `root` is its `resolve()`d path, with `bin/`, `state/`, `home/` and `checkout/` under it.
2. `bin/git` is a wrapper script that logs `{"tool": "git", "argv"}` and then `os.execv`s the real git, the module-level constant `REAL_GIT = os.path.realpath(shutil.which("git"))`, computed once at import, before any world patches `PATH`. Every `HostWorld` uses it, so a table that calls `self.setUp()` again while the previous world's patch is active never wraps that world's wrapper. The world's own setup and `commit`/`dirty` run that real path directly, unlogged. `bin/security` and `bin/codesign` are one Python script each (shebang `sys.executable`, mode +x) that appends `{"tool", "argv"}` to `state/calls.jsonl`, applies a knob from `state/knobs.json` (`{tool: {verb: {exit, stderr, sleep}}}`: sleep, write stderr, exit with that code, doing nothing else), and otherwise behaves as below. Any other argv exits 64 with `fake <tool>: unregistered call`.
3. `checkout/` is `git init -q -b main`, one tracked `README`, and one commit, run with `-c user.name=world -c user.email=world@example.invalid -c commit.gpgsign=false` (every world commit uses these).
4. `mock.patch.dict(os.environ, {"PATH": str(bin), "HOME": str(home), "HOST_WORLD": str(state), "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"})`, started and stopped by cleanup; then `os.chdir(checkout)`, restored by cleanup.

`security find-identity -v -p codesigning` prints, from `state/identities.json`, one line `  {n}) {hash} "{name}"` per pair (n from 1) and then `     {count} valid identities found`, all on stdout, exit 0 (`identities(...)` replaces the list and its own exit, stderr and sleep). Default: no identities.

`codesign` (D21's shapes, from this host's capture):
- `--force --sign <id> <path>`: writes `<path>/Contents/_CodeSignature/CodeResources` as JSON `{"identity": <id>, "seal": <hex>}`, where the seal is the SHA-256 over every entry under `<path>` except `Contents/_CodeSignature/`, in sorted relative-POSIX-path order, of `path NUL kind NUL content` (a file's bytes, a symlink's `os.readlink` text, nothing for a directory). Exit 0.
- `--verify --deep --strict <path>`: no seal file prints `<path>: code object is not signed at all` on stderr, exit 1; a seal that differs from the recomputed one prints `<path>: a sealed resource is missing or invalid`, exit 1; else exit 0.
- `-d --verbose=2 <path>`: unsigned is exit 1 with the not-signed message. Otherwise exit 0 with these lines on **stderr** and nothing on stdout: `Executable=<path>/Contents/MacOS/notifier`, `Identifier=<CFBundleIdentifier>`, `Format=app bundle with Mach-O thin (arm64)`, `CodeDirectory v=20400 size=403 flags=0x0(none) hashes=6+3 location=embedded`; then for `-`: `Signature=adhoc`, `TeamIdentifier=not set`; else `Signature size=4792`, `Authority=<name of the hash in identities.json, else the id>`, `Authority=Apple Worldwide Developer Relations Certification Authority`, `Authority=Apple Root CA`, `TeamIdentifier=TEAMID0001`; then `Sealed Resources version=2 rules=13 files=2`.
- Knob verbs: `sign`, `verify`, `display`.

`bundle(...)` writes, untracked, `<checkout>/<relative>/Contents/Info.plist` (`{"CFBundleIdentifier": identifier, "CFBundleName": "Notifier"}`, XML, or binary when `binary`), `Contents/MacOS/notifier` (`b"\x7fnotifier"`) and the relative symlink `Contents/Resources/current -> ../MacOS/notifier`. `installed(...)` copies `bundle()` (creating it if missing) to `$HOME/<home_relative>` with symlinks kept, sets the two stamp keys when `stamp` is `(version, commit)`, then runs `bin/codesign --force --sign <identity> <path>` when `identity` is not `None`. `tree()` maps every path under `home` to `"dir"`, `"-> <target>"` or the file's SHA-256 hex.

## The adapter read half

`DESCRIPTOR` below is the spec's table. Shape rules (D7, D17), the first failure answering `parameters_invalid` with the rule in `facts.detail`:
- An effect request is exactly `{kind: "effect", operation, parameters}`; a predicate request exactly `{kind: "predicate", predicate, operation, parameters}`; `operation` is `install`.
- `parameters` holds `target`, `candidate`, `config`, may hold `action` and `operation`, nothing else.
- `target` is `{kind: "installed_bundle", path}` plus an optional non-empty `handle`. `path` starts `~/`; its remainder splits on `/` into segments that are non-empty and neither `.` nor `..`; no control character (`[\x00-\x1f\x7f]`). It expands to `os.path.expanduser("~")` + `/` + remainder.
- `candidate` is exactly `{version: vMAJOR.MINOR.PATCH, commit: 40 lowercase hex}`.
- `config` has every required member and only declared ones. Strings are non-empty, without control characters. `source` is relative with segments as for `path`. `identity_env` matches `[A-Za-z_][A-Za-z0-9_]*`. `adhoc_fallback` is a `bool`.

One runner runs `[name, *args]` by name: stdin `/dev/null`, the environment unchanged, text with `errors="replace"`, and a timeout of what is left of one `INSPECT_BUDGET_SECONDS` deadline per `inspect` call. `TimeoutExpired` is `lookup_timeout`, `OSError` is `executable_missing`, and `ValueError` is `lookup_failed`. Stderr is stripped and cut to 240 characters as `facts.detail`. Each row of the spec's table runs once the rows above it do not apply:
- `lstat`: no entry, or a symlink, a non-directory, or `Contents/Info.plist` that fails `plistlib.load` (`OSError`, `ValueError`, `xml.parsers.expat.ExpatError`) or is not a dict.
- The stamp is present only when both keys are strings.
- `codesign --verify --deep --strict <path>`: exit 1 or 3 is `signature_invalid`, any other non-zero exit is `unknown`/`lookup_failed`.
- `codesign -d --verbose=2 <path>`: a non-zero exit is `unknown`/`lookup_failed`. Its stderr lines split at the first `=`: `Identifier`, the first `Authority`, `TeamIdentifier` (`not set` is `None`), and `adhoc` is `Signature=adhoc` present.

Observation members are per the spec. `observed_subject` always has the four keys `version`, `commit`, `identifier`, `authority`, `None` where unread. `references` is `[<absolute path>]`, `[]` for `parameters_invalid`. `facts` is `{path, stamp, signature}`, `None` where unread, plus `detail` on a failure. The `publication_visible` predicate maps the effect row by the table's last column, with `references` from the effect. An invalid request is `unknown`/`store_unreachable` (D19), and any other predicate is `unknown`/`predicate_unsupported`. A predicate observation is exactly `{outcome, reason, references, observed_at}`.

- [ ] **Step 1: Write the failing tests**

`tests/test_codesigned_artifact_adapter.py`, docstring `"""The codesigned-artifact adapter (issue 547). Run: just agent-workflow-tests"""`:

```python
import unittest
from unittest import mock

from agent_tools import codesigned_artifact_adapter as adapter, release_adapter
from .host_world import IDENTITY, HostWorld

PATH = "~/Library/Application Support/Notifier/Notifier.app"
CONFIG = {"source": "build/Notifier.app", "identity_prefix": "Apple Development",
          "identity_env": "NOTIFIER_SIGNING_IDENTITY", "adhoc_fallback": False}
DESCRIPTOR = {"name": "codesigned-artifact", "adapter_contract_version": "1.0.0",
              "operations": {"install": {
                  "mode": "materialize", "support": "supported", "inspect": "supported",
                  "reason": None, "mutability": "in_place", "config_schema_version": 1,
                  "config_schema": {"members": {"adhoc_fallback": "boolean", "identity_env": "string",
                                                "identity_prefix": "string", "source": "string"},
                                    "required": ["adhoc_fallback", "identity_prefix", "source"]},
                  "effects": ["reversible_no_incremental_spend", "irreversible"],
                  "recovery_capable": False, "candidate_members": []}},
              "predicates": {"publication_visible": {"support": "supported", "reason": None},
                             "running_subject_identity": {"support": "unsupported",
                                                          "reason": "no_activation_mode"}},
              "collector": {"max_collection_latency_ms": 30000, "max_concurrent_collections": 1},
              "target_kinds": {"installed_bundle": ["path"]},
              "credential_classes": ["codesigning_identity"],
              "executables": ["codesign", "git", "security"], "host_capacity": "not_required"}

class Case(unittest.TestCase):
    def setUp(self):
        self.world = HostWorld(self)
        self.world.environ(NOTIFIER_SIGNING_IDENTITY=None)
        self.world.identities(IDENTITY)
        self.candidate = {"version": "v1.2.3", "commit": self.world.head()}

    def parameters(self, **config):
        return {"action": "notifier", "operation": "install",
                "target": {"handle": "notifier", "kind": "installed_bundle", "path": PATH},
                "candidate": dict(self.candidate), "config": {**CONFIG, **config}}

    def effect(self, parameters=None):
        return adapter.inspect({"kind": "effect", "operation": "install",
                                "parameters": parameters or self.parameters()})

    def visible(self, parameters=None):
        return adapter.inspect({"kind": "predicate", "predicate": "publication_visible",
                                "operation": "install", "parameters": parameters or self.parameters()})

    def install(self, stamp="candidate", identity=IDENTITY[0]):
        stamp = (self.candidate["version"], self.candidate["commit"]) if stamp == "candidate" else stamp
        return self.world.installed(PATH[2:], stamp=stamp, identity=identity)

class DescribeTest(Case):
    def test_descriptor_is_exact_valid_and_fresh(self):
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertEqual(release_adapter.descriptor_problems(adapter.describe()), [])
        adapter.describe()["operations"].clear()
        self.assertEqual(adapter.describe(), DESCRIPTOR)
        self.assertNotIn("codesigned-artifact", release_adapter.REGISTRY)

class ClassificationTest(Case):
    def test_each_row_of_the_inspect_table(self):
        def tamper():
            path = self.install()
            (path / "Contents/MacOS/notifier").write_bytes(b"changed")
        rows = (
            ("no entry", lambda: None, ("absent", "bundle_absent"), ("unsatisfied", "ref_absent")),
            ("symlink", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).symlink_to(self.world.checkout),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("regular file", lambda: (self.world.home / PATH[2:]).parent.mkdir(parents=True) or
             (self.world.home / PATH[2:]).write_text("x"),
             ("diverged", "target_unexpected"), ("unsatisfied", "subject_mismatch")),
            ("no stamp", lambda: self.install(stamp=None), ("absent", "bundle_unmanaged"),
             ("unsatisfied", "subject_mismatch")),
            ("other release", lambda: self.install(stamp=("v1.2.2", "f" * 40)),
             ("absent", "bundle_other_release"), ("unsatisfied", "subject_mismatch")),
            ("unsigned", lambda: self.install(identity=None), ("diverged", "signature_invalid"),
             ("unsatisfied", "digest_mismatch")),
            ("tampered", tamper, ("diverged", "signature_invalid"), ("unsatisfied", "digest_mismatch")),
            ("ad hoc refused", lambda: self.install(identity="-"), ("diverged", "signature_policy"),
             ("unsatisfied", "subject_mismatch")),
            ("signed", lambda: self.install(), ("satisfied", "installed"), ("satisfied", "installed")),
            ("verify exit 2", lambda: self.install() and self.world.fail("codesign", "verify", exit=2),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("display fails", lambda: self.install() and self.world.fail("codesign", "display", exit=1),
             ("unknown", "lookup_failed"), ("unknown", "store_unreachable")),
            ("codesign missing", lambda: self.install() and (self.world.bin / "codesign").unlink(),
             ("unknown", "executable_missing"), ("unknown", "store_unreachable")))
        for name, arrange, effect, visible in rows:
            with self.subTest(row=name):
                self.setUp()
                arrange()
                before = self.world.tree()
                observed = self.effect()
                self.assertEqual((observed["outcome"], observed["reason"]), effect)
                self.assertEqual(release_adapter.effect_observation_problems(observed), [])
                predicate = self.visible()
                self.assertEqual((predicate["outcome"], predicate["reason"]), visible)
                self.assertEqual(sorted(predicate), ["observed_at", "outcome", "reason", "references"])
                self.assertEqual(self.world.tree(), before)
                self.assertEqual({c["tool"] for c in self.world.calls()} - {"codesign"}, set())
```

Add, each a separate test method on these classes:
- `ClassificationTest.test_ad_hoc_is_installed_when_the_policy_allows_it`: `install(identity="-")` with `adhoc_fallback=True` is `satisfied`/`installed`, with `facts.signature == {"identifier": "dev.example.notifier", "authority": None, "team_identifier": None, "adhoc": True}`.
- `ClassificationTest.test_a_verify_past_the_budget_is_lookup_timeout`: patch `adapter.INSPECT_BUDGET_SECONDS` to 1 and `fail("codesign", "verify", exit=0, sleep=3)`. The effect is `unknown`/`lookup_timeout` and `facts.detail` is empty.
- `ObservationTest.test_a_satisfied_observation_carries_stamp_and_signature`: `observed_subject == {"version": "v1.2.3", "commit": <head>, "identifier": "dev.example.notifier", "authority": IDENTITY[1]}`, `references == [str(world.home / PATH[2:])]`, and `facts == {"path": <same>, "stamp": {"version", "commit"}, "signature": {"identifier", "authority": IDENTITY[1], "team_identifier": "TEAMID0001", "adhoc": False}}`.
- `ObservationTest.test_stderr_detail_is_bounded`: `fail("codesign", "verify", exit=2, stderr="e" * 1000)` gives `len(facts["detail"]) == 240`.
- `ShapeTest.test_requests_outside_the_closed_shape_start_no_child`: each mutation below is `unknown`/`parameters_invalid` from `effect`, `unknown`/`store_unreachable` from `visible`, and `world.calls() == []`. Mutations: target kind `github_repository`; target extra member `domain`; path `/Users/x/N.app`, `~/a/../N.app`, `~//N.app`, `~/./N.app`, `~/N\n.app`; version `1.2.3`; commit uppercase hex; config missing `source`; config extra `entitlements`; source `/abs/N.app`, `build/../N.app`; `identity_env` `1BAD`; `adhoc_fallback` `"yes"`; parameters extra `title`; operation `publish` (request and `parameters.operation` both). A request that is not a dict, or lacks `kind`, is `unknown`/`parameters_invalid` too.
- `ShapeTest.test_an_undeclared_predicate_is_unsupported`: predicates `running_subject_identity` and `agent_running` are `unknown`/`predicate_unsupported`.
- `ShapeTest.test_the_module_imports_only_stdlib_and_canonical`: parse the module source with `ast`. Every `ImportFrom` whose module starts with `agent_tools` names `agent_tools.canonical`, and no `Import` names `agent_tools`.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_codesigned_artifact_adapter.py 2>&1 | tail -4'`
Expected: FAIL. `ModuleNotFoundError` names `tests.host_world` first, then `agent_tools.codesigned_artifact_adapter` once the world exists.

- [ ] **Step 3: Write the minimal implementation**

Write `tests/host_world.py`, then the module, as specified above. The module docstring states its surface (`describe`, `inspect`), its imports, the shape rules, the inspection budget and the classification by reference to the issue 547 spec. It must not mention an `invoke` this commit lacks. Add the suite to `justfile`.

- [ ] **Step 4: Verify**

Run: `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_codesigned_artifact_adapter.py tests/test_release_grammar.py 2>&1 | tail -4'`
Expected: PASS, `OK`.

Run: `if grep -qi argus python/agent_tools/codesigned_artifact_adapter.py tests/host_world.py; then exit 1; fi`
Expected: exit 0.

Run (timeout 3600 s, after `git add`): `just build`
Expected: exit 0 (the new module import-checks).

- [ ] **Step 5: Commit**

```bash
git add tests/host_world.py python/agent_tools/codesigned_artifact_adapter.py tests/test_codesigned_artifact_adapter.py justfile
launch-commit --repo-root <ledger root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(issue-547/T2): host world and codesigned-artifact inspection" -m "<trailer>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":2,"records":[{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["r2a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2a","last_task":4,"owner":2,"path":"tests/host_world.py"},{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["r2b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2b","last_task":3,"owner":2,"path":"python/agent_tools/codesigned_artifact_adapter.py"},{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["r2c"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r2c","last_task":3,"owner":2,"path":"tests/test_codesigned_artifact_adapter.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r2d"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r2d","last_task":4,"owner":2,"path":"justfile"}]}}
```
