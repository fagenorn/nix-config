# Review-package Publication Identity Implementation Plan

> **For agentic workers:** execute this plan with the `sdd` skill — one implementer
> per task, reviewed between tasks. Steps use `- [ ]` checkboxes.

**Goal:** Reject replaced review-package member directories on Linux and Darwin while preserving every competitor entry and the existing publication contract.

**Architecture:** First commit a test-only contract that keeps the original replacement assertion, records the two directory identities, and demonstrates the redirected-cleanup defect without relying on allocator behavior. After independent review, the issue owner publishes that exact diagnostic head through the existing advisory Ubuntu workflow; only evidence that confirms or revises the diagnosed mechanism may unlock a fresh implementer. The implementation then retains a no-follow member-directory descriptor through linking, verification, cleanup, and release, while named checks continue to detect replacement.

**Tech stack:** Python 3 standard library (`os`, `pathlib`, `stat`, `unittest.mock`), unittest, just, Nix, and the existing GitHub Actions advisory workflow.

## Global Constraints

- Keep the `publish_package(stage_root, final_root, before_mutation=None, *, final_parent_fd=None, verify_final_parent=None) -> None` interface, CLI output, producer report, callback labels, manifest-last ordering, artifact caps, complete changed-file coverage, no-follow parent semantics, and exclusive hard-link publication unchanged (D1, D2, D5).
- Acquire and retain the created member directory with `O_DIRECTORY | O_NOFOLLOW`; no member callback may run before descriptor identity, directory type, and the current named entry agree. Uncertain acquisition leaves the directory alone (D1, D3).
- Link, stat, and unlink member leaf names relative to the retained descriptor. Named checks still detect replacement, and cleanup never inspects or removes entries reached through a replacement path (D2, D3).
- Attempt release of every descriptor owned by `publish_package`, never close the borrowed final-parent descriptor, never retry a failed close, preserve the original publication failure, and report a post-publication release failure without deleting the completed package (D3).
- Describe the guarantee as a verified descriptor lifetime with observational checks. Do not claim atomic mkdir/open provenance, conditional unlink, immutable completed packages, or arbitrary same-user concurrency safety (D4).
- Preserve the three original issue-37 Ubuntu failures as historical evidence. Use the existing `.github/workflows/ci.yaml` `workflow_dispatch` path for new issue-160 evidence; do not edit workflow/protection files or create a Linux service (D6).
- Use no new dependency. Keep commits signed and append `Co-Authored-By: Codex <noreply@openai.com>`.

## Test seams

- `publish_package` plus `before_mutation` is the mutation and cleanup seam. Assert errors, bytes, entries, descriptor usability, and cwd restoration; do not assert private-helper calls.
- A narrow wrapper around real `os.link`, `os.open`, `os.fstat`, or `os.close` may move entries or inject an error at the syscall boundary while delegating every unaffected operation.
- `home/common/agent-skills/tests/test_review_package.py` remains the portable behavior/CLI seam; the full `just agent-workflow-tests` run preserves collision, cap, coverage, no-follow, report, and exclusive-publication behavior.
- The existing Ubuntu `Agent Workflow Tests (advisory)` job is the Linux evidence seam. Its raw suite outcome, exact checkout head, runner context, and bounded identity diagnostic must agree; a green job with a failed raw suite is still a failure (D6).

## Delivery estimate and boundaries

Estimate: two changed files and 220–360 added or changed lines. Task 1 changes only the test file and deliberately commits a portable red regression against the original producer; it is an independently reviewable evidence checkpoint and must not merge alone. Task 2 changes the producer and extends the same test file, then delivers the green behavior. The main aggregate-growth risk is repeated fixture setup, so Task 1 introduces one focused fixture helper reused by Task 2.

The Darwin baseline at `4ec9cd53ffcbbc5e7385efa1fec01be8bca352ec` is `just build` exit 0 and 836 passing ordinary tests in 165.405 seconds. Final acceptance requires the expanded suite on Darwin and the raw ordinary suite on an actual Ubuntu advisory run. Terra implements each task with a fresh owner for Task 2; Astra independently reviews the diagnostic commit before publication and the final acquisition/mutation/cleanup/release boundary before the final Ubuntu run.

## Task index

Task 1 — Commit the bounded diagnostic contract — `home/common/agent-skills/tests/test_review_package.py` — full — [task-1.md](2026-09-20-issue-160-review-publication-identity.tasks/task-1.md)

Task 2 — Retain publication identity and close every owned lifetime — `home/common/agent-skills/skills/sdd/scripts/review-package`, `home/common/agent-skills/tests/test_review_package.py` — full — [task-2.md](2026-09-20-issue-160-review-publication-identity.tasks/task-2.md)

## Decisions

The design specification owns the issue ledger. This plan applies D1–D6. In particular, Task 1 is the D6 Linux evidence gate, and Task 2 implements the D1–D4 lifetime while testing only the D5 seams. No new non-obvious design decision was required during planning.

---
