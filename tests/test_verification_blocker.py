"""The shared verification blocker's pure rules (issue 543 D2-D5), by import."""
import copy
import unittest

from agent_tools import verification_blocker as vb
from agent_tools.adopt_inspection import SECRET_MARKERS, is_secret_path

A, B = "a" * 40, "b" * 64
PINNED_ID = "sha256:f5a6f65defd6a92c5ffe9c65ddb04c2ff6ac1f91c858eff167fd4d18cb065829"
REPOSITORY = {"project_id": "fagenorn/nix-config", "integration_branch": "main"}
COMMAND = {"id": "nix-build", "argv": ["just", "build"], "cwd": ".", "env": []}
ZERO_ID = "sha256:" + "0" * 64


def fact(name="flake-lock", paths=("flake.lock",), objects=None):
    objects = [A] * len(paths) if objects is None else list(objects)
    return {"name": name, "source": {"paths": list(paths)},
            "value": {"objects": [{"path": p, "mode": None if o is None else "100644", "object": o}
                                  for p, o in zip(paths, objects)]}}


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
    paths = [f"p{m}" + "x" * (69 if m == 7 else 65) for m in range(8)]
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
                                   [{"path": "b", "mode": "100644", "object": A},
                                    {"path": "a", "mode": "100644", "object": A}]),
            "upper object": edited(failure(), ("facts", 0, "value", "objects", 0, "object"),
                                   "A" * 40),
            "short object": edited(failure(), ("facts", 0, "value", "objects", 0, "object"),
                                   "a" * 39),
            "no mode": edited(failure(), ("facts", 0, "value", "objects", 0, "mode"), KeyError),
            "null mode": edited(failure(), ("facts", 0, "value", "objects", 0, "mode"), None),
            "unknown mode": edited(failure(), ("facts", 0, "value", "objects", 0, "mode"),
                                   "100664"),
            "integer mode": edited(failure(), ("facts", 0, "value", "objects", 0, "mode"),
                                   100644),
            "mode without object": edited(failure(),
                                          ("facts", 0, "value", "objects", 0, "object"), None),
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

    def test_a_worktree_that_does_not_encode_as_utf8_is_refused(self):
        loaded = vb.strict_load(b'{"command_id": "nix-build", "failure_class": "dependency", '
                                b'"worktree": "/w/\\ud800", '
                                b'"facts": [{"name": "flake-lock", "paths": ["flake.lock"]}]}')
        self.assertEqual(loaded, declaration(worktree="/w/\ud800"))
        with self.assertRaises(vb.BlockerRefused) as refused:
            vb.normalize_declaration(loaded)
        self.assertEqual(str(refused.exception), "worktree: must encode as UTF-8")


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
                   (("facts", 0, "value", "objects", 0, "mode"), "100755"),
                   (("facts", 0, "value", "objects", 0), {"path": "flake.lock", "mode": None,
                                                          "object": None}))
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


def record(value=None, attempts=((61, 1),), state="open", resolution=None):
    """The schema-11 record `park` writes for `value` (issue 544 D3)."""
    value = failure() if value is None else value
    return {"id": vb.blocker_id(value), "repository": copy.deepcopy(value["repository"]),
            "command": copy.deepcopy(value["command"]),
            "failure_class": value["failure_class"], "facts": copy.deepcopy(value["facts"]),
            "attempts": [{"issue": issue, "attempt": number} for issue, number in attempts],
            "state": state, "resolution": resolution}


def changed_facts(value=None, objects=(B,)):
    """The record's facts with the one path's object replaced: a resolution's facts."""
    value = failure() if value is None else value
    facts = copy.deepcopy(value["facts"])
    for entry, object_id in zip(facts[0]["value"]["objects"], objects):
        entry["object"] = object_id
    return facts


