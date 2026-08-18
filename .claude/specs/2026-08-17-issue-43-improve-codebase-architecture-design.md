# Improve Codebase Architecture Skill

Issue: [#43 — Ship the end-to-end architecture improvement workflow](https://github.com/fagenorn/nix-config/issues/43)

Parent design: [`2026-08-17-improve-codebase-architecture-design.md`](2026-08-17-improve-codebase-architecture-design.md) —
approved, D1–D6. This spec is issue-scoped: it cites those decisions, never restates them.
Sibling slice: [`2026-08-17-issue-42-shared-design-vocabulary-design.md`](2026-08-17-issue-42-shared-design-vocabulary-design.md),
merged as PR #44, which shipped the `codebase-design` vocabulary this skill consumes.

## Problem

`codebase-design` now exists, and nothing uses it. The system has the vocabulary for deep modules
and no workflow that walks a real codebase with it, shows what it found, and carries a chosen
finding into the design pipeline that already exists here.

Matt Pocock's upstream `improve-codebase-architecture` is the right journey — bounded scan, visual
candidates, one top recommendation, then exploration of the pick — but its guts are wired to a
system this is not. Its grounding reads hard-coded `CONTEXT.md` and `docs/adr/` paths that this
repository does not have and that other projects put elsewhere. Its scan is an unregistered
sub-agent spawn, which this repository's dispatch registry forbids. Its third step hands the
selected candidate to `grilling` and `domain-modeling`, two skills that do not exist here and never
will. Copied unchanged, the skill would fail at its first grounding read and dead-end at its last
step.

The desired result is one repository-owned adaptation that keeps the upstream experience intact and
behaves as a native member of this system: explicit-only in both hosts, grounded through
`doc-grounded-questions`, scanning through a registered Opus/high `issue-owner` dispatch, and routing
its output into `wayfind` or into `worktrees` → `design` → `grill-with-docs` — then stopping.

## Solution

Create `home/common/agent-skills/skills/improve-codebase-architecture/` as an attributed adaptation
of the upstream package at revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected
2026-08-17. Creating that directory is the entire distribution change: the shared distributor
derives its skill set from `builtins.readDir ./skills`, so the package reaches Codex as a
whole-directory link at `~/.agents/skills/improve-codebase-architecture` and Claude Code as a real
directory of store links at `~/.claude/skills/improve-codebase-architecture/`, from the same
authored sources. **No `.nix`, `flake.nix`, or `justfile` edit is required, and a plan that needs
one is a defect in the plan.**

Four shared workflow files change alongside it: `model-matrix.json` gains the scan dispatch row and
standalone scenario; `scripts/agent-model-matrix.py` admits that workflow family;
`tests/test_agent_model_matrix.py` pins its deterministic trace; and
`tests/test_workflow_skill_contracts.py` gains one appended package-contract `TestCase` class. The
parent design document also lands under `.claude/specs/` so the links in #42 and #43 resolve on
`main`.

Unlike the sibling vocabulary package, this adaptation is not conservative. Upstream's process
shape, section order, report format and editorial voice are preserved; its grounding surface, its
sub-agent spawn, its hotspot rule and its entire downstream step are rewritten, because each of them
names something that does not exist in this system. Every one of those departures is enumerated in
the packaged `LICENSE`, per the vendored-skill convention in
`home/common/agent-skills/README.md` §"Vendored skills".

## Decisions

### The package

Five files, all inside the skill directory (per D1):

- **`SKILL.md`** — the loaded body. Frontmatter, the three-step process (explore → report →
  route), the registered scan dispatch and the evidence bar its owner must satisfy, the candidate
  contract, the selection routing ladder, and a closing provenance pointer. This is the only file
  the agent reads on every invocation, so everything that is needed on every invocation lives here
  and nothing else does.
- **`HTML-REPORT.md`** — upstream's report reference, loaded lazily and only when a report is
  actually being rendered: the HTML scaffold, the five diagram patterns, the card anatomy, the
  style and tone guidance, plus the accessibility contract that parent D4 requires. Same shape as
  `codebase-design`'s `DEEPENING.md` — a sibling reference `SKILL.md` links to rather than inlines.
- **`agents/openai.yaml`** — upstream's Codex metadata verbatim: `interface.display_name`,
  `interface.short_description`, and `policy.allow_implicit_invocation: false` (per D2).
- **`LICENSE`** — provenance preamble (upstream URL, path, pinned revision, inspection date, and
  every departure below) followed by the upstream MIT notice reproduced unmodified. The notice text
  never appears in `SKILL.md`, which carries a one-line pointer instead (issue-42 D2).
- **`evals/evals.json`** — the three deployed-behaviour cases (per D12).

No separate routing file and no separate scan-brief file. Routing is five short steps the agent is
mid-flight through when it needs them, and the scan brief must sit on the line after the dispatch
marker; putting either behind a hop costs a read and buys nothing.

### Frontmatter and the explicit-only interface

`SKILL.md`'s frontmatter is upstream's, unchanged, with no keys added or removed (per D8):

```yaml
---
name: improve-codebase-architecture
description: Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.
disable-model-invocation: true
---
```

`disable-model-invocation: true` is the Claude-facing half of parent D2; the Codex-facing half is
`policy.allow_implicit_invocation: false` in `agents/openai.yaml`. Both are upstream's own values at
the pinned revision, so explicit-only costs no departure. The description is not a trigger for a
skill that cannot be model-invoked — it is the human-facing blurb at the `/`-invocation site — so it
stays verbatim, matching issue-42 D14.

The parent design's Invocation-interface paragraph also says the Codex metadata supplies "a default
prompt that explicitly names `$improve-codebase-architecture`". Upstream's manifest at the pinned
revision has no such key, this repository has no precedent for one, and the Codex manifest schema is
not documented anywhere in this tree. That clause is dropped rather than guessed at (per D2).

### What the skill's own text names

Every cross-skill reference is to a skill that exists in this tree, written in this repository's
idiom: the imperative "Invoke" followed by the bare skill name in backticks, as the existing skill
tree already phrases it (per D9).

| Moment | Skill invoked | Replaces upstream's |
|---|---|---|
| Architecture vocabulary | `codebase-design` | `Call the Skill tool with "codebase-design"` (same skill; local package, local phrasing) |
| Domain grounding before the scan | `doc-grounded-questions` | hard-coded `CONTEXT.md` + `docs/adr/` reads |
| Isolation before any write | `worktrees` | nothing — upstream had no isolation step |
| Concrete candidate → spec | `design` | `grilling` (does not exist) |
| Domain language + ADRs after approval | `grill-with-docs` | `domain-modeling` (does not exist) |
| Destination still foggy | `wayfind` | nothing — upstream had no fog gate |
| Scope gate, recommended never invoked | `writing-plans` / `to-issues` | nothing |

Upstream's inline side effects during the grilling loop — add the term to `CONTEXT.md`, sharpen a
fuzzy term, offer an ADR when the user rejects a candidate for a load-bearing reason — are not
reimplemented. `grill-with-docs` owns exactly those behaviours in this system, so the adaptation
delegates to it rather than carrying a second copy of the policy (the-bar, DRY). The one thing
`grill-with-docs` does not own is *when* the reject-an-ADR offer applies, and that is upstream
guidance that survives inside the routing step in one line.

The skill names no caller. Consumers invoke it; it does not know who they are.

### Grounding and scope inference

Before proposing anything, the skill invokes `codebase-design` for the vocabulary and
`doc-grounded-questions` for the project's domain language, decisions and standards. Context terms
become the domain names used in the report; existing decisions are constraints, not invitations to
relitigate; standards are carried into candidate grading. Where a project has no doc surfaces —
this repository being one — `doc-grounded-questions` skips them silently and the run continues on
code alone.

Scope selection (parent D3):

- A user-named module, subsystem, path or pain point is authoritative and **bypasses inference
  entirely**.
- With no direction, read the last **50 non-merge commits** (`git log --oneline --no-merges -50`),
  rank repeatedly changed paths, and follow the strongest concentration into code, tests and the
  documentation covering it.
- **Widen only** when that history is scattered or yields no meaningful concentration.
- History selects where to look. It is never, by itself, evidence that a module should change.

### The scan dispatch

One fresh owner performs the organic code walk. This is design judgment, so it is the `issue-owner`
role at Opus/high, not the bounded `explorer` tier (parent D3). Registered exactly as follows.

Marker in `SKILL.md`:

```
<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->
```

Call, on the **immediately following line**:

```
Agent(subagent_type="general-purpose", model="opus", effort="high") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.
```

Row appended to `dispatch_sites` in `model-matrix.json` (the array is ordered as a
delivery-workflow narrative rather than alphabetically, and this skill is not part of that
narrative, so it goes last):

```json
{
  "id": "improve-architecture-scan-owner",
  "path": "home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md",
  "marker": "<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->",
  "call": "Agent(subagent_type=\"general-purpose\", model=\"opus\", effort=\"high\") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.",
  "role": "issue-owner",
  "model": "opus",
  "effort": "high",
  "requires": []
}
```

This is a workflow, not a fact-lookup helper, so it also gets a deterministic scenario (per D5).
Add `improve-codebase-architecture` to the validator's closed `WORKFLOW_FAMILIES`; because
`EXPECTED_SCENARIOS` derives from that set, the matrix must then carry this exact standalone trace:

```json
"improve-codebase-architecture": [
  {
    "workflow": "improve-codebase-architecture",
    "dispatch": "improve-architecture-scan-owner",
    "role": "issue-owner",
    "model": "opus",
    "effort": "high",
    "requires": []
  }
]
```

The existing `representative` scenario remains the four-family issue-delivery demo. Adding the
architecture event there, or filing it under `from-issue` or `orchestration`, would claim that a
normal issue-delivery trace performs an architecture scan. The new standalone scenario gives the
dispatch its own truthful trace without changing any existing workflow's semantics.

Because the file now carries a registered site, **every** line in `SKILL.md` containing `Agent(`
must be a registered call. There is exactly one such line in the whole package: the call above. The
no-dispatch fallback — when the host cannot dispatch a sub-agent, the calling agent performs the
same bounded scan inline and discloses the fallback — is prose and contains no `Agent(`.

The scan is read-only with respect to the target repository. It may write at most one structured
findings artifact, and only under the OS temporary directory. For every suspected candidate it must
establish the seven items parent D3 names: module and callers; the interface knowledge callers
currently carry; where locality or leverage is lost; the deletion-test result; the dependency
category and whether a real seam has at least two justified adapters; the existing tests and the
proposed interface-level test surface; and any context or decision conflict, including why
reopening it would be justified.

### The candidate contract

Render every candidate that clears that evidence bar, up to **five**. Zero, one, and five are all
valid outcomes: zero produces a truthful no-candidate report, which is a **successful run**, not a
failure. Never pad toward a count (per D13). Strength is upstream's vocabulary — `Strong`,
`Worth exploring`, `Speculative` — and a top-recommendation card closes the report whenever at least
one candidate exists.

### The report

Rendered by the calling agent (not the scan owner) to a fresh
`architecture-review-<timestamp>.html` under the OS temporary directory, resolved from `$TMPDIR`,
falling back to `/tmp`, or `%TEMP%` on Windows. Nothing lands in the target repository.

`HTML-REPORT.md` carries the full contract: upstream's scaffold, header, card anatomy, the five
diagram patterns, colour and tone guidance, and — added by this adaptation — the accessibility
requirements from parent D4: semantic headings preserving reading order, a text equivalent adjacent
to every diagram, colour never the sole carrier of meaning, minimal inline base styles so prose
stays readable when the CDN is unavailable, 4.5:1 contrast on normal text, and a side-by-side layout
that collapses cleanly at phone width without duplicating content.

Failure semantics follow parent D4 exactly: report-generation failure is a failed run; a failed
browser open or an unreachable CDN is a **disclosed warning**, not a generation failure, because the
absolute HTML path remains available. The absolute path is printed on every run, warning or not.

### Selection and routing

After presenting the report the skill asks which candidate to explore and proposes the top
recommendation. It proposes no module interface before selection. Selection is the first point at
which repository mutation may begin, and the ladder is parent D5's, unchanged:

1. **Fog gate.** Destination or its current decision questions still not statable precisely →
   invoke `wayfind`, then return control. No design worktree, and no automatic resumption of this
   skill after the map is charted.
2. **Isolation.** Reuse the current workspace only when it is already an isolated linked worktree;
   otherwise invoke `worktrees` for a candidate-named worktree cut from the configured remote
   integration-branch ref, before any spec or domain document is written.
3. **Design.** Invoke `design`. Carry the scan evidence in as grounding; do not re-ask what
   candidate selection already settled.
4. **Domain and decisions.** After the design is approved, invoke `grill-with-docs`.
5. **Scope gate, then stop.** Recommend `writing-plans` for one cohesive build or `to-issues` for
   several independently shippable slices. Do not invoke either, do not create issues, do not
   execute.

### Provenance and the recorded departures

`LICENSE` records, in the shape `codebase-design/LICENSE` established, the upstream URL, the path
`skills/engineering/improve-codebase-architecture/`, revision
`9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspection date 2026-08-17, the no-automatic-sync note,
and every departure below, before reproducing the MIT notice unmodified. `SKILL.md` closes with a
one-line pointer at it and never inlines the notice.

The departures, which are exactly what the contract suite pins:

1. **Vocabulary invocation** — upstream's `Call the Skill tool with "codebase-design"` becomes an
   "Invoke"-plus-backticked-name line, this repository's idiom, naming the repository-owned package.
2. **Domain grounding repointed** — upstream's hard-coded `CONTEXT.md` and `docs/adr/` reads become
   an invocation of `doc-grounded-questions`, which resolves whatever doc surfaces a project has and
   degrades silently where it has none. (Same repoint as issue-42 D5.)
3. **Hotspot rule made concrete** — "walk back a good stretch of the commit history" becomes the
   last 50 non-merge commits, widening only when history is scattered.
4. **Scan becomes a registered dispatch** — "spawn a sub-agent to walk the codebase" becomes the
   marked Opus/high `issue-owner` call above, with the seven-item evidence bar, the read-only
   constraint, the temp-only findings artifact, and the inline fallback.
5. **Candidate contract stated** — zero to five, never padded, no-candidate reports are truthful and
   successful.
6. **Report contract extended** — accessibility requirements added to `HTML-REPORT.md`, and the
   generation-fails-the-run / browser-or-CDN-warns split plus always-print-the-absolute-path added
   to `SKILL.md`.
7. **Downstream step replaced** — upstream's step 3 (`grilling`, `domain-modeling`) becomes the fog
   gate, worktree isolation, `design`, `grill-with-docs`, and the scope-gate stop. The inline
   `CONTEXT.md`/ADR side effects are delegated to `grill-with-docs`.
8. **Provenance pointer** — one closing line in `SKILL.md` pointing at `LICENSE`.
9. **Package extensions** — the repository adds the provenance `LICENSE` required by its vendored
   skill convention and `evals/evals.json` required by issue #43; upstream has neither file in this
   skill directory.

Everything not on that list — process shape, section order, the report scaffold and diagram
patterns, the editorial voice, the substitution ban, the deletion-test framing, `disable-model-invocation`,
and `agents/openai.yaml` in full — is upstream's, on purpose.

### Contract coverage

One `TestCase` class appended as a single contiguous block at the end of
`tests/test_workflow_skill_contracts.py` — its path constants, then the class, with its own
`setUpClass` fixtures so an absent package fails only this class (per D7, following issue-42 D9).
The module-level helpers `skill_frontmatter` and `relative_markdown_links` are reused, never copied.
Package and authored-workflow claims stay in that class. Matrix-family and trace claims go in
`test_agent_model_matrix.py`, whose existing class owns those invariants (per D7).

The observable behaviours the class pins:

1. **Package structure** — all five files exist; frontmatter `name` equals the directory name;
   description non-empty; every relative markdown link in every package document resolves to a file
   that stays inside the package.
2. **Explicit-only in both hosts** — `disable-model-invocation: true` in the frontmatter, and
   `policy.allow_implicit_invocation: false` plus both `interface` keys in `agents/openai.yaml`.
3. **Vocabulary dependency** — `SKILL.md` names `codebase-design` as its architecture vocabulary
   source, and the package nowhere names `grilling` or `domain-modeling`.
4. **Local workflow dependencies** — `SKILL.md` names each of `doc-grounded-questions`, `worktrees`,
   `design`, `grill-with-docs` and `wayfind`, and each named skill directory exists in the tree.
   This is the assertion that forecloses a reintroduced dangling workflow reference.
5. **Scope inference** — a user-named direction bypasses history; the unscoped path names 50
   non-merge commits; widening is conditioned on scattered history. Both paths are pinned, per AC2.
6. **Scan dispatch registration** — reading `model-matrix.json`: a site with id
   `improve-architecture-scan-owner` exists, its path is this skill's `SKILL.md`, its role is
   `issue-owner` at opus/high, and its marker and call appear in `SKILL.md` with the call on the
   line immediately after the marker.
7. **Single dispatch** — exactly one line in the package contains `Agent(`, and it is the registered
   call. Issue-42 D6's assertion, inverted for a package that does dispatch: the validator scans
   only registered paths, so nothing else would catch a second spawn.
8. **Read-only discovery** — `SKILL.md` states the scan writes nothing to the repository and that
   any findings artifact goes to the temp directory.
9. **Evidence bar** — the deletion test, the dependency categories, and the two-adapters-make-a-real-seam
   rule are all required of a candidate.
10. **Candidate contract** — the five-candidate ceiling, the never-pad rule, the truthful
    no-candidate outcome, the three strength labels, and the top recommendation.
11. **Report contract** — temp-directory resolution and the `architecture-review-<timestamp>.html`
    name; the absolute path is always printed; generation failure fails the run while a
    browser-open or CDN failure is a disclosed warning; every candidate has before/after evidence;
    and `HTML-REPORT.md` carries the semantic fallback and text-equivalent requirements.
12. **Routing** — fog routes to `wayfind` with no worktree; a concrete candidate reuses or creates
    an isolated worktree before `design`, then `grill-with-docs`; and the skill stops at a
    recommendation of `writing-plans` or `to-issues` rather than invoking them.
13. **Attribution** — `LICENSE` carries the upstream copyright line, the MIT permission notice, the
    pinned revision and the inspection date; each of the nine departures above is recorded in it;
    and `SKILL.md` links to it while containing no notice text.

`tests/test_agent_model_matrix.py` requires the new workflow family and scenario, asserts that the
scenario has exactly the one event above, and checks that
`trace improve-codebase-architecture` emits the exact issue-owner/opus/high selection. The existing
representative-trace assertion remains explicitly scoped to the four issue-delivery families. This
new matrix contract is the assertion that turns red against the starting matrix, where neither the
dispatch nor the scenario exists (per D6).

### Documentation

No change to `home/common/agent-skills/README.md`. Its §"Vendored skills" was written generically by
issue-42 D12 precisely so a second vendored package needs no second note, and it enumerates no
skills — so there is no list for this package to join (per D10). Its adapter-surface table describes
per-project doc locations and is untouched by a machine-global skill.

No ADR and no glossary entry. This repository has no `docs/` tree and creating one is out of scope,
so `grill-with-docs` outcomes that would normally land as ADRs or glossary terms are recorded as
rows in the Decision ledger below instead (per D11, following issue-42 D13). The load-bearing
terminology this work introduces — deepening candidate, strength label, fog gate — is defined in the
skill package itself, which is a better home for it than a glossary entry would be.

The parent design document is committed verbatim at
`.claude/specs/2026-08-17-improve-codebase-architecture-design.md` (per D4), unedited, so that D1–D6
travel with the code and the `blob/main/...` links in issues #42 and #43 resolve once this branch
merges.

## Test seams

Three seams, all public, exactly parent D6's. No fourth.

**1. Shared deployment seam.** The built, unactivated Home Manager generation must expose the
complete package to both agents.

```sh
just build   # public gate: the darwin configuration still evaluates and builds

nix build '.#darwinConfigurations.mbp.config.home-manager.users.anis.home-files' \
  --no-link --print-out-paths
```

The user attribute is the configured `username`, not a literal to assume; `mbp` is the darwin host.
Inspect the printed store path for both surfaces, each carrying the whole package — `SKILL.md`,
`HTML-REPORT.md`, `LICENSE`, `agents/openai.yaml`, and `evals/evals.json`:

- `.agents/skills/improve-codebase-architecture` — one symlink to a whole store directory, listed
  through. The Codex surface.
- `.claude/skills/improve-codebase-architecture/` — a real directory whose files are individual
  store links. The Claude Code surface.

`just build` alone proves the configuration evaluates and builds; its `result` symlink is the system
derivation and the home tree is not navigable from it, which is why the second command exists.
Neither activates. The Linux host needs no second local build: the distributor reads the directory
during evaluation, so CI's required `Nix Eval` job exercises the new directory there too.

**2. Workflow-contract seam.** `just agent-workflow-tests` runs the extended suite; the new class
must pass on the finished branch and fail at the starting commit, where its subject is absent.
`just agent-model-matrix` must pass on the finished branch — it validates the new marker, the
immediately-following call, the standalone scenario, and the absence of any unregistered `Agent(`
in `SKILL.md`. Also run the new trace directly:

```sh
python3 home/common/agent-skills/scripts/agent-model-matrix.py \
  trace improve-codebase-architecture
```

Be precise about what fails at the base: `just agent-model-matrix` **passes** at the starting commit
by construction, because its then-current validator does not yet know the new workflow family. AC3's
"the model-matrix gate rejects the starting commit" is therefore discharged by the new
`test_agent_model_matrix.py` contract run against the starting matrix: it requires the family,
dispatch and scenario and turns red there (per D6). Any falsification evidence must name that
failing test, not claim that the historical validator rejects a subject it does not know.

**3. Deployed-behaviour seam.** `evals/evals.json`, three `pipeline` cases against the TinyTask
fixture (per D12). Grade the *deployed* generation: the sandboxed `claude -p` reads
`~/.claude/skills`, so these cases cannot pass until a human runs `just switch`, which is exactly
what AC7 defers. That is a harness property, not a known gap, so no case carries
`expected_today: "fail"`.

The sandbox gives the fixture a single commit ("chore: initial tinytask import"). That is a
deterministic and useful fact, not a limitation: an unscoped run therefore finds **no hotspot**, and
the correct behaviour — widen the net and say so — becomes gradeable.

| # | Case | Mode | The observable it grades |
|---|---|---|---|
| 1 | `scan-only-renders-a-temporary-report` | pipeline | Unscoped run. An absolute path under the temp dir is printed and an `architecture-review-*.html` exists there; the file carries candidate cards with before/after evidence and a top recommendation, or a truthful no-candidate statement; the output discloses that history yielded no hotspot and the scan widened; the repository is untouched — clean `git status`, `HEAD` still at `origin/main`, the branch inventory unchanged, no new worktree, and nothing written under the fixture. |
| 2 | `clear-selection-reaches-a-design-worktree` | pipeline | Prompt names a concrete area and carries the selection up front. An isolated linked worktree exists off the fixture; `design` was entered and `grill-with-docs` named; `tinytask/` is unchanged in both the fixture and the worktree; no plan file exists; the output recommends `writing-plans` or `to-issues` without invoking either. |
| 3 | `foggy-selection-routes-to-wayfind` | pipeline | Prompt carries a deliberately unstatable destination (the fixture's documented cross-machine-sync fog). A new effort directory appears under `.claude/wayfind/` beside `concurrent-shells/`, which is left untouched; **no** design worktree was created; the output names `wayfind`; no spec is written. |

Assertions use the harness environment the runner exports — `OUT`, `REPO`, `WT`, `WT_COUNT`,
`SPEC_DIR`, `PLAN_DIR` — and the `assert-lib.sh` helpers, including `path_unchanged_since` for
proving no refactor executed.

No lower-level seam. No test for an internal scan helper, no assertion that a particular sub-agent
method was called, no grading of how a model phrases a candidate. The observable boundaries are
installation, the authored package's contract, and deployed workflow behaviour (parent D6, the-bar
"tests that can fail").

## Out of scope

- **Any `.nix`, `flake.nix`, or `justfile` edit.** Discovery is automatic; needing one is a defect
  in the plan, not permission to make one.
- **Any edit to `home/common/agent-skills/skills/codebase-design/`**, including adding the `policy`
  key to its `agents/openai.yaml` (per D3).
- Changing model tiers, role eligibility, any existing workflow scenario, or the existing
  four-family representative trace. The only validator/test expansion is the standalone
  `improve-codebase-architecture` family and its one-event scenario (per D5).
- **Editing `home/common/agent-skills/README.md`** (per D10).
- Importing upstream's `grilling` or `domain-modeling` skills, or reimplementing what
  `grill-with-docs` already owns.
- Bundling Tailwind or Mermaid for offline rendering; CDN use is an accepted constraint (parent D4).
- A flake input for the upstream repository, automatic upstream synchronisation, or any build-time
  or runtime fetch of skill text.
- Implementing any architecture candidate, or continuing into `writing-plans`, `to-issues`,
  `from-issue`, or `sdd` after the scope recommendation.
- Creating a `docs/` tree, context map, glossary, ADR directory, or standards deltas this repository
  does not have.
- The deployed-behaviour certification itself (AC7): it needs a human `just switch` and cannot be
  discharged by this branch's automated work.
- Editing the parent design document while landing it. It is a point-in-time accepted record and
  travels verbatim (per D4, the-bar "moves keep their history").

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Ship five files — `SKILL.md`, `HTML-REPORT.md`, `LICENSE`, `agents/openai.yaml`, `evals/evals.json` — with the report scaffold, diagram patterns and accessibility contract kept in `HTML-REPORT.md` as a lazily loaded sibling reference | Upstream splits its loaded body, report reference and Codex manifest; the repository's vendored-skill convention requires packaged provenance; issue #43 requires deployed evals; the-bar token economy | Inlining the report guidance into `SKILL.md`: pays ~6.7 kB of context on every run including runs that render nothing. Splitting routing or the scan brief into further files: the agent is mid-flight when it needs them, and the call must sit on the line after the marker |
| D2 | Ship `agents/openai.yaml` byte-identical to upstream — the two `interface` keys plus `policy.allow_implicit_invocation: false` — and drop the parent design's "default prompt" clause | Upstream at revision `9c9f36cc…` has no prompt key; no precedent in this tree; the Codex manifest schema is documented nowhere here; the-bar "verify before claiming done" | Inventing a plausible key: an unverifiable guess at a third-party schema that would ship broken metadata and be recorded as a departure that upstream never had |
| D3 | Leave `codebase-design` untouched; it gains no `policy` key | Issue-42 D3 reserved that key as "the explicit-only metadata interface that issue 43 owns", and #43's criteria scope explicit-only to *this* package | Adding it for symmetry: editing a just-merged sibling for a criterion that does not ask for it, widening the diff and the conflict surface |
| D4 | Commit the parent design document verbatim at `.claude/specs/2026-08-17-improve-codebase-architecture-design.md`, unedited | Both #42 and #43 link it at `blob/main/...` and it is on no merged branch, so every decision citation in both issues is currently dead; the-bar "moves keep their history" keeps accepted records byte-stable | Leaving it in the unmerged design worktree: D1–D6 stay unreachable from `main` and this spec's citations dangle. Editing it while landing it: invalidates a point-in-time accepted record |
| D5 | Register exactly one `improve-architecture-scan-owner` dispatch (issue-owner / opus / high / `general-purpose`, `requires: []`) and one `improve-codebase-architecture` workflow scenario containing that event; keep the existing representative trace unchanged and the package to one `Agent(` line | Issue #43 requires registered Opus/high dispatch; the phase contract requires a scenario; the matrix's closed-set design requires a real workflow to name its own family rather than masquerade as another | Omitting the scenario leaves a workflow dispatch unexercised. Filing it under `from-issue`, `orchestration`, or `representative` falsely says those traces always perform an architecture scan |
| D6 | Discharge AC3's starting-commit rejection with a new matrix contract requiring the workflow family, dispatch and scenario, while stating that the historical `just agent-model-matrix` remains green at its internally consistent base | The base validator predates this workflow and cannot reject what its closed set does not name; the-bar "tests that can fail" requires the added contract to turn red against the base matrix | Claiming the historical validator rejects the base: a falsification claim that does not reproduce. Editing `justfile` to manufacture a special gate: out of scope and duplicates the workflow suite |
| D7 | Put package/content claims in one appended `TestCase` in `test_workflow_skill_contracts.py`, reusing its helpers, and put workflow-family/scenario/trace claims in `test_agent_model_matrix.py` | Issue-42 D9 is the package-test precedent; existing test ownership separates authored-skill contracts from matrix schema and trace contracts; both files already run under `just agent-workflow-tests` | Putting all claims in one class: either makes the workflow-contract suite reimplement matrix validation or makes matrix tests parse unrelated package prose. A new test file: costs a `justfile` edit for no new seam |
| D8 | Keep upstream's frontmatter exactly — `name`, `description`, `disable-model-invocation: true` — adding and removing nothing | Both explicit-only controls are already upstream's at the pinned revision, so parent D2 costs no departure; issue-42 D14 kept the upstream description verbatim; a description is not a trigger for a skill that cannot be model-invoked | Retuning the description to this repository's voice: a departure to record and maintain, for a string no model matches against |
| D9 | Repoint every workflow reference at a skill that exists here (`doc-grounded-questions`, `worktrees`, `design`, `grill-with-docs`, `wayfind`), delete `grilling` and `domain-modeling`, and delegate upstream's inline `CONTEXT.md`/ADR side effects to `grill-with-docs` rather than reimplementing them | Parent design D1 and D5; those two upstream skills exist nowhere in this tree and are out of scope to import; the-bar DRY — `grill-with-docs` is already the authoritative home for glossary and ADR writes | Keeping upstream's names as aspirational references: a dead end at the skill's most important step. Reimplementing the side effects inline: a second copy of a policy that already has one home |
| D10 | Make no edit to `home/common/agent-skills/README.md` | §"Vendored skills" was written generically by issue-42 D12 so the second vendored package needs no second note, and it enumerates no skills; the adapter table describes per-project doc surfaces, which a machine-global skill does not affect | Adding a vendored-skills list: creates a registry that must be maintained on every future vendoring, which D12 deliberately avoided |
| D11 | Record grill outcomes that would normally be ADRs or glossary entries as rows in this ledger; no `docs/` tree, no ADR, no glossary | This repository has no doc surfaces and creating them is out of scope; the skill package itself is a better home for its own terminology than a glossary entry; issue-42 D13 set the precedent | Creating a `docs/` tree to hold them: fabricates a documentation surface this repository has deliberately never had |
| D12 | Three `pipeline` eval cases — scan-only, clear selection, foggy selection — none flagged `expected_today: "fail"`, with the fixture's single-commit history graded as the no-hotspot / widen path | Parent D6 seam 3 names exactly these three; the eval README documents that cases grade the deployed generation, so pre-`switch` failure is a harness property rather than a gap; `run-eval.sh` creates exactly one commit, making "widen" deterministic | Marking them `expected_today: "fail"`: the flag means "documented gap not yet closed" and would suppress a real regression after activation. A `plan-only` clear-selection case: AC7 wants the route actually walked, and `WT`/`WT_COUNT` make it assertable |
| D13 | State the candidate contract as zero to five, never padded, with a no-candidate report counting as a **successful** run | The issue's AC3 says "zero to five unpadded"; parent D3 says "two to five … one is valid; zero produces a truthful no-candidate report"; the-bar "truthful terminal states" | Parent's literal "two to five" as a floor: it would force padding in exactly the case the same paragraph forbids padding |
| D14 | Forbid `grilling` and `domain-modeling` as active workflow references in `SKILL.md` and `HTML-REPORT.md`, while retaining their names in `LICENSE` only to identify the upstream behavior that was replaced | D9 removes both dead runtime dependencies; the provenance contract simultaneously requires `LICENSE` to enumerate the downstream-step departure by name | A package-wide string ban: makes the required provenance record impossible and would test two contradictory contracts |
