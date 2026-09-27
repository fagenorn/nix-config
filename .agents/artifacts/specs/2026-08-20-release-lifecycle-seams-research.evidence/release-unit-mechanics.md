# Evidence member — release-unit mechanics, project by project

This file is an **evidence member** of
`.claude/specs/2026-08-20-release-lifecycle-seams-research.md`, which is the root of
this document package and the file issue #80's resolution comment links. It carries
bulk evidence only: the five release units' field-by-field answers to #80's recording
list. It states no synthesis and reaches no conclusion of its own — every conclusion
these records feed lives in the root, so a reader who found this file alone has found
a set of records, not a finding, and must read the root for what they mean. Its
provenance is the root's exactly: a **re-derivation authored 2026-09-02 under issue
#115**, not the never-committed 2026-08-20 original, whose content is unrecoverable.
Nothing here is a recovered byte, and no sentence in this file may be cited as
evidence of what the original said. The observation basis for every citation below —
each repository's observed `HEAD`, branch and observation date — the terminology
guards those sentences obey, and the bounds on what they assert are stated once, in
the root; read them there.

## Release-unit mechanics, project by project

The first unit is nix-config's; the next two are Nodo's; the last two are Argus's.
Every field of #80's recording list is answered once per unit, and a field with no
answer in the live tree says so and says why.

### Nix host generations (nix-config)

**Candidate identity:** a flake output attribute plus the tree and lock that
determine it. `flake.nix` builds `darwinConfigurations.mbp` (`aarch64-darwin`) and
`nixosConfigurations.anis-desktop` (`x86_64-linux`) through `libx.mkDarwin` and
`libx.mkNixos`. `just build` names the candidate as
`.#darwinConfigurations.<host>.system` on macOS and `.#<host>` to `nixos-rebuild`
on Linux. No version string, tag or build number appears in `flake.nix` or the
`justfile`; the candidate is identified by the derivation those inputs evaluate to.

**Release identity:** the realised store path plus the numbered generation link the
activation adds to the system profile. Read on this machine on 2026-09-02:
`readlink /nix/var/nix/profiles/system` → `system-238-link`, and
`readlink /nix/var/nix/profiles/system-238-link` →
`/nix/store/wzliawdp9gaflsh80rqs6n73h2jb26i3-darwin-system-25.11.ebec37a`.

**Publication target:** the local `/nix/store` of the machine being switched, and
nothing else. Nothing in the `justfile` pushes a closure to a cache or a remote
host. The one remote recipe, `just install <IP>`, clones the upstream
`ironicbadger/nix-config` over SSH and runs `lib/install/install-nix.sh` there — it
does not publish this checkout.

**Trigger:** a human running `just` (which defaults to `switch`) or `just switch`.
No CI job builds or activates anything: `.github/workflows/ci.yaml` defines exactly
two jobs, `Flake Checker` and `Nix Eval`, and `Nix Eval` runs
`nix eval --raw '.#nixosConfigurations.anis-desktop.config.system.build.toplevel.drvPath'`
— an evaluation to a derivation path, with no build and no activation, and only for
the Linux host. `.github/branch-protection.json` makes `Nix Eval` the sole required
context on `main` with `enforce_admins: true`, so it gates *merging*, not releasing.

**Ordering:** the `justfile`'s `switch` recipe declares `(build target_host)` as a
dependency, so the closure is realised before activation is attempted. Nothing
orders the two hosts relative to one another; each is switched on its own machine.

**Immutability:** store paths are *input*-addressed — the hash derives from the
derivation's inputs, not from the built output; Nix's own manual describes store paths
as "usually input-addressed" and offers `nix store make-content-addressed` as the
opt-in conversion, and nothing here declares that opt-in — and they are never
rewritten, which makes the Nix-owned part of a generation immutable. Two parts of an
activation are deliberately not: `hosts/common/darwin-common.nix` sets
`homebrew.onActivation = { cleanup = "zap"; autoUpdate = true; upgrade = true; }`
with `global.autoUpdate = true`, and `homebrew/palmier-tap/Casks/palmier-pro.rb`
declares `version :latest` with `sha256 :no_check`, paired with `greedy = true` in
`darwin-common.nix`. The cask's own comment states the consequence: every greedy
upgrade "re-fetches the newest PalmierPro.dmg. This is intentionally unpinned: the
goal is always-latest, not reproducible."

**Activation mode:** `sudo ./result/sw/bin/darwin-rebuild switch --flake ".#<host>"`
on macOS; `sudo nixos-rebuild switch --flake .#<host>` on Linux. home-manager runs
as a nix-darwin/NixOS module, so its `home.activation.*` entries run in the same
activation, ordered by `lib.hm.dag.entryAfter [ "writeBoundary" ]`.

**Authority boundary:** root, via `sudo`, for the system activation; the invoking
user for the home-manager entries. Secret material is a third boundary and lives
outside the repository: `home/common/sops/default.nix` declares
`sops.age.keyFile` as `~/.config/sops/age/keys.txt` and `sops.age.sshKeyPaths` as
`~/.ssh/id_ed25519`, neither of which the repository carries.

**Restart / convergence:** activation is one-shot and convergent by re-run rather
than by a loop. Re-running `just switch` re-asserts the whole declared state,
including `home.activation.claudeCodeSettings` re-copying `~/.claude/settings.json`
and `home.activation.palmierProMcp` re-merging one key into `~/.claude.json`. There
is no watcher, poller or reconciler on this unit.

**Deployment success evidence:** the exit status of `just build` and `just switch`.
The one repository-side inspection of a built artifact is `just show-claude-settings`,
which builds and then walks `nix-store --query --requisites ./result` for exactly one
`-claude-code-settings.json` path, failing when the count is not one.

