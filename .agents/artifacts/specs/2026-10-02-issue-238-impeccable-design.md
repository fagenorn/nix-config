# Issue 238 — Replace ui-ux-pro-max with the Impeccable design skill

Issue: https://github.com/fagenorn/nix-config/issues/238

## Problem

Both agents get their frontend design guidance from UI/UX Pro Max, a skill this
repo assembles itself from a template and a CSV corpus. The owner wants
Impeccable (pbakaus/impeccable, Apache-2.0) instead. It is a maintained skill
with a playbook per command and a design detector engine. Managing it has three
costs. The skill has to reach Claude and Codex in shapes each one loads. Its
engine has to be available without an unpinned download on first use. And
switching off the old skill must not leave a stale `ui-ux-pro-max` directory
behind. Design guidance also has to stay opt-in, so `sdd` and `from-issue` keep
their current context cost.

## Solution

A pinned non-flake input supplies upstream's prebuilt Claude skill tree
(`.claude/skills/impeccable`). A small Nix builder, living beside the
agent-plugins builder, produces one derived skill tree: upstream's tree as it
is, with the engine binary added in the launcher's sibling slot
`scripts/bin/<os>-<arch>/impeccable`. The engine binary is the checksummed
release asset for the host system. Both agents link that one tree:

- **Codex:** `~/.agents/skills/impeccable` is a whole-directory link (D3).
- **Claude:** `~/.claude/skills/impeccable` is a recursive link (D3).

`~/.agents/bin/impeccable` is a wrapper that execs the tree's own launcher. That
makes the detector a PATH command, with the launcher's skill-directory
resolution intact (D4). The upstream launcher is used unmodified. It finds the
sibling binary before any of its cache or download paths, so nothing is ever
downloaded. The ui-ux-pro-max input, its generating derivation and both of its
links are deleted. Home Manager's own orphan-link cleanup removes the old links
on switch, and a post-link report names any retired skill directory that is
still present (D6).

## Decisions

- **Source pin.** The flake input is pinned to upstream's immutable
  `skill-v<version>` tag, not to `main`. A bare `just update` therefore cannot
  move the skill away from its engine. A bump is a deliberate edit of the tag,
  the engine version and the hashes, all in one commit (D1). The lock entry
  is written with `nix flake lock`. That adds the new input and drops the old
  one without advancing any other input. `just update` is not used for this.
- **Engine.** The builder holds one engine record: a version, plus a `sha256`
  for each supported system. The values come from the release's `.sha256`
  sidecars, which are the same ones the upstream launcher verifies against.
  There are two supported systems: `aarch64-darwin` maps to `darwin-arm64` and
  `x86_64-linux` maps to `linux-x64`. On any other system, evaluation fails with
  a message naming that system. Evaluation also asserts that the engine version
  equals the trimmed `scripts/VERSION` of the pinned tree, and fails with a
  message naming both values when they differ (D2). The linux asset is a
  static-pie build. The darwin asset is ad-hoc signed and links only system
  frameworks. Neither needs patching, and both answer
  `engine-probe` → `impeccable-engine <version>`.
- **Derived tree.** The derived tree is a copy of upstream's skill tree with
  one change: the binary added at its platform slot, mode 0755. SKILL.md,
  `reference/`, `scripts/` (font index, live-browser assets) and the launcher
  are all byte-identical to upstream. The assets under `scripts/` never enter
  model context. They are only read by the engine and the browser.
- **Environment.** `home.sessionVariables` sets `IMPECCABLE_NO_UPDATE_CHECK=1`
  (D5). Nix owns the version. An `UPDATE_AVAILABLE` directive would steer an
  agent toward `impeccable update`, which cannot write to the read-only store.
- **Opt-in boundary.** No workflow skill names Impeccable. A session loads it
  only through the harness's description match or through an explicit
  `/impeccable`. Two facts carry the residency claim. The only resident text is
  the frontmatter description: SKILL.md is 12,115 B at v4.5.0, and loads only
  when invoked. The 42 `reference/*.md` playbooks (395 KB) load on demand,
  through links in SKILL.md's Commands table. The PR records both measurements.
- **Retirement.** The `ui-ux-pro-max` name leaves the
  `migrateCodexSkillLinks` loop. That migration exists only to clear a real
  directory that is in the way of a *new* link, and no new link targets this
  path. A list of retired skill names (currently only `ui-ux-pro-max`) feeds an
  activation step that runs after `linkGeneration`. For each of
  `~/.agents/skills` and `~/.claude/skills`, the step warns when a retired name
  still exists and names the first entry that is not an HM link. It never
  deletes anything and never fails activation (D6).
- **Docs.** The architecture doc's "UI/UX Pro Max is generated once…" sentence
  is replaced. The new text says Impeccable is one derived tree linked to both
  agents. It also states that detector availability is the pinned prebuilt
  engine, so the engine is never downloaded on demand and nothing is installed
  under `~/.impeccable/bin/`. The engine may still write runtime caches under
  `~/.impeccable`. It names `IMPECCABLE_NO_UPDATE_CHECK`. It also notes the known
  limitation that store-writing verbs (`update`, `install`, `link`, `pin`)
  cannot change the Nix-owned tree.

## Test seams

