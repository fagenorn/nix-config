# Agent skills — project adapter contract

The skills in `skills/` are project-agnostic: they carry zero project residue and read everything
project-specific through one retained `ResolvedProject` snapshot at each phase entry. A new project
onboards through the project contract; included documents receive the owner's snapshot and never infer policy.

| Surface | Lives at (per repo) | Carries |
|---|---|---|
| **Values** | `.agents/project.json` | Tracker, branches, verify commands, doc paths, naming, deploy adapter — every binding the skills resolve. See the per-skill "Keys used" lines. |
| **Prose hints** | paths in `bindings.paths.hints` | Project-specific prose the generic skills receive from the retained snapshot. |
| **Domain language** | `docs/CONTEXT-MAP.md` + `docs/areas/<area>/CONTEXT.md` | The map is an index (≤150 lines): areas, term → area table, `governs:` globs (root-relative). Area files are budgeted glossaries. Format: `skills/grill-with-docs/CONTEXT-FORMAT.md`; linter: `~/.agents/bin/context-map-lint`. |
| **Decisions** | `docs/areas/<slug>/adr/` — every area's own, including the reserved `system` area for decisions no single area owns | 1–3 sentence records, gated on hard-to-reverse AND surprising AND real-trade-off. Ids are `ADR-<slug>-NNN`, numbered per directory from `001`; no global sequence. Format: `skills/grill-with-docs/ADR-FORMAT.md`. |
| **Standards, Layer 2** | `docs/standards/` + ≤40-line README index with `governs:` globs | Project deltas only. Layers 0–1 are machine-global: `~/.agents/standards/the-bar.md` (universal) and `~/.agents/standards/stacks/*.md` (per-stack trap libraries) — a new project inherits both for free. Precedence: direct instruction > project > stack > bar > convention. |
| **Rejection KB** | paths in `bindings.paths.rejections` | One file per consciously-rejected direction; `to-issues` checks it before proposing slices. |
| **Decision maps** (optional) | tracker issues labelled `wayfinder:*`; no tracker → `.claude/wayfind/<effort>/` | Big fuzzy efforts charted by the `wayfind` skill; `from-issue --auto`'s fog gate emits decision tickets into them. The markdown fallback lives under `.claude/` because the docs root is reserved (see the linter's layout rules). |

## The `bindings.paths.hints` binding

`bindings.paths.hints` in the retained snapshot names the prose-hints files:

- Each path is explicit and is read only by the consuming phase; an empty list
  means that phase receives no hints.

Hints are read **only by the consuming agent at the moment of use** — never loaded into an
orchestrator context.

## Onboarding a new project

1. Copy a sibling project's `.agents/project.json`, edit the values, and use
   `resolve-project write-projections` to generate its entries.
2. Write the map skeleton: `docs/CONTEXT-MAP.md` with one area (or run a `grill-with-docs` session
   and let the first terms create it).
3. Optionally seed `docs/standards/README.md` (empty index) and `.claude/hints/`.
4. Everything else is machine-global via nix (`home/common/agent-skills/`): the skills, the
   standards layers 0–1, and the linter arrive with the home-manager generation.

## Host adapter accommodations

