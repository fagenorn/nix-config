# Repeated fallback and prerequisite checks across the agent workflow, inventoried per site and classified against a validated onboarding contract

**Durability: committed** (Git owns this file's history from this commit forward.)

## Provenance

This document is a **re-derivation authored 2026-09-02 under issue #115**. It is
not the artifact that issue [#61](https://github.com/fagenorn/nix-config/issues/61)'s
resolution comment linked. That artifact was **never committed** to any git ref —
`git log --all -- .claude/specs/2026-08-20-agent-fallback-inventory-research.md`
returns zero commits in this repository — and its content is therefore
**unrecoverable**. Nothing below is a recovered byte, and **no claim in this file
may be cited as evidence of what the original said.**

What this document is obligated to satisfy is the set of conclusions asserted in
#61's [resolution comment](https://github.com/fagenorn/nix-config/issues/61),
plus #61's own research question. Those obligations are enumerated as claim IDs
in `## Coverage of the resolution summary`; every one is discharged below from
primary sources read on 2026-09-02, never from the resolution summary itself.

The filename's `2026-08-20` prefix is **#61's decision date** (the issue was
opened `2026-08-20T09:12:26Z` and closed `2026-08-20T09:25:58Z`), not this file's
authorship date. The authorship date is 2026-09-02. The two differ deliberately,
because the path is the one #61's resolution comment links and nothing may rename
it.

Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked.
This document asserts repository-state inventory — which branches exist at which
line of which file, and how three checkouts resolve them on 2026-09-02 — not a
live-availability or blocking conclusion, so the gate's two-timepoint
standing-conclusion machinery does not apply. This follows the precedent set by
`.claude/specs/2026-08-16-codex-worker-death-research.md`. Confidence is stated
inline instead.

## Research question

#61's question, verbatim:

> Across the shared skills and helpers plus the live nix-config, Nodo, and Argus
> adapters, which branches repeatedly detect commands, configuration,
> documentation, or agent capabilities, or silently fall back?
>
> Classify unavoidable portability checks versus checks removable after a
> validated onboarding contract. Measure attributable prompt size and repeated
> execution cost. Do not decide removal policy.

## Coverage of the resolution summary

| ID (source) | Claim restated in one line | Source of the claim | Discharged by (heading in this document) |
|---|---|---|---|
| C61.1 (summary) | The clearest removable cluster is project binding, command, tracker and doc discovery — all four families named, each with its concrete sites. | #61 resolution comment | The removable cluster |
| C61.2 (summary) | Product/runtime preflights tied to live external variability are not interchangeable with onboarding fallbacks, and the discriminating property is stated. | #61 resolution comment | Why runtime preflights are not interchangeable |
| C61.3 (question) | A per-site inventory across the shared skills and helpers plus the live nix-config, Nodo and Argus adapters, each site classified. | #61 research question | Per-site inventory |
| C61.4 (question) | Attributable prompt size and repeated execution cost, with a stated unit, a stated method, and per-cluster numbers. | #61 research question | Attributable prompt size and repeated execution cost |
| C61.5 (question) | No removal policy is decided. | #61 research question | What this document does not decide |

## Unverified inheritance

This section holds claims inherited from #61 that are not re-verified against a
primary source, and observed claims whose truth is bounded. Silence is not
permitted, so each is named.

1. **"The clearest removable cluster" is #61's judgement, not an observation.**
   What this document verifies is which sites exist, what each branches on, and
   whether its input is a repository property an onboarding contract could fix.
   That the four families are the *clearest* candidate is inherited from the
   resolution comment and is not re-derived; no ranking against other families
   was measured.
2. **"Validated onboarding contract" has no artifact to check against yet.** The
   contract is *decided* but not *materialized*: issue #69 (closed) settles a
   schema-closed conformance engine over four truth domains, and #65 fixes
   `.agents/project.json` as the sole authored policy file — but on 2026-09-02
   no `.agents/` directory exists in any of the three checkouts, and
   `.claude/skills.config.json` has no schema file anywhere in this repository
   (`find . -name '*schema*'` outside `.git` returns nothing). Every
   `removable-after-validated-onboarding-contract` verdict below is therefore a
   statement about the *input* of the branch — a repository property some
   contract could guarantee — and is not a claim that today's
   `.claude/skills.config.json` guarantees it.
3. **The prompt-size numbers are whole-line byte counts and overstate.** Where a
   fallback is one clause of a longer line — `ship-issue/SKILL.md:222` is the
   worst case, 1005 bytes of which only the trailing sentence is the fallback —
   the whole line is counted. The method is stated with the numbers rather than
   corrected, because no reproducible sub-line boundary exists.
4. **Snapshot-bound fleet claims.** Every Nodo claim is bound to the checked-out
   snapshot, 111 commits behind its own `origin/dev` (see `Method and evidence
   base`). Any Nodo conclusion could turn on those 111 commits — including the
   observation that all seven of its declared `docPaths` resolve. Argus's
   checkout is level with `origin/main` and carries no such caveat.
5. **Repeated execution cost is measured only where a subprocess exists.** Only
   the project-binding family runs a process per invocation. For the doc-discovery
   family the repeated cost is model turns spent on filesystem probes, which this
   evidence base cannot price; the probe *count* is measured instead and the
   per-turn cost is recorded as having **no answer in the sources read**.
6. **Absence verdicts are observed absence on this machine and in these three
   checkouts.** The claim that `~/.agents/bin` holds nine helpers is a direct read
   of that directory on 2026-09-02, not an inference from
   `home/common/agent-skills/default.nix`; the claim that Argus declares no
   bindings is a direct read of its `.claude/` directory, not an inference from
   any module.

## Method and evidence base

**Three words are kept apart** throughout, per #61's own framing and the
terminology guard this work inherits:

- A **fallback** degrades to a lesser but continuing behaviour — the operation
  proceeds with a default, a guess, or a cheaper path.
- A **fail-closed refusal** blocks and does not degrade — the operation stops,
  and no lesser version of it runs.
- A **declared runtime alternative** is a second strategy predeclared by a
  versioned contract, not a rescue path improvised at the failure. Issue #69
  (closed) fixes it: legitimate "only when a versioned core workflow contract
  predeclares a finite strategy for a live failure after successful resolution",
  with a bounded attempt budget, the original failure retained and the selected
  branch reported. Nothing in this inventory qualifies — none of the 34 sites is
  predeclared by a versioned contract — so nothing is classified into it.

Only the first is an inventory site here. The second and third appear as
contrasting cases, named as such.

**Sources, and how they are cited.**

- *Files in this repository* (nix-config) are cited by repo-relative path plus
  line, with the symbol name when the claim is about one. Line numbers are as of
  the worktree `worktree-issue-115-recover-wayfind-research-findings` on
  2026-09-02.
- *Files in a fleet checkout* are cited as repository name + repo-relative path +
  the checkout's observed `HEAD` + the observation date. All fleet observations
  are dated **2026-09-02** and were read without writing to, checking out,
  fetching or stashing in either checkout.
- *Files in the user's home directory* (`~/.agents/bin/`, `~/.agents/standards/`)
  are given by absolute path with the observation date and labelled **user
  scope**. They sit outside every repository, which is the fact several verdicts
  below turn on.
- *Settled decisions* are cited by issue number.

**The two fleet checkouts, as observed on 2026-09-02:**

| Checkout | Observed `HEAD` | Branch | Divergence from its own `origin` integration ref |
|---|---|---|---|
| `/Users/anis/Projects/nodocom` (Nodo) | `7a3dab7e541f44f5b021fe13a1e20894de2ef0b8` | `dev` | 111 commits behind `origin/dev`, 0 ahead (`git rev-list --count HEAD..origin/dev` → `111`) |
| `/Users/anis/Projects/argus` (Argus) | `20d6655223e9497c2668f67dd016e1111b3a78cb` | `main` | level with `origin/main` — 0 behind, 0 ahead |

The checked-out snapshot is the cited evidence. Neither checkout was refreshed,
so these are the adapters as they stood on 2026-09-02, not either repository's
current integration tip. **The third repository is nix-config itself**, read in
the worktree named above.

**What "silently" means in the verdicts below.** A branch is called silent when
it takes the lesser path without writing a diagnostic. `resolve-bindings` is
mixed: a missing config file is silent (`load_config`, lines 49-50), an
unreadable or unparseable one prints one line to stderr and still returns `{}`
(lines 53-55), and an invalid orchestration integer prints one line and keeps
exit status 0 (`positive_int_str`, lines 91-107, whose docstring states the
reason: "one bad optional orchestration key must not break binding resolution
for every skill").

## The removable cluster

#61's resolution comment names four families. All four exist in the live tree,
and each is named here with its concrete sites; the full per-site classification
is in `Per-site inventory`.

**Project binding.** One helper —
`home/common/agent-skills/scripts/resolve-bindings` — owns the family. It emits
14 `key=value` lines and fills every one of them through a three-rung ladder:
`.claude/skills.config.json` → auto-detection from local git metadata →
a `DEFAULTS` table (lines 26-37). Ten of the fourteen keys have no detection
rung at all and go straight from absent-config to a hardcoded default
(`specDir`, `planDir`, `integrationBranch`, `defaultBranch`, `branchPattern`,
`worktreePrefix`, `coAuthoredBy`, `unsetGithubToken`, `agentBudgetMinutes`,
`maxParallel`); three have one (`repoSlug`, `trackerKind`, `trackerCli`), and
`repoRoot` is derived. Seven skills carry prose duplicating that ladder:
`ship-issue/SKILL.md:13`, `doc-grounded-questions/SKILL.md:12`,
`to-issues/SKILL.md:12`, `writing-plans/SKILL.md:11-13`, `research/SKILL.md:16`,
`design/SKILL.md:49`, and `ship-release/SKILL.md:24` — which does not call the
helper at all and instead restates the default set in prose.
`orchestrate-issues/SKILL.md:26-31` calls the helper but carries no fallback: it
forbids the adapter from copying either orchestration default, so it is not an
inventory site.

**Command.** Two shapes. Verify-command detection sniffs the manifest when the
config does not declare one — `ship-issue/SKILL.md:13`: "Verify commands: config,
else the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`,
`Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`)".
Helper-binary resolution is the other — `ship-issue/SKILL.md:222` and
`codex-collaboration/DIFF-REVIEW.md:23-25` both instruct the reader to use the
full `~/.agents/bin/diff-scope` path "if the bare name does not resolve", and both
define a no-measurement outcome.

**Tracker.** `resolve-bindings` `detect_tracker` (lines 77-82) maps an origin URL
to `github`/`gh`, `gitlab`/`glab`, or `none`/`""`, and `origin_url` (lines 59-69)
returns `""` on a timeout, an `OSError`, or a non-zero git exit — which silently
produces `trackerKind=none` and an empty `repoSlug`. Downstream, `kind: none` is
a first-class degraded mode: `ship-issue/SKILL.md:15` skips every issue/PR/CI
step, `to-issues/SKILL.md:18` presents the breakdown without publishing, and
`ship-release/SKILL.md:30` replaces Phases 2-4 with a local `git merge --no-ff`.
`ship-release/SKILL.md:28` re-derives `repoSlug` from `git remote get-url origin`
when config does not set it.

**Doc discovery.** The longest ladder in the tree.
`doc-grounded-questions/SKILL.md:20` resolves the context map as
`docPaths.contextMap` → `docs/CONTEXT-MAP.md` → legacy root `CONTEXT-MAP.md` →
no map at all, which routes to the legacy single-doc fallback; that fallback
(`doc-grounded-questions/REFERENCE.md:26-29`) tries `docPaths.context`,
`CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md`, or a `README` domain section. Decision
logs (`REFERENCE.md:36-38`) try each area's `adr/`, then `docPaths.adrDir`, then
`docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/`. Architecture
(`doc-grounded-questions/SKILL.md:26`) tries `docPaths.architecture`, else
`ARCHITECTURE.md` / `docs/architecture.md` / a README section.
`grill-with-docs/SKILL.md:38-41` carries its own three-tier layout detection, and
`to-issues/SKILL.md:28` closes with "If those docs are absent, skip this
grounding step silently."

## Why runtime preflights are not interchangeable

**The discriminating property, in one sentence:** an onboarding fallback branches
on a property of the repository that a one-time contract could fix and freeze, so
it can be checked once and never again; a product or runtime preflight branches
on state owned by a system outside the repository that can change between two
invocations *inside a single run*, so no contract can freeze it and the check has
to run every time.

Three preflights in this tree demonstrate the property, and none of them is an
inventory site above.

- **`ship-issue`'s launch guard** (`ship-issue/SKILL.md:60-77`) re-runs
  `workflow-state check-launch` "before **every write to the forge or to
  `origin` this skill makes up to and including the merge**", and again
  "immediately before the merge" (line 281) after having run it at line 178 and
  line 185. The reason is stated at lines 62-64: the lifecycle "hands a retry the
  predecessor's worktree and branch on purpose, so a superseded attempt can still
  push, open a PR and merge." The ledger is mutated by another agent while this
  one runs. A repeated check here is not duplication; the earlier answer expires.
- **`ship-release`'s CI wait** (`ship-release/SKILL.md:140-151`) re-issues
  `gh pr checks --watch` on exit `124` up to eight times, and treats a
  never-terminal state as an escalation because "webhooks can fail to fire
  silently". The input is GitHub Actions' state.
- **`ship-release`'s deploy watch** (`ship-release/SKILL.md:288-302`) polls
  per-service deployment *lists* rather than status summaries, precisely because
  "the chronology is what distinguishes a silent rollback from a stale
  notification" (line 306), and because a `FAILED` deployment can surface after a
  newer `SUCCESS` (line 302). The input is the deploy platform's state.

This is not a distinction invented here. Issue #69's resolution settles the same
line as a matter of policy: "Facts that can change after workflow entry — remote
reachability, provider/service health, tenant/business capability, and product
runtime state — are runtime health, not project conformance." The property is
cited as a settled decision, and the three sites above are the observations that
instantiate it in this tree.

Two contrasting cases fix the boundary of this inventory from the other side.

- The **fail-closed** lifecycle guard. `home/common/claude-code/default.nix:947-958`
  registers a `PreToolUse` hook on `Bash`; `CLAUDE.md:60` records that "there is
  no defer path: once the hook adjudicates a verb it is validated-and-allowed or
  blocked, never handed back to the allowlist unexamined, and every uncertainty
  (unknown repo, unresolvable default branch, child timeout, non-zero or
  unparseable output) blocks." Its own source says the same at the parser level:
  an unparseable command "the caller treats as a fail-closed signal" (line 243)
  and an untokenisable segment is likewise "fail-closed" (line 327). It performs
  live `gh` lookups against a changing forge — so it *is* a runtime preflight —
  but it never degrades, and it is therefore enforcement, not an inventory site.
- **Helpers that raise instead of degrading.** `diff-scope.py:428-431` refuses to
  treat a missing object as recoverable with the comment "a missing answer is a
  hard error, never a fallback (issue #21's D7)"; `artifact_budget.py:112,123,232,240,249`
  raises on every unopenable, unreadable or concurrently-modified artifact;
  `handoff/SKILL.md:51-52` requires "stop failed rather than copy unmeasured
  bytes" and `handoff/SKILL.md:85-86` forbids a "prose fallback". These are
  fail-closed refusals inside the same helper set and are excluded for the same
  reason.

## Per-site inventory

34 sites. **20** are classified
`removable-after-validated-onboarding-contract` — the branch's input is a
repository property a contract could guarantee. **14** are classified
`unavoidable-portability` — the branch's input is a property of the machine, the
harness, or the forge, which no repository onboarding contract reaches. Every
site is a fallback in the sense fixed above; fail-closed refusals and declared
runtime alternatives are excluded.

### Shared skills and helpers

| # | Site | Branches on | Classification |
|---|---|---|---|
| A1 | `scripts/resolve-bindings:26-37,132-160` — `config.get(k) or DEFAULTS[k]` for 14 keys | absent config key | removable-after-validated-onboarding-contract |
| A2 | `scripts/resolve-bindings:40-44,116-118` — `find_repo_root` returns `start` when no `.git` and no config is found | invocation directory | unavoidable-portability |
| A3 | `scripts/resolve-bindings:47-56` — `load_config` returns `{}` on missing file (silent), on `OSError`/`JSONDecodeError` (one stderr line), or on a non-dict top level (silent) | config file presence and validity | removable-after-validated-onboarding-contract |
| A4 | `scripts/resolve-bindings:85-88` — `as_bool_str` substitutes the default for any non-bool | config value type | removable-after-validated-onboarding-contract |
| A5 | `scripts/resolve-bindings:91-107` — `positive_int_str` substitutes the default for a non-positive or non-int, exit status stays 0 | config value type | removable-after-validated-onboarding-contract |
| A6 | `skills/{ship-issue:13, doc-grounded-questions:12, to-issues:12, writing-plans:11, research:16, design:49}/SKILL.md` — "helper missing → read the config and apply the same defaults" | presence of `~/.agents/bin/resolve-bindings` on the machine | unavoidable-portability |
| A7 | `skills/ship-release/SKILL.md:24` — reads the config directly and restates the whole default set in prose, calling no helper | absent config key | removable-after-validated-onboarding-contract |
| A8 | `skills/{ship-issue:15, doc-grounded-questions:12, to-issues:12}/SKILL.md`, `skills/ship-release/SKILL.md:24` — "never hard-fail on a missing optional binding"; "skip any configured-but-absent doc path silently" | declared-but-absent path | removable-after-validated-onboarding-contract |
| B1 | `skills/ship-issue/SKILL.md:13` — verify commands from config, else manifest sniffing across five manifest kinds | absent `verify` config | removable-after-validated-onboarding-contract |
| B2 | `skills/ship-issue/SKILL.md:222` — `~/.agents/bin/diff-scope` by full path when the bare name does not resolve; no measurement → run the full two-axis review | helper on PATH | unavoidable-portability |
| B3 | `skills/codex-collaboration/DIFF-REVIEW.md:23-25,59-63` — same helper, no measurement → dispatch as under-budget and report `unmeasured` | helper on PATH | unavoidable-portability |
| C1 | `scripts/resolve-bindings:77-82,123-126` — `detect_tracker` derives kind and CLI from the origin URL when config omits `issueTracker` | absent config key | removable-after-validated-onboarding-contract |
| C2 | `scripts/resolve-bindings:59-69` — `origin_url` returns `""` on `OSError`, `TimeoutExpired`, or non-zero git exit, yielding `trackerKind=none` | git availability and remote state | unavoidable-portability |
| C3 | `skills/to-issues/SKILL.md:18` — `kind: none` presents the breakdown without publishing; neither config nor remote resolves → ask exactly one question | absent tracker binding | removable-after-validated-onboarding-contract |
| C4 | `skills/ship-issue/SKILL.md:15` — `issueTracker.kind=none` skips every issue/PR/CI step | absent tracker binding | removable-after-validated-onboarding-contract |
| C5 | `skills/ship-release/SKILL.md:30` — no forge → local `git merge --no-ff`, tag the local result, skip PR/CI/Release | absent tracker binding | removable-after-validated-onboarding-contract |
| C6 | `skills/ship-release/SKILL.md:28` — derive `repoSlug` from `git remote get-url origin` when config does not set it | absent config key | removable-after-validated-onboarding-contract |
| C7 | `skills/ship-release/SKILL.md:75` — `GH_PREFIX` is `unset GITHUB_TOKEN && ` or empty per `unsetGithubToken`; `glab` verb translation when `cli == "glab"` | absent config key | removable-after-validated-onboarding-contract |
| C8 | `skills/to-issues/SKILL.md:87-89` — GitLab native blocking links are Premium/Ultimate; on the free tier the body's "Blocked by" section is the record | forge subscription tier | unavoidable-portability |
| D1 | `skills/doc-grounded-questions/SKILL.md:20` — context map: `docPaths.contextMap` → `docs/CONTEXT-MAP.md` → legacy root `CONTEXT-MAP.md` → no map | absent config key and absent file | removable-after-validated-onboarding-contract |
| D2 | `skills/doc-grounded-questions/REFERENCE.md:26-29` — no map → `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md`, or a README domain section | absent config key and absent file | removable-after-validated-onboarding-contract |
| D3 | `skills/doc-grounded-questions/REFERENCE.md:36-38` — decision log: area `adr/` dirs, else `docPaths.adrDir`, else `docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/` | absent config key and absent file | removable-after-validated-onboarding-contract |
| D4 | `skills/doc-grounded-questions/SKILL.md:24` with `REFERENCE.md:41-44` — project standards deltas are read only from `docPaths.standards`; there is no unconfigured discovery rung | absent config key | removable-after-validated-onboarding-contract |
| D5 | `skills/doc-grounded-questions/SKILL.md:26` — architecture: `docPaths.architecture`, else `ARCHITECTURE.md` / `docs/architecture.md` / a README section | absent config key and absent file | removable-after-validated-onboarding-contract |
| D6 | `skills/grill-with-docs/SKILL.md:38-41` — three-tier layout detection: standard tree, legacy conventions, then `docPaths` overrides | repository doc layout | removable-after-validated-onboarding-contract |
| D7 | `skills/to-issues/SKILL.md:28` — glossary and ADR grounding, "If those docs are absent, skip this grounding step silently" | absent file | removable-after-validated-onboarding-contract |
| D8 | `skills/ship-release/SKILL.md:71` — `doc-grounded-questions` unavailable → read the configured doc directly when it exists | sibling skill installed on the machine | unavoidable-portability |
| E1 | `skills/worktrees/SKILL.md:37` — "No native worktree tool:" → `git worktree add` | harness tool surface | unavoidable-portability |
| E2 | `skills/ship-issue/SKILL.md:237-241` — `codex-collaboration`'s `diff-review` unavailable → native `reviewer` dispatch (`id=ship-issue-full-correctness-fallback`) | Codex CLI installed on the machine | unavoidable-portability |
| E3 | `skills/from-issue/SKILL.md:155` — Phase 5 is "Codex plan review, native fallback, or self-grade" | Codex CLI installed on the machine | unavoidable-portability |
| E4 | `skills/from-issue/SKILL.md:180` — "Never hard-fail on a missing sibling" → run the phase inline | sibling skill installed on the machine | unavoidable-portability |
| E5 | `skills/ship-issue/SKILL.md:359` — absent sibling skills degrade to no-ops | sibling skill installed on the machine | unavoidable-portability |
| E6 | `skills/improve-codebase-architecture/SKILL.md:32` — host cannot dispatch a sub-agent → perform the scan inline and disclose the fallback | harness agent-dispatch capability | unavoidable-portability |
| E7 | `skills/doc-grounded-questions/SKILL.md:39` — grounding cache at `$(git rev-parse --git-dir)/GROUNDING.md`; outside a git repo, fall back to the platform temp dir | invocation directory | unavoidable-portability |

Paths in the table are relative to `home/common/agent-skills/`, except
`skills/codex-collaboration/`, which lives under `home/common/claude-code/`
(one of the two Claude-only skills).

**Why the helper- and sibling-presence sites (A6, B2, B3, D8, E4, E5) are
portability and not contract.** `~/.agents/bin/` is user scope — an absolute path outside every
repository, populated by `home/common/agent-skills/default.nix:52-102` as nine
home-manager symlinks into the Nix store, with `home.sessionPath` adding it to
PATH (line 161). Read on 2026-09-02, it holds `agent-evidence`,
`agent-model-matrix`, `artifact-budget`, `context-map-lint`, `diff-scope`,
`resolve-bindings`, `review-package`, `sdd-workspace`, `workflow-state` — so on
this machine none of these branches fires. That they are nonetheless live is
stated by the sources themselves: `DIFF-REVIEW.md:63-64` records that
"`diff-scope` reaches `~/.agents/bin` only after a rebuild, so absence is a real
state on a machine that has this skill", and
`home/common/agent-skills/default.nix:87-92` records an observed incident — "a
ship-issue cleanup wrongly retained a worktree after concluding no producer
existed on the machine" — plus a second at lines 156-159, "exit 127 — the failure
codex-companion hit before it was wrapped onto PATH". A repository onboarding
contract cannot reach any of these. A machine-level contract could, and #69's
settled `host` truth domain is where it would live: "declared CLI presence and
admissible version, native trust, credential presence without values, host
adapter prerequisites, and freshness of required native smoke certification".

### The three live adapters

Observed by running `resolve-bindings --repo-root <path>` against each checkout
on 2026-09-02 and attributing each of the 13 non-derived keys to the rung that
produced it. `repoRoot` is excluded as derived rather than resolved.

| Adapter | Checkout and `HEAD` | Config file | From config | From detection | From `DEFAULTS` |
|---|---|---|---|---|---|
| nix-config | this worktree, branch `worktree-issue-115-recover-wayfind-research-findings` | `.claude/skills.config.json`, `orchestration` only | 2 | 3 | 8 |
| Nodo | `/Users/anis/Projects/nodocom` at `7a3dab7e541f44f5b021fe13a1e20894de2ef0b8` | `.claude/skills.config.json`, 13 top-level keys | 11 | 0 | 2 |
| Argus | `/Users/anis/Projects/argus` at `20d6655223e9497c2668f67dd016e1111b3a78cb` | **none** — no `.claude/skills.config.json` exists | 0 | 3 | 10 |

Three consequences follow, each observed rather than inferred.

1. **The project-binding fallback is not dead code; for Argus it is the whole
   mechanism.** Argus declares nothing, so all 13 bindings come from detection or
   `DEFAULTS`. The defaulted `integrationBranch=main` is at least consistent with
   the checkout's observed branch `main`, level with `origin/main`. Whether the
   other nine defaulted values match Argus's intent has **no answer in the
   sources read**: Argus states no intent about them anywhere this evidence base
   reaches, which is precisely the condition an onboarding contract would end.
2. **Doc discovery runs to exhaustion in exactly one of the three.** Walking the
   four ladders (context map, legacy glossary, decision log, architecture) as
   filesystem probes on 2026-09-02, skipping any rung the adapter's config
   already resolves: nix-config makes **13 probes and gets 0 hits** — it declares
   no `docPaths` and has no `docs/` directory at all; Argus makes **4 probes and
   gets 2 hits** (`docs/CONTEXT-MAP.md`, and `docs/areas/`, which holds 12 area
   `adr/` directories) and misses on the architecture rung, because it declares
   nothing either; Nodo makes **1 probe and gets 1 hit** — its config declares
   `docPaths.contextMap` and `docPaths.architecture`, so those two ladders
   resolve at the config rung and never probe, leaving only the
   area-versus-legacy look at `docs/areas/`, which is present. All seven of
   Nodo's declared `docPaths` resolve to existing paths.
3. **Argus's project standards are unreachable through the grounding pass.**
   `docs/standards/README.md` exists in Argus, but D4 above has no unconfigured
   discovery rung — project deltas are read only from `docPaths.standards`, and
   Argus declares no config. This is a gap, recorded here as observed; it is not
   a fallback site and is not counted among the 34.

**Drift against the resolution summary, per the drift rule.**

- *As-of-decision claim:* #61's resolution comment says "The clearest removable
  cluster is project binding, command, tracker, and doc discovery."
- *As observed (2026-09-02, by reading each cited line and running
  `resolve-bindings` against all three checkouts):* the four families hold 27 of
  the 34 sites, but only **20** of those 27 are removable by a repository
  onboarding contract. Seven sites inside the named cluster — A2, A6, B2, B3, C2,
  C8, D8 — branch on the machine, the harness or the forge, not on the
  repository.
- *Reconciliation:* the summary holds at the level of families and is refined,
  not contradicted, at the level of sites. Naming a family removable does not make
  every branch inside it removable; a contract that declared every key in
  `.claude/skills.config.json` would still leave those seven standing.

## Attributable prompt size and repeated execution cost

Unit: bytes of UTF-8 Markdown source, counted as whole lines.
Method: for each prose site, `sed -n '<line-range>p' <file> | wc -c`, summed
per family. Each physical line is attributed to exactly one family and never
counted twice, so where one line carries two families' sites the second family is
understated: `ship-issue/SKILL.md:13` carries A6 and B1, and
`ship-issue/SKILL.md:15` carries A8 and C4; both are counted under project
binding. Whole lines overstate wherever a fallback is one clause of a longer line
(see `## Unverified inheritance`, item 3). Denominator: the 13 files that carry
these sites, `wc -c` -> **169,336 bytes**.

| Cluster | Line ranges measured | Bytes | Share of the 13 files |
|---|---|---|---|
| Project binding | 7 | 4,000 | 2.4% |
| Command | 3 | 1,769 | 1.0% |
| Tracker | 5 | 2,095 | 1.2% |
| Doc discovery | 5 | 4,869 | 2.9% |
| **Four families, subtotal** | **20** | **12,733** | **7.5%** |
| Agent capability (outside the four) | 7 | 2,493 | 1.5% |
| **All prose sites** | **27** | **15,226** | **9.0%** |

**Seven of the 34 sites contribute zero prompt bytes.** A1-A5, C1 and C2 live in
`home/common/agent-skills/scripts/resolve-bindings`, which the model executes
rather than reads: 5,517 bytes of Python in total, of which lines 24-107 (the
`DEFAULTS` table and the three coercion helpers) are 2,535 bytes and lines
123-160 (the binding assembly) are 1,623. Their cost is execution, measured
below, not prompt. The table above therefore counts line ranges of prose, not
sites.

A token figure is **an estimate**: at roughly 4 bytes per token for English
Markdown, 15,226 bytes is on the order of **3,800 tokens** — labelled an estimate
because no tokeniser was run against these files. The byte figures are
measurements.

Not all of these bytes are resident at once. **13,501** of the 15,226 sit in
`SKILL.md` files, which load when the skill is invoked; **1,725** sit in
`doc-grounded-questions/REFERENCE.md` (961) and
`codex-collaboration/DIFF-REVIEW.md` (764), which load only when a step points at
them.

Unit: wall-clock milliseconds per invocation, median of a 20-run sample.
Method: `subprocess.run` in a Python loop against this worktree, no warm-up
discarded, on the machine described above on 2026-09-02.

| Measured | Median |
|---|---|
| `resolve-bindings --repo-root <this worktree>` | 40 ms (a second 20-run sample gave 46 ms) |
| `python3 -c pass` (interpreter floor) | 15 ms |
| `git -C <root> remote get-url origin` (its one subprocess) | 7 ms |

So roughly 18 ms of the 40 is the script's own import and work; the rest is
interpreter startup plus the one git call, and the whole thing is unconditional —
`origin_url` runs on every invocation whether or not `repoSlug` and
`issueTracker` are configured (lines 120-121 call it before any config key is
consulted).

Per-cluster repeated execution cost:

- **Project binding:** one 40 ms process per resolving skill. A single
  `/from-issue` run passes through four skills that resolve bindings — `design`,
  `writing-plans`, `doc-grounded-questions` and `ship-issue`, being the four of
  the eight sub-skills listed at `from-issue/SKILL.md:178` that carry a
  binding-resolution site — so **at least 4 invocations, on the order of 160 ms
  per run**. The multiplication is an estimate; the 4 is a count read from the
  source and the 40 ms is measured.
- **Command:** `diff-scope` runs at most once per review in `ship-issue`
  Phase 5 and once per `diff-review` packet, so its repeated cost is negligible
  relative to the review it gates. No separate timing was taken.
- **Tracker:** no additional process. Detection is the same `git remote get-url`
  already counted in the 40 ms, and the `kind: none` branches are prose read by
  the model, not executed.
- **Doc discovery:** no subprocess at all. The repeated cost is model turns spent
  on filesystem probes — 13 for nix-config, 4 for Argus, 1 for Nodo, as measured
  above. The per-turn cost of a probe has **no answer in the sources
  read**; this evidence base contains no harness instrumentation, and none was
  fabricated.

## What this document does not decide

Per #61's own instruction — "Do not decide removal policy" — and C61.5, this
document decides nothing. Specifically it does **not** decide:

- whether any of the 20 `removable-after-validated-onboarding-contract` sites
  should actually be removed, nor in what order, nor behind what evidence. Note
  that this is not an open question in the tracker: #71's resolution (closed)
  settles a strict cutover that "deletes static discovery/default fallback in the
  same candidate", serialized `nix-config → Nodo → Argus`. That decision is
  #71's, taken after this inventory's ticket — #61 closed `2026-08-20T09:25:58Z`,
  #71 `2026-08-20T19:22:27Z` — and nothing here ratifies, refines or re-opens
  it;
- what the validated onboarding contract makes required versus optional, or what
  happens when a repository violates it. #69's resolution settles that too — one
  conformance engine, closed purposes, one repair route per reason code — and
  this document neither restates nor evaluates it; it is why every removable
  verdict here is conditional (`## Unverified inheritance`, item 2);
- whether any of the 14 `unavoidable-portability` sites should become a
  **fail-closed refusal** with a repair route, or a **declared runtime
  alternative**. #69's "no fallback is permitted for ... missing tool/trust/
  credential" bears on several of them, but mapping this inventory's 14 sites
  onto that rule is an act of policy application and is not performed here;
- whether the six helper- and sibling-presence sites (A6, B2, B3, D8, E4, E5)
  should be addressed by a machine bootstrap contract rather than a repository
  one, though the evidence above shows a repository contract cannot reach them;
- what Argus should declare, or whether it should declare anything at all. Its
  unreachable `docs/standards/README.md` is recorded as an observation, not as a
  defect to fix here.
