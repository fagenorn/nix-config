# Recover #121 Tasks 4–6: adoption plan/apply/verify — issue 148

Design for [#148](https://github.com/fagenorn/nix-config/issues/148), 2026-09-24.
Base `origin/main` `185cc1a4`. Parent #121 (coordination); siblings #147 (Tasks 1–3,
landed through PR #167) and #149 (Tasks 7–8). Inherited ledgers: resolver v1
(`.claude/specs/2026-09-02-resolver-v1-design.md`, cited "resolver Dn"), the conformance
engine (`.claude/specs/2026-09-03-issue-122-conformance-engine-v1-design.md`, "#122 Dn"),
the #147 slice (`.claude/specs/2026-09-23-issue-147-platform-manifest-status-design.md`,
"#147 Dn"), and the retained #121 design ("#121 Dn/Rn"), which is not on main and is
digested below.

## Problem

Main now publishes a platform manifest, validates the contract's platform interval, and
has a read-only fleet view in `resolve-project platform-status --fleet`. Nothing can
adopt a repository onto that platform yet, and nothing can put a project into the fleet
that view reads. The reviewed adoption module (`adopt-project` with `plan`, `apply` and
`verify [--register]`, plus the fleet-registry writer) exists only as nine commits on the
local retained branch `worktree-issue-121-adoption-v1`. The aggregate #121 attempt failed
packaging, and #147 has since landed the foundation those commits build on. Until they
are recovered, #149 cannot run the real nix-config adoption, and the fleet stays empty
by construction.

## Solution

1. Replay the nine reviewed Task 4–6 commits onto main with `git cherry-pick -x` in
   retained order. Only the first pick conflicts, and it resolves as a union (D1).
2. Carry the recovered code verbatim. No reconciliation commit is planned: a probe
   showed the slice passes every gate unchanged, and an audit of #147's landing deltas
   found no interaction that needs one (D3).
3. Verify with the focused suites, `just agent-workflow-tests`, `just build`, the Demo
   and conformance runs against the built generation under an isolated `HOME` (D4, D5),
   and the review-package gate (D9).
4. Installing `adopt-project` on a host remains an operator `just switch` after merge (D8).

### Demo

```sh
H=<home-manager-files tree in the closure of ./result>            # #147 D9
D=$(mktemp -d); mkdir "$D/.agents" "$D/.agents/state"             # D4
for p in bin lib share; do ln -s "$H/.agents/$p" "$D/.agents/$p"; done
F=<apply-ready fixture, built by the suite's own builder under HOME=$D>
export HOME=$D; B=$D/.agents/bin                                  # built binaries
$B/adopt-project plan --repo-root $F      # twice: byte-identical; reconcile, ready
# commit one unrelated change: re-plan yields a new plan_id; the old id -> plan_stale
$B/adopt-project apply --plan-id <new id>              # one commit on adopt-<12 hex>
$B/adopt-project verify --repo-root $F --register      # on that branch: not_integrated
# on main, after merge --ff-only: verify -> adopted; verify --register -> registered
$B/resolve-project platform-status --repo-root $F --fleet       # the row, compatible
$B/conformance run --purpose adoption --repo-root $F --offline  # outcome passed
```

## Requirements → acceptance criteria

| AC | Requirement | Evidence |
|---|---|---|
| 1 — reconciled once, provenance kept | The nine commits are replayed in retained order, with authorship kept and `-x` trailers added. Nothing is squashed or rebuilt (D1, D2). | `git log BASE..HEAD` carries nine `(cherry picked from commit …)` lines, one for each source SHA below. |
| 2 — plan read-only and content-addressed | Recovered from #121 R4.1, R4.7 and D15, with read-only proven by resolver D21's witnesses. | `test_adopt_project` (`PlanIdentityTest`, `InspectionBoundaryTest`) and `test_adopt_project_boundaries`. D5 steps 1–2. |
| 3 — apply refuses stale or unapproved plans; isolated worktree; one atomic history-preserving commit | Recovered from #121 R5, D14, D16, D17 and D33. Approval is naming a stored `ready` plan id, so a stored operation that differs from the re-derived list is unapproved and refuses `plan_stale`. | `test_adopt_apply`: refusals, tampering, gate failure, the success shape. D5 steps 2–3. |
| 4 — verify vs registration, visible to fleet preflight | Recovered from #121 R6, D18, D19 and D34. Fleet preflight is `platform-status --fleet` (D6). | `test_adopt_verify` (`RegistrationTest` and the cross-binary case). D5 steps 4–6. |
| 5 — suites, workflow suite, build, main-based conformance run | — | See Verification. |
| 6 — package holds only the slice and is feasible | No #121 documents and no Task 7–8 content (D1, D2). The spec and plan stay within the byte budget (D9). | `review-package PLAN BASE HEAD` falls within policy before final review. |

