# Agent-skill Evidence Freshness Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make bridge freshness and time-separated research claims pass only when a standard-library validator can prove the evidence supports them.

**Architecture:** Deploy one Python command with two typed validation modes, backed by checked JSON fixtures and subprocess-level unit tests. Update the bridge and research skills to capture those documents and treat a successful validator run as the boundary for certification or standing conclusions. Keep direct transport, mediated execution, and research observations as separate records so partial failures remain inspectable.

**Tech stack:** Python 3 standard library, `unittest`, JSON fixtures, Markdown skill contracts, Nix/Home Manager command deployment.

## Global Constraints

- The only certifying bridge path is fresh Claude session → deployed collaboration skill → deployed bridge agent → Codex terminal result.
- Bridge evidence names the deployed skill, agent, and plugin revisions and deployment times; the Claude session must start at or after all three deployments.
- `plan-review` and `diff-review` each require a successful agent-mediated terminal result. Direct transport is diagnostic evidence and cannot substitute.
- Research standing claims require two observations with distinct observation IDs, execution IDs, and normalized timestamps.
- One research observation supports only a transient, observation-scoped conclusion with a non-empty independent follow-up.
- Invalid and partial evidence remains on disk unchanged; validation never rewrites or collapses it.
- Use Python's standard library only. Do not add a schema library or runtime dependency.
- Existing Markdown evidence remains historical and non-certifying.
- Every commit ends with `Co-Authored-By: Codex <noreply@openai.com>` and does not bypass signing.

## Test seams

- Invoke the validator command as a subprocess against committed JSON fixtures; assert its exit status and stable diagnostic codes.
- Assert bridge/research skill text only for the executable contract it must communicate: required fields, production path, validator command, and conclusion limits.
- Run the existing workflow and dispatch-matrix gates unchanged, followed by `just build`.

## File structure

