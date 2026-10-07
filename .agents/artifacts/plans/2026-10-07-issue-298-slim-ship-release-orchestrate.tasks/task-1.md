# Task 1: Cut ship-release SKILL.md

**Files** (under `home/common/agent-skills/`):
- Modify: `skills/ship-release/SKILL.md`
- Modify: `skill-lint-debt.json`, `instruction-load.json` (via `tighten` only)
- Test: `tests/test_ship_release_contracts.py`

**Interfaces:**
- Consumes: the base tree at `75784bed116805ee948d6e2f7f45a6d0ad3b4212`. `CHANGELOG.md` is untouched here (Task 2 owns it).
- Produces: a `SKILL.md` of ≤ 20,500 B and ≤ 380 reflowed body lines (500 is the hard limit), with no `## The flow` section and the description below. The `L2 home/common/agent-skills/skills/ship-release/SKILL.md` debt key is gone. Task 2 relies on this file's size for the combined ≤ 29,890 B line.

**Invariants:**
- Byte for byte, from base (the Step 6 script checks each):
  - frontmatter lines `name:` and `argument-hint:`;
  - the marker line `<!-- agent-dispatch: id=ship-release-owner role=ship-owner model=opus effort=high -->` and the `Agent(...)` line after it (base lines 16–17);
  - the resolve paragraph (base line 24, starting "Run `resolve-project resolve --repo-root <checkout>`");
  - every fenced block of the base file except the `## The flow` diagram fence, which goes (per D7);
  - every inline command span the shell-example sweep vets, including `git rev-parse --git-common-dir`, the `cd $(git -C …)` span, `git status --porcelain`, the Phase 0 `${GH_PREFIX}gh pr list …` and `gh run list …` spans, `git describe --tags --abbrev=0 origin/<default>`, `git tag --points-at "$MERGE_SHA"` and the `gh api repos/<resolved-repository>/commits/$MERGE_SHA/check-runs` span.
- Description is exactly: `Releases the integration branch to the default branch — changelog, release PR, CI, merge, semver tag + GitHub Release, deploy watch. Use for "release", "ship to prod", "deploy".` (per D8).
- These headings keep their text (per D4): `## Ownership`, `## Project bindings (resolve first)`, `## Durable release state`, `## Standing authorization`, `## Doc-grounded escalations`, `## gh hygiene`, every `## Phase <n> — …`, every `### 4.5a.`–`### 4.5g.` and `### 5a.`–`### 5e.` heading. `### 4.5d. Decide MAJOR / MINOR / PATCH` and the link `CHANGELOG.md#version-bump-signals` stay exactly.
- `## Notes` is removed and its four bullets get one home each: the release-publishing authorization and the commit-trailer rule move into `## Standing authorization`; "a failed release's tag stays; fix with a hotfix `ship-issue` and a new PATCH release; never delete tags" moves to `## Phase 6 — Report` as one line; "invoked with no argument, the Phase 1 synthesis is the scope hint" joins the Phase 2 title-pattern paragraph.
- Pause conditions keep their meaning and their one list: Phase 0 failures, a CI check finishing `FAILURE`/`CANCELLED`/`TIMED_OUT`, a deployment finishing `FAILED`, genuinely new risks. The Phase 3 40-minute escalation prompt, the 4.5b "already exists" prompt, the 4.5c bootstrap `v0.1.0` proposal (never silently `v1.0.0`) and the 4.5d one-round override stay.
- Resume paths keep their meaning: every Phase 0 step-0 jump (to 4.5, 4.5f, Phase 5, stale record), the open-PR resume at Phase 3 or 4, and the durable-state write list per phase.
- The D5 guard clauses stay, one clause each: `targetCommitish` holds a branch name (4.5b); `--merged` excludes unmerged tags (4.5c); the no-PR path tags the local `<default>` (4.5a); a health 200 is not proof (Phase 5, said once); a shell variable does not survive between calls (Phase 0 step 3).
- The three findings in the spec's `### Findings to file` (state read before the checkout check, forge calls without `--repo`, the wake prompt's `/ship-release <pr-num>`) are left exactly as they behave now (per D11).

- [ ] **Step 1: Remove the L2 debt key first (the lint fails until Step 4)**

Delete `"L2 home/common/agent-skills/skills/ship-release/SKILL.md",` from `skill-lint-debt.json` (per D2).

