# Codex reviewer bridge: per-operation timeouts, PATH, and finding hygiene

Issue: [fagenorn/nix-config#104](https://github.com/fagenorn/nix-config/issues/104)
Phase 2 (brainstorm) + Phase 3 (grill), autonomous. Risk lane: full.

## Problem

The Claude→Codex reviewer bridge is the machine that runs `from-issue` Phase 5
plan-review and the diff review's correctness axis. Three complaints make its
output unreliable and expensive:

1. **One budget for two operations.** The bridge gives every reviewer job the
   same 840 s wall. A material share of plan-reviews are killed mid-sentence
   against it, discarding fourteen minutes of xhigh-effort work and then paying
   for a full Opus fallback review anyway. (The issue attributes this to
   plan-review being the slower operation; the Evidence section below shows the
   kills are real but that framing is not the one the data supports.)
2. **A helper the reviewer reports as unavailable.** Reviewer transcripts say
   `artifact-budget` could not be run, so the reviewer falls back to trusting
   supplied numbers and spends turns saying so.
3. **The sandbox's limits arrive as review findings.** The reviewer runs
   read-only. Test runners and mutation checks fail inside it, and the reviewer
   writes each failure up as a structural gap shaped exactly like a real
   finding, which the Claude side then has to disposition as noise.

The through-line is a **contract mismatch**: the bridge tells the reviewer to do
work whose cost and whose permissions the bridge never sized for it. The budget
is sized for the cheaper operation, and the packet asks for verification the
sandbox forbids.

## Evidence

Two independent measurements were taken for this spec, both on the current build
(pinned rev `db52e28f`, `patchRevision = 10`, store path `…-nix.db52e28f.p10`).
Full transcripts are summarised in this worktree's `GROUNDING.md` cache.

**Survey — 83 review job records** under
`~/.claude/plugins/data/codex-nix-codex/state/*/jobs/`:

| Operation | completed | timed out at 840000 ms | worker died without a result |
|---|---|---|---|
| plan-review | 60 | 10 | 7 |
| diff-review | 5 | 1 | 0 |

Plan-review completed-run durations: min 154 s, p25 330 s, median 475 s,
p75 668 s, **p90 730 s, max 820 s**. The distribution is dense right up to the
840 s wall and then stops — the signature of right-censoring, not of a
population that happens to finish in time. Diff-review's sample is six jobs and
supports no conclusion about its own distribution. No record was ever
`completed` with a null result: a killed job is recorded `failed` with
`Codex job timed out after 840000ms.`

These numbers differ from the issue's (median 604 s / 391 s, "10 of 35") because
the issue surveyed a 14-day window and this survey covers every retained record.
The absolute count the issue reports — **10 plan-review timeouts** — reproduces
exactly. The medians and the ratio do not, and the diff-review median here is
*higher* than plan-review's. Section "Decisions / Reviewer budget" says what that
does and does not license.

**Live probes — two real reviewer jobs** dispatched through
`codex-companion task --fresh --reviewer diff-review`, asked only to run shell
commands and report the raw transcript:

| Probe | Result |
|---|---|
| `echo $PATH` | contains `/Users/anis/.agents/bin`, ahead of the system entries |
| `command -v artifact-budget` | `/Users/anis/.agents/bin/artifact-budget` |
| `command -v python3` | resolves |
| `ls -la "$HOME/.agents/bin"` | all seven helper symlinks visible |
| `artifact-budget check --kind design-spec --root <a real spec> --format json` | **exit 0**, valid `within_budget` JSON |
| `gh --version` | exit 0 |
| `mktemp -d` | **exit 1**, `Operation not permitted` |
| `python3 -c 'tempfile.mkdtemp()'` | **exit 1**, `No usable temporary directory found` |
| `echo $TMPDIR` | set, and unwritable |

**Two of the issue's three diagnoses are corrected by this evidence.**

- Defect 2's stated mechanism — "`artifact-budget` is not on the reviewer's
  PATH… exit 127" — **does not reproduce.** It is on PATH and it runs clean.
- Defect 3's mechanism reproduces exactly, and it is the *same* root cause the
  reviewer transcripts blamed on the helper: sandbox `read-only` denies **every**
  write, including `TMPDIR`. Anything that needs scratch space dies, and a model
  that hits a wall of `Operation not permitted` reasonably concludes the tooling
  is unavailable and says so.

The-bar's *Root causes* rule applies: symptom-shaped evidence is good at proving
a mechanism wrong and bad at telling you which knob is right. It proved defect
2's mechanism wrong. The design below still delivers defect 2's acceptance
criterion, but as a guarantee rather than as a repair, and it says so plainly.

## Terms

Four clocks are involved and the prose below keeps them apart. Conflating them
is how the current coupling defect was written in the first place.

- **Reviewer budget** — the worker's own bound on one Codex turn. Its clock
  starts *after* spawn, runtime seeding and app-server connect, not at enqueue.
  This is the constant the issue calls "the 840s budget", and the only quantity
  this design re-sizes.
- **Job deadline** — the advisory timestamp recorded on the job at enqueue,
  computed as enqueue time plus the reviewer budget. It is deliberately earlier
  than the budget's true expiry by the startup interval, which is why a healthy
  job can read as overdue. Nothing may treat it as an enforcement point.
- **Transport wait ceiling** — the sum of the transport agent's bounded waits.
  Its clock starts at enqueue, so it must exceed *startup plus the reviewer
  budget*, not the budget alone.
- **Per-call wait bound** — the 540 000 ms passed to a single `status --wait`,
  sized under the Bash tool's 600 000 ms cap on one call. Unchanged by this
  design; only the number of such calls changes.

"Timeout" is avoided as a bare noun; every occurrence below names one of the four.

## Solution

One organising principle, applied three times:

> **Give each obligation exactly one authoritative home, and make every other
> party either derive from it or stop restating it.**

- The **reviewer budget** gets one home in the bridge runtime, keyed by
  operation. The transport agent stops naming a budget at all. The caller-facing
  contract keeps one deliberate, test-pinned restatement, because callers plan
  wall clock around it and prose cannot be derived from a patch.
- The **`~/.agents/bin` guarantee** gets one home in the repo-owned
  `codex-companion` wrapper — the seam where this machine's toolchain meets an
  upstream plugin — rather than being hardcoded into the plugin patch or left to
  ambient shell inheritance.
- The **read-only boundary** gets one home in the shared rubric: the reviewer is
  told once that sandbox limits are reported through the existing "could not
  verify" channel and never as findings, and the packets stop handing it
  verification it is forbidden to perform.

Nothing here widens the isolation model. The reviewer stays fresh-`CODEX_HOME`,
approval-`never`, sandbox-`read-only`.

## Decisions

### Reviewer budget

`plan-review` gets a **1 680 000 ms** reviewer budget. `diff-review` **stays at
840 000 ms**. The pair is not merely a lookup table bolted beside the existing
constants — it becomes the **reviewer operation registry**: the single place
that says which review operations exist *and* what each one costs, and it lives
in its own small runtime module rather than inline in the CLI entrypoint.

That placement is forced, not stylistic. The CLI entrypoint invokes its `main`
at module scope and exports nothing, so a test cannot import a constant from it
without running the CLI. A registry the tests cannot read is a registry whose
agreement with its consumers cannot be asserted — and an unassertable budget
constant is precisely the defect this issue is repairing. The patch already adds
sibling runtime modules for exactly this kind of extracted concern, so the shape
has precedent. The-bar's rule is to split when the second concern arrives: it has
arrived, because the tests now need the value and the entrypoint cannot hand it
over.

The closed set the runtime validates against is derived from the registry's keys,
so an operation cannot exist without a budget and a budget cannot exist for an
operation the runtime rejects. Naming it a registry makes that coupling
deliberate: the-bar's *Fail loud* rule wants a closed-set dispatch with no
missing arm, and deriving the set structurally is stronger than adding a throw
to catch a missing one. An explicit `--timeout-ms` still overrides, and
non-reviewer tasks still default to no bound at all.

Two options were weighed for the values.

- *Considered — raise both to one larger constant.* Simplest edit, and it would
  have covered the one diff-review timeout in the sample. Rejected: it preserves
  the one-size-fits-all defect the issue exists to remove, and it slows the fast
  operation's failure detection for no measured reason.
- *Chosen — 2× for plan-review only.* This honours the issue's stated intent and
  matches the censoring evidence, which is asymmetric: ten plan-review kills
  against one diff-review kill, and a plan-review population whose p90 sits at
  730 s against an 840 s wall.

The observed diff-review median (520 s, n = 5) is higher than plan-review's
(475 s, n = 60), which contradicts the issue's premise that plan-review is the
slower operation. **That contradiction is not a reason to move diff-review's
budget**, because six jobs cannot size a wall, and it is not a reason to withhold
plan-review's increase either, because the increase rests on the censoring
signature and the kill count, not on the median ratio. Diff-review is left
untouched — the smaller, more reversible call — and the spec records the
contradiction so a later pass with more diff-review data can revisit it on
evidence rather than on the issue's prose.

**Expected effect, stated so it can be checked.** The check is the same
job-record survey, re-run once enough plan-reviews have landed on the new build,
comparing kills recorded at 1 680 000 ms against this spec's baseline of ten at
840 000 ms. It is deliberately **not a merge gate** — the data does not exist at
merge time, and inventing a gate the branch cannot satisfy is how a plan acquires
an unfalsifiable step. It is the issue's follow-up evidence. If kills reappear at
1 680 s the wall was never the constraint, and the next investigation is the
reviewer's own turn behaviour, not another doubling.

Two runtime facts bound the choice and are worth recording so a future re-size
checks them. The recorded job deadline is suppressed entirely for any budget above
the runtime's maximum enforceable delay — the honest report for a bound the timer
cannot honour is no deadline at all — and 1 680 000 ms sits three orders of
magnitude below that limit, so overdue reporting keeps working. And because each
job record carries the budget it was enqueued with, jobs already in flight when
the new build lands keep their old bound and terminate normally; there is no
migration and no in-flight hazard.

**Cost.** A doubled budget doubles the worst-case spend on a job that times out
anyway. Today that spend is *additive* to a full Opus fallback, because a killed
review still triggers one; reducing the kill rate removes both. Net expected
cost falls. The recorded job deadline needs no separate change: it is already
computed from the request's own bound, so it tracks the per-operation value for
free.

### The transport agent's wait ceiling

This is the coupled change the issue does not name, and it is load-bearing.
The transport agent's wait strategy is derived from the 840 s reviewer budget:
two bounded 540 s waits, justified in its own prose as covering "the worker's
840 s budget plus startup with margin", with a failure line naming 1080 s and
840 s. Doubling the reviewer budget without touching the agent converts today's
silent truncation into a **deterministic** `CODEX_REVIEW_FAILURE` at 1080 s —
strictly worse. The Bash tool caps a single call at 600 000 ms, so covering
1 680 s needs *more* wait calls, never longer ones.

**The definition carries five coupled sites, not three.** The Phase-0
investigation named the three that state the reviewer budget. Reading the source
shows two more that state the wait *count* — the opening paragraph's claim about
how many wait calls set an explicit tool timeout, and the wait bullet's own "at
most two". Both move with the ceiling. The per-call wait bound itself is the one
number in the file that does not change. An implementation that fixes only the
three budget mentions leaves the agent making two waits against a four-wait
ceiling and reintroduces the deterministic failure this section exists to
prevent.

**Chosen — the agent names no budget, and waits a uniform four times.** Its rule
becomes: repeat the bounded 540 s wait while the job is still `queued` or
`running`, at most four times. Its failure line reports only what the transport
itself measured — the status and the elapsed bounded-wait total — and drops the
"(worker budget is Ns)" clause entirely. After this change the agent definition
contains **zero** reviewer-budget constants.

**The coupling does not vanish; it moves.** `ceiling > startup + budget` is still
a real relation between two files. What changes is where it is enforced: today it
is enforced by a sentence of prose in the transport that a human must remember to
update, and after this change it is enforced by a test that reads the registry and
the agent definition and fails when the ceiling stops covering the largest budget.
That is the whole point of putting the registry somewhere importable. Claiming the
coupling was "deleted" would be the comfortable version of this sentence and it
would be false.

**The ceiling arithmetic, in the right clock.** The transport wait ceiling is
enqueue-relative; the reviewer budget is connect-relative. Four waits give a
2160 s ceiling against a 1 680 s budget, so the invariant the design must hold is
`ceiling > startup + budget`, leaving 480 s for spawn, runtime seeding and
app-server connect. Measured startup across the survey is seconds — the
enqueue-to-completion and start-to-completion medians agree to the second — so
the margin is ample by two orders of magnitude. Stating the invariant rather than
the leftover number is what lets a future budget change be checked in one step.

- *Considered — operation-aware wait counts* (four for plan-review, two for
  diff-review). Tighter margin, and it preserves diff-review's current worst-case
  latency exactly. Rejected on two grounds. First, it puts a conditional into a
  Sonnet-tier agent whose entire contract is "act only as a transport"; the-bar's
  *Token economy* rule treats each such branch as a failure site, and a
  miscounted wait returns a spurious `CODEX_REVIEW_FAILURE`, which triggers the
  expensive Opus fallback — precisely the outcome this issue exists to stop.
  Second, a per-operation wait count is still a budget-derived constant living in
  the agent — two of them, in fact — so it keeps the coupling in prose instead of
  relocating it into a test.
- **The accepted cost, stated plainly.** `status --wait` re-reads the job record
  and performs no liveness reconciliation, so a worker that dies without
  recording a result leaves the record `running` until some later sweep. Under a
  uniform ceiling that case costs the transport 2160 s before it reports failure,
  up from 1080 s. Seven such deaths appear in the 83-record sample, all of them
  plan-review — an operation whose ceiling had to rise regardless. The trade is
  eighteen extra minutes in an already-broken state, bought against a class of
  spurious failure in the healthy path. Adding liveness reconciliation to
  `status --wait` is the right permanent answer and is explicitly out of scope.

### `~/.agents/bin` on the reviewer's PATH

The acceptance criterion is delivered, but as a **guarantee**, not as a repair:
the probes show the reviewer already resolves `artifact-budget` by bare name and
runs it to exit 0.

Today that works only *by inheritance*. `~/.agents/bin` reaches the reviewer
because home-manager's `home.sessionPath` puts it in the launching login shell's
environment, and the value is then carried down the whole chain — Bash tool →
`codex-companion` → detached worker → `codex app-server` → the exec tool, which
inherits PATH under Codex's default core environment policy. Any launch path
whose parent shell never sourced the profile — a scrubbed environment, a
non-login spawn, a machine without this configuration — silently loses it, and
the failure mode is the exit 127 the issue describes. The-bar's *Defense in
depth* rule is exactly on point: the outer check exists for experience, the inner
one for correctness, and "the other side has it covered" never justifies dropping
either.

**Chosen — prepend `$HOME/.agents/bin` in the repo-owned `codex-companion`
wrapper** (`codexCompanionBin`, a `writeShellScriptBin` in the claude-code home
module). `command -v codex-companion` resolves to that wrapper and to nothing
else — the built plugin tree ships no competing `bin/` directory — so every
invocation passes through it and every descendant inherits the export. Prepending
matches `home.sessionPath`'s own ordering; the seven helper names are unique
enough that shadowing is not a concern.

- *Considered — prepend inside the plugin's runtime env builder*, the single
  choke point through which both the workspace and reviewer runtimes construct
  their child environment. It is the natural-looking seam and the Phase-0 note
  proposed it. Rejected: `$HOME/.agents/bin` is a fact about *this machine's*
  agent toolchain, not about an upstream OpenAI plugin, and hardcoding it there
  violates single responsibility, forces patch churn plus a `patchRevision` bump
  for a change with no observable effect, and puts a config-specific literal into
  a zero-context patch that must survive three-way merges.
- *Considered — do nothing*, since the criterion already holds in practice.
  Rejected: it holds by accident, the issue asks for it explicitly, and the
  one-line wrapper export converts an accident into a construction.

The prepend is unconditional. On a machine whose login shell already exported
the directory the entry appears twice, which is inert; a guard would trade a
visible duplicate for a conditional, and the-bar's YAGNI and maintainability
rules both favour the plain line. Reviewers of the diff should read the duplicate
as deliberate.

Because this defect's fix is entirely repo-owned, it needs no patch edit and no
`patchRevision` bump of its own.

### Sandbox limits are not findings

**Root cause, confirmed:** sandbox `read-only` denies every write, `TMPDIR`
included. That is not a bug — it is what the caller-facing contract promises
("fresh `CODEX_HOME`, approval policy `never`, sandbox `read-only`") and what the
certification evidence model rests on. Test runners, mutation checks and anything
else needing scratch space cannot run, and never could.

Two coordinated edits, both in the repo-owned rubric.

**Stop provoking it.** The diff-review packet supplies "inferred verify
commands", and the plan-review packet supplies manifests and inferred
verification commands too. To a reviewer these read as instructions. They must be
reframed as **context about how the change is verified elsewhere, explicitly not
a request to execute anything.** Note that the plan-review reviewer contract
never asked for independent measurement in the first place: the four package
metrics are supplied precisely *so that* the reviewer need not remeasure, and the
caller has already validated them at its own input gate. A reviewer shelling out
to `artifact-budget` is exceeding its contract, not filling a gap in it.

**Stop reporting it.** One rule joins the shared read-only rules that both
operations already inherit. The rule is about **attribution, not topic**, and the
distinction is load-bearing:

> A limitation of the reviewer's *own execution environment* is never a finding.
> A defect in the *reviewed artifact* stays reportable even when a failed command
> is what exposed it — but it must then be anchored in the artifact with
> evidence, not in the transcript of the denial.

A blunter rule ("never report anything that looks like a sandbox problem") would
suppress a real defect that merely presents as one — a test that cannot run in
*any* environment, a script with a genuinely broken interpreter path. The
attribution form keeps that reportable while removing the noise.

When the sandbox blocks a check, the reviewer records it in the channel the
rubric already owns for exactly this — the explicit statement of what could not
be read or verified, and the per-finding unresolved-unknowns field — and never as
a `Blocking` / `Should fix` / `Critical` / `Important` / `Minor` item. This
extends an existing channel rather than adding a mechanism, which is what
the-bar's DRY rule asks for.

- *Considered — grant the reviewer a writable temp root* (`workspace-write` with
  `writable_roots` narrowed to `TMPDIR`), so the verification the rubric implies
  becomes possible. Rejected on three counts: it contradicts the isolation
  invariant the caller-facing contract and the certification procedure both
  document; the issue's own scope boundary rules out changing the isolation model
  beyond what this defect minimally requires, and instructing costs nothing while
  granting costs an invariant; and it buys verification the reviewer's contract
  never asked it to perform. Network access for `gh` is a strictly larger version
  of the same trade and is rejected for the same reasons. The probe establishes
  only that the `gh` *binary* resolves and runs; whether an authenticated network
  fetch would succeed inside the sandbox was **not** probed, because the decision
  does not turn on it — granting network is refused on the invariant, not on a
  measurement.
- The rule is stated once in the **shared** contract rather than twice in the two
  operation files, because both operation files already declare that they apply
  "alongside" the shared read-only rules. Concretely it belongs in the paragraph
  that already names fresh `CODEX_HOME`, approval `never` and sandbox
  `read-only` — the rule is the behavioural consequence of the sentence right
  above it. That paragraph sits inside a span an existing repo contract test
  slices between two prose anchors; the rule goes *between* the anchors and
  neither anchor moves.

### The caller-facing budget statement

The caller-facing contract currently promises "the runtime's internal ~14 min
budget — expect up to ~15 minutes wall clock", and the skill's eval expectations
restate "bounded around ~15 minutes". Neither was named in the issue or in the
Phase-0 investigation; both are budget-derived constants that go false the moment
plan-review doubles, so both move with it and are in scope.

The contract becomes per-operation: roughly 28 minutes of wall clock for
plan-review, roughly 14 for diff-review. This is a **deliberate second copy** of
the authoritative table. It is kept because callers schedule around the number
and there is no mechanism to derive prose from a patch — and because the rule
against grepping a zero-context patch means no test may read the patch text to
check agreement. The copy is therefore pinned by a repo-side contract test, and
the implementation must confirm agreement by reading the *built store path*.

## Test seams

Three existing seams. No new test file and no new harness; the only new source
file is the registry module D11 requires.

1. **Per-operation budget → the enqueued job record.** The plugin's reviewer
   detachment test already loops over both operations, launches a background
   reviewer and reads the job file. Extend that loop to assert the queued
   record's request timeout is the operation's budget, and that the recorded
   deadline equals the record's creation time plus that budget. This asserts
   *observable behaviour* — what the worker and the reporting surface actually
   consume — rather than the constant against itself. Note the distinction from
   D11: the registry is importable so that the *ceiling invariant* can be
   checked, but the budget's own correctness is still asserted through the job
   record. A test that only compared the registry to itself would stay green even
   if the value never reached a job.
2. **Transport agent contract → the plugin's command/agent-definition test.** It
   already reads the agent definition and pins the envelope, the forwarded
   operation, the bounded-wait invocation, the raw-output extraction and the
   foreground-only rule. Update it for the new ceiling and add the anti-drift
   assertion that makes the budget decision enforceable.

   That negative assertion must be **precise about its subject**, or it fails for
   two reasons instead of one. The definition legitimately keeps numbers: the
   per-call wait bound, the Bash tool's own cap, and the ceiling the transport
   itself measures. What is prohibited is the definition claiming a *worker-side*
   budget — the phrase naming the worker's budget, and the retired constant. The
   positive assertions continue to pin the transport's own numbers, so the two
   halves of the test do not overlap.

   The same test also carries **the invariant test**, which is the one that makes
   this design self-defending: import the registry, read the wait count and the
   per-call bound out of the definition, and assert their product exceeds the
   largest registered budget. It fails for exactly one reason — the transport's
   ceiling no longer covers the slowest operation — and it is the reason the
   registry had to become importable at all.

3. **Rubric contracts → the repo's workflow-skill-contracts suite** (run by
   `just agent-workflow-tests`). It already loads all four collaboration rubric
   files. Add assertions for the two per-operation wall-clock statements, for the
   sandbox-limits-are-not-findings rule in the shared read-only rules, and for
   the verify-commands reframing in both packets. The existing dispatch-envelope
   test slices the shared contract between two prose anchors; those anchors must
   survive the edit.

