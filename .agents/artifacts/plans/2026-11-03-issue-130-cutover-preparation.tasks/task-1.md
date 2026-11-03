# Task 1: Roster, host identity and the before-snapshot

This task covers spec §1, §2 and the §3 rows C1 and C12, and holds AC6's check. It creates `CL` with its header, the roster and the C1 and C12 sections, and fixes the roster and host reachability that every later task uses (D2, D15).

**Files:**
- Create: `.agents/artifacts/evidence/cutover-130-checklist.md` (`CL`)

**Interfaces:**
- Consumes: the flake in the delivery worktree; on each host, `~/.agents/state/fleet/registry.json` (`{"projects": [{"project_id", "root", "branch_override"?: {"branch", "default_branch", "reason"}}]}`), `/nix/var/nix/profiles/system*`, `/run/current-system`, and `resolve-project platform-status` (`platform.platform_version`, `platform.manifest_path`).
- Produces `CL`, in this order:
  - Line 1 is `# Stage-4 cutover checklist — issue 130`.
  - The header lines:
    - `Purpose: <one sentence: pre-activation predicates for the issue 130 strict cutover with fresh read-only evidence, red-row dispositions and the owner's gate; preparation only, per spec D1>`
    - `Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396`
    - `Revisions: delivery worktree <40-hex HEAD at Task 1 start>; origin/main <40-hex>, as last fetched (D15)`
    - `Hosts: <C1's hosts in flake order>`
  - `## Roster`, holding:
    - `### Hosts`, with the table `| Host | Reachable | Generation | Store path | platform_version | manifest_path | K_H | Other clones | Registry sha256 before |`. `Reachable` is `yes` or `no (C1.c exit <n>)`, Generation is `system-<N>`, and `K_H` is chosen per D15. An unreachable host's other cells are `—`.
    - `### Projects`, with the table `| Host | project_id | Root | branch_override | HEAD before |`. Cells are plain text without backticks. `branch_override` is `<branch> (<reason>)` or `—`, and `HEAD before` is the full 40-hex.
    - The inclusion paragraph. It says that every registered project on every reachable host is in (D2). It contains the exact phrase `Arcwave is in`, citing the owner's 2026-11-03 comment on issue 130. It records the observed `branch_override` of Arcwave and of `nodocom` (Nodo) as the designed #363 path, not a red item. It ends with the unreachable-host rule.
  - `## Evidence`, holding `### C1 — Roster from registry truth` and `### C12 — Bridge generation identified per host`.

**Invariants:**
- The only write outside `SCR` is `CL`, and it follows Global Constraints.
- The `### Projects` table has exactly one row per registry entry on a reachable host, and nothing is dropped or added.
- `adopt-project verify --repo-root <worktree>` reports the same `result` and the same failed check ids before and after this task's commit, and no failed check's `detail` names a `.md` path (D16).

- [ ] **Step 1: Confirm red and take the seam baseline**

Run: `test -e .agents/artifacts/evidence/cutover-130-checklist.md; echo $?`. Expected: `1`.
Record the start time, `SCR`, `git rev-parse HEAD` and `git rev-parse origin/main`. Do not fetch.
Run: `adopt-project verify --repo-root "$PWD" > SCR/verify-before.json` (timeout 120 s). Then record `result` and the sorted `id`s of checks whose `status` is `failed`. The expected values are `not_conformant` and `["adoption-evidence-record"]`, per D16.

- [ ] **Step 2: C1, the hosts and their registries**

The commands, labelled for `CL`:

```text
C1.a nix eval --json .#darwinConfigurations --apply builtins.attrNames
C1.b nix eval --json .#nixosConfigurations --apply builtins.attrNames
C1.c hostname
C1.d cat .agents/state/fleet/registry.json
```

- Run C1.a and C1.b in the worktree root (timeout 600 s each). They are expected to print `["eleven-m5","mbp"]` and `["anis-desktop"]`, and the printed lists are the hosts.
- Run C1.c on each host: locally on `mbp`, and through ssh elsewhere (timeout 60 s). A host is reachable when C1.c prints its flake name. Otherwise record the exit (255 on a timeout) and ssh's message.
- On each reachable host, run C1.d from the home directory (locally `cat ~/.agents/state/fleet/registry.json`). Save the bytes to `SCR/<H>/registry.json`, and take `shasum -a 256 SCR/<H>/registry.json` as `Registry sha256 before`.

C1 rows:
- One row for host `mbp`, subject `flake.nix`, revision the worktree's 12-hex `HEAD`, commands `C1.a; C1.b`. It is green when both evals print a JSON list, and red otherwise.
- One row per host, subject `host`, commands `C1.c; C1.d`. It is green when the registry parses as `{"projects": [...]}`, with Observed giving the project count and ids. It is human-pending when the host is unreachable, and red when the registry is missing or does not parse.

- [ ] **Step 3: The projects and their before-snapshot**

Write `SCR/rev.sh`:

```bash
#!/bin/bash
# rev.sh ROOT: prints HEAD, branch and dirty count, tab-separated
R=$1
h=$(git --no-optional-locks -C "$R" rev-parse HEAD) || exit 1
b=$(git --no-optional-locks -C "$R" symbolic-ref --short -q HEAD || echo detached)
n=$(git --no-optional-locks -C "$R" status --porcelain | wc -l | tr -d ' ')
printf '%s\t%s\t%s\n' "$h" "$b" "$n"
```

For each registry entry on each reachable host, run `/bin/bash SCR/rev.sh R` on `mbp`, or `ssh … H -- /bin/bash -s -- R < SCR/rev.sh` remotely (timeout 60 s). Write one `### Projects` row per entry, with `HEAD before` set to the full HEAD.

- [ ] **Step 4: Host identity and `K_H`**

On each reachable host:
- Run `resolve-project platform-status` and read `platform.platform_version` and `platform.manifest_path`.
- Find the nix-config clones. The candidates are the host's registered `fagenorn/nix-config` root, if it has one, and the existing directories among `~/tmp/nix-config`, `~/Projects/nix-config`, `~/nix-config`, `~/src/nix-config` and `~/.config/nix-config`.
- Keep a candidate only when `git --no-optional-locks -C D remote get-url origin` ends in `fagenorn/nix-config` or `fagenorn/nix-config.git`.
- `K_H` is chosen per D15: the registered root, else the first kept path in sort order. `Other clones` lists the rest, or `—` when there are none. When no clone is kept, `K_H` is `none found`, and Task 6 leaves that host's gate step unbound.

Never scan `~` broadly. A depth search reads privacy-protected folders on macOS.

- [ ] **Step 5: C12, the bridge generation**

```text
C12.a hostname
C12.b readlink /nix/var/nix/profiles/system
C12.c readlink /nix/var/nix/profiles/system-<N>-link
C12.d readlink /run/current-system
```

Run these per reachable host (timeout 60 s each), where `<N>` comes from C12.b's `system-<N>-link`. A host's row is green when the C12.c and C12.d store paths are equal and C12.a equals the host's flake name. It is red otherwise, and human-pending for an unreachable host. Observed carries `N`, whether the store paths are equal, and the store path's basename. Fill the roster's `Generation` (`system-<N>`) and `Store path` columns from the same reads. Per D2, a difference between hosts' store paths is recorded and is not red.

- [ ] **Step 6: Write `CL`**

Create `CL` with the layout under Interfaces. Each item section follows the Global Constraints item format, and C1's `> ` line quotes the refresh's "Derive the cutover roster from the fleet registry at execution time rather than freezing “all three,” and explicitly decide whether Arcwave belongs in this cutover." C12's line quotes the issue's "The bridge generation is retained until the strict predicates are verified green on the fleet, and rollback reactivates it."

- [ ] **Step 7: Verify**

```bash
set -e
CL=.agents/artifacts/evidence/cutover-130-checklist.md
test "$(wc -c < "$CL")" -le 10240
test "$(head -1 "$CL")" = '# Stage-4 cutover checklist — issue 130'
for h in '## Roster' '### Hosts' '### Projects' '## Evidence'; do grep -qx "$h" "$CL"; done
grep -q '^Run: rel_01a1a1d8-7220-72a2-841e-df2806f78396$' "$CL"
grep -q 'Arcwave is in' "$CL"
python3 -I - "$CL" SCR/*/registry.json <<'EOF'
import json, sys
text = open(sys.argv[1], encoding="utf-8").read()
projects = text.split("### Projects", 1)[1].split("\n## ", 1)[0]
for path in sys.argv[2:]:
    host = path.split("/")[-2]
    for p in json.load(open(path, encoding="utf-8"))["projects"]:
        row = f"| {host} | {p['project_id']} | {p['root']} |"
        assert row in projects, "missing roster row " + row
print("roster ok")
EOF
```

Substitute `SCR` literally. Then, in one Bash call, run `export CHECK_ITEMS='C1 C12'` followed by the root's row check.
Expected: `roster ok`, then `rows ok`, each with exit 0. Before Step 6 the block fails at `wc -c`, because the file does not exist.

- [ ] **Step 8: Commit and check the seam**

```bash
git add .agents/artifacts/evidence/cutover-130-checklist.md
launch-commit --repo-root /Users/anis/tmp/nix-config --run-id <run-id> --worker-id <worker-id> -- -m "docs(issue-130/T1): roster, host identity, before-snapshot" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Then run `adopt-project verify --repo-root "$PWD" > SCR/verify-after.json` and `conformance run --purpose doctor --repo-root "$PWD"` (timeout 300 s).
Expected: verify's `result` and sorted failed ids equal Step 1's, and no failed `detail` contains `cutover-130-checklist.md`. Doctor's `outcome.status` is `passed`. If either expectation fails, return `BLOCKED seam` with both observations; never edit around it.

## Review feasibility task

```json
{"kind":"review-feasibility-task","schema_version":3,"task":{"actual_ranges":[],"commit_subject_bytes":[64,64,64],"id":1,"records":[{"bounds":[{"added_lines":80,"boundary":"all","deleted_lines":0,"record_bytes":12800,"support":{"covers":["r1-1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"r1-1","last_task":6,"owner":1,"path":".agents/artifacts/evidence/cutover-130-checklist.md"}]}}
```
