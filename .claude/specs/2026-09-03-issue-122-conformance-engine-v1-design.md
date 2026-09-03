# Conformance engine v1 — closed check registry, purposes, and the ConformanceReport

- **Issue:** fagenorn/nix-config#122 (implementation slice of Wayfind map #59)
- **Base SHA:** `8b69f8c182118063eeecafda81b9948100cf2eb1` (branch `worktree-issue-122-conformance-engine-v1`)
- **Binding decisions:** #63 (closed error codes, `ResolvedProject`), #69 (engine contract), #86 (three graduated lint items), #72 (lifecycle classes, cleanup rule), #61 (removable static checks)
- **Blocked by:** #118 — closed, merged as PR #140
- **Date:** 2026-09-03

## Problem

Resolver v1 answers *what did this project declare*. Nothing answers *is this machine, this checkout and this contract actually fit to run a workflow* — so every agent answers it by hand, differently, at the moment it breaks.

Three concrete costs, all observed in the last window:

1. **Entry is unguarded.** A workflow skill that needs a stale projection regenerated or a blocked capability discovers it halfway through, as a confusing downstream error, instead of refusing at entry with one root cause and one repair.
2. **Installation defects were rediscovered per-agent.** A policy file resolved through a Nix store symlink that a no-follow reader rejects, and a required helper missing from an executor's `PATH`, each broke every owner in a run and each was worked around independently. Nothing recorded them, so the next run rediscovers them.
3. **Doctor work happens by hand.** Orphaned nested `.superpowers/` ledgers across seven worktrees, scratch request files left in the repository root, dead bridge state — all swept manually, with the ever-present risk of deleting state a live run still owns.

Separately, #86 routed three "friction, not gap" prototype findings to a #69 lint. Their subject is a release profile and the profile compiler is a later slice, so today they exist only as prose on a branch and will be lost.

There is also a failure mode a naive checker would introduce and that #69 forbids outright: probing the network to decide whether the network is available, then reporting a pass because the probe was skipped. Offline must be an input, never an inference.

## Solution

One new deep module — `conformance` — layered directly on Resolver v1, with a closed registry and a closed report.

1. **`conformance` is a new Python helper** installed at `~/.agents/bin/conformance`, in the house style of `resolve-project` / `workflow-state` / `artifact-budget`: closed vocabularies, fail-loud, compact sorted JSON on stdout.
2. **It consumes `resolve-project` as a library**, in-process, and never re-parses `.agents/project.json`. The resolver's entry ladder is already separable into exactly the five functions that raise the five #63 structural codes; the engine calls them one at a time instead of calling `resolve` and catching whatever surfaces first.
3. **A closed check registry** spans the four truth domains. Each entry is a static declaration — id, domain, subject kind, requirement, network flag, dependencies, the closed reason codes it may emit, and the repair it owns.
4. **The caller names one purpose; the engine selects the checks.** There is no `--check` flag and no way to assemble a custom ladder.
5. **One report shape for every purpose.** `workflow_entry` differs by *content*, not by schema: on a blocking finding its `checks` array holds exactly the one root cause and `repairs` exactly one repair, and the process exits non-zero. Diagnostic purposes evaluate every independent check, suppress dependent cascades, and exit zero with the full finding set.
6. **Offline is a flag.** `--offline` is the only way the engine learns it is offline; a network-flagged check then reports `not_run` and a required one drives the outcome to `incomplete`.

### Demo

```sh
conformance run --purpose doctor --repo-root .            # full report: findings + repairs, exit 0
conformance run --purpose doctor --repo-root . --offline  # network check not_run, outcome incomplete
printf 'x' >> AGENTS.md
conformance run --purpose workflow_entry --repo-root .    # one check, one repair, exit 2
```

## Decisions

### Files

| Path | Disposition |
|---|---|
| `home/common/agent-skills/scripts/conformance.py` | new — the engine and its CLI |
| `home/common/agent-skills/tests/test_conformance.py` | new — the suite |
| `home/common/agent-skills/default.nix` | modified — install `.agents/bin/conformance` |
| `justfile` | modified — add the new module to `agent-workflow-tests` |

Nothing else changes. In particular `.agents/project.json` gains no `commands` entry and `.agents/instructions/bootstrap.md` is untouched (D12, D13).

### Consuming the resolver

The engine imports `resolve-project.py` in process, loading it from the sibling of its own file by trying, in order, the names `resolve-project.py`, `resolve_project.py`, `resolve-project`, through an explicit `SourceFileLoader` so an extensionless Nix-installed link loads identically to the repository file. The loaded module's `main()` is `__main__`-guarded, so import defines functions and runs nothing.

The five structural checks map one-to-one onto resolver functions:

| Check | Resolver call | #63 code on failure |
|---|---|---|
| `repository.contract.present` | `discover_root` | `not_onboarded` |
| `compatibility.contract.schema_supported` | `validate_schema_version` | `unsupported_schema` |
| `repository.contract.valid` | `validate_contract` | `invalid_contract` |
| `repository.projection.fresh` | `validate_projections` | `invalid_projection` |
| `host.capability.required` | `compute_capabilities` + `raise_for_unavailable` | `capability_unavailable` |

