# Task 2: Migrate shared workflow consumers to one snapshot

**Files:**
- Modify: `home/common/agent-skills/tests/test_workflow_skill_contracts.py`
- Modify: `home/common/agent-skills/README.md`
- Modify: `home/common/agent-skills/skills/design/SKILL.md`
- Modify: `home/common/agent-skills/skills/doc-grounded-questions/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/from-issue/bindings.md`
- Modify: `home/common/agent-skills/skills/from-issue/AUTO.md`
- Modify: `home/common/agent-skills/skills/from-issue/REVIEW-CONTRACT.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/SKILL.md`
- Modify: `home/common/agent-skills/skills/grill-with-docs/CONTEXT-FORMAT.md`
- Modify: `home/common/agent-skills/skills/research/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/SKILL.md`
- Modify: `home/common/agent-skills/skills/sdd/final-review.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-issue/REVIEW.md`
- Modify: `home/common/agent-skills/skills/ship-issue/CONSOLIDATE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/HUMAN-GATE.md`
- Modify: `home/common/agent-skills/skills/ship-issue/SYNC.md`
- Modify: `home/common/agent-skills/skills/ship-release/SKILL.md`
- Modify: `home/common/agent-skills/skills/ship-release/CHANGELOG.md`
- Modify: `home/common/agent-skills/skills/to-issues/SKILL.md`
- Modify: `home/common/agent-skills/skills/wayfind/SKILL.md`
- Modify: `home/common/agent-skills/skills/worktrees/SKILL.md`
- Modify: `home/common/agent-skills/skills/writing-plans/SKILL.md`

**Interfaces:**
- Consumes: `resolve-project resolve --repo-root <checkout>` and the `ResolvedProject` namespaces in D1/D3; review consumers additionally consume `bindings.workflow.review.{plan,code}` and the referenced `bindings.commands[review_id]` entry (D7).
- Produces: canonical shared phase-entry instructions that resolve once and retained-snapshot support documents that never resolve; a `ProjectPolicySurface` assertion helper reusable by Tasks 3, 4, and 6.

**Invariants:**
- The phase-entry set is exact: `design`, `doc-grounded-questions`, `from-issue`, `grill-with-docs`, `research`, `ship-issue`, `ship-release`, `to-issues`, `wayfind`, `worktrees`, and `writing-plans`. Delegated phases resolve at their own entry; included Markdown files reuse the caller's snapshot.
- Every entry uses the literal command once, retains the full object in memory, and states that every resolver error is fatal before mutation/effects. No `not_onboarded`, helper-missing, manifest, Git, or literal-default branch survives (D1).
- `sdd` receives the retained project from its phase entry/caller and uses its integration branch and review command IDs; it does not perform a second policy read.
- Artifact paths, tracker credentials, VCS/merge policy, orchestration, verification, review, release, deploy, and knowledge paths are named by their exact D3 snapshot fields.
- A `blocked` required capability stops. An authored `unsupported` capability takes only an already-documented no-capability route; it never manufactures a value.
- Plan and full correctness reviews use the configured review ID and base argv. Per D7 the argv tail is exactly `exec --sandbox read-only --model gpt-6-astra -c model_reasoning_effort="xhigh" --json --output-last-message <absolute-last-message> --ephemeral -C <absolute-worktree> -`, executed from the command entry's cwd after unsetting only its declared env names.
- Review event JSONL must report the selected model `gpt-6-astra` and reasoning effort `xhigh`; the last-message file must be non-empty, agree with the terminal agent-message event, and satisfy the operation headings before identity is recorded as Codex. `review.*` blocked stops. A daemon/slot/capacity rejection is binding and surfaced with no retry, plugin dispatch, or native-review bypass. Authored unsupported or a non-capacity completed runtime/output failure uses the existing single native fallback and records why.

- [ ] **Step 1: Add the canonical shared-surface contract first**

Add this table and assertion helper to `test_workflow_skill_contracts.py`; use `normalized()` already defined in that module.

```python
SHARED_POLICY_ENTRIES = {
    "design/SKILL.md": ("bindings.paths.artifacts.specs",),
    "doc-grounded-questions/SKILL.md": (
        "bindings.paths.context", "bindings.paths.standards",
        "bindings.paths.architecture", "bindings.paths.hints",
    ),
    "from-issue/SKILL.md": (
        "bindings.tracker", "bindings.vcs", "bindings.paths.artifacts",
        "bindings.workflow",
    ),
    "grill-with-docs/SKILL.md": ("bindings.paths.context",),
    "research/SKILL.md": ("bindings.paths.artifacts.specs",),
    "ship-issue/SKILL.md": (
        "bindings.tracker", "bindings.vcs", "bindings.commands",
        "bindings.workflow.review.code", "bindings.workflow.verification",
    ),
    "ship-release/SKILL.md": (
        "bindings.tracker", "bindings.vcs", "bindings.commands",
        "bindings.workflow.release", "bindings.deploy",
    ),
    "to-issues/SKILL.md": ("bindings.tracker", "bindings.paths",),
    "wayfind/SKILL.md": ("bindings.tracker",),
    "worktrees/SKILL.md": ("bindings.vcs",),
    "writing-plans/SKILL.md": ("bindings.paths.artifacts.plans",),
}

RESOLUTION_SENTENCE = (
    "Resolve once at phase entry, retain the returned `ResolvedProject` in "
    "memory, and treat every resolver error as fatal before mutation or "
    "external effects."
)

def assert_policy_entries(case, root, entries):
    actual = {str(path.relative_to(root)) for path in root.glob("*/SKILL.md")
              if "resolve-project resolve" in path.read_text(encoding="utf-8")}
    case.assertEqual(actual, set(entries))
    for relative, fields in entries.items():
        text = (root / relative).read_text(encoding="utf-8")
        with case.subTest(relative=relative):
            case.assertEqual(text.count("resolve-project resolve"), 1)
            case.assertIn(RESOLUTION_SENTENCE, normalized(text))
            for field in fields:
                case.assertIn(field, text)
            for forbidden in (
                "resolve-" "bindings", ".claude/skills." "config.json",
                "helper missing", "not_" "onboarded", "auto-detect", "default `",
            ):
                case.assertNotIn(forbidden, text)

