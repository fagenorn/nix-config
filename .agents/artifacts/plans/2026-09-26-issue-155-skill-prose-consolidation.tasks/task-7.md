# Task 7: The live 36-profile model and its ceilings

**Files:**
- Create: `MODEL` (`home/common/agent-skills/instruction-load.json`)
- Test: `T/test_instruction_load.py`

**Interfaces:**
- Consumes (Task 5, in `IL`): `MODEL_PATH`, `FRAME_MEMBER`, `tree_reader(root)`,
  `load_model(data)`, `validate(model, read)` with its exact violation strings,
  `measure(model, read)` and `over_ceiling(model, measurement)`. The
  measurement shape is `{"frame", "documents": {member: {"path", "tree",
  "bytes", "words", "absent"}}, "profiles": {id: {host: {"hot"|"conditional":
  {"members", "bytes", "words"}}}}}`. A breach string starts
  `profile <id> on <host>: `. From the test module: `REPO_ROOT`.
- Consumes (Tasks 1–3): the edited skill documents. The ceilings measure the
  tree after those edits (D10).
- Consumes (Task 6): the `agent-instruction-load` recipe, for the smoke check
  in Step 5.
- Produces: `MODEL` with the 36 profile ids below. Task 8 and the report rely
  on them. In the test module it adds `ROSTER`, `BREACH` and `LiveModelTest`,
  which has five tests.

**Invariants:**
- The top-level keys are `frame`, `profiles` and `excluded_sites`, in that
  order. `frame` is `"agent-guidance/AGENTS.md"`. `excluded_sites` is exactly
  `{"sdd-codex-rescue-transport": "the codex:rescue plugin agent reads plugin
  documents outside both source trees"}` (spec §Roster).
- The 36 profiles appear in the order of the data block in Step 3, with their
  member lists in the order given, since that order is the report's. Each
  profile's keys are `id`, `entry` or `launch`, `hosts`, `prompt`, `hot`,
  `conditional`, `unread`, `ceiling_bytes` and `note`, in that order.
- The profiles claim 36 of the matrix's 37 dispatch sites, each exactly once
  (D23). Hot and conditional follow the spec's Terms and D24. Ambiguous means
  hot.
- Every `ceiling_bytes[host]` equals that profile's hot bytes on that host,
  measured over the working tree after Tasks 1–3. The build script in Step 3
  writes it. It is never hand-edited (D10, D29).
- This task changes no skill document, agent definition or `.nix` file. The
  model is repository data and is never installed (D9).

- [ ] **Step 1: Write the failing test**

In `T/test_instruction_load.py`, add `import copy` and `import re` to the
imports. Keep the imports in alphabetical order by module name. Then append,
after `ReportCommandTest` and before the `if __name__ == "__main__":` block:

```python
ROSTER = {
    "from-issue-controller": ["claude", "codex"],
    "orchestration-dispatcher": ["claude"],
    "orchestrated-issue-owner": ["claude"],
    "design-and-grill-owner": ["claude", "codex"],
    "planning-owner": ["claude", "codex"],
    "implementation-owner": ["claude", "codex"],
    "ship-owner": ["claude", "codex"],
    "release-owner": ["claude", "codex"],
    "researcher": ["claude", "codex"],
    "architecture-scan-owner": ["claude", "codex"],
    "research": ["claude", "codex"],
    "wayfind": ["claude", "codex"],
    "to-issues": ["claude", "codex"],
    "ship-release": ["claude", "codex"],
}
BREACH = re.compile(r"^profile (\S+) on (\S+): ")


class LiveModelTest(unittest.TestCase):
    def setUp(self):
        self.read = instruction_load.tree_reader(REPO_ROOT)
        raw = self.read(instruction_load.MODEL_PATH)
        self.assertIsNotNone(raw, f"{instruction_load.MODEL_PATH} is missing")
        self.model = instruction_load.load_model(raw)

    def profile(self, model, profile_id):
        return next(p for p in model["profiles"] if p["id"] == profile_id)

    def test_the_live_model_validates_clean(self):
        self.assertEqual(instruction_load.validate(self.model, self.read), [])

    def test_the_roster_profiles_are_modelled_on_their_hosts(self):
        hosts = {p["id"]: p["hosts"] for p in self.model["profiles"]}
        for profile_id, expected in ROSTER.items():
            with self.subTest(profile=profile_id):
                self.assertEqual(hosts.get(profile_id), expected)

    def test_each_live_mutation_yields_exactly_its_violation(self):
        live = self.read

        def with_copy(path):
            return lambda p: live(path) if p == path.replace(
                "agent-skills/skills", "claude-code/skills") else live(p)

        def drop_site(m):
            self.profile(m, "sdd-final-rereviewer")["launch"].remove("sdd-final-correctness-rereview")

        def unknown_member(m):
            self.profile(m, "research")["conditional"].append("from-issue/NOPE.md")

        def unnamed_member(m):
            self.profile(m, "research")["conditional"].append("to-issues/WIDE-REFACTORS.md")

        def unlisted_sibling(m):
            self.profile(m, "to-issues")["conditional"].remove("to-issues/WIDE-REFACTORS.md")

        def unknown_key(m):
            self.profile(m, "research")["extra"] = 1

        def duplicate_id(m):
            self.profile(m, "to-issues")["id"] = "research"

        def ceiling_host(m):
            del self.profile(m, "research")["ceiling_bytes"]["codex"]

        def empty_note(m):
            self.profile(m, "research")["note"] = ""

        sync = "home/common/agent-skills/skills/ship-issue/SYNC.md"
        cases = (
            ("a matrix site dropped", drop_site, live,
             "matrix site sdd-final-correctness-rereview is in no profile"),
            ("an unknown member", unknown_member, live,
             "profile research: from-issue/NOPE.md resolves to no document"),
            ("an ambiguous member", None, with_copy(sync),
             "profile ship-owner: ship-issue/SYNC.md resolves to 2 documents"),
            ("an unnamed member", unnamed_member, live,
             "profile research: to-issues/WIDE-REFACTORS.md is named by neither its "
             "prompt nor another member"),
            ("a named sibling left unlisted", unlisted_sibling, live,
             "profile to-issues: to-issues/SKILL.md names to-issues/WIDE-REFACTORS.md, "
             "which the profile does not list"),
            ("an unknown key", unknown_key, live, "profile research: unknown key 'extra'"),
            ("a duplicate profile id", duplicate_id, live, "profile research: duplicate id"),
            ("a ceiling host missing", ceiling_host, live,
             "profile research: ceiling_bytes hosts ['claude'] differ from hosts "
             "['claude', 'codex']"),
            ("an empty note", empty_note, live, "profile research: empty note"),
        )
        for label, mutate, read, expected in cases:
            with self.subTest(mutation=label):
                model = copy.deepcopy(self.model)
                if mutate is not None:
                    mutate(model)
                self.assertEqual(instruction_load.validate(model, read), [expected])

    def test_the_live_tree_breaches_no_ceiling(self):
        measurement = instruction_load.measure(self.model, self.read)
        self.assertEqual(instruction_load.over_ceiling(self.model, measurement), [])

    def test_growing_a_hot_member_breaches_exactly_the_pairs_that_count_it(self):
        measurement = instruction_load.measure(self.model, self.read)
        for member in ("from-issue/AUTO.md", "agents/reviewer.md"):
            with self.subTest(member=member):
                counting = {
                    (profile["id"], host)
                    for profile in self.model["profiles"] for host in profile["hosts"]
                    if member in measurement["profiles"][profile["id"]][host]["hot"]["members"]
                }
                self.assertTrue(counting)
                slack = max(
                    self.profile(self.model, pid)["ceiling_bytes"][host]
                    - measurement["profiles"][pid][host]["hot"]["bytes"]
                    for pid, host in counting)
                path = measurement["documents"][member]["path"]
                grown = lambda p, path=path, extra=b" " * (slack + 1): (
                    self.read(p) + extra if p == path else self.read(p))
                breaches = instruction_load.over_ceiling(
                    self.model, instruction_load.measure(self.model, grown))
                self.assertEqual({BREACH.match(b).groups() for b in breaches}, counting)
```

