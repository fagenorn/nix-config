# CORE correctness review record — issue 259

Issue: https://github.com/fagenorn/nix-config/issues/259
Subject: https://github.com/fagenorn/nix-config/pull/246, merge `93e6059a6fece769a621657c5889278b9cb9e0d7`
REVIEW_SHA: `8c475824d7ea3b766183e5514b5ed33f623b1749`
Scope: full — 25 of 25 product files, each read whole

## Reviewer

- Agent type: `reviewer`, dispatched by type, read-only (Read, Glob, Grep, Bash, Skill).
- Model: `claude-opus-5-5`; effort: high.
- Sessions: B1 `a6c32b7896d55d81a`, B2 `a4d48b360a8518dbf`, B3 `a5b41737516a6f768`, B4 `aa229af01c3c0e4fa`, B5 `ad27d678ae61aba91`.
- Independence: PR 246's 14 non-merge commits carry the Co-Authored-By trailers Codex ×13 and Claude Opus 5.5 ×1 (`6cdb9b9`, the shipping session's fix of CR-001 to CR-003), counted with `git log --no-merges --format='%(trailers:key=Co-Authored-By,valueonly)' 93e6059a^1..93e6059a^2`. The reviewers are a different model family from Codex, and each was a fresh session given none of PR 246's spec, plan or PR thread; none edited a file.
- Spec consultations: none.

## Coverage

| # | Path | Blob | Lines | Read | Batch | Verdict |
|---|---|---|---|---|---|---|
| 1 | `CLAUDE.md` | `d40bc59f949bf538761db94a554544cce06ee139` | 71 | whole | B4 | clean |
| 2 | `home/common/agent-skills/default.nix` | `f430497f25b130bdb1f02c259d9882d6c2761191` | 185 | whole | B4 | B4-I1 |
| 3 | `home/common/agent-skills/scripts/artifact_budget.py` | `b33c2459bbc1d574268de22ef94c2182761ed628` | 1194 | whole | B3 | B3-I1, B3-I2, B3-M1 |
| 4 | `home/common/agent-skills/skills/sdd/SKILL.md` | `e6722729547b3ca6b297056644d690844eba506d` | 302 | whole | B5 | B5-I2, B5-I3, B5-I4, B5-M2, B5-M3 |
| 5 | `home/common/agent-skills/skills/sdd/final-review.md` | `8e8535cae14325d75acfe319edbaadaf2486799d` | 220 | whole | B5 | B5-I1 |
| 6 | `home/common/agent-skills/skills/sdd/fix-loop.md` | `7e2986ad24af1344cd76e5df98b6b9c3fbbeafbd` | 47 | whole | B5 | clean |
| 7 | `home/common/agent-skills/tests/test_artifact_budget.py` | `55e4842f8e4ec5494fa7dd2673f35409218ccbca` | 1849 | whole | B3 | B3-I3, B3-I4, B3-I5 |
| 8 | `home/common/agent-skills/tests/test_review_package.py` | `24c41d0610e1925f2f82a50dec0963ea8622fae2` | 1681 | whole | B1 | clean |
| 9 | `home/common/agent-skills/tests/test_workflow_skill_contracts.py` | `137ebfe707aaa877e9c0d9cb653d096b80bb72a8` | 3299 | whole | B5 | B5-I5, B5-M1 |
| 10 | `justfile` | `f0f4d1cde0d739517df101c76d05604c3511d34d` | 325 | whole | B4 | clean |
| 11 | `lib/agent-tools.nix` | `52f1398f1f048cebfd27a27ff54849a4cc14b9dd` | 114 | whole | B4 | clean |
| 12 | `python/agent_tools/review_actual.py` | `12629c87c57783e5588ea95f78f8b9c68c86b037` | 531 | whole | B1 | B1-I1, B1-I2, B1-I4 |
| 13 | `python/agent_tools/review_budget.py` | `8a98021ba9c2ff03963794ea23408079b7f0588b` | 143 | whole | B2 | clean |
| 14 | `python/agent_tools/review_feasibility.py` | `fd58c8bf524b5b27b851338e500f9093b267d5a6` | 58 | whole | B2 | B2-I1, B2-M4 |
| 15 | `python/agent_tools/review_forecast.py` | `ab4b4697bf55ae20f8696b2918f77fa4c118ef19` | 592 | whole | B2 | B2-C1 |
| 16 | `python/agent_tools/review_git.py` | `419ff1e8a8adf43f5a3aa3d5375833414c2f2d5e` | 267 | whole | B1 | B1-M1, B1-M3 |
| 17 | `python/agent_tools/review_pack.py` | `3e0a46fad8b19389add06656d06f800a649828cf` | 203 | whole | B1 | clean |
| 18 | `python/agent_tools/review_package.py` | `390d33fde0c3c4efa41dea3efebb0a5db26428bb` | 75 | whole | B1 | clean |
| 19 | `python/agent_tools/review_projection.py` | `09f5fc860c5e2a517e27ae7f7dc659bb14edc843` | 383 | whole | B2 | B2-M1, B2-M2, B2-M3 |
| 20 | `python/agent_tools/review_publish.py` | `0fdedeb1f441184b9e28ef059425858cfe3f1cb7` | 647 | whole | B1 | B1-I3, B1-M2, B1-M4, B1-M5 |
| 21 | `tests/test_agent_tools_launchers.py` | `13304830d4839171f0b4a079a40f72f49444c032` | 736 | whole | B4 | B4-M1 |
| 22 | `tests/test_review_feasibility.py` | `71df9e9f0d45fd1c68f3978fd0bc414fc3ec83c7` | 947 | whole | B2 | B2-I2 |
| 23 | `tests/test_review_history.py` | `f815c03d8c09f82fbfe78c02195c27a789cafa03` | 380 | whole | B2 | clean |
| 24 | `tests/test_review_pack.py` | `24a8b224d9c7180b507af8a56bfd30662660cb35` | 238 | whole | B1 | clean |
| 25 | `tests/test_review_projection_cases.py` | `691554e5eddeab13dbda62ccf1882e8042abc5d1` | 310 | whole | B2 | clean |

