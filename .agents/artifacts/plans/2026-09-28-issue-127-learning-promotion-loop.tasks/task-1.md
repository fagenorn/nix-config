# Task 1: Schema, validator and `promotion validate` (package P1)

**Files:**
- Create: `python/agent_tools/promotion_schema.py`
- Create: `python/agent_tools/promotion.py`
- Create: `tests/promotion_test_support.py`
- Create: `tests/test_promotion_documents.py`
- Modify: `lib/agent-tools.nix` (append `"promotion"` to `commands`)
- Modify: `justfile` (the `promotion *args` recipe; `tests/test_promotion_documents.py` joins `agent-workflow-tests`)

Read the spec sections "The three documents", "CLI surface" and "Exit codes" first. D2, D5,
D12, D13, D15, D16, D30 govern this task. The read-only v1 file
`/Users/anis/tmp/nix-config/.worktrees/worktree-issue-127-learning-promotion-loop-v1/home/common/agent-skills/scripts/promotion-registry.py`
has a reusable validator shape (member helpers); adapt ideas, never copy its `canonical_digest`
or `load_sibling`, and never modify that worktree.

**Interfaces — produces in `promotion_schema.py` (later tasks import these exact names):**

```python
COMMAND_NAME = "promotion"
SCHEMA_VERSION = 1
DRAFT_KIND, CANDIDATE_KIND, EVALUATION_KIND = ("promotion-candidate-draft",
    "promotion-candidate", "promotion-evaluation")
KINDS = (DRAFT_KIND, CANDIDATE_KIND, EVALUATION_KIND)
STATES = ("captured", "evaluating", "decision_ready", "authorized", "promoted",
          "rejected", "withdrawn", "superseded")
TERMINAL_STATES = ("rejected", "withdrawn", "superseded")
PROMOTED = "promoted"
LAYERS = ("project_local", "core_module", "standard_layer", "native_adapter",
          "native_extension", "out_of_scope_product")
AGENT_IDS = ("claude", "codex")
REMOVE_DISPOSITION = "remove"
PROJECT_ONLY_RESIDUE = "project_only_residue"
DISPOSITIONS = (REMOVE_DISPOSITION, PROJECT_ONLY_RESIDUE)
ADMISSION_GATE = "issue-64"
ADMISSION_DECISIONS = ("pending", "admitted", "refused")
BUNDLE_STATES = ("approved", "rejected", "unmeasured")
EVALUATION_OUTCOMES = ("empty", "found")
TRACKER_LABEL = "promotion-candidate"
KNOWLEDGE_RELATIVE = (".agents", "knowledge", "promotions")
DRAFTS_RELATIVE = KNOWLEDGE_RELATIVE + ("drafts",)
CANDIDATES_RELATIVE = KNOWLEDGE_RELATIVE + ("candidates",)
EVALUATIONS_RELATIVE = KNOWLEDGE_RELATIVE + ("evaluations",)
AUTHORED_MEMBERS = ("lesson", "destination", "corroboration", "local_duplicates",
                    "native_admission")
LOCAL_DUPLICATES_MEMBER = "local_duplicates"
DUPLICATE_MEMBERS = ("repository", "path", "sha256", "disposition")
DRAFT_MEMBERS = ("schema_version", "kind") + AUTHORED_MEMBERS
CANDIDATE_MEMBERS = (("schema_version", "kind", "candidate_id", "state")
                     + AUTHORED_MEMBERS
                     + ("classification", "evidence", "deployment", "tracker", "history"))
EVALUATION_MEMBERS = ("schema_version", "kind", "evaluation_id", "scope", "commands",
                      "candidates", "outcome")
FORBIDDEN_MEMBER_NAMES = ("created_at", "generated_at", "time", "timestamp")
CLASSIFICATION_RULES = ((1, "duplicate_of_platform"),) + tuple(
    (number, layer) for number, layer in enumerate(LAYERS, start=2))
GATE_CODES = ("transition_not_permitted", "tracker_ref_required", "rationale_required",
              "authorizer_required", "corroboration_insufficient", "evidence_unresolvable",
              "evidence_unmeasured", "evidence_rejected", "native_admission_pending",
              "destination_missing", "duplicate_present", "promotion_reconciliation_required")
TOOL_CODES = ("unreadable_input", "invalid_document", "output_exists",
              "output_outside_root", "contract_unresolvable", "internal_failure")
TITLE_MAX, TEXT_MAX, ANCHOR_MAX = 120, 1000, 200
CITATIONS_MAX, DUPLICATES_MAX, COMMANDS_MAX = 8, 16, 16
INTERNAL_FAILURE_MESSAGE = "the promotion module failed unexpectedly"

def violation(pointer: str, message: str) -> dict            # {"pointer", "message"}
class Refusal(Exception):
    def __init__(self, code: str, violations: list[dict], candidate_id=None, state=None)
    exit_code: int   # 3 for GATE_CODES, 2 for TOOL_CODES; ValueError for any other code
def load_strict(text: str) -> object       # json.loads + both canonical hooks; ValueError
def is_safe_relative_path(value: object) -> bool
def symlinked_component(root: Path, relative: str) -> Path | None
def authored_section(document: dict) -> dict  # {m: document[m] for m in AUTHORED_MEMBERS}
def candidate_id_of(document: dict) -> str    # telemetry_digest(authored_section(document))
def validate_document(document: object) -> list[dict]   # [] means valid
```

