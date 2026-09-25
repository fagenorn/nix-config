# Task 3: #62 — project knowledge inventory

**Files:**
- Create: `.claude/specs/2026-08-20-project-knowledge-inventory-research.md`
- Test: none — this repository has no test suite for documentation. The task's
  gate is the shell block in Step 2/Step 4, run from the worktree root.

**Interfaces:**

- Consumes: the spec
  `.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md` —
  its `## Document contract`, its `### .claude/specs/2026-08-20-project-knowledge-inventory-research.md (#62)`
  coverage table (claims `C62.1`–`C62.6`), and rows D1–D5, D8, D12, D13, D17,
  D18. The plan root's `## Global Constraints` and its canonical section names.
  The canonical document shape Task 1 produces: the ordered headings
  `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, body
  sections, `## What this document does not decide` last; a four-column
  coverage table whose fourth column is the verbatim text of a `##`/`###`
  heading in the same document; and the front-matter literals
  `**Durability: committed**` and
  ``Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked``.
- Produces: nothing later tasks consume. This document stands alone.

**Invariants:**

- The path is exactly the path #62's resolution comment links; the
  `2026-08-20` prefix is #62's decision date, not the authorship date.
- `## Provenance` declares the re-derivation exactly as D1 requires.
- **`C62.2` is the drift instance and gets the full D5 treatment.** The spec's
  parenthetical observation is itself unverified at planning time and must not
  be copied (per D18). Re-observe it yourself, record all three parts, and let
  the observation decide the reconciliation — including the outcome "no drift;
  the as-of-decision claim still holds":
  - (a) the as-of-decision claim as `C62.2` states it — 34 ignored
    machine-local skill directories in Nodo;
  - (b) the as-observed fact, in a fenced block showing the **exact commands**
    run and their output, the checkout's `git rev-parse HEAD`, and the
    observation date `2026-09-02`. At minimum: the directory count under
    `/Users/anis/Projects/nodocom/.claude/skills`, whether any of it is tracked
    (`git ls-files .claude/skills`), and whether it is ignored
    (`git check-ignore -v .claude/skills`);
  - (c) an explicit reconciliation sentence under a heading whose text contains
    the word `Reconciliation`.
- Every fleet claim carries the repository name, the repo-relative path, the
  checkout's observed `HEAD` sha and the observation date (per D3). Both
  `/Users/anis/Projects/nodocom` and `/Users/anis/Projects/argus` are read-only.
- Every inventoried item carries all five `C62.6` fields — provenance, update
  mechanism, context cost, maintenance cost — plus exactly one classification
  from `duplicate-of-global`, `agent-exclusive`, `vendor-derived`, `stale`,
  `reusable-elsewhere`.
- `C62.5` holds: promotion candidates are listed **without** policy decisions.
  The document ends with `## What this document does not decide`.
- Length is governed by the-bar's *Token economy*; `artifact-budget` is never
  run against this file (per D8).

- [ ] **Step 1: Write the gate first, before the document**

Save this to `"${TMPDIR:-/tmp}/gate-62.sh"`. It is the task's contract.

```bash
#!/usr/bin/env bash
set -uo pipefail
DOC=".claude/specs/2026-08-20-project-knowledge-inventory-research.md"
fail=0
say() { echo "FAIL: $*"; fail=1; }

test -f "$DOC" || { echo "FAIL: $DOC does not exist"; exit 1; }

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
duplicate-of-global
agent-exclusive
vendor-derived
reusable-elsewhere
skillsDir
~/.agents/skills/
LITS

order=$(grep -n '^## ' "$DOC" | sed 's/^[0-9]*://')
expected=$'## Provenance\n## Research question\n## Coverage of the resolution summary\n## Unverified inheritance'
printf '%s\n' "$order" | head -4 | diff -q - <(printf '%s\n' "$expected") >/dev/null \
  || say "the first four ## headings are not the canonical four, in order"
[ "$(printf '%s\n' "$order" | tail -1)" = "## What this document does not decide" ] \
  || say "the last ## heading is not 'What this document does not decide'"

cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^## /{f=0} f' "$DOC")
heads=$(grep -E '^#{2,4} ' "$DOC" | sed -E 's/^#{2,4} //')
for id in C62.1 C62.2 C62.3 C62.4 C62.5 C62.6; do
  row=$(printf '%s\n' "$cov" | grep -F -- "$id " | head -1)
  [ -n "$row" ] || { say "claim $id absent from the coverage table"; continue; }
  n=$(printf '%s\n' "$row" | awk -F'|' '{print NF}')
  [ "$n" -ge 6 ] || say "$id row does not have four columns"
  printf '%s\n' "$row" | grep -qE "$id \((summary|question)\)" \
    || say "$id row does not carry its (summary|question) source tag"
  sec=$(printf '%s\n' "$row" | awk -F'|' '{print $5}' | sed -E 's/^ +| +$//g')
  [ -n "$sec" ] || { say "$id row names no discharging section"; continue; }
  printf '%s\n' "$heads" | grep -qxF -- "$sec" \
    || say "$id names discharging section '$sec', which is not a heading in $DOC"
done

# C62.2 drift treatment: the observation commands, the date, and a
# Reconciliation heading must all be present.
grep -qE '^#{2,4} .*[Rr]econciliation' "$DOC" || say "no Reconciliation heading for the C62.2 drift"
for c in 'git ls-files' 'git check-ignore' 'git rev-parse HEAD'; do
  grep -qF -- "$c" "$DOC" || say "the C62.2 drift block does not show the command '$c'"
done
grep -qF -- '2026-09-02' "$DOC" || say "no observation date recorded"

# The three fleet repositories are inventoried.
for r in nix-config Nodo Argus; do
  grep -qiF -- "$r" "$DOC" || say "repository '$r' is not inventoried"
done
grep -qF -- 'pi' "$DOC" || say "C62.4's vendor-sensitive pi guidance is absent"

if grep -qE '\b(TODO|TBD|FIXME)\b' "$DOC"; then say "placeholder marker in $DOC"; fi
if grep -qiE 'restoration of the original|restored (from|the) original' "$DOC"; then
  say "$DOC claims to restore the original"
fi

git show "HEAD:$DOC" >/dev/null 2>&1 || say "V1: $DOC is not committed at HEAD"

[ "$fail" -eq 0 ] && echo "PASS"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash "${TMPDIR:-/tmp}/gate-62.sh"`
Expected at this task's base commit: **FAIL** — first line
`FAIL: .claude/specs/2026-08-20-project-knowledge-inventory-research.md does not exist`,
exit status 1. That path has never existed on any git ref
(`git log --all -- <path>` returns zero commits), so the observation holds at
base.