`repository.contract.resolvable` is the first check and depends on nothing. Its body runs that whole ladder **once**, inside a single `except Exception`, and caches each stage's outcome — completely, so that after it returns no stage is unset and no dependent evaluator can face a hole (D33); it fails only when an exception that is not the resolver's `ContractError` escapes, and it is the only check that can carry `resolver_failure`. Every other structural check is then a pure read of the cached stage outcome, and is `suppressed` when `resolvable` failed. The ladder is never run twice and no check re-enters the resolver (D17).

Every child process the engine starts — `git rev-parse` for the revision, the tracker CLI for the credential check — is read-only, carries a bounded timeout, and on failure yields a `null` fact or a check finding, never an exception that escapes the check (D19).

### The `ConformanceReport`

Exactly six top-level members, no more, no fewer, no timestamp anywhere.

```json
{
  "schema_version": 1,
  "subject":  {"project_id": "fagenorn/nix-config", "root": "/abs/path",
               "revision": "8b69f8c1…", "platform": {"system": "Darwin", "machine": "arm64"}},
  "request":  {"purpose": "doctor", "offline": false,
               "required_capabilities": [], "platform_target": "Darwin/arm64"},
  "outcome":  {"status": "passed", "primary_check_id": null},
  "checks":   [{"id": "…", "domain": "repository", "requirement": "required",
                "status": "passed", "reason_code": null, "repair_id": null, "facts": {}}],
  "repairs":  [{"repair_id": "…", "module": "resolve-project",
                "safety_class": "worktree",
                "operation": {"module": "resolve-project", "subcommand": "write-projections", "args": []}}]
}
```

- `subject.revision` is `git rev-parse HEAD`, or `null` outside a repository or on an unborn HEAD. `subject.root` is the resolver's normalized absolute root.
- `request.required_capabilities` is the sorted, deduplicated `--require` set; when it is empty `host.capability.required` passes vacuously. `request.platform_target` is the detected host identity; v1 has no flag to override it (D14).
- Closed vocabularies: `domain` ∈ `repository | compatibility | host | verification`; `requirement` ∈ `required | optional`; `status` ∈ `passed | warning | failed | not_run | suppressed`; `outcome.status` ∈ `passed | failed | incomplete`; `safety_class` ∈ `read_only | worktree | user_action | destructive`.
- `checks` is emitted in registry order, which is stable and sorted by id. `repairs` is deduplicated by `repair_id` and sorted.
- `facts` is a bounded, non-secret object: at most eight keys; each value a bool, an int, a string of at most 200 characters, or a list of at most eight such strings. The validator rejects anything else. This bound is what mechanically keeps credential values, raw logs and prose out of the report — there is no separate "is this a secret" heuristic (D9).
- `operation` is structured — module, subcommand, argument list — never an opaque shell string.

**Outcome precedence.** `failed` if any check is `failed`; else `incomplete` if any **required** check is `not_run`; else `passed`. A `warning` never changes the outcome (D8). `primary_check_id` is the first `failed` check in registry order, or the first required `not_run` when the outcome is `incomplete`, or `null` when `passed`.

**Cascade suppression.** For a diagnostic purpose, a check whose `depends_on` closure contains a `failed` check is `suppressed`, carries `{"suppressed_by": "<ancestor id>"}` in `facts`, and contributes no repair. Every check outside that closure still runs.

### The registry

| Id | Domain | Req. | Net | Depends on | Reason codes | Repair id (safety class) |
|---|---|---|---|---|---|---|
| `repository.contract.resolvable` | repository | required | no | — | `resolver_failure` | `conformance.internal` (`user_action`) |
| `repository.contract.present` | repository | required | no | resolvable | `not_onboarded` | `onboarding.contract.missing` (`user_action`) |
| `compatibility.contract.schema_supported` | compatibility | required | no | present | `unsupported_schema` | `contract.schema.unsupported` (`user_action`) |
| `repository.contract.valid` | repository | required | no | schema_supported | `invalid_contract` | `contract.invalid` (`user_action`) |
| `repository.projection.fresh` | repository | required | no | valid | `invalid_projection` | `projection.regenerate` (`worktree`) |
| `repository.paths.classified` | repository | required | no | valid | `unclassified_path` | `lifecycle.path.classify` (`user_action`) |
| `repository.ignore.runtime_sentinel` | repository | required | no | valid | `runtime_ignore_missing`, `overbroad_ignore` | `lifecycle.ignore.repair` (`worktree`) |
| `repository.residue.nested_ledger` | repository | optional | no | valid | `live_owner`, `terminal_residue`, `unacknowledged_residue` | `lifecycle.residue.nested_ledger` (see below) |
| `repository.residue.root_scratch` | repository | optional | no | present | `root_scratch_present` | `lifecycle.residue.root_scratch` (`worktree`) |
| `repository.release_profile.rolled_back_reachable` | repository | optional | no | valid | `subject_absent`, `rolled_back_unreachable` | `release_profile.compensate.add` (`user_action`) |
| `repository.release_profile.restore_anchor` | repository | optional | no | valid | `subject_absent`, `restore_anchor_destroyed` | `release_profile.materialize.add` (`user_action`) |
| `repository.release_profile.observation_deadline` | repository | optional | no | valid | `subject_absent`, `observation_deadline_optional` | `release_profile.deadline.require` (`user_action`) |
| `host.capability.required` | host | required | no | valid | `capability_unavailable` | `capability.required.unavailable` (`user_action`) |
| `host.policy_path.no_follow_readable` | host | required | no | valid | `policy_path_symlinked` | `host.policy_path.materialize` (`user_action`) |
| `host.executor.helper_on_path` | host | required | no | valid | `helper_missing` | `host.helper.install` (`user_action`) |
| `host.tracker.credential` | host | required | **yes** | valid | `offline_constraint`, `unsupported_tracker_kind`, `tracker_credential_missing` | `conformance.rerun_online` (`read_only`) / `host.tracker.authenticate` (`user_action`) |
| `verification.commands.no_shell_indirection` | verification | required | no | valid | `shell_indirection` | `contract.commands.destructure` (`user_action`) |

