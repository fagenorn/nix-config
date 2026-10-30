# Task 1: Install GeistMono Nerd Font on every host and name it in Ghostty

Spec § Solution and § Decisions, per D1 to D4 and D6. The all-hosts module gains one `fonts.packages` entry, and Ghostty's `font-family` names the family that font registers. Both edits land in one commit, and every acceptance row is measured at that commit. The task then opens the acceptance record.

**Files:**
- Modify: `hosts/common/common-packages.nix`
- Modify: `home/common/ghostty/default.nix`
- Create: `.agents/artifacts/plans/2026-10-30-issue-487-ghostty-geist-mono.acceptance.md`
- Test: `<scratch>/i487/check.sh`, where `<scratch>` is the root that `launch-scope scratch` prints. It is a gate script and is not committed.

**Interfaces:**
- Consumes: base `07f89813`, through the plan commit. The pinned lock's `pkgs.nerd-fonts.geist-mono` (`nerd-fonts-geist-mono-3.4.0+1.401`), and fontconfig 2.17.1 as `.#darwinConfigurations.mbp.pkgs.fontconfig.bin`. The username is `anis` (`vars/default.nix`).
- Produces: `mbp`'s Home Manager `programs.ghostty.settings.font-family` = `["GeistMono Nerd Font Mono"]`. Sorted `fonts.packages` names `["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2","nerd-fonts-geist-mono-3.4.0+1.401"]` on `mbp` and `eleven-m5`, and `["nerd-fonts-geist-mono-3.4.0+1.401"]` on `anis-desktop`. The acceptance record, with rows `AC1` to `AC4`.

**Invariants:**
- `git diff --numstat 07f89813 -- hosts/common/common-packages.nix home/common/ghostty/default.nix` prints exactly two lines: `1	1	home/common/ghostty/default.nix` and `3	0	hosts/common/common-packages.nix`.
- `git diff --quiet 07f89813 -- hosts/common/darwin-common.nix hosts/common/linux-common.nix` exits 0, so FiraCode stays in the darwin list and no linux block is added (D2).
- The generated `ghostty/config` changes only its `font-family` line. `font-size = 13` and the other four lines stay as they are (D6).
- Nothing is activated (D3).

- [ ] **Step 1: Write the gate script**

Save this as `<scratch>/i487/check.sh`. It is this task's failing test (D6):

```bash
#!/usr/bin/env bash
# Gate for issue 487: AC1 measured per D4, AC2's three font lists and AC3's
# pre-activation proxy (D3), each pinned exactly (D6). Prints values and counts only.
# Usage, from the worktree root: bash check.sh
set -euo pipefail
fam="GeistMono Nerd Font Mono"
geist="nerd-fonts-geist-mono-3.4.0+1.401"
hm='.#darwinConfigurations.mbp.config.home-manager.users.anis'
fail=0

# AC1 (D4): the list-typed setting's first element starts with GeistMono, and the
# whole setting is exactly the one family (D1).
first=$(nix eval --raw "$hm.programs.ghostty.settings.font-family" --apply builtins.head)
echo "AC1 font-family head: $first"
case "$first" in GeistMono*) ;; *) fail=1 ;; esac
whole=$(nix eval --json "$hm.programs.ghostty.settings.font-family")
echo "AC1 font-family: $whole"
if [ "$whole" != "[\"$fam\"]" ]; then fail=1; fi

# AC1: the generated ghostty/config is the base file with only its font-family line changed.
cfg=$(nix build --no-link --print-out-paths "$hm.xdg.configFile.\"ghostty/config\".source")
want=$(printf '%s\n' \
  'background-blur-radius = 10' \
  'background-opacity = 0.930000' \
  "font-family = $fam" \
  'font-size = 13' \
  'scrollback-limit = 20000' \
  'theme = light:catppuccin-macchiato,dark:catppuccin-macchiato')
if [ "$(cat "$cfg")" = "$want" ]; then
  echo "AC1 ghostty/config: as expected"
else
  echo "AC1 ghostty/config: differs from expected:"
  diff <(printf '%s\n' "$want") "$cfg" || true
  fail=1
fi

# AC2: each host's fonts.packages names, sorted, are exactly the expected list.
check_fonts() {
  local got
  got=$(nix eval --json ".#$1.config.fonts.packages" \
    --apply 'ps: builtins.sort builtins.lessThan (map (p: p.name) ps)')
  echo "AC2 $1: $got"
  if [ "$got" != "$2" ]; then fail=1; fi
}
check_fonts darwinConfigurations.mbp "[\"fira-code-6.2\",\"nerd-fonts-fira-code-3.4.0+6.2\",\"$geist\"]"
check_fonts darwinConfigurations.eleven-m5 "[\"fira-code-6.2\",\"nerd-fonts-fira-code-3.4.0+6.2\",\"$geist\"]"
check_fonts nixosConfigurations.anis-desktop "[\"$geist\"]"

# AC3 proxy (D3): the font tree mbp's activation copies to /Library/Fonts/Nix Fonts,
# scanned by the pinned fontconfig; count the files whose family list holds exactly $fam.
fonts=$(nix build --no-link --print-out-paths '.#darwinConfigurations.mbp.config.system.build.fonts')
fcbin=$(nix build --no-link --print-out-paths '.#darwinConfigurations.mbp.pkgs.fontconfig.bin')
count=$("$fcbin/bin/fc-scan" --format '%{file}|%{family}\n' "$fonts/Library/Fonts/Nix Fonts" 2>/dev/null \
  | awk -F'|' -v fam="$fam" '{ n = split($2, a, ","); for (i = 1; i <= n; i++) if (a[i] == fam) { print $1; break } }' \
  | sort -u | wc -l | tr -d ' ')
echo "AC3 proxy: $count font files register \"$fam\" (want >= 1)"
if [ "$count" -lt 1 ]; then fail=1; fi

echo "check exit $fail"
exit "$fail"
```

