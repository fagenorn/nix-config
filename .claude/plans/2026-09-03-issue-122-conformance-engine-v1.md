# Conformance Engine v1 Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship one `conformance` engine over Resolver v1 — a closed check registry across four truth domains, six closed purposes the engine (not the caller) resolves into a check ladder, and one closed `ConformanceReport` whose `workflow_entry` form carries exactly one root cause and exits non-zero while `doctor` carries every independent finding and exits zero.

**Architecture:** A single standard-library Python script, `home/common/agent-skills/scripts/conformance.py`, installed as `~/.agents/bin/conformance`. It imports `resolve-project.py` in process through an explicit `SourceFileLoader` on its sibling file (D2) and calls the five ladder functions individually rather than calling `resolve` and catching whatever surfaces first. A static registry of check declarations — id, domain, subject kind, requirement, dependencies, reason codes, repair — drives evaluation; a static purpose table selects from it. Two subcommands: `run` produces a report, `validate-report` is the schema validator that every test and every consumer checks a report against.

**Tech stack:** Python 3 standard library only (`argparse`, `json`, `pathlib`, `os`, `shutil`, `fcntl`, `subprocess`, `platform`, `importlib`), `unittest` driven by subprocess against temporary roots, Home Manager / Nix (`home/common/agent-skills/default.nix`), Just.

## Global Constraints

- The authoritative design is `.claude/specs/2026-09-03-issue-122-conformance-engine-v1-design.md`. Cite D1–D27 by ID; never restate their rationale in code, tests, or commits.
- Four files change across the whole plan and no others: `home/common/agent-skills/scripts/conformance.py` (new), `home/common/agent-skills/tests/test_conformance.py` (new), `home/common/agent-skills/default.nix`, `justfile`. `.agents/project.json`, `.agents/instructions/bootstrap.md`, `AGENTS.md` and `CLAUDE.md` are untouched (D12, D13).
- Python standard library only. No third-party import, no network in any code path, no `sleep`, no timestamp anywhere in the report or the source.
- **Closed vocabularies, exhaustively.** `domain` ∈ `repository | compatibility | host | verification`. `requirement` ∈ `required | optional`. `status` ∈ `passed | warning | failed | not_run | suppressed`. `outcome.status` ∈ `passed | failed | incomplete`. `safety_class` ∈ `read_only | worktree | user_action | destructive`. `purpose` ∈ `workflow_entry | adoption | local | ci | fleet | doctor`. `subject_kind` ∈ `contract | projection | path | capability | host_tool | tracker | release_profile | residue | command` (D25). Every dispatch over one of these raises on its default branch rather than falling through (the bar, *Fail loud*).
- **The report has exactly six top-level members**: `schema_version`, `subject`, `request`, `outcome`, `checks`, `repairs`. `schema_version` is the integer `1`. No seventh member, no member omitted, no timestamp.
- A check object has exactly `id`, `domain`, `subject_kind`, `requirement`, `status`, `reason_code`, `repair_id`, `facts`. A repair object has exactly `repair_id`, `module`, `safety_class`, `operation`, where `operation` is `null` or `{"subcommand": <str>, "args": [<str>...]}` (D25).
- `facts` is bounded: at most eight keys; each value a bool, an int, a string of at most 200 characters, or a list of at most eight such strings. This bound is the whole no-secrets guarantee — there is no content heuristic (D9). Every authored or filesystem-derived string reaches `facts` through the one `bound_fact`/`bound_facts` helper pair (D30); no evaluator reasons about whether its own subject — a path, a command id, a run id, a JSON pointer — is short enough, because none of them has a length ceiling.
- **Outcome precedence**: `failed` if any check is `failed`; else `incomplete` if any **required** check is `not_run`; else `passed`. A `warning` never changes the outcome (D8). `primary_check_id` is the first `failed` check in emitted order, or the first required `not_run` when the outcome is `incomplete`, or `null` when `passed`.
- Checks are evaluated in dependency order and **emitted sorted by id**; `primary_check_id` is chosen over the emitted order (D24). `repairs` is deduplicated by `repair_id` and sorted by `repair_id`. A repair appears in `repairs` if and only if some emitted check names it.
- **Cascade suppression**: for a diagnostic purpose, a check whose `depends_on` closure contains a `failed` check is `suppressed`, carries exactly `{"suppressed_by": "<ancestor id>"}` in `facts`, and contributes no repair. Every check outside that closure still runs.
- Success output is `json.dump(..., sort_keys=True, separators=(",", ":"), allow_nan=False)` plus a trailing newline on stdout. `run` exits 0 for every diagnostic purpose whatever the outcome; it exits 2 for `workflow_entry` when the outcome is not `passed`.
- An unexpected engine failure prints the resolver's exact refusal shape `{"error":{"code":"resolver_failure","repair_id":"conformance.internal","violations":[…]}}` on stdout, exits 2, and prints no report (D15). The violation message is one **fixed sentence**, never the exception text, which can name a path. There is exactly **one** boundary — resolver loading, parser construction and dispatch all inside it, with argparse's `SystemExit` re-raised — and exactly one declared exception to it: the ladder's own catch inside `repository.contract.resolvable`, where a failure *of the resolver* is a check finding rather than a refusal (D29, D17). Argparse usage errors exit 2 and print no JSON.
- `--repo-root`, when **omitted**, means *discover the root*: the engine hands the resolver `None` so its ancestor walk runs from the process working directory, and adopts the discovered project root as `subject.root`. An explicit `--repo-root` is the root, with no walk-up. Resolving `"."` first and passing that would make every run from a project subdirectory report `not_onboarded` (D28).
- An evaluator returns an `Outcome` for every expected authored or environmental condition, and raises only where a closed-set dispatch inside it meets a value the set does not cover — an engine defect, not a finding (D32).
- `--purpose` and `--require` are closed argparse `choices`; `--require` reuses the resolver's `CAPABILITY_NAMES` rather than restating the eleven names.
- **The suite is offline and environment-hermetic** (D35). The central subprocess runner injects an explicit environment — it never inherits the caller's — whose `PATH` is a fixture stub bin, so no test can reach the network, a real credential, or a tool the fixture did not place. The acceptance gate against this repository's own committed root runs `--offline` and judges the registry and the report's shape, never the machine's ambient credential state.
- **Nothing in this slice writes, moves or deletes a file under the subject root.** `run` opens nothing for writing, creates no directory, and executes no repair. Every child process it starts is read-only, carries a bounded timeout, and on failure yields a `null` fact or a check finding — never an escaping exception (D19).
- **No v1 repair carries `destructive`** (D10). Elapsed time is never consulted anywhere.
- Offline is an input, never an inference: nothing probes the network to decide whether the network is available, and no check may flip `request.offline`.
- Sign commits normally; never pass `-c commit.gpgsign=false` or `--no-gpg-sign`. Every commit message ends with:
  `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>` then `Claude-Session: https://claude.ai/code/session_0128oBTKhwUFwSefRhxX2PAy`.

