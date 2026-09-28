# Task 2: `capture` and `evaluate`, the resolver child, P1 feasibility

**Files:**
- Modify: `python/agent_tools/promotion_schema.py` (the pure constructors)
- Modify: `python/agent_tools/promotion.py` (`resolve`, output handling, two subcommands)
- Modify: `tests/test_promotion_documents.py` (two new classes)

Read the spec sections "The three documents" (`tracker.create_command`, the body lines,
`promotion-evaluation`), "The repository root, the project id and the tracker slug" and
"CLI surface". D1, D4, D5, D13, D14, D19, D25 and D30 govern this task.

**Interfaces:**
- Consumes (Task 1, `promotion_schema`): `SCHEMA_VERSION`, `CANDIDATE_KIND`, `DRAFT_KIND`,
  `EVALUATION_KIND`, `TRACKER_LABEL`, `AUTHORED_MEMBERS`, `Refusal`, `violation`,
  `authored_section`, `candidate_id_of`, `validate_document`. (`promotion`): `read_document`,
  `render`, `emit`, `emit_refusal`, `build_parser`, `main`. (Support): `PromotionCase`
  base in the suite, `make_env`, `resolved_project`, `run`, `write_json`, `draft`, `citation`.
- Produces in `promotion_schema.py`:

```python
def create_command(repo_slug: str, document_path: str, draft: dict,
                   candidate_id: str) -> list[str]
def mint_candidate(draft: dict, repo_slug: str, document_path: str) -> dict
def mint_evaluation(repository: str, revision: str | None, commands: list[str],
                    candidates: list[str]) -> dict
```

- Produces in `promotion.py` (Tasks 4–5 reuse `resolve`):

```python
class Project(NamedTuple):
    root: Path          # Path(project.root), as the resolver printed it
    id: str             # project.id
    tracker_kind: str   # bindings.tracker.kind
    repo_slug: str | None
def resolve(repo_root: str | None) -> Project           # Refusal contract_unresolvable
def output_target(raw: str, root: Path) -> tuple[Path, str]   # (absolute path, root-relative posix)
def write_new(target: Path, document: dict) -> None       # O_CREAT|O_EXCL; output_exists
```

**Invariants:**
- `resolve` runs `["resolve-project", "resolve"]` plus `["--repo-root", repo_root]` only when
  the flag was given, via `subprocess.run(..., capture_output=True, text=True, timeout=60,
  check=False)`. `FileNotFoundError`, a timeout, a non-zero exit, unparseable stdout or a
  missing/non-string `project.root`, `project.id` or `bindings.tracker.kind` all raise
  `Refusal("contract_unresolvable", [violation("", <message>)])`; when stdout carries
  `{"error": {"code": C}}` the message is exactly `C` (D5).
- `capture` additionally refuses `contract_unresolvable` unless `tracker_kind == "github"` and
  `repo_slug` is a non-empty string.
- `output_target`: a relative `raw` is taken from the working directory; its parent must be an
  existing directory, else `output_outside_root`; `parent.resolve() / name` must lie under
  `root.resolve()`, else `output_outside_root` (D25, D30). The second value is that path relative
  to `root.resolve()`, as posix.
- `write_new` never creates a directory and never overwrites; a refusal leaves any existing file
  byte-identical (D14).
- Order for `capture`: resolve → tracker check → `output_target` → `read_document(--input)` →
  `validate_document` (and `kind == DRAFT_KIND`, else `invalid_document` at `/kind`) →
  `mint_candidate` → `write_new` → `emit`. For `evaluate`: resolve → `output_target` →
  `mint_evaluation` → `validate_document` (non-empty → `invalid_document`) → `write_new` → `emit`.
- `mint_candidate` returns `SCHEMA_VERSION`, `CANDIDATE_KIND`, `candidate_id_of(draft)`,
  `state "captured"`, the authored section verbatim, `classification/evidence/deployment: None`,
  `tracker {"ref": None, "label": TRACKER_LABEL, "create_command": create_command(...)}` and
  `history [{"from": None, "to": "captured", "actor": None, "rationale": None}]`.
- `create_command` is exactly the spec's argv. Body lines, `"\n"`-joined:
  `candidate: <id>`, `document: <path>`, `source: <repo> <path>@<revision or "unpinned">#<anchor>`,
  `destination: <layer> <owner>/<name> <path>#<anchor>`, then one
  `corroboration: <repo> <path>#<anchor>` per citation, then `platform_governance: provided`
  iff that member is non-null (D30). The statement never appears.
- `mint_evaluation` sets `outcome` to `"empty"` iff `candidates == []`, keeps `commands` and
  `candidates` in the given order, and sets `evaluation_id` to `telemetry_digest` of the
  document without `evaluation_id` (D13). Nothing executes a command (D19).