## Recovered commits

The commits are listed in retained order. Every one of them touches only Task 4–6 files:
the five adoption modules, the four adoption suites, the registry-writer hunk in
`agent_platform.py`, `default.nix` and the `justfile` list. None touches a Task 7–8
path (`.agents/project.json`, `.gitignore`, `.claude/**`, `.out-of-scope/**`). The
source SHAs exist only on the local branch (tip `fe85677c`, base `65748f48`), so this
table is their durable record on main (D2).

| # | Source | Task | Subject (abridged) |
|---|---|---|---|
| 1 | `08c9caf0` | 4 | build `adopt-project plan` over a bounded read-only inspection (the conflict) |
| 2 | `72b47ae2` | 4 | split `adopt-project` into two installed libraries |
| 3 | `c31d64e1` | 4 | hold the amendment's reach and the projection read to the boundary |
| 4 | `4fdbb8c6` | 5 | apply an adoption plan in an isolated worktree |
| 5 | `36275eb6` | 6 | verify a checkout and register it in the fleet (the registry writer) |
| 6 | `d70a08ef` | 6 | describe `verify` in the `adopt-project` overview |
| 7 | `03c08ffe` | 6 | report drift only for the refusal that names drift |
| 8 | `44afaa06` | 5–6 | split `apply` and `verify` into libraries |
| 9 | `11b1e9bc` | 4–6 | prove what the adoption commit and the stored plan are for |

`8e6f0681` landed through #147. The seven docs-only commits (`191a2344`, `5e505f5a`,
`1a7560f9`, `8a1fedd3`, `97d566aa`, `c150cfca`, `fe85677c`) touch only the #121 spec
and plan, so they are not replayed.

**Conflict resolution.** In pick 1, keep main's lines in both files and add the pick's
lines after them. The `.agents/bin/adopt-project` entry goes after the
`conformance-checks` entry in `default.nix`, and `test_adopt_project.py` goes after
`test_conformance_registry.py` in `agent-workflow-tests`. Picks 2–9 then apply cleanly:
the four `adopt_*` library entries land after `platform-manifest.json`, and the three
sibling suites land after `test_adopt_project.py`.

## Inherited #121 decisions (digest)

The recovered code and suites cite the IDs below. The retained design does not land
(D2), so on main they resolve here and in #147's digest (R1–R3, D1–D9, D18, D23 and
D26/D37). Two IDs are overloaded in the adoption code. `D12` (the error object) and
`D16` in its "usage error exits 2 with no JSON" sense are resolver IDs. In the suites,
`D21` (three read-only witnesses) and `D23` in its "in-process wrapper seam" sense are
resolver IDs too. Everywhere else, an ID means #121.