**Interfaces — produces in `promotion.py`:** `read_document(path: str) -> dict` (raises
`Refusal`), `render(document) -> str` (the canonical line with `"\n"`), `emit(document) -> int`
(prints, returns 0), `emit_refusal(refusal) -> int`, `build_parser() -> argparse.ArgumentParser`
(`prog=COMMAND_NAME`, required subcommands), `main(argv=None) -> int`.

**Interfaces — produces in `tests/promotion_test_support.py`:** `NULL_DIGEST`,
`resolved_project`, `make_env`, `run`, `write_json`, `citation`, `duplicate`, `draft`,
`candidate_document`, `evaluation_document` (code below). Consumes: nothing earlier.

**Invariants:**
- `validate_document` returns violations sorted by `(pointer, message)` and de-duplicated. Pointers
  are JSON pointers (`/lesson/title`, `/local_duplicates/0/sha256`); an unexpected member's
  violation points at that member (`/extra`); a missing member points at the member it names.
- It closes every object's member set, types every lifecycle member, checks `rule_id` against
  `CLASSIFICATION_RULES`, `evidence.gate_contract`/`gate_version` against
  `agent_gate_bundle.GATE_CONTRACT`/`GATE_VERSION` (imported, never copied), and forbids the
  clock names at any depth. It never recomputes an id and never ties section presence to
  `state` (D13).
- `schema_version` must be the int `1` (`True` is refused); ints are `type(x) is int`.
- Path members (`destination.path`, `lesson.source.path`, `corroboration.repositories[].path`,
  `local_duplicates[].path`, `evidence.bundle_path`, `deployment.removed[]`/`retained[]`) must
  pass `is_safe_relative_path`: a non-empty `str`, not absolute, with no `..` part (D15).
- `symlinked_component(root, relative)` walks `relative`'s parts from `root` (never testing `root`),
  returns the first component that `is_symlink()`, and returns `None` when a component is
  absent or none is linked.
- Name rules: `native_adapter` → `destination.name` matches
  `^adapter\.(claude|codex)\.[a-z0-9][a-z0-9_-]*$`; `native_extension` →
  `^native\.(claude|codex)\.[a-z0-9][a-z0-9_-]*$` and `native_admission` must be non-null
  (violation at `/native_admission`).
- Revisions are 40 lowercase hex or null; `sha256` members are 64 lowercase hex or null;
  `candidate_id`, `evaluation_id`, `evidence.bundle_id` and `candidates[]` are `sha256:` + 64 hex.
- `tracker = {ref: int ≥1 | null, label: TRACKER_LABEL, create_command: non-empty list of
  non-empty str}`; `history` a non-empty list of `{from: State|null, to: State, actor: str|null,
  rationale: str|null}`; `evaluation.outcome` is `empty` iff `candidates == []` (violation at
  `/outcome`); `commands` 1..16 strings of 1..1000 chars.
- `validate` resolves nothing and writes nothing; it prints `{"valid":true}` and exits 0.
- `main` is the single boundary: `SystemExit` re-raised; `Refusal` → `emit_refusal`; any other
  exception → one `promotion: <repr>` stderr line, then `internal_failure` with
  `[violation("", INTERNAL_FAILURE_MESSAGE)]`, exit 2 (D12).