- Parser: `capture --input --output [--repo-root]`; `evaluate --output --command (append,
  required) [--candidate (append)] [--revision] [--repo-root]`. No override/force option.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_promotion_documents.py`;
  add `import json` and `from agent_tools.canonical import telemetry_digest` at the top)

```python
CANDIDATES = ".agents/knowledge/promotions/candidates"


class CaptureTest(PromotionCase):
    def capture(self, document=None, output=None, *extra, env=None, cwd=None):
        source = write_json(self.root / ".agents/knowledge/promotions/drafts/d.json",
                            document or draft())
        (self.root / CANDIDATES).mkdir(parents=True, exist_ok=True)
        target = output or self.root / CANDIDATES / "c.json"
        code, payload, err = run(env or self.env, "capture", "--input", str(source),
                                 "--output", str(target), *extra, cwd=cwd)
        return code, payload, target

    def test_capture_writes_and_prints_a_captured_candidate(self):
        code, payload, target = self.capture(None, None, "--repo-root", str(self.root))
        self.assertEqual(code, 0, payload)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        authored = {m: draft()[m] for m in ("lesson", "destination", "corroboration",
                                            "local_duplicates", "native_admission")}
        self.assertEqual(payload["candidate_id"], telemetry_digest(authored))
        self.assertEqual([payload["state"], payload["classification"], payload["evidence"],
                          payload["deployment"], payload["tracker"]["ref"]],
                         ["captured", None, None, None, None])
        self.assertEqual(payload["history"], [{"from": None, "to": "captured",
                                               "actor": None, "rationale": None}])
        self.assertEqual(run(self.env, "validate", "--input", str(target))[0], 0)

    def test_create_command_is_the_exact_labelled_argv(self):
        payload = self.capture()[1]
        body = "\n".join([
            f"candidate: {payload['candidate_id']}",
            "document: .agents/knowledge/promotions/candidates/c.json",
            "source: fagenorn/argus AGENTS.md@unpinned### How we collaborate",
            "destination: standard_layer standards/the-bar "
            "home/common/agent-skills/standards/the-bar.md#### Investigate before changing",
            "corroboration: fagenorn/argus AGENTS.md### How we collaborate",
            "corroboration: elevenyellow/nodocom CLAUDE.md### How we collaborate"])
        self.assertEqual(payload["tracker"]["create_command"], [
            "gh", "issue", "create", "--repo", "fagenorn/nix-config",
            "--label", "promotion-candidate",
            "--title", "promotion: Investigate before changing", "--body", body])
        self.assertNotIn(draft()["lesson"]["statement"], body)

    def test_governance_proof_adds_its_line(self):
        document = draft(corroboration={"repositories": [], "platform_governance": "ADR"})
        body = self.capture(document)[1]["tracker"]["create_command"][-1]
        self.assertEqual(body.splitlines()[-1], "platform_governance: provided")

    def test_the_tracker_is_never_touched(self):
        self.assertEqual(self.capture()[0], 0)
        self.assertEqual(sorted(p.name for p in (self.tmp / "bin").iterdir()),
                         ["resolve-project"])

    def test_repo_root_is_passed_only_when_given(self):
        self.capture(None, None, "--repo-root", str(self.root))
        (self.root / CANDIDATES / "c.json").unlink()
        self.capture(cwd=self.root)
        argv = [json.loads(line) for line in (self.tmp / "resolver-argv.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        self.assertEqual(argv, [["resolve", "--repo-root", str(self.root)], ["resolve"]])

    def test_output_must_be_new_and_under_the_root(self):
        code, payload, target = self.capture(None, self.tmp / "outside.json")
        self.assertEqual((code, payload["error"]["code"]), (2, "output_outside_root"))
        self.assertFalse(target.exists())
        code, payload, target = self.capture(None, self.root / "missing" / "c.json")
        self.assertEqual((code, payload["error"]["code"]), (2, "output_outside_root"))
        self.assertFalse(target.parent.exists())
        existing = write_json(self.root / CANDIDATES / "c.json", {"keep": 1})
        before = existing.read_bytes()
        code, payload, _ = self.capture()
        self.assertEqual((code, payload["error"]["code"]), (2, "output_exists"))
        self.assertEqual(existing.read_bytes(), before)

    def test_resolver_failures_are_contract_unresolvable(self):
        refused = '{"error":{"code":"not_onboarded","repair_id":"x","violations":[]}}'
        cases = {
            "not_onboarded": make_env(self.tmp, resolver_exit=2, resolver_stdout=refused),
            "garbage": make_env(self.tmp, resolver_stdout="nope"),
            "gitlab": make_env(self.tmp, resolved_project(self.root, kind="gitlab")),
            "absent": dict(self.env, PATH=str(self.tmp / "empty-bin")),
        }
        for name, env in cases.items():
            with self.subTest(case=name):
                code, payload, target = self.capture(env=env)
                self.assertEqual((code, payload["error"]["code"]),
                                 (2, "contract_unresolvable"))
                self.assertFalse(target.exists())
                if name == "not_onboarded":
                    self.assertEqual(payload["error"]["violations"][0]["message"],
                                     "not_onboarded")

    def test_an_invalid_draft_writes_nothing(self):
        bad = draft(destination=dict(draft()["destination"], layer="global"))
        code, payload, target = self.capture(bad)
        self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
        self.assertFalse(target.exists())


class EvaluateTest(PromotionCase):
    SWEEP = "gh issue list --repo fagenorn/nix-config --label promotion-candidate --state open"

    def evaluate(self, *extra):
        target = self.root / "evaluation.json"
        code, payload, _ = run(self.env, "evaluate", "--output", str(target), *extra)
        return code, payload, target

    def test_an_empty_sweep_records_its_commands_verbatim(self):
        code, payload, target = self.evaluate("--command", self.SWEEP,
                                              "--command", "rg -n 'Investigate' .")
        self.assertEqual(code, 0, payload)
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), payload)
        self.assertEqual([payload["outcome"], payload["candidates"], payload["commands"],
                          payload["scope"]],
                         ["empty", [], [self.SWEEP, "rg -n 'Investigate' ."],
                          {"repository": "fagenorn/nix-config", "revision": None}])
        body = {k: v for k, v in payload.items() if k != "evaluation_id"}
        self.assertEqual(payload["evaluation_id"], telemetry_digest(body))

    def test_named_candidates_make_the_outcome_found(self):
        ids = ["sha256:" + "b" * 64, "sha256:" + "a" * 64]
        code, payload, _ = self.evaluate("--command", "x", "--candidate", ids[0],
                                         "--candidate", ids[1], "--revision", "f" * 40)
        self.assertEqual((code, payload["outcome"], payload["candidates"],
                          payload["scope"]["revision"]), (0, "found", ids, "f" * 40))

    def test_command_is_required(self):
        code, payload, target = self.evaluate()
        self.assertEqual((code, payload, target.exists()), (2, None, False))

    def test_malformed_flags_are_invalid_documents(self):
        for flags, pointer in ((("--candidate", "abc"), "/candidates/0"),
                               (("--revision", "xyz"), "/scope/revision")):
            with self.subTest(pointer=pointer):
                code, payload, target = self.evaluate("--command", "x", *flags)
                self.assertEqual((code, payload["error"]["code"]), (2, "invalid_document"))
                self.assertIn(pointer, [v["pointer"] for v in payload["error"]["violations"]])
                self.assertFalse(target.exists())

    def test_recorded_commands_never_run(self):
        marker = self.tmp / "ran"
        self.assertEqual(self.evaluate("--command", f"touch {marker}")[0], 0)
        self.assertFalse(marker.exists())
