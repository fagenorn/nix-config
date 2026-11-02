# Task 2: Fix the fix-bound findings test-first

Spec § Solution step 5, § Fixes, § Test seams; per D5, D6 and D9. The findings are unknown when this plan is written: your input is the record's Findings rows whose Evidence is exactly `fix pending` (at most three, Critical first). With none, you change nothing, make no commit and report DONE with `no fix-bound finding`; Step 7 still runs.

**Files:**
- Modify: for each `fix pending` row, the file its Location names (one of the 25), and only where the fix needs it another of the 25
- Test: that file's seam module (map below)
- Modify: `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md` (`R`): those rows' Disposition and Evidence cells only

**Interfaces:**
- Consumes: Task 1's record. Findings rows are `| ID | Severity | Location | Defect | Disposition | Evidence |`; Location is `` `<path>:<line>` ``; a fix-bound row reads `fixed` and `fix pending`.
- Produces, for Task 3, each such row either still `fixed` with Evidence `` `<fix commit, 8 hex>`; `<test file>::<Class>.<test name>`; failing first: `<the run's first AssertionError line>` `` (followed by `; mutant: <file>:<line> <the edit>` on the weak-test route), or `filed` with Evidence `issue pending (bar <k>)`.

**Seam map** (the existing module whose tests already cover the fixed code; add the test beside them with that module's fixtures):
- `review_pack.py`, `review_budget.py` → `tests/test_review_pack.py`
- `review_package.py`, `review_publish.py`, `review_actual.py` → `home/common/agent-skills/tests/test_review_package.py`
- `review_git.py` → `tests/test_review_history.py`; `review_projection.py` → `tests/test_review_projection_cases.py`
- `review_forecast.py`, `review_feasibility.py` → `tests/test_review_feasibility.py`
- `artifact_budget.py` → `home/common/agent-skills/tests/test_artifact_budget.py`
- `lib/agent-tools.nix`, `home/common/agent-skills/default.nix` → `tests/test_agent_tools_launchers.py`, run through `just agent-installed-skill-tests`
- `justfile`, `CLAUDE.md`, sdd skill text → only text a tool or subagent consumes, in the existing contract test that already pins that kind of text; never a new English-phrase pin (agent-helpers rule 6)
- a test file among the 25 (a test that cannot fail for its contract) → that test itself, by the weak-test route (Step 3)

**Invariants:**
- Rows are taken in table order; at most three end `fixed`; a row that misses the bar becomes `filed` and no other row is promoted into its place (per D9).
- Each fix is one commit holding its regression test and its fix only, with `git diff --numstat <fix>^ <fix>` summing to at most 150 added plus deleted lines (bar 4, per D9).
- Apart from its test, a fix touches only the 25; it changes no documented contract (argv, exit codes, report or manifest schema, persisted package format) and leaves `python/README.md` unchanged (bars 1, 2).
- Failing first means the red run exits 1 with one `FAIL:` line for the new test, `FAILED (failures=1)` and no `ERROR:` line; a run that fails on an import, a missing name or no matching test is not evidence (per D6).
- Tests assert observable behaviour the documented contract requires (exit code, printed JSON, files written or refused), never a call count, against real temporary Git repositories, with no mocked Git.
- No Minor row and no other row of `R` changes.

- [ ] **Step 1: List the fix-bound rows**

```bash
R=.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md
grep -n '| fixed | fix pending |$' "$R" || echo "no fix-bound finding"
```

Expected: zero to three rows. Zero: go to Step 7.

For each row, in order, run Steps 2–5.

- [ ] **Step 2: Re-check the bar before any product edit (per D5, D9)**

Read the row and the cited code at `HEAD`. Items: (1) apart from its regression test the fix stays inside the 25; (2) it keeps the documented contract and needs no `python/README.md` edit; (3) it needs no instruction-budget raise; (4) at most 150 changed lines, test included; (5) fewer than three rows already fixed in this task; (6) a regression test fits the seam map. The first item that fails: set the row's Disposition to `filed` and its Evidence to `issue pending (bar <k>)`, and take the next row.

- [ ] **Step 3: Write the failing test**

Add `test_<the behaviour the contract requires>` beside the tests of the same command or function in the seam module, reusing that module's fixtures (its temporary-repository helpers, its `subprocess.run([sys.executable, "-m", "agent_tools.<module>", …])` calls with `PYTHONPATH` at the source `python/`, or its existing imports). Build the input that triggers the row's failure scenario and assert the result the documented contract requires. The expected value comes from the contract (`python/README.md` § Review packaging and feasibility, the module docstring, the skill text), never from running the code.

Weak-test route (the Location is a test file): strengthen that test so it pins its contract. Its failing-first run is against a mutant: `git worktree add --detach "$S/mutant-<ID>" HEAD`, make the smallest edit to the product code there that breaks the contract the test documents, then run the original test there (it must pass: it could not fail) and your strengthened test, written over the copy with the editor (it must fail as in Step 4).

- [ ] **Step 4: Watch it fail (per D6)**

```bash
launch-scope exec … -- bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest -v "$1" -k "$2"' _ <test file> <test name> > "$S/red-<ID>.log" 2>&1; echo "exit=$?"
grep -E '^(FAIL|ERROR):|^(FAILED|OK)' "$S/red-<ID>.log"
grep -m1 '^AssertionError' "$S/red-<ID>.log"
```

Timeout 900 s; for a `tests/test_agent_tools_launchers.py` test run `launch-scope exec … -- bash -c 'just agent-installed-skill-tests 2>&1' > "$S/red-<ID>.log"` instead (timeout 3600 s), where only your test may fail. Expected: `exit=1`, one `FAIL: <test name>` line, `FAILED (failures=1)`, no `ERROR:` line. Keep the `AssertionError` line: it is the record's failing-first line. `ERROR:` or `exit=5` means the test does not pin the defect yet: fix the test, not the code.

- [ ] **Step 5: Fix, watch it pass, commit**

Make the smallest change that meets the documented contract. Then, each expected to pass:

- the Step 4 command → `exit=0`, `OK`;
- the whole seam module: `launch-scope exec … -- bash -c 'set -o pipefail; PYTHONPATH="$PWD/python" python3 -m unittest "$1" 2>&1 | tail -3' _ <test file>` (timeout 1800 s) → exit 0, `OK`;
- after a `.nix` edit: `launch-scope exec … -- bash -c 'set -o pipefail; just build 2>&1 | tail -3'` (timeout 1800 s) → exit 0 (`pipefail` makes the exit status the build's, not `tail`'s);
- after an edit under `home/common/agent-skills/skills/`: `launch-scope exec … -- bash -c 'set -o pipefail; just agent-instruction-budget 2>&1 | tail -3'` (timeout 600 s) → exit 0 and last line `check: pass`;
- `git diff --numstat` over the edited files sums to at most 150.

A bar that fails now (2, 3 or 4): undo your uncommitted edits to those files with the editor (no destructive Git command), set the row `filed` / `issue pending (bar <k>)`, and take the next row. Otherwise:

```bash
git add <test file> <fixed files>
launch-commit … -- -m "fix(issue-259): <ID> <what now holds>" -m "<session trailers>"
git rev-parse --short=8 HEAD
```

- [ ] **Step 6: Record the evidence**

In `R`, set each fixed row's Evidence to `` `<fix 8 hex>`; `<test file>::<Class>.<test name>`; failing first: `<AssertionError line>` `` (plus `; mutant: …` on the weak-test route), each `|` written `\|`. If `R` changed:

```bash
git add .agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md
launch-commit … -- -m "docs(issue-259): record the fix evidence" -m "<session trailers>"
```

- [ ] **Step 7: Verify**

With `REVIEW_SHA` read as in Global Constraints (timeout 300 s):

```bash
if grep -q 'fix pending' "$R"; then echo "fix pending remains"; exit 1; fi
python3 -I - "$R" "$REVIEW_SHA" <<'EOF'
import re, subprocess, sys
record, sha = sys.argv[1], sys.argv[2]
def git(*a):
    return subprocess.run(["git", *a], check=True, capture_output=True, text=True).stdout
M = "93e6059a6fece769a621657c5889278b9cb9e0d7"
paths = {p for p in git("diff", "--name-only", M + "^1", M).splitlines() if not p.startswith(".agents/artifacts/")}
lines = open(record, encoding="utf-8").read().splitlines()
start = lines.index("## Findings") + 1
end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
rows = [[c.strip() for c in re.split(r"(?<!\\)\|", l.strip())[1:-1]] for l in lines[start:end] if l.startswith("| B")]
FIX = re.compile(r"`([0-9a-f]{8})`; `([^`]+)::[A-Za-z_][A-Za-z0-9_]*\.test_[A-Za-z0-9_]+`; failing first: `AssertionError[^`]*`(; mutant: .+)?")
tests, fixed = set(), 0
for ids, sev, loc, defect, disp, ev in rows:
    if disp != "fixed":
        continue
    fixed += 1
    m = FIX.fullmatch(ev)
    assert m, ids
    commit, tfile = m.group(1), m.group(2)
    changed = set(git("diff", "--name-only", commit + "^", commit).split())
    others = changed - {tfile}
    assert tfile in changed and others <= paths and (others or loc.strip("`").rpartition(":")[0] == tfile), ids
    numstat = [l.split("\t") for l in git("diff", "--numstat", commit + "^", commit).splitlines()]
    assert sum(int(a) + int(d) for a, d, _ in numstat) <= 150, ids
    tests.add(tfile)
assert fixed <= 3, fixed
outside = [p for p in git("diff", "--name-only", sha, "HEAD", "--", ".", ":(exclude).agents/artifacts").split()
           if p not in paths and p not in tests]
assert not outside, outside
print(f"fix evidence ok: {fixed} fixed")
EOF
```

Expected: exit 0, `fix evidence ok: <n> fixed`. Then run each fixed row's Step 4 command once more at `HEAD`: `exit=0`, `OK`. Before this task the first line fails whenever a `fix pending` row exists.
