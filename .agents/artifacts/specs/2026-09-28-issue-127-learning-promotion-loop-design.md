# Learning promotion loop v1: the candidate lifecycle, the ordered classification and the leftover-duplicate check

Issue: [#127](https://github.com/fagenorn/nix-config/issues/127). Parent map: [#59](https://github.com/fagenorn/nix-config/issues/59).
Binding decisions: [#68](https://github.com/fagenorn/nix-config/issues/68) (capture, lifecycle, classification, corroboration, deployment), [#70](https://github.com/fagenorn/nix-config/issues/70) (the evidence gate), [#64](https://github.com/fagenorn/nix-config/issues/64) (adapter/extension identifiers and the admission gate), [#62](https://github.com/fagenorn/nix-config/issues/62) (the inventory that supplies the demo's corroboration).
Instruments consumed: [#120](https://github.com/fagenorn/nix-config/issues/120) (`agent_tools.agent_gate_bundle`), [#122](https://github.com/fagenorn/nix-config/issues/122) (the conformance engine).
Recovery evidence: the v1 design `.claude/specs/2026-09-03-issue-127-learning-promotion-loop-v1-design.md` on the read-only branch `worktree-issue-127-learning-promotion-loop-v1`. It is cited as evidence only. This spec stands alone, and every v1 decision it keeps is restated in the ledger below.

## Problem

A lesson learned in one repository has nowhere to go. In the last window, a real cross-cutting lesson was deliberately *not* promoted, because the only destination on offer was another skill document and widening the PR was not an autonomous call. It then needed its own issue and a full workflow cycle to land, and the same lesson turned out to be documented already, in a different file. The fleet's failure mode is a fourth copy of a maxim: each copy can drift, and none of them is the authority.

#68 settles the whole loop as policy, and #62 inventoried the fleet, but nothing *executes* either one. There is no capture command, no candidate document, and no place where the ordered classification is applied. No gate demands corroboration before a lesson becomes global doctrine, and the conformance engine has no way to notice that a "promoted" lesson still has its local copy on disk. Today all of these facts live as free prose in run reports.

The common case is an ordinary sweep that finds nothing reusable. That path must stay cheap, and its empty result must be *recorded* together with the commands used to look, not just asserted.

## Solution

The solution is one new `agent_tools` command, `promotion`, plus one new check registered with the conformance engine.

**`promotion`** is a validator and transition-computer over authored facts (D4). It owns three schema-versioned documents and four subcommands, and it is standard-library Python in the `agent_tools` package with one command-table row (D2). It never calls the tracker and never executes a recorded command. Its only child process is `resolve-project`, which it runs by command name on `PATH` (D5).

- A human writes a draft.
- `capture` turns the draft into a candidate in `captured` and prints the labelled `gh issue create` argv as data. The human runs that argv (D1).
- `advance` walks the candidate through #68's lifecycle and refuses any transition whose gate is unmet.
- `evaluate` records a sweep, whether it found candidates or found nothing.
- `validate` is the schema seam.

**`repository.residue.promoted_duplicate`** is a new required check in #122's closed registry. It reads the tracked candidate documents, selects the `promoted` ones, and reports any declared local duplicate in *this* repository that is still on disk (D10, D11).

### Demo

```sh
# 1. Capture a deferred lesson. The tracker is not touched; the argv is data.
just promotion capture \
  --input  .agents/knowledge/promotions/drafts/investigate-before-changing.json \
  --output .agents/knowledge/promotions/candidates/investigate-before-changing.json
# 2. The human runs the printed tracker.create_command, then binds the issue number.
just promotion advance --candidate <c> --to evaluating --tracker-ref <n>
# 3. Corroboration comes from #62 (Argus + Nodo); the cited bundle is #120's real output.
just promotion advance --candidate <c> --to decision_ready \
  --bundle .agents/artifacts/evidence/promotion-127-bundle.json
```

The candidate is now at `decision_ready` and carries:

```json
{"classification":{"rule":4,"rule_id":"standard_layer","declared_layer":"standard_layer","overridden_by_rule_1":false},
 "corroboration":{"repositories":[{"repository":"fagenorn/argus",…},{"repository":"elevenyellow/nodocom",…}],"platform_governance":null},
 "evidence":{"bundle_path":".agents/artifacts/evidence/promotion-127-bundle.json","bundle_id":"sha256:…","state":"unmeasured",…}}
```

The loop then stops exactly where #68 says it must. `advance --to authorized --authorized-by fagenorn` refuses `evidence_unmeasured` with exit 3. The empty case, which is the common one:

```sh
just promotion evaluate --output .agents/knowledge/promotions/evaluations/<name>.json \
  --command 'gh issue list --repo fagenorn/nix-config --label promotion-candidate --state open'
# {"kind":"promotion-evaluation","outcome":"empty","commands":[…],"candidates":[],…}   exit 0
```

### The capture contract (to post on #127)

> `promotion capture` never mutates the tracker: it writes the candidate document in `captured` and prints the exact labelled `gh issue create` argv as data. The human runs that argv to create the promotion-candidate issue, and the candidate cannot leave `captured` until `promotion advance --to evaluating --tracker-ref <issue>` binds the issue the human created.

## Decisions

### Files (D2)

Package modules under `python/agent_tools/`, each with one reason to change:

| Module | Owns | Package |
|---|---|---|
| `promotion_schema.py` | Closed vocabularies (states, layers, rules, codes, member sets, bounds, the knowledge directory names), the three-document validator, the path-safety predicate and symlink walk (D15), and the pure constructors that mint a candidate from a draft and an evaluation from its inputs (D13) | P1 |
| `promotion.py` | The command module: argparse (`prog="promotion"`), reading input, calling the resolver (D5), writing output, the one exception boundary and exit mapping (D12). No policy lives here | P1, and gains `advance` in P2 |
| `promotion_lifecycle.py` | The transition table, the ordered classification, the corroboration, evidence and native-admission gates, and deployment verification | P2 |

`agent_gate_bundle.py` gains one public function, `verify_bundle` (D8). `lib/agent-tools.nix` gains the command-table row `"promotion"`. The `justfile` gains `promotion *args` (same form as `agent-gate-bundle`), and the new suites join `agent-workflow-tests`. `conformance-registry.py` and `conformance-checks.py` gain the check. `.agents/project.json`, `.gitignore`, the projections and `CLAUDE.md` do not change.

**Size rule.** Every file the branch adds or changes must have a whole-file diff under `review-package`'s `member_max_bytes`, which is 65536 in `artifact-budget-policy.json`. The target is 48 KiB per new file. A suite that would exceed it is split by gate family (D20).

### Where the documents live (D3)

All documents live in the existing closed `.agents/` taxonomy. `classify_agents_relative` admits `knowledge/` and the `artifacts/evidence` bucket as `canonical_tracked`, so `repository.paths.classified` keeps passing (verified on `66ccba5`).

| Path | Contents |
|---|---|
| `.agents/knowledge/promotions/drafts/` | Authored `promotion-candidate-draft` documents |
| `.agents/knowledge/promotions/candidates/` | `promotion-candidate` documents, one file per candidate |
| `.agents/knowledge/promotions/evaluations/` | `promotion-evaluation` documents |
| `.agents/artifacts/evidence/` | Trials manifests and `agent-gate-bundle` documents |

The author chooses the filename. The document's `candidate_id` is its identity. The conformance check scans only `candidates/`.

### The repository root, the project id and the tracker slug (D5)

`capture`, `advance` and `evaluate` each accept `--repo-root PATH` and run `resolve-project resolve [--repo-root PATH]` by command name on `PATH`. When the flag is absent, it is not passed on, so the resolver's ancestor walk runs from the working directory. From the resolver they take `project.root`, `project.id`, `bindings.tracker.kind` and `bindings.tracker.repo_slug`. A missing executable, a non-zero exit, or unparseable or wrongly shaped stdout refuses `contract_unresolvable` (exit 2). When the resolver itself refused, its `error.code` becomes the violation message. `capture` also refuses `contract_unresolvable` unless `bindings.tracker.kind == "github"`, because the argv it prints is a `gh` argv. `validate` resolves nothing.

Every authored path member is a safe repository-relative path: a non-empty string, not absolute, and with no `..` component. The document validator enforces this, so a traversing path is a *document* fault (exit 2). The members covered are `destination.path`, `lesson.source.path`, every `corroboration.repositories[].path` and every `local_duplicates[].path`. Every read of one of these paths inside the repository also refuses a symlinked component at *any* depth (D15).

### The three documents

All three documents carry integer `schema_version: 1` and a `kind`. All three are clockless: no member named `created_at`, `generated_at`, `time` or `timestamp` appears at any depth. They are loaded with `agent_tools.canonical`'s `reject_duplicate_keys` and `reject_nonfinite_literal` hooks, and their ids come from `canonical.telemetry_digest` (D13).

**`promotion-candidate-draft`** holds everything a human authors. Its members are exactly `schema_version`, `kind`, `lesson`, `destination`, `corroboration`, `local_duplicates` and `native_admission`:

```
lesson           = {title: str ≤120, statement: str ≤1000, source: Citation}
Citation         = {repository: str, path: str, revision: str(40 hex)|null, anchor: str ≤200}
destination      = {layer: Layer, owner: str, name: str, path: str, anchor: str ≤200}
corroboration    = {repositories: [Citation] (≤8), platform_governance: str ≤1000 | null}
local_duplicates = [{repository: str, path: str, sha256: str(64 hex)|null,
                     disposition: "remove"|"project_only_residue"}]   (≤16)
native_admission = {gate: "issue-64", decision: "pending"|"admitted"|"refused",
                    irreducible_scenario: str ≤1000} | null
```

- `Layer` is the closed set `project_local`, `core_module`, `standard_layer`, `native_adapter`, `native_extension`, `out_of_scope_product`.
- For `native_adapter`, `destination.name` must match `adapter.<agent>.<capability>`.
- For `native_extension`, `destination.name` must match `native.<agent>.<operation>`, and `native_admission` must be present.
- `<agent>` is `claude` or `codex`, and the name segments are `[a-z0-9][a-z0-9_-]*` (#64).
- Breaking any of these rules is a document fault, never a classification miss.
- `disposition` is authored and never set by the module (D9).
- `sha256` is `null` when the author cannot digest the file, for example a duplicate in another repository. A `null` digest never counts as a match (D9).

**`promotion-candidate`** is the authored section verbatim plus a lifecycle section the module owns:

```json
{"schema_version":1,"kind":"promotion-candidate","candidate_id":"sha256:<64 hex>","state":"captured",
 "lesson":{…},"destination":{…},"corroboration":{…},"local_duplicates":[…],"native_admission":null,
 "classification":null,"evidence":null,"deployment":null,
 "tracker":{"ref":null,"label":"promotion-candidate","create_command":["gh","issue","create",…]},
 "history":[{"from":null,"to":"captured","actor":null,"rationale":null}]}
```

```
candidate_id   = telemetry_digest({lesson, destination, corroboration, local_duplicates, native_admission})
classification = {rule: 1..7, rule_id: RuleId, declared_layer: Layer, overridden_by_rule_1: bool} | null
evidence       = {bundle_path: str, bundle_id: str, state: "approved"|"rejected"|"unmeasured",
                  gate_contract: "issue-70", gate_version: 1} | null
deployment     = {verified_repository: str, removed: [path], retained: [path],
                  deferred_repositories: [str]} | null
tracker        = {ref: int ≥1 | null, label: "promotion-candidate", create_command: [str]}
history        = [{from: State|null, to: State, actor: str|null, rationale: str|null}]
```

The validator types every lifecycle member. A `rule_id` must be that rule's entry in the rule table. `evidence.state` must be in the bundle triple. `gate_contract`/`gate_version` equal `agent_gate_bundle.GATE_CONTRACT`/`GATE_VERSION`, imported rather than copied. It never ties the *presence* of `classification`, `evidence` or `deployment` to `state`, because state coupling belongs to the gates alone (D13).

`tracker.create_command` is exactly:

```
["gh","issue","create","--repo",<repo_slug>,"--label","promotion-candidate",
 "--title","promotion: " + lesson.title,"--body",<body>]
```

`<body>` is newline-joined fixed lines. It holds bounded fields and links, never the statement (#68: "stores bounded fields and links to source artifacts rather than copying their contents"):

- `candidate: <candidate_id>`
- `document: <--output path relative to project.root>`
- `source: <repository> <path>@<revision|unpinned>#<anchor>`
- `destination: <layer> <owner>/<name> <path>#<anchor>`
- one `corroboration: <repository> <path>#<anchor>` line per citation, or `platform_governance: provided` when the governance proof is used

**`promotion-evaluation`** is the record AC5 asks for:

```json
{"schema_version":1,"kind":"promotion-evaluation","evaluation_id":"sha256:<64 hex>",
 "scope":{"repository":"<project.id>","revision":"<40 hex>|null"},
 "commands":["<verbatim>",…],"candidates":["<candidate_id>",…],"outcome":"empty"}
```

- `evaluation_id` digests the document without `evaluation_id`.
- `outcome` is `empty` exactly when `candidates` is empty, and `found` otherwise.
- `commands` holds at least one opaque string (≤16 strings, each ≤1000 characters), recorded verbatim and never executed (D19).
- `revision` comes from `--revision` when given and is `null` otherwise. It is never fabricated.

### The ordered classification (D6)

Classification is applied once, on `captured → evaluating`, and recorded. The rule table `CLASSIFICATION_RULES` is the only classification authority. It is walked in #68's order and stops at the first match:

| # | `rule_id` | Matches when |
|---|---|---|
| 1 | `duplicate_of_platform` | The file at `destination.path` under `project.root` is a readable regular file with no symlinked component and has a line equal to `destination.anchor` once trailing whitespace is stripped (D23) |
| 2–7 | `project_local`, `core_module`, `standard_layer`, `native_adapter`, `native_extension`, `out_of_scope_product` | `destination.layer` equals the rule's id |

- Rule 1 is the only rule that reads the filesystem, and the only one that can override the author. When it overrides, the record carries `overridden_by_rule_1: true` beside the author's `declared_layer`. This is #68's "already owned by the shared platform is a duplicate-removal migration".
- Every schema-valid draft matches one of rules 2–7, so reaching the end of the walk raises. That is an engine defect, not an authored condition.
- Rule 6 records a *referral* to #64's gate. It does not execute that gate.
- A rule-1 candidate passes through the same gates as every other candidate (D26).

### The lifecycle (D7)

The states are exactly #68's: `captured`, `evaluating`, `decision_ready`, `authorized` and `promoted`, with `rejected`, `withdrawn` and `superseded` terminal. The transition table is closed. A pair that is not in the table refuses `transition_not_permitted`.

| From | To | Gate |
|---|---|---|
| `captured` | `evaluating` | `--tracker-ref <int ≥1>` (`tracker_ref_required`); the classification is computed |
| `captured` | `withdrawn` | `--rationale` |
| `evaluating` | `decision_ready` | Corroboration is satisfied, and `--bundle` passes `verify_bundle` (`evidence_unresolvable`); its state is recorded |
| `evaluating` | `rejected` / `withdrawn` | `--rationale` |
| `decision_ready` | `authorized` | Corroboration re-verified; the bundle at `evidence.bundle_path` re-verified with the same `bundle_id`; `evidence.state == "approved"` checked positively (`evidence_unmeasured`, `evidence_rejected`); for rule 6, `native_admission.decision == "admitted"` (`native_admission_pending`); `--authorized-by` (`authorizer_required`) |
| `decision_ready` | `evaluating` | The re-measure edge; clears `evidence` |
| `decision_ready` | `rejected` / `withdrawn` | `--rationale` |
| `authorized` | `promoted` | Deployment verified (below) |
| `authorized` | `rejected` | `--rationale`, which is #68's reconciliation outcome |
| `promoted` | `superseded` | `--superseded-by sha256:<64 hex>`, checked for shape only |

- A missing `--rationale` refuses `rationale_required`.
- Every transition appends one `history` entry. The actor is `--authorized-by`, and every other edge records `null`.
- The terminal states have no outgoing edge. `promoted` has exactly one: to `superseded`.
- A missing `--superseded-by` is an argparse usage error, because `superseded` has one inbound edge. A missing `--tracker-ref`, `--rationale`, `--authorized-by` or `--bundle` is an exit-3 gate keyed on the resolved edge (D12).
- A flag that has no meaning for the requested `--to` is an argparse usage error.

**Corroboration** is satisfied in one of two ways:

- at least two `corroboration.repositories` entries whose `repository` values are *distinct* and whose `path` and `anchor` are non-empty; or
- a non-empty `platform_governance` proof.

Otherwise it refuses `corroboration_insufficient`. It is checked at both `decision_ready` and `authorized`.

**Evidence** goes through `agent_gate_bundle.verify_bundle(document) -> state`. It raises `BundleIntegrityError` unless all of the following hold:

- `kind`, `schema_version`, `gate_contract` and `gate_version` are that module's constants;
- `bundle_id` equals `telemetry_digest` of the body without `bundle_id` and `generated_at`;
- `decide(document["evidence"])` equals the recorded `state`.

An unreadable or non-JSON bundle file, or a raised error, refuses `evidence_unresolvable`. **The module has no override flag.** #68's "rejected or unmeasured evidence cannot be relabelled approved by human override" is enforced by the structure, and a bundle's own `override` block never changes its `state` (#70).

**Deployment** (`authorized → promoted`) is verified only in this repository (D9). Let `here` be `project.id`.

1. The `authorized` gates are re-run, with the same codes: corroboration, re-verification of the recorded bundle, `approved`, and native admission. A hand-edited `authorized` candidate therefore gains nothing (D24).
2. `destination.path` must pass rule 1's line match. Otherwise the transition refuses `destination_missing`.
3. Each `local_duplicates` entry, in order, is handled as follows:
   - `disposition == "project_only_residue"` → recorded in `retained`.
   - `repository != here` → recorded in `deferred_repositories`.
   - The path is absent → recorded in `removed`.
   - The path is a regular file whose bytes digest to a non-null recorded `sha256` → refuse `duplicate_present`.
   - Anything else → refuse `promotion_reconciliation_required`. This covers other bytes, a `null` digest, a directory, a symlink, a symlinked component and an unreadable file.

The module never deletes, merges or rewrites authored material. #68's three reconciliation outcomes each have a route:

- Declare project-only residue: the `disposition` value.
- Incorporate the drift into a new shared revision: capture a *new* candidate (its `candidate_id` changes). Take the old one to `rejected`, or to `superseded` once the new one is promoted.
- Reject: the `authorized → rejected` edge.

### CLI surface

```
promotion capture   --input <draft> --output <path> [--repo-root PATH]
promotion advance   --candidate <path> --to <state> [--repo-root PATH] [--tracker-ref N]
                    [--bundle PATH] [--authorized-by NAME] [--rationale TEXT] [--superseded-by ID]
promotion evaluate  --output <path> --command TEXT (repeatable, ≥1) [--candidate ID (repeatable)]
                    [--revision HEX] [--repo-root PATH]
promotion validate  --input <path>
```

- `--bundle` and the path members are relative to `project.root` (D5).
- `capture` and `evaluate` refuse `output_outside_root` (exit 2) unless `--output` resolves under `project.root` (D25). They create `--output` exclusively, without creating parent directories, and refuse `output_exists` rather than overwrite.
- `advance` rewrites `--candidate` in place atomically (a temp file in the same directory, then `os.replace`) and leaves the file byte-identical on any refusal. There is no lock (D14).
- Each producing subcommand also prints its document to stdout.
- `validate` dispatches on `kind`, prints `{"valid":true}` and writes nothing.

### Exit codes and the refusal shape (D12)

- **0**: a document was produced or validated.
- **3**: a gate or transition refused on the candidate's own facts. The codes are `transition_not_permitted`, `tracker_ref_required`, `rationale_required`, `authorizer_required`, `corroboration_insufficient`, `evidence_unresolvable`, `evidence_unmeasured`, `evidence_rejected`, `native_admission_pending`, `destination_missing`, `duplicate_present` and `promotion_reconciliation_required`.
- **2**: a tool or structural failure. The codes are `unreadable_input`, `invalid_document`, `output_exists`, `output_outside_root`, `contract_unresolvable` and `internal_failure`. Every argparse usage error also exits 2, with no JSON.

Both 3 and 2 print exactly one object on stdout:

```json
{"error":{"code":"<code>","candidate_id":"sha256:…|null","state":"<state>|null",
          "violations":[{"pointer":"/evidence/state","message":"…"}]}}
```

`main` is the single exception boundary. An unexpected exception writes one `promotion: <repr>` line to stderr and prints `internal_failure` with the fixed message `the promotion module failed unexpectedly`.

### The conformance check (D10, D11)

| Field | Value |
|---|---|
| `id` | `repository.residue.promoted_duplicate` |
| `domain` / `subject_kind` / `requirement` | `repository` / `residue` / `required` |
| `depends_on` | `("repository.contract.valid",)` |
| `findings` | `(("promoted_duplicate_drifted", "promotion.duplicate.reconcile"), ("promoted_duplicate_present", "promotion.duplicate.remove"))`, in severity order |
| `run` | `check_residue_promoted_duplicate` |

- Two repairs join `REPAIRS`: `promotion.duplicate.remove` (module `promotion`, `worktree`, operation `null`) and `promotion.duplicate.reconcile` (module `promotion`, `user_action`, operation `null`).
- `REPAIR_MODULES` gains `"promotion"`.
- Because the check is registered in the `repository` domain, every non-`workflow_entry` purpose selects it. No purpose table changes.

The evaluator is pure and read-only.

1. It lists `*.json` directly under `<root>/.agents/knowledge/promotions/candidates/`. When the directory is absent, the check passes.
2. It takes each object with `kind == "promotion-candidate"` and `state == "promoted"`. Any other file is ignored, because judging it is `promotion validate`'s job.
3. From those candidates, it takes the `local_duplicates` entries with `disposition == "remove"` and `repository == contract["project"]["id"]`.
4. It re-applies the safe-relative-path rule and its own `first_symlinked_component` to each path. An unsafe path, a symlinked component, a non-regular or unreadable file, other bytes, or a `null` digest counts as **drifted**. Present with matching bytes counts as **present**. Absent yields nothing.

Facts are `{"duplicates": bound_facts([...]), "count": n, "deferred_count": n, "retained_count": n}`. `deferred_count` counts the declared duplicates in other repositories. `retained_count` counts the declared project-only residue. With both, a `passed` report states its own scope limits.

The evaluator reads documents directly. It does not spawn `promotion` or import `agent_tools`, because the installed `conformance` cannot import `agent_tools`. The literals it needs are declared in `conformance-registry.py` beside the other residue constants: the candidates directory, the two `kind`/`state` values, the member names, `remove`, and the repair module name. A test pins them to `agent_tools.promotion_schema` (seam 5).

## Test seams (D16)

These five seams are hermetic: no network, no sleep, no mocks and no patched internals. The plan and every implementer inherit them and may not invent others.

1. **The `promotion` CLI as a subprocess.** It runs as `[sys.executable, "-m", "agent_tools.promotion", …]` with an explicitly built environment that carries the recipe's `PYTHONPATH` and a `PATH` holding a fixture `resolve-project`. That stub prints a ResolvedProject with the real resolver's member shape for a temp root, or exits 2 with an error object. Fixture roots are temp directories. Every transition, gate, refusal code and exit status is asserted here on observable output. A test that must supply an authored `null` digest uses a module-level sentinel, never `digest or computed`. Prior art: `tests/test_agent_gate_bundle.py`, and the conformance suites' stub `PATH` bin.
2. **`promotion validate` as a subprocess.** Each document fault is a refused file whose pointer names the fault.
3. **The source `conformance` CLI as a subprocess** (`run --purpose doctor --offline --repo-root <fixture>`), through `conformance_test_support`. Its fixture roots carry a promoted candidate whose declared duplicate is absent, present, drifted, retained or foreign.
4. **Committed-root gates.** Three things are checked. `conformance run --purpose doctor --offline` over this repository reports the check `passed`. `promotion validate` accepts every committed document under `.agents/knowledge/promotions/`. The committed candidate's `candidate_id` recomputes from its authored section. In addition, a temp copy of the committed candidate, the committed draft and the committed bundle is walked `→ evaluating → decision_ready` to observe the demo's classification, repositories and bundle state. The committed candidate itself is never re-classified (D17).
5. **An installed-layout and pinning gate.**
   - `tests/test_promotion_installed.py` joins `agent-installed-skill-tests`. It runs the built `$HOME/.agents/bin/conformance`, with `HOME` set to the built home-manager-files tree, against a temp git root. That root copies this repository's `.agents/project.json` and `.agents/instructions/bootstrap.md` and holds a promoted candidate plus an unchanged leftover duplicate. The test asserts that the check fails with `promoted_duplicate_present`.
   - `test_conformance_registry.py` gains one case that imports `agent_tools.promotion_schema` normally and asserts that the registry's promotion literals equal its constants.
   - The existing launcher test covers the new `promotion` launcher with no change.

### Acceptance criteria

| # | Criterion (issue / recovery AC) | Proof |
|---|---|---|
| 1 | `capture` creates a labelled candidate in `captured`, never without a human (issue AC1; recovery AC1) | Seam 1: `capture` emits `state: "captured"` and the exact `create_command` above, including `--repo <slug>` and `--label promotion-candidate`. A `PATH` holding only the resolver stub (no `gh`) still succeeds. `advance --to evaluating` without `--tracker-ref` refuses `tracker_ref_required`, exit 3. |
| 2 | Classification is ordered, stops at the first match and records the rule (issue AC2) | Seam 1: a `standard_layer` draft whose destination already holds the anchor classifies as rule 1 with `overridden_by_rule_1: true`. The same draft without the anchor classifies as rule 4, and so does one whose destination path has a symlinked component. |
| 3 | No `authorized` without corroboration and an `approved` bundle (issue AC3) | Seam 1: one citation, or two naming the same repository, refuses `corroboration_insufficient`. Bundles made by `assemble_bundle` refuse `evidence_unmeasured` or `evidence_rejected`, and an approved one passes. A bundle whose `state` was edited to `approved` refuses `evidence_unresolvable`. No subcommand's `--help` exposes a force or override option. |
| 4 | A promoted lesson's duplicate is removed, and the engine reports one that remains (issue AC4; recovery AC3) | Seam 1: `→ promoted` refuses `duplicate_present` for an unchanged leftover and `promotion_reconciliation_required` for a drifted one, a `null` digest or a symlink. It succeeds when the path is absent, with `removed`, `retained` and `deferred_repositories` recorded. Seam 3 covers each finding and the facts. Seams 4 and 5 cover the source and installed engines. |
| 5 | An empty evaluation records the outcome and the commands (issue AC5; recovery AC2) | Seam 1: `evaluate` without `--candidate` emits `outcome: "empty"`, `candidates: []` and the `--command` strings verbatim, exit 0. With `--candidate` it emits `found`. Omitting `--command` is a usage error, exit 2. |
| 6 | Each package passes its focused tests and the feasibility check (recovery AC4) | For each package: its suites pass, `just build` passes, and `review-package <plan> <pkg-base> <pkg-head> <out>` exits 0 with `complete` (D20). |

**What AC4 can prove here.** This repository holds no removable duplicate of a platform lesson. Its one restated maxim, `home/common/claude-code/agents/implementer.md`'s "Verify before claiming done", is a role-scoped dispatch instruction, not a second authority. #62 puts the real duplicates in Argus and Nodo, which this repository cannot see. The engine half of AC4 is therefore proved on fixture roots, and the fleet half is #68's bridge release, which is out of scope.

## Delivery: one PR, three packages (D20)

| Package | Contents | Focused tests |
|---|---|---|
| P1: validator, capture, evaluate | `promotion_schema.py`, `promotion.py` (`capture`, `evaluate`, `validate`), the command row, the recipe | `tests/test_promotion_documents.py` (seams 1 and 2), `tests/promotion_test_support.py` |
| P2: transitions, evidence, deployment | `promotion_lifecycle.py`, `advance`, `agent_gate_bundle.verify_bundle` | `tests/test_promotion_lifecycle.py` (split by gate family if the size rule requires), plus `verify_bundle` cases in `tests/test_agent_gate_bundle.py` |
| P3: conformance and demo | The registry entry, the evaluator, the repairs, the demo draft, the candidate, the trials manifest and the bundle | Seam 3 cases in the conformance suites, `tests/test_promotion_demo.py` (seam 4), seam 5 |

A package is ready for final review only when its suites pass and its commit range passes the `review-package` feasibility run.

### The demo candidate (D17)

The demo candidate is "Investigate before changing", one of the two collaboration leads the last window deferred. It appears in both fleet repositories with no global home, according to `.agents/artifacts/specs/2026-08-20-project-knowledge-inventory-research.md` (§ Sweep B, § Promotion candidates).

- **Destination:** `standard_layer`, owner `standards`, name `the-bar`, path `home/common/agent-skills/standards/the-bar.md`, anchor `### Investigate before changing`. `the-bar.md` has no such heading (verified on `66ccba5`), so rule 1 misses and rule 4 matches.
- **Corroboration:** `fagenorn/argus` `AGENTS.md` at `20d6655223e9497c2668f67dd016e1111b3a78cb`, and `elevenyellow/nodocom` `CLAUDE.md` at `cc98ed0e65d66a01895f53659e291303d8e475f3`, each anchored to its `## How we collaborate` lead 2.
- **Source:** the Argus citation.
- **`local_duplicates`:** the same two files, `disposition: "remove"`, `sha256: null`. At promotion both would be deferred.
- **Evidence:** `.agents/artifacts/evidence/promotion-127-trials.json`, a structurally valid `agent-gate-trials` manifest that declares the four core case classes with empty `strata`, and `promotion-127-bundle.json`, which is exactly what `just agent-gate-bundle --trials …` prints. Verified during design: it prints `state: "unmeasured"` with 8 diagnostics, exit 3, and `verify_bundle`'s digest and re-decide checks both hold on it. Neither file may be hand-edited, and no `agent-cost-record` may be hand-authored.
- The candidate is committed in `captured`, as `capture` printed it. No tracker issue is created by an agent.

## Out of scope

Each item below is a later slice of #59's map, not an omission.

- #68's fleet-wide bridge release and cross-repository migrations. Other repositories' duplicates are recorded as deferred.
- The owner-local declaration manifest, the platform manifest index, and the `ResolvedProject` surface for promoted artifacts.
- Freshness hooks, `reverification_required` and vendor pins (#69 owns their presentation).
- `feedback_signal` and rollback ordering.
- Emitting a `promotion_signal` from ordinary workflows. No workflow skill text changes.
- Executing #64's admission gate or re-running #70's measurement campaign. Both are consumed as references.
- Capture from any repository other than the one holding the candidate store.
- Creating the `promotion-candidate` label, which does not exist yet. That is a one-time human setup step (D1).
- Moving `resolve-project` or `conformance` into `agent_tools`; those are their own cluster PRs.
- Any change to `.agents/project.json`, `.gitignore`, the projections or `CLAUDE.md`. There is no ADR, glossary or `docs/` tree (D18).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | `capture` never mutates the tracker. It writes the candidate in `captured` and prints the labelled `gh issue create` argv (with `--repo` from `bindings.tracker.repo_slug`) as data. `captured → evaluating` requires `--tracker-ref`, so the human's tracker step is structurally required. This amends issue AC1's wording "`capture` creates … issue" to "`capture` plus the human's run of the printed argv". Creating the missing `promotion-candidate` label is a one-time human step. Carries v1 D3 | #68 "Only explicit human `capture` creates a labelled promotion-candidate issue" and "Normal project workflows never … open candidates silently"; recovery contract bullet 1; the orchestrator's never-mutate-the-tracker rule | `capture` running `gh issue create` itself: anything, an agent included, can invoke it, so it becomes an agent-reachable tracker mutation that needs credentials and the network in a module whose value is hermetic determinism. A TTY check as a "human" test: a heuristic that proves nothing and cannot be tested hermetically |
| D2 | Three `agent_tools` modules (`promotion_schema`, `promotion`, `promotion_lifecycle`), one command-table row `promotion`, a `just promotion` recipe, and suites under root `tests/`. **Reverses v1 D1, D18, D25**: no flat scripts, no `load_sibling`, no sibling-by-path lookups | `docs/standards/agent-helpers.md` rules 1, 2, 3, 5; `agent_model_drift*` split precedent; `review-package`'s 65536-byte member cap | A single `promotion.py`: estimated at over 60 KiB and would breach the member cap. Separate CLI modules per subcommand: no second concern justifies them |
| D3 | Documents live in `.agents/knowledge/promotions/{drafts,candidates,evaluations}/` and `.agents/artifacts/evidence/`. No new path class and no contract change. Carries v1 D4, re-verified against `classify_agents_relative` on `66ccba5` | The closed `CANONICAL_AGENTS_PREFIXES` and `ARTIFACTS_BUCKETS` | A new `.agents/promotions/` root, which would fail the required `repository.paths.classified`; `.agents/artifacts/specs/`, which holds design artifacts rather than machine-read lifecycle state |
| D4 | The tracker issue is the human-facing authority. The tracked candidate document is the machine record, and the module is a pure validator and transition-computer over it: no network, no `gh`, and no execution of recorded commands. Carries v1 D2, amended by D5's single resolver child | #68 "Candidate issues own lifecycle and human decisions" and "Tracker unavailability cannot affect runtime resolution"; hermetic suites | Tracker as the only store: needs the network on every read. Repository as the only authority: contradicts #68 |
| D5 | `capture`, `advance` and `evaluate` run `resolve-project resolve [--repo-root]` by command name on `PATH` and read `project.{root,id}` and `bindings.tracker.{kind,repo_slug}`. Any failure is `contract_unresolvable` (exit 2). `validate` resolves nothing. Tests put a stub resolver on `PATH`. **Reverses v1 D19's sibling load and supersedes v1 D33** | agent-helpers rule 3 and package design D16 ("an executable outside the package runs by its command name on `PATH`"); bootstrap invariant "never read `.agents/project.json` directly"; #122 D28's ancestor walk | Importing `resolve-project`: forbidden import machinery. Reading `project.json`: bypasses validation on the field the deployment gate turns on. Driving the real resolver in tests: it needs the platform `HOME` installation that only the flat suites' support can build |
| D6 | One ordered rule table, `CLASSIFICATION_RULES`, applied once on `captured → evaluating`. Rule 1 is the only rule that reads the filesystem and the only one that can override the declared layer, recorded as `overridden_by_rule_1`. Rules 2–7 compare `destination.layer` to the rule id, and running off the end raises. Rule 6 records a referral to #64 and never executes it. Carries v1 D5 and D32 | #68's ordered list; the-bar "Fail loud" and "DRY"; #64 owns its gate | A fuzzy corpus search for rule 1, which cannot be falsified. Rule 7 as a fallback. Encoding #64's steps as predicates over prose |
| D7 | `decision_ready` requires corroboration and a bundle that *verifies* (any state). `authorized` re-verifies both, requires `approved` positively, requires `admitted` for rule 6, and requires `--authorized-by`. `decision_ready → evaluating` is the re-measure edge. There is no override flag. Carries v1 D6 and D30 | Issue AC3 places both gates at `authorized`; the issue demo needs `decision_ready` with a cited bundle; #68 no-override; the-bar "Defense in depth" | Gating `decision_ready` on `approved` (#68's "unmeasured remains evaluating" read maximally): the demo becomes unreachable, since an approved bundle needs a measurement campaign, and it adds nothing the re-measure edge lacks |
| D8 | Bundle verification is a new public `agent_gate_bundle.verify_bundle`. It checks the constants, recomputes `bundle_id` over the body without `bundle_id`/`generated_at`, and re-runs `decide` on the bundle's evidence. **Reverses v1 D7**, which verified the shape only because the flat layout forbade importing #120 | the-bar "DRY": the bundle's canonical form and verdict live only in `agent_gate_bundle`; the package now allows the import; verified on a real bundle during design | Shape-only checks, which pass a hand-edited `state: "approved"`. A copy of the digest rule in `promotion_lifecycle`, which would be a second home for #120's format |
| D9 | Deployment is verified in this repository only. The destination is checked first (`destination_missing`). Foreign duplicates are recorded as `deferred_repositories` and `project_only_residue` as `retained`. A present unchanged file refuses `duplicate_present`. Drift, a `null` digest or any non-regular file refuses `promotion_reconciliation_required`. The module deletes and merges nothing. `disposition` is authored, and incorporating drift means a new candidate. Carries v1 D8, D23, D28, D29 | #68 bridge deployment and reconciliation outcomes; house rule "absent measurements are `null`"; the scope boundary | Silently skipping foreign duplicates, so that `promoted` reads as complete. Letting the module set the disposition, which is a speculative merge. Treating a `null` digest as a match |
| D10 | The conformance evaluator reads candidate files directly. Its literals live in `conformance-registry.py`, and a normal-import test pins them to `agent_tools.promotion_schema`. Carries v1 D9; its pin now imports the package instead of a `SourceFileLoader` | The installed flat `conformance` cannot import `agent_tools` (package design D15/D16: the conformance cluster moves later); `check_residue_nested_ledger` precedent | Spawning `promotion`: a child process and a second interface. Importing `agent_tools` from the engine: breaks the installed engine |
| D11 | The check is `required`, depends on `repository.contract.valid`, has two findings ordered drift before presence, and adds two `promotion` repairs with null operations plus `REPAIR_MODULES += "promotion"`. It always reports `deferred_count` and `retained_count`, and it judges only `disposition == "remove"` entries. Carries v1 D10, D21 | #68 "zero undeclared duplicate authorities" is an invariant of `promoted`; the-bar "Truthful terminal states" | `optional`/`warning` like the machine-residue checks: cannot fail a `ci` purpose for a broken promotion invariant |
| D12 | Exit 0 for a document, 3 for a gate refusal (the file is left byte-identical), 2 for a tool or structural failure. One `error` object on stdout. A missing edge argument is an exit-3 gate keyed on the resolved edge, except `--superseded-by`, which is an argparse error. The boundary writes `promotion: <repr>` to stderr. Carries v1 D11, D24, D35 | `agent_gate_bundle`'s 0/3/2 split; the-bar "Truthful terminal states" and "The log stream is the debugger" | Exit 2 for everything, which loses gate-versus-broken. Exception text in the JSON, which can leak paths into the parsed surface |
| D13 | Documents are clockless. Ids come from `canonical.telemetry_digest`, `candidate_id` covers only the authored section, and strict loads use `canonical`'s hooks. `validate` checks shape only: it never recomputes ids and never ties section presence to state. **Reverses v1's local `canonical_digest`**; carries v1 D12, D26, D36 | agent-helpers rule 4; #68 puts the timeline on the issue; a stable id across transitions is what `--superseded-by` names | A local digest copy (forbidden). Digesting the whole document, so the id changes on every transition. A validator that recomputes ids, which refuses the hand-edited tracked files it exists to describe |
| D14 | `capture`/`evaluate` create `--output` exclusively and refuse `output_exists`. `advance` replaces `--candidate` atomically in place. All also print to stdout. No lock. Carries v1 D13 | `workflow-state` ledger-in-place precedent; one human invoker per candidate | Stdout-only `advance`: `advance … > c` truncates its own input. A `flock` with no reachable race |
| D15 | Path safety (no absolute path, no `..`) and the any-depth symlinked-component walk are implemented once in `promotion_schema`. The conformance evaluator applies its own existing `first_symlinked_component` and the same rule. Carries v1 D20, D31; **reverses v1 D20's reuse of `resolve-project`'s predicate** | agent-helpers rule 3 forbids importing the flat resolver; the-bar "Defense in depth" (the evaluator reads documents it does not own) | Importing `is_safe_relative_path`, which is forbidden. Testing only the final path component, which lets `linked-dir/file` escape the root |
| D16 | Five seams, as listed under Test seams: the CLI subprocess with a stub-resolver `PATH`, `validate`, the source conformance CLI, committed-root gates, and the installed-plus-pinning gate. There is a null-digest sentinel in fixtures. Carries v1 D14, D34 | agent-helpers rule 5; package design D8, D9; #122 D16, D22, D35 | Mocks or patched internals (the-bar "Tests that can fail"). Online gates |
| D17 | Demo: "Investigate before changing", `standard_layer`, corroborated by Argus and Nodo at the #62 inventory's observed heads. It cites a real `unmeasured` bundle for an empty-strata trials manifest. It is committed in `captured`, and the walk to `decision_ready` runs on a temp copy in seam 4. The committed candidate is never re-classified. Carries v1 D15, D22, D27 | Issue demo; #62 inventory; the-bar "Moves keep their history" (point-in-time records) | A hand-authored `approved` bundle or cost records (fabricated evidence). A committed fabricated `tracker.ref`. Re-classifying in CI, which couples the suite to the-bar's live text |
| D18 | No ADR, glossary or context doc. This ledger is #127's decision store. Re-checked: the project declares no context or ADR paths. Carries v1 D16 | #68 "this wayfinding ticket remains the decision store"; `bindings.paths.context` is empty | An ADR file: a second home for #68's decisions |
| D19 | `evaluate` records its `--command` strings verbatim and executes nothing. At least one is required. Carries v1 D17 | AC5 asks only that the commands be recorded; `verification.commands.no_shell_indirection` | Executing the sweep: needs a shell, and turns a record into an unauditable re-run |
| D20 | One PR with three package task-groups. Each package is ready only when its focused suites pass and `review-package <plan> <pkg-base> <pkg-head> <out>` exits 0 `complete`. Every added or changed file stays under the 65536-byte member cap, with a 48 KiB target | Recovery contract "Deliver in reviewable packages"; the `review-package` member cap; #122 D40's undeliverable-artifact lesson | Three PRs: triple ship overhead for one coupled contract. One unsplit package: cannot be reviewed |
| D21 | The installed-engine proof runs the built `.agents/bin/conformance` with `HOME` set to the built home-manager-files tree, through `agent-installed-skill-tests` | Recovery AC3 "installed/source conformance check"; the `agent-installed-skill-tests` precedent | Proving source only: leaves the installed half of recovery AC3 unshown |
| D22 | Promotion candidates are not a `transaction_core` consumer | `transaction_core`'s closed lifecycle is a release/attempt lifecycle, and #117 names attempts first and ship-release second | Modelling the #68 lifecycle as a transaction: foreign states, and it jumps #117's consumer order |
| D23 | Rule 1 and `destination_missing` match the anchor against a whole line (trailing whitespace stripped), never as a substring | Grill scenario: `### Investigate before changing` is a substring of `### Investigate before changing code`, which would give a false rule-1 override | Substring match, as v1 had it: a prefix-collision heading silently reclassifies a lesson |
| D24 | `authorized → promoted` re-runs every `authorized` gate before verifying deployment | the-bar "Defense in depth": `validate` checks shape only (D13), so a hand-edited `state: "authorized"` would otherwise skip the evidence gate at the final boundary | Trusting the recorded state, which relies on a gate that a tracked, hand-editable file may never have passed |
| D25 | `--output` must resolve under `project.root`, or the command refuses `output_outside_root` (exit 2), which joins the exit-2 set | The issue body's `document:` line and the conformance scan are both root-relative; a candidate outside the root is invisible to the check | Recording an absolute path: it leaks machine paths into the tracker and loses the check's subject |
| D26 | A rule-1 (`duplicate_of_platform`) candidate goes through the same corroboration, evidence and deployment gates. Its deployment is the duplicate removal, because its destination already holds the anchor | #68 "every promotion must earn ticket #70's `approved` evidence result" and "a duplicate-removal migration"; one gate table (the-bar "DRY") | A fast path for rule 1 that skips the evidence gate: #68 grants no exemption, and it adds a second gate table |
