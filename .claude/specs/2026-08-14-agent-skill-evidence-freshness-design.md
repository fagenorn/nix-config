# Agent-skill evidence freshness

## Problem

Agent-skill evidence currently records what an operator saw, but not enough about
*when* or *through which deployed path* it was seen. That permits two false
conclusions:

- a Codex command run in an older Claude session, or a direct CLI probe that
  bypassed the production skill and bridge agent, can be presented as proof of
  the currently deployed review bridge; and
- one failed service observation can be promoted from a transient event to a
  standing availability or blocking claim.

The repository needs machine-checked evidence contracts. A failed or partial
run must remain useful forensic evidence, but it must not certify a stronger
claim than it supports.

## Solution

Add one standard-library evidence validator with two explicit document kinds:
`bridge-smoke` and `research-observations`. Each kind has a versioned JSON
contract, focused validation rules, deterministic diagnostics, and fixtures
covering both accepted and rejected claims. The bridge and research skills tell
their agents how to capture these documents and require the validator before a
freshness, availability, or blocking conclusion is reported.

Bridge evidence binds a run to the deployed skill, bridge-agent, and plugin
definitions; names the fresh Claude session that loaded them; and records both
the direct transport probe and the agent-mediated result for each workflow
operation. The claim passes only when the session started after every named
definition was deployed and both `plan-review` and `diff-review` completed via
the production skill-to-agent-to-Codex path. Direct success remains separately
visible but can never substitute for the mediated result.

Research evidence records each observation as its own execution at a specific
time. A single observation may support only an observation-scoped transient
conclusion with an explicit follow-up. A standing conclusion requires at least
two distinct executions at distinct timepoints, and the conclusion names the
observations that corroborate it.

## Decisions

### Two claim-specific schemas behind one command

The validator exposes one command with `bridge` and `research` validation
modes. Both documents carry `schema_version`, `kind`, and a stable claim object,
but their payloads remain separate. This gives skills one deployed entry point
without inventing an abstraction that obscures different proof obligations.

Malformed JSON, an unsupported version, an unknown field needed to make a
claim, or a violated invariant exits non-zero and emits every deterministic
diagnostic found in that pass. Validation never rewrites evidence and never
drops failed observations.

### Bridge evidence contract

A bridge-smoke document contains:

- a unique evidence identifier and capture time;
- a deployment record for the skill, bridge agent, and plugin, each with an
  immutable revision and deployment time;
- the Claude session identifier and start time;
- exactly one record for each required operation, `plan-review` and
  `diff-review`;
- for each operation, a direct-transport observation and an agent-mediated
  observation, each with its own execution time, terminal state, result or
  failure detail, and durable bridge job identifier when one exists; and
- a bridge claim whose status is `certified` only when both mediated operations
  completed successfully.

The validator rejects certification when a definition revision is missing,
the session start precedes any deployed definition, a required operation or
layer is absent, a direct-only result is presented, an execution did not reach
a terminal state, or the claim disagrees with the observations. Direct and
mediated outcomes are never folded into one status, so direct success followed
by agent failure is preserved as exactly that partial result.

Revision values are opaque immutable identifiers: a Git object ID, Nix store
path component, or plugin revision token is acceptable. The capture procedure
must obtain them from the deployed paths visible to the fresh session, not copy
the worktree revision by assumption. Deployment times and session start times
are UTC timestamps with explicit offsets; comparisons normalize them before
the freshness decision.

### Research observation contract

A research-observations document contains:

- a unique evidence identifier and capture time;
- the sharply bounded question;
- a claim with classification `transient` or `standing`, conclusion text,
  explicit observation IDs used by the conclusion, and a follow-up field;
- one or more observations with distinct observation ID, execution ID,
  timestamp, primary-source identity, and outcome.

For a standing claim, at least two claimed observations must have distinct
execution IDs and distinct normalized timestamps. For a transient claim, the
claimed observation set is limited to the recorded execution and the follow-up
must state the independent observation needed before promotion. Duplicate IDs,
duplicate execution IDs, duplicate timepoints, references to absent
observations, and a standing claim with fewer than two qualifying observations
are rejected.

The validator checks the evidence boundary rather than interpreting whether the
research conclusion is intellectually correct. Primary-source citation quality
and synthesis remain reviewer responsibilities; the new contract prevents
those judgments from resting on missing or temporally insufficient evidence.

### Skill behavior

The bridge skill requires a new fresh Claude session after deploying changed
definitions. That session records the revisions it actually loaded, runs both
review operations through the production skill and bridge agent, records the
direct transport result separately as diagnostic context, and validates the
result before calling the bridge current. A stale session or direct-only pass is
reported as rejected evidence, never silently retried into a passing artifact.

The research skill timestamps and identifies every observation. It labels a
single-timepoint result transient, scopes its conclusion to that observation,
and names the independent follow-up. It permits standing availability or
blocking wording only after validation of two qualifying observations.

### Failure behavior

Evidence capture is append-preserving at the document boundary: success in one
layer does not erase a later failure, and a later retry is a new execution with
a new identifier. The validator reports claim failures without converting the
underlying observation into a success. Invalid evidence remains inspectable and
can be submitted to demonstrate why certification was refused.

### Deployment and compatibility

The validator is deployed beside the existing agent-skill helper commands and
uses only Python's standard library. Existing Markdown evidence remains a
historical record but does not satisfy the new checked contract. No migration
or compatibility inference turns old prose into certified evidence.

## Test seams

1. **Validator command boundary.** Invoke the deployed command against temporary
   JSON fixtures and assert exit status plus stable diagnostic codes. This is
   the highest seam shared by skills and CI and follows the existing
   standard-library workflow helper tests.