**Verification beyond unit tests** (the-bar: *Verify before claiming done* —
state what you ran and what it printed):

- The plugin suite, invoked exactly as documented, with the live Claude session
  variables unset.
- `just build` for the Nix side; there is no unit-test suite for the Nix configs.
- The collaboration skill's eval expectations are prose fixtures run by hand
  against a model, not a gated suite. The wall-clock restatement in them is
  updated as text; nothing local verifies it, and the plan should not pretend
  otherwise.
- A live reviewer probe re-run after the wrapper change, confirming bare-name
  resolution of `artifact-budget` with the transcript retained as evidence.
- Confirmation of the registry's two values and the transport's ceiling by
  reading the **built store path** or the scratch clone. Never by grepping the
  patch: a zero-context patch carries no per-line file attribution, so a
  patch-wide match counts hunk lines from every touched file at once and cannot
  say which file a hit sits in.

**Patch workflow.** Five files move inside the patch: the new registry module,
the CLI entrypoint that now reads it, the transport agent definition, and the two
plugin test files. They follow the documented route — scratch clone of the pinned
rev, `git apply --unidiff-zero`, edit the source tree, regenerate with
`git diff -U0 <pin>`, and bump `patchRevision` from 10 to 11, subject to D10's
collision check. Everything else this design touches is repo-owned and needs no
patch edit: the wrapper, the rubric, the eval expectations and the repo-side
contract test.

