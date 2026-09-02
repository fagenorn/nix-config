# Recovered wayfind research findings — content contract for the four documents (issue #115)

## Problem

The resolution comments of #60, #61, #62 and #80 each link an "Attached findings"
document under `.claude/specs/`. None of the four paths has ever existed on any
git ref (`git log --all -- <path>` returns zero commits for all four), and the
content is unrecoverable from transcripts. Four settled decisions therefore rest
on documents nobody can open, and three downstream places depend on that:

- #71 Stage 0 makes "commit the three findings attached to #60, #61 and #62 at
  their current `.claude/specs/` paths" a hard precondition for nix-config's
  adoption plan to reach `ready`.
- #79's accepted prototype records "three untracked research specs" as one of
  its two non-question blockers.
- #84 and #88 are grounded on the release-seam facts #80 attaches.

Separately, #86's resolution comment states its prototype "was never pushed —
it lives in the local worktree". That is false: `git ls-remote origin` returns
`worktree-prototype-release-transactions` at `dc98ba9b6bafaf7b5373cc7595ef79a5526846d1`.

This spec fixes **what the four recovered documents must contain**, claim by
claim, so a plan can be written against it and the four acceptance criteria can
be verified mechanically rather than impressionistically. It does not write the
documents and does not do their research.

## Solution

One shared **recovered-findings contract** (§ Document contract) plus four
per-document **coverage obligations** (§ Coverage obligations), each expressed as
numbered claim IDs. Every recovered document carries a `## Coverage of the
resolution summary` table with four columns: the claim ID from this spec, a
one-line restatement of the claim, the claim's source, and the section of that
same document **package** which discharges it — the root when the discharging
heading is there, and `<member repo-relative path> § <heading text>` when D22's
decomposition moved it to an evidence member. The restatement keeps the document readable
on its own — no reader should have to open this spec to learn what `C60.3`
means — while the ID keeps verification a `grep`. That table is the
verification seam: coverage becomes a lookup, not a reading.

