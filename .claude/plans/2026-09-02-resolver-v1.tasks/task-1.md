# Task 1: Authored contract, loader, validator, normalizer, error output

**Files:**
- Create: `.agents/project.json`
- Create: `.agents/instructions/bootstrap.md`
- Create: `home/common/agent-skills/scripts/resolve-project.py`
- Create: `home/common/agent-skills/tests/test_resolve_project.py`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `justfile`
- Modify: `.gitignore`

**Interfaces:**
- Produces, for Tasks 2–4: the module-level constants `SCHEMA_VERSION = 1`, `CAPABILITY_NAMES` (tuple, the eleven names in the Global Constraints order), `BINDING_NAMESPACES` (tuple of six), `ERROR_CODES`, `REASON_CODES`, `PROJECTION_KINDS`, `AGENT_IDS`; the exception `class ContractError(Exception)` carrying `code: str`, `repair_id: str`, `violations: list[dict]`; `discover_root(repo_root: str | None) -> pathlib.Path`; `load_contract(root: pathlib.Path) -> dict`; `validate_contract(source: dict) -> list[dict]` returning violations; `normalize_bindings(source_bindings: dict, root: pathlib.Path) -> dict`; `emit_error(code: str, repair_id: str, violations: list[dict]) -> int`; `emit_json(value: object) -> int`; and an argparse `main(argv: list[str] | None = None) -> int` with the subparsers `resolve`, `check-projections`, `write-projections`.
- Produces, for Task 5: the installed executable `~/.agents/bin/resolve-project` and the invocation `resolve-project resolve --repo-root <path>`.
- Consumes: nothing from earlier tasks.

**Invariants:**
- `resolve` writes to no file and creates no directory; `git status --porcelain` over the root is byte-identical before and after a run.
- No subprocess is spawned by any subcommand, including `git`.
- Every value in `bindings` is passed through byte-for-byte except path normalization; nothing is defaulted, inferred, or sniffed from the environment (D5).
- Two `resolve` runs over an unchanged root emit byte-identical stdout.
- An error run emits exactly one JSON object with an `error` member and no `schema_version` member.
- `violations` is non-empty and sorted byte-wise ascending by `pointer`; the error object's `repair_id` is the repair id of the first violation in that order.

## Steps

- [ ] **Step 1: Author the contract and the instruction source**

Write `.agents/project.json` with exactly the JSON given under "The concrete authored content for this repository" in `.claude/specs/2026-09-02-resolver-v1-design.md` — five top-level members, the six binding namespaces, the eleven capability declarations, and the two projection entries (`codex.entry` and `claude.entry`). Copy it verbatim; the orchestration values `max_parallel: 2` and `attempt_budget_minutes: 180` must equal those in `.claude/skills.config.json` (D2).

Write `.agents/instructions/bootstrap.md`. Per D4 it holds only universal project invariants and the instruction to trust `ResolvedProject`; it must not absorb the root `CLAUDE.md` body. Its exact bytes:

```markdown
# Project invariants — nix-config

This file is the canonical instruction source for every agent working in this
repository. It is projected into the native entry surface each agent discovers
on its own; those projections are generated and must never be hand-edited.

- Project policy lives in `.agents/project.json`. Never read that file directly
  and never persist a snapshot of it. Resolve once at entry with
  `resolve-project resolve` and trust the returned `ResolvedProject`.
- No project policy is defaulted. When `resolve-project` refuses, fix the
  contract; never guess a value it declined to give you.
- Every path in the snapshot is absolute and rooted at `project.root`.
- Every executable invocation is a `commands` entry addressed by its id; the
  contract carries no environment variable values and no shell text.
- `AGENTS.md` and the `@.agents/instructions/bootstrap.md` import line in
  `CLAUDE.md` are generated from this file by
  `resolve-project write-projections`. Edit this file, then regenerate.
```

Append `.agents/runtime/` to `.gitignore`, under the existing ephemeral-scratch block, with a one-line comment saying it is the lazily created runtime bucket of the `.agents/` taxonomy and is never tracked.

- [ ] **Step 2: Write the failing tests**

Create `home/common/agent-skills/tests/test_resolve_project.py`:

```python
"""Contract tests for scripts/resolve-project.

Runs the resolver as a subprocess against temporary repository roots and parses
its stdout, the seam established by test_resolve_bindings.py and
test_workflow_state.py. The resolver is never imported.
"""

from __future__ import annotations

import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "resolve-project.py"
REPO_ROOT = Path(__file__).resolve().parents[4]

CAPABILITY_NAMES = (
    "tracker", "worktrees", "knowledge.context", "knowledge.standards",
    "knowledge.architecture", "knowledge.hints", "verification",
    "review.plan", "review.code", "release", "deploy",
)
BINDING_NAMESPACES = ("vcs", "tracker", "paths", "commands", "workflow", "deploy")
CAPABILITY_STATES = ("available", "unsupported", "blocked")


def run(*args: str) -> tuple[int, str, str]:
    proc = subprocess.run(
        ["python3", str(SCRIPT), *args],
        capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def source_contract() -> dict:
    return json.loads((REPO_ROOT / ".agents" / "project.json").read_text("utf-8"))


class ResolverTestCase(unittest.TestCase):
    def make_root(self, contract: object | None = None) -> Path:
        """A temp root holding a valid contract and its instruction source.

        Task 4 extends this helper to materialize the projection targets too,
        once `resolve` gates on projection freshness.
        """
        root = Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        (root / "home" / "common" / "agent-skills" / "standards").mkdir(parents=True)
        (root / ".out-of-scope").mkdir()
        (root / ".worktrees").mkdir()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        (root / ".agents" / "instructions").mkdir(parents=True)
        (root / ".agents" / "instructions" / "bootstrap.md").write_text(
            "# invariants\n", encoding="utf-8")
        if contract is None:
            contract = source_contract()
        if contract is not False:
            (root / ".agents" / "project.json").write_text(
                json.dumps(contract), encoding="utf-8")
        return root

    def resolve(self, root: Path, *extra: str) -> tuple[int, object, str]:
        code, out, err = run("resolve", "--repo-root", str(root), *extra)
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err


class SnapshotShapeTest(ResolverTestCase):
    def test_resolve_returns_exactly_four_top_level_members(self):
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(
            sorted(snap), ["bindings", "capabilities", "project", "schema_version"])
        self.assertEqual(snap["schema_version"], 1)
        self.assertEqual(sorted(snap["project"]), ["id", "name", "root"])
        self.assertEqual(sorted(snap["bindings"]), sorted(BINDING_NAMESPACES))
        self.assertEqual(sorted(snap["capabilities"]), sorted(CAPABILITY_NAMES))
        for name, entry in snap["capabilities"].items():
            with self.subTest(capability=name):
                self.assertEqual(sorted(entry), ["reason_code", "repair_id", "state"])
                self.assertIn(entry["state"], CAPABILITY_STATES)

    def test_identity_is_copied_verbatim_from_the_source(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        self.assertEqual(snap["project"]["id"], "fagenorn/nix-config")
        self.assertEqual(snap["project"]["name"], "nix-config")
        self.assertEqual(snap["project"]["root"], str(root.resolve()))

    def test_unsupported_capabilities_carry_null_reason_and_repair(self):
        code, snap, err = self.resolve(self.make_root())
        self.assertEqual(code, 0, err)
        for name in ("release", "deploy", "knowledge.context", "knowledge.hints"):
            with self.subTest(capability=name):
                entry = snap["capabilities"][name]
                self.assertEqual(entry["state"], "unsupported")
                self.assertIsNone(entry["reason_code"])
                self.assertIsNone(entry["repair_id"])

    def test_two_runs_emit_byte_identical_stdout(self):
        root = self.make_root()
        first = run("resolve", "--repo-root", str(root))
        second = run("resolve", "--repo-root", str(root))
        self.assertEqual(first[0], 0, first[2])
        self.assertEqual(first[1], second[1])

    def test_stdout_is_compact_sorted_json_with_a_trailing_newline(self):
        code, out, err = run("resolve", "--repo-root", str(self.make_root()))
        self.assertEqual(code, 0, err)
        self.assertTrue(out.endswith("\n"))
        self.assertNotIn("\n", out[:-1])
        self.assertEqual(out, json.dumps(
            json.loads(out), sort_keys=True, separators=(",", ":")) + "\n")


class NormalizationTest(ResolverTestCase):
    def test_every_path_is_absolute_under_project_root(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        paths = snap["bindings"]["paths"]
        candidates = [paths["artifacts"]["specs"], paths["artifacts"]["plans"]]
        for key in ("context", "standards", "architecture", "operations",
                    "hints", "rejections"):
            candidates.extend(paths[key])
        candidates.extend(c["cwd"] for c in snap["bindings"]["commands"].values())
        for value in candidates:
            with self.subTest(path=value):
                self.assertTrue(Path(value).is_absolute())
                self.assertTrue(
                    value == str(root.resolve())
                    or value.startswith(str(root.resolve()) + "/"))

    def test_the_source_file_keeps_its_relative_values(self):
        root = self.make_root()
        self.assertEqual(self.resolve(root)[0], 0)
        on_disk = json.loads((root / ".agents" / "project.json").read_text("utf-8"))
        self.assertEqual(
            on_disk["bindings"]["paths"]["artifacts"]["plans"], ".claude/plans")

    def test_non_path_binding_values_pass_through_unchanged(self):
        root = self.make_root()
        code, snap, err = self.resolve(root)
        self.assertEqual(code, 0, err)
        source = json.loads((root / ".agents" / "project.json").read_text("utf-8"))
        self.assertEqual(snap["bindings"]["vcs"], source["bindings"]["vcs"])
        self.assertEqual(snap["bindings"]["tracker"], source["bindings"]["tracker"])
        self.assertEqual(snap["bindings"]["workflow"], source["bindings"]["workflow"])


class ReadOnlyTest(ResolverTestCase):
    def test_resolve_leaves_the_tree_untouched(self):
        root = self.make_root()
        before = sorted(
            (str(p.relative_to(root)), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file())
        self.assertEqual(self.resolve(root)[0], 0)
        after = sorted(
            (str(p.relative_to(root)), p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


class ErrorOutputTest(ResolverTestCase):
    def assert_refusal(self, code: int, payload: object, expected: str) -> dict:
        self.assertEqual(code, 2)
        self.assertIsInstance(payload, dict)
        self.assertEqual(sorted(payload), ["error"])
        self.assertNotIn("schema_version", payload)
        error = payload["error"]
        self.assertEqual(sorted(error), ["code", "repair_id", "violations"])
        self.assertEqual(error["code"], expected)
        self.assertTrue(error["violations"])
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertEqual(pointers, sorted(pointers))
        for violation in error["violations"]:
            self.assertEqual(sorted(violation), ["message", "pointer"])
        return error

    def test_missing_contract_is_not_onboarded(self):
        root = self.make_root(contract=False)
        code, payload, _ = self.resolve(root)
        error = self.assert_refusal(code, payload, "not_onboarded")
        self.assertEqual(error["repair_id"], "onboarding.contract.missing")

    def test_repo_root_does_not_walk_up(self):
        root = self.make_root()
        nested = root / "sub" / "deeper"
        nested.mkdir(parents=True)
        code, payload, _ = self.resolve(nested)
        self.assert_refusal(code, payload, "not_onboarded")

    def test_non_json_contract_is_invalid_contract(self):
        root = self.make_root()
        (root / ".agents" / "project.json").write_text("{not json", encoding="utf-8")
        code, payload, _ = self.resolve(root)
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.parse")

    def test_non_object_contract_is_invalid_contract(self):
        root = self.make_root(contract=[1, 2, 3])
        error = self.assert_refusal(*self.resolve(root)[:2], "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.parse")

    def test_missing_schema_version_is_invalid_contract(self):
        contract = source_contract()
        del contract["schema_version"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.schema_version.invalid")

    def test_boolean_schema_version_is_invalid_contract(self):
        contract = source_contract()
        contract["schema_version"] = True
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        self.assertEqual(error["repair_id"], "contract.schema_version.invalid")

    def test_other_integer_schema_version_is_unsupported_schema(self):
        contract = source_contract()
        contract["schema_version"] = 2
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "unsupported_schema")
        self.assertEqual(error["repair_id"], "contract.schema_version.unsupported")

    def test_an_unknown_top_level_member_is_refused(self):
        contract = source_contract()
        contract["extra"] = {}
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assert_refusal(code, payload, "invalid_contract")

    def test_all_violations_are_reported_in_one_pass(self):
        contract = source_contract()
        del contract["bindings"]["deploy"]
        del contract["capabilities"]["release"]
        code, payload, _ = self.resolve(self.make_root(contract))
        error = self.assert_refusal(code, payload, "invalid_contract")
        pointers = [v["pointer"] for v in error["violations"]]
        self.assertIn("/bindings/deploy", pointers)
        self.assertIn("/capabilities/release", pointers)


class NoDefaultingTest(ResolverTestCase):
    def test_dropping_any_binding_namespace_refuses(self):
        for namespace in BINDING_NAMESPACES:
            with self.subTest(namespace=namespace):
                contract = source_contract()
                del contract["bindings"][namespace]
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")
                self.assertIn(f"/bindings/{namespace}",
                              [v["pointer"] for v in payload["error"]["violations"]])

    def test_dropping_any_capability_declaration_refuses(self):
        for name in CAPABILITY_NAMES:
            with self.subTest(capability=name):
                contract = source_contract()
                del contract["capabilities"][name]
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_a_dangling_command_id_refuses(self):
        contract = source_contract()
        contract["bindings"]["workflow"]["verification"] = ["no-such-command"]
        code, payload, _ = self.resolve(self.make_root(contract))
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_unsafe_authored_paths_refuse(self):
        for value in ("/etc", "../escape", "a/../../b"):
            with self.subTest(path=value):
                contract = source_contract()
                contract["bindings"]["paths"]["artifacts"]["plans"] = value
                code, payload, _ = self.resolve(self.make_root(contract))
                self.assertEqual(code, 2)
                self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_a_refusal_emits_no_snapshot_member(self):
        contract = source_contract()
        del contract["bindings"]["vcs"]
        code, out, _ = run("resolve", "--repo-root", str(self.make_root(contract)))
        self.assertEqual(code, 2)
        for member in ("schema_version", "project", "bindings", "capabilities"):
            self.assertNotIn(f'"{member}"', out)


class CommittedContractTest(ResolverTestCase):
    def test_the_repositorys_own_contract_is_structurally_valid(self):
        contract = source_contract()
        self.assertEqual(contract["schema_version"], 1)
        self.assertEqual(sorted(contract["capabilities"]), sorted(CAPABILITY_NAMES))
        self.assertEqual(sorted(contract["bindings"]), sorted(BINDING_NAMESPACES))

    def test_orchestration_values_match_the_legacy_config(self):
        legacy = json.loads(
            (REPO_ROOT / ".claude" / "skills.config.json").read_text("utf-8"))
        orchestration = source_contract()["bindings"]["workflow"]["orchestration"]
        self.assertEqual(orchestration["max_parallel"],
                         legacy["orchestration"]["maxParallel"])
        self.assertEqual(orchestration["attempt_budget_minutes"],
                         legacy["orchestration"]["agentBudgetMinutes"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `python3 -m unittest -v home.common.agent-skills.tests.test_resolve_project 2>&1 | tail -5` — or, matching the repository's recipe form, `python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -5`.
Expected: every test errors — `home/common/agent-skills/scripts/resolve-project.py` does not exist, so each subprocess exits 2 with an interpreter error on stderr.

- [ ] **Step 4: Implement the loader, validator, normalizer and error output**

Create `home/common/agent-skills/scripts/resolve-project.py` as a `#!/usr/bin/env python3` script using the standard library only. Follow `home/common/agent-skills/scripts/workflow-state.py` for house style: module docstring, `from __future__ import annotations`, closed constants at the top, `main(argv=None) -> int` returning the exit code, and `sys.exit(main())` under `if __name__ == "__main__":`.