## Test seams

- **S1 — the CLI as a subprocess.** `python3 scripts/conformance.py run --purpose <p> --repo-root <tmp>` against temporary roots built from a copy of the repository's `.agents/project.json` and mutated per case. Assertions read parsed stdout and the exit code. Every behavioural case lands here (D16).
- **S2 — the validator as a subprocess.** `validate-report --input <file>` against hand-built report files.
- **S3 — in-process module load**, via a `load_module()` importlib helper mirroring `test_resolve_project.py:557`, reserved for the two seams no subprocess reaches: the top-level `except Exception` wrapper and the `raise` branches of closed-set dispatch sites.
- **Fake CLI on `PATH`** — a temp directory holding an executable `gh` stub exiting 0 or 1, and an empty `PATH` — covers the tracker and helper checks without a packet. `shutil.which` honours both.
- **Kernel-held `flock`** — the test process holds `fcntl.flock` on a fixture `state.lock` while the subprocess runs, proving the `live_owner` branch without a sleep.
- **The repository's own committed root** is the acceptance gate for `doctor` (D22).
- `home/common/agent-skills/tests/test_conformance.py` is the engine's whole suite, wired into `just agent-workflow-tests`. `just build` is the publication seam for `.agents/bin/conformance`. Add no other seam; a task needing one is a plan bug.

## Task index