Three of the four (#60, #61, #62) are re-derived from their in-ticket
conclusions plus the live tree. The fourth (#80) is re-derived from primary
sources in all three fleet repositories (per D6), and additionally carries six
seams the original omitted, immutable prototype references, and the #86
correction.

## Document contract

Every one of the four documents obeys all of the following. Deviation in any
single document is a defect.

### Path, name and date

- The path is exactly the path its resolution comment links. Non-negotiable —
  AC4 is link resolution. The four paths are the four named in #115.
- The `2026-08-20` prefix in each filename is the **decision date** of its
  ticket, not the authorship date of the file. Nothing renames these files.

### Required front matter, in this order

1. `# <Title>` — a sentence naming the inventory, not the ticket number alone.
2. `**Durability: committed** (Git owns this file's history from this commit
   forward.)` — per D2. #60, #61 and #62 already anticipated the commit; the
   #80 document additionally carries one clause noting that its ticket asked
   for an `attached` file and this is a `committed` one.
3. A `## Provenance` block (per D1) that states, explicitly and without
   euphemism:
   - this document is a **re-derivation authored 2026-09-02 under issue #115**,
     not a restoration of the 2026-08-20 original;
   - the original was never committed to any git ref and its content is
     unrecoverable — so nothing here is a recovered byte, and no claim here may
     be cited as evidence of what the original said;
   - the conclusions it is obligated to satisfy are those of the resolution
     comment of issue #N (linked), enumerated in its coverage table;
   - the filename date is the ticket's decision date while the authorship date
     is 2026-09-02, and the two differ deliberately.
4. An explicit **evidence-gate declaration** (per D4): "Schema-version-1
   `research-observations` / `agent-evidence` gate: not invoked", with the
   one-sentence reason that the document asserts repository-state inventory,
   not a live-availability or blocking conclusion. This mirrors the precedent
   at `.claude/specs/2026-08-16-codex-worker-death-research.md`.
5. `## Research question` — the ticket's question verbatim.

### Citation form (per D3)

Every substantive claim names the primary source that owns it:

| Source class | Required citation form |
|---|---|
| File in this repository | repo-relative path; symbol or option name when the claim is about one |
| File in a fleet checkout | repository name + repo-relative path, plus the checkout's observed `HEAD` sha and the observation date |
| Prototype artifact | full 40-character commit sha + the branch on `origin` that reaches it |
| Settled decision | issue number; the decision text, never a paraphrase presented as evidence |

A claim inherited from the resolution summary but **not** re-verified against a
primary source is marked as such inline and moved into the document's
"unverified inheritance" list. Silence is not permitted.

### Drift rule (per D5)

Where today's tree contradicts a resolution-summary claim, the document records
all three of: (a) the as-of-decision claim, as the coverage obligation; (b) the
as-observed fact with its observation date and the command that produced it;
(c) an explicit reconciliation sentence. It never silently restates a stale
claim as current, and never silently drops one. At least one such reconciliation
is already known to be required — see C62.2.

### Non-decision discipline

All four tickets forbid choosing the architecture. Each recovered document ends
with a `## What this document does not decide` section naming the decision that
was deliberately left open, so a later reader cannot mistake an inventory for a
ruling.

### Proportionality (per D8)

No `artifact-budget` kind governs research findings, so the plan must not run
`artifact-budget` against these four. The governing rule instead is the-bar's
*Token economy*: each document is as long as its coverage obligation and its
citations require and no longer. Padding, restated tables, and re-explained
ticket context are defects.

## Coverage obligations

The claim IDs below are the coverage floor. Each recovered document's coverage
table cites these IDs literally, so `grep -o` enumerates coverage.

Each claim's **source** is one of two, and the coverage table records which
(per D13). `summary` claims come from the ticket's resolution comment and are
the literal AC1 floor. `question` claims come from the ticket's own research
question — what the `research` skill contract obliges a findings file to
answer, and what #71 Stage 0 and #79 depend on — so they are in scope, but a
reviewer checking AC1 alone can filter to `summary` rows.

### `.claude/specs/2026-08-20-cross-agent-project-surfaces-research.md` (#60)

| ID (source) | Claim the document must cover |
|---|---|
| C60.1 (summary) | Both agents provide repo-scoped instructions, skills, configuration, hooks and plugins — presented as a 5-mechanism × 2-agent (Claude Code, Codex) matrix with a present/absent verdict per cell. |
| C60.2 (question) | Per cell, the six axes #60 mandates: discovery path, precedence, refresh/restart behavior, symlink support, failure semantics, gaps. |
| C60.3 (summary) | Fixed native paths mean one contained canonical source needs **validated thin projections** — with the mechanism that makes the projection necessary named per cell. |
| C60.4 (summary) | The remaining prototype gaps, listed. **The original's referent for "prototype" is irreducibly ambiguous** (per D13): it may mean a projection prototype or #79's adoption dry run. The document must not guess — it lists the gaps remaining in the contained-source-with-thin-projections approach, records the ambiguity in its unverified-inheritance list, and covers both readings where they diverge. |
| C60.5 (question) | The architecture is not chosen; options are recorded, not ranked into a decision. |

Scope discipline (per D9): #60 asks about **project-scoped** surfaces. The
in-tree modules (`home/common/agent-guidance/`, `home/common/agent-skills/`,
`home/common/claude-code/`, `lib/agent-plugins.nix`) are first-party
installed behavior at **user scope**. They are admissible primary sources for
mechanism behavior — notably that Codex ignores a skill whose `SKILL.md` is
itself a symlink, hence the whole-directory links at `~/.agents/skills/`; that
`~/.codex/skills/` is Codex runtime state Nix neither populates nor prunes; and
that Claude accepts `github` and `directory` marketplace source types while
Codex has no Nix-declared marketplace at all — but every such observation is
labelled with the scope it was observed at, and any generalisation to project
scope is stated as an inference with its own evidence level.

### `.claude/specs/2026-08-20-agent-fallback-inventory-research.md` (#61)

| ID (source) | Claim the document must cover |
|---|---|
| C61.1 (summary) | The clearest removable cluster is **project binding, command, tracker, and doc discovery** — all four families named, each with its concrete sites. |
| C61.2 (summary) | Product/runtime preflights tied to live external variability are **not interchangeable** with onboarding fallbacks, with the discriminating property stated. |
| C61.3 (question) | A per-site inventory across the shared skills and helpers plus the live nix-config, Nodo and Argus adapters, each site classified `removable-after-validated-onboarding-contract` or `unavoidable-portability`. |
| C61.4 (question) | Attributable prompt size and repeated execution cost, **measured** — a stated unit, a stated method, and per-cluster numbers. An estimate is admissible only when labelled as one. |
| C61.5 (question) | No removal policy is decided. |

Terminology guard (per D10): a **fail-closed refusal is not a fallback**. The
`PreToolUse` lifecycle guard blocks rather than degrading, so it is not an
inventory site under C61.1/C61.3; if it appears at all it appears as a
contrasting case, named as enforcement. Likewise #69/#71's *declared runtime
alternative* is a third category distinct from both, and the document keeps the
three words apart.

### `.claude/specs/2026-08-20-project-knowledge-inventory-research.md` (#62)

| ID (source) | Claim the document must cover |
|---|---|
| C62.1 (summary) | Global sources are already centralized — with the single-source mechanisms named (one `AGENTS.md` source projected to both agents; one global skills tree reaching Claude via `skillsDir` and Codex via `~/.agents/skills/`). |
| C62.2 (summary) | Nodo's **34 ignored machine-local skill directories** are a main fleet gap. **Drift is already known here**: the current checkout shows 36 skill directories under `.claude/skills`, tracked, with no blanket ignore. The drift rule applies in full — record the as-of-decision claim, the observed count and tracked/ignored status with the command and date, and reconcile. |
| C62.3 (summary) | Argus duplication is a main fleet gap, with the duplicated items named and their global counterparts identified. |
| C62.4 (summary) | Argus's vendor-sensitive `pi` guidance, with what makes it vendor-derived and what makes it stale-sensitive. |
| C62.5 (summary) | Promotion candidates are **listed without policy decisions**. |
| C62.6 (question) | Per inventoried item: provenance, update mechanism, context cost, maintenance cost, and its classification among duplicate-of-global / agent-exclusive / vendor-derived / stale / reusable-elsewhere. |

### `.claude/specs/2026-08-20-release-lifecycle-seams-research.md` (#80)

**Inherited claims:**

| ID (source) | Claim the document must cover |
|---|---|
| C80.1 (summary) | Five materially different release-unit families: Nix host generations; Railway API/admin services; digest-addressed GHCR engines with reconciler convergence; an Argus launchd daemon rooted in a checkout; locally signed Argus helpers. |
| C80.2 (summary) | Identity and evidence differ accordingly — flake outputs and generations; Railway commit/deployment state; OCI digests plus current-digest heartbeats; local process/signature state. |
| C80.3 (summary) | Rollback ranges from retained generations and digest republishing to mutable platform redeploys and local file replacement. |
| C80.4 (question) | Per release unit, #80's full recording list: candidate and release identity; publication target, trigger, ordering, immutability; activation mode, authority boundary, restart/convergence; deployment-success, running-identity, liveness, readiness, migration and product-smoke evidence; durable or mutable data at risk; rollback anchor, action, reversibility limit, retirement evidence; partial-failure and re-entry behavior already implemented or documented. |
| C80.5 (question) | Facts shared by all three projects are separated from project-specific mechanics. |
| C80.6 (question) | The architecture is not chosen and no universal adapter is invented. |

**Added claims (this issue):**

| ID | Claim the document must cover |
|---|---|
| A80.1 | The fail-closed `PreToolUse` permission guard as an **enforcement seam** — today the only machine enforcement of release policy. Must name: the four adjudicated lifecycle verbs and the exact validated form of each; the authorized-owner set and where it is declared; the per-repository integration-base map, including `dev` for `elevenyellow/nodocom` and its deliberate exemption from the protection demand; the live checks against a default-branch base (an open PR on that base, at least one required status context, `enforce_admins` enabled); the scrubbing of `GITHUB_TOKEN`/`GH_TOKEN` from the lookups' environment so they authenticate through the keyring credential; and the fail-closed classes (unparseable command, shell handed to an evaluator, a guarded verb outside a command position, unresolvable repo or default branch, child timeout, non-zero or unparseable output). Must state that there is no defer path. **The "only machine enforcement" claim must be bounded** (per D14): the guard is the only enforcement inside the agent's own execution path, adjudicating before the action runs; live branch protection and the required `Nix Eval` status context on `main` are forge-side enforcement the guard *consults*, not enforcement it replaces. Recording both keeps the inventory from asserting something this repository's own CI configuration contradicts. |
| A80.2 | Each of the five independent durable state systems as a **durable-state seam**: the attempt-lifecycle ledger, the sdd plan ledger, the review-package store, ship-release's own state file, and the tracker-native wayfind state. Each characterised by #80's framing — identity, evidence, rollback — per the seam schema below. |
| A80.3 | Immutable commit references for both surviving prototype artifacts, with a retrievability statement for each: the adoption dry run (#79) at `b49c8771cbaf87eefc5f0d385100e205060538d9`, directory `prototype-agent-adoption-dry-run/`, reachable from `origin/worktree-prototype-nix-config-adoption-dry-run`; and the release-transactions prototype (#86) at `dc98ba9b6bafaf7b5373cc7595ef79a5526846d1`, directory `prototype-release-transactions/`, reachable from `origin/worktree-prototype-release-transactions`. Full 40-character shas, and the command a reader runs to retrieve each. |
| A80.4 | A named **correction** subsection recording that #86's resolution comment states its prototype was not pushed and lives only in a local worktree, that this is false, and the evidence (`git ls-remote origin` naming the branch and sha). Per D7 the correction lives only in this committed document; the tracker comment is not edited. |

**Seam taxonomy (per D11).** The inventory carries one roster table naming
every seam and its class, so "seam" has a declared taxonomy rather than three
meanings:

| Class | Members | Required per-member fields |
|---|---|---|
| `release-unit seam` | the five of C80.1 | the full C80.4 recording list |
| `enforcement seam` | the permission guard | locator, identity, evidence, rollback |
| `durable-state seam` | the five of A80.2 | locator, identity, evidence, rollback |

The four fields for the six added seams mean, and the document defines them
inline this way:

- **locator** — where the state or enforcement physically lives, as a path
  template with its root named (caller-supplied repository root, primary
  checkout, feature worktree, `$TMPDIR`, or the tracker itself).
- **identity** — what names one record and makes two records distinct.
- **evidence** — what a reader inspects to know the seam's current truth.
- **rollback** — what undoes or supersedes a record, and the reversibility
  limit where none exists.

**Terminology guards for #80 (per D10).** The document keeps these apart, each
with a one-line disambiguation where first used:

- *state*: #82/#88's release state and terminal receipt versus the workflow
  skills' durable state stores. The added seams are the latter.
- *identity*: #88's expected/running **subject identity** versus a state
  record's key (a run id, an action id, a plan basename). Each seam row says
  which sense it uses.
- *seam*: only through the roster's three declared classes; the six added seams
  are not release units and the document never implies they are.
- `.superpowers/`: a historical directory name. The document uses the literal
  paths and states that no Superpowers input, patch, marketplace or plugin
  exists in this repository, so no reader infers a dependency.

## Test seams

There is no unit-test suite for documentation in this repository, and this work
edits no `.nix` file, so `just build` is not a gate for it. Should any task
nevertheless touch a `.nix` file, `CLAUDE.md`'s standing rule reactivates and
`just build` becomes a gate for that task. The verification seams are these
four commands, and the plan inherits them:

| Seam | Command | Proves |
|---|---|---|
| V1 | `git show main:<path>` for each of the four paths | AC1 and AC4 — the paths exist on `main` and the links resolve. |
| V2 | `grep -o` for the claim IDs of this spec in each document's `## Coverage of the resolution summary` table | AC1's "conclusions cover every claim" — mechanically, per D12. |
| V3 | Inspection of the #80 roster table for eleven rows across the three declared classes, each carrying its required fields | AC2. |
| V4 | `git cat-file -e <sha>^{commit}` and `git ls-remote origin` for both prototype shas | AC3 — the recorded references are immutable and reachable. |

Prior art: `.claude/specs/2026-08-16-codex-worker-death-research.md` is the
existing committed-research precedent this contract's front matter follows.

## Out of scope

- Implementing anything the four documents describe.
- The `.agents/` adoption itself, and publishing the platform manifest.
- Reopening or re-deciding #60, #61, #62, #80, #84, #86 or #88.
- Editing any tracker comment, including #86's (per D7).
- Any change under `home/`, `hosts/`, `lib/` or `flake.nix`. This work is four
  Markdown document packages plus this spec: four roots at the exact linked
  paths, plus the evidence members D22 allows beside a root that exceeds the
  `review-package` per-member cap.
- Creating a glossary, context map, or ADR (per D15).
- Running `artifact-budget` against the four recovered documents (per D8).

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Every recovered document opens with a mandatory `## Provenance` block declaring it a 2026-09-02 re-derivation under #115, stating the original was never committed and is unrecoverable, and forbidding any claim in it from being cited as evidence of the original's content. | the-bar *Truthful terminal states* and *Fail loud*; the `research` skill requires durability and origin to be explicit at the top of the file, never implicit. Resolves Phase-0 open question 1. | A one-line footnote, or silent recreation — either lets a reader take the document as the restored original, which is the one thing it is not. |
| D2 | Durability is declared `committed` in all four. #60, #61 and #62's resolution comments already anticipate it ("awaits a later commit"); only #80's instruction literally said write an `attached` file, so only that document carries the clause noting the changed durability class. | #71 Stage 0: commit them "so their existing links become live and Git owns their history"; the `research` skill's three-value durability vocabulary. | Keeping `attached` for fidelity to #80's wording — it would contradict the commit that is the whole point of the slice. |
| D3 | A fixed citation form per source class, with fleet claims pinned to the checkout's observed `HEAD` and date, and an explicit "unverified inheritance" list for any summary claim not re-verified against a primary source. | #80's question mandates primary sources; the `research` skill requires a source per claim; the-bar *Verify before claiming done*. | Prose citation — it makes an inherited claim indistinguishable from a verified one, which is precisely how the original findings became unauditable. |
| D4 | The schema-v1 `research-observations` / `agent-evidence` gate is not invoked for any of the four; each document declares that and why. | The `research` skill scopes the gate to live-availability or blocking conclusions; these four are repository-state inventories. The precedent doc declares the gate not invoked with a reason. | Running `agent-evidence` to obtain standing conclusions — it demands two independent timepoints for facts that are static tree reads: ceremony without added truth. |
| D5 | A uniform drift rule: where today's tree contradicts a summary claim, record the as-of-decision claim, the observed fact with command and date, and an explicit reconciliation. Never silently restate, never silently drop. | the-bar *Truthful terminal states*; #115 already sanctions exactly this shape for the #86 correction. C62.2 is a known live instance. | Restating the summary verbatim (the document would assert a false current fact) or quietly correcting it (the coverage obligation would be undischarged and unauditable). |
| D6 | #80 is re-derived from primary sources in all three repositories; the resolution summary is the coverage floor only and is never cited as a source. | #80's question mandates primary sources; #115 says the inventory "must be re-derived, not restored"; both fleet checkouts were verified to contain the release mechanics (Railway configs, the GHCR publish-and-roll workflow and reconciler supervisor, `daemon/launchd.ts`, `daemon/sign.sh`). Resolves Phase-0 open question 3. | Leaning on the summary for Nodo and Argus — that produces a restatement, which the issue forbids, and it would carry the summary's compression into the record permanently. |
| D7 | #86's misstatement is corrected only in the committed inventory, in a named correction subsection; no tracker comment is edited. | #115's scope boundary lists editing tracker comments as OUT, and AC3 asks only that the committed inventory record the references. Resolves Phase-0 open question 2. | Editing #86's comment — out of scope, and it would erase the historical record of the mistake the correction exists to document. |
| D8 | The four recovered documents are not `artifact-budget`-governed; proportionality is enforced by the-bar's *Token economy* instead. | `artifact-budget` declares exactly four kinds (`design-spec`, `implementation-plan`, `handoff`, `review-package`); no `research` kind exists, so any check would be a fabricated threshold. | Reusing the `design-spec` kind's 64 KiB root cap — it would apply a limit written for a different artifact and could truncate a coverage obligation. |
| D9 | #60's document labels every observation with the scope it was observed at (project vs user) and states any generalisation from user-scope installed behavior to project scope as an inference with its own evidence level. | #60 asks specifically about repo-scoped mechanisms, while this repository's first-party installed behavior is user-scoped; conflating them would make the projection conclusion (C60.3) rest on evidence that does not cover it. | Treating the user-scope facts as project-scope evidence — the fastest route to a confidently wrong matrix. |
| D10 | Explicit terminology guards: fallback vs fail-closed refusal vs declared runtime alternative (#61); and release state vs durable state store, subject identity vs record identity, and the three seam classes (#80); plus a `.superpowers/`-is-historical note. | `CLAUDE.md` states the guard is fail-closed with no defer path and that the `.superpowers/` name is historical with no Superpowers dependency; #69/#71 name declared runtime alternatives as their own category; #88 defines subject identity. | Letting each word carry its ambient meaning — the guard would be inventoried as a fallback in #61 and the six added seams would read as release units in #80. |
| D11 | #80 carries one roster table of eleven seams under three declared classes, with the full C80.4 recording list for release units and a locator/identity/evidence/rollback quartet for the six added seams. | #115 requires the guard and the five stores to be "named as seams" with "identity, evidence and rollback characteristics"; #80's own recording list governs release units. | One flat schema for all eleven (forces empty publication/activation fields onto a state store) or a separate non-seam word for the six (AC2 literally requires them to be named seams). |
| D12 | Each recovered document carries a `## Coverage of the resolution summary` table keyed by this spec's literal claim IDs, restating each claim in one line and naming its source so the AC1 floor is filterable and the document reads standalone. | AC1 requires conclusions to "cover every claim in its ticket's resolution summary"; a keyed table makes that a `grep`, per the-bar *Verify before claiming done*. | Prose assertion of coverage — verification would be one reader's impression, and a missed claim would be invisible until the next person needed it. |
| D13 | Claim IDs are tagged `summary` or `question`; and an inherited claim whose original referent is unrecoverable is discharged by covering the readings, never by picking one — C60.4's "prototype gaps" is the known instance. | AC1's floor is the resolution summary while the `research` skill obliges a findings file to answer its question; the-bar *Fail loud* forbids closing an ambiguity by silent choice. | Guessing C60.4's referent — a confident wrong reading is worse than the 404 it replaces, because it looks authoritative. |
| D14 | A80.1 records #115's "only machine enforcement of release policy" claim with its boundary stated: the guard is in-path pre-action adjudication; branch protection and the required `Nix Eval` context are forge-side enforcement it consults. | `CLAUDE.md` states `Nix Eval` is a required context on `main` with `enforce_admins`, so `gh pr merge --admin` is refused until it is green — machine enforcement the guard does not own. the-bar *Truthful terminal states*. | Restating the claim unbounded — the recovered inventory would contradict this repository's own CI configuration on its first page. |
| D15 | No glossary, context map, or ADR is created by this work. | #71, #84 and #88 each close with the identical settled statement that no glossary or ADR is created during wayfinding, because the ticket is the authoritative decision store and the canonical knowledge roots do not exist until adoption; this repository has no `docs/`, map, or ADR directory. | Creating the first glossary here — it would pre-empt the `.agents/` adoption that #65 and #71 make the owner of those roots. |
| D16 | Task gates observe V1 as `git show HEAD:<path>` inside the worktree; the `git show main:<path>` form of AC4 is a ship-time consequence of merging, not a task gate, and no task asserts it. | `writing-plans` requires every task's verification line to be runnable and falsifiable at the commit the implementer starts from; a path can only reach `main` after this branch merges. | Deferring all path verification to ship time — every authoring task would then carry no falsifiable path gate at all. |
| D17 | The plan dictates claim contracts, required document structure and falsifiable shell gates, and dictates **no finding prose**: every substantive sentence in the four documents is authored during execution from primary sources. It also creates no verification script, keeping the deliverable at four Markdown files plus the spec and plan package. | #115 requires the four inventories to be re-derived, not restored; the-bar *Verify before claiming done* — plan prose asserting findings would enter the record as fabricated evidence. The spec's `## Out of scope` bounds the work to Markdown files. | Pre-writing the findings in the plan (invented facts presented as contract), or shipping a reusable checker script (a new artifact the scope boundary excludes). |
| D18 | C62.2's parenthetical drift observation ("36 skill directories, tracked, no blanket ignore") is itself a planning-time unverified observation and is superseded by the execute-phase re-observation, whatever it finds — including "no drift; the as-of-decision claim still holds". The document records the commands, their real output, the checkout `HEAD` and the observation date, never a count copied from this spec or from the plan. | D5's drift rule and the-bar *Truthful terminal states*; a 2026-09-02 read of `/Users/anis/Projects/nodocom` did not reproduce the parenthetical as stated, so treating it as fact would plant an unverified number in a committed inventory. | Encoding the spec's count as the observed fact — the recovered document would assert a number nobody re-checked, which is exactly the failure #115 exists to repair. |
| D19 | The claim-ID gates prove **traceability**, never truth: a new seam V5 makes a source-backed semantic audit a required step of every authoring task, and the plan stops describing `grep` coverage as mechanical proof of AC1. The #80 gate additionally requires each added seam's `Locator/Identity/Evidence/Rollback` value to be substantive rather than merely present, names the six added seams individually, and verifies each prototype as an associated `sha`+branch+directory triple whose sha is that exact remote branch's tip. | Phase-5 Codex plan review B-01/B-02/B-03, verified against the live plan members: the #80 field list omitted eleven of `C80.4`'s fields, the added-seam check passed on empty values, and the prototype check passed on swapped associations. These are recovered historical findings whose entire value is being true of the live tree. | Trusting the syntactic gates alone — the four paths are exactly where a reader will most trust plausible fiction, so a passing `grep` is the weakest possible evidence there. |
| D20 | The `A80.1` literal set adds `elevenyellow` and `dev`; the durable-state sources name `sdd/scripts/review-package` and `scripts/sdd-workspace` as primary, ahead of the skill prose; the plan calls its gates Bash, not POSIX shell. | Phase-5 review SF-01/SF-02 plus `home/common/claude-code/default.nix`, which declares both authorized owners and maps Nodo's integration base to `dev`; the two scripts derive the locators the skill prose only describes; the gates use `$'…'` and process substitution. | Leaving the guard inventory to describe one owner and one base — the seam's authority boundary is exactly the set of owners and bases it admits. |
| D21 | The fleet documents cite the **checked-out snapshot** as of 2026-09-02, not another repository's current integration tip, and every fleet citation records the observed `HEAD` plus how far behind its own `origin` integration ref that checkout is. No task refreshes a checkout. | Phase-5 review D-01: `/Users/anis/Projects/nodocom` was 111 commits behind its local `origin/dev` at planning time, and the plan already forbids mutating fleet checkouts. Stating the gap keeps the citation honest without a write. | Refreshing the checkouts to inventory current tips — a write to a repository outside this slice's scope, and a moving target no committed document could stay true to. |
| D22 | Where a recovered document's whole-file diff exceeds the `review-package` per-member cap, that document becomes a **package**: a root at the exact path its resolution comment links, carrying `## Provenance`, `## Research question`, `## Coverage of the resolution summary`, `## Unverified inheritance`, every synthesis, every conclusion and `## What this document does not decide`; plus one or more evidence members at `<root-stem>.evidence/<name>.md` carrying **bulk evidence records only** — a per-hit adjudication map, a per-invocation appendix, a per-unit field-by-field recording section, or any comparable block whose value is enumeration rather than argument, tabular or prose. A member never carries a synthesis, a conclusion, or a sentence the document reasons from; those stay in the root whatever their length. A coverage row whose discharging heading lives in a member names that member's path beside the heading. D8 is unchanged — `artifact-budget` is still never run against these documents; D22 is a separate bound, enforced by a different tool for a different reason. | The mandatory final two-axis review packages `MERGE_BASE..HEAD` in one `review-package` call, and that generator refuses an individually oversized handwritten file diff with no remediation available (`sdd/SKILL.md`: "`member_bytes` and `root_bytes` never take this remediation: an individually oversized handwritten diff or manifest still exits 3"). Measured at `7edbe6b`, #61's whole-file diff is 80,800 bytes and #80's is 74,501 against a 65,536-byte cap, so the branch could not be reviewed at all in its single-file shape — and #80 still has Task 5's content to receive. Root-plus-members is this repository's own idiomatic decomposition: this very plan is `<plan>.md` plus `<plan>.tasks/`. AC1–AC4 are untouched, because the linked path still resolves and still carries the conclusions. | Trimming reviewed content to fit — it would undo the five fix rounds whose whole purpose was publishing per-hit evidence a reader can audit on the page, which is the charter class this issue exists to repair. Or raising `member_max_bytes` in `~/.agents/share/artifact-budget-policy.json` — a Nix-managed file that this issue's scope boundary excludes, and a change that would silently widen the bound for every other run. |
| D23 | The #80 decomposition is the reopened Task 4's remaining work, not a task of its own; only the #61 decomposition becomes the new Task 5. | Phase-5 re-review B-01, verified against the live ledger: `sdd` resumes at the first task with no `Task N: complete` line, and the ledger records Task 4 as "NOT reviewed and NOT complete", so execution restarts there and a later task could never be reached. Folding the decomposition in also puts Task 4's never-dispatched content review and the decomposition under one review, which is the review that content still owes. | A standalone decomposition task ordered before Task 4 — the task index must run in ascending order for the plan checker, and marking Task 4 complete to step over it would retire an unreviewed document, which is the one thing the reviewer said not to do. |
| D24 | Every V6 run passes `--output` to a temporary path and deletes it afterwards. | Phase-5 re-review B-05, verified in `review-package`: the default destination is keyed to `<base>..<head>`, `MERGE_BASE..HEAD` is exactly what the mandatory final review publishes to, and publication is exclusive — so a default-path V6 run makes the final review's own generation fail with exit 2, and re-running at the same `HEAD` cannot clear it. This attempt hit that collision on its first measurement and briefly read it as a budget verdict. | Letting V6 use the default path and treating exit 2 as "stale directory, re-run" — the guidance the amendment first carried, which is wrong in both halves: the collision does not clear, and exit 2 is a generation failure of any kind. |
| D25 | A decomposition's byte-identity is proved by `cmp` against a pinned pre-edit `MOVE_BASE` commit and recorded line ranges, and the commands and their output go in the task report. | Phase-5 re-review B-06: the amendment first asserted byte-identical moves but verified them only by a reviewer reading `git diff` for "no changed sentence", which cannot fail on a changed character inside a moved block. An unverifiable claim about faithfulness is the exact failure class this issue exists to repair, so the gate has to be mechanical. | Trusting the diff review — the same shape of assurance that let a confident unsupported sentence into every document this issue is recovering. |

## Amendment log

**2026-09-02, during Phase 6 (issue 115, attempt 2).** Task 4's review was
blocked by its packaging, not its content: `review-package` refuses an
individually oversized handwritten file diff and has no remediation for it. Over
merge base `9206f3ea92e2dde06b998b1a9e402fc2b1ad1e6d` at `7edbe6b`, #61's
whole-file diff is 80,800 bytes and #80's is 74,501 against a 65,536-byte cap;
the other nine files and the seven-shard, 378,936-byte aggregate were within
budget, so per-member bytes was the sole violation. The mandatory final review
packages `MERGE_BASE..HEAD` in one call and fails the same way, so the branch
could not be reviewed at all in its single-file shape.

The defect is in this plan, not the documents: its architecture fixed one file
per ticket without knowledge of a hard tooling bound, and its coverage rule put
every discharging heading in that one file. Both are amended under D22, and the
new Task 5 does the decomposition. No claim contract, acceptance criterion or
reviewed sentence changes — the linked paths still resolve to the roots, and the
roots still carry every conclusion.
