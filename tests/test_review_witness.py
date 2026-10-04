"""Retained bundle contract: tool closure, witness, anchor and validation (issue 249; RP2, RP3, RP7, RP16)."""
import copy, hashlib, json, os, shutil, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import PACKING_POLICY_SHA256, RECORD_POLICY_SHA256
from agent_tools.review_budget import describe
from agent_tools.review_forecast import _derivation, canonical_bytes, raw_digest
from agent_tools.review_issue100 import Issue100Error, derive_100, verify_archive
from agent_tools.review_issue121 import derive_121, unavailable_ids
from agent_tools.review_task7 import EstimateError, derive_task7
from agent_tools.review_witness import (ANCHOR_MAX_BYTES, ANCHOR_NAME, MEMBER_MAX_BYTES, PAYLOAD_NAMES, WitnessError,
                                        authenticate, build_anchor, build_witness, tool_closure, validate_bundle,
                                        verify_running_closure)

from .retained_review_test_support import (SOURCE, commit_files, git, init_repo, retained_fixture, source_budget_env,
                                           tool_fixture)

FIXTURES = ("issue-100-derived.json", "issue-121.json", "task7-estimate.json")
WITNESS = "derivation-witness.json"
# The members the pins alone determine (the task's component table), by group.
PINNED = {"tool": ("packing_policy_sha256", "record_policy_sha256"),
          "issue_121": ("base", "head", "tree", "signer_sha256"),
          "issue_100": ("base", "head", "live", "parent_edges_sha256"),
          "archive": ("producer_sha256", "manifest_sha256"),
          "estimate": ("prerequisite_commit", "prerequisite_tree", "plan_root_blob", "task7_blob", "model_version")}
CODES = ("tool_closure", "anchor_unreadable", "anchor_shape", "anchor_digest", "expected_digest", "member_set",
         "member_digest", "member_noncanonical", "witness_shape", "component_mismatch", "table_mismatch",
         "policy_mismatch")


def derived(tmp, **shape):
    """Components, fixture payloads and pins, assembled the way derivation assembles them."""
    repo121, repo100, archive, pins = retained_fixture(tmp, **shape)
    task7, p121, p100 = pins
    with patch.dict(os.environ, source_budget_env(tmp), clear=True):
        authority = describe("review-package")
    table = derive_task7(repo121, task7)
    payloads = {"task7-estimate.json": table, "issue-121.json": derive_121(repo121, p121, task7, authority),
                "issue-100-derived.json": derive_100(repo100, repo100, archive, p100, authority.limits)}
    components = {
        "tool": {**tool_closure(*tool_fixture(tmp)), "artifact_policy_sha256": authority.policy_sha256,
                 "packing_policy_sha256": PACKING_POLICY_SHA256, "record_policy_sha256": RECORD_POLICY_SHA256},
        "issue_121": {"base": p121.base, "head": p121.head, "tree": task7.prerequisite_tree,
                      "signer_sha256": raw_digest(p121.allowed_signer)},
        "issue_100": {"base": p100.base, "head": p100.head, "live": p100.live,
                      "parent_edges_sha256": p100.parent_edges_sha256},
        "archive": verify_archive(archive, repo100, p100),
        "estimate": {"prerequisite_commit": task7.prerequisite_commit, "prerequisite_tree": task7.prerequisite_tree,
                     "plan_root_blob": task7.plan_root_blob, "task7_blob": task7.task7_blob,
                     "model_version": task7.model_version, "table_sha256": telemetry_digest(table)}}
    return components, payloads, pins


def bound(components, payloads):
    """`(anchor, raw)` with every in-bundle digest recomputed: the test-only trust injection."""
    components = {**components, "estimate": {**components["estimate"],
                                             "table_sha256": telemetry_digest(payloads["task7-estimate.json"])}}
    raw = {name: canonical_bytes(payloads[name]) for name in FIXTURES}
    raw["derivation-witness.json"] = canonical_bytes(build_witness(components, payloads, raw))
    return build_anchor(components, raw), raw


def flip(text):
    """`text` with its last character changed, so a digest or an identity keeps its form."""
    return text[:-1] + ("1" if text[-1] == "0" else "0")


def row(raw, name):
    return {"path": name, "bytes": len(raw[name]), "raw_sha256": hashlib.sha256(raw[name]).hexdigest()}


class WitnessTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp()); cls.addClassCleanup(shutil.rmtree, cls.root)
        cls.components, cls.payloads, cls.pins = derived(cls.root, owners=(1, 2, 3, 6, 3), touches={4: 3})

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)
        self.dir = self.tmp / "bundle"; self.dir.mkdir()
        self.anchor, self.raw = bound(self.components, self.payloads)
        self.expected = self.write(self.anchor, self.raw)

    def write(self, anchor, raw=None) -> str:
        """Write the canonical anchor, and any members given, into `self.dir`; the anchor's digest."""
        for name, data in (raw or {}).items():
            (self.dir / name).write_bytes(data)
        (self.dir / ANCHOR_NAME).write_bytes(canonical_bytes(anchor))
        return telemetry_digest(anchor)

    def kwargs(self):
        return dict(zip(("task7_pins", "issue121_pins", "issue100_pins"), self.pins))

    def refused(self, code, call, *args, **kwargs):
        with self.assertRaises(WitnessError) as caught:
            call(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def rewitnessed(self, witness):
        """`(anchor, raw)` around a replaced witness, with the anchor rebuilt over it."""
        raw = {**self.raw, WITNESS: canonical_bytes(witness)}
        return build_anchor(self.components, raw), raw

    def test_error_codes_are_the_closed_twelve(self):
        self.assertEqual([WitnessError(code).code for code in CODES], list(CODES))
        with self.assertRaises(ValueError):
            WitnessError("invalid_payload")

    def test_member_bytes_are_bound_before_decode(self):
        (self.dir / "issue-121.json").write_bytes(b"{not json")
        with self.assertRaises(WitnessError) as caught:
            authenticate(self.dir, self.expected)
        self.assertEqual(caught.exception.code, "member_digest")

    def test_core_loader_accepts_a_committed_bundle(self):
        repo = init_repo(self.tmp / "committed")
        head = commit_files(repo, {f"fx/{p.name}": p.read_bytes() for p in self.dir.iterdir()}, "bundle")
        self.assertIsNone(_derivation(repo, head, {"kind": "retained-anchor/v2", "path": "fx/" + ANCHOR_NAME,
                                                   "anchor_sha256": self.expected}))

    def test_malformed_sibling_beside_an_unavailable_outcome_is_invalid(self):
        control = validate_bundle(*authenticate(self.dir, self.expected), **self.kwargs())
        self.assertEqual(unavailable_ids(control["issue-121.json"]), ("tasks-1-3", "tasks-4-6"))
        hundred = copy.deepcopy(self.payloads["issue-100-derived.json"])
        hundred["summary"]["integrated"] += 1
        table = copy.deepcopy(self.payloads["task7-estimate.json"])
        table["rows"] = table["rows"][:-1]
        for name, broken, error in (("issue-100-derived.json", hundred, Issue100Error),
                                    ("task7-estimate.json", table, EstimateError)):
            with self.subTest(member=name), self.assertRaises(error):
                validate_bundle(*bound(self.components, {**self.payloads, name: broken}), **self.kwargs())

    def test_authenticated_bundle_is_the_anchor_and_its_four_raw_members(self):
        self.assertEqual((ANCHOR_NAME, ANCHOR_MAX_BYTES, MEMBER_MAX_BYTES), ("derivation-anchor.json", 32768, 1048576))
        self.assertEqual(PAYLOAD_NAMES, (WITNESS, *FIXTURES))
        anchor, raw = authenticate(self.dir, self.expected)
        self.assertEqual((anchor, raw), (self.anchor, self.raw))
        payload = {"encoding": "canonical-json-ascii-lf/v1", "members": [row(raw, name) for name in PAYLOAD_NAMES]}
        self.assertEqual(anchor, {"schema_version": 2, "kind": "review-feasibility-derivation-anchor",
                                  **self.components, "payload": payload})
        self.assertEqual(validate_bundle(anchor, raw, **self.kwargs()),
                         {**self.payloads, WITNESS: json.loads(raw[WITNESS])})

    def test_replacement_anchor_fails_the_unchanged_digest(self):
        self.write({**self.anchor, "tool": {**self.anchor["tool"], "commit": "0" * 40}})
        self.refused("anchor_digest", authenticate, self.dir, self.expected)

    def test_malformed_expected_digest(self):
        for expected in ("sha256:xyz", self.expected[len("sha256:"):]):
            with self.subTest(expected=expected):
                self.refused("expected_digest", authenticate, self.dir, expected)

    def test_oversized_anchor_fails_before_decode(self):
        (self.dir / ANCHOR_NAME).write_bytes(b"{" * (ANCHOR_MAX_BYTES + 1))
        self.refused("anchor_unreadable", authenticate, self.dir, self.expected)

    def test_missing_or_symlinked_anchor_is_unreadable_and_a_too_deep_one_is_shape(self):
        anchor, link, moved = self.dir / ANCHOR_NAME, self.tmp / "link", self.tmp / "moved.json"
        link.symlink_to(self.dir)  # a whole valid bundle, reached through a symlinked directory
        for bundle in (self.tmp / "absent", link):
            self.refused("anchor_unreadable", authenticate, bundle, self.expected)
        anchor.rename(moved)
        self.refused("anchor_unreadable", authenticate, self.dir, self.expected)
        anchor.symlink_to(moved)
        self.refused("anchor_unreadable", authenticate, self.dir, self.expected)
        anchor.unlink(); anchor.write_bytes(b"[" * (ANCHOR_MAX_BYTES // 2) + b"]" * (ANCHOR_MAX_BYTES // 2))
        self.refused("anchor_shape", authenticate, self.dir, self.expected)  # well-formed, nested past decoding

    def test_noncanonical_or_open_anchor_is_anchor_shape(self):
        for label, raw in (("indented", json.dumps(self.anchor, indent=1).encode() + b"\n"),
                           ("extra key", canonical_bytes({**self.anchor, "extra": 1})),
                           ("boolean version", canonical_bytes({**self.anchor, "schema_version": True}))):
            (self.dir / ANCHOR_NAME).write_bytes(raw)
            with self.subTest(label):  # under the anchor's own digest, so only its shape can refuse it
                self.refused("anchor_shape", authenticate, self.dir, telemetry_digest(json.loads(raw)))

    def test_missing_extra_and_symlinked_members_fail(self):
        extra, member, outside = self.dir / "extra.json", self.dir / "issue-121.json", self.tmp / "outside.json"
        extra.write_bytes(b"{}\n")
        self.refused("member_set", authenticate, self.dir, self.expected)
        extra.unlink(); member.rename(outside); member.symlink_to(outside)
        self.refused("member_set", authenticate, self.dir, self.expected)
        member.unlink()
        self.refused("member_set", authenticate, self.dir, self.expected)
        member.mkdir()  # present, but not a regular file
        self.refused("member_set", authenticate, self.dir, self.expected)

    def test_declared_member_above_the_cap_is_refused(self):
        raw = {**self.raw, "issue-121.json": b" " * (MEMBER_MAX_BYTES + 1)}  # declared and hashed truthfully
        self.refused("member_digest", authenticate, self.dir, self.write(build_anchor(self.components, raw), raw))

    def test_same_length_member_with_another_digest_is_refused(self):
        data = self.raw["issue-121.json"]
        (self.dir / "issue-121.json").write_bytes(data[:-2] + b" \n")
        self.refused("member_digest", authenticate, self.dir, self.expected)

    def test_noncanonical_member_is_refused(self):
        spaced = json.dumps(self.payloads["issue-121.json"], sort_keys=True).encode() + b"\n"
        raw = {**self.raw, "issue-121.json": spaced}
        bundle = authenticate(self.dir, self.write(build_anchor(self.components, raw), raw))
        self.refused("member_noncanonical", validate_bundle, *bundle, **self.kwargs())

    def test_witness_has_six_keys_and_no_anchor_identity(self):
        witness = json.loads(self.raw[WITNESS])
        self.assertEqual(set(witness), {"schema_version", "kind", "components", "fixtures", "tables", "table_policies"})
        self.assertEqual((witness["schema_version"], witness["kind"]), (2, "review-feasibility-derivation-witness"))
        for identity in (self.expected, self.expected[len("sha256:"):], ANCHOR_NAME):
            self.assertNotIn(identity.encode(), self.raw[WITNESS])
        self.refused("witness_shape", validate_bundle, *self.rewitnessed({**witness, "anchor_sha256": self.expected}),
                     **self.kwargs())

    def test_witness_binds_components_fixtures_tables_and_policies(self):
        witness, (hundred, issue121, estimate) = json.loads(self.raw[WITNESS]), map(self.payloads.get, FIXTURES)
        self.assertEqual(witness["components"], self.components)
        self.assertEqual(witness["fixtures"], [row(self.raw, name) for name in FIXTURES])
        named = {"issue-121.json": {name: issue121[name] for name in ("classes", "edges", "anchors", "records")},
                 "issue-100-derived.json": {
                     **{name: hundred[name]
                        for name in ("parent_edges", "edges", "contributions", "pending_overlaps", "criteria")},
                     **{f"tables.{name}": hundred["tables"][name]["records"] for name in ("historical", "fresh")}},
                 "task7-estimate.json": {"rows": estimate["rows"]}}
        self.assertEqual({(t["fixture"], t["table"]): (t["rows"], t["sha256"]) for t in witness["tables"]},
                         {(fixture, name): (len(table), telemetry_digest(table))
                          for fixture, tables in named.items() for name, table in tables.items()})
        self.assertEqual(len(witness["tables"]), 12)
        self.assertEqual(witness["table_policies"], {
            "issue-121.json#records": issue121["record_table_policy"],
            **{f"issue-100-derived.json#tables.{name}": hundred["tables"][name]["record_table_policy"]
               for name in ("historical", "fresh")}})
        self.assertEqual({tuple(sorted(policy)) for policy in witness["table_policies"].values()},
                         {("domain", "policy_sha256")})
        for label, change in (("components", {"components": {**witness["components"], "tool": {}}}),
                              ("fixtures", {"fixtures": witness["fixtures"][:-1]})):
            with self.subTest(label):
                self.refused("component_mismatch" if label == "components" else "witness_shape", validate_bundle,
                             *self.rewitnessed({**witness, **change}), **self.kwargs())

    def test_component_substitutions_under_trust_injection(self):
        parts = self.components
        cases = [(group, member, flip(parts[group][member])) for group, members in PINNED.items() for member in members]
        cases += [("tool", "commit", "HEAD"), ("tool", "files", []), ("tool", "files", parts["tool"]["files"][::-1]),
                  ("tool", "files", [{**parts["tool"]["files"][0], "mode": "100644"}]),
                  ("tool", "artifact_policy_sha256", "sha256:xyz"), ("issue_100", "extra", "member"),
                  ("archive", "shards", [{**parts["archive"]["shards"][0], "extra": 1}])]
        for group, member, value in cases:
            changed = {**parts, group: {**parts[group], member: value}}
            with self.subTest(group=group, member=member):
                self.refused("component_mismatch", validate_bundle, *bound(changed, self.payloads), **self.kwargs())
        policy = {**parts["tool"], "artifact_policy_sha256": flip(parts["tool"]["artifact_policy_sha256"])}
        self.refused("policy_mismatch", validate_bundle, *bound({**parts, "tool": policy}, self.payloads),
                     **self.kwargs())
        stale = {**parts, "estimate": {**parts["estimate"], "table_sha256": flip(parts["estimate"]["table_sha256"])}}
        raw = {**self.raw, WITNESS: canonical_bytes(build_witness(stale, self.payloads, self.raw))}
        self.refused("component_mismatch", validate_bundle, build_anchor(stale, raw), raw, **self.kwargs())

    def test_stale_table_digest_or_policy_is_table_mismatch(self):
        witness, key = json.loads(self.raw[WITNESS]), "issue-121.json#records"
        (table, *tables), policies = witness["tables"], witness["table_policies"]
        policy = {**policies[key], "policy_sha256": flip(policies[key]["policy_sha256"])}
        for label, change in (("table", {"tables": [{**table, "sha256": flip(table["sha256"])}, *tables]}),
                              ("rows", {"tables": [{**table, "rows": table["rows"] + 1}, *tables]}),
                              ("policy", {"table_policies": {**policies, key: policy}})):
            with self.subTest(label):
                self.refused("table_mismatch", validate_bundle, *self.rewitnessed({**witness, **change}),
                             **self.kwargs())

    def test_tool_closure_is_sorted_and_complete(self):
        package, repo = SOURCE / "python/agent_tools", self.root / "repos/tool/repo"
        head = git(repo, "rev-parse", "HEAD")
        files = {path.relative_to(package).as_posix(): path.read_bytes() for path in package.rglob("*")
                 if path.is_file() and "__pycache__" not in path.relative_to(package).parts}
        self.assertIn("review_witness.py", files)
        self.assertEqual(tool_closure(repo, head), {"commit": head, "files": [
            {"path": path, "blob": hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest(),
             "raw_sha256": hashlib.sha256(data).hexdigest()} for path, data in sorted(files.items())]})
        self.refused("tool_closure", tool_closure, repo, head[:12])
        self.refused("tool_closure", tool_closure, self.root / "repos/100/repo", self.pins[2].head)  # no package
        linked = init_repo(self.tmp / "linked")
        (linked / "python/agent_tools").mkdir(parents=True)
        (linked / "python/agent_tools/link.py").symlink_to("target.py")
        git(linked, "add", "-A")
        self.refused("tool_closure", tool_closure, linked,
                     commit_files(linked, {"python/agent_tools/target.py": b"# target\n"}, "a committed symlink"))

    def test_running_closure_changed_extra_or_missing_file_fails(self):
        closure = self.components["tool"]
        files = closure["files"]
        self.assertIsNone(verify_running_closure(closure))
        for label, mutated in (("changed", [{**files[0], "raw_sha256": flip(files[0]["raw_sha256"])}, *files[1:]]),
                               ("extra running file", files[1:]),
                               ("missing running file", [*files, {**files[0], "path": "zz_absent.py"}])):
            with self.subTest(label):
                self.refused("tool_closure", verify_running_closure, {**closure, "files": mutated})
