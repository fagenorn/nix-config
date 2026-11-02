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

    def test_strict_load_refuses_input_nested_past_the_parser_depth(self):
        with self.assertRaises(vb.BlockerRefused) as caught:
            vb.strict_load(b"[" * 100000)
        self.assertTrue(str(caught.exception).startswith("input: "), str(caught.exception))

    def test_canonical_bytes_are_sorted_compact_ascii(self):
        self.assertEqual(vb.canonical_bytes({"b": [1], "a": "é"}),
                         b'{"a":"\\u00e9","b":[1]}')


if __name__ == "__main__":
    unittest.main()
