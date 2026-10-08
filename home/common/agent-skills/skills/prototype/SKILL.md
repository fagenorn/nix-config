---
name: prototype
description: Builds throwaway code answering one design question, as a terminal app for logic or several UI variations on one route. Use for "prototype this".
---

# Prototype

A prototype is **throwaway code that answers a question**; the question decides its shape.

## 1. Pin the question, read-only

Settle which question the prototype answers (from the prompt, a read-only look at the code, or by asking a present user) before creating anything. No worktree, branch or file yet: the question names the worktree, and a question that turns out pre-answered needs none.

## 2. Start in a fresh worktree

Invoke the `worktrees` skill (or run `git worktree add` if it is unavailable) and name the worktree after the question, e.g. `prototype-billing-state-machine`. Outside a git repo, use a clearly named scratch directory outside the source tree. Reuse a worktree that already exists for this prototype; never nest worktrees.

## 3. Pick the branch

- **"Does this logic or state model feel right?"** → [LOGIC.md](LOGIC.md): a tiny interactive terminal app that drives the state model through hard cases.
- **"What should this look like?"** → [UI.md](UI.md): several radically different variants on one route, switched by a URL search param and a floating bar.

If the question is ambiguous and the user is away, pick by the surrounding code (backend module → logic; page or component → UI) and state the assumption at the top of the prototype.

## Rules for both

1. **Marked throwaway.** Place the code near where it would be used, named so a reader sees it is a prototype; UI routes follow the project's routing convention.
2. **One command to run**, through the project's existing task runner (`pnpm <name>`, `python <path>`, ...).
3. **No persistence by default.** State lives in memory unless persistence is the question; then use a scratch DB or file named "PROTOTYPE — wipe me".
4. **No polish.** No tests, no error handling beyond what keeps it runnable, no abstractions.
5. **Surface the state** after every action (logic) or variant switch (UI).
6. **Delete or absorb.** When the question is answered, drop the worktree, or capture the validated decision durably and re-implement it properly on a real branch. The prototype worktree is never merged or promoted.

## When done

Only the answer survives. Record it with its question outside the worktree (ADR, issue comment, the spec's decision ledger, or a commit message on the real branch). If the user is away, leave a `NOTES.md` placeholder in the worktree for the verdict before it is dropped.
