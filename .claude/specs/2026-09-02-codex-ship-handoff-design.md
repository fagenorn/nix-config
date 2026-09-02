# Codex ship handoff — scope the no-re-prompt contract, add one explicit operator gate

Issue: https://github.com/fagenorn/nix-config/issues/119

## Problem

`ship-issue`'s `## Standing authorization` makes two claims. The first is already scoped to
the enforcement that grants it. The second is not: it asserts that in a qualifying repository
the shipping chain — `git push`, `gh pr create`, `gh pr merge …`, branch delete, worktree
remove — *needs no re-prompt*, full stop.

That claim is true on exactly one host. The Claude host runs a deterministic `PreToolUse`
permission guard that validates those exact spellings against the live repository and allows
them. The Codex host has no such layer: its built-in risk reviewer adjudicates *intent*, and
the only inputs it honours are literal human messages and repository guidance. It does not
honour skill prose — so no sentence in `ship-issue` can make it allow anything.

The result is a contract that lies to one of its two hosts. Measured over two weeks: 129
denials of these verbs on the Codex host, up to 57 in a single day. Every affected ship
completed only because a human pushed or merged by hand. In between, sessions did the three
things a false contract produces — retried the denied command, fell back to read-only checks,
and stalled — because the skill told them the command needed no re-prompt and the host told
them otherwise.

The skill cannot make the reviewer say yes. It *can* stop a session from ever putting an
unbacked command in front of it, and route the session through the one input the reviewer does
honour: a human's own message.

## Solution

Two changes, both inside the machine-global skills tree, neither touching the Claude guard.

**1. Scope the claim to the host enforcement model.** `## Standing authorization` keeps its
shared first sentence unchanged and splits the second into two host rows: one for a host that
adjudicates each command deterministically against validated spellings (the claim, unchanged,
including the pinned merge spelling), and one for a host that adjudicates intent by review
(the claim is false; take the gate instead). A session applies the row for its own host — it
knows its own harness without detection, and no environment sniffing is introduced.

**2. Add a consolidated operator gate on the review-adjudicated path.** A new ship-issue
sidecar, `HUMAN-GATE.md`, owns it. On that path a session **never attempts a shipping verb and
then reacts to the denial**. It enters the gate *instead of* the attempt, presents every
literal command that is knowable at that moment in one block, and either waits (interactive)
or suspends `blocked_on: human_gate` with the canonical re-entry line (`--auto`, per
`from-issue/AUTO.md`). The human's grant arrives as their own message — the input the reviewer
honours — after which the same session resumes in place and runs the chain to issue closure.

There are two *planned* gate locations on the successful path — one before the first
push, one before the merge — and that count is forced rather than chosen. A failed
command re-enters its own gate for a fresh single-use grant, so the gate can be entered
more often than twice; it is never entered fewer. See D2 and D16.

## Decisions

### The claim, per host enforcement model

`ship-issue`'s `## Standing authorization` reads, after the unchanged shared sentence:

> In a qualifying repository, on a host whose permission layer adjudicates each command
> deterministically against validated spellings — the Claude host's `PreToolUse` guard — this
> skill IS that chain: `git push`, `gh pr create`, `gh pr merge <pr-num> --repo <repoSlug>
> --merge [--subject "<rendered mergeSubjectTemplate>"] --delete-branch`, branch delete, and
> worktree remove need no re-prompt; pause only where a phase says to.
>
> On a host whose permission layer adjudicates intent by review rather than by validating
> spellings — the Codex host, whose risk reviewer honours literal human messages and
> repository guidance but not this skill's prose — no wording here makes that chain
> executable: it is denied by default. Take the consolidated operator gate of
> [`HUMAN-GATE.md`](./HUMAN-GATE.md) instead, and never route around a denial.

The merge spelling inside the first row is byte-identical to today's, and the second row names
no `gh pr merge` (D6). The predicate is the enforcement model, never a host name test.

### The two gates