**Running identity evidence:** the system profile symlink — the two `readlink` calls
recorded under *release identity*. This document read them; the repository declares
no recipe that does. So the machine can answer "which generation is active", but
nothing in nix-config asks it, and no command in the `justfile` compares an active
generation against the commit that produced it.

**Liveness evidence:** none is declared in this repository for an activated host.

**Readiness evidence:** none is declared. The unit has no admission or traffic
concept to be ready for.

**Migration evidence:** none — the unit has no schema and applies no migration. The
nearest related declaration is `stateVersion = "25.05"` in `flake.nix`, which pins
option defaults; it is not a migration receipt and nothing verifies it at activation.

**Product smoke evidence:** none in the release path. `just agent-workflow-tests`
runs Python suites over the agent-skill and branch-protection contracts, and
`CLAUDE.md` records that CI does not run them; either way they test repository
content, not an activated host.

**Data at risk:** three mutable surfaces that a generation does not own.
`~/.claude/settings.json` is materialised as a writable copy by
`home.activation.claudeCodeSettings`, whose comment states that live edits "persist
until the next switch, which resets it to the declared content."
`~/.claude.json` is a runtime-managed file that `home.activation.palmierProMcp`
deliberately does not own whole — it merges one `mcpServers` key with `jq` and
rewrites only when that key differs. And `homebrew.onActivation.cleanup = "zap"`
removes anything unmanaged on every activation; `darwin-common.nix`'s own tap
comment records that an undeclared `homebrew/cask` "is exactly how all casks got
wiped on 2026-08-02."

**Rollback anchor:** the retained numbered generations in the system profile. Read
2026-09-02 with
`find /nix/var/nix/profiles -maxdepth 1 -name 'system-*-link' | sed -E 's#.*/system-([0-9]+)-link#\1#' | sort -n`:
**238** links, numbered **1 through 238 with no gaps** (verified by diffing that
list against `seq 1 238`, which reported no difference), with generation 238 active.
Every one of the 237 superseded generations is still an addressable anchor.

**Rollback action:** none is declared in this repository. `grep -n 'rollback' justfile`
returns no line (exit status 1) at this `HEAD`, and the sweep
`git grep -niE 'rollback|--rollback|list-generations' -- '*.nix' '*.md' justfile ':!.claude'`
returns seven lines with this disposition: five are prose in
`home/common/agent-skills/skills/ship-release/SKILL.md` about *Railway's*
silent-rollback trap, and two match only the substring `scrollback` — one in
`home/common/agent-skills/skills/prototype/LOGIC.md`, one as `scrollback-limit` in
`home/common/ghostty/default.nix`. No recipe, no option, no documented command. The
sweep covers tracked `*.nix`, `*.md` and `justfile` outside `.claude/` and nothing
else, so it is silent about untracked files and other extensions.
The anchor exists; the action is left to the operator
and to the underlying tool.

**Reversibility limit:** the generation covers only what Nix owns. The three mutable
surfaces named under *data at risk* are outside it, so activating an older
generation does not restore a zapped Homebrew cask, an older `palmier-pro` build, or
a `~/.claude.json` that a running Claude Code has since rewritten.

**Retirement evidence:** the `justfile`'s `gc` recipe (lines 133–135) runs
`nix-env --delete-generations {{generations}}` — default argument `5` — followed by
`nix-store --gc`. The recipe passes its argument through verbatim and names no
profile with `-p`, so which profile's generations it acts on is decided by
`nix-env`'s own default-profile resolution, which this document did not exercise and
does not assert. What it does assert is the outcome on the system profile: with 238
contiguous generations and no gaps, **no system generation has ever been retired on
this machine.**

**Partial failure behaviour:** activation is not one transaction. The Nix part is
atomic — a failed build produces no generation — but `homebrew` runs `brew bundle`
inside the same activation with `cleanup = "zap"` and `upgrade = true`, and the
home-manager `home.activation.*` entries run as ordinary shell after `writeBoundary`.
A failure in a later stage therefore leaves a machine that has already changed. No
compensation, receipt or resume marker is written anywhere.

**Re-entry behaviour:** re-running `just switch` is the declared repair, and it is
safe to repeat: the settings copy is an unconditional `cp -f`, and the MCP merge is
explicitly idempotent — it compares the canonicalised current value against the
wanted one and rewrites only on a difference, "minimising any race with a
concurrently-running Claude Code."

### Railway api and admin services (Nodo)

**Candidate identity:** a commit on `main`, plus the build recipe the service reads.
`railway.toml` (Root Directory `/`, the api) sets `[build] builder = "DOCKERFILE"`
and `dockerfilePath = "src/Nodo.Api/Dockerfile"`; `admin/railway.toml` (Root
Directory `admin/`) sets `dockerfilePath = "Dockerfile"`. Neither file names an
image, a tag or a digest — the candidate is a commit, and Railway builds it.

**Release identity:** the Railway deployment record. `docs/operations/deploy.md`
names the fields a reader uses — `.latestDeployment.status`,
`.latestDeployment.meta.commitHash`, and per-deployment `{id, status, commit, at}`
from `railway deployment list` — and warns that `latestDeployment.commitHash` "shows
the latest *tagged* commit on `main`, not necessarily the one Railway actually
built."

**Publication target:** two separate Railway services, `api` and `admin`, in the
prod environment of the Railway project. They are configured by two files with two
Root Directories and are released independently.

