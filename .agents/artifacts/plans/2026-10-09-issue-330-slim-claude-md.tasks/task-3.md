# Task 3: Move skill sourcing and lifecycle-helper contracts to `home/common/agent-skills/README.md`

**Files:**
- Modify: `home/common/agent-skills/README.md` (append sections at the end; existing content unchanged)
- Modify: `CLAUDE.md` (the bullets that hold base lines L67, L68, L69, L70, L71 and L72 only)
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py` (delete three test methods)

**Interfaces:**
- Consumes: `CLAUDE.md` as at base `8e2bfb72` for those lines (`L<n>` = line `n` of `git show 8e2bfb72:CLAUDE.md`). Another task may already have removed L68's three "Plugins:" sentences (they go to the claude-code README, not here); if they are still present when you start, leave them in place. Touch no other paragraph.
- Produces: new sections at the end of `home/common/agent-skills/README.md`; two dictated pointer sentences in `CLAUDE.md`.

**Invariants:**
- Every moved sentence is copied verbatim (D2). Allowed edits only: name the subject where the sentence leaned on `CLAUDE.md` context (for example "It" opening F66–F68 becomes "`build-delivery`"), split into the sections below, and repair the dead pointer `.out-of-scope/host-contention-scheduling.md` to `.agents/knowledge/rejections/host-contention-scheduling.md` in F71 (D2). Code-span paths stay repo-root-relative as written.
- Sentences kept in `CLAUDE.md` are not copied into the README (D7).
- The four existing README sections and their wording are unchanged; the new sections are appended after `## Vendored skills` and its content.
- The `@.agents/instructions/bootstrap.md` line is untouched.
- A moved sentence that contradicts the code beside it is not corrected; list it in your report (file, line, sentence) for the owner to file.

## Fact-to-home rows (B6, B7)

Destination for every row: `home/common/agent-skills/README.md`, under the heading named. All rows are `moved`.