**Gate 1 — before the first push (ship Phase 4).** Presents, as literal text a human can read
and repeat: the exact `git push -u origin <branch>`, and the exact `gh pr create` invocation
including the rendered body. Both are fully determined at that moment. The block also *names*
that a second and final gate follows after CI, and what it will cover — so the operator sees
the whole remaining chain once, which is the consolidation the issue asks for.

**Gate 2 — after CI, before the merge (ship Phase 7).** Presents the merge command exactly as
Phase 7 renders it, plus the remaining Phase-8 chain: `gh issue close <num>`, the remote-branch
delete when the remote still carries the branch, `git worktree remove`, `git branch -d`. After
this grant nothing further is asked; the session resumes to issue closure and cleanup.

**Grant semantics, on both gates.**

- A grant covers exactly the literal command strings presented, each consumed by exactly one
  execution. A command that renders differently in any byte from the granted literal is not
  covered and needs a fresh gate.
- Silence is not a grant. No reply → keep waiting (interactive) or stay suspended (`--auto`).
  A partial reply grants only the commands it names.
- A failed execution is not re-run under the same grant. Re-entering the gate is the only path.
- The grant is *additional to* every check the Claude path performs, never a substitute:
  `check-launch` still runs before every pre-merge forge write, Phase 6's tip check and CI wait
  still bind, and the merge still requires the base branch's required status check. Nothing here
  weakens `.out-of-scope/ungated-agent-merges.md`.

### The no-bypass ban on this path

`HUMAN-GATE.md` states it as an explicit closed list, because a denial creates exactly the
pressure to be creative. On this path the session must not: merge the feature branch into
`<integrationBranch>` locally; push to `<integrationBranch>`; push to any remote other than
`origin`; pass `--admin`, `--force`, `--force-with-lease`, or any hook-bypass flag; rewrite,
reset or rebase any branch to change what a denied command would have done; re-attempt a denied
command in a re-worded or re-quoted spelling; or ask a subagent, another skill, or another host
to run the command on its behalf. This restates, for this path, the ban Phase 1 already places
on rewriting the integration branch.

### Composition with `--auto`

`from-issue/AUTO.md`'s final paragraph already routes an unguarded Phase-6/Phase-7 push, PR-open
or merge gate to `SKILL.md`'s suspension procedure. Its enumeration of *which* gates qualify
gains one case — a host that has no such guard at all — so the review-adjudicated path is
covered by the mechanism that already exists rather than a second one. `HUMAN-GATE.md` presents
the block, then defers to that procedure; it defines no new suspension shape and no new
`blocked_on` value.

### The #64 accommodation record

A new `## Host adapter accommodations` section in `home/common/agent-skills/README.md`, beside
`## Vendored skills` — the same shape of durable, cross-cutting fact about the skills tree
itself. It records: the divergence, the evidence (129 denials in two weeks, peak 57 in one day,
every affected ship completed only by hand), and why it is adapter-tier and not a native
extension under #64 — the semantics are unchanged and host-neutral ("shipping needs
authorization for irreversible egress"), only the translation differs; Claude translates it to
a validated permission-guard spelling, Codex to an operator turn. No new capability, no
Codex-only verb, no behaviour a Claude session cannot also express. #64's irreducibility
evidence is therefore not required, and the section says so.

This record is written by the design phase, not by the implementation: it is a decision
record, and the plan verifies it rather than reproducing it. It is deliberately not pinned by
a test — a prose record whose wording is frozen stops being maintainable, and the behaviour it
describes is already pinned in the two skill files.

## Test seams