**Trigger:** a push to `main` matching that service's `watchPatterns`; a push that
does not match triggers no redeploy. The api's set, as `deploy.md` records it, is
`src/**`, `Nodo.slnx`, `**/*.csproj`, `Directory.*.props`, `global.json`,
`railway.toml`, `src/Nodo.Api/Dockerfile`, `.dockerignore` and
`engines/nodo-cli-mcp/assets/showcase-preview-server.mjs`. Two other triggers are
documented: `./scripts/deploy.sh`, "the canonical entry point for upserting env vars
and triggering a deploy", and setting or changing any service variable (which
auto-redeploys) or `railway up --service <name> --detach`.

**Ordering:** an overlapping rollover, tuned by two platform variables that both
default to `0`: `RAILWAY_DEPLOYMENT_OVERLAP_SECONDS=60` keeps the old and new
containers running concurrently so the new one finishes its one-shot
`StartupRecoveryService` before the old is signalled, and
`RAILWAY_DEPLOYMENT_DRAINING_SECONDS=30` is the SIGTERM-to-SIGKILL window, matched to
.NET's default `HostOptions.ShutdownTimeout`. `deploy.sh` seeds both in its
`api_vars` upsert. The two services are not ordered against each other.

**Immutability:** low, and asymmetric. The built image is internal to Railway and is
not addressed by a digest anywhere in the repository, so a release cannot be named
by content. The admin service is additionally build-time-baked: `deploy.md` records
that changing any `VITE_*` variable "has no effect until a rebuild", because the
bundle filename hashes off the env values.

**Activation mode:** platform-managed container replacement behind a healthcheck.
`railway.toml` sets `healthcheckPath = "/health"`, `healthcheckTimeout = 300`,
`restartPolicyType = "ALWAYS"`, `restartPolicyMaxRetries = 10` and `numReplicas = 1`;
`admin/railway.toml` sets `healthcheckPath = "/"`, `healthcheckTimeout = 60` and the
same restart policy, with no `numReplicas`.

**Authority boundary:** the Railway project's own credentials, exercised from a
workstation or the dashboard, not from the repository. `scripts/deploy.sh` is the
canonical entry point and is idempotent; a separate schema-owner credential,
`ConnectionStrings__MigrationConnection`, exists precisely so the runtime role
`nodo_app` carries no `BYPASSRLS` and no DDL rights.

**Restart / convergence:** `restartPolicyType = "ALWAYS"` restarts the **active**
deployment's container on any exit — the fix for the 2026-07-20 incident, where the
api exited 0, was recorded as "Completed", and under the previous `ON_FAILURE`
policy was never restarted, staying dead about 3.5 hours.
`restartPolicyMaxRetries = 10` is the crash-loop fuse. A superseded container belongs
to a removed deployment, which Railway tears down and does not restart. There is no
convergence loop: Railway replaces, it does not reconcile.

**Deployment success evidence:** the deployment's own status, read deliberately.
`deploy.md` is explicit that `deploy.sh`'s "✓ Deploy successful" confirms only that
the env-upsert and deploy-trigger returned HTTP 200 — "*not* that the build landed" —
and that a deploy failing `ValidateOnStart` is marked `FAILED` while the previous
successful deployment keeps serving, with `/health` still returning 200. The
prescribed check is
`railway status --json | jq '…select(.name=="api") | .latestDeployment.status'`
compared against local `git rev-parse HEAD`, with
`railway deployment list --service api --json` used to distinguish a real failure
from a stale `FAILED` notification sitting in front of a newer `SUCCESS`.

**Running identity evidence:** `.latestDeployment.meta.commitHash`, carrying the
caveat above that it names the latest tagged commit on `main` rather than
necessarily the built one. No endpoint on the api reports the commit it is running.

