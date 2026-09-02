# Task 1: #60 — cross-agent project surfaces

**Files:**
- Create: `.claude/specs/2026-08-20-cross-agent-project-surfaces-research.md`
- Test: none — this repository has no test suite for documentation. The task's
  gate is the shell block in Step 2/Step 4, run from the worktree root.

**Interfaces:**

- Consumes: the spec
  `.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md` —
  its `## Document contract`, its `### .claude/specs/2026-08-20-cross-agent-project-surfaces-research.md (#60)`
  coverage table (claims `C60.1`–`C60.5`), and rows D1–D5, D8, D9, D12, D13,
  D17. The plan root's `## Global Constraints` and its canonical section names.
- Produces: the canonical document shape every later task reuses — the ordered
  headings `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, body
  sections, and `## What this document does not decide` last; the four-column
  coverage table whose fourth column is the verbatim text of a `##`/`###`
  heading in the same document; and the two required front-matter literals
  `**Durability: committed**` and
  ``Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked``.

**Invariants:**

- The file path is exactly the path #60's resolution comment links. Nothing
  renames it; the `2026-08-20` prefix is #60's decision date, not the
  authorship date.
- No sentence claims or implies that this document restores the 2026-08-20
  original. `## Provenance` states in plain words that this is a re-derivation
  authored 2026-09-02 under issue #115, that the original was never committed to
  any git ref and is unrecoverable, and that no claim here may be cited as
  evidence of what the original said (per D1).
- Every cell verdict and every axis answer names its primary source in the
  spec's citation form (per D3). An inherited summary claim not re-verified
  against a primary source appears inline as such **and** in
  `## Unverified inheritance`.
- Every observation is labelled with the scope it was observed at — project
  scope or user scope — and any generalisation from user-scope installed
  behaviour to project scope is stated as an inference carrying its own evidence
  level (per D9). The in-tree modules `home/common/agent-guidance/`,
  `home/common/agent-skills/`, `home/common/claude-code/` and
  `lib/agent-plugins.nix` are user-scope sources.
- `C60.4` is discharged by covering **both** readings of "prototype" — a
  projection prototype and #79's adoption dry run — and by recording the
  ambiguity in `## Unverified inheritance`. Never pick one reading (per D13).
- `C60.5` holds: options are recorded, never ranked into a decision. The
  document ends with `## What this document does not decide`.
- Length is governed by the-bar's *Token economy*; `artifact-budget` is never
  run against this file (per D8).

- [ ] **Step 1: Write the gate first, before the document**

Save this to `"${TMPDIR:-/tmp}/gate-60.sh"`. It is the task's contract.

```bash
#!/usr/bin/env bash
set -uo pipefail
DOC=".claude/specs/2026-08-20-cross-agent-project-surfaces-research.md"
fail=0
say() { echo "FAIL: $*"; fail=1; }

test -f "$DOC" || { echo "FAIL: $DOC does not exist"; exit 1; }

# Required front-matter and structural literals.
while IFS= read -r lit; do
  grep -qF -- "$lit" "$DOC" || say "missing literal: $lit"
done <<'LITS'
**Durability: committed**
## Provenance
re-derivation
2026-09-02
issue #115
never committed
unrecoverable
Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked
## Research question
## Coverage of the resolution summary
## Unverified inheritance
## What this document does not decide
project scope
user scope
LITS

# Heading order: the five canonical headings appear, in this order, and
# "What this document does not decide" is the last `##` heading in the file.
order=$(grep -n '^## ' "$DOC" | sed 's/^[0-9]*://')
expected=$'## Provenance\n## Research question\n## Coverage of the resolution summary\n## Unverified inheritance'
printf '%s\n' "$order" | head -4 | diff -q - <(printf '%s\n' "$expected") >/dev/null \
  || say "the first four ## headings are not the canonical four, in order"
[ "$(printf '%s\n' "$order" | tail -1)" = "## What this document does not decide" ] \
  || say "the last ## heading is not 'What this document does not decide'"

# Coverage table: every claim ID present, tagged, four columns, and its
# discharging heading really exists in this document.
cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^## /{f=0} f' "$DOC")
heads=$(grep -E '^#{2,4} ' "$DOC" | sed -E 's/^#{2,4} //')
for id in C60.1 C60.2 C60.3 C60.4 C60.5; do
  row=$(printf '%s\n' "$cov" | grep -F -- "$id " | head -1)
  [ -n "$row" ] || { say "claim $id absent from the coverage table"; continue; }
  n=$(printf '%s\n' "$row" | awk -F'|' '{print NF}')
  [ "$n" -ge 6 ] || say "$id row does not have four columns"
  printf '%s\n' "$row" | grep -qE "\($id\)|$id \((summary|question)\)" \
    || say "$id row does not carry its (summary|question) source tag"
  sec=$(printf '%s\n' "$row" | awk -F'|' '{print $5}' | sed -E 's/^ +| +$//g')
  [ -n "$sec" ] || { say "$id row names no discharging section"; continue; }
  printf '%s\n' "$heads" | grep -qxF -- "$sec" \
    || say "$id names discharging section '$sec', which is not a heading in $DOC"