1. **`just build`:** evaluation succeeds on mbp. `nix eval` of
   `nixosConfigurations.anis-desktop` covers Linux, as CI's `Nix Eval` does. A
   VERSION/engine mismatch fails evaluation (D2).
2. **`just agent-installed-skill-tests`:** this suite reads the built
   home-manager-files, following the prior art of
   `tests/test_agent_tools_launchers.py`. A new installed-home test module
   asserts five things:
   - `.agents/skills/impeccable` is a link to a directory whose `SKILL.md` is a
     regular file;
   - `.claude/skills/impeccable/SKILL.md` exists;
   - no `ui-ux-pro-max` path exists under either root;
   - the host's sibling binary answers `engine-probe` with exactly the tree's
     `scripts/VERSION`;
   - `.agents/bin/impeccable engine-probe` answers the same through the
     launcher.

   The same module asserts the opt-in boundary at the same seam: no installed
   file under the `sdd` or `from-issue` skill trees mentions `impeccable`.
3. **Post-switch state:** after switching on mbp, a manual check confirms that
   neither root has a `ui-ux-pro-max` entry. The PR records this, along with the
   SKILL.md measurement. Activation cannot be tested in the repo, and removal is
   Home Manager's own upstream `cleanOldGen` behavior.

## Out of scope

- Wiring Impeccable's UI hooks or design passes into `sdd` or `from-issue`.
  That is a follow-up issue.
- Enabling `/impeccable hooks` in any project, and Impeccable's telemetry
  setting. Both are runtime choices made per project or per user.
- Other engine platforms (`darwin-x64`, `linux-arm64`, Windows), and building
  the engine from its Rust crates.
- Generalising `migrateCodexSkillLinks` or retiring any skill other than
  `ui-ux-pro-max`.
- Editing historical specs and plans that mention UI/UX Pro Max.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Pin the non-flake input to the immutable `skill-v4.5.0` tag; a bump edits tag + engine record together | Issue: pinned non-flake input; CLAUDE.md: `just update` advances ALL inputs; the-bar Fail loud | Track `main` like ui-ux-pro-max — every `just update` could desync skill and engine and break the build |
| D2 | Engine = per-system `fetchurl` of the `engine-v<version>` release asset, hashed from upstream's `.sha256` sidecars; eval asserts version == pinned `scripts/VERSION`; only the two host systems mapped, others throw | Issue detector rule (packageable binaries → PATH); assets are static-pie / system-framework-only; YAGNI | `buildRustPackage` from the crates (cargo-hash upkeep, long builds for an upstream-checksummed binary); accept the on-demand download (impure, needs egress) |
| D3 | One derived tree with the binary in the launcher's sibling `scripts/bin/<os>-<arch>/` slot; Codex whole-dir link, Claude recursive link | CLAUDE.md: Codex ignores a symlinked SKILL.md; every Claude-side multi-file skill uses recursive links; launcher prefers the sibling before cache/download | Whole-dir link for Claude (no repo precedent that Claude discovers a symlinked skill dir); `IMPECCABLE_BIN` env (any shell that misses session vars falls through to the download) |
| D4 | `~/.agents/bin/impeccable` is a wrapper exec'ing the store tree's launcher | Launcher derives `IMPECCABLE_SKILL_DIR` from `dirname $0` (no `-P`) | Symlink the launcher (skill dir resolves to `~/.agents`); link the raw engine (no skill dir → no references, no version); an `agent_tools` command-table row (that table is for package modules) |
| D5 | Set `IMPECCABLE_NO_UPDATE_CHECK=1` via `home.sessionVariables`; leave telemetry at upstream default | Nix owns the version; store is read-only; issue silent on telemetry (tight scope) | Leave update nags on (directs agents to a verb that cannot work); also flip telemetry (unrequested preference) |
| D6 | Removal relies on HM `cleanOldGen` (orphan links + `rmdir -p --ignore-fail-on-non-empty`); a generic retired-names list feeds a post-`linkGeneration` warn-only report; `ui-ux-pro-max` leaves the migration loop | the-bar Framework-first; pinned HM `files.nix` cleanup; existing migration refuses foreign content; live mbp tree holds only HM leaves | A delete-capable pre-`checkLinkTargets` sweep (duplicates HM's cleanup); `exit 1` on leftovers (a retired path collides with nothing, so failing the switch is disproportionate) |
| D7 | Opt-in verified at the installed-home seam: no installed `sdd`/`from-issue` file mentions `impeccable`; residency claimed only from SKILL.md frontmatter + on-demand references, measured in the PR | Issue: design guidance stays opt-in; the-bar Tests that can fail | A runtime eval of sdd sessions (costly, nondeterministic) |
| D8 | The plan never switches: the post-switch check (seam 3) runs only when the owner runs `just switch`, and until then the PR records it as owner-pending beside the build-time evidence | CLAUDE.md: switch only when asked (sudo); autonomous mode never self-grants authorization | Switch inside execution (activation needs owner consent and may prompt for sudo) |
| D9 | The installed test runs both the Codex-side (`~/.agents/bin`) and Claude-side (`.claude/skills/impeccable/scripts/impeccable`) launchers with `HOME` set to a scratch directory and `IMPECCABLE_*` stripped, and fails if anything appears under the scratch `.impeccable/bin` | the-bar Tests that can fail: a missing sibling would fall through to a networked download that still answers `engine-probe` | Assert only the probe output (a download fallback passes it silently) |
