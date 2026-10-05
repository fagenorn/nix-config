# Issue 235 — the committed retained review evidence bundle (DP226-EVIDENCE)

## Problem

Parent [226](https://github.com/fagenorn/nix-config/issues/226) promised
evidence about two retained deliveries that anyone can check without the
retained repositories. CORE
([233](https://github.com/fagenorn/nix-config/issues/233)) published the packer
and projector. DERIVE
([234](https://github.com/fagenorn/nix-config/issues/234), through
[248](https://github.com/fagenorn/nix-config/issues/248),
[249](https://github.com/fagenorn/nix-config/issues/249) and
[254](https://github.com/fagenorn/nix-config/issues/254)) published the
derivation and replay commands and proved them on scratch bundles. No bundle is
committed. The evidence still exists only where the retained objects and the
ignored issue-100 archive happen to be, and nothing in the repository says
which anchor digest a reader should trust.

This child, `DP226-EVIDENCE` / slug `retained-review-evidence`, is the third and
last delivery. It commits the five files, pins the trust identity outside them,
adds the regressions that replay and tamper with the committed copy, writes the
architecture sentence, and audits parent 226. Parent 226 stays open: this child
does not close it.

Immutable `DELIVERY_BASE`: `8971e41802fd2ee4de8d1c85626ea1cdcf2d384d`,
integration with published CORE and DERIVE. The bundle directory is absent
there.

## Binding designs

The [CORE spec](2026-09-30-issue-233-review-projection-core-design.md) (caps,
whole records, the generated-evidence rule), the
[REPLAY spec](2026-10-04-issue-249-retained-derivation-replay-design.md) (rows
RP2, RP7, RP8, RP10, RP11, RP14, RP24, its § *Replay and its command* and
§ *Delivery gates*) and the
[COMPACT spec](2026-10-04-issue-254-compact-retained-encodings-design.md) (rows
CP10, CP11, CP17–CP20) bind this child. It does not restate them. Rows prefixed
`EV` are this issue's decisions.

The reviewed tool commit (G2 pin) is
`691d8f257615c5698965918b3cca036c2e9ccec9`. Its `python` tree,
`6ce6afdda7b95e749184fcd8e132fc0a38de915e`, is also the base's.

## Measured feasibility

Measured on 2026-10-05, before any product work, by one read-only derivation
with the source command at the base, `--tool-commit` the G2 pin, against the
real retained objects under `/Users/anis/tmp/nix-config`. It took 118 seconds.
The scratch bundle is a measurement and is discarded: no byte of it is
committed (EV5).

| File | Bytes | Review record at the bundle directory (EV1) |
|---|---|---|
| `derivation-anchor.json` | 13,769 | 14,118 |
| `derivation-witness.json` | 15,891 | 16,243 |
| `issue-100-derived.json` | 62,118 | 62,467 |
| `issue-121.json` | 48,917 | 49,242 |
| `task7-estimate.json` | 43,757 | 44,097 |
| Total | 184,452 | 186,167 |

The records were measured by CORE's `actual_inputs_from_trees` over a scratch
commit that adds the five files. Each is a whole record with no
generated-evidence summary, and none changes with the context-line choice. The
largest sits 3,069 B below the 65,536 B member cap. The five need four of the
eight payload members.

Other observations from the same bundle:

- Anchor digest
  `sha256:d0968f6a9ca20160bd027bb3ce12b5231efa603057a054a76fe37e5f4870a8a5`.
- Sealed source replay (scratch `cwd` and `HOME`, an empty `PATH`): exit 2,
  empty stdout, `replay-retained: projection_unavailable: tasks-1-3,tasks-4-6`.
- Outcomes: `aggregate.actual` and `aggregate.projected` are measured and
  `over_budget`; `tasks-1-3` is unavailable with `whole_path_preimage_unproved`;
  `tasks-4-6` is unavailable with `dependency_unavailable`; `tasks-7-8` is
  measured and `within_budget`.
- A one-sentence edit of the `CLAUDE.md` paragraph on the agent helper package
  is an 11,747 B record at the default context, because its neighbours are very
  long lines.

**Headroom.** The rest of the delivery is this spec, the plan and its members,
one new test module, one support module, small edits to three existing files,
the `CLAUDE.md` record and the audit: about 130 kB by REPLAY's and COMPACT's
prices, against about 338 kB and four free members. This is an estimate. The
committed plan's G0 decides (EV8).

## Solution

No module, command, option or recipe is added, and no byte under `python/`
changes (EV10).

| Element | What it is |
|---|---|
| Bundle | `tests/fixtures/retained-review-evidence/`, holding exactly the five files as the derive command wrote them (EV1) |
| Trust pin | `tests/retained_evidence_test_support.py`: standard library only. It holds the bundle path and the literals `ANCHOR_SHA256` and `TOOL_COMMIT`, and nothing else (EV2) |
| Portable suite | `tests/test_review_evidence.py`, listed in `agent-workflow-tests` (EV3) |
| Built cases | New cases in `AgentToolsLauncherTest`, run by `agent-installed-skill-tests` (EV3) |
| Reproduction case | One new case in the full-shape tier, run by `agent-retained-tests` (EV4) |
| Architecture sentence | One sentence in `CLAUDE.md` (EV9) |
| Parent audit | `.agents/artifacts/specs/2026-10-05-issue-226-parent-audit.md` (EV7) |

## Decisions

### Publication

The publication task runs only after G0 has cleared (EV8). It is the one place
committed bytes come from.

1. **Host basis.** Before each derivation the runner records that the host has
   no Git attribute or diff setting that changes CORE's record view: no
   `.gitattributes` in the tool checkout or the retained root, no
   `info/attributes` in either Git directory, no `~/.config/git/attributes`, no
   `core.attributesFile` and no `diff.*` setting at any configuration scope.
   Any of them present stops publication.
   [Issue 255](https://github.com/fagenorn/nix-config/issues/255) is open, so
   the two-derivation result holds on this basis and no wider one (RP24). The
   design-time check on 2026-10-05 found none.
2. **Derivation A**, by the task's implementer: the source command, in the
   matching source environment, `--tool-commit` the G2 pin, into a fresh scratch
   directory. Its five files are copied byte for byte into the bundle directory
   and committed with the trust pin. The committed blobs, read back from Git,
   must equal A's files, so no hook or filter touched them.
3. **Derivation B**, by a fresh actor who did not run A: the built launcher,
   with both issue repositories a separate disposable `git clone --shared` of
   the retained root and the archive read from the root, into another scratch
   directory. B's five files must equal the committed blobs byte for byte, and
   B's summary must equal A's.
4. **Three digests agree.** A's and B's `anchor_sha256` must both equal the
   digest in § *Measured feasibility*, and that value is the literal committed
   as `ANCHOR_SHA256`. A different value is never adopted silently: the task
   stops, names the bound identity that moved (tool closure, a policy digest, a
   retained input) and returns it to the issue that owns it.
5. The retained root is compared before and after A and B (RP11). A changed
   root voids the run.

The committed files are never edited, reformatted or re-encoded. A later change
is a new derivation under this same protocol.

### Trust identity

Replay trusts one value: the digest its caller passes (parent D6). For the
committed bundle that value is the literal `ANCHOR_SHA256`. Three properties
make it independent of the bundle:

- **It is outside the bundle.** The literal lives in a hand-written source
  file. No test, recipe or document computes the expected digest from the
  committed anchor or reads it from the bundle directory. Replacing all five
  files with another coherent bundle therefore fails `anchor_digest`.
- **It is rooted in reviewed identities.** The anchor it names binds the tool
  closure at the reviewed G2 pin, both retained ranges, the archive identities,
  the estimate identities and three policy digests. `validate_bundle` checks
  every group the pins determine. The portable suite also requires
  `tool.commit` to equal the literal `TOOL_COMMIT`. The members no Git-free
  check determines (`tool.files`, `archive.shards`, record bytes) are proved by
  the reproduction case, which derives them again from the objects.
- **It was fixed before the bundle existed.** This spec records the digest
  from a design-time derivation, and publication requires two further
  independent derivations to reproduce it.

The construction stays acyclic, as REPLAY built it: no payload names the anchor
and the anchor is in no payload. The pin sits outside `python/agent_tools/`, so
the tool closure the anchor hashes does not contain the anchor's digest.

### Committed-copy replay

Every case copies the committed directory into a scratch directory first, so no
case can change a tracked file. Replay runs sealed, as CP19 defines it: scratch
`cwd` and `HOME`, a `PATH` of one empty directory, and neither `git` nor
`artifact-budget` findable. The launcher module's existing sealed pair runs the
built cases. Replay runs no Git, so the copy is replayed away
from the retained repositories wherever the suite runs. In CI the retained
issue-121 objects and the archive do not exist at all.

The authentic outcome is asserted exactly, from source and from the built
launcher, and the two must be equal:

```
exit 2, empty stdout, stderr "replay-retained: projection_unavailable: tasks-1-3,tasks-4-6\n"
```

Reaching that line is itself the proof of order: replay authenticates the
anchor and the four members, runs the full semantic validation of every
payload, and only then classifies (REPLAY § *Replay and its command*).

### Committed facts

The portable suite authenticates the copy under `ANCHOR_SHA256`, runs
`validate_bundle` with the real pins and asserts these facts on what it
returns. Each number is a literal in the test, not a value read from a pin
constant.

| Payload | Asserted facts |
|---|---|
| Issue 121 | 30 assignments in range order: 12 process pairs equal to parent 226's table, commit and reason, and 18 task assignments to tasks 1–6. One Task-3 assignment follows the last Task-6 assignment (the late fix). 30 ordered edges, each on its assignment's commit. Five outcome rows. The two unavailable rows hold `failure` with a stage, a code and evidence references, and hold no `measurement` and no `result_tree`. The three measured rows hold a measurement with all four metrics and their real budget status: both aggregates `over_budget`, `tasks-7-8` `within_budget`. No row holds a recommendation |
| Task 7 | 173 rows with 173 distinct final paths: 165 moves (54 specs, 108 plans, 3 decisions), 5 rewrites and 3 additions. Every row holds finite non-Boolean integer bounds. The pinned identities equal the anchor's `estimate` group. `observed_actual` is `null`. The operational effects are exactly one row: Task 8, zero repository bytes, `unexecuted`, `post-integration-registration-evidence` |
| Issue 100 | 543 edge records over 91 parent edges, 115 contributions, 8 historical-process, 38 integrated and 69 candidate, 4 pending overlaps, 0 reconciled. Ten criteria, five `governing` and five `superseded`. The historical domain is 1,005,707 B in 115 records and the fresh domain is 1,012,913 B in 115 records, under different policies |

Positive fit and recommendation behaviour stays where CORE proves it, on
declared independently reconstructible fixtures in CORE's portable suites. The
bundle holds historical measurements and refusals only.

### Tamper and incomplete copies

Each row changes a scratch copy. Under the trusted digest it is replayed
through the source command, and the result is exact: exit 2, empty stdout and
one stderr line `replay-retained: invalid: <code>`. "Injected" means the
forger's own anchor digest is trusted instead, which reaches the semantic layer
(RP7). Injected rows call `validate_bundle` as the tier does and require the
error class the tier's table names. The rows with a code below also go through
the command with the forger's digest as the expected digest, and print that
code.

| Change to the copy | Under `ANCHOR_SHA256` | Injected |
|---|---|---|
| One byte changed in a payload member, each of the four in turn | `member_digest` | — |
| One byte changed in the anchor | `anchor_shape` or `anchor_digest`, fixed per case | — |
| A member removed; an extra file; a member replaced by a symlink; a member truncated | `member_set`; `member_set`; `member_set`; `member_digest` | — |
| Replacement anchor: another coherent anchor over the unchanged members | `anchor_digest` | — |
| Each site of the tier's trusted-site table (a tool, range, archive and estimate identity, a record digest, an edge reference), every in-bundle hash recomputed | `anchor_digest`; with the trusted anchor restored over the changed members, `member_digest` | as the next row where the pins determine the site |
| Each site of the tier's Git-free table: tree, signer, range, archive, estimate and policy identities; assignment, anchor and record rows | `anchor_digest` | the error class the table names for the site: `WitnessError`, `EstimateError`, `ContributionError` or `Issue100Error` |
| Each rehashed forgery: a missing edge, a reordered edge and a duplicate record per retained payload; each payload in SOURCE's encoding | `anchor_digest` | `invalid_payload` |
| Malformed issue-100 beside the unchanged issue-121 refusal; the estimate truncated by a row | `anchor_digest` | the owning module's refusal through the command, `invalid_payload` for issue 100, and never `projection_unavailable` |

The tables are the ones the full-shape tier already runs over a real bundle
(`TRUSTED_SITES`, `GIT_FREE_SITES`, `REHASHED_FORGERIES`, with `substituted`
and `rebuilt`). The portable suite imports them from the tier module and runs
them over the committed copy, so one table describes one real bundle (EV6).

`tool.commit`, `tool.files`, `archive.shards` and a re-measured record's bytes
or digest are not determined without Git (RP7, RP16, CP17). The trusted digest
and the reproduction case refuse them. No row claims a Git-free refusal for
them.

**Built cases.** The launcher module imports no `agent_tools` in the installed
tier (CP18), so its cases build their changes with `json` and `hashlib` alone.
Each compares the built launcher with the source module, sealed, and requires
equal exit, stdout and stderr: the authentic copy; one changed member byte
(`member_digest`); a removed member (`member_set`); a replacement anchor
(`anchor_digest`); and a malformed issue-100 member with the witness fixture
row, the anchor member row and the digest recomputed, injected
(`invalid_payload`).

**Leaks.** The committed bytes hold no absolute scratch or home path, no key
material marker and no line of the artifact-budget policy file. The tier's leak
check, which needs the archive for shard body lines, covers the same bytes
through the reproduction case.

### Reproduction from the retained objects

One new case in the full-shape tier derives the bundle again and requires the
five files to equal the committed five byte for byte, and the summary's
`anchor_sha256` to equal `ANCHOR_SHA256`.

It derives with the reviewed tool, not with the checkout's: a disposable
`git clone --shared` of this checkout is checked out at `TOOL_COMMIT`, and the
package, the budget helper and its policy all come from that clone (EV4). The
committed evidence therefore stays reproducible after `python/` moves on, and
the case fails only when the retained objects, the archive or the host basis
changed. The case never reads `AGENT_RETAINED_TOOL_COMMIT`; the class setup
keeps its selector (EV14). The tier's other cases keep their meaning. The case runs under the recipe's no-skip rule and the root
comparison (RP10, RP11).

### Architecture sentence

One sentence joins the `CLAUDE.md` paragraph on the agent helper package. It
names the bundle directory, the two commands, the file that holds the trusted
digest, and the fact that an authentic replay of this bundle exits 2 as
`projection_unavailable`. It does not repeat the digest (EV9). No projection is
regenerated: `bootstrap.md` is untouched.

### Parent audit

The audit is a committed document, written in the last task and read by both
final reviewers (EV7). One table row per item, and every item of these sources
has a row:

- each clause of parent 226's eight acceptance criteria, the 2026-09-29
  amendment and each decision bullet that states a checkable requirement;
- the three original Important findings (incomplete issue-121 attribution,
  invalid boundary graphs, unchecked witness identities);
- every residual finding the children recorded: the grafted-ancestry finding,
  248's same-commit swap, 249's attribute finding, 254's expansion-cost
  finding, and the children's Minor findings by reference to their delivery
  detail.

Each row names the owning child, its merged pull request and merge commit, and
the test or artifact that proves the item. A row is `delivered`,
`open follow-up` with the tracking issue's URL, or `unmapped`. The verdict line
says parent 226 may close only when no row is `unmapped`, and lists the open
follow-ups ([255](https://github.com/fagenorn/nix-config/issues/255),
[256](https://github.com/fagenorn/nix-config/issues/256)) as residuals the
parent's closer must accept or keep open for.

Rows owned by this child cite its tests and its branch commits, which the merge
strategy preserves. After the merge the controller posts the verdict on issue
226 with a link to the document at the merge commit. The pull request closes
issue 235 only. Closing 226 is a separate act after that post.

### Delivery gates

REPLAY's § *Delivery gates* applies with this child's base, as follows (EV8).

- **Closure check.** No commit this child authors changes a path under
  `python/`, checked before every gate. Up to and including publication,
  `HEAD:python` must also equal the G2 pin's `python` tree. This is what "both
  reviewed source closures" means here: CORE and DERIVE as reviewed at the pin
  are the code that projects, packs and derives. A failure stops the delivery.
  A source defect goes back to the issue that owns the module, G2 repeats
  there, and this child re-pins and regenerates (issue 235, decision 2). There
  is no G2 in this child because it changes no source. A later integration
  sync may bring another issue's `python/` change: the committed evidence
  stays bound to the pin (RP8, EV4), and the gates then run with integration's
  published CORE.
- **G0, projection.** A v3 plan with `derived_from: null`, its members and
  honest forecasts are committed. Published CORE's
  `review-feasibility project` clears it at `--completed-through 0` before the
  publication task, validated with `validate-result` and reproduced by a second
  run. The forecast charges this spec, the plan root and members, every subject
  reserve, each task's records, the shared paths more than one task touches,
  and the five bundle files as ordinary whole records. Each bundle record's
  bound is its measured size above, never less. It is renewed at
  `--completed-through N` after each accepted task and after any plan, spec or
  forecast change (RP14). Exit 2 or 3 stops with no bootstrap.
- **G1, actual.** The complete fixed-base `review-package` after every task and
  every fix and at the final head, validated and independently checked with
  equal metrics. It overrides every forecast. The bundle files are measured as
  the records they are: no generated-evidence exemption applies or is added.
- **Actual-only equality.** At the final head, with every task complete, the
  projection's four metrics equal the actual package's.
- **G3, final.** The portable suite alone, then `just agent-workflow-tests`,
  `just build`, `just agent-installed-skill-tests` and
  `just agent-retained-tests /Users/anis/tmp/nix-config`, the last on a
  quiescent root. The installed run's verbose log must show each new built case
  as `ok`: a skipped case is not acceptance. Then separate
  authorship-independent conformance and correctness reviews of the whole
  fixed-base delivery. Required CI stays the merge gate. Nothing is activated.

## Test seams

The existing seams and no others: modules imported under the recipe's
`PYTHONPATH`; commands as `python -m agent_tools.<module>`;
`tests/test_agent_tools_launchers.py` as the only module that touches built
launchers; the full-shape tier under `just agent-retained-tests`. The new
support module follows the `*_test_support.py` precedent and imports no
`agent_tools`. `source_budget_env` gains an optional source root for the
reproduction case. No test reads a private name.

| Issue criterion | Design element | Falsifiable verification |
|---|---|---|
| 1. Five outputs committed as exact canonical bytes; reviewed identities; independent acyclic anchor; two derivations identical; absent at base | § *Publication*; § *Trust identity* | Derivations A and B and the design-time digest agree, recorded with the host basis. The reproduction case passes. Authentic replay passes, which requires canonical members and an authentic anchor. `git ls-tree` of the base shows no bundle directory, and the portable suite fails there |
| 2. Issue-121 facts | § *Committed facts* | The issue-121 row, as literals |
| 3. Task-7 table; Task 8 unexecuted | § *Committed facts* | The Task-7 row. `validate_task7` rebuilds the whole table from its facts and the pins, so an unsupported bound fails validation before any fact is read |
| 4. Issue-100 facts; distinct domains | § *Committed facts* | The issue-100 row |
| 5. Source and built replay agree away from the repositories; validation before the unavailable exit; malformed sibling; tamper refusals; no leaks | § *Committed-copy replay*; § *Tamper and incomplete copies* | The exact authentic triple from source and built; every table row with its exact code; the built cases; the leak case |
| 6. Complete forecast; projection before publication; actual gate after every task and fix; actual-only equality | § *Delivery gates* | G0 result at 0 dated before the publication commit; a G1 result per task, per fix and at the final head; equal metrics at the final head |
| 7. Focused, full, build and installed runs with no skip as acceptance; independent reviews; parent audit | § *Delivery gates*; § *Parent audit* | G3 logs with the named cases `ok`; two review records; the audit holds no `unmapped` row and the pull request names no closing keyword for 226 |

## Risks

- **Issue-100 record headroom is 3,069 B.** The directory name is part of the
  record's header, so a longer path spends it. EV1's path is 40 characters.
- **A policy or closure change before publication** moves the digest.
  Publication step 4 stops rather than re-pins.
- **The reproduction case costs about two minutes** in a tier that already
  takes about 25.
- **A forged member can make expansion do unbounded work before a pin check**
  ([256](https://github.com/fagenorn/nix-config/issues/256)). It is reachable
  only under an injected digest and fails closed. The trusted digest refuses
  such a member at once.

## Out of scope

Any change under `python/`; a new command, option, module or recipe; caller
adoption; issue-121 registration; issue-100 reconciliation or activation; host
activation; executing Task 7 or Task 8; any cap, bound or packing-policy
change; a generated-evidence exemption for the bundle; a reader for old
encodings; [255](https://github.com/fagenorn/nix-config/issues/255) and
[256](https://github.com/fagenorn/nix-config/issues/256); closing parent 226.
Nothing writes the retained root, its object store, the archive, parent
evidence or lifecycle state.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| EV1 | The bundle is `tests/fixtures/retained-review-evidence/`, holding exactly the five files and nothing else | The retained suites and `tests/fixtures/` live under `tests/`; replay's `member_set` refuses any sixth file, a README included; measured: the largest record is 62,467 B at this path | `.agents/artifacts/evidence/`: adoption's counted record directory, read by `adopt_inspection`. `python/agent_tools/`: the tool closure would contain the bundle, a cycle. `home/common/agent-skills/tests/fixtures/review-feasibility/` (the 226 plan's path): the legacy tree, and a longer header on the tightest record |
| EV2 | The trusted digest is one literal, `ANCHOR_SHA256`, in a standard-library test-support module outside the bundle, beside the literal `TOOL_COMMIT`. Nothing computes it from the bundle. Its value is recorded in this spec before publication | Issue 235 ("payload-selected trust is invalid"); 226 design ("a caller obtains the anchor identity from independently reviewed committed evidence"); parent D6; CP11 (no output digest in the tool); CP18 (the launcher module imports no `agent_tools`) | A digest file in the bundle directory, or a digest computed from the committed anchor: the payload selects its own trust. A constant in `agent_tools`: out of scope, and the closure the anchor hashes would hold the anchor's digest. The plan's `derived_from`: the anchor does not exist at G0, and a delivery record is not a living pin |
| EV3 | Three tiers. The portable suite joins `agent-workflow-tests` and so runs in CI. Built cases join the existing launcher class under `agent-installed-skill-tests`. Reproduction joins the full-shape tier. The only recipe edit is one line | Parent D8 (two tiers plus the installed module); agent-helper standard 5; CI is source-only and has no retained objects, which is exactly "away from the retained repositories" | A dedicated evidence recipe: a fourth entry point nobody asked for. Portable cases only in the retained tier: the committed copy would never be checked in CI |
| EV4 | The reproduction case derives with the tool, budget helper and policy checked out at `TOOL_COMMIT` in a disposable shared clone, and ignores `AGENT_RETAINED_TOOL_COMMIT` | RP8 (later tools must still replay committed evidence); the closure is the whole package, so any later `agent_tools` change makes the checkout's own derivation refuse `tool_closure`; the anchor binds the policy digest | Deriving with the checkout's package: the first unrelated package change would force a 186 kB republication or leave the case permanently red |
| EV5 | Publication is two derivations by different actors, A from source and B from the built launcher in a separate clone, plus the design-time digest. All three must agree, on a host checked for attribute and diff settings. The design-time bundle is discarded | Issue 235 criterion 1; RP24 and issue 255 (the limitation is stated, not waived); RP11; 254's G2 precedent of an independent reproduction | One derivation checked by the tier's own two-run case: one actor and one environment. Committing the design-time bundle: generation before G0 |
| EV6 | Committed-copy cases assert named outcomes and literal facts, and the tamper cases reuse the tier's site tables through the public command. Refines REPLAY's "never a named status", which governs fresh derivations | The committed bytes are fixed by the digest, so their outcome is a fact; the-bar *Tests that can fail* and DRY; RP7 (two layers; what Git-free checks cannot determine) | Reading the expected ids from the payload: the case passes for any bundle. A second copy of the site tables: two descriptions of one bundle |
| EV7 | The parent audit is a committed document in the specs directory, with one row per requirement clause, original finding and residual finding. The controller posts its verdict on issue 226 after the merge. The pull request closes 235 only | Issue 235 criterion 7; `2026-09-19-harness-backlog-audit.md` (an audit in this directory); 234's audit table as the row shape; merge commits preserve branch SHAs | A tracker comment alone: the final reviewers cannot review it inside the delivery. A section of this spec: written before the evidence exists |
| EV8 | Gates: no authored `python/` change and, through publication, the pin's `python` tree at `HEAD`; G0 at 0 before publication with each bundle record bounded at its measured size, G0 advanced per RP14, G1 after every task and fix, actual-only equality at the end, G3. No G2. `derived_from` stays `null` | Issue 235 criterion 6 and decision 1; REPLAY § *Delivery gates*; RP14; 226's own plan kept `derived_from: null` with committed fixtures | Repeating G2 with no source change: a review of bytes already reviewed. A rounded-down or omitted bundle forecast: a lower forecast manufacturing a pass |
| EV9 | The `CLAUDE.md` sentence names the bundle, the commands, the pin's file and the expected exit. It does not hold the digest | Parent D16 (EVIDENCE owns the sentence); the-bar DRY; measured 11,747 B for the record | The digest in `CLAUDE.md`: a second copy that no test reads |
| EV10 | No `python/` byte, command, option or recipe is added. `source_budget_env` gains an optional source root, a test-support change only. The installed recipe is not changed to refuse skips; G3 checks the named cases in its log | Issue 235 scope (source defects go to the owning issue); the-bar YAGNI; that recipe runs suites this issue does not own | A `--verify` or digest option on `replay-retained`: a source change and a second trust channel. A skip refusal in the shared recipe: it could break suites outside this scope |
| EV11 | The late Task-3 fact is asserted as the literal owner sequence of the eighteen task assignments: commit `8e6f0681908cb1ba3d352be5d26540dab731ffeb` is assignment 25 of 30, after five Task-6 assignments and before the last one. Refines § *Committed facts*, which says it follows the last Task-6 assignment | Read from a bundle derived at the pin during planning; the tier's own case asserts position 24 "after Task 6 began"; EV6 | Asserting the sentence as written: false on the authentic bundle, so the case could never pass |
| EV12 | In the parent audit, the clauses that can only become true at this child's merge (the final reviews, required CI) share one row, `open follow-up` tracked by issue 235, and the verdict line is conditional on that merge. The controller confirms the condition when it posts the verdict. Refines EV7 | EV7 (the reviewers read the audit, so it is written before their verdicts; the post follows the merge); the-bar *Truthful terminal states* | `delivered` for reviews that have not happened. An audit commit after the final reviews: it moves the head both reviews accepted |
| EV13 | Three bundle files (`issue-100-derived.json`, `issue-121.json`, `task7-estimate.json`) hold legacy policy names as facts of the retained ranges. The publication task lists them, with their exact tokens, in `LEGACY_MIGRATION_INPUTS` of `home/common/agent-skills/tests/test_workflow_skill_contracts.py`. Refines § *Solution*: this is a fourth existing file with a small edit | Found at planning: `test_living_source_has_no_legacy_policy_surface` scans every tracked JSON file under `tests/` and fails on the bundle; that table already exempts `review_task7.py` and `review_issue100.py` for the same names, and an entry whose token is no longer seen fails the scan | Moving the bundle outside `tests/`: reverses EV1 and changes the measured record headers. A prefix exemption for the directory: any later file there would pass unread. Changing a bundle byte: forbidden |
| EV14 | Refines EV4: the reproduction case itself never reads `AGENT_RETAINED_TOOL_COMMIT`, but it stays in `RetainedFullTest`, whose setup still refuses a named commit whose `python` tree is not `HEAD`'s. The tier is run with the variable unset (the recipe never sets it) or naming such a commit; the plan and the case's docstring claim no more | Plan review S1 (Codex): `tool_commit()` in `tests/test_review_retained_full.py` raises in `setUpClass` before any case runs; parent D17 owns that selector; after `python/` moves on, an unset variable selects `HEAD` and the case still derives at `TOOL_COMMIT` | A separate class with its own setup: duplicates the input and root checks and enlarges the forecast records to serve an invocation the recipe never makes |
| EV15 | The portable leak case matches the policy in the bundle's canonical encoding (each dict-valued entry, and the policy as an escaped string), with a positive control. Supersedes Task 2's authored policy-line needles | Task-2 review: pretty-printed lines hold `": `, which canonical JSON never does, so the authored clause could not fail | Keeping the plan's text: a vacuous assertion under § *Leaks* |

Design and grill frontier: closed within the approved scope. The resolved
bindings carry no context-map or ADR route, so this ledger is the issue's
decision store.