done

# C60.4's ambiguity is recorded, not resolved.
unv=$(awk '/^## Unverified inheritance$/{f=1;next} /^## /{f=0} f' "$DOC")
printf '%s\n' "$unv" | grep -qF 'C60.4' \
  || say "C60.4's irreducible ambiguity is not recorded in Unverified inheritance"

# The 5-mechanism x 2-agent matrix and the six mandated axes.
for m in instructions skills configuration hooks plugins; do
  grep -qiF -- "$m" "$DOC" || say "mechanism '$m' is absent from the matrix"
done
for a in "discovery path" precedence "symlink" "failure semantics" gaps; do
  grep -qiF -- "$a" "$DOC" || say "axis '$a' is absent"
done
grep -qiE 'refresh|restart' "$DOC" || say "the refresh/restart axis is absent"

# Prohibitions. Written as `if grep -q ...; then` so `set -e` cannot exempt them.
if grep -qE '\b(TODO|TBD|FIXME)\b' "$DOC"; then say "placeholder marker in $DOC"; fi
if grep -qiE 'restoration of the original|restored (from|the) original' "$DOC"; then
  say "$DOC claims to restore the original"
fi

# V1 at this task's commit.
git show "HEAD:$DOC" >/dev/null 2>&1 || say "V1: $DOC is not committed at HEAD"

[ "$fail" -eq 0 ] && echo "PASS"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash "${TMPDIR:-/tmp}/gate-60.sh"`
Expected at this task's base commit: **FAIL** — the first line is
`FAIL: .claude/specs/2026-08-20-cross-agent-project-surfaces-research.md does not exist`
and the exit status is 1. That path has never existed on any git ref
(`git log --all -- <path>` returns zero commits), so this observation is
guaranteed to hold at base.

- [ ] **Step 3: Gather the primary sources**

Read, in this order, and take notes with paths as you go:

1. #60's resolution comment and its research question —
   `unset GITHUB_TOKEN GH_TOKEN && gh issue view 60 --repo fagenorn/nix-config --comments`.
   The question is transcribed **verbatim** under `## Research question`.
2. The live user-scope evidence in this repository (label every observation
   `user scope`): `home/common/claude-code/default.nix` (settings
   materialisation, `skillsDir`, `programs.claude-code.memory`, the `PreToolUse`
   hook block, the `~/.claude.json` jq merge), `home/common/agent-guidance/`,
   `home/common/agent-skills/default.nix` and its `skills/` tree,
   `lib/agent-plugins.nix` (marketplace source types, the patched plugin store
   path), and `CLAUDE.md`'s Claude Code section.
3. Project-scope evidence: `.claude/` in this repository, in
   `/Users/anis/Projects/nodocom` and in `/Users/anis/Projects/argus`
   (read-only; record each checkout's `git rev-parse HEAD` and the observation
   date, per D3).

- [ ] **Step 4: Write the document, then re-run the gate**

Write `.claude/specs/2026-08-20-cross-agent-project-surfaces-research.md`
satisfying every invariant above. Its body carries, at minimum:

- a **5-mechanism × 2-agent matrix** (instructions, skills, configuration,
  hooks, plugins × Claude Code, Codex) with an explicit present/absent verdict
  per cell (`C60.1`);
- for each cell, the six axes #60 mandates — discovery path, precedence,
  refresh/restart behaviour, symlink support, failure semantics, gaps
  (`C60.2`);
- the projection conclusion: fixed native paths mean one contained canonical
  source needs *validated thin projections*, with the mechanism that makes the
  projection necessary named per cell (`C60.3`);
- the remaining gaps in the contained-source-with-thin-projections approach,
  under both readings of "prototype" (`C60.4`);
- recorded, unranked options and a closing
  `## What this document does not decide` (`C60.5`).

Run: `bash "${TMPDIR:-/tmp}/gate-60.sh"`
Expected: `PASS`, exit 0, no `FAIL:` lines. (V1 still fails until Step 5's
commit; re-run after committing.)

- [ ] **Step 5: Commit, then confirm V1**

```bash
git add .claude/specs/2026-08-20-cross-agent-project-surfaces-research.md
git commit -m "$(cat <<'MSG'
docs(specs): re-derive the #60 cross-agent project surfaces findings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
)"
bash "${TMPDIR:-/tmp}/gate-60.sh"
```

Expected: the commit is SSH-signed and succeeds; the gate prints `PASS` with
exit 0, V1 included.
