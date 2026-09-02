# Task 2: #61 — agent fallback inventory

**Files:**
- Create: `.claude/specs/2026-08-20-agent-fallback-inventory-research.md`
- Test: none — this repository has no test suite for documentation. The task's
  gate is the shell block in Step 2/Step 4, run from the worktree root.

**Interfaces:**

- Consumes: the spec
  `.claude/specs/2026-09-02-issue-115-recovered-wayfind-findings-design.md` —
  its `## Document contract`, its `### .claude/specs/2026-08-20-agent-fallback-inventory-research.md (#61)`
  coverage table (claims `C61.1`–`C61.5`), its terminology guard, and rows
  D1–D5, D8, D10, D12, D13, D17. The plan root's `## Global Constraints` and its
  canonical section names. The canonical document shape Task 1 produces:
  the ordered headings `## Provenance`, `## Research question`,
  `## Coverage of the resolution summary`, `## Unverified inheritance`, body
  sections, `## What this document does not decide` last; a four-column
  coverage table whose fourth column is the verbatim text of a `##`/`###`
  heading in the same document; and the front-matter literals
  `**Durability: committed**` and
  ``Schema-version-1 `research-observations` / `agent-evidence` gate: not invoked``.
- Produces: nothing later tasks consume. This document stands alone.

**Invariants:**

- The path is exactly the path #61's resolution comment links; the
  `2026-08-20` prefix is #61's decision date, not the authorship date.
- `## Provenance` declares the re-derivation exactly as D1 requires: authored
  2026-09-02 under issue #115, the original never committed to any git ref and
  unrecoverable, and no claim here citable as evidence of the original's
  content.
