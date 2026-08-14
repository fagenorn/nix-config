# Cost-aware issue-workflow model matrix implementation plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Make every issue-pipeline agent and closed dispatch site select an explicit, validated model and effort, with a Sonnet reviewer-lite restricted to scoped re-reviews.

**Architecture:** A checked-in JSON matrix is the closed source of role/model/effort truth. A Python validator parses custom-agent frontmatter and exact `agent-dispatch` markers in the finite workflow inventory, and emits deterministic representative traces. Skills continue to own orchestration behavior while each dispatch instruction names its matrix selection beside the call.

**Tech stack:** Markdown skill/agent definitions, JSON fixtures, Python 3 standard library/unittest, Nix Home Manager wiring.

## Global Constraints

- Opus/high owns issue and ship ownership, design/planning judgment, non-mechanical implementation, and first-pass, plan, conformance, correctness, PR, and whole-branch reviews.
- Sonnet/medium owns deterministic mechanic and transport work.
- Haiku/medium owns sharply bounded read-only exploration.
- Reviewer-lite is Sonnet/medium and is legal only with named prior findings plus a bounded fix diff; it never performs a first pass, ambiguous adjudication, or whole-branch review.
- Every custom pipeline agent and every dispatch site in the closed manifest declares or selects both model and effort; unknown or omitted cases fail loudly.
- Cheap-tier escalation to Opus is explicit in the workflow ledger or fixed-schema report.
- Do not change review rubrics, lifecycle persistence, CI, merge policy, interactive defaults, or the model inside the external Codex reviewer runtime.
- All implementation commits include `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Test seams

- Parse all custom pipeline-agent frontmatter and compare it with the matrix.
- Parse the closed dispatch manifest and exact dispatch markers; reject omissions, unknown roles, matrix mismatches, and reviewer-lite misuse.
- Emit deterministic JSONL traces for representative orchestration, from-issue, SDD, and shipping scenarios and compare exact role/model/effort events.
- Run the complete workflow unit suite and `nix build .#darwinConfigurations.anis-mbp.system` (or the current host's equivalent flake output).

## Auto-resolved decisions

### Machine-readable contract location
- **Question:** Where should the closed role matrix live?
- **Choice:** Add `home/common/agent-skills/model-matrix.json` so shared skills, tests, and Nix wiring can reference one repository-owned contract.
- **Grounding:** The spec requires one authoritative data ledger; `home/common/agent-skills` already owns cross-runtime workflow skills and tests.
- **Alternative considered:** Put the matrix under Claude-only configuration. Rejected because the shared from-issue, SDD, and shipping skills also consume it.

### Dispatch annotation syntax
- **Question:** How should Markdown dispatch sites expose their selections to both agents and validation?
- **Choice:** Put an exact HTML marker immediately before each call instruction: `<!-- agent-dispatch: id=<id> role=<role> model=<model> effort=<effort> -->`, followed by prose that repeats the selection.
- **Grounding:** The spec rejects heuristic prose parsing and requires human-readable selections beside calls; HTML comments are stable without affecting rendered instructions.
- **Alternative considered:** Infer selection only from agent-type names. Rejected because general-purpose owners and reviewer-lite eligibility would remain implicit.

### Validator interface
- **Question:** How should CI and reviewers run validation and inspect a trace?
- **Choice:** Add a standard-library CLI with `validate` and `trace <scenario>` commands and install it as `.agents/bin/agent-model-matrix`; unittest calls the same functions.
- **Grounding:** Existing agent tooling installs Python helpers in `.agents/bin`; issue 15 asks for a runnable representative evaluation and inspectable trace.
- **Alternative considered:** Encode all assertions directly in unittest. Rejected because there would be no stable demo command or trace surface.

### Task boundaries
- **Question:** How should the work be divided for independent review?
- **Choice:** Land the validator/ledger/agent roles first, then orchestration/from-issue, then SDD/reviewer-lite, then shipping and integrated traces.
- **Grounding:** Each slice creates a green, testable subset and lets a reviewer reject one workflow mapping without invalidating the role contract.
- **Alternative considered:** One repository-wide edit. Rejected because the acceptance surface spans distinct owner, implementation/review, and shipping decisions.

### Verification scope
- **Question:** Which build demonstrates repository integration?
- **Choice:** Run the workflow unittest discovery after every task and the host flake system build in the final task/ship phase.
- **Grounding:** The current justfile exposes workflow tests and the repository's primary build is a Nix system output.
- **Alternative considered:** Run live paid agents in CI. Rejected by the spec's deterministic, credential-free evaluation seam.