The growth test adds one byte past the largest slack among the pairs that
count the member (D26). `from-issue/AUTO.md` is hot for three profiles, in
five profile-and-host pairs. `agents/reviewer.md` is hot for nine profiles,
on Claude only.

- [ ] **Step 2: Run the test and watch it fail**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py -k LiveModelTest`
Expected: FAILED (failures=5). Each failure is raised in `setUp` with
`home/common/agent-skills/instruction-load.json is missing`.

- [ ] **Step 3: Build the model**

Pick a scratch directory `<scratch>` outside the working tree, for example
under `$TMPDIR`. Let `<worktree>` be the absolute path that
`git rev-parse --show-toplevel` prints. Use the file-writing tool to save the
data block below, exactly as given with one profile per line, as
`<scratch>/i155-profiles.jsonl`:

```json
{"id": "from-issue-controller", "entry": "from-issue", "hosts": ["claude", "codex"], "prompt": null, "hot": ["from-issue/SKILL.md", "from-issue/AUTO.md", "from-issue/bindings.md", "from-issue/investigate.md", "from-issue/grounding.md", "from-issue/decision-ledger.md", "from-issue/standards-review.md", "doc-grounded-questions/SKILL.md", "worktrees/SKILL.md"], "conditional": ["from-issue/ship-handoff.md", "handoff/SKILL.md", "wayfind/SKILL.md", "wayfind/DISCIPLINE.md", "doc-grounded-questions/REFERENCE.md", "codex-collaboration/SKILL.md", "codex-collaboration/PLAN-REVIEW.md"], "unread": {"from-issue/REVIEW-CONTRACT.md": "handed to the plan reviewer by absolute path, never read into this conversation", "codex-collaboration/DIFF-REVIEW.md": "diff-review is not a Phase 0–5 operation"}, "note": "Direct autonomous `--auto` run of Phases 0–5 and the rollover. Design, grill and planning run in their owners. The hot path keeps from-issue's top-level acquisition routes and AUTO.md's rollover, whose route-scoping is deferred (#155 D6)."}
{"id": "orchestration-dispatcher", "entry": "orchestrate-issues", "hosts": ["claude"], "prompt": null, "hot": ["orchestrate-issues/SKILL.md"], "conditional": [], "unread": {}, "note": "One control-adapter run. It loads only its entry, whose resolver paragraph and lifecycle-call rule stay per entry (#155 D5)."}
{"id": "orchestrated-issue-owner", "launch": ["orchestration-issue-owner"], "hosts": ["claude"], "prompt": "orchestrate-issues/SKILL.md", "hot": ["from-issue/SKILL.md", "from-issue/AUTO.md", "from-issue/bindings.md", "from-issue/investigate.md", "from-issue/grounding.md", "from-issue/decision-ledger.md", "from-issue/standards-review.md", "from-issue/ship-handoff.md", "doc-grounded-questions/SKILL.md", "worktrees/SKILL.md", "sdd/SKILL.md", "sdd/implementer-prompt.md", "sdd/task-reviewer-prompt.md", "sdd/final-review.md", "sdd/conformance-reviewer-prompt.md"], "conditional": ["sdd/fix-loop.md", "sdd/re-review-prompt.md", "sdd/correctness-reviewer-prompt.md", "codex-collaboration/SKILL.md", "codex-collaboration/PLAN-REVIEW.md", "codex-collaboration/DIFF-REVIEW.md", "handoff/SKILL.md", "wayfind/SKILL.md", "wayfind/DISCIPLINE.md", "doc-grounded-questions/REFERENCE.md"], "unread": {"from-issue/REVIEW-CONTRACT.md": "handed to the plan reviewer by absolute path, never read into this conversation"}, "note": "Dispatcher-owned `--auto` run of Phases 0–7 in one owner: from-issue with AUTO.md, sdd at Phase 6 and the ship prompt at Phase 7. It carries from-issue's top-level acquisition routes and AUTO.md's rollover, which its route never takes (#155 D6)."}
{"id": "design-and-grill-owner", "launch": ["from-issue-design-grill"], "hosts": ["claude", "codex"], "prompt": "from-issue/AUTO.md", "hot": ["design/SKILL.md", "grill-with-docs/SKILL.md", "doc-grounded-questions/SKILL.md"], "conditional": ["grill-with-docs/CONTEXT-FORMAT.md", "grill-with-docs/ADR-FORMAT.md", "doc-grounded-questions/REFERENCE.md", "research/SKILL.md"], "unread": {}, "note": "Phases 2–3 from AUTO.md's prompt: design, grill-with-docs and doc-grounded-questions. Their producer-report and explorer-escalation blocks stay per skill (#155 D5)."}
{"id": "planning-owner", "launch": ["from-issue-planning"], "hosts": ["claude", "codex"], "prompt": "from-issue/AUTO.md", "hot": ["writing-plans/SKILL.md", "doc-grounded-questions/SKILL.md"], "conditional": ["doc-grounded-questions/REFERENCE.md", "from-issue/REVIEW-CONTRACT.md"], "unread": {}, "note": "Phase 4 from AUTO.md's prompt: writing-plans and doc-grounded-questions, plus the review contract for a mechanical-only self-grade. The producer-report block stays per skill (#155 D5)."}
{"id": "implementation-owner", "launch": ["from-issue-phase-delegate"], "hosts": ["claude", "codex"], "prompt": "from-issue/AUTO.md", "hot": ["from-issue/SKILL.md", "from-issue/AUTO.md", "from-issue/bindings.md", "from-issue/ship-handoff.md", "sdd/SKILL.md", "sdd/implementer-prompt.md", "sdd/task-reviewer-prompt.md", "sdd/final-review.md", "sdd/conformance-reviewer-prompt.md", "sdd/correctness-reviewer-prompt.md", "worktrees/SKILL.md"], "conditional": ["sdd/fix-loop.md", "sdd/re-review-prompt.md", "codex-collaboration/SKILL.md", "codex-collaboration/DIFF-REVIEW.md", "from-issue/decision-ledger.md", "handoff/SKILL.md"], "unread": {"from-issue/investigate.md": "Phase 0 ran in the earlier controller", "from-issue/grounding.md": "Phases 2–5 ran in the earlier controller", "from-issue/standards-review.md": "Phase 5 ran in the earlier controller", "from-issue/REVIEW-CONTRACT.md": "the Phase-5 reviewer contract, handed over by path", "codex-collaboration/PLAN-REVIEW.md": "plan-review ran at Phase 5"}, "note": "Post-rollover Phases 6–7: from-issue with AUTO.md, sdd and the ship prompt; the Phase 0–5 documents stay unread. It carries from-issue's top-level acquisition routes, whose route-scoping is deferred (#155 D6)."}
{"id": "ship-owner", "launch": ["from-issue-ship-owner"], "hosts": ["claude", "codex"], "prompt": "from-issue/ship-handoff.md", "hot": ["ship-issue/SKILL.md", "ship-issue/SYNC.md", "ship-issue/REVIEW.md", "ship-issue/CONSOLIDATE.md"], "conditional": ["ship-issue/CI-MERGE.md", "ship-issue/HUMAN-GATE.md", "doc-grounded-questions/SKILL.md", "doc-grounded-questions/REFERENCE.md", "codex-collaboration/SKILL.md", "codex-collaboration/DIFF-REVIEW.md"], "unread": {"codex-collaboration/PLAN-REVIEW.md": "plan-review is not a ship operation"}, "note": "ship-issue from ship-handoff.md's prompt, with its sync, review and consolidation files. The lifecycle stdin clause stays per entry (#155 D5)."}
{"id": "release-owner", "launch": ["ship-release-owner"], "hosts": ["claude", "codex"], "prompt": "ship-release/SKILL.md", "hot": ["ship-release/SKILL.md", "ship-release/CHANGELOG.md"], "conditional": ["doc-grounded-questions/SKILL.md", "doc-grounded-questions/REFERENCE.md"], "unread": {}, "note": "One delegated release through ship-release and its changelog rubric."}
{"id": "researcher", "launch": ["research-background-researcher"], "hosts": ["claude", "codex"], "prompt": "research/SKILL.md", "hot": [], "conditional": [], "unread": {}, "note": "The background researcher works from the job list in research's prompt and loads no skill document."}
{"id": "architecture-scan-owner", "launch": ["improve-architecture-scan-owner"], "hosts": ["claude", "codex"], "prompt": "improve-codebase-architecture/SKILL.md", "hot": ["codebase-design/SKILL.md", "doc-grounded-questions/SKILL.md"], "conditional": ["codebase-design/DEEPENING.md", "codebase-design/DESIGN-IT-TWICE.md", "doc-grounded-questions/REFERENCE.md"], "unread": {}, "note": "The read-only scan from improve-codebase-architecture's prompt. The codebase-design vocabulary and the grounding pass are ambiguous between caller and scan owner, so they count as hot."}
{"id": "research", "entry": "research", "hosts": ["claude", "codex"], "prompt": null, "hot": ["research/SKILL.md"], "conditional": [], "unread": {}, "note": "A standalone research launch. It loads only its entry."}
{"id": "wayfind", "entry": "wayfind", "hosts": ["claude", "codex"], "prompt": null, "hot": ["wayfind/SKILL.md", "grill-with-docs/SKILL.md"], "conditional": ["wayfind/DISCIPLINE.md", "grill-with-docs/CONTEXT-FORMAT.md", "grill-with-docs/ADR-FORMAT.md", "research/SKILL.md", "prototype/SKILL.md", "prototype/LOGIC.md", "prototype/UI.md", "worktrees/SKILL.md"], "unread": {}, "note": "One decision session. Grilling is the default mode; research and prototype sessions are conditional."}
{"id": "to-issues", "entry": "to-issues", "hosts": ["claude", "codex"], "prompt": null, "hot": ["to-issues/SKILL.md"], "conditional": ["to-issues/WIDE-REFACTORS.md"], "unread": {}, "note": "One slicing run. The wide-refactor exception is conditional."}
{"id": "ship-release", "entry": "ship-release", "hosts": ["claude", "codex"], "prompt": null, "hot": ["ship-release/SKILL.md", "ship-release/CHANGELOG.md"], "conditional": ["doc-grounded-questions/SKILL.md", "doc-grounded-questions/REFERENCE.md"], "unread": {}, "note": "A direct interactive release, with the current session as owner."}
{"id": "plan-reviewer", "launch": ["from-issue-plan-review"], "hosts": ["claude", "codex"], "prompt": "from-issue/standards-review.md", "hot": ["agents/reviewer.md", "from-issue/REVIEW-CONTRACT.md"], "conditional": [], "unread": {}, "note": "The Phase-5 plan reviewer: its agent definition on Claude and the review contract it is told to read. Its prompt comes from standards-review.md."}
{"id": "from-issue-mechanic", "launch": ["from-issue-mechanical-implementation", "from-issue-ledger-remainder"], "hosts": ["claude", "codex"], "prompt": "from-issue/SKILL.md", "hot": ["agents/mechanic.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "from-issue-mechanical-reviewer", "launch": ["from-issue-mechanical-review"], "hosts": ["claude", "codex"], "prompt": "from-issue/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "inline-ship-reviewer", "launch": ["from-issue-inline-ship-review"], "hosts": ["claude", "codex"], "prompt": "from-issue/ship-handoff.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from from-issue/ship-handoff.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "design-explorer", "launch": ["design-bounded-fact-lookup"], "hosts": ["claude", "codex"], "prompt": "design/SKILL.md", "hot": [], "conditional": [], "unread": {}, "note": "The built-in Explore type: no installed definition and no skill document. Its prompt is composed from design/SKILL.md."}
{"id": "grill-explorer", "launch": ["grill-bounded-fact-lookup"], "hosts": ["claude", "codex"], "prompt": "grill-with-docs/SKILL.md", "hot": [], "conditional": [], "unread": {}, "note": "The built-in Explore type: no installed definition and no skill document. Its prompt is composed from grill-with-docs/SKILL.md."}
{"id": "planning-explorer", "launch": ["planning-bounded-fact-lookup"], "hosts": ["claude", "codex"], "prompt": "writing-plans/SKILL.md", "hot": [], "conditional": [], "unread": {}, "note": "The built-in Explore type: no installed definition and no skill document. Its prompt is composed from writing-plans/SKILL.md."}
{"id": "grounding-explorer", "launch": ["doc-grounded-bounded-code-lookup"], "hosts": ["claude", "codex"], "prompt": "doc-grounded-questions/SKILL.md", "hot": [], "conditional": [], "unread": {}, "note": "The built-in Explore type: no installed definition and no skill document. Its prompt is composed from doc-grounded-questions/SKILL.md."}
{"id": "sdd-mechanic", "launch": ["sdd-mechanic-implementation"], "hosts": ["claude", "codex"], "prompt": "sdd/implementer-prompt.md", "hot": ["agents/mechanic.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-implementer", "launch": ["sdd-nonmechanical-implementation"], "hosts": ["claude", "codex"], "prompt": "sdd/implementer-prompt.md", "hot": ["agents/implementer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/implementer-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-task-reviewer", "launch": ["sdd-first-pass-task-review"], "hosts": ["claude", "codex"], "prompt": "sdd/task-reviewer-prompt.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/task-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-task-rereviewer", "launch": ["sdd-scoped-task-rereview"], "hosts": ["claude", "codex"], "prompt": "sdd/re-review-prompt.md", "hot": ["agents/reviewer-lite.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/re-review-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-lane-verifier", "launch": ["sdd-lane-task-verification"], "hosts": ["claude", "codex"], "prompt": "sdd/SKILL.md", "hot": ["agents/reviewer-lite.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/SKILL.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-fix-implementer", "launch": ["sdd-post-rescue-implementation", "sdd-rescue-fallback-implementation", "sdd-round-five-implementation"], "hosts": ["claude", "codex"], "prompt": "sdd/fix-loop.md", "hot": ["agents/implementer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-fix-escalation-reviewer", "launch": ["sdd-task-rereview-escalation"], "hosts": ["claude", "codex"], "prompt": "sdd/fix-loop.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/fix-loop.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-conformance-reviewer", "launch": ["sdd-final-conformance-review"], "hosts": ["claude", "codex"], "prompt": "sdd/conformance-reviewer-prompt.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/conformance-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-correctness-reviewer", "launch": ["sdd-final-correctness-review"], "hosts": ["claude", "codex"], "prompt": "sdd/correctness-reviewer-prompt.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/correctness-reviewer-prompt.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-final-fixer", "launch": ["sdd-final-review-fixer"], "hosts": ["claude", "codex"], "prompt": "sdd/final-review.md", "hot": ["agents/implementer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-final-rereviewer", "launch": ["sdd-final-conformance-rereview", "sdd-final-correctness-rereview"], "hosts": ["claude", "codex"], "prompt": "sdd/final-review.md", "hot": ["agents/reviewer-lite.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "sdd-final-escalation-reviewer", "launch": ["sdd-final-rereview-escalation"], "hosts": ["claude", "codex"], "prompt": "sdd/final-review.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from sdd/final-review.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "ship-issue-reviewer", "launch": ["ship-issue-merge-delta-review", "ship-issue-full-conformance-review", "ship-issue-full-correctness-fallback"], "hosts": ["claude", "codex"], "prompt": "ship-issue/SKILL.md", "hot": ["agents/reviewer.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5)."}
{"id": "ship-issue-rereviewer", "launch": ["ship-issue-scoped-fix-rereview"], "hosts": ["claude", "codex"], "prompt": "ship-issue/SKILL.md", "hot": ["agents/reviewer-lite.md"], "conditional": [], "unread": {}, "note": "Loads only its agent definition on Claude and nothing on Codex. Its prompt comes from ship-issue/SKILL.md, whose leaf clauses #153 holds (#155 D5)."}
```

Save this build script as `<scratch>/i155-build-model.py`:

```python
"""Scratch, outside the working tree: build the #155 instruction-load model (D29)."""
import json
import sys
from pathlib import Path

from agent_tools import instruction_load

root, data = Path(sys.argv[1]), Path(sys.argv[2])
profiles = []
for line in data.read_text(encoding="utf-8").splitlines():
    if line.strip():
        profile = json.loads(line)
        note = profile.pop("note")
        profile["ceiling_bytes"] = {host: 0 for host in profile["hosts"]}
        profile["note"] = note
        profiles.append(profile)
model = {
    "frame": instruction_load.FRAME_MEMBER,
    "profiles": profiles,
    "excluded_sites": {
        "sdd-codex-rescue-transport":
            "the codex:rescue plugin agent reads plugin documents outside both source trees",
    },
}
read = instruction_load.tree_reader(root)
violations = instruction_load.validate(model, read)
if violations:
    print("\n".join(violations))
    raise SystemExit(1)
measurement = instruction_load.measure(model, read)
for profile in profiles:
    for host in profile["hosts"]:
        profile["ceiling_bytes"][host] = measurement["profiles"][profile["id"]][host]["hot"]["bytes"]
        print(profile["id"], host, profile["ceiling_bytes"][host])
(root / instruction_load.MODEL_PATH).write_text(
    json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

Run: `env PYTHONPATH=<worktree>/python python3 <scratch>/i155-build-model.py <worktree> <scratch>/i155-profiles.jsonl`
Expected: exit 0, with 70 lines of `<id> <host> <bytes>`: 34 profiles on two
hosts and two profiles on Claude only. Any violation printed instead is a
transcription error in the data file, since the block validated clean in the
planning probe. Fix the data file, not a skill document, and rerun.

- [ ] **Step 4: Verify**

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: OK, with 30 tests: 19 in `ModelCoreTest`, 6 in `ReportCommandTest`
and 5 in `LiveModelTest`.

Cross-check the printed ceilings against the planning probe, which applied
Tasks 1–3 exactly as written:

- `from-issue-controller` 87390 on both hosts. `orchestration-dispatcher`
  22142. `orchestrated-issue-owner` 146580.
- `design-and-grill-owner` 28256, `planning-owner` 22322,
  `implementation-owner` 137626 and `ship-owner` 52871, on both hosts.
- `release-owner` and `ship-release` 41929. `architecture-scan-owner` 12945.
  `research` 3617. `wayfind` 20356. `to-issues` 9308.
- `plan-reviewer` 9854 on Claude and 8839 on Codex.
- The agent-only profiles on Claude: `agents/mechanic.md` 679,
  `agents/reviewer.md` 1015, `agents/implementer.md` 1089 and
  `agents/reviewer-lite.md` 1443. They are 0 on Codex. `researcher` and the
  four explorers are 0 on both hosts.

A differing value is not wrong in itself, because the measured value is the
ceiling. Report each difference, with the Task 1–3 edit that explains it.

Run: `python3 -c "import json, pathlib, sys; t = pathlib.Path('home/common/agent-skills/instruction-load.json').read_text(encoding='utf-8'); sys.exit(t != json.dumps(json.loads(t), indent=2, ensure_ascii=False) + '\n')"`
Expected: exit 0 and no output. The file is in its canonical form.

Run `git add home/common/agent-skills/instruction-load.json`, so the
tracked-source scan sees the file. Then run:
`env WORKFLOW_POLICY_SURFACE=source python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_living_source_has_no_legacy_policy_surface`
Expected: OK. The model has no `LEGACY_POLICY_SURFACE` token.

Run: `git grep -n -F "instruction-load.json" -- "*.nix"`
Expected: no output and exit 1. Nothing installs the model.

Run: `git diff --name-only HEAD -- home/common/agent-skills/skills home/common/claude-code`
Expected: no output. No skill text changed in this task.

- [ ] **Step 5: Commit and smoke-test at a revision**

```bash
git add home/common/agent-skills/instruction-load.json home/common/agent-skills/tests/test_instruction_load.py
git commit -m "feat(agent-skills): model the instruction load of 36 profiles with hot-path ceilings (#155)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Run: `just agent-instruction-load report --base HEAD~1 --head HEAD --output <scratch>/i155-smoke.md`
Expected: exit 0. `<scratch>/i155-smoke.md` exists, and its first line is
`# Instruction load: <HEAD~1 short sha> → <HEAD short sha>`. The committed
model loads at a revision.

Decision IDs: D7, D8, D10, D11, D16, D18, D19, D23, D24, D26, D29.