- `home/common/agent-skills/scripts/agent-evidence.py` — owns parsing, typed validation rules, stable diagnostics, and the CLI.
- `home/common/agent-skills/tests/test_agent_evidence.py` — owns subprocess tests over public CLI behavior.
- `home/common/agent-skills/tests/fixtures/evidence/*.json` — one readable proof or counterexample per acceptance scenario.
- `home/common/agent-skills/default.nix` — deploys the command at `~/.agents/bin/agent-evidence`.
- `home/common/claude-code/skills/codex-collaboration/SKILL.md` — owns production bridge capture/certification instructions.
- `home/common/agent-skills/skills/research/SKILL.md` — owns research observation and conclusion instructions.
- `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — pins both skill contracts to the validator interface.

## Auto-resolved decisions

### Three tasks along executable boundaries
- **Question:** How should the work be divided for independent implementation and review?
- **Choice:** Task 1 builds and deploys the validator with fixtures; Task 2 integrates both skill contracts and their contract tests; Task 3 runs cross-component/build verification and records the live-smoke procedure.
- **Grounding:** The approved spec defines one executable seam and two caller contracts; a reviewer can accept validator semantics while rejecting either agent-facing instruction surface.
- **Alternative considered:** One monolithic task was rejected because validation bugs and prompt-contract bugs require different review evidence. Separate bridge and research tasks were rejected because their edits share one small contract-test file and validator interface.

### Stable diagnostic codes on stderr
- **Question:** What output should callers and tests rely on when evidence is invalid?
- **Choice:** Emit every finding as `CODE path: message` on stderr in stable sorted order, return 2 for invalid evidence or malformed input, and print one `VALID <kind> <evidence_id>` line on stdout with exit 0 when clean.
- **Grounding:** The spec requires deterministic diagnostics without rewriting evidence; the repository's helper CLIs already use process exit status as the public automation seam.
- **Alternative considered:** JSON output was rejected as needless protocol surface for a local validator; matching full human prose was rejected as brittle.

### Commit readable scenario fixtures
- **Question:** Should validation cases construct dictionaries inline or use committed artifacts matching what operators submit?
- **Choice:** Commit five minimal JSON fixtures: stale bridge, direct-only bridge, fresh end-to-end bridge, single failed research observation, and corroborated research observations.
- **Grounding:** Issue 16's demo says to submit these artifact shapes to validators; subprocess tests over real files exercise that boundary directly.
- **Alternative considered:** Inline-only fixtures were rejected because they do not demonstrate the operator-facing artifact and command together.

### Deploy beside existing workflow helpers
- **Question:** How should skills find the validator outside this repository checkout?
- **Choice:** Add the script to Home Manager as executable `.agents/bin/agent-evidence`, beside `workflow-state`, `agent-model-matrix`, and `context-map-lint`.
- **Grounding:** `home/common/agent-skills/default.nix` is the existing source of stable user-level workflow commands.
- **Alternative considered:** Calling the repository-relative script was rejected because live deployed skills may run in unrelated repositories.

### Strict known-version documents
- **Question:** Should the validator ignore unknown versions or attempt best-effort inference?
- **Choice:** Accept only `schema_version: 1` and the requested kind, with required typed fields; reject unknown versions and claim-affecting malformed values.
- **Grounding:** Historical prose cannot be certified and missing freshness facts cannot be inferred truthfully.
- **Alternative considered:** Permissive forward compatibility was rejected because accepting an unknown claim format is a false certification risk.

### UTC-aware timestamp comparisons
- **Question:** Which timestamp forms count as distinct and fresh?
- **Choice:** Accept ISO-8601 timestamps only when they carry an explicit offset, normalize to UTC, and compare parsed instants rather than strings.
- **Grounding:** The spec requires explicit-offset UTC-comparable timepoints and rejects arbitrary wall-clock sleeps.
- **Alternative considered:** Lexical comparison and naive timestamps were rejected because equivalent offsets and local-time ambiguity can invert freshness decisions.

### Contract tests pin obligations, not prose layout
- **Question:** How tightly should tests couple to the Markdown skill wording?
- **Choice:** Assert stable schema/command tokens and required production-path/conclusion rules while allowing explanatory wording and section placement to change.
- **Grounding:** The universal tests-that-fail rule favors observable contract boundaries over incidental implementation wording.
- **Alternative considered:** Snapshotting whole skill files was rejected because unrelated editorial changes would fail without changing behavior.

### Live certification remains a post-deployment gate
- **Question:** Can deterministic fixture success be reported as the required live bridge validation?
- **Choice:** No. Task 3 verifies the implementation and writes the exact post-deployment procedure; certification requires deploying the candidate definitions and starting a new Claude session to create an actual artifact.
- **Grounding:** The issue rejects stale sessions and direct-only shortcuts; the approved spec distinguishes deterministic tests from release evidence.
- **Alternative considered:** Committing a synthetic passing live artifact was rejected because it would be test data mislabeled as an observation.

### B-01: Validate the complete bridge record
- **Question:** The reviewer found that the plan required mediated success but did not explicitly test or implement exactly one required operation, both layers, terminal result/failure shape, and claim consistency.
- **Choice:** Validate and test the whole bridge document before certification: exactly one plan-review and diff-review, exactly one direct and agent-mediated record for each, terminal payload shape for both layers, and a claim that agrees with the mediated observations.
- **Grounding:** The approved spec's bridge contract rejects a missing operation or layer, nonterminal execution, and claim disagreement; the reviewer cited the Task 1 gaps against that contract.
- **Alternative considered:** Reviewer's call accepted as-is.

### B-02: Validate every research observation before claim scoping
- **Question:** The reviewer found that validating uniqueness only across claim-referenced observations could let malformed unreferenced records pass inside certified evidence.
- **Choice:** Type-check and enforce unique observation IDs, execution IDs, and normalized timestamps across every recorded observation, then validate the claim's referenced subset.
- **Grounding:** The approved spec defines document-wide observation integrity and explicitly rejects duplicate identifiers and timepoints; the reviewer verified Task 1 had narrowed that invariant incorrectly.
- **Alternative considered:** Reviewer's call accepted as-is.

### S-01: Run the named workflow gate
- **Question:** The reviewer found that Task 3 enumerated the same Python test modules but omitted the approved spec's exact `just agent-workflow-tests` gate.
- **Choice:** Add the exact Justfile gate to whole-issue verification in addition to the focused evidence tests.
- **Grounding:** The spec and existing Justfile name that stable repository command, which is the interface maintainers expect CI and reviewers to exercise.
- **Alternative considered:** Treating equivalent direct unittest invocation as sufficient was rejected because it can drift from the repository-owned recipe.

### S-02: Keep session creation outside the running bridge skill
- **Question:** The reviewer found ambiguity in asking an already-running skill invocation to start the fresh session whose loaded definitions it must certify.
- **Choice:** State that certification is invoked from an externally started post-deployment session; the shipping owner creates that session and hands it the capture operation.
- **Grounding:** The post-deployment live gate already owns sequencing, and a session cannot prove its own pre-start deployment boundary by recursively replacing itself.
- **Alternative considered:** An in-session session-spawn mechanism was rejected because no supported, separately identified mechanism is documented in the live repository.

## Standards review provenance

- **Reviewer:** Native Codex reviewer (`plan_review`), fresh context, read-only
- **Base SHA:** `6b903d0875e059868436f41c92b0b0a59f1debc8`
- **Focus:** issue/spec conformance, executable evidence boundaries, repository verification gates
- **Disposition:** 4 accepted, 0 rejected, 0 deferred; 0 Discussion items
- **Fallback:** Native-reviewer path selected because `codex-collaboration` is Claude-only in this Codex session

---

### Task 1: Evidence validator, fixtures, and deployment

**Files:**
- Create: `home/common/agent-skills/scripts/agent-evidence.py`
- Create: `home/common/agent-skills/tests/test_agent_evidence.py`
- Create: `home/common/agent-skills/tests/fixtures/evidence/bridge-stale-session.json`
- Create: `home/common/agent-skills/tests/fixtures/evidence/bridge-direct-only.json`
- Create: `home/common/agent-skills/tests/fixtures/evidence/bridge-fresh-end-to-end.json`
- Create: `home/common/agent-skills/tests/fixtures/evidence/research-single-failure.json`
- Create: `home/common/agent-skills/tests/fixtures/evidence/research-corroborated.json`
- Modify: `home/common/agent-skills/default.nix`

**Interfaces:**
- Consumes: `agent-evidence bridge <artifact.json>` and `agent-evidence research <artifact.json>`.
- Produces: exit 0 plus `VALID <kind> <evidence_id>` on stdout when all claim invariants hold; exit 2 plus sorted `CODE path: message` diagnostics on stderr otherwise. Task 2 copies these two command forms verbatim.

- [ ] **Step 1: Write the five fixtures and failing subprocess tests**

Use the approved spec's exact contracts. Bridge fixtures carry:

```json
{
  "schema_version": 1,
  "kind": "bridge-smoke",
  "evidence_id": "bridge-fresh-e2e",
  "captured_at": "2026-08-14T12:10:00Z",
  "deployment": {
    "skill": {"revision": "skill-r2", "deployed_at": "2026-08-14T12:00:00Z"},
    "agent": {"revision": "agent-r2", "deployed_at": "2026-08-14T12:00:01Z"},
    "plugin": {"revision": "plugin-r2", "deployed_at": "2026-08-14T12:00:02Z"}
  },
  "session": {"id": "claude-fresh-1", "started_at": "2026-08-14T12:01:00Z"},
  "claim": {"status": "certified"},
  "operations": []
}
```

Populate `operations` with exactly `plan-review` and `diff-review`; each has
`direct` and `agent_mediated` records containing `execution_id`, `observed_at`,
terminal `status`, and `result` or `failure`. Successful mediated records also
carry `job_id`. The stale fixture moves session start before one deployment. The
direct-only fixture records direct success and mediated failure for both
operations and sets claim status `rejected` so the evidence remains truthful
while the certification command still exits 2.

Research fixtures carry:

```json
{
  "schema_version": 1,
  "kind": "research-observations",
  "evidence_id": "service-single-failure",
  "captured_at": "2026-08-14T13:00:00Z",
  "question": "Is the service presently available?",
  "claim": {
    "classification": "transient",
    "conclusion": "The request failed at the recorded observation.",
    "observation_ids": ["obs-1"],
    "follow_up": "Run one independent observation before making a standing availability claim."
  },
  "observations": [
    {"id": "obs-1", "execution_id": "exec-1", "observed_at": "2026-08-14T12:59:00Z", "source": "first-party API", "outcome": "failed"}
  ]
}
```

The corroborated fixture uses classification `standing`, two observations,
two execution IDs, and two distinct timestamps.

Tests invoke `sys.executable` plus the script path for hermeticity and assert:

```python
def run_validator(kind: str, fixture: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), kind, str(FIXTURES / fixture)],
        text=True,
        capture_output=True,
        check=False,
    )
