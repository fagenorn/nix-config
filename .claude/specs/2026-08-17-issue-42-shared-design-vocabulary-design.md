# Shared Codebase Design Vocabulary Skill

Issue: [#42 — Share the deep-module design vocabulary across agents](https://github.com/fagenorn/nix-config/issues/42)

## Problem

The system has no shared name for the things it designs. "Module", "interface", "seam", "adapter",
"depth" and "leverage" are used loosely across the skill tree, and the one place that defines them
rigorously — Matt Pocock's `codebase-design` skill — lives outside this repository entirely. Nothing
here can invoke it, neither agent receives it, and any skill that needs the vocabulary has no choice
but to restate a private approximation of it.

That gap is now blocking. The approved parent design for the architecture-improvement workflow makes
Codebase Design *the single* vocabulary and principle source that downstream skills invoke rather
than copy. Until that source exists as a repository-owned skill that both Claude Code and Codex
receive, "invoke the vocabulary module" names nothing.

The desired result is one complete, attributed, repository-owned `codebase-design` package that
arrives at both agents through the shared distributor that already exists, with no plugin, no
marketplace, no second copy of the glossary, and no installation path built specially for it.

## Solution

Create `home/common/agent-skills/skills/codebase-design/` as an attributed adaptation of the
upstream package at revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected 2026-08-17. The
directory carries the adapted `SKILL.md`, both upstream references (`DEEPENING.md`,
`DESIGN-IT-TWICE.md`), the upstream Codex interface metadata (`agents/openai.yaml`), and a packaged
`LICENSE` holding the provenance record and the verbatim upstream MIT notice.

Creating that directory *is* the entire distribution change. The shared distributor already derives
its skill set by reading the `skills/` directory, so the package reaches Codex as a whole-directory
link at `~/.agents/skills/codebase-design` and reaches Claude Code at
`~/.claude/skills/codebase-design/` through the same authored sources. No Nix module is edited. Any
proposal that requires editing one is a defect in the proposal, not a licence to edit.

The adaptation is deliberately conservative: upstream prose, headings, diagrams, code examples and
file names are preserved, and exactly four things change — the dangling domain-vocabulary reference
is repointed at this system's grounding surface, the parallel-exploration step is qualified for this
system's dispatch and autonomous-run contracts, the glossary's **seam** entry reconciles with the
"test seam" this repository already says, and a one-line provenance pointer is added. Everything
else is upstream's, on purpose.

Coverage is a second `unittest.TestCase` class appended to the existing skill-contract suite. It
pins the canonical vocabulary, the deletion test, the interface-as-test-surface principle, the
two-adapter seam rule, dependency categories, reference availability, and the adaptation decisions
that a future refresh could silently undo.

## Decisions

### The package

The skill directory holds five files:

- **`SKILL.md`** — frontmatter (`name: codebase-design` plus upstream's description, which already
  states the "another skill needs the deep-module vocabulary" trigger this system depends on),
  then the glossary of eight canonical terms, the deep-vs-shallow contrast, the four principles,
  the testability guidance, the relationship list, the rejected framings, and the "Going deeper"
  links to both references.
- **`DEEPENING.md`** — the four dependency categories (in-process, local-substitutable,
  remote-but-owned/ports-and-adapters, true-external/mock), seam discipline, and replace-don't-layer
  testing.
- **`DESIGN-IT-TWICE.md`** — frame the problem space, explore the interface several radically
  different ways in parallel, then present and compare on depth, locality and seam placement.
- **`agents/openai.yaml`** — upstream's two `interface` keys (`display_name`, `short_description`)
  and nothing else (per D3).
- **`LICENSE`** — provenance preamble plus the verbatim upstream MIT notice (per D2).

The package is pure vocabulary (per D8). It names no caller, no downstream workflow and no
consuming skill; consumers invoke it, and the module does not know who they are.

### The four adaptations

Everything below is a change from upstream. Nothing else in the vendored text changes (per D1).

**Provenance pointer.** `SKILL.md` gains a single closing line stating that the skill is an adapted
copy and pointing at the packaged `LICENSE`. The notice text itself never appears in `SKILL.md`, so
it is never injected into a model's context (per D2). The line is a closing footer, deliberately not
an entry under "Going deeper" — that section lists references an agent should load, and the license
is not one. Inside `LICENSE`, the provenance preamble is clearly separated from the upstream MIT
text, which is reproduced unmodified.

**Seam reconciliation.** The glossary's **seam** entry keeps Feathers' definition verbatim and gains
one clause tying it to this system's existing usage: a **test seam**, as the design and planning
skills use the term, is a seam chosen as the boundary that verification crosses. This is a
clarification, not a redefinition — upstream already asserts that callers and tests cross the same
seam. No other skill's text changes (per D4).

**Domain-vocabulary repoint.** `DESIGN-IT-TWICE.md`'s instruction to include "CONTEXT.md vocabulary"
in each exploration brief becomes an instruction to include the project's domain language as
resolved by `doc-grounded-questions`, which reads the context map and area context files where a
project has them and skips them silently where it does not (per D5). This is the only dangling
reference in the upstream package; every other link is intra-package and resolves.

**Exploration-step qualification.** `DESIGN-IT-TWICE.md`'s parallel exploration stays prose and
gains two qualifications (per D6, D7): the briefs carry design judgment, so they are `issue-owner`-
tier work rather than the bounded `explorer` tier; and when the run has no user, the recommendation
is the answer and the comparison outcome is recorded as a decision-ledger row rather than waited on.
No literal `Agent(` call is introduced.

### Distribution behaviour

The distributor's skill set is derived by reading the `skills/` directory, so the new package is
picked up with no Nix edit. Both delivery mechanisms already carry multi-file packages including
subdirectories, which is what lets `agents/openai.yaml` travel: Codex receives one symlink to the
whole store directory, and Claude Code receives a real directory whose entries are individual store
links.

The one-time `migrateCodexSkillLinks` activation script iterates the same derived skill set and so
gains `codebase-design` automatically. This is inert for a new skill: the function returns
immediately when the target does not already exist as a real directory, which is the case for every
machine that has never had a legacy layout for a skill that has never shipped. No migration
behaviour needs designing.

### Contract coverage

A second `unittest.TestCase` class in the existing skill-contract suite (per D9), with its own
fixture setup so that a missing package fails only the new class and leaves the suite's existing
coverage untouched — which is what makes the falsification evidence at the starting commit clean
rather than destructive. If any assertion needs one of the existing class's helpers, the helper is
lifted to module level and both classes call it; it is never copied. The class pins:

1. **Package structure and skill-package validation** (per D10) — `SKILL.md` exists, its frontmatter
   `name` equals the directory name, its description is non-empty, and both references and the
   Codex metadata file are present.
2. **Reference availability** — every relative markdown link in every file of the package resolves
   to a file that exists inside the package. This is the assertion that permanently forecloses a
   reintroduced dangling reference, including the one repointed under D5.
3. **Canonical vocabulary** — all eight terms are defined as glossary entries: module, interface,
   implementation, depth, seam, adapter, leverage, locality.
4. **Substitution ban** — the glossary's "don't substitute" instruction and its avoid-list survive,
   since a glossary that no longer forbids the synonyms has stopped being a single source.
5. **The deletion test** — present with both branches (complexity vanishes → pass-through;
   complexity reappears across callers → earning its keep).
6. **Interface as test surface** — the principle is stated in `SKILL.md` and restated as the testing
   rule in `DEEPENING.md`.
7. **The adapter/seam rule** — one adapter means a hypothetical seam, two means a real one; pinned
   in both files that carry it, so the two copies cannot drift apart.
8. **Seam reconciliation** — the glossary's seam entry names this repository's "test seam" usage
   (per D4).
9. **Dependency categories** — all four categories present in `DEEPENING.md`, with the
   ports-and-adapters category naming both the production and the test adapter.
10. **Design-it-twice availability** — the parallel-exploration workflow and its comparison axes
    (depth, locality, seam placement) survive.
11. **No unregistered dispatch** — no literal `Agent(` appears anywhere in the package (per D6).
    The model-matrix validator cannot catch this, because it only scans files registered as
    dispatch-site paths; this assertion is the substitute.
12. **Attribution** — `LICENSE` exists, carries the upstream copyright line and the MIT permission
    notice, names the pinned revision, and is pointed at from `SKILL.md` (per D2).

### Documentation

The agent-skills README gains a short, generically worded note that a skill directory may be a
vendored adaptation, that such a directory carries its upstream `LICENSE` as the provenance record,
and that refreshes are manual comparisons rather than automatic synchronisation (per D12). Written
once and generically so the sibling vendored skill needs no second note.

`grill-with-docs` ran against this spec and would normally land the new terminology as glossary
entries and the irreversible calls as ADRs. This repository has no `docs/` tree and creating one is
out of scope, so every such outcome is recorded as a row in the Decision ledger below instead — D4
and D14 carry what would have been glossary work, and D2, D9 and D12 carry what would have been
ADRs. That substitution is a graceful degradation, not a blocker: the vocabulary's authoritative
home is the vendored `SKILL.md` itself, which is a better home for it than a glossary entry would
have been, and the ADR-shaped calls are hard to reverse but small enough to state in one row each.

## Test seams

Two seams, both already public. This follows parent design D6, minus its third seam: the deployed-
behaviour eval belongs to the architecture workflow that consumes this vocabulary, not to the
vocabulary package, which has no workflow to exercise.

**1. Shared deployment seam.** The built, unactivated Home Manager generation must expose the
complete package to both agents.

```sh
just build   # public gate: the darwin configuration still evaluates and builds

nix build '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files' \
  --no-link --print-out-paths
```

The user attribute in that command is the configured `username` from the repository's variables, not
a literal to be assumed; `mbp` is the darwin host.

Inspect the printed store path for both surfaces. Each must carry the whole package — `SKILL.md`,
`DEEPENING.md`, `DESIGN-IT-TWICE.md`, `LICENSE`, and an `agents/` directory containing
`openai.yaml`:

- `.agents/skills/codebase-design` — a single symlink to a whole store directory, listed through.
  This is the Codex surface.
- `.claude/skills/codebase-design/` — a real directory whose files are individual store links.
  This is the Claude Code surface.

Be honest about the boundary: `just build` alone proves the configuration evaluates and builds, but
its `result` symlink is the system derivation and the home tree is not navigable from it — hence the
second command, which builds the generation artifact directly and is the thing actually inspected.
Neither command activates. Proving the literal `~/.claude/skills/codebase-design` and
`~/.agents/skills/codebase-design` paths on the live machine requires `just switch`, which is the
author's call and not part of this issue's verification.

Build the generation rather than evaluating `home.file`. The Codex-side link is a `home.file` entry
and can be read by pure evaluation, but the Claude Code surface is produced by the Claude Code
module from its skills directory and has **no** `home.file` entry at all — an evaluation-only check
would silently verify one agent and claim both. The built generation is the only artifact that shows
both.

The Linux host is covered without a second local build: the distributor derives its skill set by
reading the directory during evaluation, so CI's `Nix Eval` job — which evaluates the NixOS
configuration and is the required check on `main` — exercises the new directory on that host too.

**2. Workflow contract seam.** `just agent-workflow-tests` runs the extended suite; the new class
must pass on the finished branch and fail on the starting commit, where its subject is absent.
`just agent-model-matrix` must still pass **unchanged** — no dispatch site is added, no manifest
path is registered, and a diff to `model-matrix.json` would mean D6 was violated.

No third seam. No `evals/` directory: the eval harness grades workflows, and a vocabulary module has
no workflow to grade. No assertion about how a model uses the vocabulary once it has it, and no test
below the level of the authored package and its deployment.

## Out of scope

- The `improve-codebase-architecture` skill and everything else belonging to issue 43: its
  explicit-only Codex metadata, its dispatch registration in the model matrix, its HTML report, its
  routing, and its eval cases. This package must not stub, reference, or reserve anything for it.
- Any edit to the shared distributor, the Claude Code module, or the Codex module. The distributor
  needing a change would be a finding to report, not a change to make.
- Enforcing single-sourcing across *other* skills — asserting that no other skill redefines the
  eight terms. That is a cross-cutting migration touching text this issue does not own, and the
  consuming skill that would motivate it belongs to issue 43.
- Editing the seven existing files that say "test seam". D4 reconciles the terms inside the vendored
  glossary precisely so this stays unnecessary.
- Creating a `docs/` tree, context map, glossary, ADR directory, or standards deltas that this
  repository does not have.
- Importing upstream's `domain-modeling` or `grilling` skills.
- A Nix input for the upstream repository, automatic upstream synchronisation, or runtime fetching
  of skill text.
- Landing the parent design document onto this branch.
- Rewriting upstream's TypeScript examples in Nix or Python (see D1).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Vendor at high fidelity: upstream prose, headings, ASCII diagrams, TypeScript examples and file names are preserved; only the four adaptations named in Decisions change | Parent design D1 (attributed adaptation at the pinned revision); agent-skills README — the skills are project-agnostic and "carry zero project residue"; the machine standards ship `typescript-react` and `node` shards, so TS illustration is not foreign | Rewriting the examples in this repository's own languages: it adds the project residue the tree forbids and diverges from upstream for no reader benefit |
| D2 | Attribution is a packaged extensionless `LICENSE` inside the skill directory — provenance preamble (upstream URL, pinned revision, inspection date) plus the verbatim MIT notice — with a one-line pointer in `SKILL.md` and no notice text there | Parent design D1: the license notice "remains a packaged resource that is not injected into model context"; MIT requires the notice travel with copies; the-bar token economy | Notice in `SKILL.md` frontmatter or body: pays for the notice in every context that loads the skill. A separate `PROVENANCE.md`: a second file, and an unreferenced sibling `.md` in a skill package reads as a dead reference |
| D3 | Ship `agents/openai.yaml` verbatim with only upstream's two `interface` keys | Acceptance criterion demands a *complete* package; both delivery surfaces were verified to carry subdirectories, so it reaches both agents; three lines | Dropping it: an unforced divergence that costs Codex the human-facing name. Adding a policy key: pre-empts the explicit-only metadata interface that issue 43 owns |
| D4 | Upstream **seam** and this repository's **test seam** are one concept, reconciled by one clause inside the vendored glossary entry; no other skill's text changes | Upstream already states "The interface is the test surface. Callers and tests cross the same seam"; `design` defines test seams as "the public boundaries this work will be tested at"; every existing use is the qualified two-word form, so nothing collides | Renaming this repository's term, or editing the seven files that use it: a repo-wide terminology migration is a separate and much larger change than this issue |
| D5 | Repoint `DESIGN-IT-TWICE.md`'s "CONTEXT.md vocabulary" to the project's domain language as resolved by `doc-grounded-questions`, degrading silently where a project has no context map | Agent-skills README adapter table names that surface; `doc-grounded-questions` already skips absent doc paths silently; parent design bars importing `domain-modeling` | Keeping the bare `CONTEXT.md` reference: dangling in every project. Deleting the clause: loses the naming-consistency requirement it encodes |
| D6 | Keep parallel exploration as prose with no literal `Agent(` call, and state in words that those briefs are judgment-bearing `issue-owner`-tier work rather than the bounded `explorer` tier | The matrix validator scans only files registered as dispatch-site paths, so an unregistered `Agent(` line is a silent hole rather than a caught error; issue 43 owns dispatch registration for the consuming workflow | Registering a dispatch site here: claims a site this issue does not own and forces model-matrix and manifest churn for a module that dispatches nothing itself |
| D7 | Qualify `DESIGN-IT-TWICE.md`'s two user-facing checkpoints for autonomous runs: the recommendation is the answer, and the comparison outcome becomes a ledger row | `design`'s autonomous mode; `from-issue --auto` is a first-class caller in this system | Leaving "show this to the user" unqualified: under an autonomous run those checkpoints are a stall with nobody to answer them |
| D8 | Keep the module pure vocabulary — it names no caller, no consumer and no downstream workflow | The-bar single responsibility and DRY; parent design D1 makes downstream skills invoke the vocabulary rather than the reverse | A "used by" section: couples the shared module to its consumers and needs editing every time a consumer is added |
| D9 | Extend `test_workflow_skill_contracts.py` with a **second `TestCase` class** carrying its own fixture setup; no new test file and no `justfile` change | Parent design D6 says extend the existing Python contract suite; that file is already the shared home for authored-markdown contracts across seven-plus skills; a separate class keeps the missing-package failure contained instead of erroring the suite's existing tests, which is what makes the starting-commit evidence clean | A dedicated test file: buys only merge-conflict avoidance against the concurrent sibling issue and costs a `justfile` recipe edit. Interleaving methods into the existing class: widens that class's concern and maximises conflict surface |
| D10 | Define "skill-package validation" concretely as the structural assertions in the new class — frontmatter `name` equals the directory name, description non-empty, `SKILL.md` present, and every relative link inside the package resolves — with the deployment seam supplying the loadability half | No external skill validator is wired into any `just` recipe in this repository, so the phrase has no other referent here; the link-resolution assertion is what makes D5 permanent | Claiming conformance to an external validator this repository does not run: unverifiable, and the-bar requires verification before claiming done |
| D11 | Verify only at the deployment seam and the contract seam; no `evals/` directory and no lower-level tests | Parent design D6, which bars lower-level seams and method-call assertions; the eval harness grades workflows, and this module has none | An eval case: nothing observable to grade for a module whose entire output is vocabulary another skill consumes |
| D12 | Document the vendoring convention once and generically in the agent-skills README: a skill directory may be a vendored adaptation, its `LICENSE` is the provenance record, and refreshes are manual | The-bar DRY — one authoritative home for the convention; parent design D1's "no automatic upstream synchronisation"; generic wording means the sibling vendored skill needs no second note | Leaving it undocumented: the next maintainer cannot distinguish an authored skill from an adaptation. Documenting per-skill: duplicates the policy once per vendored package |
| D13 | Record decisions that `grill-with-docs` would normally land as glossary entries or ADRs as rows in this ledger instead | This repository has no `docs/` tree and creating one is out of scope; the vendored `SKILL.md` is itself a better home for the vocabulary than a glossary entry would be | Creating a `docs/` tree to hold them: out of scope, and it would fabricate a documentation surface this repository has deliberately never had |
| D14 | Audit all eight canonical terms against existing repository language and reconcile only **seam**; keep upstream's frontmatter description verbatim | "Module" in this repository usually means a Nix module and "interface" is already used in the design sense — upstream's definitions are scale-agnostic and subsume both, so neither contradicts; only "test seam" needed a bridge (D4) | Adding a reconciling note per term: pays token economy for six non-collisions. Retuning the description to avoid matching Nix-module prompts: degrades the trigger for the use the skill exists for, and diverges from upstream against D1 |
