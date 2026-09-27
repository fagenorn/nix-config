# Task 8: Re-measure after the sync, regenerate the report, final gates

This task re-runs on the attempt-2 resume (D34). Tasks 1–7 are done. The
branch already carries attempt 1's report, and the sync merge `<sync>` was made
before this task by the plan root's `### Resume` R1 (D35).

**Files:**
- Create: `.agents/artifacts/specs/<date>-issue-155-instruction-load-report.md`.
  This is the specs directory, `bindings.paths.artifacts.specs`. `<date>` is
  the generation date, as `date +%F` prints it at Step 4.
- Delete: `.agents/artifacts/specs/2026-09-26-issue-155-instruction-load-report.md`,
  attempt 1's superseded report, in its own commit before the new one (D34).
- Modify: `MODEL`, its ceilings and notes, because `<sync>` moved a measured
  member (D19).
- No merge commit: this task fetches nothing and merges nothing (D35).

**Interfaces:**
- Consumes (Resume R1): `<sync>`, the newest merge commit on the branch's
  first-parent chain since `affa05e`. Its second parent is `origin/main` as R1
  fetched it.
- Consumes (Task 6):
  `just agent-instruction-load report --base REV --head REV [--output PATH] [--format markdown|json]`.
  It exits 0 on success. On failure it exits 2, writes one
  `agent-instruction-load: …` stderr line and writes no file. The JSON form is
  `{"base", "head", "frame", "documents", "profiles": [{"id", "entry",
  "launch", "prompt", "note", "unread", "hosts": {host: {"hot": T,
  "conditional": T, "ceiling_bytes"}}}]}`, where
  `T = {"members", "base", "head", "delta": {"bytes", "words"}, "affected"}`.
- Consumes (Task 5, in `IL`): `MODEL_PATH`, `tree_reader(root)`,
  `load_model(data)`, `validate(model, read)` and `measure(model, read)`.
- Consumes (Task 7): the model and `LiveModelTest`.
- Produces: the committed report. Its header records the base and head SHAs.

**Invariants:**
- Every command runs from the worktree root. `git rev-parse --show-toplevel`
  prints it as `<worktree>`, and `git branch --show-current` prints
  `worktree-issue-155-consolidate-skill-prose`. `<scratch>` is a directory
  outside the working tree.
- The sync is a merge, never a rebase, a squash or a reset (D30). It is made
  once, by R1, and this task never merges (D35).
- The report's base is `git merge-base HEAD origin/main`, which is
  `<sync>^2`. Its head is the commit it is generated at. It is committed alone,
  so its head is that commit's parent (D9, D17).
- When this task ends, exactly one `*-issue-155-instruction-load-report.md` is
  tracked, the new one (D34).
- The report is generated after the last content change. Any later commit
  that changes a measured member, the model or the matrix repeats Steps 3–5
  (D19).
- No ceiling is raised to pass a gate (D10). Nothing is recovered from
  `worktree-issue-99-skill-prose-fixes` (D15).

- [ ] **Step 1: Confirm the starting state**

Run: `git status --short`
Expected: no output.

Run: `git ls-files -- ".agents/artifacts/specs/*-issue-155-instruction-load-report.md"`
Expected at the start commit: exactly
`.agents/artifacts/specs/2026-09-26-issue-155-instruction-load-report.md`.
Its first line is `# Instruction load: affa05e → cd7ded7`, and `affa05e` is no
longer the merge-base. This task is incomplete until the command prints
exactly one path, `<report>`, whose first line names `<sync>^2`'s first seven
characters as its base.

- [ ] **Step 2: Verify the resume sync (D30, D35)**

Run: `git log --merges --first-parent --format=%H affa05e..HEAD`
Expected: at least one SHA, and one on this resume. The first SHA printed,
the newest, is `<sync>`.

Run: `git rev-parse <sync>^2`, then `git merge-base HEAD origin/main`
Expected: the same SHA twice. When R1 merged the `origin/main` of planning
time, it is `17da7f2d53c33886073a107ce72627f9e1ec5ce1`.

No merge, or a merge-base other than `<sync>^2`, means R1 is missing. Stop
with BLOCKED and name R1. Do not fetch or merge inside this task.

- [ ] **Step 3: Re-measure after the sync (D19, D29)**

This step always runs on the resume, because `<sync>` changed the measured
`from-issue/ship-handoff.md`. Save this script as
`<scratch>/i155-remeasure.py`:

```python
"""Scratch, outside the working tree: reset the ceilings a sync moved (#155 D19)."""
import json
import sys
from pathlib import Path

from agent_tools import instruction_load

root, merge = Path(sys.argv[1]), sys.argv[2]
path = root / instruction_load.MODEL_PATH
model = instruction_load.load_model(path.read_bytes())
read = instruction_load.tree_reader(root)
violations = instruction_load.validate(model, read)
if violations:
    print("\n".join(violations))
    raise SystemExit(1)
measurement = instruction_load.measure(model, read)
for profile in model["profiles"]:
    moved = False
    for host in profile["hosts"]:
        measured = measurement["profiles"][profile["id"]][host]["hot"]["bytes"]
        if profile["ceiling_bytes"][host] != measured:
            print(f"{profile['id']} on {host}: {profile['ceiling_bytes'][host]} -> {measured}")
            profile["ceiling_bytes"][host] = measured
            moved = True
    if moved:
        profile["note"] += f" Ceiling re-measured after merging origin/main at {merge} (#155 D19)."
path.write_text(json.dumps(model, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
```

Run: `env PYTHONPATH=<worktree>/python python3 <scratch>/i155-remeasure.py <worktree> <merge>`,
where `<merge>` is what `git rev-parse --short <sync>` prints.
Expected: exit 0. With `origin/main` at `17da7f2`, the planning probe printed
exactly these three lines:

```text
orchestrated-issue-owner on claude: 146629 -> 146623
implementation-owner on claude: 137675 -> 137669
implementation-owner on codex: 137675 -> 137669
```

If R1 merged a later `origin/main`, the lines can differ.

