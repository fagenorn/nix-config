# Host-local launchd activation and locally signed release units — issue 547

Design for https://github.com/fagenorn/nix-config/issues/547. Base: `328f08da` (`origin/main`).
Approval source: autonomous (`--auto`), decision ledger. A bare "Dn" cites this spec's ledger;
"124 D7" cites `2026-10-09-issue-124-release-profiles-forge-adapter-design.md`, "465 D3"
`2026-10-27-issue-465-github-actions-health-deploy-adapter-design.md`, "368 D2"
`2026-10-11-issue-368-publication-free-release-profile-design.md` and "128 D1"
`2026-11-02-issue-128-ship-release-release-core-design.md`. "The evidence" is
`2026-08-20-release-lifecycle-seams-research.evidence/release-unit-mechanics.md`, sections
"Argus launchd daemon rooted in a checkout" and "Locally signed Argus helpers".

## Triage

Input:
```json
{"signals": {"contract_change": {"value": "hit", "evidence": "adds adapter descriptors, operations, config schemas and predicates to the closed release adapter registry (python/agent_tools/release_adapter.py REGISTRY), a public #124 contract surface"}, "concurrency_or_persistence": {"value": "doubt", "evidence": "the new activation adapter mutates host-persisted launchd/plist and installed-bundle state outside the repo, though no ledger or lock state changes"}, "open_design_questions": {"value": "hit", "evidence": "adapter split (one vs two adapters), signed-artifact publication mode, running-identity predicate shape and invoke scope are all open"}, "criteria_shape": {"value": "no", "evidence": "three acceptance criteria, each checked by compiling a fixture profile and running the release, conformance and adoption suites"}}, "paths": ["python/agent_tools/release_adapter.py", "python/agent_tools/launchd_agent_adapter.py", "python/agent_tools/signed_artifact_adapter.py", "python/agent_tools/release_profile.py", "python/README.md", "tests/test_release_adapter_core.py", "tests/test_release_profile.py", "tests/test_release_grammar.py", ".agents/artifacts/specs/2026-11-02-issue-547-host-local-release-units-design.md"]}
```
Verdict: `{"hits":["contract_change","concurrency_or_persistence","open_design_questions"],"lane":"full","mode":"shadow"}`
ran: full (shadow)

## Problem

