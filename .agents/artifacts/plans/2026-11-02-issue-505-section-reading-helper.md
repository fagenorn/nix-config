# Section-Reading Helper Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** A new `agent_tools` command, `skill-sections`, prints only the named `##` sections of a skill file, and from-issue's resume entry runs it so a relaunched owner reads `SKILL.md` by section. In the same slice, the Phase 2–4 producer-report clauses leave the always-read dispatch section, and the instruction corpus shrinks by 7 bytes.

**Architecture:** `agent_tools.skill_sections` is a thin argv shell over two functions. `parse` splits a file into its opening and its ordered `##` sections, skipping fenced blocks; `resolve` picks a section by exact heading, else by a unique word-boundary prefix. One command-table row installs the launcher (D1–D3, D11). In `SKILL.md`, the `resume-pack.md` index line names short handles that the helper resolves, and two dispatch paragraphs become `## Producer reports`. In `resume-pack.md`, the reading rule and check 2 run `skill-sections` (D4–D7). Contract tests run the source helper as a child process (D8).

**Tech stack:** Python 3 standard library (`argparse`, `dataclasses`, `json`, `re`, `subprocess`, `unittest`), Just, Nix.

Spec: `.agents/artifacts/specs/2026-11-02-issue-505-section-reading-helper-design.md`. A bare "Dn" cites its `## Decision ledger`. Issue: https://github.com/fagenorn/nix-config/issues/505 (parent https://github.com/fagenorn/nix-config/issues/448).

## Global Constraints

- Base `328f08da` (`origin/main` at planning). Spec commits `b4d8f2e0` and `5cb80184`, plus the planning commit that appends D10 and D11.
- Standard library only: `python/pyproject.toml` keeps `dependencies = []`. The command follows docs/standards/agent-helpers.md rules 1–3, and its tests follow rules 5 and 6 (D1, D8).
- Not edited:
  - `python/agent_tools/agent_boot_report.py` (D9).
  - `AUTO.md`, `ship-handoff.md`, `delegated-owner.md` and `standards-review.md` (D4).
  - `home/common/agent-skills/instruction-load.json` and every instruction-budget gate file (D7).
  - `tests/test_agent_tools_launchers.py` and its `LAUNCHER_FLOOR` (D8).
  - `home/common/claude-code/default.nix`: no allow entry (D4).
  - `workflow-state.py`, `CLAUDE.md` and `AGENTS.md`.
- No ceiling is raised: `just agent-instruction-budget` must pass with no `--raise-label` (D7). Task 2 Step 4 holds the measured final sizes and ceilings.
- Comments, docstrings and README sentences describe the code as it behaves at the task's commit. They cite this spec as `issue 505 Dn`, never a bare `Dn`, and carry no `TODO` or `FIXME`. Commit messages say "issue 505", never a bare `#505`.
- The live lifecycle guard reads a command's raw text, so no gate command or commit message pairs `git` with `push`.
- Run every long command in the foreground from the worktree root as `launch-scope exec --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <argv>`, with an explicit timeout. That includes every test command. Commit through `launch-commit --repo-root <ledger repo root> --run-id <run-id> --worker-id <worker-id> -- <git commit args>`. Commits are SSH-signed and end with the session's trailer lines. Scratch files go under the root that `launch-scope scratch` prints. Never run `just switch`, and never push.
- Final gate (sdd runs it once, on the final head): `just build` and `just agent-workflow-tests`, timeout 3600 s each. Task 1 also runs `just build`, because it changes `lib/agent-tools.nix` and adds an import-checked module.

## Test seams

- The CLI: `tests/test_skill_sections.py` runs `python -m agent_tools.skill_sections` from source over a skill-shaped fixture. For structural cases it imports `parse`, `resolve`, `Document`, `Section` and `Unresolved` (spec § Test seams 1).
- The skill-text contracts: `SlimBootContractsTest` in `home/common/agent-skills/tests/test_workflow_skill_contracts.py` runs the source helper as a child process, with `PYTHONPATH` set to `python/`. It pins identifiers only (D8):
  - every verified-pack section span resolves;
  - `Phase 0` to `Phase 7` resolve;
  - the entry's argv follows its checks;
  - the producer-report argv sits in `## Producer reports` and not in the dispatch section.
- Shell-example vetting: `skill-sections` joins `COMMAND_VOCABULARY` in `test_shell_example_contracts.py` (spec § Test seams 3).
- Build and gate: `just build` (the import check and the command-table assertion) and `just agent-instruction-budget` (spec § Test seams 4).

## Delivery estimate and boundaries

The figures come from a scratch prototype of both tasks. In it the drafted tests went red at base and green after, `just build` passed in 80 s, and the budget gate printed `check: pass`. Eleven files change, about 420 lines in all:
- the module, about 160 lines, and its test, 201 lines;
- one-line or one-section edits to `lib/agent-tools.nix`, the `justfile` and two READMEs;
- `SKILL.md` +6/−5 and `resume-pack.md` +2/−2;
- the contract tests +41/−10 and the vocabulary +1/−1;
- the acceptance record.

That is one review package and one slice. Task 2 follows Task 1 because its contract tests run Task 1's helper. Task 1 alone leaves the tree green, with the helper not yet called.

## Task index

Task 1 — The `skill-sections` command — `python/agent_tools/skill_sections.py`, `tests/test_skill_sections.py`, `lib/agent-tools.nix`, `justfile`, `python/README.md` — full — [task-1.md](2026-11-02-issue-505-section-reading-helper.tasks/task-1.md)

