# Task 3: Built parity and the full-shape tier

The real-input acceptance of both encodings and the built-launcher parity of their refusals (spec § *Measured feasibility*, § *Published refusals*, § *Test seams*; CP10, CP11, CP17, CP18; RP7, RP10, RP11). No `python/` byte changes: the tool this task runs is the G2 pin.

**Files:**
- Modify: `tests/test_review_retained_full.py`
- Modify: `tests/test_agent_tools_launchers.py`

**Interfaces:**
- Consumes (Tasks 1 and 2): `model_100(issue_repo, live_repo, archive_dir, pins, limits)`, `expand_100(payload)`, `validate_100(payload, pins) -> model`, `model_121(repo, pins, task7_pins, authority)`, `expand_121(payload)`, `validate_121(payload, pins, table) -> model`, `build_witness(components, models, raw)`, `validate_bundle(...)` returning the two models by member name.
- Consumes (the tier module today): `RetainedFullTest` with `cls.root`, `cls.bundle`, `cls.digest`, `cls.table`, `cls.authority`, `forged(change)`, `copied_bundle()`, `replay_cli(bundle)`; `substituted(*site)`, `retained_root()`, `tool_commit()`, `derive_argv(...)`, `watch_root(...)`; the constants `ARCHIVE`, `GROUPS`, `LABELS`, `WITNESS`, `ISSUE_100`, `ISSUE_121`, `ESTIMATE`, `PINS`. In the launcher module: `AgentToolsLauncherTest.retained_pair(command, args)`, `self.hostile`, `RETAINED`, `RetainedLauncherTest` and its `self.full`.
- Produces (tier module): `MEMBER_CAP`, `BUNDLE_CAP`, `EXPANDERS`, the module function `rebuilt(bundle, digest, change)`, which the launcher class calls through `self.full`, and three new cases. Produces (launcher module): `canonical(value)`, `stub_bundle(directory) -> str` and one new portable case.

**Invariants:**
- The launcher module still imports no `agent_tools` at module level; `stub_bundle` uses `json` and `hashlib` only (CP18). The retained class reaches the tier module through `self.full`, as it does today.
- Every site in `TRUSTED_SITES` and `GIT_FREE_SITES` exists whatever the proof produced, and each `GIT_FREE_SITES` row is refused with the error it is listed under. They were measured at planning on a bundle derived from the real retained objects. A site that is accepted Git-free (a record's bytes or digest, an entry id, a candidate's live entry, exchanged issue-121 `edges` rows) must not be added (CP17).
- The size case asserts bounds, never the measured sizes (CP10). No case pins an output digest (CP11).
- Nothing skips once `AGENT_RETAINED_ROOT` is set, the retained root is compared before and after each test, and every mutation happens in a copied bundle (RP10, RP11). `model_100` and `model_121` only read the root.
- `substituted` and every case this task does not name are unchanged.

- [ ] **Step 1: Watch the tier fail.** At this task's starting commit, before any edit:

```bash
AGENT_RETAINED_ROOT=/Users/anis/tmp/nix-config PYTHONPATH=python python3 -m unittest \
  tests.test_review_retained_full.RetainedFullTest.test_replay_with_sources_unreachable 2>&1 | tail -3
```

  Expected: `KeyError: 'aggregate'`, because the unedited case reads SOURCE members from the compact payload.

- [ ] **Step 2: Edit the tier module.** Import `expand_100`, `model_100`, `expand_121`, `model_121` and `validate_121`, and name issue 254 in the module docstring. Replace the two site tables and their comments, from the line after `FAILED_GATE` to the end of `GIT_FREE_SITES`:

```python
EXPANDERS = {ISSUE_100: expand_100, ISSUE_121: expand_121}
# CORE's whole-record cap for one review member, and this tier's bound on the five files together: three
# members' worth of the 524,288 B aggregate (CP10).
MEMBER_CAP, BUNDLE_CAP = 65536, 3 * 65536

# RP7 layer 1: one member of each component group, one record digest in each retained payload, one estimate
# blob and one edge's record reference. A site is a component group or a fixture name, then the keys and
# indices down to one string or count; a packed string is one site.
TRUSTED_SITES = (
    ("tool", "commit"), ("issue_121", "head"), ("issue_100", "live"), ("archive", "manifest_sha256"),
    ("estimate", "task7_blob"), (ISSUE_121, "records", "aggregate.actual", "rows", 0, 2),
    (ISSUE_100, "record_sha256"), (ESTIMATE, "rows", -1, "input", "blob"), (ISSUE_100, "edges", 0, 0))
# RP7 layer 2: every component member the pins determine and the payload members that the pins, the estimate
# table or the payload's own tables determine, under the error that refuses it. Each site exists whatever
# the proof produced: `aggregate.actual` (outcome 0) and `tasks-7-8` (outcome 4) are measured in every
# bundle. `tool.commit`, `tool.files`, `archive.shards`, a record's bytes or digest, an entry id and a
# candidate's live entry are not determined without Git (RP7, CP17), so they are not here.
GIT_FREE_SITES = {
    WitnessError: (
        *(("issue_121", member) for member in ("base", "head", "tree", "signer_sha256")),
        *(("issue_100", member) for member in ("base", "head", "live", "parent_edges_sha256")),
        *(("archive", member) for member in ("producer_sha256", "manifest_sha256")),
        *(("estimate", member) for member in ("prerequisite_commit", "prerequisite_tree", "plan_root_blob",
                                               "task7_blob", "model_version", "table_sha256")),
        *(("tool", member) for member in ("artifact_policy_sha256", "packing_policy_sha256", "record_policy_sha256")),
        (ISSUE_121, "outcomes", 0, "result_tree"), (ISSUE_121, "outcomes", 0, "measurement", "artifact_policy_sha256")),
    EstimateError: ((ESTIMATE, "rows_sha256"), (ESTIMATE, "identities", "task7_blob"),
                    (ESTIMATE, "rows", -1, "record_bytes"), (ESTIMATE, "counts", "moves")),
    ContributionError: (
        (ISSUE_121, "range", "head"), (ISSUE_121, "classes", 0, 0), (ISSUE_121, "classes", 0, 1),
        (ISSUE_121, "anchors", 0, 0), (ISSUE_121, "anchors", 0, 1), (ISSUE_121, "anchors", 0, 2),
        (ISSUE_121, "signer_sha256"), (ISSUE_121, "records", "aggregate.actual", "rows", 0, 0),
        (ISSUE_121, "records", "tasks-7-8", "rows", 0, 1), (ISSUE_121, "outcomes", 1, "estimate_refs", 0),
        (ISSUE_121, "outcomes", 4, "result_tree"), (ISSUE_121, "outcomes", 4, "prerequisite", "tree"),
        (ISSUE_121, "record_table_policy", "policy_sha256")),
    Issue100Error: (
        (ISSUE_100, "range", "live"), (ISSUE_100, "commits"), (ISSUE_100, "parents", 0, 0), (ISSUE_100, "edges", 0, 0),
        (ISSUE_100, "tables", "fresh", "paths", 0), (ISSUE_100, "tables", "fresh", "bytes", 0),
        (ISSUE_100, "tables", "historical", "bytes", 0),
        (ISSUE_100, "tables", "fresh", "record_table_policy", "policy_sha256"), (ISSUE_100, "process", 0),
        (ISSUE_100, "pending_overlaps", 0, 0), (ISSUE_100, "criteria", 0, "text")),
}
```

  Add this module function before `RetainedFullTest`, and reduce `RetainedFullTest.forged` to `return rebuilt(self.bundle, self.digest, change)`:

```python
def rebuilt(bundle, digest, change=lambda components, payloads: None):
    """`(anchor, raw)` of the bundle in `bundle` after `change(components, payloads)`, with every in-bundle hash
    recomputed as a forger would: the estimate group's table digest when the table changed, each member's
    bytes and digest, the witness and the anchor. The witness digests each changed payload's own expansion,
    and the bundle's where the change leaves none. Without a change it is the bundle itself."""
    anchor, raw = authenticate(bundle, digest)
    components = {group: anchor[group] for group in GROUPS}
    payloads = {name: json.loads(raw[name]) for name in (ISSUE_100, ISSUE_121, ESTIMATE)}
    models = {name: expand(payloads[name]) for name, expand in EXPANDERS.items()}
    change(components, payloads)
    forged = {name: canonical_bytes(payload) for name, payload in payloads.items()}
    if forged[ESTIMATE] != raw[ESTIMATE]:
        components["estimate"]["table_sha256"] = telemetry_digest(payloads[ESTIMATE])
    for name, expand in EXPANDERS.items():
        try:
            models[name] = expand(payloads[name])
        except (ContributionError, Issue100Error):
            pass
    forged[WITNESS] = canonical_bytes(build_witness(components, {**models, ESTIMATE: payloads[ESTIMATE]}, forged))
    return build_anchor(components, forged), forged
```

  Add these three cases:

```python
    def test_bundle_files_fit_the_whole_record_caps(self):
        sizes = {path.name: path.stat().st_size for path in self.bundle.iterdir()}
        self.assertEqual(set(sizes), {ANCHOR_NAME, WITNESS, ISSUE_100, ISSUE_121, ESTIMATE})
        for name, size in sizes.items():
            with self.subTest(name):
                self.assertLessEqual(size, MEMBER_CAP)
        self.assertLessEqual(sum(sizes.values()), BUNDLE_CAP)
        self.assertEqual(self.authority.limits.member_max_bytes, MEMBER_CAP)  # CORE's cap, as the policy states it
        versions = [json.loads((self.bundle / name).read_bytes())["schema_version"] for name in (ISSUE_100, ISSUE_121)]
        self.assertEqual(versions, [2, 4])

    def test_issue100_expansion_is_the_source_model_fact_for_fact(self):
        model = model_100(self.root, self.root, self.root / ARCHIVE, ISSUE_100_PINS, self.authority.limits)
        payload = json.loads((self.bundle / ISSUE_100).read_bytes())
        expansion = expand_100(payload)
        self.assertEqual((payload["schema_version"], model["schema_version"]), (2, 1))
        self.assertEqual(canonical_bytes(expansion), canonical_bytes(model))  # SOURCE's encoding, byte for byte
        self.assertEqual(canonical_bytes(validate_100(payload, ISSUE_100_PINS)), canonical_bytes(model))
        self.assertEqual((len(expansion["parent_edges"]), sum(len(edge["records"]) for edge in expansion["edges"])),
                         (91, 543))
        labels = [row["disposition"] for row in expansion["contributions"]]
        self.assertEqual([labels.count(name) for name in ("historical_process", "integrated", "candidate")],
                         [8, 38, 69])
        pending = [row["pending"] is not None for row in expansion["contributions"]
                   if row["disposition"] == "candidate"]
        self.assertEqual((len(labels), pending.count(False), pending.count(True)), (115, 65, 4))
        self.assertEqual((len(expansion["pending_overlaps"]), expansion["summary"]["reconciled"]), (4, 0))
        self.assertEqual([row["state"] for row in expansion["criteria"]], ["superseded"] * 5 + ["governing"] * 5)
        self.assertEqual({name: (sum(record["bytes"] for record in table["records"]), len(table["records"]))
                          for name, table in expansion["tables"].items()},
                         {"historical": (1005707, 115), "fresh": (1012913, 115)})

    def test_issue121_expansion_is_the_source_model_fact_for_fact(self):
        model = model_121(self.root, ISSUE_121_PINS, TASK7_PINS, self.authority)
        payload = json.loads((self.bundle / ISSUE_121).read_bytes())
        expansion = expand_121(payload)
        self.assertEqual((payload["schema_version"], model["schema_version"]), (4, 3))
        self.assertEqual(canonical_bytes(expansion), canonical_bytes(model))  # SOURCE's encoding, byte for byte
        self.assertEqual(canonical_bytes(validate_121(payload, ISSUE_121_PINS, self.table)), canonical_bytes(model))
        commits = [commit for commit, _, _ in ISSUE_121_PINS.assignments]
        owners = [row["owner"] for row in expansion["classes"]]
        self.assertEqual((len(owners), owners.count(0), sum(1 for owner in owners if owner)), (30, 12, 18))
        late = commits.index("8e6f0681908cb1ba3d352be5d26540dab731ffeb")  # the late Task-3 fix, after Task 6 began
        self.assertEqual((late, owners[late], 6 in owners[:late]), (24, 3, True))
        self.assertEqual([(edge["commit"], edge["parent"]) for edge in expansion["edges"]],
                         list(zip(commits, [ISSUE_121_PINS.base, *commits])))
        self.assertEqual(len(expansion["anchors"]), 9)
        rows = [expansion["aggregate"]["actual"], expansion["aggregate"]["projected"], *expansion["boundaries"]]
        self.assertEqual([row["boundary"] for row in rows], list(LABELS))
        common = {"boundary", "state", "prerequisite", "edge_ids", "estimate_refs"}
        for row in rows:  # each outcome is measured or an authenticated unavailable one, with no other field
            scoped = [record for record in expansion["records"] if record["scope"] == row["boundary"]]
            with self.subTest(outcome=row["boundary"]):
                if row["state"] == "measured":
                    self.assertEqual(set(row), common | {"result_tree", "record_refs", "measurement"})
                    self.assertEqual(row["record_refs"], [record["id"] for record in scoped])
                else:
                    self.assertEqual((row["state"], set(row), scoped),
                                     ("projection_unavailable", common | {"failure"}, []))
                    self.assertEqual(set(row["failure"]), {"stage", "code", "evidence_refs"})
```

  Three small edits follow. `test_replay_with_sources_unreachable` reads `payload = expand_121(json.loads(...))`. In `test_git_free_substitutions_refused_under_trust_injection` the issue-100 extra change becomes `payloads[ISSUE_100].pop("process")`, labelled "issue-100 without its process list", and two changes are added that put a member back into SOURCE's encoding: `payloads.update({ISSUE_100: expand_100(payloads[ISSUE_100])})` under `Issue100Error`, and the same for `ISSUE_121` with `expand_121` under `ContributionError`. `test_issue100_domains_are_exact_and_distinct` needs no edit: the compact payload keeps `tables.<name>.record_table_policy`.

