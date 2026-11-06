# Bridge Minor Deprecations Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Ship platform `1.1.0`, a bridge minor whose manifest declares the legacy `.claude/skills.config.json` and its adoption writer as deprecated, with successor and migration ids, so `resolve-project platform-status` reports a non-empty `platform.deprecations` on every host after a switch (issue 580, checklist item C11.a).

**Architecture:** The manifest's `deprecations` array stops being opaque: `agent_platform.validate_manifest` checks a closed six-member entry (D1). `resolve-project platform-status` already republishes the array verbatim in its `platform` block; it also gains a per-project warning, `deprecated_uses`, on the named project and on every fleet row, computed by a read-only presence check that never changes a compatibility verdict or an exit code (D2). The committed manifest then moves to `1.1.0` with the two entries, and `python/README.md` documents the shape, the warning and the migration route (D5, D6).

**Tech stack:** Python 3 standard library (`os.path.lexists`, `pathlib`), `unittest`, JSON, Home Manager (the manifest is installed by `home/common/agent-skills/default.nix`, unchanged).

Issue: https://github.com/fagenorn/nix-config/issues/580. No spec: the issue, its owner comment of 2026-11-03 (O1–O4 below) and this plan's `## Decisions` are the decision record. Background: `.agents/artifacts/specs/2026-11-03-issue-130-cutover-preparation-design.md` (C11 row, F2) and issue 66's resolution, section "Deprecation and removal".

## Global Constraints

- Base `87f6bb16` (`origin/main` at planning). Only the files in the Task index change.
- `resolve` output, its refusals and its exit codes do not change: deprecation warns, normal resolution continues (issue 66).
- `platform-status` stays read-only and starts no child process (R3.6): no `git`, no file opened for writing, no directory created.
- `removals` stays opaque: validated as an array, entries never read (D7).
- No conformance check, repair-catalogue entry, `adopt-project` behaviour change or Nix change (D6). `adopt-project` output does follow the installed manifest's version (D8), so Task 3 derives the adopt tests' pinned `1.0.0` from the committed file.
- Tests run from the worktree root as `env PYTHONPATH="$PWD/python" python3 -m unittest <test file path> -k <name>`, foreground, timeout 600 s, output cut with `2>&1 | tail -5`.
- Commits: subject `feat(issue-580): …` or `test(issue-580): …`, say "issue 580", never a bare `#580`, end with the session's `Co-Authored-By` trailer. Never run `just switch`, never push.
- sdd's final gate runs `just build` and `just agent-workflow-tests` once on the final head (timeout 3600 s each).

## Test seams

1. `home/common/agent-skills/tests/test_resolve_platform.py`: the manifest validator through the `resolve` subprocess against an installed fixture manifest (`set_manifest(mutated_manifest(...))`), and the committed manifest (`CommittedManifestTest`).
2. `home/common/agent-skills/tests/test_resolve_platform_status.py`: the `platform-status` subprocess with `--repo-root` and `--fleet`, fixture roots from `make_root`, registry staged with `install_registry`.
3. `home/common/agent-skills/tests/test_adopt_project.py` and `test_adopt_apply.py`: regression only. They install the committed manifest verbatim, so Task 3 re-derives their two literal `1.0.0` pins from it; they gain no new behaviour.

## Task index

Task 1 — Closed deprecation entry in the manifest validator — `python/agent_tools/agent_platform.py`, `home/common/agent-skills/tests/test_resolve_platform.py` — full — [task-1.md](2026-11-03-issue-580-bridge-minor-deprecations.tasks/task-1.md)

Task 2 — `platform-status` warns on deprecated uses — `python/agent_tools/resolve_project.py`, `home/common/agent-skills/tests/test_resolve_platform_status.py` — full — [task-2.md](2026-11-03-issue-580-bridge-minor-deprecations.tasks/task-2.md)

Task 3 — Platform 1.1.0 declares the legacy skills config deprecations — `home/common/agent-skills/platform-manifest.json`, `home/common/agent-skills/tests/test_resolve_platform.py`, `home/common/agent-skills/tests/test_adopt_project.py`, `home/common/agent-skills/tests/test_adopt_apply.py`, `python/README.md`, `.agents/artifacts/plans/2026-11-03-issue-580-bridge-minor-deprecations.acceptance.md` — full — [task-3.md](2026-11-03-issue-580-bridge-minor-deprecations.tasks/task-3.md)

All three are `full`: Task 1 changes the manifest's public schema, Task 2 the `platform-status` report interface, Task 3 the platform version every host activates.

## Acceptance map

| AC | Kind | Task | Check |
|----|------|------|-------|
| AC1 | evidence | Task 3 | Narrowed by O4 to C11.a. After the owner switches each of `mbp` and `eleven-m5` to a generation containing this change, `resolve-project platform-status` on that host exits 0 with `platform.platform_version == "1.1.0"` and `platform.deprecations` holding at least 1 entry (2 expected). Acceptance-record row `AC1` in `2026-11-03-issue-580-bridge-minor-deprecations.acceptance.md`, created `unverified` by Task 3 and filled in by the owner per host after the switch. C11.b–d are not graded here (O4: issues 581, 582, 555). Code precondition: `CommittedManifestTest::test_it_declares_the_bridge_minor_deprecations` (Task 3). |

