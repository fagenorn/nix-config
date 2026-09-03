# Repeated fallback and prerequisite checks across the agent workflow, inventoried per site and classified against a validated onboarding contract

**Durability: committed** (Git owns this file's history from this commit forward.)

## Provenance

This document is a **re-derivation authored 2026-09-02 under issue #115**. It is
not the artifact that issue [#61](https://github.com/fagenorn/nix-config/issues/61)'s
resolution comment linked. That artifact was **never committed** to any git ref:
`git log --all -- .claude/specs/2026-08-20-agent-fallback-inventory-research.md`
returned **zero commits** in this repository, verified at this branch's base
commit `0b57dbd` on 2026-09-02. Run at or after the commit that adds this file
the same command returns one — this file's own — so the base commit is the ref
at which the observation is checkable. Its content is therefore
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

| ID (source) | Claim restated in one line | Source of the claim | Discharged by (heading in this document package) |
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
3. **The prompt-size numbers are whole-line byte counts and overstate.** The
   measured unit is the whole line, never a sub-line span, because no
   reproducible sub-line boundary exists. Where a fallback is one clause of a
   longer line the surrounding clause is counted with it —
   `ship-issue/SKILL.md:222` is the worst case, 1005 bytes of which only the
   trailing sentence is the fallback. A multi-line range likewise counts the
   blank lines and list markers inside it. Every measured range is published in
   `.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/measured-ranges-and-adjudication.md § The measured ranges`,
   so a reader can see exactly which lines each number covers rather than taking
   the aggregate on trust; no wider block than those ranges was measured.
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
  branch reported. Nothing in this inventory qualifies, but one site comes
  close: E14, `codex-collaboration`'s one-time native reviewer, predeclares a
  single attempt, refuses to retry, retains the concrete failure class and
  records that the fallback was used. It fails #69's predicate only on
  "versioned core workflow contract ... after successful resolution" — skill
  prose is not versioned and no resolution step exists yet (see
  `## Unverified inheritance`, item 2). It is inventoried as a fallback and the
  near-miss is recorded rather than resolved either way.

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
| `/Users/anis/Projects/nodocom` (Nodo) | `7a3dab7e541f44f5b021fe13a1e20894de2ef0b8` | `dev` | 111 commits behind `origin/dev` as measured on 2026-09-02, 0 ahead (`git rev-list --count HEAD..origin/dev` → `111` **on that date**) |
| `/Users/anis/Projects/argus` (Argus) | `20d6655223e9497c2668f67dd016e1111b3a78cb` | `main` | level with `origin/main` on 2026-09-02 — 0 behind, 0 ahead |

**These two rows are a dated observation, not a re-runnable command.** They pin
the snapshot every Nodo and Argus claim below was read from. A reader running
`git rev-parse HEAD` in either checkout today will very likely get a different
sha, and `git rev-list --count 7a3dab7e..origin/dev` a larger number than 111,
because both checkouts and both remotes move and this work deliberately
refreshes neither: the cited shas stay reachable, and the distance figure is the
distance *as it stood on the observation date*, against the `origin/dev` of that
date. Re-running either command and finding a different answer confirms the
snapshot has aged; it does not contradict anything here. **The third repository
is nix-config itself**, read in the worktree named above.

**How the sites were enumerated, so the count is auditable.** Every regular file
in `home/common/agent-skills/skills/` and `home/common/claude-code/skills/`
(excluding each skill's `evals/`) and every script in
`home/common/agent-skills/scripts/` was swept — **65 files**: 58 under the two
skill trees, which already contain `sdd/scripts/`, plus 7 under `scripts/`,
enumerated with `find … -type f -not -path '*/evals/*'` on 2026-09-02 at
`d0309be`, this branch's pre-sync head. The Phase-1 sync from `main` then added
`agent-skills/scripts/resolve-project.py` and `claude-code/skills/ship-issue/HUMAN-GATE.md`
and rewrote `writing-plans/SKILL.md:11-13`, so this corpus, its line-anchored
quotations and every count derived from them reproduce at `d0309be` and not at
this file's own commit. Three inputs produced the rows.

**Pass 1, broad**, over all 65 files, to find the candidates:

```
grep -rniE 'fallback|falls? back|degrade|absent|unavailable|not (available|installed|present)|command -v|legacy|helper missing|no native|cannot dispatch' \
  home/common/agent-skills/skills home/common/claude-code/skills home/common/agent-skills/scripts \
  | grep -v '/evals/'
```

**Pass 2, narrowed** to the branch shapes the skills actually spell out, to
separate branches from prose that merely uses the words:

```
grep -rniE 'if unavailable|is unavailable|not installed|command -v|helper missing|no measurement|else the manifest|fall back to|falls back to|degrade[sd]? (to|gracefully)|no native|cannot dispatch|absent (sibling|helper|skill)|missing (sibling|helper)|legacy (fallback|root|ADR|conventions|repos|single-doc)|else `|, else |otherwise `' \
  home/common/agent-skills/skills home/common/claude-code/skills home/common/agent-skills/scripts \
  | grep -v '/evals/'
```

**A full read of `home/common/agent-skills/scripts/resolve-bindings`** (168
lines), because rows A1-A5, C1 and C2 are Python branches whose *branch lines*
carry none of the vocabulary above — pass 1 reaches that file only through its
docstrings (lines 5, 6, 92 and 94). No keyword sweep would have produced those
seven rows; reading the file did. The other six scripts under
`home/common/agent-skills/scripts/` were read the same way and yielded no rows:
`agent-evidence.py`, `agent-model-matrix.py`, `artifact-budget`,
`artifact_budget.py`, `diff-scope.py` and `workflow-state.py`. So was
`skills/sdd/scripts/task-brief`, which is a skill-tree script, not one of those
seven. The nearest thing to a degrade among them is `workflow-state.py:315-325`,
a source-module → sibling → `~/.agents/bin/artifact-budget` path ladder; it is
not one, because `artifact_budget_validate` at `:328-346` raises
`WorkflowError` on any non-zero exit or empty stdout, so no lesser result ever
reaches a caller. One branch in the same helper does substitute silently:
`:323-325` passes `--policy` only when `trusted_policy` resolves the installed
path, and that helper returns `None` on `OSError` (`:311-312`), so an
unresolvable policy symlink drops the `--policy` argument at `:342-343` and lets
`artifact-budget` resolve its own default. It is not a row because the argument
exists only to work around `artifact-budget`'s `O_NOFOLLOW` policy read
(docstring, `:302-308`) and the default it falls back to resolves to the same
policy content — the operation continues with the same input, not a lesser one.

**What counts as a row.** A hit becomes a row when an **absence or a failure
makes the same operation continue with a lesser input, output or mechanism**. A
hit that refuses, that names a state rather than taking a branch, that points at
a branch inventoried elsewhere, that chooses among options with nothing absent,
or that degrades on a *budget* rather than on an absence, is excluded — and each
exclusion is a named class below rather than a silent omission.

**The adjudication, published rather than asserted.** Pass 1 returned **193**
hits across 42 files; pass 2 returned **70** across 29; together they are **209
distinct `file:line` hits**. Every one is accounted for:

| Disposition | Hits | A named example |
|---|---|---|
| Became (part of) one of the 66 rows | 81 | `ship-issue/SKILL.md:13` → A6 and B1 |
| Closed-set state vocabulary, not a branch | 41 | `workflow-state.py:129`, the literal `"owner_unavailable"` ledger field |
| Fail-closed refusal | 38 | `diff-scope.py:430`, "a missing answer is a hard error, never a fallback" |
| Cross-reference to a branch rowed elsewhere | 26 | `DIFF-REVIEW.md:16`, pointing at `SKILL.md`'s `command -v` check (E13) |
| Vocabulary outside the subject | 13 | `improve-codebase-architecture/LICENSE:23`, a change-note; `REVIEW-CONTRACT.md:88`, a rubric about the *reviewed product's* fallbacks |
| Default selection with nothing absent | 2 | `wayfind/SKILL.md:83`, "the user's named ticket, else the first frontier ticket" |
| Budget-driven degrade, not absence-driven | 8 | `ship-issue/SKILL.md:218`, "Degrade to the merge-delta check when ALL of these hold" — the full review is skipped because the diff is small, not because anything is missing |
| **Unaccounted** | **0** | — |

81 exceeds 66 because a row may span several hit lines and two rows may share
one. **The per-hit map is published in full** as
`.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/measured-ranges-and-adjudication.md § The adjudication, hit by hit`,
one line per hit in file-then-line order, so
every total above is re-derivable by counting the map, a reader can diff it
against their own re-run, and a misclassification is visible on the page. Four
of the 66 rows have **no** hit line at all — C3, C5, C6 and D4 — because
neither pass's vocabulary appears on those lines; each was found by reading the
surrounding file while adjudicating a different hit in it, and they are listed at
the end of the map so the two sides reconcile exactly.

The 66 rows are what survived that adjudication. It remains a keyword sweep over
prose plus one script read, so a fallback phrased entirely outside that
vocabulary, or buried in a script read only for its branches, would still be
missed. The count is a floor — but the floor is now checkable.

**What "silently" means in the verdicts below.** A branch is called silent when
it takes the lesser path without writing a diagnostic. `resolve-bindings` is
mixed: a missing config file is silent (`load_config`, lines 49-50), an
unreadable or unparseable one prints one line to stderr and still returns `{}`
(lines 53-55), and an invalid orchestration integer prints one line and keeps
exit status 0 (`positive_int_str`, lines 91-107, whose docstring states the
reason: "one bad optional orchestration key must not break binding resolution
for every skill"). The `Diagnostic at the fallback` column of `Per-site
inventory` carries this verdict for all 66 sites, so #61's "or silently fall
back" is answered per site rather than only for the helper.

## The removable cluster

#61's resolution comment names four families. All four exist in the live tree,
and each is named here with its concrete sites; the full per-site classification
is in `Per-site inventory`.

**Project binding.** One helper —
`home/common/agent-skills/scripts/resolve-bindings` — owns the family. It emits
14 `key=value` lines and fills thirteen of them (`repoRoot` is derived, not
resolved) through a three-rung ladder:
`.claude/skills.config.json` → auto-detection from local git metadata →
a `DEFAULTS` table (lines 26-37). Ten of the fourteen keys have no detection
rung at all and go straight from absent-config to a hardcoded default
(`specDir`, `planDir`, `integrationBranch`, `defaultBranch`, `branchPattern`,
`worktreePrefix`, `coAuthoredBy`, `unsetGithubToken`, `agentBudgetMinutes`,
`maxParallel`); three have one (`repoSlug`, `trackerKind`, `trackerCli`), and
`repoRoot` is derived. Seven `SKILL.md` files carry prose duplicating that ladder:
`ship-issue/SKILL.md:13`, `doc-grounded-questions/SKILL.md:12`,
`to-issues/SKILL.md:12`, `writing-plans/SKILL.md:11-13`, `research/SKILL.md:16`,
`design/SKILL.md:49`, and `ship-release/SKILL.md:24` — which does not call the
helper at all and instead restates the default set in prose. An eighth
duplication sits outside any `SKILL.md`: `from-issue/bindings.md:5-8` restates
the entire ladder — config, auto-detection, eight named defaults, and the
degrade-gracefully rule — as its own auxiliary file. Three further sites in the
family govern *optional* bindings rather than that ladder:
`ship-issue/SKILL.md:15`, `doc-grounded-questions/SKILL.md:12`,
`to-issues/SKILL.md:12` and `ship-release/SKILL.md:24` carry "never hard-fail on
a missing optional binding" (A8); `ship-issue/SKILL.md:17` makes an absent
`review.criticalPaths` mean "the `risky` label is the only always-full trigger"
(A10); and `ship-issue/REVIEW.md:16-18` drops the project-hints paragraph from
the merge-delta reviewer's checklist when `projectHints` is absent (A11). With
A1-A5 inside the helper, that is 5 (the helper rungs A1-A5) + 3 (the prose
duplications A6, A7, A9) + 3 (the optional-binding sites A8, A10, A11) = 11
sites in all.
`orchestrate-issues/SKILL.md:26-31` calls the helper but carries no fallback: it
forbids the adapter from copying either orchestration default, so it is not an
inventory site.

**Command.** Two shapes. Verify-command detection sniffs the manifest when the
config does not declare one — `ship-issue/SKILL.md:13`: "Verify commands: config,
else the manifest (`package.json` scripts, `*.slnx`/`*.sln` → `dotnet test`,
`Cargo.toml` → `cargo test`, `go.mod` → `go test`, `Makefile` → `make test`)".
`from-issue/bindings.md:6` sniffs the same manifests a second time
("npm scripts, dotnet, cargo, go, make"). Helper-binary resolution is the other —
`ship-issue/SKILL.md:222` and `codex-collaboration/DIFF-REVIEW.md:23-25` both
instruct the reader to use the full `~/.agents/bin/diff-scope` path "if the bare
name does not resolve", and both define a no-measurement outcome. Two branches
in the swept set literally probe for a command with `command -v`, and only one of
them falls back: `codex-collaboration/SKILL.md:65-68`'s
`command -v codex-companion` pre-flight degrades to the native reviewer flow,
while `sdd/scripts/task-brief:25-28`'s `command -v artifact-budget` prints to
stderr and exits 2. The second is a fail-closed refusal, so it is a contrasting
case rather than an inventory site.

**Tracker.** `resolve-bindings` `detect_tracker` (lines 77-82) maps an origin URL
to `github`/`gh`, `gitlab`/`glab`, or `none`/`""`, and `origin_url` (lines 59-69)
returns `""` on a timeout, an `OSError`, or a non-zero git exit — which silently
produces `trackerKind=none` and an empty `repoSlug`. Downstream, `kind: none` is
a first-class degraded mode: `ship-issue/SKILL.md:15` skips every issue/PR/CI
step, `to-issues/SKILL.md:18` presents the breakdown without publishing, and
`ship-release/SKILL.md:30` replaces Phases 2-4 with a local `git merge --no-ff`.
`ship-release/SKILL.md:28` and `ship-issue/SKILL.md:207` each re-derive
`repoSlug` from the origin URL when config does not set it, and
`wayfind/DISCIPLINE.md:49` falls back to a body convention on a tracker with no
native blocking relationship.

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
grounding step silently." That context-map ladder, or its no-map branch, is
restated in five further places — `from-issue/REVIEW-CONTRACT.md:39`,
`sdd/conformance-reviewer-prompt.md:23` and `grill-with-docs/CONTEXT-FORMAT.md:29`
carry the ladder, `codex-collaboration/PLAN-REVIEW.md:36-47` carries both, and
`grill-with-docs/CONTEXT-FORMAT.md:133` carries the no-map branch alone. Eight
more sites complete the family without restating that ladder:
`ship-release/CHANGELOG.md:65` (ADR links), `ship-issue/CONSOLIDATE.md:28`
(a learning whose destination doc is absent), `ship-issue/CONSOLIDATE.md:33`
(the ADR home: the owning area's `adr/`, else `system`, else the legacy
`docPaths.adrDir`), `ship-issue/CONSOLIDATE.md:38` (the grilling skill's format
references), `ship-release/SKILL.md:71` (the grounding skill itself
unavailable), the two standards rungs —
`doc-grounded-questions/SKILL.md:24` with `REFERENCE.md:41-45` and
`from-issue/REVIEW-CONTRACT.md:59` — and `doc-grounded-questions/SKILL.md:18`,
the rule governing the whole pass. Six sites named earlier in this paragraph are
the ladders themselves — the context map (D1), its no-map fallback (D2),
decision logs (D3), architecture (D5), `grill-with-docs`'s layout detection (D6)
and `to-issues`'s grounding step (D7) — so 6 + 5 + 8 = 19, which is why doc
discovery is the largest of the four families, at 19 of the 46 in-cluster
sites.

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
  hard error, never a fallback (issue #21's D7)";
  `artifact_budget.py:112,123,233,241,250` raises on every unopenable,
  unreadable or concurrently-modified artifact;
  `sdd/scripts/task-brief:25-28` probes `command -v artifact-budget` and, on a
  miss, writes "artifact-budget is not available" to stderr and exits 2 rather
  than proceeding without a budget check;
  `handoff/SKILL.md:51-52` requires "stop failed rather than copy unmeasured
  bytes" and `handoff/SKILL.md:85-86` forbids a "prose fallback". These are
  fail-closed refusals inside the same helper set and are excluded for the same
  reason.

## Per-site inventory

66 sites, found by the sweep described in `## Method and evidence base`. **37**
are classified `removable-after-validated-onboarding-contract` — the branch's
input is a repository property a contract could guarantee. **29** are classified
`unavoidable-portability` — the branch's input is a property of the machine, the
harness, or the forge, which no repository onboarding contract reaches. Every
site is a fallback in the sense fixed above; fail-closed refusals and declared
runtime alternatives are excluded.

The fourth column answers the other half of #61's question — which branches
*silently* fall back. **56** of the 66 emit nothing at all; **8** are announced,
because the source requires the fallback to be recorded, reported or disclosed
(B3, C3, C5, E3, E6, E13, E14, E16); and **2** write one line to stderr and continue
at exit status 0 (A5 always, A3 only for an unreadable or unparseable config
file). Silence is the default in this tree, not the exception.

### Shared skills and helpers

| # | Site | Branches on | Diagnostic at the fallback | Classification |
|---|---|---|---|---|
| A1 | `scripts/resolve-bindings:26-37,132-160` — `config.get(k) or DEFAULTS[k]` for the ten `DEFAULTS`-backed keys | absent config key | silent | removable-after-validated-onboarding-contract |
| A2 | `scripts/resolve-bindings:40-44,116-118` — `find_repo_root` returns `start` when no `.git` and no config is found | invocation directory | silent | unavoidable-portability |
| A3 | `scripts/resolve-bindings:47-56` — `load_config` returns `{}` on a missing file, on `OSError`/`JSONDecodeError`, or on a non-dict top level | config file presence and validity | silent, except one stderr line on an unreadable or unparseable file | removable-after-validated-onboarding-contract |
| A4 | `scripts/resolve-bindings:85-88` — `as_bool_str` substitutes the default for any non-bool | config value type | silent | removable-after-validated-onboarding-contract |
| A5 | `scripts/resolve-bindings:91-107` — `positive_int_str` substitutes the default for a non-positive or non-int; exit status stays 0 | config value type | one stderr line | removable-after-validated-onboarding-contract |
| A6 | `skills/{ship-issue:13, doc-grounded-questions:12, to-issues:12, writing-plans:11, research:16, design:49}/SKILL.md` — a helper-missing branch in six files, worded three ways: `doc-grounded-questions:12` and `to-issues:12` say "helper missing → read the config and apply the same defaults"; `ship-issue:13` says "Helper missing → read the config and apply the defaults it documents."; `writing-plans:11-12`, `research:16` and `design:49` say "helper missing → `.claude/skills.config.json`, default `.claude/specs`" (`.claude/plans` in `writing-plans`) | presence of `~/.agents/bin/resolve-bindings` on the machine | silent | unavoidable-portability |
| A7 | `skills/ship-release/SKILL.md:24` — reads the config directly and restates the whole default set in prose, calling no helper | absent config key | silent | removable-after-validated-onboarding-contract |
| A8 | `skills/{ship-issue:15, doc-grounded-questions:12, to-issues:12}/SKILL.md`, `skills/ship-release/SKILL.md:24` — "never hard-fail on a missing optional binding"; "skip any configured-but-absent doc path silently" | declared-but-absent path | silent, and says so | removable-after-validated-onboarding-contract |
| A9 | `skills/from-issue/bindings.md:5-8` — the whole ladder duplicated in an auxiliary file: config, auto-detection, eight named defaults, degrade-gracefully | absent config key | silent, and says so (line 8) | removable-after-validated-onboarding-contract |
| A10 | `skills/ship-issue/SKILL.md:17` — optional `review.criticalPaths` globs; "absent = the `risky` label is the only always-full trigger" | absent config key | silent | removable-after-validated-onboarding-contract |
| A11 | `skills/ship-issue/REVIEW.md:16-18` — the merge-delta reviewer's checklist takes the project-hints review paragraph "when `projectHints` exists (a directory → its `review.md`; a single file → itself; omit silently when absent)": absent binding → the same review runs with one checklist input fewer | absent config key | silent, and says so | removable-after-validated-onboarding-contract |
| B1 | `skills/ship-issue/SKILL.md:13` — verify commands from config, else manifest sniffing across five manifest kinds | absent `verify` config | silent | removable-after-validated-onboarding-contract |
| B2 | `skills/ship-issue/SKILL.md:222` — `~/.agents/bin/diff-scope` by full path when the bare name does not resolve; no measurement → run the full two-axis review | helper on PATH | silent | unavoidable-portability |
| B3 | `skills/codex-collaboration/DIFF-REVIEW.md:23-25,59-63` — same helper; no measurement → dispatch as under-budget | helper on PATH | announced — "report `unmeasured` to the calling controller" | unavoidable-portability |
| B4 | `skills/from-issue/bindings.md:6` — a second manifest-sniff site (npm scripts, dotnet, cargo, go, make) | absent `verify` config | silent | removable-after-validated-onboarding-contract |
| C1 | `scripts/resolve-bindings:77-82,123-126` — `detect_tracker` derives kind and CLI from the origin URL when config omits `issueTracker` | absent config key | silent | removable-after-validated-onboarding-contract |
| C2 | `scripts/resolve-bindings:59-69` — `origin_url` returns `""` on `OSError`, `TimeoutExpired`, or non-zero git exit, yielding `trackerKind=none` | git availability and remote state | silent | unavoidable-portability |
| C3 | `skills/to-issues/SKILL.md:18` — `kind: none` presents the breakdown without publishing; neither config nor remote resolves → ask exactly one question | absent tracker binding | announced — the slices are handed to the user, and an unresolved tracker raises a question | removable-after-validated-onboarding-contract |
| C4 | `skills/ship-issue/SKILL.md:15` — `issueTracker.kind=none` skips every issue/PR/CI step | absent tracker binding | silent | removable-after-validated-onboarding-contract |
| C5 | `skills/ship-release/SKILL.md:30` — no forge → local `git merge --no-ff`, tag the local result, skip PR/CI/Release | absent tracker binding | announced — "report the merge SHA + tag" | removable-after-validated-onboarding-contract |
| C6 | `skills/ship-release/SKILL.md:28` — derive `repoSlug` from `git remote get-url origin` when config does not set it | absent config key | silent | removable-after-validated-onboarding-contract |
| C7 | `skills/ship-release/SKILL.md:75` — `GH_PREFIX` is `unset GITHUB_TOKEN && ` or empty per `unsetGithubToken`; `glab` verb translation when `cli == "glab"` | absent config key | silent | removable-after-validated-onboarding-contract |
| C8 | `skills/to-issues/SKILL.md:87-89` — GitLab native blocking links are Premium/Ultimate; on the free tier the body's "Blocked by" section is the record | forge subscription tier | silent | unavoidable-portability |
| C9 | `skills/from-issue/bindings.md:6,12,14` — tracker auto-detection, the `kind=none` skip, and the `unsetGithubToken` prefix, all restated in the auxiliary file | absent tracker binding | silent | removable-after-validated-onboarding-contract |
| C10 | `skills/ship-issue/SKILL.md:207` — `repoSlug` from config, else the origin URL, for every issue URL it writes | absent config key | silent | removable-after-validated-onboarding-contract |
| C11 | `skills/wayfind/DISCIPLINE.md:49` — a tracker without native blocking falls back to a body convention | forge feature set | silent | unavoidable-portability |
| C12 | `skills/from-issue/SKILL.md:465` — "derive the slug from `repoSlug` if configured, else `git remote get-url origin`" for every URL the lifecycle writes | absent config key | silent | removable-after-validated-onboarding-contract |
| D1 | `skills/doc-grounded-questions/SKILL.md:20` — context map: `docPaths.contextMap` → `docs/CONTEXT-MAP.md` → legacy root `CONTEXT-MAP.md` → no map | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D2 | `skills/doc-grounded-questions/REFERENCE.md:26-29` — no map → `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md`, or a README domain section | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D3 | `skills/doc-grounded-questions/REFERENCE.md:36-38` — decision log: area `adr/` dirs, else `docPaths.adrDir`, else `docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/` | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D4 | `skills/doc-grounded-questions/SKILL.md:24` with `REFERENCE.md:41-45` — project standards deltas are read only from `docPaths.standards`; there is no unconfigured discovery rung. The configured path is "a `docs/standards/` directory with a README index … or a single `CONTRIBUTING.md` / `docs/coding-standards.md` in older repos" — a rung on the *shape* of a configured path, not on discovery; D19 is its restatement | shape of the configured standards path (shards directory vs legacy single doc) | silent | removable-after-validated-onboarding-contract |
| D5 | `skills/doc-grounded-questions/SKILL.md:26` — architecture: `docPaths.architecture`, else `ARCHITECTURE.md` / `docs/architecture.md` / a README section | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D6 | `skills/grill-with-docs/SKILL.md:38-41` — three-tier layout detection: standard tree, legacy conventions, then `docPaths` overrides | repository doc layout | silent | removable-after-validated-onboarding-contract |
| D7 | `skills/to-issues/SKILL.md:28` — glossary and ADR grounding, "If those docs are absent, skip this grounding step silently" | absent file | silent, and says so | removable-after-validated-onboarding-contract |
| D8 | `skills/ship-release/SKILL.md:71` — `doc-grounded-questions` unavailable → read the configured doc directly when it exists | sibling skill installed on the machine | silent | unavoidable-portability |
| D9 | `skills/from-issue/REVIEW-CONTRACT.md:39` — the same context-map ladder, restated in the plan-review grounding contract | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D10 | `skills/sdd/conformance-reviewer-prompt.md:23` — the same ladder again, in the conformance reviewer's prompt | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D11 | `skills/codex-collaboration/PLAN-REVIEW.md:36-47` — the same ladder, plus "Only when the project has no map, fall back to the `docPaths.{context,standards,architecture}` whole-doc paths" | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D12 | `skills/grill-with-docs/CONTEXT-FORMAT.md:133` — "Readers fall back to reading the whole file when no `CONTEXT-MAP.md` exists" | absent file | silent | removable-after-validated-onboarding-contract |
| D13 | `skills/ship-issue/CONSOLIDATE.md:33` — ADR home: the owning area's `adr/`, else `system`, else legacy `docPaths.adrDir` | absent config key and absent directory | silent | removable-after-validated-onboarding-contract |
| D14 | `skills/ship-issue/CONSOLIDATE.md:38` — the grilling skill's `CONTEXT-FORMAT.md` / `ADR-FORMAT.md` references when shipped beside it, "if absent, match the destination doc's existing neighbours" | sibling skill file installed on the machine | silent | unavoidable-portability |
| D15 | `skills/grill-with-docs/CONTEXT-FORMAT.md:29` — prefer `docPaths.contextMap`/`docPaths.context` when set, else the two surviving legacy layouts | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D16 | `skills/ship-release/CHANGELOG.md:65` — ADR links from the area tree, else `docPaths.adrDir` and that repo's own id form, else skip when the repo keeps no ADRs | absent config key and absent directory | silent | removable-after-validated-onboarding-contract |
| D17 | `skills/doc-grounded-questions/SKILL.md:18` — the rule governing the whole grounding pass: "read whichever sources actually exist; skip absent ones silently" | absent file | silent, and says so | removable-after-validated-onboarding-contract |
| D18 | `skills/ship-issue/CONSOLIDATE.md:28` — a learning whose mapped destination doc is absent is dropped and consolidation continues without it | absent config key and absent file | silent | removable-after-validated-onboarding-contract |
| D19 | `skills/from-issue/REVIEW-CONTRACT.md:59` — the plan reviewer checks test-fixture conventions against "the project's standards shards (or legacy coding-standards doc)": no shards → the older single-doc form that `REFERENCE.md:43-45` names, and the pass continues from the coarser source | absent file | silent | removable-after-validated-onboarding-contract |
| E1 | `skills/worktrees/SKILL.md:37` — "No native worktree tool:" → `git worktree add` | harness tool surface | silent | unavoidable-portability |
| E2 | `skills/ship-issue/SKILL.md:237-241` — `codex-collaboration`'s `diff-review` unavailable → native `reviewer` dispatch (`id=ship-issue-full-correctness-fallback`) | `codex-collaboration`'s `diff-review` capability on the machine | silent by design — `REVIEW.md:43-44`, "ship-issue records no reviewer identity" | unavoidable-portability |
| E3 | `skills/from-issue/standards-review.md:18-20` — plan review goes to `codex-collaboration` when available, else a native reviewer. `codex.planReview.enabled=false` is a declared configuration choice, not a fallback, and only the unavailable branch is inventoried | `codex-collaboration` skill installed on the machine | announced — line 31 records "whether fallback was used" in the plan | unavoidable-portability |
| E4 | `skills/from-issue/SKILL.md:180` — "Never hard-fail on a missing sibling" → run the phase inline | sibling skill installed on the machine | silent | unavoidable-portability |
| E5 | `skills/ship-issue/SKILL.md:359` — absent sibling skills degrade to no-ops | sibling skill installed on the machine | silent | unavoidable-portability |
| E6 | `skills/improve-codebase-architecture/SKILL.md:32` — host cannot dispatch a sub-agent → perform the scan inline | harness agent-dispatch capability | announced — "disclose that fallback" | unavoidable-portability |
| E7 | `skills/doc-grounded-questions/SKILL.md:39` — grounding cache at `$(git rev-parse --git-dir)/GROUNDING.md`; outside a git repo, fall back to the platform temp dir | invocation directory | silent | unavoidable-portability |
| E8 | `skills/ship-issue/SKILL.md:121` — `doc-grounded-questions` unavailable → read whichever declared `docPaths` exist | sibling skill installed on the machine | silent | unavoidable-portability |
| E9 | `skills/from-issue/REVIEW-CONTRACT.md:38` — the same, in the plan-review grounding contract | sibling skill installed on the machine | silent | unavoidable-portability |
| E10 | `skills/sdd/SKILL.md:51` — correctness axis via `codex-collaboration` when available, else `reviewer` on Opus/high | `codex-collaboration` skill installed on the machine | silent | unavoidable-portability |
| E11 | `skills/sdd/correctness-reviewer-prompt.md:4` — a whole prompt file that exists only for when `codex-collaboration` is unavailable | `codex-collaboration` skill installed on the machine | silent | unavoidable-portability |
| E12 | `skills/codex-collaboration/SKILL.md:38-40` — the capability-fallback declaration: this skill or the `codex:codex-reviewer` plugin agent unavailable → the native reviewer flow | skill and plugin agent installed on the machine | silent | unavoidable-portability |
| E13 | `skills/codex-collaboration/SKILL.md:65-68` — `command -v codex-companion` pre-flight; missing → the native reviewer flow. The only `command -v` probe in the swept set that falls back rather than refusing (`skills/sdd/scripts/task-brief:25-28` is the other, and it exits 2) | runtime binary on PATH | announced — "record it as such" | unavoidable-portability |
| E14 | `skills/codex-collaboration/SKILL.md:119-141` — one-time native standards-review fallback on a real Codex failure (executable missing, authentication unavailable, `CODEX_REVIEW_FAILURE:`, or an empty/malformed result); explicitly never on concurrency | Codex runtime health | announced — "Record the concrete failure class and that Claude fallback was used" | unavoidable-portability |
| E15 | `skills/doc-grounded-questions/SKILL.md:59` — "Sibling skills are referenced opportunistically — where one is not installed, apply the same pass to whatever flow you are in" | sibling skill installed on the machine | silent | unavoidable-portability |
| E16 | `skills/sdd/final-review.md:29` — correctness axis via `codex-collaboration` when available; "Unavailable → use the Opus/high native reviewer selected in correctness-reviewer-prompt.md. Either way the axis is never skipped" | `codex-collaboration` skill installed on the machine | announced — line 31 records the reviewer identity (`Codex` / `native` / `fallback` + failure class) in the ledger | unavoidable-portability |
| E17 | `skills/sdd/fix-loop.md:18` — rescue round: "Codex unavailable → the same tier", reframed for a fresh-context implementer | rescue plugin agent installed on the machine | silent | unavoidable-portability |
| E18 | `skills/ship-issue/REVIEW.md:31-37` — "sdd templates unavailable → still use the two isolated native dispatches in SKILL.md", with the two rubrics pasted inline | sibling skill installed on the machine | silent by design — `REVIEW.md:43-44`, "ship-issue records no reviewer identity" | unavoidable-portability |
| E19 | `skills/from-issue/ship-handoff.md:60-62` — "## Inline fallback (no ship-issue skill)": push, open the PR and run the same full-review tier inline | sibling skill installed on the machine | silent | unavoidable-portability |
| E20 | `skills/sdd/correctness-reviewer-prompt.md:115-116` and `skills/sdd/conformance-reviewer-prompt.md:111-112` — "a dispatcher without the sdd scripts … omits them and the reviewer uses the body's fallback": the axis runs without a validated manifest root or its four metrics, and the reviewer fetches the range itself (`skills/ship-issue/REVIEW.md:28` is the dispatcher side) | sdd scripts installed on the machine | silent | unavoidable-portability |

Paths in the table are relative to `home/common/agent-skills/`, except
`skills/codex-collaboration/`, which lives under `home/common/claude-code/`
(one of the two Claude-only skills).

**Why the helper-, sibling- and runtime-presence sites — A6, B2, B3, D8, D14,
E2-E6 and E8-E20, called *the presence set* below — are portability and not
contract.** `~/.agents/bin/` is user scope — an absolute path outside every
repository, populated by `home/common/agent-skills/default.nix:52-102` as nine
home-manager symlinks into the Nix store, with `home.sessionPath` adding it to
PATH (line 161). `ls ~/.agents/bin/`, run 2026-09-02, returns `agent-evidence`,
`agent-model-matrix`, `artifact-budget`, `context-map-lint`, `diff-scope`,
`resolve-bindings`, `review-package`, `sdd-workspace`, `workflow-state` — so the
three helper-binary branches, A6, B2 and B3, do not fire here. That listing
settles nothing about the rest of the set, which turns on installed skills, on a
plugin agent and on the Codex runtime, so three further reads were taken the same
day. `ls ~/.claude/skills/` returns nineteen entries, among them every sibling
this table names — `codex-collaboration`, `doc-grounded-questions`,
`grill-with-docs`, `sdd`, `ship-issue` — and `ls ~/.claude/skills/sdd/scripts/`
returns `review-package`, `sdd-workspace`, `task-brief`, so D8, D14, E2-E5,
E8-E11, E15, E16 and E18-E20 do not fire either.
`ls "$(jq -r '.extraKnownMarketplaces["nix-codex"].source.path' ~/.claude/settings.json)"/plugins/codex/agents/`
returns `codex-rescue.md` and `codex-reviewer.md`, which with that skill listing
covers E12's two conditions, and `codex-rescue.md` is the rescue plugin agent
`fix-loop.md:10-11` dispatches, so E17 does not fire either. `command -v
codex-companion` returns
`/etc/profiles/per-user/anis/bin/codex-companion`, covering E13. Two rows lie
outside what any presence read can settle, and nothing is claimed for them here:
E6 branches on the harness's own sub-agent dispatch capability, and E14 on Codex
runtime health at the moment of invocation. That these branches are nonetheless live is
stated by the sources themselves: `DIFF-REVIEW.md:63-64` records that
"`diff-scope` reaches `~/.agents/bin` only after a rebuild, so absence is a real
state on a machine that has this skill", and
`home/common/agent-skills/default.nix:87-92` records an observed incident — "a
ship-issue cleanup wrongly retained a worktree after concluding no producer
existed on the machine" — plus a second at lines 157-160, "exit 127 — the failure
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
2. **Two of the three exhaust at least one doc-discovery ladder; only nix-config
   exhausts all four, and Nodo exhausts none.** A **probe** here is one
   filesystem existence check of one candidate path, counted only for rungs the
   adapter's config does not already resolve; a ladder is **exhausted** when
   every one of its filesystem candidates misses. Each ladder's candidates, from
   the rows that own them:

   - **context map** (D1) — `docPaths.contextMap`, `docs/CONTEXT-MAP.md`, root
     `CONTEXT-MAP.md`: **2** probes unconfigured.
   - **legacy glossary** (D2), entered only when no map resolved —
     `docPaths.context`, `CONTEXT.md`, `GLOSSARY.md`, `DOMAIN.md`, or a
     top-of-`README` domain section: **3** probes unconfigured. The README rung
     is a judgement about a file's *contents*, not an existence check, so it is
     excluded from the count and from the exhaustion verdict; a README that
     might carry such a section exists in nix-config and Argus and not in Nodo.
   - **decision log** (D3) — `docs/areas/` first, else `docPaths.adrDir`,
     `docs/adr/`, `docs/adrs/`, `docs/decisions/`, `adr/`: **1** probe when
     `docs/areas/` hits, **5** when it does not.
   - **architecture** (D5) — `docPaths.architecture`, `ARCHITECTURE.md`,
     `docs/architecture.md`, or a README section: **2** probes unconfigured, the
     README rung excluded on the same ground as above.

   Walked on 2026-09-02, each cell `probes/hits`:

   | Adapter | Context map | Legacy glossary | Decision log | Architecture | Probes | Hits | Exhausted |
   |---|---|---|---|---|---|---|---|
   | nix-config | 2/0 | 3/0 | 5/0 | 2/0 | **12** | **0** | all four |
   | Argus | 1/1 | not entered | 1/1 | 2/0 | **4** | **2** | architecture only |
   | Nodo | config rung, 0 probes | not entered | 1/1 | config rung, 0 probes | **1** | **1** | none |

   nix-config declares no `docPaths` and has no `docs/` directory at all, so
   every candidate misses. Argus declares nothing either, but
   `docs/CONTEXT-MAP.md` and `docs/areas/` (which holds 12 area `adr/`
   directories) exist, so its glossary ladder is never entered — a map resolved —
   and only the architecture ladder runs out. Nodo's config declares
   `docPaths.contextMap` and `docPaths.architecture`, so those two resolve
   without probing, the glossary ladder is never entered, and its one
   decision-log look hits. **Nodo exhausts no ladder at all.** All seven of
   Nodo's declared `docPaths` resolve to existing paths.

3. **Argus's project standards are unreachable through the grounding pass.**
   `docs/standards/README.md` exists in Argus, but D4 above has no unconfigured
   discovery rung — project deltas are read only from `docPaths.standards`, and
   Argus declares no config. This is a gap, recorded here as observed; it is not
   a fallback site and is not counted among the 66.

**Drift against the resolution summary, per the drift rule.**

- *As-of-decision claim:* #61's resolution comment says "The clearest removable
  cluster is project binding, command, tracker, and doc discovery."
- *As observed (2026-09-02, by reading each cited line and running
  `resolve-bindings` against all three checkouts):* the four families hold 46 of
  the 66 sites, but only **37** of those 46 are removable by a repository
  onboarding contract. Nine sites inside the named cluster — A2, A6, B2, B3, C2,
  C8, C11, D8, D14 — branch on the machine, the harness or the forge, not on the
  repository.
- *Reconciliation:* the summary holds at the level of families and is refined,
  not contradicted, at the level of sites. Naming a family removable does not make
  every branch inside it removable; a contract that declared every key in
  `.claude/skills.config.json` would still leave those nine standing.

## Attributable prompt size and repeated execution cost

Unit: bytes of UTF-8 Markdown source.
Method: every measured span is one `sed -n … | wc -c` invocation over exactly the
line ranges the site table cites, and **all of them are published** under
`.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/measured-ranges-and-adjudication.md § The measured ranges`,
so every cell in the table is reproducible without
trusting this document. Each physical line is attributed to exactly one family
and never counted twice, so where one line carries two families' sites the
second family is understated: `ship-issue/SKILL.md:13` carries A6 and B1 and
`:15` carries A8 and C4, both counted under project binding, and
`from-issue/bindings.md:6` carries A9, B4 and C9, counted under project binding.
Whole lines are the smallest unit, which overstates wherever a fallback is one
clause of a longer line (see `## Unverified inheritance`, item 3). Denominator:
the 29 files that carry these sites' prose, `wc -c` -> **280,694 bytes**.
`resolve-bindings` is not among them: it carries seven sites and zero prompt
bytes, for the reason given below the table.

| Cluster | Sites | Bytes | Share of the 29 files |
|---|---|---|---|
| Project binding | 11 | 4,242 | 1.5% |
| Command | 4 | 1,636 | 0.6% |
| Tracker | 12 | 3,173 | 1.1% |
| Doc discovery | 19 | 6,955 | 2.5% |
| **Four families, subtotal** | **46** | **16,006** | **5.7%** |
| Agent capability (outside the four) | 20 | 8,322 | 3.0% |
| **All 66 sites** | **66** | **24,328** | **8.7%** |

**Seven of the 66 sites contribute zero prompt bytes** and so contribute nothing
to the cells above. A1-A5, C1 and C2 live in
`home/common/agent-skills/scripts/resolve-bindings`, which the model executes
rather than reads: 5,517 bytes of Python in total, of which lines 24-107 (the
`DEFAULTS` table and the three coercion helpers) are 2,535 bytes and lines
123-160 (the binding assembly) are 1,623. Their cost is execution, measured
below, not prompt.

A token figure is **an estimate**: at roughly 4 bytes per token for English
Markdown, 24,328 bytes is on the order of **6,000 tokens** — labelled an estimate
because no tokeniser was run against these files. The byte figures are
measurements.

Not all of these bytes are resident at once. **14,613** of the 24,328 sit in
`SKILL.md` files, which load when the skill is invoked; **9,715** sit in sixteen
auxiliary files (`from-issue/{bindings,REVIEW-CONTRACT,standards-review,ship-handoff}.md`,
`doc-grounded-questions/REFERENCE.md`, `grill-with-docs/CONTEXT-FORMAT.md`,
`sdd/{conformance-reviewer-prompt,correctness-reviewer-prompt,final-review,fix-loop}.md`,
`ship-issue/{CONSOLIDATE,REVIEW}.md`, `ship-release/CHANGELOG.md`,
`wayfind/DISCIPLINE.md`, and `codex-collaboration/{DIFF-REVIEW,PLAN-REVIEW}.md`),
which load only when a step points at them.

### The measured ranges

Every `sed -n … | wc -c` invocation behind the byte table above is bulk evidence and
lives in this package's evidence member,
`.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/measured-ranges-and-adjudication.md`,
under the heading `## The measured ranges`. It publishes every measured range, one
line per invocation, grouped by the same clusters the byte table uses, so every cell
in that table is reproducible without trusting this document. It carries records
only; the unit, the method, the denominator, the token estimate and the
resident-versus-loaded split stay here.

### The adjudication, hit by hit

The per-hit map is bulk evidence and lives in the same evidence member,
`.claude/specs/2026-08-20-agent-fallback-inventory-research.evidence/measured-ranges-and-adjudication.md`,
under the heading `## The adjudication, hit by hit`. It lists all 209 distinct
`file:line` hits in file-then-line order, each with its disposition, and ends with the
four rows that carry no hit line, so every total in the disposition table under
`## Method and evidence base` is re-derivable by counting the map. It carries records
only; the disposition table, its totals and what the adjudication does and does not
license stay here.

### Repeated execution cost

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
  relative to the review it gates. `command -v codex-companion` (E13) is
  described by its own source as "one sub-second call"; no separate timing was
  taken for either.
- **Tracker:** no additional process. Detection is the same `git remote get-url`
  already counted in the 40 ms, and the `kind: none` branches are prose read by
  the model, not executed.
- **Doc discovery:** no subprocess at all. The repeated cost is model turns spent
  on filesystem probes — 12 for nix-config, 4 for Argus, 1 for Nodo, the counts
  the ladder walk in `The three live adapters` publishes cell by cell. The
  per-turn cost of a probe has **no answer in the sources read**;
  this evidence base contains no harness instrumentation, and none was
  fabricated.

## What this document does not decide

Per #61's own instruction — "Do not decide removal policy" — and C61.5, this
document decides nothing. Specifically it does **not** decide:

- whether any of the 37 `removable-after-validated-onboarding-contract` sites
  should actually be removed, nor in what order, nor behind what evidence. Note
  that this is not an open question in the tracker: #71's resolution (closed)
  settles a strict cutover that will "delete static binding, command, tracker,
  branch, document, hint, and tool discovery/default ladders that the validated
  contract replaces", serialized `nix-config → Nodo → Argus`. That decision is
  #71's, taken after this inventory's ticket — #61 closed `2026-08-20T09:25:58Z`,
  #71 `2026-08-20T19:22:27Z` — and nothing here ratifies, refines or re-opens
  it;
- what the validated onboarding contract makes required versus optional, or what
  happens when a repository violates it. #69's resolution settles that too — one
  conformance engine, closed purposes, one repair route per reason code — and
  this document neither restates nor evaluates it; it is why every removable
  verdict here is conditional (`## Unverified inheritance`, item 2);
- whether any of the 29 `unavoidable-portability` sites should become a
  **fail-closed refusal** with a repair route, or a **declared runtime
  alternative**. #69's "no fallback is permitted for ... missing tool/trust/
  credential" bears on several of them, but mapping this inventory's 29 sites
  onto that rule is an act of policy application and is not performed here;
- whether *the presence set* — enumerated once, in `Per-site inventory`, so the
  two mentions cannot drift apart — should be addressed by a machine bootstrap
  contract rather than a repository one, though the evidence above shows a
  repository contract cannot reach them;
- what Argus should declare, or whether it should declare anything at all. Its
  unreachable `docs/standards/README.md` is recorded as an observation, not as a
  defect to fix here.