Task 1 — Report schema, closed vocabularies and the `validate-report` subcommand, with Nix and `justfile` wiring — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py`, `home/common/agent-skills/default.nix`, `justfile` — full — [task-1.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-1.md)

Task 2 — The engine core: resolver ladder, registry, purpose selection, precedence, suppression and the two `run` report shapes — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-2.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-2.md)

Task 3 — Host installation checks: store-symlinked policy path and helper missing from `PATH` — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-3.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-3.md)

Task 4 — The offline rule and the tracker credential check — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-4.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-4.md)

Task 5 — Repository policy checks: path classification, runtime ignore sentinel, command shell indirection — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-5.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-5.md)

Task 6 — Residue checks: nested ledgers proved by `flock`, and root scratch — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-6.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-6.md)

Task 7 — The three release-profile lint checks and the end-to-end acceptance gate — `home/common/agent-skills/scripts/conformance.py`, `home/common/agent-skills/tests/test_conformance.py` — full — [task-7.md](2026-09-03-issue-122-conformance-engine-v1.tasks/task-7.md)

## Decisions

- D1 fixes the separate script and binary, used by Task 1.
- D2 and D17 fix the in-process `SourceFileLoader` import and the one-pass cached ladder, used by Task 2.
- D3 fixes the one report schema with a content-truncated `workflow_entry` form, used by Tasks 1 and 2.
- D4 and D5 fix engine-side check selection, six declared purposes, and no `--check` flag, used by Task 2.
- D6 fixes the three lint items as `repository`-domain, `optional`, `not_run`/`subject_absent`, used by Task 7.
- D7 fixes the single network-flagged check, and D20 its closed `tracker.kind` dispatch and contract-declared env scrub, used by Task 4.
- D8 fixes `warning` outside the outcome and residue as `warning`, used by Tasks 2 and 6.
- D9 fixes the bounded-`facts` no-secrets guarantee, used by Task 1.
- D10 fixes the absence of any `destructive` repair and the lock-as-evidence rule, used by Task 6.
- D11 fixes the closed scratch pattern set plus the `.gitignore` consistency test, used by Task 6.
- D12 and D13 fix the untouched contract, bootstrap and skills, used by every task.
- D14 fixes `request.platform_target` as detected with no override flag, used by Task 2.
- D15 fixes the resolver-shaped refusal for an unexpected engine failure, used by Task 2.
- D16 fixes the three test seams and the two environment fixtures, used by every task.
- D18 fixes the root-bounded symlink walk, used by Task 3.
- D19 fixes read-only bounded child processes, used by Tasks 2 and 4.
- D21 fixes additive registry growth, domain-derived purpose selection, and the offline rule arriving with its first subject, used by Tasks 2 and 4.
- D22 fixes the acceptance gate against this repository's committed root, used by Task 7.
- D23 fixes the `subject` members when the ladder cannot supply identity, used by Task 2.
- D24 fixes dependency evaluation order versus id emission order, used by Task 2.
- D25 fixes the exact member sets of check and repair objects, used by Task 1.
- D26 fixes the two nested-ledger repair ids, used by Task 6.
- D27 fixes the release-profile subject locator and its two `not_run` reasons, used by Task 7.
- D28 fixes root discovery when `--repo-root` is omitted, used by Task 2.
- D29 fixes the single exception boundary and its fixed refusal sentence, used by Task 2.
- D30 fixes the one fact-bounding helper pair, used by Tasks 1, 3, 5 and 6.
- D31 fixes `Check.findings` as the sole reason-code-to-repair declaration, used by Tasks 2–7.
- D32 fixes when an evaluator returns and when it raises, used by Tasks 2 and 7.
- D33 fixes the complete cached-stage state machine, used by Task 2.
- D34 fixes the two proofs a removable nested ledger needs, used by Task 6.
- D35 fixes the hermetic test environment and the offline acceptance gate, used by every task.
- D36 fixes the `sys.modules` registration the S3 loader needs, used by Task 2.
- D37 fixes the report invariants `validate-report` pins, used by Task 1.

## Standards review provenance

Reviewer `Codex`, isolated read-only mode, base SHA `8b69f8c182118063eeecafda81b9948100cf2eb1`, no configured focus, no fallback used. Every finding was re-verified against the live worktree before it was applied; none was rejected or deferred.

**13 accepted / 0 rejected / 0 deferred.**

Dispositions, each finding accepted and landed as the named ledger row: BLK-001 → D28, BLK-002 → D33, BLK-003 → D29, BLK-004 → D34, BLK-005 → D31, BLK-006 → D30, BLK-007 → D35, BLK-008 → D36, SF-001/SF-002/SF-003/SF-004 → D37, SF-005 → D32.

Task members are the normative executable instructions. Read this root once for shared constraints and then only the selected linked member.
