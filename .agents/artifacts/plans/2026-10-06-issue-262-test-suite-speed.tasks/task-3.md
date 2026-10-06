# Task 3: One closure per edge and per commit set

Per D3 and D9. Hotspot H2: `review_forecast.edge_facts` authenticates an edge with `original_edge`, which opens one `_closure`, and then calls `history_commit` on the parent and again on the child, which opens two more. That is three closures where the first already holds both commits. `_ownership` and `reconstruct_owned` also look up, one closure per commit, commits they have just authenticated. This task adds the one-closure API and converts those sites. Task 4 converts the remaining sites, in other modules, onto the same API.

**Files:**
- Modify: `python/agent_tools/review_git.py` (`original_edge`, new `original_commits`)
- Modify: `python/agent_tools/review_forecast.py` (import, new `history_commits`, `edge_facts`, `_ownership`)
- Modify: `python/agent_tools/review_projection.py` (the `originals` line of `reconstruct_owned`, and its import)

**Interfaces:**
- Consumes: `_closure(repo, tips) -> dict[str, OriginalCommit]`, which is guarded before and after its walk (Task 2 makes the guard cheaper and leaves its contract alone). Also `OriginalCommit(oid, tree, parents, raw)`.
- Produces:
  - `review_git.original_commits(repo: Path, oids: Sequence[str]) -> tuple[OriginalCommit, ...]`. It returns one entry per requested oid, in the order requested (duplicates allowed), from a single `_closure`. An empty `oids` returns `()` and spawns nothing.
  - `review_git.original_edge(repo, parent, commit, ordinal) -> tuple[OriginalCommit, OriginalCommit]`. It returns `(parent commit, child commit)` from the closure it already authenticates. Its checks and codes are unchanged, and callers that ignore the result keep working.
  - `review_forecast.history_commits(repo: Path, values: Sequence[str]) -> tuple[OriginalCommit, ...]`. It is `original_commits`, with `HistoryError` mapped to `ForecastError("invalid original history")` exactly as `history_commit` maps it.

**Invariants:**
- `edge_facts` opens exactly one `_closure` per call, which is one `cat-file --batch` spawn.
- No result is retained across calls: each public call opens its own closure.
- Every `ForecastError` and `HistoryError` message and code stays as it is at `BASE` wherever an existing test can observe it. In `edge_facts` both trees now come from the `original_edge` return, so a failure there surfaces as `invalid original edge`. On an unchanged repository the old follow-up lookups could not fail differently (spec § Risks).
- In `_ownership`, `checkpoint = full_commit(repo, evidence["head"])` followed by `history_commit(repo, checkpoint).tree` becomes `checkpoint = identity(evidence["head"])`, then `checkpoint_commit = history_commit(repo, checkpoint)`, then the existing tree comparison against `checkpoint_commit.tree`. That is the same sequence of checks with one closure fewer.
- In `_ownership`, add `held = dict(zip(sequence, history_commits(repo, sequence)))` with `sequence = (*complete, *tail)`, placed immediately after `tail = commit_range(repo, checkpoint, head)`. Both the tail first-parent loop and the edge loop then read `held[commit].parents`. Everything else in `_ownership`, including every `ancestor`/`commit_range` call, stays as it is (per D9).
- In `reconstruct_owned`, `originals = {commit: history_commit(repo, commit) for commit in ordered}` becomes `originals = dict(zip(ordered, history_commits(repo, ordered)))`. The `full_commit`/`ancestor` loop and the `history_commit(repo, parents[0])` line stay as they are.
- `_prerequisite` is not touched. Its re-run of `_ownership` is deliberate (per D9).

- [ ] **Step 1: Write the failing probe** (scratch only)