```

Required cases: fresh bridge passes; stale emits `BRIDGE_SESSION_STALE`;
direct-only emits `BRIDGE_MEDIATED_REQUIRED` while its failure text remains in
the fixture; missing and duplicate required operations reject; a missing direct
or mediated layer rejects; nonterminal records and terminal records without the
matching result/failure payload reject; a certified claim over failed mediated
observations and a rejected claim over fully successful mediated observations
both emit `BRIDGE_CLAIM_MISMATCH`; single research failure passes as transient;
changing its claim to standing in a temporary file emits
`RESEARCH_CORROBORATION_REQUIRED`; corroborated research passes; duplicate
observation/execution/time values anywhere in the document reject, including
unreferenced observations; naive timestamps reject; unsupported schema and
wrong kind reject.

- [ ] **Step 2: Run the focused tests and observe the missing-command failure**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_evidence.py`

Expected: FAIL because `home/common/agent-skills/scripts/agent-evidence.py` does not exist.

- [ ] **Step 3: Implement the minimal standard-library validator**

Use `argparse`, `json`, `dataclasses`, `datetime`, and `pathlib`. Keep the public
entry points:

```python
@dataclass(frozen=True, order=True)
class Diagnostic:
    code: str
    path: str
    message: str

def validate_bridge(document: object) -> list[Diagnostic]: ...
def validate_research(document: object) -> list[Diagnostic]: ...
def main(argv: Sequence[str] | None = None) -> int: ...
```

