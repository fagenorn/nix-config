# Improve Codebase Architecture Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship the explicit-only `improve-codebase-architecture` workflow as an attributed shared skill, with one registered Opus/high scan dispatch, deterministic contracts, and three deployed pipeline evals.

**Architecture:** One atomic full-risk task creates the complete five-file package and changes the four existing workflow/matrix files that register and verify it. The loaded skill owns discovery and routing, the lazy reference owns report rendering guidance, the model matrix owns dispatch selection, and the existing test modules retain package/eval versus matrix ownership.

**Tech stack:** Markdown, YAML, strict JSON, Python 3 standard-library `unittest`, Bash eval assertions, Nix/Home Manager verification.

## Global Constraints

- Create exactly `SKILL.md`, `HTML-REPORT.md`, `LICENSE`, `agents/openai.yaml`, and `evals/evals.json` under `home/common/agent-skills/skills/improve-codebase-architecture/` per D1.
- Preserve upstream revision `9c9f36ccd3995266cd675468af71639c8dde1ec5`, inspected 2026-08-17: unchanged frontmatter and Codex manifest, preserved process/report shape and voice, and exactly nine ordered adaptations before the exact upstream MIT notice per D2, D8, and D15.
- Permit only the one-time immutable authoring-source fetch in this plan per D17. No fetched file becomes a repository input, generated source, build/runtime fetch, flake input, or synchronization mechanism.
- Keep explicit-only controls `disable-model-invocation: true` and `policy.allow_implicit_invocation: false`; do not invent a default-prompt manifest key per D2.
- Register exactly one `improve-architecture-scan-owner` dispatch at `issue-owner` / `opus` / `high`, `subagent_type="general-purpose"`, `requires: []`, plus one standalone `improve-codebase-architecture` scenario per D5.
- Keep the existing four-family `representative` scenario byte-for-byte unchanged; rename only its stale test method per S2.
- Discovery is repository-read-only, may write at most one findings artifact under the OS temporary directory, and renders zero to five evidence-backed candidates without padding; a zero-candidate report succeeds per D13.
- Route fog to `wayfind` and stop; otherwise establish an isolated worktree before `design`, then invoke `grill-with-docs`, recommend `writing-plans` or `to-issues`, and stop without planning, issue creation, or execution per D9, D16, and D19.
- `grilling` and `domain-modeling` occur only in `LICENSE`'s provenance comparison, never as active guidance, per D14.
- Do not edit `.nix` files, `flake.nix`, `justfile`, `home/common/agent-skills/README.md`, `codebase-design`, either accepted parent design, the eval harness, or the TinyTask fixture.
- Do not implement a candidate, automatically invoke this skill, activate Home Manager, run the deployed evals before activation, or claim deployed-behavior certification.
- The single implementation commit remains signed and includes `Co-Authored-By: Codex <noreply@openai.com>`.
- Use targeted reads, concise output, and paths rather than pasted artifacts.

## Test seams

- **Shared deployment seam:** build without activation, then assert both generated agent surfaces expose all five files.
- **Workflow-contract seam:** one appended `ImproveCodebaseArchitectureSkillContractsTest` pins package, report, provenance, routing, and eval contracts; `AgentModelMatrixTest` plus the validator pin the closed family, exact dispatch, standalone trace, and unchanged issue-delivery trace per D6, D7, D15, and D18.
- **Deployed-behavior seam:** three authored `pipeline` cases grade scan-only, clear-selection, and fog-selection behavior after a later human activation per D12, D16, and D19.

## Task index

