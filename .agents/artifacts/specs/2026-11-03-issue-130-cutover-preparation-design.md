# Prepare the Stage-4 strict cutover — issue 130

Design for https://github.com/fagenorn/nix-config/issues/130, written autonomously (`from-issue --auto`)
after the 2026-11-03 Phase-0 note. The owner's comment of 2026-11-03 narrows this attempt to
preparation: assemble the cutover checklist from current registry truth with fresh evidence for every
item, fix or file anything red, and stop at a human gate with the checklist and the exact activation
command. Arcwave is in the cutover. The fleet-wide activation, `just switch`, the rollback exercise
and bridge retirement are not authorised. Every call made without the owner is a row of the Decision
ledger; "Dn" cites that ledger, "#71" and the like cite the decision tickets.

## Triage

```
Input: {"signals": {"contract_change": {"value": "doubt", "evidence": "the checklist is a new committed artifact; red-item fixes may touch conformance or resolver contracts"}, "concurrency_or_persistence": {"value": "hit", "evidence": "legacy workflow ledgers across five fleet roots are persisted state the checklist must classify"}, "open_design_questions": {"value": "hit", "evidence": "checklist shape, roster derivation, red-item dispositions and the activation command are open"}, "criteria_shape": {"value": "hit", "evidence": "the issue carries ten acceptance criteria, several human-verified"}}, "paths": [".agents/artifacts/specs/2026-11-03-issue-130-cutover-preparation-design.md", ".agents/artifacts/plans/2026-11-03-issue-130-cutover-preparation.md", ".agents/artifacts/evidence/cutover-130-checklist.md"]}
Verdict: {"hits":["contract_change","concurrency_or_persistence","open_design_questions","criteria_shape"],"lane":"full","mode":"shadow"}
ran: full (shadow)
```

## Problem

