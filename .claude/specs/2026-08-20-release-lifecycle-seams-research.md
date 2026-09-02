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

*Not yet written at this commit. The second authoring pass under issue #115 owns
this section, which will record the guard's locator, identity, evidence and rollback
as an `enforcement seam`, with its "only machine enforcement" claim bounded against
this repository's own forge-side branch protection.*

## Durable-state seams

*Not yet written at this commit. The second authoring pass under issue #115 owns
this section, which will record five independent durable state systems — the
attempt-lifecycle ledger, the sdd plan ledger, the review-package store,
ship-release's state file and the tracker-native wayfind state — each with a locator,
identity, evidence and rollback.*

## Immutable prototype references

*Not yet written at this commit. The second authoring pass under issue #115 owns this
section, which will record a full 40-character commit sha, a directory and a
retrievability command for each of the two surviving prototype artifacts.*

## Correction to #86's resolution comment

*Not yet written at this commit. The second authoring pass under issue #115 owns this
section. Per the issue's scope boundary the correction lives only in this committed
document; no tracker comment is edited.*

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
