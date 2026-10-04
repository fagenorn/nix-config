"""Full-shape retained tier: both commands and SOURCE's models over the real objects (issue 249; RP7, RP10, RP11).

Run: just agent-retained-tests <root>. The recipe names the retained root in
`AGENT_RETAINED_ROOT`. Without that variable the class skips, which is never
acceptance; with it, a missing commit or archive file fails `setUpClass`.

Both issue repositories are the root, the archive is the root's issue-100
evidence directory and the tool repository is this checkout. Every mutation
happens in a `git clone --shared --no-checkout` of the root or in a copied
bundle. The root is compared before and after each test, and a difference
voids the run (RP11).
"""
import hashlib, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch

from agent_tools.adopt_planning import adoption_records
from agent_tools.canonical import telemetry_digest
from agent_tools.review_actual import actual_inputs_from_trees
from agent_tools.review_budget import describe
from agent_tools.review_forecast import canonical_bytes
from agent_tools.review_issue100 import ISSUE_100_PINS, Issue100Error, fresh_records, historical_records, validate_100
from agent_tools.review_issue121 import (ISSUE_121_PINS, ContributionError, classify, contribution_edges, plan_anchors,
                                         reconstruct_boundary)
from agent_tools.review_task7 import DIGEST_PLACEHOLDER, TASK7_PINS, EstimateError, derive_task7
from agent_tools.review_witness import (ANCHOR_MAX_BYTES, ANCHOR_NAME, WitnessError, authenticate, build_anchor,
                                        build_witness, validate_bundle)

from .retained_review_test_support import SOURCE, git, rehash_edges, source_budget_env, ssh_signer

ROOT_ENV, TOOL_COMMIT_ENV = "AGENT_RETAINED_ROOT", "AGENT_RETAINED_TOOL_COMMIT"
RECIPE = "just agent-retained-tests <root>"
ARCHIVE = ".superpowers/review-evidence/100/direct-100-000002/source-integration-a7b7c6f"
# The retained commits: the issue-121 head and base, then the issue-100 head and live commit.
COMMITS = ("fe85677c8bd26c808ac69c2ee21b17ff6e262923", "65748f480124515b9d0ee1467e958bbd9d54fc4a",
           "a7b7c6f45787c7c928d064b46ed499087b5b3c46", "cba57498b1ec25f904bd2653029636c79abba41f")
WITNESS, ISSUE_100, ISSUE_121, ESTIMATE = ("derivation-witness.json", "issue-100-derived.json", "issue-121.json",
                                           "task7-estimate.json")
GROUPS = ("tool", "issue_121", "issue_100", "archive", "estimate")
LABELS = ("aggregate.actual", "aggregate.projected", "tasks-1-3", "tasks-4-6", "tasks-7-8")
DERIVE, REPLAY = "derive-review-feasibility-fixtures", "replay-retained"
PINS = dict(task7_pins=TASK7_PINS, issue121_pins=ISSUE_121_PINS, issue100_pins=ISSUE_100_PINS)
LOCKLESS = {"GIT_OPTIONAL_LOCKS": "0"}
VOID = "the retained root changed: this run is void and must be repeated on a quiescent root (RP11)"
# The pinned `apply` runs the pinned tree's own build and workflow suite as its last commit gate.
APPLY_TIMEOUT_SECONDS = 3 * 60 * 60
PASSED_GATES = ("worktree-status-matches-operations", "projections-in-sync", "no-unclassified-agent-path",
                "cold-clone-resolves", "resolve-capabilities-available")
FAILED_GATE = "workflow-verification-commands"

# RP7 layer 1: one member of each component group, one record digest in each fixture and one edge reference.
# A site is a component group or a fixture name, then the keys and indices down to one string or count.
TRUSTED_SITES = (
    ("tool", "commit"), ("issue_121", "head"), ("issue_100", "live"), ("archive", "manifest_sha256"),
    ("estimate", "task7_blob"), (ISSUE_121, "records", 0, "record_sha256"),
    (ISSUE_100, "tables", "fresh", "records", 0, "sha256"), (ESTIMATE, "rows", -1, "input", "blob"),
    (ISSUE_121, "aggregate", "actual", "edge_ids", 0))