The script may print violations instead. That means the merge added a
dispatch site or a named document that the model does not cover. Extend
`MODEL` by the spec's rules, then rerun the script:
- A new matrix site joins the profile that shares its prompt source (the
  site's matrix `path` document), its agent definition and its member list.
  Otherwise it becomes a new profile. The new profile has hosts
  `["claude", "codex"]`, its `path` document as `prompt`, its agent
  definition as hot when the call's `subagent_type` names a file in
  `home/common/claude-code/agents`, ceilings of 0 and a `note` that says what
  it loads (D23).
- A newly named same-skill document is listed as hot, conditional or
  `unread` with a reason, per the spec's Terms and D24 (D18).

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_instruction_load.py`
Expected: OK, with 30 tests.

If `git status --short` now lists `home/common/agent-skills/instruction-load.json`, commit it alone:

```bash
git add home/common/agent-skills/instruction-load.json
git commit -m "chore(agent-skills): re-measure instruction-load ceilings after syncing origin/main (#155 D19)" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Retire the superseded report, then generate and commit the new one alone (D34)**

Record `<date>`, what `date +%F` prints, once. Let `<report>` be
`.agents/artifacts/specs/<date>-issue-155-instruction-load-report.md`.

Run: `git ls-files -- ".agents/artifacts/specs/*-issue-155-instruction-load-report.md"`
Every path it prints other than `<report>` is superseded. The first time
through, that is attempt 1's `2026-09-26` report. Remove each one with
`git rm <path>`, then commit the removal alone:

```bash
git commit -m "docs(spec): retire the superseded #155 instruction-load report (D34)" -m "Its base is no longer the merge-base with origin/main after the sync, so the report is regenerated (#155 D19)." -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

Expected: the `git ls-files` command now prints nothing, or only `<report>`.
If it printed only `<report>` to begin with, there is nothing to retire. The
generation below then rewrites `<report>` in place.

Record two more values. `<base>` is what `git merge-base HEAD origin/main`
prints, and `<head>` is what `git rev-parse HEAD` prints.

Run: `just agent-instruction-load report --base <base> --head <head> --output <worktree>/<report>`
Expected: exit 0. `<report>` exists, and its first line is
`# Instruction load: <base[:7]> → <head[:7]>`.

```bash
git add <report>
git commit -m "docs(spec): record the #155 instruction-load report" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 5: Verify the report**

Run: `git show --name-only --format= HEAD`
Expected: exactly one line, `<report>`.

Run: `git diff --name-only <head> HEAD`
Expected: exactly one line, `<report>`. The report's head is its commit's
parent.

Run: `git ls-files -- ".agents/artifacts/specs/*-issue-155-instruction-load-report.md"`
Expected: exactly one line, `<report>`, whose base is `<sync>^2` (D34).

Run: `just agent-instruction-load report --base <base> --head <head> --output <scratch>/i155-regen.md`, then `cmp <scratch>/i155-regen.md <report>`
Expected: `cmp` prints nothing and exits 0. The committed report reproduces
byte for byte from its two SHAs (D17).

Run: `just agent-instruction-load report --base <base> --head <head> --format json --output <scratch>/i155-report.json`
Save this no-growth gate as `<scratch>/i155-no-growth.py` (D26):

```python
"""Scratch, outside the working tree: the #155 no-growth gate over the report JSON (D26)."""
import json
import sys
from pathlib import Path

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
report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
problems, shrank = [], 0
hosts = {profile["id"]: sorted(profile["hosts"]) for profile in report["profiles"]}
for profile_id, expected in ROSTER.items():
    if hosts.get(profile_id) != expected:
        problems.append(f"roster profile {profile_id}: hosts {hosts.get(profile_id)}, expected {expected}")
for profile in report["profiles"]:
    for host, totals in profile["hosts"].items():
        delta = totals["hot"]["delta"]["bytes"]
        if delta > 0:
            problems.append(f"{profile['id']} on {host}: hot grew by {delta} bytes")
        elif totals["hot"]["affected"] and delta == 0:
            problems.append(f"{profile['id']} on {host}: hot members changed but the total did not shrink")
        elif delta < 0:
            shrank += 1
if not shrank:
    problems.append("no hot total shrank")
print("\n".join(problems) if problems else f"no-growth gate: ok, {shrank} hot totals shrank")
raise SystemExit(1 if problems else 0)
```

Run: `python3 <scratch>/i155-no-growth.py <scratch>/i155-report.json`
Expected: exit 0 and `no-growth gate: ok, 24 hot totals shrank`. 24 is the
planning probe's count, before the sync and again with `origin/main` at
`17da7f2`. A later sync that moves a measured member can change it. Any other output is growth, or a changed hot total that did not shrink.
Stop with BLOCKED and those lines.

- [ ] **Step 6: Run the final gates**

The two suites and the installed run are long. Run each one as a background
command and read only the `FAIL:`/`ERROR:` lines and the final
`Ran`/`OK`/`FAILED` lines of its output.

Run: `env WORKFLOW_POLICY_SURFACE=source PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py home/common/agent-skills/tests/test_dispatch_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_instruction_load.py`
Expected: `OK (skipped=4)`. The skips are the `setUpClass` of
`InstalledOrchestrateRoutesTest`, `InstalledTreeContractsTest` and
`InstalledTreeSweepTest`, whose home is unset, plus
`test_installed_policy_surface_matches_source_contract`.

Run: `env WORKFLOW_POLICY_SURFACE=source just agent-workflow-tests`
Expected: `OK (skipped=4)`. The four skips are the `setUpClass` of
`InstalledOrchestrateRoutesTest`, `InstalledTreeContractsTest` and
`InstalledTreeSweepTest`, plus
`test_installed_policy_surface_matches_source_contract`. Before any sync, the
planning probe ran 1341 tests in about 13 minutes. The sync adds the tests
from #196 and #197, so the count is not asserted.

Run: `env PYTHONPATH=python python3 -m unittest home/common/agent-skills/tests/test_workflow_skill_contracts.py -k test_installed_policy_surface_matches_source_contract`
Expected: FAILED, and every failure is a `2 != 1` from
`assert_single_resolution_statement` over the installed roots. This is the
pre-activation record (D32). It is the one result the configured
`agent-workflow-tests` command, `just agent-workflow-tests` without the
variable, shows differently until the next `just switch`. The installed trees
keep the pre-E1 opener, and this plan never switches (D27). Any other failure
signature here is real, so stop with BLOCKED. Ship's Phase 2 runs that
configured command. There, this one test failing with this one signature,
beside a green source-surface run, is this recorded pre-activation lag, not
a regression. The ship owner notes it in the PR body with D32 and continues.
Any other failure is real.

Run: `just build`
Expected: exit 0. The build import-checks `agent_tools.instruction_load`.

Run: `env WORKFLOW_POLICY_SURFACE=source just agent-installed-skill-tests`
Expected: `OK (skipped=1)`. The one skip is
`test_installed_policy_surface_matches_source_contract`, with the reason
`explicit pre-activation source-only verification`. No line contains
`AGENT_SKILLS_INSTALLED_HOME is unset`, so every installed class ran (D27).

Run: `just agent-model-matrix`
Expected: `agent model matrix: valid`, followed by the representative trace.

A failure here needs a fix commit. When the fix changes a measured member,
the model or the matrix, repeat Steps 3–5 at the new head (D19).

- [ ] **Step 7: Scope and provenance checks (D15)**

Run: `git log --format=%H --grep=Recovered-From origin/main..HEAD`
Expected: no output.

Run: `git diff --name-only -S "env -u GITHUB_TOKEN" origin/main...HEAD -- . ":(exclude).agents/artifacts"`
Expected: no output. The exclusion is needed because the spec and this plan
name the string.

Run: `git diff --name-only -S ".claude/skills.config.json" origin/main...HEAD -- . ":(exclude).agents/artifacts"`
Expected: no output.

Run: `git diff --name-only origin/main...HEAD -- "*skill-prose-agent-error-fixes*"`
Expected: no output. None of the retained branch's spec, plan or task files
is added.

Run: `git diff --name-only origin/main...HEAD -- "*.nix" CLAUDE.md AGENTS.md .github .agents/instructions .agents/knowledge docs`
Expected: no output. There is no `.nix`, `CLAUDE.md`, ADR, context-doc or CI
change.

Run: `git rev-parse worktree-issue-99-skill-prose-fixes`
Expected: `3c9709ca470bd473d49b39a611ca6cab258973db`.

Run: `git status --short`
Expected: no output.

Decision IDs: D9, D10, D14, D15, D17, D19, D26, D27, D29, D30, D32, D34, D35.
