# Task 1: Geist Serif package and all-hosts registration

This task covers the spec's § Decisions › The package and › Registration, and rests on D1 through D6. When it is done, all three hosts list `geist-serif-1.9.0` in `config.fonts.packages`. On the two Macs, FiraCode's two entries stay listed before it, and both darwin system closures carry `GeistSerif-Heart.ttf`. The plan root's Global Constraints apply, with `<scratch>` being the root that `launch-scope scratch` prints.

**Files:**
- Create: `lib/geist-serif.nix`
- Modify: `hosts/common/common-packages.nix`
- Test: no test file. The seams are `nix eval` and `nix build` (plan root § Test seams).

**Interfaces:**
- Consumes: the `pkgs` module argument that `hosts/common/common-packages.nix` already takes.
- Produces: `lib/geist-serif.nix`, a function `{ pkgs }:` that returns a derivation with `pname = "geist-serif"`, `version = "1.9.0"` and name `geist-serif-1.9.0`. Its output is exactly `share/fonts/truetype/GeistSerif-{Regular,Square,Triangle,Heart}.ttf`. Its `src` is a `fetchurl` with `outputHashMode` `flat` and `outputHash` `sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=`.

**Invariants:**
- The four TTFs are named in the install command, never globbed. A missing or renamed upstream member fails the build: `unzip` exits 11 (D3).
- Nothing else is installed: no variable font, webfont, other family or `OFL.txt` (D3).
- The package is bound with a relative `import`. There is no overlay, `callPackage` or flake output (D1).
- `hosts/common/darwin-common.nix` is unchanged, and so is FiraCode in `environment.systemPackages`. `anis-desktop` gets no FiraCode in `fonts.packages` (D2, D4).

- [ ] **Step 1: Watch the measurements fail at base**

Run (timeout 600 s each), from the worktree root:

```bash
nix eval --json .#nixosConfigurations.anis-desktop.config.fonts.packages --apply 'map (p: p.name)'
nix eval --raw .#darwinConfigurations.mbp.config.fonts.packages --apply 'ps: let g = builtins.head (builtins.filter (p: (p.pname or "") == "geist-serif") ps); in "${g.version} ${g.src.outputHashMode} ${g.src.outputHash}"'
```

Expected: the first prints `[]`. The second exits 1 with `error: 'builtins.head' called on an empty list`.

- [ ] **Step 2: Write the package**

Create `lib/geist-serif.nix` with exactly this content. It is the text the planning trial built. `mkdir` must come first, because `unzip -d` does not create the parent directories.

```nix
# Geist Serif from upstream geist-font. The pinned nixpkgs `geist-font` predates
# Serif. Only the four static TTFs are installed, each named, so a missing or
# renamed upstream variant fails the build (issue 486 D3).
{ pkgs }:
pkgs.stdenvNoCC.mkDerivation rec {
  pname = "geist-serif";
  version = "1.9.0";

  # A bump edits `version` and `hash` together.
  src = pkgs.fetchurl {
    url = "https://github.com/vercel/geist-font/releases/download/v${version}/geist-font-v${version}.zip";
    hash = "sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=";
  };

  nativeBuildInputs = [ pkgs.unzip ];

  dontUnpack = true;

  installPhase = ''
    runHook preInstall
    mkdir -p "$out/share/fonts/truetype"
    unzip -j "$src" \
      geist-font/GeistSerif/ttf/GeistSerif-Regular.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Square.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Triangle.ttf \
      geist-font/GeistSerif/ttf/GeistSerif-Heart.ttf \
      -d "$out/share/fonts/truetype"
    runHook postInstall
  '';

  meta = {
    description = "Geist Serif typeface by Vercel, static Regular, Square, Triangle and Heart variants";
    homepage = "https://vercel.com/font";
    license = pkgs.lib.licenses.ofl;
    platforms = pkgs.lib.platforms.all;
  };
}
```

- [ ] **Step 3: Register it on every host**

In `hosts/common/common-packages.nix`, put these lines right after `nixpkgs.config.allowUnfree = true;`, with a blank line before them:

```nix
  # Geist Serif on every host. On darwin this list merges with darwin-common.nix's
  # FiraCode entries (issue 486 D2).
  fonts.packages = [ (import ../../lib/geist-serif.nix { inherit pkgs; }) ];
```

Change nothing else in the file. `git add lib/geist-serif.nix` before any flake eval, because the flake reads only files that git tracks.

- [ ] **Step 4: Verify the evaluation (AC2, AC3)**

Run Step 1's two commands again, plus the same element eval against `.#nixosConfigurations.anis-desktop.config.fonts.packages`, and this:

```bash
for h in mbp eleven-m5; do nix eval --json .#darwinConfigurations.$h.config.fonts.packages --apply 'map (p: p.name)'; done
```

Expected:
- anis-desktop: `["geist-serif-1.9.0"]`.
- Both element evals: `1.9.0 flat sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=`.
- Each darwin host: `["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2","geist-serif-1.9.0"]`.

Any other output means the task is incomplete.

- [ ] **Step 5: Verify the closures (AC1, AC3)**

Run the plan root's Build run (timeout 3600 s), which must exit 0. Then, for each `h` in `mbp` and `eleven-m5` (timeout 3600 s each):

```bash
nix build .#darwinConfigurations.$h.system -o <scratch>/r-$h
nix-store -qR <scratch>/r-$h | xargs -I{} find {} -name GeistSerif-Heart.ttf
```

Expected, for each host, at least one path. The trial printed the package's own `share/fonts/truetype/GeistSerif-Heart.ttf` and a `…-fonts/Library/Fonts/Nix Fonts/…-geist-serif-1.9.0/share/fonts/truetype/GeistSerif-Heart.ttf`. Empty output for either host means the task is incomplete. Keep the out-links out of the worktree.

Then the scope gate:

```bash
git diff --quiet 07f89813 -- hosts/common/darwin-common.nix hosts/common/linux-common.nix flake.nix lib/helpers.nix || exit 1
```

- [ ] **Step 6: Record the evidence baselines (AC4, AC5; D6)**

Do not run `just switch` or anything with `sudo`. Run (timeout 600 s):

```bash
system_profiler SPFontsDataType > <scratch>/fonts.txt
grep -c "Geist Serif Heart" <scratch>/fonts.txt
grep -c "FiraCode Nerd Font" <scratch>/fonts.txt
```

`grep -c` exits 1 on a zero count, so read the printed number, not the exit status. Planning saw `0` and `54`. Report, for acceptance-record rows `AC4` and `AC5`:
- `Check or command`: that row's `system_profiler … | grep -c` command.
- `Observed`: `pending: owner's just switch on mbp after merge`.
- `Commit`: your task head.
- `Conditions`: `host mbp, before activation; base count <n>`.

If the Heart count is already ≥ 1, or the FiraCode count is 0, report it as a blocker. The probe would then not discriminate.

- [ ] **Step 7: Commit**

```bash
git add lib/geist-serif.nix hosts/common/common-packages.nix
launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- -m "feat(fonts): install Geist Serif on every host (issue 486)" -m "<the session's trailer lines>"
```
