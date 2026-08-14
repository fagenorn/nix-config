# Cost-aware issue-workflow model matrix design

## Problem

The issue-delivery workflow currently names useful roles such as owner, implementer,
mechanic, and reviewer, but several custom agents and `Agent` dispatch sites do not
select a model explicitly. Those sites inherit the caller's model. The same role can
therefore run at a different capability and cost depending on who launched the flow,
and a bounded re-review pays for the same full reviewer used for first-pass and
whole-branch judgment.

Issue [15](https://github.com/fagenorn/nix-config/issues/15) requires an explicit,
auditable matrix: high-judgment ownership, design, planning, non-mechanical
implementation, shipping, and full review remain on Opus; bounded transport and
mechanical work use Sonnet; bounded exploration may use Haiku; and a new Sonnet
reviewer-lite role handles only named-finding, bounded-diff re-reviews. A repository
check must reject any closed-set pipeline dispatch that can inherit a model or effort.

## Solution

Add one declarative role ledger for the issue workflow and make every custom agent and
closed-set dispatch site select one of its named entries. The ledger records role,
model, effort, eligible use, and prohibited use. Human-readable skill instructions
repeat the exact selection beside each dispatch so a trace exposes the decision rather
than relying on ambient defaults.

The initial matrix is:

| Role | Model | Effort | Eligible work |
| --- | --- | --- | --- |
| issue owner | Opus | high | from-issue ownership, design, planning, standards disposition, delivery judgment |
| ship owner | Opus | high | ship-issue phases and merge decisions |
| implementer | Opus | high | non-mechanical task implementation |
| reviewer | Opus | high | first-pass task, plan, conformance, correctness, PR, and whole-branch reviews |
| reviewer-lite | Sonnet | medium | one scoped re-review with named findings and a bounded fix diff |
| mechanic | Sonnet | medium | transcription, inventories, bulk edits, transport, bookkeeping |
| explorer | Haiku | medium | bounded, read-only inventory or repository fact lookup |

The Codex bridge remains a Sonnet transport role even when the detached reviewer it
starts is a stronger independent system. Any move from explorer or mechanic to Opus is
an explicit escalation recorded in the task ledger or returned report. Unknown role or
dispatch-kind values fail loudly; there is no default branch that inherits a caller.

A static contract test inventories the finite dispatch sites in the workflow skills,
custom agent frontmatter, prompt templates, and orchestration definitions. It fails
when a custom agent lacks either model or effort, a closed-set dispatch lacks an
explicit role/model/effort selection, a role is absent from the ledger, or
reviewer-lite is used outside the scoped re-review seam. Representative trace fixtures
exercise orchestration, from-issue, SDD, and shipping paths and assert their ordered
role/model/effort events, including reviewer-lite for fix verification and Opus for
full review.

## Decisions

### One closed role ledger is authoritative

The matrix is data rather than free-form prose. Validation and trace fixtures consume
the same closed role names, while skills keep a nearby readable selection at dispatch
sites. A role not present in the ledger is an error. This avoids a silent fallback and
matches the repository standard for exhaustive closed-set dispatch.

### Opus owns judgment-bearing phases

Issue ownership, design, planning, standards disposition, non-mechanical
implementation, ship ownership, first-pass reviews, both final-review axes, and PR or
whole-branch review explicitly select Opus at high effort. A caller running Sonnet or
Haiku cannot silently downgrade them.

### Reviewer-lite is a distinct restricted role

Reviewer-lite selects Sonnet at medium effort and accepts only a list of named prior
findings plus the bounded fix range. It reports per-finding addressed/not-addressed
status and local breakage in that range. It cannot perform an initial review, discover
new branch-wide findings, adjudicate ambiguous requirements, or review a whole branch.
Any such need routes to the full reviewer.

### Cheap tiers remain bounded and observable

Mechanic selects Sonnet at medium effort for deterministic changes, inventory, and
transport. Explorer selects Haiku at medium effort only for read-only, sharply bounded
fact lookup. If either role encounters ambiguity, it stops or explicitly escalates to
Opus; the controller records the escalation in its existing ledger/report rather than
letting the runtime inherit a model.

### Validation covers declared sites, not arbitrary prose

The validator owns a finite manifest of dispatch-bearing files and recognized dispatch
kinds. It checks exact structured markers and frontmatter, rejects unknown or missing
entries, and asserts that every manifest path still exists. This is intentionally not
a heuristic scan of every Markdown use of the word “dispatch,” which would create both
false positives and silent misses as prose changes.

### Representative traces are deterministic fixtures

Evaluation uses a local trace-emission seam: representative workflow decisions emit
role/model/effort records without launching paid remote agents. Fixtures cover an
orchestration owner dispatch, from-issue design/plan/ship dispatches, SDD mechanical and
non-mechanical tasks, first-pass and scoped re-review, and ship-time full review. The
repository unit suite and Nix build consume these fixtures; live model billing is not a
test dependency.

### Existing review semantics remain intact

The change selects who performs each existing review; it does not collapse the two
final-review axes, weaken review rubrics, change failure classifications, or alter CI,
merge, lifecycle, and cleanup semantics delivered by prior issues.

## Test seams

- The custom-agent frontmatter seam: parse every declared pipeline agent and assert an
  explicit model and effort that matches the role ledger.
- The closed dispatch-manifest seam: parse every enumerated workflow dispatch and
  reject missing, unknown, inherited, or reviewer-lite-ineligible selections.
- The deterministic trace seam: run representative orchestration, from-issue, SDD, and
  shipping scenarios and compare the role/model/effort sequence with the matrix.
- The repository verification seam: run the complete agent-workflow unit suite and the
  Nix configuration build used by shipping.

## Out of scope

- Changing the interactive Claude or Codex default model or reasoning effort.
- Choosing the model used inside the external Codex reviewer runtime.
- Reworking review rubrics, lifecycle persistence, branch policy, CI, or merge policy.
- Dynamic price lookup, token accounting, or model selection based on current prices.
- Applying this matrix to unrelated skills that never participate in issue delivery.

## Auto-resolved decisions

### Canonical tier names
- **Question:** Which concrete model names should the matrix pin?
- **Choice:** Use the runtime's stable aliases `opus`, `sonnet`, and `haiku`, displayed as Opus, Sonnet, and Haiku in the ledger and traces.
- **Grounding:** Existing custom-agent frontmatter already uses `model: sonnet`; issue 15 explicitly names Opus, Sonnet, and Haiku as the desired tiers.
- **Alternative considered:** Pin dated model identifiers. Rejected because the issue asks for durable capability tiers and dated identifiers would turn routine model refreshes into workflow rewrites.

### Effort values
- **Question:** Which effort should each role select?
- **Choice:** Use `high` for judgment-bearing Opus roles and `medium` for bounded Sonnet/Haiku roles.
- **Grounding:** Existing implementer/reviewer agents use high and mechanic uses medium; preserving that precedent changes model selection without inventing a second effort taxonomy.
- **Alternative considered:** Use maximum effort for owners and low effort for exploration. Rejected because existing role contracts establish high/medium and the issue asks for explicit, cost-aware selection rather than a new effort policy.

### Reviewer-lite eligibility
- **Question:** How narrowly should reviewer-lite be constrained?
- **Choice:** Require named prior findings and a bounded fix diff; use the full reviewer for first-pass, ambiguous, or whole-branch work.
- **Grounding:** The issue states this boundary verbatim, and the SDD re-review prompt already consumes named findings and a fix range.
- **Alternative considered:** Let controllers choose reviewer-lite for any “small” review. Rejected because size is subjective and would silently downgrade first-pass judgment.

### Inventory tier
- **Question:** Should bounded inventory always use Haiku or retain Sonnet?
- **Choice:** Use Haiku for read-only fact lookup and Sonnet mechanic for transformations, transport, or inventories whose output changes workflow state.
- **Grounding:** The issue permits Sonnet or Haiku according to boundedness; existing mechanic policy covers inventories plus bookkeeping and already selects Sonnet.
- **Alternative considered:** Move every inventory to Haiku. Rejected because stateful bookkeeping and transformation require the mechanic's stricter stop-on-judgment contract.

### Escalation evidence
- **Question:** Where should a cheap-tier escalation be recorded?
- **Choice:** Record it in the workflow's existing durable ledger, SDD ledger, or fixed-schema report and include the selected Opus role.
- **Grounding:** Issue 15 requires explicit escalation in a ledger or report; the current workflows already persist these artifacts.
- **Alternative considered:** Add a new global audit log. Rejected as redundant scope and a new concurrency surface.

### Validation inventory
- **Question:** How should the check distinguish real dispatch sites from explanatory prose?
- **Choice:** Maintain an exhaustive manifest of dispatch-bearing files and exact structured markers, with fail-loud unknown/missing cases.
- **Grounding:** The universal coding bar requires throwing/failing defaults at closed-set sites; existing tests assert skill contracts from known repository paths.
- **Alternative considered:** Grep all Markdown for model-like words. Rejected because prose is not a stable syntax and a heuristic cannot prove completeness.

### Evaluation mechanism
- **Question:** Must the representative dispatch evaluation launch paid agents?
- **Choice:** Use deterministic local trace fixtures that exercise the same role-selection table and assert exact events; keep live dispatch as a manual demo only.
- **Grounding:** The acceptance criterion asks to inspect a trace and assert the matrix, while the current test suite deliberately avoids agent/network timing.
- **Alternative considered:** Launch real agents in CI. Rejected because nondeterminism, credentials, latency, and spend would make the validation unreliable.

### Spec and grill artifact shape
- **Question:** Does this cross-cutting workflow policy require a new domain ADR or glossary area?
- **Choice:** Keep the decision in this issue spec and the role ledger; create no domain ADR or context-map entry.
- **Grounding:** The repository has no project domain context map for this configuration area, and the grill ADR gate requires a hard-to-reverse, surprising domain trade-off. This matrix is an explicit, test-enforced implementation policy owned by issue 15.
- **Alternative considered:** Introduce a new documentation area solely for agent models. Rejected as structure without an existing domain-doc convention or broader vocabulary need.

### Base and scope checkpoint
- **Question:** Which base and scope should autonomous mode approve after Phase 1?
- **Choice:** Proceed from `27911e47621600849cadedea8aec1b96c3728062` on `origin/main`, covering only issue-delivery model selection, validation, and representative traces.
- **Grounding:** The worktree was created from the current remote main after issue 14 merged; Phase 0 found no active issue-15 PR or worktree.
- **Alternative considered:** Base on the dirty local main checkout or include unrelated default-model changes. Rejected to avoid cross-run contamination and scope expansion.