class ParkTest(unittest.TestCase):
    def test_park_creates_then_joins_keeping_history_once(self):
        blockers = {}
        identity = vb.park(blockers, failure(), 62, 1)
        self.assertEqual(identity, PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record(attempts=((62, 1),))})
        self.assertEqual(vb.park(blockers, failure(), 61, 2), PINNED_ID)
        self.assertEqual(vb.park(blockers, failure(), 62, 1), PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record(attempts=((61, 2), (62, 1)))})
        other = failure(failure_class="environment")
        self.assertEqual(vb.park(blockers, other, 61, 2), vb.blocker_id(other))
        self.assertEqual(sorted(blockers), sorted([PINNED_ID, vb.blocker_id(other)]))

    def test_park_reopens_a_resolved_record_and_never_rewrites_content(self):
        blockers = {PINNED_ID: record(state="resolved",
                                      resolution={"facts": changed_facts()})}
        self.assertEqual(vb.park(blockers, failure(), 61, 1), PINNED_ID)
        self.assertEqual(blockers, {PINNED_ID: record()})

    def test_park_copies_the_failure_and_touches_only_the_map(self):
        value, blockers = failure(), {}
        before = copy.deepcopy(value)
        vb.park(blockers, value, 61, 1)
        self.assertEqual(value, before)
        blockers[PINNED_ID]["facts"][0]["name"] = "changed"
        self.assertEqual(value, before)

    def test_park_refuses_a_bad_reference_or_failure_and_writes_nothing(self):
        for issue, number, field in ((0, 1, "issue"), (True, 1, "issue"), ("61", 1, "issue"),
                                     (61, 0, "attempt"), (61, False, "attempt")):
            blockers = {}
            with self.subTest(issue=issue, attempt=number), \
                    self.assertRaises(vb.BlockerRefused) as caught:
                vb.park(blockers, failure(), issue, number)
            self.assertEqual(str(caught.exception), f"{field}: must be a positive integer")
            self.assertEqual(blockers, {})
        blockers = {}
        with self.assertRaises(vb.BlockerRefused):
            vb.park(blockers, failure(failure_class="product"), 61, 1)
        self.assertEqual(blockers, {})


class RecordRulesTest(unittest.TestCase):
    POINTERS = {(61, 1): PINNED_ID, (62, 1): None, (62, 2): None}

    def assert_refused(self, blockers, pointers, prefix):
        with self.assertRaises(vb.BlockerRefused) as caught:
            vb.validate_blockers(blockers, pointers)
        self.assertTrue(str(caught.exception).startswith(prefix), str(caught.exception))
        self.assertNotIn("\n", str(caught.exception))

    def test_valid_maps_pass(self):
        resolved = record(attempts=((61, 1), (62, 2)), state="resolved",
                          resolution={"facts": changed_facts()})
        for blockers in ({PINNED_ID: record()}, {PINNED_ID: resolved}):
            with self.subTest(blockers=str(blockers)[:40]):
                self.assertIsNone(vb.validate_blockers(blockers, self.POINTERS))
        self.assertIsNone(vb.validate_blockers({}, {(61, 1): None}))
        # A record outlives its attempts' parking: R3 keeps the history (issue 544 D3).
        self.assertIsNone(vb.validate_blockers({PINNED_ID: record()}, {(61, 1): None}))

    def test_each_rule_refuses(self):
        key = f"verification_blockers[{PINNED_ID}]"
        secret = failure(facts=[fact(paths=(".env",))])
        secret_record = {**record(), "facts": secret["facts"]}
        moved = changed_facts()
        moved[0]["source"]["paths"] = ["other.lock"]
        moved[0]["value"]["objects"][0]["path"] = "other.lock"
        cases = {
            "R1 not an object": ([], self.POINTERS, "verification_blockers: must be an object"),
            "R1 key is not the id": ({ZERO_ID: record()}, {(61, 1): ZERO_ID},
                                     f"verification_blockers[{ZERO_ID}].id"),
            "R1 id is not the content": ({PINNED_ID: {**record(), "failure_class": "environment"}},
                                         self.POINTERS, f"{key}.id"),
            "R1 secret-shaped content": ({PINNED_ID: secret_record}, self.POINTERS,
                                         f"{key}: facts[0].source.paths[0]: secret-shaped"),
            "R1 oversized content": ({PINNED_ID: {**record(), "facts": sized("flake-lockx")["facts"]}},
                                     self.POINTERS, f"{key}: failure: longer than 2048"),
            "R2 unknown member": ({PINNED_ID: {**record(), "note": "x"}}, self.POINTERS,
                                  f"{key}: missing [], unknown ['note']"),
            "R2 missing member": ({PINNED_ID: edited(record(), ("resolution",), KeyError)},
                                  self.POINTERS, f"{key}: missing ['resolution']"),
            "R3 empty attempts": ({PINNED_ID: record(attempts=())}, {}, f"{key}.attempts"),
            "R3 boolean attempt": ({PINNED_ID: edited(record(), ("attempts", 0, "attempt"), True)},
                                   self.POINTERS, f"{key}.attempts[0].attempt"),
            "R3 open reference": ({PINNED_ID: edited(record(), ("attempts", 0, "note"), 1)},
                                  self.POINTERS, f"{key}.attempts[0]"),
            "R3 unsorted": ({PINNED_ID: record(attempts=((62, 1), (61, 1)))}, self.POINTERS,
                            f"{key}.attempts"),
            "R3 repeated": ({PINNED_ID: record(attempts=((61, 1), (61, 1)))}, self.POINTERS,
                            f"{key}.attempts"),
            "R3 not of this run": ({PINNED_ID: record(attempts=((61, 1), (63, 1)))},
                                   self.POINTERS, f"{key}.attempts[1]"),
            "R4 unknown state": ({PINNED_ID: record(state="closed")}, self.POINTERS,
                                 f"{key}.state"),
            "R4 open with a resolution": ({PINNED_ID: record(resolution={"facts": changed_facts()})},
                                          self.POINTERS, f"{key}.resolution"),
            "R4 resolved without one": ({PINNED_ID: record(state="resolved")}, self.POINTERS,
                                        f"{key}.resolution"),
            "R4 open resolution object": ({PINNED_ID: record(
                state="resolved", resolution={"facts": changed_facts(), "note": 1})},
                self.POINTERS, f"{key}.resolution"),
            "R4 invalid resolved facts": ({PINNED_ID: record(
                state="resolved", resolution={"facts": changed_facts(objects=("x",))})},
                self.POINTERS, f"{key}.resolution.facts"),
            "R4 substituted source": ({PINNED_ID: record(
                state="resolved", resolution={"facts": moved})}, self.POINTERS,
                f"{key}.resolution.facts"),
            "R4 nothing changed": ({PINNED_ID: record(
                state="resolved", resolution={"facts": copy.deepcopy(failure()["facts"])})},
                self.POINTERS, f"{key}.resolution.facts"),
            "R5 pointer to no record": ({}, self.POINTERS, "verification_blockers: attempt 61:1"),
            "R5 pointer to a record without it": ({PINNED_ID: record(attempts=((62, 1),))},
                                                  self.POINTERS,
                                                  "verification_blockers: attempt 61:1"),
            "a key with a newline": ({"a\nb": record()}, self.POINTERS,
                                     "verification_blockers[a\\nb].id: must equal its key"),
            "a pointer with a newline": ({}, {(61, 1): "x\ny"},
                                         "verification_blockers: attempt 61:1 points at x\\ny"),
            "a list pointer": ({}, {(61, 1): ["x"]},
                               'verification_blockers: attempt 61:1 points at ["x"]'),
            "a dict pointer": ({}, {(61, 1): {"a": 1}},
                               'verification_blockers: attempt 61:1 points at {"a": 1}'),
        }
        for label, (blockers, pointers, prefix) in cases.items():
            with self.subTest(case=label):
                self.assert_refused(blockers, pointers, prefix)


