# Task 5: Dispositions and tracker filings

This task covers spec §4 and §6 items 2 and 5, and follows D7, D8, D14, D16 and D19. Every row red as last observed (committed by Tasks 1–4, or re-observed in Step 4) gets exactly one disposition: an open issue cited, or a new issue filed in `fagenorn/nix-config`. This task is the attempt's only tracker writer. Its filings are external and cannot be withdrawn silently.

**Files:**
- Modify: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)

**Interfaces:**
- Consumes: the item sections C1–C12 in `CL` and their red rows; `gh`, authenticated through its own credential.
- Produces: a `## Dispositions` section after `## Evidence`, holding the table `| Rows | Repair route | Disposition |` and the owner-run line. Each Disposition cell is `#<n> filed` or `#<n> cited`. Task 6 reads the issue numbers from it.

**Invariants:**
- Each red row of C1–C12 appears in exactly one Rows cell, written `<item> <host> <subject>` with the row's Subject cell verbatim, for example `C10 mbp /Users/anis/Projects/nodocom`. Entries are separated by `; `. Rows that share a repair route (a distinct owner and action) share one issue.
- An open issue that covers a route is cited and never duplicated. A filed issue's body holds its rows' evidence in full and links #130.
- Every issue carries `wayfinder:slice`. It also carries `agent:human-required` when its repair needs the owner or another repository. None carries `agent:ready` or `instruction-budget-raise` (D14). No route is fixed here (D14).
- Dispositions follow the rows as last observed (D19). When a Step 4 re-read differs from its row in count or content, re-observe the whole row in `CL`: Revision, UTC, Exit, Observed and Verdict, the verdict read under its item's rule. Then recompute that item's `Item verdict` line. Every other row keeps its committed bytes.
- A re-observed row that is no longer red gets no disposition, so nothing is filed or cited from it. A row that turns red gets one. Filings use only the new observation.

- [ ] **Step 1: Confirm red and list the red rows**

Run: `grep -c '^## Dispositions$' .agents/artifacts/evidence/cutover-130-checklist.md`. Expected: `0`, exit 1.
Then list every row whose `Verdict` cell is `red`, with its item, host, subject and Observed, into `SCR/red-rows.tsv`, and run `gh auth status`.

- [ ] **Step 2: Assign routes**

Use the expected routes (§4, D16). Each one is filed or cited only if this run has a red row for it:

| Ref | Red rows | Repair route (§4 text) | Labels | Title |
|-----|----------|------------------------|--------|-------|
| F1 | C3, C4 | build the strict-cutover candidate (§4 F1) | slice, human-required | Stage-4 strict-cutover candidate: platform 2.0.0 without the bridge paths |
| F2 | C11 host rows (empty `deprecations`) | bridge minor declaring the deprecations (§4 F2) | slice | Bridge minor: declare deprecations for every path the strict cutover removes |
| F3 | C11 Arcwave | retire Arcwave's tracked legacy file and its reader (§4 F3) | slice, human-required | Arcwave: retire the tracked legacy skills.config.json and its reader |
| F4 | C11 Nodo | move Nodo's railway deploy off `bindings.deploy` (§4 F4) | slice, human-required | Nodo: move the railway deploy off bindings.deploy and the legacy skills config |
| #555 | C11 JarBird adapter `github-actions-health` | cited when open | — | — |
| F5 | C2 and C10 Nodo, `repository.ignore.runtime_sentinel` | repair the overbroad ignore rule (§4 F5) | slice, human-required | Nodo: repair the overbroad runtime-sentinel ignore rule |
| F6 | C6 rows with `refused` > 0 | dispose of the refused ledgers (§4 F6) | slice, human-required | Fleet: dispose of the legacy ledgers workflow-state migrate refuses |
| F7 | C7 red rows | reconcile unmapped and refused-only worktrees (§4 F7) | slice, human-required | Fleet: reconcile retained worktrees that have no resumable ledger mapping |
| F8 | C2 nix-config `adoption-evidence-record` | keep #70 bundle and trials JSON out of the adoption-evidence candidate set (D16) | slice | adopt-project verify counts gate bundle JSON as adoption evidence records |

