# Improve Codebase Architecture Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship the explicit-only `improve-codebase-architecture` workflow as an attributed shared skill, with one registered Opus/high scan dispatch, deterministic matrix coverage, and three deployed pipeline evals.

**Architecture:** A five-file skill package owns the runtime workflow, lazy report guidance, Codex metadata, provenance, and deployed eval manifest. The existing model matrix owns the single scan dispatch and standalone trace, while the existing workflow and matrix test modules retain their separate contract ownership; automatic directory discovery distributes the package without Nix registration changes.

**Tech stack:** Markdown skill instructions, YAML Codex metadata, strict JSON manifests, Python 3 standard-library `unittest`, Bash eval assertions, Nix/Home Manager verification.

## Global Constraints

- Create exactly `SKILL.md`, `HTML-REPORT.md`, `LICENSE`, `agents/openai.yaml`, and `evals/evals.json` under `home/common/agent-skills/skills/improve-codebase-architecture/` per D1.
- Preserve upstream revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected 2026-08-17: unchanged frontmatter and Codex manifest, preserved process shape/report patterns/editorial voice, and all nine adaptations enumerated before the unmodified MIT notice per D2 and D8.
- Keep the workflow explicit-only through `disable-model-invocation: true` and `policy.allow_implicit_invocation: false`; do not invent a default-prompt manifest key per D2.
- Register exactly one `improve-architecture-scan-owner` site at `issue-owner` / `opus` / `high` with `subagent_type="general-purpose"`, `requires: []`, and one standalone `improve-codebase-architecture` scenario per D5.
- Keep the existing four-family `representative` scenario byte-for-byte unchanged; change no role tier, eligibility rule, or existing scenario per D5.
- Discovery writes nothing to the target repository, may write at most one findings artifact beneath the OS temporary directory, and renders zero to five evidence-backed candidates without padding; a zero-candidate report succeeds per D13.
- Route fog to `wayfind`; otherwise establish an isolated worktree before `design`, then invoke `grill-with-docs`, recommend `writing-plans` or `to-issues`, and stop without planning or execution per D9.
- Treat `grilling` and `domain-modeling` only as names in `LICENSE`'s provenance comparison; they never appear as active guidance in `SKILL.md` or `HTML-REPORT.md` per D14.
- Do not edit any `.nix` file, `flake.nix`, `justfile`, `home/common/agent-skills/README.md`, or anything under `home/common/agent-skills/skills/codebase-design/`; do not add CDN assets, upstream inputs, synchronization, or runtime/build-time skill fetching.
- Leave `.claude/specs/2026-08-17-improve-codebase-architecture-design.md` byte-identical to committed parent decision D4.
- Do not implement an architecture candidate, automatically run this skill, activate Home Manager, or claim deployed-behavior certification; author the eval cases now and exercise them only after a human `just switch` per D12.
- Every implementation commit uses configured signing and includes `Co-Authored-By: Codex <noreply@openai.com>`.
- Use targeted searches, bounded reads, concise test output, and artifact paths instead of pasted logs.

## Test seams

- **Shared deployment seam:** `just build`, then build the configured `darwinConfigurations.mbp.config.home-manager.users.<username>.home-files` tree and assert that both agent surfaces expose all five files.
- **Workflow-contract seam:** `ImproveCodebaseArchitectureSkillContractsTest` pins package/runtime behavior, while `AgentModelMatrixTest` and `agent-model-matrix.py` pin the closed workflow family, exact dispatch, standalone scenario, direct trace, and unchanged representative trace per D6 and D7.
- **Deployed-behavior seam:** three `pipeline` entries grade scan-only reporting, concrete-selection routing, and fog routing against TinyTask; author and statically validate them, but do not execute them before activation per D12.

## Task index

Task 1 — Author and register the architecture workflow — `home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md`, `home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md`, `home/common/agent-skills/skills/improve-codebase-architecture/LICENSE`, `home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml`, `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/scripts/agent-model-matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full

Task 2 — Add deployed workflow evals and certify authored integration — `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full

## Decisions

The issue spec owns D1–D14. This plan cites those rows and introduces no second decision ledger.

---

### Task 1: Author and register the architecture workflow

