# Task 4: `check-projections` and the `resolve` freshness gate

**Files:**
- Modify: `home/common/agent-skills/scripts/resolve-project.py`
- Test: `home/common/agent-skills/tests/test_resolve_project.py`

**Interfaces:**
- Consumes, from Tasks 1–3: `class ContractError(Exception)` with `code`, `repair_id`, `violations`; `discover_root(repo_root) -> Path`; `load_contract(root) -> dict`; `validate_contract(source) -> list[dict]`; `normalize_bindings(source_bindings, root) -> dict`; `compute_capabilities(bindings, root, declarations) -> dict`; `read_projection_source(root, entry) -> bytes`; `render_projection(entry, source_bytes) -> bytes`; `projection_status(root, entry) -> str` returning `"in_sync"`, `"missing"` or `"stale"`; `emit_json(value) -> int`; `emit_error(code, repair_id, violations) -> int`; `main(argv=None) -> int`, whose `check-projections` subparser currently returns a `resolver_failure` placeholder that this task replaces.
- Produces, for Task 5: `validate_projections(root: Path, contract: dict) -> None`, raising `ContractError("invalid_projection", f"projection.{first_id}.{first_kind}", violations)` when any declared projection is `missing` or `stale`; a `resolve` that refuses on drift; and the guarantee that `resolve` still writes nothing.

**Invariants:**
- `check-projections` opens no file for writing, creates no directory, and runs no subprocess; a run leaves every file's mtime unchanged.
- In sync, `check-projections` prints `{"projections": [{"id": …, "action": "unchanged"}, …]}` in source order and exits 0.
- On drift it emits the `invalid_projection` error object and exits 2, with one violation per drifted projection, pointer `/projections/<id>`, sorted by pointer.
- `resolve` runs the same validation before emitting and refuses identically — a stale projection yields no snapshot and no partial member (D10).
- A missing projection *source* remains `invalid_contract`, never drift.
- The repair id distinguishes the two drift shapes: `projection.<id>.missing` when the target is absent, `projection.<id>.stale` otherwise.

## Steps

- [ ] **Step 1: Extend the shared root helper**

`resolve` now gates on projection freshness, so every temp root built by the existing tests must carry current projections or those tests would refuse. In `home/common/agent-skills/tests/test_resolve_project.py`, replace `ResolverTestCase.make_root` with a version that materializes both targets by default and can be told not to:

```python
    def make_root(self, contract: object | None = None, *,
                  projections: bool = True) -> Path:
        """A temp root holding a valid contract, its instruction source, and —
        unless `projections=False` — both projection targets rendered current."""
        root = Path(tempfile.mkdtemp())
        (root / ".git").mkdir()
        (root / "home" / "common" / "agent-skills" / "standards").mkdir(parents=True)
        (root / ".out-of-scope").mkdir()
        (root / ".worktrees").mkdir()
        (root / ".agents" / "instructions").mkdir(parents=True)
        (root / ".agents" / "instructions" / "bootstrap.md").write_text(
            "# invariants\n", encoding="utf-8")
        if contract is None:
            contract = source_contract()
        if contract is not False:
            (root / ".agents" / "project.json").write_text(
                json.dumps(contract), encoding="utf-8")
        body = "# authored body\n"
        if projections:
            source = (root / ".agents" / "instructions" / "bootstrap.md").read_bytes()
            (root / "AGENTS.md").write_bytes(
                CODEX_HEADER.encode() + b"\n\n" + source)
            body += MANAGED_LINE + "\n"
        (root / "CLAUDE.md").write_text(body, encoding="utf-8")
        return root
```

Move the `CODEX_HEADER` and `MANAGED_LINE` constants introduced in Task 3 above `ResolverTestCase` so the helper can use them. `WriteProjectionsTest` cases that must start from an unwritten state pass `projections=False`; the fresh-root case in Task 3 (`test_a_fresh_root_writes_both_projections`) becomes `self.make_root(projections=False)` and drops its `unlink` line.

- [ ] **Step 2: Write the failing tests**

Append to the same module, above the `if __name__ == "__main__":` guard:

