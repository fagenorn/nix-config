# Task 1: Whole-file review and triaged record

Spec § Solution steps 1–4 and 6 (the record's first four parts), § The reviewer brief, § Reviewer output, § Severity scale, § Dispositions, § The record; per D1–D5, D7 and D9. You act as the spec's "controller" for the review: you dispatch the five reviewers, check coverage, check and disposition the findings, and commit the record. You never fix a finding, and you never review the files yourself in place of a reviewer: if your host cannot launch an `Agent`, report BLOCKED `no subagent launch` (per D9).

**Files:**
- Create: `.agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md` (the record, `R` below)
- Scratch, not committed: `$W/issue-259-review/` holding each reviewer brief and report, where `W` is what `sdd-workspace .agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.md` prints

**Interfaces:**
- Consumes: `REVIEW_SHA` and the 25 paths (Global Constraints); `home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md` § What to Check; the spec's `### Severity scale (per D4)` bullets.
- Produces, for Tasks 2 and 3, the record in exactly this shape (Step 5): the header lines; `## Reviewer` bullets; `## Coverage` table `| # | Path | Blob | Lines | Read | Batch | Verdict |`; `## Findings` table `| ID | Severity | Location | Defect | Disposition | Evidence |` or the single line `None.`. A fix-bound row's Evidence is exactly `fix pending`; a row to file reads `issue pending (bar <k>)`, `k` in 1–6 (Step 4).

**Invariants:**
- The record names all 25 paths, in Git's order, each with its blob OID and `wc -l` count at `REVIEW_SHA`, read `whole`, by its batch's reviewer or that batch's one retry (per D1, D3).
- Every finding is anchored in one of the 25 and appears in exactly one Findings row; the IDs in the Verdict cells equal the IDs in the Findings rows.
- Severities are never lowered (per D4); dispositions come from the closed set (per D5); at most three rows are `fixed`; Minor rows are `recorded` with Evidence `—`.
- Nothing outside the record is committed.

## Batches (per D2)

- **B1** pack and publish: `python/agent_tools/review_pack.py`, `python/agent_tools/review_package.py`, `python/agent_tools/review_publish.py`, `python/agent_tools/review_actual.py`, `python/agent_tools/review_git.py`, `tests/test_review_pack.py`, `home/common/agent-skills/tests/test_review_package.py`
- **B2** projection and forecast: `python/agent_tools/review_projection.py`, `python/agent_tools/review_forecast.py`, `python/agent_tools/review_feasibility.py`, `python/agent_tools/review_budget.py`, `tests/test_review_feasibility.py`, `tests/test_review_projection_cases.py`, `tests/test_review_history.py`
- **B3** budget helper: `home/common/agent-skills/scripts/artifact_budget.py`, `home/common/agent-skills/tests/test_artifact_budget.py`
- **B4** wiring: `lib/agent-tools.nix`, `home/common/agent-skills/default.nix`, `justfile`, `CLAUDE.md`, `tests/test_agent_tools_launchers.py`
- **B5** SDD skill text: `home/common/agent-skills/skills/sdd/SKILL.md`, `home/common/agent-skills/skills/sdd/final-review.md`, `home/common/agent-skills/skills/sdd/fix-loop.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`

- [ ] **Step 1: Pin the tree (per D1)**

From the worktree root:

```bash
W=$(sdd-workspace .agents/artifacts/plans/2026-11-01-issue-259-core-correctness-review.md)
REVIEW_SHA=$(sed -n 's/^Delivery base: \([0-9a-f]\{40\}\)$/\1/p' "$W/progress.md")
M=93e6059a6fece769a621657c5889278b9cb9e0d7
git merge-base --is-ancestor "$REVIEW_SHA" HEAD
git diff --name-only "$M^1" "$M" | grep -v '^\.agents/artifacts/' > "$S/259-paths.txt"
test "$(wc -l < "$S/259-paths.txt" | tr -d ' ')" = 25
git diff --quiet "$REVIEW_SHA" HEAD -- $(cat "$S/259-paths.txt")
git log --no-merges --format='%(trailers:key=Co-Authored-By,valueonly)' "$M^1..$M^2" | sed '/^$/d' | sort | uniq -c
```

Expected: an empty `REVIEW_SHA` is NEEDS_CONTEXT; every other command exits 0; the tally prints `1 Claude Opus 5.5 <noreply@anthropic.com>`, `1 Codex <codex@openai.com>` and `12 Codex <noreply@openai.com>`. Any other result: report BLOCKED with the failing command. Make `mkdir -p "$W/issue-259-review"`.

- [ ] **Step 2: Write the five briefs and dispatch the reviewers (per D2)**

For each batch write `$W/issue-259-review/B<n>-brief.md` from this template, replacing `{BATCH}`, `{WORKTREE}` (the absolute worktree root), `{REVIEW_SHA}` (all 40 hex) and `{PATHS}` (the batch's paths, one per line, in the order above), and replacing `{SEVERITY}` with the three bullets under the spec's `### Severity scale (per D4)`, verbatim:

````text
You are a fresh, read-only correctness reviewer: batch {BATCH} of a whole-file correctness review of CORE, the review-packing tooling of the repository at {WORKTREE}. You did not write this code. Review it for CORRECTNESS: is it built right?

REVIEW_SHA: {REVIEW_SHA}. The worktree copies of the files below are byte-identical to REVIEW_SHA (checked before dispatch); read them in the worktree.

## Files: read every line of each, whole

{PATHS}

## Rubric

Apply the bullets under "## What to Check" in home/common/agent-skills/skills/sdd/correctness-reviewer-prompt.md to these whole files. That prompt's diff, manifest, scoping and output instructions do not apply; this brief replaces them. "Cross-task integration" here means interfaces that one CORE module defines and another uses. The CORE modules are review_pack.py, review_package.py, review_publish.py, review_actual.py, review_git.py, review_projection.py, review_forecast.py, review_feasibility.py and review_budget.py under python/agent_tools/, and home/common/agent-skills/scripts/artifact_budget.py.

Standards: ~/.agents/standards/the-bar.md, ~/.agents/standards/stacks/python.md and docs/standards/agent-helpers.md. Documented contract: the section "## Review packaging and feasibility" of python/README.md.

For a prose file (skill text, CLAUDE.md, a justfile recipe or comment), a defect is a claim that is false against the code or another binding text, or an instruction an agent cannot follow as written.

Anchor every finding in one of the files above. You may read any other file as evidence, but a defect that lies wholly outside these files is not part of this review.

Known, do not report: CR-001 to CR-003, fixed in 6cdb9b9 (review_projection proves a completed deletion in the candidate's own tree; review_forecast lists plan members with ls-tree -z and opens the final input component non-blocking); and the topic of https://github.com/fagenorn/nix-config/issues/255 (Git attributes and diff settings that change CORE's record view).

Do not open CORE's design spec, plan or PR thread, except to settle whether one specific suspected defect contradicts the documented intent; name each such check in the finding it settles.

You are read-only: never edit a file and never fix a finding; never mutate the working tree, the index, HEAD or a branch. Bash runs only read-only git inspection (git show, git rev-parse, git cat-file, git log, git grep), wc, and at most one focused test per specific doubt, as PYTHONPATH="$PWD/python" python3 -m unittest -v <test file> -k <test name> from the worktree root.

## Severity

{SEVERITY}

## Output

Your FIRST line is exactly `**Correctness:** Clean — <1–2 sentence assessment>.` or `**Correctness:** Findings — <1–2 sentence assessment>.`
Then exactly these three sections, in this order: `### Critical (Must Fix)`, `### Important (Should Fix)`, `### Minor`. Each finding is one bullet, `- <ID> — <path>:<line> — <the defect and its failure scenario> — confidence <high|medium|low> — unknowns <text|none>`, with IDs C1, C2, … under Critical, I1, I2, … under Important and M1, M2, … under Minor. Write `None.` under an empty section. These three sections total at most 400 words, with no preamble and no closing summary.
Then `### Coverage`: one line per file above, in the listed order, `<path> | <blob OID> | <line count> | read whole`, where the OID is what `git rev-parse {REVIEW_SHA}:<path>` prints and the count is what `git cat-file -p {REVIEW_SHA}:<path> | wc -l` prints. Write a file's line only if you read every line of it. Then a last line `Reviewer model: <your model ID>`. Coverage lines do not count toward the 400 words.

Launch any subagent by type only, never by name: a subagent cannot spawn a named teammate, and a named launch returns an error instead of work. Read an existing file before writing to it: overwriting content you have not read destroys work you cannot see. Run each long command, every verification command included, in the foreground with an explicit timeout above its expected duration. If the host moves one to the background anyway, wait for it in the same turn: never end your turn while a command or agent you started still runs. Never loop `sleep` in the foreground or chain a check onto it: use Monitor with an until-condition, or one short bare `sleep N` call and check in the next.
````

Dispatch all five in one message, by type, with no `name`: `Agent(subagent_type="reviewer", model="opus", effort="high", description="CORE review B<n>", prompt="Read the review brief at <absolute brief path> and follow it exactly.")`. Wait for all five within your turn. Save each final message verbatim to `$W/issue-259-review/B<n>-report.md` and note the agent ID the host returns for each.

- [ ] **Step 3: Check coverage; retry once (per D3)**

For each batch run (timeout 300 s):

```bash
python3 -I - "$REVIEW_SHA" "$W/issue-259-review/B<n>-report.md" <the batch's paths> <<'EOF'
import re, subprocess, sys
sha, report, paths = sys.argv[1], sys.argv[2], sys.argv[3:]
text = open(report, encoding="utf-8").read().strip().splitlines()
heads = [l for l in text if l.startswith("### ")]
ok = (bool(text) and re.fullmatch(r"\*\*Correctness:\*\* (Clean|Findings) — .+", text[0]) is not None
      and heads == ["### Critical (Must Fix)", "### Important (Should Fix)", "### Minor", "### Coverage"]
      and text[-1].startswith("Reviewer model: "))
lines = {}
if ok:
    for l in text[text.index("### Coverage") + 1:-1]:
        parts = [p.strip() for p in l.split("|")]
        if len(parts) == 4:
            lines[parts[0]] = parts[1:]
missed = []
for p in paths:
    oid = subprocess.run(["git", "rev-parse", f"{sha}:{p}"], check=True, capture_output=True, text=True).stdout.strip()
    count = subprocess.run(["git", "cat-file", "-p", f"{sha}:{p}"], check=True, capture_output=True).stdout.count(b"\n")
    if not ok or lines.get(p) != [oid, str(count), "read whole"]:
        missed.append(p)
print("well-formed:", ok, "| missed:", " ".join(missed) or "none")
sys.exit(1 if missed else 0)
EOF
```

Expected: exit 0, `missed: none`. For a batch that prints missed paths, write `B<n>R-brief.md` from the same template with `{BATCH}` = `B<n>R` and `{PATHS}` = only the missed paths, dispatch one fresh reviewer the same way, save `B<n>R-report.md`, and run the check on it with the missed paths. A path missed again: report BLOCKED `coverage failed twice: <paths>`; this fails the attempt (per D3), so dispatch nothing more. Keep every finding from every report, retries included.

- [ ] **Step 4: Check and disposition every finding (per D4, D5, D9)**

1. Give each finding the ID `<batch>-<reviewer ID>` (`B2-I1`, `B4R-C1`). A finding whose location lies outside the 25 is not a finding of this review (per D1): name it in your report file only.
2. Merge duplicates: findings naming the same defect become one row whose ID cell lists every ID, comma-separated, with the highest of their severities and the first one's location (per D4, D9).
3. Minor: `recorded`, Evidence `—`.
4. Each Critical or Important row, in table order (Critical first): read the cited lines at `REVIEW_SHA` (`git show "$REVIEW_SHA:<path>"`) and settle whether the failure scenario holds, with at most one focused probe under `$S` (a Focused test, or `python -m agent_tools.<module>` against a temporary Git repository). Then the first rule that applies:
   - It restates CR-001, CR-002 or CR-003: run (timeout 900 s) `launch-scope exec … -- bash -c 'PYTHONPATH="$PWD/python" python3 -m unittest -v tests.test_review_feasibility.SourceProjectionTest.test_validate_result_refuses_fifo_input_without_blocking tests.test_review_feasibility.NonAsciiPlanTest.test_non_ascii_plan_members_match_complete_index tests.test_review_feasibility.ReconstructionTest.test_recommendation_proves_completed_deletion_in_candidate_tree'`. On `OK`: `rejected`, Evidence `restates CR-00<k>; <test ID> OK at <REVIEW_SHA 8 hex>`. On a failure it is a new finding: continue below.
   - The defect does not exist at `REVIEW_SHA`: `rejected`, Evidence the check you ran and what it showed, in one sentence.
   - It is the topic of 255: `tracked`, Evidence `https://github.com/fagenorn/nix-config/issues/255`.
   - `gh issue list --repo fagenorn/nix-config --state open --search "<2–4 distinctive words of the defect>" --json number,title,url --limit 20` finds an open issue that already names this defect: `tracked`, Evidence its URL.
   - Otherwise the fix-here bar, items in order; the first item that fails gives `filed`, Evidence `issue pending (bar <k>)`; all hold gives `fixed`, Evidence `fix pending`: (1) apart from its regression test the fix stays inside the 25 files; (2) it meets the documented contract without changing it — argv, exit codes, report or manifest schema, persisted package format, and no `python/README.md` edit; (3) it needs no instruction-budget raise (it adds no net text under `home/common/agent-skills/skills/`); (4) it is at most 150 changed lines, test included, by your estimate; (5) fewer than three rows are already `fixed`; (6) its regression test fits a plan Test seam (prose only where a tool or subagent consumes it; a weak test by Task 2's mutant route).
5. Order the table Critical, Important, Minor; within a severity by batch, then reviewer ID.

- [ ] **Step 5: Write the record (per D7)**

Write `R` exactly so, replacing each `<…>`; a cell's `|` is written `\|`:

````markdown
# CORE correctness review record — issue 259

Issue: https://github.com/fagenorn/nix-config/issues/259
Subject: https://github.com/fagenorn/nix-config/pull/246, merge `93e6059a6fece769a621657c5889278b9cb9e0d7`
REVIEW_SHA: `<40 hex>`
Scope: full — 25 of 25 product files, each read whole

## Reviewer

- Agent type: `reviewer`, dispatched by type, read-only (Read, Glob, Grep, Bash, Skill).
- Model: `<each distinct Reviewer model value, comma-separated>`; effort: high.
- Sessions: B1 `<agent ID>`, B2 `<agent ID>`, B3 `<agent ID>`, B4 `<agent ID>`, B5 `<agent ID>`<, B<n>R `<agent ID>` (`<path>`, …) per retry>.
- Independence: PR 246's 14 non-merge commits carry the Co-Authored-By trailers Codex ×13 and Claude Opus 5.5 ×1 (`6cdb9b9`, the shipping session's fix of CR-001 to CR-003), counted with `git log --no-merges --format='%(trailers:key=Co-Authored-By,valueonly)' 93e6059a^1..93e6059a^2`. The reviewers are a different model family from Codex, and each was a fresh session given none of PR 246's spec, plan or PR thread; none edited a file.
- Spec consultations: <`none`, or per batch the suspected defect each reviewer checked against the CORE spec>.

## Coverage

| # | Path | Blob | Lines | Read | Batch | Verdict |
|---|---|---|---|---|---|---|
| 1 | `<path>` | `<blob OID>` | <count> | whole | <B1–B5, or B<n>R for a retried path> | <clean, or the IDs of the findings anchored in this file, comma-separated> |
````

with rows 1–25 in `$S/259-paths.txt` order, then:

````markdown
## Findings

| ID | Severity | Location | Defect | Disposition | Evidence |
|---|---|---|---|---|---|
| <IDs> | <Critical\|Important\|Minor> | `<path>:<line>` | <the defect and its failure scenario, one or two sentences> | <disposition> | <Evidence per Step 4> |
````

or, with no finding at all, `## Findings`, a blank line and `None.`. There is no `## Verification` yet (Task 3 adds it).

- [ ] **Step 6: Verify the record**

Run (timeout 300 s) with `R` and `REVIEW_SHA` set as above:

```bash
python3 -I - "$R" "$REVIEW_SHA" <<'EOF'
import re, subprocess, sys
record, sha = sys.argv[1], sys.argv[2]
MERGE = "93e6059a6fece769a621657c5889278b9cb9e0d7"
BATCHES = {
    "B1": ["python/agent_tools/review_pack.py", "python/agent_tools/review_package.py", "python/agent_tools/review_publish.py", "python/agent_tools/review_actual.py", "python/agent_tools/review_git.py", "tests/test_review_pack.py", "home/common/agent-skills/tests/test_review_package.py"],
    "B2": ["python/agent_tools/review_projection.py", "python/agent_tools/review_forecast.py", "python/agent_tools/review_feasibility.py", "python/agent_tools/review_budget.py", "tests/test_review_feasibility.py", "tests/test_review_projection_cases.py", "tests/test_review_history.py"],
    "B3": ["home/common/agent-skills/scripts/artifact_budget.py", "home/common/agent-skills/tests/test_artifact_budget.py"],
    "B4": ["lib/agent-tools.nix", "home/common/agent-skills/default.nix", "justfile", "CLAUDE.md", "tests/test_agent_tools_launchers.py"],
    "B5": ["home/common/agent-skills/skills/sdd/SKILL.md", "home/common/agent-skills/skills/sdd/final-review.md", "home/common/agent-skills/skills/sdd/fix-loop.md", "home/common/agent-skills/tests/test_workflow_skill_contracts.py"],
}
BATCH = {p: b for b, ps in BATCHES.items() for p in ps}
def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True).stdout
expected = [p for p in git("diff", "--name-only", MERGE + "^1", MERGE).decode().splitlines()
            if not p.startswith(".agents/artifacts/")]
assert sorted(expected) == sorted(BATCH), "batch map differs from Git's 25"
lines = open(record, encoding="utf-8").read().splitlines()
assert lines[0] == "# CORE correctness review record — issue 259", lines[0]
assert [l for l in lines if l.startswith("## ")] == ["## Reviewer", "## Coverage", "## Findings"]
header = lines[:lines.index("## Reviewer")]
for want in ("Issue: https://github.com/fagenorn/nix-config/issues/259",
             f"Subject: https://github.com/fagenorn/nix-config/pull/246, merge `{MERGE}`",
             f"REVIEW_SHA: `{sha}`", "Scope: full — 25 of 25 product files, each read whole"):
    assert want in header, want
def section(name):
    start = lines.index(name) + 1
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return [l for l in lines[start:end] if l.strip()]
def cells(line):
    return [c.strip() for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
for prefix in ("- Agent type: `reviewer`", "- Model: `", "- Sessions: B1 `",
               "- Independence: PR 246's 14 non-merge commits carry the Co-Authored-By trailers Codex ×13 and Claude Opus 5.5 ×1",
               "- Spec consultations: "):
    assert any(l.startswith(prefix) for l in section("## Reviewer")), prefix
ID = re.compile(r"B[1-5]R?-[CIM][0-9]+")
cov = section("## Coverage")
assert cov[0] == "| # | Path | Blob | Lines | Read | Batch | Verdict |", cov[0]
rows = [cells(l) for l in cov[2:]]
assert [r[1].strip("`") for r in rows] == expected, "coverage paths or order differ from Git"
assert [r[0] for r in rows] == [str(i) for i in range(1, 26)]
listed = set()
for _, path, blob, count, read, batch, verdict in rows:
    p = path.strip("`")
    assert blob.strip("`") == git("rev-parse", f"{sha}:{p}").decode().strip(), p
    assert count == str(git("cat-file", "-p", f"{sha}:{p}").count(b"\n")), p
    assert read == "whole" and batch in (BATCH[p], BATCH[p] + "R"), p
    if verdict != "clean":
        ids = [i.strip() for i in verdict.split(",")]
        assert all(ID.fullmatch(i) for i in ids), verdict
        listed.update(ids)
found = section("## Findings")
assert found == ["None."] or found[0] == "| ID | Severity | Location | Defect | Disposition | Evidence |", found[0]
frows = [] if found == ["None."] else [cells(l) for l in found[2:]]
seen, fixed, rank = set(), 0, {"Critical": 0, "Important": 1, "Minor": 2}
for ids, sev, loc, defect, disp, ev in frows:
    idl = [i.strip() for i in ids.split(",")]
    assert all(ID.fullmatch(i) for i in idl) and not seen & set(idl), ids
    seen.update(idl)
    path, _, line = loc.strip("`").rpartition(":")
    assert sev in rank and defect and path in BATCH and re.fullmatch(r"[0-9]+(-[0-9]+)?", line), ids
    if sev == "Minor":
        assert disp == "recorded" and ev == "—", ids
    elif disp == "fixed":
        fixed += 1
        assert ev == "fix pending", ids
    elif disp == "filed":
        assert re.fullmatch(r"issue pending \(bar [1-6]\)", ev), ids
    elif disp == "tracked":
        assert re.fullmatch(r"https://github\.com/fagenorn/nix-config/issues/[0-9]+", ev), ids
    else:
        assert disp == "rejected" and ev not in ("", "—"), ids
assert fixed <= 3, fixed
assert [rank[r[1]] for r in frows] == sorted(rank[r[1]] for r in frows), "severity order"
assert seen == listed, f"Verdict and Findings IDs differ: {sorted(seen ^ listed)}"
print(f"record ok: 25 coverage rows, {len(frows)} finding rows, {fixed} fix-bound")
EOF
```

Expected: exit 0 and `record ok: …`. Before Step 5 it fails, because `R` does not exist.

- [ ] **Step 7: Commit**

```bash
git add .agents/artifacts/specs/2026-11-01-issue-259-core-correctness-review-record.md
launch-commit … -- -m "docs(issue-259): record the full-scope CORE correctness review" -m "<session trailers>"
git diff --name-only HEAD^ HEAD
```

Expected: the last command prints only the record's path. Your report file lists every finding's check (what you read or ran, and the result), each out-of-scope finding, and the five or more agent IDs.