## Decisions

Owner decisions, binding (issue 580 comment, 2026-11-03):

- **O1** The planner proposes a closed deprecations entry shape and how `platform-status` and fleet preflight warn on it; recorded here as D1 and D2.
- **O2** Scope option b: declare only deprecations whose successor and migration already ship (issue 66). Today: the legacy `.claude/skills.config.json` and its adoption writer. `bindings.deploy` and `release deploy inspect` are declared later, with their successors (issues 555, 579).
- **O3** Declare from the four known paths F1 removes (the legacy file's writer, `release_bridge`, `release deploy inspect`, `bindings.deploy`), filtered by O2. Later paths get their own minor.
- **O4** Done when C11.a reads green (`platform.deprecations` non-empty) on `mbp` and `eleven-m5` after the owner switches; evidence. The issue stays open as needs-verification until both hosts are switched.

Planning decisions:

- **D1 Entry shape.** A `deprecations` entry is an object closed on exactly `id`, `kind`, `subject`, `since`, `successor`, `migration`. `id`, `subject`, `successor`, `migration` are non-empty strings; `id` is distinct across entries. `kind` is one of `project_file` (the subject is a repository-relative POSIX path a project may hold: not absolute, no backslash, no empty, `.` or `..` segment) or `platform_behavior` (the subject is a free-text name of shipped platform behaviour; nothing per project). `since` is strict SemVer `MAJOR.MINOR.0` with `MINOR >= 1`: deprecation begins only in a minor (issue 66). Violations refuse the manifest as `resolver_failure` with repair ids `platform.manifest.deprecations.<not_array|not_object|member_missing|member_unexpected|not_string|duplicate_id|kind_unknown|since_not_minor|subject_not_relative_path>`. Rejected: an opaque or open shape (cannot drive a warning); a structured subject object (one more nesting for two kinds).
- **D2 Warning.** `platform-status` keeps republishing `platform.deprecations` verbatim (the lifecycle-status notice). The `project` block and every `fleet` row gain `deprecated_uses`: the ascending ids of the `project_file` entries whose `subject` exists under that root by `os.path.lexists` (a dangling symlink counts), or `null` when the root is not a directory. It never changes `compatible`, `reason_code`, `repair_id` or the exit code, and `resolve` never reads it. Presence, not git tracking, because R3.6 forbids a child process; an untracked or ignored copy is still reported, and removal readiness stays judged by C11.b. Rejected: a non-zero exit or incompatible verdict (issue 66: warn, resolution continues); a separate top-level `warnings` member (a second place to join rows).
- **D3 Version invariants live on the committed file.** The validator checks only the shape of `since`. That each `since` is at most `platform_version` and shares its major is pinned by `CommittedManifestTest`, so fixtures that mutate only `platform_version` (`1.0.0`, `1.4.2`, `2.0.0` in the resolver and conformance suites) stay valid. Rejected: a cross-member validator rule (breaks those fixtures for no runtime gain; F1's `2.0.0` drops the entries anyway).
- **D4 Report interface version.** `PLATFORM_STATUS_SCHEMA_VERSION` goes from 1 to 2, because the closed report gains a member. No repository code parses the report.
- **D5 The release.** `platform_version` `1.1.0`; `project_schema_versions`, `resolved_schema_version`, `migrations`, `removals` unchanged. Two entries, both `since` `1.1.0`, successor `resolve-project resolve`, migration `legacy-skills-config.retire`: `legacy-skills-config` (`project_file`, `.claude/skills.config.json`) and `legacy-skills-config-writer` (`platform_behavior`, `adopt-project legacy binding config rewrite`, i.e. `adopt_planning.legacy_binding_operations` and the `release_bridge.project_legacy_deploy` projection it applies). Every fleet contract declares `[1.0.0, 2.0.0)`, which admits `1.1.0`. `release_bridge.plan_legacy_release`, `release deploy inspect` and `bindings.deploy` are not declared (O2, O3).
- **D6 Migration route is documented, not new code.** `legacy-skills-config.retire` is a stable id whose steps are in `python/README.md`: confirm `resolve-project resolve` succeeds; re-point every reader of the legacy file to `resolve-project resolve`; `git rm .claude/skills.config.json`; confirm `deprecated_uses` no longer lists the id. Every step uses a shipped command, and the writer only rewrites an existing file, so it never recreates a removed one. Rejected: a conformance check or repair-catalogue entry (doctor integration is outside O1's scope).
- **D7 `removals` stays opaque** until a major declares one. The non-finite-number fixtures that used `deprecations` as an untyped slot move to `removals`.
- **D8 Adopt tests read the committed version.** `adopt_planning.derived_interval` floors a newly amended contract at `manifest["platform_version"]` and the adoption plan republishes that version, so moving the manifest to `1.1.0` changes adopt output by design. The two assertions that pin `1.0.0` (`test_adopt_project.py` `test_platform_block_is_the_three_reproducible_manifest_values`, `test_adopt_apply.py` `test_the_committed_contract_declares_the_platform_and_new_homes`) are derived from the committed file in Task 3, so the next minor does not break them again. Rejected: installing a frozen `1.0.0` fixture manifest in the adopt suites (they would stop exercising the manifest hosts actually install).

---
