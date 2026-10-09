# Task 5: Condense CI and Homebrew, measure, record AC1

**Files:**
- Modify: `CLAUDE.md` (base lines L24 and L57 only)
- Create: `.agents/artifacts/plans/2026-10-09-issue-330-slim-claude-md.acceptance.md`

**Interfaces:**
- Consumes: `CLAUDE.md` after Tasks 1–4, which moved the helper package, guard, skill and local-model detail out; base `8e2bfb72` (`L<n>` = line `n` of `git show 8e2bfb72:CLAUDE.md`).
- Produces: the final `CLAUDE.md` (at most 2,136 words, the bootstrap import as its last line, exactly once) and the acceptance record with row AC1's evidence filled.

**Invariants:**
- Only the L24 and L57 clauses listed below are removed; every row here is `present`: its fact already lives in the cited file, so it is deleted from `CLAUDE.md` and not copied (D2). No `.nix`, `.yaml` or `.json` file is edited.
- The section skeleton stays: `# CLAUDE.md`, `## Commands`, `## Architecture`, `## Key conventions & gotchas`, and `@.agents/instructions/bootstrap.md` as the last line, exactly once (D3, spec "What stays").
- A base line not listed as kept below never survives verbatim; every kept base line survives verbatim.
- No committed size test is added (D6).

## Fact-to-home rows (B1, B4)

| Row | Base | Clause removed | Home (present) | Anchor (in the home, absent from `CLAUDE.md`) |
|---|---|---|---|---|
| F95 | L24 | ", plus daily (where only `Flake Checker` runs)" | `.github/workflows/ci.yaml`: the `schedule:` trigger and the `if: github.event_name != 'schedule'` lines on the other jobs | `if: github.event_name != 'schedule'` (in `ci.yaml`); `plus daily` (absent from `CLAUDE.md`) |
| F96 | L24 | ", with `strict` on" | `.github/branch-protection.json` | `"strict": true` (in the JSON); `` with `strict` on `` (absent) |
| F97 | L24 | ", with `enforce_admins` on" | `.github/branch-protection.json` | `"enforce_admins": true` (in the JSON); `` with `enforce_admins` on `` (absent) |
| F98 | L24 | "CI also runs `just agent-workflow-tests` as a source-only advisory suite, which is not a required context." | `.github/workflows/ci.yaml`: job `Agent Workflow Tests (advisory)` and its "explicitly source-only" comment; `.github/branch-protection.json` lists only the two required contexts | `Agent Workflow Tests (advisory)` (in `ci.yaml`); `source-only advisory suite` (absent) |
| F99 | L57 | "— that is Homebrew 7's spelling of the old `cleanup = \"zap\"`, which nix-darwin 25.11 still emits as the removed `brew bundle --cleanup` flag; drop the shim once nix-darwin is bumped past its 2026-06-01 fix" | `hosts/common/darwin-common.nix` comment above `cleanup = "none"` (lines 77–82 at base) | `fixed this on 2026-06-01` (in the `.nix`); `2026-06-01 fix` (absent) |

Dictated replacements (D7):
- L24's CI sentence becomes: "CI (`.github/workflows/ci.yaml`) runs on pull requests and on push to `main`: `Flake Checker` annotates `flake.lock` health without failing, and **`Nix Eval` evaluates `nixosConfigurations.anis-desktop` on Linux and is one of the two contexts `.github/branch-protection.json` makes required on `main`, the other being `Instruction Budget` (`.github/workflows/instruction-budget.yaml`)** — once `just protect-main` has been applied, `gh pr merge` (including `--admin`) is refused until both are green on a branch that is up to date with `main`, and direct pushes to `main` are refused outright (a commit that has never reached the remote can carry no status)." L24's other sentences stay verbatim except F98, which is deleted.
- L57's parenthesis becomes: "(`onActivation.extraFlags = [ \"--zap\" \"--force-cleanup\" ]` with `cleanup = \"none\"` removes anything unmanaged on every switch; the comment above it in that file explains the shim and when to drop it)". The rest of L57 stays verbatim.

- [ ] **Step 1: Write the failing gate**

Save as `$SCRATCH/task5-gate.py` (`$SCRATCH` = the directory `launch-scope scratch …` prints; never commit it):