# RP7 layer 2: every component member the pins determine and every cross-table reference, under the error
# that refuses it. Each site exists whatever the proof produced: `aggregate.actual` and `tasks-7-8`
# (boundary 2) are measured in every bundle. `tool.commit`, `tool.files`, `archive.shards` and a
# re-measured record's bytes or digest are not determined without Git, so they are not here.
GIT_FREE_SITES = {
    WitnessError: (
        *(("issue_121", member) for member in ("base", "head", "tree", "signer_sha256")),
        *(("issue_100", member) for member in ("base", "head", "live", "parent_edges_sha256")),
        *(("archive", member) for member in ("producer_sha256", "manifest_sha256")),
        *(("estimate", member) for member in ("prerequisite_commit", "prerequisite_tree", "plan_root_blob",
                                               "task7_blob", "model_version", "table_sha256")),
        *(("tool", member) for member in ("artifact_policy_sha256", "packing_policy_sha256", "record_policy_sha256")),
        (ISSUE_121, "aggregate", "actual", "result_tree")),
    EstimateError: ((ESTIMATE, "rows_sha256"), (ESTIMATE, "identities", "task7_blob"),
                    (ESTIMATE, "rows", -1, "record_bytes"), (ESTIMATE, "counts", "moves")),
    ContributionError: (
        (ISSUE_121, "range", "head"), (ISSUE_121, "classes", 0, "commit"), (ISSUE_121, "edges", 0, "parent"),
        (ISSUE_121, "edges", 0, "commit"), (ISSUE_121, "anchors", 0, "commit"), (ISSUE_121, "anchors", 0, "blob"),
        (ISSUE_121, "anchors", 0, "signer_sha256"), (ISSUE_121, "records", 0, "edge_ids", 0),
        (ISSUE_121, "aggregate", "actual", "edge_ids", 0), (ISSUE_121, "aggregate", "actual", "record_refs", 0),
        (ISSUE_121, "aggregate", "projected", "estimate_refs", 0), (ISSUE_121, "boundaries", 2, "result_tree"),
        (ISSUE_121, "boundaries", 2, "prerequisite", "tree"), (ISSUE_121, "boundaries", 2, "record_refs", 0)),
    Issue100Error: (
        (ISSUE_100, "range", "commits", 0), (ISSUE_100, "parent_edges", 0, "parent"), (ISSUE_100, "edges", 0, "commit"),
        (ISSUE_100, "contributions", 0, "record_sha256"), (ISSUE_100, "tables", "fresh", "records", 0, "sha256"),
        (ISSUE_100, "contributions", 0, "edge_refs", 0, 0), (ISSUE_100, "contributions", 0, "head_entry", "oid"),
        (ISSUE_100, "pending_overlaps", 0, "head_entry", "oid"), (ISSUE_100, "pending_overlaps", 0, "path"),
        (ISSUE_100, "criteria", 0, "text_sha256"), (ISSUE_100, "summary", "edge_records")),
}


def retained_root() -> Path:
    """The retained root the recipe names; a class-level skip naming the recipe when the variable is unset."""
    root = os.environ.get(ROOT_ENV)
    if root is None:
        raise unittest.SkipTest(f"{ROOT_ENV} is unset; run `{RECIPE}` for the full-shape tier")
    return Path(root)


def tool_commit() -> str:
    """`AGENT_RETAINED_TOOL_COMMIT`, else this checkout's `HEAD`; its `python` tree is `HEAD`'s (parent D17)."""
    commit = os.environ.get(TOOL_COMMIT_ENV) or git(SOURCE, "rev-parse", "HEAD", env=LOCKLESS)
    trees = [git(SOURCE, "rev-parse", f"{rev}:python", env=LOCKLESS) for rev in (commit, "HEAD")]
    if trees[0] != trees[1]:
        raise AssertionError(f"{commit}:python is not HEAD:python, so it is not the tool this checkout runs")
    return commit


def derive_argv(root, commit, **replaced) -> list:
    """The derive command's options over the retained inputs under `root` at tool commit `commit`, with
    `replaced` naming the output directory and any input to substitute."""
    inputs = {"issue_121_repo": root, "issue_100_repo": root, "archive_dir": Path(root) / ARCHIVE,
              "tool_repo": SOURCE, "tool_commit": commit, **replaced}
    return [word for name, value in inputs.items() for word in ("--" + name.replace("_", "-"), str(value))]


