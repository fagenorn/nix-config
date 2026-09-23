# Recover #121 Tasks 1–3: platform manifest and status — issue 147

Design for [#147](https://github.com/fagenorn/nix-config/issues/147), 2026-09-23.
Base `origin/main` `4f74c477`. Parent #121 (coordination); siblings #148 (Tasks 4–6)
and #149 (Tasks 7–8). Inherited ledgers: resolver v1
(`.claude/specs/2026-09-02-resolver-v1-design.md`, cited "resolver Dn"), the conformance
engine (`.claude/specs/2026-09-03-issue-122-conformance-engine-v1-design.md`, "#122 Dn"),
and the retained #121 design ("#121 Dn/Rn"), which is not on main and is digested below.

## Problem

The reviewed platform foundation — the platform manifest, the shared `agent_platform`
library, the contract's `platform` interval and `resolve-project platform-status` —
exists only on a local, retained branch. The aggregate #121 attempt passed review and
failed packaging (589,625 bytes against the 524,288-byte cap). Since then main has
gained the #122 conformance engine, which runs the resolver's ladder in process and
cannot run against the recovered resolver. It never binds the platform library or
manifest, it calls the pre-slice ladder signatures, and its hermetic `HOME` has no
platform installed. Replaying the commits as they are fails 58 conformance tests.
Today nothing on main can say which platform is installed, which project schemas it
supports, or whether this repository is compatible with it.

## Solution

1. Replay the nine reviewed Task 1–3 commits onto main with `git cherry-pick -x`,
   unchanged except for one `justfile` conflict (D1, D2).
2. In a separate reconciliation commit, adapt the conformance ladder to the recovered
   resolver: bind the platform first, pass the manifest, settle the interval range
   check onto the `schema_supported` stage, and publish the Demo's facts on
   `compatibility.contract.schema_supported` (D4–D6).
3. Have the conformance suites install the platform into their hermetic `HOME` (D7).
4. Verify with the focused suites, `just agent-workflow-tests`, `just build`, a
   conformance run against the built generation (D9), and the review-package gate.
   Activation remains an operator step after merge (D8).

### Demo

```sh
H=<home-manager-files tree in the closure of ./result>          # D9
HOME=$H $H/.agents/bin/conformance run --purpose doctor --repo-root "$WT" --offline
#  compatibility.contract.schema_supported: passed, facts
#  {platform_version:"1.0.0", supported_project_schemas:["1"], project_schema_version:1,
#   platform_min_inclusive:"1.0.0", platform_max_exclusive:"2.0.0"}
HOME=$H $H/.agents/bin/resolve-project platform-status --repo-root "$WT" --fleet
#  platform block with a /nix/store manifest_path, compatibility.compatible true, fleet []
```

## Requirements → acceptance criteria

| AC | Requirement | Evidence |
|---|---|---|
| 1 — reconciled once, provenance kept | The nine commits are replayed in retained order, keeping authorship and adding `-x` trailers. Nothing is squashed or rebuilt, and new code lands only in reconciliation commits (D1). | `git log BASE..HEAD` carries nine `(cherry picked from commit …)` lines, one for each source SHA below. |
| 2 — every operation validates the manifest; interval fails closed | Recovered from #121 R1.3 and R2.2–R2.4. The conformance ladder also binds the platform before discovery and reports incompatibility as `unsupported_schema` (D4, D5). | The recovered resolver suites, plus new conformance cases for a broken installation, a platform too old or too new, and an unsupported schema. |
| 3 — `platform-status` read-only, closed codes | Recovered from #121 R3, D5–D7 and D18. | `test_resolve_platform_status`: read-only witnesses, fleet rows, closed reason codes. |
| 4 — suites, workflow suite, build, main-based conformance run | — | See Verification. |
| 5 — package holds only the slice and is feasible | No #121 documents and no Task 4–8 code (D3). | `review-package PLAN BASE HEAD` falls within policy before final review. |

## Recovered commits

The table lists the commits in retained order. Every one of them touches only Task 1–3
files. The source SHAs exist only on the local branch `worktree-issue-121-adoption-v1`
(tip `fe85677c`, base `65748f48`), so this table is their durable record on main (D3).

| # | Source | Task | Subject (abridged) |
|---|---|---|---|
| 1 | `862547dd` | 1 | publish the platform manifest and gate the resolver on it |
| 2 | `afa5ceba` | 1 | pin the repair id of each whole-file manifest refusal |
| 3 | `15a20e53` | 1 | refuse an uninstalled platform library through the error contract |
| 4 | `363c2c7d` | 2 | make `platform` a required contract member with manifest-driven schema routing |
| 5 | `d87253f2` | 2 | cover the interval, the range check and the reason-code position |
| 6 | `b2202040` | 2 | widen the library guard to every member the resolver reads |
| 7 | `e4cd1d6c` | 3 | add the `platform-status` operation and the fleet view |
| 8 | `a74c4d7a` | 1–3 | split the platform cases into sibling suites (the `justfile` conflict) |
| 9 | `8e6f0681` | 1, 3 | branch-review fix: library-origin guard; `project_identity_mismatch` on fleet rows |

Nine retained product commits are left out and go to #148: `08c9caf0`, `72b47ae2`,
`c31d64e1`, `4fdbb8c6`, `36275eb6`, `d70a08ef`, `03c08ffe`, `44afaa06` and `11b1e9bc`.
The twelve design and plan document commits are not replayed. Together with the
nine picks that accounts for all 30 retained commits.

**Conflict resolution.** In pick 8, keep main's `agent-workflow-tests` list, insert
`test_resolve_platform.py` and `test_resolve_platform_status.py` right after
`test_resolve_project.py`, and add no `adopt` suite. `default.nix` and the library
hunk of pick 9 apply cleanly. No fixture contract is edited by hand:
`conformance_test_support.make_root` copies the committed contract, and that contract
gains `platform` in pick 4 (#121 D29).

## Inherited #121 decisions (digest)

The recovered code and suites cite the IDs below. The retained design itself does not
land (D3), so this digest is where those IDs resolve on main. The code also cites
resolver-v1 IDs (D10, D12, D16, D19, D21), which belong to the resolver ledger.

| ID | Decision |
|---|---|
| R1 | One strict manifest at `$HOME/.agents/share/platform-manifest.json` with seven exact members. A missing, unreadable or malformed manifest is `resolver_failure` with a stable repair id, never a default. Its identity is the resolved path actually loaded. |
| R2 | The contract's `platform` member is exactly `{min_inclusive, max_exclusive}`, both strict SemVer, with max > min. A version outside the interval is `unsupported_schema` with `platform_too_old` or `platform_too_new`. A schema outside `project_schema_versions` is `project_schema_unsupported`. A supported older schema still resolves, and `ResolvedProject` keeps four members. |
| R3 | `platform-status [--repo-root] [--fleet]` is read-only and never workflow context. With no target it reports the platform block alone. An incompatible verdict exits 0. It emits one row per registered project, refuses a structurally invalid named contract exactly as `resolve` does, and emits no secrets and no writes. |
| D1 / D2 / D3 | The manifest is an authored JSON file installed without templating. Its identity is `manifest_path`, the realpath loaded. `platform_version` starts at `1.0.0` and is bumped by hand under #66. |
| D4 | `platform` is a schema-1 member, with no schema bump and no migration. |
| D5 / D6 | `platform-status` is a fourth `resolve-project` subcommand. It reports an out-of-range interval and refuses a structurally invalid contract. |
| D7 | `SCHEMA_REASON_CODES` is separate from the capability `REASON_CODES`. `reason_code` is present exactly for `unsupported_schema`. |
| D8 / D9 | Supported schemas come from the manifest, and the resolver holds no schema literal. Versions are strict `MAJOR.MINOR.PATCH` only. |
| D18 | A registry entry is exactly `{project_id, root}`, and rows re-read the live contract. |
| D23 | Tests isolate through a temporary `HOME` holding the manifest and library, with no test-only flag. |
| D26 / D37 | `adopt-project` never imports the resolver, so `destination_mode` and `write_atomically` live in `agent_platform`, and the resolver imports them back. |
| D30 | The committed-contract path assertion does not depend on where paths move. |
| D36 | `migrations` entries are closed single steps `{id, from_schema, to_schema}`. `deprecations` and `removals` are validated and never read. |

## Decisions

### Conformance ladder

The engine keeps consuming the resolver in process (#122 D2). The whole ladder still
runs once, inside the single `except` of `repository.contract.resolvable` (#122 D17).
The steps run in this order:

| Step | Resolver call | On refusal |
|---|---|---|
| platform | `bootstrap_platform_library()`, then `require_platform_manifest()` | `resolvable` fails with `resolver_failure`, facts `{stage: "platform", resolver_repair_id}`, and every stage is suppressed under it (D5) |
| present | `discover_root` | unchanged |
| schema | `load_contract`, then `validate_schema_version(source, violations, manifest["project_schema_versions"])` | `unsupported_schema` makes `schema_supported` fail (`project_schema_unsupported`) |
| valid | `validate_contract(source, manifest)`, then `raise_for_violations`, then record `valid` as passed | `invalid_contract` makes `valid` fail; `schema_supported`, still unset, is suppressed by `repository.contract.valid` (#122 D33) |
| range | `raise_for_platform_range(source["platform"], manifest["platform_version"])`, then record `schema_supported` as passed, with facts | `unsupported_schema` (`platform_too_old`/`platform_too_new`) makes `schema_supported` fail; the report cascade suppresses `valid` |
| projection, capability | unchanged | unchanged |

- Refusal precedence now matches `resolve`: installation, then `not_onboarded`, then
  `project_schema_unsupported`, then `invalid_contract`, then range, then
  `invalid_projection`, then `capability_unavailable`. `workflow_entry`'s single root
  cause is therefore the code `resolve` would refuse with.
- One deliberate change to main's behaviour (D4): `schema_supported` is recorded as
  passed only after the range check. A contract that fails shape validation therefore
  leaves it `suppressed` by `repository.contract.valid`, as an unparseable contract
  already does, and a `passed` compatibility check always means the interval was
  evaluated.
- No closed set widens. Check ids, reason codes, repair ids, purposes, `CODE_STAGES`
  and the report schema are unchanged. The new `stage` value and the new fact keys
  are values inside the existing bounded `facts`. The recovered resolver needs no
  change: every function the ladder calls already exists.

### Facts on `compatibility.contract.schema_supported` (D6)

| Key | Value | Source | Present when |
|---|---|---|---|
| `platform_version` | string | manifest | passed or failed |
| `supported_project_schemas` | `bound_facts` of the decimal strings | manifest `project_schema_versions` | passed or failed |
| `project_schema_version` | int | contract, through the resolver's `declared_facts` | an integer is declared |
| `platform_min_inclusive`, `platform_max_exclusive` | string | contract, through `declared_facts` | the interval is well-formed |
| `schema_reason_code` | a `SCHEMA_REASON_CODES` member | the refusal's `reason_code` | failed |
| `violations`, `first_pointer` | int, string | `settle`, unchanged | failed |

A failed check carries at most eight keys, which is exactly the #122 D9 cap, so any
further key needs this row revised. There is no `compatible` fact: the check's status
is the verdict, and `schema_reason_code` says why. Authored values pass through
`bound_fact`/`bound_facts` (#122 D30). A suppressed check keeps exactly
`suppressed_by`.

Terms: the issue's "supported project-schema interval" is the manifest's
`project_schema_versions`, which #121 R1.2 publishes as an ascending set, not as
bounds. `platform_*` facts describe the agent platform generation, not the host
identity in `subject.platform`. `resolver_repair_id` (D5) is the resolver's
`PLATFORM_LIBRARY_REPAIR_ID` or the manifest refusal's own repair id, never a literal
in the engine.

### Suites (D7)

- `conformance_test_support` installs the committed manifest and library into
  `HERMETIC_HOME` with the resolver family's `install_home`, imported from
  `test_resolve_project`. A case that needs another manifest, or no library, builds
  its own `HOME` through that helper's override hook.
- New cases go in `test_conformance.py`, next to the ladder cases:
  - A missing library and a missing manifest each yield `resolvable` failed, with the
    `stage` and `resolver_repair_id` facts, every dependent check suppressed, and
    `workflow_entry` exiting 2 with one check.
  - A fixture manifest at `0.9.0`, one at `2.0.0`, and a contract at schema 2 each
    yield `schema_supported` failed with its `schema_reason_code`.
  - A malformed interval yields `valid` failed, with `schema_supported` suppressed by
    `valid`.
  - A clean root yields `schema_supported` passed, carrying the five facts.
  - Every report passes `validate-report`.
- S3 in-process ladder cases pin `HOME` to the hermetic home for their duration and
  evict the cached `agent_platform` module, as pick 9 does for the resolver.
  `test_a_resolver_exception_is_a_check_finding_not_the_refusal` also asserts
  `stage == "present"`, so the case can fail for only one reason.
- The #122 D22 committed-root gate also asserts that `schema_supported` passes with
  facts equal to the committed manifest's version and schemas and to the committed
  contract's interval. This is the in-suite form of the Demo.

### Deployment (D8)

After merge, run `just switch` on each host before any main-based checkout is
resolved. Until then, the deployed resolver refuses the new contract
(`invalid_contract`, `/platform` member unexpected), and `writing-plans` is the one
skill that calls it. After the switch, a checkout still on pre-slice main refuses in
the other direction (`/platform` member missing) until it merges main. The PR body
and the closing comment state this. There is no shim and no `CLAUDE.md` change.

## Verification

1. Focused suites: `python3 -m unittest -v` over `test_resolve_project`,
   `test_resolve_platform`, `test_resolve_platform_status`, `test_conformance`,
   `test_conformance_checks` and `test_conformance_registry`.
2. `just agent-workflow-tests`, which now includes the two platform suites.
3. `just build`.
4. The main-based conformance run (D9). Take the `home-manager-files` tree from
   `./result`'s closure and run the two Demo commands, with the branch current with
   `origin/main`. The report must pass `validate-report`. `schema_supported` must be
   passed with facts matching the committed manifest and contract. `platform-status`
   must report a `manifest_path` equal to the realpath of the tree's
   `.agents/share/platform-manifest.json` (D10), `compatible: true` and `fleet: []`.
5. Provenance and boundary: `git log BASE..HEAD` carries nine `cherry picked from`
   trailers, and `git diff --name-only BASE HEAD` names only the nine slice files,
   the conformance scripts and suites, this spec and the plan.
6. Package feasibility: run `review-package PLAN BASE HEAD` with BASE set to the
   merge-base with `origin/main`, recomputed when packaging so a main sync never
   enters the package. It must fall within the review-package policy before final
   review. The estimate is about 240 KB in about five members.

## Test seams

These are all existing seams, and the plan may not add others:

- the resolver CLI as a subprocess under a temporary `HOME` (recovered, #121 D23);
- the conformance CLI as a subprocess under the hermetic environment, now with the
  platform installed (#122 D16 and D35, plus D7);
- `validate-report` as a subprocess;
- the two S3 in-process seams, with `HOME` pinned (D7);
- the built generation as the Nix publication seam (D9).

## Out of scope

- Tasks 4–8: `adopt-project` and the `adopt_*` libraries, the registry writer and
  lock, the real adoption, and registration (#148, #149).
- Fleet-registration conformance checks and a registry-backed `fleet` purpose.
- Landing the retained #121 design or plan (D3), and pushing the retained branch as
  an archive ref.
- Changes to the review-package or feasibility tooling (#152).
- `just switch` or any deploy, and any mutation of the retained branch or worktree.
- Migrating skills onto `workflow_entry` (#122 D13).
- Any change to recovered behaviour beyond the `justfile` conflict.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `git cherry-pick -x` the nine commits in retained order, including `8e6f0681`, which touches only Task 1–3 files and whose library hunk applies without `36275eb6`. Each pick keeps its original message, trailers and author, and gains no new attribution. All new work goes in separate reconciliation commits. Intermediate picks may knowingly fail the conformance suites until the reconciliation commit lands. | Issue AC1; #121's recovery contract ("reconciled once, provenance preserved"); the PR lands as a merge commit, so main's first-parent history stays green | Squashing or reimplementing, which erases provenance (AC1). Folding the conformance fix into a recovered commit, which blurs reviewed and new code. Re-attributing the picks, which misstates who authored reviewed work. |
| D2 | Recovered code is carried verbatim. That includes `agent_platform.ensure_directory`, which has no caller until #148, and the read-only registry reader, which treats an absent registry as `fleet: []`. | AC1 "not reimplemented"; `36275eb6`, recovered by #148, calls `ensure_directory`, and its hunk context touches that helper | Pruning the unused helper, which makes #148's picks reference a removed definition and forces a second reconciliation of reviewed code. |
| D3 | The retained #121 design and plan do not land. This spec carries the recovered-commit table and a one-line digest of every #121 ID the recovered code cites. | AC5 ("only the Task 1–3 slice"); those documents cover Tasks 4–8 and add about 159 KB, the member pressure that sank #121; the retained branch is local-only | Landing the #121 spec verbatim, which brings in non-slice content and threatens the eight-member cap. Citing the local branch path, which dangles once the retained worktree is released. |
| D4 | Conformance binds the platform before `discover_root`, passes the manifest to schema and shape validation, and runs `raise_for_platform_range` after shape validation. `schema_supported` is recorded as passed only after the range check; a range failure settles onto it through #122 D33. | #122 D2, D17 and D33; #121's "range only after shape"; the bar's *Truthful terminal states* | Recording `schema_supported` as passed at the schema-set check, which reports compatibility as passed when the range never ran. Running the range before shape validation, which inverts `resolve`'s precedence, so `workflow_entry`'s root cause would disagree with `resolve`. |
| D5 | A broken installation (missing library or bad manifest) is `resolver_failure`/`conformance.internal` on `repository.contract.resolvable`, with facts `stage: "platform"` and `resolver_repair_id` (the resolver's own `platform.*` id). No check id, reason code or repair id is added. | #122 D17 (the only `resolver_failure` emitter) and D31 (one repair per code); #121 R1.3; the caller's rule to widen closed sets only when unavoidable | A `host.platform.installed` check or a `platform.install` repair, which widens the registry and breaks D31's one-code-one-repair mapping for a condition an existing check already names. |
| D6 | The Demo's facts ride on the existing `compatibility.contract.schema_supported`, on both passed and failed. Its status is the compatibility verdict. There is no new check id and no report-schema change, and fleet facts stay with #148/#149. | Issue Demo; #122 D9 and D30; `host.tracker.credential` sets the precedent for facts on a passed check; #122 scopes platform intervals to the `compatibility` domain | A separate interval check, whose extra `unsupported_schema` stage no code-keyed `CODE_STAGES` can route. Report members in `subject`, which is a schema change. |
| D7 | The conformance suites install the platform with the resolver family's `install_home`, and no second installer is written. S3 ladder cases pin `HOME`, evict the cached library and assert the `stage` fact. The D22 gate asserts the Demo facts. | #122 D16 and D35; pick 8's precedent that siblings import `test_resolve_project`'s fixtures; pick 9's cache eviction; the bar's *Tests that can fail* | A copy of the install layout in `conformance_test_support`, which gives the layout two homes. Leaving S3 cases on the process `HOME`, which makes their outcome depend on whether the machine has switched. |
| D8 | No compatibility shim. `just switch` is a documented post-merge operator step, and each side of the skew fails loud until it is taken. | #121 D4 and its risk row ("intended: fail loud"); bootstrap's "no policy is defaulted"; CLAUDE.md's "switch only when asked" | A resolver that tolerates a missing or unknown `platform`, which defaults policy. Bumping to schema 2 with a migration, which reverses #121 D4. |
| D9 | AC4's main-based conformance run uses the `home-manager-files` tree that `just build` produced as `HOME`, running that tree's own `conformance` and `resolve-project`. | The deployed `~/.agents` files are symlinks into exactly that tree (observed), so this is the production layout without activation, and it also proves the Nix wiring | A staging `HOME` hand-copied from repository files, which does not exercise `default.nix`. `just switch`, which needs authorization and deploys unreviewed code. |
| D10 | The D9 run asserts that `manifest_path` equals the realpath of `$H/.agents/share/platform-manifest.json`. That is a `/nix/store` path of its own, not a path inside `$H`, and this row revises Verification 4's "inside that tree's store path". The run happens in Task 2 on the branch head, and again after ship-issue's sync with `origin/main`. | A scratch build of the replayed slice resolved the file to `…-hm_platformmanifest.json`: home-manager links each file to its own store path. Verification 4 asks for a head that is "current with `origin/main`". | Asserting a path inside `$H`, which no correct build satisfies. Running the demo only before the sync, which leaves the main-based claim unproven once `main` advances. |
| D11 | Suite fixture cases declare their own interval `[1.0.0, 2.0.0)` and install explicit fixture manifests (`0.9.0`, `2.0.0`, `1.4.2`), and they assert literal facts. Only the D22 gate and the D9 run read the committed manifest and contract. The S3 `HOME` pin is a `PlatformHome` mixin whose `setUp` pins every case in the class. | The bar's *Tests that can fail*; #121 D1–D3 (`platform_version` is bumped by hand); D7 | Literals equal to the committed values, which would couple every case to the next hand bump and could not tell the installed manifest from the committed one. Per-case pin calls, which a new S3 case could forget. |
