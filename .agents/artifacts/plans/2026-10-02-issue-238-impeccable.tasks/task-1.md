# Task 1: Pinned Impeccable tree, engine and wrapper linked to both agents

**Files:**
- Modify: `flake.nix` (add the `impeccable` input beside `codex-plugin-cc`)
- Modify: `flake.lock` (via `nix flake lock` only)
- Create: `lib/impeccable.nix`
- Modify: `home/common/agent-skills/default.nix`
- Create: `tests/test_impeccable_installed.py`
- Modify: `justfile` (`agent-installed-skill-tests` suite list)

**Interfaces:**
- Consumes: nothing from other tasks. `ui-ux-pro-max` stays wired; Task 2 removes it.
- Produces: `import ../../../lib/impeccable.nix { inherit inputs lib pkgs; }` → `{ skill; launcher; engineVersion; }`. `skill` is the derived tree's store path, `launcher` an executable store file, `engineVersion` the string `"0.1.11"`. The installed paths are `.agents/skills/impeccable` (whole-dir link), `.claude/skills/impeccable` (recursive) and `.agents/bin/impeccable`. The test module `tests/test_impeccable_installed.py` holds the class `ImpeccableInstalledTest`, which Task 2 extends.

**Invariants:**
- Every file from upstream `.claude/skills/impeccable` is byte-identical in `skill`. The only addition is `scripts/bin/<slot>/impeccable`, mode 0755 (per D3).
- Evaluation throws on an unmapped system, naming that system. It also throws when `engine.version` ≠ the trimmed `scripts/VERSION`, naming both values (per D2).
- The engine is fetched as a flat file. Do **not** pass `executable = true` to `fetchurl`: that switches to a recursive NAR hash, and the sidecar hashes would then no longer match.
- The wrapper only `exec`s the store launcher by its store path. Never symlink the launcher, because it derives its skill dir from `dirname "$0"` (per D4).
- `home.sessionVariables.IMPECCABLE_NO_UPDATE_CHECK = "1"` (per D5).
- `impeccable` is **not** added to the `migrateCodexSkillLinks` loop. No earlier layout ever left a directory at that path.

- [ ] **Step 1: Write the failing test.** Create `tests/test_impeccable_installed.py`:

```python
"""Installed-layout seam for the Impeccable skill (#238 D3, D4, D7, D9).

Run: just agent-installed-skill-tests. That recipe builds first and passes the
built home-manager-files tree as AGENT_SKILLS_INSTALLED_HOME. Codex gets the
derived tree as one directory link, Claude as a recursive copy of links, and
both launchers must answer `engine-probe` from the tree's own sibling engine
without touching ~/.impeccable/bin.
"""

import os
import platform
import subprocess
import tempfile
import unittest
from pathlib import Path

INSTALLED_HOME_ENV = "AGENT_SKILLS_INSTALLED_HOME"
INSTALLED_RECIPE = "just agent-installed-skill-tests"
SKILL = "impeccable"
OPT_IN_SKILLS = ("sdd", "from-issue")
SKILL_ROOTS = (".agents/skills", ".claude/skills")
SLOTS = {("Darwin", "arm64"): "darwin-arm64", ("Linux", "x86_64"): "linux-x64"}
TIMEOUT_SECONDS = 60


class ImpeccableInstalledTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = os.environ.get(INSTALLED_HOME_ENV)
        if root is None:
            raise unittest.SkipTest(
                f"{INSTALLED_HOME_ENV} is unset; run `{INSTALLED_RECIPE}` to "
                "check the Impeccable skill the Nix build installs"
            )
        cls.root = Path(root)

    def setUp(self):
        self.assertTrue(
            self.root.is_absolute() and self.root.is_dir(),
            f"{INSTALLED_HOME_ENV}={str(self.root)!r} is not an absolute directory",
        )
        self.codex = self.root / ".agents/skills" / SKILL
        self.claude = self.root / ".claude/skills" / SKILL

    def slot(self):
        key = (platform.system(), platform.machine())
        if key not in SLOTS:
            self.fail(f"no pinned Impeccable engine slot for {key}")
        return SLOTS[key]

    def version(self):
        return (self.codex / "scripts/VERSION").read_text(encoding="utf-8").strip()

    def probe(self, executable):
        """Run `<executable> engine-probe` isolated from any ~/.impeccable."""
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        home = Path(scratch.name)
        env = {k: v for k, v in os.environ.items() if not k.startswith("IMPECCABLE_")}
        env.update(HOME=str(home), IMPECCABLE_NO_UPDATE_CHECK="1", DO_NOT_TRACK="1")
        result = subprocess.run(
            [str(executable), "engine-probe"], env=env, capture_output=True,
            text=True, timeout=TIMEOUT_SECONDS, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(
            (home / ".impeccable/bin").exists(),
            f"{executable} installed an engine instead of using the sibling slot",
        )
        return result.stdout.strip()

    def test_codex_view_is_a_whole_directory_link(self):
        self.assertTrue(self.codex.is_symlink(), f"{self.codex} is not a link")
        self.assertTrue(self.codex.is_dir())
        skill_md = self.codex / "SKILL.md"
        self.assertTrue(skill_md.is_file() and not skill_md.is_symlink())

    def test_claude_view_has_skill_md(self):
        self.assertTrue((self.claude / "SKILL.md").is_file())

    def test_sibling_engine_answers_tree_version(self):
        engine = self.codex / "scripts/bin" / self.slot() / SKILL
        self.assertTrue(os.access(engine, os.X_OK), f"{engine} is not executable")
        self.assertEqual(self.probe(engine), f"impeccable-engine {self.version()}")

    def test_launchers_answer_tree_version(self):
        expected = f"impeccable-engine {self.version()}"
        for launcher in (
            self.root / ".agents/bin" / SKILL,
            self.claude / "scripts" / SKILL,
        ):
            with self.subTest(launcher=str(launcher)):
                self.assertEqual(self.probe(launcher), expected)

    def test_workflow_skills_do_not_name_impeccable(self):
        for skills_dir in SKILL_ROOTS:
            for name in OPT_IN_SKILLS:
                tree = self.root / skills_dir / name
                with self.subTest(tree=str(tree)):
                    self.assertTrue((tree / "SKILL.md").is_file(), f"{tree} missing")
                    for dirpath, _, files in os.walk(tree, followlinks=True):
                        for file_name in files:
                            path = Path(dirpath) / file_name
                            self.assertNotIn(
                                b"impeccable", path.read_bytes().lower(), str(path)
                            )


if __name__ == "__main__":
    unittest.main()
```

Add `tests/test_impeccable_installed.py` to the end of the `agent-installed-skill-tests` suite list in `justfile`, after `tests/test_promotion_installed.py`. Keep the backslash continuation on the line before it.

- [ ] **Step 2: Run it and watch it fail.**
Run: `just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR|OK|FAILED)|Ran " | tail -8`
Expected: FAILED. `test_codex_view_is_a_whole_directory_link`, `test_claude_view_has_skill_md`, `test_sibling_engine_answers_tree_version` and `test_launchers_answer_tree_version` fail or error, because nothing is installed at `.agents/skills/impeccable`. `test_workflow_skills_do_not_name_impeccable` passes.

- [ ] **Step 3: Add the input and lock it.** In `flake.nix`, directly after the `codex-plugin-cc` block:

```nix
    # Impeccable design skill. Pinned to an immutable skill tag so `just update`
    # cannot move it away from the engine record in lib/impeccable.nix (#238 D1).
    impeccable = {
      url = "github:pbakaus/impeccable/skill-v4.5.0";
      flake = false;
    };
```

Run `nix flake lock`, never `just update`.

- [ ] **Step 4: Write `lib/impeccable.nix`.** The full code is given because the assert, the slot map and the flat hash are decisions (D2, D3, D4):

