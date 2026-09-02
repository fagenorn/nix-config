# Release lifecycle seams across nix-config, Nodo and Argus: five release units inventoried field by field against #80's recording list

**Durability: committed** (Git owns this file's history from this commit forward.)
#80's instruction asked for exactly one `attached` findings file under
`.claude/specs/`; this is a `committed` one. The durability class changed
deliberately — the whole point of issue #115 is that the link in #80's resolution
comment resolves, which it cannot do while the file's durability is `attached`.

## Provenance

This document is a **re-derivation authored 2026-09-02 under issue #115**. It is not
the artifact that issue [#80](https://github.com/fagenorn/nix-config/issues/80)'s
resolution comment linked, and it does not recreate the 2026-08-20 original. That
original was **never committed** to any git ref:
`git log --all -- .claude/specs/2026-08-20-release-lifecycle-seams-research.md`
returned **zero commits** in this repository, verified at this task's base commit
`ad06512` on 2026-09-02. Run at or after the commit that adds this file, the same
command returns one — this file's own — so the base commit is the ref at which that
observation is checkable. The original's content is **unrecoverable**. Nothing below
is a recovered byte, and **no claim in this file may be cited as evidence of what
the original said.**

What this document is obligated to satisfy is the set of conclusions asserted in
#80's [resolution comment](https://github.com/fagenorn/nix-config/issues/80), plus
#80's own research question. Those obligations are enumerated as claim IDs in
`## Coverage of the resolution summary`. Every one is discharged below **from
primary sources read on 2026-09-02** — files in the three repositories and reads of
this machine's live release artifacts — never from the resolution summary, which is
the coverage floor and is not cited as a source anywhere in this document.

The filename's `2026-08-20` prefix is **#80's decision date** (the issue was opened
`2026-08-20T21:42:04Z` and closed `2026-08-20T21:51:13Z`), not this file's
authorship date. The authorship date is 2026-09-02. The two differ deliberately,
because the path is the one #80's resolution comment links and nothing may rename it.

Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked. This
document asserts repository-state and machine-state inventory — which release units
exist, what each names as a candidate and a release, what each publishes and where,
and what a reader can inspect — not a live-availability or blocking conclusion, so
the gate's two-timepoint standing-conclusion machinery does not apply. This follows
the precedent set by `.claude/specs/2026-08-16-codex-worker-death-research.md`.
Confidence is stated inline instead.

## Research question

#80's question, verbatim:

> Across nix-config, Nodo, and Argus, what release units, publication targets,
> activation mechanisms, success evidence, and rollback seams exist today?
>
> Use primary sources in the three repositories and the settled platform lifecycle
> in [#66](https://github.com/fagenorn/nix-config/issues/66) and
> [#71](https://github.com/fagenorn/nix-config/issues/71). For each distinct release
> unit, record:
>
> - candidate and release identity;
> - publication target, trigger, ordering, and immutability behavior;
> - activation mode, authority boundary, and restart/convergence behavior;
> - deployment success, running-identity, liveness, readiness, migration, and
>   product-smoke evidence;
> - durable or mutable data at risk;
> - rollback anchor, rollback action, reversibility limit, and retirement evidence;
> - partial-failure and re-entry behavior already implemented or documented.
>
> Separate facts shared by all projects from project-specific mechanics. Do not
> choose the architecture or invent a universal adapter. Use the `research` skill to
> write exactly one cited, `attached` findings file under `.claude/specs/`, then link
> it from this ticket.

## Coverage of the resolution summary

| ID (source) | Claim restated in one line | Source of the claim | Discharged by (heading in this document package) |
|---|---|---|---|
| C80.1 (summary) | Five materially different release-unit families exist across the fleet: Nix host generations; Railway API/admin services; digest-addressed GHCR engines with reconciler convergence; an Argus launchd daemon rooted in a checkout; locally signed Argus helpers. | #80 resolution comment | Seam roster |
| C80.2 (summary) | Identity and evidence differ accordingly — flake outputs and generations; Railway commit/deployment state; OCI digests plus current-digest heartbeats; local process/signature state. | #80 resolution comment | Identity and evidence, per release unit |
| C80.3 (summary) | Rollback ranges from retained generations and digest republishing to mutable platform redeploys and local file replacement. | #80 resolution comment | The rollback spectrum |
| C80.4 (question) | Per release unit, #80's full recording list — candidate and release identity; publication target, trigger, ordering, immutability; activation mode, authority boundary, restart/convergence; deployment success, running identity, liveness, readiness, migration and product smoke evidence; data at risk; rollback anchor, action, reversibility limit, retirement evidence; partial failure and re-entry behaviour. | #80 research question | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Release-unit mechanics, project by project |
| C80.5 (question) | Facts shared by all three projects are separated from project-specific mechanics. | #80 research question | Facts shared by all three projects |
| C80.6 (question) | The architecture is not chosen and no universal adapter is invented. | #80 research question | What this document does not decide |
| A80.1 (#115) | The fail-closed `PreToolUse` permission guard is an enforcement seam: inside the agent's own execution path it is the only machine enforcement of release policy, adjudicating before the action runs — bounded against the forge-side protection it consults rather than replaces. | issue #115 (added claim) | Enforcement seam — the fail-closed `PreToolUse` permission guard |
| A80.2 (#115) | Five independent durable state systems, each recorded with a locator, an identity, evidence and a rollback: the attempt-lifecycle ledger, the sdd plan ledger, the review-package store, ship-release's own state file, and the tracker-native wayfind state. | issue #115 (added claim) | Durable-state seams |
| A80.3 (#115) | Both surviving prototype artifacts carry an immutable, reachable commit reference, each with its `origin` branch, its directory and the command that retrieves it. | issue #115 (added claim) | Immutable prototype references |
| A80.4 (#115) | Issue #86's comments say its prototype was not pushed and lives only in a local worktree; `origin` carries that branch at that exact sha, and the correction is recorded here rather than on the tracker. | issue #115 (added claim) | Correction to #86's resolution comment |

## Unverified inheritance

Claims inherited from #80 that this document did not re-verify against a primary
source, and observed claims whose truth is bounded. Silence is not permitted, so
each is named.

1. **"Five" is an inherited corpus boundary, not a re-derived exhaustive count.**
   Each of the five families #80 names is re-derived below from primary sources.
   This document did **not** sweep the three repositories for a sixth family, so it
   asserts nothing about completeness. Release paths seen while reading and
   deliberately left outside this inventory: Nodo's Render-hosted landing
   (`render.yaml`, `autoDeploy: false`); the four sibling engine image workflows
   (`browser-mcp-image.yml`, `cli-mcp-image.yml`, `phone-mcp-image.yml`,
   `egress-gateway-image.yml`), which the reconciler workflow's own comments
   describe as the same shape as the one inventoried here; Nodo's Supabase
   auth-config and Cloudflare steps; and the api's `Nixpacks`/Dockerfile image
   itself, which Railway builds and which this document treats as internal to the
   Railway unit. Any of these could be argued into or out of "release unit"; #80's
   summary drew the line at five and this document keeps that line rather than
   redrawing it.
2. **#66 and #71's settled platform lifecycle is cited as a decision, never as an
   observation.** #80's question directs the researcher to use it. This document
   inventories what the three repositories do today; it does not claim any running
   system implements #66 or #71.
3. **Provider behaviour is recorded from Nodo's own runbooks.** Statements about
   Railway's silent rollback, its rollover and grace windows, its per-replica log
   rate limit, and GHCR's package ACL are read out of files in
   `/Users/anis/Projects/nodocom` (`docs/operations/deploy.md`,
   `docs/operations/reconciler.md`, `docs/operations/self-serve-cutover.md`). Those
   files are a primary source for **what that project asserts and operates on**;
   they are not an independent observation of the provider, and this document made
   no API call to Railway, GHCR, Supabase or Cloudflare.
4. **Every Nodo and Argus fact is snapshot-bound.** Both checkouts were read once,
   read-only, at the `HEAD`s in `## Observation basis`. Neither was fetched,
   checked out or written. A later commit in either repository can change any
   statement below.
5. **The Nix generation observations are from one host.** `/nix/var/nix/profiles/`
   was read on this machine, which `flake.nix` configures as
   `darwinConfigurations.mbp`. `nixosConfigurations.anis-desktop` was not observed;
   nothing below asserts a generation count or an active generation for it.
6. **No release was performed.** This document ran no `just switch`, no deploy, no
   `daemon install` and no publish. Every activation, evidence and rollback field is
   derived from the declaration that governs it plus, where noted, a read of an
   artifact a past activation left behind.

## Observation basis

| Repository | Path | Observed `HEAD` | Branch | Behind its own integration ref | Working tree | Observed |
|---|---|---|---|---|---|---|
| nix-config | `/Users/anis/tmp/nix-config/.worktrees/worktree-issue-115-recover-wayfind-research-findings` | `ad06512d686357dd2e044f6f20a146d2d9f40a16` | `worktree-issue-115-recover-wayfind-research-findings` | n/a — feature branch, not an integration ref | clean at task start | 2026-09-02 |
| Nodo | `/Users/anis/Projects/nodocom` | `cc98ed0e65d66a01895f53659e291303d8e475f3` | `dev` | 0 commits behind `origin/dev` | clean (`git status --porcelain` empty) | 2026-09-02 |
| Argus | `/Users/anis/Projects/argus` | `20d6655223e9497c2668f67dd016e1111b3a78cb` | `main` | 0 commits behind `origin/main` | clean (`git status --porcelain` empty) | 2026-09-02 |

Commands, run once each in the named directory:
`git rev-parse HEAD`, `git rev-parse --abbrev-ref HEAD`,
`git status --porcelain`, `git rev-list --count HEAD..origin/<ref>` and
`git rev-list --count origin/<ref>..HEAD`. Both fleet checkouts returned `0` in both
directions, and `git rev-parse origin/<ref>` returned the same sha as `HEAD`.

**What "0 commits behind" does and does not mean.** The count is measured against
the **local remote-tracking ref**, which reflects the last fetch performed outside
this task; no task refreshed a checkout, so it is not a statement about the current
tip on GitHub. The tip commit dates of those refs, from
`git for-each-ref --format='%(refname) %(committerdate:iso8601)'`, are
`refs/remotes/origin/dev 2026-09-02 15:29:42 +0100` (Nodo) and
`refs/remotes/origin/main 2026-08-29 11:52:37 +0100` (Argus).

**Re-observed later the same day.** The second authoring pass under issue #115 re-ran
the same commands after the sections below were written. Both checkouts' `HEAD`s are
unchanged — Nodo `cc98ed0e65d66a01895f53659e291303d8e475f3`, Argus
`20d6655223e9497c2668f67dd016e1111b3a78cb` — and both working trees are still clean,
so every fleet citation in this document still resolves at the ref it names. One
figure in the table above has moved. `git -C /Users/anis/Projects/nodocom rev-list --count HEAD..origin/dev`
now returns **12**, not `0`: the local `refs/remotes/origin/dev` has advanced to
`2236cd5fd93f64569d0f3e040bbf61f213f15ad4`, tip date `2026-09-02 20:55:40 +0100`,
since the table was written. Argus is unchanged at 0 in both directions, its
`origin/main` tip still `2026-08-29 11:52:37 +0100`. This pass performed no `fetch`,
`checkout`, `stash` or write in either repository, and does not determine what
refreshed that tracking ref. The table's `0` stands as the true as-of-writing
observation; this paragraph is the reconciliation, and nothing is restated on the
strength of the newer ref — no Nodo path is cited against `2236cd5f`.

Both fleet checkouts were read only. Nothing in this task wrote, fetched, checked out
or stashed in either. nix-config claims are cited repo-relative; the worktree `HEAD`
is recorded so every observation here is re-runnable at a named ref. Every fleet
citation below names its repository and a repo-relative path, and every one resolves
at Nodo's HEAD `cc98ed0e65d66a01895f53659e291303d8e475f3` or at Argus's HEAD
`20d6655223e9497c2668f67dd016e1111b3a78cb`, both observed 2026-09-02; no fleet path
is cited against any other ref.

Three reads in this document are of **live artifacts on this machine**, not of a
repository, because a declaration cannot witness what a past activation actually
left behind: `/nix/var/nix/profiles/`,
`~/Library/LaunchAgents/dev.argus.daemon.plist`, and
`~/Library/Application Support/Argus/Argus.app`. Each is cited with the command that
read it at the point it is used.

## Terminology guards

Three words in #80's subject matter carry two meanings each in this fleet's
tracker. This document fixes one meaning for each and never uses the other silently.

- **state.** #82 ("Define the canonical release transaction, identity, and durable
  state model") and #88 ("Define release success evidence and terminal truth") use
  *state* for a **release's** own durable state machine and its sealed
  `terminal_receipt`. This document uses *state* for neither: where it says state it
  means an operational store a running system keeps — Nodo's
  `/etc/nodo-reconciler/state.conf`, Argus's `home/daemon/state.db`, a Railway
  deployment record. No release-transaction state machine exists in any of the three
  repositories at the observed `HEAD`s; #82 is a decision, not an implementation.
- **identity.** #88 requires evidence to bind an "exact expected subject" and to
  prove "running identity" — the **subject identity** sense: *is the thing running
  the thing we released?* A record's key — a deployment id, a generation number, a
  launchd label — is the other sense. Both appear below, and
  `## Identity and evidence, per release unit` states which sense each row uses.
- **seam.** Used only through the three classes declared in `## Seam roster`. The
  five release units are the only rows classed as release units; no other row in
  that roster is a release unit and nothing below implies otherwise.

One further note, so no reader infers a dependency: `.superpowers/` is a
**historical directory name** used in this repository for pipeline state and
artifact locations. There is no Superpowers input, patch, marketplace or plugin in
this repository.

## Seam roster

One roster, three declared classes. Every row's `Detail` cell names, character for
character, a heading in this same document package that holds that row's fields: a
heading in this root is named alone, and a heading in an evidence member is named
`<member repo-relative path> § <heading text>`.

| Seam | Class | Detail |
|---|---|---|
| Nix host generations (nix-config) | release-unit seam | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Nix host generations (nix-config) |
| Railway api and admin services (Nodo) | release-unit seam | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Railway api and admin services (Nodo) |
| Digest-addressed GHCR engines with reconciler convergence (Nodo) | release-unit seam | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Digest-addressed GHCR engines with reconciler convergence (Nodo) |
| Argus launchd daemon rooted in a checkout | release-unit seam | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Argus launchd daemon rooted in a checkout |
| Locally signed Argus helpers | release-unit seam | .claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md § Locally signed Argus helpers |
| The fail-closed PreToolUse permission guard |enforcement seam| Enforcement seam — the fail-closed `PreToolUse` permission guard |
| The attempt-lifecycle ledger (workflow-state) |durable-state seam| The attempt-lifecycle ledger (workflow-state) |
| The sdd plan ledger |durable-state seam| The sdd plan ledger |
| The review-package store (published delivery detail) |durable-state seam| The review-package store |
| The ship-release state file |durable-state seam| The ship-release state file |
| The wayfind state on the tracker |durable-state seam| The wayfind state on the tracker |

### Field definitions

The `Class` column declares which recording contract a row obeys. The five release
units carry #80's full recording list, answered field by field in the detail section
named beside them, and a field with no answer in the live tree says so explicitly.
Rows in the two added classes — `enforcement seam` and `durable-state seam` — instead
record four fields, written as four label lines in that row's own detail section:
`Locator:`, `Identity:`, `Evidence:`, `Rollback:`. They mean:

- **locator** — where the state or the enforcement physically lives, written as a
  path template whose root is named explicitly: a caller-supplied repository root,
  the primary checkout, a feature worktree, `$TMPDIR`, or the tracker itself.
- **identity** — what names one record and makes two records distinct.
- **evidence** — what a reader inspects to know that row's current truth.
- **rollback** — what undoes or supersedes a record, and the reversibility limit
  where nothing does.

## Facts shared by all three projects

Five properties hold across all five release units. Each is stated with its
per-unit disposition, so a reader can refute any one of them in one cell rather
than having to take the row on faith. Columns are the five units in roster order.

| Shared property | Nix generations | Railway services | GHCR engines | Argus daemon | Argus signing |
|---|---|---|---|---|---|
| **S1 — a person starts it.** Nothing releases on a timer: `grep -l 'schedule:' .github/workflows/*.yml` matches no file in Nodo and none in Argus, and nix-config's one scheduled trigger runs `Flake Checker` only, which neither builds nor deploys. | `just switch`, run by hand | push to `main` matching `watchPatterns`, `scripts/deploy.sh`, or `railway up` | push to `main` (or `workflow_dispatch`) on the engine path | `daemon install` / `daemon restart` | a build command (`wa-build`, `build-wkfetch.sh`, `notifyd/build.sh`, or first devenv shell entry) |
| **S2 — build and activation are separate, with a nameable artifact between.** | `./result` → the realised store path | the image Railway builds from the Dockerfile | `ghcr.io/<owner>/<image>@sha256:…` | the generated plist plus the checkout it points at | the compiled file on disk, then its signature |
| **S3 — no product smoke runs anywhere in the release path.** Each unit's *Product smoke evidence* field below says "none", and this row is that field's per-unit summary. | none; command exit status is the whole signal | none after the platform healthcheck, which the api's own runbook calls a pure liveness probe running no dependency checks | none for the engine release itself. The closest thing in the fleet sits inside this unit's on-device activation — a browser roll commits only after `/healthz` reports Chrome healthy at the candidate image's runtime version — and it proves a sibling component came up at the right version, not that a product flow works | none; CI is hermetic and never installs the daemon | none |
| **S4 — *choosing* which prior release to return to is a human act.** One unit also has an unattended revert, and that revert makes no choice. | a human, with no command declared to help | a human picks the deployment to `railway redeploy`, or reverts the merge | a human re-publishes an archived digest. The supervisor's crash-loop revert is unattended, but it selects nothing — it takes the single `fallback_digest` it recorded | a human runs `daemon uninstall`, or moves the checkout back and re-installs | a human rebuilds and re-signs |
| **S5 — no unit carries a semantic version or a human-assigned release number.** Every identity is content-derived, machine- or provider-assigned, or a constant label. | content hash, plus a machine-assigned monotonic generation number | provider-assigned deployment id, plus `commitHash` | content-derived OCI digest; the `Version` field the publish call sends is a 12-character git sha, not a version | a constant launchd label, `dev.argus.daemon` | a constant code-signing identifier, `dev.argus.*` |

Two properties that read like shared facts are **not** shared, and are recorded here
so they are not mistaken for one. *Whether the target set is closed at release time*:
four of the five release onto a set that is named and fixed before the release starts
— one machine for the Nix unit, the two named services for Railway, this machine's
plist and bundle for the Argus daemon, five named paths for Argus signing — while the
GHCR unit publishes to a device fleet whose membership is not fixed at publish time
and whose members converge on their own 30-second ticks. "The release landed" is
therefore a per-member question in exactly one of the five and a single question in
the other four. *Publication remoteness*: only the GHCR unit publishes an artifact to
a remote registry; the Nix unit publishes into the local `/nix/store`, Argus's two
units publish onto the local filesystem, and Railway's build artifact is not
addressable from the repository at all.

## Release-unit mechanics, project by project

The five units' field-by-field answers to #80's recording list are bulk evidence and
live in this package's evidence member,
`.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md`,
under this same heading. That member holds, in this order, `### Nix host generations
(nix-config)`, `### Railway api and admin services (Nodo)`, `### Digest-addressed
GHCR engines with reconciler convergence (Nodo)`, `### Argus launchd daemon rooted in
a checkout` and `### Locally signed Argus helpers`: every field of #80's recording
list answered once per unit, and a field with no answer in the live tree saying so
and saying why. It carries records only. Everything those records are reasoned into
stays here — `## Facts shared by all three projects` above,
`## Identity and evidence, per release unit` and `## The rollback spectrum` below,
and `## What this document does not decide` last.

## Identity and evidence, per release unit

C80.2's contrast, one row per seam. The **identity sense** column applies the
terminology guard above: *subject* is #88's expected/running sense, *record* is a
store or provider key.

| Seam | What names a release | Identity sense used | What a reader inspects for current truth |
|---|---|---|---|
| Nix host generations (nix-config) | a content-addressed store path, plus a generation number in the system profile | record — the generation number is a profile key; nothing in the repository asserts a subject | `readlink /nix/var/nix/profiles/system`, then `readlink` on that link. No repository command does this. |
| Railway api and admin services (Nodo) | a provider-assigned deployment id, attributed to a commit | record, with a **known-weak** subject binding: `latestDeployment.commitHash` names the latest tagged commit on `main`, not necessarily the built one | `railway status --json` for `latestDeployment.status`, `railway deployment list` for the chronology, `GET /health` for liveness — and the runbook insists a 200 may be the *old* build answering |
| Digest-addressed GHCR engines with reconciler convergence (Nodo) | an immutable OCI manifest-list digest | **subject** — the only one of the five where a running subject is compared against a declared desired one: the heartbeat reports the digest the device is running, against the digest the api desires | per-component heartbeat `currentImageDigest` vs `device_vps_components.desired_image_digest`, plus the supervisor heartbeat's `reconcilerAlive`/`failCount`/`fallbackDigest` |
| Argus launchd daemon rooted in a checkout | a bare launchd label, `dev.argus.daemon` | record — and the record is a constant, so it names the *slot*, never the release in it | `daemon status`: plist present, plist still pointing at this repo, `launchctl print` pid, per-job `last_success` from the state DB |
| Locally signed Argus helpers | a code-signing identifier plus its designated requirement | subject in principle, on-disk only in practice: the requirement identifies the artifact, and nothing checks a running process against it | `codesign -dv <path>`, as `tests/daemon/binaries-signed.test.ts` runs it — darwin-only, and only when a codesigning identity exists |

Read against those rows, three things follow, and each is refutable from the row it
rests on. **In these five, the strength of a release identity and the strength of its
running-identity evidence move together.** The GHCR unit is content-addressed and is
the only one of the five whose evidence compares a *running* subject against a
*declared desired* subject — `currentImageDigest` against `desired_image_digest`;
the Argus daemon is addressed by a constant label and its evidence cannot express
that comparison at all. **Two units can name a release but never check it.** The Nix
unit's active generation is readable on the machine yet no repository command reads
it, and the signing unit's requirement is inspectable on disk but never against a
live process. **And exactly one of the five identities is assigned by a provider** —
Railway's deployment id; the GHCR digest is computed from content rather than handed
out by the registry — which is why Railway's own runbook has to spend a section
warning that its identity field can disagree with what is serving.

## The rollback spectrum

C80.3's range, ordered by how much of a rollback the unit can actually perform
without a human, and paired with what bounds it. Every claim in a row is discharged
by the correspondingly-named field in that unit's section above.

| Seam | Anchor | Who acts | What bounds it |
|---|---|---|---|
| Nix host generations | strongest — 237 superseded generations retained, contiguous, observed | nobody: the repository declares **no** rollback command at all | the generation covers only what Nix owns; zapped Homebrew casks, the always-latest `palmier-pro` build and runtime writes to `~/.claude.json` are outside it |
| Digest-addressed GHCR engines | immutable digests in the registry, plus one `fallback_digest` on each device | the device itself, automatically, on a 3-strike crash loop; or an operator re-publishing an archived digest | exactly one step of depth on-device; when active and fallback are the same broken image the device waits 300 s for a server-supplied `recommendedFallbackDigest` |
| Railway api and admin services | the previous successful deployment, retained by the provider | an operator: `railway redeploy`, or revert the release merge | redeploying an older image does not un-apply a migration that already ran — the documented failure shape is old code against a new schema |
| Argus launchd daemon | the git checkout | an operator: `daemon uninstall`, or move the checkout back and re-install | forward-only state-DB migrations, which uninstall does not touch; an older checkout opens a newer DB unchanged and runs against it |
| Locally signed Argus helpers | none — nothing prior is retained | an operator, by rebuilding from older sources | there is nothing to roll *back to*; and an invalidated keychain grant is restored only by a human re-approving an OS prompt |

The spectrum is not a quality ranking, and reading it as one would be the mistake the
rows themselves refute. The unit with the strongest anchor (Nix) has **no** action
declared, while the unit with the weakest per-device anchor (one prior digest) is the
only one that rolls back **without a human at all**. What actually varies
independently is three things: whether a prior release is retained, whether anything
can select it, and whether selecting it restores the whole world or only the part
that unit owns. Each of the five rows names its own bound in the last
column, and none of the five anchors covers everything its release touched.

## Enforcement seam — the fail-closed `PreToolUse` permission guard

One row, one class. This repository generates a Python program into the Nix store
and wires it as a `PreToolUse` hook over the `Bash` tool; it adjudicates four
lifecycle verbs *before* the agent's shell runs them. Not a release unit: it
publishes nothing, activates nothing, stores nothing.

**Locator:** `home/common/claude-code/default.nix:56-863` builds
`claude-bash-lifecycle-guard` with `pkgs.writeTextFile` (`executable = true`,
`destination = "/bin/claude-bash-lifecycle-guard"`), and `:947-958` wires the
resulting store path as the sole `hooks.PreToolUse` entry, `matcher = "Bash"`,
`timeout = 30`. Two roots, and deliberately neither is one of the five
`### Field definitions` enumerates, because this seam stores no state: the
declaration lives in **this repository's checkout**, cited at the worktree `HEAD` in
`## Observation basis`, and the activated copy at the immutable `/nix/store` path
this machine's `~/.claude/settings.json` names — read here 2026-09-02 as
`/nix/store/966h4bf8mkvmj9984gblpiybgg6w7l8b-claude-bash-lifecycle-guard/bin/claude-bash-lifecycle-guard`.

**Identity:** the *record* sense, and the record is that store path —
content-addressed, so a changed guard is a different path. The guard keeps no
identity of its own: `main()` (`:865-908`) reads one hook payload from stdin and
returns an exit status, writing nothing anywhere. Two adjudications are
distinguished only by the `(command string, cwd, live forge state)` triple each is
handed. In #88's *subject* sense the guard has no identity to bind and asserts none.

**Evidence:** the live `~/.claude/settings.json` on this machine — not the module,
which owns only some of that file's keys. Read 2026-09-02 with
`jq -c '{hooks: (.hooks|keys), n: (.hooks.PreToolUse|length), defaultMode: .permissions.defaultMode, allow: (.permissions.allow|length)}' ~/.claude/settings.json`,
which returns `{"hooks":["PreToolUse"],"n":1,"defaultMode":"auto","allow":18}`: one
hook event, one matcher block (`"Bash"`) holding one command — the store path above,
`timeout` 30. So here the guard is not merely the only `PreToolUse` hook, it is the
only hook of **any** event. In the repository the evidence is
`tests/test_claude_permission_guard.py` — 629 lines, 30 test methods by
`grep -c '    def test_' tests/test_claude_permission_guard.py` — whose
`EXPECTED_ALLOW` (`:11-19`) pins those same 18 entries in order, and whose fake `gh`
exits 64 whenever `GITHUB_TOKEN` or `GH_TOKEN` is visible in its environment
(`:30-36`), so every merge-path test doubles as the token-scrubbing assertion.

**Rollback:** a decision is not a record, so there is nothing to roll back — a
blocked command did not run, and an allowed one is the agent's to undo by ordinary
means. What *is* rollable is the guard itself, and only through a release unit
inventoried above: the hook reaches this machine inside a Nix system generation, so
reverting it is the roster's `Nix host generations (nix-config)` row and inherits
that row's bound. Reversibility limit: the guard cannot un-block. Between rebuilds
there is no in-band way to disable, weaken or defer it (see *no defer path* below),
so an adjudication that wrongly blocked a correct command is reversed only by
editing `default.nix` and rebuilding, or by a human running the command outside the
agent's Bash tool, which this hook does not cover.

### The four adjudicated verbs and the exact form each is validated into

`GUARDED_LITERALS` and `GUARDED_TOKEN_LITERALS` (`default.nix:92-105`) declare
exactly four, ordered so the first match at a token wins and no sequence is a prefix
of another: `git push`, `gh pr create`, `git branch -d` and `gh pr merge`. The exact
form each validates into — argv shape, character and ref-name rules, and the source
line of every clause — is a field-by-field record and lives in this package's
evidence member, under `.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/enforcement-guard-mechanics.md § The four adjudicated verbs and the exact form each is validated into`.

**The authorized-owner set.** `default.nix:33-36` declares
`authorizedOwners = [ "fagenorn" "elevenyellow" ]` — two owners — spliced into the
generated program as `AUTHORIZED_OWNERS` at `:74`. Membership is the whole of the
ownership test (`ownership_problem`, `:540-547`): the owner segment of the slug
parsed from `git remote get-url origin` (`detect_repository`, `:466-499`) must be in
that set, and an unknown repository is refused by the same branch as an unauthorized
one. Push, PR creation and merge each require it (`:665-667`, `:691-693`,
`:734-736`); branch deletion does not, and the module says so (`:31-32`).

**The per-repository integration-base map.** `:52-54` declares
`integrationBases = { "elevenyellow/nodocom" = "dev"; }` — a single entry — spliced
as `INTEGRATION_BASES` at `:75`. `authorized_bases` (`:549-562`) returns the
repository's default branch plus its declared integration branch when it has one.
Declaring a branch there does two things at once, and the module states both
(`:45-51`): it widens which branch a guarded PR may target, **and** it waives the
merge's forge-protection demand for that branch, because an integration branch is
the development-pace branch, deliberately unprotected, whose CI gate lives in the
shipping flow's wait-for-checks. The waiver is narrow: `validate_merge` returns 0
without any protection lookup only when the PR's actual base equals that declared
integration base **and** that base is not the repository's default branch
(`:822-828`). A default branch keeps the full demand even if it is ever also
declared as an integration base.

**What a merge onto a default-branch base is checked against, live.** Three forge
facts, all of which must hold: (1) an **open** PR whose `baseRefName` is one of the
authorized bases and whose `url` starts with `https://github.com/<detected slug>/pull/`
— `gh pr view <n> --repo <slug> --json state,baseRefName,url` (`:762-775`) piped into
one `jq -e` predicate (`:781-800`); (2) **at least one required status context** on
the base the PR actually targets; and (3) **`enforce_admins` enabled** on that same
base. (2) and (3) are one `gh api repos/<slug>/branches/<base>/protection` call
(`:831-838`) and one predicate,
`(.required_status_checks.contexts | length) > 0 and .enforce_admins.enabled == true`
(`:846-854`). The base is read back out of the PR payload, not assumed (`:810-814`),
so protection is demanded of the branch actually being merged into.

**The lookups run without the shell's tokens.**
`GH_ENV_TOKEN_NAMES = ("GITHUB_TOKEN", "GH_TOKEN")` (`:83`); `gh_lookup_env()`
(`:165-170`) copies `os.environ` and removes both; and every `gh` child in
`validate_merge` is spawned with `env=gh_lookup_env()` (`:774`, `:837`). The module
records why (`:76-82`): the harness exports a fine-grained `GITHUB_TOKEN` that `gh`
prefers over the keyring credential and whose reach is narrower — it cannot see
every authorized owner's org — so validation would otherwise observe less of GitHub
than the command it is validating will. A machine with no keyring auth fails closed
at the lookup rather than proceeding.

**The fail-closed classes.** Everything the segment tokeniser cannot vouch for is
refused rather than waved through, because the parser only approximates bash and
where the two might disagree the guard fails closed. Eight classes block:
an unparseable command; a segment that cannot be tokenised; shell source handed to
an evaluator (`eval`, `sh`, `bash`, `zsh`, `dash`, `ksh`); a guarded verb sitting
outside a command position, such as an argument to `xargs` or `timeout`; an
unresolvable repository or default branch; a child timeout; non-zero or unparseable
child output; and any unexpected exception at all, which the top-level handler
turns into exit 2. A mention that is one quoted token, a heredoc body, and a comment
are each not a command and none triggers the guard. The enumeration, with the source
line of every branch, is in the evidence member under
`.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/enforcement-guard-mechanics.md § Fail-closed classes of the permission guard`.

**There is no defer path.** Once `guarded_operations` names a verb, the dispatch
loop in `main()` (`:887-908`) either validates it and continues or returns a
blocking status; no branch hands the command back to the settings allowlist
unexamined. The broad `Bash(git push:*)`, `Bash(gh pr create:*)`,
`Bash(git branch -d:*)` and `Bash(gh pr merge:*)` entries in that 18-entry allow
list are therefore usable only through the guard, and bare `Agent` stays inert under
`defaultMode = "auto"` (`:960-964`).

**The bound on "only machine enforcement" (D14).** The claim here is the *in-path*
one: inside the agent's own execution path this guard is the only machine
enforcement of release policy, and it adjudicates before the action runs. It is
**not** the only machine enforcement that exists, and stating it unbounded would
contradict this repository's own configuration. `.github/branch-protection.json:2-6`
declares `required_status_checks.contexts` `["Nix Eval"]` and `enforce_admins`
`true` for `main`; `.github/workflows/ci.yaml:49-60` defines the `Nix Eval` job,
which evaluates `nixosConfigurations.anis-desktop` and is skipped on the daily cron
(`:53`). That protection is live, not merely declared:
`gh api repos/fagenorn/nix-config/branches/main/protection`, run 2026-09-02 with
`GITHUB_TOKEN` and `GH_TOKEN` unset, returned
`{"contexts":["Nix Eval"],"enforce_admins":true,"strict":false}`. This is
**forge-side** enforcement: it runs on GitHub, after the agent's command has left
this machine, and it refuses a merge — `gh pr merge --admin` included — until
`Nix Eval` is green. The guard does not replace it; the guard *consults* it, and
checks (2) and (3) above are exactly that consultation. Neither subsumes the other:
the guard can refuse a command the forge would have accepted, and the forge can
refuse a merge the guard allowed.

## Durable-state seams

Five independent state systems, one row each. None is a release unit: none
publishes an artifact, activates anything, or has a candidate. They are the
*operational stores* the terminology guard above reserves the word **state** for —
not #82's release state machine and not #88's sealed `terminal_receipt`, which
`## Terminology guards` records as absent from all three repositories at the observed
`HEAD`s. That absence is inherited from that section, not re-swept here.

All five paths below use the literal directory name `.superpowers/`. That name is
**historical**: there is no Superpowers input, patch, marketplace or plugin in this
repository, and no reader should infer one. The directory is git-ignored at
`.gitignore:8`, verified 2026-09-02 by
`git check-ignore -v .superpowers/workflows/x/state.json`, which answers
`.gitignore:8:.superpowers/`. Nothing under it is in any commit, so for every seam
below git holds **no prior version to restore**; the tracked `.gitignore` is the
backstop precisely because `.git/info/exclude` is machine-local. Live observations
here were taken 2026-09-02 in the **primary checkout**, `/Users/anis/tmp/nix-config`,
not in the worktree this document is written from.

### The attempt-lifecycle ledger (workflow-state)

**Locator:** `<caller-supplied repository root>/.superpowers/workflows/<run_id>/state.json`,
with `state.lock` beside it. The root is supplied on every call: `--repo-root` is
required by every subcommand (`home/common/agent-skills/scripts/workflow-state.py:2983-2986`,
`:2992-3041`), and `from-issue` binds it once as `ledger_repo_root` and forbids substituting
another (`home/common/agent-skills/skills/from-issue/SKILL.md:25-31`).
`resolve_repo_root` (`workflow-state.py:629-636`) refuses a root that is missing, a
symlink or not a directory; `ensure_workflows_directory` (`:639-644`) creates
`.superpowers/` and `.superpowers/workflows/`; `workflow_paths` (`:646-654`) appends
`<run_id>/`. It is never derived from the process cwd. Handoffs sit under
`.superpowers/workflows/<run-id>/handoffs/` (`from-issue/SKILL.md:218`). The request
and result files carrying a transition *into* the ledger are in no working tree at
all — absolute temporaries beneath `${TMPDIR:-/tmp}` (`from-issue/SKILL.md:50`,
`:103`, `:281-283`), the result file removed under an unconditional cleanup on every
outcome. Live: `ls -1 .superpowers/workflows/` lists **18** run directories (`ls -A1`
lists **22** — those plus a `.gitignore` holding `*` and three `.direct-<n>.lock`
files), and `ls -1 .superpowers/workflows/run-20260902-115-130/` returns
`handoffs`, `state.json` and `state.lock`.

**Identity:** the *record* sense, at two levels. A run is named by `run_id`, a
caller-chosen string matching `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$` (`:47`) that is
also the directory name, so two runs are distinct exactly when their `run_id`s
differ. Within a run, an attempt's current launch is named by `action_id`, rendered
`issue:attempt:launch` from the attempt's own ordinals (`render_action_id`,
`:1541-1543`; `ACTION_ID_PATTERN`, `:52-54`). This is not #88's *subject* identity:
`action_id` names the *record* of a launch, and `check-launch` (`:3038-3042`, called
as `workflow-state check-launch --repo-root <root> --run-id <id> --action-id <issue:attempt:launch>`,
`from-issue/SKILL.md:451`) exists precisely because a predecessor's `action_id` goes
stale once the ledger admits a successor — which is why a still-running predecessor
must re-validate before any forge write.

**Evidence:** `state.json` itself, and `check-launch` for the launch question. Live
read of `.superpowers/workflows/run-20260902-115-130/state.json`: `schema_version`
2, issue 115 carrying **two** attempts — attempt 1 with four `launches` and
`launch_kind` `resume`, attempt 2 with one and `launch_kind` `fresh` — and every
launch in **both** recording the same `worktree`,
`/Users/anis/tmp/nix-config/.worktrees/worktree-issue-115-recover-wayfind-research-findings`.
That sharing is deliberate: the lifecycle hands a retry its predecessor's worktree
and branch so the successor resumes the task ledger seamlessly.

**Rollback:** nothing in the tool removes or reverses a record. The subparsers are
exactly `init-run`, `control`, `direct-owner`, `finish`, `suspend`, `progress` and
`check-launch` (`:2988-3042`) — seven, none of which deletes a run, an attempt or a
launch. Each transition is published by `os.replace` of a same-directory temporary
that was `fsync`ed first (`atomic_write_state`, `:899-917`) under an exclusive
`flock` on `state.lock` (`:937-939`), so a crash leaves the old record or the new
one, never a half-written third. Reversibility limit: the only reversal is
out-of-band — a human deleting `<repo-root>/.superpowers/workflows/<run_id>/`.
Nothing in this repository prunes it, and the tree being git-ignored, no committed
version exists to restore.

### The sdd plan ledger

**Locator:** `<primary checkout>/.superpowers/sdd/<bucket>/<plan-basename>/`, where
`<bucket>` is `primary` for the primary checkout and `wt-<worktree-name>` for a
linked worktree. `home/common/agent-skills/skills/sdd/scripts/sdd-workspace` is the
single source of that path: the slug is `basename "$plan" .md` (`:54`), the checkout
identity is decided *before* the primary is derived, from `git rev-parse --git-dir`
against `--git-common-dir` (`:58-84`), and the path is assembled at `:87-88`. It is
deliberately never rooted at the process cwd — that would nest a second ledger
inside a linked worktree (`:6-11`; `sdd/SKILL.md:26`). Live: this task's ledger is
`/Users/anis/tmp/nix-config/.superpowers/sdd/wt-worktree-issue-115-recover-wayfind-research-findings/2026-09-02-issue-115-recovered-wayfind-findings/`,
and `ls -1 /Users/anis/tmp/nix-config/.superpowers/sdd/` returns two buckets, both
`wt-`-prefixed — no `primary` bucket exists on this machine today.

**Identity:** the *record* sense: the pair `(bucket, plan basename)`. Two checkouts
executing one plan can never share a ledger, their buckets differing; two *attempts
on one issue* deliberately do share one, because the lifecycle hands the retry the
predecessor's worktree, so the bucket name is the same (`sdd-workspace:12-22`).
Within a ledger a task is named by its ordinal in `progress.md`'s
`Task <N>: complete` lines (`sdd/SKILL.md:27`), and a diff-review package by its
range, `review-<base7>..<head7>.json` (`review-package:770`).

**Evidence:** `<workspace>/progress.md`. Its first line names the plan file; a task
is done exactly when a `Task <N>: complete` line exists for it, and a ledger naming
a different plan is not yours — leave it and start fresh (`sdd/SKILL.md:27`). Live
sweep of this plan's own workspace, taken while this section was being written and
therefore **before** this task's report and its review package were added to it:
`ls -1 <workspace> | wc -l` returned **43** — `progress.md`, `retained-detail.json`,
**6** `task-N-brief.md`, **5** `task-N-report.md`, and **15** `review-<range>.json`
each with a matching `.shards` directory (`ls -1 <workspace>/review-*.json | wc -l`
and `ls -1d <workspace>/review-*.shards | wc -l`, both 15). 2 + 6 + 5 + 15 + 15 = 43.
The enumeration is published so the total is auditable rather than trusted; a later
re-run sees a larger ledger.

**Rollback:** none within the ledger — `progress.md` accrues completion lines and
nothing in the skill rewrites or removes one. The whole ledger is removed at exactly
one point: `ship-issue` Phase 8 deletes that one worktree's bucket **after** the
worktree is gone, having captured the bucket path from the worktree's own git
directory before removal rather than guessing it from the worktree's path, and never
`primary/` or another worktree's (`ship-issue/SKILL.md:313-332`). The reversibility
limit runs both ways. The removal is a recursive delete of git-ignored content, so
nothing restores it; and `ship-issue` records that **nothing else** prunes a bucket
(`:327-331`), so a worktree removed by any other route leaves its ledger behind, and
a later worktree recreated under the same name resolves to that stale ledger and
reads its `Task <N>: complete` lines as its own.

### The review-package store

**Locator:** `<primary checkout>/.superpowers/issue-delivery/<issue>/<identity>/<producer>-<head-sha>.json`,
with a sibling shard directory of the same stem plus `.shards`
(`home/common/agent-skills/skills/sdd/scripts/review-package:930-932`, `:948`). The
producer alone derives that destination; callers supply issue, branch, run and head
identity and never an authoritative destination (`sdd/SKILL.md:60-63`). Its home carries its
own `.gitignore` holding `*`, written `O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW` through a
directory descriptor (`:643-660`) — a second ignore layer. Diff-review packages go elsewhere —
the sdd workspace above, or an explicit fourth positional path (`:752-770`). Live:
`ls -1 .superpowers/issue-delivery/` returns **10** issue directories, and
`find .superpowers/issue-delivery/115 -maxdepth 2` returns
`115/run-20260902-115-130/sdd-7edbe6b68f85d63713cb9ed0645405a06df0f9f7.json` and its
`.shards` sibling.

**Identity:** the *record* sense, in four validated parts. `<issue>` is a positive
decimal (`:893-897`); `<identity>` is the `run_id` when one matches `RUN_ID_RE`, or
`branch-<sha256 of the branch name>` when the caller passes `-` (`:924-929`);
`<producer>` is exactly `sdd` or `ship-review` and nothing else (`:898-899`); and
`<head-sha>` must be a full sha the repository actually contains, checked with
`git cat-file -e <head>^{object}` (`:900-908`). The branch argument must equal the
checkout's own `git symbolic-ref --short HEAD` (`:910-923`), so an identity cannot
be minted for a branch you are not standing on. A diff-review package names a
*range* instead, `review-<base7>..<head7>` (`:770`).

**Evidence:** the published manifest root and its shard files, plus an independent
measurement — both `sdd` and `ship-issue` require running
`artifact-budget check --kind review-package` on the returned durable root
*separately from* the producer's own report, comparing the two metric sets
(`sdd/SKILL.md:128-131`, `ship-issue/SKILL.md:300-303`). Its bounds are
`home/common/agent-skills/artifact-budget-policy.json:8`: `root_max_bytes` 16384,
`member_max_bytes` 65536, `max_members` 8, `aggregate_max_bytes` 524288.

**Rollback:** nothing supersedes a published root in place. Publication is by
exclusive hard link with inode-matched cleanup (`_publish_candidate`, `:369-430`,
failing as `exclusive package publication failed`, `:427`), and each
`(issue, identity, producer, head sha)` names its own file, so a re-run at a new
head writes a **new** file beside the old rather than replacing it. Reversibility
limit: publication is one-way. Every deletion in the script unwinds a publish that
*failed* (`:414-426`), clears staging (`:436`), or removes a temporary (`:485`,
`:688`); none removes a published root. The tree being git-ignored, no committed
version exists to restore either. The
one documented alternative is not a rollback but a declared failure: with a
non-empty finding set that will not publish, `sdd` may report
`detail_state: "unpublished"` and keep a retained candidate at
`<workspace>/retained-detail.json`, main-root-relative like the durable path
(`sdd/SKILL.md:189`, `:203-210`), while `ship-issue`'s equivalent retained candidate
is deliberately worktree-relative instead, so its lifetime ends with the worktree
(`ship-issue/SKILL.md:106-110`).

### The ship-release state file

**Locator:** `.superpowers/workflows/ship-release/state.json`, sharing the
`.superpowers/workflows/` home with the attempt-lifecycle ledger's run directories;
the skill ensures `.superpowers/workflows/.gitignore` exists containing `*`,
creating both if missing (`home/common/agent-skills/skills/ship-release/SKILL.md:34`).
Its root is the **primary checkout, never a feature worktree**: Phase 1 requires
`git rev-parse --git-common-dir` to be `.git` or to end in `.git`, and otherwise
switches to the main checkout or surfaces, because a release is repo-wide (`:84`).
Live: `ls .superpowers/workflows/ship-release/` fails with `No such file or
directory`. But the rule runs one way only — a present file means an unfinished
release (`:34`, `:340`) — and Phase 0 writes it only at its end, "when neither
resume path applies" (`:80`), so a release inside Phase 0, or one that died
before it, leaves none. The absence rules out an unfinished release past that
write, not one in flight.

**Identity:** the *record* sense, and the record is a **singleton**: one constant
path per repository, no run id and no release id in the name. What distinguishes one
release from the next is the file's *contents* — `headSha` names the
`origin/<integration>` tip being released, and `pr`, `prUrl`, `mergeSha`, `tag`,
`releaseUrl` and `deployState` fill in as phases complete (`:36-38`). A constant
name cannot express two concurrent releases; the skill's answer is that Phase 0
reads the file first and re-enters at the first null field rather than starting a
second (`:40`, `:80`). A record whose `headSha` matches neither
`origin/<integration>` nor a resumable `mergeSha` is **stale**: surfaced, then a
fresh start (`:80`).

**Evidence:** the file, read first in Phase 0 (`:40`, `:80`) — and, because it can
be stale or missing, a forge cross-check that does not depend on it: the newest
merged base→head PR, plus `git tag --points-at <oid> 'v[0-9]*'` to see whether a
merged release was ever tagged (`:81`). Writes are atomic (a temporary in the same
directory, then `mv`) at every transition, and `mergeSha` is persisted **before
doing anything else** after a merge, because a crash there otherwise strands a
merged, untagged release (`:40`, `:166`).

**Rollback:** the file is deleted, not rolled back — Phase 6 deletes it after the
report (`:40`, `:340`). Reversibility limit: deleting it reverses nothing the
release did. By then the merge, the annotated tag (`:244`) and the GitHub Release
(`:265-268`) all exist on the forge, and deleting the state file only ends the
resume claim over them. Read end to end on 2026-09-02, this skill declares no step
that deletes a tag or a Release —
`grep -n 'git tag -d\|release delete\|un-tag' home/common/agent-skills/skills/ship-release/SKILL.md`
matches nothing — so within the skill a published release is not reversible at all.
The only reversal it describes is a *deploy*-level one, and that one is the
provider's own silent rollback, which the skill exists to detect rather than to
perform (`:300`).

### The wayfind state on the tracker

**Locator:** the **tracker itself** — the one seam here with no filesystem home at
all. One issue labelled `wayfinder:map`, whose children are the decision tickets,
each labelled `wayfinder:<type>` for `research`, `prototype`, `grilling` or `task`
(`home/common/agent-skills/skills/wayfind/SKILL.md:18`, `:47-52`). The map is
explicitly "an **index, not a store** — a decision lives only in its ticket"
(`:18`). One filesystem fallback exists and is not in use here:
`issueTracker.kind: none` puts `map.md` plus `tickets/NNN-<slug>.md` under
`.claude/wayfind/<effort>/` (`:14`). This repository's `.claude/skills.config.json`
declares only an `orchestration` block and no `issueTracker` key, so the GitHub/`gh`
default applies, and `.claude/wayfind/` does not exist — both observed 2026-09-02.

**Identity:** the *record* sense, keyed by the tracker's own issue number: the map is
its number, each decision is its ticket's number, and blocking uses the tracker's
**native** dependency relationship rather than a field the skill invents (`:56`).
The rule that tickets are referred to by name — the title wrapping the link, never
bare numbers (`:18`) — governs how that identity is *written*, not what it is. Live,
`gh issue list --repo fagenorn/nix-config --label wayfinder:map --state all --limit 200`:
exactly **one** map, #59 "Wayfind: standardize and bootstrap the cross-agent project
system", `CLOSED`. Issue #80 — the ticket this document discharges — is one of its
decision tickets, labelled `wayfinder:research`
(`gh issue view 80 --repo fagenorn/nix-config --json labels`).

**Evidence:** the map body, loaded low-res once per session with
`gh issue view <n> --json title,body` (`:20`, `:22`), carrying `## Destination`,
`## Notes`, `## Decisions so far`, `## Not yet specified` and `## Out of scope`
(`:24-39`); and a ticket's body, which is its `## Question`, opened on demand, one
at a time, never as a set (`:20`, `:47`). Claim state is the tracker's assignee
field — open and unassigned means unclaimed, and the frontier is the open,
unblocked, unclaimed children (`:56`). Live sweep, one
`gh issue list --repo fagenorn/nix-config --label <label> --state all --limit 200 --json number --jq 'length'`
per label and again with `--state open`: 1 / 4 / 2 / 22 / 0 across
`wayfinder:` `map` / `research` / `prototype` / `grilling` / `task` — **29** tickets,
**zero open** in every non-map label. An empty frontier is exactly the precondition
the completion rule sets before a map may be closed (`:87`), and #59 is `CLOSED`.

**Rollback:** the tracker's, never the skill's. Resolving appends a resolution
comment and closes the ticket (`:85`); reopening one is the tracker's own act and
returns it to the frontier, and what the skill offers instead of an undo is the
completion rule's explicit re-disposition — resolved, out of scope, or a named
standing verification hook with its reopen condition written down (`:87`).
Reversibility limit: the map body is rewritten **in place**. Compression folds
subsumed gists into their superseder and cuts grown explanations back to links, and
while it "rewrites the index, never deletes from it — every closed ticket keeps its
link" (`:43`), the folded gist *text* does not survive. Nothing in the skill retains
a prior body; recovering one would depend on the tracker's own edit history, outside
the skill's contract and not exercised by this document.

## Immutable prototype references

Map #59 has exactly two `wayfinder:prototype` tickets — #86 and #79, both `CLOSED`,
by `gh issue list --repo fagenorn/nix-config --label wayfinder:prototype --state all --limit 200`
on 2026-09-02 — and both artifacts survive as commits on `origin`. Each is recorded
here as a whole triple: full 40-character sha, the exact `origin` branch whose tip is
that sha, and the directory that commit's tree contains. Checked apart, a sha would
pass a swapped pairing. Every command and figure below was run 2026-09-02 here.

**The release-transactions prototype (#86).** Sha
`dc98ba9b6bafaf7b5373cc7595ef79a5526846d1`, branch
`worktree-prototype-release-transactions`, directory
`prototype-release-transactions` — 8 files, by
`git ls-tree -r --name-only <sha> -- prototype-release-transactions | wc -l`; commit
date 2026-08-21 11:43:09 +0100. Retrieve it with
`git fetch origin worktree-prototype-release-transactions`, then
`git show dc98ba9b6bafaf7b5373cc7595ef79a5526846d1:prototype-release-transactions/NOTES.md`
or check the branch out into a worktree.

**The nix-config adoption dry run (#79).** Sha
`b49c8771cbaf87eefc5f0d385100e205060538d9`, branch
`worktree-prototype-nix-config-adoption-dry-run`, directory
`prototype-agent-adoption-dry-run` — 5 files, same command; commit date
2026-08-20 19:44:07 +0100. Retrieve it with
`git fetch origin worktree-prototype-nix-config-adoption-dry-run`, then
`git show b49c8771cbaf87eefc5f0d385100e205060538d9:prototype-agent-adoption-dry-run/`
or check the branch out into a worktree.

The three commands that establish reachability, tip identity and tree membership —
`git cat-file -e <sha>^{commit}` for each sha, `git ls-remote origin | grep prototype`,
and `git ls-tree --name-only <sha> | grep prototype` for each — are reproduced with
their verbatim output in this package's evidence member, under
`.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/enforcement-guard-mechanics.md § Prototype reference verification, verbatim`.

What that proves, and what it does not. `git ls-remote origin` reads the remote
directly, so each sha above is the **current tip** of that named branch, not merely
an object some local ref happens to reach — the point of citing a branch beside a
sha. A commit sha is content-addressed, so the reference is immutable: it will
always name that tree. The *branch* is not — nothing prevents a future force-push or
deletion, and neither branch is protected. The durable guarantee is the sha; the
branch is the route by which a reader still fetches it.

## Correction to #86's resolution comment

Issue [#86](https://github.com/fagenorn/nix-config/issues/86) says its prototype was
not pushed. That is not true of this repository. The correction is recorded here and
**only** here: per this issue's scope boundary no tracker comment is edited,
including #86's, and both of #86's comments still report `edited: false`.

Read 2026-09-02 with `gh issue view 86 --repo fagenorn/nix-config --comments` and
`--json comments`, #86 (`CLOSED` 2026-08-21T10:45:34Z) carries two comments and the
claim is split across them: the "Prototype ready for human review" comment writes
"(commit `dc98ba9`, **not pushed** — it lives in the local worktree)", and the
**Resolution** comment repeats the local-worktree framing — "(commit `dc98ba9`,
**local worktree** `worktree-prototype-release-transactions`)" — without itself
repeating the words "not pushed". Both comments verbatim, with their permalinks and
timestamps, and the #79 comments that make no such claim, are in the evidence member
under `.claude/specs/2026-08-20-release-lifecycle-seams-research.evidence/enforcement-guard-mechanics.md § Issue #86 and #79 comment records`.

The evidence against it is one command against the remote:

```
$ git ls-remote origin refs/heads/worktree-prototype-release-transactions
dc98ba9b6bafaf7b5373cc7595ef79a5526846d1	refs/heads/worktree-prototype-release-transactions
```

`origin` carries the branch `worktree-prototype-release-transactions` at exactly the
sha both comments name, and `prototype-release-transactions` is in that commit's
tree — see `## Immutable prototype references` above. So a reader who acts on either
comment today concludes the artifact is local-only and unrecoverable, and is wrong:
it is fetchable from `origin` by anyone with access to the repository.

The bound on this correction: it says the statement is false **of the repository as
observable on 2026-09-02**, and does **not** claim it was false when written. The
commit's date is 2026-08-21 11:43:09 +0100 — 10:43:09 UTC, 35 seconds before the
first comment — so the commit existed locally then, but nothing in this repository
records *when* the branch was pushed:
`git reflog show refs/remotes/origin/worktree-prototype-release-transactions`
carries a single entry, `fetch origin: storing head`, which dates this clone's fetch
and not the push. Either way the comment misleads now, which is what this repairs.

## What this document does not decide

- **The architecture.** #80 says, in its own words, "Do not choose the architecture
  or invent a universal adapter." Nothing above proposes a release model, a shared
  transaction, a common state machine or a scheduling order across the three
  projects. The five units are inventoried as they are, including where they
  disagree.
- **A universal adapter.** No abstraction is defined over the five. The
  `## Facts shared by all three projects` table is an observation that five
  properties happen to hold, each with its per-unit disposition so a reader can
  refute any cell; it is deliberately not an interface, and the two rows recorded
  immediately after it exist precisely to say which apparent commonalities are not
  real.
- **Whether any of these units should change.** That the Nix unit has 238 retained
  generations and no declared rollback command, that Railway's release identity can
  disagree with what is serving, that the Argus daemon cannot bind a running process
  to a commit, and that the signing unit retains no anchor at all, are each recorded
  as observations. Whether any is a defect to fix or an accepted cost of a personal
  fleet is a decision this inventory leaves open.
- **Anything about the sixth release unit.** This document did not sweep for one. The
  bound is stated in `## Unverified inheritance`, item 1, together with the release
  paths it saw and deliberately left out.
- **Whether #66 or #71's platform lifecycle is implemented.** It cites those tickets
  as settled decisions, never as observations of a running system, and it found no
  release-transaction state machine in any of the three repositories at the observed
  `HEAD`s.
- **No glossary, context map or ADR is created by this work.**