---

### Task 1: Closed matrix, validator, and custom agent tiers

**Files:**
- Create: `home/common/agent-skills/model-matrix.json`
- Create: `home/common/agent-skills/scripts/agent-model-matrix.py`
- Create: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Create: `home/common/claude-code/agents/reviewer-lite.md`
- Modify: `home/common/claude-code/agents/implementer.md`
- Modify: `home/common/claude-code/agents/reviewer.md`
- Modify: `home/common/claude-code/agents/mechanic.md`
- Modify: `home/common/agent-skills/default.nix`
- Modify: `home/common/claude-code/default.nix`

**Interfaces:**
- Consumes: Python 3 standard library and existing YAML-like agent frontmatter.
- Produces: matrix roles `issue-owner`, `ship-owner`, `implementer`, `reviewer`, `reviewer-lite`, `mechanic`, `explorer`, and `codex-transport`; CLI functions `load_matrix(root)`, `validate(root) -> list[str]`, and `trace(root, scenario) -> list[dict[str, str]]`.

- [ ] **Step 1: Write the failing contract tests**

Add tests which load the new matrix, assert the exact model/effort pairs from Global Constraints, enumerate every file in `home/common/claude-code/agents`, require explicit `model:` and `effort:`, require each agent's role to match the matrix, and assert the CLI reports missing manifest files and unknown roles as errors. Include a temporary-fixture test proving an omitted model fails.

- [ ] **Step 2: Run the tests and watch them fail**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: FAIL because the matrix, validator, and reviewer-lite agent do not exist and implementer/reviewer omit `model:`.

- [ ] **Step 3: Implement the minimal role contract**

Create JSON with top-level `roles`, `dispatch_sites`, and `scenarios`. Each role contains lowercase `model`, `effort`, `eligible`, and `prohibited` arrays. Implement strict JSON loading, repository-root resolution, agent-frontmatter parsing, exact manifest-path existence checks, dispatch-marker comparison, duplicate-id rejection, and reviewer-lite eligibility validation. No fallback role or model is permitted. Add `model: opus` to implementer/reviewer, keep mechanic Sonnet/medium, and add reviewer-lite Sonnet/medium with the named-finding/bounded-diff contract. Install the CLI in `.agents/bin` and update the agent-tier comment/list.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: PASS; temporary omission/unknown-role fixtures are rejected and all four custom agents match the ledger.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json home/common/agent-skills/scripts/agent-model-matrix.py home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/default.nix home/common/claude-code/agents home/common/claude-code/default.nix
git commit -m "feat(agents): declare explicit model roles (#15)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 2: Explicit orchestration and issue-owner dispatches

**Files:**
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Modify: `home/common/claude-code/skills/orchestrate-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/design/SKILL.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/SKILL.md`
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`
- Modify: `home/common/agent-skills/skills/doc-grounded-questions/SKILL.md`

**Interfaces:**
- Consumes: Task 1 matrix schema and `agent-dispatch` marker parser.
- Produces: manifest entries and markers for orchestration issue-owner, autonomous design/grill, autonomous planning, standards review, phase delegation, shipping handoff, and bounded exploration dispatches.

- [ ] **Step 1: Extend tests with failing owner-site expectations**

Add exact expected IDs and matrix selections for every dispatch in the listed owner/design skills. Assert from-issue owner/design/plan/ship use Opus/high, standards review uses reviewer Opus/high, and bounded fact lookup uses explorer Haiku/medium or mechanic Sonnet/medium according to whether it mutates state. Assert cheap-tier escalation prose names the selected Opus role and ledger/report destination.

- [ ] **Step 2: Run and observe the missing-site failures**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: FAIL listing owner/design dispatch IDs absent from the matrix and Markdown markers.

- [ ] **Step 3: Add exact selections at every owner dispatch**

Extend `dispatch_sites`, place one exact marker immediately before each call instruction, and rewrite ambient phrases such as “model inherited” or bare `general-purpose` to explicit Opus/high selections. Bounded read-only facts select explorer Haiku/medium; any stateful inventory selects mechanic Sonnet/medium. Require the existing ledger/fixed report to record escalation to Opus.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: PASS; all declared owner/design sites appear once and no inherited-model wording remains in those files.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json home/common/agent-skills/tests/test_agent_model_matrix.py home/common/claude-code/skills/orchestrate-issues/SKILL.md home/common/agent-skills/skills/{from-issue,design,grill-with-docs,writing-plans,doc-grounded-questions}
git commit -m "fix(agents): pin issue-owner dispatch tiers (#15)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: Reviewer-lite and explicit SDD dispatches

**Files:**
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/implementer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/task-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/re-review-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/conformance-reviewer-prompt.md`
- Modify: `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md`