| ID | Decision |
|---|---|
| R2.2 | Both interval bounds are strict SemVer, with `max_exclusive` > `min_inclusive`. The amendment writes `[platform_version, next major)` only when `platform` is absent. |
| R4.1–R4.3, R4.7, R4.8 | `plan` is read-only against the target and inspects a bounded surface. It emits the seven-member document and stores it at `~/.agents/state/adopt/plans/<digest>.json`. A rerun on unchanged input prints byte-identical stdout. `--format human` changes only what is printed. |
| R5 | `apply` takes only a stored `ready` plan's id. It refuses on any drift before mutating, works in an isolated worktree, relocates with `git mv` and leaves no copy at an old path. A failed gate leaves no commit and keeps the worktree with failure evidence. Success is one commit on a new branch. It never pushes, merges or writes the registry. |
| R6.1–R6.4 | `verify` is read-only unless `--register` is given. `--register` then adds `{project_id, root}` atomically, and refuses the same id at another root. It persists no `ResolvedProject` and no capability verdict. Its result is `adopted`, `adopted_with_blockers` or `not_conformant`, each reported on exit 0. |
| D10 | Outcome routing is seven ordered rules, first match wins, over the five closed outcomes. |
| D14 | Plans and apply worktrees live in user scope under `~/.agents/state/adopt/`, outside the target checkout. |
| D15 | `plan_id` is SHA-256 over canonical JSON of `{adopt_schema_version, project_id, base_revision, platform, evidence, decisions.answered}`. The checkout path is excluded, and a stored id is bound to its first checkout. |
| D16 | Naming the content-addressed `--plan-id` is the exact-plan approval. A `delete-file` operation also needs `--acknowledge-deletions`. |
| D17 | The apply worktree is retained on failure. On success it is removed only after the ref is proven to hold the one commit. |
| D19 | `verify --register` refuses `not_integrated` unless the adoption commit is an ancestor of `vcs.integration_branch`. |
| D20 | `adopt-project` has its own closed `ADOPT_ERROR_CODES` (ten codes) and reuses the resolver's error shape. |
| D26 | The resolver is consumed only as a subprocess at `$HOME/.agents/bin/resolve-project`. |
| D27 | `plan.state` ∈ {`draft`, `ready`, `not_applicable`}. The three non-plan outcomes are `not_applicable` with `changes: []`. |
| D28 | The commit message is fixed, `-S` is passed exactly when `vcs.commit.signed` is true, and no co-author trailer is written. |
| D30 | The living-reference sweep is the closed `LEGACY_BINDING_CONFIGS` tuple. Nothing else is rewritten. |
| D33 | `apply` re-derives the operations through `plan`'s generator and requires byte equality with the stored `changes`. Operation paths must be contained. A mismatch is `plan_stale`. |
| D34 | `verify` discovers exactly one evidence record at `HEAD`. The adoption commit is the commit that added it, and the map is named by the record. |
| D35 | Without a valid contract, `project_id` is the normalized single remote, or else the one open question `project-id`. |
| D36 | The forward migration step is the unique record whose `from_schema` matches. `migrations` stays outside the `plan_id` source. |
| D37 | `agent_platform` owns the atomic writer and now the registry writer and lock, so `adopt-project` never imports the resolver. |

## Decisions

### Reconciliation evidence (D3)

AC1 asks for one reconciliation with the landed #147 slice. What settles "is a fix
needed" is the gates, plus an audit of the three things #147 changed while landing:

| #147 landing delta | Contact with the recovered code | Verdict |
|---|---|---|
| Conformance-ladder reconciliation | None. `adopt-project` neither imports nor runs the conformance engine, and the engine reads nothing under `~/.agents/state`: no plan, worktree or registry. | No change |
| Manifest refusals of `NaN`/`Infinity`/overflowing literals (`platform.manifest.parse`) | `adopt-project` reads the manifest only through `agent_platform.load_manifest` and maps every `PlatformManifestError` to `adopt_failure`, so it inherits the refusals. | No change |
| `agent_platform` drift, and the resolver's `emit_json` serializing whole before writing | Pick 5's registry hunk applies cleanly next to #147's reader. `ensure_directory`, kept by #147 D2, gains its callers. `adopt-project` keeps its own streaming `emit_json`, but it can only ever emit strings, integers, booleans and nulls taken from the validated manifest, the resolver's finite output, git and SHA-256 digests. | No change |

A throwaway replay on `185cc1a4` confirmed that result. `just agent-workflow-tests` ran
1,183 tests OK (one skipped), `just build` succeeded, and every Demo step and both
conformance runs passed against the built generation. A fix is therefore made only if a
Phase-6 gate or a review proves one necessary. It lands as a separate commit after the
nine picks, and its failing case goes into the owning adoption suite.