The existing contract-prose seam: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`.
No new seam is introduced. Sidecar prior art is the module-level `SHIP_ISSUE_REVIEW` constant;
`HUMAN-GATE.md` gets the same treatment.

| Assertion | Change | Guards |
|---|---|---|
| `test_authorization_truth_is_single_and_shared` | unchanged — the shared first sentence is untouched and must stay verbatim in both files | that the amendment did not disturb the shared truth |
| `test_ship_issue_merge_is_bound_to_the_resolved_repository` | exactly one entry of the ordered `expected_occurrences` list changes: the standing-authorization line gains its host-model prefix. Its count stays at three | AC1 and AC5; the exact-list shape is why D6 forbids a second merge-naming line in `SKILL.md` |
| new — the claim is host-scoped | both rows present in `## Standing authorization`, each naming its enforcement model; the bare unconditional opener absent | AC1 |
| new — the gate consolidates and forbids bypass | `HUMAN-GATE.md` carries both gates in order, the grant semantics including that silence is not a grant, resumption to issue closure, and every member of the no-bypass list | AC2, AC3 |
| existing `--auto` suspension assertions | extended for the added case in `AUTO.md`'s enumeration | that the gate reuses the one suspension mechanism |

Each new assertion fails for one reason: a missing or reworded contract sentence in one named
file. None asserts on a call count or a mock.

`just build` validates that the skills tree still evaluates; the Python suite is
`python3 -m pytest home/common/agent-skills/tests/test_workflow_skill_contracts.py`.

## Out of scope

- **The Claude permission guard.** `home/common/claude-code/default.nix` and
  `tests/test_claude_permission_guard.py` are untouched. The first host row restates today's
  behaviour and asserts nothing new about it.
- **`ship-release`.** It carries its own independent "Don't re-prompt at each step" claim with
  the same defect. Deliberately left; a follow-up issue should scope that claim the same way,
  and `tests/test_ship_release_contracts.py` is its seam.
- **Repository guidance.** Root `AGENTS.md` is generated from `.agents/instructions/bootstrap.md`
  by `resolve-project write-projections`; per D3 nothing here edits it, and no per-repo
  onboarding step is added.
- **Any auto-grant.** No inference of a grant from a prior turn, a label, a config key, an
  environment variable, or a previous run. No retry loop that converges on approval.
- **A native Codex extension.** No new skill, verb, capability or artifact that only one host has.
- **Host detection machinery.** No environment-variable sniffing, no probe command, no capability
  handshake.

## Decision ledger