Notes on the non-obvious entries:

- **`repository.paths.classified`** applies #72's four lifecycle classes to every entry under `.agents/` and to each declared projection target. An entry matching none of the four classes fails with `unclassified_path` and names up to eight offenders in `facts`.
- **`repository.ignore.runtime_sentinel`** requires `.agents/runtime/` to be covered by an ignore rule and rejects a broad `.agents/*` or `.claude/*` ignore, per #72.
- **`repository.release_profile.*`** are the three #86 items, registered now with `subject_kind: "release_profile"` declared. With no profile in the repository they report `not_run` with `subject_absent`. They are **optional**, so an absent subject cannot poison the outcome (D6).
- **`host.policy_path.no_follow_readable`** walks each declared standards, architecture and projection-source path component by component **from the project root downwards, never above it**, and fails when any of those components is a symlink — the defect being that a reader opening with `O_NOFOLLOW` refuses it. `facts` records the repository-relative path, the link depth, and whether the target resolves under `/nix/store/`. Bounding the walk at the root is what keeps the check honest: on macOS `/tmp` is itself a symlink to `private/tmp`, so a walk to `/` would fail every checkout under it for a reason the contract does not own (D18). Pure filesystem; offline-safe.
- **`host.executor.helper_on_path`** projects resolver truth: it fails when any computed capability is `blocked` with `command_missing` or `tracker_cli_missing`, naming the offending capability names and reason codes. It re-implements no `PATH` search of its own (DRY with `resolves_on_path`).
- **`host.tracker.credential`** is the only network-flagged check. It asks the declared tracker CLI whether an authenticated credential exists and records a boolean plus the hostname — never a token, never a username. It invokes that CLI with exactly the environment names in `tracker.credential_env.unset_before_invocation` removed, so the contract stays the single home for that policy (this repository declares an empty list, i.e. no scrub). The CLI subcommand comes from a closed dispatch on `tracker.kind`, which v1 knows for `github` only; the resolver validates `kind` as a free string, so an unrecognised value makes the check `not_run` with `unsupported_tracker_kind` and drives the outcome to `incomplete` — never a pass on a tracker the engine cannot interrogate (D20). Offline it is `not_run` with `offline_constraint`.
- **`verification.commands.no_shell_indirection`** fails when a declared command's `argv[0]` is a shell (`sh`, `bash`, `zsh`) with `-c`, or any `argv` element carries `;`, `|`, `&&` or `` ` ``. The resolver validates command *shape*; this validates command *policy*, so the two do not overlap.

### Purpose → check mapping

| Purpose | Checks |
|---|---|
| `workflow_entry` | `repository.contract.resolvable`, `…present`, `compatibility.contract.schema_supported`, `repository.contract.valid`, `repository.projection.fresh`, `host.capability.required` — evaluated in that order, stopping at the first blocking one |
| `doctor` | every registered check |
| `adoption` | the `repository` domain plus `compatibility.contract.schema_supported` |
| `local` | the `workflow_entry` ladder plus the whole `host` domain |
| `ci` | `repository` + `compatibility` + `verification` domains (no host credential check; CI owns its own auth) |
| `fleet` | `repository` + `compatibility` domains |

All six purposes are declared because the set is closed and a missing arm would be a silent gap. Only `workflow_entry` and `doctor` are populated to the acceptance criteria; the other four select from the same registry and introduce no new check (D5).

### The offline rule

`--offline` is a boolean flag, default false, recorded verbatim in `request.offline`. The engine never probes anything to decide whether it is offline, and no check may flip the flag. For each selected check, if `request.offline` is true and the registry marks the check `network: true`, the check is `not_run` with reason `offline_constraint` and contributes the single `conformance.rerun_online` repair (`read_only`) — the check body never runs, so nothing can turn a skipped probe into a pass.

`workflow_entry` selects no network-flagged check, so `--offline` cannot change its outcome. That is asserted, not assumed.

### Residue checks and the cleanup rule

`repository.residue.nested_ledger` enumerates `.superpowers/workflows/<run-id>/` directories that live inside a worktree under `vcs.worktree.root` rather than in the primary checkout. For each, it attempts a **non-blocking** `fcntl.flock(LOCK_EX)` on that run's `state.lock`:

| Lock outcome | Run state | Reason code | Repair safety class |
|---|---|---|---|
| lock held elsewhere | — | `live_owner` | `user_action` |
| acquired | terminal, result durable | `terminal_residue` | `worktree` |
| acquired | failed or stopped | `unacknowledged_residue` | `user_action` |

The lock is released immediately; acquiring it is evidence, not a claim. Nothing is deleted — v1 reports repairs and does not execute them — and **no repair in v1 carries `destructive`**, which satisfies "not destructive unless a lock proves no live owner" by never reaching for the exemption (D10). Elapsed time is not consulted anywhere, per #72's "Doctor lists retained residue; it never converts elapsed time into deletion authority."