Parse timestamps through one helper that requires `tzinfo` and normalizes to
UTC. Type-check before descending so malformed documents return diagnostics
instead of tracebacks. For bridge certification, collect all three deployment
instants, compare the session start with their maximum, reject duplicate or
unknown operation names, and require exactly one `plan-review` and one
`diff-review`. Each operation must contain exactly one `direct` and one
`agent_mediated` record. Both layers require a terminal status plus a non-empty
`result` for completion or `failure` for unsuccessful terminal states;
successful mediated records additionally require a job ID. Direct outcomes do
not certify, but their record shape is still validated. Require the claim status
to agree with the combined mediated outcomes. For research, validate types and
uniqueness of IDs, execution IDs, and normalized timestamps across every
observation first; then resolve claim references and enforce transient or
standing rules over the referenced subset.

- [ ] **Step 4: Deploy the command**

Add an executable Home Manager entry following the existing helper precedent:

```nix
".agents/bin/agent-evidence" = {
  source = ./scripts/agent-evidence.py;
  executable = true;
};
```

- [ ] **Step 5: Verify Task 1**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_evidence.py`

Expected: all evidence tests pass; the fresh bridge, transient single failure,
and corroborated research fixtures exit 0, while stale/direct-only/promoted or
duplicate variants exit 2 with their stable codes.

Run: `python3 home/common/agent-skills/scripts/agent-evidence.py bridge home/common/agent-skills/tests/fixtures/evidence/bridge-stale-session.json`

Expected: exit 2 and stderr contains `BRIDGE_SESSION_STALE`.

- [ ] **Step 6: Commit Task 1**

```bash
git add home/common/agent-skills/scripts/agent-evidence.py \
  home/common/agent-skills/tests/test_agent_evidence.py \
  home/common/agent-skills/tests/fixtures/evidence \
  home/common/agent-skills/default.nix
git commit -m "feat(agents): validate evidence freshness

Co-Authored-By: Codex <noreply@openai.com>"
```

### Task 2: Bridge and research skill contracts

**Files:**
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Modify: `home/common/agent-skills/skills/research/SKILL.md`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: Task 1 commands `agent-evidence bridge <artifact.json>` and `agent-evidence research <artifact.json>`, schema version 1, and its stable bridge/research field names.
- Produces: deployed skills that create and validate truthful artifacts before claiming fresh bridge certification or standing research availability/blocking.

- [ ] **Step 1: Add failing skill-contract tests**

Load `RESEARCH` alongside the existing collaboration skill path and assert the
stable contract fragments. Bridge assertions cover `schema_version`,
`bridge-smoke`, `skill`, `agent`, `plugin`, session `started_at`, both operation
names, distinct `direct` and `agent_mediated`, `agent-evidence bridge`, stale
rejection, and no direct-only certification. Research assertions cover
`research-observations`, observation/execution identity, `observed_at`,
`transient`, `standing`, two independent timepoints, follow-up, and
`agent-evidence research`.

- [ ] **Step 2: Run the focused contract tests and observe failure**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: the new issue-16 contract tests fail because neither skill names the
structured evidence validator or all required fields.

- [ ] **Step 3: Update the bridge skill**

Add a bounded live-evidence section stating that certification is invoked from
an externally started fresh session after the candidate definitions are
deployed. It instructs that fresh session to:

1. capture the deployed skill/agent/plugin revisions and deployment timestamps
   from the paths actually loaded;
2. record its own externally established session ID and start time;
3. run `plan-review` and `diff-review` through the collaboration skill and
   bridge agent, recording their job IDs and terminal outcomes;
4. record any direct transport probes separately without treating them as the
   mediated result;
5. keep partial failures in the artifact and run `agent-evidence bridge
   <artifact.json>`; and
6. call the bridge current only when that command exits 0.

Do not weaken the existing read-only, timeout, fallback, or output contracts.

- [ ] **Step 4: Update the research skill**

Require every live availability/blocking observation to carry an observation
ID, independent execution ID, explicit-offset timestamp, source identity, and
outcome. Require one observation to produce a `transient` conclusion scoped to
that observation plus a non-empty follow-up; permit `standing` only after two
distinct executions/timepoints. Require `agent-evidence research
<artifact.json>` before returning a standing conclusion, while keeping the
existing one-artifact and fixed report contracts.

- [ ] **Step 5: Verify Task 2**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_agent_evidence.py`