- `read_document`: `OSError`/`UnicodeError` → `unreadable_input` at `""`; `ValueError` from
  `load_strict` or a non-dict → `invalid_document` at `""` (D30).

- [ ] **Step 1: Write the support module**

```python
"""Shared support for the promotion suites (#127 D16 seam 1, D28).

The hermetic runner, the stub resolver and the document builders. It declares
no TestCase, so it is support rather than a suite and is not listed as one.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from agent_tools.canonical import telemetry_digest

# An authored `null` sha256. Fixtures pass this sentinel, never `digest or computed` (D16).
NULL_DIGEST = object()


def resolved_project(root, project_id="fagenorn/nix-config", slug="fagenorn/nix-config",
                     kind="github"):
    """A ResolvedProject with the real resolver's member shape for `root`."""
    return {"schema_version": 1,
            "project": {"id": project_id, "name": "fixture", "root": str(root)},
            "bindings": {"tracker": {"cli": "gh", "kind": kind, "repo_slug": slug,
                                     "credential_env": {"unset_before_invocation": []}}},
            "capabilities": {}}


def make_env(tmp: Path, resolved=None, *, resolver_exit=0, resolver_stdout=None):
    """An env whose PATH holds only a `resolve-project` stub. The stub appends its
    argv to `tmp/resolver-argv.jsonl`, prints `resolved` (or `resolver_stdout`
    verbatim) and exits `resolver_exit`."""
    bin_dir = tmp / "bin"
    bin_dir.mkdir(exist_ok=True)
    payload = tmp / "resolver-stdout.txt"
    payload.write_text(resolver_stdout if resolver_stdout is not None
                       else json.dumps(resolved), encoding="utf-8")
    stub = bin_dir / "resolve-project"
    stub.write_text(
        f"#!{sys.executable}\nimport json, sys\n"
        f"open({str(tmp / 'resolver-argv.jsonl')!r}, 'a').write("
        "json.dumps(sys.argv[1:]) + '\\n')\n"
        f"sys.stdout.write(open({str(payload)!r}).read())\n"
        f"raise SystemExit({resolver_exit})\n", encoding="utf-8")
    stub.chmod(0o755)
    return {"PATH": str(bin_dir), "PYTHONPATH": os.environ["PYTHONPATH"],
            "HOME": str(tmp), "TMPDIR": str(tmp), "LANG": "C"}


def run(env, *args, cwd=None):
    """One `python -m agent_tools.promotion` run: (exit, parsed stdout or None, stderr)."""
    proc = subprocess.run([sys.executable, "-m", "agent_tools.promotion", *args],
                          capture_output=True, text=True, timeout=60, env=env,
                          cwd=None if cwd is None else str(cwd), check=False)
    return (proc.returncode, json.loads(proc.stdout) if proc.stdout.strip() else None,
            proc.stderr)


def write_json(path: Path, document) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def citation(repository="fagenorn/argus", path="AGENTS.md", anchor="## How we collaborate"):
    return {"repository": repository, "path": path, "revision": None, "anchor": anchor}


def duplicate(repository="fagenorn/argus", path="AGENTS.md", sha256=NULL_DIGEST,
              disposition="remove"):
    return {"repository": repository, "path": path,
            "sha256": None if sha256 is NULL_DIGEST else sha256, "disposition": disposition}


def draft(**overrides):
    document = {
        "schema_version": 1, "kind": "promotion-candidate-draft",
        "lesson": {"title": "Investigate before changing",
                   "statement": "Read what already governs the code before changing it.",
                   "source": citation()},
        "destination": {"layer": "standard_layer", "owner": "standards", "name": "the-bar",
                        "path": "home/common/agent-skills/standards/the-bar.md",
                        "anchor": "### Investigate before changing"},
        "corroboration": {"repositories": [citation(),
                                           citation("elevenyellow/nodocom", "CLAUDE.md")],
                          "platform_governance": None},
        "local_duplicates": [duplicate()],
        "native_admission": None,
    }
    document.update(overrides)
    return document


AUTHORED = ("lesson", "destination", "corroboration", "local_duplicates", "native_admission")


def candidate_document(**overrides):
    body = draft()
    authored = {member: body[member] for member in AUTHORED}
    document = {"schema_version": 1, "kind": "promotion-candidate",
                "candidate_id": telemetry_digest(authored), "state": "captured", **authored,
                "classification": None, "evidence": None, "deployment": None,
                "tracker": {"ref": None, "label": "promotion-candidate",
                            "create_command": ["gh", "issue", "create"]},
                "history": [{"from": None, "to": "captured", "actor": None,
                             "rationale": None}]}
    document.update(overrides)
    return document


def evaluation_document(**overrides):
    document = {"schema_version": 1, "kind": "promotion-evaluation",
                "evaluation_id": "sha256:" + "c" * 64,
                "scope": {"repository": "fagenorn/nix-config", "revision": None},
                "commands": ["rg -n Investigate ."], "candidates": [], "outcome": "empty"}
    document.update(overrides)
    return document
```