```

- [ ] **Step 2: Run and watch them fail**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_documents.py 2>&1 | tail -3`
Expected: FAILED — `invalid choice: 'capture'` usage errors (exit 2, no JSON).

- [ ] **Step 3: Implement** the constructors in `promotion_schema.py` and `resolve`,
  `output_target`, `write_new` and the two handlers in `promotion.py` per the invariants.
  Handlers stay thin: argv → functions → `emit`.

- [ ] **Step 4: Verify**

Run: `PYTHONPATH=python python3 -m unittest tests/test_promotion_documents.py 2>&1 | tail -3`
Expected: `OK`, 19 tests.
Run: `if python3 -c 'import sys; sys.exit(0 if "override" in open("python/agent_tools/promotion.py").read().lower() else 1)'; then exit 1; fi`
Run: `just build 2>&1 | tail -3` — success.

- [ ] **Step 5: Commit** — `git add` the three files; subject
  `feat(issue-127/T2): promotion capture and evaluate`, with the trailers.

- [ ] **Step 6: P1 feasibility (package P1 = Tasks 1–2, D20, D28)**

```bash
set -euo pipefail
BASE="$(git log --reverse --format=%H -F --grep='feat(issue-127/T1):' | head -1)"
test -n "$BASE"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/rp-XXXXXX")/review.json"
review-package .agents/artifacts/plans/2026-09-28-issue-127-learning-promotion-loop.md \
  "$(git rev-parse "$BASE^")" "$(git rev-parse HEAD)" "$OUT" > "$OUT.report"
grep -q '"state":"complete"' "$OUT.report"
```

Expected: exit 0. A `decompose_required` report means a member diff exceeds 65536 bytes:
split the offending file before continuing. Nothing to commit for this step.