`fc-scan` writes a harmless `Cannot load default config file` line to stderr, which the script discards. A failed `fc-scan` fails the whole script, because of `pipefail`.

- [ ] **Step 2: Run the gate and watch it fail**

Run (timeout 1800 s): `launch-scope exec … -- bash <scratch>/i487/check.sh 2> <scratch>/i487/check.err`

Expected: exit 1, printing exactly these lines:

```
AC1 font-family head: FiraCode Nerd Font Mono
AC1 font-family: ["FiraCode Nerd Font Mono"]
AC1 ghostty/config: differs from expected:
3c3
< font-family = GeistMono Nerd Font Mono
---
> font-family = FiraCode Nerd Font Mono
AC2 darwinConfigurations.mbp: ["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2"]
AC2 darwinConfigurations.eleven-m5: ["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2"]
AC2 nixosConfigurations.anis-desktop: []
AC3 proxy: 0 font files register "GeistMono Nerd Font Mono" (want >= 1)
check exit 1
```

If the output is different, read `tail -20 <scratch>/i487/check.err` and stop. Do not edit the script to make it match.

- [ ] **Step 3: Edit the two modules**

1. `hosts/common/common-packages.nix`: after the `environment.systemPackages` list, which ends with `unstablePkgs.spicetify-cli` and then `    ];`, and before the file's closing `}`, insert one blank line and these two lines (per D2):

```nix
  # System fonts for every host; darwin-common.nix adds the FiraCode fonts on macOS.
  fonts.packages = [ pkgs.nerd-fonts.geist-mono ];
```

`pkgs` is already an argument of the module.

2. `home/common/ghostty/default.nix`: replace `      font-family = "FiraCode Nerd Font Mono";` with `      font-family = "GeistMono Nerd Font Mono";` (per D1). Nothing else changes.

Check: the numstat invariant above holds.

- [ ] **Step 4: Run the gate and watch it pass**

Run (timeout 1800 s): `launch-scope exec … -- bash <scratch>/i487/check.sh 2> <scratch>/i487/check.err`

Expected: exit 0, printing exactly:

```
AC1 font-family head: GeistMono Nerd Font Mono
AC1 font-family: ["GeistMono Nerd Font Mono"]
AC1 ghostty/config: as expected
AC2 darwinConfigurations.mbp: ["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2","nerd-fonts-geist-mono-3.4.0+1.401"]
AC2 darwinConfigurations.eleven-m5: ["fira-code-6.2","nerd-fonts-fira-code-3.4.0+6.2","nerd-fonts-geist-mono-3.4.0+1.401"]
AC2 nixosConfigurations.anis-desktop: ["nerd-fonts-geist-mono-3.4.0+1.401"]
AC3 proxy: 9 font files register "GeistMono Nerd Font Mono" (want >= 1)
check exit 0
```

