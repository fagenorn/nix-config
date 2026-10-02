# Task 2: Retire ui-ux-pro-max with a warn-only report

**Files:**
- Modify: `flake.nix` (delete the `ui-ux-pro-max` input)
- Modify: `flake.lock` (via `nix flake lock` only)
- Modify: `home/common/agent-skills/default.nix`
- Modify: `tests/test_impeccable_installed.py`

**Interfaces:**
- Consumes: Task 1's `ImpeccableInstalledTest` class and its `SKILL_ROOTS = (".agents/skills", ".claude/skills")` constant in `tests/test_impeccable_installed.py`, plus the Impeccable links in `default.nix`.
- Produces: a `retiredSkillNames` list (`[ "ui-ux-pro-max" ]`) in the `let` block of `home/common/agent-skills/default.nix`, and the activation entry `home.activation.reportRetiredSkills`.

**Invariants:**
- Removing the old links is left to Home Manager's own `cleanOldGen`, which runs inside `linkGeneration`. Nothing new in this task deletes, moves or `chmod`s anything (per D6).
- `reportRetiredSkills` runs `entryAfter [ "linkGeneration" ]`. For each root in `~/.agents/skills` and `~/.claude/skills`, and each retired name, it acts only when the path exists or is a dangling link. Every exit path returns 0, so activation never fails. HM activation runs under `set -eu -o pipefail`, so every command that may fail is guarded.
- The warning names the first entry that is neither a real directory nor a link into `/nix/store/*-home-manager-files/`. `find` runs without `-L`, so a top-level link is classified by its own target.
- `migrateCodexSkillLinks` iterates `localSkillNames` only. Its body is otherwise unchanged.
- No `ui-ux-pro-max` / `uiUxSkill` reference remains in `flake.nix` or `default.nix`, other than the `retiredSkillNames` entry.

- [ ] **Step 1: Write the failing test.** In `tests/test_impeccable_installed.py`, add a module constant after `OPT_IN_SKILLS`, then add this method to `ImpeccableInstalledTest`:

```python
RETIRED_SKILLS = ("ui-ux-pro-max",)
```

```python
    def test_retired_skills_are_not_installed(self):
        for skills_dir in SKILL_ROOTS:
            for name in RETIRED_SKILLS:
                path = self.root / skills_dir / name
                with self.subTest(path=str(path)):
                    self.assertFalse(os.path.lexists(path), f"{path} still installed")
```

Also add `D6` to the module docstring's decision list.

- [ ] **Step 2: Run it and watch it fail.**
Run: `just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR)|FAILED|Ran " | tail -6`
Expected: FAILED. `test_retired_skills_are_not_installed` fails for both roots.

- [ ] **Step 3: Retire the source and links.**
  - In `flake.nix`, delete the `ui-ux-pro-max = { … };` block, then run `nix flake lock`.
  - In `home/common/agent-skills/default.nix`:
    - Delete the `uiUxSkill` binding.
    - Delete the `".agents/skills/ui-ux-pro-max"` entry.
    - Delete the `".claude/skills/ui-ux-pro-max"` entry. If the "Claude accepts Home Manager's recursive file links" comment above it no longer describes what sits beneath it, reword it to fit the Impeccable entry.
    - Change the loop to `for skillName in ${lib.escapeShellArgs localSkillNames}; do`.

- [ ] **Step 4: Add the report.** Add this to the `let` block:

```nix
  # Skills this config used to install. Home Manager's own old-generation
  # cleanup removes their links on switch (#238 D6). The step below only
  # reports a retired directory that is still present, because whatever is
  # left in it is not Home Manager's to delete.
  retiredSkillNames = [ "ui-ux-pro-max" ];
```

and this attribute beside `migrateCodexSkillLinks` (full code, because it is fail-safe under `set -eu -o pipefail`):

```nix
  home.activation.reportRetiredSkills = lib.hm.dag.entryAfter [ "linkGeneration" ] ''
    for skillRoot in "$HOME/.agents/skills" "$HOME/.claude/skills"; do
      for skillName in ${lib.escapeShellArgs retiredSkillNames}; do
        target="$skillRoot/$skillName"
        if [ ! -e "$target" ] && [ ! -L "$target" ]; then
          continue
        fi
        foreign=""
        while IFS= read -r -d "" entry; do
          if [ -d "$entry" ] && [ ! -L "$entry" ]; then
            continue
          fi
          if [ -L "$entry" ]; then
            case "$(${pkgs.coreutils}/bin/readlink "$entry" || true)" in
              /nix/store/*-home-manager-files/*) continue ;;
            esac
          fi
          foreign="$entry"
          break
        done < <(${pkgs.findutils}/bin/find "$target" -print0 2>/dev/null || true)
        if [ -n "$foreign" ]; then
          warnEcho "Retired skill $target is still present: $foreign is not a Home Manager link, so it was left in place. Remove it by hand."
        else
          warnEcho "Retired skill $target is still present but holds only empty directories or Home Manager links."
        fi
      done
    done
    unset skillRoot skillName target foreign entry
  '';
```

- [ ] **Step 5: Verify.**
  - `just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR|OK|FAILED)|Ran " | tail -4`. Expected: `OK`.
  - `nix eval --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'`. Expected: one `.drv` path.
  - Lock scope: `diff <(git show HEAD:flake.lock | jq -S 'del(.nodes."ui-ux-pro-max", .nodes.root.inputs."ui-ux-pro-max")') <(jq -S . flake.lock)`. Expected: no output.
  - Built activation order. Run `A=$(nix-store -qR ./result | grep -- '-home-manager-generation$')/activate; grep -n 'linkGeneration\|Retired skill' "$A" | head`. Expected: the first `Retired skill` line comes after the `linkGeneration` lines. The gate fails if `grep -q 'ui-ux-pro-max' <(sed -n '/migrateCodexSkillLink() {/,/unset -f migrateCodexSkillLink/p' "$A")` succeeds; in that case, exit 1.
  - Gate: `if git grep -n -e uiUxSkill -e 'ui-ux-pro-max' -- flake.nix flake.lock home/common/agent-skills/default.nix | grep -v 'retiredSkillNames = \[ "ui-ux-pro-max" \];'; then exit 1; fi`

- [ ] **Step 6: Commit.**

```bash
git add flake.nix flake.lock home/common/agent-skills/default.nix tests/test_impeccable_installed.py
git commit -m "feat(skills): retire ui-ux-pro-max with a warn-only leftover report (#238)"
```