Define, exactly:

```python
SCHEMA_VERSION = 1
CAPABILITY_NAMES = (...)          # the eleven, in Global Constraints order
BINDING_NAMESPACES = (...)        # the six
CAPABILITY_STATES = ("available", "unsupported", "blocked")
AUTHORED_SUPPORT = ("supported", "unsupported")
ERROR_CODES = ("not_onboarded", "invalid_contract", "unsupported_schema",
               "invalid_projection", "capability_unavailable", "resolver_failure")
REASON_CODES = ("tracker_cli_missing", "vcs_worktree_unsupported",
                "knowledge_path_missing", "command_missing")
PROJECTION_KINDS = ("generated_file", "managed_import")
AGENT_IDS = ("claude", "codex")
CONTRACT_FILENAME = ".agents/project.json"


class ContractError(Exception):
    """One refusal: a closed code, a stable repair id, and ordered violations."""
    def __init__(self, code: str, repair_id: str, violations: list[dict]) -> None: ...
```

Implement:

- `discover_root(repo_root)` — with `--repo-root`, `Path(repo_root).resolve()` **is** the root and no walk-up occurs; that directory either holds `.agents/project.json` or the run raises `ContractError("not_onboarded", "onboarding.contract.missing", [{"pointer": "", "message": ".agents/project.json was not found at or above the start directory"}])`. Without the flag, walk `Path.cwd().resolve()` and its ancestors, stopping at the first directory holding the file, and raise the same error when none does. The violation message never embeds a path, so refusal bytes stay identical between runs.
- `load_contract(root)` — read the file as UTF-8 and `json.loads` it. An `OSError`, a `UnicodeDecodeError`, a `json.JSONDecodeError`, or a parsed value that is not a `dict` raises `ContractError("invalid_contract", "contract.parse", [{"pointer": "", "message": "..."}])`.
- `validate_contract(source)` — return the full list of violations, in one pass, never aborting early. Each violation is exactly `{"pointer": <JSON Pointer string>, "message": <one sentence>}`. Before the general pass, handle `schema_version` on its own: absent, or not an `int`, or a `bool` (booleans are not integers here) raises `ContractError("invalid_contract", "contract.schema_version.invalid", ...)`; an `int` other than `SCHEMA_VERSION` raises `ContractError("unsupported_schema", "contract.schema_version.unsupported", ...)`. The general pass then checks, collecting everything:
  - top level: exactly `schema_version`, `project`, `bindings`, `capabilities`, `projections`; a missing member and an unexpected member are both violations.
  - `/project`: exactly `id` and `name`, each a non-empty `str`.
  - `/bindings`: exactly `BINDING_NAMESPACES`, each a `dict`.
  - `/bindings/vcs`: exactly `kind`, `default_branch`, `integration_branch`, `branch_pattern`, `worktree`, `commit`, `merge`. `worktree` is exactly `{root, prefix}` (strings, `root` a safe relative path); `commit` is exactly `{co_authored_by, signed}` (`bool`); `merge` is exactly `{strategy, delete_branch}` (`str`, `bool`).
  - `/bindings/tracker`: exactly `kind`, `cli`, `repo_slug`, `credential_env`; `credential_env` is exactly `{unset_before_invocation}`, a list of `str`.
  - `/bindings/paths`: exactly `artifacts`, `context`, `standards`, `architecture`, `operations`, `hints`, `rejections`. `artifacts` is exactly `{specs, plans}`, each a safe relative path string; the six others are lists of safe relative path strings, possibly empty.
  - `/bindings/commands`: a `dict` whose every value is exactly `{argv, cwd, env}` — `argv` a non-empty list of `str`, `cwd` a safe relative path string, `env` a list of `str` naming variables only (D13).
  - `/bindings/workflow`: exactly `verification`, `orchestration`, `review`, `release`. `verification` is a list of command ids; `orchestration` is exactly `{max_parallel, attempt_budget_minutes}`, each a positive `int` that is not a `bool`; `review` is exactly `{plan, code}`, each a command id or `null`; `release` is a command id or `null`.
  - `/bindings/deploy`: exactly `adapter`, `command`, `config`; `command` is a command id or `null`; `config` is a `dict`.
  - referential integrity: every non-null command id under `/bindings/workflow` and `/bindings/deploy` is a key of `/bindings/commands`, reported at the referencing pointer.
  - `/capabilities`: exactly `CAPABILITY_NAMES`, each value exactly `{"support": <one of AUTHORED_SUPPORT>}`.
  - `/projections`: a list; each entry exactly `{id, agent, kind, target, source}` with `agent` in `AGENT_IDS`, `kind` in `PROJECTION_KINDS`, `id` a non-empty unique `str`, and `target`/`source` safe relative path strings.
  - A "safe relative path" is a non-empty `str` that is not absolute, does not start with `/`, and has no `..` segment.

  When the returned list is non-empty, the caller sorts it byte-wise ascending by `pointer` and raises `ContractError("invalid_contract", <the first violation's repair id>, violations)`. Each violation carries its own repair id of the form `contract.<section>.<violation>` internally; the error object publishes the first one in pointer order.