Expected: all workflow-contract and evidence-validator tests pass; no existing
contract test regresses.

Run: `just agent-model-matrix`

Expected: `agent model matrix: valid` and the representative trace completes;
the existing marked dispatch lines still parse exactly once.

- [ ] **Step 6: Commit Task 2**

```bash
git add home/common/claude-code/skills/codex-collaboration/SKILL.md \
  home/common/agent-skills/skills/research/SKILL.md \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -m "feat(agents): require corroborated skill evidence

Co-Authored-By: Codex <noreply@openai.com>"
```

### Task 3: Whole-issue verification and live-smoke handoff

**Files:**
- Modify only if a verified gate exposes a defect in a Task 1 or Task 2 file.

**Interfaces:**
- Consumes: Task 1's validator/fixtures and Task 2's deployed capture contracts.
- Produces: a branch proven by deterministic repository gates plus an exact post-deployment live-smoke handoff; it does not fabricate a live artifact inside the worktree.

- [ ] **Step 1: Run the full deterministic suite**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_evidence.py home/common/agent-skills/tests/test_workflow_state.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: all tests pass with no failures or errors.

Run: `just agent-workflow-tests`

Expected: the repository-owned workflow gate passes every workflow-state and
skill-contract test.

Run: `just agent-model-matrix`

Expected: validation and representative trace succeed.

- [ ] **Step 2: Run the repository build**

Run: `just build`

Expected: exit 0; the produced Home Manager closure contains executable
`.agents/bin/agent-evidence` and the updated bridge/research skill text.

- [ ] **Step 3: Exercise the issue demo against the command**

Run the deployed-build script path or repository script against all five
committed fixtures. Expected observations:

- stale bridge: non-zero with `BRIDGE_SESSION_STALE`;
- direct-only bridge: non-zero with `BRIDGE_MEDIATED_REQUIRED`, with direct
  success and mediated failure still present in the artifact;
- fresh end-to-end bridge: `VALID bridge-smoke`;
- single service failure: `VALID research-observations` only as transient;
- corroborated research: `VALID research-observations` as standing.

- [ ] **Step 4: Prepare the post-deployment live gate**

In the execution report, record this exact non-synthetic gate for the shipping
owner: after the candidate definitions are deployed, the deployment owner seals
an immutable receipt containing their authoritative paths, revisions,
`deployed_at` timestamps, and an assigned session ID. As one launch action, the
launcher creates an immutable envelope with that same ID and the actual
`started_at` timestamp, then starts a new external Claude session. Give both
objects to the session read-only; it must verify the IDs match, independently
resolve the definitions it loaded, and match their paths and revisions to the
receipt. The deploying session cannot certify itself, and receipt/envelope facts
remain external provenance rather than evidence-schema fields. The fresh session
then runs real plan-review and diff-review through the collaboration skill and
bridge agent, preserves direct and mediated results in one bridge-smoke JSON
document, and runs `agent-evidence bridge <artifact.json>`. Do not report live
certification unless it exits 0. If deployment/session authority is unavailable,
report the live gate as unverified rather than substituting fixtures.

- [ ] **Step 5: Scope-check the branch**

Run: `git diff --check origin/main...HEAD`

Expected: no output.

Run: `git diff --stat origin/main...HEAD -- home/common/agent-skills home/common/claude-code/skills/codex-collaboration/SKILL.md`

Expected: only the validator, fixtures, deployment wiring, skill contracts, and
their tests appear; spec/plan artifacts are deliberately outside this pathspec.

- [ ] **Step 6: Commit verified corrections, if any**

If Steps 1–5 required a correction, commit only the verified issue-16 files:

```bash
git add home/common/agent-skills home/common/claude-code/skills/codex-collaboration/SKILL.md
git commit -m "fix(issue-16): satisfy evidence verification

Co-Authored-By: Codex <noreply@openai.com>"
```

If no correction was required, create no empty commit.