The planning trial counted 9. Any count of 1 or more passes, and the record states the count it observed.

Run: `nixfmt --check hosts/common/common-packages.nix home/common/ghostty/default.nix`. Expected: exit 0.

- [ ] **Step 5: Build checks**

Run (timeout 3600 s): `launch-scope exec … -- bash -c 'set -o pipefail; just build mbp 2>&1 | tail -3'`. Expected: exit 0, and the last line builds a `darwin-system-25.11.…drv`.

Run (timeout 900 s): `launch-scope exec … -- nix eval --raw .#darwinConfigurations.eleven-m5.config.system.build.toplevel.drvPath`. Expected: exit 0, printing one `/nix/store/…-darwin-system-….drv` path.

- [ ] **Step 6: Commit the change**

`git status --short` must list exactly ` M home/common/ghostty/default.nix` and ` M hosts/common/common-packages.nix`. A `result` symlink from Step 5 is ignored and is not committed.

```bash
git add hosts/common/common-packages.nix home/common/ghostty/default.nix
launch-commit … -- -m "feat(fonts): Ghostty uses GeistMono Nerd Font on every host (issue 487)" \
  -m "nerd-fonts.geist-mono joins fonts.packages in the all-hosts module, and Ghostty's font-family names its registered Mono family. FiraCode stays installed." \
  -m "<session trailers>"
```

- [ ] **Step 7: Measure at the commit and open the acceptance record**

With a clean tree (`git status --short -- hosts home` prints nothing), run Step 4's gate again. Expected: the same eight lines, exit 0. This run is the evidence for the commit.

Create `.agents/artifacts/plans/2026-10-30-issue-487-ghostty-geist-mono.acceptance.md`. It holds the heading `# Acceptance record — issue #487`. Under it goes the sentence `Taken on host mbp; each row's Commit is the head its evidence was taken on (https://github.com/fagenorn/nix-config/issues/487).` Then comes one table with the columns `AC | Criterion | Kind | Check or command | Observed | Commit | Conditions | Verdict` and four rows, `AC1` to `AC4` in order:
- `Criterion`: the issue's acceptance-criterion line verbatim, without its `- [ ] ` checkbox. Read it with `gh issue view 487 --repo fagenorn/nix-config --json body --jq .body`. Escape each `|` inside a cell as `\|`.
- `Kind` and `Check or command`: copied from the plan root's Acceptance map.
- `AC1`: `Observed` holds the three `AC1` lines from this step. `Commit` is the short SHA of Step 6's commit. `Conditions` says: `mbp`; the eval read the committed tree; Step 5's `just build mbp` exited 0, and so did the `eleven-m5` drvPath eval, both on the tree that became this commit; `just build` runs again in final verification.
- `AC2`: `Observed` holds the three `AC2` lines. `Commit` is the same SHA. `Conditions` says: evaluated on `mbp` (aarch64-darwin), the `anis-desktop` list included; the PR's CI `Nix Eval` of `anis-desktop` reports at ship time.
- `AC3`: `Observed` holds the `AC3 proxy` line. `Commit` is the same SHA. `Conditions` says: taken before activation on `mbp`, with no `just switch` run; the pinned fontconfig 2.17.1 `fc-scan` read `mbp`'s `system.build.fonts` tree; the literal `ghostty +list-fonts` count after `just switch` is the owner's (D3).
- `AC4`: `—` in `Observed`, `Commit` and `Conditions` (a human row).
- `Verdict`: `—` in every row. The sdd controller writes it.

- [ ] **Step 8: Commit the record**

```bash
git add .agents/artifacts/plans/2026-10-30-issue-487-ghostty-geist-mono.acceptance.md
launch-commit … -- -m "docs(plan): acceptance record (issue 487)" -m "<session trailers>"
```

Verify: `grep -c '^| AC[1-4] |' .agents/artifacts/plans/2026-10-30-issue-487-ghostty-geist-mono.acceptance.md` prints `4`. `git status --short` prints nothing. `git diff --stat 07f89813..HEAD -- hosts home` lists exactly `home/common/ghostty/default.nix` and `hosts/common/common-packages.nix`.