### Demo and conformance harness (D4, D5)

- **`HOME`.** Build a scratch directory whose `.agents/bin`, `.agents/lib` and
  `.agents/share` are symlinks into the built tree `$H`, with its own writable
  `.agents/state`. The Nix-installed binaries and libraries then run unchanged, and
  their library-origin and resolver-path guards still resolve through the symlinks to
  the store. Plans, worktrees and the registry land in the scratch state. Every command
  runs with `GIT_CONFIG_GLOBAL` and `GIT_CONFIG_SYSTEM` set to `/dev/null`, and the
  fixture carries its own identity with `commit.gpgsign=false`.
- **Fixture.** The apply-ready fixture comes from `apply_repo` in `test_adopt_apply`.
  Its bootstrap counterpart comes from `bootstrap_repo` in `test_adopt_project`. A
  throwaway driver under `$TMPDIR` imports those builders from the checkout under test.
  The builders render the fixture's projections with the checkout's own resolver
  source. Every asserted command is a built binary run as a subprocess. The driver is
  not committed.
- **What the run asserts**, in order:
  1. `plan` twice: the two stdouts are byte-identical, the outcome is `reconcile` and
     the state is `ready`.
  2. After one committed unrelated change, re-planning yields a different `plan_id`.
     `apply` of the old id refuses `plan_stale` (`adopt.plan.inputs_changed`), an
     unknown digest refuses `plan_not_found`, and the bootstrap fixture's `draft` id
     refuses `not_ready`.
  3. `apply` of the new id exits 0. It leaves exactly one commit between the base and
     `adopt-<12 hex>`, and `git diff-tree -M100%` shows `R100` for every move. The
     target `HEAD` does not move, the worktree is gone and no registry exists.
  4. With the adoption branch checked out, `verify --register` refuses
     `not_integrated`, and still no registry exists.
  5. After `merge --ff-only` into `main`, `verify` reports `adopted` with
     `registered: false` and writes nothing. `verify --register` then reports
     `registered: true`, and the registry holds exactly one `{project_id, root}`.
  6. `platform-status --repo-root F --fleet` lists that row as `compatible: true`, and
     `manifest_path` is the realpath of `$H/.agents/share/platform-manifest.json`
     (#147 D10).
  7. `conformance run --purpose adoption --repo-root F --offline` reports
     `outcome.status: passed`, and the report passes `validate-report`. This is the
     conformance engine's own verdict on the adopted result (D7).
  8. `conformance run --purpose doctor --repo-root "$WT" --offline` on the branch head
     yields a report that passes `validate-report` and has no `failed` check in the
     `repository`, `compatibility` or `verification` domains. `host` checks describe
     the machine rather than the slice, so they are reported but not asserted.
  9. The operator's `~/.agents/state/fleet/registry.json` and `~/.agents/state/adopt/`
     are byte-identical, or equally absent, before and after the run.
- The run happens in the plan's final task on the branch head, and again after
  ship-issue's sync with `origin/main` (#147 D10).

### Fleet preflight and the conformance engine (D6, D7)

- Fleet preflight means `resolve-project platform-status --fleet`, the #121 R3.4 view.
  Pick 5 makes `verify --register` the only writer of the registry that view reads.
  What reaches preflight is the registration, `{project_id, root}`, and nothing else.
  Preflight recomputes compatibility from the live contract, and no `verify` result is
  persisted (#121 D18, R6.3).
  The conformance `fleet` purpose is not backed by the registry, and no
  fleet-registration check is added: #122 and #147 both deferred that until a registry
  existed, and it is new behaviour beyond the Task 4–6 boundary.
- `verify`'s `no-unclassified-agent-path` check and the engine's
  `repository.paths.classified` check answer overlapping questions with two closed
  vocabularies. The adoption classifier assigns an action to each candidate, while
  #72's four lifecycle classes judge the adopted tree. The plan document's public
  `evidence[].lifecycle_class` member carries adoption's eleven-value vocabulary, which
  is not #72's four classes despite the shared name. Both are reviewed code and stay
  as they are. Demo step 7 checks that the two verdicts agree on the adopted fixture.
  Converging `verify` onto the engine is a follow-up.

### Deployment (D8)

The slice adds new files and one additive `agent_platform` hunk. It changes no
contract and no resolver behaviour. After merge, `just switch` installs `adopt-project`.
Nothing on main calls it before then. A host whose installed library predates the
binary refuses with `platform.library.missing` through the member guard. There is no
shim and no `CLAUDE.md` change, and the PR body names `just switch` as the activation
step.

### Package budget (D9)

The probe packaged the nine picks as 6 review members (about 289 KB, largest member
63,235 bytes) against a policy of 8 members and 524,288 bytes. Documents are packed by
path, whole, and before the code, so the member count does not grow evenly with their
size. Simulated sets of 54 to 100 KB kept the package at 7 or 8 members. A 120 KB set
with one 82 KB file went over. The rule is therefore conservative: the spec and plan
together stay within 70 KB, and no single document exceeds 64 KB. The plan is a root
plus at most two task members, and it cites this spec rather than restating it. The
package is remeasured after every review-fix commit. If it goes over budget, the
documents are trimmed and the recovered code is not.

## Verification

1. Focused suites: `python3 -m unittest -v` over `test_adopt_project`,
   `test_adopt_project_boundaries`, `test_adopt_apply`, `test_adopt_verify`,
   `test_resolve_platform` and `test_resolve_platform_status`.
2. `just agent-workflow-tests`, which now includes the four adoption suites.
3. `just build`.
4. The main-based run of D4/D5, all nine steps, on the head and again after the sync.
5. Provenance and boundary: `git log BASE..HEAD` carries nine `cherry picked from`
   trailers, and `git diff --name-only BASE HEAD` names only the twelve slice files,
   this spec and the plan (plus the files of any D3 fix).
6. Package feasibility: run `review-package PLAN BASE HEAD` with BASE set to the
   merge-base with `origin/main`, recomputed at packaging time. It must fall within
   the review-package policy before final review (D9).

## Test seams

These are the existing seams, and the plan may not add others:

- `adopt-project` as a subprocess under a temporary `HOME` holding the libraries, a
  fixture manifest and an executable resolver copy (#121 D23), with real `git init`
  fixtures;
- the resolver CLI as a subprocess under that same `HOME`, which is where the two
  binaries meet over the registry;
- the in-process `adopt_failure` wrapper seam (resolver D23);
- the built generation, reached through the D4 scratch `HOME`, as the Nix publication
  seam (#147 D9);
- `conformance run` and `validate-report` as subprocesses.

## Out of scope

- Tasks 7–8: the real nix-config `plan`/`apply`/`verify` run and its post-merge
  registration (#149). This includes any change to `.agents/project.json`, `.claude/**`
  or `.out-of-scope/**`.
- Landing the retained #121 design or plan (D2). Releasing, pushing or mutating the
  retained branch or worktree, which #149 still reads.
- Registry-backed conformance `fleet` checks, and converging `verify` onto the
  conformance engine (D6, D7).
- `--answer` and any other new `adopt-project` surface.
- Changes to the review-package or feasibility tooling (#152).
- `just switch` or any deploy.
- Any change to recovered behaviour beyond the pick-1 union, unless D3's rule
  admits it.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `git cherry-pick -x` the nine Task 4–6 code commits in retained order, keeping message, trailers and author. The set was verified file by file: nothing touches a Task 7–8 path. Classifier rows that name nix-config's own product paths are Task 4 classifier code, not the adoption. The pick-1 conflicts in `default.nix` and the `justfile` resolve as a union, with main's lines first. | Issue AC1; #147 D1; #121 plan Task 4 (the classification table and `LEGACY_BINDING_CONFIGS` are its deliverables); the replay probe | Squashing or re-implementing, which erases provenance. Dropping nix-config's rows from the classifier, which edits reviewed code that #149's real run depends on. |
| D2 | Recovered code is carried verbatim. The retained #121 design and plan do not land: this spec carries the commit table and a digest of every #121 ID the code cites, and it notes the resolver IDs that share a number. | #147 D2 and D3; AC6 ("only the Task 4–6 slice") | Landing the #121 documents, which bring Task 7–8 content and at least 79 KB (design plus plan root) of package pressure. Leaving the overloaded IDs unexplained, which makes `D12`/`D16`/`D21`/`D23` in the code ambiguous on main. |
| D3 | No reconciliation commit is planned. The probe (full suite, build, Demo) and the three-delta audit found nothing to fix, and `adopt-project`'s streaming `emit_json` stays because no non-finite value can reach it. A fix that a gate or review proves necessary lands as one separate commit after the picks, with its failing case in the owning adoption suite. | Issue scope ("any reconciliation fix proven necessary"); #147 D1 and D12; the bar's *YAGNI* and *Root causes* | Porting the resolver's serialize-whole emitter in advance, which changes reviewed code with no reachable failure. Folding any fix into a pick, which blurs reviewed and new code. |
| D4 | The main-based run uses a scratch `HOME` whose `.agents/{bin,lib,share}` link into the built tree and whose `.agents/state` is private, with git's global and system config nulled. Its fixtures come from the suites' own builders through an uncommitted `$TMPDIR` driver. | #147 D9 (built generation as the Nix seam); the probe ran every step this way; #121 D23 (isolation through `HOME`) | `HOME=$H`, which fails because the store is read-only and `plan` must write its state. The real `~/.agents`, which lacks `adopt-project` before a switch and whose registry belongs to #149. A hand-written shell fixture, which is a second fixture home that drifts from the contract. A committed demo script, which is new tooling in the package. |
| D5 | The run asserts the nine steps in Decisions, among them `conformance --purpose adoption` passing on the adopted fixture, `doctor` on the head with no failed non-`host` check, and the operator's state left untouched. It runs on the head and again after the sync. | Issue Demo; ACs 2–5; #147 D10; the bar's *Verify before claiming done* and *Tests that can fail* | A run proving only that `verify` passes, which leaves the stale/unapproved refusals, the history-preserving commit and fleet visibility unshown against the built layout. Asserting `host` checks, which fail for machine reasons the slice cannot cause. |
| D6 | Fleet preflight is `platform-status --fleet`, fed only by `verify --register`, which exposes the registration and never a persisted verdict. The conformance `fleet` purpose is not registry-backed, and no fleet check is added. | #121 R3.4; #122 out of scope; #147 out of scope; issue AC4 | Adding registry-backed conformance checks here, which is new behaviour past the Task 4–6 boundary and widens #122's closed registry. |
| D7 | The overlap between adoption's classifier and #72's lifecycle classes stays as it is, including the shared name `lifecycle_class`. Demo step 7 shows the two verdicts agree on the adopted fixture, and convergence is a follow-up. | D2; the bar's *DRY* (the copies need not change together yet); the probe (`adoption` passed where `verify` said `adopted`) | Rebasing `verify` onto the engine now, which rewrites reviewed code and changes a public report. Ignoring the overlap, which leaves a disagreement undetected. |
| D8 | No shim and no `CLAUDE.md` change. `just switch` is a post-merge operator step, and a library/binary skew refuses through the member guard. | #147 D8; CLAUDE.md "switch only when asked"; the slice is additive | A fallback for an older library, which is a discovery ladder that #121 forbids. |
| D9 | The spec and plan together stay within about 70 KB, with no document member over 64 KB, so the package keeps at most 8 members. The package is remeasured after each review fix, and the documents, not the code, are trimmed if it goes over. | Probe: 6 product members; simulated sets of 54–100 KB stayed within budget at 7–8 members, and a 120 KB set went over; #121 failed packaging | Unbounded planning documents, which repeat #121's packaging failure. Splitting the recovered code across two PRs, which reverses AC6's one-slice package. |