**Liveness evidence:** `GET https://api.nodo.com/health`, an unauthenticated route
registered in `Program.cs`, returning 200 with `{ "status": "healthy", "timestamp":
… }`. `deploy.md` states it is a pure liveness probe that runs no dependency checks,
that "Railway deployment status is NOT a liveness signal", and that **no external
uptime monitor exists yet** (tracked as Nodo issue #1030) — so a cleanly-exited api
is currently invisible.

**Readiness evidence:** the platform healthcheck is the only gate the two
`railway.toml` files declare, and it probes the same `/health` liveness route for the
api and `/` for the admin.
Readiness is therefore not distinguished from liveness for either service; no
separate readiness signal exists.

**Migration evidence:** the EF migration runs at api startup, over
`ConnectionStrings__MigrationConnection` when that variable is set and over
`DefaultConnection` otherwise. Its evidence is indirect and negative: a migration or
boot-validator failure is a startup throw, which Railway marks `FAILED`, which
silently leaves the previous image serving. `deploy.md` names the resulting confusion
directly — old code querying "a table the new migrations dropped". Since Nodo issue
#1014 one-shot startup DB access retries transient pooler saturation on a bounded
~120 s budget, logging a named warning before proceeding.

**Product smoke evidence:** none in the deploy path. No step after the healthcheck
exercises a product behaviour.

**Data at risk:** the production Postgres schema, mutated by the startup migration
before any traffic decision is made; the durable run tables (`workflow_runs`,
`workflow_run_errors`, `workflow_run_events`, `node_timeline_frame`) that the
runbook names as the canonical read site precisely because logs are rationed; and
the session-mode pooler's shared client slots, where the documented invariant is
`worst-case concurrent containers × MaxPoolSize + slack ≤ pooler pool_size`, today
`3 × 8 = 24 ≤ 25`. A rollover that loses that race crashes the new container on its
first DB access with `XX000: (EMAXCONNSESSION)` — and then silently rolls back.

**Rollback anchor:** the previous successful Railway deployment, retained by the
platform and visible in `railway deployment list`.

**Rollback action:** `docs/operations/self-serve-cutover.md` states it in one line:
"`railway redeploy` the previous deployment, or revert the release merge."

**Reversibility limit:** redeploying an earlier image does not un-apply a migration
that already ran. The runbook's own worked example is the failure shape this
produces — a retained older image executing days-old code against a freshly-migrated
schema. `docs/areas/egress/` ADR prose records the same constraint from the other
side: a rollover's ~30 s draining window can put the old container and the new schema
in contact at the same moment.

**Retirement evidence:** the superseded container belongs to a *removed* deployment,
which Railway tears down and does not restart — observed on the first post-#1028
deploy as "old instance ends removed, new instance RUNNING." The repository holds no
record of retired deployments beyond what `railway deployment list` returns.

**Partial failure behaviour:** three documented shapes. A `FAILED` deploy with the
previous image still serving and `/health` still 200 — the silent rollback, and the
reason "verify a deploy actually landed" is a runbook section. A stale `FAILED`
notification surfacing after a newer `SUCCESS` has landed. And a rollover that loses
the pooler-capacity race, which fails on first DB access and then presents as the
first shape.

**Re-entry behaviour:** `deploy.sh` is idempotent — "a second run only re-prompts for
the values you change" — and `railway up --service <name> --detach` forces a deploy
of the current head when a watch-pattern miss left the service behind.

### Digest-addressed GHCR engines with reconciler convergence (Nodo)

**Candidate identity:** `ghcr.io/${{ github.repository_owner }}/nodo-reconciler` at
two tags written by the same build — `:${{ github.sha }}` and the floating
`:stable` on `main` or `:dev` elsewhere — produced by `docker/build-push-action@v6`
in `.github/workflows/reconciler-image.yml`, after `gofmt -l`, `go vet ./...` and
`go test ./...` pass in the same job.

**Release identity:** the **manifest list** digest, as
`ghcr.io/<owner>/nodo-reconciler@sha256:<64 hex>`. The `publish-and-roll` job
resolves it with
`docker buildx imagetools inspect "$REPO:$SHA_TAG" --format '{{json .Manifest}}' | jq -r '.digest'`
and refuses anything not matching `^sha256:[a-f0-9]{64}$`. The workflow's own comment
records why the obvious value is wrong: the build action's `outputs.digest` is the
inner image digest, "which is NOT pullable when the build produced a manifest list
(which happens on every build — provenance attestations are on by default)."

**Publication target:** two, in order. First GHCR — `ghcr.io/elevenyellow/<image>`,
never a personal namespace, per `deploy.md`'s GHCR section. Then the api, by
`POST https://api.nodo.com/api/internal/vps-components/publish` with the body
`{"Kind": "reconciler", "ImageDigest": "<repo>@sha256:…", "Version": "<first 12 chars of the sha>"}`.
`docs/operations/reconciler.md` records that all five engines publish to that one
endpoint and that the `Kind` slug discriminates rows in the single
`device_vps_components` table, idempotent on `(kind, image_digest)`.

**Trigger:** a push to `main` or `dev` touching `engines/nodo-reconciler/**` or the
workflow file builds and pushes; `pull_request` on the same paths builds without
pushing. The `publish-and-roll` job additionally requires
`github.ref == 'refs/heads/main'` and a non-empty digest output. `workflow_dispatch`
is the documented manual escape hatch, and the workflow states that the branch chosen
at dispatch governs both the tags and whether the roll happens.

**Ordering:** `publish-and-roll` declares `needs: test-and-build`, so nothing is
published from an untested build. Publishes are serialised by
`concurrency: { group: publish-and-roll-reconciler, cancel-in-progress: false }` —
queued, never cancelled, so a superseded publish still completes rather than being
dropped.

**Immutability:** the digest reference is immutable, and it is the field the device
compares itself against. `:stable`, `:dev` and `:<sha>` are mutable names that point at it, and
the publish endpoint is idempotent on `(kind, image_digest)`. The runbook records the
one gap the immutability cannot close: the endpoint's regex "cannot distinguish a
valid-looking inner-image digest from a valid-looking manifest list digest", so
resolving the right one is the workflow's obligation, not the endpoint's.

**Activation mode:** convergence, not push. The api writes
`device_vps_components.desired_image_digest` on every device's reconciler row. The
already-running reconciler polls `/api/internal/devices/{id}/components` on a
`tickInterval` of 30 s (`engines/nodo-reconciler/internal/loop/loop.go`), and at
step 7 of `Once` compares `desired` against `state.conf`'s `current_digest`. On a
difference it heartbeats `Pulling`, writes the new digest to `state.conf` and returns
`exit=true` so the process exits 0. The host-side supervisor
(`src/Nodo.Api/Services/Devices/CloudInit/Resources/nodo-reconciler-supervisor.sh`)
catches the clean exit, re-sources `state.conf`, sees `current_digest` changed,
`docker pull`s it, sets `fallback_digest` to the digest that had just run cleanly,
and restarts the container. The reconciler cannot restart itself and does not try.

**Authority boundary:** three, all distinct. GHCR writes use the workflow's
`GITHUB_TOKEN` under `permissions: packages: write`, plus an org-side "Manage Actions
access" grant that `deploy.md` records as necessary and not sufficient on its own.
The publish call authenticates with the shared `NODO_API_PUBLISH_TOKEN` bearer
(`Ci__PublisherToken`), shared across all engine publish workflows. On the device,
the reconciler container runs with `--pid=host --network=host` and
`/var/run/docker.sock`, `/run/systemd`, `/etc/nodo-mcp`, `/etc/nodo-vps`,
`/var/lib/nodo-mcp`, `/var/lib/nodo-vps` and `/etc/nodo-reconciler` mounted.

**Restart / convergence:** the supervisor is a `while true` loop with
`MAX_FAIL_COUNT=3`. Any non-zero container exit increments `fail_count` and persists
it; at 3 it sets `current_digest` to `fallback_digest` and resets the counter. If
those two are already equal — both the active and the fallback image are the same
broken build — it clears `current_digest`, sleeps
`BOTH_BAD_RECOVERY_SLEEP_SECS=300`, and adopts
`/etc/nodo-reconciler/recommended_fallback` if the heartbeat response has written
one. Every state write goes through `mktemp` + `chmod 0600` + `sync` + `mv`.

**Deployment success evidence:** the publish call's HTTP status. The workflow retries
`000|400|502|503` — where `000` is a synthetic code for a transport-level curl
failure — up to `max_attempts=5` with a 30 s backoff, and fails immediately on any
other non-2xx as "auth or payload bug". `deploy.md` explains the 400 case: a merge
fires the workflow and Railway's redeploy in parallel, so the first attempt can hit
old api code with a new payload shape.

**Running identity evidence:** the per-component heartbeat
`POST /api/internal/devices/{deviceId}/components/reconciler/heartbeat`, emitted at
the end of every 30 s tick, carrying `currentImageDigest`, `reconcileStatus`
(`Idle`, or `Pulling` for the one tick before a self-update exit),
`stateSchemaVersion: 1` and `supportedFeatures`. The api stamps
`device_vps_components.last_heartbeat_at`. The supervisor deliberately does **not**
send `current_digest` in its own heartbeat; the script's comment states that the
per-component heartbeat "is the single authority for that field" and that
dual-writing would "silently divergence-race that path."

**Liveness evidence:** two channels, by design. Channel 1 is the per-component
heartbeat above, every 30 s. Channel 2 is
`POST /api/internal/devices/{deviceId}/supervisor-heartbeat`, emitted by a background
sibling of the supervisor every `HEARTBEAT_INTERVAL_SECS` (60 s), carrying
`{"reconcilerAlive": …, "failCount": …, "fallbackDigest": …}`, where `reconcilerAlive`
is the result of
`docker ps --filter "name=^nodo-reconciler$" --format '{{.Status}}' | grep -q '^Up'`.
Two channels exist because the supervisor runs outside the container: comparing their
recency distinguishes "the reconciler is wedged on this device" from "the whole VPS
is unreachable". `docs/operations/reconciler.md` records why liveness has to be
heartbeat-driven rather than pollable — the Go binary opens no HTTP listener, the only
`http.Server` references in the package tree being test fakes, and
`ComponentMap.Reconciler.Port` is `null` to pin that on the wire. This document did not
re-run that listener sweep itself and cites the runbook for it.

**Readiness evidence:** none for this unit itself; for its siblings, yes. The
reconciler probes each MCP's `http://127.0.0.1:<port>/healthz` before heartbeating
`Idle` after a restart, and gates the env-rewrite network flip on the gateway's
`http://127.0.0.1:8090/healthz`. Those prove a sibling component is ready, not that
the reconciler release converged.

**Migration evidence:** none in the image path — the engine carries no schema. The
api-side rename `20260511111541_RenameMcpComponentsToVpsComponents` belongs to the
Railway unit's migration story, not this one.

**Product smoke evidence:** none for the reconciler's own roll. The nearest thing in
the same codebase belongs to a sibling: a browser digest change commits only after
`/healthz` reports Chrome healthy "with the immutable runtime version from the
candidate image label", and a failed candidate re-establishes the previous browser
while fleet desired stays on the candidate so a later tick retries.

**Data at risk:** `/etc/nodo-reconciler/state.conf` — mode 0600, written atomically,
holding `current_digest`, `fallback_digest`, `fail_count` and
`browser_current_proxy_token_hash`, and read by both the shell supervisor and the Go
process. Also the browser profile under `/var/lib/nodo-mcp`, protected during a roll
by a checkpoint and a journal, and the MCP env files under `/etc/nodo-mcp` that the
env-rewrite sweep edits.

**Rollback anchor:** two, at different layers. On the device, `fallback_digest` in
`state.conf` — exactly one prior digest. In the registry, every previously published
`<repo>@sha256:<hex>` reference, immutable by construction. This document made no
registry call and does not assert that any particular one is still present.

**Rollback action:** re-publish an older archived digest reference to the same
`/api/internal/vps-components/publish` endpoint; the idempotency contract and the
auto-roll path are unchanged, so the fleet converges onto it. The runbook names
`POST /api/admin/vps-components/reconciler/roll-out` as the explicit fleet-wide push
if `desired_image_digest` does not move. On the device and without any operator, the
supervisor's crash-loop revert is itself a rollback action.

**Reversibility limit:** the automatic revert is exactly one step deep —
`fallback_digest` holds a single prior digest, and it is only set when a
self-update's `docker pull` succeeded. When the active and fallback digests are the
same broken image the device cannot self-recover at all: it clears `current_digest`,
waits 300 s, and can only proceed if the api has supplied a
`recommendedFallbackDigest`.

**Retirement evidence:** for components, the `Draining` sweep — the tick loop
uninstalls a `Draining` infrastructure component and then calls `DeleteComponent`
for its row, deferring the egress-gateway teardown while any MCP env file still pins
the `nodo-egress` network. For images, nothing: no step retires or garbage-collects
an old GHCR digest, and the runbook's only deletion path is a human asking an org
owner to delete a mistakenly-personal package through the GitHub UI.

**Partial failure behaviour:** several, each handled explicitly rather than
generically. A publish landing before Railway's redeploy 400s and is retried. An
`ErrRollDeferred` from the api-side lease gate defers only the unit-disruptive part
of a roll, and the loop is careful not to bump a failure heartbeat or mutate
`LastReconciledAt` for it. A failed `state.conf` write on the self-update path
deliberately does **not** exit — "safer to keep running on the current digest" —
because an exit the supervisor cannot interpret would be worse. An interrupted
browser transaction is recovered *before* new desired state is read, and if it
remains unresolved the loop suppresses every browser restart path for that tick.

**Re-entry behaviour:** re-entrant by construction. Every 30 s tick re-reads desired
state from the api; the publish endpoint is idempotent on `(kind, image_digest)`;
`RecoverBrowserRoll` runs at the top of each tick before anything new is observed;
and a failed tick is logged and retried rather than escalated.

### Argus launchd daemon rooted in a checkout

**Candidate identity:** the working tree at the repository path — and nothing
narrower. `daemon/launchd.ts`'s `install()` bakes exactly two values into the plist:
the devenv binary, resolved at install time by `execFileSync("zsh", ["-lc", "command -v devenv"])`,
and the repository path, `process.env.DEVENV_ROOT ?? process.cwd()`. No commit,
version or content hash appears anywhere in `renderPlist`'s output.

**Release identity:** the launchd label `dev.argus.daemon` in the domain
`gui/<uid>`. One label, overwritten in place. There is no per-release identity at
all — two successive installs are indistinguishable from the plist.

**Publication target:** exactly one generated file outside the repository,
`~/Library/LaunchAgents/dev.argus.daemon.plist`, which
`docs/areas/daemon-scheduling/adr/002-launchd-agent-containment-exception.md` records
as a deliberate, minimal exception to ADR-system-002's contain-everything rule; plus
a second same-shape exception, the notification bundle copied to
`~/Library/Application Support/Argus/Argus.app`, because Notification Center records
the posting app's on-disk path and so cannot run from an ephemeral worktree path.
Read on this machine 2026-09-02, the installed plist confirms both: its
`ProgramArguments[0]` is
`/nix/store/jkjfblkggnscvgwv60nfqfkc3l8aa7ki-devenv-2.0.2/bin/devenv`, its
`WorkingDirectory` is `/Users/anis/Projects/argus` — the same checkout recorded in
`## Observation basis` — and
`ls -d "$HOME/Library/Application Support/Argus/Argus.app"` resolves. Exactly one
nix-store path is baked in, which is what the ADR claims: launching through
`devenv shell` re-resolves the rest of the environment on every start.

**Trigger:** a human running `daemon install`. The ADR additionally makes
`daemon restart` (`launchctl kickstart -k`) "the documented follow-up to any
`devenv.nix`/model/env change, because the resident process holds its env from start
time" — which means changing the checkout is not, by itself, a release.

**Ordering:** `install()` runs `installNotifyd()` first, then writes the plist, then
`launchctl bootout` (failure swallowed — "not loaded"), then `launchctl bootstrap`.
`installNotifyd()` itself removes the legacy `~/Applications/ArgusPing.app`, then
removes and re-copies the target bundle.

**Immutability:** none. `writeFileSync` overwrites the plist wholesale, and
`installNotifyd` `rmSync`s the target bundle before `cpSync`ing the new one. No prior
plist or bundle is retained anywhere.

**Activation mode:** `launchctl bootstrap gui/<uid> <plist>`, with `RunAtLoad` and
`KeepAlive` both true and `ProcessType` `Background`; stdout and stderr go to
`home/daemon/logs/daemon.{out,err}.log` inside the checkout. `daemon restart` is
`launchctl kickstart -k`.

**Authority boundary:** the user's own GUI login session — `gui/${process.getuid()}`.
No root, no `sudo`, nothing system-wide. The ADR records the consequence it accepts:
LaunchAgents run per login session, so "after a reboot with no login, nothing runs."

**Restart / convergence:** launchd's `KeepAlive` restarts the process, throttled by
launchd itself; on top of that `daemon/daemon.ts` keeps its own counter, reading
`clean_shutdown` from the state DB's `meta` table at startup, appending a timestamp
to `abnormal_restarts` when the previous shutdown was not clean, and notifying
**once** when three land inside an hour. There is no convergence loop and nothing
re-asserts the plist on a schedule.

**Deployment success evidence:** `daemon status`, which reports three things: whether
the plist exists; whether its text still contains `<string>${repo()}</string>`,
printing a warning to re-run `daemon install` when it does not; and the `pid = N`
parsed out of `launchctl print gui/<uid>/dev.argus.daemon`.

**Running identity evidence:** the pid, plus that repo-path string comparison — and
nothing more. Nothing binds the running process to a commit, so `daemon status`
cannot distinguish a current checkout from a stale one, only a *different* one. The
ADR records the matching blind spot from the other end: a fully dead daemon (broken
devenv, deleted repo, corrupted state DB at boot) "cannot self-report", and a second
watchdog process was rejected.

**Liveness evidence:** the pid from `launchctl print`, plus per-job watermarks read
out of the state DB with `{ readOnly: true }` — for each job in `REGISTRY`,
`last_success` and `consecutive_failures` from the `job_state` table, printed with a
`(disabled)` marker for gated jobs.

**Readiness evidence:** none. The daemon admits no traffic and has no readiness
concept to report.

**Migration evidence:** the state DB migrates forward when opened.
`daemon/state.ts`'s `getStateDb` sets `journal_mode = WAL` and `busy_timeout = 5000`,
then `migrate` reads `PRAGMA user_version` and applies each pending entry of an
append-only `MIGRATIONS` list inside `BEGIN` / `COMMIT`, with `ROLLBACK` on error.
The result is durable and inspectable, but there is no receipt: nothing outside the
DB records which version an install expected.

**Product smoke evidence:** none in the install path. Argus's CI
(`.github/workflows/ci.yml`, 81 lines, one job named `memory` on `ubuntu-latest`) runs
the hermetic test tree behind a coverage guard. Its steps are `checkout`, `setup-node`,
`npm ci` and four `node --test` invocations, and
`grep -niE 'daemon (install|run)|launchctl' .github/workflows/ci.yml` matches nothing,
so nothing there installs, bootstraps or starts the daemon.

**Data at risk:** the daemon-owned SQLite state DB — `home/daemon/state.db` by
default, overridable with `ARGUS_DAEMON_DB` — whose writer contract names the daemon
process as the sole writer and every other consumer read-only. It holds watermarks,
the run journal, poll seen-sets, the handoff queue, the notification ledger and the
triage queues. Also the logs, which `rotateLogs()` rotates at startup: a file over
5 MB has whatever sat at `x.2` removed, then `x.1` becomes `x.2` and `x` becomes
`x.1` — three generations are kept and the fourth is gone.

**Rollback anchor:** the git checkout itself. Nothing else is retained — no prior
plist, no prior bundle, no record of what was previously installed.

**Rollback action:** `daemon uninstall`, which boots the agent out, removes the
plist, removes the `~/Library/Application Support/Argus` directory that Argus owns
exclusively, and removes the legacy `~/Applications/ArgusPing.app`; or moving the
checkout back to an earlier state and re-running `daemon install`.

**Reversibility limit:** the state DB, which uninstall does not touch and which
migrates only forward. `migrate` iterates from `user_version` up to
`MIGRATIONS.length`, so a database whose `user_version` already exceeds an older
checkout's migration list is opened **unchanged and without error** — the older code
then runs against the newer schema. No down migration exists anywhere in
`daemon/state.ts`.

**Retirement evidence:** `uninstall()` prints "uninstalled dev.argus.daemon —
containment restored", and the legacy `~/Applications/ArgusPing.app` removal runs
unconditionally on both install and uninstall, so a pre-polish copy cannot linger in
Spotlight. Nothing records *which* release was retired, because nothing recorded
which release was installed.

**Partial failure behaviour:** `installNotifyd()` logs "no built bundle at … —
skipping install" and returns when `daemon/notifyd/Argus.app` has not been built, so
`install` then goes on to write and bootstrap the plist and exits successfully. That
is a genuinely partial release — a running daemon with no notification helper — and
it is not reported as a failure. The `bootout` failure is swallowed on purpose,
because "not loaded" is the normal first-install case.

**Re-entry behaviour:** `install` is idempotent and is itself the documented refresh
— it re-resolves the devenv binary and the repository path, and the command's own
output tells the operator to "re-run 'daemon install' after moving the repo or
changing devenv.nix."

### Locally signed Argus helpers

**Candidate identity:** the freshly compiled binary or bundle at its build path,
before `codesign` runs. It carries whatever identity the compiler left — for a bare
Go binary the linker stamps `a.out`, which is why `daemon/sign.sh`'s usage note says
to "ALWAYS pass one for bare Go binaries."

**Release identity:** the code-signing identifier plus the designated requirement the
signature anchors it to. Five artifacts: four bare binaries signed with explicit
identifiers — `dev.argus.authd`, `dev.argus.ocr-helper`, `dev.argus.wa-bridge`,
`dev.argus.wkfetch` — and one bundle, `daemon/notifyd/Argus.app`, signed with no
`--identifier` so it keeps `dev.argus.pings` from its `Info.plist`.
`docs/areas/system/adr/012-stable-code-signing-local-binaries.md` records the
resulting requirement, verified byte-identical across two independent builds:
`identifier "dev.argus.wa-bridge" and anchor apple generic and certificate
leaf[subject.CN] = "Apple Development: …"` — anchored to identifier and certificate,
never to a build hash.

**Publication target:** local filesystem paths inside the checkout —
`daemon/wa-bridge/wa-bridge`, `daemon/broker/authd`, `home/extensions/ocr/ocr-helper`,
`home/web/wkfetch` and `daemon/notifyd/Argus.app`. Nothing is uploaded anywhere. The
bundle is *copied* out of the repository by the launchd unit's install, not by this
one.

**Trigger:** a build command that ends in a signature. Sweep, in the Argus checkout:
`git grep -n 'sign\.sh' -- . ':!.claude'` returns **20** lines; of those, the ones
that actually invoke the helper (`git grep -nE 'bash [^#]*sign\.sh"? "' -- . ':!.claude'`,
7 lines, of which `docs/areas/system/adr/020-…:80` is prose quoting an invocation
rather than one) are **six invocation sites in three files**: `devenv.nix` lines 145,
155 and 160 (the `enterShell` build blocks for `authd`, `ocr-helper` and `wa-bridge`)
and line 250 (the `wa-build` script), `daemon/notifyd/build.sh:57`, and
`home/extensions/web/fetch/build-wkfetch.sh:32`. The 13 lines the invocation pattern did not
match are comments, ADR prose or the remedy string in
`tests/daemon/binaries-signed.test.ts` — 20 total minus the 7 matched — and the six
real invocations are those 7 matches minus that one prose line. Each
`enterShell` block is guarded by `if [ ! -x <path> ]`, so it fires only when the
artifact is **absent** — entering the shell again does not re-sign anything.

**Ordering:** compile, then sign — that order, in the same script, at all six
invocation sites enumerated above. For
the bundle the ordering is stricter still: `notifyd/build.sh` writes `AppIcon.icns`
and, when `actool` is available, `Assets.car` into `Contents/Resources` *before*
calling `../sign.sh`, with the comment "Must happen before codesign — the signature
seals Resources."

**Immutability:** none. `codesign --force` replaces the signature in place and the
build overwrites the binary underneath it. No prior artifact, signature or
requirement is retained, so a release cannot be named, compared or re-fetched.

**Activation mode:** none of its own. A signed artifact becomes live when the next
process to exec it starts, which is why `wa-build` ends by printing "wa-bridge
rebuilt + signed — `daemon restart` to pick it up." The activation, when it happens,
belongs to the launchd unit above.

**Authority boundary:** the developer's login keychain and codesigning identity.
`sign.sh` takes `ARGUS_CODESIGN_IDENTITY` when set, otherwise the first
`Apple Development` line from `security find-identity -v -p codesigning`; ADR-system-012
records that a free Apple ID's Xcode-managed certificate suffices and no paid
membership is needed. Two capabilities are refused on purpose: no entitlements ever,
because "entitlements in a non-provisioned signature get the process AMFI-killed",
and no hardened runtime.

**Restart / convergence:** the resident daemon picks up a re-signed binary only when
it restarts, which is what `wa-build` prints. Nothing converges: no loop re-signs, no
schedule re-checks, and no process notices that an on-disk artifact's signature
changed.

**Deployment success evidence:** `tests/daemon/binaries-signed.test.ts`, which runs
`codesign -dv` over the four bare binaries and asserts two things about the output —
that it does not match `^Signature=adhoc$`, and that it does match
`^Identifier=dev\.argus\.<name>$`. The test skips when no codesigning identity exists
on the machine and when the binary is not built. Per
`docs/areas/system/adr/020-locally-built-binaries-verified-on-darwin-only.md`, CI is
a single `ubuntu-latest` job, so this evidence is only ever produced on the
developer's Mac. The `Argus.app` bundle is not in that test's list of four.

**Running identity evidence:** none. The test inspects the artifact on disk; nothing
binds a *running* process to the signature it was started from, and no runtime check
exists. A daemon started before a re-sign keeps running the old image with no signal.

**Liveness evidence:** none — the helpers are execed on demand by other processes,
and this unit has no process of its own to be live.

**Readiness evidence:** none, for the same reason.

**Migration evidence:** none. The unit persists no schema and applies no migration.

**Product smoke evidence:** none in the signing path.

**Data at risk:** the login keychain's "Always Allow" ACL grants — which is the whole
reason the unit exists. ADR-system-012 records the mechanism: the ACL stores the
requesting app's *designated requirement*, and for an ad-hoc build that requirement
is the cdhash of that exact build, so "every rebuild is a different app: the grant is
silently invalidated and the popup returns." `wa-bridge` reads two login-keychain
items at every startup, so before the fix each rebuild plus `daemon restart` cost the
owner two prompts.

**Rollback anchor:** none. No prior binary, no prior signature and no record of what
an artifact was previously signed with is kept anywhere in the repository or on disk.

**Rollback action:** rebuild and re-sign from older sources — `wa-build` for the
bridge, or `bash daemon/sign.sh <bin> <id>` for the rest, which is exactly the remedy
string the signature test prints on failure.

**Reversibility limit:** nothing in the repository restores a keychain grant that an
ad-hoc signature has already invalidated. Re-signing correctly restores the *stable
requirement* for future grants; re-approving the prompt is a human action at the OS
dialog, and no script can perform it. This document did not run `codesign` or inspect
a keychain ACL and asserts nothing about the current signature state of any binary on
this machine.

**Retirement evidence:** none. There is no registry, manifest or log of which
signature an artifact previously carried, so a retired signature leaves no trace.

**Partial failure behaviour:** two shapes, and both exit 0. `sign.sh` falls back to
ad-hoc `-` with a stderr warning when no Apple Development identity is found — the
warning itself states the consequence, that "keychain Always-Allow will NOT survive
rebuilds; Argus.app notifications will not display" — so a machine with no identity
produces a successfully-signed-looking release that is degraded. Separately, each of
the four `devenv.nix` `enterShell` build blocks ends in `|| true` (`devenv.nix:139-160`),
which masks the exit *status*, not the output: every block echoes a progress line
naming what it is building before it runs, and neither the compiler's nor `sign.sh`'s
stderr is redirected, so a failed compile or a failed signature does print its
diagnostic into the terminal. What `|| true` costs is detectability — the shell still
opens green, so the only thing that reacts to a failure is the `compile && sign` chain
inside the three blocks that have one (a failed compile skips its signature), and no
exit status carries either failure onward. The explicit builders are
stricter: `wa-build`, `build-wkfetch.sh` and `notifyd/build.sh` all `set -euo
pipefail`, though `notifyd/build.sh` still degrades gracefully to `.icns`-only with
a warning when `actool` is absent.

**Re-entry behaviour:** asymmetric, and this is the sharpest edge in the unit.
Re-running an explicit builder rebuilds and re-signs. Re-entering the devenv shell
does not: each `enterShell` block's `if [ ! -x <path> ]` guard means an artifact that
is present but wrongly signed is left exactly as it is. Recovering from a bad
signature therefore requires knowing to run the explicit path, which the signature
test's failure message spells out.

