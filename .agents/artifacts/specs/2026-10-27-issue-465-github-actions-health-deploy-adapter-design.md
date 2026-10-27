# A GitHub Actions deploy adapter verified by a health commit — issue 465

Design for https://github.com/fagenorn/nix-config/issues/465. Base: `5ae1b9dc`
(`origin/main`). Approval source: autonomous (`--auto`), decision ledger. A bare
"Dn" cites this spec's ledger; "124 D1" cites
`2026-10-09-issue-124-release-profiles-forge-adapter-design.md` and "368 D2"
`2026-10-11-issue-368-publication-free-release-profile-design.md`.

## Triage

Lane triage: input signals contract_change=hit, concurrency_or_persistence=doubt, open_design_questions=hit, criteria_shape=hit; verdict {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape","risk_path"],"lane":"full","mode":"shadow"}; ran: full (shadow).

## Problem

JarBird deploys on every push to `main`. The deploy is a GitHub Actions workflow
(`deploy.yml`) that builds images, ships them to a VPS and checks that
`https://jarbird.com/health` reports the merge commit in a `commit` field. Its
owner wants `/ship-release` Phase 5 to confirm that each release reached
production. Today nothing can do that:

- **No adapter watches an Actions deploy.** The closed adapter registry holds only
  `github-forge`. ship-release §5d's only spelled-out adapter is Railway; any other
  adapter "follows 5a–5c" from prose and command values.
- **The resolver refuses every binding that would turn the watch on.** JarBird has a
  release profile (`forge-main`, publication-free, which the lifecycle guard's
  derived row needs). With profiles present, `capabilities.deploy` must be
  `unsupported` (124 D1's dual-authority rule). A supported deploy must also name a
  `commands` entry. The issue's repro therefore returns `invalid_contract`
  (`contract.capabilities.deploy.binding_incomplete`) with violations at
  `/bindings/deploy/command` and `/capabilities/deploy/support`.
- **A 200 is not proof.** A failed Actions deploy that auto-rolls back keeps serving
  the old build, and its health endpoint still answers 200. Only the commit that the
  endpoint reports, read together with the run's conclusion, tells success from a
  silent rollback.

The owner wants three outcomes (the issue's acceptance criteria):

- **AC1.** The resolver accepts a JarBird-shaped project (release profile
  `forge-main` plus this adapter) and reports deploy watching as available.
- **AC2.** ship-release Phase 5 polls this adapter to the §5c invariant (a run
  succeeded at `MERGE_SHA` and the health commit matches), with no prose-only
  fallback.
- **AC3.** Tests cover the config schema, the success / intermediate /
  silent-rollback classification and resolver acceptance.

## Solution

1. **A registered adapter.** `github-actions-health` joins `release_adapter.REGISTRY`.
   It has one operation, `deploy`, in the `publication_triggered` activation mode,
   whose `inspect` reads the newest Actions runs and the health endpoint and returns
   one closed effect `Observation` (D2, D6–D8). No profile may bind the operation
   yet, so the adapter's `invoke` refuses every request.
2. **The deploy binding names it.** `bindings.deploy` stays the one place deploy
   watching is declared (D1). A deploy binding that names a registered adapter
   carries `command: null`, and its `config` is checked against the operation's
   closed config schema. When `capabilities.deploy` is supported, the resolver
   reports it `available` once the adapter's declared executables are on `PATH`
   (D3).
3. **The dual-authority rule is narrowed, not dropped.** Release profiles and a
   supported deploy capability may coexist when the deploy binding names a
   registered adapter and no profile declares activation units (D4).
4. **One read command.** `release deploy inspect --commit <MERGE_SHA>` resolves the
   project and builds the adapter request from the bindings. It unsets the tracker's
   credential variables and prints the observation (D5, D10).
5. **ship-release Phase 5 polls that command.** Each outcome maps onto §5c. A
   refusal stops the phase and never falls back to prose (D11).

## Decisions

### Where deploy watching lives (AC1)

Deploy watching stays in the bridge-era `bindings.deploy` / `capabilities.deploy`
pair that 124 D1 kept for ship-release Phase 5 (D1). It does not become an
activation unit in a release profile, for three reasons:

- JarBird's `forge-main` is publication-free, and a publication-free profile must
  have `activation: "none"` because an activation needs a publication receipt
  (368 D2).
- No release path consumes a profile's activation phase. ship-release has not yet
  migrated onto the core (#128).
- JarBird's real trigger is the release merge, and the forge's `pr_merge` is
  `unsupported` (`target_cas_unproven`).

The adapter is still built as a release adapter (D2). #128 can then bind the same
module as an activation unit by declaring the operation supported. It will not need
a second adapter.

"Deploy watching available" means `capabilities.deploy.state == "available"` in the
resolved snapshot. No snapshot member is added. `bindings.deploy` passes through
unchanged, and `capabilities.release` keeps its own derivation (for JarBird it stays
`unsupported`, per 368 D4).

### The adapter (`github-actions-health`)

A new standard-library module beside `forge_adapter`. Its public surface is exactly
`describe`, `inspect` and `invoke` (124 D7). `describe()` returns a fresh
descriptor:

| Member | Value |
|---|---|
| `name` / `adapter_contract_version` | `github-actions-health` / `1.0.0` |
| `operations.deploy` | `mode: publication_triggered`, `support: unsupported`, `reason: bridge_watch_only`, `inspect: supported`, `mutability: in_place`, `effects: [reversible_no_incremental_spend]`, `recovery_capable: false`, `candidate_members: []`, `config_schema_version: 1`, closed `config_schema` below |
| `predicates` | `publication_visible: unsupported` (`no_publication_mode`), `running_subject_identity: unsupported` (`bridge_watch_only`) |
| `collector` | `max_collection_latency_ms: 30000`, `max_concurrent_collections: 1` |
| `target_kinds` | `github_repository: [branch, repository]` |
| `credential_classes` / `executables` / `host_capacity` | `[gh_cli]` / `[gh]` / `not_required` |

The config schema is closed, and all five members are required:

| Member | Type |
|---|---|
| `workflow` | `string` |
| `branch` | `string` |
| `services` | `string_list` |
| `health_url` | `string` |
| `health_commit_field` | `string` |

`release_adapter.CONFIG_TYPES` gains `string_list`: a non-empty list of unique
non-empty strings, kept in authored order. `config_problems` judges it the way it
judges the other types (D9). The forge descriptor uses none of the config types, so
its descriptor digest and every profile digest stay the same.

`release_adapter` gains one helper, `watch_operation(descriptor)`. It returns the
name of the descriptor's single operation whose mode is an activation mode and whose
`inspect` is `supported`, or `None` when there is no such operation or more than
one. The resolver and the command both read the watch operation through it.

**`inspect(request)`** never raises and never mutates. A request outside the closed
shape is `unknown`/`parameters_invalid`. An effect request is
`{kind: "effect", operation: "deploy", parameters}`, and `parameters` holds exactly:

- `target`: `{kind: github_repository, repository, branch}`;
- `candidate`: `{commit: <40 lowercase hex>}`;
- `config`: the closed config above.

The forge's tolerated `action` and `operation` members may also appear. The inner
checks are:

- `config` conforms to the schema;
- `config.branch == target.branch`;
- `health_url` parses with scheme `http` or `https` and a non-empty host;
- `services` echoes as given.

A failed inner check is `parameters_invalid`, with a bounded detail that names the
member. A predicate request answers `unknown` with reason `predicate_unsupported`.

**`invoke(request)`** returns `{result: rejected, error_class: unsupported_operation,
reference: "deploy: bridge_watch_only"}` and starts no child process, which matches
the forge's refusal of `pr_merge`.

### The reads (D6–D8)

Both reads share one 30-second collection deadline, as the forge does.

**Run list.** The adapter runs `gh run list --repo <target.repository> --workflow
<workflow> --branch <branch> --limit 5 --json
databaseId,status,conclusion,headSha,headBranch,createdAt`. It runs by name with
stdin at `/dev/null`, within the remaining deadline. Its environment is passed
through unchanged: the adapter strips no variable itself (D10).

- Each entry must have:
  - `databaseId`: a positive integer;
  - `status`, `headBranch` and `createdAt`: non-empty strings;
  - `headSha`: 40 hex characters;
  - `conclusion`: a string, which is non-empty when `status == completed`.

  Anything else is `payload_invalid`.
- A failed `gh` maps to one of `lookup_failed`, `lookup_timeout`,
  `executable_missing` or `payload_invalid`, as the forge's runner maps it. Its
  bounded stderr goes in `facts.detail`.
- Each entry maps to the `{id, status, commit, branch, createdAt}` shape §5c
  expects:
  - `status` is the `conclusion` when the run is completed and the run `status`
    otherwise;
  - `commit` is the `headSha`.

**Health read.** The adapter reads health only when the selected run (below) is
completed. It sends one stdlib `urllib` `GET <health_url>`:

- headers `Accept: application/json`, `Cache-Control: no-cache` and a fixed
  `User-Agent`;
- no redirect is followed, so a 3xx counts as an unreachable endpoint (the proof
  must come from the authored URL);
- at most 65,536 bytes are read;
- the timeout is the deadline's remainder.

The result is one of:

- **`ok`**: status 200, and the body is a UTF-8 JSON object, strictly loaded with
  `canonical.reject_duplicate_keys` and `reject_nonfinite_literal`, whose top-level
  `<health_commit_field>` is a string of 7–40 hex characters. The value is the
  health commit.
- **`health_unreachable`**: a connection error, a timeout or any non-200 status. The
  status and the first 240 characters of the body go in the detail.
- **`health_payload_invalid`**: any other body.

**Commit match (D7).** A reported commit matches `MERGE_SHA` when it is 7–40 hex
characters and `MERGE_SHA` starts with it, compared case-insensitively. A run's
`headSha` is always 40 characters, so for runs the rule is equality. For health it
also accepts the short SHA that §5c warns platforms store.

### Classification (D6)

The **selected run** is the newest entry by `createdAt` whose commit matches
`MERGE_SHA` and whose `headBranch` equals `config.branch`. Only the newest run at
`MERGE_SHA` decides. An older failed run at the same commit is the §5c "stale
FAILED" case, and it stays visible in `facts.runs`.

| Selected run | Health read | `outcome` | `reason` |
|---|---|---|---|
| none | not read | `absent` | `run_absent` |
| not `completed` | not read | `in_progress` | `run_in_progress` |
| `completed` / `success` | `ok`, matches | `satisfied` | `deployed` |
| `completed` / `success` | `ok`, does not match | `diverged` | `health_commit_mismatch` |
| `completed` / `success` | not `ok` | `unknown` | `health_unreachable` or `health_payload_invalid` |
| `completed` / any other conclusion | `ok`, does not match | `diverged` | `silent_rollback` |
| `completed` / any other conclusion | `ok` and matches, or not `ok` | `diverged` | `run_failed` |

`satisfied` is reachable only through the third row. That row is the §5c invariant:
a terminal success at `MERGE_SHA` on the watched branch, plus a health commit match.
Every observation carries the following fields:

- `observed_subject`: `{commit: <health commit or null>, run: <selected id or null>}`;
- `references`: `repos/<slug>/actions/runs/<id>` for the selected run, then the
  health URL when it was read;
- `facts`: `{runs, run, health, services}`, plus `detail` on a failed `gh` read.
  `runs` holds every mapped entry, newest first. `run` is the selected entry or
  `null`. `health` is `null` or `{status, http_status, commit, detail}`.

### Resolver acceptance (D3, D4)

`validate_deploy` gains rules that apply only when `bindings.deploy.adapter` is a
key of `release_adapter.REGISTRY`. They apply whatever the authored support, because
they judge shape:

- **`contract.deploy.adapter_unwatchable`**, at `/bindings/deploy/adapter`: the
  adapter has no single watch operation (`watch_operation` is `None`). For example,
  `github-forge`.
- **`contract.deploy.command_conflict`**, at `/bindings/deploy/command`: `command`
  is not `null`, because the registered adapter is the deploy command.
- **`contract.deploy.config_invalid`**, at `/bindings/deploy/config`: one violation
  per `config_problems` entry against the watch operation's schema. This check is
  skipped when the adapter is unwatchable.

An unregistered adapter name other than `none` (for example `railway`) keeps today's
rules: a free-form `config`, and a `command` that is required when deploy is
supported.

The completeness rule (`contract.capabilities.deploy.binding_incomplete`) changes in
one row. When deploy is supported, `command` must be non-null unless the adapter is
registered. The `adapter != none` row is unchanged.

Readiness: for a registered adapter, the supported deploy capability is `available`
when every descriptor `executables` entry resolves on `PATH` from the project root.
Otherwise it is `blocked` with the existing reason code `release_adapter_unavailable`
and repair `capability.deploy.release_adapter_unavailable`. An unregistered adapter
keeps the `command_missing` check. `REASON_CODES` is unchanged.

The grammar's `deploy_conflict` rule (124 D1) allows profiles together with a
supported deploy capability exactly when two things hold:

- `bindings.deploy.adapter` is a key of the descriptor registry the grammar was given;
- no profile authors `activation` as `{units}`.

Every other case keeps today's violation at `/capabilities/deploy/support`. The
condition reads only the adapter's registration, so an unwatchable registered adapter
is reported once, by `validate_deploy`. Both rules preserve the invariant that 124 D1
protects: at most one authority declares activation. The grammar's docstring gains
`bindings.deploy.adapter` among the members it reads.

The issue's JarBird shape resolves with `capabilities.deploy` `available` when `gh`
is on `PATH`.

### The `release deploy inspect` command (D5)

The existing `release` command gains the subcommand `release deploy inspect --commit
<sha> [--repo-root PATH]`. It needs no new launcher and no row in the command table.
It is a thin shell (agent-helpers rule 2), and it runs these steps in order:

1. If `--commit` is not 40 lowercase hex characters, it exits 2 with `parameters_invalid`
   (repair `release.deploy.commit_invalid`).
2. It calls `resolve(repo_root, required=["deploy"])`. A refusal, including
   `capability_unavailable` for an unsupported or blocked deploy, reaches the caller
   byte for byte with exit 2.
3. If `bindings.deploy.adapter` is not registered, it exits 2 with
   `deploy_adapter_unregistered` (repair `release.deploy.adapter_unregistered`):
   that binding's command is the deploy reader.
4. It removes every name in `bindings.tracker.credential_env.unset_before_invocation`
   from its own process environment (D10).
5. It calls the adapter's `inspect` with:
   - operation `watch_operation(descriptor)`;
   - target `{kind: github_repository, repository: bindings.tracker.repo_slug, branch:
     bindings.vcs.default_branch}`;
   - candidate `{commit}`;
   - config `bindings.deploy.config`.
6. It prints the observation as compact sorted-key JSON and exits 0, whatever the
   outcome. A read never mutates, so the outcome is data, not an exit status.

`release adapter inspect github-actions-health deploy --parameters <json>` keeps
working for diagnosis, because the operation's `inspect` is supported. That path
resolves no project (124 D15), so the caller's environment governs it.

### ship-release Phase 5 (AC2, D11)

§5 keeps its skip rule (`deploy.adapter == none`) and its state transitions. §5d
gains the registered-adapter path. It applies when retained `bindings.deploy.command`
is `null`. For a supported deploy, the resolver allows `null` only for a registered
adapter. Each poll is the single line

```bash
${GH_PREFIX}release deploy inspect --repo-root <checkout> --commit <MERGE_SHA>
```

Each outcome maps onto 5c:

| Observation | Phase 5 action |
|---|---|
| `satisfied` | Success. Set `deployState: done`. |
| `in_progress` | Intermediate. Log one progress line and wake again. |
| `absent` | Intermediate, under 5c's three-cycle "not picked up yet" rule; after that, the no-redeploy failure path. |
| `diverged` | Failure path. Pause, pull the build log, ground and surface; `silent_rollback` is named as one. |
| `unknown` / `parameters_invalid` | Stop and surface. It is a binding error. |
| any other `unknown` | Log and poll again. Surface after three consecutive cycles. |
| exit 2 | Stop and surface the refusal exactly. |

The build log comes from `${GH_PREFIX}gh run view <facts.run.id> --repo <repo-slug>
--log-failed`. No 5a–5c step derives a deploy verdict by hand-rolled `gh run list`
or HTTP reads; the command's observation is the only verdict.

The adapter watches one run for every configured service. Actions reports no
per-service state, so 5a's cross-check is the configured `services` list. The Phase
6 report prints one line per service with the shared run id, status and commit.

The existing sentence "any other adapter follows 5a–5c using retained bindings.deploy
command/config values" keeps covering command-bearing adapters, and nothing else.

### Docs

- The package README:
  - "Release adapters" gains a paragraph on `github-actions-health`: descriptor,
    reads, classification table reference, credential rule.
  - The `release` command paragraph gains `deploy inspect`.
  - "Release profiles" restates the narrowed `deploy_conflict` rule.
- The ship-release CHANGELOG's deploy-expectations template line names the
  registered-adapter verdict.

No context or ADR document exists to update, because `knowledge.context` is
unsupported.

### Acceptance mapping

- **AC1**:
  - a resolver test on the issue's literal JarBird contract (publication-free
    `forge-main`, the issue's exact `deploy` member and `support: supported`, a stub
    `gh` on `PATH`) returns `capabilities.deploy` `available` and no violation;
  - the same contract with `gh` absent is `blocked`/`release_adapter_unavailable`.
- **AC2**:
  - command tests show that `satisfied` needs both a successful run at `MERGE_SHA`
    and a matching health commit, and that a 200 with an older commit after a
    successful run is `diverged`;
  - a ship-release contract test pins the §5d command line and the build-log line,
    and asserts that §5 shows no `gh run list` or `curl` example.
- **AC3**: the test seams below.

## Test seams

- **Command over a fake world.** The tests drive `python -m agent_tools.release
  deploy inspect` as a subprocess against a temporary project root. A fake world in
  the `forge_world` style provides:
  - a `PATH`-only bin with a fake `gh` that logs its argv and whether a token
    variable was visible, and answers only the issue's exact `gh run list` argv;
  - a stdlib `http.server` on `127.0.0.1`, in a test thread, that serves configured
    status codes and bodies.

  The tests cover:
  - one test per classification row;
  - a stale-FAILED case (an older failure and a newer success at `MERGE_SHA`
    resolve to `satisfied`);
  - each `unknown` reason, plus the 3xx and oversized-body cases;
  - the typed exit-2 errors;
  - the credential rule: an unset list `[GITHUB_TOKEN, GH_TOKEN]` with the harness
    token set means the fake `gh` sees no token, while `[]` lets it see the token.
    This proves that the binding governs and nothing is hardcoded.

  The fixtures carry production-shaped values: 40-hex SHAs, ISO timestamps, the
  issue's config.
- **Adapter contract, imported.**
  - `config_problems` accepts and refuses `string_list` values;
  - `DESCRIPTORS` builds with the new adapter, and `watch_operation` returns
    `deploy` for it and `None` for `github-forge`;
  - `invoke` refuses without spawning a child, which the fake world's empty call
    log shows.
- **Resolver through `resolve-project resolve`.** The resolver suite covers:
  - AC1's two cases;
  - the three `contract.deploy.*` violations;
  - `railway` with a command and profiles, which still conflicts (the existing test
    stays);
  - a supported registered adapter without profiles, which is `available`.
- **Grammar with injected descriptors.** `grammar_violations` runs with a fixture
  descriptor registry whose adapter supports an activation operation. A profile
  with activation units plus a supported registered deploy binding still reports
  `deploy_conflict`, so the activation clause has a test that fails without it.
- **Skill contract.** `test_ship_release_contracts` pins the two §5d command lines
  and the absence of a hand-rolled deploy read. These are machine-consumed lines
  only (agent-helpers rule 6).

## Out of scope

- JarBird's own `.agents/project.json`; JarBird switches after this lands.
- Other deploy platforms. Railway stays a command-bearing prose adapter.
- Binding the adapter in a profile's activation phase:
  - `support: supported` for `deploy`;
  - a `running_subject_identity` predicate;
  - a `publication_triggered` `invoke`.

  This is #128's migration.
- Retiring `bindings.deploy` (#130), and the ship-release core migration (#128).
- Per-service health endpoints, health JSON paths deeper than one top-level field,
  and following redirects.
- The forge adapter's hardcoded token stripping, which stays as it is.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Deploy watching stays in `bindings.deploy`/`capabilities.deploy`; "available" means `capabilities.deploy.state == available`; no snapshot member is added | 124 D1 (Phase 5 reads the bridge binding); 368 D2 (publication-free ⇒ activation `none`); JarBird's live `forge-main` is publication-free; #128 open; the issue's repro shape | A profile activation unit: JarBird's profile cannot carry one, nothing consumes activation, and the trigger (`pr_merge`) is unsupported |
| D2 | The adapter is a release adapter in the closed `REGISTRY`: one `deploy` operation, `publication_triggered`, `support: unsupported` (`bridge_watch_only`), `inspect: supported`; both predicates unsupported; `invoke` refuses | 124 D7/D19 (one closed registry, describe/inspect/invoke); the bar's framework-first and YAGNI; the core shapes already model this adapter as `publication_triggered` | A separate deploy-watch registry: a second adapter concept and a second schema check. A supported operation now: a core `invoke` and predicate nobody calls |
| D3 | A registered deploy adapter needs `command: null`, a single watch operation and a config that matches its closed schema (three `contract.deploy.*` repairs). Readiness is the descriptor's executables on `PATH`, reusing `release_adapter_unavailable`. Unregistered adapters keep today's rules | The bar's defense in depth (the resolver is the outer check, `inspect` the inner one); `release_capability`'s executable precedent; closed `REASON_CODES` | A `commands` entry pointing at the read command: plumbing the contract can derive. A new reason code: same meaning as an existing one |
| D4 | `deploy_conflict` permits profiles plus a supported deploy only when the deploy adapter is registered and no profile authors activation units | 124 D1's purpose (one activation authority); the grammar's report-once rule; the descriptor-injection seam | Dropping the rule: a future activation adapter would reopen dual authority silently. Requiring a watch operation here: double-reports an unwatchable adapter |
| D5 | Phase 5 reads `release deploy inspect --commit <sha> [--repo-root]`, which resolves with deploy required, builds the request from the bindings, prints the observation and exits 0; typed refusals exit 2 | The bar's token economy (one short handle per poll); agent-helpers rule 2; 124 D15 keeps `adapter inspect` project-free; `profile inspect` is network-free diagnosis | `release adapter inspect` with a JSON request per poll: the model re-emits slug, branch and config, and the credential binding cannot reach it. `profile inspect`: no network by contract |
| D6 | Classification: only the newest run at `MERGE_SHA` decides; health is read only when that run is completed; outcomes and reasons as in the table; `satisfied` needs a successful run plus a health match | The issue's success and silent-rollback definitions; §5c's stale-FAILED chronology; the bar's truthful terminal states | Reading health on every poll: extra reads with no verdict. Calling a successful run with stale health `in_progress`: hides a deploy that claims success but serves the old build |
| D7 | A commit matches when it is 7–40 hex and `MERGE_SHA` starts with it (case-insensitive), for both runs and health | §5c ("startswith…never strict =="); the issue's `==` holds for a full SHA; the 7-char floor stops trivial prefixes | Strict 40-hex equality: a health endpoint that reports a short SHA never succeeds |
| D8 | Health read: stdlib `urllib` GET, http/https only, no redirects, a 64 KiB cap, a strict JSON load through the `canonical` hooks, a top-level field of 7–40 hex, inside the shared 30 s budget, failure detail bounded to 240 chars | Python shard (no undeclared dependency); agent-helpers rule 4; the bar's log-the-body rule; `urllib` opens `file://` unless the scheme is checked | `requests`/`curl`: undeclared dependencies. Following redirects: the proof could come from another URL |
| D9 | `CONFIG_TYPES` gains `string_list` (non-empty, unique, non-empty strings, ordered). The issue's five members stay as given, including `branch`, which `inspect` refuses unless it equals `target.branch` (the default branch) | The issue's stated closed schema; JarBird's planned config; the bar's defense in depth | A comma-joined `services` string: a shape the author did not ask for. Dropping `branch`: departs from the issue. A resolver check by member name: an adapter-specific special case in the generic resolver |
| D10 | The command removes `credential_env.unset_before_invocation` names from its own environment before `inspect`; the adapter strips nothing itself | The issue ("respect … for every gh call"); ship-release's `GH_PREFIX` meaning of "unset before invocation"; JarBird lists both token names | Hardcoding the forge's pair: ignores the binding. Adding the list to the request: plumbing in every adapter call |
| D11 | Phase 5's registered-adapter path (when `command` is `null`) polls the D5 line and maps outcomes as in the table; `parameters_invalid` and exit 2 stop; three consecutive other `unknown`s surface; the build log uses `gh run view <id> --log-failed`; the report prints one line per configured service | The issue's AC2 ("no prose-only fallback"); existing 5c cadence and three-cycle rule; the issue's build-log command | A prose `gh run list` plus health read in the skill: the fallback AC2 forbids. Per-service runs: Actions reports none |
| D12 | Test seams: the command as a subprocess over a fake `gh` and a loopback `http.server`; the resolver through `resolve-project`; the grammar with injected descriptors; skill-contract pins of the two §5d lines only | The `forge_world` precedent; agent-helpers rules 5 and 6; the bar's tests that can fail (production-shaped fixtures; the activation clause turns red without its rule) | Mocking `urllib`/`subprocess` in process: asserts calls, not behaviour. A live JarBird read: not deterministic |