- `normalize_bindings(source_bindings, root)` — deep-copy the source bindings and replace, with `str(root / value)`, exactly: `paths.artifacts.specs`, `paths.artifacts.plans`, every entry of the six `paths` lists, and every `commands.<id>.cwd`. Change nothing else.
- `emit_json(value)` — `json.dump(value, sys.stdout, sort_keys=True, separators=(",", ":"))`, then a `"\n"`, then return `0`.
- `emit_error(code, repair_id, violations)` — emit `{"error": {"code": code, "repair_id": repair_id, "violations": violations}}` through the same serializer and return `2`.
- `main(argv=None)` — an `argparse.ArgumentParser` with the three subcommands of D1. Each accepts `--repo-root`. Wrap the whole dispatch: a `ContractError` becomes `emit_error(...)`; any other unexpected exception becomes `emit_error("resolver_failure", "resolver.internal", [{"pointer": "", "message": "..."}])`. Dispatch over the subcommand name raises on its default branch rather than falling through.
- `resolve` in this task builds the snapshot `{"schema_version": SCHEMA_VERSION, "project": {"root": str(root), "id": ..., "name": ...}, "bindings": normalize_bindings(...), "capabilities": ...}` and emits it. Capability states here come from the authored declaration alone: `unsupported` → `{"state": "unsupported", "reason_code": None, "repair_id": None}`; `supported` → `{"state": "available", "reason_code": None, "repair_id": None}`. **Task 2 replaces that second branch with prerequisite evaluation; write no comment claiming prerequisites are already evaluated.**
- `check-projections` and `write-projections` are registered here but not yet implemented: each returns `emit_error("resolver_failure", "resolver.internal", [{"pointer": "/projections", "message": "TODO: implemented in a later task"}])`. Tasks 3 and 4 replace both bodies and the TODO.