Argus adoption (#129) stopped at a contract gap. Argus releases two units that no release profile
can describe:

- **A per-user launchd agent.** Label `dev.argus.daemon` in `gui/<uid>`. Its plist is written to
  `~/Library/LaunchAgents/<label>.plist`, then `launchctl bootout` and `bootstrap` run. The agent
  runs `devenv shell -- daemon run` from the checkout, and nothing records which commit it runs.
- **A locally signed helper bundle.** The build signs `Argus.app` with `ARGUS_CODESIGN_IDENTITY`
  or the first `Apple Development` identity, falling back to an ad-hoc signature. The bundle is
  copied to `~/Library/Application Support/Argus/Argus.app`, because Notification Center records
  the on-disk path of the posting app.

The closed adapter registry holds `github-forge` and `github-actions-health`. Neither can install
or activate anything on the host, and 124 left every non-forge adapter out of scope. #71's
contract-gap rewind puts the fix in the owning core or adapter module, with no Argus literal and no
Argus-local workaround. The owner wants three outcomes (the issue's acceptance criteria):

- **AC1.** A release profile declares both Argus units and compiles through the 124 profile and
  adapter contract with no violations.
- **AC2.** No Argus literal enters central policy or the adapter registry.
- **AC3.** The existing forge and actions-health profiles (nix-config, Nodo) compile unchanged,
  and the release, conformance and adoption suites stay green.

## Solution

1. **Two registered adapters** (D1). `codesigned-artifact` has one publication operation,
   `install` (`materialize`). It copies a bundle the checkout built, stamps the candidate into the
   bundle's `Info.plist`, signs it under a declared identity policy and swaps it into a fixed path
   under the user's home. `launchd-agent` has one activation operation, `activate` (`local_apply`).
   It renders a plist that carries the candidate, then boots the agent out and back in, in the
   user's GUI domain. Both operations are supported, and their `invoke` really runs `codesign`,
   `security` and `launchctl` (D3).
2. **Identity is stamped, then read back** (D4). The bundle's identity is sealed by its own
   signature. The agent's identity is the stamp in the loaded job plus its checkout at the
   candidate commit. That gives the core's derived `publication_visible` and
   `running_subject_identity` predicates something to observe. One authored predicate,
   `agent_running`, gives a profile liveness evidence it can require (D5).
3. **Neutral vocabulary only.** Target kinds `installed_bundle` and `launchd_gui_agent`,
   credential classes `codesigning_identity` and `gui_session`, and closed config schemas. Every
   Argus value lives in a test fixture profile (D7, D8).
4. **One contract tightening.** `release_adapter.watch_operation` now names only a
   `publication_triggered` operation, so a `local_apply` adapter can never become a bridge-era
   deploy watch (D10). The grammar, compiler, resolver and driver are otherwise unchanged (D11).

## Decisions

### The two adapters (D1, D2, D3)

Each adapter is one standard-library module, `agent_tools.codesigned_artifact_adapter` and
`agent_tools.launchd_agent_adapter`. Each imports only the standard library and
`agent_tools.canonical`, and each exposes exactly `describe`, `inspect` and `invoke` (124 D7,
465 D14). `release_adapter.REGISTRY` gains both, so `DESCRIPTORS` builds and checks them at
import, which `just build` runs.

| Member | `codesigned-artifact` | `launchd-agent` |
|---|---|---|
| `adapter_contract_version` | `1.0.0` | `1.0.0` |
| operation | `install`: `materialize`, `in_place` | `activate`: `local_apply`, `in_place` |
| `support` / `inspect` | `supported` / `supported` | `supported` / `supported` |
| `effects` | `[reversible_no_incremental_spend, irreversible]` | same |
| `recovery_capable` / `candidate_members` / `config_schema_version` | `false` / `[]` / `1` | same |
| `predicates` | `publication_visible: supported`; `running_subject_identity: unsupported` (`no_activation_mode`) | `publication_visible: unsupported` (`no_publication_mode`); `running_subject_identity: supported`; `agent_running: supported` |
| `collector` | `{max_collection_latency_ms: 30000, max_concurrent_collections: 1}` | same |
| `target_kinds` | `installed_bundle: [path]` | `launchd_gui_agent: [label]` |
| `credential_classes` | `[codesigning_identity]` | `[gui_session]` |
| `executables` | `[codesign, git, security]` | `[git, launchctl]` |
| `host_capacity` | `not_required` | `not_required` |

The signed bundle is a publication because #81 names a signed binary's identity as a publication
artifact identity. The launchd agent is an activation because #84 names Argus install and restart
as `local_apply`. An activation also needs a publication receipt (368 D2), so the Argus profile
publishes the bundle and then activates the agent, matching Argus's own install order.

Both operations declare both effect classes, so the profile states the truth per unit. For
example, Argus's state database migrates forward when the daemon starts, which is the evidence's
reversibility limit, so its fixture marks the daemon `irreversible` and the bundle reversible.
Rollback characteristics use the existing vocabulary: `in_place` mutability, no recovery-capable
operation, and the profile's recovery posture. Nothing retains the prior plist or bundle, so the
fixture's units are `supersedable_only`: a rollback is a new release of older sources (D2).

**Shared rules (D3, D6, D12, D15).**

- **Executables by name.** Every child runs by name on `PATH`, with stdin at `/dev/null` and the
  caller's environment unchanged. No GitHub call is made.
- **Inner checks.** Each module checks its own inner shapes. A request outside the closed shape
  is `invalid_input` from `invoke`, with no child process, and `unknown`/`parameters_invalid` from
  `inspect`. An undeclared operation is `rejected`/`unsupported_operation`. The forge's tolerated
  `action` and `operation` members may appear. A target is its kind's members plus an optional
  `handle`. A candidate is `{version: vMAJOR.MINOR.PATCH, commit: <40 lowercase hex>}`.
- **Authority.** Both `invoke`s refuse to run as uid 0 (`rejected`/`authorization_denied`). The
  authority boundary is the invoking user's own GUI session and home directory.
- **Checkout at the candidate.** Both `invoke`s take the checkout from
  `git rev-parse --show-toplevel` in the working directory (124 D23). Before any write, both
  require `git -C <root> rev-parse HEAD` to equal the candidate commit, and
  `git -C <root> status --porcelain --untracked-files=no` to print nothing. A failure is
  `rejected`/`precondition_failed`.
- **Budgets.** `inspect` never raises and never mutates, and it runs every child under one
  30-second deadline (the collector's latency). `invoke` runs under one deadline: 60 seconds for
  `activate`, 120 seconds for `install`, because `codesign` may wait on a keychain prompt.
- **Failure mapping.** A failure before the first host write is `rejected`. A timeout is
  `transient_transport`. A child that cannot start, or a precondition read that exits non-zero,
  is `provider_unavailable`. A precondition the world refuses, a non-zero signing exit included,
  is `precondition_failed`. A failure after the first host write is
  `unknown`/`transient_transport`, because the effect may have landed and the core's next
  inspection decides (124 D23).
- **Observations.** Child failures map to the reasons `lookup_failed`, `lookup_timeout`,
  `executable_missing` and `payload_invalid`, as the forge's runner maps them. Bounded stderr, at
  most 240 characters, goes in `facts.detail`.
- **`absent` means not this candidate.** The driver invokes only after an `absent` inspection,
  and the core refuses `not_absent` otherwise. So a target that holds an older release, or an
  install the adapter did not make, inspects `absent`, and the release replaces it. Only a state
  the adapter must not overwrite is `diverged`: a symlink, a wrong file type, or a job loaded from
  another plist (D6).
- **No guard call.** `codesign`, `security` and `launchctl` are not lifecycle-guard verbs, and
  `invoke` is reachable only through the core under the driver's grants (124 D15). So neither
  adapter runs `claude-bash-lifecycle-guard` (D12).

### `codesigned-artifact` (D7, D8, D9)

**Target** `installed_bundle`: `path` must start with `~/`, which expands to `$HOME`. It may not
contain a `..` segment, an empty segment or a control character.

**Config**, closed:

| Member | Type | Required | Meaning |
|---|---|---|---|
| `source` | `string` | yes | Checkout-relative path of the built bundle (no `..`, not absolute) |
| `identity_prefix` | `string` | yes | Sign with the first valid codesigning identity whose name starts with this |
| `identity_env` | `string` | no | Name of an environment variable whose non-empty value overrides the prefix search |
| `adhoc_fallback` | `boolean` | yes | Whether to sign ad-hoc when no identity is found |

**`invoke`** takes these steps in order and stops at the first refusal:

1. It runs the shared shape, authority and checkout checks.
2. **Source check.** `<root>/<source>` must be a real directory whose `Contents/Info.plist` loads
   with `plistlib` as a dictionary. Otherwise `precondition_failed`.
3. **Identity.** It parses `security find-identity -v -p codesigning` for lines of the form
   `N) <40-hex> "<name>"`.
   - When `identity_env` names a set, non-empty variable, its value must equal a listed name or
     hash.
   - Otherwise the first name that starts with `identity_prefix` is used.
   - The adapter signs with the matched identity's hash.
   - With no match, it signs ad-hoc (`-`) only when `adhoc_fallback` is true. Otherwise it
     refuses `precondition_failed` with `no_signing_identity`.
   - An env value that matches nothing is refused the same way and never falls back.
   - A failed `security` read refuses before any write.
4. **Install path check.** An existing install path that is a symlink or not a directory is
   `precondition_failed`.
5. **Staging.** It creates the parent directory and removes stale `.<name>.release-staging` and
   `.<name>.release-previous` siblings. Then it copies the source into staging with symlinks
   preserved, and sets the `Info.plist` keys `AgentReleaseVersion` and `AgentReleaseCommit`,
   keeping the file's XML or binary format. It runs
   `codesign --force --sign <hash or -> <staging>` with no entitlements and no runtime options.
   Then `codesign --verify --deep --strict <staging>` must pass. On any failure it removes staging
   and returns `rejected`. The install path has not been touched.
6. **Swap.** It renames any existing bundle to the previous sibling, renames staging to the
   install path, and removes the previous sibling. The first rename is the first host write.
   Success is `accepted`.

Building the bundle stays outside the adapter. It is a project command that runs before the
release. The adapter installs exactly what the checkout holds when HEAD is the candidate and no
tracked file is modified. It cannot prove that the bundle was built from that commit, and the
package README states this limitation (D9).

**`inspect`** classifies the install path. Each row applies once the rows above it do not.
"Stamp" means the two `Info.plist` keys.

| State | `outcome` | `reason` | `publication_visible` |
|---|---|---|---|
| no entry | `absent` | `bundle_absent` | `unsatisfied`/`ref_absent` |
| a symlink, a non-directory, or no readable `Contents/Info.plist` dictionary | `diverged` | `target_unexpected` | `unsatisfied`/`subject_mismatch` |
| no stamp | `absent` | `bundle_unmanaged` | `unsatisfied`/`subject_mismatch` |
| stamp of another candidate | `absent` | `bundle_other_release` | `unsatisfied`/`subject_mismatch` |
| `codesign --verify --deep --strict` exits 1 or 3 | `diverged` | `signature_invalid` | `unsatisfied`/`digest_mismatch` |
| `codesign -d --verbose=2` shows `Signature=adhoc` while `adhoc_fallback` is false | `diverged` | `signature_policy` | `unsatisfied`/`subject_mismatch` |
| otherwise | `satisfied` | `installed` | `satisfied`/`installed` |
| a failed read | `unknown` | the failure reason | `unknown`/`store_unreachable` |

The predicate's non-satisfied reasons stay inside the core's closed
`published_artifact_identity` space. Other observation members:

- `observed_subject` is `{version, commit}` from the stamp, plus the signing `identifier` and
  first `authority`, or `null`.
- `references` is `[<absolute install path>]`.
- `facts` is `{path, stamp, signature}`, where `signature` is
  `{identifier, authority, team_identifier, adhoc}` or `null`.

### `launchd-agent` (D7, D8)

**Target** `launchd_gui_agent`: `label` matches `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. The domain
is always `gui/<os.getuid()>`, and the plist is always `~/Library/LaunchAgents/<label>.plist`. The
kind fixes the authority boundary, so a profile cannot name another domain.

**Config**, closed:

| Member | Type | Required | Meaning |
|---|---|---|---|
| `program` | `string` | yes | Bare command name with no `/`, resolved on `PATH` at invoke time to the absolute `ProgramArguments[0]` |
| `arguments` | `string_list` | no | `ProgramArguments[1:]` |
| `keep_alive` | `boolean` | yes | `KeepAlive` |
| `background` | `boolean` | no | `true` renders `ProcessType` `Background`; otherwise no `ProcessType` key |
| `stdout_path`, `stderr_path` | `string` | no | Checkout-relative log paths (no `..`, not absolute) |

The adapter renders the plist with `plistlib`. `WorkingDirectory` is always the checkout root and
`RunAtLoad` is always true, because an activation must leave the agent running. The rendered
`EnvironmentVariables` hold exactly `AGENT_RELEASE_VERSION` and `AGENT_RELEASE_COMMIT`.
`ProgramArguments[0]` is the path `shutil.which` returns, not wrapped in `/bin/wait4path` (D18).

**`invoke`** takes these steps in order and stops at the first refusal:

1. It runs the shared shape, authority and checkout checks.
2. **Program.** `shutil.which(program)` must resolve. Otherwise `precondition_failed`.
3. **Plist path.** An existing plist path that is a symlink or not a regular file is
   `precondition_failed`.
4. **Loaded state.** It runs `launchctl print gui/<uid>/<label>`.
   - Exit 113 means the agent is not loaded.
   - Exit 0 means it is loaded, and the job's `path` must be the managed plist. Otherwise
     `precondition_failed`.
   - Any other exit is `rejected`/`provider_unavailable`.
5. **Bootout.** If the agent is loaded, it runs `launchctl bootout gui/<uid>/<label>`. A non-zero
   exit is `rejected`/`transient_transport`, since the job is still loaded. A timeout is `unknown`.
6. **Plist write.** It writes the rendered plist atomically with mode 0644: a temporary file in
   the same directory, then `os.replace`. It creates `~/Library/LaunchAgents` when missing.
   The bootout, or this write when nothing was loaded, is the first host write.
7. **Bootstrap.** It runs `launchctl bootstrap gui/<uid> <plist>`. Exit 0 is `accepted`; anything
   else is `unknown`.

Install, restart and status are one operation and its inspection. Every release re-renders the
stamp, so every release boots the agent out and in, which restarts it. `kickstart -k` is never
needed (D2).

**`inspect`** reads the plist path with `lstat` and then runs `launchctl print gui/<uid>/<label>`.
From the print it reads these top-level lines: `path`, `state`, `pid`, `runs`,
`working directory`, and the `environment = {` block of `K => V` lines.

- A missing `path`, `state` or `runs` line is `payload_invalid`.
- When the stamp names the candidate, it also runs `git -C <working directory> rev-parse HEAD`
  and `git -C <working directory> status --porcelain --untracked-files=no`.

| State | `outcome` | `reason` | `running_subject_identity` |
|---|---|---|---|
| the plist path is a symlink or non-regular | `diverged` | `plist_unexpected` | `unsatisfied`/`subject_mismatch` |
| `print` exits 113 | `absent` | `agent_not_loaded` | `unsatisfied`/`subject_absent` |
| loaded from another `path` | `diverged` | `agent_path_foreign` | `unsatisfied`/`subject_mismatch` |
| no stamp in `environment` | `absent` | `agent_unmanaged` | `unsatisfied`/`unrelated_subject_running` |
| stamp of another candidate | `absent` | `agent_other_release` | `unsatisfied`/`subject_mismatch` |
| HEAD differs, or tracked changes | `diverged` | `checkout_moved` | `unsatisfied`/`subject_mismatch` |
| `state` is not `running`, or no `pid` | `in_progress` | `agent_not_running` | `unsatisfied`/`subject_absent` |
| otherwise | `satisfied` | `running` | `satisfied`/`running` |
| a failed read | `unknown` | the failure reason | `unknown`/`identity_unobservable` |

The non-satisfied reasons stay inside the core's closed `running_subject_identity` space. Other
observation members:

- `observed_subject` is `{version, commit, pid}`.
- `references` is `[gui/<uid>/<label>, <plist path>]`.
- `facts` is `{label, domain, plist, loaded, path, state, pid, runs, working_directory, stamp,
  checkout}`, where `checkout` is `{head, clean}` or `null`.

### Liveness and the derived predicates (D5)

The core already derives one required `running_subject_identity` snapshot for each activation
unit, and one `publication_visible` event for each publication action. The adapters answer both
through `inspect` with the predicate columns above, so identity evidence is required by
construction.

**Liveness.** A profile may require liveness by authoring an obligation:
`semantic: liveness`, `form: snapshot`, `predicate: agent_running`, the launchd alias as
collector, and usually a dependency on `derived:running_subject_identity:<unit>`. `agent_running`
needs no candidate.

| State | `outcome` | `reason` |
|---|---|---|
| loaded from the managed plist, `state = running`, a `pid` and `runs = 1` | `satisfied` | `running` |
| not loaded | `unsatisfied` | `agent_not_loaded` |
| loaded from another path | `unsatisfied` | `agent_path_foreign` |
| not running, or no `pid` | `unsatisfied` | `agent_not_running` |
| `runs` greater than 1 | `unsatisfied` | `agent_restarted` |
| a failed read | `unknown` | the failure reason |

A bootstrap starts a new job whose `runs` is 1. A KeepAlive restart after a crash raises it. So
`runs = 1` means the agent has not exited since the release activated it.

As with every authored obligation, its `parameters.parameters` must restate the unit's compiled
`action`, `operation`, normalized `target` and `config`, because `core_binding` refuses anything
else (124 D24). Any other predicate request is `unknown`/`predicate_unsupported`.

### Registry and the deploy watch (D10, D11)

`watch_operation(descriptor)` returns the descriptor's single `publication_triggered` operation
whose `inspect` is supported. It returns `None` when there is none or more than one.

- `github-actions-health` still returns `deploy`.
- `github-forge` and `codesigned-artifact` return `None`.
- `launchd-agent` now returns `None`. Under the old activation-mode rule it would have returned
  `activate`, and a deploy binding naming it would resolve, then fail every
  `release deploy inspect` with `parameters_invalid`.

This refines 465 D3's "activation mode". The resolver's `contract.deploy.adapter_unwatchable`
now reports such a binding at resolve time.

Nothing else in the contract changes:

- 124 D1's single activation authority and 465 D4's `deploy_watch_coexists` keep their meaning.
  A profile that authors activation units still forces `capabilities.deploy` unsupported.
- The 128 driver still refuses any `bindings.deploy.adapter` other than `none`.
- The grammar and compiler need no edit. The new kinds, classes, predicates and configs are
  descriptor data, which the grammar already reads generically.
- No profile that binds only the forge or actions-health adapter changes its digest. A profile
  digest covers only the descriptors it binds (124 D17, D23), and neither existing descriptor
  changes.

### The Argus-shaped profile (AC1)

A test fixture, `tests/fixtures/release/argus-shaped-profile.json`, carries Argus's real values,
which central code never names:

- `target`: `{environment: local-host, concurrency_keys: [release/fagenorn/argus]}`.
- `requirements`/`bindings.adapters`: `bundle` → `codesigned-artifact` and `launchd` →
  `launchd-agent`, each in the range `[1.0.0, 2.0.0)`.
- `bindings`:
  - target `notifier` = `installed_bundle`,
    `path: ~/Library/Application Support/Argus/Argus.app`;
  - target `daemon` = `launchd_gui_agent`, `label: dev.argus.daemon`;
  - principal `owner` (`host_user`);
  - credentials `keychain` (`bundle`, `codesigning_identity`) and `session` (`launchd`,
    `gui_session`).
- `publication`: the action `notifier` (`install`, `materialize`, `reversible_no_incremental_spend`,
  deadline 120000) with config `{source: daemon/notifyd/Argus.app, identity_prefix: Apple
  Development, identity_env: ARGUS_CODESIGN_IDENTITY, adhoc_fallback: false}`.
- `activation`: the unit `daemon` (`activate`, `local_apply`, `irreversible`, deadline 300000)
  with config `{program: devenv, arguments: [shell, --, daemon, run], keep_alive: true,
  background: true, stdout_path: home/daemon/logs/daemon.out.log, stderr_path:
  home/daemon/logs/daemon.err.log}`.
- `proof`: `convergence_window_ms: 1800000` and one required liveness obligation, `daemon-live`,
  as described in the liveness section (`freshness_ms: 600000`).
- `recovery`: both units `supersedable_only`.
- `limits`: `{}`.

The resolver test's contract pairs this profile with a publication-free forge profile, because
`guard-policy` derives a project's guard rows only from a `github_repository` target. #129
authors both for real.

### Docs

`python/README.md`:

- "Release adapters" gains one paragraph per adapter: descriptor, config, inspect classification
  (by reference to this spec), invoke steps, the build limitation (D9) and the test world.
- "Release adapters" also restates `watch_operation` (D10).
- "Release profiles" names the liveness predicate route.

No context, ADR or standards document exists to update, because `knowledge.context` is
unsupported. CLAUDE.md is untouched.

### Delivery shape (D14)

The work is one branch with two task groups:

- **A**: `codesigned-artifact`, its registry entry and the `watch_operation` narrowing.
- **B**: `launchd-agent`, the fixture, the core run and the docs.

The two groups ship as two PRs, in that order, only if `diff-scope` reports the branch over the
configured review limit. A stands alone, because a bundle-only profile with activation `none`
compiles.

### Acceptance mapping

- **AC1**:
  - `grammar_violations` returns `[]` and `compile_profile` succeeds for the fixture against the
    real `DESCRIPTORS`;
  - `resolve-project resolve` on the fixture contract, with fake `codesign`, `security`,
    `launchctl` and `git` on `PATH`, reports `capabilities.release` `available` and lists both
    targets in `release.targets`;
  - `release profile inspect` reports the profile admissible;
  - the real `TransactionStore` drives one bound candidate of it to `succeeded` through
    `core_binding` over the fake host world (D16).
- **AC2**: a static test asserts that no module under `python/agent_tools/` contains `argus`,
  case-insensitively. No module there contains it today.
- **AC3**:
  - the release, conformance, adoption and guard-policy suites run unchanged and green;
  - a test compiles the forge fixture profile against the full `DESCRIPTORS` and against the two
    prior descriptors alone, and the digests are equal;
  - ship-time evidence records the `release profile inspect github-release` digest on nix-config
    before and after the change, and they are equal.

## Test seams

- **Adapters in process over a fake host world** (D13). A new `tests/host_world.py`, in the
  `forge_world`/`actions_world` style, patches `os.environ` for the test:
  - `PATH` is a world `bin/` alone, so no test reaches this host's `launchctl`, `codesign` or
    `security`;
  - `HOME` is a temporary directory;
  - the working directory is a temporary git checkout at a known commit.

  The `bin/` holds a link to the real `git` and three logging fakes:
  - `launchctl` models one `gui/<uid>` domain in a state file. `bootstrap` loads the plist with
    `runs = 1`, `bootout` unloads, and `print` emits the production-shaped block captured from this
    host. Scenario knobs cover a foreign path, a stopped job, extra runs, exit codes and delays.
  - `security` prints a configured identity list.
  - `codesign` signs by writing a seal over the bundle's bytes and identity, verifies by
    recomputing it, and prints `-d` lines with `Signature=adhoc` or `Authority=`.

  New suites `tests/test_codesigned_artifact_adapter.py` and `tests/test_launchd_agent_adapter.py`
  join the `agent-workflow-tests` recipe. They cover every classification row, every predicate
  mapping, every `invoke` step and refusal (including uid 0, a dirty checkout, an env identity that
  matches nothing, ad-hoc refused and allowed, and staging left by a crash) and the failure
  mapping. They also assert the rendered plist and the stamped `Info.plist` as files. Every macOS
  tool is a fake, so the suites run on `anis-desktop` as well as on the Macs.
- **Registry and descriptors, imported.** `DESCRIPTORS` builds with both adapters, and
  `watch_operation` returns `deploy`, `None`, `None` and `None` for the four adapters. This extends
  `tests/test_release_adapter_core.py`.
- **Grammar, compiler, resolver and inspection.** These use the fixture with the real registry:
  the AC1 rows above, a deploy binding naming `launchd-agent` that is `adapter_unwatchable`, and
  the AC3 digest test. They extend `tests/test_release_profile.py`, `tests/test_release_grammar.py`
  and the resolver suite.
- **Core end to end** (D16). The real `TransactionStore` runs with per-alias `core_binding`s of
  the two real adapters over the host world, following the 124 AC8 seam in
  `tests/test_release_adapter_core.py`. The candidate is the temporary checkout's real HEAD. It
  inspects and invokes `notifier` and then `daemon`, collects the derived obligations and the
  authored liveness obligation, and settles `succeeded`. A second transaction, at a new commit,
  replaces both units. A job loaded from a foreign path inspects `diverged`, and the core refuses
  the invoke with `not_absent`, with no `launchctl` mutation logged.
- **AC2 static scan.** One test reads every `python/agent_tools/*.py` source.

## Out of scope

- **Adopting Argus (#129).** This covers its contract and publication-free forge profile, its
  build-before-release step, removing its legacy `~/Applications/ArgusPing.app`, and every edit
  to the Argus tree.
- **A live run against this host.** That is #129's ship-time evidence, which also confirms the
  `launchctl print` fields and the `bootout`/`bootstrap` exit codes on a real domain.
- **Building artifacts.** Also out: signing bare binaries in place, nested-code signing,
  entitlements and hardened runtime (re-signing keeps none).
- **Recovery operations.** No `uninstall` compensate edge, no retained prior plist or bundle, and
  no `restorable` anchors, which the driver refuses anyway.
- **Other launchd domains.** No `user/<uid>`, no system daemons and no root.
- **Other adapters and contract members.** No Nix `local_apply` (`just switch`), Railway or OCI
  adapter, no spend grants and no `limits` members.
- **Shortening authored obligation parameters,** which would change `core_binding`.
- **The driver's handling of an `unknown`/`parameters_invalid` inspection,** which today waits
  (D17).
- **Mapping a legacy launchd `deploy` member in `release_bridge`.**

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Two registered adapters, `codesigned-artifact` and `launchd-agent`, each its own stdlib module (plus `agent_tools.canonical`) with its own runner and inner checks, and exactly `describe`/`inspect`/`invoke` | the bar's single responsibility (two domain operations, two reasons to change); 124 D7; 465 D14 (registry imports adapters, never the reverse); the issue's two separate requirements | One host adapter: the union of executables and credentials forces `codesign` on a launchd-only profile. A shared runner module: a third copy of a pattern each adapter owns today |
| D2 | Bundle `install` is publication `materialize`/`in_place`; launchd `activate` is activation `local_apply`/`in_place`; both declare both non-spend effect classes, no recovery-capable operation; rollback is the existing posture vocabulary (fixture: `supersedable_only`); install and restart are one bootout-plus-bootstrap operation | #81 (signed-binary identity is a publication artifact identity); #84 (`local_apply` covers Argus install and restart); 368 D2 (activation needs a publication); evidence (no rollback anchor; forward-only state DB) | The bundle as an activation unit: the profile would need an unrelated publication. An `uninstall` compensate operation or a separate `restart` operation: no consumer (128 out of scope), a half-wired path |
| D3 | Both operations are `supported` and `invoke` runs the real tools; tests reach none of this host's tools because `PATH` is a fake-only `bin/` and `HOME` a temp directory | 124 D8 (a referenced unsupported operation is `invalid_contract`, so AC1 needs `supported`); the bar's no half-wired path; the forge and actions world precedent | `invoke` unsupported, as 465 D2 chose: AC1 could not compile. An injected runner parameter: widens the three-function surface (124 D7) |
| D4 | Identity is a stamp the adapter writes: `AgentReleaseVersion`/`AgentReleaseCommit` in the bundle's `Info.plist`, sealed by the signature; `AGENT_RELEASE_VERSION`/`AGENT_RELEASE_COMMIT` in the agent plist's `EnvironmentVariables`, read back from `launchctl print`; the agent's identity also requires its working-directory checkout at the commit with no tracked changes | evidence ("nothing binds the running process to a commit"; the agent runs the checkout's code); #84 (`local_apply` inspects active local identity); `launchctl print` output read on this host; a version is reserved once an effect lands and the core abandons only effect-free transactions, so `{version, commit}` names exactly one install | A sibling stamp file: unsealed, so it drifts from the bytes. A pid or path check only: cannot tell a stale checkout from a current one. A content-digest walk: the signature already seals the bundle |
| D5 | The core's derived `publication_visible`/`running_subject_identity` are answered with reasons inside its closed spaces; one authored liveness predicate `agent_running` (running, `pid`, `runs = 1`) that a profile may require; authored obligations address their unit as 124 D24 already requires | `transaction_plan.DERIVED_REASONS` and `observation_violation`; the issue ("evidence the profile can require"); the core already derives identity per unit | Liveness equal to identity: no extra evidence. Widening `core_binding` to accept a short node reference: changes a public seam for one fixture |
| D6 | For `in_place` targets, any state that does not hold this candidate but is safe to replace is `absent`; only a symlink, a wrong type or a job loaded from another plist is `diverged` | the driver invokes only after `absent` and the core refuses `not_absent`; the bar's truthful states | An older release as `diverged`: every upgrade would park. An unmanaged Argus install as `diverged`: adoption would need a manual uninstall |
| D7 | Target kinds `installed_bundle{path}` (`~/`-relative, inside `$HOME`) and `launchd_gui_agent{label}` (domain `gui/<uid>` from the process, plist under `~/Library/LaunchAgents`); credential classes `codesigning_identity` and `gui_session`; both `invoke`s refuse uid 0 | evidence (authority boundary: the user's GUI session and login keychain); the grammar checks kinds and classes but no member values; the bar's defense in depth | A `domain` target member: the grammar cannot check its value, so a bad domain fails only at run time. Absolute install paths: escape the authority boundary |
| D8 | Closed configs. Launchd: `program` (bare name resolved on `PATH`), `arguments`, `keep_alive`, `background`, `stdout_path`/`stderr_path` (checkout-relative); `WorkingDirectory` is the checkout and `RunAtLoad` is true. Bundle: `source`, `identity_prefix`, optional `identity_env`, `adhoc_fallback`; signing is `codesign --force --sign <hash or ->` with no options | #84 (adapters own provider fields and translation); bootstrap (no shell text or env values in the contract); Argus's `launchd.ts` and `sign.sh` | A plist file in config: a raw provider document carrying host-specific absolute paths. A `run_at_load` member: an agent that does not start is not activated |
| D9 | Building stays outside the adapter: `install` requires the checkout at the candidate commit with no tracked changes and installs what it holds; the limitation is documented | bootstrap (every project executable is a `commands` entry the adapter cannot resolve); the bar (known limitations belong in docs) | A build argv in config: an executable invocation outside `commands`. Silently stamping without the checkout check |
| D10 | `watch_operation` names only the single inspectable `publication_triggered` operation (refines 465 D3), so `launchd-agent` is `adapter_unwatchable` as a deploy binding | `release deploy inspect` builds a merge-triggered `github_repository` request; the bar's fail loud and defense in depth | Leaving the activation-mode rule: a launchd deploy binding would resolve, then fail every poll. A target-kind check in the resolver: an adapter-specific rule in generic code |
| D11 | No grammar, compiler, resolver or driver change beyond D10; 124 D1, 465 D4 and 128 D1 stand; existing profiles keep their digests | descriptor data already feeds every generic rule; 124 D17/D23 (a digest covers bound descriptors only) | A host-local exception to `deploy_conflict`: reopens dual activation authority |
| D12 | Neither adapter calls the lifecycle guard | the guard adjudicates five git/gh verbs of agent Bash calls; `invoke` is reachable only through the core under driver grants (124 D15) | Guard rows for `launchctl`/`codesign`: no agent Bash surface to guard |
| D13 | Test seams: adapters in process over `tests/host_world.py` (fake-only `PATH`, temp `HOME`, real `git` on a temp checkout); registry, grammar, compiler and resolver with the Argus fixture; one core run (D16); an AC2 static scan | the bar's tests that can fail (production-shaped `launchctl print` text, files asserted on disk); the 124/465/128 seams; agent-helpers rule 5 | Mocking `subprocess`: asserts calls, not behaviour. Live host tools: non-deterministic and mutates the user's session |
| D14 | One branch, two task groups (A bundle adapter and D10; B launchd adapter, fixture, driver run, docs), split into two PRs only when `diff-scope` exceeds the review limit | 124 D16 precedent; A compiles a bundle-only profile alone | Two branches up front: cross-dependency churn |
| D15 | Budgets and failure mapping: `inspect` 30 s shared; `invoke` 60 s (`activate`) and 120 s (`install`); a failure before the first host write is `rejected`, after it `unknown`; the first write is the bootout, or the plist write when nothing is loaded (launchd), and the first rename (bundle) | 124 D23/D25 (a failed precondition read is `rejected`; `unknown` means possibly applied); `codesign` may wait on a keychain prompt | One per-child timeout: several children could outlast the declared collector latency |
| D16 | The end-to-end seam is the real `TransactionStore` with per-alias `core_binding`s over the host world, on the temporary checkout's real HEAD, not `release_driver.Driver` | 124 AC8 seam (`tests/test_release_adapter_core.py`); the driver is adapter-agnostic and 128 already drives an activation unit through fixture adapters; `ForgeWorld`'s verification fakes pin a canonical commit and replace `git` on `PATH`, while these adapters need the real `git` at a real commit | A driver run: it needs both worlds' fake `PATH`s and verification reads for a commit no real repository can carry, and it tests grants and confirmations this issue does not change |
| D17 | Every enumerable config choice is typed so the grammar checks it (`background` is a boolean, the domain is the target kind); the remaining value rules (label, program and path patterns, `~/` paths) are inner checks only, reported by `inspect` as `unknown`/`parameters_invalid` and by `invoke` as `invalid_input` | 465 D9 (no adapter-specific value check in the generic resolver); `config_problems` checks types only; the bar's defense in depth | A `process_type` string: a typo compiles and then fails every inspection. A pattern or enum member in the descriptor schema: a 124 D19 schema change for every adapter |
| D18 | `ProgramArguments[0]` is the `PATH`-resolved program path with no `/bin/wait4path` wrapper | CLAUDE.md's wait-for-volume rule governs nix-darwin boot-time daemons; a `gui` agent starts at login, after the store volume mounts; Argus's live agent runs this shape (`launchctl print`, read on this host) | A shell wrapper around the program: guards against a failure the `gui` domain has not shown, and adds a shell layer to the process launchd tracks |
