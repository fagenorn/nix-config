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
- Treat every repository-derived report value as inert: HTML-escape text and attributes; give Mermaid opaque generated IDs, escaped text labels, no raw HTML labels or repository-derived syntax, `securityLevel: "strict"`, and `htmlLabels: false`; keep the markup-like regression executable per D21.
- Eval 1 accepts only one explicit zero-state report or one to five structurally complete candidate articles plus one valid top-recommendation link per D22.
- Route fog to `wayfind`, create exactly one new non-fixture map, preserve the independent no-mutation checks, and stop with the exact final non-empty `WAYFIND_COMPLETE` status; otherwise establish an isolated worktree before `design`, then invoke `grill-with-docs`, recommend `writing-plans` or `to-issues`, and stop without planning, issue creation, or execution per D9, D16, D19, and D23.
- `grilling` and `domain-modeling` occur only in `LICENSE`'s provenance comparison, never as active guidance, per D14.
- Do not edit `.nix` files, `flake.nix`, `justfile`, `home/common/agent-skills/README.md`, `codebase-design`, either accepted parent design, the eval harness, or the TinyTask fixture.
- Do not implement a candidate, automatically invoke this skill, activate Home Manager, run the deployed evals before activation, or claim deployed-behavior certification.
- The single implementation commit remains signed and includes `Co-Authored-By: Codex <noreply@openai.com>`.
- Use targeted reads, concise output, and paths rather than pasted artifacts.

## Test seams

- **Shared deployment seam:** build without activation, then assert both generated agent surfaces expose all five files.
- **Workflow-contract seam:** one appended `ImproveCodebaseArchitectureSkillContractsTest` pins package, provenance, routing, safe report rendering, the structure-aware Eval 1 parser, the exact-one-map/anchored-status Eval 3 contract, and each eval prompt and terminal shell; `AgentModelMatrixTest` plus the validator pin the closed family, exact dispatch, standalone trace, and unchanged issue-delivery trace per D6, D7, D15, D18, and D20–D23.
- **Deployed-behavior seam:** three authored `pipeline` cases grade scan-only, clear-selection, and fog-selection behavior after a later human activation; their authored assertions use the structural and anchored contracts per D12, D16, D19, D20, D22, and D23.

## Task index