- [ ] **Step 2: Watch the gate fail**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check` (timeout 300 s)
Expected: non-zero exit with the line `L2 home/common/agent-skills/skills/ship-release/SKILL.md: body is 558 reflowed lines, over 500` (or the same rule worded by the linter).

- [ ] **Step 3: Re-point the durable-state slice (per D7)**

In `tests/test_ship_release_contracts.py`, `test_durable_state_names_every_field` ends its slice at `"## Phase 0 — Pre-flight"` instead of `"## The flow"`. Nothing else in that file changes: every other method there reads only commands, state keys, anchors or eval shape.

```python
    def test_durable_state_names_every_field(self):
        state_section = self.section(
            self.skill, "## Durable release state", "## Phase 0 — Pre-flight"
        )
        for field in ("headSha", '"pr"', "prUrl", "mergeSha", "tag", "releaseUrl", "deployState"):
            self.assertIn(field, state_section)
```

- [ ] **Step 4: Cut by content class (spec § Content classes)**

Work top to bottom. Cut a sentence only when a helper enforces it, another section holds it, it is rationale, or it is self-evident. Keep or report anything that would change behaviour if read literally.
1. Frontmatter: replace only the description (Invariants).
2. Preface: one sentence naming the unit of work (all merges on the integration branch since the last default-branch merge).
3. `## Ownership`: the marker and call line, then one line: a direct invocation keeps the current session as owner; never split release ownership.
4. `## Project bindings`: the resolve paragraph unchanged. Keep the identical-branch route, the tracker binding rule with "never derive a repository value from Git or configuration", and the tracker-free route, trimmed of restatement.
5. `## Durable release state`: keep the path and `.gitignore` rule, the JSON fence, the atomic-write rule and per-phase field list, "Phase 0 reads it first and re-enters at the first null field", and "Phase 6 deletes it; a present file means an unfinished release". Cut the crash-survival rationale.
6. Delete `## The flow` and its fence (per D7).
7. `## Standing authorization`: the authorization chain, the publishing authorization from Notes (`git tag -a`, `git push origin v*`, `gh release create`; it does not extend to pushing `<default>` or `<integration>`), the commit-trailer rule (`bindings.vcs.commit.co_authored_by`), and the pause list once.
8. `## Doc-grounded escalations`: the invoke rule and one clause that platform specifics (silent rollback, latest vs built commit, stale `FAILED`) come from the declared documents.
9. `## gh hygiene`: the `GH_PREFIX` assembly with its `unset GITHUB_TOKEN && ` example, "an empty list yields no prefix", and the `glab` verb translation. Cut the wrong-org-token story.
10. Phase 0: keep every command and decision. Cut "This step is first because…", "Common cause: …", "Any failure: … Don't paper over" becomes "Any failure: ground, then surface." Step 3's single-branch text keeps the explicit-ref rule, the first-release reading of a non-zero `git describe`, and the D5 shell-variable clause, each as one clause.
11. Phase 1: keep the instruction to read `CHANGELOG.md` first, the two outputs, the merge-count and deploy-expectations surfacing, and "do not create a tracked `CHANGELOG.md`" as one line. Cut the "flat merge-list shape this skill moved away from" sentence.
12. Phase 2: keep the body-path sentence and its `worktrees/SKILL.md`, `## Shell forms the isolation checker refuses` citation, the fence, the title pattern with the scope-hint rule (plus the Notes no-argument rule), and "persist `pr` + `prUrl`". Cut "Capture the PR number…".
13. Phase 3: keep the `headRefOid` fence and the drift rule (surface it; prefer finishing on the older tip). Keep "one Bash call, 300 s timeout, foreground; never background it (`run_in_background`, `Monitor`)" as the rule, without its keep-alive explanation. Keep "no improvised polling" as one line and the three exit-code bullets with the 8-retry bound and the escalation prompt verbatim.
14. Phase 4: keep the merge fence and "spell it exactly like that, on one line". Replace the guard-grammar paragraph with one sentence: the `PreToolUse` lifecycle guard adjudicates it as its release arm; act on its refusal (per D6). Keep the forbidden subject characters (`"`, `$`, backtick, backslash, newline) as one line. Keep "no `--delete-branch`" and "no `--no-ff`" as one line each, the `--subject` mirroring rule, the verify-and-persist-`mergeSha`-before-anything-else step, and `git fetch origin` without pushing or checking out `<default>`.
15. Phase 4.5: keep the no-opt-out rule and the unsupported-tracker clause, and the rubric pointer to `CHANGELOG.md#version-bump-signals`. In 4.5a–4.5g keep every fence, "run exactly ONE of these", the fetch-is-conditional rule, the D5 clauses, the skip and bootstrap rules, "persist `tag` as soon as `git tag` succeeds", the between-the-two-commands file instruction, the single-branch body rule, "skip `--prerelease` and `--draft`", the 4.5g checks, and "surface a failed `gh release create`; do not continue to Phase 5". Cut the operator-anchor story, "why annotated", "why `--notes-file`" and "why `MERGE_SHA` not `HEAD`".
16. Phase 5: keep the `deploy.adapter == none` skip with `deployState: none`, the `watching`/`done` writes, the invariant once as a plain sentence (running commit starts with `MERGE_SHA`, branch `<default>`, terminal SUCCESS; a health 200 is not proof). 5a–5e: keep each rule. Keep silent rollback once, in the 5c failure list. Keep the ~180 s cadence, the three-cycle wait, the 10-minute no-redeploy path with its confirm-first forced deploy, the stale-`FAILED` chronology check, the adapter contract, the railway fence and its field-reading sentence, the unrecognised-adapter stop, and the 5e wake prompt as it is.
17. Phase 6: keep the report fence, "do not keep polling", the failed-release-tag line from Notes, and "delete the state file after the report".
18. Delete `## Notes`.

