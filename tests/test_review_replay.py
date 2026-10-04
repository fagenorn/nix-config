"""Portable replay of a retained bundle and its command (issue 249; RP2, RP7, RP8, RP17)."""
import hashlib, io, json, os, shutil, subprocess, sys, tempfile, unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from agent_tools.canonical import telemetry_digest
from agent_tools.replay_retained import main
from agent_tools.review_budget import describe
from agent_tools.review_derivation import DeriveInputs, derive_bundle
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue121 import ContributionError
from agent_tools.review_replay import ReplayUnavailable, replay
from agent_tools.review_witness import ANCHOR_NAME, WitnessError, authenticate, build_anchor, build_witness

from .retained_review_test_support import SOURCE, retained_fixture, source_budget_env, tool_fixture

UNAVAILABLE = dict(owners=(1, 2, 3, 6, 3), touches={4: 3})
NAMES = ("task7_pins", "issue121_pins", "issue100_pins")
GROUPS = ("tool", "issue_121", "issue_100", "archive", "estimate")
PREFIX = "replay-retained: "
ZERO = "sha256:" + "0" * 64


def derived_bundle(tmp, limits=None, **shape):
    """`(bundle_dir, expected digest, pin keywords)` from `derive_bundle` over the portable fixture."""
    repo121, repo100, archive, pins = retained_fixture(tmp, **shape)
    with patch.dict(os.environ, source_budget_env(tmp), clear=True):
        authority = describe("review-package")
    if limits:
        authority = replace(authority, limits=replace(authority.limits, **limits))
    kwargs = dict(zip(NAMES, pins))
    summary = derive_bundle(DeriveInputs(repo121, repo100, archive, *tool_fixture(tmp), tmp / "bundle"),
                            authority=authority, **kwargs)
    return tmp / "bundle", summary["anchor_sha256"], kwargs


class ReplayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(tempfile.mkdtemp()); cls.addClassCleanup(shutil.rmtree, cls.root)
        cls.cache = {}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, self.tmp)

    def shared(self, name="measured", **shape):
        """`derived_bundle` once per shape, for the cases that only read the bundle."""
        if name not in self.cache:
            (self.root / name).mkdir()
            self.cache[name] = derived_bundle(self.root / name, **shape)
        return self.cache[name]

    def refused(self, code, bundle, expected, kwargs):
        with self.assertRaises(WitnessError) as caught:
            replay(bundle, expected, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def run_command(self, *argv):
        """The command in a subprocess that can reach neither Git nor a budget helper: `PATH` is empty."""
        done = subprocess.run([sys.executable, "-m", "agent_tools.replay_retained", *argv],
                              env={"PYTHONPATH": str(SOURCE / "python"), "PATH": ""}, capture_output=True)
        return done.returncode, done.stdout, done.stderr

    def main(self, bundle, expected, kwargs):
        """`(status, stdout, stderr)` of the command in process. It passes only its real pins, so its three
        pin names carry the fixture's here (RP17)."""
        pins = {name.replace("issue", "issue_").upper(): value for name, value in kwargs.items()}
        stdout, stderr = io.TextIOWrapper(io.BytesIO()), io.StringIO()
        with patch.multiple("agent_tools.replay_retained", **pins), patch("sys.stdout", stdout), \
                patch("sys.stderr", stderr):
            status = main(["--fixtures-dir", str(bundle), "--expected-anchor-sha256", expected])
        stdout.flush()
        return status, stdout.buffer.getvalue(), stderr.getvalue()

    def test_unavailable_bundle_replays_without_sources_in_outcome_order(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, **UNAVAILABLE)
        moved = self.tmp / "portable"; shutil.copytree(bundle, moved)
        shutil.rmtree(self.tmp / "repos"); shutil.rmtree(bundle)
        with self.assertRaises(ReplayUnavailable) as caught:
            replay(moved, expected, **kwargs)
        self.assertEqual(caught.exception.ids, ("tasks-1-3", "tasks-4-6"))

    def test_over_budget_measured_outcomes_are_a_result(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, limits={"root_max_bytes": 1})
        result = replay(bundle, expected, **kwargs)
        self.assertEqual(set(result), {"schema_version", "kind", "anchor_sha256", "issue_121", "issue_100"})
        self.assertEqual((result["schema_version"], result["kind"], result["anchor_sha256"]),
                         (3, "review-feasibility-retained-result", expected))
        rows = [*result["issue_121"]["aggregate"].values(), *result["issue_121"]["boundaries"]]
        self.assertEqual({row["measurement"]["budget_status"] for row in rows}, {"over_budget"})

    def test_validation_precedes_classification(self):
        bundle, expected, kwargs = derived_bundle(self.tmp, **UNAVAILABLE)
        anchor, raw = authenticate(bundle, expected)
        broken = {**raw, "issue-100-derived.json": canonical_bytes({"schema_version": 1})}
        rebound = build_anchor({group: anchor[group] for group in GROUPS}, broken)
        (bundle / "issue-100-derived.json").write_bytes(broken["issue-100-derived.json"])
        (bundle / ANCHOR_NAME).write_bytes(canonical_bytes(rebound))
        # A coherent anchor digest over a witness whose fixture rows are stale: invalid, never unavailable.
        self.refused("witness_shape", bundle, telemetry_digest(rebound), kwargs)

    def test_forged_head_tree_is_refused_under_its_rebuilt_digest(self):
        source, expected, kwargs = self.shared()
        bundle = Path(shutil.copytree(source, self.tmp / "forged"))
        anchor, raw = authenticate(bundle, expected)
        payloads = {name: json.loads(data) for name, data in raw.items()}
        issue121, forged = payloads["issue-121.json"], "f" * 40
        future = issue121["boundaries"][2]
        heads = (*issue121["aggregate"].values(), future)
        self.assertEqual([row["result_tree"] for row in heads] + [future["prerequisite"]["tree"]],
                         [anchor["issue_121"]["tree"]] * 4)  # as derived: the pinned head's tree (RP16)
        for row in heads:
            row["result_tree"] = forged
        future["prerequisite"]["tree"] = forged
        components = {group: anchor[group] for group in GROUPS}
        raw = {**raw, "issue-121.json": canonical_bytes(issue121)}
        raw["derivation-witness.json"] = canonical_bytes(build_witness(components, payloads, raw))
        rebound = build_anchor(components, raw)
        for name, data in {**raw, ANCHOR_NAME: canonical_bytes(rebound)}.items():
            (bundle / name).write_bytes(data)
        trusted = telemetry_digest(rebound)  # trust injection (RP7): the forger's own, coherent digest
        self.assertEqual(authenticate(bundle, trusted), (rebound, raw))
        self.refused("component_mismatch", bundle, trusted, kwargs)

    def test_result_reports_the_issue100_summary(self):
        bundle, expected, kwargs = self.shared()
        result = replay(bundle, expected, **kwargs)
        member = (bundle / "issue-100-derived.json").read_bytes()
        self.assertEqual(result["issue_100"], {
            "history_edge_count": 20, "disposition_counts": {"historical_process": 1, "integrated": 1, "candidate": 6},
            "pending_overlap_count": 2, "fixture_sha256": hashlib.sha256(member).hexdigest()})
        payload = json.loads((bundle / "issue-121.json").read_bytes())
        self.assertEqual(result["issue_121"],
                         {name: payload[name] for name in ("aggregate", "boundaries", "operational_effects")})
        self.assertEqual((set(result), result["schema_version"], result["kind"], result["anchor_sha256"]),
                         ({"schema_version", "kind", "anchor_sha256", "issue_121", "issue_100"}, 3,
                          "review-feasibility-retained-result", expected))

    def test_wrong_expected_digest_is_anchor_digest(self):
        bundle, expected, kwargs = self.shared()
        self.assertNotEqual(expected, ZERO)
        self.refused("anchor_digest", bundle, ZERO, kwargs)

    def test_partial_bundle_is_member_set(self):
        bundle, expected, kwargs = self.shared()
        partial = Path(shutil.copytree(bundle, self.tmp / "partial"))
        (partial / "task7-estimate.json").unlink()
        self.refused("member_set", partial, expected, kwargs)

    def test_command_real_pins_refuse_a_portable_bundle(self):
        bundle, expected, _ = self.shared()
        self.assertEqual(self.run_command("--fixtures-dir", str(bundle), "--expected-anchor-sha256", expected),
                         (2, b"", b"replay-retained: invalid: component_mismatch\n"))

    def test_command_usage_and_input_refusals(self):
        absent, empty = self.tmp / "absent", self.tmp / "empty"
        empty.mkdir()
        line = ["--fixtures-dir", str(empty), "--expected-anchor-sha256", ZERO]
        cases = {"usage": [line[:2], line[2:], [], line + ["--anchor", "x"], line + ["--help"], line + ["-h"],
                           line + ["extra"], ["--fixtures", str(empty), *line[2:]],
                           [*line[:2], "--expected", ZERO]],
                 "expected_digest": [[*line[:3], "sha256:xyz"], [*line[:3], ZERO[len("sha256:"):]]],
                 "anchor_unreadable": [["--fixtures-dir", str(absent), *line[2:]], line]}
        for code, lines in cases.items():
            for argv in lines:
                with self.subTest(code=code, argv=argv):
                    self.assertEqual(self.run_command(*argv), (2, b"", f"{PREFIX}invalid: {code}\n".encode()))
        self.assertEqual((absent.exists(), os.listdir(empty)), (False, []))

    def test_main_maps_measured_and_unavailable_outcomes(self):
        bundle, expected, kwargs = self.shared()
        self.assertEqual(self.main(bundle, expected, kwargs),
                         (0, canonical_bytes(replay(bundle, expected, **kwargs)), ""))
        self.assertEqual(self.main(*self.shared("unavailable", **UNAVAILABLE)),
                         (2, b"", PREFIX + "projection_unavailable: tasks-1-3,tasks-4-6\n"))

    def test_main_maps_an_os_error_and_a_source_error(self):
        pins = dict.fromkeys(NAMES)  # `replay` is replaced, so no pin is read
        for error, code in ((PermissionError(13, "denied"), "io_error"),
                            (ContributionError("assignment_mismatch"), "assignment_mismatch")):
            with self.subTest(code), patch("agent_tools.replay_retained.replay", side_effect=error) as replayed:
                self.assertEqual(self.main(self.tmp, ZERO, pins), (2, b"", f"{PREFIX}invalid: {code}\n"))
                replayed.assert_called_once_with(self.tmp, ZERO, **pins)