| ID | Choice | Grounding | Rejected alternative |
|----|--------|-----------|----------------------|
| D1 | The #64 accommodation is recorded as a `## Host adapter accommodations` section in `home/common/agent-skills/README.md` | That README is the declared adapter-contract doc and already carries `## Vendored skills`, a durable cross-cutting fact of the same shape; the record is about the skills tree, not about any one project | A `docs/areas/system/adr/` record — the ADR gate's three tests pass, but the repo has no `docs/` tree, and standing one up (map, area, linter layout rules) to hold a single record is scope the issue does not ask for. `.out-of-scope/` is wrong by definition: nothing was rejected |
| D2 | Two gates, not one: the chain is *presented* once at Gate 1, but the merge carries its own fresh confirmation at Gate 2. This is forced, not preferred — at Phase 4 the PR does not yet exist, so `<pr-num>` is unknown and the literal merge command cannot be presented, let alone granted | #84: an irreversible action needs a fresh, single-use confirmation, never inherited. A Phase-4 grant for a command whose text is not yet knowable is exactly an inherited confirmation. #90 is satisfied because each gate collects *every* confirmable irreversible action available at that moment in one turn — which is the fix for 129 per-verb denials | One grant at Phase 4 covering all three verbs, as the issue's literal wording suggests: it cannot name the merge command, so it grants an unknown string and inherits a confirmation past CI. Also rejected: three separate per-verb gates, which is the status quo the issue exists to remove |
| D3 | The path is selected by the host's *enforcement model* stated as two prose rows, not by detecting the host | #64 keeps semantics host-neutral and lets only the translation differ; the shared first sentence already keys off the enforcement that grants authorization. A session knows its own harness without a probe, and the Codex reviewer trusts repository guidance, not skill prose — so a detection instruction in skill prose would buy nothing the row already gives | An explicit detection instruction (env vars, a probe): unreliable markers, YAGNI, and it would make the contract's truth depend on a runtime check rather than on a stated model. Also rejected: a paragraph in root `AGENTS.md`, which is generated and would push project-specific residue into a project-agnostic tree |
| D4 | The gate lives in a new ship-issue sidecar `HUMAN-GATE.md`, not inline in `SKILL.md` | Sidecar precedent is established (`SYNC.md`, `REVIEW.md`, `CONSOLIDATE.md`, `CI-MERGE.md`); the bar's token economy — a Claude session should not load a path it never walks. `SKILL.md` keeps only the contract sentence and two one-line pointers | Inline in `SKILL.md`: ~70 lines every session pays for and one host uses. Also rejected: naming it `HANDOFF.md`, which collides with two live meanings — the validated ship-handoff packet and the `handoff` rollover skill (D5) |
| D5 | The canonical term is **operator gate** / **human gate**, not "handoff" | `blocked_on=human_gate` is already the vocabulary for exactly this pause, and reusing it means the gate defers to the existing suspension procedure rather than defining a second one. "Handoff" is taken twice over in this repo | Keeping the issue title's "handoff": ambiguous against the validated ship-handoff boundary that `artifact-budget validate-report --boundary ship-handoff` names |
| D6 | `HUMAN-GATE.md` refers to the merge as "the merge command exactly as Phase 7 renders it" and never re-spells it; no new line in `SKILL.md` names `gh pr merge` | The bar's DRY — one authoritative home for the spelling, which is Phase 7. Mechanically it also keeps `test_ship_issue_merge_is_bound_to_the_resolved_repository`'s exact ordered list at three entries with one changed, so the test still fails for one reason | Re-spelling the merge in the sidecar: a second home that drifts silently, since the pinned test only scans `SKILL.md` |
| D7 | The gate is entered *instead of* attempting the verb — never after a denial | The bar's root-causes clause: reacting to a denial is symptom-shaped, and it is the retry-then-stall behaviour the 129 denials produced. Entering first means the reviewer is never asked to adjudicate an unbacked command | A denial-triggered fallback: cheaper to write, but every ship pays a denial first and the failure mode stays a stall |
| D8 | The grant is additional to `check-launch`, the Phase-6 tip check, the CI wait, and the base branch's required status check — never a substitute for any of them | The bar's defense-in-depth; `.out-of-scope/ungated-agent-merges.md` puts merge safety on the required status check rather than on any authorization layer | Treating a human grant as the merge gate: recreates precisely the ungated-agent-merge shape that KB entry rejects |
| D9 | `ship-release` is left unamended and recorded as a follow-up | Scope discipline; its claim sits in a different skill with a different test file and a different flow (default-branch release, not feature ship), so amending it here would widen the blast radius past the issue's acceptance criteria | Fixing both claims in one change: tempting for consistency, but it doubles the reviewed surface and couples two independent contracts |
| D10 | The two new `SKILL.md` phase pointers name only "Gate 1"/"Gate 2" and the sidecar link, never a merge spelling, so the file's `gh pr merge` line count stays at exactly three; that count is the implementation task's own shell gate | D6 gives Phase 7 the single authoritative home for the spelling, and `test_ship_issue_merge_is_bound_to_the_resolved_repository` compares an exact *ordered list of every line* containing `gh pr merge` — a fourth line fails the suite for a reason unrelated to what the pointer is for | Re-spelling the merge in the Phase 7 pointer for local readability: it adds a fourth entry to a list whose entire value is being exact, and readers already have the rendered command three lines below |
| D11 | `AUTO.md`'s widened gate enumeration gets a *new* pinned assertion rather than an extension of an existing one — no test pins that paragraph at base | A grep of `test_workflow_skill_contracts.py` finds no assertion over `AUTO.md`'s final paragraph; unpinned contract prose is exactly the condition that let the unconditional no-re-prompt claim drift in the first place | Leaving the paragraph unpinned and resting on the two skill-file tests: the `--auto` route is the half of AC2 that resumes after the grant, and it would be the change's only unguarded surface |
| D12 | On the review-adjudicated path the Phase-7 order is Gate 2 → `check-launch` → merge: the gate pointer is inserted *before* the existing launch-guard paragraph, which stays byte-unchanged, and `check-launch` is re-validated after the grant arrives | Gate 2 waits for a human grant and in `--auto` suspends outright. Placing the pointer after `check-launch` would open an unbounded window between the check and the write, destroying `ship-issue/SKILL.md`'s `## Phase 7 — Merge` guarantee that `check-launch` runs "immediately before the merge" — the guarantee the launch guard exists to give | Pointer after the launch-guard paragraph (the reading order a reader might expect): it reads naturally and is wrong, because the suspension between them is exactly the staleness `check-launch` is there to catch. Also rejected: adding a *second* `check-launch` instruction inside the pointer, which duplicates a contract sentence that already says it |
| D13 | `AUTO.md` gets a second amendment: the general self-answer sentence gains an explicit exemption for gates that ask a human to authorize an irreversible action, which are never self-answered and instead suspend per the existing procedure | The unqualified sentence ("when one tells you to ask or wait, run the self-answer pattern instead") would direct `--auto` to self-answer the very gate D2 introduces. #84 requires a fresh, single-use confirmation that is never inherited and never silently retried; #90 requires one operator touchpoint where silence never means yes. Both are violated by a self-answered authorization | Leaving the sentence alone and relying on `HUMAN-GATE.md` to say the opposite: the two files would then contradict each other around an irreversible action, and `AUTO.md` is the file the autonomous owner reads. Also rejected: deleting the self-answer rule, which is correct for every other gate |
| D14 | AC3 is verified by a section-scoped Python assertion in the contract suite, not by a line-local `grep … | grep -v 'must not'` pipeline | The pipeline treats any matching line without the literal "must not" as an affirmative bypass, but the prescribed text puts "must not:" on the list's introduction line and each banned verb on its own bullet — so it rejects the exact implementation it is meant to accept. The Python seam already reads whole files and has `section`/`assert_ordered` helpers, so it can split the file at `## Never route around a denial` and require every bypass spelling to occur only inside that closed list | Repairing the pipeline with a `grep -A`/`awk` range over the bullet list: shell range-matching over prose is the same class of fragility one layer deeper, and the assertion belongs beside the other contract-prose assertions |
| D15 | The tests pin the *payloads*, not just the prose: each gate's literal command block in order (`git push -u origin <branch>`, the `gh pr create` invocation with its rendered body and `Closes #<num>`; then `gh issue close <num>`, the `git ls-remote --heads origin <branch>`-gated remote delete, `git worktree remove <worktree-path>`, `git branch -d <branch>`), and the complete normalized shape of `## Standing authorization` | The presented commands *are* the consolidation AC2 asks for — a suite that pins only headings and grant semantics would pass with every command omitted. Symmetrically, a lone `assertNotIn("CLAUDECODE", …)` guards one spelling of one probe, while D3 forbids host detection of any shape; pinning the whole section makes "no additional detection instruction" provable rather than spot-checked. Spellings are copied from the live `ship-issue/SKILL.md` Phases 4, 7 and 8 | Trusting the implementer to carry the payloads over from `SKILL.md`: it is exactly the drift the unpinned no-re-prompt claim already demonstrated (D11's grounding). Also rejected: adding more `assertNotIn` probe spellings, which is an open-ended blocklist against an open-ended attack surface |
| D16 | The gate is described as having two *planned locations on the successful path*, not as being "entered exactly twice"; a failed command re-enters its own gate for a fresh single-use grant | The literal count contradicts the grant semantics in the same document ("A failed execution is not re-run under the same grant; re-entering the gate is the only path"), and a contract that states an impossible invariant teaches a reader to discount it. Clarifies rather than reverses D2 — the *locations* are still two, and still forced by the unknown `<pr-num>` at Phase 4 | Keeping "exactly twice" and reading it as informal: prose a test pins cannot be informal. Also rejected: dropping the count entirely, which loses D2's point that the number is forced rather than chosen |