```python
class CheckProjectionsTest(ResolverTestCase):
    def check(self, root: Path) -> tuple[int, object, str]:
        code, out, err = run("check-projections", "--repo-root", str(root))
        try:
            payload: object = json.loads(out)
        except json.JSONDecodeError:
            payload = None
        return code, payload, err

    def test_in_sync_reports_every_projection_unchanged(self):
        code, payload, err = self.check(self.make_root())
        self.assertEqual(code, 0, err)
        self.assertEqual(sorted(payload), ["projections"])
        self.assertEqual({p["action"] for p in payload["projections"]}, {"unchanged"})
        self.assertEqual([p["id"] for p in payload["projections"]],
                         ["codex.entry", "claude.entry"])

    def test_an_appended_byte_in_the_codex_target_is_drift(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("\nhand edit\n")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual(error["code"], "invalid_projection")
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/codex.entry"])
        self.assertEqual(error["repair_id"], "projection.codex.entry.stale")

    def test_a_missing_codex_target_is_drift(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["repair_id"], "projection.codex.entry.missing")

    def test_a_deleted_managed_line_is_drift(self):
        root = self.make_root()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        error = payload["error"]
        self.assertEqual([v["pointer"] for v in error["violations"]],
                         ["/projections/claude.entry"])
        self.assertEqual(error["repair_id"], "projection.claude.entry.stale")

    def test_a_duplicated_managed_line_is_drift(self):
        root = self.make_root()
        with (root / "CLAUDE.md").open("a", encoding="utf-8") as handle:
            handle.write(MANAGED_LINE + "\n")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_projection")

    def test_both_drifted_projections_are_reported_in_pointer_order(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual([v["pointer"] for v in payload["error"]["violations"]],
                         ["/projections/claude.entry", "/projections/codex.entry"])
        self.assertEqual(payload["error"]["repair_id"],
                         "projection.claude.entry.stale")

    def test_a_missing_source_is_a_contract_error_not_drift(self):
        root = self.make_root()
        (root / ".agents" / "instructions" / "bootstrap.md").unlink()
        code, payload, _ = self.check(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_contract")

    def test_check_projections_writes_nothing(self):
        root = self.make_root()
        before = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns)
                        for p in root.rglob("*") if p.is_file())
        self.assertEqual(self.check(root)[0], 0)
        after = sorted((str(p.relative_to(root)), p.stat().st_mtime_ns)
                       for p in root.rglob("*") if p.is_file())
        self.assertEqual(before, after)


class ResolveFreshnessTest(ResolverTestCase):
    def test_resolve_refuses_a_drifted_projection_with_no_snapshot(self):
        root = self.make_root()
        with (root / "AGENTS.md").open("a", encoding="utf-8") as handle:
            handle.write("hand edit\n")
        code, out, _ = run("resolve", "--repo-root", str(root))
        self.assertEqual(code, 2)
        payload = json.loads(out)
        self.assertEqual(sorted(payload), ["error"])
        self.assertEqual(payload["error"]["code"], "invalid_projection")
        for member in ("schema_version", "project", "bindings", "capabilities"):
            self.assertNotIn(f'"{member}"', out)

    def test_resolve_refuses_a_deleted_managed_line(self):
        root = self.make_root()
        (root / "CLAUDE.md").write_text("# authored body\n", encoding="utf-8")
        code, payload, _ = self.resolve(root)
        self.assertEqual(code, 2)
        self.assertEqual(payload["error"]["code"], "invalid_projection")

    def test_resolve_still_writes_nothing_when_it_refuses(self):
        root = self.make_root()
        (root / "AGENTS.md").unlink()
        before = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
        self.assertEqual(self.resolve(root)[0], 2)
        after = sorted(str(p.relative_to(root)) for p in root.rglob("*"))
        self.assertEqual(before, after)


class DriftGateTest(ResolverTestCase):
    """Seam 9: this repository's own committed contract must resolve."""

    def test_the_repository_resolves_and_its_projections_are_current(self):
        code, out, err = run("resolve", "--repo-root", str(REPO_ROOT))
        self.assertEqual(code, 0, err or out)
        snapshot = json.loads(out)
        self.assertEqual(snapshot["schema_version"], 1)
        self.assertEqual(sorted(snapshot["capabilities"]), sorted(CAPABILITY_NAMES))
        self.assertEqual(snapshot["project"]["id"], "fagenorn/nix-config")
        self.assertEqual(snapshot["project"]["root"], str(REPO_ROOT))

    def test_the_repository_check_projections_is_clean(self):
        code, out, err = run("check-projections", "--repo-root", str(REPO_ROOT))
        self.assertEqual(code, 0, err or out)
        self.assertEqual({p["action"] for p in json.loads(out)["projections"]},
                         {"unchanged"})
```