**Files:**
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/LICENSE`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml`
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/scripts/agent-model-matrix.py`
- Modify: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `codebase-design`; local workflows `doc-grounded-questions`, `worktrees`, `design`, `grill-with-docs`, `wayfind`, `writing-plans`, and `to-issues`; the matrix's `dispatch_sites` and `scenarios`; upstream files at the pinned revision.
- Produces: explicit skill `$improve-codebase-architecture`; dispatch id `improve-architecture-scan-owner`; workflow family/scenario `improve-codebase-architecture`; a one-event trace with public fields `workflow`, `dispatch`, `role`, `model`, and `effort`.

**Invariants:**
- `SKILL.md` is the only always-loaded runtime body; `HTML-REPORT.md` is linked and loaded only while rendering per D1.
- The marker occurs once and its exact `Agent(...)` call is the immediately following line; no other package line contains `Agent(` per D5.
- A named scope bypasses history. An unnamed scope reads `git log --oneline --no-merges -50`, follows the strongest concentration, and widens only when history is scattered or has no meaningful concentration.
- Every candidate establishes the seven evidence items before rendering: module/callers, caller-owned interface knowledge, lost locality or leverage, deletion-test result, dependency category and two-adapter justification, existing/proposed interface-level tests, and decision conflicts.
- The fresh scan owner returns findings; the calling agent renders the report. Discovery is read-only, selection is the first possible mutation point, and the skill names no caller.
- The report always prints an absolute temporary path. Generation failure fails; browser-open and CDN failures are disclosed warnings. Zero candidates remains a successful truthful report.
- `HTML-REPORT.md` preserves all five upstream diagram patterns and adds semantic heading order, adjacent text equivalents, non-color meaning, readable inline fallback styles, 4.5:1 normal-text contrast, and narrow-width reflow without duplicate or clipped content.
- Only the new workflow family, final dispatch row, and standalone scenario change the matrix; `representative` remains unchanged per D5.

- [ ] **Step 1: Write the failing package contract**

Append one contiguous block before the module's final `unittest.main()` guard in `test_workflow_skill_contracts.py`. Reuse `skill_frontmatter` and `relative_markdown_links`.

```python
# --- improve-codebase-architecture workflow package (issue 43) --------------
IMPROVE_ARCHITECTURE_DIR = (
    REPO_ROOT / "home/common/agent-skills/skills/improve-codebase-architecture"
)
IMPROVE_ARCHITECTURE_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
IMPROVE_ARCHITECTURE_UPSTREAM = "https://github.com/mattpocock/skills"
IMPROVE_ARCHITECTURE_FILES = (
    "SKILL.md", "HTML-REPORT.md", "LICENSE", "agents/openai.yaml"
)
IMPROVE_ARCHITECTURE_MARKER = (
    "<!-- agent-dispatch: id=improve-architecture-scan-owner "
    "role=issue-owner model=opus effort=high -->"
)
IMPROVE_ARCHITECTURE_CALL = (
    'Agent(subagent_type="general-purpose", model="opus", effort="high") '
    "performs the one read-only architecture scan and returns evidence-backed "
    "deepening candidates without writing to the repository."
)


class ImproveCodebaseArchitectureSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (IMPROVE_ARCHITECTURE_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.report = (IMPROVE_ARCHITECTURE_DIR / "HTML-REPORT.md").read_text(encoding="utf-8")
        cls.notice = (IMPROVE_ARCHITECTURE_DIR / "LICENSE").read_text(encoding="utf-8")
        cls.manifest = (IMPROVE_ARCHITECTURE_DIR / "agents/openai.yaml").read_text(encoding="utf-8")

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            found = text.find(anchor, position + 1)
            self.assertNotEqual(found, -1, f"missing anchor: {anchor!r}")
            self.assertGreater(found, position, f"out-of-order: {anchor!r}")
            position = found

    def test_package_structure_links_and_explicit_only_metadata(self):
        for relative in IMPROVE_ARCHITECTURE_FILES:
            self.assertTrue((IMPROVE_ARCHITECTURE_DIR / relative).is_file(), relative)
        self.assertEqual(
            skill_frontmatter(self.skill),
            {
                "name": "improve-codebase-architecture",
                "description": "Scan a codebase for deepening opportunities, present "
                "them as a visual HTML report, then grill through whichever one you pick.",
                "disable-model-invocation": "true",
            },
        )
        self.assertEqual(
            self.manifest,
            'interface:\n  display_name: "Improve Codebase Architecture"\n'
            '  short_description: "Find and grill architecture improvements"\n'
            'policy:\n  allow_implicit_invocation: false\n',
        )
        root = IMPROVE_ARCHITECTURE_DIR.resolve()
        checked = 0
        for name, text in {"SKILL.md": self.skill, "HTML-REPORT.md": self.report}.items():
            for target in relative_markdown_links(text):
                checked += 1
                resolved = (root / name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(root), (name, target))
                self.assertTrue(resolved.is_file(), (name, target))
        self.assertGreaterEqual(checked, 2)

    def test_process_dependencies_scope_and_dispatch_are_native(self):
        self.assert_ordered(self.skill, "### 1. Explore", "### 2. Present", "### 3.")
        for dependency in (
            "codebase-design", "doc-grounded-questions", "worktrees", "design",
            "grill-with-docs", "wayfind", "writing-plans", "to-issues",
        ):
            self.assertIn(f"`{dependency}`", self.skill)
            self.assertTrue(
                (REPO_ROOT / "home/common/agent-skills/skills" / dependency).is_dir(),
                dependency,
            )
        self.assertNotIn("`grilling`", self.skill + self.report)
        self.assertNotIn("`domain-modeling`", self.skill + self.report)
        for fragment in (
            "bypasses inference", "git log --oneline --no-merges -50",
            "scattered", "History selects where to look",
        ):
            self.assertIn(fragment, self.skill)
        lines = self.skill.splitlines()
        self.assertEqual([line for line in lines if "Agent(" in line], [IMPROVE_ARCHITECTURE_CALL])
        self.assertEqual(lines.count(IMPROVE_ARCHITECTURE_MARKER), 1)
        self.assertEqual(lines.index(IMPROVE_ARCHITECTURE_CALL), lines.index(IMPROVE_ARCHITECTURE_MARKER) + 1)

    def test_candidate_report_and_routing_contracts(self):
        for fragment in (
            "writes nothing to the repository", "at most one structured findings artifact",
            "deletion test", "dependency category", "two adapters", "interface-level test",
            "before/after", "zero to five", "Never pad", "successful run", "Strong",
            "Worth exploring", "Speculative", "Top recommendation",
            "architecture-review-<timestamp>.html", "absolute path",
            "generation failure", "browser", "CDN",
        ):
            self.assertIn(fragment, self.skill)
        for fragment in (
            "semantic headings", "text equivalent", "colour is never the sole", "4.5:1",
            "phone width", "without duplicating content", "Mermaid graph",
            "Hand-built boxes-and-arrows", "Cross-section", "Mass diagram",
            "Call-graph collapse",
        ):
            self.assertIn(fragment, self.report)
        self.assert_ordered(
            self.skill, "`wayfind`", "`worktrees`", "`design`",
            "`grill-with-docs`", "`writing-plans`",
        )
        self.assertIn("Do not invoke", self.skill)

    def test_dispatch_registration_and_standalone_scenario(self):
        data = json.loads((REPO_ROOT / "home/common/agent-skills/model-matrix.json").read_text())
        site = {item["id"]: item for item in data["dispatch_sites"]}[
            "improve-architecture-scan-owner"
        ]
        self.assertEqual(
            (site["path"], site["marker"], site["call"], site["role"],
             site["model"], site["effort"], site["requires"]),
            ("home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md",
             IMPROVE_ARCHITECTURE_MARKER, IMPROVE_ARCHITECTURE_CALL,
             "issue-owner", "opus", "high", []),
        )
        self.assertEqual(
            data["scenarios"]["improve-codebase-architecture"],
            [{"workflow": "improve-codebase-architecture",
              "dispatch": "improve-architecture-scan-owner", "role": "issue-owner",
              "model": "opus", "effort": "high", "requires": []}],
        )

    def test_provenance_records_every_adaptation_and_notice(self):
        for fragment in (
            IMPROVE_ARCHITECTURE_UPSTREAM, "skills/engineering/improve-codebase-architecture/",
            IMPROVE_ARCHITECTURE_REVISION, "2026-08-17", "Vocabulary invocation",
            "Domain grounding repointed", "Hotspot rule made concrete", "registered dispatch",
            "Candidate contract stated", "Report contract extended", "Downstream step replaced",
            "Provenance pointer", "Package extensions", "Copyright (c) 2026 Matt Pocock",
            "Permission is hereby granted, free of charge",
        ):
            self.assertIn(fragment, self.notice)
        self.assertIn("[LICENSE](LICENSE)", self.skill)
        self.assertNotIn("Permission is hereby granted", self.skill)
```

- [ ] **Step 2: Write the failing matrix contract**

Add these constants near the existing expected-site constants and add the indented method inside `AgentModelMatrixTest` in `test_agent_model_matrix.py`:

```python
IMPROVE_ARCHITECTURE_SITE = {
    "id": "improve-architecture-scan-owner",
    "path": "home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md",
    "marker": "<!-- agent-dispatch: id=improve-architecture-scan-owner "
    "role=issue-owner model=opus effort=high -->",
    "call": 'Agent(subagent_type="general-purpose", model="opus", effort="high") '
    "performs the one read-only architecture scan and returns evidence-backed "
    "deepening candidates without writing to the repository.",
    "role": "issue-owner", "model": "opus", "effort": "high", "requires": [],
}
IMPROVE_ARCHITECTURE_EVENT = {
    "workflow": "improve-codebase-architecture",
    "dispatch": "improve-architecture-scan-owner",
    "role": "issue-owner", "model": "opus", "effort": "high", "requires": [],
}


    def test_improve_codebase_architecture_trace_is_standalone(self):
        module = load_module()
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        self.assertIn("improve-codebase-architecture", module.WORKFLOW_FAMILIES)
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(
            sites["improve-architecture-scan-owner"], IMPROVE_ARCHITECTURE_SITE
        )
        self.assertEqual(
            data["scenarios"]["improve-codebase-architecture"],
            [IMPROVE_ARCHITECTURE_EVENT],
        )
        self.assertEqual(
            module.trace(REPO_ROOT, "improve-codebase-architecture"),
            [
                {
                    key: IMPROVE_ARCHITECTURE_EVENT[key]
                    for key in ("workflow", "dispatch", "role", "model", "effort")
                }
            ],
        )
        self.assertEqual(
            {
                event["workflow"]
                for event in module.trace(REPO_ROOT, "representative")
            },
            {"orchestration", "from-issue", "sdd", "shipping"},
        )
```

- [ ] **Step 3: Run both contracts against the starting subjects**

Run:

```bash
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_improve_codebase_architecture_trace_is_standalone
```

Expected: non-zero. The package class errors because `SKILL.md` is absent, and the matrix test fails first because the starting `WORKFLOW_FAMILIES` lacks `improve-codebase-architecture`. This is the required base falsification; the historical `just agent-model-matrix` remains green because its old closed set is internally consistent per D6.

- [ ] **Step 4: Author the runtime package and registration**

- Use the pinned upstream `SKILL.md`, `HTML-REPORT.md`, and `agents/openai.yaml` as one-time authoring sources, never as generated inputs.
- Preserve the exact frontmatter, three-step shape, report patterns, voice, glossary substitutions, and manifest. In `SKILL.md`, invoke `codebase-design` and `doc-grounded-questions`; implement the exact scope rule; place the exact marker/call on adjacent lines; state the seven-item evidence bar, read-only/temp-only behavior, and disclosed inline fallback without another `Agent(` token.
- Render every evidence-clearing candidate up to five. State zero/one/five validity, no padding, successful zero-candidate output, all strength labels, and a top recommendation only when a candidate exists.
- Resolve `$TMPDIR`, `/tmp`, or `%TEMP%`; create `architecture-review-<timestamp>.html`; always print its absolute path. Fail report generation; warn on browser/CDN failures. Do not propose an interface before selection.
- Route fog to `wayfind` and return without a worktree or automatic resumption. For a concrete pick, reuse only an isolated linked worktree or invoke `worktrees` from the configured remote integration ref, then `design`, approved `grill-with-docs`, and a recommendation of `writing-plans` or `to-issues`; invoke neither and execute nothing. Preserve upstream's one load-bearing-rejection ADR-offer rule while delegating all actual domain/ADR writes to `grill-with-docs`.
- Extend `HTML-REPORT.md` with every tested accessibility/fallback property, without bundled assets or application JavaScript.
- Follow `codebase-design/LICENSE`'s provenance shape and record all nine named departures before the unmodified MIT notice. D14 permits removed upstream skill names only in this comparison; close `SKILL.md` with the one-line `[LICENSE](LICENSE)` provenance pointer.
- Append `IMPROVE_ARCHITECTURE_SITE` as the final `dispatch_sites` row; add `improve-codebase-architecture` to `WORKFLOW_FAMILIES`; add exactly `[IMPROVE_ARCHITECTURE_EVENT]` as its scenario. Do not touch `representative` or any existing selection.

- [ ] **Step 5: Verify green and commit**

Run:

```bash
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_improve_codebase_architecture_trace_is_standalone \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_repository_contract_validates
python3 home/common/agent-skills/scripts/agent-model-matrix.py validate
python3 home/common/agent-skills/scripts/agent-model-matrix.py trace improve-codebase-architecture
just agent-workflow-tests
just agent-model-matrix
git diff --check -- \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
```

Expected: all tests and validators pass; `validate` says `model matrix valid`; the direct trace is one issue-owner/opus/high event; the representative trace still contains only its existing four families; the owned diff has no whitespace errors.

```bash
git add \
  home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md \
  home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md \
  home/common/agent-skills/skills/improve-codebase-architecture/LICENSE \
  home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -S -m "feat(agent-skills): add architecture improvement workflow (#43)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```

### Task 2: Add deployed workflow evals and certify authored integration

**Files:**
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: `run-eval.sh`'s `pipeline` schema; variables `OUT`, `REPO`, `WT`, `WT_COUNT`, `SPEC_DIR`, `PLAN_DIR`; helpers `fail`, `out_matches`, `has_file`, `commits_touch`, and `path_unchanged_since`.
- Produces: eval ids 1–3 named `scan-only-renders-a-temporary-report`, `clear-selection-reaches-a-design-worktree`, and `foggy-selection-routes-to-wayfind`, all `pipeline` and without `expected_today`.

**Invariants:**
- Eval 1 leaves the fixture clean at `origin/main`, creates no branch/worktree, discloses the no-hotspot widen path, and proves an absolute temporary report exists with candidate evidence/top recommendation or a truthful no-candidate message.
- Eval 2 selects a concrete `tinytask.store` opportunity, reaches exactly one isolated worktree and committed design spec, names `grill-with-docs`, changes neither `tinytask/` nor `tests/`, creates no plan, recommends a scope workflow, and invokes neither.
- Eval 3 gives the unstatable cross-machine-sync destination, creates a new `.claude/wayfind/<effort>/` beside unchanged `concurrent-shells`, creates no worktree or spec, and names `wayfind`.

- [ ] **Step 1: Write the failing eval-manifest contract**

Append `"evals/evals.json"` to `IMPROVE_ARCHITECTURE_FILES`, load it in `setUpClass`, and add this method:

```python
    def test_deployed_eval_manifest_has_the_three_pipeline_routes(self):
        self.assertEqual(self.evals["skill_name"], "improve-codebase-architecture")
        cases = {case["id"]: case for case in self.evals["evals"]}
        self.assertEqual(
            {case_id: (case["name"], case["mode"]) for case_id, case in cases.items()},
            {
                1: ("scan-only-renders-a-temporary-report", "pipeline"),
                2: ("clear-selection-reaches-a-design-worktree", "pipeline"),
                3: ("foggy-selection-routes-to-wayfind", "pipeline"),
            },
        )
        required = {
            1: ("architecture-review-", '[ -f "$report" ]', "widen",
                "top recommendation", "WT_COUNT", "status --porcelain", "origin/main"),
            2: ("tinytask.store", "WT_COUNT", "path_unchanged_since", "tinytask tests",
                "$SPEC_DIR", "$PLAN_DIR", "grill-with-docs", "writing-plans|to-issues"),
            3: ("sync between machines", ".claude/wayfind/concurrent-shells",
                "WT_COUNT", "$SPEC_DIR", "wayfind"),
        }
        for case_id, case in cases.items():
            self.assertNotIn("expected_today", case)
            self.assertIn("/improve-codebase-architecture", case["prompt"])
            self.assertTrue(case["expected_output"].strip())
            self.assertTrue(case["asserts"])
            contract = case["prompt"] + "\n" + "\n".join(
                item["name"] + "\n" + item["shell"] for item in case["asserts"]
            )
            for fragment in required[case_id]:
                self.assertIn(fragment, contract)
```

Add this assignment in `setUpClass`:

```python
        cls.evals = json.loads(
            (IMPROVE_ARCHITECTURE_DIR / "evals/evals.json").read_text(encoding="utf-8")
        )
```

- [ ] **Step 2: Run the contract before creating the manifest**

Run:

```bash
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest
```

Expected: non-zero with `FileNotFoundError` for `evals/evals.json`; Task 1's runtime and matrix assertions remain green.

- [ ] **Step 3: Author the three pipeline entries**

Create strict JSON with `skill_name`, concise deployed-generation notes, and exactly three evals:

- Eval 1 explicitly invokes an unscoped scan and stops after reporting. Its assertions extract the first absolute `/.../architecture-review-*.html` from `OUT`, require it outside `REPO` and present on disk, accept either before/after plus top-recommendation HTML or a truthful no-candidate statement, require no-hotspot and widen output, `WT_COUNT == 0`, clean status, `HEAD == origin/main`, and only local branch `main`.
- Eval 2 explicitly invokes the skill for `tinytask.store`, selects the Store deepening opportunity up front, approves autonomous routing through design/domain review, and forbids implementation/planning. Require exactly one `WT`, a committed spec under `$WT/$SPEC_DIR`, `path_unchanged_since` for `tinytask tests` in checkout and worktree, no file under either `$PLAN_DIR`, output naming `grill-with-docs`, and output matching `writing-plans|to-issues` as a recommendation.
- Eval 3 explicitly invokes the skill with the documented `sync between machines` fog and requests the fog gate. Require one new directory under `$REPO/.claude/wayfind` other than `concurrent-shells`, `path_unchanged_since "$REPO" origin/main .claude/wayfind/concurrent-shells`, `WT_COUNT == 0`, no file under `$REPO/$SPEC_DIR`, and output naming `wayfind`.

Every assertion has a unique name and one falsifiable shell snippet. Use only existing harness variables/helpers; do not edit the harness, fixture, or assertion library.

- [ ] **Step 4: Verify static contracts, workflow gates, and unactivated deployment**

Run:

```bash
python3 -m json.tool \
  home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json >/dev/null
jq -e '.skill_name == "improve-codebase-architecture" and
  ([.evals[].id] == [1, 2, 3]) and
  ([.evals[].mode] | all(. == "pipeline")) and
  ([.evals[] | has("expected_today")] | all(. == false))' \
  home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json >/dev/null
just agent-workflow-tests
just agent-model-matrix
python3 home/common/agent-skills/scripts/agent-model-matrix.py \
  trace improve-codebase-architecture
just build
configured_user=$(nix eval --raw --file vars/default.nix username)
home_tree=$(nix build \
  ".#darwinConfigurations.mbp.config.home-manager.users.${configured_user}.home-files" \
  --no-link --print-out-paths)
test -L "$home_tree/.agents/skills/improve-codebase-architecture"
test -d "$home_tree/.claude/skills/improve-codebase-architecture"
for relative in SKILL.md HTML-REPORT.md LICENSE agents/openai.yaml evals/evals.json
do
  test -e "$home_tree/.agents/skills/improve-codebase-architecture/$relative"
  test -e "$home_tree/.claude/skills/improve-codebase-architecture/$relative"
done
```

Expected: JSON checks, all 212 baseline tests plus new tests, both matrix commands, and both Nix builds pass; the trace remains one issue-owner/opus/high event; the Codex surface is a directory symlink, the Claude surface a real directory, and all five files resolve. Do not run the pipeline evals until a human activates the generation.

- [ ] **Step 5: Run owned-scope gates and commit**

Run:

```bash
git diff --check f471376 -- \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git diff --stat f471376 -- \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git diff --quiet f471376 -- \
  '*.nix' flake.nix justfile \
  home/common/agent-skills/README.md \
  home/common/agent-skills/skills/codebase-design
```

Expected: no whitespace errors; the scoped stat contains only the five-file package and four shared workflow files; the forbidden-path diff exits 0. Spec and plan artifact commits are outside these product pathspecs.

```bash
git add \
  home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -S -m "test(agent-skills): add architecture workflow evals (#43)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