The skills are agent-agnostic by
[#64](https://github.com/fagenorn/nix-config/issues/64): a native adapter translates host
mechanics only, and anything that adds a capability one host has and another does not is a
native extension needing irreducibility evidence. Where two hosts enforce the same semantics
differently, the accommodation is recorded here — one entry per divergence, with the evidence
that forced it and the argument for why it is adapter-tier.

### Shipping authorization — `ship-issue`

*Recorded 2026-09-02,
[#119](https://github.com/fagenorn/nix-config/issues/119).*

The semantics are one sentence and hold on every host: **shipping needs authorization for
irreversible egress.** Only the translation differs.

- **Claude** runs a deterministic `PreToolUse` permission guard that validates the exact
  spellings of `git push`, `gh pr create` and `gh pr merge` against the live repository and
  allows them. The chain runs unattended.
- **Codex** has no such layer. Its built-in risk reviewer adjudicates intent, and the only
  inputs it honours are literal human messages and repository guidance — never skill prose. No
  wording in `ship-issue` can make it allow those verbs.

**Evidence.** Over two weeks the Codex host denied these verbs 129 times, peaking at 57 in a
single day. Every affected ship completed only because a human pushed or merged by hand. In
between, sessions retried the denied command, fell back to read-only checks, and stalled —
because the contract asserted the chain needed no re-prompt and the host disagreed.

**Accommodation.** `ship-issue`'s `## Standing authorization` states the no-re-prompt claim per
enforcement model rather than unconditionally, and the review-adjudicated path takes the
consolidated operator gate in `skills/ship-issue/HUMAN-GATE.md`: present the literal commands,
wait for the human's own message, resume in place. It reuses the existing
`blocked_on=human_gate` suspension rather than defining a new pause.

**Why this is adapter-tier and not a native extension.** The semantics are unchanged and
host-neutral; no capability, verb, artifact or behaviour is added that only one host has, and a
Claude session can express the operator gate too — it simply never needs to. #64's
irreducibility evidence is therefore not required.

## Vendored skills

A directory under `skills/` may be a **vendored adaptation** of an upstream skill rather than an
authored one. Such a directory carries the upstream `LICENSE` inside it as its provenance record: the
upstream URL, the pinned revision, the date it was inspected, and every way the adaptation departs
from upstream, followed by the upstream notice reproduced unmodified. Keeping the notice in that file
and out of `SKILL.md` keeps it out of the body that loads with the skill, while `SKILL.md` still
links to it so the provenance is one hop away.

Nothing fetches or refreshes these at build time — there is no flake input for the upstream and no
synchronisation. A refresh is a manual comparison against a newer revision: re-apply the recorded
adaptations by hand and move the pin. The contract suite in `tests/` pins each adaptation, so a
careless refresh fails a test rather than silently reverting one.

## Global guidance and skill sources

`~/.codex/skills/` is Codex's own runtime state: Nix's only writes under `~/.codex/` are `AGENTS.md` and the `model_reasoning_effort` key spliced into `config.toml`, so it neither populates nor prunes that directory — a skill hand-copied there duplicates the managed `~/.agents/skills/` link of the same name and has to be removed by hand.

## Impeccable

Impeccable (`pbakaus/impeccable`) is pinned by the `impeccable` flake input to an immutable `skill-v<version>` tag. `lib/impeccable.nix` builds it once into one derived skill tree. The tree is upstream's `.claude/skills/impeccable` unchanged, plus the host system's pinned prebuilt design-detector engine in the launcher's sibling slot `scripts/bin/<os>-<arch>/impeccable`. Both agents get that tree: Codex through the whole-directory link `~/.agents/skills/impeccable`, and Claude through a recursive `~/.claude/skills/impeccable`. `~/.agents/bin/impeccable` puts the detector on PATH by exec'ing the tree's own launcher. Detector availability is that pinned engine. It is never downloaded on demand, and nothing is installed under `~/.impeccable/bin/`, although the engine may still write runtime caches under `~/.impeccable`. The session sets `IMPECCABLE_NO_UPDATE_CHECK=1` because Nix owns the version. For the same reason, the store-writing verbs (`update`, `install`, `link`, `pin`) cannot change the Nix-owned tree. A bump edits the input's tag, the engine version and both hashes in `lib/impeccable.nix` together. Evaluation fails when the engine version and the tree's `scripts/VERSION` disagree, and on any system other than `aarch64-darwin` or `x86_64-linux`.

## Retired skills

Skills that are no longer installed are listed in `retiredSkillNames` in `home/common/agent-skills/default.nix`. Home Manager's own cleanup removes their old links on switch, and an activation step then warns about any retired skill directory that is still present, without deleting anything.

## Claude-only skills and the Codex stub

Two skills stay out of the shared tree and are linked only into `~/.claude/skills/` from `home/common/claude-code/skills/`: `codex-collaboration`, because a Codex session able to load the Claude→Codex bridge would recursively delegate to itself, and `orchestrate-issues`, because it fans issues out to background agents and correlates host task notifications — Claude-harness features Codex lacks, so a Codex session runs `/from-issue` per issue instead. Codex gets its own `orchestrate-issues`: a stub in `home/common/codex/skills/`, linked by the Codex module as the whole directory `~/.agents/skills/orchestrate-issues`, that relays `workflow-state host-route --route codex` (declared unsupported) and names `/from-issue <n> --auto` per issue.

## .superpowers paths and launch-fenced writers

The `.superpowers/` paths throughout `home/common/agent-skills/` are pipeline state and artifact locations that share a historical name, each with its own home, and none of them is rooted at the process cwd: the lifecycle ledger under the repository root a caller supplies explicitly, per-plan `sdd` task artifacts beneath the primary checkout in a per-checkout bucket (`primary/` or `wt-<worktree-name>/`, so two checkouts executing the same plan can never share a ledger — though two *attempts* on one issue do share a checkout, because the lifecycle hands a retry the predecessor's worktree and branch on purpose: that sharing is what lets a successor resume the task ledger seamlessly, and it is why a still-running predecessor must re-validate its launch identity with `workflow-state check-launch` before any forge write), and delivery detail beneath the primary checkout. A shared checkout is also why writers are launch-fenced (#222): every agent an owner dispatches that can commit is registered in the ledger's `workers` list (added in schema 5) through `workflow-state register-worker`. Such an agent commits only through the `launch-commit` command, which runs `git commit` only while `workflow-state check-worker` reads that worker as live. An owner's own `suspend`, `finish`, handoff `progress` or suspending `checkpoint-delivery` is refused while a registered worker of its launch is live. The one deliberate worktree-local path is `ship-issue`'s retained Minor/Discussion candidate, whose lifetime is meant to end with the worktree. Producer-report candidates are not written into a working tree at all — they are `mktemp` files under `$TMPDIR`, removed by an unconditional cleanup — and no lifecycle call writes an input file: each one feeds its request, checkpoint, summary or builder input to `workflow-state` on stdin (`-`) through a quoted heredoc, optionally piped through `artifact-budget validate-report --input -`. The tracked `.gitignore` is the backstop for every one of those shapes; `.git/info/exclude` is machine-local and cannot be. The `.superpowers` name is historical; there is no Superpowers input, patch, marketplace or plugin in this repo.

## Lifecycle helpers

### workflow-state build-delivery

Delivery objects are built, never hand-composed: `workflow-state build-delivery --repo-root <ledger_repo_root> --kind <kind> --input <absolute-path|->` derives the `delivery-contract/v1` and its initial authorization intent from the `resolve-project` policy at `--repo-root` (the ledger repository root, the only policy it seals; when the input worktree already exists it resolves there too and refuses if any sealed member differs; when the worktree's name is not an issue branch, the contract takes the branch checked out there, so a legacy slugless worktree keeps its recorded path), and seals each stage's scope, the reviewed selection and each sync selection that extends it after a post-review sync of the integration branch, every delivery observation, each authority observation an owner submits and the ship handoff's authorization-chain digest, so no agent composes a digest. `build-delivery` is read-only — no lock or write; it reads the clock only for a `--kind contract` input's `now`, to stamp an omitted one and to skew-check a supplied one. A contract it cannot re-derive is served only when a ledger under `--repo-root` has installed it, and then against that ledger's stored initial intent; `--kind current-selection` serves the current selection of the contract's reviewed slot from the one ledger that installed it; those are the only times it reads a ledger. `build-delivery` refuses anything else it cannot derive with exit 2 and empty stdout; when `resolve-project` refuses, the one stderr line carries the resolver's error document unchanged.

### Host admission

Orchestration admission is declared, not measured: `home/common/agent-skills/host-declaration.json` (installed as `~/.agents/share/host-declaration.json`, validated by `agent_tools.host_admission`) gives each orchestration route its support and, for a supported route, its `agent_slots` — the concurrent agents one root session may run: the controller plus each owner's owner, worker and reviewer. `workflow-state control` claims an owner's whole role set against that budget before dispatching it, `workflow-state host-route` returns the typed supported/unsupported answer, and the conformance check `host.admission.declaration` reports the declaration. Host admission is no CPU, memory or build-load figure (`.agents/knowledge/rejections/host-contention-scheduling.md`).

### Anti-zombie bound and progress markers

The anti-zombie bound counts progress, not phase changes: an attempt is stopped as `stopped(stalled)` on its fourth consecutive suspension with neither a phase advance nor a newly recorded progress marker. `workflow-state mark-progress --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` records the marker for the current launch of an active attempt: the helper itself reads the commit checked out in the attempt's recorded worktree and stores it as the attempt's `progress_marker` (ledger schema 6; `null` until first recorded). The first recording is a `baseline` and resets nothing; a commit that strictly descends from the stored marker is `advanced` and starts a fresh stall count; the same commit (`unchanged`) and a commit that does not descend from it (`diverged`) write nothing; a launch that is not current, a remainder launch, and a worktree git cannot read are refused. `sdd` records a marker before its first task of a session and after each completed task, so a long Phase 6 that suspends between tasks is not discarded.

### Run identity and migrate

Every run's identity is a core `rel_` UUIDv7 run transaction (#337, [design](../../../.agents/artifacts/specs/2026-10-09-issue-337-attempt-identity-migration-design.md)): `workflow-state init-run --creation-key <key>` and `direct-owner` mint new runs named by that id, while `init-run --run-id` only re-bootstraps a run that exists. Schema-8 ledgers carry `transaction_id`; a schema <= 7 ledger in one of the four legacy dialects is bound on its next locked write, or by `workflow-state migrate --repo-root <repo> --apply` after the read-only dry run that `migrate` without `--apply` is, and keeps its legacy id as its handle. A refusal (`unknown_schema`, `invalid_state`, `unknown_dialect`, `ambiguous_lineage`, `location_mismatch`) leaves the ledger's bytes untouched and is reported as data with exit 0 (exit 2 is usage, an unreadable workflows directory or a store fault). A helper from before schema 8 refuses a migrated ledger and there is no reverse migration, so rollback means redeploying a schema-8 reader (D10). `agent_tools.attempt_identity` holds the grammar, plan and report and `agent_tools.attempt_store` the store, binding and `migrate` rows (D27); installed `workflow-state` runs under the agent_tools interpreter with `-I`, the same environment as the other launchers (D16).

### Resume pack

A relaunched owner's prompt carries a resume pack: `workflow-state resume-pack --repo-root <ledger_repo_root> --run-id <run-id> --action-id <action_id>` is read-only (no lock, clock or write) and prints one `resume_pack` version-1 object derived from the ledger, the attempt's recorded worktree (branch, HEAD, the count of uncommitted entries, commits since its `progress_marker`) and that worktree's SDD workspace, ending in a closed `next_action` (`read_handoff`, `reorient`, `resume_task`, `finish_phase` or `start_phase`). `resume-pack` is served for the current launch of an active attempt and as a `current: false` preview for the last launch of a suspended or handed-off latest attempt; anything else exits 2. orchestrate-issues §4 adds it to `resume` prompts, and from-issue to direct re-entry, `delegate` and the Phase-5 rollover; the pack is not a workflow response and is never piped through `validate-report`; the relaunched owner still runs `check-launch`, checks the pack's HEAD and dirtiness, and then reads only the skill sections every owner obeys plus the current phase's, while sdd's own `progress.md` check still decides the task to resume (#265).