Task 1 — Ship the complete architecture-improvement workflow — `home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md`, `home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md`, `home/common/agent-skills/skills/improve-codebase-architecture/LICENSE`, `home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml`, `home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json`, `home/common/agent-skills/model-matrix.json`, `home/common/agent-skills/scripts/agent-model-matrix.py`, `home/common/agent-skills/tests/test_agent_model_matrix.py`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py` — full

## Decisions

The issue spec owns D1–D23. This plan cites those rows and introduces no second ledger.

## Standards review

### Pass 1

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

### Pass 2

- Reviewer: `/root/issue43_plan_review`
- Report: `/private/tmp/issue43-plan-review.md`
- Reviewed HEAD: `82943205bd8119ad28c5d8fba59b28b3b0865f32`
- Base SHA: `2efb92d6ff600b92eb3c1ed35850141b21d8b85a`
- Reviewer path: native reviewer
- Fallback: `false`
- Findings: 4 Blocking, 1 Should-fix, 0 Discussion; all actionable findings applied.
- B1 → D15: the embedded notice now matches upstream bytes including paragraph blank lines, and `SKILL.md` is checked for no inline notice text.
- B2: Step 1 emits named absolute `AUTHORING_DIR` and `IMPLEMENTATION_START` handoff values; Steps 4 and 5 explicitly consume them.
- B3: package/eval and matrix starting-subject rejection run as independent fail-closed red gates.
- B4 → D20: each scenario prompt and its exact terminal observables are pinned independently, including negative continuation semantics.
- S1: forbidden paths are compared with implementation-start HEAD; the post-commit exact allowlist and clean-status gate reject every extra or dirty path.

### Execution review

- First reviewer: `/root/issue43_task_review`
- Implementation HEAD: `e0938f9`
- First findings: 0 Critical, 3 Important, 0 Minor.
- First review artifact: `.superpowers/sdd/2026-08-18-improve-codebase-architecture/task-1-review.md`
- Controller ruling: all three findings are valid; the higher-level safe-rendering and scenario-proof invariants govern over the earlier weak literal fragments, recorded as D21–D23.
- Fix report: `.superpowers/sdd/2026-08-18-improve-codebase-architecture/task-1-report.md`, section `Fix round 1`.
- Amended HEAD: `2350b2d`
- Scoped reviewer: `/root/issue43_task_rereview`
- Scoped re-review artifact: `.superpowers/sdd/2026-08-18-improve-codebase-architecture/task-1-rereview-1.md`
- Verdict: all 3 findings addressed; no new Important or Critical finding in the bounded five-file fix package.
- Verification remained static/build-only: the focused contract class passed 9/9, the focused package/matrix selection passed 12/12, the full workflow suite passed 222/222, matrix and unactivated builds passed, and no deployed eval was run.

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
- Consumes: named Step 1 handoffs `AUTHORING_DIR` and `IMPLEMENTATION_START`; immutable upstream sources listed in Step 1; `codebase-design`; `doc-grounded-questions`, `worktrees`, `design`, `grill-with-docs`, `wayfind`, `writing-plans`, `to-issues`; matrix `dispatch_sites`/`scenarios`; eval variables `OUT`, `REPO`, `WT`, `WT_COUNT`, `SPEC_DIR`, `PLAN_DIR` and existing assertion helpers.
- Produces: explicit skill `$improve-codebase-architecture`; dispatch `improve-architecture-scan-owner`; workflow/scenario `improve-codebase-architecture`; eval ids 1–3; one complete signed implementation commit.

**Invariants:**
- `SKILL.md` alone is always loaded; `HTML-REPORT.md` is loaded only when rendering per D1.
- The exact marker occurs once and its exact `Agent(...)` call is the next line; no other package line contains `Agent(`.
- Named scope bypasses inference. Unscoped discovery runs `git log --oneline --no-merges -50`, follows the strongest concentration, and widens only for scattered/no concentration; history is never change evidence.
- The fresh scan owner establishes all seven evidence items in their accepted order and returns findings; the caller renders. Selection is the first possible repository mutation.
- Report generation fails the run; browser/CDN failures warn; an absolute temporary path is always printed. Zero candidates succeeds truthfully.
- Before the report is opened, all repository-derived text and attributes are HTML-escaped; Mermaid receives only opaque generated IDs and escaped text labels, never raw HTML labels or repository-derived graph syntax, under strict security with HTML labels disabled per D21.
- Fog returns after `wayfind` with no automatic resumption. Concrete selection uses an isolated worktree, `design`, approved `grill-with-docs`, then recommends a scope workflow and stops.
- Eval 2's one-shot autonomy answers only reversible in-scope recommendations. Scope-redrawing, hard-to-reverse, credential, spending, or unanswerable questions stop.
- Eval 1 parses the report structure and accepts only exactly one `<section id="candidates">` containing either `<p id="no-candidates" data-candidate-count="0">No evidence-backed candidates.</p>` with no candidate article/top section, or one to five unique `<article data-architecture-candidate id="candidate-N">` elements with all seven non-empty `data-evidence` surfaces, non-empty `data-diagram-text="before"` and `"after"` surfaces, and exactly one `#candidate-N` top-recommendation link per D22.
- Each eval prompt and named shell proves its own scenario identity and terminal state: unscoped scan, concrete `tinytask.store`, or `sync between machines`; exact repository/worktree state; allowed recommendation; and terminal routing per D20–D23.
- Eval 3 proves exactly one new non-`concurrent-shells` map and independently proves the prior map, worktree, spec/plan, and source/test state. Its final non-empty line is exactly `WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.`; no broad output-word ban remains. Under tracker `kind:none`, this anchored status is the issue-creation/continuation observable per D16 and D23.

- [ ] **Step 1: Fetch the four immutable authoring sources to a temporary directory**

Exact revision and URLs:

- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/SKILL.md`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/HTML-REPORT.md`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/skills/engineering/improve-codebase-architecture/agents/openai.yaml`
- `https://raw.githubusercontent.com/mattpocock/skills/9c9f36ccd3995266cd675468af71639c8dde1ec5/LICENSE`

Run this reproducible authoring-only fetch:

```bash
set -euo pipefail
implementation_start=$(git rev-parse HEAD)
upstream_revision=9c9f36ccd3995266cd675468af71639c8dde1ec5
upstream_root="https://raw.githubusercontent.com/mattpocock/skills/$upstream_revision"
authoring_dir=$(mktemp -d "${TMPDIR:-/tmp}/improve-architecture-upstream.XXXXXX")
authoring_dir=$(cd "$authoring_dir" && pwd -P)
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
printf 'AUTHORING_DIR=%s\n' "$authoring_dir"
printf 'IMPLEMENTATION_START=%s\n' "$implementation_start"
```

Expected: every effective URL equals its commit-addressed requested URL and all four temporary files are non-empty. The command prints one resolvable absolute `AUTHORING_DIR` and the exact `IMPLEMENTATION_START` commit. Record those two output lines as the named task handoff and export their values in every later shell that consumes them; do not re-fetch or discover a temporary directory by glob. Nothing under the repository changes; `/private/tmp` is not an input. These files are manual implementation-time references only per D17.

- [ ] **Step 2: Write the complete failing package/eval contract**

Add `import html`, `import os`, `import re`, `import subprocess`, and `import tempfile`, then append one contiguous block before the final `unittest.main()` guard in `test_workflow_skill_contracts.py`, reusing `skill_frontmatter` and `relative_markdown_links`. The core static contract and exact shell-fragment maps are:

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

    def test_report_escapes_repository_text_and_uses_strict_mermaid(self):
        unsafe = '<img title=\'repo\' onerror="alert(1)">&'
        escaped = html.escape(unsafe, quote=True)
        for fragment in (
            "HTML-escape every repository-derived value",
            "opaque generated node IDs",
            "escaped text labels",
            "no raw HTML labels",
            f"`{unsafe}` becomes `{escaped}`",
            'securityLevel: "strict"',
            "htmlLabels: false",
        ):
            self.assertIn(fragment, self.report)
        for fragment in (
            "HTML-escape every repository-derived value",
            "opaque generated Mermaid node IDs",
            "no raw HTML labels",
        ):
            self.assertIn(fragment, self.skill)
        self.assertNotIn('securityLevel: "loose"', self.report)

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
        self.assertNotIn("Permission is hereby granted", self.skill)

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
            1: {"temporary report exists outside repository": ('architecture-review-', '[ -f "$report" ]', '$REPO'), "report is evidence-backed or truthful": ('python3 - "$report"', "HTMLParser", "data-architecture-candidate", "data-evidence", "module-callers", "caller-interface-knowledge", "locality-leverage", "deletion-test", "dependency-adapters", "tests-interface-surface", "context-decision-conflict", "data-diagram-text", "before", "after", "no-candidates", "top-recommendation", "1 <= candidate_count <= 5"), "history miss widened the scan": ("out_matches", "widen"), "repository and branches stayed unchanged": ('test "$WT_COUNT" -eq 0', 'status=$(git -C "$REPO" status --porcelain)', 'test -z "$status"', 'test "$(git -C "$REPO" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse origin/main)"', "branches=$(git -C \"$REPO\" for-each-ref --format='%(refname:short)' refs/heads)", 'test "$branches" = "main"')},
            2: {"one isolated design worktree exists": ('test "$WT_COUNT" -eq 1', 'test -n "$WT"'), "design spec was committed": ('commits_touch "$WT" "$SPEC_DIR"',), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests', 'path_unchanged_since "$WT" origin/main tinytask tests'), "no plan was created": ('if has_file "$REPO/$PLAN_DIR"/*.md "$WT/$PLAN_DIR"/*.md; then', "fail"), "domain review was reached": ("out_matches", "grill-with-docs"), "scope workflow was recommended and execution stopped": ("out_matches", "recommend", "writing-plans|to-issues", "stop|stopping|not invok")},
            3: {"new wayfind map exists and prior map stayed unchanged": ('new_map_count=0', 'for map in "$REPO"/.claude/wayfind/*/map.md; do', "*/concurrent-shells/map.md) continue", '[ -f "$map" ] || continue', 'relative_map=${map#"$REPO"/}', 'if git -C "$REPO" cat-file -e "origin/main:$relative_map" 2>/dev/null; then', 'new_map_count=$((new_map_count + 1))', 'test "$new_map_count" -eq 1', 'path_unchanged_since "$REPO" origin/main .claude/wayfind/concurrent-shells'), "no worktree was created": ('test "$WT_COUNT" -eq 0',), "no spec or plan was created": ('if has_file "$REPO/$SPEC_DIR"/*.md "$REPO/$PLAN_DIR"/*.md; then', "fail"), "source and tests stayed unchanged": ('path_unchanged_since "$REPO" origin/main tinytask tests',), "wayfind returned control without continuation": ("terminal_line=", "WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.")},
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
        self.assertIn("unscoped", cases[1]["prompt"].lower())
        self.assertIn("tinytask.store", cases[2]["prompt"])
        self.assertIn("sync between machines", cases[3]["prompt"].lower())
        clear_prompt = cases[2]["prompt"]
        for fragment in ("Nobody is present", "reversible in-scope", "scope-redrawing", "hard to reverse", "credential", "spending", "cannot answer", "stop", "Do not create a plan", "Do not refactor"):
            self.assertIn(fragment, clear_prompt)
```

The same class owns two executable shell-regression methods, using an `assertion_shell(case_id, name)` lookup and a `run_assertion_shell(shell, out="", repo=None)` subprocess helper so the deployed assertions themselves are the subjects:

- `test_eval_1_report_assertion_rejects_malformed_structure` accepts the exact explicit zero report and a one-candidate report with all seven evidence markers, both diagram-text markers, and a top link. It rejects a candidate outside the candidates section, duplicate candidates sections, word-only HTML, a zero marker mixed with a top section, and six candidates. These cases pin the parser branches and the zero-or-1–5 cardinality per D22.
- `test_eval_3_counts_one_new_map_and_requires_final_status` accepts one new non-fixture map and rejects a second. It accepts the exact `WAYFIND_COMPLETE` line only when it is the final non-empty output line, rejects a generic wayfind stop, rejects output after that status, asserts the map shell contains no early `break`, and asserts the terminal shell contains no broad `out_lacks` ban per D23.

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

Run both red gates independently before creating any package or matrix entry:

```bash
set -euo pipefail
if python3 -m unittest -v \
  home.common.agent-skills.tests.test_workflow_skill_contracts.ImproveCodebaseArchitectureSkillContractsTest
then
  echo "expected package/eval contract to reject the starting package" >&2
  exit 1
fi
if python3 -m unittest -v \
  home.common.agent-skills.tests.test_agent_model_matrix.AgentModelMatrixTest.test_improve_codebase_architecture_trace_is_standalone
then
  echo "expected matrix contract to reject the starting matrix" >&2
  exit 1
fi
```

Expected: the package class errors because all five files are absent, and the matrix test fails because the starting closed family lacks `improve-codebase-architecture`. The historical validator itself stays green per D6.

- [ ] **Step 4: Author the complete five-file package, three evals, and matrix integration**

Export `AUTHORING_DIR` to the exact absolute path printed by Step 1, then prove the named handoff resolves before editing:

```bash
set -euo pipefail
: "${AUTHORING_DIR:?export the exact AUTHORING_DIR printed by Step 1}"
case "$AUTHORING_DIR" in
  /*) ;;
  *) echo "AUTHORING_DIR must be absolute" >&2; exit 1 ;;
esac
test -d "$AUTHORING_DIR"
for relative in SKILL.md HTML-REPORT.md openai.yaml LICENSE; do
  test -s "$AUTHORING_DIR/$relative"
done
```

Consume only those four returned-path files; do not re-fetch or search temporary directories.

- Adapt `$AUTHORING_DIR/SKILL.md` and `$AUTHORING_DIR/HTML-REPORT.md` exactly as D1–D23 require. Put the seven evidence anchors in their tested order. The caller, not scan owner, renders every clearing candidate, up to five. Preserve the no-dispatch inline fallback without a second `Agent(` token.
- Preserve upstream scaffold, both exact CDN URLs, five diagram patterns, and editorial voice in `HTML-REPORT.md`. Add semantic order, adjacent text alternatives, non-color meaning, inline fallback CSS, 4.5:1 contrast, phone collapse, overflow wrapping/max-width, and prose that explicitly guarantees no clipping under user spacing. At the auto-open boundary, require HTML escaping for every repository-derived text/attribute value; opaque generated Mermaid IDs; escaped text labels; no raw HTML labels or repository-derived graph syntax; `securityLevel: "strict"`; and `htmlLabels: false`. Include the exact markup-like escaping example that the D21 contract derives with `html.escape(..., quote=True)`.
- Copy `$AUTHORING_DIR/openai.yaml` byte-for-byte. Build `LICENSE` as provenance plus numbered adaptations 1–9 in the tested order, followed immediately by the byte-exact `$AUTHORING_DIR/LICENSE`, including both paragraph-separating blank lines.
- Author Eval 1 with an explicitly unscoped scan-only prompt, a real temporary-file assertion, widen disclosure, empty `status --porcelain`, `HEAD` at `origin/main`, local branches exactly `main`, and zero linked worktrees. Its `HTMLParser` assertion fails closed unless there is exactly one candidates section containing either the exact zero marker with no candidate/top section, or one to five unique marked candidate articles, each with exactly one non-empty instance of all seven evidence markers and both diagram-text markers, plus exactly one top-recommendation link to a candidate per D22.
- Author Eval 2 with concrete `tinytask.store` selection. Its prompt says nobody is present; recommendations answer only reversible in-scope questions; scope-redrawing, hard-to-reverse, credential, spending, or unanswerable questions stop. It forbids plan/refactor. Named shells prove one worktree, `commits_touch "$WT" "$SPEC_DIR"`, unchanged source/tests in both trees, no plan, reached domain review, and a `writing-plans` or `to-issues` recommendation plus stop semantics.
- Author Eval 3 for the literal `sync between machines` fog. Count every non-`concurrent-shells` `map.md` absent from `origin/main` and require exactly one; independently prove unchanged `concurrent-shells`, no worktree/spec/plan, and `path_unchanged_since "$REPO" origin/main tinytask tests`. Require the final non-empty output line to equal `WAYFIND_COMPLETE: map created; control returned before issue creation, planning, or implementation.` and use no broad word ban. No separate issue-file assertion exists because tracker `kind:none` has no canonical issue artifact per D16 and D23.
- Append the exact dispatch row last, add `improve-codebase-architecture` to `WORKFLOW_FAMILIES`, and add its exact one-event scenario. Change no existing scenario or selection.

- [ ] **Step 5: Verify all contracts, deployment, scope, and the single commit**

Run:

```bash
set -euo pipefail
: "${IMPLEMENTATION_START:?export the exact IMPLEMENTATION_START printed by Step 1}"
test "$IMPLEMENTATION_START" = "$(git rev-parse "$IMPLEMENTATION_START")"
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
git diff --check "$IMPLEMENTATION_START" -- \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git diff --stat "$IMPLEMENTATION_START" -- \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git diff --quiet "$IMPLEMENTATION_START" -- '*.nix' flake.nix justfile \
  home/common/agent-skills/README.md \
  home/common/agent-skills/skills/codebase-design \
  home/common/agent-skills/evals/run-eval.sh \
  home/common/agent-skills/evals/assert-lib.sh \
  home/common/agent-skills/evals/fixture-repo \
  .claude/specs/2026-08-17-improve-codebase-architecture-design.md \
  .claude/specs/2026-08-17-issue-43-improve-codebase-architecture-design.md \
  .claude/plans/2026-08-18-improve-codebase-architecture.md
```

Expected: the complete static suite, matrix validation/trace, and unactivated builds pass; both generated agent surfaces expose all five files; scoped diffs name only the nine task-owned files; every forbidden path is unchanged since implementation-start HEAD. The new deployed evals are not run before human activation.

```bash
set -euo pipefail
: "${IMPLEMENTATION_START:?export the exact IMPLEMENTATION_START printed by Step 1}"
git add \
  home/common/agent-skills/skills/improve-codebase-architecture \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -S -m "feat(agent-skills): add architecture improvement workflow (#43)" \
  -m "Co-Authored-By: Codex <noreply@openai.com>"
expected_paths=$(printf '%s\n' \
  home/common/agent-skills/model-matrix.json \
  home/common/agent-skills/scripts/agent-model-matrix.py \
  home/common/agent-skills/skills/improve-codebase-architecture/HTML-REPORT.md \
  home/common/agent-skills/skills/improve-codebase-architecture/LICENSE \
  home/common/agent-skills/skills/improve-codebase-architecture/SKILL.md \
  home/common/agent-skills/skills/improve-codebase-architecture/agents/openai.yaml \
  home/common/agent-skills/skills/improve-codebase-architecture/evals/evals.json \
  home/common/agent-skills/tests/test_agent_model_matrix.py \
  home/common/agent-skills/tests/test_workflow_skill_contracts.py | LC_ALL=C sort)
test "$(git rev-parse HEAD^)" = "$IMPLEMENTATION_START"
actual_paths=$(git diff-tree --no-commit-id --name-only -r HEAD | LC_ALL=C sort)
test "$actual_paths" = "$expected_paths"
status=$(git status --porcelain)
test -z "$status"
```

Expected: the signed implementation commit has implementation-start HEAD as its sole parent and contains exactly the nine allowlisted product paths, so pre-existing plan/spec commits are excluded; the worktree is clean. Any extra committed or uncommitted path fails this gate.