| Row | Base | Sentence opening | Heading | Anchor (in the README, absent from `CLAUDE.md`) |
|---|---|---|---|---|
| F41 | L67 | "`~/.codex/skills/` is Codex's own runtime state" | Global guidance and skill sources | `has to be removed by hand` |
| F42 | L67 | "Impeccable (`pbakaus/impeccable`) is pinned by the `impeccable` flake input" | Impeccable | ``immutable `skill-v<version>` tag`` |
| F43 | L67 | "`lib/impeccable.nix` builds it once" | Impeccable | `builds it once into one derived skill tree` |
| F44 | L67 | "The tree is upstream's `.claude/skills/impeccable` unchanged" | Impeccable | `` `scripts/bin/<os>-<arch>/impeccable` `` |
| F45 | L67 | "Both agents get that tree" | Impeccable | `` recursive `~/.claude/skills/impeccable` `` |
| F46 | L67 | "`~/.agents/bin/impeccable` puts the detector on PATH" | Impeccable | `by exec'ing the tree's own launcher` |
| F47 | L67 | "Detector availability is that pinned engine." | Impeccable | `Detector availability is that pinned engine` |
| F48 | L67 | "It is never downloaded on demand" | Impeccable | `never downloaded on demand` |
| F49 | L67 | "The session sets `IMPECCABLE_NO_UPDATE_CHECK=1`" | Impeccable | `` `IMPECCABLE_NO_UPDATE_CHECK=1` `` |
| F50 | L67 | "For the same reason, the store-writing verbs" | Impeccable | ``(`update`, `install`, `link`, `pin`)`` |
| F51 | L67 | "A bump edits the input's tag" | Impeccable | `A bump edits the input's tag` |
| F52 | L67 | "Evaluation fails when the engine version and the tree's `scripts/VERSION` disagree" | Impeccable | `` `scripts/VERSION` disagree `` |
| F53 | L67 | "Skills that are no longer installed are listed in `retiredSkillNames`" | Retired skills | `` `retiredSkillNames` `` |
| F54 | L67 | "Home Manager's own cleanup removes their old links on switch" | Retired skills | `without deleting anything` |
| F55 | L68 | "Two skills stay out of the shared tree" | Claude-only skills and the Codex stub | `would recursively delegate to itself` |
| F56 | L68 | "Codex gets its own `orchestrate-issues`" | Claude-only skills and the Codex stub | `` `workflow-state host-route --route codex` `` |
| F57 | L68 | "The `.superpowers/` paths throughout `home/common/agent-skills/`" | `.superpowers` paths and launch-fenced writers | ``(`primary/` or `wt-<worktree-name>/`, `` |
| F58 | L68 | "A shared checkout is also why writers are launch-fenced (#222)" | `.superpowers` paths and launch-fenced writers | `writers are launch-fenced (#222)` |
| F59 | L68 | "It commits only through the `launch-commit` command" | `.superpowers` paths and launch-fenced writers | `` only through the `launch-commit` command `` |
| F60 | L68 | "An owner's own `suspend`, `finish`, handoff `progress`" | `.superpowers` paths and launch-fenced writers | `is refused while a registered worker` |
| F61 | L68 | "The one deliberate worktree-local path" | `.superpowers` paths and launch-fenced writers | `retained Minor/Discussion candidate` |
| F62 | L68 | "Producer-report candidates are not written into a working tree" | `.superpowers` paths and launch-fenced writers | `removed by an unconditional cleanup` |
| F63 | L68 | "The tracked `.gitignore` is the backstop" | `.superpowers` paths and launch-fenced writers | `` `.git/info/exclude` is machine-local `` |
| F64 | L68 | "The name is historical" | `.superpowers` paths and launch-fenced writers | `there is no Superpowers input` |
| F65 | L69 | "Delivery objects are built, never hand-composed: `workflow-state build-delivery`" | Lifecycle helpers › `workflow-state build-delivery` | `` `delivery-contract/v1` `` |
| F66 | L69 | "It is read-only — no lock or write" | Lifecycle helpers › `workflow-state build-delivery` | `to skew-check a supplied one` |
| F67 | L69 | "A contract it cannot re-derive is served only when" | Lifecycle helpers › `workflow-state build-delivery` | `` `--kind current-selection` `` |
| F68 | L69 | "It refuses anything else it cannot derive" | Lifecycle helpers › `workflow-state build-delivery` | `carries the resolver's error document unchanged` |
| F69 | L70 | "Orchestration admission is declared, not measured" | Lifecycle helpers › Host admission | `` `~/.agents/share/host-declaration.json` `` |
| F70 | L70 | "`workflow-state control` claims an owner's whole role set" | Lifecycle helpers › Host admission | `` `host.admission.declaration` `` |
| F71 | L70 | "It is no CPU, memory or build-load figure" | Lifecycle helpers › Host admission | `.agents/knowledge/rejections/host-contention-scheduling.md` |
| F72 | L71 | "The anti-zombie bound counts progress, not phase changes" | Lifecycle helpers › Anti-zombie bound and progress markers | `The anti-zombie bound counts progress, not phase changes` |
| F73 | L71 | "`workflow-state mark-progress --repo-root …` records the marker" | Lifecycle helpers › Anti-zombie bound and progress markers | ``(ledger schema 6; `null` until first recorded)`` |
| F74 | L71 | "The first recording is a `baseline`" | Lifecycle helpers › Anti-zombie bound and progress markers | ``(`diverged`) write nothing`` |
| F75 | L71 | "`sdd` records a marker before its first task" | Lifecycle helpers › Anti-zombie bound and progress markers | `a long Phase 6 that suspends between tasks is not discarded` |
| F76 | L72 | "A relaunched owner's prompt carries a resume pack" | Lifecycle helpers › Resume pack | `A relaunched owner's prompt carries a resume pack` |
| F77 | L72 | "It is served for the current launch of an active attempt" | Lifecycle helpers › Resume pack | `` `current: false` preview `` |
| F100 | L72 | "orchestrate-issues §4 adds it to `resume` prompts, and from-issue to direct re-entry, `delegate` and the Phase-5 rollover; the pack is not a workflow response …" (the whole third sentence, through "(#265).") | Lifecycle helpers › Resume pack | `orchestrate-issues §4 adds it to `` `resume` `` prompts` |

Kept in `CLAUDE.md`, verbatim: L67's first two sentences ("Global guidance has one source at `home/common/agent-guidance/AGENTS.md`…" and "Global skills likewise have one source at `home/common/agent-skills/skills/`…").

- [ ] **Step 1: Write the failing gate**

Save as `$SCRATCH/task3-gate.py` (`$SCRATCH` = the directory `launch-scope scratch …` prints; never commit it):

```python
import pathlib, sys

def norm(path):
    return " ".join(pathlib.Path(path).read_text(encoding="utf-8").split())

claude, home = norm("CLAUDE.md"), norm("home/common/agent-skills/README.md")
anchors = [
    "has to be removed by hand", "immutable `skill-v<version>` tag",
    "builds it once into one derived skill tree", "`scripts/bin/<os>-<arch>/impeccable`",
    "recursive `~/.claude/skills/impeccable`", "by exec'ing the tree's own launcher",
    "Detector availability is that pinned engine", "never downloaded on demand",
    "`IMPECCABLE_NO_UPDATE_CHECK=1`", "(`update`, `install`, `link`, `pin`)",
    "A bump edits the input's tag", "`scripts/VERSION` disagree", "`retiredSkillNames`",
    "without deleting anything", "would recursively delegate to itself",
    "`workflow-state host-route --route codex`", "(`primary/` or `wt-<worktree-name>/`,",
    "writers are launch-fenced (#222)", "only through the `launch-commit` command",
    "is refused while a registered worker", "retained Minor/Discussion candidate",
    "removed by an unconditional cleanup", "`.git/info/exclude` is machine-local",
    "there is no Superpowers input", "`delivery-contract/v1`", "to skew-check a supplied one",
    "`--kind current-selection`", "carries the resolver's error document unchanged",
    "`~/.agents/share/host-declaration.json`", "`host.admission.declaration`",
    ".agents/knowledge/rejections/host-contention-scheduling.md",
    "The anti-zombie bound counts progress, not phase changes",
    "(ledger schema 6; `null` until first recorded)", "(`diverged`) write nothing",
    "a long Phase 6 that suspends between tasks is not discarded",
    "A relaunched owner's prompt carries a resume pack", "`current: false` preview",
    "orchestrate-issues §4 adds it to `resume` prompts", "still decides the task to resume (#265)",
]
kept = [
    "Global guidance has one source at `home/common/agent-guidance/AGENTS.md`",
    "Global skills likewise have one source at `home/common/agent-skills/skills/`",
    "](home/common/agent-skills/README.md)", "§ Lifecycle helpers",
]
bad = [f"missing from README: {a}" for a in anchors if a not in home]
bad += [f"still in CLAUDE.md: {a}" for a in anchors if a in claude]
bad += [f"kept text lost: {k}" for k in kept if k not in claude]
if ".out-of-scope/" in home or ".out-of-scope/" in claude:
    bad.append("dead .out-of-scope pointer survives")
tests = pathlib.Path("home/common/agent-skills/tests/test_workflow_skill_contracts.py").read_text(encoding="utf-8")
for pin in ("test_claude_md_describes_the_launch_fence", "test_claude_md_describes_the_marker",
            "test_claude_md_describes_the_resume_pack"):
    if pin in tests:
        bad.append(f"pin still present: {pin}")
print("\n".join(bad) or "task3 gate: pass")
sys.exit(1 if bad else 0)
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `python3 -I "$SCRATCH/task3-gate.py"`
Expected: exit 1, every anchor reported `missing from README`, and three `pin still present` lines.

- [ ] **Step 3: Move the text**

1. Append to `home/common/agent-skills/README.md`: `## Global guidance and skill sources` (F41), `## Impeccable` (F42–F52), `## Retired skills` (F53, F54), `## Claude-only skills and the Codex stub` (F55, F56), `## .superpowers paths and launch-fenced writers` (F57–F64), then `## Lifecycle helpers` with subsections `### workflow-state build-delivery` (F65–F68), `### Host admission` (F69–F71), `### Anti-zombie bound and progress markers` (F72–F75), `### Resume pack` (F76, F77, F100). Copy each sentence from `git show 8e2bfb72:CLAUDE.md`, not from memory.
2. In `CLAUDE.md`:
   - L67 bullet: keep its first two sentences, delete F41–F54, and append this dictated sentence (D1, D7):
     "Skill packaging (Codex's `~/.codex/skills/` runtime state, Impeccable, retired skills, the Claude-only `codex-collaboration` and `orchestrate-issues` skills and Codex's stub), the `.superpowers/` path homes and launch-fenced writers are in [`home/common/agent-skills/README.md`](home/common/agent-skills/README.md); new detail of that kind goes there, not here."
   - L68 bullet: delete F55–F64; if the three "Plugins:" sentences are still there, they stay; if the bullet is then empty, delete it.
   - Replace the L69, L70, L71 and L72 bullets with this one dictated bullet:
     "- Lifecycle helper contracts — `workflow-state build-delivery` (delivery objects are built, never hand-composed), host admission, the anti-zombie bound with `mark-progress`, and `resume-pack` — are in `home/common/agent-skills/README.md` § Lifecycle helpers; new helper-contract detail goes there, not here."
3. In `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, delete exactly the three methods `test_claude_md_describes_the_launch_fence`, `test_claude_md_describes_the_marker` and `test_claude_md_describes_the_resume_pack` (D5). Their classes keep their other tests and their `assert_ordered`/`read` helpers, which those tests still use.

- [ ] **Step 4: Verify**

Run: `python3 -I "$SCRATCH/task3-gate.py"` — Expected: `task3 gate: pass`, exit 0.
Run: `PYTHONPATH="$PWD/python" python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py` (timeout 600 s) — Expected: OK, no failures or errors.
Run: `grep -c '^@.agents/instructions/bootstrap.md$' CLAUDE.md` — Expected: `1`.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/README.md CLAUDE.md home/common/agent-skills/tests/test_workflow_skill_contracts.py
launch-commit --repo-root <ledger_repo_root> --run-id <run-id> --worker-id <worker-id> -- \
  -m "docs(claude-md): move skill sourcing and lifecycle-helper contracts to the agent-skills README (#330)"
```

The identity values and the commit-message trailers come from your dispatch brief; commits stay signed.
