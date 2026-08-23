# CLAUDE.md ↔ agent-surface reconciliation (issue 105)

Issue: https://github.com/fagenorn/nix-config/issues/105

## Problem

`CLAUDE.md` is this repo's only context document — there is no `docs/` tree, no
CONTEXT-MAP and no ADR home. Every agent that touches the agent-tooling modules
reads it first and trusts it. Three of its claims about that tooling are now
false or missing, and each one has already produced a wrong action:

1. **`orchestrate-issues` looks like it is missing from Codex.** It is
   deliberately Claude-only — it dispatches background agents and correlates
   host task notifications, neither of which Codex has. The module comment and
   the skill's own `## Notes` both say so, but `CLAUDE.md` never records it, so a
   directly-driven Codex session asked to orchestrate finds nothing to read and
   improvises rather than falling back to per-issue `/from-issue`.

2. **The Superpowers sentence describes a configuration that no longer
   exists.** The plugin, its `nix-superpowers` marketplace, the Codex personal
   marketplace and its patch were all deleted on 2026-08-08. The surviving
   sentence is wrong on four counts at once, and it is the *only* place a reader
   is told how the plugin surface works — so it is believed.

3. **`~/.codex/skills/` holds two unmanaged skill copies** that duplicate skills
   already served as managed links from `~/.agents/skills/`, with drifted
   content. Nothing in the repo explains that this directory exists outside Nix's
   control, so the duplication reads as a bug in the Nix wiring rather than as
   leftover local state.

The common defect is that `CLAUDE.md` has drifted from the modules it describes.
The fix is to make the document true again, not to change any configuration.

## Solution

A prose-only correction to `CLAUDE.md`, plus one comment fix in the module the
same claims describe.

**Split the overloaded bullet.** The bullet beginning "Global guidance has one
source at ..." currently carries five unrelated claims. Split it into two
siblings under the existing **Claude Code is declaratively managed** list:

- a *shared surface* bullet — one guidance source exposed to both agents; shared
  skills from `home/common/agent-skills/skills/`; why Codex gets whole-directory
  links; UI/UX Pro Max generated once for both;
- a *Claude-only surface and plugins* bullet — the two skills held outside the
  shared tree and why each is; what Claude actually installs; what Codex actually
  gets.

**Between them, the two corrected bullets must assert exactly these verified
facts** (per D2):

- `codex-plugin-cc` is the single remaining pinned-input-plus-repo-patch plugin;
  the patch directory holds one patch, not several.
- Claude enables two plugins from marketplaces of *different* source types:
  `skill-creator@claude-plugins-official` from a **github**-source marketplace, and
  `codex@nix-codex` from a **directory**-source marketplace pointed at the store path
  `lib/agent-plugins.nix` builds. The replaced sentence's "local marketplaces" is
  wrong by count and by source type, not because a directory marketplace fails to be
  local — state the two source types rather than a single blanket adjective.
- Codex has **no** Nix-declared marketplace. Its marketplaces are runtime-managed
  by Codex itself; Nix's only writes into `~/.codex` are `AGENTS.md`, the
  `model_reasoning_effort` key spliced into `config.toml`, and nothing else.
- Two skills are deliberately Claude-only: `codex-collaboration` (prevents Codex
  recursively delegating to itself) and `orchestrate-issues` (background agents
  and host task notifications are Claude-harness features Codex lacks). Codex runs
  `/from-issue` per issue instead.
- No mention of Superpowers as a live input, patch, marketplace or plugin. The only
  surviving reference is a present-tense clause explaining that the `.superpowers/`
  paths under `home/common/agent-skills/` are the workflow **state** directory whose
  name is historical — written as a fact about what that directory *is*, never as a
  changelog entry about what was removed and when (per D6).

**Document `~/.codex/skills/` as unowned state.** This belongs in the *shared
surface* bullet, immediately after the sentence explaining the `~/.agents/skills/`
whole-directory links — it is a statement about how skills reach Codex, not about
plugins. It says that `~/.codex/skills/` is Codex-owned runtime state which Nix
neither populates nor prunes, so a copy placed there duplicates the managed
`~/.agents/skills/` link of the same name and must be removed by hand.

The wording must stay hedged on *precedence* (per D10): which of the two discovery
roots wins on a name collision is not verified, and the correction must not assert
that the local copy shadows the managed one. "Duplicates" is supportable;
"overrides" is not.

**Drop the stale count in the module.** The comment above `skillsDir` in
`home/common/claude-code/default.nix` says "the 8 global skills"; the directory
holds 16. Delete the number rather than correct it (per D5).