- [ ] **Step 2: Write the failing suite**

```python
"""Seams 1 and 2 for the promotion documents (#127 D16): validate, capture, evaluate."""

import tempfile
import unittest
from pathlib import Path

from .promotion_test_support import (candidate_document, citation, draft, duplicate,
                                     evaluation_document, make_env, resolved_project,
                                     run, write_json)


class PromotionCase(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name).resolve()
        self.root = self.tmp / "project"
        self.root.mkdir()
        self.env = make_env(self.tmp, resolved_project(self.root))


class ValidateTest(PromotionCase):
    def validate(self, document=None, text=None):
        path = self.tmp / "doc.json"
        if text is None:
            write_json(path, document)
        else:
            path.write_text(text, encoding="utf-8")
        return run(self.env, "validate", "--input", str(path))

    def assert_fault(self, document, pointer):
        code, payload, _ = self.validate(document)
        self.assertEqual(code, 2, payload)
        self.assertEqual(payload["error"]["code"], "invalid_document")
        self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])

    def test_each_kind_validates_and_nothing_is_resolved_or_written(self):
        for document in (draft(), candidate_document(), evaluation_document()):
            with self.subTest(kind=document["kind"]):
                self.assertEqual(self.validate(document)[:2], (0, {"valid": True}))
        self.assertFalse((self.tmp / "resolver-argv.jsonl").exists())
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()),
                         ["bin", "doc.json", "project", "resolver-stdout.txt"])

    def test_section_presence_is_never_tied_to_state(self):
        evidence = {"bundle_path": "b.json", "bundle_id": "sha256:" + "d" * 64,
                    "state": "unmeasured", "gate_contract": "issue-70", "gate_version": 1}
        self.assertEqual(self.validate(candidate_document(evidence=evidence))[0], 0)

    def test_draft_faults_name_their_pointer(self):
        d = draft()
        faults = {
            "/lesson/title": draft(lesson=dict(d["lesson"], title="x" * 121)),
            "/lesson/source/path": draft(lesson=dict(d["lesson"], source=dict(
                citation(), path="/etc/passwd"))),
            "/lesson/source/revision": draft(lesson=dict(d["lesson"], source=dict(
                citation(), revision="abc"))),
            "/destination/layer": draft(destination=dict(d["destination"], layer="global")),
            "/destination/path": draft(destination=dict(d["destination"], path="a/../b.md")),
            "/destination/name": draft(destination=dict(d["destination"],
                                                        layer="native_adapter")),
            "/native_admission": draft(destination=dict(
                d["destination"], layer="native_extension", name="native.claude.op")),
            "/corroboration/repositories": draft(corroboration={
                "repositories": [citation()] * 9, "platform_governance": None}),
            "/local_duplicates/0/sha256": draft(local_duplicates=[duplicate(sha256="abc")]),
            "/local_duplicates/0/disposition": draft(
                local_duplicates=[duplicate(disposition="delete")]),
            "/schema_version": draft(schema_version=True),
            "/kind": draft(kind="promotion-other"),
            "/extra": draft(extra=1),
            "/lesson/generated_at": draft(lesson=dict(d["lesson"], generated_at="x")),
        }
        for pointer, document in faults.items():
            with self.subTest(pointer=pointer):
                self.assert_fault(document, pointer)

    def test_candidate_and_evaluation_faults_name_their_pointer(self):
        classification = {"rule": 4, "rule_id": "core_module",
                          "declared_layer": "standard_layer", "overridden_by_rule_1": False}
        evidence = {"bundle_path": "b.json", "bundle_id": "sha256:" + "d" * 64,
                    "state": "approved", "gate_contract": "issue-71", "gate_version": 1}
        faults = {
            "/candidate_id": candidate_document(candidate_id="sha256:xyz"),
            "/state": candidate_document(state="done"),
            "/classification/rule_id": candidate_document(classification=classification),
            "/evidence/gate_contract": candidate_document(evidence=evidence),
            "/tracker/ref": candidate_document(tracker={
                "ref": 0, "label": "promotion-candidate", "create_command": ["gh"]}),
            "/tracker/label": candidate_document(tracker={
                "ref": None, "label": "other", "create_command": ["gh"]}),
            "/history/0/to": candidate_document(history=[
                {"from": None, "to": "done", "actor": None, "rationale": None}]),
            "/outcome": evaluation_document(candidates=["sha256:" + "e" * 64]),
            "/commands": evaluation_document(commands=[]),
            "/scope/revision": evaluation_document(scope={
                "repository": "fagenorn/nix-config", "revision": "xyz"}),
        }
        for pointer, document in faults.items():
            with self.subTest(pointer=pointer):
                self.assert_fault(document, pointer)

    def test_unloadable_input_is_refused_with_the_empty_pointer(self):
        for text in ('{"kind": 1, "kind": 2}', '{"x": NaN}', "[]", "{ broken"):
            with self.subTest(text=text):
                code, payload, _ = self.validate(text=text)
                self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
                self.assertEqual(payload["error"]["violations"][0]["pointer"], "")
        code, payload, _ = run(self.env, "validate", "--input", str(self.tmp / "absent.json"))
        self.assertEqual((code, payload["error"]["code"]), (2, "unreadable_input"))
        self.assertEqual(payload["error"]["candidate_id"], None)

    def test_usage_errors_exit_2_without_json(self):
        code, payload, _ = run(self.env, "validate")
        self.assertEqual((code, payload), (2, None))
```

