# Task 5: ship-release rewrites and the source sweep

Decisions: D1, D5, D7, D9, D10, D11, D12, D15, D20. Work from the worktree
root; paths are repo-relative (skill paths below are under
`home/common/agent-skills/skills/`). Lands recovered and adapted hunks — the
commit carries the `Recovered-From` trailer (root Global Constraints).

**Files:**
- Modify: `ship-release/SKILL.md`
- Modify: `ship-release/CHANGELOG.md`
- Modify: `home/common/agent-skills/tests/test_ship_release_contracts.py`
- Modify: `home/common/agent-skills/tests/test_shell_example_contracts.py`

**Interfaces:**
- Consumes (Task 2, `test_shell_example_contracts.py`): `refused_examples`,
  `swept_documents`, `SOURCE_TREES` (imported from the support module).
- Produces (in `test_shell_example_contracts.py`, Task 6 uses both):
  - `GUIDANCE_POINTER = "see worktrees/SKILL.md, ## Shell forms the isolation checker refuses"`
  - `findings_report(document: str, findings: tuple[Finding, ...]) -> str` —
    one line `"{document}:{line}: {form}: {first line of example}"` per finding,
    then `GUIDANCE_POINTER`
  - `SourceTreeSweepTest.test_no_living_example_teaches_a_refused_form`

**Invariants:**
- `swept_documents()` over both source trees yields no finding at the end of
  this task (spec AC2); the sweep has no allowlist (D9, D20).
- The two `unset GITHUB_TOKEN && ` spans in `ship-release/SKILL.md` (gh hygiene,
  Phase 4 grammar sentence) are unchanged (D5).
- The release PR keeps `--body-file` (D11); `EXISTING=$(…)` and the Phase 0
  `cd $(…)` stay (D8).
- `test_ship_release_contracts.py` still executes the skill's PREV_TAG command
  in a real repo and asserts exact equality with `v0.1.0` (D12).

- [ ] **Step 1: Write the failing sweep**

Add to `test_shell_example_contracts.py`, after `WorktreesGuidanceTest`:

```python
GUIDANCE_POINTER = "see worktrees/SKILL.md, ## Shell forms the isolation checker refuses"


def findings_report(document, findings):
    lines = [
        f"{document}:{f.line}: {f.form}: {f.example.splitlines()[0]}" for f in findings
    ]
    return "\n".join(lines + [GUIDANCE_POINTER])


class SourceTreeSweepTest(unittest.TestCase):
    def test_no_living_example_teaches_a_refused_form(self):
        for tree, relative in swept_documents():
            with self.subTest(document=f"{tree}:{relative}"):
                text = (SOURCE_TREES[tree] / relative).read_text(encoding="utf-8")
                findings = refused_examples(text)
                self.assertEqual(findings, (), findings_report(relative, findings))
```

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py`
Expected: FAIL — subtests for `shared:ship-release/SKILL.md` (13 findings
across its 11 offending examples: chain ×5, pipe ×4, redirect ×3, heredoc ×1,
per the spec's site table) and `shared:ship-release/CHANGELOG.md` (one
redirect); no other document fails. Any other failing document is a classifier bug or a
missed site: stop and report it.

- [ ] **Step 2: Update the PREV_TAG execution test (adapted, D12)**

In `test_ship_release_contracts.py`, `test_prev_tag_command_ignores_unreachable_tags_in_a_real_repo`:
- docstring: `"""Execute the skill's exact PREV_TAG command in a repo where a higher semver tag exists on an unmerged side branch. The command prints only PREV_TAG."""`
- the match becomes
  `re.search(r"^git for-each-ref --count=1 .*$", self.skill, re.M)` with the
  message `"PREV_TAG command missing from SKILL.md"`; keep
  `self.assertIn('--merged "$MERGE_SHA"', command)`;
- the fixture gains an older reachable tag, so the count and the ordering are
  tested too: directly after the first commit, before the existing
  `git tag -a v0.1.0 -m v0.1.0` line, add
  `sh("git tag -a v0.0.9 -m v0.0.9", repo)` — the same commit may carry both
  tags; the unreachable `v9.9.9` stays;
- the execution becomes
  `prev = sh(command, repo, extra_env={"MERGE_SHA": merge_sha})` followed by
  `self.assertEqual(prev, "v0.1.0")` — exactly one line, so dropping
  `--count=1` (two lines) or reversing the sort (`v0.0.9`) reds it (the
  repo-wide sanity block stays).

Run: `python3 -m unittest home/common/agent-skills/tests/test_ship_release_contracts.py`
Expected: FAIL — only this test (`PREV_TAG command missing from SKILL.md`).

- [ ] **Step 3: Re-apply the recovered hunks**

Read them with `git diff 95b6caf 3c9709ca -- home/common/agent-skills/skills/ship-release/SKILL.md home/common/agent-skills/skills/ship-release/CHANGELOG.md`
and apply by hand, verbatim, only these hunks:
- `CHANGELOG.md` single-branch `PREV` (drops `2>/dev/null`; no tag → non-zero exit, empty `PREV`, whole history).
- `SKILL.md` no-forge local merge (line ~30): "check out `<default>` and, only if that succeeded, `git merge --no-ff <integration>`".
- `SKILL.md` Phase 0 step 3 ahead check: "… `--pretty=oneline` output non-empty; each line is one merge. No output → nothing to release …".
- `SKILL.md` Phase 0 local ahead ("quoting its first 20 lines") and local behind ("`git checkout <integration>` and, only if that succeeded, `git merge --ff-only origin/<integration>`, then proceed").
- `SKILL.md` Phase 2: the preface sentence and `--body-file <release-body-path>` in place of the heredoc; in the preface write "is written to `<release-body-path>`, a path outside the working tree, with the file-writing tool".
- `SKILL.md` Phase 4 "Don't … and don't check out `<default>` to merge it locally" sentence.
- `SKILL.md` 4.5b: the two-call fence (`git remote get-url origin`, `git fetch --tags --quiet origin`, the `EXISTING=` line) and its sentence, with the condition worded "skip the fetch when the first command exits non-zero (no remote)".
- `SKILL.md` 4.5f: the fence and the "Between the two …" sentence, then append `rm <release-notes-path>` as the fence's last call and extend the sentence: "… with the file-writing tool — a path outside the working tree — then pass that path to the second, and remove it once the Release exists."
- `SKILL.md` 5d railway: the single-call fence and the "Read the five most recent entries …" paragraph.

Do **not** apply the retained `env -u GITHUB_TOKEN` gh-hygiene hunk (D5) or the
`.claude/skills.config.json` "if it exists" hunk (#100).

- [ ] **Step 4: Write the adapted sites**

1. Phase 0 step 3, the parenthesised single-branch case (adapted, D10): replace
   the retained "capture its status … `set -e` …" wording so the parenthesis
   reads:

   > (Single-branch case: `git describe --tags --abbrev=0 origin/<default>` prints the previous tag, which is `PREV`; a non-zero exit there means the repo has no tag yet — the first release — so `PREV` is empty, not a failed pre-flight. The explicit ref matters because bare `git describe` reads whatever HEAD the user parked on. Then check `git log ${PREV:+$PREV..}origin/<default> --oneline` is non-empty.)

2. 4.5c (adapted, D12): the fence becomes the single line

   ```bash
   git for-each-ref --count=1 --merged "$MERGE_SHA" --sort=-v:refname --format='%(refname:short)' 'refs/tags/v[0-9]*'
   ```

   and the paragraph after it starts: "Its one output line is `PREV_TAG`; no
   output at all is the bootstrap case." followed by the existing sentence
   beginning "`--merged "$MERGE_SHA"` restricts the search …" unchanged.

- [ ] **Step 5: Verify**

Run: `python3 -m unittest home/common/agent-skills/tests/test_shell_example_contracts.py home/common/agent-skills/tests/test_ship_release_contracts.py`
Expected: `OK`.

Run: `git grep -n -c -F "unset GITHUB_TOKEN && " -- home/common/agent-skills/skills/ship-release/SKILL.md`
Expected: `home/common/agent-skills/skills/ship-release/SKILL.md:2` (both
sanctioned spans kept).

Run: `just agent-workflow-tests`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add home/common/agent-skills/skills/ship-release home/common/agent-skills/tests/test_ship_release_contracts.py home/common/agent-skills/tests/test_shell_example_contracts.py
git commit
```

Message: `fix(agent-skills): teach ship-release shell forms the checker accepts`;
the body lists the recovered hunks (CHANGELOG `PREV`, local merge, ahead check,
local ahead/behind, Phase 2 `--body-file`, "don't" sentence, 4.5b tag fetch,
4.5f release notes, 5d railway) and the adapted ones (Phase 0 `PREV` per D10,
4.5c `for-each-ref` and its executed test per D12), names the source sweep as
new work, then the trailer paragraph with
`Recovered-From: 3c9709ca470bd473d49b39a611ca6cab258973db`.
