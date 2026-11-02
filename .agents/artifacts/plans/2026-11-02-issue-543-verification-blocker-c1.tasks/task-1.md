# Task 1: Pure verification blocker module

**Files:**
- Create: `python/agent_tools/verification_blocker.py`
- Create: `tests/test_verification_blocker.py`
- Modify: `justfile` (one line, `    tests/test_verification_blocker.py \`, in the `agent-workflow-tests` list right after `    tests/test_verified_tree.py \`)

**Interfaces:**
- Consumes: `agent_tools.canonical.telemetry_digest(body) -> str`, `reject_duplicate_keys` and `reject_nonfinite_literal` (agent-helpers rule 4). The test reads `agent_tools.adopt_inspection.SECRET_MARKERS` and `is_secret_path`; nothing in `adopt_inspection` changes.
- Produces (Task 2 and the later children c2–c4 import these exact names):
  - `SCHEMA_VERSION = 1`, `FAILURE_KIND = "verification-failure"`, `OBSERVATION_KIND = "verification-observation"`, `REQUIREMENT_KIND = "verification"`, `FAILURE_CLASSES = ("command_input", "dependency", "environment", "external_service")`, `MAX_FACTS = 4`, `MAX_PATHS = 8`, `MAX_PATH_BYTES = 255`, `MAX_FAILURE_BYTES = 2048`.
  - `class BlockerRefused(ValueError)`: one line, `<field>: <reason>`.
  - `strict_load(raw: bytes) -> object`; `canonical_bytes(value: object) -> bytes`; `secret_shaped(name: str) -> bool`.
  - `normalize_declaration(value: object) -> dict`: a new dict `{"command_id", "failure_class", "worktree", "facts": [{"name", "paths"}]}` with facts sorted by name and each fact's paths sorted.
  - `validate_failure(value: object) -> dict`, `validate_observation(value: object) -> dict`, `validate_requirement(value: object) -> dict`: each returns `value` itself, never a copy, and never mutates it.
  - `blocker_id(failure: object) -> str`.

**Invariants:**
- Pure: the module imports only `json`, `re`, `unicodedata` and `agent_tools.canonical`, and touches no file, clock, process, network or environment variable (D1, D15).
- The members, limits and path rules are exactly spec § Wire objects (D2); the secret-shape rule is exactly spec § Secret-shape rule (D4); normalization and identity are spec § Normalization and identity (D3, D5).
- Refusal reasons that Task 2's tests read through stderr: an absent or other `failure_class` is exactly `failure_class: unclassified`; a secret-shaped fact name or path ends `: secret-shaped`; an object with a missing or unknown member names both lists, as `<field>: missing [...], unknown [...]`; a `strict_load` refusal starts `input: `.
- `blocker_id` validates its argument first, so an invalid failure never gets an id.

- [ ] **Step 1: Write the failing tests** in `tests/test_verification_blocker.py`

```python
"""The shared verification blocker's pure rules (issue 543 D2-D5), by import."""
import copy
import unittest

from agent_tools import verification_blocker as vb
from agent_tools.adopt_inspection import SECRET_MARKERS, is_secret_path

A, B = "a" * 40, "b" * 64
PINNED_ID = "sha256:2d494bb295c987db9c15f1b652122d180aed8f64dcd3e76b46eaa13852a91cfa"
REPOSITORY = {"project_id": "fagenorn/nix-config", "integration_branch": "main"}
COMMAND = {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []}
ZERO_ID = "sha256:" + "0" * 64


def fact(name="flake-lock", paths=("flake.lock",), objects=None):
    objects = [A] * len(paths) if objects is None else list(objects)
    return {"name": name, "source": {"paths": list(paths)},
            "value": {"objects": [{"path": p, "object": o} for p, o in zip(paths, objects)]}}


def failure(**changes):
    value = {"kind": "verification-failure", "schema_version": 1,
             "repository": dict(REPOSITORY), "command": copy.deepcopy(COMMAND),
             "failure_class": "dependency", "facts": [fact()]}
    value.update(changes)
    return value


def observation(**changes):
    value = {"kind": "verification-observation", "schema_version": 1, "blocker_id": ZERO_ID,
             "repository": dict(REPOSITORY), "facts": [fact()]}
    value.update(changes)
    return value


def requirement(**changes):
    value = {"kind": "verification", "blocker_id": ZERO_ID,
             "sources": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
    value.update(changes)
    return value


def declaration(**changes):
    value = {"command_id": "nix-build", "failure_class": "dependency", "worktree": "/w/x",
             "facts": [{"name": "flake-lock", "paths": ["flake.lock"]}]}
    value.update(changes)
    return value


def edited(value, path, member):
    """A deep copy of `value` with the member at `path` replaced, or deleted for KeyError."""
    value = copy.deepcopy(value)
    target = value
    for key in path[:-1]:
        target = target[key]
    if member is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = member
    return value


def sized(name):
    """A failure of one fact and eight padded paths: 2,048 canonical bytes for
    `flake-lock`, one byte more for `flake-lockx`."""
    paths = [f"p{m}" + "x" * (77 if m == 7 else 73) for m in range(8)]
    return failure(facts=[fact(name=name, paths=paths)])


class ShapeTest(unittest.TestCase):
    def test_the_three_canonical_objects_validate_as_themselves(self):
        for validate, value in ((vb.validate_failure, failure()),
                                (vb.validate_observation, observation()),
                                (vb.validate_requirement, requirement())):
            with self.subTest(kind=value["kind"]):
                self.assertIs(validate(value), value)
        nulls = fact(paths=("a", "b"), objects=(None, B))
        self.assertIs(vb.validate_failure(failure(facts=[nulls]))["facts"][0], nulls)

    def test_malformed_failures_are_refused(self):
        cases = {
            "unknown member": edited(failure(), ("note",), "x"),
            "missing member": edited(failure(), ("command",), KeyError),
            "boolean version": failure(schema_version=True),
            "other version": failure(schema_version=2),
            "other kind": failure(kind="verification-observation"),
            "unclassified": failure(failure_class="product"),
            "no class": edited(failure(), ("failure_class",), KeyError),
            "empty project": edited(failure(), ("repository", "project_id"), ""),
            "spaced branch": edited(failure(), ("repository", "integration_branch"), "ma in"),
            "long branch": edited(failure(), ("repository", "integration_branch"), "b" * 256),
            "empty argv": edited(failure(), ("command", "argv"), []),
            "empty word": edited(failure(), ("command", "argv"), ["just", ""]),
            "absolute cwd": edited(failure(), ("command", "cwd"), "/repo"),
            "dotted cwd": edited(failure(), ("command", "cwd"), "./sub"),
            "env value": edited(failure(), ("command", "env"), ["NAME=value"]),
            "repeated env": edited(failure(), ("command", "env"), ["HOME", "HOME"]),
            "no facts": failure(facts=[]),
            "five facts": failure(facts=[fact(name=f"f{n}", paths=(f"p{n}",)) for n in range(5)]),
            "unsorted facts": failure(facts=[fact(name="b", paths=("b",)),
                                             fact(name="a", paths=("a",))]),
            "duplicate fact": failure(facts=[fact(), fact(paths=("other",))]),
            "upper name": failure(facts=[fact(name="Flake")]),
            "no paths": failure(facts=[fact(paths=())]),
            "nine paths": failure(facts=[fact(paths=[f"p{n}" for n in range(9)])]),
            "unsorted paths": failure(facts=[fact(paths=("b", "a"))]),
            "repeated path": failure(facts=[fact(paths=("a", "a"))]),
            "cross-fact path": failure(facts=[fact(name="a", paths=("x",)),
                                              fact(name="b", paths=("x",))]),
            "object order": edited(failure(facts=[fact(paths=("a", "b"))]),
                                   ("facts", 0, "value", "objects"),
                                   [{"path": "b", "object": A}, {"path": "a", "object": A}]),
            "upper object": edited(failure(), ("facts", 0, "value", "objects", 0, "object"),
                                   "A" * 40),
            "short object": edited(failure(), ("facts", 0, "value", "objects", 0, "object"),
                                   "a" * 39),
            "oversized": sized("flake-lockx"),
        }
        for label, value in cases.items():
            with self.subTest(case=label), self.assertRaises(vb.BlockerRefused):
                vb.validate_failure(value)

    def test_only_the_failure_carries_the_byte_bound(self):
        self.assertEqual(len(vb.canonical_bytes(sized("flake-lock"))), 2048)
        self.assertEqual(len(vb.canonical_bytes(sized("flake-lockx"))), 2049)
        vb.validate_failure(sized("flake-lock"))
        facts = sized("flake-lockx")["facts"]
        self.assertIs(vb.validate_observation(observation(facts=facts))["facts"], facts)

    def test_bad_paths_are_refused_in_every_shape(self):
        bad = ("", "/flake.lock", "flake.lock/", "a\\b", "a//b", "./a", "a/./b", "../a",
               "a/..", ".git/config", "sub/.GIT", "a\x01b", "a\x7fb", "x" * 256,
               "\ud800")
        for path in bad:
            with self.subTest(path=path):
                with self.assertRaises(vb.BlockerRefused):
                    vb.validate_failure(failure(facts=[fact(paths=(path,))]))
                with self.assertRaises(vb.BlockerRefused):
                    vb.validate_observation(observation(facts=[fact(paths=(path,))]))
                with self.assertRaises(vb.BlockerRefused):
                    vb.validate_requirement(requirement(sources=[
                        {"name": "flake-lock", "paths": [path]}]))
                with self.assertRaises(vb.BlockerRefused):
                    vb.normalize_declaration(declaration(facts=[
                        {"name": "flake-lock", "paths": [path]}]))
        long_ok = "d/" + "x" * 253
        self.assertEqual(len(long_ok.encode()), 255)
        vb.validate_failure(failure(facts=[fact(paths=(long_ok,))]))

    def test_malformed_observations_and_requirements_are_refused(self):
        observations = {
            "unknown member": observation(command=COMMAND),
            "other kind": observation(kind="verification-failure"),
            "boolean version": observation(schema_version=True),
            "bad id": observation(blocker_id="sha256:" + "A" * 64),
            "no facts": observation(facts=[]),
        }
        for label, value in observations.items():
            with self.subTest(observation=label), self.assertRaises(vb.BlockerRefused):
                vb.validate_observation(value)
        requirements = {
            "versioned": requirement(schema_version=1),
            "other kind": requirement(kind="verification-observation"),
            "short id": requirement(blocker_id="sha256:" + "0" * 63),
            "valued source": requirement(sources=[fact()]),
            "unsorted": requirement(sources=[{"name": "b", "paths": ["b"]},
                                             {"name": "a", "paths": ["a"]}]),
            "cross-fact path": requirement(sources=[{"name": "a", "paths": ["x"]},
                                                    {"name": "b", "paths": ["x"]}]),
        }
        for label, value in requirements.items():
            with self.subTest(requirement=label), self.assertRaises(vb.BlockerRefused):
                vb.validate_requirement(value)


class SecretShapeTest(unittest.TestCase):
    def test_every_clause_refuses_names_and_components(self):
        shaped = (".env", ".ENV.local", "private", "Private", "my-secret", "SECRETS.yaml",
                  "auth-token", "Password.txt", "passwd", "credentials", "aws-credential",
                  "private-key", "private_key", "api-key", "API_KEY", "apikey", "server.pem",
                  "tls.KEY", "cert.p12", "cert.pfx", "id_rsa", "id_ecdsa.pub",
                  "id_ed25519_sk")
        for name in shaped:
            with self.subTest(name=name):
                self.assertTrue(vb.secret_shaped(name))
                with self.assertRaises(vb.BlockerRefused) as refused:
                    vb.validate_failure(failure(facts=[fact(paths=(f"config/{name}/x",))]))
                self.assertIn("secret-shaped", str(refused.exception))
        for name in ("flake.lock", "privacy.md", "keys.txt", "environment", "README.md"):
            with self.subTest(name=name):
                self.assertFalse(vb.secret_shaped(name))
        for name in ("my-secret", "api-key", "private"):
            with self.subTest(fact_name=name), self.assertRaises(vb.BlockerRefused):
                vb.validate_requirement(requirement(sources=[{"name": name, "paths": ["a"]}]))

    def test_the_rule_covers_every_path_adoption_calls_secret(self):
        paths = [f"a/{marker}/b" for marker in SECRET_MARKERS]
        paths += [".env", "a/.env.production", "secrets/secrets.yaml"]
        for path in paths:
            with self.subTest(path=path):
                self.assertTrue(is_secret_path(path))
                with self.assertRaises(vb.BlockerRefused):
                    vb.validate_failure(failure(facts=[fact(paths=(path,))]))

    def test_command_env_names_are_not_judged(self):
        value = edited(failure(), ("command", "env"), ["GITHUB_TOKEN", "API_KEY"])
        self.assertIs(vb.validate_failure(value), value)


class DeclarationTest(unittest.TestCase):
    def test_order_is_normalized_and_nothing_else(self):
        given = declaration(facts=[{"name": "nixpkgs", "paths": ["pkgs/b", "pkgs/a"]},
                                   {"name": "flake-lock", "paths": ["flake.lock"]}])
        expected = {"command_id": "nix-build", "failure_class": "dependency",
                    "worktree": "/w/x",
                    "facts": [{"name": "flake-lock", "paths": ["flake.lock"]},
                              {"name": "nixpkgs", "paths": ["pkgs/a", "pkgs/b"]}]}
        self.assertEqual(vb.normalize_declaration(given), expected)
        sources = {"kind": "verification", "blocker_id": ZERO_ID,
                   "sources": expected["facts"]}
        self.assertIs(vb.validate_requirement(sources), sources)

    def test_malformed_declarations_are_refused(self):
        cases = {
            "unclassified": declaration(failure_class="flaky"),
            "no class": edited(declaration(), ("failure_class",), KeyError),
            "unknown member": declaration(note="x"),
            "relative worktree": declaration(worktree="wt"),
            "empty command": declaration(command_id=""),
            "repeated name": declaration(facts=[{"name": "a", "paths": ["x"]},
                                                {"name": "a", "paths": ["y"]}]),
            "repeated path": declaration(facts=[{"name": "a", "paths": ["x", "x"]}]),
            "cross-fact path": declaration(facts=[{"name": "a", "paths": ["x"]},
                                                  {"name": "b", "paths": ["x"]}]),
            "secret": declaration(facts=[{"name": "env", "paths": [".env"]}]),
            "valued fact": declaration(facts=[fact()]),
        }
        for label, value in cases.items():
            with self.subTest(case=label), self.assertRaises(vb.BlockerRefused):
                vb.normalize_declaration(value)
        with self.assertRaises(vb.BlockerRefused) as refused:
            vb.normalize_declaration(edited(declaration(), ("failure_class",), KeyError))
        self.assertEqual(str(refused.exception), "failure_class: unclassified")


class IdentityTest(unittest.TestCase):
    def test_the_identity_is_the_content(self):
        value = failure()
        self.assertEqual(vb.blocker_id(value), PINNED_ID)
        reordered = dict(reversed(list(copy.deepcopy(value).items())))
        self.assertEqual(vb.blocker_id(reordered), PINNED_ID)
        changes = ((("repository", "project_id"), "fagenorn/other"),
                   (("repository", "integration_branch"), "release"),
                   (("command", "id"), "agent-workflow-tests"),
                   (("command", "argv"), ["just", "build", "mbp"]),
                   (("command", "cwd"), "sub"),
                   (("command", "env"), ["HOME"]),
                   (("failure_class",), "environment"),
                   (("facts", 0, "name"), "lock"),
                   (("facts", 0, "value", "objects", 0, "object"), None))
        seen = {PINNED_ID}
        for path, member in changes:
            with self.subTest(path=path):
                changed = vb.blocker_id(edited(value, path, member))
                self.assertNotIn(changed, seen)
                seen.add(changed)

    def test_an_invalid_failure_gets_no_identity(self):
        for value in (failure(failure_class="product"), failure(schema_version=True),
                      sized("flake-lockx")):
            with self.subTest(value=str(value)[:60]), self.assertRaises(vb.BlockerRefused):
                vb.blocker_id(value)


class LoadTest(unittest.TestCase):
    def test_strict_load_refuses_duplicates_non_finite_and_bad_bytes(self):
        self.assertEqual(vb.strict_load(b'{"a": [1, "\\u00e9"]}'), {"a": [1, "é"]})
        for raw in (b'{"a": 1, "a": 2}', b'{"a": NaN}', b'[Infinity]', b"\xff", b"{"):
            with self.subTest(raw=raw), self.assertRaises(vb.BlockerRefused):
                vb.strict_load(raw)

    def test_canonical_bytes_are_sorted_compact_ascii(self):
        self.assertEqual(vb.canonical_bytes({"b": [1], "a": "é"}),
                         b'{"a":"\\u00e9","b":[1]}')


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests and watch them fail**

Run (timeout 300 s): `bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest tests/test_verification_blocker.py 2>&1 | tail -4'`
Expected: `FAILED (errors=1)`, the import error naming `agent_tools.verification_blocker`.

- [ ] **Step 3: Write the module**

The module docstring says it is pure and lists what it is the one home of (D1); it names no adapter, because none exists at this commit. Decisions the tests pin:

- **Closed objects.** A non-dict refuses `<label>: must be an object`; a dict whose keys differ from the closed set refuses `<label>: missing [<sorted absent>], unknown [<sorted extra>]`. `schema_version` passes only when `type(value) is int` and it equals `SCHEMA_VERSION`, so `True` refuses. `kind` must equal the shape's constant. The requirement's closed set is `{blocker_id, kind, sources}`: it has no `schema_version`.
- **`repository`.** `project_id` and `integration_branch` are non-empty strings that encode as UTF-8 in at most 255 bytes and hold no `Cc`-category character and no `str.isspace()` character.
- **`command`.** `id` a non-empty string; `argv` a non-empty list of non-empty strings; `cwd` either `"."` or a spelling that passes the structural path rule below; `env` a list of strings that each fully match the module's own `[A-Za-z_][A-Za-z0-9_]*` with no repeat (order is not judged). The secret-shape rule never reads `command` (D4).
- **Structural path rule** (paths and `cwd`): refuse a leading or trailing `/` or any backslash, an empty, `.` or `..` segment, and any character whose `unicodedata.category` is `Cc` (C0, DEL and C1).
- **Selected paths** add, in this order: non-empty string; `path.encode("utf-8")` raising `UnicodeEncodeError` refuses (a lone surrogate); more than `MAX_PATH_BYTES` encoded bytes refuses; the structural rule; a component whose `.lower()` is `.git` refuses; a secret-shaped component refuses with reason `secret-shaped`. A fact's `paths` list holds 1–`MAX_PATHS` items and must be strictly increasing under Python string order (sorted and unique).
- **Facts.** 1–`MAX_FACTS` items; `name` must `re.fullmatch` `[a-z0-9][a-z0-9-]{0,63}` and not be secret-shaped; names strictly increasing; no path in two facts. A valued fact (failure and observation) is closed `{name, source: {paths}, value: {objects}}`, where `objects` has exactly one closed `{path, object}` per path, its `path` equal to the source path at the same index, and `object` either `None` or a string that fully matches `[0-9a-f]{40}|[0-9a-f]{64}`. A requirement's `sources` items are closed `{name, paths}` under the same name and path rules.
- **`blocker_id`** members fully match `sha256:[0-9a-f]{64}`.
- **Size.** `validate_failure` checks `len(canonical_bytes(value)) <= MAX_FAILURE_BYTES` last; `validate_observation` and `validate_requirement` carry no byte bound (D2).
- **`secret_shaped(name)`**, on `name.lower()`: equal to `private`; or starts with `.env`, `id_rsa`, `id_ecdsa` or `id_ed25519`; or ends with `.pem`, `.key`, `.p12` or `.pfx`; or contains `secret`, `token`, `password`, `passwd`, `credential`, `private-key`, `private_key`, `api-key`, `api_key` or `apikey`.
- **`normalize_declaration`**: a dict without `failure_class` refuses `failure_class: unclassified` before the closed check; then closed `{command_id, facts, failure_class, worktree}`; `command_id` a non-empty string; `failure_class` in `FAILURE_CLASSES`; `worktree` a non-empty string starting `/` with no `Cc` character; 1–`MAX_FACTS` closed `{name, paths}` facts whose paths pass the selected-path rule and are then sorted (a repeat still refuses) and whose list is sorted by name, then the name and cross-fact rules apply. Spelling is never rewritten (D5).
- **`strict_load`** decodes UTF-8 and calls `json.loads` with both canonical hooks; `UnicodeError` or `ValueError` becomes `BlockerRefused(f"input: {error}")`.
- **`canonical_bytes`** is `json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")`.
- **`blocker_id(failure)`** calls `validate_failure(failure)`, then returns `telemetry_digest` of the dict of exactly `command`, `failure_class`, `facts` and `repository` (D3).

Add the `justfile` line named under **Files**.

- [ ] **Step 4: Verify**

Run (timeout 300 s): the Step 2 command.
Expected: `Ran 14 tests` and `OK`.

Run: `if grep -nE '^(import|from) ' python/agent_tools/verification_blocker.py | grep -vE '^[0-9]+:(import (json|re|unicodedata)$|from agent_tools\.canonical import )'; then exit 1; fi`
Expected: no output, exit 0 (no import beyond D15's).

Run: `grep -c '^    tests/test_verification_blocker.py \\$' justfile`
Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/verification_blocker.py tests/test_verification_blocker.py justfile
launch-commit … -- -m "feat(verification): add the pure blocker module (issue 543)" -m "<session trailers>"
```

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":450,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["r1a"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1a","last_task":1,"owner":1,"path":"python/agent_tools/verification_blocker.py"},{"bounds":[{"added_lines":420,"boundary":"all","deleted_lines":0,"record_bytes":22528,"support":{"covers":["r1b"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1b","last_task":1,"owner":1,"path":"tests/test_verification_blocker.py"},{"bounds":[{"added_lines":1,"boundary":"all","deleted_lines":0,"record_bytes":2048,"support":{"covers":["r1c"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r1c","last_task":2,"owner":1,"path":"justfile"}]}}
```