## Findings

| ID | Severity | Location | Defect | Disposition | Evidence |
|---|---|---|---|---|---|
| B2-C1 | Critical | `python/agent_tools/review_forecast.py:230` | `tree_entry` runs `git ls-tree` without `--literal-pathspecs`, so a path that starts with `:` is read as pathspec syntax. For an absent look-alike path both replay sides return None, the whole-path pre-image and post-image proofs in `reconstruct_owned` pass vacuously, and a deletion can be treated as proven; `_blob_at` in review_actual.py already passes the flag. | fixed | `cfb35992`; `tests/test_review_feasibility.py::TreeEntryTest.test_colon_prefixed_path_is_a_literal_name_not_a_pathspec`; failing first: `AssertionError: unexpectedly None : a file literally named like pathspec syntax is a tree entry` |
| B1-I1 | Important | `python/agent_tools/review_actual.py:151` | `RECORD_OPERATIONS` accepts `T`, but `git diff` emits two `diff --git` sections for one type-changed path (file to symlink), so the section count differs from the path count and the package fails with "diff coverage does not match paths". No test covers a type change. | fixed | `5e26727b`; `home/common/agent-skills/tests/test_review_package.py::ReviewPackageCliTest.test_file_to_symlink_type_change_is_one_covered_record`; failing first: `AssertionError: 2 != 0 :` |
| B1-I2 | Important | `python/agent_tools/review_actual.py:522` | `git show -s --format=%s` runs without `--no-show-signature`; with `log.showSignature` set, Git prints verification text on stdout, so the manifest subject becomes "No signature" plus the subject and the package is still reported `complete`. (also `review_projection.py:115`) | fixed | `ea3549b4`; `home/common/agent-skills/tests/test_review_package.py::ReviewPackageCliTest.test_commit_subjects_ignore_log_show_signature`; failing first: `AssertionError: Lists differ: ['gpg: Good signature from fixture\nchange a'] != ['change a']` |
| B1-I3 | Important | `python/agent_tools/review_publish.py:642` | Production detail publication swaps the working directory and restores it with an unguarded `os.fchdir`; a failed restore leaks the descriptor and reports `failed` after the package exists, so every retry hits EEXIST. The parent-swap and restore-failure tests exercise only the `final_parent_fd` twin in `publish_package`, which production never uses. | filed | issue pending (bar 5) |
| B1-I4 | Important | `python/agent_tools/review_actual.py:452` | `_ef_designer_evidence` probes only the head side for the generated-file contract; a base side without a `[Migration(` attribute makes `_ef_designer_side` raise, failing the whole package where python/README.md promises `decompose_required`. | filed | issue pending (bar 5) |
| B2-I1 | Important | `python/agent_tools/review_feasibility.py:47` | `validate-result --input` opens the input's parent directory with O_NOFOLLOW, so a valid regular file directly under a symlinked directory such as `/tmp` is refused with exit 2 (reproduced with `/tmp/zz259.json`), while the same file under `/tmp/x` is accepted. | filed | issue pending (bar 5) |
| B2-I2 | Important | `tests/test_review_feasibility.py:358` | `test_process_tail_cannot_hide_product_or_merge` commits only an undeclared product file; no test puts a merge in the metadata tail, so deleting the first-parent-chain refusal at review_forecast.py:475 leaves the suite green. | filed | issue pending (bar 5) |
| B3-I1 | Important | `home/common/agent-skills/scripts/artifact_budget.py:288-292` | `_capture_artifact` and `_read_regular` open with O_NOFOLLOW but without O_NONBLOCK, so a FIFO as a plan member, shard or `--input` blocks forever before the regular-file check (reproduced: `_read_regular` on a FIFO was killed by `timeout 5`); this is the CR-003 defect class in a second module. | filed | issue pending (bar 5) |
| B3-I2 | Important | `home/common/agent-skills/scripts/artifact_budget.py:584` | Several checks test set membership before type, so an unhashable JSON value (a list for `context_lines`, `producer`, a verdict, `review_state` or `state`) raises `TypeError` and a traceback instead of the one-line exit-2 refusal the tests pin. | filed | issue pending (bar 5) |
| B3-I3 | Important | `home/common/agent-skills/tests/test_artifact_budget.py:1584-1585` | The `notes.md` case runs on a plan whose only member is `task-2.md`, so the gap check refuses it anyway; removing the unknown-member refusal would leave the test green and nothing pins "unknown review member". | filed | issue pending (bar 5) |
| B3-I4 | Important | `home/common/agent-skills/tests/test_artifact_budget.py:1606-1614` | The symlinked `plan.tasks` points at an empty directory with no index rows, so a checker that followed the symlink would still refuse (no task member); the case cannot detect a lost `lstat`/`S_ISDIR` guard. | filed | issue pending (bar 5) |
| B3-I5 | Important | `home/common/agent-skills/tests/test_artifact_budget.py:1564-1565` | The `bytes` and `total` rows set `True` against a 4-byte shard, and `True != 4` is refused as a stale value whatever the boolean guard does, so neither row pins the rejection of booleans. | filed | issue pending (bar 5) |
| B4-I1 | Important | `home/common/agent-skills/default.nix:51` | `.agents/bin/artifact-budget` is installed as a wrapper that runs whichever `python3` is first on PATH without `-I`, and review_budget.py invokes it with the inherited environment, so PYTHONPATH can shadow the standard library inside the budget authority that CORE trusts. The open issue 178 already names the wrapper's conversion to a `python3 -I` launcher. | tracked | https://github.com/fagenorn/nix-config/issues/178 |
| B5-I1 | Important | `home/common/agent-skills/skills/sdd/final-review.md:15` | The last `sdd-gate next` already publishes the package for DELIVERY_BASE..DELIVERY_HEAD, and the First pass text tells the controller to run `review-package` on the same range, which publish refuses with exit 2; the same collision occurs when both fix-wave axes package FIX_BASE..HEAD. test_workflow_skill_contracts.py pins this argv. | filed | issue pending (bar 3) |
| B5-I2 | Important | `home/common/agent-skills/skills/sdd/SKILL.md:81-82` | On generator exit 3 the text says to record and return the `decompose_required` report, which is a producer report; the caller accepts only an object that passes `validate-report --boundary sdd`, which rejects a producer report. | filed | issue pending (bar 3) |
| B5-I3 | Important | `home/common/agent-skills/skills/sdd/SKILL.md:250-252` | The Finish step names detail mode only as "issue/branch/run/head identity"; the CLI needs `--detail-input`, `--producer`, `--issue`, `--branch`, `--run-id` and `--head`, no skill text names them, and a wrong invocation prints only `invalid invocation`. | filed | issue pending (bar 3) |
| B5-I4 | Important | `home/common/agent-skills/skills/sdd/SKILL.md:274` | A `present` or `unpublished` SDD report must carry `report_path` inside `notes`; the sdd text states that only partly for `unpublished` and not for `present`, so a report written as the text says is refused as "invalid SDD report". | filed | issue pending (bar 3) |
| B5-I5 | Important | `home/common/agent-skills/tests/test_workflow_skill_contracts.py:1285-1287` | `test_durable_review_detail_precedes_every_removable_cleanup` asserts only that `.superpowers/issue-delivery/` appears in the text, so it passes if workspace deletion is moved ahead of publication. | filed | issue pending (bar 5) |
| B1-M1 | Minor | `python/agent_tools/review_git.py:142` | `fields[0] in ordered` is a linear search inside a traversal over the full ancestry, so cost grows with the square of history size. | recorded | — |
| B1-M2 | Minor | `python/agent_tools/review_publish.py:323` | Two checks compare `fstat` of a held descriptor with an identity captured from that same descriptor (also line 86), so they can never fail. | recorded | — |
| B1-M3 | Minor | `python/agent_tools/review_git.py:72` | `_guard` duplicates `_guard_stepwise`, so the two copies must be kept in sync by hand. | recorded | — |
| B1-M4 | Minor | `python/agent_tools/review_publish.py:531` | `^{object}` accepts a tree or blob as `--head`, and the result names the package `sdd-<head>.json`. | recorded | — |
| B1-M5 | Minor | `python/agent_tools/review_publish.py:383` | `_ensure_ignore` reopens `.superpowers/issue-delivery` by path, which follows an intermediate symlink swapped in after the no-follow chain was checked. | recorded | — |
| B2-M1 | Minor | `python/agent_tools/review_projection.py:155` | No test reaches "completed deletion is not proven absent"; only the positive candidate-tree case pins CR-001. | recorded | — |
| B2-M2 | Minor | `python/agent_tools/review_projection.py:115` | Subject decoding and the package-name check repeat code in review_actual.py, and `tree_entry` copies `_blob_at` and has drifted from it. | recorded | — |
| B2-M3 | Minor | `python/agent_tools/review_projection.py:218` | `_prerequisite` rebuilds the full ownership once per candidate boundary, giving O(boundaries x commits) Git subprocesses. | recorded | — |
| B2-M4 | Minor | `python/agent_tools/review_feasibility.py:50` | A RecursionError from `strict_json` on deeply nested input is not caught, so `validate-result` exits 1 with a traceback instead of 2. | recorded | — |
| B3-M1 | Minor | `home/common/agent-skills/scripts/artifact_budget.py:806-819` | `validate_producer_report` accepts `complete` and `within_budget` with metrics above the loaded policy limits; only `sdd_gate`'s separate `budget-check` catches this. | recorded | — |
| B4-M1 | Minor | `tests/test_agent_tools_launchers.py:437` | The local `wire()` is byte-for-byte the module-level `canonical()` at line 74, two spellings of one encoding. | recorded | — |
| B5-M1 | Minor | `home/common/agent-skills/tests/test_workflow_skill_contracts.py:1258-1263` | Substring checks for the SDD report fields never compare the field list with `validate_sdd_report`'s keys, so an extra or renamed field passes. | recorded | — |
| B5-M2 | Minor | `home/common/agent-skills/skills/sdd/SKILL.md:73-74` | Step 3 names `artifact-budget check --kind review-package` without the required `--root` and `--format json`. | recorded | — |
| B5-M3 | Minor | `home/common/agent-skills/skills/sdd/SKILL.md:86` | The failed candidate omits that `base_sha` and `head_sha` must be null and `verification_state` `not_run` when both axes are `not_run`. | recorded | — |
