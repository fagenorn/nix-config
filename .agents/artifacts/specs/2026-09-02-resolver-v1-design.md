# Resolver v1 — authored project contract, ResolvedProject, and native projections

- **Issue:** fagenorn/nix-config#118 (implementation slice of Wayfind map #59)
- **Base SHA:** `9206f3ea92e2dde06b998b1a9e402fc2b1ad1e6d` (branch `worktree-issue-118-resolver-v1`)
- **Binding decisions:** #63 (ResolvedProject contract), #64 (neutral capability names, agent ids), #65 (`.agents/` root, projections)
- **Date:** 2026-09-02

## Problem

Every workflow skill in this repo starts by asking the same question — where are the spec and plan directories, what is the integration branch, which tracker CLI, what is the attempt budget — and today it gets the answer from `~/.agents/bin/resolve-bindings`. That helper is fail-soft by construction: it walks up for `.claude/skills.config.json`, invents any absent key from a hard-coded default table or by sniffing the `origin` remote, prints a diagnostic and **exits 0** when the config is unreadable. A workflow therefore cannot tell a deliberately authored `main` from a defaulted `main`, and a typo in the config silently becomes a working configuration with the wrong values.

That fail-soft discovery sits underneath a fail-closed lifecycle (`workflow-state`, forge writes, the permission guard). The divergence is the bug. It also blocks the larger effort: #63 fixed a `ResolvedProject` contract whose central invariant is *no project policy is ever defaulted*, and nothing in the repo implements it.

Separately, the two agents each discover their instructions from a fixed native path they do not share (`CLAUDE.md` for Claude, `AGENTS.md` for Codex). Nothing derives one from the other, so the same standing guidance is either duplicated or missing on one side, and nothing detects a hand edit.

## Solution

One authored file, one read-only operation, two derived surfaces.

1. **`.agents/project.json`** becomes the sole authored source of project truth for this repository — every project-policy value explicitly written down, nothing inferred. It is resolver input, never read directly by a skill.
2. **`resolve-project`** is a new Python helper installed at `~/.agents/bin/resolve-project`, in the house style of `workflow-state` / `diff-scope` / `artifact-budget`: closed schema, fail-loud, JSON on stdout. Its `resolve` subcommand loads, validates and normalizes the source, validates projection freshness, computes capability readiness, and prints one atomic `ResolvedProject` snapshot with exactly four top-level members. Any structural problem prints one machine-readable error carrying a closed code and exits non-zero, with no partial snapshot and no defaulted binding.
3. **Native projections** are derived from one canonical instruction source, `.agents/instructions/bootstrap.md`. Codex's root `AGENTS.md` is a wholly generated file; Claude's root `CLAUDE.md` receives one generated import line and keeps its authored body. `write-projections` renders both compare-before-write; `check-projections` — and `resolve` itself — report drift when either has been hand-edited.
4. **`writing-plans`** is the first skill entry migrated onto the resolver. It stops invoking the fail-soft helper.

`resolve-bindings` survives this slice unchanged for the six skills that still call it (D2).

### Demo

```sh
python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root .   # one JSON snapshot
printf '\nhand edit\n' >> AGENTS.md
python3 home/common/agent-skills/scripts/resolve-project.py check-projections --repo-root .   # exit 2, invalid_projection
```

## Decisions

### Files

