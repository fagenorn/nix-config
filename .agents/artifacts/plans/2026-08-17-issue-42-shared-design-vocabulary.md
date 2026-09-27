# Shared Codebase Design Vocabulary Skill — Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

Spec: `.claude/specs/2026-08-17-issue-42-shared-design-vocabulary-design.md` (authoritative).
Issue: [#42 — Share the deep-module design vocabulary across agents](https://github.com/fagenorn/nix-config/issues/42).

**Goal:** Vendor Matt Pocock's `codebase-design` skill into `home/common/agent-skills/skills/` as one
attributed, repository-owned package so both Claude Code and Codex receive the complete deep-module
vocabulary through the distributor that already exists.

**Architecture:** Three additive changes and no Nix edit. A new directory
`home/common/agent-skills/skills/codebase-design/` holds five vendored files; the existing
`builtins.readDir ./skills` discovery in `home/common/agent-skills/default.nix` links it whole to
`~/.agents/skills/<name>` for Codex, and `programs.claude-code.skillsDir` in
`home/common/claude-code/default.nix` links the same sources to `~/.claude/skills/<name>/` for Claude
Code. A second `unittest.TestCase` class appended to the existing contract suite pins the vocabulary
and the four adaptations, and the agent-skills README gains one generic note about vendored skills.

**Tech stack:** Nix flake (nix-darwin + home-manager), Markdown skill packages, Python 3 `unittest`,
`just` recipes.

## Global Constraints

- Upstream is pinned at revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected 2026-08-17.
  Every vendored byte comes from `git show` at that revision (per D1).
- Vendor at high fidelity: upstream prose, headings, ASCII diagrams, TypeScript examples and file
  names are preserved. **Exactly four things change** and nothing else (per D1).
- **No Nix module may be edited.** `home/common/agent-skills/default.nix`,
  `home/common/claude-code/default.nix`, `home/common/codex/default.nix`, `lib/`, `flake.nix` and
  `justfile` all stay byte-identical. If a change to any of them looks required, that is a defect to
  report, not to fix.
- No new test file and no `justfile` recipe (per D9). No `evals/` directory (per D11). No flake input
  for the upstream and no runtime fetching.
- No literal `Agent(` anywhere in the package (per D6).
- The MIT notice text never appears in `SKILL.md` — only in the packaged `LICENSE` (per D2).
- The package is pure vocabulary: it names no caller, no consumer and no downstream workflow (per
  D8). Nothing may be stubbed or reserved for issue 43.
- **Concurrency:** issue 43 is in flight in a sibling worktree and touches the same two shared files
  (`home/common/agent-skills/README.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`).
  Every edit to both is a pure append of one contiguous block at end of file. Do not reflow, reorder
  or reindent existing content in either file, and do not add anything to the test file's top-of-file
  import or constant blocks.
- Base commit for every scoped gate: `b344aaf` (`origin/main`). Run the gates on this branch before
  any ship-time sync merge.

## Test seams

Only these two. A task needing a third is a plan bug (per D11).

1. **Shared deployment seam** — `just build`, then build the Home Manager generation directly and
   inspect the printed store path for `.agents/skills/codebase-design` (Codex) and
   `.claude/skills/codebase-design/` (Claude Code). Exercised by Task 1.
2. **Workflow contract seam** — `just agent-workflow-tests`, plus `just agent-model-matrix` unchanged.
   Exercised by Tasks 2 and 3.

Neither command activates. Proving the literal `~/.claude/skills/codebase-design` and
`~/.agents/skills/codebase-design` paths on the live machine requires `just switch`; that is the
author's step and explicitly **not** part of this issue's verification.

## Red-then-green evidence

Three acceptance criteria assert something is false at the starting commit. Each has an owning step:

- *No repository-managed package exists* → Task 1, Step 1 (`test ! -e` on the target directory).
- *Neither agent surface carries the skill* → Task 1, Step 1 (inspect the generation built from the
  base commit; `codebase-design` is absent from both surfaces).
- *The new contract test fails because its subject is absent* → Task 2, Step 2. The class is written
  first and run with the package temporarily relocated out of the tree, which reproduces the
  starting-commit condition exactly. This also demonstrates D9's containment property: the missing
  package errors only the new class's `setUpClass` and leaves the 31 existing tests passing. Keeping
  the package on disk during Task 2 (rather than ordering the test task first) is what lets every
  commit on the branch leave the suite green for the between-task review gate.

## Task index

| Task | Title | Files touched | Risk lane |
|---|---|---|---|
| Task 1 | Vendor the `codebase-design` package | `home/common/agent-skills/skills/codebase-design/{SKILL.md,DEEPENING.md,DESIGN-IT-TWICE.md,LICENSE,agents/openai.yaml}` | full |
| Task 2 | Pin the vocabulary contract | `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | low-risk |
| Task 3 | Document the vendoring convention | `home/common/agent-skills/README.md` | low-risk |

Task 1 is `full`: vendoring new agent-facing guidance is semantic documentation that becomes the
vocabulary contract downstream skills invoke, so it is neither mechanical nor bounded-local.

## Decisions

The spec owns the ledger (rows D1–D14). This plan adds none; every choice below rests on an existing
row, cited inline. Rows load-bearing per task:

- Task 1 — D1 (fidelity), D2 (packaged `LICENSE`, pointer only in `SKILL.md`), D3 (`agents/openai.yaml`
  verbatim), D4 (seam reconciliation), D5 (domain-vocabulary repoint), D6 (no literal `Agent(`;
  `issue-owner` tier), D7 (autonomous-run qualification), D8 (pure vocabulary), D14 (frontmatter
  description kept verbatim).
- Task 2 — D9 (second `TestCase` class in the existing file), D10 (what "skill-package validation"
  means here), D11 (two seams only), plus D2/D4/D5/D6/D7 as the adaptation pins.
- Task 3 — D12 (one generic README note).

---

## Task 1: Vendor the `codebase-design` package

**Files:**
- Create: `home/common/agent-skills/skills/codebase-design/SKILL.md`
- Create: `home/common/agent-skills/skills/codebase-design/DEEPENING.md`
- Create: `home/common/agent-skills/skills/codebase-design/DESIGN-IT-TWICE.md`
- Create: `home/common/agent-skills/skills/codebase-design/LICENSE`
- Create: `home/common/agent-skills/skills/codebase-design/agents/openai.yaml`
- Modify: **nothing.** No Nix file, no test, no README in this task.

**Interfaces:**
- Consumes: the pinned upstream tree, read only through `git show` (commands below).
- Produces, for Task 2 and for every downstream consumer:
  - directory name `codebase-design`, matching the `name:` in its `SKILL.md` frontmatter;
  - the five paths above, exactly (relative to the package root: `SKILL.md`, `DEEPENING.md`,
    `DESIGN-IT-TWICE.md`, `LICENSE`, `agents/openai.yaml`);
  - the four adapted strings quoted verbatim in Task 2's assertions — the seam clause, the
    domain-language repoint, the `issue-owner` tier sentence, and the autonomous-run paragraph, all
    reproduced word-for-word in Step 4 below;
  - `LICENSE` containing the literal revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, the literal
    `https://github.com/mattpocock/skills`, and the upstream notice starting at a line that is
    exactly `MIT License`.

**Invariants:**
- `DEEPENING.md` and `agents/openai.yaml` are byte-identical to upstream at the pinned revision.
- `SKILL.md` differs from upstream by exactly **1 removed** and **3 added** lines.
- `DESIGN-IT-TWICE.md` differs from upstream by exactly **1 removed** and **5 added** lines.
- Everything in `LICENSE` from the line `MIT License` to end of file is byte-identical to upstream's
  root `LICENSE`.
- The string `Agent(` appears in no file of the package.
- The string `CONTEXT.md` appears in none of the three markdown files. It *does* appear once in
  `LICENSE`, which names the repointed reference when describing adaptation 2 — that is intended.
- `SKILL.md` contains no sentence of the MIT notice.
- No file under `home/common/agent-skills/skills/codebase-design/` names issue 43, the
  `improve-codebase-architecture` skill, or any consumer of this vocabulary (per D8).

- [ ] **Step 1: Record the starting-commit falsification**

Run from the worktree root, before creating anything:

```sh
set -euo pipefail
test ! -e home/common/agent-skills/skills/codebase-design
echo "ABSENT AT BASE: no repository-managed package"
```

Expected: prints `ABSENT AT BASE: no repository-managed package` — no package exists yet.

Then build the generation from the current tree and confirm neither agent surface carries the skill:

```sh
set -euo pipefail
GEN0=$(nix --extra-experimental-features 'nix-command flakes' build \
  '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files' \
  --no-link --print-out-paths | tail -1)
test -n "$GEN0" && test -d "$GEN0"
# The parent surfaces must exist, or "the skill is absent" would be vacuously
# true of an empty or failed generation.
test -d "$GEN0/.agents/skills"
test -d "$GEN0/.claude/skills"
for surface in .agents/skills .claude/skills; do
  if test -e "$GEN0/$surface/codebase-design"; then
    echo "UNEXPECTEDLY PRESENT AT BASE: $surface/codebase-design" >&2; exit 1
  fi
done
echo "BOTH SURFACES: ABSENT AT BASE (parents present)"
```

Expected: prints `BOTH SURFACES: ABSENT AT BASE (parents present)` and exits 0. (`anis` in that
attribute path is `myvars.username` from `vars/default.nix`; `mbp` is the darwin host.)

This block **fails closed**: Nix stderr is not suppressed, `pipefail` propagates a build failure
through `tail`, and the generation and both parent directories are asserted to exist before absence
is claimed. A failed or empty build aborts the step rather than printing a false "absent".

Paste both observations into the task record — they are the evidence for two acceptance criteria.

- [ ] **Step 2: Extract the four upstream files verbatim**

The upstream scratch clone is already on disk at the path below, pinned to the revision. Do **not**
re-clone unless that path is missing; if it is, `git clone https://github.com/mattpocock/skills.git`
into a scratch directory and `git checkout 9c9f36ccd3995266cd675468af71639c8dde1ec5` first.

```sh
UPSTREAM=/private/tmp/claude-502/-Users-anis-tmp-nix-config/a7fdef11-3cd0-4343-8b23-a8b78bb5a408/scratchpad/mattpocock-skills
REV=9c9f36ccd3995266cd675468af71639c8dde1ec5
SRC=skills/engineering/codebase-design
DEST=home/common/agent-skills/skills/codebase-design

mkdir -p "$DEST/agents"
git -C "$UPSTREAM" show "$REV:$SRC/SKILL.md"           > "$DEST/SKILL.md"
git -C "$UPSTREAM" show "$REV:$SRC/DEEPENING.md"       > "$DEST/DEEPENING.md"
git -C "$UPSTREAM" show "$REV:$SRC/DESIGN-IT-TWICE.md" > "$DEST/DESIGN-IT-TWICE.md"
git -C "$UPSTREAM" show "$REV:$SRC/agents/openai.yaml" > "$DEST/agents/openai.yaml"
```

Do not open these in an editor and retype them. Every byte comes from `git show` (per D1). All four
upstream files end with a trailing newline; preserve that.

- [ ] **Step 3: Verify the verbatim extraction before adapting anything**

```sh
diff <(git -C "$UPSTREAM" show "$REV:$SRC/SKILL.md")           "$DEST/SKILL.md"
diff <(git -C "$UPSTREAM" show "$REV:$SRC/DEEPENING.md")       "$DEST/DEEPENING.md"
diff <(git -C "$UPSTREAM" show "$REV:$SRC/DESIGN-IT-TWICE.md") "$DEST/DESIGN-IT-TWICE.md"
diff <(git -C "$UPSTREAM" show "$REV:$SRC/agents/openai.yaml") "$DEST/agents/openai.yaml"
```

Expected: four empty diffs, exit 0 each. Any output here means the extraction is wrong; fix it before
Step 4.

- [ ] **Step 4: Apply exactly the four adaptations**

These four edits, and no others. Each replacement string is reproduced here in full because Task 2
asserts on it verbatim; copy them character for character, including the em dashes and backticks.

**(a) `SKILL.md` — seam reconciliation (per D4).** In the `## Glossary` section, replace this single
upstream line:

```
**Seam** _(Michael Feathers)_ — a place where you can alter behaviour without editing in that place; the *location* at which a module's interface lives. Where to put the seam is its own design decision, distinct from what goes behind it. _Avoid_: boundary (overloaded with DDD's bounded context).
```

with this single line:

```
**Seam** _(Michael Feathers)_ — a place where you can alter behaviour without editing in that place; the *location* at which a module's interface lives. Where to put the seam is its own design decision, distinct from what goes behind it. A **test seam**, as the design and planning skills use the term, is one of these seams chosen as the boundary that verification crosses — the same concept, named for the role it is playing. _Avoid_: boundary (overloaded with DDD's bounded context).
```

Feathers' definition is untouched; the added clause is a clarification, not a redefinition. It is
true of the live repository: `home/common/agent-skills/skills/design/SKILL.md` defines test seams as
"the public boundaries this work will be tested at", and no existing skill's text changes (per D4).

**(b) `SKILL.md` — provenance pointer (per D2).** Append to the end of the file, after the final
`- **Exploring alternative interfaces** — see [DESIGN-IT-TWICE.md]...` bullet, one blank line then
this single line:

```
_Adapted from Matt Pocock's `codebase-design` skill; provenance and the upstream MIT notice are recorded in [LICENSE](LICENSE)._
```

It is a closing footer, deliberately **not** an entry under "Going deeper" — that section lists
references an agent should load, and the licence is not one. No notice text appears in `SKILL.md`.

**(c) `DESIGN-IT-TWICE.md` — domain-vocabulary repoint (per D5).** In `### 2. Spawn sub-agents`,
replace this single upstream line:

```
Include both [SKILL.md](SKILL.md) vocabulary and CONTEXT.md vocabulary in the brief so each sub-agent names things consistently with the architecture language and the project's domain language.
```

with this single line:

```
Include both [SKILL.md](SKILL.md) vocabulary and the project's domain language in the brief so each sub-agent names things consistently with the architecture language and the project's domain language. Resolve the domain language the way the `doc-grounded-questions` skill does: read the project's context map and its area context files where the project has them, and skip them silently where it does not.
```

This is true of the live skill: `doc-grounded-questions/SKILL.md` says "skip any configured-but-absent
doc path, sibling skill, or hints file silently", and the agent-skills README locates domain language
at `docs/CONTEXT-MAP.md` plus `docs/areas/<area>/CONTEXT.md`.

**(d) `DESIGN-IT-TWICE.md` — exploration-step qualifications (per D6, D7).** Two purely additive
paragraphs; do not modify the surrounding lines.

*Tier (D6).* In `### 2. Spawn sub-agents`, immediately after the paragraph
`Spawn 3+ sub-agents in parallel. Each must produce a **radically different** interface for the deepened module.`,
insert one blank line then:

```
Each sub-agent is producing a design, not performing a bounded lookup, so dispatch them at the `issue-owner` tier rather than the cheap `explorer` tier.
```

*Autonomous runs (D7).* At the very end of the file, after the paragraph ending
`Be opinionated — the user wants a strong read, not a menu.`, insert one blank line then:

```
When the run has no user — an autonomous run — nothing here waits: there is nobody to show the framing to in Step 1, and nobody to absorb the comparison here. The recommendation is the answer, and the comparison outcome is recorded as a decision-ledger row rather than waited on.
```

Neither paragraph introduces a literal `Agent(` (per D6). Upstream's `Agent 1:` … `Agent 4:` bullets
stay exactly as they are — they are prose labels, not dispatch syntax.

- [ ] **Step 5: Compose the packaged `LICENSE`**

Write this preamble as `home/common/agent-skills/skills/codebase-design/LICENSE` — exactly this text,
ending with a trailing blank line:

```
Provenance
----------

This skill is a vendored adaptation of the `codebase-design` skill from Matt
Pocock's skills repository.

  Upstream:  https://github.com/mattpocock/skills
  Path:      skills/engineering/codebase-design/
  Revision:  9c9f36ccd3995266cd675468af71639c8dde1ec5
  Inspected: 2026-08-17

Upstream's prose, headings, diagrams, code examples and file names are
preserved. Four things differ:

  1. SKILL.md's `Seam` glossary entry gains a clause reconciling upstream's
     seam with the `test seam` this system's design and planning skills
     already say.
  2. DESIGN-IT-TWICE.md's `CONTEXT.md vocabulary` reference is repointed at
     the project's domain language as `doc-grounded-questions` resolves it.
  3. DESIGN-IT-TWICE.md's parallel exploration names the dispatch tier those
     briefs belong to and says what happens when the run has no user.
  4. SKILL.md gains one closing line pointing at this file.

There is no automatic synchronisation with upstream: refreshing this package
means comparing against a newer revision by hand, re-applying the four
adaptations, and moving the revision recorded above.

The upstream licence follows, reproduced unmodified.

```

Then append the upstream notice, unmodified:

```sh
git -C "$UPSTREAM" show "$REV:LICENSE" >> "$DEST/LICENSE"
```

The file must contain exactly one line that is exactly `MIT License` — the first line of the appended
notice. The preamble deliberately says "licence" in prose so it does not collide with that anchor.

- [ ] **Step 6: Verify the fidelity invariants**

Every invariant below is **asserted**, not printed: the block exits non-zero the moment one fails.
Do not replace an assertion with an `echo` of its status — a reported count is not a gate.

```sh
set -euo pipefail

# Byte-identical files (diff itself is the assertion)
diff <(git -C "$UPSTREAM" show "$REV:$SRC/DEEPENING.md")       "$DEST/DEEPENING.md"
diff <(git -C "$UPSTREAM" show "$REV:$SRC/agents/openai.yaml") "$DEST/agents/openai.yaml"
echo "DEEPENING + OPENAI: IDENTICAL"

# Exactly the named adaptations, asserted
assert_count() {  # <label> <expected> <actual>
  test "$3" -eq "$2" || { echo "FIDELITY: $1 expected $2, got $3" >&2; exit 1; }
}
skill_diff=$(diff <(git -C "$UPSTREAM" show "$REV:$SRC/SKILL.md") "$DEST/SKILL.md" || true)
twice_diff=$(diff <(git -C "$UPSTREAM" show "$REV:$SRC/DESIGN-IT-TWICE.md") "$DEST/DESIGN-IT-TWICE.md" || true)
assert_count "SKILL removed" 1 "$(printf '%s\n' "$skill_diff" | grep -c '^<' || true)"
assert_count "SKILL added"   3 "$(printf '%s\n' "$skill_diff" | grep -c '^>' || true)"
assert_count "TWICE removed" 1 "$(printf '%s\n' "$twice_diff" | grep -c '^<' || true)"
assert_count "TWICE added"   5 "$(printf '%s\n' "$twice_diff" | grep -c '^>' || true)"
echo "ADAPTATION COUNTS: EXACT"

# The upstream notice is reproduced verbatim from the `MIT License` anchor onward
anchor=$(grep -n '^MIT License$' "$DEST/LICENSE" | cut -d: -f1)
test "$(printf '%s\n' "$anchor" | wc -l)" -eq 1   # exactly one anchor line
diff <(git -C "$UPSTREAM" show "$REV:LICENSE") <(sed -n "$anchor,\$p" "$DEST/LICENSE")
echo "LICENSE NOTICE: VERBATIM"

# Prohibitions — each must match nothing; a match prints the offender and aborts.
if grep -rn 'Agent(' "$DEST"; then
  echo "PROHIBITED: a literal Agent( appears in the package (D6)" >&2; exit 1
fi
if grep -n 'CONTEXT\.md' "$DEST"/*.md; then
  echo "PROHIBITED: a markdown file still references CONTEXT.md (D5)" >&2; exit 1
fi
if grep -q 'Permission is hereby granted' "$DEST/SKILL.md"; then
  echo "PROHIBITED: MIT notice text appears in SKILL.md (D2)" >&2; exit 1
fi
echo "PROHIBITIONS: CLEAN"
```

Expected: `DEEPENING + OPENAI: IDENTICAL`, `ADAPTATION COUNTS: EXACT`, `LICENSE NOTICE: VERBATIM`,
`PROHIBITIONS: CLEAN`, and exit 0. Any other outcome is a real failure.

Two shell details matter here and are not stylistic. First, a bare `grep -c` that finds nothing
exits 1 while one that finds forbidden text exits 0, so `grep …; echo $?` reports the *inverse* of
the invariant — never write the prohibitions that way. Second, `set -e` deliberately does **not**
abort on a command whose status is inverted with `!`, so `! grep …` would also fail open; the `if …
then exit 1; fi` form above is what actually gates. The `CONTEXT.md` grep stays scoped to `*.md`:
`LICENSE` names the repointed reference on purpose and must not be caught here.

Then read the two non-empty diffs and confirm by eye that each hunk is one of the four adaptations in
Step 4 and nothing else.

- [ ] **Step 7: Verify at the deployment seam**

```sh
just build
```

Expected: the darwin configuration evaluates and builds, exit 0.

```sh
set -euo pipefail
GEN=$(nix --extra-experimental-features 'nix-command flakes' build \
  '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files' \
  --no-link --print-out-paths | tail -1)
test -n "$GEN" && test -d "$GEN"

for surface in .agents/skills/codebase-design .claude/skills/codebase-design; do
  for f in SKILL.md DEEPENING.md DESIGN-IT-TWICE.md LICENSE agents/openai.yaml; do
    test -f "$GEN/$surface/$f" || { echo "MISSING $surface/$f" >&2; exit 1; }
  done
done
test -L "$GEN/.agents/skills/codebase-design" \
  || { echo "CODEX SURFACE IS NOT A WHOLE-DIRECTORY LINK" >&2; exit 1; }
{ test -d "$GEN/.claude/skills/codebase-design" && test ! -L "$GEN/.claude/skills/codebase-design"; } \
  || { echo "CLAUDE SURFACE IS NOT A REAL DIRECTORY" >&2; exit 1; }
echo "DEPLOYMENT SEAM VERIFIED"
```

Expected: `DEPLOYMENT SEAM VERIFIED` and exit 0. Like Step 1 this block **fails closed** — every
check aborts the block instead of printing a diagnostic and continuing, so the success line can only
be reached when all twelve assertions held. That shows all five files, including the `agents/`
subdirectory, reaching both surfaces: Codex as one symlink to the whole store directory, Claude Code
as a real directory of individual store links.

`just build` alone is not sufficient here and must not be claimed as sufficient: its `result` symlink
is the system derivation and the home tree is not navigable from it, which is why the generation is
built directly. **Neither command activates.** The literal `~/.claude/skills/codebase-design` and
`~/.agents/skills/codebase-design` paths on the live machine only appear after `just switch` — the
author's step, out of scope for this issue.

The Linux host needs no second local build: the distributor reads the directory during evaluation, so
CI's `Nix Eval` job (which evaluates `nixosConfigurations.anis-desktop` and is the required check on
`main`) exercises the new directory there.

- [ ] **Step 8: Confirm no Nix file moved**

```sh
git status --porcelain --untracked-files=all
```

Expected: exactly five new paths, all under `home/common/agent-skills/skills/codebase-design/`
(`SKILL.md`, `DEEPENING.md`, `DESIGN-IT-TWICE.md`, `LICENSE`, `agents/openai.yaml`), and nothing
else. `--untracked-files=all` is required: plain `git status --porcelain` collapses a wholly
untracked directory to the single entry `?? …/codebase-design/`, which would not show the five
files and would hide a stray sixth. If any `.nix` file appears here, stop and report it as a
defect — the constraint is that no Nix edit is needed (per spec, Solution).

- [ ] **Step 9: Commit**

```sh
git add home/common/agent-skills/skills/codebase-design
git commit -m "feat(agent-skills): vendor the codebase-design vocabulary skill"
```

---

## Task 2: Pin the vocabulary contract

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Create: nothing. **No new test file and no `justfile` change** (per D9).

**Interfaces:**
- Consumes, from Task 1: the package at `home/common/agent-skills/skills/codebase-design/` with the
  five files `SKILL.md`, `DEEPENING.md`, `DESIGN-IT-TWICE.md`, `LICENSE`, `agents/openai.yaml`, and
  the four adapted strings quoted verbatim in the test code below.
- Consumes, from the existing file: the module-level constant `REPO_ROOT = Path(__file__).parents[4]`,
  already defined at line 6. Reuse it; do not redefine it.
- Produces: `class CodebaseDesignSkillContractsTest(unittest.TestCase)` plus the module-level helpers
  `skill_frontmatter(text) -> dict[str, str]` and `relative_markdown_links(text) -> Iterator[str]`.

**Invariants:**
- The edit is one contiguous block inserted immediately **before** the trailing
  `if __name__ == "__main__":` guard, at the end of the file. Nothing above that point changes — not
  the imports, not the constant block, not `nested_workflow_documents`, not
  `WorkflowSkillContractsTest`. This bounds the merge conflict with issue 43 to a single region.
- No helper is lifted out of `WorkflowSkillContractsTest` and none is copied from it. The new class
  needs neither `assert_ordered` nor `section`; it uses plain `assertIn`/`assertNotIn` and slicing.
- No new top-level `import`. `relative_markdown_links` is written without `re` precisely so the import
  block stays untouched.
- Fixtures are read in `setUpClass`, never at module import, so an absent package errors only this
  class (per D9).
- The class asserts only on the authored package. It asserts nothing about the built generation, no
  method calls, and nothing below the level of the authored files (per D11).

- [ ] **Step 1: Write the failing test**

Insert this block into `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, immediately
before the final `if __name__ == "__main__":` line, separated from the preceding class by two blank
lines:

```python
# --- codebase-design vocabulary package (issue 42) -------------------------
# One contiguous block at the end of the file. Concurrent work on neighbouring
# skills appends its own block here, so a merge conflicts at most once and is
# resolved by keeping both blocks.

CODEBASE_DESIGN_DIR = REPO_ROOT / "home/common/agent-skills/skills/codebase-design"
CODEBASE_DESIGN_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
CODEBASE_DESIGN_UPSTREAM = "https://github.com/mattpocock/skills"
CODEBASE_DESIGN_FILES = (
    "SKILL.md",
    "DEEPENING.md",
    "DESIGN-IT-TWICE.md",
    "LICENSE",
    "agents/openai.yaml",
)
# Each canonical term maps to a discriminating clause of its definition — enough
# that rewriting the meaning fails the contract, short enough that reflowing the
# paragraph around it does not. Every clause is verbatim upstream text and
# apostrophe-free, so no quoting subtleties travel with it.
CANONICAL_DESIGN_TERMS = {
    "Module": "anything with an interface and an implementation",
    "Interface": "everything a caller must know to use the module correctly",
    "Implementation": "inside a module, its body of code",
    "Depth": "the amount of behaviour a caller (or test) can exercise per unit of interface",
    "Seam": "a place where you can alter behaviour without editing in that place",
    "Adapter": "a concrete thing that satisfies an interface at a seam",
    "Leverage": "more capability per unit of interface they learn",
    "Locality": "change, bugs, knowledge, and verification concentrate in one place",
}


def skill_frontmatter(text):
    """Return a SKILL.md's YAML frontmatter as a flat ``key -> value`` dict.

    Values are everything after the first colon, stripped. The skill packages in
    this tree use only flat single-line frontmatter keys, so no YAML parser is
    pulled in. A document with no leading ``---`` fence yields an empty dict.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fields = {}
    for line in lines[1:]:
        if line.strip() == "---":
            break
        key, separator, value = line.partition(":")
        if separator:
            fields[key.strip()] = value.strip()
    return fields


def relative_markdown_links(text):
    """Yield each relative link target in `text`.

    A target is the ``target`` of a ``](target)`` sequence. Absolute URLs and
    bare in-document anchors are skipped: what this exists to catch is a link to
    a sibling file that is not in the package.
    """
    for chunk in text.split("](")[1:]:
        target = chunk.split(")", 1)[0]
        if target.startswith(("http://", "https://", "#")):
            continue
        yield target


class CodebaseDesignSkillContractsTest(unittest.TestCase):
    """The vendored deep-module vocabulary package.

    Fixtures are read here rather than at module import so that an absent or
    incomplete package errors only this class and leaves the rest of the
    suite's coverage reporting normally.
    """

    @classmethod
    def setUpClass(cls):
        cls.skill = (CODEBASE_DESIGN_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.deepening = (CODEBASE_DESIGN_DIR / "DEEPENING.md").read_text(encoding="utf-8")
        cls.twice = (CODEBASE_DESIGN_DIR / "DESIGN-IT-TWICE.md").read_text(encoding="utf-8")
        cls.notice = (CODEBASE_DESIGN_DIR / "LICENSE").read_text(encoding="utf-8")

    def glossary(self):
        start = self.skill.index("## Glossary")
        return self.skill[start : self.skill.index("## Deep vs shallow", start)]

    def test_package_passes_skill_package_validation(self):
        for relative in CODEBASE_DESIGN_FILES:
            with self.subTest(path=relative):
                self.assertTrue(
                    (CODEBASE_DESIGN_DIR / relative).is_file(),
                    f"missing package file: {relative}",
                )
        frontmatter = skill_frontmatter(self.skill)
        self.assertEqual(frontmatter.get("name"), CODEBASE_DESIGN_DIR.name)
        self.assertTrue(frontmatter.get("description", "").strip())
        # The trigger the rest of the skill tree depends on, kept verbatim (D14).
        self.assertIn(
            "another skill needs the deep-module vocabulary",
            frontmatter["description"],
        )

    def test_every_relative_link_in_the_package_resolves(self):
        documents = {
            "SKILL.md": self.skill,
            "DEEPENING.md": self.deepening,
            "DESIGN-IT-TWICE.md": self.twice,
        }
        package_root = CODEBASE_DESIGN_DIR.resolve()
        checked = 0
        for name, text in documents.items():
            for target in relative_markdown_links(text):
                checked += 1
                with self.subTest(document=name, target=target):
                    # Resolve against the containing document, then require the
                    # result to stay inside the package. `exists()` alone would
                    # let a `../../…` traversal pass by reaching a real file
                    # outside the package, which is not a resolving link.
                    resolved = (package_root / name).parent.joinpath(target).resolve()
                    self.assertTrue(
                        resolved.is_relative_to(package_root),
                        f"{name} links to {target}, which escapes the package",
                    )
                    self.assertTrue(
                        resolved.is_file(),
                        f"{name} links to {target}, which is not a file in the package",
                    )
        self.assertGreaterEqual(checked, 9, "the link scan found nothing to check")

    def test_glossary_defines_every_canonical_term(self):
        # Pin the definitions, not just the headings: a heading-only assertion
        # stays green while every definition is deleted or rewritten, which is
        # exactly the drift this contract exists to catch.
        glossary = self.glossary()
        for term, definition in CANONICAL_DESIGN_TERMS.items():
            with self.subTest(term=term):
                self.assertIn(f"\n**{term}**", glossary)
                self.assertIn(definition, glossary)

    def test_glossary_forbids_substituting_the_canonical_terms(self):
        glossary = self.glossary()
        self.assertIn(
            'Use these terms exactly — don\'t substitute "component," "service," '
            '"API," or "boundary."',
            glossary,
        )
        for avoided in (
            "_Avoid_: unit, component, service",
            "_Avoid_: API, signature",
            "_Avoid_: boundary",
        ):
            with self.subTest(avoided=avoided):
                self.assertIn(avoided, glossary)

    def test_deletion_test_keeps_both_branches(self):
        self.assertIn("**The deletion test.**", self.skill)
        self.assertIn("If complexity vanishes, it was a pass-through.", self.skill)
        self.assertIn(
            "If complexity reappears across N callers, it was earning its keep.",
            self.skill,
        )

    def test_interface_is_the_test_surface_in_both_files(self):
        self.assertIn(
            "**The interface is the test surface.** Callers and tests cross the "
            "same seam.",
            self.skill,
        )
        self.assertIn("The **interface is the test surface**.", self.deepening)

    def test_adapter_seam_rule_is_pinned_in_both_files(self):
        rule = "One adapter means a hypothetical seam. Two adapters means a real one."
        self.assertIn(rule, self.skill)
        self.assertIn(rule, self.deepening)

    def test_seam_entry_reconciles_this_repositorys_test_seam(self):
        glossary = self.glossary()
        start = glossary.index("**Seam**")
        seam_entry = glossary[start : glossary.index("**Adapter**", start)]
        self.assertIn(
            "a place where you can alter behaviour without editing in that place",
            seam_entry,
        )
        self.assertIn(
            "A **test seam**, as the design and planning skills use the term, is "
            "one of these seams chosen as the boundary that verification crosses",
            seam_entry,
        )

    def test_deepening_carries_all_four_dependency_categories(self):
        for heading in (
            "### 1. In-process",
            "### 2. Local-substitutable",
            "### 3. Remote but owned (Ports & Adapters)",
            "### 4. True external (Mock)",
        ):
            with self.subTest(heading=heading):
                self.assertIn(heading, self.deepening)
        start = self.deepening.index("### 3. Remote but owned (Ports & Adapters)")
        ports = self.deepening[
            start : self.deepening.index("### 4. True external (Mock)", start)
        ]
        self.assertIn(
            "implement an HTTP adapter for production and an in-memory adapter "
            "for testing",
            ports,
        )

    def test_design_it_twice_keeps_the_workflow_and_its_adaptations(self):
        self.assertIn("Spawn 3+ sub-agents in parallel.", self.twice)
        self.assertIn("**radically different**", self.twice)
        self.assertIn(
            "Contrast by **depth** (leverage at the interface), **locality** "
            "(where change concentrates), and **seam placement**.",
            self.twice,
        )
        # D5: upstream's dangling CONTEXT.md reference stays repointed.
        self.assertNotIn("CONTEXT.md", self.twice)
        self.assertIn(
            "Resolve the domain language the way the `doc-grounded-questions` "
            "skill does",
            self.twice,
        )
        # D7: an autonomous run has nobody to stall on.
        self.assertIn("The recommendation is the answer", self.twice)
        self.assertIn("recorded as a decision-ledger row", self.twice)

    def test_package_carries_no_dispatch_site_and_names_the_owner_tier(self):
        for path in sorted(CODEBASE_DESIGN_DIR.rglob("*")):
            if not path.is_file():
                continue
            with self.subTest(path=str(path.relative_to(CODEBASE_DESIGN_DIR))):
                self.assertNotIn("Agent(", path.read_text(encoding="utf-8"))
        # D6: the tier is stated in words instead.
        self.assertIn(
            "dispatch them at the `issue-owner` tier rather than the cheap "
            "`explorer` tier",
            self.twice,
        )

    def test_license_records_provenance_and_the_upstream_notice(self):
        self.assertIn(CODEBASE_DESIGN_UPSTREAM, self.notice)
        self.assertIn(CODEBASE_DESIGN_REVISION, self.notice)
        self.assertIn("Copyright (c) 2026 Matt Pocock", self.notice)
        self.assertIn(
            "Permission is hereby granted, free of charge, to any person "
            "obtaining a copy",
            self.notice,
        )
        self.assertIn(
            "The above copyright notice and this permission notice shall be "
            "included in all",
            self.notice,
        )
        # D2: SKILL.md points at the notice and never carries it.
        self.assertIn("[LICENSE](LICENSE)", self.skill)
        self.assertNotIn("Permission is hereby granted", self.skill)
```

- [ ] **Step 2: Run the test with its subject absent and watch it fail**

This reproduces the starting-commit condition: the class exists, the package does not.

```sh
HIDE=$(mktemp -d)
# The trap restores the package even if the run is interrupted, so an aborted
# falsification cannot leave the committed package sitting in a temp directory.
trap 'test -e "$HIDE/codebase-design" && mv "$HIDE/codebase-design" home/common/agent-skills/skills/' EXIT
mv home/common/agent-skills/skills/codebase-design "$HIDE/"
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -20
mv "$HIDE/codebase-design" home/common/agent-skills/skills/
trap - EXIT
git status --porcelain home/common/agent-skills/skills/codebase-design
```

Expected: the run reports `ERROR: setUpClass (…CodebaseDesignSkillContractsTest)` with a
`FileNotFoundError` naming `…/skills/codebase-design/SKILL.md`, and ends `Ran 31 tests` …
`FAILED (errors=1)`. The count stays 31 because a class whose `setUpClass` raises contributes one
error and runs none of its own methods — so the 31 tests of `WorkflowSkillContractsTest` are exactly
what ran, and they all passed. That containment is D9's whole point; a run that reports any failure
*inside* `WorkflowSkillContractsTest` means the block was inserted in the wrong place.

The final `git status --porcelain` must print **nothing** — the package is back where it belongs. If
it prints anything, restore the directory before continuing.

- [ ] **Step 3: Run the test against the real package**

No implementation to write: Task 1 already produced the subject. Restore-and-run only.

```sh
python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py 2>&1 | tail -5
```

Expected: `Ran 43 tests` … `OK` (31 existing + 12 new).

If a single assertion fails, the vendored text and this plan's quoted string have diverged. Fix the
**vendored file** to match the string quoted in Step 1 — those strings are Task 1's contract, and
Task 1's fidelity gate (`SKILL removed: 1 / added: 3`, `TWICE removed: 1 / added: 5`) must still hold
afterwards. Do not loosen an assertion to make it pass.

- [ ] **Step 4: Verify at the contract seam**

```sh
just agent-workflow-tests 2>&1 | tail -5
just agent-model-matrix 2>&1 | tail -5
```

Expected: `Ran 212 tests` … `OK` (the baseline is 200), and `agent-model-matrix` passes with its
output unchanged. A diff to `home/common/agent-skills/model-matrix.json` would mean D6 was violated:

```sh
git diff --stat b344aaf -- home/common/agent-skills/model-matrix.json
```

Expected: no output. Note the single `b344aaf`, not the range `b344aaf..HEAD`: this step runs
*before* the task's commit, so a range comparison would compare committed history only and miss a
staged or unstaged edit sitting in the worktree. `git diff <base>` compares the base against the
working tree and therefore covers committed, staged, and unstaged state together.

- [ ] **Step 5: Commit**

```sh
git add home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "test(agent-skills): pin the codebase-design vocabulary contract"
```

---

## Task 3: Document the vendoring convention

**Files:**
- Modify: `home/common/agent-skills/README.md`

**Interfaces:**
- Consumes: the finished package from Task 1 (specifically, that its provenance record is an
  extensionless `LICENSE` inside the skill directory carrying upstream URL, pinned revision,
  inspection date and the list of adaptations) and the contract class from Task 2 (specifically, that
  it pins each adaptation).
- Produces: nothing other tasks depend on. This is the last task.

**Invariants:**
- The note is **generic**: it describes the convention for any vendored skill and names no particular
  skill, so the sibling vendored package from issue 43 needs no second note (per D12).
- The edit is a pure append of one new `##` section at the very end of the README. The adapter
  contract table, the `projectHints` section and the onboarding list are untouched — issue 43 edits
  the same file, and appending at the end keeps the conflict region to one block.
- Every sentence is true of what Tasks 1 and 2 actually built. Re-read the finished `LICENSE` and the
  finished test class before committing, and correct any sentence that has drifted.

- [ ] **Step 1: Confirm the README says nothing about vendoring yet**

```sh
grep -in "vendor\|provenance\|upstream" home/common/agent-skills/README.md
```

Expected: no output. If the note already exists, this task is a no-op and that is a finding to report,
not a second note to add.

- [ ] **Step 2: Append the section**

Append to the end of `home/common/agent-skills/README.md`, after the `## Onboarding a new project`
list, one blank line then:

```markdown
## Vendored skills

A directory under `skills/` may be a **vendored adaptation** of an upstream skill rather than an
authored one. Such a directory carries the upstream `LICENSE` inside it as its provenance record: the
upstream URL, the pinned revision, the date it was inspected, and every way the adaptation departs
from upstream, followed by the upstream notice reproduced unmodified. Keeping the notice in that file
and out of `SKILL.md` keeps it out of the body that loads with the skill, while `SKILL.md` still
links to it so the provenance is one hop away.

Nothing fetches or refreshes these at build time — there is no flake input for the upstream and no
synchronisation. A refresh is a manual comparison against a newer revision: re-apply the recorded
adaptations by hand and move the pin. The contract suite in `tests/` pins each adaptation, so a
careless refresh fails a test rather than silently reverting one.
```

- [ ] **Step 3: Verify the note is accurate and the rest of the README is untouched**

```sh
git diff -- home/common/agent-skills/README.md
```

Expected: additions only — no `-` lines at all. The README already ends with a newline, so a clean
append produces none. Read the two paragraphs against the finished `LICENSE`
(`home/common/agent-skills/skills/codebase-design/LICENSE`) and confirm each claim holds: URL,
revision, inspection date, list of departures, unmodified notice, no synchronisation.

- [ ] **Step 4: Verify the whole change at both seams and confirm no special-case distribution logic**

```sh
just build
just agent-workflow-tests 2>&1 | tail -5
just agent-model-matrix 2>&1 | tail -5
```

Expected: build exits 0; `Ran 212 tests` … `OK`; model matrix passes.

```sh
git diff --stat b344aaf -- \
  home/common/agent-skills/default.nix \
  home/common/claude-code/default.nix \
  home/common/codex/default.nix \
  lib/ flake.nix flake.lock justfile
```

Expected: **no output.** This is the acceptance criterion "no special-case distribution logic added
for this skill" — the whole distribution change was creating a directory. As in Task 2, the base is
given as a single commit rather than the range `b344aaf..HEAD`, so the gate sees uncommitted edits
too; this step runs before the task's commit. Run it on the branch before any ship-time sync merge;
the pathspec keeps the plan and spec artifacts out of the comparison.

- [ ] **Step 5: Commit**

```sh
git add home/common/agent-skills/README.md
git commit -m "docs(agent-skills): record the vendored-skill convention"
```

---

## Standards review provenance

- **Reviewer:** Codex, in an isolated read-only runtime (fresh `CODEX_HOME`, approval policy
  `never`, sandbox `read-only`). No native fallback was needed.
- **Base SHA:** `b344aaf527920dce8a47c2b9a11244234f2383d0`; plan reviewed at `14eafc1`.
- **Focus:** none configured (`codex.planReview.focus` unset).
- **Findings:** 3 Blocking, 4 Should-fix, 3 Discussion. **7 accepted and applied** (all Blocking and
  all Should-fix), **0 rejected**, **0 deferred**. Of the Discussion items, one was a read-status
  report, one recommended a shell `trap` around the temporary-removal falsification and was applied,
  and one confirmed the scope and activation boundaries with no action.
- **Verification:** every finding was re-checked against the live plan and spec at `14eafc1` before
  being applied; none were stale. The reviewer could not reach `api.github.com`, so it worked from
  the supplied issue body and verbatim acceptance criteria rather than a live fetch.
- **Ledger:** the two non-obvious dispositions are recorded as spec rows **D15** (gates fail closed
  and compare against the working tree) and **D16** (the contract pins definitions and package
  containment). The remaining applied findings were routine corrections and get no row.
