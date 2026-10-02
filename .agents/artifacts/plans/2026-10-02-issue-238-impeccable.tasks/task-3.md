# Task 3: Architecture prose

**Files:**
- Modify: `CLAUDE.md` (the "Global guidance has one source…" bullet under **Claude Code is declaratively managed**)

**Interfaces:**
- Consumes: the behavior Tasks 1–2 shipped: `lib/impeccable.nix` (`skill`, `launcher`, the engine record, and the VERSION assert), the links and the session variable in `home/common/agent-skills/default.nix`, plus `retiredSkillNames` / `reportRetiredSkills`.
- Produces: nothing that code consumes.

**Invariants:**
- Every sentence below describes code that is live at this task's base commit. Before committing, re-check each claim against `lib/impeccable.nix` and `home/common/agent-skills/default.nix`, and correct the prose, not the code, wherever they differ.
- CLAUDE.md no longer mentions `UI/UX Pro Max` or `ui-ux-pro-max` (per spec Docs).

- [ ] **Step 1: Confirm the gate fails at base.**
Run `grep -c 'UI/UX Pro Max' CLAUDE.md`. Expected: `1`.

- [ ] **Step 2: Replace the sentence.** In that bullet, replace exactly `UI/UX Pro Max is generated once in \`home/common/agent-skills/default.nix\` and handed to both agents.` with:

> Impeccable (`pbakaus/impeccable`) is pinned by the `impeccable` flake input to an immutable `skill-v<version>` tag. `lib/impeccable.nix` builds it once into one derived skill tree. The tree is upstream's `.claude/skills/impeccable` unchanged, plus the host system's pinned prebuilt design-detector engine in the launcher's sibling slot `scripts/bin/<os>-<arch>/impeccable`. Both agents get that tree: Codex through the whole-directory link `~/.agents/skills/impeccable`, and Claude through a recursive `~/.claude/skills/impeccable`. `~/.agents/bin/impeccable` puts the detector on PATH by exec'ing the tree's own launcher. Detector availability is that pinned engine. It is never downloaded on demand, and nothing is installed under `~/.impeccable/bin/`, although the engine may still write runtime caches under `~/.impeccable`. The session sets `IMPECCABLE_NO_UPDATE_CHECK=1` because Nix owns the version. For the same reason, the store-writing verbs (`update`, `install`, `link`, `pin`) cannot change the Nix-owned tree. A bump edits the input's tag, the engine version and both hashes in `lib/impeccable.nix` together. Evaluation fails when the engine version and the tree's `scripts/VERSION` disagree, and on any system other than `aarch64-darwin` or `x86_64-linux`. Skills that are no longer installed are listed in `retiredSkillNames` in `home/common/agent-skills/default.nix`. Home Manager's own cleanup removes their old links on switch, and an activation step then warns about any retired skill directory that is still present, without deleting anything.

- [ ] **Step 3: Verify.**
  - `if grep -n -e 'UI/UX Pro Max' -e 'ui-ux-pro-max' CLAUDE.md; then exit 1; fi`. Expected: no output, exit 0.
  - `grep -c '~/.agents/bin/impeccable' CLAUDE.md`. Expected: `1`.
  - Repo scope: `git grep -l -i -e 'ui-ux-pro-max' -e 'UI/UX Pro Max' -- ':!.agents/artifacts' | sort`. Expected: exactly `home/common/agent-skills/default.nix` and `tests/test_impeccable_installed.py`, which hold the retired-name list and the test constant.

- [ ] **Step 4: Commit.**

```bash
git add CLAUDE.md
git commit -m "docs: describe the pinned Impeccable skill and engine in CLAUDE.md (#238)"
```
