# Task 1: Move the helper package and the #117 decision to `python/README.md`

**Files:**
- Create: `python/README.md`
- Modify: `CLAUDE.md` (base lines L47 and L49 only)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (delete class `LaunchScopeSweepContractsTest`)

**Interfaces:**
- Consumes: `CLAUDE.md` as at base `8e2bfb72` for L47 and L49 (`L<n>` = line `n` of `git show 8e2bfb72:CLAUDE.md`). Other tasks edit other lines of `CLAUDE.md`; touch nothing outside the **Agent helper package** paragraph and the paragraph after it.
- Produces: `python/README.md` with the sections named below; the slimmed **Agent helper package** paragraph in `CLAUDE.md`.

**Invariants:**
- Every moved sentence is copied verbatim (D2). Allowed edits only: name the subject where the sentence leaned on `CLAUDE.md` context, split into the sections below, and rebase markdown links to `python/` (D7): `.agents/artifacts/specs/…` becomes `../.agents/artifacts/specs/…`. Code-span paths (`` `python/` ``, `` `home/common/…` ``) stay as written.
- A sentence kept in `CLAUDE.md` is not copied into the README, except L47's first sentence may open the README to name its subject (D7).
- The `@.agents/instructions/bootstrap.md` line is untouched.
- A moved sentence that contradicts the code it now sits beside is not corrected; list it in your report (file, line, sentence) for the owner to file.

## Fact-to-home rows (B2, B3)

Destination for every row: `python/README.md`, under the heading named. All rows are `moved`. Opening words quote the base sentence.

| Row | Base | Sentence opening | Heading | Anchor (must be in the README, absent from `CLAUDE.md`) |
|---|---|---|---|---|
| F1 | L47 | "`lib/agent-tools.nix` builds it into one Python environment" | Package and launchers | `import-checks every module` |
| F2 | L47 | "Each row becomes a `~/.agents/bin/<command>` launcher" | Package and launchers | `` `just agent-installed-skill-tests` proves it `` |
| F3 | L47 | "`review-package` and `review-feasibility` use the package command table" | Review packaging and feasibility | `python -m agent_tools.review_feasibility` |
| F4 | L47 | "Actual production and generic projection share packing" | Review packaging and feasibility | `projection binds its policy identity` |
| F5 | L47 | "`review-feasibility project` reads committed plans" | Review packaging and feasibility | `closed canonical v3 results` |
| F6 | L47 | "Actual production also calls external `sdd-workspace` by PATH." | Review packaging and feasibility | `` calls external `sdd-workspace` by PATH `` |
| F7 | L47 | "`verified-tree` records a passing run of the declared verification" | `verified-tree` | `` `verified-tree.json` in the worktree's own git directory `` |
| F8 | L47 | "`launch-scope` (#276) contains a lifecycle agent's long commands" | `launch-scope` | `AGENT_LAUNCH_SCOPE=<repo-scope>/<run-id>/<action-id>/<nonce>` and `survives a sweep` |
| F9 | L47 | "`launch-scope scratch` (#277) prints the launch's one scratch root" | `launch-scope` | `` `unattributed_worktrees` `` |
| F10 | L47 | "`lane-triage evaluate --repo-root <root> --input -` (#279) reads" | `lane-triage` | `` `light_lane_unsupported` `` |
| F11 | L47 | "`agent_tools.transaction_core` is the transaction core's library surface" | Transaction core | `` `transaction-state/v6` validator `` |
| F12 | L47 | "The retained review evidence that `derive-review-feasibility-fixtures` derives" | Retained review evidence | `` `projection_unavailable` `` |
| F13 | L49 | "The [#117 attempt-lifecycle decision](…) selects attempts" | Transaction core | `selects attempts as the transaction core's first consumer` |
| F14 | L49 | "It governs the planned single-store migration" | Transaction core | `immutable subject/identity` |
| F15 | L49 | "It is an architecture decision: runtime core delivery" | Transaction core | `runtime core delivery belongs to the open #123/#125` |

Kept in `CLAUDE.md`, verbatim and in base order: L47's sentences "**Agent helper package.** Agent-workflow Python is moving into one standard-library package…", "The `just` recipes that run package code set `PYTHONPATH` to `python/`…", and "The remaining Python helpers are still flat scripts under `home/common/agent-skills/scripts/`…".

