# Task 4: `advance` — classification and the gates up to `authorized`

**Files:**
- Create: `python/agent_tools/promotion_lifecycle.py`
- Modify: `python/agent_tools/promotion.py` (the `advance` subparser, handler and `write_in_place`)
- Modify: `tests/promotion_test_support.py` (bundle writer and the `LifecycleFixture` mixin)
- Create: `tests/test_promotion_lifecycle.py`
- Modify: `justfile` (`tests/test_promotion_lifecycle.py \` joins `agent-workflow-tests` after `tests/test_promotion_documents.py \`)

Read the spec's "The ordered classification" and "The lifecycle" (table, Corroboration,
Evidence). D6, D7, D8, D12, D14, D15, D22, D23 and D29 govern this task.

**Interfaces:**
- Consumes: Task 1 `promotion_schema` names (`STATES`, `CLASSIFICATION_RULES`, `Refusal`,
  `violation`, `load_strict`, `is_safe_relative_path`, `symlinked_component`,
  `validate_document`, `CANDIDATE_KIND`); Task 2 `promotion.resolve`, `Project`, `render`,
  `emit`, `read_document`; Task 3 `agent_gate_bundle.verify_bundle`, `BundleIntegrityError`,
  `GATE_CONTRACT`, `GATE_VERSION`.
- Produces in `promotion_lifecycle.py` (Task 5 extends these):

```python
TRANSITIONS: dict[tuple[str, str], str]   # edge -> gate family
# This task's edges exactly (Task 5 adds ("authorized","promoted") and ("promoted","superseded")):
# ("captured","evaluating"): "bind"        ("captured","withdrawn"): "rationale"
# ("evaluating","decision_ready"): "measure"
# ("evaluating","rejected"), ("evaluating","withdrawn"): "rationale"
# ("decision_ready","authorized"): "authorize"  ("decision_ready","evaluating"): "remeasure"
# ("decision_ready","rejected"), ("decision_ready","withdrawn"), ("authorized","rejected"): "rationale"
ARGUMENT_TARGETS = {"tracker_ref": ("evaluating",), "bundle": ("decision_ready",),
                    "authorized_by": ("authorized",), "rationale": ("rejected", "withdrawn"),
                    "superseded_by": ("superseded",)}

@dataclasses.dataclass(frozen=True)
class Arguments:
    tracker_ref: int | None = None
    bundle: str | None = None
    authorized_by: str | None = None
    rationale: str | None = None
    superseded_by: str | None = None

def anchor_line_present(root: Path, relative: str, anchor: str) -> bool
def classify(candidate: dict, root: Path) -> dict
def corroboration_satisfied(candidate: dict) -> bool
def resolve_bundle(root: Path, relative: str | None) -> tuple[str, str]   # (bundle_id, state)
def authorization_gates(candidate: dict, root: Path) -> None   # D29 order, minus the authorizer
def advance(candidate: dict, target: str, root: Path, here: str, arguments: Arguments) -> dict
```

- Produces in `promotion.py`: `write_in_place(path: Path, document: dict) -> None`.
- Produces in support: `write_bundle(root, relative, state) -> Path`, `LifecycleFixture`.

**Invariants:**
- `advance` never mutates its input; it returns a deep copy with the new `state` and exactly one
  appended history entry `{"from": <old>, "to": target, "actor": authorized_by on the
  authorize edge else None, "rationale": rationale on rationale edges else None}`.
- A `(state, target)` pair absent from `TRANSITIONS` refuses `transition_not_permitted`.
  Every `Refusal` carries the candidate's current `candidate_id` and `state`.
- `anchor_line_present` is `False` unless `symlinked_component(root, relative) is None`, the
  path is a regular file (`is_file()` and not `is_symlink()`), it reads and decodes as UTF-8,
  and some `line.rstrip() == anchor` over `splitlines()` (D23). Any `OSError` → `False`.
- `classify` walks `CLASSIFICATION_RULES` in order: rule 1 matches iff `anchor_line_present`
  on the destination; rules 2–7 match iff `destination.layer == rule_id`. It returns
  `{"rule", "rule_id", "declared_layer": destination.layer, "overridden_by_rule_1": rule == 1}`,
  and raises `RuntimeError` if the walk ends (D6). It runs only on the `bind` edge.
- `corroboration_satisfied`: two or more citations with distinct `repository` values whose
  `path` and `anchor` are non-empty, or a non-empty `platform_governance`.
- `resolve_bundle` refuses `evidence_unresolvable` (pointer `/evidence/bundle_path`) for a
  `None` or unsafe relative path, a symlinked component, an unreadable or non-UTF-8 file,
  a `load_strict` failure, or a `BundleIntegrityError`; paths resolve against `root`, never
  the working directory.
- Gate order (D29), first failure wins: `bind` → `tracker_ref_required`; `rationale` →
  `rationale_required` for a missing or blank value; `measure` → corroboration, then the bundle,
  recording `evidence = {"bundle_path": <as given>, "bundle_id", "state", "gate_contract":
  GATE_CONTRACT, "gate_version": GATE_VERSION}`; `authorize` → `authorization_gates`, then
  `authorizer_required` for a missing or blank `--authorized-by`; `remeasure` → `evidence = None`
  (classification untouched).
- `authorization_gates`: corroboration; `classification is None` → `transition_not_permitted`
  (pointer `/classification`; D24); `evidence is None` or a re-resolved `bundle_id` different
  from `evidence.bundle_id` → `evidence_unresolvable`; the re-verified state (never the
  recorded one) `unmeasured` → `evidence_unmeasured`, `rejected` → `evidence_rejected`; `classification.rule == 6` and
  `native_admission` null or not `admitted` → `native_admission_pending`.
- The `advance` parser declares `--candidate` (required), `--to` (required, `choices=STATES`),
  `--repo-root`, `--tracker-ref`, `--bundle`, `--authorized-by`, `--rationale` and
  `--superseded-by` (a plain string until Task 5 adds its shape `type`).
- The command handler: a flag given for a `--to` outside its `ARGUMENT_TARGETS` entry is
  `parser.error` (exit 2, no JSON); `--tracker-ref` uses a positive-int argparse `type`;
  after reading, a `--tracker-ref` on a candidate not in `captured` is `parser.error` (D29).
  Order: resolve → read → `validate_document` (+ `kind == CANDIDATE_KIND`) → the post-read
  `--tracker-ref` check → `advance` → `write_in_place` → `emit`. `here` is `project.id`.
- `write_in_place`: `tempfile.mkstemp(dir=path.parent, prefix=".promotion-", suffix=".tmp")`,
  write `render(document)`, copy the original mode, `os.replace`; unlink the temp on any
  failure. No lock (D14). Any refusal leaves the file byte-identical.

- [ ] **Step 1: Extend the support module** (append; add `import tempfile`,
  `from agent_tools import agent_gate_bundle as gate` and the relative import below)

```python
from .test_agent_gate_bundle import context, flat, stratum

EVIDENCE = {"approved": lambda: flat(stratum(context(1000, 800))),
            "rejected": lambda: flat(stratum(context(1000, 999))),
            "unmeasured": lambda: None}


def write_bundle(root: Path, relative: str, state: str) -> Path:
    """A real `assemble_bundle` output in `state`, written at `root/relative`."""
    manifest = {"identity": {"bound": {}, "pinned": {}},
                "expansion": {"expanded": False, "checkpoint_ref": None}}
    return write_json(root / relative,
                      gate.assemble_bundle(manifest, EVIDENCE[state](), [], None, state))


class LifecycleFixture:
    """Mixin for a unittest.TestCase: a fixture root, capture() and advance()."""

    BUNDLE = ".agents/artifacts/evidence/b.json"

    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()
        self.root = self.tmp / "project"
        self.root.mkdir()
        self.env = make_env(self.tmp, resolved_project(self.root))

    def capture(self, document=None, name="c.json"):
        source = write_json(self.tmp / "draft.json", document or draft())
        target = self.root / ".agents/knowledge/promotions/candidates" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        code, payload, err = run(self.env, "capture", "--input", str(source),
                                 "--output", str(target))
        self.assertEqual(code, 0, (payload, err))
        return target

    def advance(self, path, target, *flags):
        return run(self.env, "advance", "--candidate", str(path), "--to", target, *flags)

    def step(self, path, target, *flags):
        code, payload, err = self.advance(path, target, *flags)
        self.assertEqual(code, 0, (payload, err))
        return payload

    def walk(self, path, to, bundle_state="approved"):
        """captured -> evaluating -> decision_ready -> authorized, stopping at `to`."""
        self.step(path, "evaluating", "--tracker-ref", "7")
        if to == "evaluating":
            return
        write_bundle(self.root, self.BUNDLE, bundle_state)
        self.step(path, "decision_ready", "--bundle", self.BUNDLE)
        if to == "decision_ready":
            return
        self.step(path, "authorized", "--authorized-by", "fagenorn")

    def assert_refused(self, path, target, code, *flags, exit_code=3):
        before = path.read_bytes()
        got, payload, err = self.advance(path, target, *flags)
        self.assertEqual(got, exit_code, (payload, err))
        if code is None:
            self.assertIsNone(payload)
        else:
            self.assertEqual(payload["error"]["code"], code)
        self.assertEqual(path.read_bytes(), before)
        return payload
```

- [ ] **Step 2: Write the failing suite `tests/test_promotion_lifecycle.py`**

```python
"""Seam 1 for classification and the gates up to `authorized` (#127 D6, D7, D29)."""

import json
import subprocess
import sys
import unittest

from .promotion_test_support import (LifecycleFixture, citation, draft, run, write_bundle,
                                     write_json)

HEADING = "### Investigate before changing"
DESTINATION = "home/common/agent-skills/standards/the-bar.md"


class ClassificationTest(LifecycleFixture, unittest.TestCase):
    def classification(self, document=None):
        path = self.capture(document)
        return self.step(path, "evaluating", "--tracker-ref", "7")["classification"]

    def test_binding_requires_a_tracker_ref_and_records_it(self):
        path = self.capture()
        payload = self.assert_refused(path, "evaluating", "tracker_ref_required")
        self.assertEqual(payload["error"]["state"], "captured")
        after = self.step(path, "evaluating", "--tracker-ref", "7")
        self.assertEqual([after["state"], after["tracker"]["ref"], after["history"][-1]],
                         ["evaluating", 7, {"from": "captured", "to": "evaluating",
                                            "actor": None, "rationale": None}])
        self.assertEqual(json.loads(path.read_text(encoding="utf-8")), after)

    def test_rule_one_overrides_on_a_whole_line_match(self):
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(f"# The bar\n{HEADING}   \n", encoding="utf-8")
        self.assertEqual(self.classification(), {
            "rule": 1, "rule_id": "duplicate_of_platform",
            "declared_layer": "standard_layer", "overridden_by_rule_1": True})

    def test_prefix_headings_and_symlinked_components_never_match_rule_one(self):
        real = self.root / "real"
        real.mkdir()
        (real / "the-bar.md").write_text(HEADING + "\n", encoding="utf-8")
        (self.root / "linked").symlink_to(real, target_is_directory=True)
        (self.root / DESTINATION).parent.mkdir(parents=True)
        (self.root / DESTINATION).write_text(HEADING + " code\n", encoding="utf-8")
        linked = dict(draft()["destination"], path="linked/the-bar.md")
        for document in (draft(), draft(destination=linked)):
            with self.subTest(path=document["destination"]["path"]):
                self.assertEqual(self.classification(document)["rule"], 4)

    def test_each_declared_layer_matches_its_own_rule(self):
        admission = {"gate": "issue-64", "decision": "pending", "irreducible_scenario": "s"}
        names = {"native_adapter": "adapter.claude.hooks",
                 "native_extension": "native.codex.review"}
        layers = ("project_local", "core_module", "standard_layer", "native_adapter",
                  "native_extension", "out_of_scope_product")
        for rule, layer in enumerate(layers, start=2):
            with self.subTest(layer=layer):
                destination = dict(draft()["destination"], layer=layer,
                                   name=names.get(layer, "the-bar"))
                document = draft(destination=destination, native_admission=(
                    admission if layer == "native_extension" else None))
                got = self.classification(document)
                self.assertEqual([got["rule"], got["rule_id"], got["overridden_by_rule_1"]],
                                 [rule, layer, False])


class TransitionTest(LifecycleFixture, unittest.TestCase):
    def test_pairs_outside_the_table_are_not_permitted(self):
        path = self.capture()
        for target, flags in (("authorized", ("--authorized-by", "x")), ("promoted", ()),
                              ("captured", ()), ("decision_ready", ("--bundle", "b.json"))):
            with self.subTest(target=target):
                self.assert_refused(path, target, "transition_not_permitted", *flags)

    def test_rationale_edges_and_terminal_states(self):
        path = self.capture()
        self.assert_refused(path, "withdrawn", "rationale_required")
        self.assert_refused(path, "withdrawn", "rationale_required", "--rationale", "  ")
        after = self.step(path, "withdrawn", "--rationale", "duplicate idea")
        self.assertEqual(after["history"][-1]["rationale"], "duplicate idea")
        self.assert_refused(path, "evaluating", "transition_not_permitted", exit_code=3)

    def test_flags_without_meaning_for_the_target_are_usage_errors(self):
        path = self.capture()
        self.assert_refused(path, "evaluating", None, "--bundle", "b.json", exit_code=2)
        self.assert_refused(path, "withdrawn", None, "--tracker-ref", "3", exit_code=2)
        self.assert_refused(path, "evaluating", None, "--tracker-ref", "0", exit_code=2)

    def test_an_invalid_candidate_is_an_invalid_document(self):
        path = self.capture()
        document = json.loads(path.read_text(encoding="utf-8"))
        write_json(path, dict(document, state="done"))
        self.assert_refused(path, "evaluating", "invalid_document", "--tracker-ref", "1",
                            exit_code=2)

    def test_no_subcommand_offers_an_override(self):
        for sub in ("capture", "advance", "evaluate", "validate"):
            with self.subTest(sub=sub):
                proc = subprocess.run(
                    [sys.executable, "-m", "agent_tools.promotion", sub, "--help"],
                    capture_output=True, text=True, env=self.env, timeout=60, check=False)
                text = proc.stdout.lower()
                self.assertEqual(proc.returncode, 0)
                self.assertTrue(text.startswith(f"usage: promotion {sub}"), text[:80])
                for word in ("override", "force", "skip"):
                    self.assertNotIn(word, text)


class EvidenceGateTest(LifecycleFixture, unittest.TestCase):
    def test_decision_ready_needs_distinct_corroboration(self):
        single = {"repositories": [citation()], "platform_governance": None}
        same = {"repositories": [citation(), citation(path="OTHER.md")],
                "platform_governance": None}
        for name, corroboration in (("single", single), ("same", same)):
            with self.subTest(case=name):
                path = self.capture(draft(corroboration=corroboration), name=f"{name}.json")
                self.walk(path, "evaluating")
                write_bundle(self.root, self.BUNDLE, "approved")
                self.assert_refused(path, "decision_ready", "corroboration_insufficient",
                                    "--bundle", self.BUNDLE)
        governed = self.capture(draft(corroboration={
            "repositories": [], "platform_governance": "platform ADR 12"}), name="g.json")
        self.walk(governed, "decision_ready", "unmeasured")

    def test_decision_ready_needs_a_bundle_that_verifies(self):
        path = self.capture()
        self.walk(path, "evaluating")
        edited = write_bundle(self.root, "edited.json", "rejected")
        document = json.loads(edited.read_text(encoding="utf-8"))
        write_json(edited, dict(document, state="approved"))
        (self.root / "text.json").write_text("not json", encoding="utf-8")
        for flags in ((), ("--bundle", "absent.json"), ("--bundle", "../b.json"),
                      ("--bundle", "edited.json"), ("--bundle", "text.json")):
            with self.subTest(flags=flags):
                self.assert_refused(path, "decision_ready", "evidence_unresolvable", *flags)
        write_bundle(self.root, self.BUNDLE, "unmeasured")
        after = self.step(path, "decision_ready", "--bundle", self.BUNDLE)
        bundle = json.loads((self.root / self.BUNDLE).read_text(encoding="utf-8"))
        self.assertEqual(after["evidence"], {
            "bundle_path": self.BUNDLE, "bundle_id": bundle["bundle_id"],
            "state": "unmeasured", "gate_contract": "issue-70", "gate_version": 1})

    def test_authorized_requires_approved_evidence_positively(self):
        for state, code in (("unmeasured", "evidence_unmeasured"),
                            ("rejected", "evidence_rejected")):
            with self.subTest(state=state):
                path = self.capture(name=f"{state}.json")
                self.walk(path, "decision_ready", state)
                self.assert_refused(path, "authorized", code, "--authorized-by", "fagenorn")
        path = self.capture(name="approved.json")
        self.walk(path, "decision_ready", "approved")
        self.assert_refused(path, "authorized", "authorizer_required")
        after = self.step(path, "authorized", "--authorized-by", "fagenorn")
        self.assertEqual(after["history"][-1], {"from": "decision_ready", "to": "authorized",
                                                "actor": "fagenorn", "rationale": None})

    def test_the_recorded_bundle_is_reverified_at_authorized(self):
        path = self.capture()
        self.walk(path, "decision_ready", "approved")
        bundle = self.root / self.BUNDLE
        document = json.loads(bundle.read_text(encoding="utf-8"))
        write_json(bundle, dict(document, generated_at="2000-01-01T00:00:00Z",
                                bundle_id="sha256:" + "0" * 64))
        self.assert_refused(path, "authorized", "evidence_unresolvable",
                            "--authorized-by", "fagenorn")

    def test_a_native_extension_needs_admission(self):
        destination = dict(draft()["destination"], layer="native_extension",
                           name="native.claude.review")
        for decision, expected in (("pending", "native_admission_pending"), ("admitted", None)):
            with self.subTest(decision=decision):
                path = self.capture(draft(destination=destination, native_admission={
                    "gate": "issue-64", "decision": decision, "irreducible_scenario": "s"}),
                    name=f"{decision}.json")
                self.walk(path, "decision_ready", "approved")
                if expected:
                    self.assert_refused(path, "authorized", expected,
                                        "--authorized-by", "fagenorn")
                else:
                    self.step(path, "authorized", "--authorized-by", "fagenorn")

    def test_remeasure_clears_evidence_and_binds_the_ref_once(self):
        path = self.capture()
        self.walk(path, "decision_ready", "unmeasured")
        self.assert_refused(path, "evaluating", None, "--tracker-ref", "9", exit_code=2)
        before = json.loads(path.read_text(encoding="utf-8"))
        after = self.step(path, "evaluating")
        self.assertEqual([after["evidence"], after["classification"], after["tracker"]["ref"]],
                         [None, before["classification"], 7])
```

- [ ] **Step 3: Run and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_lifecycle.py 2>&1 | tail -3`
Expected: FAILED — `invalid choice: 'advance'`.

- [ ] **Step 4: Implement** `promotion_lifecycle.py` and the `advance` path of `promotion.py`
  per the invariants. The lifecycle module never prints, parses argv or writes files (D2).

- [ ] **Step 5: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_lifecycle.py tests/test_promotion_documents.py 2>&1 | tail -3`
Expected: `OK`, 34 tests (15 new).
Run: `just build 2>&1 | tail -3` — success.

- [ ] **Step 6: Commit** — `git add` the five files; subject
  `feat(issue-127/T4): promotion advance through authorized`, with the trailers.