class ProjectPolicySurfaceTest(unittest.TestCase):
    def test_shared_source_phase_entries_use_one_resolved_project(self):
        assert_policy_entries(
            self,
            REPO_ROOT / "home/common/agent-skills/skills",
            SHARED_POLICY_ENTRIES,
        )
```

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest.test_shared_source_phase_entries_use_one_resolved_project -v`

Expected before prose changes: FAIL on the exact consumer set and legacy/fallback text. If it passes at baseline, the test is not observing the migration.

- [ ] **Step 2: Rewrite the shared phase entries and retained support prose**

Give every tabled `SKILL.md` the exact resolution sentence and one invocation. Replace flat legacy names everywhere in the listed files with these direct mappings:

| Legacy meaning | Required snapshot source |
|---|---|
| `specDir`, `planDir` | `bindings.paths.artifacts.{specs,plans}` |
| context, standards, architecture, hints, operations, rejection docs | matching `bindings.paths` list plus `capabilities.knowledge.*` |
| tracker kind/CLI/repository/credential cleanup | `bindings.tracker.{kind,cli,repo_slug,credential_env.unset_before_invocation}` plus `capabilities.tracker` |
| integration/default branch, branch/worktree naming, signing/co-authoring, merge deletion/strategy | `bindings.vcs` |
| verify commands | IDs in `bindings.workflow.verification`, dereferenced through `bindings.commands` |
| plan/code review | IDs in `bindings.workflow.review`, dereferenced through `bindings.commands`, gated by `capabilities.review.*` |
| release/deploy | `bindings.workflow.release`, `bindings.deploy`, and `capabilities.{release,deploy}` |
| orchestration | `bindings.workflow.orchestration.{attempt_budget_minutes,max_parallel}` |

Delete every fallback, default, Git/manifest inference, helper-missing branch, Boolean tracker-token rule, and direct config read. Update examples and placeholders to snake_case field names. Support documents state that their values arrive from the phase owner's retained snapshot and contain zero resolver invocations.

For review paths, spell out the D7 algorithm in `sdd/final-review.md`, `ship-issue/REVIEW.md`, and their owning skills: choose the resolved plan/code review ID, require the corresponding capability, copy the referenced command entry, unset its declared env names without values, run the exact argv tail from **Invariants**, store JSONL and last-message files outside worktrees with unconditional cleanup, validate runtime model/effort plus terminal message equality, then validate operation headings. Never call `command -v codex-companion`, dispatch the plugin bridge, claim Codex identity from exit zero alone, or describe direct `codex exec` as capacity-safe. Preserve one native fallback only for authored unsupported review or an existing non-capacity completed runtime/output failure; a blocked capability stops, and any daemon/slot/capacity rejection is surfaced without a bypass.

- [ ] **Step 3: Pin direct configured review execution**

Add a contract test that extracts the review sections from `sdd`, `final-review.md`, `ship-issue`, and `REVIEW.md` and asserts all of these literals occur in order:

```python
def test_configured_review_command_is_direct_explicit_and_attributed(self):
    corpus = normalized("\n".join(path.read_text(encoding="utf-8") for path in (
        SDD,
        SDD_DIR / "final-review.md",
        SHIP_ISSUE,
        SHIP_ISSUE_REVIEW,
    )))
    for literal in (
        "bindings.workflow.review.plan",
        "bindings.workflow.review.code",
        "bindings.commands[review_id].argv",
        "exec", "--sandbox read-only", "--model gpt-6-astra",
        'model_reasoning_effort="xhigh"', "--json",
        "--output-last-message", "--ephemeral",
        "selected model", "selected reasoning effort",
        "terminal agent-message", "last-message",
    ):
        self.assertIn(literal, corpus)
    self.assertNotIn("command -v codex-companion", corpus)
    self.assertNotIn('subagent_type="codex:codex-reviewer"', corpus)
```

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py ProjectPolicySurfaceTest -v`

Expected: PASS for shared entries and configured review execution. A second resolver string, a missing snapshot namespace, or missing runtime attribution fails.

- [ ] **Step 4: Run the shared workflow contracts**

Run: `python3 home/common/agent-skills/tests/test_workflow_skill_contracts.py -q`

Expected: existing tests whose assertions encoded legacy policy are updated to assert the new exact fields and direct review route; all source-only contracts pass. Do not weaken unrelated lifecycle, artifact, review-package, or shipping assertions.

- [ ] **Step 5: Commit**

```bash
git add home/common/agent-skills/README.md home/common/agent-skills/skills home/common/agent-skills/tests/test_workflow_skill_contracts.py
git commit -S -m "refactor(skills): consume resolved project policy" -m "Co-Authored-By: Codex <noreply@openai.com>"
```
