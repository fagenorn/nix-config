# Phase 7 detail — ship handoff and inline fallback

Loaded from `SKILL.md` at Phase 7.

## Ship-owner subagent prompt

The handoff goes in the prompt, not a file — the subagent's starting context *is*
the prompt. Recheck the current spec and plan roots immediately before building
it and include their canonical checker objects. The public handoff must never carry task member paths
and must never carry artifact contents; ship-issue
discovers validated members locally. A durable SDD `report_path` is relative to
the primary worktree and is the only detail pointer.

```
You are running ship-issue for issue #<num> in <autonomous|interactive> mode. Use
"autonomous" only when the from-issue invocation included `--auto`; otherwise use
"interactive".

Handoff from from-issue is the canonical stdout from
`artifact-budget validate-report --boundary ship-handoff` over a candidate. With
lifecycle identity the candidate is `ship-handoff/v2`, exactly these fields:
{"interface_version":2,"state":"complete","ledger_repo_root":"<immutable ledger root>","run_id":"<run>","owner":"<owner>","owner_worktree":"<owner worktree>","custody":<owner custody object>,"issue_number":<num>,"branch":"<branch-name>","worktree_path":"<absolute-worktree-path>","spec_artifact":{"kind":"design-spec","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"plan_artifact":{"kind":"implementation-plan","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"head_sha":"<full sha>","review_state":"clean|residuals","auto":true,"report_path":null,"notes":"<bounded notes>","delivery_contract":<installed contract>,"delivery_contract_digest":"<contract digest>","authorization_intents":[<initial intent>],"authorization_chain_digest":"<chain digest>","authority_observation_ids":[],"reevaluation_evidence_ids":[],"authority_evaluation_consumption_ids":[],"pending_stage_ids":[<pending stage ids>],"selected_outputs":[],"requested_scope":null}
Without lifecycle identity the candidate is the legacy handoff, exactly these
fields, with the whole lifecycle group null:
{"state":"complete","ledger_repo_root":"<immutable ledger root or null>","run_id":"<run or null>","attempt":<integer or null>,"owner":"<owner or null>","owner_worktree":"<owner worktree or null>","action_id":"<action id or null>","issue_number":<num>,"branch":"<branch-name>","worktree_path":"<absolute-worktree-path>","spec_artifact":{"kind":"design-spec","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"plan_artifact":{"kind":"implementation-plan","path":"<root>","metrics":{"root_bytes":<int>,"total_bytes":<int>,"file_count":<int>,"largest_member_bytes":<int>},"budget_status":"within_budget"},"head_sha":"<full sha>","review_state":"clean|residuals","auto":true,"report_path":null,"notes":"<bounded notes>"}

In `ship-handoff/v2`, `custody`, `delivery_contract` and
`delivery_contract_digest` are the owner object's `custody`, `contract` and
`contract_digest`, and `pending_stage_ids` is its `pending_stage_ids`.
`authorization_intents` is the one initial intent the builder regenerates from
that contract, printed by
`workflow-state build-delivery --repo-root <ledger_repo_root> --kind initial-intent --input -`
over `{"contract": <installed contract>}` in a quoted heredoc.
`authorization_chain_digest` is `sha256:` plus the SHA-256 hex of the bytes
`{"intent_ids":["<initial intent id>"]}` and a newline; the validator refuses
any other value. The three id arrays and `selected_outputs` are the ones this
owner actually holds — empty at a first ship — and `requested_scope` is null.
The handoff records historical custody and grants no current-stage authority:
the ledger, not the handoff, is current truth. A v2 handoff carries the full
contract, so its boundary reads it under the `workflow_responses` wire bound.

Use `state: failed` only according to the ship-handoff validator's before/after
matrix. `notes` is bounded by `phase_reports.notes_max_characters`; it names a
non-null `report_path`. Feed the candidate to
`artifact-budget validate-report --boundary ship-handoff --input -` through a
quoted heredoc, and dispatch only the validated stdout bytes. A residual SDD
report requires the durable path.

`action_id` is the `issue:attempt:launch` string the acquisition envelope
issued; it joins the all-or-nothing lifecycle group and is passed through
verbatim — never recomputed, never derived from `attempt` — so ship-issue's
launch guard can re-validate it before each forge write. In `ship-handoff/v2`
it is `custody.action_id`.

Your task:
  1. Invoke the `ship-issue` skill via the Skill tool. Read its SKILL.md and follow
     every phase 0 → 8 in order. The pre-flight checks still run — the handoff is a
     hint, the worktree state is ground truth.
  2. In Phase 5 (PR review), follow ship-issue's path selection — it may dispatch
     zero (empty merge-delta), one, or two reviewer subagents.
     Nested Agent calls are supported.
  3. In Phase 6, block on `<tracker-cli> pr checks --watch` per ship-issue's
     instructions.
  4. If auto is true, apply ship-issue's auto-mode rules throughout: apply Blocking
     and Should-fix items inline rather than surfacing; only Discussion items and
     genuinely blocked situations should return to me. If auto is false, honor every
     ship-issue checkpoint and confirmation; return anything requiring a user decision
     instead of treating it as autonomous.
  5. With a `ship-handoff/v2`, run ship-issue's `## Delivery loop` from its
     first null-scope `checkpoint-delivery` through the pre-merge selection gate
     and every post-selection cycle. Under this implementation custody you write
     only `checkpoint-delivery`, never `finish`: the completing observations
     ride your returned summary.