**Item 3 cleanup is the owner's, not the pipeline's** (per D3). The execute phase
performs no deletion under `~/.codex/`. It records the one-time command in the
commit body, following the `8a4baae` precedent verbatim in form:

```
Post-switch cleanup (one-time, manual): rm -rf ~/.codex/skills/codebase-design \
  ~/.codex/skills/improve-codebase-architecture — unmanaged copies that duplicate
  the ~/.agents/skills links; leave ~/.codex/skills/.system alone.
```

Issue 105 accepts item 3 as "removed **or** explained", so the documented
explanation satisfies it on its own. The manual command is offered to the owner, not
a gate: the ship phase must not wait on it, and the issue is closable without it.
Worth flagging in the handoff, though — the stale `codebase-design` copy predates the
**test seam** definition that the design, planning and sdd skills all lean on, so a
Codex session reading that copy is working from a smaller vocabulary than the shared
tree defines.

## Decisions

**Nothing in the live configuration changes.** No skill changes which agent it is
exposed to, no flake input moves, no marketplace is added or removed, no
activation script is added. The only files that change are `CLAUDE.md` (prose) and
one comment line in `home/common/claude-code/default.nix`.

**Why the Claude-only status is documented rather than resolved by exposure.**
Exposing `orchestrate-issues` through `home/common/agent-skills/skills/` would put
a skill on Codex's surface whose central instruction — dispatch background agents,
then correlate host task handles for notification — Codex cannot execute. That
turns a clean "no such skill, fall back to `/from-issue`" into a skill that reads
as available and then fails partway. The decision to keep it Claude-only is
already made and justified in two places; the defect is purely that the context
document does not record it.

**Why no declarative prune of `~/.codex/skills/`.** The repo has a consistent,
stated posture toward mutable state it did not create: `migrateCodexSkillLinks`
deletes a legacy directory only when *every* leaf is provably a Home Manager store
link and otherwise refuses with an explicit error; the `palmier-pro` and Codex
config activations each rewrite exactly one key and disclaim ownership of the rest.
Applying that same ownership test to the two live copies **fails**: of their five
files, only one matches any blob in this repo's history — the other four match
none. Under the repo's own rule these are not ours to delete. A warn-only
activation check was also considered and rejected: it is standing machinery for a
one-time, already-diagnosed condition, and it would have to encode a policy the
repo has no basis to assert, namely that a Codex-local skill sharing a name with a
shared one is always wrong.

## Test seams

There is no automated seam for this change and none should be built — no test in
the repo asserts `CLAUDE.md` prose today, and a test that pins documentation
wording would fail for every legitimate edit. Verification is by assertion against
the live configuration:

- `home/common/claude-code/default.nix` is a `.nix` file, so the execute phase runs
  `just build` even though its edit is comment-only — the repo rule is
  unconditional and is not worth special-casing (per D7).
- Every plugin name and marketplace source stated in the corrected prose is checked
  against the `enabledPlugins` and `extraKnownMarketplaces` attrsets in that same
  module, and against live `~/.codex/config.toml`.
- `git grep -in superpower` must return only `.superpowers/` state paths under
  `home/common/agent-skills/` and the corrected `CLAUDE.md` clause — no claim of a
  Superpowers plugin, input, patch or marketplace anywhere.
- `CLAUDE.md` names `orchestrate-issues` and `codex-collaboration` as the Claude-only
  pair, matching the two `home.file.".claude/skills/<name>"` entries in the module.
- The skill count stated anywhere in prose or comments must be absent, not merely
  current (per D5).

## Out of scope

- Re-adding Superpowers in any form — input, patch, marketplace or plugin.
- Changing which agent any skill is exposed to, including `orchestrate-issues`.
- `patches/agent-plugins/codex-plugin-cc.patch`, `lib/agent-plugins.nix`, and any
  flake input or `flake.lock` change.
- Any activation script, including a prune or a warning, that reaches into
  `~/.codex/skills/`.
- Deleting anything under `~/.codex/` during the pipeline; that stays the owner's
  one-time manual step.
- Creating a `docs/` tree, CONTEXT-MAP, ADR home or `docs/standards/` — this repo
  deliberately has none, and `CLAUDE.md` remains the single context document.