- **Three words stay apart** (per D10), each disambiguated in one line where
  first used: a **fallback** degrades to a lesser but continuing behaviour; a
  **fail-closed refusal** blocks and does not degrade; a **declared runtime
  alternative** (#69/#71) is a configured second source, not a rescue path. The
  `PreToolUse` lifecycle guard is fail-closed with no defer path
  (`CLAUDE.md`, `home/common/claude-code/default.nix`), so it is **not** an
  inventory site under `C61.1`/`C61.3`; if it appears at all it appears as a
  contrasting case, explicitly named as enforcement.
- Every inventoried site is classified exactly one of
  `removable-after-validated-onboarding-contract` or `unavoidable-portability`,
  and carries its concrete location in the spec's citation form (per D3). Fleet
  sites carry the repository name, repo-relative path, the checkout's observed
  `HEAD` sha and the observation date.
- `C61.4`'s cost figures state a **unit** and a **method** explicitly, on lines
  beginning `Unit:` and `Method:`. A number arrived at by estimate rather than
  measurement is labelled an estimate on the spot; an unlabelled estimate is a
  defect.
- `C61.5` holds: no removal policy is decided. The document ends with
  `## What this document does not decide`.
- Length is governed by the-bar's *Token economy*; `artifact-budget` is never
  run against this file (per D8).

- [ ] **Step 1: Write the gate first, before the document**

Save this to `"${TMPDIR:-/tmp}/gate-61.sh"`. It is the task's contract.

```bash
#!/usr/bin/env bash
set -uo pipefail
DOC=".claude/specs/2026-08-20-agent-fallback-inventory-research.md"
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
removable-after-validated-onboarding-contract
unavoidable-portability
fail-closed
declared runtime alternative
Unit:
Method:
LITS

order=$(grep -n '^## ' "$DOC" | sed 's/^[0-9]*://')
expected=$'## Provenance\n## Research question\n## Coverage of the resolution summary\n## Unverified inheritance'
printf '%s\n' "$order" | head -4 | diff -q - <(printf '%s\n' "$expected") >/dev/null \
  || say "the first four ## headings are not the canonical four, in order"
[ "$(printf '%s\n' "$order" | tail -1)" = "## What this document does not decide" ] \
  || say "the last ## heading is not 'What this document does not decide'"

cov=$(awk '/^## Coverage of the resolution summary$/{f=1;next} /^## /{f=0} f' "$DOC")
heads=$(grep -E '^#{2,4} ' "$DOC" | sed -E 's/^#{2,4} //')
for id in C61.1 C61.2 C61.3 C61.4 C61.5; do
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

# C61.1's four named families.
for f in "project binding" command tracker "doc discovery"; do
  grep -qiF -- "$f" "$DOC" || say "family '$f' is absent from C61.1's cluster"
done

# All three fleet adapters are inventoried (C61.3).
for r in nix-config Nodo Argus; do
  grep -qiF -- "$r" "$DOC" || say "adapter '$r' is not inventoried"
done

# The guard must never be classified as a fallback site.
if awk '/PreToolUse/' "$DOC" | grep -qiE 'removable-after-validated-onboarding-contract|unavoidable-portability'; then
  say "the PreToolUse guard is classified as an inventory site; it is fail-closed enforcement (D10)"
fi

if grep -qE '\b(TODO|TBD|FIXME)\b' "$DOC"; then say "placeholder marker in $DOC"; fi
if grep -qiE 'restoration of the original|restored (from|the) original' "$DOC"; then
  say "$DOC claims to restore the original"
fi

git show "HEAD:$DOC" >/dev/null 2>&1 || say "V1: $DOC is not committed at HEAD"

[ "$fail" -eq 0 ] && echo "PASS"
exit "$fail"
```

- [ ] **Step 2: Run the gate and watch it fail**

Run: `bash "${TMPDIR:-/tmp}/gate-61.sh"`
Expected at this task's base commit: **FAIL** — first line
`FAIL: .claude/specs/2026-08-20-agent-fallback-inventory-research.md does not exist`,
exit status 1. That path has never existed on any git ref
(`git log --all -- <path>` returns zero commits), so the observation holds at
base.

- [ ] **Step 3: Gather the primary sources**

1. #61's resolution comment and research question —
   `unset GITHUB_TOKEN GH_TOKEN && gh issue view 61 --repo fagenorn/nix-config --comments`.
   Transcribe the question verbatim under `## Research question`.
2. The shared skills and helpers:
   `home/common/agent-skills/skills/*/SKILL.md`,
   `home/common/claude-code/skills/*/SKILL.md`, and
   `home/common/agent-skills/scripts/` (`resolve-bindings`, `workflow-state.py`,
   `artifact-budget`, `agent-evidence.py`, `diff-scope.py`,
   `agent-model-matrix.py`). Grep for the fallback shapes the skills spell out
   — "helper missing →", "otherwise", "legacy", "degrade", "default" — and
   record each as a site with its path and line.
3. The live adapters: `.claude/skills.config.json` in this repository, in
   `/Users/anis/Projects/nodocom` and in `/Users/anis/Projects/argus`
   (read-only; record each `git rev-parse HEAD` and the observation date).
4. The contrasting case: the `PreToolUse` block in
   `home/common/claude-code/default.nix` and `CLAUDE.md`'s description of it.

- [ ] **Step 4: Write the document, then re-run the gate**

The body carries, at minimum:

- the removable cluster — project binding, command, tracker and doc discovery —
  all four families named with their concrete sites (`C61.1`);
- why product/runtime preflights tied to live external variability are **not**
  interchangeable with onboarding fallbacks, with the discriminating property
  stated in one sentence (`C61.2`);
- the per-site inventory across the shared skills and helpers plus the three
  live adapters, each site classified
  `removable-after-validated-onboarding-contract` or
  `unavoidable-portability` (`C61.3`);
- attributable prompt size and repeated execution cost with `Unit:` and
  `Method:` lines and per-cluster numbers, every estimate labelled (`C61.4`);
- a closing `## What this document does not decide` recording that no removal
  policy is chosen (`C61.5`).

Run: `bash "${TMPDIR:-/tmp}/gate-61.sh"`
Expected: `PASS`, exit 0. (V1 still fails until Step 5's commit; re-run after
committing.)

- [ ] **Step 5: Commit, then confirm V1**

```bash
git add .claude/specs/2026-08-20-agent-fallback-inventory-research.md
git commit -m "$(cat <<'MSG'
docs(specs): re-derive the #61 agent fallback inventory findings

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
MSG
)"
bash "${TMPDIR:-/tmp}/gate-61.sh"
```

Expected: the commit is SSH-signed and succeeds; the gate prints `PASS` with
exit 0, V1 included.