Any other red row is a new route with its own issue, labelled under the D14 rule. C3's live paired Claude and Codex trials are owner-run, are not filed, and stay on issue 130's gate (D11).

- [ ] **Step 3: Search open issues**

Run `gh issue list --repo fagenorn/nix-config --state open --limit 300 --json number,title,body > SCR/open-issues.json`. For each route, search the titles and bodies for its subject terms: `candidate` and `2.0.0`; `deprecation`; `Arcwave`; `railway`; `github-actions-health`; `runtime_sentinel`; `migrate` and `refused`; `worktree` and `mapping`; `adoption evidence record` and `bundle`. Cite an open issue only when its action and owner are the route's. Record each match you rejected, with the reason, for Step 7's report.

- [ ] **Step 4: Re-read the full lists**

Re-run the read-only commands whose lists a filing needs, per Global Constraints, saving each output under `SCR/<H>/`:
- F6: `workflow-state migrate --repo-root R` (no `--apply`), for each refused ledger's `ledger`, `dialect` and `reason`.
- F3 and F4: `git --no-optional-locks -C R ls-files -- .claude/skills.config.json`, `resolve-project resolve --repo-root R` (`bindings.deploy.adapter`), and `git --no-optional-locks -C R grep -n -F -e skills.config.json -e resolve-bindings -e 'release deploy inspect' -- . ':!.agents/artifacts'` for the readers.
- F7: for each red C7 root, the F6 dry-run JSON and this script and classifier (Task 4's, repeated). Run the script as `/bin/bash SCR/c7.sh R > SCR/<H>/<project>-c7.tsv`, or as `ssh … H -- /bin/bash -s -- R < SCR/c7.sh > SCR/<H>/<project>-c7.tsv` remotely. It lists each linked worktree with the ledgers whose `state.json` holds its path, as listed or as its realpath, as a whole JSON string (D15). It exits 2 with nothing on stdout when discovery or a ledger search fails, and the classifier refuses a TSV without its `#end` count line. Either failure is a re-observation of the row as red, with the failure as Observed (D4), and no path list is filed from it.

```bash
#!/bin/bash
# c7.sh ROOT: one line per linked worktree (path<TAB>ledger names), then "#end<TAB><count>".
# A failed discovery or search exits 2 and prints nothing on stdout.
set -o pipefail
shopt -s nullglob
R=$1
die() { echo "c7: $*" >&2; exit 2; }
W=$(git --no-optional-locks -C "$R" worktree list --porcelain) || die "worktree list failed in $R"
printf '%s\n' "$W" | grep -q '^worktree ' || die "worktree list printed no entry for $R"
S=("$R"/.superpowers/workflows/*/state.json)
T=""; n=0
while IFS= read -r P; do
  RP=$(cd "$P" 2>/dev/null && pwd -P || printf '%s' "$P")
  L=""
  if [ ${#S[@]} -gt 0 ]; then
    M=$(grep -l -F -e "\"$P\"" -e "\"$RP\"" "${S[@]}"); rc=$?
    [ "$rc" -le 1 ] || die "grep exit $rc for $P"
    L=$(printf '%s\n' "$M" | awk -F/ 'NF {print $(NF-1)}' | sort -u | tr '\n' ' ')
  fi
  T+="$P"$'\t'"$L"$'\n'; n=$((n + 1))
done < <(printf '%s\n' "$W" | sed -n 's/^worktree //p' | tail -n +2)
printf '%s#end\t%s\n' "$T" "$n"
```

```bash
python3 -I - SCR/<H>/<project>-migrate.json SCR/<H>/<project>-c7.tsv <<'EOF'
import json, sys
verdict = {l["ledger"]: l["verdict"] for l in json.load(open(sys.argv[1]))["ledgers"]}
lines = open(sys.argv[2], encoding="utf-8").read().splitlines()
end = lines[-1].split("\t") if lines else []
if end[:1] != ["#end"] or end[1:] != [str(len(lines) - 1)]:
    sys.exit("worktree inventory incomplete: " + sys.argv[2])
for line in lines[:-1]:
    path, _, names = line.partition("\t")
    found = {verdict.get(n, "refused") for n in names.split()}
    c = ("unmapped" if not found else "current" if found & {"current", "migrated"}
         else "migrate" if "migrate" in found else "refused-only")
    print(c, path, names.strip() or "-", sep="\t")
EOF
```

The F7 body lists every `unmapped` and `refused-only` path with its ledgers.

Compare each count with its row, and apply the re-observation rule under Invariants. Then rebuild `SCR/red-rows.tsv` from `CL` as Step 1 did, and revise Steps 2 and 3 to that list: drop a route left with no red row, and route a row that turned red. File from that list only.

- [ ] **Step 5: File**

Write each body to `SCR/<ref>.md` with these sections:
- `## Context`: "Found by the issue 130 cutover preparation (#130), checklist `.agents/artifacts/evidence/cutover-130-checklist.md`, items <ids>. The #130 gate comment links it at the merged commit."
- `## Evidence`: per row, the host, subject, revision, commands, UTC, exit and the full list.
- `## What to do`: the route's §4 text, or D16 for F8.
- `## Acceptance criteria`: one checkbox line per item, naming its commands on its subjects and "reads green under the checklist's rule".

File each issue in its own Bash call: `gh issue create --repo fagenorn/nix-config --title '<Title from Step 2>' --body-file SCR/<ref>.md --label wayfinder:slice` (add `--label agent:human-required` per Step 2). A new route's title follows the same plain style, without `"`, `$`, backticks or backslashes. Record each printed URL.

- [ ] **Step 6: Write the section**

Add `## Dispositions` after `## Evidence`. It has one table row per route, then the line `Owner-run, not filed: the #70 live paired Claude and Codex trials (#128 D11), on issue 130's gate once F1's candidate exists.`

- [ ] **Step 7: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
test "$(wc -c < "$CL")" -le 44032
python3 -I - "$CL" > SCR/cited.txt <<'EOF'
import re, sys
text = open(sys.argv[1], encoding="utf-8").read() + "\n## "
disp = text.split("\n## Dispositions\n", 1)[1].split("\n## ", 1)[0]
cells = [[x.strip() for x in l.strip().strip("|").split("|")] for l in disp.splitlines()
         if l.startswith("| ") and not l.startswith("| Rows |")]
covered = sorted(e for c in cells for e in c[0].split("; "))
red = []
for m in re.finditer(r"^### (C\d+) — .*?(?=^##)", text, re.M | re.S):
    for r in m.group(0).splitlines():
        c = [x.strip() for x in re.split(r"(?<!\\)\|", r.strip())[1:-1]]
        if len(c) == 8 and c[7] == "red":
            red.append(f"{m.group(1)} {c[0]} {c[1]}")
assert covered == sorted(red), "dispositions differ from the red rows as last observed"
for c in cells:
    assert re.fullmatch(r"#\d+ (filed|cited)", c[2]), c[2]
    print(c[2].split()[0][1:], c[2].split()[1])
EOF
while read -r n kind; do
  gh issue view "$n" --repo fagenorn/nix-config --json state --jq .state | grep -qx OPEN
  if test "$kind" = filed; then gh issue view "$n" --repo fagenorn/nix-config --json body --jq .body | grep -q '#130'; fi
done < SCR/cited.txt
echo dispositions ok
```

Substitute `SCR` literally. Expected: `dispositions ok`: every red row, as last observed, has exactly one disposition, and no Rows entry names a row that is not red. Before Step 6 the Python fails, because the section is missing.
When Step 4 re-observed a row, also run, in one Bash call, `export CHECK_ITEMS='<the re-observed items>'` followed by the root's row check. Expected: `rows ok`.

- [ ] **Step 8: Commit**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T5): dispositions and filings" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Report each filed and cited number, with its route and the open-issue matches you rejected.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[{"base":"8200934e48d1dbf1f8fb7e583880bafdf59d4eb2","head":"5151b148892eab5f2287fb59d0c39c1a6dbecca7"}],"commit_subject_bytes":[64,64,64],"id":5,"records":[{"bounds":[{"added_lines":350,"boundary":"all","deleted_lines":2,"record_bytes":47616,"support":{"covers":["r1-1","r2-1","r3-1","r4-1","r5-1"],"kind":"authored-cumulative/v1"}}],"change":"modify","id":"r5-1","last_task":6,"owner":5,"path":".agents/artifacts/evidence/cutover-130-checklist.md"}]}}
```