In F13–F15, "the lifecycle paths and behavior below" referred to `CLAUDE.md`'s later bullets; name the subject: "the lifecycle paths and behavior that `home/common/agent-skills/README.md` describes". In F14 and F15 "It" may become "The decision" (naming the subject).

- [ ] **Step 1: Write the failing gate**

Save as `$SCRATCH/task1-gate.py`, where `$SCRATCH` is the directory `launch-scope scratch …` prints (never commit it):

```python
import pathlib, sys

def norm(path):
    return " ".join(pathlib.Path(path).read_text(encoding="utf-8").split())

claude, home = norm("CLAUDE.md"), norm("python/README.md") if pathlib.Path("python/README.md").exists() else ""
anchors = [
    "import-checks every module", "`just agent-installed-skill-tests` proves it",
    "python -m agent_tools.review_feasibility", "projection binds its policy identity",
    "closed canonical v3 results", "calls external `sdd-workspace` by PATH",
    "`verified-tree.json` in the worktree's own git directory",
    "AGENT_LAUNCH_SCOPE=<repo-scope>/<run-id>/<action-id>/<nonce>", "survives a sweep",
    "`unattributed_worktrees`", "`light_lane_unsupported`", "`transaction-state/v6` validator",
    "`projection_unavailable`", "selects attempts as the transaction core's first consumer",
    "immutable subject/identity", "runtime core delivery belongs to the open #123/#125",
]
kept = [
    "**Agent helper package.** Agent-workflow Python is moving into one standard-library package",
    "The `just` recipes that run package code set `PYTHONPATH` to `python/`",
    "The remaining Python helpers are still flat scripts under `home/common/agent-skills/scripts/`",
    "](python/README.md)",
]
bad = [f"missing from README: {a}" for a in anchors if a not in home]
bad += [f"still in CLAUDE.md: {a}" for a in anchors if a in claude]
bad += [f"kept sentence lost: {k}" for k in kept if k not in claude]
if "](../.agents/artifacts/specs/2026-09-20-issue-117-attempt-lifecycle-first-consumer-design.md)" not in home:
    bad.append("#117 link not rebased")
if "test_claude_md_describes_launch_scope" in pathlib.Path(
        "home/common/agent-skills/tests/test_workflow_skill_contracts.py").read_text(encoding="utf-8"):
    bad.append("launch-scope pin still present")
print("\n".join(bad) or "task1 gate: pass")
sys.exit(1 if bad else 0)
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 -I "$SCRATCH/task1-gate.py"`
Expected: exit 1, every anchor reported `missing from README`, plus `launch-scope pin still present`.

- [ ] **Step 3: Move the text**

1. Create `python/README.md`: a `# agent_tools — the agent helper package` title, optionally L47's first sentence, then sections `## Package and launchers` (F1, F2), `## Review packaging and feasibility` (F3–F6), `## verified-tree` (F7), `## launch-scope` (F8, F9), `## lane-triage` (F10), `## Transaction core` (F11, then F13–F15 with the link rebased), `## Retained review evidence` (F12). Copy each sentence from `git show 8e2bfb72:CLAUDE.md` line 47 or 49, not from memory. Wrap lines as you like.
2. In `CLAUDE.md`, replace L47 with the three kept sentences in base order followed by this dictated pointer (D1, D7):
   "Each command's contract (review packaging, `verified-tree`, `launch-scope`, `lane-triage`), the transaction core, the retained review evidence and the #117 attempt-lifecycle decision are in [`python/README.md`](python/README.md); new detail of that kind goes there, not here."
   Delete the L49 paragraph and its trailing blank line.
3. In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, delete the whole class `LaunchScopeSweepContractsTest` (its `assert_ordered` helper and its only test `test_claude_md_describes_launch_scope`) and leave two blank lines between the neighbouring top-level statements (D5). Delete nothing else.

- [ ] **Step 4: Verify**

Run: `python3 -I "$SCRATCH/task1-gate.py"` — Expected: `task1 gate: pass`, exit 0.
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py` (timeout 600 s) — Expected: OK, no failures or errors.
Run: `grep -c '^@.agents/instructions/bootstrap.md$' CLAUDE.md` — Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add python/README.md CLAUDE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(claude-md): move the helper package detail to python/README.md (#330)"
```

The identity values and the commit-message trailers come from your dispatch brief; commits stay signed.