`repository.residue.root_scratch` reports repository-root files matching the closed scratch pattern set (`producer-report-*.json`, `review-package-report-*.json`, `*.tmp.??????`, `.resolve-project.*.tmp`). These are `mktemp` outputs that escaped `$TMPDIR`; they have no owner and no lock, so no lock probe applies. Its pattern set is a constant rather than contract-derived, so it depends only on `repository.contract.present` and still reports on a repository whose contract is invalid.

Both residue checks report `warning`, never `failed`: retained residue is untidy, not non-conformant, and a machine mid-run must not read as a broken repository (D8).

### CLI surface

```
conformance run --purpose <purpose> [--repo-root PATH] [--offline] [--require CAPABILITY]...
conformance validate-report --input PATH
```

- `--repo-root` is optional. Given, it *is* the root; omitted, the engine hands the resolver `None` so its ancestor walk finds the project root from the process working directory (D28).
- `--purpose` and `--require` use closed argparse `choices`, so an unknown value is an argparse usage error (exit 2, no JSON) rather than a JSON refusal — the same two-channel convention `resolve-project` established.
- `run` prints one report. Exit 0 for every diagnostic purpose that produced a schema-valid report, whatever its outcome. Exit 2 for `workflow_entry` when the outcome is not `passed`, honouring #63's "a structural failure exits nonzero".
- An unexpected engine failure prints the resolver's exact refusal shape — `{"error":{"code":"resolver_failure","repair_id":"conformance.internal","violations":[…]}}` — and exits 2, with no report. Reusing #63's closed code set avoids inventing a seventh error code (D15).
- `validate-report` is the schema validator: it accepts a report file and refuses anything with a missing or extra member, an out-of-closed-set value, a timestamp-shaped member, an over-bounded `facts` object, a repair referenced by a check but absent from `repairs`, or a repair present in `repairs` that no check references.

## Test seams

`home/common/agent-skills/tests/test_conformance.py`, `unittest`, no network, no sleeps, no timing dependence — the seams `test_resolve_project.py` established.

- **S1 — the CLI, as a subprocess.** `python3 conformance.py run --purpose <p> --repo-root <tmp>` against temporary repository roots built from a copy of `.agents/project.json` and mutated per case; assertions read parsed stdout and the exit code. Every behavioural case lands here: the two report shapes, cascade suppression, outcome precedence, the offline rule, each registered check's pass and fail branch.
- **S2 — the validator, as a subprocess.** `validate-report --input <file>` against hand-built reports: valid, extra member, missing member, unknown status, unknown safety class, oversized `facts`, dangling `repair_id`.
- **S3 — in-process module load**, through the `load_module` helper the resolver suite already carries, for the two seams no subprocess reaches: the top-level `except Exception` wrapper, and the `raise` branches of the closed-set dispatch sites.

Two fixtures carry the environment-shaped cases and keep them offline and deterministic:

- **Fake CLI on `PATH`.** A temp directory holding an executable `gh` stub that exits 0 or 1 covers `host.tracker.credential`'s online branches without a packet; an empty `PATH` covers `host.executor.helper_on_path`. `shutil.which` — the resolver's own lookup — honours both.
- **Held lock.** The test process holds `fcntl.flock` on a fixture `state.lock` while the subprocess runs, so the `live_owner` branch is proved by the kernel rather than by a sleep.

One consistency test asserts that every scratch pattern in the engine's closed set is present in the tracked `.gitignore`, keeping the policy's single home in the engine and the ignore file honest as its backstop (D11).

### Acceptance criteria, made falsifiable

| AC | Failing assertion at base |
|---|---|
| Schema-valid report for `doctor` and `workflow_entry`, differing in shape | both reports pass `validate-report`; the entry report on a broken contract has exactly one check, one repair, exit 2; `doctor` on the same root has more than one check and exit 0 |
| The three lint items are registered with declared subjects | the three `repository.release_profile.*` ids appear in a `doctor` report with `subject_kind: "release_profile"`, status `not_run`, reason `subject_absent` |
| Store-symlink policy path and missing helper are `host` findings with a repair and safety class | a symlinked-standards fixture and an empty-`PATH` fixture each yield a `failed` `host` check with a non-null `repair_id` whose repair carries a closed `safety_class` |
| Offline: network check `not_run`, outcome `incomplete`, never `pass` | `doctor --offline` on a clean fixture (no `failed` check, so precedence cannot mask it) gives `host.tracker.credential` status `not_run` and `outcome.status == "incomplete"` |
| Orphaned ledgers and root scratch reported with non-`destructive` repairs unless a lock proves no live owner | the residue fixture yields two `warning` checks; every repair in the report has `safety_class != "destructive"`; the held-lock fixture yields `live_owner` with `user_action` |

## Options considered

**Where the engine lives.** *A subcommand of `resolve-project`* keeps one binary and one import story, but merges two responsibilities — resolving a declaration and judging a machine — into one module that then has two reasons to change, and grows the resolver past the point where its refusal semantics stay readable. *A separate script and binary* matches how every other capability in this tree is exposed and keeps the resolver's surface closed. Chosen: separate (D1).