- [ ] **Step 3: Run it and watch it fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_documents.py 2>&1 | tail -5`
Expected: FAILED — `No module named agent_tools.promotion`.

- [ ] **Step 4: Implement `promotion_schema.py` and the `validate` path of `promotion.py`**

Module docstrings describe live behaviour only. `promotion.py` holds no policy (D2): the
`validate` handler is `read_document(args.input)`, then
`violations = validate_document(document)`; non-empty → `Refusal("invalid_document",
violations)`; else `emit({"valid": True})`. Subparsers for `capture`, `evaluate` and
`advance` are added by Tasks 2 and 4 — do not add stubs now. End the file with
`if __name__ == "__main__": raise SystemExit(main())`. `emit_refusal` prints
`{"error": {"code", "candidate_id", "state", "violations"}}` through `render` and returns
`refusal.exit_code`.

- [ ] **Step 5: Wire Nix and Just**

In `lib/agent-tools.nix` append `"promotion"` to `commands`. In the `justfile`, after
`agent-gate-bundle *args`, add

```
# Capture, evaluate, validate and advance promotion candidates (#127)
promotion *args:
  PYTHONPATH="{{agent_tools_path}}" python3 -m agent_tools.promotion {{args}}
```

and add `tests/test_promotion_documents.py \` to `agent-workflow-tests` after
`tests/test_agent_gate_bundle.py \`.

- [ ] **Step 6: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_documents.py 2>&1 | tail -3`
Expected: `OK`, 6 tests.
Run: `just promotion validate --input /nonexistent; test $? -eq 2`
Run: `just build 2>&1 | tail -3` — expected: success (the import check covers both modules).
Run: `if grep -rn "sys.path\|importlib\|__file__" python/agent_tools/promotion*.py; then exit 1; fi`

- [ ] **Step 7: Commit**

```bash
git add python/agent_tools/promotion_schema.py python/agent_tools/promotion.py \
  tests/promotion_test_support.py tests/test_promotion_documents.py lib/agent-tools.nix justfile
git commit -m "feat(issue-127/T1): promotion schema, validator and validate subcommand"
```
(with the two trailer lines from Global Constraints).