```python
import pathlib, subprocess, sys

def norm(text):
    return " ".join(text.split())

def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")

head = read("CLAUDE.md")
base = subprocess.run(["git", "show", "8e2bfb72:CLAUDE.md"], check=True,
                      capture_output=True, text=True).stdout.split("\n")
bad = []
present = [(".github/workflows/ci.yaml", "if: github.event_name != 'schedule'"),
           (".github/branch-protection.json", '"strict": true'),
           (".github/branch-protection.json", '"enforce_admins": true'),
           (".github/workflows/ci.yaml", "Agent Workflow Tests (advisory)"),
           ("hosts/common/darwin-common.nix", "fixed this on 2026-06-01")]
bad += [f"missing from {p}: {a}" for p, a in present if norm(a) not in norm(read(p))]
for gone in ("plus daily", "with `strict` on", "with `enforce_admins` on",
             "source-only advisory suite", "2026-06-01 fix"):
    if gone in norm(head):
        bad.append(f"still in CLAUDE.md: {gone}")
kept = {1, 3, 5, 7, 9, *range(11, 23), 26, 28, 30, *range(32, 39), 40, 42, 43, 45,
        51, 53, 55, 58, 59, 60, 62, 63, 74, 86, 87}
lines = head.split("\n")
for n, text in enumerate(base, 1):
    if not text.strip():
        continue
    if n in kept and text not in lines:
        bad.append(f"kept base line L{n} changed or lost")
    if n not in kept and text in lines:
        bad.append(f"base line L{n} survives unlisted")
if [l for l in lines if l.strip()][-1] != "@.agents/instructions/bootstrap.md":
    bad.append("bootstrap import is not the last line")
if lines.count("@.agents/instructions/bootstrap.md") != 1:
    bad.append("bootstrap import not exactly once")
words = len(head.split())
if words > 2136:
    bad.append(f"CLAUDE.md has {words} words > 2136")
print("\n".join(bad) or f"task5 gate: pass ({words} words)")
sys.exit(1 if bad else 0)
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 -I "$SCRATCH/task5-gate.py"`
Expected: exit 1, with `still in CLAUDE.md` lines for the five removed clauses and `base line L24 survives unlisted` and `base line L57 survives unlisted`. Any other `survives unlisted` or `kept … lost` line means an earlier task left `CLAUDE.md` off-plan: stop and report it instead of fixing it here.

- [ ] **Step 3: Condense**

1. Apply the two dictated replacements and delete F98 in `CLAUDE.md`.
2. Re-run the gate. If the only failure is the word count (not expected: the estimate is about 1,500 words), stop and report the count; do not cut further on your own.
3. After the first commit of Step 5, create `.agents/artifacts/plans/2026-10-09-issue-330-slim-claude-md.acceptance.md` with the header `# Acceptance record — issue #330`, the column row `| AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict |`, and one row per criterion, `Criterion` copied verbatim from issue #330 without its checkbox (`gh issue view 330 --repo fagenorn/nix-config --json body -q .body`):
   - AC1, `evidence`: Check `wc -w < CLAUDE.md` vs `git show 8e2bfb72:CLAUDE.md | wc -w`, threshold head ≤ 2136; Observed `<head words> / 5342 = <ratio to 3 decimals>`; Commit = the short hash of the first commit in Step 5; Conditions `worktree head after Task 5`; Verdict `—`.
   - AC2, `code`: Check `reviewer audit of the fact-to-home rows F1–F99`; Observed `in final verification`; Commit, Conditions, Verdict `—`.
   - AC3, `code`: Check `just agent-workflow-tests` (`CommittedProjectionTest`, `check-projections`); Observed `in final verification`; Commit, Conditions, Verdict `—`.

- [ ] **Step 4: Verify**

Run: `python3 -I "$SCRATCH/task5-gate.py"` — Expected: `task5 gate: pass (<n> words)`, exit 0, with n ≤ 2136.
Run: `resolve-project check-projections --repo-root .` — Expected: exit 0, every projection reported in sync.
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_resolve_project.py -k CommittedProjectionTest` (timeout 600 s) — Expected: OK.

- [ ] **Step 5: Commit**

Two commits: first `CLAUDE.md`, then the acceptance record carrying that first commit's hash in AC1's `Commit`.

```bash
git add CLAUDE.md
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(claude-md): condense CI and Homebrew (#330)"
git add .agents/artifacts/plans/2026-10-09-issue-330-slim-claude-md.acceptance.md
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(acceptance): record the CLAUDE.md size (#330)"
```

The identity values and the commit-message trailers come from your dispatch brief; commits stay signed.
