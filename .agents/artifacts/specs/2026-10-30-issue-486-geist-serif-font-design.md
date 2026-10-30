# Geist Serif (Heart variant) as a system font on all hosts — issue 486

Issue: https://github.com/fagenorn/nix-config/issues/486. This was designed autonomously
(`from-issue --auto`), so every call made without the user is a row in the Decision ledger.

## Triage

Input: `{"signals": {"contract_change": {"value": "no", "evidence": "Adds one local font package and fonts.packages entries; no schema, helper contract or public interface changes"}, "concurrency_or_persistence": {"value": "no", "evidence": "Pure Nix evaluation/build change; no locking or persisted state"}, "open_design_questions": {"value": "no", "evidence": "Issue's Decisions section fixes variant, hosts, packaging route and out-of-scope surfaces; only file placement remains, settled by repo precedent"}, "criteria_shape": {"value": "hit", "evidence": "Five acceptance criteria, two of them [evidence] checks after `just switch` that no deterministic code check verifies"}}, "paths": ["pkgs/geist-serif.nix", "hosts/common/darwin-common.nix", "hosts/common/linux-common.nix"]}`
Verdict: `{"hits":["criteria_shape"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

The triage paths were Phase 0's guess. D1 and D2 settle different files. Neither the
signals nor the verdict depend on those paths, and none of the settled files is an
agent-tooling path, so `nix-build` is the only declared verification command.

## Problem

The owner wants Vercel's Geist Serif, in its Heart variant (hearts for dots), as the
browser *Serif font* in Chrome and Helium. They set that by hand once the font is
installed. Geist Serif first shipped in geist-font v1.9.0. The pinned nixpkgs carries
`geist-font` 1.5.0, which has no Serif, so no host can install it today.

FiraCode is the only Nix-managed system font. On the Macs it is registered through
nix-darwin's `fonts.packages`. On `anis-desktop` no font is registered: its
`fonts.packages` is empty, though fontconfig is enabled.

## Solution

1. **A local package, `geist-serif`, version `1.9.0`.** It fetches the upstream release
   zip as a fixed-output fetch, pinned by the zip's flat SRI hash
   `sha256-Hy3Z6pDmjQNYodI0pfFWgHssPg4pXXjYeYCm260fpYw=` (re-verified with
   `nix store prefetch-file`). It installs exactly four files under `share/fonts/truetype`:
   `GeistSerif-Regular.ttf`, `-Square.ttf`, `-Triangle.ttf` and `-Heart.ttf`, about
   530 KB in total (D3).
2. **One registration for all three hosts.** The shared module that both `mkDarwin` and
   `mkNixos` load adds the package to `fonts.packages` (D2). On the Macs that list merges
   with FiraCode's, and nix-darwin's activation copies every TTF into
   `/Library/Fonts/Nix Fonts`. On `anis-desktop`, NixOS adds the package's font directory
   to fontconfig.

Demo: after `just switch` on mbp, Font Book lists *Geist Serif Heart*.

## Decisions

### The package (per D1, D3)

- **Identity.** `pname = "geist-serif"` and `version = "1.9.0"`, so the derivation name is
  `geist-serif-1.9.0`. The fetch URL is built from `version`. A future bump edits the
  version and the hash together and nothing else.
- **Builder.** `stdenvNoCC`, because fonts need no compiler. `unzip` extracts the four
  named members from `geist-font/GeistSerif/ttf/`. Each is named explicitly, not
  globbed. If upstream drops or renames a variant, the build fails loud and never
  ships three fonts quietly.
- **Not shipped.** The variable font `GeistSerif[ELSH].ttf`, the woff2 webfonts and the
  Geist/GeistMono/GeistPixel families.
- **Metadata.** `meta.license = lib.licenses.ofl`, plus `description` and `homepage`, as in
  nixpkgs' `geist-font`. `platforms` is all, since the font serves darwin and Linux alike.
- **Reach.** The file takes `{ pkgs }`. The registering module binds it with a plain
  relative `import`, as `agent-tools.nix` and `impeccable.nix` are bound today. The
  package gets no overlay, `callPackage` wrapper or flake output.

### Registration (per D2)

- The shared all-hosts module sets `fonts.packages = [ <geist-serif> ]`. Both module systems
  declare `fonts.packages` as a list, so the darwin-only FiraCode definition merges with it
  unchanged.
- FiraCode stays where it is: in darwin's `fonts.packages` and in every host's
  `environment.systemPackages`. Geist Serif goes only into `fonts.packages`, because
  `systemPackages` registers no font with either system.
- `anis-desktop` gets Geist Serif in `fonts.packages` and nothing else. In particular it
  does not get FiraCode there (D4).

### Acceptance mapping

| AC | Measured by | Design element |
|----|-------------|----------------|
| 1 `[code]` mbp and eleven-m5 closures contain `GeistSerif-Heart.ttf` | The issue's `nix build … -o r-<host>` + `nix-store -qR` + `find`, for both hosts, run on mbp (both are aarch64-darwin) | nix-darwin's `system.build.fonts` symlinks each TTF into the system, so the package's store path is in the closure |
| 2 `[code]` anis-desktop registers it | The issue's `nix eval --json …anis-desktop.config.fonts.packages --apply 'map (p: p.name)'` lists `geist-serif-1.9.0`, and CI `Nix Eval` is green on the PR | The shared-module registration |
| 3 `[code]` pinned v1.9.0 by hash | `nix eval` of that list's `geist-serif` element's `.version` prints `1.9.0`. `nix derivation show` of its `src` shows an `outputHash`, so it is a fixed-output fetch. `just build` builds it | Identity, and the fixed-output fetch (D5) |
| 4 `[evidence]` live on the Mac | `system_profiler SPFontsDataType \| grep -c "Geist Serif Heart"` ≥ 1 after `just switch` on mbp | nix-darwin's activation rsync into `/Library/Fonts/Nix Fonts` |
| 5 `[evidence]` FiraCode still installed | `system_profiler SPFontsDataType \| grep -c "FiraCode Nerd Font"` ≥ 1 after the same switch | The FiraCode definition is untouched |

### Grill refinements

- **The only standards that apply are the bar's.** No standards shard and no stack shard
  governs `.nix` paths. The bar's YAGNI rule settles D3 and D5. Its Fail-loud rule settles
  the explicitly named members.
- **No rejection or ADR applies.** The three recorded rejections are about orchestration and
  merge gating, and no context map or ADR set is bound for this repo.
- **AC 4's grep matches only Heart.** `fc-scan` reads Heart's full name as
  `Geist Serif Heart` (PostScript name `GeistSerif-Heart`). The other variants'
  full names are `Geist Serif Regular`, `… Square` and `… Triangle`. So the
  count measures the Heart file and nothing else.
- **The Linux build is never run.** CI `Nix Eval` only evaluates `anis-desktop` and
  never builds it, and mbp cannot build x86_64-linux. The Linux output is therefore
  never built anywhere before the switch on that host. This residual risk is accepted:
  the fixed-output source has the same hash on every platform, and the install step is
  plain `unzip` + `install` under `stdenvNoCC`, which mbp's `just build` exercises.
- **No doc update.** CLAUDE.md lists "Other notable bits" but no font inventory, and FiraCode
  has never had a line there. A single shared font list needs no new convention, so no doc
  changes, in line with the documentation rules in CLAUDE.md.

## Test seams

The repo has no Nix unit-test suite. CLAUDE.md names `just build` as the local
verification, and that stays the seam. These are the seams, all of them existing and
none of them new:

- **Configuration evaluation.** `nix eval` of `config.fonts.packages` (AC 2, AC 3). This is
  the same surface CI `Nix Eval` evaluates for `anis-desktop`.
- **The system closure.** `nix build` of each darwin `system` plus `nix-store -qR` (AC 1).
  This is the darwin build CLAUDE.md leaves to the author.
- **The activated machine.** `system_profiler` after `just switch` (AC 4, AC 5), per D5.

No flake check is added. The `omlx-adapter` check is the precedent for a flake check, but
it exists because its logic runs Python. Here every AC is already visible through these
seams.

## Out of scope

- Ghostty and every other terminal. Geist Serif is a proportional display serif, and
  Ghostty has its own issue.
- VS Code settings, which stay hand-edited.
- Browser font settings. The owner sets them by hand.
- The variable font, the webfonts, and Geist Sans, Mono and Pixel.
- Overriding or bumping nixpkgs' `geist-font`.
- Removing FiraCode, and registering it on `anis-desktop`.
- A `pkgs/` tree, an overlay or a flake `packages` output.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The package lives at `lib/geist-serif.nix` and takes `{ pkgs }`. Its one consumer binds it with a relative `import`. | Repo precedent: every local derivation (`impeccable.nix`, `agent-tools.nix`, `agent-plugins.nix`, `omlx-check.nix`) lives in `lib/` and is imported that way. No `pkgs/` tree or overlay exists. The bar: YAGNI. | A new `pkgs/` tree with `callPackage` or an overlay: a second convention for a single file. A flake `packages` output: no AC needs one (D5). |
| D2 | Register the font once, in `hosts/common/common-packages.nix`. FiraCode's darwin definition is left alone, and the list-typed option merges the two. | CLAUDE.md: that module is shared by all hosts and both builders load it. The issue's Decisions: all three hosts. The bar: DRY, one home for a cross-host policy. Both module systems declare `fonts.packages`. | Adding it to `darwin-common.nix` and `linux-common.nix` separately: two copies that must change together. Moving FiraCode there too: churn that no AC asks for. |
| D3 | `fetchurl` of the zip, then extract only the four named static TTFs. OFL.txt is not shipped, and `meta.license` records OFL. | Phase 0 verified the flat hash and it was re-verified here. The zip holds 166 files in 22 MB, while the four TTFs total about 530 KB. The issue ships the static variants only. nixpkgs' `geist-font` ships no license file either. The bar: Fail loud on the named members. | `fetchzip`: the whole 22 MB tree sits in the store as the source, and its NAR hash would have to be computed. Globbing `ttf/*.ttf`: a renamed upstream variant would ship silently. Shipping OFL.txt: a private install is not redistribution. |
| D4 | `anis-desktop` does not get FiraCode in `fonts.packages`. | The issue keeps FiraCode for the Mac's VS Code. AC 5 measures only the Mac. Scope stays tight. | Registering FiraCode on Linux as well: a behaviour change outside the issue. |
| D5 | AC 3 is measured through the configuration's `fonts.packages` element and its `src` derivation, with no new flake output or check. AC 4 and AC 5 need a real `just switch` on mbp, which the issue's own criteria call for. If sudo cannot run unattended, those rows stay `unverified` and go to the owner. They are never inferred from the build. | The issue's AC text. CLAUDE.md: switch only when asked, and the issue's evidence rows are that ask. The bar: Verify before claiming done, Truthful terminal states. | A `packages.<system>.geist-serif` output just to evaluate `.version`: it widens the flake surface for a measurement the configuration already exposes. Marking the evidence rows met from closure contents: activation is the thing being measured. |
| D6 | Refines D5: no agent runs `just switch`. AC 4 and AC 5 are graded `human_pending` and checked by the owner after merge, so ship holds the issue open as `needs-verification`. Before merge the implementer records only the base counts, 0 and ≥ 1, which show the probes discriminate. | At planning `sudo -n true` on mbp answered "a password is required". sdd's grading token for a row that waits on the owner is `human_pending`, and ship-issue holds such a row. Plans 447 and 448 left their post-switch rows to the user's switch. CLAUDE.md: switch only when asked. | `unverified`, D5's wording: that grade is an acceptance finding that outlives the fix wave, not a hold for the owner. Switching mbp to the unmerged branch: an activation of the owner's machine, with Homebrew zap, that this run is not authorized to perform. |
