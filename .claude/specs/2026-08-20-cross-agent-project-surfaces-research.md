# Project-scoped instruction, skill, configuration, hook and plugin surfaces in Claude Code and Codex, and what a single canonical repository source would have to project

**Durability: committed** (Git owns this file's history from this commit forward.)

## Provenance

This document is a **re-derivation authored 2026-09-02 under issue #115**. It is
not the artifact that issue [#60](https://github.com/fagenorn/nix-config/issues/60)'s
resolution comment linked. That artifact was **never committed** to any git ref —
`git log --all -- .claude/specs/2026-08-20-cross-agent-project-surfaces-research.md`
returns zero commits in this repository — and its content is therefore
**unrecoverable**. Nothing below is a recovered byte, and **no claim in this file
may be cited as evidence of what the original said.**

What this document is obligated to satisfy is the set of conclusions asserted in
#60's [resolution comment](https://github.com/fagenorn/nix-config/issues/60),
plus #60's own research question. Those obligations are enumerated as claim IDs
in `## Coverage of the resolution summary`; every one of them is discharged here
from primary sources read on 2026-09-02, never from the resolution summary
itself.

The filename's `2026-08-20` prefix is **#60's decision date**, not this file's
authorship date. The authorship date is 2026-09-02. The two differ deliberately,
because the path is the one #60's resolution comment links and nothing may rename
it.

Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked.
This document asserts repository-state inventory — which files exist at which
scope in three checkouts on 2026-09-02 — not a live-availability or blocking
conclusion, so the gate's two-timepoint standing-conclusion machinery does not
apply. This follows the precedent set by
`.claude/specs/2026-08-16-codex-worker-death-research.md`. Confidence is stated
inline instead.

## Research question

#60's question, verbatim:

> Which currently supported project-scoped instruction, skill, configuration,
> plugin, and hook mechanisms in Claude Code and Codex can support one canonical
> repository source without copied bodies?
>
> Document discovery paths, precedence, refresh or restart behavior, symlink
> support, failure semantics, and gaps. Use official documentation and
> first-party installed behavior; do not choose the architecture.

## Coverage of the resolution summary

| ID (source) | Claim restated in one line | Source of the claim | Discharged by (heading in this document) |
|---|---|---|---|
| C60.1 (summary) | Both agents provide repo-scoped instructions, skills, configuration, hooks and plugins, as a 5-mechanism × 2-agent matrix with a present/absent verdict per cell. | #60 resolution comment | Mechanism × agent matrix |
| C60.2 (question) | Per cell: discovery path, precedence, refresh or restart behaviour, symlink support, failure semantics, gaps. | #60 research question | Per-cell axes |
| C60.3 (summary) | Fixed native paths mean one contained canonical source needs validated thin projections, with the mechanism forcing each projection named per cell. | #60 resolution comment | What each mechanism forces a projection to do |
| C60.4 (summary) | The remaining prototype gaps, listed — under both readings of "prototype", the referent being irreducibly ambiguous. | #60 resolution comment | Remaining gaps, under both readings of "prototype" |
| C60.5 (question) | The architecture is not chosen; options are recorded, never ranked into a decision. | #60 research question | Options recorded, not ranked |

## Unverified inheritance

This section holds two kinds of entry: claims inherited from #60's resolution
summary or its question that are **not** re-verifiable against a primary source
(items 1-3), and observed claims whose truth is bounded — by the fleet snapshot,
or by the limits of what absence of evidence can establish (items 4-5). Silence
is not permitted, so each is named.

1. **C60.4's referent for "prototype" is irreducibly ambiguous.** #60's summary
   says "remaining prototype gaps are listed in the artifact" without naming the
   prototype. Two readings are live and they diverge:
   (a) a *projection prototype* — a trial of the contained-source-with-thin-
   projections shape itself; (b) **#79's adoption dry run** — issue #79 is
   titled "Prototype the nix-config adoption dry run and surface contract gaps"
   and asks for "one linked, disposable-fidelity artifact that exercises the
   `reconcile` path". The original's choice is unrecoverable, so this document
   **covers both readings and picks neither**. See
   `Remaining gaps, under both readings of "prototype"`.
2. **The documentation half of #60's question is not re-derived.** #60 asked for
   "official documentation *and* first-party installed behavior". This
   re-derivation is built from first-party installed behaviour only — the three
   checkouts and this repository's Nix modules. Whatever the original concluded
   from vendor documentation is unrecoverable and is not reconstructed here.
   Every axis this evidence base cannot answer is marked *no answer in the
   sources read* rather than filled in from expectation.
3. **The phrase "validated thin projections" is #60's, not an observation.** It
   is carried as the coverage obligation for C60.3. What this document verifies
   is which mechanism facts *force* a projection and what a validator would have
   to check; that the resulting shape should be called "thin" is inherited.
4. **Snapshot-bound fleet claims.** Every claim about `nodo` is bound to the
   checked-out snapshot, which is 111 commits behind its own `origin/dev` (see
   `Method and evidence base`). Any nodo conclusion could turn on those 111
   commits. Argus's checkout is level with `origin/main` and carries no such
   caveat.
5. **Absence verdicts are observed absence, not proof of non-existence** — and
   this applies at **both** scopes. For a Codex *project*-scope mechanism, the
   evidence is that no such surface exists in any of the three checkouts. For a
   Codex *user*-scope mechanism, the evidence is a direct read of
   `~/.codex/config.toml` on 2026-09-02 — not the silence of
   `home/common/codex/default.nix`, which owns exactly one key of that
   runtime-managed file and so could never witness the absence of anything else
   in it. Both are strong for this machine and these three repositories, and
   neither is a claim about what Codex supports in general.

## Method and evidence base

**Scope labelling (per #60's own framing).** #60 asks about **project scope** —
surfaces that live inside a repository. This repository's agent modules
(`home/common/agent-guidance/`, `home/common/agent-skills/`,
`home/common/claude-code/`, `home/common/codex/`, `lib/agent-plugins.nix`) are
first-party installed behaviour at **user scope**: they populate `~/.claude`,
`~/.codex` and `~/.agents`, not any repository. They are admissible evidence for
how a *mechanism* behaves, and every observation below carries the scope it was
taken at. Any move from a user-scope observation to a project-scope conclusion
is written as an explicit inference with its own evidence level, never as a
direct observation.

**Sources, and how they are cited.**

- *Files in this repository* (nix-config) are cited by repo-relative path, with
  the option or symbol name when the claim is about one.
- *Files in a fleet checkout* are cited as repository name + repo-relative path
  + the checkout's observed `HEAD` + the observation date. All fleet
  observations are dated **2026-09-02** and were read without writing to,
  checking out, fetching or stashing in either checkout.
- *Files in the user's home directory* — `~/.codex/config.toml` is the only one
  cited here — are given by absolute path with the observation date and are
  always labelled `user scope`. They sit outside every repository, which is
  precisely the fact several conclusions below turn on.
- *Settled decisions* are cited by issue number.

**The two fleet checkouts, as observed on 2026-09-02:**

| Checkout | Observed `HEAD` | Branch | Divergence from its own `origin` integration ref |
|---|---|---|---|
| `/Users/anis/Projects/nodocom` (`nodo`) | `7a3dab7e541f44f5b021fe13a1e20894de2ef0b8` | `dev` | 111 commits behind `origin/dev`, 0 ahead (`git rev-list --count HEAD..origin/dev` → `111`) |
| `/Users/anis/Projects/argus` (`argus`) | `20d6655223e9497c2668f67dd016e1111b3a78cb` | `main` | level with `origin/main` — 0 behind, 0 ahead |

The checked-out snapshot is the cited evidence. Neither checkout was refreshed,
so these are the surfaces as they stood on 2026-09-02, not either repository's
current integration tip.

**The third repository is nix-config itself**, read at project scope in the
worktree `worktree-issue-115-recover-wayfind-research-findings`.

## Mechanism × agent matrix

Verdicts are **project scope only**, and mean: a surface of this kind was
observed inside at least one of the three repositories (present), or none was
observed in any of them (absent). User-scope facts are listed underneath and are
not counted toward a project-scope verdict.

| Mechanism | Claude Code (project scope) | Codex (project scope) |
|---|---|---|
| Instructions | **Present** — repo-root `CLAUDE.md` in all three repositories: `CLAUDE.md`; nodo `CLAUDE.md` (`git ls-files -s` → mode `100644`) @`7a3dab7e54`, 2026-09-02; argus `CLAUDE.md` (mode `100644`) @`20d6655223`, 2026-09-02 | **Present** — repo-root `AGENTS.md`: nodo `AGENTS.md`, tracked at mode `120000`, a symlink to `CLAUDE.md` @`7a3dab7e54`; argus `AGENTS.md`, mode `100644` @`20d6655223`. Absent in nix-config, which has no `AGENTS.md` |
| Skills | **Present** — `.claude/skills/<name>/SKILL.md`: argus tracks three (`git ls-files .claude/skills` → one `SKILL.md` each under `adding-a-capability/`, `writing-pi-extensions/`, `writing-pi-skills/`) @`20d6655223`; nodo carries 34 untracked vendored skill directories @`7a3dab7e54`. Absent in nix-config, which has no `.claude/skills/` | **Absent** — no project-scoped Codex skill surface in any of the three checkouts; no `.codex/` directory exists in any of them. `home/common/codex/default.nix` states that "Skills reach Codex through the whole-directory links at ~/.agents/skills" — user scope |
| Configuration | **Present** — `.claude/settings.json` and `.claude/settings.local.json`: both observed in nodo @`7a3dab7e54`. Plus the agent-neutral `.claude/skills.config.json` in nix-config and in nodo | **Absent as a repository file** — no Codex configuration file exists in any of the three checkouts. The *mechanism*, however, is not absent: user-scope `~/.codex/config.toml` (read 2026-09-02) carries a **per-project configuration namespace**, 63 `[projects."<absolute path>"]` sections, and all three checkouts are registered in it. It is keyed by absolute path and lives outside every repository, so it is per-project configuration that cannot be a repository source — see the Discovery path and Gaps rows below |
| Hooks | **Present** — a `hooks` key inside project settings: nodo `.claude/settings.json` resolves to `{"hooks": {}}` @`7a3dab7e54` — the surface exists and is empty | **Absent** — no hook surface at either scope. At project scope no Codex config file exists in any checkout. At **user scope** this is a direct read, not an inference from module silence: `~/.codex/config.toml` (281 lines, read 2026-09-02) contains no `hooks` key and no occurrence of the string `hook` at all (`grep -i hook` → no match) |
| Plugins | **Present** — an `enabledPlugins` key inside project settings: nodo `.claude/settings.local.json` carries `"enabledPlugins": {}` @`7a3dab7e54` — the surface exists and is empty | **Absent** at project scope. At user scope Codex has plugins, but `CLAUDE.md` records that "Codex has no Nix-declared marketplace: its marketplaces and plugins are runtime-managed inside `~/.codex/config.toml`, which Nix does not own" |

**Reading of this matrix.** Claude Code exposes all five mechanisms at project
scope, and a live example of each was found. Codex exposes exactly one —
instructions, via `AGENTS.md`. The asymmetry, not the count, is what governs
everything below: four of the five mechanisms have no project-scope Codex target
to project *into*.

## Per-cell axes

One table per mechanism; rows are #60's six axes; columns are the two agents.
*No answer in the sources read* is a verdict, and is used wherever this evidence
base cannot settle an axis — it is not a placeholder for a conclusion omitted.

### Instructions

| Axis | Claude Code | Codex |
|---|---|---|
| Discovery path | Repo-root `CLAUDE.md`, observed in all three repositories (`CLAUDE.md`; nodo and argus `CLAUDE.md` @ their HEADs, 2026-09-02) | Repo-root `AGENTS.md`, observed in nodo and argus, absent in nix-config. argus `AGENTS.md` @`20d6655223` states it "is auto-discovered by pi and Claude Code when working at the **repo root**" and names a second `home/AGENTS.md` "loaded when pi runs rooted in `home/`" — evidence that at least one `AGENTS.md` consumer roots discovery at the working directory; the agent named there is pi, so whether Codex nests the same way is *no answer in the sources read* |
| Precedence | A user-scope `~/.claude/CLAUDE.md` exists simultaneously, supplied from `home/common/agent-guidance/AGENTS.md` by `programs.claude-code.memory` (`home/common/claude-code/default.nix`). Which file wins on conflict: *no answer in the sources read*. argus removes the question in content rather than by mechanism — its `CLAUDE.md` @`20d6655223` is an 11-line pointer whose opening sentence is "This project's full agent & contributor guide is **`AGENTS.md`**" | A user-scope `~/.codex/AGENTS.md` exists simultaneously, written by `home/common/agent-guidance/default.nix` from the same `AGENTS.md` source. Project-vs-user order: *no answer in the sources read* |
| Refresh or restart | *No answer in the sources read.* The user-scope file is a read-only store symlink described in `home/common/claude-code/default.nix` as "read-only store symlink is safe; static", which says nothing about when a session re-reads it | *No answer in the sources read* |
| Symlink support | At project scope, no `CLAUDE.md` symlink was observed — all three are regular files. At user scope the file *is* a store symlink (`programs.claude-code.memory`, `home/common/claude-code/default.nix`). Inferring project-scope symlink support from that user-scope fact is an inference at **low** evidence level and is not asserted | **Supported for the instruction file itself**, at project scope: nodo tracks `AGENTS.md` in git at mode `120000` pointing at `CLAUDE.md` @`7a3dab7e54`, 2026-09-02, and that symlink is the repository's only Codex-facing instruction file. Evidence level **moderate**: the link's presence and its commitment to git are directly observed; that Codex resolves rather than skips it is inferred from its being the sole such file in an actively worked repository |
| Failure semantics | *No answer in the sources read* — no missing or broken `CLAUDE.md` was observed | *No answer in the sources read* for a broken link. nix-config's own missing `AGENTS.md` is an observed absence with no observed consequence recorded anywhere in the tree |
| Gaps | The two agents read **two different filenames at the same root**, so a single instruction body at project scope is impossible without a projection at that root. nix-config, the repository that authors both agents' user-scope trees, has no project-scope `AGENTS.md` at all — a Codex session working in it inherits user-scope guidance only | Same gap, from the other side. Additionally, the only *validated* project-scope projection observed is nodo's git-tracked symlink; argus's pointer is authored prose with **no observed mechanism that detects drift** between `CLAUDE.md` and `AGENTS.md` |

### Skills

| Axis | Claude Code | Codex |
|---|---|---|
| Discovery path | `.claude/skills/<name>/SKILL.md`. argus tracks three `SKILL.md` files @`20d6655223`; nodo holds 34 skill directories under `.claude/skills/` @`7a3dab7e54`, none of them tracked (`git ls-files .claude/skills` → 0; `git check-ignore -v` names `.gitignore:46:.claude/*`) | *None observed at project scope.* No `.codex/` exists in any of the three checkouts. At **user scope** the path is `~/.agents/skills/<name>/` as whole-directory links (`home/common/agent-skills/default.nix`), plus `~/.codex/skills/`, which `CLAUDE.md` records as "Codex's own runtime state" that Nix "neither populates nor prunes" |
| Precedence | **Directly observed:** the `skillOverrides` keys in nodo `.claude/settings.local.json` @`7a3dab7e54` are **bare skill names**, not paths or scope-qualified identifiers, and one of them (`analyzing-dotnet-performance`) resolves to a project-scope directory under nodo `.claude/skills/` while three (`design-md`, `enhance-prompt`, `weekly-review`) resolve to nothing in nodo's `.claude/skills/` or in this repository's `home/common/agent-skills/skills/`. **Inferred, evidence level low:** that the name space is therefore *flat across scopes*, so a project skill and a user skill could collide on a name. The three unresolved names are equally consistent with stale override entries for skills that no longer exist anywhere, and nothing observed discriminates between the two explanations. Which scope wins a name collision: *no answer in the sources read* | Not applicable at project scope (no surface). At user scope `CLAUDE.md` records a real collision hazard in the same flat name space: "a skill hand-copied there duplicates the managed `~/.agents/skills/` link of the same name and has to be removed by hand" |
| Refresh or restart | At project scope, **vendored copies do not refresh**: nodo `.claude/resync-dotnet-skills.sh` @`7a3dab7e54` states in its own header that the skills "were vendored (copied), not installed via the plugin marketplace, so they do NOT auto-update. Run this script to pull the latest upstream copies", and pins provenance as `github.com/dotnet/skills` commit `a7a744ce18951bf30a73769217abbd7165203be9`. Whether a *running* session re-reads a changed `SKILL.md`: *no answer in the sources read* | *No answer in the sources read* at project scope. At user scope, content advances only on a Home Manager activation, since every skill path is a store link (`home/common/agent-skills/default.nix`) |
| Symlink support | **Per-file store symlinks are accepted**, at user scope: `home/common/agent-skills/default.nix` comments that "Claude accepts Home Manager's recursive file links, so its generated multi-file skill can continue to use that layout", and `.claude/skills/ui-ux-pro-max` is declared with `recursive = true`; `programs.claude-code.skillsDir` feeds the same authored tree. At **project scope**, zero symlinks exist under `.claude/skills` in either fleet checkout (`find .claude/skills -maxdepth 2 -type l` → 0 in nodo; none in argus), so project-scope symlink support is **unobserved**, not confirmed | **A symlinked `SKILL.md` is ignored; a symlinked skill *directory* is not.** `home/common/agent-skills/default.nix`: "Codex ignores a skill when SKILL.md itself is a symlink, but supports a symlink to the whole skill directory" — user scope, and it is the reason `~/.agents/skills/<name>` is a whole-directory link rather than Home Manager's default recursive per-file layout. This is a *mechanism* fact and the strongest single symlink observation in the evidence base |
| Failure semantics | *No answer in the sources read* for a malformed or unreadable project skill | Codex's symlinked-`SKILL.md` case fails as a **silent ignore**, not an error — the skill simply does not appear (`home/common/agent-skills/default.nix`). By contrast the *installer* around it fails loudly: `home.activation.migrateCodexSkillLinks` refuses with `errorEcho ... "Refusing to replace $target because it contains content not owned by the previous Home Manager skill layout"` and `return 1`, aborting activation rather than deleting user-authored content — user scope |
| Gaps | No project-scope root is shared with Codex, and the only *observed* project-scope skill bodies are copies (nodo's 34 vendored directories) or per-project originals (argus's three) — **no project-scope skill in the fleet is a link to a shared source** | Two gaps compound: no project-scope discovery path was observed at all, and the link *shape* that works differs by agent (whole-directory for Codex vs per-file acceptable for Claude), so even if a path existed, one link layout could not serve both |

### Configuration

| Axis | Claude Code | Codex |
|---|---|---|
| Discovery path | `.claude/settings.json` and `.claude/settings.local.json`, both observed in nodo @`7a3dab7e54`. Separately, an **agent-neutral** project config exists at `.claude/skills.config.json` — present in nix-config (`{"orchestration": {"agentBudgetMinutes": 180, "maxParallel": 2}}`) and in nodo — read not by either agent but by `home/common/agent-skills/scripts/resolve-bindings`, which finds it by "walking up from the current directory" (`CONFIG_RELPATH = Path(".claude/skills.config.json")`) | *No file inside any repository.* The surface is user-scope `~/.codex/config.toml` (281 lines, read 2026-09-02), and it does carry per-project configuration: **63 `[projects."<absolute path>"]` sections**, each holding exactly one key on this machine, and all 63 identical: `trust_level = "trusted"` (63 sections, 63 `trust_level` lines, one distinct value; `[projects."/Users/anis/tmp/nix-config"]` is one of them). All three checkouts of this study are registered. Top-level keys observed alongside them: `model_reasoning_effort`, `model`, `approvals_reviewer`, `notify`, `service_tier`. The namespace is keyed by **absolute path**, so an entry cannot be committed, does not travel with a clone, and does not survive the same repository being checked out at a different path |
| Precedence | Two project-scope files are observed carrying disjoint keys: nodo's `settings.json` holds only `hooks`, while `settings.local.json` holds `permissions`, `enabledMcpjsonServers`, `disabledMcpjsonServers`, `skillOverrides`, `worktree` and `enabledPlugins` @`7a3dab7e54`. A user-scope `~/.claude/settings.json` exists in parallel, generated from the `settings` attrset in `home/common/claude-code/default.nix`. The merge order across the three is *no answer in the sources read*. One intra-file conflict is directly observable and its resolution is likewise unknown: nodo's `settings.local.json` lists `shadcn` in **both** `enabledMcpjsonServers` and `disabledMcpjsonServers` | `home/common/codex/default.nix` implements a precedence of its own by rewriting: an `awk` pass prepends `model_reasoning_effort = "xhigh"` and drops any pre-existing **top-level** assignment of that key, leaving section-scoped keys untouched (`/^[[:space:]]*\[/ { in_top_level = 0 }`). Nix owns exactly that one key; the rest of the file stays runtime-managed — user scope. The 63 `[projects."<path>"]` sections are a directly observed consequence of that rule: being section-scoped, they survive every activation untouched, which is why a per-project namespace can accumulate in a file Nix rewrites on each switch |
| Refresh or restart | At user scope, the file is re-asserted on **every activation**: `home.activation.claudeCodeSettings` runs `cp -f` then `chmod u+w`, and the module states "Claude Code can still rewrite it at runtime — your live edits persist until the next switch, which resets it to the declared content". Project scope: *no answer in the sources read* | Same shape at user scope — `home.activation.codexConfig` rewrites `~/.codex/config.toml` through a temp file and `mv -f` on every activation. Project scope: not applicable |
| Symlink support | **A symlink is accepted for reading and breaks writing.** At project scope, nodo `.claude/settings.json` @`7a3dab7e54` *is* a symlink into `/nix/store/...` and resolves to `{"hooks": {}}` — evidence level **moderate** for read support (the link is directly observed; that Claude resolves it is inferred). At user scope the same shape is explicitly rejected for a *writable* file: `home/common/claude-code/default.nix` records that the module's own option "writes ~/.claude/settings.json as a READ-ONLY store symlink, which breaks Claude Code's in-app /config flow and the sandbox (both rewrite the file)", which is why the file is materialised as a writable copy instead | Not applicable at project scope. At user scope the same constraint holds by construction: `home.activation.codexConfig` keeps `config.toml` a real writable file because "plugins and marketplaces also use it" |
| Failure semantics | For the agent-neutral file, **degrade rather than fail**: `resolve-bindings` catches `OSError`/`json.JSONDecodeError`, prints `resolve-bindings: cannot read {path}: {error}` to stderr, returns `{}`, and falls through to its `DEFAULTS` table. For the native settings files: *no answer in the sources read* | *No answer in the sources read* |
| Gaps | A shared project-scope setting has **no Codex-side file inside the repository** to be shared with. Codex does have per-project configuration, but it is path-keyed and user-scope-resident (see the Codex column), so a canonical *repository* source cannot reach it by any in-repo projection — only by something that writes into the user's `~/.codex/config.toml` on that machine. The only observed cross-agent project configuration therefore remains the agent-neutral `.claude/skills.config.json`, which neither agent reads natively. And the read-only-symlink finding constrains any projection: the projected file must stay **writable**, because the agent writes to it | The per-project namespace's key *is* its gap: keyed by absolute path, it cannot be committed, does not follow a clone, and silently supplies nothing when the same repository is checked out elsewhere. That is not hypothetical: on 2026-09-02 `[projects."/Users/anis/tmp/nix-config"]` is registered and trusted, while this study's own worktree of that same repository, `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-115-recover-wayfind-research-findings`, has no entry at all — and none of the 63 registered paths is a worktree path. Beyond `trust_level`, no per-project key was observed: project-scope reasoning-effort or model settings have no home, so the one key Nix does control is settable only machine-wide |

### Hooks

| Axis | Claude Code | Codex |
|---|---|---|
| Discovery path | A `hooks` key **inside** the settings file, not a separate path. Project scope: nodo `.claude/settings.json` → `{"hooks": {}}` @`7a3dab7e54`. User scope: `settings.hooks.PreToolUse` in `home/common/claude-code/default.nix`, one entry with `matcher = "Bash"` and a `type = "command"` hook whose `command` is the `claude-bash-lifecycle-guard` store path, `timeout = 30` | *None at either scope*, observed directly rather than inferred from the Nix module's silence: `~/.codex/config.toml` (281 lines, user scope, read 2026-09-02) contains no `hooks` key and no occurrence of `hook` in any form. Its section namespaces are `[projects."<path>"]`, `[plugins."<name>@<marketplace>"]`, `[marketplaces.<name>]`, `[mcp_servers.<name>]`, `[features]`, `[desktop]`, `[tui.*]`, `[shell_environment_policy.set]` and `[notice]` — no hook namespace among them |
| Precedence | The only non-empty hook set observed is user scope; nodo's project-scope `hooks` object is empty, so **no merge or override case was observed** and the ordering is *no answer in the sources read* | Not applicable |
| Refresh or restart | The hook `command` is a Nix store path frozen into `~/.claude/settings.json` at generation time, so a hook change reaches the agent only when that file is rewritten — i.e. on the next activation (`home.activation.claudeCodeSettings`). Whether a *running* session re-reads it: *no answer in the sources read*. Project scope: *no answer in the sources read* | Not applicable |
| Symlink support | Indirect, and it is the settings file's property, not the hook's: nodo's project `settings.json` — the file that *carries* the hooks key — is itself a store symlink @`7a3dab7e54`. The hook's own `command` is a plain store path, not a symlink | Not applicable |
| Failure semantics | **Fail-closed, and loudly.** The user-scope guard's `block(reason)` prints `lifecycle guard: {reason}` to stderr and returns exit `2` (`home/common/claude-code/default.nix`), and `CLAUDE.md` states "There is no defer path: once the hook adjudicates a verb it is validated-and-allowed or blocked, never handed back to the allowlist unexamined, and every uncertainty (unknown repo, unresolvable default branch, child timeout, non-zero or unparseable output) blocks". Project scope: *no answer in the sources read* — no project hook was observed running | Not applicable |
| Gaps | Hooks are not an independent surface: they inherit every constraint of the settings file that carries them, including the writable-file requirement. And with no Codex counterpart at either scope, a hook is **not expressible as a cross-agent canonical source at all** — the Codex side of the projection is necessarily empty | The absence is the gap |

### Plugins

| Axis | Claude Code | Codex |
|---|---|---|
| Discovery path | An `enabledPlugins` key plus `extraKnownMarketplaces` inside the settings file. Project scope: nodo `.claude/settings.local.json` → `"enabledPlugins": {}` @`7a3dab7e54` — key present, empty. User scope: `home/common/claude-code/default.nix` enables `skill-creator@claude-plugins-official` and `codex@nix-codex` | *None inside any repository.* At user scope the surface was read directly in `~/.codex/config.toml`, 2026-09-02, and mirrors Claude's shape: 10 `[plugins."<name>@<marketplace>"]` sections each carrying one `enabled` boolean, over 2 `[marketplaces.<name>]` sections (`openai-bundled`, `openai-primary-runtime`) each declaring `source_type = "local"` plus a `source` path. This is the runtime-managed state `CLAUDE.md` describes: "Codex has no Nix-declared marketplace: its marketplaces and plugins are runtime-managed inside `~/.codex/config.toml`, which Nix does not own". No plugin entry is keyed by project |
| Precedence | Enablement is a per-`plugin@marketplace` boolean, and **two marketplace source types are accepted simultaneously**: `claude-plugins-official.source = { source = "github"; repo = "anthropics/claude-plugins-official"; }` and `nix-codex.source = { source = "directory"; path = "${agentPlugins.codex}"; }` — a store path built by `lib/agent-plugins.nix`. Project-vs-user merge: *no answer in the sources read*, and nodo's project value is empty so no case was observable | Not applicable at project scope |
| Refresh or restart | **The declared marketplace and the install record drift, and drift is not self-correcting.** `home.activation.repairCodexPluginInstall` exists precisely for this: "After a rebuild the recorded codex installPath can dangle (old store path GC'd, cache copy wiped) or point at a stale patch revision — spawned sessions then resolve stale or broken agent definitions (observed: p1 record while the marketplace served p2, exit-127 bridge behavior in the nodo evidence run)". The mutable record is `~/.claude/plugins/installed_plugins.json`; the repair is idempotent and "rewrites only when installPath differs from the current store plugin" — user scope | Not applicable |
| Symlink support | Not used and not observed. The marketplace is referenced by **absolute store path**, and `home/common/claude-code/default.nix` records that "Claude's install/cache state under ~/.claude/plugins stays mutable (never Nix-owned)" — so the projection here is a copy under a mutable root, not a link | Not applicable |
| Failure semantics | **Silent degradation, not refusal.** A dangling `installPath` yields "stale or broken agent definitions" and the observed `exit-127 bridge behavior` rather than an error at declaration time (`home/common/claude-code/default.nix`) — the failure surfaces later, in a spawned session. Project scope: *no answer in the sources read* | Not applicable |
| Gaps | The source of truth (a content-addressed store path) and the consumed state (a mutable JSON install record) are **different objects in different lifecycles**, so this mechanism cannot be projected by linking at all; it needs a reconciler. `repairCodexPluginInstall` is that reconciler, and it exists because its absence was observed to fail | No project-scope plugin surface exists to project into, and the user-scope one is runtime-managed state Nix explicitly does not own — so a repository-canonical plugin set has no target on the Codex side |

## What each mechanism forces a projection to do

C60.3's obligation: fixed native paths mean one contained canonical source needs
*validated thin projections*. Per cell, the observed mechanism fact that makes a
projection necessary — and what "validated" would have to mean for it:

| Mechanism | The fact that forces a projection | What a validator would have to check |
|---|---|---|
| Instructions | The two agents read **different filenames at the same root** (`CLAUDE.md`, `AGENTS.md`) — observed in nodo and argus. A contained canonical body cannot occupy both names | That the two names still resolve to one body. nodo's git-tracked `120000` symlink is self-validating — git stores the link, so a divergence would be a tracked change. argus's authored pointer is not: **no drift detector was observed** for it |
| Skills | Discovery roots differ (`.claude/skills/` for Claude; nothing observed for Codex at project scope) **and the link shape that works differs by agent** — Codex ignores a symlinked `SKILL.md` but follows a symlinked directory (`home/common/agent-skills/default.nix`) | That each projection uses the shape its consumer tolerates. The in-tree precedent validates by *refusing*: `migrateCodexSkillLinks` aborts activation unless every leaf under a target is provably an old Home Manager link |
| Configuration | The native file must remain **writable** — a read-only store symlink at `~/.claude/settings.json` "breaks Claude Code's in-app /config flow and the sandbox (both rewrite the file)" (`home/common/claude-code/default.nix`) — so the projection cannot be a link to an immutable source | That the projected file is present, writable, and matches the canonical content at assertion time. The in-tree precedent is `cp -f` + `chmod u+w` on every activation, accepting that runtime edits survive until the next switch |
| Hooks | Hooks are a **key inside the settings file**, so they inherit the writable-file constraint above and cannot be projected independently of it. And no Codex hook surface exists, so the Codex side of any hook projection is empty by construction | That the hook's `command` target still exists — the plugin case proves a store path recorded in a generated JSON file can dangle after a rebuild and GC (there, `~/.claude/plugins/installed_plugins.json`) |
| Plugins | Declaration and consumption are **different objects**: an immutable store marketplace versus a mutable `installed_plugins.json`. A link cannot bridge them; observed consequence of not bridging them is stale/broken agent definitions and exit-127 | That the recorded `installPath` equals the current store plugin, rewriting when it does not — which is exactly what `repairCodexPluginInstall` does, idempotently |

The pattern across all five: **the two mechanisms whose content is a file the
agent only reads are projected by links; the three whose target the agent also
writes are projected by re-assertion.** Instructions project by link — one
source, `home/common/agent-guidance/AGENTS.md`, reaches `~/.claude/CLAUDE.md`
through `programs.claude-code.memory` and `~/.codex/AGENTS.md` through
`home/common/agent-guidance/default.nix`, both as store symlinks. Skills project
by link too, shaped to the consumer's tolerance and guarded by a refusing
migration. Configuration, hooks and plugins cannot: they are re-asserted, by
`cp -f` for `~/.claude/settings.json`, an `awk` splice for Codex's TOML, and an
idempotent `jq` rewrite for the plugin install record. At **project** scope two links were
observed in the fleet, both in nodo, and only one of them is git-validated: its
committed `AGENTS.md` symlink, tracked at mode `120000`, so git stores the link
itself and a divergence would be a tracked change; and its
`.claude/settings.json` store symlink, which is **untracked** — `git
check-ignore -v` names `.gitignore:46:.claude/*` — so git neither records nor
validates it, and a fresh clone does not get it at all. An unbounded-depth
`find` over the three checkouts' `.claude` trees and root instruction files,
2026-09-02, located no other project-scope symlink outside the
`.claude/worktrees/` scratch trees in nodo and argus, whose links are all build
and dependency artifacts (`.devenv/`, `node_modules/.bin/`) inside checked-out
worktrees. So the projection git itself validates is the tracked instruction
symlink alone, and the property that makes it validatable is being **tracked**,
not being a link.

## Remaining gaps, under both readings of "prototype"

#60's summary says "remaining prototype gaps are listed in the artifact" without
naming the prototype, and the referent is unrecoverable (see
`## Unverified inheritance`, item 1). Both readings are covered; neither is
chosen.

### Reading (a): gaps in a projection prototype

Gaps a trial of the contained-source-with-thin-projections shape would still
face, given the 2026-09-02 evidence:

1. **Four of five mechanisms have no in-repository Codex target.** Only
   instructions can be projected to both agents by a file inside the
   repository. Skills, hooks and plugins have a Claude-side path and, in these
   three repositories, no Codex-side path at all. Configuration is the one that
   needs stating precisely: Codex *does* have per-project configuration, but it
   lives in the user-scope `~/.codex/config.toml` and is keyed by absolute
   path, so a repository cannot contain it, commit it, or carry it to another
   clone — a projection would have to write into the user's home directory
   rather than into the tree, which is a different operation with a different
   blast radius.
2. **Precedence between project and user scope is undetermined for every
   mechanism.** Nothing in the evidence base establishes whether a projected
   project-scope file wins, loses, or merges against the user-scope file of the
   same kind — so a projection cannot yet be shown to take effect.
3. **Project-scope symlink support is unobserved for Claude skills.** Both fleet
   checkouts contain zero symlinks under `.claude/skills`; the per-file-link
   evidence is user scope only. A projection prototype would have to establish
   this rather than assume it.
4. **"Validated" is unimplemented for the one non-symlink projection that
   exists.** argus's `CLAUDE.md` pointer can drift from `AGENTS.md` with nothing
   detecting it.
5. **Only one mechanism has an observed staleness reconciler.** Plugins have
   `repairCodexPluginInstall`; nothing comparable was observed for the other
   four, and nodo's vendored skills state outright that they "do NOT
   auto-update".
6. **The only cross-agent project config that exists is read by neither agent.**
   `.claude/skills.config.json` reaches both agents through
   `resolve-bindings`, i.e. through shared tooling — so cross-agent project
   configuration currently works by *bypassing* both native loaders, not by
   projecting into them.
7. **A read-only projection breaks the writing agent.** Any projection of
   configuration or hooks must be a writable materialisation; the failure mode
   of getting this wrong is recorded in-tree as a broken `/config` flow and
   sandbox.

### Reading (b): gaps for #79's adoption dry run

#79 asks to "Apply the approved adoption interface from #67 as a read-only
prototype against nix-config" and to "inventory current tracked and targeted
ignored agent-development surfaces" and test "current CLAUDE/native paths,
shared-platform source versus repo-local truth, tracked artifacts, and the
tracked-only cold-clone gate". Gaps that inventory hits, observed 2026-09-02:

1. **The dogfood target exposes the thinnest surface of the three.**
   nix-config's project scope is `CLAUDE.md`, `.claude/skills.config.json`,
   `.claude/plans/` and `.claude/specs/` — it has no `AGENTS.md`, no
   `.claude/settings.json`, and no `.claude/skills/`. A dry run there cannot
   exercise the skills, hooks or plugins projections at all, because the paths
   they would project into do not exist in that repository.
2. **"Shared-platform source versus repo-local truth" is, in nix-config,
   entirely shared-platform.** The agent-development system this repository
   authors lives in `home/common/agent-skills/`, `home/common/agent-guidance/`,
   `home/common/claude-code/` and `lib/agent-plugins.nix` — all of it user-scope
   installed behaviour. The repo-local half of the comparison is nearly empty
   here, so the dry run cannot exercise the conflict it is meant to surface.
3. **The tracked/ignored classification is different in every repository, so no
   single cold-clone gate holds across the fleet.** nix-config's `.gitignore`
   ignores `.superpowers/`, `.worktrees/` and `**/.claude/worktrees/` plus
   scratch-file patterns, and does not blanket-ignore `.claude/`; nodo's ignores
   `.claude/*` wholesale and re-includes exactly six entries
   (`skills.config.json`, `hints/`, `specs/`, `plans/`, `handoffs/`, `notes/`)
   @`7a3dab7e54`; argus's `.gitignore` names no `.claude/`
   path at all — its only near-match is `.claude-worktrees/` — so its
   `.claude/skills/` is tracked (`git check-ignore` reports it not ignored)
   @`20d6655223`. The
   consequence is concrete: nodo's 34 skills vanish from a cold clone while
   argus's three survive.
4. **A cold clone of nodo loses its project configuration and hooks entirely** —
   `.claude/settings.json`, `.claude/settings.local.json` and `.claude/skills/`
   are all under the ignored `.claude/*`, so the surfaces a dry run would
   inventory are exactly the ones a fresh checkout does not have.
5. **One tracked surface is a symlink, and a classification scheme has to say
   so.** nodo's `AGENTS.md` is tracked at mode `120000`. An inventory that
   records paths and contents without recording link-ness would report two
   independent instruction files where there is one body.
6. **The nodo half of this inventory is snapshot-bound**, 111 commits behind
   `origin/dev` as of 2026-09-02. Any of items 3-5 could read differently at
   that repository's current tip.

## Options recorded, not ranked

#60 forbids choosing the architecture, so these are the projection shapes
observed in the evidence base, each with its observed properties. They are
listed in no order of preference, and nothing here recommends one.

1. **Committed symlink at the repository root.** nodo `AGENTS.md` → `CLAUDE.md`,
   tracked at mode `120000` @`7a3dab7e54`. Observed properties: one body, two
   names; validated by git itself; survives a cold clone; confined to whole
   files at a fixed path.
2. **Authored thin pointer.** argus `CLAUDE.md` → prose reference to
   `AGENTS.md` @`20d6655223`. Observed properties: works for any consumer that
   reads text; costs one extra read; no observed drift detection.
3. **Whole-directory link shaped to the consumer's tolerance.**
   `~/.agents/skills/<name>` in `home/common/agent-skills/default.nix`.
   Observed properties: satisfies a consumer that rejects a symlinked
   `SKILL.md`; keeps the parent directory writable; requires a migration step
   when the previous layout left real directories behind.
4. **Materialised copy re-asserted by an idempotent activation.**
   `home.activation.claudeCodeSettings` (`cp -f` + `chmod u+w`),
   `home.activation.codexConfig` (`awk` splice of one key),
   `home.activation.repairCodexPluginInstall` (`jq` rewrite on mismatch).
   Observed properties: the only shape compatible with a file the agent writes
   to; canonical content is re-established per activation and runtime edits
   survive until then; each needs its own comparison logic.
5. **Vendored copy with recorded provenance and an explicit resync script.**
   nodo `.claude/resync-dotnet-skills.sh` @`7a3dab7e54`, pinning upstream
   commit `a7a744ce18951bf30a73769217abbd7165203be9`. Observed properties:
   works across repository boundaries and offline; copies bodies, which is what
   #60's question asks to avoid; states its own non-refreshing behaviour.
6. **Agent-neutral file read by shared tooling instead of by either agent.**
   `.claude/skills.config.json` + `home/common/agent-skills/scripts/resolve-bindings`.
   Observed properties: one file serves both agents with no projection at all;
   discovered by walking up from the working directory; degrades to defaults on
   a read or parse error; reaches an agent only through tooling that chooses to
   consult it.

## What this document does not decide

Per #60's own instruction — "do not choose the architecture" — and C60.5, this
document decides nothing. Specifically it does **not** decide:

- which of the six recorded options should carry any mechanism, nor whether one
  shape should carry all of them;
- what the single contained canonical source is, where it lives, or what it is
  called — that is #65's question ("What single project-local directory contains
  the complete agent-development system");
- the migration order or the acceptance evidence for adopting any of this —
  that is #71's question;
- whether the four mechanisms with no in-repository Codex target should be
  projected to Codex some other way — including whether a projection may write
  into user scope, as Codex's path-keyed `[projects."<path>"]` namespace would
  require — or be left Claude-only, or moved to shared tooling in the manner of
  `.claude/skills.config.json`;
- which of the two readings of "prototype" #60's original artifact meant. That
  is unrecoverable, and both are covered above rather than resolved.