| Path | Disposition |
|---|---|
| `.agents/project.json` | new, authored |
| `.agents/instructions/bootstrap.md` | new, authored — canonical instruction source |
| `AGENTS.md` (repo root) | new, **generated** Codex entry projection |
| `CLAUDE.md` (repo root) | modified — one generated import line appended; body stays authored |
| `home/common/agent-skills/scripts/resolve-project.py` | new — the resolver |
| `home/common/agent-skills/tests/test_resolve_project.py` | new — the suite |
| `home/common/agent-skills/default.nix` | modified — install `.agents/bin/resolve-project` |
| `justfile` | modified — add the new module to `agent-workflow-tests` |
| `home/common/agent-skills/skills/writing-plans/SKILL.md` | modified — migrated entry (D3) |
| `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | modified — assert the migrated entry text |
| `.gitignore` | modified — ignore `.agents/runtime/` |

### `.agents/project.json` — the authored source

Top-level members, all five required, no others accepted:

```json
{
  "schema_version": 1,
  "project": { "id": "fagenorn/nix-config", "name": "nix-config" },
  "bindings": { "vcs": {}, "tracker": {}, "paths": {}, "commands": {}, "workflow": {}, "deploy": {} },
  "capabilities": { "<each of the eleven names>": { "support": "supported" } },
  "projections": []
}
```

`bindings` must carry exactly the six namespaces of #63 — `vcs`, `tracker`, `paths`, `commands`, `workflow`, `deploy` — no more, no fewer. `capabilities` must carry exactly the eleven registry names, each `{"support": "supported"}` or `{"support": "unsupported"}`; omission is an `invalid_contract` violation, never an implied state (#63: "omission is not equivalent").

The concrete authored content for this repository:

```json
{
  "schema_version": 1,
  "project": { "id": "fagenorn/nix-config", "name": "nix-config" },
  "bindings": {
    "vcs": {
      "kind": "git",
      "default_branch": "main",
      "integration_branch": "main",
      "branch_pattern": "issue-<num>-<slug>",
      "worktree": { "root": ".worktrees", "prefix": "worktree-" },
      "commit": { "co_authored_by": true, "signed": true },
      "merge": { "strategy": "merge", "delete_branch": true }
    },
    "tracker": {
      "kind": "github",
      "cli": "gh",
      "repo_slug": "fagenorn/nix-config",
      "credential_env": { "unset_before_invocation": [] }
    },
    "paths": {
      "artifacts": { "specs": ".claude/specs", "plans": ".claude/plans" },
      "context": [],
      "standards": ["home/common/agent-skills/standards"],
      "architecture": ["CLAUDE.md"],
      "operations": [],
      "hints": [],
      "rejections": [".out-of-scope"]
    },
    "commands": {
      "nix-build": { "argv": ["just", "build"], "cwd": ".", "env": [] },
      "agent-workflow-tests": { "argv": ["just", "agent-workflow-tests"], "cwd": ".", "env": [] },
      "codex-review": { "argv": ["codex"], "cwd": ".", "env": [] }
    },
    "workflow": {
      "verification": ["nix-build", "agent-workflow-tests"],
      "orchestration": { "max_parallel": 2, "attempt_budget_minutes": 180 },
      "review": { "plan": "codex-review", "code": "codex-review" },
      "release": null
    },
    "deploy": { "adapter": "none", "command": null, "config": {} }
  },
  "capabilities": {
    "tracker": { "support": "supported" },
    "worktrees": { "support": "supported" },
    "knowledge.context": { "support": "unsupported" },
    "knowledge.standards": { "support": "supported" },
    "knowledge.architecture": { "support": "supported" },
    "knowledge.hints": { "support": "unsupported" },
    "verification": { "support": "supported" },
    "review.plan": { "support": "supported" },
    "review.code": { "support": "supported" },
    "release": { "support": "unsupported" },
    "deploy": { "support": "unsupported" }
  },
  "projections": [
    { "id": "codex.entry", "agent": "codex", "kind": "generated_file",
      "target": "AGENTS.md", "source": ".agents/instructions/bootstrap.md" },
    { "id": "claude.entry", "agent": "claude", "kind": "managed_import",
      "target": "CLAUDE.md", "source": ".agents/instructions/bootstrap.md" }
  ]
}
```

`orchestration.max_parallel` and `attempt_budget_minutes` carry forward the values in today's `.claude/skills.config.json` verbatim (2 / 180). `.claude/skills.config.json` stays in place this slice; the resolver never reads it (D2).

**Everything executable is a `commands` entry referenced by id** (D13). `workflow.verification` is a list of ids, `workflow.review.plan` / `workflow.review.code` / `workflow.release` are a single id or `null`, and `deploy.command` is a single id or `null`. An id that is not a key of `commands` is an `invalid_contract` violation. A `commands` entry is `{"argv": [...], "cwd": "<repo-relative>", "env": ["NAME", ...]}`; `env` lists variable **names** whose values the caller supplies from its own environment at invocation time — #63 forbids the contract from carrying values, and it carries no opaque shell text either.

All authored paths are **repository-relative**. Absolute paths, `..` segments and leading `/` are `invalid_contract` violations.

### `ResolvedProject` — the resolve output

Exactly four top-level members, no others, ever:

```json
{
  "schema_version": 1,
  "project": { "root": "/abs/path/to/checkout", "id": "fagenorn/nix-config", "name": "nix-config" },
  "bindings": { "vcs": {}, "tracker": {}, "paths": {}, "commands": {}, "workflow": {}, "deploy": {} },
  "capabilities": {
    "tracker": { "state": "available", "reason_code": null, "repair_id": null },
    "release": { "state": "unsupported", "reason_code": null, "repair_id": null },
    "deploy":  { "state": "unsupported", "reason_code": null, "repair_id": null }
  }
}
```

- `project.root` is the one absolute project root (the resolved `--repo-root`, or the nearest ancestor of `$PWD` containing `.agents/project.json`). `project.id` / `project.name` are copied verbatim from the source: repository identity is authored, never sniffed from `origin` (D5).
- `bindings` is the source `bindings` object with **every path normalized to an absolute path under `project.root`** — `paths.*` entries, `paths.artifacts.*`, and each `commands.<id>.cwd`. No other transformation; values are otherwise passed through byte-for-byte.
- `capabilities` carries all eleven names with the fixed three-key entry shape above. `reason_code` and `repair_id` are `null` unless the state is `blocked`.
- No timestamps, digests, provenance or source path appear anywhere in the output (#63).
- Output is `json.dump(..., sort_keys=True, separators=(",", ":"))` + a trailing newline on stdout, matching `workflow-state`. Success is exit 0; identical authored state plus identical readiness state yields identical bytes.
- The snapshot is invocation-scoped. Nothing writes it to disk; nothing caches it.

### Closed enums

| Enum | Members |
|---|---|
| capability registry (11, from #63) | `tracker`, `worktrees`, `knowledge.context`, `knowledge.standards`, `knowledge.architecture`, `knowledge.hints`, `verification`, `review.plan`, `review.code`, `release`, `deploy` |
| capability state (3) | `available`, `unsupported`, `blocked` |
| authored support (2) | `supported`, `unsupported` |
| error code (6) | `not_onboarded`, `invalid_contract`, `unsupported_schema`, `invalid_projection`, `capability_unavailable`, `resolver_failure` |
| binding namespace (6) | `vcs`, `tracker`, `paths`, `commands`, `workflow`, `deploy` |
| projection kind (2) | `generated_file`, `managed_import` |
| agent id (2, from #64) | `claude`, `codex` |
| `reason_code` (4) | `tracker_cli_missing`, `vcs_worktree_unsupported`, `knowledge_path_missing`, `command_missing` |

Every dispatch over these sets raises on its default branch (the bar, *Fail loud*). `orchestration` is deliberately **not** a capability name here: #63 closes the registry at eleven for this schema, and #64's `orchestration` capability is an admission that belongs to a later schema version (D9).

### Error output

Structural failure prints one JSON object on **stdout** (so a caller parses one stream) and exits **2** — the exit code `workflow-state` already uses for a refused invocation. Argparse usage errors also exit 2 but print no JSON; a caller distinguishes them by the absence of parseable JSON. Nothing else is written.

```json
{
  "error": {
    "code": "invalid_contract",
    "repair_id": "contract.bindings.namespace_missing",
    "violations": [
      { "pointer": "/bindings/deploy", "message": "required binding namespace is absent" },
      { "pointer": "/capabilities/release", "message": "required capability declaration is absent" }
    ]
  }
}
```

- `violations` is non-empty and **ordered deterministically by `pointer`** (byte-wise ascending), so two runs over the same broken source emit identical bytes.
- `repair_id` is a stable dotted string. This slice only has to *emit* stable ids; mapping them to explanations or repairs is #69's job.
- No partial `ResolvedProject` member ever appears alongside an error.

Code selection, in this order:

| Condition | Code | `repair_id` |
|---|---|---|
| no `.agents/project.json` at or above the start directory | `not_onboarded` | `onboarding.contract.missing` |
| present but unreadable / not JSON / not an object | `invalid_contract` | `contract.parse` |
| `schema_version` absent or not an integer | `invalid_contract` | `contract.schema_version.invalid` |
| `schema_version` is an integer other than `1` | `unsupported_schema` | `contract.schema_version.unsupported` |
| any structural or value violation of the source shape | `invalid_contract` | `contract.<section>.<violation>` |
| a projection target is stale, absent, or hand-edited | `invalid_projection` | `projection.<projection id>.<stale\|missing>` |
| a `--require`d capability is not `available` | `capability_unavailable` | `capability.<first offending name in pointer order>.<its `reason_code`, or `unsupported`>` |
| any unexpected internal failure | `resolver_failure` | `resolver.internal` |

`invalid_contract` collects **every** shape violation before failing (one pass, all violations reported), rather than aborting on the first.

### Capability computation

For each of the eleven names:

- authored `unsupported` → state `unsupported`, both fields `null`. No prerequisite is evaluated.
- authored `supported` → evaluate that capability's prerequisites in the fixed order below. All pass → `available`. Otherwise → `blocked` with the **first** failing prerequisite's `reason_code` and a `repair_id` of `capability.<name>.<reason_code>`.

Prerequisites are invocation-time *development readiness* facts only — never network calls, never credential values, never product/runtime conditions (#63).

| Capability | Prerequisites (in order) |
|---|---|
| `tracker` | `bindings.tracker.cli` resolves on `PATH` → else `tracker_cli_missing` |
| `worktrees` | `git` resolves on `PATH`; the parent directory of `bindings.vcs.worktree.root` exists and is writable → else `vcs_worktree_unsupported` |
| `knowledge.context` | `paths.context` is non-empty and every entry exists → else `knowledge_path_missing` |
| `knowledge.standards` | same over `paths.standards` |
| `knowledge.architecture` | same over `paths.architecture` |
| `knowledge.hints` | same over `paths.hints` |
| `verification` | every `commands[id].argv[0]` for the ids in `workflow.verification` resolves on `PATH` → else `command_missing` |
| `review.plan` | `commands[workflow.review.plan].argv[0]` resolves on `PATH` → else `command_missing` |
| `review.code` | same over `workflow.review.code` |
| `release` | same over `workflow.release` |
| `deploy` | same over `deploy.command` |

"Resolves on `PATH`" is `shutil.which`, plus — for an absolute or relative argv[0] — an executable-bit check at that path. **No subcommand of the resolver ever executes a subprocess**, including `git`; readiness is decided from the filesystem and `PATH` alone.

**Declaration/binding contradictions are contract errors, not `blocked` states (D6).** Before any prerequisite runs, a capability declared `supported` must have a complete binding, or the run fails `invalid_contract`: `tracker` requires `tracker.kind != "none"` and a non-empty `cli`; `worktrees` requires `vcs.kind == "git"`; each `knowledge.*` requires its path list to be non-empty; `verification` requires a non-empty `workflow.verification`; `review.plan` / `review.code` / `release` require their id to be non-null; `deploy` requires `deploy.adapter != "none"` and a non-null `deploy.command`. Symmetrically, a capability declared `unsupported` imposes **no** requirement on its bindings — `release: null` and `deploy.adapter: "none"` above are valid precisely because those two are declared `unsupported`.

`--require <name>` may be passed repeatedly. After computation, any required name whose state is not `available` produces `capability_unavailable`, one violation per offending name with pointer `/capabilities/<name>`, ordered by pointer.

### Native projections

One canonical source: `.agents/instructions/bootstrap.md`. Per #65 it holds only universal project invariants and the instruction to trust `ResolvedProject` — it does **not** absorb the existing 16 KB root `CLAUDE.md`, whose architecture and command prose is knowledge destined for `.agents/knowledge/` in a later slice (D4).

**`codex.entry` — `kind: generated_file`, target `AGENTS.md`.** Codex reads a root `AGENTS.md` and supports no include directive, so the file is rendered whole:

```
<!-- generated by resolve-project from .agents/instructions/bootstrap.md (project schema 1). Do not edit; edit the source and run `resolve-project write-projections`. -->