```nix
{
  inputs,
  lib,
  pkgs,
}:
let
  # One engine record per pinned skill tag (#238 D1, D2). A bump edits the
  # `impeccable` input's tag, this version and both hashes in one commit. The
  # hashes are the release's `.sha256` sidecars converted to SRI.
  engine = {
    version = "0.1.11";
    hashes = {
      aarch64-darwin = "sha256-dCeRjW51UHQBobe2ke7+WKfAGi/GO3EgFv/FoKwcBeY=";
      x86_64-linux = "sha256-AiFgfh9TWvk36iZ8NHsfkCM7hdwlY8vS7u/fQuDlxZQ=";
    };
  };
  # Nix system -> the launcher's `<os>-<arch>` slot, which is also the asset suffix.
  slots = {
    aarch64-darwin = "darwin-arm64";
    x86_64-linux = "linux-x64";
  };

  system = pkgs.stdenv.hostPlatform.system;
  slot =
    slots.${system} or (throw "impeccable: no pinned engine for system ${system} (supported: ${lib.concatStringsSep ", " (builtins.attrNames slots)})");

  upstreamTree = "${inputs.impeccable}/.claude/skills/impeccable";
  treeVersion = lib.trim (builtins.readFile "${upstreamTree}/scripts/VERSION");

  # Flat fetch: `executable = true` would hash the NAR, not the sidecar's file hash.
  engineBinary = pkgs.fetchurl {
    url = "https://github.com/pbakaus/impeccable/releases/download/engine-v${engine.version}/impeccable-${slot}";
    hash = engine.hashes.${system};
  };

  # Upstream's tree unchanged, plus the engine in the launcher's sibling slot,
  # which it tries before any cache or download path (#238 D3).
  skill =
    assert lib.assertMsg (treeVersion == engine.version)
      "impeccable: engine record ${engine.version} does not match the pinned skill's scripts/VERSION ${treeVersion}";
    pkgs.runCommand "impeccable-skill-engine-${engine.version}" { } ''
      mkdir -p "$out"
      cp -R ${upstreamTree}/. "$out/"
      chmod -R u+w "$out"
      install -Dm755 ${engineBinary} "$out/scripts/bin/${slot}/impeccable"
    '';

  # Exec by store path: the launcher resolves its skill dir from `dirname "$0"` (#238 D4).
  launcher = pkgs.writeShellScript "impeccable" ''
    exec ${skill}/scripts/impeccable "$@"
  '';
in
{
  inherit skill launcher;
  engineVersion = engine.version;
}
```

- [ ] **Step 5: Link it.** In `home/common/agent-skills/default.nix`:
  - Add `impeccable = import ../../../lib/impeccable.nix { inherit inputs lib pkgs; };` to the `let` block.
  - Add `".agents/skills/impeccable".source = impeccable.skill;` next to the `ui-ux-pro-max` entry.
  - Add `".agents/bin/impeccable".source = impeccable.launcher;`.
  - Add `".claude/skills/impeccable" = { source = impeccable.skill; recursive = true; };` next to the Claude `ui-ux-pro-max` entry.
  - Add `home.sessionVariables.IMPECCABLE_NO_UPDATE_CHECK = "1";`, with a one-line comment: Nix owns the version, and the store is read-only (D5).

- [ ] **Step 6: Verify.**
  - `just agent-installed-skill-tests 2>&1 | grep -E "^(FAIL|ERROR|OK|FAILED)|Ran " | tail -4`. Expected: `OK`, with all five `ImpeccableInstalledTest` tests passing.
  - `nix eval --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'`. Expected: one `/nix/store/…drv` path.
  - Linux hash check: `nix store prefetch-file --json https://github.com/pbakaus/impeccable/releases/download/engine-v0.1.11/impeccable-linux-x64 | jq -r .hash`. Expected: `sha256-AiFgfh9TWvk36iZ8NHsfkCM7hdwlY8vS7u/fQuDlxZQ=`.
  - Lock scope: `diff <(git show HEAD:flake.lock | jq -S 'del(.nodes.root.inputs.impeccable)') <(jq -S 'del(.nodes.impeccable, .nodes.root.inputs.impeccable)' flake.lock)`. Expected: no output. Also `jq -r .nodes.impeccable.original.ref flake.lock`, expected `skill-v4.5.0`.

- [ ] **Step 7: Commit.**

```bash
git add flake.nix flake.lock lib/impeccable.nix home/common/agent-skills/default.nix tests/test_impeccable_installed.py justfile
git commit -m "feat(skills): install pinned Impeccable skill and engine for both agents (#238)"
```

- [ ] **Step 8: Prove the mismatch guard can fail (D2).** Run `sed -i.bak 's/version = "0.1.11";/version = "0.0.0";/' lib/impeccable.nix && nix eval --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath' 2>&1 | grep -c 'engine record 0.0.0 does not match the pinned skill.s scripts/VERSION 0.1.11'; mv lib/impeccable.nix.bak lib/impeccable.nix`. Expected: `1`. Afterwards `git status --porcelain -- lib/impeccable.nix` must print nothing.