class UpgradeTenTest(unittest.TestCase):
    def ten(self):
        attempt = {"issue": 61, "attempt": 1, "state": "active", "blocked_on": None}
        return {"schema_version": 10, "run_id": "r", "transaction_id": "t",
                "issues": {"61": {"issue": 61, "attempts": [attempt, dict(attempt, attempt=2)]},
                           "62": {"issue": 62, "attempts": []}}}

    def test_the_step_adds_both_members_and_mutates_nothing(self):
        document = self.ten()
        before = copy.deepcopy(document)
        upgraded = vb.upgrade_ten(document)
        self.assertEqual(document, before)
        expected = copy.deepcopy(before)
        expected.update(schema_version=11, verification_blockers={})
        for attempt in expected["issues"]["61"]["attempts"]:
            attempt["verification_blocker"] = None
        self.assertEqual(upgraded, expected)
        upgraded["issues"]["61"]["attempts"][0]["state"] = "changed"
        self.assertEqual(document, before)

    def test_a_present_member_or_another_schema_is_refused(self):
        document = self.ten()
        pointed = copy.deepcopy(document)
        pointed["issues"]["61"]["attempts"][1]["verification_blocker"] = None
        cases = (
            ("verification_blockers: present before schema 11",
             {**document, "verification_blockers": {}}),
            ("issues[61].attempts[1].verification_blocker: present before schema 11", pointed),
            ("schema_version: must be 10", {**document, "schema_version": 11}),
            ("schema_version: must be 10", {**document, "schema_version": True}),
            ("issues: must be an object", {**document, "issues": []}),
            ("issues[6\\n1]: must be an object with an attempts list",
             {**document, "issues": {"6\n1": []}}),
        )
        for message, value in cases:
            before = copy.deepcopy(value)
            with self.subTest(message=message), self.assertRaises(vb.BlockerRefused) as caught:
                vb.upgrade_ten(value)
            self.assertEqual(str(caught.exception), message)
            self.assertEqual(value, before)
        with self.assertRaises(vb.BlockerRefused):
            vb.upgrade_ten([])


if __name__ == "__main__":
    unittest.main()