- Rewriting or restructuring `CLAUDE.md` beyond the bullets named above.
- `just switch`.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Item 1: record `orchestrate-issues`' Claude-only status in `CLAUDE.md`; do not expose it to Codex | Issue 105 accepts either; the module comment and the skill's `## Notes` already justify Claude-only, and the skill's core step dispatches background agents + host task notifications Codex lacks | Move it to `home/common/agent-skills/skills/` — ships a skill Codex reads but cannot execute, replacing a clean fallback with a partial failure |
| D2 | Item 2: rewrite the stale clause to state the real install surface — one patched plugin (`codex-plugin-cc`), Claude enabling `skill-creator@claude-plugins-official` (github source) and `codex@nix-codex` (directory source), and Codex having no Nix-declared marketplace | Verified against `enabledPlugins`/`extraKnownMarketplaces`, `lib/agent-plugins.nix` (only `nix-codex` is built), and live `~/.codex/config.toml` (only Codex-runtime marketplaces) | Word-swap the sentence — its subject ("both" = Superpowers + `codex-plugin-cc`) no longer exists, so there is no word to swap. Note the precise defect: "local marketplaces" is wrong by count and source type (one github, one directory), *not* because a directory marketplace fails to be local — an earlier draft of this row overstated that and was corrected in the grill |
| D3 | Item 3: explain `~/.codex/skills/` as unowned Codex state and hand the owner a one-time manual removal; no Nix prune, and the pipeline itself deletes nothing under `~/.codex/`. The explanation alone satisfies the issue's "removed **or** explained" acceptance, so the removal never gates the ship phase | `migrateCodexSkillLinks` refuses to remove anything not provably a HM store link, and that ownership test **fails here** — 4 of the 5 live files match no blob in repo history; `8a4baae` set the "post-switch cleanup, one-time, manual" precedent for exactly this class of leftover | Declarative prune (contradicts the repo's stated never-own-foreign-state posture and would delete content failing its own ownership test); warn-only activation check (standing machinery for a one-time condition, and encodes a name-collision policy the repo cannot justify) |
| D4 | Split the overloaded "Global guidance..." bullet into a shared-surface bullet and a Claude-only-surface-and-plugins bullet, keeping both under the existing section | `the-bar` single responsibility — the bullet already carries five unrelated claims and this change adds two more | Fold the corrections into the existing bullet (compounds the readability defect that let the stale clause hide); promote to a new top-level section (structural change out of proportion to a doc correction) |
| D5 | Delete the skill count from the `skillsDir` comment rather than updating 8→16 | `the-bar` DRY — the directory is the one authoritative home for its own size; a restated count is a second home that drifted once and would drift again. Same defect class as D1/D2, in the file this change already touches | Update the number to 16 (fixes today's value, preserves the drift mechanism); leave it stale (knowingly ships a false statement in the file under repair) |
| D6 | State in the correction, in the present tense, that the `.superpowers/` paths are the workflow state directory whose name is historical — a fact about what the directory is, not a changelog note about a removal | `git grep -in superpower` returns ~28 hits, all state paths in `home/common/agent-skills/`; a reader trusting the corrected "Superpowers is gone" would otherwise grep-purge live state | Say nothing (the correction itself creates the hazard, so it carries the guard); write it as removal history (a context document states what is, not what changed — that is the commit log's job); document the state directory fully (scope creep — one clause prevents the wrong edit) |
| D7 | Execute phase runs `just build`, because a `.nix` file is touched, and verifies the prose by asserting each claim against the live modules; no test pins documentation wording | Repo rule "after editing any `.nix`, run `just build`" is unconditional; no existing test references `CLAUDE.md` and a wording-pinning test would fail on every legitimate edit | Skip the build because the `.nix` edit is comment-only (special-cases an unconditional rule for no gain); add a contract test asserting the skill count or plugin names (re-creates the second authoritative home D5 removes) |
| D8 | The grill phase refines this spec only; the `CLAUDE.md` product edit is deferred to the execute phase | This issue's product *is* a `CLAUDE.md` correction, so a grill that "updated the context doc" would silently ship the deliverable and leave the spec describing completed work, breaking the plan and review phases downstream | Let the grill apply the correction as a normal context-doc update (destroys the phase boundary and the reviewable diff) |
| D9 | The grill creates no ADR, glossary or context-doc tree, and applies no part of the `CLAUDE.md` correction | The repo has no `docs/`, no map, no ADR home and no legacy glossary convention, and creating one is already out of scope; the ledger rows here fail the ADR three-test on reversibility — a prose correction costs nothing to revise | Open an ADR home for D1/D3 (imposes the standard tree on a repo that deliberately has none, for decisions that are cheap to reverse) |
| D10 | The correction states that a copy under `~/.codex/skills/` *duplicates* the managed `~/.agents/skills/` link, and stops there — it must not claim which root wins a name collision | Codex's discovery precedence between the two roots was not verified; the repo's own claim that skills reach Codex via `~/.agents/skills` rests on a module comment, and the correction should not add unverified mechanism on top of it | Assert that the local copy shadows or overrides the managed one (plausible, unverified, and exactly the kind of confident-but-unchecked claim this whole issue exists to remove) |