<verbatim bytes of the source file>
```

Exactly: the header line, one blank line, then the source bytes unchanged. Rendering is a pure function of (source bytes, projection id, schema version).

**`claude.entry` — `kind: managed_import`, target `CLAUDE.md`.** Claude Code expands `@path` imports in `CLAUDE.md`, which #65 names as the preferred least-context-expensive projection mechanism. The generated content is exactly one line:

```
@.agents/instructions/bootstrap.md
```

The target must contain that line **exactly once**, as a complete line. The rest of `CLAUDE.md` is authored and is never read, rewritten, or compared. Policy lives in the source; the projected line carries none.

**`write-projections`** renders every declared projection and compares before writing: a `generated_file` whose rendered bytes already match is left untouched; a `managed_import` whose line is already present exactly once is left untouched. Writes are atomic (temp file in the same directory + `os.replace`). It prints a JSON summary of `{"projections": [{"id", "action": "written"|"unchanged"}]}` and exits 0.

**`check-projections`** performs the same rendering and comparison but never writes. In sync → exits 0 and prints `{"projections": [...] }` with every action `unchanged`. Any drift → the `invalid_projection` error object and exit 2, with one violation per drifted projection, pointer `/projections/<id>`, ordered by pointer. Drift is: target missing, rendered bytes differ (`generated_file`), or the managed line absent or present more than once (`managed_import`). A missing *source* file is `invalid_contract`, not drift.

**`resolve` runs the same freshness validation** before emitting a snapshot and fails with `invalid_projection` when it drifts — #63 is explicit that a stale native projection yields no snapshot and the matching structural error.

### Command surface

One binary, three subcommands, matching the one-binary-per-contract shape of `workflow-state`:

```
resolve-project resolve            [--repo-root <path>] [--require <capability> ...]
resolve-project check-projections  [--repo-root <path>]
resolve-project write-projections  [--repo-root <path>]
```

`resolve` and `check-projections` are strictly read-only — they open no file for writing, create no directory, and run no subprocess. `write-projections` is the sole writer, and is a no-op when everything is in sync.

Root discovery: with `--repo-root <path>`, that directory **is** the root and there is no walk-up — it either holds `.agents/project.json` or the run is `not_onboarded`. Without it, the root is the nearest ancestor of `$PWD` holding `.agents/project.json`, stopping at the first hit. A worktree under `.worktrees/` therefore resolves its own checkout's contract (#65), never the primary checkout's.

The script lives at `home/common/agent-skills/scripts/resolve-project.py` and is installed by `home/common/agent-skills/default.nix` as `.agents/bin/resolve-project` with `executable = true`, exactly like `workflow-state`. `~/.agents/bin` is already on `home.sessionPath`, so skills invoke it by bare name.

### Migrated skill entry

`writing-plans` (D3). Its entry line changes from

> `planDir` from `~/.agents/bin/resolve-bindings`; helper missing → `.claude/skills.config.json`, default `.claude/plans`

to: resolve `planDir` from `~/.agents/bin/resolve-project resolve`, reading `bindings.paths.artifacts.plans` from the snapshot — an **absolute** path, since the resolver normalizes every path against `project.root`. The skill keeps the name `planDir` in its own prose so sibling skills citing that name stay correct. On the single error code `not_onboarded` — the repository has not adopted the contract yet — the skill uses the literal `.claude/plans` and says so in one line. **Every other error code is fatal**: the skill stops and reports the code rather than guessing. It never invokes `resolve-bindings`.

That `not_onboarded` branch is the migration seam, not a discovery ladder: it is keyed on exactly one closed code, it produces a literal rather than a detected or defaulted policy value, and it disappears when the remaining repositories adopt the contract (D7).

## Test seams

The existing seam for every helper in this tree is **subprocess the script against a temporary repository root and parse its stdout**, established by `tests/test_resolve_bindings.py` and `tests/test_workflow_state.py`. Reuse it; add no new seam.

`home/common/agent-skills/tests/test_resolve_project.py` (new module, added to the `agent-workflow-tests` recipe) covers:

1. **Happy path** — a synthetic onboarded root resolves: exit 0, exactly the four top-level members, exactly the six binding namespaces, exactly the eleven capabilities, every entry with the three fixed keys and a state from the closed set.
2. **Normalization** — every `paths.*` value and every `commands.*.cwd` in the output is absolute and under `project.root`; the source's relative values are untouched on disk.
3. **No defaulting** — dropping any required key from a synthetic source yields `invalid_contract` and never a snapshot; the absent value appears in no output. One subtest per binding namespace and one per omitted capability.
4. **Error codes** — one test per code: missing file (`not_onboarded`), non-JSON (`invalid_contract`), `schema_version: 2` (`unsupported_schema`), hand-edited projection (`invalid_projection`), `--require` on an `unsupported` capability (`capability_unavailable`). Each asserts exit 2, the exact code, a non-empty `violations` array sorted by pointer, and that stdout parses as JSON with no `schema_version` member.
5. **Capability states** — `unsupported` when authored so; `blocked` with a `reason_code` from the closed set and a non-null `repair_id` when a declared prerequisite is absent (a `tracker.cli` naming a binary that is not on a stubbed `PATH`); `available` when it is present.
6. **Determinism** — two consecutive `resolve` runs over the same root emit byte-identical stdout.
7. **Read-only** — `git status --porcelain` over the temp root is byte-identical before and after `resolve` and after `check-projections`; the mtimes of the projection targets are unchanged.
8. **Projection round trip** — `write-projections` on a fresh root creates both targets and reports `written`; a second run reports `unchanged` and does not touch mtimes; appending a byte to `AGENTS.md` makes `check-projections` fail with `invalid_projection` naming `codex.entry`; deleting the import line from `CLAUDE.md` makes it fail naming `claude.entry`; duplicating the import line fails likewise.
9. **The committed contract** — the repository's own `.agents/project.json` resolves successfully, its `schema_version` is `1`, its capability set is exactly the eleven names, and its `orchestration` values match those in `.claude/skills.config.json` so the two cannot drift apart while both exist.

`tests/test_workflow_skill_contracts.py` gains assertions that `writing-plans/SKILL.md` names `resolve-project`, names `not_onboarded`, and no longer contains `resolve-bindings`.

`tests/test_resolve_bindings.py` stays green untouched — the old helper's behavior is unchanged by this slice.

Seam 9 is also the repository's **drift gate**: because `resolve` validates projection freshness, `just agent-workflow-tests` fails whenever `AGENTS.md` or the `CLAUDE.md` import line has been hand-edited without regenerating. No separate recipe is added.

### Verification commands

```sh
python3 -m unittest -v home/common/agent-skills/tests/test_resolve_project.py
just agent-workflow-tests
just build
python3 home/common/agent-skills/scripts/resolve-project.py resolve --repo-root . | python3 -m json.tool | head -20
git status --porcelain    # unchanged after the resolve above
```

## Out of scope

- **#66** version and migration semantics. `schema_version` is pinned to the integer `1` for both the source and the result and asserted; no compatibility interval, no upgrade path, no deprecation window (D8).
- **#67** the bootstrap interview. `.agents/project.json` is hand-authored here.
- **#69** doctor and repair mechanics. `repair_id` values are emitted and stable; nothing maps them to an explanation or a fix.
- **#70** measurement gates. **#72** lifecycle and tracking policy.
- Moving `.claude/specs` and `.claude/plans` under `.agents/artifacts/`. The `paths.artifacts` bindings point at their current homes.
- Migrating the other six skills off `resolve-bindings`, and deleting `resolve-bindings` (D2).
- Migrating the root `CLAUDE.md` body into `.agents/knowledge/` (D4).
- Onboarding any repository other than nix-config.
- The rest of #65's taxonomy: `.agents/{skills,adapters,extensions,knowledge,artifacts,runtime}` are named by the contract but created lazily and not populated here.
- `orchestration` as a twelfth capability (D9).
- Any `.codex/config.toml`, `.claude/settings.json` or `.mcp.json` projection. Those native surfaces are machine-global and Nix-managed in this repo; projecting them is a separate decision.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The resolver is one command `resolve-project`, sourced at `home/common/agent-skills/scripts/resolve-project.py`, installed at `~/.agents/bin/resolve-project`, with three subcommands: read-only `resolve` and `check-projections`, plus the sole writer `write-projections`. | Every helper in `home/common/agent-skills/scripts/` installs to `~/.agents/bin/<name>` (`default.nix`); `workflow-state` is the precedent for one binary owning one contract behind subcommands. | Two binaries (`resolve-project` + a sibling `project-projection`) — doubles the agent-facing surface for one shared loader/validator, against *Token economy* in the bar. |
| D2 | `resolve-bindings` is not deleted and not modified in this slice; only `writing-plans` moves. The two configs coexist, and a test pins the orchestration values equal so they cannot drift. | AC-3 asks for "at least one" migrated entry; the other six skills are machine-global and run against repositories that have no `.agents/project.json`. | Deleting the helper and migrating all seven skills — breaks every non-onboarded repository at once and turns a tracer bullet into a migration. |
| D3 | `writing-plans` is the migrated entry. | It consumes exactly one binding (`planDir`), performs no forge write, and sits on the from-issue path so the bullet is visible from a real workflow. | `doc-grounded-questions` — its documented contract is "degrade gracefully; never hard-fail on a missing optional binding", which a fail-closed resolver directly contradicts. `ship-issue` — highest-stakes entry in the repo, wrong place for a first migration. |
| D4 | The canonical instruction source is a new, small `.agents/instructions/bootstrap.md`. The 16 KB root `CLAUDE.md` body is left authored and in place. | #65 restricts `bootstrap.md` to "only universal project invariants and the instruction to trust `ResolvedProject`"; moving the architecture/commands prose there would violate that and is the knowledge migration this slice excludes. | `git mv CLAUDE.md .agents/instructions/bootstrap.md` and generate a thin root `CLAUDE.md` — contract-violating content for `bootstrap.md`, and a large blast radius for a tracer. |
| D5 | Repository identity (`project.id`, `project.name`) and the tracker slug are authored in the source and copied verbatim; the resolver derives only `project.root` and path normalization from the environment. | #63: "The resolver may compute environmental facts such as repository root and invocation readiness, but not project policy." `resolve-bindings`' `origin`-remote sniffing is precisely the behavior being removed. | Keeping the `git remote get-url origin` detection as a convenience — it is inference of project policy, the exact invariant #63 closes. |
| D6 | A capability declared `supported` whose bindings are structurally incomplete is `invalid_contract`, not `blocked`. `blocked` is reserved for machine-readiness facts (a binary absent from `PATH`, an unwritable directory). | #63 separates authoring correctness (structural failure, no snapshot) from readiness (`blocked` with `reason_code`/`repair_id`); the bar's *Fail loud* forbids representing an authoring bug as a runtime state. | Emitting `blocked` for both — hides a typo in the contract behind a state that looks like a fixable environment problem. |
| D7 | The migrated `writing-plans` entry treats exactly one error code, `not_onboarded`, as "use the literal `.claude/plans` and say so"; every other code is fatal. It never calls `resolve-bindings`. | AC-3 requires the entry to stop invoking the fail-soft helper while the skill stays machine-global; a literal for an un-onboarded repo is not defaulted *project policy*, which #63's invariant governs. | Falling back to `resolve-bindings` on any resolver error — reintroduces the fail-soft posture and fails AC-3 literally. Hard-failing on `not_onboarded` — breaks planning in every repository that has not adopted the contract yet. |
| D8 | `schema_version` is the integer `1` for both the authored source and the result, and an integer `schema_version` other than `1` is `unsupported_schema`. | `workflow-state`'s `SCHEMA_VERSION = 2` sets the integer precedent; #63 defers compatibility semantics to #66, so this slice pins one value and asserts it. | A semver string (`"1.0.0"`) — invites range/compatibility logic that #66 owns and this slice must not prejudge. |
| D9 | The capability registry is exactly the eleven names in #63. `orchestration` (#64) is not added. | #63 closes the registry "for the active schema"; adding a twelfth name here would silently define schema-1 semantics that #64's admission gate and #66's versioning own. | Adding `orchestration` as a twelfth capability so `orchestrate-issues` can migrate later — widens the closed set outside the decision that owns it. |
| D10 | Projection freshness is a structural error on `resolve` (`invalid_projection`, no snapshot), not a capability state. | #63 states plainly that "a stale native projection yields no snapshot and the matching structural error"; #65's "gates the corresponding capability" has no corresponding capability in the eleven-name registry. | Gating each agent's capabilities on its own projection — no registry capability corresponds to an agent entry surface, so the mapping would have to be invented here. |
| D11 | The Claude projection is a single generated `@.agents/instructions/bootstrap.md` import line inside the otherwise-authored root `CLAUDE.md`; the Codex projection is a wholly generated `AGENTS.md`. Both are rendered by `write-projections` and both are drift-checked. | #65 names live import as the preferred mechanism for Claude and generated native syntax for formats without one; Codex supports no include directive (verified against both vendors' docs). | Generating a whole `.claude/CLAUDE.md` as well — Claude loads `./CLAUDE.md` *or* `./.claude/CLAUDE.md`, so a second file risks shadowing the authored one. A managed *region* of prose inside `CLAUDE.md` — #65 forbids generated surfaces carrying independently editable policy. |
| D12 | Errors print one JSON object on stdout and exit 2, with `violations` sorted byte-wise by JSON pointer and all shape violations collected in one pass. | `workflow-state` returns 2 for a refused invocation and writes its machine-readable payload to stdout; #63 requires "deterministic ordered violations". | Errors on stderr — forces every caller to read two streams to tell a refusal from a snapshot. Aborting on the first violation — makes fixing a contract an N-round loop. |
| D13 | Every executable invocation is a `commands` entry addressed by a stable id; `workflow.verification`, `workflow.review.*`, `workflow.release` and `deploy.command` hold ids, never inline argv. | #63 defines `commands` as the namespace of "named structured invocations (`argv`, working directory, and environment-variable names), never opaque shell text or secrets"; the bar's *DRY* wants one authoritative home per invocation. | Inline `{argv,cwd,env}` objects at each use site — the same command written twice drifts, and `commands` stops being the single home #63 names. |
| D14 | No glossary, CONTEXT map or ADR file is created by this slice; the spec's decision ledger plus the resolution comments on #63/#64/#65 remain the decision store. | This repository has no `docs/` tree and no context map; #65 states explicitly that no glossary or ADR file is created while the `.agents/knowledge/` root has not materialized. | Creating `docs/areas/...` for the resolver — imposes the standard tree mid-flight and duplicates a decision store the tickets already own. |
| D15 | The Python test suite is the drift gate: `resolve` validates projection freshness, and seam 9 resolves the repository's own committed contract, so `just agent-workflow-tests` fails on a hand-edited projection. No new `just` recipe, no CI change. | CLAUDE.md: `just build` and the Python suites are the local verification steps; CI evaluates only `nixosConfigurations.anis-desktop`. | A dedicated `just agent-projections-check` recipe — a second gate over the same assertion, and one more surface to keep in step. |
| D16 | `--require` accepts only the eleven registry names, enforced as a closed argparse `choices` set; an unknown name is an argparse usage error — exit 2 with nothing on stdout — not a JSON error object. | The error-output section already tells a caller to distinguish a usage error from a refusal by the absence of parseable JSON, and the bar's *Fail loud* requires every dispatch over a closed set to raise rather than default. | Emitting `capability_unavailable` (or `invalid_contract`) for an unknown `--require` name — dresses a caller's typo as a project-contract failure, and a misspelled requirement would then look like a satisfiable one. |
| D17 | `write-projections` refuses a `managed_import` target that already holds the managed line more than once, failing `invalid_projection` with `projection.<id>.stale`; it writes only when the line is absent, and creates an absent target holding exactly that line. | The `CLAUDE.md` body outside the managed line is authored and is never rewritten; de-duplicating would edit authored content, which #65 forbids a generated surface from owning. The same ambiguity is already drift for `check-projections`, so the two subcommands agree. | Silently deleting the surplus copies — the sole writer would mutate authored prose it does not own, and a caller would never learn its file had been ambiguous. |
| D18 | A subcommand is registered only in the task that implements it: Task 1 carries `resolve` alone, Task 3 adds `write-projections`, Task 4 adds `check-projections`. Invoking one before its task is an argparse usage error, not a placeholder refusal. | The bar, *Production-grade by default*: committed code carries no `TODO`, no placeholder waiting to be filled, no half-wired path. The plan's original staging committed a registered handler returning a `TODO` violation. | Registering all three in Task 1 with `resolver_failure` placeholder bodies — every intermediate commit would then ship a half-wired public interface, and the drift-gate test at Task 3 would pass for the placeholder reason rather than for drift. |
| D19 | Only `unsupported_schema` short-circuits validation. An absent, non-integer or boolean `schema_version` is an `invalid_contract` case and contributes its `/schema_version` violation to the same one-pass list as every other shape violation; the published `repair_id` is still the first violation in byte-wise pointer order. | This spec's own error table classifies an invalid `schema_version` as `invalid_contract`, and its adjacent rule requires `invalid_contract` to report **every** violation in one pass. Short-circuiting it contradicted the second rule. | Keeping the pre-pass abort for both cases — an author fixing a typo would be shown one violation at a time, which is the N-round loop D12 already rejected. A schema-1 shape pass is genuinely meaningless for another schema, so `unsupported_schema` keeps its short circuit. |
| D20 | Every leaf the contract types as a string must be a non-empty string, and every boolean leaf a real `bool` checked before the `int` test; no enum is invented for `vcs.kind`, the branch fields, `vcs.merge.strategy`, `tracker.kind`, `tracker.cli`, `tracker.repo_slug` or `deploy.adapter`, whose vocabularies this schema does not close. | #63's invariant that no project policy is defaulted is worth nothing if `default_branch: null` or `repo_slug: []` survives into a snapshot; the validator's structure rules typed the containers but not these leaves. | Closing an enum for each of them — the decision that owns those vocabularies is #66, and inventing one here would reject a legitimately different project. |
| D21 | The read-only guarantee is asserted by three independent witnesses over a real `git init` fixture: `git status --porcelain` bytes, the recursive path-and-type set outside `.git`, and file mtimes; and it is asserted for refusing runs, not only successful ones. | AC-5 is "running it leaves the working tree unchanged"; a file-mtime comparison alone cannot see a created empty directory, and a path-set comparison alone cannot see a rewrite with identical bytes. | The original empty-`.git` fixture with an mtime-only comparison — it could not run `git status` at all, so the seam the spec named was never actually exercised. |
| D22 | A relative command executable resolves against that command entry's own `cwd`, never against `project.root`. | `commands.<id>` authors a `cwd` precisely because the command runs there, so `{"cwd": "tools", "argv": ["./check"]}` must be probed at `<root>/tools/check`; checking it at the root would report a capability `available` on the strength of an unrelated file. | Resolving every relative `argv[0]` against `project.root` — no committed nix-config command is relative today, so the bug would have shipped latent and surfaced in the first project that authors one. |
| D23 | `resolver_failure` is exercised in-process: the test loads the module by path and monkeypatches `load_contract` to raise, then asserts the wrapper's closed code, its fixed `repair_id`, and that the exception text does not reach the output. | Every reachable external input is already classified into another code, so no subprocess fixture can induce the branch; leaving the closed set's sixth code untested was the alternative. | A subprocess fixture such as a directory or an unreadable file at the contract path — both are `OSError`, which `load_contract` classifies as `invalid_contract`, so the test would have asserted the wrong branch and passed for the wrong reason. |