**How the engine reaches the resolver.** *Subprocess* is loosely coupled and reuses the published JSON contract, but spawns an interpreter per run, gives back only the first `ContractError` the resolver chose to raise, and forces the engine to re-derive the ladder from a flat error code. *In-process import* gives the engine the five ladder functions individually — exactly the granularity the entry purpose needs — with no spawn and no PATH dependency. Chosen: in-process (D2).

**`workflow_entry`'s failure output.** *A distinct error object, not a report* is the most literal reading of #69's "never a full report in agent context", but leaves acceptance criterion 1 — "a schema-valid `ConformanceReport` for `doctor` **and** for `workflow_entry`" — untestable on the path that matters, and adds a second output schema for consumers. *One report schema, content-truncated to a single root cause*, with the #63 code carried in that check's `reason_code` and named by `primary_check_id`, is still compact and closed, is one check rather than a finding set, and keeps the non-zero exit. Chosen: one schema (D3).

**Where the #86 lint items live.** *Compatibility domain* follows #86's framing as a schema-shaped lint, but #69 scopes compatibility to platform intervals, schemas, migration state and fleet registration. *Repository domain* matches #69's "contract shape and policy", which is what a release profile is once authored. Chosen: repository (D6).

**Absent-subject status for those items.** *`suppressed`* would keep the outcome clean, but #69 reserves suppression for dependent cascades and there is no failed ancestor here. *`not_run` with the check marked optional* uses the status that means "did not evaluate" for the reason it did not evaluate, and the optional requirement keeps an absent subject out of the outcome. Chosen: `not_run` + optional (D6).

**Root-scratch pattern ownership.** *Derive from `.gitignore`* avoids a second copy but requires implementing gitignore matching and would sweep in `result`, `.worktrees/` and `.agents/runtime/`, which are legitimate homes rather than residue. *A closed pattern set in the engine plus a test asserting `.gitignore` contains each* keeps one authoritative policy home and mechanically prevents drift. Chosen: closed set + consistency test (D11).

**Residue finding severity.** *`failed`* would make `doctor` loud, but would report a machine with one live run as a non-conformant repository and would drag `outcome.status` to `failed` on every developer laptop. *`warning`* records the finding and its repair while leaving the outcome truthful. Chosen: `warning` (D8).

## Out of scope