```bash
cat > "${TMPDIR:-/tmp}/issue262-t3-probe.py" <<'PY'
import subprocess, sys, tempfile
from pathlib import Path
from agent_tools import review_git
from agent_tools.review_forecast import edge_facts
repo = Path(tempfile.mkdtemp())
git = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.name=p", "-c", "user.email=p@p",
                                 "-c", "commit.gpgsign=false", *a], check=True, capture_output=True, text=True).stdout.strip()
git("init", "-q"); (repo / "a.txt").write_text("one\n"); git("add", "a.txt"); git("commit", "-q", "-m", "one")
(repo / "a.txt").write_text("two\n"); git("commit", "-q", "-am", "two")
parent, child = git("rev-parse", "HEAD~1"), git("rev-parse", "HEAD")
spawns = []
sys.addaudithook(lambda e, a: e == "subprocess.Popen" and spawns.append(list(map(str, a[1]))))
closures = lambda: sum("cat-file" in args for args in spawns)
assert hasattr(review_git, "original_commits"), "original_commits is missing"
assert review_git.original_commits(repo, ()) == () and not spawns, "empty request spawned"
pair = review_git.original_commits(repo, (child, parent))
assert closures() == 1, f"{closures()} closures for one pair"
assert pair == (review_git.original_commit(repo, child), review_git.original_commit(repo, parent))
assert review_git.original_edge(repo, parent, child, 1) == pair[::-1]
spawns.clear(); edge_facts(repo, parent, child, 1)
assert closures() == 1, f"edge_facts opened {closures()} closures"
print("T3-PROBE-OK")
PY
```

- [ ] **Step 2: Run it and watch it fail**

Run: `PYTHONPATH=python python3 "${TMPDIR:-/tmp}/issue262-t3-probe.py"`
Expected at the start commit: `AssertionError: original_commits is missing`.

- [ ] **Step 3: Implement**

Add to `review_git.py`, after `original_commit`:

```python
def original_commits(repo: Path, oids: Sequence[str]) -> tuple[OriginalCommit, ...]:
    """Several authenticated commits, in the order asked, from one closure (#262 D3)."""
    oids = tuple(oids)
    if not oids:
        return ()
    commits = _closure(repo, oids)
    return tuple(commits[oid] for oid in oids)
```

`original_edge` gains the return annotation `-> tuple[OriginalCommit, OriginalCommit]`. After its unchanged ordinal check it ends with `return commits[parent], commits[commit]`.

In `edge_facts`, write `parent_commit, child_commit = original_edge(...)` inside the existing `try`. Set `parent_tree, commit_tree = parent_commit.tree, child_commit.tree` and delete the `history_commit` generator line. Add `history_commits` beside `history_commit`, mirroring its `try`/`except`. Then apply the `_ownership` and `reconstruct_owned` changes exactly as the invariants state, and import `history_commits` in `review_projection.py` and `original_commits` in `review_forecast.py`.

- [ ] **Step 4: Verify**

1. Run the probe. Expect `T3-PROBE-OK`.
2. Run these modules, logging to `${TMPDIR:-/tmp}/issue262-t3-<name>.log` and reporting the tail only. Each must end `OK`:
   - `tests/test_review_history.py`
   - `tests/test_review_evidence.py`
   - `tests/test_review_pack.py`
   - `tests/test_review_task7.py`
   - `tests/test_review_feasibility.py` (`timeout 2400`), which exercises `_ownership` and `reconstruct_owned` through `review-feasibility project`
3. Run `PYTHONPATH=python python3 -m unittest tests.test_review_issue121.AncestryTest` with `timeout 1800`. Expect `OK`.
4. Run the root's coverage gate. Expect `COVERAGE-GATE-OK 2077 test ids`.

- [ ] **Step 5: Commit**

```bash
git add python/agent_tools/review_git.py python/agent_tools/review_forecast.py python/agent_tools/review_projection.py
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id run-20261006-261-262-263-264-265 --worker-id <your worker id> -- \
  -m "perf(review): read each edge and commit set from one closure (#262)" -m "<trailer lines>"
```