- [ ] **Step 3: Gather the primary sources**

1. #62's resolution comment and research question —
   `unset GITHUB_TOKEN GH_TOKEN && gh issue view 62 --repo fagenorn/nix-config --comments`.
   Transcribe the question verbatim under `## Research question`.
2. The centralisation mechanisms (`C62.1`), in this repository:
   `home/common/agent-guidance/default.nix` and its `AGENTS.md`
   (one source projected to `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`);
   `home/common/agent-skills/default.nix` (`skillsDir` for Claude, the
   whole-directory links at `~/.agents/skills/` for Codex, and why they are
   whole-directory); `CLAUDE.md`'s agent-surface section.
3. Nodo, read-only, at `/Users/anis/Projects/nodocom`: record
   `git rev-parse HEAD`, then run the three `C62.2` observation commands and
   capture their real output.
4. Argus, read-only, at `/Users/anis/Projects/argus`: record
   `git rev-parse HEAD`, then inventory `.claude/` — the duplicated items
   (`C62.3`) with their global counterparts identified, and the
   vendor-sensitive `pi` guidance (`C62.4`) with what makes it vendor-derived
   and what makes it stale-sensitive.

- [ ] **Step 4: Write the document, then re-run the gate**

The body carries, at minimum:

- the already-centralised global sources with their single-source mechanisms
  named (`C62.1`);
- the Nodo skill-directory claim under the full drift treatment above
  (`C62.2`);
- Argus duplication, items named, global counterparts identified (`C62.3`);
- Argus's vendor-sensitive `pi` guidance (`C62.4`);
- promotion candidates listed with no policy decision (`C62.5`);
- a per-item table carrying provenance, update mechanism, context cost,
  maintenance cost and one classification each (`C62.6`);
- a closing `## What this document does not decide`.

Run: `bash "${TMPDIR:-/tmp}/gate-62.sh"`
Expected: exit 1 with exactly one `FAIL:` line, the V1 line
`FAIL: V1: <doc> is not committed at HEAD`. Every content check passes here;
V1 cannot pass before Step 5's commit, so `PASS` is unreachable at this step.
If any other `FAIL:` line appears, fix the document and re-run before
committing.

- [ ] **Step 5: Commit, then confirm V1**

```bash
git add .claude/specs/2026-08-20-project-knowledge-inventory-research.md
git commit -m "$(cat <<'MSG'
docs(specs): re-derive the #62 project knowledge inventory findings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
)"
bash "${TMPDIR:-/tmp}/gate-62.sh"
```

Expected: the commit is SSH-signed and succeeds; the gate prints `PASS` with
exit 0, V1 included.

- [ ] **Step 6: V5 — source-backed semantic audit (per D19)**

The gate has proven traceability only. Before this task is done, read the
document against its cited sources and confirm each claim ID it owes is
*answered*, not merely *addressed*:

- Open every `##`/`###` section the coverage table names, and every live source
  that section cites. A citation that does not support the sentence it anchors
  is a rejection.
- Confirm each enumerated obligation this task's invariants list — every matrix
  cell, every mandated axis, every required field — is answered in the place the
  coverage table points at. The gate's document-wide `grep` cannot see whether an
  axis is answered in *each* cell; only this reading can.
- A field with no answer in the live tree must say so explicitly. Silence and
  plausible-but-uncited prose are both rejections.
- Reject any conclusion not traceable to a source read during Step 3.

Expected: every claim ID answered from a cited source, or the document revised
and Steps 4-5 re-run.
