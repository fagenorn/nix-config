# Task 7: Pre-merge sweeps, threshold statement and the post-deploy protocol

Spec § Evidence and threshold (Sweep, Hold); per D12, D13, D15, D18, D19. Here is what each part does and when.

**Runs before merge (this task).**
- One `--report owners --sweep` per host root, over 2026-10-24T00:00:00Z → now.
- Each host's threshold rows and the threshold stated with reasons.
- The AC rows' evidence columns.
- The written post-deploy protocol.

**Held (not this task, D12).**
- The post-deploy boot measurement and its 25,000 verdict.
- The post-deploy sweeps per host, and any threshold change.

The issue therefore ships held, as `needs-verification`.

**Files:**
- Modify: `.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md`: AC rows `AC1`–`AC3` (evidence columns), the Built cells of cut rows 1–3, and new sections `## Pre-merge sweep` and `## Post-deploy protocol`.
- Scratch only, never committed: `S="$(launch-scope scratch --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id>)/i448"`, holding `$S/scripts/`, `$S/anis-desktop/projects/`, `$S/sweep-mbp.json`, `$S/sweep-anis-desktop.json` and their `.txt` twins.

**Interfaces:**
- Consumes:
  - the record's § Method scripts and commands (Task 3) and § Baseline table and headline;
  - the cut rows' verdict and Built cells (Tasks 3–6);
  - `--report owners --sweep` JSON: `simulated[]` rows with `step`, `spec`, `dollars_per_delivered`, `mean_saving`, `lower_bound` and `verdict`; `lineages`; and `calibration.identity_matches`.
- Produces: the complete record that sdd's final review grades, and that ship-issue reads for the hold.

**Invariants:**
- `phase_budget`'s 200,000 default is not touched in this PR, whatever the sweeps show (D13, D19).
- The record holds aggregate figures only: no transcript path, session ID, run ID or scratch path.
- The Verdict column stays for sdd's controller to write. The implementer fills only `Observed`, `Commit` and `Conditions`.

- [ ] **Step 1: Copy anis-desktop again**

Write `$S/scripts/select-sessions.sh` and `$S/scripts/extract.py`, copied byte for byte from the record's § Method blocks. Run the § Method transfer and extract commands exactly as Task 3 Step 2 did, with the window start 2026-10-24T00:00:00Z, the same timeout and the same one-retry-then-BLOCKED rule (D18).

- [ ] **Step 2: Run the sweeps**

`T="$(date -u +%Y-%m-%dT%H:%M:%SZ)"`. For each pair (label, root) in (`mbp`, `$HOME/.claude/projects`) and (`anis-desktop`, `$S/anis-desktop/projects`), run through `launch-scope exec` with timeout 3600 s:
`bash -c 'PYTHONPATH="$PWD/python" python3 -m agent_tools.agent_costs --report owners --sweep --format json --events-since 2026-10-24T00:00:00Z --events-before "$1" --projects-dir "$2" > "$3"' _ "$T" "<root>" "$S/sweep-<label>.json"`. Then run the same without `--format json` into `$S/sweep-<label>.txt`.

Expected: exit 0 four times, and `jq '.calibration.identity_matches' "$S/sweep-<label>.json"` prints `true` for each host. A `false`, or a host with fewer than 2 lineages, is recorded as such, with no threshold chosen for that host.

Read each host's threshold step with `jq -c '.simulated[] | select(.step == "threshold") | [.spec, .dollars_per_delivered, .mean_saving, .lower_bound, .verdict]' "$S/sweep-<label>.json"` and `jq '.lineages | length'`.

- [ ] **Step 2b: Pair the chosen arm against 200,000 (Phase-5 R1)**