- [ ] **Step 3: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -20`
Expected: FAIL — every `CheckProjectionsTest` case exits 2 with the Task 1 `resolver_failure` placeholder rather than a projection result, and both `ResolveFreshnessTest` drift cases exit 0 with a snapshot because `resolve` does not yet validate freshness.

- [ ] **Step 4: Implement validation and the two call sites**

Add:

```python
def validate_projections(root: Path, contract: dict) -> None:
    """Contract: returns None when every declared projection is in sync;
    otherwise raises ContractError("invalid_projection", …) with one violation
    per drifted projection, sorted by pointer."""
```

It walks `contract["projections"]` in source order, calling `read_projection_source` first — so an absent source is `invalid_contract` and propagates before any drift is considered — then `projection_status`. Every status other than `"in_sync"` contributes `{"pointer": f"/projections/{entry['id']}", "message": …}` and, alongside it, the status word for the repair id. Sort the violations byte-wise ascending by `pointer`; when the list is non-empty raise `ContractError("invalid_projection", f"projection.{first_id}.{first_status}", violations)`, where `first_id` and `first_status` belong to the first violation in that order and `first_status` is `missing` or `stale`.

Replace the `check-projections` placeholder body: resolve the root, load and validate the contract (so a broken contract still refuses first), call `validate_projections`, and on success emit `{"projections": [{"id": entry["id"], "action": "unchanged"} for entry in contract["projections"]]}` in source order, returning 0. It performs no write of any kind.

In the `resolve` body, call `validate_projections(root, contract)` after contract validation and before building the snapshot, so drift refuses with no snapshot and no partial member (D10).

- [ ] **Step 5: Verify**

```sh
python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -5
just agent-workflow-tests 2>&1 | tail -5
python3 home/common/agent-skills/scripts/resolve-project.py check-projections --repo-root .
git status --porcelain
```

Expected: both test runs report `OK`; `check-projections` prints both actions as `unchanged` and exits 0; `git status --porcelain` shows only this task's two files.

Falsifiable gate — a hand edit must now be caught end to end, and the working tree must be restored afterwards:

```sh
set -euo pipefail
cp AGENTS.md /tmp/agents-md-backup
printf '\nhand edit\n' >> AGENTS.md
if python3 home/common/agent-skills/scripts/resolve-project.py check-projections --repo-root . >/dev/null 2>&1; then
  cp /tmp/agents-md-backup AGENTS.md; exit 1
fi
if python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . >/dev/null 2>&1; then
  cp /tmp/agents-md-backup AGENTS.md; exit 1
fi
if just agent-workflow-tests >/dev/null 2>&1; then
  cp /tmp/agents-md-backup AGENTS.md; exit 1
fi
cp /tmp/agents-md-backup AGENTS.md
git diff --quiet -- AGENTS.md
```

Expected: the script reaches its last line and `git diff --quiet -- AGENTS.md` succeeds — proving the drift gate refuses at all three levels (D15) and that the edit was reverted. At Task 3's commit the first `check-projections` would have exited 2 already for the placeholder reason rather than for drift, and `just agent-workflow-tests` would have passed despite the edit.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/scripts/resolve-project.py \
  home/common/agent-skills/tests/test_resolve_project.py
git commit -m "feat(resolver): fail closed on projection drift in check and resolve

Per D10, D11, D15.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>"
```