- **The release-profile compiler.** The three #86 checks register with a declared subject; nothing compiles or validates a profile in this slice.
- **Executing repairs.** `doctor repair <repair-id>` is not built. v1 reports repairs with their owning module, safety class and structured next operation; a human or a later slice runs them. Nothing in this slice deletes, moves or writes a file.
- **Populated `adoption`, `local`, `ci`, `fleet` ladders.** The purposes are declared and select existing checks; no check is added for them.
- **Fleet registration and platform-interval compatibility checks.** Both need a fleet registry that does not exist.
- **Smoke-certification freshness** (a #69 host-domain item): no certification artifact exists to be fresh or stale.
- **Runtime health** — service reachability, product state, anything that changes after entry. #69 excludes it from conformance by definition.
- **Migrating workflow skills onto `workflow_entry`.** The engine and its CLI ship; no skill entry text changes.
- **Unauthorized native override detection.** #69 lists it as repository-domain content, but "unauthorized" needs an authored allowlist surface that #65 does not define. Deferred rather than guessed.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The engine is a new script `conformance.py` exposed as `~/.agents/bin/conformance`, not a `resolve-project` subcommand | the-bar "Single responsibility"; every other capability in `home/common/agent-skills/scripts/` is its own binary | A `resolve-project conformance` subcommand — merges declaration-resolution and machine-judgement into one module with two reasons to change |
| D2 | It consumes the resolver in process via `SourceFileLoader` on the sibling file, trying `resolve-project.py`, `resolve_project.py`, `resolve-project`, and calls the five ladder functions individually | `resolve-project.py` already separates `discover_root` / `validate_schema_version` / `validate_contract` / `validate_projections` / `compute_capabilities`, one per #63 code; Nix strips the extension when linking to `~/.agents/bin/` | Subprocess + JSON — spawns an interpreter and yields only the first `ContractError`, forcing the engine to re-derive the ladder from a flat code |
| D3 | One report schema for every purpose; `workflow_entry`'s blocking output is a report whose `checks` holds exactly the root cause and `repairs` exactly one repair, exit 2, with the #63 code in that check's `reason_code` | #69 "a compact closed error plus one repair id, never a full report"; issue AC1 requires a schema-valid report for `workflow_entry` | A separate error-object output for entry failures — makes AC1 untestable on the path that matters and adds a second consumer schema |
| D4 | The engine, not the caller, selects checks: a static `purpose → check ids` table and no `--check`, `--skip` or `--domain` flag | #69 "callers cannot assemble custom ladders" | A caller-supplied check list behind a flag |
| D5 | All six purposes are declared; only `workflow_entry` and `doctor` are populated to the acceptance criteria, and the other four select existing checks without adding any | the-bar "Fail loud" (a closed set with a missing arm is a silent gap) + YAGNI; issue scope boundary | Shipping only the two populated purposes and leaving the other four undeclared |
| D6 | The three #86 lint items are `repository`-domain, `optional`, with `subject_kind: "release_profile"`; with no profile present they report `not_run` / `subject_absent`, which cannot drive `incomplete` | #69 scopes `repository` to "contract shape and policy" and reserves `suppressed` for dependent cascades; only a *required* `not_run` yields `incomplete` | `compatibility` domain and/or `suppressed` — misuses the cascade status and, if required, would make `doctor` on this repository permanently `incomplete` |
| D7 | The single network-flagged check is `host.tracker.credential` (declared tracker CLI reports an authenticated credential; records a boolean and a hostname, never a token), not a generic reachability probe | #69 lists "credential presence with no values" as `host` and excludes runtime health from conformance | A `tracker.reachable` service probe — sits on the runtime-health side of #69's line |
| D8 | `warning` never changes `outcome.status`, and both residue checks report `warning` rather than `failed` | #69 fixes outcome precedence as failed → incomplete → passed with `warning` outside it; the-bar "Truthful terminal states" | Residue as `failed` — reports a machine with one live run as a non-conformant repository |
| D9 | The report's no-secrets guarantee is enforced structurally by bounded `facts` (≤8 keys; scalars, ≤200-char strings, or ≤8-element string lists), validated by `validate-report`, with no content heuristic | #69 forbids credential values, raw logs and prose in the report; the-bar "Defense in depth" prefers a checkable bound to a guess | A secret-detection heuristic over fact values — unfalsifiable and false-positive prone |
| D10 | No v1 repair carries `destructive`. Nested-ledger repairs are `user_action` when the lock is held or the run is failed/stopped, and `worktree` when a non-blocking `flock` proves no live owner and the terminal result is durable; elapsed time is never consulted | #72's cleanup rule and its "Doctor lists retained residue; it never converts elapsed time into deletion authority"; issue AC5 | Age-based residue classification, or a `destructive` class for proven-orphan state |
| D11 | The root-scratch pattern set is a closed constant in the engine, with a test asserting the tracked `.gitignore` carries each pattern | the-bar "DRY — knowledge, not keystrokes"; `.gitignore` documents itself as the backstop, not the policy | Deriving patterns from `.gitignore` at run time — needs gitignore matching and sweeps in `result`, `.worktrees/` and `.agents/runtime/`, which are real homes |
| D12 | `.agents/project.json` gains no `commands` entry for the engine (reverses the Phase-0 note's assumption) | the contract's `commands` namespace holds project verification operations; nothing in `workflow.verification` references conformance; YAGNI | Declaring `conformance` as a project command — an unreferenced binding that no capability computes over |
| D13 | `.agents/instructions/bootstrap.md` and its two projections are untouched; no workflow skill is migrated onto `workflow_entry` in this slice | issue scope boundary lists only the engine, CLI, tests and Nix/`justfile` wiring | Migrating an entry skill now — couples a component slice to skill-contract churn |
| D14 | `request.platform_target` is the detected host identity with no override flag in v1 | #69 fixes the member; YAGNI forbids a knob no caller has | A `--platform-target` flag for cross-platform judgement |
| D15 | An unexpected engine failure emits the resolver's exact refusal shape with code `resolver_failure` and repair `conformance.internal`, exit 2, no report | #63's code set is closed; the resolver already establishes the refusal bytes | Inventing a seventh error code such as `conformance_failure` |
| D16 | Test seams are the CLI subprocess (behaviour), the `validate-report` subprocess (schema), and an in-process module load for the two unreachable seams; environment cases use a fake-CLI `PATH` fixture and a kernel-held `flock`, never the network and never a sleep | `test_resolve_project.py` precedent; the-bar "Tests that can fail" | Monkeypatching the engine's internals, or an online tracker test |
| D17 | `repository.contract.resolvable` is the first, dependency-free check whose body runs the resolver ladder once inside one `except Exception` and caches each stage; the other structural checks read that cache and suppress under it | the-bar "Root causes" and "Fail loud"; a wrapper that is also an ancestor of what it wraps is circular | Per-check `try/except` re-entering the resolver — runs the ladder five times and gives `resolver_failure` five emitters |
| D18 | The policy-path symlink walk is bounded at the project root and never inspects a component above it | macOS `/tmp` is a symlink to `private/tmp`, so an unbounded walk fails every checkout beneath it; the contract owns only root-relative paths | Walking every component up to `/` — a false-positive generator for a condition the project cannot repair |
| D19 | Every child process the engine starts is read-only with a bounded timeout, and its failure yields a `null` fact or a finding rather than an escaping exception | the-bar "Truthful terminal states"; `resolve-project` starts no child at all, so the engine must state its own weaker guarantee explicitly | Letting a `git` or tracker-CLI failure escape into `resolver_failure` — reports an environment fact as an engine bug |
| D20 | The credential check invokes the tracker CLI with exactly `tracker.credential_env.unset_before_invocation` removed, and dispatches its subcommand on a closed `tracker.kind` set (`github` in v1); an unrecognised kind is `not_run` / `unsupported_tracker_kind`, never a pass | the contract is the single home for the scrub policy (DRY); `validate_tracker` accepts `kind` as a free string, so the engine must close the set itself; #69 forbids falling back over an unknown closed-set value | Hard-coding the `GITHUB_TOKEN`/`GH_TOKEN` scrub the shipping flow uses, or assuming `kind == "github"` |
| D21 | The registry is additive: every purpose except `workflow_entry` selects by domain rather than by a hand-maintained id list, so a task that registers a check is picked up without editing the purpose table; the registry's `network` field and the offline rule are introduced together with the first network-flagged check, not ahead of it | the-bar "Tests that can fail" (machinery with no subject cannot be tested) and "YAGNI"; `workflow_entry` needs an explicit *ordered* ladder, the diagnostic purposes do not | A hand-maintained id list per purpose (six lists to edit per new check, and a missing entry is silent) or shipping the offline rule as inert machinery before any check can exercise it |
| D22 | The end-to-end acceptance gate resolves this repository's own committed root — `conformance run --purpose doctor --repo-root <REPO_ROOT>` — and asserts the full registry appears; per-check behaviour is still proved against synthetic temporary roots | `test_resolve_project.py` already uses the committed contract as its drift gate; a registry that omits a check on the real subject is exactly the silent gap #69 forbids | Only synthetic fixtures — the demo in the issue is against nix-config, so nothing would prove it |
| D23 | When the ladder cannot supply project identity, `subject.project_id` is `null`, `subject.root` is the root the ladder settled on (see D28, which amends the flag-absent half of this row), and `subject.revision` is `null` outside a repository; the six report members are always emitted, never omitted | the report schema is closed, so a member cannot be dropped; the-bar "Fail loud" prefers an explicit `null` to a fabricated identity | Omitting `subject` on a `not_onboarded` entry failure, or synthesising a project id from the directory name |
| D24 | Checks are evaluated in dependency (topological) order and emitted sorted by id; `primary_check_id` is chosen over the emitted order | the two orders genuinely differ — `compatibility.contract.schema_supported` sorts before `repository.contract.resolvable` but depends on it — so one order cannot serve both; a sorted emission keeps two runs byte-comparable | Emitting in evaluation order (unstable as the registry grows) or evaluating in id order (would run a dependent before its ancestor) |
| D25 | A check object has exactly `id`, `domain`, `subject_kind`, `requirement`, `status`, `reason_code`, `repair_id`, `facts`, with `subject_kind` drawn from a closed set (`contract`, `projection`, `path`, `capability`, `host_tool`, `tracker`, `release_profile`, `residue`, `command`); a repair object has exactly `repair_id`, `module`, `safety_class`, `operation`, where `operation` is `null` for a repair no command performs and otherwise `{"subcommand", "args"}` — the owning module is named once, on the repair | issue AC2 requires the three lint items to carry a declared subject, so `subject_kind` must be on the check; the-bar "DRY" removes the module duplicated between repair and operation; several repairs (`lifecycle.ignore.repair`, every `user_action`) have no runnable command, so an operation must be nullable | Repeating `module` inside `operation`, or forcing a synthetic operation onto repairs no command performs |
| D26 | The nested-ledger repair the registry table left as "see below" resolves into two repair ids, not one with a varying class: `lifecycle.residue.nested_ledger.retain` (`user_action`, for a held lock or an unacknowledged run) and `lifecycle.residue.nested_ledger.remove` (`worktree`, only when a non-blocking `flock` succeeded and every attempt is `merged`) | a `repair_id` is a stable handle a caller may look up, so one id whose safety class changes per finding would make the class unpredictable from the id; splitting keeps `REPAIRS` a plain constant table and preserves D10's "no v1 repair is destructive" | One id whose `safety_class` is computed per finding — the id would no longer name a fixed operation, and a consumer caching it would cache the wrong class |
| D27 | The release-profile subject locator is the contract's `bindings.workflow.release`: `null` is `subject_absent`, and a declared release command is `not_run` with a third reason code `profile_unsupported`, because this slice ships no profile compiler and must not judge a profile it cannot read | the issue requires the three items registered "with their subject declared" while the compiler is a later slice; #69 forbids falling back over a value a closed set does not cover, and the checks are optional so neither `not_run` reaches the outcome | Inventing a profile file path this slice never writes (an unfalsifiable locator), or reporting `subject_absent` for a project that does declare a release command — a false negative the compiler slice would inherit |
| D28 | `--repo-root`, when omitted, is passed to the resolver as `None` so its ancestor walk runs, and the discovered root becomes `subject.root`; an explicit `--repo-root` is still the root with no walk-up. Amends D23's flag-absent clause | the live `discover_root` walks ancestors **only** for `None` and treats any supplied path as the root, so resolving `"."` first and passing it would report `not_onboarded` for every invocation from a project subdirectory — the common case for a workflow-entry caller | Resolving the flag to a path before the call and keeping `subject.root` as the caller's directory — silently disables the resolver's only discovery mode |
| D29 | One exception boundary in `main` covers resolver loading, parser construction and dispatch, re-raising argparse's `SystemExit`; its refusal carries the fixed sentence `the conformance engine failed unexpectedly`. `command_run` catches nothing. The single declared exception is the ladder's own catch (D17), where a resolver failure is a check finding rather than a refusal | D15 requires the refusal for an unexpected *engine* failure while D17 makes a resolver failure a finding; the two were reconcilable only by naming which is which. `--require`'s `choices` load the resolver at parser-construction time, so that call must sit inside the boundary. The live resolver's wrapper sets the fixed-sentence precedent, keeping refusal bytes deterministic and paths out of stdout | Truncating `str(err)` into the violation — leaks a path or a home directory and makes two runs' refusal bytes differ; or leaving parser construction outside the boundary — a resolver that will not load tracebacks instead of refusing |
| D30 | One `bound_fact`/`bound_facts` helper pair is the only route from an authored or filesystem-derived value into `facts`, and every evaluator uses it; only engine-authored literals bypass it | no path, command id, run id, worktree name or JSON pointer has a length ceiling — `is_safe_relative_path` bounds shape, not size — so a legitimate long subject would push a fact past D9's 200-character limit, fail the engine's own `validate_report`, and turn an honest finding into `resolver_failure` | Per-evaluator reasoning about whether its own subject can be long — the argument was already made and already wrong for JSON pointers |
| D31 | `Check.findings` is a declaration-ordered `(reason_code, repair_id)` mapping and the single source for what a check may emit; the evaluation guard, report construction and `repair_ids_for` all derive from it | the approved registry contract says each entry declares "the closed reason codes it may emit, and the repair it owns", and a `repair_ids_for` with no authoritative data behind it cannot answer the closure test; validating only the reason code let an evaluator name any repair that existed anywhere in `REPAIRS` | A separate reason-to-repair table beside the registry — two homes for one fact, and the closure test would prove only that `REPAIRS` is non-empty |
| D32 | An evaluator returns an `Outcome` for every expected authored or environmental condition and raises only where a closed-set dispatch inside it meets an uncovered value; replaces the flat "no evaluator raises" | the flat rule contradicted the closed-set default branch the release-profile locator needs, and the bar demands both — a finding for authored data, a loud failure for an engine defect | "No evaluator raises" (forces a silent fallback on a closed-set extension) or "evaluators raise freely" (turns an unknown tracker kind into an engine bug) |
| D33 | `settle(err)` dispatches on `err.code` to the stage that code names, overwrites a `passed` recording when it names an earlier stage, and marks *every* still-unset stage — before it in ladder order as well as after — `suppressed` by that stage's check id; `suppressed` is not a `workflow_entry` stopping status | `load_contract` raises `invalid_contract` before the schema stage runs, and `validate_projections` raises it from a later call site, so the raising call site does not determine the stage. Recording only the named stage left `schema_supported` unset on an unparseable contract, and an unset stage was specified to raise — making the promised `repository.contract.valid` result unreachable for the malformed-JSON case | Dispatching on the call site (wrong for `validate_projections`), or leaving unreached stages `None` (an evaluator-facing hole that raises on a routine refusal) |
| D34 | A nested-ledger run is removable only when a non-blocking `flock` on an **existing** `state.lock` succeeded *and* every attempt is `merged` carrying a `result` object whose `state` matches; a missing lock, a malformed or unreadable ledger, a missing result and a mismatched result are all `unacknowledged_residue` | D10 requires both a successful lock and a durable terminal result, and `workflow-state`'s own validator refuses a terminal attempt with no matching result. Treating an absent lock as "free" offered the `worktree` repair with no evidence behind it, and inferring durability from attempt-state strings alone accepted a ledger whose termination was never written down | Treating a missing `state.lock` as an unlocked run, or reading `"merged"` strings as proof of durability — both hand a reader a removal repair for state nothing has vouched for |
| D35 | The suite is environment-hermetic: the central subprocess runner injects an explicit environment (never inherits), whose `PATH` is a fixture stub bin, and the committed-root acceptance gate runs `--offline` and judges registry and report shape rather than ambient credentials | the approved "no network" test seam is unenforceable while the runner inherits the caller's `PATH` and credentials; an online gate that also forbids any `failed` check fails on a developer machine with no `gh` credential and passes for reasons the test never controlled | A fixture `PATH` the runner has no way to consume, or an online committed-root gate — machine-dependent, and it reaches the tracker from the test suite |
| D36 | The S3 `load_module` helper registers the module under its spec name in `sys.modules` before `exec_module`, using one stable fullname for loader, spec and registration, and pops it again if the load raises | the engine uses postponed annotations, so `dataclasses._process_class` resolves each field annotation through `sys.modules[cls.__module__].__dict__` while checking for `KW_ONLY`; unregistered, that lookup returns `None` and the import dies with `AttributeError` before any test reaches its seam. Reproduced against the pinned interpreter | Copying the resolver suite's loader verbatim — it works only because the resolver defines no dataclass |
| D37 | `validate-report` pins the declared report invariants, not only field shapes: outcome precedence against the emitted statuses, `primary_check_id` selection, suppression's exact facts and null repair, status/reason/repair consistency, and forbidden member names inside `facts`. Purpose selection gets one exact-id matrix over the closed registry, the read-only witness adds directory and root mtimes plus `git status`, and every verification gate parses the report instead of grepping it | the root declares those invariants but nothing checked them, so a report could satisfy the validator while contradicting its own outcome; `validate_facts` did not inherit the forbidden-name rule; four of six purposes had no test; a create/delete cycle passed a file-mtime-only witness; and a grep from a check id through a later `"passed"` token always matches on a single-line compact report | Leaving the invariants to the engine's own construction (untested by the schema the consumers check against) and keeping the text-search gates (false green, never false red) |
| D38 | A non-empty `--require` selects `host.capability.required` for every purpose, overriding the purpose's domain set; every other check stays domain-derived | #69 requires that a required capability which is `unsupported` or `blocked` fails uniformly. The Task 2 review found that `adoption`, `ci` and `fleet` carry no `host` domain, so the ladder still recorded the `capability_required` stage as failed while the report emitted five passing checks and `outcome.status: "passed"` — `conformance run --purpose ci --require release` answered success on a host where `release` was unavailable | Leaving the domain table authoritative — three of six purposes report `passed` while carrying the unmet name in `request.required_capabilities`, contradicting the contract this slice exists to implement |