def root_state(root) -> dict:
    """What RP11 compares: the refs, the index file, `info/grafts`, `shallow`, the `objects` listing and every
    archive file, the files as digests. Collecting it writes nothing: its Git reads take no optional lock."""
    store = Path(git(root, "rev-parse", "--path-format=absolute", "--git-common-dir", env=LOCKLESS))
    state = {"refs": git(root, "for-each-ref", "--format=%(objectname) %(refname)", env=LOCKLESS).splitlines(),
             "objects": sorted(Path(directory, name).relative_to(store).as_posix()
                               for directory, _, names in os.walk(store / "objects") for name in names)}
    files = [store / "index", store / "info/grafts", store / "shallow",
             *(path for path in sorted((Path(root) / ARCHIVE).rglob("*")) if path.is_file())]
    for path in files:
        state[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return state


def root_changes(root, before) -> list:
    """What moved in the root since `before`: each ref line and object file that came or went, and the path
    of each other file whose digest differs."""
    after, changes = root_state(root), []
    for name in sorted(before.keys() | after.keys()):
        old, new = before.get(name), after.get(name)
        if isinstance(old, list) and isinstance(new, list):
            changes += sorted(set(old) ^ set(new))
        elif old != new:
            changes.append(name)
    return changes


def watch_root(case, root) -> None:
    """Fail `case` unless the root is, once the case and its other cleanups are over, what it is now (RP11)."""
    before = root_state(root)
    case.addCleanup(lambda: case.assertEqual(root_changes(root, before), [], VOID))


def substituted(*site):
    """A change for `RetainedFullTest.forged`: the string or count at `site` becomes another of the same
    shape, and the table row it sits in, when that row carries an `id`, is rehashed."""
    def change(components, payloads):
        holder = (components if site[0] in GROUPS else payloads)[site[0]]
        rows = [holder]
        for key in site[1:-1]:
            holder = holder[key]
            rows.append(holder)
        value = holder[site[-1]]
        holder[site[-1]] = value + 1 if type(value) is int else value[:-1] + ("1" if value[-1] == "0" else "0")
        for row in rows:
            if isinstance(row, dict) and "id" in row:
                row.update(rehash_edges([row])[0])
    return change


class RetainedFullTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = retained_root()
        cls.tmp = Path(tempfile.mkdtemp(prefix="retained-full-"))
        cls.addClassCleanup(shutil.rmtree, cls.tmp)
        before = root_state(cls.root)
        for commit in COMMITS:  # a missing retained input fails here; nothing skips (RP10)
            git(cls.root, "cat-file", "-e", commit + "^{commit}", env=LOCKLESS)
        missing = [name for name in (ISSUE_100_PINS.producer_name, ISSUE_100_PINS.manifest_name)
                   if not (cls.root / ARCHIVE / name).is_file()]
        if missing:
            raise AssertionError(f"archive files missing under {ARCHIVE}: {missing}")
        cls.tool_commit = tool_commit()
        cls.key = ssh_signer(cls.tmp)[0]  # the renderer run's ephemeral key: in the scratch while deriving
        cls.env = source_budget_env(cls.tmp)
        with patch.dict(os.environ, cls.env, clear=True):
            cls.authority = describe("review-package")
        cls.table = derive_task7(cls.root, TASK7_PINS)
        cls.bundle = cls.tmp / "bundle"
        done = cls.derive_cli(output_dir=cls.bundle)
        if done.returncode:
            raise AssertionError(f"the class bundle did not derive: {done.stderr.decode()}")
        cls.summary, cls.digest = done.stdout, json.loads(done.stdout)["anchor_sha256"]
        moved = root_changes(cls.root, before)
        if moved:
            raise AssertionError(f"{VOID}: {moved}")

    def setUp(self):
        watch_root(self, self.root)

    @classmethod
    def derive_cli(cls, **replaced):
        """The source derive command over the class inputs, `replaced` as `derive_argv` takes it."""
        return subprocess.run([sys.executable, "-m", "agent_tools." + DERIVE.replace("-", "_"),
                               *derive_argv(cls.root, cls.tool_commit, **replaced)],
                              env=cls.env, cwd=cls.tmp, capture_output=True)

    def replay_cli(self, bundle):
        """`(exit, stdout, stderr)` of the source replay command on `bundle` under the class digest, with the
        sources unreachable: `cwd` and `HOME` in the scratch and a `PATH` of one empty directory."""
        sealed = self.tmp / "sealed"
        (sealed / "bin").mkdir(parents=True, exist_ok=True)
        env = {"PYTHONPATH": str(SOURCE / "python"), "HOME": str(sealed), "PATH": str(sealed / "bin")}
        self.assertEqual([shutil.which(name, path=env["PATH"]) for name in ("git", "artifact-budget")], [None, None])
        done = subprocess.run([sys.executable, "-m", "agent_tools." + REPLAY.replace("-", "_"), "--fixtures-dir",
                               str(bundle), "--expected-anchor-sha256", self.digest],
                              env=env, cwd=sealed, capture_output=True)
        return done.returncode, done.stdout, done.stderr

    def disposable_clone(self, source=None):
        """A fresh `git clone --shared --no-checkout` of the root, or of `source`, in the scratch."""
        clone = Path(tempfile.mkdtemp(dir=self.tmp, prefix="clone-")) / "repo"
        git(self.tmp, "clone", "-q", "--shared", "--no-checkout", str(source or self.root), str(clone))
        return clone

    def copied_bundle(self):
        return Path(shutil.copytree(self.bundle, Path(tempfile.mkdtemp(dir=self.tmp, prefix="bundle-")) / "bundle"))

    def forged(self, change=lambda components, payloads: None):
        """`(anchor, raw)` of the class bundle after `change(components, payloads)`, with every in-bundle hash
        recomputed as a forger would: the estimate group's table digest when the table changed, each member's
        bytes and digest, the witness and the anchor. Without a change it is the class bundle itself."""
        anchor, raw = authenticate(self.bundle, self.digest)
        components = {group: anchor[group] for group in GROUPS}
        payloads = {name: json.loads(raw[name]) for name in (ISSUE_100, ISSUE_121, ESTIMATE)}
        change(components, payloads)
        forged = {name: canonical_bytes(payload) for name, payload in payloads.items()}
        if forged[ESTIMATE] != raw[ESTIMATE]:
            components["estimate"]["table_sha256"] = telemetry_digest(payloads[ESTIMATE])
        forged[WITNESS] = canonical_bytes(build_witness(components, payloads, forged))
        return build_anchor(components, forged), forged

    def test_grafted_clone_reproduces_i1_and_every_entry_point_refuses(self):
        clone = self.disposable_clone()
        clean = contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        self.assertEqual(len(clean), 30)
        target, parent, extra = clean[10]["commit"], clean[10]["parent"], clean[3]["commit"]
        forged = [*clean[:11], *rehash_edges([{**clean[10], "parent": extra, "parent_ordinal": 2}]), *clean[11:]]
        self.assertEqual(len(forged), 31)
        (clone / ".git/info").mkdir(exist_ok=True)
        (clone / ".git/info/grafts").write_text(f"{target} {parent} {extra}\n")
        for edges in (clean, forged):
            with self.assertRaises(ContributionError):
                reconstruct_boundary(clone, ISSUE_121_PINS, boundary="tasks-1", prerequisite={"kind": "delivery-base"},
                                     edges=edges, table=self.table, task7_pins=TASK7_PINS, authority=self.authority)
        with self.assertRaises(ContributionError):
            contribution_edges(clone, ISSUE_121_PINS, classify(clone, ISSUE_121_PINS))
        out = self.tmp / "derive-grafted"
        done = self.derive_cli(issue_121_repo=clone, output_dir=out)
        self.assertEqual((done.returncode, done.stdout), (2, b""))
        self.assertRegex(done.stderr.decode(), r"\Aderive-review-feasibility-fixtures: invalid: [a-z0-9_]+\n\Z")
        self.assertFalse(out.exists())

    def test_real_assignments_anchors_and_task7_counts(self):
        classes = classify(self.root, ISSUE_121_PINS)
        owners = [row["owner"] for row in classes]
        self.assertEqual((len(contribution_edges(self.root, ISSUE_121_PINS, classes)), owners.count(0),
                          sum(1 for owner in owners if owner)), (30, 12, 18))
        anchors = {row["path"]: row["blob"] for row in plan_anchors(self.root, ISSUE_121_PINS)}
        prefix = ".claude/plans/2026-09-03-issue-121-adoption-v1"
        self.assertEqual(len(anchors), 9)  # the plan root and its eight task members
        self.assertEqual((anchors[prefix + ".md"], anchors[prefix + ".tasks/task-7.md"]),
                         ("8294252bb15684d9bf6054d7faf84ac98a376923", "c8c622dd6389dc844a7fc638c305d2ab71223cb8"))
        self.assertEqual(self.table["counts"], {"paths": 173, "moves": 165, "specs": 54, "plans": 108,
                                                "decisions": 3, "rewrites": 5, "additions": 3})
        self.assertIsNone(self.table["observed_actual"])

    def test_pinned_renderer_output_within_row_bounds(self):
        stage, clone = self.tmp / "stage", self.disposable_clone()
        # The pinned Task-7 brief's staging `HOME`: the two commands in `bin`, the platform manifest in
        # `share` and the five libraries in `lib/python`, each copied from its pinned blob.
        for path, blob in sorted({(spec.renderer_path, spec.renderer_blob) for spec in TASK7_PINS.renderers}):
            name = Path(path)
            place = ("share/" + name.name if name.suffix == ".json" else
                     "bin/" + name.stem if "-" in name.stem else "lib/python/" + name.name)
            target = stage / ".agents" / place
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.run(["git", "-C", str(self.root), "cat-file", "blob", blob],
                                              env=dict(os.environ, **LOCKLESS), check=True, capture_output=True).stdout)
            target.chmod(0o755)
        config = self.tmp / "gitconfig"
        config.write_text("[user]\n\tname = Fixture\n\temail = fixture@example.test\n"
                          f"\tsigningkey = {self.key}\n[gpg]\n\tformat = ssh\n")
        # Neither the user's key and Git configuration nor this run's own variables reach the pinned tool.
        env = {name: value for name, value in os.environ.items() if not name.startswith(("AGENT_", "GIT_", "PYTHON"))}
        env.update(HOME=str(stage), GIT_CONFIG_GLOBAL=str(config), GIT_CONFIG_NOSYSTEM="1",
                   PATH=str(stage / ".agents/bin") + os.pathsep + os.environ["PATH"])
        git(clone, "checkout", "-q", "--detach", TASK7_PINS.prerequisite_commit)

        def adopt(*args, timeout):
            done = subprocess.run(["adopt-project", *args], env=env, cwd=stage, capture_output=True, timeout=timeout)
            return done.returncode, json.loads(done.stdout)

        status, document = adopt("plan", "--repo-root", str(clone), timeout=600)
        self.assertEqual(status, 0, document)
        plan = document["plan"]
        self.assertEqual((plan["outcome"], plan["state"]), ("reconcile", "ready"))
        # At the pinned commit `apply` runs every operation in its own worktree and then stops at its last
        # commit gate, where the pinned tree's own workflow suite fails one case on the adopted configuration.
        # It makes no commit and retains the worktree, whose index is the renderers' whole output (RP23).
        status, refusal = adopt("apply", "--plan-id", plan["plan_id"], timeout=APPLY_TIMEOUT_SECONDS)
        error = refusal.get("error") or {}
        self.assertEqual((status, error.get("code"), error.get("repair_id")),
                         (2, "verification_failed", "adopt.gate." + FAILED_GATE), refusal)
        worktree = stage / ".agents/state/adopt/worktrees" / plan["plan_id"].split(":")[1]
        retained = json.loads(worktree.with_name(worktree.name + ".failure.json").read_bytes())
        self.assertEqual({gate["id"]: gate["status"] for gate in retained["gates"]},
                         {**dict.fromkeys(PASSED_GATES, "passed"), FAILED_GATE: "failed"})
        self.assertEqual(git(worktree, "rev-parse", "HEAD"), TASK7_PINS.prerequisite_commit)
        staged = git(worktree, "write-tree")
        records = next(actual_inputs_from_trees(
            clone, TASK7_PINS.prerequisite_tree, staged, base=TASK7_PINS.prerequisite_tree, head=staged, commits=(),
            package_name="adoption.json", limits=self.authority.limits)).records
        # The run names its migration map and evidence record by the plan digest; their rows carry the placeholder.
        actual, placeholder = adoption_records(plan["plan_id"]), adoption_records("sha256:" + DIGEST_PLACEHOLDER)
        rows = {row["new_path"]: row["record_bytes"] for row in self.table["rows"]}
        self.assertEqual(len(rows), len(self.table["rows"]))
        matched = [{actual[kind]: placeholder[kind] for kind in actual}.get(record.path, record.path)
                   for record in records]
        self.assertTrue(matched)
        self.assertEqual(len(set(matched)), len(matched))  # each row has at most one record
        for record, path in zip(records, matched):
            with self.subTest(path=record.path):
                self.assertIn(path, rows)  # each record has exactly one row
                self.assertLessEqual(record.source_bytes, rows[path])

    def test_issue100_domains_are_exact_and_distinct(self):
        historical = historical_records(self.root, ISSUE_100_PINS)
        fresh = fresh_records(self.root, ISSUE_100_PINS, self.authority.limits)
        self.assertEqual((sum(record["bytes"] for record in historical), len(historical)), (1005707, 115))
        self.assertEqual((sum(record["bytes"] for record in fresh), len(fresh)), (1012913, 115))
        # Each call bound its raw bytes to the pinned whole-domain digest, and no record list equals the other.
        self.assertNotEqual(ISSUE_100_PINS.historical.sha256, ISSUE_100_PINS.fresh.sha256)
        self.assertNotEqual([record["sha256"] for record in historical], [record["sha256"] for record in fresh])
        payload = json.loads((self.bundle / ISSUE_100).read_bytes())
        validate_100(payload, ISSUE_100_PINS)
        tables = payload["tables"]
        policies = [tables[name]["record_table_policy"] for name in ("historical", "fresh")]
        self.assertNotEqual(*policies)
        tables["fresh"]["record_table_policy"], tables["historical"]["record_table_policy"] = policies
        with self.assertRaises(Issue100Error):
            validate_100(payload, ISSUE_100_PINS)

    def test_two_derivations_are_byte_identical(self):
        second = self.tmp / "second"
        done = self.derive_cli(output_dir=second)
        self.assertEqual((done.returncode, done.stdout, done.stderr), (0, self.summary, b""))
        self.assertEqual(self.summary, canonical_bytes(json.loads(self.summary)))
        files = [{path.name: path.read_bytes() for path in bundle.iterdir()} for bundle in (self.bundle, second)]
        self.assertEqual(files[0], files[1])
        self.assertEqual(set(files[0]), {ANCHOR_NAME, WITNESS, ISSUE_100, ISSUE_121, ESTIMATE})
        self.assertLessEqual(len(files[0][ANCHOR_NAME]), ANCHOR_MAX_BYTES)

    def test_dirty_or_mismatched_tool_tree_refuses(self):
        clone, path = self.disposable_clone(SOURCE), "python/agent_tools/canonical.py"
        source = git(clone, "cat-file", "blob", f"{self.tool_commit}:{path}")
        blob = git(clone, "hash-object", "-w", "--stdin", input=source + "\n# drift\n")
        git(clone, "read-tree", self.tool_commit)
        git(clone, "update-index", "--cacheinfo", f"100644,{blob},{path}")
        drifted = git(clone, "commit-tree", git(clone, "write-tree"), "-p", self.tool_commit, "-m", "drift")
        self.assertNotEqual(*(git(clone, "rev-parse", f"{rev}:python") for rev in (drifted, self.tool_commit)))
        out = self.tmp / "derive-drifted"
        done = self.derive_cli(tool_repo=clone, tool_commit=drifted, output_dir=out)
        self.assertEqual((done.returncode, done.stdout, done.stderr),
                         (2, b"", f"{DERIVE}: invalid: tool_closure\n".encode()))
        self.assertFalse(out.exists())

    def test_replay_with_sources_unreachable(self):
        bundle = self.copied_bundle()
        status, stdout, stderr = self.replay_cli(bundle)
        payload = json.loads((bundle / ISSUE_121).read_bytes())
        rows = [*payload["aggregate"].values(), *payload["boundaries"]]
        unavailable = [label for label in LABELS  # in outcome order, whichever outcomes the proof left unavailable
                       for row in rows if row["boundary"] == label and row["state"] == "projection_unavailable"]
        if unavailable:
            line = f"{REPLAY}: projection_unavailable: {','.join(unavailable)}\n"
            self.assertEqual((status, stdout, stderr), (2, b"", line.encode()))
            return
        self.assertEqual((status, stderr), (0, b""))
        result = json.loads(stdout)
        self.assertEqual(stdout, canonical_bytes(result))
        self.assertEqual(result, {
            "schema_version": 3, "kind": "review-feasibility-retained-result", "anchor_sha256": self.digest,
            "issue_121": {name: payload[name] for name in ("aggregate", "boundaries", "operational_effects")},
            "issue_100": {"history_edge_count": 543, "pending_overlap_count": 4,
                          "disposition_counts": {"historical_process": 8, "integrated": 38, "candidate": 69},
                          "fixture_sha256": hashlib.sha256((bundle / ISSUE_100).read_bytes()).hexdigest()}})

    def test_substitutions_refused_under_the_trusted_digest(self):
        trusted = (self.bundle / ANCHOR_NAME).read_bytes()
        for site in TRUSTED_SITES:
            with self.subTest(site=site):
                anchor, raw = self.forged(substituted(*site))
                bundle = self.copied_bundle()
                for name, data in {**raw, ANCHOR_NAME: canonical_bytes(anchor)}.items():
                    (bundle / name).write_bytes(data)
                # Coherent under the forger's own digest, so the trusted digest alone refuses it.
                self.assertEqual(authenticate(bundle, telemetry_digest(anchor)), (anchor, raw))
                self.assertEqual(self.replay_cli(bundle), (2, b"", f"{REPLAY}: invalid: anchor_digest\n".encode()))
                (bundle / ANCHOR_NAME).write_bytes(trusted)  # the trusted anchor over the substituted members
                self.assertEqual(self.replay_cli(bundle), (2, b"", f"{REPLAY}: invalid: member_digest\n".encode()))

    def test_git_free_substitutions_refused_under_trust_injection(self):
        rebuilt = self.forged()
        self.assertEqual(rebuilt, authenticate(self.bundle, self.digest))  # the rebuild alone changes nothing
        validate_bundle(*rebuilt, **PINS)
        changes = [(error, site, substituted(*site)) for error, sites in GIT_FREE_SITES.items() for site in sites]
        # Beside the unaltered issue-121 payload, a malformed sibling is invalid whatever that payload's outcomes.
        changes += [
            (Issue100Error, "issue-100 without its summary", lambda _, payloads: payloads[ISSUE_100].pop("summary")),
            (EstimateError, "estimate truncated by a row", lambda _, payloads: payloads[ESTIMATE]["rows"].pop())]
        for error, site, change in changes:
            with self.subTest(site=site), self.assertRaises(error):
                validate_bundle(*self.forged(change), **PINS)

    def test_outputs_hold_no_bodies_paths_or_credentials(self):
        outputs = {path.name: path.read_bytes() for path in self.bundle.iterdir()}
        outputs["summary"] = self.summary
        policy = (SOURCE / "home/common/agent-skills/artifact-budget-policy.json").read_bytes()
        shards = sorted((self.root / ARCHIVE).glob("*.shards/*"))
        self.assertTrue(shards)
        secrets = {line for shard in shards for line in shard.read_bytes().split(b"\n") if len(line) > 40}
        secrets |= {line.strip() for line in policy.split(b"\n") if len(line.strip()) > 16}
        secrets |= {line for line in self.key.read_bytes().split(b"\n") if line}
        secrets |= {self.key.with_suffix(".pub").read_bytes().split()[1]}
        secrets |= {self.tmp.name.encode(), self.env["HOME"].encode(), os.environ["HOME"].encode()}
        for name, data in outputs.items():
            self.assertEqual([secret[:80] for secret in secrets if secret in data], [], name)
