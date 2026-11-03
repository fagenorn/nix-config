# Task 2: Three-spawn review history guard

Per D2. Hotspot H2: `_guard` in `python/agent_tools/review_git.py` runs before and after every `_closure` walk. In the default environment each `_guard` launches five `git` processes: `rev-parse` for the locations, `rev-parse --is-shallow-repository`, one `for-each-ref`, `config --null --list` and `rev-parse --show-object-format`. With `cat-file --batch` and `rev-list` added, one `original_commit` costs 12 spawns at `BASE`. After this task a guard costs three spawns and one `original_commit` costs 8.

**Files:**
- Modify: `python/agent_tools/review_git.py` (only `_guard`)

**Interfaces:**
- Consumes: `_git(repo, *args) -> bytes` (unchanged; it maps a failed or unlaunchable `git` to `HistoryError("original_history_unavailable")`).
- Produces: `_guard(repo: Path) -> str`, with the same signature and return value as at `BASE` (`"sha1"` or `"sha256"`).

**Invariants:**
- Exactly three `git` spawns per call when the combined `rev-parse` succeeds. They run in this order: one `rev-parse`, one `for-each-ref`, one `config`.
- When the combined `rev-parse` raises `HistoryError` (for example malformed `GIT_SHALLOW_FILE` contents make `--is-shallow-repository` exit 128), `_guard` returns the result of `_guard_stepwise(repo)` — `BASE`'s `_guard` body kept byte-for-byte under that name — so every failure-path code and its precedence equal `BASE`'s (per PR262-B1 in the plan's standards review provenance).
- Checks run in `BASE`'s order, with `BASE`'s codes:
  1. a routing variable → `original_repository_routing_unavailable`, before any spawn
  2. a graft or shallow file, or a `GIT_GRAFT_FILE`/`GIT_SHALLOW_FILE`, that is a symlink or non-empty → `original_history_virtualized`
  3. an `OSError` from those file checks → `original_history_unavailable`
  4. a shallow flag other than `false` → `original_history_virtualized`
  5. any ref under `refs/replace/` or `GIT_REPLACE_REF_BASE` → `original_history_virtualized`
  6. promisor or partial-clone configuration → `original_history_unavailable`
  7. an object format other than `sha1`/`sha256` → `original_object_format_unavailable`
- Combined `rev-parse` output that is not exactly four lines also falls back to `_guard_stepwise(repo)`.
- `_closure` still calls `_guard` before and after its walk. The comment `# No retained cache: every API boundary observes current metadata and objects.` stays verbatim.

- [ ] **Step 1: Write the failing probe** (scratch only)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t2-probe.py" <<'PY'
import subprocess, sys, tempfile
from pathlib import Path
from agent_tools.review_git import original_commit
repo = Path(tempfile.mkdtemp())
git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=p", "-c", "user.email=p@p",
                                 "-c", "commit.gpgsign=false", *a], check=True, capture_output=True, text=True).stdout.strip()
git("init", "-q"); git("commit", "-q", "--allow-empty", "-m", "one")
head = git("rev-parse", "HEAD")
spawns = []
sys.addaudithook(lambda e, a: e == "subprocess.Popen" and spawns.append(a[1]))
original_commit(repo, head)
assert len(spawns) == 8, f"{len(spawns)} spawns: {spawns}"
print("T2-PROBE-OK")
PY
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t2-probe.py"`
Expected at `BASE`: `AssertionError: 12 spawns: ...`

- [ ] **Step 3: Implement**

Replace `_guard` with this shape. It folds the four `rev-parse` queries into one and the replace namespaces into one `for-each-ref`, and leaves the checks in the same order:

```python
def _guard(repo: Path) -> str:
    # Repository-routing overrides would also redirect disposable reconstruction
    # commands. Refuse them before any source or scratch operation can write.
    if any(key in os.environ for key in ("GIT_DIR", "GIT_COMMON_DIR", "GIT_WORK_TREE",
            "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES")):
        raise HistoryError("original_repository_routing_unavailable")
    # One rev-parse answers locations, shallowness and object format (#262 D2).
    # Any failure re-runs BASE's stepwise guard so failure codes keep their precedence.
    try:
        facts = _git(repo, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
                     "--is-shallow-repository", "--show-object-format").decode().splitlines()
    except HistoryError:
        return _guard_stepwise(repo)
    if len(facts) != 4:
        return _guard_stepwise(repo)
    *locations, shallow, algorithm = facts
    paths = [Path(root) / name for root in locations for name in ("info/grafts", "shallow")]
    for key in ("GIT_GRAFT_FILE", "GIT_SHALLOW_FILE"):
        if key in os.environ:
            path = Path(os.environ[key])
            paths.append(path if path.is_absolute() else repo / path)
    try:
        for path in paths:
            if path.is_symlink() or (path.exists() and path.stat().st_size):
                raise HistoryError("original_history_virtualized")
    except OSError as exc:
        raise HistoryError("original_history_unavailable") from exc
    if shallow.strip() != "false":
        raise HistoryError("original_history_virtualized")
    namespaces = sorted({"refs/replace/", os.environ.get("GIT_REPLACE_REF_BASE", "refs/replace/")})
    if _git(repo, "for-each-ref", "--format=%(refname)", *namespaces):
        raise HistoryError("original_history_virtualized")
    # (the promisor block stays exactly as at BASE)
    algorithm = algorithm.strip()
    if algorithm not in {"sha1", "sha256"}:
        raise HistoryError("original_object_format_unavailable")
    return algorithm
```

Keep the promisor `config --null --list` block and its comment byte-for-byte where the placeholder comment sits. Do not commit the placeholder line itself. Rename `BASE`'s `_guard` to `_guard_stepwise`, unchanged apart from its name, directly above the new `_guard`.

- [ ] **Step 4: Verify**

1. Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t2-probe.py"`. Expect `T2-PROBE-OK`.
2. Run: `grep -c "No retained cache: every API boundary observes current metadata and objects." python/agent_tools/review_git.py`. Expect `1`.
3. Run `tests/test_review_history.py` and `tests/test_review_evidence.py`, each to `OK`.
4. Run the adversarial entry-point test, with `timeout 900`: `PYTHONPATH=python python3 -m unittest tests.test_review_issue121.AncestryTest.test_virtualized_history_is_invalid_at_both_entry_points`. Expect `OK`.
5. Differential precedence probe (scratch only, not committed): in a fresh scratch repo, for each environment case — a malformed non-empty `GIT_SHALLOW_FILE` (e.g. the text `garbage`), an empty `GIT_SHALLOW_FILE`, a symlinked `GIT_GRAFT_FILE`, a `refs/replace/` ref, `extensions.partialClone` set, and the clean default — call `_guard` and `_guard_stepwise` and assert both raise the same `HistoryError` code or return the same value. Expect every case equal; the malformed-shallow case must report `original_history_virtualized`.
6. Run the root's coverage gate. Expect `COVERAGE-GATE-OK 2077 test ids`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_git.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "perf(review): answer the history guard from three git calls (#262)" -m "<trailer lines>"
```