Stage 4 of the project-system rollout (#71) is one fleet-wide Nix activation that deletes every static
fallback ladder the additive bridge kept alive, followed by bridge retirement once the strict
predicates are green. #71 and the issue make that activation conditional on a set of predicates, each
verified fresh rather than inherited, and #71 requires a person to confirm them. Today nothing
records whether those predicates hold:

- No cutover checklist exists. The predicates are spread over the issue body, its 2026-09-19 refresh,
  #71's Stage 4 and retirement sections, #66's deprecation and removal rules, #90's legacy-release
  block and #128's deferral of its live paired trials (AC5) to this issue.
- The fleet changed since the issue was written. The issue names three projects. The mbp fleet
  registry lists five (Arcwave, Argus, nix-config, JarBird, Nodo as `nodocom`). eleven-m5's registry
  lists JarBird only, and anis-desktop is offline.
- Phase-0 observations already show red predicates. Nodo's doctor fails. Hundreds of legacy ledgers
  across the fleet roots still need migration, and some are refused. The platform manifest
  declares no deprecation. Two fleet projects still use the legacy `.claude/skills.config.json` and
  two use the free-form `bindings.deploy` that the cutover retires. No strict-cutover candidate or
  approved #70 bundle exists.

The owner needs one document that tells them, item by item and with evidence they can re-run, what
stands between the fleet and the activation. Every red item needs a named route to green, and the
exact commands for the activation and its rollback must be ready when the items turn green.

## Solution

1. **The cutover checklist** (section 1): one committed Markdown artifact,
   `.agents/artifacts/evidence/cutover-130-checklist.md`, holding the roster, one item per predicate,
   per-row evidence, a disposition for every red row, the human gate's command text and a map from the
   issue's criteria to the items.
2. **The roster** (section 2) is derived at evidence time. The hosts are the flake's outputs, and the
   projects come from each host's fleet registry. Arcwave is in by the owner's decision, JarBird by
   registry truth, and "Nodo" is `nodocom`.
3. **Twelve pre-activation items and six post-activation items** (section 3), each with read-only
   evidence commands that already exist and a mechanical verdict rule.
4. **Dispositions** (section 4): a red row is fixed in this attempt only under a narrow rule, and is
   otherwise covered by exactly one tracker issue per distinct repair route. Before filing, the open
   issues are searched (#554 and #555 already exist).
5. **The human gate** (section 5): the migration, re-run, freeze, activation, verification and
   rollback command text, with every value known at evidence time bound and the
   candidate commit as the one named parameter.
6. **Delivery** (section 6): a docs-only PR holding the spec, the plan and the checklist. #130 stays
   open at the human gate, and its own criteria are recorded as unmet or human-pending.

## Decisions

Terms used below. The **bridge generation** is a host's active pre-cutover Nix generation, which is
the rollback anchor. The **bridge paths** are the deprecated compatibility code the candidate deletes:
the legacy file's writer, `release_bridge`, `release deploy inspect` and `bindings.deploy`. The
**candidate** is the strict platform build F1 produces. A **legacy ledger** is one whose
`workflow-state migrate` dry-run verdict is not `current`, and a **legacy attempt** is an attempt
recorded in a legacy ledger.

### 1. The checklist artifact (per D3, D4, D5)

One Markdown file at `.agents/artifacts/evidence/cutover-130-checklist.md`, in this order:

1. **Header**: purpose, the attempt's run id, the evidence window (first and last UTC timestamp), the
   nix-config revision the evidence was taken at, the hosts, and the activation-readiness statement.
   That statement reads "activation not permitted" while any pre-activation item is red or
   human-pending, and gives the counts.
2. **Summary**: one table row per item: `ID | Predicate | Source | Phase (pre/post) | Verdict |
   Disposition`.
3. **Roster** (section 2).
4. **Evidence**: one subsection per item. Each holds the predicate quoted from its source, its
   commands in a fenced block, each labelled (`C10.a`), and a rows table: `Host | Subject | Revision |
   Command | UTC | Exit | Observed | Verdict`. "Subject" is the root, host or artifact the row
   observes. "Revision" is the subject's commit (`git -C R rev-parse HEAD`, its branch and the count
   of `git -C R status --porcelain` entries) for a project row, or the host's active system
   generation for a host row. "Observed" is a bounded verbatim excerpt of the verdict-bearing fields, at most about 200 characters. A list that does not
   fit, such as refused ledgers or unmapped worktrees, is counted in the row and listed in full in
   the filed issue.
5. **Dispositions**: `Rows | Repair route | Disposition (fix commit or issue)`.
6. **Human gate** (section 5).
7. **Criteria map**: each acceptance criterion of the issue and its refresh, mapped to the items
   that evidence it.

Raw command output stays in the attempt's launch scratch and is not committed. The checklist is the
record, and re-running the commands is how anyone checks it.

### 2. The roster (per D2)

- **Hosts**: the attribute names of the flake's `darwinConfigurations` and `nixosConfigurations` at the
  evidence revision: today `mbp`, `eleven-m5` and `anis-desktop`. Each host receives the activation,
  so each is in the roster.
- **Projects**: on each host, the entries of `~/.agents/state/fleet/registry.json`. The roster is the
  set of `(host, project_id, root)` triples. A project registered on two hosts, like JarBird on mbp
  and eleven-m5, has two roots and is evidenced on both.
- **Inclusion**: every registered project is in. Arcwave is explicitly in: the owner's 2026-11-03
  comment is cited, and the row records its `branch_override` (`dev`, `default_contract_unresolved`).
  Nodo (`nodocom`) carries the same override. Registration through that override is the designed #363
  path, so the checklist records it as a fact. It does not make the row red.
- **Host identity**: each host row records the active system generation (`system-N-link` and its store
  path), `platform_version` and `manifest_path` from `resolve-project platform-status`, and the
  nix-config checkout found on the host (`K_H`, a clone whose `origin` is `fagenorn/nix-config`). When
  a host has several, the row names the one the gate uses and lists the others. Hosts
  may run different bridge builds; eleven-m5's generation differs from mbp's today. #66 says store
  paths and generation numbers are not portable compatibility versions, so a difference is recorded
  and is not red. Compatibility is judged by `platform_version` against each contract's interval.
- **Unreachable host**: a host whose registry cannot be read is `human-pending` on every item that
  needs it. It is never green and never dropped. Excluding a configured host is the owner's call.

### 3. The items (per D4, D6, D9, D10, D11)

`H` is a roster host and `R` a root on it. Rows for a remote host run as `ssh H -- <argv>`. Every
command is read-only: none carries `--apply`, `--register`, `switch`, a write or a fetch into a fleet
root. The evidence run creates no worktree in a roster root, so it cannot disturb C7. The verdict
reads the command's answer, never its exit code: `adopt-project verify` exits 0 on `not_conformant`,
and `ls` exits non-zero on a green `absent`.

**Pre-activation items**

| ID | Predicate (source) | Evidence | Verdict rule |
|----|--------------------|----------|--------------|
| C1 | The roster is derived from current registry truth, with the Arcwave decision recorded (refresh) | `nix eval --json .#darwinConfigurations --apply builtins.attrNames` and the same for `nixosConfigurations`, run in the delivery worktree; per H `cat ~/.agents/state/fleet/registry.json` | green when every host's registry was read; human-pending for an unreachable host |
| C2 | Every roster project is registered and compatible, and its adoption evidence is still current (issue; #71) | per H `resolve-project platform-status --fleet` (each row `compatible: true`) and `conformance run --purpose fleet` (outcome `passed`); per (H,R) `adopt-project verify --repo-root R` | red on any incompatible row, a fleet outcome other than `passed`, or verify result `not_conformant`. `adopted` is green. `adopted_with_blockers` is green with its blockers listed: #71 lets optional host readiness stay blocked only through that state |
| C3 | A fresh `approved` #70 bundle covers the strict-cutover candidate as a whole (issue; #71; #128 AC5) | every `*-bundle.json` under `.agents/artifacts/evidence/` at `origin/main`, read for `state` and `identity.bound.commit.candidate` | green only for a bundle with `state: approved` that binds the commit C4 names as the candidate; otherwise red |
| C4 | Candidate and retained-bridge fleet preflight are green for every registered project (#71) | bridge side: the C2 fleet rows, cited; candidate side: `git show origin/main:home/common/agent-skills/platform-manifest.json` and the C2 intervals | red while no candidate exists: the manifest says `1.0.0`, and every interval excludes `2.0.0`, the strict major #66 requires |
| C5 | No legacy release is in flight (#90) | per (H,R) `ls -la R/.superpowers/workflows/ship-release/state.json`; if it is present, `release transaction status --repo-root R` for its `legacy.class` | green when absent (`classify` is `absent` exactly when the path is missing) or `completed`; red when `in_flight` or `unreadable`, or when a file is present and the project cannot classify it because its release capability is unsupported |
| C6 | No legacy attempt is left without a resumable strict-path mapping (issue; refresh) | per (H,R) `workflow-state migrate --repo-root R` (the dry run) | red when `counts.refused > 0`; otherwise human-pending when `counts.migrate > 0`, cleared by the owner's gate step 1; green when every ledger is `current` |
| C7 | No retained legacy worktree is left without a resumable mapping (refresh) | per (H,R) `git -C R worktree list --porcelain`; each linked worktree's path, as listed and as its realpath, is searched as a fixed string in `R/.superpowers/workflows/*/state.json` | each linked worktree is classed by the ledgers its path occurs in. Red when any is unmapped (in no ledger, including one whose ledger was archived or a scratch or hand-made worktree, which the owner classifies in F7) or mapped only to refused ledgers. Otherwise human-pending when any maps only through `migrate` ledgers. Green when every one maps to a `current` ledger |
| C8 | The Codex ship handoff is in place (issue; #119) | per H `ls -lL ~/.agents/skills/ship-issue/HUMAN-GATE.md` and `grep -n 'HUMAN-GATE.md' ~/.agents/skills/ship-issue/SKILL.md`; the source revision from `git log -1 --format=%H -- home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md` | green when the gate file is installed in the tree Codex reads and wired from the skill on every host |
| C9 | Claude and Codex paths answer as their declared host capabilities say, including bounded admission (refresh) | per H `workflow-state host-route --route claude-code` and `--route codex`; the `host.admission.declaration` check status from the C10 rows | green when each route answers per the installed declaration: `claude-code` supported with its slots, and `codex` `declared_unsupported` with the alternative `/from-issue <issue> --auto`; red on `declaration_missing`, `declaration_invalid` or `route_undeclared` |
| C10 | `doctor` is clean on every adopted host (issue) | per (H,R) `conformance run --purpose doctor --repo-root R` | outcome `passed` is green, with warnings listed; `failed` is red with its primary check, its repair id and the count of checks it suppressed (#69 suppresses dependants, so a repair can expose more); `incomplete` is rerun online once and stays red if it repeats |
| C11 | Deprecation notices shipped in a bridge minor, and the fleet has zero users of the deprecated paths (issue; #66) | per H `resolve-project platform-status` for `platform.deprecations`; per (H,R) `git -C R ls-files -- .claude/skills.config.json`, `resolve-project resolve --repo-root R` for `bindings.deploy.adapter`, and `git -C R grep -n -F 'release deploy inspect' -- . ':!.agents/artifacts'`. For nix-config the pathspec is `home/common/agent-skills/skills`, because its implementation and tests are what the candidate deletes | red when `deprecations` is empty, since the candidate removes the legacy file, its writer, `bindings.deploy` and `release deploy inspect` (124 and 128 specs). Red for each root with a tracked legacy file, a `bindings.deploy.adapter` other than `none`, or a hit. Point-in-time records are not users |
| C12 | The bridge generation is identified per host and can be retained (issue; #66) | per H `hostname`, `readlink /nix/var/nix/profiles/system`, `readlink /nix/var/nix/profiles/system-N-link` and `readlink /run/current-system` | green when the current profile generation is the running system and `hostname` equals the host's flake attribute; records `N_H` |

**Post-activation items.** These are listed so the gate is complete. Each is `human-pending`, phase
`post`, and none is evaluated in this attempt.

| ID | Predicate (source) | Evidence when evaluated |
|----|--------------------|-------------------------|
| P1 | No static fallback ladder remains in the resolver, conformance or workflow-entry paths of any adopted project, and a missing contract fails closed with a closed error code (AC2; #69) | `resolve-project resolve --repo-root <a scratch git repository with no contract>` returns a closed `error.code`; the ladder-absence check is delivered with the candidate (F1) |
| P2 | The bridge generation is retained, and rollback to it is exercised once before retirement (AC3; refresh) | the gate's rollback block run on each host, then the C12 rows re-observed and re-activation |
| P3 | A Claude-driven and a Codex-driven ship complete on the strict path, against declared host capabilities with bounded admission (AC4; refresh) | owner-run sessions: the merged PR, the closed issue and the run ledger outcome, plus the C9 commands |
| P4 | The #71 retirement predicates: the active generation's identity matches its manifest; active and bridge fleet conformance are green; `workflow_entry` passes through both adapters; post-activation smoke is green; doctor reports no residue; traces show zero removed-fallback executions | the C2, C10 and C12 commands on the strict generation, and the trace check delivered with F1 |
| P5 | Implementation delivered, PR merged, tracker closed and cleanup postconditions reconciled before retirement (refresh) | `gh pr view`, `gh issue view`, the delivery state in the run ledger, and `git worktree list` |
| P6 | Retirement is recorded with the evidence that satisfied each strict predicate (AC5) | a retirement section appended to this checklist |

### 4. Dispositions (per D7, D8)

A red row gets exactly one disposition:

- **Fixed in this attempt** only when all four hold. The fix is in nix-config's tracked tree. It is
  small: one bounded change that the declared verification covers. Its effect can be re-observed
  without any activation: the predicate reads repository state, not the installed generation. It is
  not part of the cutover itself: it deletes no ladder and changes no platform or schema version. The
  row is then re-observed green and cites the fix commit.
- **Filed** otherwise: one tracker issue in `fagenorn/nix-config` per distinct repair route, meaning a
  distinct owner and action. Rows sharing a route share the issue. The open issues are searched
  first, and an existing issue is cited instead of filing a duplicate. Each filed issue carries the
  red rows' evidence in full and links back to #130 and the checklist.
- **Human-pending** is not a disposition of a red row. It is the verdict of a row that needs only an
  owner action: an unreachable host, owner-run trials, the owner's `migrate --apply`, or the
  activation.

The filings expected from the Phase-0 observations are below. The execution derives the actual set
from its own fresh evidence: a row that turns out green files nothing, and a new red route adds an
issue.

| Ref | Repair route | Covers |
|-----|--------------|--------|
| F1 | Build the strict-cutover candidate on an unmerged branch. It is platform `2.0.0`: it deletes the bridge paths, retiring `bindings.deploy` through a project-schema migration, and the workflow-entry residues of the fallback inventory, adds candidate-and-bridge fleet preflight, delivers the ladder-absence and trace checks, and lands each fleet project's migration commit admitting the bridge and the candidate (#66) | C3 (the candidate it binds), C4, P1, P4 |
| F2 | Ship a bridge minor that declares the deprecations of every path F1 removes, with successor and migration ids | C11 (deprecations) |
| F3 | Arcwave: retire its tracked legacy `.claude/skills.config.json` and the script that reads it, and its references to the removed `resolve-bindings` | C11 (Arcwave) |
| F4 | Nodo: move the railway deploy off `bindings.deploy` and the legacy file. This needs a railway activation unit in the release core, which no issue covers | C11 (Nodo) |
| #555 | JarBird's `github-actions-health` deploy, cited, not filed | C11 (JarBird) |
| F5 | Nodo: repair the overbroad ignore rule (`repository.ignore.runtime_sentinel`, repair `lifecycle.ignore.repair`) | C10 (Nodo) |
| F6 | Dispose of the fleet legacy ledgers that `workflow-state migrate` refuses (each classified, then migrated, archived or abandoned under #72's acknowledged cleanup) | C6 refused rows |
| F7 | Reconcile retained worktrees that have no resumable mapping (each classified, then removed under #72's acknowledged cleanup or attached to a resumable attempt) | C7 red rows |

C3's other blocker, the live paired Claude and Codex trials, are owner-run (#128 D11) and stay on
#130's gate. They are not filed: they cannot start before F1 exists, and the #128 owner placed them
here.

### 5. The human gate (per D12)

The checklist's gate section holds the following text. `K_H`, `N_H` and the roots are the values the
evidence observed, filled in. `<candidate>` is the one parameter: the 40-hex commit of F1's candidate
that C3's approved bundle binds. The section says that `N_H` must be re-read in step 2, because any
switch before the activation moves it. The steps run in order, and the owner runs every one.

**1. Migrate the ledgers (under the bridge generation).** For every roster root `R` on host `H`:

```
workflow-state migrate --repo-root R           # must report "refused": 0
workflow-state migrate --repo-root R --apply
```

The bridge's helper already reads and writes the migrated schema (schema 11), so a later rollback to
the bridge generation needs no reverse migration. A refused ledger stops the gate here: C6 is red.

**2. Re-run the checklist.** On every host, re-run every pre-activation item's commands. Every verdict
must be green. Any changed or red verdict rewinds the stage (#71): the candidate is regenerated, never
patched around. Record `N_H` from `readlink /nix/var/nix/profiles/system`.

**3. Freeze.** From step 2 until retirement is recorded, on every host, run no `just gc`, no
`nix-collect-garbage`, no system-generation deletion and no `just switch` other than step 4's.

**4. Activation (every host in one session, host by host).** The approved bundle must bind
`<candidate>`. On each host `H`:

```
git -C K_H fetch origin
git -C K_H worktree add --detach K_H/.worktrees/cutover-130 <candidate>
cd K_H/.worktrees/cutover-130 && just switch
git -C K_H worktree remove K_H/.worktrees/cutover-130
```

`just switch` is the contract's `nix-activate` command, run from the candidate checkout's root. The new
system generation roots the build, so the worktree is removed and leaves no residue for C7. If any
host fails to activate, roll back every host already activated, because #71 forbids a mixed live
fleet.

**5. Post-activation verification.** On each host, run `resolve-project platform-status --fleet`
(`platform_version` is the candidate's, every row compatible) and `conformance run --purpose fleet`.
Per root, run `conformance run --purpose doctor --repo-root R`. Then evaluate P1–P5.

**6. Rollback (per host, to the bridge generation).**

```
# darwin hosts (mbp, eleven-m5)
sudo /nix/var/nix/profiles/system-N_H-link/sw/bin/darwin-rebuild --switch-generation N_H
# NixOS host (anis-desktop)
sudo nix-env --profile /nix/var/nix/profiles/system --switch-generation N_H
sudo /nix/var/nix/profiles/system/bin/switch-to-configuration switch
```

After rollback, re-run C12 to show the bridge generation is running again.

### 6. Acceptance for this attempt and delivery (per D1, D13)

This attempt is accepted when:

1. `.agents/artifacts/evidence/cutover-130-checklist.md` is committed with the roster and items
   C1–C12 and P1–P6. Every pre-activation row was observed by this attempt's own command run and
   records its command, host, revision, UTC time, exit and observed excerpt.
2. Every red row has a disposition: a fix commit with the row re-observed green, or a cited issue.
   No red row is left without one, and no issue duplicates an open one.
3. The gate section holds steps 1–6 with every value known at evidence time bound, and
   `<candidate>` as the only parameter.
4. The attempt ran only the read-only commands of section 3 against fleet roots and hosts. It made no
   switch, no `migrate --apply`, no registry write and no commit in any fleet repository. Each fleet
   root's HEAD and each host's registry bytes are recorded before the evidence run and after it, and
   any difference is reported with its cause. Other runs may legitimately move a root meanwhile.
5. Every verdict comes from the attempt's last full run of the commands. The filings are made from
   that run's red rows, so no filed issue rests on an earlier observation.

Delivery is a docs-only PR holding the spec, the plan and the checklist. #130 stays open with
`agent:human-required`. Its gate comment links the checklist's gate section at the merged commit
and lists the filed issues. The acceptance record marks each of the issue's own criteria from its
items: met only when every mapped item is green, `human_pending` when the remaining items wait on
the owner or the activation, and unmet otherwise. AC1 and the refresh's legacy-attempt criterion are
expected to be unmet.

Re-entry: once the filings close, a new attempt on #130 re-runs the whole checklist (D5). It inherits
no verdict from this one. Activation stays the owner's step 4, after an all-green step 2.

## Test seams

This delivery adds no code, so it adds no test. Its proof is evidence taken at the existing operator
boundaries:

- **The installed commands, run as an operator runs them**: `resolve-project platform-status` and
  `resolve`, `conformance run` (`fleet`, `doctor`), `adopt-project verify`, `workflow-state migrate`
  (the dry run) and `host-route`, `release transaction status`, with git, `ls`, `readlink` and `ssh`
  as the only other primitives. Each command's own suite already pins its answer: the resolver,
  conformance, adoption-verify, host-admission and release-driver tests.
- **The repository the checklist lands in**: `conformance run --purpose doctor` and
  `adopt-project verify` on the delivery worktree stay `passed` and `adopted` with the new Markdown
  file under `.agents/artifacts/evidence/`. Only a `.json` file directly in that directory counts as
  an adoption-evidence candidate.
- **Declared verification**: `nix-build` (`just build`). `agent-workflow-tests` also runs, because
  `.agents/artifacts/evidence/*` is in its `when_changed` set.

Prior art: the 129 evidence record (`.agents/artifacts/plans/2026-11-03-issue-129-argus-adoption.evidence.md`)
for per-row evidence tables, and the #127 and #128 bundles under `.agents/artifacts/evidence/`.

## Out of scope

- The fleet-wide activation, `just switch` on any host, the rollback exercise and bridge retirement.
- Building, merging or evaluating the strict-cutover candidate. Deleting any ladder, changing the
  platform manifest, the platform or schema version, or any contract interval (F1, F2).
- `workflow-state migrate --apply`, `adopt-project verify --register`, reaping or removing any
  worktree or ledger, and any commit, branch or file change in Arcwave, Argus, JarBird or Nodo.
- Running the #70 live paired trials or authoring trial or cost records (#70 forbids hand-authored
  records).
- Bringing anis-desktop online, or deciding to drop a configured host from the fleet.
- New tooling: a checklist runner, a `strict_predicates` module or a candidate-preflight command (D6).
- Changing the host declaration (Codex stays `unsupported` as declared).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | This attempt prepares only: it commits the checklist, files the red routes and writes the gate text. It builds no strict candidate and runs no activation, switch, `migrate --apply`, rollback, retirement or trials. #130 stays open at the human gate | Owner comment 2026-11-03 ("preparation only", activation, rollback and retirement not authorised); #71 (one explicit activation confirmed by a person) | Building the candidate here: merging it would make the next routine `just switch` the activation, and it needs migration commits in four other repositories, which is outside this attempt's authority |
| D2 | The roster is `(host, project_id, root)` over the flake's hosts and each host's own registry. Arcwave is in by the owner's decision, JarBird by registry truth, and Nodo is `nodocom`. `branch_override` registrations count as registered. An unreachable host is human-pending, never dropped. Per-host build differences are recorded and are not red | Refresh: derive from registry truth and decide Arcwave; owner comment (Arcwave in); registries are per host (eleven-m5 lists JarBird only); #363 override design; #66 (store identities are not compatibility versions) | Freezing "all three": the refresh forbids it. Using mbp's registry alone: eleven-m5 registers its own JarBird root and receives the same activation |
| D3 | The checklist is one Markdown file at `.agents/artifacts/evidence/cutover-130-checklist.md`, with a summary, roster, per-item evidence rows, dispositions, gate and criteria map. Raw output is not committed. Later passes rewrite it in new commits, and git history is the audit trail. `agent-workflow-tests` runs because that path is watched | #127 and #128 evidence home; the Phase-0 triage path list; `is_evidence_record_path` counts only top-level `.json` files there, so a `.md` cannot pose as adoption evidence | A plan-local `.evidence.md`: the checklist outlives this plan and is re-run at the gate. A JSON twin or schema: it has no consumer (YAGNI), and a `.json` there would be read as an adoption-evidence candidate |
| D4 | Verdicts are `green`, `red` and `human-pending`. An item takes its worst row (red over human-pending over green). Evidence rules are fail-closed: they may over-report red and never under-report. A command's answer decides, never its exit code: `adopt-project verify` exits 0 on `not_conformant`, and `ls` exits non-zero on a green `absent` | the-bar "Truthful terminal states"; `verify_exit_code` returns 0 for all three results; #71 (a gap rewinds) | A `n/a` or inherited-green verdict for unobservable rows: it presents missing evidence as success |
| D5 | Freshness means every pre-activation row comes from this attempt's own read-only command run. Phase-0 notes and earlier artifacts are never evidence, only things to re-run. There is no time window: the gate re-runs everything before activation, and any changed verdict rewinds | Issue: "verified fresh, not inherited"; #71: elapsed time is never evidence; the candidate is regenerated on a gap | A freshness TTL: an arbitrary number that #71 rejects as evidence. Carrying Phase-0 counts into the checklist: inherited evidence |
| D6 | No new tooling. Every item uses an installed command or git, `ls`, `readlink` or `ssh`. The legacy-release check stats the path, and the worktree mapping is a fixed-string search of the ledger files | Caller and the-bar YAGNI; `release transaction status` refuses where the release capability is unsupported (Nodo), so the stat is the uniform check; ledger dialects vary, while a path string does not | A `cutover-checklist` runner or `strict_predicates` module: single-use, and its own new code would need the review and tests the cutover is gated on. The post-activation trace checks belong to F1 |
| D7 | A red row is fixed here only if the fix is in nix-config, small, observable without any activation and not part of the cutover. Otherwise it is filed: one issue per distinct repair route, after searching open issues. Owner-only actions are human-pending, not filed | Owner: "fix or file anything red"; the installed generation changes only on `just switch`, which is not authorised, so an installed-behaviour fix cannot be re-observed; one issue per route keeps rows that share a remedy together | Fixing across fleet repositories: not authorised. One issue per red row: Nodo alone would yield dozens of ledger issues with one remedy |
| D8 | The expected filings are F1–F7, with #555 cited for JarBird. Interval widening for the candidate major is folded into F1, and the deprecation minor (F2) is separate. The execution re-derives the set from fresh evidence | #66 choreography: deprecate in a minor, migrate users, widen intervals to admit bridge and candidate, remove in the major; 124 and 128 specs list what #130 retires; open #554 and #555 | Filing interval widening separately: its schema is not known until F1 defines the candidate. Folding F2 into F1: it is a separate, earlier release with its own activation |
| D9 | C6: a legacy attempt has a mapping when its ledger's dry-run verdict is `migrate`, and it resumes on the strict path once the owner's gate step 1 applies the migration. Refused ledgers are red whatever the state of their attempts. C7 classes each linked worktree by the ledgers naming its path: `current` is green, `migrate` only is human-pending, and refused-only or unmapped is red. Unmapped covers archived runs, scratch leaks and hand-made worktrees alike, and the owner classifies them in F7. `migrate --apply` is gate step 1, run before the step-2 re-run under the bridge generation | Refresh ("do not activate while any legacy attempt or worktree lacks a resumable strict-path mapping"); helper README: refusals leave bytes untouched, and the bridge helper writes schema 11 with no reverse migration; #69: no unclassified residue | Requiring zero non-terminal attempts: forces mass abandonment the refresh does not ask for. Running `--apply` here: it mutates other repositories' ledgers, which is not authorised |
| D10 | The Codex predicates are judged against the declaration. C8 is the #119 gate installed in the skills tree Codex reads. C9 is `host-route` answering as declared (Codex `declared_unsupported` with its alternative). Live Claude and Codex ships are P3, post-activation | Refresh: "against declared host capabilities, including bounded capacity admission"; #150 admission covers orchestration agent slots only (host-contention rejection), not the single-session ship path; #119 | Making Codex's `unsupported` red: the refresh measures against the declaration, and changing it is out of scope |
| D11 | C3 is red until F1's candidate exists and an `approved` bundle binds it. The #128 AC5 live paired trials are owner-run against that candidate and stay on #130's gate | #70 (approved needs fresh live strata, no hand-authored records); #128 owner comment and D11; #71 (one bundle against the final candidate) | Reusing `release-128-bundle.json`: it is `unmeasured` and binds another candidate. Moving the trials into F1: the owner placed them on #130 |
| D12 | The gate runs in order: migrate, re-run every item and record `N_H`, freeze (no gc, no other switch), activate, verify, roll back. Activation runs the contract's `nix-activate` (`just switch`) in a detached worktree at `<candidate>` that is removed afterwards, host by host in one session, and any failure rolls every activated host back. Rollback switches to the explicit bridge generation, through that generation's own `darwin-rebuild` on darwin and `nix-env --switch-generation` then `switch-to-configuration` on NixOS. `<candidate>` is the only unbound value | The resolved contract's `nix-activate` command; `darwin-rebuild --switch-generation` is its rollback action; no checkout-path symlinks exist in the config; #71 (no mixed live mode; the bridge is the rollback anchor) | Merging the candidate and switching from `main`: any routine switch would activate it host by host, giving a mixed fleet. `--rollback`: correct only if exactly one generation was added |
| D13 | Delivery is a docs-only PR. #130 stays open with `agent:human-required`. The gate comment links the checklist at the merged commit and lists the filings, so the command text lives only in the checklist. The issue's criteria are recorded as unmet or human-pending | Owner comment (stop at a human gate); DRY (one home for the command text); the 128 hold precedent | Closing #130 or checking its boxes: its criteria are post-activation or red. Quoting the commands in the comment: a second copy that can drift |
| D14 | Planning appended. The plan holds no fix task. Every expected red route fails a D7 condition: F1 and F2 are the cutover and its minor, F3–F7 and #555 lie in other repositories, their ledgers or worktrees, and F8 (D16) needs the installed tool. So a red route found at execution is filed even when it meets all four D7 conditions, and the delivery stays docs-only within the planned files. Each filed issue carries `wayfinder:slice`, plus `agent:human-required` when its repair needs the owner or another repository, and never `agent:ready` | D7 ("fixed here only if" states a necessary condition); D13 (docs-only PR); the #554 and #555 filings | A conditional fix task: its files are unknown until the evidence run, so it can be neither forecast nor reviewed as planned. Stopping to replan for a small fix: a planning round for work the owner can schedule from the filed issue |
| D15 | Planning appended. Evidence mechanics. `conformance run --purpose fleet` runs per (H,R) with `--repo-root R`, because its checks are repository checks on one subject; this refines section 3's per-host C2 wording. Every git call into a fleet root carries `--no-optional-locks`, and none fetches, nix-config's own clone included, so `origin/main` is read as last fetched and its commit recorded. C7 matches each worktree path, as listed and as its realpath, as a whole JSON string (`"<path>"`). `K_H` is the host's registered `fagenorn/nix-config` root, else the first by sorted path of its clones whose `origin` is `fagenorn/nix-config`. A host unreachable when Task 1 runs stays human-pending for the whole run | Planning probe 2026-11-03: the fleet purpose observes the `--repo-root` project, and Nodo's fleet run fails `repository.ignore.runtime_sentinel`; `git status` refreshes the index when it can lock it; D4 (a bare substring lets `x` inherit `x-y`'s ledger); D2; section 6 item 4 (no write or fetch into a fleet root) | One fleet run per host: it observes only the cwd's project. A substring search: under-reports red. Choosing `K_H` by build provenance: no generation records its checkout, and activation runs from a detached worktree at `<candidate>`, so the clone cannot change the result |
| D16 | Planning appended. The spec's seam "`adopt-project verify` stays `adopted` on the delivery worktree" is false at base: nix-config's verify is `not_conformant` on `adoption-evidence-record`, because the #127 and #128 bundle and trials JSON files at the top of `.agents/artifacts/evidence/` count as candidates. The seam becomes "the checklist adds no candidate": verify's result and failed check ids on the delivery worktree equal those at the base. The nix-config C2 row is red, and its expected disposition is a new filing, F8: count only adoption evidence records, or keep #70 bundles out of the candidate set | Planning probe 2026-11-03 on main `f6a48dcf` and the delivery worktree; `is_evidence_record_path` counts every top-level `.json` there; the-bar (point-in-time records keep their paths; root causes); D7 (an installed-tool fix cannot be re-observed without activation) | Moving the bundle files here: they are point-in-time records cited by the #127 and #128 plans, and C3's next bundle would land at the top level again. Keeping the seam as written: it fails at base, not because of the checklist |
| D17 | Planning appended. The checklist is capped at 57,344 bytes, an Observed excerpt at 160 characters, and the delivery is one review boundary. The post-activation items' evidence is cited from section 3 rather than copied | The review-package member limit is 65,536 bytes and one file diff above it forces `decompose_required`; D3 (one file) | Several checklist files: D3 rejects them. Two delivery boundaries: one file's whole diff still lands in the root boundary. Copying section 3's post-activation evidence column: a second copy of text the committed spec already holds, paid from the same cap |
| D18 | Plan review appended. C3 grades whether the candidate is covered, not each bundle: one row over `.agents/artifacts/evidence/` at `origin/main`, green when at least one `*-bundle.json` has `state: approved` and binds the commit C4 names as the strict candidate, and red otherwise or when a bundle cannot be read. Bundles that bind another candidate (today `promotion-127` and `release-128`) are listed as informational lines without a verdict and take no part in the worst-row rule. This refines section 3's C3 rule and D11; C3 stays red in this attempt because no candidate exists | Codex plan review B3: graded per bundle, the two retained `unmeasured` bundles keep C3 red after an approved cutover bundle lands, so the gate's all-green step 2 and F1's acceptance could never be met; #71 (one bundle against the final candidate); D4 (an unreadable bundle is red) | Grading every bundle against the candidate: never green while history is retained. Moving or deleting the historical bundles: they are point-in-time records cited by the #127 and #128 plans (D16) |
| D19 | Plan review appended. When a Task 5 re-read differs from its row, the whole row is re-observed (Revision, UTC, Exit, Observed and Verdict under its item's rule) and the item verdict recomputed. Dispositions follow the rows as last observed: a row no longer red is never filed or cited, and a row that turns red gets one. The acceptance record cites the commit that holds the final observation of each deciding row, not a fixed task's commit. This refines D5 and section 6 item 5 | Codex plan review S1: updating only UTC and Observed kept stale verdicts, so an issue could be filed from a now-green row, and AC7 cited Task 4's commit after Task 5 replaced its evidence; section 6 item 5 (filings from the last full run) | reviewer's call accepted as-is |
| D20 | SDD appended. After Task 1 the plan root stood 110 bytes over its 16,384-byte budget: `sdd-gate record` grows the delivery forecast block by one 123-byte process range per task, and the reviewed root left 12 bytes. One metadata-tail commit (#565) trims only the root's prose (header, test seams, boundaries, decision index, provenance, three Global Constraints wordings) to 15,622 bytes, leaving every forecast block byte-identical and every rule unchanged | `review-package` refused the cumulative gate as `invalid plan package`; `next`'s evidence step admits a process-only metadata tail; from-issue: a phase that shows the previous one wrong is redone | Failing the attempt at the review-package gate, or moving rules out of the root into task members that the other briefs would no longer quote |