Task 1 — Ship the complete architecture-improvement workflow — `home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md`, `home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md`, `home/common/agent-skills/skills/improve-codebase-architecture/LICENSE`, `home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml`, `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`, `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/scripts/agent-model-matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full

## Decisions

The issue spec owns D1–D19. This plan cites those rows and introduces no second ledger.

## Standards review

- Reviewer: `/root/issue43_plan_review`
- Report: `/private/tmp/issue43-plan-review.md`
- Reviewed HEAD: `455f6b6a2e7374902786cf938b586bc5752e8b0c`
- Base SHA: `2efb92d6ff600b92eb3c1ed35850141b21d8b85a`
- Reviewer path: native reviewer
- Fallback: `false`
- Findings: 3 Blocking, 4 Should-fix, 0 Discussion; all actionable findings applied.
- B1 → D15: static contracts now pin all seven evidence items, the report scaffold/CDNs/accessibility behavior, and exact ordered provenance.
- B2 → D16: fog eval now proves no plan/source/issue continuation and requires terminal stop output.
- B3 → D17: exact immutable authoring URLs and an effective-URL verification command are included.
- S1 → D18: eval assertions have unique names and each named shell is inspected independently.
- S2: rename the stale representative-trace test without changing its scenario.
- S3: replace the two-task/four-file intermediate state with one complete five-file task and one commit.
- S4 → D19: clear-route autonomy is bounded to reversible in-scope recommendations and stops on reserved questions.

---

### Task 1: Ship the complete architecture-improvement workflow

**Files:**
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/LICENSE`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml`
- Create: `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`
- Modify: `home/common/agent-skills/model-matrix.json`
- Modify: `home/common/agent-skills/scripts/agent-model-matrix.py`
- Modify: `home/common/agent-skills/tests/test_agent_model_matrix.py`
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

**Interfaces:**
- Consumes: immutable upstream sources listed in Step 1; `codebase-design`; `doc-grounded-questions`, `worktrees`, `design`, `grill-with-docs`, `wayfind`, `writing-plans`, `to-issues`; matrix `dispatch_sites`/`scenarios`; eval variables `OUT`, `REPO`, `WT`, `WT_COUNT`, `SPEC_DIR`, `PLAN_DIR` and existing assertion helpers.
- Produces: explicit skill `$improve-codebase-architecture`; dispatch `improve-architecture-scan-owner`; workflow/scenario `improve-codebase-architecture`; eval ids 1–3; one complete signed implementation commit.

**Invariants:**
- `SKILL.md` alone is always loaded; `HTML-REPORT.md` is loaded only when rendering per D1.
- The exact marker occurs once and its exact `Agent(...)` call is the next line; no other package line contains `Agent(`.
- Named scope bypasses inference. Unscoped discovery runs `git log --oneline --no-merges -50`, follows the strongest concentration, and widens only for scattered/no concentration; history is never change evidence.
- The fresh scan owner establishes all seven evidence items in their accepted order and returns findings; the caller renders. Selection is the first possible repository mutation.
- Report generation fails the run; browser/CDN failures warn; an absolute temporary path is always printed. Zero candidates succeeds truthfully.
- Fog returns after `wayfind` with no automatic resumption. Concrete selection uses an isolated worktree, `design`, approved `grill-with-docs`, then recommends a scope workflow and stops.
- Eval 2's one-shot autonomy answers only reversible in-scope recommendations. Scope-redrawing, hard-to-reverse, credential, spending, or unanswerable questions stop.
- Eval 3 proves map creation and the absence of worktree, spec, plan, source/test mutation, and continuation into issues/planning/execution. Under tracker `kind:none`, no canonical issue artifact exists; stop-semantic output is the issue-creation observable per D16.

- [ ] **Step 1: Fetch the four immutable authoring sources to a temporary directory**

Exact revision and URLs:

- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/SKILL.md`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/HTML-REPORT.md`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/agents/openai.yaml`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/LICENSE`

Run this reproducible authoring-only fetch, or use a web connector that returns and verifies the same four requested URLs:

```bash
set -euo pipefail
upstream_revision=9c9f36ccd3995266cd675468af71639c8dde1ec5
upstream_root="https://raw.githubusercontent.com/mattpocock/skills/$upstream_revision"
authoring_dir=$(mktemp -d "${TMPDIR:-/tmp}/improve-architecture-upstream.XXXXXX")
fetch_exact() {
  local relative=$1 destination=$2 expected effective
  expected="$upstream_root/$relative"
  effective=$(curl --fail --location --silent --show-error \
    --output "$destination" --write-out '%{url_effective}' "$expected")
  test "$effective" = "$expected"
  test -s "$destination"
}
fetch_exact skills/engineering/improve-codebase-architecture/SKILL.md "$authoring_dir/SKILL.md"
fetch_exact skills/engineering/improve-codebase-architecture/HTML-REPORT.md "$authoring_dir/HTML-REPORT.md"
fetch_exact skills/engineering/improve-codebase-architecture/agents/openai.yaml "$authoring_dir/openai.yaml"
fetch_exact LICENSE "$authoring_dir/LICENSE"
test "$upstream_revision" = 9c9f36ccd3995266cd675468af71639c8dde1ec5
```

Expected: every effective URL equals its commit-addressed requested URL and all four temporary files are non-empty. Nothing under the repository changes; `/private/tmp` is not an input. These files are manual implementation-time references only per D17.

- [ ] **Step 2: Write the complete failing package/eval contract**

Add `import re`, then append one contiguous block before the final `unittest.main()` guard in `test_workflow_skill_contracts.py`, reusing `skill_frontmatter` and `relative_markdown_links`. The full test contract is:

```python
IMPROVE_DIR = REPO_ROOT / "home/common/agent-skills/skills/improve-codebase-architecture"
IMPROVE_REVISION = "9c9f36ccd3995266cd675468af71639c8dde1ec5"
IMPROVE_FILES = ("SKILL.md", "HTML-REPORT.md", "LICENSE", "agents/openai.yaml", "evals/evals.json")
IMPROVE_MARKER = "<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->"
IMPROVE_CALL = ('Agent(subagent_type="general-purpose", model="opus", effort="high") '
                "performs the one read-only architecture scan and returns evidence-backed "
                "deepening candidates without writing to the repository.")
MIT_NOTICE = '''MIT License

Copyright (c) 2026 Matt Pocock

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:
The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.
THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
'''


class ImproveCodebaseArchitectureSkillContractsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skill = (IMPROVE_DIR / "SKILL.md").read_text(encoding="utf-8")
        cls.report = (IMPROVE_DIR / "HTML-REPORT.md").read_text(encoding="utf-8")
        cls.notice = (IMPROVE_DIR / "LICENSE").read_text(encoding="utf-8")
        cls.manifest = (IMPROVE_DIR / "agents/openai.yaml").read_text(encoding="utf-8")
        cls.evals = json.loads((IMPROVE_DIR / "evals/evals.json").read_text(encoding="utf-8"))

    def assert_ordered(self, text, *anchors):
        position = -1
        for anchor in anchors:
            found = text.find(anchor, position + 1)
            self.assertGreater(found, position, anchor)
            position = found

    def test_structure_links_and_explicit_only_metadata(self):
        self.assertEqual(sorted(str(p.relative_to(IMPROVE_DIR)) for p in IMPROVE_DIR.rglob("*") if p.is_file()), sorted(IMPROVE_FILES))
        self.assertEqual(skill_frontmatter(self.skill), {
            "name": "improve-codebase-architecture",
            "description": "Scan a codebase for deepening opportunities, present them as a visual HTML report, then grill through whichever one you pick.",
            "disable-model-invocation": "true",
        })
        self.assertEqual(self.manifest, 'interface:\n  display_name: "Improve Codebase Architecture"\n  short_description: "Find and grill architecture improvements"\npolicy:\n  allow_implicit_invocation: false\n')
        root = IMPROVE_DIR.resolve()
        checked = 0
        for name, text in {"SKILL.md": self.skill, "HTML-REPORT.md": self.report}.items():
            for target in relative_markdown_links(text):
                checked += 1
                resolved = (root / name).parent.joinpath(target).resolve()
                self.assertTrue(resolved.is_relative_to(root), (name, target))
                self.assertTrue(resolved.is_file(), (name, target))
        self.assertGreaterEqual(checked, 2)

    def test_scan_pins_all_evidence_in_order_and_one_dispatch(self):
        self.assert_ordered(self.skill, "module and callers", "interface knowledge callers currently carry", "where locality or leverage is lost", "deletion-test result", "dependency category", "two justified adapters", "existing tests", "proposed interface-level test surface", "context or decision conflict")
        for dependency in ("codebase-design", "doc-grounded-questions", "worktrees", "design", "grill-with-docs", "wayfind", "writing-plans", "to-issues"):
            self.assertIn(f"`{dependency}`", self.skill)
            self.assertTrue((REPO_ROOT / "home/common/agent-skills/skills" / dependency).is_dir(), dependency)
        for fragment in ("bypasses inference", "git log --oneline --no-merges -50", "scattered", "History selects where to look", "writes nothing to the repository", "at most one structured findings artifact", "zero to five", "Never pad", "successful run", "Strong", "Worth exploring", "Speculative", "when at least one candidate exists"):
            self.assertIn(fragment, self.skill)
        lines = self.skill.splitlines()
        self.assertEqual([line for line in lines if "Agent(" in line], [IMPROVE_CALL])
        self.assertEqual(lines.index(IMPROVE_CALL), lines.index(IMPROVE_MARKER) + 1)

    def test_report_pins_scaffold_cdns_and_accessible_fallbacks(self):
        for fragment in ("<!doctype html>", '<html lang="en">', '<script src="https://cdn.tailwindcss.com"></script>', 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs', '<section id="candidates"', '<section id="top-recommendation"', "Mermaid graph", "Hand-built boxes-and-arrows", "Cross-section", "Mass diagram", "Call-graph collapse", "semantic headings", "text equivalent", "colour is never the sole", "minimal inline base styles", "4.5:1", "phone width", "without duplicating content", "text is not clipped", "user spacing overrides"):
            self.assertIn(fragment, self.report)
        for css in ("body {", "font-family:", "line-height: 1.5", "overflow-wrap: anywhere", "max-width: 100%", "height: auto", ".before-after {", "grid-template-columns: repeat(2, minmax(0, 1fr))", "@media (max-width: 640px)", "grid-template-columns: 1fr"):
            self.assertIn(css, self.report)
        for fragment in ("$TMPDIR", "/tmp", "%TEMP%", "architecture-review-<timestamp>.html", "absolute path", "generation failure is a failed run", "browser", "CDN", "disclosed warning", "before/after", "Top recommendation"):
            self.assertIn(fragment, self.skill)

    def test_routing_and_exact_ordered_provenance(self):
        self.assert_ordered(self.skill, "`wayfind`", "`worktrees`", "`design`", "`grill-with-docs`", "`writing-plans`")
        for fragment in ("no design worktree", "do not automatically resume", "Do not invoke", "Selection is the first point"):
            self.assertIn(fragment, self.skill)
        self.assertNotIn("from-issue", self.skill)
        self.assertNotIn("`grilling`", self.skill + self.report)
        self.assertNotIn("`domain-modeling`", self.skill + self.report)
        provenance = self.notice[:-len(MIT_NOTICE)]
        self.assertTrue(self.notice.endswith(MIT_NOTICE))
        headings = ("Vocabulary invocation", "Domain grounding repointed", "Hotspot rule made concrete", "Scan becomes a registered dispatch", "Candidate contract stated", "Report contract extended", "Downstream step replaced", "Provenance pointer", "Package extensions")
        self.assertEqual(len(re.findall(r"(?m)^  [1-9]\. ", provenance)), 9)
        self.assert_ordered(provenance, *(f"  {i}. {heading}" for i, heading in enumerate(headings, 1)))
        for fragment in ("https://github.com/mattpocock/skills", "skills/engineering/improve-codebase-architecture/", IMPROVE_REVISION, "2026-08-17", "no automatic synchronisation"):
            self.assertIn(fragment, provenance)
        self.assertIn("[LICENSE](LICENSE)", self.skill)

    def test_dispatch_registration_and_standalone_scenario(self):
        data = json.loads((REPO_ROOT / "home/common/agent-skills/model-matrix.json").read_text(encoding="utf-8"))
        site = {item["id"]: item for item in data["dispatch_sites"]}["improve-architecture-scan-owner"]
        self.assertEqual((site["path"], site["marker"], site["call"], site["role"], site["model"], site["effort"], site["requires"]), ("home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md", IMPROVE_MARKER, IMPROVE_CALL, "issue-owner", "opus", "high", []))
        self.assertEqual(data["scenarios"]["improve-codebase-architecture"], [{"workflow": "improve-codebase-architecture", "dispatch": "improve-architecture-scan-owner", "role": "issue-owner", "model": "opus", "effort": "high", "requires": []}])

    def test_eval_assertion_shells_are_unique_and_behavioral(self):
        self.assertEqual(self.evals["skill_name"], "improve-codebase-architecture")
        cases = {case["id"]: case for case in self.evals["evals"]}
        self.assertEqual({i: (c["name"], c["mode"]) for i, c in cases.items()}, {1: ("scan-only-renders-a-temporary-report", "pipeline"), 2: ("clear-selection-reaches-a-design-worktree", "pipeline"), 3: ("foggy-selection-routes-to-wayfind", "pipeline")})
        required_shells = {
            1: {"temporary report exists outside repository": ('architecture-review-', '[ -f "$report" ]', '$REPO'), "report is evidence-backed or truthful": ("before", "after", "top recommendation", "no.?candidate"), "history miss widened the scan": ("out_matches", "widen"), "repository and branches stayed unchanged": ('test "$WT_COUNT" -eq 0', "status --porcelain", "origin/main")},
            2: {"one isolated design worktree exists": ('test "$WT_COUNT" -eq 1', 'test -n "$WT"'), "design spec was committed": ('commits_touch "$WT" "$SPEC_DIR"',), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests', 'path_unchanged_since "$WT" origin/main tinytask tests'), "no plan was created": ('if has_file "$REPO/$PLAN_DIR"/*.md "$WT/$PLAN_DIR"/*.md; then', "fail"), "domain review was reached": ("out_matches", "grill-with-docs"), "scope workflow was recommended and execution stopped": ("out_matches", "recommend", "stop|stopping|not invok")},
            3: {"new wayfind map exists and prior map stayed unchanged": (".claude/wayfind/concurrent-shells", "path_unchanged_since"), "no worktree was created": ('test "$WT_COUNT" -eq 0',), "no spec or plan was created": ('if has_file "$REPO/$SPEC_DIR"/*.md "$REPO/$PLAN_DIR"/*.md; then', "fail"), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests',), "wayfind returned control without continuation": ("out_matches", "stop|return control", "issues|to-issues|writing-plans|implementation|execute")},
        }
        for case_id, case in cases.items():
            self.assertNotIn("expected_today", case)
            self.assertIn("/improve-codebase-architecture", case["prompt"])
            self.assertTrue(case["expected_output"].strip())
            assertions = case["asserts"]
            names = [item["name"] for item in assertions]
            self.assertEqual(len(names), len(set(names)))
            self.assertTrue(all(item["shell"].strip() for item in assertions))
            shells = {item["name"]: item["shell"] for item in assertions}
            self.assertEqual(set(shells), set(required_shells[case_id]))
            for name, fragments in required_shells[case_id].items():
                self.assertIn(name, shells)
                for fragment in fragments:
                    self.assertIn(fragment, shells[name])
        clear_prompt = cases[2]["prompt"]
        for fragment in ("Nobody is present", "reversible in-scope", "scope-redrawing", "hard to reverse", "credential", "spending", "cannot answer", "stop", "Do not create a plan", "Do not refactor"):
            self.assertIn(fragment, clear_prompt)
```

- [ ] **Step 3: Write the failing matrix contract and adjacent test rename**

Add this self-contained method inside `AgentModelMatrixTest`. Separately rename `test_representative_trace_covers_every_workflow_with_safe_rereviews` to `test_representative_trace_covers_every_issue_delivery_workflow_with_safe_rereviews` without changing its body:

```python
    def test_improve_codebase_architecture_trace_is_standalone(self):
        module = load_module()
        data = json.loads(MATRIX.read_text(encoding="utf-8"))
        expected_site = {
            "id": "improve-architecture-scan-owner",
            "path": "home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md",
            "marker": "<!-- agent-dispatch: id=improve-architecture-scan-owner role=issue-owner model=opus effort=high -->",
            "call": 'Agent(subagent_type="general-purpose", model="opus", effort="high") performs the one read-only architecture scan and returns evidence-backed deepening candidates without writing to the repository.',
            "role": "issue-owner", "model": "opus", "effort": "high", "requires": [],
        }
        expected_event = {
            "workflow": "improve-codebase-architecture",
            "dispatch": "improve-architecture-scan-owner",
            "role": "issue-owner", "model": "opus", "effort": "high", "requires": [],
        }
        self.assertIn("improve-codebase-architecture", module.WORKFLOW_FAMILIES)
        sites = {site["id"]: site for site in data["dispatch_sites"]}
        self.assertEqual(sites["improve-architecture-scan-owner"], expected_site)
        self.assertEqual(data["scenarios"]["improve-codebase-architecture"], [expected_event])
        self.assertEqual(module.trace(REPO_ROOT, "improve-codebase-architecture"), [{key: expected_event[key] for key in ("workflow", "dispatch", "role", "model", "effort")}])
        self.assertEqual({event["workflow"] for event in module.trace(REPO_ROOT, "representative")}, {"orchestration", "from-issue", "sdd", "shipping"})
```

Run the red gate before creating any package or matrix entry:

```bash
set -euo pipefail
if python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_improve_codebase_architecture_trace_is_standalone
then
  echo "expected new contracts to reject the starting subjects" >&2
  exit 1
fi
```

Expected: the package class errors because all five files are absent, and the matrix test fails because the starting closed family lacks `improve-codebase-architecture`. The historical validator itself stays green per D6.

- [ ] **Step 4: Author the complete five-file package, three evals, and matrix integration**

- Adapt the temporary pinned `SKILL.md` and `HTML-REPORT.md` exactly as D1–D19 require. Put the seven evidence anchors in their tested order. The caller, not scan owner, renders every clearing candidate, up to five. Preserve the no-dispatch inline fallback without a second `Agent(` token.
- Preserve upstream scaffold, both exact CDN URLs, five diagram patterns, and editorial voice in `HTML-REPORT.md`. Add semantic order, adjacent text alternatives, non-color meaning, inline fallback CSS, 4.5:1 contrast, phone collapse, overflow wrapping/max-width, and prose that explicitly guarantees no clipping under user spacing.
- Copy upstream `openai.yaml` byte-for-byte. Build `LICENSE` as provenance plus numbered adaptations 1–9 in the tested order, followed immediately by the exact temporary upstream `LICENSE` bytes.
- Author Eval 1 as the unscoped scan-only case with a real temporary-file assertion, truthful candidate/no-candidate branch, widen disclosure, and unchanged repository/branch inventory.
- Author Eval 2 with concrete `tinytask.store` selection. Its prompt says nobody is present; recommendations answer only reversible in-scope questions; scope-redrawing, hard-to-reverse, credential, spending, or unanswerable questions stop. It forbids plan/refactor. Named shells prove one worktree, `commits_touch "$WT" "$SPEC_DIR"`, unchanged source/tests in both trees, no plan, reached domain review, and recommendation-plus-stop semantics.
- Author Eval 3 for cross-machine-sync fog. Named shells prove a new map, unchanged `concurrent-shells`, no worktree/spec/plan, `path_unchanged_since "$REPO" origin/main tinytask tests`, and output that `wayfind` returned control without issues, planning, or execution. No separate issue-file assertion exists because tracker `kind:none` has no canonical issue artifact per D16.
- Append the exact dispatch row last, add `improve-codebase-architecture` to `WORKFLOW_FAMILIES`, and add its exact one-event scenario. Change no existing scenario or selection.

- [ ] **Step 5: Verify all contracts, deployment, scope, and the single commit**

Run:

```bash
set -euo pipefail
python3 -m json.tool home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json >/dev/null
jq -e '.skill_name == "improve-codebase-architecture" and ([.evals[].id] == [1,2,3]) and ([.evals[].mode] | all(. == "pipeline")) and ([.evals[] | has("expected_today")] | all(. == false))' home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json >/dev/null
python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_improve_codebase_architecture_trace_is_standalone \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_representative_trace_covers_every_issue_delivery_workflow_with_safe_rereviews \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_repository_contract_validates
just agent-workflow-tests
just agent-model-matrix
python3 home/common/agent-skills/scripts/agent-model-matrix.py trace improve-codebase-architecture
just build
configured_user=$(nix eval --raw --file vars/default.nix username)
home_tree=$(nix build ".#darwinConfigurations.mbp.config.home-manager.users.${configured_user}.home-files" --no-link --print-out-paths)
test -L "$home_tree/.agents/skills/improve-codebase-architecture"
test -d "$home_tree/.claude/skills/improve-codebase-architecture"
for relative in SKILL.md HTML-REPORT.md LICENSE agents/openai.yaml evals/evals.json; do
  test -e "$home_tree/.agents/skills/improve-codebase-architecture/$relative"
  test -e "$home_tree/.claude/skills/improve-codebase-architecture/$relative"
done
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
git diff --quiet f471376 -- '*.nix' flake.nix justfile \
  home/common/agent-skills/README.md \
  home/common/agent-skills/skills/codebase-design \
  .claude/specs/2026-08-17-improve-codebase-architecture-design.md
```

Expected: the complete static suite, matrix validation/trace, and unactivated builds pass; both generated agent surfaces expose all five files; scoped diffs name only the nine task-owned files; forbidden paths are unchanged. The new deployed evals are not run before human activation.

```bash
set -euo pipefail
git add \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -S -m "feat(agent-skills): add architecture improvement workflow (#43)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
```