## Out of scope

- **The app-server's ~50 KB exec-output shard truncation.** The issue defers it
  explicitly; one reviewer escalated it into a spurious must-fix Critical.
  Mitigated caller-side with smaller shards. Untouched here.
- **Liveness reconciliation in `status --wait`.** Named above as the permanent
  answer to the wedged-worker latency this design accepts. It is a change to
  job-state semantics for every caller, not just the reviewer, and belongs to its
  own issue.
- **Any widening of the isolation model** — network access, writable roots, a
  shared broker for reviewers, or a non-fresh `CODEX_HOME`.
- **`flake.lock` or pinned-rev advancement.** The patch is regenerated against
  the same pinned rev.
- **Re-tuning `diff-review`'s budget.** Left at 840 000 ms on a six-job sample;
  revisit on evidence.
- **The 7 worker-death records.** A distinct failure mode with its own existing
  post-mortem machinery.
- **The post-ship survey itself.** Named above as the issue's follow-up evidence;
  it cannot run until plan-reviews have accumulated on the new build, so it is
  not part of this branch's verification.

## Durable decisions

This repository keeps no `docs/` tree and no ADR directory, so the architectural
decisions live here as numbered ledger rows rather than as separate records. Three
of them meet the bar an ADR would: hard to reverse, surprising without the
context above, and the result of a genuine trade-off. **D3** (the transport stops
owning a budget) reshapes the contract between the bridge and its transport.
**D5** (the PATH guarantee lives in the repo-owned wrapper, not the patch) fixes
where machine-specific facts may enter an upstream plugin. **D6** (sandbox limits
are reported by attribution, never as findings) is a standing rule for every
future reviewer pass. **D11** is the structural companion to D3 — it is what
converts "the transport must cover the budget" from a remembered convention into
a failing test. A later change that reverses one of these should say so by
naming the row, per the ledger's own convention.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | Reviewer budget becomes a per-operation table — plan-review 1 680 000 ms, diff-review unchanged at 840 000 ms — and the closed set of valid operations derives from that table's keys. | Issue AC1; 83-record survey: 10 plan-review kills vs 1 diff-review kill, plan-review p90 730 s against an 840 s wall (censoring signature). the-bar DRY (one authoritative home) and Fail loud (a closed-set dispatch cannot have a missing arm). | Raise both operations to one larger constant — preserves the one-size defect the issue exists to remove and slows the fast operation's failure detection for no measured reason. |
| D2 | Diff-review's budget is left untouched despite its observed median (520 s, n=5) exceeding plan-review's (475 s, n=60) and one observed kill. | Six jobs cannot size a wall; the smaller and more reversible call is to move only the operation the evidence indicts. Contradiction recorded in Evidence so a later pass revisits it on data, not on the issue's prose. | Raise diff-review too on the strength of the same sample — would set a wall from six observations and double the change's behavioural surface. |
| D3 | The transport agent stops naming any budget: it waits a uniform four bounded 540 s waits for both operations, and its failure line reports only the status and the elapsed bounded-wait total. | The Bash tool caps one call at 600 000 ms, so 1 680 s needs more calls, not longer ones; the-bar Token economy (a branch in a Sonnet transport is a failure site whose miscount triggers the expensive Opus fallback), DRY, and Truthful terminal states. Deletes the coupling class instead of re-tuning it. | Operation-aware wait counts (4 / 2) — tighter margin and preserves diff-review's worst-case latency, but puts a conditional in a pure transport and keeps a budget-derived constant living in the agent definition. |
| D4 | Accept that a worker which dies without recording a result now costs the transport 2160 s instead of 1080 s, because `status --wait` performs no liveness reconciliation. | Measured: 7 such deaths in 83 records, all plan-review — an operation whose ceiling had to rise anyway. Eighteen extra minutes in an already-broken state is the cheaper side of the trade against spurious healthy-path failures. | Clamp `status --wait` to the job's recorded deadline — would abandon a healthy job that started late, since the deadline is measured from enqueue and deliberately precedes the worker's own budget window. |
| D5 | Defect 2 is delivered as a guarantee, not a repair: `$HOME/.agents/bin` is prepended in the repo-owned `codex-companion` wrapper, and the spec records that the issue's stated mechanism does not reproduce. | Live probe: PATH already contains it, `command -v artifact-budget` resolves, and `artifact-budget check` exits 0 inside the reviewer sandbox. Today it holds only by login-shell inheritance; the-bar Defense in depth converts inheritance into construction. `command -v codex-companion` resolves to that wrapper alone. | Prepend inside the plugin's shared runtime env builder — hardcodes a machine-specific path into an upstream patch, violating single responsibility and forcing patch churn plus a `patchRevision` bump for no observable effect. |
| D6 | Defect 3 is resolved by instruct-and-scope in the repo-owned rubric: a sandbox restriction is never a finding, reported instead through the existing could-not-verify channel, stated once in the shared read-only rules. | Probe confirms read-only denies every write including `TMPDIR` (`mktemp -d` → Operation not permitted), which is exactly what the caller-facing contract promises and the certification model rests on. The rubric already owns a channel for unverifiable input, so this extends a mechanism rather than adding one (the-bar DRY). | Grant a narrowed writable temp root (or network for `gh`) — contradicts a documented invariant, exceeds the issue's own scope boundary, and buys verification the reviewer's contract never asked it to perform. |
| D7 | The packets' inferred verify commands are reframed as context describing how the change is verified elsewhere, explicitly not a request to execute anything. | The diff-review packet hands verify commands to a read-only reviewer, and the confirmed test-runner denials are the direct consequence; the plan-review contract never asked for independent measurement — the supplied metrics exist so it need not remeasure. | Rely on the prohibition alone — leaves the provocation in place and asks the model to disregard an instruction it was handed. |
| D8 | The coupled repo-owned consumers the issue never named — the caller-facing wall-clock promise and the skill's eval expectation — are in scope and become per-operation (~28 min / ~14 min); the restatement is a deliberate second copy pinned by a repo contract test. | The issue's own scope boundary covers "every budget-derived constant that must move with them"; leaving them at ~15 minutes ships a knowingly false contract. Callers schedule on the number, prose cannot be derived from a patch, and no test may grep the patch to check agreement. | Delete the number from the caller-facing contract and point at the bridge — callers lose the planning figure the contract exists to provide. |
| D9 | The per-operation budget is asserted through the enqueued job record inside the existing both-operations reviewer loop, and the transport agent is pinned by a negative assertion that its definition carries no numeric worker-budget claim. | the-bar Tests that can fail: assert observable behaviour, and each test fails for exactly one reason. Both are existing, highest-available seams; no new test file. | Export the budget table and assert it directly — asserts the constant against itself and stays green even if the value never reaches a job. |
| D10 | The plan must re-check `patchRevision` against the integration branch before merging, and reconcile any collision by three-way merging the plugin *source trees* in scratch clones — never the patch text. | CLAUDE.md: a textually-merged zero-context patch applies at lenient offsets with no error, so a wrong merge is silent, and an identical revision bump on both sides hides the collision from git's conflict list entirely. Parallel issue work on this repo makes a concurrent patch edit a live possibility, not a hypothetical. | Bump 10→11 and rely on git to surface a conflict — the one failure mode the documented workflow says git cannot surface. |
| D11 | The operation registry lives in its own importable runtime module rather than inline in the CLI entrypoint, so a test can assert that the transport's wait ceiling still covers the largest reviewer budget. | The entrypoint runs its `main` at module scope and exports nothing, so no test can read a constant from it; an unassertable budget constant is the exact defect this issue repairs, and it would recur on the next re-size. the-bar: split when the second concern arrives — the tests needing the value is that second concern. | Keep the registry inline and assert the ceiling and the budget as two independent literals — nothing then fails when a future re-size breaks the relation, which is how this defect was written the first time. |
| D12 | The patch moves **six** files, not five: `tests/worker-postmortem.test.mjs` is the sixth. Test seam 1 splits across the two files that already own each half — `tests/reviewer-detach.test.mjs` pins the enqueued `request.timeoutMs` per operation, and worker-postmortem's existing both-operations deadline test is parameterised by the registry instead of a flat `840000`. | Reading the patched source found a coupled site the Phase-2/3 pass missed: worker-postmortem already asserts `Date.parse(deadlineAt) - Date.parse(createdAt) === 840000` for both operations and turns red the instant plan-review doubles. Its assertion *is* the deadline half of seam 1, so restating it in reviewer-detach would duplicate a live assertion (the-bar DRY). | Add both assertions to reviewer-detach and leave worker-postmortem's literal alone — the suite then fails on the change the plan intends, and two files assert the same delta. |
| D13 | The transport's wait count lives in the agent definition as one parseable phrase, `Wait with at most four foreground calls`, and the invariant test resolves that word through a closed word→number table that fails loudly on any word it does not know. | D11's ceiling test must multiply the definition's wait count by its per-call bound, and the count exists only as agent-facing prose, so the test has to parse it. A closed table keeps "the ceiling stopped covering the budget" and "the prose stopped being machine-readable" as two distinct loud failures instead of one silent pass. | Write the count as a digit so a bare `\d+` match suffices — reads as machine output inside a Sonnet-facing instruction whose every other quantity is spelled, and buys nothing the table does not already give. |
| D14 | The sandbox-limits-are-not-findings rule is added as a fourth bullet under SKILL.md's `## Read-only rules (both operations)` — the block that is "included verbatim in substance in every packet" — not inside the Launch paragraph that names fresh `CODEX_HOME` / `never` / `read-only`. | Refines D6's placement prose without reversing D6, which already says "stated once in the shared read-only rules". The Launch paragraph is caller-facing narration that never travels to the reviewer, so a rule placed there would instruct nobody and leave issue AC3 undelivered; the rules bullets are the only shared text a packet carries. It also leaves the contract test's two prose anchors untouched rather than editing between them. | Put the rule in the Launch paragraph as the Decisions prose suggested — the reviewer never receives that paragraph, so the instruction would not reach the model it is written for. |
| D15 | Both wall-clock restatements are pinned by the repo contract suite: SKILL.md's per-operation sentence and `evals/evals.json` (the eval-1 expectation and the file's `notes` figure), asserted in `test_workflow_skill_contracts.py`. | D8 keeps the caller-facing number as a deliberate second copy "pinned by a repo-side contract test", and `test_ship_issue_eval_restates_the_gate_boundary_it_grades` is the existing precedent for pinning an eval's restatement of a number its skill owns. Pinning the text is not grading the eval's outcome, which stays manual exactly as the spec says. | Pin only SKILL.md and leave the eval prose unpinned — the eval then keeps grading a model against a wall-clock figure the skill no longer states. |
| D16 | The `patchRevision` collision re-check runs twice: Task 1 Step 1 before implementation, and again as a plan-root pre-merge gate after the last integration-branch sync. | D10 places the authoritative check before merging, and CLAUDE.md states that neither a lenient zero-context `patch -p1` nor git's conflict list can surface a concurrent patch edit; the pre-implementation check alone cannot see one that lands later. Codex plan-review B-104-01. | Rely on the Step 1 check plus the shipping flow's generic integration merge — exactly the silent-failure path CLAUDE.md warns about. |
| D17 | One built-artifact gate asserts the two budget values as literals (`plan-review=1680000`, `diff-review=840000`) and one built-wrapper gate asserts the PATH export precedes the `exec` by line number; the registry-derived tests are kept alongside them. | the-bar Tests that can fail: D9's assertions compare the enqueued record against the same registry they are meant to pin, so a typo propagated through both stays green, and two independent `grep -q`s accept an export placed after the `exec` that no child could inherit. Codex plan-review S-104-01, S-104-02. | Keep only the registry-derived assertions — they pin the wiring but not the values, leaving the exact defect this issue repairs re-introducible in one keystroke. |
| D18 | The registry's dictated source comment justifies plan-review's larger wall by asymmetric truncation (ten kills to one, p90 730 s against an 840 s wall) rather than by calling plan-review the slower operation. | Plan-prose ≠ code-prose: dictated prose must describe how the code actually behaves and why, and this spec's own Evidence section disproves the relative-speed premise (observed diff-review median 520 s exceeds plan-review's 475 s). Codex plan-review B-104-02. | Keep the "slower operation" phrasing inherited from the issue — ships a comment the approved spec contradicts two sections earlier. |
| D19 | The plan's dictated negative regex for the transport's "no worker-side budget claim" guard is overridden: the guard whitespace-collapses the definition before matching, rather than keeping the line-scoped `[^.\n]*` form the plan wrote. | the-bar Tests that can fail: the dictated regex cannot cross a line wrap, and the claim it retires is wrapped prose, so it could never have gone red — a guard green by construction pins nothing. D9 makes this negative assertion the only seam holding the transport free of budget-derived constants, so its failing is load-bearing. Where a reviewer's finding and the plan's own text disagree on a verification seam, the finding governs; fixed in `9574503`. | Honour the plan's dictated regex byte-for-byte — preserves plan conformance and ships a guard that passes on prose it was written to reject. |
| D20 | SKILL.md's caller-facing wait sentence states the bridge's uniform wait as a bounded-wait figure — `CODEX_REVIEW_FAILURE` only after roughly 2160 s of bounded waiting, four bounded 540 s calls — and tells callers to schedule against the per-operation budget while planning for that figure, rather than calling it the worst case they can be held for. It is pinned in `test_workflow_skill_contracts.py` by the arithmetic (total = four times the per-call bound) plus a negative on the retired overstatement. | Each of the four 540 s waits is issued through a Bash tool with its own 600 000 ms outer cap, so 2160 s bounds the bridge's waiting, not the hold — the-bar Truthful terminal states. D8 keeps the wider wait visible to callers (deleting the sentence would leave the 28/14-minute budgets as the only figures a caller sees), and D15 makes every caller-facing wall-clock restatement a pinned second copy; this one shipped unpinned and unlogged. | Revert the sentence to the plan-mandated byte-identical form — restores plan conformance and re-hides the wider wait behind a figure the caller cannot rely on. |
