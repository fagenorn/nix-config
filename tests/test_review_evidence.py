"""The committed retained review evidence, checked away from the retained repositories (issue 235; EV3, EV6).

Run: just agent-workflow-tests. Every case copies the committed bundle into a
scratch directory first and the committed files are compared before and after
each test. Replay runs sealed: scratch `cwd` and `HOME` and a `PATH` of one
empty directory, so it finds neither Git nor the budget helper. The trusted
digest is the literal `ANCHOR_SHA256`; no case computes an expected digest from
the committed anchor. The site and forgery tables are the full-shape tier's,
run here over the committed copy.
"""
import json, os, shutil, subprocess, sys, tempfile, unittest
from collections import Counter
from pathlib import Path

from agent_tools.canonical import telemetry_digest
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import Issue100Error
from agent_tools.review_task7 import EstimateError
from agent_tools.review_witness import ANCHOR_NAME, authenticate, validate_bundle

from .retained_evidence_test_support import ANCHOR_SHA256, BUNDLE, TOOL_COMMIT
from .retained_review_test_support import SOURCE
from .test_review_retained_full import (ESTIMATE, GIT_FREE_SITES, ISSUE_100, ISSUE_121, LABELS, PINS,
                                        REHASHED_FORGERIES, REPLAY, TRUSTED_SITES, WITNESS, rebuilt, substituted)

NAMES = (ANCHOR_NAME, WITNESS, ISSUE_100, ISSUE_121, ESTIMATE)
UNAVAILABLE = (2, b"", f"{REPLAY}: projection_unavailable: tasks-1-3,tasks-4-6\n".encode())
# Parent 226's twelve process assignments, in range order.
PROCESS = (
    ("348ab54e7d997ee6aa18a7c3adba0c8e7be5aba4", "initial_spec"),
    ("1f22492b58adda9d46e5e03690a3233754472cfa", "initial_plan"),
    ("c5346dc746b13bb9c8aa40462a36e90df1dd1b49", "standards_disposition"),
    ("023278198b8de5ccfa9ffaac447fa68b45f9ee19", "task2_contract_fix"),
    ("17d75549e7ceaf5b4d23cbee5b7b6eb3ffdfbbb0", "design_fix"),
    ("191a2344578c7ca4d245dde4aa04ba058a85e76b", "task4_contract_fix"),
    ("5e505f5ab2dbc328b2c5a071d86620bbcf05d941", "task5_plan_fix"),
    ("1a7560f9d3919cfe11c76b1b5105228220484abd", "design_budget_fix"),
    ("8a1fedd3dce3d441b7a55b5144a6be12696b55df", "plan_head_sync"),
    ("97d566aabdd5b87b6fc5d6949fcd05c23894d7ba", "design_budget_fix"),
    ("c150cfca5c591c3114cfbef5b1a15864acc7f39a", "design_grounding_fix"),
    ("fe85677c8bd26c808ac69c2ee21b17ff6e262923", "task7_staging_fix"))
# The eighteen task assignments, in range order. The sixth 3 is the late Task-3 fix: five Task-6
# assignments precede it and one follows.
TASK_OWNERS = [1, 1, 1, 2, 2, 3, 3, 4, 4, 4, 5, 6, 6, 6, 6, 6, 3, 6]
LATE_FIX = "8e6f0681908cb1ba3d352be5d26540dab731ffeb"
TASK8 = {"task": 8, "repository_bytes": 0, "state": "unexecuted",
         "acceptance": "post-integration-registration-evidence"}
# Nothing a bundle may carry: a home or scratch path, or the armour of a key.
LEAKS = (b"/Users/", b"/home/", b"/private/", b"/tmp/", b"/var/folders/", b"/nix/store/", b"PRIVATE KEY",
         b"ssh-ed25519 ", b"ssh-rsa ")


def flipped(data, at):
    """`data` with the hex digit or other byte at `at` replaced by a different one."""
    return data[:at] + (b"1" if data[at:at + 1] != b"1" else b"0") + data[at + 1:]


class CommittedEvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="review-evidence-"))
        self.addCleanup(shutil.rmtree, self.tmp)
        before = {path.name: path.read_bytes() for path in BUNDLE.iterdir()}
        self.assertEqual(sorted(before), sorted(NAMES))
        self.addCleanup(lambda: self.assertEqual({path.name: path.read_bytes() for path in BUNDLE.iterdir()}, before))
        self.committed = before

    def copy(self):
        return Path(shutil.copytree(BUNDLE, Path(tempfile.mkdtemp(dir=self.tmp)) / "bundle"))

    def written(self, forged):
        """A scratch copy holding the `(anchor, raw)` a forger rebuilt."""
        anchor, raw = forged
        bundle = self.copy()
        for name, data in {**raw, ANCHOR_NAME: canonical_bytes(anchor)}.items():
            (bundle / name).write_bytes(data)
        return bundle

    def replay(self, bundle, digest=ANCHOR_SHA256):
        """`(exit, stdout, stderr)` of the source replay command on `bundle`, sealed."""
        sealed = self.tmp / "sealed"
        (sealed / "bin").mkdir(parents=True, exist_ok=True)
        env = {"PYTHONPATH": str(SOURCE / "python"), "HOME": str(sealed), "PATH": str(sealed / "bin")}
        self.assertEqual([shutil.which(name, path=env["PATH"]) for name in ("git", "artifact-budget")], [None, None])
        done = subprocess.run([sys.executable, "-m", "agent_tools." + REPLAY.replace("-", "_"), "--fixtures-dir",
                               str(bundle), "--expected-anchor-sha256", digest],
                              env=env, cwd=sealed, capture_output=True, timeout=120)
        return done.returncode, done.stdout, done.stderr

    def refused(self, code):
        return 2, b"", f"{REPLAY}: invalid: {code}\n".encode()

    def models(self):
        anchor, raw = authenticate(self.copy(), ANCHOR_SHA256)
        return anchor, validate_bundle(anchor, raw, **PINS)

    def test_authentic_copy_replays_to_the_historical_refusal(self):
        bundle = self.copy()
        self.assertEqual(self.replay(bundle), UNAVAILABLE)
        self.assertEqual({path.name: path.read_bytes() for path in bundle.iterdir()}, self.committed)
        anchor, raw = authenticate(bundle, ANCHOR_SHA256)
        self.assertEqual(anchor["tool"]["commit"], TOOL_COMMIT)
        for name, data in self.committed.items():  # exact canonical bytes
            with self.subTest(name):
                self.assertEqual(canonical_bytes(json.loads(data)), data)

    def test_issue121_facts(self):
        model = self.models()[1][ISSUE_121]
        classes = model["classes"]
        self.assertEqual(len(classes), 30)
        self.assertEqual(tuple((row["commit"], row["reason"]) for row in classes if row["owner"] == 0), PROCESS)
        self.assertEqual([row["owner"] for row in classes if row["owner"]], TASK_OWNERS)
        late = [row["commit"] for row in classes].index(LATE_FIX)
        self.assertEqual((late, classes[late]["owner"], [row["owner"] for row in classes[late + 1:] if row["owner"]]),
                         (24, 3, [6]))
        commits = [row["commit"] for row in classes]
        self.assertEqual([(edge["commit"], edge["parent"], edge["owner"]) for edge in model["edges"]],
                         list(zip(commits, ["65748f480124515b9d0ee1467e958bbd9d54fc4a", *commits],
                                  [row["owner"] for row in classes])))
        rows = [model["aggregate"]["actual"], model["aggregate"]["projected"], *model["boundaries"]]
        self.assertEqual([row["boundary"] for row in rows], list(LABELS))
        common = {"boundary", "state", "prerequisite", "edge_ids", "estimate_refs"}
        measured = {"aggregate.actual": ("over_budget", 626996), "aggregate.projected": ("over_budget", 793484),
                    "tasks-7-8": ("within_budget", 169817)}
        failed = {"tasks-1-3": ("reconstruction", "whole_path_preimage_unproved"),
                  "tasks-4-6": ("prerequisite", "dependency_unavailable")}
        for row in rows:
            label = row["boundary"]
            with self.subTest(outcome=label):
                if label in measured:
                    self.assertEqual((row["state"], set(row)),
                                     ("measured", common | {"result_tree", "record_refs", "measurement"}))
                    metrics = row["measurement"]["metrics"]
                    self.assertEqual(set(metrics), {"root_bytes", "total_bytes", "file_count", "largest_member_bytes"})
                    self.assertTrue(all(type(value) is int for value in metrics.values()))
                    self.assertEqual((row["measurement"]["budget_status"], metrics["total_bytes"]), measured[label])
                else:
                    self.assertEqual((row["state"], set(row)), ("projection_unavailable", common | {"failure"}))
                    failure = row["failure"]
                    self.assertEqual(set(failure), {"stage", "code", "evidence_refs"})
                    self.assertEqual((failure["stage"], failure["code"]), failed[label])
                    self.assertTrue(failure["evidence_refs"])
        self.assertEqual(model["operational_effects"], [TASK8])

    def test_task7_facts(self):
        anchor, payloads = self.models()
        table = payloads[ESTIMATE]
        rows = table["rows"]
        self.assertEqual((len(rows), len({row["new_path"] for row in rows})), (173, 173))
        self.assertEqual(Counter(row["operation"] for row in rows), {"move": 165, "write": 5, "add": 3})
        roots = (".agents/artifacts/specs/", ".agents/artifacts/plans/", ".agents/knowledge/rejections/")
        self.assertEqual([sum(row["operation"] == "move" and row["new_path"].startswith(root) for row in rows)
                          for root in roots], [54, 108, 3])
        self.assertEqual(table["counts"], {"paths": 173, "moves": 165, "specs": 54, "plans": 108, "decisions": 3,
                                           "rewrites": 5, "additions": 3})
        for row in rows:
            bounds = [row["record_bytes"], *(row.get("output") or {}).values(), *((row["input"] or {}).get(name, 0)
                                                                                 for name in ("bytes", "lines"))]
            with self.subTest(path=row["new_path"]):
                self.assertTrue(all(type(value) is int and value >= 0 for value in bounds) and row["record_bytes"] > 0)
        pinned = ("prerequisite_commit", "prerequisite_tree", "plan_root_blob", "task7_blob", "model_version")
        self.assertEqual({name: table["identities"][name] for name in pinned},
                         {name: anchor["estimate"][name] for name in pinned})
        self.assertEqual(anchor["estimate"]["table_sha256"], telemetry_digest(table))
        self.assertIsNone(table["observed_actual"])
        self.assertEqual(table["historical_scope"]["operational_effects"], [TASK8])

    def test_issue100_facts(self):
        model = self.models()[1][ISSUE_100]
        self.assertEqual((len(model["parent_edges"]), sum(len(edge["records"]) for edge in model["edges"])), (91, 543))
        labels = Counter(row["disposition"] for row in model["contributions"])
        self.assertEqual(labels, {"historical_process": 8, "integrated": 38, "candidate": 69})
        self.assertEqual((len(model["contributions"]), len(model["pending_overlaps"])), (115, 4))
        summary = model["summary"]
        counted = ("edge_records", "parent_edges", "contributions", "historical_process", "integrated", "candidate",
                   "pending_overlaps", "reconciled")
        self.assertEqual([summary[name] for name in counted], [543, 91, 115, 8, 38, 69, 4, 0])
        self.assertEqual([row["state"] for row in model["criteria"]], ["superseded"] * 5 + ["governing"] * 5)
        tables = model["tables"]
        self.assertEqual({name: (sum(record["bytes"] for record in table["records"]), len(table["records"]))
                          for name, table in tables.items()},
                         {"historical": (1005707, 115), "fresh": (1012913, 115)})
        self.assertNotEqual(tables["historical"]["record_table_policy"], tables["fresh"]["record_table_policy"])

    def test_changed_and_incomplete_copies_are_refused(self):
        def change(name, alter):
            def apply(bundle):
                (bundle / name).write_bytes(alter((bundle / name).read_bytes()))
            return apply
        payload = lambda data: flipped(data, len(data) // 2)
        cases = [(f"one byte of {name}", "member_digest", change(name, payload))
                 for name in (WITNESS, ISSUE_100, ISSUE_121, ESTIMATE)]
        cases += [
            ("an anchor that no longer decodes", "anchor_shape", change(ANCHOR_NAME, lambda data: b"[" + data[1:])),
            ("one hex digit of the anchor", "anchor_digest",
             change(ANCHOR_NAME, lambda data: flipped(data, data.index(TOOL_COMMIT.encode())))),
            ("a member removed", "member_set", lambda bundle: (bundle / ESTIMATE).unlink()),
            ("an extra file", "member_set", lambda bundle: (bundle / "README.md").write_bytes(b"evidence\n")),
            ("a member truncated", "member_digest", change(ISSUE_121, lambda data: data[:-2] + b"\n"))]

        def linked(bundle):
            target = bundle.parent / WITNESS
            shutil.move(bundle / WITNESS, target)
            (bundle / WITNESS).symlink_to(target)
        cases.append(("a member replaced by a symlink", "member_set", linked))

        def replaced(bundle):  # another coherent anchor over the unchanged members
            anchor = json.loads((bundle / ANCHOR_NAME).read_bytes())
            anchor["tool"]["commit"] = "0" * 40
            (bundle / ANCHOR_NAME).write_bytes(canonical_bytes(anchor))
            authenticate(bundle, telemetry_digest(anchor))
        cases.append(("a replacement anchor", "anchor_digest", replaced))
        for label, code, alter in cases:
            with self.subTest(label):
                bundle = self.copy()
                alter(bundle)
                self.assertEqual(self.replay(bundle), self.refused(code))

    def test_trusted_sites_are_refused_under_the_trusted_digest(self):
        for site in TRUSTED_SITES:
            with self.subTest(site=site):
                anchor, raw = rebuilt(self.copy(), ANCHOR_SHA256, substituted(*site))
                bundle = self.written((anchor, raw))
                self.assertEqual(authenticate(bundle, telemetry_digest(anchor)), (anchor, raw))
                self.assertEqual(self.replay(bundle), self.refused("anchor_digest"))
                (bundle / ANCHOR_NAME).write_bytes(self.committed[ANCHOR_NAME])
                self.assertEqual(self.replay(bundle), self.refused("member_digest"))

    def test_rehashed_changes_are_refused_under_either_digest(self):
        intact = rebuilt(self.copy(), ANCHOR_SHA256)
        self.assertEqual(self.written(intact).joinpath(ANCHOR_NAME).read_bytes(), self.committed[ANCHOR_NAME])
        validate_bundle(*intact, **PINS)  # the rebuild alone changes nothing
        changes = [(error, site, substituted(*site), None) for error, sites in GIT_FREE_SITES.items() for site in sites]
        changes += [(error, label, change, "invalid_payload") for error, label, change in REHASHED_FORGERIES]
        # Beside the unchanged issue-121 refusal, a malformed sibling is invalid and never `projection_unavailable`.
        changes += [
            (Issue100Error, "issue-100 without its process list",
             lambda _, payloads: payloads[ISSUE_100].pop("process"), "invalid_payload"),
            (EstimateError, "estimate truncated by a row",
             lambda _, payloads: payloads[ESTIMATE]["rows"].pop(), "invalid_table")]
        for error, site, change, code in changes:
            with self.subTest(site=site):
                anchor, raw = rebuilt(self.copy(), ANCHOR_SHA256, change)
                with self.assertRaises(error) as caught:
                    validate_bundle(anchor, raw, **PINS)
                bundle = self.written((anchor, raw))
                self.assertEqual(self.replay(bundle), self.refused("anchor_digest"))
                if code is not None:  # the forger's own digest reaches the semantic layer (RP7)
                    self.assertEqual(caught.exception.code, code)
                    self.assertEqual(self.replay(bundle, telemetry_digest(anchor)), self.refused(code))

    def test_committed_bytes_hold_no_paths_keys_or_policy_lines(self):
        policy = (SOURCE / "home/common/agent-skills/artifact-budget-policy.json").read_bytes()
        secrets = {line.strip() for line in policy.split(b"\n") if len(line.strip()) > 16}
        secrets |= {*LEAKS, os.path.expanduser("~").encode(), tempfile.gettempdir().encode()}
        for name, data in self.committed.items():
            self.assertEqual([secret[:80] for secret in secrets if secret in data], [], name)


if __name__ == "__main__":
    unittest.main()