Then wire publication:
- In `home/common/agent-skills/default.nix`, add a `".agents/bin/resolve-project" = { source = ./scripts/resolve-project.py; executable = true; };` entry alongside `".agents/bin/workflow-state"`.
- In `justfile`, add `home/common/agent-skills/tests/test_resolve_project.py` to the `agent-workflow-tests` recipe's file list, after `test_resolve_bindings.py`.

- [ ] **Step 5: Verify**

```sh
python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -5
just agent-workflow-tests 2>&1 | tail -5
just build 2>&1 | tail -5
python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted(d))'
git status --porcelain
```

Expected: the unittest run reports `OK` with no failures; `just agent-workflow-tests` reports `OK`; `just build` succeeds; the snapshot line prints exactly `['bindings', 'capabilities', 'project', 'schema_version']`; `git status --porcelain` lists only the files this task created or modified, proving `resolve` wrote nothing.

Falsifiable gate — at the base commit `.agents/project.json` does not exist and the resolver does not, so the snapshot command fails outright:

```sh
if ! python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . >/dev/null; then exit 1; fi
if ! grep -q "resolve-project" justfile; then exit 1; fi
if ! grep -q '".agents/bin/resolve-project"' home/common/agent-skills/default.nix; then exit 1; fi
```

(The `resolve-project` TODO in the two unimplemented subcommands is expected at this task and removed by Tasks 3 and 4; do not gate on its absence here.)

- [ ] **Step 6: Commit**

```bash
git add .agents .gitignore justfile \
  home/common/agent-skills/scripts/resolve-project.py \
  home/common/agent-skills/tests/test_resolve_project.py \
  home/common/agent-skills/default.nix
git commit -m "feat(resolver): add the authored project contract and its fail-closed loader

Per D1, D5, D8, D12, D13.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