- [ ] **Step 3: Edit the launcher module.** Add `import shutil`. Add before `AgentToolsLauncherTest`:

```python
# SOURCE's encodings of the two retained members (#254): replay refuses them whatever digests surround them.
SOURCE_ENCODED = {"issue-100-derived.json": {"kind": "issue-100-retained-history", "schema_version": 1},
                  "issue-121.json": {"kind": "issue-121-retained-history", "schema_version": 3}}


def canonical(value) -> bytes:
    """CORE's canonical JSON bytes, spelled here because this module imports no `agent_tools`."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("ascii") + b"\n"


def stub_bundle(directory) -> str:
    """Write a five-file bundle around `SOURCE_ENCODED` into the new `directory`; the anchor's digest.

    The anchor, the witness and the member rows agree with one another, so replay authenticates the bundle
    and refuses it only for what it reads inside the retained members."""
    groups = dict.fromkeys(("tool", "issue_121", "issue_100", "archive", "estimate"), {})
    raw = {name: canonical(value) for name, value in {**SOURCE_ENCODED, "task7-estimate.json": {}}.items()}

    def rows():
        return [{"path": name, "bytes": len(raw[name]), "raw_sha256": hashlib.sha256(raw[name]).hexdigest()}
                for name in sorted(raw)]
    raw["derivation-witness.json"] = canonical({
        "schema_version": 2, "kind": "review-feasibility-derivation-witness", "components": groups,
        "fixtures": rows(), "tables": [], "table_policies": {}})
    anchor = {"schema_version": 2, "kind": "review-feasibility-derivation-anchor", **groups,
              "payload": {"encoding": "canonical-json-ascii-lf/v1", "members": rows()}}
    directory.mkdir()
    for name, data in {**raw, "derivation-anchor.json": canonical(anchor)}.items():
        (directory / name).write_bytes(data)
    return "sha256:" + hashlib.sha256(canonical(anchor)[:-1]).hexdigest()
```

  In `test_retained_commands_refuse_alike_from_source_and_built`, add a fourth case: the derive command with the same four repository options, `--tool-commit` of forty zeros and `--output-dir` of `self.hostile / "absent"` gives `tool_closure`; the closing assertion also requires that this directory does not exist. Add to `AgentToolsLauncherTest`:

```python
    def test_replay_refuses_stub_bundles_alike_from_source_and_built(self):
        """The bundle refusals of #254 on a bundle that holds no retained fact, so no source is reachable: SOURCE's
        encodings under coherent digests, a replacement anchor, a changed member and a partial bundle."""
        def replace_anchor(bundle):
            path = bundle / "derivation-anchor.json"
            path.write_bytes(canonical({**json.loads(path.read_bytes()), "tool": {"commit": "0" * 40}}))
        cases = (("invalid_payload", lambda bundle: None), ("anchor_digest", replace_anchor),
                 ("member_digest", lambda bundle: (bundle / "issue-121.json").write_bytes(canonical({}))),
                 ("member_set", lambda bundle: (bundle / "task7-estimate.json").unlink()))
        for code, alter in cases:
            with self.subTest(code=code):
                bundle = self.hostile / f"stub-{code}"
                digest = stub_bundle(bundle)
                alter(bundle)
                before = {path.name: path.read_bytes() for path in bundle.iterdir()}
                built, source = self.retained_pair(
                    "replay-retained", ["--fixtures-dir", str(bundle), "--expected-anchor-sha256", digest])
                self.assertEqual(built, source)
                self.assertEqual(built, (2, b"", f"replay-retained: invalid: {code}\n".encode()))
                self.assertEqual({path.name: path.read_bytes() for path in bundle.iterdir()}, before)
```

  Append to `RetainedLauncherTest.test_real_derivation_and_replay_match_from_source_and_built`:

```python
        # A rehashed alteration of the real bundle: invalid under the forger's own digest, and never authentic
        # under the trusted one.
        full, trusted = self.full, json.loads(summaries["built"])["anchor_sha256"]
        forged = Path(shutil.copytree(self.hostile / "built-bundle", self.hostile / "forged-bundle"))
        anchor, raw = full.rebuilt(forged, trusted, full.substituted(full.ISSUE_100, "process", 0))
        for name, data in {**raw, full.ANCHOR_NAME: full.canonical_bytes(anchor)}.items():
            (forged / name).write_bytes(data)
        for digest, code in ((full.telemetry_digest(anchor), "invalid_payload"), (trusted, "anchor_digest")):
            with self.subTest(code=code):
                built, source = self.retained_pair(
                    replay, ["--fixtures-dir", str(forged), "--expected-anchor-sha256", digest])
                self.assertEqual(built, source)
                self.assertEqual(built, (2, b"", f"{replay}: invalid: {code}\n".encode()))
```

- [ ] **Step 4: Verify.**

```bash
set -euo pipefail
PIN=<the G2 source commit>
AGENT_RETAINED_TOOL_COMMIT="$PIN" just agent-retained-tests /Users/anis/tmp/nix-config 2>&1 | tail -6
just agent-installed-skill-tests 2>&1 | tail -3
just agent-workflow-tests 2>&1 | tail -3
if ! grep -q 'def stub_bundle' tests/test_agent_tools_launchers.py; then exit 1; fi
test "$(git diff --name-only "$PIN" HEAD -- python | wc -l)" -eq 0
```

  Before the run, set `MEMBER_CAP = 60000` once and run `test_bundle_files_fit_the_whole_record_caps` as in Step 1: it must fail on `issue-100-derived.json`. Restore the constant. The retained run ends `OK` with no `skipped`, and it must be quiescent (RP11): if the root comparison differs, the run is void and is repeated. The installed run ends `OK` and includes the four stub cases and the `tool_closure` case. The last line shows that no `python/` byte changed since the pin; if this task finds a `python/` defect, stop: the fix reopens Task 1 or 2 and repeats G2.

- [ ] **Step 5: Commit.** Stage only the two Files. Check that `printf %s "$subject" | wc -c` is at most 64, then commit `test(review): prove compact payloads on the retained tier (#254)`. A review-fix commit uses `fix(review): address Task-3 review findings (#254)`.

- [ ] **Step 6: G1 (controller).** Run the plan root's G1 at the new `HEAD`, record this task's `actual_ranges` and refresh `actual_evidence`, then renew G0 at `--completed-through 3`, which equals the actual gate. G3 follows.

## Forecast basis

Estimates, priced as in Task 1. Applied to the base files at planning, the edits above measure 24,169 B / +124 / −40 for the tier module and 9,911 B / +73 / −2 for the launcher module. With room for the module docstring and review fixes: 30,720 B / +160 / −55 and 11,264 B / +85 / −6.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64],"id":3,"records":[{"bounds":[{"added_lines":160,"boundary":"compact","deleted_lines":55,"record_bytes":30720,"support":{"covers":["t3-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-1","last_task":3,"owner":3,"path":"tests/test_review_retained_full.py"},{"bounds":[{"added_lines":85,"boundary":"compact","deleted_lines":6,"record_bytes":11264,"support":{"covers":["t3-2"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"t3-2","last_task":3,"owner":3,"path":"tests/test_agent_tools_launchers.py"}]}}
```