- [ ] **Step 5: Models**

Run `just agent-instruction-load tighten` (timeout 300 s).

- [ ] **Step 6: Verify**

Run: `PYTHONPATH=python python3 -m agent_tools.skill_lint check`. Expected: exit 0.
Run the focused suite (Global Constraints). Expected: OK.
Run: `PYTHONPATH=python python3 -m agent_tools.instruction_load check`. Expected: `check: pass`.
Run:

```bash
set -euo pipefail
PYTHONPATH=python python3 - <<'EOF'
import subprocess
from pathlib import Path
from agent_tools import skill_lint
BASE = "75784bed116805ee948d6e2f7f45a6d0ad3b4212"
PATH = "home/common/agent-skills/skills/ship-release/SKILL.md"
base = subprocess.run(["git", "show", f"{BASE}:{PATH}"], capture_output=True, text=True, check=True).stdout
text = Path(PATH).read_text(encoding="utf-8")
def fences(t):
    out, cur = [], None
    for line in t.splitlines(keepends=True):
        if cur is None:
            if line.startswith("```"):
                cur = [line]
        else:
            cur.append(line)
            if line.startswith("```"):
                out.append("".join(cur)); cur = None
    return out
for block in fences(base):
    if block.startswith("```\n0. Pre-flight"):
        assert block not in text, "the flow fence survives (D7)"
        continue
    assert block in text, "fence changed: " + block.splitlines()[1]
lines = base.splitlines(keepends=True)
for lo, hi in ((2, 2), (4, 4), (16, 17), (24, 24)):
    assert "".join(lines[lo - 1:hi]) in text, f"base lines {lo}-{hi} changed"
front, body = skill_lint.parse_frontmatter(text)
assert front["description"] == ('Releases the integration branch to the default branch — changelog, '
    'release PR, CI, merge, semver tag + GitHub Release, deploy watch. '
    'Use for "release", "ship to prod", "deploy".'), "description"
for heading in ("## Durable release state", "### 4.5d. Decide MAJOR / MINOR / PATCH",
                "CHANGELOG.md#version-bump-signals", "## Shell forms the isolation checker refuses"):
    assert heading in text, heading
for gone in ("## The flow", "## Notes", "This step is first because",
             "The 5-minute ceiling forces an assistant turn"):
    assert gone not in text, gone
assert text.count("Agent(") == 1, "unmarked Agent( line"
reflowed = skill_lint.reflowed_lines(body)
size = len(text.encode("utf-8"))
print(f"SKILL.md body {reflowed} reflowed lines, {size} bytes")
assert reflowed <= 500, "over the L2 limit"
if reflowed > 380 or size > 20500:
    print("over target (name it in the commit body)")
EOF
if grep -q 'ship-release/SKILL.md' home/common/agent-skills/skill-lint-debt.json; then exit 1; fi
```

Expected: exit 0. At the base it fails first on `the flow fence survives (D7)`, and then on the description and the 558-line body.

- [ ] **Step 7: Commit**

Commit `skills/ship-release/SKILL.md`, `tests/test_ship_release_contracts.py`, `skill-lint-debt.json` and `instruction-load.json` as `refactor(ship-release): cut SKILL.md to what the owner acts on (#298)`.