The sweep's threshold step compares its singles against the replay's `ORIGIN.threshold` (110,000 at `agent_owner_replay.py:56`), and its phase grid against the chosen single, so neither row says whether an arm beats the live 200,000. For each host whose threshold step chose an arm other than `threshold=200000`, write `$S/scripts/pair200.py` (scratch, not the repo) that collects that host's lineages exactly as the sweep did (`agent_owner_report.collect` with the same root and window), fits `agent_owner_replay.fit(lineages)`, and builds two arms that hold every non-threshold sweep choice (boot, keepalive, help) equal: the chosen spec, and the same spec with its threshold item(s) replaced by `threshold=200000`. It prints `agent_owner_replay._Evaluation(lineages, model).verdict(arm_200k, arm_chosen)` as mean saving, lower bound and keep. Run it through `launch-scope exec` (timeout 3600 s). A host "chooses a lower arm against 200,000" only when that verdict's keep is true; record the verdict per host. A host whose sweep chose `threshold=200000` needs no pair.

- [ ] **Step 3: Write `## Pre-merge sweep`**

Record, as fenced blocks in the section, the exact Step 2 sweep command and the full source of Step 2b's `pair200.py`, so the post-deploy protocol can be followed without this plan or the scratch copy.

For each host, give: the window, the lineage count, the identity check, and one table row per threshold arm (spec, $ per delivered issue, mean saving, lower bound, verdict). Name the chosen arm, the threshold row whose verdict is `chosen`, or state `none chosen`. Add each host's Step 2b paired verdict against 200,000 (mean saving, lower bound, keep), or `chosen arm is 200,000`.

Then the statement, with each host's reason drawn from its rows: "The threshold stays 200,000 in this PR: the observed boots are not yet cut, and D13 lowers it only in a follow-up commit citing issue 448, after both hosts' post-deploy sweeps choose a lower arm against 200,000." Two cases change that wording:
- if both hosts' Step 2b pairs keep the same lower arm against 200,000 now, say so and that the post-deploy sweeps decide;
- if a host's identity check is false, say so.

- [ ] **Step 4: Write `## Post-deploy protocol` (held)**

State, as numbered steps a later session follows without this plan:

1. **Window start `W` (Phase-5 R2).** A generation activated after the merge can still be built from an older checkout (`just switch` builds the current checkout's flake), so time alone does not prove deployment. On each host `h`, list system generations with their activation times (`darwin-rebuild --list-generations` on mbp; `ssh anis-desktop 'wsl -e bash -l -c "nixos-rebuild list-generations"'` on anis-desktop) and, newest first, find the earliest generation whose closure installs the merged skills: its `-home-manager-files` store path (`nix-store --query --requisites <generation link> | grep -- '-home-manager-files$'`) contains, for every built cut, each `SlimBootContractsTest` pin at the merge commit in the installed copy of the file that test reads (`.claude/skills/<skill>/<file>`, e.g. `from-issue/resume-pack.md`, `sdd/SKILL.md`, `orchestrate-issues/SKILL.md`), matched after collapsing whitespace as the tests do. `W_h` is that generation's activation time. Record per host the generation number, `W_h` and the matched store path. A host with no such generation has not deployed: record nothing and run again later. `W` is the later of the `W_h`, as RFC 3339 UTC.
2. **Copy and measure.** Copy anis-desktop with § Method's scripts and commands, passing `W` as the window start. Then run `just agent-costs --report boot --format json --events-since W --events-before <now> --projects-dir "mbp=$HOME/.claude/projects" --projects-dir "anis-desktop=<copy>" --top 100000`.
3. **Close rule.** Every host × phase-group stratum that holds a `fresh` boot in § Baseline must hold 5 or more `fresh` boots in the window, and the window 20 or more in all. Otherwise record nothing and run again later.
4. **Weights.** Copy from § Baseline, for each such stratum `(h, g)`: the count `n0(h, g)` and the mean B without tool schemas `m0(h, g)`. Add `N0 = Σ n0` and the headline `M0` (host `all`, `fresh`, `all`).
5. **Verdict.**
   - `M1 = Σ n0(h, g) / N0 × m1(h, g)`, where `m1` is the window's mean B without tool schemas for the same stratum.
   - **Met when `M0 − M1 ≥ 25,000`.**
   - Each host's fall, `M0(h) − Σ_g n0(h, g) / N0(h) × m1(h, g)`, is reported alongside for information.
6. **Sweeps.** Run § Pre-merge sweep's command per host over `[W, now]`. A lower threshold is set only when both hosts' Step 2b pairs, re-run over `[W, now]`, keep it against 200,000, in a follow-up commit citing issue 448 (D13).
7. **Record.** Fill row `AC3`'s evidence columns and its verdict. On `met`, close the issue; otherwise keep it held.

- [ ] **Step 5: Fill the evidence columns**

Find each built cut's commit with `git log --abbrev=12 --format=%h -1 --grep '<its commit subject>'` (the subjects are in Tasks 4–6, Step 5). Each Built cell `built; net <n> bytes` becomes `built at <12-char sha>; net <n> bytes`. Then run **Skill contract tests** and **Budget**, and record their results.

- **`AC1`**
  - Observed: `in final verification (just agent-workflow-tests runs tests/test_agent_boot_report.py: BootReportTest, HostsTest)`.
  - Commit: `git rev-parse --short=12 HEAD`.
  - Conditions: `host mbp; the SDD ledger's Final verification line names the head and tree`.
- **`AC2`**
  - Observed: the built cuts with their `SlimBootContractsTest` tests and commits; the cuts not built, with their verdicts; `just agent-instruction-budget` (no `--raise-label`) `check: pass` at `<sha>`, `<UTC time>`; and `just agent-workflow-tests` and `just build`: in final verification.
  - Commit and Conditions as AC1.
- **`AC3`**
  - Observed: `before merge: § Baseline (headline <M0>) and § Pre-merge sweep (mbp: <chosen arm or none>; anis-desktop: <chosen arm or none>; 200,000 stands); the fall is not measurable before deploy and is held per § Post-deploy protocol`.
  - Commit: HEAD.
  - Conditions: hosts `mbp` and `anis-desktop` (read-only copy), the two windows, and `T`.

  The controller's verdict is expected to be `unmet`, which holds the issue as `needs-verification` (D12).

- [ ] **Step 6: Verify**

Run:
```bash
bash -c 'set -e; f=.agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
for s in "## Pre-merge sweep" "## Post-deploy protocol"; do grep -qxF "$s" "$f"; done
sed -n "/^## Pre-merge sweep$/,/^## Post-deploy protocol$/p" "$f" | grep -q "anis-desktop"
sed -n "/^## Pre-merge sweep$/,/^## Post-deploy protocol$/p" "$f" | grep -q "mbp"
sed -n "/^## Post-deploy protocol$/,\$p" "$f" | grep -q "25,000"
for a in AC1 AC2 AC3; do if grep -qE "^\| $a \|([^|]*\|){3} — \|" "$f"; then exit 1; fi; done
if grep -qE "^\| [123] \| .*\| built; net " "$f"; then exit 1; fi
if grep -qE "/private/|/var/folders/|launch-scope-|rel_[0-9a-f]{8}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-" "$f"; then exit 1; fi
if git status --porcelain | grep -vq "acceptance\.md$"; then exit 1; fi'
```
Expected: exit 0. It checks both sections, both hosts in the sweep, the literal threshold, an `Observed` cell other than `—` in every AC row, every built cut naming its commit, no private path or identifier, and only the record changed.

- [ ] **Step 7: Commit, then clean up**

```bash
git add .agents/artifacts/plans/2026-10-26-issue-448-slim-owner-boot.acceptance.md
git commit -m "docs(issue-448): pre-merge sweeps, threshold statement and the post-deploy protocol"
```

Then `rm -rf "$S"`, and confirm `test ! -e "$S"`.
