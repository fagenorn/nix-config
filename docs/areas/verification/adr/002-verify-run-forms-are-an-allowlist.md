# ADR-verification-002 — A verify block runs only a contract command, a committed script or a built-in probe

- **Status:** accepted
- **Decided in:** issue 625

## Context

A verify block lives in a hold comment that a runner executes later, unattended, on a host. The history study behind issue 625 found holds that could never run or that carried code the runner should not trust. The lint cannot tell safe arguments of a general tool such as `git`, `python3`, `nix`, `gh` or `curl` from code-carrying ones: a declared argv is often a `just` recipe, which pastes its parameters into shell lines unquoted and runs a surplus argument as another recipe.

## Decision

The run forms are a closed allowlist of three: `{"command"}` runs a command id declared in `bindings.commands` with its declared argv and nothing else, `{"script"}` runs a file committed with mode `100755` at an exact path of the repository, and `{"probe"}` runs a built-in read-only probe by name. Any other shape is refused `run_form`, and inline code or an appended argument to a declared command is refused `inline_code`. A block therefore trusts only installed or committed code, never code in the comment. A reference the lint cannot confirm is refused, never accepted.

## Consequences

- A check that needs a tool outside the three forms must be committed as a script (or become a probe) before it can be held; the block cannot name the tool.
- A new probe is a code change to `verify-pending` with its own closed parameter set, not a field a block can invent.
- The lint stays read-only and decidable: it refuses what it cannot prove, so some safe blocks are rejected until their reference is committed.