Launch any subagent by type only, never by name: a subagent cannot spawn a named
teammate, and a named launch returns an error instead of work. Read an existing
file before writing to it: overwriting content you have not read destroys work
you cannot see.

Return exactly canonical JSON from `artifact-budget validate-report --boundary ship-summary`.
With a `ship-handoff/v2`, validate a `ship-summary/v2` with exactly these keys:
`interface_version` (2), `issue`, `state` (`delivery_complete` or
`terminal_failed`), `custody` (the handoff's), `historical_owner_result`,
`delivery_contract_digest`, `delivery_observations`, `authority_observations`,
`reevaluation_evidence`, `detail_state`, `report_path`, and `notes`. Its
`historical_owner_result` is the legacy row below, and its observation arrays
carry the completing observations ship-issue's `## Delivery loop` names, or the
partial ones of a failure. The one exception is a denial ship-issue's loop
checkpointed: it has already suspended the custody, so return only the re-entry
line ship-issue prints. Without lifecycle identity, validate that legacy row
itself, with these exact keys: `issue`, `state`, `pr_url`,
`merge_sha`, `issue_closed`, `discussion_items`, `detail_state`, `report_path`,
and `notes`. `discussion_items: []` because non-empty details are moved to the
single report. `detail_state` is `none`, `present`, or failure-only `unpublished`
per the validator matrix. With `unpublished`, name the readable retained source
and the root it resolves against in notes — a retained path is
worktree-relative, unlike a `present` one — keep the worktree, and do not claim
merge success. Never inline detail.
```

## Inline fallback (no ship-issue skill)

Deliver inline: push the branch, open a PR against `<integration-branch>`, then use the same full-review tier over the diff:

<!-- agent-dispatch: id=from-issue-inline-ship-review role=reviewer model=opus effort=high -->
Agent(subagent_type="reviewer", model="opus", effort="high") launches a fresh first-pass reviewer over the shipping diff.

Then wait for CI (`<tracker-cli> pr checks --watch`), merge `--no-ff`, close the
issue, and publish every non-empty review detail beneath the primary worktree's
`.superpowers/issue-delivery/` home before cleanup. Publication failure must keep
the worktree and report `unpublished`. With `issueTracker.kind=none`, merge
locally and clean up under the same detail rule.

## Remainder owner prompt

For a validated `delivery_remainder` object, launch the ship owner through the
same `from-issue-ship-owner` site with this prompt, carrying the object's
canonical JSON verbatim. A remainder has no spec, plan or reviewed head of its
own, so it gets no `ship-handoff/v2`:

```text
You are running ship-issue for issue #<num> in remainder mode, autonomously.

Delivery remainder from from-issue is this validated `delivery_remainder`
object, canonical JSON, verbatim:
<canonical-json>
Validate it with `artifact-budget validate-report --boundary workflow-response --input -`
before decoding any field.

Your task: invoke the `ship-issue` skill via the Skill tool and follow its
`## Remainder mode` from the ledger's ready stage. You hold this remainder
custody, so you write its `checkpoint-delivery` cycles and your own
`workflow-state finish --summary-file -`, then return exactly that finish's
validated JSON stdout and nothing else.

<the two leaf-agent sentences of the ship-owner prompt above, verbatim>
```

The placeholder line stands for those two sentences copied verbatim as a
paragraph of their own; they are spelled once in this file, inside the
ship-owner prompt.