Task 2 — The resume entry reads `SKILL.md` by section — `home/common/agent-skills/skills/from-issue/SKILL.md`, `home/common/agent-skills/skills/from-issue/resume-pack.md`, `home/common/agent-skills/tests/test_workflow_skill_contracts.py`, `home/common/agent-skills/tests/test_shell_example_contracts.py`, `home/common/agent-skills/README.md`, `.agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.acceptance.md` — full — [task-2.md](2026-11-02-issue-505-section-reading-helper.tasks/task-2.md)

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | code | Task 2 | Task 1's `tests/test_skill_sections.py`: `SkillSectionsCommandTest`, `ParseTest` and `ResolveTest`, 18 tests, red at Task 1's start commit (Step 2). Task 2's `home/common/agent-skills/tests/test_workflow_skill_contracts.py::SlimBootContractsTest::test_the_entry_runs_its_checks_before_any_skill_section`, `::test_every_section_and_file_the_verified_pack_reads_exists`, `::test_the_resume_read_list_names_producer_reports_and_every_phase_resolves` and `::test_producer_report_rules_left_the_always_read_dispatch_section`, red at Task 2's start commit (Step 2). `just agent-instruction-budget` with no raise label passes in Task 2 Step 4, and again as the required CI check `Instruction Budget`. `just build` and `just agent-workflow-tests` run green at the final gate. Task 2 writes acceptance-record row `AC1`. |
| AC2 | evidence | Task 2 | Command: `just agent-costs --report boot` on mbp. Conditions: fresh owners in the 7 days after the first `just switch` on mbp that includes the merge, read only once the boot report attributes `skill-sections` output to the file it reads (D9). Threshold: mean from-issue `SKILL.md` tokens per fresh boot (skill bodies + skill files) ≤ 4k. Task 2 writes row `AC2` as `not measured — post-deploy (D9, D10)`. The delivery never claims AC2: it stays evidence-pending, and ship holds the issue for it. Planning projects a Phase 6–7 resume boot at 20,032–21,941 bytes of `SKILL.md`, about 5–6k tokens, so the threshold is likely missed without a follow-up (D10). |

## Decisions

The plan rests on D1–D9. Planning appends two rows to the spec's ledger. D10 records the measured per-phase read against AC2's 4k threshold, with scope unchanged. D11 fixes the helper's byte output, its stderr report and its `\n`-only line split.

Task 2's exact text measures −80 (index line), −10 (heading swap) and +83 (entry), so the corpus falls by 7 bytes. The spec's D7 candidate measured −80, −9 and +86, a 3-byte fall. Either way D7's three bounds hold: the corpus does not grow, `resume-pack.md` grows by at most 99 bytes, and `SKILL.md` does not grow.

## Standards review provenance

Reviewer: Codex (`codex-plan-review`, gpt-6-astra, xhigh), isolated read-only mode, base 328f08da, no fallback. Blocking: none. Should fix: 2 accepted — R1 (Task 2 Step 2 keeps the exit status with `pipefail` and shows `OK`; Step 4 already did) and R2 (Task 1 adds `test_only_a_line_feed_ends_a_line`, pinning D11's `\n`-only split; 18 tests). Rejected: 0. Deferred: 0.

---

## Review feasibility delivery

```json
{"actual_evidence":{"head":"513100fddf6670866ba1792ae8c9e98f9ba6cc64","kind":"git-range-ownership/v1","process_ranges":[{"base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","boundaries":["all"],"head":"198d632cd7229838d3dc683b46b8ac190ee2cfc3"}],"tree":"e02d1478868bc380e475d4912bba02264eddb899"},"boundaries":[{"acceptance":"Issue 505 complete: AC1 green under just agent-workflow-tests, just build and just agent-instruction-budget; AC2 evidence pending","depends_on":[],"id":"all","parent":null,"prerequisite":{"kind":"delivery-base"},"process_commit_subject_bytes":[64,64,64,64,64],"process_forecast_ids":["s","p","t1","t2"],"process_package":{"plan":".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.md","spec":".agents/artifacts/specs/2026-11-02-issue-505-section-reading-helper-design.md","tasks":[".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.tasks/task-1.md",".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.tasks/task-2.md"]},"tasks":[1,2]}],"delivery_base":"328f08daca0cd21e71a622f98c91c3f3a7a6728c","derived_from":null,"kind":"review-feasibility-delivery","process_records":[{"bounds":[{"added_lines":260,"boundary":"all","deleted_lines":0,"record_bytes":32768,"support":{"covers":["s"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"s","last_task":2,"owner":0,"path":".agents/artifacts/specs/2026-11-02-issue-505-section-reading-helper-design.md"},{"bounds":[{"added_lines":120,"boundary":"all","deleted_lines":0,"record_bytes":20480,"support":{"covers":["p"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"p","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.md"},{"bounds":[{"added_lines":360,"boundary":"all","deleted_lines":0,"record_bytes":28672,"support":{"covers":["t1"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t1","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.tasks/task-1.md"},{"bounds":[{"added_lines":240,"boundary":"all","deleted_lines":0,"record_bytes":24576,"support":{"covers":["t2"],"kind":"authored-cumulative/v1"}}],"change":"add","id":"t2","last_task":2,"owner":0,"path":".agents/artifacts/plans/2026-11-02-issue-505-section-reading-helper.tasks/task-2.md"}],"proposed_boundary":"all","schema_version":3}
```
