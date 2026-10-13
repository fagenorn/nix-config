# Task 1: Sparse contract export and the resolver's projection paths

Spec section 3 ("Materialize the resolver's reads"), per D4, D9 and D10. This task adds the export and the path list and their direct seam. Nothing calls the export yet (Task 2 wires it), so no command's behaviour changes at this commit.

**Files:**
- Modify: `python/agent_tools/resolve_project.py` (one new public function beside `validate_projection_entries`)
- Create: `python/agent_tools/contract_export.py`
- Test: `tests/test_guard_policy.py` (new class `ContractExportTest`, new imports)

**Interfaces:**
- Consumes (existing): `resolve_project.CONTRACT_FILENAME` (`".agents/project.json"`), `resolve_project.is_safe_relative_path(value: object) -> bool`, `resolve_project.load_contract(root: Path) -> dict` (raises `ContractError`), `adopt_inspection.run_git(root, *args, input: bytes | None = None, ...) -> tuple[int, bytes]` (`git -C root *args`), `adopt_inspection.refuse(code, repair_id, pointer, message) -> AdoptError`, `adopt_inspection.export_commit(root, commit, destination)` (test oracle only), `guard_policy.resolver(root, "resolve") -> tuple[int, object]`, `GuardPolicyWorld.project(..., register=False)`, `.git`, `.commit_contract`, `.home`, `.tmp`.
- Produces:
  - `resolve_project.projection_paths(source: object) -> list[str]`: the `source` and `target` of each entry of `source["projections"]` that `is_safe_relative_path` accepts, in declaration order (each entry's `source` before its `target`), first occurrence kept on a duplicate. It never raises. A non-`dict` `source`, a `projections` that is not a `list`, an entry that is not a `dict`, and a member that is absent or not a safe relative path each contribute nothing.
  - `contract_export.export_contract(root: Path, commit: str, destination: Path) -> None`: the sparse export described below. On any git or OS failure it raises `adopt_inspection.refuse("adopt_failure", "adopt.git.export_failed", "", "the remote commit could not be exported")`, the same refusal `export_commit` raises.

**Invariants:**
- `destination` must not exist. It is created with `mkdir()`, and an `OSError` there refuses `export_failed`.
- Only regular blobs are written: a tree entry whose mode is `100644` or `100755` and whose type is `blob`. A path that is absent at `commit`, a tree, a symlink (`120000`) or a gitlink (`160000`) is left absent, and no symlink is ever created in `destination` (D4, D9).
- Phase 1 reads `CONTRACT_FILENAME` at `commit`. When it is not a regular blob, the export is the empty `destination` and the function returns, so the resolver refuses `not_onboarded`. Otherwise its bytes are written as read. The contract is then parsed with `resolve_project.load_contract(destination)`. Any exception from that parse (a `ContractError`, or a `ValueError` or `RecursionError` from a hostile document) ends the export with only the contract written, because the resolver reports that contract's verdict itself (D10).
- Phase 2 reads `projection_paths(contract)` at `commit` and writes each regular blob to `destination / <path as authored>`, creating parent directories (`mkdir(parents=True, exist_ok=True)`).
- Each phase is one `git --literal-pathspecs ls-tree -z --full-tree <commit> -- <paths…>` child and, when it found a regular blob, one `git cat-file --batch` child fed the blob ids on stdin, one per line. An `ls-tree` record is `<mode> <type> <oid>\t<path>`. A requested path matches the record whose path equals `posixpath.normpath(requested)`. A non-zero exit, an unparseable record or a `<oid> missing` batch answer refuses `export_failed`. A `--batch` answer is `<oid> <type> <size>\n<size bytes>\n`, read in request order (D10).
- No other file is written anywhere, and no ref or object is written to the repository.
- `contract_export` imports `resolve_project` and `adopt_inspection`. No `adopt_*` module imports `contract_export` or `resolve_project` (issue 148 D26).
- On the fixture, the resolver's verdict on the sparse export equals its verdict on `export_commit`'s full export for every world except the symlinked projection file, which the sparse export refuses (D9).

- [ ] **Step 1: Write the failing tests**

Add to the imports of `tests/test_guard_policy.py`:

```python
import os
from pathlib import Path
from unittest import mock

from agent_tools import adopt_inspection, contract_export
```

(keep the existing `json`, `shutil`, `unittest`, `guard_policy`, `support` and `GuardPolicyWorld` imports). Append this class after `TargetProfilesTest`:

```python
CONFORMANT = (0, "fixture/one", "main")


class ContractExportTest(unittest.TestCase):
    """`contract_export.export_contract` on a fixture checkout (issue 385 D4, D9, D10).

    The resolver runs in process on the sparse export and, as the oracle, on `export_commit`'s
    full `git archive` export of the same commit. A verdict is `(0, project id, integration
    branch)` or `(status, error code, repair id)`.
    """

    def setUp(self) -> None:
        self.world = GuardPolicyWorld(self)
        self.root = self.world.project("fixture/one", "fagenorn/one", register=False)
        self.base = self.world.git(self.root, "rev-parse", "HEAD").strip()
        patcher = mock.patch.dict(os.environ, {"HOME": str(self.world.home),
                                               "GIT_CONFIG_GLOBAL": os.devnull,
                                               "GIT_CONFIG_SYSTEM": os.devnull})
        patcher.start()
        self.addCleanup(patcher.stop)
        self.exports = 0

    def commit(self, message: str) -> str:
        self.world.git(self.root, "add", "-A")
        self.world.git(self.root, "commit", "--quiet", "-m", message)
        return self.world.git(self.root, "rev-parse", "HEAD").strip()

    def destination(self) -> Path:
        self.exports += 1
        return self.world.tmp / f"export-{self.exports}"

    def sparse(self, commit: str) -> Path:
        destination = self.destination()
        contract_export.export_contract(self.root, commit, destination)
        return destination

    @staticmethod
    def verdict(root: Path) -> tuple:
        status, payload = guard_policy.resolver(root, "resolve")
        if status == 0:
            return (0, payload["project"]["id"], payload["bindings"]["vcs"]["integration_branch"])
        return (status, payload["error"]["code"], payload["error"]["repair_id"])

    def verdicts(self, commit: str) -> tuple[tuple, tuple]:
        full = self.destination()
        adopt_inspection.export_commit(self.root, commit, full)
        return self.verdict(self.sparse(commit)), self.verdict(full)

    @staticmethod
    def files(root: Path) -> set[str]:
        return {path.relative_to(root).as_posix() for path in root.rglob("*")
                if path.is_file() or path.is_symlink()}

    def test_a_conformant_commit_exports_the_contract_and_its_projection_files_only(self):
        sparse = self.sparse(self.base)
        expected = {".agents/project.json", ".agents/instructions/bootstrap.md",
                    "AGENTS.md", "CLAUDE.md"}
        self.assertEqual(self.files(sparse), expected)
        for relative in expected:
            self.assertEqual((sparse / relative).read_bytes(),
                             adopt_inspection.blob_at(self.root, self.base, relative))
        self.assertEqual(self.verdicts(self.base), (CONFORMANT, CONFORMANT))

    def test_each_refusal_matches_the_full_export(self):
        root = self.root

        def stale_target():
            (root / "AGENTS.md").write_text("stale\n", "utf-8")

        def missing_target():
            (root / "CLAUDE.md").unlink()

        def target_is_a_tree():
            (root / "CLAUDE.md").unlink()
            (root / "CLAUDE.md").mkdir()
            (root / "CLAUDE.md/keep.txt").write_text("x\n", "utf-8")

        def missing_source():
            (root / ".agents/instructions/bootstrap.md").unlink()

        def unparseable_contract():
            (root / ".agents/project.json").write_text("not json\n", "utf-8")

        def no_contract():
            (root / ".agents/project.json").unlink()

        def malformed_projections():
            path = root / ".agents/project.json"
            contract = json.loads(path.read_text("utf-8"))
            contract["projections"] = [1, {"source": "../escape", "target": "AGENTS.md"}]
            path.write_text(json.dumps(contract), "utf-8")

        cases = (
            (stale_target, "invalid_projection", "projection.codex.entry.stale"),
            (missing_target, "invalid_projection", "projection.claude.entry.missing"),
            (target_is_a_tree, "invalid_projection", "projection.claude.entry.missing"),
            (missing_source, "invalid_contract", "contract.projections.source_missing"),
            (unparseable_contract, "invalid_contract", "contract.parse"),
            (no_contract, "not_onboarded", "onboarding.contract.missing"),
            (malformed_projections, "invalid_contract", "contract.projections.not_object"),
        )
        for mutate, code, repair_id in cases:
            with self.subTest(mutate.__name__):
                self.world.git(root, "reset", "--quiet", "--hard", self.base)
                self.world.git(root, "clean", "-fdq")
                mutate()
                sparse, full = self.verdicts(self.commit(mutate.__name__))
                self.assertEqual(sparse, (2, code, repair_id))
                self.assertEqual(sparse, full)

    def test_an_executable_projection_file_is_exported(self):
        (self.root / "AGENTS.md").chmod(0o755)
        commit = self.commit("executable target")
        self.assertTrue(self.world.git(self.root, "ls-tree", commit, "AGENTS.md")
                        .startswith("100755 "))
        sparse = self.sparse(commit)
        self.assertTrue((sparse / "AGENTS.md").is_file())
        self.assertEqual(self.verdict(sparse), CONFORMANT)

    def test_a_symlinked_projection_target_is_left_absent_and_refused(self):
        """D9: the one intended divergence; a full export follows the in-tree link."""
        real = self.root / "CLAUDE.real.md"
        real.write_bytes((self.root / "CLAUDE.md").read_bytes())
        (self.root / "CLAUDE.md").unlink()
        os.symlink("CLAUDE.real.md", self.root / "CLAUDE.md")
        commit = self.commit("symlinked target")
        self.assertTrue(self.world.git(self.root, "ls-tree", commit, "CLAUDE.md")
                        .startswith("120000 "))
        sparse = self.sparse(commit)
        self.assertFalse(os.path.lexists(sparse / "CLAUDE.md"))
        self.assertNotIn("CLAUDE.real.md", self.files(sparse))
        self.assertEqual(self.verdict(sparse),
                         (2, "invalid_projection", "projection.claude.entry.missing"))

    def test_nested_projection_files_are_exported_and_resolve(self):
        contract = json.loads((self.root / ".agents/project.json").read_text("utf-8"))
        contract["projections"].append({
            "id": "codex.nested", "agent": "codex", "kind": "generated_file",
            "target": "sub/dir/AGENTS.md", "source": ".agents/instructions/bootstrap.md"})
        self.world.commit_contract(self.root, contract, "nested projection")
        commit = self.world.git(self.root, "rev-parse", "HEAD").strip()
        self.assertIn("sub/dir/AGENTS.md", self.files(self.sparse(commit)))
        self.assertEqual(self.verdicts(commit), (CONFORMANT, CONFORMANT))

    def test_a_commit_the_object_store_lacks_refuses_export_failed(self):
        with self.assertRaises(adopt_inspection.AdoptError) as caught:
            contract_export.export_contract(self.root, "0" * 40, self.destination())
        self.assertEqual(caught.exception.repair_id, "adopt.git.export_failed")
```

- [ ] **Step 2: Run the tests and watch them fail**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py -k ContractExport 2>&1 | tail -4`
Expected: FAIL. The import of `contract_export` fails (`ImportError: cannot import name 'contract_export'`), so the whole module errors.

- [ ] **Step 3: Write the minimal implementation**

`resolve_project.projection_paths(source: object) -> list[str]`, placed directly after `validate_projection_entries`, with a docstring stating the contract in Produces. Write the docstring from the implemented code: it names the paths a resolution reads beyond the contract file (`validate_projections` reads each source and target) and says the function never raises.

`python/agent_tools/contract_export.py`: the module docstring states (write it from the implemented code) that the module is the sparse export the guard-policy proof resolves on (issue 385). It writes the contract file and the regular-blob projection files a resolution reads (`resolve_project.projection_paths`) of one commit into a new directory. Every other path, and any symlink, tree or submodule at a listed path, is left absent, so the resolver refuses it as missing. It reads through git plumbing only, it writes nothing to the repository, it refuses `adopt.git.export_failed`, and it is imported, never run.

Shape (private helper names are free; the public one is fixed):

```python
REGULAR_MODES = ("100644", "100755")


def export_contract(root: Path, commit: str, destination: Path) -> None:
    """Contract: see the module docstring; refuses `adopt.git.export_failed`."""


def _regular_blobs(root: Path, commit: str, paths: list[str]) -> dict[str, str]:
    """Requested path -> blob id, for each requested path that is a regular blob at `commit`."""


def _read_blobs(root: Path, object_ids: list[str]) -> list[bytes]:
    """The bytes of each blob, in order, from one `git cat-file --batch` child."""
```

`_regular_blobs` returns `{}` with no child when `paths` is empty. Otherwise it runs `run_git(root, "--literal-pathspecs", "ls-tree", "-z", "--full-tree", commit, "--", *paths)`, splits the output on `\0`, parses each record into `mode`, `type`, `oid` and the record's path, and keeps the records whose mode is in `REGULAR_MODES` and whose type is `blob`. It then maps each requested path `p` to the kept record whose path is `posixpath.normpath(p)`. Every `OSError` from `mkdir`, `write_bytes` or the parents' `mkdir` maps to the same refusal.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest tests/test_guard_policy.py 2>&1 | tail -4`
Expected: `OK`. Every existing class stays green, plus 6 new `ContractExportTest` tests.

Run: `env PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py 2>&1 | tail -4`
Expected: `OK`.

Run: `git add python/agent_tools/contract_export.py && just build 2>&1 | tail -3`
Expected: exit 0. The package's `pythonImportsCheck` imports the new module.

Run: `if git grep -n -E 'import.*(contract_export|resolve_project)' -- 'python/agent_tools/adopt_*.py'; then exit 1; fi`
Expected: no output, exit 0.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/resolve_project.py python/agent_tools/contract_export.py tests/test_guard_policy.py
launch-commit … -- -m "feat(guard-policy): sparse contract export for the row check (issue 385)"
```