2. **Bridge claim fixtures.** Pin stale-session rejection, direct-only rejection,
   preserved direct-success/mediated-failure diagnostics, and fresh end-to-end
   certification containing both plan-review and diff-review.
3. **Research claim fixtures.** Pin a single observation as transient with a
   required follow-up, reject its promotion to standing, and accept two distinct
   timestamped executions as corroborated standing evidence.
4. **Skill contract tests.** Assert the bridge and research instructions require
   the fields, production path, validator call, and truthful conclusion language
   on which the executable fixtures depend.
5. **Repository gates.** Run `just agent-workflow-tests`, `just
   agent-model-matrix`, the validator's focused test module, and `just build`.
   The fresh live bridge smoke is captured only after the changed definitions
   are deployed, from a newly started Claude session; its validated artifact is
   the release evidence for the real path rather than a substitute for the
   deterministic tests.

## Out of scope

- Scheduling or continuously monitoring external services.
- Deciding whether a cited primary source is authoritative or whether a
  conclusion is analytically correct.
- Redesigning Codex transport, job persistence, or the reviewer protocol beyond
  exposing and recording identifiers already available to the production path.
- Certifying historical prose evidence retroactively.
- Requiring elapsed sleeps between research observations; independence is an
  execution-and-timepoint property, not an arbitrary wall-clock delay.

## Auto-resolved decisions

### Use claim-specific schemas behind one validator
- **Question:** Should bridge and research proof share one generic evidence schema, use separate tools, or use one command with claim-specific contracts?
- **Choice:** Use one standard-library command with separate `bridge-smoke` and `research-observations` schemas.
- **Grounding:** Issue 16 defines two different proof obligations; the universal DRY rule deduplicates shared policy without forcing merely similar fields into one abstraction, and the repository already deploys Python workflow helpers as stable commands.
- **Alternative considered:** A generic event schema would obscure required fields and make diagnostics indirect; separate executables would duplicate parsing, timestamp, and error-reporting policy.

### Treat mediated success as the certification boundary
- **Question:** Can a successful direct Codex transport probe certify the bridge when the agent-mediated path is absent or fails?
- **Choice:** No. Record direct transport independently for diagnosis, but require successful agent-mediated plan-review and diff-review results for certification.
- **Grounding:** Issue 16 explicitly names Claude skill → bridge agent → Codex result as the production path and says direct-only success cannot pass; the universal truthful-terminal-state rule forbids promoting partial work to completion.
- **Alternative considered:** Accepting direct transport as a fallback was rejected because it recreates the exact false-positive the issue targets.

### Compare session start with every deployed definition
- **Question:** What makes a Claude session fresh enough to certify changed bridge definitions?
- **Choice:** Require the session start to be at or after the deployment time of each named skill, agent, and plugin revision, and require those revisions to come from paths loaded by that session.
- **Grounding:** The acceptance criteria require all three deployed revisions plus a genuinely fresh session, and state that a session predating the definitions must be rejected.
- **Alternative considered:** Comparing only against the plugin deployment or trusting an operator checkbox was rejected because either can leave stale skill or agent instructions unchecked.

### Preserve partial bridge outcomes as evidence
- **Question:** Should a failed agent-mediated run overwrite an earlier direct success or collapse both into one failure status?
- **Choice:** Keep separate execution records and fail only the certification claim, preserving every terminal result or failure detail.
- **Grounding:** The issue requires failure preservation and a distinction between transport and mediated success; the universal log-stream rule requires the original failure to remain available.
- **Alternative considered:** One aggregate status was rejected because it loses the boundary at which the failure occurred.

### Define research independence structurally
- **Question:** How should the validator decide whether two observations independently corroborate a standing conclusion?
- **Choice:** Require distinct observation IDs, execution IDs, and normalized timestamps, with the conclusion explicitly naming both observations.
- **Grounding:** Issue 16 requires independently executed observations at distinct timepoints and identified/timestamped evidence. These are machine-checkable without inventing an arbitrary delay.
- **Alternative considered:** A minimum elapsed duration was rejected because the issue does not define one and sleeping would paper over rather than prove execution independence.

### Make one-observation scope explicit
- **Question:** How can a single observation remain useful without being mistaken for standing proof?
- **Choice:** Require classification `transient`, an explicit observation-ID scope, and a non-empty follow-up describing the independent observation still needed.
- **Grounding:** The acceptance criteria require all three properties; explicit fields make the gate falsifiable rather than relying on prose interpretation.
- **Alternative considered:** A warning-only validator was rejected because callers could still report the standing conclusion while the command exited successfully.

### Keep historical Markdown non-certifying
- **Question:** Should the validator infer structured proof from prior Markdown evidence?
- **Choice:** No. Historical evidence remains readable but only versioned structured documents can pass the new gate.
- **Grounding:** Prior bridge evidence is manual and lacks the freshness data this issue adds; manufacturing missing fields would violate truthful evidence rules.
- **Alternative considered:** Best-effort migration was rejected because it would turn absent session and deployment facts into assumptions.

### Defer the real live smoke until deployment
- **Question:** Can a worktree or direct validator fixture stand in for the required live production-path smoke?
- **Choice:** No. Deterministic fixtures gate implementation, while a newly started Claude session after deployment produces the real validated plan-review and diff-review evidence.
- **Grounding:** The issue expressly rejects older sessions and direct-only shortcuts; the existing bridge evidence precedent also separates build-time proof from post-deployment live proof.
- **Alternative considered:** Calling the validator on synthetic fresh data alone was rejected as test coverage, not live certification.
