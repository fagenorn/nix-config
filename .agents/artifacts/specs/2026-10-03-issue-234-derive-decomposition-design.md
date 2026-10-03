# Issue 234 — DERIVE delivery decomposition

[DERIVE design](2026-10-03-issue-234-retained-review-derivation-design.md)
(“Spec” below) keeps D1–D18, R1–R4 and every behavioral contract binding. This
document only assigns them to two child deliveries, Q1–Q4 below. Parent
[234](https://github.com/fagenorn/nix-config/issues/234) stays open until both
children are delivered and a parent audit confirms the full scope. Parent
[226](https://github.com/fagenorn/nix-config/issues/226) and
[EVIDENCE 235](https://github.com/fagenorn/nix-config/issues/235) keep their scope.

## Problem

DERIVE's single `derive` boundary (base `93e6059a`) cleared G0 at `058ac21e`
(exit 0, 9 files, largest member 65,534 B). It was 2 B short of nine payloads.
Task 1 then added the forecast record `t1-5` (2,560 B) plus small spec and member
growth. At checkpoint `d5febe33`, G0 `--completed-through 1` exits 3:
`decompose_required`, violation `member_count`, file_count 11 (10 payloads against
8), total 490,779 B, largest 61,596 B. A second run was byte-identical, and
`validate-result --producer-exit 3` exits 0. The plan rule is that exit 3 stops
for decomposition, so Tasks 2–8 are unstarted.

The overflow comes from packing fragmentation, not from aggregate size. The total
is 490,779 B against an aggregate cap of 524,288 B, but whole records of
30–36 KB pack two to a 64 KiB payload. Nothing in the contract changes: caps,
records and forecasts stay honest.

## Frozen parent state

| Work | Identity | State |
|---|---|---|
| Task 1 (Task-7 model, Task-8 effect) | `7b782f9a`, `0c9bb299`, `0facdd3f`, `218b70bf`, `92a0c79c` | Implemented. The re-review resolved I1, I2, M1 and M3. It left **N1 Important** open: `validate_task7` raises a raw `TypeError` on an unhashable `operation` instead of `invalid_table`. It also left **N2 Minor** open: overlapping move-root new prefixes make derive and validate disagree. Minors M2, M4, M5 and M6 are deferred to the final review. **Unaccepted.** |
| Process | Spec/plan `6e710165..058ac21e`, D18 `0c9bb299`, checkpoint `d5febe33` | Parent evidence. It is never relabelled as a child base or package. |
| Tasks 2–8 | — | Unstarted. |

The branch, worktree and SDD workspace
`.superpowers/sdd/wt-worktree-issue-234-orchestrated/` (with `progress.md`,
`gate-task-1.md`, `task-1-report.md` and the three review packages) are all
preserved.

## Solution

There are two children in the chain CORE → **SOURCE → REPLAY** → EVIDENCE. Each
starts from integration that contains its accepted, published predecessor. Each
pins its own immutable base and authors a complete own process package (spec,
indexed v3 plan, members, forecasts, subject reserves). Each must then clear its
own G0 with CORE's published projector before product work.

| Design ID / slug | Spec scope (D-rows) | #234 plan tasks | Usable on its own |
|---|---|---|---|
| `DP234-SOURCE` / `retained-source-models` | D2, D4, D5, D11, D12, D15, D17–D18; R1, R3, part of R4; § Issue-121 adapter, § Historical outcomes, § Task-7 table, § Issue-100 payload | 1–3 | The Task-7 model, the I1-corrected issue-121 adapter (both entry points) and the issue-100 verifier, each with its `derive_*`/`validate_*` pair and a portable real-Git tier in `agent-workflow-tests`. It adds no command rows. |
| `DP234-REPLAY` / `retained-derivation-replay` | D1, D3, D6–D10, D13–D14, D16; rest of R4; § Bundle, witness and anchor, § Commands, § DERIVE's own delivery gate | 4–8 | It publishes `derive-review-feasibility-fixtures` and `replay-retained` (source and built) and delivers the full-shape tier, `agent-retained-tests`. That tier is the authoritative real-input acceptance for SOURCE's modules too. It includes the G2 source pin. |

### Q1 — Split by command publication, not by task count

SOURCE delivers library contracts. REPLAY makes them usable as commands, and the
#226 rule "registration, build and installed checks belong to the stage that
makes each command usable" puts every command row, launcher test and the
full-shape tier in REPLAY. SOURCE is still independently verifiable. Its portable
tier is red at base, because the modules do not exist there. Its I1 correction is
the issue's standalone Important finding.

Rejected: three children (models / commands / full-shape). A test-only child is
not usable on its own, and the two-way split already fits with margin. Also
rejected: a split at Task 5 (derive vs replay). The full-shape tier needs both
commands, so DERIVE would publish one command without its real-input acceptance.

### Q2 — Task 1 is recovered by SOURCE, with N1 fixed

SOURCE's first task recovers the Task-1 effects by blob from `92a0c79c`:

| Effect | Blob |
|---|---|
| `review_task7.py` | `fc721644` |
| `retained_review_test_support.py` | `15e28b21` |
| `test_review_task7.py` | `b49b3af9` |
| The one-line `agent-workflow-tests` entry | — |
| The two `LEGACY_MIGRATION_INPUTS` allowances | — |

These effects go through SOURCE's recovery manifest. The task must:

- fix **N1**: every malformed row, including an unhashable `operation`, raises
  `EstimateError("invalid_table")`;
- fix **N2**: overlapping move roots are refused, or resolved identically by
  derive and validate;
- disposition M2, M4, M5 and M6 explicitly.

Old commits, signatures and reviews are provenance only. The task receives a
fresh review in SOURCE's own range.

`review_task7.py` measures 27,007 B against a 27,012 B bound. The fix needs a
revised bound, which the measurement below charges as 28,672 B, and the test
bound as 23,552 B.

### Q3 — Retained-object adversarial checks split by tier

SOURCE's final gate includes a fresh adversarial reviewer. On disposable
alternates-backed clones of the real retained objects, that reviewer repeats the
I1 graft and rehash reproduction against the library entry points `derive_121`
and `reconstruct_boundary` `tasks-1`. The clean control must yield exactly 30
edges, and the source objects must stay unchanged.

The committed full-shape tests are REPLAY's: the derive command, `tasks-1`, the
real pinned-renderer Task-7 run and the issue-100 byte domains. REPLAY's G2 pins
the complete `python/` closure, including SOURCE's modules. A SOURCE defect found
there is fixed in REPLAY's range and re-reviewed. It is never hidden in EVIDENCE.

### Q4 — Dependencies

- REPLAY is blocked by SOURCE.
- EVIDENCE 235 is additionally blocked by REPLAY, because it consumes both
  commands and REPLAY's reviewed `--tool-commit`.
- 235's existing block on parent 234 remains.
- D16 stands: REPLAY makes no CLAUDE.md edit, and EVIDENCE owns the
  architecture sentence.

## Measured fit (CORE projector, synthetic committed plans)

Each candidate was committed as a real v3 plan on a scratch clone. The plan root
had a task index and members with canonical JSON blocks. Process records were
bound at estimated spec, plan and member sizes, and product records carried the
#234 committed forecasts. The candidates were projected with
`core_gate source <clone> python3 -m agent_tools.review_feasibility project
--completed-through 0` on published CORE (`5f865639`). Each projection was run
twice (byte-identical) and checked with `validate-result` (exit 0).

The SOURCE row's base is integration. The REPLAY row's base is integration plus
the Task-1 files as simulated SOURCE output. The cap is 8 payloads; `file_count`
includes the root.

| Child | Inputs | Exit / state | file_count | largest | root | total |
|---|---|---|---|---|---|---|
| SOURCE | Process 80,896 B (spec 28,672, plan 15,872, three members), product as #234 T1–T3 with the Q2 bounds | 0 complete/within | 6 | 58,744 | 8,064 | 270,096 |
| REPLAY | Process 91,392 B (spec 28,672, plan 15,872, five members), product as #234 T4–T8, support modify 10,240 | 0 complete/within | 6 | 63,372 | 9,857 | 275,615 |
| SOURCE stress | Spec 40,960, plan 20,480, members ×1.4, product ×1.25, three subjects per task | 0 complete/within | 8 | 64,355 | 11,342 | 350,093 |
| REPLAY stress | Same | 0 complete/within | 8 | 63,005 | 14,031 | 359,012 |

Each child leaves three spare payloads, and it still fits with process up 40% and
product up 25%. The binding risk is REPLAY's root, at 14,031 B against 16,384 B
under stress. REPLAY should keep its subject reserves at two per task plus ten
for process. These are synthetic projections of forecasts, not measurements of
committed child plans. Each child's own G0 decides fit.

## Parent acceptance

234 closes only after an audit maps each acceptance criterion to the published
SOURCE or REPLAY artifacts. The 30 assignments, I1, the 173-row table, Task 8 and
issue 100 map to SOURCE. Commands, bundle determinism, replay and full-shape map
to REPLAY. A blocked child leaves 234 open. Nothing here changes caps, the Spec's
out-of-scope list or EVIDENCE's scope.