**Interfaces:**
- Consumes: `reviewer-lite` agent contract and Task 1 marker validation.
- Produces: explicit SDD site IDs for mechanic/implementer, first-pass reviewer, scoped reviewer-lite, final conformance reviewer, native correctness reviewer, Codex transport, and full-review fallback.

- [ ] **Step 1: Add failing SDD matrix assertions**

Require every SDD dispatch site to select an exact role/model/effort. Assert first-pass task and both whole-branch axes are reviewer Opus/high, scoped named-finding re-review is reviewer-lite Sonnet/medium, non-mechanical work is implementer Opus/high, deterministic work is mechanic Sonnet/medium, and the bridge call is codex-transport Sonnet/medium. Add a negative fixture that marks reviewer-lite as first-pass and expect validation failure.

- [ ] **Step 2: Run and observe the current shared-reviewer failure**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: FAIL because current SDD prose routes scoped re-reviews through the same unpinned reviewer role as first-pass review.

- [ ] **Step 3: Implement SDD selections and eligibility guard**

Add exact markers and explicit selections to the SDD controller and prompt headers. Change only the scoped re-review call/template to reviewer-lite. Preserve existing review rubrics, fix-round limits, two-axis independence, and external Codex reviewer semantics. State that ambiguous or branch-wide findings escape reviewer-lite to reviewer Opus/high and record that escalation in the SDD ledger.

- [ ] **Step 4: Verify**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/tests/test_workflow_skill_contracts.py`

Expected: PASS; the negative first-pass reviewer-lite fixture is rejected and every SDD site matches the matrix.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/skills/sdd
git commit -m "feat(agents): route scoped re-reviews to reviewer-lite (#15)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: Shipping selections, representative traces, and integrated gates

**Files:**
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Modify: `home/common/claude-code/skills/codex-collaboration/SKILL.md`
- Modify: `justfile`

**Interfaces:**
- Consumes: complete matrix, marker validator, and trace CLI.
- Produces: explicit ship-owner/reviewer/Codex-transport selections; scenarios `orchestration`, `from-issue`, `sdd`, `shipping`, and `representative`; `just agent-model-matrix` verification/demo entry.

- [ ] **Step 1: Add failing shipping and trace assertions**

Require ship ownership Opus/high, merge-delta and first-pass PR/final reviews reviewer Opus/high, scoped fix re-review reviewer-lite Sonnet/medium, and Codex bridge transport Sonnet/medium. Assert `trace representative` emits events for all four workflow families, contains reviewer-lite only after a named full-review finding, and contains no `inherit`, null model, or null effort.

- [ ] **Step 2: Run and observe missing shipping/trace failures**

Run: `python3 -m unittest -v home/common/agent-skills/tests/test_agent_model_matrix.py`

Expected: FAIL listing missing shipping selections/scenarios or an incomplete representative trace.

- [ ] **Step 3: Complete shipping mappings and runnable demo**

Add markers and explicit selections without altering phase order, review axes, CI watch, merge, issue close, or cleanup. Populate deterministic scenario events from dispatch IDs, have `trace representative` output JSONL including `workflow`, `dispatch`, `role`, `model`, and `effort`, and add a just target that runs validation then prints the trace.

- [ ] **Step 4: Verify unit contracts, trace, formatting, and build**

Run: `python3 -m unittest discover -s home/common/agent-skills/tests -v`

Expected: PASS, including the original 35 workflow lifecycle/skill tests and all new matrix tests.

Run: `python3 home/common/agent-skills/scripts/agent-model-matrix.py validate && python3 home/common/agent-skills/scripts/agent-model-matrix.py trace representative`

Expected: validation exits 0; every JSONL event has explicit role/model/effort, reviewer-lite appears only at scoped re-review events, and full reviews are Opus/high.

Run: `git diff --check origin/main...HEAD`

Expected: no whitespace errors.

Run: `nix build .#darwinConfigurations.anis-mbp.system`

Expected: exit 0 and the Home Manager generation includes the matrix CLI and four agent definitions.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/model-matrix.json home/common/agent-skills/tests/test_agent_model_matrix.py home/common/agent-skills/skills/{ship-issue,ship-release} home/common/claude-code/skills/codex-collaboration/SKILL.md justfile
git commit -m "test(agents): gate the issue-workflow model matrix (#15)" -m "Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
